# Interactive Tests

Tests that require live harness sessions or account access. Run the relevant
checks explicitly (e.g., "run the interactive tests" or "test the push hook
live"). Automated test results do not imply these checks ran.

## IT-01: git-push-guard fires on push

**Setup:** Create a temp bare repo and local repo in ~/tmp.
**Action:** Attempt `git push` to the bare repo.
**Expected:** Claude is prompted for confirmation before push executes.
**Teardown:** Remove ~/tmp/test-push-hook/.

## IT-05: statusline displays correctly

**Action:** Observe the Claude Code status bar during normal operation.
**Expected:** Shows user@host:cwd, git branch with indicators, a `session` %
for context fill, and session cost. On a subscription the quota column is
headed `↻HH:MM` — the local time the 5-hour window resets. Cross-check that
time against `/usage`, and check that the two rows stay column-aligned (the
`↻` is the only multi-byte glyph in a header).

## IT-06: Jira MCP is scoped to the `jira` agent (Sonnet only)

Verifies the "model-scoped MCP agent" pattern (see `harnesses/claude-code/agents/README.md`).

**Prereq:** `~/.claude/agents/jira.md` exists with `model: sonnet` and an
`atlassian` server under `mcpServers`, and `atlassian` is removed from global
config (`claude mcp remove atlassian -s user`). Needs a fresh session — MCP
removal only takes effect on restart.
**Action A (main thread):** Ask Claude whether it can see any `mcp__atlassian__*`
tool.
**Expected A:** No — the Atlassian MCP is absent from the main thread.
**Action B (delegation):** Ask Claude to have the `jira` agent look up a
deliberately fictitious issue (`ZZZ-999999`) and report the error and its model.
**Expected B:** The `jira` agent returns "Issue ZZZ-999999 not found" and runs on
Sonnet.
**Authoritative check:** Confirm via structured output, not the agent's
self-report (which can misstate its own model):

    claude -p "Delegate to the jira agent: look up ZZZ-999999, report the error and your model." \
      --settings '{"permissions":{"allow":["Task"]}}' --permission-mode acceptEdits \
      --output-format json | jq '.[]|select(.type=="result")|.modelUsage|keys'

`modelUsage` should include a `claude-sonnet-*` key; the `init` event's
`mcp_servers` should omit `atlassian`.

## IT-07: Codex authentication profiles

**Prerequisites:** Codex CLI 0.134.0 or newer, both profiles installed in the
selected `CODEX_HOME`, a saved ChatGPT login, and a working API key supplied
only to the API process. Use a model available to both accounts. The API
request incurs API usage charges; run it only when requested.

**Subscription:** Start `codex --profile subscription`, check `/status`, and
send a small prompt. Confirm subscription authentication. Exit and confirm
plain `codex` also uses the subscription with the base OpenAI provider.

**API:** Use the private input example in the Codex README to start
`codex --profile api`. Check `/status` for the `openai_api` provider, send a
small prompt, and confirm the request in the API account's usage. With the
variable absent, verify that the API profile reports the missing variable
and does not send a subscription request. Do not record the key in test
output.

**Preservation and resume:** After the API run, verify `codex login status`
still reports ChatGPT. Resume a subscription session with `--profile api`
and the API variable supplied, and confirm the selected provider in
`/status`. Verify the session browser can pass both profile names through.

**Mismatch check:** Only in a disposable `CODEX_HOME` under a private
`mktemp -d "$HOME/tmp/codex-auth.XXXXXXXX"` directory, check that the
subscription profile rejects an API-key login. Codex may clear that saved
login; never run this check against an account store you intend to preserve.
