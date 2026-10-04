# Settings

Claude Code settings configurations. Add these snippets to your `~/.claude/settings.json`.

## statusline.sh

A two-row columnar statusline with dim headers and colored values. Adapts to your setup — vim mode only appears if enabled, the quota columns only on a subscription, and memory detection works on both Linux and macOS. It mirrors the three windows `/usage` shows: the 5-hour session limit, the weekly all-models limit, and any per-model weekly limit.

**Illustrative output** (fictitious values, with vim mode enabled):
```
mode   workspace            branch   model    effort   session   cost    @14:30   week   model-B   profile   memory
[NOR]  ~/projects/demo-app  main*    model-A  high     23%       $1.23   42%      40%    17%       example   312.5 MB
```

The ASCII `@14:30` represents the reset-time header; the terminal uses a
clock-arrow symbol. Model and profile labels depend on the actual session.

Columns are grouped by what they describe: the conversation (`session`, `cost`),
then the plan windows that outlive it (`↻14:30`, `week`, per-model).

The 5-hour quota column has no fixed header — it wears the wall-clock time it
resets at (`↻14:30`), so the deadline costs no extra width.

**Columns:**

| Column | Color | Description |
|--------|-------|-------------|
| mode | Bold magenta | Vim mode indicator, abbreviated to 3 letters (`[NOR]`/`[INS]`), only when vim mode is on |
| workspace | Bold blue | Working directory (`~` shorthand for `$HOME`) |
| branch | Yellow | Git branch + status indicators (`*` dirty, `+` staged, `%` untracked) |
| model | Green | Active model display name. On a 1M-context session the ` (1M context)` qualifier Claude Code appends for `[1m]` model ids is stripped — it is the ordinary case now and only widened the column. When the enforced window is smaller, the name wears its size instead (e.g. `Opus 4.8 [200k]`), read from `context_window_size` — this covers both the plain 200k model variant and a `[1m]` model whose 1M credits are spent |
| effort | Magenta (dim→bold) | Reasoning effort level (`low`/`medium`/`high`/`xhigh`/`max`), read from `.effort.level`. Brightness ramps with intensity — dim at `low`, bold at `max` — deliberately off the green→red tier scale, which is reserved for "distance to a limit". Hidden on models with no effort parameter |
| session | Green→Yellow→Red | Context window fill for this conversation, color-coded by tier |
| cost | Cyan | Estimated session cost in USD to the cent, computed client-side (all backends). Reads `$0.00` until the session crosses a cent |
| ↻*HH:MM* | Green→Yellow→Red | 5-hour rate limit usage (subscription only — absent on API/Vertex). The header is the local time the window resets, read from `resets_at` in the same payload; it falls back to `quota` when that field is absent |
| week | Green→Yellow→Red | 7-day all-models rate limit usage (subscription only) |
| *model name* | Green→Yellow→Red | 7-day per-model limit, one column per bucket the API reports (e.g. `fable`). Requires `statusline-usage.sh` — see below |
| profile | Cyan/Yellow/Dim | Which account this session bills to: the exact plan on a subscription (`pro`, `max 5x`, `max 20x`, `team`, …), `vertex` on Vertex AI, or a dim `api` for a key-based backend. The plan is not in the status line payload — it is read from `subscriptionType` + `rateLimitTier` in `~/.claude/.credentials.json`, the same pair Claude Code uses to tell Max 20x from Max 5x. Only those two fields are read; the access token beside them is never touched. The column disappears when nothing identifies the backend |
| memory | Cyan | Claude Code process RSS memory |

**Color thresholds** (session, quota, week, per-model):
- **Green**: < 50% used
- **Yellow**: 50–79% used
- **Red**: ≥ 80% used

**Installation:**

1. Copy `statusline.sh` to `~/.claude/` (or use `/agent-toolbox-sync`)
2. Make it executable: `chmod +x ~/.claude/statusline.sh`
3. Add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline.sh",
    "refreshInterval": 10
  }
}
```

4. For the per-model weekly columns, also install `statusline-usage.sh` (below)

**Platform notes:**

- **Linux**: Memory detection reads `/proc/<pid>/status` (VmRSS)
- **macOS**: Memory detection uses `ps -o rss=`
- Requires `jq` and `git` in `$PATH` (plus `curl` for the per-model columns)

## statusline-usage.sh

Keeps the per-model weekly quota columns fed. Install it next to `statusline.sh` — the status line looks for it as a sibling and does nothing if it is absent.

**Why it is needed:** the JSON Claude Code pipes to a status line carries only two windows, `five_hour` and `seven_day`. Per-model weekly buckets are not in it. `/usage` gets those from `GET /api/oauth/usage`, and Claude Code persists that response to `~/.claude.json` (`cachedUsageUtilization`) **only when you open the `/usage` dialog** — no timer, no startup prefetch. Between visits that copy just sits there, so reading it alone would show a number that is usually hours old.

So this script fetches the same endpoint on a timer. The status line spawns it detached and never waits on the network itself.

```
Claude Code ──stdin──► statusline.sh ──► quota, week           (live, from response headers)
                            │
                            ├─ reads ──► ~/.claude/statusline-usage.json   (this script, refreshed on a timer)
                            │            ~/.claude.json                    (Claude Code's copy, whichever is newer)
                            └─ spawns ─► statusline-usage.sh ──► GET /api/oauth/usage
```

**Behavior worth knowing:**

- Safe to call on every tick. It self-gates on a TTL and exits in ~10ms when a refresh is not due.
- The TTL gate keys on *attempt*, not success, so a bad token cannot cause one request per tick. Concurrent sessions collapse into a single request via an `mkdir` mutex, re-checked after acquiring it.
- A failed refresh never overwrites the last good snapshot.
- The bearer token is passed to `curl` via `--config` on stdin, never on the command line where `ps` would expose it.
- When the snapshot ages past 15 minutes the status line dims the value and appends its age (`17% ·2h`) instead of presenting stale data as current.

**Commands:**

```
statusline-usage.sh            # refresh if older than the TTL (what the status line calls)
statusline-usage.sh --force    # refresh now
statusline-usage.sh --status   # snapshot age, current buckets, last error
statusline-usage.sh --path     # print the snapshot path
```

**Environment:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `CLAUDE_USAGE_CACHE` | `~/.claude/statusline-usage.json` | Snapshot path |
| `CLAUDE_USAGE_TTL` | `300` | Seconds between refreshes (matches Claude Code's own throttle on this endpoint) |
| `CLAUDE_USAGE_STALE_AFTER` | `900` | Seconds before the status line marks a value stale |
| `CLAUDE_USAGE_CREDS` | `~/.claude/.credentials.json` | OAuth credentials |
| `CLAUDE_USAGE_API` | `https://api.anthropic.com` | API base |
| `CLAUDE_USAGE_FALLBACK` | `~/.claude.json` | Claude Code's own usage cache |
| `CLAUDE_USAGE_REFRESH` | sibling `statusline-usage.sh` | Refresher the status line spawns |

**Caveat:** `/api/oauth/usage` is an internal endpoint, not a documented API. It is the same call `/usage` makes, but its response shape can change between Claude Code releases. If a per-model column disappears, run `statusline-usage.sh --status` to see what the endpoint is actually returning.

If there are no OAuth credentials (API key, Bedrock, Vertex) the script exits silently and the per-model columns simply do not appear.

**Customization:**

The script uses ANSI escape codes for colors. To change them, modify the `\033[XXm` sequences:
- `31` = red, `32` = green, `33` = yellow, `34` = blue, `35` = magenta, `36` = cyan
- `01;XX` = bold, `2m` = dim (used for headers)

To hide a column, comment out or remove its `col` call near the end of the script.
