# Optional prompts

Use these as explicit requests in your preferred harness, adding the commit
range, application URL, or other task context. They are plain text and do
not install agents, select models, or change permissions.

- [Review changes](review-changes.md): correctness and maintainability review
  with concrete findings and verification evidence.
- [Verify a web UI](verify-web-ui.md): exercise a running application in a
  browser and check the resulting behavior.

The prompts replace the old Claude-specific reviewer and verifier agent/skill
pairs. A harness's native review or browser facilities can execute the task;
use the facilities actually available in the current environment.
