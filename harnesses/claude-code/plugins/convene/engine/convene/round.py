"""Running one turn per acting seat and closing the round.

Every launch, however it ends, banks the same records: the prompt, the
launch (argv, wrapper, tier attestation, environment names), the event
stream, stderr and a receipt. A quota stop is classified rather than
filed as a failure, and it holds the round open instead of publishing an
absence: a published board is never rewritten.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from convene import board, harnesses, isolation, observe, platform, runs, sessions
from convene.storage import digest, event, hashes, lock, read, trail, write, write_text


def state_path(root, seat):
    return Path(root) / "records" / seat / "state.json"


def seat_named(plan, value):
    for seat in plan["seats"]:
        if seat["id"] == value:
            return seat
    raise ValueError(f"no seat {value!r}; seats: {', '.join(s['id'] for s in plan['seats'])}")


def turn_prompt(root, plan, seat, n):
    """The standing assignment, delivered whole on the first turn."""
    start = (Path(root) / "work" / seat["id"] / "START.md").read_text(encoding="utf-8")
    return start + "\nNobody has posted yet. Post now.\n"


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
    mode = "resume" if resume else "start"
    return launch(root, plan, seat, n, turn_prompt(root, plan, seat, n), mode, resume,
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


def run_round(root, n, *, jobs=None, timeout=None):
    root, plan = runs.load(root)
    with lock(root / "run.lock"):
        if n < 1 or n > plan["rounds"]:
            raise ValueError(f"round must be 1..{plan['rounds']}")
        if n in board.published_rounds(root):
            raise ValueError(f"round {n} is already published")
        jobs = jobs or plan.get("jobs", 1)
        event(root, round=n, event="round-opened", jobs=jobs)
        speaking = board.acting(plan, n)
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
    root, plan = runs.load(root)
    played = []
    ceiling = plan["rounds"] if rounds is None else min(rounds, plan["rounds"])
    while True:
        number = len(board.published_rounds(root)) + 1
        if number > ceiling:
            return played, "done"
        outcome = run_round(root, number, jobs=jobs, timeout=timeout)
        played.append((number, outcome))
        if outcome["_board"].get("held"):
            return played, "held on " + ", ".join(outcome["_board"]["held"])


def status(root):
    """A read-only view, safe while a run is in progress."""
    root, plan = runs.load(root, verify=False)
    seats = {}
    for seat in plan["seats"]:
        state = read(state_path(root, seat["id"]))
        receipts = {}
        for path in sorted((root / "records" / seat["id"]).glob("r[0-9][0-9][0-9]/receipt.json")):
            got = read(path)
            receipts[int(path.parent.name[1:])] = {
                k: got.get(k) for k in ("status", "model", "requested_model", "seconds",
                                        "tool_calls", "red_flags", "error", "quota_stop",
                                        "quota_resets_at", "compaction_observed")}
            receipts[int(path.parent.name[1:])]["tier"] = (got.get("isolation") or {}).get("tier")
        seats[seat["id"]] = {
            "label": board.label(seat), "harness": seat["harness"], "model": seat["model"],
            "effort": seat["effort"], "tools": seat["tools"], "isolation": seat["isolation"],
            "status": state.get("status"), "session_id": state.get("session_id"),
            "receipts": receipts,
        }
    rows = trail(root)
    return {"run": str(root), "name": plan["name"], "title": plan["title"], "kind": plan["kind"],
            "rounds": plan["rounds"], "published_rounds": board.published_rounds(root),
            "held": [r for r in rows if r.get("event") == "round-held"][-1:],
            "seats": seats, "last_events": rows[-8:]}


def render_status(data):
    lines = [f"{data['title']}  [{data['kind']}, {data['name']}]", f"  {data['run']}",
             f"  rounds published: {data['published_rounds'] or 'none'} of {data['rounds']}"]
    if data["held"]:
        lines.append(f"  HELD: waiting on {', '.join(data['held'][0].get('waiting_on', []))} "
                     "(provider quota); continue them when the window resets")
    for name, seat in data["seats"].items():
        lines.append(f"- {name} ({seat['label']}): {seat['harness']}/{seat['model']} "
                     f"effort={seat['effort']} tools={seat['tools']} isolation={seat['isolation']} "
                     f"status={seat['status']}")
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
