Verify the requested application page or workflow in a real browser using
the browser facilities available in this environment. Establish the URL,
scope, and an isolated test environment before actions that change data.
Use synthetic fixtures and avoid live user data.

Exercise the relevant interactions and inspect rendered results. Check
browser console errors, failed requests, keyboard behavior, and the expected
application state after each important action. For a persistence change,
verify the saved result through an independent read or reload. Capture and
inspect screenshots when visual evidence helps assess the result.

Follow the project's supported setup and testing procedures. Do not disable
browser sandboxing or invent installation and privilege requirements. If a
required capability is unavailable, explain the specific gap and what can
still be verified.

Report the scenarios exercised, expected and observed behavior, concrete
reproduction steps for failures, and relevant evidence. Distinguish browser
verification from unit tests and state anything that remains untested.
