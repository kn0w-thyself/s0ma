"""M11 (feedback 5–6) — declarative bootstrap-file recognition.

Locks down the M11 contract:

- ``s0ma verify`` reads ``[tool.s0ma].bootstrap_files`` from the
  resolved :class:`S0maProject` and emits status ``BOOTSTRAP`` for
  declared plain-Python entry points (informational).
- ``.py`` files without a ``.s0ma`` source and *not* declared under
  ``bootstrap_files`` keep emitting ``UNKNOWN`` with the actionable
  remediation pointing at the declaration or a transpile.
- Default text output omits ``BOOTSTRAP`` rows so the noise floor goes
  to zero on a project that declares its bootstrap surface; the
  summary line still reports the recognised count.
- ``--verbose`` re-enables per-file ``BOOTSTRAP`` rows.

Pairs with ``tests/test_project_discovery.py`` (M1 schema) and the
``TestVerifyCommand`` class in ``tests/test_cli.py`` (M5b drift
detection on hash-bearing ``.py`` files).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import (
    EXIT_NOTHING_VERIFIED,
    EXIT_SUCCESS,
    S0maCLI,
)

FIXTURE = Path(__file__).parent / "fixtures" / "project_with_bootstrap"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cli() -> S0maCLI:
    return S0maCLI()


@pytest.fixture()
def built_project(tmp_path: Path, cli: S0maCLI) -> tuple[Path, Path]:
    """Build the M11 fixture into a fresh tmp output dir.

    Each test runs against its own directory so writes from one test
    cannot leak to another. Returns ``(project_root, build_dir)``: the
    project root is the original fixture (so discovery sees the real
    ``[tool.s0ma]`` table), the build dir holds the transpiled
    artifacts.
    """
    out_dir = tmp_path / "build"
    rc = cli.run([
        "--project-root", str(FIXTURE),
        "build", str(FIXTURE / "src" / "sample_app"),
        "--output-dir", str(out_dir),
        # POST-11a / M-16 (0.16.0): suppress the
        # BUILD_DIR_OVERRIDE_CONFLICT pre-flight since this test
        # deliberately writes to a tmp build dir rather than the
        # configured ``[tool.s0ma].build_dir``.
        "--force-output-dir",
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS, "fixture build failed"
    return FIXTURE, out_dir


# ---------------------------------------------------------------------------
# 1. Declared bootstrap files surface as BOOTSTRAP, not UNKNOWN
# ---------------------------------------------------------------------------


def test_verify_recognizes_declared_bootstrap(
    cli: S0maCLI, built_project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """A ``.py`` listed under ``[tool.s0ma].bootstrap_files`` is BOOTSTRAP.

    The fixture declares ``src/sample_app/main.py`` and
    ``src/sample_app/bootstrap/startup.py`` as bootstrap files. Run
    ``s0ma verify --format json`` against each of them and assert the
    resolver emits status ``BOOTSTRAP`` with the M11 detail string,
    not ``UNKNOWN``.
    """
    project_root, _ = built_project
    main_py = project_root / "src" / "sample_app" / "main.py"
    startup_py = project_root / "src" / "sample_app" / "bootstrap" / "startup.py"

    for declared in (main_py, startup_py):
        capsys.readouterr()
        rc = cli.run([
            "--project-root", str(project_root),
            "verify", str(declared),
            "--format", "json",
        ])
        # Pilot01: a BOOTSTRAP-only target carries zero checked rows,
        # so verify reports "nothing verified" (deliberate — an
        # informational row is not a verified module).
        assert rc == EXIT_NOTHING_VERIFIED
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        assert {row["status"] for row in data} == {"BOOTSTRAP", "HOLLOW_MODEL"}
        row = next(row for row in data if row["status"] == "BOOTSTRAP")
        assert row["status"] == "BOOTSTRAP", (
            f"{declared} should be BOOTSTRAP, got {row['status']!r}"
        )
        assert "bootstrap_files" in row["detail"]


# ---------------------------------------------------------------------------
# 2. Undeclared .py files surface as UNKNOWN with the M11 remediation
# ---------------------------------------------------------------------------


def test_verify_flags_undeclared_py_as_unknown(
    cli: S0maCLI, built_project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """A plain-Python file without a ``.s0ma`` and without a declaration is UNKNOWN.

    The fixture carries ``stray_utility.py`` next to ``main.py`` but
    *does not* list it under ``[tool.s0ma].bootstrap_files``. The
    expected UX: status ``UNKNOWN`` with a remediation pointing at
    either declaring the file or transpiling a ``.s0ma`` source for
    it.
    """
    project_root, _ = built_project
    stray_py = project_root / "src" / "sample_app" / "stray_utility.py"

    capsys.readouterr()
    rc = cli.run([
        "--project-root", str(project_root),
        "verify", str(stray_py),
        "--format", "json",
    ])
    # UNKNOWN is a warning, not a hard fail (exit 1); but pilot01 makes
    # an all-UNKNOWN target exit EXIT_NOTHING_VERIFIED — zero verified
    # modules is not a pass.
    assert rc == EXIT_NOTHING_VERIFIED
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert {row["status"] for row in data} == {"UNKNOWN", "HOLLOW_MODEL"}
    row = next(row for row in data if row["status"] == "UNKNOWN")
    assert row["status"] == "UNKNOWN"
    detail = row["detail"]
    assert "[tool.s0ma].bootstrap_files" in detail
    assert "transpile a .s0ma source" in detail


# ---------------------------------------------------------------------------
# 3. Default text output hides BOOTSTRAP rows; summary still reports them
# ---------------------------------------------------------------------------


def test_verify_default_output_hides_bootstrap(
    cli: S0maCLI, built_project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Default ``s0ma verify`` text output omits BOOTSTRAP per-file rows.

    M11 collapses the noise floor by hiding the recognised-bootstrap
    rows from the default output. The summary line still names the
    count so the consumer can see the project's exception surface at
    a glance.
    """
    project_root, _ = built_project
    src_dir = project_root / "src" / "sample_app"

    capsys.readouterr()
    rc = cli.run([
        "--project-root", str(project_root),
        "verify", str(src_dir),
    ])
    # M11 keeps UNKNOWN as a warning (never exit 1); pilot01 makes the
    # zero-checked-rows tree exit EXIT_NOTHING_VERIFIED (the src tree
    # holds no hash-bearing .py). The structural assertions are about
    # output content, not exit code.
    assert rc == EXIT_NOTHING_VERIFIED
    out = capsys.readouterr().out

    # No per-file BOOTSTRAP row should appear in the default rendering.
    for line in out.splitlines():
        # The summary line is allowed to mention "bootstrap" — it's
        # the count, not a per-file row.
        if line.lstrip().startswith("BOOTSTRAP "):
            pytest.fail(
                f"Default verify output should not show BOOTSTRAP rows; got: {line!r}"
            )

    # The M11 summary line is always present and names the count.
    assert "bootstrap file(s) recognized" in out
    # 2 declared bootstrap files in the fixture
    assert "2 bootstrap file(s) recognized" in out


# ---------------------------------------------------------------------------
# 4. --verbose re-introduces the BOOTSTRAP rows
# ---------------------------------------------------------------------------


def test_verify_verbose_shows_bootstrap_rows(
    cli: S0maCLI, built_project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """``s0ma verify --verbose`` re-introduces the per-file BOOTSTRAP rows.

    ``--verbose`` is the explicit opt-in for "show me everything"; the
    default behaviour is the new noise-floor-zero shape.
    """
    project_root, _ = built_project
    src_dir = project_root / "src" / "sample_app"

    capsys.readouterr()
    rc = cli.run([
        "--project-root", str(project_root),
        "verify", str(src_dir),
        "--verbose",
    ])
    # Pilot01: zero checked rows in the src tree → nothing verified.
    assert rc == EXIT_NOTHING_VERIFIED
    out = capsys.readouterr().out

    bootstrap_lines = [
        line for line in out.splitlines()
        if line.lstrip().startswith("BOOTSTRAP ")
    ]
    # Both fixture-declared bootstrap files must be present as rows.
    assert any("main.py" in line for line in bootstrap_lines), (
        f"--verbose should surface main.py as BOOTSTRAP; got rows: {bootstrap_lines!r}"
    )
    assert any("startup.py" in line for line in bootstrap_lines), (
        f"--verbose should surface startup.py as BOOTSTRAP; got rows: {bootstrap_lines!r}"
    )
    # The summary row is unchanged.
    assert "2 bootstrap file(s) recognized" in out
