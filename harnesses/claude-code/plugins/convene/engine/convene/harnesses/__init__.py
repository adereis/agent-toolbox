"""One protocol for every native CLI a seat can run on.

Quirework grew four argv builders for the same three CLIs and they drifted.
Here a harness is one object: it builds the command, says where its private
state lives, finds its own session files, and reads its own receipt. Policy
that is the same for every harness (tool sets, the environment allow-list,
prompt guard lines) lives in this module so it has exactly one definition.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

TOOL_SETS = ("none", "read", "write", "research")
MODES = ("start", "resume", "fork")

# Doors a seat may open on purpose. Closed by default; each grant is
# frozen into the plan, applied by the harness, accepted by the receipt
# checks, and reported as a red flag so the operator sees an opened door.
GRANTS = {
    "web": "web search and fetch tools (Claude: WebSearch, WebFetch; Codex: web_search=live)",
    "mcp": "MCP servers (Claude: the account's and any --mcp-config in the seat's args; "
           "Codex: the account's connected apps and the user config's mcp_servers, which "
           "implies `settings`)",
    "settings": "the operator's own harness settings (Claude: every setting source, so the "
                "global CLAUDE.md loads; Codex: config.toml)",
    "instructions": "project instruction files (Claude: project setting sources; Codex: "
                    "AGENTS.md and execpolicy rules)",
    "hooks": "lifecycle hooks (Claude only; Codex has none)",
}

# What reaches a seat from the operator's environment, and nothing else.
# Credentials are added per harness, per tier, never inherited wholesale.
ENV_ALLOW = ("PATH", "LANG", "LC_ALL", "TERM", "TZ", "HTTPS_PROXY", "HTTP_PROXY",
             "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR")

_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class Capabilities:
    resume: bool
    fork: bool
    json_schema: bool
    system_prompt: bool
    window_pinned: bool  # whether compaction can be prevented, not only detected


def base_environment(environ=None, extra=()):
    """The allow-list, plus the names a plan passes through on purpose."""
    environ = os.environ if environ is None else environ
    env = {k: environ[k] for k in (*ENV_ALLOW, *extra) if k in environ}
    env.update(USER=environ.get("USER", ""), DISABLE_AUTOUPDATER="1")
    return env


def granted(seat, name):
    return name in (seat.get("grants") or ())


def may_search(seat):
    return seat.get("tools") == "research" or granted(seat, "web")


def guard_lines(tools):
    """Prompt lines that restate the tool policy the flags already enforce.

    Flags stop a tool from existing; these stop the model from asking for
    one and reading the refusal as a hint about its situation.
    """
    text = ""
    if tools != "research":
        text += "\nUse no web or external services. Work only with the supplied material.\n"
    if tools == "none":
        text += "\nUse no tools. Return your answer directly.\n"
    return text


def guard_text(seat):
    """The guard lines for a seat, minus the ones its grants contradict."""
    text = guard_lines(seat["tools"])
    if granted(seat, "web") or granted(seat, "mcp"):
        text = text.replace(
            "\nUse no web or external services. Work only with the supplied material.\n", "")
    return text


# A plan names a model family (`opus`, `terra`, `gemini-pro`) and the engine
# picks the newest member from the harness's own catalog at prepare time, so
# a release needs no code change here. The resolved id is frozen in the plan
# and the receipt; a version number in the name pins it instead.

def _tokens(name):
    return [t for t in re.split(r"[-_\s]+", str(name).strip().lower()) if t]


def _words(name):
    """The family words of a model name: every token that is not a version."""
    return [t for t in _tokens(name) if not t[0].isdigit()]


def _version(name):
    return tuple(int(n) for t in _tokens(name) if t[0].isdigit()
                 for n in re.findall(r"\d+", t))


def is_family(name):
    """Whether a model name names a family rather than a version: no digit."""
    return bool(_tokens(name)) and not re.search(r"\d", str(name))


def families(slugs):
    """The family names a catalog offers, for a refusal to list."""
    return sorted({"-".join(_words(s)) for s in slugs if _words(s)})


def newest_in_family(family, slugs):
    """The newest catalog slug in `family`, or None when nothing matches.

    A slug is in the family when every family word is one of its words.
    Among those, the members with the fewest words win, so `terra` means
    `gpt-5.6-terra` and not a later `gpt-6-terra-mini`. Two different word
    sets left tied are ambiguous, as `gemini` is between Flash and Pro, and
    the refusal names both. Inside the family the highest version wins.
    """
    wanted = set(_words(family))
    members = [s for s in slugs if wanted <= set(_words(s))]
    if not members:
        return None
    fewest = min(len(_words(s)) for s in members)
    members = [s for s in members if len(_words(s)) == fewest]
    shapes = families(members)
    if len(shapes) > 1:
        raise ValueError(f"model {family!r} names more than one family "
                         f"({', '.join(shapes)}); name one of them")
    return max(members, key=lambda s: (_version(s), s))


def model_text(seat):
    """A seat's model as status prints it: the id, and the family it came from."""
    asked = seat.get("model_requested")
    return f"{seat['model']} (from {asked})" if asked else seat["model"]


def model_matches(expected, actual):
    """Whether the served model id satisfies the requested one."""
    if not actual:
        return False
    if is_family(expected):
        return set(_words(expected)) <= set(_words(actual))
    return actual == expected or bool(re.fullmatch(re.escape(expected) + r"-\d{8}", actual))


class Harness:
    """Base class; subclasses fill the methods the engine calls."""

    # The model a seat gets when the plan names none. Every harness sets it,
    # as a family rather than a version so it never goes stale; there is no
    # cross-harness default, because a name means nothing outside the
    # catalog that lists it.
    default_model = None

    # Flags the engine owns, or that open a door a grant names. A seat's raw
    # `args` may not carry them: an engine-owned flag would be passed twice
    # with the last one winning, and a door flag would open the door without
    # the grant that makes it visible in the receipt.
    reserved: dict = {}  # flag -> (grant that unlocks it, or None) and a hint
    tool_sets: tuple = TOOL_SETS  # the tool policies this harness can enforce

    def check_args(self, seat):
        for arg in seat.get("args") or []:
            key = arg.split("=", 1)[0]
            for prefix, (unlock, hint) in self.reserved.items():
                if key == prefix or arg.startswith(prefix + "=") or (
                        prefix.endswith(".") and key.startswith(prefix)):
                    if unlock and granted(seat, unlock):
                        break
                    raise ValueError(f"seat {seat['id']!r}: {arg!r} in args: {hint}")

    name = ""
    capabilities: Capabilities
    home_name = ""       # the directory name of the harness's own state dir
    home_variable = ""   # the environment variable that relocates it
    efforts: tuple = ()
    # Session-bus names the CLI must reach to run at all. The enforced jail
    # never binds the raw bus; it proxies exactly these names in and reports
    # the opened door as a red flag. Empty for a CLI that needs none.
    bus_names: tuple = ()

    def served_model(self, record):
        """The model a turn's own stream names, even if the turn failed.

        None where the stream names none or more than one. The engine uses it
        to pin a session whose first turn was cut off before a receipt could
        be written; a harness whose seats already run a frozen exact id needs
        nothing here, because there is nothing to pin.
        """
        return None

    def preflight(self, seat, argv, launched, home):
        """Receipt fields read before the turn, or a RuntimeError refusing it.

        Runs inside the seat's own wrapper (`launched`), after the tier has
        staged it and before the model is called, so a door the flags failed
        to close is refused without spending the turn. A `red_flags` list in
        the result joins the receipt's. A harness whose own stream proves
        what it loaded, as Claude's init row does, needs nothing here.
        """
        return {}

    def installed(self):
        return shutil.which(self.name)

    def version(self):
        try:
            result = subprocess.run([self.name, "--version"], capture_output=True,
                                    text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        match = _SEMVER.search(result.stdout or result.stderr or "")
        return match.group(0) if match else None

    def real_home(self, environ=None):
        """The operator's own state directory for this harness."""
        environ = os.environ if environ is None else environ
        configured = environ.get(self.home_variable)
        return Path(configured).expanduser() if configured else Path.home() / self.home_name

    def private_env(self, home):
        """Environment that points the harness at a private state directory."""
        return {self.home_variable: str(home)}

    # Subclasses implement:
    #   resolve(model, effort, environ) -> dict with model, effort, evidence
    #   prepare_home(home)              -> None; onboarding state a fresh home needs
    #   credential_files(real_home)     -> [Path]; what an enforced jail binds read-only
    #   credential_env(real_home, environ) -> {name: value} for tiers with no bind
    #   stage_credentials(home, real_home) / unstage_credentials(home)
    #   command(seat, mode, session_id, prompt, cwd) -> (argv, stdin_bytes)
    #   session_paths(home, session_id) -> [Path]
    #   receipt(seat, record, home, expected_session=None) -> dict
    #   preflight(seat, argv, launched, home) -> dict (optional; see above)
    #   usage_totals(usage) -> dict | None
    #   probes -> tuple of doctor.Probe


def registry():
    from convene.harnesses import agy, claude, codex
    return {"claude": claude.Claude(), "codex": codex.Codex(), "agy": agy.Antigravity()}


def get(name):
    harnesses = registry()
    if name not in harnesses:
        raise ValueError(f"unknown harness {name!r}; convene supports {', '.join(harnesses)}")
    return harnesses[name]
