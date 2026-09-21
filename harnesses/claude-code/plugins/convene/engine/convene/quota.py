"""Telling a provider's account limit apart from a failure, and which recovery
each shape allows.

Ported from quirework's `providers/quota.py`. Two shapes, two recoveries:

``refused``
    The provider declined before the model ran. Nothing was generated. The
    harness has still appended the prompt (often with its refusal notice) to
    the session, so the session file is rewound to its recorded prefix and
    the identical turn is resubmitted (`sessions.rewind`).

``interrupted``
    The model ran and the wall arrived partway. The turn's reasoning is
    banked in the session and the only recovery that keeps it is to resume
    that session with a task-free continuation note.

A transport fault is neither: returning None is the safe answer, because
resubmitting an ambiguous turn can duplicate work that actually happened.
"""

from __future__ import annotations

import re
from pathlib import Path

from convene.observe import native_rows

LIMIT_TEXT = re.compile(
    r"usage limit|session limit|rate.?limit|quota|too many requests|resets? at|429\b",
    re.I)
CAPACITY_TEXT = re.compile(
    r"at capacity|overloaded|try a different model|temporarily unavailable", re.I)
CODEX_LIMIT_CODES = ("rate_limit_exceeded", "insufficient_quota")

CONTINUATION = (
    "There was a session quota limit event and your previous turn was cut "
    "off partway through. Nothing about the assignment has changed and "
    "nothing you already did has been lost.\n\n"
    "Continue from where you were. Re-read what you have already written, "
    "do not redo work you have already completed, do not start over, and "
    "finish the task you were given.")


def continuation(note=None):
    return CONTINUATION if not note else f"{CONTINUATION}\n\n{note.strip()}\n"


def session_id(harness, stream):
    """The one session this stream belongs to, even when the turn failed."""
    if harness == "codex":
        ids = [r["thread_id"] for r in stream if r.get("type") == "thread.started"]
    elif harness == "claude":
        ids = [r["session_id"] for r in stream if r.get("session_id")]
    elif harness == "agy":
        ids = [r["conversation_id"] for r in stream if r.get("conversation_id")]
    else:
        raise ValueError(f"unknown harness: {harness}")
    unique = list(dict.fromkeys(ids))
    return unique[0] if len(unique) == 1 else None


def _claude(stream):
    results = [r for r in stream if r.get("type") == "result"]
    if len(results) != 1 or not results[0].get("is_error"):
        return None
    result = results[0]
    said = str(result.get("result") or "")
    if CAPACITY_TEXT.search(said) and not LIMIT_TEXT.search(said):
        return dict(phase="refused", scope="capacity", resets_at=None,
                    detail=said[:200], output_tokens=0)
    limit = [r for r in stream if r.get("type") == "rate_limit_event"
             and (r.get("rate_limit_info") or {}).get("status") == "rejected"]
    if not limit and not LIMIT_TEXT.search(said):
        return None
    info = (limit[-1].get("rate_limit_info") or {}) if limit else {}
    produced = sum(v.get("outputTokens", 0) or 0
                   for v in (result.get("modelUsage") or {}).values())
    return dict(phase="refused" if not produced else "interrupted",
                scope=info.get("rateLimitType") or "quota",
                resets_at=info.get("resetsAt"), detail=said[:200],
                output_tokens=produced)


def _codex(stream):
    stopped = [r for r in stream if r.get("type") == "turn.failed"]
    failed = [r for r in stopped
              if (r.get("error") or {}).get("code") in CODEX_LIMIT_CODES]
    if not failed:
        busy = [r for r in stopped
                if CAPACITY_TEXT.search(str((r.get("error") or {}).get("message", "")))]
        if not busy:
            return None
        error = busy[-1].get("error") or {}
        return dict(phase="refused", scope="capacity", resets_at=None,
                    detail=str(error.get("message", ""))[:200], output_tokens=None)
    error = failed[-1].get("error") or {}
    produced = any(r.get("type") == "item.completed" for r in stream)
    return dict(phase="interrupted" if produced else "refused",
                scope=error.get("code"), resets_at=error.get("resets_at"),
                detail=str(error.get("message", ""))[:200], output_tokens=None)


def _agy(stream):
    results = [r["result"] for r in stream if r.get("event") == "result"]
    if len(results) != 1 or results[0].get("status") != "ERROR":
        return None
    result = results[0]
    said = str(result.get("error") or result.get("response") or "")
    if not LIMIT_TEXT.search(said):
        return None
    produced = (bool(result.get("response"))
                or bool((result.get("usage") or {}).get("output_tokens"))
                or any((r.get("step_update") or {}).get("step_type") == "tool" for r in stream))
    return dict(phase="interrupted" if produced else "refused", scope="quota", resets_at=None,
                detail=said[:200], output_tokens=(result.get("usage") or {}).get("output_tokens"))


CLASSIFIERS = {"claude": _claude, "codex": _codex, "agy": _agy}


def classify(harness, record):
    """A quota stop in this record's event stream, or None."""
    if harness not in CLASSIFIERS:
        raise ValueError(f"unknown harness: {harness}")
    record = Path(record)
    path = record if record.is_file() else record / "events.jsonl"
    if not path.exists():
        return None
    # Tolerant of a truncated final row: a killed seat's stream still has
    # to be classified, and a classifier that raises on it would leave the
    # turn with no receipt at all.
    try:
        stream = list(native_rows(path))
    except ValueError:
        return None
    if not stream:
        return None
    detail = CLASSIFIERS[harness](stream)
    if detail is None:
        return None
    detail["harness"] = harness
    detail["session_id"] = session_id(harness, stream)
    return detail


def resumable_session(detail):
    """The session to resume after an interrupted stop, else None."""
    if not detail or detail["phase"] != "interrupted":
        return None
    return detail["session_id"]
