"""Tests for claude-memory-sync: three-way memory sync between machines.

Each test builds throwaway machines (a fake HOME with ~/projects and ~/.claude)
that share one portable directory, all under the run's private TMPDIR.
"""

import fcntl
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "harnesses/claude-code/scripts/claude-memory-sync.py"
spec = importlib.util.spec_from_file_location("claude_memory_sync", SCRIPT)
cms = importlib.util.module_from_spec(spec)
# Importing by path would drop a __pycache__ into the source tree.
_dont_write, sys.dont_write_bytecode = sys.dont_write_bytecode, True
spec.loader.exec_module(cms)
sys.dont_write_bytecode = _dont_write


def tmp_root():
    base = Path(os.environ.get("TMPDIR") or Path.home() / "tmp")
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="claude-memory-sync.", dir=base))


class Machine:
    def __init__(self, root, name, portable):
        self.home = root / name
        self.portable = portable
        (self.home / "projects").mkdir(parents=True)
        (self.home / ".claude/projects").mkdir(parents=True)

    def run(self, *args, stdin=None):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_MEMORY_DIR", "CLAUDE_PROJECTS_DIR", "CLAUDE_DIR")}
        env.update(HOME=str(self.home), XDG_STATE_HOME=str(self.home / ".local/state"))
        cmd, *rest = args
        proc = subprocess.run([sys.executable, str(SCRIPT), cmd, "--dir", str(self.portable), *rest],
                              env=env, input=stdin, capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    def lines(self, *args):
        code, out, err = self.run(*args)
        self.last_err = err
        return code, [ln.split("\t")[:2] for ln in out.splitlines()]

    def project(self, slug):
        (self.home / "projects" / slug / ".git").mkdir(parents=True, exist_ok=True)
        return self

    def mem(self, slug):
        target = self.home if slug == "_global" else self.home / "projects" / slug
        return self.home / ".claude/projects" / cms.encode(target) / "memory"

    def write(self, slug, name, text):
        path = self.mem(slug) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def read(self, slug, name):
        return (self.mem(slug) / name).read_text()

    def exists(self, slug, name):
        return (self.mem(slug) / name).exists()


class SyncTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tmp_root()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.portable = self.root / "portable"
        self.portable.mkdir()
        self.a = Machine(self.root, "a", self.portable).project("app")
        self.b = Machine(self.root, "b", self.portable).project("app")

    def pfile(self, slug, name):
        return self.portable / slug / "memory" / name

    def tombstone(self, slug, name):
        return self.portable / slug / "memory" / ".deleted" / name

    def apply(self, machine, *extra):
        code, rows = machine.lines("apply", *extra)
        return code, {tuple(r) for r in rows}


class BasicFlowTests(SyncTestCase):
    def test_new_local_is_exported_then_in_sync(self):
        self.a.write("app", "note.md", "one\n")
        code, rows = self.a.lines("status")
        self.assertEqual((code, rows), (2, [["NEW_LOCAL", "app/memory/note.md"]]))
        self.assertEqual(self.apply(self.a), (0, {("EXPORTED", "app/memory/note.md")}))
        self.assertEqual(self.pfile("app", "note.md").read_text(), "one\n")
        self.assertEqual(self.a.lines("status"), (0, []))

    def test_new_remote_is_imported_under_the_other_home(self):
        self.a.write("app", "note.md", "one\n")
        self.apply(self.a)
        self.assertEqual(self.apply(self.b), (0, {("IMPORTED", "app/memory/note.md")}))
        self.assertEqual(self.b.read("app", "note.md"), "one\n")
        self.assertIn(cms.encode(self.b.home), str(self.b.mem("app")))

    def test_edits_flow_both_ways(self):
        self.a.write("app", "note.md", "one\n")
        self.apply(self.a)
        self.apply(self.b)
        self.b.write("app", "note.md", "two\n")
        self.assertEqual(self.apply(self.b), (0, {("EXPORTED", "app/memory/note.md")}))
        code, rows = self.a.lines("status")
        self.assertEqual(rows, [["REMOTE_EDIT", "app/memory/note.md"]])
        self.assertEqual(self.apply(self.a), (0, {("IMPORTED", "app/memory/note.md")}))
        self.assertEqual(self.a.read("app", "note.md"), "two\n")

    def test_global_memories_use_the_global_slug(self):
        self.a.write("_global", "me.md", "user\n")
        self.assertEqual(self.apply(self.a), (0, {("EXPORTED", "_global/memory/me.md")}))
        self.apply(self.b)
        self.assertEqual(self.b.read("_global", "me.md"), "user\n")

    def test_memory_is_imported_before_the_project_is_cloned(self):
        self.a.project("later").write("later", "n.md", "x\n")
        self.apply(self.a)
        self.assertEqual(self.apply(self.b), (0, {("IMPORTED", "later/memory/n.md")}))
        self.assertTrue(self.b.exists("later", "n.md"))


class DeletionTests(SyncTestCase):
    def synced(self, text="one\n"):
        self.a.write("app", "note.md", text)
        self.apply(self.a)
        self.apply(self.b)

    def test_local_deletion_tombstones_and_propagates(self):
        self.synced()
        (self.a.mem("app") / "note.md").unlink()
        self.assertEqual(self.apply(self.a), (0, {("TOMBSTONED", "app/memory/note.md")}))
        self.assertFalse(self.pfile("app", "note.md").exists())
        digest = hashlib.sha256(b"one\n").hexdigest()
        self.assertTrue(self.tombstone("app", "note.md").read_text().startswith(digest))
        self.assertEqual(self.b.lines("status")[1], [["DELETED_REMOTE", "app/memory/note.md"]])
        self.assertEqual(self.apply(self.b), (0, {("REMOVED", "app/memory/note.md")}))
        self.assertFalse(self.b.exists("app", "note.md"))
        # nothing is resurrected on the next round
        self.assertEqual(self.a.lines("status"), (0, []))
        self.assertEqual(self.b.lines("status"), (0, []))

    def test_removed_file_is_backed_up(self):
        self.synced()
        (self.a.mem("app") / "note.md").unlink()
        self.apply(self.a)
        self.apply(self.b)
        backups = list((self.b.home / ".local/state").rglob("backups/*/disk/app/memory/note.md"))
        self.assertEqual([p.read_text() for p in backups], ["one\n"])

    def test_stale_copy_on_a_machine_that_never_synced_is_removed(self):
        self.synced()
        c = Machine(self.root, "c", self.portable).project("app")
        c.write("app", "note.md", "one\n")          # e.g. restored from a backup
        (self.a.mem("app") / "note.md").unlink()
        self.apply(self.a)
        self.assertEqual(c.lines("status")[1], [["STALE_LOCAL", "app/memory/note.md"]])
        self.apply(c)
        self.assertFalse(c.exists("app", "note.md"))

    def test_tombstoned_name_with_other_content_is_a_conflict(self):
        self.synced()
        c = Machine(self.root, "c", self.portable).project("app")
        c.write("app", "note.md", "different\n")
        (self.a.mem("app") / "note.md").unlink()
        self.apply(self.a)
        code, rows = self.apply(c)
        self.assertEqual((code, rows), (2, {("CONFLICT", "app/memory/note.md")}))
        self.assertEqual(c.read("app", "note.md"), "different\n")

    def test_deleted_here_edited_elsewhere_is_a_conflict(self):
        self.synced()
        self.b.write("app", "note.md", "two\n")
        self.apply(self.b)
        (self.a.mem("app") / "note.md").unlink()
        self.assertEqual(self.apply(self.a), (2, {("CONFLICT", "app/memory/note.md")}))
        self.assertEqual(self.pfile("app", "note.md").read_text(), "two\n")

    def test_edited_here_deleted_elsewhere_is_a_conflict(self):
        self.synced()
        (self.b.mem("app") / "note.md").unlink()
        self.apply(self.b)
        self.a.write("app", "note.md", "two\n")
        self.assertEqual(self.apply(self.a), (2, {("CONFLICT", "app/memory/note.md")}))
        self.assertEqual(self.a.read("app", "note.md"), "two\n")

    def test_recreating_a_deleted_file_clears_its_tombstone(self):
        self.synced()
        (self.a.mem("app") / "note.md").unlink()
        self.apply(self.a)
        self.a.write("app", "note.md", "back\n")
        self.assertEqual(self.apply(self.a), (0, {("EXPORTED", "app/memory/note.md")}))
        self.assertFalse(self.tombstone("app", "note.md").exists())
        self.apply(self.b)
        self.assertEqual(self.b.read("app", "note.md"), "back\n")


class ConflictTests(SyncTestCase):
    def test_both_edited_is_left_untouched_until_resolved(self):
        self.a.write("app", "note.md", "one\n")
        self.apply(self.a)
        self.apply(self.b)
        self.a.write("app", "note.md", "a\n")
        self.b.write("app", "note.md", "b\n")
        self.apply(self.b)
        self.assertEqual(self.apply(self.a), (2, {("CONFLICT", "app/memory/note.md")}))
        self.assertEqual(self.a.read("app", "note.md"), "a\n")
        self.assertEqual(self.pfile("app", "note.md").read_text(), "b\n")
        code, out, _ = self.a.run("resolve", "--keep", "local", "app/memory/note.md")
        self.assertEqual((code, out), (0, "EXPORTED\tapp/memory/note.md\n"))
        self.apply(self.b)
        self.assertEqual(self.b.read("app", "note.md"), "a\n")

    def test_resolve_remote_takes_the_portable_copy(self):
        self.a.write("app", "note.md", "mine\n")
        self.b.write("app", "note.md", "theirs\n")
        self.apply(self.b)
        self.assertEqual(self.apply(self.a), (2, {("CONFLICT", "app/memory/note.md")}))
        self.a.run("resolve", "--keep", "remote", "app/memory/note.md")
        self.assertEqual(self.a.read("app", "note.md"), "theirs\n")
        self.assertEqual(self.a.lines("status"), (0, []))

    def test_resolve_rejects_a_malformed_path(self):
        code, _, err = self.a.run("resolve", "--keep", "local", "app/note.md")
        self.assertEqual(code, 1)
        self.assertIn("<slug>/memory/<file>", err)


class IndexMergeTests(SyncTestCase):
    BASE = "# Index\n- [A](a.md) — a\n- [B](b.md) — b\n"

    def test_merge_keeps_both_sides_changes_and_honours_removals(self):
        text, conflicts = cms.merge_index(
            self.BASE,
            "# Index\n- [B](b.md) — b\n- [C](c.md) — c\n",           # removed A, added C
            "# Index\n- [A](a.md) — a\n- [B](b.md) — b2\n- [D](d.md) — d\n")  # edited B, added D
        self.assertEqual(conflicts, [])
        self.assertEqual(text, "# Index\n- [B](b.md) — b2\n- [C](c.md) — c\n- [D](d.md) — d\n")

    def test_merge_reports_entries_changed_on_both_sides(self):
        _, conflicts = cms.merge_index(self.BASE, self.BASE.replace("— b", "— x"),
                                       self.BASE.replace("— b", "— y"))
        self.assertEqual(conflicts, ["link:b.md"])

    def test_merge_reports_edit_against_removal(self):
        _, conflicts = cms.merge_index(self.BASE, self.BASE.replace("— a", "— a2"),
                                       "# Index\n- [B](b.md) — b\n")
        self.assertEqual(conflicts, ["link:a.md"])

    def test_without_a_base_the_merge_is_a_union(self):
        text, conflicts = cms.merge_index("", "- [A](a.md) — a\n", "- [B](b.md) — b\n")
        self.assertEqual((text, conflicts), ("- [A](a.md) — a\n- [B](b.md) — b\n", []))

    def test_index_changed_on_both_machines_is_merged(self):
        self.a.write("app", "MEMORY.md", self.BASE)
        self.apply(self.a)
        self.apply(self.b)
        self.a.write("app", "MEMORY.md", "# Index\n- [B](b.md) — b\n")
        self.b.write("app", "MEMORY.md", self.BASE + "- [D](d.md) — d\n")
        self.apply(self.b)
        self.assertEqual(self.a.lines("status")[1], [["MERGE", "app/memory/MEMORY.md"]])
        self.assertEqual(self.apply(self.a), (0, {("MERGED", "app/memory/MEMORY.md")}))
        merged = "# Index\n- [B](b.md) — b\n- [D](d.md) — d\n"
        self.assertEqual(self.a.read("app", "MEMORY.md"), merged)
        self.assertEqual(self.pfile("app", "MEMORY.md").read_text(), merged)
        self.apply(self.b)
        self.assertEqual(self.b.read("app", "MEMORY.md"), merged)


class FilterTests(SyncTestCase):
    def setUp(self):
        super().setUp()
        for slug in ("red", "redhat", "redhat/aro", "other"):
            self.a.project(slug).write(slug, "n.md", slug + "\n")

    def exported(self, *flags):
        _, rows = self.apply(self.a, *flags)
        return sorted(r[1].split("/memory/")[0] for r in rows)

    def test_skip_matches_whole_path_segments(self):
        self.assertEqual(self.exported("--skip", "red"), ["other", "redhat", "redhat/aro"])

    def test_skip_covers_nested_slugs(self):
        self.assertEqual(self.exported("--skip", "redhat/"), ["other", "red"])

    def test_allow_limits_and_skip_subtracts(self):
        self.a.write("_global", "g.md", "g\n")
        self.assertEqual(self.exported("--allow", "redhat", "--skip", "redhat/aro"),
                         ["_global", "redhat"])


class LayoutTests(SyncTestCase):
    def test_encoding_replaces_every_non_alphanumeric(self):
        self.assertEqual(cms.encode("/home/u/my_app.v2 x"), "-home-u-my-app-v2-x")

    def test_project_with_dots_and_underscores(self):
        self.a.project("my_app.v2").write("my_app.v2", "n.md", "x\n")
        self.assertIn("-projects-my-app-v2", str(self.a.mem("my_app.v2")))
        self.assertEqual(self.apply(self.a), (0, {("EXPORTED", "my_app.v2/memory/n.md")}))

    def alias(self):
        real = self.a.home / "elsewhere/tool"
        (real / ".git").mkdir(parents=True)
        (self.a.home / "projects/tool").symlink_to(real)
        real_mem = self.a.home / ".claude/projects" / cms.encode(real) / "memory"
        return real_mem

    def test_symlinked_project_uses_the_real_path_store(self):
        real_mem = self.alias()
        real_mem.mkdir(parents=True)
        (real_mem / "n.md").write_text("x\n")
        self.assertEqual(self.apply(self.a), (0, {("EXPORTED", "tool/memory/n.md")}))

    def test_duplicate_stores_are_refused_then_linked(self):
        real_mem = self.alias()
        real_mem.mkdir(parents=True)
        (real_mem / "MEMORY.md").write_text("- [R](r.md) — r\n")
        (real_mem / "r.md").write_text("r\n")
        self.a.write("tool", "MEMORY.md", "- [C](c.md) — c\n")
        self.a.write("tool", "c.md", "c\n")
        self.assertEqual(self.apply(self.a), (2, {("ALIASED", "tool")}))
        code, out, _ = self.a.run("link-aliases")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("LINKED\t"))
        self.assertTrue(real_mem.is_symlink())
        self.assertEqual(self.a.read("tool", "MEMORY.md"), "- [C](c.md) — c\n- [R](r.md) — r\n")
        self.assertEqual(self.apply(self.a)[0], 0)

    def test_link_aliases_refuses_differing_files(self):
        real_mem = self.alias()
        real_mem.mkdir(parents=True)
        (real_mem / "n.md").write_text("one\n")
        self.a.write("tool", "n.md", "two\n")
        code, out, _ = self.a.run("link-aliases")
        self.assertEqual(code, 2)
        self.assertIn("CONFLICT\ttool\tdiffering files: n.md", out)
        self.assertFalse(real_mem.is_symlink())


class OperationTests(SyncTestCase):
    def test_adopt_lets_the_first_run_see_a_local_deletion(self):
        self.pfile("app", "old.md").parent.mkdir(parents=True)
        self.pfile("app", "old.md").write_text("old\n")
        digest = hashlib.sha256(b"old\n").hexdigest()
        self.assertEqual(self.a.lines("status")[1], [["NEW_REMOTE", "app/memory/old.md"]])
        code, out, _ = self.a.run("adopt", stdin=f"app/memory/old.md\t{digest}\n"
                                               f"app/memory/gone.md\t{'0' * 64}\n")
        self.assertEqual(out, "ADOPTED\tapp/memory/old.md\n"
                              "UNADOPTED\tapp/memory/gone.md\tno copy with that checksum\n")
        self.assertEqual(self.a.lines("status")[1], [["DELETED_LOCAL", "app/memory/old.md"]])

    def test_missing_portable_dir_names_the_fix(self):
        shutil.rmtree(self.portable)
        code, _, err = self.a.run("status")
        self.assertEqual(code, 1)
        self.assertIn("mkdir -p", err)

    def test_concurrent_apply_is_refused(self):
        self.a.run("status")
        code, _, _ = self.a.run("apply")
        lock = next((self.a.home / ".local/state").rglob("lock"))
        with open(lock, "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code, _, err = self.a.run("apply")
        self.assertEqual(code, 1)
        self.assertIn("another claude-memory-sync is running", err)

    def test_bases_are_isolated_per_portable_dir(self):
        self.a.write("app", "n.md", "x\n")
        self.apply(self.a)
        other = self.root / "other-portable"
        other.mkdir()
        code, out, _ = self.a.run("status", "--dir", str(other))
        self.assertEqual((code, out), (2, "NEW_LOCAL\tapp/memory/n.md\n"))


if __name__ == "__main__":
    unittest.main()
