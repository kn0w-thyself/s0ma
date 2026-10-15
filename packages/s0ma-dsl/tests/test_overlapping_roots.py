"""G2 (feedback 5–6 cleanup) — pre-flight ``OVERLAPPING_DISCOVERY_ROOTS``.

Pins the project-load-time overlap detector that surfaces structural
ambiguity in ``[tool.s0ma].source_roots`` / ``[tool.s0ma].test_roots``
*before* any subcommand runs. Without G2 the same ``.s0ma`` files
were discovered twice (once per overlapping anchor), the cross-module
resolver registered each ``module <name>`` declaration twice, and the
author saw an opaque ``MODULE_NAME_COLLISION`` against a file
colliding with itself — several command invocations downstream from
the actual mistake.

Locks down:

- ``_detect_overlapping_roots`` returns the right triples for every
  overlap shape (source-source, test-test, source-test) including
  identity (same path declared in two roots).
- ``S0maProject._from_tool_s0ma`` raises ``ValueError`` whose message
  starts with the ``OVERLAPPING_DISCOVERY_ROOTS:`` prefix and names
  both offending paths plus the two clean-config remediation options.
- The disjoint case loads cleanly (control test).
- Multiple offending pairs at once surface together (one diagnostic
  with every pair, not one diagnostic per edit-rerun cycle).
- Deeply nested overlap is detected the same way as shallow nesting.
- ``OVERLAPPING_DISCOVERY_ROOTS`` is registered in ``SEVERITY_MATRIX``
  with ``error`` severity in every strictness mode (the meta-test
  ``test_error_codes_in_traceability`` already pins traceability).

Pairs with ``tests/test_project_discovery.py`` (M1 ``[tool.s0ma]``
schema) and ``tests/test_package_markers.py`` (G1's load-time
``CONFLICTING_PACKAGE_DECLARATION`` is the structural sibling of this
diagnostic).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from s0ma_dsl.config import SEVERITY_MATRIX, StrictnessMode
from s0ma_dsl.project import (
    S0maProject,
    _detect_overlapping_roots,
    _render_root_for_diagnostic,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "overlapping_roots"


# ---------------------------------------------------------------------------
# Unit tests for the detector — no pyproject.toml, just the helper.
# ---------------------------------------------------------------------------


class TestDetectOverlappingRoots:
    """Unit tests for ``_detect_overlapping_roots`` over absolute paths."""

    def test_disjoint_roots_return_empty_list(self, tmp_path: Path) -> None:
        """Top-level peer src / tests directories produce no overlaps."""
        src = (tmp_path / "src").resolve()
        tests = (tmp_path / "tests").resolve()
        result = _detect_overlapping_roots((src,), (tests,))
        assert result == []

    def test_test_nested_under_source_returns_source_test(self, tmp_path: Path) -> None:
        """The kn0wthyself-website-2 shape: ``src/<proj>/tests`` under ``src/<proj>``."""
        src = (tmp_path / "src" / "myproject").resolve()
        tests = (tmp_path / "src" / "myproject" / "tests").resolve()
        result = _detect_overlapping_roots((src,), (tests,))
        assert len(result) == 1
        a, b, kind = result[0]
        assert kind == "source-test"
        assert {a, b} == {src, tests}

    def test_source_nested_under_test_returns_source_test(self, tmp_path: Path) -> None:
        """The opposite-direction overlap is detected the same way."""
        tests = (tmp_path / "tests").resolve()
        src = (tmp_path / "tests" / "myproject" / "src").resolve()
        result = _detect_overlapping_roots((src,), (tests,))
        assert len(result) == 1
        a, b, kind = result[0]
        assert kind == "source-test"
        assert {a, b} == {src, tests}

    def test_identical_source_and_test_path_returns_source_test(
        self, tmp_path: Path
    ) -> None:
        """The same path declared in both lists is overlap (identity)."""
        same = (tmp_path / "src").resolve()
        result = _detect_overlapping_roots((same,), (same,))
        assert len(result) == 1
        a, b, kind = result[0]
        assert kind == "source-test"
        assert a == same and b == same

    def test_two_source_roots_overlap_returns_source_source(
        self, tmp_path: Path
    ) -> None:
        """``source_roots = [\"src\", \"src/myproject\"]`` is an overlap."""
        outer = (tmp_path / "src").resolve()
        inner = (tmp_path / "src" / "myproject").resolve()
        result = _detect_overlapping_roots((outer, inner), ())
        assert len(result) == 1
        a, b, kind = result[0]
        assert kind == "source-source"
        # The pair is preserved in declaration order.
        assert a == outer and b == inner

    def test_two_test_roots_overlap_returns_test_test(self, tmp_path: Path) -> None:
        """Mirrored case for the test list."""
        outer = (tmp_path / "tests").resolve()
        inner = (tmp_path / "tests" / "integration").resolve()
        result = _detect_overlapping_roots((), (outer, inner))
        assert len(result) == 1
        a, b, kind = result[0]
        assert kind == "test-test"
        assert a == outer and b == inner

    def test_deeply_nested_overlap_detected(self, tmp_path: Path) -> None:
        """Many directory levels between enclosing and enclosed roots."""
        src = (tmp_path / "src").resolve()
        tests = (tmp_path / "src" / "a" / "b" / "c" / "d" / "e" / "tests").resolve()
        result = _detect_overlapping_roots((src,), (tests,))
        assert len(result) == 1
        _, _, kind = result[0]
        assert kind == "source-test"

    def test_multiple_overlaps_returned_together(self, tmp_path: Path) -> None:
        """Several offending pairs at once surface in a single result."""
        src1 = (tmp_path / "src").resolve()
        src2 = (tmp_path / "src" / "myproject").resolve()
        tests = (tmp_path / "src" / "myproject" / "tests").resolve()
        result = _detect_overlapping_roots((src1, src2), (tests,))
        # Three offending pairs:
        #   1. src1 vs src2                   (source-source)
        #   2. src1 vs tests                  (source-test)
        #   3. src2 vs tests                  (source-test)
        kinds = sorted(triple[2] for triple in result)
        assert kinds == ["source-source", "source-test", "source-test"]
        assert len(result) == 3

    def test_disjoint_subtrees_under_common_parent_do_not_overlap(
        self, tmp_path: Path
    ) -> None:
        """``src`` and ``tests`` under the same project root are not overlap.

        ``src`` is not a subpath of ``tests`` and vice versa; they
        share an ancestor but neither contains the other.
        """
        src = (tmp_path / "src").resolve()
        tests = (tmp_path / "tests").resolve()
        result = _detect_overlapping_roots((src,), (tests,))
        assert result == []

    def test_sibling_layer_subdirs_under_same_source_do_not_overlap(
        self, tmp_path: Path
    ) -> None:
        """Two source_roots at peer subdirectory level are disjoint."""
        a = (tmp_path / "src" / "application").resolve()
        b = (tmp_path / "src" / "domain").resolve()
        result = _detect_overlapping_roots((a, b), ())
        assert result == []

    def test_paths_with_trailing_separators_resolve_consistently(
        self, tmp_path: Path
    ) -> None:
        """``Path('src/').resolve()`` strips the trailing slash; equality holds."""
        src1 = (tmp_path / "src/").resolve()
        src2 = (tmp_path / "src").resolve()
        # Same Path after resolve, so the same-path detector triggers.
        result = _detect_overlapping_roots((src1,), (src2,))
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Integration tests — full project load with each fixture.
# ---------------------------------------------------------------------------


class TestProjectLoadOverlapDiagnostic:
    """``S0maProject.discover`` raises with the right message for each shape."""

    def test_test_root_nested_under_source_root_errors(self) -> None:
        """The kn0wthyself-website-2 shape produces ``OVERLAPPING_DISCOVERY_ROOTS``.

        Pre-G2 this discovered every test file twice and the
        cross-module resolver fired ``MODULE_NAME_COLLISION`` against
        the file colliding with itself. Post-G2 it raises at project-
        load time before any subcommand runs.
        """
        fixture = FIXTURE_ROOT / "test_under_source"
        with pytest.raises(ValueError, match="OVERLAPPING_DISCOVERY_ROOTS"):
            S0maProject.discover(fixture)

    def test_source_root_nested_under_test_root_errors(self) -> None:
        """Opposite-direction nesting is detected the same way."""
        fixture = FIXTURE_ROOT / "source_under_test"
        with pytest.raises(ValueError, match="OVERLAPPING_DISCOVERY_ROOTS"):
            S0maProject.discover(fixture)

    def test_identical_source_and_test_root_errors(self) -> None:
        """Same path in both lists is the identity-equality case."""
        fixture = FIXTURE_ROOT / "identical_roots"
        with pytest.raises(ValueError, match="OVERLAPPING_DISCOVERY_ROOTS"):
            S0maProject.discover(fixture)

    def test_two_source_roots_overlap_errors(self) -> None:
        """``source_roots = [\"src\", \"src/myproject\"]`` is rejected."""
        fixture = FIXTURE_ROOT / "source_source_overlap"
        with pytest.raises(ValueError, match="OVERLAPPING_DISCOVERY_ROOTS"):
            S0maProject.discover(fixture)

    def test_two_test_roots_overlap_errors(self) -> None:
        """``test_roots = [\"tests\", \"tests/integration\"]`` is rejected."""
        fixture = FIXTURE_ROOT / "test_test_overlap"
        with pytest.raises(ValueError, match="OVERLAPPING_DISCOVERY_ROOTS"):
            S0maProject.discover(fixture)

    def test_disjoint_roots_load_cleanly(self) -> None:
        """Control case: top-level peer src/tests load without error."""
        fixture = FIXTURE_ROOT / "disjoint"
        project = S0maProject.discover(fixture)
        assert project.project_name == "disjoint"
        assert len(project.source_roots) == 1
        assert project.source_roots[0].name == "src"
        assert len(project.test_roots) == 1
        assert project.test_roots[0].name == "tests"

    def test_deeply_nested_overlap_errors(self) -> None:
        """Many directory levels between enclosing and enclosed root."""
        fixture = FIXTURE_ROOT / "deeply_nested"
        with pytest.raises(ValueError, match="OVERLAPPING_DISCOVERY_ROOTS"):
            S0maProject.discover(fixture)


# ---------------------------------------------------------------------------
# Diagnostic message shape — names paths, names remediation.
# ---------------------------------------------------------------------------


class TestErrorMessageShape:
    """Pin the exact prose so future contributors cannot degrade the diagnostic."""

    def test_overlapping_roots_error_message_names_offending_paths(self) -> None:
        """Both offending paths must appear in the error message.

        The pre-G2 failure mode was opaque (``MODULE_NAME_COLLISION``
        against a file colliding with itself, no mention of the
        roots). The G2 contract is the opposite — the user reads the
        diagnostic and immediately sees which two paths are the
        problem.
        """
        fixture = FIXTURE_ROOT / "test_under_source"
        with pytest.raises(ValueError) as exc_info:
            S0maProject.discover(fixture)
        msg = str(exc_info.value)
        assert "OVERLAPPING_DISCOVERY_ROOTS" in msg
        # The fixture's source_roots and test_roots each appear in the
        # diagnostic rendered relative to the project root with POSIX
        # separators on every OS (W-2). We do not pin the exact
        # rendering style (single-quote vs backtick) but both paths
        # MUST appear so the user can identify the pair without
        # re-reading their pyproject.toml.
        assert "src/myproject" in msg
        assert "src/myproject/tests" in msg

    def test_overlapping_roots_error_message_names_remediation(self) -> None:
        """The two clean-config options must appear in the error message."""
        fixture = FIXTURE_ROOT / "test_under_source"
        with pytest.raises(ValueError) as exc_info:
            S0maProject.discover(fixture)
        msg = str(exc_info.value)
        # Option 1: move tests outside the source root.
        assert "test_roots = [\"tests\"]" in msg
        # Option 2: narrow source_roots to disjoint layer subdirs.
        # We pin the keyword "source_roots" appears in a remediation
        # context (the message mentions narrowing to disjoint
        # subdirectories).
        assert "source_roots" in msg
        assert "disjoint layer subdirectories" in msg

    def test_multiple_overlaps_all_surface_in_one_diagnostic(self) -> None:
        """Several offending pairs at once must all be named in the message.

        Surfacing one pair at a time would force the author through
        several edit-rerun cycles. The G2 contract is "every pair
        named in a single diagnostic so the author sees the full
        picture on the first try."
        """
        fixture = FIXTURE_ROOT / "multiple_overlaps"
        with pytest.raises(ValueError) as exc_info:
            S0maProject.discover(fixture)
        msg = str(exc_info.value)
        # ``source_roots = [\"src\", \"src/myproject\"]`` overlaps internally
        # AND ``test_roots = [\"src/myproject/tests\"]`` overlaps with
        # both source_roots — three offending pairs total. Every
        # path must appear in the message.
        assert "OVERLAPPING_DISCOVERY_ROOTS" in msg
        assert "src/myproject" in msg
        assert "src/myproject/tests" in msg
        # The ``src`` root must also be named — it is the enclosing
        # path of two overlap pairs.
        assert (
            "/src`" in msg
            or "/src'" in msg
            or "/src\n" in msg
            or "`src`" in msg
            or msg.count("/src") >= 2
        )

    def test_diagnostic_kind_label_appears_in_message(self) -> None:
        """The triple's kind label (source-source / source-test / test-test) shows up.

        The kind label tells the author which pair-shape is broken at
        a glance — useful in the multi-overlap case where the same
        path appears in several pairs with different kinds.
        """
        fixture = FIXTURE_ROOT / "source_source_overlap"
        with pytest.raises(ValueError) as exc_info:
            S0maProject.discover(fixture)
        msg = str(exc_info.value)
        assert "source-source" in msg


# ---------------------------------------------------------------------------
# Severity matrix registration — pin the matrix-level invariant.
# ---------------------------------------------------------------------------


class TestSeverityMatrixRegistration:
    """``OVERLAPPING_DISCOVERY_ROOTS`` is in ``SEVERITY_MATRIX`` with the right shape."""

    def test_overlapping_discovery_roots_in_severity_matrix(self) -> None:
        """The error code is registered (so the doc-consistency
        traceability meta-test ``test_error_codes_in_traceability``
        will catch a missing traceability row)."""
        assert "OVERLAPPING_DISCOVERY_ROOTS" in SEVERITY_MATRIX

    def test_overlapping_discovery_roots_is_error_in_every_mode(self) -> None:
        """Structural project-model violation — error in every strictness mode."""
        row = SEVERITY_MATRIX["OVERLAPPING_DISCOVERY_ROOTS"]
        for mode in StrictnessMode:
            assert row[mode] == "error", (
                f"OVERLAPPING_DISCOVERY_ROOTS must be 'error' in every mode "
                f"(structural configuration violation); got {row[mode]!r} for "
                f"{mode.value}."
            )


class TestDiagnosticPathRendering:
    """W-2 (Windows plan M2): roots render relative + POSIX on every OS.

    ``_render_root_for_diagnostic`` is the formatting site for the
    ``OVERLAPPING_DISCOVERY_ROOTS`` message. PurePath inputs let the
    native-Windows-separator case run on POSIX CI and vice versa, so
    both the ``/``-input and native-input paths are asserted everywhere.
    """

    def test_posix_inputs_render_relative_posix(self) -> None:
        root = PurePosixPath("/work/proj")
        nested = PurePosixPath("/work/proj/src/myproject")
        assert _render_root_for_diagnostic(nested, root) == "src/myproject"

    def test_windows_native_inputs_render_relative_posix(self) -> None:
        root = PureWindowsPath(r"C:\work\proj")
        nested = PureWindowsPath(r"C:\work\proj\src\myproject")
        assert _render_root_for_diagnostic(nested, root) == "src/myproject"

    def test_root_outside_project_stays_native_absolute(self) -> None:
        # W-2: absolute paths (the user's own machine) stay native.
        root = PureWindowsPath(r"C:\work\proj")
        outside = PureWindowsPath(r"C:\shared\src")
        assert _render_root_for_diagnostic(outside, root) == str(outside)

    def test_posix_root_outside_project_stays_native_absolute(self) -> None:
        root = PurePosixPath("/work/proj")
        outside = PurePosixPath("/shared/src")
        assert _render_root_for_diagnostic(outside, root) == "/shared/src"

    def test_project_root_itself_renders_as_dot(self) -> None:
        root = PurePosixPath("/work/proj")
        assert _render_root_for_diagnostic(root, root) == "."
