"""Isolation tiers: how far the OS, not the prompt, keeps a seat away from
the operator's state and the project.

- ``enforced``: a bubblewrap jail (Linux). The root is an allow-list of
  system trees bound read-only, the home is blanked, and only the seat's
  private harness home, the harness launcher and the declared workspace
  are bound back. A `Read` of an absolute path fails.
- ``private-home``: portable. The seat gets a private HOME and harness state
  directory and a neutral working directory, and the harness flags remove
  project instructions and MCP servers. Advisory: the OS does not stop a
  `Read` of an absolute path.
- ``none``: the seat runs in the operator's own harness home.

``strongest`` resolves to the first available tier at prepare time. The
resolved tier is frozen into the plan and stamped on every receipt, so a run
never claims more than it enforced.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

TIERS = ("enforced", "private-home", "none")
REQUESTS = ("strongest", *TIERS)


@dataclass
class Launch:
    argv: list
    env: dict
    cwd: str
    attestation: dict = field(default_factory=dict)
    # Descriptors the launched process must inherit (a jail's `--sync-fd`).
    # The launcher calls `release()` once the process holds them, so the
    # tier's own copy does not keep a helper alive past the seat.
    pass_fds: tuple = ()

    def release(self):
        for fd in self.pass_fds:
            os.close(fd)
        self.pass_fds = ()


def tiers():
    from convene.isolation import bwrap, none, private_home
    return {"enforced": bwrap.Enforced(), "private-home": private_home.PrivateHome(),
            "none": none.Unisolated()}


def get(name):
    available = tiers()
    if name not in available:
        raise ValueError(f"unknown isolation tier {name!r}; one of {', '.join(TIERS)}")
    return available[name]


def unavailable(name, harness=None):
    """Why tier `name` cannot run this harness here, or None."""
    reason = get(name).available()
    if reason:
        return reason
    if name == "enforced" and harness is not None and harness.bus_names:
        from convene.isolation import bwrap
        reason = bwrap.bus_proxy_missing()
        if reason:
            return f"{harness.name} needs the session bus for {', '.join(harness.bus_names)}; {reason}"
    if name == "private-home" and harness is not None and not harness.home_variable:
        return (f"{harness.name} has no variable that relocates its home, so there is no "
                "private-home tier for it; use \"enforced\" (Linux, bubblewrap) or \"none\"")
    return None


def resolve(requested, harness=None):
    """The tier name a request settles on, or a ValueError naming why not.

    ``strongest`` walks the tiers in order and takes the first one available
    for this harness. A named tier that is unavailable is an error, not a
    downgrade.
    """
    if requested not in REQUESTS:
        raise ValueError(f"isolation must be one of {', '.join(REQUESTS)}: {requested!r}")
    if requested != "strongest":
        reason = unavailable(requested, harness)
        if reason:
            raise ValueError(f"isolation {requested!r} is unavailable: {reason}")
        return requested
    reasons = []
    for name in TIERS:
        reason = unavailable(name, harness)
        if reason is None:
            return name
        reasons.append(f"{name}: {reason}")
    raise ValueError("no isolation tier is available: " + "; ".join(reasons))
