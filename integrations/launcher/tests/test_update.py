"""Keeping s0ma current without ever interrupting anyone.

The promise (plan decision CD-3) is that s0ma starts what is installed at once,
looks for something newer in a process of its own, and uses the newer one from
the next session. These tests hold that promise to its four conditions - a copy
the launcher looks after, updates switched on, a key to ask with, and not more
than once a day - and to its manners: a second run that finds the lock held says
nothing alarming, a quiet update that fails writes one sentence into
``state.json`` instead of into the session, and the log it keeps never contains
a license key.

One test starts a real detached process. The rest use a stand-in spawner, and
none of them ever contacts the real control plane.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import fake_control_plane
from fake_control_plane import FakeControlPlane

# The fixtures live in ``fake_control_plane.py`` so there is one of each. They
# are bound here, rather than imported by name, because a test that takes
# ``keyed`` as an argument would otherwise look like a redefinition of the
# imported name to every linter that reads this file.
control_plane = fake_control_plane.control_plane
keyed = fake_control_plane.keyed

LAUNCHER_FILE = Path(__file__).resolve().parents[1] / "s0ma_launch.py"


@pytest.fixture(autouse=True)
def _no_stray_offline_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("S0MA_LAUNCH_OFFLINE_INSTALL", raising=False)


def state_of(home: Path) -> dict[str, Any]:
    return json.loads((home / "launcher" / "state.json").read_text(encoding="utf-8"))


def write_state(home: Path, **values: Any) -> None:
    path = home / "launcher" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    stored: dict[str, Any] = {
        "installed": [],
        "current": None,
        "latest_seen": None,
        "last_check": None,
        "entitlement": "unknown",
        "pending": None,
        "last_error": None,
    }
    if path.is_file():
        stored.update(json.loads(path.read_text(encoding="utf-8")))
    stored.update(values)
    path.write_text(json.dumps(stored, indent=2, sort_keys=True), encoding="utf-8")


@pytest.fixture
def with_a_key(monkeypatch: pytest.MonkeyPatch, fake_key: str) -> str:
    """A license key in the environment, exactly as the plugin would set one."""
    monkeypatch.setenv("S0MA_LICENSE_KEY", fake_key)
    return fake_key


class Spawner:
    """Stands in for the real detached start, and remembers what it was asked."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.fail = fail

    def __call__(self, command: list[str], **kwargs: Any) -> Any:
        self.calls.append((list(command), dict(kwargs)))
        if self.fail:
            raise OSError("no process for you")
        return None


# ---------------------------------------------------------------------------
# update --check: what is here, what there is, and what this project asks for.
# ---------------------------------------------------------------------------


def test_check_says_what_is_installed_and_what_is_newest(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    run_cli("install")
    keyed.publish("0.19.0")

    code, out, err = run_cli("update", "--check")

    assert code == 0, err
    assert "Installed here:  0.18.0" in out
    assert "Newest there is: 0.19.0" in out
    assert "A newer s0ma is available" in out
    assert state_of(isolated_home)["latest_seen"] == "0.19.0"
    assert not (isolated_home / "toolchains" / "0.19.0").exists(), "--check fetches nothing"


def test_check_says_so_when_there_is_nothing_newer(
    run_cli: Any, keyed: FakeControlPlane
) -> None:
    run_cli("install")

    code, out, _ = run_cli("update", "--check")

    assert code == 0
    assert "already has the newest s0ma" in out


def test_check_names_the_projects_pin(
    run_cli: Any, keyed: FakeControlPlane, project: Path
) -> None:
    run_cli("install")
    keyed.publish("0.19.0")
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")

    _, out, _ = run_cli("update", "--check")

    assert "asks for s0ma 0.18.0" in out
    assert "unpin" in out


def test_check_names_a_projects_own_copy(
    run_cli: Any, keyed: FakeControlPlane, project: Path, make_venv: Any
) -> None:
    make_venv(project / ".venv")

    _, out, _ = run_cli("update", "--check")

    assert "has its own copy of s0ma" in out


def test_check_without_a_key_says_where_a_key_goes(
    run_cli: Any, control_plane: FakeControlPlane, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S0MA_CP_HOST", control_plane.host)

    code, _, err = run_cli("update", "--check")

    assert code == 4
    assert "plugin's settings" in err


# ---------------------------------------------------------------------------
# update: the newer one lands beside the old one.
# ---------------------------------------------------------------------------


def test_update_installs_the_newer_version_and_keeps_the_one_before_it(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.16.0")
    make_toolchain("0.17.0")
    run_cli("install")  # 0.18.0, for real
    keyed.publish("0.19.0")

    code, _, err = run_cli("update")

    assert code == 0, err
    assert (isolated_home / "toolchains" / "0.19.0" / ".complete").is_file()
    assert (isolated_home / "toolchains" / "0.18.0").is_dir(), "the previous one stays"
    assert not (isolated_home / "toolchains" / "0.17.0").exists()
    assert not (isolated_home / "toolchains" / "0.16.0").exists()
    assert "will be used from the next session" in err
    assert "pin 0.18.0" in err
    state = state_of(isolated_home)
    assert state["current"] == "0.19.0"
    assert state["installed"] == ["0.18.0", "0.19.0"]


def test_update_never_takes_away_the_version_this_project_is_pinned_to(
    run_cli: Any,
    keyed: FakeControlPlane,
    isolated_home: Path,
    make_toolchain: Any,
    project: Path,
) -> None:
    make_toolchain("0.16.0")
    make_toolchain("0.17.0")
    run_cli("install")
    keyed.publish("0.19.0")
    (project / ".s0ma-version").write_text("0.16.0\n", encoding="utf-8")

    run_cli("update")

    assert (isolated_home / "toolchains" / "0.16.0").is_dir()
    assert not (isolated_home / "toolchains" / "0.17.0").exists()


def test_update_with_nothing_newer_says_so_and_changes_nothing(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    run_cli("install")

    code, _, err = run_cli("update")

    assert code == 0
    assert "already the newest" in err
    assert sorted(p.name for p in (isolated_home / "toolchains").iterdir()) == ["0.18.0"]


def test_a_second_run_leaves_the_first_one_to_finish(
    run_cli: Any, keyed: FakeControlPlane, launcher: ModuleType, isolated_home: Path
) -> None:
    with launcher.UpdateLock(isolated_home) as taken:
        assert taken, "the first run holds the lock"

        code, out, err = run_cli("update")

    assert code == 0
    assert out == ""
    assert "left it to finish" in err
    assert "error" not in err.lower()


def test_an_install_also_waits_for_whoever_holds_the_lock(
    run_cli: Any, keyed: FakeControlPlane, launcher: ModuleType, isolated_home: Path
) -> None:
    with launcher.UpdateLock(isolated_home):
        code, _, err = run_cli("install")

    assert code == 0
    assert "left it to finish" in err
    assert not (isolated_home / "toolchains").exists()


# ---------------------------------------------------------------------------
# The lock itself, on both platforms.
# ---------------------------------------------------------------------------


class FakeLockModule:
    """A stand-in for ``msvcrt`` (or ``fcntl``), so both branches are tested here."""

    LK_NBLCK = 1
    LK_UNLCK = 0
    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def __init__(self, *, refuse: bool = False) -> None:
        self.refuse = refuse
        self.calls: list[tuple[str, int]] = []

    def locking(self, fileno: int, mode: int, nbytes: int) -> None:
        self.calls.append(("locking", mode))
        if self.refuse and mode == self.LK_NBLCK:
            raise OSError(36, "already locked")

    def flock(self, fileno: int, flags: int) -> None:
        self.calls.append(("flock", flags))
        if self.refuse and flags & self.LOCK_NB:
            raise OSError(35, "already locked")


def test_the_windows_branch_locks_one_byte_without_waiting(launcher: ModuleType) -> None:
    fake = FakeLockModule()
    asked: list[str] = []

    def loader(name: str) -> Any:
        asked.append(name)
        return fake

    assert launcher.take_file_lock(3, windows=True, import_module=loader) is True
    launcher.release_file_lock(3, windows=True, import_module=loader)

    assert asked == ["msvcrt", "msvcrt"]
    assert fake.calls == [("locking", fake.LK_NBLCK), ("locking", fake.LK_UNLCK)]


def test_the_windows_branch_gives_up_when_someone_else_holds_it(
    launcher: ModuleType,
) -> None:
    fake = FakeLockModule(refuse=True)

    assert launcher.take_file_lock(3, windows=True, import_module=lambda _n: fake) is False


def test_the_posix_branch_asks_for_the_module_posix_has(launcher: ModuleType) -> None:
    fake = FakeLockModule()
    asked: list[str] = []

    def loader(name: str) -> Any:
        asked.append(name)
        return fake

    assert launcher.take_file_lock(3, windows=False, import_module=loader) is True
    assert asked == ["fcntl"]
    assert fake.calls == [("flock", fake.LOCK_EX | fake.LOCK_NB)]


def test_a_lock_file_that_cannot_be_made_does_not_stop_the_work(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """A home directory that cannot hold a lock file is a reason to carry on.

    A read-only directory is the real case; a name the operating system refuses
    outright is how it is provoked here, on any platform.
    """
    nowhere = tmp_path / "missing" / "deeper"
    lock = launcher.UpdateLock(nowhere)
    lock.path = nowhere / "no" / "\x00bad"

    with lock as taken:
        assert taken is True


# ---------------------------------------------------------------------------
# Starting the quiet update: the four conditions `serve` checks.
# ---------------------------------------------------------------------------


def managed(launcher: ModuleType, version: str = "0.18.0") -> Any:
    return launcher.Resolution(
        kind=launcher.KIND_MANAGED, path=Path("/x/bin"), version=version, reason="."
    )


def test_serve_starts_a_quiet_update_when_everything_lines_up(
    launcher: ModuleType, isolated_home: Path, make_toolchain: Any, with_a_key: str
) -> None:
    make_toolchain("0.18.0")
    spawner = Spawner()

    decision = launcher.maybe_start_background_update(
        managed(launcher), home=isolated_home, spawn=spawner
    )

    assert decision == "started"
    command, kwargs = spawner.calls[0]
    assert command == [sys.executable, str(LAUNCHER_FILE), "update", "--background"]
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.STDOUT
    assert kwargs["cwd"] == str(isolated_home)
    assert Path(kwargs["stdout"].name) == isolated_home / "launcher" / "update.log"


@pytest.mark.parametrize("kind", ["override", "project", "pinned", "none"])
def test_a_copy_the_launcher_does_not_look_after_is_never_moved(
    launcher: ModuleType, isolated_home: Path, kind: str, with_a_key: str
) -> None:
    spawner = Spawner()
    resolution = launcher.Resolution(
        kind=kind, path=Path("/x/bin"), version="0.18.0", reason="."
    )

    decision = launcher.maybe_start_background_update(
        resolution, home=isolated_home, spawn=spawner
    )

    assert decision == "not-managed"
    assert spawner.calls == []


def test_updates_switched_off_start_nothing(
    launcher: ModuleType, isolated_home: Path, with_a_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S0MA_UPDATE", "off")
    spawner = Spawner()

    decision = launcher.maybe_start_background_update(
        managed(launcher), home=isolated_home, spawn=spawner
    )

    assert decision == "updates-off"
    assert spawner.calls == []


def test_notify_still_looks_but_will_not_fetch(
    launcher: ModuleType, isolated_home: Path, with_a_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    spawner = Spawner()

    assert (
        launcher.maybe_start_background_update(
            managed(launcher), home=isolated_home, spawn=spawner
        )
        == "started"
    )


def test_without_a_key_there_is_nothing_to_ask_with(
    launcher: ModuleType, isolated_home: Path
) -> None:
    spawner = Spawner()

    decision = launcher.maybe_start_background_update(
        managed(launcher), home=isolated_home, spawn=spawner
    )

    assert decision == "no-key"
    assert spawner.calls == []


def test_the_control_plane_is_asked_at_most_once_a_day(
    launcher: ModuleType, isolated_home: Path, with_a_key: str
) -> None:
    write_state(isolated_home, last_check=launcher.now_seconds() - 60)
    spawner = Spawner()

    decision = launcher.maybe_start_background_update(
        managed(launcher), home=isolated_home, spawn=spawner
    )

    assert decision == "checked-recently"
    assert spawner.calls == []


def test_a_day_later_it_asks_again(
    launcher: ModuleType, isolated_home: Path, with_a_key: str
) -> None:
    write_state(
        isolated_home,
        last_check=launcher.now_seconds() - launcher.UPDATE_CHECK_INTERVAL_SECONDS - 1,
    )

    assert (
        launcher.maybe_start_background_update(
            managed(launcher), home=isolated_home, spawn=Spawner()
        )
        == "started"
    )


def test_a_version_that_was_waiting_is_no_longer_waiting_once_it_runs(
    launcher: ModuleType, isolated_home: Path, with_a_key: str
) -> None:
    write_state(isolated_home, pending="0.19.0", last_check=launcher.now_seconds())

    launcher.maybe_start_background_update(
        managed(launcher, "0.19.0"), home=isolated_home, spawn=Spawner()
    )

    assert state_of(isolated_home)["pending"] is None


def test_a_quiet_update_that_cannot_start_is_not_an_error(
    launcher: ModuleType, isolated_home: Path, with_a_key: str
) -> None:
    decision = launcher.maybe_start_background_update(
        managed(launcher), home=isolated_home, spawn=Spawner(fail=True)
    )

    assert decision == "failed"


def test_serve_leaves_a_quiet_update_behind_before_handing_over(
    launcher: ModuleType,
    run_cli: Any,
    make_toolchain: Any,
    isolated_home: Path,
    with_a_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_toolchain("0.18.0")
    started: list[str] = []
    monkeypatch.setattr(launcher, "hand_off", lambda *a, **k: 0)
    monkeypatch.setattr(
        launcher,
        "spawn_background_update",
        lambda home, **kwargs: bool(started.append(str(home))) or True,
    )

    code, out, err = run_cli("serve")

    assert code == 0
    assert started == [str(isolated_home)]
    assert out == "", "stdout belongs to the MCP conversation"
    assert err == ""


# ---------------------------------------------------------------------------
# How a process is detached, and where its words go.
# ---------------------------------------------------------------------------


def test_detaching_on_each_platform(launcher: ModuleType) -> None:
    assert launcher.detach_kwargs(windows=False) == {"start_new_session": True}
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, from the Win32 documentation.
    assert launcher.detach_kwargs(windows=True) == {"creationflags": 0x00000008 | 0x00000200}


def test_the_log_is_rotated_and_one_older_file_is_kept(
    launcher: ModuleType, isolated_home: Path
) -> None:
    log = isolated_home / "launcher" / "update.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("x" * (launcher.UPDATE_LOG_LIMIT_BYTES + 1), encoding="utf-8")

    launcher.rotate_update_log(isolated_home)

    assert not log.exists()
    assert (isolated_home / "launcher" / "update.log.1").is_file()


def test_a_small_log_is_left_alone(launcher: ModuleType, isolated_home: Path) -> None:
    log = isolated_home / "launcher" / "update.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("one line\n", encoding="utf-8")

    launcher.rotate_update_log(isolated_home)

    assert log.read_text(encoding="utf-8") == "one line\n"
    assert not (isolated_home / "launcher" / "update.log.1").exists()


def test_the_quiet_update_is_given_the_key_in_its_environment_not_its_arguments(
    launcher: ModuleType, isolated_home: Path, with_a_key: str
) -> None:
    spawner = Spawner()

    launcher.spawn_background_update(isolated_home, spawn=spawner)

    command, kwargs = spawner.calls[0]
    assert with_a_key not in " ".join(command)
    assert kwargs["env"]["S0MA_LICENSE_KEY"] == with_a_key, (
        "the child is the one that has to ask the control plane"
    )


# ---------------------------------------------------------------------------
# The quiet update itself.
# ---------------------------------------------------------------------------


def test_the_quiet_update_installs_and_leaves_it_waiting(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    run_cli("install")
    keyed.publish("0.19.0")
    write_state(isolated_home, last_check=0)

    code, out, err = run_cli("update", "--background")

    assert code == 0
    assert out == ""
    assert (isolated_home / "toolchains" / "0.19.0" / ".complete").is_file()
    state = state_of(isolated_home)
    assert state["pending"] == "0.19.0"
    assert state["current"] == "0.19.0"
    assert "waiting for the next session" in err


def test_notify_writes_down_what_is_available_and_fetches_nothing(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_cli("install")
    keyed.publish("0.19.0")
    monkeypatch.setenv("S0MA_UPDATE", "notify")

    code, _, err = run_cli("update", "--background")

    assert code == 0
    assert not (isolated_home / "toolchains" / "0.19.0").exists()
    assert state_of(isolated_home)["latest_seen"] == "0.19.0"
    assert state_of(isolated_home)["pending"] is None
    assert "set to tell you" in err


def test_updates_switched_off_check_nothing_at_all(
    run_cli: Any, keyed: FakeControlPlane, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S0MA_UPDATE", "off")

    code, _, err = run_cli("update", "--background")

    assert code == 0
    assert "switched off" in err
    assert keyed.requests == []


def test_a_quiet_update_that_fails_writes_one_sentence_and_ends_quietly(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    run_cli("install")
    keyed.invalid_key = True
    write_state(isolated_home, last_check=0)

    code, out, _ = run_cli("update", "--background")

    assert code == 0, "a background run never fails in front of anybody"
    assert out == ""
    state = state_of(isolated_home)
    assert state["entitlement"] == "invalid_key"
    assert isinstance(state["last_error"], str)
    assert "\n" not in state["last_error"]
    assert keyed.key not in state["last_error"]


def test_a_manual_update_still_works_when_automatic_ones_are_off(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`off` governs what s0ma does on its own, not what a person asks for."""
    run_cli("install")
    keyed.publish("0.19.0")
    monkeypatch.setenv("S0MA_UPDATE", "off")

    code, _, err = run_cli("update")

    assert code == 0, err
    assert (isolated_home / "toolchains" / "0.19.0" / ".complete").is_file()


# ---------------------------------------------------------------------------
# One real, detached, end-to-end quiet update.
# ---------------------------------------------------------------------------


def test_a_real_detached_update_installs_the_newer_version_and_logs_no_key(
    run_cli: Any, keyed: FakeControlPlane, launcher: ModuleType, isolated_home: Path
) -> None:
    run_cli("install")
    keyed.publish("0.19.0")
    write_state(isolated_home, last_check=0)

    assert launcher.spawn_background_update(isolated_home) is True

    marker = isolated_home / "toolchains" / "0.19.0" / ".complete"
    deadline = time.time() + 120
    while time.time() < deadline and not marker.is_file():
        time.sleep(0.1)
    assert marker.is_file(), "the detached update did not finish"

    # Give the process the moment it needs to write its last lines.
    log = isolated_home / "launcher" / "update.log"
    deadline = time.time() + 20
    while time.time() < deadline and "waiting for the next session" not in log.read_text(
        encoding="utf-8"
    ):
        time.sleep(0.1)

    written = log.read_text(encoding="utf-8")
    assert "s0ma 0.19.0 is installed" in written
    assert keyed.key not in written, "a license key never reaches the log"
    assert state_of(isolated_home)["pending"] == "0.19.0"
