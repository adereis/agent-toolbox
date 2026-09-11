#!/bin/bash
# Run the shell and Python suites with private temporary files under ~/tmp.
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/tmp" || exit 1
TMPDIR=$(mktemp -d "$HOME/tmp/agent-toolbox-tests.XXXXXXXX") || exit 1
export TMPDIR
trap 'rm -rf -- "$TMPDIR"' EXIT

overall_fail=0
if [ -n "${1:-}" ]; then
    name="${1#test_}"
    name="${name%.sh}"
    name="${name%.py}"
    if [ -f "$SCRIPT_DIR/test_${name}.sh" ]; then
        bash "$SCRIPT_DIR/test_${name}.sh"
        exit $?
    elif [ -f "$SCRIPT_DIR/test_${name}.py" ]; then
        python3 -m unittest discover -s "$SCRIPT_DIR" -p "test_${name}.py"
        exit $?
    fi
    echo "Test not found: $1" >&2
    exit 1
fi

for test_file in "$SCRIPT_DIR"/test_*.sh; do
    [ "$test_file" = "$SCRIPT_DIR/test_helper.sh" ] && continue
    bash "$test_file" || overall_fail=1
done
python3 -m unittest discover -s "$SCRIPT_DIR" -p 'test_*.py' || overall_fail=1

if [ "$overall_fail" -eq 0 ]; then
    echo "All test suites passed."
else
    echo "Some tests failed." >&2
fi
exit "$overall_fail"
