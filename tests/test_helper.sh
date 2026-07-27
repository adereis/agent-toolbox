#!/bin/bash
# Minimal test assertion library for hook tests
# Source this from test_*.sh files

_pass=0
_fail=0
_test_name=""

test_begin() {
    _test_name="$1"
}

assert_output_contains() {
    local expected="$1"
    if echo "$_stdout" | grep -q "$expected"; then
        (( _pass++ ))
    else
        (( _fail++ ))
        echo "  FAIL: $_test_name"
        echo "    expected output to contain: $expected"
        echo "    got: $_stdout"
    fi
}

assert_output_lacks() {
    local unexpected="$1"
    if echo "$_stdout" | grep -q "$unexpected"; then
        (( _fail++ ))
        echo "  FAIL: $_test_name"
        echo "    expected output NOT to contain: $unexpected"
        echo "    got: $_stdout"
    else
        (( _pass++ ))
    fi
}

assert_output_empty() {
    if [ -z "$_stdout" ]; then
        (( _pass++ ))
    else
        (( _fail++ ))
        echo "  FAIL: $_test_name"
        echo "    expected empty output"
        echo "    got: $_stdout"
    fi
}

assert_stderr_contains() {
    local expected="$1"
    if echo "$_stderr" | grep -q "$expected"; then
        (( _pass++ ))
    else
        (( _fail++ ))
        echo "  FAIL: $_test_name"
        echo "    expected stderr to contain: $expected"
        echo "    got stderr: $_stderr"
    fi
}

assert_exit_code() {
    local expected="$1"
    if [ "$_exit_code" -eq "$expected" ]; then
        (( _pass++ ))
    else
        (( _fail++ ))
        echo "  FAIL: $_test_name"
        echo "    expected exit code: $expected"
        echo "    got: $_exit_code"
    fi
}

# Run a hook with JSON input, capture stdout, stderr, and exit code
run_hook() {
    local hook="$1"
    local json="$2"
    _stderr_file=$(mktemp)
    _stdout=$(echo "$json" | "$hook" 2>"$_stderr_file")
    _exit_code=$?
    _stderr=$(cat "$_stderr_file")
    rm -f "$_stderr_file"
}

# Run a script with arguments, capture stdout, stderr, and exit code
run_script() {
    local script="$1"
    shift
    _stderr_file=$(mktemp)
    _stdout=$("$script" "$@" 2>"$_stderr_file")
    _exit_code=$?
    _stderr=$(cat "$_stderr_file")
    rm -f "$_stderr_file"
}

# Print summary and return appropriate exit code
test_summary() {
    local file_name="${1:-tests}"
    echo "$file_name: $_pass passed, $_fail failed"
    [ "$_fail" -eq 0 ]
}
