# Global baseline

Shared working agreements for coding agents. Repository conventions and
direct user instructions take precedence over every default below.

## CRITICAL: Temporary Files
**ALWAYS use ~/tmp, NEVER /tmp** — predictable filenames in /tmp are a
security risk.

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
* **AI co-authorship is required by default.** Every AI-assisted commit
  carries an accurate `Co-Authored-By: <agent/model> <email>` trailer. Use
  the model identity the harness reports for the current turn; never infer
  it from prompt text, memory, or a configured default, and never
  impersonate a different model. A project or the user may waive or change
  this practice.

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
* Redirect to a log file and only surface on failure:
  `cmd > ~/tmp/cmd.log 2>&1 || { cat ~/tmp/cmd.log; false; }`
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
