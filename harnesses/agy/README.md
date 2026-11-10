# Antigravity (`agy`) Harness Integration

Integrations and skills for Google Antigravity (`agy`).

## Available components

| Component | Type | Destination | Documentation |
|-----------|------|-------------|---------------|
| `whats-new` | Skill | `skills/whats-new` | [Release digest skill](skills/whats-new/SKILL.md) |
| `agy-whats-new.py` | Script | `scripts/agy-whats-new.py` | Below |
| `convene` | Command | `~/.local/bin/convene` | [Convene plugin](../claude-code/plugins/convene/README.md) |
| `global-baseline.md` | Instruction module | `instructions/global-baseline.md` | Below |

## Installation

Install components using `tools/install.py`:

```bash
# Preview links (dry-run)
python3 tools/install.py --harness agy --scope user --component skills --component scripts

# Apply user-scoped links
python3 tools/install.py --harness agy --scope user --component skills --component scripts --apply
```

* **User scope** installs into `~/.gemini/config/`.
* **Project scope** installs into `<project>/.agents/`.

## Global baseline

The `instructions` component links the shared policy modules under
`~/.gemini/config/instructions/`, where they do nothing until adopted:

```bash
python3 tools/install.py --harness agy --scope user --component instructions --apply
```

Then follow [the adoption prompt](../../prompts/adopt-baseline.md). It adds an
include of `config/instructions/global-baseline.md` to
`~/.gemini/GEMINI.md` and an Antigravity section that tells the model how to
find its own model id, which Antigravity reports only by display name.
Antigravity resolves a relative include against `~/.gemini/`, and an include
it cannot resolve is silent, so the prompt ends by checking that the model
sees the module.

Over SSH, Antigravity stores and looks for its login in a file rather than in
the login keyring, so a CLI that was signed in at the desktop reports
`You are not logged into Antigravity.` Sign in once from the SSH session by
running `agy` without arguments.

## Release digest (`agy-whats-new.py`)

Correlates Antigravity CLI releases with local machine configuration and environment.
Bullets are tagged with matching configuration signals (such as `auto-mode`, `sandbox`,
`plugins`, `skills`, `rules`, `hooks`, `mcp`, `subagents`, `telemetry`), while entries
belonging exclusively to other operating systems or environments are withheld.

### CLI Usage

```bash
# Report releases published since your last recorded baseline
python3 harnesses/agy/scripts/agy-whats-new.py

# Report the last 3 releases
python3 harnesses/agy/scripts/agy-whats-new.py --releases 3

# Report releases since an explicit version
python3 harnesses/agy/scripts/agy-whats-new.py --since 1.4.0

# Search changelog for a feature across all releases
python3 harnesses/agy/scripts/agy-whats-new.py --topic "auto-mode" --topic "accept-edits"

# Record the baseline after reviewing a window
python3 harnesses/agy/scripts/agy-whats-new.py --since 1.3.0 --through 1.4.2 --commit
```

### Options

* `--releases N`: The N newest releases.
* `--since VERSION`: Exclusive baseline version.
* `--through VERSION`: Inclusive ceiling version (pins the window for `--commit`).
* `--commit`: Records the newest reported version as baseline in state.
* `--topic PATTERN`: Searches all notes for regex patterns (repeatable).
* `--relevant-only`: Shows only bullets matching active configuration signals.
* `--no-filter`: Disables platform filtering (includes notes for other operating systems).
* `--changelog FILE`: Reads an explicit changelog file instead of querying `agy changelog`.
* `--offline`: Forbids executing subprocesses if a cached changelog exists.
* `--json`: Machine-readable JSON output.
