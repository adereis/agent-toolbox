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

    def run_cli(self, *args, codex_home=""):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(installer.Path, "home", return_value=self.root), \
             patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = installer.main(list(args))
        return result, out.getvalue(), err.getvalue()

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
        for target in (claude, codex):
            self.assertEqual((target / "skills/whats-new/references/workflow.md").resolve(), REPO / "skills/whats-new/SKILL.md")
            self.assertTrue((target / "skills/whats-new/SKILL.md").is_file())
        self.assertFalse((codex / "settings.json").exists())
        self.assertFalse((claude / "settings.json").exists())

    def test_baseline_skill_shares_one_workflow_across_harnesses(self):
        claude, codex = self.root / "claude", self.root / "codex"
        for name, target in (("claude-code", claude), ("codex", codex)):
            self.install(target, installer.catalog(name, ["skills"]), True)
            workflow = target / "skills/adopt-baseline/references/workflow.md"
            self.assertEqual(workflow.resolve(), REPO / "skills/adopt-baseline/SKILL.md")
            entry = target / "skills/adopt-baseline/SKILL.md"
            self.assertEqual(entry.resolve(), REPO / "harnesses" / name / "skills/adopt-baseline/SKILL.md")
        self.assertEqual((codex / "skills/adopt-baseline/agents/openai.yaml").resolve(),
                         REPO / "harnesses/codex/skills/adopt-baseline/agents/openai.yaml")
        self.assertFalse((claude / "skills/adopt-baseline/agents").exists())

    def test_instruction_modules_install_without_touching_policy_files(self):
        for name in ("claude-code", "codex"):
            with self.subTest(harness=name):
                target = self.root / name
                self.install(target, installer.catalog(name, ["instructions"]), True)
                module = target / "instructions/global-baseline.md"
                self.assertEqual(module.resolve(), REPO / "instructions/global-baseline.md")
                self.assertFalse((target / "instructions/README.md").exists())
                for policy in ("CLAUDE.md", "AGENTS.md"):
                    self.assertFalse((target / policy).exists())

    def test_global_baseline_module_stays_harness_neutral(self):
        text = (REPO / "instructions/global-baseline.md").read_text()
        for token in ("Claude-Session", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "mcpServers",
                      "config.toml", "subagent", "~/.claude", "~/.codex", "~/.agents"):
            self.assertNotIn(token, text, f"harness-specific token in shared module: {token}")

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
        links = installer.catalog("claude-code", [c for c in installer.COMPONENTS if c != "profiles"])
        self.assertTrue(all("examples" not in source.parts for source in links.values()))
        self.assertEqual({Path(path).name for path in links if path.startswith("hooks/")},
                         {"git-push-guard.sh", "jira-mcp-subagent-guard.sh"})

    def test_profile_dry_run_uses_codex_home_without_creating_it(self):
        target = self.root / "custom codex home"
        result, out, err = self.run_cli(
            "--harness", "codex", "--scope", "user", "--component", "profiles", codex_home=target)
        self.assertEqual((result, err), (0, ""))
        self.assertIn(str(target / "api.config.toml"), out)
        self.assertIn(str(target / "subscription.config.toml"), out)
        self.assertFalse(target.exists())

    def test_mixed_install_uses_each_native_root(self):
        args = ["--harness", "codex", "--scope", "user", "--component", "skills",
                "--component", "profiles", "--apply"]
        result, _, err = self.run_cli(*args)
        self.assertEqual((result, err), (0, ""))
        self.assertTrue((self.root / ".agents/skills/teach/SKILL.md").is_symlink())
        for name in ("api", "subscription"):
            installed = self.root / ".codex" / f"{name}.config.toml"
            self.assertEqual(installed.resolve(), REPO / "harnesses/codex/profiles" / installed.name)
            self.assertFalse((self.root / ".agents" / installed.name).exists())
        self.assertFalse((self.root / ".codex/skills").exists())

    def test_profiles_preserve_login_config_history_and_other_profiles(self):
        target = self.root / "selected codex home"
        target.mkdir()
        existing = {
            "config.toml": 'model = "demo-model"\n',
            "auth.json": '{"synthetic": "saved login fixture"}\n',
            "history.jsonl": '{"synthetic": "history fixture"}\n',
            "work.config.toml": 'model = "work-model"\n',
        }
        for name, content in existing.items():
            (target / name).write_text(content)
        args = ["--harness", "codex", "--scope", "user", "--component", "profiles", "--apply"]
        result, _, err = self.run_cli(*args, codex_home=target)
        self.assertEqual((result, err), (0, ""))
        before = {p.name: p.lstat().st_ino for p in target.iterdir()}
        result, _, err = self.run_cli(*args, codex_home=target)
        self.assertEqual((result, err), (0, ""))
        self.assertEqual(before, {p.name: p.lstat().st_ino for p in target.iterdir()})
        for name, content in existing.items():
            self.assertEqual((target / name).read_text(), content)
        self.assertFalse((self.root / ".codex").exists())

    def test_explicit_profile_target_overrides_codex_home(self):
        target = self.root / "staged config"
        other = self.root / "unselected config"
        result, _, err = self.run_cli(
            "--harness", "codex", "--scope", "user", "--component", "profiles",
            "--target", str(target), "--apply", codex_home=other)
        self.assertEqual((result, err), (0, ""))
        self.assertTrue((target / "api.config.toml").is_symlink())
        self.assertTrue((target / "subscription.config.toml").is_symlink())
        self.assertFalse(other.exists())
        self.assertFalse((self.root / ".codex").exists())

    def test_explicit_target_applies_to_all_selected_components(self):
        target = self.root / "staging"
        result, _, err = self.run_cli(
            "--harness", "codex", "--scope", "user", "--component", "profiles",
            "--component", "scripts", "--target", str(target), "--apply")
        self.assertEqual((result, err), (0, ""))
        self.assertTrue((target / "api.config.toml").is_symlink())
        self.assertTrue((target / "scripts/codex-code-session-resume.py").is_symlink())
        self.assertFalse((self.root / ".agents").exists())
        self.assertFalse((self.root / ".codex").exists())

    def test_profiles_reject_project_scope_even_with_explicit_target(self):
        for extra in ([], ["--target", str(self.root / "staging")]):
            with self.subTest(extra=extra):
                result, _, err = self.run_cli(
                    "--harness", "codex", "--scope", "project", "--component", "scripts",
                    "--component", "profiles", "--apply", *extra)
                self.assertEqual(result, 1)
                self.assertIn("require --scope user", err)
                self.assertEqual(list(self.root.iterdir()), [])

    def test_profiles_reject_claude_without_installing_other_components(self):
        result, _, err = self.run_cli(
            "--harness", "claude-code", "--scope", "user", "--component", "skills",
            "--component", "profiles", "--target", str(self.root / "claude"), "--apply")
        self.assertEqual(result, 1)
        self.assertIn("profiles is not available for claude-code", err)
        self.assertFalse((self.root / "claude").exists())

    def test_mixed_install_preflights_conflicts_across_roots(self):
        target = self.root / "codex"
        target.mkdir()
        existing = target / "subscription.config.toml"
        existing.write_text("# Custom profile\n")
        result, _, err = self.run_cli(
            "--harness", "codex", "--scope", "user", "--component", "skills",
            "--component", "profiles", "--apply", codex_home=target)
        self.assertEqual(result, 1)
        self.assertIn("Existing files differ", err)
        self.assertEqual(existing.read_text(), "# Custom profile\n")
        self.assertFalse((target / "api.config.toml").exists())
        self.assertFalse((self.root / ".agents").exists())

    def test_mixed_install_rolls_back_links_across_roots(self):
        target = self.root / "codex"
        original = os.symlink

        def race(src, name, *, dir_fd):
            if name == "subscription.config.toml":
                descriptor = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=dir_fd)
                try:
                    os.write(descriptor, b"# Concurrent user profile\n")
                finally:
                    os.close(descriptor)
                raise FileExistsError(name)
            return original(src, name, dir_fd=dir_fd)

        with patch.object(installer.os, "symlink", side_effect=race):
            result, _, err = self.run_cli(
                "--harness", "codex", "--scope", "user", "--component", "skills",
                "--component", "profiles", "--apply", codex_home=target)
        self.assertEqual(result, 1)
        self.assertIn("Target changed during installation", err)
        self.assertEqual((target / "subscription.config.toml").read_text(), "# Concurrent user profile\n")
        self.assertFalse((target / "api.config.toml").exists())
        self.assertFalse((self.root / ".agents/skills/teach/SKILL.md").exists())
        self.assertFalse((self.root / ".agents/skills/teach/agents/openai.yaml").exists())
