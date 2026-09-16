---
name: adopt-baseline
description: Adopt or reconcile the shared global baseline in the Claude Code global instruction file
disable-model-invocation: true
---

Read and follow the shared [baseline adoption workflow](references/workflow.md).

Global instruction file: `$CLAUDE_CONFIG_DIR/CLAUDE.md`, or `~/.claude/CLAUDE.md`
when that variable is unset. Installed module: `instructions/global-baseline.md`
beneath the same root.

Claude Code loads `@path` imports with the file that declares them, so adopt
the module with a single relative import line in `CLAUDE.md`:

```markdown
@instructions/global-baseline.md
```

The path resolves against the importing file's directory, which keeps the
import correct under a custom `CLAUDE_CONFIG_DIR`. The baseline then applies
unconditionally, so its sections must not also appear verbatim in `CLAUDE.md`.
An unresolved import is silent; verify the module is installed before relying
on it, and report an unsatisfied import instead of inlining the text.
