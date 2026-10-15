"""Parser entry point for the s0ma DSL.

Implements a two-phase parsing strategy:
  Phase 1 — Line-based preprocessor splits .s0ma source into declaration blocks,
            extracting headers, field lines, and raw body text.
  Phase 2 — Lark LALR(1) parser handles structured field values (lists,
            depends_on entries, import entries).

The Transformer builds typed AST nodes from parsed data.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from dataclasses import field as _dc_field
from dataclasses import replace as _dc_replace
from pathlib import Path
from typing import Any, cast

from lark import Lark, Token, Transformer
from lark.exceptions import LarkError
from s0ma.decorators import component
from s0ma.types import ComponentKind
from s0ma.types import Layer as S0maLayer

from s0ma_dsl.ast_nodes.enums import (
    Coupling,
    EvaluatesAt,
    Kind,
    Layer,
    Relation,
    Visibility,
)
from s0ma_dsl.ast_nodes.nodes import (
    METADATA_INVALID_VALUE_MARKER,
    AssertBoolean,
    AssertComparison,
    BooleanPredicate,
    CellDecl,
    ComparisonPredicate,
    ConsumesViaDictEntry,
    DocGuideDecl,
    DocRefDecl,
    EntityRefAst,
    ExampleDecl,
    FilterExprAst,
    GanglionDecl,
    HelperDecl,
    InlineAxon,
    IntegrationDecl,
    InternalHelperEntry,
    IterationAst,
    MetadataValue,
    ModuleDecl,
    NerveDecl,
    ProvidesEntry,
    RequiresEntry,
    S0maModule,
    SectionAst,
    SourceLocation,
    StandaloneAxonDecl,
    TestDecl,
    UsesEntry,
)
from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maParseError, S0maSemanticError
from s0ma_dsl.parser.body_extractor import (
    extract_body,
    validate_body,
    validate_example_body,
)
from s0ma_dsl.parser.prose_parser import parse_prose
from s0ma_dsl.semantic_state import (
    CODE_FIELDS,
    FIELD_CLASSIFICATIONS,
    HEADER_LINE_FIELDS,
    SemanticState,
    authored_field_names,
    derived_field_names,
    semantic_fields,
    semantic_source_field,
)

__all__ = ["parse_s0ma", "parse_s0ma_with_warnings", "S0maParser"]

# ---------------------------------------------------------------------------
# Lark grammar loader (field-value parsing)
# ---------------------------------------------------------------------------

_GRAMMAR_PATH = Path(__file__).parent / "grammar.lark"


def _build_lark_parser(start: str) -> Lark:
    # W-3: explicit encoding — the locale default (e.g. a DBCS code page
    # on Windows) cannot decode the grammar file.
    grammar_text = _GRAMMAR_PATH.read_text(encoding="utf-8")
    return Lark(grammar_text, start=start, parser="lalr", strict=True)


# Lazily-initialised parsers for each entry point
_name_list_parser: Lark | None = None
_import_list_parser: Lark | None = None
_depends_on_parser: Lark | None = None
_entity_ref_parser: Lark | None = None
_filter_expr_parser: Lark | None = None
_section_entry_parser: Lark | None = None
_assert_pred_parser: Lark | None = None


def _get_name_list_parser() -> Lark:
    global _name_list_parser
    if _name_list_parser is None:
        _name_list_parser = _build_lark_parser("name_list")
    return _name_list_parser


def _get_import_list_parser() -> Lark:
    global _import_list_parser
    if _import_list_parser is None:
        _import_list_parser = _build_lark_parser("import_list")
    return _import_list_parser


def _get_depends_on_parser() -> Lark:
    global _depends_on_parser
    if _depends_on_parser is None:
        _depends_on_parser = _build_lark_parser("depends_on_entry")
    return _depends_on_parser


def _get_entity_ref_parser() -> Lark:
    global _entity_ref_parser
    if _entity_ref_parser is None:
        _entity_ref_parser = _build_lark_parser("entity_ref")
    return _entity_ref_parser


def _get_filter_expr_parser() -> Lark:
    global _filter_expr_parser
    if _filter_expr_parser is None:
        _filter_expr_parser = _build_lark_parser("filter_expr")
    return _filter_expr_parser


def _get_section_entry_parser() -> Lark:
    global _section_entry_parser
    if _section_entry_parser is None:
        _section_entry_parser = _build_lark_parser("section_entry")
    return _section_entry_parser


def _get_assert_pred_parser() -> Lark:
    global _assert_pred_parser
    if _assert_pred_parser is None:
        _assert_pred_parser = _build_lark_parser("assert_pred")
    return _assert_pred_parser


# Map of singular/plural ENTITY_KIND surface forms → canonical singular kind.
_ENTITY_KIND_NORMALISED = {
    "nerve": "nerve", "nerves": "nerve",
    "cell": "cell", "cells": "cell",
    "ganglion": "ganglion", "ganglia": "ganglion",
    "module": "module", "modules": "module",
    "example": "example", "examples": "example",
    "test": "test", "tests": "test",
}


# ---------------------------------------------------------------------------
# Phase 1: Line-based declaration splitter
# ---------------------------------------------------------------------------

# Regex patterns for declaration headers
_MODULE_RE = re.compile(r"^module\s+(\w+)\s*$")
_NERVE_RE = re.compile(r"^nerve\s+(\w+)\s*::\s*(\w+)\s*$")
_CELL_RE = re.compile(r"^cell\s+(\w+)\s*::\s*(\w+)\s*$")
_GANGLION_RE = re.compile(r"^ganglion\s+(\w+)\s*::\s*(\w+)\s*$")
_TEST_RE = re.compile(r"^test\s+(\w+)\s*::\s*(\w+)\s*$")
_AXON_RE = re.compile(r"^axon\s+(\w+)\s*->\s*(\w+)\s*$")
# M13 (feedback 5–6): module-private helper functions. The ``::`` LAYER
# qualifier mirrors nerve/cell/ganglion/test syntax. Helper names must
# start with an underscore by convention; the parser accepts any
# identifier, the body validator checks for the leading underscore.
_HELPER_RE = re.compile(r"^helper\s+(\w+)\s*::\s*(\w+)\s*$")
# POST-5 (0.16.0): first-class integration declaration. Mirrors the
# ``nerve``/``cell``/``ganglion``/``test``/``helper`` ``::`` LAYER
# qualifier syntax. The validator enforces ``layer == INFRASTRUCTURE``
# with ``LAYER_MISMATCH``.
_INTEGRATION_RE = re.compile(r"^integration\s+(\w+)\s*::\s*(\w+)\s*$")
# Documentation subsystem declaration headers (no :: LAYER qualifier — doc
# declarations describe components across the module and are not layered).
_DOC_REF_RE = re.compile(r"^doc-ref\s+(\w+)\s*$")
_DOC_GUIDE_RE = re.compile(r"^doc-guide\s+(\w+)\s*$")
_EXAMPLE_RE = re.compile(r"^example\s+(\w+)\s*$")
_COMMENT_RE = re.compile(r"^\s*#")
_SEPARATOR_RE = re.compile(r"^\s*---\s*$")
_FIELD_RE = re.compile(r"^    (\w+):\s*(.*)")
_CONTINUATION_RE = re.compile(r"^        (.+)")
# DSL-M2 (0.8.0, ADR-011 §(d)): the entry target accepts the qualified
# in-project form ``module.declaration`` — at most one dot (the lark
# ``dep_target`` rule enforces the exactly-one-dot contract; this
# splitter regex only needs to FORWARD dotted lines to it).
_DEPENDS_ON_ENTRY_RE = re.compile(r"^        \w+(?:\.\w+)*:\s*\{.*\}\s*$")

# M14 (feedback 5–6): YAML literal-block-scalar marker. When a field value is
# exactly ``|`` (optionally followed by whitespace), the parser switches to
# block-scalar mode and consumes subsequent more-indented lines until either
# (a) the indent drops back to the field column or below on a non-blank line,
# (b) a top-level declaration begins, or (c) a ``---`` body separator is hit.
# Common leading indent is stripped from the collected lines (smallest
# interior indentation becomes the baseline). Trailing whitespace is trimmed
# (default chomping). The folded form ``>`` and explicit chomping indicators
# ``|+``/``|-`` are out of scope for M14.
_BLOCK_SCALAR_RE = re.compile(r"^\|\s*$")
_FIELD_INDENT = 4  # number of leading spaces required for a top-level field
# Sentinel prefix used internally to mark a fields-dict entry as a
# pre-resolved block-scalar value. NUL is chosen because it is not legal
# in well-formed .s0ma source, so collision is impossible. See
# ``_parse_string_field`` for the consumer side.
_BLOCK_SCALAR_SENTINEL = "\x00<BLOCK_SCALAR>\x00"

# PRE-7 (0.14.0): YAML block-list-style entry. When a field value is empty
# and the next non-blank line is indented strictly past the field column
# and begins with ``-`` (followed by space or end-of-line), the parser
# switches to block-list mode and reassembles the items into the
# canonical inline ``[a, b, c]`` form so existing field parsers
# (``_parse_name_list``, ``_parse_import_list``) keep working unchanged.
_BLOCK_LIST_ITEM_RE = re.compile(r"^(\s+)-\s*(.*)$")

# POST-3a (0.15.0): structured ``provides:`` block-list entry. When an item
# inside a block list ends with ``:`` (a mapping key with no inline value),
# the parser switches to structured mode and collects the sub-fields
# (``returns:`` / ``expects:`` / ``guarantees:``) indented past the dash
# column. The structured form is encoded with the sentinel prefix below so
# downstream consumers ``_build_nerve`` can recognise it without re-parsing
# the raw lines. JSON is used for the payload — the keys are restricted to
# the four legal slots (``name`` / ``returns`` / ``expects`` /
# ``guarantees``) so the round-trip is total and the decoder is trivial.
_STRUCTURED_PROVIDES_SENTINEL = "\x00<STRUCTURED_PROVIDES>\x00"
_PROVIDES_ITEM_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
_PROVIDES_SUB_FIELD_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$",
)
_PROVIDES_SUB_FIELDS: frozenset[str] = frozenset({
    "returns",
    "expects",
    "guarantees",
})

# POST-3d (0.15.0): structured ``internal:`` block-list entry on nerves.
# Each ``- <name>: "<intent>"`` item names an inner helper function
# declared inside the nerve body that ``s0ma inspect`` surfaces under a
# separate "Internal helpers" sub-section without ever registering the
# helper as a component. The intent is optional — the inline form
# ``internal: [_foo, _bar]`` carries no intent strings; the block form
# accepts either ``- _foo`` (no intent) or ``- _foo: "..."`` (with
# intent). The structured payload is encoded with the sentinel below so
# the field-value table can keep its ``dict[str, str]`` shape; the
# ``_build_nerve`` consumer recognises the sentinel and reconstitutes
# the :class:`InternalHelperEntry` tuple.
_STRUCTURED_INTERNAL_SENTINEL = "\x00<STRUCTURED_INTERNAL>\x00"
_INTERNAL_ITEM_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
_INTERNAL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# POST-4b (0.15.0): inline-helper shorthand. The module's ``helpers:``
# field accepts a block list whose entries declare a helper with both
# its intent and body inline, removing the need for a separate
# ``helper <name> :: <layer>`` block. The canonical entry shape is::
#
#     helpers:
#       - helper _add @inline: "Quick addition" :: def _add(a, b): return a + b
#
# Each entry is encoded with the sentinel below so the field-value
# table keeps its ``dict[str, str]`` shape; ``parse_s0ma`` recognises
# the sentinel and reconstitutes the :class:`HelperDecl` list.
_INLINE_HELPERS_SENTINEL = "\x00<INLINE_HELPERS>\x00"
_INLINE_HELPER_ITEM_RE = re.compile(
    r"^helper\s+([A-Za-z_][A-Za-z0-9_]*)\s+@inline\s*:\s*"
    r"(\"[^\"]*\"|'[^']*')\s*::\s*(.+)$",
)

# POST-5 (0.16.0): structured ``manifest:`` block on integration
# declarations. The manifest is a nested YAML-style map indented past
# the field column. Each sub-line is either ``key: value`` (scalar) or
# ``key: [a, b]`` (inline list). Values are parsed best-effort:
# - ``true`` / ``false`` → Python bool
# - bare digits → ``int``
# - quoted strings → str (quotes stripped)
# - bracketed lists → list of trimmed items (best-effort)
# - everything else → str (verbatim, after trim)
# The result is encoded as a JSON payload behind the sentinel below so
# the field-value table keeps its ``dict[str, str]`` shape.
_STRUCTURED_MANIFEST_SENTINEL = "\x00<STRUCTURED_MANIFEST>\x00"
_MANIFEST_ITEM_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")

# POST-12d (0.16.0): structured ``consumes_via_dict:`` block on nerves.
# Each item is a sub-map with two mandatory keys: ``contract:`` and
# ``param:``. Both are bare identifiers (the contract resolves to a
# cell or a ``uses:`` target; the param resolves to a parameter on the
# nerve body's outer function). The block list is consumed by
# :func:`_consume_consumes_via_dict_block` and encoded under the
# sentinel below so the field-value table keeps its ``dict[str, str]``
# shape; ``_build_nerve`` recognises the sentinel and reconstitutes the
# :class:`ConsumesViaDictEntry` tuple.
_STRUCTURED_CONSUMES_VIA_DICT_SENTINEL = "\x00<STRUCTURED_CONSUMES_VIA_DICT>\x00"
_CONSUMES_VIA_DICT_SUB_FIELD_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$",
)
_CONSUMES_VIA_DICT_SUB_FIELDS: frozenset[str] = frozenset({
    "contract",
    "param",
})

# DSL-M1 (0.8.0): authored ``metadata:`` block map on nerve / cell /
# ganglion declarations (ADR-011 §(a), design rule L-1). The block is a
# flat map indented past the field column, mirroring the integration
# ``manifest:`` syntax; values are restricted to the L-1 shape set
# (quoted string | int | float | true/false | bracketed list of
# strings). The splitter consumes the block via
# :func:`_consume_metadata_block` and encodes the ordered entry list
# behind the sentinel below; ``_build_nerve`` / ``_build_cell`` /
# ``_build_ganglion`` decode it through :func:`_build_metadata_field`.
# Unlike the manifest consumer, duplicate keys and out-of-shape values
# do NOT raise at parse time — they ride to the semantic validator,
# which owns the three ``METADATA_*`` diagnostics (the entry list, not
# a dict, preserves duplicates and authored order for exactly that
# reason).
_STRUCTURED_METADATA_SENTINEL = "\x00<STRUCTURED_METADATA>\x00"
_METADATA_BOOL_TOKENS: frozenset[str] = frozenset({"true", "false"})
_METADATA_INT_RE = re.compile(r"^[+-]?\d+$")
_METADATA_FLOAT_RE = re.compile(
    r"^[+-]?(\d+\.\d*|\.\d+|\d+(\.\d*)?[eE][+-]?\d+)$",
)
_METADATA_BARE_LIST_ENTRY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Permissive key arm: a ``key: value`` line whose key is NOT
# identifier-shaped (``foo-bar: 1``) still belongs to the block — it is
# recorded verbatim so the validator can reject it with
# ``METADATA_INVALID_KEY`` instead of the block silently ending and the
# remaining lines being misattributed ("no silent failures").
_METADATA_ANY_KEY_RE = re.compile(r"^([^\s:]+)\s*:\s*(.*)$")


@dataclass
class _RawDeclaration:
    """A raw declaration block extracted by the line-based splitter."""

    decl_type: str  # "module", "nerve", "cell", "ganglion", "test", "axon",
                    # "helper", "integration", "doc_ref", "doc_guide", "example"
    header_names: tuple[str, ...]  # (name,) or (name, layer) or (source, target)
    fields: dict[str, str]  # field_name -> raw value string
    depends_on_lines: list[str]  # raw depends_on entry lines
    body: str | None  # raw body text (after ---)
    start_line: int
    end_line: int
    saw_separator: bool = False  # whether a --- separator was consumed
    body_start_line: int | None = None  # line number of first body line (if any)
    semantic_markers: dict[str, SemanticState] | None = None
    # Where each field sits (field name -> 1-based line of its first
    # occurrence), and every line of the description the splitter could
    # place nowhere: not a field, not part of a block, not a comment.
    # Both exist so that a line a person wrote is reported rather than
    # dropped — see ``_check_declaration_lines``.
    field_lines: dict[str, int] = _dc_field(default_factory=dict)
    stray_lines: list[tuple[int, str]] = _dc_field(default_factory=list)


_SEMANTIC_LIST_FIELDS = frozenset({
    "exports", "requires", "uses", "soft_requires", "runtime_only_requires",
    "deferred_requires", "exports_helpers", "provides", "returns", "raises",
    "interface", "internal_helpers", "expected_exceptions", "consumes_via_dict",
    "declares_attributes", "covered_by", "observes", "tests", "mocks",
    "dataclass_invariants", "placeholders", "covers", "sections", "asserts",
    "examples", "demonstrates",
})
_PENDING_STATE_RE = re.compile(r'^pending\(\s*("(?:[^"\\]|\\.)*")\s*\)$')


def _decode_semantic_marker(
    raw: str, *, field: str, filename: str, line: int
) -> SemanticState | None:
    """Decode the two whole-value semantic-state forms, if present."""

    stripped = raw.strip()
    if stripped == "none":
        return SemanticState.none()
    match = _PENDING_STATE_RE.fullmatch(stripped)
    if match is not None:
        try:
            reason = json.loads(match.group(1))
        except json.JSONDecodeError as exc:  # pragma: no cover - regex is defensive
            raise S0maParseError(
                code="SEMANTIC_PENDING_INVALID",
                message=f"Field '{field}' has an invalid pending reason string.",
                file=filename,
                line=line,
                column=1,
                severity="error",
                remediation=(
                    f'Use `{field}: pending("non-empty explanation")` with a valid '
                    "quoted JSON string."
                ),
            ) from exc
        if not reason.strip():
            raise S0maParseError(
                code="SEMANTIC_PENDING_REASON_EMPTY",
                message=f"Field '{field}' has pending state without a reason.",
                file=filename,
                line=line,
                column=1,
                severity="error",
                remediation=(
                    f'Use `{field}: pending("why this is unresolved")`; the reason '
                    "must contain non-whitespace text."
                ),
                context={"field": field},
            )
        return SemanticState.pending(reason)
    if stripped.startswith("pending("):
        raise S0maParseError(
            code="SEMANTIC_PENDING_INVALID",
            message=f"Field '{field}' has malformed pending state syntax.",
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=f'Use `{field}: pending("non-empty explanation")`.',
            context={"field": field, "value": stripped},
        )
    return None


_SEMANTIC_HEADER_FIELDS = HEADER_LINE_FIELDS
_SEMANTIC_BODY_FIELDS = CODE_FIELDS

# A line that reads as ``<name>:`` at any indentation. Used only to describe
# a line the splitter already declined — never to accept one.
_LOOSE_FIELD_RE = re.compile(r"^(\s*)(\w+):")

# Every field a person may write on a declaration, and every field s0ma
# computes, both in authored spelling. Read from the normative field matrix
# rather than kept as a second list; the generated quick reference reads the
# same two functions, so the lines it lists are the lines this check accepts.
_known_fields = authored_field_names
_derived_fields = derived_field_names


def _kind_word(decl_type: str) -> str:
    """A declaration kind as its author spells it: ``doc-ref``, not ``doc_ref``."""
    return decl_type.replace("_", "-")


def _nearest_field(name: str, known: frozenset[str]) -> str | None:
    """The known field ``name`` was most likely meant to be, if one is close."""
    close = difflib.get_close_matches(name, sorted(known), n=1, cutoff=0.75)
    return close[0] if close else None


def _omission_hint(
    raw: _RawDeclaration, source_field: str,
) -> tuple[str, dict[str, Any]]:
    """Where an omitted field probably is, when the page itself suggests it.

    ``SEMANTIC_REQUIRED_STATE_OMITTED`` is raised before any other finding
    about a declaration can be collected, so an author whose field is on
    the page — indented wrongly, or under a misspelt name — would otherwise
    be told only that it is missing. This names the line. It returns a
    sentence to put in front of the remediation and the facts for the
    report's context, or an empty pair when nothing on the page explains
    the omission.
    """
    for number, text in raw.stray_lines:
        match = _LOOSE_FIELD_RE.match(text)
        if match and match.group(2) == source_field:
            indent = len(match.group(1).expandtabs())
            return (
                f"Line {number} holds '{source_field}:' and starts with "
                f"{indent} space(s); a field starts with exactly "
                f"{_FIELD_INDENT}. ",
                {"misplaced_line": number, "indent": indent},
            )
    # ``depends_on:`` opened a block and none of the lines under it read as
    # an entry, so the field holds nothing although its line is there.
    opened = raw.field_lines.get(source_field)
    if source_field == "depends_on" and opened is not None:
        unread = [number for number, _text in raw.stray_lines if number > opened]
        if unread:
            return (
                f"Line {opened} opens 'depends_on:' and line {unread[0]} under "
                f"it could not be read as an entry; an entry starts with "
                f"exactly {_FIELD_INDENT * 2} spaces and reads "
                '`name: {relation: CALLS, carries: "...", coupling: LOOSE}`. ',
                {"misplaced_line": unread[0]},
            )
    known = _known_fields(raw.decl_type)
    for name in sorted(raw.fields, key=lambda item: raw.field_lines.get(item, 0)):
        if name in known:
            continue
        if _nearest_field(name, frozenset({source_field})) == source_field:
            number = raw.field_lines.get(name, raw.start_line)
            return (
                f"Line {number} holds '{name}:', which is not a field of a "
                f"{_kind_word(raw.decl_type)}; '{source_field}' was probably "
                f"meant. ",
                {"misspelt_field": name, "misspelt_line": number},
            )
    return "", {}


def _unknown_field_remediation(
    decl_type: str, name: str, known: frozenset[str],
) -> tuple[str, str | None]:
    """What to do about a field ``decl_type`` does not have, and the likely fix."""
    kind = _kind_word(decl_type)
    if name == "module_location":
        return (
            "s0ma takes it from the module header of the file the "
            f"{kind} is written in. Remove this line.",
            None,
        )
    if name in _SEMANTIC_HEADER_FIELDS.get(decl_type, frozenset()):
        return (
            f"A {kind}'s {name} is written on its first line, not as a field. "
            "Remove this line.",
            None,
        )
    if name in _SEMANTIC_BODY_FIELDS:
        return (
            "The code is written after the `---` line, not as a field. "
            "Remove this line.",
            None,
        )
    nearest = _nearest_field(name, known)
    if nearest is not None:
        return (
            f"Did you mean '{nearest}'? Correct the name, or remove the line.",
            nearest,
        )
    owners = sorted(
        _kind_word(other)
        for other in FIELD_CLASSIFICATIONS
        if other != decl_type and name in _known_fields(other)
    )
    if owners:
        advice = (
            f"'{name}' is a field of {', '.join(owners)}; a {kind} does not "
            "have it. Remove the line"
        )
        if decl_type == "helper":
            advice += (
                ", or declare this part as a nerve if it needs a contract of "
                "its own"
            )
        return advice + ".", None
    return (
        f"A {kind}'s fields are: {', '.join(sorted(known))}. Correct the "
        "name, or remove the line.",
        None,
    )


def _check_declaration_lines(
    declarations: list[_RawDeclaration],
    filename: str,
    mode: StrictnessMode,
) -> list[S0maParseError | S0maSemanticError]:
    """Report every line of a description that would otherwise be dropped.

    Two reports, both about something a person wrote and s0ma did not read:

    * ``UNKNOWN_FIELD`` — a well-formed field line whose name this kind of
      declaration does not have. Before this check the line was stored and
      never read, so a misspelt optional field silently did nothing.
    * ``UNRECOGNIZED_LINE`` — a line that is not a field, not part of a
      block and not a comment. Almost always a field, or an entry of a
      block, indented by the wrong number of spaces.

    Collected rather than raised, at the severity the matrix gives each
    code for ``mode``, so they ride the same collection point as the body
    findings: a warning is returned to the caller and the first error is
    raised.
    """
    findings: list[S0maParseError | S0maSemanticError] = []
    unknown_severity = get_severity("UNKNOWN_FIELD", mode)
    stray_severity = get_severity("UNRECOGNIZED_LINE", mode)

    for raw in declarations:
        kind = _kind_word(raw.decl_type)
        owner = raw.header_names[0]
        known = _known_fields(raw.decl_type)
        derived = _derived_fields(raw.decl_type)

        if unknown_severity is not None:
            for name in sorted(
                raw.fields, key=lambda item: raw.field_lines.get(item, 0),
            ):
                if name in known or name in derived:
                    continue
                remediation, suggestion = _unknown_field_remediation(
                    raw.decl_type, name, known,
                )
                context: dict[str, Any] = {
                    "declaration_type": raw.decl_type,
                    "declaration_name": owner,
                    "field": name,
                }
                if suggestion is not None:
                    context["suggestion"] = suggestion
                findings.append(S0maParseError(
                    code="UNKNOWN_FIELD",
                    message=f"Unknown field '{name}' on {kind} '{owner}'.",
                    file=filename,
                    line=raw.field_lines.get(name, raw.start_line),
                    column=1,
                    severity=unknown_severity,
                    remediation=remediation,
                    context=context,
                ))

        if stray_severity is None:
            continue
        for number, text in raw.stray_lines:
            match = _LOOSE_FIELD_RE.match(text)
            indent = len(text) - len(text.lstrip())
            if match and match.group(2) in known:
                message = (
                    f"Line {number} looks like the field '{match.group(2)}' "
                    f"of {kind} '{owner}', but it starts with {indent} "
                    f"space(s)."
                )
                remediation = (
                    f"Start the line with exactly {_FIELD_INDENT} spaces. A "
                    "line that belongs to a block goes further in, under the "
                    "line that opens the block."
                )
            else:
                message = (
                    f"Line {number} of {kind} '{owner}' is not a field, not "
                    f"part of a block, and not a comment: {text.strip()!r}."
                )
                remediation = (
                    f"Write it as a field (`name: value`, starting with "
                    f"exactly {_FIELD_INDENT} spaces), move it under the "
                    "block it belongs to, or remove it. A note to a reader "
                    "starts with `#`."
                )
            findings.append(S0maParseError(
                code="UNRECOGNIZED_LINE",
                message=message,
                file=filename,
                line=number,
                column=1,
                severity=stray_severity,
                remediation=remediation,
                context={
                    "declaration_type": raw.decl_type,
                    "declaration_name": owner,
                    "line_text": text.strip(),
                    "indent": indent,
                },
            ))

    return findings


def _semantic_field_authored(raw: _RawDeclaration, field: str) -> bool:
    """Return whether *field* has an authored source representation."""

    if field in _SEMANTIC_HEADER_FIELDS.get(raw.decl_type, frozenset()):
        return True
    if field in _SEMANTIC_BODY_FIELDS:
        return raw.saw_separator and raw.body is not None and bool(raw.body.strip())
    source_field = semantic_source_field(raw.decl_type, field)
    if field == "depends_on":
        return source_field in raw.fields or bool(raw.depends_on_lines)
    return source_field in raw.fields


def _raise_semantic_contract_error(
    *,
    code: str,
    raw: _RawDeclaration,
    field: str,
    filename: str,
    message: str,
    remediation: str,
    state: str | None = None,
    extra_context: dict[str, Any] | None = None,
) -> None:
    context: dict[str, Any] = {
        "declaration_type": raw.decl_type,
        "declaration_name": raw.header_names[0],
        "field": field,
    }
    if state is not None:
        context["state"] = state
    if extra_context:
        context.update(extra_context)
    raise S0maParseError(
        code=code,
        message=message,
        file=filename,
        line=raw.start_line,
        column=1,
        severity="error",
        remediation=remediation,
        context=context,
    )


def _prepare_semantic_markers(
    declarations: list[_RawDeclaration],
    filename: str,
    *,
    allow_legacy_omissions: bool = False,
) -> None:
    """Validate field-state contracts and install a primitive projection.

    Normal parsing is strict as of M3B: every semantic-required-state field
    must be present, ``none``/``pending`` must be legal for that exact field,
    and derived fields may not be authored.  ``allow_legacy_omissions`` is an
    intentionally private escape hatch used only by ``s0ma migrate grammar``
    during the documented compatibility window.  The neutral primitive
    projection remains an internal implementation bridge for explicit tagged
    values; it is not a compatibility reader for omitted source state.
    """

    for declaration in declarations:
        contract_name = declaration.decl_type
        try:
            contract_fields = semantic_fields(contract_name)
            all_fields = FIELD_CLASSIFICATIONS[contract_name]
        except KeyError:
            continue
        for field, classification in all_fields.items():
            if classification.field_class != "derived":
                continue
            source_field = semantic_source_field(contract_name, field)
            if source_field in declaration.fields:
                _raise_semantic_contract_error(
                    code="SEMANTIC_DERIVED_FIELD_AUTHORED",
                    raw=declaration,
                    field=field,
                    filename=filename,
                    message=(
                        f"Derived field '{field}' may not be authored on "
                        f"{contract_name} '{declaration.header_names[0]}'."
                    ),
                    remediation=(
                        f"Remove the '{source_field}:' field; s0ma computes "
                        f"'{field}' from source shape, resolution, or emission."
                    ),
                )
        markers: dict[str, SemanticState] = {}
        for field, classification in contract_fields.items():
            source_field = semantic_source_field(contract_name, field)
            authored = _semantic_field_authored(declaration, field)
            if not authored:
                if (
                    classification.field_class == "semantic-required-state"
                    and not (allow_legacy_omissions and classification.allow_none)
                ):
                    allowed = ["a real value"]
                    if classification.allow_none:
                        allowed.append("`none`")
                    if classification.allow_pending:
                        allowed.append('`pending("non-empty reason")`')
                    # The field may be on the page after all — indented
                    # wrongly, or under a misspelt name. Say so first:
                    # this error is raised before the line reports can be
                    # collected, so it is the only one the author sees.
                    hint, hint_context = _omission_hint(declaration, source_field)
                    _raise_semantic_contract_error(
                        code="SEMANTIC_REQUIRED_STATE_OMITTED",
                        raw=declaration,
                        field=field,
                        filename=filename,
                        message=(
                            f"Semantic-required field '{field}' is omitted from "
                            f"{contract_name} '{declaration.header_names[0]}'."
                        ),
                        remediation=(
                            hint +
                            f"Author '{source_field}:' with " + ", ".join(allowed) +
                            "; for a legacy project run `s0ma migrate grammar --apply`."
                        ),
                        extra_context=hint_context,
                    )
                continue
            state = None
            if source_field in declaration.fields:
                state = _decode_semantic_marker(
                    declaration.fields[source_field],
                    field=field,
                    filename=filename,
                    line=declaration.start_line,
                )
            if state is None:
                continue
            if state.state == "none" and not classification.allow_none:
                _raise_semantic_contract_error(
                    code="SEMANTIC_NONE_NOT_ALLOWED",
                    raw=declaration,
                    field=field,
                    filename=filename,
                    state="none",
                    message=(
                        f"Semantic field '{field}' on {contract_name} "
                        f"'{declaration.header_names[0]}' cannot be `none`."
                    ),
                    remediation=(
                        f"Replace '{source_field}: none' with a real value"
                        + (
                            f" or '{source_field}: pending(\"non-empty reason\")'."
                            if classification.allow_pending else "."
                        )
                    ),
                )
            if state.state == "pending" and not classification.allow_pending:
                _raise_semantic_contract_error(
                    code="SEMANTIC_PENDING_NOT_ALLOWED",
                    raw=declaration,
                    field=field,
                    filename=filename,
                    state="pending",
                    message=(
                        f"Semantic field '{field}' on {contract_name} "
                        f"'{declaration.header_names[0]}' cannot be pending."
                    ),
                    remediation=f"Replace '{source_field}:' with its required real value.",
                )
            markers[field] = state
            if field == "covered_by":
                # ``covered_by: []`` is intentionally a malformed authored
                # evidence claim, represented by one empty marker. The
                # explicit semantic state ``covered_by: none`` must project
                # to true absence instead so it cannot earn coverage or fire
                # COVERED_BY_EMPTY.
                declaration.fields[source_field] = ""
            elif field in _SEMANTIC_LIST_FIELDS:
                declaration.fields[source_field] = "[]"
            elif field == "latency_ms":
                # The legacy builder branches on key presence before parsing
                # the integer, so its neutral projection is true omission.
                declaration.fields.pop(source_field)
            elif field == "manifest":
                declaration.fields[source_field] = "{}"
            else:
                declaration.fields[source_field] = '""'
        declaration.semantic_markers = markers


def _attach_semantic_states(
    node: Any, declaration_type: str, raw: _RawDeclaration | None
) -> Any:
    """Attach the canonical tagged field map to one parsed AST node."""

    markers = raw.semantic_markers if raw and raw.semantic_markers else {}
    present = set(raw.fields) if raw is not None else set()
    states: list[tuple[str, SemanticState]] = []
    for field, classification in semantic_fields(declaration_type).items():
        marker = markers.get(field)
        if marker is not None:
            states.append((field, marker))
            continue
        value = getattr(node, field, None)
        is_body = field in {"body", "prose_body", "python_body"}
        is_identity = field in {
            "name", "layer", "kind", "visibility", "evaluates_at", "scope",
            "source", "target", "relation", "carries", "coupling",
            "module_location",
        }
        source_field = semantic_source_field(declaration_type, field)
        authored = (
            source_field in present
            or is_identity
            or (is_body and value is not None)
        )
        if classification.field_class == "semantic-conditional-state" and not authored:
            continue
        if not authored and classification.allow_none:
            states.append((field, SemanticState.none()))
        else:
            states.append((field, SemanticState.valued(value)))
    return _dc_replace(node, semantic_states=tuple(states))


def _finalize_semantic_states(
    module: S0maModule, raw_decls: list[_RawDeclaration]
) -> S0maModule:
    """Populate every declaration's typed state map after body extraction."""

    by_key = {
        (raw.decl_type, raw.start_line): raw
        for raw in raw_decls
    }

    def raw_for(node: Any, raw_type: str) -> _RawDeclaration | None:
        line = node.location.start_line if node.location is not None else -1
        return by_key.get((raw_type, line))

    return S0maModule(
        module=_attach_semantic_states(
            module.module, "module", raw_for(module.module, "module")
        ),
        nerves=tuple(
            _attach_semantic_states(node, "nerve", raw_for(node, "nerve"))
            for node in module.nerves
        ),
        cells=tuple(
            _attach_semantic_states(node, "cell", raw_for(node, "cell"))
            for node in module.cells
        ),
        ganglia=tuple(
            _attach_semantic_states(node, "ganglion", raw_for(node, "ganglion"))
            for node in module.ganglia
        ),
        tests=tuple(
            _attach_semantic_states(node, "test", raw_for(node, "test"))
            for node in module.tests
        ),
        axons=tuple(
            _attach_semantic_states(node, "axon", raw_for(node, "axon"))
            for node in module.axons
        ),
        helpers=tuple(
            _attach_semantic_states(node, "helper", raw_for(node, "helper"))
            for node in module.helpers
        ),
        integrations=tuple(
            _attach_semantic_states(
                node, "integration", raw_for(node, "integration")
            )
            for node in module.integrations
        ),
        doc_refs=tuple(
            _attach_semantic_states(node, "doc_ref", raw_for(node, "doc_ref"))
            for node in module.doc_refs
        ),
        doc_guides=tuple(
            _attach_semantic_states(
                node, "doc_guide", raw_for(node, "doc_guide")
            )
            for node in module.doc_guides
        ),
        examples=tuple(
            _attach_semantic_states(node, "example", raw_for(node, "example"))
            for node in module.examples
        ),
    )


def _leading_spaces(line: str) -> int:
    """Return the number of leading space characters in ``line``."""
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        else:
            break
    return n


def _consume_block_scalar(
    lines: list[str],
    start_index: int,
    field_name: str,
    field_indent: int,
    field_line: int,
    filename: str,
) -> tuple[str, int]:
    """Consume a YAML literal-block-scalar (``|``) starting at ``start_index``.

    Reads consecutive lines whose indentation is strictly greater than
    ``field_indent`` (the column of the field key). Blank lines that fall
    inside the block are preserved. Stops when a non-blank line has
    indentation ``<= field_indent``, a ``---`` body separator appears, or
    EOF is reached.

    Once the lines are collected, the smallest interior indent (over
    non-blank lines) becomes the baseline; that many spaces are stripped
    from the front of every collected line. Trailing whitespace on each
    line is preserved interior, but the final trailing newline(s)/spaces
    are trimmed (default-chomping equivalent — we keep the simpler "strip
    trailing whitespace from joined value" behavior, which preserves
    interior structure without leaving stray trailing newlines).

    Returns ``(content, next_index)`` where ``next_index`` is the index
    of the first line that did NOT belong to the block scalar.

    Raises :class:`S0maParseError` if the block has no indented content
    line — silent acceptance of an empty block would defeat M14's
    purpose.
    """
    collected: list[tuple[int, str]] = []  # (indent, raw_text_after_indent)
    i = start_index
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.rstrip()

        # Blank line: provisionally include — only kept if a later non-blank
        # block line follows.
        if not stripped:
            collected.append((-1, ""))  # sentinel indent for blank line
            i += 1
            continue

        # Body separator ends the block.
        if _SEPARATOR_RE.match(stripped):
            break

        # Top-level declaration (no leading indent) ends the block.
        if not line.startswith(" "):
            break

        indent = _leading_spaces(line)
        if indent <= field_indent:
            # Same-column-or-shallower content ends the block.
            break

        # Comments inside a block scalar are NOT comments — YAML literal
        # blocks pass them through verbatim. We accept any text here.
        collected.append((indent, line[indent:]))
        i += 1

    # Trim trailing blank lines that don't belong to the block.
    while collected and collected[-1][0] == -1:
        collected.pop()
        # Note: those blank lines are not consumed by the block — but we
        # already advanced ``i`` past them. We need to back ``i`` up so the
        # outer field loop can re-process them as plain blank lines.
        i -= 1

    if not collected:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"Block-scalar field '{field_name}' has no indented content. "
                f"After '{field_name}: |' you must follow with at least one "
                f"line indented more than {field_indent} spaces."
            ),
            file=filename,
            line=field_line,
            column=1,
            severity="error",
            remediation=(
                f"Either provide indented content for the block scalar, e.g.:\n"
                f"    {field_name}: |\n"
                f"        your text here\n"
                f"or use a quoted single-line form: {field_name}: \"...\""
            ),
        )

    # Smallest indent among non-blank lines becomes the baseline.
    non_blank_indents = [ind for ind, _ in collected if ind != -1]
    baseline = min(non_blank_indents)

    # Validate baseline > field_indent (already guaranteed by collection
    # rule, but keep the assertion explicit to catch future regressions).
    if baseline <= field_indent:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"Block-scalar field '{field_name}': content indentation "
                f"({baseline}) must be strictly greater than the field "
                f"column ({field_indent})."
            ),
            file=filename,
            line=field_line,
            column=1,
            severity="error",
            remediation=(
                f"Indent every content line of the block scalar by more "
                f"than {field_indent} spaces."
            ),
        )

    out_lines: list[str] = []
    for indent, text in collected:
        if indent == -1:
            # Blank line within the block — emit empty string.
            out_lines.append("")
        else:
            extra = indent - baseline  # >= 0; preserves indented sub-lines
            out_lines.append(" " * extra + text.rstrip())

    content = "\n".join(out_lines).rstrip()
    return content, i


def _next_line_is_block_list(
    lines: list[str], start_index: int, field_indent: int,
) -> bool:
    """Peek ahead to see if the next non-blank line begins a block list.

    Looks past comments and blank lines for the first non-blank line.
    Returns True when that line is indented past ``field_indent`` and
    matches the ``- item`` shape. Used by ``_split_declarations`` to
    decide whether an empty-value field should consume a block list.
    """
    i = start_index
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.rstrip()
        if not stripped:
            i += 1
            continue
        if _COMMENT_RE.match(stripped):
            i += 1
            continue
        if not line.startswith(" "):
            return False
        if _leading_spaces(line) <= field_indent:
            return False
        return _BLOCK_LIST_ITEM_RE.match(line) is not None
    return False


def _next_line_is_indented_map(
    lines: list[str], start_index: int, field_indent: int,
) -> bool:
    """Peek ahead to see if the next non-blank line begins an indented map.

    Returns True when the first non-blank, non-comment line is indented
    past ``field_indent`` and matches ``<identifier>:``. Used by
    ``_split_declarations`` to decide whether an empty-value ``manifest:``
    field on an integration declaration should consume a nested map
    (rather than a block list). POST-5 (0.16.0).
    """
    i = start_index
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.rstrip()
        if not stripped:
            i += 1
            continue
        if _COMMENT_RE.match(stripped):
            i += 1
            continue
        if not line.startswith(" "):
            return False
        indent = _leading_spaces(line)
        if indent <= field_indent:
            return False
        # The line begins a map iff it is *not* a block-list item and
        # matches ``key: ...``.
        if _BLOCK_LIST_ITEM_RE.match(line) is not None:
            return False
        body_text = line[indent:]
        return _MANIFEST_ITEM_KEY_RE.match(body_text) is not None
    return False


def _next_line_is_metadata_map(
    lines: list[str], start_index: int, field_indent: int,
) -> bool:
    """Like :func:`_next_line_is_indented_map`, plus malformed keys.

    DSL-M1: the ``metadata:`` block routes through its consumer even
    when the FIRST entry's key is not identifier-shaped (``foo-bar: 1``)
    so the semantic validator can reject the key with
    ``METADATA_INVALID_KEY`` — if routing declined, the block would
    fall through to the inline-form arm and the author would get the
    wrong diagnostic.
    """
    if _next_line_is_indented_map(lines, start_index, field_indent):
        return True
    i = start_index
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.rstrip()
        if not stripped:
            i += 1
            continue
        if _COMMENT_RE.match(stripped):
            i += 1
            continue
        if not line.startswith(" "):
            return False
        indent = _leading_spaces(line)
        if indent <= field_indent:
            return False
        if _BLOCK_LIST_ITEM_RE.match(line) is not None:
            return False
        return _METADATA_ANY_KEY_RE.match(line[indent:]) is not None
    return False


def _consume_block_list(
    lines: list[str],
    start_index: int,
    field_name: str,
    field_indent: int,
    field_line: int,
    filename: str,
) -> tuple[str, int]:
    """Consume a YAML block-list (``- item`` per line) starting at ``start_index``.

    Reads consecutive lines whose indentation is strictly greater than
    ``field_indent`` and which begin with ``-`` (followed by space or
    end-of-line). All items in the block must share the same indent
    column. Comments (lines whose first non-blank character is ``#``)
    inside the block are skipped silently. Blank lines terminate the
    block.

    Returns ``(inline_form, next_index)`` where ``inline_form`` is the
    canonical ``"[item1, item2, item3]"`` shape so existing field
    parsers (``_parse_name_list``, ``_parse_import_list``) consume the
    block-list output unchanged.

    Raises :class:`S0maParseError` on:
    - empty block (``EMPTY_BLOCK_LIST``),
    - inconsistent item indentation (``INCONSISTENT_BLOCK_LIST_INDENT``).
    """
    items: list[str] = []
    i = start_index
    n = len(lines)
    list_indent: int | None = None

    while i < n:
        line = lines[i]
        stripped = line.rstrip()

        # Blank line ends the block.
        if not stripped:
            break

        # Body separator ends the block.
        if _SEPARATOR_RE.match(stripped):
            break

        # Top-level declaration ends the block.
        if not line.startswith(" "):
            break

        # Skip comments inside the block.
        if _COMMENT_RE.match(stripped):
            i += 1
            continue

        indent = _leading_spaces(line)
        if indent <= field_indent:
            # Same-column-or-shallower content ends the block.
            break

        match = _BLOCK_LIST_ITEM_RE.match(line)
        if match is None:
            # Indented but not a list-item line — block ends.
            break

        if list_indent is None:
            list_indent = indent
        elif indent != list_indent:
            raise S0maParseError(
                code="INCONSISTENT_BLOCK_LIST_INDENT",
                message=(
                    f"Block-list field '{field_name}': item at line "
                    f"{i + 1} has indentation {indent} but earlier items "
                    f"use indentation {list_indent}. All items in a block "
                    f"list must share the same indent column."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    f"Align every '- item' line under '{field_name}:' "
                    f"to the same column."
                ),
            )

        # Strip trailing inline comment ("- foo  # note").
        item_text = match.group(2)
        if "#" in item_text:
            # Take everything before the first ``#``. Quoted strings
            # complicate this, but the inline-form parser handles those
            # downstream; for the block-list form we keep the simple
            # rule: ``#`` outside a quoted string is a comment.
            in_quote = False
            cut = -1
            for idx, ch in enumerate(item_text):
                if ch == '"':
                    in_quote = not in_quote
                elif ch == "#" and not in_quote:
                    cut = idx
                    break
            if cut >= 0:
                item_text = item_text[:cut]
        item_text = item_text.strip()
        if item_text:
            items.append(item_text)
        i += 1

    if not items:
        raise S0maParseError(
            code="EMPTY_BLOCK_LIST",
            message=(
                f"Block-list field '{field_name}' has no items. "
                f"Either provide at least one '- item' line indented "
                f"more than {field_indent} spaces, or use the inline "
                f"form: {field_name}: []."
            ),
            file=filename,
            line=field_line,
            column=1,
            severity="error",
            remediation=(
                f"Add at least one '- item' line under "
                f"'{field_name}:' (indented more than {field_indent} "
                f"spaces) or use the inline form."
            ),
        )

    inline = "[" + ", ".join(items) + "]"
    return inline, i


def _peek_structured_provides(
    lines: list[str], start_index: int, field_indent: int,
) -> bool:
    """Peek ahead to see if the next block-list item is a structured entry.

    Returns ``True`` when the first list item under ``provides:`` is of
    the shape ``- name:`` (a trailing colon with no inline value) AND a
    following sub-field line indented past the dash column exists. This
    is the trigger that distinguishes the structured form
    (``- name:\\n      returns: "..."``) from the flat block form
    (``- name``). The peek is *non-destructive* — it never consumes
    lines.

    POST-3a (0.15.0). Used only by the ``provides:`` consumer in
    ``_split_declarations`` to decide which block-list flavour to run.
    Other fields keep using the flat consumer unconditionally.
    """
    i = start_index
    n = len(lines)
    # Find the first list-item line.
    while i < n:
        line = lines[i]
        stripped = line.rstrip()
        if not stripped:
            i += 1
            continue
        if _COMMENT_RE.match(stripped):
            i += 1
            continue
        if not line.startswith(" "):
            return False
        if _leading_spaces(line) <= field_indent:
            return False
        m = _BLOCK_LIST_ITEM_RE.match(line)
        if m is None:
            return False
        item_text = m.group(2).strip()
        # Strip trailing inline comment.
        if "#" in item_text:
            in_quote = False
            cut = -1
            for idx, ch in enumerate(item_text):
                if ch == '"':
                    in_quote = not in_quote
                elif ch == "#" and not in_quote:
                    cut = idx
                    break
            if cut >= 0:
                item_text = item_text[:cut].strip()
        # Structured trigger: item_text is ``<name>:`` with nothing after.
        key_match = _PROVIDES_ITEM_KEY_RE.match(item_text)
        if key_match is None:
            return False
        if key_match.group(2).strip():
            # Inline value (``- name: value``) — not the structured form.
            return False
        # Check if the next non-blank line is indented past the dash column.
        dash_indent = _leading_spaces(line)
        j = i + 1
        while j < n:
            nl = lines[j]
            ns = nl.rstrip()
            if not ns:
                j += 1
                continue
            if _COMMENT_RE.match(ns):
                j += 1
                continue
            if not nl.startswith(" "):
                return False
            ni = _leading_spaces(nl)
            if ni <= dash_indent:
                # Same-column-or-shallower — likely the next item or end.
                # An entry with NO sub-fields is degenerate but technically
                # allowed (e.g. ``- name:`` with nothing under it). Treat
                # any ``<name>:`` shape as the structured form regardless,
                # so the error path reports a clear "no sub-fields" message
                # instead of falling through to the flat consumer (which
                # would treat ``name:`` as a literal name and fail later).
                return True
            return True
        return True
    return False


def _consume_structured_provides_block(
    lines: list[str],
    start_index: int,
    field_indent: int,
    field_line: int,
    filename: str,
) -> tuple[str, int]:
    """Consume a structured ``provides:`` block (POST-3a, 0.15.0).

    Reads block-list items of the form::

        - <name>:
              returns: "..."
              expects: "..."
              guarantees: "..."
        - <name>:
              returns: "..."

    Each item's sub-fields are *optional* — an author can declare just
    ``returns:`` or just ``guarantees:`` without supplying the others.
    Sub-fields outside the legal set (``returns`` / ``expects`` /
    ``guarantees``) raise ``PARSE_ERROR`` with a list of valid names.

    Returns ``(encoded, next_index)`` where ``encoded`` is the JSON-
    serialised list of dicts prefixed with
    :data:`_STRUCTURED_PROVIDES_SENTINEL`. ``_build_nerve`` recognises
    the sentinel and reconstitutes the
    :class:`~s0ma_dsl.ast_nodes.nodes.ProvidesEntry` list.

    Raises :class:`S0maParseError` on:
    - duplicate item names (``DUPLICATE_PROVIDES_NAME``),
    - empty block (``EMPTY_BLOCK_LIST``),
    - inconsistent indentation (``INCONSISTENT_BLOCK_LIST_INDENT``),
    - unknown sub-field key (``PARSE_ERROR``),
    - mixed structured + flat items in the same block
      (``MIXED_PROVIDES_FORMS``).
    """
    entries: list[dict[str, str]] = []
    seen_names: set[str] = set()
    i = start_index
    n = len(lines)
    list_indent: int | None = None
    current: dict[str, str] | None = None
    sub_indent: int | None = None

    def _flush() -> None:
        if current is not None:
            entries.append(current)

    while i < n:
        line = lines[i]
        stripped = line.rstrip()

        if not stripped:
            i += 1
            continue

        if _SEPARATOR_RE.match(stripped):
            break

        if not line.startswith(" "):
            break

        indent = _leading_spaces(line)
        if indent <= field_indent:
            break

        if _COMMENT_RE.match(stripped):
            i += 1
            continue

        list_match = _BLOCK_LIST_ITEM_RE.match(line)
        if list_match is not None and (list_indent is None or indent == list_indent):
            # New item — flush the previous one.
            _flush()
            current = None
            sub_indent = None

            if list_indent is None:
                list_indent = indent

            item_text = list_match.group(2).strip()
            # Strip trailing inline comment.
            if "#" in item_text:
                in_quote = False
                cut = -1
                for idx, ch in enumerate(item_text):
                    if ch == '"':
                        in_quote = not in_quote
                    elif ch == "#" and not in_quote:
                        cut = idx
                        break
                if cut >= 0:
                    item_text = item_text[:cut].strip()

            key_match = _PROVIDES_ITEM_KEY_RE.match(item_text)
            if key_match is None or key_match.group(2).strip():
                # Either not a ``name:`` shape, or has an inline value
                # (``- name: value`` would be a different grammar). Both
                # are flat-form items the structured consumer cannot
                # blend — reject with a precise message.
                raise S0maParseError(
                    code="MIXED_PROVIDES_FORMS",
                    message=(
                        f"Block-list field 'provides': item at line "
                        f"{i + 1} mixes the structured form (where each "
                        f"item is '- <name>:' followed by indented "
                        f"sub-fields) with the flat form (where each "
                        f"item is '- <name>'). Pick one form per "
                        f"'provides:' block."
                    ),
                    file=filename,
                    line=i + 1,
                    column=1,
                    severity="error",
                    remediation=(
                        "Either rewrite every item as '- name' (flat "
                        "form) or as '- name:' with indented "
                        "returns:/expects:/guarantees: sub-fields "
                        "(structured form)."
                    ),
                )
            name = key_match.group(1)
            if name in seen_names:
                raise S0maParseError(
                    code="DUPLICATE_PROVIDES_NAME",
                    message=(
                        f"Block-list field 'provides': duplicate entry "
                        f"name {name!r} at line {i + 1}. Each "
                        f"'provides:' name must be unique within the "
                        f"nerve."
                    ),
                    file=filename,
                    line=i + 1,
                    column=1,
                    severity="error",
                    remediation=(
                        f"Remove the duplicate '{name}:' entry, or "
                        f"rename one of the entries so the operation "
                        f"names are unique."
                    ),
                )
            seen_names.add(name)
            current = {"name": name}
            i += 1
            continue

        if list_match is not None and list_indent is not None and indent != list_indent:
            raise S0maParseError(
                code="INCONSISTENT_BLOCK_LIST_INDENT",
                message=(
                    f"Block-list field 'provides': item at line "
                    f"{i + 1} has indentation {indent} but earlier "
                    f"items use indentation {list_indent}. All items "
                    f"in a block list must share the same indent "
                    f"column."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Align every '- item' line under 'provides:' to "
                    "the same column."
                ),
            )

        # Indented past the dash column — a sub-field line.
        if current is None:
            # Indented content without a preceding ``-`` item — bail.
            break

        if list_indent is not None and indent <= list_indent:
            # Same indent as the list itself but not a ``- item`` —
            # block ends.
            break

        if sub_indent is None:
            sub_indent = indent
        elif indent != sub_indent:
            raise S0maParseError(
                code="INCONSISTENT_BLOCK_LIST_INDENT",
                message=(
                    f"Block-list field 'provides': sub-field at line "
                    f"{i + 1} has indentation {indent} but earlier "
                    f"sub-fields use indentation {sub_indent}. All "
                    f"sub-fields under a single 'provides:' item must "
                    f"share the same indent column."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Align every 'returns:' / 'expects:' / "
                    "'guarantees:' line under each '- name:' to the "
                    "same column."
                ),
            )

        sub_text = line[indent:].rstrip()
        sub_match = _PROVIDES_SUB_FIELD_RE.match(sub_text)
        if sub_match is None:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'provides': unrecognised "
                    f"content {sub_text!r} at line {i + 1} under a "
                    f"structured item. Expected 'returns:', "
                    f"'expects:', or 'guarantees:'."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Each sub-line under a '- name:' entry must be "
                    "one of: returns: \"...\", expects: \"...\", "
                    "guarantees: \"...\"."
                ),
            )

        sub_key = sub_match.group(1)
        sub_value = sub_match.group(2).rstrip()

        if sub_key not in _PROVIDES_SUB_FIELDS:
            valid = ", ".join(sorted(_PROVIDES_SUB_FIELDS))
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'provides': unknown sub-field "
                    f"{sub_key!r} at line {i + 1}. Valid sub-fields "
                    f"are: {valid}."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    f"Rename '{sub_key}:' to one of {valid}, or "
                    f"remove the line."
                ),
                context={"sub_field": sub_key, "valid": sorted(_PROVIDES_SUB_FIELDS)},
            )

        if sub_key in current:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'provides': duplicate "
                    f"sub-field {sub_key!r} for entry "
                    f"{current.get('name', '?')!r} at line {i + 1}."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    f"Remove the duplicate '{sub_key}:' line under "
                    f"'{current.get('name', '?')}:'."
                ),
            )

        # Parse the value — accept quoted strings (``"..."`` or ``'...'``)
        # *or* bare text. We strip a single matched pair of outer quotes
        # so callers get the human-readable contract string. Bare text
        # passes through unchanged.
        sub_value_stripped = sub_value.strip()
        if (
            len(sub_value_stripped) >= 2
            and sub_value_stripped[0] == sub_value_stripped[-1]
            and sub_value_stripped[0] in ('"', "'")
        ):
            sub_value_stripped = sub_value_stripped[1:-1]

        current[sub_key] = sub_value_stripped
        i += 1
        continue

    _flush()

    if not entries:
        raise S0maParseError(
            code="EMPTY_BLOCK_LIST",
            message=(
                "Block-list field 'provides' has no items. Either "
                f"provide at least one '- name:' entry indented more "
                f"than {field_indent} spaces, or use the inline form: "
                "provides: []."
            ),
            file=filename,
            line=field_line,
            column=1,
            severity="error",
            remediation=(
                "Add at least one '- name:' line under 'provides:' "
                f"(indented more than {field_indent} spaces) or use "
                "the inline / flat form."
            ),
        )

    encoded = _STRUCTURED_PROVIDES_SENTINEL + json.dumps(entries)
    return encoded, i


def _consume_internal_block(
    lines: list[str],
    start_index: int,
    field_indent: int,
    field_line: int,
    filename: str,
) -> tuple[str, int]:
    """Consume an ``internal:`` block list on a nerve (POST-3d, 0.15.0).

    Reads block-list items of either of these shapes::

        internal:
          - _foo
          - _bar: "Optional intent string"

    Every item names an inner helper function defined inside the nerve
    body. The intent string is *optional* per entry — bare ``- _foo``
    parses to :class:`InternalHelperEntry` with ``intent=None``;
    ``- _foo: "..."`` populates ``intent``. Both forms can be mixed
    freely in the same block.

    Returns ``(encoded, next_index)`` where ``encoded`` is the JSON-
    serialised list of dicts prefixed with
    :data:`_STRUCTURED_INTERNAL_SENTINEL`. ``_build_nerve`` recognises
    the sentinel and reconstitutes the :class:`InternalHelperEntry`
    tuple.

    Raises :class:`S0maParseError` on:
    - empty block (``EMPTY_BLOCK_LIST``),
    - duplicate names (``PARSE_ERROR``),
    - invalid Python-identifier names (``PARSE_ERROR``),
    - inconsistent indentation (``INCONSISTENT_BLOCK_LIST_INDENT``).
    """
    entries: list[dict[str, str | None]] = []
    seen_names: set[str] = set()
    i = start_index
    n = len(lines)
    list_indent: int | None = None

    while i < n:
        line = lines[i]
        stripped = line.rstrip()

        if not stripped:
            break

        if _SEPARATOR_RE.match(stripped):
            break

        if not line.startswith(" "):
            break

        indent = _leading_spaces(line)
        if indent <= field_indent:
            break

        if _COMMENT_RE.match(stripped):
            i += 1
            continue

        list_match = _BLOCK_LIST_ITEM_RE.match(line)
        if list_match is None:
            # Indented content without a leading ``-`` is not legal here.
            break

        if list_indent is None:
            list_indent = indent
        elif indent != list_indent:
            raise S0maParseError(
                code="INCONSISTENT_BLOCK_LIST_INDENT",
                message=(
                    f"Block-list field 'internal': item at line "
                    f"{i + 1} has indentation {indent} but earlier "
                    f"items use indentation {list_indent}. All items "
                    f"in a block list must share the same indent "
                    f"column."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Align every '- item' line under 'internal:' to "
                    "the same column."
                ),
            )

        item_text = list_match.group(2).strip()
        # Strip trailing inline comment.
        if "#" in item_text:
            in_quote = False
            cut = -1
            for idx, ch in enumerate(item_text):
                if ch == '"':
                    in_quote = not in_quote
                elif ch == "#" and not in_quote:
                    cut = idx
                    break
            if cut >= 0:
                item_text = item_text[:cut].strip()

        if not item_text:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'internal': item at line "
                    f"{i + 1} is empty. Each entry must name an inner "
                    f"helper function."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Write either '- _name' or '- _name: \"intent\"' "
                    "on each block-list line under 'internal:'."
                ),
            )

        # Parse ``- name`` (bare) or ``- name: "intent"`` (with intent).
        key_match = _INTERNAL_ITEM_KEY_RE.match(item_text)
        if key_match is not None and key_match.group(2).strip():
            # ``- name: <value>`` form. The value is parsed as the
            # intent string. Strip a single matched pair of outer
            # quotes for human-readable output; bare text passes
            # through unchanged.
            name = key_match.group(1)
            intent_text = key_match.group(2).rstrip().strip()
            if (
                len(intent_text) >= 2
                and intent_text[0] == intent_text[-1]
                and intent_text[0] in ('"', "'")
            ):
                intent_text = intent_text[1:-1]
            intent: str | None = intent_text
        elif key_match is not None and not key_match.group(2).strip():
            # ``- name:`` (trailing colon, no value). Treat as a bare
            # entry with no intent.
            name = key_match.group(1)
            intent = None
        else:
            # ``- name`` (no colon at all) — bare entry.
            name = item_text
            intent = None

        if not _INTERNAL_NAME_RE.match(name):
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'internal': entry name "
                    f"{name!r} at line {i + 1} is not a valid Python "
                    f"identifier."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Each 'internal:' entry must name an inner helper "
                    "function — a Python identifier (letters, digits, "
                    "and underscores; must not start with a digit)."
                ),
                context={"name": name},
            )

        if name in seen_names:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'internal': duplicate entry "
                    f"name {name!r} at line {i + 1}. Each 'internal:' "
                    f"name must be unique within the nerve."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    f"Remove the duplicate '{name}' entry, or rename "
                    f"one of the entries so the helper names are "
                    f"unique."
                ),
                context={"name": name},
            )
        seen_names.add(name)
        entries.append({"name": name, "intent": intent})
        i += 1
        continue

    if not entries:
        raise S0maParseError(
            code="EMPTY_BLOCK_LIST",
            message=(
                "Block-list field 'internal' has no items. Either "
                f"provide at least one '- name' entry indented more "
                f"than {field_indent} spaces, or use the inline form: "
                "internal: []."
            ),
            file=filename,
            line=field_line,
            column=1,
            severity="error",
            remediation=(
                "Add at least one '- name' line under 'internal:' "
                f"(indented more than {field_indent} spaces) or use "
                "the inline form."
            ),
        )

    encoded = _STRUCTURED_INTERNAL_SENTINEL + json.dumps(entries)
    return encoded, i


def _consume_inline_helpers_block(
    lines: list[str],
    start_index: int,
    field_indent: int,
    field_line: int,
    filename: str,
) -> tuple[str, int]:
    """Consume a module-level ``helpers:`` block list (POST-4b, 0.15.0).

    Reads block-list items of the inline shorthand shape::

        helpers:
          - helper _add @inline: "Quick addition" :: def _add(a, b): return a + b
          - helper _mul @inline: "Quick multiplication" :: def _mul(a, b): return a * b

    Each item carries the keyword ``helper``, the helper name, the
    ``@inline`` marker, the intent string (single- or double-quoted),
    ``::``, and a single-line Python ``def`` body. Returns
    ``(encoded, next_index)`` where ``encoded`` is the JSON-serialised
    list of dicts prefixed with :data:`_INLINE_HELPERS_SENTINEL`;
    :func:`parse_s0ma` recognises the sentinel and materialises the
    :class:`HelperDecl` list.

    Raises :class:`S0maParseError` on:
    - empty block (``EMPTY_BLOCK_LIST``),
    - duplicate helper names within the block (``PARSE_ERROR``),
    - malformed entries that don't match the canonical shape
      (``PARSE_ERROR``),
    - inconsistent item indentation (``INCONSISTENT_BLOCK_LIST_INDENT``).
    """
    entries: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    i = start_index
    n = len(lines)
    list_indent: int | None = None

    while i < n:
        line = lines[i]
        stripped = line.rstrip()

        if not stripped:
            break

        if _SEPARATOR_RE.match(stripped):
            break

        if not line.startswith(" "):
            break

        indent = _leading_spaces(line)
        if indent <= field_indent:
            break

        if _COMMENT_RE.match(stripped):
            i += 1
            continue

        list_match = _BLOCK_LIST_ITEM_RE.match(line)
        if list_match is None:
            break

        if list_indent is None:
            list_indent = indent
        elif indent != list_indent:
            raise S0maParseError(
                code="INCONSISTENT_BLOCK_LIST_INDENT",
                message=(
                    f"Block-list field 'helpers': item at line "
                    f"{i + 1} has indentation {indent} but earlier "
                    f"items use indentation {list_indent}. All items "
                    f"in a block list must share the same indent "
                    f"column."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Align every '- helper <name> @inline: ...' line "
                    "under 'helpers:' to the same column."
                ),
            )

        item_text = list_match.group(2).strip()
        if not item_text:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'helpers': item at line "
                    f"{i + 1} is empty. Each entry must declare an "
                    f"inline helper: '- helper _name @inline: \"intent\" "
                    f":: def _name(...): <body>'."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Use the canonical shape: "
                    "'- helper _name @inline: \"intent\" :: def "
                    "_name(...): <body>'."
                ),
            )

        match = _INLINE_HELPER_ITEM_RE.match(item_text)
        if match is None:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'helpers': item at line "
                    f"{i + 1} does not match the canonical inline-"
                    f"helper shape."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Use the canonical shape: "
                    "'- helper _name @inline: \"intent\" :: def "
                    "_name(...): <body>'. The intent is a quoted "
                    "string; the body is a single-line def statement "
                    "after '::'."
                ),
                context={"item_text": item_text[:120]},
            )

        helper_name = match.group(1)
        quoted_intent = match.group(2)
        body_text = match.group(3).rstrip()

        # Strip surrounding quotes from intent. ``_INLINE_HELPER_ITEM_RE``
        # guarantees a matched pair of either ``"..."`` or ``'...'``.
        intent_text = quoted_intent[1:-1]

        if helper_name in seen_names:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'helpers': duplicate inline "
                    f"helper name {helper_name!r} at line {i + 1}."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    f"Remove the duplicate '{helper_name}' entry, or "
                    f"rename one of the entries so the helper names "
                    f"are unique within the module."
                ),
                context={"name": helper_name},
            )
        seen_names.add(helper_name)

        entries.append({
            "name": helper_name,
            "intent": intent_text,
            "body": body_text,
            "line": i + 1,
        })
        i += 1
        continue

    if not entries:
        raise S0maParseError(
            code="EMPTY_BLOCK_LIST",
            message=(
                "Block-list field 'helpers' has no items. Either "
                f"provide at least one '- helper <name> @inline: ...' "
                f"entry indented more than {field_indent} spaces, or "
                f"use the inline form: helpers: []."
            ),
            file=filename,
            line=field_line,
            column=1,
            severity="error",
            remediation=(
                "Add at least one '- helper <name> @inline: ...' line "
                f"under 'helpers:' (indented more than {field_indent} "
                "spaces) or use the inline form."
            ),
        )

    encoded = _INLINE_HELPERS_SENTINEL + json.dumps(entries)
    return encoded, i


def _parse_manifest_scalar(raw: str) -> Any:
    """Best-effort scalar parsing for a manifest sub-field value (POST-5).

    Order of attempts:
    - ``true`` / ``false`` (lower-case) → Python bool
    - ``True`` / ``False`` → Python bool (lenient — surfaces the YAML
      authors' usual capitalisation)
    - All-digits (optionally signed) → ``int``
    - Quoted string (``"..."`` or ``'...'``) → str without quotes
    - Bracketed list (``[a, b]``) → list of trimmed string items
    - Anything else → trimmed string verbatim
    """
    val = raw.strip()
    if val == "":
        return ""
    if val in ("true", "True"):
        return True
    if val in ("false", "False"):
        return False
    if val.startswith("-") and val[1:].isdigit():
        return int(val)
    if val.isdigit():
        return int(val)
    if (
        len(val) >= 2
        and val[0] == val[-1]
        and val[0] in ('"', "'")
    ):
        return val[1:-1]
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        # Split on top-level commas. Re-use the existing
        # ``_split_bracketed_list`` helper for paren / quote awareness.
        items = _split_bracketed_list("[" + inner + "]")
        # Each item is a trimmed string; strip surrounding quotes
        # where present for human-friendly storage.
        cleaned: list[Any] = []
        for it in items:
            cleaned.append(_parse_manifest_scalar(it))
        return cleaned
    return val


def _consume_manifest_block(
    lines: list[str],
    start_index: int,
    field_indent: int,
    field_line: int,
    filename: str,
) -> tuple[str, int]:
    """Consume a structured ``manifest:`` block on an integration (POST-5).

    The manifest is a nested YAML-style map indented past the field
    column. Each sub-line is ``key: value`` where the value is parsed
    via :func:`_parse_manifest_scalar`. The whole map is JSON-encoded
    behind :data:`_STRUCTURED_MANIFEST_SENTINEL` so it round-trips
    through the field-value table unchanged.

    Example accepted shape::

        manifest:
          provides: [list_events, get_event]
          required_env: [GOOGLE_CALENDAR_CREDENTIALS]
          requires_oauth: true

    Returns ``(encoded, next_index)``. Empty maps (no sub-fields) are
    permitted and round-trip as ``{}`` — the validator decides whether
    an empty manifest is acceptable.
    """
    entries: dict[str, Any] = {}
    i = start_index
    n = len(lines)
    sub_indent: int | None = None

    while i < n:
        line = lines[i]
        stripped = line.rstrip()

        if not stripped:
            i += 1
            continue

        if _SEPARATOR_RE.match(stripped):
            break

        if not line.startswith(" "):
            break

        indent = _leading_spaces(line)
        if indent <= field_indent:
            break

        if _COMMENT_RE.match(stripped):
            i += 1
            continue

        if sub_indent is None:
            sub_indent = indent
        elif indent < sub_indent:
            # Same-or-shallower content ends the block.
            break

        # We accept ``key: value`` at the sub-indent column. Strip the
        # leading whitespace before matching.
        body_text = line[indent:]
        match = _MANIFEST_ITEM_KEY_RE.match(body_text)
        if match is None:
            # Indented content without ``key: value`` shape — block ends.
            break

        key = match.group(1)
        raw_val = match.group(2).strip()
        # Strip trailing inline comments (outside quoted strings).
        if raw_val and "#" in raw_val:
            in_quote: str | None = None
            cut = -1
            for idx, ch in enumerate(raw_val):
                if in_quote is None:
                    if ch in ('"', "'"):
                        in_quote = ch
                    elif ch == "#":
                        cut = idx
                        break
                elif ch == in_quote:
                    in_quote = None
            if cut >= 0:
                raw_val = raw_val[:cut].strip()

        if key in entries:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Manifest block: duplicate key {key!r} at line "
                    f"{i + 1}. Each key under 'manifest:' must be unique."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    f"Remove the duplicate '{key}:' line, or rename it."
                ),
                context={"key": key},
            )

        entries[key] = _parse_manifest_scalar(raw_val)
        i += 1
        continue

    encoded = _STRUCTURED_MANIFEST_SENTINEL + json.dumps(entries)
    return encoded, i


def _parse_metadata_scalar(raw: str) -> Any:
    """Parse one authored ``metadata:`` entry value (DSL-M1, ADR-011 §(a)).

    The L-1 shape set is deliberately narrower than the integration
    manifest's (:func:`_parse_manifest_scalar`): a value is exactly one
    of

    - ``true`` / ``false`` (lower-case) → Python bool
    - an optionally-signed integer → ``int``
    - an optionally-signed float (``3.5``, ``.5``, ``1e-3``) → ``float``
    - a quoted string (``"..."`` or ``'...'``) → str without quotes
    - a bracketed list whose entries are quoted strings or bare
      identifiers → list of strings

    Anything else — an UNQUOTED bare token (typo'd booleans included),
    an empty value (null), a malformed list entry — returns a
    :data:`~s0ma_dsl.ast_nodes.nodes.METADATA_INVALID_VALUE_MARKER`
    string instead of raising, so the semantic validator can emit a
    structured ``METADATA_INVALID_VALUE`` diagnostic (the language
    validates shape only, and validation diagnostics beat parse aborts
    for authoring UX). The marker format is
    ``<marker><reason>\\x00<raw-display>``.
    """
    val = raw.strip()
    if val == "":
        return _metadata_invalid("null", val)
    if val in _METADATA_BOOL_TOKENS:
        return val == "true"
    if _METADATA_INT_RE.match(val):
        return int(val)
    if _METADATA_FLOAT_RE.match(val):
        return float(val)
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        return val[1:-1]
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        entries: list[str] = []
        for item in _split_bracketed_list(val):
            item = item.strip()
            if (
                len(item) >= 2
                and item[0] == item[-1]
                and item[0] in ('"', "'")
            ):
                entries.append(item[1:-1])
            elif _METADATA_BARE_LIST_ENTRY_RE.match(item):
                entries.append(item)
            else:
                return _metadata_invalid("list-entry", item)
        return entries
    return _metadata_invalid("bare-token", val)


def _metadata_invalid(reason: str, raw_display: str) -> str:
    """Encode an out-of-shape ``metadata:`` value for the validator."""
    return f"{METADATA_INVALID_VALUE_MARKER}{reason}\x00{raw_display}"


def _consume_metadata_block(
    lines: list[str],
    start_index: int,
    field_indent: int,
    field_line: int,
    filename: str,
) -> tuple[str, int]:
    """Consume an authored ``metadata:`` block map (DSL-M1, ADR-011 §(a)).

    Structurally a sibling of :func:`_consume_manifest_block` (the
    block-map house pattern), with three deliberate differences that
    serve the semantic validator's ``METADATA_*`` diagnostics:

    - entries are collected as an ORDERED LIST of ``[key, value, line]``
      triples, never a dict — duplicate keys must survive to the
      validator (``METADATA_INVALID_KEY``), and authored order is
      contractual (it is preserved into the IR object, the emitted dict
      literal, and runtime ``ComponentSpec.metadata``);
    - values parse through the narrowed :func:`_parse_metadata_scalar`
      (L-1 shape set; out-of-shape values ride as marker strings);
    - nothing raises: a nested sub-map under an entry (deeper-indented
      ``key: value`` lines) is consumed, discarded, and recorded as a
      ``nested-map`` invalid value for the validator to reject.

    Returns ``(encoded, next_index)`` where ``encoded`` is the JSON
    entry list behind :data:`_STRUCTURED_METADATA_SENTINEL`.
    """
    entries: list[list[Any]] = []
    i = start_index
    n = len(lines)
    sub_indent: int | None = None

    while i < n:
        line = lines[i]
        stripped = line.rstrip()

        if not stripped:
            i += 1
            continue

        if _SEPARATOR_RE.match(stripped):
            break

        if not line.startswith(" "):
            break

        indent = _leading_spaces(line)
        if indent <= field_indent:
            break

        if _COMMENT_RE.match(stripped):
            i += 1
            continue

        if sub_indent is None:
            sub_indent = indent
        elif indent < sub_indent:
            # Same-or-shallower content ends the block.
            break
        elif indent > sub_indent:
            # Deeper-indented content — a nested map (or stray
            # continuation) under the previous entry. The L-1 shape set
            # excludes nested maps; consume the whole deeper run and
            # mark the owning entry invalid for the validator.
            while i < n:
                deeper = lines[i]
                if not deeper.strip():
                    i += 1
                    continue
                if (
                    not deeper.startswith(" ")
                    or _leading_spaces(deeper) <= sub_indent
                ):
                    break
                i += 1
            if entries:
                key, _value, line_no = entries[-1]
                entries[-1] = [
                    key,
                    _metadata_invalid("nested-map", str(key)),
                    line_no,
                ]
            continue

        body_text = line[indent:]
        match = _MANIFEST_ITEM_KEY_RE.match(body_text)
        if match is None:
            # Not an identifier-keyed ``key: value`` line. Try the
            # permissive arm so a malformed KEY stays inside the block
            # and reaches the validator (``METADATA_INVALID_KEY``)
            # instead of silently terminating the map.
            match = _METADATA_ANY_KEY_RE.match(body_text)
            if match is None:
                # No ``key: value`` shape at all — block ends.
                break

        key = match.group(1)
        raw_val = match.group(2).strip()
        # Strip trailing inline comments (outside quoted strings) —
        # same rule as the manifest consumer.
        if raw_val and "#" in raw_val:
            in_quote: str | None = None
            cut = -1
            for idx, ch in enumerate(raw_val):
                if in_quote is None:
                    if ch in ('"', "'"):
                        in_quote = ch
                    elif ch == "#":
                        cut = idx
                        break
                elif ch == in_quote:
                    in_quote = None
            if cut >= 0:
                raw_val = raw_val[:cut].strip()

        entries.append([key, _parse_metadata_scalar(raw_val), i + 1])
        i += 1
        continue

    encoded = _STRUCTURED_METADATA_SENTINEL + json.dumps(entries)
    return encoded, i


def _consume_consumes_via_dict_block(
    lines: list[str],
    start_index: int,
    field_indent: int,
    field_line: int,
    filename: str,
) -> tuple[str, int]:
    """Consume a ``consumes_via_dict:`` block on a nerve (POST-12d, 0.16.0).

    Reads block-list items of the form::

        consumes_via_dict:
          - contract: SettingsDict
            param: config
          - contract: FeatureFlags
            param: flags

    Each item is a sub-map with two MANDATORY keys: ``contract:`` and
    ``param:``. Both values are bare identifiers (the parser accepts
    arbitrary identifiers; the validator enforces that the contract
    resolves to a cell or ``uses:`` target and the param is a real
    parameter on the nerve's outer function).

    The block is JSON-encoded behind
    :data:`_STRUCTURED_CONSUMES_VIA_DICT_SENTINEL`. ``_build_nerve``
    recognises the sentinel and reconstitutes the
    :class:`ConsumesViaDictEntry` tuple.

    Raises :class:`S0maParseError` on:
    - empty block (``EMPTY_BLOCK_LIST``),
    - missing mandatory sub-field (``PARSE_ERROR``),
    - inconsistent indentation (``INCONSISTENT_BLOCK_LIST_INDENT``),
    - unknown sub-field key (``PARSE_ERROR``),
    - duplicate sub-field within an item (``PARSE_ERROR``).
    """
    entries: list[dict[str, str]] = []
    i = start_index
    n = len(lines)
    list_indent: int | None = None
    current: dict[str, str] | None = None
    sub_indent: int | None = None
    current_line: int = field_line

    def _flush() -> None:
        if current is not None:
            # Each entry MUST carry both ``contract:`` and ``param:``.
            for required in ("contract", "param"):
                if required not in current:
                    raise S0maParseError(
                        code="PARSE_ERROR",
                        message=(
                            f"Block-list field 'consumes_via_dict': "
                            f"item ending at line {current_line} is "
                            f"missing required sub-field "
                            f"{required!r}."
                        ),
                        file=filename,
                        line=current_line,
                        column=1,
                        severity="error",
                        remediation=(
                            "Each '- contract: <C>' entry must also "
                            "carry a 'param: <P>' sub-line."
                        ),
                    )
            entries.append(current)

    while i < n:
        line = lines[i]
        stripped = line.rstrip()

        if not stripped:
            i += 1
            continue

        if _SEPARATOR_RE.match(stripped):
            break

        if not line.startswith(" "):
            break

        indent = _leading_spaces(line)
        if indent <= field_indent:
            break

        if _COMMENT_RE.match(stripped):
            i += 1
            continue

        list_match = _BLOCK_LIST_ITEM_RE.match(line)
        if list_match is not None and (
            list_indent is None or indent == list_indent
        ):
            # New item — flush the previous one.
            _flush()
            current = None
            sub_indent = None

            if list_indent is None:
                list_indent = indent

            item_text = list_match.group(2).strip()
            # Strip trailing inline comment (outside quoted strings).
            if "#" in item_text:
                in_quote = False
                cut = -1
                for idx, ch in enumerate(item_text):
                    if ch == '"':
                        in_quote = not in_quote
                    elif ch == "#" and not in_quote:
                        cut = idx
                        break
                if cut >= 0:
                    item_text = item_text[:cut].strip()

            # The first sub-field can appear on the same line as the
            # dash (``- contract: X``), or the dash can stand alone
            # with each sub-field on a subsequent indented line.
            current = {}
            current_line = i + 1
            if item_text:
                sub_match = _CONSUMES_VIA_DICT_SUB_FIELD_RE.match(
                    item_text,
                )
                if sub_match is None:
                    raise S0maParseError(
                        code="PARSE_ERROR",
                        message=(
                            f"Block-list field 'consumes_via_dict': "
                            f"item at line {i + 1} is not in the "
                            f"'<key>: <value>' shape. Expected "
                            f"'- contract: <name>' (with a 'param:' "
                            f"sub-line below)."
                        ),
                        file=filename,
                        line=i + 1,
                        column=1,
                        severity="error",
                        remediation=(
                            "Each entry under 'consumes_via_dict:' "
                            "must carry both 'contract: <C>' and "
                            "'param: <P>'."
                        ),
                    )
                sub_key = sub_match.group(1)
                sub_value = sub_match.group(2).strip()
                if sub_key not in _CONSUMES_VIA_DICT_SUB_FIELDS:
                    valid = ", ".join(
                        sorted(_CONSUMES_VIA_DICT_SUB_FIELDS),
                    )
                    raise S0maParseError(
                        code="PARSE_ERROR",
                        message=(
                            f"Block-list field 'consumes_via_dict': "
                            f"unknown sub-field {sub_key!r} at line "
                            f"{i + 1}. Valid sub-fields are: {valid}."
                        ),
                        file=filename,
                        line=i + 1,
                        column=1,
                        severity="error",
                        remediation=(
                            f"Rename '{sub_key}:' to one of {valid}, "
                            f"or remove the line."
                        ),
                        context={
                            "sub_field": sub_key,
                            "valid": sorted(_CONSUMES_VIA_DICT_SUB_FIELDS),
                        },
                    )
                # Strip a single matched pair of outer quotes if
                # present (consistency with other parsers).
                if (
                    len(sub_value) >= 2
                    and sub_value[0] == sub_value[-1]
                    and sub_value[0] in ('"', "'")
                ):
                    sub_value = sub_value[1:-1]
                current[sub_key] = sub_value
            i += 1
            continue

        if (
            list_match is not None
            and list_indent is not None
            and indent != list_indent
        ):
            raise S0maParseError(
                code="INCONSISTENT_BLOCK_LIST_INDENT",
                message=(
                    f"Block-list field 'consumes_via_dict': item at "
                    f"line {i + 1} has indentation {indent} but earlier "
                    f"items use indentation {list_indent}. All items "
                    f"in a block list must share the same indent column."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Align every '- contract:' line under "
                    "'consumes_via_dict:' to the same column."
                ),
            )

        # Indented past the dash column — a sub-field line.
        if current is None:
            break

        if list_indent is not None and indent <= list_indent:
            # Same indent as the list itself but not a ``- item`` —
            # block ends.
            break

        if sub_indent is None:
            sub_indent = indent
        elif indent != sub_indent:
            raise S0maParseError(
                code="INCONSISTENT_BLOCK_LIST_INDENT",
                message=(
                    f"Block-list field 'consumes_via_dict': sub-field "
                    f"at line {i + 1} has indentation {indent} but "
                    f"earlier sub-fields use indentation {sub_indent}. "
                    f"All sub-fields under a single "
                    f"'- contract:' entry must share the same indent "
                    f"column."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Align every 'contract:' / 'param:' line under "
                    "each entry to the same column."
                ),
            )

        sub_text = line[indent:].rstrip()
        sub_match = _CONSUMES_VIA_DICT_SUB_FIELD_RE.match(sub_text)
        if sub_match is None:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'consumes_via_dict': "
                    f"unrecognised content {sub_text!r} at line "
                    f"{i + 1} under a structured item. Expected "
                    f"'contract:' or 'param:'."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Each sub-line under a '- contract:' entry must "
                    "be one of: contract: <name>, param: <name>."
                ),
            )

        sub_key = sub_match.group(1)
        sub_value = sub_match.group(2).strip()
        current_line = i + 1

        if sub_key not in _CONSUMES_VIA_DICT_SUB_FIELDS:
            valid = ", ".join(sorted(_CONSUMES_VIA_DICT_SUB_FIELDS))
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'consumes_via_dict': unknown "
                    f"sub-field {sub_key!r} at line {i + 1}. Valid "
                    f"sub-fields are: {valid}."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    f"Rename '{sub_key}:' to one of {valid}, or "
                    f"remove the line."
                ),
                context={
                    "sub_field": sub_key,
                    "valid": sorted(_CONSUMES_VIA_DICT_SUB_FIELDS),
                },
            )

        if sub_key in current:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Block-list field 'consumes_via_dict': duplicate "
                    f"sub-field {sub_key!r} at line {i + 1}."
                ),
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    f"Remove the duplicate '{sub_key}:' line under "
                    f"the entry."
                ),
            )

        # Strip a single matched pair of outer quotes if present.
        if (
            len(sub_value) >= 2
            and sub_value[0] == sub_value[-1]
            and sub_value[0] in ('"', "'")
        ):
            sub_value = sub_value[1:-1]

        current[sub_key] = sub_value
        i += 1
        continue

    _flush()

    if not entries:
        raise S0maParseError(
            code="EMPTY_BLOCK_LIST",
            message=(
                "Block-list field 'consumes_via_dict' has no items. "
                "Either provide at least one '- contract: <name>' "
                "entry with a 'param: <name>' sub-line, or omit the "
                "field entirely."
            ),
            file=filename,
            line=field_line,
            column=1,
            severity="error",
            remediation=(
                "Add at least one entry under 'consumes_via_dict:', "
                "or remove the field."
            ),
        )

    encoded = (
        _STRUCTURED_CONSUMES_VIA_DICT_SENTINEL + json.dumps(entries)
    )
    return encoded, i


def _split_declarations(source: str, filename: str = "<string>") -> list[_RawDeclaration]:
    """Split .s0ma source into raw declaration blocks."""
    lines = source.split("\n")
    declarations: list[_RawDeclaration] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()

        # Skip blank lines and comments at top level
        if not stripped or _COMMENT_RE.match(stripped):
            i += 1
            continue

        # Try to match a declaration header
        decl = _try_match_header(stripped, i + 1)
        if decl is None:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=f"Unexpected content at top level: {stripped!r}",
                file=filename,
                line=i + 1,
                column=1,
                severity="error",
                remediation=(
                    "Every top-level block must be a module, nerve, cell, ganglion, "
                    "test, axon, or helper declaration. Remove or wrap this content "
                    "in a declaration."
                ),
                context={"content": stripped[:120]},
            )

        i += 1  # move past header

        # Collect fields (indented lines with key: value)
        fields: dict[str, str] = {}
        field_lines: dict[str, int] = {}
        stray_lines: list[tuple[int, str]] = []
        depends_on_lines: list[str] = []
        current_field: str | None = None
        current_value: str | None = None
        in_depends_on = False

        while i < len(lines):
            line = lines[i]
            stripped = line.rstrip()

            # Check for separator
            if _SEPARATOR_RE.match(stripped):
                break

            # Check if this is a new top-level declaration (end of fields)
            if stripped and not stripped.startswith(" ") and not _COMMENT_RE.match(stripped):
                break

            # Skip blank lines within field block
            if not stripped:
                i += 1
                continue

            # Skip comment lines
            if _COMMENT_RE.match(stripped):
                i += 1
                continue

            # Check for depends_on entries (double-indented, must match pattern)
            if in_depends_on and _CONTINUATION_RE.match(line):
                dep_line = line.strip()
                if dep_line and _DEPENDS_ON_ENTRY_RE.match(line):
                    depends_on_lines.append(dep_line)
                    i += 1
                    continue
                # Not a valid depends_on entry — end depends_on mode
                # (could be a field with different indentation)
                in_depends_on = False

            # Check for field line
            field_match = _FIELD_RE.match(line)
            if field_match:
                # Save previous field if we were accumulating
                if current_field is not None:
                    fields[current_field] = current_value or ""

                field_name = field_match.group(1)
                field_value = field_match.group(2).rstrip()
                field_lines.setdefault(field_name, i + 1)

                if field_name == "depends_on" and not field_value:
                    in_depends_on = True
                    current_field = None
                    current_value = None
                    i += 1
                    continue

                in_depends_on = False

                # M14 (feedback 5–6): YAML literal-block-scalar form. When
                # the field value is exactly ``|``, consume the indented
                # block as a single multi-line string. The result is stored
                # with a sentinel prefix so ``_parse_string_field`` knows
                # to return it verbatim (skipping the inline-quoted-string
                # normalisation path which would otherwise mangle interior
                # indentation and quote characters).
                if _BLOCK_SCALAR_RE.match(field_value):
                    block_content, new_i = _consume_block_scalar(
                        lines,
                        start_index=i + 1,
                        field_name=field_name,
                        field_indent=_FIELD_INDENT,
                        field_line=i + 1,
                        filename=filename,
                    )
                    fields[field_name] = _BLOCK_SCALAR_SENTINEL + block_content
                    current_field = None
                    current_value = None
                    i = new_i
                    continue

                # POST-5 (0.16.0): structured ``manifest:`` block on
                # integration declarations. The map is *not* a block
                # list — sub-fields are ``key: value`` pairs indented
                # past the field column. Route to the dedicated consumer
                # before the block-list dispatcher (which only
                # recognises ``- item`` lines).
                if (
                    field_name == "manifest"
                    and decl.decl_type == "integration"
                    and not field_value
                    and _next_line_is_indented_map(lines, i + 1, _FIELD_INDENT)
                ):
                    encoded, new_i = _consume_manifest_block(
                        lines,
                        start_index=i + 1,
                        field_indent=_FIELD_INDENT,
                        field_line=i + 1,
                        filename=filename,
                    )
                    fields[field_name] = encoded
                    current_field = None
                    current_value = None
                    i = new_i
                    continue

                # DSL-M1 (0.8.0): authored ``metadata:`` block map on
                # nerve / cell / ganglion declarations (ADR-011 §(a),
                # rule L-1). Same routing shape as the integration
                # ``manifest:`` above — a flat ``key: value`` map
                # indented past the field column — but consumed by the
                # dedicated metadata consumer, which preserves
                # duplicate keys / authored order and narrows values to
                # the L-1 shape set for the semantic validator's
                # ``METADATA_*`` checks. Other declaration kinds keep
                # today's generic unknown-field behaviour (the
                # applicability matrix in ADR-011 says no).
                if (
                    field_name == "metadata"
                    and decl.decl_type in ("nerve", "cell", "ganglion")
                    and not field_value
                    and _next_line_is_metadata_map(lines, i + 1, _FIELD_INDENT)
                ):
                    encoded, new_i = _consume_metadata_block(
                        lines,
                        start_index=i + 1,
                        field_indent=_FIELD_INDENT,
                        field_line=i + 1,
                        filename=filename,
                    )
                    fields[field_name] = encoded
                    current_field = None
                    current_value = None
                    i = new_i
                    continue

                # PRE-7 (0.14.0): YAML block-list form. When the field
                # value is empty *and* the next non-blank line is
                # indented past the field column and starts with a
                # ``-`` list marker, consume the block and re-assemble
                # it into the canonical inline ``[a, b, c]`` shape so
                # downstream field parsers (``_parse_name_list``,
                # ``_parse_import_list``) need no awareness of the
                # block form. Mixed inline+block (a non-empty
                # ``field_value`` followed by ``- item`` lines)
                # always takes the inline path: the user must pick
                # one form per field.
                #
                # POST-3a (0.15.0): for the ``provides:`` field
                # specifically, the block-list form has a second flavour
                # — the structured form, where each ``- name:`` item
                # carries an indented per-method
                # ``returns:`` / ``expects:`` / ``guarantees:`` triple.
                # We disambiguate by peeking: if the first list item is
                # ``- name:`` (trailing colon, no inline value) we
                # delegate to :func:`_consume_structured_provides_block`
                # and encode the result with the dedicated sentinel so
                # ``_build_nerve`` can reconstitute the
                # :class:`ProvidesEntry` list. Every other field — and
                # the flat ``- name`` form on ``provides:`` itself —
                # continues to flow through ``_consume_block_list``.
                if not field_value and _next_line_is_block_list(
                    lines, i + 1, _FIELD_INDENT,
                ):
                    if field_name == "provides" and _peek_structured_provides(
                        lines, i + 1, _FIELD_INDENT,
                    ):
                        encoded, new_i = _consume_structured_provides_block(
                            lines,
                            start_index=i + 1,
                            field_indent=_FIELD_INDENT,
                            field_line=i + 1,
                            filename=filename,
                        )
                        fields[field_name] = encoded
                        current_field = None
                        current_value = None
                        i = new_i
                        continue

                    # POST-3d (0.15.0): ``internal:`` on nerves accepts
                    # bare-name or ``name: "intent"`` entries in a block
                    # list. We always route through the dedicated
                    # consumer (not the generic ``_consume_block_list``)
                    # because intent strings may contain a colon, which
                    # would confuse the flat-form consumer's
                    # name-only assumption.
                    if field_name == "internal":
                        encoded, new_i = _consume_internal_block(
                            lines,
                            start_index=i + 1,
                            field_indent=_FIELD_INDENT,
                            field_line=i + 1,
                            filename=filename,
                        )
                        fields[field_name] = encoded
                        current_field = None
                        current_value = None
                        i = new_i
                        continue

                    # POST-4b (0.15.0): module-level ``helpers:`` accepts
                    # inline-helper shorthand entries (``- helper _name
                    # @inline: "intent" :: def _name(...): ...``).
                    # Route through the dedicated consumer because the
                    # canonical item shape contains both colons and
                    # quoted strings — the generic block-list consumer
                    # would mis-parse them.
                    if (
                        field_name == "helpers"
                        and decl.decl_type == "module"
                    ):
                        encoded, new_i = _consume_inline_helpers_block(
                            lines,
                            start_index=i + 1,
                            field_indent=_FIELD_INDENT,
                            field_line=i + 1,
                            filename=filename,
                        )
                        fields[field_name] = encoded
                        current_field = None
                        current_value = None
                        i = new_i
                        continue

                    # POST-12d (0.16.0): ``consumes_via_dict:`` on
                    # nerves is a structured block list of
                    # ``- contract: <C>\n    param: <P>`` items.
                    # Each entry has two mandatory sub-fields so the
                    # generic flat block-list consumer would mis-parse
                    # the colon-bearing item shape. Route through the
                    # dedicated consumer.
                    if (
                        field_name == "consumes_via_dict"
                        and decl.decl_type == "nerve"
                    ):
                        encoded, new_i = _consume_consumes_via_dict_block(
                            lines,
                            start_index=i + 1,
                            field_indent=_FIELD_INDENT,
                            field_line=i + 1,
                            filename=filename,
                        )
                        fields[field_name] = encoded
                        current_field = None
                        current_value = None
                        i = new_i
                        continue

                    list_inline, new_i = _consume_block_list(
                        lines,
                        start_index=i + 1,
                        field_name=field_name,
                        field_indent=_FIELD_INDENT,
                        field_line=i + 1,
                        filename=filename,
                    )
                    fields[field_name] = list_inline
                    current_field = None
                    current_value = None
                    i = new_i
                    continue

                current_field = field_name
                current_value = field_value
                i += 1
                continue

            # Check for continuation line (8-space or more indent for multi-line strings)
            if _CONTINUATION_RE.match(line) and current_field is not None:
                cont_text = line.strip()
                if current_value is not None:
                    current_value += "\n        " + cont_text
                i += 1
                continue

            # Unknown indented content. Nothing above could place this
            # line, so it is not read — and it is remembered, because a
            # line a person wrote and s0ma skipped has to be reported
            # (``_check_declaration_lines``).
            stray_lines.append((i + 1, line.rstrip()))
            i += 1
            continue

        # Save last field
        if current_field is not None:
            fields[current_field] = current_value or ""

        # Capture body if separator found
        body: str | None = None
        saw_separator = False
        body_first_line: int | None = None
        if i < len(lines) and _SEPARATOR_RE.match(lines[i].rstrip()):
            saw_separator = True
            i += 1  # skip separator
            body_first_line = i + 1  # 1-indexed line of first body line
            body_lines: list[str] = []
            while i < len(lines):
                line = lines[i]
                stripped = line.rstrip()

                # Check if next declaration starts (non-indented, non-blank, non-comment)
                if (  # noqa: SIM102 — comment on outer branch describes the gate condition
                    stripped
                    and not stripped.startswith(" ")
                    and not _COMMENT_RE.match(stripped)
                ):
                    # Check if it's a declaration header
                    if _try_match_header(stripped, i + 1) is not None:
                        break

                body_lines.append(lines[i])
                i += 1

            # Strip trailing blank lines from body
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()

            if body_lines:
                body = "\n".join(body_lines)

        # The declaration ends on its last non-blank line. ``i`` is where
        # the next header (or the end of the file) begins, so line ``i``
        # (1-indexed) is the one before it — but that is usually the blank
        # line separating two declarations, and at the end of a file with a
        # final newline it is the empty string ``split`` yields, one line
        # past the end. Walk back over those so ``end_line`` is the last
        # body line when there is a body (the body keeps no trailing blank
        # lines either), which the source map's ``body_source`` arithmetic
        # and the ``# s0ma:`` pointers depend on (ADR-003).
        end_line = i
        while end_line > decl.start_line and not lines[end_line - 1].strip():
            end_line -= 1

        decl.fields = fields
        decl.field_lines = field_lines
        decl.stray_lines = stray_lines
        decl.depends_on_lines = depends_on_lines
        decl.body = body
        decl.end_line = end_line
        decl.saw_separator = saw_separator
        decl.body_start_line = body_first_line

        declarations.append(decl)

    return declarations


def _try_match_header(line: str, line_num: int) -> _RawDeclaration | None:
    """Try to match a declaration header line. Returns a partial _RawDeclaration or None."""
    m = _MODULE_RE.match(line)
    if m:
        return _RawDeclaration(
            decl_type="module",
            header_names=(m.group(1),),
            fields={},
            depends_on_lines=[],
            body=None,
            start_line=line_num,
            end_line=line_num,
        )

    m = _NERVE_RE.match(line)
    if m:
        return _RawDeclaration(
            decl_type="nerve",
            header_names=(m.group(1), m.group(2)),
            fields={},
            depends_on_lines=[],
            body=None,
            start_line=line_num,
            end_line=line_num,
        )

    m = _CELL_RE.match(line)
    if m:
        return _RawDeclaration(
            decl_type="cell",
            header_names=(m.group(1), m.group(2)),
            fields={},
            depends_on_lines=[],
            body=None,
            start_line=line_num,
            end_line=line_num,
        )

    m = _GANGLION_RE.match(line)
    if m:
        return _RawDeclaration(
            decl_type="ganglion",
            header_names=(m.group(1), m.group(2)),
            fields={},
            depends_on_lines=[],
            body=None,
            start_line=line_num,
            end_line=line_num,
        )

    m = _TEST_RE.match(line)
    if m:
        return _RawDeclaration(
            decl_type="test",
            header_names=(m.group(1), m.group(2)),
            fields={},
            depends_on_lines=[],
            body=None,
            start_line=line_num,
            end_line=line_num,
        )

    m = _AXON_RE.match(line)
    if m:
        return _RawDeclaration(
            decl_type="axon",
            header_names=(m.group(1), m.group(2)),
            fields={},
            depends_on_lines=[],
            body=None,
            start_line=line_num,
            end_line=line_num,
        )

    m = _HELPER_RE.match(line)
    if m:
        return _RawDeclaration(
            decl_type="helper",
            header_names=(m.group(1), m.group(2)),
            fields={},
            depends_on_lines=[],
            body=None,
            start_line=line_num,
            end_line=line_num,
        )

    # POST-5 (0.16.0): first-class integration declaration.
    m = _INTEGRATION_RE.match(line)
    if m:
        return _RawDeclaration(
            decl_type="integration",
            header_names=(m.group(1), m.group(2)),
            fields={},
            depends_on_lines=[],
            body=None,
            start_line=line_num,
            end_line=line_num,
        )

    m = _DOC_REF_RE.match(line)
    if m:
        return _RawDeclaration(
            decl_type="doc_ref",
            header_names=(m.group(1),),
            fields={},
            depends_on_lines=[],
            body=None,
            start_line=line_num,
            end_line=line_num,
        )

    m = _DOC_GUIDE_RE.match(line)
    if m:
        return _RawDeclaration(
            decl_type="doc_guide",
            header_names=(m.group(1),),
            fields={},
            depends_on_lines=[],
            body=None,
            start_line=line_num,
            end_line=line_num,
        )

    m = _EXAMPLE_RE.match(line)
    if m:
        return _RawDeclaration(
            decl_type="example",
            header_names=(m.group(1),),
            fields={},
            depends_on_lines=[],
            body=None,
            start_line=line_num,
            end_line=line_num,
        )

    return None


# ---------------------------------------------------------------------------
# Phase 2: Lark-based field value parsing
# ---------------------------------------------------------------------------


class _FieldValueTransformer(Transformer[Token, Any]):
    """Transforms Lark parse trees for field values into Python objects."""

    # --- name_list ---
    def empty_list(self, _items: list[Any]) -> list[str]:
        return []

    def populated_list(self, items: list[Any]) -> list[str]:
        return list(items)

    def qualified_item(self, items: list[Any]) -> str:
        return str(items[0])

    def simple_item(self, items: list[Any]) -> str:
        return str(items[0])

    # --- import_list ---
    def empty_import_list(self, _items: list[Any]) -> list[dict[str, Any]]:
        return []

    def populated_import_list(self, items: list[Any]) -> list[dict[str, Any]]:
        return list(items)

    def aliased_colon_import(self, items: list[Any]) -> dict[str, Any]:
        raw = str(items[0])  # e.g. "unittest.mock:patch"
        pkg, name = raw.rsplit(":", 1)
        return {"path": f"{pkg}.{name}", "alias": str(items[1]), "colon_form": True}

    def colon_import(self, items: list[Any]) -> dict[str, Any]:
        raw = str(items[0])  # e.g. "unittest.mock:patch"
        pkg, name = raw.rsplit(":", 1)
        return {"path": f"{pkg}.{name}", "alias": None, "colon_form": True}

    def aliased_import(self, items: list[Any]) -> dict[str, Any]:
        return {"path": str(items[0]), "alias": str(items[1])}

    def qualified_import(self, items: list[Any]) -> dict[str, Any]:
        return {"path": str(items[0]), "alias": None}

    def simple_import(self, items: list[Any]) -> dict[str, Any]:
        return {"path": str(items[0]), "alias": None}

    # --- depends_on_entry ---
    def dep_target(self, items: list[Any]) -> str:
        # DSL-M2 (0.8.0, ADR-011 §(d)): join the one-or-two NAME
        # segments back into the authored target string — bare
        # ``decl`` or qualified ``module.decl``. InlineAxon.target
        # stays a plain string carrying either form.
        return ".".join(str(item) for item in items)

    def depends_on_entry(self, items: list[Any]) -> dict[str, Any]:
        target = str(items[0])
        fields_dict = items[1]
        return {"target": target, **fields_dict}

    def depends_on_fields(self, items: list[Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in items:
            result.update(item)
        return result

    def dep_relation(self, items: list[Any]) -> dict[str, str]:
        return {"relation": str(items[0])}

    def dep_carries(self, items: list[Any]) -> dict[str, str]:
        raw = str(items[0])
        return {"carries": _strip_quotes(raw)}

    def dep_coupling(self, items: list[Any]) -> dict[str, str]:
        return {"coupling": str(items[0])}

    # --- entity_ref ---
    def entity_ref(self, items: list[Any]) -> EntityRefAst:
        kind_tok = items[0]
        kind = _ENTITY_KIND_NORMALISED[str(kind_tok)]
        name = str(items[1])
        field_path = tuple(str(t) for t in items[2:])
        raw = f"{kind}::{name}"
        if field_path:
            raw = raw + "." + ".".join(field_path)
        return EntityRefAst(kind=kind, name=name, field_path=field_path, raw=raw)

    # --- filter_expr ---
    def filter_expr(self, items: list[Any]) -> FilterExprAst:
        kind = _ENTITY_KIND_NORMALISED[str(items[0])]
        predicate: ComparisonPredicate | BooleanPredicate | None = None
        ordered_by: tuple[str, ...] = ()
        group_by: str | None = None
        for item in items[1:]:
            if isinstance(item, _WhereClause):
                predicate = item.predicate
            elif isinstance(item, _OrderedByClause):
                ordered_by = item.fields
            elif isinstance(item, _GroupByClause):
                group_by = item.field
        return FilterExprAst(
            kind=kind,
            predicate=predicate,
            ordered_by=ordered_by,
            group_by=group_by,
            raw="",  # filled in by the parse helper (so we can carry the caller's raw string)
        )

    def filter_where(self, items: list[Any]) -> _WhereClause:
        return _WhereClause(predicate=items[0])

    def filter_ordered_by(self, items: list[Any]) -> _OrderedByClause:
        return _OrderedByClause(fields=tuple(str(t) for t in items))

    def filter_group_by(self, items: list[Any]) -> _GroupByClause:
        return _GroupByClause(field=str(items[0]))

    # --- predicate composition ---
    def or_pred(self, items: list[Any]) -> ComparisonPredicate | BooleanPredicate:
        if len(items) == 1:
            return cast("ComparisonPredicate | BooleanPredicate", items[0])
        return BooleanPredicate(operator="or", operands=tuple(items))

    def and_pred(self, items: list[Any]) -> ComparisonPredicate | BooleanPredicate:
        if len(items) == 1:
            return cast("ComparisonPredicate | BooleanPredicate", items[0])
        return BooleanPredicate(operator="and", operands=tuple(items))

    def not_pred(self, items: list[Any]) -> BooleanPredicate:
        return BooleanPredicate(operator="not", operands=(items[0],))

    # --- comparison (filter-level) ---
    def binary_comparison(self, items: list[Any]) -> ComparisonPredicate:
        lhs = items[0]  # field_path → tuple[str, ...]
        op = str(items[1])
        rhs = items[2]
        return ComparisonPredicate(lhs=lhs, operator=op, rhs=rhs)

    def in_comparison(self, items: list[Any]) -> ComparisonPredicate:
        lhs = items[0]
        rhs = items[1]  # value_list → tuple[str, ...]
        return ComparisonPredicate(lhs=lhs, operator="in", rhs=rhs)

    # --- field_path ---
    def field_path(self, items: list[Any]) -> tuple[str, ...]:
        return tuple(str(t) for t in items)

    # --- value ---
    def value_name(self, items: list[Any]) -> str:
        return str(items[0])

    def value_quoted(self, items: list[Any]) -> str:
        return _strip_quotes(str(items[0]))

    def empty_value_list(self, _items: list[Any]) -> tuple[str, ...]:
        return ()

    def populated_value_list(self, items: list[Any]) -> tuple[str, ...]:
        return tuple(items)

    # --- section_entry ---
    def section_field(self, items: list[Any]) -> SectionAst:
        return SectionAst(field_name=str(items[0]), raw=str(items[0]))

    def section_iteration(self, items: list[Any]) -> SectionAst:
        var = str(items[0])
        collection = items[1]  # FilterExprAst
        iteration = IterationAst(
            var=var,
            collection=collection,
            ordered_by=collection.ordered_by,
            group_by=collection.group_by,
        )
        return SectionAst(iteration=iteration, raw="")

    # --- assert_* ---
    def assert_or(self, items: list[Any]) -> AssertComparison | AssertBoolean:
        if len(items) == 1:
            return cast("AssertComparison | AssertBoolean", items[0])
        return AssertBoolean(operator="or", operands=tuple(items))

    def assert_and(self, items: list[Any]) -> AssertComparison | AssertBoolean:
        if len(items) == 1:
            return cast("AssertComparison | AssertBoolean", items[0])
        return AssertBoolean(operator="and", operands=tuple(items))

    def assert_not(self, items: list[Any]) -> AssertBoolean:
        return AssertBoolean(operator="not", operands=(items[0],))

    def assert_binary_comparison(self, items: list[Any]) -> AssertComparison:
        lhs = items[0]  # EntityRefAst
        op = str(items[1])
        rhs = items[2]
        return AssertComparison(lhs=lhs, operator=op, rhs=rhs)

    def assert_in_comparison(self, items: list[Any]) -> AssertComparison:
        lhs = items[0]
        rhs = items[1]  # tuple[str, ...]
        return AssertComparison(lhs=lhs, operator="in", rhs=rhs)


# Transformer-internal carrier types for filter_expr sub-clauses. Using
# dataclasses instead of raw tuples keeps filter_expr's items list disambiguable.
@dataclass(frozen=True)
class _WhereClause:
    predicate: ComparisonPredicate | BooleanPredicate


@dataclass(frozen=True)
class _OrderedByClause:
    fields: tuple[str, ...]


@dataclass(frozen=True)
class _GroupByClause:
    field: str


_field_transformer = _FieldValueTransformer()


def _parse_name_list(raw: str, filename: str, line: int) -> list[str]:
    """Parse a name list field value like [name1, name2]."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        tree = _get_name_list_parser().parse(raw)
        return cast("list[str]", _field_transformer.transform(tree))
    except LarkError as e:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"Invalid name list: {raw!r}",
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation="Name lists must use the format: [name1, name2, qualified.name]",
            context={"raw_value": raw, "parse_error": str(e)},
        ) from e


def _parse_import_list(raw: str, filename: str, line: int) -> list[dict[str, Any]]:
    """Parse an import list field value like [mod.Name, other as alias]."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        tree = _get_import_list_parser().parse(raw)
        return cast("list[dict[str, Any]]", _field_transformer.transform(tree))
    except LarkError as e:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"Invalid import list: {raw!r}",
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation="Import lists must use the format: [mod.Name, other.thing as alias]",
            context={"raw_value": raw, "parse_error": str(e)},
        ) from e


def _parse_depends_on_entry(raw: str, filename: str, line: int) -> dict[str, Any]:
    """Parse a single depends_on entry like: target: {relation: CALLS, ...}."""
    raw = raw.strip()
    try:
        tree = _get_depends_on_parser().parse(raw)
        return cast("dict[str, Any]", _field_transformer.transform(tree))
    except LarkError as e:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"Invalid depends_on entry: {raw!r}",
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=(
                'depends_on entries must use the format: '
                'target: {relation: CALLS, carries: "data", coupling: TIGHT}. '
                'The target is a local declaration name or the qualified '
                'in-project form module.declaration (exactly one dot).'
            ),
            context={"raw_value": raw, "parse_error": str(e)},
        ) from e


# ---------------------------------------------------------------------------
# Documentation subsystem element parsers (M2)
#
# Each helper parses ONE element (already split out of a ``[a, b, c]`` list
# by :func:`_split_bracketed_list`). The list-level shape is handled in
# Python because an LALR(1) grammar cannot disambiguate list commas from
# ``ordered_by <field>, <field>`` tails inside ``filter_expr``.
# ---------------------------------------------------------------------------


def _wrap_template_syntax_error(
    raw: str, filename: str, line: int, exc: Exception, remediation: str
) -> S0maParseError:
    return S0maParseError(
        code="TEMPLATE_SYNTAX_ERROR",
        message=f"Invalid template expression: {raw!r}",
        file=filename,
        line=line,
        column=1,
        severity="error",
        remediation=remediation,
        context={"raw_value": raw, "parse_error": str(exc)},
    )


def _wrap_assert_syntax_error(
    raw: str, filename: str, line: int, exc: Exception, remediation: str
) -> S0maParseError:
    return S0maParseError(
        code="ASSERT_SYNTAX_ERROR",
        message=f"Invalid assert expression: {raw!r}",
        file=filename,
        line=line,
        column=1,
        severity="error",
        remediation=remediation,
        context={"raw_value": raw, "parse_error": str(exc)},
    )


def _parse_entity_ref(raw: str, filename: str, line: int) -> EntityRefAst:
    """Parse one entity reference: ``nerve::X`` or ``nerve::X.field``."""
    raw = raw.strip()
    try:
        tree = _get_entity_ref_parser().parse(raw)
        ref = _field_transformer.transform(tree)
    except LarkError as e:
        raise _wrap_template_syntax_error(
            raw, filename, line, e,
            remediation=(
                "Entity references must have the form <kind>::<name> (optionally "
                ".<field>.<subfield>). Valid kinds: nerve, cell, ganglion, module, "
                "example, test."
            ),
        ) from e
    # Preserve caller's raw text for downstream diagnostics.
    return EntityRefAst(
        kind=ref.kind,
        name=ref.name,
        field_path=ref.field_path,
        raw=raw,
    )


def _parse_filter_expr(raw: str, filename: str, line: int) -> FilterExprAst:
    """Parse one filter expression: ``nerves [where ...] [ordered_by ...] [group_by ...]``."""
    raw = raw.strip()
    try:
        tree = _get_filter_expr_parser().parse(raw)
        expr = _field_transformer.transform(tree)
    except LarkError as e:
        raise _wrap_template_syntax_error(
            raw, filename, line, e,
            remediation=(
                "Filter expressions must have the form: "
                "<kind> [where <predicate>] [ordered_by <fields>] [group_by <field>]. "
                "Predicates support ==, !=, in, and boolean composition with and/or/not; "
                "string concatenation, arithmetic, and arbitrary Python are not allowed."
            ),
        ) from e
    return FilterExprAst(
        kind=expr.kind,
        predicate=expr.predicate,
        ordered_by=expr.ordered_by,
        group_by=expr.group_by,
        raw=raw,
    )


def _parse_section_entry(raw: str, filename: str, line: int) -> SectionAst:
    """Parse one sections entry: a bare field NAME or a ``for ... in ...`` iteration."""
    raw = raw.strip()
    try:
        tree = _get_section_entry_parser().parse(raw)
        section = _field_transformer.transform(tree)
    except LarkError as e:
        raise _wrap_template_syntax_error(
            raw, filename, line, e,
            remediation=(
                "Each sections entry must be either a bare field name (e.g. 'intent') "
                "or an iteration of the form 'for <var> in <filter_expression>'."
            ),
        ) from e
    # Preserve caller's raw text.
    if section.field_name is not None:
        return SectionAst(field_name=section.field_name, raw=raw)
    return SectionAst(iteration=section.iteration, raw=raw)


def _parse_assert_pred(
    raw: str, filename: str, line: int
) -> AssertComparison | AssertBoolean:
    """Parse one assert expression entry."""
    raw = raw.strip()
    try:
        tree = _get_assert_pred_parser().parse(raw)
        expr = cast("AssertComparison | AssertBoolean", _field_transformer.transform(tree))
    except LarkError as e:
        raise _wrap_assert_syntax_error(
            raw, filename, line, e,
            remediation=(
                "Assert expressions must be entity-level comparisons "
                "(e.g. 'nerve::X.field == VALUE', 'nerve::X.field in [A, B]') "
                "optionally composed with and/or/not. Iteration, ordering, and "
                "grouping are not allowed inside asserts."
            ),
        ) from e
    return expr


# ---------------------------------------------------------------------------
# String helpers
# ---------------------------------------------------------------------------

def _strip_quotes(s: str) -> str:
    """Remove surrounding quotes from a string value."""
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _parse_string_field(raw: str) -> str:
    """Parse a string field value, handling multi-line quoted strings.

    M14 (feedback 5–6): block-scalar (``|``) content is pre-processed in
    :func:`_consume_block_scalar` and tagged with the
    :data:`_BLOCK_SCALAR_SENTINEL` prefix so this function can return the
    parsed text verbatim, bypassing the quote-detection / per-line
    normalization that applies to inline-quoted forms. The sentinel is a
    NUL character which cannot appear in valid .s0ma source.
    """
    if raw.startswith(_BLOCK_SCALAR_SENTINEL):
        return raw[len(_BLOCK_SCALAR_SENTINEL):]

    raw = raw.strip()
    if not raw:
        return ""

    # Handle quoted multi-line strings
    if raw.startswith('"'):
        # Collect the full quoted string (may span continuation lines)
        text = _strip_quotes(raw)
        # Normalize continuation whitespace
        lines = text.split("\n")
        normalized = []
        for line in lines:
            normalized.append(line.strip())
        return "\n".join(normalized)

    # Unquoted value — return as-is
    return raw


_ATTRIBUTE_NAMESPACE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_attribute_list(
    raw: str, filename: str, line: int
) -> list[str]:
    """Parse a ``declares_attributes:`` list value into a list of strings.

    M18 (feedback 5–6): Each entry is a ``<namespace>:<attribute>``
    tuple where ``<namespace>`` is an identifier (alphanumerics +
    underscores) and ``<attribute>`` is any non-empty string after the
    colon. Quoted entries (``"route:GET /self"``) are accepted and the
    surrounding quotes stripped so attributes that contain commas or
    spaces can be expressed cleanly.

    Examples:

        declares_attributes: [landmark:header, landmark:main]
        declares_attributes: [route:GET /self, "route:POST /self"]
        declares_attributes: [css_class:btn-primary]

    The function does not enforce the budgets — that runs at the
    project level in the resolver. It does enforce structural shape
    (``<namespace>:<attribute>``) so a typo'd entry like ``[header]``
    fails at parse time rather than silently violating budgets.
    """
    raw = raw.strip()
    if not raw:
        return []
    if not (raw.startswith("[") and raw.endswith("]")):
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"declares_attributes must be a bracketed list of "
                f"<namespace>:<attribute> entries, got: {raw!r}"
            ),
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=(
                "Enclose the entries in [] and separate with commas: "
                "declares_attributes: [landmark:header, landmark:main]"
            ),
            context={"raw_value": raw},
        )
    inner = raw[1:-1].strip()
    if not inner:
        return []

    entries: list[str] = []
    buf: list[str] = []
    in_quote = False
    for ch in inner:
        if ch == '"':
            in_quote = not in_quote
            buf.append(ch)
            continue
        if ch == "," and not in_quote:
            entries.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    last = "".join(buf).strip()
    if last:
        entries.append(last)
    elif buf:
        # trailing empty after a comma — surface a clear error
        entries.append("")

    cleaned: list[str] = []
    for entry in entries:
        token = entry.strip()
        if not token:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    "declares_attributes contains an empty entry — "
                    "remove the trailing comma or fill in the entry."
                ),
                file=filename,
                line=line,
                column=1,
                severity="error",
                remediation=(
                    "Each entry must be a <namespace>:<attribute> string."
                ),
                context={"raw_value": raw},
            )
        if token.startswith('"') and token.endswith('"') and len(token) >= 2:
            token = token[1:-1]
        if ":" not in token:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"declares_attributes entry {entry!r} is not in "
                    f"<namespace>:<attribute> form."
                ),
                file=filename,
                line=line,
                column=1,
                severity="error",
                remediation=(
                    "Each entry must be a <namespace>:<attribute> string, "
                    "e.g. 'landmark:header' or 'route:GET /self'."
                ),
                context={"raw_value": raw, "entry": entry},
            )
        namespace, _, attribute = token.partition(":")
        namespace = namespace.strip()
        attribute = attribute.strip()
        if not namespace or not _ATTRIBUTE_NAMESPACE_RE.match(namespace):
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"declares_attributes namespace {namespace!r} is "
                    f"not a valid identifier in entry {entry!r}."
                ),
                file=filename,
                line=line,
                column=1,
                severity="error",
                remediation=(
                    "Namespaces must match [A-Za-z_][A-Za-z0-9_]* — pick "
                    "a stable identifier for the attribute kind, "
                    "e.g. 'landmark', 'route', 'css_class'."
                ),
                context={"raw_value": raw, "entry": entry},
            )
        if not attribute:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"declares_attributes entry {entry!r} has an empty "
                    f"attribute — write '<namespace>:<attribute>'."
                ),
                file=filename,
                line=line,
                column=1,
                severity="error",
                remediation=(
                    "Provide a non-empty attribute after the colon, "
                    "e.g. 'landmark:header'."
                ),
                context={"raw_value": raw, "entry": entry},
            )
        cleaned.append(f"{namespace}:{attribute}")
    return cleaned


def _parse_covered_by_list(
    raw: str, filename: str, line: int
) -> tuple[str, ...]:
    """Parse a ``covered_by:`` list value into a tuple of strings.

    DSL-M2 (0.8.0, ADR-011 §(e)): entries are free-form strings — suite
    paths or rationale prose — quoted for anything beyond a bare
    identifier (same list lexing as ``declares_attributes:`` values,
    minus the namespace shape rule: the language validates SHAPE only
    and never resolves the strings; honesty is the author's burden and
    the IR makes the claim auditable).

    Empty entries (and the authored-but-empty ``covered_by: []`` form,
    encoded as one empty-string marker) ride the AST so the semantic
    validator owns the diagnostic (``COVERED_BY_EMPTY``, error in every
    mode) — the M1 marker-string pattern.
    """
    raw = raw.strip()
    if not raw:
        return ()
    if not (raw.startswith("[") and raw.endswith("]")):
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"covered_by must be a bracketed list of strings, "
                f"got: {raw!r}"
            ),
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=(
                "Enclose the entries in [] and separate with commas: "
                'covered_by: ["tests/test_tools.py — boundary suite"]'
            ),
            context={"raw_value": raw},
        )
    inner = raw[1:-1].strip()
    if not inner:
        # Authored-but-empty list — one empty-string marker so the
        # semantic validator can distinguish it from "not authored"
        # and emit COVERED_BY_EMPTY.
        return ("",)

    entries: list[str] = []
    buf: list[str] = []
    in_quote = False
    for ch in inner:
        if ch == '"':
            in_quote = not in_quote
            buf.append(ch)
            continue
        if ch == "," and not in_quote:
            entries.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    entries.append("".join(buf).strip())

    cleaned: list[str] = []
    for entry in entries:
        token = entry.strip()
        if token.startswith('"') and token.endswith('"') and len(token) >= 2:
            token = token[1:-1]
        # Empty / whitespace-only entries ride through for the
        # validator's COVERED_BY_EMPTY check.
        cleaned.append(token.strip())
    return tuple(cleaned)


def _parse_int_field(raw: str, field_name: str, filename: str, line: int) -> int:
    """Parse an integer field value."""
    raw = raw.strip()
    try:
        return int(raw)
    except ValueError as err:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"Field '{field_name}' must be an integer, got: {raw!r}",
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=f"Set '{field_name}' to a valid integer value (e.g., {field_name}: 100).",
        ) from err


def _parse_bool_field(raw: str, field_name: str, filename: str, line: int) -> bool:
    """Parse a boolean field value (true/false)."""
    raw = raw.strip().lower()
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise S0maParseError(
        code="PARSE_ERROR",
        message=f"Field '{field_name}' must be true or false, got: {raw!r}",
        file=filename,
        line=line,
        column=1,
        severity="error",
        remediation=f"Set '{field_name}' to 'true' or 'false'.",
    )


# ---------------------------------------------------------------------------
# Enum resolution helpers
# ---------------------------------------------------------------------------

_LAYER_MAP = {v.value: v for v in Layer}
_KIND_MAP = {v.value: v for v in Kind}
_VISIBILITY_MAP = {v.value: v for v in Visibility}
_RELATION_MAP = {v.value: v for v in Relation}
_COUPLING_MAP = {v.value: v for v in Coupling}
_EVALUATES_AT_MAP = {v.value: v for v in EvaluatesAt}


def _resolve_layer(raw: str, filename: str, line: int) -> Layer:
    val = raw.strip()
    if val not in _LAYER_MAP:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"Invalid layer: {val!r}",
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=f"Valid layers are: {', '.join(_LAYER_MAP.keys())}",
        )
    return _LAYER_MAP[val]


def _resolve_kind(raw: str, filename: str, line: int) -> Kind:
    val = raw.strip()
    if val not in _KIND_MAP:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"Invalid kind: {val!r}",
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=f"Valid kinds are: {', '.join(_KIND_MAP.keys())}",
        )
    return _KIND_MAP[val]


def _resolve_visibility(raw: str, filename: str, line: int) -> Visibility:
    val = raw.strip()
    if val not in _VISIBILITY_MAP:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"Invalid visibility: {val!r}",
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation="Valid visibility values are: PUBLIC, INTERNAL, TEST",
        )
    return _VISIBILITY_MAP[val]


def _resolve_evaluates_at(raw: str, filename: str, line: int) -> EvaluatesAt:
    val = raw.strip()
    if val not in _EVALUATES_AT_MAP:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"Invalid evaluates_at/scope value: {val!r}",
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=f"Valid values are: {', '.join(_EVALUATES_AT_MAP.keys())}",
        )
    return _EVALUATES_AT_MAP[val]


# POST-2 (0.15.0): the optional ``category:`` field on cell declarations
# accepts only the two values below. Anything else is a ``PARSE_ERROR``.
# The value is lower-case to mirror the surrounding "label" style fields
# (``role:`` on manifest entries, ``coupling:`` on edges) rather than the
# enum-uppercase style used by ``kind:`` / ``layer:`` / ``visibility:``.
VALID_CELL_CATEGORIES: frozenset[str] = frozenset({"capability", "behaviour"})


def _resolve_cell_category(
    raw: str, name: str, filename: str, line: int,
) -> str:
    """Validate a ``category:`` value and return it normalised.

    Returns the lower-cased / stripped value (always one of
    :data:`VALID_CELL_CATEGORIES`). Raises ``PARSE_ERROR`` on any other
    input — the caller should only invoke this helper when the field
    appears with a non-empty value.
    """
    val = raw.strip()
    if val not in VALID_CELL_CATEGORIES:
        valid = ", ".join(sorted(VALID_CELL_CATEGORIES))
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"Cell '{name}' has invalid category {val!r}. "
                f"Valid values are: {valid}."
            ),
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=(
                f"Set 'category:' on cell '{name}' to one of: {valid}, "
                f"or omit the field entirely."
            ),
            context={"declaration": name, "category": val},
        )
    return val


# ---------------------------------------------------------------------------
# AST node builders
# ---------------------------------------------------------------------------


def _build_module(decl: _RawDeclaration, filename: str) -> ModuleDecl:
    """Build a ModuleDecl from a raw declaration."""
    name = decl.header_names[0]
    fields = decl.fields

    # Mandatory fields
    _require_field("layer", fields, "module", name, filename, decl.start_line)
    _require_field("version", fields, "module", name, filename, decl.start_line)
    _require_field("intent", fields, "module", name, filename, decl.start_line)
    _require_field("exports", fields, "module", name, filename, decl.start_line)

    layer = _resolve_layer(fields["layer"], filename, decl.start_line)
    version = fields["version"].strip()
    intent = _parse_string_field(fields["intent"])
    exports = tuple(_parse_name_list(fields["exports"], filename, decl.start_line))

    # Optional / conditional fields
    requires_raw = fields.get("requires", "")
    soft_requires_raw = fields.get("soft_requires", "")
    # POST-10b (0.16.0): ``runtime_only_requires:`` — imports emitted on
    # the generated module but exempted from the Phase 4 vestigial
    # check. Same grammar as ``requires:`` / ``soft_requires:``.
    runtime_only_requires_raw = fields.get("runtime_only_requires", "")
    # DSL-M2 (0.8.0, ADR-011 §(c)): ``deferred_requires:`` — imports
    # the emitter injects into each consuming def body instead of the
    # module top (per-call failure semantics). Same grammar as
    # ``requires:`` / ``soft_requires:`` / ``runtime_only_requires:``
    # — entries ride the same ``_build_requires`` machinery, colon
    # overrides and ``as`` aliases included.
    deferred_requires_raw = fields.get("deferred_requires", "")
    uses_raw = fields.get("uses", "")
    tags_raw = fields.get("tags", "")

    requires_entries = _build_requires(requires_raw, filename, decl.start_line)
    soft_requires_entries = _build_requires(soft_requires_raw, filename, decl.start_line)
    runtime_only_requires_entries = _build_requires(
        runtime_only_requires_raw, filename, decl.start_line
    )
    deferred_requires_entries = _build_requires(
        deferred_requires_raw, filename, decl.start_line
    )
    uses_entries = _build_uses(uses_raw, filename, decl.start_line)
    tags = tuple(_parse_name_list(tags_raw, filename, decl.start_line)) if tags_raw.strip() else ()

    # POST-4c (0.15.0): ``exports_helpers:`` — names of helpers that
    # may be reached cross-module via ``uses:`` (still gated by the M13
    # test-context rule on the consumer side). The field is optional;
    # absent or empty parses to ``()``. Accepts inline (``[a, b]``) and
    # block-list (``- a`` / ``- b``) forms exactly like ``exports:``.
    exports_helpers_raw = fields.get("exports_helpers", "")
    exports_helpers = (
        tuple(_parse_name_list(exports_helpers_raw, filename, decl.start_line))
        if exports_helpers_raw.strip()
        else ()
    )

    return ModuleDecl(
        name=name,
        layer=layer,
        version=version,
        intent=intent,
        exports=exports,
        requires=requires_entries,
        uses=uses_entries,
        soft_requires=soft_requires_entries,
        tags=tags,
        exports_helpers=exports_helpers,
        runtime_only_requires=runtime_only_requires_entries,
        deferred_requires=deferred_requires_entries,
        location=SourceLocation(
            start_line=decl.start_line,
            start_column=1,
            end_line=decl.end_line,
            end_column=1,
            file=filename,
        ),
    )


def _build_inline_helpers(
    module_decl_raw: _RawDeclaration,
    module_layer: Layer,
    filename: str,
) -> list[HelperDecl]:
    """Materialise inline-helper entries from a module decl's ``helpers:`` field.

    POST-4b (0.15.0): the module header may declare a list of helpers
    inline via the ``helpers:`` field. Each entry already lived through
    :func:`_consume_inline_helpers_block` as a sentinel-encoded JSON
    blob; this function decodes that blob and builds :class:`HelperDecl`
    instances. Inline helpers always carry ``body_kind == "function"``
    and ``inline == True``.

    Returns an empty list when ``helpers:`` is absent or empty.
    """
    raw = module_decl_raw.fields.get("helpers", "")
    if not raw.startswith(_INLINE_HELPERS_SENTINEL):
        # Field is absent OR was supplied as an inline ``[]`` (empty
        # list) — in either case there are no inline helpers to build.
        return []

    payload = raw[len(_INLINE_HELPERS_SENTINEL):]
    entries = json.loads(payload)

    result: list[HelperDecl] = []
    for entry in entries:
        name = entry["name"]
        intent = entry["intent"]
        body = entry["body"]
        line = int(entry["line"])

        result.append(HelperDecl(
            name=name,
            layer=module_layer,
            intent=intent,
            tags=(),
            body=body,
            raw_body=body,
            body_kind="function",
            inline=True,
            location=SourceLocation(
                start_line=line,
                start_column=1,
                end_line=line,
                end_column=1,
                file=filename,
            ),
        ))
    return result


_KNOWN_FROM_IMPORTS = frozenset({
    "datetime.datetime", "datetime.timezone", "datetime.timedelta",
    "collections.defaultdict", "collections.Counter", "collections.OrderedDict",
    "dataclasses.dataclass", "dataclasses.field",
    "functools.wraps", "functools.lru_cache", "functools.partial",
    "contextlib.contextmanager", "contextlib.asynccontextmanager",
    "typing.Any", "typing.Optional", "typing.Union",
})


def _build_requires(raw: str, filename: str, line: int) -> tuple[RequiresEntry, ...]:
    """Build RequiresEntry tuple from raw requires field value."""
    if not raw.strip():
        return ()
    entries = _parse_import_list(raw, filename, line)
    result = []
    for entry in entries:
        path = entry["path"]
        alias = entry["alias"]

        if entry.get("colon_form"):
            # Explicit colon syntax: package:name → always a from-import
            result.append(RequiresEntry(
                module_path=path,
                alias=alias,
                is_from_import=True,
            ))
        else:
            # Heuristic: check known-exceptions, then capitalization
            parts = path.split(".")
            is_from = (
                path in _KNOWN_FROM_IMPORTS
                or (len(parts) > 1 and parts[-1][0:1].isupper())
            )
            result.append(RequiresEntry(
                module_path=path,
                alias=alias,
                is_from_import=is_from,
            ))
    return tuple(result)


def _build_uses(raw: str, filename: str, line: int) -> tuple[UsesEntry, ...]:
    """Build UsesEntry tuple from raw uses field value."""
    if not raw.strip():
        return ()
    entries = _parse_import_list(raw, filename, line)
    result = []
    for entry in entries:
        result.append(UsesEntry(
            qualified_name=entry["path"],
            alias=entry["alias"],
        ))
    return tuple(result)


def _build_metadata_field(
    fields: dict[str, str],
) -> tuple[tuple[str, MetadataValue], ...]:
    """Decode the authored ``metadata:`` field for a declaration builder.

    DSL-M1 (0.8.0, ADR-011 §(a)): shared by ``_build_nerve`` /
    ``_build_cell`` / ``_build_ganglion``. Three arms:

    - field absent or empty → ``()`` (an empty block map is permitted
      and indistinguishable from "not authored" — the IR omits the key);
    - the splitter's sentinel payload → ordered ``(key, value)`` pairs
      (JSON lists come back as ``tuple[str, ...]``; marker strings for
      out-of-shape values ride through untouched);
    - anything else (the unsupported inline ``metadata: {...}`` form, a
      block-scalar, a block list, ...) → one empty-key entry carrying an
      ``inline-form`` invalid marker. The empty key cannot collide with
      a real entry (keys are identifiers), and the semantic validator
      turns it into ``METADATA_INVALID_VALUE`` with the block-map
      remediation.
    """
    raw = fields.get("metadata", "")
    if not raw.strip():
        return ()
    if raw.startswith(_STRUCTURED_METADATA_SENTINEL):
        encoded = raw[len(_STRUCTURED_METADATA_SENTINEL):]
        raw_entries = json.loads(encoded)
        result: list[tuple[str, MetadataValue]] = []
        for key, value, _line in raw_entries:
            if isinstance(value, list):
                result.append((key, tuple(str(item) for item in value)))
            else:
                result.append((key, value))
        return tuple(result)
    display = raw.replace("\x00", "").strip()
    if len(display) > 60:
        display = display[:57] + "..."
    return (("", _metadata_invalid("inline-form", display)),)


def _build_nerve(decl: _RawDeclaration, filename: str) -> NerveDecl:
    """Build a NerveDecl from a raw declaration."""
    name = decl.header_names[0]
    layer_str = decl.header_names[1]
    fields = decl.fields

    # Mandatory fields
    _require_field("kind", fields, "nerve", name, filename, decl.start_line)
    _require_field("visibility", fields, "nerve", name, filename, decl.start_line)
    _require_field("intent", fields, "nerve", name, filename, decl.start_line)
    _require_field("expects", fields, "nerve", name, filename, decl.start_line)
    _require_field("guarantees", fields, "nerve", name, filename, decl.start_line)
    _require_field("evaluates_at", fields, "nerve", name, filename, decl.start_line)

    layer = _resolve_layer(layer_str, filename, decl.start_line)
    kind = _resolve_kind(fields["kind"], filename, decl.start_line)
    visibility = _resolve_visibility(fields["visibility"], filename, decl.start_line)
    intent = _parse_string_field(fields["intent"])
    expects = _parse_string_field(fields["expects"])
    guarantees = _parse_string_field(fields["guarantees"])
    # ``forbids:`` is read like an optional line. Whether it may be left
    # out, and its ``none`` and ``pending`` states, are settled in
    # ``_prepare_semantic_markers``, which leaves a state here as an empty
    # quoted string.
    forbids = (
        _parse_string_field(fields["forbids"])
        if fields.get("forbids", "").strip()
        else ""
    )
    evaluates_at = _resolve_evaluates_at(fields["evaluates_at"], filename, decl.start_line)

    # Optional fields
    # POST-3a (0.15.0): ``provides:`` accepts two forms:
    #   * flat — ``provides: [foo, bar]`` or block ``- foo\n  - bar``.
    #     Each entry is a bare operation name. ``provides_entries`` mirrors
    #     ``provides`` with every triple slot ``None``.
    #   * structured — ``provides:\n  - foo:\n      returns: "..."``.
    #     The splitter encoded the structured payload with
    #     :data:`_STRUCTURED_PROVIDES_SENTINEL`; we decode it here so the
    #     ``ProvidesEntry`` tuple carries the per-method triple, and the
    #     flat ``provides`` tuple stays the canonical ordered name list.
    provides_raw = fields.get("provides", "")
    provides: tuple[str, ...]
    provides_entries: tuple[ProvidesEntry, ...]
    if provides_raw.startswith(_STRUCTURED_PROVIDES_SENTINEL):
        encoded = provides_raw[len(_STRUCTURED_PROVIDES_SENTINEL):]
        try:
            raw_entries = json.loads(encoded)
        except json.JSONDecodeError as exc:  # pragma: no cover — defensive
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Nerve '{name}' has a corrupted structured "
                    f"'provides:' payload (internal sentinel decode "
                    f"failed: {exc})."
                ),
                file=filename,
                line=decl.start_line,
                column=1,
                severity="error",
                remediation=(
                    "Re-emit the 'provides:' block — this is an "
                    "internal parser invariant violation."
                ),
            ) from exc
        provides_entries = tuple(
            ProvidesEntry(
                name=entry["name"],
                returns=entry.get("returns"),
                expects=entry.get("expects"),
                guarantees=entry.get("guarantees"),
            )
            for entry in raw_entries
        )
        provides = tuple(entry.name for entry in provides_entries)
    elif provides_raw.strip():
        provides = tuple(_parse_name_list(
            provides_raw, filename, decl.start_line,
        ))
        provides_entries = tuple(
            ProvidesEntry(name=n) for n in provides
        )
    else:
        provides = ()
        provides_entries = ()

    returns_field = tuple(_parse_name_list(
        fields.get("returns", ""), filename, decl.start_line
    )) if fields.get("returns", "").strip() else ()

    raises = tuple(_parse_name_list(
        fields.get("raises", ""), filename, decl.start_line
    )) if fields.get("raises", "").strip() else ()

    abstract = False
    if "abstract" in fields:
        abstract = _parse_bool_field(fields["abstract"], "abstract", filename, decl.start_line)

    interface = tuple(_parse_name_list(
        fields.get("interface", ""), filename, decl.start_line
    )) if fields.get("interface", "").strip() else ()

    latency_ms = None
    if "latency_ms" in fields:
        latency_ms = _parse_int_field(fields["latency_ms"], "latency_ms", filename, decl.start_line)

    depends_on = _build_depends_on(decl.depends_on_lines, filename, decl.start_line)

    version = fields.get("version", "").strip() or None
    tags = tuple(_parse_name_list(
        fields.get("tags", ""), filename, decl.start_line
    )) if fields.get("tags", "").strip() else ()

    # M18 (feedback 5–6): structural attribute claims
    # (``landmark:header``, ``route:GET /self``, …). Optional; descriptive
    # without an ``[tool.s0ma.attribute_budgets]`` table.
    declares_attributes = tuple(_parse_attribute_list(
        fields.get("declares_attributes", ""),
        filename,
        decl.start_line,
    )) if fields.get("declares_attributes", "").strip() else ()

    # DSL-M2 (0.8.0, ADR-011 §(e)): external test-evidence credit —
    # a list of strings naming the out-of-DSL suites (or rationale)
    # that cover this declaration. The release-mode
    # MISSING_TEST_COVERAGE gate credits it; empty entries become
    # COVERED_BY_EMPTY at validation.
    covered_by = _parse_covered_by_list(
        fields.get("covered_by", ""), filename, decl.start_line,
    )

    # F3 (feedback 5–6 follow-up): explicit page-composer marker. Replaces
    # M18's "top-level module in the uses: graph" heuristic. Default
    # ``False`` keeps every existing nerve unchanged.
    is_page_composer = False
    if "is_page_composer" in fields:
        is_page_composer = _parse_bool_field(
            fields["is_page_composer"],
            "is_page_composer",
            filename,
            decl.start_line,
        )

    # POST-3d (0.15.0): ``internal:`` accepts two forms:
    #   * inline — ``internal: [_foo, _bar]`` (no intent strings).
    #   * block — ``internal:\n      - _foo\n      - _bar: "intent"``
    #     (intent optional per entry; mixed bare / intent items
    #     allowed).
    # The block form is consumed by ``_consume_internal_block`` and
    # encoded under :data:`_STRUCTURED_INTERNAL_SENTINEL`; the inline
    # form arrives as a literal ``[a, b]`` string and parses through
    # ``_parse_name_list`` for the bare-name list, with every entry's
    # intent set to ``None``.
    internal_raw = fields.get("internal", "")
    internal_helpers: tuple[InternalHelperEntry, ...]
    if internal_raw.startswith(_STRUCTURED_INTERNAL_SENTINEL):
        encoded = internal_raw[len(_STRUCTURED_INTERNAL_SENTINEL):]
        try:
            raw_entries = json.loads(encoded)
        except json.JSONDecodeError as exc:  # pragma: no cover — defensive
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Nerve {name!r} has a corrupted structured "
                    f"'internal:' payload (internal sentinel decode "
                    f"failed: {exc})."
                ),
                file=filename,
                line=decl.start_line,
                column=1,
                severity="error",
                remediation=(
                    "Re-emit the 'internal:' block — this is an "
                    "internal parser invariant violation."
                ),
            ) from exc
        internal_helpers = tuple(
            InternalHelperEntry(
                name=entry["name"],
                intent=entry.get("intent"),
            )
            for entry in raw_entries
        )
    elif internal_raw.strip():
        # Inline / flat form — bare names only, no intent strings.
        # Validate each entry as a Python identifier; the inline
        # parser would otherwise accept any token.
        bare_names = _parse_name_list(
            internal_raw, filename, decl.start_line,
        )
        seen: set[str] = set()
        helpers_list: list[InternalHelperEntry] = []
        for n in bare_names:
            if not _INTERNAL_NAME_RE.match(n):
                raise S0maParseError(
                    code="PARSE_ERROR",
                    message=(
                        f"Nerve {name!r}: 'internal:' entry {n!r} is "
                        f"not a valid Python identifier."
                    ),
                    file=filename,
                    line=decl.start_line,
                    column=1,
                    severity="error",
                    remediation=(
                        "Each 'internal:' entry must name an inner "
                        "helper function — a Python identifier "
                        "(letters, digits, and underscores; must not "
                        "start with a digit)."
                    ),
                    context={"name": n},
                )
            if n in seen:
                raise S0maParseError(
                    code="PARSE_ERROR",
                    message=(
                        f"Nerve {name!r}: duplicate 'internal:' "
                        f"entry {n!r}. Each name must be unique "
                        f"within the nerve."
                    ),
                    file=filename,
                    line=decl.start_line,
                    column=1,
                    severity="error",
                    remediation=(
                        f"Remove the duplicate {n!r} entry, or rename "
                        f"one of the entries so the helper names are "
                        f"unique."
                    ),
                    context={"name": n},
                )
            seen.add(n)
            helpers_list.append(InternalHelperEntry(name=n))
        internal_helpers = tuple(helpers_list)
    else:
        internal_helpers = ()

    # POST-12a (0.16.0): ``expected_exceptions:`` — Python-side
    # exception types the nerve catches by design. Distinct from
    # ``raises:`` (which is restricted to s0ma cells). Entries are
    # dotted Python paths (``json.JSONDecodeError``,
    # ``urllib.error.HTTPError``); ``_parse_name_list`` accepts the
    # dotted form natively. Inline (``expected_exceptions: [a, b]``)
    # and block-list (``expected_exceptions:\n      - a\n      - b``)
    # forms parse identically via the PRE-7 block-list re-assembler
    # upstream. The field has no validation side effect — see
    # :class:`NerveDecl.expected_exceptions`.
    expected_exceptions = tuple(_parse_name_list(
        fields.get("expected_exceptions", ""), filename, decl.start_line,
    )) if fields.get("expected_exceptions", "").strip() else ()

    # POST-12f (0.16.0): ``deferred:`` — stub-marker annotation.
    # When present and non-empty, marks the nerve body as a deferred
    # stub awaiting fill; the value is a free-form reason string.
    # ``s0ma check --report-deferred`` enumerates every deferred
    # declaration. See :class:`NerveDecl.deferred`.
    deferred: str | None = None
    if "deferred" in fields and fields["deferred"].strip():
        deferred = _parse_string_field(fields["deferred"])

    # POST-12d (0.16.0): ``consumes_via_dict:`` — duck-typed coupling
    # declarations. The block consumer encoded the payload behind
    # :data:`_STRUCTURED_CONSUMES_VIA_DICT_SENTINEL`; we decode it
    # here so the :class:`ConsumesViaDictEntry` tuple is hydrated.
    # The validator (see ``_check_consumes_via_dict``) enforces that
    # the named contract resolves to a known cell or ``uses:`` target
    # and that the named param is a real parameter on the nerve
    # body's outer function. The parser-side responsibility is
    # structural: the field arrives as either the sentinel-encoded
    # block payload or unset.
    consumes_via_dict_raw = fields.get("consumes_via_dict", "")
    consumes_via_dict: tuple[ConsumesViaDictEntry, ...]
    if consumes_via_dict_raw.startswith(
        _STRUCTURED_CONSUMES_VIA_DICT_SENTINEL,
    ):
        encoded = consumes_via_dict_raw[
            len(_STRUCTURED_CONSUMES_VIA_DICT_SENTINEL):
        ]
        try:
            raw_entries = json.loads(encoded)
        except json.JSONDecodeError as exc:  # pragma: no cover — defensive
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Nerve '{name}' has a corrupted structured "
                    f"'consumes_via_dict:' payload (internal sentinel "
                    f"decode failed: {exc})."
                ),
                file=filename,
                line=decl.start_line,
                column=1,
                severity="error",
                remediation=(
                    "Re-emit the 'consumes_via_dict:' block — this "
                    "is an internal parser invariant violation."
                ),
            ) from exc
        consumes_via_dict = tuple(
            ConsumesViaDictEntry(
                contract=entry["contract"],
                param=entry["param"],
            )
            for entry in raw_entries
        )
    else:
        consumes_via_dict = ()

    return NerveDecl(
        name=name,
        layer=layer,
        kind=kind,
        visibility=visibility,
        intent=intent,
        expects=expects,
        guarantees=guarantees,
        forbids=forbids,
        evaluates_at=evaluates_at,
        provides=provides,
        provides_entries=provides_entries,
        returns=returns_field,
        raises=raises,
        abstract=abstract,
        interface=interface,
        latency_ms=latency_ms,
        depends_on=depends_on,
        version=version,
        tags=tags,
        declares_attributes=declares_attributes,
        covered_by=covered_by,
        metadata=_build_metadata_field(fields),
        serves_as=(
            _parse_string_field(fields["serves_as"]) or None
            if fields.get("serves_as", "").strip()
            else None
        ),
        is_page_composer=is_page_composer,
        internal_helpers=internal_helpers,
        expected_exceptions=expected_exceptions,
        deferred=deferred,
        consumes_via_dict=consumes_via_dict,
        body=decl.body,
        location=SourceLocation(
            start_line=decl.start_line,
            start_column=1,
            end_line=decl.end_line,
            end_column=1,
            file=filename,
        ),
    )


def _build_cell(decl: _RawDeclaration, filename: str) -> CellDecl:
    """Build a CellDecl from a raw declaration."""
    name = decl.header_names[0]
    layer_str = decl.header_names[1]
    fields = decl.fields

    # Mandatory fields
    _require_field("kind", fields, "cell", name, filename, decl.start_line)
    _require_field("visibility", fields, "cell", name, filename, decl.start_line)
    _require_field("intent", fields, "cell", name, filename, decl.start_line)
    _require_field("schema", fields, "cell", name, filename, decl.start_line)

    layer = _resolve_layer(layer_str, filename, decl.start_line)
    kind = _resolve_kind(fields["kind"], filename, decl.start_line)
    visibility = _resolve_visibility(fields["visibility"], filename, decl.start_line)
    intent = _parse_string_field(fields["intent"])
    schema = _parse_string_field(fields["schema"])

    # Optional fields
    invariants = None
    if "invariants" in fields and fields["invariants"].strip():
        invariants = _parse_string_field(fields["invariants"])

    version = fields.get("version", "").strip() or None
    tags = tuple(_parse_name_list(
        fields.get("tags", ""), filename, decl.start_line
    )) if fields.get("tags", "").strip() else ()

    # POST-2 (0.15.0): optional ``category: capability | behaviour``.
    # Absent → ``None``. Invalid value → ``PARSE_ERROR``. fr3d's MS 19
    # ConfigDiff classifier consumes the field to derive event
    # classification from the registry instead of a static rule table.
    category: str | None = None
    if "category" in fields and fields["category"].strip():
        category = _resolve_cell_category(
            fields["category"], name, filename, decl.start_line,
        )

    # POST-12f (0.16.0): ``deferred:`` — stub-marker annotation.
    # When present and non-empty, marks the cell body as a deferred
    # stub awaiting fill; the value is a free-form reason string.
    # See :class:`CellDecl.deferred`.
    deferred: str | None = None
    if "deferred" in fields and fields["deferred"].strip():
        deferred = _parse_string_field(fields["deferred"])

    # POST-12b (0.16.0): ``placeholders:`` — magic-string markers
    # the embedded file is asserted to contain. The field is only
    # legal on CONSTANT cells with ``content: @file(...)`` (the
    # check below enforces this after parsing the embed directive).
    # Inline (``placeholders: [a, b]``) and block-list
    # (``placeholders:\n      - a\n      - b``) forms are both
    # accepted via ``_parse_name_list``. See
    # :class:`CellDecl.placeholders`.
    placeholders = tuple(_parse_name_list(
        fields.get("placeholders", ""), filename, decl.start_line,
    )) if fields.get("placeholders", "").strip() else ()

    # POST-12c (0.16.0): ``dataclass_invariants:`` — list of Python
    # boolean expressions authored against the dataclass's fields
    # (``"len(latency_samples) <= 100"``, ``"0.0 <= ratio <= 1.0"``).
    # The field is *only* meaningful on MODEL cells — declaring it
    # on a CONSTANT / CONFIG / ENUM / EXCEPTION / TYPE cell raises
    # ``PARSE_ERROR``. Inline (``dataclass_invariants: ["x <= 10"]``)
    # and block-list (``dataclass_invariants:\n      - "x <= 10"``)
    # forms both work. Entries can contain commas (e.g.
    # ``"0 <= x <= 10"``) because the splitter is quote-aware. The
    # validator syntax-checks each entry via
    # ``ast.parse(expr, mode="eval")``; a parse failure raises
    # ``INVALID_DATACLASS_INVARIANT``. See
    # :class:`CellDecl.dataclass_invariants`.
    dataclass_invariants: tuple[str, ...] = ()
    if "dataclass_invariants" in fields and fields["dataclass_invariants"].strip():
        if kind != Kind.MODEL:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Cell '{name}' declares 'dataclass_invariants:' "
                    f"but kind is {kind.value}. The "
                    f"'dataclass_invariants:' field is only "
                    f"meaningful on MODEL cells — invariants are "
                    f"declared against the dataclass's fields."
                ),
                file=filename,
                line=decl.start_line,
                column=1,
                severity="error",
                remediation=(
                    f"Either change cell '{name}' kind to MODEL, or "
                    f"remove the 'dataclass_invariants:' field."
                ),
                context={"declaration": name, "kind": kind.value},
            )
        # Split the inline / block-form value into individual
        # entries, then strip a single matched pair of outer quotes
        # from each. Each entry is preserved verbatim as a string;
        # the validator runs the Python-expression syntax check.
        entries = _split_bracketed_list(
            fields["dataclass_invariants"].strip(),
        )
        cleaned: list[str] = []
        for entry in entries:
            entry = entry.strip()
            if (
                len(entry) >= 2
                and entry[0] == entry[-1]
                and entry[0] in ('"', "'")
            ):
                entry = entry[1:-1]
            if entry:
                cleaned.append(entry)
        dataclass_invariants = tuple(cleaned)

    # M12 (feedback 5–6): ``content: @file("path")`` embed directive.
    # The directive replaces the inline ``--- ... ---`` body block on
    # CONSTANT cells. The parser resolves the path against the .s0ma
    # file's directory, reads the file as UTF-8, and stamps the cell's
    # ``embedded_*`` fields. The codegen synthesises the assignment
    # ``<NAME> = <literal>`` from the read content; the build manifest
    # records ``embedded_file_path`` + ``embedded_file_hash`` so cache
    # invalidation tracks the external file. See plan M12 / spec §4.2.2.
    embedded_file_path: str | None = None
    embedded_file_resolved: str | None = None
    embedded_content: str | None = None
    embedded_file_hash: str | None = None
    if "content" in fields and fields["content"].strip():
        embedded_file_path = _parse_embed_directive(
            fields["content"], name, filename, decl.start_line,
        )
        # Reject combined inline body + embed directive — pick one form.
        if decl.saw_separator or decl.body is not None:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Cell '{name}' uses both 'content: @file(...)' and "
                    f"an inline '---' body. Pick one form: either embed "
                    f"the value via @file() OR write the body inline, "
                    f"not both."
                ),
                file=filename,
                line=decl.start_line,
                column=1,
                severity="error",
                remediation=(
                    f"Remove either the 'content: @file(...)' field or "
                    f"the '---' separator and inline body for cell "
                    f"'{name}'."
                ),
                context={"declaration": name},
            )
        # @file() is only valid on CONSTANT cells in M12.
        if kind != Kind.CONSTANT:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"Cell '{name}' has 'content: @file(...)' but kind is "
                    f"{kind.value}. The @file() embed directive is only "
                    f"supported on CONSTANT cells in v0.12.0."
                ),
                file=filename,
                line=decl.start_line,
                column=1,
                severity="error",
                remediation=(
                    f"Either change cell '{name}' kind to CONSTANT, or "
                    f"remove the 'content: @file(...)' field and use an "
                    f"inline '---' body."
                ),
                context={"declaration": name, "kind": kind.value},
            )
        embedded_file_resolved, embedded_content, embedded_file_hash = (
            _resolve_and_read_embed(
                embedded_file_path, name, filename, decl.start_line,
            )
        )

    # POST-12b (0.16.0): ``placeholders:`` is tied to the embed
    # directive — the field describes which magic-string markers
    # the embedded file's content is asserted to contain. Reject
    # ``placeholders:`` on any cell that does NOT use
    # ``content: @file(...)`` because there is no embedded content
    # for the validator to cross-check against. (CONSTANT cells with
    # an inline ``---`` body can interpolate values directly in the
    # body literal; placeholders are an artifact of the external-file
    # path.)
    if placeholders and embedded_file_path is None:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"Cell '{name}' declares 'placeholders:' but does "
                f"not use 'content: @file(\"...\")'. The "
                f"'placeholders:' field is only meaningful on "
                f"CONSTANT cells whose body comes from an embedded "
                f"file — there is no external content to validate "
                f"placeholders against otherwise."
            ),
            file=filename,
            line=decl.start_line,
            column=1,
            severity="error",
            remediation=(
                f"Either remove the 'placeholders:' field from cell "
                f"'{name}', or replace the inline body with "
                f"'content: @file(\"path/to/file\")' so the "
                f"placeholder validator has external content to "
                f"check against."
            ),
            context={"declaration": name},
        )

    return CellDecl(
        name=name,
        layer=layer,
        kind=kind,
        visibility=visibility,
        intent=intent,
        schema=schema,
        invariants=invariants,
        version=version,
        tags=tags,
        body=decl.body,
        embedded_file_path=embedded_file_path,
        embedded_file_resolved=embedded_file_resolved,
        embedded_content=embedded_content,
        embedded_file_hash=embedded_file_hash,
        category=category,
        deferred=deferred,
        placeholders=placeholders,
        dataclass_invariants=dataclass_invariants,
        metadata=_build_metadata_field(fields),
        covered_by=_parse_covered_by_list(
            fields.get("covered_by", ""), filename, decl.start_line,
        ),
        location=SourceLocation(
            start_line=decl.start_line,
            start_column=1,
            end_line=decl.end_line,
            end_column=1,
            file=filename,
        ),
    )


# ---------------------------------------------------------------------------
# M12 (feedback 5–6) — @file() embed directive helpers
# ---------------------------------------------------------------------------

# ``@file("path")`` — captures the path between the double quotes. We
# accept ``"`` only (matching the rest of the language's string
# convention). Whitespace around the parenthesised argument is tolerated.
_EMBED_DIRECTIVE_RE = re.compile(r'^@file\s*\(\s*"([^"]*)"\s*\)\s*$')


def _parse_embed_directive(
    raw: str, cell_name: str, filename: str, start_line: int,
) -> str:
    """Parse a ``content: @file("path")`` field value, returning the path.

    Rejects malformed forms (``@file()`` with no path, missing quotes,
    extra arguments) with a structural ``PARSE_ERROR``. The grammar is
    deliberately narrow — it is the language's first first-class
    directive surface and we will widen it (e.g., ``@file("path", encoding="utf-8")``)
    only if the consumer base demonstrably needs it.
    """
    raw = raw.strip()
    match = _EMBED_DIRECTIVE_RE.match(raw)
    if match is None:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"Cell '{cell_name}': 'content' field must be of the form "
                f'``@file("path")``, got: {raw!r}.'
            ),
            file=filename,
            line=start_line,
            column=1,
            severity="error",
            remediation=(
                f"Use the literal form 'content: @file(\"path/to/file\")' "
                f"on cell '{cell_name}'. The path is resolved relative "
                f"to the .s0ma file's directory."
            ),
            context={"declaration": cell_name, "raw": raw},
        )
    path = match.group(1)
    if not path:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"Cell '{cell_name}': '@file(\"\")' has an empty path."
            ),
            file=filename,
            line=start_line,
            column=1,
            severity="error",
            remediation=(
                f"Provide a non-empty path to '@file(...)' on cell "
                f"'{cell_name}'."
            ),
            context={"declaration": cell_name},
        )
    return path


def _resolve_and_read_embed(
    embed_path: str,
    cell_name: str,
    filename: str,
    start_line: int,
) -> tuple[str, str, str]:
    """Resolve an embed path relative to *filename* and read its contents.

    Returns ``(absolute_resolved_path, content, "sha256:<hex>")``. Raises
    ``S0maSemanticError`` with code ``EMBEDDED_FILE_NOT_FOUND`` when the
    file is missing, unreadable, or not decodable as UTF-8 text — see
    the M12 severity matrix entry.

    Path resolution policy: relative paths resolve against the .s0ma
    file's parent directory; absolute paths are used as-is. When the
    parser was invoked with the sentinel filename ``<string>`` (no
    on-disk source), relative paths cannot be resolved and the error is
    surfaced with a remediation pointing at how to invoke the parser
    with a real path.
    """
    import hashlib

    p = Path(embed_path)
    if not p.is_absolute():
        if filename in ("<string>", ""):
            raise S0maSemanticError(
                code="EMBEDDED_FILE_NOT_FOUND",
                message=(
                    f"Cell '{cell_name}': cannot resolve relative embed "
                    f"path {embed_path!r} — the parser was invoked "
                    f"without a source file path."
                ),
                file=filename,
                line=start_line,
                column=1,
                severity="error",
                remediation=(
                    "Invoke the parser with the .s0ma file's path so "
                    "@file() can resolve relative paths against it, "
                    "or write an absolute path in '@file(...)'."
                ),
                context={
                    "declaration": cell_name,
                    "embed_path": embed_path,
                },
            )
        base_dir = Path(filename).resolve().parent
        p = (base_dir / embed_path).resolve()
    else:
        p = p.resolve()

    if not p.is_file():
        raise S0maSemanticError(
            code="EMBEDDED_FILE_NOT_FOUND",
            message=(
                f"Cell '{cell_name}': @file({embed_path!r}) "
                f"references a file that does not exist at "
                f"{p}."
            ),
            file=filename,
            line=start_line,
            column=1,
            severity="error",
            remediation=(
                f"Create the file at {p}, or update the @file() path "
                f"on cell '{cell_name}' to point at an existing file. "
                f"Relative paths resolve against the .s0ma file's "
                f"directory."
            ),
            context={
                "declaration": cell_name,
                "embed_path": embed_path,
                "resolved_path": str(p),
            },
        )

    try:
        content = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise S0maSemanticError(
            code="EMBEDDED_FILE_NOT_FOUND",
            message=(
                f"Cell '{cell_name}': @file({embed_path!r}) at "
                f"{p} is not readable as UTF-8 text: {exc}."
            ),
            file=filename,
            line=start_line,
            column=1,
            severity="error",
            remediation=(
                f"Ensure the embedded file at {p} is a UTF-8-encoded "
                f"text file. Binary embed is not supported in v0.12.0; "
                f"if you need to embed binary content, file an issue."
            ),
            context={
                "declaration": cell_name,
                "embed_path": embed_path,
                "resolved_path": str(p),
            },
        ) from exc

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return str(p), content, f"sha256:{digest}"


def _build_ganglion(decl: _RawDeclaration, filename: str) -> GanglionDecl:
    """Build a GanglionDecl from a raw declaration."""
    name = decl.header_names[0]
    layer_str = decl.header_names[1]
    fields = decl.fields

    # Mandatory fields
    _require_field("visibility", fields, "ganglion", name, filename, decl.start_line)
    _require_field("intent", fields, "ganglion", name, filename, decl.start_line)
    _require_field("observes", fields, "ganglion", name, filename, decl.start_line)
    _require_field("scope", fields, "ganglion", name, filename, decl.start_line)
    _require_field("priors", fields, "ganglion", name, filename, decl.start_line)
    _require_field("on_anomaly", fields, "ganglion", name, filename, decl.start_line)

    layer = _resolve_layer(layer_str, filename, decl.start_line)
    visibility = _resolve_visibility(fields["visibility"], filename, decl.start_line)
    intent = _parse_string_field(fields["intent"])
    observes = tuple(_parse_name_list(fields["observes"], filename, decl.start_line))
    scope = _resolve_evaluates_at(fields["scope"], filename, decl.start_line)
    priors = _parse_string_field(fields["priors"])
    on_anomaly = _parse_string_field(fields["on_anomaly"])
    # ``forbids:`` is read the way ``_build_nerve`` reads it.
    forbids = (
        _parse_string_field(fields["forbids"])
        if fields.get("forbids", "").strip()
        else ""
    )

    depends_on = _build_depends_on(decl.depends_on_lines, filename, decl.start_line)
    tags = tuple(_parse_name_list(
        fields.get("tags", ""), filename, decl.start_line
    )) if fields.get("tags", "").strip() else ()

    # POST-12f (0.16.0): ``deferred:`` — stub-marker annotation.
    # When present and non-empty, marks the ganglion body as a
    # deferred stub awaiting fill; the value is a free-form reason
    # string. See :class:`GanglionDecl.deferred`.
    deferred: str | None = None
    if "deferred" in fields and fields["deferred"].strip():
        deferred = _parse_string_field(fields["deferred"])

    return GanglionDecl(
        name=name,
        layer=layer,
        visibility=visibility,
        intent=intent,
        observes=observes,
        scope=scope,
        priors=priors,
        on_anomaly=on_anomaly,
        forbids=forbids,
        depends_on=depends_on,
        tags=tags,
        body=decl.body,
        deferred=deferred,
        metadata=_build_metadata_field(fields),
        covered_by=_parse_covered_by_list(
            fields.get("covered_by", ""), filename, decl.start_line,
        ),
        location=SourceLocation(
            start_line=decl.start_line,
            start_column=1,
            end_line=decl.end_line,
            end_column=1,
            file=filename,
        ),
    )


def _build_test(decl: _RawDeclaration, filename: str) -> TestDecl:
    """Build a TestDecl from a raw declaration."""
    name = decl.header_names[0]
    layer_str = decl.header_names[1]
    fields = decl.fields

    # Mandatory fields
    _require_field("intent", fields, "test", name, filename, decl.start_line)
    _require_field("tests", fields, "test", name, filename, decl.start_line)

    layer = _resolve_layer(layer_str, filename, decl.start_line)
    intent = _parse_string_field(fields["intent"])
    tests = tuple(_parse_name_list(fields["tests"], filename, decl.start_line))

    # Optional fields
    expects = None
    if "expects" in fields and fields["expects"].strip():
        expects = _parse_string_field(fields["expects"])

    depends_on = _build_depends_on(decl.depends_on_lines, filename, decl.start_line)
    tags = tuple(_parse_name_list(
        fields.get("tags", ""), filename, decl.start_line
    )) if fields.get("tags", "").strip() else ()

    # POST-3b (0.15.0): ``mocks:`` lists nerve names whose public
    # ``provides:`` surface this test mocks. The validator cross-checks
    # any mock-shape dict literal in the body against the target's
    # ``provides:`` set. Inline (``mocks: [a, b]``) and block-list
    # (``mocks:\n      - a\n      - b``) forms parse identically via
    # the PRE-7 block-list re-assembler upstream.
    mocks = tuple(_parse_name_list(
        fields.get("mocks", ""), filename, decl.start_line
    )) if fields.get("mocks", "").strip() else ()

    return TestDecl(
        name=name,
        layer=layer,
        intent=intent,
        tests=tests,
        expects=expects,
        depends_on=depends_on,
        tags=tags,
        mocks=mocks,
        body=decl.body,
        location=SourceLocation(
            start_line=decl.start_line,
            start_column=1,
            end_line=decl.end_line,
            end_column=1,
            file=filename,
        ),
    )


def _build_axon(decl: _RawDeclaration, filename: str) -> StandaloneAxonDecl:
    """Build a StandaloneAxonDecl from a raw declaration."""
    source = decl.header_names[0]
    target = decl.header_names[1]
    fields = decl.fields

    # Mandatory fields
    _require_field("relation", fields, "axon", f"{source} -> {target}", filename, decl.start_line)
    _require_field("intent", fields, "axon", f"{source} -> {target}", filename, decl.start_line)
    _require_field("carries", fields, "axon", f"{source} -> {target}", filename, decl.start_line)
    _require_field("coupling", fields, "axon", f"{source} -> {target}", filename, decl.start_line)

    relation_str = fields["relation"].strip()
    if relation_str not in _RELATION_MAP:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"Invalid relation in axon: {relation_str!r}",
            file=filename,
            line=decl.start_line,
            column=1,
            severity="error",
            remediation=f"Valid authored relation types are: {', '.join(_RELATION_MAP.keys())}",
        )
    relation = _RELATION_MAP[relation_str]

    coupling_str = fields["coupling"].strip()
    if coupling_str not in _COUPLING_MAP:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"Invalid coupling in axon: {coupling_str!r}",
            file=filename,
            line=decl.start_line,
            column=1,
            severity="error",
            remediation="Valid coupling values are: TIGHT, LOOSE",
        )
    coupling = _COUPLING_MAP[coupling_str]

    intent = _parse_string_field(fields["intent"])
    carries = _parse_string_field(fields["carries"])

    return StandaloneAxonDecl(
        source=source,
        target=target,
        relation=relation,
        intent=intent,
        carries=carries,
        coupling=coupling,
        location=SourceLocation(
            start_line=decl.start_line,
            start_column=1,
            end_line=decl.end_line,
            end_column=1,
            file=filename,
        ),
    )


def _build_helper(decl: _RawDeclaration, filename: str) -> HelperDecl:
    """Build a HelperDecl from a raw declaration.

    M13 (feedback 5–6): helpers are a fourth top-level declaration kind
    alongside ``nerve``, ``cell``, and ``ganglion``. They live at module
    scope, are not registered as components, but are introspectable via
    ``s0ma inspect``.

    Required: ``intent:`` and a ``--- ... ---`` body. The body must be a
    function or class definition (POST-4a extended ``helper`` bodies to
    accept classes; validated downstream by ``validate_body`` with
    decl_type='helper'). Helpers do *not* have ``kind`` or
    ``visibility`` fields — both are explicitly omitted because helpers
    are not component contracts (per the M13 plan).

    POST-4a (0.15.0): body_kind is set provisionally from the body's
    first non-blank line — ``"class"`` if it begins with ``class``,
    otherwise ``"function"``. The downstream :func:`validate_body`
    pass enforces a true AST classification (``BodyType.CLASS`` vs
    ``BodyType.FUNCTION``); ``_finalize_helper_body_kind`` reconciles
    the AST-derived value back onto the decl after extraction.
    """
    name = decl.header_names[0]
    layer_str = decl.header_names[1]
    fields = decl.fields

    # Mandatory fields. ``intent`` is required (no silent helpers).
    _require_field("intent", fields, "helper", name, filename, decl.start_line)

    # Helpers must have a ``--- ... ---`` body.
    if not decl.saw_separator:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"helper '{name}' is missing the '---' separator and "
                f"function or class body."
            ),
            file=filename,
            line=decl.end_line,
            column=1,
            severity="error",
            remediation=(
                f"Add a '---' separator after the last field of helper "
                f"'{name}', followed by a 'def {name}(...)' function "
                f"body or a 'class {name}:' definition."
            ),
            context={"declaration_type": "helper", "declaration_name": name},
        )
    if decl.body is None or not decl.body.strip():
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"helper '{name}' has an empty body after the '---' "
                f"separator."
            ),
            file=filename,
            line=decl.body_start_line or decl.end_line,
            column=1,
            severity="error",
            remediation=(
                f"Add a 'def {name}(...)' function or 'class {name}:' "
                f"class body to helper '{name}', or delete the "
                f"declaration."
            ),
            context={"declaration_type": "helper", "declaration_name": name},
        )

    layer = _resolve_layer(layer_str, filename, decl.start_line)
    intent = _parse_string_field(fields["intent"])

    tags = tuple(_parse_name_list(
        fields.get("tags", ""), filename, decl.start_line
    )) if fields.get("tags", "").strip() else ()

    # Provisional body_kind from the body's first non-blank line. The
    # canonical value is reconciled from the AST in
    # ``_finalize_helper_body_kind`` after body extraction.
    body_kind = _provisional_body_kind(decl.body)

    return HelperDecl(
        name=name,
        layer=layer,
        intent=intent,
        tags=tags,
        body=decl.body,
        body_kind=body_kind,
        inline=False,
        location=SourceLocation(
            start_line=decl.start_line,
            start_column=1,
            end_line=decl.end_line,
            end_column=1,
            file=filename,
        ),
    )


def _provisional_body_kind(body: str | None) -> str:
    """Return ``"class"`` or ``"function"`` from the body's first line (POST-4a).

    Provisional only — used to seed :attr:`HelperDecl.body_kind` before
    AST extraction. ``_finalize_helper_body_kind`` updates the field
    from the AST-classified :class:`BodyType` so the canonical value
    always matches what the validator sees.
    """
    if body is None:
        return "function"
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("class "):
            return "class"
        return "function"
    return "function"


# ---------------------------------------------------------------------------
# Integration declaration (POST-5, 0.16.0)
# ---------------------------------------------------------------------------


def _build_integration(decl: _RawDeclaration, filename: str) -> IntegrationDecl:
    """Build an :class:`IntegrationDecl` from a raw declaration (POST-5, 0.16.0).

    Required fields: ``version``, ``intent``, ``factory``,
    ``smoke_test_primary``, ``manifest``. The validator (not the
    parser) enforces:
    - ``layer == INFRASTRUCTURE`` (``LAYER_MISMATCH``),
    - the ``factory:`` nerve exists in the module and has
      ``kind: SERVICE`` (``INTEGRATION_FACTORY_NOT_FOUND`` /
      ``INTEGRATION_FACTORY_NOT_SERVICE``),
    - the ``smoke_test_primary:`` nerve exists or resolves via ``uses:``
      (``INTEGRATION_SMOKE_TEST_NOT_FOUND``).

    The manifest is decoded from the sentinel-encoded JSON payload the
    block consumer leaves on the field-value table. Inline-empty
    manifests (``manifest: {}`` or ``manifest:`` with no nested map)
    parse to ``{}``.
    """
    name = decl.header_names[0]
    layer_str = decl.header_names[1]
    fields = decl.fields

    # Mandatory fields.
    _require_field("intent", fields, "integration", name, filename, decl.start_line)
    _require_field("version", fields, "integration", name, filename, decl.start_line)
    _require_field("factory", fields, "integration", name, filename, decl.start_line)
    _require_field(
        "smoke_test_primary", fields, "integration", name, filename, decl.start_line,
    )
    _require_field("manifest", fields, "integration", name, filename, decl.start_line)

    # ``_resolve_layer`` enforces the enum membership; the
    # ``LAYER_MISMATCH`` check lives in the validator so a bad layer
    # still produces the layer enum's canonical value (e.g. APPLICATION)
    # and the validator surfaces the integration-specific message.
    layer = _resolve_layer(layer_str, filename, decl.start_line)

    intent = _parse_string_field(fields["intent"])
    version = fields["version"].strip()
    factory = fields["factory"].strip()
    smoke_test_primary = fields["smoke_test_primary"].strip()

    # Decode the manifest. The consumer leaves either:
    # - the sentinel-prefixed JSON payload (when the block form was used)
    # - an inline ``{}`` or ``{ ... }`` literal string the user wrote
    # - the empty string (when ``manifest:`` had no value AND no
    #   following indented map — semantically equivalent to empty).
    manifest_raw = fields.get("manifest", "")
    manifest: dict[str, Any]
    if manifest_raw.startswith(_STRUCTURED_MANIFEST_SENTINEL):
        payload = manifest_raw[len(_STRUCTURED_MANIFEST_SENTINEL):]
        manifest = json.loads(payload)
    else:
        # Inline form: accept ``{}`` and ``{ key: value, key2: value2 }``
        # via a best-effort split. Keys are bare identifiers, values
        # use :func:`_parse_manifest_scalar`.
        stripped = manifest_raw.strip()
        if not stripped or stripped == "{}":
            manifest = {}
        elif stripped.startswith("{") and stripped.endswith("}"):
            manifest = {}
            inner = stripped[1:-1].strip()
            if inner:
                # Split on top-level commas keeping bracketed values intact.
                parts: list[str] = []
                buf: list[str] = []
                depth = 0
                in_quote: str | None = None
                for ch in inner:
                    if in_quote is not None:
                        buf.append(ch)
                        if ch == in_quote:
                            in_quote = None
                    elif ch in ('"', "'"):
                        in_quote = ch
                        buf.append(ch)
                    elif ch in "([{":
                        depth += 1
                        buf.append(ch)
                    elif ch in ")]}":
                        depth -= 1
                        buf.append(ch)
                    elif ch == "," and depth == 0:
                        parts.append("".join(buf).strip())
                        buf = []
                    else:
                        buf.append(ch)
                if buf:
                    parts.append("".join(buf).strip())
                for part in parts:
                    if not part:
                        continue
                    m = _MANIFEST_ITEM_KEY_RE.match(part)
                    if m is None:
                        raise S0maParseError(
                            code="PARSE_ERROR",
                            message=(
                                f"integration '{name}': manifest inline "
                                f"entry {part!r} is not 'key: value'."
                            ),
                            file=filename,
                            line=decl.start_line,
                            column=1,
                            severity="error",
                            remediation=(
                                "Each inline manifest entry must be "
                                "'key: value'. Prefer the block form "
                                "(indented sub-fields under manifest:) "
                                "for non-trivial manifests."
                            ),
                        )
                    manifest[m.group(1)] = _parse_manifest_scalar(
                        m.group(2),
                    )
        else:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"integration '{name}': manifest value "
                    f"{manifest_raw!r} is not a recognised shape. Use "
                    f"the block form (indented 'key: value' lines under "
                    f"'manifest:') or the inline ``{{key: value, ...}}`` "
                    f"shape."
                ),
                file=filename,
                line=decl.start_line,
                column=1,
                severity="error",
                remediation=(
                    "Switch to the block form:\n"
                    "    manifest:\n"
                    "      provides: [list_events]\n"
                    "      required_env: [GOOGLE_CALENDAR_CREDENTIALS]\n"
                    "      requires_oauth: true"
                ),
            )

    # Optional list-style fields parse with the existing helpers.
    requires_raw = fields.get("requires", "")
    uses_raw = fields.get("uses", "")
    raises_raw = fields.get("raises", "")
    tags_raw = fields.get("tags", "")

    requires_entries = _build_requires(requires_raw, filename, decl.start_line)
    uses_entries = _build_uses(uses_raw, filename, decl.start_line)
    raises = (
        tuple(_parse_name_list(raises_raw, filename, decl.start_line))
        if raises_raw.strip()
        else ()
    )
    tags = (
        tuple(_parse_name_list(tags_raw, filename, decl.start_line))
        if tags_raw.strip()
        else ()
    )

    return IntegrationDecl(
        name=name,
        layer=layer,
        version=version,
        intent=intent,
        factory=factory,
        smoke_test_primary=smoke_test_primary,
        manifest=manifest,
        requires=requires_entries,
        uses=uses_entries,
        raises=raises,
        tags=tags,
        body=decl.body,
        raw_body=decl.body,
        location=SourceLocation(
            start_line=decl.start_line,
            start_column=1,
            end_line=decl.end_line,
            end_column=1,
            file=filename,
        ),
    )


# ---------------------------------------------------------------------------
# Documentation subsystem helpers (M1)
#
# M1 intentionally does not parse the full template/assert expression grammar
# (that is M2). For fields whose v1 shape is a bracketed list — ``covers``,
# ``sections``, ``examples``, ``demonstrates``, ``asserts`` — the preprocessor
# preserves the raw text of each list element so M2 can reparse without
# information loss.
# ---------------------------------------------------------------------------


def _split_bracketed_list(raw: str) -> list[str]:
    """Split a ``[a, b, c]`` list into trimmed elements, preserving content.

    Handles top-level commas only — commas inside nested brackets, parens,
    braces, or quoted strings are preserved inside their element. Returns
    an empty list for ``[]``. If the value is not bracketed, the entire
    value is returned as a single-element list (so M2 can still recover
    it).
    """
    s = raw.strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()
        if not s:
            return []
    elements: list[str] = []
    buf: list[str] = []
    depth = 0
    in_string: str | None = None
    i = 0
    while i < len(s):
        ch = s[i]
        if in_string is not None:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(s):
                buf.append(s[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
        elif ch in ('"', "'"):
            in_string = ch
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            piece = "".join(buf).strip()
            if piece:
                elements.append(piece)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        elements.append(tail)
    return elements


def _build_doc_ref(
    decl: _RawDeclaration, filename: str, module_name: str
) -> DocRefDecl:
    """Build a DocRefDecl from a raw declaration.

    doc-ref is a field-only declaration: its output is synthesised by the
    renderer from ``covers`` + ``sections`` (M6). A ``---`` separator or
    body is a hard parse error.
    """
    name = decl.header_names[0]
    fields = decl.fields

    if decl.saw_separator or decl.body is not None:
        raise S0maParseError(
            code="PARSE_DOC_REF_BODY_PROHIBITED",
            message=(
                f"doc-ref '{name}' has a body, but doc-ref declarations are field-only — "
                "their content is synthesised by the renderer from covers + sections."
            ),
            file=filename,
            line=decl.body_start_line or decl.end_line,
            column=1,
            severity="error",
            remediation=(
                f"Remove the '---' separator and body from doc-ref '{name}'. "
                "If you want authored prose, declare a doc-guide instead."
            ),
            context={"declaration_type": "doc-ref", "declaration_name": name},
        )

    _require_field("intent", fields, "doc-ref", name, filename, decl.start_line)
    _require_field("format", fields, "doc-ref", name, filename, decl.start_line)
    _require_field("output", fields, "doc-ref", name, filename, decl.start_line)
    _require_field("covers", fields, "doc-ref", name, filename, decl.start_line)

    intent = _parse_string_field(fields["intent"])
    doc_format = _parse_string_field(fields["format"])
    output = _parse_string_field(fields["output"])

    # G7a (feedback 5–6 cleanup): ``covers:`` is a discriminated union.
    # The historic form is a bracketed list of filter expressions; G7a
    # adds a sub-key form ``{ source: <name> }`` that pulls from a
    # derived registry instead of project components. The two are
    # exclusive — one populates ``covers``, the other populates
    # ``covers_source``.
    covers_raw = fields["covers"].strip()
    covers, covers_source = _parse_doc_ref_covers(
        covers_raw, name, filename, decl.start_line,
    )

    # ADR-013 §6: ``sections:`` is required for the filter form and
    # optional for the brace form. It was required for both and dead for
    # the brace form — the one in-tree generator authored ``sections: []``
    # purely to satisfy a check whose value the renderer discarded. The
    # covers shape has to be known before this runs, which is why the
    # requirement moved below the ``covers:`` parse.
    #
    # This is the one parser-validation change the documentation
    # initiative makes, authorized at milestone D7 and only there. It is a
    # relaxation of a required-field check, not a grammar change: the
    # field, its syntax, and its meaning in the filter form are untouched.
    if covers_source is None:
        _require_field(
            "sections", fields, "doc-ref", name, filename, decl.start_line,
        )
    sections = tuple(
        _parse_section_entry(piece, filename, decl.start_line)
        for piece in _split_bracketed_list(fields.get("sections", ""))
    )
    if covers_source is not None and sections:
        # An empty ``sections: []`` keeps parsing — it is the exact shape
        # the old rule forced every brace-form author to write, including
        # any consumer project that took up ADR-010's invitation to render
        # the s0ma error catalogue in its own docs, and breaking working
        # sources to tidy a field is not a trade this initiative is
        # entitled to make. A NON-empty one is rejected in the same
        # exclusivity spirit as the existing mixed ``kind:``/``source:``
        # rejection: nobody is forced to write one, and an author who does
        # is expecting a rendering that will never happen.
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"doc-ref '{name}' uses the source-registry form "
                f"'covers: {{ source: {covers_source} }}' and also declares "
                f"a non-empty 'sections:'. The two are exclusive — a "
                f"derived source renders its own records, so the sections "
                f"would never be rendered."
            ),
            file=filename,
            line=decl.start_line,
            column=1,
            severity="error",
            remediation=(
                f"Remove the 'sections:' field from doc-ref '{name}' (it is "
                f"optional for the source-registry form), or switch "
                f"'covers:' to the filter form "
                f"'[<kind> where <predicate>]' if you meant to render "
                f"project components."
            ),
            context={
                "declaration_type": "doc-ref",
                "declaration_name": name,
                "covers_source": covers_source,
            },
        )

    tags = tuple(_parse_name_list(
        fields.get("tags", ""), filename, decl.start_line
    )) if fields.get("tags", "").strip() else ()

    return DocRefDecl(
        name=name,
        module_location=module_name,
        intent=intent,
        format=doc_format,
        output=output,
        covers=covers,
        covers_source=covers_source,
        sections=sections,
        tags=tags,
        location=SourceLocation(
            start_line=decl.start_line,
            start_column=1,
            end_line=decl.end_line,
            end_column=1,
            file=filename,
        ),
    )


# ---------------------------------------------------------------------------
# G7a (feedback 5–6 cleanup): ``covers:`` discriminated-union parser.
#
# Recognised forms:
#   covers: [nerve where visibility == PUBLIC]   # historic — list of filters
#   covers: { source: error_codes }              # G7a — derived registry
#
# The two are exclusive. Anything that is neither (e.g. ``{ kind: ... }``,
# ``{ source: error_codes, kind: nerve }``, an unknown source name) raises
# at parse time. The plan rejects polymorphic bare-string sentinels because
# they overload the existing kind-name string-value space.
# ---------------------------------------------------------------------------


# The source names valid in this release. ADR-013 §1 makes the derived-source
# registry the single place a source name exists, so this is a read of that
# registry rather than a copy of it: the parser, the three renderers, and the
# spec's §4.12.1 enumeration all answer to one authority. Adding a source is a
# registration — a provider component plus a registry row — and touches
# nothing here.
#
# The import is function-local because the registry lives under
# ``codegen/``: importing it at parser module load would make the parser
# depend on codegen package initialisation, and the parser is imported by
# codegen. After the first call it is a ``sys.modules`` lookup.
def _doc_ref_covers_sources() -> frozenset[str]:
    """Return the derived source names registered for this release."""
    from s0ma_dsl.codegen.doc_emitter.derived_sources import (
        derived_source_names,
    )

    return derived_source_names()


def _parse_doc_ref_covers(
    raw: str,
    decl_name: str,
    filename: str,
    line: int,
) -> tuple[tuple[FilterExprAst, ...], str | None]:
    """Parse a doc-ref ``covers:`` value into its discriminated-union shape.

    Returns ``(filters, None)`` for the list-of-filters form and
    ``((), source_name)`` for the ``{ source: <name> }`` form. Raises
    :class:`S0maParseError` for any other shape, including:

    - a brace-form value carrying both ``source:`` and ``kind:`` (the
      discriminator must be exclusive);
    - a brace-form value with an unknown sub-key;
    - a brace-form value naming a source the derived-source registry does
      not register for this release (:func:`_doc_ref_covers_sources`);
    - any malformed brace-form (missing colon, unbalanced braces, etc.).

    The list-of-filters branch delegates to :func:`_parse_filter_expr`; if
    that raises, the caller (``_build_doc_ref``) propagates the error.
    """
    stripped = raw.strip()
    if stripped.startswith("{"):
        return ((), _parse_doc_ref_covers_source(
            stripped, decl_name, filename, line,
        ))

    # Historic list-of-filters form.
    filters = tuple(
        _parse_filter_expr(piece, filename, line)
        for piece in _split_bracketed_list(raw)
    )
    return filters, None


def _parse_doc_ref_covers_source(
    raw: str,
    decl_name: str,
    filename: str,
    line: int,
) -> str:
    """Parse a brace-form ``covers:`` value and return its source name.

    The accepted shape is ``{ source: <name> }`` — a single-entry
    dictionary whose only key is ``source`` and whose value is registered
    in the derived-source registry (:func:`_doc_ref_covers_sources`).
    Whitespace and a trailing comma are permitted. Anything else raises
    ``PARSE_ERROR`` with a remediation pointing at the supported shapes.
    """
    body = raw.strip()
    if not (body.startswith("{") and body.endswith("}")):
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"doc-ref '{decl_name}' has a malformed 'covers:' value: "
                f"{raw!r}. Expected either a bracketed list of filter "
                f"expressions or a '{{ source: <name> }}' dictionary."
            ),
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=(
                "Use 'covers: [<kind> where <predicate>]' for component "
                "filters, or 'covers: { source: error_codes }' to pull "
                "from the canonical error-code registry."
            ),
            context={"declaration_name": decl_name, "raw_value": raw},
        )
    inner = body[1:-1].strip()
    # Allow a trailing comma so authors can carry per-line formatting.
    if inner.endswith(","):
        inner = inner[:-1].strip()

    entries = _split_bracketed_list(inner) if inner else []
    parsed: dict[str, str] = {}
    for entry in entries:
        if ":" not in entry:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"doc-ref '{decl_name}' has a malformed 'covers:' "
                    f"sub-entry {entry!r}. Each entry must be "
                    f"'<key>: <value>'."
                ),
                file=filename,
                line=line,
                column=1,
                severity="error",
                remediation=(
                    "Inside 'covers: { ... }' every entry must use "
                    "'<key>: <value>' form. The only supported key is "
                    "'source', whose value is a name the derived-source "
                    "registry registers for this release: "
                    + ", ".join(sorted(_doc_ref_covers_sources())) + "."
                ),
                context={"declaration_name": decl_name, "entry": entry},
            )
        key, _, value = entry.partition(":")
        key_clean = key.strip()
        value_clean = value.strip()
        if not key_clean or not value_clean:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"doc-ref '{decl_name}' has an empty key or value in "
                    f"'covers:' sub-entry {entry!r}."
                ),
                file=filename,
                line=line,
                column=1,
                severity="error",
                remediation=(
                    "Inside 'covers: { ... }' every entry must use "
                    "'<key>: <value>' with non-empty key and value."
                ),
                context={"declaration_name": decl_name, "entry": entry},
            )
        if key_clean in parsed:
            raise S0maParseError(
                code="PARSE_ERROR",
                message=(
                    f"doc-ref '{decl_name}' repeats key {key_clean!r} in "
                    f"'covers:' dictionary."
                ),
                file=filename,
                line=line,
                column=1,
                severity="error",
                remediation=(
                    "Each key in 'covers: { ... }' must appear at most "
                    "once."
                ),
                context={
                    "declaration_name": decl_name,
                    "duplicate_key": key_clean,
                },
            )
        parsed[key_clean] = value_clean

    # Discriminator: ``source:`` is the only supported key, and it
    # is exclusive with the list-of-filters form. ``kind:`` is rejected
    # explicitly so the diagnostic names the conflict instead of emitting
    # the generic "unknown key" message — kind-form filters belong in a
    # bracketed list, not in the source dictionary.
    if "kind" in parsed and "source" in parsed:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"doc-ref '{decl_name}' has both 'kind:' and 'source:' in "
                f"its 'covers:' dictionary; the two are exclusive."
            ),
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=(
                "Choose one shape: 'covers: [<kind> where <predicate>]' "
                "for component filters, or "
                "'covers: { source: error_codes }' for the error-code "
                "registry."
            ),
            context={"declaration_name": decl_name, "keys": sorted(parsed)},
        )

    if "source" not in parsed:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"doc-ref '{decl_name}' has a 'covers:' dictionary "
                f"missing the required 'source:' key. Got keys "
                f"{sorted(parsed)!r}."
            ),
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=(
                "The dictionary form of 'covers:' takes one key — "
                "'source: <name>'. The names this release registers are: "
                + ", ".join(sorted(_doc_ref_covers_sources())) + "."
            ),
            context={"declaration_name": decl_name, "keys": sorted(parsed)},
        )

    extras = sorted(set(parsed) - {"source"})
    if extras:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"doc-ref '{decl_name}' has unrecognised keys "
                f"{extras!r} in its 'covers:' dictionary."
            ),
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=(
                "The dictionary form of 'covers:' supports only the "
                "'source:' key today. Remove the extra keys or move them "
                "into a different field."
            ),
            context={"declaration_name": decl_name, "extra_keys": extras},
        )

    source_name = parsed["source"]
    registered = _doc_ref_covers_sources()
    if source_name not in registered:
        supported = ", ".join(sorted(registered))
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"doc-ref '{decl_name}' references unknown 'covers: "
                f"{{ source: {source_name} }}'. Supported source(s): "
                f"{supported}."
            ),
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=(
                f"Set 'source:' to one of: {supported}. Adding a new "
                f"source is a registration, not a renderer edit: register "
                f"a provider component and its row in "
                f"codegen/doc_emitter/derived_sources.py (ADR-013)."
            ),
            context={
                "declaration_name": decl_name,
                "source": source_name,
                "supported": sorted(registered),
            },
        )
    return source_name


def _build_doc_guide(
    decl: _RawDeclaration,
    filename: str,
    module_name: str,
    mode: StrictnessMode = StrictnessMode.DEV,
) -> tuple[DocGuideDecl, list[S0maParseError | S0maSemanticError]]:
    """Build a DocGuideDecl from a raw declaration.

    doc-guide has a mandatory ``---`` separator followed by a prose body.
    The prose body is tokenised by the M3 prose parser: the returned
    ``DocGuideDecl`` carries the full token stream in ``prose_tokens``
    (with the byte-exact ``prose_body`` preserved alongside), and the
    returned diagnostics list contains any prose-level findings
    (``PROSE_RAW_CODE_BLOCK`` errors, ``POSSIBLE_UNRESOLVED_REFERENCE``
    heuristic warnings). Callers merge those diagnostics with
    body-validation diagnostics for uniform reporting.
    """
    name = decl.header_names[0]
    fields = decl.fields

    _require_field("intent", fields, "doc-guide", name, filename, decl.start_line)
    _require_field("format", fields, "doc-guide", name, filename, decl.start_line)
    _require_field("output", fields, "doc-guide", name, filename, decl.start_line)
    _require_field("covers", fields, "doc-guide", name, filename, decl.start_line)
    _require_field("asserts", fields, "doc-guide", name, filename, decl.start_line)
    _require_field("examples", fields, "doc-guide", name, filename, decl.start_line)

    if not decl.saw_separator:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"doc-guide '{name}' is missing the '---' separator and prose body."
            ),
            file=filename,
            line=decl.end_line,
            column=1,
            severity="error",
            remediation=(
                f"Add a '---' separator after the last field of doc-guide '{name}', "
                "followed by the prose body."
            ),
            context={"declaration_type": "doc-guide", "declaration_name": name},
        )
    if decl.body is None or not decl.body.strip():
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"doc-guide '{name}' has an empty prose body after the '---' separator.",
            file=filename,
            line=decl.body_start_line or decl.end_line,
            column=1,
            severity="error",
            remediation=(
                f"Add authored prose content to the body of doc-guide '{name}', "
                "or delete the declaration if no guide is needed."
            ),
            context={"declaration_type": "doc-guide", "declaration_name": name},
        )

    intent = _parse_string_field(fields["intent"])
    doc_format = _parse_string_field(fields["format"])
    output = _parse_string_field(fields["output"])
    covers = tuple(
        _parse_entity_ref(piece, filename, decl.start_line)
        for piece in _split_bracketed_list(fields["covers"])
    )
    asserts = tuple(
        _parse_assert_pred(piece, filename, decl.start_line)
        for piece in _split_bracketed_list(fields["asserts"])
    )
    examples_refs = tuple(
        _parse_entity_ref(piece, filename, decl.start_line)
        for piece in _split_bracketed_list(fields["examples"])
    )
    tags = tuple(_parse_name_list(
        fields.get("tags", ""), filename, decl.start_line
    )) if fields.get("tags", "").strip() else ()

    # M3: tokenise the prose body. parse_prose preserves decl.body
    # byte-for-byte via its token stream and surfaces structural
    # (PROSE_RAW_CODE_BLOCK) and heuristic (POSSIBLE_UNRESOLVED_REFERENCE)
    # diagnostics for the top-level orchestrator to aggregate.
    prose_tokens, prose_diagnostics = parse_prose(
        decl.body,
        filename,
        decl.body_start_line or decl.end_line,
        mode,
    )

    guide = DocGuideDecl(
        name=name,
        module_location=module_name,
        intent=intent,
        format=doc_format,
        output=output,
        covers=covers,
        asserts=asserts,
        examples=examples_refs,
        prose_body=decl.body,
        prose_tokens=prose_tokens,
        tags=tags,
        location=SourceLocation(
            start_line=decl.start_line,
            start_column=1,
            end_line=decl.end_line,
            end_column=1,
            file=filename,
        ),
    )
    return guide, prose_diagnostics


# A8 (T2): the mandatory ``runs_in:`` field on an ``example`` selects a
# dispatcher arm in s0ma-core's ``ExampleDispatcher.dispatch`` — the three
# names below are the only arms that exist. Spec §4.12.3 declares the
# field as ``runs_in: <standalone | pytest | integration>``; anything else
# can never execute, so it is a layer-1 ``PARSE_ERROR`` in every
# strictness mode rather than a deferred runtime ``ValueError``.
#
# Ordered (not a frozenset) so the diagnostic lists the modes in the
# spec's declared order deterministically.
VALID_EXAMPLE_RUNS_IN: tuple[str, ...] = ("standalone", "pytest", "integration")


def _build_example(
    decl: _RawDeclaration, filename: str, module_name: str
) -> ExampleDecl:
    """Build an ExampleDecl from a raw declaration.

    example has a mandatory ``---`` separator followed by a python body.
    The python body is syntax-checked via :func:`extract_body`; escape-hatch
    validation happens during top-level parsing via
    :func:`validate_example_body`.
    """
    name = decl.header_names[0]
    fields = decl.fields

    _require_field("intent", fields, "example", name, filename, decl.start_line)
    _require_field("demonstrates", fields, "example", name, filename, decl.start_line)
    _require_field("runs_in", fields, "example", name, filename, decl.start_line)

    if not decl.saw_separator:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"example '{name}' is missing the '---' separator and python body.",
            file=filename,
            line=decl.end_line,
            column=1,
            severity="error",
            remediation=(
                f"Add a '---' separator after the last field of example '{name}', "
                "followed by the python body."
            ),
            context={"declaration_type": "example", "declaration_name": name},
        )
    if decl.body is None or not decl.body.strip():
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"example '{name}' has an empty python body after the '---' separator.",
            file=filename,
            line=decl.body_start_line or decl.end_line,
            column=1,
            severity="error",
            remediation=(
                f"Add python code demonstrating the referenced components in example '{name}', "
                "or delete the declaration."
            ),
            context={"declaration_type": "example", "declaration_name": name},
        )

    intent = _parse_string_field(fields["intent"])
    runs_in = _parse_string_field(fields["runs_in"])
    if runs_in not in VALID_EXAMPLE_RUNS_IN:
        valid = ", ".join(VALID_EXAMPLE_RUNS_IN)
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"example '{name}' has invalid runs_in {runs_in!r}. "
                f"Valid values are: {valid}."
            ),
            file=filename,
            line=decl.start_line,
            column=1,
            severity="error",
            remediation=(
                f"Set 'runs_in:' on example '{name}' to one of: {valid}. "
                "Each names an execution context the example runner can "
                "dispatch to; any other value could never run."
            ),
            context={
                "declaration_type": "example",
                "declaration_name": name,
                "runs_in": runs_in,
                "valid": list(VALID_EXAMPLE_RUNS_IN),
            },
        )
    demonstrates = tuple(
        _parse_entity_ref(piece, filename, decl.start_line)
        for piece in _split_bracketed_list(fields["demonstrates"])
    )
    tags = tuple(_parse_name_list(
        fields.get("tags", ""), filename, decl.start_line
    )) if fields.get("tags", "").strip() else ()

    return ExampleDecl(
        name=name,
        module_location=module_name,
        intent=intent,
        demonstrates=demonstrates,
        runs_in=runs_in,
        python_body=decl.body,
        tags=tags,
        location=SourceLocation(
            start_line=decl.start_line,
            start_column=1,
            end_line=decl.end_line,
            end_column=1,
            file=filename,
        ),
    )


def _build_depends_on(
    raw_lines: list[str], filename: str, decl_line: int
) -> tuple[InlineAxon, ...]:
    """Build InlineAxon tuple from raw depends_on entry lines."""
    if not raw_lines:
        return ()
    result = []
    for raw_line in raw_lines:
        parsed = _parse_depends_on_entry(raw_line, filename, decl_line)
        relation_str = parsed["relation"]
        coupling_str = parsed["coupling"]
        result.append(InlineAxon(
            target=parsed["target"],
            relation=_RELATION_MAP[relation_str],
            carries=parsed["carries"],
            coupling=_COUPLING_MAP[coupling_str],
        ))
    return tuple(result)


def _require_field(
    field_name: str,
    fields: dict[str, str],
    decl_type: str,
    decl_name: str,
    filename: str,
    line: int,
) -> None:
    """Raise S0maParseError if a required field is missing."""
    if field_name not in fields or not fields[field_name].strip():
        raise S0maParseError(
            code="MISSING_FIELD",
            message=f"Missing required field '{field_name}' in {decl_type} '{decl_name}'.",
            file=filename,
            line=line,
            column=1,
            severity="error",
            remediation=(
                f"Add '{field_name}: <value>' to the {decl_type} "
                f"'{decl_name}' declaration."
            ),
            context={
                "declaration_type": decl_type,
                "declaration_name": decl_name,
                "field": field_name,
            },
        )


# ---------------------------------------------------------------------------
# Body line helpers
# ---------------------------------------------------------------------------


def _decl_body_start_line(decl: ExampleDecl) -> int:
    """Return a reasonable source line for an example's python body start."""
    return decl.location.start_line if decl.location is not None else 1


def _body_start_line(
    decl: NerveDecl | CellDecl | GanglionDecl | TestDecl | HelperDecl,
) -> int:
    """Estimate the .s0ma source line where a declaration's body starts.

    The body starts after the ``---`` separator. Since we don't track the
    separator line exactly, we use the declaration's location end_line as
    a reasonable approximation (the body follows immediately after fields
    and the separator).
    """
    if decl.location is not None:
        # The body is captured after the separator; the end_line of the
        # declaration's location is set to the last line of the entire
        # declaration block (including body). We approximate body start
        # by scanning the body text position — but since we preserved
        # exact body text, we use the declaration start_line as a
        # conservative base for error reporting.
        return decl.location.start_line
    return 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_S0maParser",
    kind=ComponentKind.SERVICE,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Main parser for .s0ma files — splits declarations, parses field values with Lark, and "
        "builds typed AST nodes."
    ),
    idempotent=True,
    is_framework=True,
)
class S0maParser:
    """Parser for ``.s0ma`` source files.

    Implements a two-phase strategy:
      1. Line-based preprocessor splits into declaration blocks.
      2. Lark LALR(1) parses structured field values.

    Produces a ``S0maModule`` AST or raises ``S0maParseError``.
    """

    def parse(
        self,
        source: str,
        filename: str = "<string>",
        mode: StrictnessMode = StrictnessMode.DEV,
    ) -> S0maModule:
        """Parse a ``.s0ma`` source string into a ``S0maModule`` AST.

        Args:
            source: The full text content of a .s0ma file.
            filename: The file path (for diagnostics).
            mode: Strictness mode for body validation severity.

        Returns:
            A fully populated S0maModule AST node.

        Raises:
            S0maParseError: On any syntax or structural error.
        """
        return parse_s0ma(source, filename, mode=mode)


def _refine_bare_imports(
    body_errors: list[S0maParseError | S0maSemanticError],
    module_decl: ModuleDecl,
) -> None:
    """M-14 (POST-10f): refine ``BARE_IMPORT`` diagnostics in place.

    The body-extractor's ``_check_bare_imports`` does not know the
    module's ``uses:`` set when it runs (the body validator is called
    per-declaration during parsing), so its baseline message gives a
    generic remediation ("declare in `requires:` or `uses:`"). After
    the module is built, this helper walks the collected body
    diagnostics and tailors the ``BARE_IMPORT`` remediation per
    POST-10f. Every variant frames the complete fix as ONE edit with
    two parts — declare the dependency in the module header AND delete
    the bare import from the body — so a consumer that has already done
    one half reads the follow-up diagnostic as the remaining step of
    the same fix, never as a contradiction:

    * **Name already in ``uses:``** — the import name matches the
      local resolution of a ``uses:`` entry. The remediation confirms
      the header half is done and asks for the body-line deletion.
    * **Name already in a requires-family list** — same sequencing,
      and the diagnostic names the ACTUAL list the entry is in
      (``requires:`` / ``soft_requires:`` / ``runtime_only_requires:``
      / ``deferred_requires:``).
    * **Name not declared anywhere** — the remediation spells out both
      parts of the edit explicitly and simultaneously.
    * **Other patterns** — fall through to the baseline text.

    The original diagnostic carries the import-statement source in
    its ``context['import_statement']`` field; the refinement parses
    that string to recover the imported names. Only ``BARE_IMPORT``
    diagnostics are touched; the others are left untouched.
    """
    # Collect the local-name set the body would have seen from
    # ``uses:``. The names follow ``_uses_local_name`` semantics
    # (final dotted segment, or the entry's alias).
    uses_local_names: set[str] = set()
    uses_local_to_qualified: dict[str, str] = {}
    for entry in module_decl.uses:
        local = entry.alias or entry.qualified_name.rsplit(".", 1)[-1]
        uses_local_names.add(local)
        uses_local_to_qualified[local] = entry.qualified_name

    # Same shape for ``requires:`` / ``soft_requires:`` /
    # ``runtime_only_requires:`` / ``deferred_requires:`` — a name
    # already there is also an "imported automatically" hit (deferred
    # entries are imported automatically too, just at call time inside
    # the consuming def — DSL-M2, ADR-011 §(c)). The map records WHICH
    # list each local name came from so the refined remediation can
    # name the actual list instead of a four-way parenthetical.
    requires_local_to_list: dict[str, str] = {}
    for list_name, entries in (
        ("requires", module_decl.requires),
        ("soft_requires", module_decl.soft_requires),
        ("runtime_only_requires", module_decl.runtime_only_requires),
        ("deferred_requires", module_decl.deferred_requires),
    ):
        for req_entry in entries:
            if req_entry.alias:
                local = req_entry.alias
            elif req_entry.is_from_import:
                local = req_entry.module_path.rsplit(".", 1)[-1]
            else:
                local = req_entry.module_path.split(".")[0]
            requires_local_to_list.setdefault(local, list_name)

    for i, err in enumerate(body_errors):
        if err.code != "BARE_IMPORT":
            continue
        ctx = err.context or {}
        stmt = ctx.get("import_statement")
        if not isinstance(stmt, str):
            continue

        # Parse the statement back into the bound local names AND the
        # header tokens a ``requires:`` entry would need — the two
        # differ, and suggesting the wrong shape breaks the build at
        # import time (a bare ``requires: [Path]`` checks clean but
        # emits a literal ``import Path``):
        #   * ``import a.b, c`` — locals are ``[a, c]``; the header
        #     tokens are the full dotted paths ``[a.b, c]`` (which emit
        #     ``import a.b`` / ``import c`` verbatim).
        #   * ``from m import n, o`` — locals are ``[n, o]``; the
        #     header tokens are the colon-override forms
        #     ``[m:n, m:o]``, the deterministic shape that emits
        #     ``from m import n``.
        imported_locals: list[str] = []
        header_tokens: list[str] = []
        if stmt.startswith("from "):
            head, _, rest = stmt.partition(" import ")
            source_module = head[len("from "):].strip()
            for raw in rest.split(","):
                token = raw.strip().split(" as ")[0].strip()
                if token:
                    imported_locals.append(token)
                    header_tokens.append(
                        f"{source_module}:{token}" if source_module else token
                    )
        elif stmt.startswith("import "):
            rest = stmt[len("import "):]
            for raw in rest.split(","):
                token = raw.strip().split(" as ")[0].strip()
                if token:
                    # ``import a.b`` → local binding is ``a``; the
                    # header token stays the full dotted path.
                    imported_locals.append(token.split(".")[0])
                    header_tokens.append(token)

        # Tailor the remediation. The variants are explicitly
        # sequenced as ONE fix with two parts (declare in header +
        # delete from body) so an agent that already did the header
        # half reads the follow-up diagnostic as step 2 of the same
        # fix, not a contradiction. The "already declared" variants
        # fire only when EVERY bound name is covered — otherwise
        # "delete the line" would orphan an undeclared sibling of a
        # multi-name import.
        refined_remediation: str | None = None
        first_name = imported_locals[0] if imported_locals else None
        undeclared = [
            (local, token)
            for local, token in zip(
                imported_locals, header_tokens, strict=True
            )
            if local not in uses_local_names
            and local not in requires_local_to_list
        ]
        if first_name and not undeclared:
            names_text = ", ".join(f"`{n}`" for n in imported_locals)
            verb = "is" if len(imported_locals) == 1 else "are"
            if first_name in uses_local_names:
                qualified = uses_local_to_qualified.get(first_name, first_name)
                where = f"`uses: [{qualified}]`"
            else:
                where = f"`{requires_local_to_list[first_name]}:`"
            refined_remediation = (
                f"{names_text} {verb} already declared in "
                f"{where} — that half is done; the transpiler "
                f"imports it automatically. Now delete the `{stmt}` "
                f"line from the body (declared-in-header + "
                f"deleted-from-body is the complete fix)."
            )
        elif undeclared:
            # Bias toward ``requires:`` for stdlib-shaped names —
            # the canonical fix for an un-declared body-level
            # import is a single edit that touches the header AND
            # the body. Spelling out both parts as simultaneous
            # halves prevents the observed half-fix thrash (agent
            # adds the header entry, keeps the import line, then
            # reads the follow-up diagnostic as a contradiction).
            tokens_text = ", ".join(f"`{token}`" for _, token in undeclared)
            first_undeclared_local = undeclared[0][0]
            refined_remediation = (
                f"Fix in ONE edit, two parts: (1) add {tokens_text} "
                f"to the module header's `requires:` list (or "
                f"`deferred_requires:` for a call-time import with "
                f"per-call failure semantics), AND (2) delete the "
                f"`{stmt}` line from this body. The transpiler emits "
                f"the import from the declaration — a bare import in "
                f"the body is always an error even after the header "
                f"declares it. (If `{first_undeclared_local}` refers "
                f"to a s0ma component, add the fully-qualified path "
                f"to `uses:` instead.)"
            )

        if refined_remediation is None:
            continue

        # S0maSemanticError / S0maParseError are dataclasses; we
        # rebuild the record with the refined remediation. Other
        # fields stay intact so downstream consumers see the same
        # code / message / location.
        body_errors[i] = type(err)(
            code=err.code,
            message=err.message,
            file=err.file,
            line=err.line,
            column=err.column,
            severity=err.severity,
            remediation=refined_remediation,
            context=err.context,
        )


@component(
    name="S0maDSL_parse_s0ma",
    kind=ComponentKind.FUNCTION,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Parse a .s0ma source string into a typed S0maModule AST, enforcing grammar rules and "
        "extracting validated Python bodies."
    ),
    idempotent=True,
    is_framework=True,
)
def parse_s0ma(
    source: str,
    filename: str = "<string>",
    mode: StrictnessMode = StrictnessMode.DEV,
    *,
    _allow_legacy_semantic_omissions: bool = False,
) -> S0maModule:
    """Parse a ``.s0ma`` source string into a ``S0maModule`` AST.

    This is the main entry point for the parser. It splits the source
    into declaration blocks, parses field values, and builds AST nodes.
    Then extracts and validates Python bodies.

    Args:
        source: The full text content of a .s0ma file.
        filename: The file path (for diagnostics).
        mode: Strictness mode for body validation severity.

    Returns:
        A fully populated S0maModule AST node.

    Raises:
        S0maParseError: On any syntax or structural error.
    """
    # Phase 1: split into raw declarations
    raw_decls = _split_declarations(source, filename)
    _prepare_semantic_markers(
        raw_decls,
        filename,
        allow_legacy_omissions=_allow_legacy_semantic_omissions,
    )

    if not raw_decls:
        raise S0maParseError(
            code="PARSE_ERROR",
            message="Empty .s0ma file — no declarations found.",
            file=filename,
            line=1,
            column=1,
            severity="error",
            remediation="Every .s0ma file must begin with a module declaration.",
        )

    # First declaration must be a module (FR-02)
    if raw_decls[0].decl_type != "module":
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"File must begin with a module declaration, "
                f"found '{raw_decls[0].decl_type}' instead."
            ),
            file=filename,
            line=raw_decls[0].start_line,
            column=1,
            severity="error",
            remediation="Add a 'module <name>' declaration at the top of the file.",
        )

    # Build module
    module_decl = _build_module(raw_decls[0], filename)

    # Build component declarations
    nerves: list[NerveDecl] = []
    cells: list[CellDecl] = []
    ganglia: list[GanglionDecl] = []
    tests: list[TestDecl] = []
    axons: list[StandaloneAxonDecl] = []
    # POST-4b (0.15.0): inline helpers declared in the module header's
    # ``helpers:`` field are materialised here so they live in the same
    # list as the block-form helpers. Source order is preserved by
    # processing inline helpers (declared in the module header, which
    # is always raw_decls[0]) before the subsequent declarations.
    helpers: list[HelperDecl] = list(_build_inline_helpers(
        raw_decls[0], module_decl.layer, filename,
    ))
    integrations: list[IntegrationDecl] = []
    doc_refs: list[DocRefDecl] = []
    doc_guides: list[DocGuideDecl] = []
    examples: list[ExampleDecl] = []
    _pending_prose_diagnostics: list[S0maParseError | S0maSemanticError] = []

    for raw in raw_decls[1:]:
        if raw.decl_type == "nerve":
            nerves.append(_build_nerve(raw, filename))
        elif raw.decl_type == "cell":
            cells.append(_build_cell(raw, filename))
        elif raw.decl_type == "ganglion":
            ganglia.append(_build_ganglion(raw, filename))
        elif raw.decl_type == "test":
            tests.append(_build_test(raw, filename))
        elif raw.decl_type == "axon":
            axons.append(_build_axon(raw, filename))
        elif raw.decl_type == "helper":
            helpers.append(_build_helper(raw, filename))
        elif raw.decl_type == "integration":
            integrations.append(_build_integration(raw, filename))
        elif raw.decl_type == "doc_ref":
            doc_refs.append(_build_doc_ref(raw, filename, module_decl.name))
        elif raw.decl_type == "doc_guide":
            guide, guide_diagnostics = _build_doc_guide(
                raw, filename, module_decl.name, mode,
            )
            doc_guides.append(guide)
            _pending_prose_diagnostics.extend(guide_diagnostics)
        elif raw.decl_type == "example":
            examples.append(_build_example(raw, filename, module_decl.name))
        elif raw.decl_type == "module":
            raise S0maParseError(
                code="PARSE_ERROR",
                message="Multiple module declarations found — only one per file is allowed.",
                file=filename,
                line=raw.start_line,
                column=1,
                severity="error",
                remediation=(
                    "Remove the extra module declaration. "
                    "Each .s0ma file has exactly one module."
                ),
            )

    # Phase 3: Body extraction, canonicalisation, and validation.
    #
    # F1 (feedback 5–6 follow-up): bodies are dedented exactly once here.
    # Each declaration's ``body`` (or ``python_body`` for examples) is
    # replaced with the canonical, Python-ready dedented form returned by
    # :func:`extract_body`; the original raw text is preserved on
    # ``raw_body`` (or ``raw_python_body``) for diagnostics. Every
    # downstream consumer (validator, codegen, IR, derived edges, source
    # map, doc subsystem) reads the canonical value directly — no
    # secondary dedent.
    #
    # Body validation errors are collected; the first hard error is raised.
    # Prose diagnostics collected during _build_doc_guide flow in first so
    # release-mode promotion of POSSIBLE_UNRESOLVED_REFERENCE fires at the
    # same collection point as body-level findings. The description-line
    # reports (``UNKNOWN_FIELD``, ``UNRECOGNIZED_LINE``) join them here for
    # the same reason: their severity ladders with the mode.
    body_errors: list[S0maParseError | S0maSemanticError] = [
        *_check_declaration_lines(raw_decls, filename, mode),
        *_pending_prose_diagnostics,
    ]

    for i, nerve in enumerate(nerves):
        if nerve.body is not None:
            body_info = extract_body(nerve.body, filename, _body_start_line(nerve))
            nerves[i] = _dc_replace(
                nerve, body=body_info.dedented_text, raw_body=body_info.source_text,
            )
            body_errors.extend(validate_body(
                body_info, "nerve", nerve.name, nerve.kind,
                filename, _body_start_line(nerve), mode,
            ))

    for i, cell in enumerate(cells):
        if cell.body is not None:
            body_info = extract_body(cell.body, filename, _body_start_line(cell))
            cells[i] = _dc_replace(
                cell, body=body_info.dedented_text, raw_body=body_info.source_text,
            )
            body_errors.extend(validate_body(
                body_info, "cell", cell.name, cell.kind,
                filename, _body_start_line(cell), mode,
            ))

    for i, ganglion in enumerate(ganglia):
        if ganglion.body is not None:
            body_info = extract_body(ganglion.body, filename, _body_start_line(ganglion))
            ganglia[i] = _dc_replace(
                ganglion, body=body_info.dedented_text, raw_body=body_info.source_text,
            )
            body_errors.extend(validate_body(
                body_info, "ganglion", ganglion.name, None,
                filename, _body_start_line(ganglion), mode,
            ))

    for i, test in enumerate(tests):
        if test.body is not None:
            body_info = extract_body(test.body, filename, _body_start_line(test))
            tests[i] = _dc_replace(
                test, body=body_info.dedented_text, raw_body=body_info.source_text,
            )
            body_errors.extend(validate_body(
                body_info, "test", test.name, None,
                filename, _body_start_line(test), mode,
            ))

    for i, helper in enumerate(helpers):
        if helper.body is not None:
            body_info = extract_body(
                helper.body, filename, _body_start_line(helper),
            )
            # POST-4a (0.15.0): reconcile body_kind from the AST-derived
            # BodyType (``CLASS`` vs ``FUNCTION``) so the canonical value
            # always matches the validator's classification. Inline
            # helpers (POST-4b) are always functions and the provisional
            # value already reflects that.
            from s0ma_dsl.parser.body_extractor import BodyType as _BodyType
            reconciled_kind = (
                "class" if body_info.body_type == _BodyType.CLASS
                else "function"
            )
            if helper.inline:
                # POST-4b: inline helpers carry a single-line body
                # already in canonical form. Preserve the original raw
                # text on ``raw_body`` (already set at materialisation
                # time) so diagnostics still see the source-form body.
                helpers[i] = _dc_replace(
                    helper,
                    body=body_info.dedented_text,
                    body_kind=reconciled_kind,
                )
            else:
                helpers[i] = _dc_replace(
                    helper,
                    body=body_info.dedented_text,
                    raw_body=body_info.source_text,
                    body_kind=reconciled_kind,
                )
            body_errors.extend(validate_body(
                body_info, "helper", helper.name, None,
                filename, _body_start_line(helper), mode,
            ))

    for i, example in enumerate(examples):
        body_info = extract_body(example.python_body, filename, _decl_body_start_line(example))
        examples[i] = _dc_replace(
            example,
            python_body=body_info.dedented_text,
            raw_python_body=body_info.source_text,
        )
        body_errors.extend(validate_example_body(
            body_info, example.name, filename, _decl_body_start_line(example), mode,
        ))

    # M-14 (POST-10f): refine ``BARE_IMPORT`` remediation text now
    # that the module-header ``uses:`` / ``requires:`` sets are
    # built. Idempotent: only ``BARE_IMPORT`` diagnostics are
    # touched, and the refinement only fires when the original
    # message would have been confusing for the author.
    _refine_bare_imports(body_errors, module_decl)

    # Raise the first hard error (severity == "error") if any
    for err in body_errors:
        if err.severity == "error":
            raise err

    return _finalize_semantic_states(S0maModule(
        module=module_decl,
        nerves=tuple(nerves),
        cells=tuple(cells),
        ganglia=tuple(ganglia),
        tests=tuple(tests),
        axons=tuple(axons),
        helpers=tuple(helpers),
        integrations=tuple(integrations),
        doc_refs=tuple(doc_refs),
        doc_guides=tuple(doc_guides),
        examples=tuple(examples),
    ), raw_decls)


@component(
    name="S0maDSL_parse_s0ma_with_warnings",
    kind=ComponentKind.FUNCTION,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Parse a .s0ma source string returning both the AST and any non-fatal body-validation "
        "warnings for caller collection."
    ),
    idempotent=True,
    is_framework=True,
)
def parse_s0ma_with_warnings(
    source: str,
    filename: str = "<string>",
    mode: StrictnessMode = StrictnessMode.DEV,
    *,
    _allow_legacy_semantic_omissions: bool = False,
) -> tuple[S0maModule, list[S0maParseError | S0maSemanticError]]:
    """Parse a ``.s0ma`` source string, returning warnings alongside the AST.

    Unlike :func:`parse_s0ma`, which silently discards body-validation
    warnings (e.g. ``PROHIBITED_CONSTRUCT`` and ``BARE_IMPORT`` in
    MIGRATION/DEV mode), this function returns them so callers can
    display or collect them.

    Args:
        source: The full text content of a .s0ma file.
        filename: The file path (for diagnostics).
        mode: Strictness mode for body validation severity.

    Returns:
        A tuple of ``(module, warnings)`` where *warnings* contains any
        non-error body-validation diagnostics.

    Raises:
        S0maParseError: On any syntax or structural error (severity == "error").
    """
    # Phase 1: split into raw declarations
    raw_decls = _split_declarations(source, filename)
    _prepare_semantic_markers(
        raw_decls,
        filename,
        allow_legacy_omissions=_allow_legacy_semantic_omissions,
    )

    if not raw_decls:
        raise S0maParseError(
            code="PARSE_ERROR",
            message="Empty .s0ma file — no declarations found.",
            file=filename,
            line=1,
            column=1,
            severity="error",
            remediation="Every .s0ma file must begin with a module declaration.",
        )

    # First declaration must be a module (FR-02)
    if raw_decls[0].decl_type != "module":
        raise S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"File must begin with a module declaration, "
                f"found '{raw_decls[0].decl_type}' instead."
            ),
            file=filename,
            line=raw_decls[0].start_line,
            column=1,
            severity="error",
            remediation="Add a 'module <name>' declaration at the top of the file.",
        )

    # Build module
    module_decl = _build_module(raw_decls[0], filename)

    # Build component declarations
    nerves: list[NerveDecl] = []
    cells: list[CellDecl] = []
    ganglia: list[GanglionDecl] = []
    tests: list[TestDecl] = []
    axons: list[StandaloneAxonDecl] = []
    # POST-4b (0.15.0): inline helpers declared inline in the module
    # header's ``helpers:`` field. See ``parse_s0ma`` for the source-
    # order rationale.
    helpers: list[HelperDecl] = list(_build_inline_helpers(
        raw_decls[0], module_decl.layer, filename,
    ))
    integrations: list[IntegrationDecl] = []
    doc_refs: list[DocRefDecl] = []
    doc_guides: list[DocGuideDecl] = []
    examples: list[ExampleDecl] = []
    _pending_prose_diagnostics: list[S0maParseError | S0maSemanticError] = []

    for raw in raw_decls[1:]:
        if raw.decl_type == "nerve":
            nerves.append(_build_nerve(raw, filename))
        elif raw.decl_type == "cell":
            cells.append(_build_cell(raw, filename))
        elif raw.decl_type == "ganglion":
            ganglia.append(_build_ganglion(raw, filename))
        elif raw.decl_type == "test":
            tests.append(_build_test(raw, filename))
        elif raw.decl_type == "axon":
            axons.append(_build_axon(raw, filename))
        elif raw.decl_type == "helper":
            helpers.append(_build_helper(raw, filename))
        elif raw.decl_type == "integration":
            integrations.append(_build_integration(raw, filename))
        elif raw.decl_type == "doc_ref":
            doc_refs.append(_build_doc_ref(raw, filename, module_decl.name))
        elif raw.decl_type == "doc_guide":
            guide, guide_diagnostics = _build_doc_guide(
                raw, filename, module_decl.name, mode,
            )
            doc_guides.append(guide)
            _pending_prose_diagnostics.extend(guide_diagnostics)
        elif raw.decl_type == "example":
            examples.append(_build_example(raw, filename, module_decl.name))
        elif raw.decl_type == "module":
            raise S0maParseError(
                code="PARSE_ERROR",
                message="Multiple module declarations found — only one per file is allowed.",
                file=filename,
                line=raw.start_line,
                column=1,
                severity="error",
                remediation=(
                    "Remove the extra module declaration. "
                    "Each .s0ma file has exactly one module."
                ),
            )

    # Phase 3: Body extraction, canonicalisation, and validation.
    # See ``parse_s0ma`` above for the F1 invariant: the parser dedents
    # bodies exactly once here; downstream consumers read the canonical
    # value via ``decl.body`` / ``example.python_body``.
    body_errors: list[S0maParseError | S0maSemanticError] = [
        *_check_declaration_lines(raw_decls, filename, mode),
        *_pending_prose_diagnostics,
    ]

    for i, nerve in enumerate(nerves):
        if nerve.body is not None:
            body_info = extract_body(nerve.body, filename, _body_start_line(nerve))
            nerves[i] = _dc_replace(
                nerve, body=body_info.dedented_text, raw_body=body_info.source_text,
            )
            body_errors.extend(validate_body(
                body_info, "nerve", nerve.name, nerve.kind,
                filename, _body_start_line(nerve), mode,
            ))

    for i, cell in enumerate(cells):
        if cell.body is not None:
            body_info = extract_body(cell.body, filename, _body_start_line(cell))
            cells[i] = _dc_replace(
                cell, body=body_info.dedented_text, raw_body=body_info.source_text,
            )
            body_errors.extend(validate_body(
                body_info, "cell", cell.name, cell.kind,
                filename, _body_start_line(cell), mode,
            ))

    for i, ganglion in enumerate(ganglia):
        if ganglion.body is not None:
            body_info = extract_body(ganglion.body, filename, _body_start_line(ganglion))
            ganglia[i] = _dc_replace(
                ganglion, body=body_info.dedented_text, raw_body=body_info.source_text,
            )
            body_errors.extend(validate_body(
                body_info, "ganglion", ganglion.name, None,
                filename, _body_start_line(ganglion), mode,
            ))

    for i, test in enumerate(tests):
        if test.body is not None:
            body_info = extract_body(test.body, filename, _body_start_line(test))
            tests[i] = _dc_replace(
                test, body=body_info.dedented_text, raw_body=body_info.source_text,
            )
            body_errors.extend(validate_body(
                body_info, "test", test.name, None,
                filename, _body_start_line(test), mode,
            ))

    for i, helper in enumerate(helpers):
        if helper.body is not None:
            body_info = extract_body(
                helper.body, filename, _body_start_line(helper),
            )
            # POST-4a (0.15.0): reconcile body_kind from the AST-derived
            # BodyType (``CLASS`` vs ``FUNCTION``) so the canonical value
            # always matches the validator's classification. Inline
            # helpers (POST-4b) are always functions and the provisional
            # value already reflects that.
            from s0ma_dsl.parser.body_extractor import BodyType as _BodyType
            reconciled_kind = (
                "class" if body_info.body_type == _BodyType.CLASS
                else "function"
            )
            if helper.inline:
                # POST-4b: inline helpers carry a single-line body
                # already in canonical form. Preserve the original raw
                # text on ``raw_body`` (already set at materialisation
                # time) so diagnostics still see the source-form body.
                helpers[i] = _dc_replace(
                    helper,
                    body=body_info.dedented_text,
                    body_kind=reconciled_kind,
                )
            else:
                helpers[i] = _dc_replace(
                    helper,
                    body=body_info.dedented_text,
                    raw_body=body_info.source_text,
                    body_kind=reconciled_kind,
                )
            body_errors.extend(validate_body(
                body_info, "helper", helper.name, None,
                filename, _body_start_line(helper), mode,
            ))

    for i, example in enumerate(examples):
        body_info = extract_body(example.python_body, filename, _decl_body_start_line(example))
        examples[i] = _dc_replace(
            example,
            python_body=body_info.dedented_text,
            raw_python_body=body_info.source_text,
        )
        body_errors.extend(validate_example_body(
            body_info, example.name, filename, _decl_body_start_line(example), mode,
        ))

    # M-14 (POST-10f): refine ``BARE_IMPORT`` remediation text now
    # that the module-header ``uses:`` / ``requires:`` sets are
    # built. See ``_refine_bare_imports`` for the contract.
    _refine_bare_imports(body_errors, module_decl)

    # Separate hard errors from warnings
    warnings: list[S0maParseError | S0maSemanticError] = []
    for err in body_errors:
        if err.severity == "error":
            raise err
        else:
            warnings.append(err)

    module = _finalize_semantic_states(S0maModule(
        module=module_decl,
        nerves=tuple(nerves),
        cells=tuple(cells),
        ganglia=tuple(ganglia),
        tests=tuple(tests),
        axons=tuple(axons),
        helpers=tuple(helpers),
        integrations=tuple(integrations),
        doc_refs=tuple(doc_refs),
        doc_guides=tuple(doc_guides),
        examples=tuple(examples),
    ), raw_decls)
    return module, warnings
