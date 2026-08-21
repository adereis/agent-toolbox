#!/usr/bin/env bash
# Claude Code status line — two-row columnar layout
# Row 1: dim column headers  |  Row 2: colored values
#
# Fields (when available):
#   vim mode | workspace | branch | model | effort | session | cost | ↻HH:MM |
#   week | <per-model weekly buckets> | profile | memory
#
# Order groups by what a column is about: the conversation (session, cost),
# then the plan windows that outlive it (↻HH:MM, week, per-model).
#
# The 5-hour quota column has no word for a header: it wears the wall-clock time
# it resets at (↻14:30), so the deadline is visible without spending a column.
#
# Usage columns change color by tier:
#   green (<50%) → yellow (50-79%) → red (≥80%)
#
# Platform support: Linux and macOS (memory detection adapts automatically)
#
# Usage: Configure in ~/.claude/settings.json:
#   "statusLine": {
#     "type": "command",
#     "command": "~/.claude/statusline.sh",
#     "refreshInterval": 10
#   }
#
# The per-model weekly columns need statusline-usage.sh alongside this script;
# see the "Weekly per-model quotas" section below for why.

input=$(cat)

# ── Platform detection (once) ───────────────────────────────────────
_PLATFORM=$(uname -s)

# Bash's ${#s} counts characters under a UTF-8 LC_CTYPE but *bytes* under C or
# POSIX. We emit two non-ASCII glyphs (↻ in the quota header, · in the stale
# marker), so column widths would come out 2 too wide for a status line launched
# with a stripped locale. Probe once instead of assuming the caller's.
_MB=0
_probe='·'; [ "${#_probe}" -eq 1 ] || _MB=1

# ── Helpers ──────────────────────────────────────────────────────────

# Display width of $1, into $_w. In a byte-counting locale the UTF-8
# continuation bytes (0x80–0xBF) are exactly the bytes that do not begin a
# character, so dropping them leaves the character count.
_w=0
_width() {
  local s=$1
  [ "$_MB" -eq 1 ] && s=${s//[$'\200'-$'\277']/}
  _w=${#s}
}

pad() {
  _width "$1"
  local gap=$(( $2 - _w ))
  (( gap < 0 )) && gap=0
  printf '%s%*s' "$1" "$gap" ''
}

# Usage tier: green under half, yellow approaching, red at the point where the
# remaining headroom starts dictating what you can still do.
tier_color() {
  local i=${1%%.*}
  if   [ "${i:-0}" -ge 80 ] 2>/dev/null; then printf '\033[31m'
  elif [ "${i:-0}" -ge 50 ] 2>/dev/null; then printf '\033[33m'
  else                                        printf '\033[32m'
  fi
}

# Effort (reasoning) intensity as brightness on a single hue: dim when barely
# thinking, bold when flat out. Deliberately NOT the green→red tier ramp — that
# vocabulary means "distance to a limit", and effort is intensity, not a limit.
# medium/high/xhigh share the middle rung; only the extremes carry a marker.
effort_color() {
  case "$1" in
    low) printf '\033[2;35m' ;;   # dim magenta
    max) printf '\033[1;35m' ;;   # bold magenta
    *)   printf '\033[35m'   ;;   # medium / high / xhigh
  esac
}

_proc_comm() {
  case "$_PLATFORM" in
    Linux)  cat "/proc/$1/comm" 2>/dev/null ;;
    Darwin) ps -o comm= -p "$1" 2>/dev/null | xargs basename 2>/dev/null ;;
  esac
}

_proc_ppid() {
  case "$_PLATFORM" in
    Linux)  awk '/^PPid:/ {print $2}' "/proc/$1/status" 2>/dev/null ;;
    Darwin) ps -o ppid= -p "$1" 2>/dev/null | tr -d ' ' ;;
  esac
}

# Epoch seconds → local HH:MM. Claude Code rounds the
# anthropic-ratelimit-unified-5h-reset header to whole seconds before putting it
# in the payload, so this is a plain integer, not the ISO string the
# /api/oauth/usage endpoint returns for the same field.
_fmt_clock() {
  case "$_PLATFORM" in
    Darwin) date -r "$1" +%H:%M 2>/dev/null ;;
    *)      date -d "@$1" +%H:%M 2>/dev/null ;;
  esac
}

_proc_rss_kb() {
  case "$_PLATFORM" in
    Linux)  awk '/^VmRSS:/ {print $2}' "/proc/$1/status" 2>/dev/null ;;
    Darwin) ps -o rss= -p "$1" 2>/dev/null | tr -d ' ' ;;
  esac
}

# ── Extract all fields in one jq call ────────────────────────────────
# Each value on its own line — avoids bash IFS tab-stripping bug where
# leading/consecutive tabs are silently dropped, shifting all fields.

{
  read -r vim_mode
  read -r cwd
  read -r model_val
  read -r ctx_pct
  read -r ctx_size
  read -r q
  read -r q_reset
  read -r wk
  read -r cost_val
  read -r effort_lvl
} < <(printf '%s' "$input" | jq -r '
    def val: if . == null then "" else tostring end;
    (.vim.mode | val),
    (.workspace.current_dir | val),
    ((if .model | type == "array" then .model[0].display_name
      elif .model | type == "object" then .model.display_name
      else .model end) | val),
    (.context_window.used_percentage | val),
    (.context_window.context_window_size | val),
    (.rate_limits.five_hour.used_percentage | val),
    (.rate_limits.five_hour.resets_at | val),
    (.rate_limits.seven_day.used_percentage | val),
    (.cost.total_cost_usd | val),
    (.effort.level | val)')

short_cwd="${cwd/#$HOME/\~}"

# Claude Code builds this name as display_name + " (1M context)" whenever the
# model id ends in [1m] — the registry's display_name is always the short form.
# A million tokens is the ordinary case now, so drop the qualifier and keep the
# column narrow. Matching the literal suffix, not any trailing parenthetical, so
# a future qualifier that does carry information still shows up.
model_val="${model_val% (1M context)}"

# The inverse is worth surfacing. context_window_size is the window Claude Code is
# actually enforcing this session: 1e6 on a 1M model, 200000 otherwise — and also
# 200000 for a [1m] model once its 1M credits are spent. So a size below a million
# means "not on 1M", whatever the reason, and the field says so. 1M stays bare as
# the ordinary case; a smaller window wears its size, e.g. Opus 4.8 [200k]. The
# suffix strip above and this flag cooperate: a credit-capped [1m] model loses its
# "(1M context)" name yet still gains [200k], reading as the demotion it is.
ctx_size="${ctx_size%%.*}"
if [ -n "$model_val" ] && [ -n "$ctx_size" ] && [ "$ctx_size" -lt 1000000 ] 2>/dev/null; then
  model_val="$model_val [$(( ctx_size / 1000 ))k]"
fi

# ── Git branch + dirty state ────────────────────────────────────────

git_val=""
if [ -n "$cwd" ] && git -C "$cwd" rev-parse --git-dir >/dev/null 2>&1; then
  branch=$(git -C "$cwd" --no-optional-locks symbolic-ref --short HEAD 2>/dev/null ||
           git -C "$cwd" --no-optional-locks rev-parse --short HEAD 2>/dev/null || true)
  d="" s="" u=""
  git -C "$cwd" --no-optional-locks diff --quiet 2>/dev/null || d='*'
  git -C "$cwd" --no-optional-locks diff --cached --quiet 2>/dev/null || s='+'
  git -C "$cwd" --no-optional-locks ls-files --others --exclude-standard 2>/dev/null \
    | head -1 | grep -q . && u='?' || true
  git_val="${branch}${d}${s}${u}"
fi

# ── Profile — backend, or the exact subscription plan ────────────────
#
# The status line payload carries no account information: it stops at model,
# context, cost, effort and rate limits. The plan lives in the OAuth credentials
# Claude Code writes, split across two fields — subscriptionType is the family
# (pro / max / team / enterprise) and rateLimitTier carries the Max multiplier.
# Claude Code decides "is this Max 20x" from exactly that pair, so we read the
# same two, and only those two: the access token sits beside them in the file
# and never enters a variable, a command line, or the output.
#
# Its own jq call rather than a field on one of the calls above — sharing an
# invocation would mean feeding the credentials file to a filter that also
# handles data we print, for no saved work.
#
# ~/.claude.json's oauthAccount.organizationType looks like it would answer this
# in one field, but it reads "claude_pro" on a Max account: it names the org's
# product, not the seat's plan.

CREDS_FILE="${CLAUDE_USAGE_CREDS:-$HOME/.claude/.credentials.json}"

profile_val="" profile_clr="\033[36m" sub_type="" rl_tier=""
if [ -n "${CLAUDE_CODE_USE_VERTEX:-}" ] && [ "${CLAUDE_CODE_USE_VERTEX}" != '0' ]; then
  profile_val="vertex"  profile_clr="\033[33m"
else
  if [ -r "$CREDS_FILE" ]; then
    { read -r sub_type; read -r rl_tier; } < <(jq -r '
        def val: if . == null then "" else tostring end;
        (.claudeAiOauth.subscriptionType | val),
        (.claudeAiOauth.rateLimitTier | val)' "$CREDS_FILE" 2>/dev/null)
  fi
  case "$sub_type" in
    # Match the multiplier by suffix, not the whole tier string: the prefix is
    # Anthropic's internal plan id (default_claude_max_20x today) and only the
    # ×N part is what the column is reporting.
    max) case "$rl_tier" in
           *_20x) profile_val="max 20x" ;;
           *_5x)  profile_val="max 5x"  ;;
           *)     profile_val="max"     ;;
         esac ;;
    # pro / team / enterprise need no decoding — the API's own word is the name
    # a user would use for the plan. An unrecognised future value passes through
    # intact rather than being flattened into a wrong guess.
    "") ;;
    *)  profile_val="$sub_type" ;;
  esac
  # No OAuth credentials at all means a key-based backend rather than a plan.
  # Naming it keeps the column's promise — "which account is this session on" —
  # instead of leaving a gap that reads like a bug.
  if [ -z "$profile_val" ] && [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    profile_val="api"  profile_clr="\033[2m"
  fi
fi

# ── Session — context window fill, colored by usage tier ─────────────
#
# Headed "session" rather than "context": it answers "how full is this
# conversation", which is the question you actually ask it. Note that the API
# uses "session" for the 5-hour limit (kind:"session") — different thing.

ctx_val="" ctx_clr=""
if [ -n "$ctx_pct" ]; then
  ctx_clr=$(tier_color "$ctx_pct")
  ctx_val=$(printf '%.0f%%' "$ctx_pct")
fi

# ── Effort — reasoning effort level, when the model exposes one ───────
#
# .effort.level is absent (not null) on models without an effort parameter, so
# `val` yields "" and the column drops out on its own — the same idiom the vim
# and git columns use. Brightness ramp, not the tier ramp — see effort_color.

effort_val="" effort_clr=""
if [ -n "$effort_lvl" ]; then
  effort_val="$effort_lvl"
  effort_clr=$(effort_color "$effort_lvl")
fi

# ── Quota — 5-hour and 7-day rate limits (subscription only) ─────────
#
# Both ride on the anthropic-ratelimit-unified-* response headers, so Claude
# Code refreshes them on every API call: these are live to within one tick.
#
# The 5-hour header doubles as its own reset clock. resets_at comes from the
# same headers, so it costs nothing extra; when it is missing (older payload,
# no rate limit info yet) the column falls back to the plain word.

quota_val="" quota_clr="" quota_hdr="quota"
if [ -n "$q" ]; then
  quota_clr=$(tier_color "$q")
  quota_val=$(printf '%.0f%%' "$q")
  if [ -n "$q_reset" ]; then
    clock=$(_fmt_clock "${q_reset%%.*}")
    [ -n "$clock" ] && quota_hdr="↻$clock"
  fi
fi

week_val="" week_clr=""
if [ -n "$wk" ]; then
  week_clr=$(tier_color "$wk")
  week_val=$(printf '%.0f%%' "$wk")
fi

# ── Weekly per-model quotas (e.g. Fable) ─────────────────────────────
#
# These are not in the status line payload — it carries only five_hour and
# seven_day. /usage gets them from GET /api/oauth/usage, and Claude Code only
# persists that response (~/.claude.json, cachedUsageUtilization) when you open
# the /usage dialog, so its copy is usually hours old. statusline-usage.sh keeps
# a snapshot refreshed on a timer; we read whichever source is newer and kick
# off a detached refresh when the winner is aging. The status line itself never
# touches the network, so it cannot stall on a slow request.
#
# When a refresh is failing (expired token, offline, rate limited) the value
# goes dim and picks up an age suffix (17% ·2h) rather than quietly presenting
# old data as current.

USAGE_CACHE="${CLAUDE_USAGE_CACHE:-$HOME/.claude/statusline-usage.json}"
USAGE_FALLBACK="${CLAUDE_USAGE_FALLBACK:-$HOME/.claude.json}"
USAGE_REFRESH="${CLAUDE_USAGE_REFRESH:-$(dirname "$0")/statusline-usage.sh}"
USAGE_TTL="${CLAUDE_USAGE_TTL:-300}"
USAGE_STALE_AFTER="${CLAUDE_USAGE_STALE_AFTER:-900}"

snap_files=()
[ -r "$USAGE_CACHE" ]    && snap_files+=("$USAGE_CACHE")
[ -r "$USAGE_FALLBACK" ] && snap_files+=("$USAGE_FALLBACK")

snap_ms="" scoped_pairs=""
if [ "${#snap_files[@]}" -gt 0 ]; then
  # Our snapshot is {fetchedAtMs, utilization}; Claude Code nests the same shape
  # under .cachedUsageUtilization — so one expression reads both.
  { read -r snap_ms; read -r scoped_pairs; } < <(jq -rs '
      [ .[]
        | (.cachedUsageUtilization // .)
        | select(type == "object" and (.fetchedAtMs | type) == "number") ]
      | (max_by(.fetchedAtMs) // {})
      | ((.fetchedAtMs // "") | tostring),
        ([ (.utilization.limits // [])[]
           | select(.kind == "weekly_scoped" and .percent != null)
           | select(.scope.model.display_name != null)
           | "\(.scope.model.display_name)=\(.percent)" ] | join(","))' \
      "${snap_files[@]}" 2>/dev/null)
fi

snap_age=""
[ -n "$snap_ms" ] && snap_age=$(( $(date +%s) - ${snap_ms%%.*} / 1000 ))

if [ -x "$USAGE_REFRESH" ] && { [ -z "$snap_age" ] || [ "$snap_age" -ge "$USAGE_TTL" ]; }; then
  # Detached, all three descriptors closed — the status line must reach EOF on
  # stdout immediately regardless of how long the refresh takes.
  ( "$USAGE_REFRESH" >/dev/null 2>&1 </dev/null & )
fi

scoped_hdrs=() scoped_vals=() scoped_clrs=()
if [ -n "$scoped_pairs" ]; then
  age_sfx=""
  if [ -n "$snap_age" ] && [ "$snap_age" -ge "$USAGE_STALE_AFTER" ]; then
    if [ "$snap_age" -ge 3600 ]; then
      age_sfx=" ·$(( snap_age / 3600 ))h"
    else
      age_sfx=" ·$(( snap_age / 60 ))m"
    fi
  fi
  IFS=',' read -ra scoped_list <<< "$scoped_pairs"
  for pair in "${scoped_list[@]}"; do
    name=${pair%%=*} pct=${pair##*=}
    if [ -n "$age_sfx" ]; then clr="\033[2m"; else clr=$(tier_color "$pct"); fi
    scoped_hdrs+=("$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')")
    scoped_vals+=("$(printf '%.0f%%%s' "$pct" "$age_sfx")")
    scoped_clrs+=("$clr")
  done
fi

# ── Cost — estimated session cost (all backends) ─────────────────────
#
# Cents are the useful resolution here; the extra two digits only ever changed
# how wide the column was. Sub-cent sessions therefore read $0.00 until they
# cross a cent.

cost_disp=""
[ -n "$cost_val" ] && cost_disp=$(printf '$%.2f' "$cost_val")

# ── Process memory (walk up to find Claude Code's node process) ──────

mem_val=""
cc_pid=$PPID
comm=$(_proc_comm "$cc_pid")
case "$comm" in
  node|claude) ;;
  *) cc_pid=$(_proc_ppid "$cc_pid") ;;
esac
if [ -n "$cc_pid" ]; then
  vmrss=$(_proc_rss_kb "$cc_pid")
  if [ -n "$vmrss" ] && [ "$vmrss" -gt 0 ] 2>/dev/null; then
    mem_val=$(awk "BEGIN {printf \"%.1f MB\", $vmrss / 1024}")
  fi
fi

# ── Build two-row output ────────────────────────────────────────────

DIM="\033[2m"  RST="\033[0m"  BOLD="\033[1m"
SEP="   "
hdr="" val=""

col() {
  local h="$1" v="$2" c="$3"
  _width "$v"; local w=$_w
  _width "$h"; (( _w > w )) && w=$_w
  hdr+="${DIM}$(pad "$h" "$w")${RST}${SEP}"
  val+="${c}$(pad "$v" "$w")${RST}${SEP}"
}

[ -n "$vim_mode" ] && col "mode" "[${vim_mode:0:3}]" "\033[1;35m"
col "workspace" "$short_cwd" "${BOLD}\033[34m"
[ -n "$git_val" ]   && col "branch"     "$git_val"     "\033[33m"
[ -n "$model_val" ] && col "model"      "$model_val"   "\033[32m"
[ -n "$effort_val" ] && col "effort"    "$effort_val"  "$effort_clr"
[ -n "$ctx_val" ]   && col "session"    "$ctx_val"     "$ctx_clr"
[ -n "$cost_disp" ] && col "cost"       "$cost_disp"   "\033[36m"
[ -n "$quota_val" ] && col "$quota_hdr" "$quota_val"   "$quota_clr"
[ -n "$week_val" ]  && col "week"       "$week_val"    "$week_clr"
for i in "${!scoped_vals[@]}"; do
                       col "${scoped_hdrs[$i]}" "${scoped_vals[$i]}" "${scoped_clrs[$i]}"
done
# profile last — a near-fixed plan marker earns less width than the live
# columns, so it sits out of the way beside memory rather than up front. It
# drops out when nothing identifies the backend, like every other column.
[ -n "$profile_val" ] && col "profile" "$profile_val" "$profile_clr"
[ -n "$mem_val" ]   && col "memory"     "$mem_val"     "\033[36m"

printf '%b\n%b' "$hdr" "$val"
