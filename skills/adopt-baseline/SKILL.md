---
name: adopt-baseline
description: Adopt the shared global baseline into a harness's global instruction file, or reconcile it after the module changed.
---

`instructions/global-baseline.md` is the authoritative source for shared
agent policy. A global instruction file also carries harness-specific and
personal rules, so merging the two requires judgment and is not part of the
installer. Perform that merge here and report what moved.

## Read both sides first

Read the installed baseline module and the harness's global instruction
file in full before editing. The harness entry point for this workflow names
both paths and the adoption mechanism that harness supports. Stop and report
if the module is not installed; do not reconstruct it from memory.

## Adopt

Make the baseline effective through the mechanism the harness supports, then
remove the now-duplicated shared sections from the global instruction file.
Leave every harness-specific and personal section in place, including rules
that only make sense for that harness. Preserve the file's existing order and
voice; this is the user's configuration, not a generated artifact.

## Reconcile

On later runs the module is the reference for shared policy. Compare it
against the global instruction file section by section:

- A shared section that drifted returns to the module's wording.
- A local section the module does not cover stays untouched.
- A local rule that contradicts the baseline is reported to the user with
  both wordings. Do not silently resolve it in either direction: the
  contradiction is either a deliberate harness exception or a stale copy,
  and only the user knows which.

Content that a harness cannot load unconditionally must not be described as
enforced. State plainly which harnesses receive the baseline automatically
and which require the text to be present in the file itself.

## Report

List the sections added, removed, rewritten, and left alone, and name any
contradiction awaiting a decision. Never copy content from a global
instruction file back into the repository.
