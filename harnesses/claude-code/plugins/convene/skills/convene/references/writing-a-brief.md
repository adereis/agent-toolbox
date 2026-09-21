# Writing a brief

A brief is what every seat reads before anything else. It sets the task;
it must not set the answer.

**Say what the change is for.** One paragraph: the problem, the
approach the author chose, what a maintainer would want to be true
before merging. The panel preset already tells seats where the diff and
the commit log are, so do not restate the range.

**Say what a good post looks like.** The instrument (`review` by
default) already asks for numbered findings with severity, location and
a failure scenario. Add what is specific to this change: the invariant
that matters most, the platform it must run on, the user it must not
break.

**Do not say what to find.** "Check the error handling in `save()`"
turns three independent reviewers into one reviewer with three
sessions. If you already suspect a defect, keep it for the synthesis
and see whether the seats find it unprompted; that is evidence.

**Do not name models, authors or verdicts.** A seat told "the author
used Codex" or "we think this is fine" weighs the change by its make
rather than by what it does. Material filenames are shown to seats;
give a file a `label` when its name carries any of that.

**Keep it short.** Everything the seat needs is in the materials. A
brief longer than a screen is usually a review in disguise.
