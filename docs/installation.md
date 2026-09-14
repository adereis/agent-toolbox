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

| Scope | Claude Code root | Codex root |
|-------|------------------|------------|
| User | `$CLAUDE_CONFIG_DIR` or `~/.claude` | `~/.agents` |
| Project | `<project>/.claude` | `<project>/.agents` |

`--target PATH` explicitly replaces the installation root, useful for staging
or a custom setup. Custom targets are not automatically added to native
harness discovery paths. Codex user skills are shared across its profiles;
use project scope for a project-specific installation. This installer does
not change `CODEX_HOME` or partition native session history.

| Component | Claude Code | Codex | Installation behavior |
|-----------|-------------|-------|-----------------------|
| `skills` | Yes | Yes | Installs the shared `teach` workflow with native explicit-invocation metadata; Claude Code also gets the `whats-new` release digest |
| `scripts` | Yes | Yes | Links harness utilities under `<root>/scripts/` |
| `hooks` | Yes | Unavailable | Links the remaining hook scripts; registration is manual |
| `settings` | Yes | Unavailable | Links statusline scripts at the Claude configuration root |
| `prompts` | Yes | Yes | Links plain text under `<root>/prompts/`; no automatic invocation |
| `instructions` | Yes | Yes | Links opt-in modules under `<root>/instructions/`; no policy files overwritten |

The installer reports unavailable combinations, missing source files, and
conflicts. It checks every destination before changing anything and refuses
to overwrite regular files or links to other sources. Back up and resolve
conflicts explicitly before retrying. Repeated installation is idempotent.
It does not follow symlinked parent directories beneath the chosen root.
On a creation failure, it removes links created by that invocation while
preserving concurrently changed entries; empty directories may remain.

Installing hook or statusline scripts does not enable them. Apply the
configuration documented under the Claude [hooks](../harnesses/claude-code/hooks/README.md)
or [settings](../harnesses/claude-code/settings/README.md) pages to the scope
you selected, using the actual installed script path. Reference examples and
retired components are excluded from the installer.

Run installed session utilities from a terminal, for example:

```bash
python3 ~/.agents/scripts/codex-code-session-resume.py --all
python3 ~/.claude/scripts/claude-code-session-resume.py --all
```

You can also symlink a session entry point directly onto your `PATH`:

```bash
mkdir -p ~/bin
ln -s "$PWD/harnesses/codex/scripts/codex-code-session-resume.py" ~/bin/
```

To remove an installation, remove only its symlinks; remove any hook or
statusline registration before removing the script it runs. The installer
never imports local configuration or content back into the repository.
