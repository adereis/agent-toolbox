"""Isolation tiers, platform breadcrumbs and the doctor for the convene plugin."""

import contextlib
import io
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from convene_support import STUBS, Sandbox

from convene import doctor, harnesses, isolation, platform, plan, round as round_
from convene.harnesses import claude as claude_, codex as codex_
from convene.isolation import bwrap
from convene.storage import read


class TierResolutionTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self, fake_bwrap=True)

    def test_strongest_prefers_enforced_when_bwrap_exists(self):
        with patch.object(bwrap.sys, "platform", "linux"):
            self.assertEqual(isolation.resolve("strongest"), "enforced")

    def test_darwin_falls_back_to_private_home_and_names_it_when_enforced_is_asked(self):
        with patch.object(bwrap.sys, "platform", "darwin"):
            self.assertEqual(isolation.resolve("strongest"), "private-home")
            with self.assertRaisesRegex(ValueError, "Linux-only.*private-home"):
                isolation.resolve("enforced")

    def test_missing_bwrap_names_the_package_and_the_alternative(self):
        with patch.object(bwrap.sys, "platform", "linux"), \
             patch.object(bwrap.shutil, "which", return_value=None):
            self.assertIn("bubblewrap", isolation.get("enforced").available())
            self.assertEqual(isolation.resolve("strongest"), "private-home")

    def test_unknown_request_is_refused(self):
        with self.assertRaisesRegex(ValueError, "isolation must be one of"):
            isolation.resolve("chroot")


class BwrapArgvTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self, fake_bwrap=True)

    def wrap(self, harness_name="claude", repo_ro=True, project=None):
        harness = harnesses.get(harness_name)
        work = self.box.root / "work"
        (work / "materials").mkdir(parents=True, exist_ok=True)
        (work / "START.md").write_text("x")
        with patch.object(bwrap.sys, "platform", "linux"):
            return isolation.get("enforced").wrap(
                ["claude", "-p"], harness=harness, seat_home=self.box.root / "seat-home",
                workspace=work, project_root=project or self.box.project, repo_ro=repo_ro)

    def test_order_blank_then_allow_list_then_workspace_then_chdir(self):
        launched = self.wrap()
        argv = launched.argv
        home = str(self.box.home)
        self.assertEqual(argv[0], "bwrap")
        self.assertIn("--die-with-parent", argv)
        tmpfs = argv.index("--tmpfs")
        self.assertEqual(argv[tmpfs + 1], home)
        private = argv.index(str(self.box.root / "seat-home/claude"))
        self.assertEqual(argv[private - 1], "--bind")
        self.assertEqual(argv[private + 1], f"{home}/.claude")
        self.assertGreater(private, tmpfs, "the private home is bound after the home is blanked")
        launcher = argv.index(str(STUBS))
        self.assertGreater(launcher, private)
        self.assertEqual(argv[launcher - 1], "--ro-bind")
        repo = argv.index(str(self.box.project))
        self.assertEqual(argv[repo - 1], "--ro-bind")
        workspace = argv.index(str(self.box.root / "work"))
        self.assertEqual(argv[workspace - 1], "--bind")
        self.assertGreater(workspace, repo, "the writable bind comes after every read-only one")
        self.assertEqual(argv[workspace + 1], f"{home}/workspace")
        materials = argv.index(f"{home}/workspace/materials")
        self.assertGreater(materials, workspace)
        self.assertEqual(argv[materials - 1 - 1], "--ro-bind")
        chdir = argv.index("--chdir")
        self.assertGreater(chdir, materials)
        self.assertEqual(argv[chdir + 1], f"{home}/workspace")
        self.assertEqual(argv[-2:], ["claude", "-p"])
        self.assertEqual(launched.env["CLAUDE_CONFIG_DIR"], f"{home}/.claude")
        self.assertEqual(launched.env["HOME"], home)
        self.assertEqual(launched.env["CLAUDE_CODE_OAUTH_TOKEN"], "sk-ant-oat-fake-access")
        self.assertNotIn("SECRET_FROM_OPERATOR", launched.env)
        self.assertTrue(launched.attestation["enforced"])
        self.assertEqual(launched.attestation["backend_version"], "bubblewrap 0.11.0")
        self.assertEqual(launched.attestation["repository_read_only"], str(self.box.project))
        self.assertTrue((self.box.root / "seat-home/claude/.claude.json").exists())

    def test_codex_credentials_are_bound_read_only_into_the_private_home(self):
        launched = self.wrap("codex")
        argv = launched.argv
        auth = argv.index(str(self.box.home / ".codex/auth.json"))
        self.assertEqual(argv[auth - 1], "--ro-bind")
        self.assertEqual(argv[auth + 1], f"{self.box.home}/.codex/auth.json")
        self.assertEqual(launched.env["CODEX_HOME"], f"{self.box.home}/.codex")
        self.assertFalse((self.box.root / "seat-home/codex/auth.json").exists(), "never copied")

    def test_finish_removes_only_empty_credential_stubs(self):
        harness = harnesses.get("codex")
        private = self.box.root / "seat-home/codex"
        private.mkdir(parents=True)
        (private / "auth.json").write_text("")
        isolation.get("enforced").finish(harness, self.box.root / "seat-home")
        self.assertFalse((private / "auth.json").exists())
        (private / "auth.json").write_text("{}")
        isolation.get("enforced").finish(harness, self.box.root / "seat-home")
        self.assertTrue((private / "auth.json").exists(), "a written file is kept visible")

    def test_project_outside_the_home_is_blanked_unless_repo_ro(self):
        outside = self.box.root / "elsewhere"
        outside.mkdir()
        launched = self.wrap(repo_ro=False, project=outside)
        self.assertIn(str(outside), launched.attestation["blanked"])
        self.assertIsNone(launched.attestation["repository_read_only"])
        launched = self.wrap(repo_ro=True, project=outside)
        self.assertNotIn(str(outside), launched.attestation["blanked"])

    def test_network_mounts_are_left_out_of_the_root(self):
        table = self.box.root / "mounts"
        table.write_text("rootfs / ext4 rw 0 0\n/etc/auto.nas /nas autofs rw 0 0\n"
                         "//srv/home /nas/me cifs rw 0 0\nsrv:/x /mnt/share\\040two nfs4 rw 0 0\n"
                         "tmpfs /tmp tmpfs rw 0 0\n")
        excluded = bwrap.excluded_mounts(table)
        self.assertEqual(excluded, [Path("/nas"), Path("/mnt/share two"), Path("/nas/me")])
        fake = self.box.root / "fakeroot"
        for name in ("usr", "etc", "mnt/share two", "mnt/other", "nas/me", "home"):
            (fake / name).mkdir(parents=True)
        (fake / "bin").symlink_to("usr/bin")
        (fake / "vmlinuz").write_text("")
        binds = bwrap.root_binds([fake / "nas", fake / "mnt/share two"], fake)
        self.assertNotIn(str(fake / "nas"), [b[1] for b in binds])
        self.assertIn(("--bind", str(fake / "mnt/other"), str(fake / "mnt/other")), binds)
        self.assertNotIn(("--bind", str(fake / "mnt"), str(fake / "mnt")), binds)
        self.assertIn(("--bind", str(fake / "usr"), str(fake / "usr")), binds)
        self.assertIn(("--symlink", "usr/bin", str(fake / "bin")), binds)
        self.assertIn(("--ro-bind", str(fake / "vmlinuz"), str(fake / "vmlinuz")), binds)
        self.assertEqual(bwrap.root_binds([], fake), [("--bind", str(fake), str(fake))])

    def test_launcher_paths_follow_intermediate_links(self):
        real = self.box.root / "opt/app-1.0/bin"
        real.mkdir(parents=True)
        (real / "tool").write_text("")
        current = self.box.root / "opt/current"
        current.symlink_to(self.box.root / "opt/app-1.0")
        (self.box.root / "bin").mkdir()
        (self.box.root / "bin/tool").symlink_to(current / "bin/tool")
        found = bwrap.launcher_paths(self.box.root / "bin/tool")
        # Unresolved on purpose: bwrap binds by the spelled path, so binding
        # opt/current/bin keeps the `current` link somewhere to point.
        self.assertEqual(found, [self.box.root / "bin", self.box.root / "opt/current/bin"])


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("/usr/bin/bwrap"),
                     "needs the real bubblewrap")
class RealJailTests(unittest.TestCase):
    """The stub claude inside a real jail: what it can and cannot reach."""

    def setUp(self):
        self.box = Sandbox(self)

    def test_project_is_readable_only_when_repo_ro(self):
        for workspace, expect in (("repo-ro", "READ=ok"), ("none", "READ=fail")):
            with self.subTest(workspace=workspace):
                root, _ = plan.prepare(self.box.plan(seats=[{"id": "s", "persona": "quinn-t-shun",
                                                            "isolation": "enforced",
                                                            "workspace": workspace}],
                                                     brief={"text": "[[stub:canary]] Review the repository is at "
                                                            + str(self.box.project) + ", read-only."}),
                                       project_root=self.box.project, range_spec="HEAD~1..HEAD")
                played, why = round_.run(root)
                got = read(root / "records/s/r001/receipt.json")
                self.assertEqual(got["status"], "answered", (played, got.get("error"),
                                 (root / "records/s/r001/stderr.log").read_text()))
                answer = (root / "records/s/r001/answer.md").read_text()
                self.assertIn(expect, answer)
                self.assertIn(f"CWD={self.box.home}/workspace", answer)
                self.assertIn("SECRET=no", answer)
                self.assertTrue(got["isolation"]["enforced"])
                self.assertEqual(got["isolation"]["tier"], "enforced")
                self.assertTrue(list((root / "homes/s/claude/projects").rglob("*.jsonl")),
                                "the seat's session landed in its private home")


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("/usr/bin/bwrap"),
                     "needs the real bubblewrap")
class RealJailWorktreeTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self)

    def test_worktree_seat_can_use_git_inside_the_jail(self):
        root, _ = plan.prepare(self.box.plan(kind="room", workspace="none", seats=[
            {"id": "d", "persona": "connie-tinuity", "isolation": "enforced", "tools": "write",
             "workspace": "worktree"}],
            brief={"text": "[[stub:canary]] Build."}), project_root=self.box.project)
        played, why = round_.run(root)
        got = read(root / "records/d/r001/receipt.json")
        self.assertEqual(got["status"], "answered", (played, got.get("error"),
                         (root / "records/d/r001/stderr.log").read_text()))
        answer = (root / "records/d/r001/answer.md").read_text()
        self.assertIn("GIT=ok", answer, answer)
        self.assertIn("READ=fail", answer, "the operator's checkout stays out of reach")
        patch = (root / "board/made/d/r001/changes.patch").read_text()
        self.assertIn("STUB-NOTE.md", patch)
        self.assertEqual(got["isolation"]["worktree_git"][0], str(self.box.project / ".git"))
        round_.prune(root)
        self.assertNotIn("work/d/repo", self.box.git("worktree", "list"))


class PlatformTests(unittest.TestCase):
    def test_darwin_process_identity_uses_ps(self):
        done = subprocess.CompletedProcess([], 0, stdout="Mon Sep 21 10:00:00 2026\n", stderr="")
        with patch.object(platform.sys, "platform", "darwin"), \
             patch.object(platform.subprocess, "run", return_value=done) as run:
            self.assertEqual(platform.process_identity(4242), "Mon Sep 21 10:00:00 2026")
            self.assertEqual(run.call_args[0][0], ["ps", "-o", "lstart=", "-p", "4242"])
        gone = subprocess.CompletedProcess([], 1, stdout="", stderr="")
        with patch.object(platform.sys, "platform", "darwin"), \
             patch.object(platform.subprocess, "run", return_value=gone):
            self.assertIsNone(platform.process_identity(4242))

    def test_other_platforms_fail_loudly(self):
        with patch.object(platform.sys, "platform", "win32"), \
             self.assertRaisesRegex(RuntimeError, "Linux and macOS"):
            platform.process_identity(1)

    def test_state_home_follows_xdg(self):
        env = {"HOME": "/h", "XDG_STATE_HOME": "/s"}
        self.assertEqual(platform.state_home(env), Path("/s/agent-toolbox/convene"))
        self.assertEqual(platform.state_home({"HOME": "/h"}), Path("/h/.local/state/agent-toolbox/convene"))

    def test_macos_keychain_hint_when_credentials_file_is_absent(self):
        box = Sandbox(self, claude_credentials=False)
        with patch.object(claude_.sys, "platform", "darwin"), \
             self.assertRaisesRegex(RuntimeError, "security find-generic-password"):
            harnesses.get("claude").credential_env(box.home / ".claude")
        import os
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "from-operator"
        self.assertEqual(harnesses.get("claude").credential_env(box.home / ".claude"),
                         {"CLAUDE_CODE_OAUTH_TOKEN": "from-operator"})


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self)
        real = shutil.which
        def which(name, *args, **kwargs):
            return None if name == "bwrap" else real(name, *args, **kwargs)
        patcher = patch.object(doctor.shutil, "which", side_effect=which)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_probes_run_against_the_stubs_and_report(self):
        data = doctor.report(project_root=self.box.project)
        for name in ("claude", "codex"):
            self.assertTrue(data["harnesses"][name]["installed"])
            self.assertEqual(data["harnesses"][name]["credentials"], "present")
            self.assertTrue(all(p["ok"] for p in data["harnesses"][name]["probes"]),
                            data["harnesses"][name]["probes"])
        text, bad = doctor.render(data)
        self.assertFalse(bad)
        self.assertIn("✓ claude 2.1.278", text)

    def test_dead_flag_is_reported_with_its_reason(self):
        probe = doctor.Probe("--bogus", ("--help",), needles=("never-printed",), why="reason here")
        ok, detail = doctor.run_probe("claude", probe)
        self.assertFalse(ok)
        self.assertIn("accepted a deliberately invalid value", detail)

    def test_missing_codex_login_is_named(self):
        (self.box.home / ".codex/auth.json").unlink()
        data = doctor.report(probes=False)
        self.assertIn("auth.json", data["harnesses"]["codex"]["credentials"])


if __name__ == "__main__":
    unittest.main()
