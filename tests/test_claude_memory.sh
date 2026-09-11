#!/bin/bash
# Tests for claude-memory-{export,import,status} scripts.
#
# Creates isolated mock directories to simulate Claude Code's memory
# layout, then exercises export/import/status round-trips.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"

EXPORT="$SCRIPT_DIR/../harnesses/claude-code/scripts/claude-memory-export.sh"
IMPORT="$SCRIPT_DIR/../harnesses/claude-code/scripts/claude-memory-import.sh"
STATUS="$SCRIPT_DIR/../harnesses/claude-code/scripts/claude-memory-status.sh"

# --- Test environment setup ---

TEST_ROOT=$(mktemp -d "$HOME/tmp/claude-memory-test.XXXXXX")
trap 'rm -rf "$TEST_ROOT"' EXIT

MOCK_HOME="$TEST_ROOT/fakehome"
MOCK_CLAUDE="$MOCK_HOME/.claude"
MOCK_PROJECTS="$MOCK_HOME/projects"
MOCK_PORTABLE="$TEST_ROOT/portable"

HOME_ENC=$(echo "$MOCK_HOME" | tr '/' '-')

setup_clean() {
    rm -rf "$TEST_ROOT"/*
    mkdir -p "$MOCK_HOME" "$MOCK_PROJECTS"
}

# Create a mock project with a .git dir and Claude memories
create_project() {
    local slug="$1"
    shift

    mkdir -p "$MOCK_PROJECTS/$slug/.git"
    local encoded
    encoded=$(echo "$MOCK_HOME/projects/$slug" | tr '/' '-')
    local mem_dir="$MOCK_CLAUDE/projects/$encoded/memory"
    mkdir -p "$mem_dir"

    for file in "$@"; do
        local name="${file%%=*}"
        local content="${file#*=}"
        echo "$content" > "$mem_dir/$name"
    done
}

# Create global memories
create_global() {
    local mem_dir="$MOCK_CLAUDE/projects/$HOME_ENC/memory"
    mkdir -p "$mem_dir"
    for file in "$@"; do
        local name="${file%%=*}"
        local content="${file#*=}"
        echo "$content" > "$mem_dir/$name"
    done
}

# Common env vars for all script invocations
run_mem() {
    local script="$1"
    shift
    HOME="$MOCK_HOME" \
    CLAUDE_DIR="$MOCK_CLAUDE" \
    CLAUDE_PROJECTS_DIR="$MOCK_PROJECTS" \
    CLAUDE_MEMORY_DIR="$MOCK_PORTABLE" \
    run_script "$script" "$@"
}

# ===== Export tests =====

setup_clean
create_project "alpha" "MEMORY.md=# Alpha" "user_role.md=role content"

test_begin "export: collects project memories"
run_mem "$EXPORT"
assert_exit_code 0
assert_output_contains "NEW"
assert_output_contains "alpha/memory/MEMORY.md"
assert_output_contains "alpha/memory/user_role.md"

test_begin "export: files exist in portable dir"
if [[ -f "$MOCK_PORTABLE/alpha/memory/MEMORY.md" && \
      -f "$MOCK_PORTABLE/alpha/memory/user_role.md" ]]; then
    (( _pass++ ))
else
    (( _fail++ ))
    echo "  FAIL: $_test_name — files not found in portable dir"
fi

test_begin "export: second run shows SKIP for unchanged"
run_mem "$EXPORT"
assert_exit_code 0
assert_output_contains "SKIP"

test_begin "export: detects changed files"
local_encoded=$(echo "$MOCK_HOME/projects/alpha" | tr '/' '-')
echo "updated role" > "$MOCK_CLAUDE/projects/$local_encoded/memory/user_role.md"
run_mem "$EXPORT"
assert_output_contains "COLLECTED"
assert_output_contains "user_role.md"

# ===== Global memory export =====

setup_clean
create_global "MEMORY.md=# Global" "feedback_style.md=be terse"

test_begin "export: collects global memories as _global"
run_mem "$EXPORT"
assert_exit_code 0
assert_output_contains "_global/memory/MEMORY.md"
assert_output_contains "_global/memory/feedback_style.md"

test_begin "export: global files land in _global slug"
if [[ -f "$MOCK_PORTABLE/_global/memory/MEMORY.md" ]]; then
    (( _pass++ ))
else
    (( _fail++ ))
    echo "  FAIL: $_test_name — _global/memory/MEMORY.md not found"
fi

# ===== Nested project export =====

setup_clean
create_project "org/sub-project" "MEMORY.md=# Nested"

test_begin "export: handles nested project slugs"
run_mem "$EXPORT"
assert_exit_code 0
assert_output_contains "org/sub-project/memory/MEMORY.md"

test_begin "export: nested slug creates correct directory"
if [[ -f "$MOCK_PORTABLE/org/sub-project/memory/MEMORY.md" ]]; then
    (( _pass++ ))
else
    (( _fail++ ))
    echo "  FAIL: $_test_name — nested slug directory not created correctly"
fi

# ===== Skip prefix =====

setup_clean
create_project "work/secret" "MEMORY.md=# Secret"
create_project "personal" "MEMORY.md=# Personal"

test_begin "export: --skip filters projects by prefix"
run_mem "$EXPORT" --skip "work/"
assert_exit_code 0
assert_output_contains "personal/memory/MEMORY.md"

test_begin "export: skipped project not in output"
if echo "$_stdout" | grep -q "work/secret"; then
    (( _fail++ ))
    echo "  FAIL: $_test_name — skipped project appeared in output"
else
    (( _pass++ ))
fi

# Multiple skip prefixes

setup_clean
create_project "work/secret" "MEMORY.md=# Secret"
create_project "scratch/temp" "MEMORY.md=# Temp"
create_project "personal" "MEMORY.md=# Personal"

test_begin "export: multiple --skip flags"
run_mem "$EXPORT" --skip "work/" --skip "scratch/"
assert_exit_code 0
assert_output_contains "personal/memory/MEMORY.md"

test_begin "export: all skipped prefixes filtered"
if echo "$_stdout" | grep -qE "work/|scratch/"; then
    (( _fail++ ))
    echo "  FAIL: $_test_name — skipped project appeared in output"
else
    (( _pass++ ))
fi

# ===== Import tests =====

setup_clean
create_project "beta" "MEMORY.md=# Beta" "feedback.md=feedback content"
run_mem "$EXPORT" > /dev/null

# Clear disk memories, then import
local_encoded=$(echo "$MOCK_HOME/projects/beta" | tr '/' '-')
rm -rf "$MOCK_CLAUDE/projects/$local_encoded/memory"

test_begin "import: deploys files from portable dir"
run_mem "$IMPORT"
assert_exit_code 0
assert_output_contains "NEW"
assert_output_contains "beta/memory/MEMORY.md"

test_begin "import: files restored on disk"
if [[ -f "$MOCK_CLAUDE/projects/$local_encoded/memory/MEMORY.md" ]]; then
    (( _pass++ ))
else
    (( _fail++ ))
    echo "  FAIL: $_test_name — file not restored"
fi

test_begin "import: second run shows SKIP"
run_mem "$IMPORT"
assert_exit_code 0
assert_output_contains "SKIP"

test_begin "import: detects updated portable file"
echo "updated feedback" > "$MOCK_PORTABLE/beta/memory/feedback.md"
run_mem "$IMPORT"
assert_output_contains "DEPLOYED"
assert_output_contains "feedback.md"

# ===== Import with skip =====

setup_clean
mkdir -p "$MOCK_PORTABLE/work-proj/memory" "$MOCK_PORTABLE/home-proj/memory"
echo "# Work" > "$MOCK_PORTABLE/work-proj/memory/MEMORY.md"
echo "# Home" > "$MOCK_PORTABLE/home-proj/memory/MEMORY.md"

test_begin "import: --skip filters during import"
run_mem "$IMPORT" --skip "work-"
assert_exit_code 0
assert_output_contains "home-proj"

test_begin "import: skipped project not deployed"
if echo "$_stdout" | grep -q "work-proj"; then
    (( _fail++ ))
    echo "  FAIL: $_test_name — skipped project was deployed"
else
    (( _pass++ ))
fi

# ===== Import error: missing portable dir =====

setup_clean

test_begin "import: errors when portable dir missing"
run_mem "$IMPORT"
assert_exit_code 1
assert_stderr_contains "not found"

# ===== Status tests =====

setup_clean
create_project "gamma" "MEMORY.md=# Gamma" "notes.md=some notes"
run_mem "$EXPORT" > /dev/null

test_begin "status: shows OK when in sync"
run_mem "$STATUS"
assert_exit_code 0
assert_output_contains "OK"
assert_output_contains "gamma/memory/MEMORY.md"

test_begin "status: detects DIFFERS after local edit"
local_encoded=$(echo "$MOCK_HOME/projects/gamma" | tr '/' '-')
echo "modified" > "$MOCK_CLAUDE/projects/$local_encoded/memory/notes.md"
run_mem "$STATUS"
assert_exit_code 2
assert_output_contains "DIFFERS"
assert_output_contains "notes.md"

# ===== Status: new local memory =====

setup_clean
create_project "delta" "MEMORY.md=# Delta"
run_mem "$EXPORT" > /dev/null

local_encoded=$(echo "$MOCK_HOME/projects/delta" | tr '/' '-')
echo "new memory" > "$MOCK_CLAUDE/projects/$local_encoded/memory/new_insight.md"

test_begin "status: discovers NEW_LOCAL memories"
run_mem "$STATUS"
assert_exit_code 2
assert_output_contains "NEW_LOCAL"
assert_output_contains "new_insight.md"

# ===== Status: deleted local memory =====

setup_clean
create_project "epsilon" "MEMORY.md=# Epsilon" "old.md=old content"
run_mem "$EXPORT" > /dev/null

local_encoded=$(echo "$MOCK_HOME/projects/epsilon" | tr '/' '-')
rm -f "$MOCK_CLAUDE/projects/$local_encoded/memory/old.md"

test_begin "status: detects DELETED_LOCAL"
run_mem "$STATUS"
assert_exit_code 2
assert_output_contains "DELETED_LOCAL"
assert_output_contains "old.md"

# ===== Status: empty (no memories anywhere) =====

setup_clean
mkdir -p "$MOCK_PROJECTS/empty/.git"

test_begin "status: clean exit when no memories exist"
run_mem "$STATUS"
assert_exit_code 0

# ===== Round-trip: export → import on different "machine" =====

setup_clean
create_project "roundtrip" "MEMORY.md=# RT" "data.md=important data"
create_global "MEMORY.md=# Global Index" "pref.md=user preference"
run_mem "$EXPORT" > /dev/null

# Simulate a different machine: new HOME, same portable dir
MOCK_HOME2="$TEST_ROOT/otherhome"
MOCK_CLAUDE2="$MOCK_HOME2/.claude"
MOCK_PROJECTS2="$MOCK_HOME2/projects"
mkdir -p "$MOCK_HOME2" "$MOCK_PROJECTS2/roundtrip/.git"
HOME_ENC2=$(echo "$MOCK_HOME2" | tr '/' '-')

test_begin "round-trip: import onto different HOME"
HOME="$MOCK_HOME2" \
CLAUDE_DIR="$MOCK_CLAUDE2" \
CLAUDE_PROJECTS_DIR="$MOCK_PROJECTS2" \
CLAUDE_MEMORY_DIR="$MOCK_PORTABLE" \
run_script "$IMPORT"
assert_exit_code 0
assert_output_contains "NEW"

test_begin "round-trip: files encoded with new HOME"
new_encoded=$(echo "$MOCK_HOME2/projects/roundtrip" | tr '/' '-')
if [[ -f "$MOCK_CLAUDE2/projects/$new_encoded/memory/MEMORY.md" ]]; then
    (( _pass++ ))
else
    (( _fail++ ))
    echo "  FAIL: $_test_name — file not at new encoded path"
    echo "    expected: $MOCK_CLAUDE2/projects/$new_encoded/memory/MEMORY.md"
fi

test_begin "round-trip: global memories encoded with new HOME"
if [[ -f "$MOCK_CLAUDE2/projects/$HOME_ENC2/memory/pref.md" ]]; then
    (( _pass++ ))
else
    (( _fail++ ))
    echo "  FAIL: $_test_name — global memory not at new HOME-encoded path"
fi

# ===== Done =====

test_summary "claude_memory"
