# Claude Code integration

- [Session and memory utilities](scripts/README.md)
- [Statusline configuration](settings/README.md)
- [Supported hooks](hooks/README.md)
- [Local agent configuration patterns](agents/README.md)

Use the [scoped installer](../../docs/installation.md) to link selected
components from this checkout. Hook and statusline activation remains an
explicit settings change in the intended scope.

The `teach` skill is a thin explicit-invocation entry point to the shared
workflow under `skills/teach/`. Its `references/workflow.md` link resolves
to that canonical source both in the checkout and when installed.

The old reviewer/verifier pairs and tmp, test-edit, and continue-plan hooks
are retired. See the [migration notes](../../docs/migration.md).
