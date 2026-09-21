"""From a plan file to a frozen run directory.

`prepare` validates, fills defaults, resolves every reference (persona,
instrument, isolation tier, model) and stages every seat's materials. It
then writes `plan.json` and its digest. Nothing about the assignment changes
after that: every turn re-hashes the inputs and the standing assignment.
"""

from __future__ import annotations

import datetime
import time
from pathlib import Path

from convene import (SCHEMA, config, harnesses, instruments, isolation, personas, runs,
                     staging, workspace)
from convene.harnesses import GRANTS, TOOL_SETS
from convene.presets import panel
from convene.storage import (digest, event, hashes, identifier, read, safe_name, write,
                             write_text)

KINDS = ("panel", "room", "fanout")
VISIBILITY = ("board", "blind")
WORKSPACES = ("none", "repo-ro", "worktree")
COMPACTION = ("forbid", "allow")
SEAT_FIELDS = ("harness", "model", "effort", "tools", "isolation", "visibility", "workspace",
               "compaction")
# Doors, opened explicitly: named grants, raw harness arguments and
# environment names passed through. Closed by default at every level.
ACCESS_FIELDS = ("grants", "claude_args", "codex_args", "env")
DEFAULTS = {"harness": "claude", "model": "opus", "effort": "high", "tools": "read",
            "isolation": "strongest", "visibility": "board", "workspace": "none",
            "compaction": "forbid", "rounds": 1, "jobs": 1, "post_length": 400,
            "grants": [], "claude_args": [], "codex_args": [], "env": []}
# What this version of the engine runs. Later phases lift these; until then
# a plan asking for more is refused by name rather than run partially.
LATER = "is not supported by this version of convene (a later phase adds it)"
PHASE_FIELDS = {"name", "rounds", "seats", "deliverable", "instruction", "length"}


def load(plan_path):
    plan_path = Path(plan_path).expanduser().resolve()
    if plan_path.suffix not in (".toml", ".json"):
        raise ValueError(f"a plan is a .toml or .json file: {plan_path}")
    supplied = read(plan_path)
    if not isinstance(supplied, dict):
        raise ValueError("a plan is a table of fields")
    return plan_path, supplied


def _brief(supplied, plan_dir):
    brief = supplied.get("brief")
    if isinstance(brief, str):
        brief = {"text": brief}
    if not isinstance(brief, dict) or not ({"path", "text"} & set(brief)):
        raise ValueError("brief must give a path or text")
    if "text" in brief:
        text = str(brief["text"])
    else:
        path = Path(brief["path"])
        path = path if path.is_absolute() else plan_dir / path
        if not path.is_file():
            raise ValueError(f"brief not found: {path}")
        text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("the brief is empty")
    return text


def _phases(supplied, rounds, seat_ids, kind):
    declared = supplied.get("phases") or []
    if not declared:
        return [{"name": "findings" if kind == "panel" else "discussion", "rounds": rounds}]
    total = 0
    for phase in declared:
        if not isinstance(phase, dict) or not isinstance(phase.get("rounds"), int) or phase["rounds"] < 1:
            raise ValueError("each phase needs a name and a positive round count")
        unknown = set(phase) - PHASE_FIELDS
        if unknown:
            raise ValueError(f"phase {phase.get('name')!r}: unknown fields {sorted(unknown)}")
        identifier(str(phase.get("name", "")))
        named = phase.get("seats")
        if named is not None and (not isinstance(named, list) or not named):
            raise ValueError(f"phase {phase.get('name')!r} must seat somebody")
        if set(named or seat_ids) - set(seat_ids):
            raise ValueError(f"phase {phase.get('name')!r} names unknown seats")
        if "deliverable" in phase:
            safe_name(phase["deliverable"])
            if phase["deliverable"] == "changes.patch":
                raise ValueError("changes.patch is captured from a worktree seat; do not declare it")
        if "instruction" in phase and not isinstance(phase["instruction"], str):
            raise ValueError(f"phase {phase.get('name')!r}: instruction must be text")
        if "length" in phase and (not isinstance(phase["length"], int) or phase["length"] < 1):
            raise ValueError(f"phase {phase.get('name')!r}: length must be a positive word count")
        total += phase["rounds"]
    if total != rounds:
        raise ValueError("phase rounds must add up to the plan's rounds")
    return declared


def _names(value, what):
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ValueError(f"{what} must be a list of names")
    return list(dict.fromkeys(value))


def _access(item, defaults, seat):
    """Grants, extra arguments and environment names, seat over defaults."""
    grants = _names(item.get("grants", defaults["grants"]), f"seat {seat['id']!r}: grants")
    unknown = sorted(set(grants) - set(GRANTS))
    if unknown:
        raise ValueError(f"seat {seat['id']!r}: unknown grants {unknown}; known: "
                         + ", ".join(f"{k} ({v})" for k, v in GRANTS.items()))
    key = f"{seat['harness']}_args"
    args = item.get("args", item.get(key, defaults.get(key, [])))
    if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
        raise ValueError(f"seat {seat['id']!r}: {key} must be a list of strings")
    env = _names(item.get("env", defaults["env"]), f"seat {seat['id']!r}: env")
    if "grants" in item and "mcp" in grants and seat["harness"] == "codex":
        pass  # documented: mcp on Codex opens the user config, as settings does
    return {"grants": grants, "args": list(args), "env": env}


def _seat(item, defaults, project_root, plan_dir, environ=None):
    if not isinstance(item, dict) or "id" not in item:
        raise ValueError("every seat needs an id")
    seat = {"id": identifier(item["id"])}
    for key in SEAT_FIELDS:
        seat[key] = item.get(key, defaults[key])
    seat.update(_access(item, defaults, seat))
    harness = harnesses.get(seat["harness"])
    harness.check_args(seat)
    if not harness.installed():
        raise ValueError(f"seat {seat['id']!r}: {seat['harness']} is not on PATH")
    if seat["tools"] not in TOOL_SETS:
        raise ValueError(f"seat {seat['id']!r}: tools must be one of {', '.join(TOOL_SETS)}")
    if seat["visibility"] not in VISIBILITY:
        raise ValueError(f"seat {seat['id']!r}: visibility must be one of {', '.join(VISIBILITY)}")
    if seat["workspace"] not in WORKSPACES:
        raise ValueError(f"seat {seat['id']!r}: workspace must be one of {', '.join(WORKSPACES)}")
    if seat["workspace"] == "worktree" and seat["tools"] != "write":
        raise ValueError(f"seat {seat['id']!r}: a worktree seat needs tools = \"write\"")
    if seat["compaction"] not in COMPACTION:
        raise ValueError(f"seat {seat['id']!r}: compaction must be one of {', '.join(COMPACTION)}")
    resolved = harness.resolve(seat["model"], seat["effort"], environ)
    seat.update(model=resolved["model"], effort=resolved["effort"],
                context_window=resolved.get("context_window"),
                model_evidence=resolved.get("model_evidence"))
    if seat["compaction"] == "forbid" and not seat["context_window"]:
        raise ValueError(f"seat {seat['id']!r}: no context ceiling is known for "
                         f"{seat['model']} ({resolved.get('catalog')}); set compaction = "
                         "\"allow\" to run without pinning the window")
    try:
        seat["isolation"] = isolation.resolve(seat["isolation"])
    except ValueError as exc:
        raise ValueError(f"seat {seat['id']!r}: {exc}") from exc
    seat["persona"] = personas.resolve(item.get("persona", defaults.get("persona")), project_root) \
        if item.get("persona", defaults.get("persona")) is not None else None
    if seat["persona"] is None:
        raise ValueError(f"seat {seat['id']!r}: name a persona")
    private = [staging.entry(m, plan_dir, project_root) for m in item.get("materials", [])]
    seat["_private"] = private
    return seat


def _start_text(plan, seat, common, private):
    """The standing assignment: who they are, what they were given, what to
    produce. Deliberately silent about promotion and the controller; a seat
    told it is executing a procedure starts writing like one."""
    others = len(plan["seats"]) - 1
    text = "{{persona}}\n\n"
    if plan["kind"] == "panel":
        text += (f"You are one of {others + 1} reviewers convened on the same change. Each "
                 "of you was given the same brief and works independently.\n\n")
    elif seat["visibility"] == "board":
        text += (f"You are one of {others + 1} people in a room working on the same brief. "
                 "Between your turns, the board with everyone's posts appears under board/ "
                 "in your working directory, one digest per round.\n\n")
    else:
        text += (f"You are one of {others + 1} people given the same brief. You work on your "
                 "own; you will not see what the others write.\n\n")
    text += "# Brief\n\n" + plan["brief"]["text"].strip() + "\n\n"
    reads = staging.listing(common + private)
    if reads:
        text += "# Materials\n\nThe files under materials/ in your working directory:\n\n" + reads + "\n\n"
    if seat["workspace"] == "repo-ro":
        text += (f"The repository is at {plan['project_root']}, read-only. Cite files by "
                 "their path there.\n\n")
    elif seat["workspace"] == "worktree":
        text += ("A checkout of the repository is at repo/ in your working directory. It is "
                 "yours to edit, build and test; whatever you change there is collected "
                 "with your post as a patch.\n\n")
    if plan.get("instrument"):
        text += "# What to produce\n\n" + plan["instrument"]["profile"]["prompt"].strip() + "\n\n"
    text += ("Your final message each turn is your post. It is what the others and the "
             f"operator read under your name, about {plan['post_length']} words, as finished "
             "text: no preamble about what you are going to do, and no summary of these "
             "instructions.\n")
    if seat["visibility"] == "board" and others:
        roster = "".join(f"- {s['persona']['profile']['label']} ({s['id']})\n"
                         for s in plan["seats"] if s["id"] != seat["id"])
        text += "\nAlso convened:\n\n" + roster
    return personas.compose(text, seat["persona"])


def prepare(plan_path, *, project_root=None, name=None, range_spec=None, environ=None,
            overrides=None):
    """Stage one workspace per seat and freeze the plan that governs them.

    ``overrides`` are command-line seat defaults (grants, tools) that win over
    the plan's own; they are recorded in the frozen plan like any default.
    """
    plan_path, supplied = load(plan_path)
    plan_dir = plan_path.parent
    project_root = runs.project_root(project_root)
    schema = supplied.get("schema", SCHEMA)
    if schema != SCHEMA:
        raise ValueError(f"unsupported plan schema {schema!r}")
    kind = supplied.get("kind", "panel")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    title = supplied.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("a plan needs a title")
    rounds = supplied.get("rounds", DEFAULTS["rounds"])
    if not isinstance(rounds, int) or rounds < 1:
        raise ValueError("rounds must be a positive integer")
    synthesis = supplied.get("synthesis", {"by": "operator"})
    if not isinstance(synthesis, dict) or synthesis.get("by") != "operator":
        raise ValueError(f"synthesis by a seat {LATER}; use by = \"operator\"")

    defaults = dict(DEFAULTS)
    configured, config_sources = config.load(project_root, environ)
    defaults.update({k: v for k, v in configured.items() if k in SEAT_FIELDS + ACCESS_FIELDS
                     or k in ("persona", "jobs")})
    defaults.update({k: supplied[k] for k in SEAT_FIELDS + ACCESS_FIELDS if k in supplied})
    defaults["persona"] = supplied.get("persona", defaults.get("persona"))
    for key in ("grants", "env"):
        defaults[key] = _names(defaults[key], key)
    if overrides:
        defaults.update(overrides)
    jobs = supplied.get("jobs", defaults.get("jobs", DEFAULTS["jobs"]))
    if not isinstance(jobs, int) or jobs < 1:
        raise ValueError("jobs must be a positive integer")
    post_length = supplied.get("post_length", defaults.get("post_length", DEFAULTS["post_length"]))
    if not isinstance(post_length, int) or post_length < 1:
        raise ValueError("post_length must be a positive word count")
    if kind == "panel" and "workspace" not in supplied:
        defaults["workspace"] = "repo-ro"

    brief = _brief(supplied, plan_dir)
    common = [staging.entry(m, plan_dir, project_root) for m in supplied.get("materials", [])]
    delta = None
    spec = range_spec or (supplied.get("panel") or {}).get("range")
    if kind == "panel":
        delta = panel.resolve_range(project_root, spec)
        common = [staging.entry(m, plan_dir, project_root) for m in panel.materials(project_root, delta)] + common
        brief = panel.brief_prelude(delta, project_root) + "\n" + brief
    elif spec:
        raise ValueError("--range applies to kind = \"panel\" only")

    instrument_ref = supplied.get("instrument", "review" if kind == "panel" else None)
    instrument = instruments.resolve(instrument_ref, project_root) if instrument_ref else None

    if not supplied.get("seats"):
        raise ValueError("declare at least one seat")
    seats = [_seat(item, defaults, project_root, plan_dir, environ) for item in supplied["seats"]]
    if len({s["id"] for s in seats}) != len(seats):
        raise ValueError("duplicate seat id")
    for seat in seats:
        if seat["tools"] == "none" and (common or seat["_private"]):
            raise ValueError(f"seat {seat['id']!r}: tools = \"none\" cannot read materials; "
                             "give the seat Read (tools = \"read\") or inline the brief")
    phases = _phases(supplied, rounds, [s["id"] for s in seats], kind)
    if any(s["workspace"] == "worktree" for s in seats):
        base = workspace.base_commit(project_root)
    else:
        base = None

    directory = runs.register(project_root, environ)
    if name:
        identifier(name)
        root = directory / name
        if root.exists():
            raise ValueError(f"run exists: {root}; pick another --name")
    else:
        stem = f"{datetime.date.today().isoformat()}-{kind}-{runs.slug(title)}"
        root, n = directory / stem, 2
        while root.exists():
            root, n = directory / f"{stem}-{n}", n + 1

    frozen = {
        "schema": SCHEMA, "kind": kind, "title": title.strip(), "name": root.name,
        "project_root": str(project_root), "plan_source": str(plan_path),
        "rounds": rounds, "jobs": jobs, "phases": phases, "synthesis": synthesis,
        "post_length": post_length, "base_commit": base,
        "brief": {"text": brief, "sha256": digest_text(brief)},
        "instrument": instrument, "delta": delta,
        "materials": [{k: v for k, v in m.items() if k != "content"} for m in common],
        "defaults": {k: defaults[k] for k in SEAT_FIELDS + ACCESS_FIELDS},
        "config_sources": config_sources, "overrides": overrides or {},
        "seats": [], "prepared_at": time.time(),
    }
    root.mkdir(parents=True, mode=0o700)
    (root / "board" / "posts").mkdir(parents=True)
    (root / "board" / "rounds").mkdir(parents=True)
    (root / "board" / "made").mkdir(parents=True)
    (root / "chair").mkdir()
    for seat in seats:
        private = seat.pop("_private")
        work = root / "work" / seat["id"]
        for sub in ("outbox", "board"):
            (work / sub).mkdir(parents=True)
        if seat["workspace"] == "worktree":
            workspace.create(project_root, work, base)
        staged = staging.stage(common + private, work / "materials")
        seat["materials"] = [m for m in staged if m["path"] not in {c["path"] for c in common}]
        seat["reads"] = [m["path"] for m in staged]
        seat["input_hashes"] = hashes(work / "materials")
        (root / "board" / "posts" / seat["id"]).mkdir(parents=True)
        (root / "homes" / seat["id"]).mkdir(parents=True, mode=0o700)
        write(root / "records" / seat["id"] / "state.json", {
            "status": "prepared", "session_id": None, "rounds": {},
            "persona": personas.identity(seat["persona"])})
        frozen["seats"].append(seat)
    # Second pass: the roster names every seat, which is knowable only once
    # all of them exist.
    for seat in frozen["seats"]:
        start = root / "work" / seat["id"] / "START.md"
        private = [m for m in seat["materials"]]
        write_text(start, _start_text(frozen, seat, frozen["materials"], private))
        seat["start_sha256"] = digest(start)
    write(root / "plan.json", frozen)
    write(root / "plan-digest.json", {"sha256": digest(root / "plan.json")})
    (root / ".gitignore").write_text(
        "# A run holds private harness homes with credentials staged for a turn.\n*\n")
    event(root, event="prepared", seats=[s["id"] for s in seats], rounds=rounds,
          isolation={s["id"]: s["isolation"] for s in seats})
    return root, frozen


def digest_text(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
