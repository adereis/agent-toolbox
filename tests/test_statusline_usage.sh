#!/bin/bash
# Tests for statusline-usage.sh — the refresher behind the status line's
# per-model weekly quota columns.
#
# The behaviors worth pinning down are the ones that protect the endpoint and
# the user: the TTL gate must back off after *failures* too (or a bad token
# means one request per status line tick), concurrent sessions must collapse
# into a single request, and a failed refresh must never destroy the last good
# snapshot.
#
# A local HTTP server stands in for /api/oauth/usage so the suite stays offline
# and can count requests exactly.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"
SCRIPT="$SCRIPT_DIR/../harnesses/claude-code/settings/statusline-usage.sh"

WORK=$(mktemp -d)
FAKE_PID=""
cleanup() { [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null; rm -rf "$WORK"; }
trap cleanup EXIT

export CLAUDE_USAGE_CACHE="$WORK/snap.json"
export CLAUDE_USAGE_CREDS="$WORK/creds.json"
export CLAUDE_USAGE_API="http://127.0.0.1:1"   # refused unless a test overrides

creds() {  # $1 = ms until the token expires
    printf '{"claudeAiOauth":{"accessToken":"test-token","expiresAt":%s}}' \
        "$(( $(date +%s) * 1000 + $1 ))" > "$CLAUDE_USAGE_CREDS"
}

start_fake_api() {
    python3 - "$WORK" <<'PY' &
import http.server, json, os, signal, sys, threading, time
outdir, count, lock = sys.argv[1], 0, threading.Lock()
BODY = json.dumps({
    "five_hour": {"utilization": 50},
    "seven_day": {"utilization": 40},
    "limits": [{"kind": "weekly_scoped", "percent": 17,
                "scope": {"model": {"display_name": "Fable"}}}],
}).encode()
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global count
        with lock:
            count += 1
            open(os.path.join(outdir, "count"), "w").write(str(count))
        time.sleep(0.2)                      # widen the race window
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
open(os.path.join(outdir, "count"), "w").write("0")
open(os.path.join(outdir, "port"), "w").write(str(srv.server_port))
signal.signal(signal.SIGTERM, lambda *a: os._exit(0))
srv.serve_forever()
PY
    FAKE_PID=$!
    until [ -s "$WORK/port" ]; do :; done
    export CLAUDE_USAGE_API="http://127.0.0.1:$(cat "$WORK/port")"
}

reset() { rm -rf "$WORK"/snap.json*; }

# The fake server counts for its whole lifetime, so measure deltas.
requests_since() { echo "requests=$(( $(cat "$WORK/count") - $1 ))"; }

# ── Flags and gating ─────────────────────────────────────────────────

test_begin "--path reports the configured snapshot location"
run_script "$SCRIPT" --path
assert_output_contains "$WORK/snap.json"

test_begin "does nothing without OAuth credentials"
reset
rm -f "$CLAUDE_USAGE_CREDS"
run_script "$SCRIPT" --force
assert_exit_code 0
[ -e "$CLAUDE_USAGE_CACHE" ] && { echo "  FAIL: wrote a snapshot with no credentials"; }

test_begin "skips while the attempt marker is within the TTL"
reset
creds 3600000
touch "$CLAUDE_USAGE_CACHE.attempt"
CLAUDE_USAGE_TTL=300 run_script "$SCRIPT"
assert_exit_code 0

test_begin "refuses to spend a request on an expired token"
reset
creds -1000
run_script "$SCRIPT" --force
assert_exit_code 1
run_script "$SCRIPT" --status
assert_output_contains "expired"

# ── Failure handling ─────────────────────────────────────────────────

test_begin "records why a failed refresh failed"
reset
creds 3600000
run_script "$SCRIPT" --force
assert_exit_code 1
run_script "$SCRIPT" --status
assert_output_contains "no response"

test_begin "backs off after a failure instead of retrying every tick"
CLAUDE_USAGE_TTL=300 run_script "$SCRIPT"
assert_exit_code 0

# ── Fetching ─────────────────────────────────────────────────────────

if command -v python3 >/dev/null 2>&1; then
    start_fake_api

    test_begin "writes a snapshot carrying the per-model weekly bucket"
    reset
    creds 3600000
    run_script "$SCRIPT" --force
    assert_exit_code 0
    run_script "$SCRIPT" --status
    assert_output_contains "Fable=17"

    test_begin "clears the recorded error once a refresh succeeds"
    run_script "$SCRIPT" --status
    assert_output_lacks "error:"

    test_begin "concurrent refreshers collapse into a single request"
    reset                                    # no attempt marker: all 8 clear the TTL gate
    before=$(cat "$WORK/count")
    pids=()
    for _ in $(seq 8); do "$SCRIPT" & pids+=($!); done
    for p in "${pids[@]}"; do wait "$p"; done
    _stdout=$(requests_since "$before")
    assert_output_contains "requests=1"

    test_begin "a failed refresh leaves the last good snapshot intact"
    cp "$CLAUDE_USAGE_CACHE" "$WORK/good.json"
    rm -f "$CLAUDE_USAGE_CACHE.attempt"
    CLAUDE_USAGE_API="http://127.0.0.1:1" run_script "$SCRIPT" --force
    assert_exit_code 1
    _stdout=$(cmp -s "$CLAUDE_USAGE_CACHE" "$WORK/good.json" && echo preserved)
    assert_output_contains "preserved"

    test_begin "a live lock defers to the refresher already running"
    rm -f "$CLAUDE_USAGE_CACHE.attempt"
    mkdir -p "$CLAUDE_USAGE_CACHE.lock"
    before=$(cat "$WORK/count")
    run_script "$SCRIPT" --force
    assert_exit_code 0
    _stdout=$(requests_since "$before")
    assert_output_contains "requests=0"

    test_begin "a lock left behind by a dead process is broken"
    rm -f "$CLAUDE_USAGE_CACHE.attempt"
    touch -d '5 minutes ago' "$CLAUDE_USAGE_CACHE.lock" 2>/dev/null ||
        touch -t "$(date -v-5M +%Y%m%d%H%M 2>/dev/null)" "$CLAUDE_USAGE_CACHE.lock"
    before=$(cat "$WORK/count")
    run_script "$SCRIPT" --force
    assert_exit_code 0
    _stdout=$(requests_since "$before")
    assert_output_contains "requests=1"
else
    echo "  SKIP: python3 not available — fetch tests not run"
fi

test_summary "statusline-usage"
