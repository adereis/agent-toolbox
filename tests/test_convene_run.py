"""End-to-end runs of the convene engine against stub harnesses."""

import json
import os
import unittest
from pathlib import Path

from convene_support import Sandbox

from convene import board, export, plan, round as round_, runs
from convene.cli import main
from convene.storage import read


class RunTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self)

    def prepare(self, **fields):
        fields.setdefault("seats", [{"id": "skeptic", "persona": "quinn-t-shun"},
                                    {"id": "maintainer", "persona": "connie-tinuity",
                                     "harness": "codex", "model": "gpt-5.5", "effort": "medium"}])
        root, frozen = plan.prepare(self.box.plan(**fields), project_root=self.box.project,
                                    range_spec="HEAD~1..HEAD")
        return root, frozen

    def receipt(self, root, seat, n=1):
        return read(root / "records" / seat / f"r{n:03d}" / "receipt.json")

    def test_two_harness_panel_runs_promotes_and_exports(self):
        root, frozen = self.prepare()
        played, why = round_.run(root)
        self.assertEqual(why, "done")
        self.assertEqual(played[0][1]["_board"]["posted"], ["maintainer", "skeptic"])
        claude, codex = self.receipt(root, "skeptic"), self.receipt(root, "maintainer")
        self.assertEqual(claude["status"], "answered")
        self.assertEqual(claude["model"], "claude-opus-5-20260601")
        self.assertEqual(claude["requested_model"], "opus")
        self.assertEqual(claude["isolation"]["tier"], "private-home")
        self.assertTrue(claude["isolation"]["advisory"])
        self.assertIn("isolation is advisory", " ".join(claude["red_flags"]))
        self.assertTrue(claude["inputs_intact"])
        self.assertEqual(codex["status"], "answered")
        self.assertEqual(codex["model"], "gpt-5.5")
        self.assertEqual(codex["effort_evidence"], "native turn context")
        text = board.text(root, frozen)
        self.assertIn("(skeptic, claude/opus)", text)
        self.assertIn("(maintainer, codex/gpt-5.5)", text)
        self.assertNotIn("claude/opus", board.text(root, frozen, attribute=False))
        self.assertIn("Stub finding", text)
        target = self.box.root / "export"
        export.export(root, target)
        self.assertTrue((target / "board.md").is_file())
        summary = read(target / "summary.json")
        self.assertEqual(summary["receipts"]["skeptic"]["r001"]["tier"], "private-home")
        self.assertIsNone(summary["usage"][1]["cost_usd"], "codex reports no price; never zero")
        self.assertAlmostEqual(summary["usage"][0]["cost_usd"], 0.0123)
        self.assertFalse((target / "records/skeptic/r001/events.jsonl").exists())
        # A second run finds nothing to do and relaunches nobody.
        played, why = round_.run(root)
        self.assertEqual((played, why), ([], "done"))
        self.assertEqual(len(self.box.calls("skeptic", "claude")), 1)

    def test_private_home_seat_sees_only_its_own_home_and_the_access_token(self):
        root, _ = self.prepare(seats=[{"id": "skeptic", "persona": "quinn-t-shun"}],
                               brief={"text": "[[stub:canary]] Review."})
        round_.run(root)
        call = self.box.calls("skeptic", "claude")[0]
        self.assertEqual(call["env"]["HOME"], str(root / "homes/skeptic"))
        self.assertEqual(call["env"]["CLAUDE_CONFIG_DIR"], str(root / "homes/skeptic/claude"))
        self.assertEqual(call["env"]["CLAUDE_CODE_OAUTH_TOKEN"], "sk-ant-oat-fake-access")
        self.assertIsNone(call["env"]["SECRET_FROM_OPERATOR"], "the environment is an allow-list")
        self.assertEqual(call["cwd"], str(root / "work/skeptic"))
        answer = (root / "records/skeptic/r001/answer.md").read_text()
        self.assertIn("READ=ok", answer, "repo-ro is advisory here: the tree is readable")
        self.assertIn("TOKEN=yes SECRET=no", answer)
        launch = read(root / "records/skeptic/r001/launch.json")
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", launch["environment"])
        self.assertNotIn("sk-ant", json.dumps(launch), "values never enter the record")
        self.assertTrue((root / "homes/skeptic/claude/.claude.json").exists())
        self.assertFalse((root / "homes/skeptic/claude/.credentials.json").exists(),
                         "the refresh token never enters a seat")
        argv = launch["argv"]
        self.assertIn("--setting-sources", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Glob,Grep")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--autocompact", argv)

    def test_codex_login_is_staged_for_the_turn_and_removed_after(self):
        root, _ = self.prepare(seats=[{"id": "m", "persona": "sec-urity", "harness": "codex",
                                       "model": "gpt-5.5", "effort": "low"}])
        round_.run(root)
        call = self.box.calls("m", "codex")[0]
        self.assertTrue(call["had_auth"])
        self.assertFalse((root / "homes/m/codex/auth.json").exists())
        self.assertTrue(list((root / "homes/m/codex/sessions").rglob("*.jsonl")))
        argv = call["argv"]
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertIn("--ignore-user-config", argv)
        self.assertIn('web_search="disabled"', argv)
        self.assertIn("model_context_window=272000", argv)

    def test_served_model_mismatch_fails_the_seat_loudly(self):
        root, _ = self.prepare(brief={"text": "[[stub:mismatch]] Review."})
        played, why = round_.run(root)
        self.assertEqual(why, "done")
        claude, codex = self.receipt(root, "skeptic"), self.receipt(root, "maintainer")
        self.assertEqual(claude["status"], "failed")
        self.assertIn("served claude-sonnet-4-20250514, requested opus", claude["error"])
        self.assertEqual(codex["status"], "failed")
        self.assertIn("gpt-4.1-mini", codex["error"])
        self.assertEqual(played[0][1]["_board"]["absent"], ["skeptic", "maintainer"])
        self.assertIn("No post this round from", board.text(root, runs.load(root)[1]))

    def test_quota_refused_holds_the_round_and_keeps_no_session(self):
        root, _ = self.prepare(brief={"text": "[[stub:quota-refused]] Review."})
        played, why = round_.run(root)
        self.assertEqual(why, "held on maintainer, skeptic")
        self.assertEqual(board.published_rounds(root), [])
        for seat in ("skeptic", "maintainer"):
            got = self.receipt(root, seat)
            self.assertEqual(got["status"], "quota")
            self.assertEqual(got["quota_stop"], "refused")
            self.assertIsNone(read(root / "records" / seat / "state.json")["session_id"])
        self.assertEqual(self.receipt(root, "skeptic")["quota_scope"], "five_hour")
        data = round_.status(root)
        self.assertEqual(data["held"][0]["waiting_on"], ["maintainer", "skeptic"])
        self.assertIn("HELD", round_.render_status(data))

    def test_quota_interrupted_keeps_the_session_for_a_continuation(self):
        root, _ = self.prepare(brief={"text": "[[stub:quota-interrupted]] Review."})
        round_.run(root)
        for seat in ("skeptic", "maintainer"):
            self.assertEqual(self.receipt(root, seat)["quota_stop"], "interrupted")
            self.assertIsNotNone(read(root / "records" / seat / "state.json")["session_id"])

    def test_compaction_is_a_red_flag_not_a_failure(self):
        root, _ = self.prepare(brief={"text": "[[stub:compaction]] Review."})
        round_.run(root)
        for seat in ("skeptic", "maintainer"):
            got = self.receipt(root, seat)
            self.assertEqual(got["status"], "answered")
            self.assertTrue(got["compaction_observed"])
            self.assertIn("compaction observed", " ".join(got["red_flags"]))

    def test_killed_seat_is_a_failure_with_the_stream_kept(self):
        root, _ = self.prepare(seats=[{"id": "skeptic", "persona": "quinn-t-shun"}],
                               brief={"text": "[[stub:killed]] Review."})
        round_.run(root)
        got = self.receipt(root, "skeptic")
        self.assertEqual(got["status"], "failed")
        self.assertEqual(got["exit_code"], 137)
        self.assertTrue((root / "records/skeptic/r001/events.jsonl").stat().st_size)

    def test_forbidden_tools_fail_the_receipt(self):
        for scenario, message in (("mcp", "connected-service"), ("web", "network tool")):
            with self.subTest(scenario=scenario):
                root, _ = self.prepare(seats=[{"id": "skeptic", "persona": "quinn-t-shun"}],
                                       brief={"text": f"[[stub:{scenario}]] Review."})
                round_.run(root)
                got = self.receipt(root, "skeptic")
                self.assertEqual(got["status"], "failed")
                self.assertIn(message, got["error"])
        root, _ = self.prepare(seats=[{"id": "skeptic", "persona": "quinn-t-shun"},
                                      {"id": "m", "persona": "sec-urity", "harness": "codex",
                                       "model": "gpt-5.5", "effort": "low"}],
                               brief={"text": "[[stub:tools]] Review."})
        round_.run(root)
        self.assertEqual(self.receipt(root, "skeptic")["tool_calls"], 1)
        self.assertEqual(self.receipt(root, "skeptic")["tools_used"], ["Read"])
        self.assertEqual(self.receipt(root, "m")["tools_used"], ["command_execution"])

    def test_tampered_materials_stop_the_turn(self):
        root, _ = self.prepare(seats=[{"id": "skeptic", "persona": "quinn-t-shun"}])
        (root / "work/skeptic/materials/diff.patch").write_text("edited\n")
        played, _ = round_.run(root)
        self.assertIn("stopped: seat materials changed", played[0][1]["skeptic"])
        self.assertEqual(self.box.calls("skeptic", "claude"), [])

    def test_tier_none_runs_in_the_operators_home(self):
        real = self.box.home / "real-claude"
        os.environ["CLAUDE_CONFIG_DIR"] = str(real)
        self.box.write_claude_credentials()
        root, _ = self.prepare(seats=[{"id": "skeptic", "persona": "quinn-t-shun",
                                       "isolation": "none"}],
                               brief={"text": "[[stub:canary]] Review."})
        round_.run(root)
        got = self.receipt(root, "skeptic")
        self.assertEqual(got["status"], "answered")
        self.assertEqual(got["isolation"]["tier"], "none")
        self.assertIn("no isolation", " ".join(got["red_flags"]))
        self.assertTrue(list((real / "projects").rglob("*.jsonl")))
        self.assertIn(f"HOME={self.box.home} ", (root / "records/skeptic/r001/answer.md").read_text())

    def test_expiring_claude_token_is_refused_before_launch(self):
        self.box.write_claude_credentials(expires_in=60)
        root, _ = self.prepare(seats=[{"id": "skeptic", "persona": "quinn-t-shun"}])
        played, _ = round_.run(root)
        self.assertIn("expiring", played[0][1]["skeptic"])

    def test_cli_round_trip(self):
        import contextlib
        import io
        plan_path = self.box.plan()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--project", str(self.box.project), "prepare", str(plan_path),
                         "--range", "HEAD~1..HEAD", "--name", "trial"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("isolation=private-home", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--project", str(self.box.project), "run", "trial"]), 0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--project", str(self.box.project), "status"]), 0)
            self.assertEqual(main(["--project", str(self.box.project), "board", "trial"]), 0)
            self.assertEqual(main(["--project", str(self.box.project), "runs"]), 0)
            self.assertEqual(main(["--project", str(self.box.project), "usage"]), 0)
            self.assertEqual(main(["--project", str(self.box.project), "personas"]), 0)
        text = out.getvalue()
        self.assertIn("served claude-opus-5-20260601", text)
        self.assertIn("(skeptic, claude/opus)", text)
        self.assertIn("trial", text)
        self.assertIn("quinn-t-shun@1", text)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["--project", str(self.box.project), "status", "nope"]), 1)
        self.assertIn("no run at", err.getvalue())


if __name__ == "__main__":
    unittest.main()


class GrantTests(unittest.TestCase):
    """Doors are closed by default and open only on purpose, visibly."""

    def setUp(self):
        self.box = Sandbox(self)

    def prepare(self, seats, **fields):
        root, frozen = plan.prepare(self.box.plan(seats=seats, **fields),
                                    project_root=self.box.project, range_spec="HEAD~1..HEAD",
                                    overrides=fields.pop("_overrides", None))
        return root, frozen

    def argv(self, seat, harness):
        return self.box.calls(seat, harness)[0]["argv"]

    def test_closed_by_default(self):
        root, _ = self.prepare([{"id": "c", "persona": "quinn-t-shun"},
                                {"id": "x", "persona": "sec-urity", "harness": "codex",
                                 "model": "gpt-5.5", "effort": "low"}])
        round_.run(root)
        claude, codex = self.argv("c", "claude"), self.argv("x", "codex")
        self.assertIn("--strict-mcp-config", claude)
        self.assertEqual(claude[claude.index("--setting-sources") + 1], "")
        self.assertIn('"disableAllHooks": true', claude[claude.index("--settings") + 1])
        self.assertNotIn("WebSearch", claude[claude.index("--tools") + 1])
        for flag in ("--ignore-user-config", "--ignore-rules", "project_doc_max_bytes=0",
                     'web_search="disabled"'):
            self.assertIn(flag, codex)
        self.assertEqual(read(root / "records/c/r001/receipt.json")["red_flags"],
                         ["isolation is advisory (private-home): the OS did not enforce it"])

    def test_every_grant_changes_both_harnesses_and_is_a_red_flag(self):
        root, frozen = self.prepare(
            [{"id": "c", "persona": "quinn-t-shun"},
             {"id": "x", "persona": "sec-urity", "harness": "codex", "model": "gpt-5.5",
              "effort": "low"}],
            grants=["web", "mcp", "settings", "instructions", "hooks"])
        round_.run(root)
        claude, codex = self.argv("c", "claude"), self.argv("x", "codex")
        self.assertNotIn("--strict-mcp-config", claude)
        self.assertNotIn("--setting-sources", claude)
        self.assertNotIn("disableAllHooks", claude[claude.index("--settings") + 1])
        self.assertIn("WebSearch,WebFetch", claude[claude.index("--tools") + 1])
        for flag in ("--ignore-user-config", "--ignore-rules", "project_doc_max_bytes=0"):
            self.assertNotIn(flag, codex)
        self.assertIn('web_search="live"', codex)
        flags = read(root / "records/c/r001/receipt.json")["red_flags"]
        self.assertIn("granted on purpose: web, mcp, settings, instructions, hooks", flags)
        self.assertIn("[can search the web]", board.text(root, frozen))

    def test_instructions_alone_keeps_the_operator_settings_out(self):
        root, _ = self.prepare([{"id": "c", "persona": "quinn-t-shun", "grants": ["instructions"]}])
        round_.run(root)
        claude = self.argv("c", "claude")
        self.assertEqual(claude[claude.index("--setting-sources") + 1], "project")
        self.assertIn("--strict-mcp-config", claude)

    def test_granted_tools_pass_the_receipt_checks(self):
        root, _ = self.prepare([{"id": "c", "persona": "quinn-t-shun", "grants": ["mcp"]},
                                {"id": "w", "persona": "sec-urity", "grants": ["web"]}],
                               brief={"text": "[[stub:mcp]] Review."})
        (root / "work/w/START.md").write_text("[[stub:web]] Review.\n")
        # The standing assignment is hashed, so edit the frozen digest to match
        # this deliberate test edit rather than defeating the check.
        from convene.storage import digest, write
        _, frozen = runs.load(root)
        for seat in frozen["seats"]:
            if seat["id"] == "w":
                seat["start_sha256"] = digest(root / "work/w/START.md")
        write(root / "plan.json", frozen)
        write(root / "plan-digest.json", {"sha256": digest(root / "plan.json")})
        round_.run(root)
        self.assertEqual(read(root / "records/c/r001/receipt.json")["status"], "answered")
        self.assertEqual(read(root / "records/c/r001/receipt.json")["tools_used"],
                         ["mcp__gmail__send_message"])
        self.assertEqual(read(root / "records/w/r001/receipt.json")["status"], "answered")

    def test_extra_args_and_environment_pass_through(self):
        root, _ = self.prepare([{"id": "c", "persona": "quinn-t-shun",
                                 "args": ["--mcp-config", "/x/mcp.json"],
                                 "env": ["SECRET_FROM_OPERATOR"]},
                                {"id": "x", "persona": "sec-urity", "harness": "codex",
                                 "model": "gpt-5.5", "effort": "low"}],
                               codex_args=["-c", 'mcp_servers.docs.command="docs"'],
                               grants=["mcp"], brief={"text": "[[stub:canary]] Review."})
        round_.run(root)
        claude, codex = self.argv("c", "claude"), self.argv("x", "codex")
        self.assertEqual(claude[claude.index("--mcp-config") + 1], "/x/mcp.json")
        self.assertIn('mcp_servers.docs.command="docs"', codex)
        self.assertEqual(self.box.calls("c", "claude")[0]["env"]["SECRET_FROM_OPERATOR"],
                         "must-not-leak")
        self.assertIsNone(self.box.calls("x", "codex")[0]["env"]["SECRET_FROM_OPERATOR"])
        flags = read(root / "records/c/r001/receipt.json")["red_flags"]
        self.assertIn("extra harness arguments: --mcp-config /x/mcp.json", flags)
        self.assertIn("environment passed through: SECRET_FROM_OPERATOR", flags)
        self.assertIn("SECRET_FROM_OPERATOR", read(root / "records/c/r001/launch.json")["environment"])

    def test_args_cannot_open_a_door_without_its_grant(self):
        for seats in (
            [{"id": "c", "persona": "quinn-t-shun", "args": ["--mcp-config", "/x"]}],
            [{"id": "c", "persona": "quinn-t-shun", "args": ["--tools", "Bash"]}],
            [{"id": "x", "persona": "sec-urity", "harness": "codex", "model": "gpt-5.5",
              "effort": "low", "args": ["-c", 'mcp_servers.d.command="d"']}],
            [{"id": "x", "persona": "sec-urity", "harness": "codex", "model": "gpt-5.5",
              "effort": "low", "args": ['-cweb_search="live"']}],
        ):
            with self.subTest(args=seats[0]["args"]), \
                 self.assertRaisesRegex(ValueError, "in args: (grant|set)"):
                self.prepare(seats)

    def test_unknown_grant_names_the_known_ones(self):
        with self.assertRaisesRegex(ValueError, r"unknown grants \['network'\].*web \("):
            self.prepare([{"id": "c", "persona": "quinn-t-shun", "grants": ["network"]}])

    def test_prepare_overrides_win_and_are_recorded(self):
        root, frozen = self.prepare([{"id": "c", "persona": "quinn-t-shun"}],
                                    _overrides={"grants": ["web"], "tools": "write"})
        self.assertEqual(frozen["seats"][0]["grants"], ["web"])
        self.assertEqual(frozen["seats"][0]["tools"], "write")
        self.assertEqual(frozen["overrides"], {"grants": ["web"], "tools": "write"})

    def test_config_files_supply_defaults_in_order(self):
        user = self.box.root / "config/agent-toolbox/convene.toml"
        user.parent.mkdir(parents=True)
        user.write_text('grants = ["web"]\nmodel = "sonnet"\neffort = "low"\n')
        os.environ["XDG_CONFIG_HOME"] = str(self.box.root / "config")
        self.addCleanup(os.environ.pop, "XDG_CONFIG_HOME", None)
        project = self.box.project / ".convene/config.toml"
        project.parent.mkdir(parents=True)
        project.write_text('model = "haiku"\n')
        root, frozen = self.prepare([{"id": "c", "persona": "quinn-t-shun"},
                                     {"id": "d", "persona": "sec-urity", "model": "opus"}],
                                    model=None, effort=None)
        seats = {s["id"]: s for s in frozen["seats"]}
        self.assertEqual(seats["c"]["model"], "haiku", "project beats user")
        self.assertEqual(seats["d"]["model"], "opus", "seat beats both")
        self.assertEqual(seats["c"]["effort"], "low")
        self.assertEqual(seats["c"]["grants"], ["web"])
        self.assertEqual(frozen["config_sources"], [str(user), str(project)])
        project.write_text('colour = "blue"\n')
        with self.assertRaisesRegex(ValueError, "unknown keys \\['colour'\\]"):
            self.prepare([{"id": "c", "persona": "quinn-t-shun"}])
