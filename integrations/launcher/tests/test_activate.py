"""Taking a license key once, at a hidden prompt, and keeping it safe.

``activate`` is the way a key reaches a machine when it is not coming from the
plugin's settings screen. Everything about it is about the key never being seen:
it is typed at a prompt that does not echo, it is never a command-line argument
(arguments are readable by every process on the machine), it is checked once,
and the only place it is ever written is one owner-readable file. Afterwards the
launcher will say that there is a key and what its last four characters are, and
nothing else, ever.
"""

from __future__ import annotations

import json
import os
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


@pytest.fixture(autouse=True)
def _no_stray_offline_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("S0MA_LAUNCH_OFFLINE_INSTALL", raising=False)


@pytest.fixture
def at_a_terminal(launcher: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Pretend someone is sitting there, and answer the prompt for them."""
    asked: list[str] = []

    def _typing(answer: str) -> list[str]:
        monkeypatch.setattr(launcher, "_stdin_is_a_terminal", lambda: True)

        def prompt(text: str) -> str:
            asked.append(text)
            return answer

        monkeypatch.setattr(launcher, "_ask_for_key", prompt)
        return asked

    return _typing


@pytest.fixture
def unkeyed(
    control_plane: FakeControlPlane, monkeypatch: pytest.MonkeyPatch
) -> FakeControlPlane:
    """The fake control plane, with NO key in the environment: activate supplies it."""
    monkeypatch.setenv("S0MA_CP_HOST", control_plane.host)
    monkeypatch.delenv("S0MA_LICENSE_KEY", raising=False)
    return control_plane


def state_of(home: Path) -> dict[str, Any]:
    return json.loads((home / "launcher" / "state.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The happy path.
# ---------------------------------------------------------------------------


def test_a_key_that_is_accepted_is_saved_and_shown_only_as_its_last_four(
    run_cli: Any,
    unkeyed: FakeControlPlane,
    at_a_terminal: Any,
    isolated_home: Path,
    launcher: ModuleType,
) -> None:
    asked = at_a_terminal(unkeyed.key)

    code, out, err = run_cli("activate")

    assert code == 0, err
    assert out == ""
    assert asked == [launcher.ACTIVATE_PROMPT]
    saved = isolated_home / "license"
    assert saved.read_text(encoding="utf-8") == unkeyed.key + "\n"
    assert "That key was accepted" in err
    assert "s0ma_...wxyz" in err
    assert str(saved.as_posix()) in err
    assert unkeyed.key not in err, "the key itself is never printed"
    assert state_of(isolated_home)["entitlement"] == "ok"


def test_the_key_is_checked_exactly_once_and_only_in_a_header(
    run_cli: Any, unkeyed: FakeControlPlane, at_a_terminal: Any
) -> None:
    at_a_terminal(unkeyed.key)

    run_cli("activate")

    assert unkeyed.requests == ["GET /api/key/check"]
    assert unkeyed.authorizations == ["Bearer " + unkeyed.key]


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_the_saved_file_is_readable_by_its_owner_and_nobody_else(
    run_cli: Any, unkeyed: FakeControlPlane, at_a_terminal: Any, isolated_home: Path
) -> None:
    at_a_terminal(unkeyed.key)

    run_cli("activate")

    assert (isolated_home / "license").stat().st_mode & 0o777 == 0o600


def test_spaces_around_a_pasted_key_are_taken_off(
    run_cli: Any, unkeyed: FakeControlPlane, at_a_terminal: Any, isolated_home: Path
) -> None:
    at_a_terminal("  " + unkeyed.key + "  \n")

    code, _, err = run_cli("activate")

    assert code == 0, err
    assert (isolated_home / "license").read_text(encoding="utf-8") == unkeyed.key + "\n"


def test_the_key_saved_here_is_the_one_used_afterwards(
    run_cli: Any, unkeyed: FakeControlPlane, at_a_terminal: Any
) -> None:
    at_a_terminal(unkeyed.key)
    run_cli("activate")

    _, out, _ = run_cli("status")

    assert "present (s0ma_...wxyz), saved on this machine" in out


def test_the_control_planes_own_notice_is_passed_on_word_for_word(
    run_cli: Any, unkeyed: FakeControlPlane, at_a_terminal: Any
) -> None:
    unkeyed.notice = "Your beta access runs to the end of the year."
    at_a_terminal(unkeyed.key)

    _, _, err = run_cli("activate")

    assert err.strip().splitlines()[-2] == "Your beta access runs to the end of the year."


# ---------------------------------------------------------------------------
# Everything that stops it.
# ---------------------------------------------------------------------------


def test_without_a_terminal_it_says_where_else_a_key_can_go(
    run_cli: Any, unkeyed: FakeControlPlane, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "_stdin_is_a_terminal", lambda: False)

    code, _, err = run_cli("activate")

    assert code == 2
    assert "needs a real terminal" in err
    assert "plugin's settings" in err
    assert unkeyed.requests == []


def test_a_key_the_control_plane_refuses_is_not_written_anywhere(
    run_cli: Any, unkeyed: FakeControlPlane, at_a_terminal: Any, isolated_home: Path
) -> None:
    unkeyed.key_check_ok = False
    at_a_terminal(unkeyed.key)

    code, _, err = run_cli("activate")

    assert code == 4
    assert not (isolated_home / "license").exists()
    assert "Nothing was saved." in err
    assert "did not accept this license key" in err
    assert state_of(isolated_home)["entitlement"] == "invalid_key"


def test_an_account_whose_access_has_ended_is_told_so_here_too(
    run_cli: Any, unkeyed: FakeControlPlane, at_a_terminal: Any, isolated_home: Path
) -> None:
    unkeyed.not_entitled = True
    at_a_terminal(unkeyed.key)

    code, _, err = run_cli("activate")

    assert code == 4
    assert "access to new versions of s0ma has ended" in err
    assert not (isolated_home / "license").exists()
    assert state_of(isolated_home)["entitlement"] == "not_entitled"


def test_a_control_plane_that_cannot_be_reached_saves_nothing_and_blames_nobody(
    run_cli: Any,
    control_plane: FakeControlPlane,
    at_a_terminal: Any,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = control_plane.host
    control_plane.stop()
    monkeypatch.setenv("S0MA_CP_HOST", host)
    monkeypatch.delenv("S0MA_LICENSE_KEY", raising=False)
    at_a_terminal(control_plane.key)

    code, _, err = run_cli("activate")

    assert code == 5
    assert "could not reach its control plane" in err
    assert not (isolated_home / "license").exists()
    assert state_of(isolated_home)["entitlement"] == "unknown"


@pytest.mark.parametrize("typed", ["", "   ", "\n"])
def test_nothing_typed_means_nothing_saved(
    run_cli: Any, unkeyed: FakeControlPlane, at_a_terminal: Any, isolated_home: Path, typed: str
) -> None:
    at_a_terminal(typed)

    code, _, err = run_cli("activate")

    assert code == 2
    assert "Nothing was typed" in err
    assert not (isolated_home / "license").exists()
    assert unkeyed.requests == []


def test_a_prompt_that_is_abandoned_leaves_no_trace(
    run_cli: Any,
    unkeyed: FakeControlPlane,
    launcher: ModuleType,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "_stdin_is_a_terminal", lambda: True)

    def interrupted(_prompt: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(launcher, "_ask_for_key", interrupted)

    code, _, err = run_cli("activate")

    assert code == 2
    assert "Nothing was typed" in err
    assert not (isolated_home / "license").exists()


def test_a_key_cannot_be_given_as_an_argument(
    run_cli: Any, unkeyed: FakeControlPlane, isolated_home: Path
) -> None:
    """Arguments are readable by every process on the machine. There is no such form."""
    code, _, _ = run_cli("activate", "s0ma_test_not_a_real_key_wxyz")

    assert code == 2
    assert not (isolated_home / "license").exists()
    assert unkeyed.requests == []


# ---------------------------------------------------------------------------
# The prompt itself.
# ---------------------------------------------------------------------------


def test_the_prompt_is_the_one_that_does_not_echo(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        launcher.getpass, "getpass", lambda prompt: seen.append(prompt) or "typed"
    )

    assert launcher._ask_for_key("Key: ") == "typed"
    assert seen == ["Key: "]


def test_the_prompt_says_plainly_that_nothing_will_be_shown(launcher: ModuleType) -> None:
    assert "will not be shown" in launcher.ACTIVATE_PROMPT
    assert launcher.ACTIVATE_PROMPT.isascii()
