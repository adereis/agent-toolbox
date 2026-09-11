# Codex integration

## codex-code-session-resume.py

Browse recent local Codex sessions with their titles, a prompt arc, recognized
commit results, and optional edited-file details. Select a session to launch
the native `codex resume <id>` command. Run the interactive utility from a
terminal; use `--list` or `--json` inside an existing agent session.

```bash
# Current project, newest session at the bottom
python3 harnesses/codex/scripts/codex-code-session-resume.py

# Browse across projects, including edited files
python3 harnesses/codex/scripts/codex-code-session-resume.py --all -n 20 -v

# Read-only listing suitable for pipes and automation
python3 harnesses/codex/scripts/codex-code-session-resume.py --all --list | less
python3 harnesses/codex/scripts/codex-code-session-resume.py --all --json
```

Python 3.10 or newer is sufficient for browsing; Codex CLI is needed only
when resuming. Keep the checkout intact, since the entry point imports the
shared `tools/_session_resume.py` module. Symlinking the entry point onto
your `PATH` works; copying only that file does not.

| Option | Behavior |
|--------|----------|
| `--codex-dir PATH` | Select the store to read and pass to the resumed process |
| `--project PATH` / `-p PATH` | Match the recorded working directory exactly |
| `--all` / `-a` | Include other project directories in the same store |
| `--include-subagents` | Also show delegated sessions, hidden by default |
| `--profile NAME` | Forward a configuration profile to native `codex resume` |
| `--resume-cwd PATH` | Explicit replacement working directory when resuming |
| `--color auto\|always\|never` | Control terminal styling; `NO_COLOR` disables automatic styling |

By default, the store is `$CODEX_HOME`, or `~/.codex` when unset. A selected
store stays selected during resume. Codex configuration profiles sharing
the same store share history; `--profile` selects launch configuration and
does not claim to partition that history. Use separate stores when you need
separate history. No session files, indexes, or databases are modified.

The parser reads active `sessions/**/*.jsonl` rollouts and the optional
`session_index.jsonl` title index. Archived sessions are excluded. Discovery
uses metadata and file modification times; only the selected recent sessions
are fully parsed. Duplicate user event/response records and known injected
context blocks are omitted from the prompt arc. Incomplete records produce
warnings, and uninspectable dynamic tool calls are reported.

Commit extraction is best effort: it correlates recognized shell calls with
Git's success output, including static JSON-string commands in wrapped `exec`
calls. It never evaluates transcript code. Quiet commits without success
output and dynamically constructed commands may be absent. Edited-file
details cover recognized successful `apply_patch` calls, not arbitrary shell
file writes. These are observed historical results, not current Git state.

The CLI arguments and local rollout shapes were checked against Codex CLI
0.154.0. Rollout storage is an internal format that may evolve. Native command
documentation: [Codex CLI reference](https://developers.openai.com/codex/cli/reference).
