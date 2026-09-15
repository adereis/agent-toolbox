---
name: whats-new
description: Explain recent Codex CLI releases against local configuration, or trace when a CLI feature or fix appeared. Use for update digests, upgrade impact, and release-history questions about Codex CLI.
---

Follow the shared [release digest workflow](references/workflow.md).
In an uninstalled Agent Toolbox checkout, read `skills/whats-new/SKILL.md`
from the repository root instead.

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

Use `--relevant-only` if a window exceeds the limit. New features remain
tagged even when there is no existing setting for them. Both withheld and
unmatched counts appear in every window report. `--json` works in both modes.

After presenting a window digest, repeat its arguments with
`--through NEWEST_PRESENTED_VERSION --commit`. The ceiling keeps a newly
published release from being marked read before it was discussed. Never use
`--commit` with `--topic`. This flag records digest state; it does not create
a Git commit.

State lives under `$XDG_STATE_HOME/agent-toolbox/codex-whats-new/`, defaulting
to `~/.local/state/agent-toolbox/codex-whats-new/`. Each Codex home, project,
and profile has a separate file. Its path is printed in the report. The file
retains five previous baselines. The complete public archive is cached under
`$XDG_CACHE_HOME/agent-toolbox/`, defaulting to `~/.cache/agent-toolbox/`.
Use `--refresh` to bypass the 24-hour cache, or `--offline` to forbid fetching.
