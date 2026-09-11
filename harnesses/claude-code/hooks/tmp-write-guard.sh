#!/bin/bash
#
# PreToolUse hook: Path write deny guard
#
# Hard-blocks writes to specific paths. Acts as a security boundary
# that cannot be overridden — uses permissionDecision "deny" for
# unconditional blocking (no user override prompt).
#
# This hook blocks writes to /tmp/. Add path/message pairs below to
# block additional paths. Examples:
#
#   BLOCKED_PATHS+=('/etc/')      DENY_MESSAGES+=("Writing to /etc is blocked. Use project-local config.")
#   BLOCKED_PATHS+=('/var/run/')   DENY_MESSAGES+=("Writing to /var/run is blocked.")
#
# How it works:
# - Intercepts Write tool calls and Bash commands
# - Checks if target paths match any blocked prefix
# - Allows read-only Bash commands (ls, cat, head, tail, etc.)
# - Allows cleanup commands (rm) and git commands
# - Returns permissionDecision "deny" for writes to blocked paths
#
# Upstream issue: https://github.com/anthropics/claude-code/issues/14085
# The /tmp block may become unnecessary once resolved.
#

# --- Configuration: paths to block ---
BLOCKED_PATHS=()  DENY_MESSAGES=()

BLOCKED_PATHS+=('/tmp/')
DENY_MESSAGES+=("Writing to /tmp is blocked (predictable names are a security risk). Use ~/tmp instead.")

# Uncomment or add more:
# BLOCKED_PATHS+=('/etc/')       DENY_MESSAGES+=("Writing to /etc is blocked (system configuration). Use project-local config instead.")
# BLOCKED_PATHS+=('/var/run/')   DENY_MESSAGES+=("Writing to /var/run is blocked. Use a project-local directory instead.")
# ------------------------------------------

input=$(cat)

tool_name=$(echo "$input" | jq -r '.tool_name // ""')

deny_with_reason() {
    cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "$1"
  }
}
EOF
    exit 0
}

# Handle Write tool
if [ "$tool_name" = "Write" ]; then
    file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')
    # Resolve to absolute path to catch traversal (e.g., ../../../tmp/)
    resolved_path=$(realpath -m "$file_path" 2>/dev/null || echo "$file_path")
    for i in "${!BLOCKED_PATHS[@]}"; do
        if [[ "$resolved_path" == "${BLOCKED_PATHS[$i]}"* ]]; then
            deny_with_reason "${DENY_MESSAGES[$i]}"
        fi
    done
    exit 0
fi

# Handle Bash tool
if [ "$tool_name" = "Bash" ]; then
    command=$(echo "$input" | jq -r '.tool_input.command // ""')

    # Find which blocked path is referenced (if any)
    matched_index=-1
    for i in "${!BLOCKED_PATHS[@]}"; do
        path="${BLOCKED_PATHS[$i]}"
        dir_name=$(basename "${path%/}")
        # Match: space or redirect followed by the path, or ../<dirname>/ traversal
        if echo "$command" | grep -qE "(^|[[:space:]]|[>])${path}|\\.\\.\\/\b${dir_name}\b/"; then
            matched_index=$i
            break
        fi
    done

    # No blocked path referenced
    if [ "$matched_index" -eq -1 ]; then
        exit 0
    fi

    # Allow read-only commands (but NOT if they redirect to the blocked path)
    read_only_pattern='^[[:space:]]*(ls|cat|head|tail|less|more|file|stat|wc|md5sum|sha256sum|sha1sum|xxd|hexdump|strings|readlink|test|\[)([[:space:]]|$)'
    if echo "$command" | grep -qE "$read_only_pattern"; then
        # But block if redirecting to the blocked path (e.g., "cat > /tmp/file")
        path="${BLOCKED_PATHS[$matched_index]}"
        if echo "$command" | grep -qE ">>?[[:space:]]*${path}"; then
            deny_with_reason "${DENY_MESSAGES[$matched_index]}"
        fi
        exit 0
    fi

    # Allow rm (cleanup is fine)
    if echo "$command" | grep -qE '^[[:space:]]*rm[[:space:]]'; then
        exit 0
    fi

    # Allow git commands (may mention paths in commit messages, not actual writes)
    if echo "$command" | grep -qE '^[[:space:]]*git[[:space:]]'; then
        exit 0
    fi

    # Block commands that likely write to the blocked path
    deny_with_reason "${DENY_MESSAGES[$matched_index]}"
fi

exit 0
