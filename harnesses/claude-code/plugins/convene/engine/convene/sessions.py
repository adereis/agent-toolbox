"""Marks and rewinds of native session files around a submission.

A refused turn leaves the prompt (and often the refusal) appended to the
harness's own session file. Resubmitting on top of that would send the
model a conversation containing a turn it never answered. The mark taken
before submission is what lets the rewind cut exactly those rows and
nothing else.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def marks(paths):
    """Length and prefix digest of each session file, before a submission."""
    out = []
    for path in paths:
        data = Path(path).read_bytes()
        out.append(dict(path=str(path), size=len(data),
                        sha256=hashlib.sha256(data).hexdigest()))
    return out


def rewind(marks):
    """Return each marked file to its marked state.

    Refuses unless the file still begins with exactly the marked bytes, so
    this can only ever remove the refused turn's own appended rows.
    """
    for mark in marks or []:
        path = Path(mark["path"])
        if not path.exists():
            if mark["size"]:
                raise RuntimeError(f"session file vanished: {path}")
            continue
        data = path.read_bytes()
        if len(data) < mark["size"]:
            raise RuntimeError(f"session file shrank; not a clean rewind: {path}")
        if hashlib.sha256(data[: mark["size"]]).hexdigest() != mark["sha256"]:
            raise RuntimeError(f"session prefix changed; not a clean rewind: {path}")
        if len(data) == mark["size"]:
            continue
        with path.open("r+b") as handle:
            handle.truncate(mark["size"])
