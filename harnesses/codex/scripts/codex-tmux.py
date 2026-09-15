#!/usr/bin/env python3
"""Launch Codex with explicit billing and a two-row tmux status display (Linux)."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit("codex-tmux.py requires Python 3.11+; run it with a Python 3.11 or newer interpreter.")

HERE = Path(__file__).resolve()
HARNESS = HERE.parents[1]
sys.path.insert(0, str(HARNESS))
from _statusline import (
    Rollout, git_state, load_prices, memory_mb, open_rollouts, other_writers,
    render, safe_text,
)


API_HELPER = HERE.with_name("codex-api-profile.sh")
AUTH_VARIABLES = ("CODEX_API_KEY", "CODEX_OPENAI_API_KEY", "OPENAI_API_KEY")


def clean_environment(detach_tmux=True):
    env = os.environ.copy()
    names = (*AUTH_VARIABLES, "CODEX_THREAD_ID", "CODEX_SESSION_ID")
    if detach_tmux:
        names += ("TMUX", "TMUX_PANE")
    for name in names:
        env.pop(name, None)
    return env


def atomic_json(path, value):
    temporary = path.with_suffix(".new")
    with temporary.open("w") as stream:
        json.dump(value, stream)
        stream.write("\n")
    temporary.replace(path)


def private_directory(path):
    path = Path(path).expanduser().absolute()
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("runtime directory must be owned by you with mode 0700 and must not be a symlink")
    if path.parent.resolve() != (Path.home() / "tmp").resolve() or not path.name.startswith("codex-tmux-"):
        raise ValueError("runtime directory must be a codex-tmux-* directory under ~/tmp")
    return path


def tmux(directory, *args, check=True):
    result = subprocess.run(["tmux", "-S", str(directory / "socket"), *args],
                            capture_output=True, text=True, timeout=5, env=clean_environment())
    if check and result.returncode:
        raise ValueError("tmux: " + safe_text(result.stderr.strip()))
    return result


def inspect_arguments(arguments):
    """Leave native parsing to Codex, but refuse competing backend/remote selection."""
    configs = {}
    takes_value = {"-m", "--model", "-C", "--cd", "-s", "--sandbox", "-a", "--ask-for-approval",
                   "--add-dir", "-i", "--image", "--enable", "--disable"}
    forbidden = {"--profile", "-p", "--remote", "--remote-auth-token-env", "--oss", "--local-provider"}
    commands = {"exec", "e", "review", "login", "logout", "mcp", "plugin", "app-server", "remote-control",
                "completion", "update", "doctor", "sandbox", "debug", "apply", "queue", "archive", "delete",
                "migrate-rollouts", "unarchive", "cloud", "exec-server", "features", "agents"}
    i = 0
    while i < len(arguments):
        arg = arguments[i]
        if arg == "--":
            break
        option = arg.split("=", 1)[0]
        if option in forbidden or (arg.startswith("-p") and not arg.startswith("--")):
            raise ValueError(f"{option} conflicts with wrapper billing/session ownership; use --backend api or subscription")
        config = None
        if arg in ("-c", "--config"):
            i += 1
            if i == len(arguments):
                raise ValueError(f"{arg} requires key=value")
            config = arguments[i]
        elif arg.startswith("--config="):
            config = arg[len("--config="):]
        elif arg.startswith("-c") and not arg.startswith("--"):
            config = arg[2:].removeprefix("=")
        if config is not None:
            key, separator, value = config.partition("=")
            if not separator:
                raise ValueError("--config requires key=value")
            try:
                parsed = tomllib.loads(config)
            except tomllib.TOMLDecodeError:
                # Codex accepts an unquoted string when the value is not TOML.
                parsed = tomllib.loads(key + "=" + json.dumps(value))
            if any(key in parsed for key in ("model_provider", "model_providers", "forced_login_method", "profile", "profiles")):
                raise ValueError("authentication/provider overrides conflict with --backend")
            configs.update(parsed)
        elif option in takes_value and "=" not in arg:
            i += 1
        elif arg in commands:
            raise ValueError(f"codex {arg} is not an interactive session; use codex or codex-api-profile.sh directly")
        i += 1
    return configs


def launch_spec(backend, arguments, codex_home):
    overrides = inspect_arguments(arguments)
    profile = codex_home / f"{backend}.config.toml"
    if not profile.is_file():
        raise ValueError(f"missing {profile}; run python3 {HARNESS.parents[1] / 'tools/install.py'} "
                         "--harness codex --scope user --component profiles --apply")
    selected = tomllib.loads(profile.read_text())
    expected = tomllib.loads((HARNESS / "profiles" / profile.name).read_text())

    def matches(actual, required):
        return isinstance(actual, dict) and all(
            matches(actual.get(k), v) if isinstance(v, dict) else actual.get(k) == v
            for k, v in required.items())

    if not matches(selected, expected):
        raise ValueError(f"{profile} differs from the toolbox authentication profile; review it before using this launcher")
    config_file = codex_home / "config.toml"
    config = tomllib.loads(config_file.read_text()) if config_file.exists() else {}
    tier = overrides.get("service_tier", selected.get("service_tier", config.get("service_tier", "default")))
    if not isinstance(tier, str):
        raise ValueError("service_tier must be a string")
    # The explicit config override also prevents 0.154.0 from reusing a shared
    # app-server daemon. The owned process must hold its own rollout descriptors.
    command = ["codex", "--profile", backend, "-c", "tui.status_line=[]",
               "-c", "service_tier=" + json.dumps(tier), *arguments]
    if backend == "api":
        command = [str(API_HELPER), "--", *command[1:]]
    return {"command": command, "backend": backend, "tier": tier, "codex_home": str(codex_home)}


def require_linux():
    if platform.system() != "Linux":
        raise ValueError("codex-tmux.py currently requires Linux /proc. On macOS run "
                         "codex --profile subscription, or codex-api-profile.sh for the security keychain instructions")


def capture_exit_output(directory):
    # Child exit guarantees its writes finished, but tmux may still have bytes
    # queued to read. A private pane-title marker acknowledges that tmux parsed
    # those bytes before we capture. set-titles is off on this private server.
    marker = "codex-tmux-exit-" + uuid.uuid4().hex
    sys.stdout.write(f"\x1b]2;{marker}\x07")
    sys.stdout.flush()
    deadline = time.monotonic() + 5
    while tmux(directory, "display-message", "-p", "-t", "codex:0", "#{pane_title}").stdout.strip() != marker:
        if time.monotonic() > deadline:
            raise ValueError("tmux did not finish reading the exit output within 5 seconds")
        time.sleep(.01)
    # Recent history retains exit messages scrolled off a short terminal; -J
    # rejoins wrapped commands so the resume hint remains copyable.
    return tmux(directory, "capture-pane", "-p", "-J", "-S", "-100", "-t", "codex:0").stdout.rstrip()


def run_pane(directory):
    directory = private_directory(directory)
    spec = json.loads((directory / "launch.json").read_text())
    deadline = time.monotonic() + 15
    while not (directory / "ready").exists():
        if time.monotonic() > deadline:
            raise ValueError("tmux setup did not finish within 15 seconds")
        time.sleep(0.05)
    prices = load_prices()
    started = datetime.now(timezone.utc).timestamp()
    child_env = clean_environment(detach_tmux=False)
    child_env["CODEX_HOME"] = spec["codex_home"]
    child = subprocess.Popen(spec["command"], env=child_env)
    # Leave terminal-generated Ctrl-C to Codex. The runner must remain alive to
    # reap it, publish its exit code, and keep updating the display.
    previous = {}
    previous[signal.SIGINT] = signal.signal(signal.SIGINT, lambda number, frame: None)
    for signum in (signal.SIGTERM, signal.SIGHUP):
        previous[signum] = signal.signal(signum, lambda number, frame: child.send_signal(number) if child.poll() is None else None)
    reader = None
    last_rows = None
    last_error = None
    ownership_error = None
    try:
        while child.poll() is None:
            data = {"cwd": spec["cwd"], "backend": spec["backend"], "cost": "0"}
            try:
                candidates = open_rollouts(child.pid, spec["codex_home"])
                if len(candidates) > 1:
                    raise ValueError("multiple main threads are open; restart the wrapper for an unambiguous display")
                if candidates:
                    path, (owner, thread_id) = next(iter(candidates.items()))
                    if other_writers(path, {owner}):
                        ownership_error = "another process is writing this conversation; close the duplicate and restart the wrapper"
                    if ownership_error:
                        raise ValueError(ownership_error)
                    if reader is None or reader.path != path:
                        reader = Rollout(path, thread_id, started, spec["backend"], spec["tier"], prices)
                    reader.poll()
                    data.update(reader.snapshot())
                    data["cwd"] = data.get("cwd") or spec["cwd"]
                    data["memory"] = memory_mb(owner)
                else:
                    data["notice"] = "waiting for local transcript"
                data["branch"] = git_state(data["cwd"])
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                data = {"backend": spec["backend"], "error": safe_text(str(error)), "cost": None}
            error = data.get("error") or data.get("cost_error")
            if error and error != last_error:
                with (directory / "errors.log").open("a") as stream:
                    stream.write(f"{datetime.now(timezone.utc).isoformat()} {error}\n")
            last_error = error
            atomic_json(directory / "status.json", data)
            size = int(tmux(directory, "display-message", "-p", "-t", "codex:0", "#{window_width}").stdout.strip())
            try:
                rows = render(data, size)
            except (ValueError, TypeError, KeyError, OverflowError) as error:
                data = {"backend": spec["backend"], "error": "invalid telemetry: " + safe_text(str(error)), "cost": None}
                atomic_json(directory / "status.json", data)
                rows = render(data, size)
            if rows != last_rows:
                for i, row in enumerate(rows):
                    tmux(directory, "set-option", "-g", f"status-format[{i}]", row)
                last_rows = rows
            time.sleep(1)
        code = child.wait()
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        code = child.returncode
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    code = code if code >= 0 else 128 - code
    # Save the final screen before this pane exits and the private server dies.
    output = capture_exit_output(directory)
    if code and not output:
        output = f"Codex exited with status {code}."
    (directory / ("failure.txt" if code else "output.txt")).write_text(output)
    atomic_json(directory / "exit.json", {"code": code})
    return code


def attach(directory):
    directory = private_directory(directory)
    if not (directory / "exit.json").exists():
        result = subprocess.run(["tmux", "-S", str(directory / "socket"), "attach-session", "-t", "codex"],
                                env=clean_environment())
        if result.returncode and not (directory / "exit.json").exists():
            raise ValueError(f"could not attach; inspect {directory} (no files were removed)")
    if (directory / "exit.json").exists():
        code = json.loads((directory / "exit.json").read_text())["code"]
        output = directory / ("failure.txt" if code else "output.txt")
        if output.exists():
            message = output.read_text()
        else:
            message = f"Codex exited with status {code}." if code else ""
        if message:
            print("\n".join(safe_text(line) for line in message.splitlines()), file=sys.stderr if code else sys.stdout)
        shutil.rmtree(directory)
        return code
    print("Session detached. Reattach with:")
    print(shlex.join([str(HERE), "--attach", str(directory)]))
    return 0


def launch(spec):
    dependencies = {"tmux": "sudo dnf install tmux (Fedora) or sudo apt install tmux (Debian/Ubuntu)",
                    "git": "sudo dnf install git (Fedora) or sudo apt install git (Debian/Ubuntu)",
                    "codex": "npm install -g @openai/codex"}
    for program, install in dependencies.items():
        if shutil.which(program) is None:
            raise ValueError(f"{program} is missing on Linux; install it with {install}")
    version = subprocess.run(["tmux", "-V"], capture_output=True, text=True, check=True, timeout=5)
    match = re.search(r"tmux (\d+)\.(\d+)", version.stdout)
    if not match or tuple(map(int, match.groups())) < (3, 2):
        raise ValueError("tmux 3.2 or newer is required; on Fedora run sudo dnf upgrade tmux")
    load_prices()  # Fail before opening a terminal if bundled rates are invalid.
    if spec["backend"] == "api":
        result = subprocess.run([str(API_HELPER), "--status"], capture_output=True, text=True, env=clean_environment())
        if result.returncode:
            raise ValueError("API key unavailable. Run codex-tmux.py --store-key. " + safe_text(result.stderr.strip()))
    root = Path.home() / "tmp"
    root.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="codex-tmux-", dir=root))
    os.chmod(directory, 0o700)
    # AF_UNIX sun_path is 108 bytes on Linux, including its trailing NUL.
    if len(os.fsencode(directory / "socket")) >= 108:
        directory.rmdir()
        raise ValueError("~/tmp path is too long for a Linux tmux socket (maximum 107 bytes)")
    spec = {**spec, "cwd": str(Path.cwd())}
    atomic_json(directory / "launch.json", spec)
    size = shutil.get_terminal_size((160, 40))
    initial_rows = render({"cwd": spec["cwd"], "backend": spec["backend"], "notice": "starting"}, size.columns)
    try:
        tmux(directory, "-f", "/dev/null", "new-session", "-d", "-s", "codex",
             "-x", str(size.columns), "-y", str(size.lines), "-c", spec["cwd"],
             sys.executable, str(HERE), "_run", str(directory))
        for option, value in (("status", "2"), ("status-position", "bottom"),
                              ("status-style", "bg=default,fg=default"), ("status-interval", "1"),
                              ("status-format[0]", initial_rows[0]), ("status-format[1]", initial_rows[1]),
                              ("set-titles", "off"), ("allow-rename", "off"), ("update-environment", "")):
            tmux(directory, "set-option", "-g", option, value)
        (directory / "ready").touch()
    except BaseException:
        tmux(directory, "kill-server", check=False)
        shutil.rmtree(directory)
        raise
    return attach(directory)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["_run"]:
        try:
            return run_pane(arguments[1])
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            print("codex-tmux: " + safe_text(str(error)), file=sys.stderr)
            if len(arguments) == 2:
                directory = private_directory(arguments[1])
                (directory / "failure.txt").write_text("codex-tmux: " + safe_text(str(error)))
                atomic_json(directory / "exit.json", {"code": 1})
            return 1
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  codex-tmux.py
  codex-tmux.py --backend api
  codex-tmux.py --backend api -- resume --last
  codex-tmux.py --backend api -- -c service_tier=priority

Pass native interactive arguments after --, including resume and fork.

Requirements:
  Linux with readable /proc, tmux 3.2+, Python 3.11+, Git, Codex CLI,
  and the toolbox Codex authentication profiles.

Sessions and keys:
  Each launch uses a private tmux server under ~/tmp.
  Ctrl-b d detaches. Use the printed --attach command to reconnect.
  On exit, the final pane output is replayed in your calling terminal.
  API mode uses the login keyring through codex-api-profile.sh.

Service tier and cost:
  The tier comes from the selected profile/base config (Standard if unset).
  Override it with -- -c service_tier=default, priority, or flex.
  Cost estimates cover this main thread since launch.
  Delegated agents and tool fees are excluded.
""")
    parser.add_argument("--backend", choices=("subscription", "api"), default="subscription",
                        help="billing backend (default: subscription; never falls back to API)")
    parser.add_argument("--attach", type=Path, help="reattach to a private runtime directory printed on detach")
    keys = parser.add_mutually_exclusive_group()
    keys.add_argument("--store-key", action="store_true", help="store the API key using the existing keyring helper")
    keys.add_argument("--key-status", action="store_true", help="report whether the API key is stored")
    keys.add_argument("--clear-key", action="store_true", help="remove the API key from the keyring")
    native = []
    if "--" in arguments:
        boundary = arguments.index("--")
        arguments, native = arguments[:boundary], arguments[boundary + 1:]
    args = parser.parse_args(arguments)
    try:
        key_operation = "--store" if args.store_key else "--status" if args.key_status else "--clear" if args.clear_key else None
        if key_operation:
            if native or args.attach:
                raise ValueError("keyring operations cannot be combined with launch or attach arguments")
            return subprocess.call([str(API_HELPER), key_operation], env=clean_environment())
        require_linux()
        if args.attach and (native or any(arg == "--backend" or arg.startswith("--backend=") for arg in arguments)):
            raise ValueError("--attach reuses the existing backend and arguments; start a new launcher to change them")
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ValueError("run this launcher in a terminal; use --help or --key-status from an agent")
        if args.attach:
            return attach(args.attach)
        codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()
        return launch(launch_spec(args.backend, native, codex_home))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print("codex-tmux: " + safe_text(str(error)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
