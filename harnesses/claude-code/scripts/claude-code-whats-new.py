#!/usr/bin/env python3
"""Correlate Claude Code release notes with this machine's configuration.

Prints the releases published since the last digest, with each bullet tagged
by the parts of your environment it touches, so a reader can tell "this
changes something I configured" from "this is about a feature I never use".
A second mode searches the whole changelog for when a topic first appeared
and what was changed afterwards.

The digest is deliberately not a summary: it filters and tags, and always
reports what it withheld. Judgement belongs to the reader, or to the skill
that invokes this utility.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
from _text import safe_text, warn
from _whats_new import (
    TERMINALS, detect_terminal,
    cache_path, day, load_changelog, load_state, parse_changelog, release_dates,
    save_state, search, select, state_path, version_key,
)

CHANGELOG_URL = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
PACKUMENT_URL = "https://registry.npmjs.org/@anthropic-ai/claude-code"
STATE_NAME = "claude-code-whats-new.json"
CHANGELOG_CACHE = "claude-code-changelog.md"
DATES_CACHE = "claude-code-release-dates.json"
DEFAULT_FIRST_RUN = 5
DEFAULT_MAX_RELEASES = 25

# Bullets another host or platform owns. Each filter names the evidence that
# makes it safe, and the digest always reports how many it removed.
FILTERS = (
    ("[VSCode]", "ide", "no IDE extension found"),
    ("[JetBrains]", "ide", "no IDE extension found"),
    ("[Claude Tag]", "slack", "Claude in Slack is not configured here"),
    ("Windows:", "windows", "not this platform"),
    ("macOS:", "macos", "not this platform"),
)

# Tag, pattern, and the fingerprint predicate that makes the tag meaningful.
# Patterns stay broad; the predicate is what keeps a tag off an unrelated setup.
SIGNALS = (
    ("statusline", r"status ?line", lambda f: f["statusline"]),
    ("hooks", r"\bhooks?\b|PreToolUse|PostToolUse|SessionStart|SessionEnd|UserPromptSubmit|PreCompact",
     lambda f: bool(f["hooks"])),
    ("permissions", r"permission|deny rule|allow rule|allowlist|\bsandbox\b",
     lambda f: any(f["rules"].values())),
    ("auto-mode", r"auto[- ]mode|auto[- ]accept|defaultMode",
     lambda f: f["default_mode"] in ("auto", "acceptEdits")),
    ("plugins", r"\bplugins?\b|marketplace", lambda f: bool(f["plugins"])),
    ("mcp", r"\bMCP\b|mcp__", lambda f: bool(f["mcp"])),
    ("output-style", r"output[- ]style", lambda f: bool(f["output_style"])),
    ("vim", r"\bvim\b", lambda f: f["editor_mode"] == "vim"),
    ("fullscreen", r"fullscreen|full-screen", lambda f: f["tui"] == "fullscreen"),
    ("compaction", r"\bcompact", lambda f: True),
    ("thinking", r"\bthinking\b|\bthought\b", lambda f: f["thinking"]),
    ("remote-control", r"remote control|remote session|cloud session|headless session",
     lambda f: f["remote_control"]),
    ("attribution", r"attribution|Co-Authored-By|co-author", lambda f: f["attribution"]),
    ("memory", r"\bmemory\b|MEMORY\.md", lambda f: f["memory"]),
    ("skills", r"\bskills?\b|SKILL\.md", lambda f: bool(f["skills"])),
    ("subagents", r"subagent|agent team|background agent|\bagent view\b",
     lambda f: bool(f["agents"]) or bool(f["plugins"])),
    ("sessions", r"/resume\b|session history|--continue\b|resuming a session",
     lambda f: f["sessions"]),
    ("telemetry", r"OTEL|OpenTelemetry|telemetry", lambda f: bool(f["otel"])),
    ("deployment", r"\bBedrock\b|\bVertex\b|\bFoundry\b|\bgateway\b|ANTHROPIC_BASE_URL|third-party",
     lambda f: bool(f["deployment"])),
    ("notifications", r"notification", lambda f: f["notifications"]),
    ("git", r"\bgit\b|worktree|pull request|commit message", lambda f: f["git"]),
    ("linux", r"\bLinux\b|Wayland|\bX11\b|\bWSL\b", lambda f: f["platform"] == "linux"),
    # A new knob matches no existing configuration by definition, so these
    # unconditional tags keep --relevant-only from hiding what to adopt next.
    ("new-setting", r"`(CLAUDE_CODE|ANTHROPIC|OTEL|DISABLE)_[A-Z0-9_]+`|\bsetting `", lambda f: True),
    ("new-command", r"^(Added|Changed) .*`/[a-z][\w-]*`", lambda f: True),
    ("behavior-change", r"^(Changed|Removed)\b|no longer\b|\bdeprecat", lambda f: True),
)

MODEL_FAMILIES = ("opus", "sonnet", "haiku", "fable")

# A session served by Bedrock, Vertex, Foundry, or a gateway takes a different
# code path from a first-party one, and the changelog says so explicitly.
DEPLOYMENT_ENV = re.compile(
    r"^(CLAUDE_CODE_USE_(VERTEX|BEDROCK)|CLAUDE_CODE_GATEWAY[A-Z_]*"
    r"|ANTHROPIC_(VERTEX|BEDROCK)_[A-Z_]+|ANTHROPIC_BASE_URL)$")

# Variables a running session injects into its own children. They describe this
# invocation rather than the user's configuration, so they are not reported.
RUNTIME_ENV = re.compile(
    r"^CLAUDE_(PID|EFFORT|PLUGIN_(DATA|ROOT)|PROJECT_DIR"
    r"|CODE_(SESSION_ID|ENTRYPOINT|EXECPATH|CHILD_SESSION|SESSION_ATTENDED"
    r"|MESSAGING_[A-Z_]+|3P_PROBE_[A-Z_]+))$")


def read_json(path):
    """Load a settings document, treating anything unusable as absent."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        warn(f"{path}: ignoring unreadable configuration ({error})")
        return {}
    return data if isinstance(data, dict) else {}


def read_settings(paths):
    """Load each settings file once, however many roles it plays.

    Started from the home directory, the project's .claude/settings.json is
    the user's own file, and reading it twice doubles every hook and
    permission rule in it. File identity rather than path equality also
    covers a .claude directory reached through a symlink.
    """
    documents, seen = [], set()
    for path in paths:
        try:
            status = Path(path).stat()
        except OSError:
            documents.append(read_json(path))  # Reports what is wrong, or is absent.
            continue
        identity = (status.st_dev, status.st_ino)
        if identity not in seen:
            seen.add(identity)
            documents.append(read_json(path))
    return documents


def running_version(claude_dir):
    """Identify the running release, preferring the CLI's own answer."""
    try:
        output = subprocess.run(["claude", "--version"], capture_output=True, text=True,
                                timeout=20, check=True).stdout
        found = re.search(r"\d+\.\d+\.\d+", output)
        if found:
            return found.group(0), []
    except (OSError, subprocess.SubprocessError):
        pass  # Fall back to the installed payloads below.
    directory = Path.home() / ".local/share/claude/versions"
    try:
        installed = sorted((p.name for p in directory.iterdir() if re.fullmatch(r"[\d.]+", p.name)),
                           key=version_key)
    except OSError:
        installed = []
    return (installed[-1] if installed else None), installed


def fingerprint(claude_dir, project):
    """Describe the configuration that decides whether a change matters here.

    Environment variables contribute their names only. Their values can hold
    credentials and must never reach a digest that gets read back out loud.
    """
    settings = read_settings([claude_dir / "settings.json",
                              claude_dir / "settings.local.json",
                              project / ".claude/settings.json",
                              project / ".claude/settings.local.json",
                              Path("/etc/claude-code/managed-settings.json")])

    def setting(key, default=None):
        for source in reversed(settings):
            if key in source:
                return source[key]
        return default

    rules = {kind: 0 for kind in ("allow", "deny", "ask")}
    for source in settings:
        permissions = source.get("permissions")
        if isinstance(permissions, dict):
            for kind in rules:
                rules[kind] += len(permissions.get(kind) or [])
    default_mode = ""
    for source in settings:
        permissions = source.get("permissions")
        if isinstance(permissions, dict) and permissions.get("defaultMode"):
            default_mode = permissions["defaultMode"]

    hooks = []
    for source in settings:
        for event, entries in (source.get("hooks") or {}).items():
            for entry in entries if isinstance(entries, list) else []:
                matcher = entry.get("matcher") if isinstance(entry, dict) else None
                hooks.append(f"{event}[{matcher}]" if matcher else str(event))

    plugins = sorted({name for source in settings
                      for name, on in (source.get("enabledPlugins") or {}).items() if on})

    root = read_json(Path.home() / ".claude.json")
    mcp = sorted(set(root.get("mcpServers") or {})
                 | set((root.get("projects", {}).get(str(project), {}) or {}).get("mcpServers") or {}))

    def names(directory, suffix=None):
        try:
            return sorted(p.name for p in (claude_dir / directory).iterdir()
                          if suffix is None or p.name.endswith(suffix))
        except OSError:
            return []

    model = str(setting("model") or root.get("model") or "")
    version, installed = running_version(claude_dir)
    terminal, evidence, disagrees = detect_terminal()
    # glob() is lazy, so the match has to be forced; a bare any() over the
    # generators would report every location as a hit.
    ide = any(next(Path.home().joinpath(base).glob(pattern), None) is not None
              for base, pattern in ((".vscode/extensions", "*anthropic*"),
                                    (".vscode-server/extensions", "*anthropic*"),
                                    (".cursor/extensions", "*anthropic*"),
                                    (".windsurf/extensions", "*anthropic*"),
                                    (".local/share/JetBrains", "*/claude*")))
    return {
        "platform": sys.platform,
        "version": version,
        "installed": installed,
        "term": os.environ.get("TERM", ""),
        "term_program": os.environ.get("TERM_PROGRAM", ""),
        "terminal": terminal,
        "terminal_evidence": evidence,
        "term_disagrees": disagrees,
        "multiplexer": ("tmux" if os.environ.get("TMUX") else
                        "screen" if os.environ.get("STY") else ""),
        "tui": setting("tui", ""),
        "editor_mode": setting("editorMode", root.get("editorMode", "")),
        "theme": setting("theme", ""),
        "default_mode": default_mode,
        "rules": rules,
        "model": model,
        "effort": setting("effortLevel", ""),
        "thinking": bool(setting("alwaysThinkingEnabled")),
        "auto_compact": bool(setting("autoCompactEnabled", root.get("autoCompactEnabled", True))),
        "remote_control": bool(setting("remoteControlAtStartup")),
        "notifications": (setting("preferredNotifChannel", root.get("preferredNotifChannel", ""))
                          not in ("", "notifications_disabled")),
        "output_style": setting("outputStyle", ""),
        "attribution": bool(setting("attribution")),
        "statusline": bool(setting("statusLine")),
        "hooks": hooks,
        "plugins": plugins,
        "mcp": mcp,
        "skills": names("skills"),
        "agents": names("agents", ".md"),
        "memory": any((claude_dir / "projects").glob("*/memory")),
        "sessions": (claude_dir / "projects").is_dir(),
        "git": (project / ".git").exists(),
        "ide": ide,
        "slack": False,
        "windows": sys.platform.startswith("win"),
        "macos": sys.platform == "darwin",
        "otel": sorted(name for name in os.environ if name.startswith("OTEL_")),
        "deployment": sorted(name for name in os.environ if DEPLOYMENT_ENV.match(name)),
        "env": sorted(name for name in os.environ
                      if name.startswith(("CLAUDE_", "ANTHROPIC_", "DISABLE_", "OTEL_"))
                      and not RUNTIME_ENV.match(name)),
    }


def matchers(marks):
    """Compile the signals whose predicate holds, plus model and terminal tags."""
    active = [(tag, re.compile(pattern, re.I))
              for tag, pattern, applies in SIGNALS if applies(marks)]
    for family in MODEL_FAMILIES:
        if family in marks["model"].lower():
            active.append((f"model:{family}", re.compile(rf"\b{family}\b", re.I)))
    if marks["effort"]:
        active.append(("effort", re.compile(r"effort|thinking budget", re.I)))
    terminal = marks["terminal"]
    if terminal:
        known = {name: pattern for name, _, pattern in TERMINALS}
        active.append((f"term:{terminal}",
                       re.compile(known.get(terminal, rf"\b{re.escape(terminal)}\b"), re.I)))
    if marks["multiplexer"]:
        active.append((marks["multiplexer"], re.compile(rf"\b{marks['multiplexer']}\b", re.I)))
    return active


def excluded(bullet, marks, enabled=True):
    """Return the reason another host or platform owns this bullet, if any."""
    if not enabled:
        return None
    for prefix, key, reason in FILTERS:
        if bullet.startswith(prefix) and not marks[key]:
            return f"{prefix} ({reason})"
    return None


def digest(releases, marks, filtering=True):
    """Tag every bullet in the window and tally what the filters removed."""
    active, kept, dropped = matchers(marks), [], {}
    for release in releases:
        bullets = []
        for bullet in release["bullets"]:
            reason = excluded(bullet, marks, filtering)
            if reason:
                dropped[reason] = dropped.get(reason, 0) + 1
                continue
            bullets.append({"text": bullet,
                            "tags": [tag for tag, expression in active if expression.search(bullet)]})
        kept.append({"version": release["version"], "bullets": bullets})
    return kept, dropped


def describe(marks):
    """Summarize the configuration the tags were derived from."""
    rules = ", ".join(f"{count} {kind}" for kind, count in marks["rules"].items() if count)
    lines = [
        f"platform     : {marks['platform']}"
        + (", IDE extension present" if marks["ide"] else ", no IDE extension"),
        f"terminal     : {marks['terminal'] or 'unidentified'} "
        f"(via {marks['terminal_evidence']}), TERM={marks['term'] or 'unset'}"
        + (f", TERM_PROGRAM={marks['term_program']}" if marks["term_program"] else "")
        + (f", inside {marks['multiplexer']}" if marks["multiplexer"] else "")
        + ("  <- TERM does not name this terminal" if marks["term_disagrees"] else ""),
        f"running      : {marks['version'] or 'unknown'}"
        + (f" (installed: {', '.join(marks['installed'][-3:])})" if marks["installed"] else ""),
        f"interface    : tui={marks['tui'] or 'default'}, editor={marks['editor_mode'] or 'default'}, "
        f"style={marks['output_style'] or 'default'}, theme={marks['theme'] or 'default'}",
        f"model        : {marks['model'] or 'default'}, effort={marks['effort'] or 'default'}, "
        f"thinking={'always' if marks['thinking'] else 'default'}, "
        f"served by {', '.join(marks['deployment']) or 'the first-party API'}",
        f"permissions  : defaultMode={marks['default_mode'] or 'default'}, {rules or 'no rules'}",
        f"session      : autoCompact={'on' if marks['auto_compact'] else 'off'}, "
        f"remoteControl={'on' if marks['remote_control'] else 'off'}, "
        f"notifications={'on' if marks['notifications'] else 'off'}, "
        f"attribution={'configured' if marks['attribution'] else 'default'}",
        f"hooks        : {', '.join(marks['hooks']) or 'none'}",
        f"plugins      : {', '.join(marks['plugins']) or 'none'}",
        f"mcp servers  : {', '.join(marks['mcp']) or 'none'}",
        f"extras       : statusline={'custom' if marks['statusline'] else 'default'}, "
        f"skills={', '.join(marks['skills']) or 'none'}, agents={', '.join(marks['agents']) or 'none'}, "
        f"memory={'present' if marks['memory'] else 'none'}",
        f"env vars     : {', '.join(marks['env']) or 'none'} (names only)",
    ]
    return lines


def unmatched(window):
    """Count the bullets no signal matched, whether or not they are shown."""
    return sum(not bullet["tags"] for release in window for bullet in release["bullets"])


def render(window, marks, dropped, dates, header, relevant_only):
    """Print the digest: provenance, environment, both counts, then bullets.

    Both counts lead the bullets so a reader paging through a long digest has
    the exact numbers before its first page ends, and never has to tally them.
    """
    out = [header, "", "## Environment", *describe(marks), "",
           f"## Signals watched: {', '.join(tag for tag, _ in matchers(marks))}"]
    if dropped:
        total = sum(dropped.values())
        out += ["", f"## Withheld: {total} bullet(s) belonging to another host or platform"]
        out += [f"  {count:4d}  {reason}" for reason, count in sorted(dropped.items())]
        out += ["  Add --no-filter to include them."]
    unread = unmatched(window)
    out += ["", f"## Unmatched: {unread} bullet(s) matched no signal for this setup, marked [-]"]
    if relevant_only and unread:
        out += ["  Not shown because of --relevant-only; re-run without it to read them."]
    for release in window:
        shown = [b for b in release["bullets"] if b["tags"] or not relevant_only]
        if not shown:
            continue
        out += ["", f"## {release['version']}  {day(dates.get(release['version']))}"]
        for bullet in shown:
            tags = ",".join(bullet["tags"]) if bullet["tags"] else "-"
            out.append(f"[{tags}] {safe_text(bullet['text'])}")
    print("\n".join(out))


def topics(releases, patterns, dates, limit):
    """Trace a subject through the changelog, oldest mention first."""
    hits = search(releases, patterns)
    if not hits:
        print(f"No changelog entry matches: {', '.join(patterns)}")
        return
    print(f"# {len(hits)} matching entries for: {', '.join(patterns)}")
    print(f"# First appeared in {hits[0][0]} ({day(dates.get(hits[0][0]))}), "
          f"most recent {hits[-1][0]} ({day(dates.get(hits[-1][0]))})")
    shown = hits if limit is None else hits[-limit:]
    if len(shown) < len(hits):
        print(f"# Showing the {len(shown)} most recent; pass --limit 0 for all")
    print()
    for version, bullet in shown:
        print(f"{version:>10}  {day(dates.get(version))}  {safe_text(bullet)}")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--releases", type=int, metavar="N",
                        help="the N most recent releases instead of the stored baseline")
    window.add_argument("--since", metavar="VERSION",
                        help="releases published after VERSION (exclusive)")
    window.add_argument("--days", type=int, metavar="N", help="releases from the last N days")
    window.add_argument("--months", type=int, metavar="N", help="releases from the last N months")
    parser.add_argument("--topic", action="append", metavar="PATTERN",
                        help="search the whole changelog instead of a window (repeatable; "
                             "patterns are alternatives, so pass a feature's several names)")
    parser.add_argument("--limit", type=int, default=40, metavar="N",
                        help="most recent topic matches to print; 0 for all (default: 40)")
    parser.add_argument("--commit", action="store_true",
                        help="record the newest release in the window as the new baseline")
    parser.add_argument("--relevant-only", action="store_true",
                        help="print only bullets that matched an environment signal")
    parser.add_argument("--no-filter", action="store_true",
                        help="keep bullets owned by another host or platform")
    parser.add_argument("--offline", action="store_true", help="never use the network")
    parser.add_argument("--max-releases", type=int, default=DEFAULT_MAX_RELEASES, metavar="N",
                        help=f"refuse a window wider than N releases unless --relevant-only "
                             f"is given (default: {DEFAULT_MAX_RELEASES})")
    parser.add_argument("--claude-dir", type=Path, help="configuration directory to inspect")
    parser.add_argument("--state", type=Path, help="baseline state file")
    parser.add_argument("--changelog", type=Path, help="read the changelog from this file")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="project directory")
    parser.add_argument("--json", action="store_true", help="emit the digest as JSON")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    claude_dir = Path(args.claude_dir or os.environ.get("CLAUDE_CONFIG_DIR")
                      or Path.home() / ".claude").expanduser()
    state_file = Path(args.state) if args.state else state_path(STATE_NAME)
    project = args.project.expanduser().resolve()
    marks = fingerprint(claude_dir, project)

    # Claude Code's own cache is read but never written; our copy absorbs the
    # hours between a release and that cache catching up with it.
    mirror = cache_path(CHANGELOG_CACHE)
    try:
        if args.changelog:
            text, source = args.changelog.read_text(encoding="utf-8"), str(args.changelog)
        else:
            text, source = load_changelog([claude_dir / "cache/changelog.md", mirror],
                                          CHANGELOG_URL, required=marks["version"],
                                          offline=args.offline, store=mirror)
    except (OSError, ValueError) as error:
        print(f"Cannot read a changelog: {error}", file=sys.stderr)
        return 1
    releases = parse_changelog(text)
    if not releases:
        print(f"No releases found in {source}", file=sys.stderr)
        return 1

    wants_dates = args.days is not None or args.months is not None
    dates = release_dates(cache_path(DATES_CACHE), PACKUMENT_URL, offline=args.offline)
    if wants_dates and not dates:
        print("Release dates are unavailable, so a date window cannot be computed. "
              "Use --releases N or --since VERSION instead.", file=sys.stderr)
        return 1

    if args.topic:
        topics(releases, args.topic, dates, None if args.limit == 0 else args.limit)
        return 0

    state = load_state(state_file)
    baseline = (state.get("baseline") or {}).get("release")
    notice, since, count, not_before = "", None, None, None
    if args.releases is not None:
        count = max(1, args.releases)
    elif args.since:
        since = args.since
    elif wants_dates:
        span = timedelta(days=args.days if args.days is not None else args.months * 30)
        not_before = datetime.now(timezone.utc) - span
    elif baseline:
        since = baseline
    else:
        count = DEFAULT_FIRST_RUN
        notice = (f"No baseline recorded yet, so this shows the {DEFAULT_FIRST_RUN} most recent "
                  f"releases. Add --commit to start tracking from here.")

    try:
        window = select(releases, since=since, count=count, not_before=not_before, dates=dates)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    if not window:
        print(f"No releases after {since or 'the requested window'}; "
              f"{marks['version'] or 'this install'} is current.")
        return 0
    if len(window) > args.max_releases and not args.relevant_only:
        print(f"That window covers {len(window)} releases (~{sum(len(r['bullets']) for r in window)} "
              f"entries), over the --max-releases limit of {args.max_releases}. Add --relevant-only "
              f"to keep the whole window and print just the bullets that touch this setup, or "
              f"narrow it with --releases N.", file=sys.stderr)
        return 1

    tagged, dropped = digest(window, marks, not args.no_filter)
    newest, oldest = window[0]["version"], window[-1]["version"]
    header = (f"# Claude Code changes: {oldest} through {newest} "
              f"({len(window)} release{'s' if len(window) > 1 else ''}, "
              f"{day(dates.get(oldest))} to {day(dates.get(newest))})\n"
              f"# Source: {source}\n"
              f"# Baseline: {baseline or 'none recorded'}"
              + (f", reported {(state.get('baseline') or {}).get('reported_at')}" if baseline else ""))
    if notice:
        header += f"\n# {notice}"
    if args.commit:
        save_state(state_file, newest, previous=state, source=source)
        header += f"\n# Baseline advanced to {newest} in {state_file}"
    else:
        header += "\n# Baseline unchanged; add --commit once this digest has been read"

    if args.json:
        print(json.dumps({"window": {"from": oldest, "to": newest, "count": len(window)},
                          "source": source, "baseline": baseline, "environment": marks,
                          "withheld": dropped, "unmatched": unmatched(tagged), "releases": tagged,
                          "dates": {v: day(d) for v, d in dates.items()
                                    if any(v == r["version"] for r in window)}},
                         indent=2, sort_keys=True, default=str))
        return 0
    render(tagged, marks, dropped, dates, header, args.relevant_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
