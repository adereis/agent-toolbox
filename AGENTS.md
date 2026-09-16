# Agent Toolbox development

This repository distributes reusable tools, prompts, instructions, skills,
and harness integrations. Explain significant design choices before editing,
implement the agreed scope, and document usage with the change.

## Layout and ownership

- `harnesses/<name>/` owns harness-specific configuration, hooks, agent
  definitions, packaging, and utilities that read that harness's state.
- Shared workflows belong in `skills/`, standalone prompts in `prompts/`,
  reusable policy modules in `instructions/`, and common programs in `tools/`
  when those components are introduced. Create directories for real content.
- Keep one authoritative source for shared content. Harness entry points
  should reference or package it rather than maintain independent copies.
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
such as merging shared policy into a user's instruction file, belongs in an
agent workflow that reports what it changed, not in installer logic.

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
