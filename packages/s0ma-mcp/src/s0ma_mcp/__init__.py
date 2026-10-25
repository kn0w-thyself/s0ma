"""s0ma-mcp — the s0ma authoring MCP server, and its single bootstrap module.

Exposes the s0ma DSL toolchain (transpile, build, check, verify-host,
inspect, run-example, migrate, scaffold) and the agent-alignment guides
to coding agents over the Model Context Protocol (PRD §7.3, FR-MCP-1..5).

Usage::

    s0ma-mcp                      # stdio transport (console script)

    # or programmatically:
    from s0ma_mcp import create_server
    server = create_server()
    server.run()                  # stdio transport

(`from s0ma_mcp.server import create_server` — the pre-0.7.0 import
path — keeps working through a runtime alias; see the end of this
module.)

Self-hosting (FR-MCP-11, ADR-001): THE single bootstrap module
==============================================================

This package is itself a s0ma application, and this file is its **one
handwritten Python module** (the FR-MCP-11 end state, enforced by
``tests/test_components.py``): every served surface is authored as a
``.s0ma`` module under ``s0ma_src/`` and shipped as the transpiler's
committed build output in the generated subpackage ``_built/``;
everything else in the package is emitted or data (``_docs/``,
``py.typed``, the build manifest and stub). What remains handwritten
here is exactly what cannot be emitted:

* **the bootstrap** — ``s0ma.bootstrap.bootstrap_imports`` reads
  ``_built/build.s0ma.json`` and imports each built module under its
  canonical flat name in topological order (executing its emitted
  ``@component``/``register_*`` self-registrations exactly once), then
  aliases each module into this package's namespace
  (``s0ma_mcp.resources``) so every existing import form keeps working.
  A built module cannot bootstrap itself into existence;
* **the catalog bridge** — translates the built modules' global-registry
  registrations into the package self-model under their MCP-facing
  names, reading each declaration's authored ``metadata:`` /
  ``serves_as:`` facts straight from the runtime ``spec.metadata``
  (DSL-M1: the emitter passes both first-class fields through to the
  registration dict, so the bridge needs no IR access and no
  prefixed-string parsing). It consumes the bootstrap's result and
  must run before any catalog consumer;
* **the self-model machinery** — the dedicated registry, the
  ``@self_component`` decorator, and the ``self_model_*`` views the
  built modules import back from this package (their module headers
  declare ``requires: [s0ma_mcp:self_model_document, ...]``, which is
  why the plumbing above is defined BEFORE the bootstrap call below:
  the emitted imports execute against this partially-initialized
  module);
* **the factory** — :func:`create_server` derives the entire FastMCP
  surface from the self-model catalog (FR-MCP-7's no-drift clause made
  structural: a component carrying MCP metadata is served *because* it
  is in the registry, so the registered set and the served set cannot
  diverge) — plus :func:`main`, the console-script entry point.

The flat name is the ONLY runtime identity. Never import a built module
through its on-disk dotted path (``s0ma_mcp._built.<module>``) at
runtime — that would execute the module a second time and double its
registrations. The ``TYPE_CHECKING`` import below is the one sanctioned
use of the dotted path: it gives mypy the real module symbol table for
the exact same file, so emitted symbols stay strictly typed in
handwritten consumers (D-2).

Registration idiom (FR-MCP-7)
=============================

The package self-model lives in a dedicated ``ComponentRegistry``
(:func:`get_self_registry`), not the process-global one: the global
registry belongs to whatever application this server process hosts (the
built modules' own emitted registrations target it — that is the
product's runtime model), and test suites reset it at will. The
catalog is filled two ways:

* converted ``.s0ma`` surfaces — the only kind left — are absorbed by
  :func:`bridge_built_modules`: each declaration authors its MCP facts
  first-class (DSL-M1): ``metadata: mcp_uri:`` for resources (plus
  ``mcp_mime_type:`` where not text/plain), ``serves_as:`` for the
  public tool/prompt name (plus ``metadata: mcp_prompt_title:`` /
  ``mcp_tool_title:`` / ``mcp_tool_annotations: ["<field>=<bool>", ...]``), and
  ``metadata: mcp_dependency: [...]`` for referential catalog edges a
  ``.s0ma`` ``depends_on:`` honestly cannot carry — URI-shaped catalog
  names no DSL identifier can spell, the cross-boundary edge onto the
  handwritten ``self_registry``, and (per ADR-011 §(d) rule 8, weighed
  at DSL-M2 when qualified in-project ``depends_on:`` targets became
  expressible) the prompt→tool journey edges whose evidence lives in
  embedded template DATA rather than the rendering bodies — converting
  those would either fail the relation-evidence check or require a
  dishonest relation, so ``metadata:`` stays their documented
  carrier. The emitter passes the
  authored map and the served name through to the runtime
  registration, so the bridge catalogs each component under its served
  name straight from ``spec.metadata`` — which is exactly what
  :func:`create_server` derives the FastMCP registrations from. Prompt
  and tool MCP names are identifier-shaped, so their declarations are
  ``_prompt``/``_tool``-suffixed to keep the self/global registry
  name-disjointness invariant (``serves_as`` carries the served name;
  the emitted ``__name__`` stamp keeps schema titles honest without
  binding-layer mutation);
* handwritten surfaces — now exactly one, :func:`create_server` itself —
  use the :func:`self_component` decorator, which mirrors
  ``s0ma.decorators.component`` (same metadata, same ``__component__``
  attachment) but targets the package catalog.

A component that is registered but intentionally *not* served over MCP
(internal plumbing) is listed in :data:`UNSERVED_COMPONENTS`; everything
else must carry MCP identity metadata, and the D-6 suite asserts the
partition is total.

Taxonomy (and its tensions)
===========================

Core's ``ComponentKind`` / ``Layer`` enums are used as-is (extending
them is out of scope); the closest-fit choices, per surface class:

* **Tools** (``transpile`` … ``describe_server``) —
  ``FUNCTION`` / ``PRESENTATION``. Each is a stateless
  request → ``{ok, ...}`` transformation forming the server's API
  surface. Tension: there is no "endpoint" archetype; ``SERVICE`` was
  rejected (tools are not long-running or stateful) and ``ADAPTER`` is
  reserved for the actual toolchain bridge below.
* **Resources** (``s0ma://guide/*``, ``s0ma://spec/current``,
  ``s0ma://self/model``) — ``FUNCTION`` / ``PRESENTATION``, named by
  their URIs. The registered component is the provider function, not
  the document it returns (``MODEL`` was rejected for that reason).
* **Prompts** (``author_module``, ``fix_check_failures``,
  ``migrate_project``, ``diagnose_fault``) — ``FUNCTION`` / ``PRESENTATION``, named by
  their MCP prompt names: like resources they are stateless
  arguments → text providers on the served surface. Their declared
  dependencies are *referential* — the tools/resources the rendered
  copy instructs an agent to call. The prompt texts themselves are
  data: embedded-template CONSTANT cells (global-registry-only) the
  rendering nerves substitute markers into.
* **Factory** (``create_server``) — ``ORCHESTRATOR`` / ``APPLICATION``:
  it derives every served surface from the self-model catalog; its
  dependency list is computed from the catalog so it tracks the served
  surface automatically.
* **Internal plumbing** (unserved) — ``dsl_cli_bridge`` and
  ``guide_doc_loader`` are ``ADAPTER`` kind (interfaces to the s0ma DSL
  CLI and the packaged ``_docs/`` data respectively); both are authored
  in ``.s0ma`` modules whose single layer is ``PRESENTATION``, so they
  carry that layer in the catalog (the F-M0-6 re-layering — the DSL's
  one-layer-per-module rule is stricter than the hand-rolled
  ``INFRASTRUCTURE`` placement was); ``self_registry`` is ``FRAMEWORK``
  / ``FRAMEWORK`` and is the only component flagged
  ``is_framework=True`` — it is the one piece of s0ma self-model
  *machinery* this package adds, while everything else is an ordinary
  component of the s0ma-mcp application.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import json
import os
import sys
import threading
import time
from importlib import metadata as _distribution_metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from s0ma.models import ComponentSpec, Contract
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from mcp.server.fastmcp import FastMCP

    # Static identity for type checkers only — same files the bootstrap
    # imports below under the flat names (see the module docstring).
    from s0ma_mcp._built import prompts as prompts
    from s0ma_mcp._built import resources as resources
    from s0ma_mcp._built import tools as tools

__version__ = "0.21.0"

__all__ = [
    "SERVER_NAME",
    "UNSERVED_COMPONENTS",
    "__version__",
    "bridge_built_modules",
    "create_server",
    "get_self_registry",
    "live_tool_map",
    "main",
    "normalize_docstring",
    "prompts",
    "resources",
    "self_component",
    "self_model_document",
    "self_model_json",
    "self_model_text",
    "served_component_names",
    "tool_journey_map",
    "tools",
]

#: The MCP server name (FR-MCP-1) — single source for the factory and the
#: self-model surfaces.
SERVER_NAME = "s0ma-authoring"

#: Components that are registered in the self-model but intentionally not
#: served as an MCP tool/resource/prompt — the documented plumbing
#: inventory. Extend this ONLY for internal plumbing; everything else must
#: carry MCP identity metadata (the D-6 suite asserts the partition is
#: total and every metadata-carrying component is served).
UNSERVED_COMPONENTS: frozenset[str] = frozenset(
    {
        "create_server",  # the factory derives the surface; it is not on it
        "dsl_cli_bridge",  # in-process s0ma CLI invocation plumbing
        "guide_doc_loader",  # importlib.resources loader for _docs/
        "self_registry",  # the self-model registry itself
    }
)

_T = TypeVar("_T")

#: Insertion-ordered catalog of every declared spec — the self-model
#: registry's authoritative feed (the D-6 suite asserts catalog set ==
#: registry set). Filled at import time by the bridged entries of every
#: converted .s0ma module (resources, prompts, tools) plus the one
#: @self_component decoration below (create_server). create_server derives
#: the served FastMCP surface from it.
_CATALOG: dict[str, ComponentSpec] = {}

_registry: ComponentRegistry | None = None
_registry_lock = threading.Lock()


def _package_version() -> str:
    """The installed s0ma-mcp distribution version (fallback: module)."""
    try:
        return _distribution_metadata.version("s0ma-mcp")
    except _distribution_metadata.PackageNotFoundError:  # pragma: no cover
        return __version__


def self_component(
    name: str,
    kind: ComponentKind,
    layer: Layer,
    intent: str,
    *,
    contracts: Contract | None = None,
    dependencies: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    is_framework: bool = False,
) -> Callable[[_T], _T]:
    """Register a s0ma-mcp surface in the package self-model (FR-MCP-7).

    Mirrors ``s0ma.decorators.component`` — same required metadata, same
    auto-derived fields, same ``__component__`` attachment, entity
    returned unmodified — but targets this package's dedicated registry
    (see the module docstring for why not the process-global one).
    Construction validates eagerly via ``ComponentSpec`` (non-empty
    name, ≥ 10-char intent, no self-dependency), so a malformed
    registration fails at import time, not at query time.

    Args:
        name: The MCP-facing identifier — the tool/prompt name or the
            resource URI; internal plumbing uses a snake_case role name
            listed in :data:`UNSERVED_COMPONENTS`.
        kind: Closest-fit ``ComponentKind`` (taxonomy in module docstring).
        layer: Closest-fit ``Layer``.
        intent: One agent-quality sentence — this string is product.
        contracts: Behavioral contracts, where they say something real.
        dependencies: Names of other *registered* components this surface
            uses (the drift tests assert the graph stays closed).
        metadata: Extensible facts (e.g. what an adapter wraps).
        is_framework: True only for self-model machinery itself.

    Returns:
        A decorator that catalogs the spec and returns the entity as-is.
    """

    def decorator(entity: _T) -> _T:
        module_path = getattr(entity, "__module__", "") or ""
        qualname = getattr(entity, "__qualname__", None) or getattr(
            entity, "__name__", repr(entity)
        )
        qualified_name = f"{module_path}.{qualname}" if module_path else str(qualname)

        source_file: str | None = None
        with contextlib.suppress(TypeError, OSError):
            source_file = inspect.getfile(entity)  # type: ignore[arg-type]

        spec = ComponentSpec(
            name=name,
            kind=kind,
            layer=layer,
            intent=intent,
            contracts=contracts if contracts is not None else Contract(),
            dependencies=list(dependencies) if dependencies is not None else [],
            version=_package_version(),
            metadata=dict(metadata) if metadata is not None else {},
            module_path=module_path,
            qualified_name=qualified_name,
            source_file=source_file,
            is_framework=is_framework,
        )
        # First declaration wins — keeps repeated decoration (e.g. module
        # reloads) idempotent, matching core's bootstrap `contains` guard.
        _CATALOG.setdefault(name, spec)
        setattr(entity, "__component__", spec)  # noqa: B010 — mirror core
        return entity

    return decorator


#: Built-module components that are catalog plumbing rather than served
#: surfaces: maps the DSL declaration name to the established catalog name.
#: The rename keeps the self-model's stable plumbing identity ("what role
#: does this play here") while the global registry carries the built
#: module's own identity ("load_doc", "_run_cli") — the two stores stay
#: name-disjoint by construction, which the registry-separation test pins.
_BUILT_PLUMBING_RENAMES: dict[str, str] = {
    "load_doc": "guide_doc_loader",
    "_run_cli": "dsl_cli_bridge",
}

#: Which served-surface identity key a built module's ``serves_as:``
#: declarations bind to (DSL-M1). The ``.s0ma`` source authors ONE
#: public-name fact (``serves_as: check``); which MCP surface family it
#: serves is the module's architectural identity — the package
#: deliberately splits the three surface families into three modules,
#: and the bootstrap aliases them by name above. Resources are not
#: listed: resource catalog names are URIs (not identifiers), authored
#: as ``metadata: mcp_uri:`` directly.
_SERVED_AS_SURFACE_KEY_BY_MODULE: dict[str, str] = {
    "tools": "mcp_tool",
    "prompts": "mcp_prompt",
}

#: The MCP SDK's ``ToolAnnotations`` boolean hint fields — the only
#: fields an ``mcp_tool_annotations`` metadata entry may set. Validated
#: eagerly at bridge time so a typo'd field name fails the package
#: import loudly instead of being silently ignored by pydantic's
#: tolerant constructor.
_TOOL_ANNOTATION_FIELDS = frozenset(
    {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
)


def _parse_tool_annotation_entry(
    declaration_name: str, entry: str
) -> tuple[str, bool]:
    """One authored ``mcp_tool_annotations`` list entry, validated.

    Entries are ``<field>=<true|false>`` strings authored in the
    declaration's ``metadata:`` map (DSL-M1 — the flat L-1 value shapes
    deliberately exclude nested maps, so the SDK field/value pair rides
    as one string). Field names are the MCP SDK's own ``ToolAnnotations``
    hint fields; anything else is an authoring error in the ``.s0ma``
    source and fails the package import loudly (pydantic would silently
    tolerate an unknown field, hiding the typo).
    """
    field, separator, raw_value = entry.partition("=")
    if (
        not separator
        or field not in _TOOL_ANNOTATION_FIELDS
        or raw_value not in {"true", "false"}
    ):
        raise ValueError(
            f"malformed mcp_tool_annotations entry {entry!r} on built "
            f"declaration '{declaration_name}': expected "
            f"'<field>=<true|false>' with <field> in "
            f"{sorted(_TOOL_ANNOTATION_FIELDS)}"
        )
    return field, raw_value == "true"


#: The longest human-readable tool title the bridge accepts. A title is a
#: label beside a tool in a client's list, not a description; the ceiling
#: keeps it one (surface contract revision R3).
_TOOL_TITLE_MAX_CHARS = 60


def _parse_tool_title(declaration_name: str, value: object) -> str:
    """One authored ``mcp_tool_title``, validated.

    A title is what a person reads beside the tool in a client, so it is
    one short line of plain text: a non-empty string with no surrounding
    whitespace, no line break, and at most
    :data:`_TOOL_TITLE_MAX_CHARS` characters. Anything else is an
    authoring error in the ``.s0ma`` source and fails the package import
    loudly, the same way a malformed annotation entry does.
    """
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\n" in value
        or len(value) > _TOOL_TITLE_MAX_CHARS
    ):
        raise ValueError(
            f"malformed mcp_tool_title {value!r} on built declaration "
            f"'{declaration_name}': expected one line of plain text, "
            f"1 to {_TOOL_TITLE_MAX_CHARS} characters, with no leading or "
            f"trailing whitespace"
        )
    return value


def _catalog_name_for(module_name: str, spec: ComponentSpec) -> str | None:
    """The self-model catalog name a built spec serves under, if any.

    Pure runtime-registry data (DSL-M1 — no IR read): a declaration
    authoring ``metadata: mcp_uri:`` catalogs under the URI (the
    served-surface naming rule; URIs are not identifiers, so the
    declaration name stays disjoint by construction); a declaration
    authoring ``serves_as:`` catalogs under the served name (the
    emitted metadata carries it under the reserved ``serves_as`` key;
    the declaration itself is ``_tool``/``_prompt``-suffixed so the
    self/global registry name-disjointness invariant survives
    identifier-shaped served names); explicitly-mapped plumbing keeps
    its established catalog name. Everything else (data cells — the
    prompt templates included — helpers, internal providers like
    ``version_document``) stays global-registry-only.
    """
    uri = spec.metadata.get("mcp_uri")
    if isinstance(uri, str):
        return uri
    served = spec.metadata.get("serves_as")
    if isinstance(served, str) and module_name in _SERVED_AS_SURFACE_KEY_BY_MODULE:
        return served
    return _BUILT_PLUMBING_RENAMES.get(spec.name)


def bridge_built_modules(built_modules: dict[str, ModuleType]) -> None:
    """Absorb built ``.s0ma`` modules' components into the self-model.

    FR-MCP-11 mechanics (ADR-001): a built module's emitted
    ``@component`` registrations target the process-global registry
    under DSL identifier names — that is the product's runtime model.
    The package self-model (FR-MCP-7) additionally needs each converted
    surface under its MCP-facing catalog name, re-stamped with the
    package conventions. Since DSL-M1 every MCP-facing fact rides the
    RUNTIME ``spec.metadata`` (the ``.s0ma`` sources author first-class
    ``metadata:`` maps and ``serves_as:`` names; the emitter passes
    both through to the registration dict) — the bridge reads specs
    only, with no IR access and no prefixed-string parsing. For every
    member carrying a ``__component__`` spec that the module itself
    registered:

    * components authoring ``metadata: mcp_uri:`` enter the catalog
      under the **URI** (the served-surface naming rule); any authored
      ``mcp_mime_type`` already rides the same metadata;
    * components authoring ``serves_as:`` enter the catalog under the
      **served name**, with the surface-identity key
      (``metadata["mcp_tool"]`` / ``metadata["mcp_prompt"]``) stamped
      per the owning module's surface family
      (:data:`_SERVED_AS_SURFACE_KEY_BY_MODULE`); tool declarations'
      authored ``mcp_tool_annotations`` entries (``<field>=<bool>``
      strings) are validated and folded into the hint dict
      ``create_server`` binds, and an authored ``mcp_tool_title`` is
      validated as one short line of plain text and joins that dict
      under ``title``;
    * explicitly-mapped plumbing (:data:`_BUILT_PLUMBING_RENAMES`)
      keeps its established catalog name and stays in
      :data:`UNSERVED_COMPONENTS`;
    * everything else stays global-registry-only — exactly the
      pre-conversion catalog scope.

    The stamped metadata is the §1.3 carrier :func:`create_server`
    derives the FastMCP surface from. Dependency edges are translated
    through the same name mapping; edges onto components outside the
    mapping are dropped (the documented F-M0-6 deltas — the self-model's
    plumbing edges, not the served surface), and authored
    ``mcp_dependency`` referential edges (the edges weighed and kept as
    metadata at DSL-M2 — URI-shaped catalog names, the cross-boundary
    ``self_registry`` edge, and the template-evidence prompt→tool
    journey edges; see the module docstring) are appended in authored
    order.
    Specs are re-stamped with ``version`` = the installed package
    version and ``module_path``/``qualified_name`` under the package's
    dotted alias, so every self-model invariant (one version,
    ``module_path`` starts with ``s0ma_mcp``) holds for bridged and
    handwritten components alike. Idempotent: the catalog is filled
    with ``setdefault`` exactly like ``@self_component``.

    DSL-M2 note: ``spec.dependencies`` translation covers SAME-module
    bare targets (the only kind these sources author). Qualified
    in-project ``depends_on:`` targets now exist in the language and
    would arrive here as canonical ``module::declaration`` strings —
    if a future edit authors one, extend ``catalog_name_by_built`` to
    a cross-module map before relying on the edge (today such an entry
    would be dropped like any other unmapped dependency).
    """
    for module_name, module in built_modules.items():
        own_specs: dict[str, ComponentSpec] = {}
        for member in vars(module).values():
            spec = getattr(member, "__component__", None)
            if (
                isinstance(spec, ComponentSpec)
                and spec.module_path == module_name
            ):
                own_specs.setdefault(spec.name, spec)

        catalog_name_by_built = {
            built_name: _catalog_name_for(module_name, spec)
            for built_name, spec in own_specs.items()
        }

        for built_name, spec in own_specs.items():
            catalog_name = catalog_name_by_built.get(built_name)
            if catalog_name is None:
                continue
            extra_dependencies = spec.metadata.get("mcp_dependency")
            translated_deps = [
                str(catalog_name_by_built[dep])
                for dep in spec.dependencies
                if catalog_name_by_built.get(dep) is not None
            ]
            translated_deps.extend(
                str(dep)
                for dep in (
                    extra_dependencies
                    if isinstance(extra_dependencies, list)
                    else ()
                )
                if dep not in translated_deps
            )
            bridged_metadata = dict(spec.metadata)
            served = spec.metadata.get("serves_as")
            surface_key = _SERVED_AS_SURFACE_KEY_BY_MODULE.get(module_name)
            if isinstance(served, str) and surface_key is not None:
                bridged_metadata[surface_key] = served
                if surface_key == "mcp_tool":
                    hint_entries = spec.metadata.get(
                        "mcp_tool_annotations", []
                    )
                    bridged_metadata["mcp_tool_annotations"] = dict(
                        _parse_tool_annotation_entry(built_name, str(entry))
                        for entry in (
                            hint_entries
                            if isinstance(hint_entries, list)
                            else ()
                        )
                    )
                    if "mcp_tool_title" in spec.metadata:
                        # The title joins the hint dict, so the registry's
                        # account of a tool's annotations is exactly what
                        # ``create_server`` serves — the documentation
                        # model compares the two and refuses a difference.
                        bridged_metadata["mcp_tool_annotations"]["title"] = (
                            _parse_tool_title(
                                built_name, spec.metadata["mcp_tool_title"]
                            )
                        )
            _CATALOG.setdefault(
                catalog_name,
                ComponentSpec(
                    name=catalog_name,
                    kind=spec.kind,
                    layer=spec.layer,
                    intent=spec.intent,
                    contracts=spec.contracts,
                    dependencies=translated_deps,
                    version=_package_version(),
                    metadata=bridged_metadata,
                    module_path=f"s0ma_mcp.{module_name}",
                    qualified_name=f"s0ma_mcp.{module_name}.{built_name}",
                    source_file=spec.source_file,
                    is_framework=False,
                ),
            )


def normalize_docstring(entity: _T) -> _T:
    """Normalize ``entity.__doc__`` to its PEP 257 ``cleandoc`` form, in place.

    FastMCP derives every docstring-borne description on the served MCP
    surface — tools, resources, and prompts alike — from raw
    ``__doc__``, and raw ``__doc__`` is interpreter-dependent: CPython
    3.13 strips the common leading whitespace at compile time
    (python/cpython gh-81283) while 3.11/3.12 preserve the source
    indentation, so the same source served different description bytes
    per interpreter (caught by the SH-M3 surface snapshot; friction log
    F-M3-8). ``inspect.cleandoc`` maps both raw forms to one canonical
    string, making the served surface version-independent.

    :func:`create_server` MUST route every callable it binds onto the
    MCP surface through this helper — the derived bindings below do, and
    any future binding must too. The committed surface snapshot pins the
    normalized form, so a binding that skips this helper fails
    ``test_served_surface_matches_snapshot`` on every supported
    interpreter (even 3.13 serves a trailing newline raw that
    ``cleandoc`` strips).

    Idempotent (``cleandoc`` is a fixed point on its own output) and a
    no-op for entities without a docstring; returns the entity, so it
    stacks as a decorator beneath a FastMCP registration call.
    """
    doc = getattr(entity, "__doc__", None)
    if isinstance(doc, str):
        entity.__doc__ = inspect.cleandoc(doc)
    return entity


def served_component_names() -> list[str]:
    """Sorted names of every cataloged component that is served over MCP.

    Evaluated at this module's import time (after the bootstrap and
    bridge below) to declare the factory's dependencies, so the
    factory's edge list tracks the served surface automatically.
    """
    return sorted(name for name in _CATALOG if name not in UNSERVED_COMPONENTS)


def _dependency_ordered(catalog: dict[str, ComponentSpec]) -> list[ComponentSpec]:
    """The catalog in a dependency-respecting registration order.

    Catalog insertion order is *import* order, and from M1 the prompt
    components (imported first, alphabetically) declare dependencies on
    tool components imported after them — registering in raw insertion
    order would make core's registry log a forward-reference warning per
    edge (and fail outright under ``strict_dependencies``). A simple
    deterministic Kahn pass fixes the order; insertion order breaks
    ties, so the result is stable. Dependencies that are not in the
    catalog at all do not block (the drift suite asserts the graph is
    closed, so that arm is defensive only).
    """
    ordered: list[ComponentSpec] = []
    placed: set[str] = set()
    pending = list(catalog.values())
    while pending:
        ready = [
            spec
            for spec in pending
            if all(dep in placed for dep in spec.dependencies if dep in catalog)
        ]
        if not ready:  # pragma: no cover - cycle; register rest, core warns
            ordered.extend(pending)
            break
        ordered.extend(ready)
        placed.update(spec.name for spec in ready)
        pending = [spec for spec in pending if spec.name not in placed]
    return ordered


@self_component(
    "self_registry",
    ComponentKind.FRAMEWORK,
    Layer.FRAMEWORK,
    intent=(
        "Holds the s0ma-mcp self-model: a dedicated component registry "
        "of every tool, resource, prompt, and factory this server "
        "exposes, kept apart from the process-global registry"
    ),
    contracts=Contract(
        postconditions=[
            "repeated calls return the same registry instance",
            "the registry contains every cataloged component exactly once",
        ],
    ),
    is_framework=True,
)
def get_self_registry() -> ComponentRegistry:
    """The package self-model: a dedicated registry of every component.

    Lazily builds one module-level ``ComponentRegistry`` (no
    persistence, no global-singleton interaction) and registers the full
    catalog into it exactly once — repeated calls, repeated
    ``create_server()`` invocations, and repeated test imports all see
    the same instance with a stable component set. The catalog is
    necessarily complete by the time any caller can exist: every entry
    is made during this module's own execution (the bootstrap/bridge
    below plus the factory decoration), which any importer must finish
    first.
    """
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                registry = ComponentRegistry(persist=False)
                for spec in _dependency_ordered(_CATALOG):
                    if not registry.contains(spec.name):
                        registry.register(spec)
                _registry = registry
    return _registry


def self_model_document() -> dict[str, Any]:
    """The live component graph as a JSON-compatible document.

    Rendered through core's own self-model machinery — the registry
    snapshot and its serialization (``RegistrySnapshot.to_dict``) — plus
    a server identity block; nothing is hand-assembled per component.
    """
    snapshot = get_self_registry().snapshot()
    return {
        "server": {
            "name": SERVER_NAME,
            "package": "s0ma-mcp",
            "version": _package_version(),
        },
        "component_count": snapshot.component_count,
        "self_model": snapshot.to_dict(),
    }


def self_model_json() -> str:
    """:func:`self_model_document` as pretty-printed JSON text."""
    return json.dumps(self_model_document(), indent=2)


def self_model_text() -> str:
    """Core's human/LLM rendering of the graph (FR-CORE-6 dogfooded).

    ``RegistrySnapshot.describe()`` is the same renderer s0ma-core's
    bootstrap test validates for the framework's own self-description.
    """
    return get_self_registry().snapshot().describe()


def live_tool_map() -> dict[str, str]:
    """Return the compact live tool-name-to-intent map.

    This is derived from the same catalog :func:`create_server` serves, so
    initialize guidance, body-failure recovery, and ``describe_server`` do
    not maintain a second inventory.
    """
    return {
        name: spec.intent
        for name, spec in sorted(_CATALOG.items())
        if isinstance(spec.metadata.get("mcp_tool"), str)
    }


def tool_journey_map() -> dict[str, list[str]]:
    """Map common job situations to the live tools that carry the journey."""
    journeys = {
        "orient in an unfamiliar project": ["project_status"],
        "initialize an unconfigured project": ["init_project", "scaffold_module"],
        "start a component from intent": ["scaffold_module", "check", "build_project"],
        "transpile a focused source": ["transpile", "inspect_module"],
        "inspect before grepping": ["inspect_module"],
        "repair authored diagnostics": ["check", "build_project"],
        "migrate pre-existing Python": ["adopt_file", "inspect_module", "scaffold_module"],
        "migrate legacy file extensions": ["migrate_ext", "build_project", "check"],
        "prove host runtime reality": ["check", "verify_host"],
        "diagnose an observed runtime fault": ["project_status", "inspect_module", "run_example"],
        "discover available capabilities": ["describe_server"],
        "send feedback about s0ma": ["prepare_feedback", "submit_feedback"],
        # F7: the situation is not knowing what a s0ma word means. A
        # first-party entry rather than the intent-neutral fallback
        # below, which would have read "use the live learn_s0ma
        # capability" and taught nobody when to reach for it.
        "look up a s0ma concept, command or diagnostic": ["learn_s0ma"],
    }
    live = set(live_tool_map())
    mapped = {tool for tools in journeys.values() for tool in tools}
    missing = sorted(mapped - live)
    if missing:
        raise RuntimeError(f"tool journey map names unserved tools: {missing}")
    # The factory is intentionally catalog-derived: extensions and derivation
    # tests may add a live tool without editing this function. Keep recovery
    # complete for those tools with a deterministic intent-neutral fallback;
    # first-party tools above retain their concise situation wording.
    for tool in sorted(live - mapped):
        journeys[f"use the live {tool} capability"] = [tool]
    return journeys


if not TYPE_CHECKING:
    # M10: the loader lives in Apache-licensed s0ma-core, so a package
    # that ships its own committed build boots without the authoring
    # packages on the runtime path (INV-9).
    from s0ma.bootstrap import bootstrap_imports

    # One module object per built module, executed exactly once under
    # its canonical flat name (the DSL's import contract: build_dir on
    # sys.path, manifest-driven topological order). The emitted modules
    # import this package's self-model views back (`from s0ma_mcp
    # import self_model_document`, authored as `requires:
    # [s0ma_mcp:...]` colon-overrides) — those imports execute against
    # THIS partially-initialized module, which is why everything they
    # need is defined above this call.
    _built_modules = bootstrap_imports(Path(__file__).parent / "_built")

    # Package-namespace aliases: the same module object is reachable as
    # s0ma_mcp.<name> (attribute AND sys.modules entry) so existing
    # `from s0ma_mcp.resources import X` / `import s0ma_mcp.resources`
    # forms keep working. One object, two names — never two executions.
    resources = _built_modules["resources"]
    sys.modules[__name__ + ".resources"] = resources
    prompts = _built_modules["prompts"]
    sys.modules[__name__ + ".prompts"] = prompts
    tools = _built_modules["tools"]
    sys.modules[__name__ + ".tools"] = tools

    # Bridge the built modules' component registrations into the package
    # self-model (FR-MCP-7) — must run before the factory decoration
    # below, whose dependency list is computed from the catalog.
    bridge_built_modules(_built_modules)


#: Values of ``S0MA_MCP_TELEMETRY`` that mean "off" (case-insensitive).
#: Anything else non-empty turns the hook on.
_TELEMETRY_OFF_VALUES = frozenset({"", "0", "false", "off", "no"})

#: Serializes JSONL appends — FastMCP runs sync providers on a thread
#: pool, so two tool calls can complete concurrently.
_telemetry_lock = threading.Lock()


def _telemetry_enabled() -> bool:
    """True when ``S0MA_MCP_TELEMETRY`` is set to a truthy value."""
    return (
        os.environ.get("S0MA_MCP_TELEMETRY", "").strip().lower()
        not in _TELEMETRY_OFF_VALUES
    )


def _telemetry_sink_path() -> Path:
    """The JSONL sink: ``S0MA_MCP_TELEMETRY_SINK`` or a user-cache default.

    NEVER stdout — on the stdio transport stdout is the protocol channel
    and a single stray line corrupts the JSON-RPC stream.
    """
    configured = os.environ.get("S0MA_MCP_TELEMETRY_SINK", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "s0ma-mcp" / "telemetry.jsonl"


def _telemetry_sanitize(value: Any) -> str:
    """A bounded string form of one call argument (values can be large)."""
    text = repr(value)
    return text if len(text) <= 200 else text[:197] + "..."


def _telemetry_record_size(result: Any) -> int | None:
    """Approximate byte size of a provider result, best-effort."""
    try:
        if isinstance(result, str):
            return len(result.encode("utf-8"))
        return len(json.dumps(result, default=str).encode("utf-8"))
    except Exception:  # noqa: BLE001 — sizing must never fail a call
        return None


def _telemetry_append(record: dict[str, Any]) -> None:
    """Append one JSONL record to the sink; failures are swallowed.

    Telemetry must never change what the agent observes — a full disk,
    an unwritable sink, or an unserializable record drops the record,
    never the tool call.
    """
    try:
        sink = _telemetry_sink_path()
        sink.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, default=str)
        with _telemetry_lock, sink.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001 — observability, not behavior
        pass


#: The project-scoped runbook resource URI (O1, batch-01a). A read of it
#: is the bench's "did the agent consult the ops runbook" signal.
_RUNBOOK_URI = "s0ma://project/runbook"


def _telemetry_result_has_drift(result: Any) -> bool:
    """True when a diagnostics result surfaced a ``GENERATED_FILE_DRIFT`` code.

    The check/build tools return the DSL's ``--format json`` diagnostics
    verbatim under ``result["diagnostics"]``; a hand-edited generated file
    shows up as a ``GENERATED_FILE_DRIFT`` finding (a check-time warning,
    a build-time refusal error). This is read-only inspection of the
    value the agent already received — nothing is added to the result.
    """
    if not isinstance(result, dict):
        return False
    diagnostics = result.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return False
    for bucket in ("errors", "warnings"):
        for finding in diagnostics.get(bucket) or []:
            if (
                isinstance(finding, dict)
                and finding.get("code") == "GENERATED_FILE_DRIFT"
            ):
                return True
    return False


def _telemetry_result_has_declaration_suggestion(result: Any) -> bool:
    """True when a diagnostics result carries a ``suggested_declaration``.

    M1 (0.13.0, batch-01c): the self-healing contract diagnostics
    (``PROVIDES_KEY_MISMATCH`` / ``MISSING_PACKAGE``) attach a ready-to-paste
    corrected declaration block as a ``suggested_declaration`` value on the
    finding. The DSL emits it in the ``--format json`` diagnostics that the
    check/build tools return verbatim under ``result["diagnostics"]``, so —
    exactly like :func:`_telemetry_result_has_drift` — this is read-only
    inspection of the value the agent already received; nothing is added to
    the result. Presence of a non-empty block anywhere is the bench's
    "the toolchain taught the fix this call" signal (batch-02a's teaching
    KPI: did fix-loop length drop when a suggestion was shown?).
    """
    if not isinstance(result, dict):
        return False
    diagnostics = result.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return False
    for bucket in ("errors", "warnings"):
        for finding in diagnostics.get(bucket) or []:
            if (
                isinstance(finding, dict)
                and finding.get("suggested_declaration")
            ):
                return True
    return False


def _telemetry_result_has_new_error_override(result: Any) -> bool:
    """True when a ``build_project`` result waved NEW check errors through.

    M2 (0.13.0, batch-01c): the build gate refuses to emit when an edit
    introduces NEW check-severity errors since the last baseline (the
    check-red / build-green gap the CM6 crater shipped through). Passing
    ``allow_new_errors=true`` overrides the refusal and builds; the DSL
    stamps a ``build_override`` block into the ``--format json`` document
    the tool returns verbatim under ``result["diagnostics"]``. Read-only
    inspection of the value the agent already received — nothing is added
    to the result — so the bench can count how often the override fires
    (batch-02a's guardrail: did agents lean on the escape hatch?).
    """
    if not isinstance(result, dict):
        return False
    diagnostics = result.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return False
    return bool(diagnostics.get("build_override"))


#: The telemetry JSONL record schema tag — the one self-describing marker
#: carried on every record (M3, batch-01c). 0.11.0's records carried the
#: derived ``counters`` list but no version/schema marker at all, so a
#: consumer had to shape-sniff the record to recognize it: the bench's
#: guardrail-counter table silently rendered all-n/a for batch-01c because
#: its detector keyed on the ``counters`` key it didn't yet recognize
#: (fixed bench-side by keying on ``counters``-presence — the
#: counter-evidence for this marker). Now every record is self-describing:
#: consumers key on this tag. Discipline — the ``@N`` suffix bumps ONLY on
#: a breaking record-shape change; @2 is the first MARKED shape (the
#: implicit, unmarked 0.11.0 shape is @1), and ``counters``-presence stays
#: the documented fallback for recognizing a pre-marker (@1) record.
_TELEMETRY_SCHEMA = "s0ma-telemetry@2"


def _telemetry_counters(surface: str, name: str, result: Any) -> list[str]:
    """Derive the batch-01a bench counter tags for one served call (P2).

    Pure inspection of the ``(surface, name, result)`` the wrapper
    already has — no result field is added, so these tags exist ONLY in
    the telemetry JSONL and only when the hook is enabled (the record
    itself only exists then). The four signals the batch-01a verification
    plan needs to watch:

    * ``runbook_read`` — a read of the ``s0ma://project/runbook`` resource
      (the new ops-story surface).
    * ``inline_rule_impression`` — a tool result carrying the inline
      survival ``rules`` (D1: init_project / scaffold_module /
      describe_server).
    * ``refused_overwrite`` — ``build_project`` surfaced
      ``GENERATED_FILE_DRIFT`` (the B2 refusal to clobber a hand-edited
      generated file).
    * ``drift_shown`` — ``check`` surfaced ``GENERATED_FILE_DRIFT`` (the
      M1 warn pass that shows the hand edit before the next build
      refuses on it).
    * ``declaration_suggestion_shown`` — a tool result surfaced a
      ``suggested_declaration`` block (0.13.0 M1: the self-healing contract
      diagnostics handed the agent a ready-to-paste corrected declaration).
      Result-driven, not name-gated — any tool that surfaces DSL diagnostics
      (``check`` / ``build_project`` / ``transpile``) registers the teaching
      exposure — so the bench can measure whether showing the fix shortened
      the fix loop (batch-02a's teaching KPI).
    * ``build_override_new_errors`` — a ``build_project`` result carried a
      ``build_override`` block (0.13.0 M2: ``allow_new_errors=true`` waved
      NEW check errors past the build gate). Lets the bench count how often
      agents lean on the escape hatch instead of fixing the new errors.
    """
    counters: list[str] = []
    if surface == "resource" and name == _RUNBOOK_URI:
        counters.append("runbook_read")
    if isinstance(result, dict):
        if result.get("rules"):
            counters.append("inline_rule_impression")
        if surface == "tool" and _telemetry_result_has_drift(result):
            if name == "build_project":
                counters.append("refused_overwrite")
            elif name == "check":
                counters.append("drift_shown")
        if surface == "tool" and _telemetry_result_has_declaration_suggestion(
            result
        ):
            counters.append("declaration_suggestion_shown")
        if (
            surface == "tool"
            and name == "build_project"
            and _telemetry_result_has_new_error_override(result)
        ):
            counters.append("build_override_new_errors")
    return counters


def _telemetry_wrap(surface: str, name: str, provider: _T) -> _T:
    """Optionally wrap a served provider with JSONL call telemetry.

    The §6 improvement-telemetry hook (pilot-01 memo). Deliberately
    UNREGISTERED — a documented FR-MCP-7 exception: a cataloged
    component would enter ``describe_server`` / ``s0ma://self/model``
    payloads and violate the agent-invisibility invariant the hook
    exists to uphold. It lives here because ``__init__.py`` is the one
    FR-MCP-11-permitted handwritten module.

    Invisibility by construction:

    * flag off (``S0MA_MCP_TELEMETRY`` unset/falsy — the default): the
      provider is returned UNTOUCHED. Identical object, identical code
      path, provably zero delta.
    * flag on: ``functools.wraps`` copies ``__name__`` / ``__qualname__``
      / ``__doc__`` / ``__annotations__`` and sets ``__wrapped__``, and
      the wrap is applied AFTER :func:`_served_as` /
      :func:`normalize_docstring` — so FastMCP's derived schemas
      (``inspect.signature`` follows ``__wrapped__``) and descriptions
      are byte-identical to the unwrapped surface. The only observable
      delta is wall-clock: one JSONL append per call, to a file sink,
      never stdout (stdio transport). Each record leads with a
      ``telemetry_schema`` marker (:data:`_TELEMETRY_SCHEMA`, M3) so a
      consumer keys on the tag instead of shape-sniffing, and additionally
      carries derived bench ``counters`` (:func:`_telemetry_counters`)
      computed from the ``(surface, name, result)`` triple — both live
      only in the JSONL, never in the result the agent receives. Results
      and exceptions pass through unmodified.
      ``tests/test_telemetry_invisibility.py`` pins all of this over a
      real stdio session.

    Honest scope limit: calls rejected by FastMCP's schema validation
    never reach the provider, so malformed-call telemetry needs SDK
    middleware — out of scope here.
    """
    if not _telemetry_enabled():
        return provider

    fn: Callable[..., Any] = provider  # type: ignore[assignment]

    @functools.wraps(fn)
    def logged(*args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        ok = True
        result: Any = None
        try:
            result = fn(*args, **kwargs)
            return result
        except BaseException:
            ok = False
            raise
        finally:
            _telemetry_append(
                {
                    # M3 (batch-01c): the self-describing schema marker —
                    # first field on every record (including zero-counter
                    # events) so a consumer keys on the tag instead of
                    # shape-sniffing; counters-presence stays the documented
                    # 0.11.0 fallback for pre-marker records.
                    "telemetry_schema": _TELEMETRY_SCHEMA,
                    "ts": time.time(),
                    "surface": surface,
                    "name": name,
                    "ok": ok,
                    "ms": (time.monotonic() - started) * 1000.0,
                    "size": _telemetry_record_size(result) if ok else None,
                    # P2 (batch-01a): the bench counter tags for this call,
                    # derived from the (surface, name, result) triple —
                    # present ONLY in the JSONL, only when the hook is on.
                    "counters": _telemetry_counters(surface, name, result),
                    "args": {
                        "positional": [_telemetry_sanitize(a) for a in args],
                        "keyword": {
                            key: _telemetry_sanitize(val)
                            for key, val in sorted(kwargs.items())
                        },
                    },
                }
            )

    return logged  # type: ignore[return-value]


#: Parameters a built tool body may declare to receive MCP *interaction*
#: facts the protocol — not the caller — supplies. :func:`_mcp_binding`
#: fills them in and HIDES them from the served input schema, so a
#: coding agent can neither read them nor forge them: a client-supplied
#: "the user already approved this" would defeat the only thing the
#: approval step exists for (FD-6). A tool body that declares neither is
#: bound exactly as before — every existing tool takes this path.
#:
#: * ``mcp_client`` — ``{name, version?, protocol_version?}`` of the
#:   coding client on the other end of the session, or ``None``.
#: * ``mcp_approval`` — the user's decision from the client's
#:   elicitation interaction: ``{"action": "accept", "contact_ok": bool}``
#:   / ``{"action": "decline" | "cancel" | "unavailable"}``. The body is
#:   first called with ``{"action": "preview"}`` to obtain the copy the
#:   user will read; see :func:`_mcp_binding`.
_MCP_INJECTED_PARAMETERS = ("mcp_client", "mcp_approval")

#: Stamped on the served ``Tool`` of any body asking for ``mcp_approval``:
#: a client-specific always-ask hint, defense in depth beside — never
#: instead of — the elicitation round and its refusal path
#: (0.14 surface budget §10.3).
_ALWAYS_ASK_META = {"anthropic/requiresUserInteraction": True}


def _mcp_session(ctx: Any) -> Any | None:
    """The live client session behind a request Context, or ``None``.

    ``Context.session`` RAISES outside a request (the in-process
    ``call_tool`` path the suite uses, a direct Python call), so this is
    a try/except and not a ``getattr`` default. No session simply means
    there is nobody to ask — never a tool failure.
    """
    if ctx is None:
        return None
    try:
        return ctx.session
    except Exception:  # noqa: BLE001 - "no live session" is an answer, not a fault
        return None


def _mcp_client_identity(ctx: Any) -> dict[str, Any] | None:
    """The calling client's own account of itself, or ``None``.

    Read from the initialize handshake the SDK already holds
    (``clientInfo`` + ``protocolVersion``), never from tool arguments.
    """
    params = getattr(_mcp_session(ctx), "client_params", None)
    if params is None:
        return None
    identity: dict[str, Any] = {}
    info = getattr(params, "clientInfo", None)
    name = getattr(info, "name", None)
    if isinstance(name, str) and name:
        identity["name"] = name
        version = getattr(info, "version", None)
        if isinstance(version, str) and version:
            identity["version"] = version
    protocol = getattr(params, "protocolVersion", None)
    if isinstance(protocol, str) and protocol:
        identity["protocol_version"] = protocol
    return identity or None


async def _elicit_approval(ctx: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Put one approval question to the user and report their answer.

    Protocol plumbing only: every word the user reads — the report
    itself, the two labels, the contact question — is authored copy this
    function was handed by the tool body (``approval_request``), and the
    only thing it returns is the decision. A client that declared no
    elicitation capability, an in-process call with no live session, and
    an elicitation the SDK could not complete are one answer:
    ``unavailable``, which the body turns into the refusal path. There is
    no substitute approval and no default-yes anywhere on this path.
    """
    from mcp.types import ClientCapabilities, ElicitationCapability
    from pydantic import Field, create_model

    session = _mcp_session(ctx)
    try:
        capable = session is not None and session.check_client_capability(
            ClientCapabilities(elicitation=ElicitationCapability())
        )
    except Exception:  # noqa: BLE001 - an unreadable handshake is "cannot ask"
        capable = False
    if not capable:
        return {"action": "unavailable"}

    form = create_model(
        "FeedbackApproval",
        send=(bool, Field(description=str(request.get("send_label", "")))),
        contact_ok=(
            bool,
            Field(
                default=bool(request.get("contact_default", False)),
                description=str(request.get("contact_label", "")),
            ),
        ),
    )
    try:
        outcome = await ctx.elicit(
            message=str(request.get("message", "")), schema=form
        )
    except Exception:  # noqa: BLE001 - an unusable interaction is a refusal
        return {"action": "unavailable"}
    if outcome.action != "accept":
        return {"action": str(outcome.action)}
    if not bool(getattr(outcome.data, "send", False)):
        return {"action": "decline"}
    return {
        "action": "accept",
        "contact_ok": bool(getattr(outcome.data, "contact_ok", False)),
    }


def _mcp_binding(provider: Any) -> Any:
    """Supply the MCP interaction facts a built tool body asked for.

    Derivation, not enumeration: the binding is decided by the built
    signature. A body declaring none of :data:`_MCP_INJECTED_PARAMETERS`
    is returned untouched (every tool but the feedback pair), so this is
    provably zero delta for the rest of the surface.

    The wrapper is the one place the MCP *protocol* meets a tool body,
    and it stays strictly interaction plumbing — the built function
    remains the single source of the business logic. Approval runs as a
    two-call handshake so that all of it stays authored in ``.s0ma``:

    1. the body is called with ``mcp_approval={"action": "preview"}``
       and answers either a refusal (a hash mismatch, an unenrolled
       machine — nobody should be asked to approve something that
       cannot be sent) or an ``approval_request`` carrying the exact
       report and the labels the user will read;
    2. that request goes to :func:`_elicit_approval`, and the body is
       called again with the decision, which is what actually sends,
       declines, or saves a draft.

    ``__signature__`` is the built signature MINUS the injected
    parameters — that is what FastMCP derives the served input schema
    from, so the injected facts are unreachable from a client — while
    ``__annotations__`` gains ``ctx: Context``, which is what FastMCP's
    ``find_context_parameter`` reads to inject the request Context
    (it reads annotations, not the signature; both must be set, and the
    built callable's own annotations are left untouched). Same
    binding-layer precedent as :func:`normalize_docstring` (F-M3-8) and
    :func:`_served_as` (F-M4-2): the bootstrap adjusts how a built
    callable is bound, never what it does.
    """
    from mcp.server.fastmcp import Context

    signature = inspect.signature(provider)
    injected = tuple(
        name for name in _MCP_INJECTED_PARAMETERS if name in signature.parameters
    )
    if not injected:
        return provider
    served = signature.replace(
        parameters=[
            parameter
            for name, parameter in signature.parameters.items()
            if name not in injected
        ]
    )

    def facts(ctx: Any) -> dict[str, Any]:
        return (
            {"mcp_client": _mcp_client_identity(ctx)}
            if "mcp_client" in injected
            else {}
        )

    if "mcp_approval" not in injected:

        @functools.wraps(provider)
        def bound(*args: Any, ctx: Any = None, **kwargs: Any) -> Any:
            return provider(*args, **facts(ctx), **kwargs)

    else:

        @functools.wraps(provider)
        async def bound(*args: Any, ctx: Any = None, **kwargs: Any) -> Any:
            supplied = facts(ctx)
            preview = provider(
                *args, **supplied, mcp_approval={"action": "preview"}, **kwargs
            )
            request = (
                preview.get("approval_request")
                if isinstance(preview, dict)
                else None
            )
            if not isinstance(request, dict):
                return preview
            return provider(
                *args,
                **supplied,
                mcp_approval=await _elicit_approval(ctx, request),
                **kwargs,
            )

        bound.__s0ma_mcp_meta__ = dict(_ALWAYS_ASK_META)  # type: ignore[attr-defined]

    bound.__signature__ = served  # type: ignore[attr-defined]
    bound.__annotations__ = {**provider.__annotations__, "ctx": Context}
    return bound


def _bound_provider(spec: ComponentSpec) -> Any:
    """The live callable a catalog spec describes.

    Resolution is pure registry data — ``spec.module_path`` (an imported
    module: the package's bootstrap aliases for bridged specs, anything
    in ``sys.modules`` for in-test fakes) plus the attribute name from
    ``spec.qualified_name`` — so a new MCP-surfaced component is served
    without touching the factory (derivation, not enumeration; the D-6
    suite proves it with an injected fake).
    """
    module = sys.modules[spec.module_path]
    return getattr(module, spec.qualified_name.rsplit(".", 1)[-1])


def _served_as(provider: Any, served_name: str) -> Any:
    """Stamp the MCP serving identity onto a provider, in place.

    Tool declarations are ``_tool``-suffixed (registry disjointness), but
    FastMCP derives the input/output schema titles from the bound
    callable's ``__name__`` (``<name>Arguments``/``<name>DictOutput`` in
    ``func_metadata``) — the served schemas must carry the MCP tool
    name, not the declaration identifier, to stay byte-identical to the
    0.6.x surface (D-5; the snapshot pins it).

    Since DSL-M1 the converted tools author ``serves_as:`` and the
    EMITTER already stamps ``__name__``/``__qualname__`` at build time,
    so for every ``.s0ma``-built tool this call is a no-op rename to
    the name the callable already carries. Kept deliberately as an
    idempotent guard (exactly parallel to :func:`normalize_docstring`):
    any future handwritten or injected binding (the D-6 suite's fakes
    included) gets the same serving-identity guarantee without having
    to know about the emitter's stamp.
    """
    provider.__name__ = served_name
    return normalize_docstring(provider)


def _validated_tool_result(provider: Any, tool_manager: Any) -> Any:
    """Enforce the common result/action contract against the live surface.

    FastMCP validates client arguments before invoking ``provider``.  This
    wrapper is deliberately *inside* that protocol boundary: only values a
    tool body actually returned are checked here, so schema-invalid calls
    remain MCP validation errors rather than fabricated ``ok=false`` results.
    Each action is validated with the target live tool's own pydantic argument
    model — the same model FastMCP uses for real calls.
    """

    @functools.wraps(provider)
    def validated(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = provider(*args, **kwargs)
        if not isinstance(result, dict):
            raise RuntimeError("MCP tool body returned a non-object result")
        if result.get("schema") != "s0ma-tool-result@1":
            raise RuntimeError(
                "MCP tool body omitted schema='s0ma-tool-result@1'"
            )
        if not isinstance(result.get("ok"), bool):
            raise RuntimeError("MCP tool body omitted boolean ok")
        actions = result.get("next_actions")
        if not isinstance(actions, list):
            raise RuntimeError("MCP tool body omitted next_actions array")
        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                raise RuntimeError(f"next_actions[{index}] is not an object")
            target_name = action.get("tool")
            arguments = action.get("arguments")
            reason = action.get("reason")
            if not isinstance(target_name, str):
                raise RuntimeError(f"next_actions[{index}].tool is not a string")
            if not isinstance(arguments, dict):
                raise RuntimeError(
                    f"next_actions[{index}].arguments is not an object"
                )
            if not isinstance(reason, str) or not reason.strip():
                raise RuntimeError(
                    f"next_actions[{index}].reason is not a non-empty string"
                )
            target = tool_manager.get_tool(target_name)
            if target is None:
                raise RuntimeError(
                    f"next_actions[{index}] names unserved tool {target_name!r}"
                )
            try:
                target.fn_metadata.arg_model.model_validate(arguments)
            except Exception as exc:  # noqa: BLE001 - normalize SDK validator errors
                raise RuntimeError(
                    f"next_actions[{index}] arguments do not validate against "
                    f"live tool {target_name!r}: {exc}"
                ) from exc
        return result

    return validated


@self_component(
    "create_server",
    ComponentKind.ORCHESTRATOR,
    Layer.APPLICATION,
    intent=(
        "Builds the s0ma-authoring FastMCP server by deriving every "
        "tool, resource, and prompt registration from the package "
        "self-model registry — the registered component set IS the "
        "served surface"
    ),
    # Evaluated at import time, after the bootstrap + bridge above — the
    # factory's edge list therefore always equals the served surface
    # (the drift test asserts exactly this).
    dependencies=served_component_names(),
)
def create_server() -> FastMCP:
    """Create the s0ma authoring MCP server from the self-model registry.

    Every registration is DERIVED from the package self-model catalog
    (FR-MCP-11 / D-3): a component whose metadata carries ``mcp_tool``
    is bound as a tool (with its authored FR-MCP-8 ``ToolAnnotations``),
    ``mcp_uri`` as a resource (with its authored MIME type, where one
    is declared), ``mcp_prompt`` as a prompt (with its authored title) —
    there is no hand-maintained registration list, so the self-model
    and the served surface cannot drift (FR-MCP-7, structural). Every
    bound callable routes through :func:`normalize_docstring` (F-M3-8)
    and tools additionally through :func:`_served_as` and
    :func:`_mcp_binding` — the latter a no-op unless the built body asked
    for MCP interaction facts by declaring one of
    :data:`_MCP_INJECTED_PARAMETERS`.

    Returns:
        A configured FastMCP server instance named ``s0ma-authoring``
        exposing the authoring tools (transpile, build_project, check,
        verify_host, inspect_module, project_status, init_project,
        run_example, migrate_ext, scaffold_module, describe_server) with honest
        ToolAnnotations (FR-MCP-8), the authoring/operating-journey prompts
        (author_module, fix_check_failures, migrate_project, diagnose_fault,
        feedback — FR-MCP-6),
        the agent-guide resources (``s0ma://guide/*``,
        ``s0ma://spec/current``), the meta resources
        (``s0ma://meta/changelog``, ``s0ma://meta/version`` —
        FR-MCP-10), and the server's own live component graph
        (``s0ma://self/model``, FR-MCP-7). Every served binding passes
        through :func:`_telemetry_wrap` (a no-op unless
        ``S0MA_MCP_TELEMETRY`` is set).
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only sans SDK
        raise ImportError(
            "The s0ma authoring MCP server requires the MCP SDK. "
            "Install it with: pip install s0ma-mcp"
        ) from exc
    from mcp.types import ToolAnnotations

    compact_journeys = json.dumps(
        tool_journey_map(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    mcp = FastMCP(
        SERVER_NAME,
        instructions=(
            "This server exposes the s0ma authoring toolchain. s0ma is a "
            "software self-knowledge platform: you author .s0ma DSL "
            "modules, the transpiler emits self-describing Python plus a "
            "machine-readable IR. When the task is to build or extend an "
            "application as a s0ma app: call project_status first; if it "
            "is not yet a project, call init_project (adds the "
            "[tool.s0ma] table to pyproject.toml) before scaffolding. "
            "For the outcome-first cold journey, read "
            "s0ma://guide/getting-started. Then read "
            "s0ma://guide/survival-card (under 4 KB — the essential "
            "rules; the full quick-reference is large), then loop: "
            "scaffold_module -> edit -> check -> build_project. "
            # F7's docs paragraph. Budget: 527 bytes (B6), asserted in
            # tests/test_docs_read_surface.py — the discovery channel is
            # necessary but not sufficient (plan §1.2 fact 15), so it is
            # bounded, and it names the one topic query plus the index
            # to start from.
            "This server documents itself: learn_s0ma(topic) answers "
            "one question about s0ma — a concept, a CLI command, a "
            "[tool.s0ma] setting, a diagnostic code — from the "
            "documentation snapshot built with this release, and names "
            "the committed page carrying the rest. Start at "
            "s0ma://docs/index when you do not know what to ask for; "
            "s0ma://docs/concepts is the whole vocabulary in one read "
            "and s0ma://docs/journeys the worked paths. Ask rather than "
            "guess what a s0ma word means. "
            "For "
            "release evidence, first call check with gate_mode=release, "
            "then call verify_host with gate_mode=release only after the "
            "user approves executing trusted project code in the target "
            "Python environment; neither result alone proves readiness. "
            "Diagnostics are structured "
            "(code/file/line/severity/remediation) — fix what they say, "
            "and look codes up in s0ma://guide/errors. Only write .s0ma "
            "files; never edit generated .py files. Every tool takes an "
            "explicit project_root and never writes outside it. "
            "For an observed runtime fault, look inward first: capture the "
            "symptom, call project_status, use its runtime block and "
            "s0ma://project/runbook, inspect_module on suspects and their "
            "dependency neighbors, then test the smallest hypothesis against "
            "observed behavior without reverting durable state. The "
            "diagnose_fault prompt carries this journey. "
            "When a user explicitly asks to send feedback about s0ma, "
            "follow the feedback prompt's journey. If their words never "
            "named s0ma or kn0wthyself, first confirm the report is meant "
            "for the s0ma team — other tools collect feedback too. Never "
            "submit without the client's approval interaction on the exact "
            "feedback data, and never read frustration as consent. "
            f"Live situation-to-tool map: {compact_journeys}"
        ),
    )
    # FastMCP takes no version parameter, and the low-level server
    # defaults serverInfo.version to the MCP SDK's own version — which
    # told pilot-01 clients they were talking to "1.27.2" while
    # s0ma://meta/version said 0.9.0. Stamp the real package version on
    # the underlying server (the attribute create_initialization_options
    # reads; private access is the sanctioned bootstrap's job).
    mcp._mcp_server.version = _package_version()  # noqa: SLF001

    for spec in _CATALOG.values():
        tool_name = spec.metadata.get("mcp_tool")
        uri = spec.metadata.get("mcp_uri")
        prompt_name = spec.metadata.get("mcp_prompt")
        if isinstance(tool_name, str):
            hints = spec.metadata.get("mcp_tool_annotations")
            annotations = ToolAnnotations(
                **(hints if isinstance(hints, dict) else {})
            )
            # The title is served in both places a client may look for it —
            # ``annotations.title`` above and the tool's own ``title`` below
            # — from the one bridged value, so the two can never disagree
            # (surface contract revision R3).
            title = annotations.title
            provider = _mcp_binding(
                _telemetry_wrap(
                    "tool",
                    tool_name,
                    _validated_tool_result(
                        _served_as(_bound_provider(spec), tool_name),
                        mcp._tool_manager,  # noqa: SLF001 - live schema authority
                    ),
                )
            )
            mcp.tool(
                name=tool_name,
                title=title,
                annotations=annotations,
                meta=getattr(provider, "__s0ma_mcp_meta__", None),
            )(provider)
        elif isinstance(uri, str):
            mime_type = spec.metadata.get("mcp_mime_type")
            mcp.resource(
                uri,
                mime_type=mime_type if isinstance(mime_type, str) else None,
            )(
                _telemetry_wrap(
                    "resource",
                    uri,
                    normalize_docstring(_bound_provider(spec)),
                )
            )
        elif isinstance(prompt_name, str):
            title = spec.metadata.get("mcp_prompt_title")
            mcp.prompt(
                name=prompt_name,
                title=title if isinstance(title, str) else None,
            )(
                _telemetry_wrap(
                    "prompt",
                    prompt_name,
                    normalize_docstring(_bound_provider(spec)),
                )
            )

    return mcp


def main() -> None:
    """Console-script entry point: run the server on stdio transport."""
    create_server().run()


if not TYPE_CHECKING:
    # Compatibility alias (0.6.x → 0.7.0): the factory and entry point
    # lived in `s0ma_mcp.server` until SH-M4 collapsed the package to
    # this single bootstrap module. `from s0ma_mcp.server import
    # create_server` / `... import main` (the documented 0.6.x forms,
    # and any installed console-script shim still targeting
    # `s0ma_mcp.server:main`) keep working through this runtime alias
    # of the package module itself. Runtime-only: static type checkers
    # see the canonical `from s0ma_mcp import create_server` form.
    server = sys.modules[__name__]
    sys.modules[__name__ + ".server"] = server
