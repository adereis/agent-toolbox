"""What differs between Linux and macOS, behind one door.

Every caller that needs a platform fact asks here, so an unsupported platform
fails in exactly one place with a message naming what would work there.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path


def state_home(env=None):
    """`$XDG_STATE_HOME/agent-toolbox/convene`, on every platform.

    XDG rather than `~/Library/Application Support` on macOS, so an operator
    finds runs in the same place on both machines. Documented in the README.
    """
    env = os.environ if env is None else env
    home = Path(env.get("HOME") or Path.home())
    base = Path(env.get("XDG_STATE_HOME") or home / ".local/state").expanduser()
    return base / "agent-toolbox" / "convene"


def project_key(root):
    """A stable directory name for one project's runs."""
    return hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:12]


def process_identity(pid):
    """A token that changes if `pid` is reused, or None if the process is gone.

    Linux reads the start time out of `/proc`; macOS asks `ps`. Anything else
    raises, because "unknown" read as "not alive" is how a running seat's
    home gets removed out from under it.
    """
    if sys.platform.startswith("linux"):
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        except FileNotFoundError:
            return None
        return None if fields[0] == "Z" else fields[19]
    if sys.platform == "darwin":
        result = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                                capture_output=True, text=True, check=False)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return result.stdout.strip()
    raise RuntimeError(
        f"process liveness is not implemented on {sys.platform}; "
        "convene supports Linux and macOS")


def unsupported(feature, alternative):
    """The message an untested platform path prints before exiting non-zero."""
    return (f"{feature} is not available on {sys.platform}; {alternative}")
