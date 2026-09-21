"""Copy what a reader needs out of a run: the board, the receipts, the plan.

The export is where the operator writes `synthesis.md`. Private homes,
event streams and stderr stay in the run directory.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from convene import board, round as rounds_, runs
from convene.storage import read, write


def export(root, directory):
    root, plan = runs.load(root)
    directory = Path(directory).expanduser().resolve()
    if directory.exists() and any(directory.iterdir()):
        raise ValueError(f"export directory is not empty: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / "plan.json", directory / "plan.json")
    if (root / "board").exists():
        shutil.copytree(root / "board", directory / "board", dirs_exist_ok=True)
    receipts = {}
    for seat in plan["seats"]:
        for path in sorted((root / "records" / seat["id"]).glob("r[0-9][0-9][0-9]/*.json")):
            target = directory / "records" / seat["id"] / path.parent.name / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            if path.name == "receipt.json":
                receipts.setdefault(seat["id"], {})[path.parent.name] = read(path)
    (directory / "board.md").write_text(board.text(root, plan), encoding="utf-8")
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
    return "\n".join(lines) + "\n"
