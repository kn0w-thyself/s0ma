"""Shared pytest fixtures and helpers for the s0ma DSL transpiler test suite."""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
VALID_FIXTURES_DIR = FIXTURES_DIR / "valid"
INVALID_FIXTURES_DIR = FIXTURES_DIR / "invalid"
GOLDEN_FIXTURES_DIR = FIXTURES_DIR / "golden"


@pytest.fixture()
def fixtures_dir() -> Path:
    """Path to the top-level fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture()
def valid_fixtures_dir() -> Path:
    """Path to the directory containing valid .s0ma fixtures."""
    return VALID_FIXTURES_DIR


@pytest.fixture()
def invalid_fixtures_dir() -> Path:
    """Path to the directory containing invalid .s0ma fixtures."""
    return INVALID_FIXTURES_DIR


@pytest.fixture()
def golden_fixtures_dir() -> Path:
    """Path to the directory containing golden output fixtures."""
    return GOLDEN_FIXTURES_DIR


@pytest.fixture()
def tmp_output_dir(tmp_path: Path) -> Path:
    """Temporary directory for transpiler output during tests."""
    out = tmp_path / "output"
    out.mkdir()
    return out


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def assert_no_errors(errors: list) -> None:
    """Assert that an error list is empty, printing diagnostics if not."""
    if errors:
        def _fmt(err: object) -> str:
            fmt = getattr(err, "format_text", None)
            return fmt() if callable(fmt) else str(err)

        msgs = "\n".join(_fmt(e) for e in errors)
        pytest.fail(f"Expected no errors but got {len(errors)}:\n{msgs}")


def assert_has_error(errors: list, code: str) -> None:
    """Assert that at least one error with the given code exists."""
    codes = [getattr(e, "code", None) for e in errors]
    if code not in codes:
        pytest.fail(
            f"Expected error code '{code}' but found: {codes}"
        )


def assert_artifacts_identical(label: str, reference: str, other: str) -> None:
    """Assert two artifact texts are identical; show a unified diff if not.

    The comparison is deliberately raw — no path normalisation. Build
    artifacts must be byte-identical across runs and output directories
    on every OS: embedded output references are directory-independent
    basenames (WIN-M3). A diff here means a machine-, run-, or
    directory-dependent value leaked into an artifact; the unified diff
    in the failure output shows exactly which bytes diverged (CI logs
    on platforms without local repro depend on this).
    """
    if reference == other:
        return
    diff = "\n".join(difflib.unified_diff(
        reference.splitlines(),
        other.splitlines(),
        fromfile=f"{label} (reference)",
        tofile=f"{label} (other)",
        lineterm="",
    ))
    pytest.fail(f"{label} differs between runs:\n{diff}")
