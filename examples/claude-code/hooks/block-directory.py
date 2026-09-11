#!/usr/bin/env python3
"""Reference PreToolUse hook for denying structured file access to a directory."""

import argparse
import json
import os
import sys
from pathlib import Path


def decision(event, blocked):
    """Return a denial for supported paths; shell and MCP tools are out of scope."""
    tool = event.get("tool_name")
    if not isinstance(tool, str):
        raise ValueError("tool_name must be a string")
    fields = {
        "Read": "file_path", "Write": "file_path", "Edit": "file_path",
        "MultiEdit": "file_path", "NotebookEdit": "notebook_path",
        "Glob": "path", "Grep": "path",
    }
    if tool not in fields:
        return None
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise ValueError("supported file tools require an absolute event cwd")
    args = event.get("tool_input")
    if not isinstance(args, dict):
        raise ValueError("tool_input must be an object")
    raw = args.get(fields[tool], cwd if tool in ("Glob", "Grep") else None)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{tool} requires {fields[tool]}")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(cwd) / path
    scopes = [Path(os.path.abspath(path)), path.resolve()]
    if tool == "Glob":
        pattern = args.get("pattern", "")
        if not isinstance(pattern, str):
            raise ValueError("Glob pattern must be a string")
        # Absolute patterns can escape the supplied search path. Their fixed
        # directory prefix bounds the possible matches conservatively.
        if Path(pattern).is_absolute():
            prefix = Path("/")
            for part in Path(pattern).parts[1:]:
                if any(char in part for char in "*?["):
                    break
                prefix /= part
            scopes.extend((Path(os.path.abspath(prefix)), prefix.resolve()))
    boundaries = (Path(os.path.abspath(blocked)), blocked.resolve())
    for scope in scopes:
        for boundary in boundaries:
            if scope.is_relative_to(boundary) or (
                tool in ("Glob", "Grep") and boundary.is_relative_to(scope)
            ):
                return f"Access to the configured directory is blocked: {blocked}"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocked-dir", required=True, type=Path)
    args = parser.parse_args()
    blocked = args.blocked_dir.expanduser()
    if not blocked.is_absolute():
        parser.error("--blocked-dir must be absolute")
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("hook event must be an object")
        reason = decision(event, blocked)
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Invalid hook input: {error}", file=sys.stderr)
        return 2
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
