"""Reusable perspectives. A persona never grants access or selects a model."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

NAME = re.compile(r"[a-z][a-z0-9-]*")
FIELDS = {"schema_version", "id", "revision", "label", "description", "tags", "prompt"}
PLUGIN_DIR = Path(__file__).resolve().parents[2] / "personas"
PROJECT_DIR = ".convene/personas"


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def parse(text):
    return json.loads(text, object_pairs_hook=_pairs)


def validate(data):
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError(f"persona fields must be exactly: {', '.join(sorted(FIELDS))}")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported persona schema")
    if not isinstance(data["id"], str) or not NAME.fullmatch(data["id"]):
        raise ValueError("persona id must be a lowercase slug")
    if type(data["revision"]) is not int or data["revision"] < 1:
        raise ValueError("persona revision must be a positive integer")
    for key in ("label", "description", "prompt"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"persona {key} must contain text")
    tags = data["tags"]
    if (not isinstance(tags, list) or any(not isinstance(t, str) or not NAME.fullmatch(t)
                                          for t in tags) or len(set(tags)) != len(tags)):
        raise ValueError("persona tags must be unique slugs")
    return data


def directories(project_root=None):
    """Where personas are looked up: the project's own first, then the plugin's."""
    found = []
    if project_root:
        found.append(Path(project_root) / PROJECT_DIR)
    found.append(PLUGIN_DIR)
    return found


def catalog(project_root=None):
    """Every persona by id; a project persona shadows a plugin one."""
    out = {}
    for directory in reversed(directories(project_root)):
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            snapshot = _load(path)
            out[snapshot["profile"]["id"]] = snapshot
    return out


def _load(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"persona source cannot be a symlink: {path}")
    raw = path.read_bytes().decode("utf-8")
    data = validate(parse(raw))
    if data["id"] != path.stem:
        raise ValueError(f"persona filename and id disagree: {path}")
    return {"profile": data, "source": {"kind": "file", "path": str(path)},
            "text": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest()}


def resolve(reference, project_root=None):
    """A frozen snapshot from an id, an id@revision, or an inline profile."""
    if isinstance(reference, dict) and set(reference) == {"inline"}:
        data = copy.deepcopy(validate(reference["inline"]))
        raw = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        return {"profile": data, "source": {"kind": "inline"}, "text": raw,
                "sha256": hashlib.sha256(raw.encode()).hexdigest()}
    if isinstance(reference, dict) and set(reference) == {"frozen"}:
        return verify(reference["frozen"])
    if not isinstance(reference, str):
        raise ValueError("persona must be an id, id@revision, or {inline: PROFILE}")
    name, sep, rev = reference.partition("@")
    if sep and not rev.isdecimal():
        raise ValueError("persona revision must be an integer")
    for directory in directories(project_root):
        path = directory / f"{name}.json"
        if path.exists():
            snapshot = _load(path)
            if sep and snapshot["profile"]["revision"] != int(rev):
                raise ValueError(f"persona revision unavailable: {name}@{rev} "
                                 f"(found {snapshot['profile']['revision']})")
            return snapshot
    looked = ", ".join(str(d) for d in directories(project_root))
    raise ValueError(f"unknown persona {name!r}; looked in {looked}; "
                     "`convene personas list` prints the catalog")


def verify(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {"profile", "source", "text", "sha256"}:
        raise ValueError("invalid frozen persona")
    if hashlib.sha256(snapshot["text"].encode()).hexdigest() != snapshot["sha256"]:
        raise ValueError("frozen persona hash changed")
    if validate(parse(snapshot["text"])) != snapshot["profile"]:
        raise ValueError("frozen persona disagrees with its bytes")
    return snapshot


def compose(text, snapshot):
    """Fill the `{{persona}}` slot, or prefix the perspective when there is none."""
    profile = verify(snapshot)["profile"]["prompt"]
    if "{{persona}}" in text:
        return text.replace("{{persona}}", profile)
    return "=== PERSPECTIVE ===\n" + profile + "\n\n" + text


def identity(snapshot):
    profile = verify(snapshot)["profile"]
    return {"id": profile["id"], "revision": profile["revision"], "sha256": snapshot["sha256"]}
