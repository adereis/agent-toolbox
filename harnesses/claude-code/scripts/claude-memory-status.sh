#!/bin/bash
#
# claude-memory-status — Show sync status between disk and portable directory.
#
# Two-way comparison: checks portable directory files against local
# Claude memories, and discovers local memories not yet exported.
#
# For a three-way comparison that can distinguish "remote updated"
# from "local edit", see the Advanced section in scripts/README.md.
#
# Usage: claude-memory-status [OPTIONS]
#
# Options:
#   --dir <path>          Portable directory (default: ~/.claude/memory-sync)
#   --projects-dir <path> Projects base directory (default: ~/projects)
#   --claude-dir <path>   Claude Code data directory (default: ~/.claude)
#   --skip <prefix>       Skip projects matching prefix (repeatable)
#   -h, --help            Show this help
#
# Output (tab-separated):
#   OK               <slug/path>   — in sync
#   DIFFERS          <slug/path>   — content differs (can't tell direction)
#   NEW_LOCAL        <slug/path>   — exists on disk only
#   NEW_PORTABLE     <slug/path>   — exists in portable dir only
#   DELETED_LOCAL    <slug/path>   — in portable dir but missing from disk
#
# Exit codes:
#   0 — everything in sync
#   1 — error
#   2 — differences found

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/claude-memory-lib.sh"

show_help() {
    sed -n '/^# Usage:/,/^[^#]/{ /^#/s/^# \?//p; }' "$0"
}

parse_args "$@"

has_diff=false
declare -A seen_slugfiles

# --- Phase 1: Compare portable dir files against disk ---

if [[ -d "$CLAUDE_MEMORY_DIR" ]]; then
    while IFS= read -r -d '' portable_file; do
        rel="${portable_file#"$CLAUDE_MEMORY_DIR"/}"
        slug="${rel%%/memory/*}"
        filename=$(basename "$portable_file")
        slugfile="$slug/memory/$filename"
        seen_slugfiles["$slugfile"]=1

        is_skipped "$slug" && continue

        disk_dir="$(claude_memory_path "$slug")"
        disk_file="$disk_dir/$filename"

        if [[ -f "$disk_file" ]]; then
            portable_sha=$(file_sha "$portable_file")
            disk_sha=$(file_sha "$disk_file")
            if [[ "$portable_sha" = "$disk_sha" ]]; then
                printf "OK\t%s\n" "$slugfile"
            else
                printf "DIFFERS\t%s\n" "$slugfile"
                has_diff=true
            fi
        else
            printf "DELETED_LOCAL\t%s\n" "$slugfile"
            has_diff=true
        fi
    done < <(find "$CLAUDE_MEMORY_DIR" -path '*/memory/*.md' -type f -print0 | sort -z)
fi

# --- Phase 2: Discover local-only memories ---

discover_new_local() {
    local slug="$1"
    local mem_dir="$2"

    for disk_file in "$mem_dir"/*.md; do
        [[ -f "$disk_file" ]] || continue
        local filename
        filename=$(basename "$disk_file")
        local slugfile="$slug/memory/$filename"

        [[ -n "${seen_slugfiles[$slugfile]:-}" ]] && continue

        printf "NEW_LOCAL\t%s\n" "$slugfile"
        has_diff=true
    done
}

# Check global
global_mem="$(claude_memory_path "_global")"
[[ -d "$global_mem" ]] && discover_new_local "_global" "$global_mem"

# Check project dirs
while IFS= read -r -d '' project_dir; do
    slug="${project_dir#"$CLAUDE_PROJECTS_DIR"/}"
    is_skipped "$slug" && continue
    mem_dir="$(claude_memory_path "$slug")"
    [[ -d "$mem_dir" ]] && discover_new_local "$slug" "$mem_dir"
done < <(discover_projects)

$has_diff && exit 2 || exit 0
