---
name: whats-new
description: Report harness releases since the last digest against the local configuration, or trace when a feature or fix landed.
---

# Release digest workflow

The digest utility does the mechanical work: it picks a release window,
removes entries another host or platform owns, and tags every remaining
bullet with the parts of this machine's configuration it touches. It
deliberately does not decide what matters. That judgement is the task.

## Reporting what changed

1. Run the utility with no window argument. It covers every release after the
   stored baseline, or the most recent few when no baseline exists yet.
2. Read the `## Environment` block before the bullets. It states the settings,
   hooks, plugins, MCP servers, and platform the tags were derived from, and
   it is the evidence for every claim about relevance.
3. Sort the bullets into three groups, most consequential first:
   - **Act on this** — behavior that changed under an existing setting, or a
     new option worth adopting given how this machine is configured. Each
     entry asks the user to do or decide something. An item that changes
     nothing here belongs under Worth knowing, or nowhere.
   - **Fixed for you** — bugs this configuration was plausibly hitting.
   - **Worth knowing** — new capability that touches the user's workflow
     without needing a decision.
   Omit a group that has no entries rather than padding it.
4. Name the release for each item, and say *why* it applies here, citing the
   configuration: "you run `defaultMode: auto`", not "this may affect you".
5. Close with the counts the utility reported: bullets withheld as belonging
   to another host, and bullets that matched no signal. The user needs to know
   the size of what was not discussed.
6. Advance the baseline only after presenting the digest, and only for a
   window report. A topic search must never move it.

## Tracing a topic

Pass the feature's several names as alternative patterns, because a
capability is often renamed between its introduction and the present. Report
the release that introduced it, the dates, and the later entries that
refined, fixed, or reversed it — an arc, not a list. Say plainly when the
search terms may have missed an earlier name for the same thing.

## Rules

- Never paste the raw digest back. It is input to be read, not output to be
  forwarded; a digest that is merely reprinted has done nothing for the user.
- A tag means the bullet mentions something configured here. It is a reason to
  look, not proof of impact. Read the bullet before asserting it applies.
- Untagged bullets are not noise. A capability that did not exist cannot match
  a setting, so genuinely new features often carry no configuration tag.
- Settle an item's condition before handing the user a check. Look first in
  the environment block, and read the condition in the bullet itself: an
  entry that applies "when telemetry is off" does not apply where telemetry
  is on. When the block cannot decide it, check narrowly: count or match the
  one detail, such as the rules naming one tool, and never print a settings
  file or its values. Those can hold credentials, and a harness's own
  permission checks may refuse a broad read. When even a narrow check is not
  possible, name the detail that decides the item instead of telling the
  user to look.
- The terminal is identified from the variables it sets for itself, not from
  `TERM`, which a wrapper or profile may rewrite. When the environment block
  reports that `TERM` does not name the detected terminal, say so: it is a
  configuration choice worth examining, and it places the user in a
  combination the harness tests less often.
- Terminal entries are tagged but never filtered. Several terminals share the
  kitty keyboard protocol, and one entry often names a handful of them.
- Withheld and unmatched counts are always reported, never rounded away.
- If the window is wide enough that the utility refuses it, narrow it or
  request only signal-matching bullets. Do not work around the limit by
  reading the changelog file directly.
