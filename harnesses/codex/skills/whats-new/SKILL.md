---
name: whats-new
description: Explain recent Codex CLI releases against local configuration, or trace when a CLI feature or fix appeared. Use for update digests, upgrade impact, and release-history questions about Codex CLI.
---

## Supervised release reading

The parent collects evidence and owns the baseline. Delegate changelog
interpretation to a fresh Luna subagent with **reasoning effort high**.
Select the newest Luna family member in the harness's available model
catalog and explicitly set both model and effort on the spawn. Do not
inherit the parent's conversation or let its model stand in for Luna.
If the harness cannot spawn with those settings, report that limitation
instead of silently processing the changelog on another model.

Read the shared [release digest workflow](references/workflow.md).
The subagent follows the [reader procedure](references/reader.md) and that
same workflow. Give it the user's complete question, the utility report,
the exact utility arguments, and any explicit session facts the user
supplied. It cannot infer the conversation, selected profile, or CLI
overrides from the parent's state.

Collect the report before spawning. Save output in a private directory
made with `mktemp -d "$HOME/tmp/codex-digest.XXXXXXXX"`; create `~/tmp`
first if needed. Reuse the exact returned path across shell calls rather
than a shared filename. Read the entire report in complete line ranges.
Do not discard untagged entries or truncate long bullets. The worker may
read only its supplied evidence and procedures; it must not inspect user
configuration, run commands from release notes, or advance state.

Check the returned digest against the report before relaying it. Every
impact claim needs both release evidence and a matching configuration
condition. Inventory alone does not establish runtime activation. Look for
missed new capabilities or fixes for enabled settings, repeated entries,
unsupported action items, changed meanings in paraphrases, and incorrect
counts or claims about which entries were hidden. Have Luna revise omissions
and unsupported claims. When a missing condition can be settled,
the parent makes one narrow check per question under the shared workflow's
rules and passes only that answer back. Otherwise retain it under Could not check.

## Collecting evidence

Run `~/.agents/scripts/codex-whats-new.py`, or
`harnesses/codex/scripts/codex-whats-new.py` from the checkout. Project-scope
installations put the script under `<project>/.agents/scripts/`. It requires
Linux and Python 3.11+. Keep the checkout intact for its shared imports.
Online fetching also needs GitHub CLI authenticated with
`gh auth login --hostname github.com`.

| Request | Arguments |
|---|---|
| Changes since the last digest | no window argument |
| Recent releases | `--releases N` |
| A time span | `--days N` or `--months N` (30-day periods) |
| Since a version | `--since VERSION` (exclusive) |
| Feature history | `--topic PATTERN`, repeated for alternative names |
| Re-read a digest | `--since VERSION --through VERSION`, using the baseline history |

Pass `--project PATH` for the project being discussed. Pass `--profile NAME`
when the user's selected profile is known. The utility cannot infer a running
session's profile or CLI overrides. Read the environment's limitations before
claiming a setting is active. Hook events and installed skills are an
inventory; their presence does not prove they are trusted or enabled.

The source is the public GitHub release archive. Cursor pagination avoids
the REST API's 1,000-record limit. Only stable CLI
releases are included. SDKs and prereleases are excluded. Topic searches cover
the available archive without platform filtering. Describe the first match
as evidence from those notes, not proof that no earlier implementation existed.
Always disclose offline or stale-snapshot notices and archive coverage.
For topic history, add `--limit 0` so older matches needed to explain the
feature's introduction and later changes are not hidden. A first match is
the earliest note matching those names in this archive, not proof of the
feature's first implementation. If there are no matches, say so.

Use `--relevant-only` if a window exceeds the limit. New features remain
tagged even when there is no existing setting for them. Both withheld and
unmatched counts appear in every window report. `--json` works in both modes.
Disclose the hidden unmatched count when using `--relevant-only`; those
entries were not read. An empty window means no releases in this snapshot's
window, not that the installed CLI is current.

## Recording the reviewed window

After presenting the checked window digest, repeat its arguments with
`--through NEWEST_PRESENTED_VERSION --commit`. The ceiling keeps a newly
published release from being marked read before it was discussed. Never use
`--commit` with `--topic`. This flag records digest state; it does not create
a Git commit.

If the harness can only deliver the report as its final message, record the
baseline as the last tool step after supervision, then deliver the checked
report. This is the same delivery exception as Claude's forked skill: the
baseline moves just before the user reads it. State the previous baseline
and the ceiling in the report so that window can be read again. For a first
digest, give its actual `--since`/`--releases`/time-window arguments and
`--through` ceiling instead. Never record an incomplete or failed reading,
an unreviewed worker answer, or a window with no releases. A state-write
failure must be visible; report the digest with the baseline unchanged.
Keep diagnostics on standard error when saving a second utility result.
Clean up the private report directory when finished.

State lives under `$XDG_STATE_HOME/agent-toolbox/codex-whats-new/`, defaulting
to `~/.local/state/agent-toolbox/codex-whats-new/`. Each Codex home, project,
and profile has a separate file. Its path is printed in the report. The file
retains five previous baselines. The complete public archive is cached under
`$XDG_CACHE_HOME/agent-toolbox/`, defaulting to `~/.cache/agent-toolbox/`.
Use `--refresh` to bypass the 24-hour cache, or `--offline` to forbid fetching.
