"""Holding one project on one version of s0ma, and letting it go again.

A pin is one small file, ``.s0ma-version``, in the project directory - the same
directory the launcher reads it from, with no searching upwards, so what `pin`
writes is exactly what `serve` will read (gate ruling 4). These tests cover what
it says to the person, what it refuses to do, and the one case where a pin would
be a lie: a project that carries its own copy of s0ma is already held on one
version by its own dependencies.
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# pin
# ---------------------------------------------------------------------------


def test_pin_writes_one_line_and_says_what_it_means(
    run_cli: Any, keyed: FakeControlPlane, project: Path
) -> None:
    code, out, err = run_cli("pin", "0.18.0")

    assert code == 0, err
    assert out == ""
    assert (project / ".s0ma-version").read_text(encoding="utf-8") == "0.18.0\n"
    assert "stays on s0ma 0.18.0 until someone unpins it" in err
    assert "s0ma-launch unpin" in err


def test_pin_says_how_to_get_a_version_that_is_not_here_yet(
    run_cli: Any, keyed: FakeControlPlane
) -> None:
    _, _, err = run_cli("pin", "0.18.0")

    assert "is not installed on this machine yet" in err
    assert "install --version 0.18.0" in err


def test_pin_does_not_say_that_about_a_version_that_is_here(
    run_cli: Any, keyed: FakeControlPlane, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0")

    _, _, err = run_cli("pin", "0.18.0")

    assert "is not installed on this machine yet" not in err


def test_pin_asks_whether_the_version_exists(
    run_cli: Any, keyed: FakeControlPlane, project: Path
) -> None:
    code, _, err = run_cli("pin", "0.99.0")

    assert code == 2
    assert "has no version 0.99.0" in err
    assert not (project / ".s0ma-version").exists(), "nothing is written on a refusal"


def test_pin_offline_writes_the_file_without_asking_anybody(
    run_cli: Any, keyed: FakeControlPlane, project: Path
) -> None:
    code, _, err = run_cli("pin", "0.99.0", "--offline")

    assert code == 0, err
    assert (project / ".s0ma-version").read_text(encoding="utf-8") == "0.99.0\n"
    assert keyed.requests == []


def test_pin_without_a_key_still_pins_and_says_it_could_not_check(
    run_cli: Any, control_plane: FakeControlPlane, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S0MA_CP_HOST", control_plane.host)

    code, _, err = run_cli("pin", "0.18.0")

    assert code == 0
    assert "could not check whether 0.18.0 exists" in err
    assert "no license key" in err
    assert (project / ".s0ma-version").read_text(encoding="utf-8") == "0.18.0\n"


def test_pin_still_pins_when_the_control_plane_cannot_be_reached(
    run_cli: Any,
    control_plane: FakeControlPlane,
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = control_plane.host
    control_plane.stop()
    monkeypatch.setenv("S0MA_CP_HOST", host)
    monkeypatch.setenv("S0MA_LICENSE_KEY", control_plane.key)

    code, _, err = run_cli("pin", "0.18.0")

    assert code == 0
    assert "could not check" in err
    assert (project / ".s0ma-version").is_file()


@pytest.mark.parametrize("given", ["latest", "v0.18.0", "0.18.0; rm -rf /", "", "  "])
def test_something_that_is_not_a_version_is_refused(
    run_cli: Any, keyed: FakeControlPlane, project: Path, given: str
) -> None:
    code, _, err = run_cli("pin", given)

    assert code == 2
    assert "does not look like a version" in err
    assert not (project / ".s0ma-version").exists()
    assert keyed.requests == []


def test_pin_writes_where_claude_says_the_project_is(
    run_cli: Any, keyed: FakeControlPlane, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate ruling 4: the project is CLAUDE_PROJECT_DIR, with no search upwards."""
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(elsewhere))

    assert run_cli("pin", "0.18.0", "--offline")[0] == 0
    assert (elsewhere / ".s0ma-version").read_text(encoding="utf-8") == "0.18.0\n"


def test_what_is_pinned_is_what_runs(
    run_cli: Any, keyed: FakeControlPlane, make_toolchain: Any
) -> None:
    make_toolchain("0.18.0")
    make_toolchain("0.19.0")

    run_cli("pin", "0.18.0", "--offline")
    _, out, _ = run_cli("status")

    assert "pinned to 0.18.0" in out
    assert "s0ma 0.18.0" in out


def test_a_pin_to_something_that_is_not_installed_sends_people_to_setup(
    run_cli: Any, keyed: FakeControlPlane, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`serve` answers with the setup helper rather than the wrong version."""
    run_cli("pin", "0.99.0", "--offline")
    monkeypatch.setattr(launcher, "serve_stub", lambda *a, **k: 0)

    code, out, err = run_cli("serve")

    assert code == 0
    assert out == ""
    assert "asks for s0ma 0.99.0" in err
    assert "install --version 0.99.0" in err


def test_pinning_over_an_earlier_pin_replaces_it(
    run_cli: Any, keyed: FakeControlPlane, project: Path
) -> None:
    (project / ".s0ma-version").write_text("0.17.0\n", encoding="utf-8")

    run_cli("pin", "0.18.0", "--offline")

    assert (project / ".s0ma-version").read_text(encoding="utf-8") == "0.18.0\n"


# ---------------------------------------------------------------------------
# unpin
# ---------------------------------------------------------------------------


def test_unpin_removes_the_file_and_says_so(
    run_cli: Any, project: Path
) -> None:
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")

    code, out, err = run_cli("unpin")

    assert code == 0
    assert out == ""
    assert not (project / ".s0ma-version").exists()
    assert "no longer asks for a particular version" in err


def test_unpin_with_nothing_to_remove_is_not_a_failure(
    run_cli: Any, project: Path
) -> None:
    code, _, err = run_cli("unpin")

    assert code == 0
    assert "nothing to remove" in err


# ---------------------------------------------------------------------------
# A project that carries its own copy of s0ma pins itself.
# ---------------------------------------------------------------------------


def test_pin_refuses_inside_a_project_with_its_own_copy_of_s0ma(
    run_cli: Any, keyed: FakeControlPlane, project: Path, make_venv: Any
) -> None:
    make_venv(project / ".venv")

    code, _, err = run_cli("pin", "0.18.0")

    assert code == 2
    assert "its own copy of s0ma" in err
    assert "the project's own dependencies" in err
    assert not (project / ".s0ma-version").exists()
    assert keyed.requests == []


def test_unpin_refuses_there_too(
    run_cli: Any, project: Path, make_venv: Any
) -> None:
    make_venv(project / ".venv", windows=True)
    (project / ".s0ma-version").write_text("0.18.0\n", encoding="utf-8")

    code, _, err = run_cli("unpin")

    assert code == 2
    assert "its own copy of s0ma" in err
    assert (project / ".s0ma-version").is_file(), "nothing was touched"


# ---------------------------------------------------------------------------
# Manners.
# ---------------------------------------------------------------------------


def test_pinning_never_shows_a_key(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    code, out, err = run_cli("pin", "0.18.0")

    assert code == 0
    assert keyed.key not in out + err
    for line in keyed.requests:
        assert keyed.key not in line


def test_every_word_pin_says_can_be_printed_on_any_console(
    run_cli: Any, keyed: FakeControlPlane, launcher: ModuleType
) -> None:
    _, out, err = run_cli("pin", "0.18.0")
    _, out2, err2 = run_cli("unpin")

    for text in (out, err, out2, err2, launcher.OWN_TOOLCHAIN_MESSAGE):
        assert text.isascii(), f"not printable on a Windows console: {text!r}"
