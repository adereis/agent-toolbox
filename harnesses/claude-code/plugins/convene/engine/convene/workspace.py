"""Worktrees: portable write isolation without a jail.

A `worktree` seat gets its own detached git worktree under
`work/<seat>/repo`, checked out at the run's base commit. It can edit and
run anything there without touching the operator's checkout. Promotion
captures what it changed as `changes.patch` (tracked and untracked files
alike) and `prune` removes the worktree through git, so the operator's
repository never accumulates stale registrations.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = "repo"


def git(cwd, *args, check=True):
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                            check=False)
    if check and result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()[:300]}")
    return result.stdout


def base_commit(project_root):
    return git(project_root, "rev-parse", "HEAD").strip()


def create(project_root, work, commit):
    """A detached worktree at `work/repo`, checked out at `commit`."""
    target = Path(work) / REPO
    if target.exists():
        raise RuntimeError(f"worktree path exists: {target}")
    git(project_root, "worktree", "add", "--detach", "-q", str(target), commit)
    return target


def gitdir(worktree):
    """The worktree's private git directory inside the main repository."""
    return Path(git(worktree, "rev-parse", "--git-dir").strip()).resolve()


def common_dir(worktree):
    return Path(git(worktree, "rev-parse", "--git-common-dir").strip()).resolve()


def capture(worktree, base):
    """The seat's changes against the base commit, untracked files included.

    The diff runs from `base`, not from HEAD: a seat that commits moves
    HEAD, and a diff from there would drop everything it committed.
    `git add -N` records intent-to-add so untracked files appear in the
    diff; the index is reset afterwards so the worktree is left as the seat
    left it.
    """
    worktree = Path(worktree)
    git(worktree, "add", "-N", "--", ".")
    try:
        patch = git(worktree, "diff", "--binary", base, "--", ".")
    finally:
        git(worktree, "reset", "-q", "--", ".", check=False)
    return patch


def remove(project_root, worktree):
    """Remove the worktree through git, forcing past uncommitted changes."""
    worktree = Path(worktree)
    if worktree.exists():
        git(project_root, "worktree", "remove", "--force", str(worktree))
    git(project_root, "worktree", "prune", check=False)
