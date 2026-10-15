"""Derived edge analysis for the s0ma DSL (Stage 4).

Derives RAISES and TYPE_USES edges from structured fields per PRD §1.12
and spec §4.11.1–4.11.3. Also detects conflicts between authored and
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
from s0ma_dsl.resolver.namespaces import NamespaceService, build_namespaces

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
        "fields or function signature annotations."
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
    """The relation type — always RAISES or TYPE_USES."""

    origin: str
    """The derivation origin: ``'raises_field'`` or ``'function_signature'``."""

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
        "Derives RAISES edges from raises fields and TYPE_USES edges from signatures and "
        "constructor calls, and detects conflicts with authored edges, per spec §4.11."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class DerivedEdgeAnalyzer:
    """Derives RAISES and TYPE_USES edges from a parsed ``S0maModule``.

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
    ) -> tuple[list[DerivedEdge], list[S0maSemanticError]]:
        """Derive all RAISES and TYPE_USES edges and detect conflicts.

        Parameters
        ----------
        module:
            A fully parsed and semantically validated ``S0maModule``.
        ns:
            Pre-built namespace service for the module. If ``None``,
            one is built automatically.

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

        # Detect conflicts between authored and derived edges
        conflict_errors = self._detect_conflicts(module, edges)
        errors.extend(conflict_errors)

        return edges, errors

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
        "Convenience function to derive RAISES and TYPE_USES edges and detect authored/derived "
        "conflicts for a module."
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
) -> tuple[list[DerivedEdge], list[S0maSemanticError]]:
    """Derive RAISES and TYPE_USES edges and detect conflicts.

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

    Returns
    -------
    tuple[list[DerivedEdge], list[S0maSemanticError]]
        The derived edges and any conflict errors/warnings.
    """
    analyzer = DerivedEdgeAnalyzer(mode=mode, filename=filename)
    return analyzer.analyze(module, ns=ns)
