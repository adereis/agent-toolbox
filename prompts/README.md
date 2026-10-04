# Optional prompts

Use these as explicit requests in your preferred harness, adding the commit
range, application URL, or other task context. They are plain text and do
not install agents, select models, or change permissions.

- [Adopt the baseline](adopt-baseline.md): merge
  [the shared policy module](../instructions/global-baseline.md) into a
  global instruction file, and reconcile it after either side changed.
- [Review changes](review-changes.md): correctness and maintainability review
  with concrete findings and verification evidence.
- [Verify a web UI](verify-web-ui.md): exercise a running application in a
  browser and check the resulting behavior.
- [Sync memories](sync-memories.md): run Claude Code's three-way memory sync
  under supervision, accounting for every memory it deletes or merges.
  Claude Code only.

The prompts replace the old Claude-specific reviewer and verifier agent/skill
pairs, and baseline adoption followed them for the same reason. A harness's
native review or browser facilities can execute the task; use the facilities
actually available in the current environment.

A prompt suits a workflow that runs rarely and edits the user's own
configuration. An installed skill announces itself in every session that can
discover it, which is a standing cost for a task performed twice a year; a
prompt is inert text until it is invoked by name.
