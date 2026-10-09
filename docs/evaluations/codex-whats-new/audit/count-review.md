# Unmatched-entry coverage audit

Reviewed all 60 blinded answers against the unchanged rubric and their frozen reports: 24 original training answers, 12 separate tuning answers, and 24 held-out answers. Topic answers have no common-window counts check and were left unchanged. No keys, manifests, prompts, or unblinded results were inspected.

The pre-review complete grade arrays are preserved byte-for-byte in `pre-count-review/train-grades.json`, `pre-count-review/tuning-train-grades.json`, and `pre-count-review/held-grades.json`.

## Changed grades

Only `common-window.counts` changed, from true to false, for these two answers. All other checks and separate action/impact arrays were preserved.

| Namespace | Blind label | Frozen report | Source counts | Answer evidence |
|---|---|---|---|---|
| tuning | R05 | train-public.md | Unmatched: 78; Not shown: 0 | “**78** entries matched no configuration signal; **0** unmatched entries were hidden, and those unmatched entries were not read.” |
| held | R21 | held-public.md | Unmatched: 48; Not shown: 0 | “**48** entries matched no configuration signal; **0** unmatched entries were hidden, and the 48 unmatched entries were not read.” |

## Already failing or unaffected

The separate tuning answers R04, R08, and R11 already fail counts for conflating unmatched entries with unavailable or unread material despite zero hidden entries. The held-out answer R14 already fails counts for reporting zero hidden entries after correctly acknowledging four not shown. No additional grade change was needed for those answers.

The original training set has no additional shown-but-unread assertions. “Not discussed” was not treated as “not shown” or “not read.” Reports with four genuinely hidden unmatched entries were checked against that source count; accurately calling those four unavailable or unread was allowed.

## Interpretation concern

`Not shown: 0` establishes availability, not the reader’s attention. An answer can truthfully admit that it did not read displayed entries. That admission still fails the requested coverage audit, but the unread-only statements above are not independent proof that the utility hid those entries. These two updates therefore use the operator’s stated coverage interpretation of the existing counts check. They do not assert a new hidden count or alter the rubric.

The audit did not turn an unread-coverage admission into an unsupported action or setup-impact claim. Those separate arrays remain unchanged.
