# Agent Toolbox

Reusable tools, prompts, instructions, skills, and hooks for coding agents.
Shared components live alongside explicit integrations for individual
harnesses; each component documents where it works.

## Available components

| Component | Harness | Documentation |
|-----------|---------|---------------|
| Session history and resume | Claude Code | [Utilities](harnesses/claude-code/scripts/README.md) |
| Memory export, import, and status | Claude Code | [Utilities](harnesses/claude-code/scripts/README.md#claude-memory--memory-portability) |
| Statusline and quota display | Claude Code | [Settings](harnesses/claude-code/settings/README.md) |
| Hooks | Claude Code | [Hooks](harnesses/claude-code/hooks/README.md) |
| Review and browser verification prompts | Any harness accepting text prompts | [Prompts](prompts/README.md) |
| Agent configuration examples | Claude Code | [Agents](harnesses/claude-code/agents/README.md) |

## Installation

Claude Code components are under `harnesses/claude-code/`. From this checkout,
run `/sync` in Claude Code to compare the collection with your user
configuration. Individual component READMEs describe manual installation.
Session utilities run from a terminal; use `--list` to inspect history without
launching an interactive agent.

## Repository layout

```text
agent-toolbox/
├── harnesses/
│   └── claude-code/       # Claude hooks, skills, agents, settings, utilities
├── tests/                # Automated and live integration checks
├── AGENTS.md             # Repository development conventions
├── CLAUDE.md             # Claude entry point to those conventions
└── README.md             # Catalog and installation
```

## Migration from Claude Code Extensions

The existing Git history is retained. The `claude-code-baseline` tag marks
the collection before this migration. Source directories formerly at the
repository root now live under `harnesses/claude-code/`; update any links or
scripts that refer to checkout paths. Installed `~/.claude/` paths are
unchanged by this source reorganization.

## Related

- [mcp-servers](https://github.com/adereis/mcp-servers): reusable MCP servers.
- [claude-sandbox](https://github.com/adereis/claude-sandbox): a containerized
  Claude Code environment.

## License

MIT
