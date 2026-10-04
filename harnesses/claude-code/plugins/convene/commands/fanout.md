---
description: Fan a brief out to N blind seats that each implement it in their own worktree; read the attempts sealed, judge, then unseal
argument-hint: "discuss | [seats=N] [seat=harness/model ...] [--persona ID ...] [judge=ID] [synthesizer=ID] [grant=...] brief text"
disable-model-invocation: true
---

Run a fanout with the convene engine at `${CLAUDE_PLUGIN_ROOT}/bin/convene`.
Read the operator procedure first: `${CLAUDE_PLUGIN_ROOT}/skills/convene/SKILL.md`,
especially its section on reading a sealed round.

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
- `seats=N` or `seat=harness/model` (repeatable) declares the attempts;
  with neither, use the template's three, on two harnesses when both are
  installed;
- `--persona ID` (repeatable) assigns personas in order;
- `judge=ID` adds a seat of that id that judges the attempts instead of
  you (`[judgment] by = ID`). It sees only the lettered attempts, never the
  plan, so it is blind where you are not. Leave it out to judge yourself;
- `synthesizer=ID` adds a seat of that id that synthesizes instead of
  you (`[synthesis] by = ID`); leave it out to synthesize yourself;
- `grant=...` opens doors for every seat (see the skill);
- everything else is the brief: what to implement and how it will be
  verified.

Then:

1. `${CLAUDE_PLUGIN_ROOT}/bin/convene doctor --no-probes`.
2. Write a plan from `${CLAUDE_PLUGIN_ROOT}/templates/fanout.toml` into a
   directory under the user's home (`~/tmp/convene/` when it exists,
   otherwise `mktemp -d` under `$HOME`), with the brief and seats
   resolved.
3. `${CLAUDE_PLUGIN_ROOT}/bin/convene prepare PLAN`, then
   `${CLAUDE_PLUGIN_ROOT}/bin/convene run NAME`. N implementations take
   a while; say so.
4. `convene status NAME`. A held round is a quota stop: name the seat and
   the reset time; `continue`, `promote`, `run` as the skill describes.
5. With a judge seat, `run` has already sealed round 1 and played the
   judge's round, and its post is on file as `sealed/r001/judgment.md`.
   Read it; do not write or edit a judgment of your own. Without one,
   `convene seal NAME`, then read every letter under `sealed/r001/` in the
   run directory: `post.md`, `report.md`, `changes.patch`. Write your
   judgment to `sealed/r001/judgment.md`: which attempt to take, what to
   change in it first, what each other attempt got right, all by letter.
   Either way, do not run `board`, `usage` or `export`; they are withheld
   and say so.
6. `convene unseal NAME` prints who judged and the key. Report the
   judgment first, as written, then who judged, then the key, then the
   receipts and every red flag verbatim. A view of your own after a
   judge's goes last, labeled as written with the key in hand. With a
   synthesizer seat, the synthesis is its post on the board; read it after
   the judgment, never before.
7. `convene export NAME DIR`, then offer `convene prune NAME`.
