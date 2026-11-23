"""The first-run driver's own parts, on any machine, with no Claude and no uv needed.

``scripts/first_run_check.py`` is what the first-run workflow runs on GitHub's
runners. Its full checks need a machine with no uv and the real Claude Code, so
they run there. What is tested here is what lets those checks fail: the driver
refuses to start without being told whether to run Claude, it reads ``claude
mcp list`` lines in both sets of marks and calls a failed server failed, its
MCP client fails on a server that says nothing or writes something that is not
JSON, and it takes Git's shell off a Windows ``PATH`` while keeping ``Git\\cmd``.

Nothing here runs Claude: no test passes ``--claude``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DRIVER = REPO_ROOT / "scripts" / "first_run_check.py"


@pytest.fixture(scope="module")
def driver() -> ModuleType:
    spec = importlib.util.spec_from_file_location("first_run_check_for_tests", DRIVER)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise RuntimeError(f"could not load {DRIVER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("leg", ["uv-absent", "uv-present"])
def test_the_driver_will_not_start_without_being_told_about_claude(leg: str) -> None:
    done = subprocess.run(  # noqa: S603 - this repository's own script
        [sys.executable, str(DRIVER), leg],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 2
    assert "--claude <command> or --no-claude" in done.stderr


def test_claude_needs_a_version_to_hold_it_to() -> None:
    done = subprocess.run(  # noqa: S603 - this repository's own script
        [sys.executable, str(DRIVER), "uv-absent", "--claude", "claude"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 2
    assert "--claude needs --claude-version" in done.stderr


@pytest.mark.parametrize(
    ("line", "connected"),
    [
        ("plugin:s0ma:s0ma: /x/plugin/scripts/s0ma-serve  - ✔ Connected", True),
        ("plugin:s0ma:s0ma: C:/x/plugin/scripts/s0ma-serve  - √ Connected", True),
        (
            "plugin:s0ma:s0ma: /x/plugin/scripts/s0ma-serve  - ✘ Failed to connect",
            False,
        ),
        (
            "plugin:s0ma:s0ma: C:/x/plugin/scripts/s0ma-serve  - × Failed to connect",
            False,
        ),
        ("plugin:s0ma:s0ma: /x/Connected/s0ma-serve  - ✘ Failed to connect", False),
    ],
)
def test_a_server_line_is_read_in_either_set_of_marks(
    driver: ModuleType, line: str, connected: bool
) -> None:
    output = f"Checking MCP server health...\n\n{line}\n"
    assert driver.server_line(output) == line
    assert driver.is_connected(line) is connected


def test_no_server_line_is_a_failure(driver: ModuleType) -> None:
    with pytest.raises(driver.CheckFailed):
        driver.server_line("No MCP servers configured.\n")


def test_git_shell_comes_off_a_windows_path_and_git_cmd_stays(
    driver: ModuleType,
) -> None:
    path = ";".join(
        [
            r"C:\Program Files\Git\bin",
            r"C:\Program Files\Git\usr\bin",
            r"C:\Program Files\Git\mingw64\bin",
            r"C:\Program Files\Git\cmd",
            r"C:\Windows\System32",
        ]
    )
    kept, dropped = driver.without_git_shell(path, ";")
    assert kept.split(";") == [r"C:\Program Files\Git\cmd", r"C:\Windows\System32"]
    assert len(dropped) == 3


def fake_server(body: str) -> list[str]:
    return [sys.executable, "-c", body]


def test_a_server_that_says_nothing_fails(driver: ModuleType, tmp_path: Path) -> None:
    session = driver.McpSession(
        fake_server("import sys; sys.stdin.readline()"), None, tmp_path
    )
    try:
        with pytest.raises(driver.CheckFailed, match="closed its output"):
            session.initialize()
    finally:
        session.kill()


def test_a_server_that_writes_something_else_fails(
    driver: ModuleType, tmp_path: Path
) -> None:
    body = "import sys; sys.stdin.readline(); print('hello'); sys.stdout.flush()"
    session = driver.McpSession(fake_server(body), None, tmp_path)
    try:
        with pytest.raises(driver.CheckFailed, match="not JSON"):
            session.initialize()
    finally:
        session.kill()


def test_a_server_that_answers_with_the_wrong_id_fails(
    driver: ModuleType, tmp_path: Path
) -> None:
    body = (
        "import sys; sys.stdin.readline(); "
        'print(\'{"jsonrpc":"2.0","id":7,"result":{}}\'); sys.stdout.flush()'
    )
    session = driver.McpSession(fake_server(body), None, tmp_path)
    try:
        with pytest.raises(driver.CheckFailed, match="id 0"):
            session.initialize()
    finally:
        session.kill()
