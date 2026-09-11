#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"
HOOK="$SCRIPT_DIR/../harnesses/claude-code/hooks/test-edit-guard.sh"

# Ensure debug log dir exists
mkdir -p ~/tmp

test_begin "Edit test_foo.py triggers context injection"
run_hook "$HOOK" '{"tool_name":"Edit","tool_input":{"file_path":"/home/user/project/test_foo.py"}}'
assert_output_contains '"additionalContext"'
assert_output_contains 'TEST FILE EDITED'
assert_exit_code 0

test_begin "Edit foo_test.go triggers context injection"
run_hook "$HOOK" '{"tool_name":"Edit","tool_input":{"file_path":"/home/user/project/foo_test.go"}}'
assert_output_contains '"additionalContext"'

test_begin "Edit foo.test.js triggers context injection"
run_hook "$HOOK" '{"tool_name":"Edit","tool_input":{"file_path":"/home/user/project/foo.test.js"}}'
assert_output_contains '"additionalContext"'

test_begin "Edit foo.spec.ts triggers context injection"
run_hook "$HOOK" '{"tool_name":"Edit","tool_input":{"file_path":"/home/user/project/foo.spec.ts"}}'
assert_output_contains '"additionalContext"'

test_begin "Edit file in tests/ directory triggers context injection"
run_hook "$HOOK" '{"tool_name":"Edit","tool_input":{"file_path":"/home/user/project/tests/conftest.py"}}'
assert_output_contains '"additionalContext"'

test_begin "Edit file in __tests__/ directory triggers context injection"
run_hook "$HOOK" '{"tool_name":"Edit","tool_input":{"file_path":"/home/user/project/__tests__/App.test.js"}}'
assert_output_contains '"additionalContext"'

test_begin "Edit regular source file does not trigger"
run_hook "$HOOK" '{"tool_name":"Edit","tool_input":{"file_path":"/home/user/project/src/main.py"}}'
assert_output_empty

test_begin "Edit file with 'test' in name but not a test pattern does not trigger"
run_hook "$HOOK" '{"tool_name":"Edit","tool_input":{"file_path":"/home/user/project/testimonial.py"}}'
assert_output_empty

test_begin "Non-Edit tool is ignored"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"vim test_foo.py"}}'
assert_output_empty
assert_exit_code 0

test_summary "test-edit-guard"
