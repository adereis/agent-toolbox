"""Changelog windows, baseline state, and environment correlation."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import _whats_new as core

spec = importlib.util.spec_from_file_location(
    "claude_whats_new", REPO / "harnesses/claude-code/scripts/claude-code-whats-new.py")
digest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(digest)

CHANGELOG = """# Changelog

## 2.1.10

- Added `/widget` for widgets
- Fixed a wrapped entry that continues
  onto a second line
- [VSCode] Fixed something in the editor
- Windows: Fixed a path

## 2.1.9

- Added auto mode, once called auto-accept
- Fixed statusline flicker

## 2.1.2

- Added the first widget
"""


class ChangelogTests(unittest.TestCase):
    def setUp(self):
        self.releases = core.parse_changelog(CHANGELOG)

    def test_releases_are_ordered_numerically_not_lexically(self):
        self.assertEqual([r["version"] for r in self.releases], ["2.1.10", "2.1.9", "2.1.2"])

    def test_wrapped_entry_stays_one_searchable_bullet(self):
        bullets = self.releases[0]["bullets"]
        self.assertIn("Fixed a wrapped entry that continues onto a second line", bullets)
        self.assertEqual(len(bullets), 4)

    def test_preamble_before_the_first_release_is_not_a_bullet(self):
        self.assertEqual(sum(len(r["bullets"]) for r in self.releases), 7)

    def test_since_is_exclusive_of_the_reported_baseline(self):
        window = core.select(self.releases, since="2.1.9")
        self.assertEqual([r["version"] for r in window], ["2.1.10"])

    def test_count_takes_the_newest_releases(self):
        self.assertEqual([r["version"] for r in core.select(self.releases, count=2)],
                         ["2.1.10", "2.1.9"])

    def test_date_window_without_dates_is_an_error_not_an_empty_result(self):
        with self.assertRaises(ValueError):
            core.select(self.releases, not_before=core.parse_timestamp("2026-01-01T00:00:00Z"))

    def test_search_matches_any_pattern_oldest_first(self):
        hits = core.search(self.releases, [r"auto[- ]mode", r"auto[- ]accept", r"widget"])
        self.assertEqual([version for version, _ in hits], ["2.1.2", "2.1.9", "2.1.10"])

    def test_search_reports_no_match_rather_than_guessing(self):
        self.assertEqual(core.search(self.releases, ["nonexistent"]), [])


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home() / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stale = self.root / "stale.md"
        self.stale.write_text("# Changelog\n\n## 2.1.9\n\n- Old\n")

    def quiet(self, *args, **kwargs):
        with contextlib.redirect_stderr(io.StringIO()):
            return core.load_changelog(*args, **kwargs)

    def test_cache_holding_the_running_release_is_used_without_fetching(self):
        fresh = self.root / "fresh.md"
        fresh.write_text(CHANGELOG)
        with patch.object(core, "fetch", side_effect=AssertionError("must not fetch")):
            text, source = core.load_changelog([fresh], "https://example.invalid", required="2.1.10")
        self.assertIn("2.1.10", text)
        self.assertIn("fresh.md", source)

    def test_a_cache_predating_the_running_release_triggers_a_fetch(self):
        mirror = self.root / "mirror.md"
        with patch.object(core, "fetch", return_value=CHANGELOG) as fetched:
            text, source = self.quiet([self.stale], "https://example.invalid",
                                      required="2.1.10", store=mirror)
        fetched.assert_called_once()
        self.assertEqual(source, "https://example.invalid")
        self.assertEqual(mirror.read_text(), CHANGELOG)
        self.assertIn("2.1.10", text)

    def test_the_stored_mirror_prevents_a_second_fetch(self):
        mirror = self.root / "mirror.md"
        mirror.write_text(CHANGELOG)
        with patch.object(core, "fetch", side_effect=AssertionError("must not fetch")):
            _, source = core.load_changelog([self.stale, mirror], "https://example.invalid",
                                            required="2.1.10")
        self.assertIn("mirror.md", source)

    def test_a_failed_fetch_degrades_to_the_stale_cache_and_says_so(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            with patch.object(core, "fetch", side_effect=OSError("no network")):
                text, source = core.load_changelog([self.stale], "https://example.invalid",
                                                   required="2.1.10")
        self.assertIn("Old", text)
        self.assertIn("stale cache", source)
        self.assertIn("no network", errors.getvalue())

    def test_offline_without_any_cache_fails_rather_than_reporting_nothing(self):
        with self.assertRaises(ValueError):
            core.load_changelog([self.root / "absent.md"], "https://example.invalid", offline=True)

    def test_a_source_that_is_not_https_is_refused(self):
        with self.assertRaises(ValueError):
            core.fetch("http://example.invalid/CHANGELOG.md")


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home() / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "nested" / "state.json"

    def test_baselines_accumulate_into_a_capped_history(self):
        state = {}
        for number in range(9):
            state = core.save_state(self.path, f"2.1.{number}", previous=state)
        self.assertEqual(state["baseline"]["release"], "2.1.8")
        self.assertEqual([entry["release"] for entry in state["history"]],
                         ["2.1.7", "2.1.6", "2.1.5", "2.1.4", "2.1.3"])

    def test_state_is_written_privately_and_reloads_unchanged(self):
        core.save_state(self.path, "2.1.10")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(core.load_state(self.path)["baseline"]["release"], "2.1.10")

    def test_a_missing_baseline_is_not_an_error(self):
        self.assertEqual(core.load_state(self.path.parent / "absent.json"), {})

    def test_a_foreign_or_corrupt_baseline_is_reported_and_ignored(self):
        self.path.parent.mkdir(parents=True)
        for content in ('{"version": 99}', "not json"):
            self.path.write_text(content)
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                self.assertEqual(core.load_state(self.path), {})
            self.assertIn(str(self.path), errors.getvalue())

    def test_state_and_cache_follow_the_xdg_variables(self):
        env = {"HOME": "/home/example", "XDG_STATE_HOME": "/state", "XDG_CACHE_HOME": "/cache"}
        self.assertEqual(core.state_path("a.json", env), Path("/state/agent-toolbox/a.json"))
        self.assertEqual(core.cache_path("b.md", env), Path("/cache/agent-toolbox/b.md"))
        self.assertEqual(core.state_path("a.json", {"HOME": "/home/example"}),
                         Path("/home/example/.local/state/agent-toolbox/a.json"))


def marks(**overrides):
    """A fingerprint with everything off, so each test enables what it means."""
    base = {key: False for key in ("statusline", "thinking", "remote_control", "attribution",
                                   "memory", "sessions", "git", "ide", "slack", "windows",
                                   "macos", "notifications", "auto_compact")}
    base.update(platform="linux", version="2.1.10", installed=[], term="", term_program="",
                terminal="", terminal_evidence="TERM", term_disagrees=False, multiplexer="",
                tui="", editor_mode="", theme="", default_mode="", rules={"allow": 0, "deny": 0, "ask": 0},
                model="", effort="", output_style="", hooks=[], plugins=[], mcp=[], skills=[],
                agents=[], otel=[], deployment=[], env=[])
    base.update(overrides)
    return base


class CorrelationTests(unittest.TestCase):
    def test_a_signal_needs_the_matching_configuration(self):
        bullet = "Fixed statusline flicker"
        self.assertEqual(digest.digest([{"version": "1", "bullets": [bullet]}],
                                       marks())[0][0]["bullets"][0]["tags"], [])
        tagged = digest.digest([{"version": "1", "bullets": [bullet]}],
                               marks(statusline=True))[0][0]["bullets"][0]
        self.assertEqual(tagged["tags"], ["statusline"])

    def test_a_new_setting_is_tagged_even_though_nothing_is_configured_for_it(self):
        bullet = "Added `CLAUDE_CODE_NEW_KNOB` to change something"
        tags = digest.digest([{"version": "1", "bullets": [bullet]}],
                             marks())[0][0]["bullets"][0]["tags"]
        self.assertIn("new-setting", tags)

    def test_a_third_party_deployment_is_only_tagged_where_one_is_configured(self):
        bullet = "Changed the system prompt on Bedrock, Vertex and Foundry to use attachments"
        self.assertEqual(digest.digest([{"version": "1", "bullets": [bullet]}],
                                       marks())[0][0]["bullets"][0]["tags"], ["behavior-change"])
        tags = digest.digest([{"version": "1", "bullets": [bullet]}],
                             marks(deployment=["CLAUDE_CODE_USE_VERTEX"]))[0][0]["bullets"][0]["tags"]
        self.assertIn("deployment", tags)

    def test_another_host_is_filtered_only_while_it_is_absent(self):
        self.assertIsNotNone(digest.excluded("[VSCode] Fixed the editor", marks()))
        self.assertIsNone(digest.excluded("[VSCode] Fixed the editor", marks(ide=True)))

    def test_filtering_can_be_turned_off_entirely(self):
        self.assertIsNone(digest.excluded("[VSCode] Fixed the editor", marks(), enabled=False))

    def test_withheld_bullets_are_counted_by_reason(self):
        releases = [{"version": "1", "bullets": ["[VSCode] One", "[VSCode] Two", "Windows: Three",
                                                 "Fixed statusline flicker"]}]
        kept, dropped = digest.digest(releases, marks(statusline=True))
        self.assertEqual(len(kept[0]["bullets"]), 1)
        self.assertEqual(sum(dropped.values()), 3)
        self.assertEqual(len(dropped), 2)


class TerminalTests(unittest.TestCase):
    def test_the_terminal_is_identified_by_its_own_variable_not_by_term(self):
        name, evidence, disagrees = digest.detect_terminal(
            {"TERM": "xterm-256color", "KITTY_WINDOW_ID": "1"})
        self.assertEqual((name, evidence), ("kitty", "KITTY_WINDOW_ID"))
        self.assertTrue(disagrees)

    def test_a_term_that_names_the_terminal_does_not_count_as_disagreeing(self):
        self.assertEqual(digest.detect_terminal({"TERM": "xterm-kitty", "KITTY_PID": "9"}),
                         ("kitty", "KITTY_PID", False))

    def test_term_is_the_fallback_when_no_terminal_announces_itself(self):
        self.assertEqual(digest.detect_terminal({"TERM": "xterm-ghostty"}),
                         ("ghostty", "TERM", False))
        self.assertEqual(digest.detect_terminal({"TERM": "xterm-256color"}),
                         ("xterm", "TERM", False))

    def test_entries_naming_the_detected_terminal_are_tagged(self):
        bullet = "Fixed Ctrl+Z suspend in terminals using Kitty keyboard protocol"
        tags = digest.digest([{"version": "1", "bullets": [bullet]}],
                             marks(terminal="kitty"))[0][0]["bullets"][0]["tags"]
        self.assertIn("term:kitty", tags)
        self.assertNotIn("term:kitty", digest.digest([{"version": "1", "bullets": [bullet]}],
                                                     marks(terminal="konsole"))[0][0]["bullets"][0]["tags"])

    def test_a_multiplexer_is_tagged_separately_from_the_terminal(self):
        bullet = "Fixed notifications not reaching the outer terminal inside tmux"
        tags = digest.digest([{"version": "1", "bullets": [bullet]}],
                             marks(terminal="kitty", multiplexer="tmux"))[0][0]["bullets"][0]["tags"]
        self.assertIn("tmux", tags)


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home() / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.claude = self.home / ".claude"
        (self.claude / "skills").mkdir(parents=True)
        (self.claude / "settings.json").write_text(json.dumps({
            "statusLine": {"type": "command", "command": "x"},
            "permissions": {"defaultMode": "auto", "allow": ["Bash(git:*)", "WebFetch"]},
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]},
            "enabledPlugins": {"on@market": True, "off@market": False},
            "editorMode": "vim",
        }))
        (self.claude / "settings.local.json").write_text(json.dumps(
            {"permissions": {"allow": ["Bash(ls:*)"]}, "outputStyle": "Explanatory"}))
        (self.home / ".claude.json").write_text(json.dumps({"mcpServers": {"notes": {}}}))
        self.project = self.home / "project"
        self.project.mkdir()

    def probe(self, environ=None, project=None):
        with patch.dict(os.environ, environ or {}, clear=True), \
             patch.object(digest, "running_version", return_value=("2.1.10", [])):
            os.environ["HOME"] = str(self.home)
            return digest.fingerprint(self.claude, project or self.project)

    def test_settings_sources_combine_without_one_hiding_another(self):
        found = self.probe()
        self.assertEqual(found["default_mode"], "auto")
        self.assertEqual(found["rules"]["allow"], 3)
        self.assertEqual(found["hooks"], ["PreToolUse[Bash]"])
        self.assertEqual(found["plugins"], ["on@market"])
        self.assertEqual(found["mcp"], ["notes"])
        self.assertEqual(found["output_style"], "Explanatory")
        self.assertTrue(found["statusline"])

    def test_the_home_directory_as_project_counts_user_settings_once(self):
        found = self.probe(project=self.home)
        self.assertEqual(found["rules"]["allow"], 3)
        self.assertEqual(found["hooks"], ["PreToolUse[Bash]"])

    def test_a_project_linked_to_the_user_settings_counts_them_once(self):
        (self.project / ".claude").symlink_to(self.claude)
        found = self.probe()
        self.assertEqual(found["rules"]["allow"], 3)
        self.assertEqual(found["hooks"], ["PreToolUse[Bash]"])

    def test_environment_values_never_appear_only_their_names(self):
        found = self.probe({"ANTHROPIC_API_KEY": "sk-secret-value", "PATH": "/usr/bin"})
        self.assertIn("ANTHROPIC_API_KEY", found["env"])
        self.assertNotIn("sk-secret-value", json.dumps(found))

    def test_rules_are_counted_by_tool_without_their_specifiers(self):
        (self.claude / "settings.local.json").write_text(json.dumps({"permissions": {
            "allow": ["Bash(ls:*)", "mcp__notes__search", "mcp__notes__write(draft)"],
            "deny": ["Read(~/private-example/**)"]}}))
        found = self.probe()
        self.assertEqual(found["rule_tools"]["allow"], {"Bash": 2, "WebFetch": 1, "mcp__notes": 2})
        text = "\n".join(digest.describe(found))
        self.assertIn("5 allow (Bash 2, mcp__notes 2, WebFetch 1), 1 deny (Read 1)", text)
        for specifier in ("git:*", "ls:*", "private-example", "draft"):
            self.assertNotIn(specifier, text)

    def test_a_telemetry_opt_out_is_read_from_the_shell_or_settings_and_settings_win(self):
        found = self.probe()
        self.assertEqual(found["telemetry_off"], [])
        self.assertIn("telemetry=not opted out", "\n".join(digest.describe(found)))

        found = self.probe({"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "true"})
        self.assertIn("telemetry=opted out by CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
                      "\n".join(digest.describe(found)))

        (self.claude / "settings.local.json").write_text(json.dumps({"env": {"DISABLE_TELEMETRY": "1"}}))
        self.assertEqual(self.probe()["telemetry_off"], ["DISABLE_TELEMETRY"])

        (self.claude / "settings.local.json").write_text(json.dumps({"env": {"DISABLE_TELEMETRY": "0"}}))
        self.assertEqual(self.probe({"DISABLE_TELEMETRY": "1"})["telemetry_off"], [])

    def test_variables_a_session_injects_are_not_reported_as_configuration(self):
        found = self.probe({"CLAUDE_CODE_SESSION_ID": "abc", "CLAUDE_PID": "1",
                            "CLAUDE_CODE_USE_VERTEX": "1"})
        self.assertEqual(found["env"], ["CLAUDE_CODE_USE_VERTEX"])

    def test_an_unreadable_settings_file_is_reported_and_skipped(self):
        (self.claude / "settings.local.json").write_text("{ broken")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            found = self.probe()
        self.assertIn("settings.local.json", errors.getvalue())
        self.assertEqual(found["default_mode"], "auto")


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home() / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.changelog = self.root / "CHANGELOG.md"
        self.changelog.write_text(CHANGELOG)
        self.state = self.root / "state.json"
        (self.root / ".claude").mkdir()

    def run_tool(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--changelog", str(self.changelog), "--state", str(self.state),
                "--claude-dir", str(self.root / ".claude"), "--project", str(self.root),
                "--offline", *extra]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
             patch.dict(os.environ, {"HOME": str(self.root)}, clear=True), \
             patch.object(digest, "running_version", return_value=("2.1.10", [])):
            code = digest.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_first_run_says_it_has_no_baseline(self):
        code, out, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertIn("No baseline recorded yet", out)

    def test_committing_advances_the_baseline_so_the_next_run_is_quiet(self):
        self.run_tool("--commit")
        self.assertEqual(core.load_state(self.state)["baseline"]["release"], "2.1.10")
        code, out, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertIn("is current", out)

    def test_a_digest_that_was_not_committed_leaves_no_state(self):
        self.run_tool()
        self.assertFalse(self.state.exists())

    def test_a_topic_search_never_moves_the_baseline(self):
        code, out, _ = self.run_tool("--topic", "auto[- ]accept", "--commit")
        self.assertEqual(code, 0)
        self.assertIn("2.1.9", out)
        self.assertFalse(self.state.exists())

    def test_an_oversized_window_is_refused_with_a_way_forward(self):
        code, _, err = self.run_tool("--releases", "3", "--max-releases", "1")
        self.assertEqual(code, 1)
        self.assertIn("--relevant-only", err)

    def test_relevant_only_lifts_the_limit_and_counts_what_it_hid(self):
        code, out, _ = self.run_tool("--releases", "3", "--max-releases", "1", "--relevant-only")
        self.assertEqual(code, 0)
        self.assertIn("Not shown", out)

    def test_the_unmatched_count_is_printed_not_left_to_the_reader(self):
        _, out, _ = self.run_tool("--releases", "3")
        untagged = sum(line.startswith("[-] ") for line in out.splitlines())
        self.assertGreater(untagged, 0)
        self.assertIn(f"## Unmatched: {untagged} bullet(s)", out)
        self.assertLess(out.index("## Unmatched:"), out.index("[-] "))

        _, hidden, _ = self.run_tool("--releases", "3", "--relevant-only")
        self.assertIn(f"## Unmatched: {untagged} bullet(s)", hidden)
        self.assertNotIn("[-] ", hidden)

        _, raw, _ = self.run_tool("--releases", "3", "--json")
        self.assertEqual(json.loads(raw)["unmatched"], untagged)

    def test_a_date_window_without_dates_explains_the_alternative(self):
        code, _, err = self.run_tool("--days", "30")
        self.assertEqual(code, 1)
        self.assertIn("--releases", err)

    def test_the_digest_states_its_source_and_the_signals_it_used(self):
        _, out, _ = self.run_tool("--releases", "1")
        self.assertIn(f"# Source: {self.changelog}", out)
        self.assertIn("## Signals watched:", out)
        self.assertIn("## Environment", out)


if __name__ == "__main__":
    unittest.main()
