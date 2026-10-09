# Codex CLI release digest
## Environment
platform: linux
installed CLI: 9.0.0
Codex home: /example/.codex
project: /example/project
profile: subscription
project trust: trusted
terminal: kitty (via KITTY_PID)
TERM: xterm-256color; multiplexer: none
TERM does not name the detected terminal.
setting approval_policy: on-request
setting sandbox_mode: workspace-write
setting model_reasoning_effort: high
feature hooks: True
feature memories: False
hooks: PreCompact
mcp: none found
plugins: reference-plugin
skills: none found
sources: /example/.codex/config.toml
hooks disabled in files: False
statusline: True
notifications: False
vim: False
keymap: False
otel: False
rules: True
sessions: True
git: True
environment variables (names only): CODEX_DISABLE_HINTS
File-based inventory, not the running session's effective configuration. CLI overrides, cloud defaults, enforced requirements, plugin-bundled content, and hook trust are not resolved. Unset features retain unknown runtime defaults.

Window: 9.0.0 through 9.0.0 (1 releases)
Baseline: 8.9.0
Signals watched: hooks, plugins, permissions, statusline, sessions, git, effort, compaction, new-setting, new-command, behavior-change, feature:hooks, term:kitty, new-feature
Withheld: 2 entries belonging to another platform
Unmatched: 4 entries matched no configuration signal
Not shown: 4 unmatched entries (--relevant-only)
  Windows: another platform: 1
  macOS: another platform: 1

## 9.0.0 (2026-09-30)
[hooks,compaction,behavior-change] Removed the PreCompact hook event; configurations listing PreCompact must rename it to PreCompaction.
[behavior-change] Removed the old memories setting; migrate only if features.memories is true.
[new-setting,new-feature] Added `CODEX_DISABLE_HINTS=1` to disable default hints; configurations that already allow hints need no change.
[plugins] Fixed plugin OAuth refresh when a plugin is enabled.
[statusline,sessions] Fixed the status line losing its selected fields after resume.
[statusline,sessions] Preserve selected status line fields on resumed sessions.
[new-command,new-feature] Added `/bookmarks` to bookmark a transcript position.

Baseline file: /example/state/baseline.json
Baseline unchanged; add --through VERSION --commit after presenting this window.
Local snapshot; releases outside this file are not searched.
Archive coverage: 9.0.0 through 9.0.0
Source: Frozen public archive or explicitly synthetic fixture; see cases.json
