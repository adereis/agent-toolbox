"""Tier ``none``: the seat runs in the operator's own harness home."""

from __future__ import annotations

import os
from pathlib import Path

from convene.harnesses import base_environment
from convene.isolation import Launch


class Unisolated:
    name = "none"

    def available(self):
        return None

    def home(self, harness, seat_home):
        """Where this tier keeps the harness state: the operator's own."""
        return harness.real_home()

    def wrap(self, argv, *, harness, seat_home, workspace, project_root, repo_ro):
        env = base_environment()
        env["HOME"] = str(Path.home())
        real = harness.real_home()
        if os.environ.get(harness.home_variable):
            env[harness.home_variable] = os.environ[harness.home_variable]
        return Launch(list(argv), env, str(workspace), {
            "tier": "none", "enforced": False, "harness_home": str(real),
            "note": "the seat runs in the operator's own harness home; project files "
                    "and the operator's memory are reachable, and session files land "
                    "in the operator's history"})
