Install selected Agent Toolbox components using the deterministic installer.

Run from this repository. Use the scope and components requested by the
user; default to Claude Code, user scope, skills and scripts:

```bash
python3 tools/install.py --harness claude-code --scope user \
  --component skills --component scripts
```

Review the dry-run output. If the user requested installation or sync, apply
that same selection with `--apply`. Conflicting files are preserved: report
the paths and resolve the conflict within the user's authorization before
retrying. Do not add a separate permission step for an already authorized
installation.

Hooks and settings are opt-in components. Installing their scripts does not
register hooks or change settings; follow docs/installation.md for the
selected scope when configuration changes are requested.

Do not import user configuration back into the repository or deploy anything
from examples/. Retired names and migration instructions are listed in
docs/migration.md. Keep machine-specific agents and MCP launchers local.
