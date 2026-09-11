"""Behavioral coverage for opt-in hook examples using fictitious paths."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


EXAMPLES = Path(__file__).resolve().parents[1] / "examples/claude-code/hooks"
spec = importlib.util.spec_from_file_location("directory_hook", EXAMPLES / "block-directory.py")
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class DirectoryHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home() / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.blocked = self.root / "private-data"
        self.blocked.mkdir()

    def event(self, tool="Read", path="private-data/example.txt"):
        field = "path" if tool in ("Glob", "Grep") else "file_path"
        if tool == "NotebookEdit":
            field = "notebook_path"
        return {"tool_name": tool, "cwd": str(self.root), "tool_input": {field: path}}

    def test_direct_tools_block_descendants_and_exact_directory(self):
        for tool in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep"):
            for path in (str(self.blocked), "private-data/example.txt", "public/../private-data/a"):
                with self.subTest(tool=tool, path=path):
                    self.assertIsNotNone(hook.decision(self.event(tool, path), self.blocked))

    def test_prefix_sibling_and_other_paths_are_allowed(self):
        for path in ("private-data-copy/example.txt", "public/example.txt"):
            self.assertIsNone(hook.decision(self.event(path=path), self.blocked))

    def test_existing_symlink_cannot_bypass_directory_check(self):
        (self.root / "alias").symlink_to(self.blocked, target_is_directory=True)
        self.assertIsNotNone(hook.decision(self.event(path="alias/example.txt"), self.blocked))

    def test_recursive_search_cannot_include_blocked_directory(self):
        for tool in ("Glob", "Grep"):
            event = self.event(tool, str(self.root))
            self.assertIsNotNone(hook.decision(event, self.blocked))
            del event["tool_input"]["path"]
            self.assertIsNotNone(hook.decision(event, self.blocked))
        event = self.event("Glob", "public")
        event["tool_input"]["pattern"] = str(self.blocked / "*.txt")
        self.assertIsNotNone(hook.decision(event, self.blocked))

    def test_unrelated_tool_has_no_decision(self):
        self.assertIsNone(hook.decision({"tool_name": "Bash"}, self.blocked))

    def test_json_protocol_and_malformed_input(self):
        command = [sys.executable, str(EXAMPLES / "block-directory.py"),
                   "--blocked-dir", str(self.blocked)]
        result = subprocess.run(command, input=json.dumps(self.event()), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        for value in ("{", "[]", '{"tool_name":[]}'):
            with self.subTest(value=value):
                result = subprocess.run(command, input=value, text=True, capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Invalid hook input", result.stderr)


class ContextHookTests(unittest.TestCase):
    def run_hook(self, event, pattern="(^|/)migrations/", message='Check "rollback".\nThen ordering.'):
        return subprocess.run(
            [sys.executable, str(EXAMPLES / "file-edit-context.py"),
             "--pattern", pattern, "--message", message],
            input=json.dumps(event), text=True, capture_output=True,
        )

    def test_matching_edit_adds_context_without_permission_decision(self):
        result = self.run_hook({"tool_name": "Edit", "tool_input": {"file_path": "migrations/demo.sql"}})
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["additionalContext"], 'Check "rollback".\nThen ordering.')
        self.assertNotIn("permissionDecision", output)

    def test_unmatched_paths_and_read_tools_are_ignored(self):
        for tool, path in (("Edit", "src/demo.py"), ("Read", "migrations/demo.sql")):
            result = self.run_hook({"tool_name": tool, "tool_input": {"file_path": path}})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")

    def test_invalid_configuration_is_reported(self):
        result = self.run_hook({"tool_name": "Edit"}, pattern="[")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Invalid hook input", result.stderr)
