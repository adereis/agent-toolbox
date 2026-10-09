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
`mktemp -d` inside `~/tmp` when it exists and inside `$HOME` otherwise. Each
command runs in a fresh shell, so reuse the path `mktemp` printed; never
record it in a file of your own, which a concurrent run would share. Read
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
is not printed a second time. Pipe standard output only: the utility reports
failures on standard error, and `2>&1` would send them into the grep and out
of sight. The baseline therefore moves before the user reads the digest.
That is recoverable, because the state keeps the last five baselines. End
the report by naming the version the baseline moved from, so the user can
re-read this digest later with `--since` that version.

State lives in `~/.local/state/agent-toolbox/claude-code-whats-new.json` and
keeps the last five baselines. The changelog and release dates are cached
under `~/.cache/agent-toolbox/`; Claude Code's own cache is read, never
written. Pass `--offline` to forbid the network, accepting a possibly stale
changelog, which the utility will say.

## Reading the digest

Read it in two passes before writing anything.

1. Go release by release and note every bullet that touches this machine:
   each bullet whose tag names something the environment block shows
   configured, and each `[-]` bullet that changes what a key, a prompt or a
   dialog does for everyone. With `defaultMode=auto`, every `auto-mode`
   bullet is noted; with `editor=vim`, every `vim` bullet.
2. Place each noted bullet in one group, or drop it with a reason you could
   state. Related fixes may share one entry, but a fix to a configured
   feature is never dropped to save space.

Settle what the block already settles:

- The plugins line lists enabled plugins only. Never suggest enabling a
  plugin it names.
- A bullet that offers a variable to opt out (`0` turns it off, a
  `DISABLE_` name) describes behavior that is on by default. It applies here
  unless the env vars line shows that variable set.
- Whole-tool rules are listed separately from scoped ones. A bullet about
  whole-tool rules does not apply when the block lists none for that tool.

## Deciding what goes under Act on this

Ask of each candidate: if the user does nothing, does something on this
machine now behave differently from what they rely on, in a way they may
want to change? Only a yes belongs there. These are never Act on this:

- a new switch that turns off something the user already allows
- a price, a model's new default, or a version the user is already running
- a layout or wording change in a menu or dialog
- an option the entry itself says changes nothing here

They go under Worth knowing, or nowhere.

## Report layout

Use these headings, in this order:

1. One plain sentence saying whether anything needs a decision.
2. `## Act on this`, always present. When nothing qualifies, it holds the
   single line "Nothing here needs a decision."
3. `## Could not check`, `## Fixed for you` and `## Worth knowing`, each
   only when it has entries.
4. `## Counts and baseline`: the withheld count with its breakdown, the
   unmatched count, the version the baseline moved from, and the `--since`
   version that re-reads this window.

A topic trace uses its own layout: when the feature first appears, the arc
of later changes with dates, and a coverage line. The coverage line says how
many entries matched and whether you read them all; the utility shows only
the 40 most recent unless you pass `--limit 0`. Name entries that use the
feature's words for a different feature, and never date the feature from
them.
