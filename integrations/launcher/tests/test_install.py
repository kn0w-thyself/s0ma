"""Installing s0ma: the manifest, the files, the checks, and the four answers.

These tests do a **real** install - a real ``uv`` environment, real wheels, real
console scripts - against the fake control plane in ``fake_control_plane.py``,
with ``uv`` told to resolve nothing from any network. Nothing here, and nothing
anywhere else in this directory, ever contacts the real control plane or writes
to the real ``~/.s0ma``.

The fake license key is checked for in everything a run leaves behind: what it
printed, what it wrote down, and the addresses it asked for. A key belongs in
one place only - the ``Authorization`` header - and these tests are what says
so.
"""

from __future__ import annotations

import json
import subprocess
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
    """The test-only install flag is never inherited from the machine."""
    monkeypatch.delenv("S0MA_LAUNCH_OFFLINE_INSTALL", raising=False)


def state_of(home: Path) -> dict[str, Any]:
    """Read ``state.json`` the way anything else would."""
    return json.loads((home / "launcher" / "state.json").read_text(encoding="utf-8"))


def everything_written(home: Path) -> str:
    """Every byte the launcher has written under the state directory."""
    parts: list[str] = []
    for path in sorted(home.rglob("*")):
        if path.is_file() and path.suffix in ("", ".json", ".log", ".1"):
            try:
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:  # pragma: no cover - nothing here is unreadable
                continue
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# The whole thing, for real.
# ---------------------------------------------------------------------------


def test_install_really_installs_a_working_copy_of_s0ma(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path, launcher: ModuleType
) -> None:
    code, out, err = run_cli("install")

    assert code == 0, err
    assert out == ""
    toolchain = isolated_home / "toolchains" / "0.18.0"
    assert (toolchain / ".complete").is_file()
    program = launcher.find_program(toolchain / "bin", "s0ma-mcp") or launcher.find_program(
        toolchain / "Scripts", "s0ma-mcp"
    )
    assert program is not None, "the install left no s0ma-mcp behind"

    # The environment was built under one name and moved to another, so this is
    # also the proof that `uv venv --relocatable` did its job.
    finished = subprocess.run([str(program)], capture_output=True, text=True, check=False)
    assert finished.returncode == 0
    assert finished.stdout.strip() == "s0ma_mcp 0.18.0"

    assert "s0ma 0.18.0 is installed." in err
    state = state_of(isolated_home)
    assert state["installed"] == ["0.18.0"]
    assert state["current"] == "0.18.0"
    assert state["entitlement"] == "ok"
    assert state["last_error"] is None
    assert state["latest_seen"] == "0.18.0"


def test_after_installing_that_copy_is_what_runs_here(
    run_cli: Any, keyed: FakeControlPlane
) -> None:
    run_cli("install")

    _, out, _ = run_cli("status")

    assert "s0ma 0.18.0" in out
    assert "newest version installed" in out


def test_a_wheel_already_downloaded_is_used_again(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    run_cli("install")
    downloads = [one for one in keyed.requests if one.startswith("GET /dist/")]

    _, _, err = run_cli("install")

    assert "already here" in err
    assert [one for one in keyed.requests if one.startswith("GET /dist/")] == downloads
    assert len(list((isolated_home / "downloads").glob("*.whl"))) == 4


def test_a_named_version_is_the_one_installed(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    keyed.publish("0.19.0")

    code, _, err = run_cli("install", "--version", "0.18.0")

    assert code == 0, err
    assert (isolated_home / "toolchains" / "0.18.0" / ".complete").is_file()
    assert not (isolated_home / "toolchains" / "0.19.0").exists()
    assert state_of(isolated_home)["latest_seen"] == "0.19.0", (
        "asking for an older version on purpose does not hide the newest one"
    )


def test_half_built_toolchains_are_swept_and_never_used(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path, make_toolchain: Any
) -> None:
    interrupted = make_toolchain("0.16.0", complete=False)
    leftover = isolated_home / "toolchains" / "0.17.0.partial"
    leftover.mkdir(parents=True)
    (leftover / "marker").write_text("x", encoding="utf-8")

    code, _, err = run_cli("install")

    assert code == 0, err
    assert not interrupted.exists()
    assert not leftover.exists()
    assert "Cleared away 2 unfinished installs." in err


# ---------------------------------------------------------------------------
# What arrives is checked.
# ---------------------------------------------------------------------------


def test_a_file_that_does_not_match_its_checksum_stops_everything(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    keyed.wrong_sha = True

    code, _, err = run_cli("install")

    assert code == 6
    assert "s0ma_core-0.18.0-py3-none-any.whl" in err
    assert "Nothing has been installed" in err
    assert list((isolated_home / "downloads").glob("*")) == []
    assert not (isolated_home / "toolchains" / "0.18.0").exists()


def test_a_download_that_stops_part_way_is_not_installed(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    keyed.truncate = True

    code, _, err = run_cli("install")

    assert code == 6
    assert "cut short" in err
    assert list((isolated_home / "downloads").glob("*")) == []


def test_a_damaged_file_in_the_downloads_folder_is_fetched_again(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    downloads = isolated_home / "downloads"
    downloads.mkdir(parents=True)
    (downloads / "s0ma_core-0.18.0-py3-none-any.whl").write_bytes(b"not a wheel")

    code, _, err = run_cli("install")

    assert code == 0, err
    assert (isolated_home / "toolchains" / "0.18.0" / ".complete").is_file()


# ---------------------------------------------------------------------------
# The four answers the control plane can give (milestone task T4).
# ---------------------------------------------------------------------------


def test_a_key_the_control_plane_refuses_says_where_a_key_goes(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    keyed.invalid_key = True

    code, _, err = run_cli("install")

    assert code == 4
    assert "did not accept this license key" in err
    assert "plugin's settings" in err
    assert "s0ma-launch activate" in err
    assert "Never type a license key into a chat." in err
    assert state_of(isolated_home)["entitlement"] == "invalid_key"


def test_an_account_whose_access_has_ended_is_told_kindly(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    keyed.not_entitled = True

    code, _, err = run_cli("install")

    assert code == 4
    assert "access to new versions of s0ma has ended" in err
    assert "keeps working exactly as it is" in err
    assert keyed.host in err, "the account page is named"
    assert state_of(isolated_home)["entitlement"] == "not_entitled"


def test_a_busy_control_plane_is_not_a_subscription_problem(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    keyed.rate_limited = True

    code, _, err = run_cli("install")

    assert code == 5
    assert "busy" in err
    assert "try again in a little while" in err.lower()
    assert "about 30 seconds" in err
    assert state_of(isolated_home)["entitlement"] == "unknown", (
        "a busy server says nothing about the subscription"
    )


def test_a_control_plane_that_cannot_be_reached_says_what_still_works(
    run_cli: Any,
    control_plane: FakeControlPlane,
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
) -> None:
    host = control_plane.host
    control_plane.stop()
    monkeypatch.setenv("S0MA_CP_HOST", host)
    monkeypatch.setenv("S0MA_LICENSE_KEY", control_plane.key)

    code, _, err = run_cli("install")

    assert code == 5
    assert "could not reach its control plane" in err
    assert "keeps working" in err
    assert state_of(isolated_home)["entitlement"] == "unknown"


def test_a_control_plane_that_takes_too_long_gives_up_and_says_so(
    run_cli: Any,
    keyed: FakeControlPlane,
    launcher: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyed.slow_seconds = 3.0
    monkeypatch.setattr(launcher, "CP_TIMEOUT_SECONDS", 0.25)

    code, _, err = run_cli("install")

    assert code == 5
    assert "could not reach its control plane" in err
    assert "too long" in err


def test_the_control_plane_s_own_wording_is_shown_after_ours(
    run_cli: Any, keyed: FakeControlPlane
) -> None:
    keyed.not_entitled = True

    _, _, err = run_cli("install")

    lines = [line for line in err.splitlines() if line.strip()]
    assert lines[-1] == "This account's access has ended.", (
        "the control plane's own sentence comes last, and verbatim"
    )


def test_a_notice_on_a_good_answer_is_passed_on_word_for_word(
    run_cli: Any, keyed: FakeControlPlane
) -> None:
    keyed.notice = "s0ma 0.19.0 will need Python 3.12."

    code, _, err = run_cli("install")

    assert code == 0, err
    assert err.count("s0ma 0.19.0 will need Python 3.12.") == 1, "said once, verbatim"


def test_a_version_the_control_plane_does_not_have(
    run_cli: Any, keyed: FakeControlPlane
) -> None:
    code, _, err = run_cli("install", "--version", "9.9.9")

    assert code == 2
    assert "has no such version" in err


def test_something_that_is_not_a_version_is_refused_before_any_request(
    run_cli: Any, keyed: FakeControlPlane
) -> None:
    code, _, err = run_cli("install", "--version", "latest; rm -rf /")

    assert code == 2
    assert "does not look like a version" in err
    assert keyed.requests == []


def test_installing_without_a_key_says_where_to_put_one(
    run_cli: Any, control_plane: FakeControlPlane, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S0MA_CP_HOST", control_plane.host)

    code, _, err = run_cli("install")

    assert code == 4
    assert "there is no key on this machine" in err
    assert "plugin's settings" in err
    assert control_plane.requests == [], "nothing is asked without a key"


def test_installing_without_uv_says_how_to_get_it(
    run_cli: Any, keyed: FakeControlPlane, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "find_uv", lambda *args, **kwargs: None)

    code, _, err = run_cli("install")

    assert code == 7
    assert "uv" in err
    assert keyed.requests == [], "nothing is fetched that could not be installed"


def test_a_manifest_that_is_missing_a_package_stops_with_a_plain_sentence(
    run_cli: Any, keyed: FakeControlPlane
) -> None:
    keyed.versions["0.18.0"] = [
        wheel for wheel in keyed.versions["0.18.0"] if "s0ma_studi0" not in wheel.name
    ]

    code, _, err = run_cli("install")

    assert code == 5
    assert "s0ma_studi0" in err
    assert "could not use" in err


# ---------------------------------------------------------------------------
# Where the key does, and does not, go.
# ---------------------------------------------------------------------------


def test_the_key_travels_in_the_header_and_nowhere_else(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    code, out, err = run_cli("install")

    assert code == 0, err
    assert keyed.authorizations, "the launcher did make requests"
    assert all(header == "Bearer " + keyed.key for header in keyed.authorizations)
    for line in keyed.requests:
        assert keyed.key not in line, f"a key reached a URL: {line}"
    assert keyed.key not in out
    assert keyed.key not in err
    assert keyed.key not in everything_written(isolated_home)


def test_a_failing_install_never_writes_the_key_down(
    run_cli: Any, keyed: FakeControlPlane, isolated_home: Path
) -> None:
    keyed.not_entitled = True

    _, out, err = run_cli("install")

    assert keyed.key not in out + err
    assert keyed.key not in everything_written(isolated_home)


def test_uv_is_never_handed_the_key(
    run_cli: Any, keyed: FakeControlPlane, launcher: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[list[str], dict[str, str]]] = []
    real = subprocess.run

    def watching(command: Any, **kwargs: Any) -> Any:
        seen.append((list(command), dict(kwargs.get("env") or {})))
        return real(command, **kwargs)

    monkeypatch.setattr(launcher.subprocess, "run", watching)

    assert run_cli("install")[0] == 0
    assert seen, "uv was run"
    for command, env in seen:
        assert keyed.key not in " ".join(command)
        assert "S0MA_LICENSE_KEY" not in env
        assert keyed.key not in "".join(env.values())


# ---------------------------------------------------------------------------
# Which address the launcher is willing to call at all.
# ---------------------------------------------------------------------------


def test_a_plain_http_host_that_is_not_this_machine_is_refused(
    run_cli: Any, monkeypatch: pytest.MonkeyPatch, fake_key: str
) -> None:
    monkeypatch.setenv("S0MA_CP_HOST", "http://wheels.example.invalid")
    monkeypatch.setenv("S0MA_LICENSE_KEY", fake_key)

    code, _, err = run_cli("install")

    assert code == 2
    assert "plain, unencrypted connection" in err
    assert "https" in err


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("account.kn0wthyself.ai", "https://account.kn0wthyself.ai"),
        ("https://account.kn0wthyself.ai", "https://account.kn0wthyself.ai"),
        ("https://account.kn0wthyself.ai/", "https://account.kn0wthyself.ai"),
        ("http://127.0.0.1:8788", "http://127.0.0.1:8788"),
        ("http://localhost:8788", "http://localhost:8788"),
        ("http://[::1]:8788", "http://[::1]:8788"),
    ],
)
def test_the_address_a_host_setting_turns_into(
    launcher: ModuleType, host: str, expected: str
) -> None:
    assert launcher.cp_base_url(host) == expected


@pytest.mark.parametrize(
    "host", ["http://example.com", "ftp://example.com", "http://10.0.0.5:8788", ""]
)
def test_an_address_the_launcher_will_not_call(launcher: ModuleType, host: str) -> None:
    with pytest.raises(launcher.LauncherError) as refusal:
        launcher.cp_base_url(host)
    assert refusal.value.code == 2


def test_the_key_is_never_part_of_an_address(launcher: ModuleType, fake_key: str) -> None:
    manifest = launcher.manifest_url("https://account.kn0wthyself.ai", "0.18.0")
    wheels = launcher.wheel_url("https://account.kn0wthyself.ai", "dist/0.18.0/a.whl")
    check = launcher.key_check_url("https://account.kn0wthyself.ai")

    for address in (manifest, wheels, check):
        assert fake_key not in address
        assert "Bearer" not in address
    assert manifest.endswith("/api/dist/manifest?version=0.18.0")
    assert wheels.endswith("/dist/0.18.0/a.whl")
    assert check.endswith("/api/key/check")


# ---------------------------------------------------------------------------
# Reading a manifest: everything in it arrived over a network.
# ---------------------------------------------------------------------------


def _manifest(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "version": "0.18.0",
        "wheels": [
            {
                "name": "s0ma_core-0.18.0-py3-none-any.whl",
                "path": "dist/0.18.0/s0ma_core-0.18.0-py3-none-any.whl",
                "sha256": "a" * 64,
                "size": 10,
            }
        ],
    }
    body.update(changes)
    return body


def test_a_manifest_is_read_when_it_is_well_formed(launcher: ModuleType) -> None:
    manifest = launcher.parse_manifest(_manifest())

    assert manifest.version == "0.18.0"
    assert manifest.wheels[0].sha256 == "a" * 64
    assert manifest.named("s0ma_core") is not None
    assert manifest.named("s0ma_dsl") is None


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (_manifest(version=None), "names no version"),
        (_manifest(wheels=[]), "lists no files"),
        (_manifest(wheels=["a wheel"]), "not an object"),
        (
            _manifest(wheels=[{"name": "../../etc/passwd", "path": "a", "sha256": "a" * 64}]),
            "no usable filename",
        ),
        (
            _manifest(
                wheels=[
                    {
                        "name": "s0ma_core-0.18.0-py3-none-any.whl",
                        "path": "dist/../../secret",
                        "sha256": "a" * 64,
                    }
                ]
            ),
            "is not usable",
        ),
        (
            _manifest(
                wheels=[
                    {
                        "name": "s0ma_core-0.18.0-py3-none-any.whl",
                        "path": "dist/0.18.0/s0ma_core-0.18.0-py3-none-any.whl",
                        "sha256": "",
                    }
                ]
            ),
            "carries no checksum",
        ),
    ],
)
def test_a_manifest_that_cannot_be_trusted_is_refused(
    launcher: ModuleType, body: dict[str, Any], detail: str
) -> None:
    with pytest.raises(launcher.ControlPlaneError) as refusal:
        launcher.parse_manifest(body)

    assert refusal.value.code == 5
    assert detail in refusal.value.message


def test_a_version_named_only_as_latest_is_still_read(launcher: ModuleType) -> None:
    body = _manifest()
    del body["version"]
    body["latest"] = "0.18.0"

    assert launcher.parse_manifest(body).version == "0.18.0"


# ---------------------------------------------------------------------------
# Anything the control plane says is made safe before it is printed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("Check your account.", "Check your account."),
        ("two\nlines", "two lines"),
        ("\x1b[2Jcleared the screen", "[2Jcleared the screen"),
        ("   ", None),
        (None, None),
        (17, None),
    ],
)
def test_wording_from_the_network_is_made_plain(
    launcher: ModuleType, given: Any, expected: str | None
) -> None:
    assert launcher.plain_sentence(given) == expected


def test_a_very_long_notice_is_shortened(launcher: ModuleType) -> None:
    made = launcher.plain_sentence("x" * 1000)

    assert made is not None
    assert len(made) <= 303
    assert made.endswith("...")
