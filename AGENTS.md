# Agent Toolbox development

This repository distributes reusable tools, prompts, instructions, skills,
and harness integrations. Explain significant design choices before editing,
implement the agreed scope, and document usage with the change.

This file covers developing the repository. A harness loads it before
anything else, so it is also the first thing an agent reads here, and it
answers how to change these components rather than what they are or who
runs them. Read [README.md](README.md) for that: what the project is, the
catalog of components, which harness each supports, and how a user installs
them. Answer a question about the project from the README, and install or
operate components by following it; use the conventions below when editing
the repository itself.

## Layout and ownership

- `harnesses/<name>/` owns harness-specific configuration, hooks, agent
  definitions, packaging, and utilities that read that harness's state.
- Shared workflows belong in `skills/`, standalone prompts in `prompts/`,
  reusable policy modules in `instructions/`, and common programs in `tools/`
  when those components are introduced. Create directories for real content.
- Keep one authoritative source for shared content. Harness entry points
  should reference or package it rather than maintain independent copies.
- A harness entry point that links shared text keeps a committed
  `references/workflow.md` symlink beside it, so the link resolves in an
  uninstalled checkout as well as in an installation. An agent often reads
  the skill from the checkout before anything is installed.
- Root `AGENTS.md` governs development here. Distributed instruction modules
  are opt-in content, not automatically active repository policy.
- README files document usage and installation. This file documents developer
  conventions. Keep `CLAUDE.md` as the entry point to this file.

## Compatibility

Share task instructions where behavior is portable. Keep event payloads,
permission decisions, agent delegation, discovery paths, and state formats
inside the harness integration that understands them. Document supported
combinations and limitations; do not claim equivalent enforcement from a
prompt and a hook.

Reference examples must remain outside deployable component directories.
Installation must preserve unrelated local configuration and distinguish
project scope from user scope. Keep machine-specific MCP launchers, secrets,
session histories, and memory data outside this repository.

The installer handles only unambiguous linking. Work that requires judgment,
such as merging shared policy into a user's instruction file, belongs in a
prompt that reports what it changed, not in installer logic. Prefer a prompt
over a skill for a workflow that runs rarely and rewrites the user's own
configuration: a skill costs context in every session that can discover it,
while a prompt costs nothing until it is invoked by name.

Codex authentication profiles live in `harnesses/codex/profiles/` and install
at the user `CODEX_HOME`; other Codex components retain their `.agents`
destinations. Preflight and roll back a mixed installation across all roots.
Profile files contain provider and authentication settings only; keep
credentials and machine-specific defaults in the user's configuration.

The Codex tmux launcher composes the authentication profiles and existing
keyring helper. Acquire API keys inside the pane, after the private server
starts; never put credentials in its environment, commands, or runtime
metadata. Its telemetry module lives under `harnesses/codex/` and follows
open process descriptors, not the newest session file. Keep unknown or
ambiguous telemetry visibly unavailable. Per-response cost estimates use
the dated price table beside that module; update its source/date and cost
tests when pricing rules change.

The Codex release digest reads configuration files without exposing arbitrary
values. Keep credentials, hook commands, MCP arguments, and provider endpoints
out of its fingerprint. State is isolated by Codex home, project, and profile;
serialize baseline writes and never regress a recorded release. Only complete
public release archives may replace the cache. Shared release-window, terminal,
and baseline primitives stay in `tools/_whats_new.py`.

The Codex digest skill delegates release interpretation to a fresh Luna
subagent at high effort. The parent supplies the complete report and exact
utility arguments, checks the claims, and owns the baseline. Keep the
reader procedure next to the Codex entry point and the shared relevance
rules in `skills/whats-new/`; install the Codex skill as a directory link
so its regular `SKILL.md` is discoverable. The utility's skill inventory
must follow the same entry-point rule as native discovery.

## Convene plugin

`harnesses/claude-code/plugins/convene/` is a Claude Code plugin and the
plugin root is its own world: an installed plugin is a copy of that
directory, so nothing inside it may import or link outside it. The engine
under `engine/convene/` is stdlib-only Python 3.11+, entered through
`bin/convene`, and commands reach it through `${CLAUDE_PLUGIN_ROOT}`.

One harness protocol (`harnesses/__init__.py`) owns every argv, private
home, session lookup and receipt; do not add a second argv builder for a
CLI that already has one. Isolation tiers must attest what they enforced
and the receipt carries the attestation; `strongest` resolves at prepare
time and the resolved tier is frozen. A run never claims more than it
enforced. Run state lives under `$XDG_STATE_HOME/agent-toolbox/convene`,
never inside the project, and credentials never enter a record.

The jail is an allow-list all the way down, and the root is no exception.
It binds a fixed set of system trees read-only at their own paths (`/usr`,
`/etc`, and `/opt`, `/var/lib`, `/sys`, `/nix`, `/snap` where present) and
nothing else, so the operator's home, network shares and removable media
never exist inside and no mount table is read. Do not reintroduce a
deny-list of filesystem types or a whole-root bind: every earlier repair
to the root (enumerating `/` around a stale share, probing before each
launch, re-reading the table after the probe) was a consequence of that
shape, and inverting it removed the class. A CLI that needs a tree outside
the list fails loudly at launch; add the tree to the list, do not bind `/`.

The seat runs in its own pid, ipc, uts and cgroup namespaces with bwrap's
minimal `/dev`, and `/run/user/<uid>` is never bound: the session bus there
lets `systemd --user` start a process outside any sandbox, which is a full
escape for a seat with a shell. A harness that must reach a bus name
declares it in `bus_names`; the jail runs `xdg-dbus-proxy` filtered to
those names, binds only the proxy's socket, ties the proxy's lifetime to
the jail through `--sync-fd`, and the receipt reports the opened door as a
red flag. Without the proxy the enforced tier is unavailable to that
harness rather than quietly less enforced.

The jail's invariants, each asserted by the test of the same label in
`tests/test_convene_isolation.py` (`JailInvariantTests`):

- **J1 root.** The root is the allow-list of system trees, read-only.
  `/` is never bound whole and no mount table is read.
- **J2 home.** `$HOME`, `/tmp` and `/var/tmp` are size-capped tmpfs. The
  private harness home, launcher, credentials and workspace are bound
  back after them, and the writable workspace is the last bind.
- **J3 bus.** `/run/user/<uid>` is never bound from the host. A declared
  bus name arrives only through `xdg-dbus-proxy --filter`, whose socket
  lives exactly as long as the jail through `--sync-fd`.
- **J4 process.** The seat has its own pid, ipc, uts and cgroup
  namespaces, dies with its parent, and gets bwrap's minimal `/dev`,
  never the host's.
- **J5 receipt.** The receipt names the root, the namespaces and any
  proxied bus this launch used, and a proxied bus is a red flag.
- **J6 refusal.** A jail that cannot be built as specified is refused by
  name (a missing required tree, a missing proxy), never built weaker.

quirework's `providers/blind.py` is the same jail. A change to one of
these invariants belongs in both, even while the code stays duplicated.

Seats are closed by default and opened only on purpose. A new capability
(a tool, a server, a setting source) is a named grant in
`harnesses.GRANTS`, mapped per harness, accepted by that harness's receipt
checks and reported as a red flag; it is never enabled by default and
never enabled silently to make a run pass. Raw arguments and environment
pass-through exist for what has no name yet, and they too appear in the
receipt.

Codex turns tools on by default between releases, and some arrive with the
account rather than from any file. Every Codex seat, whatever its tool
set, turns off the account's connected apps (unless `mcp` is granted),
image generation, and sub-agents. Multi-agent v2 ignores
`features.multi_agent=false`, so the seat's session is limited to one
thread. A switch closed in `harnesses/codex.py` is also reserved there
against raw args, because a seat's args come last and the last value of a
key wins. It is also probed by the doctor. A feature's probe reads
`codex features list` with the setting applied, because Codex type-checks
a feature's value whether or not the feature exists.

A harness whose stream does not name what it loaded proves it in
`preflight`, which runs inside the seat's own wrapper before the turn.
Codex's asks its app server for the seat's MCP inventory. Without `mcp`,
any server refuses the turn, and so does an inventory that cannot be read.
The app-server protocol is experimental. When a release breaks the reader,
fix the reader; never let the seat run unchecked. The app server cannot
ignore `config.toml` as the seat does, so an unjailed seat that ignores it
is inventoried against a view of its home without that file.

A `worktree` seat gets a private `git clone --local` of the operator's
repository, not a linked worktree, with its origin removed and a generic
git identity. Linked worktrees share the operator's `.git`: the jail had
to bind its object store read-only, so no seat could commit, and on
private-home one seat's `git log --all` showed every other seat's
commits. A seat's repository lives wholly inside its workspace; do not go
back to binding the operator's `.git` to give a seat one.

A fanout's judge seat sees copies of the sealed letters and nothing else
of the run. It never gets the key or `seal.json`, and never the board,
which names every seat. It may read the repository (`repo-ro`), because
the attempts' clones leave no trace there. Only the enforced tier makes
that blindness more than the judge's good behaviour, so every other
tier's receipt says `judging is advisory`. Seats the engine appends to act
alone, the judge and the synthesizer, deliver through their post rather
than an outbox file, because their default read tool set cannot write
one; `prepare` refuses any phase that asks a seat without
`tools = "write"` for a file.

Models are named by family (`opus`, `terra`, `gemini-pro`), never by a
version, in defaults, templates and examples of what to write. A family
resolves at prepare to the newest version the harness's own catalog lists
(`newest_in_family` in `harnesses/__init__.py`) and the resolved id is
frozen with the family recorded beside it, so a release needs no change
here. Do not add a list of model versions to the engine; where a harness
has no catalog, as Claude Code has none, pass its own alias through and
let the receipt verify what was served. The seat's first turn whose
stream names a served model records that version in its state, whether
the turn answered or a quota cut it partway, and every resumed turn
names it exactly, because an alias on resume would follow a release
mid-run. `launch` refuses a fork, which would need its parent's version.

Codex reaches the engine without the plugin: `tools/install.py` links
`bin/convene` onto `PATH` as the `convene` command and links the plugin's
`skills/convene/` as a Codex skill. The plugin's `SKILL.md` is the one
authoritative operator procedure; `harnesses/codex/skills/convene/` holds
symlinks into it, never a copy. Install that skill as a directory link;
Codex's discovery skips symlinked `SKILL.md` files. Keep `agents/openai.yaml`
inside the shared skill so its explicit invocation policy survives native
path resolution. Antigravity seats are audited, not
confined: the adapter rejects tool sets it cannot enforce and checks the
transcript instead, and it has no private-home tier.

Tests drive the engine against the stub binaries in `tests/convene-stubs/`
with an isolated home under `~/tmp`; a scenario is chosen by a
`[[stub:NAME]]` token in the brief. The real bubblewrap jail test runs only
where `bwrap` exists. macOS paths are implemented as breadcrumbs and
unit-tested by patching the platform until someone runs them there.

## Portability

Consumers run Linux and macOS. Implement the platform you can test, and make
the untested path fail loudly instead of silently: detect the unsupported
platform and exit non-zero naming the command that works there. Prefer a
breadcrumb over an untested implementation, because a wrong implementation
fails in the user's session while a breadcrumb costs them one step.

Add a portable fallback where one is cheap. Convene's `platform.py` reads a
process start time from `/proc` on Linux and asks `ps` on macOS, and raises
anywhere else rather than guessing.
Where no such fallback exists, name the alternative: `codex-api-profile.sh`
implements the libsecret keyring only and prints the equivalent macOS
`security` commands when it runs on Darwin.

State the supported platform with the component, and do not claim support
for a platform without evidence that the code ran there.

## Agent-mediated use

Most consumers reach this repository through a coding agent rather than by
reading it themselves. That agent sees error output, `--help` text, and
README prose; it cannot see intent that was never written down.

Write failures so an agent can act on them unaided: name the missing tool,
the platform, and the command that would succeed. "Keyring not supported"
strands the agent, while a message naming `security find-generic-password`
lets it finish the task on macOS without asking the user.

Keep usage next to the component and keep help text able to stand alone,
because an agent may read only one of the two.

## Validation

Run `./tests/run.sh` for all automated checks, or
`./tests/run.sh session_resume` for a single shell suite. Tests use synthetic
data and isolated temporary directories under `~/tmp`; never use `/tmp`.
The shell assertions live in `tests/test_helper.sh`. Live integration checks
are described in `tests/INTERACTIVE.md`; report them separately from unit
tests and do not claim they ran without evidence.

Update paths, installation instructions, and relevant tests in the same
commit as a move or behavior change. Add regression coverage for meaningful
behavior and isolate fixtures from user profiles and concurrent test runs.

## Git history

Make incremental commits that explain the problem, reason for the change,
chosen approach, tradeoffs, and actual validation. Inspect recent messages
and the staged diff before committing. Target a 50-column subject with 60 as
the hard limit, wrap body paragraphs at 72 columns, and include an accurate
`Co-Authored-By` trailer. Include `Claude-Session` only when this session has
such a URL.

Fold follow-up fixes into their intended commit. Check `git log -1 --oneline`
before any amend or soft reset and never reuse an unrelated commit's subject.
Do not push without an explicit request.
