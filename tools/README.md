# Shared tooling

`_session_resume.py` provides the common presentation and interactive
selection used by the harness session utilities. Launch the entry point
documented under `harnesses/`; this module is not itself a
command. Keep it with the checkout when running or symlinking those utilities.

The browser lists history before asking to resume. It passes the selected
harness configuration directory to the native process, requires an explicit
replacement for a missing working directory, and emits plain text when
piped. `--json` supports read-only use by other tools.
