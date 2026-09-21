# Convene

Convene runs several independent AI coding sessions on the same brief and
brings back what each of them wrote, with a receipt for what actually ran.
The seats are native CLIs (`claude -p`, `codex exec`), each with a declared
persona, model, tool set and isolation tier. The foreground Claude Code
session is the operator: it writes the brief, runs the seats, reads the
board and synthesizes.

This version ships the **panel**: a one-round review of a commit range by
independent reviewers who do not see each other. Rooms (seats that discuss
over rounds on a shared board) and fanouts (blind parallel implementations,
sealed before reading) follow the same engine and arrive in later versions.

## Why a panel rather than a subagent

A subagent shares its parent's model, memory and project instructions. A
panel seat is a separate process with its own harness home, its own model,
no MCP servers, no project instruction files, and a receipt that proves it:
the served model is read from the harness's own evidence, the tool calls are
counted, compaction is detected, and the isolation tier is attested. Two
seats on two vendors' models reviewing the same diff independently is a
different instrument from one model asked twice.

## Install

Claude Code discovers plugins through its own registry, so convene is not
installed by `tools/install.py`. From a checkout of this repository:

```bash
claude plugin marketplace add /path/to/agent-toolbox
claude plugin install convene@agent-toolbox
```

For development, load the checkout in place:

```bash
claude --plugin-dir /path/to/agent-toolbox/harnesses/claude-code/plugins/convene
```

Requirements: Python 3.11+ (the engine is stdlib-only), `git`, and the
harnesses you seat: `claude` and/or `codex` on `PATH`, logged in. The
`enforced` isolation tier needs `bwrap` (bubblewrap) on Linux; macOS gets
`private-home`. `bin/convene doctor` reports all of this.

## Use

In Claude Code:

```
/convene:panel HEAD~3..HEAD
/convene:panel HEAD seat=codex/gpt-5.5 seat=claude/opus --persona sec-urity --persona quinn-t-shun
/convene:status
```

The command writes a plan from `templates/panel.toml`, prepares and runs it,
reads the board, synthesizes, exports, and reports the receipts. The same
engine runs from a shell:

```bash
convene=~/.claude/plugins/cache/agent-toolbox/convene/*/bin/convene   # or the checkout's bin/convene
$convene doctor
$convene prepare templates/panel.toml --range HEAD~3..HEAD
$convene run 2026-09-21-panel-review-the-change
$convene status
$convene board
$convene export 2026-09-21-panel-review-the-change ~/tmp/panel-export
```

`convene --help` lists every verb. Runs live under
`$XDG_STATE_HOME/agent-toolbox/convene/<project-key>/<run>/` (default
`~/.local/state`), never inside the project, on both Linux and macOS.

## What a seat gets, and what it cannot reach

Every seat is launched with the harness flags that remove the operator's
layer: no setting sources (so no global `CLAUDE.md`), a pinned output style,
no hooks, no MCP servers, no project instruction files for Codex
(`project_doc_max_bytes=0`, `--ignore-rules`), a personality pin, and a
tool allow-list. Those flags hide the operator's world from the seat's
attention. The isolation tier hides it from the seat's hands:

| Tier | Platform | What the OS enforces | Attestation |
|---|---|---|---|
| `enforced` | Linux with `bwrap` | home blanked; only the private harness home, the launcher, credentials and the workspace bound back; repository read-only when `workspace = "repo-ro"` | `enforced: true` |
| `private-home` | Linux, macOS | private `HOME`, `CLAUDE_CONFIG_DIR`/`CODEX_HOME`, environment allow-list, neutral working directory | `advisory: true`; a tool given an absolute path can open it |
| `none` | any | nothing; the seat runs in the operator's own harness home | `enforced: false` |

`isolation = "strongest"` resolves at prepare time to the first available
tier, and the resolved tier is frozen into the plan and stamped on every
receipt. A run never claims more than it enforced.

Credentials: a Claude seat receives only the short-lived access token from
`~/.claude/.credentials.json` as `CLAUDE_CODE_OAUTH_TOKEN`; the refresh
token never enters a seat. On macOS that file is in the Keychain, so export
`CLAUDE_CODE_OAUTH_TOKEN="$(security find-generic-password -s "Claude Code-credentials" -w)"`
before running; the engine names that command when the token is missing. A
Codex seat in `private-home` gets `auth.json` copied 0600 into its private
home for the turn and removed afterwards; in `enforced` the file is bound
read-only.

## Opening doors on purpose

Everything above is the default. A seat that needs more says so, and the
receipt says it was granted:

| Where | Field | Effect |
|---|---|---|
| plan, seat, config file, `prepare --grant` | `grants = ["web", "mcp", "settings", "instructions", "hooks"]` | named doors, mapped per harness (below) |
| plan, seat, config file | `claude_args = [...]`, `codex_args = [...]` (a seat may write `args`) | raw arguments appended to that harness's command line, for anything without a name: `--mcp-config path`, `-c mcp_servers.x.command=...` |
| plan, seat, config file | `env = ["NAME", ...]` | operator environment variables passed through by name, on every tier |
| plan, seat, config file, `prepare --tools` | `tools = "write"` or `"research"` | a wider tool set |

| Grant | Claude seat | Codex seat |
|---|---|---|
| `web` | adds `WebSearch,WebFetch` to the tool list | `web_search="live"` |
| `mcp` | drops the empty strict MCP config, so the account's servers and any `--mcp-config` in `args` load | loads `config.toml` (MCP servers live there), as `settings` does |
| `settings` | drops `--setting-sources ""`, so the operator's settings and global `CLAUDE.md` load | drops `--ignore-user-config` |
| `instructions` | `--setting-sources project` | keeps `AGENTS.md` and execpolicy rules (drops `project_doc_max_bytes=0`, `--ignore-rules`) |
| `hooks` | drops `disableAllHooks` | no hooks exist |

The receipt checks accept what was granted (an MCP call on a seat with
`mcp`, a web fetch on a seat with `web`) and refuse the rest, and every
grant, extra argument and passed-through variable appears in the seat's red
flags, so an opened door is never invisible in the synthesis.

Defaults that should apply to every plan go in a config file:
`$XDG_CONFIG_HOME/agent-toolbox/convene.toml` for the user (default
`~/.config`), `<project>/.convene/config.toml` for a project. Both accept the
seat-default keys (`harness`, `model`, `effort`, `tools`, `isolation`,
`visibility`, `workspace`, `compaction`, `persona`, `grants`, `claude_args`,
`codex_args`, `env`, `jobs`) and nothing else; the project file wins over
the user file, the plan over both, a seat over the plan, and `prepare`'s
flags over the seat defaults. `prepare` prints which files it read.

## Receipts

`records/<seat>/rNNN/receipt.json` records, per turn: the session id, the
served model against the requested one (Claude: assistant message model plus
non-zero output tokens for that model; Codex: `turn_context` rows in the
native rollout), effort and its evidence, usage, tool calls, compaction
markers, the isolation attestation, whether the materials were intact after
the turn, the quota classification when a provider limit stopped the turn,
and a list of red flags. `convene status` prints the flags; the operator
skill requires them to be repeated to the user verbatim.

A provider quota stop holds the round open instead of publishing an absence:
the seat's turn is recorded as `quota` with the reset time, and the board is
not written. Continuing a held round arrives with the multi-round version.

## Personas and instruments

`personas/` holds ten fictional software-review perspectives (the names
follow quirework's pun catalog; the prompts are new): a skeptic, an
adversary, a maintainer, a measurer, a threat modeler, a reader of the
outside, an architect, a tester, a domain expert and a performance reviewer. A project adds its own
under `.convene/personas/<id>.json`; `convene personas list` prints the
catalog. `instruments/` holds what a phase asks for: `review` (numbered
findings with severity, location and failure scenario), `design` and
`implement`. Both are plain JSON with a `revision` integer.

## Platform notes

Tested on Linux (Fedora). The macOS paths (`ps` for process identity, the
Keychain hint, `private-home` as the strongest tier) are implemented and
unit-tested by patching the platform, not by running there; a wrong turn on
macOS exits non-zero naming the alternative.

## Attribution

Convene ports the generic core of [quirework](https://github.com/adereis/quirework):
the bubblewrap jail, the flag-liveness probes, the quota classifier, the
session rewind marks and the room's board and promotion invariants.
