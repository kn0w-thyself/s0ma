"""What a new Claude session is told, and everything it must never do to say it.

``s0ma-launch session-hint`` is the body of the plugin's ``SessionStart`` hook.
Claude's first answer waits for that hook, so this command lives under three
promises, and most of the file below is about the second and third rather than
about the words:

* it says one thing, or nothing;
* it reads local files and does nothing else - no socket, no subprocess, and no
  write, not even the tidying-up the everyday readers do when they meet a
  spoiled file;
* it never fails, whatever it is handed.

Every test here runs the command in this process, through the ``run_cli``
fixture, with ``S0MA_HOME`` inside ``tmp_path`` (see ``conftest.py``). Nothing
here opens a socket or spawns anything, and two tests prove that by making both
impossible first.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# The exact words. Written out in full, not built from the launcher's own
# constants: a test that assembles the sentence the same way the code does
# cannot notice the code assembling the wrong sentence.
# ---------------------------------------------------------------------------

NOTHING_INSTALLED = (
    "s0ma's tools are not available in this session. "
    "s0ma is not installed on this machine yet. "
    "Run /s0ma:setup in Claude to fix that."
)
NOTHING_INSTALLED_CONTEXT = (
    "s0ma's tools are not available in this session. "
    "s0ma is not installed on this machine yet. "
    "The /s0ma:setup skill fixes that."
)
PIN_NOT_INSTALLED = (
    "s0ma's tools are not available in this session. "
    "This project asks for s0ma 0.19.0 in its .s0ma-version file, and that "
    "version is not installed on this machine. "
    "Run /s0ma:setup in Claude to fix that."
)
PIN_NOT_INSTALLED_CONTEXT = (
    "s0ma's tools are not available in this session. "
    "This project asks for s0ma 0.19.0 in its .s0ma-version file, and that "
    "version is not installed on this machine. "
    "The /s0ma:setup skill fixes that."
)
KEY_REFUSED = (
    "The last time s0ma used your license key, it was refused. "
    "Put it in the s0ma plugin's settings in Claude, or run `s0ma-launch "
    "activate` in a terminal to save it on this machine. "
    "Never type a license key into a chat."
)
ACCESS_ENDED = (
    "This account's access to new versions of s0ma has ended. "
    "The copy you have installed keeps working. "
    "Your subscription is at account.kn0wthyself.ai."
)
NEWER_AVAILABLE = (
    "s0ma 0.19.0 is available; s0ma 0.18.0 is what runs here. "
    "Run /s0ma:update in Claude when you want it."
)
UPDATE_WAITING = (
    "s0ma 0.19.0 was fetched quietly in the background, and it is what Claude "
    "will use from your next session."
)
TOO_LONG = (
    "s0ma has something to say about this machine, and it did not fit in one "
    "line. Run /s0ma:doctor in Claude to see it."
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def write_state(launcher: ModuleType, home: Path, **fields: Any) -> Path:
    """Write ``launcher/state.json`` with *fields* over the defaults."""
    state = launcher.default_state()
    state.update(fields)
    path = launcher.state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def write_config(launcher: ModuleType, home: Path, **fields: Any) -> Path:
    """Write ``launcher/config.json`` with *fields* over the defaults."""
    config = launcher.default_config()
    config.update(fields)
    path = launcher.config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(config, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def spoken(out: str) -> dict[str, Any]:
    """The one line of JSON the hook printed, parsed, with its shape checked."""
    assert out, "the hook said nothing"
    assert out.endswith("\n"), "the hook's line must end in a newline"
    body = out[:-1]
    assert "\n" not in body, f"the hook printed more than one line:\n{out}"
    assert body.isascii(), "everything the hook prints is plain ASCII"
    assert len(body) < 600, f"the hook printed {len(body)} characters"
    parsed = json.loads(body)
    assert isinstance(parsed, dict)
    return parsed


def message_of(out: str) -> str:
    """The line shown to the person."""
    return str(spoken(out)["systemMessage"])


def context_of(out: str) -> str | None:
    """The context given to the model, when there is any."""
    extra = spoken(out).get("hookSpecificOutput")
    if extra is None:
        return None
    assert extra["hookEventName"] == "SessionStart"
    return str(extra["additionalContext"])


def snapshot(*roots: Path) -> dict[str, bytes]:
    """Every file under *roots*, by path and content."""
    taken: dict[str, bytes] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                taken[str(path)] = path.read_bytes()
    return taken


# ---------------------------------------------------------------------------
# 1. There is nothing to run here at all.
# ---------------------------------------------------------------------------


def test_nothing_installed_tells_the_person_and_the_model(run_cli: Any) -> None:
    """A machine with no s0ma on it. The model needs this one too: without it,
    it will offer to use tools that cannot answer."""
    code, out, err = run_cli("session-hint")
    assert code == 0
    assert err == ""
    assert message_of(out) == NOTHING_INSTALLED
    assert context_of(out) == NOTHING_INSTALLED_CONTEXT


def test_a_broken_toolchain_override_is_named_rather_than_ignored(
    run_cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit answer that holds no s0ma is still "nothing runs here", and
    the person is told which explicit answer it was."""
    monkeypatch.setenv("S0MA_TOOLCHAIN", "nowhere/at/all")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    message = message_of(out)
    assert message.startswith("s0ma's tools are not available in this session.")
    assert "S0MA_TOOLCHAIN points at nowhere/at/all" in message
    assert message.endswith("Run /s0ma:setup in Claude to fix that.")


# ---------------------------------------------------------------------------
# 2. The project asks for a version that is not installed.
# ---------------------------------------------------------------------------


def test_a_pin_that_is_not_installed_names_the_version(
    run_cli: Any, project: Path
) -> None:
    (project / ".s0ma-version").write_text("0.19.0\n", encoding="utf-8")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == PIN_NOT_INSTALLED
    assert context_of(out) == PIN_NOT_INSTALLED_CONTEXT


def test_a_pin_that_is_installed_says_nothing(
    run_cli: Any, project: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.19.0")
    (project / ".s0ma-version").write_text("0.19.0\n", encoding="utf-8")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


# ---------------------------------------------------------------------------
# 3 and 4. What the control plane last said.
# ---------------------------------------------------------------------------


def test_a_refused_key_says_where_a_key_goes_and_never_asks_for_one(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, make_toolchain: Any
) -> None:
    """The two places a key may be typed, and the one place it may not."""
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement="invalid_key")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    message = message_of(out)
    assert message == KEY_REFUSED
    assert context_of(out) is None, "a refused key changes nothing for the model"
    assert "Never type a license key into a chat." in message


def test_a_refused_key_never_shows_the_key(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
    fake_key: str,
) -> None:
    """Not the key, and not the last four characters of it either: this line is
    about where a key goes, and shows nothing about the one on the machine."""
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement="invalid_key")
    monkeypatch.setenv("S0MA_LICENSE_KEY", fake_key)
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert fake_key not in out
    assert fake_key[-4:] not in out


def test_access_that_has_ended_says_what_still_works(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement="not_entitled")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == ACCESS_ENDED
    assert context_of(out) is None


def test_access_that_has_ended_names_the_configured_host(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tester pointed at a different control plane is sent to that one."""
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement="not_entitled")
    monkeypatch.setenv("S0MA_CP_HOST", "account.example.test")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out).endswith("Your subscription is at account.example.test.")


@pytest.mark.parametrize("entitlement", ["ok", "unknown"])
def test_an_untroubled_entitlement_says_nothing(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    entitlement: str,
) -> None:
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement=entitlement)
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


# ---------------------------------------------------------------------------
# 5. A newer version exists, and this machine asked to be told.
# ---------------------------------------------------------------------------


def test_notify_names_both_versions_and_the_update_skill(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement="ok", latest_seen="0.19.0")
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == NEWER_AVAILABLE
    assert context_of(out) is None


def test_the_stored_setting_is_read_when_the_variable_is_unset(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, make_toolchain: Any
) -> None:
    """``notify`` in ``config.json`` does the same as ``S0MA_UPDATE=notify``."""
    make_toolchain("0.18.0")
    write_config(launcher, isolated_home, update="notify")
    write_state(launcher, isolated_home, entitlement="ok", latest_seen="0.19.0")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == NEWER_AVAILABLE


def test_notify_says_nothing_when_the_newest_seen_is_what_runs(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_toolchain("0.19.0")
    write_state(launcher, isolated_home, entitlement="ok", latest_seen="0.19.0")
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


def test_notify_compares_versions_as_numbers(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0.9.0 is older than 0.10.0, whatever sorting the two strings would say."""
    make_toolchain("0.10.0")
    write_state(launcher, isolated_home, entitlement="ok", latest_seen="0.9.0")
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


def test_auto_does_not_announce_a_version_it_will_fetch_by_itself(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under ``auto`` the whole point is that nobody has to do anything."""
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement="ok", latest_seen="0.19.0")
    monkeypatch.setenv("S0MA_UPDATE", "auto")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


# ---------------------------------------------------------------------------
# 6. A newer version is already here, waiting to be started.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["auto", "notify"])
def test_a_waiting_update_is_one_calm_line(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    make_toolchain("0.18.0")
    make_toolchain("0.19.0")
    write_state(
        launcher,
        isolated_home,
        entitlement="ok",
        latest_seen="0.19.0",
        pending="0.19.0",
    )
    monkeypatch.setenv("S0MA_UPDATE", mode)
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == UPDATE_WAITING
    assert context_of(out) is None


def test_a_stale_pending_record_is_not_news(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``pending`` naming a version older than the one that would start here
    is a record left behind, not an update waiting."""
    make_toolchain("0.18.0")
    make_toolchain("0.19.0")
    write_state(launcher, isolated_home, entitlement="ok", pending="0.18.0")
    monkeypatch.setenv("S0MA_UPDATE", "auto")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


def test_nonsense_in_the_pending_field_is_ignored(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement="ok", pending={"not": "a version"})
    monkeypatch.setenv("S0MA_UPDATE", "auto")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


# ---------------------------------------------------------------------------
# Updates switched off, and copies of s0ma that are not the launcher's to move.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["latest_seen", "pending"])
def test_updates_off_silences_both_update_lines(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    make_toolchain("0.18.0")
    make_toolchain("0.19.0")
    write_state(launcher, isolated_home, entitlement="ok", **{field: "0.19.0"})
    monkeypatch.setenv("S0MA_UPDATE", "off")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


def test_a_project_with_its_own_s0ma_hears_nothing_about_updates(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    project: Path,
    make_venv: Any,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A project that carries its own copy is pinned by construction; the
    launcher never moves it, so promising it a newer s0ma would be untrue."""
    make_venv(project / ".venv", version="0.17.0")
    make_toolchain("0.19.0")
    write_state(
        launcher,
        isolated_home,
        entitlement="ok",
        latest_seen="0.19.0",
        pending="0.19.0",
    )
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


def test_a_pinned_project_hears_nothing_about_updates(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    project: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_toolchain("0.18.0")
    make_toolchain("0.19.0")
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")
    write_state(
        launcher,
        isolated_home,
        entitlement="ok",
        latest_seen="0.19.0",
        pending="0.19.0",
    )
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


def test_a_contributors_own_checkout_hears_nothing_about_updates(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    tmp_path: Path,
    make_venv: Any,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    own = tmp_path / "checkout"
    make_venv(own, version="0.18.0")
    monkeypatch.setenv("S0MA_TOOLCHAIN", str(own))
    make_toolchain("0.19.0")
    write_state(
        launcher,
        isolated_home,
        entitlement="ok",
        latest_seen="0.19.0",
        pending="0.19.0",
    )
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


# ---------------------------------------------------------------------------
# Only ever one thing is said, and this is the order.
# ---------------------------------------------------------------------------


def test_nothing_to_run_outranks_everything_else(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_state(
        launcher,
        isolated_home,
        entitlement="invalid_key",
        latest_seen="0.19.0",
        pending="0.19.0",
    )
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == NOTHING_INSTALLED


def test_a_refused_key_outranks_an_ended_subscription_and_the_updates(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_toolchain("0.18.0")
    make_toolchain("0.19.0")
    write_state(
        launcher,
        isolated_home,
        entitlement="invalid_key",
        latest_seen="0.20.0",
        pending="0.19.0",
    )
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == KEY_REFUSED


def test_an_ended_subscription_outranks_the_updates(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_toolchain("0.18.0")
    write_state(
        launcher, isolated_home, entitlement="not_entitled", latest_seen="0.19.0"
    )
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == ACCESS_ENDED


def test_being_told_outranks_something_already_waiting(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_toolchain("0.18.0")
    make_toolchain("0.19.0")
    write_state(
        launcher,
        isolated_home,
        entitlement="ok",
        latest_seen="0.20.0",
        pending="0.19.0",
    )
    monkeypatch.setenv("S0MA_UPDATE", "notify")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out).startswith("s0ma 0.20.0 is available;")


# ---------------------------------------------------------------------------
# The shape of what is printed.
# ---------------------------------------------------------------------------


def test_the_person_gets_a_system_message_and_the_model_gets_nothing_extra(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, make_toolchain: Any
) -> None:
    """Plain stdout from a SessionStart hook becomes context the model reads
    (https://code.claude.com/docs/en/hooks), so a line meant for the person is
    printed as JSON with ``systemMessage`` and nothing else in it."""
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement="not_entitled")
    _, out, _ = run_cli("session-hint")
    assert list(spoken(out)) == ["systemMessage"]


def test_the_model_is_only_ever_told_that_the_tools_are_missing(
    run_cli: Any,
) -> None:
    printed = spoken(run_cli("session-hint")[1])
    assert sorted(printed) == ["hookSpecificOutput", "systemMessage"]
    assert sorted(printed["hookSpecificOutput"]) == [
        "additionalContext",
        "hookEventName",
    ]
    assert printed["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_a_line_that_still_will_not_fit_points_at_the_doctor_skill(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last-resort guard, over every case rather than one of them.

    Nothing said here is normally anywhere near the ceiling; a control-plane
    host somebody set to nonsense is the way to get past it, and the answer is
    the skill that can print the whole story.
    """
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement="not_entitled")
    monkeypatch.setenv("S0MA_CP_HOST", "h" * 600)
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == TOO_LONG
    assert context_of(out) is None


def test_a_path_that_is_not_ascii_still_prints_as_ascii(
    run_cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The line goes to a Windows console that may not be in UTF-8 mode, so it
    is escaped rather than sent as bytes that console cannot show."""
    monkeypatch.setenv("S0MA_TOOLCHAIN", "café/bin")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert out.isascii(), "the printed bytes are plain ASCII"
    assert "café/bin" in message_of(out), "and decode back to the real path"


def test_a_cause_too_long_to_read_is_dropped_but_the_fix_is_not(
    run_cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Somebody's very long directory must not turn a glance into a paragraph.

    The symptom and the one thing to do survive; only the why goes, and
    ``/s0ma:setup`` prints the why in full.
    """
    monkeypatch.setenv("S0MA_TOOLCHAIN", "/" + "/".join(["a-long-directory"] * 25))
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == (
        "s0ma's tools are not available in this session. "
        "Run /s0ma:setup in Claude to fix that."
    )
    assert context_of(out) == (
        "s0ma's tools are not available in this session. "
        "The /s0ma:setup skill fixes that."
    )


# ---------------------------------------------------------------------------
# What it must never do: reach out, spawn anything, or write.
# ---------------------------------------------------------------------------


def test_no_socket_is_opened(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proven by making a socket impossible: anything that tried would raise,
    and the command's own safety net would then swallow the line it owes."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("session-hint must never open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement="not_entitled")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == ACCESS_ENDED


def test_no_process_is_spawned(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    make_toolchain: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `uv`, no s0ma, nothing: the version that would run here is read off
    the disk, never asked for."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("session-hint must never spawn a process")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    make_toolchain("0.18.0")
    write_state(launcher, isolated_home, entitlement="invalid_key")
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == KEY_REFUSED


def test_nothing_on_disk_is_touched(
    run_cli: Any,
    launcher: ModuleType,
    isolated_home: Path,
    project: Path,
    make_toolchain: Any,
) -> None:
    make_toolchain("0.18.0")
    write_config(launcher, isolated_home, update="notify")
    write_state(launcher, isolated_home, entitlement="ok", latest_seen="0.19.0")
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")
    before = snapshot(isolated_home, project)
    run_cli("session-hint")
    assert snapshot(isolated_home, project) == before


def test_an_empty_state_directory_stays_empty(
    run_cli: Any, isolated_home: Path, project: Path
) -> None:
    """``status`` is allowed to leave a clean machine clean; a hook has to."""
    code, out, _ = run_cli("session-hint")
    assert code == 0
    assert message_of(out) == NOTHING_INSTALLED
    assert list(isolated_home.rglob("*")) == []
    assert list(project.rglob("*")) == []


# ---------------------------------------------------------------------------
# It never fails a session.
# ---------------------------------------------------------------------------


def test_a_spoiled_state_file_is_neither_repaired_nor_complained_about(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, make_toolchain: Any
) -> None:
    """The everyday reader would move this aside, write a fresh one and say so
    on stderr. A hook does none of the three."""
    make_toolchain("0.18.0")
    path = launcher.state_path(isolated_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")
    assert path.read_text(encoding="utf-8") == "{ this is not json"
    assert not path.with_name(path.name + ".corrupt").exists()


def test_a_spoiled_settings_file_is_left_alone_too(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0")
    path = launcher.config_path(isolated_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]", encoding="utf-8")
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")
    assert path.read_text(encoding="utf-8") == "[]"
    assert not path.with_name(path.name + ".corrupt").exists()


def test_a_state_file_holding_the_wrong_kinds_of_value_says_nothing(
    run_cli: Any, launcher: ModuleType, isolated_home: Path, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0")
    path = launcher.state_path(isolated_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"entitlement": 7, "latest_seen": [], "pending": True}),
        encoding="utf-8",
    )
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root reads a directory whatever its mode says",
)
def test_a_project_directory_that_cannot_be_read_is_survivable(
    run_cli: Any, project: Path
) -> None:
    project.chmod(0o000)
    try:
        code, out, err = run_cli("session-hint")
    finally:
        project.chmod(0o700)
    assert code == 0
    assert err == ""
    if out:
        spoken(out)


def test_an_unexpected_failure_ends_as_silence(
    run_cli: Any, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever breaks, a session never sees a hook error because of it."""

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("something nobody thought of")

    monkeypatch.setattr(launcher, "session_hint", explode)
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


def test_a_failure_while_rendering_the_line_ends_as_silence(
    run_cli: Any, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("unprintable")

    monkeypatch.setattr(launcher, "hint_line", explode)
    code, out, err = run_cli("session-hint")
    assert (code, out, err) == (0, "", "")


def test_a_closed_pipe_ends_as_silence(
    launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude Code closing the hook's pipe early is not a reason to fail."""

    class ClosedPipe:
        def write(self, text: str) -> int:
            raise BrokenPipeError("closed")

        def flush(self) -> None:
            return None

    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    assert launcher.main(["session-hint"]) == 0


# ---------------------------------------------------------------------------
# It is quick enough to sit in front of Claude's first answer.
# ---------------------------------------------------------------------------


def test_the_hint_is_quick(
    launcher: ModuleType,
    isolated_home: Path,
    project: Path,
    make_toolchain: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Under two tenths of a second, measured in this process.

    The bound is deliberately far above what the work costs - the budget in the
    plan is 200 ms, and the fastest of several runs on a busy machine is what is
    checked, so a loaded build agent cannot turn a slow moment into a failure.
    """
    for version in ("0.16.0", "0.17.0", "0.18.0", "0.19.0"):
        make_toolchain(version)
    write_config(launcher, isolated_home, update="notify")
    write_state(launcher, isolated_home, entitlement="ok", latest_seen="0.20.0")
    (project / ".s0ma-version").write_text("0.19.0\n", encoding="utf-8")

    best = None
    for _ in range(5):
        started = time.perf_counter()
        code = launcher.main(["session-hint"])
        taken = time.perf_counter() - started
        capsys.readouterr()
        assert code == 0
        best = taken if best is None else min(best, taken)
    assert best is not None
    assert best < 0.5, f"the fastest of five runs took {best * 1000:.0f} ms"
