#!/bin/bash
# Tests for claude-code-session-resume.py parsing logic.
#
# Focuses on the two subtle, regression-prone behaviors:
#   - git-commit detection: catch compound commands (recall) without being
#     fooled by commit-like text that was merely printed (precision)
#   - parse_session_jsonl: title extraction + commit/result matching end-to-end
#
# The script's filename has hyphens, so it can't be `import`ed by name; we load
# it from its path with importlib. Only function defs run at import (main() is
# guarded), so importing is safe.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/test_helper.sh"
SCRIPT="$SCRIPT_DIR/../harnesses/claude-code/scripts/claude-code-session-resume.py"

test_begin "session-resume parsing"

_stdout=$(python3 - "$SCRIPT" <<'PY'
import importlib.util, sys, json, tempfile, os

spec = importlib.util.spec_from_file_location("ccsr", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def b(x):
    return "True" if x else "False"

# --- command detection: recall (real commits, incl. compound forms) ---
print("simple=" + b(m._command_makes_commit('git commit -m x')))
print("compound=" + b(m._command_makes_commit('git add -A && git commit -m "feat: x"')))
print("softreset=" + b(m._command_makes_commit('git reset --soft HEAD~1 && git add -A && git commit -m x')))
print("globalopt=" + b(m._command_makes_commit('git -C /tmp/repo commit -m x')))
print("amend=" + b(m._command_makes_commit('git commit --amend --no-edit')))

# --- command detection: precision (must NOT count these) ---
print("log=" + b(m._command_makes_commit('git log --oneline -5')))
print("grep=" + b(m._command_makes_commit('git log --grep=commit')))
print("echo=" + b(m._command_makes_commit("echo 'run git commit later'")))
print("pystr=" + b(m._command_makes_commit('python3 -c "x = 1 if \'git commit\' in cmd else 0"')))

# --- result-line extraction from git's "[branch sha] summary" output ---
def one(t):
    r = m._commits_from_result(t)
    return f"{r[0][0]}|{r[0][1]}" if r else "NONE"
print("res_simple=" + one("[main abc1234] fix: thing\n 1 file changed, 2 insertions(+)"))
print("res_detached=" + one("[detached HEAD def5678] msg"))
print("res_root=" + one("[main (root-commit) abcdef0] init"))
print("res_info=" + one("[INFO] not a commit line"))
print("res_branchonly=" + one("[main] already up to date"))

# --- quiet-commit message recovery from the command itself ---
heredoc_cmd = (
    "git add -A\n"
    "git commit -q -F - <<'EOF'\n"
    "feat: quiet heredoc commit\n\n"
    "Body line that must not be picked as the summary.\n"
    "EOF\n"
    'echo "done: $(git log -1 --format=%h)"'
)
print("msg_heredoc=" + m._commit_message_from_command(heredoc_cmd))
print("msg_dashm=" + m._commit_message_from_command('git commit -q -m "fix: inline message"'))
print("msg_longopt=" + m._commit_message_from_command("git commit -q --message='use long opt'"))
print("msg_none=" + (m._commit_message_from_command("git commit -q --amend --no-edit") or "EMPTY"))

# --- anchored SHA recovery: pick the hash next to THIS summary, not a log's ---
echoed = ("commit done: 9abcdef feat: quiet heredoc commit\n"
          "=== log (top 2) ===\n"
          "9abcdef feat: quiet heredoc commit\n"
          "1111111 some older unrelated commit")
print("sha_anchored=" + (m._sha_for_summary(echoed, "feat: quiet heredoc commit") or "EMPTY"))
print("sha_wrongsummary=" + (m._sha_for_summary(echoed, "some older unrelated commit") or "EMPTY"))
print("sha_missing=" + (m._sha_for_summary("no hash here for feat: x", "feat: x") or "EMPTY"))

# --- end-to-end: title + commit gated on a real invocation, phantom rejected ---
recs = [
    {"type": "ai-title", "aiTitle": "My Session Title"},
    {"type": "user", "message": {"role": "user",
        "content": [{"type": "text", "text": "do the thing"}]}},
    # Real commit: compound command + matching result.
    {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "T1", "name": "Bash",
         "input": {"command": 'git add -A && git commit -m "feat: x"'}}]}},
    {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "T1",
         "content": [{"type": "text", "text": "[main abc1234] feat: x\n 1 file changed"}]}]}},
    # Phantom: a non-commit command whose output merely contains a commit line.
    {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "T2", "name": "Bash",
         "input": {"command": "git log --oneline -1"}}]}},
    {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "T2",
         "content": [{"type": "text", "text": "[main deadbee] phantom not a real commit"}]}]}},
]
fd, fp = tempfile.mkstemp(suffix=".jsonl")
with os.fdopen(fd, "w") as f:
    for r in recs:
        f.write(json.dumps(r) + "\n")
parsed = m.parse_session_jsonl(fp)
os.unlink(fp)
print("title=" + parsed["title"])
print("ncommits=" + str(len(parsed["git_commits"])))
print("commit0=" + (f"{parsed['git_commits'][0][0]}:{parsed['git_commits'][0][1]}"
                    if parsed["git_commits"] else "NONE"))
print("phantom=" + b(any(sha == "deadbee" for sha, _ in parsed["git_commits"])))

# --- end-to-end: quiet (`-q`) commits that print no "[branch sha]" line ---
# Mirrors the real session that exposed the bug: heredoc message + a wrapper
# that echoes the SHA itself, plus a soft-reset/redo whose final SHA must win,
# and a failed quiet commit that must be dropped as a phantom.
def qc(tid, cmd, result, is_error=False):
    return [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "is_error": is_error,
             "content": [{"type": "text", "text": result}]}]}},
    ]

qrecs = []
# Quiet commit, message via heredoc, SHA echoed back by the script.
qrecs += qc("Q1",
    "git add -A\ngit commit -q -F - <<'EOF'\nfeat: alpha\n\nbody\nEOF\n"
    'echo "done: $(git log -1 --format=%h)"',
    "done: aaaaaaa\naaaaaaa feat: alpha")
# Quiet commit via -m, success, NO echoed SHA -> summary shown without a SHA.
qrecs += qc("Q2", 'git commit -q -m "feat: beta"', "")
# Soft-reset then redo the same summary: retain both observed commit SHAs.
qrecs += qc("Q3",
    "git reset --soft HEAD~1\ngit commit -q -F - <<'EOF'\nfeat: alpha\nEOF\n"
    'echo "redo: $(git log -1 --format=%h)"',
    "redo: ccccccc\nccccccc feat: alpha")
# Failed quiet commit: error result, no echoed SHA -> dropped (no phantom).
qrecs += qc("Q4", 'git commit -q -m "feat: never happened"',
    "nothing to commit, working tree clean", is_error=True)

fd, fp = tempfile.mkstemp(suffix=".jsonl")
with os.fdopen(fd, "w") as f:
    for r in qrecs:
        f.write(json.dumps(r) + "\n")
qp = m.parse_session_jsonl(fp)
os.unlink(fp)
qcommits = qp["git_commits"]
print("q_ncommits=" + str(len(qcommits)))
print("q_alpha_shas=" + ",".join(sha for sha, s in qcommits if s == "feat: alpha"))
print("q_beta=" + next((f"{sha or 'NOSHA'}:{s}" for sha, s in qcommits if s == "feat: beta"), "NONE"))
print("q_failed_dropped=" + b(not any(s == "feat: never happened" for _, s in qcommits)))
print("q_body_not_summary=" + b(not any(s == "body" for _, s in qcommits)))
PY
)

# Recall: real commits detected, including compound/global-option forms.
assert_output_contains "simple=True"
assert_output_contains "compound=True"
assert_output_contains "softreset=True"
assert_output_contains "globalopt=True"
assert_output_contains "amend=True"

# Precision: commit-like text that isn't a commit invocation is ignored.
assert_output_contains "log=False"
assert_output_contains "grep=False"
assert_output_contains "echo=False"
assert_output_contains "pystr=False"

# Result parsing yields (sha, summary); non-commit brackets are rejected.
assert_output_contains "res_simple=abc1234|fix: thing"
assert_output_contains "res_detached=def5678|msg"
assert_output_contains "res_root=abcdef0|init"
assert_output_contains "res_info=NONE"
assert_output_contains "res_branchonly=NONE"

# End-to-end: title shown, only the real commit counted, phantom dropped.
assert_output_contains "title=My Session Title"
assert_output_contains "ncommits=1"
assert_output_contains "commit0=abc1234:feat: x"
assert_output_contains "phantom=False"

# Quiet-commit message recovery (unit): heredoc/-m/long-opt, none for bare amend.
assert_output_contains "msg_heredoc=feat: quiet heredoc commit"
assert_output_contains "msg_dashm=fix: inline message"
assert_output_contains "msg_longopt=use long opt"
assert_output_contains "msg_none=EMPTY"

# Anchored SHA recovery (unit): right hash for the summary, none when missing.
assert_output_contains "sha_anchored=9abcdef"
assert_output_contains "sha_wrongsummary=1111111"
assert_output_contains "sha_missing=EMPTY"

# Quiet commits end-to-end: retain both observed alpha SHAs; beta has no
# echoed SHA, failed commit dropped, heredoc body never mistaken for a summary.
assert_output_contains "q_ncommits=3"
assert_output_contains "q_alpha_shas=aaaaaaa,ccccccc"
assert_output_contains "q_beta=NOSHA:feat: beta"
assert_output_contains "q_failed_dropped=True"
assert_output_contains "q_body_not_summary=True"

test_summary "session-resume"
