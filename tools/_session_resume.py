"""Shared display, selection, and transcript helpers for session browsers."""

import argparse
import json
import os
import re
import shlex
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


def safe_text(text):
    """Prevent transcript data from injecting terminal control sequences."""
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(text))
    return "".join(" " if ch in "\n\t" else ch for ch in text
                   if not unicodedata.category(ch).startswith("C") or ch in "\n\t")


def warn(message):
    print(f"Warning: {message}", file=sys.stderr)


def read_jsonl(path):
    """Stream object records and report incomplete or malformed records."""
    bad = 0
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("record must be an object")
                except ValueError:
                    bad += 1
                    continue
                yield record
    finally:
        if bad:
            warn(f"{path}: skipped {bad} malformed or incomplete record(s)")


def valid_session_id(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value.lower()
    except ValueError:
        return False


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("count must be positive")
    return number


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
    """Drop repeated results without conflating distinct commits by subject."""
    return list(dict.fromkeys(commits))


def format_age(iso_str: str) -> str:
    """Format an ISO timestamp as a human-readable age string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        seconds = max(0, int(delta.total_seconds()))
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
        if c.tzinfo is None:
            c = c.replace(tzinfo=timezone.utc)
        if m.tzinfo is None:
            m = m.replace(tzinfo=timezone.utc)
        delta = m - c
        seconds = max(0, int(delta.total_seconds()))
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
    text = safe_text(text).replace("\n", " ").strip()
    if len(text) <= length:
        return text
    return text[: length - 1] + "\u2026"


USER_HOME_PATH = str(Path.home())


def shorten_path(path: str) -> str:
    """Replace $HOME prefix with ~ for display."""
    if path.startswith(USER_HOME_PATH + "/"):
        return "~" + path[len(USER_HOME_PATH):]
    if path == USER_HOME_PATH:
        return "~"
    return path


# --- Color handling -------------------------------------------------------
# ANSI styling is emitted only when enabled (a terminal, by default), so
# piping into `less` or redirecting to a file yields clean, plain text.
# Honors the NO_COLOR convention (https://no-color.org) and the --color flag.


def _resolve_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def style(code: str, text, enabled: bool = False) -> str:
    """Wrap text in an ANSI SGR sequence when color is on, else return plain."""
    text = safe_text(str(text))
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def display_session(idx: int, entry: dict, parsed: dict | None, verbose: bool, color=False):
    """Display a single session entry."""
    c = lambda code, text: style(code, text, color)
    sid = safe_text(entry["sessionId"])
    age = format_age(entry.get("modified", entry.get("created", "")))
    duration = format_duration(entry.get("created", ""), entry.get("modified", ""))
    branch = safe_text(entry.get("gitBranch", ""))
    # Session title (AI-generated or user-renamed). Prefer the freshly parsed
    # value; fall back to the listing entry, then the legacy index "summary".
    title = (parsed or {}).get("title") or entry.get("title") or entry.get("summary", "")
    msg_count = (parsed or {}).get("messageCount", entry.get("messageCount", "?"))
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
            if project and fp.startswith(project.rstrip("/") + "/"):
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


def run_browser(adapter, argv=None):
    """Browse one explicitly selected harness store and resume via native argv."""
    parser = argparse.ArgumentParser(description=f"Enriched session resume for {adapter.name}")
    parser.add_argument("-n", "--count", type=positive_int, default=10,
                        help="Number of recent sessions to show (default: 10)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show edited files")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("-a", "--all", action="store_true", help="Show all projects")
    scope.add_argument("-p", "--project", help="Filter by a project path")
    parser.add_argument("-l", "--list", action="store_true", help="List sessions without resuming")
    parser.add_argument("--json", action="store_true", help="List sessions as JSON")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    parser.add_argument(adapter.directory_option, dest="data_dir", type=Path,
                        help=f"Session store (default: ${adapter.directory_env} or {adapter.default_dir})")
    parser.add_argument("--resume-cwd", type=Path,
                        help="Explicit working directory override when resuming")
    adapter.add_arguments(parser)
    args = parser.parse_args(argv)
    root = (args.data_dir or Path(os.environ.get(adapter.directory_env) or adapter.default_dir)).expanduser().resolve()
    target = Path(args.project or Path.cwd()).expanduser().resolve()
    try:
        entries = adapter.discover(root, args)
        if not args.all:
            entries = [entry for entry in entries if entry.get("projectPath")
                       and Path(entry["projectPath"]).expanduser().resolve() == target]
        entries.sort(key=lambda entry: (entry["_mtime"], entry["sessionId"]), reverse=True)
        sessions = []
        for entry in entries:
            if len(sessions) == args.count:
                break
            try:
                parsed = adapter.parse(entry)
                if not parsed.get("title"):
                    parsed["title"] = entry.get("title", "")
            except (OSError, ValueError) as error:
                warn(f"Could not read session {entry['sessionId']}: {error}")
                continue
            sessions.append((entry, parsed))
        sessions.reverse()
    except (OSError, ValueError) as error:
        print(f"Cannot read {adapter.name} sessions: {error}", file=sys.stderr)
        return 1
    if not sessions:
        print(f"No {adapter.name} sessions found in {root}"
              + ("." if args.all else f" for {target}. Use --all to see other projects."), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([{**{k: v for k, v in entry.items() if not k.startswith("_")},
                           **parsed} for entry, parsed in sessions], ensure_ascii=True, indent=2))
        return 0
    color = _resolve_color(args.color)
    c = lambda code, text: style(code, text, color)
    label = "all projects" if args.all else shorten_path(str(target))
    print(f"\n{c('1', f'{adapter.name} Sessions ({label}, showing {len(sessions)})')}\n")
    current_project = None
    for number, (entry, parsed) in enumerate(sessions, 1):
        project = entry.get("projectPath", "")
        if args.all and project != current_project:
            print(f"  {c('1;35', shorten_path(project))}\n")
            current_project = project
        display_session(number, entry, parsed, args.verbose, color)
    if args.list or not sys.stdin.isatty() or not sys.stdout.isatty():
        return 0
    try:
        choice = input(f"Select session to resume [{len(sessions)}] (q to quit): ").strip()
        if choice.lower() in ("q", "quit"):
            return 0
        number = int(choice) if choice else len(sessions)
        if not 1 <= number <= len(sessions):
            raise ValueError("selection out of range")
        entry = sessions[number - 1][0]
        recorded = entry.get("projectPath", "")
        directory = args.resume_cwd or (Path(recorded) if recorded else None)
        if directory is None or not directory.expanduser().is_dir():
            print("The recorded project directory is missing. Choose the intended "
                  "directory with --resume-cwd before resuming.", file=sys.stderr)
            return 1
        directory = directory.expanduser().resolve()
        command = adapter.command(entry, args)
        print(f"\n  cd {shlex.quote(str(directory))} && {shlex.join(command)}\n")
        confirm = input("Run this command? [Y/n] ").strip().lower()
        if confirm in ("n", "no"):
            return 0
        if confirm not in ("", "y", "yes"):
            print("Expected yes or no; no session was started.", file=sys.stderr)
            return 1
        # Only the child uses this selected harness store; never read another
        # profile's sessions or silently resume from its default directory.
        environment = os.environ.copy()
        environment[adapter.directory_env] = str(root)
        os.chdir(directory)
        os.execvpe(command[0], command, environment)
    except (EOFError, KeyboardInterrupt):
        print()
        return 0
    except (OSError, ValueError) as error:
        print(f"Cannot resume session: {error}", file=sys.stderr)
        return 1
    return 0
