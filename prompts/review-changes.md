Review the requested changes against their intended behavior and applicable
repository conventions. Establish the comparison base and scope from the
request and Git state; identify any ambiguity before drawing conclusions.

Prioritize actionable correctness bugs, regressions, security problems,
and missing behavior. Read enough surrounding code and callers to explain
each finding. Check relevant tests and documentation and run focused checks
when they can resolve uncertainty. Preserve unrelated working-tree changes.

For each finding, state its severity, file and line, concrete triggering
conditions, impact, and evidence. Separate confirmed defects from questions
and suggestions. Do not infer that repeated edits to a file or tests written
before implementation are defects by themselves.

Report which checks ran and their results, plus material gaps in verification.
If no actionable findings remain, say so. Make changes only if requested.
