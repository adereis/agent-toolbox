# Agent Toolbox

Reusable tools, prompts, instructions, skills, and hooks for coding agents.
Shared components live alongside explicit integrations for individual
harnesses; each component documents where it works.

## Convene: panels of independent AI reviewers

[Convene](harnesses/claude-code/plugins/convene/README.md) is a Claude Code
plugin that runs several **independent** coding-agent sessions on the same
brief and brings back what each wrote, with a receipt for what actually ran.
Seats are native CLIs (`claude -p`, `codex exec`) with a declared persona,
model, tool set and isolation tier; the foreground Claude is the operator
that writes the brief, reads the board and synthesizes.

```
/convene:panel HEAD~3..HEAD seat=codex/gpt-5.5 seat=claude/opus --persona sec-urity
```

That convenes a security reviewer on Codex and a skeptic on Claude over the
last three commits, each in its own process with no MCP servers, no project
instruction files and no operator memory, then reports the findings with the
served model, the isolation tier and every red flag per seat. On Linux with
bubblewrap the seats are jailed at the OS level; elsewhere they get a private
home and the receipt says so. It installs through Claude Code's own plugin
commands, not through `tools/install.py`:

```bash
claude plugin marketplace add /path/to/agent-toolbox
claude plugin install convene@agent-toolbox
```

Two kinds ship: the one-round **panel**, and the **room**, where seats
discuss a feature over rounds on a shared board, one seat drafts it in its
own git worktree, and the room critiques and revises the patch. Blind
fanouts (parallel implementations sealed before reading) follow on the same
engine.

## Available components

| Component | Harness | Documentation |
|-----------|---------|---------------|
| Convene: multi-seat review panels and design rooms with isolation tiers and receipts | Claude Code plugin; seats on Claude Code and Codex | [Convene](harnesses/claude-code/plugins/convene/README.md) |
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
  --component skills --component scripts --component commands
```

Add `--apply` to create the links. Existing conflicting files are preserved.
See [installation](docs/installation.md) for scope, components, configuration,
and removal. `/sync` in Claude Code wraps this same installer.

`scripts` links every harness utility where a skill can reach it by path.
`commands` puts the ones you run yourself on your `PATH` in `~/.local/bin`,
without the file extension, so the session browser is typed as
`codex-code-session-resume` rather than as a path. Session utilities run
from a terminal; `--list` and `--json` only inspect history.

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
│   ├── claude-code/      # Claude wrappers, hooks, settings, utilities, plugins
│   └── codex/            # Codex profiles, wrappers, and session utility
├── examples/             # Reference implementations, excluded from install
├── .claude-plugin/       # Marketplace manifest: the checkout is a local plugin marketplace
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
