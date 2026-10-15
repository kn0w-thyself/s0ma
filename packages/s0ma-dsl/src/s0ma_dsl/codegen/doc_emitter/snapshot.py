"""Synthesise a :class:`s0ma.RegistrySnapshot` from parsed AST modules.

The s0ma-core M7 ``content_hash`` utility walks a registry snapshot to
compute a transitive content hash over the entities a doc-ref or
doc-guide references. At transpile time the live registry is empty —
the ``.s0ma`` files have not been imported yet — so the transpiler
constructs an equivalent snapshot directly from the parsed AST.

The synthesised snapshot must cover every store ``content_hash`` reads:

* ``components`` — every nerve, cell, ganglion (plus tests as a
  side-channel) is registered as a :class:`ComponentSpec`. The ``kind``
  is the **DSL kind string** (``"nerve"``, ``"cell"``, ``"ganglion"``)
  rather than a :class:`ComponentKind` enum so the
  ``_resolve_by_component_kind`` walker can match doc-ref filters of
  the form ``covers: [nerve where ...]``. ``ComponentSpec``'s
  ``__post_init__`` validates ``intent`` length but does not type-check
  ``kind``; that gives us room to use the DSL nomenclature without
  forking the framework.
* ``modules`` — :class:`ModuleMetadata` for every parsed module, keyed
  by module name.
* ``examples`` — :class:`ExampleRegistration` for every ``example``
  declaration. The example body (verbatim) participates in the
  doc-guide hash so editing an example body invalidates every guide
  that embeds it.
* ``doc_refs`` / ``doc_guides`` — empty at transpile time; populated
  later when the doc registrations themselves are built.

PRD references: §2.7 (registry expansion), §8.5 (content hashes).
"""

from __future__ import annotations

from typing import Any

from s0ma.decorators import component
from s0ma.models import (
    ComponentSpec,
    Contract,
    EntityRef,
    ExampleRegistration,
    ModuleMetadata,
    RegistrySnapshot,
    SourceSpan,
)
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.nodes import (
    CellDecl,
    ExampleDecl,
    GanglionDecl,
    NerveDecl,
    S0maModule,
    TestDecl,
)

__all__ = [
    "build_content_hash_snapshot",
]


# Mapping from DSL declaration class to the singular kind string the
# doc-resolver and content-hash walker both use. Standalone axons and
# doc declarations are intentionally excluded — they are not entity
# references in v1 (per the M4 ProjectIndex).
_DECL_KIND: dict[type, str] = {
    NerveDecl: "nerve",
    CellDecl: "cell",
    GanglionDecl: "ganglion",
    TestDecl: "test",
}


def _layer_for(decl_layer: Any) -> Layer:
    """Convert a DSL :class:`s0ma_dsl.ast_nodes.enums.Layer` into a
    framework :class:`s0ma.types.Layer`.

    The DSL Layer enum's ``.value`` matches the framework Layer enum's
    member name (both use ``DOMAIN`` / ``APPLICATION`` / ... / ``FRAMEWORK``),
    so the conversion is a name-based lookup.
    """
    if decl_layer is None:
        return Layer.DOMAIN
    name = getattr(decl_layer, "value", str(decl_layer))
    try:
        return Layer[name]
    except KeyError:
        return Layer.DOMAIN


def _safe_intent(text: str | None) -> str:
    """Return an intent string ≥ 10 chars (the ComponentSpec minimum).

    Pads obviously-short or missing intents with the AST's "intent
    placeholder" sentinel. Real DSL declarations always carry a >= 10
    char intent because the parser enforces it; this fallback only
    fires for synthetic test-side fixtures the resolver might feed in.
    """
    if text and len(text) >= 10:
        return text
    return f"{text or '(no intent)'} (synthesised for content-hash snapshot)"


def _build_component_spec(
    *,
    name: str,
    kind: str,
    layer: Layer,
    intent: str,
    module_path: str,
    version: str = "0.1.0",
) -> ComponentSpec:
    """Construct a :class:`ComponentSpec` whose ``kind`` is a plain string.

    ``ComponentSpec`` is annotated as ``kind: ComponentKind``, but the
    dataclass does not type-check the field. We exploit that to use the
    DSL kind nomenclature (``"nerve"``, ``"cell"``, ``"ganglion"``) so
    that ``content_hash``'s ``_resolve_by_component_kind`` matches
    ``covers: [nerve where ...]`` filters. Mismatching the DSL filter
    surface with the framework's narrower ComponentKind would otherwise
    produce hashes that ignore every nerve-level change.
    """
    spec = ComponentSpec(
        name=name,
        kind=ComponentKind.SERVICE,  # placeholder; overwritten below
        layer=layer,
        intent=_safe_intent(intent),
        contracts=Contract(),
        version=version,
        module_path=module_path,
        qualified_name=f"{module_path}.{name}" if module_path else name,
    )
    # ``ComponentSpec`` is a non-frozen dataclass — overwrite ``kind``
    # post-construction so we keep the DSL nomenclature without
    # tripping ``__post_init__`` (which only runs once).
    spec.kind = kind  # type: ignore[assignment]
    return spec


def _component_specs_from_module(
    module: S0maModule,
) -> list[ComponentSpec]:
    """Extract a :class:`ComponentSpec` per addressable AST declaration."""
    specs: list[ComponentSpec] = []
    module_path = module.module.name
    layer = _layer_for(module.module.layer)

    for decl in module.all_declarations:
        kind_str = _DECL_KIND.get(type(decl))
        if kind_str is None:
            continue
        # tests aren't surfaced in covers: filters today, but include
        # them so the hash captures test additions/removals — content
        # changes that should drift downstream guides referencing the
        # test entity directly.
        specs.append(_build_component_spec(
            # Only Nerve/Cell/Ganglion/Test reach here (the _DECL_KIND
            # guard above skips name-less decls like StandaloneAxonDecl);
            # getattr mirrors the intent/version access just below.
            name=getattr(decl, "name", ""),
            kind=kind_str,
            layer=layer,
            intent=getattr(decl, "intent", "") or "",
            module_path=module_path,
            version=getattr(module.module, "version", "") or "0.1.0",
        ))
    return specs


def _module_metadata(module: S0maModule) -> ModuleMetadata:
    """Build a :class:`ModuleMetadata` record from a parsed module."""
    mod = module.module
    return ModuleMetadata(
        name=mod.name,
        layer=getattr(mod.layer, "value", str(mod.layer)),
        version=mod.version,
        intent=mod.intent,
        exports=list(mod.exports),
        content_hash="",
        tags=list(getattr(mod, "tags", ()) or ()),
    )


def _example_registration(
    decl: ExampleDecl, module_name: str
) -> ExampleRegistration:
    """Build a :class:`ExampleRegistration` from an ``example`` decl.

    The body is stored verbatim (after dedenting in the renderer's
    pipeline); for hash purposes we want byte-stability so we pass the
    AST's ``python_body`` directly. Source spans are populated from the
    declaration's ``location``.
    """
    span = _source_span(module_name, decl)
    runs_in: Any = decl.runs_in if decl.runs_in in {
        "standalone", "pytest", "integration"
    } else "standalone"
    return ExampleRegistration(
        name=decl.name,
        module=module_name,
        intent=decl.intent,
        demonstrates=[
            EntityRef(kind=r.kind, name=r.name, module=module_name)
            for r in decl.demonstrates
        ],
        runs_in=runs_in,
        body=decl.python_body or "",
        source_span=span,
    )


def _source_span(module_name: str, decl: Any) -> SourceSpan:
    loc = getattr(decl, "location", None)
    if loc is None:
        return SourceSpan(file=module_name, start_line=0, end_line=0)
    return SourceSpan(
        file=module_name,
        start_line=getattr(loc, "start_line", 0) or 0,
        end_line=getattr(loc, "end_line", 0) or 0,
    )


@component(
    name="S0maDSL_build_content_hash_snapshot",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Synthesise a s0ma RegistrySnapshot from parsed AST modules so the "
        "framework's content_hash utility can compute transitive doc hashes "
        "at transpile time, before the .s0ma sources are imported."
    ),
    idempotent=True,
    is_framework=True,
)
def build_content_hash_snapshot(
    modules: dict[str, S0maModule],
) -> RegistrySnapshot:
    """Construct a snapshot covering every entity a doc reference may reach.

    The snapshot is intentionally *content*-faithful, not
    *behaviourally*-faithful: it carries the metadata fields
    ``content_hash`` reads (``name``, ``kind``, ``layer``, ``intent``,
    ``version``, ``module_path``, ``qualified_name``, ``is_framework``,
    plus example bodies and module metadata) and nothing more. The
    runtime never imports it; it lives for the duration of one
    ``content_hash`` call and is discarded.
    """
    components: dict[str, ComponentSpec] = {}
    layers: dict[str, list[str]] = {}
    module_meta: dict[str, ModuleMetadata] = {}
    examples: dict[str, ExampleRegistration] = {}

    for module_name in sorted(modules.keys()):
        module = modules[module_name]
        module_meta[module_name] = _module_metadata(module)

        for spec in _component_specs_from_module(module):
            components[spec.name] = spec
            layer_name = spec.layer.name if hasattr(spec.layer, "name") else str(spec.layer)
            layers.setdefault(layer_name, []).append(spec.name)

        for decl in module.all_declarations:
            if isinstance(decl, ExampleDecl):
                ex = _example_registration(decl, module_name)
                examples[ex.name] = ex

    # Sort the per-layer name lists for determinism.
    layers = {layer: sorted(names) for layer, names in sorted(layers.items())}

    return RegistrySnapshot(
        components=components,
        component_count=len(components),
        framework_component_count=0,
        layers=layers,
        dependency_graph={},
        modules=module_meta,
        examples=examples,
    )
