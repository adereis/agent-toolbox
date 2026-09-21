"""Plan validation, freezing and staging for the convene plugin."""

import json
import os
import unittest
from pathlib import Path

from convene_support import PLUGIN, Sandbox  # noqa: F401  (sets sys.path)

from convene import instruments, personas, plan, runs
from convene.presets import panel
from convene.storage import read


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self)

    def prepare(self, path, **kwargs):
        kwargs.setdefault("project_root", self.box.project)
        kwargs.setdefault("range_spec", "HEAD~1..HEAD")
        return plan.prepare(path, **kwargs)

    def test_panel_freezes_defaults_materials_and_start_text(self):
        root, frozen = self.prepare(self.box.plan(materials=[
            {"path": "docs.md", "label": "the design note"}]))
        self.assertTrue((root / "plan.json").is_file())
        self.assertEqual(read(root / "plan-digest.json")["sha256"],
                         __import__("convene.storage", fromlist=["digest"]).digest(root / "plan.json"))
        seat = frozen["seats"][0]
        self.assertEqual(seat["workspace"], "repo-ro", "a panel stands in the read-only repository")
        self.assertEqual(seat["isolation"], "private-home")
        self.assertEqual(seat["tools"], "read")
        self.assertEqual(seat["model"], "opus")
        self.assertEqual(sorted(seat["reads"]), ["diff.patch", "docs.md", "log.txt"])
        start = (root / "work/skeptic/START.md").read_text()
        self.assertIn("Quinn T. Shun", start)
        self.assertIn("the design note (materials/docs.md)", start)
        self.assertIn("Break addition", (root / "work/skeptic/materials/log.txt").read_text())
        self.assertIn("-    return a + b", (root / "work/skeptic/materials/diff.patch").read_text())
        self.assertNotIn("opus", start.lower(), "model names never reach a seat")
        self.assertIn("Report findings", start)
        self.assertTrue((root / ".gitignore").exists())
        self.assertTrue(str(root).startswith(str(self.box.state)), "state lives under XDG, not the project")

    def test_run_names_are_dated_and_do_not_collide(self):
        first, _ = self.prepare(self.box.plan())
        second, _ = self.prepare(self.box.plan())
        self.assertNotEqual(first, second)
        self.assertTrue(second.name.endswith("-2"))
        with self.assertRaisesRegex(ValueError, "run exists"):
            self.prepare(self.box.plan(), name=first.name)

    def test_tools_none_cannot_take_materials(self):
        with self.assertRaisesRegex(ValueError, "cannot read materials"):
            self.prepare(self.box.plan(seats=[{"id": "a", "persona": "sec-urity", "tools": "none"}]))

    def test_codex_seat_resolves_effort_and_window_from_the_catalog(self):
        root, frozen = self.prepare(self.box.plan(seats=[
            {"id": "a", "persona": "sec-urity", "harness": "codex", "model": "gpt-5-6-sol",
             "effort": "xhigh"}]))
        seat = frozen["seats"][0]
        self.assertEqual(seat["model"], "gpt-5.6-sol")
        self.assertEqual(seat["context_window"], 872000)
        with self.assertRaisesRegex(ValueError, "supports efforts"):
            self.prepare(self.box.plan(seats=[{"id": "a", "persona": "sec-urity",
                                               "harness": "codex", "model": "gpt-5.5",
                                               "effort": "xhigh"}]))
        with self.assertRaisesRegex(ValueError, "does not list"):
            self.prepare(self.box.plan(seats=[{"id": "a", "persona": "sec-urity",
                                               "harness": "codex", "model": "gpt-9"}]))

    def test_later_phase_features_are_refused_by_name(self):
        for fields, message in (
            ({"rounds": 2}, "more than one round"),
            ({"workspace": "worktree"}, "worktree"),
            ({"synthesis": {"by": "skeptic"}}, "synthesis by a seat"),
        ):
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, message):
                self.prepare(self.box.plan(**fields))

    def test_unknown_persona_names_where_it_looked(self):
        with self.assertRaisesRegex(ValueError, "unknown persona 'nobody'.*personas list"):
            self.prepare(self.box.plan(seats=[{"id": "a", "persona": "nobody"}]))

    def test_project_persona_shadows_plugin_persona(self):
        directory = self.box.project / ".convene/personas"
        directory.mkdir(parents=True)
        (directory / "quinn-t-shun.json").write_text(json.dumps({
            "schema_version": 1, "id": "quinn-t-shun", "revision": 7, "label": "Local Quinn",
            "description": "project override", "tags": ["skeptic"], "prompt": "You are Local Quinn."}))
        root, frozen = self.prepare(self.box.plan())
        self.assertEqual(frozen["seats"][0]["persona"]["profile"]["revision"], 7)
        self.assertIn("You are Local Quinn.", (root / "work/skeptic/START.md").read_text())

    def test_instruction_files_never_travel_as_materials(self):
        for path in ("AGENTS.md", "docs/../CLAUDE.md", ".claude/settings.json"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "instruction files|invalid relative"):
                self.prepare(self.box.plan(materials=[{"path": path}]))

    def test_symlinked_material_is_refused(self):
        (self.box.project / "link.md").symlink_to(self.box.project / "docs.md")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.prepare(self.box.plan(materials=[{"path": "link.md"}]))

    def test_range_resolution(self):
        with self.assertRaisesRegex(ValueError, "covers no commits"):
            panel.resolve_range(self.box.project, "HEAD..HEAD")
        with self.assertRaisesRegex(ValueError, "not a git range"):
            panel.resolve_range(self.box.project, "main")
        with self.assertRaisesRegex(ValueError, "working tree, and it is clean"):
            panel.resolve_range(self.box.project, "HEAD")
        (self.box.project / "app.py").write_text("changed\n")
        delta = panel.resolve_range(self.box.project, "HEAD")
        self.assertEqual(delta["kind"], "worktree")
        staged = panel.materials(self.box.project, delta)
        self.assertIn("changed", staged[0]["text"])

    def test_plugin_catalogs_validate(self):
        names = set(personas.catalog())
        self.assertEqual(names, {"quinn-t-shun", "ada-versary", "connie-tinuity", "emma-pirical",
                                 "sec-urity", "axel-cess", "archie-tecture", "tess-tcase",
                                 "xavier-pert", "percy-formance"})
        self.assertEqual(set(instruments.catalog()), {"review", "design", "implement"})
        self.assertIn("json_schema", instruments.catalog()["review"]["profile"])

    def test_run_resolution_by_name_and_path(self):
        root, frozen = self.prepare(self.box.plan())
        self.assertEqual(runs.resolve(frozen["name"], self.box.project), root)
        self.assertEqual(runs.resolve(str(root), self.box.project), root)
        with self.assertRaisesRegex(ValueError, "no run at"):
            runs.resolve("missing", self.box.project)
        self.assertEqual(runs.latest(self.box.project), root)


if __name__ == "__main__":
    unittest.main()
