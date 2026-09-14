# Scripts

Utilities for Claude Code. Run them from this checkout or use symlinks.
Keep the checkout intact: session recovery imports the shared
`tools/_session_resume.py` module, the release digest imports
`tools/_whats_new.py`, and the memory scripts need their sibling
`claude-memory-lib.sh`. Copying just an entry point is insufficient.

## claude-code-session-resume.py

Smart session resume with enriched history. For each recent session it shows the
session title (the AI-generated or renamed name from `/resume`), an arc of
prompts, and recognized git commit results from the session; `-v` adds edited files.

**Run it from a shell, not from inside Claude Code.** When you pick a session it
`exec`s `claude --resume <id>` in place, so it must be your terminal's foreground
process — that can't work as a slash command from within a running session
(and Claude Code's built-in `/resume` already covers the in-session case). A
shell alias is the natural home, e.g. an alias to this checkout's script or an installed symlink.

Colors are emitted only on a terminal, so `| less` and file redirects stay
clean (override with `--color always|never`, or honor `NO_COLOR`). Use `--list`
to print the history and exit without the interactive resume prompt.

```bash
# Sessions for the current project, newest last (interactive)
python3 harnesses/claude-code/scripts/claude-code-session-resume.py

# All projects, more entries, with edited files
python3 harnesses/claude-code/scripts/claude-code-session-resume.py --all -n 20 -v

# Just view, no prompt (pipe-friendly)
python3 harnesses/claude-code/scripts/claude-code-session-resume.py --list --all | less
```


`--claude-dir PATH` selects a separate Claude configuration directory;
otherwise the utility honors `CLAUDE_CONFIG_DIR` and then `~/.claude`. The
selected store is passed to the resumed child process. Cached index paths
never redirect reads into another profile. Sessions are ordered by transcript
file modification time, with the newest displayed last.

`--json` emits a machine-readable listing. Piped output never starts an
interactive session, even without `--list`. Counts must be positive. If the
recorded project directory is gone, use `--resume-cwd PATH` to choose its
replacement explicitly; the utility does not silently switch projects.

Malformed or incomplete JSONL records produce warnings while other records
remain usable. Custom titles and all text blocks in a user prompt are shown;
injected metadata is omitted. Edited files require a successful tool result.
Commit extraction is best effort for recognized shell calls; quiet commits
may have only a summary. Distinct observed SHAs remain visible even when
subjects match, including commits later replaced by an amend or reset.

To run it from anywhere, symlink it onto your `PATH`:

```bash
ln -s "$PWD/harnesses/claude-code/scripts/claude-code-session-resume.py" ~/bin/
```

## claude-code-whats-new.py

Reports the Claude Code releases published since its last digest, tagging each
changelog entry with the parts of your configuration it touches. It answers
"does this update affect me", and — with `--topic` — "when did this land".

It is the utility behind the `whats-new` skill, which supplies the judgement
this script deliberately withholds. Run it directly when you want the raw
tagged digest.

```bash
# Everything since the last digest, then record that you have read it
python3 harnesses/claude-code/scripts/claude-code-whats-new.py
python3 harnesses/claude-code/scripts/claude-code-whats-new.py --commit

# A fixed window; --relevant-only drops entries matching nothing here
python3 harnesses/claude-code/scripts/claude-code-whats-new.py --releases 10
python3 harnesses/claude-code/scripts/claude-code-whats-new.py --months 1 --relevant-only

# Trace a feature, passing every name it has carried
python3 harnesses/claude-code/scripts/claude-code-whats-new.py \
    --topic 'auto[- ]mode' --topic 'auto[- ]accept'
```

**Sources.** The changelog comes from `~/.claude/cache/changelog.md`, which is
byte-identical to the published `CHANGELOG.md`. That cache is read but never
written, and it is trusted only when it already contains the running release;
otherwise the published changelog is fetched and mirrored under
`~/.cache/agent-toolbox/`, so the hours between a release and the cache
catching up cost one download rather than one per run. `--offline` forbids the
network and says when it is falling back to a stale cache. Changelog headings
carry no dates, so `--days` and `--months` need release dates from the npm
packument; every other window works without them.

**Correlation.** The digest prints an `## Environment` block — settings,
permission rules, hooks, plugins, MCP servers, statusline, skills, agents,
terminal, and platform — and tags each bullet with the signals it matched.
`[-]` marks an entry no signal matched, which includes genuinely new features,
so knobs and commands that did not exist are tagged unconditionally rather
than disappearing under `--relevant-only`. Environment variables contribute
their names only; values may hold credentials and are never printed.

The terminal is identified from the variables it sets for itself
(`KITTY_WINDOW_ID`, `WEZTERM_PANE`, `GHOSTTY_RESOURCES_DIR`, and so on),
falling back to `TERM` only when none is present. This is what Claude Code
itself does, and it survives a wrapper or profile that rewrites `TERM`; when
`TERM` does not name the detected terminal the digest says so, because that
mismatch is a configuration choice with consequences. `tmux` and `screen` are
tagged separately. Terminal entries are never filtered, since one entry
commonly names several terminals that share the kitty keyboard protocol.

**What it withholds.** Entries owned by another host or platform (`[VSCode]`
without an IDE extension installed, `[Claude Tag]`, `Windows:` off Windows)
are removed, and the count is always reported with the reason; `--no-filter`
keeps them. A window wider than `--max-releases` (default 25) is refused
rather than truncated, because silently dropping the middle of a window and
then advancing the baseline past it would lose those releases for good.

**State.** The baseline lives in
`~/.local/state/agent-toolbox/claude-code-whats-new.json` and holds the last
five entries, so an earlier digest can be re-read with `--since`. Only
`--commit` moves it, and only for a window report.

## claude-memory — Memory Portability

A set of scripts for exporting, importing, and diffing Claude Code memories across machines. Claude Code memories are machine-local by design — these scripts make them portable.

### The Problem

Claude Code stores per-project memories at:

```
~/.claude/projects/<encoded-path>/memory/
```

Where `<encoded-path>` is the project's absolute filesystem path with every `/` replaced by `-`:

```
/home/alice/projects/foo  →  -home-alice-projects-foo
/home/bob/projects/foo    →  -home-bob-projects-foo
```

Different username, different home directory, different machine — different encoded path. Memories accumulated on one machine are invisible on another, even for the same project.

### The Solution

Three scripts that transform between machine-specific encoded paths and portable project slugs:

```
Disk (machine-specific)              Portable (machine-agnostic)
~/.claude/projects/                  ~/.claude/memory-sync/
  -home-alice-projects-foo/            foo/
    memory/                              memory/
      MEMORY.md          ←export→          MEMORY.md
      user_role.md       ←import→          user_role.md
  -home-alice/                         _global/
    memory/                              memory/
      feedback.md        ←export→          feedback.md
```

The portable directory can be synced between machines using any method: git, rsync, Syncthing, Dropbox, a USB stick — whatever works for your setup.

### claude-memory-export.sh

Exports memories from your local Claude Code data to the portable directory. Scans git repos under your projects directory, finds matching Claude memory directories, and copies new/changed files.

```bash
# Export all project memories
./harnesses/claude-code/scripts/claude-memory-export.sh

# Export with custom paths
./harnesses/claude-code/scripts/claude-memory-export.sh --dir ~/sync/claude-memories --projects-dir ~/code

# Skip work-specific projects
./harnesses/claude-code/scripts/claude-memory-export.sh --skip work/ --skip scratch/
```

**Output** (tab-separated):

| Status | Meaning |
|--------|---------|
| `NEW` | New file copied to portable directory |
| `COLLECTED` | Updated file copied (content changed since last export) |
| `SKIP` | File unchanged, skipped |

### claude-memory-import.sh

Imports memories from the portable directory to your local Claude Code data. Computes machine-specific encoded paths from `$HOME` and deploys each file.

```bash
# Import all memories
./harnesses/claude-code/scripts/claude-memory-import.sh

# Import from custom portable directory
./harnesses/claude-code/scripts/claude-memory-import.sh --dir ~/sync/claude-memories

# Skip projects you don't have locally
./harnesses/claude-code/scripts/claude-memory-import.sh --skip proprietary-work/
```

**Output** (tab-separated):

| Status | Meaning |
|--------|---------|
| `NEW` | New file deployed to Claude data directory |
| `DEPLOYED` | Updated file deployed (portable version was newer) |
| `SKIP` | File unchanged, skipped |

### claude-memory-status.sh

Shows sync status between your local memories and the portable directory. Two-way comparison: checks portable files against disk, and discovers local-only memories not yet exported.

```bash
# Show what's different
./harnesses/claude-code/scripts/claude-memory-status.sh

# Filter output to only differences
./harnesses/claude-code/scripts/claude-memory-status.sh | grep -v '^OK'
```

**Output** (tab-separated):

| Status | Meaning |
|--------|---------|
| `OK` | In sync |
| `DIFFERS` | Content differs between disk and portable |
| `NEW_LOCAL` | Exists on disk only (not yet exported) |
| `DELETED_LOCAL` | In portable directory but missing from disk |

**Exit codes:** 0 = in sync, 2 = differences found.

### Configuration

All three scripts accept the same flags and environment variables:

| Flag | Env Var | Default | Description |
|------|---------|---------|-------------|
| `--dir` | `CLAUDE_MEMORY_DIR` | `~/.claude/memory-sync` | Portable directory |
| `--projects-dir` | `CLAUDE_PROJECTS_DIR` | `~/projects` | Base projects directory |
| `--claude-dir` | `CLAUDE_DIR` | `~/.claude` | Claude Code data directory |
| `--skip` | — | — | Skip projects matching prefix (repeatable) |

CLI flags take precedence over environment variables.

### Typical Workflows

**Git-based sync** (recommended for versioned backup):

```bash
# First machine: export and push
cd ~/.claude/memory-sync  # or wherever --dir points
git init  # one-time setup
../path/to/claude-memory-export.sh
git add -A && git commit -m "export memories"
git push

# Second machine: pull and import
cd ~/.claude/memory-sync
git pull
../path/to/claude-memory-import.sh
```

**Rsync** (direct machine-to-machine):

```bash
# Export locally, rsync to remote
./claude-memory-export.sh
rsync -av ~/.claude/memory-sync/ remote:~/.claude/memory-sync/

# On remote: import
./claude-memory-import.sh
```

**Periodic sync** (check before sessions):

```bash
# Quick status check
./claude-memory-status.sh | grep -v '^OK'
# If differences found, export or import as needed
```

### Special Cases

**Global memories** — memories stored at `~/.claude/projects/<home-encoded>/memory/` (the "global" project scope) are mapped to the `_global/` slug in the portable directory. These are user-level memories not tied to any specific project.

**Nested projects** — projects like `~/projects/org/sub-project` produce the slug `org/sub-project`, preserving the directory hierarchy in the portable directory. Project discovery scans up to 4 levels deep under `--projects-dir` (e.g., `~/projects/org/team/sub-project` works, but deeper nesting won't be found).

**Skip prefixes** — use `--skip` to exclude projects by prefix. This is useful when some project memories contain context that shouldn't leave a particular machine (e.g., work-specific projects on a personal machine):

```bash
./claude-memory-import.sh --skip work/ --skip client-a/
```

---

## Reference: Claude Code Memory Layout

This section documents how Claude Code organizes data on disk. Understanding this layout is useful for building tools that interact with Claude Code's data, beyond what these scripts cover.

### Directory Structure

```
~/.claude/
├── settings.json                   # global settings, hooks, permissions
├── sessions/                       # session index
│   └── <numeric-id>.json           # pid, sessionId, cwd, startedAt
└── projects/
    └── <encoded-path>/
        ├── <uuid>.jsonl             # session transcripts
        ├── <uuid>/                  # session working data
        └── memory/
            ├── MEMORY.md            # memory index (loaded into context)
            └── *.md                 # individual memory files
```

### Path Encoding

The encoded path is computed as:

```bash
echo "$absolute_path" | tr '/' '-'
# /home/alice/projects/foo → -home-alice-projects-foo
```

**The encoding is lossy in reverse.** The `-` character is both the separator and a valid character in directory names. Given `-home-alice-projects-my-app`, you can't tell if the project is `my-app` or `my/app` without checking the actual filesystem. This is why the export script discovers projects by scanning git repos on disk (forward direction) rather than trying to decode existing Claude paths (reverse direction).

### Memory File Format

Individual memory files use YAML frontmatter:

```markdown
---
name: short-kebab-slug
description: One-line summary used for relevance matching
metadata:
  type: user|feedback|project|reference
---

Memory content in markdown. Can reference other memories with [[name]].
```

`MEMORY.md` is a plain index file (no frontmatter) loaded into every conversation. It contains one-line pointers to individual memory files.

### Session Transcripts

`.jsonl` files contain one JSON object per line. Most lines include a `cwd` field with the absolute project path. Other path references appear in tool call content (file paths, command output) — these are conversation history, not structural data.

The `sessions/<id>.json` index links sessions to projects via the `cwd` field, but most sessions are found through the project directory's `.jsonl` files directly.

---

## Advanced: Three-Way Sync with State Tracking

The `claude-memory-status` script performs a **two-way comparison**: it checks whether disk and portable directory contents match, but when they differ, it can only report `DIFFERS` — it can't tell you *which side changed*.

This section explains how to extend the scripts to a **three-way comparison** that can distinguish "updated remotely" from "edited locally" and detect true conflicts. This is provided as a reference for building more sophisticated sync tools on top of these scripts.

### The Limitation of Two-Way Comparison

With two-way comparison, when a file differs between disk and portable:

```
Disk: sha256=aaa...    Portable: sha256=bbb...
→ DIFFERS (but who changed?)
```

You don't know whether to import (overwrite disk) or export (overwrite portable). The user must inspect the diff and decide manually.

### The State-Tracking Approach

The idea: after each successful import, record the SHA-256 checksum of every deployed file in a **state file** on the local machine. This creates a third reference point — "what was the content the last time we synced?"

```
State file (~/.claude/memory-sync-state.json):
{
  "foo/memory/MEMORY.md": "ccc...",
  "foo/memory/user_role.md": "ddd..."
}
```

With three data points — disk checksum, state checksum (last-synced), and portable checksum — you can distinguish every case:

| Disk | State | Portable | Diagnosis |
|------|-------|----------|-----------|
| A | A | A | `OK` — all three match |
| A | A | B | `REMOTE_UPDATED` — portable changed since last sync, safe to import |
| B | A | A | `LOCAL_EDIT` — disk changed since last sync, safe to export |
| B | A | C | `CONFLICT` — both sides changed, needs manual resolution |
| — | A | A | `DELETED_LOCAL` — file removed from disk since last sync |
| A | A | — | `DELETED_REMOTE` — file removed from portable since last sync |
| A | — | — | `NEW_LOCAL` — new file on disk, never synced |
| — | — | A | `NEW_REMOTE` — new file in portable, never synced |

### Implementing State Tracking

To add state tracking to the import script:

1. **After deploying each file**, record `slug/memory/filename → sha256` in a JSON state file.
2. **In the status script**, load the state file and perform three-way comparison instead of two-way.
3. **The state file is machine-local** — it lives on each machine and is never synced. It represents "what this machine last received."

A minimal state file implementation:

```bash
STATE_FILE="${CLAUDE_DIR}/memory-sync-state.json"

# Record after deploy (append to a temp file, merge at end)
record_state() {
    local key="$1" sha="$2"
    # Use jq to merge into existing state
    jq --arg k "$key" --arg v "$sha" '.[$k] = $v' "$STATE_FILE" > "$STATE_FILE.tmp"
    mv "$STATE_FILE.tmp" "$STATE_FILE"
}

# Read during status
read_state() {
    local key="$1"
    jq -r --arg k "$key" '.[$k] // ""' "$STATE_FILE"
}
```

### Trade-offs

Three-way sync adds complexity:

- **State file maintenance**: must be updated atomically on every import
- **State corruption**: if the state file is lost or corrupted, all files show as conflicts until re-synced
- **Recovery**: a "reset state" command that re-derives state from current disk+portable is needed for robustness

The two-way approach in these scripts is intentionally simple. For most users syncing memories across 2–3 machines, manually resolving the occasional `DIFFERS` is faster than maintaining state-tracking infrastructure. The three-way approach becomes worthwhile when you have many machines, frequent edits, or want fully automated sync.
