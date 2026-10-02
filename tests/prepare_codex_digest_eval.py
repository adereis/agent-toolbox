#!/usr/bin/env python3
"""Prepare synthetic utility reports for supervised Luna prompt evaluation.

Usage: python3 tests/prepare_codex_digest_eval.py ~/tmp/PRIVATE_RUN/reports
The destination must be new and beneath ~/tmp. No model or network calls,
user configuration reads, or real baseline writes are made.
"""

import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "tools"), str(REPO / "harnesses/codex")]
import _release_digest as adapter

spec = importlib.util.spec_from_file_location(
    "codex_digest_eval", REPO / "harnesses/codex/scripts/codex-whats-new.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def prepare(destination):
    destination = destination.expanduser().resolve()
    if not destination.is_relative_to((Path.home() / "tmp").resolve()):
        raise ValueError("Evaluation output must be under ~/tmp")
    destination.mkdir(parents=True, mode=0o700)
    archive = REPO / "tests/fixtures/codex-whats-new/releases.json"
    cases = {}
    for name, memories in (("disabled", False), ("enabled", True),
                           ("topic", False), ("empty", False)):
        home = destination / name
        codex = home / ".codex"
        project = home / "project"
        codex.mkdir(parents=True)
        project.mkdir()
        (codex / "config.toml").write_text(
            'sandbox_mode = "workspace-write"\napproval_policy = "on-request"\n'
            '[features]\nhooks = false\nmemories = ' + str(memories).lower() + '\n'
            'multi_agent = true\n[tui]\neditor_mode = "vim"\n'
            '[otel]\nlog_user_prompt = false\n', encoding="utf-8")
        (codex / "hooks.json").write_text('{"hooks":{"PreToolUse":[]}}', encoding="utf-8")
        (codex / "rules").mkdir()
        arguments = ["--codex-dir", str(codex), "--project", str(project),
                     "--changelog", str(archive), "--state", str(home / "baseline.json")]
        if name == "topic":
            arguments += ["--topic", "helpers", "--topic", "subagents", "--limit", "0"]
        else:
            arguments += ["--since", "9.3.0" if name == "empty" else "9.1.0"]
        report = destination / f"{name}.md"
        with patch.dict(os.environ, {"HOME": str(home), "TERM": "xterm-256color",
                                     "KITTY_PID": "123"}, clear=True), \
                patch.object(adapter, "SYSTEM_CONFIG", destination / "absent-system.toml"), \
                patch.object(adapter, "running_version", return_value="9.3.0"), \
                report.open("w", encoding="utf-8") as output, \
                contextlib.redirect_stdout(output):
            result = cli.main(arguments)
        if result:
            raise RuntimeError(f"Utility failed preparing {name}; exit {result}")
        if (home / "baseline.json").exists():
            raise RuntimeError(f"Evaluation unexpectedly wrote a baseline for {name}")
        cases[name] = {"report": str(report), "arguments": arguments}
    (destination / "cases.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    return destination / "cases.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(prepare(args.destination))
