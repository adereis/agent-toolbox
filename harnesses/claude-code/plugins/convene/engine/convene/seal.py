"""Sealing a round: reading blind work without learning who wrote it.

A fanout's value is that the operator judges N attempts on their merits.
Seat ids, sizes, tool counts and durations are all near-unique per seat,
so any of them printed before the drafts are read hands the operator the
identity key by arithmetic. `seal` shuffles the round's posts and made
files under letters and writes the key to a file it never prints; `board`,
`usage` and `export` withhold the attributed view until `unseal`, which
insists on a recorded judgment first. Reading the key before the drafts
spends the step and keeps none of it, and a reshuffle cannot undo that.
"""

from __future__ import annotations

import os
import random
import shutil
import string
import time
from pathlib import Path

from convene import board, runs
from convene.storage import digest, event, read, write

JUDGMENT = "judgment.md"


def sealed_dir(root, n):
    return Path(root) / "sealed" / f"r{n:03d}"


def sealed_rounds(root):
    return sorted(int(p.name[1:]) for p in (Path(root) / "sealed").glob("r[0-9][0-9][0-9]")
                  if (p / "seal.json").exists())


def is_sealed(root, n):
    return (sealed_dir(root, n) / "seal.json").exists()


def is_unsealed(root, n):
    return (sealed_dir(root, n) / "unsealed.json").exists()


def blind(plan):
    """Whether this run is read sealed: any seat that works blind."""
    return plan["kind"] == "fanout" or any(s["visibility"] == "blind" for s in plan["seats"])


def blind_rounds(plan, rounds):
    """The rounds in which a blind seat acted: the only rounds `seal` letters.

    A synthesizer's round has one seat that read the board; lettering it
    would hide nothing and leave the attempts unsealed.
    """
    blind_seats = {s["id"] for s in plan["seats"] if s["visibility"] == "blind"}
    return [n for n in rounds if blind_seats & set(board.acting(plan, n))]


def pending(root, plan):
    """Published blind rounds the operator has not yet judged and unsealed."""
    return [n for n in blind_rounds(plan, board.published_rounds(root))
            if not is_unsealed(root, n)]


def withheld(root, plan):
    """Rounds whose attributed view is still withheld from the operator.

    Every published round stays withheld while any blind round is pending,
    not only the blind rounds themselves: a synthesis or a reply names the
    seats it read, which would hand over the key.
    """
    if not blind(plan) or not pending(root, plan):
        return []
    return [n for n in board.published_rounds(root) if not is_unsealed(root, n)]


def guard(root, plan, what):
    if withheld(root, plan):
        n = pending(root, plan)[-1]
        step = ("`convene seal` then read sealed/" if not is_sealed(root, n)
                else f"read sealed/r{n:03d}/, write its {JUDGMENT}, then `convene unseal`")
        raise ValueError(f"{what} is withheld while round {n} is sealed or unsealed: {step}")


def seal(root, n=None, *, seed=None, force=False):
    """Shuffle round `n`'s posts and made files under letters; write the key.

    With no `n`, the latest blind round not yet lettered, so the `convene
    seal` that `status` names next always lands on the round it meant.
    """
    root, plan = runs.load(root)
    published = board.published_rounds(root)
    sealable = blind_rounds(plan, published)
    if not sealable:
        raise ValueError("no published round with a blind seat to seal")
    if n is None:
        unlettered = [r for r in sealable if not is_sealed(root, r)]
        n = (unlettered or sealable)[-1]
    if n not in published:
        raise ValueError(f"round {n} is not published")
    if n not in sealable:
        raise ValueError(f"round {n} has no blind seat; nothing in it is read sealed "
                         f"(blind rounds: {', '.join(map(str, sealable))})")
    target = sealed_dir(root, n)
    if is_sealed(root, n) and not force:
        raise ValueError(f"round {n} is already sealed; reading a second shuffle beside the "
                         "first would leak the key (--force reseals anyway)")
    present = sorted(name for name in board.acting(plan, n) if board.post_path(root, name, n).exists())
    if not present:
        raise ValueError(f"round {n} has no posts to seal")
    if len(present) > 26:
        raise ValueError("more than 26 seats cannot be lettered")
    shuffled = list(present)
    random.Random(seed if seed is not None else os.urandom(16)).shuffle(shuffled)
    judgment = target / JUDGMENT
    kept = judgment.read_bytes() if judgment.exists() else None
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    if kept is not None:
        # A reseal reshuffles the letters; the operator's words are theirs
        # and are kept, with a note that the letters under them moved.
        judgment.write_bytes(kept)
        event(root, round=n, event="judgment-kept-across-reseal")
    key = {}
    for letter, name in zip(string.ascii_uppercase, shuffled):
        folder = target / letter
        folder.mkdir(parents=True)
        shutil.copyfile(board.post_path(root, name, n), folder / "post.md")
        made = root / "board" / "made" / name / f"r{n:03d}"
        for file in sorted(made.iterdir()) if made.is_dir() else []:
            shutil.copyfile(file, folder / file.name)
        key[letter] = name
    write(target / "identity-key.json", key)
    write(target / "seal.json", {"round": n, "letters": sorted(key), "count": len(key),
                                 "sealed_at": time.time(),
                                 "posts_sha256": {k: digest(target / k / "post.md") for k in key}})
    event(root, round=n, event="sealed", count=len(key))
    return {"round": n, "letters": sorted(key), "directory": str(target),
            "judgment": str(target / JUDGMENT), "judgment_kept": kept is not None}


def unseal(root, n=None):
    """Print the key, once the operator's judgment is on file."""
    root, plan = runs.load(root)
    sealed = sealed_rounds(root)
    if not sealed:
        raise ValueError("no sealed round; `convene seal` first")
    if n is None:
        # The latest round still waiting, rather than the latest lettered:
        # with two blind rounds, the second may be open while the first is not.
        waiting = [r for r in sealed if not is_unsealed(root, r)]
        n = (waiting or sealed)[-1]
    if n not in sealed:
        raise ValueError(f"round {n} is not sealed")
    target = sealed_dir(root, n)
    judgment = target / JUDGMENT
    if not judgment.exists() or not judgment.read_text(encoding="utf-8").strip():
        raise ValueError(f"write your judgment of the lettered drafts to {judgment} before "
                         "unsealing; the key is printed only after it is on file")
    key = read(target / "identity-key.json")
    if not is_unsealed(root, n):
        write(target / "unsealed.json", {"round": n, "unsealed_at": time.time(),
                                         "judgment_sha256": digest(judgment)})
        event(root, round=n, event="unsealed")
    served = {s["id"]: f"{s['harness']}/{s['model']}" for s in plan["seats"]}
    return {"round": n, "key": {letter: {"seat": seat, "served": served.get(seat)}
                                 for letter, seat in key.items()}}
