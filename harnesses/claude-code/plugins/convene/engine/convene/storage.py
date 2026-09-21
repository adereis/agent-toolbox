"""Durable records: atomic writes, hashes, locks and the run trail.

Every file a run relies on later is written through `write`, which lands the
whole document or nothing: a receipt half-written when the machine went down
would otherwise read as a receipt.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

_LOG_LOCK = Lock()


def read(path):
    """Parse a JSON or TOML document by its suffix."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)


def write(path, value):
    """Write JSON atomically: temp file, fsync, rename, directory fsync."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False,
                                     encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = handle.name
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_text(path, text):
    """Atomic text write with the same guarantees as `write`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False,
                                     encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = handle.name
    os.replace(temporary, path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def hashes(root):
    """Every regular file under `root` with its digest; symlinks are refused.

    A symlink in a frozen tree would let the content change after the hash
    was taken, which is the one thing a frozen tree promises cannot happen.
    """
    root = Path(root)
    if root.is_symlink():
        raise ValueError(f"symlink in frozen tree: {root}")
    result = {}
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"symlink in frozen tree: {item}")
        if item.is_file():
            result[str(item.relative_to(root))] = digest(item)
        elif not item.is_dir():
            raise ValueError(f"non-regular file: {item}")
    return result


IDENTIFIER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*")


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid identifier: {value!r}")
    return value


def relative(value):
    """A relative path that stays inside the directory it is joined to."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"invalid relative path: {value!r}")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise ValueError(f"invalid relative path: {value!r}")
    return path


def safe_name(value):
    """A plain file name: no directory part, no leading dot."""
    text = str(value)
    if not text or "/" in text or text.startswith(".") or text != Path(text).name:
        raise ValueError(f"expected a plain file name: {value!r}")
    return text


def rows(path):
    """Parse complete JSON lines; a truncated last line is a visible failure."""
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


@contextmanager
def lock(path, *, wait=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise RuntimeError(f"another operator owns {path}") from exc
        yield


def event(root, **fields):
    """Append one whole line to the run trail under O_APPEND.

    One write per line is what keeps a reader tailing `run.log` from ever
    seeing half a record.
    """
    line = json.dumps({"t": round(time.time(), 3), **fields}, ensure_ascii=False)
    with _LOG_LOCK:
        fd = os.open(Path(root) / "run.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (line + "\n").encode("utf-8"))
        finally:
            os.close(fd)


def trail(root):
    """The run trail as parsed rows; a half-written final line is skipped."""
    path = Path(root) / "run.log"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
