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

Seats are closed by default and opened only on purpose. A new capability
(a tool, a server, a setting source) is a named grant in
`harnesses.GRANTS`, mapped per harness, accepted by that harness's receipt
checks and reported as a red flag; it is never enabled by default and
never enabled silently to make a run pass. Raw arguments and environment
pass-through exist for what has no name yet, and they too appear in the
receipt.

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

Add a portable fallback where one is cheap. `file_sha` in
`claude-memory-lib.sh` tries `sha256sum` and falls back to `shasum -a 256`.
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
and the staged diff before committing. Use a subject of at most 50 columns,
wrap body paragraphs at 72 columns, and include an accurate `Co-Authored-By`
trailer. Include `Claude-Session` only when this session has such a URL.

Fold follow-up fixes into their intended commit. Check `git log -1 --oneline`
before any amend or soft reset and never reuse an unrelated commit's subject.
Do not push without an explicit request.
