"""The `convene` command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from convene import (doctor as doctor_, export as export_, follow as follow_, personas,
                     plan as plan_, runs, seal as seal_)
from convene import round as round_, board as board_

HELP = """\
convene: multi-seat panels over native coding-agent CLIs.

  prepare PLAN [--range A..B] [--name NAME]   freeze a plan into a run
          [--grant DOOR]... [--tools SET]       open doors for every seat
  run RUN [--jobs N] [--timeout S]            run rounds until done, converged or held
  round RUN N                                 run one round
  continue RUN SEAT [--round N]               retake a quota-stopped turn
  promote RUN N [--absent]                    close a round by hand
  extend RUN ROUNDS                           raise the round budget
  prune RUN [--force]                         remove worktrees and private homes
  follow RUN SEAT [--round N] [--thinking]    tail a seat's turn as it runs
  seal RUN [--round N]                        letter a blind round's drafts for reading
  unseal RUN [--round N]                      print the key, once judgment.md is written
  status RUN                                  what each seat did, with red flags
  board RUN [--round N] [--raw]               the published posts, attributed
  export RUN DIR                              copy board and receipts out
  usage RUN                                   tokens and cost per seat
  runs                                        this project's runs, oldest first
  personas [list|show ID]                     the persona catalog
  doctor [--no-probes]                        harnesses, credentials, tiers, flags

RUN is a run name under this project's state directory, or a path.
State lives under $XDG_STATE_HOME/agent-toolbox/convene (default
~/.local/state), never inside the project. --project DIR names the
project when it is not the current directory's git checkout.
"""


def main(argv=None):
    parser = argparse.ArgumentParser(prog="convene", description=HELP,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=None, help="project root (default: git top level of cwd)")
    parser.add_argument("--json", action="store_true", help="machine-readable output where supported")
    # Accepted after the verb too, which is where a hand types it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", dest="json_after")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=lambda **kw:
                                argparse.ArgumentParser(parents=[common], **kw))

    p = sub.add_parser("prepare", help="freeze a plan into a run directory")
    p.add_argument("plan")
    p.add_argument("--range", dest="range_spec", default=None, help="A..B or HEAD, for a panel")
    p.add_argument("--name", default=None, help="run name (default: date-kind-title)")
    p.add_argument("--grant", action="append", default=[], metavar="DOOR",
                   help="open a door for every seat: web, mcp, settings, instructions, hooks "
                        "(repeatable; a seat's own grants still apply)")
    p.add_argument("--tools", default=None, choices=("none", "read", "write", "research"),
                   help="tool set for every seat that does not name its own")

    p = sub.add_parser("run", help="run every round that is not yet published")
    p.add_argument("run")
    p.add_argument("--rounds", type=int, default=None)
    p.add_argument("--jobs", type=int, default=None, help="seats in parallel (default: the plan's)")
    p.add_argument("--timeout", type=float, default=None, help="seconds per seat turn")

    p = sub.add_parser("round", help="run one round")
    p.add_argument("run")
    p.add_argument("number", type=int)
    p.add_argument("--jobs", type=int, default=None)
    p.add_argument("--timeout", type=float, default=None)

    p = sub.add_parser("continue", help="retake a seat's turn after a provider quota stop")
    p.add_argument("run")
    p.add_argument("seat")
    p.add_argument("--round", dest="round_number", type=int, default=None,
                   help="default: the held round")
    p.add_argument("--timeout", type=float, default=None)

    p = sub.add_parser("promote", help="publish a round's board")
    p.add_argument("run")
    p.add_argument("number", type=int)
    p.add_argument("--absent", action="store_true",
                   help="record quota-stopped seats as absent instead of waiting")

    p = sub.add_parser("extend", help="raise the round budget")
    p.add_argument("run")
    p.add_argument("rounds", type=int)

    p = sub.add_parser("prune", help="remove worktrees and private homes; keep the records")
    p.add_argument("run")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("follow", help="print a seat's stream as it grows, until its turn ends")
    p.add_argument("run")
    p.add_argument("seat")
    p.add_argument("--round", dest="round_number", type=int, default=None,
                   help="follow a turn that has started (default: latest turn)")
    p.add_argument("--thinking", action="store_true", help="show reasoning too")
    p.add_argument("--width", type=int, default=88)

    p = sub.add_parser("seal", help="shuffle a round's drafts under letters; the key is never printed")
    p.add_argument("run")
    p.add_argument("--round", dest="round_number", type=int, default=None)
    p.add_argument("--seed", type=int, default=None, help="reproducible shuffle, for tests")
    p.add_argument("--force", action="store_true", help="reseal a round that is already sealed")

    p = sub.add_parser("unseal", help="print the identity key after judgment.md is on file")
    p.add_argument("run")
    p.add_argument("--round", dest="round_number", type=int, default=None)

    for name in ("status", "usage"):
        p = sub.add_parser(name)
        p.add_argument("run", nargs="?", default=None, help="default: the latest run")

    p = sub.add_parser("board", help="print the published board")
    p.add_argument("run", nargs="?", default=None)
    p.add_argument("--round", dest="round_number", type=int, default=None)
    p.add_argument("--raw", action="store_true", help="as the seats see it, without models")

    p = sub.add_parser("export", help="copy the board and receipts into DIR")
    p.add_argument("run")
    p.add_argument("directory")

    sub.add_parser("runs", help="list this project's runs")

    p = sub.add_parser("personas")
    p.add_argument("action", nargs="?", default="list", choices=("list", "show"))
    p.add_argument("persona", nargs="?", default=None)

    p = sub.add_parser("doctor", help="check harnesses, credentials, isolation tiers and flags")
    p.add_argument("--no-probes", action="store_true", help="skip the flag-liveness probes")

    args = parser.parse_args(argv)
    args.json = args.json or getattr(args, "json_after", False)
    try:
        return dispatch(args)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"convene {args.command}: {exc}", file=sys.stderr)
        return 1


def _run(args, project):
    value = args.run
    if value is None:
        latest = runs.latest(project)
        if latest is None:
            raise ValueError("no runs for this project yet; `convene prepare PLAN` creates one")
        return latest
    return runs.resolve(value, project)


def dispatch(args):
    project = runs.project_root(args.project)
    if args.command == "prepare":
        overrides = {}
        if args.grant:
            overrides["grants"] = [g.strip() for item in args.grant for g in item.split(",") if g.strip()]
        if args.tools:
            overrides["tools"] = args.tools
        root, frozen = plan_.prepare(args.plan, project_root=project, name=args.name,
                                     range_spec=args.range_spec, overrides=overrides)
        if args.json:
            print(json.dumps({"run": str(root), "name": frozen["name"],
                              "seats": {s["id"]: s["isolation"] for s in frozen["seats"]}}))
        else:
            print(f"prepared {frozen['name']} at {root}")
            for seat in frozen["seats"]:
                doors = ("" if not seat["grants"] else " grants=" + ",".join(seat["grants"]))
                print(f"  {seat['id']}: {seat['harness']}/{seat['model']} effort={seat['effort']} "
                      f"tools={seat['tools']} isolation={seat['isolation']} "
                      f"workspace={seat['workspace']}{doors}")
            per = frozen.get("per_harness")
            print(f"  {frozen['jobs']} seat(s) at once, at most {per} per harness")
            delta = frozen.get("delta") or {}
            if delta.get("kind") == "range":
                commits = delta.get("commits") or []
                print(f"  range {delta.get('spec')}: {len(commits)} commit(s)")
                for line in commits:
                    sha, _, subject = line.partition(" ")
                    print(f"    {sha[:9]} {subject}")
                # A..B is left-exclusive, so the commit a user names as A is
                # not reviewed. Saying which one it is turns a silent
                # off-by-one into something visible before the run starts.
                if delta.get("base"):
                    print(f"    base, not reviewed: {delta['base'][:9]}")
            if frozen["config_sources"]:
                print("  defaults from: " + ", ".join(frozen["config_sources"]))
            print(f"next: convene run {frozen['name']}")
        return 0
    if args.command == "run":
        root = runs.resolve(args.run, project)
        played, why = round_.run(root, rounds=args.rounds, jobs=args.jobs, timeout=args.timeout)
        for number, outcome in played:
            posted = outcome["_board"].get("posted", [])
            held = outcome["_board"].get("held", [])
            print(f"round {number}: " + ", ".join(f"{k}={v}" for k, v in outcome.items()
                                                  if k != "_board")
                  + (f"; held on {', '.join(held)}" if held else f"; posted {len(posted)}"))
        print(f"{why}; next: convene status {root.name}")
        return 3 if why.startswith("held") else 0
    if args.command == "round":
        outcome = round_.run_round(runs.resolve(args.run, project), args.number, jobs=args.jobs,
                                   timeout=args.timeout)
        held = outcome["_board"].get("held", [])
        print(f"round {args.number}: " + ", ".join(f"{k}={v}" for k, v in outcome.items() if k != "_board")
              + (f"; held on {', '.join(held)}" if held else "; published"))
        return 3 if held else 0
    if args.command == "continue":
        root = runs.resolve(args.run, project)
        number = args.round_number
        if number is None:
            data = round_.status(root)
            if not data["held"]:
                raise ValueError("no round is held; pass --round N")
            number = data["held"][0]["round"]
        status = round_.continue_seat(root, number, args.seat, timeout=args.timeout)
        print(f"{args.seat} round {number}: {status}")
        if status == "answered":
            print(f"next: convene promote {root.name} {number} once every held seat has answered")
        return 0 if status == "answered" else 3
    if args.command == "promote":
        root = runs.resolve(args.run, project)
        outcome = (round_.promote_absent if args.absent else round_.promote_held)(root, args.number)
        print(f"round {args.number} published: posted {', '.join(outcome['posted']) or 'nobody'}"
              + (f"; absent {', '.join(outcome['absent'])}" if outcome["absent"] else ""))
        return 0
    if args.command == "extend":
        allowed = board_.extend(runs.resolve(args.run, project), args.rounds)
        print(f"budget is now {allowed} rounds")
        return 0
    if args.command == "prune":
        removed = round_.prune(runs.resolve(args.run, project), force=args.force)
        print("removed:\n" + "\n".join(f"  {r}" for r in removed) if removed else "nothing to remove")
        return 0
    if args.command == "follow":
        root, plan = runs.load(runs.resolve(args.run, project), verify=False)
        seat = round_.seat_named(plan, args.seat)
        record = (root / "records" / seat["id"] / f"r{args.round_number:03d}"
                  if args.round_number is not None else None)
        try:
            follow_.follow(root, seat["id"], seat["harness"], record=record,
                           thinking=args.thinking, width=args.width)
        except KeyboardInterrupt:
            print()
        return 0
    if args.command == "seal":
        result = seal_.seal(runs.resolve(args.run, project), args.round_number, seed=args.seed,
                            force=args.force)
        print(f"round {result['round']} sealed as {', '.join(result['letters'])} under "
              f"{result['directory']}\nread each letter's post.md and files, write your judgment to "
              f"{result['judgment']}, then: convene unseal {args.run}")
        if result["judgment_kept"]:
            print("your existing judgment.md was kept; the letters under it were reshuffled")
        return 0
    if args.command == "unseal":
        result = seal_.unseal(runs.resolve(args.run, project), args.round_number)
        print(f"round {result['round']} unsealed:")
        for letter, who in result["key"].items():
            print(f"  {letter} = {who['seat']} ({who['served']})")
        return 0
    if args.command == "status":
        data = round_.status(_run(args, project))
        print(json.dumps(data, indent=2) if args.json else round_.render_status(data))
        return 0
    if args.command == "usage":
        root, plan = runs.load(_run(args, project), verify=False)
        seal_.guard(root, plan, "usage")
        rows = round_.usage(root)
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            print(f"{'seat':<16}{'harness/model':<28}{'turns':>6}{'input':>10}{'output':>10}"
                  f"{'cache read':>12}{'cost':>10}")
            for row in rows:
                cost = f"{row['cost_usd']:.4f}" if row["cost_usd"] is not None else "unknown"
                print(f"{row['seat']:<16}{row['harness'] + '/' + row['model']:<28}"
                      f"{row['turns']:>6}{row['input']:>10}{row['output']:>10}"
                      f"{row['cache_read']:>12}{cost:>10}")
        return 0
    if args.command == "board":
        root, plan = runs.load(_run(args, project), verify=False)
        seal_.guard(root, plan, "the board")
        print(board_.text(root, plan, round_number=args.round_number, attribute=not args.raw), end="")
        return 0
    if args.command == "export":
        where = export_.export(runs.resolve(args.run, project), args.directory)
        print(f"exported to {where}; write synthesis.md there")
        return 0
    if args.command == "runs":
        for root in runs.listing(project):
            print(root.name)
        return 0
    if args.command == "personas":
        catalog = personas.catalog(project)
        if args.action == "show":
            if not args.persona or args.persona not in catalog:
                raise ValueError(f"name a persona from: {', '.join(catalog)}")
            snapshot = catalog[args.persona]
            print(json.dumps(snapshot, indent=2) if args.json else snapshot["profile"]["prompt"])
            return 0
        for name, snapshot in catalog.items():
            profile = snapshot["profile"]
            print(f"{name}@{profile['revision']}  {profile['label']}: {profile['description']}")
        return 0
    if args.command == "doctor":
        data = doctor_.report(probes=not args.no_probes, project_root=project)
        if args.json:
            print(json.dumps(data, indent=2))
            return 0
        text, bad = doctor_.render(data)
        print(text)
        return 1 if bad else 0
    raise ValueError(f"unknown command {args.command}")
