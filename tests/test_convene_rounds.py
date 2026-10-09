"""Multi-round runs: boards between rounds, phases, deliverables, worktrees,
quota continuation, budgets, convergence, cold joins and pruning."""

import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from convene_support import Sandbox, environment_of

from convene import board, plan, platform, round as round_, runs, workspace
from convene.cli import main
from convene.storage import digest, read, trail, write


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
            self.assertTrue((environment_of(root) / "work" / seat / "board/round-001/digest.md").exists())
        self.assertIn("The board has moved: board/round-001/digest.md", self.prompt(root, "a", 2))
        self.assertIn("Nobody has posted yet", self.prompt(root, "a", 1))
        self.assertFalse(list((environment_of(root) / "work/blind/board").iterdir()), "a blind seat sees no board")
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
        self.assertFalse((environment_of(root) / "work/a/outbox/draft.md").exists(), "moved, not copied")
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

    def test_a_seat_that_posts_without_its_file_is_named(self):
        """Its prompt said where to write the file, so a post without it is the
        trace any failure leaves; on its own it read as a finished turn."""
        import contextlib
        import io
        root, _ = self.prepare(rounds=1, seats=[
            {"id": "a", "persona": "archie-tecture", "tools": "write"},
            {"id": "b", "persona": "quinn-t-shun", "harness": "codex", "model": "gpt-5.5",
             "effort": "low", "tools": "write"}],
            phases=[{"name": "draft", "rounds": 1, "deliverable": "draft.md"}],
            brief={"text": "[[stub:no-file]] Draft it."})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--project", str(self.box.project), "run", root.name]), 0)
        self.assertIn("posted 2, 1 without draft.md", out.getvalue())
        digest = (root / "board/rounds/r001/digest.md").read_text()
        self.assertIn("No draft.md this round from: Archie Tecture.\n", digest)
        self.assertNotIn("No post this round", digest)
        self.assertEqual(read(root / "board/rounds/r001/digest.json")["unmade"], ["a"])
        text = round_.render_status(round_.status(root))
        self.assertIn("- a (Archie Tecture): answered 1 of 1 round, r001 without draft.md\n", text)
        self.assertIn("    r001: answered, draft.md NOT MADE, ", text)
        self.assertIn("- b (Quinn T. Shun): answered 1 of 1 round\n", text)

    def test_a_release_between_rounds_does_not_switch_a_seat_model(self):
        """`opus` is resolved by the CLI; round two must keep round one's Opus."""
        root, frozen = self.prepare(rounds=2)
        round_.run_round(root, 1)
        first = self.receipt(root, "a", 1)["model"]
        self.assertEqual(first, "claude-opus-5-20260601")
        # A newer Opus ships while the room waits between rounds.
        next(environment_of(root).glob("homes/a/**/stub-calls.jsonl")).with_name("stub-new-opus").touch()
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
        tree = environment_of(root) / "work/d/repo"
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
        environment = environment_of(root)
        self.assertEqual(round_.prune(root), [str(environment)])
        self.assertFalse(environment.exists(), "workspaces, clones and homes go together")
        self.assertTrue((root / "records/d/r001/receipt.json").exists(), "records are kept")
        self.assertTrue((root / "board/made/d/r001/changes.patch").exists(), "the board is kept")

    def as_older_run(self, root):
        """Give a fresh run the layout of one prepared before environments
        moved to the cache: workspaces and homes inside the run directory,
        and a plan that names no environment."""
        import shutil
        environment = environment_of(root)
        for part in ("work", "homes"):
            shutil.move(str(environment / part), str(root / part))
        shutil.rmtree(environment)
        frozen = read(root / "plan.json")
        del frozen["environment"]
        write(root / "plan.json", frozen)
        write(root / "plan-digest.json", {"sha256": digest(root / "plan.json")})

    def test_prune_unregisters_a_linked_worktree_from_an_older_run(self):
        """Runs prepared before private clones hold linked worktrees, which
        the operator's repository keeps a registration for. They also predate
        the cache, so their workspaces stay and only repositories and homes go."""
        root, _ = self.prepare(rounds=1, seats=[
            {"id": "d", "persona": "connie-tinuity", "tools": "write", "workspace": "worktree"}])
        self.as_older_run(root)
        tree = root / "work/d/repo"
        __import__("shutil").rmtree(tree)
        self.box.git("worktree", "add", "--detach", "-q", str(tree), "HEAD")
        self.assertIn(str(tree), self.box.git("worktree", "list"))
        # Never played, so only a forced prune takes it.
        self.assertEqual(round_.prune(root, force=True), [str(tree), str(root / "homes/d")])
        self.assertFalse(tree.exists())
        self.assertNotIn(str(tree), self.box.git("worktree", "list"))
        self.assertTrue((root / "work/d/START.md").exists(), "an older run's workspace stays")
        # Its assignment survived, so only the trail can say the run is over.
        self.assertEqual(round_.status(root)["environment"]["gone"], "it was pruned")

    def test_a_pruned_run_keeps_its_board_and_refuses_to_play_on(self):
        """Extending a pruned run would resume sessions whose homes are gone."""
        import contextlib
        import io
        root, _ = self.prepare(rounds=1, seats=[{"id": "a", "persona": "archie-tecture"}])
        round_.run(root)
        round_.prune(root)
        board.extend(root, 2)
        with self.assertRaisesRegex(RuntimeError, r"no more turns .*: it was pruned\. "
                                    r".*convene board .* still work"):
            round_.run(root)
        data = round_.status(root)
        self.assertEqual(data["environment"]["gone"], "it was pruned")
        self.assertEqual(data["next"], f"convene board {root.name}, then convene export "
                         f"{root.name} DIR; no seat can take another turn, because the "
                         "run's environment is gone (it was pruned)")
        self.assertIn("  environment: gone (it was pruned)", round_.render_status(data))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--project", str(self.box.project), "board", root.name]), 0)
        self.assertIn("Stub finding", out.getvalue())

    def test_prune_keeps_a_held_run_unless_forced(self):
        """A held seat resumes its session from its home; pruning would strand it."""
        root, _ = self.prepare(rounds=1, seats=[{"id": "a", "persona": "archie-tecture"}],
                               brief={"text": "[[stub:quota-refused-once]] Discuss."})
        self.assertEqual(round_.run(root)[1], "held on a")
        with self.assertRaisesRegex(RuntimeError, r"not finished: round 1 is held on a\. "
                                    r".*--force prunes it anyway"):
            round_.prune(root)
        self.assertTrue(environment_of(root).exists())
        self.assertEqual(round_.continue_seat(root, 1, "a"), "answered")
        round_.promote_held(root, 1)
        self.assertIsNone(round_.status(root)["unfinished"])
        self.assertEqual(round_.prune(root), [str(environment_of(root))])

    def test_prune_finished_takes_finished_runs_and_lists_the_rest(self):
        import contextlib
        import io
        import json
        seats = [{"id": "a", "persona": "archie-tecture"}]
        run = lambda *a: main(["--project", str(self.box.project), *a])  # noqa: E731

        def cli(*args, code=0):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                self.assertEqual(run(*args), code, out.getvalue())
            return out.getvalue()

        done, _ = self.prepare(rounds=1, seats=seats)
        self.assertRegex(cli("run", done.name),
                         rf"its environment holds [\d.]+ k?B at {environment_of(done)}; "
                         rf"convene prune {done.name} frees it once you are done with the run")
        going, _ = self.prepare(rounds=2, seats=seats)
        self.assertNotIn("its environment holds", cli("run", going.name, "--rounds", "1"))
        gone, _ = self.prepare(rounds=1, seats=seats)
        round_.run(gone)
        round_.prune(gone)

        listing = cli("runs")
        self.assertRegex(listing, rf"(?m)^{done.name}\s+[\d.]+ k?B  finished$")
        self.assertRegex(listing, rf"(?m)^{going.name}\s+[\d.]+ k?B  unfinished: "
                                  r"1 of 2 rounds are published$")
        self.assertRegex(listing, rf"(?m)^{gone.name}\s+pruned$")
        self.assertRegex(listing, r"convene prune --finished frees [\d.]+ k?B from finished runs")
        rows = {row["name"]: row for row in json.loads(cli("runs", "--json"))}
        self.assertEqual(rows[gone.name]["gone"], "it was pruned")
        self.assertEqual(rows[going.name]["environment"], str(environment_of(going)))

        swept = cli("prune", "--finished")
        self.assertRegex(swept, rf"{done.name}: freed [\d.]+ k?B\n")
        self.assertIn(f"{going.name}: kept, unfinished: 1 of 2 rounds are published\n", swept)
        self.assertNotIn(gone.name, swept, "a pruned run has nothing left to remove")
        self.assertFalse(environment_of(done).exists())
        self.assertTrue(environment_of(going).exists())
        self.assertNotIn("convene prune --finished frees", cli("runs"))
        self.assertIn("nothing to remove", cli("prune", "--finished"))

        self.assertIn("name one RUN, or pass --finished", cli("prune", code=1))
        self.assertIn("name one RUN, or pass --finished",
                      cli("prune", going.name, "--finished", code=1))
        self.assertIn("--force applies to one named run",
                      cli("prune", "--finished", "--force", code=1))

    def test_disk_usage_counts_a_hard_link_once(self):
        """A local clone hard-links its objects; each seat's would count them again."""
        first, second = self.box.root / "du/one", self.box.root / "du/two"
        first.mkdir(parents=True)
        second.mkdir()
        (first / "object").write_bytes(os.urandom(200_000))
        os.link(first / "object", second / "object")
        alone = runs.disk_usage([first])
        self.assertGreaterEqual(alone, 200_000)
        self.assertEqual(runs.disk_usage([first, second]), alone)

    def test_a_cleared_cache_stops_turns_and_promotion_by_name(self):
        """Clearing the cache removes the environment without the run knowing.
        A promotion would then read empty outboxes and file the seats' work as
        unmade, and a turn would resume nothing, so both refuse instead."""
        import shutil
        root, _ = self.prepare(rounds=2, seats=[{"id": "a", "persona": "archie-tecture"}],
                               brief={"text": "[[stub:quota-refused-once]] Discuss."})
        played, why = round_.run(root)
        self.assertEqual(why, "held on a")
        self.assertIn("environment: " + str(environment_of(root)),
                      round_.render_status(round_.status(root)))
        shutil.rmtree(environment_of(root))
        for attempt in (lambda: round_.continue_seat(root, 1, "a"),
                        lambda: round_.promote_absent(root, 1),
                        lambda: round_.promote_held(root, 1),
                        lambda: round_.run_round(root, 1)):
            with self.assertRaisesRegex(RuntimeError, "no longer holds the workspace of a; "
                                        "the cache was cleared"):
                attempt()
        self.assertFalse(environment_of(root).exists(), "nothing recreated the workspace")
        self.assertNotIn("unmade", [r.get("event") for r in trail(root)])
        self.assertTrue(round_.status(root)["next"].startswith(
            f"convene board {root.name}, then convene export {root.name} DIR; no seat"))

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
        (environment_of(root) / "work/late/START.md").write_text("[[stub:quota-refused]] " + (environment_of(root) / "work/late/START.md").read_text())
        from convene.storage import digest, write
        _, frozen = runs.load(root)
        for seat in frozen["seats"]:
            if seat["id"] == "late":
                seat["start_sha256"] = digest(environment_of(root) / "work/late/START.md")
        write(root / "plan.json", frozen)
        write(root / "plan-digest.json", {"sha256": digest(root / "plan.json")})
        played, why = round_.run(root)
        self.assertEqual(why, "held on late")
        round_.promote_absent(root, 1)
        # The seat's assignment is rewritten so its second turn succeeds.
        (environment_of(root) / "work/late/START.md").write_text((environment_of(root) / "work/late/START.md").read_text().replace("[[stub:quota-refused]] ", ""))
        _, frozen = runs.load(root)
        for seat in frozen["seats"]:
            if seat["id"] == "late":
                seat["start_sha256"] = digest(environment_of(root) / "work/late/START.md")
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
            # Extended to three rounds with two played: unfinished, so kept.
            self.assertEqual(run("prune", root.name), 1)
            self.assertTrue(environment_of(root).exists())
            self.assertEqual(run("prune", root.name, "--force"), 0)
        text = out.getvalue()
        self.assertIn("held on a", text)
        self.assertIn("still held on a", text)
        self.assertIn("a round 1: answered", text)
        self.assertIn("round 1 published: posted a", text)
        self.assertIn("round 2: a=answered; published", text)
        self.assertIn("budget is now 3 rounds", text)
        self.assertIn("The board -- round 2", text)
        self.assertIn("convene prune: run " + root.name + " is not finished: 2 of 3 rounds "
                      "are published", text)
        self.assertRegex(text, "removed:\n  " + str(environment_of(root)) + r"\nfreed \d")
        self.assertEqual([r.get("unfinished") for r in trail(root) if r["event"] == "pruned"],
                         ["2 of 3 rounds are published"], "a forced prune says what it cut short")


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
