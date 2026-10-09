# Codex CLI release digest
## Environment
platform: linux
installed CLI: 9.3.0
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
feature hooks: False
feature memories: True
feature multi_agent: True
hooks: PreToolUse
mcp: none found
plugins: none found
skills: none found
sources: /example/.codex/config.toml
hooks disabled in files: True
statusline: True
notifications: False
vim: True
keymap: False
otel: True
rules: True
sessions: True
git: True
environment variables (names only): none
File-based inventory, not the running session's effective configuration. CLI overrides, cloud defaults, enforced requirements, plugin-bundled content, and hook trust are not resolved. Unset features retain unknown runtime defaults.

Window: 9.2.0 through 9.3.0 (2 releases)
Baseline: none recorded
Signals watched: permissions, memory, subagents, statusline, vim, sessions, git, telemetry, effort, compaction, new-setting, new-command, behavior-change, feature:memories, feature:multi_agent, term:kitty, new-feature
Withheld: 1 entries belonging to another platform
Unmatched: 2 entries matched no configuration signal
Not shown: 0 unmatched entries (--relevant-only)
  Windows: another platform: 1

## 9.3.0 (2026-09-30)
[new-command,new-feature] Added `/rewind` to restore an earlier conversation turn.
[vim] Fixed Vim input losing the draft after leaving scrollback.
[telemetry] Fixed telemetry initialization only when telemetry is disabled.
[-] Fixed MCP OAuth refresh for an enabled server.
[vim] Fix Vim draft loss after scrollback.

## 9.2.0 (2026-09-30)
[memory,behavior-change,feature:memories] Removed `features.memories`; users who explicitly enable it must migrate to `features.memory_v2`.
[permissions,behavior-change] Removed `sandbox_legacy`; users with an old `legacy_access` permission rule must replace that rule.
[-] Fixed PreToolUse hook allow decisions bypassing an ask rule.
[subagents,feature:multi_agent] Fixed subagents reconnecting when multi_agent is enabled.
[new-feature] Added `CODEX_DISABLE_TIPS=1` to suppress the new default startup tips.

Baseline file: /example/state/baseline.json
Baseline unchanged; add --through VERSION --commit after presenting this window.
Local snapshot; releases outside this file are not searched.
Archive coverage: 9.2.0 through 9.3.0
Source: Frozen public archive or explicitly synthetic fixture; see cases.json
