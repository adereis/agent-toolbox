"""The Antigravity adapter against its stub: audited tools, no private home."""

import os
import unittest
from unittest.mock import patch

from convene_support import Sandbox

from convene import harnesses, isolation, plan, round as round_
from convene.isolation import bwrap
from convene.storage import read


class AntigravityTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self)
        (self.box.home / ".gemini").mkdir(exist_ok=True)
        for name in ("oauth_creds.json", "google_accounts.json", "settings.json", "installation_id"):
            (self.box.home / ".gemini" / name).write_text("{}")

    def prepare(self, **fields):
        fields.setdefault("seats", [{"id": "g", "persona": "quinn-t-shun", "harness": "agy",
                                     "model": "gemini-3.8-flash", "effort": "low",
                                     "tools": "write", "isolation": "none"}])
        fields.setdefault("workspace", "none")
        root, frozen = plan.prepare(self.box.plan(**fields), project_root=self.box.project,
                                    range_spec="HEAD~1..HEAD")
        return root, frozen

    def test_resolve_takes_the_effort_variant_and_marks_compaction_detected(self):
        root, frozen = self.prepare()
        seat = frozen["seats"][0]
        self.assertEqual(seat["model"], "gemini-3.8-flash-low")
        self.assertEqual(seat["compaction"], "detected")
        self.assertIsNone(seat["context_window"])
        with self.assertRaisesRegex(ValueError, "does not list 'gemini-9'"):
            self.prepare(seats=[{"id": "g", "persona": "quinn-t-shun", "harness": "agy",
                                 "model": "gemini-9", "effort": "low", "tools": "write",
                                 "isolation": "none"}])

    def test_only_write_tools_and_no_private_home(self):
        with self.assertRaisesRegex(ValueError, "cannot confine a seat to tools = \"read\""):
            self.prepare(seats=[{"id": "g", "persona": "quinn-t-shun", "harness": "agy",
                                 "model": "gemini-3.8-flash-low", "effort": "low",
                                 "isolation": "none"}])
        with self.assertRaisesRegex(ValueError, "no private-home tier.*enforced.*none"):
            self.prepare(seats=[{"id": "g", "persona": "quinn-t-shun", "harness": "agy",
                                 "model": "gemini-3.8-flash-low", "effort": "low",
                                 "tools": "write", "isolation": "private-home"}])
        agy = harnesses.get("agy")
        with patch.object(bwrap.sys, "platform", "darwin"):
            # The strongest tier for agy off Linux is no tier at all, and the
            # receipt's red flag says so.
            self.assertEqual(isolation.resolve("strongest", agy), "none")
            self.assertEqual(isolation.resolve("strongest", harnesses.get("claude")), "private-home")
        with patch.object(bwrap.sys, "platform", "linux"), \
             patch.object(bwrap.shutil, "which", return_value="/usr/bin/bwrap"):
            self.assertEqual(isolation.resolve("strongest", agy), "enforced")
            self.assertEqual(isolation.resolve("strongest", harnesses.get("claude")), "enforced")

    def test_seat_runs_with_a_served_model_receipt(self):
        root, _ = self.prepare()
        played, why = round_.run(root)
        self.assertEqual(why, "done")
        got = read(root / "records/g/r001/receipt.json")
        self.assertEqual(got["status"], "answered", got.get("error"))
        self.assertEqual(got["model"], "gemini-3.8-flash-low")
        self.assertEqual(got["tool_calls"], 0)
        self.assertIn("audited", got["filesystem"])
        argv = read(root / "records/g/r001/launch.json")["argv"]
        self.assertEqual(argv[:4], ["stdbuf", "-oL", "-eL", "agy"])
        self.assertIn("--dangerously-skip-permissions", argv)
        self.assertNotIn("--conversation", argv)
        self.assertTrue(list((self.box.home / ".gemini/antigravity-cli/brain").rglob("transcript_full.jsonl")))
        self.assertEqual(round_.usage(root)[0]["output"], 120)
        self.assertIsNone(round_.usage(root)[0]["cost_usd"])

    def test_audit_catches_paths_and_web_outside_the_policy(self):
        for scenario, message in (("path-violation", "outside the declared workspace"),
                                  ("web", "network tool"), ("mismatch", "served 'gemini-3.1-pro-high'")):
            with self.subTest(scenario=scenario):
                root, _ = self.prepare(brief={"text": f"[[stub:{scenario}]] Review."})
                round_.run(root)
                got = read(root / "records/g/r001/receipt.json")
                self.assertEqual(got["status"], "failed")
                self.assertIn(message, got["error"])
        root, _ = self.prepare(brief={"text": "[[stub:tools]] Review."})
        round_.run(root)
        self.assertEqual(read(root / "records/g/r001/receipt.json")["tools_used"], ["read_file"])
        root, _ = self.prepare(brief={"text": "[[stub:web]] Review."}, grants=["web"])
        round_.run(root)
        self.assertEqual(read(root / "records/g/r001/receipt.json")["status"], "answered")

    def test_quota_and_compaction_are_classified(self):
        root, _ = self.prepare(brief={"text": "[[stub:quota-refused]] Review."})
        played, why = round_.run(root)
        self.assertEqual(why, "held on g")
        got = read(root / "records/g/r001/receipt.json")
        self.assertEqual((got["status"], got["quota_stop"]), ("quota", "refused"))
        root, _ = self.prepare(brief={"text": "[[stub:compaction]] Review."})
        round_.run(root)
        got = read(root / "records/g/r001/receipt.json")
        self.assertTrue(got["compaction_observed"])
        self.assertIn("compaction observed", " ".join(got["red_flags"]))

    def test_enforced_jail_argv_binds_the_gemini_home_and_credentials(self):
        box = Sandbox(self, fake_bwrap=True)
        (box.home / ".gemini").mkdir(exist_ok=True)
        (box.home / ".gemini/oauth_creds.json").write_text("{}")
        work = box.root / "work"
        work.mkdir()
        with patch.object(bwrap.sys, "platform", "linux"):
            launched = isolation.get("enforced").wrap(["agy"], harness=harnesses.get("agy"),
                                                       seat_home=box.root / "seat", workspace=work,
                                                       project_root=box.project, repo_ro=False)
        argv = launched.argv
        private = argv.index(str(box.root / "seat/agy"))
        self.assertEqual(argv[private + 1], f"{box.home}/.gemini")
        creds = argv.index(str(box.home / ".gemini/oauth_creds.json"))
        self.assertEqual(argv[creds - 1], "--ro-bind")
        self.assertNotIn("CLAUDE_CONFIG_DIR", launched.env)


if __name__ == "__main__":
    unittest.main()


class FollowTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self)

    def test_render_each_harness(self):
        from convene import follow
        claude = [{"type": "assistant", "message": {"content": [
                       {"type": "tool_use", "name": "Read", "input": {"file_path": "materials/diff.patch"}},
                       {"type": "text", "text": "Found one."}]}},
                  {"type": "result", "is_error": False, "result": "Found one."}]
        lines = [t for row in claude for t in follow.render("claude", row)]
        self.assertEqual(lines, ["> Read materials/diff.patch", "  Found one.", "-- done: Found one."])
        codex = [{"type": "item.completed", "item": {"type": "command_execution", "command": "git log"}},
                 {"type": "item.completed", "item": {"type": "reasoning", "text": "hmm"}},
                 {"type": "item.completed", "item": {"type": "agent_message", "text": "Done."}},
                 {"type": "turn.completed"}]
        self.assertEqual([t for row in codex for t in follow.render("codex", row)],
                         ["> $ git log", "  Done.", "-- done"])
        self.assertIn("  ~ hmm", [t for row in codex for t in follow.render("codex", row, thinking=True)])
        agy = [{"step_update": {"step_type": "tool", "state": "ACTIVE", "tool_name": "read_file",
                                "tool_info": {"parameters": {"file_path": "/x"}}}},
               {"event": "result", "result": {"status": "SUCCESS", "response": "Ok."}}]
        self.assertEqual([t for row in agy for t in follow.render("agy", row)],
                         ["> read_file /x", "  Ok.", "-- done"])

    def test_follow_reads_a_finished_turn_and_its_stderr(self):
        import io
        from convene import follow
        root, _ = plan.prepare(self.box.plan(seats=[{"id": "s", "persona": "quinn-t-shun"}],
                                             brief={"text": "[[stub:tools]] Review."}),
                               project_root=self.box.project, range_spec="HEAD~1..HEAD")
        round_.run(root)
        out = io.StringIO()
        record = follow.follow(root, "s", "claude", out=out, poll=0)
        self.assertEqual(record.name, "r001")
        text = out.getvalue()
        self.assertIn("> Read materials/diff.patch", text)
        self.assertIn("-- done", text)
        with self.assertRaisesRegex(ValueError, "no turn yet"):
            follow.latest_record(root, "nobody")
