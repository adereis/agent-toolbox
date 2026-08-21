# Claude Code Extensions

A collection of reusable extensions for Claude Code: agents, skills, hooks, and scripts.

## Statusline

The most-used piece here. Two rows — dim headers over colored values — putting context fill, session cost, and every rate-limit window `/usage` tracks in front of you without opening `/usage`.

![Claude Code statusline showing branch, model, effort, session, cost, and quota columns](settings/statusline.png)

Columns adapt to the setup: vim mode only when it is on, quota columns only on a subscription, one column per per-model weekly bucket the API reports. See [settings/README.md](settings/README.md) for the full column reference and installation.

## Related

- [claude-sandbox](https://github.com/adereis/claude-sandbox) - Containerized environment for running Claude Code in autonomous mode
- [mcp-servers](https://github.com/adereis/mcp-servers) - MCP servers (protocol layer, portable across clients)

## Extension Types

This repo covers Claude Code's extension points:

| Type | Description |
|------|-------------|
| Hooks | Event handlers that modify Claude's behavior |
| Skills | Reusable capabilities invoked via `/skill-name` (includes custom slash commands) |
| Agents | Specialized AI for specific tasks |
| Settings | Useful settings.json configurations (statusline, etc.) |
| Scripts | Standalone tools that complement Claude Code |

## Structure

```
claude-code-extensions/
├── hooks/            # Event handlers
├── skills/           # Slash commands and auto-invoked capabilities
├── agents/           # Specialized AI for specific tasks
├── settings/         # Settings.json configurations
├── scripts/          # Standalone tools (memory sync, session-resume, etc.)
├── README.md         # This file
└── CLAUDE.md         # Workflow and conventions
```

## Installing

**Using `/sync`** (recommended): From this project directory, run `/sync` inside Claude Code. It syncs all extension types (commands, agents, skills, hooks, settings) to `~/.claude/`, detects conflicts, and verifies hook enablement in `settings.json`.

**Manual installation:**

- **Hooks**: Copy scripts to `~/.claude/hooks/` and add configuration to `~/.claude/settings.json` (see `hooks/README.md` for each hook's config)
- **Skills**: Copy skill directories to `~/.claude/skills/`
- **Agents**: Copy agent files to `~/.claude/agents/`
- **Settings**: Copy scripts to `~/.claude/` and add configuration to `~/.claude/settings.json` (see `settings/README.md`)
- **Scripts**: Run directly or copy to a directory in your `$PATH` (see `scripts/README.md`)

## License

MIT
