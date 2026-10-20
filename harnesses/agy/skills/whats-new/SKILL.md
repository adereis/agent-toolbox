---
name: whats-new
description: Report what changed in Antigravity CLI (agy) since the last digest and how it affects this machine's configuration, or trace when a feature or fix landed. Use when asked what is new, whether recent releases affect you, what an update changed, or when some capability or behavior was introduced.
---

# Antigravity Release Digest

Read and follow the shared [release digest workflow](references/workflow.md).

Run the utility from `~/.gemini/config/scripts/agy-whats-new.py`, or from
`harnesses/agy/scripts/agy-whats-new.py` in the Agent Toolbox checkout when it
is not installed. Keep the checkout intact either way, because it imports the
shared modules under `tools/`.

A window of several releases prints more than one command result can show.
Save the utility's output to a file in a private directory, made with `mktemp -d`
inside `~/tmp` when it exists and inside `$HOME` otherwise. Read that file with
the Read tool until you reach its last line. The counts come before the first
bullet: `## Unmatched` always, and `## Withheld` when anything was withheld.
Remove the directory before writing the report.

Interpret the request:

| The user asked | Command |
|---|---|
| nothing in particular, or the request is empty | `agy-whats-new.py` |
| for a count of releases | `--releases N` |
| for a time span | `--days N` or `--months N` (requires dated notes) |
| since a known version | `--since VERSION` |
| when something landed | `--topic PATTERN` (repeat for each name it has had) |
| to re-read a past digest | `--since VERSION`, taking the version from `history` in the state file |

Add `--relevant-only` when the utility refuses a window as too wide. Never pass
`--commit` with `--topic`.

For a window report, commit the baseline as the last tool step before writing
the report: rerun the same arguments with `--through NEWEST_REPORTED_VERSION --commit`,
piped through `grep '^# Baseline'` so the digest is not printed a second time.
Pipe standard output only: the utility reports failures on standard error, and
`2>&1` would send them into the grep and out of sight.

The state lives in `~/.local/state/agent-toolbox/agy-whats-new.json` and keeps the
last five baselines. The changelog is cached under `~/.cache/agent-toolbox/agy-changelog.txt`.
Pass `--offline` to forbid spawning subprocesses or fetching when a cache is
available.

## Reading the digest

Read it in two passes before writing anything:

1. Go release by release and note every bullet that touches this machine: each
   bullet whose tag names something the environment block shows configured, and
   each `[-]` bullet that changes what a key, command, mode, or dialog does for
   everyone. With `mode: auto`, every `auto-mode` bullet is noted; with
   `plugins: science`, plugin and skill validation fixes are noted.
2. Place each noted bullet in one group, or drop it with a reason you could
   state. Related fixes may share one entry, but a fix to a configured feature
   is never dropped to save space.

Settle what the block already settles:
- Active plugins, skills, rules, hooks, and MCP servers are listed in the
  environment block.
- Environment variables report active variable names only.

## Deciding what goes under Act on this

Ask of each candidate: if the user does nothing, does something on this
machine now behave differently from what they rely on, in a way they may
want to change? Only a yes belongs there. These are never Act on this:
- a new switch that turns off something the user already allows
- a version or setting the user is already running
- a layout or wording change in a menu or dialog
- an option the entry itself says changes nothing here

They go under Worth knowing, or nowhere.

## Report layout

Use these headings, in this order:

1. One plain sentence saying whether anything needs a decision.
2. `## Act on this`, always present. When nothing qualifies, it holds the
   single line "Nothing here needs a decision."
3. `## Could not check`, `## Fixed for you` and `## Worth knowing`, each only
   when it has entries.
4. `## Counts and baseline`: the withheld count with its breakdown, the
   unmatched count, the version the baseline moved from, and the `--since`
   version that re-reads this window.

A topic trace uses its own layout: when the feature first appears, the arc of
later changes, and a coverage line naming matched entries.
