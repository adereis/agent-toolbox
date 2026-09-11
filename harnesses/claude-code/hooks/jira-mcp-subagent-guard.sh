#!/bin/bash
#
# PreToolUse hook: Subagent delegation guard
#
# Blocks specific tools from running in the main agent, forcing them
# into subagents (via the Agent tool). This keeps the main conversation
# context clean — MCP calls that return large payloads or require
# multiple round-trips are better isolated in subagents.
#
# The tool matching is handled by the "matcher" field in settings.json,
# not by this script. This script only checks whether the call comes
# from the main agent (no agent_id) or a subagent (has agent_id).
#
# To guard additional tools, add more matcher entries in settings.json
# pointing to this same script. Examples:
#
#   {"matcher": "mcp__atlassian__*", ...}   # Jira MCP
#   {"matcher": "mcp__slack__*", ...}       # Slack MCP
#   {"matcher": "mcp__notion__*", ...}      # Notion MCP
#   {"matcher": "mcp__github__*", ...}      # GitHub MCP
#
# How it works:
# - Receives JSON on stdin with tool_name and agent_id
# - If agent_id is absent → main agent → block with reason
# - If agent_id is present → subagent → allow
#
# Requires Claude Code >= 2.1.64 (agent_id in hook inputs).
#
# Best used with a CLAUDE.md instruction like:
#   "Delegate Jira MCP calls to subagents to keep the main conversation clean"
# The CLAUDE.md provides guidance and rationale; this hook enforces it.
# In practice, the instruction alone is not always followed — but once
# the hook fires and blocks, the agent recognizes the pattern and
# self-corrects for the rest of the session.
#
# Upstream issue: https://github.com/anthropics/claude-code/issues/9340
# MCP tool results (e.g., jira_get_issue) can return 10-12k tokens of
# raw JSON rendered as a wall of text in the terminal. This hook forces
# those calls into subagents where the verbose output stays hidden. A
# per-tool display mode or --quiet flag would make this unnecessary.
#

# --- Configuration ---
BLOCK_REASON="Delegate this MCP call to a subagent (Agent tool) to keep the main conversation clean."
# ---------------------

input=$(cat)
agent_id=$(echo "$input" | jq -r '.agent_id // empty')

if [ -z "$agent_id" ]; then
    cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "$BLOCK_REASON"
  }
}
EOF
else
    # Subagent call — allow without intervention
    exit 0
fi
