# Scripts

Utilities for Claude Code. Run them from this checkout or use symlinks.
Keep the checkout intact: session recovery imports the shared
`tools/_session_resume.py` module and the release digest imports
`tools/_whats_new.py`. Copying just those entry points is insufficient;
`claude-memory-sync.py` is self-contained.

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
otherwise the utility honors `CLAUDE_CONFIG_DIR` and then `~/.claude`. A store
you chose explicitly, by either of those two means, is passed to the resumed
child process so it cannot stray into another profile. The default store is
not, because `CLAUDE_CONFIG_DIR` also moves the `.claude.json` configuration
file, which lives beside `~/.claude` rather than inside it; exporting the
default session directory would point the child at a configuration path that
has never existed and start it on a blank profile. Cached index paths never
redirect reads into another profile. Sessions are ordered by transcript
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

To run it from anywhere, install the `commands` component. It links the
script into `~/.local/bin` as `claude-code-session-resume`, matching the
name its own usage line prints:

```bash
python3 tools/install.py --harness claude-code --scope user \
  --component commands --apply
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
than disappearing under `--relevant-only`. The `## Unmatched` line states how
many `[-]` entries the window holds, beside the withheld count and before the
first bullet, even when `--relevant-only` hides them; `--json` carries the
same number as `unmatched`. Environment variables contribute
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

## claude-memory-sync — Memory Portability

Syncs Claude Code memories between machines through a portable directory,
propagating edits **and deletions** in both directions.

### The Problem

Claude Code stores per-project memories at
`~/.claude/projects/<encoded-path>/memory/`, where `<encoded-path>` is the
directory a session was launched from with every character that is not a
letter or digit replaced by `-`:

```
/home/alice/projects/foo     →  -home-alice-projects-foo
/home/bob/projects/my_app.v2 →  -home-bob-projects-my-app-v2
```

A different home directory gives a different encoded path, so memories
accumulated on one machine are invisible on another, even for the same
project.

### The Portable Layout

`claude-memory-sync` maps each store to a machine-agnostic slug, the
project's path relative to `--projects-dir`:

```
Disk (machine-specific)              Portable (machine-agnostic)
~/.claude/projects/                  ~/.claude/memory-sync/
  -home-alice-projects-foo/            foo/
    memory/                              memory/
      MEMORY.md                            MEMORY.md
      user_role.md          ⇄              user_role.md
  -home-alice/                           .deleted/        (tombstones)
    memory/                          _global/
      feedback.md           ⇄          memory/
                                         feedback.md
```

Carry the portable directory between machines with anything: git, rsync,
Syncthing, Dropbox. Memories under the home directory itself (the global
scope) use the `_global` slug. Nested projects keep their hierarchy
(`org/sub-project`); discovery scans three levels under `--projects-dir` and
follows symlinked repos.

### Why Three-Way

Comparing only the disk and the portable copy cannot tell "deleted here"
from "added elsewhere", or "edited here" from "edited elsewhere". A two-way
tool therefore restores every deleted memory on the next sync, and the
last writer silently wins an edit race. `claude-memory-sync` keeps two more
records:

- **Base** (per machine, never shared): a copy of each file as this machine
  last synced it, under
  `$XDG_STATE_HOME/agent-toolbox/claude-memory/<key>/base/`, keyed by the
  portable directory so two portable directories never share a base.
- **Tombstones** (shared): `<slug>/memory/.deleted/<file>` lists the SHA-256
  of each deleted version. One file per deleted memory, so two machines
  deleting different memories never touch the same file and git or
  Syncthing merge them cleanly.

| Disk | Base | Portable | Status | `apply` does |
|------|------|----------|--------|--------------|
| A | — | — | `NEW_LOCAL` | export |
| — | — | A | `NEW_REMOTE` | import |
| A′ | A | A | `LOCAL_EDIT` | export |
| A | A | A′ | `REMOTE_EDIT` | import (disk backed up) |
| — | A | A | `DELETED_LOCAL` | remove from portable, write tombstone |
| A | A | — | `DELETED_REMOTE` | delete from disk (backed up) |
| A | — | — + tombstone of A | `STALE_LOCAL` | delete from disk (backed up) |
| A′ | A | A″ | `MERGE` (MEMORY.md) | three-way index merge |
| A′ | A | A″ | `CONFLICT` (other files) | nothing until `resolve` |

Deleted on one side and edited on the other, content that differs with no
base to judge by, and a tombstoned name holding content this machine never
saw are also `CONFLICT`. A file this machine deleted and later re-created
exports normally.

`MEMORY.md` is merged entry by entry, keyed by each line's link target: an
entry added on either side is kept, one removed on one side and untouched
on the other stays removed, and one changed differently on both sides is a
conflict. Every overwrite and deletion is copied to `--backup-dir` first,
writes are atomic, and a lock keeps two mutating runs apart.

### Usage

```bash
claude-memory-sync status              # read-only; exit 2 when work is pending
claude-memory-sync apply               # everything except CONFLICT / ALIASED
claude-memory-sync resolve --keep local  foo/memory/user_role.md
claude-memory-sync resolve --keep remote foo/memory/user_role.md
```

With git as the carrier, pull before `apply` so remote tombstones are
present, and commit afterwards, including the `.deleted/` directories:

```bash
git -C ~/.claude/memory-sync pull
claude-memory-sync apply
git -C ~/.claude/memory-sync add -A && git -C ~/.claude/memory-sync commit -m "Sync memories"
```

Install it on `PATH` with the `commands` component, or run
`harnesses/claude-code/scripts/claude-memory-sync.py` from the checkout.

| Flag | Env var | Default |
|------|---------|---------|
| `--dir` | `CLAUDE_MEMORY_DIR` | `~/.claude/memory-sync` (must exist) |
| `--projects-dir` | `CLAUDE_PROJECTS_DIR` | `~/projects` |
| `--claude-dir` | `CLAUDE_DIR` | `~/.claude` |
| `--state-dir` | `XDG_STATE_HOME` | `~/.local/state/agent-toolbox/claude-memory` |
| `--backup-dir` | — | `<state-dir>/<key>/backups` |
| `--allow PREFIX` | — | sync only slugs equal to or nested under PREFIX |
| `--skip PREFIX` | — | never sync those slugs; subtracts inside `--allow` |

A prefix matches whole path segments: `--skip red` excludes `red` and
`red/x`, not `redhat`. `_global` is always synced.

### Migrating From Another Tool

A first run has no base, so a memory you deleted locally before switching
looks like `NEW_REMOTE` and would be re-imported. If the previous tool
recorded checksums of what it last synced, seed the base from them first:

```bash
printf 'foo/memory/old.md\t<sha256>\n' | claude-memory-sync adopt
```

A line is adopted when the portable or disk copy has that checksum;
`status` then reports the deletion as `DELETED_LOCAL`.

### Symlinked Projects

A project reached through a symlink gets one memory directory per launch
path. `status` reports such a project as `ALIASED` and `apply` leaves it
alone, because syncing two live copies would undo deletions made in either.
`claude-memory-sync link-aliases` merges them into the conventional
directory and replaces the others with symlinks to it; it refuses, listing
the files, when anything other than `MEMORY.md` differs.

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
printf '%s' "$absolute_path" | tr -c 'A-Za-z0-9' '-'
# /home/alice/projects/my_app.v2 → -home-alice-projects-my-app-v2
```

**The encoding is lossy in reverse.** Every non-alphanumeric character maps to `-`. Given `-home-alice-projects-my-app`, you can't tell if the project is `my-app`, `my_app`, `my.app` or `my/app` without checking the actual filesystem. This is why `claude-memory-sync` discovers projects by scanning git repos on disk (forward direction) rather than trying to decode existing Claude paths (reverse direction).

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

