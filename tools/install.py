#!/usr/bin/env python3
"""Install explicitly selected Agent Toolbox components as scoped symlinks."""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import sys


REPO = Path(__file__).resolve().parents[1]
COMPONENTS = ("skills", "scripts", "hooks", "settings", "prompts", "instructions")


def catalog(harness, components):
    """Map install-relative paths to authoritative source files; no examples."""
    result = {}
    for component in components:
        if component == "skills":
            if harness == "claude-code":
                result["skills/teach/SKILL.md"] = REPO / "harnesses/claude-code/skills/teach/SKILL.md"
                result["skills/teach/references/workflow.md"] = REPO / "skills/teach/SKILL.md"
            else:
                result["skills/teach/SKILL.md"] = REPO / "skills/teach/SKILL.md"
                result["skills/teach/agents/openai.yaml"] = REPO / "harnesses/codex/skills/teach/agents/openai.yaml"
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
    statuses = {}
    for relative, source in links.items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"Destination must remain under the installation root: {relative}")
        if not source.is_file():
            raise ValueError(f"Missing source file: {source}")
        statuses[relative] = link_status(root, relative, source)
        print(f"{statuses[relative]:8} {root / relative}")
    if "conflict" in statuses.values():
        raise ValueError("Existing files differ from the proposed links; back up and resolve conflicts first")
    if not apply:
        print("Dry run; add --apply to create these links.")
        return
    root.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for relative, source in links.items():
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
    if args.target:
        target = args.target
    elif args.scope == "project":
        target = (args.project or Path.cwd()) / directory
    elif args.harness == "claude-code":
        target = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / directory)
    else:
        target = Path.home() / directory
    try:
        install(target.expanduser().resolve(), catalog(args.harness, args.component), args.apply)
    except (OSError, ValueError) as error:
        print(f"Installation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
