"""``set``: changing one of the launcher's own preferences.

The Claude Code plugin asks nothing at install, so the update mode lives in
the launcher's own config file, and ``set update <mode>`` is how a person, or
Claude on their behalf, changes it. ``S0MA_UPDATE`` still wins while it is set,
because the Claude Desktop extension passes it from its own settings.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def stored(launcher: ModuleType, home: Path) -> dict[str, Any]:
    data = json.loads(launcher.config_path(home).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.mark.parametrize("mode", ["auto", "notify", "off"])
def test_set_update_saves_the_mode(
    mode: str, run_cli: Any, launcher: ModuleType, isolated_home: Path
) -> None:
    code, out, err = run_cli("set", "update", mode)
    assert code == 0
    assert out == ""
    assert err == f"Saved. s0ma's update setting on this machine is now {mode}.\n"
    assert stored(launcher, isolated_home)["update"] == mode
    assert launcher.update_mode({}, launcher.load_config(isolated_home)) == mode


def test_set_keeps_the_other_settings(
    run_cli: Any, launcher: ModuleType, isolated_home: Path
) -> None:
    launcher.save_config(isolated_home, {"update": "auto", "cp_host": "cp.example"})
    assert run_cli("set", "update", "off")[0] == 0
    assert stored(launcher, isolated_home) == {"update": "off", "cp_host": "cp.example"}


def test_status_reports_the_saved_mode(run_cli: Any) -> None:
    run_cli("set", "update", "off")
    _, out, _ = run_cli("status")
    assert "Updates:      off" in out


@pytest.mark.parametrize(
    "argv",
    [
        ("set",),
        ("set", "update"),
        ("set", "update", "sometimes"),
        ("set", "colour", "blue"),
        ("set", "cp_host", "evil.example"),
    ],
    ids=["nothing", "no value", "bad value", "unknown name", "not settable"],
)
def test_set_refuses_anything_else_and_changes_nothing(
    argv: tuple[str, ...], run_cli: Any, launcher: ModuleType, isolated_home: Path
) -> None:
    code, out, err = run_cli(*argv)
    assert code == launcher.EXIT_USAGE
    assert out == ""
    assert err == (
        "Nothing was changed. Use `s0ma-launch set update <auto|notify|off>` or "
        "`s0ma-launch set use <always|asked>` or "
        "`s0ma-launch set studi0 <always|offer|asked>`.\n"
    )
    assert not launcher.config_path(isolated_home).exists()


def test_the_environment_still_wins_and_set_says_so(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    code, _, err = run_cli("set", "update", "off")
    assert code == 0
    assert "S0MA_UPDATE is set to notify" in err
    assert stored(launcher, isolated_home)["update"] == "off"
    assert launcher.update_mode(None, launcher.load_config(isolated_home)) == "notify"


def test_set_opens_no_connection(run_cli: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proven by making a socket impossible: anything that tried would raise."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("set must never open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert run_cli("set", "update", "notify")[0] == 0


def test_every_output_is_ascii(run_cli: Any) -> None:
    for argv in (("set", "update", "off"), ("set", "nope")):
        _, out, err = run_cli(*argv)
        (out + err).encode("ascii")


# ---------------------------------------------------------------------------
# use and studi0: the two a person sets by saying so in Claude.
# ---------------------------------------------------------------------------

USE_SAID = {
    "always": (
        "Saved. s0ma's use setting on this machine is now always: s0ma on new "
        "work without being asked.\n"
    ),
    "asked": (
        "Saved. s0ma's use setting on this machine is now asked: s0ma only when "
        "asked.\n"
    ),
}

STUDI0_SAID = {
    "always": (
        "Saved. s0ma's studi0 setting on this machine is now always: studi0 "
        "opened at the first build of each session.\n"
    ),
    "offer": (
        "Saved. s0ma's studi0 setting on this machine is now offer: studi0 "
        "offered once per project.\n"
    ),
    "asked": (
        "Saved. s0ma's studi0 setting on this machine is now asked: studi0 only "
        "when asked.\n"
    ),
}


@pytest.mark.parametrize("value", ["always", "asked"])
def test_set_use_saves_the_value_beside_update(
    value: str, run_cli: Any, launcher: ModuleType, isolated_home: Path
) -> None:
    code, out, err = run_cli("set", "use", value)
    assert (code, out) == (0, "")
    assert err == USE_SAID[value]
    assert stored(launcher, isolated_home) == {
        "cp_host": "account.kn0wthyself.ai",
        "update": "auto",
        "use": value,
    }
    assert launcher.machine_use(launcher.load_config(isolated_home)) == value


@pytest.mark.parametrize("value", ["always", "offer", "asked"])
def test_set_studi0_saves_the_value_beside_update(
    value: str, run_cli: Any, launcher: ModuleType, isolated_home: Path
) -> None:
    code, out, err = run_cli("set", "studi0", value)
    assert (code, out) == (0, "")
    assert err == STUDI0_SAID[value]
    assert stored(launcher, isolated_home) == {
        "cp_host": "account.kn0wthyself.ai",
        "studi0": value,
        "update": "auto",
    }
    assert launcher.machine_studi0(launcher.load_config(isolated_home)) == value


def test_the_three_settings_live_side_by_side(
    run_cli: Any, launcher: ModuleType, isolated_home: Path
) -> None:
    """Setting one never resets another, and ``update`` still works."""
    assert run_cli("set", "use", "always")[0] == 0
    assert run_cli("set", "studi0", "asked")[0] == 0
    code, _, err = run_cli("set", "update", "notify")
    assert code == 0
    assert err == "Saved. s0ma's update setting on this machine is now notify.\n"
    assert stored(launcher, isolated_home) == {
        "cp_host": "account.kn0wthyself.ai",
        "studi0": "asked",
        "update": "notify",
        "use": "always",
    }
    assert run_cli("set", "use", "asked")[0] == 0
    assert stored(launcher, isolated_home)["studi0"] == "asked"
    assert stored(launcher, isolated_home)["update"] == "notify"
    assert stored(launcher, isolated_home)["use"] == "asked"


@pytest.mark.parametrize(
    "argv",
    [
        ("set", "use"),
        ("set", "use", "offer"),
        ("set", "use", "sometimes"),
        ("set", "studi0"),
        ("set", "studi0", "never"),
        ("set", "studi0", "off"),
    ],
)
def test_a_wrong_value_for_use_or_studi0_changes_nothing(
    argv: tuple[str, ...], run_cli: Any, launcher: ModuleType, isolated_home: Path
) -> None:
    run_cli("set", "use", "always")
    before = stored(launcher, isolated_home)
    code, out, err = run_cli(*argv)
    assert code == launcher.EXIT_USAGE
    assert out == ""
    assert err.startswith("Nothing was changed. Use ")
    assert stored(launcher, isolated_home) == before


def test_a_wrong_value_on_a_clean_machine_writes_nothing(
    run_cli: Any, launcher: ModuleType, isolated_home: Path
) -> None:
    assert run_cli("set", "use", "never")[0] == launcher.EXIT_USAGE
    assert not launcher.config_path(isolated_home).exists()


def test_values_in_the_config_file_that_mean_nothing_fall_back(
    launcher: ModuleType,
) -> None:
    for config in ({}, {"use": "sometimes", "studi0": 3}, {"use": None, "studi0": "offered"}):
        assert launcher.machine_use(config) == "asked"
        assert launcher.machine_studi0(config) == "offer"
