"""Synthetic telemetry and real, isolated tmux tests. No account requests."""

from datetime import datetime, timezone
from decimal import Decimal
import contextlib
import errno
import importlib.util
import io
import json
import os
import pty
import re
from pathlib import Path
import shutil
import select
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "harnesses/codex/scripts/codex-tmux.py"
sys.path.insert(0, str(REPO / "harnesses/codex"))
import _statusline as status

spec = importlib.util.spec_from_file_location("codex_tmux", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
SID = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
NOW = 1789473600
PRICE = {"demo-model": {"input": 10, "cached_input": 1, "cache_write": 12.5,
                        "output": 50, "long_context_after": 272000}}


def event(kind, payload, when=NOW):
    return {"timestamp": datetime.fromtimestamp(when, timezone.utc).isoformat(), "type": kind, "payload": payload}


def context(model="demo-model", when=NOW):
    return event("turn_context", {"model": model, "effort": "high", "cwd": "/fictional/project"}, when)


def usage(response="response-demo", thread=SID, **counts):
    return event("token_usage_record", {"thread_id": thread, "response_id": response,
                 "usage": {"input_tokens": 1000, "output_tokens": 100, **counts}})


class TemporaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home() / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def reader(self, backend="api", started=NOW):
        return status.Rollout(self.root / "rollout-demo.jsonl", SID, started, backend, "default", PRICE)


class PricingTests(TemporaryTest):
    def test_cache_read_write_and_reasoning_are_not_double_counted(self):
        counts = {"input_tokens": 1000, "cached_input_tokens": 400, "cache_write_input_tokens": 300,
                  "output_tokens": 100, "reasoning_output_tokens": 80}
        self.assertEqual(status.estimate(counts, "demo-model", "default", PRICE), Decimal("0.01215"))
        self.assertEqual(status.estimate(counts, "demo-model", "priority", PRICE), Decimal("0.02430"))
        self.assertEqual(status.estimate(counts, "demo-model", "flex", PRICE), Decimal("0.006075"))

    def test_long_context_boundary_and_unknown_rates(self):
        counts = {"input_tokens": 272000, "output_tokens": 100}
        self.assertEqual(status.estimate(counts, "demo-model", "default", PRICE), Decimal("2.725"))
        counts["input_tokens"] += 1
        self.assertEqual(status.estimate(counts, "demo-model", "default", PRICE), Decimal("5.44752"))
        for model, tier in (("unknown", "default"), ("demo-model", "unknown")):
            with self.assertRaises(ValueError):
                status.estimate(counts, model, tier, PRICE)

    def test_inconsistent_usage_is_not_shown_as_zero(self):
        for bad in ({"cached_input_tokens": 1001}, {"output_tokens": -1}, {"output_tokens": True}):
            with self.assertRaises(ValueError):
                status.estimate({"input_tokens": 1000, **bad}, "demo-model", "default", PRICE)

    def test_bundled_rates_validate(self):
        self.assertIn("gpt-6-astra", status.load_prices())


class RolloutTests(TemporaryTest):
    def test_resume_ignores_old_backend_quota_and_spend(self):
        reader = self.reader()
        reader.consume(context("old-model", NOW - 10))
        reader.consume(event("event_msg", {"type": "token_count", "rate_limits": {"plan_type": "pro"}}, NOW - 10))
        old = usage(); old["timestamp"] = context(when=NOW - 10)["timestamp"]
        reader.consume(old)
        self.assertEqual(reader.backend, "api")
        self.assertIsNone(reader.limits)
        self.assertEqual(reader.cost, 0)
        reader.consume(context())
        reader.consume(usage())
        self.assertEqual(reader.cost, Decimal("0.015"))

    def test_repeated_usage_and_agent_records_do_not_inflate_cost(self):
        reader = self.reader()
        reader.consume(context())
        reader.consume(usage())
        reader.consume(usage())
        reader.consume(usage("child-response", OTHER))
        reader.consume(event("event_msg", {"type": "token_count", "info": {
            "model_context_window": 10000, "last_token_usage": {"total_tokens": 7000},
            "total_token_usage": {"total_tokens": 999999}}}))
        self.assertEqual(reader.cost, Decimal("0.015"))
        self.assertEqual(reader.context, 70)

    def test_tier_and_model_changes_price_each_response(self):
        reader = self.reader()
        reader.consume(context())
        reader.consume(usage())
        reader.consume(event("event_msg", {"type": "thread_settings_applied", "thread_id": SID,
            "thread_settings": {"model": "demo-model", "model_provider_id": "openai_api", "service_tier": "fast"}}))
        reader.consume(usage("response-fast"))
        self.assertEqual(reader.cost, Decimal("0.045"))
        reader.consume(context("unknown-model"))
        reader.consume(usage("unknown"))
        self.assertIsNone(reader.snapshot()["cost"])
        self.assertIn("unknown-model", reader.snapshot()["cost_error"])

    def test_copied_settings_and_api_quota_are_ignored(self):
        reader = self.reader()
        reader.consume(event("event_msg", {"type": "thread_settings_applied", "thread_id": OTHER,
            "thread_settings": {"model_provider_id": "openai"}}))
        reader.consume(event("event_msg", {"type": "token_count", "rate_limits": {"plan_type": "pro"}}))
        self.assertEqual(reader.backend, "api")
        self.assertIsNone(reader.limits)

    def test_unexpected_provider_does_not_claim_subscription_authentication(self):
        reader = self.reader()
        reader.consume(event("event_msg", {"type": "thread_settings_applied", "thread_id": SID,
            "thread_settings": {"model_provider_id": "openai", "model": "demo-model"}}))
        self.assertEqual(reader.backend, "openai")
        self.assertIsNone(reader.limits)

    def test_partial_append_retries_and_never_replays_cost(self):
        reader = self.reader()
        prefix = json.dumps(context()) + "\n"
        response = json.dumps(usage()) + "\n"
        reader.path.write_text(prefix + response[:30])
        reader.poll()
        self.assertEqual(reader.offset, len(prefix))
        with reader.path.open("a") as stream:
            stream.write(response[30:])
        reader.poll(); reader.poll()
        self.assertEqual(reader.cost, Decimal("0.015"))
        reader.path.write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "truncated"):
            reader.poll()

    def test_malformed_complete_record_is_visible_error(self):
        reader = self.reader()
        reader.path.write_text("{bad json}\n")
        with self.assertRaises(ValueError):
            reader.poll()

    def test_resumed_totals_before_first_response_do_not_poison_estimate(self):
        reader = self.reader()
        reader.consume(event("event_msg", {"type": "token_count", "info": {
            "total_token_usage": {"total_tokens": 1000}}}))
        self.assertIsNone(reader.snapshot()["cost"])
        reader.consume(context())
        reader.consume(usage())
        self.assertEqual(reader.snapshot()["cost"], "0.015")

    def test_large_resume_marks_estimate_unavailable_until_caught_up(self):
        reader = self.reader()
        reader.path.write_text((json.dumps(context(when=NOW-10)) + "\n") * 2001 +
                               json.dumps(context()) + "\n" + json.dumps(usage()) + "\n")
        reader.poll()
        self.assertIsNone(reader.snapshot()["cost"])
        self.assertEqual(reader.snapshot()["notice"], "reading session history")
        reader.poll()
        self.assertEqual(reader.snapshot()["cost"], "0.015")


class DisplayTests(TemporaryTest):
    def test_layout_tiers_escaping_and_narrow_terminal(self):
        data = {"backend": "api", "cwd": "/fictional/界/demo", "model": "demo-model", "effort": "max",
                "context": 85, "cost": "1.234", "branch": "topic#(touch /fictional/x)\x1b[31m", "memory": 100.5}
        header, row = status.render(data, 180)
        self.assertIn("#[fg=red]85%", row)
        self.assertIn("$1.23", row)
        self.assertNotIn("\x1b", row)
        self.assertIn("##(", row)
        for size in (180, 80, 40, 12, 7, 5, 3, 2, 1):
            plain = status.render(data, size, styled=False)
            self.assertEqual(status.width(plain[0]), status.width(plain[1]))
            self.assertLessEqual(status.width(plain[0]), size)
            if size >= 5:
                for line in plain:
                    self.assertTrue(line.startswith("  "))
                    self.assertTrue(line.endswith("  "))
            if size >= 7:
                self.assertIn("api", plain[1])

    def test_subscription_plan_quota_reset_and_stale_mark(self):
        data = {"backend": "subscription", "cost": "0", "limits": {"plan_type": "pro", "primary": {
            "used_percent": 60, "window_minutes": 300, "resets_at": NOW + 3600}, "secondary": {
            "used_percent": 30, "window_minutes": 10080}}, "limit_time": NOW}
        header, row = status.render(data, 180, NOW, False)
        self.assertIn("↻", header); self.assertIn("week", header); self.assertIn("pro", row)
        self.assertNotIn("·", row)
        self.assertIn("·20m", status.render(data, 180, NOW + 1200, False)[1])
        data["backend"] = "api"
        header, row = status.render(data, 180, NOW, False)
        self.assertNotIn("week", header); self.assertNotIn("pro", row)

    def test_git_states_with_rename_and_untracked_paths(self):
        subprocess.run(["git", "init", "-q", "-b", "demo", str(self.root)], check=True)
        (self.root / "before").write_text("fictional content\n")
        subprocess.run(["git", "-C", str(self.root), "add", "before"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Example User", "-c",
                        "user.email=example@example.invalid", "commit", "-qm", "Synthetic fixture"], check=True)
        subprocess.run(["git", "-C", str(self.root), "mv", "before", "after"], check=True)
        (self.root / "after").write_text("modified fictional content\n")
        (self.root / "untracked").write_text("fixture\n")
        self.assertEqual(status.git_state(self.root), "demo*+?")


class OwnershipTests(TemporaryTest):
    def test_duplicate_writers_are_detected_but_readers_are_allowed(self):
        file = self.root / "rollout-duplicate.jsonl"
        file.touch()
        code = "import sys; f=open(sys.argv[1],sys.argv[2]); print('ready',flush=True); sys.stdin.read()"
        for mode in ("a", "r"):
            child = subprocess.Popen([sys.executable, "-c", code, str(file), mode],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), "ready")
                writers = status.other_writers(file, {os.getpid()})
                self.assertEqual(writers, [child.pid] if mode == "a" else [])
                self.assertEqual(status.other_writers(file, {os.getpid(), child.pid}), [])
            finally:
                child.communicate(timeout=5)

    def test_process_descriptors_ignore_newer_unrelated_sessions_and_agents(self):
        sessions = self.root / "home/sessions"
        sessions.mkdir(parents=True)
        handles = []
        for name, sid, source in (("owned", SID, "cli"), ("agent", OTHER, {"subagent": {}}), ("newer", OTHER, "cli")):
            file = sessions / f"rollout-{name}.jsonl"
            file.write_text(json.dumps(event("session_meta", {"id": sid, "source": source})) + "\n")
            if name != "newer":
                handles.append(file.open("a"))
        self.addCleanup(lambda: [f.close() for f in handles])
        found = status.open_rollouts(os.getpid(), self.root / "home")
        self.assertEqual(list(found), [sessions / "rollout-owned.jsonl"])
        self.assertEqual(found[sessions / "rollout-owned.jsonl"], (os.getpid(), SID))
        self.assertEqual(status.open_rollouts(os.getpid(), self.root / "other-profile"), {})


class LauncherTests(TemporaryTest):
    def setUp(self):
        super().setUp()
        for profile in ("api", "subscription"):
            shutil.copy(REPO / f"harnesses/codex/profiles/{profile}.config.toml", self.root)

    def test_shared_keyring_helper_and_resume_arguments(self):
        api = launcher.launch_spec("api", ["resume", SID, "-m", "demo-model"], self.root)
        self.assertEqual(api["command"][0], str(launcher.API_HELPER))
        self.assertEqual(api["command"][-4:], ["resume", SID, "-m", "demo-model"])
        self.assertEqual(api["command"].count("--profile"), 1)
        self.assertIn("tui.status_line=[]", api["command"])
        self.assertEqual(launcher.launch_spec("subscription", [], self.root)["command"][0], "codex")

    def test_profile_and_authentication_overrides_are_rejected(self):
        for args in (["--profile=api"], ["-papi"], ["--remote=unix:///fictional"], ["--oss"],
                     ["-c", 'model_provider="other"'], ["--config=model_providers.other.env_key='key'"],
                     ["-c", "forced_login_method=api"], ["-m", "demo-model", "exec", "fictional prompt"]):
            with self.subTest(args=args), self.assertRaises(ValueError):
                launcher.launch_spec("subscription", args, self.root)
        (self.root / "subscription.config.toml").write_text('model_provider="openai_api"\n')
        with self.assertRaisesRegex(ValueError, "differs"):
            launcher.launch_spec("subscription", [], self.root)

    def test_native_unquoted_config_and_selected_home_are_preserved(self):
        (self.root / "config.toml").write_text('service_tier="priority"\n')
        result = launcher.launch_spec("api", ["-c", "service_tier=flex", "-c", "model_reasoning_effort=high"], self.root)
        self.assertEqual(result["tier"], "flex")
        self.assertEqual(result["codex_home"], str(self.root))
        self.assertEqual(launcher.launch_spec("api", [], self.root)["tier"], "priority")

    def test_credentials_and_other_session_environment_do_not_reach_tmux(self):
        values = {key: "synthetic-test-value" for key in (*launcher.AUTH_VARIABLES, "TMUX", "TMUX_PANE", "CODEX_THREAD_ID")}
        values["CODEX_HOME"] = str(self.root)
        with patch.dict(os.environ, values):
            env = launcher.clean_environment()
            self.assertEqual(env["CODEX_HOME"], str(self.root))
            for key in values:
                if key != "CODEX_HOME":
                    self.assertNotIn(key, env)
            self.assertIn("TMUX", launcher.clean_environment(detach_tmux=False))

    def test_unsupported_platform_has_actionable_fallback(self):
        with patch("platform.system", return_value="Darwin"), self.assertRaisesRegex(ValueError, "codex --profile subscription"):
            launcher.require_linux()

    def test_attach_refuses_shared_or_symlinked_directory(self):
        with self.assertRaises(ValueError):
            launcher.private_directory(self.root)
        link = self.root / "alias"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            launcher.private_directory(link)


class TmuxIntegrationTests(TemporaryTest):
    """Exercise the real tmux server with a fake Codex process and no credentials."""

    def assert_mouse_scrollback(self, mouse_reporting):
        binary = self.root / "bin"
        binary.mkdir()
        store = self.root / "codex-home"
        store.mkdir()
        shutil.copy(REPO / "harnesses/codex/profiles/subscription.config.toml", store)
        # Even a user's full-screen default must leave output in pane history.
        (store / "config.toml").write_text('[tui]\nalternate_screen="always"\n')
        received = self.root / "received"
        received.touch()
        fake = binary / "codex"
        fake.write_text('''#!/usr/bin/env python3
import os, pathlib, sys, tty
tty.setraw(sys.stdin.fileno())
if os.environ["DEMO_MOUSE"] == "1":
    sys.stdout.write("\\x1b[?1000h\\x1b[?1006h")
for i in range(2300):
    sys.stdout.write(f"Synthetic answer {i:04d}\\r\\n")
sys.stdout.write("Synthetic prompt ready")
sys.stdout.flush()
with pathlib.Path(os.environ["DEMO_RECEIVED"]).open("ab", buffering=0) as received:
    while True:
        received.write(os.read(sys.stdin.fileno(), 4096))
''')
        fake.chmod(0o755)
        env = {**launcher.clean_environment(), "TERM": "xterm-256color", "CODEX_HOME": str(store),
               "PATH": str(binary) + os.pathsep + os.environ["PATH"],
               "DEMO_MOUSE": str(int(mouse_reporting)), "DEMO_RECEIVED": str(received)}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(launcher, "attach", side_effect=lambda directory: directory):
            launch = launcher.launch_spec("subscription", [], store)
            runtime = launcher.launch(launch)
        self.addCleanup(lambda: shutil.rmtree(runtime) if runtime.exists() else None)
        self.addCleanup(lambda: launcher.tmux(runtime, "kill-server", check=False))
        master, slave = pty.openpty()
        termios.tcsetwinsize(slave, (24, 80))
        self.addCleanup(os.close, master)
        client = subprocess.Popen(["tmux", "-S", str(runtime / "socket"), "attach-session", "-t", "codex"],
                                  stdin=slave, stdout=slave, stderr=slave,
                                  env=env, start_new_session=True)
        os.close(slave)
        def close_client():
            if client.poll() is None:
                client.kill()
            client.wait(timeout=5)
        self.addCleanup(close_client)
        terminal = bytearray()

        def wait_for(predicate, message):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if select.select([master], [], [], .05)[0]:
                    terminal.extend(os.read(master, 65536))
                if predicate():
                    return
            self.fail(message)

        def pane_value(format):
            return launcher.tmux(runtime, "display-message", "-p", "-t", "codex:0", format).stdout.strip()

        wait_for(lambda: b"Synthetic prompt ready" in terminal, "synthetic prompt did not reach the terminal")
        self.assertEqual(pane_value("#{mouse_any_flag}"), str(int(mouse_reporting)))
        live = launcher.tmux(runtime, "capture-pane", "-p", "-t", "codex:0").stdout
        first_visible = int(re.search(r"Synthetic answer (\d+)", live)[1])
        older_line = f"Synthetic answer {first_visible - 1:04d}".encode()
        expected_input = b"draft"
        os.write(master, expected_input)
        wait_for(lambda: received.read_bytes() == expected_input, "draft did not reach the prompt")
        # SGR wheels over the prompt and legacy X10 wheels over the output.
        # These bytes enter the attached client, not tmux's send-keys shortcut.
        for up, down, cancel, keys in ((b"\x1b[<64;5;22M", b"\x1b[<65;5;22M", b"q", "emacs"),
                                       (b"\x1b[M`%%", b"\x1b[Ma%%", b"\x1b", "vi")):
            with self.subTest(up=up):
                launcher.tmux(runtime, "set-option", "-w", "-t", "codex:0", "mode-keys", keys)
                terminal.clear()
                os.write(master, up)
                wait_for(lambda: pane_value("#{pane_in_mode}") == "1", "wheel-up did not enter scrollback")
                self.assertGreater(int(pane_value("#{scroll_position}")), 0)
                # capture-pane -M can still return the live grid on tmux 3.7.
                # Prove older text is actually sent to the attached terminal.
                wait_for(lambda: older_line in terminal, "earlier output did not reach the terminal")
                os.write(master, down * 20)
                wait_for(lambda: pane_value("#{pane_in_mode}") == "0", "wheel-down did not return to the prompt")
                # Extra downward scrolling at the bottom must never reach Codex.
                os.write(master, down * 3)
                os.write(master, up)
                wait_for(lambda: pane_value("#{pane_in_mode}") == "1", "second wheel-up did not enter scrollback")
                os.write(master, cancel)
                wait_for(lambda: pane_value("#{pane_in_mode}") == "0", "cancel key did not leave scrollback")
                os.write(master, b"typed")
                expected_input += b"typed"
                wait_for(lambda: received.read_bytes().count(b"typed") == expected_input.count(b"typed"),
                         "typing did not reach the prompt")
                self.assertEqual(received.read_bytes(), expected_input, "a scroll event or copy-mode key reached Codex")
        self.assertIn('tui.alternate_screen="never"', launch["command"])
        # Verify the pane's actual history, not just a late global option change.
        self.assertEqual(pane_value("#{history_limit}"), "100000")
        history = launcher.tmux(runtime, "capture-pane", "-p", "-S", "-", "-t", "codex:0").stdout
        self.assertIn("Synthetic answer 0000", history)

    def test_wheel_scrolls_output_without_sending_prompt_history_keys(self):
        self.assert_mouse_scrollback(mouse_reporting=False)

    def test_wheel_scrolls_output_even_when_application_requests_mouse(self):
        self.assert_mouse_scrollback(mouse_reporting=True)

    def test_ctrl_d_replays_resume_output_after_leaving_tmux(self):
        binary = self.root / "bin"
        binary.mkdir()
        store = self.root / "codex-home"
        (store / "sessions").mkdir(parents=True)
        shutil.copy(REPO / "harnesses/codex/profiles/subscription.config.toml", store)
        ready = self.root / "ready.json"
        fake = binary / "codex"
        fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
store = pathlib.Path(os.environ["CODEX_HOME"])
with (store / "sessions/rollout-demo.jsonl").open("a") as f:
    f.write(json.dumps({"type": "session_meta", "payload": {
        "id": "22222222-2222-4222-8222-222222222222", "source": "cli"}}) + "\\n")
    f.flush()
    sys.stdout.write("\\x1b[?1049h\\x1b[2J\\x1b[HSynthetic session ready\\n")
    sys.stdout.flush()
    pathlib.Path(os.environ["DEMO_READY"]).write_text(json.dumps({"socket": os.environ["TMUX"].rsplit(",", 2)[0]}))
    sys.stdin.read()
sys.stdout.write("\\x1b[?1049l")
print("Token usage: total=1100 input=1000 output=100")
print("To continue this session, run:")
print("  codex resume 22222222-2222-4222-8222-222222222222")
''')
        fake.chmod(0o755)
        master, slave = pty.openpty()
        # The resume command must wrap inside this pane, then replay unbroken.
        termios.tcsetwinsize(slave, (10, 40))
        env = {**launcher.clean_environment(), "TERM": "xterm-256color", "CODEX_HOME": str(store),
               "PATH": str(binary) + os.pathsep + os.environ["PATH"], "DEMO_READY": str(ready)}
        process = subprocess.Popen([sys.executable, str(SCRIPT)], stdin=slave, stdout=slave,
                                   stderr=slave, env=env, start_new_session=True)
        os.close(slave)
        runtime = None
        try:
            deadline = time.monotonic() + 12
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(ready.exists(), "synthetic Codex did not start")
            runtime = Path(json.loads(ready.read_text())["socket"]).parent
            terminal = b""
            deadline = time.monotonic() + 5
            while b"Synthetic session ready" not in terminal and time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    terminal += os.read(master, 65536)
            self.assertIn(b"Synthetic session ready", terminal)
            launcher.tmux(runtime, "send-keys", "-t", "codex:0", "C-d")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    try:
                        terminal += os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        break  # Linux PTYs report EIO when their final slave closes.
                elif process.poll() is not None:
                    break
            self.assertEqual(process.wait(timeout=5), 0, terminal.decode(errors="replace"))
            restored = terminal.rfind(b"\x1b[?1049l")
            self.assertGreaterEqual(restored, 0, "tmux did not restore the calling terminal")
            replay = terminal[restored + len(b"\x1b[?1049l"):]
            self.assertIn(b"Token usage: total=1100 input=1000 output=100", replay)
            self.assertIn(b"To continue this session, run:", replay)
            self.assertIn(b"codex resume " + SID.encode(), replay)
            self.assertFalse(runtime.exists())
        finally:
            if runtime is not None and runtime.exists():
                launcher.tmux(runtime, "kill-server", check=False)
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            os.close(master)
            if runtime is not None and runtime.exists():
                shutil.rmtree(runtime)

    def test_two_launchers_keyring_isolation_and_attached_terminal(self):
        binary = self.root / "bin"
        binary.mkdir()
        store = self.root / "codex-home"
        (store / "sessions").mkdir(parents=True)
        for profile in ("api", "subscription"):
            shutil.copy(REPO / f"harnesses/codex/profiles/{profile}.config.toml", store)
        secret = binary / "secret-tool"
        secret.write_text("#!/bin/sh\n[ \"$1\" = lookup ] || exit 1\nprintf 'synthetic-keyring-key\\n'\n")
        secret.chmod(0o755)
        fake = binary / "codex"
        fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys, time
from datetime import datetime, timezone
store = pathlib.Path(os.environ["CODEX_HOME"])
name = os.environ["DEMO_SESSION_NAME"]
sid = "22222222-2222-4222-8222-222222222222" if name == "api" else "33333333-3333-4333-8333-333333333333"
snapshot = {"args": sys.argv[1:], "key": os.environ.get("CODEX_OPENAI_API_KEY"), "tmux": bool(os.environ.get("TMUX")), "inherited_thread": os.environ.get("CODEX_THREAD_ID")}
(store / (name + ".json")).write_text(json.dumps(snapshot))
def record(kind, payload):
    return json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "type": kind, "payload": payload}) + "\\n"
with (store / ("sessions/rollout-" + name + ".jsonl")).open("a") as f:
    f.write(record("session_meta", {"id": sid, "source": "cli"}))
    f.write(record("turn_context", {"model": "gpt-6-astra", "effort": "high" if name == "api" else "low", "cwd": str(store)}))
    f.write(record("token_usage_record", {"thread_id": sid, "response_id": "response-" + name, "usage": {"input_tokens": 1000 if name == "api" else 2000, "output_tokens": 100}}))
    f.flush()
    print("Synthetic Codex is running", flush=True)
    while not (store / ("stop-" + name)).exists(): time.sleep(.1)
''')
        fake.chmod(0o755)
        runtimes = {}
        environment = {"PATH": str(binary) + os.pathsep + os.environ["PATH"], "CODEX_HOME": str(store),
                       "CODEX_OPENAI_API_KEY": "synthetic-inherited-key", "CODEX_THREAD_ID": "unrelated-thread", "TERM": "xterm-256color"}
        for name in ("api", "subscription"):
            with patch.dict(os.environ, {**environment, "DEMO_SESSION_NAME": name}), \
                 patch.object(launcher, "attach", side_effect=lambda directory: directory):
                runtime = launcher.launch(launcher.launch_spec(name, [], store))
            runtimes[name] = runtime
            self.addCleanup(lambda directory=runtime: shutil.rmtree(directory) if directory.exists() else None)
            self.addCleanup(lambda directory=runtime: launcher.tmux(directory, "kill-server", check=False))
        deadline = time.monotonic() + 12
        snapshots = {}
        while time.monotonic() < deadline:
            for name, runtime in runtimes.items():
                if (runtime / "status.json").exists():
                    snapshots[name] = json.loads((runtime / "status.json").read_text())
            if all(snapshots.get(name, {}).get("model") for name in runtimes): break
            time.sleep(.1)
        self.assertEqual(snapshots["api"]["cost"], "0.015")
        self.assertEqual(snapshots["subscription"]["cost"], "0.025")
        self.assertEqual(snapshots["api"]["effort"], "high")
        self.assertEqual(snapshots["subscription"]["effort"], "low")
        for name, runtime in runtimes.items():
            native = json.loads((store / (name + ".json")).read_text())
            self.assertEqual(native["key"], "synthetic-keyring-key" if name == "api" else None)
            self.assertTrue(native["tmux"])
            self.assertIsNone(native["inherited_thread"])
            self.assertEqual(launcher.tmux(runtime, "show-environment", "-g", "CODEX_OPENAI_API_KEY", check=False).returncode, 1)
            self.assertNotIn("synthetic-key", (runtime / "launch.json").read_text())
        # Attach a genuine terminal client, verify the footer reaches the screen,
        # and exercise detach without stopping either synthetic Codex process.
        master, slave = pty.openpty()
        termios.tcsetwinsize(slave, (40, 180))
        self.addCleanup(os.close, master)
        client = subprocess.Popen(["tmux", "-S", str(runtimes["api"] / "socket"), "attach-session", "-t", "codex"],
                                  stdin=slave, stdout=slave, stderr=slave,
                                  env={**launcher.clean_environment(), "TERM": "xterm-256color"}, start_new_session=True)
        os.close(slave)
        def close_client():
            if client.poll() is None:
                client.kill()
            client.wait(timeout=5)
        self.addCleanup(close_client)
        terminal = b""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if select.select([master], [], [], .1)[0]:
                terminal += os.read(master, 65536)
                if b"profile" in terminal and b"api" in terminal: break
        self.assertIn(b"profile", terminal)
        self.assertIn(b"api", terminal)
        # Verify terminal SGR output, not just strings stored in tmux options:
        # bare colour names in #[...] look plausible but tmux ignores them.
        attributes = {int(code) for sgr in re.findall(rb"\x1b\[([0-9;]*)m", terminal)
                      for code in sgr.split(b";") if code}
        for code, name in ((1, "bold workspace"), (2, "dim headers"),
                           (34, "blue workspace"), (32, "green model"),
                           (35, "magenta effort"), (36, "cyan cost and memory")):
            self.assertIn(code, attributes, f"Missing terminal styling: {name}")
        launcher.tmux(runtimes["api"], "detach-client", "-s", "codex")
        self.assertEqual(client.wait(timeout=5), 0)
        self.assertFalse((runtimes["api"] / "exit.json").exists())
        for name in runtimes:
            (store / ("stop-" + name)).touch()
        deadline = time.monotonic() + 6
        while not all((p / "exit.json").exists() for p in runtimes.values()) and time.monotonic() < deadline:
            time.sleep(.1)
        for runtime in runtimes.values():
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(launcher.attach(runtime), 0)
            self.assertIn("Synthetic Codex is running", output.getvalue())

    def test_real_server_ownership_footer_escaping_and_exit(self):
        self.assertIsNotNone(shutil.which("tmux"), "Install tmux to run the Linux integration suite")
        runtime = Path(tempfile.mkdtemp(prefix="codex-tmux-", dir=Path.home() / "tmp"))
        self.addCleanup(lambda: shutil.rmtree(runtime) if runtime.exists() else None)
        self.addCleanup(lambda: launcher.tmux(runtime, "kill-server", check=False))
        store = self.root / "codex-home"
        sessions = store / "sessions"
        sessions.mkdir(parents=True)
        fake = self.root / "fake-codex.py"
        fake.write_text('''import json, os, pathlib, sys, time
from datetime import datetime, timezone
store, stop = map(pathlib.Path, sys.argv[1:])
def record(kind, payload):
    return json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "type": kind, "payload": payload}) + "\\n"
with (store / "sessions/rollout-owned.jsonl").open("a") as f:
    f.write(record("session_meta", {"id": "22222222-2222-4222-8222-222222222222", "source": "cli"}))
    f.write(record("turn_context", {"model": "gpt-6-astra", "effort": "high", "cwd": str(store)}))
    f.write(record("token_usage_record", {"thread_id": "22222222-2222-4222-8222-222222222222", "response_id": "synthetic-response", "usage": {"input_tokens": 1000, "output_tokens": 100}}))
    f.flush()
    while not stop.exists(): time.sleep(.1)
print("Synthetic startup failure: configure the demo option.", flush=True)
sys.exit(7)
''')
        stop = self.root / "stop"
        launcher.atomic_json(runtime / "launch.json", {"command": [sys.executable, str(fake), str(store), str(stop)],
                             "backend": "api", "tier": "default", "codex_home": str(store), "cwd": str(store)})
        launcher.tmux(runtime, "-f", "/dev/null", "new-session", "-d", "-s", "codex", "-x", "180", "-y", "40",
                      sys.executable, str(SCRIPT), "_run", str(runtime))
        for key, value in (("status", "2"), ("status-format[0]", "profile"), ("status-format[1]", "api")):
            launcher.tmux(runtime, "set-option", "-g", key, value)
        (runtime / "ready").touch()
        deadline = time.monotonic() + 12
        data = {}
        while time.monotonic() < deadline:
            if (runtime / "status.json").exists():
                data = json.loads((runtime / "status.json").read_text())
                if data.get("model") == "gpt-6-astra": break
            time.sleep(.1)
        self.assertEqual(data.get("model"), "gpt-6-astra", data)
        self.assertEqual(data["cost"], "0.015")
        self.assertGreater(data["memory"], 0)
        # Use tmux's real format evaluator to verify that display data cannot execute a job.
        _, malicious = status.render({"backend": "#(printf EXPLOITED)", "cost": "0"}, 200)
        result = launcher.tmux(runtime, "display-message", "-p", malicious).stdout
        self.assertIn("#(printf EXPLOITED)", result)
        # Allow one update tick after the snapshot was published.
        deadline = time.monotonic() + 3
        footer = ""
        while time.monotonic() < deadline:
            footer = launcher.tmux(runtime, "show-options", "-gv", "status-format[1]").stdout
            if "$0.02" in footer: break
            time.sleep(.1)
        self.assertIn("gpt-6-astra", footer)
        self.assertIn("api", footer)
        stop.touch()
        deadline = time.monotonic() + 6
        while not (runtime / "exit.json").exists() and time.monotonic() < deadline:
            time.sleep(.1)
        self.assertEqual(json.loads((runtime / "exit.json").read_text())["code"], 7)
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(launcher.attach(runtime), 7)
        self.assertIn("Synthetic startup failure: configure the demo option.", error.getvalue())
        self.assertFalse(runtime.exists())


if __name__ == "__main__":
    unittest.main()
