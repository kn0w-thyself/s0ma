"""Tests for the G7a ``covers: { source: error_codes }`` doc-ref grammar.

G7a (feedback 5–6 cleanup) extends the ``doc-ref`` ``covers:`` field with a
sub-key form that pulls from a derived non-component registry instead of
materialising a project-entity filter. The only registered source today is
``error_codes`` — the canonical union of ``SEVERITY_MATRIX`` and
``OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE``.

These tests pin:

- the parser-level discriminator (kind-form vs source-form, mutually
  exclusive);
- parse-time rejection of malformed brace forms (combined keys, unknown
  source, missing key);
- the renderer's table output (every code present, severity-by-mode columns
  populated, descriptions sourced from ``ERROR_CODE_DESCRIPTIONS``);
- parity between the rendered code list and the existing
  ``docs/spec_traceability.md`` registry (the safety check G7b's cutover
  depends on);
- the ``ERROR_CODE_DESCRIPTIONS`` completeness invariant (every registered
  code must have a description).

Plan reference: ``plans/5-6_cleanup_plan.md`` Milestone G7a.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.codegen.doc_emitter.markdown import render_doc_ref_markdown
from s0ma_dsl.config import (
    ERROR_CODE_DESCRIPTIONS,
    OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE,
    SEVERITY_MATRIX,
)
from s0ma_dsl.parser.s0ma_parser import S0maParseError, parse_s0ma
from s0ma_dsl.resolver.doc_resolver import build_project_index

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import DocRefDecl

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "doc_ref_error_codes"
TRACEABILITY_PATH = REPO_ROOT / "docs" / "spec_traceability.md"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_fixture() -> DocRefDecl:
    """Load the canonical ``doc-ref`` fixture and return the lone decl."""
    text = (FIXTURE_DIR / "error_codes_doc.s0ma").read_text()
    module = parse_s0ma(text, filename="error_codes_doc.s0ma")
    assert len(module.doc_refs) == 1, (
        "Fixture is expected to declare exactly one doc-ref so the test "
        "asserts can address it positionally."
    )
    return module.doc_refs[0]


def _parse_inline(s0ma_source: str) -> DocRefDecl:
    """Parse an inline ``.s0ma`` source with one doc-ref and return it."""
    module = parse_s0ma(s0ma_source, filename="<inline>")
    return module.doc_refs[0]


def test_doc_ref_parses_error_codes_filter() -> None:
    """``covers: { source: error_codes }`` populates the discriminator.

    The fixture's ``ErrorCodesTable`` doc-ref uses the new sub-key form.
    The parser must populate ``covers_source = "error_codes"`` and leave
    ``covers`` empty so the renderer takes the source-registry branch.
    """
    decl = _parse_fixture()
    assert decl.name == "ErrorCodesTable"
    assert decl.covers == ()
    assert decl.covers_source == "error_codes"


def test_doc_ref_kind_form_still_parses() -> None:
    """The historic ``covers: [<kind> where ...]`` form is unchanged.

    G7a is additive. An existing list-of-filter-expressions doc-ref must
    populate ``covers`` and leave ``covers_source = None``.
    """
    source = """\
module legacy_form
    layer: DOMAIN
    version: 1.0.0
    intent: "Sanity-check fixture: historic covers shape still parses."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-ref Legacy
    intent: "Reference for every public nerve."
    format: markdown
    output: docs/legacy.md
    covers: [nerve where visibility == PUBLIC]
    sections: [intent]
"""
    decl = _parse_inline(source)
    assert decl.covers_source is None
    assert len(decl.covers) == 1
    assert decl.covers[0].kind == "nerve"


def test_doc_ref_error_codes_rejects_combined_kind_and_source() -> None:
    """``covers: { source: error_codes, kind: nerve }`` errors at parse time.

    The discriminator is exclusive: a kind-form filter belongs in a
    bracketed list, not in the brace-form source dictionary. Mixing both
    is a structural authoring mistake — the parser fires
    ``PARSE_ERROR`` with a remediation pointing at the two clean shapes.
    """
    source = """\
module bad_combined
    layer: DOMAIN
    version: 1.0.0
    intent: "Bad fixture: covers carries both kind: and source:."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-ref Bad
    intent: "Should fail to parse."
    format: markdown
    output: docs/bad.md
    covers: { source: error_codes, kind: nerve }
    sections: []
"""
    with pytest.raises(S0maParseError) as exc:
        _parse_inline(source)
    assert exc.value.code == "PARSE_ERROR"
    assert "exclusive" in exc.value.message.lower()


def test_doc_ref_error_codes_rejects_unknown_source() -> None:
    """An unknown ``source:`` value is rejected with the supported list.

    Today only ``error_codes`` is registered. A typo like
    ``source: error_code`` (or any other name) must fire ``PARSE_ERROR``
    with a message naming the supported sources so the author can
    correct it.
    """
    source = """\
module bad_source
    layer: DOMAIN
    version: 1.0.0
    intent: "Bad fixture: covers references an unregistered source."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-ref Bad
    intent: "Should fail to parse."
    format: markdown
    output: docs/bad.md
    covers: { source: mcp_surface }
    sections: []
"""
    with pytest.raises(S0maParseError) as exc:
        _parse_inline(source)
    assert exc.value.code == "PARSE_ERROR"
    assert "mcp_surface" in exc.value.message
    assert "error_codes" in exc.value.message


def test_doc_ref_error_codes_rejects_brace_without_source_key() -> None:
    """``covers: { kind: nerve }`` (brace form, no source key) is rejected.

    The brace form is the source-registry shape; it requires a ``source:``
    key. Putting kind-form information in a dictionary instead of a
    bracketed list is a structural mistake; the diagnostic names the
    missing key so the author can pick the correct shape.
    """
    source = """\
module bad_kind_brace
    layer: DOMAIN
    version: 1.0.0
    intent: "Bad fixture: covers brace-form lacking source: key."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
doc-ref Bad
    intent: "Should fail to parse."
    format: markdown
    output: docs/bad.md
    covers: { kind: nerve }
    sections: []
"""
    with pytest.raises(S0maParseError) as exc:
        _parse_inline(source)
    assert exc.value.code == "PARSE_ERROR"
    assert "source" in exc.value.message.lower()


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def _render_fixture() -> str:
    """Parse the fixture, build a project index, and render the doc-ref."""
    decl = _parse_fixture()
    text = (FIXTURE_DIR / "error_codes_doc.s0ma").read_text()
    module = parse_s0ma(text, filename="error_codes_doc.s0ma")
    index = build_project_index({module.module.name: module})
    return render_doc_ref_markdown(
        decl,
        index=index,
        content_hash="1:" + "0" * 64,
        schema_version="1.2.0",
    )


def test_doc_ref_renders_error_codes_table() -> None:
    """The rendered Markdown carries one row per registered error code.

    The renderer's source-registry branch materialises every code in the
    canonical union and emits a Markdown table. The test checks (a) the
    table header is present, (b) every code appears in the table body
    surrounded by backticks (the canonical inline-code spelling).
    """
    output = _render_fixture()
    assert "| Code | Migration | Dev | Strict | Release | Description |" in output
    assert "|---|---|---|---|---|---|" in output

    every_code = set(SEVERITY_MATRIX.keys()) | set(
        OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE
    )
    missing: list[str] = []
    for code in sorted(every_code):
        if f"`{code}`" not in output:
            missing.append(code)
    assert not missing, (
        f"The following error codes are registered but absent from the "
        f"rendered table: {missing}. The renderer must emit one row per "
        f"code in SEVERITY_MATRIX | OUT_OF_MATRIX_CODES_THAT_MUST_STILL_"
        f"BE_TRACEABLE."
    )


def test_doc_ref_error_codes_descriptions_appear_in_render() -> None:
    """The render embeds the canonical description for every code.

    Pin the renderer to ``ERROR_CODE_DESCRIPTIONS`` (not to a hand-rolled
    table inside the renderer): a future contributor adding a code must
    update the description registry, and this test confirms the renderer
    reads from there.
    """
    output = _render_fixture()
    for code, description in ERROR_CODE_DESCRIPTIONS.items():
        # Markdown-table cells preserve description text verbatim, with one
        # transformation: a vertical bar is escaped, because an unescaped
        # one ends the cell and every column after it shifts left.
        # `METADATA_INVALID_VALUE` names a shape set with bars in it and
        # rendered as five columns of nonsense until it was. Backtick spans
        # inside descriptions are intentional and are left alone.
        rendered = description.replace("|", "\\|")
        assert rendered in output, (
            f"Description for {code!r} ({description!r}) is registered in "
            f"ERROR_CODE_DESCRIPTIONS but missing from the rendered "
            f"table. The renderer must read from ERROR_CODE_DESCRIPTIONS."
        )


def test_doc_ref_error_codes_render_is_byte_stable() -> None:
    """Rendering the same fixture twice yields byte-equal output.

    The renderer's determinism contract (plan §M6 §5) says every doc
    output is byte-for-byte reproducible. The G7a source-registry branch
    must obey the same rule — sort order is alphabetical by code,
    severities pull from the deterministic registry, and no timestamps
    or wall-clock values leak in.
    """
    first = _render_fixture()
    second = _render_fixture()
    assert first == second


def test_doc_ref_error_codes_table_matches_traceability() -> None:
    """The rendered table's code list equals the traceability matrix's.

    Parity check that protects G7b's cutover. Both surfaces should be
    derived from the same registry; if the rendered table covers a code
    the traceability matrix does not (or vice versa), G7b's replacement
    of the hand-authored quick-reference block would silently lose a row.

    The test extracts code tokens from both sources via the same regex so
    surface-style differences (column count, severity formatting) do not
    affect the comparison.
    """
    output = _render_fixture()
    rendered_codes = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", output))
    # Drop the table header tokens and any backticked tokens that aren't
    # error codes (today none — but the registry-side filter keeps the
    # comparison defensive against future header drift).
    every_registered = set(SEVERITY_MATRIX.keys()) | set(
        OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE
    )
    rendered_codes &= every_registered

    traceability_text = TRACEABILITY_PATH.read_text(encoding="utf-8")
    traceability_codes = {
        m.group(1)
        for m in re.finditer(r"`([A-Z][A-Z0-9_]+)`", traceability_text)
    }
    traceability_codes &= every_registered

    assert rendered_codes == every_registered == traceability_codes, (
        f"Code-list parity broken. "
        f"rendered={sorted(rendered_codes)}, "
        f"traceability={sorted(traceability_codes)}, "
        f"registered={sorted(every_registered)}. "
        f"All three sets must agree — the rendered table is derived from "
        f"the registry, and the traceability doc must mention every "
        f"registered code (enforced by "
        f"test_error_codes_in_traceability)."
    )


def test_doc_ref_error_codes_severity_columns_render_correctly() -> None:
    """Per-mode severity values are formatted as ``error`` / ``warning`` / em-dash.

    Spot-check three reference codes that exercise the three formatting
    branches:
    - ``PARSE_ERROR``: ``error`` in every mode (always-error structural
      diagnostic);
    - ``POSSIBLE_UNRESOLVED_REFERENCE``: ``warning`` in migration/dev/strict,
      ``error`` only in release (the canonical mode-graded code);
    - ``MISSING_TEST_COVERAGE``: ``error`` only in release (release-only
      check; other modes show em-dash for "not applicable").
    """
    output = _render_fixture()

    def _row(code: str) -> str:
        for line in output.splitlines():
            if line.startswith(f"| `{code}`"):
                return line
        raise AssertionError(f"Code {code!r} not found in rendered table.")

    parse_error = _row("PARSE_ERROR")
    assert parse_error.count(" error ") >= 4, (
        f"PARSE_ERROR is always-error in every mode but the row "
        f"{parse_error!r} does not show 'error' four times."
    )

    pur = _row("POSSIBLE_UNRESOLVED_REFERENCE")
    assert " warning " in pur and " error " in pur, (
        f"POSSIBLE_UNRESOLVED_REFERENCE is the canonical warning→release-"
        f"error code but the row {pur!r} does not exhibit both."
    )

    mtc = _row("MISSING_TEST_COVERAGE")
    # "Not applicable" mode cells are rendered as em-dash.
    assert mtc.count(" — ") >= 3, (
        f"MISSING_TEST_COVERAGE is release-only but the row {mtc!r} does "
        f"not show three em-dash cells for migration/dev/strict."
    )


# ---------------------------------------------------------------------------
# ``ERROR_CODE_DESCRIPTIONS`` completeness pin
# ---------------------------------------------------------------------------


def test_error_code_descriptions_complete() -> None:
    """Every registered code has a description in ``ERROR_CODE_DESCRIPTIONS``.

    The registry is the single source of truth for the rendered table; a
    code without a description renders as an em-dash, which is silent
    drift the renderer cannot recover from. This test catches a future
    contributor who adds a code to ``SEVERITY_MATRIX`` without adding a
    description, before the rendered table becomes incomplete.
    """
    every_code = set(SEVERITY_MATRIX.keys()) | set(
        OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE
    )
    missing = sorted(every_code - set(ERROR_CODE_DESCRIPTIONS))
    extra = sorted(set(ERROR_CODE_DESCRIPTIONS) - every_code)
    assert not missing, (
        f"ERROR_CODE_DESCRIPTIONS is missing entries for the following "
        f"registered codes: {missing}. Add a one-sentence description for "
        f"each in s0ma_dsl.config (next to SEVERITY_MATRIX)."
    )
    assert not extra, (
        f"ERROR_CODE_DESCRIPTIONS carries entries for codes that are not "
        f"registered in SEVERITY_MATRIX or OUT_OF_MATRIX_CODES_THAT_MUST_"
        f"STILL_BE_TRACEABLE: {extra}. Either register the code "
        f"appropriately or remove the orphaned description."
    )
