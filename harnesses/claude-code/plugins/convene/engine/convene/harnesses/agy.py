"""Antigravity (`agy`) as a seat.

The least confinable of the three harnesses: it exposes no tool
allow-list, no setting-source switch, no context ceiling and no variable
that relocates its home. A seat here therefore always runs with write
tools, its filesystem access is audited from the transcript rather than
enforced by a flag, compaction can only be detected, and the private home
exists only inside the enforced jail, where `~/.gemini` is bound from the
seat's private directory. `private-home` is refused by name.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from convene import quota
from convene.harnesses import Capabilities, Harness, granted, guard_text
from convene.storage import read, rows

TRANSCRIPT = "antigravity-cli/brain/{sid}/.system_generated/logs/transcript_full.jsonl"
DONE = ("SUCCESS", "COMPLETED", "DONE")
FORBIDDEN_WEB = re.compile(r"browser|search_web|web_search|google_web_search|read_url|fetch_url", re.I)
FORBIDDEN_MCP = re.compile(r"^mcp|mcp__", re.I)
FORBIDDEN_DELEGATION = re.compile(r"invoke_subagent|send_message|schedule", re.I)


class Antigravity(Harness):
    name = "agy"
    home_name = ".gemini"
    # What a seat gets when the plan names no model.
    default_model = "gemini-3.1-pro"
    home_variable = ""  # nothing relocates it; only the jail can give it a private home
    efforts = ("low", "medium", "high")
    capabilities = Capabilities(resume=True, fork=False, json_schema=False,
                                system_prompt=False, window_pinned=False)
    tool_sets = ("write",)
    reserved = {
        "--model": (None, "set model on the seat"), "--effort": (None, "set effort on the seat"),
        "--conversation": (None, "the engine owns sessions"),
        "--print": (None, "the engine owns the launch mode"), "-p": (None, "the engine owns the launch mode"),
        "--output-format": (None, "the engine owns the stream"),
        "--input-format": (None, "the engine owns the stream"),
    }

    def private_env(self, home):
        return {}

    def models(self, timeout=45):
        """The slugs `agy models` lists, or None when the lookup fails."""
        try:
            result = subprocess.run(["agy", "models"], capture_output=True, text=True,
                                    timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode:
            return None
        return [line.split()[0] for line in result.stdout.splitlines()
                if line.strip() and not line.startswith(("Fetching", " "))]

    def resolve(self, model, effort, environ=None):
        if effort not in self.efforts:
            raise ValueError(f"agy effort must be one of {', '.join(self.efforts)}: {effort!r}")
        model = str(model)
        available = self.models()
        out = {"model": model, "effort": effort, "context_window": None,
               "model_evidence": "result.model in the stream"}
        if available is None:
            out["catalog"] = "agy models did not answer; the model is taken as written"
            return out
        if model not in available and f"{model}-{effort}" in available:
            model = f"{model}-{effort}"
        if model not in available:
            raise ValueError(f"agy does not list {model!r}; `agy models` prints the slugs")
        out.update(model=model, catalog="agy models")
        return out

    def prepare_home(self, home):
        Path(home).mkdir(parents=True, exist_ok=True)

    def credential_files(self, real_home):
        real_home = Path(real_home)
        return [real_home / name for name in ("oauth_creds.json", "google_accounts.json",
                                              "settings.json", "installation_id")]

    def credential_env(self, real_home, environ=None):
        if not (Path(real_home) / "oauth_creds.json").exists():
            raise RuntimeError(f"no Antigravity login at {real_home}/oauth_creds.json; run `agy` "
                               "once to log in")
        return {}

    def stage_credentials(self, home, real_home):
        raise RuntimeError("agy has no private-home tier: nothing relocates ~/.gemini; use "
                           "isolation = \"enforced\" (Linux, bubblewrap) or \"none\"")

    def unstage_credentials(self, home):
        return None

    def command(self, seat, mode, session_id, prompt, cwd):
        prompt = prompt + guard_text(seat)
        args = ["stdbuf", "-oL", "-eL"] if shutil.which("stdbuf") else []
        args += ["agy", "--print=", "--input-format", "stream-json", "--output-format",
                 "stream-json", "--model", seat["model"], "--effort", seat["effort"],
                 "--disable-slash-commands", "--print-timeout", "60m",
                 "--dangerously-skip-permissions"]
        if mode == "fork":
            raise ValueError("agy exposes no native fork")
        if mode != "start":
            args += ["--conversation", session_id]
        args += list(seat.get("args") or [])
        import json
        payload = json.dumps({"event": "user", "message": {
            "role": "user", "content": [{"type": "text", "text": prompt}]}}) + "\n"
        return args, payload.encode("utf-8")

    def session_paths(self, home, session_id):
        return sorted(Path(home).glob(TRANSCRIPT.format(sid=session_id)))

    def classify_stop(self, record):
        return quota.classify("agy", record)

    def receipt(self, seat, record, home, expected_session=None):
        record = Path(record)
        stream = rows(record / "events.jsonl")
        results = [r["result"] for r in stream if r.get("event") == "result"]
        ids = {r["conversation_id"] for r in stream if r.get("conversation_id")}
        if len(results) != 1 or len(ids) != 1:
            raise RuntimeError("agy has no unique completed result")
        result = results[0]
        if result.get("status") not in DONE:
            raise RuntimeError(f"agy result status {result.get('status')!r}: "
                               f"{str(result.get('error') or result.get('response') or '')[:200]}")
        sid = ids.pop()
        if expected_session and sid != expected_session:
            raise RuntimeError(f"resume landed in conversation {sid}, not {expected_session}")
        model = result.get("model") or next(
            (r.get("init", {}).get("model") for r in stream if r.get("event") == "init"), None)
        if model != seat["model"]:
            raise RuntimeError(f"agy served {model!r}, requested {seat['model']!r}")
        answer = result.get("response", "") or ""
        usage = result.get("usage")
        paths = self.session_paths(home, sid)
        if len(paths) != 1:
            raise RuntimeError(f"expected one native agy transcript for {sid}, found {len(paths)}")
        calls = []
        for row in stream:
            step = row.get("step_update") or {}
            if step.get("step_type") == "tool" and step.get("state") == "ACTIVE":
                calls.append({"name": step.get("tool_name") or "",
                              "parameters": (step.get("tool_info") or {}).get("parameters") or {}})
        self._audit(seat, record, calls)
        if not answer.strip():
            raise RuntimeError("empty completed answer")
        return {
            "session_id": sid, "model": model, "requested_model": seat["model"],
            "model_evidence": "result.model in the stream", "effort": seat["effort"],
            "effort_evidence": "CLI selection", "usage": usage, "tool_calls": len(calls),
            "tools_used": sorted({c["name"] for c in calls}),
            "native_transcripts": [str(paths[0])], "answer": answer,
            "filesystem": "audited from the transcript; agy has no tool allow-list",
        }

    def _audit(self, seat, record, calls):
        """What a flag cannot enforce here, the transcript is checked for."""
        launch = read(record / "launch.json") if (record / "launch.json").exists() else {}
        attestation = launch.get("isolation") or {}
        cwd = attestation.get("chdir") or launch.get("cwd")
        allowed = [Path(os.path.normpath(p)) for p in
                   (cwd, attestation.get("repository_read_only")) if p]
        for call in calls:
            name = call["name"]
            if FORBIDDEN_DELEGATION.search(name):
                raise RuntimeError(f"delegation or messaging tool reached the seat: {name}")
            if FORBIDDEN_MCP.search(name) and not granted(seat, "mcp"):
                raise RuntimeError(f"an MCP tool reached the seat: {name}")
            if FORBIDDEN_WEB.search(name) and not (granted(seat, "web") or seat["tools"] == "research"):
                raise RuntimeError(f"network tool use violates the declared policy: {name}")
            params = call["parameters"] if isinstance(call["parameters"], dict) else {}
            for key, value in params.items():
                if isinstance(value, str) and ("path" in key.lower() or "file" in key.lower()):
                    path = Path(value).expanduser()
                    if not path.is_absolute():
                        if not cwd:
                            raise RuntimeError("agy path audit has no declared working directory")
                        path = Path(cwd) / path
                    # The jail also exposes runtime paths such as /etc; its
                    # presence does not make every filesystem call in scope.
                    # Normalize lexically in the seat's namespace, not via
                    # resolve() in the operator's different mount namespace.
                    path = Path(os.path.normpath(path))
                    if not any(path == root or root in path.parents for root in allowed):
                        raise RuntimeError(f"agy reached a path outside the declared workspace: {value}")

    def usage_totals(self, usage):
        if not isinstance(usage, dict) or not usage:
            return None
        return {"input": usage.get("input_tokens") or 0, "output": usage.get("output_tokens") or 0,
                "reasoning": usage.get("thinking_tokens") or 0,
                "cache_read": usage.get("cache_read_tokens") or 0, "cost_usd": None,
                "cache_inside_input": False}

    @property
    def probes(self):
        from convene.doctor import Probe
        return (Probe("--model", ("-p", "x", "--model", "bogus-model-xyz"),
                      needles=("not recognized", "Available models"), offline=False,
                      why="agy renames its models often and a seat's model is its only receipt"),)
