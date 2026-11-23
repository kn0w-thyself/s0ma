"""The plugin's scripts, run for real: the hook, the server, and their Windows twins.

Each script is run as Claude Code would run it, through a real shell and real
pipes, with a ``PATH`` and a home of the test's own making:

* **``hooks/session-start.sh``** under ``sh`` (Git Bash on Windows CI): with no
  uv it prints the one message and exits 0 with nothing on stderr; with a uv
  that fails it does the same; with one that works it passes the launcher's
  line through.
* **``scripts/s0ma-serve``** under ``sh``: with a uv that has a Python it
  hands over to the launcher's ``serve`` with ``--frozen`` and downloads off;
  without one it is the stand-in server, which a small test client drives
  over stdin and stdout.
* **``scripts/s0ma-stand-in.ps1``** under Windows PowerShell, and the ``.cmd``
  twins, on Windows only.

The stand-ins' answers are compared with the launcher's own setup helper,
read from its functions, so the two cannot say different things.

Nothing here opens a socket, and nothing here runs Claude.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "integrations" / "claude" / "plugin"
LAUNCHER_PATH = REPO_ROOT / "integrations" / "launcher" / "s0ma_launch.py"

HOOK_SCRIPT = PLUGIN_DIR / "hooks" / "session-start.sh"
SERVER_SCRIPT = PLUGIN_DIR / "scripts" / "s0ma-serve"
SERVER_CMD = PLUGIN_DIR / "scripts" / "s0ma-serve.cmd"
STAND_IN_PS1 = PLUGIN_DIR / "scripts" / "s0ma-stand-in.ps1"
MESSAGE_FILE = PLUGIN_DIR / "scripts" / "not-set-up.txt"
SHIM_CMDS = (PLUGIN_DIR / "bin" / "s0ma.cmd", PLUGIN_DIR / "bin" / "s0ma-launch.cmd")

WINDOWS = sys.platform.startswith("win")

#: The places uv may live that no environment variable can move. A machine
#: with uv in one of them cannot be made to look uv-less from here.
FIXED_UV_PLACES = (Path("/opt/homebrew/bin/uv"), Path("/usr/local/bin/uv"))

TIMEOUT = 60


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("s0ma_launch_for_script_tests", LAUNCHER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise RuntimeError(f"could not load the launcher from {LAUNCHER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def find_sh() -> str | None:
    """A POSIX ``sh``: the system's, or Git's on Windows."""
    found = shutil.which("sh")
    if found:
        return found
    if WINDOWS:
        for root in (os.environ.get("ProgramFiles", ""), r"C:\Program Files"):
            candidate = Path(root) / "Git" / "bin" / "sh.exe"
            if root and candidate.is_file():
                return str(candidate)
    return None


SH = find_sh()
needs_sh = pytest.mark.skipif(SH is None, reason="no POSIX sh on this machine")
windows_only = pytest.mark.skipif(not WINDOWS, reason="the Windows twins run on Windows only")


def posix(path: Path | str) -> str:
    """A path as a POSIX shell reads it; Git Bash takes ``C:/x`` too."""
    return Path(path).as_posix()


def message() -> str:
    return MESSAGE_FILE.read_text(encoding="ascii").rstrip("\n")


def base_dirs() -> list[Path]:
    """What the scripts need on the ``PATH`` besides uv: the shell's own tools.

    ``sed`` above all, which the stand-in server uses. On Windows that is
    System32, and Git's ``usr/bin`` beside the ``sh`` in use.
    """
    if not WINDOWS:
        dirs = [Path("/usr/bin"), Path("/bin")]
    else:
        dirs = [Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"]
        if SH is not None:
            git_root = Path(SH).resolve().parent.parent
            dirs.append(git_root / "usr" / "bin")
    return [d for d in dirs if d.is_dir()]


def isolated_env(tmp_path: Path, path_dirs: list[Path]) -> dict[str, str]:
    """An environment where uv is only where the test puts it."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("UV_", "S0MA_")) and key.upper() not in {"VIRTUAL_ENV"}
    }
    base = [str(d) for d in base_dirs()]
    env["PATH"] = os.pathsep.join([*(str(d) for d in path_dirs), *base])
    env["HOME"] = str(home)
    for name in ("USERPROFILE", "LOCALAPPDATA", "ProgramFiles"):
        env[name] = str(home)
    env["S0MA_HOME"] = str(tmp_path / "s0ma-home")
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    return env


def stand_in_uv(directory: Path, body: str) -> Path:
    """A POSIX ``uv`` that does what *body* says, first on the ``PATH``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "uv"
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return path


def run_sh(script: Path, env: dict[str, str], stdin: str = "") -> subprocess.CompletedProcess[str]:
    assert SH is not None
    return subprocess.run(  # noqa: S603 - a fixed, local command
        [SH, posix(script)],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=TIMEOUT,
        check=False,
    )


def skip_if_uv_is_fixed() -> None:
    for directory in base_dirs():
        if shutil.which("uv", path=str(directory)):
            pytest.skip(f"uv is in {directory}, which the scripts need on the PATH")
    for place in FIXED_UV_PLACES:
        if place.exists():
            pytest.skip(f"uv is installed at {place}, which no environment can hide")


# ---------------------------------------------------------------------------
# hooks/session-start.sh
# ---------------------------------------------------------------------------


@needs_sh
def test_the_hook_with_no_uv_prints_the_message(tmp_path: Path) -> None:
    skip_if_uv_is_fixed()
    env = isolated_env(tmp_path, [tmp_path / "empty"])
    result = run_sh(HOOK_SCRIPT, env)
    assert result.returncode == 0
    assert result.stdout == message() + "\n"
    assert result.stderr == ""


@needs_sh
def test_the_hook_with_a_failing_uv_prints_the_message(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    stand_in_uv(bin_dir, 'echo "uv: no Python here" >&2\nexit 2\n')
    result = run_sh(HOOK_SCRIPT, isolated_env(tmp_path, [bin_dir]))
    assert result.returncode == 0
    assert result.stdout == message() + "\n"
    assert result.stderr == ""


@needs_sh
def test_the_hook_passes_the_launchers_line_through(tmp_path: Path) -> None:
    """A stand-in uv that runs the launcher with this Python, after checking
    that it was asked to fetch nothing."""
    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "args.txt"
    stand_in_uv(
        bin_dir,
        f'printf \'%s\\n\' "$@" > "{posix(args_file)}"\n'
        "while [ $# -gt 0 ]; do\n"
        f'    if [ "$1" = --script ]; then shift; exec "{posix(sys.executable)}" "$@"; fi\n'
        "    shift\n"
        "done\n"
        "exit 9\n",
    )
    env = isolated_env(tmp_path, [bin_dir])
    result = run_sh(HOOK_SCRIPT, env)
    expected = subprocess.run(  # noqa: S603 - a fixed, local command
        [sys.executable, str(PLUGIN_DIR / "launcher" / "s0ma_launch.py"), "session-hint"],
        capture_output=True,
        text=True,
        env=env,
        timeout=TIMEOUT,
        check=False,
    ).stdout
    assert result.returncode == 0
    assert result.stderr == ""
    assert expected.strip(), "the launcher should have something to say with nothing installed"
    assert result.stdout == expected
    asked = args_file.read_text(encoding="utf-8").split()
    assert asked[0] == "run"
    for flag in ("--frozen", "--offline", "--no-python-downloads"):
        assert flag in asked
    assert asked[-1] == "session-hint"


@needs_sh
def test_the_hook_stays_quiet_when_the_launcher_has_nothing_to_say(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    stand_in_uv(bin_dir, "exit 0\n")
    result = run_sh(HOOK_SCRIPT, isolated_env(tmp_path, [bin_dir]))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@needs_sh
def test_the_hook_exits_0_even_with_its_launcher_missing(tmp_path: Path) -> None:
    """A broken copy of the plugin is still no reason for a hook error."""
    root = tmp_path / "plugin"
    (root / "hooks").mkdir(parents=True)
    shutil.copyfile(HOOK_SCRIPT, root / "hooks" / "session-start.sh")
    bin_dir = tmp_path / "bin"
    stand_in_uv(bin_dir, 'echo "no such file" >&2\nexit 2\n')
    result = run_sh(root / "hooks" / "session-start.sh", isolated_env(tmp_path, [bin_dir]))
    assert (result.returncode, result.stderr) == (0, "")


# ---------------------------------------------------------------------------
# The stand-in server: a small client.
# ---------------------------------------------------------------------------

#: What Claude Code sends, in the key order it uses: method, params, jsonrpc, id.
def request(method: str, message_id: Any, params: dict[str, Any] | None = None) -> str:
    body: dict[str, Any] = {"method": method}
    if params is not None:
        body["params"] = params
    body["jsonrpc"] = "2.0"
    body["id"] = message_id
    return json.dumps(body)


def request_id_first(method: str, message_id: Any) -> str:
    return json.dumps({"id": message_id, "jsonrpc": "2.0", "method": method})


INITIALIZE_PARAMS = {
    "protocolVersion": "2025-06-18",
    "capabilities": {"roots": {}, "elicitation": {}},
    "clientInfo": {"name": "claude-code", "version": "2.1.330"},
}

CONVERSATION = [
    request("initialize", 0, INITIALIZE_PARAMS),
    json.dumps({"method": "notifications/initialized", "jsonrpc": "2.0"}),
    request("ping", 1),
    request_id_first("ping", "two"),
    request("tools/list", "3", {}),
    request("tools/call", 4, {"name": "s0ma_setup_status", "arguments": {}}),
    request_id_first("resources/list", 5),
    request("prompts/list", "six", {}),
]
EXPECTED_IDS = [0, 1, "two", "3", 4, 5, "six"]


def converse(argv: list[str], env: dict[str, str]) -> tuple[list[dict[str, Any]], str, int]:
    """Send the conversation through real pipes; return the answers, stdout, code.

    The first exchange is made one line at a time, so a server that waited
    for the end of its input before answering would be caught.
    """
    process = subprocess.Popen(  # noqa: S603 - a fixed, local command
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert process.stdin is not None and process.stdout is not None
    first: list[bytes] = []

    def read_one() -> None:
        assert process.stdout is not None
        first.append(process.stdout.readline())

    process.stdin.write((CONVERSATION[0] + "\n").encode("utf-8"))
    process.stdin.flush()
    reader = threading.Thread(target=read_one, daemon=True)
    reader.start()
    reader.join(TIMEOUT)
    assert first, "no answer to initialize before the input ended"
    rest = "".join(line + "\n" for line in CONVERSATION[1:]).encode("utf-8")
    out, _ = process.communicate(rest, timeout=TIMEOUT)
    stdout = (first[0] + out).decode("utf-8")
    lines = stdout.splitlines()
    answers = [json.loads(line) for line in lines]
    return answers, stdout, process.returncode


def check_conversation(
    answers: list[dict[str, Any]], stdout: str, code: int, launcher: ModuleType
) -> None:
    assert code == 0
    assert stdout.endswith("\n")
    assert [answer["id"] for answer in answers] == EXPECTED_IDS, "one answer per request, in order"
    for answer in answers:
        assert answer["jsonrpc"] == "2.0"
    init, ping_one, ping_two, tools, call, unknown_one, unknown_two = answers
    assert init["result"] == {
        "protocolVersion": "2025-06-18",
        "capabilities": {"tools": {}},
        "serverInfo": launcher.stub_server_info(),
        "instructions": message(),
    }
    assert ping_one["result"] == {} and ping_two["result"] == {}
    assert tools["result"] == {"tools": [launcher.stub_tool()]}
    assert call["result"] == launcher.stub_text_result(message())
    for unknown in (unknown_one, unknown_two):
        assert unknown["error"]["code"] == launcher.JSONRPC_METHOD_NOT_FOUND
        assert "result" not in unknown


def negotiated(argv: list[str], env: dict[str, str], asked: object) -> str:
    params = {**INITIALIZE_PARAMS, "protocolVersion": asked}
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        argv,
        input=request("initialize", 1, params) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=TIMEOUT,
        check=False,
    )
    version = json.loads(result.stdout)["result"]["protocolVersion"]
    assert isinstance(version, str)
    return version


def check_negotiation(argv: list[str], env: dict[str, str], launcher: ModuleType) -> None:
    for asked in (*launcher.STUB_PROTOCOL_VERSIONS, "1999-01-01"):
        assert negotiated(argv, env, asked) == launcher.negotiate_protocol_version(asked)


# ---------------------------------------------------------------------------
# scripts/s0ma-serve, the stand-in in sh.
# ---------------------------------------------------------------------------


def no_python_uv(tmp_path: Path) -> Path:
    """A uv that is there but has no usable Python, and records being asked."""
    bin_dir = tmp_path / "bin"
    stand_in_uv(
        bin_dir,
        'if [ "$1" = python ]; then echo "no interpreter found" >&2; exit 2; fi\n'
        f'echo ran >> "{posix(tmp_path / "ran.txt")}"\nexit 0\n',
    )
    return bin_dir


@needs_sh
def test_the_sh_stand_in_speaks_mcp(tmp_path: Path, launcher: ModuleType) -> None:
    assert SH is not None
    bin_dir = no_python_uv(tmp_path)
    env = isolated_env(tmp_path, [bin_dir])
    answers, stdout, code = converse([SH, posix(SERVER_SCRIPT)], env)
    check_conversation(answers, stdout, code, launcher)
    assert not (tmp_path / "ran.txt").exists(), "nothing was handed over"


@needs_sh
def test_the_sh_stand_in_with_no_uv_at_all(tmp_path: Path, launcher: ModuleType) -> None:
    skip_if_uv_is_fixed()
    assert SH is not None
    env = isolated_env(tmp_path, [tmp_path / "empty"])
    answers, stdout, code = converse([SH, posix(SERVER_SCRIPT)], env)
    check_conversation(answers, stdout, code, launcher)


@needs_sh
def test_the_sh_stand_in_negotiates_like_the_launcher(
    tmp_path: Path, launcher: ModuleType
) -> None:
    assert SH is not None
    env = isolated_env(tmp_path, [no_python_uv(tmp_path)])
    check_negotiation([SH, posix(SERVER_SCRIPT)], env, launcher)


@needs_sh
def test_the_server_hands_over_with_nothing_to_fetch(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "args.txt"
    stand_in_uv(
        bin_dir,
        'if [ "$1" = python ]; then exit 0; fi\n'
        f'printf \'%s\\n\' "$@" > "{posix(args_file)}"\n'
        "echo handed-over\n",
    )
    result = run_sh(SERVER_SCRIPT, isolated_env(tmp_path, [bin_dir]))
    assert result.returncode == 0
    assert result.stdout == "handed-over\n"
    asked = args_file.read_text(encoding="utf-8").splitlines()
    assert asked[0] == "run"
    assert "--frozen" in asked or "--locked" in asked
    for flag in ("--offline", "--no-python-downloads"):
        assert flag in asked
    assert asked[-1] == "serve"
    assert asked[-2].endswith("/scripts/../launcher/s0ma_launch.py")


@pytest.mark.skipif(shutil.which("uv") is None, reason="no uv on PATH to hand over to")
@needs_sh
def test_the_server_hands_over_to_the_real_launcher(tmp_path: Path, launcher: ModuleType) -> None:
    """With the real uv and nothing installed, the launcher's own helper answers."""
    assert SH is not None
    uv = shutil.which("uv")
    assert uv is not None
    env = isolated_env(tmp_path, [Path(uv).parent, Path(sys.executable).parent])
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        [SH, posix(SERVER_SCRIPT)],
        input=request("initialize", 7, INITIALIZE_PARAMS) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=TIMEOUT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    answer = json.loads(result.stdout.splitlines()[0])
    assert answer["id"] == 7
    assert answer["result"]["serverInfo"] == launcher.stub_server_info()
    assert answer["result"]["instructions"] != message(), "the launcher answered, not the stand-in"


# ---------------------------------------------------------------------------
# Windows: the PowerShell stand-in and the .cmd twins.
# ---------------------------------------------------------------------------


def windows_powershell() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return str(Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def powershell_argv() -> list[str]:
    return [
        windows_powershell(),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(STAND_IN_PS1),
    ]


@windows_only
def test_the_powershell_stand_in_speaks_mcp(tmp_path: Path, launcher: ModuleType) -> None:
    env = isolated_env(tmp_path, [])
    answers, stdout, code = converse(powershell_argv(), env)
    check_conversation(answers, stdout, code, launcher)


@windows_only
def test_the_powershell_stand_in_negotiates_like_the_launcher(
    tmp_path: Path, launcher: ModuleType
) -> None:
    check_negotiation(powershell_argv(), isolated_env(tmp_path, []), launcher)


@windows_only
def test_the_cmd_server_with_no_uv_is_the_stand_in(tmp_path: Path, launcher: ModuleType) -> None:
    env = isolated_env(tmp_path, [])
    answers, stdout, code = converse([str(SERVER_CMD)], env)
    check_conversation(answers, stdout, code, launcher)


@windows_only
@pytest.mark.skipif(shutil.which("uv") is None, reason="no uv on PATH to hand over to")
def test_the_cmd_server_hands_over_to_the_real_launcher(
    tmp_path: Path, launcher: ModuleType
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    env = isolated_env(tmp_path, [Path(uv).parent, Path(sys.executable).parent])
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        [str(SERVER_CMD)],
        input=request("initialize", 7, INITIALIZE_PARAMS) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=TIMEOUT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    answer = json.loads(result.stdout.splitlines()[0])
    assert answer["result"]["serverInfo"] == launcher.stub_server_info()
    assert answer["result"]["instructions"] != message()


@windows_only
@pytest.mark.parametrize("shim", SHIM_CMDS, ids=lambda path: path.name)
def test_a_cmd_shim_with_no_uv_says_so_and_exits_7(tmp_path: Path, shim: Path) -> None:
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        [str(shim), "status"],
        capture_output=True,
        text=True,
        env=isolated_env(tmp_path, []),
        timeout=TIMEOUT,
        check=False,
    )
    assert result.returncode == 7
    assert result.stdout == ""
    assert "s0ma needs a small program called uv" in result.stderr


@windows_only
@pytest.mark.skipif(shutil.which("uv") is None, reason="no uv on PATH to copy")
def test_a_cmd_shim_finds_uv_where_its_installer_puts_it(tmp_path: Path) -> None:
    """uv only in ``%USERPROFILE%\\.local\\bin``, not on the PATH."""
    uv = shutil.which("uv")
    assert uv is not None
    env = isolated_env(tmp_path, [Path(sys.executable).parent])
    if shutil.which("uv", path=env["PATH"]):
        pytest.skip("uv sits beside this Python, so it cannot be kept off the PATH")
    place = Path(env["USERPROFILE"]) / ".local" / "bin"
    place.mkdir(parents=True)
    shutil.copyfile(uv, place / "uv.exe")
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        [str(PLUGIN_DIR / "bin" / "s0ma-launch.cmd"), "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=TIMEOUT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "s0ma-launch" in result.stdout
