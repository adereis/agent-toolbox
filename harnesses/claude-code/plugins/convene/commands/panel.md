---
description: Convene a multi-seat review panel over a commit range, on independent native CLI sessions, and synthesize the board
argument-hint: "discuss | <A..B | HEAD> [seat=harness/model ...] [--persona ID ...] [grant=web,mcp] [tools=read|write|research] [brief text]"
disable-model-invocation: true
---

Run a review panel with the convene engine at `${CLAUDE_PLUGIN_ROOT}/bin/convene`.
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

- a leading `discuss` is not a range and not a brief: it asks for the
  plan in conversation, so propose one and run nothing until accepted;
- the first token is otherwise the range: `A..B`, or `HEAD` for the
  uncommitted working tree; with no range, propose `HEAD~1..HEAD` rather
  than assuming it;
- `seat=harness/model` (repeatable) declares seats in order; with none,
  use the template's three seats and put at least one on a harness other
  than the one you run on when both are installed (`convene doctor`
  says which are);
- `--persona ID` (repeatable) assigns personas to the seats in order;
  `convene personas list` prints the catalog;
- `grant=web,mcp,settings,instructions,hooks` opens those doors for
  every seat (`prepare --grant`); `tools=write|research` widens the tool
  set. Open a door only when the user asked for it or a seat cannot do
  its job without it, and say so in the report;
- anything else is the brief, appended to the template's default brief.

Then:

1. `${CLAUDE_PLUGIN_ROOT}/bin/convene doctor --no-probes`. Stop and report
   if a harness a seat needs is missing or has no credentials.
2. Write a plan file from `${CLAUDE_PLUGIN_ROOT}/templates/panel.toml`
   into a directory under the user's home (`~/tmp/convene/` when it
   exists, otherwise `mktemp -d` under `$HOME`), with the seats, personas
   and brief resolved. The run keeps its own frozen copy, so the file's
   location does not matter afterwards.
3. `${CLAUDE_PLUGIN_ROOT}/bin/convene prepare PLAN --range RANGE`, then
   `${CLAUDE_PLUGIN_ROOT}/bin/convene run NAME`. Seats run one at a time
   unless the plan says otherwise; a run of three seats takes minutes.
4. `convene status NAME`. A held round means a provider quota stop; tell
   the user which seat and when it resets, and stop there.
5. `convene board NAME` and synthesize following the skill's
   `references/synthesis.md`. Cite seats by id.
6. `convene export NAME DIR` into a directory the user names (default:
   a sibling of the plan file), write `synthesis.md` there, and report
   the receipts: served model per seat, isolation tier, tool calls, and
   every red flag verbatim. Never soften a red flag.
