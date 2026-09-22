Install selected Agent Toolbox components using the deterministic installer.

Run from this repository. Use the scope and components requested by the
user; default to Claude Code, user scope, skills, scripts, and commands:

```bash
python3 tools/install.py --harness claude-code --scope user \
  --component skills --component scripts --component commands
```

`commands` is user scope only; drop it when installing to project scope.

Review the dry-run output. If the user requested installation or sync, apply
that same selection with `--apply`. Conflicting files are preserved: report
the paths and resolve the conflict within the user's authorization before
retrying. Do not add a separate permission step for an already authorized
installation.

`scripts` links every harness utility under the harness root, where skills
reach them by path. `commands` links only the utilities a person runs, into
`~/.local/bin` without the file extension. The two overlap by design: the
same script can be a path the agent reads and a name you type. Do not add
the `whats-new` or memory utilities to `commands`; `tools/install.py`
records why, and `tests/test_installer.py` enforces it.

## Plugins

Plugins are not installer components and `tools/install.py` has no `plugin`
component, because Claude Code owns the registry at
`~/.claude/plugins/installed_plugins.json` and a second writer would be a
second source of truth. Sync them here instead, with Claude Code's own
commands.

Cover them on every sync, because their update semantics differ from the
rest of the repository. Installer components are symlinks into the checkout,
so a `git pull` updates them immediately. A plugin is copied into
`~/.claude/plugins/cache/` and pinned to the commit it was installed from,
so the same pull leaves it stale until it is updated explicitly.

Read the plugin names from `.claude-plugin/marketplace.json` rather than
naming them here; the manifest is the authoritative list and gains entries
without this file changing. Then:

```bash
# Idempotent: reports the marketplace is already on disk when it is.
claude plugin marketplace add "$PWD"

# Current state, including scope and enabled flag.
claude plugin list --json
```

Report the state with the installer's dry run, before changing anything.
For each plugin in the manifest, name whether it is absent, installed at
which scope, or installed and possibly behind the checkout. On apply:

```bash
claude plugin install <name>@agent-toolbox --scope user   # absent
claude plugin update <name>@agent-toolbox                 # already installed
```

Use the scope the user selected for this sync; plugin scopes are `user`,
`project`, and `local`. An update applies only after Claude Code restarts,
so say that rather than implying the new version is live.

Claude Code only. Codex cannot load plugins and reaches the same engine
through the installer: the `commands` component puts `convene` on `PATH`
and the Codex `skills` component links the plugin's operator procedure.
Sync a Codex request through those components and do not run plugin
commands for it.

A plugin adds always-on session cost in every project it is installed for.
Report it from `claude plugin details <name>@agent-toolbox` when installing
one for the first time, so the scope choice is made against a real number.

Hooks and settings are opt-in components. Installing their scripts does not
register hooks or change settings; follow docs/installation.md for the
selected scope when configuration changes are requested.

Do not import user configuration back into the repository or deploy anything
from examples/. Keep machine-specific agents and MCP launchers local.

Retired names and migration instructions are listed in docs/migration.md.
Read it on a machine you have not synced recently and check the paths it
names. A component dropped from the catalog is no longer inspected, so a
dry run reports no conflict while its files stay installed and active; a
clean run is not evidence that retired components are gone. Report what you
find and remove it only within the user's authorization.
