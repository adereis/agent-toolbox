---
description: Convene a room of seats to discuss a feature over rounds on a shared board, draft it in a worktree, critique and revise it
argument-hint: "discuss | [seat=harness/model ...] [--persona ID ...] [rounds=N] [grant=web,mcp] brief text"
disable-model-invocation: true
---

Run a room with the convene engine at `${CLAUDE_PLUGIN_ROOT}/bin/convene`.
Read the operator procedure first: `${CLAUDE_PLUGIN_ROOT}/skills/convene/SKILL.md`.

Do not start a run on your own reading of a partial invocation. Follow the
operator procedure's step 4: state the plan — range or brief, every seat as
`harness/model` with its persona, the isolation tier each resolves to, the
tool set, any grants, the round budget — then ask and wait. Run
immediately only when the invocation already names both the work and the
seats. A bare invocation, or one that opens with `discuss`, is a request to
design the run together: propose, take corrections, run once accepted.

Arguments: `$ARGUMENTS`

Interpret them as:

- a leading `discuss` is not part of the brief: it asks for the plan in
  conversation, so propose one and run nothing until accepted;
- `seat=harness/model` (repeatable) declares seats in order; the last
  seat declared is the drafter unless a seat is named `drafter`. With no
  seats, use the template's three (architect, skeptic on the other
  installed harness, drafter);
- `--persona ID` (repeatable) assigns personas in order;
- `rounds=N` sets the total; the template's four phases (discuss, draft,
  critique, revise) are kept and the extra rounds go to `discuss`;
- `grant=...` opens doors for every seat (see the skill);
- everything else is the brief: the feature to design and draft.

Then:

1. `${CLAUDE_PLUGIN_ROOT}/bin/convene doctor --no-probes`.
2. Write a plan from `${CLAUDE_PLUGIN_ROOT}/templates/room.toml` into a
   directory under the user's home (`~/tmp/convene/` when it exists,
   otherwise `mktemp -d` under `$HOME`), with the brief and seats
   resolved. The drafter keeps `tools = "write"` and
   `workspace = "worktree"`.
3. `${CLAUDE_PLUGIN_ROOT}/bin/convene prepare PLAN`, then
   `${CLAUDE_PLUGIN_ROOT}/bin/convene run NAME`. A room of three seats
   over four rounds takes a while; say so.
4. `convene status NAME`. A held round is a provider quota stop: name
   the seat and the reset time, and offer `convene continue NAME SEAT`
   once it resets, then `convene promote NAME N` and `convene run NAME`
   for the remaining rounds.
5. `convene board NAME` and read every round. The drafter's
   `changes.patch` is on the board under its post. Synthesize following
   the skill's `references/synthesis.md`: the design the room settled
   on, the disagreements and your ruling, and the patch's state after
   the revision.
6. `convene export NAME DIR`, write `synthesis.md` there, report the
   receipts and every red flag verbatim, and offer `convene prune NAME`
   to remove the worktree and private homes once the user has what they
   need. The patch stays in the export.
