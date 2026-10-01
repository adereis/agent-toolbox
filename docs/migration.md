# Migration to Agent Toolbox

The repository is now [adereis/agent-toolbox](https://github.com/adereis/agent-toolbox).
Existing clones can update their remote without changing checkout paths:

```bash
git remote set-url origin git@github.com:adereis/agent-toolbox.git
```

Renaming the local checkout directory is optional. If you move it, update
installed symlinks and aliases to the new location. GitHub redirects the old
repository URL; keep the old repository name unused to retain that redirect.

The `claude-code-baseline` tag preserves the previous collection. Harness
components moved from the root into `harnesses/claude-code/`; update any
checkout-relative paths, aliases, or symlinks you maintain.

## Hand-made PATH symlinks

Earlier instructions told you to symlink a session utility into `~/bin`
yourself. The `commands` component now owns that job and installs into
`~/.local/bin` without the file extension. Remove the hand-made links so one
tool cannot answer to two names:

```bash
rm -f ~/bin/claude-code-session-resume.py ~/bin/codex-code-session-resume.py
rm -f ~/bin/codex-api-profile.sh ~/bin/codex-tmux.py
python3 tools/install.py --harness codex --scope user \
  --component commands --apply
```

Check the removal against your own `~/bin` before running it; the installer
never deletes files it did not create. If both directories are on your
`PATH`, confirm with `type -a <command>` that no stale entry remains. The
`whats-new` utilities never belonged on `PATH`; run them from their
installed `scripts` directory instead. `claude-memory-sync` does belong
there, and the `commands` component installs it.

## Retired hooks

Remove these command registrations from your Claude Code settings before
removing the corresponding installed files:

- `tmp-write-guard.sh`
- `tmp-home-allow.sh`
- `test-edit-guard.sh`
- `continue-plan.sh`

Check both user and project scopes, including `settings.local.json`. Preserve
other commands in shared matcher groups. Back up settings and installed
files before editing; start a fresh Claude session after changing hooks.
Remove the same obsolete files and registrations from any provisioning or
dotfile source so a future setup run cannot restore them. Update deployed-file
tracking records when your provisioning system maintains them.

Directory denial and edit-context examples now live under
[`examples/claude-code/hooks/`](../examples/claude-code/hooks/README.md). They
are reference implementations and must not be automatically deployed.
The obsolete plan continuation hook has no replacement.

## Retired agents and skills

Remove installed `agents/commit-reviewer.md`, `agents/web-ui-verifier.md`,
`skills/commit-review/`, and `skills/web-ui-verify/` from the Claude
configuration scopes where you previously installed them. Keep a backup of
any local customizations; do not import these obsolete wrappers back into
the collection.

The old agents pinned a model and tool list, coupled browser checks to a
particular machine setup, and treated patterns such as tests preceding an
implementation or consecutive edits to one file as history defects. Those
rules do not reliably indicate a problem. The useful review and browser
verification guidance is retained as short, opt-in
[prompts](../prompts/README.md), without automatic delegation or installation
of browser dependencies.

## Retired session-resume skill

`session-resume` is still supported, but only as a standalone script. The
skill wrapper that `/sync` once deployed to `skills/session-resume/` was
removed in June 2026 because it carried its own copy of the script and drifted
from it. Remove the installed directory from the Claude configuration scopes
where you previously installed it, honoring `CLAUDE_CONFIG_DIR` when set:

```bash
rm -rf ~/.claude/skills/session-resume
```

The installer will not report this and cannot clean it up. The catalog no
longer claims that path, so `link_status` never examines it: whether it holds
copied files or dangling symlinks, the dry run says nothing while the stale
skill stays registered. A clean `/sync` is not evidence the directory is gone.

Recognize the obsolete copy by a private `session-resume.py` beside its
`SKILL.md`, and by the `--skill` flag that copy accepts; the supported script
renamed that flag to `--list`. The removed files are preserved in git history
at `83fbb1c` if you want to compare behavior before deleting.

Keep `claude-code-session-resume.py`, the `scripts` component that installs
it, and any `~/bin` symlink or alias pointing at it. Those are the supported
entry points. The script execs `claude --resume` in place, so it must be the
terminal's foreground process and cannot run from inside a session; that is
why no skill wraps it. Codex never received this skill, because its session
browser arrived after the wrapper was removed.

## Statusline illustration

The terminal screenshot has been removed. The statusline remains supported;
its README uses a generic ASCII example with fictitious values.
