"""Installing and updating s0ma with no license key.

A machine with no key installs the version this launcher was released with
(``LAUNCHER_VERSION``), through uv, from whichever package index the machine's
uv is set up to use. The launcher itself asks nobody anything on that route:
no manifest, no wheel, no key check, no look for a newer version. A newer s0ma
arrives when the plugin that carries the launcher is updated.

Most tests here stand uv in through the runner seam (:class:`FakeUv`), which
builds an environment-shaped directory in either platform's layout and records
exactly what it was asked. One test does a real uv install of stand-in wheels
from a local directory, with uv's own ``UV_NO_INDEX`` and ``UV_FIND_LINKS``
settings, so nothing leaves the machine. The fake control plane is running in
the tests that ask whether it heard anything, and it must hear nothing.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import fake_control_plane
from fake_control_plane import FakeControlPlane
from hint_reading import parts, quiet_for_the_person

control_plane = fake_control_plane.control_plane

#: Anything that could be a real key, in any output. Nothing may match.
KEY_SHAPED = r"s0ma_(?:live|test)_[A-Za-z0-9_-]{4,}"


@pytest.fixture(autouse=True)
def _no_stray_offline_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test-only install flag, and uv's own index settings, start unset."""
    for name in ("S0MA_LAUNCH_OFFLINE_INSTALL", "UV_FIND_LINKS", "UV_NO_INDEX", "UV_CONFIG_FILE"):
        monkeypatch.delenv(name, raising=False)


def state_of(home: Path) -> dict[str, Any]:
    return json.loads((home / "launcher" / "state.json").read_text(encoding="utf-8"))


def write_state(launcher: ModuleType, home: Path, **fields: Any) -> None:
    state = launcher.default_state()
    state.update(fields)
    launcher.save_state(home, state)


# ---------------------------------------------------------------------------
# A stand-in for uv.
# ---------------------------------------------------------------------------


def umbrella_of(arguments: list[str]) -> str:
    """The one ``s0ma-lang==<version>`` requirement in a ``uv pip install``."""
    found = [argument for argument in arguments if argument.startswith("s0ma-lang==")]
    assert len(found) == 1, f"not one umbrella requirement in {arguments}"
    return found[0]


class FakeUv:
    """Stands in for ``subprocess.run`` when the launcher runs uv.

    ``uv venv <dir>`` leaves a Python behind in *dir*; ``uv pip install
    --python <python> s0ma-lang==<v> pytest>=7.0`` leaves the s0ma programs
    and a ``s0ma_lang_mcp-<v>.dist-info`` beside it. ``windows=True`` uses the
    ``Scripts`` and ``Lib/site-packages`` layout, so both platforms' shapes
    are exercised on whichever machine the tests run on. ``fail=True`` makes
    the install step refuse, the way uv does when a version cannot be found.
    """

    def __init__(self, *, windows: bool = False, fail: bool = False) -> None:
        self.windows = windows
        self.fail = fail
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(command), dict(kwargs.get("env") or {})))
        arguments = list(command[1:])
        if arguments[:1] == ["venv"]:
            root = Path(arguments[-1])
            if self.windows:
                python = root / "Scripts" / "python.exe"
            else:
                python = root / "bin" / "python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("fake python\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        if arguments[:2] == ["pip", "install"]:
            if self.fail:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    "",
                    "  x No solution found when resolving dependencies:\n"
                    "  Because there is no version of s0ma-lang==9.9.9 and you "
                    "require s0ma-lang==9.9.9, we can conclude that your "
                    "requirements are unsatisfiable.\n",
                )
            python = Path(arguments[arguments.index("--python") + 1])
            root = python.parent.parent
            version = umbrella_of(arguments).split("==", 1)[1]
            suffix = ".exe" if self.windows else ""
            for name in ("s0ma-mcp", "s0ma"):
                (python.parent / (name + suffix)).write_text("fake\n", encoding="utf-8")
            if self.windows:
                site_packages = root / "Lib" / "site-packages"
            else:
                site_packages = root / "lib" / "python3.11" / "site-packages"
            dist_info = site_packages / f"s0ma_lang_mcp-{version}.dist-info"
            dist_info.mkdir(parents=True, exist_ok=True)
            (dist_info / "METADATA").write_text("fake\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"the launcher ran something unexpected: {command}")

    def installs(self) -> list[list[str]]:
        """The ``uv pip install`` commands, in order."""
        return [command for command, _ in self.calls if command[1:3] == ["pip", "install"]]


@pytest.fixture(params=[False, True], ids=["posix-layout", "windows-layout"])
def fake_uv(
    request: pytest.FixtureRequest, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> FakeUv:
    """uv stood in through the launcher's own call to ``subprocess.run``."""
    stand_in = FakeUv(windows=bool(request.param))
    monkeypatch.setattr(launcher.subprocess, "run", stand_in)
    return stand_in


@pytest.fixture
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make a socket impossible: anything that tried would raise."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the keyless route opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class Spawner:
    """Stands in for the detached start of the quiet update."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> Any:
        self.calls.append((list(command), dict(kwargs)))
        return None


def managed(launcher: ModuleType, version: str) -> Any:
    return launcher.Resolution(
        kind=launcher.KIND_MANAGED, path=Path("/x/bin"), version=version, reason="."
    )


# ---------------------------------------------------------------------------
# B. With no key, nothing reaches the control plane, and no socket is opened.
# ---------------------------------------------------------------------------


def test_every_keyless_command_leaves_the_control_plane_unasked(
    run_cli: Any,
    launcher: ModuleType,
    control_plane: FakeControlPlane,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """install, update --check, the serve path's decision and the background
    run, update, status, session-hint and pin, one after another on one
    machine with no key, against a control plane that is up and listening."""
    monkeypatch.setenv("S0MA_CP_HOST", control_plane.host)
    stand_in = FakeUv()
    monkeypatch.setattr(launcher.subprocess, "run", stand_in)

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the keyless route opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    assert run_cli("install", "--version", "0.18.0")[0] == 0
    assert run_cli("update", "--check")[0] == 0

    # The serve path: an older copy runs and the plugin brings a newer one,
    # and still nothing is started, and a background run fetches nothing.
    spawner = Spawner()
    decision = launcher.maybe_start_background_update(
        launcher.resolve_toolchain(), home=isolated_home, spawn=spawner
    )
    assert decision == "no-key"
    assert spawner.calls == []
    installs_before = len(stand_in.installs())
    assert run_cli("update", "--background")[0] == 0
    assert len(stand_in.installs()) == installs_before

    # A person's own update is what installs the plugin's version.
    assert run_cli("update")[0] == 0
    assert (isolated_home / "toolchains" / launcher.LAUNCHER_VERSION / ".complete").is_file()

    assert run_cli("status")[0] == 0
    assert run_cli("status", "--json")[0] == 0
    assert run_cli("session-hint")[0] == 0
    code, _, err = run_cli("pin", "0.18.0")
    assert code == 0, err
    assert "could not check" in err

    assert control_plane.requests == [], "a keyless machine asked the control plane"
    assert control_plane.authorizations == []
    assert stand_in.installs(), "uv did the fetching"


@pytest.mark.parametrize("mode", ["auto", "notify", "off"])
@pytest.mark.parametrize("installed", ["0.18.0", "same", "99.0.0", "pinned"])
def test_the_serve_path_starts_nothing_with_no_key(
    run_cli: Any,
    launcher: ModuleType,
    control_plane: FakeControlPlane,
    make_toolchain: Any,
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_sockets: None,
    installed: str,
    mode: str,
) -> None:
    """``serve`` itself, with the hand-off stood in. With no key nothing is
    fetched on its own: not for an older copy, the same one, a newer one or a
    pinned project, under any update setting."""
    monkeypatch.setenv("S0MA_CP_HOST", control_plane.host)
    monkeypatch.setenv("S0MA_UPDATE", mode)
    if installed == "pinned":
        make_toolchain("0.18.0")
        (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")
    else:
        make_toolchain(launcher.LAUNCHER_VERSION if installed == "same" else installed)
    started: list[str] = []
    monkeypatch.setattr(launcher, "hand_off", lambda *a, **k: 0)
    monkeypatch.setattr(
        launcher,
        "spawn_background_update",
        lambda home, **kwargs: bool(started.append(str(home))) or True,
    )

    code, out, err = run_cli("serve")

    assert (code, out, err) == (0, "", "")
    assert started == [], "a keyless machine started a quiet update"
    assert control_plane.requests == []


# ---------------------------------------------------------------------------
# C. The keyless install itself.
# ---------------------------------------------------------------------------


def test_uv_is_asked_for_the_umbrella_at_the_launchers_own_version(
    launcher: ModuleType, isolated_home: Path, fake_uv: FakeUv
) -> None:
    installed = launcher.install_from_index(
        isolated_home, uv=Path("uv"), runner=fake_uv, progress=lambda _m: None
    )

    assert installed == launcher.LAUNCHER_VERSION
    partial = isolated_home / "toolchains" / (launcher.LAUNCHER_VERSION + ".partial")
    venv, pip = (command for command, _ in fake_uv.calls)
    assert venv == [
        "uv",
        "venv",
        "--relocatable",
        "--python",
        launcher.SUPPORTED_PYTHON,
        str(partial),
    ]
    python = "Scripts/python.exe" if fake_uv.windows else "bin/python"
    assert pip == [
        "uv",
        "pip",
        "install",
        "--python",
        str(partial / python),
        f"s0ma-lang=={launcher.LAUNCHER_VERSION}",
        "pytest>=7.0",
    ]
    assert launcher.PYTEST_REQUIREMENT == "pytest>=7.0"


def test_an_explicit_version_is_the_one_asked_for(
    launcher: ModuleType, isolated_home: Path, fake_uv: FakeUv
) -> None:
    installed = launcher.install_from_index(
        isolated_home, version="0.21.0", uv=Path("uv"), runner=fake_uv, progress=lambda _m: None
    )

    assert installed == "0.21.0"
    assert fake_uv.installs()[0][-2:] == ["s0ma-lang==0.21.0", launcher.PYTEST_REQUIREMENT]
    assert (isolated_home / "toolchains" / "0.21.0" / ".complete").is_file()


def test_install_on_the_command_line_routes_by_key(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, fake_uv: FakeUv
) -> None:
    code, out, err = run_cli("install", "--version", "0.21.0")

    assert code == 0, err
    assert out == ""
    assert fake_uv.installs()[-1][-2:] == ["s0ma-lang==0.21.0", launcher.PYTEST_REQUIREMENT]
    assert "s0ma 0.21.0 is installed." in err
    assert "no license key on this machine" in err
    assert launcher.installed_versions(isolated_home) == ["0.21.0"]

    code, _, err = run_cli("install")

    assert code == 0, err
    assert fake_uv.installs()[-1][-2:] == [
        f"s0ma-lang=={launcher.LAUNCHER_VERSION}",
        launcher.PYTEST_REQUIREMENT,
    ]


def test_uv_is_never_handed_a_key_on_this_route(
    launcher: ModuleType,
    isolated_home: Path,
    fake_uv: FakeUv,
    run_cli: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key variable that holds only blanks is no key: the keyless route is
    taken, and uv still never sees the variable at all."""
    monkeypatch.setenv("S0MA_LICENSE_KEY", "   ")

    assert run_cli("install")[0] == 0
    assert fake_uv.calls
    for command, env in fake_uv.calls:
        assert "S0MA_LICENSE_KEY" not in env
        assert re.search(KEY_SHAPED, " ".join(command)) is None
        assert re.search(KEY_SHAPED, "".join(env.values())) is None


def test_uv_keeps_the_machines_own_settings(
    launcher: ModuleType,
    isolated_home: Path,
    fake_uv: FakeUv,
    run_cli: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whatever index the machine's uv is set up to use is the one it uses."""
    monkeypatch.setenv("UV_INDEX_URL", "https://mirror.example.invalid/simple")
    monkeypatch.setenv("UV_CACHE_DIR", str(isolated_home.parent / "uv-cache"))

    assert run_cli("install")[0] == 0
    for _, env in fake_uv.calls:
        assert env["UV_INDEX_URL"] == "https://mirror.example.invalid/simple"
        assert env["UV_CACHE_DIR"] == str(isolated_home.parent / "uv-cache")


def test_uv_keeps_the_python_it_downloads_under_s0mas_home(
    launcher: ModuleType,
    isolated_home: Path,
    fake_uv: FakeUv,
    run_cli: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every uv call is told where to keep a Python: ``python`` under s0ma's home."""
    monkeypatch.delenv("UV_PYTHON_INSTALL_DIR", raising=False)

    assert run_cli("install")[0] == 0
    assert fake_uv.calls
    for _, env in fake_uv.calls:
        assert env["UV_PYTHON_INSTALL_DIR"] == str(isolated_home / "python")


def test_a_python_folder_the_person_chose_is_left_alone(
    launcher: ModuleType,
    isolated_home: Path,
    fake_uv: FakeUv,
    run_cli: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chosen = str(isolated_home.parent / "my-pythons")
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", chosen)

    assert run_cli("install")[0] == 0
    assert fake_uv.calls
    for _, env in fake_uv.calls:
        assert env["UV_PYTHON_INSTALL_DIR"] == chosen


def test_the_supported_pythons_are_what_the_header_and_the_lock_say(
    launcher: ModuleType,
) -> None:
    """The launcher runs on the Pythons it builds s0ma's environment on, and the
    Desktop extension's project file asks its host for the same ones."""
    source = Path(launcher.__file__)
    header = re.search(r'(?m)^# requires-python = "([^"]*)"$', source.read_text(encoding="utf-8"))
    assert header is not None
    assert header.group(1) == launcher.SUPPORTED_PYTHON
    lock = source.with_name(source.name + ".lock").read_text(encoding="utf-8")
    locked = re.search(r'(?m)^requires-python = "([^"]*)"$', lock)
    assert locked is not None
    assert locked.group(1).replace(" ", "") == launcher.SUPPORTED_PYTHON
    desktop = source.parents[1] / "claude" / "desktop" / "pyproject.toml"
    with desktop.open("rb") as handle:
        declared = tomllib.load(handle)["project"]["requires-python"]
    assert declared == launcher.SUPPORTED_PYTHON, "the Desktop extension asks for another range"


def test_a_failed_uv_run_leaves_nothing_installed_and_nothing_false(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stand_in = FakeUv(fail=True)
    monkeypatch.setattr(launcher.subprocess, "run", stand_in)

    code, out, err = run_cli("install", "--version", "9.9.9")

    assert code == 3
    assert out == ""
    assert "s0ma could not install s0ma 9.9.9 from the package index" in err
    assert "This is what uv said:" in err
    assert "No solution found" in err
    assert stand_in.installs()[-1][-2:] == ["s0ma-lang==9.9.9", launcher.PYTEST_REQUIREMENT], (
        "s0ma and pytest are asked for in the one call that failed"
    )
    toolchains = isolated_home / "toolchains"
    assert list(toolchains.iterdir()) == [], "nothing half-built is left behind"
    state = state_of(isolated_home)
    assert state["installed"] == []
    assert state["current"] is None
    assert state["entitlement"] == "unknown"
    assert state["last_check"] is None
    assert state["latest_seen"] is None
    assert isinstance(state["last_error"], str) and state["last_error"]


def test_the_marker_is_written_last_and_the_move_is_one_step(
    launcher: ModuleType, isolated_home: Path, fake_uv: FakeUv
) -> None:
    """Already here once: the new copy replaces it, and no ``.partial`` stays."""
    launcher.install_from_index(isolated_home, uv=Path("uv"), runner=fake_uv, progress=lambda _m: None)
    said: list[str] = []
    launcher.install_from_index(isolated_home, uv=Path("uv"), runner=fake_uv, progress=said.append)

    version = launcher.LAUNCHER_VERSION
    final = isolated_home / "toolchains" / version
    assert (final / ".complete").read_text(encoding="utf-8") == version + "\n"
    assert not (isolated_home / "toolchains" / (version + ".partial")).exists()
    assert sorted(path.name for path in (isolated_home / "toolchains").iterdir()) == [version]
    assert f"Replacing the copy of s0ma {version} that was already here." in said
    assert launcher.bin_dir_of(final) is not None


def test_an_unfinished_install_is_swept_first(
    launcher: ModuleType, isolated_home: Path, fake_uv: FakeUv, make_toolchain: Any
) -> None:
    interrupted = make_toolchain("0.16.0", complete=False)
    said: list[str] = []

    launcher.install_from_index(isolated_home, uv=Path("uv"), runner=fake_uv, progress=said.append)

    assert not interrupted.exists()
    assert "Cleared away 1 unfinished install." in said


def test_the_state_record_is_only_what_is_true(
    launcher: ModuleType, isolated_home: Path, fake_uv: FakeUv
) -> None:
    """No control plane was asked, so nothing it would have said is written."""
    launcher.install_from_index(isolated_home, uv=Path("uv"), runner=fake_uv, progress=lambda _m: None)

    state = state_of(isolated_home)
    assert state["installed"] == [launcher.LAUNCHER_VERSION]
    assert state["current"] == launcher.LAUNCHER_VERSION
    assert state["last_error"] is None
    assert state["entitlement"] == "unknown"
    assert state["last_check"] is None
    assert state["latest_seen"] is None
    assert state["pending"] is None


def test_what_a_control_plane_once_said_is_left_as_it_was(
    launcher: ModuleType, isolated_home: Path, fake_uv: FakeUv
) -> None:
    """A machine that had a key once keeps that record; a keyless install
    neither confirms nor erases it."""
    write_state(
        launcher,
        isolated_home,
        entitlement="not_entitled",
        last_check=12345,
        latest_seen="0.30.0",
        last_error="something from before",
    )

    launcher.install_from_index(isolated_home, uv=Path("uv"), runner=fake_uv, progress=lambda _m: None)

    state = state_of(isolated_home)
    assert state["entitlement"] == "not_entitled"
    assert state["last_check"] == 12345
    assert state["latest_seen"] == "0.30.0"
    assert state["last_error"] is None


def test_a_real_uv_install_from_a_local_index(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real uv, real wheels, the real ``s0ma-lang==<version>`` resolution.

    The stand-in index is a directory uv reaches through its own
    ``UV_FIND_LINKS`` setting, with ``UV_NO_INDEX`` so it looks nowhere else -
    the launcher passes both through untouched, which is the point.
    """
    links = tmp_path / "index"
    fake_control_plane.build_fake_index(links, "0.21.0")
    monkeypatch.setenv("UV_FIND_LINKS", str(links))
    monkeypatch.setenv("UV_NO_INDEX", "1")
    monkeypatch.setenv("UV_CONFIG_FILE", str(fake_control_plane.only_from(links)))
    monkeypatch.setenv("S0MA_LAUNCH_OFFLINE_INSTALL", "1")

    code, _, err = run_cli("install", "--version", "0.21.0")

    assert code == 0, err
    toolchain = isolated_home / "toolchains" / "0.21.0"
    program = launcher.find_program(launcher.bin_dir_of(toolchain), "s0ma-mcp")
    assert program is not None
    finished = subprocess.run([str(program)], capture_output=True, text=True, check=False)
    assert finished.stdout.strip() == "s0ma_lang_mcp 0.21.0", "the stand-in from the local index"
    assert launcher.installed_version_of(toolchain) == "0.21.0"
    assert (
        launcher.installed_version_of(toolchain, "pytest")
        == fake_control_plane.FAKE_PYTEST_VERSION
    ), "pytest came in the same install, from the same local index"


# ---------------------------------------------------------------------------
# C. update with no key: the plugin's version is the newest there is.
# ---------------------------------------------------------------------------


def test_update_moves_an_older_copy_to_the_launchers_version(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    fake_uv: FakeUv,
) -> None:
    make_toolchain("0.16.0", windows=fake_uv.windows)
    make_toolchain("0.18.0", windows=fake_uv.windows)

    code, out, err = run_cli("update")

    assert code == 0, err
    assert out == ""
    assert fake_uv.installs()[-1][-2:] == [
        f"s0ma-lang=={launcher.LAUNCHER_VERSION}",
        launcher.PYTEST_REQUIREMENT,
    ]
    assert launcher.installed_versions(isolated_home) == ["0.18.0", launcher.LAUNCHER_VERSION]
    assert "will be used from the next session" in err
    assert "pin 0.18.0" in err
    state = state_of(isolated_home)
    assert state["current"] == launcher.LAUNCHER_VERSION
    assert state["latest_seen"] is None
    assert state["last_check"] is None


def test_update_with_the_same_version_says_so_and_installs_nothing(
    run_cli: Any, launcher: ModuleType, make_toolchain: Any, fake_uv: FakeUv
) -> None:
    make_toolchain(launcher.LAUNCHER_VERSION, windows=fake_uv.windows)

    code, out, err = run_cli("update")

    assert code == 0, err
    assert out == ""
    assert fake_uv.calls == []
    assert "which is the version this plugin brings" in err
    assert "a newer s0ma arrives when the s0ma plugin" in err
    assert "license key" in err


def test_update_with_a_newer_copy_already_here_installs_nothing(
    run_cli: Any, make_toolchain: Any, fake_uv: FakeUv
) -> None:
    """A copy newer than the plugin brings, from a key this machine once had."""
    make_toolchain("99.0.0", windows=fake_uv.windows)

    code, _, err = run_cli("update")

    assert code == 0
    assert fake_uv.calls == []
    assert "nothing newer to install" in err


def test_update_with_nothing_installed_installs_the_launchers_version(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, fake_uv: FakeUv
) -> None:
    """A person asked, so a first install is fine here."""
    code, _, err = run_cli("update")

    assert code == 0, err
    assert launcher.installed_versions(isolated_home) == [launcher.LAUNCHER_VERSION]


def test_update_keeps_the_version_a_project_is_pinned_to(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    fake_uv: FakeUv,
    project: Path,
) -> None:
    make_toolchain("0.16.0", windows=fake_uv.windows)
    make_toolchain("0.17.0", windows=fake_uv.windows)
    (project / ".s0ma-version").write_text("0.16.0\n", encoding="utf-8")

    code, _, err = run_cli("update")

    assert code == 0, err
    assert launcher.installed_versions(isolated_home) == [
        "0.16.0",
        "0.17.0",
        launcher.LAUNCHER_VERSION,
    ]
    assert "carries on using that one" in err


def test_a_manual_update_still_works_with_updates_off(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    fake_uv: FakeUv,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_toolchain("0.18.0", windows=fake_uv.windows)
    monkeypatch.setenv("S0MA_UPDATE", "off")

    assert run_cli("update")[0] == 0
    assert launcher.LAUNCHER_VERSION in launcher.installed_versions(isolated_home)


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        (None, "Run `s0ma-launch update` to install it."),
        ("0.18.0", "Run `s0ma-launch update` to install it."),
        ("same", "This machine already has the s0ma this plugin brings."),
    ],
)
def test_update_check_says_what_the_plugin_brings_and_installs_nothing(
    run_cli: Any,
    launcher: ModuleType,
    make_toolchain: Any,
    fake_uv: FakeUv,
    installed: str | None,
    expected: str,
) -> None:
    if installed is not None:
        version = launcher.LAUNCHER_VERSION if installed == "same" else installed
        make_toolchain(version, windows=fake_uv.windows)

    code, out, err = run_cli("update", "--check")

    assert code == 0, err
    assert err == ""
    assert f"Plugin brings:   {launcher.LAUNCHER_VERSION}" in out
    assert expected in out
    assert "a newer s0ma arrives when the s0ma plugin" in out
    assert fake_uv.calls == []


def test_update_check_names_the_projects_pin(
    run_cli: Any, make_toolchain: Any, fake_uv: FakeUv, project: Path
) -> None:
    make_toolchain("0.18.0", windows=fake_uv.windows)
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")

    _, out, _ = run_cli("update", "--check")

    assert "asks for s0ma 0.18.0" in out


# ---------------------------------------------------------------------------
# C. No quiet update with no key: nothing is fetched unless a person asks.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["auto", "notify"])
@pytest.mark.parametrize("version", ["0.18.0", "same", "99.0.0", None])
def test_the_quiet_update_decision_is_no_key_in_every_case(
    launcher: ModuleType,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str | None,
    mode: str,
) -> None:
    monkeypatch.setenv("S0MA_UPDATE", mode)
    spawner = Spawner()

    decision = launcher.maybe_start_background_update(
        managed(launcher, launcher.LAUNCHER_VERSION if version == "same" else version),
        home=isolated_home,
        spawn=spawner,
    )

    assert decision == "no-key"
    assert spawner.calls == []


@pytest.mark.parametrize("mode", ["auto", "notify"])
@pytest.mark.parametrize("installed", [None, "0.18.0", "same"])
def test_the_background_run_installs_nothing_with_no_key(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    fake_uv: FakeUv,
    monkeypatch: pytest.MonkeyPatch,
    installed: str | None,
    mode: str,
) -> None:
    """Started by hand, or left over from before: still nothing is fetched."""
    if installed is not None:
        version = launcher.LAUNCHER_VERSION if installed == "same" else installed
        make_toolchain(version, windows=fake_uv.windows)
    monkeypatch.setenv("S0MA_UPDATE", mode)
    before = launcher.installed_versions(isolated_home)

    code, out, err = run_cli("update", "--background")

    assert code == 0
    assert out == ""
    assert "nothing is fetched on its own" in err
    assert "s0ma-launch update" in err
    assert fake_uv.calls == []
    assert launcher.installed_versions(isolated_home) == before
    assert not (isolated_home / "launcher" / "state.json").exists()


def test_serve_with_nothing_installed_starts_no_install(
    run_cli: Any, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first install is for a person to start: serve answers with the stub."""
    spawned: list[Any] = []
    monkeypatch.setattr(launcher, "serve_stub", lambda *a, **k: 0)
    monkeypatch.setattr(
        launcher, "spawn_background_update", lambda *a, **k: bool(spawned.append(a)) or True
    )

    code, out, _ = run_cli("serve")

    assert code == 0
    assert out == ""
    assert spawned == []


# ---------------------------------------------------------------------------
# What a keyless machine is told.
# ---------------------------------------------------------------------------


def test_status_says_where_an_install_comes_from(
    run_cli: Any, launcher: ModuleType, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0")

    _, out, _ = run_cli("status")

    assert "Fetched from: the package index, no key needed" in out
    assert "License key:  not set" in out
    assert (
        f"Next step:    Nothing urgent. s0ma {launcher.LAUNCHER_VERSION} came with the "
        "s0ma plugin; run `s0ma-launch update` to move to it now."
    ) in out
    assert (
        "Updates:      automatic notice - you are told when the plugin brings a "
        "newer s0ma, and `s0ma-launch update` installs it"
    ) in out
    assert "fetched quietly" not in out

    _, out, _ = run_cli("status", "--json")
    report = json.loads(out)
    assert report["install_route"] == "package_index"
    assert report["launcher_version"] == launcher.LAUNCHER_VERSION
    assert report["entitlement"] == "unknown"


def test_status_with_a_current_keyless_copy_says_it_is_ready(
    run_cli: Any, launcher: ModuleType, make_toolchain: Any
) -> None:
    make_toolchain(launcher.LAUNCHER_VERSION)

    _, out, _ = run_cli("status")

    assert "Next step:    Nothing - s0ma is ready." in out


def test_status_with_a_key_says_the_control_plane(
    run_cli: Any, fake_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S0MA_LICENSE_KEY", fake_key)

    _, out, _ = run_cli("status")
    assert "Fetched from: the s0ma control plane, with the license key" in out
    _, out, _ = run_cli("status", "--json")
    assert json.loads(out)["install_route"] == "control_plane"


def test_the_stub_says_no_key_is_needed(launcher: ModuleType) -> None:
    resolution = launcher.Resolution(
        kind=launcher.KIND_NONE, path=None, version=None, reason="s0ma is not installed."
    )

    instructions = launcher.stub_instructions(resolution)

    assert "/s0ma:start" in instructions
    assert "no license key is needed" in instructions
    assert "where their license key goes" not in instructions


HINT_PLUGIN_BRINGS = (
    "s0ma {latest} came with the s0ma plugin; s0ma 0.18.0 is what runs here. "
    "Run /s0ma:update in Claude to install it."
)


@pytest.mark.parametrize("mode", ["auto", "notify"])
def test_the_hint_names_what_the_plugin_brings_under_auto_and_notify(
    run_cli: Any,
    launcher: ModuleType,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
    no_sockets: None,
    isolated_home: Path,
    mode: str,
) -> None:
    make_toolchain("0.18.0")
    monkeypatch.setenv("S0MA_UPDATE", mode)
    before = sorted(str(path) for path in isolated_home.rglob("*"))

    code, out, err = run_cli("session-hint")

    assert (code, err) == (0, "")
    message = json.loads(out)["systemMessage"]
    assert message == HINT_PLUGIN_BRINGS.format(latest=launcher.LAUNCHER_VERSION)
    _, context, note = parts(out)
    assert context is None
    assert note is not None
    assert sorted(str(path) for path in isolated_home.rglob("*")) == before, "nothing written"


def test_the_hint_never_names_a_control_planes_old_offer_with_no_key(
    run_cli: Any, launcher: ModuleType, make_toolchain: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``latest_seen`` from a key this machine once had cannot be fetched now."""
    make_toolchain(launcher.LAUNCHER_VERSION)
    write_state(launcher, launcher.s0ma_home(), entitlement="ok", latest_seen="99.0.0")
    monkeypatch.setenv("S0MA_UPDATE", "notify")

    quiet_for_the_person(run_cli("session-hint"))


@pytest.mark.parametrize(
    ("installed", "mode", "pinned"),
    [
        ("0.18.0", "off", False),
        ("0.18.0", "auto", True),
        ("0.18.0", "notify", True),
        ("same", "auto", False),
        ("same", "notify", False),
        ("99.0.0", "notify", False),
    ],
)
def test_the_hint_is_silent_otherwise(
    run_cli: Any,
    launcher: ModuleType,
    make_toolchain: Any,
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    installed: str,
    mode: str,
    pinned: bool,
) -> None:
    """Updates off, a pinned project, or nothing newer with the launcher."""
    version = launcher.LAUNCHER_VERSION if installed == "same" else installed
    make_toolchain(version)
    if pinned:
        (project / ".s0ma-version").write_text(version + "\n", encoding="utf-8")
    monkeypatch.setenv("S0MA_UPDATE", mode)

    quiet_for_the_person(run_cli("session-hint"))
