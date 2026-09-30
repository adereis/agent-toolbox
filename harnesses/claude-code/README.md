# Claude Code integration

- [Session and memory utilities](scripts/README.md)
- [Statusline configuration](settings/README.md)
- [Supported hooks](hooks/README.md)
- [Local agent configuration patterns](agents/README.md)
- [Convene plugin: multi-seat review panels](plugins/convene/README.md)

Use the [scoped installer](../../docs/installation.md) to link selected
components from this checkout. Hook and statusline activation remains an
explicit settings change in the intended scope.

The `teach` skill is a thin explicit-invocation entry point to the shared
workflow under `skills/teach/`. Its `references/workflow.md` link resolves
to that canonical source both in the checkout and when installed.

The `whats-new` skill follows the same split and stays model-invocable, so a
question about what changed reaches it. It supplies the Claude Code command
line and state locations for the shared workflow under `skills/whats-new/`,
and reports the releases published since its last digest against this
machine's configuration. Installing it without the `scripts` component leaves
the skill without the utility it drives.

The skill runs in a forked Sonnet sub-agent at high effort, so the raw
digest and the workflow never enter the calling session; only the finished
report comes back. The sub-agent cannot see the conversation, which is why
the skill asks for the whole question as its argument. It also advances the
baseline just before returning the report rather than after it is read;
`--since` the version the report names brings that digest back.

Plugins under `plugins/` are installed with Claude Code's own plugin
commands, not with the installer; the repository root is a local
marketplace. See the [installation notes](../../docs/installation.md#plugins).

The old reviewer/verifier pairs and tmp, test-edit, and continue-plan hooks
are retired. See the [migration notes](../../docs/migration.md).
