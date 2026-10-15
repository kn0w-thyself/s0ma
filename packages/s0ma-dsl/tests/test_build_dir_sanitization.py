"""G3 (feedback 5–6 cleanup) — sanitize non-identifier characters in default ``build_dir``.

Pins the project-load-time sanitizer that turns hyphens, dots, spaces, and
other non-word characters in ``[project].name`` into underscores when
deriving the default ``[tool.s0ma].build_dir``, and surfaces irrecoverable
shapes (digit-start, sanitized-to-empty) loudly at project-load time via
``INVALID_PROJECT_NAME_FOR_BUILD_DIR``. Without G3, a project with a
hyphenated name silently produced an un-importable build directory: the
transpile succeeded, the artifacts landed on disk, and the runtime bridge
failed with ``ModuleNotFoundError`` only when consumers wired it up
(the kn0wthyself-website-2 shape from M20 finding #5).

Locks down:

- ``_default_build_dir`` sanitizes hyphens / dots / spaces / exclamation
  marks to underscores and produces a valid Python identifier appended
  with ``_build``.
- ``_default_build_dir`` raises ``ValueError`` whose message starts with
  the ``INVALID_PROJECT_NAME_FOR_BUILD_DIR:`` prefix for irrecoverable
  shapes (digit-start, empty-after-sanitize) and instructs the author to
  set ``[tool.s0ma].build_dir`` explicitly.
- ``S0maProject._from_tool_s0ma`` validates explicit ``build_dir`` values
  too — the directory's last path component (the importable basename)
  must be a valid Python identifier; ``out/foo_bar`` is fine,
  ``out/foo-bar`` is not.
- The single-underscore edge case (``_``) is accepted and produces
  ``__build`` (valid identifier, unusual but not blocked).
- ``INVALID_PROJECT_NAME_FOR_BUILD_DIR`` is registered in
  ``SEVERITY_MATRIX`` with ``error`` severity in every strictness mode
  (the meta-test ``test_error_codes_in_traceability`` already pins the
  traceability row).
- The end-to-end importability contract: a hyphenated project name's
  default ``build_dir`` is produced, ``s0ma build`` lands artifacts in
  it, and a fresh Python interpreter can import the module via
  ``from <sanitized>_build import <module>``.

Pairs with ``tests/test_overlapping_roots.py`` (G2's project-load-time
``OVERLAPPING_DISCOVERY_ROOTS`` is the structural sibling of G3's
``INVALID_PROJECT_NAME_FOR_BUILD_DIR``) and
``tests/test_package_markers.py`` (G1's load-time
``CONFLICTING_PACKAGE_DECLARATION``).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from s0ma_dsl.config import SEVERITY_MATRIX, StrictnessMode
from s0ma_dsl.project import S0maProject, _default_build_dir

FIXTURE = Path(__file__).parent / "fixtures" / "hyphenated_project_name"


# ---------------------------------------------------------------------------
# Unit tests for the sanitizer — no pyproject.toml, just the helper.
# ---------------------------------------------------------------------------


class TestDefaultBuildDirSanitizer:
    """Unit tests for ``_default_build_dir`` covering every documented edge."""

    def test_hyphen_in_project_name_sanitized(self) -> None:
        """``foo-bar-baz`` → ``foo_bar_baz_build`` (the kn0wthyself-website-2 shape)."""
        assert _default_build_dir("foo-bar-baz") == "foo_bar_baz_build"

    def test_dot_in_project_name_sanitized(self) -> None:
        """``foo.bar`` → ``foo_bar_build``.

        PEP 426 allowed dots; PEP 503 normalises them away but the
        dot can survive into ``[project].name`` on legacy projects.
        """
        assert _default_build_dir("foo.bar") == "foo_bar_build"

    def test_space_in_project_name_sanitized(self) -> None:
        """``foo bar`` (embedded space) → ``foo_bar_build``."""
        assert _default_build_dir("foo bar") == "foo_bar_build"

    def test_exclamation_in_project_name_sanitized(self) -> None:
        """``foo!bar`` → ``foo_bar_build``. ``\\W`` covers every non-word ASCII (and Unicode)."""
        assert _default_build_dir("foo!bar") == "foo_bar_build"

    def test_already_valid_identifier_passes_through(self) -> None:
        """``foo_bar`` is already valid; the helper appends ``_build`` without re-sanitizing."""
        assert _default_build_dir("foo_bar") == "foo_bar_build"

    def test_single_underscore_accepted(self) -> None:
        """``_`` is a valid Python identifier; the helper returns ``__build`` (valid, unusual)."""
        assert _default_build_dir("_") == "__build"

    def test_digit_start_project_name_errors(self) -> None:
        """``123foo`` → ``INVALID_PROJECT_NAME_FOR_BUILD_DIR``. Underscoring does not help.

        The sanitizer's substitution rule is ``\\W → _``; the digits are
        word characters and survive, leaving the result ``123foo`` (or
        ``"123_foo_"`` for ``123-foo-`` etc.) — neither is a valid Python
        identifier because identifiers cannot start with a digit.
        """
        with pytest.raises(ValueError, match="INVALID_PROJECT_NAME_FOR_BUILD_DIR"):
            _default_build_dir("123foo")

    def test_digit_start_after_sanitization_errors(self) -> None:
        """``123-foo`` (sanitizes to ``123_foo``, still digit-start) → error."""
        with pytest.raises(ValueError, match="INVALID_PROJECT_NAME_FOR_BUILD_DIR"):
            _default_build_dir("123-foo")

    def test_empty_project_name_errors(self) -> None:
        """Empty name → error (defensive — PEP 621 requires non-empty names)."""
        with pytest.raises(ValueError, match="INVALID_PROJECT_NAME_FOR_BUILD_DIR"):
            _default_build_dir("")

    def test_only_punctuation_sanitizes_to_underscores_and_passes(self) -> None:
        """``---`` sanitizes to ``___`` (three underscores, a valid identifier).

        ``___`` is silly but technically valid; the author can opt out
        with an explicit ``build_dir``. This pins the rule "any string
        whose ``\\W → _`` substitution lands on a valid identifier passes."
        """
        assert _default_build_dir("---") == "____build"

    def test_error_message_names_project_name(self) -> None:
        """The diagnostic includes the offending project name and the sanitized form."""
        with pytest.raises(ValueError) as exc_info:
            _default_build_dir("123foo")
        msg = str(exc_info.value)
        assert "123foo" in msg
        assert "INVALID_PROJECT_NAME_FOR_BUILD_DIR" in msg

    def test_error_message_names_remediation(self) -> None:
        """The diagnostic instructs the author to set ``[tool.s0ma].build_dir`` explicitly."""
        with pytest.raises(ValueError) as exc_info:
            _default_build_dir("123foo")
        msg = str(exc_info.value)
        # The remediation must mention the explicit-override key by name
        # so the author can act on the diagnostic without re-reading the
        # spec.
        assert "[tool.s0ma].build_dir" in msg
        # And it must mention "Python identifier" (or a near phrase) so
        # the author understands the contract.
        assert "Python identifier" in msg or "identifier" in msg


# ---------------------------------------------------------------------------
# Integration tests — full project load with the hyphenated fixture.
# ---------------------------------------------------------------------------


class TestProjectLoadDefaultBuildDir:
    """``S0maProject.discover`` derives the sanitized default for the fixture."""

    def test_hyphenated_project_name_sanitizes_default_build_dir(self) -> None:
        """The fixture's ``[project].name = "foo-bar-baz"`` produces ``foo_bar_baz_build/``."""
        project = S0maProject.discover(FIXTURE)
        assert project.project_name == "foo-bar-baz"
        # ``build_dir`` is absolute (resolved against project root); the
        # last-path-component (``.name`` on Path) is the importable
        # token.
        assert project.build_dir.name == "foo_bar_baz_build"

    def test_explicit_valid_build_dir_passes(self, tmp_path: Path) -> None:
        """``build_dir = "out/foo_bar"`` accepted; basename is a valid identifier."""
        # Build a minimal project under tmp_path with an explicit
        # build_dir whose final component is a valid identifier. The
        # parent path component is not the importable token so it does
        # not need to be an identifier.
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\n'
            'name = "explicitvalid"\n'
            'version = "0.0.1"\n'
            '\n'
            '[tool.s0ma]\n'
            'source_roots = ["src"]\n'
            'test_roots = ["tests"]\n'
            'build_dir = "out/foo_bar"\n',
            encoding="utf-8",
        )
        project = S0maProject.discover(tmp_path)
        # Last path component is the importable token; it must be a
        # valid identifier.
        assert project.build_dir.name == "foo_bar"

    def test_explicit_invalid_build_dir_errors(self, tmp_path: Path) -> None:
        """``build_dir = "out/foo-bar"`` errors — the basename ``foo-bar`` is not an identifier."""
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\n'
            'name = "explicitinvalid"\n'
            'version = "0.0.1"\n'
            '\n'
            '[tool.s0ma]\n'
            'source_roots = ["src"]\n'
            'test_roots = ["tests"]\n'
            'build_dir = "out/foo-bar"\n',
            encoding="utf-8",
        )
        with pytest.raises(
            ValueError, match="INVALID_PROJECT_NAME_FOR_BUILD_DIR"
        ):
            S0maProject.discover(tmp_path)

    def test_explicit_invalid_build_dir_error_names_basename(
        self, tmp_path: Path
    ) -> None:
        """The diagnostic mentions both the value-as-written and the offending basename."""
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\n'
            'name = "explicitinvalid"\n'
            'version = "0.0.1"\n'
            '\n'
            '[tool.s0ma]\n'
            'source_roots = ["src"]\n'
            'test_roots = ["tests"]\n'
            'build_dir = "out/foo-bar"\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc_info:
            S0maProject.discover(tmp_path)
        msg = str(exc_info.value)
        # Both the value as the user wrote it and the extracted basename
        # appear so the user can connect the diagnostic to their config.
        assert "out/foo-bar" in msg
        assert "foo-bar" in msg
        # And the remediation mentions the override-key by name.
        assert "[tool.s0ma].build_dir" in msg

    def test_digit_start_project_name_errors_at_load(
        self, tmp_path: Path
    ) -> None:
        """``[project].name = "123foo"`` (no explicit build_dir) errors at discovery."""
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\n'
            'name = "123foo"\n'
            'version = "0.0.1"\n'
            '\n'
            '[tool.s0ma]\n'
            'source_roots = ["src"]\n'
            'test_roots = ["tests"]\n',
            encoding="utf-8",
        )
        with pytest.raises(
            ValueError, match="INVALID_PROJECT_NAME_FOR_BUILD_DIR"
        ):
            S0maProject.discover(tmp_path)

    def test_digit_start_with_explicit_build_dir_passes(
        self, tmp_path: Path
    ) -> None:
        """A digit-start ``[project].name`` is recoverable with an explicit valid ``build_dir``.

        The plan's remediation message instructs the author to set
        ``[tool.s0ma].build_dir`` explicitly; this test pins that the
        instruction works — once the author overrides, the
        irrecoverable-by-default name does not block project load.
        """
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\n'
            'name = "123foo"\n'
            'version = "0.0.1"\n'
            '\n'
            '[tool.s0ma]\n'
            'source_roots = ["src"]\n'
            'test_roots = ["tests"]\n'
            'build_dir = "proj_123_build"\n',
            encoding="utf-8",
        )
        project = S0maProject.discover(tmp_path)
        assert project.build_dir.name == "proj_123_build"


# ---------------------------------------------------------------------------
# End-to-end importability — sanitized build_dir really is importable.
# ---------------------------------------------------------------------------


class TestSanitizedBuildDirImportable:
    """The contract: a sanitized default ``build_dir`` is import-time valid."""

    def test_sanitized_build_dir_is_importable(self, tmp_path: Path) -> None:
        """Build a hyphenated fixture and import via ``from <sanitized>_build import <module>``.

        Acceptance criterion: the M6a runtime-bridge contract holds for
        a hyphenated project name with no explicit ``build_dir`` —
        ``s0ma build`` lands artifacts in ``foo_bar_baz_build/`` (not
        ``foo-bar-baz_build/``), and a fresh Python interpreter can
        import the transpiled module.
        """
        # Stage a writeable copy of the hyphenated fixture under
        # ``tmp_path`` so the build's transpiled artifacts land in the
        # ephemeral test tree (the on-disk fixture stays read-only).
        # The default ``build_dir`` will be ``foo_bar_baz_build``
        # relative to the project root — so ``project.build_dir`` is
        # ``<tmp_path>/<project_copy>/foo_bar_baz_build``.
        import shutil

        from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI

        project_copy = tmp_path / "hyphenated_project_name"
        shutil.copytree(FIXTURE, project_copy)

        # Confirm the default derivation produces the sanitized name
        # before invoking the build (this is the load-time half of the
        # contract).
        project = S0maProject.discover(project_copy)
        assert project.build_dir.name == "foo_bar_baz_build", (
            f"expected default build_dir basename 'foo_bar_baz_build'; "
            f"got {project.build_dir.name!r}"
        )

        # Run ``s0ma build`` against the staged project. We use the
        # in-process ``S0maCLI`` here (the same pattern as
        # ``test_build_layout.py``) so error reporting goes through the
        # same path the rest of the test suite exercises.
        cli = S0maCLI()
        rc = cli.run(
            [
                "build",
                str(project_copy),
                "--output-dir",
                str(project.build_dir),
                "--mode",
                "dev",
                "--no-cache",
            ]
        )
        assert rc == EXIT_SUCCESS, "build failed for hyphenated project"
        contents = (
            list(project.build_dir.iterdir())
            if project.build_dir.exists()
            else "NO DIR"
        )
        assert (project.build_dir / "widget.py").is_file(), (
            f"expected widget.py at {project.build_dir / 'widget.py'}; "
            f"contents: {contents}"
        )

        # Import the transpiled module in a fresh interpreter via the
        # M6a contract: ``from <build_dir_basename> import <module>``.
        # The basename ``foo_bar_baz_build`` is the importable token;
        # its parent goes on ``sys.path``.
        parent_of_build = project.build_dir.parent
        code = (
            "import sys\n"
            f"sys.path.insert(0, {str(parent_of_build)!r})\n"
            "from foo_bar_baz_build import widget\n"
            "print(widget.greet('world'))\n"
        )
        import_proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert import_proc.returncode == 0, (
            f"importing sanitized build_dir failed: "
            f"stdout={import_proc.stdout!r} "
            f"stderr={import_proc.stderr!r}"
        )
        assert "hello, world" in import_proc.stdout


# ---------------------------------------------------------------------------
# Severity matrix registration — pin the matrix-level invariant.
# ---------------------------------------------------------------------------


class TestSeverityMatrixRegistration:
    """``INVALID_PROJECT_NAME_FOR_BUILD_DIR`` is in ``SEVERITY_MATRIX`` with the right shape."""

    def test_invalid_project_name_for_build_dir_in_severity_matrix(
        self,
    ) -> None:
        """The error code is registered (so the matrix-wide
        traceability meta-test ``test_error_codes_in_traceability``
        catches a missing traceability row)."""
        assert "INVALID_PROJECT_NAME_FOR_BUILD_DIR" in SEVERITY_MATRIX

    def test_invalid_project_name_for_build_dir_is_error_in_every_mode(
        self,
    ) -> None:
        """Structural project-config violation — error in every strictness mode.

        The strictness ladder cannot legitimately make a load-time
        configuration error softer than ``error``: a build directory
        that isn't a Python identifier is unimportable, so the build
        is broken in every mode.
        """
        row = SEVERITY_MATRIX["INVALID_PROJECT_NAME_FOR_BUILD_DIR"]
        for mode in StrictnessMode:
            assert row[mode] == "error", (
                f"INVALID_PROJECT_NAME_FOR_BUILD_DIR must be 'error' in "
                f"every mode (structural project-config violation); got "
                f"{row[mode]!r} for {mode.value}."
            )
