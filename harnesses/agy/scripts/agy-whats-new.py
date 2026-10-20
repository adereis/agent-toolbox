#!/usr/bin/env python3
"""Correlate Antigravity CLI (agy) release notes with local configuration.

Prints the releases published since the last digest, with each bullet tagged
by the parts of your environment it touches, so a reader can tell "this
changes something I configured" from "this is about a feature I never use".
A second mode searches the changelog for when a topic first appeared and what
was changed afterwards.

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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
from _text import safe_text, warn
from _whats_new import (
    TERMINALS, detect_terminal,
    cache_path, day, load_state, parse_timestamp,
    save_state, search, select, state_path, version_key,
)

STATE_NAME = "agy-whats-new.json"
CHANGELOG_CACHE = "agy-changelog.txt"
DEFAULT_FIRST_RUN = 5
DEFAULT_MAX_RELEASES = 25

# Bullets another host or platform owns. Each filter names the evidence that
# makes it safe, and the digest always reports how many it removed.
FILTERS = (
    ("Windows:", "windows", "not this platform"),
    ("macOS:", "macos", "not this platform"),
    ("Linux:", "linux", "not this platform"),
    ("[IDE]", "ide", "Antigravity IDE extension not running in CLI"),
    ("VS Code", "ide", "VS Code extension not running in CLI"),
    ("JetBrains", "ide", "JetBrains extension not running in CLI"),
)

# Tag, pattern, and the fingerprint predicate that makes the tag meaningful.
SIGNALS = (
    ("auto-mode", r"auto[- ]mode|auto[- ]accept|accept-edits|--mode auto|Agent Mode",
     lambda f: f["mode"] in ("auto", "accept-edits")),
    ("sandbox", r"\bsandbox\b|terminal sandbox|proceed-in-sandbox|--sandbox\b|dangerously-skip-permissions",
     lambda f: f["sandbox"] or f["platform"] == "linux"),
    ("plugins", r"\bplugins?\b|agy plugin|plugin\.json", lambda f: bool(f["plugins"])),
    ("skills", r"\bskills?\b|SKILL\.md|skills\.json", lambda f: bool(f["skills"])),
    ("rules", r"\brules?\b|GEMINI\.md|AGENTS\.md", lambda f: bool(f["rules"])),
    ("hooks", r"\bhooks?\b|PreToolUse|PostToolUse|PreInvocation|hooks\.json", lambda f: bool(f["hooks"])),
    ("mcp", r"\bMCP\b|mcp_config\.json|agy mcp", lambda f: bool(f["mcp"])),
    ("subagents", r"subagent|custom agent|invoke_subagent|define_subagent|agent\.md|agents\.json",
     lambda f: bool(f["agents"]) or bool(f["plugins"])),
    ("permissions", r"permission|allow rule|deny rule|ask rule|permission\.allow",
     lambda f: bool(f["permissions"])),
    ("remote-control", r"remote[- ]control|remote session|daemon mode",
     lambda f: f["remote_control"]),
    ("statusline", r"status ?line|OSC 7501|AGY_CLI_OSC7501", lambda f: f["statusline"]),
    ("notifications", r"\bnotifications?\b", lambda f: f["notifications"]),
    ("diff", r"\b/diff\b|diff view|syntax highlighting", lambda f: True),
    ("compaction", r"\bcompact|/compact\b", lambda f: True),
    ("sessions", r"/resume\b|conversation history|--continue\b|--conversation\b", lambda f: True),
    ("artifacts", r"\bartifacts?\b|Artifact Review", lambda f: f["artifacts"]),
    ("git", r"\bgit\b|worktree|commit hash|short-hash", lambda f: f["git"]),
    ("telemetry", r"telemetry|Enable Telemetry|AGY_ADC_AUTH", lambda f: bool(f["telemetry"])),
    ("linux", r"\bLinux\b|Wayland|\bX11\b|\bWSL\b", lambda f: f["platform"] == "linux"),
    # A new knob matches no existing configuration by definition, so these
    # unconditional tags keep --relevant-only from hiding what to adopt next.
    ("new-setting", r"`?(?:AGY_CLI_|GEMINI_)[A-Z0-9_]+`?|\bsetting `|in `/config`|in `/settings`", lambda f: True),
    ("new-command", r"^(?:Added|Changed) .*`/[a-z][\w-]*`|`agy [a-z]+`", lambda f: True),
    ("behavior-change", r"^(?:Changed|Removed)\b|no longer\b|\bdeprecat", lambda f: True),
)

ENVIRONMENT_VARS = (
    "AGY_CLI_OSC7501", "AGY_CLI_OSC7501_MESSAGES", "AGY_CLI_HIDE_LOGO",
    "AGY_CLI_HIDE_ACCOUNT_INFO", "AGY_CLI_DISABLE_LATEX", "AGY_CLI_CMD_OUTPUT_PERCENTAGE",
    "AGY_CLI_DISABLE_ESCAPE_SEQUENCE_OPTIMIZATIONS", "AGY_ADC_AUTH",
    "GEMINI_API_KEY", "GOOGLE_GEMINI_BASE_URL",
)


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


def running_version():
    """Identify the installed agy release via agy --version."""
    try:
        output = subprocess.run(["agy", "--version"], capture_output=True, text=True,
                                timeout=10, check=True).stdout
        found = re.search(r"\d+\.\d+\.\d+", output)
        if found:
            return found.group(0)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def parse_agy_changelog(text):
    """Parse Antigravity changelog text into releases newest first.

    Supports both agy changelog (<version>: and · bullets) and standard
    Markdown (## <version> and -/* bullets). Continuation lines are folded
    into the preceding bullet.
    """
    releases, bullets = [], None
    for line in text.splitlines():
        # Match ## 1.4.2 or 1.4.2:
        m_heading = re.match(r"^(?:##\s+)?(\d+\.\d+\.\d+):?\s*$", line.strip())
        if m_heading:
            bullets = []
            releases.append({"version": m_heading.group(1), "bullets": bullets})
        elif bullets is None:
            continue  # Preamble before first release
        elif line.strip().startswith(("·", "-", "*", "+")):
            # Bullet line
            content = re.sub(r"^[·\-*+]\s*", "", line.strip())
            bullets.append(content)
        elif bullets and line[:1] in (" ", "\t") and line.strip():
            bullets[-1] += " " + line.strip()
    releases.sort(key=lambda r: version_key(r["version"]), reverse=True)
    return releases


def load_changelog_text(cache_file, changelog_arg=None, offline=False):
    """Fetch or load changelog text from arg, cache, or agy changelog."""
    if changelog_arg:
        try:
            return Path(changelog_arg).read_text(encoding="utf-8"), str(changelog_arg)
        except OSError as error:
            raise ValueError(f"Cannot read changelog {changelog_arg}: {error}") from error

    # Try local cache first if offline
    cache_path_obj = Path(cache_file)
    if offline and cache_path_obj.is_file():
        try:
            return cache_path_obj.read_text(encoding="utf-8"), f"cache {cache_file}"
        except OSError:
            pass

    # Run `agy changelog`
    try:
        res = subprocess.run(["agy", "changelog"], capture_output=True, text=True,
                             timeout=15, check=False)
        if res.returncode == 0 and res.stdout.strip():
            text = res.stdout
            try:
                cache_path_obj.parent.mkdir(parents=True, exist_ok=True)
                cache_path_obj.write_text(text, encoding="utf-8")
            except OSError:
                pass
            return text, "agy changelog"
    except (OSError, subprocess.SubprocessError):
        pass

    # If subprocess failed, check cache
    if cache_path_obj.is_file():
        try:
            return cache_path_obj.read_text(encoding="utf-8"), f"cache {cache_file}"
        except OSError:
            pass

    raise ValueError("No changelog available: `agy changelog` failed and no cache found")


def fingerprint(agy_dir, config_dir, project_dir):
    """Describe the configuration that decides whether a change matters here."""
    agy_dir = Path(agy_dir)
    config_dir = Path(config_dir)
    project_dir = Path(project_dir)

    settings_candidates = [
        agy_dir / "settings.json",
        config_dir / "settings.json",
        config_dir / "config.json",
        project_dir / ".agents/settings.json",
        project_dir / ".agents/config.json",
    ]
    settings = {}
    for p in settings_candidates:
        data = read_json(p)
        if data:
            settings.update(data)

    mode = settings.get("agentMode") or settings.get("mode", "default")
    model = settings.get("model", "")
    effort = settings.get("effort", "")
    verbosity = settings.get("verbosity", "medium")
    theme = settings.get("colorScheme") or settings.get("theme", "")
    notifications = settings.get("notifications", False)
    telemetry = settings.get("telemetry", True)
    artifacts = settings.get("artifactReview", True)
    remote_control = settings.get("remoteControl", False)
    statusline = settings.get("statusline", True)

    permissions = settings.get("permissions") or settings.get("permission") or {}
    sandbox = bool(settings.get("sandbox", True))

    # Plugins inventory
    plugins = []
    try:
        res = subprocess.run(["agy", "plugin", "list", "--json"],
                             capture_output=True, text=True, timeout=10, check=False)
        if res.returncode == 0:
            plugin_list = json.loads(res.stdout)
            if isinstance(plugin_list, list):
                for pl in plugin_list:
                    if isinstance(pl, dict) and pl.get("name"):
                        plugins.append(pl["name"])
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

    if not plugins:
        # Fallback file scan
        for p_dir in (config_dir / "plugins", project_dir / ".agents/plugins"):
            if p_dir.is_dir():
                try:
                    for sub in p_dir.iterdir():
                        if sub.is_dir() and (sub / "plugin.json").is_file():
                            plugins.append(sub.name)
                except OSError:
                    pass

    # Skills inventory
    skills = []
    for s_dir in (config_dir / "skills", project_dir / ".agents/skills",
                  agy_dir / "builtin/skills"):
        if s_dir.is_dir():
            try:
                for sub in s_dir.iterdir():
                    if sub.is_dir() and (sub / "SKILL.md").is_file():
                        skills.append(sub.name)
            except OSError:
                pass

    # Rules inventory
    rules = []
    for r_cand in (project_dir / "AGENTS.md", project_dir / "GEMINI.md"):
        if r_cand.is_file():
            rules.append(r_cand.name)
    for r_dir in (project_dir / ".agents/rules", config_dir / "rules"):
        if r_dir.is_dir():
            try:
                for rf in r_dir.glob("*.md"):
                    rules.append(rf.name)
            except OSError:
                pass

    # Hooks inventory
    hooks = []
    for h_path in (project_dir / ".agents/hooks.json", config_dir / "hooks.json"):
        h_data = read_json(h_path)
        for h_name, h_conf in h_data.items():
            if isinstance(h_conf, dict) and h_conf.get("enabled", True) is not False:
                hooks.append(h_name)

    # MCP servers inventory
    mcp = []
    for m_path in (project_dir / ".agents/mcp_config.json", config_dir / "mcp_config.json"):
        m_data = read_json(m_path)
        servers = m_data.get("mcpServers")
        if isinstance(servers, dict):
            mcp.extend(servers.keys())

    # Subagents inventory
    agents = []
    for a_dir in (project_dir / ".agents/agents", config_dir / "agents"):
        if a_dir.is_dir():
            try:
                for af in a_dir.iterdir():
                    if af.suffix in (".md", ".json"):
                        agents.append(af.stem)
            except OSError:
                pass

    git = (project_dir / ".git").is_dir()

    terminal, evidence, disagrees = detect_terminal()
    active_env = [var for var in ENVIRONMENT_VARS if os.environ.get(var) is not None]

    return {
        "platform": sys.platform,
        "version": running_version(),
        "term": os.environ.get("TERM", ""),
        "terminal": terminal,
        "terminal_evidence": evidence,
        "term_disagrees": disagrees,
        "multiplexer": ("tmux" if os.environ.get("TMUX") else
                        "screen" if os.environ.get("STY") else ""),
        "mode": mode,
        "model": model,
        "effort": effort,
        "verbosity": verbosity,
        "theme": theme,
        "notifications": notifications,
        "telemetry": telemetry,
        "artifacts": artifacts,
        "remote_control": remote_control,
        "statusline": statusline,
        "sandbox": sandbox,
        "permissions": permissions,
        "plugins": sorted(set(plugins)),
        "skills": sorted(set(skills)),
        "rules": sorted(set(rules)),
        "hooks": sorted(set(hooks)),
        "mcp": sorted(set(mcp)),
        "agents": sorted(set(agents)),
        "git": git,
        "env": sorted(active_env),
    }


def describe(marks):
    """Render the ## Environment block for the report."""
    lines = [
        "## Environment",
        f"platform: {marks['platform']}",
        f"installed CLI: {marks['version'] or 'unknown'}",
        f"terminal: {marks['terminal'] or 'unidentified'} (via {marks['terminal_evidence']})",
        f"TERM: {marks['term'] or 'unset'}; multiplexer: {marks['multiplexer'] or 'none'}",
    ]
    if marks["term_disagrees"]:
        lines.append("TERM does not name the detected terminal.")
    lines.append(f"mode: {marks['mode']}; sandbox: {marks['sandbox']}")
    if marks["model"]:
        lines.append(f"model: {marks['model']}" + (f" (effort: {marks['effort']})" if marks['effort'] else ""))
    lines.append(f"verbosity: {marks['verbosity']}; theme: {marks['theme'] or 'default'}")
    lines.append(f"telemetry: {marks['telemetry']}; notifications: {marks['notifications']}")
    lines.append(f"artifact review: {marks['artifacts']}; remote control: {marks['remote_control']}")

    for key in ("plugins", "skills", "rules", "hooks", "mcp", "agents"):
        val = ", ".join(marks[key]) if marks[key] else "none"
        lines.append(f"{key}: {val}")

    lines.append(f"environment variables (names only): {', '.join(marks['env']) or 'none'}")
    return lines


def applies(bullet, pattern, predicate, marks):
    """Check whether a bullet matches a signal pattern and its predicate."""
    if re.search(pattern, bullet, re.I):
        return predicate(marks)
    return False


def is_withheld(bullet, marks):
    """Check if a bullet belongs to another platform or host."""
    for prefix, target_platform, reason in FILTERS:
        if prefix in bullet:
            if target_platform == "windows" and marks["platform"] != "win32":
                return True, reason
            if target_platform == "macos" and marks["platform"] != "darwin":
                return True, reason
            if target_platform == "linux" and marks["platform"] != "linux":
                return True, reason
            if target_platform == "ide":
                return True, reason
    return False, None


def tag_bullets(releases, marks, relevant_only=False, no_filter=False):
    """Filter foreign bullets and tag surviving bullets with matching signals."""
    tagged_releases = []
    withheld_count = 0
    withheld_reasons = {}
    unmatched_count = 0

    for rel in releases:
        rel_tagged = []
        for bullet in rel["bullets"]:
            if not no_filter:
                withheld, reason = is_withheld(bullet, marks)
                if withheld:
                    withheld_count += 1
                    withheld_reasons[reason] = withheld_reasons.get(reason, 0) + 1
                    continue

            tags = [tag for tag, pat, pred in SIGNALS if applies(bullet, pat, pred, marks)]

            # Check terminal matching
            if marks["terminal"]:
                for term_name, _, term_pat in TERMINALS:
                    if term_name == marks["terminal"] and re.search(term_pat, bullet, re.I):
                        tags.append(marks["terminal"])
                        break

            if not tags:
                unmatched_count += 1
                if relevant_only:
                    continue

            rel_tagged.append({
                "bullet": bullet,
                "tags": sorted(set(tags)),
            })
        tagged_releases.append({
            "version": rel["version"],
            "bullets": rel_tagged,
        })

    return tagged_releases, withheld_count, withheld_reasons, unmatched_count


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--releases", type=int, metavar="N", help="the N newest releases")
    window.add_argument("--since", metavar="VERSION", help="exclusive baseline version")
    window.add_argument("--days", type=int, metavar="N", help="last N days (requires dated changelog)")
    window.add_argument("--months", type=int, metavar="N", help="last N months (requires dated changelog)")
    parser.add_argument("--through", metavar="VERSION",
                        help="inclusive ceiling; pin the presented window when using --commit")
    parser.add_argument("--topic", action="append", metavar="PATTERN", help="search all notes (repeatable regex)")
    parser.add_argument("--limit", type=int, default=40, metavar="N", help="recent topic matches; 0 for all")
    parser.add_argument("--commit", action="store_true", help="save the newest reported release as baseline")
    parser.add_argument("--relevant-only", action="store_true", help="show only tagged entries; still count unmatched")
    parser.add_argument("--no-filter", action="store_true", help="include entries labelled for another platform")
    parser.add_argument("--max-releases", type=int, default=DEFAULT_MAX_RELEASES, metavar="N",
                        help=f"refuse wider windows unless --relevant-only (default: {DEFAULT_MAX_RELEASES})")
    parser.add_argument("--offline", action="store_true", help="forbid network; require cache or --changelog")
    parser.add_argument("--changelog", type=Path, metavar="FILE", help="explicit changelog file")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="project directory (default: cwd)")
    parser.add_argument("--agy-dir", type=Path, help="agy home directory (default: ~/.gemini/antigravity-cli)")
    parser.add_argument("--config-dir", type=Path, help="agy config directory (default: ~/.gemini/config)")
    parser.add_argument("--state", type=Path, help="explicit baseline state file")
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    home = Path(os.environ.get("HOME") or Path.home())
    agy_dir = args.agy_dir or (home / ".gemini/antigravity-cli")
    config_dir = args.config_dir or (home / ".gemini/config")
    state_file = args.state or state_path(STATE_NAME)
    cache_file = cache_path(CHANGELOG_CACHE)

    marks = fingerprint(agy_dir, config_dir, args.project)

    try:
        raw_text, source = load_changelog_text(cache_file, args.changelog, args.offline)
    except ValueError as e:
        sys.exit(f"Error loading changelog: {e}")

    releases = parse_agy_changelog(raw_text)
    if not releases:
        sys.exit("No releases found in changelog")

    # Topic search mode
    if args.topic:
        if args.commit:
            sys.exit("Cannot combine --commit with --topic")
        matches = search(releases, args.topic)
        if args.limit and len(matches) > args.limit:
            matches = matches[-args.limit:]
        if args.json:
            print(json.dumps([{"version": v, "bullet": b} for v, b in matches], indent=2))
        else:
            print(f"# Topic matches for: {', '.join(args.topic)}")
            for v, b in matches:
                print(f"[{v}] {b}")
        return

    # Baseline loading
    state = load_state(state_file)
    baseline = state.get("baseline", {}).get("release") if isinstance(state.get("baseline"), dict) else None

    since_version = args.since
    if since_version is None and args.releases is None and args.days is None and args.months is None:
        if baseline:
            since_version = baseline
        else:
            args.releases = DEFAULT_FIRST_RUN

    # Select window
    try:
        window = select(releases, since=since_version, count=args.releases)
    except ValueError as e:
        sys.exit(str(e))

    if args.through:
        ceiling_key = version_key(args.through)
        window = [r for r in window if version_key(r["version"]) <= ceiling_key]

    if len(window) > args.max_releases and not args.relevant_only:
        sys.exit(f"Window of {len(window)} releases exceeds limit of {args.max_releases}. "
                 f"Use --relevant-only or narrow with --releases / --since.")

    tagged_window, withheld, withheld_reasons, unmatched = tag_bullets(
        window, marks, relevant_only=args.relevant_only, no_filter=args.no_filter
    )

    newest_version = window[0]["version"] if window else None

    # Handle commit
    committed_msg = None
    if args.commit:
        if not newest_version:
            sys.exit("Cannot commit empty window")
        target_version = args.through or newest_version
        save_state(state_file, target_version, previous=state, source=source)
        committed_msg = f"# Baseline advanced to {target_version} (was {baseline or 'none'})"

    if args.json:
        payload = {
            "environment": marks,
            "baseline": baseline,
            "newest_version": newest_version,
            "withheld": withheld,
            "withheld_reasons": withheld_reasons,
            "unmatched": unmatched,
            "releases": tagged_window,
        }
        if committed_msg:
            payload["committed"] = committed_msg
        print(json.dumps(payload, indent=2))
        return

    # Output text format
    if committed_msg:
        print(committed_msg)

    for line in describe(marks):
        print(line)
    print()

    if withheld:
        breakdown = ", ".join(f"{count} {reason}" for reason, count in sorted(withheld_reasons.items()))
        print(f"## Withheld: {withheld} entries ({breakdown})")
    print(f"## Unmatched: {unmatched} entries with no configuration signal")
    print()

    for rel in tagged_window:
        if not rel["bullets"]:
            continue
        print(f"## {rel['version']}")
        for item in rel["bullets"]:
            prefix = f"[{', '.join(item['tags'])}]" if item["tags"] else "[-]"
            print(f"{prefix} · {item['bullet']}")
        print()


if __name__ == "__main__":
    main()
