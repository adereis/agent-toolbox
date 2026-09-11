#!/usr/bin/env python3
"""Smart session resume for Claude Code.

Shows enriched session history and lets you pick a session to resume. For each
session it surfaces:
  - the session's title (the AI-generated or user-renamed name shown in /resume)
  - an "arc" of prompts (first, second-to-last, last) so you recognize the work
  - recognized git commit results during the session (sha + summary)
  - files edited (in --verbose mode)
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
from _session_resume import (
    _command_makes_commit, _commits_from_result, _commit_message_from_command,
    _sha_for_summary, _dedupe_commits, _tool_result_text, read_jsonl,
    valid_session_id, warn, run_browser,
)

# Pattern to detect skill/command invocations in user prompts
_COMMAND_RE = re.compile(
    r"<command-name>\s*/(\S+)\s*</command-name>"
)


_SKILL_EXPANSION_RE = re.compile(
    r"^Base directory for this skill:"
)


def _clean_prompt(text: str) -> str:
    """Clean up a user prompt, replacing command XML with /command-name.

    Returns empty string for prompts that should be skipped entirely
    (e.g., skill expansion content injected by Claude Code).
    """
    m = _COMMAND_RE.search(text)
    if m:
        return f"/{m.group(1)}"
    # Skip skill expansion content (SKILL.md injected as user message)
    if _SKILL_EXPANSION_RE.match(text):
        return ""
    return text


def _entry_from_jsonl(path, indexed):
    """Use this store's actual file, never a cached fullPath into another store."""
    stat = path.stat()
    first = None
    for record in read_jsonl(path):
        if record.get("type") == "user":
            first = record
            break
    if first is None or first.get("isSidechain"):
        return None
    if first.get("sessionId") and first["sessionId"] != path.stem:
        warn(f"{path}: session ID does not match filename")
        return None
    project = first.get("cwd") or indexed.get("projectPath", "")
    if not isinstance(project, str) or not Path(project).is_absolute():
        warn(f"{path}: missing absolute project path")
        return None
    modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    return {
        "sessionId": path.stem, "fullPath": str(path),
        "title": indexed.get("summary", ""),
        "created": first.get("timestamp") or modified,
        "modified": modified, "gitBranch": first.get("gitBranch", ""),
        "projectPath": project, "_mtime": stat.st_mtime,
    }


class ClaudeSessions:
    name = "Claude Code"
    directory_option = "--claude-dir"
    directory_env = "CLAUDE_CONFIG_DIR"
    default_dir = str(Path.home() / ".claude")

    def add_arguments(self, parser):
        pass

    def discover(self, root, args):
        entries = []
        projects = root / "projects"
        if not projects.is_dir():
            return entries
        for project in sorted(projects.iterdir()):
            if not project.is_dir() or project.is_symlink():
                continue
            index = {}
            index_path = project / "sessions-index.json"
            if index_path.is_file():
                try:
                    data = json.loads(index_path.read_text())
                    if not isinstance(data, dict) or not isinstance(data.get("entries", []), list):
                        raise ValueError("invalid index shape")
                    index = {entry["sessionId"]: entry for entry in data.get("entries", [])
                             if isinstance(entry, dict) and valid_session_id(entry.get("sessionId"))}
                except (OSError, ValueError) as error:
                    warn(f"{index_path}: {error}; discovering transcript files instead")
            for path in project.glob("*.jsonl"):
                if path.is_symlink() or not valid_session_id(path.stem):
                    continue
                try:
                    entry = _entry_from_jsonl(path, index.get(path.stem, {}))
                    if entry:
                        entries.append(entry)
                except OSError as error:
                    warn(f"{path}: {error}")
        return entries

    def parse(self, entry):
        return parse_session_jsonl(entry["fullPath"])

    def command(self, entry, args):
        return ["claude", "--resume", entry["sessionId"]]


def parse_session_jsonl(jsonl_path: str) -> dict:
    """Parse a session JSONL file to extract title, prompts, commits, and files."""
    path = Path(jsonl_path)
    title = ""
    user_prompts = []  # list of (serial_number, text)
    prompt_num = 0
    git_commits = []  # list of (sha, message) in order seen
    files_edited = set()
    edit_calls = {}
    message_count = 0
    commit_cmds = {}  # tool_use id -> command text, for real `git commit` calls

    for obj in read_jsonl(path):
        # Session title (AI-generated or user-renamed) — keep the latest.
        if obj.get("type") in ("ai-title", "custom-title"):
            title = obj.get("customTitle") or obj.get("aiTitle") or title
            continue

        msg = obj.get("message", {})
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "")
        if role in ("user", "assistant"):
            message_count += 1
        content = msg.get("content", "")

        # Extract user prompts
        if role == "user" and not obj.get("isMeta") and not obj.get("isCompactSummary"):
            text = ""
            if isinstance(content, str) and content.strip():
                text = content.strip()
            elif isinstance(content, list):
                text = "\n".join(c["text"] for c in content if isinstance(c, dict)
                                 and c.get("type") == "text" and isinstance(c.get("text"), str)).strip()
            if text:
                text = _clean_prompt(text)
                if text:
                    prompt_num += 1
                    user_prompts.append((prompt_num, text))

        # Track git-commit invocations and edited files (tool_use), then
        # read the SHA + summary from the matching result (tool_result).
        if isinstance(content, list):
            for c in content:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                if ctype == "tool_use":
                    name = c.get("name")
                    payload = c.get("input")
                    if not isinstance(payload, dict):
                        warn(f"{path}: ignored malformed tool input")
                        continue
                    if name == "Bash":
                        cmd = payload.get("command", "")
                        if isinstance(cmd, str) and _command_makes_commit(cmd):
                            commit_cmds[c.get("id")] = cmd
                    elif name in ("Write", "Edit"):
                        fp = payload.get("file_path", "")
                        if isinstance(fp, str) and fp:
                            edit_calls[c.get("id")] = fp
                elif ctype == "tool_result" and c.get("tool_use_id") in edit_calls:
                    if not c.get("is_error"):
                        files_edited.add(edit_calls[c["tool_use_id"]])
                elif ctype == "tool_result" and c.get("tool_use_id") in commit_cmds:
                    text = _tool_result_text(c)
                    found = _commits_from_result(text)
                    if found:
                        git_commits.extend(found)
                    else:
                        # `git commit -q` printed no success line; recover
                        # the summary from the command and the SHA from any
                        # hash the script echoed. Drop a failed quiet commit
                        # (error result with no echoed SHA) as a phantom.
                        summary = _commit_message_from_command(
                            commit_cmds[c.get("tool_use_id")]
                        )
                        if summary:
                            sha = _sha_for_summary(text, summary)
                            if sha or not c.get("is_error"):
                                git_commits.append((sha, summary))

    return {
        "title": title,
        "user_prompts": user_prompts,
        "git_commits": _dedupe_commits(git_commits),
        "files_edited": sorted(files_edited),
        "messageCount": message_count,
    }


def main(argv=None):
    return run_browser(ClaudeSessions(), argv)


if __name__ == "__main__":
    sys.exit(main())
