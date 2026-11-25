#!/usr/bin/env python3
"""The first-run check: the Claude Code plugin on a machine that has just met it.

``.github/workflows/first-run.yml`` runs this on Linux, macOS and Windows, in
three legs each. It is standard library only, so the uv-absent leg can run it
with the runner's own Python and nothing else.

``uv-absent``
    Proves uv is nowhere the plugin or the launcher looks (``--hide-uv`` moves
    a runner image's uv out of the way first, and proves it again). Then runs
    the session-start hook's command exactly as ``hooks/hooks.json`` writes
    it, the way Claude Code runs a shell-form hook, and drives the server
    command with a small MCP client, against the plugin folder and against the
    tree ``scripts/export_claude_marketplace.py`` writes. Then shows the
    checks bite: a copy with the message removed and a copy with a broken
    stand-in must each fail them. Both edit hooks' commands are run too, as
    ``hooks/hooks.json`` writes them, for an edit in a s0ma project: with no uv
    they say nothing and exit 0. Every hook command is run by each PowerShell
    found (both on Windows), where it must exit 0 and print nothing, and the
    skip path's mean time over ten runs is printed.

``uv-present``
    With uv, a fresh ``S0MA_HOME`` and no license key: the hook and the server
    with nothing installed, then a keyless install from wheels built here at a
    version no package index can hold, and the real server's 15 tools through
    the plugin's server command. Once s0ma is installed the hook shows the
    person nothing and gives Claude the standing note, and in a project whose
    ``.s0ma/preferences.json`` turns s0ma off it says the one off line and
    nothing else. In a project the installed s0ma makes with ``s0ma new
    project``, the installed ``s0ma test`` exits 0 with the starter tests
    passed, and the edit hooks refuse an edit under its build folder and hand
    on what ``s0ma check`` finds in a broken ``.s0ma`` file. The start skill's
    "show me" walk runs with the installed s0ma: ``--sample --step 0``, each
    step in turn on the folder it names, one step again, then ``s0ma check``
    and ``s0ma build .``, each step's line, counts and ``finished`` held to
    the sample's own words and to ``s0ma inspect --all``. Then step 0 again,
    whose refusal must say where the project is, so a second walk picks up. Imports the
    end-to-end test's helpers and s0ma's own sample, so run it with ``uv run
    python``.

``python-download``
    With the newest uv and no Python handed to it: every variable that names
    an interpreter or where uv keeps Pythons is cleared, and
    ``UV_PYTHON_PREFERENCE=only-managed`` is set for the plugin's commands, so
    no Python already on the machine can be used and uv has to download one.
    That stands in for a machine with no Python. A keyless install from wheels
    built here then runs through the plugin's own ``s0ma-launch``. It must
    succeed; the installed environment's Python must be one s0ma supports and
    its files must be under the leg's s0ma home; uv's default Python folder
    for this user must gain nothing; and ``new project``, ``check``, ``build
    .`` and ``test`` must pass with it. No Claude step runs. Imports the
    end-to-end test's helpers, so run it with ``uv run python``.

``e2e``
    Runs ``integrations/launcher/tests/test_e2e_real_wheels.py`` with
    ``S0MA_E2E=1`` and fails if any case skips.

``real-index --version X.Y.Z``
    After a release: the install a person gets from the public package index.
    The version is checked before anything runs, and the launcher in this tree
    must be at it, because a plugin installs the version it brings. With uv, a
    fresh ``S0MA_HOME``, no license key, no local wheels, no find-links and uv
    not offline, the exported plugin's ``s0ma-launch install`` has uv fetch
    ``s0ma-lang==X.Y.Z`` from the index. A version the index does not show
    yet, which happens for a few minutes after a release is published, is
    asked for again every half minute for up to five minutes, and each wait
    is printed. Then only what holds for any released
    version is checked: the version the installed ``s0ma doctor`` reports for
    each s0ma package (s0ma has no ``--version`` flag), the plugin's server
    and its tools, ``new project``, ``check``, ``build .`` and ``test`` in a
    fresh project, the start skill's "show me" walk as the ``uv-present`` leg
    runs it, and no request to the stand-in control plane. Every installed
    distribution is printed with its version. No Claude step runs. Imports
    s0ma's own sample for the walk, so run it with ``uv run python``.

The real Claude Code (``claude plugin validate --strict``, ``claude plugin
validate --profile directory``, each of which must exit 0 and is printed in
full, and ``claude --plugin-dir <dir> mcp list``) runs only when ``--claude
<command>`` is given, and the
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
import re
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
# The edit hooks.
# ---------------------------------------------------------------------------

#: Which hooks.json event runs which edit hook.
EDIT_HOOK_EVENTS = {"before-edit": "PreToolUse", "after-edit": "PostToolUse"}


def edit_hook_command(plugin_dir: Path, hook: str) -> str:
    """The one command an edit hook runs, with the plugin root filled in."""
    hooks = json.loads(
        (plugin_dir / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )
    event = EDIT_HOOK_EVENTS[hook]
    commands = {
        str(h["command"])
        for entry in hooks["hooks"].get(event, [])
        for h in entry["hooks"]
        if h.get("type") == "command"
    }
    expect(len(commands) == 1, f"expected one {event} command, found {commands}")
    return commands.pop().replace("${CLAUDE_PLUGIN_ROOT}", plugin_root_text(plugin_dir))


def run_edit_hook(
    plugin_dir: Path, hook: str, env: dict[str, str], project: Path, target: Path
) -> Ran:
    """Run one edit hook the way Claude Code runs it, for a Write to *target*."""
    command = edit_hook_command(plugin_dir, hook)
    shell = [str(git_bash()), "-c"] if WINDOWS else ["/bin/sh", "-c"]
    hook_env = dict(env)
    hook_env["CLAUDE_PLUGIN_ROOT"] = plugin_root_text(plugin_dir)
    hook_env["CLAUDE_PROJECT_DIR"] = str(project)
    payload: dict[str, Any] = {
        "session_id": "first-run-check",
        "transcript_path": str(project / "transcript.jsonl"),
        "cwd": str(project),
        "permission_mode": "default",
        "hook_event_name": EDIT_HOOK_EVENTS[hook],
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "x = 1\n"},
        "tool_use_id": "toolu_first_run_check",
    }
    if hook == "after-edit":
        payload["tool_response"] = {"filePath": str(target), "success": True}
    return run([*shell, command], hook_env, project, stdin=json.dumps(payload), timeout=60)


def edit_hook_answer(ran: Ran, hook: str) -> dict[str, Any]:
    """An edit hook's one line of JSON, after exit 0 and an empty stderr."""
    answer = hook_line(ran)
    extra = answer.get("hookSpecificOutput")
    expect(isinstance(extra, dict), f"the {hook} hook answered {answer!r}")
    assert isinstance(extra, dict)
    expect(
        extra.get("hookEventName") == EDIT_HOOK_EVENTS[hook],
        f"the {hook} answer names the event {extra.get('hookEventName')!r}",
    )
    return dict(extra)


def check_edit_hook_silent(ran: Ran, hook: str) -> str:
    """Exit 0, nothing on stderr, nothing on stdout."""
    expect(ran.code == 0, f"the {hook} hook exited {ran.code}, not 0")
    expect(ran.stderr == "", f"the {hook} hook wrote to stderr: {ran.stderr!r}")
    expect(ran.stdout == "", f"the {hook} hook said something: {ran.stdout!r}")
    return "exit 0, stderr empty, stdout empty"


def check_edit_refused(ran: Ran, launcher: ModuleType, build_dir: str) -> str:
    """The refusal, with the project's build folder named in it."""
    extra = edit_hook_answer(ran, "before-edit")
    expect(
        extra.get("permissionDecision") == "deny",
        f"the edit was not refused: {extra!r}",
    )
    reason = extra.get("permissionDecisionReason")
    expected = launcher.BUILD_DIR_REFUSAL.format(build_dir=build_dir)
    expect(reason == expected, f"the refusal said {reason!r}")
    return f"exit 0, stderr empty, deny naming {build_dir}/"


def check_edit_finding(ran: Ran, launcher: ModuleType, shown: str, code: str) -> str:
    """What the check found, between the lead-in and the closing line."""
    extra = edit_hook_answer(ran, "after-edit")
    context = str(extra.get("additionalContext", ""))
    lead = launcher.EDIT_CHECK_LEAD.format(path=shown)
    expect(context.startswith(lead + "\n"), f"the context does not lead in: {context!r}")
    expect(
        context.endswith("\n" + launcher.EDIT_CHECK_CLOSE),
        f"the context does not close: {context!r}",
    )
    expect(f"[{code}]" in context, f"the context does not name {code}: {context!r}")
    expect(
        len(context) <= launcher.EDIT_CHECK_MAX_CHARS,
        f"the context is {len(context)} characters",
    )
    return f"exit 0, stderr empty, additionalContext names {code} ({len(context)} characters)"


#: The shells that run a shell-form hook on Windows when Git Bash is missing:
#: Windows PowerShell 5.1 and PowerShell 7.
POWERSHELLS = ("powershell", "pwsh")


def all_hook_commands(plugin_dir: Path) -> list[tuple[str, str]]:
    """``(event, command)`` for every hook, with the plugin root filled in."""
    hooks = json.loads(
        (plugin_dir / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )
    root = plugin_root_text(plugin_dir)
    found: list[tuple[str, str]] = []
    for event, entries in sorted(hooks["hooks"].items()):
        for command in sorted(
            {str(h["command"]) for entry in entries for h in entry["hooks"]}
        ):
            found.append((event, command.replace("${CLAUDE_PLUGIN_ROOT}", root)))
    return found


def check_hooks_in_powershell(
    plugin_dir: Path, env: dict[str, str], project: Path, results: Results
) -> None:
    """Every hook command, as hooks.json writes it, run by PowerShell.

    Claude Code runs a shell-form hook in PowerShell on Windows when Git Bash
    is missing. Each command line is written so that PowerShell runs nothing
    and prints nothing there, and exits 0. On Windows both PowerShells must be
    found; elsewhere whichever is on this machine runs, and the result says
    which ran.
    """
    shells = [(name, shutil.which(name, path=env.get("PATH"))) for name in POWERSHELLS]
    say(f"PowerShells found: {shells}")
    if WINDOWS:
        missing = [name for name, path in shells if path is None]
        expect(not missing, f"no {missing} on this Windows machine")
    ran_any = False
    for name, path in shells:
        if path is None:
            continue
        ran_any = True
        for event, command in all_hook_commands(plugin_dir):
            payload = json.dumps(
                {"cwd": str(project), "hook_event_name": event, "session_id": "first-run-check"}
            )
            ran = run(
                [path, "-NoProfile", "-NonInteractive", "-Command", command],
                env,
                project,
                stdin=payload,
                timeout=120,
            )
            expect(ran.code == 0, f"{name} exited {ran.code} on the {event} hook")
            expect(ran.stdout == "", f"{name} printed {ran.stdout!r} on the {event} hook")
            expect(ran.stderr == "", f"{name} wrote {ran.stderr!r} on the {event} hook")
            results.add(
                f"{event} hook in {name}", "exit 0, stdout empty, stderr empty"
            )
    if not ran_any:
        results.add("hooks in PowerShell", "no powershell or pwsh on this machine; none ran")


def skip_path_timing(
    plugin_dir: Path, env: dict[str, str], work: Path, results: Results
) -> None:
    """The refusal hook for build/x.py in a folder that is no s0ma project:
    the mean of ten runs, as Claude Code runs it. Printed, not asserted."""
    plain = work / "no-project"
    (plain / "build").mkdir(parents=True, exist_ok=True)
    command = edit_hook_command(plugin_dir, "before-edit")
    shell = [str(git_bash()), "-c"] if WINDOWS else ["/bin/sh", "-c"]
    hook_env = dict(env)
    hook_env["CLAUDE_PLUGIN_ROOT"] = plugin_root_text(plugin_dir)
    hook_env["CLAUDE_PROJECT_DIR"] = str(plain)
    payload = json.dumps(
        {
            "cwd": str(plain),
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(plain / "build" / "x.py"), "content": "x = 1\n"},
        }
    ).encode("utf-8")
    times: list[float] = []
    for _ in range(10):
        start = time.perf_counter()
        done = subprocess.run(  # noqa: S603 - a fixed, local command
            [*shell, command],
            input=payload,
            capture_output=True,
            env=hook_env,
            cwd=str(plain),
            timeout=60,
            check=False,
        )
        times.append(time.perf_counter() - start)
        expect(
            (done.returncode, done.stdout, done.stderr) == (0, b"", b""),
            f"the skip path did not stay silent: {done!r}",
        )
    mean = sum(times) / len(times) * 1000
    results.add(
        "skip path, before-edit outside a s0ma project",
        f"mean {mean:.1f} ms over ten runs (min {min(times) * 1000:.1f}, max {max(times) * 1000:.1f})",
    )


def s0ma_shaped_project(where: Path) -> Path:
    """A folder that is a s0ma project by its pyproject.toml, with one source."""
    (where / "src").mkdir(parents=True)
    (where / "build").mkdir()
    (where / "pyproject.toml").write_text(
        '[project]\nname = "edits"\n[tool.s0ma]\nsource_roots = ["src"]\nbuild_dir = "build"\n',
        encoding="utf-8",
    )
    (where / "src" / "edits.s0ma").write_text("module edits\n", encoding="utf-8")
    return where


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
    plugin_dir: Path,
    version: str,
    names: list[str],
    env: dict[str, str],
    project: Path,
    *,
    count: int = 15,
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
        expect(len(tools) == count, f"{len(tools)} tools, not {count}")
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
        """Both verdicts on one plugin folder: strict, then the directory profile.

        ``--strict`` turns every warning the runtime would tolerate into a
        failure. ``--profile directory`` also fails on what the plugin
        directory would refuse a submission for. Each report is printed whole
        by :func:`run`. A CLI that does not know ``--profile`` says so, and
        that is printed and left there rather than failed: the flag is in the
        CLI's help and not yet in its documentation.
        """
        strict = self.validate_strict(plugin_dir, base, cwd)
        directory = self.validate_directory(plugin_dir, base, cwd)
        return f"--strict: {strict}; --profile directory: {directory}"

    def validate_strict(self, plugin_dir: Path, base: dict[str, str], cwd: Path) -> str:
        ran = run(
            [self.path, "plugin", "validate", "--strict", str(plugin_dir)],
            self.env(base),
            cwd,
        )
        expect(ran.code == 0, f"claude plugin validate --strict exited {ran.code}")
        return passed_verdict(ran, "claude plugin validate --strict")

    def validate_directory(
        self, plugin_dir: Path, base: dict[str, str], cwd: Path
    ) -> str:
        ran = run(
            [
                self.path,
                "plugin",
                "validate",
                "--profile",
                "directory",
                str(plugin_dir),
            ],
            self.env(base),
            cwd,
        )
        if ran.code != 0 and profile_rejected(ran):
            say("  this claude does not take --profile; the directory profile is left out")
            return "NOT RUN: this claude does not take --profile"
        expect(
            ran.code == 0,
            f"claude plugin validate --profile directory exited {ran.code}",
        )
        return passed_verdict(ran, "claude plugin validate --profile directory")

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


def report_lines(ran: Ran) -> list[str]:
    """Every non-blank line a command printed, on either stream, trimmed."""
    return [
        line.strip() for line in (ran.stdout + ran.stderr).splitlines() if line.strip()
    ]


def passed_verdict(ran: Ran, what: str) -> str:
    """The validator's last "Validation passed" line, or a failed check."""
    verdict = [line for line in report_lines(ran) if "Validation passed" in line]
    expect(bool(verdict), f"{what} did not say it passed")
    return verdict[-1]


def profile_rejected(ran: Ran) -> bool:
    """Whether the CLI refused ``--profile`` itself, before validating anything.

    A run that validated prints a verdict, passed or failed, and that is never
    read as a refusal of the flag: a failed report fails the check.
    """
    lines = report_lines(ran)
    if any("Validation passed" in line or "Validation failed" in line for line in lines):
        return False
    text = "\n".join(lines).lower()
    return "unknown option" in text or ("--profile" in text and "invalid" in text)


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
        edits = s0ma_shaped_project(work / f"edits-{label.replace(' ', '-')}")
        for hook, target in (
            ("before-edit", edits / "build" / "edits.py"),
            ("after-edit", edits / "src" / "edits.s0ma"),
        ):
            results.add(
                f"{hook} hook, {label}",
                check_edit_hook_silent(
                    run_edit_hook(plugin_dir, hook, env, edits, target), hook
                ),
            )

    banner("uv absent: the hooks in PowerShell, and the cost of the skip path")
    check_hooks_in_powershell(PLUGIN_DIR, env, project, results)
    skip_path_timing(PLUGIN_DIR, env, work, results)

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

        banner("uv present, the edit hooks in a project the installed s0ma made")
        bin_dir = launcher.bin_dir_of(toolchain)
        cli = launcher.find_program(bin_dir, "s0ma") if bin_dir is not None else None
        expect(cli is not None, f"no s0ma program in {toolchain}")
        assert cli is not None
        fresh_parent = work / "fresh"
        fresh_parent.mkdir()
        ran = run([str(cli), "new", "project", "demo", "--name", "demo"], env, fresh_parent)
        expect(ran.code == 0, f"s0ma new project exited {ran.code}")
        fresh = fresh_parent / "demo"
        generated = fresh / "build" / "core_domain.py"
        expect(generated.is_file(), f"the new project has no {generated.name} under build/")
        # `s0ma test` runs pytest from the toolchain's own environment, which
        # only the launcher's install puts there. Run before the edit hooks
        # below break a source file on purpose.
        ran = run([str(cli), "test"], env, fresh)
        expect(ran.code == 0, f"s0ma test exited {ran.code}")
        passed = [
            line.strip("= ")
            for line in ran.stdout.splitlines()
            if line.startswith("=") and " passed" in line
        ]
        expect(len(passed) == 1, "s0ma test printed no pytest pass line")
        expect(
            "failed" not in passed[0] and "error" not in passed[0],
            f"s0ma test reported {passed[0]}",
        )
        results.add("s0ma test, installed, a fresh project", f"exit 0, {passed[0]}")
        results.add(
            "before-edit hook, installed, a file under build/",
            check_edit_refused(
                run_edit_hook(PLUGIN_DIR, "before-edit", env, fresh, generated),
                launcher,
                "build",
            ),
        )
        source = fresh / "src" / "core" / "core_domain.s0ma"
        text = source.read_text(encoding="utf-8")
        expect("kind: FUNCTION" in text, f"{source.name} has no `kind: FUNCTION` line")
        source.write_text(text.replace("kind: FUNCTION", "kind: FUNKTION", 1), encoding="utf-8")
        results.add(
            "after-edit hook, installed, a broken .s0ma file",
            check_edit_finding(
                run_edit_hook(PLUGIN_DIR, "after-edit", env, fresh, source),
                launcher,
                "src/core/core_domain.s0ma",
                "PARSE_ERROR",
            ),
        )

        banner("uv present, the show-me walk with the installed s0ma")
        walk_parent = work / "walk"
        walk_parent.mkdir()
        run_show_me_walk(cli, env, walk_parent, results)

        banner("uv present: the hooks in PowerShell, and the cost of the skip path")
        check_hooks_in_powershell(PLUGIN_DIR, env, project, results)
        skip_path_timing(PLUGIN_DIR, env, work, results)

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


# ---------------------------------------------------------------------------
# After a release: the install a person gets from the public package index.
# ---------------------------------------------------------------------------

#: A released version: digits and dots, then at most a pre-release or
#: post-release tail of letters, digits and dots (``1.0.0rc1``, ``1.0.0.post1``).
#: No local label, no space, nothing a shell would read.
RELEASE_VERSION_RE = re.compile(r"\A[0-9]+(?:\.[0-9]+)*(?:\.?[A-Za-z][A-Za-z0-9.]*)?\Z")

#: What would point uv anywhere but the public package index, or keep it off
#: the network. None of it reaches uv in the ``real-index`` leg.
INDEX_STEERING = (
    "UV_FIND_LINKS",
    "UV_OFFLINE",
    "UV_NO_INDEX",
    "UV_INDEX",
    "UV_INDEX_URL",
    "UV_DEFAULT_INDEX",
    "UV_EXTRA_INDEX_URL",
    "UV_CONFIG_FILE",
    "PIP_FIND_LINKS",
    "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL",
    "PIP_NO_INDEX",
)


def release_version(text: str) -> str:
    """*text*, if it is a released version; otherwise a refusal naming it."""
    if len(text) > 64 or RELEASE_VERSION_RE.match(text) is None or text.endswith("."):
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a released version: give digits and dots, such as "
            "0.22.0, with at most a pre-release or post-release tail such as rc1"
        )
    return text


def launcher_version_line(launcher_file: Path) -> str:
    """The one ``LAUNCHER_VERSION = "..."`` value in a launcher file."""
    found = re.findall(
        r'(?m)^LAUNCHER_VERSION = "([^"]*)"$', launcher_file.read_text(encoding="utf-8")
    )
    expect(len(found) == 1, f"{launcher_file} states its version {len(found)} times")
    return str(found[0])


def check_launcher_is_at(version: str, launcher_file: Path = LAUNCHER_FILE) -> str:
    """The launcher in this tree must bring *version*: it is what a plugin installs."""
    brings = launcher_version_line(launcher_file)
    expect(
        brings == version,
        f"the launcher in this tree brings s0ma {brings} and the version given is "
        f"{version}, so run this from the tag of {version}, because a plugin "
        "installs the version it brings",
    )
    return brings


def real_index_env(home: Path, cp_host: str, uv_cache: Path) -> dict[str, str]:
    """The machine's environment for an install from the public package index.

    No key and no s0ma setting (:func:`child_env`), nothing that steers uv to
    another index, to local files, or off the network, no uv configuration
    file, and a uv cache of its own, so every file is fetched in this run.
    """
    env = {
        key: value
        for key, value in child_env().items()
        if key.upper() not in INDEX_STEERING
    }
    env["UV_NO_CONFIG"] = "1"
    env["UV_CACHE_DIR"] = str(uv_cache)
    env["S0MA_HOME"] = str(home)
    env["S0MA_CP_HOST"] = cp_host
    return env


def launch_command(plugin_dir: Path, *arguments: str) -> list[str] | str:
    """The plugin's own ``s0ma-launch``, as a command line in Claude runs it."""
    if WINDOWS:
        command = str(plugin_dir.resolve() / "bin" / "s0ma-launch.cmd")
        return f'cmd.exe /d /s /c ""{command}" {" ".join(arguments)}"'
    return [str(plugin_dir / "bin" / "s0ma-launch"), *arguments]


#: How long an install from the index waits, in all, for a version the index
#: does not show yet, and how long each wait is. A version published a minute
#: ago can be missing from the index's answer for a little while.
INDEX_WAIT_SECONDS = 300.0
INDEX_RETRY_SECONDS = 30.0


def not_on_the_index_yet(ran: Ran, version: str) -> bool:
    """Whether uv refused because the index has no ``s0ma-lang==<version>``."""
    said = (ran.stdout + ran.stderr).lower()
    return f"no version of s0ma-lang=={version}".lower() in said


def install_from_real_index(
    plugin_dir: Path,
    version: str,
    env: dict[str, str],
    cwd: Path,
    *,
    sleep: Any = time.sleep,
    clock: Any = time.monotonic,
) -> str:
    """``s0ma-launch install`` with no key and no local wheels: uv asks the index.

    When uv says the version does not exist, the install is tried again after
    a wait, for up to :data:`INDEX_WAIT_SECONDS` in all. Any other failure
    fails at once.
    """
    for name in (*INDEX_STEERING, "S0MA_LICENSE_KEY", "S0MA_LAUNCH_OFFLINE_INSTALL"):
        expect(name not in env, f"{name} would reach uv in an install from the index")
    deadline = clock() + INDEX_WAIT_SECONDS
    waits = 0
    while True:
        ran = run(launch_command(plugin_dir, "install"), env, cwd, timeout=900)
        if ran.code == 0 or not not_on_the_index_yet(ran, version):
            break
        left = deadline - clock()
        if left <= 0:
            break
        pause = min(INDEX_RETRY_SECONDS, left)
        waits += 1
        say(
            f"WAIT {waits}: the index does not show s0ma-lang=={version} yet; "
            f"asking again in {pause:.0f}s (up to {INDEX_WAIT_SECONDS:.0f}s in all)"
        )
        sleep(pause)
    expect(ran.code == 0, f"s0ma-launch install exited {ran.code}")
    expect(
        f"s0ma {version} is installed." in ran.stdout + ran.stderr,
        f"s0ma-launch install did not say it installed {version}",
    )
    after = f", after {waits} wait{'s' if waits != 1 else ''} for the index" if waits else ""
    return f"exit 0, s0ma {version} is installed, with no key and no local wheels{after}"


def installed_distributions(uv: str, python: Path, env: dict[str, str], cwd: Path) -> str:
    """Every distribution in the installed environment, ``name==version``."""
    ran = run([uv, "pip", "list", "--python", str(python), "--format", "json"], env, cwd)
    expect(ran.code == 0, f"uv pip list exited {ran.code}")
    listed = json.loads(ran.stdout)
    return ", ".join(sorted(f"{item['name']}=={item['version']}" for item in listed))


#: The four packages ``s0ma doctor`` lists in its ``versions`` block.
DOCTOR_PACKAGES = ("s0ma-lang-core", "s0ma-lang-dsl", "s0ma-lang-mcp", "s0ma-lang-studi0")


def check_doctor_versions(output: str, version: str) -> str:
    """Each s0ma package in ``s0ma doctor``'s ``versions`` block is at *version*."""
    found: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in DOCTOR_PACKAGES and line.startswith(" "):
            found[parts[0]] = parts[1]
    expect(
        sorted(found) == sorted(DOCTOR_PACKAGES),
        f"s0ma doctor listed {sorted(found)}, not the four s0ma packages",
    )
    wrong = {name: seen for name, seen in found.items() if seen != version}
    expect(not wrong, f"s0ma doctor reports {wrong}, not {version}")
    return ", ".join(f"{name} {found[name]}" for name in DOCTOR_PACKAGES)


def walk_json(ran: Ran, what: str) -> dict[str, Any]:
    """The JSON one ``--step`` call printed, or a failure saying what came."""
    expect(ran.code == 0, f"{what} exited {ran.code}")
    try:
        report: dict[str, Any] = json.loads(ran.stdout)
    except ValueError as exc:
        raise CheckFailed(f"{what} printed no JSON: {ran.stdout!r}") from exc
    expect(report.get("ok") is True, f"{what} said ok={report.get('ok')!r}: {report.get('error')!r}")
    return report


def expected_step_line(steps: list[tuple[str, str]], number: int) -> str:
    """The ``line`` a step after step 0 says, from the sample's own words."""
    name, intent = steps[number - 1]
    return f"Step {number} of {len(steps)}: {name}. {intent}"


def check_walk_step(
    report: dict[str, Any],
    number: int,
    steps: list[tuple[str, str]],
    sample: dict[str, str],
) -> None:
    """One step's JSON says that step, of this sample, and whether it is the last."""
    total = len(steps)
    step = report.get("step") or {}
    expect(step.get("number") == number, f"step {number}: the JSON says step {step.get('number')!r}")
    expect(step.get("of") == total, f"step {number}: the JSON says of {step.get('of')!r}, not {total}")
    expect(report.get("finished") is (number == total), f"step {number}: finished is {report.get('finished')!r}")
    for key, value in sample.items():
        expect(report.get(key) == value, f"step {number}: {key} is {report.get(key)!r}, not {value!r}")
    if number == 0:
        expect(step.get("name") is None, f"step 0 has a name: {step.get('name')!r}")
        expect(
            (report.get("modules"), report.get("parts")) == (0, 0),
            f"step 0 built something: {report.get('modules')} modules, {report.get('parts')} parts",
        )
        return
    name, intent = steps[number - 1]
    expect((step.get("name"), step.get("intent")) == (name, intent), f"step {number}: {step!r}")
    line = expected_step_line(steps, number)
    expect(report.get("line") == line, f"step {number}: line {report.get('line')!r}, not {line!r}")


def check_walk_counts(
    cli: Path, env: dict[str, str], root: Path, report: dict[str, Any], number: int
) -> None:
    """The step's ``modules`` and ``parts`` are what ``s0ma inspect --all`` reads."""
    ran = run([str(cli), "inspect", "--all", "--format", "json"], env, root)
    expect(ran.code == 0, f"s0ma inspect --all exited {ran.code} after step {number}")
    modules = json.loads(ran.stdout)
    parts = sum(int(module["components"]) for module in modules)
    expect(
        (report.get("modules"), report.get("parts")) == (len(modules), parts),
        f"step {number}: the JSON says {report.get('modules')} modules, {report.get('parts')} parts; "
        f"s0ma inspect --all reads {len(modules)} modules, {parts} parts",
    )


def run_show_me_walk(cli: Path, env: dict[str, str], parent: Path, results: Results) -> None:
    """The start skill's "show me" walk, command by command, with the installed s0ma.

    What each step must say is read from the sample's archetype in this tree
    and from the JSON itself. In the ``uv-present`` leg the installed wheels
    were built from this tree. In the ``real-index`` leg this tree is the
    release's tag and the installed s0ma came from the package index.
    """
    from s0ma_dsl.cli.templates import FIRST_RUN_SAMPLE, get_archetype

    archetype = get_archetype(FIRST_RUN_SAMPLE)
    steps = [(step.name, step.intent) for step in archetype.steps]
    expect(len(steps) > 1, f"the first-run sample {FIRST_RUN_SAMPLE!r} has {len(steps)} steps")
    sample = {
        "called": archetype.called,
        "noun": archetype.noun,
        "example_question": archetype.example_question,
    }
    expect(all(sample.values()), f"the first-run sample leaves a word empty: {sample}")

    def step(number: int, folder: str | None) -> dict[str, Any]:
        where = [folder] if folder is not None else []
        command = [str(cli), "new", "project", *where, "--sample", "--step", str(number), "--format", "json"]
        return walk_json(run(command, env, parent), f"--sample --step {number}")

    first = step(0, None)
    check_walk_step(first, 0, steps, sample)
    root = Path(str(first.get("project_root")))
    expect(root.parent.resolve() == parent.resolve(), f"step 0 made {root}, not a folder in {parent}")
    expect(not list((root / "build").glob("*.py")), "step 0 built something")
    results.add(
        "show-me walk, step 0",
        f"exit 0, {root.name}/ made, step 0 of {len(steps)}, nothing built, called {first['called']!r}",
    )

    for number in range(1, len(steps) + 1):
        report = step(number, str(root))
        check_walk_step(report, number, steps, sample)
        expect(report.get("project_root") == str(root), f"step {number} moved to {report.get('project_root')}")
        expect(report.get("unchanged") is False, f"step {number} says it changed nothing")
        check_walk_counts(cli, env, root, report, number)
        results.add(
            f"show-me walk, step {number}",
            f"exit 0, {report['line']!r}, {report['modules']} modules, {report['parts']} parts, "
            f"finished {report['finished']}",
        )
        if number == 1:
            again = step(number, str(root))
            check_walk_step(again, number, steps, sample)
            expect(again.get("unchanged") is True, "a repeated step did not say it changed nothing")
            expect(again.get("files_written") == [], f"a repeated step wrote {again.get('files_written')}")
            expect(
                (again.get("modules"), again.get("parts")) == (report.get("modules"), report.get("parts")),
                "a repeated step changed the counts",
            )
            results.add(f"show-me walk, step {number} again", "exit 0, unchanged, nothing written")

    ran = run([str(cli), "check"], env, root)
    expect(ran.code == 0, f"s0ma check exited {ran.code} on the finished sample")
    expect("No errors." in ran.stdout, "s0ma check did not say No errors. on the finished sample")
    ran = run([str(cli), "build", "."], env, root)
    expect(ran.code == 0, f"s0ma build . exited {ran.code} on the finished sample")
    said = ran.stdout + ran.stderr
    # The walk says "all checks pass" only when the build printed no error and
    # no warning, and a build with either prints a `Results:` line.
    results_lines = [line for line in said.splitlines() if line.strip().startswith("Results:")]
    expect(results_lines == [], f"the finished sample's build printed {results_lines}")
    results.add(
        "show-me walk, the final check",
        f"s0ma check: No errors.; s0ma build .: exit 0, no Results: line; "
        f"{len(steps)} steps, {report['parts']} parts",
    )

    # A second "show me" in the same folder: step 0 refuses and says where the
    # project is, and asking for that step picks the walk up, changing nothing.
    ran = run(
        [str(cli), "new", "project", "--sample", "--step", "0", "--format", "json"], env, parent
    )
    expect(ran.code != 0, "step 0 on a finished sample did not refuse")
    try:
        refusal: dict[str, Any] = json.loads(ran.stdout)
    except ValueError as exc:
        raise CheckFailed(f"the refusal printed no JSON: {ran.stdout!r}") from exc
    expect(refusal.get("ok") is False, f"the refusal said ok={refusal.get('ok')!r}")
    expect(
        (refusal.get("project_root"), refusal.get("at_step"), refusal.get("of"))
        == (str(root), len(steps), len(steps)),
        f"the refusal says {refusal.get('project_root')!r}, at_step {refusal.get('at_step')!r}, "
        f"of {refusal.get('of')!r}",
    )
    picked = step(int(refusal["at_step"]), str(root))
    check_walk_step(picked, len(steps), steps, sample)
    expect(picked.get("unchanged") is True, "picking the walk up changed something")
    expect(picked.get("files_written") == [], f"picking the walk up wrote {picked.get('files_written')}")
    results.add(
        "show-me walk, a second time",
        f"step 0 refused with at_step {refusal['at_step']} of {refusal['of']}; "
        f"--step {refusal['at_step']} unchanged, finished {picked['finished']}",
    )


def run_fresh_project_steps(
    cli: Path, env: dict[str, str], parent: Path, results: Results
) -> None:
    """``new project``, ``check``, ``build .`` and ``test`` each exit 0."""
    ran = run([str(cli), "new", "project", "demo", "--name", "demo"], env, parent)
    expect(ran.code == 0, f"s0ma new project exited {ran.code}")
    results.add("s0ma new project demo", "exit 0")
    fresh = parent / "demo"
    ran = run([str(cli), "check"], env, fresh)
    expect(ran.code == 0, f"s0ma check exited {ran.code}")
    results.add("s0ma check", "exit 0")
    ran = run([str(cli), "build", "."], env, fresh)
    expect(ran.code == 0, f"s0ma build . exited {ran.code}")
    # A warning in the build is printed above, with everything it said, and
    # does not fail this leg: what a release warns about is not a first-run fault.
    said = [line.strip() for line in (ran.stdout + ran.stderr).splitlines() if line.strip()]
    results.add("s0ma build .", f"exit 0, last line: {said[-1] if said else '(nothing)'}")
    ran = run([str(cli), "test"], env, fresh)
    expect(ran.code == 0, f"s0ma test exited {ran.code}")
    passed = [
        line.strip("= ")
        for line in ran.stdout.splitlines()
        if line.startswith("=") and " passed" in line
    ]
    expect(len(passed) == 1, "s0ma test printed no pytest pass line")
    expect(
        "failed" not in passed[0] and "error" not in passed[0],
        f"s0ma test reported {passed[0]}",
    )
    results.add("s0ma test", f"exit 0, {passed[0]}")


def leg_real_index(opts: argparse.Namespace, work: Path, results: Results) -> None:
    version = str(opts.version)
    banner(f"After a release: s0ma {version} from the public package index")
    brings = check_launcher_is_at(version)
    results.add("launcher in this tree", f"brings s0ma {brings}, the version given")
    launcher = load_launcher()
    sys.path.insert(0, str(LAUNCHER_TESTS))
    from fake_control_plane import FakeControlPlane  # type: ignore[import-not-found]

    project = work / "project"
    project.mkdir()
    home = work / "s0ma-home"
    uv = shutil.which("uv", path=child_env().get("PATH"))
    expect(uv is not None, "the real-index leg found no uv on the PATH")
    assert uv is not None
    say(f"uv is {uv}")
    ran = run([uv, "--version"], child_env(), project)
    results.add("uv", ran.stdout.strip())

    # A loopback stand-in for the control plane: a keyless install that asked
    # it anything would be recorded, and nothing here reaches the real one.
    plane = FakeControlPlane(key="first-run-check-never-sent", work=work / "control-plane")
    plane.start()
    try:
        env = real_index_env(home, plane.host, work / "uv-cache")
        say(f"S0MA_HOME={home}  S0MA_CP_HOST={plane.host}  no license key, no find-links")
        exported = export_tree(work, env, results, with_claude=False)
        expect(
            launcher_version_line(exported / "launcher" / "s0ma_launch.py") == version,
            f"the exported plugin's launcher does not bring {version}",
        )

        banner(f"s0ma-launch install: uv fetches s0ma-lang=={version} from the index")
        results.add("keyless install from the index", install_from_real_index(exported, version, env, project))
        toolchain = launcher.managed_toolchain_dir(home, version)
        state = json.loads(launcher.state_path(home).read_text(encoding="utf-8"))
        say(f"state.json: {json.dumps(state, sort_keys=True)}")
        expect(
            state.get("installed") == [version],
            f"state.json installed {state.get('installed')!r}",
        )
        for distribution in (None, "s0ma_lang", "s0ma_lang_mcp"):
            found = launcher.installed_version_of(toolchain, distribution)
            expect(
                found == version,
                f"{distribution or 'the toolchain'} is {found!r}, not {version}",
            )
        python = launcher.venv_python(toolchain)
        expect(python is not None, f"no Python in {toolchain}")
        results.add("installed", installed_distributions(uv, python, env, project))

        bin_dir = launcher.bin_dir_of(toolchain)
        cli = launcher.find_program(bin_dir, "s0ma") if bin_dir is not None else None
        expect(cli is not None, f"no s0ma program in {toolchain}")
        assert cli is not None
        # s0ma has no --version flag; `s0ma doctor` is how it says its version,
        # one line per s0ma package in its `versions` block.
        ran = run([str(cli), "doctor"], env, project)
        expect(ran.code == 0, f"s0ma doctor exited {ran.code}")
        results.add("s0ma doctor, versions", check_doctor_versions(ran.stdout, version))

        names = sorted(
            str(t["name"])
            for t in json.loads(SURFACE_SNAPSHOT.read_text(encoding="utf-8"))["tools"]
        )
        results.add(
            "server, the exported plugin",
            check_real_server(exported, version, names, env, project, count=len(names)),
        )

        banner("The installed s0ma in a fresh project")
        fresh_parent = work / "fresh"
        fresh_parent.mkdir()
        run_fresh_project_steps(cli, env, fresh_parent, results)

        banner("The show-me walk with the installed s0ma")
        walk_parent = work / "walk"
        walk_parent.mkdir()
        run_show_me_walk(cli, env, walk_parent, results)

        results.add("claude checks", "none in this leg")
        expect(
            plane.requests == [], f"something asked the control plane: {plane.requests}"
        )
        results.add("control plane", "running and configured; no request from anything in this leg")
    finally:
        plane.stop()


# ---------------------------------------------------------------------------
# uv chooses the Python: a machine with no Python, stood in for.
# ---------------------------------------------------------------------------

#: What names an interpreter, or where uv keeps or finds Pythons. None of it
#: reaches the plugin's commands in the ``python-download`` leg, so the choice
#: is uv's and the plugin's alone.
PYTHON_STEERING = (
    "UV_PYTHON",
    "UV_PYTHON_INSTALL_DIR",
    "UV_PYTHON_BIN_DIR",
    "UV_PYTHON_PREFERENCE",
    "UV_PYTHON_DOWNLOADS",
    "UV_MANAGED_PYTHON",
    "UV_NO_MANAGED_PYTHON",
    "UV_SYSTEM_PYTHON",
    "UV_PROJECT_ENVIRONMENT",
    "UV_OFFLINE",
    "UV_CONFIG_FILE",
    "CONDA_PREFIX",
    "PYTHONHOME",
    "PYTHONPATH",
)


def python_download_env(home: Path, cp_host: str) -> dict[str, str]:
    """The plugin's environment when uv must download the Python itself.

    Nothing names an interpreter or a Python folder, no uv configuration file
    is read, and only Pythons uv manages may be used, which on a fresh s0ma
    home means one uv downloads.
    """
    env = {
        key: value
        for key, value in child_env().items()
        if key.upper() not in PYTHON_STEERING
    }
    env["UV_NO_CONFIG"] = "1"
    env["UV_PYTHON_PREFERENCE"] = "only-managed"
    env["S0MA_HOME"] = str(home)
    env["S0MA_CP_HOST"] = cp_host
    return env


def supported_minors(spec: str) -> set[int]:
    """``>=3.A,<3.B``, the launcher's supported range, as the minors A to B-1."""
    found = re.fullmatch(r">=3\.(\d+),<3\.(\d+)", spec)
    expect(found is not None, f"the launcher's supported range is not >=3.A,<3.B: {spec}")
    assert found is not None
    return set(range(int(found.group(1)), int(found.group(2))))


def default_python_dirs(uv: str, cwd: Path) -> list[Path]:
    """uv's own Python folders for this user: its default, and the runner's if set.

    The default is what ``uv python dir`` says with no setting naming one. A
    folder this machine's environment names (a CI action may set one) is
    watched too.
    """
    env = {
        key: value
        for key, value in child_env().items()
        if key.upper() not in ("UV_PYTHON_INSTALL_DIR", "UV_CONFIG_FILE")
    }
    env["UV_NO_CONFIG"] = "1"
    ran = run([uv, "python", "dir"], env, cwd)
    expect(ran.code == 0 and ran.stdout.strip() != "", "uv python dir said nothing")
    folders = [Path(ran.stdout.strip().splitlines()[-1])]
    named = os.environ.get("UV_PYTHON_INSTALL_DIR", "").strip()
    if named and not any(same_dir(named, folder) for folder in folders):
        folders.append(Path(named))
    return folders


def entry_names(folder: Path) -> list[str]:
    """The names directly inside *folder*, without reading any of them."""
    try:
        return sorted(os.listdir(folder))
    except FileNotFoundError:
        return []


def is_under(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def plugin_with_launcher(work: Path, launcher_file: Path) -> Path:
    """A copy of the plugin folder whose launcher is *launcher_file*.

    The lock file beside it is the plugin's own: only the launcher's version
    line differs, and the header the lock matches is the same.
    """
    copy = work / "plugin"
    shutil.copytree(PLUGIN_DIR, copy, symlinks=True)
    shutil.copyfile(launcher_file, copy / "launcher" / "s0ma_launch.py")
    return copy


def deps_are_cached(
    uv: str, index: Path, version: str, launcher: ModuleType, work: Path
) -> bool:
    """Whether every dependency of the built wheels is in uv's cache already.

    A dry run, offline, in a scratch environment made the way this machine's
    uv makes one: no Python is downloaded for it and nothing is installed.
    """
    probe = work / "deps-probe"
    env = child_env({"UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never"})
    ran = run([uv, "venv", str(probe)], env, work)
    if ran.code != 0:
        return False
    python = launcher.venv_python(probe)
    if python is None:
        return False
    ran = run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--dry-run",
            "--find-links",
            str(index),
            launcher.index_requirement(version),
            launcher.PYTEST_REQUIREMENT,
        ],
        env,
        work,
    )
    return ran.code == 0


def leg_python_download(work: Path, results: Results) -> None:
    launcher = load_launcher()
    e2e = import_e2e_helpers()
    from fake_control_plane import FakeControlPlane  # type: ignore[import-not-found]

    banner("uv chooses the Python: none is handed to it and none on this machine may be used")
    project = work / "project"
    project.mkdir()
    # A space in the home, as a Windows user name often has.
    home = work / "s0ma home"
    uv = shutil.which("uv", path=child_env().get("PATH"))
    expect(uv is not None, "the python-download leg found no uv on the PATH")
    assert uv is not None
    say(f"uv is {uv}")
    ran = run([uv, "--version"], child_env(), project)
    results.add("uv", ran.stdout.strip())
    supported = supported_minors(launcher.SUPPORTED_PYTHON)

    watched = default_python_dirs(uv, project)
    before = {folder: entry_names(folder) for folder in watched}
    for folder, names in before.items():
        say(f"before: {folder} holds {names}")

    version_v = e2e.tree_version()
    version_k = f"{e2e.next_patch(version_v)}+{e2e.KEYLESS_LABEL}"
    say(f"the tree is {version_v}; the wheels are built as {version_k}")
    index = e2e.build_keyless_wheels(work / "wheels", version_v, version_k)
    for wheel in sorted(index.glob("*.whl")):
        say(f"built {wheel.name}")
    plugin = plugin_with_launcher(work, e2e.launcher_at_version(work, version_k))

    plane = FakeControlPlane(key="first-run-check-never-sent", work=work / "control-plane")
    plane.start()
    try:
        env = python_download_env(home, plane.host)
        say(f"S0MA_HOME={home}  S0MA_CP_HOST={plane.host}  no license key")
        say(f"UV_PYTHON_PREFERENCE={env['UV_PYTHON_PREFERENCE']}  cleared: {', '.join(PYTHON_STEERING)}")
        install_env = dict(env)
        install_env["UV_FIND_LINKS"] = str(index)
        # The index is left on, as a person's install has it, unless every
        # dependency is already cached here: then the launcher's own offline
        # switch keeps the install to this machine. The Python itself is
        # downloaded either way, by the `uv run` that starts the launcher.
        if deps_are_cached(uv, index, version_k, launcher, work):
            install_env["S0MA_LAUNCH_OFFLINE_INSTALL"] = "1"
            results.add("package index", "not asked: every dependency was in uv's cache")
        else:
            results.add("package index", "asked for the dependencies uv's cache did not hold")

        banner("s0ma-launch install, through the plugin's own command")
        ran = run(launch_command(plugin, "install"), install_env, project, timeout=900)
        expect(ran.code == 0, f"s0ma-launch install exited {ran.code}")
        expect(
            f"s0ma {version_k} is installed." in ran.stdout + ran.stderr,
            "the install did not say it installed the built version",
        )
        results.add("keyless install", f"exit 0, s0ma {version_k} from UV_FIND_LINKS={index.name}/")

        toolchain = launcher.managed_toolchain_dir(home, version_k)
        python = launcher.venv_python(toolchain)
        expect(python is not None, f"no Python in {toolchain}")
        assert python is not None
        ran = run(
            [
                str(python),
                "-c",
                "import json, sys; print(json.dumps([list(sys.version_info[:3]), sys.base_prefix]))",
            ],
            env,
            project,
        )
        expect(ran.code == 0, f"the environment's Python exited {ran.code}")
        numbers, base = json.loads(ran.stdout.strip().splitlines()[-1])
        shown = ".".join(str(n) for n in numbers)
        expect(
            numbers[0] == 3 and numbers[1] in supported,
            f"the environment runs Python {shown}, outside {launcher.SUPPORTED_PYTHON}",
        )
        results.add("environment's Python", f"{shown}, inside {launcher.SUPPORTED_PYTHON}")
        pythons = launcher.python_install_dir(home)
        expect(
            is_under(Path(base), pythons),
            f"the environment's Python lives at {base}, not under {pythons}",
        )
        results.add("environment's Python, where", f"{base}, under the leg's s0ma home")
        results.add("the leg's Python folder", f"{pythons} holds {entry_names(pythons)}")

        for folder in watched:
            after = entry_names(folder)
            say(f"after: {folder} holds {after}")
            expect(
                after == before[folder],
                f"uv's Python folder {folder} changed: {before[folder]} before, {after} after",
            )
            results.add(
                "uv's default Python folder",
                f"{folder}: {before[folder]} before, {after} after, nothing gained",
            )

        ran = run(launch_command(plugin, "status"), env, project)
        expect(ran.code == 0, f"s0ma-launch status exited {ran.code}")
        results.add("s0ma-launch status", "exit 0")

        banner("The installed s0ma in a fresh project")
        bin_dir = launcher.bin_dir_of(toolchain)
        cli = launcher.find_program(bin_dir, "s0ma") if bin_dir is not None else None
        expect(cli is not None, f"no s0ma program in {toolchain}")
        assert cli is not None
        fresh_parent = work / "fresh"
        fresh_parent.mkdir()
        run_fresh_project_steps(cli, env, fresh_parent, results)

        results.add("claude checks", "none in this leg")
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
    parser.add_argument(
        "leg", choices=("uv-absent", "uv-present", "python-download", "e2e", "real-index")
    )
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
    parser.add_argument(
        "--version",
        type=release_version,
        help="real-index only: the released version to install from the package index",
    )
    opts = parser.parse_args(argv)
    if opts.leg in ("real-index", "python-download") and opts.claude:
        parser.error(f"{opts.leg} runs no Claude Code step; leave --claude out")
    if opts.leg == "real-index":
        if opts.version is None:
            parser.error("real-index needs --version, the released version to install")
    else:
        if opts.version is not None:
            parser.error("--version belongs to the real-index leg only")
        if opts.leg in ("uv-absent", "uv-present") and not opts.claude and not opts.no_claude:
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
        elif opts.leg == "real-index":
            leg_real_index(opts, work, results)
        elif opts.leg == "python-download":
            leg_python_download(work, results)
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
