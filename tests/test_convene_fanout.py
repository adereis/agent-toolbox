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
        self.assertIn("read sealed", round_.render_status(data))

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
                                               "deliverable": "synthesis.md",
                                               "instruction": frozen["phases"][1]["instruction"]})
        self.assertIn("You are synthesizing", frozen["phases"][1]["instruction"])
        synth = next(s for s in frozen["seats"] if s["id"] == "synth")
        self.assertEqual((synth["visibility"], synth["workspace"], synth["tools"]), ("board", "none", "read"))
        played, why = round_.run(root)
        self.assertEqual(why, "done")
        self.assertEqual([n for n, _ in played], [1, 2])
        prompt = (root / "records/synth/r002/prompt.md").read_text()
        self.assertIn("The others have posted; the latest board is board/round-001/digest.md", prompt)
        self.assertNotIn("joining a room already in progress", prompt)
        self.assertIn("Write the work itself to outbox/synthesis.md", prompt)
        self.assertTrue((root / "work/synth/board/round-001/digest.md").exists())
        self.assertFalse(list((root / "work/one/board").iterdir()), "attempt seats stay blind")
        self.assertTrue((root / "board/made/synth/r002/synthesis.md").exists())
        self.assertEqual(len(self.box.calls("synth", "claude")), 1)
        self.assertIsNone(round_.status(root)["seats"]["synth"]["joined_late"])
        self.assertEqual(round_.status(root)["withheld"], [1, 2])
        with self.assertRaisesRegex(ValueError, "may not act in a declared phase"):
            self.prepare(seats=[{"id": "one", "persona": "connie-tinuity"},
                                {"id": "synth", "persona": "quinn-t-shun"}],
                         synthesis={"by": "synth"}, phases=[{"name": "attempt", "rounds": 1}])
        with self.assertRaisesRegex(ValueError, "names no seat"):
            self.prepare(synthesis={"by": "nobody"})

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
