---
name: agent-toolbox-sync
description: Install selected Agent Toolbox components with the deterministic installer and update its Claude Code plugins. Use from a checkout of this repository when asked to sync, install or update the toolbox.
---

Install selected Agent Toolbox components using the deterministic installer.

Run from this repository. Use the scope and components requested by the
user; default to Claude Code, user scope, skills, scripts, and commands:

```bash
python3 tools/install.py --harness claude-code --scope user \
  --component skills --component scripts --component commands
```

`commands` is user scope only; drop it when installing to project scope.

That default is a selection, not the whole catalog. `instructions` and
`prompts` are deliberately outside it, because a policy module and a task
prompt are things a person opts into rather than receives by default. Name
what the default omits when reporting a sync, so an omission is a visible
choice rather than a silent one, and offer the components the user's request
implies. A user asking for baseline adoption needs `instructions`, since
[the prompt](../../../prompts/adopt-baseline.md) stops when the module is
missing.

Weigh scope against session cost before installing. A skill advertises
itself in every session at the scope it was installed to, while prompts,
instruction modules and scripts cost nothing until they are read; see
`docs/installation.md` under "What a component costs a session". Prefer
`--scope project` for a workflow belonging to one repository, and say what a
user-scope install will be present in every session for.

Review the dry-run output. If the user requested installation or sync, apply
that same selection with `--apply`. Conflicting files are preserved: report
the paths and resolve the conflict within the user's authorization before
retrying. Do not add a separate permission step for an already authorized
installation.

`scripts` links every harness utility under the harness root, where skills
reach them by path. `commands` links only the utilities a person runs, into
`~/.local/bin` without the file extension. The two overlap by design: the
same script can be a path the agent reads and a name you type. Do not add
the `whats-new` utilities or `claude-memory-sync` to `commands`;
`tools/install.py` records why, and `tests/test_installer.py` enforces it.
Memory sync runs under an agent following
[the supervised procedure](../../../prompts/sync-memories.md), because its
deletions and merges reach every machine.

## Plugins

Plugins are not installer components and `tools/install.py` has no `plugin`
component, because Claude Code owns the registry at
`~/.claude/plugins/installed_plugins.json` and a second writer would be a
second source of truth. Sync them here instead, with Claude Code's own
commands.

Cover them on every sync, because a plugin follows the checkout only when
Claude Code reads it in place. Installer components are symlinks into the
checkout, so a `git pull` updates them immediately. Whether a plugin does
the same depends on where Claude Code loads it from, and
`claude plugin list --json` records that for each plugin:

- **Read in place.** A `readFromFolder` field naming this checkout means
  Claude Code loads the plugin from the checkout itself, as Claude Code
  2.1.301 does for a marketplace added from a local path. The next session
  runs whatever is checked out, so report the plugin as current without
  updating it. Its copy under `~/.claude/plugins/cache/` is a leftover that
  nothing loads, and a difference between that copy and the checkout is not
  staleness. A `readFromFolder` naming another path means the plugin follows
  that checkout instead; report the path rather than updating.
- **Copied.** Without `readFromFolder`, the plugin runs from
  `~/.claude/plugins/cache/<marketplace>/<name>/<version>/`, and a pull
  leaves it stale until it is updated explicitly.

When the listing is ambiguous, confirm which root a session actually loads
from its init event. This spends one short model turn:

```bash
claude -p "Reply OK." --output-format stream-json --verbose --max-turns 1 \
  --no-session-persistence |
  python3 -c 'import json, sys
for e in map(json.loads, sys.stdin):
    if e.get("subtype") == "init":
        print(*(p["source"] + " " + p["path"] for p in e["plugins"]), sep="\n")'
```

For a copied plugin, `claude plugin update` compares version strings, not
commits: a plugin whose `version` is unchanged reports "already at the
latest version" and copies nothing, however far the checkout has moved.
Before updating, compare each manifest `version` against the installed one
from `claude plugin list --json`. When the checkout has changed a copied
plugin but not its version, say so and stop rather than reporting a
successful sync: the fix is to bump `version` in both the plugin's
`.claude-plugin/plugin.json` and its marketplace entry, which `claude plugin
tag` validates, and that is a release decision for the user. A plugin read
in place runs new code without a bump, so do not propose one as a sync step.

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
which scope, read in place from which checkout, or copied and possibly
behind the checkout. On apply:

```bash
claude plugin marketplace update agent-toolbox             # refresh first
claude plugin install <name>@agent-toolbox --scope user    # absent
claude plugin update <name>@agent-toolbox                  # copied
```

Use the scope the user selected for this sync; plugin scopes are `user`,
`project`, and `local`. An update to a copied plugin applies only after
Claude Code restarts, so say that rather than implying the new version is
live. A plugin read in place picks up a pull at the next session.

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
