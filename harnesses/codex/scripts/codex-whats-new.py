#!/usr/bin/env python3
"""Correlate stable Codex CLI releases with local configuration (Linux).

Requires Python 3.11+. Online fetching needs GitHub CLI and a GitHub login
(gh auth login --hostname github.com). Codex CLI is optional for detecting
the installed version. The first online run downloads the complete public
release archive; later runs reuse a private XDG cache for up to 24 hours.
No Codex credentials or model calls are involved.
Keep the Agent Toolbox checkout intact when symlinking this entry point.

Examples:
  codex-whats-new.py --profile api
  codex-whats-new.py --days 14 --relevant-only
  codex-whats-new.py --topic 'multi.agent' --topic subagent
  codex-whats-new.py --since 0.153.0 --through 0.154.0 --commit

Configuration is a file-based inventory, not a live session probe. Supply
--profile explicitly when applicable. Baselines are isolated by Codex home,
project, and profile. --commit records a completed digest, not a Git commit.
"""

import argparse
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timedelta, timezone

if sys.version_info < (3, 11):
    sys.exit("codex-whats-new.py requires Python 3.11+; run it with python3.11 or newer")

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _text import safe_text
from _whats_new import cache_path, day, save_state, select, version_key, parse_timestamp
from _release_digest import (
    CACHE_NAME, baseline_path, digest, fingerprint, load_releases,
    matchers, parse_releases, scope_for, validate_releases,
)


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def stable_version(value):
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise argparse.ArgumentTypeError("use a stable CLI version such as 0.154.0")
    return value


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--releases", type=positive, metavar="N", help="the N newest releases")
    window.add_argument("--since", type=stable_version, metavar="VERSION", help="exclusive baseline")
    window.add_argument("--days", type=positive, metavar="N", help="last N days")
    window.add_argument("--months", type=positive, metavar="N", help="last N periods of 30 days")
    parser.add_argument("--through", type=stable_version, metavar="VERSION",
                        help="inclusive ceiling; pin the presented window when using --commit")
    parser.add_argument("--topic", action="append", metavar="PATTERN", help="search all notes (repeatable regex)")
    parser.add_argument("--limit", type=int, default=40, metavar="N", help="recent topic matches; 0 for all")
    parser.add_argument("--commit", action="store_true", help="save the newest reported release as baseline")
    parser.add_argument("--relevant-only", action="store_true", help="show only tagged entries; still count unmatched entries")
    parser.add_argument("--no-filter", action="store_true", help="include entries labelled for another platform")
    parser.add_argument("--max-releases", type=positive, default=25, metavar="N",
                        help="refuse wider windows unless --relevant-only (default: 25)")
    parser.add_argument("--offline", action="store_true", help="forbid network; require a cache or --changelog")
    parser.add_argument("--refresh", action="store_true", help="refresh even a recent release archive")
    parser.add_argument("--changelog", type=Path, metavar="FILE", help="read a GitHub releases JSON array (local snapshot)")
    parser.add_argument("--codex-dir", type=Path, help="Codex home (default: CODEX_HOME or ~/.codex)")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="project directory (default: cwd)")
    parser.add_argument("--profile", help="selected NAME.config.toml; never inferred from a session")
    parser.add_argument("--state", type=Path, help="explicit baseline file; scope must still match")
    parser.add_argument("--json", action="store_true", help="machine-readable report, including topic mode")
    return parser


@contextmanager
def baseline_lock(path):
    """Serialize commits; atomic replacement also keeps unlocked readers safe."""
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def read_baseline(path, scope):
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as error:
        raise ValueError(f"Cannot parse baseline {path}; restore it or choose another --state file") from error
    if not isinstance(state, dict) or not state:
        raise ValueError(f"Invalid baseline object in {path}")
    if state:
        if state.get("version") != 1 or state.get("scope") != scope:
            raise ValueError(f"Baseline {path} has a different scope or format; choose another --state file")
        baseline = state.get("baseline")
        if not isinstance(baseline, dict) or not re.fullmatch(r"\d+\.\d+\.\d+", str(baseline.get("release"))):
            raise ValueError(f"Invalid baseline in {path}; restore the file or choose another --state file")
        if not isinstance(state.get("history"), list):
            raise ValueError(f"Invalid baseline history in {path}")
    return state


def describe(marks):
    lines = ["## Environment", f"platform: {marks['platform']}",
             f"installed CLI: {marks['version'] or 'unknown'}",
             f"Codex home: {marks['codex_home']}", f"project: {marks['project']}",
             f"profile: {marks['profile'] or 'none selected'}",
             f"project trust: {marks['project_trust']}",
             f"terminal: {marks['terminal'] or 'unidentified'} (via {marks['terminal_evidence']})",
             f"TERM: {marks['term'] or 'unset'}; multiplexer: {marks['multiplexer'] or 'none'}"]
    if marks["term_disagrees"]:
        lines.append("TERM does not name the detected terminal.")
    lines += [f"setting {key}: {value}" for key, value in marks["settings"].items()]
    lines += [f"feature {key}: {value}" for key, value in sorted(marks["features"].items())]
    for key in ("hooks", "mcp", "plugins", "skills", "sources"):
        lines.append(f"{key}: {', '.join(marks[key]) or 'none found'}")
    lines.append(f"hooks disabled in files: {marks['hooks_disabled']}")
    for key in ("statusline", "notifications", "vim", "keymap", "otel", "rules", "sessions", "git"):
        lines.append(f"{key}: {marks[key]}")
    lines.append(f"environment variables (names only): {', '.join(marks['env']) or 'none'}")
    lines.extend(marks["notices"])
    return lines


def emit(report, as_json):
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    lines = ["# Codex CLI release digest", *describe(report["environment"]), ""]
    if report["mode"] == "topic":
        lines += [f"Topic matches: {report['total_matches']}; shown: {len(report['matches'])}",
                  "First match in available stable history: " + (report["first_match"] or "none")]
        for hit in report["matches"]:
            lines.append(f"{hit['version']} {hit['date']}  {hit['text']}")
        if report["total_matches"] > len(report["matches"]):
            lines.append("Older matches are hidden; pass --limit 0 to read them all.")
    else:
        window = report["window"]
        lines += [f"Window: {window['from']} through {window['to']} ({window['count']} releases)",
                  f"Baseline: {report['baseline'] or 'none recorded'}",
                  f"Signals watched: {', '.join(report['signals'])}",
                  f"Withheld: {report['counts']['withheld']} entries belonging to another platform",
                  f"Unmatched: {report['counts']['unmatched']} entries matched no configuration signal",
                  f"Not shown: {report['counts']['hidden_unmatched']} unmatched entries (--relevant-only)"]
        lines.extend(f"  {reason}: {count}" for reason, count in sorted(report["withheld"].items()))
        for release in report["releases"]:
            lines += ["", f"## {release['version']} ({day(parse_timestamp(release['published_at']))})"]
            for bullet in release["bullets"]:
                lines.append(f"[{','.join(bullet['tags']) or '-'}] {bullet['text']}")
        lines += ["", f"Baseline file: {report['state_file']}"]
        lines.append("Baseline will be recorded after successful output." if report["commit"]
                     else "Baseline unchanged; add --through VERSION --commit after presenting this window.")
    lines += report["notices"]
    lines += [f"Archive coverage: {report['coverage']['oldest']} through {report['coverage']['newest']}",
              f"Source: {report['source']}"]
    print("\n".join(safe_text(line) for line in lines))


def run(args):
    codex_home = Path(args.codex_dir or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()
    project = args.project.expanduser().resolve()
    if not project.is_dir():
        raise ValueError(f"Project directory does not exist: {project}")
    marks = fingerprint(codex_home, project, args.profile)
    if args.changelog:
        releases = validate_releases(parse_releases(json.loads(args.changelog.expanduser().read_text(encoding="utf-8"))))
        source, notices = str(args.changelog), ["Local snapshot; releases outside this file are not searched."]
    else:
        releases, source, notices = load_releases(cache_path(CACHE_NAME), required=marks["version"],
                                                  offline=args.offline, refresh=args.refresh)
    coverage = {"oldest": releases[-1]["version"], "newest": releases[0]["version"]}
    if marks["version"] and marks["version"] not in {r["version"] for r in releases}:
        notices.append("Installed version is absent from this stable-release snapshot; it may be newer or a prerelease.")
    common = {"environment": marks, "source": source, "notices": notices, "coverage": coverage}
    if args.topic:
        patterns = [re.compile(pattern, re.I) for pattern in args.topic]
        hits = [{"version": r["version"], "date": day(parse_timestamp(r["published_at"])), **b}
                for r in reversed(releases) for b in r["bullets"]
                if any(p.search(b["text"]) for p in patterns)]
        emit({**common, "mode": "topic", "patterns": args.topic, "total_matches": len(hits),
              "first_match": hits[0]["version"] if hits else None,
              "matches": hits[-args.limit:] if args.limit else hits}, args.json)
        return
    if args.through:
        if args.through not in {r["version"] for r in releases}:
            raise ValueError("--through version is absent from this archive; refresh or choose a listed release")
        releases = [r for r in releases if version_key(r["version"]) <= version_key(args.through)]
    scope = scope_for(marks)
    state_file = args.state.expanduser().resolve() if args.state else baseline_path(scope)
    with baseline_lock(state_file) if args.commit else nullcontext():
        state = read_baseline(state_file, scope)
        baseline = (state.get("baseline") or {}).get("release")
        since, count, not_before = args.since, args.releases, None
        if args.days or args.months:
            not_before = datetime.now(timezone.utc) - timedelta(days=args.days or args.months * 30)
        elif since is None and count is None:
            if baseline:
                since = baseline
            else:
                count = 5
                notices.append("No baseline recorded yet; showing the five most recent stable CLI releases.")
        dates = {r["version"]: parse_timestamp(r["published_at"]) for r in releases}
        window = select(releases, since=since, count=count, not_before=not_before, dates=dates)
        if len(window) > args.max_releases and not args.relevant_only:
            raise ValueError(f"Window covers {len(window)} releases, over --max-releases {args.max_releases}; "
                             "narrow the window or use --relevant-only. No releases were truncated.")
        newest = window[0]["version"] if window else None
        if args.commit and newest and baseline and version_key(newest) < version_key(baseline):
            raise ValueError("Refusing to move the baseline backward; re-read without --commit")
        tagged, dropped = digest(window, marks, not args.no_filter)
        unmatched = sum(not b["tags"] for r in tagged for b in r["bullets"])
        counts = {"withheld": sum(dropped.values()), "unmatched": unmatched,
                  "hidden_unmatched": unmatched if args.relevant_only else 0,
                  "total": sum(len(r["bullets"]) for r in window)}
        if args.relevant_only:
            tagged = [{**r, "bullets": [b for b in r["bullets"] if b["tags"]]} for r in tagged]
        if not window:
            notices.append("No releases in this window of the available snapshot. This is not an update check.")
        report = {**common, "mode": "window", "baseline": baseline, "state_file": str(state_file),
                  "commit": bool(args.commit and newest), "counts": counts, "withheld": dropped,
                  "signals": [tag for tag, _ in matchers(marks)] + ["new-feature"],
                  "window": {"from": window[-1]["version"] if window else None,
                             "to": newest, "count": len(window)}, "releases": tagged}
        emit(report, args.json)
        sys.stdout.flush()  # A failed pipe must not consume unread releases.
        if args.commit and newest and newest != baseline:
            save_state(state_file, newest, previous=state, source=source, scope=scope)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if sys.platform != "linux":
        parser.error("Only Linux is verified. On macOS run: open https://github.com/openai/codex/releases ; "
                     "use codex --version to identify your CLI")
    if args.offline and args.refresh:
        parser.error("--offline cannot be combined with --refresh")
    if args.limit < 0:
        parser.error("--limit must be zero or positive")
    if args.topic and any((args.commit, args.releases, args.since, args.days, args.months, args.through)):
        parser.error("--topic cannot be combined with a release window or --commit")
    try:
        for pattern in args.topic or []:
            re.compile(pattern)
    except re.error:
        parser.error("Invalid --topic regular expression")
    try:
        run(args)
    except (OSError, ValueError) as error:
        print(safe_text(f"Cannot produce Codex digest: {error}"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
