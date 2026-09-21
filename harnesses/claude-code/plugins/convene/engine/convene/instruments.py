"""Question sets: what a phase asks every seat to produce, and in what shape."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from convene.personas import NAME, parse

FIELDS = {"schema_version", "id", "revision", "label", "description", "prompt"}
OPTIONAL = {"json_schema"}
PLUGIN_DIR = Path(__file__).resolve().parents[2] / "instruments"
PROJECT_DIR = ".convene/instruments"


def validate(data):
    if not isinstance(data, dict) or not FIELDS <= set(data) or set(data) - FIELDS - OPTIONAL:
        raise ValueError(f"instrument fields: {', '.join(sorted(FIELDS))}"
                         f" (optional: {', '.join(sorted(OPTIONAL))})")
    if data["schema_version"] != 1 or type(data["schema_version"]) is not int:
        raise ValueError("unsupported instrument schema")
    if not isinstance(data["id"], str) or not NAME.fullmatch(data["id"]):
        raise ValueError("instrument id must be a lowercase slug")
    if type(data["revision"]) is not int or data["revision"] < 1:
        raise ValueError("instrument revision must be a positive integer")
    for key in ("label", "description", "prompt"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"instrument {key} must contain text")
    if "json_schema" in data and not isinstance(data["json_schema"], dict):
        raise ValueError("instrument json_schema must be an object")
    return data


def directories(project_root=None):
    found = []
    if project_root:
        found.append(Path(project_root) / PROJECT_DIR)
    found.append(PLUGIN_DIR)
    return found


def _load(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"instrument source cannot be a symlink: {path}")
    raw = path.read_bytes().decode("utf-8")
    data = validate(parse(raw))
    if data["id"] != path.stem:
        raise ValueError(f"instrument filename and id disagree: {path}")
    return {"profile": data, "source": {"kind": "file", "path": str(path)},
            "text": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest()}


def catalog(project_root=None):
    out = {}
    for directory in reversed(directories(project_root)):
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            snapshot = _load(path)
            out[snapshot["profile"]["id"]] = snapshot
    return out


def resolve(reference, project_root=None):
    if isinstance(reference, dict) and set(reference) == {"inline"}:
        data = validate(reference["inline"])
        raw = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        return {"profile": data, "source": {"kind": "inline"}, "text": raw,
                "sha256": hashlib.sha256(raw.encode()).hexdigest()}
    if not isinstance(reference, str) or not NAME.fullmatch(reference):
        raise ValueError("instrument must be an id or {inline: INSTRUMENT}")
    for directory in directories(project_root):
        path = directory / f"{reference}.json"
        if path.exists():
            return _load(path)
    looked = ", ".join(str(d) for d in directories(project_root))
    raise ValueError(f"unknown instrument {reference!r}; looked in {looked}")
