"""Tests for the assert-expression sub-grammar (Milestone 2).

Assert expressions back the ``asserts:`` field of a ``doc-guide``. The
grammar is deliberately narrower than the template grammar: entity field
access, ``==`` / ``!=`` / ``in``, and boolean composition (``and``, ``or``,
``not``). Iteration, ordering, and grouping are *not* allowed.
"""

from __future__ import annotations

import pytest

from s0ma_dsl.ast_nodes.nodes import (
    AssertBoolean,
    AssertComparison,
    EntityRefAst,
)
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.parser.s0ma_parser import _parse_assert_pred


class TestAssertComparison:
    def test_simple_eq(self) -> None:
        a = _parse_assert_pred("nerve::greet.visibility == PUBLIC", "t.s0ma", 1)
        assert isinstance(a, AssertComparison)
        assert isinstance(a.lhs, EntityRefAst)
        assert a.lhs.kind == "nerve"
        assert a.lhs.name == "greet"
        assert a.lhs.field_path == ("visibility",)
        assert a.operator == "=="
        assert a.rhs == "PUBLIC"

    def test_simple_neq(self) -> None:
        a = _parse_assert_pred("cell::Message.kind != ENUM", "t.s0ma", 1)
        assert isinstance(a, AssertComparison)
        assert a.operator == "!="

    def test_in_list(self) -> None:
        a = _parse_assert_pred(
            "nerve::X.kind in [SERVICE, FUNCTION]", "t.s0ma", 1,
        )
        assert isinstance(a, AssertComparison)
        assert a.operator == "in"
        assert a.rhs == ("SERVICE", "FUNCTION")

    def test_nested_field_path(self) -> None:
        a = _parse_assert_pred(
            "cell::Message.schema.fields == something", "t.s0ma", 1,
        )
        assert isinstance(a, AssertComparison)
        assert a.lhs.field_path == ("schema", "fields")

    def test_quoted_value(self) -> None:
        a = _parse_assert_pred(
            'nerve::X.intent == "Something meaningful"', "t.s0ma", 1,
        )
        assert isinstance(a, AssertComparison)
        assert a.rhs == "Something meaningful"


class TestAssertComposition:
    def test_and_composition(self) -> None:
        a = _parse_assert_pred(
            "nerve::X.visibility == PUBLIC and nerve::X.kind == FUNCTION",
            "t.s0ma", 1,
        )
        assert isinstance(a, AssertBoolean)
        assert a.operator == "and"
        assert len(a.operands) == 2
        assert all(isinstance(op, AssertComparison) for op in a.operands)

    def test_or_composition(self) -> None:
        a = _parse_assert_pred(
            "nerve::X.kind == SERVICE or nerve::X.kind == FUNCTION",
            "t.s0ma", 1,
        )
        assert isinstance(a, AssertBoolean)
        assert a.operator == "or"

    def test_not_composition(self) -> None:
        a = _parse_assert_pred(
            "not nerve::X.visibility == PUBLIC", "t.s0ma", 1,
        )
        assert isinstance(a, AssertBoolean)
        assert a.operator == "not"
        assert len(a.operands) == 1
        assert isinstance(a.operands[0], AssertComparison)

    def test_mixed_and_or(self) -> None:
        a = _parse_assert_pred(
            "nerve::A.f == X and nerve::B.g == Y or nerve::C.h == Z",
            "t.s0ma", 1,
        )
        # Precedence: and binds tighter than or, so top-level is OR.
        assert isinstance(a, AssertBoolean)
        assert a.operator == "or"
        assert len(a.operands) == 2
        # First operand is an AND-combination.
        assert isinstance(a.operands[0], AssertBoolean)
        assert a.operands[0].operator == "and"


class TestAssertRejections:
    def test_iteration_rejected(self) -> None:
        # Iteration is valid in templates but forbidden inside asserts.
        with pytest.raises(S0maParseError) as exc:
            _parse_assert_pred("for n in nerves", "t.s0ma", 1)
        assert exc.value.code == "ASSERT_SYNTAX_ERROR"

    def test_ordered_by_rejected(self) -> None:
        with pytest.raises(S0maParseError) as exc:
            _parse_assert_pred(
                "nerve::X.visibility == PUBLIC ordered_by name", "t.s0ma", 1,
            )
        assert exc.value.code == "ASSERT_SYNTAX_ERROR"

    def test_group_by_rejected(self) -> None:
        with pytest.raises(S0maParseError):
            _parse_assert_pred(
                "nerve::X.kind == SERVICE group_by kind", "t.s0ma", 1,
            )

    def test_bare_field_path_rejected(self) -> None:
        # Assert LHS must be an entity reference, not a bare field path.
        with pytest.raises(S0maParseError) as exc:
            _parse_assert_pred("visibility == PUBLIC", "t.s0ma", 1)
        assert exc.value.code == "ASSERT_SYNTAX_ERROR"

    def test_single_eq_rejected(self) -> None:
        with pytest.raises(S0maParseError):
            _parse_assert_pred("nerve::X.f = PUBLIC", "t.s0ma", 1)

    def test_arithmetic_rejected(self) -> None:
        with pytest.raises(S0maParseError):
            _parse_assert_pred("nerve::X.count > 5", "t.s0ma", 1)

    def test_string_concatenation_rejected(self) -> None:
        with pytest.raises(S0maParseError):
            _parse_assert_pred(
                'nerve::X.intent == "a" + "b"', "t.s0ma", 1,
            )

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(S0maParseError):
            _parse_assert_pred("widget::X.f == Y", "t.s0ma", 1)


class TestAssertDiagnosticFields:
    def test_remediation_includes_grammar_hint(self) -> None:
        with pytest.raises(S0maParseError) as exc:
            _parse_assert_pred("nerve::X.count > 5", "t.s0ma", 42)
        err = exc.value
        assert err.code == "ASSERT_SYNTAX_ERROR"
        assert err.line == 42
        assert err.severity == "error"
        # Remediation must be specific.
        assert "entity-level" in err.remediation or "nerve::" in err.remediation
        assert err.context.get("raw_value") == "nerve::X.count > 5"
