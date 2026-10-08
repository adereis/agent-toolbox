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
import threading
import time
import uuid
from collections import defaultdict
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
    if seal.judge_of(plan) in board.acting(plan, n):
        seal.stage_for_judge(root, plan, n)
    return source


def _promote(root, plan, n):
    """Publish round `n`, then file a judge's post as the judgment it is."""
    published = board.promote(root, n)
    seal.file_judgment(root, plan, n)
    return published


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
    if mode not in ("start", "resume"):
        # A fork continues another session's history, so it must pin to the
        # version that session was served, which lives in the parent seat's
        # state, not this one's. Nothing forks through here yet; refusing
        # keeps the first caller from getting an unpinned seat by accident.
        raise ValueError(f"launch drives start and resume turns, not {mode!r}; a fork "
                         "must pin to its parent session's served model")
    harness = harnesses.get(seat["harness"])
    pinned = read(state_path(root, name)).get("model_served") if mode != "start" else None
    if pinned == seat["model"]:
        pinned = None  # the plan already names the exact version
    if pinned:
        # A family such as `opus` means whatever is newest when the CLI
        # runs; a resumed session must keep the version it began on, so a
        # release between rounds cannot switch the seat's model.
        seat = {**seat, "model_pinned": pinned}
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
    timed_out = False
    try:
        # Inside the try, so a refused seat still has its tier's staging
        # undone; before the clock, because no turn has started yet.
        checked = harness.preflight(seat, argv, launched, home)
        started = time.time()
        with (record / "events.jsonl").open("xb") as out, (record / "stderr.log").open("xb") as err:
            try:
                proc = subprocess.Popen(launched.argv, stdin=subprocess.PIPE, stdout=out,
                                        stderr=err, cwd=launched.cwd, env=launched.env,
                                        start_new_session=True, pass_fds=launched.pass_fds)
            finally:
                launched.release()
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
    if seat["visibility"] == "sealed" and not launched.attestation.get("enforced"):
        # Only the jail keeps the run directory out of reach; anywhere else
        # the judge's blindness rests on it not looking.
        flags.append("judging is advisory: nothing stopped the judge from opening the run "
                     "directory, where the key sits beside the letters")
    bus = launched.attestation.get("session_bus")
    if bus:
        flags.append("session bus proxied into the jail for " + ", ".join(bus["names"])
                     + ": the operator's login keyring is readable by the seat")
    if not intact:
        flags.append("the seat's materials changed during the turn")
    if seat.get("tools_relaxed"):
        widened = seat["tools_relaxed"]
        flags.append(f"tools widened from {widened['requested']!r} to {widened['used']!r}: "
                     + widened["why"])
    if seat.get("grants"):
        flags.append("granted on purpose: " + ", ".join(seat["grants"]))
    if seat.get("args"):
        flags.append("extra harness arguments: " + " ".join(seat["args"]))
    if seat.get("env"):
        flags.append("environment passed through: " + ", ".join(seat["env"]))
    flags += checked.pop("red_flags", [])
    write(record / "receipt.json", {
        **got, **checked, "status": status, "exit_code": code, "seconds": seconds,
        "timed_out": timed_out,
        "error": detail, "isolation": launched.attestation, "compaction_markers": compacted,
        "compaction_observed": bool(compacted), "quota_stop": stop["phase"] if stop else None,
        "quota_scope": stop.get("scope") if stop else None,
        "quota_resets_at": stop.get("resets_at") if stop else None,
        "inputs_intact": intact, "red_flags": flags,
        **({"model_pinned": pinned} if pinned else {}),
    })
    if compacted:
        event(root, round=n, seat=name, event="compacted", markers=len(compacted))
    state = read(state_path(root, name))
    if got.get("session_id"):
        state["session_id"] = got["session_id"]
    elif stop and stop.get("session_id") and stop["phase"] == "interrupted":
        state["session_id"] = stop["session_id"]
    # The version a session began on is recorded from its first turn that
    # shows one, answered or not. A turn a quota cut partway has already
    # written that model's reasoning into the session, and its continuation
    # must resume on the same version rather than on whatever the family
    # alias means by then. A served id that does not match the seat's model
    # is not adopted: pinning to it would enshrine the mismatch.
    served = got.get("model") or harness.served_model(record)
    if (served and state.get("session_id") and not state.get("model_served")
            and harnesses.model_matches(seat["model"], served)):
        state["model_served"] = served
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
        jobs = jobs or plan.get("jobs") or 1
        # Concurrency is capped per harness, not only overall: seats sharing
        # one account meet the same quota wall together, while seats on
        # different harnesses are independent and should not wait for it.
        per_harness = plan.get("per_harness") or 1
        gates = defaultdict(lambda: threading.Semaphore(max(1, per_harness)))
        event(root, round=n, event="round-opened", jobs=jobs, per_harness=per_harness)
        open_round(root, plan, n)
        speaking = board.acting(plan, n)
        for seat in plan["seats"]:
            if seat["id"] not in speaking:
                event(root, round=n, seat=seat["id"], event="resting")
        results = {}

        def task(seat):
            try:
                with gates[seat["harness"]]:
                    return seat["id"], run_seat(root, plan, seat, n, timeout=timeout)
            except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
                event(root, round=n, seat=seat["id"], event="stopped", error=str(exc))
                return seat["id"], f"stopped: {exc}"

        # One worker per speaking seat, because a seat waiting on its harness
        # gate holds its thread. Sizing the pool by `jobs` lets the seats
        # submitted first fill it and block, leaving a seat of another
        # harness queued behind a gate it never contends for. The gates are
        # what limit concurrency; the pool only has to not get in their way.
        acting = [s for s in plan["seats"] if s["id"] in speaking]
        with ThreadPoolExecutor(max_workers=max(1, len(acting))) as pool:
            futures = [pool.submit(task, s) for s in acting]
            for future in futures:
                name, outcome = future.result()
                results[name] = outcome
        held = sorted(k for k, v in results.items() if v == "quota")
        if held:
            event(root, round=n, event="round-held", waiting_on=held)
            results["_board"] = {"held": held}
            return results
        results["_board"] = _promote(root, plan, n)
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
        return _promote(root, plan, n)


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
        return _promote(root, plan, n)


def _spans(numbers):
    """[1, 2, 3, 5] -> "1-3, 5", because a Python list repr is not a notation."""
    spans = []
    for n in sorted(numbers):
        if spans and n == spans[-1][1] + 1:
            spans[-1][1] = n
        else:
            spans.append([n, n])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in spans)


def next_step(root, plan, *, published, budget, held, withheld, converged):
    """The one command to type next.

    Every other verb ends by naming the verb that follows it; status read
    the state and stopped, so a prepared run and a finished one ended the
    same way and neither told the operator what to do. The branches mirror
    `run`'s stop rule and `seal.guard`'s wording, so a reader is never sent
    to a command the engine would refuse.
    """
    name = plan["name"]
    if held:
        waiting = held[0].get("waiting_on") or []
        first = waiting[0] if waiting else "SEAT"
        more = f" (and {len(waiting) - 1} more)" if len(waiting) > 1 else ""
        return (f"convene continue {name} {first}{more} once the window resets, "
                f"then convene promote {name} {held[0].get('round')}")
    if withheld:
        n = seal.pending(root, plan)[-1]
        rules = seal.judge_round(root, plan, n)
        if rules and rules not in published:
            # A judge seat rules before anybody reads the letters, so the
            # next step is its round, not `seal`.
            return f"convene run {name}; the judge {seal.judge_of(plan)} reads round {n} sealed next"
        judgment = Path(root) / "sealed" / f"r{n:03d}" / seal.JUDGMENT
        if judgment.exists():
            by = seal.judged_by(root, plan, n)["seat"]
            return f"convene unseal {name}; the judgment by {by} is on file at {judgment}"
        if not seal.is_sealed(root, n):
            return f"convene seal {name}"
        return (f"read {root}/sealed/r{n:03d}/, write its {seal.JUDGMENT}, "
                f"then convene unseal {name}")
    if len(published) < budget and not converged:
        return f"convene run {name}"
    if converged and len(published) < budget:
        # `run` would play one more round and stop again if the signal holds,
        # so say both halves: the room thinks it is done, and going past
        # that is the operator's call, usually made by extending the budget.
        return (f"convene board {name}, then convene export {name} DIR; the run "
                f"converged, and convene run {name} plays past it")
    return f"convene board {name}, then convene export {name} DIR"


def status(root):
    """A read-only view, safe while a run is in progress."""
    root, plan = runs.load(root, verify=False)
    withheld = seal.withheld(root, plan)
    budget = board.budget(root, plan)
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
        # The rounds this seat speaks in. It listens through the others, so
        # they are not turns it owes, and counting them would report a
        # phase seat as permanently behind. Read over the budget rather than
        # the declared count so an extended run counts its own rounds.
        acting = [n for n in range(1, budget + 1) if seat["id"] in board.acting(plan, n)]
        seats[seat["id"]] = {
            "label": board.label(seat), "harness": seat["harness"], "model": seat["model"],
            "model_requested": seat.get("model_requested"),
            "effort": seat["effort"], "tools": seat["tools"], "isolation": seat["isolation"],
            "workspace": seat["workspace"], "status": state.get("status"),
            "session_id": state.get("session_id"), "receipts": receipts,
            "attempts": state.get("attempts", []), "acting_rounds": acting,
            # A seat whose first answered round is not the first round it was
            # expected in heard the room before it spoke.
            "joined_late": answered[0] if answered and answered[0] != (acting[0] if acting else 1)
            else None,
        }
    rows = trail(root)
    published = board.published_rounds(root)
    convergence = [read(root / "board" / "rounds" / f"r{n:03d}" / "convergence.json")
                   for n in published if (root / "board" / "rounds" / f"r{n:03d}" / "convergence.json").exists()]
    signals = [{k: c[k] for k in ("round", "novelty", "closing", "converged", "reason")}
               for c in convergence]
    spoken = sorted(int(p.stem[1:]) for p in (root / "chair").glob("r[0-9][0-9][0-9].md"))
    held = [r for r in rows if r.get("event") == "round-held"]
    still_held = held[-1:] if held and held[-1].get("round") not in published else []
    # A phased run is not asked whether it converged, so its measured signal
    # must not be allowed to end the run early here either. Only the latest
    # round counts, as it does for `run`: a room that converged at round five
    # and was extended and played past it has not converged at round seven
    # unless its latest signal says so again.
    unphased = len(plan["phases"]) == 1 and not plan["phases"][0].get("seats")
    converged = unphased and bool(signals) and signals[-1]["converged"]
    flags = sum(len(got.get("red_flags") or [])
                for one in seats.values() for got in one["receipts"].values())
    return {"run": str(root), "name": plan["name"], "title": plan["title"], "kind": plan["kind"],
            "sealed": seal.sealed_rounds(root), "withheld": withheld,
            "rounds": budget, "declared_rounds": plan["rounds"],
            "phases": plan["phases"], "published_rounds": published, "held": still_held,
            "convergence": signals, "converged": converged, "red_flags": flags,
            "chair": {"delivered": [r for r in spoken if r in published],
                      "queued": [r for r in spoken if r not in published]},
            "seats": seats, "last_events": rows[-8:],
            "next": next_step(root, plan, published=published, budget=budget, held=still_held,
                              withheld=withheld, converged=converged)}


def _turn_line(n, got):
    """One round's receipt, leaving absent fields out rather than printing them.

    A missing tool count used to render as the Python `None` and a withheld
    duration as `withhelds`, and both appear exactly when a turn failed or a
    round is blind, which is the worst moment to hand the reader a repr.
    """
    bits = [got.get("status") or "unknown"]
    if got.get("model"):
        bits.append(f"served {got['model']}")
    seconds = got.get("seconds")
    if seconds == "withheld":
        bits.append("duration withheld")
    elif seconds is not None:
        bits.append(f"{seconds:.1f}s")
    calls = got.get("tool_calls")
    if calls == "withheld":
        bits.append("tool calls withheld")
    elif calls is not None:
        bits.append(f"{calls} tool calls")
    if got.get("tier"):
        bits.append(f"tier {got['tier']}")
    return f"    r{n:03d}: " + ", ".join(bits)


def _seat_line(name, seat):
    """A seat's record across the run, not just how its last turn ended.

    The seat state file keeps one `status`, overwritten every turn, so a
    seat that answered three rounds and failed the fourth used to read
    `status=failed`, which looks like a verdict on the seat.
    """
    receipts = seat["receipts"]
    expected = len(seat["acting_rounds"]) or len(receipts)
    done = sum(1 for got in receipts.values() if got.get("status") == "answered")
    trouble = [f"r{n:03d} {got.get('status')}" for n, got in sorted(receipts.items())
               if got.get("status") != "answered"]
    if not receipts:
        summary = f"not started, {expected} round" + ("" if expected == 1 else "s") + " to speak in"
    else:
        summary = f"answered {done} of {expected} round" + ("" if expected == 1 else "s")
        if trouble:
            summary += ", " + ", ".join(trouble)
    if seat.get("joined_late"):
        summary += f", JOINED LATE in round {seat['joined_late']}"
    return f"- {name} ({seat['label']}): {summary}"


def _resets_at(data, n, waiting):
    """The soonest quota reset among the seats holding round `n` open."""
    times = sorted({t for s in waiting
                    for t in [data["seats"].get(s, {}).get("receipts", {})
                              .get(n, {}).get("quota_resets_at")] if t})
    return times[0] if times else None


def render_status(data):
    published, budget = data["published_rounds"], data["rounds"]
    rounds = f"  rounds: {len(published)} of {budget} published"
    if published:
        rounds += f" ({_spans(published)})"
    if budget != data["declared_rounds"]:
        rounds += f"; budget raised from the {data['declared_rounds']} declared"
    lines = [f"{data['title']}  [{data['kind']}, {data['name']}]", f"  {data['run']}", rounds]
    if len(data["phases"]) > 1 or data["phases"][0].get("seats"):
        lines.append("  phases: " + ", ".join(f"{p['name']} x{p['rounds']}"
                                              + (f" [{', '.join(p['seats'])}]" if p.get("seats") else "")
                                              for p in data["phases"]))
    if len(data["convergence"]) > 1:
        # Novelty is the room's own stop rule. Printing it only once it has
        # fired hides the approach, which is the part worth watching. A lone
        # round is left out: with nothing to differ from it is always 100%.
        measured = ", ".join(f"r{s['round']:03d} {s['novelty'] or 0:.0f}%"
                             for s in data["convergence"])
        fired = next((f"  (converged at round {s['round']} on {s['reason']})"
                      for s in data["convergence"] if s["converged"]), "")
        lines.append(f"  novelty: {measured}{fired}")
    if data["red_flags"]:
        lines.append(f"  red flags: {data['red_flags']} (marked ! below)")
    if data["held"]:
        waiting = data["held"][0].get("waiting_on", [])
        number = data["held"][0].get("round")
        when = _resets_at(data, number, waiting)
        lines.append(f"  HELD: round {number} waiting on {', '.join(waiting)} "
                     f"(provider quota{f'; resets {when}' if when else ''})")
    if data["withheld"]:
        lines.append(f"  blind: round {_spans(data['withheld'])} is read sealed; "
                     + ("sealed so far: " + ", ".join(f"r{n:03d}" for n in data["sealed"])
                        if data["sealed"] else "no drafts lettered yet"))
    if data["chair"]["queued"]:
        lines.append("  chair note queued for round " + ", ".join(str(r) for r in data["chair"]["queued"]))
    for name, seat in data["seats"].items():
        lines.append(_seat_line(name, seat))
        lines.append(f"    {seat['harness']}/{harnesses.model_text(seat)} effort={seat['effort']} "
                     f"tools={seat['tools']} isolation={seat['isolation']} "
                     f"workspace={seat['workspace']}")
        for n, got in sorted(seat["receipts"].items()):
            lines.append(_turn_line(n, got))
            if got.get("error"):
                lines.append(f"      error: {got['error'][:200]}")
            for flag in got.get("red_flags") or []:
                lines.append(f"      ! {flag}")
    lines.append(f"next: {data['next']}")
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
    """Remove the run's seat repositories and private homes, keeping every record.

    A private home is the harness's own state, bound over the real one so a
    seat cannot reach the operator's; it is large and nothing else collects
    it. A seat's repository is a clone of the operator's, and its work is
    already captured as changes.patch. Neither is evidence: the receipts
    beside them already hold what was read from them. A seat still running is never pruned; a machine that cannot say
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
