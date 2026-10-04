# Hooks

Claude Code hooks are scripts that run at specific points during tool execution. Copy this directory to `~/.claude/hooks/`, then add the configuration snippets below to your `~/.claude/settings.json`.

## git-push-guard.sh

**Command confirmation guard** — forces human confirmation before specific commands execute, even when Bash is pre-approved via permissions.

This is useful as a safety net for autonomous or semi-autonomous sessions: you can broadly allow Bash commands for speed, while still requiring explicit approval for high-impact operations. The hook intercepts commands *after* Claude Code's own permission check, so it acts as an additional protection layer.

**Default behavior:** Guards `git push` commands. Prevents accidental pushes when Claude is running autonomously.

**What counts as a push.** The guard asks whenever `git` is followed by `push`, with any of git's global options in between. So `git push`, `git -C "$repo" push` (the usual form when an agent works across repositories, in a loop or through `xargs`), `git -c key=val push`, `git --git-dir=… push` and `/usr/bin/git push` all ask. A command split with a line continuation is joined before matching. Other subcommands stay quiet even with the same options, `git -C repo pull` or `git stash push` for example.

The guard scans the command's text; it does not parse the shell. So a command that only *mentions* a push asks too, an `echo` or a commit message, for instance. That is deliberate. A parser that misread one shell construct would let a real push through unasked, and for a safety net a needless prompt is the cheaper mistake. Text cannot reveal a push hidden behind a git alias (`git p`), a variable (`$GIT push`), or a script file the command runs.

**Adapting to other commands:** The script uses parallel `PATTERNS` and `REASONS` arrays. Uncomment the built-in examples or add your own — the first matching pattern wins and its reason is shown to the user:

| Guard | Pattern | Use case |
|-------|---------|----------|
| `git push` (default) | `git` + global options + `push` (see the script) | Prevent unreviewed pushes |
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

## Retired hooks

The tmp write/allow guards, test-edit guard, and continue-plan hook are no
longer deployed. Remove their command registrations from your Claude
settings before removing installed files. Preserve other hooks sharing the
same matcher. See [migration notes](../../../docs/migration.md).

[Reference examples](../../../examples/claude-code/hooks/README.md) demonstrate
directory denial and contextual guidance on edits. They are opt-in examples
and are excluded from installation.
