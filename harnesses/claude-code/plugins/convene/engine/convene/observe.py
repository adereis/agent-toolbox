"""Read-only diagnostics over event streams and native transcripts."""

from __future__ import annotations

import json
from pathlib import Path


def native_rows(path):
    """Rows of a JSONL file a running writer may still be appending to."""
    with Path(path).open("rb") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                if not line.endswith(b"\n"):
                    return
                raise ValueError(f"{path}:{number}: malformed row") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{number}: row must be an object")
            yield value


def compaction_markers(values):
    """Every row whose type tags mention compaction, with its timestamp."""
    markers = []
    for row in values:
        payload = row.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        item = payload.get("item")
        item = item if isinstance(item, dict) else {}
        tags = [row.get("type"), row.get("subtype"), row.get("event"),
                payload.get("type"), item.get("type")]
        matched = [t for t in tags if isinstance(t, str) and "compact" in t.lower()]
        if matched:
            markers.append({"timestamp": row.get("timestamp"), "tags": matched})
    return markers


def compaction(path):
    """Compaction markers in one file, or an explicit unreadable marker.

    A malformed stream is a failure the receipt already reports; it must not
    also turn into a missing compaction check that reads as a clean one.
    """
    path = Path(path)
    if not path.exists():
        return []
    try:
        return compaction_markers(native_rows(path))
    except (ValueError, OSError):
        return [{"timestamp": None, "tags": ["unreadable-stream"]}]
