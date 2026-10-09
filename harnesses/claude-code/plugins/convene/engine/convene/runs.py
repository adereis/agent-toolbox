"""Where runs live and how a name becomes a directory.

State never lives inside the project. A run's records sit under
`$XDG_STATE_HOME/agent-toolbox/convene/<project-key>/<run>/`, and a bare
name resolves there; anything spelled as a path is taken literally.

What its seats run in, their workspaces and private homes, sits under
`$XDG_CACHE_HOME` instead, at the path the frozen plan names. The records
are the run's evidence and a backup should keep them. The environment is
large, holds a harness login while a turn runs, and is worth nothing once
the run is over, so it lives where backups skip.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from convene import SCHEMA, platform, workspace
from convene.storage import digest, identifier, read, trail, write, write_text

# https://bford.info/cachedir/: borg, restic and GNU tar skip a directory
# holding this file when asked to exclude caches, wherever it sits.
CACHEDIR_TAG = ("Signature: 8a477f597d28d172789f06886806bc55\n"
                "# This file is a cache directory tag created by convene.\n"
                "# Seat workspaces and private homes; a run's records are elsewhere.\n"
                "# For information about cache directory tags see https://bford.info/cachedir/\n")


def project_root(start=None):
    """The git top level of `start` (default: cwd), else `start` itself."""
    start = Path(start or Path.cwd()).resolve()
    result = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return start


def runs_dir(project, env=None):
    directory = platform.state_home(env) / platform.project_key(project)
    return directory


def register(project, env=None):
    """Record which project a key belongs to, so a listing can say so."""
    directory = runs_dir(project, env)
    marker = directory / "project.json"
    if not marker.exists():
        write(marker, {"root": str(Path(project).resolve())})
    return directory


def environment_for(project, name, env=None):
    """Where a new run's seats will run, under a tagged cache directory."""
    base = platform.cache_home(env)
    if not (base / "CACHEDIR.TAG").exists():
        write_text(base / "CACHEDIR.TAG", CACHEDIR_TAG)
    return base / platform.project_key(project) / name


def environment(root, plan):
    """The directory holding a run's `work/` and `homes/`.

    A plan prepared before environments moved to the cache names none, and
    its seats ran inside the run directory itself.
    """
    named = plan.get("environment")
    return Path(named) if named else Path(root)


def seat_work(root, plan, name):
    return environment(root, plan) / "work" / name


def seat_home(root, plan, name):
    return environment(root, plan) / "homes" / name


def removable(root, plan):
    """The paths `prune` would remove, as they exist now.

    The environment whole; for an older run whose environment is its own
    directory, only its seat repositories and private homes, since its
    workspaces sit beside the records.
    """
    place = environment(root, plan)
    if place != Path(root):
        return [place] if place.exists() else []
    found = []
    for seat in plan["seats"]:
        tree = seat_work(root, plan, seat["id"]) / workspace.REPO
        if seat["workspace"] == "worktree" and tree.exists():
            found.append(tree)
        if seat_home(root, plan, seat["id"]).exists():
            found.append(seat_home(root, plan, seat["id"]))
    return found


def disk_usage(paths):
    """Bytes the paths occupy on disk, each hard-linked file counted once.

    A clone made with `git clone --local` hard-links its objects, so a
    naive sum would count them once per seat.
    """
    seen, total = set(), 0
    for top in paths:
        for directory, dirs, files in os.walk(top):
            for name in dirs + files:
                try:
                    info = os.lstat(os.path.join(directory, name))
                except FileNotFoundError:
                    continue  # a running seat removed it between listing and reading
                if (info.st_dev, info.st_ino) not in seen:
                    seen.add((info.st_dev, info.st_ino))
                    total += info.st_blocks * 512
    return total


def environment_gone(root, plan):
    """Why the run's seats can no longer run, or None while they can.

    `prune` removes the environment on purpose; clearing the cache removes
    it without the run knowing. A standing assignment is written once, at
    prepare, and nothing recreates it, so a missing one means the
    workspace went with the rest.
    """
    if any(row.get("event") == "pruned" for row in trail(root)):
        return "it was pruned"
    missing = [s["id"] for s in plan["seats"]
               if not (seat_work(root, plan, s["id"]) / "START.md").is_file()]
    if missing:
        return (f"{environment(root, plan)} no longer holds the workspace of "
                f"{', '.join(missing)}; the cache was cleared or the directory removed")
    return None


def require_environment(root, plan):
    """Refuse a turn or a promotion once the environment is gone.

    A turn would resume a session that no longer exists, and a promotion
    would read empty outboxes and file the seats' work as unmade.
    """
    why = environment_gone(root, plan)
    if why:
        name = plan["name"]
        raise RuntimeError(
            f"run {name} can play no more turns and promote no more rounds: {why}. "
            "Its seats' sessions, workspaces and unpromoted files are gone. Its records "
            f"are intact, so convene board {name} and convene export {name} DIR still work; "
            "prepare a new run to go on")


def spelled_as_path(value):
    text = str(value)
    return "/" in text or text.startswith((".", "~"))


def resolve(value, project, env=None, *, must_exist=True):
    if spelled_as_path(value):
        root = Path(value).expanduser().resolve()
    else:
        root = (runs_dir(project, env) / identifier(str(value))).resolve()
    if must_exist and not (root / "plan.json").is_file():
        raise ValueError(f"no run at {root}; `convene runs` lists this project's runs")
    return root


def listing(project, env=None):
    directory = runs_dir(project, env)
    if not directory.is_dir():
        return []
    found = [p for p in directory.iterdir() if (p / "plan.json").is_file()]
    return sorted(found, key=lambda p: p.stat().st_mtime)


def latest(project, env=None):
    runs = listing(project, env)
    return runs[-1] if runs else None


def load(root, *, verify=True):
    root = Path(root).expanduser().resolve()
    plan = read(root / "plan.json")
    if plan.get("schema") != SCHEMA:
        raise ValueError("unsupported run schema")
    if verify and digest(root / "plan.json") != read(root / "plan-digest.json")["sha256"]:
        raise ValueError("frozen plan changed; a run's plan is never edited after prepare")
    return root, plan


def slug(text, limit=40):
    text = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return (text[:limit].rstrip("-")) or "run"
