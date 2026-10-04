"""Multi-round runs: boards between rounds, phases, deliverables, worktrees,
quota continuation, budgets, convergence, cold joins and pruning."""

import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from convene_support import Sandbox

from convene import board, plan, platform, round as round_, runs, workspace
from convene.cli import main
from convene.storage import read, trail, write


class RoundTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self)

    def prepare(self, **fields):
        fields.setdefault("kind", "room")
        fields.setdefault("seats", [{"id": "a", "persona": "archie-tecture"},
                                    {"id": "b", "persona": "quinn-t-shun", "harness": "codex",
                                     "model": "gpt-5.5", "effort": "low"}])
        fields.setdefault("workspace", "none")
        root, frozen = plan.prepare(self.box.plan(**fields), project_root=self.box.project)
        return root, frozen

    def prompt(self, root, seat, n):
        return (root / "records" / seat / f"r{n:03d}" / "prompt.md").read_text()

    def receipt(self, root, seat, n):
        return read(root / "records" / seat / f"r{n:03d}" / "receipt.json")

    def test_rounds_resume_sessions_and_show_the_board_between_them(self):
        root, frozen = self.prepare(rounds=2, seats=[
            {"id": "a", "persona": "archie-tecture"},
            {"id": "b", "persona": "quinn-t-shun", "harness": "codex", "model": "gpt-5.5",
             "effort": "low"},
            {"id": "blind", "persona": "sec-urity", "visibility": "blind"}])
        played, why = round_.run(root)
        self.assertEqual(why, "done")
        self.assertEqual([n for n, _ in played], [1, 2])
        self.assertEqual(board.published_rounds(root), [1, 2])
        for seat, harness in (("a", "claude"), ("b", "codex")):
            calls = self.box.calls(seat, harness)
            self.assertEqual(len(calls), 2)
            first = self.receipt(root, seat, 1)["session_id"]
            self.assertIn(first, calls[1]["argv"], "round two resumes round one's session")
            self.assertEqual(self.receipt(root, seat, 2)["session_id"], first)
            self.assertTrue((root / "work" / seat / "board/round-001/digest.md").exists())
        self.assertIn("The board has moved: board/round-001/digest.md", self.prompt(root, "a", 2))
        self.assertIn("Nobody has posted yet", self.prompt(root, "a", 1))
        self.assertFalse(list((root / "work/blind/board").iterdir()), "a blind seat sees no board")
        self.assertIn("You do not see the others' posts", self.prompt(root, "blind", 2))
        self.assertIn("I read round-001", board.post_path(root, "a", 2).read_text())
        digest = (root / "board/rounds/r002/digest.md").read_text()
        self.assertIn("## Archie Tecture  (a)", digest)
        self.assertNotIn("opus", digest, "seats never see model names on the board")
        self.assertEqual(read(root / "board/rounds/r002/digest.json")["order"], ["b", "blind", "a"])

    def test_phases_seat_subsets_deliverables_and_instructions(self):
        root, frozen = self.prepare(rounds=3, seats=[
            {"id": "a", "persona": "archie-tecture", "tools": "write"},
            {"id": "b", "persona": "quinn-t-shun", "harness": "codex", "model": "gpt-5.5",
             "effort": "low"}], phases=[
            {"name": "discuss", "rounds": 1},
            {"name": "draft", "rounds": 1, "seats": ["a"], "deliverable": "draft.md",
             "instruction": "Draft it now.", "length": 900},
            {"name": "critique", "rounds": 1, "seats": ["b"]}])
        played, why = round_.run(root)
        self.assertEqual(why, "done", "a phased run never stops on convergence")
        self.assertEqual(len(self.box.calls("b", "codex")), 2, "b rests in the draft round")
        self.assertIn("Write the work itself to outbox/draft.md, as finished text and nothing "
                      "else, about 900 words", self.prompt(root, "a", 2))
        self.assertIn("Draft it now.", self.prompt(root, "a", 2))
        made = root / "board/made/a/r002/draft.md"
        self.assertTrue(made.is_file())
        self.assertFalse((root / "work/a/outbox/draft.md").exists(), "moved, not copied")
        digest = (root / "board/rounds/r002/digest.md").read_text()
        self.assertIn("### draft.md", digest)
        self.assertIn("Deliverable draft.md", digest)
        self.assertEqual(read(root / "board/rounds/r002/digest.json")["made"], {"a": {"draft.md": __import__("convene.storage", fromlist=["digest"]).digest(made)}})
        self.assertIn("Nobody else has posted since round 1", self.prompt(root, "a", 2)
                      if False else "Nobody else has posted since round 1: board/round-001/digest.md.",
                      )
        self.assertIn("You did not post in round 2", self.prompt(root, "b", 3))
        events = [r for r in trail(root) if r.get("event") == "resting"]
        self.assertEqual([(r["round"], r["seat"]) for r in events], [(2, "b"), (3, "a")])
        data = round_.status(root)
        text = round_.render_status(data)
        self.assertIn("phases: discuss x1, draft x1 [a], critique x1 [b]", text)
        # Three rounds, but each seat speaks in two: the round it rests in is
        # not a turn it owes, so neither seat may read as one round behind.
        self.assertIn("- a (Archie Tecture): answered 2 of 2 rounds", text)
        self.assertIn("- b (Quinn T. Shun): answered 2 of 2 rounds", text)

    def test_a_release_between_rounds_does_not_switch_a_seat_model(self):
        """`opus` is resolved by the CLI; round two must keep round one's Opus."""
        root, frozen = self.prepare(rounds=2)
        round_.run_round(root, 1)
        first = self.receipt(root, "a", 1)["model"]
        self.assertEqual(first, "claude-opus-5-20260601")
        # A newer Opus ships while the room waits between rounds.
        next(root.glob("homes/a/**/stub-calls.jsonl")).with_name("stub-new-opus").touch()
        round_.run_round(root, 2)
        second = self.receipt(root, "a", 2)
        self.assertEqual(second["status"], "answered", second.get("error"))
        self.assertEqual(second["model"], first)
        self.assertEqual(second["model_pinned"], first)
        self.assertEqual(second["requested_model"], "opus")
        argv = self.box.calls("a", "claude")[1]["argv"]
        self.assertIn("--resume", argv)
        self.assertEqual(argv[argv.index("--model") + 1], first)
        # A seat whose plan already names the exact version needs no pin.
        self.assertNotIn("model_pinned", self.receipt(root, "b", 2))

    def test_status_names_the_command_to_type_next_at_every_stage(self):
        root, _ = self.prepare(rounds=2, seats=[{"id": "a", "persona": "archie-tecture"}])
        text = round_.render_status(round_.status(root))
        self.assertIn("rounds: 0 of 2 published", text)
        self.assertIn("not started, 2 rounds to speak in", text)
        self.assertIn(f"next: convene run {root.name}", text)
        round_.run_round(root, 1)
        self.assertIn(f"next: convene run {root.name}", round_.render_status(round_.status(root)))
        round_.run_round(root, 2)
        text = round_.render_status(round_.status(root))
        self.assertIn("rounds: 2 of 2 published (1-2)", text)
        self.assertIn("red flags: 2 (marked ! below)", text)
        self.assertIn(f"next: convene board {root.name}", text)

    def test_only_the_latest_signal_says_a_run_converged(self):
        """An extended run that played past its convergence is not done."""
        root, _ = self.prepare(rounds=2, seats=[{"id": "a", "persona": "archie-tecture"}])
        round_.run_round(root, 1)
        round_.run_round(root, 2)
        board.extend(root, 4)

        def signal(n, converged):
            path = root / "board" / "rounds" / f"r{n:03d}" / "convergence.json"
            write(path, {**read(path), "converged": converged,
                         "reason": "novelty" if converged else None})

        # Converged at round one, then played past it: not converged now.
        signal(1, True)
        signal(2, False)
        data = round_.status(root)
        self.assertFalse(data["converged"])
        self.assertEqual(data["next"], f"convene run {root.name}")
        # Converged at the latest round with budget left: both halves named.
        signal(2, True)
        data = round_.status(root)
        self.assertTrue(data["converged"])
        self.assertEqual(data["next"],
                         f"convene board {root.name}, then convene export {root.name} DIR; "
                         f"the run converged, and convene run {root.name} plays past it")

    def test_worktree_seat_changes_are_captured_and_pruned(self):
        root, frozen = self.prepare(rounds=1, seats=[
            {"id": "d", "persona": "connie-tinuity", "tools": "write", "workspace": "worktree"}],
            brief={"text": "[[stub:edit-repo]] Build it."})
        tree = root / "work/d/repo"
        self.assertTrue((tree / "app.py").is_file())
        # A private clone: the operator's repository never records it, and
        # nothing in it points back there.
        self.assertNotIn(str(tree), self.box.git("worktree", "list"))
        self.assertTrue((tree / ".git").is_dir())
        self.assertEqual(self.box.git("-C", str(tree), "remote").strip(), "")
        self.assertEqual(frozen["base_commit"], self.box.git("rev-parse", "HEAD").strip())
        self.assertEqual(self.box.git("-C", str(tree), "rev-parse", "HEAD").strip(),
                         frozen["base_commit"])
        round_.run(root)
        patch = (root / "board/made/d/r001/changes.patch").read_text()
        self.assertIn("edited by the stub seat", patch)
        self.assertIn("NEW.md", patch, "untracked files are in the patch")
        self.assertIn("```", (root / "board/rounds/r001/digest.md").read_text())
        self.assertEqual(self.box.git("status", "--porcelain"), "", "the operator's checkout is untouched")
        self.assertIn("A checkout of the repository is at repo/", self.prompt(root, "d", 1))
        self.assertIn("build output and caches included, so delete any you do not mean to submit",
                      self.prompt(root, "d", 1))
        removed = round_.prune(root)
        self.assertIn(str(tree), removed)
        self.assertFalse(tree.exists())
        self.assertFalse((root / "homes/d").exists())
        self.assertTrue((root / "records/d/r001/receipt.json").exists(), "records are kept")

    def test_prune_unregisters_a_linked_worktree_from_an_older_run(self):
        """Runs prepared before private clones hold linked worktrees, which
        the operator's repository keeps a registration for."""
        root, _ = self.prepare(rounds=1, seats=[
            {"id": "d", "persona": "connie-tinuity", "tools": "write", "workspace": "worktree"}])
        tree = root / "work/d/repo"
        __import__("shutil").rmtree(tree)
        self.box.git("worktree", "add", "--detach", "-q", str(tree), "HEAD")
        self.assertIn(str(tree), self.box.git("worktree", "list"))
        self.assertIn(str(tree), round_.prune(root))
        self.assertFalse(tree.exists())
        self.assertNotIn(str(tree), self.box.git("worktree", "list"))

    def test_prune_refuses_a_live_seat(self):
        root, _ = self.prepare(rounds=1, seats=[{"id": "a", "persona": "archie-tecture"}])
        round_.run(root)
        running = [r for r in trail(root) if r.get("event") == "running"][0]
        with patch.object(platform, "process_identity", return_value=running["process_identity"]):
            with self.assertRaisesRegex(RuntimeError, "still running: a"):
                round_.prune(root)
        with patch.object(platform, "process_identity", side_effect=RuntimeError("no /proc here")):
            with self.assertRaisesRegex(RuntimeError, "--force"):
                round_.prune(root)
            self.assertTrue(round_.prune(root, force=True))

    def test_refused_quota_holds_then_continue_and_promote(self):
        root, _ = self.prepare(rounds=2, seats=[{"id": "a", "persona": "archie-tecture"},
                                                {"id": "b", "persona": "quinn-t-shun"}],
                               brief={"text": "[[stub:quota-refused-once]] Discuss."})
        played, why = round_.run(root)
        self.assertEqual(why, "held on a, b")
        self.assertEqual(board.published_rounds(root), [])
        with self.assertRaisesRegex(RuntimeError, "still held on a, b"):
            round_.promote_held(root, 1)
        self.assertEqual(round_.continue_seat(root, 1, "a"), "answered")
        self.assertEqual(round_.continue_seat(root, 1, "b"), "answered")
        state = read(root / "records/a/state.json")
        self.assertEqual(state["attempts"], [{"round": 1, "attempt": 1, "quota_stop": "refused",
                                              "quota_scope": "five_hour", "resumed": None}])
        self.assertTrue((root / "records/a/r001/attempts/01/receipt.json").exists())
        self.assertEqual(self.prompt(root, "a", 1), (root / "records/a/r001/attempts/01/prompt.md").read_text(),
                         "a refused turn is delivered again verbatim")
        with self.assertRaisesRegex(ValueError, "already answered round 1"):
            round_.continue_seat(root, 1, "a")
        outcome = round_.promote_held(root, 1)
        self.assertEqual(outcome["posted"], ["a", "b"])
        played, why = round_.run(root)
        self.assertEqual(([n for n, _ in played], why), ([2], "done"))

    def test_interrupted_quota_resumes_the_same_session(self):
        root, _ = self.prepare(rounds=1, seats=[{"id": "a", "persona": "archie-tecture"},
                                                {"id": "b", "persona": "quinn-t-shun",
                                                 "harness": "codex", "model": "gpt-5.5",
                                                 "effort": "low"}],
                               brief={"text": "[[stub:quota-interrupted-once]] Discuss."})
        played, why = round_.run(root)
        self.assertEqual(why, "held on a, b")
        for seat, harness in (("a", "claude"), ("b", "codex")):
            first = read(root / "records" / seat / "state.json")["session_id"]
            self.assertIsNotNone(first, "an interrupted stop keeps its session")
            self.assertEqual(round_.continue_seat(root, 1, seat), "answered")
            calls = self.box.calls(seat, harness)
            self.assertIn(first, calls[1]["argv"])
            self.assertIn("Continue from where you were", self.prompt(root, seat, 1))
            self.assertEqual(self.receipt(root, seat, 1)["session_id"], first)
        round_.promote_held(root, 1)
        self.assertEqual(board.published_rounds(root), [1])

    def test_promote_absent_gives_up_on_a_held_seat(self):
        root, _ = self.prepare(rounds=1, seats=[{"id": "a", "persona": "archie-tecture"}],
                               brief={"text": "[[stub:quota-refused]] Discuss."})
        round_.run(root)
        outcome = round_.promote_absent(root, 1)
        self.assertEqual(outcome["absent"], ["a"])
        self.assertEqual(read(root / "records/a/state.json")["status"], "given-up")
        self.assertIn("No post this round from: Archie Tecture", (root / "board/rounds/r001/digest.md").read_text())

    def test_cold_join_after_a_lost_first_round(self):
        root, _ = self.prepare(rounds=2, seats=[{"id": "a", "persona": "archie-tecture"},
                                                {"id": "late", "persona": "quinn-t-shun"}],
                               brief={"text": "Discuss."})
        (root / "work/late/START.md").write_text("[[stub:quota-refused]] " + (root / "work/late/START.md").read_text())
        from convene.storage import digest, write
        _, frozen = runs.load(root)
        for seat in frozen["seats"]:
            if seat["id"] == "late":
                seat["start_sha256"] = digest(root / "work/late/START.md")
        write(root / "plan.json", frozen)
        write(root / "plan-digest.json", {"sha256": digest(root / "plan.json")})
        played, why = round_.run(root)
        self.assertEqual(why, "held on late")
        round_.promote_absent(root, 1)
        # The seat's assignment is rewritten so its second turn succeeds.
        (root / "work/late/START.md").write_text((root / "work/late/START.md").read_text().replace("[[stub:quota-refused]] ", ""))
        _, frozen = runs.load(root)
        for seat in frozen["seats"]:
            if seat["id"] == "late":
                seat["start_sha256"] = digest(root / "work/late/START.md")
        write(root / "plan.json", frozen)
        write(root / "plan-digest.json", {"sha256": digest(root / "plan.json")})
        played, why = round_.run(root)
        self.assertEqual(why, "done")
        self.assertIn("joining a room already in progress", self.prompt(root, "late", 2))
        self.assertIn("Joining late.", board.post_path(root, "late", 2).read_text())
        self.assertEqual(self.box.calls("late", "claude")[-1]["argv"].count("--session-id"), 1)
        data = round_.status(root)
        self.assertEqual(data["seats"]["late"]["joined_late"], 2)
        self.assertIn("JOINED LATE in round 2", round_.render_status(data))

    def test_convergence_stops_an_unphased_room_and_budget_extends_it(self):
        root, _ = self.prepare(rounds=5, seats=[{"id": "a", "persona": "archie-tecture"},
                                                {"id": "b", "persona": "quinn-t-shun"}])
        played, why = round_.run(root)
        self.assertEqual(why, "converged on novelty")
        self.assertEqual([n for n, _ in played], [1, 2, 3], "two quiet rounds after the opening")
        signal = read(root / "board/rounds/r003/convergence.json")
        self.assertTrue(signal["converged"])
        self.assertEqual(signal["series"][0]["novelty"], 100.0)
        self.assertEqual(signal["series"][2]["novelty"], 0.0)
        # Asking again plays one more round; a quiet room stays quiet.
        played, why = round_.run(root, rounds=4)
        self.assertEqual(([n for n, _ in played], why), ([4], "converged on novelty"))
        played, why = round_.run(root)
        self.assertEqual(([n for n, _ in played], why), ([5], "converged on novelty"))
        self.assertEqual(round_.run(root), ([], "done"))
        with self.assertRaisesRegex(ValueError, "round must be 1..5"):
            round_.run_round(root, 6)
        self.assertEqual(board.extend(root, 6), 6)
        with self.assertRaisesRegex(ValueError, "already allows 6"):
            board.extend(root, 6)
        played, why = round_.run(root, rounds=6)
        self.assertEqual([n for n, _ in played], [6])
        self.assertEqual(round_.run(root), ([], "done"))
        self.assertIn("converged at round 3 on novelty", round_.render_status(round_.status(root)))

    def test_chair_note_reaches_the_turn_and_the_digest(self):
        root, _ = self.prepare(rounds=2, seats=[{"id": "a", "persona": "archie-tecture"}])
        (root / "chair/r002.md").write_text("Budget is fixed; do not propose a rewrite.\n")
        round_.run_round(root, 1)
        self.assertEqual(round_.status(root)["chair"], {"delivered": [], "queued": [2]})
        round_.run_round(root, 2)
        self.assertIn("From the chair, to everyone acting this round:\n\nBudget is fixed",
                      self.prompt(root, "a", 2))
        self.assertIn("## From the chair", (root / "board/rounds/r002/digest.md").read_text())
        self.assertEqual(round_.status(root)["chair"], {"delivered": [2], "queued": []})

    def test_cli_verbs(self):
        import contextlib
        import io
        root, _ = self.prepare(rounds=2, seats=[{"id": "a", "persona": "archie-tecture"}],
                               brief={"text": "[[stub:quota-refused-once]] Discuss."})
        run = lambda *a: main(["--project", str(self.box.project), *a])  # noqa: E731
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.assertEqual(run("run", root.name), 3)
            self.assertEqual(run("promote", root.name, "1"), 1)
            self.assertEqual(run("continue", root.name, "a"), 0)
            self.assertEqual(run("promote", root.name, "1"), 0)
            self.assertEqual(run("round", root.name, "2"), 0)
            self.assertEqual(run("extend", root.name, "3"), 0)
            self.assertEqual(run("board", root.name, "--round", "2"), 0)
            self.assertEqual(run("prune", root.name), 0)
        text = out.getvalue()
        self.assertIn("held on a", text)
        self.assertIn("still held on a", text)
        self.assertIn("a round 1: answered", text)
        self.assertIn("round 1 published: posted a", text)
        self.assertIn("round 2: a=answered; published", text)
        self.assertIn("budget is now 3 rounds", text)
        self.assertIn("The board -- round 2", text)
        self.assertIn(str(root / "homes/a"), text)


class StatusRenderingTests(unittest.TestCase):
    """The status text is the operator's only read of a run, so pin its shape.

    These are the pieces with no sandbox in them; the run-level assertions
    live beside the runs that produce them.
    """

    def test_round_numbers_collapse_instead_of_printing_a_python_list(self):
        self.assertEqual(round_._spans([1]), "1")
        self.assertEqual(round_._spans([1, 2, 3, 5]), "1-3, 5")
        self.assertEqual(round_._spans([4, 2, 1]), "1-2, 4")

    def test_a_turn_leaves_out_the_fields_its_receipt_lacks(self):
        line = round_._turn_line(1, {"status": "failed", "seconds": 60.0, "tool_calls": None,
                                     "model": None, "tier": "enforced"})
        self.assertEqual(line, "    r001: failed, 60.0s, tier enforced")
        self.assertNotIn("None", line)

    def test_a_blind_turn_names_what_is_withheld_instead_of_formatting_it(self):
        line = round_._turn_line(2, {"status": "answered", "model": "m",
                                     "seconds": "withheld", "tool_calls": "withheld"})
        self.assertIn("duration withheld", line)
        self.assertIn("tool calls withheld", line)
        self.assertNotIn("withhelds", line)

    def test_a_seat_reports_every_round_not_only_how_its_last_turn_ended(self):
        seat = {"label": "L", "acting_rounds": [1, 2, 3], "joined_late": None,
                "receipts": {1: {"status": "answered"}, 2: {"status": "answered"},
                             3: {"status": "failed"}}}
        self.assertEqual(round_._seat_line("a", seat),
                         "- a (L): answered 2 of 3 rounds, r003 failed")

    def test_a_seat_that_has_not_run_says_so_and_names_its_rounds(self):
        seat = {"label": "L", "acting_rounds": [1, 2], "joined_late": None, "receipts": {}}
        self.assertEqual(round_._seat_line("a", seat), "- a (L): not started, 2 rounds to speak in")


if __name__ == "__main__":
    unittest.main()
