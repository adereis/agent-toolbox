# Claude Code agent configuration examples

Agent Toolbox no longer ships the commit-reviewer or web-ui-verifier agents
or their delegation skills. Use the optional [review prompts](../../../prompts/README.md)
with the tools and review facilities available in your harness.

The machine-specific Jira agent remains local configuration. The example
below documents that Claude-specific integration; it is not an installed
agent or a portable permission policy.

## Pattern: model-scoped MCP agent ("Layer 0")

**Goal:** make an MCP server (here, Jira/Atlassian) usable *only* through one
subagent that runs on a chosen model (Sonnet), so the main (Opus) thread never
touches it. Two payoffs:

- **Model control** — every Jira call runs on Sonnet. You can't tag an
  individual tool call with a model; a tool call runs on whatever model owns the
  turn. The only way to run a specific call on a specific model is to move it
  into a subagent configured for that model.
- **Context hygiene** — a single `jira_get_issue` can return 10k+ tokens of raw
  JSON. Isolated in a subagent, only the compact final report crosses back to
  the main thread.

### The mechanism that works: `mcpServers` frontmatter scoping

Define the MCP server *inline* in the agent's frontmatter and **remove it from
global config** (`~/.claude.json`). The server then exists only for that agent:

```yaml
---
name: jira
description: Handles ALL Jira/Atlassian work — get/search/create/update issues,
  comments, transitions, sprints, worklogs. Runs on Sonnet so Jira's verbose MCP
  output stays off the main context. Delegate any Jira/Atlassian request here.
model: sonnet
tools: mcp__atlassian__*
mcpServers:
  - atlassian:
      type: stdio
      command: /path/to/your/atlassian-mcp/run-stdio.sh   # your real launcher
---

You are a Jira/Atlassian specialist ...
```

Find your real launcher with `claude mcp get atlassian` (copy its `Command`,
`Args`, `Type`) before removing the global entry.

### Setup

1. Create `~/.claude/agents/jira.md` from the template above with your real
   `mcpServers` command.
2. Remove the server from global config so the main thread loses it:
   `claude mcp remove atlassian -s user`
   (Re-add if needed: `claude mcp add atlassian -s user -- /path/to/run-stdio.sh`)
3. Add a routing line to CLAUDE.md so Claude knows to delegate:
   *"The Jira MCP is scoped to the `jira` subagent only; delegate all
   Jira/Atlassian work to it."* The agent's `description` also drives routing.

### Why not `permissions.deny` (the approach that fails)

The tempting alternative — keep Jira in global config, `deny` it in the main
thread, and re-`allow` it via the agent's `tools:` list — **does not work for a
delegated subagent**. A session-level `permissions.deny` cascades into
Task-spawned subagents: the subagent resolves its `tools:` allowlist against the
parent's *already-filtered* toolset, matches nothing, and Claude Code refuses to
spawn it ("would be spawned with zero tools"). Verified empirically — it looks
like it works when you launch the session directly *as* the agent
(`--agent jira`), but breaks in the real topology where a main session
*delegates* to the agent.

`mcpServers` scoping avoids the trap entirely: it *adds* a server to the agent
rather than trying to re-permit a denied one.

### Verifying it works

Run headless and read the structured result (`--output-format json`):

- **Main thread has no Jira:** the `init` event's `mcp_servers` list omits
  `atlassian`.
- **Subagent ran on Sonnet:** the result event's `modelUsage` includes a
  `claude-sonnet-*` key (the agent's *self-reported* model is unreliable — trust
  `modelUsage`).

Requires Claude Code ≥ 2.1.153 (subagent MCP-scoping semantics).

### Relationship to `jira-mcp-subagent-guard.sh`

The [hook](../hooks/README.md#jira-mcp-subagent-guardsh) is the *soft* version of
this idea: it leaves Jira in global config and merely *blocks* main-thread calls,
nudging Claude to delegate. Use the hook when you want an MCP available in more
than one place but kept out of the main thread; use `mcpServers` scoping when you
want a single agent to own the server outright (and to pin its model). Under the
scoping approach the hook's `mcp__atlassian__*` matcher becomes a harmless no-op
(the main thread has no such tools to guard) — keep it only if you guard other
MCP servers with it.
