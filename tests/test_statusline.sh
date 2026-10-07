#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"
SCRIPT="$SCRIPT_DIR/../harnesses/claude-code/settings/statusline.sh"

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

# ── Agent panel rows (--subagent) ────────────────────────────────────
# subagentStatusLine sends every agent row in one payload (base hook fields,
# columns, tasks) and reads back one JSON line per row, {"id", "content"}.
# The fixtures follow the payload Claude Code 2.1.293 builds.

# Run the subagent mode. $_json keeps the reply Claude Code reads; $_stdout
# holds the same rows as "<id> <content>" with colors stripped, so the shared
# assertions read them as text.
run_subagent() {
    _json=$(printf '%s' "$1" | "$SCRIPT" --subagent 2>"$FIXTURES/stderr")
    _exit_code=$?
    _stderr=$(cat "$FIXTURES/stderr")
    _stdout=$(printf '%s' "$_json" | jq -r '"\(.id) \(.content)"' 2>/dev/null \
        | sed 's/\x1b\[[0-9;]*m//g')
}

# The column the given text starts at in the row for task $1.
col_of() {
    local line
    line=$(printf '%s\n' "$_stdout" | grep "^$1 ")
    line=${line%%"$2"*}
    echo "${#line}"
}

assert_true() {
    if "$@" > /dev/null; then
        (( _pass++ ))
    else
        (( _fail++ ))
        echo "  FAIL: $_test_name"
        echo "    reply: $_json"
    fi
}

NOW_MS=$(( $(date +%s) * 1000 ))
T_SCOUT='{"id":"t1","name":"scout","agentType":"Explore","type":"local_agent","status":"running","label":"Map the loader","startTime":'$(( NOW_MS - 83000 ))',"model":"claude-haiku-5-5","effort":"low","contextWindowSize":1000000,"tokenCount":45231,"tokenSamples":[40000,45231]}'
T_PLAIN='{"id":"t2","agentType":"general-purpose","type":"local_agent","status":"running","description":"Write tests","startTime":'$(( NOW_MS - 3725000 ))',"model":"claude-opus-5-5[1m]","effort":"max","contextWindowSize":200000,"tokenCount":170000}'
T_DONE='{"id":"t3","agentType":"a-much-longer-finished-agent","type":"local_agent","status":"completed","description":"Done","startTime":'$(( NOW_MS - 9000 ))',"model":"claude-sonnet-4-5-20250929","effort":8000,"contextWindowSize":1000000,"tokenCount":1234567}'
SUB_IN='{"session_id":"s","cwd":"/home/testuser","columns":120,"tasks":['"$T_SCOUT,$T_PLAIN,$T_DONE"']}'

test_begin "answers every agent row with one JSON line keyed by its id"
run_subagent "$SUB_IN"
assert_exit_code 0
assert_true jq -e -n --argjson r "$(printf '%s' "$_json" | jq -s .)" \
    '$r | length == 3 and map(.id) == ["t1","t2","t3"] and all(.content | type == "string")'

test_begin "names an unnamed agent by its type, as the default row does"
assert_output_contains "^t2 general-purpose "

test_begin "shows the agent type beside a name that differs from it"
assert_output_contains "^t1 scout  *Explore "

test_begin "rebuilds the model display name from the model id"
assert_output_contains "Haiku 5.5"
assert_output_contains "Opus 5.5"
assert_output_contains "Sonnet 4.5"
assert_output_lacks "claude-"

test_begin "flags an agent window below 1M with its size"
assert_output_contains "Opus 5.5 \[200k\]"
assert_output_lacks "\[1m\]"

test_begin "shows the effort level, and a numeric effort as a thinking budget"
assert_output_contains "Haiku 5.5  *low "
assert_output_contains " max "
assert_output_contains "budget 8k"

test_begin "shows the agent's context fill and token count"
assert_output_contains " 5%  *45.2k "
assert_output_contains " 85%  *170k "
assert_output_contains " 1.2M "

test_begin "colors the agent's context fill by usage tier"
assert_true grep -q $'\e\[31m85%' <<< "$(printf '%s' "$_json" | jq -r .content)"

test_begin "shows elapsed time only while the agent runs"
assert_output_contains " 1m2[34]s "
assert_output_contains " 1h02m "
assert_true bash -c '! grep "^t3 " <<< "$1" | grep -q "[0-9]s "' _ "$_stdout"

test_begin "falls back to the description when there is no label"
assert_output_contains "Write tests$"

test_begin "aligns each cell across the live rows"
assert_true [ "$(col_of t1 'Haiku')" -eq "$(col_of t2 'Opus')" ]

test_begin "a finished agent does not widen the live columns"
with_done=$(col_of t1 'Haiku')
run_subagent '{"columns":120,"tasks":['"$T_SCOUT,$T_PLAIN"']}'
assert_true [ "$with_done" -eq "$(col_of t1 'Haiku')" ]

test_begin "passes an unrecognised model id through unchanged"
run_subagent '{"columns":120,"tasks":[{"id":"x","status":"running","model":"us.anthropic.custom-v1:0"}]}'
assert_output_contains "^x agent  *us.anthropic.custom-v1:0"

test_begin "strips control characters from free text"
run_subagent '{"columns":120,"tasks":[{"id":"x","agentType":"Explore","status":"running","label":"one\ntwo\tthree \u001b[31mred"}]}'
assert_output_contains "one two three  *\[31mred"
assert_true bash -c '! grep -q $'"'"'\e\\[31mred'"'"' <<< "$1"' _ "$(printf '%s' "$_json" | jq -r .content)"

test_begin "prints nothing when there are no agent rows"
run_subagent '{"columns":120,"tasks":[]}'
assert_exit_code 0
assert_true [ -z "$_json" ]

test_begin "fails loudly on a payload it cannot parse"
run_subagent 'not json'
assert_exit_code 1
assert_stderr_contains "cannot read the subagentStatusLine payload"

test_begin "rejects an unknown argument with usage"
run_script "$SCRIPT" --bogus < /dev/null
assert_exit_code 2
assert_stderr_contains "usage: statusline.sh \[--subagent\]"

test_begin "prints usage on --help"
run_script "$SCRIPT" --help < /dev/null
assert_exit_code 0
assert_output_contains "subagentStatusLine"

# Same probe as the main line: a non-ASCII name must pad to its characters,
# not its bytes, whatever locale Claude Code launched the command under.
test_begin "agent row widths do not depend on the caller's locale"
ACCENT_IN='{"columns":120,"tasks":[{"id":"a","name":"café","agentType":"Explore","status":"running","model":"claude-haiku-5-5"},{"id":"b","agentType":"general-purpose","status":"running","model":"claude-opus-5-5"}]}'
run_subagent "$ACCENT_IN"
utf8_rows=$_stdout
export LC_ALL=C
run_subagent "$ACCENT_IN"
unset LC_ALL
assert_true [ "$utf8_rows" = "$_stdout" ]
assert_true [ "$(col_of a 'Haiku')" -eq "$(col_of b 'Opus')" ]

test_summary "statusline"
