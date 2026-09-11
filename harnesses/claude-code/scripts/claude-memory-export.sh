#!/bin/bash
#
# claude-memory-export — Export Claude Code memories to a portable directory.
#
# Scans git repos under your projects directory, finds matching Claude
# memory directories, and copies new/changed files into a portable
# directory using project-relative slugs (stripping the machine-specific
# path encoding).
#
# The portable directory can then be synced to other machines via git,
# rsync, Syncthing, or any file-sync tool.
#
# Usage: claude-memory-export [OPTIONS]
#
# Options:
#   --dir <path>          Portable directory (default: ~/.claude/memory-sync)
#   --projects-dir <path> Projects base directory (default: ~/projects)
#   --claude-dir <path>   Claude Code data directory (default: ~/.claude)
#   --skip <prefix>       Skip projects matching prefix (repeatable)
#   -h, --help            Show this help
#
# Output (tab-separated):
#   SKIP       <slug/path>  <sha256>   — file unchanged
#   COLLECTED  <slug/path>  <sha256>   — updated file copied
#   NEW        <slug/path>  <sha256>   — new file copied
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

export_memory_dir() {
    local slug="$1"
    local source_dir="$2"

    local target_dir
    target_dir="$(portable_memory_path "$slug")"
    mkdir -p "$target_dir"

    for src_file in "$source_dir"/*.md; do
        [[ -f "$src_file" ]] || continue
        local filename
        filename=$(basename "$src_file")
        local target_file="$target_dir/$filename"
        local src_sha
        src_sha=$(file_sha "$src_file")

        if [[ -f "$target_file" ]]; then
            local target_sha
            target_sha=$(file_sha "$target_file")
            if [[ "$src_sha" = "$target_sha" ]]; then
                printf "SKIP\t%s\t%s\n" "$slug/memory/$filename" "$src_sha"
                continue
            fi
            cp -a "$src_file" "$target_file"
            printf "COLLECTED\t%s\t%s\n" "$slug/memory/$filename" "$src_sha"
        else
            cp -a "$src_file" "$target_file"
            printf "NEW\t%s\t%s\n" "$slug/memory/$filename" "$src_sha"
        fi
    done
}

# Export global memories
global_mem="$(claude_memory_path "_global")"
if [[ -d "$global_mem" ]]; then
    export_memory_dir "_global" "$global_mem"
fi

# Export project memories
while IFS= read -r -d '' project_dir; do
    slug="${project_dir#"$CLAUDE_PROJECTS_DIR"/}"
    is_skipped "$slug" && continue

    mem_dir="$(claude_memory_path "$slug")"
    [[ -d "$mem_dir" ]] || continue

    has_md=false
    for f in "$mem_dir"/*.md; do
        [[ -f "$f" ]] && { has_md=true; break; }
    done
    $has_md || continue

    export_memory_dir "$slug" "$mem_dir"
done < <(discover_projects)
