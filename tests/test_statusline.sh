#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"
SCRIPT="$SCRIPT_DIR/../settings/statusline.sh"

# Keep the suite hermetic. Without these the status line would read the real
# usage snapshot and spawn the real refresher, i.e. hit the network from a test.
FIXTURES=$(mktemp -d)
trap 'rm -rf "$FIXTURES"' EXIT
export CLAUDE_USAGE_CACHE="$FIXTURES/absent.json"
export CLAUDE_USAGE_FALLBACK="$FIXTURES/absent.json"
export CLAUDE_USAGE_REFRESH="$FIXTURES/no-such-refresher"

# Write a usage snapshot aged $1 seconds, in the shape statusline-usage.sh
# produces. $3 wraps it as Claude Code's ~/.claude.json when set.
snapshot() {
    local age=$1 path=$2 wrap=${3:-}
    local body
    body=$(printf '{"fetchedAtMs":%s,"utilization":{"limits":[{"kind":"weekly_all","percent":40,"scope":null},{"kind":"weekly_scoped","percent":17,"scope":{"model":{"display_name":"Fable"}}}]}}' \
        "$(( ($(date +%s) - age) * 1000 ))")
    if [ -n "$wrap" ]; then
        printf '{"cachedUsageUtilization":%s}' "$body" > "$path"
    else
        printf '%s' "$body" > "$path"
    fi
}

test_begin "outputs current directory from input"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"/home/testuser/project"},"context_window":{},"cost":{}}'
assert_output_contains "/home/testuser/project"

test_begin "abbreviates home directory to ~"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$HOME"'/myproj"},"context_window":{},"cost":{}}'
assert_output_contains "~/myproj"

test_begin "shows context percentage, formatted to whole percent"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{"used_percentage":42.4},"cost":{}}'
assert_output_contains "42% used"

test_begin "shows quota from 5-hour rate limit (subscription)"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"rate_limits":{"five_hour":{"used_percentage":73}},"cost":{}}'
assert_output_contains "73% used"

test_begin "shows cost in its own column"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"cost":{"total_cost_usd":1.2345}}'
assert_output_contains '$1.2345'

test_begin "shows cost alongside quota on subscription"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"rate_limits":{"five_hour":{"used_percentage":73}},"cost":{"total_cost_usd":1.2345}}'
assert_output_contains '$1.2345'

test_begin "abbreviates vim mode to three letters"
run_hook "$SCRIPT" '{"vim":{"mode":"NORMAL"},"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"cost":{}}'
assert_output_contains '\[NOR\]'

test_begin "shows git branch in a git repo"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$SCRIPT_DIR/.."'"},"context_window":{},"cost":{}}'
assert_output_contains "main"

# ── Weekly quotas ────────────────────────────────────────────────────
# `week` comes from the status line payload; per-model buckets come from the
# usage snapshot, so they are tested against fixtures rather than live data.

WEEK_IN='{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"rate_limits":{"five_hour":{"used_percentage":73},"seven_day":{"used_percentage":40}},"cost":{}}'

test_begin "shows week column from the 7-day rate limit"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_contains "week"
assert_output_contains "40% used"

test_begin "omits per-model column when no usage snapshot exists"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_lacks "fable"

test_begin "shows per-model weekly column from a fresh snapshot"
snapshot 60 "$FIXTURES/fresh.json"
CLAUDE_USAGE_CACHE="$FIXTURES/fresh.json"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_contains "fable"
assert_output_contains "17% used"

test_begin "does not mark a fresh snapshot as stale"
assert_output_lacks '17% used ·'

test_begin "marks a stale snapshot with its age"
snapshot 7200 "$FIXTURES/stale.json"
CLAUDE_USAGE_CACHE="$FIXTURES/stale.json"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_contains '17% used ·2h'

test_begin "reports staleness in minutes under an hour"
snapshot 1200 "$FIXTURES/stale20.json"
CLAUDE_USAGE_CACHE="$FIXTURES/stale20.json"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_contains '17% used ·20m'

test_begin "falls back to Claude Code's own cached usage data"
CLAUDE_USAGE_CACHE="$FIXTURES/absent.json"
snapshot 60 "$FIXTURES/claude.json" wrap
CLAUDE_USAGE_FALLBACK="$FIXTURES/claude.json"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_contains "fable"
assert_output_contains "17% used"

test_begin "prefers the newer of the two snapshot sources"
snapshot 7200 "$FIXTURES/old.json"
CLAUDE_USAGE_CACHE="$FIXTURES/old.json"       # ours is 2h old, Claude Code's is 1m
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_lacks '·2h'

test_summary "statusline"
