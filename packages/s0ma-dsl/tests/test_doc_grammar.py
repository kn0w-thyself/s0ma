"""Grammar/AST/preprocessor tests for doc-ref, doc-guide, and example declarations.

Covers Milestones 1 and 2 of the documentation-subsystem plan:
- Minimal valid parses for each new declaration type.
- Missing-mandatory-field diagnostics with correct codes.
- doc-ref with a ``---`` body rejected via PARSE_DOC_REF_BODY_PROHIBITED.
- doc-guide without a ``---`` body rejected via PARSE_ERROR.
- example body validated for prohibited constructs (exec/eval/__import__).
- Regression: existing fixtures continue to parse unchanged.
- M2: structured AST shapes for covers/sections/asserts/examples/demonstrates.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from s0ma_dsl.ast_nodes.nodes import (
    AssertComparison,
    ComparisonPredicate,
    DocGuideDecl,
    DocRefDecl,
    EntityRefAst,
    ExampleDecl,
    FilterExprAst,
    S0maModule,
    SectionAst,
)
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.parser import parse_s0ma
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# doc-ref
# ---------------------------------------------------------------------------


class TestDocRefMinimal:
    def test_parses_to_docrefdecl(self) -> None:
        source = (FIXTURES / "valid" / "docs" / "minimal_doc_ref.s0ma").read_text()
        result = parse_s0ma(source, "minimal_doc_ref.s0ma")
        assert isinstance(result, S0maModule)
        assert len(result.doc_refs) == 1
        assert result.doc_guides == ()
        assert result.examples == ()
        ref = result.doc_refs[0]
        assert isinstance(ref, DocRefDecl)
        assert ref.name == "api_reference"
        assert ref.module_location == "minimal_doc_ref"
        assert ref.intent == "Generated reference for every public nerve in the module."
        assert ref.format == "markdown"
        assert ref.output == "docs/api_reference.md"

    def test_covers_and_sections_are_structured_asts(self) -> None:
        source = (FIXTURES / "valid" / "docs" / "minimal_doc_ref.s0ma").read_text()
        result = parse_s0ma(source, "minimal_doc_ref.s0ma")
        ref = result.doc_refs[0]

        # covers: one FilterExprAst with a structured predicate.
        assert len(ref.covers) == 1
        fe = ref.covers[0]
        assert isinstance(fe, FilterExprAst)
        assert fe.kind == "nerve"
        assert fe.raw == "nerve where visibility == PUBLIC"
        assert isinstance(fe.predicate, ComparisonPredicate)
        assert fe.predicate.lhs == ("visibility",)
        assert fe.predicate.operator == "=="
        assert fe.predicate.rhs == "PUBLIC"
        assert fe.ordered_by == ()
        assert fe.group_by is None

        # sections: three bare field references.
        assert [s.field_name for s in ref.sections] == ["intent", "expects", "guarantees"]
        for s in ref.sections:
            assert isinstance(s, SectionAst)
            assert s.iteration is None

    def test_missing_intent_raises(self) -> None:
        source = (FIXTURES / "invalid" / "docs" / "doc_ref_missing_intent.s0ma").read_text()
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(source, "doc_ref_missing_intent.s0ma")
        err = excinfo.value
        assert err.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert err.context.get("field") == "intent"
        assert err.context.get("declaration_type") == "doc_ref"

    def test_body_prohibited(self) -> None:
        source = (FIXTURES / "invalid" / "docs" / "doc_ref_with_body.s0ma").read_text()
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(source, "doc_ref_with_body.s0ma")
        err = excinfo.value
        assert err.code == "PARSE_DOC_REF_BODY_PROHIBITED"
        assert err.severity == "error"
        # Remediation must point the author at doc-guide as the alternative.
        assert "doc-guide" in err.remediation


# ---------------------------------------------------------------------------
# doc-guide
# ---------------------------------------------------------------------------


class TestDocGuideMinimal:
    def test_parses_to_docguidedecl(self) -> None:
        source = (FIXTURES / "valid" / "docs" / "minimal_doc_guide.s0ma").read_text()
        result = parse_s0ma(source, "minimal_doc_guide.s0ma")
        assert len(result.doc_guides) == 1
        guide = result.doc_guides[0]
        assert isinstance(guide, DocGuideDecl)
        assert guide.name == "getting_started"
        assert guide.module_location == "minimal_doc_guide"
        assert guide.format == "markdown"
        assert guide.output == "docs/getting_started.md"

    def test_asserts_are_structured(self) -> None:
        source = (FIXTURES / "valid" / "docs" / "minimal_doc_guide.s0ma").read_text()
        result = parse_s0ma(source, "minimal_doc_guide.s0ma")
        guide = result.doc_guides[0]
        assert len(guide.asserts) == 1
        a = guide.asserts[0]
        assert isinstance(a, AssertComparison)
        assert isinstance(a.lhs, EntityRefAst)
        assert a.lhs.kind == "nerve"
        assert a.lhs.name == "greet"
        assert a.lhs.field_path == ("visibility",)
        assert a.operator == "=="
        assert a.rhs == "PUBLIC"

    def test_covers_and_examples_are_entity_refs(self) -> None:
        source = (FIXTURES / "valid" / "docs" / "minimal_doc_guide.s0ma").read_text()
        result = parse_s0ma(source, "minimal_doc_guide.s0ma")
        guide = result.doc_guides[0]
        assert len(guide.covers) == 1
        assert isinstance(guide.covers[0], EntityRefAst)
        assert guide.covers[0].kind == "nerve"
        assert guide.covers[0].name == "greet"
        assert guide.covers[0].field_path == ()

        assert len(guide.examples) == 1
        assert isinstance(guide.examples[0], EntityRefAst)
        assert guide.examples[0].kind == "example"
        assert guide.examples[0].name == "greet_example"

    def test_prose_body_preserved(self) -> None:
        source = (FIXTURES / "valid" / "docs" / "minimal_doc_guide.s0ma").read_text()
        result = parse_s0ma(source, "minimal_doc_guide.s0ma")
        guide = result.doc_guides[0]
        # The body must contain the {{...}} token unmodified (M1: pass-through).
        assert "{{nerve::greet}}" in guide.prose_body
        assert "Getting Started" in guide.prose_body

    def test_missing_body_raises(self) -> None:
        source = (FIXTURES / "invalid" / "docs" / "doc_guide_missing_body.s0ma").read_text()
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(source, "doc_guide_missing_body.s0ma")
        err = excinfo.value
        assert err.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert err.context.get("field") == "prose_body"


# ---------------------------------------------------------------------------
# example
# ---------------------------------------------------------------------------


class TestExampleMinimal:
    def test_parses_to_exampledecl(self) -> None:
        source = (FIXTURES / "valid" / "docs" / "minimal_example.s0ma").read_text()
        result = parse_s0ma(source, "minimal_example.s0ma")
        assert len(result.examples) == 1
        ex = result.examples[0]
        assert isinstance(ex, ExampleDecl)
        assert ex.name == "greet_example"
        assert ex.module_location == "minimal_example"
        assert ex.runs_in == "standalone"
        assert len(ex.demonstrates) == 1
        d = ex.demonstrates[0]
        assert isinstance(d, EntityRefAst)
        assert d.kind == "nerve"
        assert d.name == "greet"
        assert d.field_path == ()

    def test_python_body_preserved(self) -> None:
        source = (FIXTURES / "valid" / "docs" / "minimal_example.s0ma").read_text()
        result = parse_s0ma(source, "minimal_example.s0ma")
        ex = result.examples[0]
        assert "from minimal_example import greet" in ex.python_body
        assert "print(greet(" in ex.python_body

    def test_missing_demonstrates_raises(self) -> None:
        source = (FIXTURES / "invalid" / "docs" / "example_missing_demonstrates.s0ma").read_text()
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(source, "example_missing_demonstrates.s0ma")
        err = excinfo.value
        assert err.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert err.context.get("field") == "demonstrates"

    def test_prohibited_construct_in_body_is_warning_in_dev(self) -> None:
        # In DEV mode, PROHIBITED_CONSTRUCT is a warning. The parse succeeds
        # but the warning surfaces via parse_s0ma_with_warnings.
        source = (FIXTURES / "invalid" / "docs" / "example_prohibited_construct.s0ma").read_text()
        _, warnings = parse_s0ma_with_warnings(
            source, "example_prohibited_construct.s0ma", mode=StrictnessMode.DEV,
        )
        codes = [w.code for w in warnings]
        assert "PROHIBITED_CONSTRUCT" in codes
        hit = next(w for w in warnings if w.code == "PROHIBITED_CONSTRUCT")
        assert "exec" in hit.context.get("construct", "")

    def test_prohibited_construct_in_body_raises_in_strict(self) -> None:
        # In STRICT mode, PROHIBITED_CONSTRUCT promotes to an error.
        source = (FIXTURES / "invalid" / "docs" / "example_prohibited_construct.s0ma").read_text()
        with pytest.raises(Exception) as excinfo:
            parse_s0ma(source, "example_prohibited_construct.s0ma", mode=StrictnessMode.STRICT)
        err = excinfo.value
        assert err.code == "PROHIBITED_CONSTRUCT"
        assert "exec" in err.context.get("construct", "")


# ---------------------------------------------------------------------------
# Mixed declarations in one module
# ---------------------------------------------------------------------------


class TestMixedDocDeclarations:
    def test_multiple_doc_declarations_in_one_module(self) -> None:
        source = """\
module mixed
    layer: DOMAIN
    version: 1.0.0
    intent: "Mixed module with one nerve plus doc declarations."
    exports: [greet]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Returns a greeting string for a username."
    expects: "username is non-empty"
    guarantees: "return value contains the username"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def greet(username: str) -> str:
        return f"Hello, {username}!"

doc-ref api
    intent: "Reference for the greet nerve."
    format: markdown
    output: docs/api.md
    covers: [nerves where visibility == PUBLIC]
    sections: [intent]

example greet_example
    intent: "Shows how to call greet."
    demonstrates: [nerve::greet]
    runs_in: standalone
    ---
    from mixed import greet
    assert greet("Ada") == "Hello, Ada!"
"""
        result = parse_s0ma(source, "mixed.s0ma")
        assert len(result.nerves) == 1
        assert len(result.doc_refs) == 1
        assert len(result.examples) == 1
        # Source order is preserved via all_declarations.
        all_names = [d.name for d in result.all_declarations]
        assert all_names == ["greet", "api", "greet_example"]


# ---------------------------------------------------------------------------
# Regression: existing fixtures still parse
# ---------------------------------------------------------------------------


class TestExistingFixturesStillParse:
    def test_signal_processor_still_parses(self) -> None:
        source = (FIXTURES / "valid" / "signal_processor.s0ma").read_text()
        result = parse_s0ma(source, "signal_processor.s0ma")
        assert isinstance(result, S0maModule)
        # Doc-related tuples default to empty for pre-existing fixtures.
        assert result.doc_refs == ()
        assert result.doc_guides == ()
        assert result.examples == ()
