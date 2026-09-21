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

from convene.harnesses import base_environment
from convene.isolation import Launch

BWRAP = "bwrap"
BLANKED = ("$HOME", "/tmp", "/var/tmp")
WORKSPACE_NAME = "workspace"


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
        jail = [BWRAP, "--die-with-parent", "--bind", "/", "/", "--dev-bind", "/dev", "/dev",
                "--proc", "/proc"]
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
            "writable": [str(virtual_workspace)], "read_only_in_workspace":
            [str(virtual_workspace / n) for n in ("materials", "START.md", "board")],
            "harness_home": str(virtual_harness_home), "harness_home_source": str(private),
            "chdir": str(virtual_workspace),
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
