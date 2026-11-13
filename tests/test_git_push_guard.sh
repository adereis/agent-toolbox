#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"
HOOK="$SCRIPT_DIR/../harnesses/claude-code/hooks/git-push-guard.sh"

# Keep the user's own allow file out of these tests: every case reads an
# empty one unless it writes its own.
GUARD_TMP=$(mktemp -d -p "$HOME/tmp")
trap 'rm -rf "$GUARD_TMP"' EXIT
export GIT_PUSH_GUARD_ALLOW="$GUARD_TMP/allow"
: > "$GIT_PUSH_GUARD_ALLOW"

# Bash tool input for a command, JSON-escaped by jq so commands may hold
# quotes, $(...) and newlines.
bash_input() {
    jq -n --arg c "$1" '{tool_name: "Bash", tool_input: {command: $c}}'
}

expect_ask() {
    test_begin "$1"
    run_hook "$HOOK" "$(bash_input "$2")"
    assert_output_contains '"permissionDecision": "ask"'
}

expect_no_decision() {
    test_begin "$1"
    run_hook "$HOOK" "$(bash_input "$2")"
    assert_output_empty
}

test_begin "git push triggers ask"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}'
assert_output_contains '"permissionDecision": "ask"'
assert_exit_code 0

test_begin "git push --force triggers ask"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"git push --force origin main"}}'
assert_output_contains '"permissionDecision": "ask"'

test_begin "git push with extra whitespace triggers ask"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"git   push origin main"}}'
assert_output_contains '"permissionDecision": "ask"'

test_begin "git status does not trigger"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"git status"}}'
assert_output_empty

test_begin "git pull does not trigger"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"git pull origin main"}}'
assert_output_empty

test_begin "non-Bash tool is ignored"
run_hook "$HOOK" '{"tool_name":"Write","tool_input":{"file_path":"/tmp/test"}}'
assert_output_empty
assert_exit_code 0

test_begin "echo containing git push does not trigger (not a word boundary)"
run_hook "$HOOK" '{"tool_name":"Bash","tool_input":{"command":"echo git-push-guard"}}'
assert_output_empty

# Global options between `git` and `push`. Agents working across
# repositories push with -C; this loop once pushed two repositories
# without a prompt, because the old pattern wanted `push` right after
# `git`.
expect_ask "git -C <repo> push triggers ask" \
    'git -C /work/repo push origin main'
expect_ask "a loop of git -C pushes triggers ask" \
    'for r in /work/a /work/b; do echo "== $(basename $r)"; git -C $r push origin main 2>&1 | tail -2; done'
expect_ask "git -C with a quoted path holding spaces triggers ask" \
    'git -C "/work/my repo" push'
expect_ask "git -C with a quoted variable triggers ask" \
    'git -C "$repo" push --tags'
expect_ask "git -C with a command substitution triggers ask" \
    'git -C $(git rev-parse --show-toplevel) push'
expect_ask "git -c key=value push triggers ask" \
    'git -c http.extraHeader=x push origin'
expect_ask "git --git-dir=... --work-tree=... push triggers ask" \
    'git --git-dir=/work/repo/.git --work-tree=/work/repo push'
expect_ask "git --git-dir with a separate argument triggers ask" \
    'git --git-dir /work/repo/.git push'
expect_ask "git --no-pager push triggers ask" \
    'git --no-pager push'
expect_ask "git by absolute path triggers ask" \
    '/usr/bin/git push origin main'
expect_ask "xargs running git -C {} push triggers ask" \
    'printf "%s\n" a b | xargs -I{} git -C {} push'
expect_ask "a push split by a line continuation triggers ask" \
    $'git -C /work/repo \\\n    push origin main'
expect_ask "a command starting with -n is still read" \
    '-n; git push'

# The same options on other subcommands stay quiet.
expect_no_decision "git -C <repo> pull does not trigger" \
    'git -C /work/repo pull'
expect_no_decision "git -C <repo> stash push (local) does not trigger" \
    'git -C /work/repo stash push -m wip'
expect_no_decision "git -C <repo> log --grep=push does not trigger" \
    'git -C /work/repo log --grep=push'
expect_no_decision "git -C <repo> commit mentioning push does not trigger" \
    'git -C /work/repo commit -m "push later"'
expect_no_decision "a different program ending in git does not trigger" \
    'my-git push'

# Deliberate over-match: the guard scans text, so a command that only
# mentions a push is asked about too. A shell parser would avoid this
# prompt, but any construct it misread would let a real push through
# unasked.
expect_ask "text that mentions git push asks (deliberate)" \
    'echo "remember to git push later"'

# Exceptions from the allow file: only the exact form, only until the
# line's date.
cat > "$GIT_PUSH_GUARD_ALLOW" <<EOF
# a comment, then a malformed line, then the real entries
not-a-date /work/ignored
2999-12-31 /work/app
2999-12-31 $HOME/work/app
2000-01-01 /work/expired
EOF
expect_no_decision "an allowed exact push skips the prompt" \
    'git -C /work/app push origin main'
expect_no_decision "surrounding whitespace doesn't matter" \
    '  git -C /work/app push origin main  '
expect_no_decision "~ stands for \$HOME in an allowed path under it" \
    'git -C ~/work/app push origin main'
expect_ask "~ never stands for a path outside \$HOME" \
    'git -C ~/work/app2 push origin main'
expect_ask "an expired line asks again" \
    'git -C /work/expired push origin main'
expect_ask "a force push of an allowed repo asks" \
    'git -C /work/app push --force origin main'
expect_ask "another branch of an allowed repo asks" \
    'git -C /work/app push origin dev'
expect_ask "an allowed push chained after another command asks" \
    'cd /work && git -C /work/app push origin main'
expect_ask "an allowed push followed by another command asks" \
    'git -C /work/app push origin main; git -C /work/other push origin main'
expect_ask "a repo that isn't listed asks" \
    'git -C /work/other push origin main'
expect_ask "a malformed line allows nothing" \
    'git -C /work/ignored push origin main'
expect_ask "a plain git push asks even with an allow file" \
    'git push origin main'
: > "$GIT_PUSH_GUARD_ALLOW"

test_summary "git-push-guard"
