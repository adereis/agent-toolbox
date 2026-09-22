"""Isolation tiers, platform breadcrumbs and the doctor for the convene plugin."""

import contextlib
import io
import os
import re
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
        joined = " ".join(argv)
        for flag in ("--unshare-pid", "--unshare-ipc", "--unshare-uts", "--unshare-cgroup-try"):
            self.assertIn(flag, argv)
        self.assertIn("--ro-bind /usr /usr", joined)
        self.assertIn("--ro-bind /etc /etc", joined)
        self.assertNotIn("--bind / /", joined, "the root is an allow-list, never bound whole")
        self.assertIn("--dev /dev", joined)
        self.assertNotIn("--dev-bind", argv, "the host's devices stay out")
        self.assertNotIn("/run/user", joined, "the runtime directory and its bus stay out")
        self.assertNotIn("--sync-fd", argv, "a claude seat proxies no bus")
        self.assertEqual(launched.pass_fds, ())
        self.assertIsNone(launched.attestation["session_bus"])
        self.assertEqual(launched.attestation["namespaces"], ["pid", "ipc", "uts", "cgroup"])
        self.assertIn("/usr", launched.attestation["root_read_only"])
        tmpfs = argv.index("--tmpfs")
        self.assertEqual(argv[tmpfs - 2:tmpfs], ["--size", str(bwrap.TMPFS_BYTES)])
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

    def test_project_inside_a_bound_tree_is_blanked_unless_repo_ro(self):
        """A project under `/opt` would stay readable through the `/opt` bind."""
        outside = self.box.root / "elsewhere"
        outside.mkdir()
        launched = self.wrap(repo_ro=False, project=outside)
        self.assertNotIn(str(outside), launched.attestation["blanked"],
                         "outside every bound tree there is nothing to cover")
        self.assertNotIn(str(outside), " ".join(launched.argv))
        with patch.object(bwrap, "OPTIONAL_TREES", (str(outside.parent),)):
            launched = self.wrap(repo_ro=False, project=outside)
            self.assertIn(str(outside), launched.attestation["blanked"])
            self.assertIsNone(launched.attestation["repository_read_only"])
            launched = self.wrap(repo_ro=True, project=outside)
            self.assertNotIn(str(outside), launched.attestation["blanked"])
            self.assertEqual(launched.attestation["repository_read_only"], str(outside))

    def test_system_root_is_an_allow_list_of_host_trees(self):
        fake = self.box.root / "fakeroot"
        for name in ("usr/bin", "etc", "opt", "var/lib", "var/mnt", "home/me", "nas",
                     "run/systemd/resolve", "lib32"):
            (fake / name).mkdir(parents=True)
        (fake / "bin").symlink_to("usr/bin")
        (fake / "run/systemd/resolve/stub-resolv.conf").write_text("nameserver 127.0.0.53\n")
        (fake / "etc/resolv.conf").symlink_to("../run/systemd/resolve/stub-resolv.conf")
        triples = bwrap.system_root(fake)
        bound = [t[1] for t in triples if t[0] == "--ro-bind"]
        self.assertEqual(bound[:2], [str(fake / "usr"), str(fake / "etc")])
        self.assertIn(str(fake / "opt"), bound)
        self.assertIn(str(fake / "var/lib"), bound)
        self.assertIn(str(fake / "lib32"), bound, "a real directory alias is bound")
        self.assertIn(("--symlink", "usr/bin", str(fake / "bin")), triples)
        self.assertIn(str(fake / "run/systemd/resolve/stub-resolv.conf"), bound,
                      "the resolver's real file comes along or nothing resolves")
        for absent in ("home", "nas", "var/mnt", "var", "run"):
            self.assertNotIn(str(fake / absent), bound)
        self.assertTrue(all(t[1] == t[2] for t in triples if t[0] == "--ro-bind"),
                        "every tree is bound at its own path")
        self.assertTrue(bwrap.visible(fake / "opt/src/thing", bwrap.bound_trees(triples)))
        self.assertFalse(bwrap.visible(fake / "home/me/thing", bwrap.bound_trees(triples)))

    def test_system_root_names_a_missing_required_tree(self):
        fake = self.box.root / "bare"
        (fake / "etc").mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, "usr is missing"):
            bwrap.system_root(fake)

    def test_resolver_inside_etc_needs_no_extra_bind(self):
        fake = self.box.root / "etcroot"
        (fake / "etc").mkdir(parents=True)
        (fake / "etc/resolv.real").write_text("")
        (fake / "etc/resolv.conf").symlink_to("resolv.real")
        self.assertEqual(bwrap.resolver_paths(fake / "etc/resolv.conf", fake), [])
        (fake / "etc/dangling").symlink_to("../run/gone")
        self.assertEqual(bwrap.resolver_paths(fake / "etc/dangling", fake), [])
        (fake / "home/me").mkdir(parents=True)
        (fake / "home/me/resolv.conf").write_text("")
        (fake / "etc/stray").symlink_to("../home/me/resolv.conf")
        with self.assertRaisesRegex(RuntimeError, "outside /etc and /run"):
            bwrap.resolver_paths(fake / "etc/stray", fake)

    def test_offline_jail_shares_the_seats_root(self):
        argv = bwrap.offline_jail(self.box.home)
        joined = " ".join(argv)
        self.assertIn("--unshare-net", argv)
        self.assertIn("--ro-bind /usr /usr", joined)
        self.assertIn(f"--bind {self.box.home} {self.box.home}", joined)
        self.assertNotIn("--bind / /", joined)

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
                self.assertIn("RUNTIME=no", answer, "no /run/user, so no session bus to escape by")
                entries = set(re.search(r"ROOT=(\S+)", answer).group(1).split(","))
                self.assertLessEqual(entries, {"bin", "dev", "etc", "home", "lib", "lib32",
                                               "lib64", "libx32", "nix", "opt", "proc", "run",
                                               "sbin", "snap", "sys", "tmp", "usr", "var"},
                                     entries)
                pids = int(re.search(r"PIDS=(\d+)", answer).group(1))
                self.assertLess(pids, 16, "a private pid namespace shows the seat only")
                self.assertTrue(got["isolation"]["enforced"])
                self.assertEqual(got["isolation"]["tier"], "enforced")
                self.assertIn("/usr", got["isolation"]["root_read_only"])
                self.assertIsNone(got["isolation"]["session_bus"])
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


# Captured before any Sandbox replaces them: the one test that dials the
# operator's real bus needs the real address back.
HOST_BUS = {k: os.environ[k] for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
            if k in os.environ}


def host_bus_answers(name):
    """Whether the operator's session bus has `name` and dbus-send can reach it."""
    if not (shutil.which("dbus-send") and os.environ.get("DBUS_SESSION_BUS_ADDRESS")):
        return False
    done = subprocess.run(["dbus-send", "--session", "--print-reply", f"--dest={name}",
                           "/", "org.freedesktop.DBus.Peer.Ping"], capture_output=True, timeout=30)
    return done.returncode == 0


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("/usr/bin/bwrap")
                     and shutil.which("xdg-dbus-proxy") and host_bus_answers("org.freedesktop.secrets"),
                     "needs the real bubblewrap, xdg-dbus-proxy and a session bus with a keyring")
class RealBusProxyTests(unittest.TestCase):
    """The proxied bus lets exactly the granted name through."""

    def test_secrets_reachable_and_systemd_refused_inside_the_jail(self):
        box = Sandbox(self)
        (box.home / ".gemini").mkdir()
        (box.home / ".gemini/oauth_creds.json").write_text("{}")
        # The host bus, not the sandbox's dead address: this test dials it.
        with patch.dict(os.environ, HOST_BUS):
            work = box.root / "work"
            work.mkdir()
            harness = harnesses.get("agy")
            tier = isolation.get("enforced")
            ping = ("dbus-send --session --print-reply --dest={} / org.freedesktop.DBus.Peer.Ping "
                    ">/dev/null 2>&1; echo {}=$?")
            script = "; ".join([ping.format("org.freedesktop.secrets", "SECRETS"),
                                ping.format("org.freedesktop.systemd1", "SYSTEMD"),
                                "ls /run/user/*/ | tr '\\n' ' '"])
            launched = tier.wrap(["/bin/sh", "-c", script], harness=harness,
                                 seat_home=box.root / "seat", workspace=work,
                                 project_root=box.project, repo_ro=False)
            try:
                proc = subprocess.Popen(launched.argv, env=launched.env, cwd=launched.cwd,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        pass_fds=launched.pass_fds, start_new_session=True)
            finally:
                launched.release()
            out, err = proc.communicate(timeout=60)
            tier.finish(harness, box.root / "seat")
        text = out.decode()
        self.assertIn("SECRETS=0", text, (text, err.decode()))
        self.assertIn("SYSTEMD=1", text, "the filter refuses every name but the granted one")
        self.assertEqual(text.strip().splitlines()[-1].strip(), "bus",
                         "the runtime directory holds the proxied socket and nothing else")
        self.assertEqual(launched.attestation["session_bus"]["names"], ["org.freedesktop.secrets"])
        self.assertIsNone(tier._buses.get(str(box.root / "seat")), "finish reaped the proxy")


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
