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

Plugins (`harnesses/claude-code/plugins/`) are not installer components.
They install natively: `claude plugin marketplace add <checkout>` then
`claude plugin install convene@agent-toolbox`; see docs/installation.md.

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
