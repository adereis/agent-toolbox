#!/bin/bash
#
# PreToolUse hook: File edit context guard
#
# Injects contextual guidance when specific file types are edited.
# Uses additionalContext to show a message after the edit, prompting
# Claude to verify the edit was appropriate.
#
# This hook guards test file edits. Add pattern groups below to guard
# additional file types. Each group needs: a label (for logging), a
# filename regex, a directory regex, and a context message. A file
# matches if either its name or directory matches. First match wins.
#
# Examples:
#
#   LABELS+=("CI/CD config")
#   FILE_PATTERNS+=('(Jenkinsfile|\.gitlab-ci\.yml|\.github/workflows/.*\.yml)')
#   DIR_PATTERNS+=('/(\.github/workflows|\.circleci)(/|$)')
#   CONTEXT_MESSAGES+=('CI/CD CONFIG EDITED: ...')
#
# How it works:
# - Intercepts Edit tool calls
# - Checks filename and directory against each pattern group
# - First match wins — injects its context message
# - Returns nothing for non-matching files
#

# --- Configuration: file pattern groups ---
LABELS=()  FILE_PATTERNS=()  DIR_PATTERNS=()  CONTEXT_MESSAGES=()

LABELS+=("test file")
FILE_PATTERNS+=('(^test_|_test\.|_test_|Test\.|Tests\.|\.test\.|\.spec\.)')
DIR_PATTERNS+=('/(test|tests|__tests__|spec)(/|$)')
CONTEXT_MESSAGES+=('TEST FILE EDITED: Before continuing, verify this was the right call.\n\nCommon mistake: \"fixing\" tests when the code is actually incomplete (e.g., partial backport, missing dependency). If the original test expectation was correct, revert your edit and discuss with the user or fix the code instead.')

# Uncomment or add more:
# LABELS+=("CI/CD config")
# FILE_PATTERNS+=('(Jenkinsfile|\.gitlab-ci\.yml)')
# DIR_PATTERNS+=('/(\.github/workflows|\.circleci)(/|$)')
# CONTEXT_MESSAGES+=('CI/CD CONFIG EDITED: Verify this change will not break the pipeline. Consider: Does this affect all branches? Are secrets still properly referenced?')
#
# LABELS+=("database migration")
# FILE_PATTERNS+=('(\.migration\.|\.migrate\.)')
# DIR_PATTERNS+=('/(migrations|migrate|db/migrate)(/|$)')
# CONTEXT_MESSAGES+=('MIGRATION EDITED: Verify this migration is reversible and safe for production data. Consider: Is there a rollback path? Will this lock tables on large datasets?')
# ------------------------------------------

input=$(cat)

tool_name=$(echo "$input" | jq -r '.tool_name // ""')

# Only care about Edit tool
if [ "$tool_name" != "Edit" ]; then
    exit 0
fi

file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""')
filename=$(basename "$file_path")

# Check each pattern group (first match wins)
for i in "${!LABELS[@]}"; do
    matched=false

    # Check filename pattern
    if [ -n "${FILE_PATTERNS[$i]}" ] && echo "$filename" | grep -qE "${FILE_PATTERNS[$i]}"; then
        matched=true
    fi

    # Check directory pattern
    if [ "$matched" = false ] && [ -n "${DIR_PATTERNS[$i]}" ] && echo "$file_path" | grep -qE "${DIR_PATTERNS[$i]}"; then
        matched=true
    fi

    if [ "$matched" = true ]; then
        # Log for debugging (verify hook fired)
        echo "$(date '+%Y-%m-%d %H:%M:%S') ${LABELS[$i]} guard: $file_path" >> ~/tmp/hook-debug.log

        # Inject context message via additionalContext
        cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "${CONTEXT_MESSAGES[$i]}"
  }
}
EOF
        exit 0
    fi
done

exit 0
