"""Codex CLI as a seat."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from convene import quota
from convene.harnesses import (Capabilities, Harness, families, granted, guard_text,
                               is_family, may_search, newest_in_family)
from convene.storage import read, rows

FALLBACK = "Falling back from WebSockets to HTTPS transport."
# The account's connected apps (mail, calendar, documents, code hosting, with
# tools that send, delete, commit and merge) reach a seat as the built-in
# `codex_apps` MCP server. They come with the login, not from a file, so
# neither a private home nor --ignore-user-config removes them; only this
# switch does. The `mcp` grant keeps them, as it keeps Claude's.
NO_APPS = ["-c", "features.apps=false"]
# The account's plugins arrive the same way: with the login on, Codex
# installs every remote plugin the account enables (mail, calendar, drive,
# code hosting) into the seat's private home, some tens of megabytes per
# seat, on every launch into a fresh home. None reach a seat that runs
# without apps, but they are its capabilities all the same, so they close
# and open with the apps, under `mcp`.
NO_PLUGINS = ["-c", "features.plugins=false", "-c", "features.remote_plugin=false"]
# Codex's catalog puts most models (the `terra` default among them) on its
# second multi-agent version, which ignores features.multi_agent=false and
# offers every seat, a tool-free one included, `spawn_agent` with overrides
# naming other models. No setting removes the tool. A session limit of one
# thread, the seat itself, makes every spawn fail; Codex refuses a limit of
# zero. A sub-agent's turns live in a session the receipt never reads, so
# without this a seat could hand its work to a model the receipt never names.
NO_SUBAGENTS = ["-c", "features.multi_agent_v2.max_concurrent_threads_per_session=1"]
# A tool on every seat with a shell, spending the account's image quota; no
# seat is asked for an image.
NO_IMAGES = ["-c", "features.image_generation=false"]
# Every tool feature a tool-free seat names off rather than leaving to its
# default. Codex 0.156 moved the image viewer from `tools.view_image` to a
# feature and ignores the old key with a warning, which the receipt reads as
# a failed turn. `features list` shows unified_exec on whatever this says,
# but its tools leave with shell_tool.
TOOL_FEATURES = ("shell_tool", "unified_exec", "view_image", "browser_use",
                 "browser_use_external", "in_app_browser", "computer_use")
NO_TOOLS = [arg for feature in TOOL_FEATURES for arg in ("-c", f"features.{feature}=false")]
# How long the app server may take to list a seat's MCP servers. The
# account's apps are fetched over the network when they are on.
INVENTORY_SECONDS = 120
# The flags of a seat's command that `codex app-server` takes too.
SETTINGS = ("-c", "--config", "--enable", "--disable")


def settings(argv):
    """The settings a seat's command makes, as `codex app-server` takes them.

    Only settings travel. The app server refuses the rest of an exec command
    (its subcommand, -m, -s, --ignore-user-config), and none of it decides
    which servers load.
    """
    argv, out = [str(a) for a in argv], []
    for index, arg in enumerate(argv):
        if index and argv[index - 1] in SETTINGS:
            continue  # the value of the flag before it, already taken
        if arg in SETTINGS and index + 1 < len(argv):
            out += [arg, argv[index + 1]]
        elif arg.startswith(("--config=", "--enable=", "--disable=")) or (
                arg.startswith("-c") and len(arg) > 2):
            out.append(arg)
    return out


def without_user_config(home, view):
    """Fill `view` with links to every entry of `home` except its config.toml.

    `--ignore-user-config` skips exactly `$CODEX_HOME/config.toml`, and the
    app server has no such flag. Pointed at this view it sees what the seat
    sees: the same login, plugin cache and state, and no config to enable a
    plugin or declare a server from.
    """
    for entry in Path(home).iterdir():
        if entry.name != "config.toml":
            (Path(view) / entry.name).symlink_to(entry)


def mcp_inventory(argv, *, env, cwd, pass_fds=(), timeout=INVENTORY_SECONDS):
    """The MCP servers `codex app-server` lists, as ``({name: tool count}, "")``.

    ``(None, why)`` when the inventory could not be read. The protocol is
    marked experimental, so a release that changes it leaves the inventory
    unreadable rather than empty. Every page is read, so a long list is never
    taken for its first page.
    """
    with tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=err, env=env, cwd=cwd, pass_fds=pass_fds)
        except OSError as exc:
            return None, f"codex app-server did not start ({exc})"
        expired = []
        timer = threading.Timer(timeout, lambda: (expired.append(True), proc.kill()))
        timer.start()
        servers = {}
        try:
            why = _list_servers(proc, servers)
        except OSError as exc:
            why = f"codex app-server stopped answering ({exc})"
        finally:
            timer.cancel()
            proc.kill()
            proc.wait()
        if why and expired:
            why += f" within {timeout}s"
        if why:
            err.seek(0)
            tail = err.read().decode("utf-8", "replace").strip()[-200:]
            return None, why + (f": {tail}" if tail else "")
        return servers, ""


def _list_servers(proc, servers):
    """Speak the app server's JSON-RPC over stdio; return why it failed, or ""."""
    def ask(number, method, params=None):
        message = {"method": method}
        if number is not None:
            message |= {"id": number, "params": params or {}}
        proc.stdin.write((json.dumps(message) + "\n").encode())
        proc.stdin.flush()
        if number is None:
            return None
        for line in proc.stdout:
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if isinstance(reply, dict) and reply.get("id") == number:
                return reply
        return None

    hello = {"clientInfo": {"name": "convene", "version": "1"}}
    if (ask(1, "initialize", hello) or {}).get("result") is None:
        return "codex app-server did not initialize"
    ask(None, "initialized")
    cursor = None
    # The bound guards against a server that never stops paging; no real
    # inventory comes near it.
    for number in range(2, 50):
        reply = ask(number, "mcpServerStatus/list",
                    {"detail": "toolsAndAuthOnly", "cursor": cursor}) or {}
        page = reply.get("result")
        if not isinstance(page, dict):
            return "codex app-server listed no MCP inventory: " + (
                json.dumps(reply["error"])[:200] if reply.get("error") else "no reply")
        for server in page.get("data") or []:
            servers[server.get("name", "?")] = len(server.get("tools") or {})
        cursor = page.get("nextCursor")
        if not cursor:
            return ""
    return "codex app-server's MCP inventory did not end"


class Codex(Harness):
    name = "codex"
    home_name = ".codex"
    # What a seat gets when the plan names no model: a family, never a version.
    default_model = "terra"
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
        # A seat's args come after the engine's flags and the last value of a
        # key wins, so every switch the engine closes is reserved here too.
        "features": (None, "name one feature, `features.NAME=...`"),
        "features.apps": ("mcp", "grant mcp on the seat; it keeps the account's apps"),
        "features.plugins": ("mcp", "grant mcp on the seat; it keeps the account's plugins"),
        "features.remote_plugin": ("mcp", "grant mcp on the seat; it keeps the account's plugins"),
        "features.multi_agent": (None, "every Codex seat is kept to its own thread"),
        "features.multi_agent_v2": (None, "every Codex seat is kept to its own thread"),
        "features.multi_agent_v2.": (None, "every Codex seat is kept to its own thread"),
        "features.image_generation": (None, "no seat is asked for an image"),
        **{f"features.{feature}": (None, "set tools on the seat") for feature in TOOL_FEATURES},
    }

    def check_args(self, seat):
        # Check each setting as the key it sets: `-c key=value` carries it in
        # the next token, `-ckey=value` and `--config=key=value` in the same
        # one, and `--enable NAME` is `-c features.NAME=true`.
        args = list(seat.get("args") or [])
        flat = []
        for index, arg in enumerate(args):
            following = args[index + 1] if index + 1 < len(args) else ""
            if arg in ("-c", "--config"):
                flat.append(following)
            elif arg in ("--enable", "--disable"):
                flat.append(f"features.{following}")
            elif arg.startswith(("--enable=", "--disable=")):
                flat.append("features." + arg.split("=", 1)[1])
            elif arg.startswith("--config="):
                flat.append(arg.split("=", 1)[1])
            elif arg.startswith("-c") and len(arg) > 2:
                flat.append(arg[2:])
            else:
                flat.append(arg)
        super().check_args({**seat, "args": flat})

    def catalog(self, environ=None):
        path = self.real_home(environ) / "models_cache.json"
        return path, (read(path).get("models", []) if path.exists() else None)

    def resolve(self, model, effort, environ=None):
        model = re.sub(r"^(gpt-\d+)-(\d+)", r"\1.\2", str(model).strip().lower())
        path, models = self.catalog(environ)
        out = {"model": model, "effort": effort, "context_window": None,
               "model_evidence": "native turn context"}
        if models is None:
            if is_family(model):
                raise ValueError(f"codex model {model!r} is a family, and resolving it needs "
                                 f"the Codex catalog at {path}; start codex once to write it, "
                                 "or name an exact slug")
            if effort not in self.efforts:
                raise ValueError(f"codex effort must be one of {', '.join(self.efforts)}: {effort!r}")
            out["catalog"] = f"absent: {path}; start codex once to refresh it"
            return out
        item = next((m for m in models if m.get("slug") == model), None)
        # Hidden entries are Codex's own internals; a family never lands on one.
        listed = [m["slug"] for m in models if m.get("slug") and m.get("visibility") != "hide"]
        if item is None and is_family(model):
            slug = newest_in_family(model, listed)
            item = next((m for m in models if m.get("slug") == slug), None)
        if item is None:
            raise ValueError(f"Codex catalog {path} does not list {model!r}; it offers the "
                             f"families {', '.join(families(listed))}, which resolve to their "
                             "newest version, or an exact slug")
        model = out["model"] = item["slug"]
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
        # multi_agent=false still removes the tools from a model on the first
        # multi-agent version; NO_SUBAGENTS covers the second.
        args += ["-c", "features.multi_agent=false", *NO_SUBAGENTS, *NO_IMAGES,
                 "-c", 'web_search="live"' if may_search(seat) else 'web_search="disabled"']
        if not granted(seat, "mcp"):
            args += NO_APPS + NO_PLUGINS
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

    def preflight(self, seat, argv, launched, home):
        """The MCP servers the seat would hold, by Codex's own count.

        Codex has no start-up event naming what it loaded, as Claude's init
        row does, and its session records no inventory. Its app server does.
        Started inside the seat's own wrapper, with the seat's settings and
        home, it lists every server the seat would hold, before any model is
        called and without the model's word. Without the `mcp` grant, any
        server refuses the launch, and so does an inventory that cannot be
        read, because then nothing shows the seat holds none. With the grant
        the inventory is recorded, and what it lists is a red flag.

        The app server cannot ignore the user config the way the seat does,
        and a config enables plugins that bring servers of their own. Where
        the seat ignores it and its home has one, which only the `none`
        tier's does, the operator's own, the app server reads a view of that
        home without it. A jailed home is a private one with no config; if
        one ever had a config, its servers would be counted, refusing the
        seat rather than admitting it.
        """
        wrapper = launched.argv[: len(launched.argv) - len(argv)]
        command = [*wrapper, "codex", "app-server", *settings(argv)]
        with tempfile.TemporaryDirectory(prefix="convene-codex-home.") as view:
            env = dict(launched.env)
            if ("--ignore-user-config" in argv and not wrapper
                    and (Path(home) / "config.toml").exists()):
                without_user_config(home, view)
                env[self.home_variable] = view
            servers, why = mcp_inventory(command, env=env, cwd=launched.cwd,
                                         pass_fds=launched.pass_fds)
        out = {"mcp_servers": servers}
        held = ", ".join(f"{name} ({count} tools)" for name, count in sorted((servers or {}).items()))
        if granted(seat, "mcp"):
            out["red_flags"] = ([f"MCP inventory unread: {why}"] if servers is None
                                else [f"MCP servers held: {held}"] if servers else [])
            return out
        if servers is None:
            raise RuntimeError(
                f"Codex's MCP inventory could not be read ({why}), so nothing shows this seat "
                "holds no MCP servers; it was refused before its turn and no model was called. "
                "`codex app-server` is experimental: if a release changed "
                "mcpServerStatus/list, update the reader in convene's harnesses/codex.py")
        if servers:
            raise RuntimeError(
                f"Codex's app server lists MCP servers this seat would hold without the mcp "
                f"grant: {held}. It was refused before its turn and no model was called. A "
                "Codex release may have moved the switch that closes them (features.apps for "
                "the account's apps); run `convene doctor`, and grant mcp only if the seat "
                "is meant to hold them")
        return out

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
            _features_off("features.apps", ("apps",),
                          "keeps the account's connected apps out of a seat; they come with "
                          "the login, so no home or config file removes them"),
            _features_off("features.plugins", ("plugins", "remote_plugin"),
                          "keeps the account's plugins out of a seat, and with them a download "
                          "of tens of megabytes into every private home"),
            _features_off("features.image_generation", ("image_generation",),
                          "no seat is asked for an image, and each one spends the account's quota"),
            Probe("multi_agent_v2 thread limit",
                  ("exec", "--ignore-user-config", "-c",
                   "features.multi_agent_v2.max_concurrent_threads_per_session=0", "x"),
                  needles=("at least 1",),
                  why="the only bound on spawn_agent, which multi-agent v2 offers every seat"),
            _features_off("tool-free features",
                          tuple(f for f in TOOL_FEATURES if f != "unified_exec"),
                          "what takes a tool-free seat's tools away"),
        )


def _features_off(label, features, why):
    """A probe that each feature still exists and reads off when set off.

    An invalid value proves nothing here: codex type-checks a feature's value
    whether or not the feature exists, so a dead name errors like a live one.
    `features list` shows the setting applied, and a renamed feature drops
    out of it.
    """
    from convene.doctor import Probe
    args = tuple(a for f in features for a in ("-c", f"features.{f}=false"))
    return Probe(label, (*args, "features", "list"), expect="ok",
                 patterns=tuple(rf"^{f}\s.*\sfalse\s*$" for f in features), why=why)
