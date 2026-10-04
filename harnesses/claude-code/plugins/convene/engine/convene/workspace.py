"""Worktrees: portable write isolation without a jail.

A `worktree` seat gets a private clone of the operator's repository under
`work/<seat>/repo`, checked out detached at the run's base commit. It can
edit, build, commit and run anything there without touching the operator's
checkout. Promotion captures what it changed as `changes.patch` (committed,
tracked and untracked alike) and `prune` deletes the clone.

A clone rather than a linked `git worktree`, although the plan still calls
the workspace `worktree`. Linked worktrees share the operator's .git, so
under the jail its object store had to be bound read-only and no seat could
commit; anywhere else, `git log --all` in one seat listed every other
seat's commits, and `git worktree list` named every seat. A clone holds its
own refs and objects, and `--local` hardlinks the object files, so it costs
little on one filesystem. Its origin remote is removed, so nothing in it
points back at the operator's repository, and the operator's repository
never learns the clone exists.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = "repo"
# A seat's private home has no git identity, so `git commit` would refuse.
# Its commits never leave its clone, and only the diff reaches the board, so
# one generic identity serves every seat and names none of them.
IDENTITY = (("user.name", "convene seat"), ("user.email", "seat@convene.invalid"))


def git(cwd, *args, check=True):
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                            check=False)
    if check and result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()[:300]}")
    return result.stdout


def base_commit(project_root):
    return git(project_root, "rev-parse", "HEAD").strip()


def create(project_root, work, commit):
    """A private clone at `work/repo`, checked out detached at `commit`."""
    target = Path(work) / REPO
    if target.exists():
        raise RuntimeError(f"seat repository path exists: {target}")
    source = Path(project_root).resolve()
    git(source, "clone", "--local", "--no-checkout", "--quiet", str(source), str(target))
    git(target, "remote", "remove", "origin")
    for key, value in IDENTITY:
        git(target, "config", key, value)
    git(target, "checkout", "--quiet", "--detach", commit)
    return target


def is_linked(tree):
    """A linked worktree from a run prepared before seats got clones."""
    return (Path(tree) / ".git").is_file()


def capture(tree, base):
    """The seat's changes against the base commit, untracked files included.

    The diff runs from `base`, not from HEAD: a seat that commits moves
    HEAD, and a diff from there would drop everything it committed.
    `git add -N` records intent-to-add so untracked files appear in the
    diff; the index is reset afterwards so the tree is left as the seat
    left it.
    """
    tree = Path(tree)
    git(tree, "add", "-N", "--", ".")
    try:
        patch = git(tree, "diff", "--binary", base, "--", ".")
    finally:
        git(tree, "reset", "-q", "--", ".", check=False)
    return patch


def remove(project_root, tree):
    """Delete a seat's repository.

    A clone is deleted outright. A linked worktree left by a run prepared
    before clones is removed through git, so the operator's repository does
    not keep its registration.
    """
    tree = Path(tree)
    if is_linked(tree):
        git(project_root, "worktree", "remove", "--force", str(tree))
        git(project_root, "worktree", "prune", check=False)
    elif tree.exists():
        shutil.rmtree(tree)
