"""Installation preflight, scope isolation, and concurrent conflict behavior."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("toolbox_install", REPO / "tools/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home() / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def install(self, target, links, apply=False):
        with contextlib.redirect_stdout(io.StringIO()):
            installer.install(target, links, apply)

    def test_dry_run_does_not_create_destination(self):
        target = self.root / "not-created"
        self.install(target, installer.catalog("codex", ["skills", "scripts"]))
        self.assertFalse(target.exists())

    def test_both_harnesses_use_same_workflow_with_native_metadata(self):
        claude, codex = self.root / "claude", self.root / "codex"
        for name, target in (("claude-code", claude), ("codex", codex)):
            self.install(target, installer.catalog(name, ["skills"]), True)
        self.assertEqual((claude / "skills/teach/references/workflow.md").resolve(), REPO / "skills/teach/SKILL.md")
        self.assertEqual((codex / "skills/teach/SKILL.md").resolve(), REPO / "skills/teach/SKILL.md")
        self.assertEqual((codex / "skills/teach/agents/openai.yaml").resolve(), REPO / "harnesses/codex/skills/teach/agents/openai.yaml")
        self.assertFalse((codex / "settings.json").exists())
        self.assertFalse((claude / "settings.json").exists())

    def test_repeated_install_is_idempotent(self):
        target = self.root / "install"
        links = installer.catalog("codex", ["skills", "scripts"])
        self.install(target, links, True)
        before = {path: (target / path).lstat().st_ino for path in links}
        self.install(target, links, True)
        self.assertEqual(before, {path: (target / path).lstat().st_ino for path in links})

    def test_preflight_conflict_preserves_all_existing_content(self):
        target = self.root / "install"
        (target / "skills/teach").mkdir(parents=True)
        custom = target / "skills/teach/SKILL.md"
        custom.write_text("Local custom workflow")
        with self.assertRaises(ValueError):
            self.install(target, installer.catalog("codex", ["skills", "scripts"]), True)
        self.assertEqual(custom.read_text(), "Local custom workflow")
        self.assertFalse((target / "scripts").exists())

    def test_parent_symlink_cannot_write_into_another_scope(self):
        target, outside = self.root / "install", self.root / "other-profile"
        target.mkdir(); outside.mkdir()
        (target / "skills").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.install(target, installer.catalog("codex", ["skills"]), True)
        self.assertEqual(list(outside.iterdir()), [])

    def test_racing_conflict_rolls_back_only_our_links(self):
        target = self.root / "install"
        source = REPO / "skills/teach/SKILL.md"
        original = os.symlink
        count = 0

        def race(src, name, *, dir_fd):
            nonlocal count
            count += 1
            if count == 2:
                descriptor = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=dir_fd)
                os.write(descriptor, b"Concurrent user content")
                os.close(descriptor)
                raise FileExistsError(name)
            return original(src, name, dir_fd=dir_fd)

        with patch.object(installer.os, "symlink", side_effect=race), self.assertRaises(ValueError):
            self.install(target, {"first": source, "second": source}, True)
        self.assertFalse((target / "first").exists())
        self.assertEqual((target / "second").read_text(), "Concurrent user content")

    def test_unavailable_components_are_reported(self):
        with self.assertRaisesRegex(ValueError, "not available"):
            installer.catalog("codex", ["hooks"])

    def test_examples_and_retired_components_are_not_installable(self):
        links = installer.catalog("claude-code", list(installer.COMPONENTS))
        self.assertTrue(all("examples" not in source.parts for source in links.values()))
        self.assertEqual({Path(path).name for path in links if path.startswith("hooks/")},
                         {"git-push-guard.sh", "jira-mcp-subagent-guard.sh"})
