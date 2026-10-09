#!/usr/bin/env python3
"""Extract answers and non-sensitive receipts; shuffle answers for blind grading."""
import argparse
import json
from pathlib import Path
import random

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("target", type=Path)
parser.add_argument("run", type=Path)
parser.add_argument("--split", choices=["train", "held", "regression"], required=True)
parser.add_argument("--partial", action="store_true", help="Collect only completed receipts")
args = parser.parse_args()
manifest = json.loads((args.target / f"{args.split}-manifest.json").read_text())
random.Random(20261009 if args.split == "held" else 20261008).shuffle(manifest)
results = []
blind, key = [], {}
for i, item in enumerate(manifest, 1):
    record = args.run / "records" / item["id"] / "r001"
    if args.partial and not (record / "receipt.json").exists():
        continue
    receipt = json.loads((record / "receipt.json").read_text())
    if receipt["status"] != "answered":
        raise SystemExit(f"{item['id']}: {receipt['status']}: {receipt.get('error')}")
    result = {**item, "answer": (record / "answer.md").read_text(),
        "receipt": {key: receipt.get(key) for key in (
            "model", "effort", "seconds", "usage", "tool_calls", "tools_used", "mcp_servers",
            "compaction_observed", "red_flags", "status", "inputs_intact")},
        "isolation": receipt["isolation"]["tier"]}
    results.append(result)
    label = f"R{i:02}"
    blind.append({"label": label, "case": result["case"], "answer": result["answer"]})
    key[label] = result["id"]
for name, data in (("results", results), ("blind", blind), ("key", key)):
    (args.target / f"{args.split}-{name}.json").write_text(json.dumps(data, indent=2) + "\n")
print(f"Collected {len(results)} answered sessions; sanitized receipts and blinded answers saved.")
