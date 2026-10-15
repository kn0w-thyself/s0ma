"""Tests for the S0maProject discovery model (Milestone 1).

Covers the [tool.s0ma] schema, defaults, upward-walk discovery, and
the S0maProjectNotFound remediation path.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl import S0maProject
from s0ma_dsl.errors import S0maProjectNotFound
from s0ma_dsl.project import DEFAULT_SOURCE_ROOTS, DEFAULT_TEST_ROOTS

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_pyproject(
    root: Path,
    *,
    project_name: str = "fakeproj",
    tool_s0ma: str | None = "",
) -> Path:
    """Write a minimal pyproject.toml at *root*.

    *tool_s0ma* is the body of the ``[tool.s0ma]`` table. ``""`` writes
    an empty table; ``None`` omits the table entirely.
    """
    body = dedent(f"""
        [project]
        name = "{project_name}"
        version = "0.1.0"
    """).lstrip()
    if tool_s0ma is not None:
        body += "\n[tool.s0ma]\n" + tool_s0ma + "\n"
    pyproject = root / "pyproject.toml"
    pyproject.write_text(body)
    return pyproject


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discover_finds_pyproject_with_tool_s0ma(tmp_path: Path) -> None:
    """Discovery finds the right root and parses [tool.s0ma] keys."""
    _write_pyproject(
        tmp_path,
        project_name="myproj",
        tool_s0ma=dedent("""
            source_roots = ["src", "lib"]
            test_roots = ["tests", "tests_extra"]
            build_dir = "build_out"
        """).strip(),
    )
    deep = tmp_path / "src" / "deep" / "subdir"
    deep.mkdir(parents=True)

    project = S0maProject.discover(deep)

    assert project.root == tmp_path.resolve()
    assert project.project_name == "myproj"
    assert project.source_roots == (
        (tmp_path / "src").resolve(),
        (tmp_path / "lib").resolve(),
    )
    assert project.test_roots == (
        (tmp_path / "tests").resolve(),
        (tmp_path / "tests_extra").resolve(),
    )
    assert project.build_dir == (tmp_path / "build_out").resolve()
    assert project.bootstrap_files == ()
    assert project.synthetic is False


def test_discover_raises_when_no_tool_s0ma(tmp_path: Path) -> None:
    """Discovery raises S0maProjectNotFound with a remediation message."""
    _write_pyproject(tmp_path, tool_s0ma=None)
    with pytest.raises(S0maProjectNotFound) as exc_info:
        S0maProject.discover(tmp_path)
    err_text = str(exc_info.value)
    assert "[tool.s0ma]" in err_text
    assert "pyproject.toml" in err_text
    # Remediation must include the minimal-table example.
    assert "source_roots" in err_text


def test_discover_uses_defaults_when_table_is_empty(tmp_path: Path) -> None:
    """Empty [tool.s0ma] table yields default source_roots / test_roots / build_dir."""
    _write_pyproject(tmp_path, project_name="defaultsproj", tool_s0ma="")
    project = S0maProject.discover(tmp_path)
    assert project.source_roots == tuple(
        (tmp_path / r).resolve() for r in DEFAULT_SOURCE_ROOTS
    )
    assert project.test_roots == tuple(
        (tmp_path / r).resolve() for r in DEFAULT_TEST_ROOTS
    )
    assert project.build_dir == (tmp_path / "defaultsproj_build").resolve()
    assert project.bootstrap_files == ()
    assert project.warnings == ()


def test_discover_resolves_bootstrap_files(tmp_path: Path) -> None:
    """Declared bootstrap files resolve to absolute paths.

    Files that do not exist on disk surface as warnings (not errors) so
    fresh consumer projects can declare entries before scaffolding.
    """
    src = tmp_path / "src" / "myproj"
    src.mkdir(parents=True)
    existing = src / "main.py"
    existing.write_text("# bootstrap\n")
    _write_pyproject(
        tmp_path,
        project_name="myproj",
        tool_s0ma=dedent("""
            bootstrap_files = ["src/myproj/main.py", "src/myproj/missing.py"]
        """).strip(),
    )

    project = S0maProject.discover(tmp_path)

    assert (tmp_path / "src" / "myproj" / "main.py").resolve() in project.bootstrap_files
    assert (tmp_path / "src" / "myproj" / "missing.py").resolve() in project.bootstrap_files
    # Every bootstrap path is absolute.
    assert all(p.is_absolute() for p in project.bootstrap_files)
    # The missing file produced a warning, not an error.
    assert any("missing.py" in w for w in project.warnings)


def test_discover_walks_up_from_subdir(tmp_path: Path) -> None:
    """Discovery walks upward through arbitrary directory depth."""
    _write_pyproject(tmp_path, project_name="walkproj", tool_s0ma="")
    deep = tmp_path / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)

    project = S0maProject.discover(deep)

    assert project.root == tmp_path.resolve()
    assert project.project_name == "walkproj"


# ---------------------------------------------------------------------------
# Synthetic fallback
# ---------------------------------------------------------------------------


def test_synthetic_fallback_uses_basename_for_project_name(tmp_path: Path) -> None:
    """The legacy fallback names the project after the start directory."""
    project = S0maProject.synthetic_fallback(tmp_path)
    assert project.synthetic is True
    assert project.project_name == tmp_path.name
    assert project.source_roots == tuple(
        (tmp_path / r).resolve() for r in DEFAULT_SOURCE_ROOTS
    )


# ---------------------------------------------------------------------------
# CLI integration: legacy fallback warning
# ---------------------------------------------------------------------------


def test_cli_legacy_mode_warns_on_missing_tool_s0ma(tmp_path, capsys, monkeypatch):
    """When no [tool.s0ma] is reachable, the CLI emits a one-line warning
    and continues with a synthetic project."""
    from s0ma_dsl.cli.main import S0maCLI

    # Make the tmp_path a project root with NO pyproject.toml at all.
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "test.s0ma"
    src.write_text(
        "module empty_module\n"
        "    layer: DOMAIN\n"
        "    version: 0.1.0\n"
        '    intent: "x"\n'
    )

    cli = S0maCLI()
    # Use --mode dev so missing exports are tolerated; the precise exit
    # code is not the assertion target — the warning is.
    cli.run(["check", str(src), "--mode", "dev"])

    err = capsys.readouterr().err
    assert "Operating without project discovery" in err


def test_cli_no_warning_when_tool_s0ma_present(tmp_path, capsys, monkeypatch):
    """When [tool.s0ma] is reachable, no legacy-mode warning is emitted."""
    from s0ma_dsl.cli.main import S0maCLI

    _write_pyproject(tmp_path, project_name="quietproj", tool_s0ma="")
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "test.s0ma"
    src.write_text(
        "module empty_module\n"
        "    layer: DOMAIN\n"
        "    version: 0.1.0\n"
        '    intent: "x"\n'
    )

    cli = S0maCLI()
    cli.run(["check", str(src), "--mode", "dev"])

    err = capsys.readouterr().err
    assert "Operating without project discovery" not in err


# ---------------------------------------------------------------------------
# DSL-M4 (F-M0-1): discovery-warning upgrade when the positional argument
# itself carries a [tool.s0ma] table that CWD-anchored discovery missed.
# ---------------------------------------------------------------------------


class TestFindUnusedToolS0maTable:
    def test_finds_table_on_positional_path(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        pyproject = _write_pyproject(proj, tool_s0ma='build_dir = "_built"')
        assert S0maProject.find_unused_tool_s0ma_table(proj) == pyproject

    def test_finds_table_from_a_file_inside_the_project(
        self, tmp_path: Path,
    ) -> None:
        proj = tmp_path / "proj"
        (proj / "src").mkdir(parents=True)
        pyproject = _write_pyproject(proj, tool_s0ma="")
        src = proj / "src" / "m.s0ma"
        src.write_text("module m\n")
        assert S0maProject.find_unused_tool_s0ma_table(src) == pyproject

    def test_returns_none_when_no_table_present(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_pyproject(proj, tool_s0ma=None)  # pyproject without [tool.s0ma]
        assert S0maProject.find_unused_tool_s0ma_table(proj) is None

    def test_returns_none_when_no_pyproject_at_all(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        assert S0maProject.find_unused_tool_s0ma_table(bare) is None


def test_cli_warns_with_project_root_hint_when_positional_table_unused(
    tmp_path, capsys, monkeypatch,
):
    """F-M0-1: ``s0ma build <project_dir>`` from a CWD without a
    ``[tool.s0ma]`` table, where <project_dir> DOES carry one, upgrades the
    warning to name the unused table and suggest ``--project-root``."""
    from s0ma_dsl.cli.main import S0maCLI

    # The project (with a table) lives in a subdirectory; the CWD is a
    # sibling with no reachable table, so CWD-anchored discovery fails.
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    pyproject = _write_pyproject(proj, tool_s0ma='source_roots = ["src"]')
    (proj / "src" / "m.s0ma").write_text(
        "module m\n"
        "    layer: DOMAIN\n"
        "    version: 0.1.0\n"
        '    intent: "x"\n'
    )
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    cli = S0maCLI()
    cli.run(["build", str(proj), "--mode", "dev", "--quiet"])

    err = capsys.readouterr().err
    assert "Operating without project discovery" in err
    assert str(pyproject) in err
    assert "--project-root" in err
    assert str(proj) in err


def test_cli_uses_plain_warning_when_positional_has_no_table(
    tmp_path, capsys, monkeypatch,
):
    """F-M0-1: with no [tool.s0ma] anywhere (CWD or positional), the warning
    stays the historic plain message — no spurious --project-root hint."""
    from s0ma_dsl.cli.main import S0maCLI

    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    # A pyproject WITHOUT a [tool.s0ma] table.
    _write_pyproject(proj, tool_s0ma=None)
    (proj / "src" / "m.s0ma").write_text(
        "module m\n"
        "    layer: DOMAIN\n"
        "    version: 0.1.0\n"
        '    intent: "x"\n'
    )
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    cli = S0maCLI()
    cli.run(["build", str(proj), "--mode", "dev", "--quiet"])

    err = capsys.readouterr().err
    assert "Operating without project discovery" in err
    assert "--project-root" not in err
    assert "was not used" not in err
