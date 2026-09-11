#!/bin/bash
# Tests for the BASE detection logic used in harnesses/claude-code/agents/commit-reviewer.md
# Creates temporary git repos to verify correct base branch detection.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"

# The BASE detection command from harnesses/claude-code/agents/commit-reviewer.md
detect_base() {
    BASE=$(git rev-parse --abbrev-ref @{upstream} 2>/dev/null || { git rev-parse --verify main >/dev/null 2>&1 && echo main; } || echo master)
    echo "$BASE"
}

# Helper: create a bare remote and a cloned working repo under ~/tmp
setup_repo() {
    local dir="$HOME/tmp/test-commit-reviewer-$$"
    rm -rf "$dir"
    mkdir -p "$dir"
    echo "$dir"
}

cleanup_repo() {
    rm -rf "$1"
}

# --- Test: upstream tracking branch ---

test_begin "BASE detects upstream tracking branch"
_dir=$(setup_repo)
(
    cd "$_dir"
    git init -b main --bare remote.git >/dev/null 2>&1
    git clone remote.git work >/dev/null 2>&1
    cd work
    git commit --allow-empty -m "init" >/dev/null 2>&1
    git push >/dev/null 2>&1
    git checkout -b feature >/dev/null 2>&1
    git push -u origin feature >/dev/null 2>&1
    _stdout=$(detect_base)
    # Should detect origin/feature as upstream
    echo "$_stdout"
) > /dev/null 2>&1

# Run again to capture output for assertion
_stdout=$(cd "$_dir/work" && detect_base)
_exit_code=$?
assert_output_contains "origin/feature"
assert_exit_code 0
cleanup_repo "$_dir"

# --- Test: no upstream, main branch exists ---

test_begin "BASE falls back to main when no upstream"
_dir=$(setup_repo)
(
    cd "$_dir"
    git init -b main repo >/dev/null 2>&1
    cd repo
    git commit --allow-empty -m "init" >/dev/null 2>&1
) > /dev/null 2>&1

_stdout=$(cd "$_dir/repo" && detect_base)
_exit_code=$?
assert_output_contains "main"
assert_exit_code 0
cleanup_repo "$_dir"

# --- Test: no upstream, only master branch ---

test_begin "BASE falls back to master when no upstream and no main"
_dir=$(setup_repo)
(
    cd "$_dir"
    git init -b master repo >/dev/null 2>&1
    cd repo
    git commit --allow-empty -m "init" >/dev/null 2>&1
) > /dev/null 2>&1

_stdout=$(cd "$_dir/repo" && detect_base)
_exit_code=$?
assert_output_contains "master"
assert_exit_code 0
cleanup_repo "$_dir"

# --- Test: output is a single line (no SHA leakage) ---

test_begin "BASE output is exactly one line (no SHA leakage)"
_dir=$(setup_repo)
(
    cd "$_dir"
    git init -b main repo >/dev/null 2>&1
    cd repo
    git commit --allow-empty -m "init" >/dev/null 2>&1
) > /dev/null 2>&1

_stdout=$(cd "$_dir/repo" && detect_base)
_exit_code=$?
_line_count=$(echo "$_stdout" | wc -l)
if [ "$_line_count" -eq 1 ]; then
    (( _pass++ ))
else
    (( _fail++ ))
    echo "  FAIL: $_test_name"
    echo "    expected 1 line, got $_line_count"
    echo "    output: $_stdout"
fi
assert_exit_code 0
cleanup_repo "$_dir"

test_summary "commit-reviewer"
