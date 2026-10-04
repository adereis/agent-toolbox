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
# - Joins the command onto one line (continuations and newlines become
#   spaces), so a command split across lines cannot slip past a pattern
# - Matches it against each pattern in order (first match wins)
# - Returns permissionDecision "ask" with the matched reason
# - Returns nothing (exit 0) for non-matching commands
#
# Patterns scan the command text; they do not parse the shell. Text that
# merely mentions a guarded command (an echo, a commit message) is asked
# about too. That is deliberate: a parser that misreads one construct
# lets a real command through unasked, and for a safety net a needless
# prompt is the cheaper mistake.
#

# --- Configuration: add as many guards as you need ---
PATTERNS=()  REASONS=()

# git takes global options before the subcommand, and agents use them to
# work across repositories: `git -C "$repo" push` must be caught like
# `git push`. So: `git`, any run of global options (with a separate
# argument for those that take one), then `push`. An argument may be
# quoted (spaces included) or a $(...) or `...` substitution. Written
# with POSIX classes only, not the GNU-specific \b and \s.
_ARG="(\"[^\"]*\"|'[^']*'|\\\$\\([^)]*\\)|\`[^\`]*\`|[^[:space:]\"'\`;&|()]+)+"
_GIT_OPT="(-C|-c|--git-dir|--work-tree|--namespace)[[:space:]]+${_ARG}|--?[[:alnum:]][[:alnum:]-]*(=${_ARG})?"
PATTERNS+=("(^|[^[:alnum:]_.-])git([[:space:]]+(${_GIT_OPT}))*[[:space:]]+push([^[:alnum:]_-]|\$)")
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

# grep matches line by line, so `git -C repo \` + newline + `push` would
# never match. Join continuations, then every line, with spaces.
command=${command//$'\\\n'/ }
command=${command//$'\n'/ }

# Check command against each guarded pattern (first match wins). printf,
# not echo: echo would take a command starting with -n or -e as options.
for i in "${!PATTERNS[@]}"; do
    if printf '%s\n' "$command" | grep -qE -- "${PATTERNS[$i]}"; then
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
