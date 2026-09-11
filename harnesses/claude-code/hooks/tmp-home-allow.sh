#!/bin/bash
#
# PreToolUse hook: Auto-approve ~/tmp operations
#
# Problem: Claude Code's permission system prompts for confirmation on
# bash commands and file writes that don't match an allow-listed pattern.
# Prefix-based permission rules (e.g., "Bash(git:*)") can't cover every
# command shape where ~/tmp appears — it could be a redirect target, an
# argument in the middle of a pipeline, an env var assignment, etc.
#
# Solution: This hook inspects the full command/path and returns
# permissionDecision "allow" whenever ~/tmp is the target. This pairs
# with tmp-write-guard.sh, which hard-denies /tmp/ (predictable filenames
# in /tmp are a security risk). Together they enforce: ~/tmp = safe,
# /tmp = blocked.
#
# How it works:
# - For Write/Edit tools: resolves the file_path and checks if it falls
#   under ~/tmp/
# - For Bash tool: matches ~/tmp/ or $HOME/tmp/ anywhere in the command
# - Returns permissionDecision "allow" on match; exits silently otherwise
#   (letting subsequent hooks and the default permission system decide)
#
# Must be listed BEFORE tmp-write-guard.sh in settings.json so the allow
# decision is registered before the deny guard runs.
#

input=$(cat)

tool_name=$(echo "$input" | jq -r '.tool_name // ""')
home_tmp="$HOME/tmp"

allow() {
    cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow"
  }
}
EOF
    exit 0
}

if [ "$tool_name" = "Write" ] || [ "$tool_name" = "Edit" ]; then
    file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')
    resolved_path=$(realpath -m "$file_path" 2>/dev/null || echo "$file_path")
    if [[ "$resolved_path" == "$home_tmp"/* ]]; then
        allow
    fi
fi

if [ "$tool_name" = "Bash" ]; then
    command=$(echo "$input" | jq -r '.tool_input.command // ""')
    # Match ~/tmp or $HOME/tmp anywhere in the command
    if echo "$command" | grep -qE "(~/tmp|$home_tmp)/"; then
        allow
    fi
fi

exit 0
