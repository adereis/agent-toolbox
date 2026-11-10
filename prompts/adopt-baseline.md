Adopt the shared global baseline into a harness's global instruction file,
or reconcile it after the module changed.

`instructions/global-baseline.md` is the authoritative source for shared
agent policy. A global instruction file also carries harness-specific and
personal rules, so merging the two requires judgment and is not part of the
installer. Perform that merge here and report what moved.

## Read both sides first

Read the installed baseline module and the harness's global instruction file
in full before editing.

For Claude Code the global instruction file is `$CLAUDE_CONFIG_DIR/CLAUDE.md`,
or `~/.claude/CLAUDE.md` when that variable is unset, and the module installs
as `instructions/global-baseline.md` beneath the same root.

For Codex the global instruction file is `$CODEX_HOME/AGENTS.md`, or
`~/.codex/AGENTS.md` when that variable is unset, and the module installs as
`~/.agents/instructions/global-baseline.md` at user scope or
`<project>/.agents/instructions/global-baseline.md` for one project.

For Antigravity the global instruction file is `~/.gemini/GEMINI.md`, and the
module installs as `~/.gemini/config/instructions/global-baseline.md` at user
scope. Antigravity also loads `~/.gemini/AGENTS.md` and the `GEMINI.md` and
`AGENTS.md` beneath `~/.gemini/config/` as global rules. Read whichever of
them exist, because shared text in more than one of them is a duplicate.

Stop and report if the module is not installed; do not reconstruct it from
memory. Install it from a checkout of this repository with:

```bash
python3 tools/install.py --harness claude-code --scope user \
  --component instructions --apply
```

Pass `--harness codex` or `--harness agy` for those harnesses.

## Adopt

Make the baseline effective through the mechanism the harness supports, then
remove the now-duplicated shared sections from the global instruction file.
Leave every harness-specific and personal section in place, including rules
that only make sense for that harness. Preserve the file's existing order and
voice; this is the user's configuration, not a generated artifact.

Claude Code loads `@path` imports with the file that declares them, so adopt
the module with a single relative import line in `CLAUDE.md`:

```markdown
@instructions/global-baseline.md
```

The path resolves against the importing file's directory, which keeps the
import correct under a custom `CLAUDE_CONFIG_DIR`. The baseline then applies
unconditionally, so its sections must not also appear verbatim in `CLAUDE.md`.
An unresolved import is silent; verify the module is installed before relying
on it, and report an unsatisfied import instead of inlining the text.

Codex discovers `AGENTS.md` files up the directory tree and has no import
syntax for them; this was checked against Codex CLI 0.154.0. Shared policy
therefore only reaches the model when the text is present in the file itself.
Inline the module's sections, shifting their heading depth to sit beneath the
file's existing top-level heading, and keep them in the module's order. Use no
marker comments.

Antigravity expands include lines, an `@` before a Markdown link, in its rule
files, so adopt the module with a single include line in `~/.gemini/GEMINI.md`:

```markdown
@[global baseline](config/instructions/global-baseline.md)
```

Antigravity resolves a relative include against `~/.gemini/`, not against the
including file's directory. From `~/.gemini/config/GEMINI.md` the path
`instructions/global-baseline.md` stays unexpanded, while
`config/instructions/global-baseline.md` loads. Keeping the include in
`~/.gemini/GEMINI.md`, whose directory is `~/.gemini/`, makes the path right
under either rule. A file under `~/.gemini/config/rules/` is no substitute:
without `trigger: always_on` frontmatter it loads only when the model decides
to, and the shared module carries no frontmatter. This was checked against
Antigravity CLI 1.4.12.

An unexpanded include is silent: the model sees the literal reference line and
none of the module. After adopting, verify it in a fresh print-mode turn that
uses no tools, for example by asking the model to quote the bold lead of the
baseline's AI-credit bullet. A reply that quotes it confirms the include; one
that names an unresolved reference, or answers that there is no such bullet,
means it failed.

Antigravity gives the model only a display name for itself, such as
"Gemini 4 Argon (Medium)", never an API id. The baseline's attribution rule
therefore needs a harness section in `GEMINI.md` that says where the id is:

```markdown
## Git (Antigravity)
* Credit yourself as `Assisted-by: Antigravity (<model-id>)`. Antigravity names your model only by its display name. Find that name in `agy models`, which pairs each display name with its slug, and credit the slug without its trailing effort (`-low`, `-medium`, `-high`). If the lookup fails, omit the model-specific trailer and say so. Antigravity documents no session-link trailer, so add none.
```

## Reconcile

On later runs the module is the reference for shared policy. Compare it
against the global instruction file section by section:

- A shared section that drifted returns to the module's wording.
- A local section the module does not cover stays untouched.
- A local rule that contradicts the baseline is reported to the user with
  both wordings. Do not silently resolve it in either direction: the
  contradiction is either a deliberate harness exception or a stale copy,
  and only the user knows which.

Under Codex, match sections by heading and compare their bodies against the
module, because there are no markers to find them by.

Content that a harness cannot load unconditionally must not be described as
enforced. The Claude Code import is a link and cannot fall out of date. The
Antigravity include is a link too, but it fails silently, so report whether
the no-tools check confirmed it. The Codex copy is maintained rather than
linked, so it can drift; say so when reporting, and never describe a copy as
equivalent to a link.

## Report

List the sections added, removed, rewritten, and left alone, and name any
contradiction awaiting a decision. Never copy content from a global
instruction file back into the repository.
