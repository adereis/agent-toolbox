"""Tier ``enforced``: a bubblewrap jail, Linux only.

Ported from quirework's blind launcher, and an allow-list all the way
down. The root is assembled from the system trees a CLI needs (`/usr`,
`/etc` and a few optional ones), bound read-only at their own paths, so the
operator's home, network shares and removable media never enter the jail
and no mount table is consulted: there is nothing to enumerate, probe or
race. The home is a tmpfs and an allow-list is bound back, because a
deny-list is one forgotten directory from a leak, and the directories that
leak are the ones nobody lists. Order is load-bearing: bwrap applies
operations in sequence, so the home is blanked before anything is bound
into it, the private harness home before the launcher and credentials that
live inside it, and the writable workspace last so no read-only bind can
shadow it.

The seat gets its own pid, ipc, uts and cgroup namespaces and bwrap's
minimal `/dev`. `/run/user/<uid>` is never bound: the session bus there is
a door out of any sandbox, because `systemd --user` starts processes on
request outside the jail. A harness that needs a bus name gets a filtered
proxy socket instead, and the receipt says so.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from convene import platform
from convene import workspace as worktrees
from convene.harnesses import base_environment
from convene.isolation import Launch

BWRAP = "bwrap"
BUS_PROXY = "xdg-dbus-proxy"
BLANKED = ("$HOME", "/tmp", "/var/tmp")
# The cap on each blanked tmpfs, so a runaway seat cannot fill the host's
# memory. The workspace and the private harness home are binds, not tmpfs,
# so real output never counts against it.
TMPFS_BYTES = 2 * 1024 ** 3
WORKSPACE_NAME = "workspace"
# What the engine staged for the seat, bound back read-only over the
# writable workspace: a seat may not rewrite its brief, its materials, the
# board it answers, or the letters a judge rules on.
READ_ONLY_IN_WORKSPACE = ("materials", "START.md", "board", "sealed")
# Host trees a CLI needs, bound read-only at their own paths. A required
# tree that is missing fails the launch by name; an optional one is bound
# when present. `/var/lib` rather than `/var`: on Silverblue `/var/mnt` and
# `/var/home` are where media and homes live, and the point of the list is
# that nothing of the operator's arrives by accident.
REQUIRED_TREES = ("/usr", "/etc")
OPTIONAL_TREES = ("/opt", "/var/lib", "/sys", "/nix", "/snap")
# Merged-usr aliases: recreated as symlinks where the host has symlinks,
# bound read-only where it still has real directories.
USR_ALIASES = ("/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32")
NAMESPACES = ("--unshare-pid", "--unshare-ipc", "--unshare-uts", "--unshare-cgroup-try")
BUS_READY_SECONDS = 15
# The record each bus directory keeps of the proxy that owns it, and how old
# a directory must be before a sweep may judge it. The grace covers the gap
# between creating the directory and starting the proxy, so a concurrent
# launch's directory is never taken for a dead one.
BUS_OWNER = "proxy.json"
BUS_SWEEP_GRACE = 4 * BUS_READY_SECONDS


def resolver_paths(resolv=Path("/etc/resolv.conf"), root=Path("/")):
    """Where the resolver file points when that is outside `/etc`.

    Fedora and Ubuntu link `/etc/resolv.conf` to systemd-resolved's stub
    under `/run`, which the allow-list does not bind. Without the target
    nothing in the jail resolves a name, and the seat cannot reach its
    provider. Only a target under `/run` is followed, where every resolver
    manager keeps its file; a link anywhere else is refused by name rather
    than bound, so a stray symlink cannot pull a private path into the
    jail. A dangling link is skipped: the host has no resolver either.
    """
    resolv = Path(resolv)
    if not resolv.is_symlink():
        return []
    target = resolv.resolve()
    if root / "etc" in target.parents or not target.exists():
        return []
    if root / "run" not in target.parents:
        raise RuntimeError(f"{resolv} points at {target}, outside /etc and /run; the jail "
                           "binds only a resolver under /run. Point it at a file under "
                           "/run or make it a regular file")
    return [target]


def system_root(root=Path("/")):
    """`(op, source, target)` triples that build the read-only allow-list root.

    Everything is bound at its own path, so `/usr/bin/git` is `/usr/bin/git`
    inside as well. `root` exists for tests that build a fake host tree.
    """
    out = []
    for tree in REQUIRED_TREES:
        path = root / tree.lstrip("/")
        if not path.is_dir():
            raise RuntimeError(f"{path} is missing; the enforced jail binds it read-only "
                               "and cannot run without it")
        out.append(("--ro-bind", str(path), str(path)))
    for tree in OPTIONAL_TREES:
        path = root / tree.lstrip("/")
        if path.is_dir() and not path.is_symlink():
            out.append(("--ro-bind", str(path), str(path)))
    for alias in USR_ALIASES:
        path = root / alias.lstrip("/")
        if path.is_symlink():
            out.append(("--symlink", os.readlink(path), str(path)))
        elif path.is_dir():
            out.append(("--ro-bind", str(path), str(path)))
    for target in resolver_paths(root / "etc/resolv.conf", root):
        out.append(("--ro-bind", str(target), str(target)))
    return out


def bound_trees(triples):
    """The host paths a set of root triples makes visible."""
    return [Path(source) for op, source, _ in triples if op != "--symlink"]


def visible(path, trees):
    """Whether `path` lies inside one of the bound host trees."""
    path = Path(path)
    return any(path == tree or tree in path.parents for tree in trees)


def offline_jail(home=None):
    """A wrapper for running a CLI with no network, for the doctor's probes.

    The same root the seats get, plus the operator's own home read-write,
    because a probe answers whether a flag still exists in this
    installation, not whether the operator's state is hidden. Its one
    enforcement is `--unshare-net`.
    """
    home = str(home or Path.home())
    argv = [BWRAP, "--die-with-parent", *NAMESPACES]
    for triple in system_root():
        argv += list(triple)
    return argv + ["--dev", "/dev", "--proc", "/proc", "--bind", home, home,
                   "--tmpfs", "/tmp", "--unshare-net"]


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


def bus_proxy_missing():
    """Why a filtered session bus cannot be built here, or None."""
    if shutil.which(BUS_PROXY) is None:
        return (f"{BUS_PROXY} not found on PATH (Fedora: dnf install xdg-dbus-proxy; Debian: "
                "apt install xdg-dbus-proxy); the jail never binds the raw session bus, "
                "so without the proxy use isolation = \"none\"")
    return None


def host_bus_address(environ=None):
    """The operator's session bus, as the proxy will dial it."""
    environ = os.environ if environ is None else environ
    address = environ.get("DBUS_SESSION_BUS_ADDRESS")
    if address:
        return address
    runtime = environ.get("XDG_RUNTIME_DIR")
    if runtime and (Path(runtime) / "bus").exists():
        return f"unix:path={runtime}/bus"
    raise RuntimeError("no session bus: DBUS_SESSION_BUS_ADDRESS is unset and "
                       "$XDG_RUNTIME_DIR/bus does not exist; run from a desktop session, "
                       "or use isolation = \"none\"")


def bus_socket_dir(environ=None):
    """A fresh private directory for the proxy's socket.

    Under the runtime directory when there is one, because socket paths are
    limited to 107 bytes and that is the shortest private place there is;
    under `~/tmp` otherwise. Directories a killed run left behind are swept
    first, so they do not collect until logout.
    """
    environ = os.environ if environ is None else environ
    runtime = environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) / "agent-toolbox" if runtime else Path.home() / "tmp"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    sweep_buses(base)
    return Path(tempfile.mkdtemp(prefix="bus.", dir=base))


def sweep_buses(base, now=None):
    """Remove bus directories whose proxy is gone; return what was removed.

    `finish` removes a directory when its seat ends, but a run killed with
    SIGKILL never reaches it. The proxy itself dies with the jail, so what
    remains is a directory and a dead socket. A directory is removed only
    when its recorded proxy no longer exists as the same process, or when it
    never recorded one and is older than the grace period. A directory
    another launch is still setting up is therefore never touched.
    """
    now = time.time() if now is None else now
    removed = []
    for directory in sorted(Path(base).glob("bus.*")):
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            age = now - directory.stat().st_mtime
            owner = json.loads((directory / BUS_OWNER).read_text())
        except FileNotFoundError:
            owner = None
        except (OSError, ValueError):
            continue
        if owner is None:
            dead = age > BUS_SWEEP_GRACE
        else:
            dead = platform.process_identity(owner["pid"]) != owner["identity"]
        if dead:
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(directory)
    return removed


class Enforced:
    name = "enforced"

    def __init__(self):
        self._buses = {}

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
        root = system_root()
        trees = bound_trees(root)
        jail = [BWRAP, "--die-with-parent", *NAMESPACES]
        for triple in root:
            jail += list(triple)
        jail += ["--dev", "/dev", "--proc", "/proc"]
        blanked = [str(home) if b == "$HOME" else b for b in BLANKED]
        for target in blanked:
            jail += ["--size", str(TMPFS_BYTES), "--tmpfs", target]
        # A project inside a bound tree (say `/opt/src/thing`) would otherwise
        # stay readable through that tree. One outside every bound tree does
        # not exist in the jail and needs nothing.
        if (not repo_ro and visible(project_root, trees)
                and not visible(project_root, [Path(b) for b in blanked])):
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
        staged = [name for name in READ_ONLY_IN_WORKSPACE if (workspace / name).exists()]
        for name in staged:
            jail += ["--ro-bind", str(workspace / name), str(virtual_workspace / name)]
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
        env = base_environment()
        env["HOME"] = str(home)
        env.update(harness.private_env(virtual_harness_home))
        env.update(harness.credential_env(real))
        bus, pass_fds = None, ()
        if harness.bus_names:
            bus = self._start_bus(harness.bus_names, seat_home)
            runtime = Path(f"/run/user/{os.getuid()}")
            jail += ["--size", str(64 * 1024 ** 2), "--tmpfs", str(runtime),
                     "--ro-bind", str(bus["socket"]), str(runtime / "bus"),
                     "--sync-fd", str(bus["fd"])]
            env["XDG_RUNTIME_DIR"] = str(runtime)
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime / 'bus'}"
            pass_fds = (bus["fd"],)
        jail += ["--chdir", str(virtual_workspace), "--setenv", "PWD", str(virtual_workspace),
                 "--unsetenv", "OLDPWD"]
        launch = Launch(jail + list(argv), env, str(workspace), {
            "tier": "enforced", "enforced": True, "backend": "bwrap",
            "backend_version": version(),
            "root_read_only": [str(t) for t in trees],
            "root_symlinks": [f"{target} -> {link}" for op, link, target in root
                              if op == "--symlink"],
            "namespaces": [flag.removeprefix("--unshare-").removesuffix("-try")
                           for flag in NAMESPACES],
            "dev": "minimal", "tmpfs_bytes": TMPFS_BYTES, "blanked": blanked,
            "read_only_binds": [t for _, t in read_only],
            "writable": [str(virtual_workspace)], "read_only_in_workspace":
            [str(virtual_workspace / n) for n in staged],
            "harness_home": str(virtual_harness_home), "harness_home_source": str(private),
            "chdir": str(virtual_workspace), "worktree_git": worktree_binds,
            "repository_read_only": str(project_root) if repo_ro else None,
            "session_bus": None if bus is None else
            {"names": list(harness.bus_names), "proxy": BUS_PROXY, "filtered": True},
            "note": "the root is an allow-list of system trees bound read-only, so the "
                    "operator's home, network shares and removable media do not exist "
                    "inside; the home is a tmpfs and only the private harness home, the "
                    "launcher, credentials and the declared workspace are bound back; "
                    "the runtime directory and its session bus are absent"
                    + ("" if bus is None else
                       " except for a proxied bus filtered to the names listed")},
            pass_fds)
        if bus is not None:
            bus["launch"] = launch
        return launch

    def _start_bus(self, names, seat_home):
        """A filtered session bus for the jail, ready before this returns.

        The proxy writes a byte to its `--fd` when it listens and exits when
        every reader of that pipe is gone. bwrap holds the read end through
        `--sync-fd`, so the proxy lives exactly as long as the jail.
        """
        reason = bus_proxy_missing()
        if reason:
            raise RuntimeError(reason)
        address = host_bus_address()
        socket_dir = bus_socket_dir()
        socket = socket_dir / "bus"
        if len(str(socket).encode()) > 107:
            shutil.rmtree(socket_dir, ignore_errors=True)
            raise RuntimeError(f"socket path {socket} exceeds 107 bytes; set XDG_RUNTIME_DIR "
                               "to a shorter directory")
        reader, writer = os.pipe()
        argv = [BUS_PROXY, f"--fd={writer}", address, str(socket), "--filter"]
        argv += [f"--talk={name}" for name in names]
        try:
            proc = subprocess.Popen(argv, pass_fds=(writer,), stdin=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
        except OSError:
            os.close(reader)
            os.close(writer)
            shutil.rmtree(socket_dir, ignore_errors=True)
            raise
        os.close(writer)
        # Written before the proxy is known to be ready, so a sweep can tell
        # this directory's owner apart from a dead one from the start.
        (socket_dir / BUS_OWNER).write_text(json.dumps(
            {"pid": proc.pid, "identity": platform.process_identity(proc.pid)}))
        ready, _, _ = select.select([reader], [], [], BUS_READY_SECONDS)
        if not ready or os.read(reader, 1) == b"":
            os.close(reader)
            proc.kill()
            error = (proc.communicate()[1] or b"").decode(errors="replace").strip()
            shutil.rmtree(socket_dir, ignore_errors=True)
            raise RuntimeError(f"{BUS_PROXY} did not come up on {socket}"
                               + (f": {error}" if error else ""))
        bus = {"process": proc, "fd": reader, "socket": socket, "dir": socket_dir,
               "launch": None}
        self._buses[str(seat_home)] = bus
        return bus

    def finish(self, harness, seat_home):
        """Reap the bus proxy and remove the mount-point stubs the binds leave.

        bwrap creates the target of a file bind inside the private home; after
        the jail exits that is a zero-byte `auth.json` that reads as a staged
        login to anyone listing the directory. Only an empty file is removed:
        a non-empty one was written by something else and is kept visible.
        """
        bus = self._buses.pop(str(seat_home), None)
        if bus is not None:
            # Idempotent: the runner released the pipe once the jail held it.
            # A launch that never happened still holds it here, and the proxy
            # waits for exactly this close.
            if bus["launch"] is not None:
                bus["launch"].release()
            else:
                os.close(bus["fd"])
            try:
                bus["process"].wait(timeout=BUS_READY_SECONDS)
            except subprocess.TimeoutExpired:
                bus["process"].kill()
                bus["process"].wait()
            bus["process"].stderr.close()
            shutil.rmtree(bus["dir"], ignore_errors=True)
        real = harness.real_home()
        private = self.home(harness, seat_home)
        for file in harness.credential_files(real):
            stub = private / file.relative_to(real)
            if stub.is_file() and not stub.is_symlink() and stub.stat().st_size == 0:
                stub.unlink()
