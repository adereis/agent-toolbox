"""Shared fixtures for the convene tests: an isolated home, stub harnesses,
fake credentials and a small git project, all under ~/tmp."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "harnesses/claude-code/plugins/convene"
ENGINE = PLUGIN / "engine"
STUBS = Path(__file__).resolve().parent / "convene-stubs"
FAKE_BWRAP = STUBS / "fake-bwrap"

if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))


class Sandbox:
    """Everything a run touches, redirected into one temporary directory."""

    def __init__(self, testcase, *, claude_credentials=True, codex_auth=True, fake_bwrap=False):
        base = Path.home() / "tmp"
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base, prefix="convene-test.")
        testcase.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "tmp").mkdir()
        self.state = self.root / "state"
        env = {"HOME": str(self.home), "XDG_STATE_HOME": str(self.state),
               "PATH": (f"{FAKE_BWRAP}:" if fake_bwrap else "") + f"{STUBS}:{os.environ.get('PATH', '')}",
               "SECRET_FROM_OPERATOR": "must-not-leak", "TERM": "dumb", "LANG": "C.UTF-8"}
        for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "CLAUDE_CODE_OAUTH_TOKEN",
                     "ANTHROPIC_API_KEY"):
            env.setdefault(name, "")
        self.patcher = patch.dict(os.environ, env)
        self.patcher.start()
        testcase.addCleanup(self.patcher.stop)
        for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "CLAUDE_CODE_OAUTH_TOKEN",
                     "ANTHROPIC_API_KEY"):
            os.environ.pop(name, None)
        if claude_credentials:
            self.write_claude_credentials()
        if codex_auth:
            (self.home / ".codex").mkdir(exist_ok=True)
            (self.home / ".codex/auth.json").write_text(json.dumps({"tokens": "fake"}))
        (self.home / ".codex").mkdir(exist_ok=True)
        (self.home / ".codex/models_cache.json").write_text(json.dumps({"models": [
            {"slug": "gpt-5.5", "context_window": 272000, "max_context_window": 272000,
             "supported_reasoning_levels": [{"effort": e} for e in ("low", "medium", "high")]},
            {"slug": "gpt-5.6-sol", "context_window": 272000, "max_context_window": 872000,
             "supported_reasoning_levels": [{"effort": e} for e in ("low", "medium", "high", "xhigh")]},
        ]}))
        self.project = self.root / "project"
        self.make_project()

    def write_claude_credentials(self, expires_in=3600):
        (self.home / ".claude").mkdir(exist_ok=True)
        (self.home / ".claude/.credentials.json").write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "sk-ant-oat-fake-access", "refreshToken": "sk-ant-ort-fake-refresh",
            "expiresAt": int((time.time() + expires_in) * 1000)}}))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.project), *args], check=True,
                              capture_output=True, text=True,
                              env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.com",
                                   "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.com"}).stdout

    def make_project(self):
        self.project.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.project / "AGENTS.md").write_text("# Project rules\nSecret project guidance.\n")
        (self.project / "app.py").write_text("def add(a, b):\n    return a + b\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "Initial commit")
        (self.project / "app.py").write_text("def add(a, b):\n    return a - b\n")
        (self.project / "docs.md").write_text("Notes about the change.\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "Break addition\n\nOn purpose, for the panel to find.")

    def plan(self, name="plan.toml", **fields):
        """Write a plan file; `seats` is a list of dicts, everything else top-level."""
        seats = fields.pop("seats", [{"id": "skeptic", "persona": "quinn-t-shun"}])
        materials = fields.pop("materials", [])
        tables = {k: fields.pop(k) for k in list(fields) if isinstance(fields[k], list)
                  and fields[k] and isinstance(fields[k][0], dict)}
        base = {"schema": 1, "kind": "panel", "title": "Test panel", "isolation": "private-home",
                "brief": {"text": "Review this change carefully."}, "harness": "claude",
                "model": "opus", "effort": "high"}
        base.update(fields)
        base = {k: v for k, v in base.items() if v is not None}
        lines = []
        for key, value in base.items():
            if isinstance(value, dict):
                continue
            lines.append(f"{key} = {json.dumps(value)}")
        for key, value in base.items():
            if isinstance(value, dict):
                lines.append(f"[{key}]")
                for k, v in value.items():
                    lines.append(f"{k} = {json.dumps(v)}")
        for item in materials:
            lines.append("[[materials]]")
            lines += [f"{k} = {json.dumps(v)}" for k, v in item.items()]
        for key, items in tables.items():
            for item in items:
                lines.append(f"[[{key}]]")
                lines += [f"{k} = {json.dumps(v)}" for k, v in item.items()]
        for seat in seats:
            lines.append("[[seats]]")
            private = seat.pop("materials", [])
            lines += [f"{k} = {json.dumps(v)}" for k, v in seat.items()]
            for item in private:
                lines.append("[[seats.materials]]")
                lines += [f"{k} = {json.dumps(v)}" for k, v in item.items()]
        path = self.root / name
        path.write_text("\n".join(lines) + "\n")
        return path

    def calls(self, seat, harness):
        path = self.state / "agent-toolbox/convene"
        found = list(path.rglob(f"homes/{seat}/{harness}/stub-calls.jsonl"))
        if not found:
            return []
        return [json.loads(line) for line in found[0].read_text().splitlines()]
