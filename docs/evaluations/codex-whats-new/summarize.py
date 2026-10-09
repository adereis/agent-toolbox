#!/usr/bin/env python3
"""Validate complete grading and summarize native measurements by arm."""
import argparse
import json
from pathlib import Path
import statistics

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("target", type=Path)
parser.add_argument("--split", choices=["train", "held", "regression"], required=True)
args = parser.parse_args()
root = args.target
rubric = json.loads((root / "rubric.json").read_text())
cases = json.loads((root / "cases.json").read_text())
results = json.loads((root / f"{args.split}-results.json").read_text())
key = json.loads((root / f"{args.split}-key.json").read_text())
grades = json.loads((root / f"{args.split}-grades.json").read_text())
assert len({r["label"] for r in grades}) == len(grades), "Duplicate grade labels"
assert {r["label"] for r in grades} == set(key), "Incomplete grading"
by_id = {key[r["label"]]: r for r in grades}
groups = {}
for result in results:
    grade = by_id[result["id"]]
    case = result["case"]
    common = "common-topic" if cases[case]["report"]["mode"] == "topic" else "common-window"
    expected = {f"{section}.{check}" for section in (common, case) for check in rubric[section]}
    assert grade["case"] == case and set(grade["checks"]) == expected, result["id"]
    assert all(type(value) is bool for value in grade["checks"].values()), result["id"]
    receipt = result["receipt"]
    assert receipt["status"] == "answered" and receipt["inputs_intact"], result["id"]
    assert not receipt["red_flags"] and not receipt["compaction_observed"], result["id"]
    assert receipt["tool_calls"] == 0 and not receipt["mcp_servers"], result["id"]
    assert receipt["effort"] == result["effort"] and result["isolation"] == "enforced", result["id"]
    assert (receipt["model"] == result["family"]
            or receipt["model"].endswith("-" + result["family"])), result["id"]
    groups.setdefault((result["variant"], result["family"], result["effort"]), []).append((result, grade))
summary = []
for (variant, family, effort), rows in sorted(groups.items()):
    passed = sum(sum(g["checks"].values()) for r, g in rows)
    total = sum(len(g["checks"]) for r, g in rows)
    summary.append(dict(variant=variant, family=family, effort=effort, n=len(rows),
        passed=passed, checks=total, fraction=passed / total,
        mean_seconds=statistics.mean(r["receipt"]["seconds"] for r, g in rows),
        median_seconds=statistics.median(r["receipt"]["seconds"] for r, g in rows),
        mean_input_tokens=statistics.mean(r["receipt"]["usage"]["input_tokens"] for r, g in rows),
        mean_output_tokens=statistics.mean(r["receipt"]["usage"]["output_tokens"] for r, g in rows),
        false_actions=sum(len(g["false_actions"]) for r, g in rows),
        false_impacts=sum(len(g["false_impacts"]) for r, g in rows)))
(root / f"{args.split}-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print("| Prompt | Model | Effort | Checks passed | Mean seconds | False actions | False impact claims |")
print("|---|---|---|---:|---:|---:|---:|")
for row in summary:
    print(f"| {row['variant']} | {row['family']} | {row['effort']} | {row['passed']}/{row['checks']} "
          f"({row['fraction']:.0%}) | {row['mean_seconds']:.1f} | {row['false_actions']} | {row['false_impacts']} |")
