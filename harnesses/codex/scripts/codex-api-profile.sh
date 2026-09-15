#!/bin/bash
#
# codex-api-profile — Run Codex under the API profile with a keyring-held key.
#
# Reads the OpenAI API key from the login keyring and exports it as
# CODEX_OPENAI_API_KEY for the Codex process only. The saved ChatGPT login
# is never read or replaced, so subscription access survives API use.
#
# The variable name must match `env_key` in ../profiles/api.config.toml.
# It ends in KEY so that Codex's default shell_environment_policy excludes
# it from the environment of model-run shell commands.
#
# Usage: codex-api-profile [OPTIONS] [CODEX ARGS...]
#
# Options:
#   --store       Store the API key in the keyring (input is not echoed)
#   --status      Report whether a key is stored, without printing it
#   --clear       Remove the stored key from the keyring
#   -h, --help    Show this help
#
# An option is recognised only as the first argument. Any other arguments
# are passed to codex, which runs under --profile api unless those
# arguments already select a profile:
#
#   codex-api-profile                 # interactive session
#   codex-api-profile exec "say ok"   # non-interactive
#   codex-api-profile resume --last   # resume under the API profile
#
# Keyring backend: secret-tool (libsecret). macOS is not implemented; the
# error names the built-in `security` commands to use instead.
#
# Environment:
#   CODEX_API_KEYRING_SERVICE  Keyring service attribute (default: codex)
#   CODEX_API_KEYRING_ACCOUNT  Keyring account attribute (default: openai-api)
#
# Exit codes:
#   0 — success, or --status found a stored key
#   1 — error, missing key, or unsupported keyring backend

set -euo pipefail

KEYRING_SERVICE="${CODEX_API_KEYRING_SERVICE:-codex}"
KEYRING_ACCOUNT="${CODEX_API_KEYRING_ACCOUNT:-openai-api}"
KEYRING_LABEL="Codex OpenAI API key (Agent Toolbox)"
KEY_VARIABLE="CODEX_OPENAI_API_KEY"
PROFILE="api"

show_help() {
    sed -n '/^# Usage:/,/^[^#]/{ /^#/s/^# \?//p; }' "$0"
}

# Fail with a backend-specific breadcrumb rather than a silent no-op.
backend_unavailable() {
    if [ "$(uname -s)" = "Darwin" ]; then
        cat >&2 <<EOF
codex-api-profile: no supported keyring backend on macOS.

This script implements the libsecret backend (secret-tool) only. The macOS
equivalent is the built-in \`security\` command:

  security add-generic-password -s $KEYRING_SERVICE -a $KEYRING_ACCOUNT -w
  security find-generic-password -s $KEYRING_SERVICE -a $KEYRING_ACCOUNT -w

Supply the key to the Codex process alone:

  $KEY_VARIABLE="\$(security find-generic-password \\
      -s $KEYRING_SERVICE -a $KEYRING_ACCOUNT -w)" codex --profile $PROFILE

A tested macOS backend would be a welcome contribution.
EOF
    else
        cat >&2 <<EOF
codex-api-profile: secret-tool not found.

Install the libsecret command line tool (Fedora: libsecret; Debian and
Ubuntu: libsecret-tools) and run a keyring daemon. Without a keyring,
supply the key to the Codex process alone:

  $KEY_VARIABLE="\$(cat ~/.codex/api-key)" codex --profile $PROFILE
EOF
    fi
    exit 1
}

require_backend() {
    command -v secret-tool >/dev/null 2>&1 || backend_unavailable
}

lookup_key() {
    secret-tool lookup service "$KEYRING_SERVICE" account "$KEYRING_ACCOUNT" 2>/dev/null
}

# Echoes the key on stdout; callers must not log it.
require_key() {
    local key
    if ! key="$(lookup_key)" || [ -z "$key" ]; then
        cat >&2 <<EOF
codex-api-profile: no key stored for $KEYRING_SERVICE/$KEYRING_ACCOUNT.

Store one with:

  codex-api-profile --store
EOF
        exit 1
    fi
    printf '%s' "$key"
}

has_profile_flag() {
    local argument
    for argument in "$@"; do
        case "$argument" in
            -p|--profile|--profile=*) return 0 ;;
        esac
    done
    return 1
}

store_key() {
    require_backend
    [ -t 0 ] && printf 'Reading the API key; input is not echoed.\n' >&2
    secret-tool store --label="$KEYRING_LABEL" \
        service "$KEYRING_SERVICE" account "$KEYRING_ACCOUNT"
    printf 'Stored\t%s/%s\n' "$KEYRING_SERVICE" "$KEYRING_ACCOUNT"
}

report_status() {
    require_backend
    local key
    if key="$(lookup_key)" && [ -n "$key" ]; then
        printf 'stored\t%s/%s\n' "$KEYRING_SERVICE" "$KEYRING_ACCOUNT"
        return 0
    fi
    printf 'missing\t%s/%s\n' "$KEYRING_SERVICE" "$KEYRING_ACCOUNT"
    return 1
}

clear_key() {
    require_backend
    secret-tool clear service "$KEYRING_SERVICE" account "$KEYRING_ACCOUNT"
    printf 'Cleared\t%s/%s\n' "$KEYRING_SERVICE" "$KEYRING_ACCOUNT"
}

run_codex() {
    require_backend
    local key
    key="$(require_key)"
    command -v codex >/dev/null 2>&1 || {
        printf 'codex-api-profile: codex not found on PATH.\n' >&2
        exit 1
    }
    export "$KEY_VARIABLE=$key"
    if has_profile_flag "$@"; then
        exec codex "$@"
    fi
    exec codex "$@" --profile "$PROFILE"
}

case "${1:-}" in
    -h|--help) show_help; exit 0 ;;
    --store) store_key; exit 0 ;;
    --status) report_status ;;
    --clear) clear_key; exit 0 ;;
    --) shift; run_codex "$@" ;;
    *) run_codex "$@" ;;
esac
