#!/usr/bin/env python3
"""Install explicitly selected Agent Toolbox components as scoped symlinks."""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import sys


REPO = Path(__file__).resolve().parents[1]
COMPONENTS = ("skills", "scripts", "hooks", "settings", "prompts", "instructions",
              "profiles", "commands")

# Utilities a person runs at a shell prompt, installed without their extension.
# The whats-new scripts are deliberately absent: a skill invokes them by path
# and interprets output they withhold judgement on, and a stray --commit would
# move the digest baseline out from under that skill.
# claude-memory-sync is withheld for a similar reason: its deletions and
# merges propagate to every machine, so an agent runs it by path under
# prompts/sync-memories.md and accounts for each one.
# Each entry names the installed command and its source, relative to the
# checkout. `convene` is the engine shipped inside the Claude Code plugin;
# its shim resolves the engine through the link's real path, so one symlink
# on PATH serves Claude Code, Codex and a shell alike.
COMMANDS = {
    "claude-code": {
        "claude-code-session-resume": "harnesses/claude-code/scripts/claude-code-session-resume.py",
        "convene": "harnesses/claude-code/plugins/convene/bin/convene",
    },
    "codex": {
        "codex-api-profile": "harnesses/codex/scripts/codex-api-profile.sh",
        "codex-code-session-resume": "harnesses/codex/scripts/codex-code-session-resume.py",
        "codex-tmux": "harnesses/codex/scripts/codex-tmux.py",
        "convene": "harnesses/claude-code/plugins/convene/bin/convene",
    },
}
CONVENE_SKILL = REPO / "harnesses/claude-code/plugins/convene/skills/convene"


def catalog(harness, components):
    """Map install-relative paths to authoritative source files; no examples."""
    result = {}
    for component in components:
        if component == "skills":
            if harness == "claude-code":
                result["skills/teach/SKILL.md"] = REPO / "harnesses/claude-code/skills/teach/SKILL.md"
                result["skills/teach/references/workflow.md"] = REPO / "skills/teach/SKILL.md"
                result["skills/whats-new/SKILL.md"] = REPO / "harnesses/claude-code/skills/whats-new/SKILL.md"
                result["skills/whats-new/references/workflow.md"] = REPO / "skills/whats-new/SKILL.md"
            else:
                result["skills/teach/SKILL.md"] = REPO / "skills/teach/SKILL.md"
                result["skills/teach/agents/openai.yaml"] = REPO / "harnesses/codex/skills/teach/agents/openai.yaml"
                # Codex skips a symlinked SKILL.md. Link the directory so
                # its regular entry point and reader procedure are discovered.
                result["skills/whats-new"] = REPO / "harnesses/codex/skills/whats-new"
                # The convene operator procedure is authored inside the plugin
                # (an installed plugin may not reach outside its root) and
                # linked as a directory: Codex follows directory symlinks but
                # its skill scan skips a symlinked SKILL.md. Keep the policy
                # and references beside the authoritative regular file.
                result["skills/convene"] = CONVENE_SKILL
        elif component == "profiles":
            if harness != "codex":
                raise ValueError(f"{component} is not available for {harness}")
            for name in ("subscription", "api"):
                filename = f"{name}.config.toml"
                result[filename] = REPO / "harnesses/codex/profiles" / filename
        elif component == "commands":
            for name, source in COMMANDS[harness].items():
                result[name] = REPO / source
        elif component in ("prompts", "instructions"):
            for source in (REPO / component).glob("*.md"):
                if source.name != "README.md":
                    result[f"{component}/{source.name}"] = source
        else:
            source_dir = REPO / "harnesses" / harness / component
            sources = sorted(p for p in source_dir.glob("*") if p.suffix in (".py", ".sh"))
            if not sources:
                raise ValueError(f"{component} is not available for {harness}")
            for source in sources:
                relative = source.name if component == "settings" else f"{component}/{source.name}"
                result[relative] = source
    return dict(sorted(result.items()))


@contextmanager
def parent_fd(root, relative, create=False):
    """Traverse beneath an explicit root without following parent symlinks."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in Path(relative).parts[:-1]:
            if create:
                try:
                    os.mkdir(part, dir_fd=descriptor)
                except FileExistsError:
                    pass  # The no-follow directory open below validates it.
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def link_status(root, relative, source):
    try:
        with parent_fd(root, relative) as descriptor:
            name = Path(relative).name
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(name, dir_fd=descriptor)
                actual = Path(os.path.abspath(root / Path(relative).parent / target))
                if actual == source:
                    return "present"
            return "conflict"
    except FileNotFoundError:
        return "install"


def install(root, links, apply=False):
    install_roots({root: links}, apply)


def install_roots(plans, apply=False):
    """Preflight and roll back one invocation across all installation roots."""
    statuses = {}
    entries = [(root, relative, source)
               for root, links in plans.items() for relative, source in links.items()]
    for root, relative, source in entries:
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"Destination must remain under the installation root: {relative}")
        if not (source.is_file() or source.is_dir()):
            raise ValueError(f"Missing source file or directory: {source}")
        statuses[root, relative] = link_status(root, relative, source)
        print(f"{statuses[root, relative]:8} {root / relative}")
    if "conflict" in statuses.values():
        raise ValueError("Existing files differ from the proposed links; back up and resolve conflicts first")
    if not apply:
        print("Dry run; add --apply to create these links.")
        return
    created = []
    try:
        for root, relative, source in entries:
            root.mkdir(parents=True, exist_ok=True)
            with parent_fd(root, relative, create=True) as descriptor:
                name = Path(relative).name
                try:
                    os.symlink(str(source), name, dir_fd=descriptor)
                except FileExistsError:
                    if link_status(root, relative, source) == "present":
                        continue
                    raise ValueError(f"Target changed during installation: {root / relative}")
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                created.append((os.dup(descriptor), name, info.st_ino))
    except Exception:
        for descriptor, name, inode in reversed(created):
            try:
                current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if current.st_ino == inode:
                    os.unlink(name, dir_fd=descriptor)
                else:
                    print(f"Rollback left a concurrently changed entry alone: {name}", file=sys.stderr)
            except FileNotFoundError:
                pass  # Another process already removed this link.
        raise
    finally:
        for descriptor, _, _ in created:
            os.close(descriptor)
    print(f"Installed {len(created)} link(s); existing matching links were unchanged.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", required=True, choices=("claude-code", "codex"))
    parser.add_argument("--scope", required=True, choices=("user", "project"))
    parser.add_argument("--project", type=Path, help="Project directory for project scope")
    parser.add_argument("--target", type=Path, help="Explicit installation root instead of the scope default")
    parser.add_argument("--component", required=True, action="append", choices=COMPONENTS)
    parser.add_argument("--apply", action="store_true", help="Create links; default is a dry run")
    args = parser.parse_args(argv)
    if args.project and args.scope != "project":
        parser.error("--project requires --scope project")
    if args.target and args.project:
        parser.error("Choose --target or --project")
    directory = ".claude" if args.harness == "claude-code" else ".agents"
    try:
        plans = {}
        for component in dict.fromkeys(args.component):
            links = catalog(args.harness, [component])
            if component == "profiles" and args.scope != "user":
                raise ValueError("Codex profiles require --scope user; project config cannot select providers")
            if component == "commands" and args.scope != "user":
                raise ValueError("Commands require --scope user; PATH is a property of the account, not a project")
            if args.target:
                target = args.target
            elif args.scope == "project":
                target = (args.project or Path.cwd()) / directory
            elif component == "profiles":
                target = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
            elif component == "commands":
                target = Path.home() / ".local/bin"
            elif args.harness == "claude-code":
                target = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / directory)
            else:
                target = Path.home() / directory
            plans.setdefault(target.expanduser().resolve(), {}).update(links)
        install_roots(plans, args.apply)
    except (OSError, ValueError) as error:
        print(f"Installation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
