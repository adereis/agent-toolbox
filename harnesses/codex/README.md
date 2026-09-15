# Codex integration

Use the [scoped installer](../../docs/installation.md) for authentication
profiles, utilities, and the shared `teach` and `whats-new` skills. The `teach`
adapter preserves explicit invocation through `agents/openai.yaml`.
The release digest skill supports normal automatic discovery.

## Release digest

`codex-whats-new.py` tags release notes with the settings they touch on this
machine. The `whats-new` skill turns that evidence into a digest of changes
to act on, fixes relevant to your setup, and capabilities worth knowing.
For example, a configured MCP server makes OAuth fixes worth inspecting.
A tag indicates a possible connection; it does not prove that a bug affected
your session.

**Requirements:** Linux and Python 3.11+. Online fetching also needs GitHub CLI
authenticated with `gh auth login --hostname github.com`. On Fedora, install
it with `sudo dnf install gh`; on Debian/Ubuntu, use `sudo apt install gh`.
Configuration paths and profile
behavior were checked against Codex CLI 0.154.0. The CLI itself is optional;
without it the installed version is reported as unknown. macOS execution
is not verified, so the utility exits with a command to open the release
archive there.

```bash
python3 tools/install.py --harness codex --scope user \
  --component skills --component scripts --apply

# Changes since the last digest, or five releases on the first run
~/.agents/scripts/codex-whats-new.py

# Inspect the selected profile and project
~/.agents/scripts/codex-whats-new.py --profile api --project ~/projects/demo-app

# Select a window or trace a topic through stable CLI history
~/.agents/scripts/codex-whats-new.py --days 14 --relevant-only
~/.agents/scripts/codex-whats-new.py --since 0.153.0 --through 0.154.0
~/.agents/scripts/codex-whats-new.py --topic 'multi.agent' --topic subagent
```

Invoke `$whats-new` in Codex for the interpreted digest. Keep the checkout
intact when using installed script symlinks. Project-scope installations
put both components under `<project>/.agents/`.

| Option | Behavior |
|---|---|
| `--releases N` | Newest N stable CLI releases |
| `--days N`, `--months N` | Publication-date window; a month means 30 days |
| `--since VERSION`, `--through VERSION` | Exclusive baseline and inclusive ceiling |
| `--topic PATTERN` | Case-insensitive regex; repeat for alternative names |
| `--limit N` | Recent topic matches to show; default 40, zero shows all |
| `--relevant-only` | Show tagged entries while reporting unmatched counts |
| `--no-filter` | Include explicitly labelled entries for another platform |
| `--max-releases N` | Refuse wider windows; default 25; `--relevant-only` lifts this limit |
| `--codex-dir PATH`, `--profile NAME` | Inspect a particular Codex home and separate profile file |
| `--refresh`, `--offline` | Refresh the archive or forbid network access |
| `--changelog FILE` | Read a local JSON array in GitHub releases API format |
| `--json` | Structured output in window and topic modes |
| `--state FILE` | Explicit baseline file; its recorded scope must match |
| `--commit` | Record a digest baseline after successful output; no Git operation |

### Sources and configuration evidence

The source is the public [Codex release archive](https://github.com/openai/codex/releases).
The first fetch follows all cursor pages through `gh api graphql`. The REST
API stops at 1,000 release records, which previews can fill before the oldest
stable versions appear. Cursor pagination avoids that history gap.
Only non-draft, non-prerelease
`rust-vX.Y.Z` tags qualify; SDK and other product releases are excluded.
Release bodies retain prose, feature summaries, and the detailed changelog.
Wrapped entries stay together. All entries in a New Features section remain
tagged even when they introduce something absent from your configuration.
Platform filtering requires an explicit label such as `Windows:`.
Mentioning a platform or terminal somewhere in an entry never removes it.
Withheld and unmatched counts are always reported, including zero.

The archive is cached for 24 hours under
`$XDG_CACHE_HOME/agent-toolbox/codex-releases.json`, defaulting to
`~/.cache/agent-toolbox/codex-releases.json`. An installed version absent
from the cache also triggers a refresh. A failed refresh can use a previous
complete cache with a visible notice. A partial fetch never replaces it.
Offline and local-file reports state their snapshot limitation. The utility
uses GitHub CLI's existing authentication without reading or copying its
credentials. No Codex credentials, model calls, or harness cache modifications
are involved. Cached and local-file reports do not require GitHub CLI.

The environment block inventories system configuration, user configuration,
the explicitly selected `<name>.config.toml`, and project layers from the
Git root to the chosen directory. Project layers require recorded trust in
the system or user configuration. The closest recorded trust decision wins.
Settings merge in that order. Hook event names accumulate across layers.
Separate profiles require Codex 0.134+; legacy embedded profile tables are
reported as ignored. The utility never reads `auth.json` or session contents.

This is a file-based view. It does not resolve CLI overrides, cloud defaults,
enforced requirements, plugin-bundled content, or hook trust decisions.
Unspecified feature defaults remain unknown. Installed skills and configured
hook events do not prove runtime activation. Environment variables contribute
names only. Hook commands, MCP arguments, provider endpoints, and arbitrary
configuration values are omitted. Invalid configuration fails with a path
and a repair instruction instead of being treated as absent.

Official configuration references: [layer precedence](https://developers.openai.com/codex/config-basic),
[file profiles](https://developers.openai.com/codex/config-advanced#profiles),
and [hook sources](https://developers.openai.com/codex/hooks).

### Remembering a completed digest

After reading the report, repeat its window and configuration arguments with
`--through NEWEST_PRESENTED_VERSION --commit`. For example:

```bash
~/.agents/scripts/codex-whats-new.py --profile api \
  --since 0.153.0 --through 0.154.0 --commit
```

The ceiling prevents a release published between the read and the commit
from being marked as already discussed. Topic searches reject `--commit`.
Re-reading an older window cannot move the baseline backward.

Each Codex home, project, and profile has a separate baseline under
`$XDG_STATE_HOME/agent-toolbox/codex-whats-new/`, defaulting to
`~/.local/state/agent-toolbox/codex-whats-new/`. The report prints its exact
path. Baselines use private atomic files with serialized writes and retain
five previous records. Ordinary reports do not create baseline files.
An empty window means no matching releases in that snapshot; it does not
claim that the installed CLI is current.

## Authentication profiles

Keep subscription access as your normal login and select API billing when
needed. The profiles require Codex CLI 0.134.0 or newer and use separate
`<name>.config.toml` files; their configuration was checked with 0.154.0.
They inherit your model, reasoning, MCP, and other settings from the base
configuration. Choose a model available to the selected account.

```bash
# Preview both profiles; add --apply to install
python3 tools/install.py --harness codex --scope user --component profiles
```

The installer links the files from `profiles/` into `$CODEX_HOME` (default
`~/.codex`). It preserves existing conflicting files and does not edit your
base config or login. Provider configuration belongs at user scope, so the
installer rejects `--scope project` for this component.

| Profile | Command | Authentication |
|---------|---------|----------------|
| `subscription` | `codex --profile subscription` | Built-in OpenAI provider; requires a saved ChatGPT login |
| `api` | `codex --profile api` | OpenAI Responses API using `CODEX_OPENAI_API_KEY` |

### Establish the subscription default

Run `codex login` and complete the ChatGPT browser sign-in, then verify it
with `codex login status`. Keep the base `model_provider` set to `"openai"`
or unset (its default). Plain `codex` then uses that saved login; installing
the profiles does not change the default provider. Avoid supplying built-in
authentication overrides such as `CODEX_API_KEY` when using the subscription.

Use `codex --profile subscription` when you want explicit enforcement. Its
`forced_login_method = "chatgpt"` prevents use of a saved API-key login.
Codex clears a mismatched saved login and exits, so establish the ChatGPT
login first. The restriction belongs to this profile, not a global switch
that you toggle between backends.

### Use the API key for one run

Supply `CODEX_OPENAI_API_KEY` through your secret manager or enter it in a
terminal. This Bash example hides the input and limits the variable to the
subshell and its child process:

```bash
(
  read -rsp 'OpenAI API key: ' CODEX_OPENAI_API_KEY || exit
  printf '\n'
  export CODEX_OPENAI_API_KEY
  codex --profile api
)
```

The API provider requires this variable and does not fall back to the saved
ChatGPT login when it is missing. The distinct variable name keeps the key
specific to this provider. `requires_openai_auth = false` makes Codex use
`env_key`; setting it to `true` would ignore that variable and select the
shared OpenAI login instead. Do not put the key in TOML, shell arguments,
or this repository, and do not run `codex login --with-api-key` to switch to
this profile: that command changes the shared saved login.

API requests are billed separately from subscription usage. Some features
that depend on ChatGPT workspace access differ in API mode. There is no
automatic fallback to paid API usage when subscription limits are reached.

### Store the key in the keyring

`codex-api-profile.sh` keeps the key in the login keyring instead of your
shell history or a plaintext file, and exports it for the Codex process
alone. Install it with the `scripts` component and store the key once:

```bash
python3 tools/install.py --harness codex --scope user \
  --component scripts --apply
~/.agents/scripts/codex-api-profile.sh --store   # input is not echoed
```

Then run Codex through the wrapper. It appends `--profile api` unless the
arguments already select a profile:

```bash
codex-api-profile.sh                 # interactive session
codex-api-profile.sh exec "say ok"   # non-interactive
codex-api-profile.sh resume --last   # resume under the API profile
codex-api-profile.sh --status        # stored or missing; never prints the key
codex-api-profile.sh --clear         # remove the stored key
```

The wrapper reads the keyring through `secret-tool` (libsecret) and does not
implement the macOS keychain. On macOS it exits with the equivalent
`security add-generic-password` and `security find-generic-password`
commands instead of failing quietly; see
[portability](../../AGENTS.md#portability). Storing the key in the keyring
does not change the saved ChatGPT login, and the wrapper never runs
`codex login`.

### Resume and shared state

Select either profile for an existing session:

```bash
codex resume --last --profile subscription
# Requires CODEX_OPENAI_API_KEY in this process's environment
codex resume --last --profile api
# Or let the wrapper supply the key from the keyring
codex-api-profile.sh resume --last
python3 harnesses/codex/scripts/codex-code-session-resume.py --profile api
```

Profiles sharing `CODEX_HOME` share session history and saved login state;
they are configuration layers, not isolated accounts. The API profile reads
its key from the environment without replacing the subscription login.
Use a separate `CODEX_HOME` if you need separate histories and login stores,
and install the profiles into that home as well. Existing sessions retain
their launch configuration; select a profile for a new or resumed process.

Official OpenAI documentation: [configuration profiles](https://learn.chatgpt.com/docs/config-file/config-advanced#profiles),
[authentication and login restrictions](https://learn.chatgpt.com/docs/auth),
and [custom provider authentication](https://learn.chatgpt.com/docs/auth#alternative-model-providers).
Live checks requiring your accounts are described in
[interactive validation](../../tests/INTERACTIVE.md#it-07-codex-authentication-profiles).

## Tmux status display

`codex-tmux.py` opens Codex with an explicit billing backend and a two-row
status area beneath it. It uses the same column order and color thresholds
as the Claude Code status line. The API path calls the existing keyring
helper, so backend selection and the display have one launch command.

**Requirements:** Linux with readable `/proc`, Python 3.11+, tmux 3.2+, Git,
and Codex CLI. The transcript format was checked against Codex 0.154.0.
The automated integration tests exercise real tmux with synthetic Codex
processes. Account-backed checks are listed separately in
[interactive validation](../../tests/INTERACTIVE.md#it-08-codex-tmux-display).
On Fedora, install terminal dependencies with `sudo dnf install tmux git`.
On Debian/Ubuntu, use `sudo apt install tmux git`.

Install the scripts and authentication profiles:

```bash
python3 tools/install.py --harness codex --scope user \
  --component scripts --component profiles --apply

# Store the API key once, using the existing libsecret helper
~/.agents/scripts/codex-tmux.py --store-key

# Subscription is the default
~/.agents/scripts/codex-tmux.py
~/.agents/scripts/codex-tmux.py --backend api

# Native Codex arguments follow --
~/.agents/scripts/codex-tmux.py --backend api -- resume --last
~/.agents/scripts/codex-tmux.py --backend subscription -- -m gpt-6-astra
~/.agents/scripts/codex-tmux.py --backend api -- -C ~/projects/demo-app
```

Establish the saved ChatGPT login as described under
[authentication profiles](#authentication-profiles) before using subscription
mode. The launcher checks the selected profile's authentication settings.
It refuses competing native `--profile`, provider, and remote-server
overrides. Use `--backend` to choose billing. Model, reasoning, permissions,
resume, fork, and other interactive arguments remain native Codex options.
For a known initial pricing rate, the launcher explicitly sets the service
tier from the selected profile or base user config. It selects Standard
when neither specifies one. This takes precedence over project or model
catalog defaults. Select a different tier with a native override such as
`-- -c service_tier=priority` (Fast) or `-- -c service_tier=flex`.
Use `codex` or `codex-api-profile.sh` directly for non-interactive commands
such as `exec`, login management, and maintenance.

The keyring controls are `--store-key`, `--key-status`, and `--clear-key`.
API mode requires a stored key. Inherited OpenAI API-key variables are
removed before starting tmux. The helper retrieves the key inside the pane
and exports it only to Codex. Runtime metadata contains no credentials.

Illustrative output with fictitious usage:

```text
workspace            branch   model                 effort   session   cost~   ↻14:30   week   profile   memory
~/projects/demo-app  main*+?  gpt-6-astra [828k]     high     23%       $1.23   42%      40%    pro       312.5 MB
```

| Column | Color | Meaning |
|--------|-------|---------|
| `workspace` | Bold blue | Current turn's working directory, with `~` for your home |
| `branch` | Yellow | Git branch or detached commit; `*` unstaged, `+` staged, `?` untracked |
| `model` | Green | Model recorded for the current turn; windows under one million tokens appear in brackets |
| `effort` | Magenta | Recorded reasoning effort; dim at `low`, bold at `max` |
| `session` | Green → yellow → red | Last request's total tokens divided by its reported context window |
| `cost~` | Cyan | Estimated main-thread token cost since this launch, in USD |
| `↻HH:MM`, `week` | Green → yellow → red | Reported subscription quota usage; the first header shows its local reset time |
| `profile` | Cyan; API dim | Selected backend, refined by current runtime settings and a reported subscription plan |
| `memory` | Cyan | RSS of the process holding this main thread's transcript |
| `status` | Dim while waiting; red for errors | Waiting state or a visible explanation when telemetry is unavailable |

Headers are dim. The colors match the Claude Code status line.
They come from the terminal's standard palette.
Both rows have a two-character margin on each side. Those margins count
toward the available width, so the footer still fits narrow terminals.

Context and quota values are green below 50%, yellow from 50%, and red
from 80%. Quotas older than 15 minutes, or past their reset time, go dim
and show their age. A narrow terminal drops less essential columns first;
the backend remains visible. Extra per-model quota buckets and Claude's
vim mode are not available from this Codex transcript format.

The context percentage uses the reported token count directly. Codex's own
footer subtracts a fixed baseline, so the percentages can differ. Model,
effort, and quota changes appear after Codex persists the corresponding
event. A new idle session can show `waiting for local transcript` until its
first turn. The display reads local telemetry and makes no usage API calls.

### Cost estimates

The estimate prices each completed response with the model and service tier
active for that response. It includes cached-input discounts, cache-write
charges, long-context pricing above 272,000 input tokens, and Standard,
Fast/Priority, or Flex processing. Reasoning output is already included in
output tokens and is not charged twice. Resuming starts a fresh estimate.

Bundled rates cover GPT-6 Astra and GPT-5.6 Sol, Terra, and Luna. They were
checked against [OpenAI pricing](https://developers.openai.com/api/docs/pricing/)
and the model pages on September 15, 2026. They are a versioned snapshot;
GPT-5.6 Sol currently has promotional pricing. Unknown models, missing
per-response usage, and unknown service tiers produce `n/a` with a reason.
They never produce a guessed price or an understated partial total.

This is the main thread's token estimate. It excludes delegated agents,
tool fees, regional uplifts, credits, and account-specific discounts.
For a subscription it is an API-equivalent estimate, not an additional bill.
For API billing, reconcile charges with your account's usage reports.

### Scrolling and text selection

Scroll with the mouse wheel or trackpad to read earlier messages and tool
output. Scrolling over the input box also scrolls the conversation. It does
not cycle through prompt history. Scroll down to the bottom or press `q`
or `Escape` to return to the live prompt before typing. Codex keeps running
while you read earlier output.

The launcher enables tmux mouse handling and gives wheel events to tmux
scrollback, even when the application requests mouse input. It defaults
Codex to inline output with `tui.alternate_screen="never"`, which overrides
the saved screen preference for this launch. Keep that setting when passing
native configuration overrides so earlier output remains in pane history.
The private server retains up to 100,000 history lines per pane. Older lines
beyond that limit fall out of tmux scrollback.

For keyboard scrolling, press `Ctrl-b [` and use Page Up or Page Down.
Press `q` or `Escape` to return. Mouse dragging uses tmux selection; hold
Shift while dragging to use your terminal's native text selection instead
(the override modifier depends on the terminal).

These settings apply to new launches. Exit and resume through the updated
launcher to apply them to an existing conversation; `--attach` reconnects
to the existing server with its original settings.

### Sessions, detach, and compatibility

Every launch owns a private tmux server under a random directory in `~/tmp`.
It does not load your tmux configuration. The standard prefix is `Ctrl-b`;
press `Ctrl-b d` to detach. The launcher prints a command such as:

```bash
codex-tmux.py --attach ~/tmp/codex-tmux-EXAMPLE
```

That command reconnects to the same process and its existing billing choice.
When nested inside another tmux, send the prefix through the outer server
first (with the standard bindings, `Ctrl-b Ctrl-b d` detaches the inner one).
The private server does not modify the outer server's options or environment.
After Ctrl+D or another normal exit, the final pane output is replayed in
your calling terminal. Token totals and the resume command remain visible
after tmux closes. Wrapped lines are joined so commands stay copyable.
The capture includes up to 100 rows of recent scrollback for short terminals.

The launcher returns Codex's exit code and removes the runtime directory
when attached. If Codex exits while detached, `--attach` replays its output
and collects the exit status before cleanup. The directory also holds
`status.json` and `errors.log` for troubleshooting. Successful exits save
their text in private `output.txt`; failures use `failure.txt` and are
replayed to standard error.

The display follows transcript file descriptors held by the launched process
tree. Two sessions in the same project and `CODEX_HOME` therefore keep their
own displays. It excludes subagent transcripts and never chooses the newest
file. Multiple open main threads, inaccessible telemetry, or replaced files
produce a visible error instead of an arbitrary session choice. The display
requires one writer per saved conversation. If another accessible process
also has that transcript open for writing, telemetry stops with a restart
instruction. Start distinct conversations when running parallel windows;
the transcript has no process identifier for separating concurrent writers.
The display always describes the main thread, including when you inspect
a subagent in Codex. Local legacy JSONL transcripts are required; remote servers and
paginated history storage are outside this first version's support.

The wrapper's configuration override makes Codex 0.154.0 use an embedded
app server. Its built-in status line is disabled for this invocation.
Keep the checkout intact when installing script symlinks; the entry point
imports the adjacent telemetry module and published price table.

macOS is not implemented because the process ownership check uses Linux
`/proc`. The launcher exits with a direct `codex --profile subscription`
fallback. API keychain instructions remain available from the keyring helper.

## codex-code-session-resume.py

Browse recent local Codex sessions with their titles, a prompt arc, recognized
commit results, and optional edited-file details. Select a session to launch
the native `codex resume <id>` command. Run the interactive utility from a
terminal; use `--list` or `--json` inside an existing agent session.

```bash
# Current project, newest session at the bottom
python3 harnesses/codex/scripts/codex-code-session-resume.py

# Browse across projects, including edited files
python3 harnesses/codex/scripts/codex-code-session-resume.py --all -n 20 -v

# Read-only listing suitable for pipes and automation
python3 harnesses/codex/scripts/codex-code-session-resume.py --all --list | less
python3 harnesses/codex/scripts/codex-code-session-resume.py --all --json
```

Python 3.10 or newer is sufficient for browsing; Codex CLI is needed only
when resuming. Keep the checkout intact, since the entry point imports the
shared `tools/_session_resume.py` module. Symlinking the entry point onto
your `PATH` works; copying only that file does not.

| Option | Behavior |
|--------|----------|
| `--codex-dir PATH` | Select the store to read and pass to the resumed process |
| `--project PATH` / `-p PATH` | Match the recorded working directory exactly |
| `--all` / `-a` | Include other project directories in the same store |
| `--include-subagents` | Also show delegated sessions, hidden by default |
| `--profile NAME` | Forward a configuration profile to native `codex resume` |
| `--resume-cwd PATH` | Explicit replacement working directory when resuming |
| `--color auto\|always\|never` | Control terminal styling; `NO_COLOR` disables automatic styling |

By default, the store is `$CODEX_HOME`, or `~/.codex` when unset. A selected
store stays selected during resume. Codex configuration profiles sharing
the same store share history; `--profile` selects launch configuration and
does not claim to partition that history. Use separate stores when you need
separate history. No session files, indexes, or databases are modified.

The parser reads active `sessions/**/*.jsonl` rollouts and the optional
`session_index.jsonl` title index. Archived sessions are excluded. Discovery
uses metadata and file modification times; only the selected recent sessions
are fully parsed. Duplicate user event/response records and known injected
context blocks are omitted from the prompt arc. Incomplete records produce
warnings, and uninspectable dynamic tool calls are reported.

Commit extraction is best effort: it correlates recognized shell calls with
Git's success output, including static JSON-string commands in wrapped `exec`
calls. It never evaluates transcript code. Quiet commits without success
output and dynamically constructed commands may be absent. Edited-file
details cover recognized successful `apply_patch` calls, not arbitrary shell
file writes. These are observed historical results, not current Git state.

The CLI arguments and local rollout shapes were checked against Codex CLI
0.154.0. Rollout storage is an internal format that may evolve. Native command
documentation: [Codex CLI reference](https://developers.openai.com/codex/cli/reference).
