# Installing components

The installer requires Python 3.10+ and a POSIX system with symlinks (Linux
or macOS). It installs selected components as links to this checkout. Keep
the checkout available; use a pinned checkout when you want a stable version.

Choose a harness, scope, and one or more components. The default is a dry run:

```bash
python3 tools/install.py --harness codex --scope user \
  --component skills --component scripts

# Apply that same plan
python3 tools/install.py --harness codex --scope user \
  --component skills --component scripts --apply

# Install the teaching skill for one Claude Code project
python3 tools/install.py --harness claude-code --scope project \
  --project /path/to/demo-project --component skills --apply
```

| Scope | Claude Code root | Codex components | Codex `profiles` | `commands` |
|-------|------------------|------------------|------------------|------------|
| User | `$CLAUDE_CONFIG_DIR` or `~/.claude` | `~/.agents` | `$CODEX_HOME` or `~/.codex` | `~/.local/bin` |
| Project | `<project>/.claude` | `<project>/.agents` | Unavailable | Unavailable |

`--target PATH` explicitly replaces the installation root for every selected
component, useful for staging or a custom setup. With `--component profiles`,
it is the Codex configuration directory itself, not a `profiles/` directory.
Custom targets are not automatically added to native harness discovery paths.
Codex user skills are shared across its profiles; use project scope for a
project-specific skill installation. This installer does not change
`CODEX_HOME` or partition native session history.

| Component | Claude Code | Codex | Installation behavior |
|-----------|-------------|-------|-----------------------|
| `skills` | Yes | Yes | Installs `teach` and `adopt-baseline` with native explicit-invocation metadata and the configuration-aware `whats-new` release digest; for Codex also the `convene` operator procedure, linked from the plugin |
| `scripts` | Yes | Yes | Links harness utilities under `<root>/scripts/` |
| `hooks` | Yes | Unavailable | Links the remaining hook scripts; registration is manual |
| `settings` | Yes | Unavailable | Links statusline scripts at the Claude configuration root |
| `prompts` | Yes | Yes | Links plain text under `<root>/prompts/`; no automatic invocation |
| `instructions` | Yes | Yes | Links opt-in modules under `<root>/instructions/`; no policy files overwritten |
| `profiles` | Unavailable | User scope only | Links `subscription.config.toml` and `api.config.toml` directly into the Codex configuration directory |
| `commands` | Yes | Yes | User scope only; links the utilities you run yourself into `~/.local/bin`, without their file extension, `convene` included |

Install the Codex [authentication profiles](../harnesses/codex/README.md#authentication-profiles)
with:

```bash
python3 tools/install.py --harness codex --scope user \
  --component profiles --apply
```

Omit `--apply` to preview. Profiles can be installed together with other
components: each uses its native destination, and the complete plan is
checked before any links are created. Profiles are user configuration layers;
Codex does not support provider selection from project configuration.
Installation does not edit `config.toml`, change the saved login, select a
default profile, or store an API key. Follow the profile documentation to
establish the subscription default and supply an API key when needed.

For personal context-window, compaction, and Vim preferences, use the
[Codex bootstrap template](../examples/codex/README.md). Follow its merge
instructions separately; the installer does not apply reference examples.

The installer reports unavailable combinations, missing source files, and
conflicts. It checks every destination before changing anything and refuses
to overwrite regular files or links to other sources. Back up and resolve
conflicts explicitly before retrying. Repeated installation is idempotent.
It does not follow symlinked parent directories beneath the chosen root.
On a creation failure, it removes links created by that invocation across all
destination roots while preserving concurrently changed entries; empty
directories may remain.

Installing hook or statusline scripts does not enable them. Apply the
configuration documented under the Claude [hooks](../harnesses/claude-code/hooks/README.md)
or [settings](../harnesses/claude-code/settings/README.md) pages to the scope
you selected, using the actual installed script path. Reference examples and
retired components are excluded from the installer.

Instruction modules are inert until an instruction file adopts them. The
installer never edits `AGENTS.md`, `CLAUDE.md`, or user-level instructions;
the [baseline adoption workflow](../skills/adopt-baseline/SKILL.md) performs
that merge and reports what it changed.

Put the utilities you run yourself on your `PATH` with the `commands`
component. It links them into `~/.local/bin` under the name their own help
text already prints, so the extension disappears:

```bash
python3 tools/install.py --harness codex --scope user \
  --component commands --apply

codex-code-session-resume --all
codex-tmux
convene doctor
```

`commands` withholds two groups on purpose. A skill invokes each `whats-new`
utility by path and supplies the judgement that utility deliberately omits,
and its `--commit` flag moves the digest baseline, so running it by hand
would mark releases read behind the skill's back. The memory scripts resolve
`claude-memory-lib.sh` relative to `$0` and need their siblings in a single
directory. Reach both groups through their installed `scripts` path:

```bash
python3 ~/.claude/scripts/claude-code-whats-new.py
~/.claude/scripts/claude-memory-status.sh
```

## Plugins

Claude Code plugins live under `harnesses/claude-code/plugins/` and are
installed with Claude Code's own commands. The repository root carries a
marketplace manifest, so a checkout is a local marketplace:

```bash
claude plugin marketplace add /path/to/agent-toolbox
claude plugin install convene@agent-toolbox

# Development: load the checkout in place, without installing
claude --plugin-dir /path/to/agent-toolbox/harnesses/claude-code/plugins/convene
```

Codex does not load Claude Code plugins. It reaches the same engine
directly: the `commands` component puts `convene` on `PATH`, and the Codex
`skills` component links the plugin's operator procedure as the `convene`
skill, so a Codex session drives the engine the way `/convene:panel` does.
The installed `skills/convene` entry is a directory symlink. Codex 0.155.1
discovers the regular `SKILL.md` inside it and exposes it as
`convene:convene`, using the plugin namespace. Its references and explicit
invocation policy live in that same shared directory.

If an earlier installation left a real `~/.agents/skills/convene`
directory containing individual file links, the installer reports a
conflict. Inspect that directory, move it to a backup under `~/tmp`, and
rerun the installer. It does not replace an existing directory or discard
local edits. The same rule applies to project-scope installations.

`tools/install.py` does not manage plugins and has no `plugin` component.
Claude Code discovers plugins only through its own registry
(`~/.claude/plugins/installed_plugins.json`), and an installer writing there
would be a second source of truth for the same state. Update an installed
plugin with `claude plugin update convene@agent-toolbox`; remove it with
`claude plugin uninstall convene@agent-toolbox`.

To remove an installation, remove only its symlinks; remove any hook or
statusline registration before removing the script it runs. The installer
never imports local configuration or content back into the repository.
