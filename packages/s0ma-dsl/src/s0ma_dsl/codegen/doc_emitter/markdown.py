"""Deterministic Markdown renderer for doc-ref and doc-guide declarations.

Per plan §M6 §5 / design §11.6: rendering is byte-for-byte reproducible.
The renderer is hand-rolled (no pluggable Markdown library) so output
never depends on a downstream package version. The syntax it emits is a
narrow subset of GitHub-Flavoured Markdown — headings, paragraphs,
fenced code blocks (`` ``` ``), and bullet lists — which is what every
common Markdown consumer already understands.

Determinism contract (plan §5):
- No timestamps, no UUIDs, no wall-clock or random values.
- Dict iteration is always sorted.
- Lines end with ``\\n``; the file ends with a single trailing ``\\n``.
- Floating-point values would use :func:`repr`, but the doc surface
  has no float-typed fields today.
"""

from __future__ import annotations

from typing import Any

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.nodes import (
    DocGuideDecl,
    DocRefDecl,
    EntityRefAst,
    ExampleEmbedToken,
    FilterExprAst,
    IterationAst,
    ReferenceToken,
    SectionAst,
    TextChunk,
)
from s0ma_dsl.codegen.doc_emitter.derived_sources import (
    DerivedFieldKind,
    DerivedRecordSet,
    records_for,
)
from s0ma_dsl.codegen.doc_emitter.frontmatter import (
    FrontmatterFields,
    render_markdown_frontmatter,
)
from s0ma_dsl.resolver.doc_resolver import ProjectIndex, _enum_to_str

__all__ = [
    "render_doc_ref_markdown",
    "render_doc_guide_markdown",
]


# ---------------------------------------------------------------------------
# Field formatting
# ---------------------------------------------------------------------------


def _format_field_value(value: Any) -> str:
    """Render an entity field value as a Markdown-safe string.

    Tuples / lists are rendered as comma-joined values; ``None`` is
    rendered as ``"—"`` so blank fields are visible rather than
    silently absent. Enums are flattened via :func:`_enum_to_str`
    (the same normalisation the resolver uses).
    """
    value = _enum_to_str(value)
    if value is None:
        return "—"
    if isinstance(value, (list, tuple)):
        if not value:
            return "—"
        rendered = [_format_field_value(v) for v in value]
        return ", ".join(rendered)
    if isinstance(value, dict):
        # Sort keys so two equivalent dicts always render the same.
        parts = [f"{k}: {_format_field_value(v)}"
                 for k, v in sorted(value.items())]
        return "; ".join(parts)
    return str(value)


def _heading(level: int, text: str) -> str:
    """Emit a Markdown heading line. Level is 1..6."""
    level = max(1, min(level, 6))
    return f"{'#' * level} {text}"


# ---------------------------------------------------------------------------
# Doc-ref rendering
# ---------------------------------------------------------------------------


def _resolve_filter(
    fexpr: FilterExprAst, index: ProjectIndex,
) -> list[Any]:
    """Return the entities a ``covers:`` filter selects, in deterministic order.

    Predicate evaluation is delegated to
    :func:`_predicate_matches`. Sorted by entity name so the rendered
    output is order-stable across runs.
    """
    entities = index.entities_of_kind(fexpr.kind)
    if fexpr.predicate is not None:
        entities = [e for e in entities if _predicate_matches(e.fields, fexpr.predicate)]
    if fexpr.ordered_by:
        entities = sorted(
            entities,
            key=lambda e: tuple(
                _ordering_key(e.fields.get(f)) for f in fexpr.ordered_by
            ),
        )
    else:
        entities = sorted(entities, key=lambda e: e.name)
    return entities


def _ordering_key(value: Any) -> Any:
    """Return a hashable key for ``ordered_by`` comparison.

    Lists / tuples are converted to tuples of strings so heterogeneous
    field shapes do not raise ``TypeError`` mid-sort. ``None`` sorts
    before anything else (we coerce to empty string).
    """
    value = _enum_to_str(value)
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return str(value)


def _predicate_matches(fields: dict[str, Any], pred: Any) -> bool:
    """Evaluate a structured predicate AST against an entity's fields.

    Mirrors the resolver's predicate semantics so renderer output stays
    consistent with what validation accepts. Booleans short-circuit;
    ``in`` membership is set-style on string-equal members.
    """
    from s0ma_dsl.ast_nodes.nodes import (
        BooleanPredicate,
        ComparisonPredicate,
    )

    if isinstance(pred, BooleanPredicate):
        if pred.operator == "and":
            return all(_predicate_matches(fields, o) for o in pred.operands)
        if pred.operator == "or":
            return any(_predicate_matches(fields, o) for o in pred.operands)
        if pred.operator == "not":
            return not _predicate_matches(fields, pred.operands[0])
        return False

    if isinstance(pred, ComparisonPredicate):
        lhs = pred.lhs
        # Asserts have an EntityRefAst; the doc-ref filter path uses a
        # tuple. We should not see EntityRefAst here, but be defensive —
        # degrade to a non-match rather than raising.
        if isinstance(lhs, tuple):  # noqa: SIM108 — comment clarifies the EntityRefAst case
            lookup_field = lhs[0] if lhs else ""
        else:
            lookup_field = ""
        actual = _enum_to_str(fields.get(lookup_field))
        rhs = pred.rhs
        if pred.operator == "==":
            return _scalar_equal(actual, rhs)
        if pred.operator == "!=":
            return not _scalar_equal(actual, rhs)
        if pred.operator == "in":
            if isinstance(rhs, tuple):
                return any(_scalar_equal(actual, item) for item in rhs)
            return _scalar_equal(actual, rhs)
        return False

    return False


def _scalar_equal(actual: Any, expected: Any) -> bool:
    """Compare two scalar-ish values stringily, matching the resolver."""
    if actual is None and expected is None:
        return True
    if isinstance(actual, (list, tuple)):
        return False  # lists never == scalars in v1
    return str(actual) == str(expected)


def _render_section_for_doc_ref(
    section: SectionAst,
    covered_kinds: tuple[str, ...],
    covers: tuple[FilterExprAst, ...],
    index: ProjectIndex,
) -> str:
    """Render a single ``sections:`` entry as a Markdown block.

    Bare field references are rendered as a sub-section per covered
    entity. Iterations evaluate their collection (must be a
    :class:`FilterExprAst` in v1 — see M2 handoff) and emit one block
    per matched entity.
    """
    if section.field_name is not None:
        # Iterate every covered entity across every covers: filter and
        # emit a small block per entity carrying the requested field.
        # Sort by (kind, name) so the order is stable across runs.
        rows: list[tuple[str, str, Any]] = []
        for fexpr in covers:
            for ent in _resolve_filter(fexpr, index):
                rows.append((ent.kind, ent.name, ent.fields.get(section.field_name)))
        rows.sort(key=lambda r: (r[0], r[1]))
        if not rows:
            return _heading(2, section.field_name) + "\n\n_None._\n"

        lines: list[str] = [_heading(2, section.field_name), ""]
        for kind, name, value in rows:
            lines.append(f"### {kind}::{name}")
            lines.append("")
            lines.append(_format_field_value(value))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    if section.iteration is not None:
        return _render_iteration(section.iteration, index)

    return ""


def _render_iteration(it: IterationAst, index: ProjectIndex) -> str:
    """Render a ``for <var> in <collection>`` block."""
    coll = it.collection
    if isinstance(coll, FilterExprAst):
        entities = _resolve_filter(coll, index)
    elif isinstance(coll, EntityRefAst):
        ent = index.lookup(coll.kind, coll.name)
        entities = [ent] if ent is not None else []
    else:
        entities = []

    if it.ordered_by:
        entities = sorted(
            entities,
            key=lambda e: tuple(
                _ordering_key(e.fields.get(f)) for f in it.ordered_by
            ),
        )

    title = it.raw or f"for {it.var}"
    lines: list[str] = [_heading(2, title), ""]

    if not entities:
        lines.append("_None._")
        return "\n".join(lines) + "\n"

    if it.group_by:
        groups: dict[str, list[Any]] = {}
        for ent in entities:
            key = str(_enum_to_str(ent.fields.get(it.group_by)) or "")
            groups.setdefault(key, []).append(ent)
        for group_value in sorted(groups):
            lines.append(_heading(3, f"{it.group_by}: {group_value}"))
            lines.append("")
            for ent in groups[group_value]:
                lines.extend(_render_entity_summary(ent))
                lines.append("")
    else:
        for ent in entities:
            lines.extend(_render_entity_summary(ent))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_entity_summary(entity: Any) -> list[str]:
    """Emit a small Markdown block summarising one entity."""
    lines = [f"#### {entity.kind}::{entity.name}"]
    intent = entity.fields.get("intent")
    if intent:
        lines.append("")
        lines.append(_format_field_value(intent))
    # DSL-M2 (0.8.0, ADR-011 §(e)): render the external test-evidence
    # claim after the intent when present — the audit trail behind the
    # release gate's covered_by credit, surfaced where readers look.
    covered_by = entity.fields.get("covered_by")
    if covered_by:
        lines.append("")
        lines.append(
            "Covered by: " + "; ".join(str(c) for c in covered_by)
        )
    return lines


@component(
    name="S0maDSL_render_doc_ref_markdown",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Render a doc-ref declaration as deterministic Markdown with a "
        "content-hash YAML front-matter."
    ),
    idempotent=True,
    is_framework=True,
)
def render_doc_ref_markdown(
    decl: DocRefDecl,
    *,
    index: ProjectIndex,
    content_hash: str,
    schema_version: str,
) -> str:
    """Render a :class:`DocRefDecl` as a complete Markdown document.

    Two body shapes:

    - **Component filter form** (``covers: [<kind> where ...]``): each
      ``sections:`` entry is rendered against the materialised filter
      results.
    - **Source-registry form** (``covers: { source: <name> }``): the
      declaration's records come from the derived-source registry
      (ADR-013) and render as a single Markdown table. ``sections:`` is
      optional for this shape and, when present, must be empty.
    """
    fields = FrontmatterFields(
        s0ma_kind="doc-ref",
        name=decl.name,
        module=decl.module_location,
        format=decl.format,
        intent=decl.intent,
        schema_version=schema_version,
        content_hash=content_hash,
    )
    body_parts: list[str] = [render_markdown_frontmatter(fields)]
    body_parts.append(_heading(1, decl.name) + "\n")
    body_parts.append(decl.intent + "\n")

    if decl.covers_source is not None:
        # ADR-013 §1: registry dispatch, not a per-source branch. The
        # literal ``== "error_codes"`` compare that used to live here was
        # the thing the ADR replaced — nine sources would have meant nine
        # branches in this file and two more in html.py / json_format.py,
        # where a missed branch renders an empty document in silence.
        # Adding a source now touches only the registry.
        body_parts.append(_render_records_table(records_for(
            decl.covers_source,
            doc_format="markdown",
            decl_name=decl.name,
        )))
    else:
        covered_kinds = tuple(f.kind for f in decl.covers)
        for section in decl.sections:
            body_parts.append(
                _render_section_for_doc_ref(section, covered_kinds, decl.covers, index)
            )

    return _join_blocks(body_parts)


# ---------------------------------------------------------------------------
# ADR-013: derived-source table renderer.
#
# One renderer for every registered source, driven by the record schema the
# provider declares. Columns come from the field labels; a cell's shape
# comes from its field kind (identifiers render in backticks, prose renders
# plain) and an absent value renders as an em-dash. Row order is the
# provider's declared sort key, verified before the records reach here.
#
# There is deliberately nothing source-specific in this function: that is
# the whole point of ADR-013 §1. Before it, the error-code table lived here
# as a hand-written branch, and the HTML and JSON renderers had no branch at
# all — so a derived doc-ref in either format emitted a heading, an intent,
# and no content, silently, in every strictness mode.
# ---------------------------------------------------------------------------


def _render_records_table(record_set: DerivedRecordSet) -> str:
    """Emit a Markdown table for one derived source's records.

    Determinism is inherited from the provider contract (ADR-013 §2):
    records arrive sorted by a declared key, field order is the declared
    schema order, and no value depends on wall-clock, locale, or dict
    iteration order.
    """
    headers = [f.label for f in record_set.fields]

    lines: list[str] = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")

    for row in record_set.records:
        cells = [
            _render_record_cell(value, field.kind)
            for field, value in zip(record_set.fields, row, strict=True)
        ]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"


def _render_record_cell(value: str | None, kind: DerivedFieldKind) -> str:
    """Render one record value as a Markdown table cell.

    ``None`` means *absent* — the provider never substitutes a display
    string — and reads as an em-dash so the column header stays
    meaningful and the row is visibly distinct.

    A vertical bar inside a value is escaped, for the reason
    ``s0ma_dsl.docs_model.inventories.cell`` escapes one: an unescaped bar
    ends the cell, so every column after it silently shifts left and the
    tail of the value disappears from the rendered table. It was really
    happening — ``METADATA_INVALID_VALUE``'s description names the shape
    set ``(quoted string | int | float | bool | list of strings)``, and
    the row rendered as five columns of nonsense with the sentence cut
    off. Escaping applies inside a backticked identifier too: a code span
    does not protect a bar from the table parser.

    The value is otherwise reproduced exactly. Collapsing whitespace here
    would be a second opinion about a provider's own record, and the
    provider contract (ADR-013 §2) already says a field value is one
    line.
    """
    if value is None:
        return "—"
    escaped = value.replace("|", "\\|")
    if kind is DerivedFieldKind.IDENTIFIER:
        return f"`{escaped}`"
    return escaped


# ---------------------------------------------------------------------------
# Doc-guide rendering
# ---------------------------------------------------------------------------


def _render_reference_token(
    tok: ReferenceToken, index: ProjectIndex,
) -> str:
    """Substitute a ``{{entity::name[.field]}}`` token with rendered text.

    For a bare entity reference (no ``field_path``) we emit the entity's
    intent so the surrounding prose still reads naturally. For a field
    reference we emit the field value via :func:`_format_field_value`.
    Unresolved references fall back to the raw ``{{...}}`` source so
    drift output is still legible — the resolver has already produced a
    diagnostic if it could not find the target.
    """
    ref = tok.entity_ref
    ent = index.lookup(ref.kind, ref.name)
    if ent is None:
        return tok.raw

    if not ref.field_path:
        intent = ent.fields.get("intent")
        if intent:
            return f"`{ref.kind}::{ref.name}` ({intent})"
        return f"`{ref.kind}::{ref.name}`"

    # Walk the field path; if a path segment fails to resolve, fall
    # back to the raw token so authors see something.
    cursor: Any = ent.fields.get(ref.field_path[0])
    for segment in ref.field_path[1:]:
        cursor = cursor.get(segment) if isinstance(cursor, dict) else None
        if cursor is None:
            break
    if cursor is None:
        return tok.raw
    return _format_field_value(cursor)


def _render_example_embed(
    tok: ExampleEmbedToken, index: ProjectIndex,
) -> str:
    """Substitute ``{{example::X}}`` with a fenced code block of the body.

    The example body is dedented to the column-0 form before being
    enclosed in a ``python`` fence: the parser preserves the source's
    leading whitespace verbatim, but a code fence with extra leading
    indentation reads as a quoted block in some Markdown processors.
    """
    ref = tok.entity_ref
    ent = index.lookup("example", ref.name)
    if ent is None or not hasattr(ent.decl, "python_body"):
        return tok.raw

    raw = (ent.decl.python_body or "").rstrip("\n")
    body = _strip_indent(raw, _common_leading_indent(raw))
    lines = ["```python", body, "```"]
    return "\n".join(lines)


@component(
    name="S0maDSL_render_doc_guide_markdown",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Render a doc-guide declaration as deterministic Markdown with a "
        "content-hash YAML front-matter."
    ),
    idempotent=True,
    is_framework=True,
)
def render_doc_guide_markdown(
    decl: DocGuideDecl,
    *,
    index: ProjectIndex,
    content_hash: str,
    schema_version: str,
) -> str:
    """Render a :class:`DocGuideDecl` as a complete Markdown document."""
    fields = FrontmatterFields(
        s0ma_kind="doc-guide",
        name=decl.name,
        module=decl.module_location,
        format=decl.format,
        intent=decl.intent,
        schema_version=schema_version,
        content_hash=content_hash,
    )

    # The .s0ma parser preserves the source's indentation in every
    # ``TextChunk.raw`` exactly. For Markdown output we strip the
    # common leading indent across the whole prose_body (computed once)
    # from each text chunk before substitution; reference and example
    # substitutions are inserted at column 0 because they live inside
    # ``{{...}}`` brackets the parser already treats as inline.
    indent = _common_leading_indent(decl.prose_body)
    parts: list[str] = []
    for token in decl.prose_tokens:
        if isinstance(token, TextChunk):
            parts.append(_strip_indent(token.raw, indent))
        elif isinstance(token, ExampleEmbedToken):
            parts.append(_render_example_embed(token, index))
        elif isinstance(token, ReferenceToken):
            parts.append(_render_reference_token(token, index))
        else:
            parts.append(getattr(token, "raw", ""))

    body = "".join(parts)
    if not body.endswith("\n"):
        body += "\n"

    return render_markdown_frontmatter(fields) + body


def _common_leading_indent(text: str) -> str:
    """Return the longest leading whitespace common to every non-blank line.

    Mirrors :func:`textwrap.dedent`'s indent-detection logic but is
    exposed as a helper so the renderer can apply the strip selectively
    (text chunks only, not substituted reference / example payloads).
    """
    lines = text.splitlines()
    indent: str | None = None
    for line in lines:
        if not line.strip():
            continue
        stripped = line.lstrip()
        leading = line[: len(line) - len(stripped)]
        if indent is None:
            indent = leading
        else:
            # Reduce ``indent`` to the common prefix of itself and ``leading``.
            common_len = 0
            for a, b in zip(indent, leading, strict=False):
                if a != b:
                    break
                common_len += 1
            indent = indent[:common_len]
            if not indent:
                break
    return indent or ""


def _strip_indent(text: str, indent: str) -> str:
    """Strip ``indent`` from the beginning of every line, preserving newlines."""
    if not indent:
        return text
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith(indent):
            out.append(line[len(indent):])
        else:
            out.append(line)
    return "".join(out)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _join_blocks(blocks: list[str]) -> str:
    """Join rendered blocks with blank-line separation; ensure trailing ``\\n``."""
    cleaned = [b.rstrip("\n") for b in blocks if b]
    joined = "\n\n".join(cleaned)
    if not joined.endswith("\n"):
        joined += "\n"
    return joined
