# Shared tooling

`install.py` previews and applies scoped symlink installations. See
[installation](../docs/installation.md) for the command interface and
supported components. It never deploys reference examples or rewrites
native configuration files.

`_session_resume.py` provides the common presentation and interactive
selection used by the harness session utilities. Launch the entry point
documented under `harnesses/`; this module is not itself a
command. Keep it with the checkout when running or symlinking those utilities.

`_whats_new.py` parses a Markdown changelog whose releases are `## <version>`
headings, selects a window by baseline version, release count, or date, and
stores the baseline under `$XDG_STATE_HOME`. It reads a harness's own
changelog cache but never writes to it, keeping its copies under
`$XDG_CACHE_HOME/agent-toolbox/`. A cache is trusted only when it already
documents the running release, so a harness that updated moments ago does not
appear to have changed nothing. Release dates come from the npm packument and
are optional: only an explicit date window fails without them.

`_text.py` holds the terminal-safe rendering both of the above rely on.
Transcript and changelog text are untrusted input and must not reach a
terminal with their escape sequences intact.

The browser lists history before asking to resume. It passes the selected
harness configuration directory to the native process, requires an explicit
replacement for a missing working directory, and emits plain text when
piped. `--json` supports read-only use by other tools.
