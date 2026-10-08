"""Free checks that a run's assumptions still hold on this machine.

Every probe here is rejected during argument parsing, before a token is
spent. The reason they exist is codex's asymmetry, which generalizes: an
unknown config key is accepted in silence while an invalid value errors
loudly. A renamed knob does not break; it quietly stops doing anything.
Feeding a deliberately invalid value turns that silent failure into a loud
one: if the error stops arriving, the key is dead. Where an invalid value
proves nothing, as for a codex feature, whose value is type-checked whether
or not the feature exists, a probe asks the CLI to show the setting applied
and matches its `patterns` against what it shows.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

from convene import harnesses, isolation, platform
from convene.isolation import bwrap


@dataclass(frozen=True)
class Probe:
    label: str
    args: tuple
    expect: str = "error"   # "error" | "ok"
    needles: tuple = ()
    why: str = ""
    offline: bool = True
    patterns: tuple = ()    # regular expressions the output must match


def run_probe(name, probe):
    """``(ok, detail)``. Output is matched, never the exit status: claude
    prints `Invalid setting source: bogus` and still exits 0."""
    argv = [name, *probe.args]
    if probe.offline and sys.platform.startswith("linux") and shutil.which(bwrap.BWRAP):
        argv = bwrap.offline_jail() + argv
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                                stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"probe did not run ({exc})"
    out = (result.stdout or "") + (result.stderr or "")
    low = out.lower()
    if probe.expect == "ok":
        if result.returncode != 0:
            return False, f"rejected (exit {result.returncode}): {out.strip()[:120]}"
    elif not any(w in low for w in ("error", "invalid", "unknown", "not recognized", "not found")):
        return False, "accepted a deliberately invalid value; the key is dead and the flag is now a silent no-op"
    missing = [n for n in probe.needles if n.lower() not in low]
    if missing:
        return False, f"output no longer mentions {', '.join(missing)}"
    unmatched = [p for p in probe.patterns if not re.search(p, out, re.M)]
    if unmatched:
        return False, f"output no longer matches {', '.join(unmatched)}"
    return True, ""


def report(*, probes=True, project_root=None):
    out = {"python": sys.version.split()[0], "platform": sys.platform,
           "state_home": str(platform.state_home()), "harnesses": {}, "tiers": {}}
    if project_root:
        out["project_root"] = str(project_root)
    for name, harness in harnesses.registry().items():
        entry = {"installed": harness.installed(), "version": None, "credentials": None,
                 "probes": []}
        if entry["installed"]:
            entry["version"] = harness.version()
            try:
                harness.credential_env(harness.real_home())
                files = harness.credential_files(harness.real_home())
                missing = [str(f) for f in files if not f.exists()]
                entry["credentials"] = "missing: " + ", ".join(missing) if missing else "present"
            except RuntimeError as exc:
                entry["credentials"] = str(exc)
            if probes:
                for probe in harness.probes:
                    ok, detail = run_probe(name, probe)
                    entry["probes"].append({"label": probe.label, "ok": ok,
                                            "detail": detail, "why": probe.why})
        out["harnesses"][name] = entry
    for name, tier in isolation.tiers().items():
        out["tiers"][name] = tier.available()
    if sys.platform.startswith("linux"):
        out["jail_root"] = [str(t) for t in bwrap.bound_trees(bwrap.system_root())]
        out["bus_proxy"] = shutil.which(bwrap.BUS_PROXY)
    return out


def render(data):
    lines = [f"python {data['python']} on {data['platform']}",
             f"state under {data['state_home']}"]
    if data.get("project_root"):
        lines.append(f"project {data['project_root']}")
    for name, entry in data["harnesses"].items():
        if not entry["installed"]:
            lines.append(f"✗ {name}: not on PATH")
            continue
        lines.append(f"✓ {name} {entry['version'] or '?'} at {entry['installed']}; "
                     f"credentials {entry['credentials']}")
        for probe in entry["probes"]:
            mark = "✓" if probe["ok"] else "✗"
            lines.append(f"  {mark} {probe['label']}" + ("" if probe["ok"] else
                         f": {probe['detail']} ({probe['why']})"))
    for name, reason in data["tiers"].items():
        lines.append(f"{'✓' if reason is None else '✗'} isolation {name}" +
                     ("" if reason is None else f": {reason}"))
    if data.get("jail_root"):
        # Only the enforced tier has a root of its own. `private-home` and
        # `none` give the seat the real root, so say where this applies.
        where = ("the enforced jail" if data["tiers"].get("enforced") is None
                 else "the enforced jail, which is unavailable here")
        lines.append(f"  root of {where}: " + ", ".join(data["jail_root"])
                     + " read-only; nothing else exists inside (other tiers give the "
                     "seat the real root)")
        proxy = data.get("bus_proxy")
        lines.append(f"  {bwrap.BUS_PROXY} {proxy}" if proxy else
                     f"  {bwrap.BUS_PROXY} missing: an agy seat cannot use the enforced "
                     "jail (Fedora: dnf install xdg-dbus-proxy)")
    bad = any(not e["installed"] or any(not p["ok"] for p in e["probes"])
              for e in data["harnesses"].values())
    return "\n".join(lines), bad
