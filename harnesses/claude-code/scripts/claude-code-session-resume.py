#!/usr/bin/env python3
"""Smart session resume for Claude Code.

Shows enriched session history and lets you pick a session to resume. For each
session it surfaces:
  - the session's title (the AI-generated or user-renamed name shown in /resume)
  - an "arc" of prompts (first, second-to-last, last) so you recognize the work
  - every git commit made during the session (sha + summary)
  - files edited (in --verbose mode)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"

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


def cwd_to_project_key(cwd: str) -> str:
    """Convert a working directory path to the Claude project key format."""
    return cwd.replace("/", "-")


def find_project_dir(cwd: str) -> Path | None:
    """Find the Claude project directory for a given working directory."""
    key = cwd_to_project_key(cwd)
    candidate = PROJECTS_DIR / key
    if candidate.is_dir():
        return candidate
    return None


def all_project_dirs() -> list[Path]:
    """Return all project directories that have sessions (index or JSONL files)."""
    results = []
    if not PROJECTS_DIR.is_dir():
        return results
    for d in sorted(PROJECTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        has_index = (d / "sessions-index.json").exists()
        has_jsonl = any(d.glob("*.jsonl"))
        if has_index or has_jsonl:
            results.append(d)
    return results


def load_sessions_index(project_dir: Path) -> list[dict]:
    """Load sessions from index + any JSONL files not in the index."""
    index_file = project_dir / "sessions-index.json"
    entries = []
    indexed_ids = set()

    if index_file.exists():
        with open(index_file) as f:
            data = json.load(f)
        entries = data.get("entries", [])
        indexed_ids = {e["sessionId"] for e in entries}

    # Discover JSONL files not represented in the index
    for jsonl in project_dir.glob("*.jsonl"):
        sid = jsonl.stem
        if sid in indexed_ids:
            continue
        entry = _entry_from_jsonl(jsonl, sid)
        if entry:
            entries.append(entry)

    return entries


def _entry_from_jsonl(jsonl_path: Path, session_id: str) -> dict | None:
    """Build a minimal session entry by reading JSONL metadata."""
    first_user = None
    last_timestamp = None
    msg_count = 0
    title = ""

    with open(jsonl_path) as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "ai-title":
                title = obj.get("aiTitle") or title
                continue
            if obj.get("type") in ("user", "assistant"):
                msg_count += 1
                ts = obj.get("timestamp")
                if ts:
                    last_timestamp = ts
            if obj.get("type") == "user" and first_user is None:
                first_user = obj

    if not first_user:
        return None

    msg = first_user.get("message", {})
    content = msg.get("content", "")
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                content = c["text"]
                break
        else:
            content = ""
    first_prompt = content.strip() if isinstance(content, str) else ""

    created = first_user.get("timestamp", "")
    return {
        "sessionId": session_id,
        "fullPath": str(jsonl_path),
        "firstPrompt": first_prompt or "No prompt",
        "title": title,
        "summary": "",
        "messageCount": msg_count,
        "created": created,
        "modified": last_timestamp or created,
        "gitBranch": first_user.get("gitBranch", ""),
        "projectPath": first_user.get("cwd", ""),
        "isSidechain": False,
    }


# A Bash tool call that actually *invokes* `git commit` is the authoritative
# signal that a commit happened. We can't just test startswith("git commit") —
# most commits are compound, e.g. "git add -A && git commit ...". So we split
# the command on shell operators and check whether any segment runs
# `git ... commit` as its subcommand (after skipping global options like
# "-C path"). This also rejects commands that merely *mention* "git commit" in
# a string, an echo, or a Python snippet — so history audits that print
# commit-like text without committing produce nothing.
#
# Given a confirmed commit invocation, we recover the (sha, summary) to show in
# two layers:
#
#   1. Preferred — git's own success line in the *result*, printed as
#      "[<branch...> <sha>] <summary>" (e.g. "[main 1a2b3c4] fix: thing" or
#      "[detached HEAD 1a2b3c4] msg"). This gives the real SHA and the committed
#      summary regardless of how the message was passed in.
#
#   2. Fallback for `git commit -q` — quiet mode SUPPRESSES that success line,
#      so layer 1 finds nothing. We then take the summary from the command's
#      own message (a `-F -` heredoc body or an inline -m), and best-effort the
#      SHA from any "<sha> <summary>" the script echoed back itself (e.g. via
#      `git log -1 --format='%h %s'`). Anchoring the SHA search on the exact
#      summary avoids picking up unrelated commits from an embedded git log.
#      A quiet commit that *failed* prints an error and echoes no SHA, so we
#      drop it (is_error and no recovered SHA) rather than show a phantom.
_COMMIT_RESULT_RE = re.compile(r"^\s*\[([^\]]+)\]\s+(.+)$", re.MULTILINE)
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_SEG_SPLIT_RE = re.compile(r"&&|\|\||[;|\n]")
_ENV_PREFIX_RE = re.compile(r"^\w+=\S*\s+")
# git global options that consume the following token as their argument.
_GIT_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def _is_git_commit_segment(seg: str) -> bool:
    """True if a single shell segment runs `git commit` as its subcommand."""
    seg = seg.strip()
    while _ENV_PREFIX_RE.match(seg):  # strip leading FOO=bar assignments
        seg = _ENV_PREFIX_RE.sub("", seg, count=1)
    if not re.match(r"^git\b", seg):
        return False
    tokens = seg.split()[1:]  # everything after "git"
    i = 0
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 2 if tokens[i] in _GIT_OPTS_WITH_ARG else 1
    return i < len(tokens) and tokens[i] == "commit"


def _command_makes_commit(cmd: str) -> bool:
    """True if any segment of a (possibly compound) command invokes git commit."""
    return any(_is_git_commit_segment(s) for s in _SEG_SPLIT_RE.split(cmd))


def _tool_result_text(block: dict) -> str:
    """Extract the text payload from a tool_result content block."""
    res = block.get("content", "")
    if isinstance(res, list):
        for r in res:
            if isinstance(r, dict) and r.get("type") == "text":
                return r.get("text", "")
        return ""
    return res if isinstance(res, str) else ""


def _commits_from_result(text: str) -> list[tuple]:
    """Pull (sha, summary) pairs out of git's commit-success output."""
    commits = []
    for m in _COMMIT_RESULT_RE.finditer(text):
        bracket, summary = m.group(1), m.group(2).strip()
        tokens = bracket.split()
        # The bracket must end in a short SHA (e.g. "main 1a2b3c4"). This
        # rejects non-commit lines like "[INFO] ..." or "[main] up to date".
        if not summary or not tokens or not _SHA_RE.match(tokens[-1]):
            continue
        commits.append((tokens[-1][:9], summary))
    return commits


# A heredoc redirect: `<<EOF`, `<<-EOF`, `<<'EOF'`, `<<"EOF"`. Group 2 is the
# delimiter word we scan for to close the body.
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
# An inline commit message: -m / --message, value either quoted or bare.
_MSG_OPT_RE = re.compile(
    r"""(?:^|\s)(?:-m|--message)(?:=|\s+)('([^']*)'|"([^"]*)"|(\S+))"""
)


def _commit_message_from_command(cmd: str) -> str:
    """Recover a commit's summary line from the command text itself.

    Used when `git commit -q` suppressed git's success line. Handles the two
    ways automation passes a message without relying on git echoing it back:
    a `-F -` heredoc (summary = first non-blank body line) or an inline
    -m/--message. Returns "" if neither is present (e.g. bare --amend).
    """
    m = _HEREDOC_RE.search(cmd)
    if m:
        delim = m.group(2)
        capturing = False
        for line in cmd.split("\n"):
            if not capturing:
                if _HEREDOC_RE.search(line):
                    capturing = True  # opener seen; body starts next line
                continue
            if line.strip() == delim:
                break  # heredoc terminator
            if line.strip():
                return line.strip()
    m = _MSG_OPT_RE.search(cmd)
    if m:
        return (m.group(2) or m.group(3) or m.group(4) or "").strip()
    return ""


def _sha_for_summary(text: str, summary: str) -> str:
    """Best-effort SHA for a quiet commit: a short hash printed immediately
    before this exact summary (e.g. a `git log -1 --format='%h %s'` echo).
    Anchored on the summary so an embedded git log of older commits can't
    supply the wrong hash. Returns "" if none is found."""
    m = re.search(r"\b([0-9a-f]{7,40})\b[ \t]+" + re.escape(summary), text)
    return m.group(1)[:9] if m else ""


def _dedupe_commits(commits: list[tuple]) -> list[tuple]:
    """Collapse commits that share a summary (e.g. the soft-reset + recommit
    amend workflow), keeping the latest SHA where the summary first appeared."""
    seen = {}  # summary -> index in result
    result = []
    for sha, summary in commits:
        if summary in seen:
            result[seen[summary]] = (sha, summary)
        else:
            seen[summary] = len(result)
            result.append((sha, summary))
    return result


def parse_session_jsonl(jsonl_path: str) -> dict:
    """Parse a session JSONL file to extract title, prompts, commits, and files."""
    path = Path(jsonl_path)
    if not path.exists():
        return {}

    title = ""
    user_prompts = []  # list of (serial_number, text)
    prompt_num = 0
    git_commits = []  # list of (sha, message) in order seen
    files_edited = set()
    commit_cmds = {}  # tool_use id -> command text, for real `git commit` calls

    with open(path) as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Session title (AI-generated or user-renamed) — keep the latest.
            if obj.get("type") == "ai-title":
                title = obj.get("aiTitle") or title
                continue

            msg = obj.get("message", {})
            if not isinstance(msg, dict):
                continue

            role = msg.get("role", "")
            content = msg.get("content", "")

            # Extract user prompts
            if role == "user":
                text = ""
                if isinstance(content, str) and content.strip():
                    text = content.strip()
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            text = c["text"].strip()
                            break
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
                        if name == "Bash":
                            cmd = c.get("input", {}).get("command", "")
                            if _command_makes_commit(cmd):
                                commit_cmds[c.get("id")] = cmd
                        elif name in ("Write", "Edit"):
                            fp = c.get("input", {}).get("file_path", "")
                            if fp:
                                files_edited.add(fp)
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
    }


def format_age(iso_str: str) -> str:
    """Format an ISO timestamp as a human-readable age string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            m = seconds // 60
            return f"{m}m ago"
        elif seconds < 86400:
            h = seconds // 3600
            return f"{h}h ago"
        else:
            d = seconds // 86400
            return f"{d}d ago"
    except (ValueError, TypeError):
        return "unknown"


def format_duration(created: str, modified: str) -> str:
    """Format session duration from created/modified timestamps."""
    try:
        c = datetime.fromisoformat(created)
        m = datetime.fromisoformat(modified)
        delta = m - c
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m"
        else:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return f"{h}h{m}m" if m else f"{h}h"
    except (ValueError, TypeError):
        return "?"


def truncate(text: str, length: int) -> str:
    """Truncate text to length, adding ellipsis if needed."""
    text = text.replace("\n", " ").strip()
    if len(text) <= length:
        return text
    return text[: length - 1] + "\u2026"


HOME = str(Path.home())


def shorten_path(path: str) -> str:
    """Replace $HOME prefix with ~ for display."""
    if path.startswith(HOME + "/"):
        return "~" + path[len(HOME):]
    if path == HOME:
        return "~"
    return path


def decode_project_key(key: str) -> str:
    """Best-effort decode of a Claude project-dir key back to a real path.

    The encoding (every "/" in the cwd becomes "-") is lossy: a "-" in the key
    may be a path separator or a literal character in a directory name (e.g.
    "claude-code-extensions"). We resolve the ambiguity by walking the
    filesystem, splitting on "-" only where the resulting directory actually
    exists, and preferring the shortest component that does. If the path no
    longer exists on disk we can't know, so we fall back to treating every
    "-" as "/".
    """
    if not key.startswith("-"):
        return key
    naive = "/" + key[1:].replace("-", "/")
    segs = key[1:].split("-")
    path = Path("/")
    i = 0
    while i < len(segs):
        comp = segs[i]
        j = i
        # Grow the component with "-" until it names a real directory.
        while not (path / comp).exists() and j + 1 < len(segs):
            j += 1
            comp = f"{comp}-{segs[j]}"
        if not (path / comp).exists():
            return naive  # unresolvable from here — best-effort decode
        path = path / comp
        i = j + 1
    return str(path)


# --- Color handling -------------------------------------------------------
# ANSI styling is emitted only when enabled (a terminal, by default), so
# piping into `less` or redirecting to a file yields clean, plain text.
# Honors the NO_COLOR convention (https://no-color.org) and the --color flag.
_COLOR_ENABLED = False  # finalized in main() from --color + tty state


def _resolve_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(code: str, text) -> str:
    """Wrap text in an ANSI SGR sequence when color is on, else return plain."""
    text = str(text)
    if not _COLOR_ENABLED:
        return text
    return f"\033[{code}m{text}\033[0m"


def display_session(idx: int, entry: dict, parsed: dict | None, verbose: bool):
    """Display a single session entry."""
    sid = entry["sessionId"]
    age = format_age(entry.get("modified", entry.get("created", "")))
    duration = format_duration(entry.get("created", ""), entry.get("modified", ""))
    branch = entry.get("gitBranch", "")
    # Session title (AI-generated or user-renamed). Prefer the freshly parsed
    # value; fall back to the listing entry, then the legacy index "summary".
    title = (parsed or {}).get("title") or entry.get("title") or entry.get("summary", "")
    msg_count = entry.get("messageCount", 0)
    project = entry.get("projectPath", "")

    # Header line
    branch_str = f"  [{branch}]" if branch else ""
    print(f"  {c('1;33', idx)}  {age}, {duration}, {msg_count} msgs{branch_str}  {sid}")

    # Title
    if title:
        print(f"     {c('1', truncate(title, 90))}")

    # Prompts: show arc (first, second-to-last, last) with serial numbers
    if parsed and parsed.get("user_prompts"):
        prompts = parsed["user_prompts"]
        selected = _select_arc_prompts(prompts)
        for num, text in selected:
            label = f"#{num:<3d}"
            print(f"     {c('2', label + ' ' + truncate(text, 81))}")
    else:
        # Fall back to firstPrompt from index
        first = entry.get("firstPrompt", "")
        if first and first != "No prompt":
            print(f"     {c('2', '> ' + truncate(first, 85))}")

    # Git commits — show every commit made during the session.
    if parsed and parsed.get("git_commits"):
        for sha, msg in parsed["git_commits"]:
            sha_str = f"{sha} " if sha else ""
            print(f"     {c('32', '* ' + sha_str + truncate(msg, 83 - len(sha_str)))}")

    # Files (verbose only)
    if verbose and parsed and parsed.get("files_edited"):
        files = parsed["files_edited"]
        limit = 10
        for fp in files[:limit]:
            # Show relative to project if possible
            project = entry.get("projectPath", "")
            if project and fp.startswith(project):
                fp = fp[len(project) :].lstrip("/")
            else:
                fp = shorten_path(fp)
            print(f"     {c('36', '~ ' + fp)}")
        remaining = len(files) - limit
        if remaining > 0:
            print(f"     {c('36', f'  ...and {remaining} more file(s)')}")

    print()


def _select_arc_prompts(prompts: list[tuple]) -> list[tuple]:
    """Select prompts that tell the session's story: first, second-to-last, last."""
    if len(prompts) <= 3:
        return prompts

    selected = [prompts[0]]
    if len(prompts) >= 3:
        selected.append(prompts[-2])
    selected.append(prompts[-1])
    return selected


def main():
    parser = argparse.ArgumentParser(
        description="Smart session resume for Claude Code"
    )
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=10,
        help="Number of sessions to show (default: 10)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show extra details (files edited)"
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Show sessions from all projects, not just current directory",
    )
    parser.add_argument(
        "-p",
        "--project",
        type=str,
        default=None,
        help="Show sessions for a specific project path",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List sessions and exit, without the interactive resume prompt",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="When to colorize output (default: auto — only on a terminal)",
    )
    args = parser.parse_args()

    # Colorize only on a terminal by default, so `| less` and redirects stay clean.
    global _COLOR_ENABLED
    _COLOR_ENABLED = _resolve_color(args.color)

    # Determine which project(s) to show
    if args.all:
        project_dirs = all_project_dirs()
        if not project_dirs:
            print("No Claude Code sessions found.", file=sys.stderr)
            sys.exit(1)
    else:
        target = args.project or os.getcwd()
        project_dir = find_project_dir(target)
        if project_dir is None:
            print(
                f"No Claude Code sessions found for: {target}", file=sys.stderr
            )
            print(
                "Use --all to see sessions from all projects, or --project <path>.",
                file=sys.stderr,
            )
            sys.exit(1)
        project_dirs = [project_dir]

    # Collect all sessions, skipping those without JSONL files (unresumable)
    all_sessions = []
    for pd in project_dirs:
        entries = load_sessions_index(pd)
        for e in entries:
            e["_project_dir"] = str(pd)
            # Check if the session's JSONL file actually exists
            fp = e.get("fullPath", "")
            if fp and Path(fp).exists():
                all_sessions.append(e)
            elif (pd / f"{e['sessionId']}.jsonl").exists():
                all_sessions.append(e)
            # else: stale index entry, skip

    # Sort by modified time (most recent first) to pick the top N,
    # then reverse so newest appears at the bottom (closest to prompt)
    all_sessions.sort(
        key=lambda e: e.get("modified", e.get("created", "")), reverse=True
    )
    sessions = all_sessions[: args.count]
    sessions.reverse()

    if not sessions:
        print("No sessions found.", file=sys.stderr)
        sys.exit(1)

    # Show header
    if args.all:
        print(f"\n{c('1', f'Claude Code Sessions (all projects, showing {len(sessions)})')}\n")
    else:
        target = args.project or os.getcwd()
        print(f"\n{c('1', f'Claude Code Sessions for {shorten_path(target)} (showing {len(sessions)})')}\n")

    # Parse JSONL files where available, display sessions
    current_project = None
    for i, entry in enumerate(sessions, 1):
        # Show project header if --all and project changed. Prefer the session's
        # recorded cwd (already a real path); fall back to decoding the project
        # directory key only when cwd is unavailable.
        if args.all:
            proj = entry.get("projectPath") or decode_project_key(
                Path(entry["_project_dir"]).name
            )
            if proj != current_project:
                current_project = proj
                print(f"  {c('1;35', f'--- {shorten_path(proj)} ---')}\n")

        # Try to parse JSONL — fullPath in the index may be stale,
        # so also check for the file by session ID in the project dir
        jsonl_path = entry.get("fullPath", "")
        if not jsonl_path or not Path(jsonl_path).exists():
            candidate = Path(entry["_project_dir"]) / f"{entry['sessionId']}.jsonl"
            if candidate.exists():
                jsonl_path = str(candidate)
        parsed = parse_session_jsonl(jsonl_path) if jsonl_path else None

        display_session(i, entry, parsed, args.verbose)

    if args.list:
        sys.exit(0)

    # Selection — Enter defaults to the last (most recent) session
    default = len(sessions)
    print(f"{c('1', f'Select session to resume [{default}] (q to quit):')} ", end="")
    try:
        choice = input().strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    if choice.lower() in ("q", "quit"):
        sys.exit(0)

    if choice == "":
        num = default
    else:
        try:
            num = int(choice)
        except ValueError:
            print(f"Invalid selection: {choice}", file=sys.stderr)
            sys.exit(1)

    if num < 1 or num > len(sessions):
        print(f"Selection out of range: {num}", file=sys.stderr)
        sys.exit(1)

    selected = sessions[num - 1]
    session_id = selected["sessionId"]
    project_path = selected.get("projectPath", "")

    # Handle stale project path (e.g., directory was renamed)
    if project_path and not os.path.isdir(project_path):
        print(
            f"\n  {c('33', f'Note: recorded project path no longer exists: {shorten_path(project_path)}')}",
            file=sys.stderr,
        )
        print(
            f"  {c('33', f'Resuming from current directory instead: {shorten_path(os.getcwd())}')}",
            file=sys.stderr,
        )
        project_path = os.getcwd()

    # Show command and confirm
    cmd = f"claude --resume {session_id}"
    needs_cd = project_path and os.path.realpath(project_path) != os.path.realpath(os.getcwd())
    if needs_cd:
        print(f"\n  cd {shorten_path(project_path)} && {cmd}\n")
    else:
        print(f"\n  {cmd}\n")

    print(f"{c('1', 'Run this command? [Y/n]')} ", end="")
    try:
        confirm = input().strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    if confirm.lower() in ("n", "no"):
        sys.exit(0)

    # Execute
    if needs_cd:
        os.chdir(project_path)
    os.execvp("claude", ["claude", "--resume", session_id])


if __name__ == "__main__":
    main()
