"""Which s0ma runs here, and how control is handed to it.

These tests cover the decision the launcher makes before it does anything else
(decision CD-4 in the plan), the small things that decision rests on - version
sorting, virtual-environment layouts, the pin file, finding uv - and the two
ways the launcher gives a run away to the toolchain it found.

Windows is a first-class target, so every layout that differs between platforms
is built and read here on whatever machine the suite runs on:
``bin/`` against ``Scripts/``, ``lib/pythonX.Y/site-packages`` against
``Lib/site-packages``, ``uv`` against ``uv.exe``, and replacing the process
against spawning a child and waiting for it.
"""

from __future__ import annotations

import json
import signal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# The state directory.
# ---------------------------------------------------------------------------


def test_s0ma_home_follows_the_environment_variable(
    launcher: ModuleType, isolated_home: Path
) -> None:
    assert launcher.s0ma_home() == isolated_home


def test_s0ma_home_falls_back_to_the_users_home(launcher: ModuleType, tmp_path: Path) -> None:
    somewhere = tmp_path / "elsewhere"
    resolved = launcher.s0ma_home({"HOME": str(somewhere), "USERPROFILE": str(somewhere)})
    assert resolved == somewhere / ".s0ma"


def test_state_paths_sit_where_the_plan_freezes_them(
    launcher: ModuleType, isolated_home: Path
) -> None:
    assert launcher.license_path(isolated_home) == isolated_home / "license"
    assert launcher.config_path(isolated_home) == isolated_home / "launcher" / "config.json"
    assert launcher.state_path(isolated_home) == isolated_home / "launcher" / "state.json"
    assert launcher.toolchains_dir(isolated_home) == isolated_home / "toolchains"
    assert launcher.downloads_dir(isolated_home) == isolated_home / "downloads"
    assert launcher.update_lock_path(isolated_home) == (
        isolated_home / "launcher" / "update.lock"
    )
    assert launcher.update_log_path(isolated_home) == isolated_home / "launcher" / "update.log"


# ---------------------------------------------------------------------------
# Settings and the runtime record.
# ---------------------------------------------------------------------------


def test_missing_settings_give_defaults_and_write_nothing(
    launcher: ModuleType, isolated_home: Path
) -> None:
    config = launcher.load_config(isolated_home)
    state = launcher.load_state(isolated_home)
    assert config["update"] == "auto"
    assert config["cp_host"] == "account.kn0wthyself.ai"
    assert state["entitlement"] == "unknown"
    assert state["installed"] == []
    # A machine that has never run an install keeps a clean state directory.
    assert not launcher.launcher_dir(isolated_home).exists()


def test_settings_survive_a_round_trip(launcher: ModuleType, isolated_home: Path) -> None:
    launcher.save_config(isolated_home, {"update": "off", "cp_host": "example.invalid"})
    config = launcher.load_config(isolated_home)
    assert config["update"] == "off"
    assert config["cp_host"] == "example.invalid"


def test_written_json_is_sorted_and_ends_with_one_newline(
    launcher: ModuleType, isolated_home: Path
) -> None:
    path = launcher.config_path(isolated_home)
    launcher.write_json_file(path, {"zebra": 1, "apple": 2})
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert text.index('"apple"') < text.index('"zebra"')
    assert json.loads(text) == {"zebra": 1, "apple": 2}


def test_a_replaced_file_leaves_no_temporary_behind(
    launcher: ModuleType, isolated_home: Path
) -> None:
    path = launcher.config_path(isolated_home)
    launcher.write_json_file(path, {"one": 1})
    launcher.write_json_file(path, {"two": 2})
    assert sorted(p.name for p in path.parent.iterdir()) == ["config.json"]


def test_a_broken_settings_file_is_moved_aside_and_reported(
    launcher: ModuleType, isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = launcher.state_path(isolated_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")

    state = launcher.load_state(isolated_home)

    assert state == launcher.default_state()
    assert path.with_name("state.json.corrupt").read_text(encoding="utf-8") == (
        "{ this is not json"
    )
    # A fresh, readable file takes its place, so the next run starts clean.
    assert json.loads(path.read_text(encoding="utf-8")) == launcher.default_state()
    message = capsys.readouterr().err
    assert "could not be understood" in message
    assert "state.json.corrupt" in message
    # One line, not a wall of text.
    assert len([line for line in message.splitlines() if line.strip()]) == 1


def test_a_settings_file_holding_a_list_is_treated_as_broken(
    launcher: ModuleType, isolated_home: Path
) -> None:
    path = launcher.config_path(isolated_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert launcher.load_config(isolated_home)["update"] == "auto"
    assert path.with_name("config.json.corrupt").exists()
    assert json.loads(path.read_text(encoding="utf-8")) == launcher.default_config()


def test_an_unknown_update_setting_falls_back_to_auto(
    launcher: ModuleType, isolated_home: Path
) -> None:
    launcher.save_config(isolated_home, {"update": "sometimes"})
    assert launcher.load_config(isolated_home)["update"] == "auto"


def test_the_environment_wins_over_the_stored_update_setting(launcher: ModuleType) -> None:
    config = {"update": "off"}
    assert launcher.update_mode({"S0MA_UPDATE": "notify"}, config) == "notify"
    assert launcher.update_mode({"S0MA_UPDATE": "NONSENSE"}, config) == "off"
    assert launcher.update_mode({}, config) == "off"
    assert launcher.update_mode({}, None) == "auto"


def test_the_environment_wins_over_the_stored_control_plane_host(launcher: ModuleType) -> None:
    config = {"cp_host": "stored.invalid"}
    assert launcher.cp_host({"S0MA_CP_HOST": "asked.invalid"}, config) == "asked.invalid"
    assert launcher.cp_host({}, config) == "stored.invalid"
    assert launcher.cp_host({}, None) == "account.kn0wthyself.ai"


# ---------------------------------------------------------------------------
# The license key: found, never shown.
# ---------------------------------------------------------------------------


def test_no_key_anywhere_reads_as_absent(launcher: ModuleType, isolated_home: Path) -> None:
    assert launcher.license_key({}, isolated_home) == (None, None)


def test_the_environment_key_wins_over_the_saved_one(
    launcher: ModuleType, isolated_home: Path
) -> None:
    launcher.license_path(isolated_home).write_text("s0ma_test_saved_0001\n", encoding="utf-8")
    key, source = launcher.license_key({"S0MA_LICENSE_KEY": "s0ma_test_env_0002"}, isolated_home)
    assert key == "s0ma_test_env_0002"
    assert source == "environment"


def test_a_saved_key_is_read_and_reported_as_saved(
    launcher: ModuleType, isolated_home: Path
) -> None:
    launcher.license_path(isolated_home).write_text("s0ma_test_saved_0001\n", encoding="utf-8")
    key, source = launcher.license_key({}, isolated_home)
    assert key == "s0ma_test_saved_0001"
    assert source == "file"


def test_a_key_is_redacted_to_a_mask_and_four_characters(launcher: ModuleType) -> None:
    redacted = launcher.redact_key("s0ma_test_something_secret_wxyz")
    assert redacted == "s0ma_...wxyz"
    assert "secret" not in redacted
    assert launcher.key_last4("s0ma_test_something_secret_wxyz") == "wxyz"
    # Short input never raises and never shows more than it has.
    assert launcher.redact_key("ab") == "s0ma_...ab"


# ---------------------------------------------------------------------------
# Version numbers.
# ---------------------------------------------------------------------------


def test_versions_sort_as_numbers_not_as_text(launcher: ModuleType) -> None:
    versions = ["0.9.0", "0.10.0", "0.2.0", "1.0.0", "0.18.1"]
    ordered = sorted(versions, key=launcher.version_sort_key)
    assert ordered == ["0.2.0", "0.9.0", "0.10.0", "0.18.1", "1.0.0"]


def test_a_version_with_a_suffix_still_sorts(launcher: ModuleType) -> None:
    ordered = sorted(["0.19.0", "0.19.0rc1", "0.20.0"], key=launcher.version_sort_key)
    assert ordered[-1] == "0.20.0"


def test_what_counts_as_a_version(launcher: ModuleType) -> None:
    assert launcher.looks_like_version("0.18.0")
    assert launcher.looks_like_version("1.0.0rc1")
    assert not launcher.looks_like_version("")
    assert not launcher.looks_like_version("latest")
    assert not launcher.looks_like_version("../escape")
    assert not launcher.looks_like_version("0." + "9" * 100)


# ---------------------------------------------------------------------------
# Virtual-environment layouts: POSIX and Windows, on either machine.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("windows", [False, True], ids=["posix-layout", "windows-layout"])
def test_the_programs_are_found_in_either_layout(
    launcher: ModuleType, tmp_path: Path, make_venv: Any, windows: bool
) -> None:
    root = tmp_path / "venv"
    bin_dir = make_venv(root, windows=windows)
    assert launcher.bin_dir_of(root) == bin_dir
    assert bin_dir.name == ("Scripts" if windows else "bin")
    found = launcher.find_program(bin_dir, "s0ma-mcp")
    assert found is not None
    assert found.name == ("s0ma-mcp.exe" if windows else "s0ma-mcp")


def test_a_directory_without_the_server_program_is_not_a_toolchain(
    launcher: ModuleType, tmp_path: Path, make_venv: Any
) -> None:
    root = tmp_path / "venv"
    make_venv(root, programs=("s0ma",))
    assert launcher.bin_dir_of(root) is None


@pytest.mark.parametrize("windows", [False, True], ids=["posix-layout", "windows-layout"])
def test_the_version_is_read_from_the_dist_info_directory(
    launcher: ModuleType, tmp_path: Path, make_venv: Any, windows: bool
) -> None:
    root = tmp_path / "venv"
    make_venv(root, windows=windows, version="0.18.0")
    assert launcher.installed_version_of(root) == "0.18.0"


def test_an_environment_without_dist_info_has_no_cheap_version(
    launcher: ModuleType, tmp_path: Path, make_venv: Any
) -> None:
    root = tmp_path / "venv"
    make_venv(root)
    assert launcher.installed_version_of(root) is None


# ---------------------------------------------------------------------------
# Installed managed toolchains.
# ---------------------------------------------------------------------------


def test_installed_versions_are_listed_oldest_first(
    launcher: ModuleType, isolated_home: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.9.0")
    make_toolchain("0.10.0")
    make_toolchain("0.2.0")
    assert launcher.installed_versions(isolated_home) == ["0.2.0", "0.9.0", "0.10.0"]


def test_a_half_built_toolchain_is_ignored(
    launcher: ModuleType, isolated_home: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0")
    make_toolchain("0.19.0", complete=False)
    assert launcher.installed_versions(isolated_home) == ["0.18.0"]


def test_a_marked_toolchain_with_no_programs_is_ignored(
    launcher: ModuleType, isolated_home: Path
) -> None:
    root = launcher.managed_toolchain_dir(isolated_home, "0.18.0")
    root.mkdir(parents=True)
    (root / launcher.COMPLETE_MARKER).write_text("", encoding="utf-8")
    assert launcher.installed_versions(isolated_home) == []


def test_no_toolchains_directory_is_not_an_error(
    launcher: ModuleType, isolated_home: Path
) -> None:
    assert launcher.installed_versions(isolated_home) == []


# ---------------------------------------------------------------------------
# The pin file.
# ---------------------------------------------------------------------------


def test_no_pin_file_reads_as_not_pinned(launcher: ModuleType, project: Path) -> None:
    pin = launcher.read_pin(project)
    assert (pin.present, pin.version, pin.problem) == (False, None, None)


def test_a_pin_file_names_one_version(launcher: ModuleType, project: Path) -> None:
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")
    pin = launcher.read_pin(project)
    assert pin.present and pin.version == "0.18.0" and pin.problem is None


def test_an_empty_pin_file_is_a_problem_not_a_version(
    launcher: ModuleType, project: Path
) -> None:
    (project / ".s0ma-version").write_text("\n \n", encoding="utf-8")
    pin = launcher.read_pin(project)
    assert pin.present and pin.version is None and pin.problem == "is empty"


def test_a_pin_file_holding_nonsense_is_a_problem(launcher: ModuleType, project: Path) -> None:
    (project / ".s0ma-version").write_text("the newest one please\n", encoding="utf-8")
    pin = launcher.read_pin(project)
    assert pin.version is None and pin.problem == "does not name a version"


# ---------------------------------------------------------------------------
# The project directory.
# ---------------------------------------------------------------------------


def test_claude_names_the_project_when_it_can(
    launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(elsewhere))
    assert launcher.project_dir() == elsewhere


def test_without_claude_the_working_directory_is_the_project(
    launcher: ModuleType, project: Path
) -> None:
    assert launcher.project_dir() == project


# ---------------------------------------------------------------------------
# Resolution (decision CD-4), in order.
# ---------------------------------------------------------------------------


def test_nothing_anywhere_resolves_to_nothing(launcher: ModuleType) -> None:
    resolution = launcher.resolve_toolchain()
    assert resolution.kind == "none"
    assert resolution.path is None
    assert resolution.reason == "s0ma is not installed on this machine yet."
    assert not resolution.found


@pytest.mark.parametrize("windows", [False, True], ids=["posix-layout", "windows-layout"])
def test_the_override_wins_over_everything(
    launcher: ModuleType,
    tmp_path: Path,
    project: Path,
    make_venv: Any,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
    windows: bool,
) -> None:
    make_toolchain("0.18.0")
    make_venv(project / ".venv")
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")
    mine = tmp_path / "my-checkout-venv"
    bin_dir = make_venv(mine, windows=windows, version="0.99.0")
    monkeypatch.setenv("S0MA_TOOLCHAIN", str(mine))

    resolution = launcher.resolve_toolchain()

    assert resolution.kind == "override"
    assert resolution.path == bin_dir
    assert resolution.version == "0.99.0"
    assert "S0MA_TOOLCHAIN" in resolution.reason


def test_the_override_may_be_the_directory_of_programs_itself(
    launcher: ModuleType, tmp_path: Path, make_venv: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = make_venv(tmp_path / "venv")
    monkeypatch.setenv("S0MA_TOOLCHAIN", str(bin_dir))
    resolution = launcher.resolve_toolchain()
    assert resolution.kind == "override"
    assert resolution.path == bin_dir


def test_the_override_may_be_a_checkout_with_a_dot_venv(
    launcher: ModuleType, tmp_path: Path, make_venv: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    bin_dir = make_venv(checkout / ".venv")
    monkeypatch.setenv("S0MA_TOOLCHAIN", str(checkout))
    resolution = launcher.resolve_toolchain()
    assert resolution.kind == "override"
    assert resolution.path == bin_dir


def test_an_override_holding_no_s0ma_never_falls_through_quietly(
    launcher: ModuleType, tmp_path: Path, make_toolchain: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Someone said which copy to use. Running a different one would be a lie."""
    make_toolchain("0.18.0")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("S0MA_TOOLCHAIN", str(empty))

    resolution = launcher.resolve_toolchain()

    assert resolution.kind == "none"
    assert "S0MA_TOOLCHAIN" in resolution.reason
    assert "no s0ma program there" in resolution.reason


@pytest.mark.parametrize("windows", [False, True], ids=["posix-layout", "windows-layout"])
def test_a_project_with_its_own_s0ma_keeps_it(
    launcher: ModuleType, project: Path, make_venv: Any, make_toolchain: Any, windows: bool
) -> None:
    make_toolchain("0.19.0")
    bin_dir = make_venv(project / ".venv", windows=windows, version="0.12.0")

    resolution = launcher.resolve_toolchain()

    assert resolution.kind == "project"
    assert resolution.path == bin_dir
    assert resolution.version == "0.12.0"
    assert "its own copy" in resolution.reason


def test_a_projects_own_s0ma_wins_over_its_pin_file(
    launcher: ModuleType, project: Path, make_venv: Any, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0")
    bin_dir = make_venv(project / ".venv")
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")

    resolution = launcher.resolve_toolchain()

    assert resolution.kind == "project"
    assert resolution.path == bin_dir


def test_a_projects_own_s0ma_may_have_no_readable_version(
    launcher: ModuleType, project: Path, make_venv: Any
) -> None:
    make_venv(project / ".venv")
    resolution = launcher.resolve_toolchain()
    assert resolution.kind == "project"
    assert resolution.version is None
    assert launcher.version_words(resolution) == "s0ma (the project's own copy)"


def test_a_pinned_project_runs_the_version_it_names(
    launcher: ModuleType, project: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0")
    make_toolchain("0.19.0")
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")

    resolution = launcher.resolve_toolchain()

    assert resolution.kind == "pinned"
    assert resolution.version == "0.18.0"
    assert ".s0ma-version" in resolution.reason


def test_a_pin_to_a_version_that_is_not_installed_is_said_plainly(
    launcher: ModuleType, project: Path, make_toolchain: Any
) -> None:
    """A pinned project is never quietly moved to a version it did not ask for."""
    make_toolchain("0.19.0")
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")

    resolution = launcher.resolve_toolchain()

    assert resolution.kind == "none"
    assert resolution.version == "0.18.0"
    assert "not installed on this machine" in resolution.reason


def test_a_pin_to_a_half_built_version_counts_as_not_installed(
    launcher: ModuleType, project: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0", complete=False)
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")
    assert launcher.resolve_toolchain().kind == "none"


def test_an_unreadable_pin_file_stops_the_launcher_guessing(
    launcher: ModuleType, project: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.19.0")
    (project / ".s0ma-version").write_text("whatever is newest\n", encoding="utf-8")

    resolution = launcher.resolve_toolchain()

    assert resolution.kind == "none"
    assert "does not name a version" in resolution.reason


def test_the_newest_installed_version_runs_when_nothing_asks_otherwise(
    launcher: ModuleType, make_toolchain: Any
) -> None:
    make_toolchain("0.9.0")
    newest = make_toolchain("0.10.0")

    resolution = launcher.resolve_toolchain()

    assert resolution.kind == "managed"
    assert resolution.version == "0.10.0"
    assert resolution.path == newest / "bin"
    assert "newest version installed" in resolution.reason


def test_a_windows_shaped_managed_toolchain_is_startable(
    launcher: ModuleType, make_toolchain: Any
) -> None:
    root = make_toolchain("0.18.0", windows=True)
    resolution = launcher.resolve_toolchain()
    assert resolution.kind == "managed"
    assert resolution.path == root / "Scripts"
    assert launcher.toolchain_program(resolution, "s0ma-mcp") == root / "Scripts" / "s0ma-mcp.exe"


def test_every_reason_is_one_plain_sentence(
    launcher: ModuleType, project: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0")
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")
    reason = launcher.resolve_toolchain().reason
    assert reason.endswith(".")
    assert reason[0].isupper() or reason.startswith("s0ma")
    assert "\n" not in reason


# ---------------------------------------------------------------------------
# Finding uv.
# ---------------------------------------------------------------------------


def test_uv_is_found_on_the_path(launcher: ModuleType, tmp_path: Path) -> None:
    """``find_uv`` asks the host's own ``which``, so the file is spelled the
    host's way: on Windows ``which`` only matches a ``PATHEXT`` extension, and
    a bare ``uv`` there is invisible to it however ``windows=`` is set. (Found
    by the first Windows CI run of this suite.)
    """
    somewhere = tmp_path / "tools"
    somewhere.mkdir()
    uv = somewhere / ("uv.exe" if launcher.is_windows() else "uv")
    uv.write_text("#!/bin/sh\n", encoding="utf-8")
    uv.chmod(0o755)
    assert launcher.find_uv({"PATH": str(somewhere)}) == uv


def test_uv_is_found_where_it_installs_itself_when_the_path_is_bare(
    launcher: ModuleType, tmp_path: Path
) -> None:
    """A GUI-launched Claude does not read a shell profile (research note 7.4)."""
    home = tmp_path / "home"
    uv = home / ".local" / "bin" / "uv"
    uv.parent.mkdir(parents=True)
    uv.write_text("#!/bin/sh\n", encoding="utf-8")
    assert launcher.find_uv({"PATH": "", "HOME": str(home)}, windows=False) == uv


def test_uv_on_windows_is_looked_for_as_an_exe(launcher: ModuleType, tmp_path: Path) -> None:
    profile = tmp_path / "Users" / "someone"
    uv = profile / ".local" / "bin" / "uv.exe"
    uv.parent.mkdir(parents=True)
    uv.write_text("", encoding="utf-8")
    env = {"PATH": "", "USERPROFILE": str(profile)}
    assert launcher.find_uv(env, windows=True) == uv
    assert all(path.name == "uv.exe" for path in launcher.uv_candidates(env, windows=True))


def test_a_machine_without_uv_says_so_and_stops_with_code_seven(
    launcher: ModuleType, tmp_path: Path
) -> None:
    env = {"PATH": "", "USERPROFILE": str(tmp_path / "nobody")}
    assert launcher.find_uv(env, windows=True) is None
    with pytest.raises(launcher.LauncherError) as raised:
        launcher.require_uv(env, windows=True)
    assert raised.value.code == launcher.EXIT_NO_UV
    assert "uv" in raised.value.message
    assert "Install uv" in raised.value.message


# ---------------------------------------------------------------------------
# Handing the run to the toolchain: replace on POSIX, spawn and wait elsewhere.
# ---------------------------------------------------------------------------


def test_the_posix_branch_replaces_this_process(launcher: ModuleType) -> None:
    calls: list[tuple[str, list[str], dict[str, str]]] = []

    def fake_execv(path: str, argv: Any, env: Any) -> None:
        calls.append((path, list(argv), dict(env)))

    code = launcher.hand_off(
        ["/toolchain/bin/s0ma-mcp"],
        {"S0MA_HOME": "/somewhere"},
        replace=True,
        execv=fake_execv,
    )

    assert code == launcher.EXIT_OK
    assert len(calls) == 1
    path, argv, env = calls[0]
    assert path == "/toolchain/bin/s0ma-mcp"
    assert argv == ["/toolchain/bin/s0ma-mcp"]
    assert env["S0MA_HOME"] == "/somewhere"


def test_a_refused_replacement_still_starts_the_child(
    launcher: ModuleType, fakes: Any
) -> None:
    """If the kernel will not replace this process, a child is better than nothing."""

    def refusing_execv(path: str, argv: Any, env: Any) -> None:
        raise OSError(8, "Exec format error")

    spawner = fakes.Spawner(fakes.Process(returncode=3))
    code = launcher.hand_off(
        ["/toolchain/bin/s0ma-mcp"],
        {},
        replace=True,
        execv=refusing_execv,
        spawn=spawner,
        set_handler=fakes.Handlers(),
    )

    assert code == 3
    assert spawner.calls[0][0] == ["/toolchain/bin/s0ma-mcp"]


def test_the_windows_branch_spawns_waits_and_returns_the_childs_code(
    launcher: ModuleType, fakes: Any
) -> None:
    spawner = fakes.Spawner(fakes.Process(returncode=42))
    handlers = fakes.Handlers()

    code = launcher.hand_off(
        ["C:/toolchain/Scripts/s0ma-mcp.exe", "--flag"],
        {"S0MA_HOME": "C:/Users/someone/.s0ma"},
        replace=False,
        spawn=spawner,
        set_handler=handlers,
    )

    assert code == 42
    argv, env = spawner.calls[0]
    assert argv == ["C:/toolchain/Scripts/s0ma-mcp.exe", "--flag"]
    assert env["S0MA_HOME"] == "C:/Users/someone/.s0ma"
    assert spawner.process.waits == 1


def test_the_windows_branch_passes_signals_on_to_the_child(
    launcher: ModuleType, fakes: Any
) -> None:
    spawner = fakes.Spawner()
    handlers = fakes.Handlers()
    launcher.hand_off(["s0ma-mcp"], {}, replace=False, spawn=spawner, set_handler=handlers)

    handlers.fire(int(signal.SIGTERM))

    assert int(signal.SIGTERM) in spawner.process.signals


def test_a_signal_windows_refuses_becomes_a_polite_stop(
    launcher: ModuleType, fakes: Any
) -> None:
    """``Popen.send_signal`` on Windows raises for anything but a few signals."""
    spawner = fakes.Spawner(fakes.Process(refuse_signals=True))
    handlers = fakes.Handlers()
    launcher.hand_off(["s0ma-mcp"], {}, replace=False, spawn=spawner, set_handler=handlers)

    handlers.fire(int(signal.SIGINT))

    assert spawner.process.signals == []
    assert spawner.process.terminated is True


def test_the_original_signal_handlers_are_put_back(launcher: ModuleType, fakes: Any) -> None:
    spawner = fakes.Spawner()
    handlers = fakes.Handlers()
    launcher.hand_off(["s0ma-mcp"], {}, replace=False, spawn=spawner, set_handler=handlers)
    assert handlers.restored(int(signal.SIGTERM))
    assert handlers.restored(int(signal.SIGINT))


def test_a_platform_that_refuses_a_handler_still_starts_s0ma(
    launcher: ModuleType, fakes: Any
) -> None:
    """Off the main thread, ``signal.signal`` raises. That is not a reason to stop."""

    def refusing_handler(signum: int, handler: Any) -> Any:
        raise ValueError("signal only works in main thread")

    spawner = fakes.Spawner(fakes.Process(returncode=0))
    code = launcher.hand_off(
        ["s0ma-mcp"], {}, replace=False, spawn=spawner, set_handler=refusing_handler
    )
    assert code == 0
    assert spawner.process.waits == 1
