"""Tests for the Antigravity (agy) release digest utility."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "harnesses/agy/scripts"))
import _whats_new as core

spec = importlib.util.spec_from_file_location("agy_whats_new", REPO / "harnesses/agy/scripts/agy-whats-new.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

SAMPLE_CHANGELOG = """
1.4.2:
· Fixed conversation history not showing in Remote Control in daemon mode.
· Windows: Fixed path separator issue in terminal sandbox.

1.4.1:
· Improved `agy plugin validate` to also check skills, subagents, and rules.
· Improved the inline diff preview with syntax highlighting.
· Improved CPU usage and animated status line.
· Fixed `Enable Telemetry` in `/config` remaining editable.
· Fixed socket disconnect errors.
· macOS: Fixed menu shortcut in window bar.

1.4.0:
· Added terminal status reporting over OSC 7501.
· Added the `/compact` command to compact the conversation.
· Added Auto mode, which approves file edits and safe commands without asking.

1.3.0:
· Added `agy mcp` command to manage MCP servers.
· Fixed hooks.json loading in project root.
"""


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        tmp_dir = Path.home() / "tmp" if (Path.home() / "tmp").is_dir() else None
        self.temp = tempfile.TemporaryDirectory(dir=tmp_dir)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.agy_dir = self.home / ".gemini/antigravity-cli"
        self.agy_dir.mkdir(parents=True)
        self.config_dir = self.home / ".gemini/config"
        self.config_dir.mkdir(parents=True)
        self.project = self.root / "project"
        self.project.mkdir()

        self.changelog_file = self.root / "changelog.txt"
        self.changelog_file.write_text(SAMPLE_CHANGELOG, encoding="utf-8")

        for mock in (
            patch.dict(os.environ, {"HOME": str(self.home)}, clear=False),
            patch.object(cli, "running_version", return_value="1.4.2"),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class ChangelogParserTests(unittest.TestCase):
    def test_parses_agy_format_and_markdown_format(self):
        text = """
1.2.0:
· First bullet
· Second bullet with
  continuation line

## 1.1.0
- Markdown bullet 1
* Markdown bullet 2
"""
        releases = cli.parse_agy_changelog(text)
        self.assertEqual(len(releases), 2)
        self.assertEqual(releases[0]["version"], "1.2.0")
        self.assertEqual(releases[0]["bullets"], [
            "First bullet",
            "Second bullet with continuation line"
        ])
        self.assertEqual(releases[1]["version"], "1.1.0")
        self.assertEqual(releases[1]["bullets"], [
            "Markdown bullet 1",
            "Markdown bullet 2"
        ])


class FilteringAndTaggingTests(IsolatedTest):
    def test_withholds_foreign_platforms(self):
        releases = cli.parse_agy_changelog(SAMPLE_CHANGELOG)
        marks = {
            "platform": "linux",
            "terminal": "kitty",
            "mode": "auto",
            "sandbox": True,
            "plugins": ["science"],
            "skills": ["custom-skill"],
            "rules": ["AGENTS.md"],
            "hooks": [],
            "mcp": [],
            "agents": [],
            "telemetry": True,
            "artifacts": True,
            "remote_control": False,
            "statusline": True,
            "git": True,
        }
        tagged, withheld, reasons, unmatched = cli.tag_bullets(releases, marks, relevant_only=False, no_filter=False)
        # Windows bullet in 1.4.2 and macOS bullet in 1.4.1 should be withheld on Linux
        self.assertEqual(withheld, 2)
        self.assertIn("not this platform", reasons)

    def test_tags_matching_signals(self):
        releases = cli.parse_agy_changelog(SAMPLE_CHANGELOG)
        marks = {
            "platform": "linux",
            "terminal": "kitty",
            "mode": "auto",
            "sandbox": True,
            "plugins": ["science"],
            "skills": ["custom-skill"],
            "rules": ["AGENTS.md"],
            "hooks": ["my-hook"],
            "mcp": ["sqlite"],
            "agents": [],
            "telemetry": True,
            "artifacts": True,
            "remote_control": False,
            "statusline": True,
            "git": True,
        }
        tagged, withheld, reasons, unmatched = cli.tag_bullets(releases, marks)
        rel_141 = next(r for r in tagged if r["version"] == "1.4.1")
        plugin_bullet = next(b for b in rel_141["bullets"] if "plugin validate" in b["bullet"])
        self.assertIn("plugins", plugin_bullet["tags"])
        self.assertIn("skills", plugin_bullet["tags"])
        self.assertIn("rules", plugin_bullet["tags"])

        rel_140 = next(r for r in tagged if r["version"] == "1.4.0")
        auto_bullet = next(b for b in rel_140["bullets"] if "Auto mode" in b["bullet"])
        self.assertIn("auto-mode", auto_bullet["tags"])


class FingerprintTests(IsolatedTest):
    def test_fingerprints_settings_and_customizations(self):
        self.write_json(self.config_dir / "settings.json", {
            "agentMode": "auto",
            "model": "gemini-pro",
            "notifications": True,
        })
        self.write_json(self.config_dir / "mcp_config.json", {
            "mcpServers": {"local-db": {"command": "db-server"}}
        })
        (self.project / "AGENTS.md").write_text("# Agents rule", encoding="utf-8")
        (self.project / ".git").mkdir()

        marks = cli.fingerprint(self.agy_dir, self.config_dir, self.project)
        self.assertEqual(marks["mode"], "auto")
        self.assertEqual(marks["model"], "gemini-pro")
        self.assertTrue(marks["notifications"])
        self.assertIn("local-db", marks["mcp"])
        self.assertIn("AGENTS.md", marks["rules"])
        self.assertTrue(marks["git"])


class CommandTests(IsolatedTest):
    def test_runs_topic_search(self):
        out = io.StringIO()
        with patch("sys.stdout", out):
            cli.main([
                "--changelog", str(self.changelog_file),
                "--project", str(self.project),
                "--topic", "compact",
            ])
        output = out.getvalue()
        self.assertIn("# Topic matches for: compact", output)
        self.assertIn("[1.4.0] Added the `/compact` command", output)

    def test_runs_window_and_records_commit(self):
        state_path_file = self.root / "state.json"
        out = io.StringIO()
        with patch("sys.stdout", out):
            cli.main([
                "--changelog", str(self.changelog_file),
                "--project", str(self.project),
                "--state", str(state_path_file),
                "--releases", "2",
                "--commit",
            ])
        output = out.getvalue()
        self.assertIn("# Baseline advanced to 1.4.2", output)
        self.assertIn("## Environment", output)
        self.assertIn("## 1.4.2", output)
        self.assertIn("## 1.4.1", output)

        # Baseline file should be saved
        saved = json.loads(state_path_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["baseline"]["release"], "1.4.2")

        # Second run with no args should now pick up the baseline
        out2 = io.StringIO()
        with patch("sys.stdout", out2):
            cli.main([
                "--changelog", str(self.changelog_file),
                "--project", str(self.project),
                "--state", str(state_path_file),
            ])
        output2 = out2.getvalue()
        # Since baseline was 1.4.2 and newest is 1.4.2, window since baseline is empty
        self.assertIn("## Environment", output2)
        self.assertNotIn("## 1.4.2", output2)

    def test_relevant_only_filters_unmatched(self):
        out = io.StringIO()
        with patch("sys.stdout", out):
            cli.main([
                "--changelog", str(self.changelog_file),
                "--project", str(self.project),
                "--releases", "2",
                "--relevant-only",
                "--json",
            ])
        data = json.loads(out.getvalue())
        self.assertGreater(data["unmatched"], 0)
        # All returned bullets in releases must have non-empty tags
        for rel in data["releases"]:
            for b in rel["bullets"]:
                self.assertTrue(len(b["tags"]) > 0)

    def test_through_pins_window_ceiling(self):
        out = io.StringIO()
        with patch("sys.stdout", out):
            cli.main([
                "--changelog", str(self.changelog_file),
                "--project", str(self.project),
                "--through", "1.4.1",
                "--releases", "5",
                "--json",
            ])
        data = json.loads(out.getvalue())
        versions = [r["version"] for r in data["releases"]]
        self.assertNotIn("1.4.2", versions)
        self.assertEqual(versions[0], "1.4.1")

    def test_refuses_oversized_window_without_relevant_only(self):
        with self.assertRaises(SystemExit) as ctx:
            cli.main([
                "--changelog", str(self.changelog_file),
                "--project", str(self.project),
                "--max-releases", "2",
                "--releases", "4",
            ])
        self.assertIn("exceeds limit", str(ctx.exception))

    def test_refuses_topic_with_commit(self):
        with self.assertRaises(SystemExit) as ctx:
            cli.main([
                "--changelog", str(self.changelog_file),
                "--project", str(self.project),
                "--topic", "compact",
                "--commit",
            ])
        self.assertIn("Cannot combine --commit with --topic", str(ctx.exception))


class InstallIntegrationTests(IsolatedTest):
    def test_install_catalog_for_agy(self):
        import tools.install as installer
        skills = installer.catalog("agy", ["skills"])
        self.assertIn("skills/whats-new", skills)
        self.assertIn("skills/teach/SKILL.md", skills)
        self.assertIn("skills/convene", skills)

        scripts = installer.catalog("agy", ["scripts"])
        self.assertIn("scripts/agy-whats-new.py", scripts)


if __name__ == "__main__":
    unittest.main()
