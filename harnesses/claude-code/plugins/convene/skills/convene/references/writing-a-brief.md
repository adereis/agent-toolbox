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

**Check the ignore rules before seats write code.** A worktree seat's
patch carries every new file git does not ignore, because a seat that
creates a source file seldom stages it. Build output rides along the same
way: a fanout over a Python project with no `__pycache__/` in its
`.gitignore` hands every attempt that ran its tests a patch full of
bytecode, and the judge marks it down for that. Seats are told to delete
what they do not mean to submit, and the cheaper ones do not always
listen; fix the ignore rules in the project instead.

**Keep it short.** Everything the seat needs is in the materials. A
brief longer than a screen is usually a review in disguise.
