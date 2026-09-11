#!/usr/bin/env python3
"""Browse local Codex rollouts with prompt arcs, commits, and resume selection."""

import json
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
from _session_resume import (
    _command_makes_commit, _commits_from_result, _dedupe_commits,
    read_jsonl, run_browser, valid_session_id, warn,
)


_JSON_STRING = r'"(?:\\.|[^"\\])*"'
_STATIC_COMMAND = re.compile(r'\b(?:cmd|command)\s*:\s*(' + _JSON_STRING + ')')
_STATIC_PATCH = re.compile(r'\bapply_patch\s*\(\s*(' + _JSON_STRING + ')')
_PATCH_FILE = re.compile(r'^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$', re.MULTILINE)
_CONTEXT_PREFIXES = (
    "# AGENTS.md instructions", "<environment_context>", "<permissions instructions>",
    "<user_instructions>", "<INSTRUCTIONS>", "Base directory for this skill:",
)


def prompt_text(content):
    if isinstance(content, str):
        blocks = [content]
    elif isinstance(content, list):
        blocks = [block.get("text", "") for block in content if isinstance(block, dict)
                  and block.get("type") in ("input_text", "text", "output_text")]
    else:
        return ""
    return "\n".join(text.strip() for text in blocks if isinstance(text, str)
                     and text.strip() and not text.strip().startswith(_CONTEXT_PREFIXES))


def output_parts(value):
    """Unwrap native tool output and statically rendered orchestration results."""
    if isinstance(value, list):
        return [part for item in value for part in output_parts(item)]
    if isinstance(value, dict):
        if "output" in value:
            return [value, *output_parts(value["output"])]
        if "text" in value:
            return [value, *output_parts(value["text"])]
        if "content" in value:
            return [value, *output_parts(value["content"])]
        if value.get("status") == "fulfilled" and "value" in value:
            return [value, *output_parts(value["value"])]
        return [value]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return [value]
        if isinstance(decoded, (dict, list)):
            return output_parts(decoded)
        return [value]
    return []


def call_details(payload, processes):
    name = payload.get("name", "")
    if not isinstance(name, str):
        return {"commands": [], "files": [], "unparsed": True}
    name = name.rsplit(".", 1)[-1]
    raw = payload.get("arguments", payload.get("input", ""))
    if name == "apply_patch":
        return {"commands": [], "files": _PATCH_FILE.findall(raw) if isinstance(raw, str) else []}
    if name == "exec":
        if not isinstance(raw, str):
            return {"commands": [], "files": [], "unparsed": True}
        commands = [json.loads(match) for match in _STATIC_COMMAND.findall(raw)]
        files = [file for match in _STATIC_PATCH.findall(raw)
                 for file in _PATCH_FILE.findall(json.loads(match))]
        return {"commands": commands, "files": files,
                "unparsed": "exec_command" in raw and not commands}
    try:
        args = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {"commands": [], "files": [], "unparsed": True}
    if not isinstance(args, dict):
        return {"commands": [], "files": []}
    if name == "write_stdin":
        return processes.get(args.get("session_id"), {"commands": [], "files": []})
    command = args.get("cmd", args.get("command", "")) if name in ("exec_command", "shell_command", "shell") else ""
    if isinstance(command, list):
        # Older shell calls use argv. Only inspect an explicit shell -c body.
        command = command[-1] if len(command) >= 3 and command[-2] in ("-c", "-lc") else ""
    return {"commands": [command] if isinstance(command, str) and command else [], "files": []}


def parse_rollout(path):
    prompts, commits, edited = [], [], set()
    calls, processes = {}, {}
    last_prompt = None
    messages = 0
    unparsed = 0
    modified = ""
    for record in read_jsonl(path):
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if isinstance(record.get("timestamp"), str):
            modified = record["timestamp"]
        kind = record.get("type")
        subtype = payload.get("type")
        text, origin = "", ""
        if kind == "event_msg" and subtype == "user_message":
            text, origin = prompt_text(payload.get("message", "")), "event"
        elif kind == "response_item" and subtype == "message":
            if payload.get("role") in ("user", "assistant"):
                messages += 1
            if payload.get("role") == "user":
                text, origin = prompt_text(payload.get("content", [])), "response"
            elif payload.get("role") == "assistant":
                last_prompt = None
        if text:
            # The same input can be recorded as both an event and a response
            # item. Repeated genuine user turns of the same kind are retained.
            if last_prompt is None or last_prompt[0] != text or last_prompt[1] == origin:
                prompts.append((len(prompts) + 1, text))
            last_prompt = (text, origin)
        if kind != "response_item":
            continue
        call_id = payload.get("call_id")
        if subtype in ("function_call", "custom_tool_call"):
            try:
                details = call_details(payload, processes)
            except ValueError:
                details = {"commands": [], "files": [], "unparsed": True}
            calls[call_id] = details
            unparsed += bool(details.get("unparsed"))
        elif subtype in ("function_call_output", "custom_tool_call_output") and call_id in calls:
            details = calls.pop(call_id)
            parts = output_parts(payload.get("output", ""))
            text = "\n".join(part for part in parts if isinstance(part, str))
            if any(_command_makes_commit(command) for command in details["commands"]):
                commits.extend(_commits_from_result(text))
            failed = bool(payload.get("is_error")) or any(
                isinstance(part, dict) and (part.get("isError") or part.get("exit_code", 0) not in (0, None))
                for part in parts
            ) or bool(re.search(r"(?im)^(?:error:|apply_patch verification failed|failed to apply|"
                                r"Process exited with code [1-9]|Exit code: [1-9])", text))
            if not failed:
                edited.update(details["files"])
            for part in parts:
                if isinstance(part, dict) and part.get("session_id") is not None:
                    processes[part["session_id"]] = details
    if unparsed:
        warn(f"{path}: {unparsed} dynamic or malformed tool call(s) could not be inspected")
    return {"title": "", "user_prompts": prompts, "git_commits": _dedupe_commits(commits),
            "files_edited": sorted(edited), "messageCount": messages or len(prompts),
            "modified": modified}


class CodexSessions:
    name = "Codex"
    directory_option = "--codex-dir"
    directory_env = "CODEX_HOME"
    default_dir = str(Path.home() / ".codex")

    def add_arguments(self, parser):
        parser.add_argument("--include-subagents", action="store_true", help="Include delegated sessions")
        parser.add_argument("--profile", help="Pass this configuration profile to codex resume")

    def discover(self, root, args):
        titles = {}
        index = root / "session_index.jsonl"
        if index.is_file():
            for item in read_jsonl(index):
                sid, title = item.get("id"), item.get("thread_name")
                if valid_session_id(sid) and isinstance(title, str):
                    # The index is append-only; later records supersede names.
                    titles[sid] = title
        entries = {}
        sessions = root / "sessions"
        if not sessions.is_dir():
            return []
        for path in sessions.glob("**/*.jsonl"):
            if path.is_symlink() or not path.resolve().is_relative_to(sessions.resolve()):
                continue
            try:
                records = read_jsonl(path)
                try:
                    first = next(records, {})
                finally:
                    records.close()
                metadata = first.get("payload")
                if first.get("type") != "session_meta" or not isinstance(metadata, dict):
                    warn(f"{path}: missing session metadata")
                    continue
                sid = metadata.get("id") or metadata.get("session_id")
                if not valid_session_id(sid):
                    warn(f"{path}: invalid session ID")
                    continue
                source = metadata.get("source", metadata.get("thread_source"))
                if not args.include_subagents and (source == "subagent" or isinstance(source, dict) and "subagent" in source):
                    continue
                cwd = metadata.get("cwd")
                if not isinstance(cwd, str) or not Path(cwd).is_absolute():
                    warn(f"{path}: missing absolute project path")
                    continue
                stat = path.stat()
                modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
                git = metadata.get("git")
                entry = {"sessionId": sid, "fullPath": str(path), "title": titles.get(sid, ""),
                         "created": metadata.get("timestamp") or first.get("timestamp") or modified,
                         "modified": modified, "projectPath": cwd,
                         "gitBranch": git.get("branch", "") if isinstance(git, dict) else "",
                         "_mtime": stat.st_mtime}
                if sid not in entries or entries[sid]["_mtime"] < entry["_mtime"]:
                    entries[sid] = entry
            except OSError as error:
                warn(f"{path}: {error}")
        return list(entries.values())

    def parse(self, entry):
        parsed = parse_rollout(entry["fullPath"])
        modified = parsed.pop("modified")
        if modified:
            entry["modified"] = modified
        return parsed

    def command(self, entry, args):
        command = ["codex", "resume", entry["sessionId"]]
        if args.profile:
            command.extend(("--profile", args.profile))
        return command


def main(argv=None):
    return run_browser(CodexSessions(), argv)


if __name__ == "__main__":
    sys.exit(main())
