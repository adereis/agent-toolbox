"""Codex archive completeness, configuration evidence, and scoped baselines."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "harnesses/codex"))
import _release_digest as adapter
import _whats_new as core

spec = importlib.util.spec_from_file_location("codex_whats_new", REPO / "harnesses/codex/scripts/codex-whats-new.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def release(version="0.154.0", body="## New Features\n- Added `/widget`\n", **extra):
    return {"tag_name": f"rust-v{version}", "body": body,
            "published_at": "2026-09-09T22:35:38Z", "draft": False, "prerelease": False, **extra}


ARCHIVE = [
    release(body="## New Features\n- Added `/widget`\n\n## Bug Fixes\n"
                 "- Fixed an ordinary issue\n- Windows: Fixed a path\n- Fixed MCP OAuth refresh\n"),
    release("0.153.4", "## Bug Fixes\n- Fixed status line refresh\n",
            published_at="2026-09-04T23:25:48Z"),
    release("0.153.0", "## New Features\n- Added agents, originally called helpers\n",
            published_at="2026-09-03T01:37:38Z"),
]


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home() / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.codex = self.home / ".codex"
        self.codex.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        self.system = self.root / "system/config.toml"
        for mock in (
            patch.dict(os.environ, {"HOME": str(self.home)}, clear=True),
            patch.object(adapter, "SYSTEM_CONFIG", self.system),
            patch.object(adapter, "running_version", return_value="0.154.0"),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def fingerprint(self, profile=None):
        return adapter.fingerprint(self.codex, self.project, profile)


class ArchiveTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cache = self.root / "cache/releases.json"

    def store(self, versions=None, **extra):
        core.write_json(self.cache, {
            "schema": 1, "complete": True, "source": adapter.RELEASES_URL,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "releases": adapter.parse_releases(versions or ARCHIVE), **extra,
        })

    def test_selects_only_stable_cli_not_sdk_or_prereleases(self):
        data = [release("0.99.0"), release(), release("0.155.0-alpha.1"),
                release("0.156.0", prerelease=True), release("0.157.0", draft=True),
                release(tag_name="python-v0.154.0"), release(tag_name="voice-cygwin-snapshot")]
        result = adapter.validate_releases(adapter.parse_releases(data))
        self.assertEqual([r["version"] for r in result], ["0.154.0", "0.99.0"])

    def test_preserves_prose_nested_and_wrapped_entries_and_sections(self):
        body = "A migration note.\n\n## New Features\n- Added the widget\n  with a flag\n  - nested detail\n## Changelog\n* Fixed a thing\n"
        result = adapter.entries(body)
        self.assertEqual([b["text"] for b in result],
                         ["A migration note.", "Added the widget with a flag - nested detail", "Fixed a thing"])
        self.assertEqual([b["section"] for b in result], ["", "New Features", "Changelog"])

    def test_follows_all_pages_before_writing_complete_cache(self):
        first = [release(), *[release(tag_name=f"ignored-{i}") for i in range(99)]]
        second = [release("0.153.0")]
        with patch.object(adapter, "fetch_page", side_effect=[(first, "next-page"), (second, None)]) as fetch:
            result, source, notices = adapter.load_releases(self.cache)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[1].args[0], "next-page")
        self.assertEqual(len(result), 2)
        self.assertEqual(source, adapter.RELEASES_URL)
        self.assertEqual(notices, [])
        self.assertTrue(json.loads(self.cache.read_text())["complete"])
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o600)

    def test_mid_archive_failure_does_not_cache_partial_history(self):
        page = [release(), *[release(tag_name=f"ignored-{i}") for i in range(99)]]
        with patch.object(adapter, "fetch_page", side_effect=[(page, "next-page"), OSError("offline")]):
            with self.assertRaisesRegex(ValueError, "complete release archive"):
                adapter.load_releases(self.cache)
        self.assertFalse(self.cache.exists())

    def test_failed_refresh_keeps_previous_complete_cache_and_reports_it(self):
        self.store()
        before = self.cache.read_bytes()
        with patch.object(adapter, "fetch_page", side_effect=OSError("rate limited")), \
             contextlib.redirect_stderr(io.StringIO()) as err:
            result, source, notices = adapter.load_releases(self.cache, refresh=True)
        self.assertEqual(len(result), 3)
        self.assertIn("stale cache", source)
        self.assertIn("rate limited", err.getvalue())
        self.assertTrue(notices)
        self.assertEqual(before, self.cache.read_bytes())

    def test_fresh_cache_avoids_network(self):
        self.store()
        with patch.object(adapter, "fetch_page", side_effect=AssertionError("unexpected network")):
            self.assertEqual(len(adapter.load_releases(self.cache, required="0.154.0")[0]), 3)

    def test_missing_installed_release_refreshes_even_a_recent_cache(self):
        self.store([release("0.153.0")])
        with patch.object(adapter, "fetch_page", return_value=(ARCHIVE, None)) as fetch:
            result, _, _ = adapter.load_releases(self.cache, required="0.154.0")
        fetch.assert_called_once()
        self.assertEqual(result[0]["version"], "0.154.0")

    def test_old_cache_refreshes_when_installed_version_is_unchanged(self):
        self.store(fetched_at="2020-01-01T00:00:00Z")
        with patch.object(adapter, "fetch_page", return_value=(ARCHIVE, None)) as fetch:
            adapter.load_releases(self.cache, required="0.154.0")
        fetch.assert_called_once()

    def test_offline_always_labels_snapshot_and_never_fetches(self):
        self.store()
        with patch.object(adapter, "fetch_page", side_effect=AssertionError("unexpected network")), \
             contextlib.redirect_stderr(io.StringIO()):
            _, source, notices = adapter.load_releases(self.cache, offline=True)
        self.assertIn("offline", source)
        self.assertTrue(notices)

    def test_offline_missing_or_incomplete_cache_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "--changelog"):
            adapter.load_releases(self.cache, offline=True)
        self.store(complete=False)
        with self.assertRaisesRegex(ValueError, "--changelog"), contextlib.redirect_stderr(io.StringIO()):
            adapter.load_releases(self.cache, offline=True)

    def test_api_error_and_invalid_metadata_fail_loudly(self):
        for payload in ({"message": "rate limited"}, [release(published_at=None)], [release(body=None)]):
            with self.subTest(payload=payload), patch.object(adapter, "fetch_page", return_value=(payload, None)):
                with self.assertRaises(ValueError):
                    adapter.load_releases(self.cache)
        self.assertFalse(self.cache.exists())

    def test_duplicate_release_at_a_moving_page_boundary_is_refused(self):
        with patch.object(adapter, "fetch_page", return_value=([release(), release()], None)):
            with self.assertRaisesRegex(ValueError, "Duplicate release"):
                adapter.load_releases(self.cache)

    def test_cursor_history_can_cross_the_rest_thousand_record_limit(self):
        pages = [([release(tag_name=f"preview-{page}-{i}") for i in range(100)], f"cursor-{page}")
                 for page in range(10)]
        pages.append(([release("0.1.0")], None))
        with patch.object(adapter, "fetch_page", side_effect=pages) as fetch:
            result, _, _ = adapter.load_releases(self.cache)
        self.assertEqual(fetch.call_count, 11)
        self.assertEqual(result[0]["version"], "0.1.0")

    def test_repeated_cursor_cannot_produce_an_incomplete_cache(self):
        with patch.object(adapter, "fetch_page", return_value=([release(tag_name="preview")], "same")):
            with self.assertRaisesRegex(ValueError, "Repeated release cursor"):
                adapter.load_releases(self.cache)
        self.assertFalse(self.cache.exists())

    def test_graphql_maps_fields_and_uses_explicit_public_host(self):
        payload = {"data": {"repository": {"releases": {
            "nodes": [{"tagName": "rust-v0.154.0", "isPrerelease": False, "isDraft": False,
                       "publishedAt": "2026-09-09T22:35:38Z", "description": "- Fixed widgets"}],
            "pageInfo": {"hasNextPage": True, "endCursor": "next"},
        }}}}
        response = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with patch.object(adapter.subprocess, "run", return_value=response) as run:
            releases, cursor = adapter.fetch_page("previous")
        self.assertEqual(cursor, "next")
        self.assertEqual(releases[0]["tag_name"], "rust-v0.154.0")
        command = run.call_args.args[0]
        self.assertIn("cursor=previous", command)
        self.assertEqual(command[command.index("--hostname") + 1], "github.com")

    def test_missing_gh_and_auth_failure_name_recovery_commands(self):
        with patch.object(adapter.subprocess, "run", side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(ValueError, "sudo dnf install gh"):
                adapter.fetch_page()
        response = subprocess.CompletedProcess([], 1, "", "fictitious-secret-diagnostic")
        with patch.object(adapter.subprocess, "run", return_value=response):
            with self.assertRaises(ValueError) as error:
                adapter.fetch_page()
        self.assertIn("gh auth login", str(error.exception))
        self.assertNotIn("fictitious-secret", str(error.exception))

    def test_partial_graphql_error_and_missing_cursor_fail(self):
        bad_connection = {"data": {"repository": {"releases": {
            "nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": None}}}}}
        for payload in ({"errors": [{"message": "partial query failure"}]}, bad_connection):
            response = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
            with patch.object(adapter.subprocess, "run", return_value=response):
                with self.assertRaisesRegex(ValueError, "Invalid GitHub release response"):
                    adapter.fetch_page()


class FingerprintTests(IsolatedTest):
    def test_layers_merge_in_precedence_order_with_separate_profiles(self):
        self.write(self.system, 'model = "system-model"\n[features]\nhooks = true\nmemories = true\n')
        self.write(self.codex / "config.toml", 'model = "base-model"\n[features]\nmemories = false\n')
        self.write(self.codex / "api.config.toml", 'model = "profile-model"\nmodel_provider = "fictitious-api"\n')
        marks = self.fingerprint("api")
        self.assertEqual(marks["settings"]["model"], "profile-model")
        self.assertEqual(marks["features"], {"hooks": True, "memories": False})
        self.assertEqual(marks["profile"], "api")

    def test_trusted_project_layers_override_profile_from_root_to_cwd(self):
        root = self.project
        (root / ".git").mkdir()
        self.project = root / "nested"
        self.project.mkdir()
        self.write(self.codex / "config.toml", f'[projects.{json.dumps(str(root))}]\ntrust_level = "trusted"\n')
        self.write(self.codex / "api.config.toml", 'model = "profile-model"\n')
        self.write(root / ".codex/config.toml", 'model = "root-model"\n[features]\nmemories = true\n')
        self.write(self.project / ".codex/config.toml", 'model = "nested-model"\n')
        marks = self.fingerprint("api")
        self.assertEqual(marks["settings"]["model"], "nested-model")
        self.assertTrue(marks["features"]["memories"])
        self.assertEqual(marks["project_trust"], "trusted")

    def test_untrusted_project_cannot_authorize_itself(self):
        self.write(self.project / ".codex/config.toml",
                   f'model = "must-not-load"\n[projects.{json.dumps(str(self.project))}]\ntrust_level = "trusted"\n')
        marks = self.fingerprint()
        self.assertNotIn("model", marks["settings"])
        self.assertIn("skipped", " ".join(marks["notices"]))

    def test_nearer_untrusted_decision_wins(self):
        root = self.project
        (root / ".git").mkdir()
        self.project = root / "nested"
        self.project.mkdir()
        self.write(self.codex / "config.toml",
                   f'[projects.{json.dumps(str(root))}]\ntrust_level = "trusted"\n'
                   f'[projects.{json.dumps(str(self.project))}]\ntrust_level = "untrusted"\n')
        self.write(root / ".codex/config.toml", 'model = "must-not-load"\n')
        self.assertNotIn("model", self.fingerprint()["settings"])

    def test_profile_cannot_mutate_the_base_trust_inventory(self):
        project_key = json.dumps(str(self.project))
        self.write(self.codex / "config.toml", f'[projects.{project_key}]\ntrust_level = "untrusted"\n')
        self.write(self.codex / "api.config.toml", f'[projects.{project_key}]\ntrust_level = "trusted"\n')
        self.write(self.project / ".codex/config.toml", 'model = "must-not-load"\n')
        marks = self.fingerprint("api")
        self.assertEqual(marks["project_trust"], "untrusted")
        self.assertNotIn("model", marks["settings"])

    def test_malformed_server_and_plugin_entries_fail_instead_of_disappearing(self):
        for text in ('[mcp_servers]\nexample = false\n', '[plugins.example]\nenabled = "yes"\n'):
            with self.subTest(text=text):
                self.write(self.codex / "config.toml", text)
                with self.assertRaisesRegex(ValueError, "boolean enabled"):
                    self.fingerprint()

    def test_hook_sources_accumulate_without_exposing_commands(self):
        self.write(self.system, '[hooks]\nSessionStart = []\n')
        self.write(self.codex / "config.toml", '[hooks]\nPreCompact = []\n')
        self.write(self.codex / "hooks.json", json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "fictitious-secret-matcher", "hooks": [{"command": "fictitious-secret-command"}]}]}}))
        marks = self.fingerprint()
        self.assertEqual(marks["hooks"], ["PreCompact", "PreToolUse", "SessionStart"])
        self.assertNotIn("fictitious-secret", json.dumps(marks))

    def test_credentials_and_arbitrary_values_never_reach_the_fingerprint(self):
        self.write(self.codex / "config.toml", '''
[mcp_servers.example]
command = "fictitious-mcp-command"
args = ["fictitious-secret-argument"]
[mcp_servers.disabled]
enabled = false
[model_providers.example]
base_url = "https://fictitious-secret.example.invalid"
http_headers = { Authorization = "fictitious-secret-header" }
[plugins."example@catalog"]
enabled = true
[plugins."disabled@catalog"]
enabled = false
''')
        self.write(self.codex / "auth.json", "broken fictitious-secret-auth")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fictitious-secret-env"}):
            marks = self.fingerprint()
        self.assertEqual(marks["mcp"], ["example"])
        self.assertEqual(marks["plugins"], ["example@catalog"])
        self.assertIn("OPENAI_API_KEY", marks["env"])
        self.assertNotIn("fictitious-secret", json.dumps(marks))
        self.assertNotIn("fictitious-mcp-command", json.dumps(marks))

    def test_malformed_config_fails_without_echoing_sensitive_source(self):
        self.write(self.codex / "config.toml", 'x = "fictitious-secret" trailing-invalid')
        with self.assertRaises(ValueError) as error:
            self.fingerprint()
        self.assertIn("config.toml", str(error.exception))
        self.assertNotIn("fictitious-secret", str(error.exception))

    def test_profiles_require_valid_names_and_existing_files(self):
        for name in ("../outside", "not-installed"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.fingerprint(name)

    def test_legacy_profile_selector_is_not_applied(self):
        self.write(self.codex / "config.toml", 'profile = "old"\n[profiles.old]\nmodel = "legacy-model"\n')
        marks = self.fingerprint()
        self.assertIsNone(marks["profile"])
        self.assertNotIn("model", marks["settings"])
        self.assertIn("Legacy", " ".join(marks["notices"]))

    def test_native_and_compatibility_skill_locations_are_inventoried(self):
        for path in (self.home / ".agents/skills/first/SKILL.md", self.codex / "skills/second/SKILL.md"):
            self.write(path, "fictitious skill")
        self.assertEqual(self.fingerprint()["skills"], ["first", "second"])

    def test_terminal_identity_survives_a_term_override(self):
        with patch.dict(os.environ, {"KITTY_WINDOW_ID": "42", "TERM": "xterm-256color", "TMUX": "fictitious-socket"}):
            marks = self.fingerprint()
        self.assertEqual(marks["terminal"], "kitty")
        self.assertTrue(marks["term_disagrees"])
        self.assertEqual(marks["multiplexer"], "tmux")


class CorrelationTests(IsolatedTest):
    def tags(self, text, marks, section="Bug Fixes"):
        tagged, _ = adapter.digest([{"version": "0.154.0", "bullets": [{"text": text, "section": section}]}], marks)
        return tagged[0]["bullets"][0]["tags"]

    def test_mcp_signal_needs_a_configured_enabled_server(self):
        self.assertNotIn("mcp", self.tags("Fixed MCP refresh", self.fingerprint()))
        self.write(self.codex / "config.toml", '[mcp_servers.example]\ncommand = "example"\n')
        self.assertIn("mcp", self.tags("Fixed MCP refresh", self.fingerprint()))

    def test_disabled_hooks_and_features_do_not_claim_activation(self):
        self.write(self.codex / "config.toml", '[features]\nhooks = false\nmemories = false\n[hooks]\nPreCompact = []\n')
        tags = self.tags("Fixed hooks and memory", self.fingerprint())
        self.assertNotIn("hooks", tags)
        self.assertNotIn("memory", tags)

    def test_new_features_settings_commands_and_breaking_changes_survive_relevance_filter(self):
        marks = self.fingerprint()
        for text, section, tag in (("A brand new capability", "New Features", "new-feature"),
                                   ("Added the `widget_mode` setting", "Changelog", "new-setting"),
                                   ("Added `/widget`", "Changelog", "new-command"),
                                   ("The deprecated entry point is no longer supported", "Chores", "behavior-change")):
            with self.subTest(text=text):
                self.assertIn(tag, self.tags(text, marks, section))

    def test_only_explicit_platform_ownership_is_filtered(self):
        marks = self.fingerprint()
        self.assertIsNotNone(adapter.excluded("Windows: Fixed a path", marks))
        for text in ("Fixed Windows and Linux paths", "Fixed kitty and Windows terminals", "Linux: Fixed a path"):
            self.assertIsNone(adapter.excluded(text, marks))
        tagged, dropped = adapter.digest(adapter.parse_releases(ARCHIVE), marks, filtering=False)
        self.assertEqual(dropped, {})
        self.assertEqual(len(tagged[0]["bullets"]), 4)


class CommandTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.archive = self.root / "releases.json"
        self.archive.write_text(json.dumps(ARCHIVE))
        self.state = self.root / "digest-state"  # Extension is deliberately absent.

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--changelog", str(self.archive), "--state", str(self.state),
                "--codex-dir", str(self.codex), "--project", str(self.project), *args]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as exit:
                code = exit.code
        return code, out.getvalue(), err.getvalue()

    def report(self, *args):
        code, out, err = self.run_cli("--json", *args)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_first_run_does_not_create_state_and_counts_every_entry(self):
        report = self.report()
        self.assertIsNone(report["baseline"])
        self.assertEqual(report["window"]["count"], 3)
        self.assertEqual(report["counts"], {"total": 6, "withheld": 1, "unmatched": 3, "hidden_unmatched": 0})
        self.assertFalse(self.state.exists())
        self.assertFalse(Path(str(self.state) + ".lock").exists())

    def test_relevant_only_applies_to_json_and_text_without_losing_counts(self):
        report = self.report("--relevant-only")
        self.assertEqual(report["counts"]["hidden_unmatched"], 3)
        self.assertTrue(all(b["tags"] for r in report["releases"] for b in r["bullets"]))
        _, text, _ = self.run_cli("--relevant-only")
        self.assertIn("Withheld: 1", text)
        self.assertIn("Unmatched: 3", text)
        self.assertNotIn("Fixed an ordinary issue", text)

    def test_committed_baseline_makes_next_window_empty_without_claiming_update_status(self):
        self.report("--commit", "--through", "0.154.0")
        state = json.loads(self.state.read_text())
        self.assertEqual(state["baseline"]["release"], "0.154.0")
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.report()["window"]["count"], 0)
        _, out, _ = self.run_cli()
        self.assertIn("not an update check", out)
        self.assertNotIn("is current", out)

    def test_through_pins_commit_even_when_newer_release_exists(self):
        self.report("--since", "0.153.0", "--through", "0.153.4", "--commit")
        self.assertEqual(json.loads(self.state.read_text())["baseline"]["release"], "0.153.4")
        self.assertEqual(self.report()["window"]["to"], "0.154.0")

    def test_baseline_never_regresses_or_duplicates_same_release(self):
        self.report("--commit")
        before = self.state.read_bytes()
        self.report("--releases", "3", "--commit")
        self.assertEqual(self.state.read_bytes(), before)
        code, _, err = self.run_cli("--releases", "1", "--through", "0.153.0", "--commit")
        self.assertEqual(code, 1)
        self.assertIn("backward", err)
        self.assertEqual(self.state.read_bytes(), before)

    def test_refused_window_does_not_advance_baseline(self):
        code, _, err = self.run_cli("--max-releases", "1", "--commit")
        self.assertEqual(code, 1)
        self.assertIn("--relevant-only", err)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.report("--max-releases", "1", "--relevant-only")["window"]["count"], 3)

    def test_topics_are_oldest_first_with_alternative_terms_and_no_state(self):
        report = self.report("--topic", "helpers", "--topic", "widget", "--limit", "0")
        self.assertEqual([h["version"] for h in report["matches"]], ["0.153.0", "0.154.0"])
        self.assertEqual(report["first_match"], "0.153.0")
        self.assertFalse(self.state.exists())

    def test_topic_limit_reports_hidden_history_and_ignores_platform_filters(self):
        report = self.report("--topic", "Fixed", "--limit", "1")
        self.assertEqual(report["total_matches"], 4)
        self.assertEqual(len(report["matches"]), 1)
        self.assertEqual(self.report("--topic", "Windows")["total_matches"], 1)

    def test_topic_commit_and_invalid_arguments_are_rejected_before_work(self):
        for args in (("--topic", "widget", "--commit"), ("--topic", "["), ("--releases", "0"),
                     ("--days", "-1"), ("--months", "0"), ("--limit", "-1"),
                     ("--offline", "--refresh"), ("--since", "bad")):
            with self.subTest(args=args):
                code, _, _ = self.run_cli(*args)
                self.assertEqual(code, 2)
        self.assertFalse(self.state.exists())

    def test_date_window_uses_release_dates_without_external_date_fetch(self):
        dates = [release("0.154.0", published_at=datetime.now(timezone.utc).isoformat()),
                 release("0.100.0", published_at="2020-01-01T00:00:00Z")]
        self.archive.write_text(json.dumps(dates))
        self.assertEqual(self.report("--days", "1")["window"]["count"], 1)

    def test_unknown_through_version_is_rejected(self):
        code, _, err = self.run_cli("--through", "0.999.0", "--commit")
        self.assertEqual(code, 1)
        self.assertIn("absent", err)
        self.assertFalse(self.state.exists())

    def test_explicit_state_file_cannot_be_reused_across_profiles_or_projects(self):
        self.report("--commit")
        before = self.state.read_bytes()
        self.write(self.codex / "api.config.toml", 'model_provider = "fictitious-api"\n')
        other_project = self.root / "another-project"
        other_project.mkdir()
        for args in (("--profile", "api"), ("--project", str(other_project)), ("--codex-dir", str(self.root / "other-home"))):
            with self.subTest(args=args):
                code, _, err = self.run_cli(*args, "--commit")
                self.assertEqual(code, 1)
                self.assertIn("scope", err)
        self.assertEqual(before, self.state.read_bytes())

    def test_default_paths_are_isolated_for_every_configuration_scope(self):
        marks = self.fingerprint()
        scope = adapter.scope_for(marks)
        paths = {adapter.baseline_path(scope)}
        for key in scope:
            paths.add(adapter.baseline_path({**scope, key: "different"}))
        self.assertEqual(len(paths), 4)

    def test_corrupt_state_is_not_overwritten(self):
        self.state.write_text("broken state")
        code, _, err = self.run_cli("--commit")
        self.assertEqual(code, 1)
        self.assertIn("baseline", err)
        self.assertEqual(self.state.read_text(), "broken state")

    def test_failed_output_does_not_consume_releases(self):
        with patch.object(cli, "emit", side_effect=BrokenPipeError("closed output")):
            code, _, _ = self.run_cli("--commit")
        self.assertEqual(code, 1)
        self.assertFalse(self.state.exists())

    def test_baseline_lock_excludes_other_processes(self):
        lock = str(self.state) + ".lock"
        script = "import fcntl,sys\nf=open(sys.argv[1], 'r+')\ntry: fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError: sys.exit(23)\n"
        with cli.baseline_lock(self.state):
            blocked = subprocess.run([sys.executable, "-c", script, lock], capture_output=True)
        unblocked = subprocess.run([sys.executable, "-c", script, lock], capture_output=True)
        self.assertEqual(blocked.returncode, 23, blocked.stderr)
        self.assertEqual(unblocked.returncode, 0, unblocked.stderr)

    def test_terminal_control_sequences_are_removed_from_text_output(self):
        self.archive.write_text(json.dumps([release(body="- Fixed \x1b[31mcolor\x1b[0m\x07 injection")]))
        code, out, err = self.run_cli()
        self.assertEqual(code, 0, err)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)
        self.assertIn("color", out)

    def test_unsupported_platform_has_a_concrete_fallback(self):
        with patch.object(cli.sys, "platform", "darwin"):
            code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("open https://github.com/openai/codex/releases", err)


if __name__ == "__main__":
    unittest.main()
