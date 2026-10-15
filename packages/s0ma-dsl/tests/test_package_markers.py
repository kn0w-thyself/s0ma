"""G1 (feedback 5–6 cleanup) — package-marker classification.

Pins the four-status verify taxonomy:

* ``OK`` / ``CLEAN`` — transpiled artifact whose checksum matches.
* ``BOOTSTRAP`` — declared in ``[tool.s0ma].bootstrap_files``.
* ``PACKAGE_MARKER`` — empty / docstring-only ``__init__.py``
  auto-classified, OR explicitly declared in
  ``[tool.s0ma].package_markers``.
* ``UNKNOWN`` — none of the above.

Locks down:

- ``is_empty_package_marker`` AST inspection: empty body, single-
  docstring body → marker; any executable content → not a marker.
- The default text output hides ``PACKAGE_MARKER`` rows the same way
  ``BOOTSTRAP`` rows are hidden — it is informational and surfaces
  only under ``--verbose``.
- The default summary footer omits the package-marker count;
  ``--verbose`` includes it.
- Explicit declaration wins: a non-empty ``__init__.py`` carrying
  ``__all__`` re-exports listed under ``[tool.s0ma].package_markers``
  is classified as ``PACKAGE_MARKER``, not ``UNKNOWN``.
- A file appearing in BOTH ``bootstrap_files`` and
  ``package_markers`` produces a load-time
  ``CONFLICTING_PACKAGE_DECLARATION`` error in every mode (silent no
  op forbidden).

Pairs with ``tests/test_verify_bootstrap.py`` (M11 BOOTSTRAP shape)
and ``tests/test_project_discovery.py`` (M1 schema) — same project
discovery / verify command surfaces, extended for the new fourth
status.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from s0ma_dsl.cli.main import EXIT_NOTHING_VERIFIED, S0maCLI
from s0ma_dsl.project import S0maProject, is_empty_package_marker

FIXTURE = Path(__file__).parent / "fixtures" / "package_markers_project"


# ---------------------------------------------------------------------------
# is_empty_package_marker AST inspection
# ---------------------------------------------------------------------------


class TestIsEmptyPackageMarker:
    """Unit tests for the structural classifier."""

    def test_empty_init_is_marker(self, tmp_path: Path) -> None:
        """A zero-byte ``__init__.py`` is a package marker."""
        path = tmp_path / "__init__.py"
        path.write_text("")
        assert is_empty_package_marker(path) is True

    def test_whitespace_only_init_is_marker(self, tmp_path: Path) -> None:
        """Whitespace / blank-lines only ``__init__.py`` is a marker.

        ``ast.parse`` returns an empty module body for whitespace-only
        input, so the helper takes the empty-body branch.
        """
        path = tmp_path / "__init__.py"
        path.write_text("\n\n   \n\t\n\n")
        assert is_empty_package_marker(path) is True

    def test_docstring_only_init_is_marker(self, tmp_path: Path) -> None:
        """A single triple-quoted docstring at module scope is a marker.

        The body still has executable content in the strict sense —
        the docstring itself is an ``ast.Expr`` node — but it carries
        no behaviour. Python's own ``__init__.py`` convention covers
        this case explicitly.
        """
        path = tmp_path / "__init__.py"
        path.write_text('"""my package marker."""\n')
        assert is_empty_package_marker(path) is True

    def test_multiline_docstring_only_init_is_marker(
        self, tmp_path: Path
    ) -> None:
        """A multi-paragraph docstring is still structurally empty."""
        path = tmp_path / "__init__.py"
        path.write_text(
            dedent(
                '''\
                """Multi-paragraph docstring.

                Spans several lines but contributes zero runtime
                behaviour.
                """
                '''
            )
        )
        assert is_empty_package_marker(path) is True

    def test_init_with_dunder_all_is_not_marker(self, tmp_path: Path) -> None:
        """``__all__`` re-exports disqualify auto-classification."""
        path = tmp_path / "__init__.py"
        path.write_text('__all__ = ["foo", "bar"]\n')
        assert is_empty_package_marker(path) is False

    def test_init_with_import_is_not_marker(self, tmp_path: Path) -> None:
        """An ``import`` statement disqualifies auto-classification."""
        path = tmp_path / "__init__.py"
        path.write_text("import os\n")
        assert is_empty_package_marker(path) is False

    def test_init_with_assignment_is_not_marker(self, tmp_path: Path) -> None:
        """An assignment disqualifies auto-classification."""
        path = tmp_path / "__init__.py"
        path.write_text("VERSION = '1.0.0'\n")
        assert is_empty_package_marker(path) is False

    def test_init_with_docstring_then_import_is_not_marker(
        self, tmp_path: Path
    ) -> None:
        """Docstring-plus-anything-else fails the single-statement check."""
        path = tmp_path / "__init__.py"
        path.write_text('"""docs."""\nimport os\n')
        assert is_empty_package_marker(path) is False

    def test_non_init_path_is_not_marker(self, tmp_path: Path) -> None:
        """The helper is gated on the ``__init__`` stem.

        An empty ``utils.py`` is not a package marker — the file is
        simply empty source code, and the verify pipeline should keep
        surfacing it as ``UNKNOWN`` so the author gets the remediation.
        """
        path = tmp_path / "utils.py"
        path.write_text("")
        assert is_empty_package_marker(path) is False

    def test_non_py_path_is_not_marker(self, tmp_path: Path) -> None:
        """The helper is gated on the ``.py`` suffix."""
        path = tmp_path / "__init__.txt"
        path.write_text("")
        assert is_empty_package_marker(path) is False

    def test_syntax_error_is_not_marker(self, tmp_path: Path) -> None:
        """Unparseable bodies fall through to ``UNKNOWN``.

        A broken ``__init__.py`` should not be silently classified as
        harmless; the conservative default keeps the diagnostic loud.
        """
        path = tmp_path / "__init__.py"
        path.write_text("def broken(:\n    pass\n")
        assert is_empty_package_marker(path) is False

    def test_missing_file_is_not_marker(self, tmp_path: Path) -> None:
        """The helper does not raise on a missing file; it returns False."""
        path = tmp_path / "__init__.py"
        # Don't create it.
        assert is_empty_package_marker(path) is False


# ---------------------------------------------------------------------------
# S0maProject.discover() integration: package_markers parsing
# ---------------------------------------------------------------------------


def _write_pyproject(
    root: Path, *, project_name: str = "fakeproj", tool_s0ma: str = ""
) -> Path:
    """Write a minimal ``pyproject.toml`` rooted at *root*.

    Mirrors ``tests/test_project_discovery.py``'s helper of the same
    name so the two suites stay aligned on input shape.
    """
    body = dedent(
        f"""
        [project]
        name = "{project_name}"
        version = "0.1.0"
        """
    ).lstrip()
    body += "\n[tool.s0ma]\n" + tool_s0ma + "\n"
    pyproject = root / "pyproject.toml"
    pyproject.write_text(body)
    return pyproject


class TestPackageMarkersProjectModel:
    """Pin the project-load-time semantics of ``[tool.s0ma].package_markers``."""

    def test_default_is_empty_tuple(self, tmp_path: Path) -> None:
        """Omitting the key yields the empty tuple, not ``None``."""
        _write_pyproject(tmp_path)
        project = S0maProject.discover(tmp_path)
        assert project.package_markers == ()

    def test_resolved_to_absolute_paths(self, tmp_path: Path) -> None:
        """Every entry resolves to an absolute :class:`Path`."""
        src = tmp_path / "src" / "myproj"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        _write_pyproject(
            tmp_path,
            tool_s0ma=dedent(
                """
                package_markers = ["src/myproj/__init__.py"]
                """
            ).strip(),
        )
        project = S0maProject.discover(tmp_path)
        expected = (tmp_path / "src" / "myproj" / "__init__.py").resolve()
        assert expected in project.package_markers
        assert all(p.is_absolute() for p in project.package_markers)

    def test_missing_on_disk_surfaces_warning(self, tmp_path: Path) -> None:
        """Declared markers that do not exist surface as warnings, not errors.

        Mirrors the existing accommodation for ``bootstrap_files`` so a
        fresh project can declare entries before scaffolding.
        """
        _write_pyproject(
            tmp_path,
            tool_s0ma=dedent(
                """
                package_markers = ["src/myproj/__init__.py"]
                """
            ).strip(),
        )
        project = S0maProject.discover(tmp_path)
        assert any(
            "package_marker" in w.lower() for w in project.warnings
        ), project.warnings

    def test_non_list_value_raises(self, tmp_path: Path) -> None:
        """Type-mismatched ``package_markers`` raises a friendly error."""
        _write_pyproject(
            tmp_path,
            tool_s0ma=dedent(
                """
                package_markers = "src/myproj/__init__.py"
                """
            ).strip(),
        )
        with pytest.raises(ValueError) as exc_info:
            S0maProject.discover(tmp_path)
        assert "package_markers" in str(exc_info.value)


class TestConflictingPackageDeclaration:
    """G1: a file in both lists is a load-time error in every mode."""

    def test_conflict_raises(self, tmp_path: Path) -> None:
        """Same file under both lists → ``CONFLICTING_PACKAGE_DECLARATION``.

        The error fires at ``S0maProject.discover`` time so the
        diagnostic surfaces before any subcommand runs.
        """
        src = tmp_path / "src" / "myproj"
        src.mkdir(parents=True)
        init_py = src / "__init__.py"
        init_py.write_text("")
        _write_pyproject(
            tmp_path,
            tool_s0ma=dedent(
                """
                bootstrap_files = ["src/myproj/__init__.py"]
                package_markers = ["src/myproj/__init__.py"]
                """
            ).strip(),
        )
        with pytest.raises(ValueError) as exc_info:
            S0maProject.discover(tmp_path)
        msg = str(exc_info.value)
        assert "CONFLICTING_PACKAGE_DECLARATION" in msg
        assert "src/myproj/__init__.py" in msg or str(init_py.resolve()) in msg
        # The error must name BOTH lists so the remediation is unambiguous.
        assert "bootstrap_files" in msg
        assert "package_markers" in msg

    def test_no_conflict_when_lists_are_disjoint(self, tmp_path: Path) -> None:
        """Disjoint lists discover cleanly."""
        src = tmp_path / "src" / "myproj"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text("# bootstrap\n")
        _write_pyproject(
            tmp_path,
            tool_s0ma=dedent(
                """
                bootstrap_files = ["src/myproj/main.py"]
                package_markers = ["src/myproj/__init__.py"]
                """
            ).strip(),
        )
        project = S0maProject.discover(tmp_path)  # no raise
        assert any(
            p.name == "__init__.py" for p in project.package_markers
        )
        assert any(
            p.name == "main.py" for p in project.bootstrap_files
        )


# ---------------------------------------------------------------------------
# `s0ma verify` integration with the fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def cli() -> S0maCLI:
    return S0maCLI()


def _verify_json(
    cli: S0maCLI,
    project_root: Path,
    target: Path,
    capsys: pytest.CaptureFixture[str],
) -> list[dict]:
    """Run ``s0ma verify --format json`` and return the parsed rows."""
    capsys.readouterr()  # drain
    rc = cli.run(
        [
            "--project-root",
            str(project_root),
            "verify",
            str(target),
            "--format",
            "json",
        ]
    )
    # Pilot01: every target this helper is used on carries zero checked
    # rows (markers / unknowns only), so verify exits
    # EXIT_NOTHING_VERIFIED rather than a vacuous success.
    assert rc == EXIT_NOTHING_VERIFIED
    return json.loads(capsys.readouterr().out)


class TestVerifyAutoClassifiesEmptyInit:
    """G1: empty / docstring-only ``__init__.py`` → ``PACKAGE_MARKER``."""

    def test_empty_init_auto_classified(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The fixture's empty ``__init__.py`` files surface as PACKAGE_MARKER."""
        rows = _verify_json(
            cli,
            FIXTURE,
            FIXTURE / "src" / "sample_pkg" / "empty_layer" / "__init__.py",
            capsys,
        )
        assert {row["status"] for row in rows} == {
            "PACKAGE_MARKER", "HOLLOW_MODEL",
        }
        row = next(row for row in rows if row["status"] == "PACKAGE_MARKER")
        assert row["status"] == "PACKAGE_MARKER", row
        assert "auto-classified" in row["detail"]
        assert "__init__.py" in row["detail"]

    def test_docstring_only_init_auto_classified(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The fixture's docstring-only ``__init__.py`` is PACKAGE_MARKER."""
        rows = _verify_json(
            cli,
            FIXTURE,
            FIXTURE / "src" / "sample_pkg" / "docstring_layer" / "__init__.py",
            capsys,
        )
        assert {row["status"] for row in rows} == {
            "PACKAGE_MARKER", "HOLLOW_MODEL",
        }


class TestVerifyDunderAllInit:
    """G1: ``__all__``-bearing ``__init__.py`` honours the declarative split."""

    def test_init_with_dunder_all_not_auto_classified(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An undeclared ``__init__.py`` with ``__all__`` is UNKNOWN.

        The auto-classifier's structural rule rejects re-exports, so
        the file falls through to ``UNKNOWN`` with the M11
        remediation that names both available fixes.
        """
        rows = _verify_json(
            cli,
            FIXTURE,
            FIXTURE / "src" / "sample_pkg" / "undeclared_layer" / "__init__.py",
            capsys,
        )
        assert {row["status"] for row in rows} == {"UNKNOWN", "HOLLOW_MODEL"}
        row = next(row for row in rows if row["status"] == "UNKNOWN")
        assert row["status"] == "UNKNOWN", row
        assert "[tool.s0ma].bootstrap_files" in row["detail"]

    def test_explicit_package_markers_override_unknown(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A declared ``__init__.py`` carrying ``__all__`` is PACKAGE_MARKER.

        Explicit declaration wins over auto-detection: the file's body
        has executable content (``import``, ``__all__``) but the
        author has acknowledged it as a marker via
        ``[tool.s0ma].package_markers``.
        """
        rows = _verify_json(
            cli,
            FIXTURE,
            FIXTURE / "src" / "sample_pkg" / "declared_layer" / "__init__.py",
            capsys,
        )
        assert {row["status"] for row in rows} == {
            "PACKAGE_MARKER", "HOLLOW_MODEL",
        }
        row = next(row for row in rows if row["status"] == "PACKAGE_MARKER")
        assert row["status"] == "PACKAGE_MARKER", row
        assert "package_markers" in row["detail"]


class TestVerifyDefaultOutputHidesPackageMarker:
    """G1: ``PACKAGE_MARKER`` rows are hidden under default verbosity.

    Mirrors the M11 ``BOOTSTRAP`` policy: package markers are
    informational, so the default text output keeps the noise floor at
    zero. They surface only under ``--verbose``.
    """

    def test_package_marker_hidden_from_default_verify_output(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Default text output omits per-file PACKAGE_MARKER rows.

        The default summary footer also omits the package-marker count
        (it stays ``OK / BOOTSTRAP / UNKNOWN``); ``--verbose`` re
        introduces the count alongside the per-file rows.
        """
        capsys.readouterr()
        rc = cli.run(
            [
                "--project-root",
                str(FIXTURE),
                "verify",
                str(FIXTURE / "src" / "sample_pkg"),
            ]
        )
        # Pilot01: the fixture tree has zero checked rows -> exit 4.
        assert rc == EXIT_NOTHING_VERIFIED
        out = capsys.readouterr().out

        # No per-file PACKAGE_MARKER row at default verbosity.
        for line in out.splitlines():
            if line.lstrip().startswith("PACKAGE_MARKER "):
                pytest.fail(
                    f"Default verify output should not show PACKAGE_MARKER "
                    f"rows; got: {line!r}"
                )

        # The default summary footer omits the package-marker count.
        assert "package marker" not in out.lower(), out

    def test_package_marker_shown_under_verbose(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--verbose`` re-introduces PACKAGE_MARKER rows + summary count."""
        capsys.readouterr()
        rc = cli.run(
            [
                "--project-root",
                str(FIXTURE),
                "verify",
                str(FIXTURE / "src" / "sample_pkg"),
                "--verbose",
            ]
        )
        # Pilot01: the fixture tree has zero checked rows -> exit 4.
        assert rc == EXIT_NOTHING_VERIFIED
        out = capsys.readouterr().out

        marker_lines = [
            line
            for line in out.splitlines()
            if line.lstrip().startswith("PACKAGE_MARKER ")
        ]
        # The fixture has three PACKAGE_MARKER files: the top-level
        # __init__.py (empty), empty_layer/__init__.py (empty),
        # docstring_layer/__init__.py (docstring), and the declared
        # declared_layer/__init__.py — four rows total.
        assert len(marker_lines) >= 3, (
            f"--verbose should surface every PACKAGE_MARKER row; got: "
            f"{marker_lines!r}"
        )

        # Verbose summary footer carries the package-marker count.
        assert "package marker(s)" in out

    def test_package_marker_shown_under_all_flag(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--all`` is a synonym for ``--verbose`` on the verify surface.

        G1 spec: PACKAGE_MARKER count "is shown only with `--verbose`
        or `--all`." Either flag opts into the full informational
        rendering (per-file rows + extended summary footer).
        """
        capsys.readouterr()
        rc = cli.run(
            [
                "--project-root",
                str(FIXTURE),
                "verify",
                str(FIXTURE / "src" / "sample_pkg"),
                "--all",
            ]
        )
        # Pilot01: the fixture tree has zero checked rows -> exit 4.
        assert rc == EXIT_NOTHING_VERIFIED
        out = capsys.readouterr().out

        marker_lines = [
            line
            for line in out.splitlines()
            if line.lstrip().startswith("PACKAGE_MARKER ")
        ]
        assert len(marker_lines) >= 3, (
            f"--all should surface every PACKAGE_MARKER row (synonym "
            f"for --verbose); got: {marker_lines!r}"
        )
        assert "package marker(s)" in out

    def test_differing_reasons_stay_on_their_own_rows(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A status whose rows say different things is not collapsed.

        ``s0ma verify`` says a repeated explanation once, under the list,
        rather than after every row — but only when it really is the same
        explanation. This fixture holds both kinds of package marker, the
        declared one and the auto-classified ones, and a reader cannot
        tell which is which from the file name. So each row keeps its own
        reason, and no single hoisted ``PACKAGE_MARKER`` note appears in
        place of them.
        """
        capsys.readouterr()
        rc = cli.run(
            [
                "--project-root",
                str(FIXTURE),
                "verify",
                str(FIXTURE / "src" / "sample_pkg"),
                "--all",
            ]
        )
        assert rc == EXIT_NOTHING_VERIFIED
        lines = capsys.readouterr().out.splitlines()

        reasons = {
            ln.strip()
            for index, ln in enumerate(lines)
            if index and lines[index - 1].lstrip().startswith("PACKAGE_MARKER ")
            if ln.startswith("           (")
        }
        assert len(reasons) == 2, reasons
        assert any("declared under" in reason for reason in reasons), reasons
        assert any("auto-classified" in reason for reason in reasons), reasons
        assert [ln for ln in lines if ln.startswith("PACKAGE_MARKER (")] == []

        # The repeated one on the same screen is still collapsed.
        assert [ln for ln in lines if ln.startswith("UNKNOWN (")] != []


# ---------------------------------------------------------------------------
# Doc-consistency cross-reference for the new error code
# ---------------------------------------------------------------------------


class TestPep561TypedMarker:
    """DSL-M5 (0.8.0): s0ma-dsl ships the PEP 561 ``py.typed`` marker.

    The package reached ``mypy --strict`` cleanliness in DSL-M5, so it
    now advertises inline types to downstream consumers (the marker
    rides the wheel via hatchling's default packaging — same mechanism
    s0ma-core uses since 0.7.0). This pins the marker's presence so a
    future packaging refactor cannot silently drop it and quietly
    regress every strict downstream (s0ma-mcp's gate stands on this).
    """

    def test_py_typed_marker_present(self) -> None:
        """``src/s0ma_dsl/py.typed`` exists beside the package source."""
        import s0ma_dsl

        pkg_dir = Path(s0ma_dsl.__file__).resolve().parent
        marker = pkg_dir / "py.typed"
        assert marker.is_file(), (
            f"PEP 561 marker missing: {marker}. s0ma-dsl is strict-clean "
            f"since 0.8.0 (DSL-M5) and must ship py.typed so downstream "
            f"strict gates see its real types."
        )


class TestDocConsistencyConflictingPackageDeclaration:
    """G1: ``CONFLICTING_PACKAGE_DECLARATION`` is registered in the spec.

    ``tests/test_doc_consistency.py`` already enforces the matrix-wide
    invariant. This test pins the new code's traceability row
    explicitly so a future ``SEVERITY_MATRIX`` refactor (or a
    re-organisation of ``package_markers`` enforcement) cannot drop
    the row without surfacing the gap.
    """

    def test_doc_consistency_pins_conflicting_package_declaration(
        self,
    ) -> None:
        """The error code must appear in ``docs/spec_traceability.md``."""
        repo_root = Path(__file__).resolve().parent.parent
        text = (repo_root / "docs" / "spec_traceability.md").read_text(
            encoding="utf-8"
        )
        assert "`CONFLICTING_PACKAGE_DECLARATION`" in text, (
            "CONFLICTING_PACKAGE_DECLARATION (added in G1 for the "
            "[tool.s0ma].package_markers escape hatch) must appear in "
            "docs/spec_traceability.md so future contributors can trace "
            "the rule to its implementation. See feedback_5-6 cleanup "
            "plan G1 for the surrounding context."
        )
