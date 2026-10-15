"""Tests for the template-expression sub-grammar (Milestone 2).

Covers the narrow grammar that backs doc-ref ``covers:`` and ``sections:``
fields, doc-guide ``covers:``/``examples:`` fields, and example
``demonstrates:`` fields. Per design §8.2 the grammar intentionally supports
only entity references, field access, filter predicates (==, !=, in, and/or/not),
ordering, grouping, and iteration — and rejects everything else.
"""

from __future__ import annotations

import pytest

from s0ma_dsl.ast_nodes.nodes import (
    BooleanPredicate,
    ComparisonPredicate,
    EntityRefAst,
    FilterExprAst,
    IterationAst,
    SectionAst,
)
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.parser.s0ma_parser import (
    _parse_entity_ref,
    _parse_filter_expr,
    _parse_section_entry,
)

# ---------------------------------------------------------------------------
# Entity references
# ---------------------------------------------------------------------------


class TestEntityRef:
    def test_simple_nerve(self) -> None:
        ref = _parse_entity_ref("nerve::greet", "t.s0ma", 1)
        assert isinstance(ref, EntityRefAst)
        assert ref.kind == "nerve"
        assert ref.name == "greet"
        assert ref.field_path == ()

    def test_all_kinds(self) -> None:
        for kind in ("nerve", "cell", "ganglion", "module", "example", "test"):
            ref = _parse_entity_ref(f"{kind}::X", "t.s0ma", 1)
            assert ref.kind == kind
            assert ref.name == "X"

    def test_field_access(self) -> None:
        ref = _parse_entity_ref("nerve::greet.intent", "t.s0ma", 1)
        assert ref.field_path == ("intent",)

    def test_nested_field_access(self) -> None:
        ref = _parse_entity_ref("cell::Message.schema.fields", "t.s0ma", 1)
        assert ref.kind == "cell"
        assert ref.name == "Message"
        assert ref.field_path == ("schema", "fields")

    def test_raw_preserved(self) -> None:
        ref = _parse_entity_ref("  nerve::greet.intent  ", "t.s0ma", 1)
        assert ref.raw == "nerve::greet.intent"

    def test_missing_kind_delimiter_fails(self) -> None:
        with pytest.raises(S0maParseError) as exc:
            _parse_entity_ref("nerve:greet", "t.s0ma", 1)
        assert exc.value.code == "TEMPLATE_SYNTAX_ERROR"

    def test_unknown_kind_fails(self) -> None:
        with pytest.raises(S0maParseError):
            _parse_entity_ref("widget::X", "t.s0ma", 1)

    def test_arithmetic_fails(self) -> None:
        with pytest.raises(S0maParseError) as exc:
            _parse_entity_ref("nerve::X + 1", "t.s0ma", 1)
        assert exc.value.code == "TEMPLATE_SYNTAX_ERROR"


# ---------------------------------------------------------------------------
# Filter expressions
# ---------------------------------------------------------------------------


class TestFilterExpr:
    def test_bare_kind(self) -> None:
        fe = _parse_filter_expr("nerves", "t.s0ma", 1)
        assert fe.kind == "nerve"  # plural normalised to singular
        assert fe.predicate is None
        assert fe.ordered_by == ()
        assert fe.group_by is None

    def test_singular_and_plural_equivalent(self) -> None:
        a = _parse_filter_expr("nerve", "t.s0ma", 1)
        b = _parse_filter_expr("nerves", "t.s0ma", 1)
        assert a.kind == b.kind == "nerve"

    def test_simple_where_eq(self) -> None:
        fe = _parse_filter_expr("nerves where visibility == PUBLIC", "t.s0ma", 1)
        pred = fe.predicate
        assert isinstance(pred, ComparisonPredicate)
        assert pred.lhs == ("visibility",)
        assert pred.operator == "=="
        assert pred.rhs == "PUBLIC"

    def test_where_neq(self) -> None:
        fe = _parse_filter_expr("cells where kind != CONSTANT", "t.s0ma", 1)
        assert isinstance(fe.predicate, ComparisonPredicate)
        assert fe.predicate.operator == "!="

    def test_where_in_list(self) -> None:
        fe = _parse_filter_expr(
            "cells where kind in [MODEL, CONSTANT]", "t.s0ma", 1
        )
        assert isinstance(fe.predicate, ComparisonPredicate)
        assert fe.predicate.operator == "in"
        assert fe.predicate.rhs == ("MODEL", "CONSTANT")

    def test_where_and_composition(self) -> None:
        fe = _parse_filter_expr(
            "cells where visibility == PUBLIC and kind in [MODEL, CONSTANT]",
            "t.s0ma", 1,
        )
        assert isinstance(fe.predicate, BooleanPredicate)
        assert fe.predicate.operator == "and"
        assert len(fe.predicate.operands) == 2

    def test_where_or_composition(self) -> None:
        fe = _parse_filter_expr(
            "nerves where kind == SERVICE or kind == FUNCTION",
            "t.s0ma", 1,
        )
        assert isinstance(fe.predicate, BooleanPredicate)
        assert fe.predicate.operator == "or"

    def test_where_not(self) -> None:
        fe = _parse_filter_expr("nerves where not visibility == PUBLIC", "t.s0ma", 1)
        assert isinstance(fe.predicate, BooleanPredicate)
        assert fe.predicate.operator == "not"
        assert len(fe.predicate.operands) == 1

    def test_ordered_by_single(self) -> None:
        fe = _parse_filter_expr("nerves ordered_by name", "t.s0ma", 1)
        assert fe.ordered_by == ("name",)

    def test_ordered_by_multiple(self) -> None:
        fe = _parse_filter_expr("nerves ordered_by module, name", "t.s0ma", 1)
        assert fe.ordered_by == ("module", "name")

    def test_group_by(self) -> None:
        fe = _parse_filter_expr("cells group_by kind", "t.s0ma", 1)
        assert fe.group_by == "kind"

    def test_full_combo(self) -> None:
        fe = _parse_filter_expr(
            "nerves where visibility == PUBLIC ordered_by module, name group_by module",
            "t.s0ma", 1,
        )
        assert isinstance(fe.predicate, ComparisonPredicate)
        assert fe.ordered_by == ("module", "name")
        assert fe.group_by == "module"

    def test_quoted_value(self) -> None:
        fe = _parse_filter_expr('nerves where intent == "abc"', "t.s0ma", 1)
        assert isinstance(fe.predicate, ComparisonPredicate)
        assert fe.predicate.rhs == "abc"

    # --- rejections (UNSUPPORTED_TEMPLATE_CONSTRUCT vs syntax) -------------

    def test_single_eq_rejected(self) -> None:
        # Single '=' is not a valid operator — must be '=='.
        with pytest.raises(S0maParseError) as exc:
            _parse_filter_expr("nerves where visibility = PUBLIC", "t.s0ma", 1)
        assert exc.value.code == "TEMPLATE_SYNTAX_ERROR"

    def test_string_concatenation_rejected(self) -> None:
        with pytest.raises(S0maParseError):
            _parse_filter_expr('nerves where intent == "a" + "b"', "t.s0ma", 1)

    def test_arithmetic_rejected(self) -> None:
        with pytest.raises(S0maParseError):
            _parse_filter_expr("nerves where count > 5", "t.s0ma", 1)

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(S0maParseError):
            _parse_filter_expr("widgets where x == 1", "t.s0ma", 1)

    def test_trailing_garbage_rejected(self) -> None:
        with pytest.raises(S0maParseError):
            _parse_filter_expr("nerves foobar", "t.s0ma", 1)


# ---------------------------------------------------------------------------
# Section entries
# ---------------------------------------------------------------------------


class TestSectionEntry:
    def test_simple_field(self) -> None:
        s = _parse_section_entry("intent", "t.s0ma", 1)
        assert isinstance(s, SectionAst)
        assert s.field_name == "intent"
        assert s.iteration is None

    def test_iteration_over_filter(self) -> None:
        s = _parse_section_entry(
            "for nerve in nerves where visibility == PUBLIC", "t.s0ma", 1,
        )
        assert s.field_name is None
        assert isinstance(s.iteration, IterationAst)
        assert s.iteration.var == "nerve"
        assert isinstance(s.iteration.collection, FilterExprAst)
        assert s.iteration.collection.kind == "nerve"
        assert isinstance(s.iteration.collection.predicate, ComparisonPredicate)

    def test_iteration_with_ordered_by(self) -> None:
        s = _parse_section_entry(
            "for n in nerves ordered_by module, name", "t.s0ma", 1,
        )
        assert s.iteration is not None
        assert s.iteration.ordered_by == ("module", "name")

    def test_iteration_with_group_by(self) -> None:
        s = _parse_section_entry(
            "for c in cells group_by kind", "t.s0ma", 1,
        )
        assert s.iteration is not None
        assert s.iteration.group_by == "kind"

    def test_malformed_section_rejected(self) -> None:
        with pytest.raises(S0maParseError) as exc:
            _parse_section_entry("for in nerves", "t.s0ma", 1)
        assert exc.value.code == "TEMPLATE_SYNTAX_ERROR"


# ---------------------------------------------------------------------------
# Raw preservation
# ---------------------------------------------------------------------------


class TestRawPreservation:
    def test_filter_expr_raw_round_trip(self) -> None:
        raw = "nerves where visibility == PUBLIC and kind in [SERVICE, FUNCTION]"
        fe = _parse_filter_expr(raw, "t.s0ma", 1)
        assert fe.raw == raw

    def test_section_iteration_raw_preserved(self) -> None:
        raw = "for n in nerves where visibility == PUBLIC"
        s = _parse_section_entry(raw, "t.s0ma", 1)
        assert s.raw == raw
