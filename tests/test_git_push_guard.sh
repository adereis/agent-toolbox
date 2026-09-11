#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"
HOOK="$SCRIPT_DIR/../harnesses/claude-code/hooks/git-push-guard.sh"

test_begin "git push triggers ask"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}'
assert_output_contains '"permissionDecision": "ask"'
assert_exit_code 0

test_begin "git push --force triggers ask"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"git push --force origin main"}}'
assert_output_contains '"permissionDecision": "ask"'

test_begin "git push with extra whitespace triggers ask"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"git   push origin main"}}'
assert_output_contains '"permissionDecision": "ask"'

test_begin "git status does not trigger"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"git status"}}'
assert_output_empty

test_begin "git pull does not trigger"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"git pull origin main"}}'
assert_output_empty

test_begin "non-Bash tool is ignored"
run_hook "$HOOK" '{"tool_name":"Write","tool_input":{"file_path":"/tmp/test"}}'
assert_output_empty
assert_exit_code 0

test_begin "echo containing git push does not trigger (not a word boundary)"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"echo git-push-guard"}}'
assert_output_empty

test_summary "git-push-guard"
