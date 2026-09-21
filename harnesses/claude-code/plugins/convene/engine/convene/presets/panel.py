"""Panel: a multi-seat review of a commit range.

The range becomes two staged materials, the net diff and the commit log,
so a seat with no shell can still read the change, and a seat standing in
the read-only repository can check any citation against the tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(project_root, *args):
    result = subprocess.run(["git", "-C", str(project_root), *args], capture_output=True,
                            text=True, check=False)
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()[:300]}")
    return result.stdout


def resolve_range(project_root, spec):
    """Validate the delta and return it with the commits it covers."""
    if spec in ("", None):
        raise ValueError("a panel needs a delta: pass --range A..B, or --range HEAD "
                         "for the uncommitted working tree")
    if spec == "HEAD":
        if not git(project_root, "status", "--porcelain").strip():
            raise ValueError("--range HEAD means the uncommitted working tree, and it is clean")
        return {"spec": "HEAD", "kind": "worktree", "commits": []}
    if ".." not in spec:
        raise ValueError(f"not a git range: {spec!r} (expected A..B, or HEAD)")
    commits = [line for line in git(project_root, "log", "--format=%H %s", spec).splitlines()
               if line.strip()]
    if not commits:
        raise ValueError(f"{spec!r} covers no commits; there is nothing to review")
    base, _, tip = spec.partition("..")
    return {"spec": spec, "kind": "range", "commits": commits,
            "base": git(project_root, "rev-parse", base).strip(),
            "tip": git(project_root, "rev-parse", tip or "HEAD").strip()}


def materials(project_root, delta):
    """`diff.patch` and `log.txt` for the delta, as inline material entries."""
    if delta["kind"] == "worktree":
        diff = git(project_root, "diff", "HEAD")
        untracked = git(project_root, "ls-files", "--others", "--exclude-standard")
        log = "Uncommitted working tree against HEAD.\n\n" + git(
            project_root, "status", "--porcelain")
        if untracked.strip():
            log += "\nUntracked files (not in the diff):\n" + untracked
    else:
        diff = git(project_root, "diff", delta["base"], delta["tip"])
        log = git(project_root, "log", "--stat", "--format=commit %H%nAuthor: %an%nDate:   %ad%n%n%B",
                  delta["spec"])
    return [
        {"path": "diff.patch", "text": diff,
         "label": "the change under review (net diff)"},
        {"path": "log.txt", "text": log,
         "label": "the commits and their messages" if delta["kind"] == "range"
         else "the working-tree status"},
    ]


def brief_prelude(delta, project_root):
    if delta["kind"] == "worktree":
        return (f"The change under review is the uncommitted working tree of the repository at "
                f"{project_root}. Its net diff against HEAD is materials/diff.patch.\n")
    count = len(delta["commits"])
    return (f"The change under review is `{delta['spec']}` in the repository at {project_root}: "
            f"{count} commit{'s' if count != 1 else ''}. The net diff is materials/diff.patch "
            f"and the commits with their messages are materials/log.txt.\n")


# Seats a panel gets when the operator names none. Two harnesses when both
# are installed, because independence from the operator's own model is the
# point of convening a panel.
DEFAULT_SEATS = (
    {"id": "skeptic", "persona": "quinn-t-shun"},
    {"id": "maintainer", "persona": "connie-tinuity"},
    {"id": "security", "persona": "sec-urity"},
)
