#!/bin/bash
# Tests for codex-api-profile. Stubs secret-tool and codex on PATH so the
# suite never reads, writes, or requires the developer's real keyring.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"
SCRIPT="$SCRIPT_DIR/../harnesses/codex/scripts/codex-api-profile.sh"

FAKE_KEY="sk-FAKE-TEST-KEY-NOT-A-CREDENTIAL"
WORK="$(mktemp -d "${TMPDIR:-$HOME/tmp}/codex-api-profile.XXXXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT

STATE="$WORK/state"
BIN="$WORK/bin"
mkdir -p "$STATE" "$BIN"

cat > "$BIN/secret-tool" <<STUB
#!/bin/bash
# Stub libsecret backend backed by a file under the test state directory.
case "\$1" in
    lookup) [ -s "$STATE/key" ] || exit 1; cat "$STATE/key" ;;
    store)  cat > "$STATE/key" ;;
    clear)  rm -f "$STATE/key" ;;
    *)      exit 2 ;;
esac
STUB

cat > "$BIN/codex" <<STUB
#!/bin/bash
# Stub Codex that records its arguments and the inherited key variable.
printf '%s\n' "args=\$*" > "$STATE/invocation"
printf '%s\n' "key=\${CODEX_OPENAI_API_KEY:-unset}" >> "$STATE/invocation"
STUB

chmod +x "$BIN/secret-tool" "$BIN/codex"

# Minimal PATH for the missing-backend cases: real utilities the script
# needs, a uname we control, and deliberately no secret-tool.
NOBIN="$WORK/nobin"
mkdir -p "$NOBIN"
for utility in sed cat rm mktemp; do
    ln -s "$(command -v "$utility")" "$NOBIN/$utility"
done

run_with_path() {
    local path="$1"; shift
    local saved="$PATH"
    PATH="$path"
    run_script "$SCRIPT" "$@"
    PATH="$saved"
}

STUBBED="$BIN:$PATH"

# --- Missing key ---

rm -f "$STATE/key" "$STATE/invocation"

test_begin "missing key reports the store command and fails"
run_with_path "$STUBBED"
assert_exit_code 1
assert_stderr_contains "codex-api-profile --store"

test_begin "missing key does not invoke codex"
[ ! -f "$STATE/invocation" ] && _pass=$((_pass + 1)) || {
    _fail=$((_fail + 1)); echo "  FAIL: codex ran without a key"; }

test_begin "status reports missing"
run_with_path "$STUBBED" --status
assert_output_contains "missing"
assert_exit_code 1

# --- Storing ---

test_begin "store writes the key to the keyring"
printf '%s\n' "$FAKE_KEY" | (PATH="$STUBBED" "$SCRIPT" --store >/dev/null)
[ "$(cat "$STATE/key")" = "$FAKE_KEY" ] && _pass=$((_pass + 1)) || {
    _fail=$((_fail + 1)); echo "  FAIL: stored key did not round-trip"; }

test_begin "status reports stored"
run_with_path "$STUBBED" --status
assert_output_contains "stored"
assert_exit_code 0

test_begin "status does not print the key"
assert_output_lacks "$FAKE_KEY"

# --- Running ---

test_begin "codex receives the key through the environment"
run_with_path "$STUBBED" exec "say ok"
assert_exit_code 0
grep -q "key=$FAKE_KEY" "$STATE/invocation" && _pass=$((_pass + 1)) || {
    _fail=$((_fail + 1)); echo "  FAIL: key variable did not reach codex"; }

test_begin "the api profile is appended"
grep -q -- "--profile api" "$STATE/invocation" && _pass=$((_pass + 1)) || {
    _fail=$((_fail + 1)); echo "  FAIL: --profile api missing"; }

test_begin "the wrapper does not print the key"
assert_output_lacks "$FAKE_KEY"

test_begin "an explicit profile is not overridden"
run_with_path "$STUBBED" exec --profile subscription
[ "$(grep -c -- '--profile' "$STATE/invocation")" -eq 1 ] && _pass=$((_pass + 1)) || {
    _fail=$((_fail + 1)); echo "  FAIL: duplicated --profile"; }

test_begin "a double dash separator is consumed"
run_with_path "$STUBBED" -- exec "say ok"
grep -q "args=exec say ok --profile api" "$STATE/invocation" && _pass=$((_pass + 1)) || {
    _fail=$((_fail + 1)); echo "  FAIL: separator not consumed: $(cat "$STATE/invocation")"; }

# --- Clearing ---

test_begin "clear removes the stored key"
run_with_path "$STUBBED" --clear
assert_exit_code 0
[ ! -s "$STATE/key" ] && _pass=$((_pass + 1)) || {
    _fail=$((_fail + 1)); echo "  FAIL: key survived --clear"; }

# --- Missing backend breadcrumbs ---

cat > "$NOBIN/uname" <<'STUB'
#!/bin/bash
printf 'Linux\n'
STUB
chmod +x "$NOBIN/uname"

test_begin "a missing backend names the libsecret package"
run_with_path "$NOBIN" --status
assert_exit_code 1
assert_stderr_contains "libsecret"

test_begin "a missing backend offers a keyring-free fallback"
assert_stderr_contains "CODEX_OPENAI_API_KEY="

cat > "$NOBIN/uname" <<'STUB'
#!/bin/bash
printf 'Darwin\n'
STUB

test_begin "macOS states that the backend is not implemented"
run_with_path "$NOBIN" --status
assert_exit_code 1
assert_stderr_contains "macOS"

test_begin "macOS names the security command to use instead"
assert_stderr_contains "find-generic-password"

test_begin "macOS failure is loud rather than silent"
assert_output_empty

test_summary "codex-api-profile"
