"""Deterministic JSON renderer for doc-ref and doc-guide declarations.

JSON is the cheapest format to make byte-deterministic: pass
``sort_keys=True`` and a fixed ``indent`` to :func:`json.dumps` and the
output is reproducible across runs and Python versions. We still
follow the front-matter contract — the ``content_hash`` lives at the
top-level ``_hash`` key and the rest of the meta block at ``_meta``.

Per design §11.6 / plan §M6: the JSON output is the canonical
machine-readable form of a rendered doc. AI tooling and registries
ingest it directly without re-parsing the Markdown / HTML siblings.
"""

from __future__ import annotations

import json
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
)
from s0ma_dsl.codegen.doc_emitter.derived_sources import records_for
from s0ma_dsl.codegen.doc_emitter.frontmatter import (
    FrontmatterFields,
    json_frontmatter_dict,
)
from s0ma_dsl.codegen.doc_emitter.markdown import (
    _resolve_filter,
)
from s0ma_dsl.resolver.doc_resolver import ProjectIndex, _enum_to_str

__all__ = [
    "render_doc_ref_json",
    "render_doc_guide_json",
]


def _entity_to_dict(entity: Any) -> dict[str, Any]:
    """Serialise an indexed entity to a JSON-safe dict.

    Only the addressable fields are emitted (the same allow-list the
    resolver enforces) so consumer schemas stay narrow and stable.
    """
    return {
        "kind": entity.kind,
        "name": entity.name,
        "module": entity.module_name,
        "fields": {
            k: _normalise(entity.fields.get(k))
            for k in sorted(entity.fields.keys())
        },
    }


def _normalise(value: Any) -> Any:
    """Recursively flatten enums and tuples for JSON-safe output."""
    value = _enum_to_str(value)
    if isinstance(value, tuple):
        return [_normalise(v) for v in value]
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in sorted(value.items())}
    return value


def _section_to_json(
    section: SectionAst,
    covers: tuple[FilterExprAst, ...],
    index: ProjectIndex,
) -> dict[str, Any]:
    if section.field_name is not None:
        rows: list[dict[str, Any]] = []
        for fexpr in covers:
            for ent in _resolve_filter(fexpr, index):
                rows.append({
                    "kind": ent.kind,
                    "name": ent.name,
                    "value": _normalise(ent.fields.get(section.field_name)),
                })
        rows.sort(key=lambda r: (r["kind"], r["name"]))
        return {
            "type": "field",
            "field": section.field_name,
            "entries": rows,
        }
    if section.iteration is not None:
        return _iteration_to_json(section.iteration, index)
    return {"type": "empty"}


def _iteration_to_json(
    it: IterationAst, index: ProjectIndex,
) -> dict[str, Any]:
    coll = it.collection
    if isinstance(coll, FilterExprAst):
        entities = _resolve_filter(coll, index)
        coll_dict: dict[str, Any] = {
            "type": "filter",
            "kind": coll.kind,
            "predicate_raw": coll.raw,
        }
    elif isinstance(coll, EntityRefAst):
        ent = index.lookup(coll.kind, coll.name)
        entities = [ent] if ent is not None else []
        coll_dict = {
            "type": "entity_ref",
            "kind": coll.kind,
            "name": coll.name,
        }
    else:
        entities = []
        coll_dict = {"type": "unknown"}

    return {
        "type": "iteration",
        "var": it.var,
        "collection": coll_dict,
        "ordered_by": list(it.ordered_by),
        "group_by": it.group_by,
        "entities": [_entity_to_dict(e) for e in entities],
    }


@component(
    name="S0maDSL_render_doc_ref_json",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Render a doc-ref declaration as a deterministic JSON document with "
        "a top-level _hash field and per-section structured payload."
    ),
    idempotent=True,
    is_framework=True,
)
def render_doc_ref_json(
    decl: DocRefDecl,
    *,
    index: ProjectIndex,
    content_hash: str,
    schema_version: str,
) -> str:
    """Render a :class:`DocRefDecl` as JSON."""
    fields = FrontmatterFields(
        s0ma_kind="doc-ref",
        name=decl.name,
        module=decl.module_location,
        format=decl.format,
        intent=decl.intent,
        schema_version=schema_version,
        content_hash=content_hash,
    )
    payload: dict[str, Any] = json_frontmatter_dict(fields)
    payload["covers"] = [
        {
            "target_kind": f.kind,
            "predicate_raw": f.raw,
            "ordered_by": list(f.ordered_by),
            "group_by": f.group_by,
        }
        for f in decl.covers
    ]
    # G7a (feedback 5–6 cleanup): the discriminator round-trips through
    # the JSON output too. The field is omitted entirely when the
    # declaration uses the historic list-of-filters form so existing
    # fixtures (and their content hashes) stay byte-stable; consumers of
    # the new form see ``"covers_source": "<name>"`` alongside an empty
    # ``"covers"`` array.
    #
    # ADR-013 §4: the brace form no longer falls through to the
    # ``sections:`` path. Until this landed, a ``format: json`` doc-ref
    # over a derived source emitted the source *name* and then rendered
    # zero sections — a document with a heading, an intent, and no
    # content, in every strictness mode. It now carries the records and
    # their provenance.
    if decl.covers_source is not None:
        payload["covers_source"] = decl.covers_source
        payload["source"] = _derived_source_to_json(
            decl.covers_source, decl_name=decl.name,
        )
        payload["sections"] = []
    else:
        payload["sections"] = [
            _section_to_json(section, decl.covers, index)
            for section in decl.sections
        ]

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _derived_source_to_json(
    source_name: str, *, decl_name: str,
) -> dict[str, Any]:
    """Serialise a derived source's records and ADR-013 §3 provenance.

    The record-schema version is keyed ``record_schema_version``, never
    ``schema_version``: the payload already carries a top-level
    ``schema_version`` meaning the *IR* schema, and ADR-013 §3a forbids
    conflating the two in a rendered artifact. ``records`` are name-keyed
    objects (rather than the provider's positional rows) so a consumer
    reading the JSON never has to zip against ``fields`` to know what a
    value means.
    """
    record_set = records_for(
        source_name, doc_format="json", decl_name=decl_name,
    )
    return {
        "name": source_name,
        "provider_id": record_set.provider_id,
        "source_identity": record_set.source_identity,
        "record_schema_version": record_set.schema_version,
        "content_hash": record_set.content_hash,
        "sort_key": record_set.sort_key,
        "fields": [
            {"name": f.name, "label": f.label, "kind": f.kind.value}
            for f in record_set.fields
        ],
        "records": [dict(row) for row in record_set.as_mappings()],
    }


@component(
    name="S0maDSL_render_doc_guide_json",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Render a doc-guide declaration as a deterministic JSON document with "
        "the prose body and reference resolution payload."
    ),
    idempotent=True,
    is_framework=True,
)
def render_doc_guide_json(
    decl: DocGuideDecl,
    *,
    index: ProjectIndex,
    content_hash: str,
    schema_version: str,
) -> str:
    """Render a :class:`DocGuideDecl` as JSON."""
    fields = FrontmatterFields(
        s0ma_kind="doc-guide",
        name=decl.name,
        module=decl.module_location,
        format=decl.format,
        intent=decl.intent,
        schema_version=schema_version,
        content_hash=content_hash,
    )
    payload: dict[str, Any] = json_frontmatter_dict(fields)
    payload["covers"] = [
        {"kind": r.kind, "name": r.name, "field_path": list(r.field_path)}
        for r in decl.covers
    ]
    payload["examples"] = [
        {"kind": r.kind, "name": r.name}
        for r in decl.examples
    ]
    payload["asserts"] = [
        {"raw": getattr(a, "raw", "")}
        for a in decl.asserts
    ]
    payload["body"] = decl.prose_body
    payload["resolved_references"] = [
        {
            "kind": tok.entity_ref.kind,
            "name": tok.entity_ref.name,
            "field_path": list(tok.entity_ref.field_path),
            "raw": tok.raw,
            "embed": isinstance(tok, ExampleEmbedToken),
        }
        for tok in decl.prose_tokens
        if isinstance(tok, (ReferenceToken, ExampleEmbedToken))
    ]
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
