"""FB-M4: the context allow-list, local state, and the no-network boundary.

Three rules are held here as executable facts:

* contract §5 — nothing outside the allow-list can enter a context;
* contract §8 — ``~/.s0ma`` is HOME-based, owner-only where the platform
  can express that, and never raises because a mode was refused;
* the milestone boundary — the feedback engine opens no sockets outside
  ``client.py``, the one module FB-M6 gave a transport, and importing the
  package opens none at all.

Every test in this module runs against an isolated HOME (``isolated_home``
is autouse), so no test can read or write the developer's real
``~/.s0ma``.
"""

from __future__ import annotations

import ast
import importlib
import os
import re
import socket
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.feedback import context as context_module
from s0ma_dsl.feedback import state as state_module
from s0ma_dsl.feedback.context import (
    COHORT,
    DISTRIBUTIONS,
    DURATION_BUCKETS,
    OUTCOMES,
    ClientInfo,
    ContextAllowListError,
    SurfaceInfo,
    architecture,
    build_context,
    distribution_versions,
    duration_bucket,
    enforce_allow_list,
    os_family,
    python_series,
)
from s0ma_dsl.feedback.model import (
    CONTEXT_ALLOWED_KEYS,
    CONTEXT_MAX_BYTES,
    canonical_bytes,
    validate_payload,
)
from s0ma_dsl.feedback.state import (
    INSTALLATION_ID_FILENAME,
    STATE_DIR_NAME,
    installation_id,
    read_installation_id,
    rotate_installation_id,
    state_dir,
    write_private_text,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

PSEUDONYM_RE = re.compile(r"\A[0-9a-f]{32}\Z")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME (and ``%USERPROFILE%``) at a throwaway directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


# ---------------------------------------------------------------------------
# Contract §5 — the allow-list is enforced by rejection
# ---------------------------------------------------------------------------


def test_allow_list_matches_the_contract() -> None:
    assert sorted(CONTEXT_ALLOWED_KEYS) == [
        "architecture",
        "client",
        "cohort",
        "diagnostic_codes",
        "duration_bucket",
        "mcp_protocol_version",
        "os",
        "outcome",
        "pseudonym",
        "python",
        "s0ma_core",
        "s0ma_dsl",
        "s0ma_mcp",
        "s0ma_studi0",
        "s0ma_version",
        "surface",
    ]


@pytest.mark.parametrize(
    "forbidden",
    [
        "git_remote",
        "repository",
        "organization",
        "email",
        "license_key",
        "source",
        "transcript",
        "stack_trace",
        "hostname",
        "mac_address",
        "cwd",
    ],
)
def test_enforce_allow_list_rejects_anything_else(forbidden: str) -> None:
    with pytest.raises(ContextAllowListError) as caught:
        enforce_allow_list({"os": "linux", forbidden: "whatever it held"})
    assert forbidden in str(caught.value)


def test_enforce_allow_list_returns_a_key_sorted_copy() -> None:
    original = {"python": "3.13", "cohort": "beta", "os": "linux"}
    checked = enforce_allow_list(original)
    assert list(checked) == ["cohort", "os", "python"]
    assert checked is not original


def test_build_context_has_no_route_for_an_arbitrary_key() -> None:
    """The collector takes typed keywords only — no map is copied through."""
    with pytest.raises(TypeError):
        build_context(git_remote="git@example.com:me/private.git")  # type: ignore[call-arg]


def test_built_context_only_ever_carries_allow_listed_keys() -> None:
    built = build_context(
        channel="mcp",
        client=ClientInfo(name="claude-code", version="1.2.3"),
        surface=SurfaceInfo(kind="tool", name="check"),
        diagnostic_codes=["PROVIDES_KEY_MISMATCH", "NOT_EXPORTED"],
        outcome="failure",
        duration_seconds=7.5,
        mcp_protocol_version="2025-06-18",
    )
    assert set(built) <= CONTEXT_ALLOWED_KEYS
    assert set(built["client"]) == {"name", "version"}
    assert set(built["surface"]) == {"kind", "name"}


def test_built_context_passes_envelope_validation() -> None:
    built = build_context(surface=SurfaceInfo(kind="tool", name="check"))
    payload = {
        "schema": "s0ma-feedback@1",
        "category": "friction",
        "impact": "minor",
        "summary": "the collector output must satisfy the schema validator",
        "context": built,
    }
    assert validate_payload(payload) == ()
    assert len(canonical_bytes(built)) <= CONTEXT_MAX_BYTES


def test_minimal_context_is_the_documented_always_present_set() -> None:
    built = build_context(include_pseudonym=False)
    assert set(built) == {
        "s0ma_version",
        "s0ma_core",
        "s0ma_dsl",
        "s0ma_mcp",
        "s0ma_studi0",
        "python",
        "os",
        "architecture",
        "cohort",
    }
    assert built["cohort"] == COHORT == "beta"


def test_optional_details_are_absent_unless_supplied() -> None:
    built = build_context(include_pseudonym=False)
    for key in ("client", "surface", "diagnostic_codes", "outcome", "duration_bucket"):
        assert key not in built


# ---------------------------------------------------------------------------
# Contract §5 — the individual collected facts
# ---------------------------------------------------------------------------


def test_distribution_versions_cover_all_four_distributions() -> None:
    versions = distribution_versions()
    assert set(versions) == {"s0ma_core", "s0ma_dsl", "s0ma_mcp", "s0ma_studi0"}
    assert [name for _, name in DISTRIBUTIONS] == [
        "s0ma-core",
        "s0ma-dsl",
        "s0ma-mcp",
        "s0ma-studi0",
    ]


def test_absent_distribution_reports_none_rather_than_dropping_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _absent(name: str) -> str:
        raise context_module.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(context_module.metadata, "version", _absent)
    assert distribution_versions() == {
        "s0ma_core": None,
        "s0ma_dsl": None,
        "s0ma_mcp": None,
        "s0ma_studi0": None,
    }
    built = build_context(include_pseudonym=False)
    assert built["s0ma_mcp"] is None
    assert built["s0ma_version"] is None


def test_python_is_major_minor_only() -> None:
    series = python_series()
    assert re.fullmatch(r"\d+\.\d+", series)
    assert series == f"{sys.version_info.major}.{sys.version_info.minor}"


@pytest.mark.parametrize(
    ("system", "family"),
    [
        ("Darwin", "macos"),
        ("Linux", "linux"),
        ("Windows", "windows"),
        ("FreeBSD", "other"),
        ("", "other"),
    ],
)
def test_os_family_is_a_closed_vocabulary(
    monkeypatch: pytest.MonkeyPatch, system: str, family: str
) -> None:
    monkeypatch.setattr(context_module.platform, "system", lambda: system)
    assert os_family() == family


def test_architecture_is_lower_case_and_never_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(context_module.platform, "machine", lambda: "ARM64")
    assert architecture() == "arm64"
    monkeypatch.setattr(context_module.platform, "machine", lambda: "")
    assert architecture() == "unknown"


@pytest.mark.parametrize(
    ("seconds", "bucket"),
    [
        (0.0, "<1s"),
        (0.999, "<1s"),
        (1.0, "1-5s"),
        (4.999, "1-5s"),
        (5.0, "5-30s"),
        (29.9, "5-30s"),
        (30.0, "30s-2m"),
        (119.9, "30s-2m"),
        (120.0, ">2m"),
        (86400.0, ">2m"),
    ],
)
def test_duration_bucket_table(seconds: float, bucket: str) -> None:
    assert duration_bucket(seconds) == bucket
    assert bucket in DURATION_BUCKETS


def test_duration_bucket_refuses_a_negative_duration() -> None:
    with pytest.raises(ValueError, match="negative"):
        duration_bucket(-1.0)


def test_outcome_must_come_from_the_contract_vocabulary() -> None:
    assert OUTCOMES == ("success", "failure")
    assert build_context(outcome="success", include_pseudonym=False)["outcome"] == "success"
    with pytest.raises(ValueError, match="outcome"):
        build_context(outcome="crashed", include_pseudonym=False)


def test_diagnostic_codes_must_be_a_list_not_one_string() -> None:
    with pytest.raises(TypeError):
        build_context(diagnostic_codes="PROVIDES_KEY_MISMATCH", include_pseudonym=False)


def test_mcp_protocol_version_belongs_to_the_mcp_channel_only() -> None:
    built = build_context(
        channel="mcp", mcp_protocol_version="2025-06-18", include_pseudonym=False
    )
    assert built["mcp_protocol_version"] == "2025-06-18"
    with pytest.raises(ValueError, match="mcp channel"):
        build_context(channel="cli", mcp_protocol_version="2025-06-18")
    assert "mcp_protocol_version" not in build_context(include_pseudonym=False)


def test_unknown_channel_is_refused() -> None:
    with pytest.raises(ValueError, match="channel"):
        build_context(channel="carrier-pigeon")


# ---------------------------------------------------------------------------
# Contract §5/§8 — the pseudonym
# ---------------------------------------------------------------------------


def test_context_pseudonym_is_the_installation_id() -> None:
    built = build_context()
    assert built["pseudonym"] == installation_id()
    assert PSEUDONYM_RE.match(built["pseudonym"])


def test_pseudonym_can_be_left_out() -> None:
    assert "pseudonym" not in build_context(include_pseudonym=False)


def test_unwritable_state_never_blocks_a_report(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(home: Path | None = None) -> str:
        raise PermissionError("read-only home")

    monkeypatch.setattr(context_module, "installation_id", _refuse)
    built = build_context()
    assert "pseudonym" not in built
    assert built["cohort"] == COHORT


# ---------------------------------------------------------------------------
# Contract §8 — local state
# ---------------------------------------------------------------------------


def test_state_dir_is_home_based(isolated_home: Path) -> None:
    assert state_dir() == isolated_home / STATE_DIR_NAME
    assert state_dir() == Path.home() / ".s0ma"


def test_explicit_home_wins_over_the_environment(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    assert state_dir(elsewhere) == elsewhere / STATE_DIR_NAME
    value = installation_id(elsewhere)
    assert PSEUDONYM_RE.match(value)
    assert (elsewhere / STATE_DIR_NAME / INSTALLATION_ID_FILENAME).exists()


def test_state_is_never_touched_until_it_is_needed(isolated_home: Path) -> None:
    assert not state_dir().exists()
    assert read_installation_id() is None
    assert not state_dir().exists()


def test_installation_id_is_created_on_first_use_and_then_stable(
    isolated_home: Path,
) -> None:
    first = installation_id()
    assert PSEUDONYM_RE.match(first)
    stored = (state_dir() / INSTALLATION_ID_FILENAME).read_text(encoding="utf-8")
    assert stored.strip() == first
    assert installation_id() == first
    assert read_installation_id() == first


def test_rotation_is_delete_and_regenerate(isolated_home: Path) -> None:
    first = installation_id()
    second = rotate_installation_id()
    assert second != first
    assert PSEUDONYM_RE.match(second)
    assert read_installation_id() == second


def test_deleting_the_file_rotates_the_pseudonym(isolated_home: Path) -> None:
    first = installation_id()
    (state_dir() / INSTALLATION_ID_FILENAME).unlink()
    assert read_installation_id() is None
    assert installation_id() != first


def test_a_hand_written_pseudonym_is_never_transmitted(isolated_home: Path) -> None:
    """A corrupt id reads as absent, so nothing hand-typed can ride along."""
    directory = state_dir()
    directory.mkdir(parents=True)
    path = directory / INSTALLATION_ID_FILENAME
    path.write_text("someone@example.com\n", encoding="utf-8")
    assert read_installation_id() is None
    fresh = installation_id()
    assert PSEUDONYM_RE.match(fresh)
    assert "example.com" not in path.read_text(encoding="utf-8")
    assert build_context()["pseudonym"] == fresh


def test_state_files_are_utf8_with_lf_endings(isolated_home: Path) -> None:
    path = state_dir() / "sample.json"
    write_private_text(path, '{"note": "naïve — em dash"}\nsecond line\n')
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    assert raw.decode("utf-8").startswith('{"note": "naïve')


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes; Windows uses ACLs")
def test_state_permissions_are_owner_only_on_posix(isolated_home: Path) -> None:
    installation_id()
    directory = state_dir()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    path = directory / INSTALLATION_ID_FILENAME
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes; Windows uses ACLs")
def test_rewritten_state_file_keeps_owner_only_permissions(isolated_home: Path) -> None:
    path = state_dir() / "token"
    write_private_text(path, "first\n")
    os.chmod(path, 0o644)
    write_private_text(path, "second\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "posix", reason="the Windows best-effort fallback")
def test_windows_permission_fallback_is_a_working_no_op(isolated_home: Path) -> None:
    """Off POSIX the mode is not applied, and nothing about that fails."""
    value = installation_id()
    assert PSEUDONYM_RE.match(value)
    assert (state_dir() / INSTALLATION_ID_FILENAME).exists()
    assert read_installation_id() == value


def test_a_refused_chmod_never_stops_the_feedback_function(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    def _refuse(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("this filesystem does not do modes")

    monkeypatch.setattr(state_module.os, "chmod", _refuse)
    value = installation_id()
    assert PSEUDONYM_RE.match(value)
    assert read_installation_id() == value


def test_a_concurrent_writer_wins_and_both_agree(isolated_home: Path) -> None:
    """Losing the create race adopts the winner's id rather than clobbering it.

    Calls the minting step directly: that is the only way to reach the
    exclusive-create collision, since :func:`installation_id` reads first.
    """
    directory = state_dir()
    directory.mkdir(parents=True)
    other = "a" * 32
    (directory / INSTALLATION_ID_FILENAME).write_text(f"{other}\n", encoding="utf-8")
    assert state_module._mint_installation_id() == other
    assert read_installation_id() == other


# ---------------------------------------------------------------------------
# Milestone boundary — zero network in this package
# ---------------------------------------------------------------------------

FEEDBACK_DIR = Path(context_module.__file__).parent

#: Import roots that would put a socket under the feedback engine.
FORBIDDEN_IMPORT_ROOTS = frozenset({
    "socket",
    "urllib",
    "http",
    "ssl",
    "ftplib",
    "smtplib",
    "xmlrpc",
    "requests",
    "httpx",
})

#: The one module allowed to carry a socket (FB-M6). ``urllib.request`` is
#: its documented transport, and it opens a connection only when one of its
#: functions is called — importing the package still touches no network,
#: which ``test_the_package_imports_and_works_with_sockets_disabled`` below
#: and ``test_feedback_client.py`` both hold.
TRANSPORT_MODULES = frozenset({"client.py"})


def _module_sources() -> Iterator[tuple[Path, str]]:
    for path in sorted(FEEDBACK_DIR.glob("*.py")):
        yield path, path.read_text(encoding="utf-8")


def test_the_package_has_the_modules_this_milestone_owns() -> None:
    present = {path.name for path, _ in _module_sources()}
    assert {"__init__.py", "model.py", "context.py", "state.py"} <= present


def test_no_module_imports_anything_network_shaped() -> None:
    offenders: list[str] = []
    for path, source in _module_sources():
        if path.name in TRANSPORT_MODULES:
            continue
        for node in ast.walk(ast.parse(source, filename=str(path))):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = [node.module.split(".")[0]]
            offenders.extend(
                f"{path.name}: {root}"
                for root in roots
                if root in FORBIDDEN_IMPORT_ROOTS
            )
    assert offenders == []


def test_the_package_imports_and_works_with_sockets_disabled(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """Import and run the whole compose path with socket creation poisoned."""

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the feedback engine must not open a socket")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)

    saved = {
        name: module
        for name, module in sys.modules.items()
        if name == "s0ma_dsl.feedback" or name.startswith("s0ma_dsl.feedback.")
    }
    for name in saved:
        del sys.modules[name]
    try:
        feedback = importlib.import_module("s0ma_dsl.feedback")
        built = feedback.build_context(surface=feedback.SurfaceInfo("tool", "check"))
        result = feedback.build_envelope(
            category="bug",
            impact="degraded",
            summary="composed with no network available",
            context=built,
            privacy=feedback.FeedbackPrivacy(),
        )
        assert result.ok is True
        assert result.envelope is not None
        assert result.envelope.payload_sha256().startswith("sha256:")
        assert feedback.installation_id() == built["pseudonym"]
    finally:
        for name in [
            name
            for name in sys.modules
            if name == "s0ma_dsl.feedback" or name.startswith("s0ma_dsl.feedback.")
        ]:
            del sys.modules[name]
        sys.modules.update(saved)
        s0ma_dsl = importlib.import_module("s0ma_dsl")
        s0ma_dsl.feedback = saved["s0ma_dsl.feedback"]  # type: ignore[attr-defined]
