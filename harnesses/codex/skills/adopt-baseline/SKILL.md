---
name: adopt-baseline
description: Adopt or reconcile the shared global baseline in the Codex global instruction file
---

Read and follow the shared [baseline adoption workflow](references/workflow.md).

Global instruction file: `$CODEX_HOME/AGENTS.md`, or `~/.codex/AGENTS.md` when
that variable is unset. Installed module: `~/.agents/instructions/global-baseline.md`
at user scope, or `<project>/.agents/instructions/global-baseline.md`.

Codex discovers `AGENTS.md` files up the directory tree and has no import
syntax for them; this was checked against Codex CLI 0.154.0. Shared policy
therefore only reaches the model when the text is present in the file itself.
Inline the module's sections, shifting their heading depth to sit beneath the
file's existing top-level heading, and keep them in the module's order.

Use no marker comments. On reconciliation, match sections by heading and
compare their bodies against the module. Because the copy is maintained
rather than linked, it can drift: say so when reporting, and do not describe
the Codex copy as equivalent to an automatically loaded import.
