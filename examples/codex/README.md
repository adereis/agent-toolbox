# Personal Codex configuration

[config.toml](config.toml) records the maintainer's selected personal
preferences for bootstrapping a new Codex setup. These values were checked
against the live configuration on September 15, 2026. Codex CLI 0.154.0 on
Linux accepts the template. It is a reviewed snapshot. It does not sync
automatically with the live configuration.

## Context and editing preferences

The context settings express a preference for long sessions with delayed
compaction. For example, the requested context budget and explicit
compaction threshold are both 1,050,000 tokens.

| Setting | Saved choice | Purpose |
|---------|--------------|---------|
| `model_context_window` | `1050000` | Request a large context budget |
| `model_auto_compact_token_limit` | `1050000` | Keep the explicit compaction threshold at that budget |
| `model_auto_compact_token_limit_scope` | `"body_after_prefix"` | Count growth after the carried compaction-window prefix |
| `tui.vim_mode_default` | `true` | Start each session in Vim normal mode |

The requested window does not guarantee that every model can use 1,050,000
tokens. Model limits and Codex's reserved headroom still constrain the
effective window. The scope setting controls what counts toward the
configured compaction threshold. Codex can still reach a separate context
limit. The displayed context percentage alone does not establish how close
the session is to that limit.

Review these personal choices against the target model and account.
Recheck context and compaction behavior after CLI or model changes.
The configuration-load check does not exercise a full context window.
See the [official configuration reference](https://developers.openai.com/codex/config-reference/)
for the supported keys and scope definitions.

## Bootstrap a new setup

Ask the agent configuring the machine to use this template:

> Merge the preferences in `examples/codex/config.toml` into my Codex user
> configuration. Preserve existing settings. Read the accompanying README
> for the context limits and separate compaction-hook dependency.

The destination is `$CODEX_HOME/config.toml` when `CODEX_HOME` is set.
Otherwise it is `~/.codex/config.toml`. On a fresh setup, the template can
seed that file. On an existing setup, merge the three context keys at the
top level and `vim_mode_default` into the existing `[tui]` table. Preserve
unrelated preferences, authentication settings, MCP integrations, and trust
state. Do not replace an existing configuration wholesale or duplicate a
TOML table.

Choose the model and authentication separately. The
[subscription and API profiles](../../harnesses/codex/README.md#authentication-profiles)
inherit these user preferences. The
[tmux wrapper](../../harnesses/codex/README.md#tmux-status-display) also inherits
them. Restart Codex after merging the settings. New sessions start in Vim
normal mode. Press `i` to type. `/vim` toggles editing mode for the current
session.

This reference stays outside the installer. Installing toolbox components
does not apply these personal preferences. Keep future changes to the
selected keys and their rationale here. Credentials, session contents,
machine paths, and generated runtime state do not belong in this template.

## Blocking automatic compaction

The context thresholds alone do not disable automatic compaction. The
maintainer's current setup also uses a separate `PreCompact` hook with the
matcher `^auto$`. Its handler returns `continue: false` to stop the turn
before Codex compacts the conversation. Manual `/compact` remains available
because its trigger does not match that hook.

That hook is maintained in `modules/codex/` in the separate machine-setup
repository. Reproduce it separately if the new setup must preserve the
same rule against automatic compaction. This TOML template neither installs
nor enables the hook. Register and trust the handler through Codex's hook
configuration and `/hooks` when setting up a new machine. See the
[official hook documentation](https://developers.openai.com/codex/hooks/)
for the `PreCompact` event and its stop behavior.
