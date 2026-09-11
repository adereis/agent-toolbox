#!/bin/bash
# Auto-continue hook for multi-phase plans
# Enable: CLAUDE_AUTO_PLAN=1 claude
#
# Uses exit code 2 to block stopping and inject message via stderr

state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/claude-code"
mkdir -p "$state_dir"
counter_file="$state_dir/continue-count"

# Read hook input to get transcript path
input=$(cat)
transcript_path=$(echo "$input" | grep -o '"transcript_path":"[^"]*"' | cut -d'"' -f4)

# Not enabled? Do nothing.
if [ "${CLAUDE_AUTO_PLAN:-0}" != "1" ]; then
    exit 0
fi

# Check if plan is complete (look in transcript for the marker)
if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
    if tail -50 "$transcript_path" | grep -q "ALL_PHASES_COMPLETE"; then
        rm -f "$counter_file"
        exit 0
    fi
fi

# Count restarts
count=$(cat "$counter_file" 2>/dev/null || echo 0)
count=$((count + 1))
echo "$count" > "$counter_file"

# Stop after 5
if [ "$count" -gt 5 ]; then
    rm -f "$counter_file"
    exit 0
fi

# Block stop with message to stderr, exit code 2
cat >&2 <<EOF
AUTO-CONTINUE MODE ($count/5): Do not wait for user confirmation. Continue autonomously.

1. Run tests if code changed, fix any failures
2. If you need to make a decision, use CLAUDE.md, AGENTS.md, README.md, the original plan, and git log. Do NOT ask.
3. Record significant decisions in DECISIONS.md (timestamp, context, options, choice, rationale)
4. Proceed to the next phase
5. When ALL phases complete, output ALL_PHASES_COMPLETE
EOF
exit 2
