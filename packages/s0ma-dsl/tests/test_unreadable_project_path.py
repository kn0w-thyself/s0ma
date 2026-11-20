"""A path project resolution cannot read ends as one line, not a traceback.

Before any command runs, the CLI resolves the project around the path it was
given: discovery walks up from ``--project-root`` (or the working directory),
and when that finds no project, the positional path is probed for a
``[tool.s0ma]`` table it could have meant. A ``pyproject.toml`` the user may
not read on either walk used to raise ``PermissionError`` before the CLI's own
error handling, so the user got a Python traceback and exit 1. It now stops
the command with one line on stderr that names the path and the reason, and
exit 2, the code for a path argument the command cannot use.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import EXIT_USAGE_ERROR, S0maCLI

if TYPE_CHECKING:
    from collections.abc import Iterator

# Each command reaches resolution with the target as its positional path.
_COMMANDS: list[list[str]] = [
    ["check"],
    ["build"],
    ["migrate", "grammar"],
    ["transpile"],
]
_COMMAND_IDS = [" ".join(argv) for argv in _COMMANDS]


def _mode_change_cannot_lock() -> str | None:
    """Why a mode change cannot make a directory unreadable here, if it cannot."""

    if sys.platform == "win32":
        return "a mode change does not make a directory unreadable on Windows"
    if os.geteuid() == 0:
        return "a run as root reads a directory whatever its mode"
    return None


@contextmanager
def _mode(path: Path, mode: int) -> Iterator[None]:
    original = stat.S_IMODE(path.stat().st_mode)
    path.chmod(mode)
    try:
        yield
    finally:
        path.chmod(original)


def _expected_line(pyproject: Path, reason: str = "Permission denied") -> str:
    return (
        f"Cannot read {pyproject.resolve().as_posix()} ({reason}) "
        f"while resolving the project; nothing ran."
    )


def _run_s0ma(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "s0ma_dsl", *argv],
        cwd=cwd,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )


def _run_cli(
    argv: list[str], capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    code = S0maCLI().run(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _refuse_probe(monkeypatch: pytest.MonkeyPatch, *refused: Path) -> None:
    """Make ``Path.is_file`` raise for *refused*, as a locked directory does."""

    refused_paths = {path.resolve() for path in refused}
    real_is_file = Path.is_file

    def is_file(self: Path) -> bool:
        if self.resolve() in refused_paths:
            raise PermissionError(13, "Permission denied", str(self))
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", is_file)


def _locked_target(root: Path) -> Path:
    target = root / "plain"
    target.mkdir()
    (target / "a.s0ma").write_text("", encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# A real locked directory (skipped where a mode change cannot lock one)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_mode_change_cannot_lock() is not None,
                    reason=_mode_change_cannot_lock() or "")
@pytest.mark.parametrize("command", _COMMANDS, ids=_COMMAND_IDS)
def test_a_locked_positional_path_ends_in_one_line_and_exit_2(
    tmp_path: Path, command: list[str],
) -> None:
    target = _locked_target(tmp_path)
    with _mode(target, 0):
        proc = _run_s0ma([*command, "plain"], cwd=tmp_path)
    assert "Traceback" not in proc.stderr
    assert proc.stderr.splitlines() == [_expected_line(target / "pyproject.toml")]
    assert proc.stdout == ""
    assert proc.returncode == EXIT_USAGE_ERROR


@pytest.mark.skipif(_mode_change_cannot_lock() is not None,
                    reason=_mode_change_cannot_lock() or "")
@pytest.mark.parametrize("command", _COMMANDS, ids=_COMMAND_IDS)
def test_a_locked_project_root_ends_in_one_line_and_exit_2(
    tmp_path: Path, command: list[str],
) -> None:
    target = _locked_target(tmp_path)
    (target / "pyproject.toml").write_text("[tool.s0ma]\n", encoding="utf-8")
    with _mode(target, 0):
        proc = _run_s0ma(["--project-root", "plain", *command, "plain"], cwd=tmp_path)
    assert "Traceback" not in proc.stderr
    assert proc.stderr.splitlines() == [_expected_line(target / "pyproject.toml")]
    assert proc.returncode == EXIT_USAGE_ERROR


@pytest.mark.skipif(_mode_change_cannot_lock() is not None,
                    reason=_mode_change_cannot_lock() or "")
def test_a_project_file_that_cannot_be_opened_ends_in_one_line_and_exit_2(
    tmp_path: Path,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.s0ma]\n", encoding="utf-8")
    with _mode(pyproject, 0):
        proc = _run_s0ma(["check", "."], cwd=tmp_path)
    assert "Traceback" not in proc.stderr
    assert proc.stderr.splitlines() == [_expected_line(pyproject)]
    assert proc.returncode == EXIT_USAGE_ERROR


# ---------------------------------------------------------------------------
# A refused probe, on every platform
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", _COMMANDS, ids=_COMMAND_IDS)
def test_a_refused_probe_of_the_positional_path_ends_in_one_line_and_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    target = _locked_target(tmp_path)
    monkeypatch.chdir(tmp_path)
    _refuse_probe(monkeypatch, target / "pyproject.toml")
    code, out, err = _run_cli([*command, "plain"], capsys)
    assert err.splitlines() == [_expected_line(target / "pyproject.toml")]
    assert out == ""
    assert code == EXIT_USAGE_ERROR


@pytest.mark.parametrize("command", _COMMANDS, ids=_COMMAND_IDS)
def test_a_refused_probe_of_the_project_root_ends_in_one_line_and_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    target = _locked_target(tmp_path)
    monkeypatch.chdir(tmp_path)
    _refuse_probe(monkeypatch, target / "pyproject.toml")
    code, out, err = _run_cli(
        ["--project-root", "plain", *command, "plain"], capsys,
    )
    assert err.splitlines() == [_expected_line(target / "pyproject.toml")]
    assert out == ""
    assert code == EXIT_USAGE_ERROR


# ---------------------------------------------------------------------------
# A readable path is untouched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", _COMMANDS, ids=_COMMAND_IDS)
def test_a_readable_path_runs_as_before(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    """A refused probe somewhere else changes nothing for a readable target."""

    _locked_target(tmp_path)
    monkeypatch.chdir(tmp_path)
    expected = _run_cli([*command, "plain"], capsys)
    _refuse_probe(monkeypatch, tmp_path / "elsewhere" / "pyproject.toml")
    assert _run_cli([*command, "plain"], capsys) == expected
    assert "while resolving the project" not in expected[2]


def test_a_readable_path_without_a_project_keeps_its_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "plain").mkdir()
    monkeypatch.chdir(tmp_path)
    code, _out, err = _run_cli(["build", "plain"], capsys)
    assert err.splitlines() == [
        "warning: Operating without project discovery. "
        "Add `[tool.s0ma]` to pyproject.toml for full functionality.",
        "No .s0ma files found in: plain",
    ]
    assert code == EXIT_USAGE_ERROR
