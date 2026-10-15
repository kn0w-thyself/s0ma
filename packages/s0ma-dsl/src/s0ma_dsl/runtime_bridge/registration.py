"""Runtime registration functions for transpiled .s0ma modules.

This module provides the registration functions that transpiled Python code
calls at module load time. Each function is a thin adapter that delegates
to the s0ma framework's ComponentRegistry, converting DSL-level concepts
(modules, constants, types, relationships, tests) into the registry's
expanded storage.

The emitter imports these functions in every generated module::

    from s0ma_dsl.runtime_bridge.registration import register_module, ...

Functions accept ``s0ma.types.Layer`` enum values (as emitted by the
code generator) and convert them to the string form expected by the
registry's expanded API.

M6b (feedback 5–6, ADR-007): the runtime bridge also exposes
:func:`import_modules_from_manifest`, a manifest-driven entry point that
reads ``build.s0ma.json`` from a build directory and imports each
listed module in the order the manifest records. The manifest is the
canonical "what's in this build" answer — filesystem walking is *not*
a fallback. A missing or schema-mismatched manifest raises
:class:`s0ma.bootstrap.ManifestSchemaError` (re-exported as
``s0ma_dsl.codegen.build_manifest.ManifestSchemaError``) with a
remediation pointing at ``s0ma build`` or ``s0ma migrate-layout``. M10
will extend the manifest with ``topological_import_order`` and this
function will honour that order automatically.

PRD references: §2.7.1 (new registration functions), §2.7.2 (registry
schema expansion), §2.2 (declaration behavior).
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma.decorators import component
from s0ma.models import (
    AssertExpr,
    Contract,
    EntityRef,
    FilterExpr,
    Section,
    SourceSpan,
)
from s0ma.registry import get_registry
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from types import ModuleType

    from s0ma.models import (
        DocGuideRegistration,
        DocRefRegistration,
        ExampleRegistration,
        ModuleMetadata,
        RelationshipEdge,
        TestRegistration,
    )
    from s0ma.registry import ComponentRegistry

__all__ = [
    "import_modules_from_manifest",
    "register_constant",
    "register_doc_guide",
    "register_doc_ref",
    "register_example",
    "register_integration_helper",
    "register_module",
    "register_relationship",
    "register_test",
    "register_type",
]


def _get_registry() -> ComponentRegistry:
    """Get the global registry, creating it without persistence if needed.

    Transpiled modules run in the user's project context, not s0ma's
    own bootstrap. Persistence is disabled by default to avoid creating
    ``.s0ma/`` directories in arbitrary project trees.
    """
    return get_registry(persist=False)


@component(
    name="S0maDSL_register_module",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Register module-level metadata for a transpiled .s0ma module. "
        "Converts Layer enum to string and delegates to the registry."
    ),
    contracts=Contract(
        preconditions=[
            "name is a non-empty string",
            "layer is a valid Layer enum member",
            "version is a valid semver string",
            "intent is a non-empty string",
        ],
        postconditions=["Module metadata is stored in the registry and retrievable by name"],
        input_type=(
            "name: str, layer: Layer, version: str, intent: str, "
            "exports: list[str] | None, tags: list[str] | None"
        ),
        output_type="ModuleMetadata",
    ),
    dependencies=["ModuleMetadata"],
    is_framework=True,
    idempotent=True,
)
def register_module(
    *,
    name: str,
    layer: Layer,
    version: str,
    intent: str,
    exports: list[str] | None = None,
    tags: list[str] | None = None,
) -> ModuleMetadata:
    """Register module-level metadata in the s0ma registry.

    Called once per transpiled module at load time.

    Parameters
    ----------
    name:
        Module canonical name (e.g., ``signal_processor``).
    layer:
        Architectural layer (``Layer.DOMAIN``, etc.).
    version:
        Semantic version string.
    intent:
        Human-readable purpose statement.
    exports:
        List of exported component names.
    tags:
        Optional classification tags.

    Returns
    -------
    ModuleMetadata
        The stored module metadata.
    """
    registry = _get_registry()
    return registry.register_module(
        name=name,
        layer=layer.name,
        version=version,
        intent=intent,
        exports=exports,
        tags=tags,
    )


@component(
    name="S0maDSL_register_constant",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Register a CONSTANT cell as a component in the s0ma registry. "
        "Constants cannot use the @component decorator directly."
    ),
    contracts=Contract(
        preconditions=[
            "name is a non-empty string",
            "layer is a valid Layer enum member",
            "intent is a non-empty string",
        ],
        postconditions=[
            "Constant is registered as a component with kind CONSTANT and correct layer",
        ],
        input_type=(
            "name: str, layer: Layer, intent: str, "
            "metadata: dict[str, Any] | None, module_path: str | None"
        ),
        output_type="None",
    ),
    is_framework=True,
    idempotent=True,
)
def register_constant(
    *,
    name: str,
    layer: Layer,
    intent: str,
    metadata: dict[str, Any] | None = None,
    module_path: str | None = None,
) -> None:
    """Register a CONSTANT cell as a component.

    Parameters
    ----------
    name:
        The constant's name.
    layer:
        Architectural layer.
    intent:
        Human-readable purpose statement.
    metadata:
        Additional DSL metadata (visibility, schema, etc.).
    module_path:
        Owning module's canonical name (added 0.14.0 / PRE-8). The
        emitter passes the transpiler's ``self.module_name`` so the
        registry can attribute the constant to its module the same
        way ``register_module`` and ``@component`` do. ``None`` is
        the back-compat default — older transpiled ``.py`` files
        continue to work unchanged.
    """
    registry = _get_registry()
    kwargs: dict[str, Any] = {
        "name": name,
        "layer": layer.name,
        "intent": intent,
        "metadata": metadata,
    }
    # Forward ``module_path`` only when both the caller supplied it
    # *and* the framework's registry signature accepts it. The
    # introspection guard means the bridge keeps working against
    # pre-0.3.0 builds of s0ma-core (then distributed as
    # ``s0ma-framework``) where ``register_constant`` has no
    # ``module_path`` parameter — older frameworks just lose
    # the attribution, but no crash.
    if module_path is not None and "module_path" in inspect.signature(
        registry.register_constant
    ).parameters:
        kwargs["module_path"] = module_path
    registry.register_constant(**kwargs)


@component(
    name="S0maDSL_register_type",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Register a TYPE cell as a component in the s0ma registry. "
        "Type aliases cannot use the @component decorator directly."
    ),
    contracts=Contract(
        preconditions=[
            "name is a non-empty string",
            "layer is a valid Layer enum member",
            "intent is a non-empty string",
        ],
        postconditions=["Type alias is registered as a component with kind TYPE and correct layer"],
        input_type=(
            "name: str, layer: Layer, intent: str, "
            "metadata: dict[str, Any] | None, module_path: str | None"
        ),
        output_type="None",
    ),
    is_framework=True,
    idempotent=True,
)
def register_type(
    *,
    name: str,
    layer: Layer,
    intent: str,
    metadata: dict[str, Any] | None = None,
    module_path: str | None = None,
) -> None:
    """Register a TYPE cell as a component.

    Parameters
    ----------
    name:
        The type alias name.
    layer:
        Architectural layer.
    intent:
        Human-readable purpose statement.
    metadata:
        Additional DSL metadata (visibility, schema, etc.).
    module_path:
        Owning module's canonical name (added 0.14.0 / PRE-8). See
        :func:`register_constant` for the back-compat semantics.
    """
    registry = _get_registry()
    kwargs: dict[str, Any] = {
        "name": name,
        "layer": layer.name,
        "intent": intent,
        "metadata": metadata,
    }
    if module_path is not None and "module_path" in inspect.signature(
        registry.register_type
    ).parameters:
        kwargs["module_path"] = module_path
    registry.register_type(**kwargs)


@component(
    name="S0maDSL_register_relationship",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Register a dependency relationship between two components. "
        "Called for standalone axon declarations in transpiled output."
    ),
    contracts=Contract(
        preconditions=[
            "source is a valid canonical ID (module::component)",
            "target is a valid canonical ID (module::component)",
            "relation is a valid relation type string "
            "(CALLS, READS, CONSTRUCTS, CONFIGURES, RAISES, TYPE_USES)",
        ],
        postconditions=[
            "Relationship edge is stored in the registry linking source to target",
        ],
        input_type=(
            "source: str, target: str, relation: str, intent: str, "
            "carries: str, coupling: str"
        ),
        output_type="RelationshipEdge",
    ),
    dependencies=["RelationshipEdge"],
    is_framework=True,
    idempotent=True,
)
def register_relationship(
    *,
    source: str,
    target: str,
    relation: str,
    intent: str = "",
    carries: str = "",
    coupling: str = "",
) -> RelationshipEdge:
    """Register a dependency relationship between two components.

    Parameters
    ----------
    source:
        Canonical ID of the source component (``module::name``).
    target:
        Canonical ID of the target component.
    relation:
        Relationship type (``CALLS``, ``READS``, ``RAISES``, etc.).
    intent:
        Human-readable description.
    carries:
        Data type carried across the edge.
    coupling:
        Coupling strength (``TIGHT`` or ``LOOSE``).

    Returns
    -------
    RelationshipEdge
        The stored relationship edge.
    """
    registry = _get_registry()
    return registry.register_relationship(
        source=source,
        target=target,
        relation=relation,
        intent=intent,
        carries=carries,
        coupling=coupling,
        origin="authored",
    )


@component(
    name="S0maDSL_register_test",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Register a test declaration with its validated component links. "
        "Called for test declarations in transpiled output."
    ),
    contracts=Contract(
        preconditions=[
            "name is a valid canonical test ID (module::test_name)",
            "intent is a non-empty string",
        ],
        postconditions=[
            "Test declaration is registered with validated links to the components it covers",
        ],
        input_type="name: str, intent: str, validates: list[str] | None",
        output_type="TestRegistration",
    ),
    dependencies=["TestRegistration"],
    is_framework=True,
    idempotent=True,
)
def register_test(
    *,
    name: str,
    intent: str,
    validates: list[str] | None = None,
) -> TestRegistration:
    """Register a test declaration in the s0ma registry.

    Parameters
    ----------
    name:
        Canonical test ID (``module::test_name``).
    intent:
        Human-readable purpose statement.
    validates:
        List of canonical component IDs this test validates.

    Returns
    -------
    TestRegistration
        The stored test registration.
    """
    registry = _get_registry()
    return registry.register_test(
        name=name,
        intent=intent,
        validates=validates,
    )


# ---------------------------------------------------------------------------
# Documentation subsystem registration adapters (plan M5)
# ---------------------------------------------------------------------------
#
# Transpiled `.py` modules emitted from `doc-ref`, `doc-guide`, and `example`
# declarations call these adapters at import time. Each adapter accepts the
# DSL-side primitive form (plain dicts / strings) the emitter prefers to
# serialise and constructs the s0ma-side typed records (``EntityRef``,
# ``FilterExpr``, ``Section``, ``AssertExpr``, ``SourceSpan``) before
# delegating to the framework registry.


def _coerce_entity_refs(
    refs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> list[EntityRef]:
    if not refs:
        return []
    return [
        EntityRef(
            kind=str(r["kind"]),
            name=str(r["name"]),
            module=r.get("module"),
        )
        for r in refs
    ]


def _coerce_filter_exprs(
    exprs: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> list[FilterExpr]:
    if not exprs:
        return []
    return [
        FilterExpr(
            target_kind=str(f["target_kind"]),
            predicate=f.get("predicate"),
            raw=str(f.get("raw", "")),
        )
        for f in exprs
    ]


def _coerce_sections(
    sections: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> list[Section]:
    if not sections:
        return []
    return [
        Section(
            title=str(s["title"]),
            iterate=s.get("iterate"),
            group_by=s.get("group_by"),
            render=dict(s.get("render", {})),
        )
        for s in sections
    ]


def _coerce_source_span(span: dict[str, Any] | None) -> SourceSpan | None:
    if span is None:
        return None
    return SourceSpan(
        file=str(span["file"]),
        start_line=int(span["start_line"]),
        end_line=int(span["end_line"]),
    )


def _coerce_asserts(
    items: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> list[AssertExpr]:
    if not items:
        return []
    out: list[AssertExpr] = []
    for a in items:
        span = _coerce_source_span(a["source_span"])
        # SourceSpan is mandatory on AssertExpr; fall back to a synthetic
        # span anchored at line 0 if the emitter omitted one (defensive).
        if span is None:
            span = SourceSpan(file="", start_line=0, end_line=0)
        out.append(AssertExpr(expression=str(a["expression"]), source_span=span))
    return out


@component(
    name="S0maDSL_register_doc_ref",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Register a doc-ref declaration in the s0ma registry. "
        "Coerces DSL-side primitive payloads into typed FilterExpr / "
        "Section / SourceSpan records and delegates to the framework."
    ),
    contracts=Contract(
        preconditions=[
            "name, module, intent are non-empty strings",
            "format is one of markdown / html / json",
            "output is a relative path",
        ],
        postconditions=[
            "Doc-ref registration is stored in the registry and retrievable by name",
        ],
        input_type=(
            "name: str, module: str, intent: str, format: str, output: str, "
            "covers: list[dict[str, Any]] | None, "
            "sections: list[dict[str, Any]] | None, content_hash: str, "
            "source_span: dict[str, Any] | None"
        ),
        output_type="DocRefRegistration",
    ),
    dependencies=["DocRefRegistration"],
    is_framework=True,
    idempotent=True,
)
def register_doc_ref(
    *,
    name: str,
    module: str,
    intent: str,
    format: str,  # noqa: A002 — field name mandated by design §6 / plan M2
    output: str,
    covers: list[dict[str, Any]] | None = None,
    sections: list[dict[str, Any]] | None = None,
    content_hash: str = "",
    source_span: dict[str, Any] | None = None,
) -> DocRefRegistration:
    """Register a ``doc-ref`` declaration emitted from a transpiled ``.s0ma`` module."""
    registry = _get_registry()
    return registry.register_doc_ref(
        name=name,
        module=module,
        intent=intent,
        format=format,
        output=output,
        covers=_coerce_filter_exprs(covers),
        sections=_coerce_sections(sections),
        content_hash=content_hash,
        source_span=_coerce_source_span(source_span),
        idempotent=True,
    )


@component(
    name="S0maDSL_register_doc_guide",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Register a doc-guide declaration in the s0ma registry. "
        "Coerces DSL-side primitive payloads into typed EntityRef / "
        "AssertExpr / SourceSpan records and delegates to the framework."
    ),
    contracts=Contract(
        preconditions=[
            "name, module, intent are non-empty strings",
            "format is one of markdown / html / json",
            "output is a relative path",
        ],
        postconditions=[
            "Doc-guide registration is stored in the registry and retrievable by name",
        ],
        input_type=(
            "name: str, module: str, intent: str, format: str, output: str, "
            "covers: list[dict[str, Any]] | None, "
            "asserts: list[dict[str, Any]] | None, "
            "examples: list[dict[str, Any]] | None, "
            "body: str, content_hash: str, source_span: dict[str, Any] | None"
        ),
        output_type="DocGuideRegistration",
    ),
    dependencies=["DocGuideRegistration"],
    is_framework=True,
    idempotent=True,
)
def register_doc_guide(
    *,
    name: str,
    module: str,
    intent: str,
    format: str,  # noqa: A002 — field name mandated by design §6 / plan M2
    output: str,
    covers: list[dict[str, Any]] | None = None,
    asserts: list[dict[str, Any]] | None = None,
    examples: list[dict[str, Any]] | None = None,
    body: str = "",
    content_hash: str = "",
    source_span: dict[str, Any] | None = None,
) -> DocGuideRegistration:
    """Register a ``doc-guide`` declaration emitted from a transpiled ``.s0ma`` module."""
    registry = _get_registry()
    return registry.register_doc_guide(
        name=name,
        module=module,
        intent=intent,
        format=format,
        output=output,
        covers=_coerce_entity_refs(covers),
        asserts=_coerce_asserts(asserts),
        examples=_coerce_entity_refs(examples),
        body=body,
        content_hash=content_hash,
        source_span=_coerce_source_span(source_span),
        idempotent=True,
    )


@component(
    name="S0maDSL_register_example",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Register an example declaration in the s0ma registry. "
        "Coerces DSL-side primitive payloads into typed EntityRef / "
        "SourceSpan records and delegates to the framework."
    ),
    contracts=Contract(
        preconditions=[
            "name, module, intent are non-empty strings",
            "demonstrates is a non-empty list of entity references",
            "runs_in is one of standalone / pytest / integration",
        ],
        postconditions=[
            "Example registration is stored in the registry and retrievable by name",
        ],
        input_type=(
            "name: str, module: str, intent: str, "
            "demonstrates: list[dict[str, Any]], "
            "runs_in: str, body: str, source_span: dict[str, Any] | None"
        ),
        output_type="ExampleRegistration",
    ),
    dependencies=["ExampleRegistration"],
    is_framework=True,
    idempotent=True,
)
def register_example(
    *,
    name: str,
    module: str,
    intent: str,
    demonstrates: list[dict[str, Any]],
    runs_in: str = "standalone",
    body: str = "",
    source_span: dict[str, Any] | None = None,
) -> ExampleRegistration:
    """Register an ``example`` declaration emitted from a transpiled ``.s0ma`` module."""
    registry = _get_registry()
    return registry.register_example(
        name=name,
        module=module,
        intent=intent,
        demonstrates=_coerce_entity_refs(demonstrates),
        runs_in=runs_in,  # type: ignore[arg-type]
        body=body,
        source_span=_coerce_source_span(source_span),
        idempotent=True,
    )


# ---------------------------------------------------------------------------
# Manifest-driven module import (M6b — feedback 5–6, ADR-007)
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_register_integration_helper",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Register one of the four auto-emitted helpers for an integration "
        "declaration with module_scoped=True so two integrations in different "
        "modules can share helper names without registry collisions."
    ),
    contracts=Contract(
        preconditions=[
            "func is a callable function or method",
            "module_path is the owning module's canonical name (non-empty)",
            "kind is ComponentKind.FUNCTION",
            "layer is Layer.INFRASTRUCTURE",
        ],
        postconditions=[
            "The function is registered with module_scoped=True",
            "func.__component__ is set to the new spec",
        ],
        input_type=(
            "func: Any, name: str, intent: str, module_path: str, "
            "metadata: dict[str, Any] | None"
        ),
        output_type="Any",
    ),
    dependencies=["ComponentSpec"],
    is_framework=True,
    idempotent=True,
)
def register_integration_helper(
    func: Any,
    *,
    name: str,
    intent: str,
    module_path: str,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Register one of the four auto-emitted integration helpers (POST-5).

    The four helpers emitted for every ``integration`` declaration are
    ``get_factory`` / ``get_manifest`` / ``smoke_test_primary`` /
    ``get_smoke_test``. These bare names would collide in the registry
    when two ``integration`` declarations exist in different modules,
    so each registration opts into the ``module_scoped=True`` flag on
    :class:`s0ma.models.ComponentSpec` so the registry stores them
    under ``<module_path>::<name>`` keys instead of the bare name.

    The helper does NOT use the ``@component`` decorator because that
    decorator does not expose ``module_scoped``. Instead it constructs
    a :class:`ComponentSpec` directly, registers it via
    :meth:`ComponentRegistry.register`, and attaches the spec to the
    function as ``__component__`` so introspection (``is_component``,
    ``get_component_spec``) keeps working.

    Parameters
    ----------
    func:
        The function object to register (the result of ``def
        get_factory()`` in the emitted Python).
    name:
        Bare component name (``get_factory`` / ``get_manifest`` /
        ``smoke_test_primary`` / ``get_smoke_test``).
    intent:
        Required intent prose, derived from the integration's
        ``intent:`` field plus a per-helper qualifier.
    module_path:
        Owning module's canonical name. The registry stores the spec
        under ``<module_path>::<name>``.
    metadata:
        Optional extensible key-value dict (carries the integration's
        manifest under ``"integration_manifest"`` and the parent
        integration name under ``"integration"``).

    Returns
    -------
    The decorated function (unchanged — pattern matches ``@component``).
    """
    from s0ma.models import ComponentSpec

    spec = ComponentSpec(
        name=name,
        kind=ComponentKind.FUNCTION,
        layer=Layer.INFRASTRUCTURE,
        intent=intent,
        module_path=module_path,
        qualified_name=f"{module_path}.{name}",
        metadata=metadata or {},
        module_scoped=True,
    )

    registry = _get_registry()
    registry.register(spec, idempotent=True)

    # Attach the spec to the function so ``get_component_spec`` and
    # ``is_component`` see it. Mirrors the ``@component`` decorator's
    # final step.
    setattr(func, "__component__", spec)  # noqa: B010
    return func


@component(
    name="S0maDSL_import_modules_from_manifest",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Read build.s0ma.json and import every transpiled module the "
        "manifest lists. The manifest is the canonical source of truth "
        "for what was emitted; no filesystem walking is performed."
    ),
    contracts=Contract(
        preconditions=[
            "build_dir is an existing directory containing a build.s0ma.json file",
            "build.s0ma.json carries the s0ma-build-manifest@1 schema string",
            "every module listed in the manifest has a matching .py on disk",
        ],
        postconditions=[
            "every module in the manifest is importable by name in the current process",
            "registry registrations triggered by transpiled module bodies have run",
        ],
        input_type="build_dir: Path | str, sys_path_insert: bool",
        output_type="dict[str, ModuleType]",
    ),
    is_framework=True,
    idempotent=True,
)
def import_modules_from_manifest(
    build_dir: Path | str,
    *,
    sys_path_insert: bool = True,
) -> dict[str, ModuleType]:
    """Import every transpiled module the build manifest lists.

    Reads ``build_dir/build.s0ma.json`` and imports each module by
    name. The manifest IS the contract; this function does not
    fall back to filesystem traversal. A missing or schema-mismatched
    manifest raises
    :class:`s0ma_dsl.codegen.build_manifest.ManifestSchemaError`
    with a remediation that points at ``s0ma build`` or
    ``s0ma migrate-layout``.

    M11 (feedback 5–6) — bootstrap files are *not* registered as
    components. Every entry in ``build.s0ma.json`` is the product of a
    ``.s0ma`` source being transpiled, so bootstrap files (declared
    under ``[tool.s0ma].bootstrap_files``) are by construction outside
    the manifest and never imported here. The runtime bridge does not
    need a bootstrap-aware skip list — the registration model is the
    manifest, and the manifest already excludes them.

    Parameters
    ----------
    build_dir:
        Directory holding the M6a flat layout — ``__init__.py``,
        per-module ``.py`` / ``.s0ma.json`` / ``.s0ma.map`` triples,
        and the ``build.s0ma.json`` manifest.
    sys_path_insert:
        If ``True`` (default), inserts *build_dir* at the head of
        ``sys.path`` so the modules' top-level name is the canonical
        DSL ``module`` declaration. Pass ``False`` if the caller has
        already arranged ``sys.path`` (e.g., a framework-side import
        hook).

    Returns
    -------
    dict[str, ModuleType]
        Mapping of canonical module name to imported module object.
        Order in the dict reflects the order the modules were imported,
        which is the order the manifest records. M10 extends the
        manifest with ``topological_import_order``; once that lands,
        this function will honour the explicit order field. Until
        then, the manifest's ``modules`` field is sorted by name.
    """
    from s0ma_dsl.codegen.build_manifest import load_manifest

    build_path = Path(build_dir)
    manifest = load_manifest(build_path)

    if sys_path_insert:
        build_str = str(build_path)
        if build_str not in sys.path:
            sys.path.insert(0, build_str)

    imported: dict[str, ModuleType] = {}
    for entry in manifest.modules:
        # Importing by canonical module name. The manifest's
        # ``output`` field is a basename relative to the build dir
        # (e.g., ``models.py``); ``importlib`` resolves it by name
        # via the sys.path entry we (or the caller) added.
        module_obj = importlib.import_module(entry.name)
        imported[entry.name] = module_obj
    return imported
