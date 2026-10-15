"""Tests for the M17 (feedback 5–6) CONSTANT_NAME_MISMATCH check.

The intra-module validator must enforce that a CONSTANT cell's
declaration name equals the Python identifier its body assigns to at
top level. The transpiler emits ``from <module> import <cell_name>``,
so a mismatch produces a runtime ``ImportError`` — silent at build,
loud at runtime. This is the canonical motivating failure from
feedback-5 MS 2 (``cell VizTemplate`` with body
``VIZ_TEMPLATE = '''...'''``).

Tests:
  - ``test_matching_constant_name_clean`` — the matching fixture
    validates clean of CONSTANT_NAME_MISMATCH.
  - ``test_mismatched_constant_name_errors`` — the mismatched fixture
    produces exactly one CONSTANT_NAME_MISMATCH error with the
    documented remediation.
  - ``test_constant_with_multiple_assignments_passes_if_any_match`` —
    a body with `_X = compute(); FOO = _X` passes when the cell name
    is `FOO`, because at least one top-level assignment matches.

See:
  - plans/feedback_5-6/feedback_5-6_plan.md, Milestone 17
  - feedback-5 MS 2 (the kn0wthyself viz_template.s0ma case)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.semantic.validator import (
    _body_top_level_assigned_names,
    validate_module,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _parse_and_validate(
    fixture_path: Path,
    *,
    mode: StrictnessMode = StrictnessMode.DEV,
):
    """Parse a fixture and run intra-module validation.

    Returns ``(module, all_diagnostics)`` where ``all_diagnostics``
    folds in both parser warnings and validator errors. Mirrors the
    pipeline order used by ``s0ma check``.
    """
    source = fixture_path.read_text(encoding="utf-8")
    module, warnings = parse_s0ma_with_warnings(
        source, str(fixture_path), mode=mode,
    )
    errors = validate_module(module, mode=mode, filename=str(fixture_path))
    return module, list(warnings) + list(errors)


class TestConstantNameMismatch:
    """The CONSTANT_NAME_MISMATCH check fires when cell name != body identifier."""

    def test_matching_constant_name_clean(self) -> None:
        """A CONSTANT cell whose name matches the body's top-level assignment
        validates clean.

        ``constant_name_match/constant_name_match.s0ma`` declares
        ``cell VIZ_TEMPLATE`` with body ``VIZ_TEMPLATE = "..."``. The
        validator must emit zero CONSTANT_NAME_MISMATCH diagnostics.
        """
        fixture = (
            _FIXTURES
            / "constant_name_match"
            / "constant_name_match.s0ma"
        )
        _, diags = _parse_and_validate(fixture)
        mismatches = [d for d in diags if d.code == "CONSTANT_NAME_MISMATCH"]
        assert mismatches == [], (
            f"matching fixture must validate clean of "
            f"CONSTANT_NAME_MISMATCH, got: "
            f"{[d.message for d in mismatches]}"
        )

    def test_mismatched_constant_name_errors(self) -> None:
        """A CONSTANT cell whose name doesn't match the body's assignment
        produces exactly one CONSTANT_NAME_MISMATCH error.

        ``constant_name_mismatch/constant_name_mismatch.s0ma`` declares
        ``cell VizTemplate`` but the body assigns to ``VIZ_TEMPLATE``
        — the canonical kn0wthyself / feedback-5 MS 2 failure mode.
        """
        fixture = (
            _FIXTURES
            / "constant_name_mismatch"
            / "constant_name_mismatch.s0ma"
        )
        _, diags = _parse_and_validate(fixture)
        mismatches = [d for d in diags if d.code == "CONSTANT_NAME_MISMATCH"]

        assert len(mismatches) == 1, (
            f"mismatched fixture must produce exactly one "
            f"CONSTANT_NAME_MISMATCH error, got: "
            f"{[d.message for d in mismatches]}"
        )
        err = mismatches[0]
        assert err.severity == "error"
        assert err.context["cell_name"] == "VizTemplate"
        assert "VIZ_TEMPLATE" in err.context["assigned_names"]
        # Remediation must surface both options the spec promises.
        assert "Rename the cell declaration" in err.remediation
        assert "VizTemplate = ..." in err.remediation

    def test_constant_with_multiple_assignments_passes_if_any_match(
        self,
    ) -> None:
        """A CONSTANT cell whose body has multiple top-level
        assignments validates clean as long as one matches the cell
        name.

        ``constant_name_multiple_assignments/...`` has a body with
        ``_X = 21; _Y = 21; FOO: int = _X + _Y`` and is declared as
        ``cell FOO``. The check must accept this — at least one
        top-level assignment matches.
        """
        fixture = (
            _FIXTURES
            / "constant_name_multiple_assignments"
            / "constant_name_multiple_assignments.s0ma"
        )
        _, diags = _parse_and_validate(fixture)
        mismatches = [d for d in diags if d.code == "CONSTANT_NAME_MISMATCH"]
        assert mismatches == [], (
            f"multi-assignment fixture must validate clean of "
            f"CONSTANT_NAME_MISMATCH when one assignment matches the "
            f"cell name, got: {[d.message for d in mismatches]}"
        )


class TestConstantNameMismatchModeIndependence:
    """CONSTANT_NAME_MISMATCH is an error in every strictness mode.

    Per the SEVERITY_MATRIX entry, the code is ``error`` in every
    StrictnessMode — there is no warning ladder. This is a hard
    correctness invariant: a CONSTANT cell whose body diverges from
    its declaration name produces a runtime ImportError regardless of
    the mode the project was last built under.
    """

    @pytest.mark.parametrize(
        "mode",
        [
            StrictnessMode.MIGRATION,
            StrictnessMode.DEV,
            StrictnessMode.STRICT,
            StrictnessMode.RELEASE,
        ],
    )
    def test_mismatch_errors_in_every_mode(
        self, mode: StrictnessMode,
    ) -> None:
        fixture = (
            _FIXTURES
            / "constant_name_mismatch"
            / "constant_name_mismatch.s0ma"
        )
        _, diags = _parse_and_validate(fixture, mode=mode)
        mismatches = [d for d in diags if d.code == "CONSTANT_NAME_MISMATCH"]
        assert len(mismatches) == 1, (
            f"mode={mode.value}: mismatched fixture must produce "
            f"exactly one CONSTANT_NAME_MISMATCH error"
        )
        assert mismatches[0].severity == "error", (
            f"mode={mode.value}: severity must be 'error', got "
            f"{mismatches[0].severity!r}"
        )


class TestEmbeddedFileCellsAreExempt:
    """CONSTANT cells with ``content: @file("...")`` are exempt from the check.

    Under M12, the codegen synthesises ``<cell_name> = <literal>``
    from the embedded file's contents — so the cell name and the
    assigned identifier are equal by construction. The check must
    skip these cells (no body to walk; the AST helper would return
    an empty set and falsely flag them).
    """

    def test_embed_html_fixture_clean(self) -> None:
        """The existing embed_html fixture has ``cell VIZ_TEMPLATE``
        with ``content: @file("templates/viz.html")`` and no inline
        body — the check must not fire.
        """
        fixture = _FIXTURES / "embed_html" / "embed_test.s0ma"
        _, diags = _parse_and_validate(fixture)
        mismatches = [d for d in diags if d.code == "CONSTANT_NAME_MISMATCH"]
        assert mismatches == [], (
            f"embedded-file CONSTANT cell must be exempt from the "
            f"name-vs-body check, got: {[d.message for d in mismatches]}"
        )


class TestBodyTopLevelAssignedNames:
    """Unit tests for the AST helper that drives the check."""

    def test_simple_assign(self) -> None:
        assert _body_top_level_assigned_names("FOO = 1") == {"FOO"}

    def test_ann_assign(self) -> None:
        assert _body_top_level_assigned_names("FOO: int = 1") == {"FOO"}

    def test_multiple_top_level_assigns(self) -> None:
        body = "_X = 1\n_Y = 2\nFOO = _X + _Y\n"
        assert _body_top_level_assigned_names(body) == {"_X", "_Y", "FOO"}

    def test_canonical_body_parses_at_column_zero(self) -> None:
        # F1 (feedback 5–6 follow-up): the parser dedents bodies once at
        # parse time. Downstream callers (this helper) consume the
        # canonical column-0 form. An indented body would have already
        # been dedented before reaching here; the helper itself does not
        # dedent.
        body = "FOO = 1\nBAR: int = 2\n"
        assert _body_top_level_assigned_names(body) == {"FOO", "BAR"}

    def test_nested_assigns_excluded(self) -> None:
        # Assignments inside class/def bodies are not module-scope
        # imports — they must not be counted.
        body = (
            "class Foo:\n"
            "    BAR = 1\n"
            "\n"
            "def make():\n"
            "    BAZ = 2\n"
            "\n"
            "QUX = 3\n"
        )
        assert _body_top_level_assigned_names(body) == {"QUX"}

    def test_syntax_error_returns_empty(self) -> None:
        # Bodies with parse errors are surfaced by a separate
        # body-syntax check; this helper avoids double-reporting.
        assert _body_top_level_assigned_names("FOO = (") == set()

    def test_tuple_target_excluded(self) -> None:
        # Tuple-unpacking targets are not bound to a single
        # importable name; skip them rather than over-promise.
        assert _body_top_level_assigned_names("X, Y = 1, 2") == set()

    def test_attribute_target_excluded(self) -> None:
        # ``foo.X = 1`` is not a top-level name binding.
        body = "import foo\nfoo.X = 1\n"
        assert _body_top_level_assigned_names(body) == set()
