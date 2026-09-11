---
name: commit-review
description: Review commits for code quality issues
argument-hint: "[commit-range]"
disable-model-invocation: true
context: fork
agent: commit-reviewer
---

Analyze commits for code quality issues.

**Commit range**: No arg = unpushed commits (vs upstream, or main/master if no upstream); `HEAD~3` = last 3; or any git range.

Review: $ARGUMENTS
