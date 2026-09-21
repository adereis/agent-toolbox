"""Running one turn per acting seat and closing the round.

Every launch, however it ends, banks the same records: the prompt, the
launch (argv, wrapper, tier attestation, environment names), the event
stream, stderr and a receipt. A quota stop is classified rather than
filed as a failure, and it holds the round open instead of publishing an
absence: a published board is never rewritten.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from convene import (board, harnesses, isolation, observe, platform, quota, runs, seal,
                     sessions, workspace)
from convene.storage import digest, event, hashes, lock, read, trail, write, write_text


def state_path(root, seat):
    return Path(root) / "records" / seat / "state.json"


def seat_named(plan, value):
    for seat in plan["seats"]:
        if seat["id"] == value:
            return seat
    raise ValueError(f"no seat {value!r}; seats: {', '.join(s['id'] for s in plan['seats'])}")


def turn_prompt(root, plan, seat, n, *, cold=False):
    """What a seat is told when the run moves.

    Round one delivers the standing assignment whole. Later rounds send one
    line: everything standing is already in the session, so repeating it
    would buy nothing and cost tokens on every seat. A cold seat (no
    session at round > 1) gets the assignment again and is told to read the
    boards it missed.
    """
    name = seat["id"]
    phase = board.phase_for(plan, n)
    start = (Path(root) / "work" / name / "START.md").read_text(encoding="utf-8")
    first = next((r for r in range(1, n + 1) if name in board.acting(plan, r)), n)
    if n == 1:
        text = start + "\nNobody has posted yet. Post now."
    elif n == first and not cold:
        # The seat's first scheduled turn: a synthesizer, or a seat a phase
        # kept quiet until now. It has the assignment and, when it sees the
        # board, the rounds so far.
        text = start + ("\nThe others have posted; the latest board is "
                        f"board/round-{n - 1:03d}/digest.md and earlier rounds are beside it. "
                        "Read them, then post." if seat["visibility"] == "board"
                        else "\nPost now.")
    elif cold:
        text = (start + "\nYou are joining a room already in progress. Read the boards under "
                f"board/, beginning with board/round-{n - 1:03d}/digest.md, then post as the "
                "others do. Answer your colleagues by name. You were expected earlier and could "
                "not be reached, so nothing the room has said is a reply to you.")
    elif seat["visibility"] != "board":
        text = "Post again. You do not see the others' posts; continue from your own."
    elif board.others_spoke(root, plan, name, n - 1):
        text = (f"The board has moved: board/round-{n - 1:03d}/digest.md. Read it and post "
                "again. Answer your colleagues by name.")
    else:
        heard = board.last_heard(root, plan, name, n - 1)
        text = ("Nobody else has posted since"
                + (f" round {heard}: board/round-{heard:03d}/digest.md." if heard
                   else " the room opened.")
                + " Post again. Anything you asked them is still outstanding, not declined.")
    missed = [r for r in range(first, n) if name not in board.acting(plan, r)]
    if missed and n > first and not cold and seat["visibility"] == "board":
        text += (f" You did not post in round{'s' if len(missed) > 1 else ''} "
                 f"{', '.join(str(r) for r in missed)}; those boards are under board/ and are "
                 "worth reading first.")
    made = board.deliverable(plan, n)
    words = phase.get("length", plan["post_length"])
    if made:
        text += (f" Write the work itself to outbox/{made}, as finished text and nothing else, "
                 f"about {words} words. Your post is your note to the room about it, about "
                 f"{plan['post_length']} words.")
    elif words != plan["post_length"]:
        text += f" About {words} words this time."
    instruction = (phase.get("instruction") or "").strip()
    if instruction:
        text += " " + instruction
    note = board.chair_note(root, n)
    if note:
        text += f"\n\nFrom the chair, to everyone acting this round:\n\n{note}"
    return text + "\n"


def open_round(root, plan, n):
    """Put the previous digest inside every board seat's workspace, read-only.

    Blind seats are never shown a board; a seat that rests this round still
    receives it, because it will read it when it next acts.
    """
    if n == 1:
        return None
    source = Path(root) / "board" / "rounds" / f"r{n - 1:03d}" / "digest.md"
    if not source.exists():
        raise RuntimeError(f"round {n - 1} has not been promoted; nothing to show")
    for seat in plan["seats"]:
        if seat["visibility"] != "board":
            continue
        target = Path(root) / "work" / seat["id"] / "board" / f"round-{n - 1:03d}"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target / "digest.md")
    event(root, round=n, event="board-published", digest_sha256=digest(source))
    return source


def _terminate(proc):
    for number in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), number)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=20)
            return
        except subprocess.TimeoutExpired:
            continue


def run_seat(root, plan, seat, n, *, timeout=None):
    name = seat["id"]
    work = Path(root) / "work" / name
    state = read(state_path(root, name))
    if str(n) in state["rounds"]:
        return state["rounds"][str(n)]["status"]
    if hashes(work / "materials") != seat["input_hashes"]:
        raise RuntimeError(f"seat materials changed since prepare: {name}")
    if digest(work / "START.md") != seat["start_sha256"]:
        raise RuntimeError(f"standing assignment changed since prepare: {name}")
    resume = state.get("session_id")
    # A seat with no session at round > 1 had an earlier turn that produced
    # nothing at all. Refusing it for the rest of the run costs the seat;
    # so it opens a session now and joins in progress, and `status` reports
    # the round it joined so no reading mistakes a late arrival for an
    # independent opening position.
    first = next((r for r in range(1, n + 1) if name in board.acting(plan, r)), n)
    cold = n > first and not resume
    mode = "resume" if resume else "start"
    return launch(root, plan, seat, n, turn_prompt(root, plan, seat, n, cold=cold), mode, resume,
                  timeout=timeout)


def launch(root, plan, seat, n, prompt, mode, session_id, *, timeout=None):
    """Run one turn and bank what it produced, however it ended."""
    root, name = Path(root), seat["id"]
    harness = harnesses.get(seat["harness"])
    tier = isolation.get(seat["isolation"])
    work, seat_home = root / "work" / name, root / "homes" / name
    record = root / "records" / name / f"r{n:03d}"
    record.mkdir(parents=True, exist_ok=True)
    write_text(record / "prompt.md", prompt)
    requested = session_id if mode != "start" else str(uuid.uuid4())
    argv, payload = harness.command(seat, mode, requested, prompt, work)
    launched = tier.wrap(argv, harness=harness, seat_home=seat_home, workspace=work,
                         project_root=plan["project_root"],
                         repo_ro=seat["workspace"] == "repo-ro")
    # Environment names a plan passes through on purpose, on every tier.
    launched.env.update({k: os.environ[k] for k in seat.get("env") or [] if k in os.environ})
    home = tier.home(harness, seat_home)
    marks = sessions.marks(harness.session_paths(home, session_id)) if session_id else []
    write(record / "launch.json", {
        "mode": mode, "session_requested": requested, "argv": argv,
        "wrapper": launched.argv[: len(launched.argv) - len(argv)],
        "cwd": launched.cwd, "environment": sorted(launched.env),
        "isolation": launched.attestation, "harness_home": str(home),
        "harness_version": harness.version(), "session_marks": marks,
    })
    event(root, round=n, seat=name, event="launching", mode=mode, tier=seat["isolation"])
    started = time.time()
    timed_out = False
    try:
        with (record / "events.jsonl").open("xb") as out, (record / "stderr.log").open("xb") as err:
            proc = subprocess.Popen(launched.argv, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                    cwd=launched.cwd, env=launched.env, start_new_session=True)
            event(root, round=n, seat=name, event="running", pid=proc.pid,
                  process_identity=platform.process_identity(proc.pid))
            try:
                proc.communicate(payload, timeout=timeout)
            except subprocess.TimeoutExpired:
                _terminate(proc)
                proc.communicate()
                timed_out = True
    finally:
        finish = getattr(tier, "finish", None)
        if finish:
            finish(harness, seat_home)
    code, seconds = proc.returncode, round(time.time() - started, 2)
    event(root, round=n, seat=name, event="exited", code=code, seconds=seconds,
          timed_out=timed_out)
    try:
        got = harness.receipt(seat, record, home, expected_session=session_id)
        status, detail = "answered", None
    except (RuntimeError, ValueError, OSError, KeyError) as exc:
        got, status, detail = {}, "failed", str(exc)
    answer = got.pop("answer", "")
    if status == "answered":
        write_text(record / "answer.md", answer if answer.endswith("\n") else answer + "\n")
    compacted = observe.compaction(record / "events.jsonl")
    for path in got.get("native_transcripts", []):
        compacted += observe.compaction(Path(path))
    stop = harness.classify_stop(record) if status == "failed" else None
    if stop:
        status = "quota"
    intact = hashes(work / "materials") == seat["input_hashes"]
    flags = []
    if compacted:
        flags.append("compaction observed: the seat's context was rewritten mid-turn")
    if launched.attestation.get("advisory"):
        flags.append("isolation is advisory (private-home): the OS did not enforce it")
    if launched.attestation.get("tier") == "none":
        flags.append("no isolation: the seat ran in the operator's own harness home")
    if not intact:
        flags.append("the seat's materials changed during the turn")
    if seat.get("grants"):
        flags.append("granted on purpose: " + ", ".join(seat["grants"]))
    if seat.get("args"):
        flags.append("extra harness arguments: " + " ".join(seat["args"]))
    if seat.get("env"):
        flags.append("environment passed through: " + ", ".join(seat["env"]))
    write(record / "receipt.json", {
        **got, "status": status, "exit_code": code, "seconds": seconds, "timed_out": timed_out,
        "error": detail, "isolation": launched.attestation, "compaction_markers": compacted,
        "compaction_observed": bool(compacted), "quota_stop": stop["phase"] if stop else None,
        "quota_scope": stop.get("scope") if stop else None,
        "quota_resets_at": stop.get("resets_at") if stop else None,
        "inputs_intact": intact, "red_flags": flags,
    })
    if compacted:
        event(root, round=n, seat=name, event="compacted", markers=len(compacted))
    state = read(state_path(root, name))
    if got.get("session_id"):
        state["session_id"] = got["session_id"]
    elif stop and stop.get("session_id") and stop["phase"] == "interrupted":
        state["session_id"] = stop["session_id"]
    state["rounds"][str(n)] = {"status": status, "seconds": seconds, "error": detail,
                               **({"quota_stop": stop["phase"], "quota_scope": stop.get("scope")}
                                  if stop else {})}
    state["status"] = status
    write(state_path(root, name), state)
    event(root, round=n, seat=name, event="collected", status=status, error=detail)
    return status


ATTEMPT_FILES = ("events.jsonl", "stderr.log", "prompt.md", "launch.json", "receipt.json")


def continue_seat(root, n, name, *, timeout=None):
    """Take one seat's turn again after a provider limit stopped it.

    Refused: nothing ran, so the native session is rewound to the mark taken
    before submission and the identical prompt is delivered again. With no
    session yet, it is simply launched again. Interrupted: the session holds
    the reasoning, so it is resumed with a task-free continuation note. Any
    other failure is refused here: a crash or a timeout looks identical at
    the command line, and re-running one can duplicate work that happened.
    """
    root, plan = runs.load(root)
    seat = seat_named(plan, name)
    record = root / "records" / name / f"r{n:03d}"
    state = read(state_path(root, name))
    attempt = state.get("rounds", {}).get(str(n))
    if not attempt:
        raise ValueError(f"{name} has no round {n} to continue")
    if attempt["status"] == "answered":
        raise ValueError(f"{name} already answered round {n}")
    if board.post_path(root, name, n).exists():
        raise RuntimeError(f"round {n} is already published for {name}")
    harness = harnesses.get(seat["harness"])
    stop = harness.classify_stop(record)
    if not stop:
        raise RuntimeError(f"{name} does not carry a provider quota stop in round {n}; "
                           "diagnose the failure rather than taking the turn again")
    launch_record = read(record / "launch.json")
    resume = quota.resumable_session(stop)
    if resume:
        prompt, mode, session = quota.continuation(), "resume", resume
    else:
        sessions.rewind(launch_record.get("session_marks") or [])
        prompt = (record / "prompt.md").read_text(encoding="utf-8")
        session = state.get("session_id")
        mode = "resume" if session else "start"
    number = len(list((record / "attempts").glob("[0-9][0-9]"))) + 1
    folder = record / "attempts" / f"{number:02d}"
    folder.mkdir(parents=True)
    for item in ATTEMPT_FILES:
        if (record / item).exists():
            shutil.move(str(record / item), str(folder / item))
    del state["rounds"][str(n)]
    state.setdefault("attempts", []).append({"round": n, "attempt": number,
                                             "quota_stop": stop["phase"],
                                             "quota_scope": stop.get("scope"), "resumed": resume})
    write(state_path(root, name), state)
    event(root, round=n, seat=name, event="continuing", quota_stop=stop["phase"],
          resumed=resume, attempt=number)
    return launch(root, plan, seat, n, prompt, mode, session, timeout=timeout)


def run_round(root, n, *, jobs=None, timeout=None):
    root, plan = runs.load(root)
    with lock(root / "run.lock"):
        allowed = board.budget(root, plan)
        if n < 1 or n > allowed:
            raise ValueError(f"round must be 1..{allowed}; `convene extend` raises the budget")
        if n in board.published_rounds(root):
            raise ValueError(f"round {n} is already published")
        if n > 1 and (n - 1) not in board.published_rounds(root):
            raise ValueError(f"round {n - 1} is not published yet")
        jobs = jobs or plan.get("jobs", 1)
        event(root, round=n, event="round-opened", jobs=jobs)
        open_round(root, plan, n)
        speaking = board.acting(plan, n)
        for seat in plan["seats"]:
            if seat["id"] not in speaking:
                event(root, round=n, seat=seat["id"], event="resting")
        results = {}

        def task(seat):
            try:
                return seat["id"], run_seat(root, plan, seat, n, timeout=timeout)
            except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
                event(root, round=n, seat=seat["id"], event="stopped", error=str(exc))
                return seat["id"], f"stopped: {exc}"

        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            futures = [pool.submit(task, s) for s in plan["seats"] if s["id"] in speaking]
            for future in futures:
                name, outcome = future.result()
                results[name] = outcome
        held = sorted(k for k, v in results.items() if v == "quota")
        if held:
            event(root, round=n, event="round-held", waiting_on=held)
            results["_board"] = {"held": held}
            return results
        results["_board"] = board.promote(root, n)
    return results


def run(root, *, rounds=None, jobs=None, timeout=None):
    """Play rounds until the budget runs out, the room converges, or a hold.

    A run that declared phases is not asked whether it has converged: its
    schedule says how long it runs, and the stop rule cannot tell a room
    that has exhausted the question from a critique phase whose revision
    comes next. The signal is still measured and recorded every round.
    """
    root, plan = runs.load(root)
    played = []
    while True:
        allowed = board.budget(root, plan)
        ceiling = allowed if rounds is None else min(rounds, allowed)
        number = len(board.published_rounds(root)) + 1
        if number > ceiling:
            return played, "done" if number > allowed else "round limit reached"
        outcome = run_round(root, number, jobs=jobs, timeout=timeout)
        played.append((number, outcome))
        if outcome["_board"].get("held"):
            return played, "held on " + ", ".join(outcome["_board"]["held"])
        signal = outcome["_board"]["convergence"]
        if signal["converged"] and len(plan["phases"]) == 1 and not plan["phases"][0].get("seats"):
            return played, f"converged on {signal['reason']}"


def promote_held(root, n):
    """Close a round every seat has now answered or been given up on."""
    root, plan = runs.load(root)
    with lock(root / "run.lock"):
        if n in board.published_rounds(root):
            raise ValueError(f"round {n} is already published")
        waiting = [s["id"] for s in plan["seats"] if s["id"] in board.acting(plan, n)
                   and read(state_path(root, s["id"])).get("rounds", {}).get(str(n), {}).get("status") == "quota"]
        if waiting:
            raise RuntimeError(f"round {n} is still held on {', '.join(waiting)}; continue them "
                               "first, or accept their absence with --absent")
        return board.promote(root, n)


def promote_absent(root, n):
    """Publish a held round with the stopped seats recorded as absent."""
    root, plan = runs.load(root)
    with lock(root / "run.lock"):
        if n in board.published_rounds(root):
            raise ValueError(f"round {n} is already published")
        for seat in plan["seats"]:
            state = read(state_path(root, seat["id"]))
            turn = state.get("rounds", {}).get(str(n))
            if turn and turn["status"] == "quota":
                turn["status"] = "given-up"
                state["status"] = "given-up"
                write(state_path(root, seat["id"]), state)
                event(root, round=n, seat=seat["id"], event="given-up")
        return board.promote(root, n)


def status(root):
    """A read-only view, safe while a run is in progress."""
    root, plan = runs.load(root, verify=False)
    withheld = seal.withheld(root, plan)
    seats = {}
    for seat in plan["seats"]:
        state = read(state_path(root, seat["id"]))
        receipts = {}
        for path in sorted((root / "records" / seat["id"]).glob("r[0-9][0-9][0-9]/receipt.json")):
            got = read(path)
            n = int(path.parent.name[1:])
            receipts[n] = {
                k: got.get(k) for k in ("status", "model", "requested_model", "seconds",
                                        "tool_calls", "red_flags", "error", "quota_stop",
                                        "quota_resets_at", "compaction_observed")}
            receipts[n]["tier"] = (got.get("isolation") or {}).get("tier")
            if n in withheld:
                # Seconds and tool counts are near-unique per seat: printed
                # beside the seat id they are the identity key by arithmetic.
                receipts[n]["seconds"] = receipts[n]["tool_calls"] = "withheld"
        answered = sorted(int(r) for r, v in state.get("rounds", {}).items()
                          if v.get("status") == "answered")
        seats[seat["id"]] = {
            "label": board.label(seat), "harness": seat["harness"], "model": seat["model"],
            "effort": seat["effort"], "tools": seat["tools"], "isolation": seat["isolation"],
            "workspace": seat["workspace"], "status": state.get("status"),
            "session_id": state.get("session_id"), "receipts": receipts,
            "attempts": state.get("attempts", []),
            # A seat whose first answered round is not the first round it was
            # expected in heard the room before it spoke.
            "joined_late": answered[0] if answered and answered[0] != next(
                (r for r in range(1, plan["rounds"] + 1) if seat["id"] in board.acting(plan, r)), 1)
            else None,
        }
    rows = trail(root)
    published = board.published_rounds(root)
    convergence = [read(root / "board" / "rounds" / f"r{n:03d}" / "convergence.json")
                   for n in published if (root / "board" / "rounds" / f"r{n:03d}" / "convergence.json").exists()]
    spoken = sorted(int(p.stem[1:]) for p in (root / "chair").glob("r[0-9][0-9][0-9].md"))
    held = [r for r in rows if r.get("event") == "round-held"]
    still_held = held[-1:] if held and held[-1].get("round") not in published else []
    return {"run": str(root), "name": plan["name"], "title": plan["title"], "kind": plan["kind"],
            "sealed": seal.sealed_rounds(root), "withheld": withheld,
            "rounds": board.budget(root, plan), "declared_rounds": plan["rounds"],
            "phases": plan["phases"], "published_rounds": published, "held": still_held,
            "convergence": [{k: c[k] for k in ("round", "novelty", "closing", "converged", "reason")}
                            for c in convergence],
            "chair": {"delivered": [r for r in spoken if r in published],
                      "queued": [r for r in spoken if r not in published]},
            "seats": seats, "last_events": rows[-8:]}


def render_status(data):
    lines = [f"{data['title']}  [{data['kind']}, {data['name']}]", f"  {data['run']}",
             f"  rounds published: {data['published_rounds'] or 'none'} of {data['rounds']}"
             + (f" (declared {data['declared_rounds']})" if data['rounds'] != data['declared_rounds'] else "")]
    if len(data["phases"]) > 1 or data["phases"][0].get("seats"):
        lines.append("  phases: " + ", ".join(f"{p['name']} x{p['rounds']}"
                                              + (f" [{', '.join(p['seats'])}]" if p.get("seats") else "")
                                              for p in data["phases"]))
    for signal in data["convergence"]:
        if signal["converged"]:
            lines.append(f"  converged at round {signal['round']} on {signal['reason']}")
    if data["held"]:
        lines.append(f"  HELD: round {data['held'][0].get('round')} waiting on "
                     f"{', '.join(data['held'][0].get('waiting_on', []))} (provider quota); "
                     "`convene continue` them when the window resets")
    if data["withheld"]:
        lines.append(f"  blind: rounds {data['withheld']} are read sealed; "
                     + ("sealed so far: " + ", ".join(f"r{n:03d}" for n in data["sealed"])
                        if data["sealed"] else "`convene seal` letters the drafts"))
    if data["chair"]["queued"]:
        lines.append("  chair note queued for round " + ", ".join(str(r) for r in data["chair"]["queued"]))
    for name, seat in data["seats"].items():
        lines.append(f"- {name} ({seat['label']}): {seat['harness']}/{seat['model']} "
                     f"effort={seat['effort']} tools={seat['tools']} isolation={seat['isolation']} "
                     f"status={seat['status']}"
                     + (f" JOINED LATE in round {seat['joined_late']}" if seat.get("joined_late") else ""))
        for n, got in seat["receipts"].items():
            served = got.get("model") or "?"
            lines.append(f"    r{n:03d}: {got['status']}, served {served}, "
                         f"{got.get('seconds')}s, tool calls {got.get('tool_calls')}, "
                         f"tier {got.get('tier')}")
            if got.get("error"):
                lines.append(f"      error: {got['error'][:200]}")
            for flag in got.get("red_flags") or []:
                lines.append(f"      ! {flag}")
    return "\n".join(lines)


def usage(root):
    root, plan = runs.load(root, verify=False)
    out = []
    for seat in plan["seats"]:
        harness = harnesses.get(seat["harness"])
        totals = {k: 0 for k in ("input", "output", "reasoning", "cache_read")}
        cost, priced, turns = 0.0, 0, 0
        for path in sorted((root / "records" / seat["id"]).glob("r[0-9][0-9][0-9]/receipt.json")):
            counted = harness.usage_totals(read(path).get("usage"))
            if not counted:
                continue
            turns += 1
            for key in totals:
                totals[key] += counted[key]
            if counted["cost_usd"] is not None:
                cost, priced = cost + counted["cost_usd"], priced + 1
        out.append({"seat": seat["id"], "harness": seat["harness"], "model": seat["model"],
                    "turns": turns, **totals, "cost_usd": cost if priced else None})
    return out


def prune(root, *, force=False):
    """Remove the run's worktrees and private harness homes, keeping every record.

    A private home is the harness's own state, bound over the real one so a
    seat cannot reach the operator's; it is large and nothing else collects
    it. A worktree is a registration in the operator's repository. Neither
    is evidence: the receipts beside them already hold what was read from
    them. A seat still running is never pruned; a machine that cannot say
    whether one is running keeps everything unless forced.
    """
    root, plan = runs.load(root)
    live = []
    for row in trail(root):
        if row.get("event") == "running" and row.get("pid"):
            try:
                identity = platform.process_identity(row["pid"])
            except RuntimeError as exc:
                if not force:
                    raise RuntimeError(f"{exc}; pass --force after checking by hand") from exc
                identity = None
            if identity is not None and identity == row.get("process_identity"):
                live.append((row.get("seat"), row["pid"]))
    if live:
        raise RuntimeError("seats still running: " + ", ".join(f"{s} (pid {p})" for s, p in live))
    removed = []
    for seat in plan["seats"]:
        tree = root / "work" / seat["id"] / workspace.REPO
        if seat["workspace"] == "worktree" and tree.exists():
            workspace.remove(plan["project_root"], tree)
            removed.append(str(tree))
        home = root / "homes" / seat["id"]
        if home.exists():
            shutil.rmtree(home)
            removed.append(str(home))
    event(root, event="pruned", removed=removed)
    return removed
