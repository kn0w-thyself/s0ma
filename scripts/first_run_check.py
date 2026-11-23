#!/usr/bin/env python3
"""The first-run check: the Claude Code plugin on a machine that has just met it.

``.github/workflows/first-run.yml`` runs this on Linux, macOS and Windows, in
two legs each. It is standard library only, so the uv-absent leg can run it
with the runner's own Python and nothing else.

``uv-absent``
    Proves uv is nowhere the plugin or the launcher looks (``--hide-uv`` moves
    a runner image's uv out of the way first, and proves it again). Then runs
    the session-start hook's command exactly as ``hooks/hooks.json`` writes
    it, the way Claude Code runs a shell-form hook, and drives the server
    command with a small MCP client, against the plugin folder and against the
    tree ``scripts/export_claude_marketplace.py`` writes. Then shows the
    checks bite: a copy with the message removed and a copy with a broken
    stand-in must each fail them.

``uv-present``
    With uv, a fresh ``S0MA_HOME`` and no license key: the hook and the server
    with nothing installed, then a keyless install from wheels built here at a
    version no package index can hold, and the real server's 15 tools through
    the plugin's server command. Once s0ma is installed the hook shows the
    person nothing and gives Claude the standing note, and in a project whose
    ``.s0ma/preferences.json`` turns s0ma off it says the one off line and
    nothing else. Imports the end-to-end test's helpers, so run it with
    ``uv run python``.

``e2e``
    Runs ``integrations/launcher/tests/test_e2e_real_wheels.py`` with
    ``S0MA_E2E=1`` and fails if any case skips.

The real Claude Code (``claude plugin validate`` and ``claude --plugin-dir
<dir> mcp list``) runs only when ``--claude <command>`` is given, and the
workflow is the only thing that gives it. ``--no-claude`` says out loud that
those checks were left out. One of the two is required, so nothing is left out
in silence.

Every check fails loudly; nothing here skips. Every command is printed with
what it returned, raw, and each verdict is one ``RESULT |`` line.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "integrations" / "claude" / "plugin"
LAUNCHER_FILE = ROOT / "integrations" / "launcher" / "s0ma_launch.py"
LAUNCHER_TESTS = ROOT / "integrations" / "launcher" / "tests"
E2E_TEST = LAUNCHER_TESTS / "test_e2e_real_wheels.py"
EXPORT_SCRIPT = ROOT / "scripts" / "export_claude_marketplace.py"
SURFACE_SNAPSHOT = (
    ROOT / "packages" / "s0ma-mcp" / "tests" / "snapshots" / "mcp_surface.json"
)

WINDOWS = os.name == "nt"

#: How ``claude mcp list`` names the plugin's server: plugin name, server name.
SERVER_LABEL = "plugin:s0ma:s0ma:"

#: The files the export must leave executable.
EXECUTABLE_FILES = ("bin/s0ma", "bin/s0ma-launch", "scripts/s0ma-serve")

#: Where a hidden uv goes: beside itself, under a name nothing looks for.
HIDDEN_SUFFIX = ".hidden-by-first-run-check"

#: Seconds one command, or one MCP answer, may take.
TIMEOUT = 300.0

#: The protocol version Claude Code asks for first.
PROTOCOL = "2025-11-25"

#: Kept out of every child: a key, a sign-in, a virtual environment, s0ma's own
#: settings. Nothing in this check signs in to anything.
DROPPED_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "VIRTUAL_ENV",
    "UV_RUN_RECURSION_DEPTH",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_PLUGIN_ROOT",
    "CLAUDE_PLUGIN_DATA",
)


class CheckFailed(Exception):
    """One check did not hold. The message says what was expected and what came."""


# ---------------------------------------------------------------------------
# Saying what happened.
# ---------------------------------------------------------------------------


def say(text: str = "") -> None:
    print(text, flush=True)


def banner(text: str) -> None:
    say("")
    say("=" * 72)
    say(text)
    say("=" * 72)


class Results:
    """The ``RESULT |`` lines, printed as they come and again at the end."""

    def __init__(self, leg: str) -> None:
        self.leg = leg
        self.lines: list[str] = []

    def add(self, check: str, raw: str) -> None:
        line = f"RESULT | {self.leg} | {sys.platform} | {check} | {raw}"
        self.lines.append(line)
        say(line)

    def summary(self) -> None:
        banner(f"SUMMARY {self.leg} on {sys.platform}")
        for line in self.lines:
            say(line)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


# ---------------------------------------------------------------------------
# Running things.
# ---------------------------------------------------------------------------


class Ran:
    def __init__(self, code: int, stdout: str, stderr: str) -> None:
        self.code = code
        self.stdout = stdout
        self.stderr = stderr


def decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def run(
    command: list[str] | str,
    env: dict[str, str],
    cwd: Path,
    *,
    stdin: str = "",
    timeout: float = TIMEOUT,
) -> Ran:
    """Run one command, print it and everything it returned, raw."""
    say("")
    say(
        f"$ {command if isinstance(command, str) else subprocess.list2cmdline(command)}"
    )
    say(f"  (cwd {cwd})")
    try:
        done = subprocess.run(  # noqa: S603 - fixed, local commands
            command,
            input=stdin.encode("utf-8"),
            capture_output=True,
            env=env,
            cwd=str(cwd),
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CheckFailed(f"{command!r} did not finish in {timeout:.0f}s") from exc
    except OSError as exc:
        raise CheckFailed(f"{command!r} could not be started: {exc}") from exc
    ran = Ran(done.returncode, decode(done.stdout), decode(done.stderr))
    say(f"[exit {ran.code}]")
    say(f"[stdout, {len(done.stdout)} bytes]")
    if ran.stdout:
        say(ran.stdout.rstrip("\n"))
    say(f"[stderr, {len(done.stderr)} bytes]")
    if ran.stderr:
        say(ran.stderr.rstrip("\n"))
    return ran


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """This process's environment, less anything that would sign in or steer s0ma."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in DROPPED_VARIABLES and not key.upper().startswith("S0MA_")
    }
    # A uv run's own virtual environment is not part of the machine under test.
    venv_bin = Path(sys.prefix) / ("Scripts" if WINDOWS else "bin")
    if sys.prefix != sys.base_prefix:
        env["PATH"] = os.pathsep.join(
            entry
            for entry in env.get("PATH", "").split(os.pathsep)
            if not same_dir(entry, venv_bin)
        )
    if extra:
        env.update(extra)
    return env


def same_dir(entry: str, directory: Path) -> bool:
    try:
        return bool(entry) and Path(entry).resolve() == directory.resolve()
    except OSError:
        return False


def load_launcher() -> ModuleType:
    """The launcher, imported from this tree, for its names and its uv places."""
    spec = importlib.util.spec_from_file_location(
        "s0ma_launch_first_run", LAUNCHER_FILE
    )
    if spec is None or spec.loader is None:
        raise CheckFailed(f"could not load the launcher from {LAUNCHER_FILE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def the_message(plugin_dir: Path = PLUGIN_DIR) -> str:
    """The one not-set-up sentence, from the one file that holds it."""
    text = (plugin_dir / "scripts" / "not-set-up.txt").read_text(encoding="utf-8")
    lines = text.splitlines()
    expect(
        len(lines) == 1 and lines[0].strip() != "",
        f"not-set-up.txt is not one line: {text!r}",
    )
    return lines[0]


# ---------------------------------------------------------------------------
# Is there a uv here?
# ---------------------------------------------------------------------------


def uv_places(launcher: ModuleType, env: dict[str, str]) -> list[Path]:
    """Every uv this machine offers: on the PATH, and where the launcher looks."""
    found: list[Path] = []
    names = ("uv.exe", "uv") if WINDOWS else ("uv",)
    for entry in env.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        for name in names:
            candidate = Path(entry) / name
            if candidate.is_file():
                found.append(candidate)
    for candidate in launcher.uv_candidates(env):
        if Path(candidate).exists():
            found.append(Path(candidate))
    unique: list[Path] = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return unique


def git_bash() -> Path:
    """Git Bash, found the way Claude Code finds it: from git on the PATH."""
    git = shutil.which("git")
    roots: list[Path] = []
    if git:
        roots.append(Path(git).resolve().parent.parent)
    roots.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git")
    for root in roots:
        candidate = root / "bin" / "bash.exe"
        if candidate.is_file():
            return candidate
    raise CheckFailed(
        "no Git Bash on this machine, and Claude Code runs hooks with it here"
    )


def git_bash_uv(env: dict[str, str], cwd: Path) -> list[str]:
    """What Git Bash sees as uv, in the POSIX places the hook also looks."""
    script = (
        'command -v uv; for p in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" '
        '/opt/homebrew/bin/uv /usr/local/bin/uv; do [ -e "$p" ] && echo "$p"; done; exit 0'
    )
    ran = run([str(git_bash()), "-c", script], env, cwd)
    return [line for line in ran.stdout.splitlines() if line.strip()]


def hide(path: Path) -> None:
    """Move one uv out of view. The runner is thrown away after the job."""
    target = path.with_name(path.name + HIDDEN_SUFFIX)
    say(f"hiding {path} as {target.name}")
    try:
        path.rename(target)
        return
    except PermissionError:
        if WINDOWS:
            raise CheckFailed(f"could not move {path} out of view") from None
    done = subprocess.run(["sudo", "-n", "mv", str(path), str(target)], check=False)  # noqa: S603, S607
    expect(done.returncode == 0, f"could not move {path} out of view, even with sudo")


def prove_uv_absent(
    launcher: ModuleType, results: Results, cwd: Path, *, hide_uv: bool
) -> None:
    banner("Is there a uv anywhere the plugin or the launcher looks?")
    env = child_env()
    for attempt in ("first look", "after hiding"):
        places = uv_places(launcher, env)
        candidates = [str(c) for c in launcher.uv_candidates(env)]
        say(f"PATH: {env.get('PATH', '')}")
        say(f"the launcher's uv_candidates: {candidates}")
        say(f"uv found ({attempt}): {[str(p) for p in places]}")
        if WINDOWS:
            seen = git_bash_uv(env, cwd)
            say(f"uv Git Bash sees ({attempt}): {seen}")
            places += [Path(p) for p in seen if Path(p) not in places]
        if not places:
            results.add(
                "uv absent",
                f"no uv on the PATH or in {len(candidates)} launcher places ({attempt})",
            )
            return
        if not hide_uv or attempt == "after hiding":
            raise CheckFailed(
                f"uv is on this machine and was not hidden: {[str(p) for p in places]}"
            )
        for place in places:
            hide(place if place.is_absolute() else Path(place))
    raise CheckFailed("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# The hook.
# ---------------------------------------------------------------------------


def plugin_root_text(plugin_dir: Path) -> str:
    """The plugin root as Claude Code fills it in: forward slashes on Windows."""
    return plugin_dir.resolve().as_posix() if WINDOWS else str(plugin_dir.resolve())


def hook_command(plugin_dir: Path) -> str:
    """The one SessionStart command in hooks.json, with the plugin root filled in."""
    hooks = json.loads(
        (plugin_dir / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )
    entries = hooks["hooks"]["SessionStart"]
    commands = [
        h for entry in entries for h in entry["hooks"] if h.get("type") == "command"
    ]
    expect(
        len(commands) == 1, f"expected one SessionStart command hook, found {commands}"
    )
    return str(commands[0]["command"]).replace(
        "${CLAUDE_PLUGIN_ROOT}", plugin_root_text(plugin_dir)
    )


def run_hook(plugin_dir: Path, env: dict[str, str], project: Path) -> Ran:
    """Run the hook the way Claude Code runs a shell-form hook."""
    command = hook_command(plugin_dir)
    shell = [str(git_bash()), "-c"] if WINDOWS else ["/bin/sh", "-c"]
    hook_env = dict(env)
    hook_env["CLAUDE_PLUGIN_ROOT"] = plugin_root_text(plugin_dir)
    hook_env["CLAUDE_PROJECT_DIR"] = str(project)
    payload = json.dumps(
        {
            "session_id": "first-run-check",
            "transcript_path": str(project / "transcript.jsonl"),
            "cwd": str(project),
            "hook_event_name": "SessionStart",
            "source": "startup",
        }
    )
    return run([*shell, command], hook_env, project, stdin=payload, timeout=60)


def check_hook_not_set_up(
    plugin_dir: Path, message: str, env: dict[str, str], project: Path
) -> str:
    ran = run_hook(plugin_dir, env, project)
    expect(ran.code == 0, f"the hook exited {ran.code}, not 0")
    expect(ran.stderr == "", f"the hook wrote to stderr: {ran.stderr!r}")
    expect(
        ran.stdout == message + "\n",
        f"the hook printed {ran.stdout!r}, not the message",
    )
    return f"exit 0, stderr empty, stdout is the not-set-up message ({len(ran.stdout)} bytes)"


def hook_line(ran: Ran) -> dict[str, Any]:
    """The hook's one line of JSON, after exit 0 and an empty stderr."""
    expect(ran.code == 0, f"the hook exited {ran.code}, not 0")
    expect(ran.stderr == "", f"the hook wrote to stderr: {ran.stderr!r}")
    lines = ran.stdout.splitlines()
    expect(
        len(lines) == 1, f"the hook printed {len(lines)} lines, not one: {ran.stdout!r}"
    )
    expect(lines[0].isascii(), f"the hook's line is not plain ASCII: {lines[0]!r}")
    try:
        hint = json.loads(lines[0])
    except ValueError as exc:
        raise CheckFailed(f"the hook's line is not JSON: {lines[0]!r}") from exc
    expect(isinstance(hint, dict), f"the hook's line is not an object: {lines[0]!r}")
    return dict(hint)


def check_hook_installed(ran: Ran, launcher: ModuleType) -> str:
    """With s0ma installed: nothing for the person, the standing note for Claude."""
    hint = hook_line(ran)
    expect(
        "systemMessage" not in hint,
        f"the hook showed the person something: {hint.get('systemMessage')!r}",
    )
    extra = hint.get("hookSpecificOutput")
    expect(isinstance(extra, dict), f"no context for Claude: {hint!r}")
    assert isinstance(extra, dict)
    expect(
        extra.get("hookEventName") == "SessionStart",
        f"the context names the event {extra.get('hookEventName')!r}",
    )
    context = str(extra.get("additionalContext", ""))
    expect(
        context.startswith(launcher.NOTE_PURPOSE),
        f"the context is not the standing note: {context!r}",
    )
    expect(
        len(context) <= launcher.NOTE_MAX_CHARS,
        f"the standing note is {len(context)} characters, over {launcher.NOTE_MAX_CHARS}",
    )
    return (
        "exit 0, stderr empty, no systemMessage, the standing note in "
        f"additionalContext ({len(context)} characters)"
    )


def check_hook_off(ran: Ran, launcher: ModuleType) -> str:
    """With s0ma off in the project: the one off line for Claude, nothing else."""
    hint = hook_line(ran)
    expected = {
        "hookSpecificOutput": {
            "additionalContext": launcher.HINT_OFF_HERE,
            "hookEventName": "SessionStart",
        }
    }
    expect(hint == expected, f"the hook did not say only the off line: {hint!r}")
    return "exit 0, stderr empty, no systemMessage, additionalContext is the off line"


# ---------------------------------------------------------------------------
# A small MCP client, sending what Claude Code sends.
# ---------------------------------------------------------------------------


def server_command(plugin_dir: Path) -> list[str] | str:
    """The server command from .mcp.json, started as Claude Code starts it."""
    config = json.loads((plugin_dir / ".mcp.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["s0ma"]
    command = str(server["command"]).replace(
        "${CLAUDE_PLUGIN_ROOT}", plugin_root_text(plugin_dir)
    )
    args = [str(a) for a in server.get("args", [])]
    expect(
        args == [],
        f"the server command has arguments this client does not pass: {args}",
    )
    if WINDOWS:
        # cmd.exe finds the .cmd beside a command path with no extension.
        return f'cmd.exe /d /s /c ""{command}""'
    return [command]


class McpSession:
    """One server process, spoken to one JSON line at a time, every read bounded."""

    def __init__(
        self, command: list[str] | str, env: dict[str, str], cwd: Path
    ) -> None:
        say("")
        say(
            f"$ {command if isinstance(command, str) else subprocess.list2cmdline(command)}   (MCP over stdio)"
        )
        self.next_id = 0
        try:
            self.process = subprocess.Popen(  # noqa: S603 - a fixed, local command
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=str(cwd),
            )
        except OSError as exc:
            raise CheckFailed(
                f"the server command could not be started: {exc}"
            ) from exc
        self.lines: queue.Queue[bytes | None] = queue.Queue()
        self.errors: list[bytes] = []
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read_out(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _read_err(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self.errors.append(line)

    def stderr_text(self) -> str:
        return decode(b"".join(self.errors))

    def send(self, message: dict[str, Any]) -> None:
        text = json.dumps(message, separators=(",", ":"))
        say(f">> {text}")
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(text.encode("utf-8") + b"\n")
            self.process.stdin.flush()
        except OSError as exc:
            raise CheckFailed(
                f"the server stopped reading: {exc}; stderr: {self.stderr_text()!r}"
            ) from exc

    def receive(self, timeout: float = TIMEOUT) -> dict[str, Any]:
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            raise CheckFailed(
                f"the server said nothing for {timeout:.0f}s; stderr: {self.stderr_text()!r}"
            ) from None
        if line is None:
            raise CheckFailed(
                f"the server closed its output before answering; stderr: {self.stderr_text()!r}"
            )
        text = decode(line).rstrip("\r\n")
        say(f"<< {text}")
        try:
            parsed = json.loads(text)
        except ValueError:
            raise CheckFailed(
                f"the server wrote something that is not JSON on stdout: {text!r}"
            ) from None
        expect(
            isinstance(parsed, dict), f"the server's answer is not an object: {text!r}"
        )
        answer: dict[str, Any] = parsed
        return answer

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        ident = self.next_id
        self.next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": ident, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        answer = self.receive()
        expect(
            answer.get("id") == ident,
            f"asked with id {ident}, answered with {answer.get('id')!r}",
        )
        return answer

    def initialize(self) -> dict[str, Any]:
        answer = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"roots": {}, "elicitation": {}},
                "clientInfo": {"name": "claude-code", "version": "first-run-check"},
            },
        )
        expect("result" in answer, f"initialize was refused: {answer}")
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        result: dict[str, Any] = answer["result"]
        return result

    def close(self) -> int:
        """Close stdin as a host does, and wait for the server to end."""
        assert self.process.stdin is not None
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            code = self.process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.process.kill()
            raise CheckFailed(
                "the server did not end within 60s of stdin closing"
            ) from None
        time.sleep(0.2)
        say(f"[server exit {code}]")
        say(f"[server stderr] {self.stderr_text()!r}")
        return code

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=30)


def check_stand_in(
    plugin_dir: Path,
    message: str,
    launcher: ModuleType,
    env: dict[str, str],
    project: Path,
) -> str:
    """The server command with no uv: the stand-in's answers, one by one."""
    session = McpSession(server_command(plugin_dir), env, project)
    try:
        result = session.initialize()
        expect(
            result.get("protocolVersion") == PROTOCOL,
            f"protocolVersion {result.get('protocolVersion')!r}",
        )
        expect(
            result.get("serverInfo") == launcher.stub_server_info(),
            f"serverInfo {result.get('serverInfo')!r}",
        )
        expect(
            "tools" in result.get("capabilities", {}),
            f"capabilities {result.get('capabilities')!r}",
        )
        expect(
            result.get("instructions") == message,
            f"instructions {result.get('instructions')!r}",
        )
        ping = session.request("ping")
        expect(ping.get("result") == {}, f"ping answered {ping}")
        listed = session.request("tools/list")
        expect(
            listed.get("result", {}).get("tools") == [launcher.stub_tool()],
            f"tools/list answered {listed}",
        )
        called = session.request(
            "tools/call", {"name": launcher.STUB_TOOL_NAME, "arguments": {}}
        )
        expect(
            called.get("result")
            == {"content": [{"type": "text", "text": message}], "isError": False},
            f"tools/call answered {called}",
        )
        unknown = session.request("resources/list")
        expect(
            unknown.get("error", {}).get("code") == -32601,
            f"an unknown method answered {unknown}",
        )
        code = session.close()
        expect(code == 0, f"the stand-in exited {code} when stdin closed")
    finally:
        session.kill()
    return (
        f"stand-in {result['serverInfo']['name']} {result['serverInfo']['version']}: "
        f"initialize, ping, tools/list ({launcher.STUB_TOOL_NAME}), tools/call, -32601, exit 0"
    )


def check_real_server(
    plugin_dir: Path, version: str, names: list[str], env: dict[str, str], project: Path
) -> str:
    """The server command with s0ma installed: the real server and its tools."""
    session = McpSession(server_command(plugin_dir), env, project)
    try:
        result = session.initialize()
        info = result.get("serverInfo", {})
        expect(info.get("name") == "s0ma-authoring", f"serverInfo {info!r}")
        expect(
            info.get("version") == version,
            f"serverInfo version {info.get('version')!r}, not {version}",
        )
        listed = session.request("tools/list")
        tools = sorted(
            str(t["name"]) for t in listed.get("result", {}).get("tools", [])
        )
        say(f"tools: {tools}")
        expect(tools == names, f"tools/list gave {tools}, the snapshot pins {names}")
        expect(len(tools) == 15, f"{len(tools)} tools, not 15")
        code = session.close()
        expect(code == 0, f"the server exited {code} when stdin closed")
    finally:
        session.kill()
    return f"{info['name']} {info['version']}, tools/list returned {len(tools)} tools, the snapshot's"


# ---------------------------------------------------------------------------
# The real Claude Code. Only ever with --claude.
# ---------------------------------------------------------------------------


class Claude:
    def __init__(self, command: str, version: str, work: Path) -> None:
        found = shutil.which(command)
        if found is None:
            raise CheckFailed(f"--claude {command!r} is not on the PATH")
        self.path = found
        self.version = version
        self.work = work
        self.count = 0

    def env(self, base: dict[str, str]) -> dict[str, str]:
        """A fresh configuration each time, no key, no sign-in, no update check."""
        self.count += 1
        config = self.work / f"claude-config-{self.count}"
        config.mkdir(parents=True)
        env = dict(base)
        env["CLAUDE_CONFIG_DIR"] = str(config)
        env["DISABLE_AUTOUPDATER"] = "1"
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        return env

    def check_version(self, base: dict[str, str], cwd: Path, results: Results) -> None:
        ran = run([self.path, "--version"], self.env(base), cwd)
        expect(ran.code == 0, f"claude --version exited {ran.code}")
        expect(
            ran.stdout.strip().startswith(self.version + " "),
            f"claude is {ran.stdout.strip()!r}, not {self.version}",
        )
        results.add("claude --version", ran.stdout.strip())

    def validate(self, plugin_dir: Path, base: dict[str, str], cwd: Path) -> str:
        ran = run(
            [self.path, "plugin", "validate", str(plugin_dir)], self.env(base), cwd
        )
        expect(ran.code == 0, f"claude plugin validate exited {ran.code}")
        lines = [
            line.strip()
            for line in (ran.stdout + ran.stderr).splitlines()
            if line.strip()
        ]
        verdict = [line for line in lines if "Validation passed" in line]
        expect(bool(verdict), "claude plugin validate did not say it passed")
        return verdict[-1]

    def mcp_list_line(self, plugin_dir: Path, base: dict[str, str], cwd: Path) -> str:
        ran = run(
            [self.path, "--plugin-dir", str(plugin_dir), "mcp", "list"],
            self.env(base),
            cwd,
        )
        expect(ran.code == 0, f"claude mcp list exited {ran.code}")
        return server_line(ran.stdout + "\n" + ran.stderr)

    def connected(self, plugin_dir: Path, base: dict[str, str], cwd: Path) -> str:
        line = self.mcp_list_line(plugin_dir, base, cwd)
        expect(is_connected(line), f"the s0ma server is not connected: {line}")
        return line


def server_line(output: str) -> str:
    """The one line of ``claude mcp list`` about the plugin's s0ma server."""
    lines = [
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith(SERVER_LABEL)
    ]
    expect(
        len(lines) == 1,
        f"expected one {SERVER_LABEL} line in claude mcp list, found {lines}",
    )
    return lines[0]


def is_connected(line: str) -> bool:
    """Connected, in either set of marks (Windows without UTF-8 prints the others)."""
    status = line.rsplit(" - ", 1)[-1]
    return (
        "Connected" in status
        and "Failed" not in status
        and not any(m in status for m in ("✘", "×"))
    )


def without_git_shell(path: str, separator: str = os.pathsep) -> tuple[str, list[str]]:
    """*path* with every Git for Windows entry but ``Git\\cmd`` taken out."""
    kept: list[str] = []
    dropped: list[str] = []
    for entry in path.split(separator):
        low = entry.lower().replace("/", "\\").rstrip("\\") + "\\"
        if "\\git\\" in low and not low.endswith("\\git\\cmd\\"):
            dropped.append(entry)
        else:
            kept.append(entry)
    return separator.join(kept), dropped


def connected_everywhere(
    claude: Claude,
    label: str,
    plugin_dir: Path,
    base: dict[str, str],
    cwd: Path,
    results: Results,
) -> None:
    """``mcp list`` Connected; on Windows also with Git's shell off the PATH."""
    results.add(f"mcp list, {label}", claude.connected(plugin_dir, base, cwd))
    if WINDOWS:
        stripped = dict(base)
        stripped["PATH"], dropped = without_git_shell(base.get("PATH", ""))
        say(f"PATH entries taken out: {dropped}")
        expect(
            bool(dropped),
            "no Git for Windows entries were found on the PATH to take out",
        )
        for tool in ("sh", "bash", "sed", "git"):
            say(f"with them out, {tool} is {shutil.which(tool, path=stripped['PATH'])}")
        results.add(
            f"mcp list, {label}, Git cmd only",
            claude.connected(plugin_dir, stripped, cwd),
        )


# ---------------------------------------------------------------------------
# The exported tree.
# ---------------------------------------------------------------------------


def path_without_claude(path: str) -> str:
    return os.pathsep.join(
        entry
        for entry in path.split(os.pathsep)
        if not shutil.which("claude", path=entry)
    )


def export_tree(
    work: Path,
    env: dict[str, str],
    results: Results,
    *,
    with_claude: bool,
    from_tar: Path | None = None,
) -> Path:
    """Write the export, or unpack one, and prove its executable bits came through.

    The export needs the workspace to check the plugin's skills against, so a
    leg with no uv is handed the export as a tar file another job wrote with
    ``uv run``; a tar file keeps the modes the export set.
    """
    banner("The tree scripts/export_claude_marketplace.py writes")
    out = work / "export"
    if from_tar is not None:
        say(f"unpacking the export from {from_tar}")
        expect(from_tar.is_file(), f"{from_tar} is not there")
        with tarfile.open(from_tar) as archive:
            archive.extractall(out, filter="data")
        for entry in sorted(out.rglob("*")):
            if entry.is_file():
                say(
                    f"  {entry.stat().st_mode & 0o777:04o}  {entry.relative_to(out).as_posix()}"
                )
    else:
        export_env = dict(env)
        if not with_claude:
            # The export runs claude plugin validate when it finds a claude.
            export_env["PATH"] = path_without_claude(env.get("PATH", ""))
        ran = run(
            [sys.executable, str(EXPORT_SCRIPT), "--out", str(out)], export_env, ROOT
        )
        expect(ran.code == 0, f"the export exited {ran.code}")
        if with_claude:
            expect(
                "the plugin: accepted." in ran.stdout,
                "the export did not report claude accepting the plugin",
            )
    plugin = out / "plugins" / "s0ma"
    manifest = json.loads((out / "EXPORT-MANIFEST.json").read_text(encoding="utf-8"))
    modes = {entry["path"]: entry["mode"] for entry in manifest["files"]}
    bits: list[str] = []
    for relative in EXECUTABLE_FILES:
        recorded = modes.get(f"plugins/s0ma/{relative}")
        expect(
            recorded == "0755",
            f"the export manifest records {relative} as {recorded!r}, not 0755",
        )
        if not WINDOWS:
            mode = (plugin / relative).stat().st_mode & 0o777
            expect(
                mode == 0o755, f"{relative} in the export has mode {mode:04o}, not 0755"
            )
            bits.append(f"{relative} {mode:04o}")
        else:
            bits.append(f"{relative} 0755 in the manifest")
    results.add("export executable bits", ", ".join(bits))
    return plugin


# ---------------------------------------------------------------------------
# Proving the checks bite.
# ---------------------------------------------------------------------------


def broken_copies(work: Path) -> tuple[Path, Path]:
    """Two copies of the plugin: one with no message, one with a broken stand-in."""
    no_message = work / "bite-no-message" / "s0ma"
    shutil.copytree(PLUGIN_DIR, no_message)
    (no_message / "scripts" / "not-set-up.txt").write_text("", encoding="utf-8")

    broken = work / "bite-broken-stand-in" / "s0ma"
    shutil.copytree(PLUGIN_DIR, broken)
    if WINDOWS:
        target, old, new = (
            broken / "scripts" / "s0ma-stand-in.ps1",
            "$ErrorActionPreference = 'Stop'",
            "exit 3",
        )
    else:
        target = broken / "scripts" / "s0ma-serve"
        old = 'while IFS= read -r line || [ -n "$line" ]; do'
        new = "exit 3\n" + old
    text = target.read_text(encoding="utf-8")
    expect(text.count(old) == 1, f"could not find the line to break in {target.name}")
    target.write_bytes(text.replace(old, new).encode("utf-8"))
    return no_message, broken


def must_fail(label: str, check: Any, results: Results) -> None:
    """Run *check*, which must fail. A check that cannot fail is not a gate."""
    banner(f"BITE: {label} (this check must fail)")
    try:
        check()
    except CheckFailed as failure:
        results.add(f"bites: {label}", f"failed as it must: {failure}")
        return
    raise CheckFailed(f"{label}: the check passed on a broken copy, so it cannot fail")


# ---------------------------------------------------------------------------
# The legs.
# ---------------------------------------------------------------------------


def leg_uv_absent(opts: argparse.Namespace, work: Path, results: Results) -> None:
    launcher = load_launcher()
    project = work / "project"
    project.mkdir()
    prove_uv_absent(launcher, results, project, hide_uv=opts.hide_uv)
    message = the_message()
    say(f"the message: {message}")
    env = child_env({"S0MA_HOME": str(work / "s0ma-home")})
    claude = Claude(opts.claude, opts.claude_version, work) if opts.claude else None
    exported = export_tree(
        work, env, results, with_claude=claude is not None, from_tar=opts.exported_tar
    )

    for label, plugin_dir in (
        ("plugin folder", PLUGIN_DIR),
        ("exported tree", exported),
    ):
        banner(f"uv absent: the hook and the server, {label}")
        results.add(
            f"hook, {label}", check_hook_not_set_up(plugin_dir, message, env, project)
        )
        results.add(
            f"server direct, {label}",
            check_stand_in(plugin_dir, message, launcher, env, project),
        )

    no_message, broken = broken_copies(work)
    must_fail(
        "hook, message removed",
        lambda: check_hook_not_set_up(no_message, message, env, project),
        results,
    )
    must_fail(
        "server, message removed",
        lambda: check_stand_in(no_message, message, launcher, env, project),
        results,
    )
    must_fail(
        "server, stand-in broken",
        lambda: check_stand_in(broken, message, launcher, env, project),
        results,
    )

    if claude is None:
        results.add("claude checks", "LEFT OUT ON REQUEST (--no-claude)")
        return
    banner("uv absent: the real Claude Code")
    claude.check_version(env, project, results)
    for label, plugin_dir in (
        ("plugin folder", PLUGIN_DIR),
        ("exported tree", exported),
    ):
        results.add(
            f"plugin validate, {label}", claude.validate(plugin_dir, env, project)
        )
        connected_everywhere(claude, label, plugin_dir, env, project, results)

    def broken_shows_connected() -> None:
        line = claude.mcp_list_line(broken, env, project)
        expect(is_connected(line), f"the s0ma server is not connected: {line}")

    must_fail("mcp list, stand-in broken", broken_shows_connected, results)


def import_e2e_helpers() -> ModuleType:
    """The end-to-end test's own helpers, so the keyless wheels are built its way."""
    sys.path.insert(0, str(LAUNCHER_TESTS))
    try:
        e2e: ModuleType = importlib.import_module("test_e2e_real_wheels")
    except ImportError as exc:
        raise CheckFailed(
            f"the e2e helpers need the workspace environment (uv run): {exc}"
        ) from exc
    return e2e


def leg_uv_present(opts: argparse.Namespace, work: Path, results: Results) -> None:
    launcher = load_launcher()
    e2e = import_e2e_helpers()
    from fake_control_plane import FakeControlPlane  # type: ignore[import-not-found]

    project = work / "project"
    project.mkdir()
    home = work / "s0ma-home"
    banner("uv present")
    uv = shutil.which("uv", path=child_env().get("PATH"))
    expect(uv is not None, "the uv-present leg found no uv on the PATH")
    say(f"uv is {uv}")
    run([str(uv), "--version"], child_env(), project)

    # A loopback stand-in for the control plane: anything keyless that asked it
    # for something would be recorded, and nothing here reaches the real one.
    plane = FakeControlPlane(
        key="first-run-check-never-sent", work=work / "control-plane"
    )
    plane.start()
    try:
        env = child_env({"S0MA_HOME": str(home), "S0MA_CP_HOST": plane.host})
        say(f"S0MA_HOME={home}  S0MA_CP_HOST={plane.host}  no license key")
        claude = Claude(opts.claude, opts.claude_version, work) if opts.claude else None
        exported = export_tree(work, env, results, with_claude=claude is not None)

        banner("uv present, nothing installed")
        ran = run_hook(PLUGIN_DIR, env, project)
        expect(ran.code == 0, f"the hook exited {ran.code}")
        expect(ran.stderr == "", f"the hook wrote to stderr: {ran.stderr!r}")
        lines = ran.stdout.splitlines()
        expect(
            len(lines) == 1,
            f"the hook printed {len(lines)} lines, not one: {ran.stdout!r}",
        )
        hint = json.loads(lines[0])
        expect(
            str(hint.get("systemMessage", "")).startswith(launcher.HINT_TOOLS_MISSING),
            f"the hook's line is not the launcher's tools-missing line: {lines[0]}",
        )
        context = hint.get("hookSpecificOutput", {}).get("additionalContext", "")
        expect(
            str(context).startswith(launcher.HINT_TOOLS_MISSING),
            f"no tools-missing context: {lines[0]}",
        )
        results.add(
            "hook, nothing installed", f"exit 0, stderr empty, stdout {lines[0]}"
        )

        session = McpSession(server_command(PLUGIN_DIR), env, project)
        try:
            info: dict[str, Any] = session.initialize().get("serverInfo") or {}
            expect(
                info == launcher.stub_server_info(),
                f"serverInfo {info!r}, not the setup helper",
            )
            tools = session.request("tools/list").get("result", {}).get("tools")
            expect(tools == [launcher.stub_tool()], f"tools/list gave {tools}")
            expect(session.close() == 0, "the setup helper did not exit 0")
        finally:
            session.kill()
        results.add(
            "server direct, nothing installed",
            f"the launcher's setup helper {info['name']} {info['version']}",
        )

        if claude is not None:
            claude.check_version(env, project, results)
            for label, plugin_dir in (
                ("plugin folder", PLUGIN_DIR),
                ("exported tree", exported),
            ):
                connected_everywhere(
                    claude,
                    f"nothing installed, {label}",
                    plugin_dir,
                    env,
                    project,
                    results,
                )

        banner("uv present, a keyless install from wheels built here")
        version_v = e2e.tree_version()
        version_k = f"{e2e.next_patch(version_v)}+{e2e.KEYLESS_LABEL}"
        say(
            f"the tree is {version_v}; the wheels are built as {version_k}, a local version no index can hold"
        )
        index = e2e.build_keyless_wheels(work / "wheels", version_v, version_k)
        for wheel in sorted(index.glob("*.whl")):
            say(f"built {wheel.name}")
        keyless = e2e.launcher_at_version(work, version_k)
        install_env = dict(env)
        install_env["UV_FIND_LINKS"] = str(index)
        ran = run(
            [sys.executable, str(keyless), "install"], install_env, project, timeout=900
        )
        expect(ran.code == 0, f"the keyless install exited {ran.code}")
        expect(
            f"s0ma {version_k} is installed." in ran.stderr,
            "the install did not say it installed the built version",
        )
        toolchain = launcher.managed_toolchain_dir(home, version_k)
        state = json.loads(launcher.state_path(home).read_text(encoding="utf-8"))
        say(f"state.json: {json.dumps(state, sort_keys=True)}")
        expect(
            state.get("installed") == [version_k],
            f"state.json installed {state.get('installed')!r}",
        )
        for distribution in (None, "s0ma_lang", "s0ma_lang_mcp"):
            found = launcher.installed_version_of(toolchain, distribution)
            expect(
                found == version_k,
                f"{distribution or 'the toolchain'} is {found!r}, not {version_k}",
            )
        expect(
            plane.requests == [],
            f"the keyless install asked the control plane: {plane.requests}",
        )
        results.add(
            "keyless install",
            f"s0ma {version_k} from UV_FIND_LINKS={index.name}/; umbrella and server dist-info both {version_k}; "
            f"no control-plane request",
        )

        names = sorted(
            str(t["name"])
            for t in json.loads(SURFACE_SNAPSHOT.read_text(encoding="utf-8"))["tools"]
        )
        for label, plugin_dir in (
            ("plugin folder", PLUGIN_DIR),
            ("exported tree", exported),
        ):
            results.add(
                f"server direct, installed, {label}",
                check_real_server(plugin_dir, version_k, names, env, project),
            )
        results.add(
            "hook, installed",
            check_hook_installed(run_hook(PLUGIN_DIR, env, project), launcher),
        )
        project_off = work / "project-off"
        (project_off / ".s0ma").mkdir(parents=True)
        (project_off / ".s0ma" / "preferences.json").write_text(
            '{"s0ma": "off"}\n', encoding="utf-8"
        )
        results.add(
            "hook, installed, s0ma off in the project",
            check_hook_off(run_hook(PLUGIN_DIR, env, project_off), launcher),
        )

        if claude is not None:
            for label, plugin_dir in (
                ("plugin folder", PLUGIN_DIR),
                ("exported tree", exported),
            ):
                results.add(
                    f"plugin validate, {label}",
                    claude.validate(plugin_dir, env, project),
                )
                connected_everywhere(
                    claude, f"installed, {label}", plugin_dir, env, project, results
                )
        else:
            results.add("claude checks", "LEFT OUT ON REQUEST (--no-claude)")
        expect(
            plane.requests == [], f"something asked the control plane: {plane.requests}"
        )
        results.add("control plane", "no request from anything in this leg")
    finally:
        plane.stop()


def leg_e2e(work: Path, results: Results) -> None:
    banner("The real-wheel end-to-end test, every case, none skipped")
    report = work / "e2e.xml"
    env = child_env({"S0MA_E2E": "1", "S0MA_HOME": str(work / "s0ma-home")})
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(E2E_TEST),
        "-v",
        "-s",
        "-rs",
        "-p",
        "no:cacheprovider",
        f"--junitxml={report}",
    ]
    say(f"$ {subprocess.list2cmdline(command)}")
    code = subprocess.run(
        command, env=env, cwd=str(ROOT), check=False, timeout=3600
    ).returncode  # noqa: S603
    say(f"[exit {code}]")
    expect(report.is_file(), "pytest wrote no report")
    suites = ElementTree.parse(report).getroot()
    suite = suites if suites.tag == "testsuite" else suites.find("testsuite")
    expect(suite is not None, "the report has no test suite")
    assert suite is not None
    counts = {
        name: int(suite.get(name, "0"))
        for name in ("tests", "skipped", "failures", "errors")
    }
    cases = [case.get("name", "") for case in suite.iter("testcase")]
    say(f"cases: {cases}")
    expect(code == 0, f"pytest exited {code}")
    expect(counts["skipped"] == 0, f"{counts['skipped']} end-to-end cases skipped")
    expect(
        counts["failures"] == 0 and counts["errors"] == 0,
        f"failures or errors: {counts}",
    )
    expect(any("keyless" in case for case in cases), "the keyless case did not run")
    results.add(
        "e2e",
        f"{counts['tests']} run, {counts['skipped']} skipped, 0 failed: {', '.join(cases)}",
    )


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="The first-run check of the Claude Code plugin."
    )
    parser.add_argument("leg", choices=("uv-absent", "uv-present", "e2e"))
    who = parser.add_mutually_exclusive_group()
    who.add_argument(
        "--claude",
        metavar="COMMAND",
        help="run the real Claude Code checks with this command",
    )
    who.add_argument(
        "--no-claude",
        action="store_true",
        help="leave the Claude Code checks out, and say so",
    )
    parser.add_argument(
        "--claude-version", help="the exact Claude Code version --claude must be"
    )
    parser.add_argument(
        "--exported-tar",
        type=Path,
        help="the export as a tar file, for a leg with no uv to write it with",
    )
    parser.add_argument(
        "--hide-uv",
        action="store_true",
        help="move a uv this machine has out of view (CI only)",
    )
    opts = parser.parse_args(argv)
    if opts.leg != "e2e" and not opts.claude and not opts.no_claude:
        parser.error("say --claude <command> or --no-claude")
    if opts.claude and not opts.claude_version:
        parser.error("--claude needs --claude-version")

    results = Results(opts.leg)
    work = Path(tempfile.mkdtemp(prefix=f"first-run-{opts.leg}-"))
    say(f"working in {work}")
    try:
        if opts.leg == "uv-absent":
            leg_uv_absent(opts, work, results)
        elif opts.leg == "uv-present":
            leg_uv_present(opts, work, results)
        else:
            leg_e2e(work, results)
    except CheckFailed as failure:
        results.summary()
        say("")
        say(f"FAILED: {failure}")
        return 1
    results.summary()
    say("")
    say("PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
