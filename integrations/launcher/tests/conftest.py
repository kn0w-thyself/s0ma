"""Shared fixtures for the launcher's tests.

Two rules hold for every test in this directory, and the autouse fixture below
is what enforces them:

* **The real ``~/.s0ma`` is never touched.** ``S0MA_HOME`` always points inside
  ``tmp_path``.
* **The real working directory is never the project under test.** The launcher
  reads the working directory when Claude has not set ``CLAUDE_PROJECT_DIR``,
  and this repository's own checkout has a ``.venv`` with s0ma in it - a test
  run from there would "find" a project toolchain that has nothing to do with
  the case being tested.

Every variable the launcher reads is cleared for the same reason: a developer
who happens to have ``S0MA_LICENSE_KEY`` exported must get the same test result
as a clean machine.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

LAUNCHER_PATH = Path(__file__).resolve().parents[1] / "s0ma_launch.py"

#: Everything the launcher consults. Cleared before every test.
LAUNCHER_ENV_VARS = (
    "S0MA_HOME",
    "S0MA_LICENSE_KEY",
    "S0MA_TOOLCHAIN",
    "S0MA_UPDATE",
    "S0MA_CP_HOST",
    "CLAUDE_PROJECT_DIR",
    "CLAUDE_PLUGIN_DATA",
)

#: An obviously fake key. Never a real shape, never a real value. Its last four
#: characters are what a test expects to see in a redacted message.
FAKE_LICENSE_KEY = "s0ma_test_not_a_real_key_wxyz"
FAKE_LICENSE_KEY_LAST4 = "wxyz"


def _load_launcher() -> ModuleType:
    """Import ``s0ma_launch.py`` straight from its path.

    The launcher is one standalone file with no package around it - that is the
    point of it - so it is loaded the way ``uv run --script`` would find it,
    rather than by adding directories to ``sys.path``.
    """
    spec = importlib.util.spec_from_file_location("s0ma_launch", LAUNCHER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - a broken checkout
        raise RuntimeError(f"could not load the launcher from {LAUNCHER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def launcher() -> ModuleType:
    """The launcher module, imported once for the whole run."""
    return _load_launcher()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the launcher at a throwaway state directory and a throwaway project.

    Returns the state directory. The working directory becomes
    ``tmp_path/project``, which is also what the launcher will treat as the
    project unless a test says otherwise.
    """
    for name in LAUNCHER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "s0ma-home"
    home.mkdir(parents=True, exist_ok=True)
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("S0MA_HOME", str(home))
    monkeypatch.chdir(project)
    return home


@pytest.fixture
def fake_key() -> str:
    """An obviously fake license key, for tests that need one to exist."""
    return FAKE_LICENSE_KEY


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """The working directory the launcher sees, created by :func:`isolated_home`."""
    return tmp_path / "project"


@pytest.fixture
def make_venv() -> Any:
    """Build a virtual-environment-shaped directory, in either platform's layout.

    ``windows=True`` produces ``Scripts/s0ma-mcp.exe`` and
    ``Lib/site-packages``; the default produces ``bin/s0ma-mcp`` and
    ``lib/python3.11/site-packages``. Both shapes are built and read on whatever
    machine the tests run on, which is how the Windows layout is covered from a
    POSIX machine.
    """

    def _make(
        root: Path,
        *,
        windows: bool = False,
        programs: tuple[str, ...] = ("s0ma-mcp", "s0ma"),
        version: str | None = None,
        distribution: str = "s0ma_mcp",
    ) -> Path:
        suffix = ".exe" if windows else ""
        bin_dir = root / ("Scripts" if windows else "bin")
        bin_dir.mkdir(parents=True, exist_ok=True)
        for name in programs:
            program = bin_dir / (name + suffix)
            program.write_text("fake program\n", encoding="utf-8")
        if version is not None:
            if windows:
                site_packages = root / "Lib" / "site-packages"
            else:
                site_packages = root / "lib" / "python3.11" / "site-packages"
            dist_info = site_packages / f"{distribution}-{version}.dist-info"
            dist_info.mkdir(parents=True, exist_ok=True)
            (dist_info / "METADATA").write_text("fake metadata\n", encoding="utf-8")
        return bin_dir

    return _make


@pytest.fixture
def make_toolchain(launcher: ModuleType, isolated_home: Path, make_venv: Any) -> Any:
    """Install a fake managed toolchain under ``S0MA_HOME/toolchains/<version>``.

    ``complete=False`` leaves out the ``.complete`` marker, which is how a build
    that was interrupted part-way looks on disk.
    """

    def _make(
        version: str,
        *,
        windows: bool = False,
        complete: bool = True,
        programs: tuple[str, ...] = ("s0ma-mcp", "s0ma"),
        home: Path | None = None,
    ) -> Path:
        root = launcher.managed_toolchain_dir(home or isolated_home, version)
        make_venv(root, windows=windows, programs=programs)
        if complete:
            (root / launcher.COMPLETE_MARKER).write_text("", encoding="utf-8")
        return root

    return _make


@pytest.fixture
def run_cli(launcher: ModuleType, capsys: pytest.CaptureFixture[str]) -> Any:
    """Run one launcher command and return ``(exit_code, stdout, stderr)``."""

    def _run(*args: str) -> tuple[int, str, str]:
        code = launcher.main(list(args))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


class FakeProcess:
    """Stands in for :class:`subprocess.Popen` in the spawn-and-wait tests."""

    def __init__(self, returncode: int = 0, *, refuse_signals: bool = False) -> None:
        self.returncode = returncode
        self.refuse_signals = refuse_signals
        self.signals: list[int] = []
        self.terminated = False
        self.waits = 0

    def send_signal(self, signum: int) -> None:
        if self.refuse_signals:
            # What Windows does for anything but SIGTERM and the console events.
            raise ValueError(f"Unsupported signal: {signum}")
        self.signals.append(signum)

    def terminate(self) -> None:
        self.terminated = True

    def wait(self) -> int:
        self.waits += 1
        return self.returncode


class FakeSpawner:
    """Records what would have been spawned and hands back a :class:`FakeProcess`."""

    def __init__(self, process: FakeProcess | None = None) -> None:
        self.process = process or FakeProcess()
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, argv: list[str], env: dict[str, str] | None = None) -> FakeProcess:
        self.calls.append((list(argv), dict(env or {})))
        return self.process


class FakeHandlers:
    """Records the signal handlers a run installs, and lets a test fire them."""

    def __init__(self) -> None:
        self.installed: list[tuple[int, Any]] = []
        self.current: dict[int, Any] = {}

    def __call__(self, signum: int, handler: Any) -> Any:
        previous = self.current.get(signum, "original")
        self.current[signum] = handler
        self.installed.append((signum, handler))
        return previous

    def fire(self, signum: int) -> None:
        """Call the forwarder that was installed for *signum*.

        The most recent callable wins: the launcher puts the original handlers
        back when the child exits, and those are recorded here as the plain
        string ``"original"``, so they are skipped.
        """
        for number, handler in reversed(self.installed):
            if number == signum and callable(handler):
                handler(signum, None)
                return
        raise AssertionError(f"no handler was installed for signal {signum}")

    def restored(self, signum: int) -> bool:
        """Whether the handler in place for *signum* is the one we started with."""
        return self.current.get(signum) == "original"


@pytest.fixture
def fakes() -> Any:
    """The stand-ins the process-hand-off tests use."""

    class Fakes:
        Process = FakeProcess
        Spawner = FakeSpawner
        Handlers = FakeHandlers

    return Fakes
