#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"
HOOK="$SCRIPT_DIR/../harnesses/claude-code/hooks/jira-mcp-subagent-guard.sh"

test_begin "Main agent (no agent_id) is blocked"
run_hook "$HOOK" '{"tool_name":"mcp__atlassian__jira_search","tool_input":{"jql":"project = TEST"}}'
assert_output_contains '"permissionDecision": "deny"'
assert_output_contains '"permissionDecisionReason"'
assert_exit_code 0

test_begin "Subagent (has agent_id) is allowed"
run_hook "$HOOK" '{"tool_name":"mcp__atlassian__jira_search","tool_input":{"jql":"project = TEST"},"agent_id":"abc123"}'
assert_output_empty
assert_exit_code 0

test_begin "Block reason mentions subagent delegation"
run_hook "$HOOK" '{"tool_name":"mcp__atlassian__jira_get_issue","tool_input":{"issue_key":"TEST-1"}}'
assert_output_contains 'subagent'

test_begin "Any MCP tool is handled (script does not filter by tool name)"
run_hook "$HOOK" '{"tool_name":"mcp__slack__send_message","tool_input":{}}'
assert_output_contains '"permissionDecision": "deny"'

test_begin "Any MCP tool with agent_id is allowed"
run_hook "$HOOK" '{"tool_name":"mcp__slack__send_message","tool_input":{},"agent_id":"xyz789"}'
assert_output_empty

test_summary "jira-mcp-subagent-guard"
