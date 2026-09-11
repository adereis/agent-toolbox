# Claude Code hook reference examples

These examples are **not installed or enabled** by Agent Toolbox. They replace
the retired tmp and test-edit guards as small examples to study and adapt.
They require Python 3.10 or newer and use Claude Code's `PreToolUse` payload.

## Deny access to a selected directory

`block-directory.py --blocked-dir /absolute/path/to/private-data` emits a
`deny` decision for direct file access within the configured directory. It
handles Read, Write, Edit, MultiEdit, NotebookEdit, Glob, and Grep. Relative
paths resolve against the event's `cwd`; directory boundaries, traversal,
and existing symlinks are checked. Search scopes that include the blocked
directory are denied conservatively, including searches of its ancestors.

Example input, using fictitious paths:

```bash
printf '%s\n' '{"cwd":"/workspace/demo","tool_name":"Read","tool_input":{"file_path":"private-data/example.txt"}}' |
  python3 examples/claude-code/hooks/block-directory.py \
    --blocked-dir /workspace/demo/private-data
```

For an intentional manual installation, match
`Read|Write|Edit|MultiEdit|NotebookEdit|Glob|Grep` and invoke the script with
an absolute blocked directory. No default directory is blocked.

This demonstrates a hook decision, not an OS filesystem boundary. Shell
commands, MCP tools, other processes, and symlink changes after the check
need enforcement through the harness or operating system sandbox. Do not
try to enforce arbitrary shell access with command-string regexes. Malformed
input for supported tools exits with status 2 and an explanatory error.

## Add context when a file is edited

`file-edit-context.py` emits `additionalContext` for matching file paths. It
handles Write, Edit, MultiEdit, and NotebookEdit and makes no permission
decision. Choose a regex and message appropriate to the repository:

```bash
printf '%s\n' '{"tool_name":"Edit","tool_input":{"file_path":"migrations/example.sql"}}' |
  python3 examples/claude-code/hooks/file-edit-context.py \
    --pattern '(^|/)migrations/' \
    --message 'Check migration ordering and rollback behavior.'
```

The example has no shared log or persistent state. JSON encoding preserves
quotes and newlines in the supplied message.
