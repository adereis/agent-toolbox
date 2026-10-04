Synchronize Claude Code memories between machines with `claude-memory-sync`,
supervising every deletion and merge it makes. Claude Code only.

The utility decides mechanically from three copies of each memory file: this
machine's disk, the shared portable directory, and this machine's base, the
copy it last synced. It cannot tell whether a deletion was meant, and its
output names files without their content. Supply that judgement here. Treat
any result that departs from the utility's decision table as a suspected
defect in the utility: report it with evidence, and never repair it by
editing memories by hand.

## Prepare

Run the installed script by path,
`${CLAUDE_CONFIG_DIR:-$HOME/.claude}/scripts/claude-memory-sync.py`. It is
deliberately not on `PATH`, so that every run goes through this procedure.
Stop and report if it is missing; install it from a checkout with:

```bash
python3 tools/install.py --harness claude-code --scope user \
  --component scripts --apply
```

Read its `--help`, including the decision table. Settle the arguments once
and pass the same ones to every invocation: the portable directory (`--dir`,
default `$CLAUDE_MEMORY_DIR` or `~/.claude/memory-sync`), `--claude-dir`,
`--projects-dir`, and any `--allow` or `--skip` the user named. Confirm that
`--claude-dir` is the configuration directory Claude Code is using, which is
`$CLAUDE_CONFIG_DIR` when that is set, and that `--projects-dir` is the one
earlier runs used. A wrong value maps each project to a memory directory
that does not exist, and the utility reads every memory it synced there
before as deleted.

When the portable directory is a git repository, inspect `git status` first.
Uncommitted changes there are unfinished work from an earlier run or a hand
edit; stop and report them. Otherwise pull, so that tombstones written
elsewhere are present before the preview. Stop if the pull conflicts.

## Preview

Run `status`. It is read-only and exits 2 when work is pending. Keep its
output for the comparison after `apply`.

Locate this machine's base store before reading the entries. It is the
directory under the state directory (`$XDG_STATE_HOME/agent-toolbox/claude-memory`,
or `~/.local/state/agent-toolbox/claude-memory` when that variable is unset)
whose `portable-dir` file names the portable directory. Its `base/` holds
the last synced copies. If no store names the portable directory, this
machine has never applied against it.

Read each entry that removes or rewrites a memory, and record its file name,
its `name` and `description`, and what it holds:

- `DELETED_LOCAL` removes the portable copy and writes a tombstone, so the
  memory leaves every machine at its next sync. Read the portable copy.
- `DELETED_REMOTE` and `STALE_LOCAL` remove the disk copy. Read it. For
  `STALE_LOCAL`, confirm that `<dir>/<slug>/memory/.deleted/<file>` lists
  the disk copy's SHA-256.
- `REMOTE_EDIT` overwrites the disk copy. Show the difference.
- `MERGE` rewrites `MEMORY.md` on both sides. Compare the disk and portable
  copies against the base copy and list the entries each side added and
  removed.

Stop before applying, and ask the user, when the preview looks like an
accident rather than a decision:

- Every file of a project is `DELETED_LOCAL`, or the project's memory
  directory is missing on disk. That is a moved checkout, a cleaned-up
  `~/.claude/projects`, or a wrong `--claude-dir` or `--projects-dir`, not a
  set of deliberate deletions. Applying it would delete the project's
  memories on every machine.
- This machine has no base store and the portable directory already holds
  memories. A memory deleted here before the first sync reappears as
  `NEW_REMOTE`. Ask whether an earlier sync tool recorded checksums that
  `adopt` can seed the base from.
- An entry's status contradicts the copies you read, such as a
  `REMOTE_EDIT` whose disk copy differs from the base.

`apply` leaves `CONFLICT` and `ALIASED` entries untouched. Show each
conflict with both versions and let the user choose; run `resolve` or
`link-aliases` only on their decision.

## Apply and verify

List the timestamped directories under the backup directory (`--backup-dir`,
default `backups/` in the base store), then run `apply` with the same
arguments. Each action line must be the one the decision table maps that
file's previewed status to, and every previewed entry other than `CONFLICT`
and `ALIASED` must have one. A missing, extra or different line is a
finding.

Check the result against the preview:

- The backup directory this run created holds a copy of every file it
  removed or overwrote, matching what the preview recorded.
- A `REMOVED` file is gone from disk. A `TOMBSTONED` file is gone from the
  portable directory, and its tombstone lists the removed version's SHA-256.
- A `MERGED` index is identical on disk and in the portable directory. It
  keeps every entry either side added and drops every entry one side
  removed.
- A second `status` reports only the `CONFLICT` and `ALIASED` entries left
  behind. Anything else pending means `apply` did not converge.

Then check what the utility does not. After deletions and merges, each
`MEMORY.md` should link only to files beside it, and each memory file should
have an index entry. Report a dangling link or an unindexed file; fix
neither without the user's decision.

When the portable directory is a git repository, commit the result,
including the `.deleted/` directories, with a message that lists each
deleted and merged memory. Push only when the user asked.

## Report

Lead with what changed in the user's memories, as a ledger:

- Memories removed from this machine, each with its description, the reason
  (deleted elsewhere, or a stale copy of a tombstoned version) and its
  backup path.
- Memories this run deleted everywhere by tombstoning, with the same
  details.
- Merged indexes, with the entries added and removed on each side.
- Imported and exported files, by name.
- Conflicts and aliased projects awaiting the user.

List findings separately: each departure from the decision table, missing
backup, wrong tombstone, non-converging `apply` or index inconsistency, with
the commands and output that show it. When a finding points at a defect in
`claude-memory-sync.py`, describe a reproduction with synthetic data that a
regression test in `tests/test_claude_memory_sync.py` could encode.
