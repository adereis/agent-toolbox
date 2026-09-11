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

## Retired agents and skills

Remove installed `agents/commit-reviewer.md`, `agents/web-ui-verifier.md`,
`skills/commit-review/`, and `skills/web-ui-verify/` from the Claude
configuration scopes where you previously installed them. Keep a backup of
any local customizations; do not import these obsolete wrappers back into
the collection.

The old agents pinned a model and tool list, coupled browser checks to a
particular machine setup, and treated patterns such as tests preceding an
implementation or consecutive edits to one file as history defects. Those
rules do not reliably indicate a problem. The useful review and browser
verification guidance is retained as short, opt-in
[prompts](../prompts/README.md), without automatic delegation or installation
of browser dependencies.

## Statusline illustration

The terminal screenshot has been removed. The statusline remains supported;
its README uses a generic ASCII example with fictitious values.
