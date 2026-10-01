---
name: whats-new
description: Report what changed in Claude Code since the last digest and how it affects this machine's configuration, or trace when a feature or fix landed. Use when asked what is new, whether recent releases affect them, what an update changed, or when some capability or behavior was introduced. It runs in a sub-agent that cannot see the conversation, so pass the user's whole question as the argument.
argument-hint: "[question, topic, or a window like '2 weeks' or '10 releases']"
context: fork
model: sonnet
effort: high
background: false
---

You run in a sub-agent and cannot see the user's conversation. The request
below is all you know about what they asked. Your final message is the
report: the main session relays it to the user, so make it the finished
digest and nothing else.

Request: $ARGUMENTS

Read and follow the shared [release digest workflow](references/workflow.md),
found at `${CLAUDE_SKILL_DIR}/references/workflow.md`.

Run the utility from `~/.claude/scripts/claude-code-whats-new.py`, or from
`harnesses/claude-code/scripts/` in the Agent Toolbox checkout when it is not
installed. It needs the checkout intact either way, because it imports the
shared modules under `tools/`.

A window of a few releases prints more than one command result can show.
Save the utility's output to a file in a private directory, made with
`mktemp -d` inside `~/tmp` when it exists and inside `$HOME` otherwise. Read
that file with the Read tool, using `offset` and `limit`, until you reach its
last line. Do not page with `cut`, `head -c` or `grep -v`: a cut line loses
the end of its bullet, and the `[-]` lines hold the new features the workflow
says to read. The counts come before the first bullet: `## Unmatched`
always, and `## Withheld` when anything was withheld. Remove the directory
before writing the report.

Interpret the request:

| The user asked | Command |
|---|---|
| nothing in particular, or the request is empty | `claude-code-whats-new.py` |
| for a count of releases | `--releases N` |
| for a time span | `--days N` or `--months N` |
| since a known version | `--since VERSION` |
| when something landed | `--topic PATTERN` (repeat for each name it has had) |
| to re-read a past digest | `--since VERSION`, taking the version from `history` in the state file |

Add `--relevant-only` when the utility refuses a window as too wide. Never
pass `--commit` with `--topic`.

A sub-agent cannot act after its final message, so this replaces the
workflow's rule to advance the baseline after presenting. For a window
report, commit as the last step before writing the report: rerun the same
arguments with `--commit`, piped through `grep '^# Baseline'` so the digest
is not printed a second time. The baseline therefore moves before the user
reads the digest. That is recoverable, because the state keeps the last five
baselines. End the report by naming the version the baseline moved from, so
the user can re-read this digest later with `--since` that version.

State lives in `~/.local/state/agent-toolbox/claude-code-whats-new.json` and
keeps the last five baselines. The changelog and release dates are cached
under `~/.cache/agent-toolbox/`; Claude Code's own cache is read, never
written. Pass `--offline` to forbid the network, accepting a possibly stale
changelog, which the utility will say.
