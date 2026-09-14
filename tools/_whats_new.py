"""Changelog parsing, release windows, and baseline state for release digests.

Harness entry points supply the changelog location, the platform filters, and
the environment fingerprint. Everything here is portable across harnesses that
publish a Markdown changelog whose releases are `## <version>` headings.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from _text import warn

STATE_VERSION = 1
HISTORY_LIMIT = 5


def version_key(value):
    """Order releases by their numeric components; text suffixes are ignored."""
    return tuple(int(part) for part in re.findall(r"\d+", str(value))[:4]) or (0,)


def parse_changelog(text):
    """Return releases newest first as dicts of version and bullet strings.

    Continuation lines are folded into the preceding bullet so that a wrapped
    entry stays one searchable unit.
    """
    releases, bullets = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            bullets = []
            releases.append({"version": line[3:].strip(), "bullets": bullets})
        elif bullets is None:
            continue  # Preamble before the first release heading.
        elif line[:2] in ("- ", "* "):
            bullets.append(line[2:].strip())
        elif bullets and line[:1] in (" ", "\t") and line.strip():
            bullets[-1] += " " + line.strip()
    releases.sort(key=lambda release: version_key(release["version"]), reverse=True)
    return releases


def select(releases, since=None, count=None, not_before=None, dates=None):
    """Pick a newest-first window by baseline version, release count, or date.

    `since` is exclusive: it is the last release already reported. A date
    window requires `dates`; without it the caller gets an explicit error
    rather than a window silently computed from nothing.
    """
    chosen = releases
    if since is not None:
        baseline = version_key(since)
        chosen = [r for r in chosen if version_key(r["version"]) > baseline]
    if not_before is not None:
        if not dates:
            raise ValueError("A date window needs release dates, which are unavailable")
        chosen = [r for r in chosen
                  if dates.get(r["version"]) and dates[r["version"]] >= not_before]
    if count is not None:
        chosen = chosen[:count]
    return chosen


def search(releases, patterns):
    """Find bullets matching any pattern, oldest first, tagged with a release.

    Patterns are alternatives rather than requirements so that a caller can
    pass the several names one feature has carried over time.
    """
    compiled = [re.compile(pattern, re.I) for pattern in patterns]
    return [(release["version"], bullet)
            for release in reversed(releases)
            for bullet in release["bullets"]
            if any(expression.search(bullet) for expression in compiled)]


def parse_timestamp(value):
    """Read an ISO-8601 instant, returning None for anything unrecognized."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def day(moment):
    """Render a release date, naming the gap when the date is unknown."""
    return moment.strftime("%Y-%m-%d") if moment else "undated"


def fetch(url, timeout=20):
    """Retrieve an HTTPS URL; callers degrade rather than fail on an error."""
    if not str(url).startswith("https://"):
        raise ValueError(f"Refusing a source that is not HTTPS: {url}")
    request = Request(url, headers={"User-Agent": "agent-toolbox-whats-new"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def write_json(path, record):
    """Replace a state file atomically so a crash cannot truncate it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    replaced = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        replaced = True
    finally:
        if not replaced:
            try:
                os.unlink(temporary)
            except OSError:
                pass  # Nothing further to do while unwinding.
    return path


def load_changelog(caches, url, required=None, offline=False, timeout=20, store=None):
    """Return changelog text and provenance from the freshest available source.

    A cache is trusted only when it already documents `required`, the running
    release: a harness that updated after its cache was written would
    otherwise report nothing for precisely the newest releases. Fetched text
    is written to `store` so that lag costs one download rather than one per
    invocation.
    """
    stale = None
    for cache in caches:
        try:
            text = Path(cache).read_text(encoding="utf-8")
        except OSError:
            continue
        if required is None or f"\n## {required}\n" in f"\n{text}\n":
            return text, f"cache {cache}"
        stale = stale or (text, cache)
    if offline:
        if stale is None:
            raise ValueError("No changelog cache is available and --offline forbids fetching")
        warn(f"Using a cache that predates {required} because --offline was given")
        return stale[0], f"stale cache {stale[1]}"
    try:
        text = fetch(url, timeout=timeout)
    except (OSError, URLError, ValueError) as error:
        if stale is None:
            raise ValueError(f"No changelog available: {error}") from error
        warn(f"Fetch failed ({error}); using a cache that predates {required}")
        return stale[0], f"stale cache {stale[1]}"
    if store is not None:
        try:
            Path(store).parent.mkdir(parents=True, exist_ok=True)
            Path(store).write_text(text, encoding="utf-8")
        except OSError as error:
            warn(f"Could not cache the fetched changelog ({error})")
    return text, url


def release_dates(cache, url, max_age_hours=24, timeout=20, offline=False):
    """Map version to release date from an npm packument, cached between runs.

    Dates are optional context: every failure degrades to whatever is already
    cached and says so, because only an explicit date window truly needs them.
    """
    cache, stored, fresh = Path(cache), {}, False
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        stored = data.get("times") if isinstance(data.get("times"), dict) else {}
        fetched = parse_timestamp(data.get("fetched_at"))
        fresh = bool(fetched and datetime.now(timezone.utc) - fetched < timedelta(hours=max_age_hours))
    except (OSError, ValueError):
        stored, fresh = stored or {}, False
    if not fresh and not offline:
        try:
            payload = json.loads(fetch(url, timeout=timeout))
            times = payload.get("time")
            if not isinstance(times, dict):
                raise ValueError("packument has no time table")
            stored = {name: value for name, value in times.items()
                      if name not in ("created", "modified")}
            write_json(cache, {
                "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "times": stored,
            })
        except (OSError, URLError, ValueError) as error:
            warn(f"Release dates unavailable ({error}); continuing with cached dates")
    return {name: moment for name, value in stored.items()
            if (moment := parse_timestamp(value)) is not None}


def load_state(path):
    """Read the baseline record; an unreadable or foreign file means no baseline."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        warn(f"{path}: ignoring an unreadable baseline ({error})")
        return {}
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        warn(f"{path}: ignoring a baseline written in an unsupported format")
        return {}
    return data


def save_state(path, release, previous=None, reported=None, source=None):
    """Record a new baseline, retaining recent ones so a digest can be re-read."""
    previous = previous or {}
    history = [entry for entry in previous.get("history", []) if isinstance(entry, dict)]
    if isinstance(previous.get("baseline"), dict):
        history.insert(0, previous["baseline"])
    moment = reported or datetime.now(timezone.utc)
    record = {
        "version": STATE_VERSION,
        "baseline": {
            "release": release,
            "reported_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
            **({"source": source} if source else {}),
        },
        "history": history[:HISTORY_LIMIT],
    }
    write_json(path, record)
    return record


def state_path(name, env=None):
    """Resolve the XDG state file holding a harness baseline."""
    return _xdg("XDG_STATE_HOME", ".local/state", name, env)


def cache_path(name, env=None):
    """Resolve an XDG cache file. Never write into a harness's own cache."""
    return _xdg("XDG_CACHE_HOME", ".cache", name, env)


def _xdg(variable, default, name, env=None):
    env = os.environ if env is None else env
    home = Path(env.get("HOME") or Path.home())
    return Path(env.get(variable) or home / default).expanduser() / "agent-toolbox" / name
