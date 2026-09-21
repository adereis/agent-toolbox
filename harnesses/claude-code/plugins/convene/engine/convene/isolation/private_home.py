"""Tier ``private-home``: portable, advisory isolation.

The seat's HOME and harness state directory are private to the seat, its
working directory is a neutral path outside the project, the environment is
an allow-list, and the harness flags remove instruction files and MCP
servers. What this tier cannot do is stop a tool from opening an absolute
path the seat guesses, which is why its attestation says ``advisory``.
"""

from __future__ import annotations

from pathlib import Path

from convene.harnesses import base_environment
from convene.isolation import Launch


class PrivateHome:
    name = "private-home"

    def available(self):
        return None

    def home(self, harness, seat_home):
        return Path(seat_home) / harness.name

    def wrap(self, argv, *, harness, seat_home, workspace, project_root, repo_ro):
        seat_home = Path(seat_home)
        if not harness.home_variable:
            raise RuntimeError(f"{harness.name} has no private-home tier; use enforced or none")
        home = self.home(harness, seat_home)
        home.mkdir(parents=True, exist_ok=True)
        harness.prepare_home(home)
        env = base_environment()
        env["HOME"] = str(seat_home)
        env.update(harness.private_env(home))
        real = harness.real_home()
        env.update(harness.credential_env(real))
        harness.stage_credentials(home, real)
        return Launch(list(argv), env, str(workspace), {
            "tier": "private-home", "enforced": False, "advisory": True,
            "home": str(seat_home), "harness_home": str(home),
            "workspace": str(workspace),
            "repository_read_only": None if not repo_ro else
            "by harness policy only (tools=read); the OS does not enforce it",
            "note": "a private HOME and harness state directory, an environment "
                    "allow-list and a neutral working directory; a tool given an "
                    "absolute path can still open it"})

    def finish(self, harness, seat_home):
        harness.unstage_credentials(self.home(harness, seat_home))
