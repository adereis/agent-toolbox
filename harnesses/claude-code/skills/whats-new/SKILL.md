---
name: whats-new
description: Report what changed in Claude Code since the last digest and how it affects this machine's configuration, or trace when a feature or fix landed. Use when asked what is new, whether recent releases affect them, what an update changed, or when some capability or behavior was introduced.
argument-hint: "[topic, or a window like '2 weeks' or '10 releases']"
---

Read and follow the shared [release digest workflow](references/workflow.md).

Run the utility from `~/.claude/scripts/claude-code-whats-new.py`, or from
`harnesses/claude-code/scripts/` in the Agent Toolbox checkout when it is not
installed. It needs the checkout intact either way, because it imports the
shared modules under `tools/`.

Interpret `$ARGUMENTS`:

| The user asked | Command |
|---|---|
| nothing in particular | `claude-code-whats-new.py` |
| for a count of releases | `--releases N` |
| for a time span | `--days N` or `--months N` |
| since a known version | `--since VERSION` |
| when something landed | `--topic PATTERN` (repeat for each name it has had) |
| to re-read a past digest | `--since VERSION`, taking the version from `history` in the state file |

Add `--relevant-only` when the utility refuses a window as too wide. Add
`--commit` on the final run of a window report, once the digest has been
presented, to move the baseline forward. Never pass `--commit` with
`--topic`.

State lives in `~/.local/state/agent-toolbox/claude-code-whats-new.json` and
keeps the last five baselines. The changelog and release dates are cached
under `~/.cache/agent-toolbox/`; Claude Code's own cache is read, never
written. Pass `--offline` to forbid the network, accepting a possibly stale
changelog, which the utility will say.
