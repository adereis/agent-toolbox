#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"
HOOK="$SCRIPT_DIR/../harnesses/claude-code/hooks/continue-plan.sh"

# Use isolated state dir to avoid interfering with real state
export XDG_STATE_HOME=$(mktemp -d)
trap "rm -rf $XDG_STATE_HOME" EXIT

test_begin "does nothing when CLAUDE_AUTO_PLAN is unset"
unset CLAUDE_AUTO_PLAN
run_hook "$HOOK" '{"transcript_path":""}'
assert_output_empty
assert_exit_code 0

test_begin "does nothing when CLAUDE_AUTO_PLAN=0"
export CLAUDE_AUTO_PLAN=0
run_hook "$HOOK" '{"transcript_path":""}'
assert_output_empty
assert_exit_code 0

test_begin "exits 2 with stderr message when CLAUDE_AUTO_PLAN=1"
export CLAUDE_AUTO_PLAN=1
run_hook "$HOOK" '{"transcript_path":""}'
assert_exit_code 2
assert_stderr_contains "AUTO-CONTINUE MODE"

test_begin "increments counter on each invocation"
export CLAUDE_AUTO_PLAN=1
# Reset counter
rm -f "$XDG_STATE_HOME/claude-code/continue-count"
run_hook "$HOOK" '{"transcript_path":""}'
assert_stderr_contains "1/5"
run_hook "$HOOK" '{"transcript_path":""}'
assert_stderr_contains "2/5"

test_begin "stops after 5 invocations"
export CLAUDE_AUTO_PLAN=1
echo "5" > "$XDG_STATE_HOME/claude-code/continue-count"
run_hook "$HOOK" '{"transcript_path":""}'
assert_exit_code 0
assert_output_empty

test_begin "stops when ALL_PHASES_COMPLETE found in transcript"
export CLAUDE_AUTO_PLAN=1
rm -f "$XDG_STATE_HOME/claude-code/continue-count"
transcript=$(mktemp)
echo "some output" > "$transcript"
echo "ALL_PHASES_COMPLETE" >> "$transcript"
run_hook "$HOOK" '{"transcript_path":"'"$transcript"'"}'
assert_exit_code 0
rm -f "$transcript"

test_summary "continue-plan"
