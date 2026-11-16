"""`convene ask`: one seat, one question, follow-ups on the same session."""

import contextlib
import io
import os
import unittest
from unittest.mock import patch

from convene_support import Sandbox

from convene import ask, board, plan, round as round_
from convene.cli import main
from convene.storage import read


class AskTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self)
        # The CLI names no tier, so an ask resolves `strongest`; pin it the
        # way an operator would, so these tests do not depend on bwrap.
        config = self.box.home / ".config/agent-toolbox/convene.toml"
        config.parent.mkdir(parents=True)
        config.write_text('isolation = "private-home"\n')
        os.environ.pop("XDG_CONFIG_HOME", None)

    def cli(self, *args, cwd=None, stdin=None):
        out = io.StringIO()
        argv = ["--project", str(cwd or self.box.project), *args]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out), \
                patch("sys.stdin", io.StringIO(stdin or "")):
            code = main(argv)
        return code, out.getvalue()

    def prompt(self, root, seat, n):
        return (root / "records" / seat / f"r{n:03d}" / "prompt.md").read_text()

    def only_run(self):
        from convene import runs
        found = runs.listing(self.box.project)
        self.assertEqual(len(found), 1)
        return found[0]

    def test_an_ask_answers_like_a_subagent_and_names_the_follow_up(self):
        code, text = self.cli("ask", "codex/sol", "--tools", "read", "Is add() right?",
                              "--name", "q1")
        self.assertEqual(code, 0, text)
        root = self.only_run()
        frozen = read(root / "plan.json")
        self.assertEqual(frozen["kind"], "ask")
        seat = frozen["seats"][0]
        self.assertEqual((seat["id"], seat["harness"], seat["model"], seat["model_requested"]),
                         ("codex", "codex", "gpt-5.6-sol", "sol"))
        self.assertEqual(seat["persona"]["profile"]["id"], "consultant")
        self.assertEqual(seat["workspace"], "repo-ro", "a checkout is shown read-only")
        first = self.prompt(root, "codex", 1)
        self.assertIn("is asking for your independent answer", first)
        self.assertIn("# Question\n\nIs add() right?", first)
        self.assertNotIn("one of 1 people", first)
        self.assertNotIn("about 400 words", first)
        self.assertTrue(first.rstrip().endswith("Answer now."))
        self.assertLess(text.index("Codex stub finding."), text.index("--- answered"),
                        "the answer comes before its receipt")
        self.assertIn("! isolation is advisory (private-home)", text, "red flags are repeated")
        self.assertIn("--- answered, round 1 of q1: codex/gpt-5.6-sol (from sol), Consultant", text)
        self.assertIn('next: convene ask --to q1 "FOLLOW-UP"', text)
        self.assertEqual(round_.status(root)["unfinished"], None, "an answered ask is finished")

    def test_a_follow_up_resumes_the_same_session_with_the_message_alone(self):
        self.assertEqual(self.cli("ask", "codex", "First question?", "--name", "q2")[0], 0)
        root = self.only_run()
        code, text = self.cli("ask", "--to", "q2", "And the second?")
        self.assertEqual(code, 0, text)
        self.assertEqual(board.published_rounds(root), [1, 2])
        calls = self.box.calls("codex", "codex")
        self.assertEqual(len(calls), 2)
        session = read(root / "records/codex/r001/receipt.json")["session_id"]
        self.assertIn(session, calls[1]["argv"], "the follow-up resumes round one's session")
        self.assertEqual(self.prompt(root, "codex", 2),
                         "A follow-up from the same asker:\n\nAnd the second?\n")
        self.assertIn("--- answered, round 2 of q2", text)
        code, text = self.cli("ask", "--to", "q2", "--persona", "sec-urity", "Third?")
        self.assertEqual(code, 1)
        self.assertIn("a follow-up keeps it", text)

    def test_a_question_on_stdin_and_a_withheld_repository(self):
        code, text = self.cli("ask", "claude/opus", "--no-repo", "-", "--name", "q3",
                              stdin="A long question\nover two lines.\n")
        self.assertEqual(code, 0, text)
        root = self.only_run()
        frozen = read(root / "plan.json")
        self.assertEqual(frozen["seats"][0]["workspace"], "none")
        self.assertEqual(frozen["title"], "A long question")
        self.assertNotIn("The repository is at", self.prompt(root, "claude", 1))

    def test_outside_a_checkout_the_seat_gets_no_repository(self):
        loose = self.box.root / "loose"
        loose.mkdir()
        root = ask.start("What is this?", "claude", project=loose, name="q4")
        self.assertEqual(read(root / "plan.json")["seats"][0]["workspace"], "none")

    def test_the_home_directory_is_never_bound_read_only(self):
        with self.assertRaisesRegex(ValueError, "holds your home directory"):
            ask.start("What is here?", "claude", project=self.box.home, workspace="repo-ro")
        with self.assertRaisesRegex(ValueError, "holds your home directory"):
            ask.start("What is here?", "claude", project=self.box.root, workspace="repo-ro")

    def test_a_quota_stop_holds_the_turn_and_refuses_a_second_message(self):
        code, text = self.cli("ask", "claude", "[[stub:quota-refused-once]] Why?", "--name", "q5")
        self.assertEqual(code, 3, text)
        self.assertIn("HELD on a provider quota", text)
        self.assertIn("next: convene continue q5 claude", text)
        code, text = self.cli("ask", "--to", "q5", "Still there?")
        self.assertEqual(code, 1)
        self.assertIn("has not answered its last message yet", text)
        self.assertEqual(self.cli("continue", "q5", "claude")[0], 0)
        self.assertEqual(self.cli("promote", "q5", "1")[0], 0)
        code, text = self.cli("ask", "--to", "q5", "Still there?")
        self.assertEqual(code, 0, text)

    def test_seat_names_are_checked_before_anything_is_prepared(self):
        for spec, why in (("gpt/sol", "HARNESS one of"), ("codex/", "no model after the slash")):
            with self.subTest(spec=spec):
                code, text = self.cli("ask", spec, "Q?")
                self.assertEqual(code, 1)
                self.assertIn(why, text)
        code, text = self.cli("ask", "codex")
        self.assertEqual(code, 1)
        self.assertIn("name the seat and the question", text)
        from convene import runs
        self.assertEqual(runs.listing(self.box.project), [])

    def test_a_plan_cannot_stretch_an_ask_into_a_room(self):
        for fields, why in (({"rounds": 2}, "starts with one round"),
                            ({"seats": [{"id": "a", "persona": "consultant"},
                                        {"id": "b", "persona": "consultant"}]}, "exactly one seat"),
                            ({"workspace": "worktree", "tools": "write"}, "reads the repository at most")):
            with self.subTest(fields=fields):
                fields = {"kind": "ask", "seats": [{"id": "a", "persona": "consultant"}], **fields}
                with self.assertRaisesRegex(ValueError, why):
                    plan.prepare(self.box.plan(**fields), project_root=self.box.project)

    def test_a_follow_up_to_a_room_is_refused_by_name(self):
        room = self.box.plan(kind="room", workspace="none",
                             seats=[{"id": "a", "persona": "archie-tecture"}])
        root, _ = plan.prepare(room, project_root=self.box.project, name="room1")
        round_.run_round(root, 1)
        with self.assertRaisesRegex(ValueError, "is a room, not an ask"):
            ask.follow_up(root, "Hello?")


if __name__ == "__main__":
    unittest.main()
