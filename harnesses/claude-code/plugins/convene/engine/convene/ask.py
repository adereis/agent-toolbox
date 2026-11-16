"""One question to one seat, and follow-ups on the same session.

An ask is the subagent call of convene. `convene ask codex/sol "..."`
prepares a one-seat run of kind `ask`, plays its round and prints the
answer with its receipt; `convene ask --to RUN "..."` files the next
message as that round's chair note, raises the budget by one and plays
it, so the seat resumes its own native session the way a subagent takes
a follow-up. Everything else a run guarantees holds unchanged: the
frozen plan, the isolation tier, the served model pinned across turns,
the receipts and their red flags.
"""

from __future__ import annotations

from convene import board, harnesses, plan as plan_, round as round_, runs
from convene.storage import lock, read

TITLE_LENGTH = 60


def parse_seat(spec):
    """`codex/sol` -> ("codex", "sol"); a bare harness takes its own default model."""
    harness, slash, model = str(spec).strip().partition("/")
    known = list(harnesses.registry())
    if harness not in known:
        raise ValueError(f"name a seat as HARNESS or HARNESS/MODEL, with HARNESS one of "
                         f"{', '.join(known)}: {spec!r}")
    if slash and not model:
        raise ValueError(f"no model after the slash in {spec!r}")
    # Named explicitly even when it is the harness's default, so a model in
    # the operator's convene.toml, written for another harness, cannot reach
    # this seat: `opus` handed to Codex is refused by its catalog.
    return harness, model or harnesses.get(harness).default_model


def title_of(question):
    line = next((l.strip() for l in question.splitlines() if l.strip()), "")
    return line if len(line) <= TITLE_LENGTH else line[:TITLE_LENGTH - 1].rstrip() + "…"


def start(question, seat_spec, *, project=None, persona=None, tools=None, grants=(),
          workspace=None, effort=None, name=None, timeout=None, environ=None):
    """Prepare an ask and play its first round; returns the run directory."""
    if not str(question).strip():
        raise ValueError("the question is empty")
    harness, model = parse_seat(seat_spec)
    seat = {"id": harness, "persona": persona or plan_.ASK_PERSONA}
    supplied = {"schema": 1, "kind": "ask", "title": title_of(question), "rounds": 1,
                "harness": harness, "model": model, "brief": {"text": question},
                "seats": [seat]}
    for key, value in (("tools", tools), ("effort", effort), ("workspace", workspace)):
        if value is not None:
            supplied[key] = value
    if grants:
        supplied["grants"] = list(grants)
    project_root = runs.project_root(project)
    root, _ = plan_.freeze(supplied, plan_dir=project_root, plan_source="convene ask",
                           project_root=project_root, name=name, environ=environ)
    round_.run_round(root, 1, timeout=timeout)
    return root


def follow_up(root, message, *, timeout=None):
    """File the next message and play its round on the resumed session."""
    if not str(message).strip():
        raise ValueError("the follow-up is empty")
    root, plan = runs.load(root)
    if plan["kind"] != "ask":
        raise ValueError(f"{plan['name']} is a {plan['kind']}, not an ask; a room takes a "
                         "chair note in chair/rNNN.md before its next round")
    runs.require_environment(root, plan)
    with lock(root / "run.lock"):
        published = board.published_rounds(root)
        allowed = board.budget(root, plan)
        if len(published) != allowed:
            # A held round or a follow-up still playing: a second message now
            # would land in a round whose answer nobody has read yet.
            raise RuntimeError(f"{plan['name']} has not answered its last message yet: "
                               f"{round_.status(root)['next']}")
        n = allowed + 1
        note = root / "chair" / f"r{n:03d}.md"
        note.write_text(message.rstrip() + "\n", encoding="utf-8")
        board.extend(root, n)
    round_.run_round(root, n, timeout=timeout)
    return root, n


def result(root, n=None):
    """What the asker reads: the answer, and the receipt it rests on."""
    root, plan = runs.load(root, verify=False)
    seat = plan["seats"][0]
    published = board.published_rounds(root)
    data = round_.status(root)
    n = n or (data["held"][0]["round"] if data["held"] else (published[-1] if published else 1))
    receipt_path = root / "records" / seat["id"] / f"r{n:03d}" / "receipt.json"
    got = read(receipt_path) if receipt_path.exists() else {}
    post = board.post_path(root, seat["id"], n)
    answer = post.read_text(encoding="utf-8") if post.exists() and got.get("status") == "answered" \
        else None
    return {"run": str(root), "name": plan["name"], "round": n, "seat": seat["id"],
            "harness": seat["harness"], "model": harnesses.model_text(seat),
            "persona": board.label(seat), "workspace": seat["workspace"],
            "tools": seat["tools"], "status": got.get("status") or "not run",
            "answer": answer, "served": got.get("model"), "seconds": got.get("seconds"),
            "tool_calls": got.get("tool_calls"),
            "tier": (got.get("isolation") or {}).get("tier"),
            "red_flags": got.get("red_flags") or [], "error": got.get("error"),
            "quota_resets_at": got.get("quota_resets_at"), "next": data["next"]}


def render(data):
    """The answer first, then one receipt line, the red flags and the next step."""
    lines = []
    if data["answer"]:
        lines.append(data["answer"].rstrip())
        lines.append("")
    receipt = [f"{data['harness']}/{data['model']}", data["persona"],
               f"workspace {data['workspace']}", f"tools {data['tools']}"]
    if data["served"]:
        receipt.append(f"served {data['served']}")
    if data["tier"]:
        receipt.append(f"tier {data['tier']}")
    if data["seconds"] is not None:
        receipt.append(f"{data['seconds']:.1f}s")
    if data["tool_calls"] is not None:
        receipt.append(f"{data['tool_calls']} tool calls")
    lines.append(f"--- {data['status']}, round {data['round']} of {data['name']}: "
                 + ", ".join(receipt))
    if data["status"] == "quota":
        lines.append("HELD on a provider quota"
                     + (f"; resets {data['quota_resets_at']}" if data["quota_resets_at"] else ""))
    if data["error"] and data["status"] != "answered":
        lines.append(f"error: {data['error'][:400]}")
    lines += [f"! {flag}" for flag in data["red_flags"]]
    lines.append(f"next: {data['next']}")
    return "\n".join(lines)


def exit_code(data):
    return {"answered": 0, "quota": 3}.get(data["status"], 1)


def read_question(value, stdin):
    """`-` reads the text from standard input, for a question too long for argv."""
    return stdin.read() if value == "-" else value
