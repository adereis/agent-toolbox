# Global baseline

Shared working agreements for coding agents. Repository conventions and
direct user instructions take precedence over every default below.

## Environment
* Use `rm -f` to avoid confirmation prompts

## Git
* Don't push unless user explicitly requests
* Merge follow-up fixes into previous commit (soft reset + new commit)
* **Check HEAD before any amend or soft reset.** Run `git log -1 --oneline`
  and confirm the subject is the commit you mean to fold into. An amend
  rewrites whatever HEAD points at, and HEAD moves the moment another commit
  lands — including one you made yourself minutes earlier. A mis-aimed amend
  is doubly destructive: it absorbs unrelated changes *and* overwrites the
  target commit's message, which is not recoverable from the diff.
* **Never fold into a commit already pushed to the default branch.**
  Before an amend or soft reset, run `git branch -r --contains HEAD`; if
  it lists the remote's default branch (`origin/HEAD`, usually
  `origin/main`), commit the follow-up as a new commit instead. The HEAD
  check above cannot catch this, because a push leaves HEAD where it
  was, and the user may push by hand from outside the session. Folding a
  pushed commit forks the local branch from its remote, and only a force
  push repairs it, which the default branch never gets.
* **A work branch is rewritten freely, pushed or not.** Rebase, fold and
  squash its commits as the work goes; its next push, still only on
  request, is `git push --force-with-lease`, which refuses to overwrite
  commits it has not fetched. Treat a branch other people also push to
  like the default branch unless the user says otherwise.
* **Never reuse a recent commit's subject line.** If the message you are
  about to write already appears in `git log`, you are probably amending or
  re-committing the wrong thing. Two adjacent commits sharing a subject is
  the signature of that mistake, not a deliberate pair.
* **Commit hygiene**: Only stage files related to the commit message.
  Separate commits for unrelated changes. Ask if unsure.
* **Every commit needs a substantive changelog body.** A subject-only commit
  is unacceptable. Explain the problem or root cause, why the change is
  needed, the chosen approach and important tradeoffs, and relevant
  verification. Do not merely restate filenames or the diff.
* **In a repository that is or will be public, describe the problem's
  shape, never the private event that surfaced it.** Write "a card billed
  in a foreign currency", not the trip that produced the charge. Leave out
  names, places, dates, counts, amounts and health details drawn from
  personal data.
* Before committing, inspect recent high-quality commit messages in the
  repository and review the complete proposed message alongside the staged
  diff.
* Follow the repository's established commit convention. When none is
  apparent, or when bootstrapping a new project, apply basic Conventional
  Commits practice — a `type(scope): summary` subject over an explanatory
  body. Approximate it; the specification is not a compliance target.
* Target 50 columns for the subject and treat 60 as the hard limit. Wrap
  body prose at 72 columns, separate paragraphs with blank lines, and keep
  structured trailers together at the end.
* **Credit AI assistance with `Assisted-by`.** Every AI-assisted commit
  carries one `Assisted-by: <harness> (<model-id>)` trailer per model that
  took part, whether it wrote, designed or reviewed the change; for
  example `Assisted-by: Codex (gpt-6.1-sol)`, or
  `Assisted-by: Claude Code (glm-5.3)` when one vendor's harness runs
  another's model. The model id is the versioned API id that the harness,
  or a multi-agent run's receipt, reports for the turn that did the work.
  Never use a display name, a floating alias, a gateway's route name, or
  a context-window or effort suffix such as `[1m]` or `-high`; never
  infer the id from prompt text, memory or a configured default; never
  impersonate a different model. Say in the body what each model did. A project or the user may
  waive or change this practice, including a project that forbids naming
  the model or forbids AI trailers.
* **A model is never a co-author, reviewer or signer.** `Co-authored-by`,
  `Reviewed-by`, `Acked-by`, `Tested-by` and `Signed-off-by` are each a
  statement a person makes and answers for, so none of them names a
  model. Never add a `Signed-off-by` on your own initiative, not even the
  user's; only the user can certify the Developer Certificate of Origin.
* **Keep the harness's session link.** When the harness documents a
  trailer that links a commit to the session that made it, put it after
  the `Assisted-by` lines. Never invent one for a harness that documents
  none.

## Documentation
* README.md = users (usage, install). CLAUDE.md/AGENTS.md = developers
  (architecture, patterns). No duplication.
* **Update docs with code changes** — same commit for small changes,
  immediately after for large. Never defer.

## Data Protection
* NEVER commit real/sensitive data anywhere (examples, tests, comments,
  commits). Use clearly fictitious data.

## Context Hygiene
* **Never stream verbose output into context.** Commands like `dnf install`,
  `pip install`, `npm install`, `cargo build`, and bulk file operations
  produce progress bars and transaction logs that waste tokens.
* Redirect to a log file with a unique name under `~/tmp`, never `/tmp`,
  and only surface it on failure:
  `log=$(mktemp -p ~/tmp); cmd > "$log" 2>&1 || { cat "$log"; false; }`
* On success, report a one-line summary (e.g., "12 packages installed").

## Quality Standards
* **No technical debt**: don't rush quick solutions. Implement properly or
  ask first.
* **No silent failures**: never guard/suppress errors without addressing
  root cause. If something is missing, ensure it gets installed/configured —
  don't just skip it.
* **Full isolation**: solutions must be correct in all cases, not just
  "most" or "single-user". No leaking state across processes, profiles, or
  sessions.
* **Ask when in doubt**: if unsure whether a solution meets these standards,
  ask before implementing.

## Project Setup
* Create `AGENTS.md` early to document developer-facing patterns as they
  emerge
* Add `CLAUDE.md` as a thin entry point to `AGENTS.md` when the project also
  supports a harness that reads it
* Set up .gitignore immediately to prevent sensitive data commits

## Python Projects
* **Always use `--system-site-packages`** when creating venvs:
  `python3 -m venv --system-site-packages .venv`
* This reduces supply-chain attack surface — most deps come from signed
  Fedora RPMs, only pip-install what's not packaged in Fedora
* Use direnv `.envrc` to auto-create the venv on first `cd` (see existing
  projects for the pattern)
* Add `.envrc` and `.venv/` to `.gitignore`
