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

    def test_baseline_adoption_is_a_prompt_and_never_a_skill(self):
        """Adoption runs rarely and rewrites the user's own configuration.

        A skill announces itself in every session that can discover it, so
        this workflow ships as a prompt: installed as plain text, invoked
        explicitly, and absent from the skills component for both harnesses.
        """
        for name in ("claude-code", "codex"):
            with self.subTest(harness=name):
                target = self.root / name
                self.install(target, installer.catalog(name, ["prompts"]), True)
                prompt = target / "prompts/adopt-baseline.md"
                self.assertEqual(prompt.resolve(), REPO / "prompts/adopt-baseline.md")
                skills = installer.catalog(name, ["skills"])
                self.assertEqual([p for p in skills if "adopt-baseline" in p], [])

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

    def test_commands_install_on_path_without_their_extensions(self):
        result, _, err = self.run_cli(
            "--harness", "codex", "--scope", "user", "--component", "commands", "--apply")
        self.assertEqual((result, err), (0, ""))
        expected = {"codex-api-profile": "harnesses/codex/scripts/codex-api-profile.sh",
                    "codex-code-session-resume": "harnesses/codex/scripts/codex-code-session-resume.py",
                    "codex-tmux": "harnesses/codex/scripts/codex-tmux.py",
                    "convene": "harnesses/claude-code/plugins/convene/bin/convene"}
        installed = self.root / ".local/bin"
        self.assertEqual({path.name for path in installed.iterdir()}, set(expected))
        for command, source in expected.items():
            self.assertEqual((installed / command).resolve(), REPO / source)

    def test_convene_reaches_both_harnesses_and_codex_reads_the_plugin_skill(self):
        """Codex reaches the engine directly: the command on PATH and the
        plugin's own operator procedure linked as a Codex skill."""
        self.assertEqual(installer.catalog("claude-code", ["commands"])["convene"],
                         REPO / "harnesses/claude-code/plugins/convene/bin/convene")
        result, _, err = self.run_cli(
            "--harness", "codex", "--scope", "user", "--component", "skills", "--apply")
        self.assertEqual((result, err), (0, ""))
        skill = self.root / ".agents/skills/convene"
        plugin = REPO / "harnesses/claude-code/plugins/convene/skills/convene"
        self.assertTrue(skill.is_symlink())
        self.assertEqual(skill.resolve(), plugin)
        # Codex follows directory symlinks but omits file symlinks in its
        # inventory. Checking only Path.is_file() hid the live loading defect.
        discovered = {entry.name for entry in os.scandir(skill)
                      if entry.is_file(follow_symlinks=False)}
        self.assertIn("SKILL.md", discovered)
        self.assertEqual((skill / "SKILL.md").resolve(), plugin / "SKILL.md")
        self.assertEqual((skill / "references/synthesis.md").resolve(), plugin / "references/synthesis.md")
        self.assertEqual((skill / "agents/openai.yaml").resolve(), plugin / "agents/openai.yaml")
        self.assertIn("allow_implicit_invocation: false", (skill / "agents/openai.yaml").read_text())
        text = (skill / "SKILL.md").read_text()
        self.assertIn("`convene` on PATH", text, "the shared procedure names the command for every harness")
        self.assertIn("harnesses/claude-code/plugins/convene/bin/convene", text)
        self.assertFalse((self.root / ".claude/skills/convene").exists(),
                         "Claude Code gets the skill from the plugin, not the installer")

    def test_directory_link_conflict_preserves_existing_skill(self):
        skill = self.root / ".agents/skills/convene"
        skill.mkdir(parents=True)
        custom = skill / "SKILL.md"
        custom.write_text("Local custom workflow")
        result, _, err = self.run_cli(
            "--harness", "codex", "--scope", "user", "--component", "skills",
            "--component", "commands", "--apply")
        self.assertEqual(result, 1)
        self.assertIn("Existing files differ", err)
        self.assertEqual(custom.read_text(), "Local custom workflow")
        self.assertFalse((self.root / ".local/bin/convene").exists())

    def test_directory_link_rollback_preserves_source_contents(self):
        source = self.root / "source"
        source.mkdir()
        marker = source / "SKILL.md"
        marker.write_text("Authoritative workflow")
        original = os.symlink

        def fail_second(src, name, *, dir_fd):
            if name == "second":
                raise OSError("Synthetic link failure")
            return original(src, name, dir_fd=dir_fd)

        target = self.root / "install"
        with patch.object(installer.os, "symlink", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "Synthetic link failure"):
                self.install(target, {"first": source, "second": marker}, True)
        self.assertFalse((target / "first").is_symlink())
        self.assertEqual(marker.read_text(), "Authoritative workflow")

    def test_commands_exclude_agent_invoked_scripts(self):
        """A skill reads whats-new by path, so it never lands on PATH."""
        commands = set()
        for harness in ("claude-code", "codex"):
            commands |= set(installer.catalog(harness, ["commands"]))
        for withheld in ("claude-code-whats-new", "codex-whats-new"):
            self.assertNotIn(withheld, commands)
        self.assertIn("claude-memory-sync", commands)
        self.assertTrue(all("." not in command for command in commands),
                        "commands install under the name their own help text prints")

    def test_commands_require_user_scope(self):
        result, _, err = self.run_cli(
            "--harness", "codex", "--scope", "project", "--component", "commands", "--apply")
        self.assertEqual(result, 1)
        self.assertIn("PATH is a property of the account", err)
        self.assertFalse((self.root / ".local/bin").exists())

    def test_commands_and_scripts_reach_separate_roots(self):
        """The same script is a named command on PATH and a path the agent reads."""
        result, _, err = self.run_cli(
            "--harness", "codex", "--scope", "user", "--component", "commands",
            "--component", "scripts", "--apply")
        self.assertEqual((result, err), (0, ""))
        source = REPO / "harnesses/codex/scripts/codex-code-session-resume.py"
        self.assertEqual((self.root / ".local/bin/codex-code-session-resume").resolve(), source)
        self.assertEqual((self.root / ".agents/scripts/codex-code-session-resume.py").resolve(), source)
        self.assertFalse((self.root / ".local/bin/codex-whats-new").exists())
        self.assertTrue((self.root / ".agents/scripts/codex-whats-new.py").is_symlink())
