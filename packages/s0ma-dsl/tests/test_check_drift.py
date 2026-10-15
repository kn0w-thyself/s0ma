"""Tests for ``s0ma docs check-drift`` (plan M7 subtask 8).

The drift check re-renders every doc declaration into memory using the
M6 renderer and byte-compares against the committed output. It must:
- exit 0 when committed output matches re-rendered bytes,
- exit 1 (and report ``DRIFT_DETECTED``) when the on-disk file differs,
- exit 1 when the on-disk file is missing entirely,
- respect the strictness-mode severity ladder (warning in migration/dev,
  error in strict/release).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.config import StrictnessMode, get_severity

FIXTURES = Path(__file__).parent / "fixtures" / "valid" / "docs" / "full_project"


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    target = tmp_path / "project"
    shutil.copytree(FIXTURES, target)
    cli = S0maCLI()
    rc = cli.run(["docs", "render", str(target)])
    assert rc == 0
    return target


class TestCheckDriftClean:
    def test_no_drift_after_render(self, project_dir: Path) -> None:
        cli = S0maCLI()
        rc = cli.run(["docs", "check-drift", str(project_dir), "--mode", "strict"])
        assert rc == 0


class TestCheckDriftDetected:
    def test_byte_diff_triggers_drift(self, project_dir: Path, capsys) -> None:
        # Tamper with one rendered output.
        target = project_dir / "docs" / "greetings_reference.md"
        text = target.read_text(encoding="utf-8")
        target.write_text(text + "tampered\n", encoding="utf-8")

        cli = S0maCLI()
        rc = cli.run(["docs", "check-drift", str(project_dir), "--mode", "strict"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "DRIFT_DETECTED" in out
        assert "greetings_reference.md" in out

    def test_missing_output_triggers_drift(self, project_dir: Path, capsys) -> None:
        target = project_dir / "docs" / "greetings_reference.md"
        target.unlink()
        cli = S0maCLI()
        rc = cli.run(["docs", "check-drift", str(project_dir), "--mode", "strict"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "DRIFT_DETECTED" in out
        assert "missing" in out


class TestCheckDriftStrictnessLadder:
    """Severity ladder for DRIFT_DETECTED: warning in migration/dev,
    error in strict/release (plan §11.11)."""

    def test_severity_matrix(self) -> None:
        assert get_severity("DRIFT_DETECTED", StrictnessMode.MIGRATION) == "warning"
        assert get_severity("DRIFT_DETECTED", StrictnessMode.DEV) == "warning"
        assert get_severity("DRIFT_DETECTED", StrictnessMode.STRICT) == "error"
        assert get_severity("DRIFT_DETECTED", StrictnessMode.RELEASE) == "error"

    def test_drift_in_migration_mode_warns_but_passes(
        self, project_dir: Path, capsys,
    ) -> None:
        target = project_dir / "docs" / "greetings_reference.md"
        target.write_text("tampered\n", encoding="utf-8")
        cli = S0maCLI()
        rc = cli.run(["docs", "check-drift", str(project_dir), "--mode", "migration"])
        # warning, not error → exit 0
        assert rc == 0
        out = capsys.readouterr().out
        assert "DRIFT_DETECTED" in out

    def test_drift_in_strict_mode_fails(
        self, project_dir: Path,
    ) -> None:
        target = project_dir / "docs" / "greetings_reference.md"
        target.write_text("tampered\n", encoding="utf-8")
        cli = S0maCLI()
        rc = cli.run(["docs", "check-drift", str(project_dir), "--mode", "strict"])
        assert rc == 1
