"""Copy what a reader needs out of a run: the board, the receipts, the plan.

The export is where the operator writes `synthesis.md`. Private homes,
event streams and stderr stay in the run directory. It also names the
`Assisted-by` trailers for the commit that lands the run's work, read from
the receipts so no version is ever guessed. Export refuses while a round is
withheld, so the credits never reach a sealed round's reader.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from convene import board, harnesses, round as rounds_, runs, seal
from convene.storage import read, write


def credits(plan, receipts):
    """The `Assisted-by` trailers for this run, and the seats it cannot credit.

    One line per model that answered a turn, named by the version its own
    stream reported rather than the family the plan asked for, reduced by
    the harness to the bare API id (no `[1m]` window, no effort suffix), and
    sorted so the list says nothing about seat order. A seat that answered without naming its model is
    returned by id, to be credited by hand: a guessed version would be a
    false credit. No receipt records the operator's own session, so its line
    is the operator's to add.
    """
    lines, unnamed = set(), []
    for seat in plan["seats"]:
        answered = [got for got in receipts.get(seat["id"], {}).values()
                    if got.get("status") == "answered"]
        harness = harnesses.get(seat["harness"])
        served = {harness.credited_model(got["model"]) for got in answered if got.get("model")}
        lines.update(f"Assisted-by: {harness.product} ({model})" for model in served)
        if answered and not served:
            unnamed.append(seat["id"])
    return sorted(lines), unnamed


def export(root, directory):
    root, plan = runs.load(root)
    seal.guard(root, plan, "export")
    directory = Path(directory).expanduser().resolve()
    if directory.exists() and any(directory.iterdir()):
        raise ValueError(f"export directory is not empty: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "plan.json", directory / "plan.json")
    if (root / "board").exists():
        shutil.copytree(root / "board", directory / "board", dirs_exist_ok=True)
    if (root / "sealed").exists():
        shutil.copytree(root / "sealed", directory / "sealed", dirs_exist_ok=True)
    receipts = {}
    for seat in plan["seats"]:
        for path in sorted((root / "records" / seat["id"]).glob("r[0-9][0-9][0-9]/*.json")):
            target = directory / "records" / seat["id"] / path.parent.name / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            if path.name == "receipt.json":
                receipts.setdefault(seat["id"], {})[path.parent.name] = read(path)
    (directory / "board.md").write_text(board.text(root, plan), encoding="utf-8")
    assisted_by, unnamed = credits(plan, receipts)
    summary = {"run": str(root), "title": plan["title"], "kind": plan["kind"],
               "seats": {s["id"]: {"label": board.label(s), "harness": s["harness"],
                                   "model": s["model"], "effort": s["effort"],
                                   "tools": s["tools"], "isolation": s["isolation"]}
                         for s in plan["seats"]},
               "receipts": {seat: {r: {k: v for k, v in got.items()
                                       if k in ("status", "model", "requested_model", "effort",
                                                "tool_calls", "seconds", "red_flags",
                                                "compaction_observed", "inputs_intact", "error")}
                                   | {"tier": (got.get("isolation") or {}).get("tier")}
                                   for r, got in by_round.items()}
                            for seat, by_round in receipts.items()},
               "credits": {"assisted_by": assisted_by, "unnamed": unnamed},
               "usage": rounds_.usage(root)}
    write(directory / "summary.json", summary)
    (directory / "README.md").write_text(_readme(summary), encoding="utf-8")
    return directory


def _readme(summary):
    lines = [f"# {summary['title']}", "", f"Exported from `{summary['run']}`.", "",
             "- `board.md`: every published post, attributed by seat and model.",
             "- `records/<seat>/rNNN/receipt.json`: what actually ran for each turn.",
             "- `summary.json`: receipts and usage in one document.",
             "- `synthesis.md`: the operator's synthesis, written here after reading the board.",
             "", "## Receipts", "",
             "| seat | harness/model | round | status | served | tier | tool calls | red flags |",
             "|---|---|---|---|---|---|---|---|"]
    for seat, by_round in summary["receipts"].items():
        info = summary["seats"][seat]
        for r, got in by_round.items():
            lines.append(f"| {seat} | {info['harness']}/{info['model']} | {r} | {got.get('status')} "
                         f"| {got.get('model') or '?'} | {got.get('tier')} | {got.get('tool_calls')} "
                         f"| {'; '.join(got.get('red_flags') or []) or 'none'} |")
    lines += ["", "## Credit", ""] + credit_lines(summary["credits"])
    return "\n".join(lines) + "\n"


def credit_lines(credit):
    """The credit section as text, shared by the export README and the CLI."""
    out = []
    if credit["assisted_by"]:
        out += ["A commit that lands this run's work credits each model that answered:",
                "", "```", *credit["assisted_by"], "```", ""]
    else:
        out += ["No seat answered with a named model.", ""]
    if credit["unnamed"]:
        out += [f"Answered without naming a model, so credit by hand from the harness: "
                f"{', '.join(credit['unnamed'])}.", ""]
    out.append("Add a line for the session that ran the run; no receipt records it.")
    return out
