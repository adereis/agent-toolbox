"""Codex CLI as a seat."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from convene import quota
from convene.harnesses import Capabilities, Harness, granted, guard_text, may_search
from convene.storage import read, rows

FALLBACK = "Falling back from WebSockets to HTTPS transport."
NO_TOOLS = ["-c", "features.shell_tool=false", "-c", "features.unified_exec=false",
            "-c", "features.apps=false", "-c", "tools.view_image=false"]


class Codex(Harness):
    name = "codex"
    home_name = ".codex"
    home_variable = "CODEX_HOME"
    efforts = ("low", "medium", "high", "xhigh", "max", "ultra")
    capabilities = Capabilities(resume=True, fork=True, json_schema=False,
                                system_prompt=True, window_pinned=True)
    reserved = {
        "mcp_servers.": ("mcp", "grant mcp on the seat, then declare the server in config.toml "
                                "or here"),
        "web_search": (None, "grant web on the seat"),
        "model_reasoning_effort": (None, "set effort on the seat"),
        "sandbox_mode": (None, "set tools on the seat"),
        "project_doc_max_bytes": (None, "grant instructions"),
        "model_context_window": (None, "set compaction on the seat"),
        "model_auto_compact_token_limit": (None, "set compaction on the seat"),
        "--ignore-user-config": (None, "grant settings"),
        "--ignore-rules": (None, "grant instructions"),
        "-m": (None, "set model on the seat"), "--model": (None, "set model on the seat"),
        "-s": (None, "set tools on the seat"), "--sandbox": (None, "set tools on the seat"),
        "--json": (None, "the engine owns the stream"),
        "resume": (None, "the engine owns sessions"),
    }

    def check_args(self, seat):
        # `-c key=value` carries the key in the next token; check both shapes.
        args = list(seat.get("args") or [])
        flat = []
        for index, arg in enumerate(args):
            flat.append(arg[2:] if arg.startswith("-c") and len(arg) > 2 else
                        (args[index + 1] if arg == "-c" and index + 1 < len(args) else arg))
        super().check_args({**seat, "args": flat})

    def catalog(self, environ=None):
        path = self.real_home(environ) / "models_cache.json"
        return path, (read(path).get("models", []) if path.exists() else None)

    def resolve(self, model, effort, environ=None):
        model = re.sub(r"^(gpt-\d+)-(\d+)", r"\1.\2", str(model))
        path, models = self.catalog(environ)
        out = {"model": model, "effort": effort, "context_window": None,
               "model_evidence": "native turn context"}
        if models is None:
            if effort not in self.efforts:
                raise ValueError(f"codex effort must be one of {', '.join(self.efforts)}: {effort!r}")
            out["catalog"] = f"absent: {path}; start codex once to refresh it"
            return out
        item = next((m for m in models if m.get("slug") == model), None)
        if item is None:
            raise ValueError(f"Codex catalog {path} does not list {model!r}")
        levels = [r["effort"] for r in item.get("supported_reasoning_levels", [])]
        if levels and effort not in levels:
            raise ValueError(f"{model} supports efforts {levels}, not {effort!r}")
        out["context_window"] = item.get("max_context_window") or item.get("context_window")
        out["catalog"] = str(path)
        return out

    def prepare_home(self, home):
        Path(home).mkdir(parents=True, exist_ok=True)

    def credential_files(self, real_home):
        return [Path(real_home) / "auth.json"]

    def credential_env(self, real_home, environ=None):
        return {}

    def stage_credentials(self, home, real_home):
        """Copy the login into the private home, 0600, for the turn's duration."""
        source, target = Path(real_home) / "auth.json", Path(home) / "auth.json"
        if not source.exists():
            raise RuntimeError(f"no Codex login at {source}; run `codex login` first")
        Path(home).mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
        os.chmod(target, 0o600)

    def unstage_credentials(self, home):
        target = Path(home) / "auth.json"
        if target.exists():
            target.unlink()

    def sandbox(self, tools):
        return "workspace-write" if tools == "write" else "read-only"

    def command(self, seat, mode, session_id, prompt, cwd):
        prompt = prompt + guard_text(seat)
        args = ["codex", "exec"]
        if mode != "start":
            args += ["resume", session_id]
        # The user config carries MCP servers, so `mcp` opens it as `settings` does.
        if not (granted(seat, "settings") or granted(seat, "mcp")):
            args += ["--ignore-user-config"]
        if not granted(seat, "instructions"):
            args += ["--ignore-rules"]
        args += ["--skip-git-repo-check",
                 "-m", seat["model"], "-c", f'model_reasoning_effort="{seat["effort"]}"',
                 "-c", 'personality="none"', "-c", 'model_verbosity="high"']
        if not granted(seat, "instructions"):
            args += ["-c", "project_doc_max_bytes=0"]
        args += ["-c", "features.multi_agent=false",
                 "-c", 'web_search="live"' if may_search(seat) else 'web_search="disabled"']
        # `codex exec resume` refuses -s; the sandbox travels as config there.
        if mode == "start":
            args += ["-s", self.sandbox(seat["tools"])]
        else:
            args += ["-c", f'sandbox_mode="{self.sandbox(seat["tools"])}"']
        if seat["tools"] == "none":
            args += NO_TOOLS
        window = seat.get("context_window")
        if window and seat.get("compaction", "forbid") == "forbid":
            # Without the scope, the limit is clamped to 90% of the window and
            # compaction fires anyway (Codex 0.153+).
            args += ["-c", f"model_context_window={window}",
                     "-c", f"model_auto_compact_token_limit={window}",
                     "-c", 'model_auto_compact_token_limit_scope="body_after_prefix"']
        args += list(seat.get("args") or [])
        return args + ["--json", "-"], prompt.encode("utf-8")

    def session_paths(self, home, session_id):
        return sorted((Path(home) / "sessions").rglob(f"*{session_id}.jsonl"))

    def classify_stop(self, record):
        return quota.classify("codex", record)

    def receipt(self, seat, record, home, expected_session=None):
        stream = rows(Path(record) / "events.jsonl")
        ids = {r["thread_id"] for r in stream if r.get("type") == "thread.started"}
        complete = [r for r in stream if r.get("type") == "turn.completed"]
        answers, notices, calls = [], [], []
        for row in stream:
            if row.get("type") != "item.completed":
                continue
            item = row["item"]
            kind = item.get("type")
            if kind == "agent_message":
                answers.append(item.get("text", ""))
            elif kind == "error":
                if item.get("message", "").startswith(FALLBACK):
                    notices.append(item["message"])
                else:
                    raise RuntimeError("Codex error item: " + item.get("message", "")[:200])
            elif kind not in ("reasoning", "todo_list"):
                calls.append(item)
        if len(ids) != 1 or not complete or not answers:
            raise RuntimeError("Codex receipt is incomplete or ambiguous")
        sid = ids.pop()
        if expected_session and sid != expected_session:
            raise RuntimeError(f"resume landed in session {sid}, not {expected_session}")
        answer = answers[-1]
        usage = complete[-1].get("usage")
        if not usage or not usage.get("output_tokens"):
            raise RuntimeError("Codex has no output-token receipt")
        paths = self.session_paths(home, sid)
        if len(paths) != 1:
            raise RuntimeError(f"expected one native Codex session for {sid}, found {len(paths)}")
        native = rows(paths[0])
        contexts = [r["payload"] for r in native if r.get("type") == "turn_context"]
        if not contexts:
            raise RuntimeError("native Codex rollout carries no turn context")
        if any(c.get("model") != seat["model"] or c.get("effort") != seat["effort"]
               for c in contexts):
            served = sorted({(c.get("model"), c.get("effort")) for c in contexts})
            raise RuntimeError(f"Codex served {served}, requested "
                               f"({seat['model']}, {seat['effort']})")
        expected = self.sandbox(seat["tools"])
        if any((c.get("sandbox_policy") or {}).get("type") != expected for c in contexts):
            raise RuntimeError("Codex served sandbox policy differs from the declared tools")
        native_calls = [r["payload"] for r in native
                        if r.get("type") == "response_item"
                        and str(r.get("payload", {}).get("type", "")).endswith("_call")]
        if seat["tools"] == "none" and (calls or native_calls):
            raise RuntimeError("tool use violates the declared no-tools policy")
        for call in calls:
            kind = call.get("type", "")
            if kind == "mcp_tool_call" and not granted(seat, "mcp"):
                raise RuntimeError("an MCP tool reached the seat")
            if not may_search(seat):
                if kind == "web_search":
                    raise RuntimeError("web search violates the declared policy")
                if re.search(r"https?://|\b(curl|wget)\b", str(call.get("command", ""))):
                    raise RuntimeError("network use in a shell command violates the declared policy")
        if not answer.strip():
            raise RuntimeError("empty completed answer")
        return {
            "session_id": sid, "model": contexts[-1]["model"],
            "requested_model": seat["model"], "model_evidence": "native turn context",
            "effort": seat["effort"], "effort_evidence": "native turn context",
            "usage": usage, "tool_calls": len(calls),
            "tools_used": sorted({c.get("type", "") for c in calls}),
            "native_transcripts": [str(paths[0])], "notices": notices, "answer": answer,
        }

    def usage_totals(self, usage):
        if not isinstance(usage, dict) or not usage:
            return None
        return {
            "input": usage.get("input_tokens") or 0,
            "output": usage.get("output_tokens") or 0,
            "reasoning": usage.get("reasoning_output_tokens") or 0,
            "cache_read": usage.get("cached_input_tokens") or 0,
            "cost_usd": None,
            "cache_inside_input": True,
        }

    @property
    def probes(self):
        from convene.doctor import Probe
        return (
            Probe("web_search", ("exec", "--ignore-user-config", "-c", 'web_search="bogus"', "x"),
                  needles=("unknown variant", "disabled"),
                  why="codex ships a live web tool on by default; a dead key hands it back"),
            Probe("personality", ("exec", "--ignore-user-config", "-c", 'personality="bogus"', "x"),
                  needles=("unknown variant", "none"),
                  why="the register pin, codex's analogue of --settings"),
            Probe("--ignore-user-config", ("exec", "--ignore-user-config", "--help"),
                  expect="ok", why="keeps the operator's config and rules out of the seat"),
        )
