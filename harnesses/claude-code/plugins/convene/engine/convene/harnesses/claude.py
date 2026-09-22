"""Claude Code as a seat."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from convene import quota
from convene.harnesses import (Capabilities, Harness, granted, guard_text, is_family,
                               may_search, model_matches)
from convene.storage import read, rows, write

# Claude Code resolves its own aliases to the latest model of each family,
# and has no local catalog of full ids, so the engine keeps no list of
# versions: an alias passes through, and the served id is checked against it
# on the receipt. Source for the aliases: `claude --model` help text. A
# version is written by the user as `opus-5.5` or `claude-opus-5-5`; both
# reach the CLI as the latter. A name that is neither is refused at prepare,
# not at launch where it returns `unrecognized_model`, and the refusal names
# what would have worked.
ALIASES = ("fable", "opus", "sonnet", "haiku")


def entitled_models(real_home=None):
    """Extra model ids this account was offered, from Claude Code's own cache."""
    home = Path(real_home) if real_home else Path.home()
    try:
        cached = read(home / ".claude.json") or {}
    except Exception:
        return ()
    found = []
    for item in cached.get("additionalModelOptionsCache") or ():
        value = item.get("value") if isinstance(item, dict) else None
        if isinstance(value, str) and value:
            # A cached value may carry a context-window suffix, as in
            # `claude-fable-5-1[1m]`; the bare id is what --model takes.
            found.append(value.split("[", 1)[0])
    return tuple(found)


def resolve_model(model, real_home=None):
    """User shorthand to a name Claude Code accepts; (name, note) or raise.

    `opus-5.5` is what a person says and `claude-opus-5-5` is what the CLI
    takes: Claude ids spell versions with dashes, never dots.
    """
    text = str(model).strip().lower()
    if not text:
        raise ValueError("claude model must not be empty")
    bare = text.removeprefix("claude-").replace(".", "-")
    if bare in ALIASES:
        return bare, None
    if not is_family(bare) and (text.startswith("claude-") or bare.split("-")[0] in ALIASES):
        full = f"claude-{bare}"
        if full in entitled_models(real_home):
            return full, None
        return full, (f"{full} is not in Claude Code's cached model list; the receipt "
                      "verifies what is served")
    raise ValueError(
        f"claude model {model!r} is not a name Claude Code accepts. Use a family alias "
        f"({', '.join(ALIASES)}), which the CLI resolves to its latest model, or a version "
        f"such as opus-5.5 or claude-opus-5-5.")


# Overrides the operator's settings for the seat only: pins the output style
# (an Explanatory style makes the model teach instead of answer) and stops
# lifecycle hooks from running inside a seat unless `hooks` is granted.
def settings_flag(seat):
    pinned = {"outputStyle": "default"}
    if not granted(seat, "hooks"):
        pinned["disableAllHooks"] = True
    return ["--settings", json.dumps(pinned)]
# Loads no setting sources at all, which is what keeps the global CLAUDE.md
# out of the seat; `--setting-sources project` does not close it.
NO_SETTING_SOURCES = ["--setting-sources", ""]
# MCP servers come from the account, not from files; only an empty strict
# config removes them.
NO_MCP = ["--mcp-config", json.dumps({"mcpServers": {}}), "--strict-mcp-config"]

# `--tools ""` is a measured no-op (it falls back to the default set), so the
# floor is one harmless tool. Only an allow-list restricts; never a deny-list.
TOOL_SETS = {
    "none": "Read",
    "read": "Read,Glob,Grep",
    "write": "Read,Write,Edit,Glob,Grep,Bash",
    "research": "Read,Glob,Grep,WebSearch,WebFetch",
}
MAX_WINDOW = 1_000_000
KEYCHAIN_HINT = 'security find-generic-password -s "Claude Code-credentials" -w'


class Claude(Harness):
    name = "claude"
    home_name = ".claude"
    # What a seat gets when the plan names no model: a family, never a version.
    default_model = "opus"
    home_variable = "CLAUDE_CONFIG_DIR"
    efforts = ("low", "medium", "high", "xhigh", "max")
    capabilities = Capabilities(resume=True, fork=True, json_schema=True,
                                system_prompt=True, window_pinned=True)
    reserved = {
        "--mcp-config": ("mcp", "grant mcp on the seat; the config then loads beside the "
                                "account's servers"),
        "--strict-mcp-config": (None, "grant mcp instead"),
        "--setting-sources": (None, "grant settings or instructions instead"),
        "--settings": (None, "grant hooks or settings instead; the output style stays pinned"),
        "--tools": (None, "set tools on the seat, or grant web"),
        "--allowedTools": (None, "set tools on the seat, or grant web"),
        "--model": (None, "set model on the seat"), "--effort": (None, "set effort on the seat"),
        "--session-id": (None, "the engine owns sessions"),
        "--resume": (None, "the engine owns sessions"),
        "--fork-session": (None, "the engine owns sessions"),
        "--autocompact": (None, "set compaction on the seat"),
        "-p": (None, "the engine owns the launch mode"),
        "--output-format": (None, "the engine owns the stream"),
        "--input-format": (None, "the engine owns the stream"),
    }

    def resolve(self, model, effort, environ=None):
        model, note = resolve_model(model)
        if effort not in self.efforts:
            raise ValueError(f"claude effort must be one of {', '.join(self.efforts)}: {effort!r}")
        out = {"model": model, "effort": effort, "context_window": MAX_WINDOW,
               "model_evidence": "explicit model; served identity verified after launch"}
        if note:
            out["catalog"] = note
        return out

    def prepare_home(self, home):
        config = Path(home) / ".claude.json"
        if not config.exists():
            write(config, {"hasCompletedOnboarding": True, "theme": "dark"})

    def credential_files(self, real_home):
        return []  # the token travels in the environment; the file never enters a seat

    def credential_env(self, real_home, environ=None):
        """A short-lived access token, never the refresh token.

        The credentials file holds both; passing only the access token keeps
        the long-lived secret out of every seat. On macOS the file lives in
        the Keychain, so the operator supplies the token themselves.
        """
        import os
        environ = os.environ if environ is None else environ
        if environ.get("ANTHROPIC_API_KEY"):
            return {"ANTHROPIC_API_KEY": environ["ANTHROPIC_API_KEY"]}
        if environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return {"CLAUDE_CODE_OAUTH_TOKEN": environ["CLAUDE_CODE_OAUTH_TOKEN"]}
        path = Path(real_home) / ".credentials.json"
        if not path.exists():
            hint = (f"on macOS export CLAUDE_CODE_OAUTH_TOKEN=\"$({KEYCHAIN_HINT})\""
                    if sys.platform == "darwin"
                    else f"run `claude` once to log in, or export CLAUDE_CODE_OAUTH_TOKEN")
            raise RuntimeError(f"no Claude credentials at {path}; {hint}")
        oauth = read(path).get("claudeAiOauth", {})
        if not oauth.get("accessToken") or oauth.get("expiresAt", 0) / 1000 < time.time() + 300:
            raise RuntimeError("Claude access token missing or expiring within five minutes; "
                               "run `claude` once to renew it, then retry")
        return {"CLAUDE_CODE_OAUTH_TOKEN": oauth["accessToken"]}

    def stage_credentials(self, home, real_home):
        return None

    def unstage_credentials(self, home):
        return None

    def tool_list(self, seat):
        tools = TOOL_SETS[seat["tools"]]
        if granted(seat, "web") and "WebSearch" not in tools:
            tools += ",WebSearch,WebFetch"
        return tools

    def command(self, seat, mode, session_id, prompt, cwd):
        tools = self.tool_list(seat)
        prompt = prompt + guard_text(seat)
        args = ["claude", "-p", "--input-format", "stream-json", "--output-format",
                "stream-json", "--verbose", "--effort", seat["effort"], "--tools", tools,
                "--allowedTools", tools, "--disable-slash-commands"]
        if seat.get("compaction", "forbid") == "forbid":
            args += ["--autocompact", str(seat.get("context_window") or MAX_WINDOW)]
        args += settings_flag(seat)
        if granted(seat, "settings"):
            pass  # every setting source loads, the operator's CLAUDE.md included
        elif granted(seat, "instructions"):
            args += ["--setting-sources", "project"]
        else:
            args += NO_SETTING_SOURCES
        if not granted(seat, "mcp"):
            args += NO_MCP
        args += list(seat.get("args") or [])
        # Every launch names the model: a resume without it runs the CLI's
        # default, and a resume with the family alone runs the newest one.
        model = seat.get("model_pinned") or seat["model"]
        if mode == "start":
            args += ["--model", model, "--session-id", session_id]
        else:
            args += ["--resume", session_id, "--model", model]
            if mode == "fork":
                args += ["--fork-session"]
        payload = json.dumps({"type": "user", "message": {
            "role": "user", "content": [{"type": "text", "text": prompt}]}}) + "\n"
        return args, payload.encode("utf-8")

    def session_paths(self, home, session_id):
        found = sorted((Path(home) / "projects").rglob(f"{session_id}.jsonl"))
        return [p for p in found if "subagents" not in p.parts]

    def classify_stop(self, record):
        return quota.classify("claude", record)

    def served_model(self, record):
        stream = rows(Path(record) / "events.jsonl")
        models = {r["message"]["model"] for r in stream
                  if r.get("type") == "assistant"
                  and r.get("message", {}).get("model") not in (None, "<synthetic>")}
        return models.pop() if len(models) == 1 else None

    def receipt(self, seat, record, home, expected_session=None):
        stream = rows(Path(record) / "events.jsonl")
        results = [r for r in stream if r.get("type") == "result"]
        if len(results) != 1 or results[0].get("is_error") or results[0].get("subtype") != "success":
            said = str(results[0].get("result", "")) if results else "no result row"
            raise RuntimeError("Claude did not complete: " + said[:250])
        result = results[0]
        sid = result["session_id"]
        if expected_session and sid != expected_session:
            raise RuntimeError(f"resume landed in session {sid}, not {expected_session}")
        answer = result.get("result", "") or ""
        models = {r["message"]["model"] for r in stream
                  if r.get("type") == "assistant"
                  and r.get("message", {}).get("model") not in (None, "<synthetic>")}
        if len(models) != 1:
            raise RuntimeError(f"missing or mixed Claude model identity: {sorted(models)}")
        model = models.pop()
        expected = seat.get("model_pinned") or seat["model"]
        if not model_matches(expected, model):
            raise RuntimeError(f"Claude served {model}, requested {expected}")
        usage = result.get("modelUsage", {}) or {}
        if not usage.get(model, {}).get("outputTokens"):
            raise RuntimeError("Claude lacks served-model usage evidence")
        calls = []
        for row in stream:
            if row.get("type") == "assistant":
                calls += [b for b in row.get("message", {}).get("content", [])
                          if b.get("type") in ("tool_use", "server_tool_use")]
        init = [r for r in stream if r.get("type") == "system" and r.get("subtype") == "init"]
        if len(init) != 1:
            raise RuntimeError("Claude init row missing or duplicated")
        if init[0].get("mcp_servers") and not granted(seat, "mcp"):
            raise RuntimeError("Claude MCP configuration drift: servers reached the seat")
        if init[0].get("output_style") not in (None, "default"):
            raise RuntimeError(f"Claude output style drift: {init[0].get('output_style')}")
        paths = self.session_paths(home, sid)
        if len(paths) != 1:
            raise RuntimeError(f"expected one native Claude session for {sid}, found {len(paths)}")
        self._check_calls(seat, calls)
        if not answer.strip():
            raise RuntimeError("empty completed answer")
        return {
            "session_id": sid, "model": model, "requested_model": seat["model"],
            "model_evidence": "assistant message model plus modelUsage output tokens",
            "effort": seat["effort"], "effort_evidence": "CLI selection",
            "usage": usage, "tool_calls": len(calls),
            "tools_used": sorted({c.get("name", "") for c in calls}),
            "native_transcripts": [str(p) for p in paths], "answer": answer,
        }

    def _check_calls(self, seat, calls):
        if seat["tools"] == "none" and calls:
            raise RuntimeError("tool use violates the declared no-tools policy")
        for call in calls:
            tool = call.get("name") or call.get("type", "")
            if re.search(r"^mcp__", tool) and not granted(seat, "mcp"):
                raise RuntimeError(f"connected-service tool reached the seat: {tool}")
            if re.search(r"subagent|^Task$|^Agent$", tool, re.I):
                raise RuntimeError(f"delegation tool reached the seat: {tool}")
            if not may_search(seat) and re.search(r"WebSearch|WebFetch", tool):
                raise RuntimeError(f"network tool use violates the declared policy: {tool}")
            command = str((call.get("input") or {}).get("command", ""))
            if not may_search(seat) and re.search(r"https?://|\b(curl|wget)\b", command):
                raise RuntimeError("network use in a shell command violates the declared policy")

    def usage_totals(self, usage):
        if not isinstance(usage, dict) or not usage:
            return None
        served = [v for v in usage.values() if isinstance(v, dict)]
        if not served:
            return None
        return {
            "input": sum(v.get("inputTokens") or 0 for v in served),
            "output": sum(v.get("outputTokens") or 0 for v in served),
            "reasoning": sum(v.get("thinkingTokens") or 0 for v in served),
            "cache_read": sum(v.get("cacheReadInputTokens") or 0 for v in served),
            "cost_usd": round(sum(v.get("costUSD") or 0.0 for v in served), 4),
            "cache_inside_input": False,
        }

    @property
    def probes(self):
        from convene.doctor import Probe
        return (
            Probe("--setting-sources", ("-p", "x", "--setting-sources", "bogus"),
                  needles=("Invalid setting source",),
                  why="the only thing keeping the global CLAUDE.md out of a seat"),
            Probe("--settings", ("-p", "x", "--settings", "NOTJSONNOTAPATH"),
                  needles=("Settings file not found",),
                  why="pins the output style; an Explanatory style swaps a seat's register"),
            Probe("--tools", ("--help",), expect="ok", needles=("--tools",),
                  why="the tool allow-list; its value is not validated, only its existence"),
        )
