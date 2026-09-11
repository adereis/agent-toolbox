"""Session store isolation and resume behavior with synthetic transcripts."""

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
import _session_resume as common

spec = importlib.util.spec_from_file_location(
    "claude_browser", REPO / "harnesses/claude-code/scripts/claude-code-session-resume.py")
claude = importlib.util.module_from_spec(spec)
spec.loader.exec_module(claude)
SID = "11111111-1111-4111-8111-111111111111"


class SessionBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home() / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "demo project"
        self.project.mkdir()
        self.store = self.root / "profile"
        self.directory = self.store / "projects" / "encoded-project"
        self.directory.mkdir(parents=True)
        self.file = self.directory / f"{SID}.jsonl"
        self.records = [{"type": "user", "sessionId": SID, "cwd": str(self.project),
                         "timestamp": "2026-01-01T12:00:00Z", "message": {
                             "role": "user", "content": "Implement the demo"}}]
        self.write_records()

    def write_records(self):
        self.file.write_text("".join(json.dumps(item) + "\n" for item in self.records))

    def run_cli(self, *flags, interactive=False, inputs=()):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
             patch.object(out, "isatty", return_value=interactive), \
             patch("sys.stdin.isatty", return_value=interactive), \
             patch("builtins.input", side_effect=inputs) as prompt:
            result = claude.main(["--claude-dir", str(self.store), "--all", *flags])
        return result, out.getvalue(), err.getvalue(), prompt

    def test_cached_external_paths_do_not_escape_selected_store(self):
        external = self.root / "other-profile.jsonl"
        external.write_text(json.dumps({"type": "custom-title", "customTitle": "OTHER PROFILE"}) + "\n")
        (self.directory / "sessions-index.json").write_text(json.dumps({"entries": [
            {"sessionId": SID, "fullPath": str(external), "modified": "2099-01-01"}]}))
        result, out, _, _ = self.run_cli("--json")
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(out)[0]["fullPath"], str(self.file))
        self.assertNotIn("OTHER PROFILE", out)

    def test_invalid_index_and_partial_rollout_report_fallback(self):
        (self.directory / "sessions-index.json").write_text("{")
        with self.file.open("a") as stream:
            stream.write('{"unfinished":')
        result, out, err, _ = self.run_cli("--json")
        self.assertEqual(result, 0)
        self.assertEqual(len(json.loads(out)), 1)
        self.assertIn("discovering transcript files", err)
        self.assertIn("malformed or incomplete", err)

    def test_custom_title_all_text_blocks_and_successful_edits(self):
        self.records.extend([
            {"type": "custom-title", "customTitle": "Demo title"},
            {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Injected policy"}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": "First part"}, {"type": "text", "text": "Second part"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "edit-ok", "name": "Edit", "input": {"file_path": "ok.py"}},
                {"type": "tool_use", "id": "edit-fail", "name": "Write", "input": {"file_path": "failed.py"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "edit-ok", "content": "done"},
                {"type": "tool_result", "tool_use_id": "edit-fail", "is_error": True, "content": "failed"}]}},
        ])
        self.write_records()
        parsed = claude.parse_session_jsonl(self.file)
        self.assertEqual(parsed["title"], "Demo title")
        self.assertEqual(parsed["user_prompts"], [(1, "Implement the demo"), (2, "First part\nSecond part")])
        self.assertEqual(parsed["files_edited"], ["ok.py"])

    def test_piped_output_never_prompts(self):
        result, out, _, prompt = self.run_cli()
        self.assertEqual(result, 0)
        self.assertIn("Implement the demo", out)
        prompt.assert_not_called()

    def test_missing_project_requires_explicit_override(self):
        self.project.rmdir()
        with patch("os.execvpe") as launch:
            result, _, err, _ = self.run_cli(interactive=True, inputs=[""])
        self.assertEqual(result, 1)
        self.assertIn("--resume-cwd", err)
        launch.assert_not_called()

    def test_unrecognized_confirmation_does_not_launch(self):
        with patch("os.execvpe") as launch:
            result, _, err, _ = self.run_cli(interactive=True, inputs=["", "maybe"])
        self.assertEqual(result, 1)
        self.assertIn("Expected yes or no", err)
        launch.assert_not_called()

    def test_resume_uses_selected_store_and_quoted_directory(self):
        with patch("os.execvpe") as launch, patch("os.chdir") as change:
            result, out, _, _ = self.run_cli(interactive=True, inputs=["", "yes"])
        self.assertEqual(result, 0)
        change.assert_called_once_with(self.project)
        self.assertEqual(launch.call_args.args[1], ["claude", "--resume", SID])
        self.assertEqual(launch.call_args.args[2]["CLAUDE_CONFIG_DIR"], str(self.store))
        self.assertIn("'" + str(self.project) + "'", out)

    def test_invalid_count_is_rejected(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("--count", "0")
        self.assertEqual(caught.exception.code, 2)

    def test_terminal_controls_and_mixed_timestamps(self):
        self.assertEqual(common.safe_text("\x1b[31mred\x1b[0m\x07"), "red")
        self.assertEqual(common.format_duration("2026-01-01T12:00:00", "2026-01-01T12:01:00Z"), "1m")
        with patch.dict(os.environ, {"NO_COLOR": ""}), patch("sys.stdout.isatty", return_value=True):
            self.assertFalse(common._resolve_color("auto"))
