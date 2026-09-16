# Optional instruction modules

[Global baseline](global-baseline.md) is the authoritative source for shared
agent policy: temporary files, environment, Git history, documentation, data
protection, context hygiene, quality standards, project setup, and Python
environments. It holds nothing harness-specific, so paths, event payloads,
agent delegation, and attribution formats stay in the harness that owns them.

[Reviewable changes](reviewable-changes.md) is a reusable policy module for
focused changes, evidence-backed verification, and explanatory Git history.

Copy or reference selected modules from your harness's project instructions
when you want them to apply. Installing these files does not activate them or
overwrite `AGENTS.md`, `CLAUDE.md`, or user-level instructions.

## Adopting the baseline

Merging shared policy into a global instruction file that also holds personal
and harness-specific rules requires judgment, so the installer does not
attempt it. The [baseline adoption workflow](../skills/adopt-baseline/SKILL.md)
performs that merge and reconciles later drift.

Adoption is not equally enforced across harnesses. Claude Code loads `@path`
imports with the file that declares them, so an import line makes the module
apply unconditionally. Codex discovers `AGENTS.md` files up the directory tree
and has no import syntax for them, so the text must be present in the file
itself and is a maintained copy rather than a link.
