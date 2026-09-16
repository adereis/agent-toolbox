# Agent Toolbox

Reusable tools, prompts, instructions, skills, and hooks for coding agents.
Shared components live alongside explicit integrations for individual
harnesses; each component documents where it works.

## Available components

| Component | Harness | Documentation |
|-----------|---------|---------------|
| Session history and resume | Claude Code | [Utilities](harnesses/claude-code/scripts/README.md) |
| Session history and resume | Codex | [Codex integration](harnesses/codex/README.md) |
| Subscription and API authentication profiles | Codex | [Authentication profiles](harnesses/codex/README.md#authentication-profiles) |
| Personal context, compaction, and Vim preferences | Codex; bootstrap reference | [Configuration template](examples/codex/README.md) |
| Keyring-backed API key wrapper | Codex | [Store the key in the keyring](harnesses/codex/README.md#store-the-key-in-the-keyring) |
| Tmux launcher with backend and status display | Codex | [Tmux status display](harnesses/codex/README.md#tmux-status-display) |
| Memory export, import, and status | Claude Code | [Utilities](harnesses/claude-code/scripts/README.md#claude-memory--memory-portability) |
| Release digest against local configuration | Claude Code | [Utilities](harnesses/claude-code/scripts/README.md#claude-code-whats-newpy) |
| Release digest against local configuration | Codex | [Release digest](harnesses/codex/README.md#release-digest) |
| Statusline and quota display | Claude Code | [Settings](harnesses/claude-code/settings/README.md) |
| Hooks | Claude Code | [Hooks](harnesses/claude-code/hooks/README.md) |
| Teaching skill | Claude Code and Codex | [Shared workflow](skills/teach/SKILL.md) |
| Baseline adoption skill | Claude Code and Codex | [Shared workflow](skills/adopt-baseline/SKILL.md) |
| Release digest skill | Claude Code and Codex | [Shared workflow](skills/whats-new/SKILL.md) |
| Review and browser verification prompts | Any harness accepting text prompts | [Prompts](prompts/README.md) |
| Optional instruction modules | Any harness accepting instruction files | [Instructions](instructions/README.md) |
| Hook reference examples | Claude Code payloads; not deployed | [Examples](examples/claude-code/hooks/README.md) |
| Agent configuration examples | Claude Code | [Agents](harnesses/claude-code/agents/README.md) |

## Installation

Choose a harness and scope, then preview the selected components:

```bash
git clone https://github.com/adereis/agent-toolbox.git
cd agent-toolbox
python3 tools/install.py --harness codex --scope user \
  --component skills --component scripts
```

Add `--apply` to create the links. Existing conflicting files are preserved.
See [installation](docs/installation.md) for scope, components, configuration,
and removal. `/sync` in Claude Code wraps this same installer. Session
utilities run from a terminal; `--list` and `--json` only inspect history.

## Using this repository with an agent

Most people install and operate these components through a coding agent
rather than by hand. Point the agent at this repository and describe the
outcome you want; it reads the component table above, runs the installer,
and follows the README for the harness it selected.

Components are written for that workflow. When a component cannot run on
your platform it exits with the command that works there instead of failing
quietly, so the agent can finish the task without a round trip through you.
Supported platforms are stated with each component; Linux is tested, and
macOS support varies by component.

## Repository layout

```text
agent-toolbox/
├── skills/               # Shared workflows
├── prompts/              # Optional task prompts
├── instructions/         # Opt-in policy modules
├── tools/                # Installer and common utility code
├── harnesses/
│   ├── claude-code/      # Claude wrappers, hooks, settings, utilities
│   └── codex/            # Codex profiles, wrappers, and session utility
├── examples/             # Reference implementations, excluded from install
├── docs/                 # Installation and migration
├── tests/                # Automated and live integration checks
├── AGENTS.md             # Repository development conventions
├── CLAUDE.md             # Claude entry point to those conventions
└── README.md             # Catalog and installation
```

## Migration from Claude Code Extensions

The GitHub repository was renamed from `claude-code-extensions` to
[`agent-toolbox`](https://github.com/adereis/agent-toolbox), retaining its
history. The `claude-code-baseline` tag marks
the collection before this migration. Source directories formerly at the
repository root now live under `harnesses/claude-code/`; update any links or
scripts that refer to checkout paths. Installed `~/.claude/` paths are
unchanged by this source reorganization. Follow the
[migration notes](docs/migration.md) to remove retired installations and
update session utility links.

## Related

- [mcp-servers](https://github.com/adereis/mcp-servers): reusable MCP servers.
- [claude-sandbox](https://github.com/adereis/claude-sandbox): a containerized
  Claude Code environment.

## License

MIT
