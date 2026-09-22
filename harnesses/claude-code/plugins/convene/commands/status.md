---
description: Show the status of the latest convene run for this project, or of a named run
argument-hint: "[run name]"
disable-model-invocation: true
---

Run `${CLAUDE_PLUGIN_ROOT}/bin/convene status $ARGUMENTS` and report it.
With no argument it shows the latest run for this project. A held round
is a provider quota stop, not a failure: name the seat and the reset time.
Repeat every red flag verbatim.

The last line of the output names the command to run next; pass it on
rather than working one out. Do not run it without being asked: `run`,
`continue` and `promote` all spend the user's provider quota.

If the user wants the posts, `${CLAUDE_PLUGIN_ROOT}/bin/convene board`
prints the published board attributed by seat and model.
