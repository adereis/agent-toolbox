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

# Same reason, for the profile column: it reads the real OAuth credentials to
# name the plan, so point it at a fixture and clear the two variables that
# would otherwise let the developer's own backend decide the answer.
export CLAUDE_USAGE_CREDS="$FIXTURES/absent-creds.json"
unset CLAUDE_CODE_USE_VERTEX ANTHROPIC_API_KEY

# OAuth credentials in the shape Claude Code writes them. The token is here
# because the real file has one and the column must ignore it, not because
# anything reads it.
creds() {
    printf '{"claudeAiOauth":{"accessToken":"sk-ant-oat-EXAMPLE-NOT-A-REAL-TOKEN","subscriptionType":%s,"rateLimitTier":%s}}' \
        "$1" "$2" > "$FIXTURES/creds.json"
    export CLAUDE_USAGE_CREDS="$FIXTURES/creds.json"
}

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

test_begin "shows context window fill under a 'session' header"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{"used_percentage":42.4},"cost":{}}'
assert_output_contains "session"
assert_output_contains "42%"
assert_output_lacks "context"

test_begin "percentages carry no 'used' suffix"
assert_output_lacks "used"

test_begin "shows quota from 5-hour rate limit (subscription)"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"rate_limits":{"five_hour":{"used_percentage":73}},"cost":{}}'
assert_output_contains "73%"

test_begin "shows cost in its own column, rounded to cents"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"cost":{"total_cost_usd":1.2345}}'
assert_output_contains '$1.23'
assert_output_lacks '1.2345'

test_begin "rounds cost up at the half cent"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"cost":{"total_cost_usd":2.9719}}'
assert_output_contains '$2.97'

# Claude Code appends " (1M context)" to display_name whenever the model id ends
# in [1m]. It is a fixed suffix, not part of the name, so the column drops it.
test_begin "drops the (1M context) qualifier from the model name"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"model":{"display_name":"Opus 5 (1M context)"},"context_window":{},"cost":{}}'
assert_output_contains "Opus 5"
assert_output_lacks "1M context"

test_begin "leaves a model name without the qualifier alone"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"model":{"display_name":"Haiku 4.5"},"context_window":{},"cost":{}}'
assert_output_contains "Haiku 4.5"

# context_window_size is the window Claude Code is actually enforcing. 1M is the
# ordinary case and stays bare; anything smaller wears its size, so a 200k session
# is visible at a glance.
test_begin "flags a sub-1M window with its size"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"model":{"display_name":"Opus 4.8"},"context_window":{"context_window_size":200000},"cost":{}}'
assert_output_contains "Opus 4.8 \[200k\]"

test_begin "leaves a 1M window unmarked"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"model":{"display_name":"Opus 4.8 (1M context)"},"context_window":{"context_window_size":1000000},"cost":{}}'
assert_output_contains "Opus 4.8"
assert_output_lacks "200k"
assert_output_lacks "1M context"

# A [1m] model capped to 200k once its 1M credits are spent: the name loses its
# "(1M context)" suffix and still gains [200k], so the demotion reads as what it is.
test_begin "flags a credit-capped 1M model as 200k"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"model":{"display_name":"Opus 4.8 (1M context)"},"context_window":{"context_window_size":200000},"cost":{}}'
assert_output_contains "Opus 4.8 \[200k\]"
assert_output_lacks "1M context"

test_begin "shows cost alongside quota on subscription"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"rate_limits":{"five_hour":{"used_percentage":73}},"cost":{"total_cost_usd":1.2345}}'
assert_output_contains '$1.23'

test_begin "abbreviates vim mode to three letters"
run_hook "$SCRIPT" '{"vim":{"mode":"NORMAL"},"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"cost":{}}'
assert_output_contains '\[NOR\]'

test_begin "shows git branch in a git repo"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$SCRIPT_DIR/.."'"},"context_window":{},"cost":{}}'
assert_output_contains "main"

# ── 5-hour reset clock ───────────────────────────────────────────────
# resets_at arrives in the same payload as the percentage — epoch seconds, off
# the anthropic-ratelimit-unified-5h-reset response header — so the column can
# label itself with the time it resets instead of spending a header on "quota".

RESET_AT=$(( $(date +%s) + 3600 ))
RESET_HHMM=$(date -d "@$RESET_AT" +%H:%M 2>/dev/null || date -r "$RESET_AT" +%H:%M)
CLOCK_IN='{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{"used_percentage":23},"rate_limits":{"five_hour":{"used_percentage":73,"resets_at":'"$RESET_AT"'}},"cost":{}}'

test_begin "heads the quota column with its local reset time"
run_hook "$SCRIPT" "$CLOCK_IN"
assert_output_contains "↻$RESET_HHMM"
assert_output_lacks "quota"

test_begin "falls back to the word 'quota' when resets_at is absent"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"rate_limits":{"five_hour":{"used_percentage":73}},"cost":{}}'
assert_output_contains "quota"

# ${#s} counts bytes, not characters, when LC_CTYPE is C — which would pad the
# ↻ header two columns too wide. The script probes for this rather than trusting
# the caller's locale, so both runs must lay out identically.
test_begin "column widths do not depend on the caller's locale"
strip_mem() { printf '%s' "$1" | sed 's/[0-9.]* MB/MEM/'; }
run_hook "$SCRIPT" "$CLOCK_IN"
utf8_layout=$(strip_mem "$_stdout")
export LC_ALL=C
run_hook "$SCRIPT" "$CLOCK_IN"
unset LC_ALL
if [ "$utf8_layout" = "$(strip_mem "$_stdout")" ]; then
    (( _pass++ ))
else
    (( _fail++ ))
    echo "  FAIL: $_test_name"
    echo "    UTF-8: $utf8_layout"
    echo "    C:     $(strip_mem "$_stdout")"
fi

# ── Weekly quotas ────────────────────────────────────────────────────
# `week` comes from the status line payload; per-model buckets come from the
# usage snapshot, so they are tested against fixtures rather than live data.

WEEK_IN='{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"rate_limits":{"five_hour":{"used_percentage":73},"seven_day":{"used_percentage":40}},"cost":{}}'

test_begin "shows week column from the 7-day rate limit"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_contains "week"
assert_output_contains "40%"

test_begin "omits per-model column when no usage snapshot exists"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_lacks "fable"

test_begin "shows per-model weekly column from a fresh snapshot"
snapshot 60 "$FIXTURES/fresh.json"
CLAUDE_USAGE_CACHE="$FIXTURES/fresh.json"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_contains "fable"
assert_output_contains "17%"

test_begin "does not mark a fresh snapshot as stale"
assert_output_lacks '17% ·'

test_begin "marks a stale snapshot with its age"
snapshot 7200 "$FIXTURES/stale.json"
CLAUDE_USAGE_CACHE="$FIXTURES/stale.json"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_contains '17% ·2h'

test_begin "reports staleness in minutes under an hour"
snapshot 1200 "$FIXTURES/stale20.json"
CLAUDE_USAGE_CACHE="$FIXTURES/stale20.json"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_contains '17% ·20m'

test_begin "falls back to Claude Code's own cached usage data"
CLAUDE_USAGE_CACHE="$FIXTURES/absent.json"
snapshot 60 "$FIXTURES/claude.json" wrap
CLAUDE_USAGE_FALLBACK="$FIXTURES/claude.json"
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_contains "fable"
assert_output_contains "17%"

test_begin "prefers the newer of the two snapshot sources"
snapshot 7200 "$FIXTURES/old.json"
CLAUDE_USAGE_CACHE="$FIXTURES/old.json"       # ours is 2h old, Claude Code's is 1m
run_hook "$SCRIPT" "$WEEK_IN"
assert_output_lacks '·2h'

# ── Effort (reasoning) level ─────────────────────────────────────────
# .effort.level rides in the status line payload on models that expose an
# effort parameter; it is absent (not null) otherwise, so the column vanishes
# rather than showing a placeholder.

test_begin "shows the effort level in its own column"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"cost":{},"effort":{"level":"max"}}'
assert_output_contains "effort"
assert_output_contains "max"

test_begin "omits the effort column when the model exposes no effort parameter"
run_hook "$SCRIPT" '{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"cost":{}}'
assert_output_lacks "effort"

# ── Profile (plan / backend) ─────────────────────────────────────────
# subscriptionType names the family and rateLimitTier the Max multiplier; the
# column is the two read together, because neither alone identifies the plan.

PROFILE_IN='{"workspace":{"current_dir":"'"$PWD"'"},"context_window":{},"cost":{}}'

test_begin "names the Max multiplier, not just the plan family"
creds '"max"' '"default_claude_max_5x"'
run_hook "$SCRIPT" "$PROFILE_IN"
assert_output_contains "max 5x"

test_begin "distinguishes Max 20x from Max 5x"
creds '"max"' '"default_claude_max_20x"'
run_hook "$SCRIPT" "$PROFILE_IN"
assert_output_contains "max 20x"

test_begin "falls back to the bare family when the tier is missing"
creds '"max"' 'null'
run_hook "$SCRIPT" "$PROFILE_IN"
assert_output_contains "max"
assert_output_lacks "5x"

test_begin "shows pro without a multiplier"
creds '"pro"' '"default_claude_zero"'
run_hook "$SCRIPT" "$PROFILE_IN"
assert_output_contains "pro"
assert_output_lacks "zero"

test_begin "passes an unrecognised plan family through unchanged"
creds '"team"' 'null'
run_hook "$SCRIPT" "$PROFILE_IN"
assert_output_contains "team"

test_begin "never leaks the access token sitting beside the plan fields"
creds '"max"' '"default_claude_max_5x"'
run_hook "$SCRIPT" "$PROFILE_IN"
assert_output_lacks "sk-ant-oat"

test_begin "Vertex overrides the plan even with credentials present"
creds '"max"' '"default_claude_max_5x"'
CLAUDE_CODE_USE_VERTEX=1 run_hook "$SCRIPT" "$PROFILE_IN"
assert_output_contains "vertex"
assert_output_lacks "max 5x"
unset CLAUDE_CODE_USE_VERTEX

test_begin "reports a key-based backend as api when there are no credentials"
export CLAUDE_USAGE_CREDS="$FIXTURES/absent-creds.json"
ANTHROPIC_API_KEY=sk-ant-example run_hook "$SCRIPT" "$PROFILE_IN"
assert_output_contains "api"

test_begin "drops the profile column when nothing identifies the backend"
run_hook "$SCRIPT" "$PROFILE_IN"
assert_output_lacks "profile"

test_summary "statusline"
