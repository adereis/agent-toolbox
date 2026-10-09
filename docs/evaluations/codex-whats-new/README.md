# Codex release-reader comparison

This experiment adapts the Claude reader improvements in commit `79d9da2`
to Codex. The target is the supervised reader, not archive fetching or
baseline persistence. Provider calls use frozen reports with invented
configuration. They cannot change a real digest baseline.

## Evidence and prompts

- `cases.json` freezes the structured inputs. The five case Markdown files
  are rendered by the existing utility's `emit`, with the existing adapter
  providing tags and filtering. No private configuration is collected.
- The public inputs preserve the cached stable-release notes for
  0.159.0–0.159.3 and 0.160.0–0.160.1. The other inputs are explicitly
  synthetic. Public release dates and text are frozen, not refreshed live.
- `original-reader.md` is the original Codex reader (A).
- `candidate-reader.md` adds the Claude revision's completeness pass,
  stricter action criterion and layout, adapted to Codex inventory (B).
- `tuned-reader.md` resolves observed training errors about explicit
  configuration and hypothetical overrides, and integrates the instructions
  into one procedure (C).
- `final-reader.md` clarifies the difference between unmatched and hidden
  entries and requires preservation of the actual relation in a fix (D).
- `workflow.md` is a frozen copy of the shared workflow used in every arm.
  It is experiment evidence, not a second maintained workflow.
- `rubric.json` contains semantic checks frozen before answers were inspected.
  An independent evaluator audited the key against the reports before grading.
  The audit clarified that a leading action section satisfies the opening
  requirement, and omissions are named rather than quoted.

The first screen compares A and B on two training cases using Luna at
medium/high/xhigh and Terra at low/medium/high. C is then tested on the same
cases and efforts. Each screen uses one independent session per combination.
Finalists are repeated twice on three cases held out from model-based tuning.
Those cases test a separate public window, filtered counts and configuration
conditions, and a topic trace with misleading word matches.

The operator's final audit found displayed unmatched entries described as
unread in two answers. The evaluator then reviewed all sixty answers for
that coverage failure under a uniform interpretation of the existing counts
check. Original grades and the review are retained in `audit/`. D is replayed
twice on all five existing cases, adding ten final regression readings. These
are regression tests after tuning, not a new independent held-out set.

## Isolation and measurement

Convene resolves model families using the installed Codex catalog. Every
reading has an enforced bubblewrap jail, no tools, no grants, no inherited
conversation, no repository, and no access to other answers. Two reader
sessions run at a time. The question, exact utility arguments, complete report, shared
workflow and reader instructions are inlined into the prompt. The common
Convene wrapper requests a finished digest of about 900 words. Actual
model, effort, elapsed time, token usage, tool calls, MCP inventory and
compaction are taken from native receipts. Only sanitized receipt fields
are retained here.

`*-results.json` holds answers and receipts. `*-blind.json` hides model,
effort, prompt variant and timing. `*-key.json` maps shuffled labels back to
arms. The evaluator reads only blinded answers, reports, workflow and rubric.
`*-grades.json` gives every check, failed-check evidence, false action items
and unsupported impact claims. The operator audits the grades against the
reports before choosing a default.

Check scores measure this checklist, not a universal quality scale. Related
checks can penalize the same underlying error. Missing relevant fixes and
unsupported actions matter more to the choice than presentation. The operator
wrote the fixtures and prompts, including the held-out inputs. The independent
grader uses the operator's frozen answer key. These are small behavioral
comparisons, not a statistical guarantee or a blind test of the fixture author.

Token usage and elapsed time are observed. Dollar costs are not estimated:
the repository's dated price table does not contain the served Luna version.
The test does not measure real baseline writes, archive fetching, parent
supervision overhead, or end-to-end user latency.

## Reproduction

The retained cases can be replayed without fetching releases. Use a private
experiment directory under `~/tmp`. Copy `cases.json` and the five case
Markdown files into it before generating a plan. To regenerate them from a
complete cached public archive instead, run:

```bash
python3 docs/evaluations/codex-whats-new/prepare.py EXPERIMENT_DIR \
  --archive ~/.cache/agent-toolbox/codex-releases.json
```

To create a plan against frozen cases, pass the variant files and arm matrix:

```bash
python3 docs/evaluations/codex-whats-new/prepare.py EXPERIMENT_DIR \
  --variant A=docs/evaluations/codex-whats-new/original-reader.md \
  --variant C=docs/evaluations/codex-whats-new/tuned-reader.md \
  --arm A,luna,high --arm C,luna,high --arm C,terra,low \
  --split held --repeats 2
harnesses/claude-code/plugins/convene/bin/convene prepare \
  EXPERIMENT_DIR/held-plan.json --name YOUR_UNIQUE_RUN
harnesses/claude-code/plugins/convene/bin/convene run YOUR_UNIQUE_RUN
python3 docs/evaluations/codex-whats-new/collect.py EXPERIMENT_DIR RUN_PATH \
  --split held
```

For the final D replay, use `--variant D=.../final-reader.md`,
`--arm D,luna,high`, and `--split regression --repeats 2`. This selects all
five cases. Collect with `--split regression`. After writing complete grades,
run `summarize.py EXPERIMENT_DIR --split regression` to validate the receipts
and grading and produce the comparison table.

The plan and manifest freeze requested settings before provider calls. To
repeat the exact model versions after a catalog update, replace a family's
name in the arms with the served model ID in the retained receipts. Grade
the blinded answers before opening the key. Generated plans repeat substantial
input text and are omitted from the retained evidence; the generator and
manifests reproduce them. Convene keeps full native records in its private
state directory. The actual run names and final comparison are in `results.md`.
