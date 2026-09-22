"""Tailing a live seat: what it is saying and doing, as it happens.

Streams go to files, not pipes, so a reader can attach at any time
without perturbing the seat. Each harness's event shape is rendered to
a few line kinds: text the seat produced, a tool it called, and the end
of the turn. Reasoning is shown only on request.
"""

from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path


def _wrap(text, width, prefix="  "):
    return "\n".join(textwrap.fill(line, width, initial_indent=prefix, subsequent_indent=prefix)
                     if line.strip() else "" for line in text.splitlines())


def claude_lines(row, *, thinking, width):
    kind = row.get("type")
    if kind == "assistant":
        for block in row.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                yield _wrap(block["text"], width)
            elif block.get("type") == "thinking" and thinking:
                yield _wrap(block.get("thinking", ""), width, "  ~ ")
            elif block.get("type") in ("tool_use", "server_tool_use"):
                inputs = block.get("input") or {}
                hint = inputs.get("file_path") or inputs.get("command") or inputs.get("pattern") or ""
                yield f"> {block.get('name')} {str(hint)[:width - 4]}".rstrip()
    elif kind == "result":
        yield f"-- {'error' if row.get('is_error') else 'done'}: {str(row.get('result', ''))[:width - 10]}"
    elif kind == "system" and row.get("subtype") not in ("init", None):
        yield f"-- {row.get('subtype')}"


def codex_lines(row, *, thinking, width):
    if row.get("type") == "item.completed":
        item = row.get("item") or {}
        kind = item.get("type")
        if kind == "agent_message":
            yield _wrap(item.get("text", ""), width)
        elif kind == "reasoning" and thinking:
            yield _wrap(item.get("text", ""), width, "  ~ ")
        elif kind == "command_execution":
            yield f"> $ {str(item.get('command', ''))[:width - 4]}"
        elif kind in ("file_change", "web_search", "mcp_tool_call"):
            yield f"> {kind} {str(item.get('path') or item.get('query') or item.get('name') or '')[:width - 4]}".rstrip()
    elif row.get("type") == "turn.completed":
        yield "-- done"
    elif row.get("type") == "turn.failed":
        yield f"-- error: {str((row.get('error') or {}).get('message', ''))[:width - 10]}"


def agy_lines(row, *, thinking, width):
    step = row.get("step_update") or {}
    if step.get("step_type") == "tool" and step.get("state") == "ACTIVE":
        params = (step.get("tool_info") or {}).get("parameters") or {}
        hint = next((str(v) for k, v in params.items() if isinstance(v, str)), "")
        yield f"> {step.get('tool_name')} {hint[:width - 4]}".rstrip()
    elif step.get("step_type") == "thinking" and thinking and step.get("text"):
        yield _wrap(step["text"], width, "  ~ ")
    elif row.get("event") == "result":
        result = row.get("result") or {}
        if result.get("status") in ("SUCCESS", "COMPLETED", "DONE"):
            yield _wrap(result.get("response", ""), width)
            yield "-- done"
        else:
            yield f"-- error: {str(result.get('error') or result.get('response') or '')[:width - 10]}"


RENDERERS = {"claude": claude_lines, "codex": codex_lines, "agy": agy_lines}


def render(harness, row, *, thinking=False, width=88):
    return list(RENDERERS[harness](row, thinking=thinking, width=width))


def latest_record(root, seat):
    records = sorted((Path(root) / "records" / seat).glob("r[0-9][0-9][0-9]"))
    if not records:
        raise ValueError(f"{seat} has no turn yet")
    return records[-1]


def follow(root, seat, harness, *, record=None, thinking=False, width=88, poll=1.0,
           out=sys.stdout, once=False):
    """Print a seat's stream as it grows; return when the turn's receipt lands."""
    record = Path(record) if record else latest_record(root, seat)
    if not record.is_dir():
        raise ValueError(f"{seat} has no turn record at {record}; "
                         "use `convene status` to check which turns have started")
    events = record / "events.jsonl"
    seen = 0
    buffer = b""
    while True:
        if events.exists():
            with events.open("rb") as handle:
                handle.seek(seen)
                buffer += handle.read()
                seen = handle.tell()
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for text in render(harness, row, thinking=thinking, width=width):
                    print(text, file=out)
        if (record / "receipt.json").exists() or once:
            stderr = record / "stderr.log"
            if stderr.exists() and stderr.stat().st_size:
                print("-- stderr:", file=out)
                print(_wrap(stderr.read_text(errors="replace")[-2000:], width), file=out)
            return record
        time.sleep(poll)
