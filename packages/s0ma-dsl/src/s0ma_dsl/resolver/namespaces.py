"""Four-namespace model for the s0ma DSL.

Implements the namespace services defined in PRD §2.3 and spec §4.10.1.
Centralises all name resolution behind a single service to prevent
duplicated logic in validators and emitters (PRD Risk 3).

The four namespaces:
  1. Code namespace       — local + uses + requires  (Python bodies)
  2. Component-reference  — local + uses only        (DSL metadata fields)
  3. Public API           — exports list              (cross-module interface)
  4. Registry             — ALL project components    (observes, tests)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.nodes import (
    CellDecl,
    DocGuideDecl,
    DocRefDecl,
    ExampleDecl,
    GanglionDecl,
    HelperDecl,
    IntegrationDecl,
    NerveDecl,
    RequiresEntry,
    S0maModule,
    StandaloneAxonDecl,
    TestDecl,
    UsesEntry,
)
from s0ma_dsl.errors import S0maSemanticError

__all__ = [
    "AmbiguousTestTarget",
    "NamespaceEntry",
    "NamespaceService",
    "build_namespaces",
    "canonicalize_qualified_target",
    "resolve_test_target_canonical",
]


# ---------------------------------------------------------------------------
# Namespace entry — a resolved name with its origin
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_NamespaceEntry",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "A single resolved name within a namespace, tracking its origin (local, uses, or "
        "requires) and canonical identity."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class NamespaceEntry:
    """A single name within a namespace.

    ``local_name`` is the name as it appears in code or metadata fields
    (which may be an alias).  ``canonical_name`` is the fully-qualified
    identity (e.g. ``module::component`` for uses entries, or the dotted
    module path for requires entries).  ``origin`` indicates where the
    name came from.
    """

    local_name: str
    """The name usable in code or metadata (may be an alias)."""

    canonical_name: str
    """The fully-qualified or canonical identity."""

    origin: str
    """One of 'local', 'uses', or 'requires'."""

    source_entry: RequiresEntry | UsesEntry | None = None
    """The original AST entry, if this came from requires/uses."""


# ---------------------------------------------------------------------------
# Namespace service — holds all four namespaces for a module
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_NamespaceService",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent=(
        "Holds and queries the four namespaces for a single parsed module, providing alias-aware "
        "lookup and collision detection."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class NamespaceService:
    """Namespace manager for a single ``S0maModule``.

    Provides lookup into each of the four namespaces defined in PRD §2.3
    and detects namespace collisions per spec §4.10.3 (R-25).
    """

    # Namespace 1: Code namespace — local + uses + requires
    code_namespace: dict[str, NamespaceEntry] = field(default_factory=dict)

    # Namespace 2: Component-reference namespace — local + uses only (NO requires)
    component_ref_namespace: dict[str, NamespaceEntry] = field(default_factory=dict)

    # Namespace 3: Public API namespace — exports
    public_api_namespace: dict[str, NamespaceEntry] = field(default_factory=dict)

    # Namespace 4: Registry namespace — stub, populated at project level
    registry_namespace: dict[str, NamespaceEntry] = field(default_factory=dict)

    # The module this service was built from
    module_name: str = ""

    # -----------------------------------------------------------------------
    # Lookup methods (alias-aware)
    # -----------------------------------------------------------------------

    def lookup_code(self, name: str) -> NamespaceEntry | None:
        """Look up a name in the code namespace (local + uses + requires)."""
        return self.code_namespace.get(name)

    def lookup_component_ref(self, name: str) -> NamespaceEntry | None:
        """Look up a name in the component-reference namespace (local + uses only).

        ``requires`` names are excluded — DSL metadata fields must only
        reference s0ma components.
        """
        return self.component_ref_namespace.get(name)

    def lookup_public_api(self, name: str) -> NamespaceEntry | None:
        """Look up a name in the public API namespace (exports)."""
        return self.public_api_namespace.get(name)

    def lookup_registry(self, name: str) -> NamespaceEntry | None:
        """Look up a name in the registry namespace (all project components)."""
        return self.registry_namespace.get(name)

    def is_in_code_namespace(self, name: str) -> bool:
        """Check if a name exists in the code namespace."""
        return name in self.code_namespace

    def is_in_component_ref_namespace(self, name: str) -> bool:
        """Check if a name exists in the component-reference namespace."""
        return name in self.component_ref_namespace

    def is_requires_name(self, name: str) -> bool:
        """Check if a name originates from a ``requires`` entry.

        Useful for detecting when a requires name is incorrectly used
        in a DSL metadata field (which requires component-reference names).
        """
        entry = self.code_namespace.get(name)
        return entry is not None and entry.origin == "requires"

    # -----------------------------------------------------------------------
    # Bulk accessors
    # -----------------------------------------------------------------------

    def local_names(self) -> list[str]:
        """Return all locally declared component names."""
        return [
            e.local_name
            for e in self.code_namespace.values()
            if e.origin == "local"
        ]

    def uses_names(self) -> list[str]:
        """Return all names from ``uses`` entries (aliases resolved)."""
        return [
            e.local_name
            for e in self.code_namespace.values()
            if e.origin == "uses"
        ]

    def requires_names(self) -> list[str]:
        """Return all names from ``requires`` entries (aliases resolved)."""
        return [
            e.local_name
            for e in self.code_namespace.values()
            if e.origin == "requires"
        ]


# ---------------------------------------------------------------------------
# Local declaration name extraction
# ---------------------------------------------------------------------------


def _local_decl_name(
    decl: (
        NerveDecl | CellDecl | GanglionDecl | TestDecl | StandaloneAxonDecl
        | HelperDecl | IntegrationDecl | DocRefDecl | DocGuideDecl | ExampleDecl
    ),
) -> str | None:
    """Extract the name from a non-module declaration.

    Standalone axons don't contribute a local component name — they declare
    relationships, not components.

    M13 (feedback 5–6): helpers DO contribute a local name — they are
    in scope intra-module so a nerve in the same module can call them
    directly without a ``uses:`` entry.
    """
    if isinstance(decl, StandaloneAxonDecl):
        return None
    return decl.name


# ---------------------------------------------------------------------------
# Resolve the usable local name for a requires entry
# ---------------------------------------------------------------------------


def _requires_local_name(entry: RequiresEntry) -> str:
    """Determine the name by which a requires entry is available in code.

    If an alias is provided, that is the local name.
    Otherwise: for from-imports (``from uuid import UUID``), the final
    segment is used (``UUID``).  For plain imports (``import os.path``),
    the first segment is used (``os``).
    """
    if entry.alias:
        return entry.alias
    if entry.is_from_import:
        # ``from uuid import UUID`` → local name is ``UUID``
        return entry.module_path.rsplit(".", 1)[-1]
    # ``import os.path`` → local name is ``os``
    return entry.module_path.split(".")[0]


# ---------------------------------------------------------------------------
# Resolve the usable local name for a uses entry
# ---------------------------------------------------------------------------


def _uses_local_name(entry: UsesEntry) -> str:
    """Determine the name by which a uses entry is available.

    If an alias is provided, that is the local name.
    Otherwise, the component name (final segment after ``.``) is used.
    For example ``routing.select_evaluator`` → ``select_evaluator``.
    """
    if entry.alias:
        return entry.alias
    # ``routing.select_evaluator`` → ``select_evaluator``
    return entry.qualified_name.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# Collision detection
# ---------------------------------------------------------------------------


def _detect_collisions(
    s0ma_module: S0maModule,
    filename: str,
) -> list[S0maSemanticError]:
    """Detect namespace collisions per spec §4.10.3 (R-25).

    Checks:
      - local vs. local  (duplicate declaration names)
      - local vs. uses   (a uses name shadows a local declaration)
      - uses  vs. uses   (two uses entries resolve to the same local name)
      - local vs. requires (a requires name shadows a local declaration)
      - uses  vs. requires (a uses and requires entry share the same local name)
    """
    errors: list[S0maSemanticError] = []
    module_decl = s0ma_module.module

    # Collect all names with their origins and source locations
    seen: dict[str, tuple[str, int]] = {}  # name → (origin_desc, line)

    # 1. Local declarations
    for decl in s0ma_module.all_declarations:
        name = _local_decl_name(decl)
        if name is None:
            continue
        line = decl.location.start_line if decl.location else 0

        if name in seen:
            prev_origin, prev_line = seen[name]
            errors.append(S0maSemanticError(
                code="NAMESPACE_COLLISION",
                message=(
                    f"Name '{name}' collides: declared locally at line {line} "
                    f"but already present as {prev_origin} at line {prev_line}."
                ),
                file=filename,
                line=line,
                column=0,
                severity="error",
                remediation=(
                    f"Rename one of the conflicting declarations of '{name}', "
                    f"or use an alias on the import that introduces it."
                ),
                context={
                    "name": name,
                    "first_origin": prev_origin,
                    "first_line": prev_line,
                    "second_origin": "local declaration",
                    "second_line": line,
                },
            ))
        else:
            seen[name] = ("local declaration", line)

    # 2. uses entries
    for entry in module_decl.uses:
        local = _uses_local_name(entry)
        line = entry.location.start_line if entry.location else 0

        if local in seen:
            prev_origin, prev_line = seen[local]
            errors.append(S0maSemanticError(
                code="NAMESPACE_COLLISION",
                message=(
                    f"Name '{local}' (from uses entry '{entry.qualified_name}') "
                    f"collides with {prev_origin} at line {prev_line}."
                ),
                file=filename,
                line=line,
                column=0,
                severity="error",
                remediation=(
                    f"Add an alias to the uses entry: "
                    f"'{entry.qualified_name} as <unique_name>' "
                    f"to avoid the collision with '{local}'."
                ),
                context={
                    "name": local,
                    "qualified_name": entry.qualified_name,
                    "first_origin": prev_origin,
                    "first_line": prev_line,
                    "second_origin": f"uses entry '{entry.qualified_name}'",
                    "second_line": line,
                },
            ))
        else:
            seen[local] = (f"uses entry '{entry.qualified_name}'", line)

    # 3. requires entries
    for req_entry in module_decl.requires:
        local = _requires_local_name(req_entry)
        line = req_entry.location.start_line if req_entry.location else 0

        if local in seen:
            prev_origin, prev_line = seen[local]
            errors.append(S0maSemanticError(
                code="NAMESPACE_COLLISION",
                message=(
                    f"Name '{local}' (from requires entry '{req_entry.module_path}') "
                    f"collides with {prev_origin} at line {prev_line}."
                ),
                file=filename,
                line=line,
                column=0,
                severity="error",
                remediation=(
                    f"Add an alias to the requires entry: "
                    f"'{req_entry.module_path} as <unique_name>' "
                    f"to avoid the collision with '{local}'."
                ),
                context={
                    "name": local,
                    "module_path": req_entry.module_path,
                    "first_origin": prev_origin,
                    "first_line": prev_line,
                    "second_origin": f"requires entry '{req_entry.module_path}'",
                    "second_line": line,
                },
            ))
        else:
            seen[local] = (f"requires entry '{req_entry.module_path}'", line)

    return errors


# ---------------------------------------------------------------------------
# Builder — constructs a NamespaceService from a parsed S0maModule
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_build_namespaces",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Builds the four-namespace model for a parsed module, performing alias resolution and "
        "collision detection."
    ),
    idempotent=True,
    is_framework=True,
)
def build_namespaces(
    s0ma_module: S0maModule,
    filename: str = "<unknown>",
) -> tuple[NamespaceService, list[S0maSemanticError]]:
    """Build the four-namespace model for a parsed module.

    Returns a populated ``NamespaceService`` and a list of collision errors.
    The registry namespace is left as a stub — it requires project-level
    information and is populated later by the dependency resolver.

    Parameters
    ----------
    s0ma_module:
        A fully parsed ``S0maModule`` from the parser.
    filename:
        The source file path for diagnostics.

    Returns
    -------
    tuple[NamespaceService, list[S0maSemanticError]]
        The namespace service and any collision errors detected.
    """
    module_decl = s0ma_module.module
    ns = NamespaceService(module_name=module_decl.name)

    # -----------------------------------------------------------------------
    # 1. Collect local component names
    # -----------------------------------------------------------------------
    local_entries: list[NamespaceEntry] = []
    for decl in s0ma_module.all_declarations:
        name = _local_decl_name(decl)
        if name is None:
            continue
        entry = NamespaceEntry(
            local_name=name,
            canonical_name=f"{module_decl.name}::{name}",
            origin="local",
        )
        local_entries.append(entry)

    # -----------------------------------------------------------------------
    # 2. Resolve uses entries (alias-aware)
    # -----------------------------------------------------------------------
    uses_entries: list[NamespaceEntry] = []
    for use in module_decl.uses:
        local = _uses_local_name(use)
        # Canonical name from qualified_name: "routing.select_evaluator"
        # → canonical ID: "routing::select_evaluator"
        parts = use.qualified_name.rsplit(".", 1)
        canonical = f"{parts[0]}::{parts[1]}" if len(parts) == 2 else use.qualified_name
        uses_entries.append(NamespaceEntry(
            local_name=local,
            canonical_name=canonical,
            origin="uses",
            source_entry=use,
        ))

    # -----------------------------------------------------------------------
    # 3. Resolve requires entries (alias-aware)
    # -----------------------------------------------------------------------
    requires_entries: list[NamespaceEntry] = []
    for req in module_decl.requires:
        local = _requires_local_name(req)
        requires_entries.append(NamespaceEntry(
            local_name=local,
            canonical_name=req.module_path,
            origin="requires",
            source_entry=req,
        ))

    # POST-10b (0.16.0): ``runtime_only_requires:`` populates the code
    # namespace identically to ``requires:`` — the only difference
    # between the two is the vestigial-check carve-out in Phase 4 of
    # the dependency resolver. Treat them as one population from the
    # namespace's point of view so a body that does reference the
    # import (e.g. ``pytest.fixture`` on a future refactor) does not
    # collide with itself.
    for req in module_decl.runtime_only_requires:
        local = _requires_local_name(req)
        requires_entries.append(NamespaceEntry(
            local_name=local,
            canonical_name=req.module_path,
            origin="requires",
            source_entry=req,
        ))

    # -----------------------------------------------------------------------
    # 4. Populate namespaces
    # -----------------------------------------------------------------------

    # Code namespace: local + uses + requires
    for entry in local_entries:
        ns.code_namespace[entry.local_name] = entry
    for entry in uses_entries:
        ns.code_namespace.setdefault(entry.local_name, entry)
    for entry in requires_entries:
        ns.code_namespace.setdefault(entry.local_name, entry)

    # Component-reference namespace: local + uses only (NO requires)
    for entry in local_entries:
        ns.component_ref_namespace[entry.local_name] = entry
    for entry in uses_entries:
        ns.component_ref_namespace.setdefault(entry.local_name, entry)

    # Public API namespace: exports
    for export_name in module_decl.exports:
        # Check if the export is a local declaration
        local_match = next(
            (e for e in local_entries if e.local_name == export_name),
            None,
        )
        if local_match:
            ns.public_api_namespace[export_name] = local_match
        else:
            # Export name doesn't match a local declaration — we record
            # it anyway; validation of export correctness is done by the
            # intra-module validator (M7).
            ns.public_api_namespace[export_name] = NamespaceEntry(
                local_name=export_name,
                canonical_name=f"{module_decl.name}::{export_name}",
                origin="local",
            )

    # Registry namespace: stub — populated at project level by resolver
    # (For now, include local declarations as a baseline)
    for entry in local_entries:
        ns.registry_namespace[entry.canonical_name] = entry

    # -----------------------------------------------------------------------
    # 5. Detect collisions
    # -----------------------------------------------------------------------
    errors = _detect_collisions(s0ma_module, filename)

    return ns, errors


# ---------------------------------------------------------------------------
# Canonical target resolution (single source of truth for `tests:` and other
# registry-namespace fields). The IR builder, the dependency resolver, and
# any other consumer of registry-namespace targets must call through these
# helpers so that the syntactic split rule and the validating lookup rule
# are defined in exactly one place.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AmbiguousTestTarget:
    """Sentinel returned when a bare target matches multiple modules.

    The list of candidate canonical IDs is preserved so that the caller
    can surface them in an actionable diagnostic.
    """

    raw_target: str
    candidates: tuple[str, ...]


@component(
    name="S0maDSL_canonicalize_qualified_target",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Pure syntactic split of a registry-namespace target into a canonical "
        "'module::component' ID."
    ),
    idempotent=True,
    is_framework=True,
)
def canonicalize_qualified_target(target: str, source_module: str) -> str:
    """Canonicalise a target reference syntactically.

    Resolution rules (PRD §2.3.4 / spec §4.10.2):
      - If ``target`` contains a ``.``: split on the **last** dot;
        the left side is the module name, the right side is the
        component name; return ``f"{module}::{component}"``.
      - Otherwise: treat as an intra-module reference; return
        ``f"{source_module}::{target}"``.

    This is a *purely syntactic* split — it does **not** verify that the
    referenced module or component actually exists. Validation against
    the project registry is the caller's responsibility (see
    :func:`resolve_test_target_canonical`).
    """
    if "." in target:
        parts = target.rsplit(".", 1)
        return f"{parts[0]}::{parts[1]}"
    return f"{source_module}::{target}"


def _component_names_in_module(module: S0maModule) -> set[str]:
    """Return the set of component names declared in a module.

    Includes nerves, cells, ganglia, and tests. Standalone axons are
    excluded — they declare relationships, not addressable components.
    """
    names: set[str] = set()
    for decl in module.all_declarations:
        if isinstance(decl, StandaloneAxonDecl):
            continue
        names.add(decl.name)
    return names


@component(
    name="S0maDSL_resolve_test_target_canonical",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Resolves a raw test target string to a canonical 'module::component' ID by validating "
        "against the project registry, with ambiguity detection."
    ),
    idempotent=True,
    is_framework=True,
)
def resolve_test_target_canonical(
    raw_target: str,
    source_module: str,
    modules: dict[str, S0maModule],
) -> str | AmbiguousTestTarget | None:
    """Resolve a ``tests:`` field entry to a canonical ID.

    This is the **single source of truth** for `tests:` resolution. Both
    the IR builder (when emitting verification edges) and the dependency
    resolver (when checking release-mode coverage) must call this
    helper so that bare-vs-qualified, intra-vs-cross-module behaviour
    cannot drift between consumers.

    Resolution algorithm:

    1. **Qualified (contains ``.``)**: split on the last dot.
       - If the left-side module exists in the project *and* contains a
         component matching the right-side name → return canonical ID.
       - Otherwise → return ``None`` so the caller can flag the bad
         reference (the qualified name is unambiguous, but it points at
         nothing — that is *not* a release-coverage problem; some other
         pass should surface it).
    2. **Bare**: search ``source_module`` first (intra-module wins).
       - If found locally → return canonical ID.
       - Otherwise walk every module looking for a component of that
         name. If exactly one match → return its canonical ID. If
         zero matches → return ``None``. If more than one match →
         return an ``AmbiguousTestTarget`` sentinel so the caller can
         emit ``AMBIGUOUS_TEST_TARGET``.

    Parameters
    ----------
    raw_target:
        The string as it appears in the ``tests:`` list (e.g. ``"MyNerve"``
        or ``"my_module.MyNerve"``).
    source_module:
        The name of the module declaring the ``test`` block. Bare names
        resolve here first.
    modules:
        The full project registry, keyed by module name.

    Returns
    -------
    str | AmbiguousTestTarget | None
        - Canonical ID (``"module::component"``) when resolution is
          unambiguous.
        - :class:`AmbiguousTestTarget` when a bare name matches multiple
          modules.
        - ``None`` when nothing matches (the caller decides whether to
          ignore or to flag).
    """
    if "." in raw_target:
        module_name, component_name = raw_target.rsplit(".", 1)
        target_mod = modules.get(module_name)
        if target_mod is None:
            return None
        if component_name in _component_names_in_module(target_mod):
            return f"{module_name}::{component_name}"
        return None

    # Bare name: intra-module first, then cross-module unique-match.
    source_mod = modules.get(source_module)
    if source_mod is not None and raw_target in _component_names_in_module(source_mod):
        return f"{source_module}::{raw_target}"

    matches: list[str] = []
    for mod_name in sorted(modules):
        if mod_name == source_module:
            continue
        if raw_target in _component_names_in_module(modules[mod_name]):
            matches.append(f"{mod_name}::{raw_target}")

    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        return None
    return AmbiguousTestTarget(raw_target=raw_target, candidates=tuple(matches))
