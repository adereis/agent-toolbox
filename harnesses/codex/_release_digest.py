"""Codex release sources and a credential-free, file-based configuration view.

The public GitHub archive uses cursors to avoid the REST 1,000-record cap;
only a complete fetch can replace the cache. Config discovery follows the
documented 0.134+ file-profile layout.
This inventory does not resolve cloud defaults, requirements, or live flags.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _text import safe_text, warn
from _whats_new import (
    TERMINALS, detect_terminal, parse_timestamp, state_path, version_key, write_json,
)

RELEASES_URL = "https://github.com/openai/codex/releases"
RELEASE_QUERY = """query($cursor: String) {
  repository(owner: "openai", name: "codex") {
    releases(first: 100, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes { tagName isPrerelease isDraft publishedAt description }
      pageInfo { hasNextPage endCursor }
    }
  }
}"""
CACHE_NAME = "codex-releases.json"
STABLE_TAG = re.compile(r"rust-v(\d+\.\d+\.\d+)")
PROFILE_NAME = re.compile(r"[A-Za-z0-9_-]+")
SYSTEM_CONFIG = Path("/etc/codex/config.toml")
VIEW_LIMITS = (
    "File-based inventory, not the running session's effective configuration. "
    "CLI overrides, cloud defaults, enforced requirements, plugin-bundled content, "
    "and hook trust are not resolved. Unset features retain unknown runtime defaults."
)


def note(message):
    warn(safe_text(message))


def entries(body):
    """Keep prose and top-level bullets; fold wrapped and nested text together."""
    result, parts, section = [], [], ""

    def flush():
        if parts:
            result.append({"text": " ".join(parts), "section": section})
            parts.clear()

    for line in body.splitlines():
        if re.match(r"^#{1,6}\s", line):
            flush()
            section = re.sub(r"^#+\s*", "", line).strip()
        elif re.match(r"^(?:[-*+] |\d+\. )", line):
            flush()
            parts.append(re.sub(r"^(?:[-*+] |\d+\. )", "", line).strip())
        elif not line.strip():
            flush()
        else:
            parts.append(line.strip())
    flush()
    return result


def parse_releases(payload):
    """Select stable Rust CLI releases; SDKs and prereleases are other products."""
    if not isinstance(payload, list):
        raise ValueError("GitHub releases must be a JSON array")
    releases = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("tag_name"), str):
            raise ValueError("Malformed GitHub release record")
        match = STABLE_TAG.fullmatch(item["tag_name"])
        if not match or item.get("draft") or item.get("prerelease"):
            continue
        date = parse_timestamp(item.get("published_at"))
        body = item.get("body")
        if date is None or not isinstance(body, str):
            raise ValueError(f"Release {match[1]} has no usable publication date or notes")
        releases.append({"version": match[1], "published_at": date.isoformat(),
                         "bullets": entries(body)})
    return releases


def validate_releases(releases):
    if not isinstance(releases, list) or not releases:
        raise ValueError("No stable Codex CLI releases found")
    versions = set()
    for release in releases:
        if not isinstance(release, dict):
            raise ValueError("Malformed cached release")
        version = release.get("version")
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("Malformed stable CLI version")
        if version in versions:
            raise ValueError(f"Duplicate release {version}; retry the archive fetch")
        versions.add(version)
        if parse_timestamp(release.get("published_at")) is None:
            raise ValueError(f"Release {version} has no publication date")
        bullets = release.get("bullets")
        if not isinstance(bullets, list) or any(
                not isinstance(b, dict) or not isinstance(b.get("text"), str)
                or not isinstance(b.get("section"), str) for b in bullets):
            raise ValueError(f"Release {version} has malformed notes")
    return sorted(releases, key=lambda r: version_key(r["version"]), reverse=True)


def fetch_page(cursor=None):
    """Use GitHub CLI auth without reading, copying, or printing its credentials."""
    command = ["gh", "api", "graphql", "--hostname", "github.com", "-f", "query=" + RELEASE_QUERY]
    if cursor:
        command += ["-f", "cursor=" + cursor]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    except FileNotFoundError as error:
        raise ValueError("Missing GitHub CLI; install gh (Fedora: sudo dnf install gh; "
                         "Debian/Ubuntu: sudo apt install gh), then run gh auth login --hostname github.com") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError("GitHub release query timed out; check connectivity and retry --refresh") from error
    if result.returncode:
        # gh diagnostics can reflect environment settings. Do not relay them
        # into a digest; give specific local diagnostic commands instead.
        raise ValueError(f"GitHub CLI query failed (exit {result.returncode}); run gh auth status --hostname github.com "
                         "and gh api --hostname github.com rate_limit. Authenticate with "
                         "gh auth login --hostname github.com if needed, then retry --refresh")
    try:
        payload = json.loads(result.stdout)
        if payload.get("errors"):
            raise ValueError("GraphQL returned errors")
        connection = payload["data"]["repository"]["releases"]
        nodes, page = connection["nodes"], connection["pageInfo"]
        if not isinstance(nodes, list) or not isinstance(page["hasNextPage"], bool):
            raise ValueError("Invalid release connection")
        next_cursor = page["endCursor"] if page["hasNextPage"] else None
        if page["hasNextPage"] and (not isinstance(next_cursor, str) or not next_cursor):
            raise ValueError("Missing pagination cursor")
        releases = [{"tag_name": n["tagName"], "prerelease": n["isPrerelease"],
                     "draft": n["isDraft"], "published_at": n["publishedAt"],
                     "body": n["description"]} for n in nodes]
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ValueError("Invalid GitHub release response; run gh api --hostname github.com rate_limit "
                         "and retry --refresh") from error
    return releases, next_cursor


def load_releases(cache, required=None, offline=False, refresh=False):
    """Fetch every page before caching; failed refreshes use a labelled old cache."""
    stored, fresh = None, False
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != 1 or data.get("complete") is not True:
            raise ValueError("Not a complete release archive")
        if data.get("source") != RELEASES_URL:
            raise ValueError("Archive belongs to another release source")
        stored = validate_releases(data.get("releases"))
        fetched = parse_timestamp(data.get("fetched_at"))
        age = datetime.now(timezone.utc) - fetched if fetched else None
        fresh = bool(age is not None and timedelta(0) <= age < timedelta(hours=24))
        if required and required not in {r["version"] for r in stored}:
            fresh = False
    except FileNotFoundError:
        pass  # A first run has no cache.
    except (OSError, ValueError) as error:
        note(f"Cannot use release cache {cache}: {error}")
        stored = None
    if offline:
        if stored is None:
            raise ValueError("No complete release cache; run without --offline or supply --changelog FILE")
        notice = "Offline snapshot; newer releases may be missing."
        note(notice)
        return stored, f"offline cache {cache}", [notice]
    if stored is not None and fresh and not refresh:
        return stored, f"cache {cache}", []

    try:
        releases, cursors, cursor = [], set(), None
        for _ in range(100):
            payload, next_cursor = fetch_page(cursor)
            releases.extend(parse_releases(payload))
            if next_cursor is None:
                break
            if next_cursor in cursors:
                raise ValueError("Repeated release cursor; refusing incomplete history")
            cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise ValueError("Release archive exceeds 100 pages; refusing a partial history")
        releases = validate_releases(releases)
    except (OSError, ValueError) as error:
        if stored is None:
            raise ValueError(f"Cannot fetch the complete release archive: {error}") from error
        notice = f"Archive refresh failed ({error}); using an older complete snapshot."
        note(notice)
        return stored, f"stale cache {cache}", [notice]
    try:
        write_json(cache, {"schema": 1, "complete": True, "source": RELEASES_URL,
                           "fetched_at": datetime.now(timezone.utc).isoformat(),
                           "releases": releases})
    except OSError as error:
        note(f"Could not cache release archive: {error}")
    return releases, RELEASES_URL, []


def read_document(path, required=False):
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if required:
            raise ValueError(f"Missing {path}; select an installed profile with --profile NAME")
        return {}
    try:
        data = json.loads(text) if path.suffix == ".json" else tomllib.loads(text)
    except ValueError as error:
        # Parser exceptions can include credential-bearing source fragments.
        raise ValueError(f"Cannot parse {path}; fix its {path.suffix[1:].upper()} syntax") from error
    if not isinstance(data, dict):
        raise ValueError(f"Expected a configuration object in {path}")
    return data


def merge(base, overlay):
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value.copy() if isinstance(value, dict) else value
    return base


def table(config, key):
    value = config.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Expected a table for {key}")
    return value


def project_chain(project):
    """Closest Git root through cwd; without a repository inspect cwd only."""
    chain = []
    for directory in (project, *project.parents):
        chain.append(directory)
        if (directory / ".git").exists():
            return list(reversed(chain))
    return [project]


def running_version(codex_home):
    try:
        result = subprocess.run(["codex", "--version"], capture_output=True, text=True,
                                env={**os.environ, "CODEX_HOME": str(codex_home)},
                                timeout=20, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        note(f"Cannot identify installed Codex CLI ({type(error).__name__}); run codex --version")
        return None
    match = re.search(r"codex-cli\s+(\d+\.\d+\.\d+(?:[-+][\w.-]+)?)", result.stdout)
    if not match:
        note("Unrecognized codex --version output; installed CLI version is unknown")
    return match[1] if match else None


def fingerprint(codex_home, project, profile=None):
    config, sources, hooks, ignored = {}, [], set(), []
    hook_dirs = set()

    def layer(path, required=False):
        data = read_document(path, required)
        if path.exists():
            sources.append(str(path))
        hooks.update(table(data, "hooks"))
        if path.parent not in hook_dirs:
            hook_dirs.add(path.parent)
            hooks.update(table(read_document(path.with_name("hooks.json")), "hooks"))
        merge(config, data)

    layer(SYSTEM_CONFIG)
    layer(codex_home / "config.toml")
    # Project-local files cannot establish their own trust.
    projects = table(config, "projects")
    trust = None
    for directory in (project, *project.parents):
        record = projects.get(str(directory), {})
        if isinstance(record, dict) and record.get("trust_level") in ("trusted", "untrusted"):
            trust = record["trust_level"]
            break
    if profile:
        if not PROFILE_NAME.fullmatch(profile):
            raise ValueError("Profile names may contain only letters, digits, hyphens, and underscores")
        layer(codex_home / f"{profile}.config.toml", required=True)
    if "profiles" in config or "profile" in config:
        ignored.append("Legacy embedded profiles/selectors are ignored by Codex 0.134+; use --profile NAME")
    chain = project_chain(project)
    for directory in chain:
        path = directory / ".codex/config.toml"
        if trust == "trusted":
            layer(path)
        elif path.exists() or path.with_name("hooks.json").exists():
            ignored.append(f"Project layer skipped without recorded trust: {path.parent}")

    features = table(config, "features")
    if any(not isinstance(v, bool) for v in features.values()):
        raise ValueError("Feature flags must be booleans")
    tui = table(config, "tui")
    def enabled_names(key, default):
        names = []
        for name, value in table(config, key).items():
            if not isinstance(value, dict) or not isinstance(value.get("enabled", default), bool):
                raise ValueError(f"Expected {key} entries to be tables with a boolean enabled setting")
            if value.get("enabled", default):
                names.append(name)
        return sorted(names)

    mcp = enabled_names("mcp_servers", True)
    plugins = enabled_names("plugins", False)
    skills = set()
    skill_dirs = [Path.home() / ".agents/skills", codex_home / "skills", SYSTEM_CONFIG.parent / "skills"]
    if trust == "trusted":
        skill_dirs.extend(d / ".agents/skills" for d in chain)
    for directory in skill_dirs:
        if directory.exists():
            # Follow native discovery's entry-point rule: directory links
            # work, file links are skipped. Presence is not activation.
            skills.update(p.name for p in directory.iterdir()
                          if (p / "SKILL.md").is_file() and not (p / "SKILL.md").is_symlink())
    # Only named, non-secret display settings cross this boundary. Never emit
    # raw TOML, hook commands/matchers, provider URLs/headers, or MCP arguments.
    display = {}
    for key in ("model", "model_provider", "model_reasoning_effort", "service_tier",
                "approval_policy", "approvals_reviewer", "sandbox_mode", "default_permissions",
                "web_search", "forced_login_method"):
        value = config.get(key)
        if value is not None:
            display[key] = value if isinstance(value, (str, bool, int)) else "configured"
    terminal, evidence, disagrees = detect_terminal()
    return {
        "platform": sys.platform, "version": running_version(codex_home),
        "codex_home": str(codex_home), "project": str(project), "profile": profile,
        "sources": sources, "settings": display, "features": features,
        "project_trust": trust or "not recorded", "notices": [VIEW_LIMITS, *ignored],
        "hooks": sorted(hooks), "hooks_disabled": features.get("hooks") is False,
        "mcp": mcp, "plugins": plugins, "skills": sorted(skills),
        "statusline": bool(tui.get("status_line")),
        "notifications": bool(config.get("notify") or tui.get("notifications")),
        "vim": tui.get("editor_mode") == "vim", "keymap": bool(tui.get("keymap")),
        "otel": bool(config.get("otel")),
        "rules": any((p / "rules").is_dir() for p in hook_dirs),
        "sessions": (codex_home / "sessions").is_dir(),
        "git": any((p / ".git").exists() for p in chain),
        "terminal": terminal, "terminal_evidence": evidence, "term_disagrees": disagrees,
        "term": os.environ.get("TERM", ""), "term_program": os.environ.get("TERM_PROGRAM", ""),
        "multiplexer": "tmux" if os.environ.get("TMUX") else "screen" if os.environ.get("STY") else "",
        "env": sorted(k for k in os.environ if k.startswith(("CODEX_", "OPENAI_", "OTEL_"))
                      and not k.startswith(("CODEX_THREAD", "CODEX_TURN", "CODEX_INTERNAL"))),
    }


def scope_for(marks):
    return {key: marks[key] for key in ("codex_home", "project", "profile")}


def baseline_path(scope):
    identity = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    return state_path(f"codex-whats-new/{identity}.json")


SIGNALS = (
    ("hooks", r"\bhooks?\b|PreCompact|PreToolUse|PostToolUse|SessionStart|SessionEnd",
     lambda f: bool(f["hooks"]) and not f["hooks_disabled"]),
    ("mcp", r"\bMCP\b|OAuth", lambda f: bool(f["mcp"])),
    ("plugins", r"\bplugins?\b|marketplace", lambda f: bool(f["plugins"])),
    ("skills", r"\bskills?\b|SKILL\.md", lambda f: bool(f["skills"])),
    ("permissions", r"permission|approval|sandbox|allowlist|execpolicy",
     lambda f: f["rules"] or any(k in f["settings"] for k in
                                ("approval_policy", "sandbox_mode", "default_permissions"))),
    ("memory", r"\bmemor(?:y|ies)\b", lambda f: f["features"].get("memories") is True),
    ("subagents", r"sub.?agent|multi.?agent|delegat", lambda f: f["features"].get("multi_agent") is True),
    ("statusline", r"status.?line|status bar|footer", lambda f: f["statusline"]),
    ("notifications", r"notification|\bnotify\b", lambda f: f["notifications"]),
    ("vim", r"\bvim\b", lambda f: f["vim"]),
    ("keymap", r"keymap|key.?bind|shortcut", lambda f: f["keymap"]),
    ("sessions", r"resum|session history|\bfork", lambda f: f["sessions"]),
    ("git", r"\bgit\b|worktree|pull request|commit", lambda f: f["git"]),
    ("telemetry", r"OTEL|OpenTelemetry|telemetry", lambda f: f["otel"]),
    ("provider", r"provider|API key|authenticat|ChatGPT login|Bedrock|Azure|Ollama",
     lambda f: "model_provider" in f["settings"] or "forced_login_method" in f["settings"]),
    ("effort", r"reasoning|effort|thinking budget", lambda f: "model_reasoning_effort" in f["settings"]),
    ("service-tier", r"service.tier|fast mode|priority|\bflex\b", lambda f: "service_tier" in f["settings"]),
    ("web-search", r"web.?search|brows", lambda f: f["settings"].get("web_search") not in (None, "disabled")),
    ("compaction", r"compact|context window", lambda f: True),
    ("new-setting", r"(?:add|introduc|new|support).*?(?:setting|config|flag|option|`[A-Z][A-Z_]+`)", lambda f: True),
    ("new-command", r"(?:add|introduc|new|support).*?`(?:/[a-z]|--[a-z]|codex )", lambda f: True),
    ("behavior-change", r"breaking|deprecat|no longer|\bremov(?:e|ed|al)\b|migration", lambda f: True),
)


def matchers(marks):
    active = [(tag, re.compile(pattern, re.I)) for tag, pattern, applies in SIGNALS if applies(marks)]
    model = marks["settings"].get("model")
    if isinstance(model, str) and model:
        active.append(("model", re.compile(re.escape(model), re.I)))
    for flag, enabled in marks["features"].items():
        if enabled:
            active.append((f"feature:{flag}", re.compile(re.escape(flag), re.I)))
    terminal = marks["terminal"]
    if terminal:
        known = {name: pattern for name, _, pattern in TERMINALS}
        active.append((f"term:{terminal}", re.compile(known.get(terminal, re.escape(terminal)), re.I)))
    if marks["multiplexer"]:
        active.append((marks["multiplexer"], re.compile(rf"\b{marks['multiplexer']}\b", re.I)))
    return active


def excluded(text, marks):
    # Only explicit ownership labels are safe to remove. A Windows fix may
    # also change Linux behavior; mentioning a platform is not ownership.
    for label, platform in (("Windows", "win32"), ("macOS", "darwin"), ("Linux", "linux")):
        if re.match(rf"^(?:\[{label}\]|{label}:)\s", text, re.I) and marks["platform"] != platform:
            return f"{label}: another platform"
    return None


def digest(releases, marks, filtering=True):
    active, kept, dropped = matchers(marks), [], {}
    for release in releases:
        bullets = []
        for bullet in release["bullets"]:
            reason = excluded(bullet["text"], marks) if filtering else None
            if reason:
                dropped[reason] = dropped.get(reason, 0) + 1
                continue
            tags = [tag for tag, expression in active if expression.search(bullet["text"])]
            if re.search(r"new features|what.s new", bullet["section"], re.I):
                tags.append("new-feature")
            bullets.append({**bullet, "tags": tags})
        kept.append({**release, "bullets": bullets})
    return kept, dropped
