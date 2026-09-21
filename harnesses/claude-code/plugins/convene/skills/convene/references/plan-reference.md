# Plan reference

A plan is a TOML or JSON table. `convene prepare` validates it, resolves
every reference and freezes it as `plan.json` in the run directory. The
annotated template is `templates/panel.toml`.

| Field | Default | Meaning |
|---|---|---|
| `schema` | 1 | plan format version |
| `kind` | `panel` | `panel`, `room`, `fanout`; this version runs one round of any kind |
| `title` | required | shown in status and export |
| `rounds` | 1 | this version accepts 1 |
| `jobs` | 1 | seats run in parallel per round |
| `harness` | `claude` | seat default: `claude` or `codex` |
| `model` | `opus` | seat default; verified against the served model |
| `effort` | `high` | seat default; harness-specific values |
| `tools` | `read` | seat default: `none`, `read`, `write`, `research` |
| `isolation` | `strongest` | seat default: `strongest`, `enforced`, `private-home`, `none` |
| `visibility` | `board` | seat default: `board` or `blind`; matters from round 2 |
| `workspace` | `none` (`repo-ro` for a panel) | seat default: `none`, `repo-ro` |
| `compaction` | `forbid` | `forbid` pins the whole context window; `allow` lets the harness compact |
| `persona` | none | seat default persona id |
| `grants` | `[]` | doors opened for every seat: `web`, `mcp`, `settings`, `instructions`, `hooks` |
| `claude_args`, `codex_args` | `[]` | raw arguments appended to that harness's command line |
| `env` | `[]` | operator environment variable names passed through to seats |
| `instrument` | `review` for a panel | what every seat is asked to produce |
| `brief` | required | `{ text = "..." }` or `{ path = "brief.md" }` (relative to the plan) |
| `materials` | `[]` | common materials: `{ path, label, source?, relative_to? }` or `{ path, text, label }` |
| `panel.range` | none | `A..B` or `HEAD`; `--range` on the command line overrides it |
| `seats` | required | list of seats; every seat default above may be repeated per seat |
| `seats[].id` | required | an identifier; appears on the board |
| `seats[].persona` | plan default | persona id, `id@revision`, or `{ inline = {...} }` |
| `seats[].materials` | `[]` | private materials for this seat |
| `seats[].grants`, `seats[].args`, `seats[].env` | plan default | this seat's doors; `args` are for its own harness |
| `phases` | one phase | this version accepts one phase and no deliverables |
| `synthesis.by` | `operator` | this version accepts `operator` |

Defaults for every plan come from `$XDG_CONFIG_HOME/agent-toolbox/convene.toml`
and `<project>/.convene/config.toml`, which accept the seat-default keys
above and nothing else. `prepare --grant DOOR` and `--tools SET` override
the defaults for one run.

Material paths are relative to the project root unless
`relative_to = "plan"`. Instruction files (`AGENTS.md`, `CLAUDE.md`,
`.claude/`, `.codex/`) are refused as materials. A `label` is what the
seats are told about the file.

## Run directory

```
plan.json  plan-digest.json  run.log  run.lock
work/<seat>/{START.md, materials/, outbox/, board/}
homes/<seat>/{claude,codex}/          private harness homes
board/posts/<seat>/rNNN.md            promoted posts
board/rounds/rNNN/{digest.md,digest.json}
records/<seat>/state.json
records/<seat>/rNNN/{prompt.md,launch.json,events.jsonl,stderr.log,receipt.json,answer.md}
```

`launch.json` records the harness argv, the isolation wrapper, the tier
attestation and the names (never the values) of the environment
variables the seat received. `receipt.json` records what actually ran:
session id, served model against the requested one, usage, tool calls,
compaction markers, quota classification and red flags.
