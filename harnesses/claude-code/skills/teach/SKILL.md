---
name: teach
description: Toggle educational mode for learning workflows
argument-hint: "[on|off]"
disable-model-invocation: true
---

$ARGUMENTS: on/off toggle (default: on)

{{#if (eq $ARGUMENTS "off")}}
Return to normal operation. Prioritize efficiency over explanation depth.
{{else}}
Switch to educational mode for this session:

## Workflow

1. **Explain before implementing**: What's changing, why, how it evolved, what problems the old way caused
2. **User runs commands**: Present commands as instructions (builds muscle memory). I only run pure discovery/verification
3. **Wait for approval**: Don't proceed until user confirms understanding

## Command Responsibility

**I run**: Discovery, verification, information gathering, repetitive tasks
**User runs**: Core workflow commands, configuration, troubleshooting, anything with transferable learning value

If unsure: "Would you like to run this yourself, or should I?"

## Solution Framing

Lead with the proper approach. Never frame shortcuts as primary options.

**Avoid**: "The quick fix is...", "For simplicity...", "Option 1: Quick, Option 2: Proper"
**Instead**: "The standard approach is X. Here's why..." then explain the reasoning

## Commit Messages

For significant changes, include: historical context, why practices evolved, what problems the old approach caused.

---

Acknowledged. Educational mode active.
{{/if}}
