"""Build provisional doc registration records from AST declarations.

The s0ma-core M7 ``content_hash`` utility hashes a
:class:`DocRefRegistration` or :class:`DocGuideRegistration` directly,
so the transpiler must construct one *before* it knows the hash. We
build them with ``content_hash=""``; ``content_hash`` itself zeroes the
field as part of its canonicalisation step, so the placeholder survives
the round trip.

These helpers are independent of the runtime-bridge ``register_doc_*``
functions: they produce typed framework records, where the runtime
bridge produces dicts the import hook coerces. Both paths must agree
on the underlying typed shape — that is what makes the transpile-time
hash equal the post-import hash for the same registration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from s0ma.decorators import component
from s0ma.models import (
    AssertExpr,
    DocGuideRegistration,
    DocRefRegistration,
    EntityRef,
    ExampleRegistration,
    FilterExpr,
    Section,
    SourceSpan,
)
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.nodes import (
    AssertBoolean,
    AssertComparison,
    BooleanPredicate,
    ComparisonPredicate,
    DocGuideDecl,
    DocRefDecl,
    EntityRefAst,
    ExampleDecl,
    FilterExprAst,
    SectionAst,
    SourceLocation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from s0ma_dsl.codegen.doc_emitter.derived_sources import DerivedRecordSet

__all__ = [
    "build_doc_ref_registration",
    "build_doc_guide_registration",
    "build_example_registration",
]


def _span_for(filename: str, loc: SourceLocation | None) -> SourceSpan | None:
    if loc is None:
        return None
    return SourceSpan(
        file=filename,
        start_line=getattr(loc, "start_line", 0) or 0,
        end_line=getattr(loc, "end_line", 0) or 0,
    )


def _predicate_to_string(pred: Any) -> str | None:
    """Serialise a structured predicate AST to a deterministic string.

    Mirrors :func:`s0ma_dsl.codegen.python_emitter._predicate_to_string`
    so the registration the transpiler hashes equals the registration
    the runtime stores after coercion.
    """
    if pred is None:
        return None
    if isinstance(pred, BooleanPredicate):
        if pred.operator == "not" and len(pred.operands) == 1:
            return f"not ({_predicate_to_string(pred.operands[0])})"
        return f" {pred.operator} ".join(
            f"({_predicate_to_string(o)})" for o in pred.operands
        )
    if isinstance(pred, ComparisonPredicate):
        lhs = pred.lhs
        if isinstance(lhs, tuple):
            lhs_str = ".".join(lhs)
        elif isinstance(lhs, EntityRefAst):
            base = f"{lhs.kind}::{lhs.name}"
            if lhs.field_path:
                base += "." + ".".join(lhs.field_path)
            lhs_str = base
        else:
            lhs_str = str(lhs)
        rhs = pred.rhs
        if isinstance(rhs, tuple):
            rhs_str = "[" + ", ".join(repr(r) for r in rhs) + "]"
        else:
            rhs_str = str(rhs)
        return f"{lhs_str} {pred.operator} {rhs_str}"
    return None


def _filter_from_ast(fexpr: FilterExprAst) -> FilterExpr:
    return FilterExpr(
        target_kind=fexpr.kind,
        predicate=_predicate_to_string(fexpr.predicate),
        raw=fexpr.raw,
    )


def _section_from_ast(section: SectionAst) -> Section:
    """Map an AST :class:`SectionAst` to a framework :class:`Section`.

    Matches the shape :class:`PythonEmitter._emit_doc_ref` produces in
    its ``sections=[...]`` argument so the transpile-time and post-import
    canonicalisations agree.
    """
    if section.field_name is not None:
        return Section(
            title=section.field_name,
            iterate=None,
            group_by=None,
            render={"field": section.field_name},
        )

    it = section.iteration
    if it is None:
        return Section(title="", iterate=None, group_by=None, render={})

    coll = it.collection
    if isinstance(coll, FilterExprAst):
        coll_dict: dict[str, Any] = {
            "type": "filter",
            "value": {
                "target_kind": coll.kind,
                "predicate": _predicate_to_string(coll.predicate),
                "raw": coll.raw,
            },
        }
        coll_repr = coll.raw or coll.kind
    elif isinstance(coll, EntityRefAst):
        ref_value: dict[str, Any] = {"kind": coll.kind, "name": coll.name}
        if coll.field_path:
            ref_value["field_path"] = list(coll.field_path)
        coll_dict = {"type": "entity_ref", "value": ref_value}
        coll_repr = coll.raw or f"{coll.kind}::{coll.name}"
    else:
        coll_dict = {"type": "unknown", "value": None}
        coll_repr = ""

    return Section(
        title=f"for {it.var} in {coll_repr}",
        iterate=coll_repr,
        group_by=it.group_by,
        render={
            "iteration": {
                "var": it.var,
                "collection": coll_dict,
                "ordered_by": list(it.ordered_by),
                "group_by": it.group_by,
            },
        },
    )


def _entity_refs_from_ast(
    refs: tuple[EntityRefAst, ...], default_module: str
) -> list[EntityRef]:
    return [
        EntityRef(kind=r.kind, name=r.name, module=default_module)
        for r in refs
    ]


def _assert_expression(a: AssertComparison | AssertBoolean) -> str:
    """Serialise an assert AST to a deterministic single-line string.

    Mirrors :func:`s0ma_dsl.codegen.python_emitter._assert_to_string`.
    """
    if isinstance(a, AssertBoolean):
        if a.operator == "not" and len(a.operands) == 1:
            return f"not ({_assert_expression(a.operands[0])})"
        return f" {a.operator} ".join(
            f"({_assert_expression(o)})" for o in a.operands
        )
    if isinstance(a, AssertComparison):
        lhs = a.lhs
        base = f"{lhs.kind}::{lhs.name}"
        if lhs.field_path:
            base += "." + ".".join(lhs.field_path)
        rhs = a.rhs
        if isinstance(rhs, tuple):
            rhs_str = "[" + ", ".join(repr(r) for r in rhs) + "]"
        else:
            rhs_str = str(rhs)
        return f"{base} {a.operator} {rhs_str}"
    return ""


def _asserts_from_ast(
    asserts: tuple[AssertComparison | AssertBoolean, ...],
    filename: str,
    base_loc: SourceLocation | None,
) -> list[AssertExpr]:
    out: list[AssertExpr] = []
    for a in asserts:
        loc = getattr(a, "location", None) or base_loc
        span = _span_for(filename, loc) or SourceSpan(
            file=filename, start_line=0, end_line=0,
        )
        out.append(AssertExpr(
            expression=_assert_expression(a),
            source_span=span,
        ))
    return out


@component(
    name="S0maDSL_build_doc_ref_registration",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Construct a provisional DocRefRegistration from a DocRefDecl AST, "
        "with content_hash zeroed so content_hash() can compute the real "
        "transitive hash."
    ),
    idempotent=True,
    is_framework=True,
)
def build_doc_ref_registration(
    decl: DocRefDecl, *, filename: str = "",
) -> DocRefRegistration:
    """Build a typed :class:`DocRefRegistration` from a parsed AST decl.

    For the derived form (``covers: { source: <name> }``) the registration
    also carries the source name and the provider's own hash over its
    normalized records. Without them, a derived doc-ref's transitive hash
    was blind to what it renders: ``covers`` is empty for that shape, so
    the hashed snapshot was empty too, and the committed artifact's stamp
    moved when ``TRANSPILER_VERSION`` moved and not when the registry the
    table shows changed (ADR-013 §3b).
    """
    return DocRefRegistration(
        name=decl.name,
        module=decl.module_location,
        intent=decl.intent,
        format=decl.format,
        output=decl.output,
        covers=[_filter_from_ast(f) for f in decl.covers],
        sections=[_section_from_ast(s) for s in decl.sections],
        content_hash="",
        source_span=_span_for(filename, decl.location),
        covers_source=decl.covers_source,
        covers_source_hash=_derived_source_hash(decl.covers_source),
    )


def _derived_source_hash(source_name: str | None) -> str | None:
    """Return the registered provider's record hash for ``source_name``.

    ``None`` for the filter form, and ``None`` for a source the registry
    does not know — the parser refuses unregistered names, so reaching
    that branch means a synthesised declaration, and hashing is not the
    place to raise about it.

    ``None`` too for a source that describes a *checkout* (D6's
    ``needs_input``): its records exist only once a caller has handed it a
    root, and a registration is built during parsing, where no root is in
    hand. That is not the ADR-013 §3b hole reopening. The hole was a
    rendered artifact whose table could be rewritten under a stable hash;
    a checkout-scoped source cannot be rendered by a doc-ref at all until
    the renderer is given a way to pass an input, and until then
    :func:`~s0ma_dsl.codegen.doc_emitter.derived_sources.records_for`
    refuses it by name. There is no artifact here whose hash could go
    stale, which is why an absent hash is the honest answer rather than a
    silence.
    """
    if source_name is None:
        return None
    # Local import: ``registrations`` is imported by ``content_hashes``,
    # which the renderers' package init pulls in; importing the registry
    # at module scope would order those two against each other for no gain.
    from s0ma_dsl.codegen.doc_emitter.derived_sources import lookup_source

    source = lookup_source(source_name)
    if source is None or source.needs_input:
        return None
    provider = cast("Callable[[], DerivedRecordSet]", source.provider)
    return provider().content_hash


@component(
    name="S0maDSL_build_doc_guide_registration",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Construct a provisional DocGuideRegistration from a DocGuideDecl "
        "AST, with content_hash zeroed so content_hash() can compute the "
        "real transitive hash."
    ),
    idempotent=True,
    is_framework=True,
)
def build_doc_guide_registration(
    decl: DocGuideDecl, *, filename: str = "",
) -> DocGuideRegistration:
    """Build a typed :class:`DocGuideRegistration` from a parsed AST decl."""
    default_module = decl.module_location
    return DocGuideRegistration(
        name=decl.name,
        module=decl.module_location,
        intent=decl.intent,
        format=decl.format,
        output=decl.output,
        covers=_entity_refs_from_ast(decl.covers, default_module),
        asserts=_asserts_from_ast(decl.asserts, filename, decl.location),
        examples=_entity_refs_from_ast(decl.examples, default_module),
        body=decl.prose_body,
        content_hash="",
        source_span=_span_for(filename, decl.location),
    )


@component(
    name="S0maDSL_build_example_registration",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Construct a typed ExampleRegistration from an ExampleDecl AST so "
        "examples can participate in doc-guide content hashes."
    ),
    idempotent=True,
    is_framework=True,
)
def build_example_registration(
    decl: ExampleDecl, *, filename: str = "",
) -> ExampleRegistration:
    """Build a typed :class:`ExampleRegistration` from a parsed AST decl."""
    runs_in: Any = decl.runs_in if decl.runs_in in {
        "standalone", "pytest", "integration",
    } else "standalone"
    return ExampleRegistration(
        name=decl.name,
        module=decl.module_location,
        intent=decl.intent,
        demonstrates=_entity_refs_from_ast(
            decl.demonstrates, decl.module_location,
        ),
        runs_in=runs_in,
        body=decl.python_body or "",
        source_span=_span_for(filename, decl.location),
    )
