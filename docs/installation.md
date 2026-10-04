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
| `skills` | Yes | Yes | Installs `teach` with native explicit-invocation metadata and the configuration-aware `whats-new` release digest; for Codex also the `convene` operator procedure, linked from the plugin |
| `scripts` | Yes | Yes | Links harness utilities under `<root>/scripts/` |
| `hooks` | Yes | Unavailable | Links the remaining hook scripts; registration is manual |
| `settings` | Yes | Unavailable | Links statusline scripts at the Claude configuration root |
| `prompts` | Yes | Yes | Links plain text under `<root>/prompts/`; no automatic invocation |
| `instructions` | Yes | Yes | Links opt-in modules under `<root>/instructions/`; no policy files overwritten |
| `profiles` | Unavailable | User scope only | Links `subscription.config.toml` and `api.config.toml` directly into the Codex configuration directory |
| `commands` | Yes | Yes | User scope only; links the utilities you run yourself into `~/.local/bin`, without their file extension, `convene` included |

Codex's `whats-new` skill is linked as a directory so its regular
`SKILL.md` is discoverable. The skill delegates release reading to Luna at
high effort, with the parent checking the result. Older individual file
links require the [release digest migration](migration.md#codex-release-digest-discovery).

### What a component costs a session

Components differ in whether an agent pays for them when it is doing
something else. A skill advertises its name and description to every session
that can discover it, so an installed skill is a standing cost in every
project at user scope, whether or not it is ever used. A prompt, an
instruction module, and a script cost nothing until something reads them.

| Component | Cost when unused | Why |
|-----------|------------------|-----|
| `skills` | Every session, at the installed scope | Name and description are offered to the model so it can choose the skill |
| Plugins | Every session, at the installed scope | Bundled skills and commands are advertised the same way; `claude plugin details <name>` prints the figure |
| `prompts` | None | Plain text outside any discovery path; read only when named |
| `instructions` | None until adopted | Inert files; a module applies only after an instruction file imports or inlines it |
| `scripts`, `commands` | None | Executables, run on demand |
| `hooks`, `settings` | None until registered | Installing a script does not configure the harness to run it |

Choose scope against that cost. A workflow used across projects earns user
scope; one that belongs to a single repository should be installed with
`--scope project` so other work does not carry it. A workflow that runs
rarely and edits your own configuration is better as a prompt than as a
skill, which is why [baseline adoption](../prompts/adopt-baseline.md) ships
as one.

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
the [baseline adoption prompt](../prompts/adopt-baseline.md) performs that
merge and reports what it changed. It ships as a prompt so that a workflow run
twice a year costs nothing in the sessions that never run it.

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

`commands` withholds the `whats-new` utilities on purpose. A skill invokes
each by path and supplies the judgement that utility deliberately omits, and
its `--commit` flag moves the digest baseline, so running it by hand would
mark releases read behind the skill's back. Reach them through their
installed `scripts` path:

```bash
python3 ~/.claude/scripts/claude-code-whats-new.py
```

`claude-memory-sync` is withheld as well. A deletion or merge it applies
reaches every machine at its next sync, and its output names files without
their content, so an agent runs it from the `scripts` path under the
[supervised memory sync prompt](../prompts/sync-memories.md) and reports each
memory it removed or merged.

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
would be a second source of truth for the same state. Remove an installed
plugin with `claude plugin uninstall convene@agent-toolbox`.

Updating a plugin is a separate step, because a plugin does not track the
checkout the way installed components do. The installer creates symlinks, so
`git pull` changes what a skill or script does immediately. A plugin is
copied into `~/.claude/plugins/cache/<marketplace>/<name>/<version>/`, so the
same pull leaves it running the old code until you update it:

```bash
claude plugin marketplace update agent-toolbox
claude plugin update convene@agent-toolbox
```

The update compares **version strings, not commits**. A plugin whose
`version` has not changed reports "already at the latest version" and copies
nothing, however far the checkout has moved. Changing a plugin therefore
means bumping `version` in both its `.claude-plugin/plugin.json` and its
entry in the root marketplace manifest; `claude plugin tag` validates that
the two agree. Without that bump no installed copy will ever see the change.

The update applies after Claude Code restarts. `/sync` performs this step
for every plugin in the marketplace manifest, which is the reason to sync
rather than to pull alone. Check what a plugin costs every session, and what
it is currently pinned to, with:

```bash
claude plugin details convene@agent-toolbox
claude plugin list --json
```

To remove an installation, remove only its symlinks; remove any hook or
statusline registration before removing the script it runs. The installer
never imports local configuration or content back into the repository.
