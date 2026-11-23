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
        "Nothing was changed. Use `s0ma-launch set update <auto|notify|off>`.\n"
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
