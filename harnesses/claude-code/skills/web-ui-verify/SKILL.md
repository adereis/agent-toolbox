---
name: web-ui-verify
description: Verify a running web app's UI actually works in a real browser
argument-hint: "[what to verify, e.g. 'the invoice modal' or a page/flow]"
disable-model-invocation: true
context: fork
agent: web-ui-verifier
---

Verify a running web app's UI by driving a real headless browser over it —
screenshot pages and read them back, capture JS console/`pageerror` events, and
check the DB before/after any write. For Python + local-DB web projects
(Flask/Django/FastAPI, SQLite/Postgres).

**Scope**: No arg = full smoke tour of every page (HTTP 200 + 0 pageerrors,
eyeball screenshots). Otherwise, focus on the page, flow, or bug described.

Verify: $ARGUMENTS
