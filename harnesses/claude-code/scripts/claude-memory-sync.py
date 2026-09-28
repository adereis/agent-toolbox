#!/usr/bin/env python3
"""Three-way sync of Claude Code memories with a portable directory.

Claude Code keeps each project's memory under
~/.claude/projects/<encoded-path>/memory/, where the encoding depends on the
machine's home directory. This utility maps those stores to a portable layout,
<dir>/<slug>/memory/*.md, that git, rsync or Syncthing can carry between
machines, and reconciles the two in both directions.

A two-way comparison cannot tell a file deleted on one side from a file added
on the other, so this tool keeps two more records:

  base        Per machine, never shared: a copy of every file as it was when
              this machine last synced it, under
              $XDG_STATE_HOME/agent-toolbox/claude-memory/<portable-dir-key>/.
              Comparing disk and portable copies against it tells which side
              changed, so edits and deletions propagate instead of being
              undone by the next sync.
  tombstones  Shared, inside the portable directory: <slug>/memory/.deleted/
              holds one file per deleted memory, listing the SHA-256 of each
              deleted version. A machine that never synced a file can still
              recognise a stale copy of something deleted elsewhere.

MEMORY.md is an index, so when both sides changed it is merged entry by entry
(an entry is keyed by its link target) against the base. Any other file
changed on both sides is a CONFLICT: nothing is touched until `resolve`
settles it. Every overwrite or deletion is backed up first.

Linux and macOS; Python 3.9+ standard library only.
"""

import argparse
import fcntl
import hashlib
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

INDEX = "MEMORY.md"
TOMBSTONE_DIR = ".deleted"
GLOBAL = "_global"
DISCOVERY_DEPTH = 4

STATUS_HELP = """\
statuses (status) and actions (apply):
  OK              disk, portable and base agree
  NEW_LOCAL       only on disk                     -> EXPORTED
  NEW_REMOTE      only in the portable dir         -> IMPORTED
  LOCAL_EDIT      disk changed since last sync     -> EXPORTED
  REMOTE_EDIT     portable changed since last sync -> IMPORTED (disk backed up)
  DELETED_LOCAL   deleted on disk since last sync  -> TOMBSTONED (removed from
                                                      portable, tombstone written)
  DELETED_REMOTE  deleted from portable            -> REMOVED (disk backed up)
  STALE_LOCAL     on disk, tombstoned elsewhere    -> REMOVED (disk backed up)
  MERGE           MEMORY.md changed on both sides  -> MERGED
  CONFLICT        cannot be decided; left untouched until `resolve`
  ALIASED         the project has several memory dirs; run `link-aliases`

exit status: 0 nothing pending, 1 error, 2 pending changes (status) or
unresolved conflicts / aliased projects left (apply)."""


class SyncError(Exception):
    """A failure the user must act on; the message names the fix."""


# --- Small helpers ----------------------------------------------------------

def encode(path):
    """Encode a path the way Claude Code names its project dirs.

    Every character that is not an ASCII letter or digit becomes '-', so
    /home/a/my_app.v2 -> -home-a-my-app-v2. Replacing only '/' misses projects
    whose path contains '.', '_' or spaces.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def sha(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def write_atomic(path, data, mode=0o644):
    """Replace path with data without ever exposing a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_bytes(data)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def file_mode(path, default=0o644):
    try:
        return path.stat().st_mode & 0o777
    except FileNotFoundError:
        return default


def prefix_match(slug, prefix):
    """True when slug is prefix or nested beneath it; a trailing / is optional."""
    prefix = prefix.rstrip("/")
    return slug == prefix or slug.startswith(prefix + "/")


# --- MEMORY.md index merge --------------------------------------------------

def index_key(line):
    m = re.search(r"\]\(([^)]*)\)", line)
    return "link:" + m.group(1) if m else "text:" + line.strip()


def index_entries(text):
    entries, order = {}, []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        key = index_key(line)
        if key not in entries:
            entries[key] = line
            order.append(key)
    return entries, order


def merge_index(base, local, remote):
    """Three-way merge of MEMORY.md; returns (text, conflicting keys).

    Local order and blank lines are kept; entries only the remote added are
    appended. An entry removed on one side and untouched on the other stays
    removed, which is what a union cannot do. An entry changed on both sides,
    or changed on one and removed on the other, is a conflict.
    """
    b, _ = index_entries(base)
    l_ent, _ = index_entries(local)
    r_ent, r_order = index_entries(remote)
    out, conflicts, seen = [], [], set()
    for line in (local or "").splitlines():
        if not line.strip():
            out.append(line)
            continue
        key = index_key(line)
        if key in seen:
            out.append(line)
            continue
        seen.add(key)
        lv, bv, rv = l_ent[key], b.get(key), r_ent.get(key)
        if key in r_ent:
            if rv == lv or (bv is not None and rv == bv):
                out.append(lv)
            elif bv is not None and lv == bv:
                out.append(rv)
            else:
                out.append(lv)
                conflicts.append(key)
        elif bv is None:
            out.append(lv)                  # added locally
        elif lv != bv:
            out.append(lv)                  # edited here, removed remotely
            conflicts.append(key)
        # else: removed remotely, untouched here -> stays removed
    for key in r_order:
        if key in l_ent:
            continue
        rv, bv = r_ent[key], b.get(key)
        if bv is None:
            out.append(rv)                  # added remotely
        elif rv != bv:
            conflicts.append(key)           # removed here, edited remotely
        # else: removed here, untouched remotely -> stays removed
    text = "\n".join(out)
    return (text + "\n" if out else ""), conflicts


# --- Configuration and layout -----------------------------------------------

class Sync:
    def __init__(self, args):
        home = Path.home()
        # absolute() but not resolve(): the encoding follows the path a session
        # is launched from, which keeps any symlinks in it.
        self.claude_dir = Path(args.claude_dir).expanduser().absolute()
        self.projects_dir = Path(args.projects_dir).expanduser().absolute()
        self.portable = Path(args.dir).expanduser().absolute()
        self.allows = args.allow or []
        self.skips = args.skip or []
        self.home = home
        if not self.portable.is_dir():
            raise SyncError(
                f"portable directory not found: {self.portable}\n"
                f"Create it to start a new store (mkdir -p {self.portable}), "
                "or pass the right one with --dir.")
        state_root = Path(args.state_dir).expanduser()
        key = hashlib.sha256(str(self.portable.resolve()).encode()).hexdigest()[:16]
        self.store = state_root / key
        self.base_root = self.store / "base"
        self.backup_root = (Path(args.backup_dir).expanduser() if args.backup_dir
                            else self.store / "backups")
        self.stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._lock = None

    # Locking: one mutating run per portable directory at a time.
    def lock(self):
        self.store.mkdir(parents=True, exist_ok=True)
        (self.store / "portable-dir").write_text(str(self.portable.resolve()) + "\n")
        self._lock = open(self.store / "lock", "w")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncError(f"another claude-memory-sync is running on {self.portable} "
                            f"(lock {self.store / 'lock'}); retry when it finishes.")

    def included(self, slug):
        if slug == GLOBAL:
            return True
        if self.allows and not any(prefix_match(slug, p) for p in self.allows):
            return False
        return not any(prefix_match(slug, p) for p in self.skips)

    # Disk side ---------------------------------------------------------------
    def candidate_dirs(self, slug):
        """Every ~/.claude/projects/<encoded> dir a session could write for slug."""
        projects = self.claude_dir / "projects"
        if slug == GLOBAL:
            return [projects / encode(self.home)]
        conv = self.projects_dir / slug
        dirs = [projects / encode(conv)]
        real = os.path.realpath(conv)
        if real != str(conv):
            dirs.append(projects / encode(real))
        return dirs

    def memory_dirs(self, slug):
        """Existing memory dirs for slug, deduplicated by real path."""
        found, reals = [], set()
        for cand in self.candidate_dirs(slug):
            mem = cand / "memory"
            if mem.is_dir():
                real = os.path.realpath(mem)
                if real not in reals:
                    reals.add(real)
                    found.append(mem)
        return found

    def disk_dir(self, slug):
        found = self.memory_dirs(slug)
        return found[0] if found else self.candidate_dirs(slug)[0] / "memory"

    def discover_projects(self):
        """Slugs of git repos under projects_dir, following symlinked repos."""
        slugs, visited = [], set()
        root = self.projects_dir
        if not root.is_dir():
            return slugs
        for dirpath, dirnames, _ in os.walk(root, followlinks=True):
            real = os.path.realpath(dirpath)
            if real in visited:
                dirnames[:] = []
                continue
            visited.add(real)
            rel = Path(dirpath).relative_to(root)
            depth = len(rel.parts)
            if depth and (Path(dirpath) / ".git").is_dir():
                slugs.append(rel.as_posix())
            if depth >= DISCOVERY_DEPTH - 1:
                dirnames[:] = []
            else:
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        return slugs

    # Portable and base sides -------------------------------------------------
    @staticmethod
    def stored_slugs(root):
        slugs = []
        if not root.is_dir():
            return slugs
        for dirpath, dirnames, _ in os.walk(root):
            rel = Path(dirpath).relative_to(root)
            if rel.parts and rel.parts[-1] == "memory" and len(rel.parts) > 1:
                slugs.append(Path(*rel.parts[:-1]).as_posix())
                dirnames[:] = []
            elif len(rel.parts) > DISCOVERY_DEPTH:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        return slugs

    def portable_dir(self, slug):
        return self.portable / slug / "memory"

    def base_dir(self, slug):
        return self.base_root / slug / "memory"

    def tombstones(self, slug, name):
        path = self.portable_dir(slug) / TOMBSTONE_DIR / name
        try:
            return {ln.split("\t")[0] for ln in path.read_text().splitlines() if ln.strip()}
        except FileNotFoundError:
            return set()

    def slugs(self):
        found = {GLOBAL}
        for slug in self.discover_projects():
            if self.memory_dirs(slug):
                found.add(slug)
        found.update(self.stored_slugs(self.portable))
        found.update(self.stored_slugs(self.base_root))
        return sorted(s for s in found if self.included(s))

    @staticmethod
    def names(directory, tombstones=False):
        names = set()
        if directory.is_dir():
            names = {p.name for p in directory.glob("*.md") if p.is_file()}
            if tombstones:
                tdir = directory / TOMBSTONE_DIR
                if tdir.is_dir():
                    names |= {p.name for p in tdir.iterdir() if p.is_file()}
        return names

    # Classification ------------------------------------------------------------
    def entries(self):
        """Yield (slug, name, status, detail) for every tracked memory file."""
        for slug in self.slugs():
            if len(self.memory_dirs(slug)) > 1:
                yield slug, None, "ALIASED", " ".join(str(d) for d in self.memory_dirs(slug))
                continue
            ddir, pdir, bdir = self.disk_dir(slug), self.portable_dir(slug), self.base_dir(slug)
            for name in sorted(self.names(ddir) | self.names(pdir, True) | self.names(bdir)):
                status, detail = self.classify(slug, name, ddir / name, bdir / name, pdir / name)
                yield slug, name, status, detail

    def classify(self, slug, name, dpath, bpath, ppath):
        d, b, p = sha(dpath), sha(bpath), sha(ppath)
        if d is None and p is None:
            return ("GONE", "") if b is not None else ("OK", "")
        if d == p:
            return "OK", ""
        if b is None:
            if p is None:
                tomb = self.tombstones(slug, name)
                if d in tomb:
                    return "STALE_LOCAL", ""
                if tomb and not self.acknowledged(slug, name):
                    return "CONFLICT", "deleted elsewhere, differs here"
                return "NEW_LOCAL", ""
            if d is None:
                return "NEW_REMOTE", ""
            return self.both_changed(name, None, dpath, ppath, "differs, never synced here")
        if d is None:
            return ("DELETED_LOCAL", "") if p == b else ("CONFLICT", "deleted here, edited elsewhere")
        if p is None:
            return ("DELETED_REMOTE", "") if d == b else ("CONFLICT", "edited here, deleted elsewhere")
        if p == b:
            return "LOCAL_EDIT", ""
        if d == b:
            return "REMOTE_EDIT", ""
        return self.both_changed(name, bpath, dpath, ppath, "edited on both sides")

    @staticmethod
    def both_changed(name, bpath, dpath, ppath, reason):
        if name != INDEX:
            return "CONFLICT", reason
        base = bpath.read_text() if bpath is not None else ""
        _, conflicts = merge_index(base, dpath.read_text(), ppath.read_text())
        if conflicts:
            return "CONFLICT", "MEMORY.md entries: " + ", ".join(k.split(":", 1)[1] for k in conflicts)
        return "MERGE", ""

    # Mutations -------------------------------------------------------------------
    def backup(self, side, slug, path):
        if path.exists():
            dest = self.backup_root / self.stamp / side / slug / "memory" / path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)

    def copy(self, src, dst):
        write_atomic(dst, src.read_bytes(), file_mode(src))

    # A deletion this machine carried out, in either direction, is recorded in
    # the base. A later file of that name on this disk was then created here on
    # purpose, not left over, so it exports instead of conflicting with the
    # tombstone. Content this machine never saw still conflicts.
    def ack_path(self, slug, name):
        return self.base_dir(slug) / TOMBSTONE_DIR / name

    def acknowledged(self, slug, name):
        return self.ack_path(slug, name).exists()

    def set_base(self, slug, name, src):
        self.copy(src, self.base_dir(slug) / name)
        self.ack_path(slug, name).unlink(missing_ok=True)

    def drop_base(self, slug, name, deleted=False):
        (self.base_dir(slug) / name).unlink(missing_ok=True)
        if deleted:
            self.ack_path(slug, name).parent.mkdir(parents=True, exist_ok=True)
            self.ack_path(slug, name).touch()

    def clear_tombstone(self, slug, name):
        (self.portable_dir(slug) / TOMBSTONE_DIR / name).unlink(missing_ok=True)

    def add_tombstone(self, slug, name, digest):
        if digest in self.tombstones(slug, name):
            return
        path = self.portable_dir(slug) / TOMBSTONE_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(f"{digest}\t{datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")

    def export(self, slug, name):
        src, dst = self.disk_dir(slug) / name, self.portable_dir(slug) / name
        self.backup("portable", slug, dst)
        self.copy(src, dst)
        self.clear_tombstone(slug, name)
        self.set_base(slug, name, src)

    def import_(self, slug, name):
        src, dst = self.portable_dir(slug) / name, self.disk_dir(slug) / name
        self.backup("disk", slug, dst)
        self.copy(src, dst)
        self.set_base(slug, name, src)

    def delete_remote(self, slug, name):
        ppath = self.portable_dir(slug) / name
        self.backup("portable", slug, ppath)
        self.add_tombstone(slug, name, sha(ppath))
        ppath.unlink()
        self.drop_base(slug, name, deleted=True)

    def delete_local(self, slug, name):
        dpath = self.disk_dir(slug) / name
        self.backup("disk", slug, dpath)
        dpath.unlink()
        self.drop_base(slug, name, deleted=True)

    def merge(self, slug, name):
        dpath, ppath, bpath = (self.disk_dir(slug) / name, self.portable_dir(slug) / name,
                               self.base_dir(slug) / name)
        base = bpath.read_text() if bpath.exists() else ""
        text, conflicts = merge_index(base, dpath.read_text(), ppath.read_text())
        if conflicts:
            raise SyncError(f"{slug}/memory/{name} changed while merging; rerun apply")
        self.backup("disk", slug, dpath)
        self.backup("portable", slug, ppath)
        data = text.encode()
        write_atomic(dpath, data, file_mode(dpath))
        write_atomic(ppath, data, file_mode(ppath))
        self.clear_tombstone(slug, name)
        self.set_base(slug, name, dpath)

    def apply_entry(self, slug, name, status):
        """Carry out status; return the action word to report, or None."""
        dpath = self.disk_dir(slug) / name
        if status == "OK":
            if dpath.exists():
                if sha(self.base_dir(slug) / name) != sha(dpath):
                    self.set_base(slug, name, dpath)
                # The file is live on both sides, so a tombstone for it is
                # left over from before it was re-created.
                self.clear_tombstone(slug, name)
            return None
        if status == "GONE":
            self.drop_base(slug, name)
            return None
        if status in ("NEW_LOCAL", "LOCAL_EDIT"):
            self.export(slug, name)
            return "EXPORTED"
        if status in ("NEW_REMOTE", "REMOTE_EDIT"):
            self.import_(slug, name)
            return "IMPORTED"
        if status == "DELETED_LOCAL":
            self.delete_remote(slug, name)
            return "TOMBSTONED"
        if status in ("DELETED_REMOTE", "STALE_LOCAL"):
            self.delete_local(slug, name)
            return "REMOVED"
        if status == "MERGE":
            self.merge(slug, name)
            return "MERGED"
        raise AssertionError(status)


def label(slug, name):
    return f"{slug}/memory/{name}" if name else slug


def split_label(text):
    slug, sep, name = text.rpartition("/memory/")
    if not sep or not slug or not name or "/" in name:
        raise SyncError(f"expected <slug>/memory/<file>, got: {text}")
    return slug, name


# --- Commands ---------------------------------------------------------------

def cmd_status(sync, args):
    pending = False
    for slug, name, status, detail in sync.entries():
        if status == "GONE":
            continue
        if status != "OK":
            pending = True
        if status != "OK" or args.verbose:
            print("\t".join(filter(None, [status, label(slug, name), detail])))
    return 2 if pending else 0


def cmd_apply(sync, args):
    sync.lock()
    blocked = False
    for slug, name, status, detail in list(sync.entries()):
        if status in ("CONFLICT", "ALIASED"):
            blocked = True
            print("\t".join(filter(None, [status, label(slug, name), detail])))
            continue
        action = sync.apply_entry(slug, name, status)
        if action:
            print(f"{action}\t{label(slug, name)}")
    return 2 if blocked else 0


def cmd_resolve(sync, args):
    sync.lock()
    for text in args.paths:
        slug, name = split_label(text)
        dpath, ppath = sync.disk_dir(slug) / name, sync.portable_dir(slug) / name
        if args.keep == "local":
            if dpath.exists():
                sync.export(slug, name)
                print(f"EXPORTED\t{text}")
            elif ppath.exists():
                sync.delete_remote(slug, name)
                print(f"TOMBSTONED\t{text}")
            else:
                sync.drop_base(slug, name)
        else:
            if ppath.exists():
                sync.import_(slug, name)
                print(f"IMPORTED\t{text}")
            elif dpath.exists():
                sync.delete_local(slug, name)
                print(f"REMOVED\t{text}")
            else:
                sync.drop_base(slug, name)
    return 0


def cmd_adopt(sync, args):
    """Seed the base from a record of what an earlier tool last synced."""
    sync.lock()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            text, digest = raw.split("\t")
        except ValueError:
            raise SyncError(f"adopt expects '<slug>/memory/<file><TAB><sha256>', got: {raw}")
        slug, name = split_label(text)
        if (sync.base_dir(slug) / name).exists():
            print(f"SKIP\t{text}")
            continue
        for src in (sync.portable_dir(slug) / name, sync.disk_dir(slug) / name):
            if sha(src) == digest:
                sync.set_base(slug, name, src)
                print(f"ADOPTED\t{text}")
                break
        else:
            print(f"UNADOPTED\t{text}\tno copy with that checksum")
    return 0


def cmd_link_aliases(sync, args):
    """Fold a project's duplicate memory dirs into one and symlink the rest."""
    sync.lock()
    failed = False
    for slug in sync.slugs():
        dirs = sync.memory_dirs(slug)
        if len(dirs) < 2:
            continue
        keep, others = dirs[0], dirs[1:]
        merged, clash = {}, []
        for d in dirs:
            for name in sync.names(d):
                data = (d / name).read_bytes()
                if name not in merged or merged[name] == data:
                    merged[name] = data
                elif name == INDEX:
                    text, conflicts = merge_index("", merged[name].decode(), data.decode())
                    if conflicts:
                        clash.append(name)
                    merged[name] = text.encode()
                else:
                    clash.append(name)
        if clash:
            failed = True
            print(f"CONFLICT\t{slug}\tdiffering files: {', '.join(sorted(set(clash)))}")
            continue
        for name, data in merged.items():
            if sha(keep / name) != hashlib.sha256(data).hexdigest():
                sync.backup("disk", slug, keep / name)
                write_atomic(keep / name, data)
        for d in others:
            for name in sync.names(d):
                sync.backup("disk-alias", slug, d / name)
            shutil.rmtree(d)
            d.symlink_to(keep, target_is_directory=True)
            print(f"LINKED\t{d}\t{keep}")
    return 2 if failed else 0


def build_parser():
    state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", default=os.environ.get("CLAUDE_MEMORY_DIR", "~/.claude/memory-sync"),
                        help="portable directory (default: $CLAUDE_MEMORY_DIR or ~/.claude/memory-sync)")
    common.add_argument("--projects-dir", default=os.environ.get("CLAUDE_PROJECTS_DIR", "~/projects"),
                        help="where project checkouts live (default: $CLAUDE_PROJECTS_DIR or ~/projects)")
    common.add_argument("--claude-dir", default=os.environ.get("CLAUDE_DIR", "~/.claude"),
                        help="Claude Code data directory (default: $CLAUDE_DIR or ~/.claude)")
    common.add_argument("--state-dir", default=str(state_home / "agent-toolbox/claude-memory"),
                        help="per-machine base store (default: $XDG_STATE_HOME/agent-toolbox/claude-memory)")
    common.add_argument("--backup-dir", help="where overwritten and deleted files are copied first "
                        "(default: <state-dir>/<key>/backups)")
    common.add_argument("--allow", action="append", metavar="PREFIX",
                        help="only sync slugs equal to or nested under PREFIX (repeatable)")
    common.add_argument("--skip", action="append", metavar="PREFIX",
                        help="never sync slugs equal to or nested under PREFIX (repeatable); "
                             f"{GLOBAL} is always synced")

    parser = argparse.ArgumentParser(
        prog="claude-memory-sync", description=__doc__.split("\n\n")[0],
        epilog=STATUS_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("status", parents=[common], help="show what apply would do (read-only)",
                       epilog=STATUS_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true", help="also list files that are OK")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("apply", parents=[common], help="carry out every non-conflicting action",
                       epilog=STATUS_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("resolve", parents=[common], help="settle CONFLICT files by keeping one side")
    p.add_argument("--keep", choices=("local", "remote"), required=True,
                   help="local: disk wins (a deleted disk file deletes the portable copy); "
                        "remote: the portable copy wins")
    p.add_argument("paths", nargs="+", metavar="SLUG/memory/FILE")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("adopt", parents=[common],
                       help="seed the base from '<slug>/memory/<file>\\t<sha256>' lines on stdin",
                       description="Record what an earlier sync tool last synced, so the first run "
                                   "of this one recognises local deletions instead of re-importing "
                                   "them. A line is adopted when the portable or disk copy has that "
                                   "checksum; an existing base entry is never replaced.")
    p.set_defaults(func=cmd_adopt)

    p = sub.add_parser("link-aliases", parents=[common],
                       help="merge a project's duplicate memory dirs and symlink the extras",
                       description="A project reached through a symlink gets one memory dir per "
                                   "launch path. This merges them into the conventional one and "
                                   "replaces the others with symlinks to it. Differing files other "
                                   "than MEMORY.md are refused, not guessed at.")
    p.set_defaults(func=cmd_link_aliases)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(Sync(args), args)
    except SyncError as err:
        print(f"claude-memory-sync: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
