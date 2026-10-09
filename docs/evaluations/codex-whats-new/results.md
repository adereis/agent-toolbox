# Release-reader results

Evaluation date: 2026-10-08. Source checkout: `79d9da2`. Tested on Linux.

The selected reader is D on Luna at high effort. Its ten final replay answers
passed 156/164 checks, with zero false actions and zero unsupported impact
claims. Mean worker time was 28.0 seconds across all five cases. No answer
repeated the shown-versus-hidden coverage error. Both public training answers
preserved the credential-isolation meaning. Relevant-fix omissions remain,
so the parent still checks the draft before recording a baseline.

## Initial held-out comparison

Each arm had two independent readings on three reports excluded from the
training runs. C was the strongest prompt in this comparison. D was then
derived from C after an operator audit. D's replay is reported separately;
it is not another independent held-out evaluation.

| Prompt | Model | Effort | Passed checks | Mean seconds | False actions | False impact claims |
|---|---|---|---:|---:|---:|---:|
| A | luna | high | 72/88 | 18.4 | 0 | 2 |
| B | luna | high | 82/88 | 18.8 | 0 | 0 |
| B | terra | high | 80/88 | 47.2 | 0 | 0 |
| C | luna | high | 85/88 | 21.4 | 0 | 0 |

The original reader made two unsupported setup claims: it inferred plugin
activation from presence, and inferred fullscreen visibility from a configured
status line. The revised readers avoided those claims. The simpler revision
B was strongest in training, but C recalled more relevant changes here.

## Training comparisons

One reading per arm on each of two inputs. A is the original reader. B appends
the adapted Claude improvements. C integrates the instructions and explicitly
distinguishes recorded feature values from runtime evidence. These small
screens select candidates; they do not establish repeatability.

| Prompt | Model | Effort | Passed checks | Mean seconds | False actions | False impact claims |
|---|---|---|---:|---:|---:|---:|
| A | luna | high | 28/38 | 22.1 | 1 | 0 |
| A | luna | medium | 28/38 | 11.5 | 0 | 1 |
| A | luna | xhigh | 31/38 | 47.2 | 1 | 0 |
| A | terra | high | 33/38 | 76.1 | 1 | 0 |
| A | terra | low | 34/38 | 36.2 | 0 | 0 |
| A | terra | medium | 27/38 | 56.1 | 1 | 0 |
| B | luna | high | 36/38 | 32.8 | 0 | 0 |
| B | luna | medium | 30/38 | 10.2 | 0 | 0 |
| B | luna | xhigh | 36/38 | 80.9 | 0 | 0 |
| B | terra | high | 38/38 | 127.2 | 0 | 0 |
| B | terra | low | 33/38 | 24.5 | 0 | 0 |
| B | terra | medium | 30/38 | 52.6 | 2 | 1 |
| C | luna | high | 32/38 | 31.7 | 0 | 1 |
| C | luna | medium | 27/38 | 10.8 | 2 | 0 |
| C | luna | xhigh | 34/38 | 77.6 | 0 | 0 |
| C | terra | high | 35/38 | 150.8 | 0 | 1 |
| C | terra | low | 33/38 | 59.3 | 1 | 0 |
| C | terra | medium | 35/38 | 61.8 | 0 | 0 |

B on Luna high improved from 28/38 to 36/38 checks. Its two misses were
skill-catalog stability and model/access-program preservation during compaction.
Extra-high Luna passed the same total at a longer mean response time, with
mean output usage rising from 2,924 to 8,483 tokens. Medium effort missed more
conditions or fixes. B on Terra high passed every training check, but averaged
127.2 seconds. Its held-out result did not beat Luna high.

C settled the explicit memory migration more reliably across efforts. It also
introduced semantic errors in summarizing MCP credential boundaries and resource
URI preservation. These failures motivated both a targeted fidelity instruction
and an explicit parent check. Higher reasoning effort did not consistently
outperform a better prompt, and the best training score did not predict the
best held-out result.

## Operator audit and final replay

The operator read all six C held-out answers and the public training draft
against the reports. One held-out answer claimed 48 unmatched entries were
unread despite zero hidden entries. The evaluator reviewed all sixty blinded
answers for the same coverage failure. Two complete grades changed under a
uniform interpretation of the existing counts check. Original grades and the
interpretation caveat are retained in `audit/`. All tables here use the audited
grades. Availability does not prove attention; an admission of not reading
shown material still fails the complete-reading requirement.

D changes two passages in C. It says that only actually hidden entries were
unavailable, and requires reading shown unmatched bullets. It also preserves
the relation in a fix, with credential boundaries as a concrete example. The
parent procedure now checks changed meanings, hidden-entry claims and omissions.

D was replayed twice on all five existing reports. It passed **156/164 (95%)**
checks. On the three formerly held-out reports alone it passed **86/88**,
but those reports had now informed the coverage correction. This is regression
evidence, not a fresh generalization score. All ten answers avoided the targeted
unread-coverage confusion, credential-boundary meaning loss and invented actions.

The eight remaining failed checks were omissions: two supplied Windows withheld
breakdowns, two compaction-preservation mentions, and one each for SQLite
reliability, content-filter guidance, skill-catalog stability and resource-URI
preservation. Some checks combine related requirements; see the individual
grades for the exact accounting. The parent must still catch omissions.

The final reader is byte-identical to `final-reader.md`, which produced this
replay. The existing installation directory link exposes it without reinstalling.

## Measurement limits

The operator and independent evaluator are separate Sol instances. The operator
authored the prompts, fixtures and answer key. The grader saw the reports,
rubric and shuffled answers, but not model, effort, arm keys or prompt text.
The tuning stage was known; final-comparison arms were mixed. This reduces
direct author grading bias, but is not independent validation of the answer key.
Only five distinct reports were used. Two repetitions cannot establish stable
rankings across releases or hosts. The 900-word Convene wrapper and tools-free
inlined input differ from a normal parent session. The measured times exclude
collection and parent supervision. Dollar costs are not estimated because the
dated repository price table lacks the served Luna version.

## Native records and validation

The served models were `gpt-6-luna` and `gpt-5.6-terra`. Every one of the seventy
native receipts attested enforced isolation, zero tools, empty MCP inventory,
intact inputs, no compaction and no red flags. No real digest baseline was
collected or changed. The reports use public notes and invented configuration.

- `codex-digest-tune-train-20261008`: 24 initial A/B readings.
- `codex-digest-tune-c-20261008`: 12 readings of C.
- `codex-digest-tune-held-20261008`: 24 final-comparison readings.
- `codex-digest-tune-final-20261008`: 10 D regression readings.

Full records remain in private Convene state. Retained `*-results.json` files
contain answers and sanitized measurements. Manifests, keys and grades make the
comparison auditable without copying credentials, private homes or native logs.
This validates the reader behavior, not live archive fetching, baseline writes
or the entire installed skill invocation.

Final validation passed: `./tests/run.sh` (383 Python tests and all shell
suites), skill frontmatter validation, compilation of the three replay
scripts, exact deployed-reader/snapshot hash comparison and `git diff --check`.
