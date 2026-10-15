"""Tests for ``s0ma inspect`` module-name resolution and ``--all`` (M16).

M16 (feedback 5–6) makes ``s0ma inspect`` accept a module name in
addition to a path. The resolution chain is:

1. Existing filesystem path → use directly (legacy form).
2. Module name → ``project.build_dir/<name>.s0ma.json``.
3. ``.s0ma`` source basename → walk source/test roots.
4. Friendly error listing the available modules from the manifest.

``s0ma inspect --all`` prints a one-line-per-module project survey.

These tests build a fresh copy of the ``multi_module_project`` fixture
into a tmp directory with its own ``pyproject.toml`` so the project
discovery path can be exercised end-to-end without touching shared
fixtures.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import (
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    S0maCLI,
)

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_MULTI_MODULE_DIR = _FIXTURES_DIR / "multi_module_project"
_EXPECTED_MODULES = ("models", "processing", "routing")


# ---------------------------------------------------------------------------
# Project fixture — a real consumer-style layout with ``[tool.s0ma]``
# ---------------------------------------------------------------------------


@pytest.fixture()
def built_project(tmp_path: Path) -> Path:
    """Stage ``multi_module_project`` under a real project root and build.

    Lays the fixture out as::

        <tmp_path>/project/
            pyproject.toml         (with [tool.s0ma])
            src/<module>.s0ma      (one per fixture module)

    Then runs ``s0ma build`` so ``project.build_dir`` is populated and
    the manifest is in place. Returns the project root path.
    """
    project_root = tmp_path / "project"
    src_dir = project_root / "src"
    src_dir.mkdir(parents=True)

    for s0ma_file in _MULTI_MODULE_DIR.glob("*.s0ma"):
        shutil.copy(s0ma_file, src_dir / s0ma_file.name)

    (project_root / "pyproject.toml").write_text(
        '[project]\n'
        'name = "m16_inspect_fixture"\n'
        'version = "0.0.1"\n'
        '\n'
        '[tool.s0ma]\n'
        'source_roots = ["src"]\n'
        'test_roots = []\n'
        'build_dir = "build"\n'
        'bootstrap_files = []\n',
        encoding="utf-8",
    )

    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(project_root),
        "build", str(src_dir),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS, "fixture build failed"

    build_dir = project_root / "build"
    assert build_dir.is_dir()
    for name in _EXPECTED_MODULES:
        assert (build_dir / f"{name}.s0ma.json").is_file()

    return project_root


# ---------------------------------------------------------------------------
# 1) test_inspect_by_module_name
# ---------------------------------------------------------------------------


def test_inspect_by_module_name(built_project: Path, capsys) -> None:
    """``s0ma inspect <module_name>`` resolves the IR via the project."""
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(built_project),
        "inspect", "models",
    ])
    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS, captured.err
    assert "Module: models" in captured.out
    assert "Layer: DOMAIN" in captured.out


def test_inspect_by_module_name_json(built_project: Path, capsys) -> None:
    """Module-name resolution honours ``--format json`` for machine output."""
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(built_project),
        "inspect", "processing", "--format", "json",
    ])
    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS, captured.err
    payload = json.loads(captured.out)
    assert payload["module"]["name"] == "processing"
    assert payload["module"]["layer"] == "APPLICATION"


# ---------------------------------------------------------------------------
# 2) test_inspect_by_path_still_works (legacy)
# ---------------------------------------------------------------------------


def test_inspect_by_path_still_works(built_project: Path, capsys) -> None:
    """The pre-M16 path-based form continues to work unchanged."""
    ir_path = built_project / "build" / "routing.s0ma.json"
    assert ir_path.is_file()

    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(built_project),
        "inspect", str(ir_path),
    ])
    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS, captured.err
    assert "Module: routing" in captured.out


# ---------------------------------------------------------------------------
# 3) test_inspect_unknown_module_errors
# ---------------------------------------------------------------------------


def test_inspect_unknown_module_errors(built_project: Path, capsys) -> None:
    """Unknown module names produce a friendly error with the available list."""
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(built_project),
        "inspect", "no_such_module",
    ])
    captured = capsys.readouterr()
    assert rc == EXIT_USAGE_ERROR
    # The error names the missing target.
    assert "no_such_module" in captured.err
    # The error lists every available module.
    for name in _EXPECTED_MODULES:
        assert name in captured.err
    # And it labels the listing as such.
    assert "Available modules" in captured.err


def test_inspect_close_match_suggests_did_you_mean(
    built_project: Path, capsys,
) -> None:
    """A close-but-misspelled module name surfaces a 'Did you mean ...?' hint."""
    cli = S0maCLI()
    # ``modls`` is a single-edit-distance match for ``models``.
    rc = cli.run([
        "--project-root", str(built_project),
        "inspect", "modls",
    ])
    captured = capsys.readouterr()
    assert rc == EXIT_USAGE_ERROR
    assert "Did you mean" in captured.err
    assert "models" in captured.err


# ---------------------------------------------------------------------------
# 4) test_inspect_all_lists_every_module
# ---------------------------------------------------------------------------


def test_inspect_all_lists_every_module(built_project: Path, capsys) -> None:
    """``s0ma inspect --all`` prints a row for every module in the project."""
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(built_project),
        "inspect", "--all",
    ])
    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS, captured.err

    out = captured.out
    # Every module appears.
    for name in _EXPECTED_MODULES:
        assert name in out, f"module {name!r} missing from --all output: {out!r}"
    # Layer column is present.
    assert "DOMAIN" in out
    assert "APPLICATION" in out
    assert "PRESENTATION" in out
    # Header is present.
    assert "Module" in out
    assert "Layer" in out
    assert "Components" in out


def test_inspect_all_json(built_project: Path, capsys) -> None:
    """``s0ma inspect --all --format json`` emits a structured survey."""
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(built_project),
        "inspect", "--all", "--format", "json",
    ])
    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS, captured.err

    survey = json.loads(captured.out)
    assert isinstance(survey, list)
    assert {row["name"] for row in survey} == set(_EXPECTED_MODULES)
    for row in survey:
        assert isinstance(row["layer"], str)
        assert isinstance(row["components"], int)
        assert isinstance(row["kind_counts"], dict)


def test_inspect_all_without_project_errors(tmp_path: Path, capsys) -> None:
    """Without a discoverable project, ``--all`` errors with usage exit code."""
    # tmp_path has no pyproject.toml → discovery falls back to synthetic.
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(tmp_path),
        "inspect", "--all",
    ])
    captured = capsys.readouterr()
    assert rc == EXIT_USAGE_ERROR
    assert "no project resolved" in captured.err.lower() or "[tool.s0ma]" in captured.err


def test_inspect_no_target_no_all_errors(built_project: Path, capsys) -> None:
    """Calling ``s0ma inspect`` with neither target nor ``--all`` errors."""
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(built_project),
        "inspect",
    ])
    captured = capsys.readouterr()
    assert rc == EXIT_USAGE_ERROR
    assert "required" in captured.err
