# Startup condition and crash-fix regression

The current fixture preparer adds a `startup` case alongside the original
four interactive reports. See [IT-14](../../../tests/INTERACTIVE.md#it-14-codex-release-digest-with-supervised-luna)
for preparation and the assessment criteria. This case is separate from
the frozen five-case comparison and does not change its scores.

The [fixture](../../../tests/fixtures/codex-whats-new/startup-releases.json)
uses public [0.162.1 fix wording](https://github.com/openai/codex/releases/tag/rust-v0.162.1)
with a fictitious version and date. All configuration is synthetic. The
report contains two unmatched entries, both visible, with none withheld.

The startup note distinguishes two conditions. The old failure arose when
a running background server's feature settings differed from CLI defaults.
The new compatibility check applies only to explicit command-line feature
overrides. A digest must not turn that new check into a prerequisite for
the old bug. It must also retain crash prevention in the multiline-question
fix, rather than reducing it to text preservation.

## Observed reading

A fresh native subagent read this case on 2026-10-15 using `gpt-6-luna`
with explicit high effort and no inherited conversation. It received the
question, exact utility arguments, complete report, current reader procedure
and shared workflow. It was instructed to use only those resources and not
to write a baseline. This was one reading, not a model comparison or an
enforced-isolation Convene run.

The first answer omitted crash prevention. It described only preserved
line breaks and hyperlink destinations. It also used the configured
`multi_agent` flag to put the server fix under Fixed for you, although the
report did not establish server usage. It preserved the distinction between
the old mismatch and the new override check. Its counts were correct.

Parent review requested the missing crash fix and conditional server scope.
The revised answer included crash prevention and said the report did not
establish background-server usage. It retained the old/new condition
distinction and the exact counts. The revised answer is supervised
correction, not a second independent pass.

No reader prompt changed. Both report preparations left every synthetic
baseline absent. No real digest baseline was read or changed by this
evaluation. The initial omission supports retaining parent review; this
single case does not establish a general reader success rate.
