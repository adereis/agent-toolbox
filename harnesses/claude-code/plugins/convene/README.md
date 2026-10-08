# Convene

Convene runs several independent AI coding sessions on the same brief and
brings back what each of them wrote, with a receipt for what actually ran.
The seats are native CLIs (`claude -p`, `codex exec`, `agy --print`), each
with a declared persona, model, tool set and isolation tier. The foreground
session is the operator: it writes the brief, runs the seats, reads the
board and synthesizes. Claude Code operates through this plugin; Codex
operates through the toolbox installer, which puts `convene` on `PATH` and
links this plugin's operator procedure as a Codex skill (see the
[Codex integration](../../../codex/README.md#convene-from-codex)).

Three kinds ship. The **panel** is a one-round review of a commit range by
independent reviewers who do not see each other. The **room** has seats
discuss a brief over rounds on a shared board, one seat draft the change in
its own git worktree, and the room critique and revise it. The **fanout**
hands the same brief to N seats that each implement it blind in their own
worktree. The operator, or a judge seat that sees nothing but the attempts,
reads them sealed under letters and records a judgment, and only then does
anyone learn who wrote what.

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
harnesses you seat: `claude`, `codex` and/or `agy` on `PATH`, logged in. The
`enforced` isolation tier needs `bwrap` (bubblewrap) on Linux; macOS gets
`private-home`. `bin/convene doctor` reports all of this.

Antigravity (`agy`) is the least confinable seat: it has no tool
allow-list, no setting-source switch, no context ceiling and nothing that
relocates its home. An `agy` seat therefore always runs with `tools =
"write"`. Its declared file/path arguments and network tools are audited
from the transcript. Path checks apply on every tier, including enforced
isolation, against the seat's working directory and any declared read-only
repository. Relative paths and `..` are normalized before checking.
This checks tool arguments; it is not a trace of filesystem access inside
shell commands or through symlinks. Compaction is
detected rather than prevented (the plan records `compaction = "detected"`),
and its only tiers are `enforced` (the jail binds a private `~/.gemini`)
and `none`; `private-home` is refused by name. Its token lives in the login
keyring, so the enforced jail runs `xdg-dbus-proxy` (Fedora: `dnf install
xdg-dbus-proxy`) filtered to `org.freedesktop.secrets` and binds only that
socket; the receipt flags it, because the secrets service exposes every
secret the keyring holds. Without the proxy, `enforced` is unavailable for
`agy` and `strongest` resolves to `none`. The proxy's socket lives in a
private directory under `$XDG_RUNTIME_DIR/agent-toolbox/`. A run killed
outright leaves that directory behind, and the next enforced agy launch
removes it once its proxy is gone.

## Use

In Claude Code:

```
/convene:panel discuss
/convene:panel discuss HEAD~3..HEAD
/convene:panel HEAD seat=codex/terra seat=claude/opus --persona sec-urity --persona quinn-t-shun
/convene:room Add a --json flag to the session browser that prints what --list prints
/convene:fanout seats=3 Implement --json for the session browser; verify with the existing tests
/convene:status
```

Start with `discuss` when the run is not settled yet. The operator then
designs the run with you in conversation and runs nothing until you accept
the plan. The plan names the range or brief, each seat as `harness/model`
with its persona, the isolation tier each seat resolves to, the tool set
and any grants, the round budget, and how many seats run at once. Correct
any of it by answering, for example by moving a seat to another harness or
asking for a different persona. Whatever follows `discuss` is a starting
point, not the whole plan: `/convene:panel discuss HEAD~3..HEAD` fixes the
range and leaves the seats open. `panel`, `room` and `fanout` all accept it.

A command with no arguments behaves the same as `discuss`. A command that
names both the work and the seats, like the third line above, runs
straight away because nothing is left to propose. Anything in between, such
as a brief with no seats, gets a proposal and a question rather than a run
filled in from the template's defaults. A run starts several provider
sessions and spends real quota, so you see the plan before it spends any.

Name a seat's model by its family: `opus`, `fable`, `terra`, `sol`,
`gemini-pro`, `flash`. `prepare` resolves a family to the newest version
that harness's own catalog lists, so a plan written today picks up next
month's release without an edit. The resolved version is frozen into the
run, and every round of that run uses it. For example, `seat=codex/terra`
prepares as `gpt-5.6-terra (from terra)`. A version, such as `opus-5.5` or
`gpt-5.6-terra`, pins the seat instead. Claude Code has no local catalog, so
a Claude family is passed as the CLI's own alias and the receipt records
the version that answered. Every later round of that seat resumes pinned to
that version, and its receipt shows the pin as `model_pinned`. So an Opus
released between rounds two and three does not change who is speaking.

Once the plan is agreed, the command writes it from `templates/panel.toml`,
prepares and runs it, reads the board, synthesizes, exports, and reports
the receipts. The same engine runs from a shell:

```bash
convene=~/.claude/plugins/cache/agent-toolbox/convene/*/bin/convene   # or the checkout's bin/convene
$convene doctor
$convene prepare templates/panel.toml --range HEAD~3..HEAD
$convene run 2026-09-21-panel-review-the-change
$convene status
$convene board
$convene export 2026-09-21-panel-review-the-change ~/tmp/panel-export
```

A room plays rounds until its phases are done, until an unphased room
converges (two consecutive rounds of low novelty or closing language), or
until a provider quota stop holds a round open. Then:

```bash
$convene status NAME                 # HELD: round 2 waiting on skeptic
$convene continue NAME skeptic       # once the window resets
$convene promote NAME 2              # or: promote NAME 2 --absent
$convene run NAME                    # the remaining rounds
$convene extend NAME 6               # more rounds than the plan declared
$convene prune NAME                  # remove seat repositories and private homes; records stay
```

`convene status` reads the records and changes nothing. Its header counts
published rounds against the budget, reports the room's novelty once there
are two rounds to compare, and counts the red flags marked `!` below it.
Each seat then reports how many of the rounds its phase lets it speak in it
answered, one line per turn, holding only the fields that turn's receipt
recorded. The last line names the command to run next. `convene status
--help` reads a worked example line by line.

An operator note for the next round goes in `chair/rNNN.md` inside the run
directory; every acting seat reads it that round and the digest records it.

A fanout is read sealed:

```bash
$convene seal NAME                   # sealed/r001/{A,B,C}/{post.md,report.md,changes.patch}
$EDITOR ~/.local/state/agent-toolbox/convene/*/NAME/sealed/r001/judgment.md
$convene unseal NAME                 # prints A = two (codex/gpt-5.6-terra), ...
$convene board NAME                  # attributed from here on
```

Until `unseal`, `board`, `usage` and `export` refuse and say why, and
`status` withholds each seat's duration and tool count: those numbers are
near-unique per seat and would be the identity key by arithmetic. The key
file is written at `seal` and never printed before a judgment is on file.
A plan may name a seat as the synthesizer (`[synthesis] by = "ID"`): it
acts alone in one extra round, sees the board, and posts the synthesis;
the operator still reads the attempts sealed first.

The operator wrote the plan, so it knows which persona sits on which model
and is never fully blind. A plan may name a judge seat instead
(`[judgment] by = "ID"`). `run` then seals the attempts itself and plays
one more round, in which the judge alone reads the letters' own files:
no key and no board, and the repository only if the plan gives the judge
`workspace = "repo-ro"`. Its post is filed as `judgment.md`,
and `unseal` prints who judged. Only the `enforced` tier keeps the run
directory out of the judge's reach; on any other tier its receipt says
`judging is advisory`.

`convene follow NAME SEAT` tails a running seat: what it says, which tools
it calls, and its stderr when the turn ends; `--thinking` adds reasoning.
Use `--round N` for a specific turn that has started. A missing turn fails
immediately with a pointer to `convene status`; it does not wait for a
future round.

`convene --help` lists every verb. Runs live under
`$XDG_STATE_HOME/agent-toolbox/convene/<project-key>/<run>/` (default
`~/.local/state`), never inside the project, on both Linux and macOS.

## What a seat gets, and what it cannot reach

Every seat is launched with the harness flags that remove the operator's
layer: no setting sources (so no global `CLAUDE.md`), a pinned output style,
no hooks, no MCP servers, no project instruction files for Codex
(`project_doc_max_bytes=0`, `--ignore-rules`), a personality pin, and a
tool allow-list. A Codex seat also turns off what Codex turns on by
default: the account's connected apps (`features.apps=false`), which
arrive with the login rather than from any file; image generation; and
sub-agents. Codex offers most models a `spawn_agent` tool that
`features.multi_agent=false` does not remove, so every Codex seat is
limited to one thread, itself, and a spawn fails. Without that limit a seat
could hand its work to a model its receipt never names. Raw `codex_args`
cannot reopen any of these.

Codex has no start-up event that names what it loaded, so before each Codex
turn the engine asks Codex's own app server, inside the seat's wrapper and
under its settings, which MCP servers the seat would hold. Without the
`mcp` grant, any server refuses the turn before a model is called, and so
does an inventory that cannot be read. With the grant, the servers are
recorded as a red flag. The protocol is marked experimental in Codex, so a
release that changes it stops Codex seats by name rather than letting them
run unchecked.

Those flags hide the operator's world from the seat's attention. The
isolation tier hides it from the seat's hands:

| Tier | Platform | What the OS enforces | Attestation |
|---|---|---|---|
| `enforced` | Linux with `bwrap` | root is an allow-list of system trees bound read-only (`/usr`, `/etc`, `/opt`, `/var/lib`, `/sys`); home blanked; only the private harness home, the launcher, credentials and the workspace bound back; own pid/ipc/uts namespaces, minimal `/dev`, no `/run/user` and no session bus; repository read-only when `workspace = "repo-ro"` | `enforced: true` |
| `private-home` | Linux, macOS | private `HOME`, `CLAUDE_CONFIG_DIR`/`CODEX_HOME`, environment allow-list, neutral working directory | `advisory: true`; a tool given an absolute path can open it |
| `none` | any | nothing; the seat runs in the operator's own harness home | `enforced: false` |

`isolation = "strongest"` resolves at prepare time to the first available
tier, and the resolved tier is frozen into the plan and stamped on every
receipt. A run never claims more than it enforced.

What the enforced jail does not cut off is the network, which a seat needs
for its provider: anything listening on this machine, such as a container
socket or a local MCP server, is reachable from inside. The receipt's
`isolation` object lists the trees bound read-only, the namespaces, and a
`session_bus` entry that is `null` unless a bus was proxied in.

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
| `mcp` | drops the empty strict MCP config, so the account's servers and any `--mcp-config` in `args` load | keeps the account's connected apps (drops `features.apps=false`) and loads `config.toml` (MCP servers live there), as `settings` does |
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
for Codex the MCP servers the seat held by its app server's count
(`mcp_servers`), and a list of red flags. `convene status` prints the flags; the operator
skill requires them to be repeated to the user verbatim.

A provider quota stop holds the round open instead of publishing an absence:
the seat's turn is recorded as `quota` with the reset time, and the board is
not written. `continue` retakes the turn: a refused stop (nothing ran)
rewinds the native session to its pre-submission mark and delivers the same
prompt again; an interrupted stop (the model ran) resumes the session with a
task-free continuation note. The stopped attempt is archived beside the new
one, so the round reads as two submissions rather than one that changed its
mind.

## Rounds, phases and worktrees

From round two a `board` seat finds the previous round's digest under
`board/round-NNN/digest.md` in its working directory and is told the board
has moved; a `blind` seat never sees one. Sessions are resumed, so a turn
costs one line of prompt on top of the seat's own context. A seat whose
earlier turn produced nothing joins cold, is told it missed the opening, and
is marked `JOINED LATE` in `status`.

Phases divide the rounds: each may seat a subset (the rest listen), ask for
a `deliverable` file written to `outbox/NAME` beside the post, add an
`instruction`, or set a post `length`. Promotion moves deliverables to
`board/made/<seat>/rNNN/` and prints them under the post on the digest. A
`worktree` seat (`tools = "write"`) gets a private clone of the repository
at `repo/`, checked out detached at the run's base commit, with no remote
and a generic git identity, so it can commit on any tier. Whatever it
changes is captured against the base commit as `changes.patch` on every
round it acts, committed and untracked files included. The operator's
checkout is never touched and its `.git` records nothing of the clone, so
no seat can reach another's commits through git.

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
