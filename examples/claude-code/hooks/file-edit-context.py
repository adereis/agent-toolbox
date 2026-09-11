#!/usr/bin/env python3
"""Reference PreToolUse hook that adds context for matching edit paths."""

import argparse
import json
import re
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", required=True, help="Regular expression for the file path")
    parser.add_argument("--message", required=True, help="Context to add for a matching edit")
    args = parser.parse_args()
    try:
        pattern = re.compile(args.pattern)
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("hook event must be an object")
        tool = event.get("tool_name")
        if not isinstance(tool, str):
            raise ValueError("tool_name must be a string")
        if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            return 0
        payload = event.get("tool_input")
        if not isinstance(payload, dict):
            raise ValueError("tool_input must be an object")
        field = "notebook_path" if tool == "NotebookEdit" else "file_path"
        path = payload.get(field)
        if not isinstance(path, str) or not path:
            raise ValueError(f"{tool} requires {field}")
        if pattern.search(path):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "additionalContext": args.message,
            }}))
    except (ValueError, re.error) as error:
        print(f"Invalid hook input: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
