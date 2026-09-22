"""Plan validation, freezing and staging for the convene plugin."""

import json
import os
import unittest
from pathlib import Path

from convene_support import PLUGIN, Sandbox  # noqa: F401  (sets sys.path)

from convene import harnesses, instruments, personas, plan, round as round_, runs
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

    def test_claude_seat_resolves_user_shorthand_without_a_version_list(self):
        """`opus-5.5` is what a person says; `claude-opus-5-5` is what the CLI takes."""
        for said, taken in (("opus-5.5", "claude-opus-5-5"), ("Opus-5", "claude-opus-5"),
                            ("claude-opus", "opus"), ("Fable", "fable"),
                            ("claude-unreleased-9", "claude-unreleased-9")):
            with self.subTest(model=said):
                root, frozen = self.prepare(self.box.plan(seats=[
                    {"id": "a", "persona": "sec-urity", "harness": "claude", "model": said}]))
                self.assertEqual(frozen["seats"][0]["model"], taken)
        # An id nothing lists still runs, so a release needs no code change,
        # but the plan records that only the receipt will verify it.
        self.assertIn("receipt verifies",
                      harnesses.get("claude").resolve("claude-unreleased-9", "high")["catalog"])
        # A string that is neither an alias nor a Claude version is refused
        # here rather than at launch, where it returns `unrecognized_model`.
        for bogus in ("opus5", "gpt-5", "terra"):
            with self.subTest(model=bogus):
                with self.assertRaisesRegex(ValueError, "not a name Claude Code accepts"):
                    self.prepare(self.box.plan(seats=[
                        {"id": "a", "persona": "sec-urity", "harness": "claude",
                         "model": bogus}]))

    def test_codex_family_resolves_to_its_newest_listed_version(self):
        """A plan says `terra`; a Terra released tomorrow needs no code change."""
        root, frozen = self.prepare(self.box.plan(seats=[
            {"id": "a", "persona": "sec-urity", "harness": "codex", "model": "Terra"}]))
        seat = frozen["seats"][0]
        # Newer than gpt-5.4-terra; the hidden gpt-7-terra is Codex's own.
        self.assertEqual(seat["model"], "gpt-5.6-terra")
        self.assertEqual(seat["model_requested"], "Terra")
        self.assertEqual(seat["context_window"], 872000)
        self.assertIn("codex/gpt-5.6-terra (from Terra) effort=high",
                      round_.render_status(round_.status(root)))
        # A family with a single member, newer than every other family.
        root, frozen = self.prepare(self.box.plan(seats=[
            {"id": "a", "persona": "sec-urity", "harness": "codex", "model": "astra"}]))
        self.assertEqual(frozen["seats"][0]["model"], "gpt-6-astra")
        # An exact slug pins, and records no family.
        root, frozen = self.prepare(self.box.plan(seats=[
            {"id": "a", "persona": "sec-urity", "harness": "codex", "model": "gpt-5.4-terra"}]))
        self.assertEqual(frozen["seats"][0]["model"], "gpt-5.4-terra")
        self.assertNotIn("model_requested", frozen["seats"][0])
        # An unknown family is refused with the families that exist.
        with self.assertRaisesRegex(ValueError, "families gpt, gpt-astra, gpt-sol, gpt-terra"):
            self.prepare(self.box.plan(seats=[
                {"id": "a", "persona": "sec-urity", "harness": "codex", "model": "nova"}]))
        # Without a catalog a family cannot resolve, and says what would.
        (self.box.home / ".codex/models_cache.json").unlink()
        with self.assertRaisesRegex(ValueError, "is a family.*start codex once"):
            self.prepare(self.box.plan(seats=[
                {"id": "a", "persona": "sec-urity", "harness": "codex", "model": "terra"}]))

    def test_family_resolution_rules(self):
        slugs = ["gpt-5.5", "gpt-5.4-terra", "gpt-5.10-terra", "gpt-6-terra-mini",
                 "gemini-3.8-flash", "gemini-3.1-pro", "claude-haiku-4-5-20251001"]
        pick = harnesses.newest_in_family
        # Versions compare as numbers, so 5.10 is newer than 5.4, and the
        # plainest member wins: the newer gpt-6-terra-mini is not `terra`.
        self.assertEqual(pick("terra", slugs), "gpt-5.10-terra")
        self.assertEqual(pick("terra-mini", slugs), "gpt-6-terra-mini")
        self.assertEqual(pick("Gemini-Pro", slugs), "gemini-3.1-pro")
        self.assertEqual(pick("haiku", slugs), "claude-haiku-4-5-20251001")
        self.assertIsNone(pick("luna", slugs))
        with self.assertRaisesRegex(ValueError, r"more than one family \(gemini-flash, gemini-pro\)"):
            pick("gemini", slugs)
        self.assertTrue(harnesses.is_family("gemini-pro"))
        self.assertFalse(harnesses.is_family("gpt-5.6-terra"))
        # The served id satisfies a family when it carries every family word;
        # `fable` failed here once, because only three aliases were known.
        match = harnesses.model_matches
        self.assertTrue(match("fable", "claude-fable-5-1"))
        self.assertTrue(match("opus", "claude-opus-5-5"))
        self.assertFalse(match("opus", "claude-sonnet-5"))
        self.assertTrue(match("claude-opus-5-5", "claude-opus-5-5-20260901"))
        self.assertFalse(match("claude-opus-5", "claude-opus-5-5"))
        self.assertFalse(match("opus", None))

    def test_a_seat_without_a_model_takes_its_own_harness_default(self):
        """One default across harnesses would hand `opus` to Gemini."""
        self.assertIsNone(plan.DEFAULTS["model"], "no cross-harness model default")
        for name, expected in (("claude", "opus"), ("codex", "terra"),
                               ("agy", "gemini-pro")):
            with self.subTest(harness=name):
                self.assertEqual(harnesses.get(name).default_model, expected)
        # Stated as invariants, not as a list: a harness added later that
        # forgets a default would pass `None` to a CLI as the string "None",
        # and one that names a version would go stale at the next release.
        for name, harness in harnesses.registry().items():
            with self.subTest(harness=name):
                self.assertIsNotNone(harness.default_model,
                                     f"{name} must name the model a seat gets by default")
                self.assertTrue(harnesses.is_family(harness.default_model),
                                f"{name} must default to a family, not a version")
        # End to end, where the plan names no model at any level, for each
        # harness whose catalog the sandbox can stand in for.
        for name, expected in (("claude", "opus"), ("codex", "gpt-5.6-terra")):
            with self.subTest(harness=name):
                root, frozen = self.prepare(self.box.plan(model=None, seats=[
                    {"id": "a", "persona": "sec-urity", "harness": name}]))
                self.assertEqual(frozen["seats"][0]["model"], expected)

    def test_an_audited_harness_widens_an_inherited_tool_set_and_says_so(self):
        """A review panel writes `tools = "read"` once, for every seat."""
        root, frozen = self.prepare(self.box.plan(tools="read", seats=[
            {"id": "a", "persona": "sec-urity", "harness": "agy",
             "model": "gemini-3.1-pro", "isolation": "none"}]))
        seat = frozen["seats"][0]
        self.assertEqual(seat["tools"], "write")
        self.assertEqual(seat["tools_relaxed"]["requested"], "read")
        self.assertEqual(seat["tools_relaxed"]["used"], "write")
        # Named on the seat it is refused, because widening past what the
        # plan spelled out for this seat is not a default to be corrected.
        with self.assertRaisesRegex(ValueError, "cannot confine a seat"):
            self.prepare(self.box.plan(seats=[
                {"id": "a", "persona": "sec-urity", "harness": "agy",
                 "model": "gemini-3.1-pro", "isolation": "none", "tools": "read"}]))

    def test_every_harness_can_take_raw_arguments_from_the_plan(self):
        """`agy` is a first-class harness, so `agy_args` must reach the seat."""
        for harness in ("claude", "codex", "agy"):
            with self.subTest(harness=harness):
                self.assertIn(f"{harness}_args", plan.ACCESS_FIELDS)
                self.assertIn(f"{harness}_args", plan.DEFAULTS)

    def test_unsupported_plan_shapes_are_refused_by_name(self):
        for fields, message in (
            ({"synthesis": {"by": "skeptic"}}, "needs at least one other seat"),
            ({"synthesis": {"by": 3}}, "synthesis.by must be"),
            ({"workspace": "worktree"}, "needs tools"),
            ({"phases": [{"name": "a", "rounds": 1, "deliverable": "changes.patch"}]},
             "captured from a worktree"),
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
        self.assertEqual(set(instruments.catalog()), {"review", "design", "implement", "synthesize"})
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
