"""The board: the shared, append-only record of promoted posts and made files.

Promotion is the only writer of shared state and runs with every seat
stopped. It copies, hashes and attributes; it never reads a post to decide
whether it belongs. A digest concatenates posts whole and never summarizes:
a controller that compressed four posts into a paragraph would become the
room's narrator, and every later round would answer its reading rather than
what the seats wrote.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from convene import runs, workspace
from convene.storage import digest, event, read, write

RULE = "-" * 68
CHANGES = "changes.patch"


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
    """The seats that speak in round `n`. The rest are listening, not absent."""
    named = phase_for(plan, n).get("seats")
    every = [s["id"] for s in plan["seats"]]
    return every if not named else [s for s in every if s in named]


def deliverable(plan, n):
    return phase_for(plan, n).get("deliverable")


def declared_files(plan):
    """Every file any phase asks for: a late correction still has a home."""
    return sorted({p["deliverable"] for p in plan["phases"] if p.get("deliverable")})


def board_order(seats, n):
    """Rotated by round so no seat always anchors the read."""
    names = [s["id"] for s in seats]
    offset = (n - 1) % len(names)
    return names[offset:] + names[:offset]


def post_path(root, seat, n):
    return Path(root) / "board" / "posts" / seat / f"r{n:03d}.md"


def made_path(root, seat, n, name):
    return Path(root) / "board" / "made" / seat / f"r{n:03d}" / name


def chair_note(root, n):
    """What the operator told the room before round `n`, if anything.

    The operator is the only one who sees both the room and the world it
    writes for. The note travels with every acting seat's turn and is copied
    onto the round's digest; it is not a post and the chair takes no seat.
    """
    path = Path(root) / "chair" / f"r{n:03d}.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def spoke(root, plan, n):
    return [name for name in acting(plan, n) if post_path(root, name, n).exists()]


def others_spoke(root, plan, seat, n):
    return bool([name for name in spoke(root, plan, n) if name != seat])


def last_heard(root, plan, seat, n):
    """The latest round up to `n` in which `seat` heard somebody else."""
    return next((r for r in range(n, 0, -1) if others_spoke(root, plan, seat, r)), None)


def compose_digest(root, plan, n):
    """Round `n`'s posts and made files, attributed by label and seat id."""
    labels = {s["id"]: label(s) for s in plan["seats"]}
    research = {s["id"] for s in plan["seats"]
                if s["tools"] == "research" or "web" in (s.get("grants") or [])}
    text = f"# The board -- round {n}\n\n"
    note = chair_note(root, n)
    if note:
        text += f"{RULE}\n## From the chair\n{RULE}\n\n{note}\n\n"
    included, made = {}, {}
    for name in board_order(plan["seats"], n):
        post = post_path(root, name, n)
        if not post.exists():
            continue
        mark = "  [can search the web]" if name in research else ""
        text += f"{RULE}\n## {labels[name]}  ({name}){mark}\n{RULE}\n\n"
        text += post.read_text(encoding="utf-8").strip() + "\n\n"
        included[name] = digest(post)
        folder = Path(root) / "board" / "made" / name / f"r{n:03d}"
        for file in sorted(folder.iterdir()) if folder.is_dir() else []:
            body = file.read_text(encoding="utf-8", errors="replace").strip()
            text += f"### {file.name}\n\n"
            text += (f"```\n{body}\n```\n\n" if file.suffix in (".patch", ".diff") else body + "\n\n")
            made.setdefault(name, {})[file.name] = digest(file)
    absent = [s for s in acting(plan, n) if s not in included]
    if absent:
        text += f"{RULE}\n\nNo post this round from: {', '.join(labels[a] for a in absent)}.\n"
    return text, included, absent, made


def attributed(text, plan):
    """The board as the operator reads it: each seat named by harness/model."""
    for seat in plan["seats"]:
        text = text.replace(f"({seat['id']})", f"({seat['id']}, {seat['harness']}/{seat['model']})")
    return text


def collect_made(root, plan, seat, n):
    """Move the seat's declared files out of its outbox, and capture its worktree."""
    name = seat["id"]
    outbox = Path(root) / "work" / name / "outbox"
    asked = deliverable(plan, n)
    for file in declared_files(plan):
        written = outbox / file
        if not written.exists() or not written.read_bytes().strip():
            if file == asked:
                event(root, round=n, seat=name, event="unmade", file=file)
            continue
        kept = made_path(root, name, n, file)
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(written, kept)
        written.unlink()
        event(root, round=n, seat=name, event="made" if file == asked else "revised",
              file=file, bytes=kept.stat().st_size, sha256=digest(kept))
    if seat["workspace"] == "worktree":
        patch = workspace.capture(Path(root) / "work" / name / workspace.REPO,
                                  plan["base_commit"])
        if patch.strip():
            kept = made_path(root, name, n, CHANGES)
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_text(patch, encoding="utf-8")
            event(root, round=n, seat=name, event="changes", bytes=kept.stat().st_size,
                  sha256=digest(kept))


def promote(root, n):
    """Move every answered seat's post and files onto the board; publish the digest."""
    root, plan = runs.load(root)
    for seat in plan["seats"]:
        name = seat["id"]
        if name not in acting(plan, n):
            continue
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
        collect_made(root, plan, seat, n)
    text, included, absent, made = compose_digest(root, plan, n)
    out = root / "board" / "rounds" / f"r{n:03d}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "digest.md").write_text(text, encoding="utf-8")
    write(out / "digest.json", {"round": n, "order": board_order(plan["seats"], n),
                                "posts": included, "made": made, "absent": absent,
                                "chair_note": chair_note(root, n) is not None,
                                "digest_sha256": digest(out / "digest.md")})
    signal = convergence(root, plan, n)
    write(out / "convergence.json", signal)
    event(root, round=n, event="round-closed", posted=len(included), absent=len(absent))
    event(root, round=n, event="convergence", novelty=signal["novelty"],
          closing=signal["closing"], converged=signal["converged"], reason=signal["reason"])
    return {"posted": sorted(included), "absent": absent, "made": made,
            "convergence": {k: signal[k] for k in ("novelty", "closing", "converged", "reason")}}


def published_rounds(root):
    return sorted(int(p.name[1:]) for p in (Path(root) / "board" / "rounds").glob("r[0-9][0-9][0-9]"))


def text(root, plan, *, round_number=None, attribute=True):
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


# A room that has stopped producing positions keeps producing paragraphs,
# so it cannot be trusted to notice it is finished. Both signals read the
# board and nothing else; no model call is spent asking a room whether it is
# done. Heuristics fitted to measured rooms, not laws; a plan can move them.
STOP_NOVELTY = 55.0
STOP_CLOSING = 0.75
CLOSING = re.compile(
    r"\b(unanimous|our work here|the room has|settled|adjourn|no more objections|"
    r"nothing further|nothing to add|verdict)", re.IGNORECASE)
WORD = re.compile(r"[a-z][a-z'-]+")
COMMON = frozenset("""the a an and or but of to in is it that this for with as on not you we
they be are was were has have had will would can could their its his her them me my our
your if then than so what which who when how all any each other more most some such no nor
only own same too very just do does did at by from up down out off over under again once
here there why while about against between into through during before after above
below""".split())


def _content_words(text):
    return {w for w in WORD.findall(text.lower()) if w not in COMMON and len(w) > 3}


def convergence(root, plan, n):
    """How close the room is to having nothing left to say, after round `n`.

    Novelty is the share of a post's content words that seat has never used
    before; closing is the share of speaking seats reaching for consensus
    language. Either must hold for two consecutive rounds, because one round
    of agreement is noise.
    """
    seats = [s["id"] for s in plan["seats"]]
    seen = {s: set() for s in seats}
    series = []
    for number in range(1, n + 1):
        novel, closers = [], 0
        for name in spoke(root, plan, number):
            body = post_path(root, name, number).read_text(encoding="utf-8")
            words = _content_words(body)
            novel.append(100 * len(words - seen[name]) / max(1, len(words)))
            seen[name] |= words
            closers += bool(CLOSING.search(body))
        series.append({"round": number,
                       "novelty": round(sum(novel) / len(novel), 1) if novel else None,
                       "closing": round(closers / len(novel), 2) if novel else None})
    quiet_at = plan.get("stop_novelty", STOP_NOVELTY)
    closed_at = plan.get("stop_closing", STOP_CLOSING)
    last = series[-2:]
    usable = last if all(x["novelty"] is not None for x in last) else []
    quiet = len(usable) == 2 and all(x["novelty"] <= quiet_at for x in usable)
    closed = len(usable) == 2 and all(x["closing"] >= closed_at for x in usable)
    return {"round": n, "novelty": series[-1]["novelty"] if series else None,
            "closing": series[-1]["closing"] if series else None,
            "converged": quiet or closed,
            "reason": "novelty" if quiet else "closing" if closed else None, "series": series}


def budget(root, plan):
    """Rounds this run may play: what it declared, plus extensions.

    Kept outside the frozen plan so the budget can move without touching
    what the seats were promised.
    """
    path = Path(root) / "budget.json"
    return read(path)["rounds"] if path.exists() else plan["rounds"]


def extend(root, rounds):
    """Raise the round budget. One way, because lowering it orphans rounds."""
    root, plan = runs.load(root)
    current = budget(root, plan)
    if not isinstance(rounds, int) or rounds <= current:
        raise ValueError(f"this run already allows {current} rounds")
    write(root / "budget.json", {"rounds": rounds, "declared": plan["rounds"]})
    event(root, event="budget-extended", rounds=rounds, was=current)
    return rounds
