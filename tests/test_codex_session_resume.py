"""Synthetic Codex rollout compatibility and native resume integration."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "codex_browser", REPO / "harnesses/codex/scripts/codex-code-session-resume.py")
codex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codex)
SID = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"


def response(kind, **fields):
    return {"type": "response_item", "payload": {"type": kind, **fields}}


class CodexSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home() / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "demo project"
        self.project.mkdir()
        self.store = self.root / "codex-profile"
        self.sessions = self.store / "sessions/2026/01/01"
        self.sessions.mkdir(parents=True)

    def write_rollout(self, records=(), sid=SID, source="cli", project=None):
        file = self.sessions / f"rollout-2026-01-01T12-00-00-{sid}.jsonl"
        metadata = {"type": "session_meta", "timestamp": "2026-01-01T12:00:00Z", "payload": {
            "id": sid, "cwd": str(project or self.project), "source": source, "git": {"branch": "demo"}}}
        file.write_text("".join(json.dumps(item) + "\n" for item in (metadata, *records)))
        return file

    def run_cli(self, *flags, inputs=(), interactive=False):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
             patch.object(out, "isatty", return_value=interactive), \
             patch("sys.stdin.isatty", return_value=interactive), \
             patch("builtins.input", side_effect=inputs):
            result = codex.main(["--codex-dir", str(self.store), *flags])
        return result, out.getvalue(), err.getvalue()

    def test_title_index_and_exact_project_filter(self):
        self.write_rollout([response("message", role="user", content=[{"type": "input_text", "text": "Demo task"}])])
        self.write_rollout(sid=OTHER, project=self.root / "different project")
        (self.store / "session_index.jsonl").write_text("".join(json.dumps(item) + "\n" for item in (
            {"id": SID, "thread_name": "Old title"}, {"id": SID, "thread_name": "Renamed demo"})))
        result, out, _ = self.run_cli("--project", str(self.project), "--json")
        self.assertEqual(result, 0)
        records = json.loads(out)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "Renamed demo")
        self.assertEqual(records[0]["user_prompts"], [[1, "Demo task"]])

    def test_subagents_are_explicit_and_archived_files_are_excluded(self):
        self.write_rollout()
        self.write_rollout(sid=OTHER, source={"subagent": {"thread_spawn": {}}})
        (self.store / "archived_sessions").mkdir()
        (self.store / "archived_sessions/example.jsonl").write_text("{}\n")
        result, out, _ = self.run_cli("--all", "--json")
        self.assertEqual(result, 0)
        self.assertEqual(len(json.loads(out)), 1)
        result, out, _ = self.run_cli("--all", "--include-subagents", "--json")
        self.assertEqual(len(json.loads(out)), 2)

    def test_duplicate_events_and_injected_context(self):
        file = self.write_rollout([
            {"type": "event_msg", "payload": {"type": "user_message", "message": "Do the demo"}},
            response("message", role="user", content=[
                {"type": "input_text", "text": "# AGENTS.md instructions\nInjected policy"},
                {"type": "input_text", "text": "<environment_context>injected</environment_context>"},
                {"type": "input_text", "text": "Do the demo"}]),
            response("message", role="assistant", content=[{"type": "output_text", "text": "Done"}]),
            response("message", role="user", content=[{"type": "input_text", "text": "Do the demo"}]),
        ])
        self.assertEqual(codex.parse_rollout(file)["user_prompts"], [(1, "Do the demo"), (2, "Do the demo")])

    def test_native_commit_calls_require_matching_output(self):
        file = self.write_rollout([
            response("function_call", name="exec_command", call_id="commit", arguments=json.dumps({"cmd": "git commit -m demo"})),
            response("function_call_output", call_id="commit", output=json.dumps({"exit_code": 0, "output": "[main abc1234] demo\n"})),
            response("function_call", name="exec_command", call_id="read", arguments=json.dumps({"cmd": "git log -1"})),
            response("function_call_output", call_id="read", output="[main deadbee] unrelated"),
        ])
        self.assertEqual(codex.parse_rollout(file)["git_commits"], [("abc1234", "demo")])

    def test_wrapped_calls_are_inspected_without_executing_javascript(self):
        file = self.write_rollout([
            response("custom_tool_call", name="exec", call_id="wrapped", input='text(await tools.exec_command({cmd: "git commit -m demo"}));'),
            response("custom_tool_call_output", call_id="wrapped", output=[{"type": "text", "text": json.dumps({
                "status": "fulfilled", "value": {"exit_code": 0, "output": "[main abc1234] demo\n"}})}]),
        ])
        self.assertEqual(codex.parse_rollout(file)["git_commits"], [("abc1234", "demo")])

    def test_async_shell_completion_is_correlated(self):
        file = self.write_rollout([
            response("function_call", name="exec_command", call_id="start", arguments=json.dumps({"cmd": "git commit -m demo"})),
            response("function_call_output", call_id="start", output=json.dumps({"session_id": 12, "output": ""})),
            response("function_call", name="write_stdin", call_id="finish", arguments=json.dumps({"session_id": 12, "chars": ""})),
            response("function_call_output", call_id="finish", output=json.dumps({"exit_code": 0, "output": "[main abc1234] demo"})),
        ])
        self.assertEqual(codex.parse_rollout(file)["git_commits"], [("abc1234", "demo")])

    def test_patch_changes_require_successful_tool_results(self):
        patch_text = "*** Begin Patch\n*** Add File: demo.py\n+example\n*** End Patch"
        file = self.write_rollout([
            response("custom_tool_call", name="apply_patch", call_id="good", input=patch_text),
            response("custom_tool_call_output", call_id="good", output="Success. Updated the following files:\nA demo.py"),
            response("custom_tool_call", name="apply_patch", call_id="bad", input=patch_text.replace("demo.py", "failed.py")),
            response("custom_tool_call_output", call_id="bad", output={"isError": True, "content": [{"type": "text", "text": "Failed"}]}),
        ])
        self.assertEqual(codex.parse_rollout(file)["files_edited"], ["demo.py"])

    def test_partial_records_do_not_hide_other_sessions(self):
        file = self.write_rollout()
        with file.open("a") as stream:
            stream.write('{"unfinished":')
        result, out, err = self.run_cli("--all", "--json")
        self.assertEqual(result, 0)
        self.assertEqual(len(json.loads(out)), 1)
        self.assertIn("malformed or incomplete", err)

    def test_resume_preserves_selected_store_profile_and_cwd(self):
        self.write_rollout()
        with patch("os.execvpe") as launch, patch("os.chdir") as change:
            result, _, _ = self.run_cli("--all", "--profile", "demo", interactive=True, inputs=["", "y"])
        self.assertEqual(result, 0)
        change.assert_called_once_with(self.project)
        self.assertEqual(launch.call_args.args[1], ["codex", "resume", SID, "--profile", "demo"])
        self.assertEqual(launch.call_args.args[2]["CODEX_HOME"], str(self.store))

    def test_separate_stores_do_not_share_titles_or_transcripts(self):
        self.write_rollout()
        other_store = self.root / "other-store"
        other_store.mkdir()
        (other_store / "session_index.jsonl").write_text(json.dumps({"id": SID, "thread_name": "OTHER STORE"}) + "\n")
        with patch.dict(os.environ, {"CODEX_HOME": str(other_store)}):
            result, out, _ = self.run_cli("--all", "--json")
        self.assertEqual(result, 0)
        self.assertNotIn("OTHER STORE", out)
