#!/bin/bash
#
# Shared library for claude-memory-{export,import,status} scripts.
#
# Source this file — do not execute directly.
# Provides path encoding, project discovery, and argument parsing.

# Defaults (override with env vars or CLI flags)
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
CLAUDE_PROJECTS_DIR="${CLAUDE_PROJECTS_DIR:-$HOME/projects}"
CLAUDE_MEMORY_DIR="${CLAUDE_MEMORY_DIR:-$HOME/.claude/memory-sync}"

SKIP_PREFIXES=()

# --- Path encoding ---

encode_path() {
    echo "$1" | tr '/' '-'
}

home_encoded() {
    encode_path "$HOME"
}

project_encoded() {
    local slug="$1"
    encode_path "$CLAUDE_PROJECTS_DIR/$slug"
}

# --- File operations ---

file_sha() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    else
        shasum -a 256 "$1" | cut -d' ' -f1
    fi
}

# --- Skip-prefix filtering ---

is_skipped() {
    local slug="$1"
    for prefix in "${SKIP_PREFIXES[@]+"${SKIP_PREFIXES[@]}"}"; do
        [[ "$slug" = "$prefix"* ]] && return 0
    done
    return 1
}

# --- Project discovery ---
# Finds git repos under CLAUDE_PROJECTS_DIR and outputs their slugs
# (paths relative to CLAUDE_PROJECTS_DIR). Uses find+.git to avoid
# the lossy reverse-encoding problem — we always go from known
# filesystem paths to encoding, never the other direction.

discover_projects() {
    find "$CLAUDE_PROJECTS_DIR" -mindepth 1 -maxdepth 4 \
        -name '.git' -type d -printf '%h\0' 2>/dev/null | sort -z
}

# --- Argument parsing ---
# Call with "$@" from the main script. Sets CLAUDE_DIR, CLAUDE_PROJECTS_DIR,
# CLAUDE_MEMORY_DIR, and SKIP_PREFIXES from CLI flags.

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dir)
                CLAUDE_MEMORY_DIR="$2"; shift 2 ;;
            --projects-dir)
                CLAUDE_PROJECTS_DIR="$2"; shift 2 ;;
            --claude-dir)
                CLAUDE_DIR="$2"; shift 2 ;;
            --skip)
                SKIP_PREFIXES+=("$2"); shift 2 ;;
            -h|--help)
                show_help; exit 0 ;;
            *)
                echo "Unknown option: $1" >&2; exit 1 ;;
        esac
    done
}

# --- Disk paths for a slug ---

claude_memory_path() {
    local slug="$1"
    if [[ "$slug" = "_global" ]]; then
        echo "$CLAUDE_DIR/projects/$(home_encoded)/memory"
    else
        echo "$CLAUDE_DIR/projects/$(project_encoded "$slug")/memory"
    fi
}

portable_memory_path() {
    local slug="$1"
    echo "$CLAUDE_MEMORY_DIR/$slug/memory"
}
