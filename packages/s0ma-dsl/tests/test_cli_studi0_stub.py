"""M1 (studi0 v1) — the ``s0ma studi0`` launcher contract.

The transpiler must not depend on the viewer. ``s0ma studi0`` imports
``s0ma_studi0`` lazily, inside the handler, and hands it the parsed
arguments through the frozen ``launch(project_root, *, port,
open_browser) -> int`` signature (studi0 plan §3.3/§3.4).

``s0ma_studi0`` is a workspace member, so it is importable while these
tests run. Absence is therefore simulated the way the interpreter itself
signals a blocked import: ``sys.modules["s0ma_studi0"] = None`` makes any
subsequent import raise ``ImportError``.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma_dsl.cli.main import EXIT_SUCCESS, EXIT_USAGE_ERROR, S0maCLI

if TYPE_CHECKING:
    import pytest

STUDI0_MODULE = "s0ma_studi0"


class _LaunchRecorder:
    """A stand-in for ``s0ma_studi0.launch`` that records how it was called."""

    def __init__(self, exit_code: int = EXIT_SUCCESS) -> None:
        self.exit_code = exit_code
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> int:
        self.calls.append((args, kwargs))
        return self.exit_code


def _install_stub(
    monkeypatch: pytest.MonkeyPatch, exit_code: int = EXIT_SUCCESS
) -> _LaunchRecorder:
    """Put a stub ``s0ma_studi0`` in ``sys.modules`` for the test's duration."""
    recorder = _LaunchRecorder(exit_code)
    module = types.ModuleType(STUDI0_MODULE)
    module.launch = recorder  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, STUDI0_MODULE, module)
    return recorder


def _block_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import s0ma_studi0`` raise ImportError, as if it were not installed."""
    monkeypatch.setitem(sys.modules, STUDI0_MODULE, None)


# ---------------------------------------------------------------------------
# Parser contract
# ---------------------------------------------------------------------------


def test_parser_defaults() -> None:
    """``project_root`` is optional; the port defaults to OS-assigned."""
    args = S0maCLI().build_parser().parse_args(["studi0"])
    assert args.command == "studi0"
    assert args.project_root is None
    assert args.port == 0
    assert args.no_open is False


def test_parser_accepts_port_and_no_open() -> None:
    args = S0maCLI().build_parser().parse_args([
        "studi0", "some/project", "--port", "8123", "--no-open",
    ])
    assert args.project_root == "some/project"
    assert args.port == 8123
    assert args.no_open is True


# ---------------------------------------------------------------------------
# Package absent
# ---------------------------------------------------------------------------


def test_missing_package_prints_one_hint_block(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Absence is a usage error carrying exactly one actionable hint block."""
    _block_import(monkeypatch)

    rc = S0maCLI().run(["studi0", str(tmp_path)])
    assert rc == EXIT_USAGE_ERROR

    err = capsys.readouterr().err
    # Exactly one block: one statement of the problem, one remediation.
    assert err.count("is not importable in this environment") == 1
    assert err.count("Remediation:") == 1
    assert err.count("Install the `s0ma-studi0` wheel") == 1
    # The remediation must never name a PyPI install route (PRD NFR-8).
    assert "pip install s0ma-studi0" not in err
    assert "s0ma studi0: the optional `s0ma-studi0` package" in err
    # It says what studi0 is, not merely that something failed.
    assert "component graph" in err
    # A hint, never a traceback.
    assert "Traceback" not in err
    assert "Internal error" not in err


def test_missing_package_does_not_crash_without_a_positional(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The cwd default is resolved before the import is attempted."""
    _block_import(monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert S0maCLI().run(["studi0"]) == EXIT_USAGE_ERROR
    err = capsys.readouterr().err
    assert "Install the `s0ma-studi0` wheel" in err
    # The hint names the directory it would have served.
    assert str(Path.cwd()) in err


# ---------------------------------------------------------------------------
# Package present
# ---------------------------------------------------------------------------


def test_launch_receives_parsed_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Parsed arguments reach ``launch`` through the frozen signature."""
    recorder = _install_stub(monkeypatch)

    rc = S0maCLI().run([
        "studi0", str(tmp_path), "--port", "8123", "--no-open",
    ])

    assert rc == EXIT_SUCCESS
    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]
    assert args == (Path(tmp_path),)
    assert kwargs == {"port": 8123, "open_browser": False}


def test_launch_defaults_to_cwd_and_opens_a_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No positional: the current working directory, ephemeral port, browser on."""
    recorder = _install_stub(monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert S0maCLI().run(["studi0"]) == EXIT_SUCCESS

    args, kwargs = recorder.calls[0]
    assert args == (Path.cwd(),)
    assert kwargs == {"port": 0, "open_browser": True}


def test_launch_exit_code_is_the_command_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The viewer owns its own outcome; the CLI passes it through."""
    _install_stub(monkeypatch, exit_code=7)
    assert S0maCLI().run(["studi0", str(tmp_path)]) == 7


def test_studi0_is_not_imported_by_other_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The lazy import is real: an unrelated command runs with the import blocked."""
    _block_import(monkeypatch)
    # ``graph`` against an empty directory: a usage error from the graph
    # path, which proves the CLI imported and dispatched fine without
    # ever touching s0ma_studi0.
    assert S0maCLI().run(["graph", str(tmp_path)]) == EXIT_USAGE_ERROR
