"""Derived edge analysis for the s0ma DSL (Stage 4).

Derives RAISES and TYPE_USES edges from structured fields per PRD §1.12
and spec §4.11.1–4.11.3, and READS edges from the constants a nerve or
ganglion body refers to. Also detects conflicts between authored and
derived edges (single-source authority enforcement).

Derived edges are inferred by the transpiler — they must never be
manually authored. This module produces the complete derived edge set
and validates that no authored edge duplicates a derived one.

PRD references: FR-14 (authored vs. derived), §1.12 (relationship rules)
Spec references: §4.11.1–4.11.3 (relationship derivation)
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.enums import Kind, Relation
from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maSemanticError
from s0ma_dsl.resolver.namespaces import (
    NamespaceService,
    build_namespaces,
    canonicalize_qualified_target,
)

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import (
        GanglionDecl,
        NerveDecl,
        S0maModule,
    )

__all__ = [
    "DerivedEdge",
    "DerivedEdgeAnalyzer",
    "analyze_derived_edges",
    "_extract_constructor_type_uses",
]


# ---------------------------------------------------------------------------
# DerivedEdge — a single derived dependency edge
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_DerivedEdge",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Represents a single derived dependency edge inferred by the transpiler from raises "
        "fields, function signature annotations or a body's references to constants."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class DerivedEdge:
    """A single derived dependency edge.

    Derived edges are inferred by the transpiler from structured fields
    and must never be manually authored. Each edge carries its origin
    (``raises_field`` or ``function_signature``) for auditability.
    """

    source: str
    """The source component name (within the current module)."""

    target: str
    """The target component name (local name or canonical ID)."""

    target_canonical: str
    """The fully-qualified canonical ID of the target (``module::component``)."""

    relation: Relation
    """The relation type: RAISES, TYPE_USES, or READS for a constant a body refers to."""

    origin: str
    """The derivation origin: ``'raises_field'``, ``'function_signature'``,
    ``'constructor_call'`` or ``'constant_reference'``."""

    source_line: int = 0
    """Line number in the source file where this edge was derived from."""


# ---------------------------------------------------------------------------
# DerivedEdgeAnalyzer — derives RAISES and TYPE_USES edges
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_DerivedEdgeAnalyzer",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent=(
        "Derives RAISES edges from raises fields, TYPE_USES edges from signatures and "
        "constructor calls and READS edges from the constants a body refers to, and detects "
        "conflicts with authored edges, per spec §4.11."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class DerivedEdgeAnalyzer:
    """Derives RAISES, TYPE_USES and READS edges from a parsed ``S0maModule``.

    Also detects conflicts where an authored edge duplicates a derived
    edge (single-source authority violation).

    Attributes
    ----------
    mode:
        Active strictness mode for severity modulation.
    filename:
        Source file path for diagnostics.
    """

    mode: StrictnessMode = StrictnessMode.DEV
    filename: str = "<unknown>"

    def analyze(
        self,
        module: S0maModule,
        ns: NamespaceService | None = None,
        *,
        constant_targets: frozenset[str] | None = None,
    ) -> tuple[list[DerivedEdge], list[S0maSemanticError]]:
        """Derive all RAISES, TYPE_USES and READS edges and detect conflicts.

        Parameters
        ----------
        module:
            A fully parsed and semantically validated ``S0maModule``.
        ns:
            Pre-built namespace service for the module. If ``None``,
            one is built automatically.
        constant_targets:
            The canonical ids (``module::NAME``) of every CONSTANT cell
            in the project, so a ``uses``-imported name that is a
            constant of another module derives a READS edge too. The
            build passes the set it has from parsing every module;
            without it only the module's own constants are read.

        Returns
        -------
        tuple[list[DerivedEdge], list[S0maSemanticError]]
            The derived edges and any conflict errors/warnings.
        """
        if ns is None:
            ns, _ = build_namespaces(module, self.filename)

        edges: list[DerivedEdge] = []
        errors: list[S0maSemanticError] = []

        # Derive RAISES edges from raises fields on nerves
        raises_edges, raises_errors = self._derive_raises_edges(module, ns)
        edges.extend(raises_edges)
        errors.extend(raises_errors)

        # Derive TYPE_USES edges from function signature annotations
        type_uses_edges, type_uses_errors = self._derive_type_uses_edges(
            module, ns
        )
        edges.extend(type_uses_edges)
        errors.extend(type_uses_errors)

        # Derive READS edges from the constants a body refers to
        edges.extend(self._derive_reads_edges(module, ns, constant_targets))

        # Detect conflicts between authored and derived edges
        conflict_errors = self._detect_conflicts(module, edges)
        errors.extend(conflict_errors)

        return edges, errors

    # -------------------------------------------------------------------
    # READS edge derivation (from constant references in bodies)
    # -------------------------------------------------------------------

    def _derive_reads_edges(
        self,
        module: S0maModule,
        ns: NamespaceService,
        constant_targets: frozenset[str] | None,
    ) -> list[DerivedEdge]:
        """Derive READS edges from the constants a nerve or ganglion body reads.

        A body that refers to a CONSTANT cell by name (``timeout =
        MIN_INTERVAL_SECONDS``) depends on that constant: a limit is
        connected to the service it governs, so ``dependencies`` of the
        service names the constant and ``impact`` of the constant names
        the service. Constants of the module itself are always known;
        constants of another module are known through
        ``constant_targets`` when the caller has the project in hand.

        An authored edge between the same source and target, with any
        relation, is the architectural statement and wins: no READS edge
        is derived for that pair, so an author who already declared
        ``depends_on: {LIMIT: {relation: READS, ...}}`` sees no
        duplicate. A name the body also binds (a parameter, a local
        assignment) is not read as the constant.
        """
        module_name = module.module.name
        constants: dict[str, str] = {}
        for cell in module.cells:
            if cell.kind == Kind.CONSTANT:
                constants[cell.name] = f"{module_name}::{cell.name}"
        if constant_targets:
            for use in module.module.uses:
                local = use.alias or use.qualified_name.rsplit(".", 1)[-1]
                entry = ns.lookup_component_ref(local)
                if entry is not None and entry.canonical_name in constant_targets:
                    constants.setdefault(local, entry.canonical_name)
        if not constants:
            return []

        authored = self._authored_pairs(module, ns)
        edges: list[DerivedEdge] = []
        decls_with_bodies: list[NerveDecl | GanglionDecl] = []
        decls_with_bodies.extend(module.nerves)
        decls_with_bodies.extend(module.ganglia)
        for decl in decls_with_bodies:
            if not decl.body:
                continue
            source_line = decl.location.start_line if decl.location else 0
            for name in sorted(_extract_free_name_reads(decl.body) & constants.keys()):
                canonical = constants[name]
                if (decl.name, canonical) in authored:
                    continue
                edges.append(DerivedEdge(
                    source=decl.name,
                    target=name,
                    target_canonical=canonical,
                    relation=Relation.READS,
                    origin="constant_reference",
                    source_line=source_line,
                ))
        return edges

    @staticmethod
    def _authored_pairs(
        module: S0maModule, ns: NamespaceService
    ) -> set[tuple[str, str]]:
        """``(source name, target canonical id)`` for every authored edge in the module."""
        module_name = module.module.name

        def canonical(target: str) -> str:
            if "." in target:
                return canonicalize_qualified_target(target, module_name)
            entry = ns.lookup_component_ref(target)
            if entry is not None:
                return entry.canonical_name
            return f"{module_name}::{target}"

        pairs: set[tuple[str, str]] = set()
        for decl in module.all_declarations:
            parent_name = getattr(decl, "name", None)
            if parent_name is None:
                continue
            for axon in getattr(decl, "depends_on", ()):
                pairs.add((parent_name, canonical(axon.target)))
        for axon in module.axons:
            pairs.add((axon.source, canonical(axon.target)))
        return pairs

    # -------------------------------------------------------------------
    # RAISES edge derivation (from raises fields)
    # -------------------------------------------------------------------

    def _derive_raises_edges(
        self,
        module: S0maModule,
        ns: NamespaceService,
    ) -> tuple[list[DerivedEdge], list[S0maSemanticError]]:
        """Derive RAISES edges from nerve ``raises`` fields.

        For each nerve with a ``raises`` field, each exception name is
        resolved to its canonical ID and a RAISES edge is emitted.

        The raises field validation (targets must exist in component-ref
        namespace) is already done by the intra-module validator (M7).
        This method only derives edges for valid entries.
        """
        edges: list[DerivedEdge] = []
        errors: list[S0maSemanticError] = []

        for nerve in module.nerves:
            if not nerve.raises:
                continue

            source_line = nerve.location.start_line if nerve.location else 0

            for exc_name in nerve.raises:
                # Look up in component-reference namespace for canonical ID
                entry = ns.lookup_component_ref(exc_name)
                if entry is None:
                    # Already reported by intra-module validator — skip
                    continue

                edges.append(DerivedEdge(
                    source=nerve.name,
                    target=exc_name,
                    target_canonical=entry.canonical_name,
                    relation=Relation.RAISES,
                    origin="raises_field",
                    source_line=source_line,
                ))

        return edges, errors

    # -------------------------------------------------------------------
    # TYPE_USES edge derivation (from function signature annotations)
    # -------------------------------------------------------------------

    def _derive_type_uses_edges(
        self,
        module: S0maModule,
        ns: NamespaceService,
    ) -> tuple[list[DerivedEdge], list[S0maSemanticError]]:
        """Derive TYPE_USES edges from function signatures and constructor calls.

        Sources:
        1. Function signature annotations (parameter types, return type)
        2. Constructor calls where the target is a known cell

        Only s0ma components in the component-reference namespace produce
        TYPE_USES edges — external Python types (from requires) are ignored.
        """
        edges: list[DerivedEdge] = []
        errors: list[S0maSemanticError] = []

        cell_names = _collect_cell_names(module)

        decls_with_bodies: list[NerveDecl | GanglionDecl] = []
        decls_with_bodies.extend(module.nerves)
        decls_with_bodies.extend(module.ganglia)

        for decl in decls_with_bodies:
            if not decl.body:
                continue

            source_line = decl.location.start_line if decl.location else 0

            # Collect candidates from both annotations and constructor calls
            annotation_names = _extract_annotation_names(decl.body)
            constructor_names = _extract_constructor_type_uses(
                decl.body, cell_names,
            )
            all_candidates = annotation_names | constructor_names

            seen_targets: set[str] = set()

            for name in sorted(all_candidates):  # Sorted for determinism
                entry = ns.lookup_component_ref(name)
                if entry is None:
                    continue

                if name in seen_targets:
                    continue
                seen_targets.add(name)

                origin = (
                    "constructor_call"
                    if name in constructor_names and name not in annotation_names
                    else "function_signature"
                )

                edges.append(DerivedEdge(
                    source=decl.name,
                    target=name,
                    target_canonical=entry.canonical_name,
                    relation=Relation.TYPE_USES,
                    origin=origin,
                    source_line=source_line,
                ))

        return edges, errors

    # -------------------------------------------------------------------
    # Conflict detection (authored vs. derived — §1.12)
    # -------------------------------------------------------------------

    def _detect_conflicts(
        self,
        module: S0maModule,
        derived_edges: list[DerivedEdge],
    ) -> list[S0maSemanticError]:
        """Detect conflicts where authored edges duplicate derived edges.

        Per PRD §1.12, single-source authority rules:
        - An authored RAISES axon must be rejected (caught by M7 validator).
        - An authored TYPE_USES axon must be rejected (caught by M7 validator).
        - If an authored edge (CALLS, READS, etc.) has the same source
          and target as a derived edge, warn in dev, error in strict.

        This method checks the third case — overlap between authored
        inline/standalone edges and derived edges where the same
        source→target pair exists in both sets (possibly with different
        relation types).
        """
        errors: list[S0maSemanticError] = []
        dup_severity = get_severity("DUPLICATE_AXON", self.mode)
        if dup_severity is None:
            return errors

        # Build a set of derived (source, target) pairs
        derived_pairs: dict[tuple[str, str], DerivedEdge] = {}
        for edge in derived_edges:
            key = (edge.source, edge.target)
            # Keep first occurrence (deterministic since edges are
            # derived in declaration order)
            if key not in derived_pairs:
                derived_pairs[key] = edge

        # Check inline depends_on entries
        for decl in module.all_declarations:
            parent_name = getattr(decl, "name", None)
            if parent_name is None:
                continue
            for axon in getattr(decl, "depends_on", ()):
                key = (parent_name, axon.target)
                if key in derived_pairs:
                    derived = derived_pairs[key]
                    axon_line = (
                        axon.location.start_line
                        if axon.location
                        else (
                            decl.location.start_line
                            if decl.location
                            else 0
                        )
                    )
                    errors.append(S0maSemanticError(
                        code="DUPLICATE_AXON",
                        message=(
                            f"Authored dependency '{parent_name}' → "
                            f"'{axon.target}' ({axon.relation.value}) "
                            f"overlaps with derived {derived.relation.value} "
                            f"edge (origin: {derived.origin}). Each "
                            f"relationship should have one authoritative "
                            f"source."
                        ),
                        file=self.filename,
                        line=axon_line,
                        column=0,
                        severity=dup_severity,
                        remediation=(
                            f"Remove the inline depends_on entry for "
                            f"'{axon.target}' — the {derived.relation.value} "
                            f"edge is already derived from the "
                            f"'{derived.origin.replace('_', ' ')}'."
                        ),
                        context={
                            "source": parent_name,
                            "target": axon.target,
                            "authored_relation": axon.relation.value,
                            "derived_relation": derived.relation.value,
                            "derived_origin": derived.origin,
                        },
                    ))

        # Check standalone axons
        for axon in module.axons:
            key = (axon.source, axon.target)
            if key in derived_pairs:
                derived = derived_pairs[key]
                line = axon.location.start_line if axon.location else 0
                errors.append(S0maSemanticError(
                    code="DUPLICATE_AXON",
                    message=(
                        f"Standalone axon '{axon.source}' → "
                        f"'{axon.target}' ({axon.relation.value}) "
                        f"overlaps with derived {derived.relation.value} "
                        f"edge (origin: {derived.origin}). Each "
                        f"relationship should have one authoritative "
                        f"source."
                    ),
                    file=self.filename,
                    line=line,
                    column=0,
                    severity=dup_severity,
                    remediation=(
                        f"Remove the standalone axon for "
                        f"'{axon.target}' — the {derived.relation.value} "
                        f"edge is already derived from the "
                        f"'{derived.origin.replace('_', ' ')}'."
                    ),
                    context={
                        "source": axon.source,
                        "target": axon.target,
                        "authored_relation": axon.relation.value,
                        "derived_relation": derived.relation.value,
                        "derived_origin": derived.origin,
                    },
                ))

        return errors


# ---------------------------------------------------------------------------
# Name-read extraction helper (READS derivation)
# ---------------------------------------------------------------------------


def _extract_free_name_reads(body: str) -> set[str]:
    """Return the names a body reads without binding them itself.

    Every ``ast.Name`` in load context counts as a read; every name the
    body binds anywhere (assignment and deletion targets, function and
    class names, parameters, import aliases, exception aliases, ``global``
    and ``nonlocal`` declarations) is removed from the answer, so a local
    that happens to share a constant's name is not read as the constant.
    An unparsable body reads nothing; the body-syntax check reports it.
    """
    if not body or not body.strip():
        return set()
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return set()

    reads: set[str] = set()
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                reads.add(node.id)
            else:
                bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            arguments = node.args
            for arg in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            ):
                bound.add(arg.arg)
            if arguments.vararg is not None:
                bound.add(arguments.vararg.arg)
            if arguments.kwarg is not None:
                bound.add(arguments.kwarg.arg)
        elif isinstance(node, ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
    return reads - bound


# ---------------------------------------------------------------------------
# Annotation extraction helper
# ---------------------------------------------------------------------------


def _collect_cell_names(module: S0maModule) -> set[str]:
    """Collect names of cells that represent constructable types.

    Returns local cell names (kinds: MODEL, EXCEPTION, ENUM, CONFIG)
    and uses-imported names that likely refer to cells. Only cell-like
    kinds are included — CONSTANT and TYPE cells are not constructable.
    """
    constructable_kinds = frozenset({
        Kind.MODEL, Kind.EXCEPTION, Kind.ENUM, Kind.CONFIG,
    })
    names: set[str] = set()
    for cell in module.cells:
        if cell.kind in constructable_kinds:
            names.add(cell.name)
    # Uses entries that reference cells — we include all uses names
    # since we can't determine kind from the entry alone. The caller
    # verifies via namespace lookup that the name is a real component.
    for use in module.module.uses:
        local = use.alias or use.qualified_name.rsplit(".", 1)[-1]
        names.add(local)
    return names


def _extract_constructor_type_uses(
    body: str,
    cell_names: set[str],
) -> set[str]:
    """Extract TYPE_USES candidates from constructor calls in body code.

    Scans all ``ast.Call`` nodes for targets matching known cell names.
    Only direct ``Name(...)`` calls are matched — attribute-chain calls
    like ``module.Cell(...)`` are matched by their root attribute.
    """
    if not body or not body.strip():
        return set()

    # F1 (feedback 5–6 follow-up): ``body`` is the canonical column-0
    # form from the AST. No secondary dedent.
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return set()

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in cell_names:
                    names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute) and node.func.attr in cell_names:
                names.add(node.func.attr)
    return names


def _extract_annotation_names(body: str) -> set[str]:
    """Extract type annotation names from function signatures in a body.

    Parses the body as Python and inspects function definition
    signatures for type annotations. Returns the set of simple names
    (``ast.Name.id``) found in parameter annotations and return type
    annotations.

    Only top-level names are extracted — nested generics like
    ``list[Foo]`` yield ``Foo``, not ``list``.

    The body is dedented before parsing to handle preserved
    indentation from ``.s0ma`` source files.
    """
    if not body or not body.strip():
        return set()

    # F1 (feedback 5–6 follow-up): ``body`` is the canonical (column-0)
    # form produced by ``parser.body_extractor.extract_body``. No
    # secondary dedent here.
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return set()

    names: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Collect all annotation nodes from the function signature
        annotations: list[ast.expr] = []

        # Parameter annotations
        for arg in node.args.args:
            if arg.annotation is not None:
                annotations.append(arg.annotation)
        for arg in node.args.posonlyargs:
            if arg.annotation is not None:
                annotations.append(arg.annotation)
        for arg in node.args.kwonlyargs:
            if arg.annotation is not None:
                annotations.append(arg.annotation)
        if node.args.vararg and node.args.vararg.annotation is not None:
            annotations.append(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation is not None:
            annotations.append(node.args.kwarg.annotation)

        # Return type annotation
        if node.returns is not None:
            annotations.append(node.returns)

        # Walk each annotation subtree for Name nodes
        for ann in annotations:
            for sub in ast.walk(ann):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)

    return names


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_analyze_derived_edges",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Convenience function to derive RAISES, TYPE_USES and READS edges and detect "
        "authored/derived conflicts for a module."
    ),
    idempotent=True,
    is_framework=True,
)
def analyze_derived_edges(
    module: S0maModule,
    *,
    mode: StrictnessMode = StrictnessMode.DEV,
    filename: str = "<unknown>",
    ns: NamespaceService | None = None,
    constant_targets: frozenset[str] | None = None,
) -> tuple[list[DerivedEdge], list[S0maSemanticError]]:
    """Derive RAISES, TYPE_USES and READS edges and detect conflicts.

    Parameters
    ----------
    module:
        A fully parsed and semantically validated ``S0maModule``.
    mode:
        Active strictness mode.
    filename:
        Source file path for diagnostics.
    ns:
        Pre-built namespace service. If ``None``, one is built.
    constant_targets:
        Canonical ids of every CONSTANT cell in the project, so imported
        constants derive READS edges too; see
        :meth:`DerivedEdgeAnalyzer.analyze`.

    Returns
    -------
    tuple[list[DerivedEdge], list[S0maSemanticError]]
        The derived edges and any conflict errors/warnings.
    """
    analyzer = DerivedEdgeAnalyzer(mode=mode, filename=filename)
    return analyzer.analyze(module, ns=ns, constant_targets=constant_targets)
