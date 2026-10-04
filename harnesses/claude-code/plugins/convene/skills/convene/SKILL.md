---
name: convene
description: "Operator procedure for convene runs: multi-seat panels over independent native CLI sessions with declared personas, isolation tiers and receipts. Read before driving `convene`; the commands invoke it."
disable-model-invocation: true
---

You are the operator of a convene run. The seats are independent native
sessions (`claude -p`, `codex exec`, `agy --print`) that never see you and, in a panel,
never see each other. Your job is to give them a good brief, run them,
read what they wrote, and synthesize it without laundering the receipts.

The engine is the `convene` command. Inside Claude Code it is
`${CLAUDE_PLUGIN_ROOT}/bin/convene`; with the toolbox's `commands`
component installed it is `convene` on PATH; in a checkout it is
`harnesses/claude-code/plugins/convene/bin/convene`. `convene --help` lists
every verb. State lives under `~/.local/state/agent-toolbox/convene/`, never
in the project. Seats run on Claude Code, Codex or Antigravity; the
operator may be any of them.

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
   `convene personas` lists every persona with its id and one line of
   what it reviews; read it rather than inventing an id, because a plan
   naming one that does not exist fails at prepare.
   Write a model as its family (`opus`, `terra`, `gemini-pro`) unless the
   user named a version. `convene prepare` resolves the family to the
   newest version the harness lists and prints what it chose, as in
   `gpt-5.6-terra (from terra)`. It refuses a name no catalog can place
   and lists the families that exist, rather than letting the seat die at
   launch. Never pass a user's shorthand straight to a CLI, including in a
   quick check of your own: `opus-5.5` reaches Claude as `claude-opus-5-5`
   only through the engine.
4. **Agree the plan, unless the invocation already settled it.** A convene
   run spends real provider quota on several sessions, so the user sees
   the plan before it runs. State the range or brief, every seat as
   `harness/model` with its persona, the isolation tier each will resolve
   to, the tool set and any grants, the round budget, and how many seats
   run at once. Then ask, and wait. Anything you chose rather than read from the invocation is a
   proposal, including a default you took from the template.

   Run without asking only when the invocation already names the work and
   the seats, because then there is nothing left to propose. Treat an
   invocation that names neither, or that opens with `discuss`, as a
   request to design the run in conversation: propose a plan, take the
   user's corrections, and run once they accept it. Never expand a
   half-specified invocation into a full run by filling the rest with
   defaults.

5. **Prepare and run.** `convene prepare PLAN --range A..B` freezes the
   plan and stages every seat's materials; it prints the resolved
   isolation tier per seat, how many seats run at once, and the commits
   the range actually covers. Read that list before running: `A..B`
   excludes `A`, so the commit a user names first is not reviewed, and
   prepare names it as the base for exactly that reason.

   Start the run in the background, not in the foreground. A round takes
   minutes — seats answer in single-digit minutes each — and a foreground
   `convene run` blocks you from reporting progress or taking a correction
   until it returns. Launch it in the background and watch it with
   `convene follow NAME`, which streams events as rounds open and seats
   answer. `convene run NAME` plays rounds and promotes
   the board after each, stopping when the phases are done, when an
   unphased room converges, or when a quota stop holds a round. Seats
   run sequentially by default because seats sharing one account hit
   the same quota wall at once. `convene round NAME N` plays one round.
6. **Read status.** `convene status NAME`. A **held** round is a quota
   stop: the round stays open rather than publishing a false absence.
   Tell the user which seat and the reset time. When it resets,
   `convene continue NAME SEAT`, then `convene promote NAME N`, then
   `convene run NAME` for the rest. `promote NAME N --absent` gives up
   on the stopped seat instead, and says so on the board. A note the
   room should read before round N goes in `chair/rNNN.md`. The last
   line of the output names this same next command, computed from the
   run's own state; report it, and run it only when asked.
7. **Read the board.** `convene board NAME`, then follow
   [reading a board](references/reading-a-board.md). Read every post
   whole. The engine never summarizes.
8. **Export and synthesize.** `convene export NAME DIR` creates the export;
   DIR must be absent or empty. Then follow [synthesis](references/synthesis.md).
   Write `synthesis.md` into that directory and cite seats by id.
9. **Report.** Report to the user:
   the synthesis, then the receipts (served model per seat, isolation
   tier, tool calls, usage) and every red flag verbatim. Offer
   `convene prune NAME` once the export is in hand: it removes the
   worktrees and private homes and keeps every record.

## Reading a sealed round

A fanout, or any run with a blind seat, is read sealed. After `run`:
`convene seal NAME` letters the latest round a blind seat acted in under
`sealed/rNNN/` in the run directory. A synthesizer's round is never
lettered; it stays withheld with the attempts until they are unsealed.
Read every letter's `post.md`, `report.md` and `changes.patch` before
anything else. Do not call `board`, `usage` or `export`; they refuse
until the round is unsealed, and `status` withholds
durations and tool counts, because any of those beside a seat id is the
key by arithmetic. Write your judgment to `sealed/rNNN/judgment.md` by
letter: which attempt to take, what to change in it first, what the
others got right. Then `convene unseal NAME`, which prints the key. Report
the judgment as written, then the key, then the receipts. A synthesizer
seat's synthesis is its post on the board; read it after your own judgment.

## Red flags you must repeat, never soften

- `compaction observed`: a seat's context was rewritten mid-turn; its
  post may have lost the early material.
- `isolation is advisory`: the OS did not stop the seat from opening an
  absolute path; the tier was `private-home`.
- `no isolation`: the seat ran in the operator's own harness home.
- `granted on purpose: …`, `extra harness arguments: …`, `environment
  passed through: …`: a door the plan opened; name it beside the seat's
  findings.
- `JOINED LATE in round N`: the seat heard the room before it first
  spoke, so its first post is a reply, not an independent position.
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
