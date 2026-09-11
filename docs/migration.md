# Migration to Agent Toolbox

The `claude-code-baseline` tag preserves the previous collection. Harness
components moved from the root into `harnesses/claude-code/`; update any
checkout-relative paths, aliases, or symlinks you maintain.

## Retired hooks

Remove these command registrations from your Claude Code settings before
removing the corresponding installed files:

- `tmp-write-guard.sh`
- `tmp-home-allow.sh`
- `test-edit-guard.sh`
- `continue-plan.sh`

Check both user and project scopes, including `settings.local.json`. Preserve
other commands in shared matcher groups. Back up settings and installed
files before editing; start a fresh Claude session after changing hooks.

Directory denial and edit-context examples now live under
[`examples/claude-code/hooks/`](../examples/claude-code/hooks/README.md). They
are reference implementations and must not be automatically deployed.
The obsolete plan continuation hook has no replacement.
