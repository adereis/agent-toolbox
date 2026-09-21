"""The board: the shared, append-only record of promoted posts.

Promotion is the only writer of shared state and runs with every seat
stopped. It copies, hashes and attributes; it never reads a post to decide
whether it belongs. A digest concatenates posts whole and never summarizes:
a controller that compressed four posts into a paragraph would become the
room's narrator.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from convene import runs
from convene.storage import digest, event, write

RULE = "-" * 68


def label(seat):
    return seat["persona"]["profile"]["label"]


def phase_for(plan, n):
    first = 1
    for phase in plan["phases"]:
        if first <= n < first + phase["rounds"]:
            return phase
        first += phase["rounds"]
    return plan["phases"][-1]


def acting(plan, n):
    named = phase_for(plan, n).get("seats")
    every = [s["id"] for s in plan["seats"]]
    return every if not named else [s for s in every if s in named]


def board_order(seats, n):
    """Rotated by round so no seat always anchors the read."""
    names = [s["id"] for s in seats]
    offset = (n - 1) % len(names)
    return names[offset:] + names[:offset]


def post_path(root, seat, n):
    return Path(root) / "board" / "posts" / seat / f"r{n:03d}.md"


def compose_digest(root, plan, n):
    """Round `n`'s posts, attributed by label and seat id, never by model.

    The stored digest is what seats are shown in later rounds; a model name
    on it would have every seat weighing a colleague by its make."""
    labels = {s["id"]: label(s) for s in plan["seats"]}
    research = {s["id"] for s in plan["seats"]
                if s["tools"] == "research" or "web" in (s.get("grants") or [])}
    text = f"# The board -- round {n}\n\n"
    included = {}
    for name in board_order(plan["seats"], n):
        post = post_path(root, name, n)
        if not post.exists():
            continue
        mark = "  [can search the web]" if name in research else ""
        text += f"{RULE}\n## {labels[name]}  ({name}){mark}\n{RULE}\n\n"
        text += post.read_text(encoding="utf-8").strip() + "\n\n"
        included[name] = digest(post)
    absent = [s for s in acting(plan, n) if s not in included]
    if absent:
        text += f"{RULE}\n\nNo post this round from: {', '.join(labels[a] for a in absent)}.\n"
    return text, included, absent


def attributed(text, plan):
    """The board as the operator reads it: each seat named by harness/model."""
    for seat in plan["seats"]:
        text = text.replace(f"({seat['id']})", f"({seat['id']}, {seat['harness']}/{seat['model']})")
    return text


def promote(root, n):
    """Move every answered seat's post onto the board and publish the digest."""
    root, plan = runs.load(root)
    for name in acting(plan, n):
        answer = root / "records" / name / f"r{n:03d}" / "answer.md"
        if not answer.exists() or not answer.read_bytes().strip():
            event(root, round=n, seat=name, event="absent")
            continue
        post = post_path(root, name, n)
        if post.exists():
            raise RuntimeError(f"round {n} already promoted for {name}")
        shutil.copyfile(answer, post)
        event(root, round=n, seat=name, event="promoted", bytes=post.stat().st_size,
              sha256=digest(post))
    text, included, absent = compose_digest(root, plan, n)
    out = root / "board" / "rounds" / f"r{n:03d}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "digest.md").write_text(text, encoding="utf-8")
    write(out / "digest.json", {"round": n, "order": board_order(plan["seats"], n),
                                "posts": included, "absent": absent,
                                "digest_sha256": digest(out / "digest.md")})
    event(root, round=n, event="round-closed", posted=len(included), absent=len(absent))
    return {"posted": sorted(included), "absent": absent}


def published_rounds(root):
    return sorted(int(p.name[1:]) for p in (Path(root) / "board" / "rounds").glob("r[0-9][0-9][0-9]"))


def text(root, plan, *, round_number=None, attribute=True):
    """The board as text: one round, or every published round in order."""
    numbers = published_rounds(root)
    if round_number is not None:
        if round_number not in numbers:
            raise ValueError(f"round {round_number} is not published")
        numbers = [round_number]
    parts = []
    for n in numbers:
        body = (Path(root) / "board" / "rounds" / f"r{n:03d}" / "digest.md").read_text(encoding="utf-8")
        parts.append(attributed(body, plan) if attribute else body)
    return "\n".join(parts)
