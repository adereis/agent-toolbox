"""Freezing materials into a seat's workspace.

Materials are copied, never linked, and hashed once staged. A filename
carrying a model id, an author or a verdict puts that in the room, so seats
are shown a label when the plan gives one. Instruction files never travel
as materials: a staged AGENTS.md is a prompt injection with a filename.
"""

from __future__ import annotations

from pathlib import Path

from convene.storage import relative

FORBIDDEN_PARTS = {"AGENTS.md", "CLAUDE.md", "CODEX.md", "GEMINI.md", ".claude", ".codex",
                   ".convene", ".gemini"}


def entry(item, plan_dir, project_root):
    """Normalize one material entry to {path, label, source} with bytes read."""
    if isinstance(item, str):
        item = {"path": item}
    if not isinstance(item, dict) or "path" not in item and "text" not in item:
        raise ValueError(f"a material needs a path or text: {item!r}")
    staged = relative(item.get("as", item["path"]))
    if any(part in FORBIDDEN_PARTS for part in staged.parts):
        raise ValueError(f"instruction files never travel as materials: {staged}")
    if "text" in item:
        content = str(item["text"]).encode("utf-8")
        source = {"kind": "inline"}
    else:
        source_path = Path(item.get("source", item["path"]))
        base = Path(plan_dir) if item.get("relative_to") == "plan" else Path(project_root)
        physical = source_path if source_path.is_absolute() else base / source_path
        if physical.is_symlink():
            raise ValueError(f"material source is a symlink: {physical}")
        if not physical.is_file():
            raise ValueError(f"material not found: {physical}")
        content = physical.read_bytes()
        source = {"kind": "file", "path": str(physical)}
    label = item.get("label")
    if label is not None and (not isinstance(label, str) or not label.strip()):
        raise ValueError(f"material label must be text: {staged}")
    return {"path": str(staged), "label": label, "source": source, "content": content}


def stage(entries, directory):
    """Write staged entries under `directory`; returns the list without bytes."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    listed = []
    for item in entries:
        target = directory / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item["content"])
        listed.append({k: v for k, v in item.items() if k != "content"})
    return listed


def listing(entries):
    """The materials as a seat is told about them: label first, path second."""
    lines = []
    for item in entries:
        shown = f"materials/{item['path']}"
        lines.append(f"- {item['label']} ({shown})" if item.get("label") else f"- {shown}")
    return "\n".join(lines)
