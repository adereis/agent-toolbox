"""Blind fanouts: sealed reading, withheld numbers, unseal after judgment,
and a synthesizer seat."""

import contextlib
import io
import unittest

from convene_support import Sandbox

from convene import board, export, plan, round as round_, runs, seal
from convene.cli import main
from convene.storage import read


class FanoutTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self)

    def prepare(self, **fields):
        fields.setdefault("kind", "fanout")
        fields.setdefault("seats", [{"id": "one", "persona": "connie-tinuity"},
                                    {"id": "two", "persona": "archie-tecture", "harness": "codex",
                                     "model": "gpt-5.5", "effort": "low"},
                                    {"id": "three", "persona": "tess-tcase"}])
        fields.setdefault("brief", {"text": "[[stub:edit-repo]] Implement it."})
        root, frozen = plan.prepare(self.box.plan(**fields), project_root=self.box.project)
        return root, frozen

    def test_fanout_fixes_blindness_worktrees_and_reports(self):
        root, frozen = self.prepare()
        for seat in frozen["seats"]:
            self.assertEqual((seat["visibility"], seat["workspace"], seat["tools"]),
                             ("blind", "worktree", "write"))
            self.assertTrue((root / "work" / seat["id"] / "repo/app.py").exists())
        self.assertEqual(frozen["phases"], [{"name": "attempt", "rounds": 1, "deliverable": "report.md"}])
        self.assertEqual(frozen["instrument"]["profile"]["id"], "implement")
        self.assertIn("You work on your own; you will not see what the others write",
                      (root / "work/one/START.md").read_text())
        with self.assertRaisesRegex(ValueError, "fixes visibility"):
            self.prepare(visibility="board")

    def test_reading_is_withheld_until_sealed_judged_and_unsealed(self):
        root, frozen = self.prepare()
        played, why = round_.run(root)
        self.assertEqual(why, "done")
        for name in ("one", "two", "three"):
            self.assertTrue((root / "board/made" / name / "r001/report.md").exists())
        self.assertTrue((root / "board/made/one/r001/changes.patch").exists())
        for what, call in (("the board", lambda: seal.guard(root, frozen, "the board")),
                           ("usage", lambda: seal.guard(root, frozen, "usage")),
                           ("export", lambda: export.export(root, self.box.root / "out"))):
            with self.subTest(what=what), self.assertRaisesRegex(ValueError, "withheld.*`convene seal`"):
                call()
        data = round_.status(root)
        self.assertEqual(data["withheld"], [1])
        self.assertEqual(data["seats"]["one"]["receipts"][1]["seconds"], "withheld")
        self.assertEqual(data["seats"]["one"]["receipts"][1]["tool_calls"], "withheld")
        self.assertEqual(data["seats"]["one"]["receipts"][1]["status"], "answered")
        text = round_.render_status(data)
        self.assertIn("read sealed", text)
        self.assertIn("duration withheld, tool calls withheld", text)
        self.assertNotIn("withhelds", text)
        self.assertIn(f"next: convene seal {root.name}", text)

        result = seal.seal(root, seed=7)
        self.assertEqual(result["letters"], ["A", "B", "C"])
        sealed = root / "sealed/r001"
        key = read(sealed / "identity-key.json")
        self.assertEqual(sorted(key.values()), ["one", "three", "two"])
        for letter in "ABC":
            # The codex stub writes no repo edits, so its letter has no patch.
            expected = ["post.md", "report.md"] if key[letter] == "two" else ["changes.patch", "post.md", "report.md"]
            self.assertEqual(sorted(p.name for p in (sealed / letter).iterdir()), expected)
        self.assertIn("Deliverable report.md", (sealed / "A/report.md").read_text())
        with self.assertRaisesRegex(ValueError, "already sealed"):
            seal.seal(root)
        with self.assertRaisesRegex(ValueError, "withheld.*judgment.md"):
            seal.guard(root, frozen, "the board")
        with self.assertRaisesRegex(ValueError, "write your judgment"):
            seal.unseal(root)
        (sealed / "judgment.md").write_text("B is the one to take; A is close; C skipped tests.\n")
        unsealed = seal.unseal(root)
        self.assertEqual({k: v["seat"] for k, v in unsealed["key"].items()}, key)
        self.assertEqual(unsealed["key"]["A"]["served"], f"claude/opus" if key["A"] != "two" else "codex/gpt-5.5")
        self.assertTrue((sealed / "unsealed.json").exists())
        self.assertEqual(round_.status(root)["withheld"], [])
        self.assertIn("(one, claude/opus)", board.text(root, frozen))
        self.assertIsInstance(round_.status(root)["seats"]["one"]["receipts"][1]["tool_calls"], int)
        target = export.export(root, self.box.root / "out")
        self.assertTrue((target / "sealed/r001/judgment.md").exists())
        self.assertTrue((target / "board.md").exists())

    def test_a_committed_attempt_keeps_its_work_in_the_patch(self):
        """The patch was diffed against the worktree's HEAD, so whatever a
        seat committed vanished from its letter."""
        root, frozen = self.prepare(seats=[{"id": "one", "persona": "connie-tinuity"}],
                                    brief={"text": "[[stub:commit-repo]] Implement it."})
        round_.run(root)
        tree = root / "work/one/repo"
        self.assertNotEqual(self.box.git("-C", str(tree), "rev-parse", "HEAD").strip(),
                            frozen["base_commit"], "the seat's commit landed")
        patch = (root / "board/made/one/r001/changes.patch").read_text()
        self.assertIn("COMMITTED.md", patch)
        self.assertIn("edited by the stub seat", patch)

    def test_declared_phases_keep_their_own_deliverables(self):
        """Found by a live Antigravity seat reviewing the fanout commit."""
        root, frozen = self.prepare(rounds=2, phases=[
            {"name": "attempt", "rounds": 1, "deliverable": "notes.md"},
            {"name": "wrap", "rounds": 1, "seats": ["one"]}])
        self.assertEqual([p.get("deliverable") for p in frozen["phases"]], ["notes.md", None])

    def test_reseal_keeps_the_judgment(self):
        """Found by the same seat: --force used to delete judgment.md."""
        root, _ = self.prepare()
        round_.run(root)
        seal.seal(root, seed=1)
        (root / "sealed/r001/judgment.md").write_text("A wins.\n")
        result = seal.seal(root, seed=2, force=True)
        self.assertTrue(result["judgment_kept"])
        self.assertEqual((root / "sealed/r001/judgment.md").read_text(), "A wins.\n")
        self.assertTrue((root / "sealed/r001/A/post.md").exists())

    def test_seal_leaves_out_absent_seats(self):
        root, _ = self.prepare(seats=[{"id": "one", "persona": "connie-tinuity"},
                                      {"id": "two", "persona": "archie-tecture"}],
                               brief={"text": "Implement it."})
        (root / "work/two/START.md").write_text("[[stub:killed]] " + (root / "work/two/START.md").read_text())
        from convene.storage import digest, write
        _, frozen = runs.load(root)
        for seat in frozen["seats"]:
            if seat["id"] == "two":
                seat["start_sha256"] = digest(root / "work/two/START.md")
        write(root / "plan.json", frozen)
        write(root / "plan-digest.json", {"sha256": digest(root / "plan.json")})
        round_.run(root)
        result = seal.seal(root, seed=1)
        self.assertEqual(result["letters"], ["A"])
        self.assertEqual(read(root / "sealed/r001/identity-key.json"), {"A": "one"})

    def test_synthesizer_seat_gets_a_final_round_on_the_board(self):
        root, frozen = self.prepare(seats=[{"id": "one", "persona": "connie-tinuity"},
                                           {"id": "two", "persona": "archie-tecture"},
                                           {"id": "synth", "persona": "quinn-t-shun"}],
                                    synthesis={"by": "synth"})
        self.assertEqual(frozen["rounds"], 2)
        self.assertEqual([p["name"] for p in frozen["phases"]], ["attempt", "synthesis"])
        self.assertEqual(frozen["phases"][0]["seats"], ["one", "two"])
        self.assertEqual(frozen["phases"][1], {"name": "synthesis", "rounds": 1, "seats": ["synth"],
                                               "instruction": frozen["phases"][1]["instruction"]})
        self.assertIn("You are synthesizing", frozen["phases"][1]["instruction"])
        self.assertIn("Your post is the synthesis", frozen["phases"][1]["instruction"])
        synth = next(s for s in frozen["seats"] if s["id"] == "synth")
        self.assertEqual((synth["visibility"], synth["workspace"], synth["tools"]), ("board", "none", "read"))
        played, why = round_.run(root)
        self.assertEqual(why, "done")
        self.assertEqual([n for n, _ in played], [1, 2])
        prompt = (root / "records/synth/r002/prompt.md").read_text()
        self.assertIn("The others have posted; the latest board is board/round-001/digest.md", prompt)
        self.assertNotIn("joining a room already in progress", prompt)
        # The seat keeps the read tool set, which cannot write a file, so
        # the synthesis travels as its post rather than as outbox/synthesis.md.
        self.assertNotIn("outbox/", prompt)
        self.assertTrue((root / "work/synth/board/round-001/digest.md").exists())
        self.assertFalse(list((root / "work/one/board").iterdir()), "attempt seats stay blind")
        self.assertTrue(board.post_path(root, "synth", 2).exists())
        self.assertFalse((root / "board/made/synth").exists())
        self.assertEqual(len(self.box.calls("synth", "claude")), 1)
        self.assertIsNone(round_.status(root)["seats"]["synth"]["joined_late"])
        self.assertEqual(round_.status(root)["withheld"], [1, 2])
        with self.assertRaisesRegex(ValueError, "may not act in a declared phase"):
            self.prepare(seats=[{"id": "one", "persona": "connie-tinuity"},
                                {"id": "synth", "persona": "quinn-t-shun"}],
                         synthesis={"by": "synth"}, phases=[{"name": "attempt", "rounds": 1}])
        with self.assertRaisesRegex(ValueError, "names no seat"):
            self.prepare(synthesis={"by": "nobody"})

    def test_seal_letters_the_attempts_not_the_synthesis(self):
        """`seal` used to letter the latest round, which was the synthesizer's,
        and the board then stayed withheld behind a round nobody could unseal."""
        root, frozen = self.prepare(seats=[{"id": "one", "persona": "connie-tinuity"},
                                           {"id": "two", "persona": "archie-tecture"},
                                           {"id": "synth", "persona": "quinn-t-shun"}],
                                    synthesis={"by": "synth"})
        round_.run(root)
        self.assertEqual(round_.status(root)["next"], f"convene seal {root.name}")
        result = seal.seal(root, seed=1)
        self.assertEqual(result["round"], 1)
        self.assertEqual(sorted(read(root / "sealed/r001/identity-key.json").values()),
                         ["one", "two"])
        with self.assertRaisesRegex(ValueError, "round 2 has no blind seat"):
            seal.seal(root, 2)
        # The synthesis names seats by id, so it stays withheld with the attempts.
        self.assertEqual(round_.status(root)["withheld"], [1, 2])
        with self.assertRaisesRegex(ValueError, "withheld while round 1 .*sealed/r001/"):
            seal.guard(root, frozen, "the board")
        (root / "sealed/r001/judgment.md").write_text("A.\n")
        self.assertEqual(seal.unseal(root)["round"], 1)
        self.assertEqual(round_.status(root)["withheld"], [])
        self.assertIn("(synth, claude/opus)", board.text(root, frozen))
        self.assertTrue(export.export(root, self.box.root / "out").exists())

    JUDGED = [{"id": "one", "persona": "connie-tinuity"},
              {"id": "two", "persona": "archie-tecture", "harness": "codex", "model": "gpt-5.5",
               "effort": "low"},
              {"id": "judge", "persona": "quinn-t-shun"}]

    def judged(self, *extra, **fields):
        seats = [dict(s) for s in self.JUDGED] + list(extra)
        return self.prepare(seats=seats, judgment={"by": "judge"}, **fields)

    def test_judge_seat_rules_on_the_letters_alone(self):
        root, frozen = self.judged()
        judge = next(s for s in frozen["seats"] if s["id"] == "judge")
        self.assertEqual((judge["visibility"], judge["workspace"], judge["tools"]),
                         ("sealed", "none", "read"))
        self.assertEqual([(p["name"], p.get("seats"), p.get("deliverable")) for p in frozen["phases"]],
                         [("attempt", ["one", "two"], "report.md"), ("judgment", ["judge"], None)])
        start = (root / "work/judge/START.md").read_text()
        self.assertIn("You are judging 2 attempts", start)
        self.assertNotIn("Report what you built", start, "the attempts' instrument is not the judge's")
        played, why = round_.run(root)
        self.assertEqual(why, "done")
        self.assertEqual([n for n, _ in played], [1, 2])
        # The engine sealed the attempts before the judge's round opened and
        # staged the letters' own files, never the key beside them.
        self.assertEqual(sorted(read(root / "sealed/r001/identity-key.json").values()), ["one", "two"])
        staged = root / "work/judge/sealed"
        self.assertEqual(sorted(p.name for p in staged.iterdir()), ["A", "B"])
        for letter in "AB":
            self.assertEqual(sorted(p.name for p in (staged / letter).iterdir()),
                             sorted(p.name for p in (root / "sealed/r001" / letter).iterdir()))
        names = {p.name for p in (root / "work/judge").rglob("*")}
        self.assertFalse(names & {"identity-key.json", "seal.json"}, "the key never reaches the judge")
        self.assertFalse(list((root / "work/judge/board").iterdir()), "the judge sees no board")
        self.assertIn("You are judging, not competing",
                      (root / "records/judge/r002/prompt.md").read_text())
        # Its post is the judgment, filed where unseal looks for one.
        post = board.post_path(root, "judge", 2).read_text()
        self.assertIn("I judged A, B.", post)
        self.assertEqual((root / "sealed/r001/judgment.md").read_text(), post)
        data = round_.status(root)
        self.assertEqual(data["withheld"], [1, 2])
        self.assertTrue(data["next"].startswith(f"convene unseal {root.name}; the judgment by judge"))
        flags = data["seats"]["judge"]["receipts"][2]["red_flags"]
        self.assertTrue(any(f.startswith("judging is advisory") for f in flags), flags)
        with self.assertRaisesRegex(ValueError, "judgment.md is on file, so `convene unseal`"):
            seal.guard(root, frozen, "the board")
        unsealed = seal.unseal(root)
        self.assertEqual(unsealed["judged_by"],
                         {"seat": "judge", "served": "claude/opus", "tier": "private-home"})
        self.assertEqual(read(root / "sealed/r001/unsealed.json")["judged_by"]["seat"], "judge")
        self.assertEqual(round_.status(root)["withheld"], [])

    def test_the_judge_rules_before_anyone_reads_the_letters(self):
        root, frozen = self.judged()
        round_.run_round(root, 1)
        self.assertEqual(round_.status(root)["next"],
                         f"convene run {root.name}; the judge judge reads round 1 sealed next")
        with self.assertRaisesRegex(ValueError, "`convene run` lets the judge seat 'judge' rule"):
            seal.guard(root, frozen, "the board")
        # A judgment already on file is never overwritten by the judge.
        seal.seal(root, seed=1)
        (root / "sealed/r001/judgment.md").write_text("Mine.\n")
        with self.assertRaisesRegex(ValueError, "already has a judgment.md on file.*aside"):
            round_.run_round(root, 2)
        (root / "sealed/r001/judgment.md").unlink()
        round_.run_round(root, 2)
        self.assertEqual(read(root / "sealed/r001/seal.json")["round"], 1, "the operator's seal is reused")
        # An operator's edit of the judge's words is no longer the judge's judgment.
        with open(root / "sealed/r001/judgment.md", "a") as handle:
            handle.write("Edited.\n")
        self.assertEqual(seal.unseal(root)["judged_by"], {"seat": "operator"})

    def test_judge_then_synthesizer(self):
        root, frozen = self.judged({"id": "synth", "persona": "tess-tcase"},
                                   synthesis={"by": "synth"})
        self.assertEqual([p["name"] for p in frozen["phases"]], ["attempt", "judgment", "synthesis"])
        # The appended phases once shadowed prepare's own `name` argument and
        # named the run after the last of them.
        self.assertRegex(root.name, r"^\d{4}-\d{2}-\d{2}-fanout-")
        round_.run(root)
        self.assertEqual(board.published_rounds(root), [1, 2, 3])
        self.assertEqual(seal.sealed_rounds(root), [1])
        self.assertIn("(judge)", (root / "work/synth/board/round-002/digest.md").read_text())
        self.assertEqual(round_.status(root)["withheld"], [1, 2, 3])
        seal.unseal(root)
        self.assertEqual(round_.status(root)["withheld"], [])

    def test_judge_plans_are_refused_by_name(self):
        for fields, message in (
            ({"kind": "room", "judgment": {"by": "judge"}}, "applies to kind = \"fanout\" only"),
            ({"judgment": {"by": "one"}, "synthesis": {"by": "one"}}, "cannot both judge and synthesize"),
            ({"judgment": {"by": "nobody"}}, "judgment.by names no seat"),
            ({"judgment": {"by": 3}}, "judgment.by must be"),
        ):
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, message):
                self.prepare(seats=[dict(s) for s in self.JUDGED], **fields)
        repo = [dict(s) for s in self.JUDGED]
        repo[2]["workspace"] = "repo-ro"
        with self.assertRaisesRegex(ValueError, "takes workspace = \"none\""):
            self.prepare(seats=repo, judgment={"by": "judge"})
        with self.assertRaisesRegex(ValueError, "visibility = \"sealed\" is the judge's"):
            self.prepare(seats=[{"id": "one", "persona": "connie-tinuity", "visibility": "sealed"}])
        with self.assertRaisesRegex(ValueError, "the judge 'judge' may not act in a declared phase"):
            self.judged(phases=[{"name": "attempt", "rounds": 1}])

    def test_cli_seal_and_unseal(self):
        root, _ = self.prepare()
        run = lambda *a: main(["--project", str(self.box.project), *a])  # noqa: E731
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(run("run", root.name), 0)
            self.assertEqual(run("board", root.name), 1)
            self.assertEqual(run("seal", root.name, "--seed", "3"), 0)
            self.assertEqual(run("unseal", root.name), 1)
            (root / "sealed/r001/judgment.md").write_text("A.\n")
            self.assertEqual(run("unseal", root.name), 0)
            self.assertEqual(run("board", root.name), 0)
        text = out.getvalue()
        key = read(root / "sealed/r001/identity-key.json")
        self.assertNotIn(str(key), text)
        self.assertIn("round 1 sealed as A, B, C", text)
        self.assertIn(f"A = {key['A']}", text)
        self.assertIn("withheld", err.getvalue())
        self.assertIn("write your judgment", err.getvalue())


if __name__ == "__main__":
    unittest.main()
