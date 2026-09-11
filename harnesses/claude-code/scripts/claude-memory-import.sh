#!/bin/bash
#
# claude-memory-import — Import Claude Code memories from a portable directory.
#
# Reads memory files from the portable directory, computes the
# machine-specific encoded path for each project slug, and deploys
# them to the local Claude Code data directory.
#
# Usage: claude-memory-import [OPTIONS]
#
# Options:
#   --dir <path>          Portable directory (default: ~/.claude/memory-sync)
#   --projects-dir <path> Projects base directory (default: ~/projects)
#   --claude-dir <path>   Claude Code data directory (default: ~/.claude)
#   --skip <prefix>       Skip projects matching prefix (repeatable)
#   -h, --help            Show this help
#
# Output (tab-separated):
#   SKIP      <slug/path>  <sha256>   — file unchanged
#   DEPLOYED  <slug/path>  <sha256>   — updated file deployed
#   NEW       <slug/path>  <sha256>   — new file deployed
#
# Environment variables:
#   CLAUDE_MEMORY_DIR    — same as --dir
#   CLAUDE_PROJECTS_DIR  — same as --projects-dir
#   CLAUDE_DIR           — same as --claude-dir

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/claude-memory-lib.sh"

show_help() {
    sed -n '/^# Usage:/,/^[^#]/{ /^#/s/^# \?//p; }' "$0"
}

parse_args "$@"

[[ -d "$CLAUDE_MEMORY_DIR" ]] || {
    echo "Error: portable directory not found: $CLAUDE_MEMORY_DIR" >&2
    echo "Run claude-memory-export first, or specify --dir." >&2
    exit 1
}

while IFS= read -r -d '' src_file; do
    rel="${src_file#"$CLAUDE_MEMORY_DIR"/}"
    slug="${rel%%/memory/*}"
    [[ -z "$slug" || "$slug" = "$rel" ]] && continue
    mem_rel="${rel#"$slug"/}"
    filename=$(basename "$src_file")

    is_skipped "$slug" && continue

    target_dir="$(claude_memory_path "$slug")"
    target_file="$target_dir/$filename"

    mkdir -p "$target_dir"

    src_sha=$(file_sha "$src_file")

    if [[ -f "$target_file" ]]; then
        dst_sha=$(file_sha "$target_file")
        if [[ "$src_sha" = "$dst_sha" ]]; then
            printf "SKIP\t%s\t%s\n" "$slug/memory/$filename" "$src_sha"
            continue
        fi
        cp -a "$src_file" "$target_file"
        printf "DEPLOYED\t%s\t%s\n" "$slug/memory/$filename" "$src_sha"
    else
        cp -a "$src_file" "$target_file"
        printf "NEW\t%s\t%s\n" "$slug/memory/$filename" "$src_sha"
    fi
done < <(find "$CLAUDE_MEMORY_DIR" -path '*/memory/*.md' -type f -print0 | sort -z)
