"""Where runs live and how a name becomes a directory.

State never lives inside the project. Runs sit under
`$XDG_STATE_HOME/agent-toolbox/convene/<project-key>/<run>/`, and a bare
name resolves there; anything spelled as a path is taken literally.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from convene import SCHEMA, platform
from convene.storage import digest, identifier, read, write


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
