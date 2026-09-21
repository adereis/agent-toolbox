# Interactive Tests

Tests that require live harness sessions or account access. Run the relevant
checks explicitly (e.g., "run the interactive tests" or "test the push hook
live"). Automated test results do not imply these checks ran.

The automated runner (`./tests/run.sh`) makes no real model calls and uses
no model tokens. It uses fake Codex/keyring executables, mocked launch and
network calls, and a local HTTP server. The live checks below can consume
subscription quota or incur API charges when explicitly invoked.

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

**Keyring wrapper:** Store the key with `codex-api-profile.sh --store` and
confirm `--status` reports `stored` without printing it. Start
`codex-api-profile.sh`, check `/status` for the `openai_api` provider, and
send a small prompt. Confirm `codex login status` still reports ChatGPT
afterwards. On macOS, confirm the wrapper exits naming the `security`
commands rather than running; the stubbed paths are covered by
`tests/test_codex_api_profile.sh`, but the real macOS keychain is not.

**Preservation and resume:** After the API run, verify `codex login status`
still reports ChatGPT. Resume a subscription session with `--profile api`
and the API variable supplied, and confirm the selected provider in
`/status`. Verify the session browser can pass both profile names through.

**Mismatch check:** Only in a disposable `CODEX_HOME` under a private
`mktemp -d "$HOME/tmp/codex-auth.XXXXXXXX"` directory, check that the
subscription profile rejects an API-key login. Codex may clear that saved
login; never run this check against an account store you intend to preserve.

## IT-08: Codex tmux display

**Prerequisites:** Linux, tmux 3.2+, Python 3.11+, Git, installed Codex profiles,
and the IT-07 authentication setup. `./tests/run.sh codex_tmux` runs real
isolated tmux servers with synthetic Codex/keyring processes and an attached
pseudo-terminal. It does not validate account-backed Codex telemetry.

**Subscription:** Run `codex-tmux.py`, submit a small prompt, and check model,
effort, context, process memory, and subscription profile. Compare quotas
with `/status`. Check the model after changing it. Observe the display at
wide and narrow terminal widths. The context percentage intentionally uses
raw reported usage, whereas Codex's native footer subtracts a baseline.

**API:** When paid API testing is requested, run
`codex-tmux.py --backend api`, submit a small prompt, and confirm `api` in
the display. The estimate should advance without quota columns. Check
`codex login status` afterwards to verify the saved ChatGPT login remains.
Do not capture credentials or real session contents in fixtures.

**Concurrency and resume:** Run distinct subscription and API sessions in
the same project and store. Give them different effort settings and verify
each footer follows its own session. Exit one and confirm the other keeps
running. Resume an existing session under the other backend and check that
the estimate starts afresh and old quota/plan labels do not carry over.

**Mouse and trackpad scrolling:** In a new wrapper session with several
screens of messages and tool output, scroll up with the pointer over the
output and then over the input box. Earlier output should move into view
without changing the draft or selecting an older prompt. Scroll down to
the bottom and confirm typing works immediately. Repeat using `q` and
`Escape` to leave scrollback, including while Codex generates output.
Check Page Up/Page Down after `Ctrl-b [` and terminal-native text selection
with Shift-drag (or the terminal's mouse override modifier). Repeat after
detach/reattach and inside an existing tmux server with mouse forwarding
enabled. Confirm the outer server's options are unchanged. The automated
tests inject SGR and legacy X10 wheel events through a real attached tmux
client; physical trackpad behavior still requires this terminal check.

**Detach and cleanup:** Detach with `Ctrl-b d` and use the printed `--attach`
command. Confirm the session and estimate survive. Repeat from inside an
existing tmux server and verify its options remain intact. Exit Codex and
check that the wrapper returns its exit status and removes its private
runtime directory. If Codex exits while detached, reattach once to collect
the exit status and clean up.

**Exit output:** Exit normally with Ctrl+D after a turn. Confirm the token
summary and native resume command remain on the calling terminal after
tmux closes. Repeat in a narrow terminal and verify the replayed resume
command is a single copyable line. Check `--help` for separate examples,
requirements, session/key behavior, and service-tier/cost sections.

## IT-09: Convene panel with live seats

**Prerequisites:** the plugin loaded (`claude --plugin-dir
harnesses/claude-code/plugins/convene`, or installed from the checkout
marketplace), `claude` and `codex` logged in, and on Linux `bwrap` on PATH.
One cheap seat per harness (Claude `haiku`, the cheapest Codex slug the
catalog lists) keeps the cost to a short exchange each.

**Doctor:** `bin/convene doctor`. Expected: both harnesses with versions and
`credentials present`, every probe `✓`, and `isolation enforced` available
on Linux. A `✗` on a probe means a flag the blindness relies on went dead
in an upgrade; stop there.

**Panel:** `/convene:panel HEAD~3..HEAD seat=claude/haiku seat=codex/<slug>`
in this repository. Expected: `prepare` prints `isolation=enforced` per seat
on Linux (`private-home` on macOS), `run` posts both seats, and the
synthesis cites both by id. Inspect `records/<seat>/r001/receipt.json` in
the run directory: `model` is the served id (`claude-haiku-*` for `haiku`;
the exact slug for Codex), `isolation.tier` matches what `prepare` printed,
`tool_calls` is small, `compaction_observed` is false, `inputs_intact` is
true. `launch.json` lists environment variable names only; grep the run
directory for the access token and find nothing.

**Canary (enforced tier):** prepare a plan with `workspace = "none"` and a
brief asking the seat to report what is in its `HOME`, whether it can read
this checkout's `AGENTS.md` by absolute path, and which tools it has.
Expected: an empty home apart from the harness's own directory, the read
fails, no `mcp__*` or web tools. Repeat with `isolation = "private-home"`:
the read succeeds, and the receipt's red flags say `isolation is advisory`.

**Quota hold:** only when a quota window is genuinely exhausted, run a
panel and confirm `status` reports the round as HELD with the seat and the
reset time, and that `board` prints nothing for that round.

## IT-10: Convene room with a worktree drafter

**Prerequisites:** as IT-09. Two cheap seats over two rounds keep the cost
to four short exchanges.

**Room:** a plan from `templates/room.toml` with two seats (Claude `haiku`
as the drafter with `tools = "write"` and `workspace = "worktree"`, a Codex
seat as the other) and two phases, `discuss` (both) then `draft` (drafter
only), on the enforced tier. Run it with `bin/convene run NAME`. Expected:
round two resumes both sessions (`launch.json` shows `--resume` or
`resume SID` and the receipt's `session_id` equals round one's); the
drafter's `changes.patch` appears under `board/made/drafter/r002/` and on
the round-two digest; `git -C <project> worktree list` shows the seat's
worktree and the operator's checkout has no changes; the drafter's
receipt shows `isolation.worktree_git` naming the project's `.git`.
`bin/convene prune NAME` removes the worktree and the private homes, and
`git worktree list` no longer shows it.

**Hold and continue:** only when a quota window is genuinely exhausted:
`status` reports HELD with the seat, `continue NAME SEAT` after the reset
answers in the same session (interrupted) or with the same prompt
(refused), `promote NAME N` publishes, and `run NAME` finishes the phases.

## IT-11: Convene fanout read sealed

**Prerequisites:** as IT-09. Two cheap seats on two harnesses, one round.

**Fanout:** a plan from `templates/fanout.toml` with two seats (Claude
`haiku`, a Codex slug) and a small brief, enforced tier. After `run`,
`bin/convene board NAME` must refuse naming `convene seal`; `seal` must
print letters and the judgment path and never the key; `sealed/r001/A`
and `B` must each hold `post.md`, `report.md` and `changes.patch`;
`status` must show `withheld` for seconds and tool calls; `unseal` must
refuse until `judgment.md` has text, then print `A = <seat> (<harness>/
<model>)`, after which `board` is attributed and `usage` prints.
