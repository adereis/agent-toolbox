---
name: convene
description: Operator procedure for convene runs: multi-seat panels over independent native CLI sessions with declared personas, isolation tiers and receipts. Read before driving `convene`; the commands invoke it.
disable-model-invocation: true
---

You are the operator of a convene run. The seats are independent native
sessions (`claude -p`, `codex exec`) that never see you and, in a panel,
never see each other. Your job is to give them a good brief, run them,
read what they wrote, and synthesize it without laundering the receipts.

The engine is `${CLAUDE_PLUGIN_ROOT}/bin/convene`; `--help` lists every
verb. State lives under `~/.local/state/agent-toolbox/convene/`, never in
the project.

## The loop

1. **Confirm the machine.** `convene doctor --no-probes` names the
   installed harnesses, their credentials and the isolation tiers
   available. `convene doctor` adds free flag-liveness probes; run them
   after a harness upgrade.
2. **Write the brief.** Follow [writing a brief](references/writing-a-brief.md).
   A brief says what the change is for and what a good post looks like;
   it does not say what to find.
3. **Choose seats.** Follow [choosing seats](references/choosing-seats.md).
   Persona × harness × model. When independence from your own judgment
   matters, at least one seat runs on a different harness than you do.
4. **Prepare and run.** `convene prepare PLAN --range A..B` freezes the
   plan and stages every seat's materials; it prints the resolved
   isolation tier per seat. `convene run NAME` runs the round and
   promotes the board. Seats run sequentially by default because seats
   sharing one account hit the same quota wall at once.
5. **Read status.** `convene status NAME`. A **held** round is a quota
   stop: the round stays open rather than publishing a false absence.
   Tell the user which seat and the reset time; a later version adds
   `continue`.
6. **Read the board.** `convene board NAME`, then follow
   [reading a board](references/reading-a-board.md). Read every post
   whole. The engine never summarizes.
7. **Synthesize.** Follow [synthesis](references/synthesis.md). Write
   `synthesis.md` into the export directory and cite seats by id.
8. **Export and report.** `convene export NAME DIR`. Report to the user:
   the synthesis, then the receipts (served model per seat, isolation
   tier, tool calls, usage) and every red flag verbatim.

## Red flags you must repeat, never soften

- `compaction observed`: a seat's context was rewritten mid-turn; its
  post may have lost the early material.
- `isolation is advisory`: the OS did not stop the seat from opening an
  absolute path; the tier was `private-home`.
- `no isolation`: the seat ran in the operator's own harness home.
- `granted on purpose: …`, `extra harness arguments: …`, `environment
  passed through: …`: a door the plan opened; name it beside the seat's
  findings.
- a `failed` seat with its error text; a `quota` seat with its scope.

## Opening doors

Seats are closed by default: no web, no MCP servers, no operator settings,
no project instruction files, no hooks. When the user asks for one of
those, or a seat needs it (a reviewer that must check a source, a seat
that must call a project MCP server), open it explicitly: `grants` in the
plan or seat, `prepare --grant web,mcp` for one run, or the user's config
file for every run. Raw harness arguments (`claude_args`, `codex_args`)
cover anything without a name. Never open a door silently to make a run
work; say which one and why in the report.

The plan format is in [plan reference](references/plan-reference.md).
