"""Operator configuration: seat defaults that apply to every plan.

Two files, both optional, read in this order so the nearer one wins:
`$XDG_CONFIG_HOME/agent-toolbox/convene.toml` (user), then
`<project>/.convene/config.toml` (project). A plan overrides both and a seat
overrides the plan. Only the seat-default keys are accepted, so a typo is
an error naming the file rather than a silently ignored setting.
"""

from __future__ import annotations

import os
from pathlib import Path

from convene.storage import read

KEYS = ("harness", "model", "effort", "tools", "isolation", "visibility", "workspace",
        "compaction", "persona", "grants", "claude_args", "codex_args", "env", "jobs")


def user_path(environ=None):
    environ = os.environ if environ is None else environ
    home = Path(environ.get("HOME") or Path.home())
    base = Path(environ.get("XDG_CONFIG_HOME") or home / ".config").expanduser()
    return base / "agent-toolbox" / "convene.toml"


def project_path(project_root):
    return Path(project_root) / ".convene" / "config.toml"


def load(project_root, environ=None):
    """Merged defaults from the user and project files, with their sources."""
    merged, sources = {}, []
    for path in (user_path(environ), project_path(project_root)):
        if not path.is_file():
            continue
        data = read(path)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a table of seat defaults")
        unknown = sorted(set(data) - set(KEYS))
        if unknown:
            raise ValueError(f"{path}: unknown keys {unknown}; accepted: {', '.join(KEYS)}")
        merged.update(data)
        sources.append(str(path))
    return merged, sources
