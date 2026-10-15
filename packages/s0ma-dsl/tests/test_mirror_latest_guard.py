"""Tests for the forward-only ``latest`` guard in ``scripts/mirror_to_r2.sh``.

``dist/manifest.json``'s top-level ``latest`` is what every keyed install
resolves when it asks for "latest". The mirror script used to set it
unconditionally, so mirroring an older version — a historical tag push is
enough — would silently downgrade every new install. Plan RD-5: forward-only
by semver, with ``--allow-latest-downgrade`` as the explicit override, which
doubles as the documented rollback mechanism.

These tests are **network-free by construction**. The real run's guard reads
the served manifest with ``wrangler``; the dry run reads a fixture instead,
via ``--existing-manifest <file>`` (rejected outside ``--dry-run``, so the
seam can never weaken a real mirror). Everything below drives that path with
throwaway wheel files, and every test skips gracefully without ``bash``.

One deliberate narrowing: the tests that EXECUTE the script skip on Windows.
Every dry run reaches ``merge_manifest``, the script's JSON-merge step, which
hands a ``python3`` heredoc its inputs through the environment — and on
Git-Bash that heredoc raises before it can merge (the Windows CI matrix fails
exactly, and only, the runs that reach it; the guard's own refusal paths pass
there). ``mirror_to_r2.sh`` is Linux/macOS release tooling — the release
workflow mirrors from ubuntu-latest and the runbook never invokes it on
Windows — so rather than assert an unverifiable interpreter/environment
behavior, Windows runs the static check only. This is the same narrowing, for
the same reason, as ``test_verify_served_script.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
MIRROR_SH = REPO_ROOT / "scripts" / "mirror_to_r2.sh"

#: The four wheel stems the mirror expects in --dist-dir (H4 contract).
WHEEL_STEMS = ("s0ma_core", "s0ma_dsl", "s0ma_mcp", "s0ma_studi0")

#: The flag that names the rollback path. Its exact spelling is part of the
#: refusal's remediation — RD-5 — so it is pinned here.
OVERRIDE_FLAG = "--allow-latest-downgrade"

_BASH = shutil.which("bash")


def _require_bash() -> str:
    """For the static check (``bash -n``) — parses the script, runs nothing."""
    if _BASH is None:
        pytest.skip("bash unavailable")
    return _BASH


def _require_run() -> str:
    """For the tests that actually execute the script (see module docstring)."""
    bash = _require_bash()
    if sys.platform.startswith("win"):
        pytest.skip(
            "every dry run reaches merge_manifest, whose python3 heredoc takes "
            "its inputs from the environment and raises under Git-Bash (see the "
            "module docstring). mirror_to_r2.sh is Linux/macOS release tooling."
        )
    return bash


def _dist_dir(tmp_path: Path, *versions: str) -> Path:
    """A wheel directory holding four plausible wheels per version."""
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    for version in versions:
        for stem in WHEEL_STEMS:
            (dist / f"{stem}-{version}-py3-none-any.whl").write_bytes(
                f"fixture wheel {stem} {version}\n".encode()
            )
    return dist


def _manifest(tmp_path: Path, name: str, payload: object) -> Path:
    path = tmp_path / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8", newline="\n")
    else:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8", newline="\n")
    return path


def _mirror(
    tmp_path: Path,
    version: str,
    *extra: str,
    existing: Path | None = None,
    dist: Path | None = None,
    dry_run: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Drive the mirror script offline. ``--dry-run`` makes no network calls."""
    bash = _require_run()
    dist_dir = dist if dist is not None else _dist_dir(tmp_path, version)
    cmd = [bash, str(MIRROR_SH), "--version", version, "--dist-dir", str(dist_dir)]
    if dry_run:
        cmd.append("--dry-run")
    if existing is not None:
        cmd += ["--existing-manifest", str(existing)]
    cmd += list(extra)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        cwd=str(REPO_ROOT),
    )


def _merged_manifest(stdout: str) -> dict:
    """Parse the manifest JSON a dry run prints after its comment banner."""
    start = stdout.index("\n{", stdout.index("manifest.json that would be written"))
    return json.loads(stdout[start:])


# ---------------------------------------------------------------------------
# Script-level invariants.
# ---------------------------------------------------------------------------


def test_mirror_script_parses_clean() -> None:
    """``bash -n scripts/mirror_to_r2.sh`` parses without error."""
    bash = _require_bash()
    result = subprocess.run(
        [bash, "-n", str(MIRROR_SH)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"bash -n reported:\n{result.stderr}"


def test_help_documents_the_guard_and_its_override() -> None:
    """``--help`` prints the USAGE block (not some other slice of the header)
    and documents both new flags."""
    bash = _require_run()
    result = subprocess.run(
        [bash, str(MIRROR_SH), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.lstrip().startswith("Usage:")
    assert OVERRIDE_FLAG in result.stdout
    assert "--existing-manifest" in result.stdout
    assert "set -euo pipefail" not in result.stdout


# ---------------------------------------------------------------------------
# The guard's verdicts.
# ---------------------------------------------------------------------------


def test_forward_release_is_allowed(tmp_path: Path) -> None:
    existing = _manifest(
        tmp_path, "m.json", {"latest": "0.16.1", "versions": {"0.16.1": {"wheels": []}}}
    )
    result = _mirror(tmp_path, "0.18.0", existing=existing)
    assert result.returncode == 0, result.stderr
    assert "forward, ok" in result.stdout
    merged = _merged_manifest(result.stdout)
    assert merged["latest"] == "0.18.0"
    # Prior versions survive the merge.
    assert set(merged["versions"]) == {"0.16.1", "0.18.0"}


def test_semver_compare_is_numeric_not_lexical(tmp_path: Path) -> None:
    """0.10.0 over 0.9.0 is FORWARD. Lexically "0.10.0" < "0.9.0", so a
    string compare would refuse a legitimate release (or, mirrored, wave a
    downgrade through)."""
    existing = _manifest(tmp_path, "m.json", {"latest": "0.9.0", "versions": {}})
    result = _mirror(tmp_path, "0.10.0", existing=existing)
    assert result.returncode == 0, result.stderr
    assert "is newer than the served latest 0.9.0" in result.stdout


def test_re_mirroring_the_same_version_is_allowed(tmp_path: Path) -> None:
    """Equal is not a downgrade: the verify-back re-run path must still work."""
    existing = _manifest(
        tmp_path, "m.json", {"latest": "0.17.0", "versions": {"0.17.0": {"wheels": []}}}
    )
    result = _mirror(tmp_path, "0.17.0", existing=existing)
    assert result.returncode == 0, result.stderr
    assert "IS the served latest" in result.stdout
    assert _merged_manifest(result.stdout)["latest"] == "0.17.0"


def test_downgrade_aborts_with_the_remediation(tmp_path: Path) -> None:
    existing = _manifest(
        tmp_path, "m.json", {"latest": "0.18.0", "versions": {"0.18.0": {"wheels": []}}}
    )
    result = _mirror(tmp_path, "0.9.0", existing=existing)

    assert result.returncode != 0
    assert "BACKWARDS" in result.stderr
    # Both ends of the move are named, so the operator can see the damage.
    assert "latest=0.18.0" in result.stderr
    assert "latest=0.9.0" in result.stderr
    # The remediation names the flag, and says nothing happened.
    assert OVERRIDE_FLAG in result.stderr
    assert "Nothing was written" in result.stderr
    # It aborts BEFORE proposing a manifest.
    assert "manifest.json that would be written" not in result.stdout


def test_downgrade_with_the_override_is_allowed_and_preserves_history(
    tmp_path: Path,
) -> None:
    """The flag IS the rollback mechanism (RD-5): latest moves back, and the
    newer version stays in `versions` (wheel objects are untouched)."""
    existing = _manifest(
        tmp_path,
        "m.json",
        {
            "latest": "0.18.0",
            "versions": {"0.18.0": {"wheels": []}, "0.17.0": {"wheels": []}},
        },
    )
    result = _mirror(tmp_path, "0.17.0", OVERRIDE_FLAG, existing=existing)

    assert result.returncode == 0, result.stderr
    assert "DELIBERATE ROLLBACK" in result.stdout
    merged = _merged_manifest(result.stdout)
    assert merged["latest"] == "0.17.0"
    assert "0.18.0" in merged["versions"], "a rollback must not erase the newer release"


def test_a_fresh_bucket_has_nothing_to_protect(tmp_path: Path) -> None:
    """No manifest / no `latest` key / empty file: allowed, loudly."""
    cases = [
        _manifest(tmp_path, "no-latest.json", {"versions": {}}),
        _manifest(tmp_path, "empty.json", ""),
        _manifest(tmp_path, "null-latest.json", {"latest": None, "versions": {}}),
        _manifest(tmp_path, "blank-latest.json", {"latest": "  ", "versions": {}}),
    ]
    for existing in cases:
        result = _mirror(tmp_path, "0.18.0", existing=existing)
        assert result.returncode == 0, f"{existing.name}: {result.stderr}"
        assert "nothing to protect" in result.stdout, existing.name


def test_an_uncomparable_latest_aborts_rather_than_guessing(tmp_path: Path) -> None:
    """If the served `latest` is not X.Y.Z, forward motion cannot be proven —
    so the run refuses instead of assuming, and names the same override."""
    existing = _manifest(tmp_path, "m.json", {"latest": "banana", "versions": {}})
    result = _mirror(tmp_path, "0.18.0", existing=existing)

    assert result.returncode != 0
    assert "cannot prove" in result.stderr
    assert '"banana"' in result.stderr
    assert OVERRIDE_FLAG in result.stderr

    forced = _mirror(tmp_path, "0.18.0", OVERRIDE_FLAG, existing=existing)
    assert forced.returncode == 0, forced.stderr
    assert _merged_manifest(forced.stdout)["latest"] == "0.18.0"


@pytest.mark.parametrize("payload", ["{ this is not json", "[]", '"latest"'])
def test_an_unreadable_manifest_aborts_in_the_guard(
    tmp_path: Path, payload: str
) -> None:
    """A manifest that is not a JSON object cannot be checked OR merged
    (merging it would drop every version it lists). It fails in the guard —
    i.e. before any wheel object is written — and no override bypasses it."""
    existing = _manifest(tmp_path, "m.json", payload)
    result = _mirror(tmp_path, "0.18.0", existing=existing)
    assert result.returncode != 0
    assert "not valid JSON" in result.stderr or "not a JSON object" in result.stderr
    assert "manifest.json that would be written" not in result.stdout

    forced = _mirror(tmp_path, "0.18.0", OVERRIDE_FLAG, existing=existing)
    assert forced.returncode != 0, "the rollback flag must not excuse a broken manifest"


# ---------------------------------------------------------------------------
# The offline seam cannot weaken a real mirror.
# ---------------------------------------------------------------------------


def test_existing_manifest_is_rejected_without_dry_run(tmp_path: Path) -> None:
    """A real mirror always reads the LIVE manifest; the fixture seam is
    dry-run only, so it can never be used to fake the guard's input."""
    existing = _manifest(tmp_path, "m.json", {"latest": "0.18.0", "versions": {}})
    result = _mirror(tmp_path, "0.9.0", existing=existing, dry_run=False)
    assert result.returncode == 1
    assert "--dry-run only" in result.stderr


def test_missing_existing_manifest_file_fails_loudly(tmp_path: Path) -> None:
    result = _mirror(tmp_path, "0.18.0", existing=tmp_path / "nope.json")
    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_plain_dry_run_says_the_guard_was_not_evaluated(tmp_path: Path) -> None:
    """Without a fixture the guard has nothing to compare against — a dry run
    must say so rather than imply it checked."""
    result = _mirror(tmp_path, "0.18.0")
    assert result.returncode == 0, result.stderr
    assert "is NOT evaluated here" in result.stdout
    assert "--existing-manifest" in result.stdout
    # Still the pre-existing behaviour: this release alone, no network.
    assert _merged_manifest(result.stdout)["latest"] == "0.18.0"


def test_dry_run_makes_no_network_calls(tmp_path: Path) -> None:
    """The dry run never shells out to wrangler (the only network path)."""
    existing = _manifest(tmp_path, "m.json", {"latest": "0.16.1", "versions": {}})
    result = _mirror(tmp_path, "0.18.0", existing=existing)
    assert result.returncode == 0
    assert "wrangler r2 object" not in result.stdout
    assert "wrangler" not in result.stderr


# ---------------------------------------------------------------------------
# F-2: r2_get distinguishes "absent" from "read failed" (wet path, faked).
# ---------------------------------------------------------------------------


def _fake_wrangler_env(tmp_path: Path, mode: str) -> tuple[dict[str, str], Path]:
    """A PATH-first `wrangler` stub: `object get` answers per *mode*
    (``notfound`` → wrangler 4's not-found stderr; anything else → a
    transient network error); `object put` fails with a sentinel so a run
    that legitimately passes the guard stops deterministically right after
    it. Every invocation is logged to a calls file."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    calls = tmp_path / "wrangler-calls.log"
    stub = bin_dir / "wrangler"
    stub.write_text(
        '#!/bin/sh\n'
        'printf "%s\\n" "$*" >> "$FAKE_CALLS"\n'
        'case "$*" in\n'
        '  *"object get"*)\n'
        '    if [ "$FAKE_MODE" = "notfound" ]; then\n'
        '      echo "X [ERROR] The specified key does not exist." >&2\n'
        '    else\n'
        '      echo "read tcp 203.0.113.9:443: connection reset by peer" >&2\n'
        '    fi\n'
        '    exit 1 ;;\n'
        '  *"object put"*) echo "FAKE-PUT-STOP" >&2; exit 9 ;;\n'
        'esac\n'
        'exit 0\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_CALLS"] = str(calls)
    env["FAKE_MODE"] = mode
    env["CLOUDFLARE_API_TOKEN"] = "fake-token-for-classification-test"
    return env, calls


def _wet_mirror(tmp_path: Path, mode: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    bash = _require_run()
    env, calls = _fake_wrangler_env(tmp_path, mode)
    dist_dir = _dist_dir(tmp_path, "0.18.0")
    result = subprocess.run(
        [bash, str(MIRROR_SH), "--version", "0.18.0", "--dist-dir", str(dist_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        cwd=str(REPO_ROOT),
        env=env,
    )
    return result, calls


def test_a_genuine_not_found_still_reads_as_a_fresh_bucket(tmp_path: Path) -> None:
    """wrangler's "specified key does not exist" → the guard's `none` path,
    and the run proceeds to the (sentinel-stopped) first upload."""
    result, calls = _wet_mirror(tmp_path, "notfound")
    assert "nothing to protect" in result.stdout, result.stdout
    assert "refusing to treat a failed read" not in result.stderr
    logged = calls.read_text(encoding="utf-8")
    assert "object get" in logged and "object put" in logged
    assert result.returncode != 0  # the deliberate FAKE-PUT-STOP sentinel
    assert "FAKE-PUT-STOP" in result.stderr


def test_any_other_read_failure_aborts_instead_of_playing_fresh(tmp_path: Path) -> None:
    """A transient/auth read failure must never be treated as an empty
    bucket: the run dies before ANY write, naming the real stderr."""
    result, calls = _wet_mirror(tmp_path, "transient")
    assert result.returncode != 0
    assert "refusing to treat a failed read" in result.stderr, result.stderr
    assert "connection reset by peer" in result.stderr
    logged = calls.read_text(encoding="utf-8")
    assert "object put" not in logged, logged
    assert "nothing to protect" not in result.stdout
