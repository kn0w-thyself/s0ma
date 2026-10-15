"""What the launcher tells a person, and what its commands do when run.

``status`` is the launcher's whole answer to "what is going on here?", so these
tests read it the way a user would: how many lines it is, whether it says
anything about a key beyond present-or-absent, whether a machine with nothing
installed is told something kind and actionable, and whether every character in
it will survive a Windows console that is not running in UTF-8 mode.

The rest of the file drives the commands themselves - ``serve``, ``run`` and the
shape of the command line as a whole - through :func:`s0ma_launch.main`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

#: The most lines ``status`` may print (plan milestone L1, task T4).
MAX_STATUS_LINES = 12

#: Anything that could be a real key, in any output. Nothing may match.
KEY_SHAPED = re.compile(r"s0ma_(?:live|test)_[A-Za-z0-9_-]{4,}")


# ---------------------------------------------------------------------------
# status: shape and manners.
# ---------------------------------------------------------------------------


def test_status_on_an_empty_machine_says_so_kindly(run_cli: Any) -> None:
    code, out, err = run_cli("status")

    assert code == 0
    assert err == ""
    assert "nothing yet" in out
    assert "s0ma is not installed on this machine yet." in out
    assert "Next step:" in out
    assert "/s0ma:setup" in out


def test_status_never_runs_longer_than_twelve_lines(
    run_cli: Any,
    project: Path,
    make_toolchain: Any,
    fake_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_toolchain("0.18.0")
    make_toolchain("0.19.0")
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")
    monkeypatch.setenv("S0MA_LICENSE_KEY", fake_key)

    _, out, _ = run_cli("status")

    lines = out.splitlines()
    assert 0 < len(lines) <= MAX_STATUS_LINES
    assert all(line.strip() for line in lines), "no blank filler lines"


def test_status_creates_nothing_under_the_state_directory(
    run_cli: Any, isolated_home: Path
) -> None:
    run_cli("status")
    assert list(isolated_home.iterdir()) == []


def test_status_asks_nothing_of_the_network(
    launcher: ModuleType, run_cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``status`` is the command a user runs when something is wrong. It is offline."""
    import socket

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("status opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    code, _, _ = run_cli("status")
    assert code == 0


def test_status_prints_only_ascii(
    run_cli: Any,
    project: Path,
    make_venv: Any,
    fake_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Windows console outside UTF-8 mode refuses anything else."""
    make_venv(project / ".venv", windows=True, version="0.18.0")
    monkeypatch.setenv("S0MA_LICENSE_KEY", fake_key)
    _, out, _ = run_cli("status")
    out.encode("ascii")
    out.encode("cp1252")


# ---------------------------------------------------------------------------
# status: the license key.
# ---------------------------------------------------------------------------


def test_a_key_shows_as_present_and_four_characters_only(
    run_cli: Any, fake_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S0MA_LICENSE_KEY", fake_key)

    _, out, _ = run_cli("status")

    assert "License key:  present (s0ma_...wxyz)" in out
    assert "from the plugin's settings" in out
    assert "not_a_real_key" not in out
    assert KEY_SHAPED.search(out) is None


def test_a_saved_key_says_where_it_lives(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, fake_key: str
) -> None:
    launcher.license_path(isolated_home).write_text(fake_key + "\n", encoding="utf-8")
    _, out, _ = run_cli("status")
    assert "present (s0ma_...wxyz), saved on this machine" in out


def test_no_key_is_stated_plainly(run_cli: Any) -> None:
    _, out, _ = run_cli("status")
    assert "License key:  not set" in out


def test_the_json_report_carries_no_key_either(
    run_cli: Any, fake_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S0MA_LICENSE_KEY", fake_key)

    _, out, _ = run_cli("status", "--json")

    assert KEY_SHAPED.search(out) is None
    report = json.loads(out)
    assert report["license_key"] == {
        "present": True,
        "last4": "wxyz",
        "source": "environment",
    }


# ---------------------------------------------------------------------------
# status: what it says about each resolution.
# ---------------------------------------------------------------------------


def test_status_names_the_managed_version_and_where_it_lives(
    run_cli: Any, make_toolchain: Any
) -> None:
    make_toolchain("0.9.0")
    make_toolchain("0.10.0")

    _, out, _ = run_cli("status")

    assert "Runs here:    s0ma 0.10.0, from " in out
    assert "Installed:    0.9.0, 0.10.0" in out
    assert "newest version installed" in out


def test_status_says_the_project_owns_its_copy_when_no_version_is_readable(
    run_cli: Any, project: Path, make_venv: Any
) -> None:
    make_venv(project / ".venv")
    _, out, _ = run_cli("status")
    assert "s0ma (the project's own copy), from " in out
    assert "(not pinned)" in out


def test_status_explains_a_pin_that_is_not_installed_and_what_to_do(
    run_cli: Any, project: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.19.0")
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")

    _, out, _ = run_cli("status")

    assert "pinned to 0.18.0" in out
    assert "not installed on this machine" in out
    assert "Next step:    Run `s0ma-launch install --version 0.18.0`" in out


def test_status_explains_a_pin_file_it_cannot_read(run_cli: Any, project: Path) -> None:
    (project / ".s0ma-version").write_text("newest\n", encoding="utf-8")

    _, out, _ = run_cli("status")

    assert "does not name a version" in out
    assert "Next step:    Fix or delete" in out
    assert ".s0ma-version" in out


def test_status_explains_an_override_that_holds_no_s0ma(
    run_cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "wrong-place"
    empty.mkdir()
    monkeypatch.setenv("S0MA_TOOLCHAIN", str(empty))

    _, out, _ = run_cli("status")

    assert "S0MA_TOOLCHAIN points at" in out
    assert "Next step:    Point S0MA_TOOLCHAIN at a directory that contains s0ma" in out


def test_status_forward_slashes_every_path_it_prints(
    run_cli: Any, make_toolchain: Any
) -> None:
    """NFR-7: a printed path looks the same on every platform."""
    make_toolchain("0.18.0")
    _, out, _ = run_cli("status")
    assert "\\" not in out


def test_status_reports_the_update_setting_in_words(
    run_cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, out, _ = run_cli("status")
    assert "Updates:      automatic" in out

    monkeypatch.setenv("S0MA_UPDATE", "off")
    _, out, _ = run_cli("status")
    assert "Updates:      off - s0ma never updates itself" in out


def test_status_reports_the_entitlement_it_last_saw(
    run_cli: Any, launcher: ModuleType, isolated_home: Path
) -> None:
    _, out, _ = run_cli("status")
    assert "Subscription: not checked yet" in out

    state = launcher.default_state()
    state["entitlement"] = "not_entitled"
    launcher.save_state(isolated_home, state)

    _, out, _ = run_cli("status")
    assert "Subscription: this account's access to new versions has ended" in out


def test_status_says_when_uv_is_missing(
    run_cli: Any, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "find_uv", lambda *a, **k: None)
    _, out, _ = run_cli("status")
    assert "uv:           not found on this machine" in out


# ---------------------------------------------------------------------------
# status --json
# ---------------------------------------------------------------------------


def test_the_json_report_has_the_fields_the_next_pieces_read(
    run_cli: Any, project: Path, make_toolchain: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_toolchain("0.18.0")
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(project / "plugin-data"))

    code, out, err = run_cli("status", "--json")

    assert code == 0
    assert err == ""
    report = json.loads(out)
    assert report["schema"] == "s0ma-launch-status@1"
    assert report["resolved"]["kind"] == "pinned"
    assert report["resolved"]["version"] == "0.18.0"
    assert report["resolved"]["named"] == "s0ma 0.18.0"
    assert report["installed"] == ["0.18.0"]
    assert report["pin"] == {"present": True, "version": "0.18.0", "problem": None}
    assert report["update"] == "auto"
    assert report["cp_host"] == "account.kn0wthyself.ai"
    assert report["entitlement"] == "unknown"
    assert report["plugin_data"].endswith("/plugin-data")
    assert report["next_step"]


def test_the_json_report_is_sorted_and_slash_only(run_cli: Any, make_toolchain: Any) -> None:
    make_toolchain("0.18.0")
    _, out, _ = run_cli("status", "--json")
    assert "\\" not in out
    keys = list(json.loads(out).keys())
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


def test_serve_hands_the_run_to_the_toolchains_server(
    launcher: ModuleType, run_cli: Any, make_toolchain: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_toolchain("0.18.0")
    handed: list[list[str]] = []
    monkeypatch.setattr(launcher, "hand_off", lambda argv, *a, **k: handed.append(list(argv)) or 0)

    code, out, err = run_cli("serve")

    assert code == 0
    assert handed == [[str(root / "bin" / "s0ma-mcp")]]
    assert out == "", "stdout belongs to the MCP conversation"
    assert err == ""


def test_serve_starts_the_windows_shaped_server_too(
    launcher: ModuleType, run_cli: Any, make_toolchain: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_toolchain("0.18.0", windows=True)
    handed: list[list[str]] = []
    monkeypatch.setattr(launcher, "hand_off", lambda argv, *a, **k: handed.append(list(argv)) or 0)

    run_cli("serve")

    assert handed == [[str(root / "Scripts" / "s0ma-mcp.exe")]]


def test_serve_passes_on_the_servers_own_exit_code(
    launcher: ModuleType, run_cli: Any, make_toolchain: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_toolchain("0.18.0")
    monkeypatch.setattr(launcher, "hand_off", lambda *a, **k: 17)
    code, _, _ = run_cli("serve")
    assert code == 17


def test_serve_with_nothing_installed_explains_itself_on_stderr(run_cli: Any) -> None:
    """stdout is the MCP channel: a stray line there breaks the session."""
    code, out, err = run_cli("serve")

    # Zero, not 3: the built-in stub server now takes the session and ends
    # cleanly when the input closes (plan section 4.4, milestone L3). The reason
    # is still said on stderr, which is what this test is about.
    assert code == 0
    assert out == ""
    assert "s0ma is not installed on this machine yet." in err
    assert "/s0ma:setup" in err


def test_serve_never_installs_anything(run_cli: Any, isolated_home: Path) -> None:
    """An MCP server has thirty seconds to answer. Installing is not its job."""
    run_cli("serve")
    assert list(isolated_home.iterdir()) == []


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_starts_a_toolchain_command_with_its_arguments(
    launcher: ModuleType, run_cli: Any, make_toolchain: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_toolchain("0.18.0")
    handed: list[list[str]] = []
    monkeypatch.setattr(launcher, "hand_off", lambda argv, *a, **k: handed.append(list(argv)) or 0)

    code, _, _ = run_cli("run", "--", "s0ma", "doctor", "--verbose")

    assert code == 0
    assert handed == [[str(root / "bin" / "s0ma"), "doctor", "--verbose"]]


def test_run_works_without_the_double_dash(
    launcher: ModuleType, run_cli: Any, make_toolchain: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_toolchain("0.18.0")
    handed: list[list[str]] = []
    monkeypatch.setattr(launcher, "hand_off", lambda argv, *a, **k: handed.append(list(argv)) or 0)

    run_cli("run", "s0ma", "check")

    assert handed == [[str(root / "bin" / "s0ma"), "check"]]


def test_run_with_no_command_says_what_it_needs(run_cli: Any) -> None:
    code, _, err = run_cli("run")
    assert code == 2
    assert "run -- s0ma doctor" in err


def test_run_refuses_anything_that_is_not_a_plain_command_name(
    run_cli: Any, make_toolchain: Any
) -> None:
    """The launcher runs the s0ma it resolved, never something else on the machine."""
    make_toolchain("0.18.0")
    for attempt in ("/bin/sh", "../../bin/sh", "C:/Windows/system32/cmd.exe"):
        code, _, err = run_cli("run", "--", attempt)
        assert code == 2
        assert "is not the name of a s0ma command" in err


def test_run_without_a_toolchain_says_so(run_cli: Any) -> None:
    code, _, err = run_cli("run", "--", "s0ma", "doctor")
    assert code == 3
    assert "s0ma is not installed on this machine yet." in err


def test_run_names_a_command_the_toolchain_does_not_have(
    run_cli: Any, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0", programs=("s0ma-mcp",))
    code, _, err = run_cli("run", "--", "s0ma", "doctor")
    assert code == 3
    assert "does not provide a command called `s0ma`" in err


# ---------------------------------------------------------------------------
# The command line as a whole.
# ---------------------------------------------------------------------------


def test_every_frozen_sub_command_exists(launcher: ModuleType) -> None:
    """Plan section 4.3. The shape is frozen from day one so the plugin, the
    extension and the skills can be written against it."""
    parser = launcher.build_parser()
    # argparse offers no public way to read back its sub-commands.
    choices = [getattr(action, "choices", None) for action in parser._actions]
    names = set(next(choice for choice in choices if choice))
    assert names == {
        "serve",
        "status",
        "install",
        "update",
        "pin",
        "unpin",
        "activate",
        "session-hint",
        "run",
    }


def test_no_arguments_prints_the_help(run_cli: Any) -> None:
    code, out, err = run_cli()
    assert code == 2
    assert out == ""
    assert "usage:" in err


def test_an_unknown_command_stops_with_the_usage_code(run_cli: Any) -> None:
    code, _, _ = run_cli("teleport")
    assert code == 2


def test_help_is_offered_and_costs_nothing(run_cli: Any) -> None:
    code, out, _ = run_cli("--help")
    assert code == 0
    assert "s0ma" in out


def test_run_help_still_reaches_the_parser(run_cli: Any) -> None:
    code, out, _ = run_cli("run", "--help")
    assert code == 0
    assert "s0ma doctor" in out


def test_no_message_the_launcher_prints_is_addressed_to_a_programmer(
    launcher: ModuleType,
) -> None:
    """House rule: user-facing text is for intelligent non-programmers."""
    source = (Path(launcher.__file__).read_text(encoding="utf-8")).lower()
    assert "payload" not in source
    assert "s0ma" in source
    assert "soma" not in source.replace("s0ma", "")
