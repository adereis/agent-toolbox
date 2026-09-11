#!/bin/bash
#
# PreToolUse hook: Command confirmation guard
#
# Forces human confirmation for specific commands before execution.
# Acts as a safety net on top of Claude Code's permission system — even
# if Bash is pre-approved, matched commands still require explicit approval.
#
# Add pattern/reason pairs below to guard additional commands. The first
# matching pattern wins and its reason is shown to the user. Examples:
#
#   PATTERNS+=('\bkubectl\s+delete\b')    REASONS+=("kubectl delete requires approval")
#   PATTERNS+=('\bdocker\s+rm\b')         REASONS+=("docker rm requires approval")
#   PATTERNS+=('\bterraform\s+destroy\b') REASONS+=("terraform destroy requires approval")
#   PATTERNS+=('\brm\s+-rf\b')            REASONS+=("rm -rf requires approval")
#
# How it works:
# - Receives JSON on stdin with tool_name and tool_input
# - Matches Bash commands against each pattern in order (first match wins)
# - Returns permissionDecision "ask" with the matched reason
# - Returns nothing (exit 0) for non-matching commands
#

# --- Configuration: add as many guards as you need ---
PATTERNS=()  REASONS=()

PATTERNS+=('\bgit\s+push\b')
REASONS+=("Git push requires explicit approval")

# Uncomment or add more guards:
# PATTERNS+=('\bkubectl\s+delete\b')    REASONS+=("kubectl delete requires approval")
# PATTERNS+=('\bterraform\s+destroy\b') REASONS+=("terraform destroy requires approval")
# PATTERNS+=('\brm\s+-rf\b')            REASONS+=("rm -rf requires approval")
# -----------------------------------------------------

# Read JSON from stdin
input=$(cat)

# Extract tool name and command using jq
tool_name=$(echo "$input" | jq -r '.tool_name // ""')
command=$(echo "$input" | jq -r '.tool_input.command // ""')

# Only process Bash tool calls
if [ "$tool_name" != "Bash" ]; then
    exit 0
fi

# Check command against each guarded pattern (first match wins)
for i in "${!PATTERNS[@]}"; do
    if echo "$command" | grep -qE "${PATTERNS[$i]}"; then
        cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask",
    "permissionDecisionReason": "${REASONS[$i]}"
  }
}
EOF
        exit 0
    fi
done

# No pattern matched: no decision (use normal permission flow)
exit 0
