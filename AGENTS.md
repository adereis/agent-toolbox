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
