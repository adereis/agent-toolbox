#!/usr/bin/env bash
# Claude Code status line — two-row columnar layout
# Row 1: dim column headers  |  Row 2: colored values
#
# Fields (when available):
#   vim mode | workspace | branch | profile | model | context | quota | cost |
#   week | <per-model weekly buckets> | memory
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

# ── Helpers ──────────────────────────────────────────────────────────

pad() {
  local gap=$(( $2 - ${#1} ))
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
  read -r q
  read -r wk
  read -r cost_val
} < <(printf '%s' "$input" | jq -r '
    def val: if . == null then "" else tostring end;
    (.vim.mode | val),
    (.workspace.current_dir | val),
    ((if .model | type == "array" then .model[0].display_name
      elif .model | type == "object" then .model.display_name
      else .model end) | val),
    (.context_window.used_percentage | val),
    (.rate_limits.five_hour.used_percentage | val),
    (.rate_limits.seven_day.used_percentage | val),
    (.cost.total_cost_usd | val)')

short_cwd="${cwd/#$HOME/\~}"

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

# ── Profile (vertex / subscription) ─────────────────────────────────

if [ -n "${CLAUDE_CODE_USE_VERTEX:-}" ] && [ "${CLAUDE_CODE_USE_VERTEX}" != '0' ]; then
  profile_val="vertex"  profile_clr="\033[33m"
else
  profile_val="pro"     profile_clr="\033[36m"
fi

# ── Context — color by usage tier ────────────────────────────────────

ctx_val="" ctx_clr=""
if [ -n "$ctx_pct" ]; then
  ctx_clr=$(tier_color "$ctx_pct")
  ctx_val=$(printf '%.0f%% used' "$ctx_pct")
fi

# ── Quota — 5-hour and 7-day rate limits (subscription only) ─────────
#
# Both ride on the anthropic-ratelimit-unified-* response headers, so Claude
# Code refreshes them on every API call: these are live to within one tick.

quota_val="" quota_clr=""
if [ -n "$q" ]; then
  quota_clr=$(tier_color "$q")
  quota_val=$(printf '%.0f%% used' "$q")
fi

week_val="" week_clr=""
if [ -n "$wk" ]; then
  week_clr=$(tier_color "$wk")
  week_val=$(printf '%.0f%% used' "$wk")
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
# goes dim and picks up an age suffix rather than quietly presenting old data as
# current.

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
    scoped_vals+=("$(printf '%.0f%% used%s' "$pct" "$age_sfx")")
    scoped_clrs+=("$clr")
  done
fi

# ── Cost — estimated session cost (all backends) ─────────────────────

cost_disp=""
[ -n "$cost_val" ] && cost_disp=$(printf '$%.4f' "$cost_val")

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
  local w=${#v}; (( ${#h} > w )) && w=${#h}
  hdr+="${DIM}$(pad "$h" "$w")${RST}${SEP}"
  val+="${c}$(pad "$v" "$w")${RST}${SEP}"
}

[ -n "$vim_mode" ] && col "mode" "[${vim_mode:0:3}]" "\033[1;35m"
col "workspace" "$short_cwd" "${BOLD}\033[34m"
[ -n "$git_val" ]   && col "branch"     "$git_val"     "\033[33m"
                       col "profile"    "$profile_val" "$profile_clr"
[ -n "$model_val" ] && col "model"      "$model_val"   "\033[32m"
[ -n "$ctx_val" ]   && col "context"    "$ctx_val"     "$ctx_clr"
[ -n "$quota_val" ] && col "quota"      "$quota_val"   "$quota_clr"
[ -n "$cost_disp" ] && col "cost"       "$cost_disp"   "\033[36m"
[ -n "$week_val" ]  && col "week"       "$week_val"    "$week_clr"
for i in "${!scoped_vals[@]}"; do
                       col "${scoped_hdrs[$i]}" "${scoped_vals[$i]}" "${scoped_clrs[$i]}"
done
[ -n "$mem_val" ]   && col "memory"     "$mem_val"     "\033[36m"

printf '%b\n%b' "$hdr" "$val"
