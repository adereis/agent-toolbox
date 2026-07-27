#!/usr/bin/env bash
# Refresh the cached claude.ai usage snapshot that statusline.sh reads.
#
# Why this exists: the JSON Claude Code pipes to a status line carries only the
# five-hour and seven-day windows. Per-model weekly buckets (e.g. Fable) come
# from GET /api/oauth/usage — the same call /usage makes — and Claude Code only
# persists that response (to ~/.claude.json as cachedUsageUtilization) when you
# actually open /usage. That copy is stale most of the time, so we keep our own
# and refresh it on a timer.
#
# Usage:
#   statusline-usage.sh            refresh only if the snapshot is older than TTL
#   statusline-usage.sh --force    refresh unconditionally
#   statusline-usage.sh --status   report snapshot age, buckets, and last error
#   statusline-usage.sh --path     print the snapshot path
#
# Safe to invoke on every status line tick. The TTL gate is an *attempt* marker,
# not a success marker, so a failing fetch backs off exactly like a successful
# one instead of retrying every tick; an mkdir mutex collapses concurrent
# callers across sessions.
#
# Environment:
#   CLAUDE_USAGE_CACHE   snapshot path       (default ~/.claude/statusline-usage.json)
#   CLAUDE_USAGE_TTL     seconds between refreshes (default 300 — matches Claude
#                        Code's own write throttle on the same endpoint)
#   CLAUDE_USAGE_CREDS   credentials path    (default ~/.claude/.credentials.json)
#   CLAUDE_USAGE_API     API base            (default https://api.anthropic.com)
#
# Exit status: 0 when the snapshot was refreshed or the refresh was correctly
# skipped, 1 when a refresh was attempted and failed.

set -u
umask 077

CACHE="${CLAUDE_USAGE_CACHE:-$HOME/.claude/statusline-usage.json}"
TTL="${CLAUDE_USAGE_TTL:-300}"
CREDS="${CLAUDE_USAGE_CREDS:-$HOME/.claude/.credentials.json}"
API="${CLAUDE_USAGE_API:-https://api.anthropic.com}"

ATTEMPT="$CACHE.attempt"
LOCK="$CACHE.lock"
ERRFILE="$CACHE.error"
LOCK_STALE=120

# ── Helpers ──────────────────────────────────────────────────────────

_mtime() {
  case "$(uname -s)" in
    Darwin) stat -f %m "$1" 2>/dev/null ;;
    *)      stat -c %Y "$1" 2>/dev/null ;;
  esac
}

# Seconds since $1 was last written; a very large number when it is absent, so
# callers can compare against a TTL without special-casing "never fetched".
_age() {
  local m
  m=$(_mtime "$1")
  if [ -z "$m" ]; then echo 999999999; else echo $(( $(date +%s) - m )); fi
}

# Record why a refresh failed. The status line surfaces staleness on its own;
# this leaves the reason somewhere `--status` can find it.
fail() {
  printf '%s\n' "$1" > "$ERRFILE"
  [ -t 2 ] && printf 'statusline-usage: %s\n' "$1" >&2
  return 1
}

# ── Flags ────────────────────────────────────────────────────────────

force=0
case "${1:-}" in
  --path) printf '%s\n' "$CACHE"; exit 0 ;;
  --status)
    if [ -r "$CACHE" ]; then
      printf 'snapshot: %s (age %ss)\n' "$CACHE" "$(_age "$CACHE")"
      jq -r '"buckets:  five_hour=\(.utilization.five_hour.utilization // "-")" +
             " seven_day=\(.utilization.seven_day.utilization // "-")" +
             ([ (.utilization.limits // [])[]
                | select(.kind == "weekly_scoped" and .scope.model.display_name != null)
                | " \(.scope.model.display_name)=\(.percent)" ] | join(""))' \
        "$CACHE" 2>/dev/null || echo "buckets:  <unparseable>"
    else
      printf 'snapshot: %s (absent)\n' "$CACHE"
    fi
    [ -r "$ERRFILE" ] && printf 'error:    %s' "$(cat "$ERRFILE")"
    exit 0 ;;
  --force) force=1 ;;
  "") ;;
  *) printf 'usage: %s [--force|--status|--path]\n' "${0##*/}" >&2; exit 2 ;;
esac

# ── TTL gate ─────────────────────────────────────────────────────────

if [ "$force" -eq 0 ] && [ "$(_age "$ATTEMPT")" -lt "$TTL" ]; then
  exit 0
fi

# ── Mutex ────────────────────────────────────────────────────────────
# Several sessions tick independently, so collapse concurrent refreshes. A lock
# left behind by a killed process is broken once it is clearly too old to be a
# live fetch (curl itself is capped at 10s).

mkdir -p "$(dirname "$CACHE")" 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then
  [ "$(_age "$LOCK")" -lt "$LOCK_STALE" ] && exit 0
  rmdir "$LOCK" 2>/dev/null
  mkdir "$LOCK" 2>/dev/null || exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# Re-check the TTL now that we hold the lock. Several ticks can clear the gate
# together before any of them marks an attempt; without this second look, each
# would fetch in turn as the lock frees up. --force means "fetch now" and skips
# it deliberately.
if [ "$force" -eq 0 ] && [ "$(_age "$ATTEMPT")" -lt "$TTL" ]; then
  exit 0
fi

# ── Credentials ──────────────────────────────────────────────────────
# No OAuth credentials means no plan limits to report (API key, Bedrock,
# Vertex): leave the snapshot alone and say nothing. An expired token is
# different — Claude Code refreshes it on its own schedule, so back off and let
# the next tick try rather than spending a request on a certain 401.

[ -r "$CREDS" ] || exit 0
jq -e '.claudeAiOauth.accessToken // empty' "$CREDS" >/dev/null 2>&1 || exit 0

: > "$ATTEMPT"

expires_at=$(jq -r '.claudeAiOauth.expiresAt // 0' "$CREDS" 2>/dev/null)
now_ms=$(( $(date +%s) * 1000 ))
if [ "${expires_at%%.*}" -le "$now_ms" ] 2>/dev/null; then
  fail "OAuth token expired; waiting for Claude Code to refresh it"
  exit 1
fi

# ── Fetch ────────────────────────────────────────────────────────────
# The bearer token goes in via --config on stdin, never argv, so it cannot be
# read out of `ps` by other local users.

tmp="$CACHE.tmp.$$"
trap 'rm -f "$tmp"; rmdir "$LOCK" 2>/dev/null' EXIT

http=$(jq -r '"header = \"Authorization: Bearer \(.claudeAiOauth.accessToken)\""' "$CREDS" 2>/dev/null |
  curl -sS --config - \
    --max-time 10 \
    -H 'anthropic-beta: oauth-2025-04-20' \
    -H 'Content-Type: application/json' \
    -o "$tmp" \
    -w '%{http_code}' \
    "$API/api/oauth/usage" 2>/dev/null)

if [ "$http" != "200" ]; then
  # curl reports "000" when it never got a response at all (offline, DNS, TLS).
  case "$http" in
    000|"") fail "GET /api/oauth/usage: no response (offline or unreachable)" ;;
    *)      fail "GET /api/oauth/usage returned HTTP $http" ;;
  esac
  exit 1
fi

# A 200 with an error envelope is possible (the endpoint reports rate limiting
# in-band), so require the shape we actually consume before overwriting.
if ! jq -e 'type == "object" and (has("five_hour") or has("limits"))' "$tmp" >/dev/null 2>&1; then
  fail "usage response missing expected fields"
  exit 1
fi

# Mirror Claude Code's own cachedUsageUtilization shape so the status line can
# read either source through the same jq path.
if ! jq -c --argjson t "$now_ms" '{fetchedAtMs: $t, utilization: .}' "$tmp" > "$CACHE.new" 2>/dev/null; then
  rm -f "$CACHE.new"
  fail "could not write snapshot"
  exit 1
fi

mv -f "$CACHE.new" "$CACHE"
rm -f "$ERRFILE"
exit 0
