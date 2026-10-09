"""End-to-end runs of the convene engine against stub harnesses."""

import json
import os
import sys
import unittest
from pathlib import Path

from convene_support import Sandbox, environment_of

from convene import board, export, harnesses, plan, round as round_, runs
from convene.cli import main
from convene.harnesses import codex as codex_harness
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
        self.assertEqual(call["env"]["HOME"], str(environment_of(root) / "homes/skeptic"))
        self.assertEqual(call["env"]["CLAUDE_CONFIG_DIR"], str(environment_of(root) / "homes/skeptic/claude"))
        self.assertEqual(call["env"]["CLAUDE_CODE_OAUTH_TOKEN"], "sk-ant-oat-fake-access")
        self.assertIsNone(call["env"]["SECRET_FROM_OPERATOR"], "the environment is an allow-list")
        self.assertEqual(call["cwd"], str(environment_of(root) / "work/skeptic"))
        answer = (root / "records/skeptic/r001/answer.md").read_text()
        self.assertIn("READ=ok", answer, "repo-ro is advisory here: the tree is readable")
        self.assertIn("TOKEN=yes SECRET=no", answer)
        launch = read(root / "records/skeptic/r001/launch.json")
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", launch["environment"])
        self.assertNotIn("sk-ant", json.dumps(launch), "values never enter the record")
        self.assertTrue((environment_of(root) / "homes/skeptic/claude/.claude.json").exists())
        self.assertFalse((environment_of(root) / "homes/skeptic/claude/.credentials.json").exists(),
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
        self.assertFalse((environment_of(root) / "homes/m/codex/auth.json").exists())
        self.assertTrue(list((environment_of(root) / "homes/m/codex/sessions").rglob("*.jsonl")))
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

    def test_every_claude_alias_passes_its_served_model_receipt(self):
        """`fable` once failed here: only opus, sonnet and haiku were families."""
        root, _ = self.prepare(seats=[{"id": "skeptic", "persona": "quinn-t-shun",
                                       "model": "fable"}])
        played, why = round_.run(root)
        got = self.receipt(root, "skeptic")
        self.assertEqual(got["status"], "answered", got.get("error"))
        self.assertEqual(got["requested_model"], "fable")
        self.assertTrue(got["model"].startswith("claude-fable-"))

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
        text = round_.render_status(data)
        self.assertIn("HELD: round 1 waiting on maintainer, skeptic", text)
        self.assertIn(f"next: convene continue {root.name} maintainer (and 1 more)", text)
        self.assertIn(f"then convene promote {root.name} 1", text)

    def test_quota_interrupted_keeps_the_session_for_a_continuation(self):
        root, _ = self.prepare(brief={"text": "[[stub:quota-interrupted]] Review."})
        round_.run(root)
        for seat in ("skeptic", "maintainer"):
            self.assertEqual(self.receipt(root, seat)["quota_stop"], "interrupted")
            self.assertIsNotNone(read(root / "records" / seat / "state.json")["session_id"])

    def test_a_turn_cut_by_a_quota_still_pins_its_session(self):
        """The cut turn's reasoning is already in the session, on one Opus.

        A pin recorded only from answered turns left the continuation to
        resume on `opus`, which by then may mean a newer model.
        """
        root, _ = self.prepare(seats=[{"id": "skeptic", "persona": "quinn-t-shun"}],
                               brief={"text": "[[stub:quota-interrupted]] Review."})
        round_.run(root)
        self.assertEqual(self.receipt(root, "skeptic")["quota_stop"], "interrupted")
        state = read(root / "records" / "skeptic" / "state.json")
        self.assertEqual(state["model_served"], "claude-opus-5-20260601")
        # A newer Opus ships while the seat waits out its quota window.
        next(environment_of(root).glob("homes/skeptic/**/stub-calls.jsonl")).with_name("stub-new-opus").touch()
        self.assertEqual(round_.continue_seat(root, 1, "skeptic"), "answered")
        got = self.receipt(root, "skeptic")
        self.assertEqual(got["model"], "claude-opus-5-20260601")
        self.assertEqual(got["model_pinned"], "claude-opus-5-20260601")

    def test_launch_refuses_a_fork_it_cannot_pin(self):
        root, frozen = self.prepare(seats=[{"id": "skeptic", "persona": "quinn-t-shun"}])
        with self.assertRaisesRegex(ValueError, "must pin to its parent"):
            round_.launch(root, frozen, frozen["seats"][0], 1, "x", "fork", "s-1")

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
        (environment_of(root) / "work/skeptic/materials/diff.patch").write_text("edited\n")
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
                     'web_search="disabled"', "features.apps=false", "features.plugins=false",
                     "features.remote_plugin=false"):
            self.assertIn(flag, codex)
        self.assertEqual(read(root / "records/c/r001/receipt.json")["red_flags"],
                         ["isolation is advisory (private-home): the OS did not enforce it"])

    def test_every_codex_seat_closes_what_codex_leaves_open(self):
        """Sub-agents and image generation on every seat, apps and plugins unless granted.

        Codex's catalog puts most models on multi-agent v2, which ignores
        features.multi_agent=false and offers every seat a tool that spawns a
        sub-agent on another model. The account's connected apps come with
        the login, and so do its plugins, which install into every private
        home. A builder that forgets any of them hands a seat all of them.
        """
        codex = harnesses.get("codex")
        always = ["features.multi_agent_v2.max_concurrent_threads_per_session=1",
                  "features.image_generation=false"]
        for tools in harnesses.TOOL_SETS:
            for mode, session in (("start", None), ("resume", "s-1")):
                for grants in ([], ["mcp"]):
                    seat = {"id": "x", "model": "gpt-5.5", "effort": "low", "tools": tools,
                            "grants": grants, "args": []}
                    with self.subTest(tools=tools, mode=mode, grants=grants):
                        argv, _ = codex.command(seat, mode, session, "p", self.box.root)
                        for setting in always:
                            self.assertEqual(argv[argv.index(setting) - 1], "-c")
                        for closed in ("features.apps=false", "features.plugins=false",
                                       "features.remote_plugin=false"):
                            self.assertEqual(closed in argv, not grants,
                                             "the mcp grant keeps the apps and plugins, "
                                             "as Claude's keeps its servers")

    def test_a_tool_free_codex_seat_names_its_tools_off_and_answers(self):
        """Codex ignores `tools.view_image` since 0.156 and says so in an error
        item, which the receipt reads as a failed turn; the viewer stayed on."""
        root, _ = plan.prepare(self.box.plan(kind="room", workspace="none", seats=[
            {"id": "x", "persona": "sec-urity", "harness": "codex", "model": "gpt-5.5",
             "effort": "low", "tools": "none"}]), project_root=self.box.project)
        round_.run_round(root, 1)
        got = read(root / "records/x/r001/receipt.json")
        self.assertEqual(got["status"], "answered", got.get("error"))
        argv = self.argv("x", "codex")
        for feature in ("shell_tool", "unified_exec", "view_image", "browser_use",
                        "browser_use_external", "in_app_browser", "computer_use"):
            self.assertIn(f"features.{feature}=false", argv)
        self.assertFalse([a for a in argv if a.startswith("tools.")])

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
        for flag in ("--ignore-user-config", "--ignore-rules", "project_doc_max_bytes=0",
                     "features.apps=false"):
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
        (environment_of(root) / "work/w/START.md").write_text("[[stub:web]] Review.\n")
        # The standing assignment is hashed, so edit the frozen digest to match
        # this deliberate test edit rather than defeating the check.
        from convene.storage import digest, write
        _, frozen = runs.load(root)
        for seat in frozen["seats"]:
            if seat["id"] == "w":
                seat["start_sha256"] = digest(environment_of(root) / "work/w/START.md")
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

    def test_args_cannot_reopen_what_every_codex_seat_closes(self):
        """A seat's args come last and the last value of a key wins."""
        for args in (["-c", "features.apps=true"], ["--enable", "apps"],
                     ["--enable", "plugins"], ["-c", "features.remote_plugin=true"],
                     ["--enable=image_generation"], ["--config", "features.view_image=true"],
                     ["-c", "features.multi_agent_v2.max_concurrent_threads_per_session=8"],
                     ["-cfeatures.multi_agent=true"], ["-c", "features={apps=true}"]):
            seats = [{"id": "x", "persona": "sec-urity", "harness": "codex", "model": "gpt-5.5",
                      "effort": "low", "args": args}]
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "in args: "):
                self.prepare(seats)
        seats[0].update(args=["--enable", "apps"], grants=["mcp"])
        self.assertEqual(self.prepare(seats)[1]["seats"][0]["args"], ["--enable", "apps"])

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


class CodexInventoryTests(unittest.TestCase):
    """A Codex seat's MCP servers, by Codex's own count, before its turn.

    Codex has no start-up event naming what it loaded, and the account's
    apps reach a seat through generic tools, so neither the stream nor the
    model can say what a seat holds. Its app server can, under the seat's
    own settings, before a model is called.
    """

    def setUp(self):
        self.box = Sandbox(self)

    def run_seat(self, **seat):
        root, _ = plan.prepare(self.box.plan(kind="room", workspace="none", seats=[
            {"id": "x", "persona": "sec-urity", "harness": "codex", "model": "gpt-5.5",
             "effort": "low", **seat}]), project_root=self.box.project)
        return root, round_.run_round(root, 1)

    def passthrough(self, name, value):
        os.environ[name] = value
        self.addCleanup(os.environ.pop, name, None)
        return [name]

    def asked(self):
        return [json.loads(line) for path in self.box.root.rglob("stub-app-server.jsonl")
                for line in path.read_text().splitlines()]

    def test_a_closed_seat_holds_no_server_and_its_receipt_says_so(self):
        root, _ = self.run_seat()
        got = read(root / "records/x/r001/receipt.json")
        self.assertEqual(got["status"], "answered", got.get("error"))
        self.assertEqual(got["mcp_servers"], {})
        (asked,) = self.asked()
        self.assertEqual(asked["argv"][0], "app-server")
        self.assertIn("features.apps=false", asked["argv"])
        for flag in ("exec", "-m", "--ignore-user-config", "--json"):
            self.assertNotIn(flag, asked["argv"], "only settings travel")

    def test_a_granted_seat_records_what_it_holds_as_a_red_flag(self):
        root, _ = self.run_seat(grants=["mcp"], args=["-c", 'mcp_servers.docs.command="docs"'])
        got = read(root / "records/x/r001/receipt.json")
        self.assertEqual(got["status"], "answered", got.get("error"))
        self.assertEqual(got["mcp_servers"], {"codex_apps": 2, "docs": 0},
                         "one server per page: the reader follows the cursor")
        self.assertIn("MCP servers held: codex_apps (2 tools), docs (0 tools)", got["red_flags"])

    def test_a_seat_holding_a_server_is_refused_before_its_turn(self):
        """A release that ignored features.apps would hand the seat the account's apps."""
        root, results = self.run_seat(env=self.passthrough("CONVENE_STUB_APPS", "1"))
        self.assertRegex(results["x"], r"^stopped: .*without the mcp grant: codex_apps \(2 tools\)")
        self.assertIn("no model was called", results["x"])
        self.assertEqual(self.box.calls("x", "codex"), [], "the turn never started")
        self.assertFalse((root / "records/x/r001/events.jsonl").exists())
        self.assertFalse(list((environment_of(root) / "homes/x").rglob("auth.json")), "the login is unstaged")

    def test_an_inventory_that_cannot_be_read_refuses_the_seat(self):
        _, results = self.run_seat(env=self.passthrough("CONVENE_STUB_APP_SERVER", "broken"))
        self.assertRegex(results["x"], r"^stopped: Codex's MCP inventory could not be read "
                                       r"\(codex app-server did not initialize")
        self.assertEqual(self.box.calls("x", "codex"), [])

    def test_the_none_tier_reads_the_operators_home_without_its_config(self):
        """The seat ignores the operator's config.toml; the app server cannot."""
        (self.box.home / ".codex/config.toml").write_text(
            '[mcp_servers.fictional]\ncommand = "true"\n')
        root, _ = self.run_seat(isolation="none")
        got = read(root / "records/x/r001/receipt.json")
        self.assertEqual(got["status"], "answered", got.get("error"))
        self.assertEqual(got["mcp_servers"], {})
        self.assertTrue((self.box.home / ".codex/config.toml").exists(), "left where it was")
        # With `settings` the seat reads that config, so the server is its own.
        _, results = self.run_seat(isolation="none", grants=["settings"])
        self.assertIn("without the mcp grant: fictional (0 tools)", results["x"])

    def test_only_settings_travel_to_the_app_server(self):
        argv = ["codex", "exec", "--ignore-user-config", "-m", "m", "-c", "a=b", "-s",
                "read-only", "--enable", "x", "-cfoo=1", "--config=k=v", "--json", "-"]
        self.assertEqual(codex_harness.settings(argv),
                         ["-c", "a=b", "--enable", "x", "-cfoo=1", "--config=k=v"])

    def test_the_inventory_reader_names_what_it_could_not_read(self):
        env = {"PATH": os.environ["PATH"]}
        silent = [sys.executable, "-c", "import time; time.sleep(30)"]
        servers, why = codex_harness.mcp_inventory(silent, env=env, cwd=self.box.root, timeout=1)
        self.assertIsNone(servers)
        self.assertIn("within 1s", why)
        refusing = [sys.executable, "-c", (
            "import json, sys\n"
            "for line in sys.stdin:\n"
            "    m = json.loads(line)\n"
            "    if 'id' not in m: continue\n"
            "    r = {'result': {}} if m['method'] == 'initialize' else "
            "{'error': {'code': -32601, 'message': 'unknown method'}}\n"
            "    print(json.dumps({'id': m['id'], **r}), flush=True)\n")]
        servers, why = codex_harness.mcp_inventory(refusing, env=env, cwd=self.box.root)
        self.assertIsNone(servers)
        self.assertIn("listed no MCP inventory", why)
        self.assertIn("unknown method", why)
