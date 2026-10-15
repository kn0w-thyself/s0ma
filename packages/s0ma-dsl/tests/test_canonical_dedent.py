"""F1 (feedback 5–6 follow-up) — canonical dedented body invariant.

Pins the post-F1 contract: bodies on AST declarations are stored in
canonical (dedented) Python-ready form and downstream consumers
(validator, codegen) do not re-dedent. The five tests below mirror the
five named tests in the F1 milestone of
the 5-6 plan (internal).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma, parse_s0ma_with_warnings
from s0ma_dsl.semantic.validator import validate_module

if TYPE_CHECKING:
    import pytest

_FIXTURES = Path(__file__).parent / "fixtures"
_M17_FIXTURE = _FIXTURES / "m17_multiline_constant" / "m17_multiline_constant.s0ma"


# ---------------------------------------------------------------------------
# Test 1: M17 false-positive regression — multi-line CONSTANT with column-0
# string lines validates clean post-F1.
# ---------------------------------------------------------------------------


def test_constant_with_multiline_string_body_no_false_positive() -> None:
    """Pre-F1 the validator's M17 helper called ``textwrap.dedent`` on
    the raw body. A CONSTANT body whose triple-quoted string contains
    column-0 lines (``\"\"\"\\n<html>...``) collapses the common
    leading prefix to the empty string, so the dedent is a no-op and
    the still-indented assignment line trips ``ast.parse`` with
    ``IndentationError``. The helper swallowed the parse error and
    reported zero assigned names — producing a spurious
    ``CONSTANT_NAME_MISMATCH`` even though the body's top-level
    assignment matched the cell name.

    Post-F1 the parser dedents bodies once at parse time using the
    first-line-indent strategy (which tolerates column-0 string
    content) and the validator reads the canonical column-0 body
    directly. This fixture must validate clean in strict mode.
    """
    source = _M17_FIXTURE.read_text(encoding="utf-8")
    module, warnings = parse_s0ma_with_warnings(
        source, str(_M17_FIXTURE), mode=StrictnessMode.STRICT,
    )
    errors = validate_module(
        module, mode=StrictnessMode.STRICT, filename=str(_M17_FIXTURE),
    )
    diagnostics = list(warnings) + list(errors)
    constant_mismatches = [d for d in diagnostics if d.code == "CONSTANT_NAME_MISMATCH"]
    assert constant_mismatches == [], (
        "Expected zero CONSTANT_NAME_MISMATCH diagnostics on the M17 "
        "multi-line CONSTANT regression fixture; got: "
        f"{[d.message for d in constant_mismatches]}"
    )
    # Defensive: nothing else should fire either, but pin the M17 code
    # specifically — that's the bug F1 closes.
    assert errors == [], f"Expected validator-clean fixture; got {errors!r}"


# ---------------------------------------------------------------------------
# Test 2: AST.body is the canonical dedented form.
# ---------------------------------------------------------------------------


def test_canonical_body_is_dedented() -> None:
    """``decl.body`` carries the dedented Python-ready form: the
    .s0ma source's leading indent is stripped, but lines that were
    column-0 in the source (e.g. inside the multi-line string
    literal) remain column-0.
    """
    source = _M17_FIXTURE.read_text(encoding="utf-8")
    module = parse_s0ma(source, str(_M17_FIXTURE), mode=StrictnessMode.STRICT)
    cell = module.cells[0]
    assert cell.body is not None
    # First non-blank line is the assignment ``BIG_TEMPLATE = """``;
    # post-F1 it is at column 0 (no leading spaces).
    first_line = cell.body.split("\n", 1)[0]
    assert first_line.startswith("BIG_TEMPLATE"), (
        f"Expected canonical body to start at column 0; got {first_line!r}"
    )
    # And the column-0 ``<html>`` line inside the string literal
    # remains exactly as authored.
    assert "\n<html>\n" in cell.body, (
        f"Expected column-0 ``<html>`` line preserved; got body[:120]={cell.body[:120]!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: raw_body retains the .s0ma source's indentation.
# ---------------------------------------------------------------------------


def test_raw_body_preserves_indentation() -> None:
    """``decl.raw_body`` is the diagnostics-only original form — it
    keeps the source's leading 4-space indent on the assignment line.
    The split between ``body`` and ``raw_body`` is the F1 contract:
    canonical for production consumers, raw for tooling that needs
    column offsets back into the .s0ma source.
    """
    source = _M17_FIXTURE.read_text(encoding="utf-8")
    module = parse_s0ma(source, str(_M17_FIXTURE), mode=StrictnessMode.STRICT)
    cell = module.cells[0]
    assert cell.raw_body is not None
    first_nonblank = next(
        (line for line in cell.raw_body.split("\n") if line.strip()),
        "",
    )
    assert first_nonblank.startswith("    BIG_TEMPLATE"), (
        f"Expected raw_body to retain the .s0ma source's leading indent; "
        f"got first non-blank line {first_nonblank!r}"
    )
    # Sanity: raw_body and body are not the same string when the
    # source had any leading indent.
    assert cell.raw_body != cell.body


# ---------------------------------------------------------------------------
# Test 4: validator does not re-dedent.
# ---------------------------------------------------------------------------


def test_validator_does_not_re_dedent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkey-patch ``textwrap.dedent`` to raise. If the validator
    still calls it on a body, this test fails. Post-F1 the validator
    consumes the canonical body directly, so the patched dedent is
    never invoked on the M17-style fixture.
    """
    import textwrap as _textwrap

    def _explode(*args, **kwargs):  # noqa: ANN001, ANN201
        raise AssertionError(
            "textwrap.dedent must not be called on a body post-F1"
        )

    monkeypatch.setattr(_textwrap, "dedent", _explode)

    source = _M17_FIXTURE.read_text(encoding="utf-8")
    module, _warnings = parse_s0ma_with_warnings(
        source, str(_M17_FIXTURE), mode=StrictnessMode.STRICT,
    )
    errors = validate_module(
        module, mode=StrictnessMode.STRICT, filename=str(_M17_FIXTURE),
    )
    assert errors == []


# ---------------------------------------------------------------------------
# Test 5: codegen does not re-dedent.
# ---------------------------------------------------------------------------


def test_codegen_does_not_re_dedent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The post-F1 codegen owns no private dedent helper. To pin that
    invariant we patch the parser-level ``_dedent_body`` (the single
    source of truth) so it raises if called *outside* the parser
    pipeline. The parser has already dedented at parse time, so the
    body extractor's helper must not be invoked again during
    codegen.
    """
    import s0ma_dsl.parser.body_extractor as _be
    from s0ma_dsl.codegen.python_emitter import emit_python

    source = _M17_FIXTURE.read_text(encoding="utf-8")
    module = parse_s0ma(source, str(_M17_FIXTURE), mode=StrictnessMode.STRICT)

    # Now patch — codegen should not re-enter ``_dedent_body``.
    def _explode(*args, **kwargs):  # noqa: ANN001, ANN201
        raise AssertionError(
            "_dedent_body must not be called during codegen post-F1"
        )

    monkeypatch.setattr(_be, "_dedent_body", _explode)

    output = emit_python(module)
    assert "BIG_TEMPLATE" in output
