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

Several projects can share one memory dir, each project's memory dir being a
symlink to the dir of the project that owns it. The shared dir is synced once,
under its owner's slug, and each link is recorded as <slug>/memory.link naming
the owner, so that other machines recreate the links instead of keeping
separate copies that drift apart.

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
LINK_FILE = "memory.link"
GLOBAL = "_global"
DISCOVERY_DEPTH = 4
BLOCKING = ("CONFLICT", "ALIASED", "MISSING", "LINK_CONFLICT")

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
  MISSING         the project's memory dir is gone but files synced from it
                  remain; usually a wrong --claude-dir or --projects-dir.
                  Otherwise `resolve` its files: --keep remote restores
                  (naming every remaining file), --keep local deletes

shared memory dirs (one line per project, not per file):
  NEW_LINK        the memory dir here is a link to another -> RECORDED (link written to the
                  project's, not yet recorded                 portable dir; this project's own
                                                              copies retired, and any the shared
                                                              dir lacks tombstoned in its store)
  REMOTE_LINK     the portable dir records a link that is  -> LINKED (an existing memory dir is
                  missing here                                folded into the shared one first)
  LINK_CONFLICT   the link here and the recorded one disagree, the link points at no
                  project's memory dir, or folding would clash; left untouched

exit status: 0 nothing pending, 1 error, 2 pending changes (status) or
unresolved conflicts / aliased, missing or link-conflicted projects left (apply).

Deletions and merges reach every machine, so run apply under an agent
following prompts/sync-memories.md in Agent Toolbox, which checks each one."""


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
        self._walked = None
        self.carried = set()    # shared stores a fold carried files into

    # Locking: one mutating run per portable directory at a time.
    def lock(self, bind=True):
        self.store.mkdir(parents=True, exist_ok=True)
        (self.store / "portable-dir").write_text(str(self.portable.resolve()) + "\n")
        self._lock = open(self.store / "lock", "w")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncError(f"another claude-memory-sync is running on {self.portable} "
                            f"(lock {self.store / 'lock'}); retry when it finishes.")
        if bind:
            # Again under the lock: a rebind may have finished since main checked.
            self.check_binding()
            for key, value in self.binding().items():
                if not (self.store / key).exists():
                    write_atomic(self.store / key, (value + "\n").encode())

    # Binding: the base describes one disk side, the Claude directory and the
    # projects directory it was built against. Compared with any other, every
    # memory absent there would read as DELETED_LOCAL and be tombstoned on
    # every machine, and a second configuration that exists is not caught by
    # the MISSING guard. A store records its binding on its first locked run.
    def binding(self):
        return {"claude-dir": os.path.realpath(self.claude_dir),
                "projects-dir": os.path.realpath(self.projects_dir)}

    def recorded_binding(self):
        recorded = {}
        for key in self.binding():
            try:
                recorded[key] = (self.store / key).read_text().rstrip("\n")
            except FileNotFoundError:
                pass
        return recorded

    def check_binding(self):
        recorded = self.recorded_binding()
        for key, now in self.binding().items():
            if key in recorded and recorded[key] != now:
                raise SyncError(
                    f"this machine's base for {self.portable} was built against --{key} "
                    f"{recorded[key]}, not {now}; compared with it, every memory absent from "
                    f"{now} would read as deleted. Pass --{key} {recorded[key]} to sync that "
                    "directory, --state-dir to give another configuration its own base, or, "
                    f"only if the memories moved to {now}, run `rebind --{key} {now}`.")

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

    def walk_projects(self):
        """(slug, path, is_git) for each dir under projects_dir, following symlinks."""
        if self._walked is not None:
            return self._walked
        found, visited = [], set()
        root = self.projects_dir
        if root.is_dir():
            for dirpath, dirnames, _ in os.walk(root, followlinks=True):
                real = os.path.realpath(dirpath)
                if real in visited:
                    dirnames[:] = []
                    continue
                visited.add(real)
                rel = Path(dirpath).relative_to(root)
                depth = len(rel.parts)
                if depth:
                    found.append((rel.as_posix(), dirpath, (Path(dirpath) / ".git").is_dir()))
                if depth >= DISCOVERY_DEPTH - 1:
                    dirnames[:] = []
                else:
                    dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        self._walked = found
        return found

    def discover_projects(self):
        """Slugs of git repos under projects_dir, following symlinked repos."""
        return [slug for slug, _, is_git in self.walk_projects() if is_git]

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

    def known_slugs(self):
        """Every slug on any side, unfiltered, and the owner map built from them.

        The owner of a shared memory dir need not be a git repo: it is often
        the workspace dir holding the linked repos. It is found through the
        links, so it joins the slugs even though discovery alone skips it.
        """
        found = {GLOBAL}
        for slug in self.discover_projects():
            if self.memory_dirs(slug):
                found.add(slug)
        for root in (self.portable, self.base_root):
            found.update(self.stored_slugs(root))
            found.update(self.link_slugs(root))
        owners = self.owner_map(found)
        for slug in list(found):
            disk = self.disk_link(slug, owners)
            if disk and disk[0]:
                found.add(disk[0])
        return found, owners

    def slugs(self):
        found, _ = self.known_slugs()
        return sorted(s for s in found if self.included(s))

    # Shared memory dirs ------------------------------------------------------
    # A project whose memory dir is a symlink to another project's shares that
    # project's store. The link is recorded in the portable dir as
    # <slug>/memory.link holding the owner's slug, and in the base the same
    # way once this machine has synced it, so a link is classified three ways
    # like a file: disk, portable and base.
    def link_file(self, root, slug):
        return root / slug / LINK_FILE

    @staticmethod
    def read_link(path):
        try:
            return path.read_text().strip() or None
        except FileNotFoundError:
            return None

    @staticmethod
    def link_slugs(root):
        slugs = []
        if not root.is_dir():
            return slugs
        for dirpath, dirnames, filenames in os.walk(root):
            rel = Path(dirpath).relative_to(root)
            if rel.parts and LINK_FILE in filenames:
                slugs.append(rel.as_posix())
            if len(rel.parts) >= DISCOVERY_DEPTH:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "memory"]
        return slugs

    def owner_map(self, known):
        """Encoded project dir name -> the slug whose memory dir it holds."""
        owners = {encode(self.home): GLOBAL}
        for slug, path, _ in self.walk_projects():
            owners.setdefault(encode(path), slug)
            owners.setdefault(encode(os.path.realpath(path)), slug)
        # A slug known only from the portable dir or the base, such as one
        # whose checkout is not cloned here, still owns its encoded name.
        for slug in sorted(known):
            if slug != GLOBAL:
                owners.setdefault(encode(self.projects_dir / slug), slug)
        return owners

    def disk_link(self, slug, owners):
        """(owner, target) when slug's memory dir is another project's, else None.

        owner is None when the target is no project's memory dir.
        """
        if slug == GLOBAL:
            return None
        dirs = self.memory_dirs(slug)
        if len(dirs) != 1:
            return None
        projects = Path(os.path.realpath(self.claude_dir / "projects"))
        target = Path(os.path.realpath(dirs[0]))
        if target in {projects / c.name / "memory" for c in self.candidate_dirs(slug)}:
            return None
        owner = None
        if target.name == "memory" and target.parent.parent == projects:
            owner = owners.get(target.parent.name)
        return (owner if owner != slug else None), target

    def link_state(self, slug, owners):
        """(disk, portable, base) for slug's link; disk is disk_link()'s result."""
        return (self.disk_link(slug, owners),
                self.read_link(self.link_file(self.portable, slug)),
                self.read_link(self.link_file(self.base_root, slug)))

    def unsettled(self, slug):
        """Own files of slug whose portable copy changed since this machine synced it."""
        pdir, bdir = self.portable_dir(slug), self.base_dir(slug)
        return sorted(n for n in self.names(pdir) | self.names(bdir)
                      if sha(pdir / n) != sha(bdir / n))

    def dropped_by_link(self, slug):
        """Files of slug's own store that the shared dir it now links to lacks."""
        return sorted(self.names(self.base_dir(slug)) - self.names(self.disk_dir(slug)))

    def settled_copy(self, slug, name):
        """The bytes of slug/name that a file pass leaves on disk, or None."""
        dpath, bpath, ppath = (self.disk_dir(slug) / name, self.base_dir(slug) / name,
                               self.portable_dir(slug) / name)
        status, _ = self.classify(slug, name, dpath, bpath, ppath)
        if status in ("NEW_REMOTE", "REMOTE_EDIT"):
            return ppath.read_bytes()
        if status in ("DELETED_REMOTE", "STALE_LOCAL"):
            return None
        return dpath.read_bytes() if dpath.is_file() else None

    def fold_plan(self, slug, owner):
        """What folding slug's own memory dir into owner's does: ({name: data}, clashes).

        A file unchanged since this machine last synced it stays behind: the
        shared store already holds what the machines agreed on, and may have
        dropped it on purpose. A changed or never-synced file is carried over,
        MEMORY.md merged against slug's base. A file whose shared copy differs
        is a clash, as in link-aliases.
        """
        src = self.disk_dir(slug)
        if src.is_symlink() or not src.is_dir():
            return {}, []
        carry, clash = {}, []
        for name in sorted(self.names(src)):
            data, bpath = (src / name).read_bytes(), self.base_dir(slug) / name
            if sha(bpath) == hashlib.sha256(data).hexdigest():
                continue
            have = self.settled_copy(owner, name)
            if have is None:
                carry[name] = data
            elif have == data:
                continue
            elif name == INDEX:
                base = bpath.read_text() if bpath.exists() else ""
                text, conflicts = merge_index(base, have.decode(), data.decode())
                if conflicts:
                    clash.append(name)
                else:
                    carry[name] = text.encode()
            else:
                clash.append(name)
        return carry, clash

    def classify_link(self, slug, state):
        disk, p, b = state
        d = disk[0] if disk else None
        marker = self.link_file(self.portable, slug)
        if disk and d is None:
            return "LINK_CONFLICT", (f"memory dir links to {disk[1]}, which is no project's memory "
                                     "dir; point the link at one, or make it a dir of its own")
        if d and d == p:
            return "OK", f"link to {d}"
        if d and p is None and b is None:
            unsettled = self.unsettled(slug)
            if unsettled:
                return "LINK_CONFLICT", (
                    f"link to {d}, but this project's own copies changed elsewhere since this "
                    f"machine last synced them: {', '.join(unsettled)}. Settle each with resolve "
                    "(--keep remote brings it into the shared dir) before the link is recorded")
            dropped = self.dropped_by_link(slug)
            return "NEW_LINK", f"link to {d}" + (
                f"; the shared dir lacks {', '.join(dropped)}, tombstoned in {d}" if dropped else "")
        if d is None and p and b is None:
            carry, clash = self.fold_plan(slug, p)
            if clash:
                return "LINK_CONFLICT", (f"link to {p}; this project's memory dir here differs from "
                                         f"the shared one in {', '.join(clash)}. Settle those files "
                                         "by hand, then rerun")
            return "REMOTE_LINK", f"link to {p}" + (
                f"; carries {', '.join(sorted(carry))} into it" if carry else "")
        if d is None and p is None and b:
            return "GONE", ""
        if d and p:
            return "LINK_CONFLICT", f"links to {d} here, but {marker} records a link to {p}"
        if d:
            return "LINK_CONFLICT", (f"links to {d} here, but {marker}, recorded before, is gone. "
                                     f"Restore it, or replace the link here with a dir of its own")
        return "LINK_CONFLICT", (f"{marker} records a link to {p}, but the link here is gone. "
                                 f"Recreate it, or delete {marker} to give this project a store "
                                 "of its own")

    def missing(self, slug):
        """Files synced from slug whose disk memory dir is gone; empty when present.

        A whole directory vanishing is a wrong --claude-dir or --projects-dir, a
        moved checkout or a cleaned-up ~/.claude/projects far more often than a
        decision to delete every memory in it. Read file by file it would be
        DELETED_LOCAL, and the tombstones would delete it on every machine.
        """
        if self.memory_dirs(slug):
            return set()
        return self.names(self.base_dir(slug)) & self.names(self.portable_dir(slug))

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
        """Yield (slug, name, status, detail) for every tracked memory file.

        A linked project yields one entry with name None, after every file:
        apply settles the shared stores before it records or creates links.
        """
        found, owners = self.known_slugs()
        links = []
        for slug in sorted(s for s in found if self.included(s)):
            if len(self.memory_dirs(slug)) > 1:
                yield slug, None, "ALIASED", " ".join(str(d) for d in self.memory_dirs(slug))
                continue
            state = self.link_state(slug, owners)
            if any(state):
                links.append((slug, state))
                continue
            # Held whole: importing even one new file would recreate the dir,
            # and the next run would read the rest as deleted here.
            if self.missing(slug):
                yield slug, None, "MISSING", f"no memory dir at {self.disk_dir(slug)}"
                continue
            ddir, pdir, bdir = self.disk_dir(slug), self.portable_dir(slug), self.base_dir(slug)
            for name in sorted(self.names(ddir) | self.names(pdir, True) | self.names(bdir)):
                status, detail = self.classify(slug, name, ddir / name, bdir / name, pdir / name)
                yield slug, name, status, detail
        for slug, state in links:
            status, detail = self.classify_link(slug, state)
            yield slug, None, status, detail

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

    def mark_link(self, slug, owner):
        """Record slug as a link to owner in the base, which then holds nothing else."""
        shutil.rmtree(self.base_dir(slug), ignore_errors=True)
        write_atomic(self.link_file(self.base_root, slug), (owner + "\n").encode())

    def record_link(self, slug, owner):
        # Files the shared dir lacks were dropped when the stores were joined.
        # A tombstone in the shared store stops a copy elsewhere from being
        # carried back into it; this machine made the deletion, so it is
        # acknowledged here.
        for name in self.dropped_by_link(slug):
            self.add_tombstone(owner, name, sha(self.base_dir(slug) / name))
            self.ack_path(owner, name).parent.mkdir(parents=True, exist_ok=True)
            self.ack_path(owner, name).touch()
        pdir = self.portable_dir(slug)
        if pdir.is_dir():
            for path in sorted(p for p in pdir.rglob("*") if p.is_file()):
                side = "portable-tombstones" if path.parent.name == TOMBSTONE_DIR else "portable"
                self.backup(side, slug, path)
            shutil.rmtree(pdir)
        write_atomic(self.link_file(self.portable, slug), (owner + "\n").encode())
        self.mark_link(slug, owner)

    def create_link(self, slug, owner):
        """Fold slug's memory dir into owner's and replace it with a link; files carried."""
        carry, clash = self.fold_plan(slug, owner)
        if clash:
            raise SyncError(f"{slug}: {', '.join(clash)} changed while linking; rerun apply")
        src, dst = self.disk_dir(slug), self.disk_dir(owner)
        dst.mkdir(parents=True, exist_ok=True)
        for name, data in carry.items():
            self.backup("disk", owner, dst / name)
            write_atomic(dst / name, data, file_mode(dst / name))
        if src.is_dir():
            for name in self.names(src):
                self.backup("disk-alias", slug, src / name)
            shutil.rmtree(src)
        src.parent.mkdir(parents=True, exist_ok=True)
        src.symlink_to(os.path.relpath(dst, src.parent), target_is_directory=True)
        self.mark_link(slug, owner)
        return sorted(carry)

    def apply_link(self, slug, status, state):
        """Carry out a link entry's status; return the action word, or None."""
        disk, p, b = state
        if status == "OK":
            if b != p:
                self.mark_link(slug, p)
            return None
        if status == "GONE":
            self.link_file(self.base_root, slug).unlink(missing_ok=True)
            return None
        if status == "NEW_LINK":
            self.record_link(slug, disk[0])
            return "RECORDED"
        if status == "REMOTE_LINK":
            self.carried |= {p} if self.create_link(slug, p) else set()
            return "LINKED"
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
    _, owners = sync.known_slugs()
    for slug, name, status, detail in list(sync.entries()):
        if status in BLOCKING:
            blocked = True
            print("\t".join(filter(None, [status, label(slug, name), detail])))
            continue
        if name is None:
            action = sync.apply_link(slug, status, sync.link_state(slug, owners))
        else:
            action = sync.apply_entry(slug, name, status)
        if action:
            print(f"{action}\t{label(slug, name)}")
    # Files a fold carried into a shared dir are new to its store: export them
    # now, so that one apply converges.
    if sync.carried:
        for slug, name, status, detail in list(sync.entries()):
            if slug not in sync.carried or name is None or status == "OK":
                continue
            if status in BLOCKING:
                blocked = True
                print("\t".join(filter(None, [status, label(slug, name), detail])))
                continue
            action = sync.apply_entry(slug, name, status)
            if action:
                print(f"{action}\t{label(slug, name)}")
    return 2 if blocked else 0


def cmd_resolve(sync, args):
    sync.lock()
    targets = [(text, *split_label(text)) for text in args.paths]
    if args.keep == "remote":
        # Restoring part of a MISSING project recreates its memory dir, and the
        # files left out would then read as deleted here and be tombstoned.
        for slug in {slug for _, slug, _ in targets}:
            left = sync.missing(slug) - {name for _, s, name in targets if s == slug}
            if left:
                raise SyncError(
                    f"{slug} has no memory dir at {sync.disk_dir(slug)}, and restoring only some "
                    f"of its files would turn the rest into deletions. Also name: "
                    f"{' '.join(label(slug, n) for n in sorted(left))}, or delete the unwanted "
                    "ones first with --keep local.")
    for text, slug, name in targets:
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


def cmd_rebind(sync, args):
    """Record that the memories this base describes now live in these directories."""
    for key, path in (("claude-dir", sync.claude_dir), ("projects-dir", sync.projects_dir)):
        if not path.is_dir():
            raise SyncError(f"--{key} {path} is not a directory; rebind only to where the "
                            "memories are now.")
    sync.lock(bind=False)
    recorded = sync.recorded_binding()
    for key, now in sync.binding().items():
        if recorded.get(key) != now:
            write_atomic(sync.store / key, (now + "\n").encode())
            print(f"REBOUND\t{key}\t{recorded.get(key, '(none)')} -> {now}")
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
    common.add_argument("--claude-dir",
                        default=(os.environ.get("CLAUDE_DIR") or os.environ.get("CLAUDE_CONFIG_DIR")
                                 or "~/.claude"),
                        help="Claude Code data directory (default: $CLAUDE_DIR, else Claude Code's "
                             "own $CLAUDE_CONFIG_DIR, else ~/.claude)")
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

    p = sub.add_parser("rebind", parents=[common],
                       help="record that this machine's memories moved to --claude-dir / --projects-dir",
                       description="The base is bound to the Claude and projects directories it "
                                   "was built against, and any other run is refused. After moving "
                                   "the memory directories themselves, run this with the new "
                                   "directories to bind the base to them. To sync a second "
                                   "configuration instead, give it its own base with --state-dir.")
    p.set_defaults(func=cmd_rebind)

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
        sync = Sync(args)
        if args.func is not cmd_rebind:
            sync.check_binding()
        return args.func(sync, args)
    except SyncError as err:
        print(f"claude-memory-sync: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
