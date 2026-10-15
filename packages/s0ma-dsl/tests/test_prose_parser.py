"""Tests for the M3 prose body parser.

Covers:
- Plain text → single TextChunk.
- Text with {{entity::ref}} tokens → correct token sequence.
- {{example::X}} → ExampleEmbedToken; other kinds → ReferenceToken.
- Fenced code blocks → PROSE_RAW_CODE_BLOCK diagnostic (always error).
- Single-backtick identifier-shaped inline code → POSSIBLE_UNRESOLVED_REFERENCE
  (warning in dev, error in release).
- Round-trip invariant: joining token .raw reproduces the body byte-for-byte.
- Malformed {{...}} → TEMPLATE_SYNTAX_ERROR with column-accurate span.
- Integration: doc-guide declarations carry prose_tokens after parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from s0ma_dsl.ast_nodes.nodes import (
    ExampleEmbedToken,
    ReferenceToken,
    TextChunk,
)
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maParseError, S0maSemanticError
from s0ma_dsl.parser import parse_s0ma
from s0ma_dsl.parser.prose_parser import parse_prose

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# parse_prose — direct unit tests
# ---------------------------------------------------------------------------


class TestPlainText:
    def test_plain_text_produces_single_textchunk(self) -> None:
        body = "The quick brown fox jumps over the lazy dog."
        tokens, diagnostics = parse_prose(body, "x.s0ma", 1)
        assert diagnostics == []
        assert len(tokens) == 1
        assert isinstance(tokens[0], TextChunk)
        assert tokens[0].raw == body

    def test_empty_body_produces_no_tokens(self) -> None:
        tokens, diagnostics = parse_prose("", "x.s0ma", 1)
        assert tokens == ()
        assert diagnostics == []

    def test_multiline_plain_text_preserves_newlines(self) -> None:
        body = "Line 1\nLine 2\nLine 3"
        tokens, diagnostics = parse_prose(body, "x.s0ma", 10)
        assert diagnostics == []
        # Exactly one text chunk whose raw equals the body.
        assert "".join(t.raw for t in tokens) == body


# ---------------------------------------------------------------------------
# Reference tokens
# ---------------------------------------------------------------------------


class TestReferenceTokens:
    def test_single_reference_produces_three_tokens(self) -> None:
        body = "Before {{nerve::greet}} after."
        tokens, diagnostics = parse_prose(body, "x.s0ma", 1)
        assert diagnostics == []
        assert len(tokens) == 3
        assert isinstance(tokens[0], TextChunk)
        assert tokens[0].raw == "Before "
        assert isinstance(tokens[1], ReferenceToken)
        assert tokens[1].raw == "{{nerve::greet}}"
        assert tokens[1].entity_ref.kind == "nerve"
        assert tokens[1].entity_ref.name == "greet"
        assert tokens[1].entity_ref.field_path == ()
        assert isinstance(tokens[2], TextChunk)
        assert tokens[2].raw == " after."

    def test_reference_with_field_path_resolves(self) -> None:
        body = "See {{nerve::greet.intent}}."
        tokens, diagnostics = parse_prose(body, "x.s0ma", 1)
        assert diagnostics == []
        ref = next(t for t in tokens if isinstance(t, ReferenceToken))
        assert ref.entity_ref.kind == "nerve"
        assert ref.entity_ref.name == "greet"
        assert ref.entity_ref.field_path == ("intent",)

    def test_multiple_references_on_one_line(self) -> None:
        body = "{{nerve::a}} and {{cell::B}} together."
        tokens, diagnostics = parse_prose(body, "x.s0ma", 1)
        assert diagnostics == []
        ref_tokens = [t for t in tokens if isinstance(t, ReferenceToken)]
        assert len(ref_tokens) == 2
        assert ref_tokens[0].entity_ref.name == "a"
        assert ref_tokens[1].entity_ref.name == "B"

    def test_example_embed_produces_example_embed_token(self) -> None:
        body = "Usage:\n{{example::greet_example}}\nEnd."
        tokens, diagnostics = parse_prose(body, "x.s0ma", 1)
        assert diagnostics == []
        embed = next(t for t in tokens if isinstance(t, ExampleEmbedToken))
        assert embed.entity_ref.kind == "example"
        assert embed.entity_ref.name == "greet_example"
        assert embed.raw == "{{example::greet_example}}"

    def test_reference_across_all_kinds(self) -> None:
        body = (
            "{{nerve::n}} {{cell::c}} {{ganglion::g}} "
            "{{module::m}} {{example::e}} {{test::t}}"
        )
        tokens, diagnostics = parse_prose(body, "x.s0ma", 1)
        assert diagnostics == []
        kinds = [t for t in tokens if isinstance(t, (ReferenceToken, ExampleEmbedToken))]
        assert len(kinds) == 6
        # example must be the only ExampleEmbedToken
        embeds = [t for t in kinds if isinstance(t, ExampleEmbedToken)]
        assert len(embeds) == 1
        assert embeds[0].entity_ref.kind == "example"


# ---------------------------------------------------------------------------
# Round-trip invariant
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.parametrize(
        "body",
        [
            "",
            "hello",
            "{{nerve::x}}",
            "before {{nerve::x}} after",
            "multi\nline\nbody",
            "{{cell::a}}\n\n{{cell::b}}\n",
            "weird  spacing   here",
            "tabs\there\tand\tthere",
            "text `identifier` mixed {{nerve::foo}} here",
        ],
    )
    def test_joining_raw_fields_reproduces_body(self, body: str) -> None:
        tokens, _ = parse_prose(body, "x.s0ma", 1)
        assert "".join(t.raw for t in tokens) == body


# ---------------------------------------------------------------------------
# Fenced code blocks
# ---------------------------------------------------------------------------


class TestFencedCodeBlocks:
    def test_triple_backtick_emits_prose_raw_code_block(self) -> None:
        body = "intro\n```python\nprint('hi')\n```\nend"
        tokens, diagnostics = parse_prose(body, "x.s0ma", 5)
        assert "".join(t.raw for t in tokens) == body
        codes = [d.code for d in diagnostics]
        assert "PROSE_RAW_CODE_BLOCK" in codes
        diag = next(d for d in diagnostics if d.code == "PROSE_RAW_CODE_BLOCK")
        # The fence opens on line 2 of the body (body starts at line 5, so abs line = 6).
        assert diag.line == 6
        assert diag.severity == "error"
        assert "example::" in diag.remediation

    def test_triple_tilde_emits_prose_raw_code_block(self) -> None:
        body = "~~~\ncode here\n~~~"
        tokens, diagnostics = parse_prose(body, "x.s0ma", 1)
        assert "".join(t.raw for t in tokens) == body
        codes = [d.code for d in diagnostics]
        assert "PROSE_RAW_CODE_BLOCK" in codes

    def test_indented_fence_still_detected(self) -> None:
        # When a doc-guide body is captured under 4-space source indent,
        # the fence has leading whitespace.
        body = "    ```\n    code\n    ```"
        _, diagnostics = parse_prose(body, "x.s0ma", 1)
        codes = [d.code for d in diagnostics]
        assert "PROSE_RAW_CODE_BLOCK" in codes

    def test_fence_is_error_in_every_mode(self) -> None:
        body = "```\nx\n```"
        for mode in StrictnessMode:
            _, diagnostics = parse_prose(body, "x.s0ma", 1, mode)
            severities = [
                d.severity for d in diagnostics if d.code == "PROSE_RAW_CODE_BLOCK"
            ]
            assert all(s == "error" for s in severities)
            assert severities, f"expected diagnostic in mode {mode}"


# ---------------------------------------------------------------------------
# Heuristic inline-code warning
# ---------------------------------------------------------------------------


class TestInlineCodeHeuristic:
    def test_identifier_in_backticks_warns_in_dev(self) -> None:
        body = "Call the `myHelper` function before starting."
        _, diagnostics = parse_prose(body, "x.s0ma", 1, StrictnessMode.DEV)
        codes = [d.code for d in diagnostics]
        assert "POSSIBLE_UNRESOLVED_REFERENCE" in codes
        diag = next(d for d in diagnostics if d.code == "POSSIBLE_UNRESOLVED_REFERENCE")
        assert diag.severity == "warning"
        assert "myHelper" in diag.context["identifier"]

    def test_identifier_in_backticks_is_error_in_release(self) -> None:
        body = "Call the `myHelper` function."
        _, diagnostics = parse_prose(body, "x.s0ma", 1, StrictnessMode.RELEASE)
        diag = next(d for d in diagnostics if d.code == "POSSIBLE_UNRESOLVED_REFERENCE")
        assert diag.severity == "error"

    def test_plain_prose_without_backticks_does_not_warn(self) -> None:
        body = "Plain prose with no inline code at all."
        _, diagnostics = parse_prose(body, "x.s0ma", 1)
        codes = [d.code for d in diagnostics]
        assert "POSSIBLE_UNRESOLVED_REFERENCE" not in codes

    def test_backticks_with_non_identifier_content_do_not_warn(self) -> None:
        # Punctuation-heavy backtick span — not identifier-shaped.
        body = "Use `a = b + c` as a template."
        _, diagnostics = parse_prose(body, "x.s0ma", 1)
        codes = [d.code for d in diagnostics]
        assert "POSSIBLE_UNRESOLVED_REFERENCE" not in codes


# ---------------------------------------------------------------------------
# Malformed references
# ---------------------------------------------------------------------------


class TestMalformed:
    def test_unclosed_reference_raises_template_syntax_error(self) -> None:
        body = "broken {{nerve::greet without close"
        with pytest.raises(S0maParseError) as excinfo:
            parse_prose(body, "x.s0ma", 5)
        err = excinfo.value
        assert err.code == "TEMPLATE_SYNTAX_ERROR"
        assert err.line == 5

    def test_empty_reference_raises_template_syntax_error(self) -> None:
        body = "{{}}"
        with pytest.raises(S0maParseError) as excinfo:
            parse_prose(body, "x.s0ma", 1)
        assert excinfo.value.code == "TEMPLATE_SYNTAX_ERROR"

    def test_nested_braces_inside_reference_raises(self) -> None:
        body = "outer {{nerve::{{other}} }} text"
        with pytest.raises(S0maParseError) as excinfo:
            parse_prose(body, "x.s0ma", 1)
        assert excinfo.value.code == "TEMPLATE_SYNTAX_ERROR"

    def test_invalid_entity_ref_raises_template_syntax_error(self) -> None:
        # Missing '::' delimiter.
        body = "{{not_an_entity_ref}}"
        with pytest.raises(S0maParseError) as excinfo:
            parse_prose(body, "x.s0ma", 1)
        assert excinfo.value.code == "TEMPLATE_SYNTAX_ERROR"

    def test_line_number_is_accurate_for_multiline_body(self) -> None:
        body = "line one\nline two\n{{bad"
        with pytest.raises(S0maParseError) as excinfo:
            parse_prose(body, "x.s0ma", 10)
        # Body starts at line 10; the malformed reference is on body line 3.
        assert excinfo.value.line == 12


# ---------------------------------------------------------------------------
# Integration: parse_s0ma populates prose_tokens on DocGuideDecl
# ---------------------------------------------------------------------------


class TestDocGuideIntegration:
    def test_minimal_doc_guide_populates_prose_tokens(self) -> None:
        source = (FIXTURES / "valid" / "docs" / "minimal_doc_guide.s0ma").read_text()
        result = parse_s0ma(source, "minimal_doc_guide.s0ma")
        guide = result.doc_guides[0]
        # The prose body has a {{nerve::greet}} reference; tokenisation
        # must produce at least one ReferenceToken.
        ref_tokens = [t for t in guide.prose_tokens if isinstance(t, ReferenceToken)]
        assert len(ref_tokens) >= 1
        assert ref_tokens[0].entity_ref.kind == "nerve"
        assert ref_tokens[0].entity_ref.name == "greet"

    def test_round_trip_holds_for_minimal_doc_guide(self) -> None:
        source = (FIXTURES / "valid" / "docs" / "minimal_doc_guide.s0ma").read_text()
        result = parse_s0ma(source, "minimal_doc_guide.s0ma")
        guide = result.doc_guides[0]
        joined = "".join(t.raw for t in guide.prose_tokens)
        assert joined == guide.prose_body

    def test_fenced_code_block_in_doc_guide_raises_in_dev(self) -> None:
        source = """\
module fenced_guide
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide with an illegal fenced code block."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide bad
    intent: "Guide that tries to embed a raw code block."
    format: markdown
    output: docs/bad.md
    covers: [nerve::greet]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: []
    ---
    Here is some code:
    ```python
    print('hi')
    ```
    Done.
"""
        with pytest.raises((S0maParseError, S0maSemanticError)) as excinfo:
            parse_s0ma(source, "fenced.s0ma")
        assert excinfo.value.code == "PROSE_RAW_CODE_BLOCK"

    def test_inline_identifier_warning_in_dev_does_not_block_parse(self) -> None:
        source = """\
module warn_guide
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide with a heuristic warning."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide warn
    intent: "Guide containing an inline-code identifier."
    format: markdown
    output: docs/warn.md
    covers: [nerve::greet]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: []
    ---
    The `myHelper` function does something important.
"""
        # Parse should succeed in DEV (warning only). We import
        # parse_s0ma_with_warnings to surface the warning for the assertion.
        from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings

        result, warnings = parse_s0ma_with_warnings(
            source, "warn.s0ma", mode=StrictnessMode.DEV,
        )
        assert len(result.doc_guides) == 1
        codes = [w.code for w in warnings]
        assert "POSSIBLE_UNRESOLVED_REFERENCE" in codes

    def test_inline_identifier_blocks_parse_in_release(self) -> None:
        source = """\
module warn_guide_release
    layer: DOMAIN
    version: 1.0.0
    intent: "Guide with a heuristic warning, release mode."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-guide warn
    intent: "Guide containing an inline-code identifier."
    format: markdown
    output: docs/warn.md
    covers: [nerve::greet]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: []
    ---
    The `myHelper` function does something important.
"""
        with pytest.raises((S0maParseError, S0maSemanticError)) as excinfo:
            parse_s0ma(source, "warn.s0ma", mode=StrictnessMode.RELEASE)
        assert excinfo.value.code == "POSSIBLE_UNRESOLVED_REFERENCE"
