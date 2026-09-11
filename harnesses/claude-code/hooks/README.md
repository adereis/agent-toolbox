# Hooks

Claude Code hooks are scripts that run at specific points during tool execution. Copy this directory to `~/.claude/hooks/`, then add the configuration snippets below to your `~/.claude/settings.json`.

## git-push-guard.sh

**Command confirmation guard** — forces human confirmation before specific commands execute, even when Bash is pre-approved via permissions.

This is useful as a safety net for autonomous or semi-autonomous sessions: you can broadly allow Bash commands for speed, while still requiring explicit approval for high-impact operations. The hook intercepts commands *after* Claude Code's own permission check, so it acts as an additional protection layer.

**Default behavior:** Guards `git push` commands. Prevents accidental pushes when Claude is running autonomously.

**Adapting to other commands:** The script uses parallel `PATTERNS` and `REASONS` arrays. Uncomment the built-in examples or add your own — the first matching pattern wins and its reason is shown to the user:

| Guard | Pattern | Use case |
|-------|---------|----------|
| `git push` (default) | `\bgit\s+push\b` | Prevent unreviewed pushes |
| `kubectl delete` | `\bkubectl\s+delete\b` | Protect cluster resources |
| `docker rm` | `\bdocker\s+rm\b` | Prevent container removal |
| `terraform destroy` | `\bterraform\s+destroy\b` | Protect infrastructure |
| `rm -rf` | `\brm\s+-rf\b` | Prevent recursive deletion |

Multiple guards are handled within a single script — just add more `PATTERNS+=` / `REASONS+=` pairs. Each match produces a specific reason so the user knows exactly which command triggered the confirmation.

**Configuration:**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/git-push-guard.sh"
          }
        ]
      }
    ]
  }
}
```

Merge the `hooks` object into your existing settings.json. If you already have `PreToolUse` hooks, add the new hook object to the existing array.

## tmp-write-guard.sh

**Path write deny guard** — hard-blocks writes to specific paths with no user override. Uses `permissionDecision: "deny"` for unconditional blocking.

This differs from the command confirmation guard: instead of *asking* before proceeding, it *denies* outright. Use this for security boundaries where the answer is always "no".

**Default behavior:** Blocks writes to `/tmp/` (predictable filenames are a security risk). Claude sees the error message and should use `~/tmp` instead.

**Note:** `"block"` is only valid for the root-level `decision` field (shows a prompt). Inside `hookSpecificOutput.permissionDecision`, use `"deny"` (prevents execution), `"ask"` (shows prompt), or `"allow"`/`"defer"`. Using `"block"` inside `hookSpecificOutput` causes validation failure and the hook is silently ignored.

**Upstream issue:** https://github.com/anthropics/claude-code/issues/14085 — The `/tmp` block may become unnecessary once resolved.

**Adapting to other paths:** The script uses parallel `BLOCKED_PATHS` and `DENY_MESSAGES` arrays. Add entries to block additional paths:

| Guard | Path | Use case |
|-------|------|----------|
| `/tmp/` (default) | `/tmp/` | Prevent insecure temp file creation |
| `/etc/` | `/etc/` | Protect system configuration |
| `/var/run/` | `/var/run/` | Protect runtime state |

**Smart exceptions** (apply to all blocked paths):
- Read-only commands (`cat`, `ls`, `head`, `tail`, etc.) are allowed
- Cleanup commands (`rm`) are allowed
- Git commands are allowed (paths may appear in commit messages)
- Redirects from read-only commands (`cat > /path`) are still blocked

**Configuration:**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/tmp-write-guard.sh"
          }
        ]
      },
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/tmp-write-guard.sh"
          }
        ]
      }
    ]
  }
}
```

## tmp-home-allow.sh

**Path write allow guard** — the *allow* half of the `~/tmp` policy. Returns `permissionDecision: "allow"` whenever an operation targets `~/tmp`, so those writes and commands skip the permission prompt entirely.

Pairs with `tmp-write-guard.sh`: together they enforce `~/tmp` = safe (auto-approved), `/tmp` = blocked. Prefix-based permission rules (e.g. `Bash(...)`) can't reliably cover every shape where `~/tmp` appears — a redirect target, a mid-pipeline argument, an env assignment — so this hook inspects the resolved path / full command instead.

**Covered tools:**
- `Write`/`Edit` — resolves `file_path` with `realpath` and allows if it falls under `~/tmp/`
- `Bash` — allows if `~/tmp/` or `$HOME/tmp/` appears anywhere in the command

On no match it exits silently, letting later hooks and the default permission system decide.

**Ordering (important):** Must be listed **before** `tmp-write-guard.sh` in each matcher, so the `allow` decision is registered before the deny guard runs. Appending it *after* the guard defeats the pairing.

**Configuration** (shown with `tmp-write-guard.sh` in the correct order):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/tmp-home-allow.sh"
          },
          {
            "type": "command",
            "command": "~/.claude/hooks/tmp-write-guard.sh"
          }
        ]
      },
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/tmp-home-allow.sh"
          },
          {
            "type": "command",
            "command": "~/.claude/hooks/tmp-write-guard.sh"
          }
        ]
      },
      {
        "matcher": "Edit",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/tmp-home-allow.sh"
          }
        ]
      }
    ]
  }
}
```

## test-edit-guard.sh

**File edit context guard** — injects contextual guidance when specific file types are edited. Uses `additionalContext` to show a message after the edit, prompting Claude to verify the edit was appropriate.

This is a softer intervention than the other guards: it doesn't block or ask for confirmation, it *nudges* Claude to reconsider after the fact. Useful for file types where edits are often a mistake.

**Default behavior:** Guards test file edits. When tests fail, it's tempting to modify the tests to pass. But often the tests are correct and the code is incomplete (e.g., backporting only part of a feature, missing a dependency). The injected context prompts Claude to verify.

**Adapting to other file types:** The script uses parallel arrays for `LABELS`, `FILE_PATTERNS` (filename regex), `DIR_PATTERNS` (directory regex), and `CONTEXT_MESSAGES`. A file matches if either its name or directory matches. First match wins.

| Guard | Detects | Use case |
|-------|---------|----------|
| Test files (default) | `test_*`, `*_test.*`, `*.spec.*`, `tests/` | Prevent "fixing" correct tests |
| CI/CD config | `Jenkinsfile`, `*.yml` in `.github/workflows/` | Protect pipeline definitions |
| DB migrations | `*.migration.*` in `migrations/` | Ensure migration safety |

**Behavior:**
- Detects files by name patterns and/or directory patterns
- Injects a context-specific nudge Claude sees after the edit executes
- Logs to `~/tmp/hook-debug.log` when triggered (for debugging)

**Configuration:**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/test-edit-guard.sh"
          }
        ]
      }
    ]
  }
}
```

## jira-mcp-subagent-guard.sh

**Subagent delegation guard** — blocks specific tools from the main agent, forcing them into subagents. Keeps the main conversation context clean by isolating MCP calls that return large payloads or require multiple round-trips.

This uses a different mechanism than the other guards: instead of matching commands by regex, the tool matching is handled by the `matcher` field in `settings.json`. The script itself only checks whether the caller is the main agent (block) or a subagent (allow), using the `agent_id` field in hook inputs.

**Default behavior:** Guards Jira MCP calls (`mcp__atlassian__*`).

**Adapting to other tools:** Point additional `matcher` entries at the same script — no code changes needed:

| Guard | Matcher | Use case |
|-------|---------|----------|
| Jira MCP (default) | `mcp__atlassian__*` | Isolate Jira queries |
| Slack MCP | `mcp__slack__*` | Isolate Slack messages |
| Notion MCP | `mcp__notion__*` | Isolate Notion queries |
| GitHub MCP | `mcp__github__*` | Isolate GitHub API calls |

**Pairs with CLAUDE.md:** This hook works best alongside a CLAUDE.md instruction like `"Delegate Jira MCP calls to subagents to keep the main conversation clean"`. The instruction provides guidance and rationale; the hook enforces it. In practice, the instruction alone is not always followed — but once the hook fires and blocks, the agent recognizes the pattern and self-corrects for the rest of the session. The duo is essential: guidance without enforcement is unreliable, enforcement without guidance produces confusion.

**Stronger alternative — hard scoping:** This hook is the *soft* option: it keeps the MCP server in global config and merely blocks the main thread, so the tool still exists everywhere. To make a server owned by a *single* agent — unreachable from the main thread and pinned to a specific model — scope it to that agent with `mcpServers` frontmatter and remove it from global config instead. See [agents/README.md](../agents/README.md#pattern-model-scoped-mcp-agent-layer-0). Note: `permissions.deny` + a per-agent `tools:` allow does **not** achieve this — the deny cascades into delegated subagents. When Jira is hard-scoped to the `jira` agent, this hook's `mcp__atlassian__*` matcher becomes a harmless no-op (no such tool in the main thread to guard).

**Requires:** Claude Code >= 2.1.64 (`agent_id` in hook inputs).

**Upstream issue:** https://github.com/anthropics/claude-code/issues/9340 — MCP tool results (e.g., `jira_get_issue`) can return 10-12k tokens of raw JSON rendered as a wall of text in the terminal. This hook forces those calls into subagents where the verbose output stays hidden. A per-tool display mode or `--quiet` flag would make this unnecessary.

**Configuration:**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "mcp__atlassian__*",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/jira-mcp-subagent-guard.sh"
          }
        ]
      }
    ]
  }
}
```

To guard multiple MCP servers, add separate matcher entries all pointing to the same script.

## continue-plan.sh

**Stop event handler** — auto-continues multi-phase plan execution. When enabled via environment variable, Claude continues autonomously instead of stopping after each phase.

Unlike the guards above (which intercept tool calls), this hook intercepts the `Stop` event — it runs when Claude would normally stop and wait for input. It uses exit code 2 to block stopping and injects instructions via stderr.

**Features:**
- Disabled by default (must set `CLAUDE_AUTO_PLAN=1`)
- Stops after 5 restarts (prevents infinite loops)
- Detects `ALL_PHASES_COMPLETE` marker to stop early
- Instructs Claude to run tests, make autonomous decisions, and record them in `DECISIONS.md`

**Usage:**

```bash
CLAUDE_AUTO_PLAN=1 claude
```

**Configuration:**

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/continue-plan.sh",
            "timeout": 10000
          }
        ]
      }
    ]
  }
}
```
