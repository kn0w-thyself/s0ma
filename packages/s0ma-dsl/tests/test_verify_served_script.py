"""Tests for ``scripts/verify_served.sh`` — the served-release verifier (RP-M3).

The script answers one question the release pipeline could never answer
before: *does the control plane actually serve the release we just cut?* It
fetches the entitlement-gated manifest with a real tester key, downloads every
wheel it names and hashes the bytes, and diffs the publicly served installer
against the canonical ``scripts/install.sh``.

These tests are **network-free by construction**: every run points
``--cp-host`` at a threaded ``http.server`` on 127.0.0.1 that impersonates the
control plane (the HOST-H4 manifest shape, the D-5 error shape, the gated
``/dist/`` objects, and the public ``/install.sh``). No test ever contacts
``account.kn0wthyself.ai`` or any other host — the proxy environment is
scrubbed so curl cannot be diverted to one either.

Each test drives one failure class, because the script's whole contract is
that its exit code tells the caller WHICH thing is wrong: the release
workflow downgrades installer drift (exit 2) to a notice, since control-plane
deploys are manual (hardening plan R10/R11), while every other class is red.

Idioms follow ``test_install_script.py``: the script is located relative to
this file, and every test skips gracefully when ``bash`` or ``curl`` is
unavailable, so the gate stays green on a host without them.

One deliberate narrowing: the fixture-server tests skip on Windows. Unlike
the installer tests (which only ever drive ``--dry-run``), these actually
execute ``curl`` from ``bash``, and Git-Bash hands a native curl.exe MSYS
paths — including the ``-H @<header-file>`` argument that keeps the key off
argv. The script is Linux/macOS tooling (the release workflow runs it on
ubuntu-latest, the owner runs it locally), so rather than assert an
unverifiable path-translation behavior, Windows runs the static checks only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
VERIFY_SH = REPO_ROOT / "scripts" / "verify_served.sh"
CANON_INSTALLER = REPO_ROOT / "scripts" / "install.sh"

#: The four distributions the manifest must carry (the H4 contract). Pinned
#: here so a stem quietly dropped from — or added to — the script fails.
WHEEL_STEMS = ("s0ma_core", "s0ma_dsl", "s0ma_mcp", "s0ma_studi0")

#: A deliberately fictional release version: no real s0ma release can ever
#: collide with it, so nothing in these tests reads as a version claim.
VERSION = "1.2.3"

#: A throwaway key for the fixture control plane. It must NEVER appear in the
#: script's output — the key is redacted as ``Bearer ***`` everywhere.
TEST_KEY = "s0ma_test_FIXTURESECRETVALUE"

#: Exit classes, mirrored from the script's header table. The release
#: workflow routes on these numbers, so they are part of the contract.
EXIT_OK = 0
EXIT_REFUSAL = 1
EXIT_DRIFT = 2
EXIT_MANIFEST = 3
EXIT_LATEST = 4
EXIT_WHEEL_LIST = 5
EXIT_WHEEL_BYTES = 6
EXIT_INSTALLER_FETCH = 7

#: The exact operator-facing sentence the drift class must print (the CI job
#: quotes it in its ``::notice``).
DRIFT_MESSAGE = "CP deploy pending — served installer differs from canon"

#: The trailing comment block the SERVED installer copy carries and the
#: canonical one does not (kts-website-3 ``public/install.sh``). Reproduced in
#: the same shape — blank separator line, banner, ``# DRIFT NOTE`` — because
#: tolerating exactly this block, and nothing else, is what the diff check
#: promises.
DRIFT_NOTE = (
    "\n"
    "# ===========================================================================\n"
    "# DRIFT NOTE (hosting & entitlement plan, HOST-H8) — DO NOT remove.\n"
    "#\n"
    "# This file is the PUBLICLY SERVED copy of the s0ma installer. It is a\n"
    "# faithful byte-for-byte copy of the canonical source in the S0 repo:\n"
    "#\n"
    "#     s0ma-new/scripts/install.sh\n"
    "# ===========================================================================\n"
)

_BASH = shutil.which("bash")
_CURL = shutil.which("curl")


def _require_bash() -> str:
    """For the static checks (existence, ``bash -n``) — no execution."""
    if _BASH is None:
        pytest.skip("bash unavailable")
    return _BASH


def _require_tools() -> str:
    """For the tests that actually run the script against the fixture host."""
    bash = _require_bash()
    if _CURL is None:
        pytest.skip("curl unavailable")
    if sys.platform.startswith("win"):
        pytest.skip(
            "the fixture-server tests need bash to drive curl with POSIX paths; "
            "Git-Bash hands a native curl.exe translated paths (see the module "
            "docstring). verify_served.sh is Linux/macOS release tooling."
        )
    return bash


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# The fixture control plane.
# ---------------------------------------------------------------------------


@dataclass
class ServedState:
    """Exactly what the fixture control plane serves. Tests mutate it."""

    #: The version ``?version=latest`` resolves to (the manifest's `latest`).
    latest: str = VERSION
    #: The manifest's ``wheels`` array, in the H4 shape.
    entries: list[dict[str, object]] = field(default_factory=list)
    #: Gated object bytes, keyed by the manifest path (``dist/<ver>/<name>``).
    objects: dict[str, bytes] = field(default_factory=dict)
    #: The public ``/install.sh`` body; ``None`` serves a 404.
    installer: bytes | None = None
    #: The only key the fixture accepts as ``Authorization: Bearer <key>``.
    key: str = TEST_KEY


class _Handler(BaseHTTPRequestHandler):
    """A control plane just real enough: H4 manifest, D-5 errors, gated dist."""

    protocol_version = "HTTP/1.1"

    # Silence the per-request stderr logging; pytest output stays readable.
    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A002
        return

    @property
    def _state(self) -> ServedState:
        return self.server.state  # type: ignore[attr-defined]

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self._state.key}"

    def _deny(self) -> None:
        # The D-5 structured-error shape the installer and this script parse.
        self._send_json(
            401,
            {
                "ok": False,
                "code": "INVALID_KEY",
                "remediation": "Check the key you were given, or ask for a new one.",
            },
        )

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
        path = self.path.split("?", 1)[0]
        state = self._state

        if path == "/install.sh":
            if state.installer is None:
                self._send_json(
                    404,
                    {"ok": False, "code": "NOT_FOUND", "remediation": "Deploy the site."},
                )
                return
            self._send(200, state.installer, "text/x-shellscript")
            return

        if not self._authorized():
            self._deny()
            return

        if path == "/api/dist/manifest":
            self._send_json(
                200, {"ok": True, "version": state.latest, "wheels": state.entries}
            )
            return

        key = path.lstrip("/")
        if key in state.objects:
            self._send(200, state.objects[key], "application/octet-stream")
            return

        self._send_json(
            404,
            {"ok": False, "code": "NOT_FOUND", "remediation": "Check the version."},
        )


@dataclass
class FixtureCP:
    """A running fixture control plane plus the local wheel directory."""

    base: str
    state: ServedState
    dist_dir: Path

    def drop_wheel(self, stem: str) -> None:
        """Remove one distribution from the manifest AND from the objects."""
        keep: list[dict[str, object]] = []
        for entry in self.state.entries:
            if str(entry["name"]).startswith(f"{stem}-"):
                self.state.objects.pop(str(entry["path"]), None)
            else:
                keep.append(entry)
        self.state.entries = keep

    def path_for(self, stem: str) -> str:
        for entry in self.state.entries:
            if str(entry["name"]).startswith(f"{stem}-"):
                return str(entry["path"])
        raise AssertionError(f"no manifest entry for {stem}")


def _wheel_bytes(stem: str) -> bytes:
    """Deterministic stand-in bytes for a built wheel."""
    return f"fixture wheel {stem} {VERSION}\n".encode()


@pytest.fixture
def cp(tmp_path: Path) -> Iterator[FixtureCP]:
    """A green control plane: four matching wheels + the served installer."""
    _require_tools()

    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    state = ServedState()
    for stem in WHEEL_STEMS:
        name = f"{stem}-{VERSION}-py3-none-any.whl"
        data = _wheel_bytes(stem)
        path = f"dist/{VERSION}/{name}"
        state.objects[path] = data
        state.entries.append(
            {
                "name": name,
                "path": path,
                "sha256": _sha256(data),
                "size": len(data),
            }
        )
        # The locally built wheel the script compares the served bytes with.
        (dist_dir / name).write_bytes(data)

    # The served installer = canonical + the trailing DRIFT NOTE block.
    canon = CANON_INSTALLER.read_bytes()
    state.installer = canon + DRIFT_NOTE.encode("utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    try:
        yield FixtureCP(base=f"http://{host}:{port}", state=state, dist_dir=dist_dir)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _run(
    cp: FixtureCP,
    *extra: str,
    version: str = VERSION,
    key: str | None = TEST_KEY,
    dist_dir: Path | str | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the verifier against the fixture control plane."""
    bash = _require_tools()
    cmd = [bash, str(VERIFY_SH), "--version", version, "--cp-host", cp.base]
    if dist_dir is not None:
        cmd += ["--dist-dir", str(dist_dir)]
    cmd += list(extra)

    env = {
        k: v
        for k, v in os.environ.items()
        if k.lower() not in {"http_proxy", "https_proxy", "all_proxy", "s0ma_smoke_key"}
    }
    # Belt and braces: no proxy may intercept the loopback requests.
    env["no_proxy"] = "*"
    env["NO_PROXY"] = "*"
    if key is not None:
        env["S0MA_SMOKE_KEY"] = key

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(cwd) if cwd is not None else str(REPO_ROOT),
        timeout=180,
    )


def _run_bare(
    *args: str, key: str | None = TEST_KEY
) -> subprocess.CompletedProcess[str]:
    """Run the verifier for a refusal that happens BEFORE any request.

    Argument validation and the key check both precede every network call
    (and the curl/python3 tool checks), so these cases need nothing but a
    shell — they run on every platform, unlike the fixture-server tests."""
    bash = _require_bash()
    env = {
        k: v for k, v in os.environ.items() if k.lower() != "s0ma_smoke_key"
    }
    if key is not None:
        env["S0MA_SMOKE_KEY"] = key
    return subprocess.run(
        [bash, str(VERIFY_SH), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )


def _combined(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Shape of the script itself.
# ---------------------------------------------------------------------------


def test_verify_script_exists_and_is_executable() -> None:
    assert VERIFY_SH.is_file(), f"missing verifier at {VERIFY_SH}"
    assert os.access(VERIFY_SH, os.X_OK), "verify_served.sh should be executable"


def test_verify_script_parses_clean() -> None:
    """``bash -n scripts/verify_served.sh`` parses without error."""
    bash = _require_bash()
    result = subprocess.run(
        [bash, "-n", str(VERIFY_SH)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"bash -n reported a parse error:\n{result.stderr}"
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# The green path.
# ---------------------------------------------------------------------------


def test_green_path_verifies_everything(cp: FixtureCP) -> None:
    """A correctly served release: manifest, four wheels, installer — exit 0."""
    result = _run(cp, dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_OK, out

    assert f"`latest` resolves to {VERSION}" in out
    assert "the manifest lists exactly 4 wheels" in out
    for stem in WHEEL_STEMS:
        assert f"{stem}-{VERSION}-py3-none-any.whl downloaded and matches" in out
        assert f"{stem}-{VERSION}-py3-none-any.whl is byte-identical" in out
    # The served installer differs from canon only by the DRIFT NOTE block.
    assert "the served installer matches scripts/install.sh" in out
    assert DRIFT_MESSAGE not in out

    # Structured summary + a single final verdict line.
    assert "  FAIL: 0\n" in out
    verdicts = [line for line in out.splitlines() if line.startswith("VERDICT:")]
    assert len(verdicts) == 1, verdicts
    assert verdicts[0].startswith("VERDICT: PASS")


def test_green_path_without_local_wheels_still_passes(
    cp: FixtureCP, tmp_path: Path
) -> None:
    """The local comparison is skipped — never silently counted as a pass."""
    empty = tmp_path / "no-such-dist"
    result = _run(cp, dist_dir=empty)
    out = _combined(result)
    assert result.returncode == EXIT_OK, out
    assert "does not exist" in out
    assert "no local copy" in out
    assert "is byte-identical" not in out


def test_served_installer_without_a_drift_note_is_accepted(cp: FixtureCP) -> None:
    """A served copy carrying no trailing note at all is compared whole.

    The note is a CP-side convenience, not part of the contract; dropping it
    must not be reported as drift (nor must the trim eat the final line)."""
    cp.state.installer = CANON_INSTALLER.read_bytes()
    result = _run(cp, dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_OK, out
    assert "the served installer matches scripts/install.sh" in out


# ---------------------------------------------------------------------------
# One test per failure class.
# ---------------------------------------------------------------------------


def test_wrong_latest_is_its_own_class(cp: FixtureCP) -> None:
    """Prod serving an older release than the tag → exit 4, naming both."""
    cp.state.latest = "1.2.2"
    result = _run(cp, dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_LATEST, out
    assert "latest=1.2.2" in out
    assert VERSION in out
    assert "VERDICT: FAILED (exit 4)" in out


def test_missing_fourth_wheel_is_its_own_class(cp: FixtureCP) -> None:
    """A three-wheel manifest → exit 5, naming the missing distribution."""
    cp.drop_wheel("s0ma_studi0")
    result = _run(cp, dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_WHEEL_LIST, out
    assert "lists 3 wheels, expected 4" in out
    assert "names no wheel for s0ma_studi0" in out
    assert "VERDICT: FAILED (exit 5)" in out


def test_served_bytes_not_matching_the_manifest_sha_is_its_own_class(
    cp: FixtureCP,
) -> None:
    """Served wheel bytes ≠ the manifest's sha256 → exit 6.

    This is the failure every keyed install would hit: the installer verifies
    the manifest hash and aborts, so the release is unusable."""
    path = cp.path_for("s0ma_mcp")
    cp.state.objects[path] = b"tampered wheel bytes\n"
    result = _run(cp, dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_WHEEL_BYTES, out
    assert "does NOT match the manifest sha256" in out
    assert "VERDICT: FAILED (exit 6)" in out


def test_local_dist_mismatch_is_reported(cp: FixtureCP) -> None:
    """Served bytes that are self-consistent but differ from the local build.

    The manifest and the served object agree, so an install would succeed —
    with different bytes than this checkout produced. That is still red."""
    path = cp.path_for("s0ma_dsl")
    replacement = b"a different but self-consistent wheel\n"
    cp.state.objects[path] = replacement
    for entry in cp.state.entries:
        if entry["path"] == path:
            entry["sha256"] = _sha256(replacement)

    result = _run(cp, dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_WHEEL_BYTES, out
    assert "differs from the wheel built here" in out
    # The manifest-side check passed; only the local comparison failed.
    assert "does NOT match the manifest sha256" not in out


def test_installer_drift_is_the_non_fatal_class(cp: FixtureCP) -> None:
    """A stale served installer → exit 2 with the CP-deploy-pending message.

    Everything else verified, so the release itself is good; the workflow
    turns this class into a notice because CP deploys are manual (R10/R11)."""
    stale = CANON_INSTALLER.read_text(encoding="utf-8").replace(
        'CP_HOST_DEFAULT="account.kn0wthyself.ai"',
        'CP_HOST_DEFAULT="stale.example.invalid"',
    )
    assert "stale.example.invalid" in stale, "the canonical default host moved"
    cp.state.installer = stale.encode("utf-8") + DRIFT_NOTE.encode("utf-8")

    result = _run(cp, dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_DRIFT, out
    assert DRIFT_MESSAGE in out
    # The release itself verified — the drift is the only finding.
    assert "  FAIL: 0\n" in out
    assert "VERDICT: CP DEPLOY PENDING (exit 2)" in out
    # The operator gets the actual difference, not just a verdict.
    assert "stale.example.invalid" in out


def test_a_real_failure_outranks_installer_drift(cp: FixtureCP) -> None:
    """Drift never masks a broken release: the fatal class wins the exit code."""
    cp.state.latest = "1.2.2"
    cp.state.installer = b"#!/usr/bin/env sh\necho not the installer\n"
    result = _run(cp, dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_LATEST, out
    assert DRIFT_MESSAGE in out  # still reported...
    assert "VERDICT: FAILED (exit 4)" in out  # ...but not the verdict


def test_unfetchable_installer_is_not_drift(cp: FixtureCP) -> None:
    """A 404 on /install.sh is a broken install path, not a pending deploy."""
    cp.state.installer = None
    result = _run(cp, dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_INSTALLER_FETCH, out
    assert "could not be fetched" in out
    assert DRIFT_MESSAGE not in out


def test_auth_failure_surfaces_the_structured_error(cp: FixtureCP) -> None:
    """A key the control plane rejects → exit 3, with the D-5 code + remediation."""
    result = _run(cp, key="s0ma_test_WRONGKEYVALUE", dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_MANIFEST, out
    assert "HTTP 401" in out
    assert "INVALID_KEY" in out
    assert "remediation:" in out
    assert "VERDICT: FAILED (exit 3)" in out
    # Downstream checks are skipped, never reported as passes.
    assert "no usable manifest" in out


def test_unreachable_control_plane_is_a_manifest_failure(cp: FixtureCP) -> None:
    """Nothing listening → exit 3 (and no traceback, no stray success)."""
    # A port that is closed: the fixture's own port + a high offset, with the
    # request pointed at a host:port nothing binds.
    dead = "http://127.0.0.1:1"
    bash = _require_tools()
    env = dict(os.environ, S0MA_SMOKE_KEY=TEST_KEY, no_proxy="*", NO_PROXY="*")
    result = subprocess.run(
        [bash, str(VERIFY_SH), "--version", VERSION, "--cp-host", dead],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=180,
    )
    out = _combined(result)
    assert result.returncode == EXIT_MANIFEST, out
    assert "could not reach the control plane" in out


# ---------------------------------------------------------------------------
# The key: environment-only, and never printed.
# ---------------------------------------------------------------------------


def test_the_key_never_appears_in_the_output(cp: FixtureCP) -> None:
    """Not on the green path, not in any echoed request line."""
    result = _run(cp, dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_OK, out
    assert TEST_KEY not in out, "the smoke key leaked into the output!"
    assert "FIXTURESECRETVALUE" not in out
    # Every keyed request is echoed with the redacted header instead.
    assert 'Authorization: Bearer ***' in out


def test_the_key_never_leaks_on_a_failure_path(cp: FixtureCP) -> None:
    """A rejected key is not echoed back while explaining the rejection."""
    wrong = "s0ma_test_WRONGSECRETVALUE"
    result = _run(cp, key=wrong, dist_dir=cp.dist_dir)
    out = _combined(result)
    assert result.returncode == EXIT_MANIFEST, out
    assert wrong not in out
    assert "WRONGSECRETVALUE" not in out


def test_missing_key_refuses_before_touching_the_network() -> None:
    """No S0MA_SMOKE_KEY → exit 1, naming the variable and the runbook."""
    result = _run_bare("--version", VERSION, key=None)
    out = _combined(result)
    assert result.returncode == EXIT_REFUSAL, out
    assert "S0MA_SMOKE_KEY" in result.stderr
    assert "hosting-getting-started" in result.stderr
    # Nothing was checked, so no summary and no verdict were printed.
    assert "VERDICT:" not in out
    assert "PASS:" not in out


def test_key_as_an_argument_is_refused() -> None:
    """``--key`` does not exist: argv is world-readable, so it never will."""
    result = _run_bare("--version", VERSION, "--key", "s0ma_test_ONARGV")
    out = _combined(result)
    assert result.returncode == EXIT_REFUSAL, out
    assert "there is no --key option" in result.stderr
    assert "S0MA_SMOKE_KEY" in result.stderr
    assert "s0ma_test_ONARGV" not in out


# ---------------------------------------------------------------------------
# Usage refusals.
# ---------------------------------------------------------------------------


def test_missing_version_fails_loudly() -> None:
    result = _run_bare("--cp-host", "https://example.invalid")
    assert result.returncode == EXIT_REFUSAL
    assert "a release version is required" in result.stderr


def test_tag_shaped_version_is_refused() -> None:
    """``v1.2.3`` is a tag, not a version — the workflow strips the ``v``."""
    result = _run_bare("--version", f"v{VERSION}")
    assert result.returncode == EXIT_REFUSAL
    assert "bare X.Y.Z release version" in result.stderr


def test_unknown_option_fails_loudly() -> None:
    result = _run_bare("--version", VERSION, "--bogus")
    assert result.returncode == EXIT_REFUSAL
    assert "unknown option" in result.stderr
