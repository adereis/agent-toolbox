"""Free checks that a run's assumptions still hold on this machine.

Every probe here is rejected during argument parsing, before a token is
spent. The reason they exist is codex's asymmetry, which generalizes: an
unknown config key is accepted in silence while an invalid value errors
loudly. A renamed knob does not break; it quietly stops doing anything.
Feeding a deliberately invalid value turns that silent failure into a loud
one: if the error stops arriving, the key is dead.
"""

from __future__ import annotations

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


def run_probe(name, probe):
    """``(ok, detail)``. Output is matched, never the exit status: claude
    prints `Invalid setting source: bogus` and still exits 0."""
    argv = [name, *probe.args]
    if probe.offline and sys.platform.startswith("linux") and shutil.which(bwrap.BWRAP):
        argv = [bwrap.BWRAP, "--bind", "/", "/", "--dev-bind", "/dev", "/dev", "--proc",
                "/proc", "--unshare-net", *argv]
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
        out["excluded_mounts"] = [str(e) for e in bwrap.excluded_mounts()]
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
    if data.get("excluded_mounts"):
        # Either strategy keeps these out of reach: the cheap jail covers each
        # with an empty tmpfs, the fallback omits it from the reassembled root.
        lines.append("  network and automount filesystems unreachable in every jail: "
                     + ", ".join(data["excluded_mounts"]))
    bad = any(not e["installed"] or any(not p["ok"] for p in e["probes"])
              for e in data["harnesses"].values())
    return "\n".join(lines), bad
