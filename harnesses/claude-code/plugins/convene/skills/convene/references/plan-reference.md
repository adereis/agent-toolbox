# Plan reference

A plan is a TOML or JSON table. `convene prepare` validates it, resolves
every reference and freezes it as `plan.json` in the run directory. The
annotated template is `templates/panel.toml`.

| Field | Default | Meaning |
|---|---|---|
| `schema` | 1 | plan format version |
| `kind` | `panel` | `panel`, `room` or `fanout`; a fanout fixes `visibility = "blind"`, `workspace = "worktree"`, `tools = "write"`; when it declares no phases its one attempt phase asks for `report.md` |
| `title` | required | shown in status and export |
| `rounds` | 1 | rounds to play; phases must add up to it |
| `post_length` | 400 | words per post; a phase may override with `length` |
| `jobs` | per harness | seats in parallel per round; the default runs each harness's seats independently, up to `per_harness` each, because only seats sharing an account share a quota wall |
| `harness` | `claude` | seat default: `claude`, `codex` or `agy` |
| `model` | `opus` | seat default; resolved against the harness's catalog, so `opus-5` becomes `claude-opus-5`, then verified against the served model |
| `effort` | `high` | seat default; harness-specific values |
| `tools` | `read` | seat default: `none`, `read`, `write`, `research` |
| `isolation` | `strongest` | seat default: `strongest`, `enforced`, `private-home`, `none` |
| `visibility` | `board` | seat default: `board` or `blind`; matters from round 2 |
| `workspace` | `none` (`repo-ro` for a panel) | seat default: `none`, `repo-ro`, `worktree` (needs `tools = "write"`) |
| `compaction` | `forbid` | `forbid` pins the whole context window; `allow` lets the harness compact |
| `persona` | none | seat default persona id |
| `grants` | `[]` | doors opened for every seat: `web`, `mcp`, `settings`, `instructions`, `hooks` |
| `per_harness` | 2 | seats of one harness running at once; the cap that protects a shared quota |
| `claude_args`, `codex_args`, `agy_args` | `[]` | raw arguments appended to that harness's command line |
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
| `phases` | one phase | list of `{ name, rounds, seats?, deliverable?, instruction?, length? }` |
| `stop_novelty`, `stop_closing` | 55.0, 0.75 | convergence thresholds for an unphased room |
| `synthesis.by` | `operator` | `operator`, or a seat id: that seat acts alone in one extra final round, sees the board, and writes `synthesis.md`; it may not act in any declared phase |

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
plan.json  plan-digest.json  budget.json  run.log  run.lock
chair/rNNN.md                          operator notes, read before round NNN
work/<seat>/{START.md, materials/, outbox/, board/, repo/}
homes/<seat>/{claude,codex}/           private harness homes
board/posts/<seat>/rNNN.md             promoted posts
board/made/<seat>/rNNN/<file>          deliverables and changes.patch
board/rounds/rNNN/{digest.md,digest.json,convergence.json}
sealed/rNNN/{A,B,...}/                 a blind round's drafts under letters
sealed/rNNN/{identity-key.json,seal.json,judgment.md,unsealed.json}
records/<seat>/state.json
records/<seat>/rNNN/{prompt.md,launch.json,events.jsonl,stderr.log,receipt.json,answer.md}
records/<seat>/rNNN/attempts/NN/       a quota-stopped attempt, archived whole
```

`launch.json` records the harness argv, the isolation wrapper, the tier
attestation and the names (never the values) of the environment
variables the seat received. `receipt.json` records what actually ran:
session id, served model against the requested one, usage, tool calls,
compaction markers, quota classification and red flags.
