"""Tier ``enforced``: a bubblewrap jail, Linux only.

Ported from quirework's blind launcher. The home is blanked wholesale and an
allow-list is bound back, because a deny-list is one forgotten directory
from a leak, and the directories that leak are the ones nobody lists.
Order is load-bearing: bwrap applies operations in sequence, so the home is
blanked before anything is bound into it, the private harness home before
the launcher and credentials that live inside it, and the writable
workspace last so no read-only bind can shadow it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from convene import workspace as worktrees
from convene.harnesses import base_environment
from convene.isolation import Launch

BWRAP = "bwrap"
BLANKED = ("$HOME", "/tmp", "/var/tmp")
WORKSPACE_NAME = "workspace"
MOUNTS = "/proc/self/mounts"
# Filesystems that never enter a jail. Two reasons, either sufficient: a
# network share is the operator's personal or shared data, which a seat
# has no business reaching; and bwrap applies mount flags recursively to
# every submount of a bind, so a stale or slow share under `/` makes the
# whole root bind fail with "Unable to apply mount flags".
EXCLUDED_FSTYPES = {"autofs", "cifs", "smb3", "nfs", "nfs4", "afs", "9p", "fuse.sshfs",
                    "fuse.rclone", "fuse.gvfsd-fuse", "davfs", "ceph", "glusterfs"}


def excluded_mounts(path=MOUNTS):
    """Mount points of network and automount filesystems, deepest last."""
    found = []
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return found
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        target, fstype = parts[1].replace("\\040", " "), parts[2]
        if fstype in EXCLUDED_FSTYPES or fstype.startswith("fuse."):
            found.append(Path(target))
    return sorted(set(found), key=lambda p: (len(p.parts), str(p)))


def root_binds(excluded, root=Path("/"), skip=()):
    """Binds that reassemble `/` without the excluded mount points.

    `--bind / /` is one line when nothing under `/` is excluded. With an
    exclusion, the directories on the path to it are bound entry by entry
    and the excluded mount itself is left out, so the jail's root simply
    has no such directory. Symlinks at any level are recreated as symlinks
    (Fedora's `/bin` -> `usr/bin`), never bound through. Sockets and other
    special files are bound as they are: the session bus socket under
    `/run/user/<uid>/` is how Antigravity reaches the keyring that holds
    its token, and `--bind / /` always exposed it.
    """
    out = []
    excluded = [e for e in excluded if e != root]
    inside = [e for e in excluded if root in e.parents]
    if not inside:
        return [("--bind", str(root), str(root))]
    for child in sorted(root.iterdir()):
        if child in skip or child in excluded:
            continue
        if child.is_symlink():
            out.append(("--symlink", os.readlink(child), str(child)))
        elif child.is_dir():
            out += root_binds(excluded, child, skip)
        elif child.is_file():
            out.append(("--ro-bind", str(child), str(child)))
        elif child.exists():
            out.append(("--bind", str(child), str(child)))
    return out


def root_tmpfs(excluded, root=Path("/"), skip=()):
    """Binds that reassemble `/` by binding it whole and blanking what is out.

    The cheap counterpart to `root_binds`. One `--bind / /` carries the
    whole filesystem and each excluded mount is covered by an empty tmpfs,
    so a seat sees a directory with nothing in it where the NAS would be.
    That is the same containment `root_binds` achieves by leaving the entry
    out, in a handful of arguments instead of one per entry along the way.

    It is not always available: binding `/` applies mount flags recursively,
    and a stale or slow automount underneath makes the whole bind fail. Ask
    `probe_root_bind` first and fall back to `root_binds` when it says no.
    """
    out = [("--bind", str(root), str(root))]
    for mount in excluded:
        if mount == root:
            continue
        if any(s == mount or s in mount.parents for s in skip):
            # Replaced wholesale later anyway, as `/proc` is by `--proc`.
            continue
        out.append(("--tmpfs", str(mount)))
    return out


def probe_root_bind(excluded, skip=(), timeout=30):
    """Whether this machine can bind `/` whole right now.

    Run before every jail rather than cached, because the answer follows the
    network: an automount that resolves at home fails on another network,
    and a run prepared in one place may be played in another.
    """
    if shutil.which(BWRAP) is None:
        return False
    argv = [BWRAP, "--die-with-parent"]
    for item in root_tmpfs(excluded, skip=skip):
        argv += list(item)
    argv += ["--dev-bind", "/dev", "/dev", "--proc", "/proc", "/bin/true"]
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def launcher_paths(link, hops=10):
    """Every directory needed to follow a launcher's symlink chain.

    One hop at a time rather than `resolve()`, collecting each element's
    parent, so an intermediate link like codex's `current` still has
    somewhere to point inside the jail.
    """
    out, seen, current = [], set(), Path(link)
    for _ in range(hops):
        if current in seen:
            break
        seen.add(current)
        out.append(current.parent)
        if not current.is_symlink():
            break
        current = Path(os.path.normpath(os.path.join(current.parent, os.readlink(current))))
    out.append(current if current.is_dir() else current.parent)
    return list(dict.fromkeys(out))


def version():
    try:
        result = subprocess.run([BWRAP, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


class Enforced:
    name = "enforced"

    def available(self):
        if not sys.platform.startswith("linux"):
            return (f"bubblewrap confinement is Linux-only (this is {sys.platform}); "
                    "use isolation = \"private-home\"")
        if shutil.which(BWRAP) is None:
            return ("bwrap not found on PATH (Fedora: dnf install bubblewrap; Debian: "
                    "apt install bubblewrap); or use isolation = \"private-home\"")
        return None

    def home(self, harness, seat_home):
        return Path(seat_home) / harness.name

    def wrap(self, argv, *, harness, seat_home, workspace, project_root, repo_ro):
        reason = self.available()
        if reason:
            raise RuntimeError(reason)
        launcher = shutil.which(harness.name)
        if launcher is None:
            raise RuntimeError(f"{harness.name} is not on PATH")
        home = Path.home()
        private = self.home(harness, seat_home)
        private.mkdir(parents=True, exist_ok=True)
        harness.prepare_home(private)
        virtual_harness_home = home / harness.home_name
        virtual_workspace = home / WORKSPACE_NAME
        workspace, project_root = Path(workspace), Path(project_root)
        excluded = excluded_mounts()
        skip = (Path("/dev"), Path("/proc"))
        # Probed here, not at prepare: the cheap jail depends on what is
        # mounted at this moment, and the receipt must name what this launch
        # actually used rather than what an earlier probe predicted.
        whole_root = probe_root_bind(excluded, skip=skip)
        root_strategy = "root-bind" if whole_root else "enumerated"
        jail = [BWRAP, "--die-with-parent"]
        for triple in (root_tmpfs(excluded, skip=skip) if whole_root
                       else root_binds(excluded, skip=skip)):
            jail += list(triple)
        jail += ["--dev-bind", "/dev", "/dev", "--proc", "/proc"]
        blanked = [str(home) if b == "$HOME" else b for b in BLANKED]
        for target in blanked:
            jail += ["--tmpfs", target]
        # A project outside the blanked set would otherwise stay reachable
        # through the root bind.
        if not repo_ro and not any(project_root == Path(b) or Path(b) in project_root.parents
                                   for b in blanked):
            jail += ["--tmpfs", str(project_root)]
            blanked.append(str(project_root))
        jail += ["--bind", str(private), str(virtual_harness_home)]
        read_only = []
        for path in launcher_paths(Path(launcher)):
            read_only.append((str(path), str(path)))
        real = harness.real_home()
        for file in harness.credential_files(real):
            if file.exists():
                read_only.append((str(file), str(virtual_harness_home / file.relative_to(real))))
        if repo_ro:
            read_only.append((str(project_root), str(project_root)))
        for source, target in read_only:
            jail += ["--ro-bind", source, target]
        jail += ["--bind", str(workspace), str(virtual_workspace)]
        for name in ("materials", "START.md", "board"):
            item = workspace / name
            if item.exists():
                jail += ["--ro-bind", str(item), str(virtual_workspace / name)]
        # A worktree's `.git` file names the main repository's git directory
        # by absolute path, and git writes this worktree's index there. The
        # common directory is bound read-only at its real path and only the
        # worktree's own entry inside it is writable.
        tree = workspace / worktrees.REPO
        worktree_binds = []
        if tree.is_dir():
            common = worktrees.common_dir(tree)
            own = worktrees.gitdir(tree)
            jail += ["--ro-bind", str(common), str(common), "--bind", str(own), str(own)]
            worktree_binds = [str(common), str(own)]
        jail += ["--chdir", str(virtual_workspace), "--setenv", "PWD", str(virtual_workspace),
                 "--unsetenv", "OLDPWD"]
        env = base_environment()
        env["HOME"] = str(home)
        env.update(harness.private_env(virtual_harness_home))
        env.update(harness.credential_env(real))
        return Launch(jail + list(argv), env, str(workspace), {
            "tier": "enforced", "enforced": True, "backend": "bwrap",
            "backend_version": version(), "blanked": blanked,
            "read_only_binds": [t for _, t in read_only],
            "excluded_mounts": [str(e) for e in excluded],
            "root_strategy": root_strategy,
            "root_strategy_note":
                "bound / whole and covered every excluded mount with an empty tmpfs"
                if whole_root else
                "bound / entry by entry, leaving every excluded mount out, because "
                "binding / whole failed here",
            "writable": [str(virtual_workspace)], "read_only_in_workspace":
            [str(virtual_workspace / n) for n in ("materials", "START.md", "board")],
            "harness_home": str(virtual_harness_home), "harness_home_source": str(private),
            "chdir": str(virtual_workspace), "worktree_git": worktree_binds,
            "repository_read_only": str(project_root) if repo_ro else None,
            "note": "the home is a tmpfs; only the private harness home, the launcher, "
                    "credentials and the declared workspace are bound back"})

    def finish(self, harness, seat_home):
        """Remove the empty mount-point stubs the credential binds leave behind.

        bwrap creates the target of a file bind inside the private home; after
        the jail exits that is a zero-byte `auth.json` that reads as a staged
        login to anyone listing the directory. Only an empty file is removed:
        a non-empty one was written by something else and is kept visible.
        """
        real = harness.real_home()
        private = self.home(harness, seat_home)
        for file in harness.credential_files(real):
            stub = private / file.relative_to(real)
            if stub.is_file() and not stub.is_symlink() and stub.stat().st_size == 0:
                stub.unlink()
