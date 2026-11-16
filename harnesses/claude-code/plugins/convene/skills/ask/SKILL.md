---
name: ask
description: "Ask another model's own CLI session a question, as you would a subagent: Codex (\"ask codex sol\", terra, luna), Claude (\"ask opus\"), Antigravity (\"ask agy\", \"ask gemini\"). Use when the user names one of those to ask, consult, get a second opinion from, or follow up with. Runs `convene ask`, an isolated native session with a receipt."
---

# Ask another model

`convene ask` is the subagent call for other harnesses. It starts one
independent native session (`codex exec`, `claude -p` or `agy`), gives it
your question, and prints its answer. The session is closed the way every
convene seat is: no web, no MCP servers, no operator settings, no project
instruction files, and the repository read-only. A receipt says which model
was actually served and how the seat was isolated. Follow-ups resume the
same session, so the seat remembers the conversation.

The engine is `convene`. Inside Claude Code it is
`${CLAUDE_PLUGIN_ROOT}/bin/convene`. With the toolbox's `commands`
component installed, `convene` is on PATH. In a checkout it is
`harnesses/claude-code/plugins/convene/bin/convene`. `convene ask --help`
has the full usage.

## Naming the seat

The user names a harness and maybe a model family. Pass it as
`HARNESS/FAMILY`:

| The user says | Seat |
|---|---|
| codex, ask codex | `codex` (its default family) |
| codex sol, sol, terra, luna | `codex/sol`, `codex/terra`, `codex/luna` |
| claude, opus, sonnet, haiku | `claude/opus`, `claude/sonnet`, `claude/haiku` |
| agy, antigravity, gemini, gemini pro | `agy/gemini-pro` |
| gemini flash | `agy/gemini-flash` |

Name a family, never a version, unless the user named a version. The
engine resolves the family to the newest model that harness lists and
prints what it chose, as in `gpt-6.1-sol (from sol)`. It refuses a name
no catalog can place and lists the families that exist; report that
rather than guessing another. Bare `gemini` is ambiguous between Flash
and Pro, which is why the table maps it to Pro.

## Writing the question

The seat sees none of this conversation. Write the question the way you
would brief a subagent:
- say what you need answered and why;
- name the files, commits or commands it concerns;
- say what you already know or have ruled out.

When the user wants an independent view, leave your own conclusion out,
because a seat handed your hypothesis tends to confirm it.

The seat runs at the project's git top level and can read the working
tree, uncommitted changes included. Outside a git checkout it gets no
files at all. Put a question with quotes, backticks or several
paragraphs in a file and pass `-` to read it from standard input:
`convene ask codex/sol - < question.md`.

## Running it

```bash
convene ask codex/sol "Is the retry loop in src/net.py bounded on timeout?"
```

A turn takes minutes. Where your harness can run a command in the
background and notify you when it exits, do that and keep working. In
Claude Code that is Bash with `run_in_background`; set no short timeout.
Otherwise run it in the foreground with a timeout of at least ten minutes.
Several asks to different harnesses can run at once.

Options go before or after the seat:
- `--no-repo` withholds the repository.
- `--persona ID` swaps the default `consultant` for a reviewer from
  `convene personas`.
- `--tools none|read|research` sets the tool set. The default is `read`.
- `--grant web` opens web search and fetch. Open it only when the user
  asked for it or the question cannot be answered without it, and say so
  when you report.
- `--effort LEVEL` passes the harness's own effort level.

## Reading the result

The output is the answer, then one line starting `---` with the run name,
the served model, the isolation tier and the tool count. Then come
`!` red flags, then a `next:` line.

The exit status says how the turn ended:
- **0, answered.** Report the answer as the seat's, attributed to the
  served model, for example "Codex (gpt-6.1-sol) says: …". Repeat every
  red flag verbatim. Treat the answer as you would a subagent's report:
  check a claim against the code before acting on it.
- **3, held by a provider quota.** Tell the user which seat stopped and
  when the window resets. Retrying spends the user's quota, so run
  nothing more unless they ask. Once it resets, the `next:` line names
  the commands: `convene continue NAME SEAT`, then `convene promote NAME N`.
  After that, `convene board NAME --round N` shows the answer.
- **1, failed or refused.** Report the error as written. A Codex seat
  stopped because its app server listed MCP servers did not call a model.
  Never pass `--grant mcp` just to make it run.

## Following up

```bash
convene ask --to NAME "And what happens when the timeout is zero?"
```

`NAME` is the run name from the `---` line. The seat resumes its own
session on the same model version, so write the follow-up as the next
message of a conversation, not as a fresh brief. Persona, tools and doors
are fixed when the ask starts. Ask again from scratch for a different
seat or a different topic.

## When to use something else

- Several models on the same question, a design discussion, or blind
  competing implementations: that is a convene panel, room or fanout.
  Use the `convene` skill, which proposes the plan before it spends quota.
- A helper on your own harness with your tools and context: use your
  harness's own subagent.

## Housekeeping

Each ask keeps its records under `~/.local/state/agent-toolbox/convene/`
and the seat's private home under `~/.cache/agent-toolbox/convene/`. The
home is what makes a follow-up possible. `convene runs` lists them. When
the user is done with those conversations, `convene prune --finished`
frees the homes and keeps every record; after that, those asks take no
more follow-ups. Offer it; do not run it unasked.
