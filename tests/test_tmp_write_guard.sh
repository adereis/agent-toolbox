#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"
HOOK="$SCRIPT_DIR/../harnesses/claude-code/hooks/tmp-write-guard.sh"

# --- Write tool ---

test_begin "Write to /tmp/foo is denied"
run_hook "$HOOK" '{"tool_name":"Write","tool_input":{"file_path":"/tmp/foo.txt"}}'
assert_output_contains '"permissionDecision": "deny"'
assert_exit_code 0

test_begin "Write to ~/tmp/foo is allowed"
run_hook "$HOOK" '{"tool_name":"Write","tool_input":{"file_path":"'"$HOME"'/tmp/foo.txt"}}'
assert_output_empty

test_begin "Write to /home/user/project/file is allowed"
run_hook "$HOOK" '{"tool_name":"Write","tool_input":{"file_path":"/home/user/project/file.txt"}}'
assert_output_empty

test_begin "Write with path traversal to /tmp is denied"
run_hook "$HOOK" '{"tool_name":"Write","tool_input":{"file_path":"/home/user/../../tmp/exploit.sh"}}'
assert_output_contains '"permissionDecision": "deny"'

# --- Bash tool ---

test_begin "Bash: echo > /tmp/foo is denied"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"echo hello > /tmp/foo"}}'
assert_output_contains '"permissionDecision": "deny"'

test_begin "Bash: cp file /tmp/ is denied"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"cp myfile /tmp/backup"}}'
assert_output_contains '"permissionDecision": "deny"'

test_begin "Bash: cat /tmp/foo is allowed (read-only)"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"cat /tmp/foo"}}'
assert_output_empty

test_begin "Bash: ls /tmp/ is allowed (read-only)"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"ls /tmp/"}}'
assert_output_empty

test_begin "Bash: head /tmp/foo is allowed (read-only)"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"head -20 /tmp/foo"}}'
assert_output_empty

test_begin "Bash: rm /tmp/foo is allowed (cleanup)"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"rm -f /tmp/old-file"}}'
assert_output_empty

test_begin "Bash: git command mentioning /tmp is allowed"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"git commit -m \"fix /tmp/ usage\""}}'
assert_output_empty

test_begin "Bash: cat > /tmp/foo is denied (redirect from read-only)"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"cat > /tmp/foo"}}'
assert_output_contains '"permissionDecision": "deny"'

test_begin "Bash: command without /tmp is allowed"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"echo hello world"}}'
assert_output_empty

test_begin "Non-matching tool is ignored"
run_hook "$HOOK" '{"tool_name":"Read","tool_input":{"file_path":"/tmp/foo"}}'
assert_output_empty

test_summary "tmp-write-guard"
