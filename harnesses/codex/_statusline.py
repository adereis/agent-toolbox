"""Read telemetry from a locally owned Codex process; never discover by recency."""

from datetime import datetime, timezone
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from _text import safe_text


MAX_RECORD = 16 * 1024 * 1024
PRICES = Path(__file__).with_name("statusline-prices.json")


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def load_prices(path=PRICES):
    data = json.loads(Path(path).read_text())
    for model, rates in data["models"].items():
        for key in ("input", "cached_input", "cache_write", "output", "long_context_after"):
            value = rates[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid {key} price for {model}")
    return data["models"]


def estimate(usage, model, tier, prices):
    """Price a response, counting cached reads/writes within input exactly once."""
    if model not in prices:
        raise ValueError(f"no published rates bundled for {model or 'unknown model'}")
    multipliers = {"default": 1, "standard": 1, "priority": 2, "fast": 2, "flex": 0.5}
    if tier not in multipliers:
        raise ValueError(f"unknown service tier {tier}")
    values = [usage.get(k, 0) for k in (
        "input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")]
    if any(type(v) is not int or v < 0 for v in values):
        raise ValueError("invalid token counts")
    inputs, cached, writes, outputs = values
    if cached + writes > inputs:
        raise ValueError("cached reads and writes exceed input tokens")
    rates = prices[model]
    long = inputs > rates["long_context_after"]
    input_cost = sum(Decimal(n) * Decimal(str(rates[k])) for n, k in (
        (inputs - cached - writes, "input"), (cached, "cached_input"), (writes, "cache_write")))
    output_cost = outputs * Decimal(str(rates["output"]))
    return ((input_cost * (2 if long else 1) + output_cost * (Decimal("1.5") if long else 1))
            * Decimal(str(multipliers[tier])) / 1_000_000)


def process_tree(pid, proc=Path("/proc")):
    """Include children of every thread, including a native child of an npm shim."""
    found, pending = set(), [pid]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        if len(found) > 1024:
            raise ValueError("process tree is too large to inspect")
        try:
            tasks = list((proc / str(current) / "task").iterdir())
            for task in tasks:
                try:
                    pending.extend(int(n) for n in (task / "children").read_text().split())
                except FileNotFoundError:
                    pass  # A child may exit between listing its threads and reading them.
        except FileNotFoundError:
            pass  # Process exit is expected during discovery.
    return found


def open_rollouts(pid, codex_home, proc=Path("/proc")):
    """Return main CLI rollouts held open by this process tree, excluding agents."""
    sessions = (Path(codex_home) / "sessions").resolve()
    candidates = {}
    for owner in process_tree(pid, proc):
        try:
            descriptors = list((proc / str(owner) / "fd").iterdir())
        except FileNotFoundError:
            continue
        for descriptor in descriptors:
            try:
                path = descriptor.readlink()
                if not path.name.startswith("rollout-") or path.suffix != ".jsonl":
                    continue
                path = path.resolve()
                if not path.is_relative_to(sessions) or path in candidates:
                    continue
                with path.open("rb") as stream:
                    line = stream.readline(MAX_RECORD + 1)
                if not line.endswith(b"\n"):
                    if len(line) > MAX_RECORD:
                        raise ValueError("rollout metadata exceeds 16 MiB")
                    continue  # The writer has not finished the first line yet.
                record = json.loads(line)
                meta = record.get("payload", {})
                if (record.get("type") == "session_meta" and meta.get("source") == "cli"
                        and not meta.get("parent_thread_id") and meta.get("id")):
                    candidates[path] = (owner, meta["id"])
            except FileNotFoundError:
                continue  # The process closed the descriptor during the scan.
    return candidates


def other_writers(path, owned, proc=Path("/proc")):
    """A shared history file cannot attribute two embedded writers to processes."""
    writers = []
    for process in proc.iterdir():
        if not process.name.isdecimal() or int(process.name) in owned:
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            for descriptor in (process / "fd").iterdir():
                try:
                    if descriptor.readlink() != path:
                        continue
                    fields = (process / "fdinfo" / descriptor.name).read_text().splitlines()
                    flags = next(int(line.split()[1], 8) for line in fields if line.startswith("flags:"))
                    if flags & os.O_ACCMODE:
                        writers.append(int(process.name))
                        break
                except FileNotFoundError:
                    pass  # A descriptor can close during the check.
        except FileNotFoundError:
            pass  # A process can exit during the check.
        except PermissionError:
            # Linux protects non-dumpable processes (e.g. credential agents).
            # They are outside the accessible local process set.
            continue
    return writers


class Rollout:
    """Incrementally tail one file without retaining prompts or tool results."""

    def __init__(self, path, thread_id, started, backend, tier, prices):
        self.path, self.thread_id = Path(path), thread_id
        self.started, self.backend, self.tier, self.prices = started, backend, tier, prices
        self.launch_backend = backend
        self.offset = 0
        self.identity = None
        self.model = self.effort = self.cwd = None
        self.context = self.window = None
        self.limits = None
        self.limit_time = None
        self.cost = Decimal(0)
        self.cost_error = None
        self.responses = set()
        self.usage_seen = False
        self.totals_seen = False
        self.catching_up = False

    def poll(self):
        with self.path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            identity = info.st_dev, info.st_ino
            if self.identity is not None and (identity != self.identity or info.st_size < self.offset):
                raise ValueError("active rollout was replaced or truncated; restart the wrapper")
            self.identity = identity
            stream.seek(self.offset)
            # Bound work per refresh, even when resuming a very large transcript.
            for _ in range(2000):
                line = stream.readline(MAX_RECORD + 1)
                if len(line) > MAX_RECORD:
                    raise ValueError("rollout record exceeds 16 MiB")
                if not line or not line.endswith(b"\n"):
                    break  # Retry an unfinished append without advancing the cursor.
                self.consume(json.loads(line))
                self.offset = stream.tell()
            self.catching_up = self.offset < info.st_size and stream.tell() < info.st_size

    def consume(self, record):
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            return
        kind, event = record.get("type"), payload.get("type")
        if kind not in ("turn_context", "token_usage_record", "event_msg"):
            return
        if kind == "event_msg" and event not in ("token_count", "thread_settings_applied"):
            return
        if timestamp(record["timestamp"]) < self.started:
            return  # Old billing, models, and account quotas do not describe this launch.
        if kind == "turn_context":
            self.model, self.effort, self.cwd = payload.get("model"), payload.get("effort"), payload.get("cwd")
        elif event == "thread_settings_applied":
            if payload.get("thread_id", self.thread_id) != self.thread_id:
                return
            settings = payload["thread_settings"]
            self.model, self.effort, self.cwd = settings.get("model"), settings.get("reasoning_effort"), settings.get("cwd")
            self.tier = settings.get("service_tier") or "default"
            provider = settings.get("model_provider_id")
            expected = "openai_api" if self.launch_backend == "api" else "openai"
            # A different provider has not passed this launcher's authentication
            # preflight. Its name alone cannot prove subscription authentication.
            backend = self.launch_backend if provider == expected else provider
            if backend != self.backend:
                self.limits = None
            self.backend = backend or "unknown"
        elif kind == "token_usage_record":
            if payload.get("thread_id") != self.thread_id:
                return
            response_id = payload.get("response_id")
            if not response_id:
                raise ValueError("token usage has no response identifier")
            if response_id in self.responses:
                return
            self.responses.add(response_id)
            self.usage_seen = True
            try:
                self.cost += estimate(payload["usage"], self.model, self.tier, self.prices)
            except ValueError as error:
                self.cost_error = str(error)  # Never display a partial sum as the total.
        elif event == "token_count":
            info = payload.get("info")
            if info:
                self.window = info.get("model_context_window")
                used = info.get("last_token_usage", {}).get("total_tokens")
                if self.window and used is not None:
                    self.context = min(100, max(0, used / self.window * 100))
                # Older histories only have totals; they cannot price mixed models/tiers reliably.
                self.totals_seen |= bool(info.get("total_token_usage", {}).get("total_tokens", 0))
            if payload.get("rate_limits") is not None and self.backend == "subscription":
                self.limits = payload["rate_limits"]
                self.limit_time = timestamp(record["timestamp"])

    def snapshot(self):
        error = self.cost_error or ("per-response usage unavailable" if self.totals_seen and not self.usage_seen else None)
        return {"model": self.model, "effort": self.effort, "cwd": self.cwd,
                "context": self.context, "window": self.window, "backend": self.backend,
                "tier": self.tier, "cost": None if error or self.catching_up else str(self.cost),
                "cost_error": error, "limits": self.limits, "limit_time": self.limit_time,
                "notice": "reading session history" if self.catching_up else None}


def git_state(cwd):
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(cwd), "status", "--porcelain=v1", "-b", "-z"],
        capture_output=True, timeout=2)
    if result.returncode:
        if b"not a git repository" in result.stderr:
            return None
        raise ValueError("git status failed: " + safe_text(result.stderr.decode(errors="replace")))
    records = result.stdout.decode(errors="replace").split("\0")
    branch = records[0].removeprefix("## ").split("...")[0]
    for prefix in ("No commits yet on ", "Initial commit on "):
        branch = branch.removeprefix(prefix)
    if branch.startswith("HEAD "):
        head = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=2, check=True)
        branch = head.stdout.strip()
    dirty = staged = untracked = False
    items = iter(records[1:])
    for record in items:
        if not record:
            continue
        status = record[:2]
        if status == "??":
            untracked = True
        else:
            staged |= status[0] != " "
            dirty |= status[1] != " "
            if "R" in status or "C" in status:
                next(items, None)  # Porcelain -z puts a rename's other path in the next record.
    return branch + ("*" if dirty else "") + ("+" if staged else "") + ("?" if untracked else "")


def memory_mb(pid, proc=Path("/proc")):
    for line in (proc / str(pid) / "status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    raise ValueError("process RSS is unavailable")


def width(text):
    return sum(0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in text)


def shorten(text, limit):
    if width(text) <= limit:
        return text
    result = ""
    for ch in text:
        if width(result + ch) > limit - 1:
            break
        result += ch
    return result + "…" if limit else ""


def tier_color(value):
    return "red" if value >= 80 else "yellow" if value >= 50 else "green"


def render(data, columns=160, now=None, styled=True):
    """Two aligned rows; escape both terminal controls and tmux format syntax."""
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    cells = []

    def add(header, value, color="cyan", priority=5, cap=24):
        if value is None:
            return
        header, value = safe_text(header), safe_text(value)
        value = shorten(value, cap)
        cells.append((header, value, color, priority))

    cwd = str(data.get("cwd") or "")
    home = str(Path.home())
    if cwd == home or cwd.startswith(home + "/"):
        cwd = "~" + cwd[len(home):]
    add("workspace", cwd, "blue,bold", 1, 28)
    add("branch", data.get("branch"), "yellow", 2, 18)
    model = data.get("model") or "waiting"
    if data.get("window") and data["window"] < 1_000_000:
        model += f" [{data['window'] // 1000}k]"
    add("model", model, "green", 8, 28)
    effort = data.get("effort")
    add("effort", effort, "magenta,dim" if effort == "low" else "magenta,bold" if effort == "max" else "magenta", 3)
    context = data.get("context")
    add("session", "--" if context is None else f"{context:.0f}%", "default" if context is None else tier_color(context), 9)
    add("cost~", "n/a" if data.get("cost") is None else f"${Decimal(data['cost']):.2f}", "cyan", 7)
    limits = data.get("limits") or {}
    if data.get("backend") == "subscription":
        for name in ("primary", "secondary"):
            window = limits.get(name)
            if not window or window.get("used_percent") is None:
                continue
            minutes = window.get("window_minutes")
            header = "week" if minutes == 10080 else "quota" if minutes == 300 else f"{minutes}m" if minutes else name
            if minutes == 300 and window.get("resets_at"):
                header = "↻" + datetime.fromtimestamp(window["resets_at"]).strftime("%H:%M")
            percent = window["used_percent"]
            age = max(0, now - (data.get("limit_time") or now))
            stale = age >= 900 or (window.get("resets_at") is not None and now >= window["resets_at"])
            suffix = f" ·{int(age // 60)}m" if stale else ""
            add(header, f"{percent:.0f}%{suffix}", "default,dim" if stale else tier_color(percent), 4)
    backend = data.get("backend") or "unknown"
    if backend == "subscription" and limits.get("plan_type"):
        backend = str(limits["plan_type"])
    add("profile", backend, "cyan" if backend != "api" else "default,dim", 100)
    if data.get("memory") is not None:
        add("memory", f"{data['memory']:.1f} MB", "cyan", 0)
    if data.get("error") or data.get("cost_error"):
        add("status", data.get("error") or data["cost_error"], "red", 99, 52)
    elif data.get("notice"):
        add("status", data["notice"], "default,dim", 6, 30)
    columns = max(1, min(columns, 4096))
    padding = min(2, (columns - 1) // 2)
    columns -= 2 * padding
    while len(cells) > 1 and sum(max(width(c[0]), width(c[1])) for c in cells) + 3 * (len(cells) - 1) > columns:
        cells.pop(min(range(len(cells)), key=lambda i: cells[i][3]))
    rows = [[], []]
    for header, value, color, _ in cells:
        size = min(columns, max(width(header), width(value)))
        for row, text, style in ((0, header, "default,dim"), (1, value, color)):
            text = shorten(text, size)
            text += " " * (size - width(text))
            # No external text can create #{...}, #(commands), or #[styles].
            # tmux requires fg= before a colour name; a bare name invalidates
            # the whole style, including its bold/dim attributes.
            rows[row].append(f"#[fg={style}]" + text.replace("#", "##") + "#[default]" if styled else text)
    margin = " " * padding
    return tuple(margin + "   ".join(row) + margin for row in rows)
