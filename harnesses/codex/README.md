# Codex integration

Use the [scoped installer](../../docs/installation.md) for authentication
profiles, utilities, and the shared `teach` skill. The Codex skill adapter
preserves explicit invocation through `agents/openai.yaml`; it does not
change other skill policies.

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
