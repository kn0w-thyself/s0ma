"""Cross-module dependency resolution for the s0ma DSL.

Implements the four-phase resolution algorithm:
  Phase 1: Module graph construction and cycle detection
  Phase 2: Export validation (uses references must exist in target exports)
  Phase 3: External validation (requires entries must be importable)
  Phase 4: Usage verification (vestigial import detection + evidence rules)

Also validates standalone axon cross-module consistency.

PRD references: FR-11 through FR-13, §2.3.3–2.3.4
Spec references: §4.6.1–4.6.4 (resolution phases), §4.6.3 (evidence rules)
"""

from __future__ import annotations

import ast
import importlib.util
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.enums import Layer as AstLayer
from s0ma_dsl.ast_nodes.enums import Relation, Visibility
from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maResolutionError
from s0ma_dsl.resolver.namespaces import (
    AmbiguousTestTarget,
    build_namespaces,
    resolve_test_target_canonical,
)
from s0ma_dsl.suggestions import render_requires_block

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import (
        HelperDecl,
        IntegrationDecl,
        NerveDecl,
        RequiresEntry,
        S0maModule,
        SourceLocation,
        UsesEntry,
    )

__all__ = [
    "DependencyResolver",
    "resolve_dependencies",
]


# ---------------------------------------------------------------------------
# Helpers: qualified name decomposition
# ---------------------------------------------------------------------------


def _module_from_qualified(qualified_name: str) -> str:
    """Extract module name from a uses qualified_name.

    ``'routing.select_evaluator'`` → ``'routing'``
    """
    parts = qualified_name.rsplit(".", 1)
    return parts[0] if len(parts) == 2 else qualified_name


def _component_from_qualified(qualified_name: str) -> str:
    """Extract component name from a uses qualified_name.

    ``'routing.select_evaluator'`` → ``'select_evaluator'``
    """
    return qualified_name.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# Helpers: local name resolution (mirrors namespaces.py logic)
# ---------------------------------------------------------------------------


def _uses_local_name(entry: UsesEntry) -> str:
    """Determine the name by which a uses entry is available in code."""
    if entry.alias:
        return entry.alias
    return entry.qualified_name.rsplit(".", 1)[-1]


def _requires_local_name(entry: RequiresEntry) -> str:
    """Determine the name by which a requires entry is available in code."""
    if entry.alias:
        return entry.alias
    if entry.is_from_import:
        return entry.module_path.rsplit(".", 1)[-1]
    return entry.module_path.split(".")[0]


# ---------------------------------------------------------------------------
# Helpers: cross-layer reachability matrix (M9)
# ---------------------------------------------------------------------------
#
# Layer discipline is one of s0ma's load-bearing architectural promises
# (spec §4.0.1 — intra-module — plus the cross-module extension this
# rule enforces). The matrix below is authoritative: a module at layer
# ``L`` may declare ``uses:`` against a target module whose layer is in
# ``_ALLOWED_TARGET_LAYERS[L]``. Any other combination fires
# ``CROSS_LAYER_DEPENDENCY`` (warning in migration/dev, error in strict
# and release per the severity matrix in :mod:`s0ma_dsl.config`).
#
# Reading the rows:
#   - DOMAIN sees only DOMAIN and FRAMEWORK. Domain models cannot reach
#     application services or presentation/infrastructure adapters; the
#     classic Clean Architecture rule.
#   - APPLICATION can call DOMAIN and FRAMEWORK plus its own layer. It
#     does not reach upward into PRESENTATION or sideways into
#     INFRASTRUCTURE (those are wired in via composition at the
#     boundary).
#   - PRESENTATION may consume DOMAIN, APPLICATION, PRESENTATION, and
#     FRAMEWORK. (No INFRASTRUCTURE — infrastructure adapters are
#     plumbed through APPLICATION services.)
#   - INFRASTRUCTURE mirrors PRESENTATION but for the other side: may
#     consume DOMAIN, APPLICATION, INFRASTRUCTURE, and FRAMEWORK.
#   - FRAMEWORK is the lowest level; it sees only itself.
#
# This is the same matrix the M9 plan calls authoritative. If it ever
# differs from intra-module rules, that is a real model contradiction
# rather than an implementation drift — see the deviation tracker.
_ALLOWED_TARGET_LAYERS: dict[AstLayer, set[AstLayer]] = {
    AstLayer.DOMAIN:         {AstLayer.DOMAIN, AstLayer.FRAMEWORK},
    AstLayer.APPLICATION:    {
        AstLayer.DOMAIN, AstLayer.APPLICATION, AstLayer.FRAMEWORK,
    },
    AstLayer.PRESENTATION:   {
        AstLayer.DOMAIN,
        AstLayer.APPLICATION,
        AstLayer.PRESENTATION,
        AstLayer.FRAMEWORK,
    },
    AstLayer.INFRASTRUCTURE: {
        AstLayer.DOMAIN,
        AstLayer.APPLICATION,
        AstLayer.INFRASTRUCTURE,
        AstLayer.FRAMEWORK,
    },
    AstLayer.FRAMEWORK:      {AstLayer.FRAMEWORK},
}


@component(
    name="S0maDSL_layer_reachability_matrix",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Projects the cross-layer reachability matrix the resolver enforces on uses: "
        "declarations as plain data, one sorted list of reachable layers per layer, so a "
        "build artifact can carry the rule the build applies and the two cannot drift."
    ),
    idempotent=True,
    is_framework=True,
)
def layer_reachability_matrix() -> dict[str, list[str]]:
    """The enforced cross-layer matrix as data: per layer, the layers it may reach.

    This is a reading of ``_ALLOWED_TARGET_LAYERS``, the one table
    :meth:`DependencyResolver._check_cross_layer_dependencies` applies, so
    whatever is projected from here is exactly what ``CROSS_LAYER_DEPENDENCY``
    enforces. Keys and values are the layer names (``"DOMAIN"``,
    ``"APPLICATION"``, ...); every row lists the layer itself, and every row
    lists FRAMEWORK, s0ma's own layer. The self-context companion carries the
    result as ``layer_rules.may_reach`` so a reader of the self-model learns
    which layer may import which without reading the resolver.
    """
    return {
        source.value: sorted(target.value for target in targets)
        for source, targets in sorted(
            _ALLOWED_TARGET_LAYERS.items(), key=lambda item: item[0].value
        )
    }


def _suggest_lower_layer(src_layer: AstLayer, tgt_layer: AstLayer) -> AstLayer:
    """Pick a sensible "move the shared concept down to" suggestion.

    The remediation hint is "move the shared concept to a lower layer";
    "lower" here means "a layer that both source and target can legally
    consume." DOMAIN is reachable from every layer, so it's the safest
    universal floor. We return DOMAIN unless both layers are FRAMEWORK
    (in which case there is no lower layer and the only fix is to
    invert the dependency — the remediation text mentions both
    options).
    """
    if src_layer == AstLayer.FRAMEWORK or tgt_layer == AstLayer.FRAMEWORK:
        return AstLayer.FRAMEWORK
    return AstLayer.DOMAIN


def _lookup_component_visibility(
    module: S0maModule, component_name: str,
) -> Visibility | None:
    """Return the visibility of a named component in ``module``, or ``None``.

    Searches nerves and cells (the two declaration types with a
    ``visibility`` field that ``uses:`` can target). Ganglia carry a
    visibility but are not addressable via ``uses:``; tests have no
    visibility. Returns ``None`` if no nerve or cell with this name
    exists in the module — the caller treats that as "fall through to
    the existing export check," which will produce ``NOT_EXPORTED``
    with the right diagnostic. (M8.)
    """
    for nerve in module.nerves:
        if nerve.name == component_name:
            return nerve.visibility
    for cell in module.cells:
        if cell.name == component_name:
            return cell.visibility
    return None


def _lookup_helper(
    module: S0maModule, name: str,
) -> HelperDecl | None:
    """Return the helper declaration with ``name`` in ``module``, or ``None``.

    M13 (feedback 5–6): helpers are addressable by ``uses:`` only from
    test modules in the project. The dependency resolver uses this
    lookup to detect when a ``uses:`` entry targets a helper, which
    triggers the ``HELPER_PRIVATE_TO_MODULE`` access-control check.
    """
    for helper in module.helpers:
        if helper.name == name:
            return helper
    return None


def _lookup_integration(
    module: S0maModule, name: str,
) -> IntegrationDecl | None:
    """Return the integration declaration with ``name`` in ``module``, or ``None``.

    POST-5 (0.16.0): integration declarations are exempt from the
    ``NOT_EXPORTED`` check — the integration name resolves to a
    module-level marker symbol that bundles the four auto-emitted
    helpers (``get_factory``, ``get_manifest``,
    ``smoke_test_primary``, ``get_smoke_test``). Like ``visibility:
    TEST`` and ``helper`` declarations, integration access has its own
    carve-out path through the export check.
    """
    for integ in module.integrations:
        if integ.name == name:
            return integ
    return None


# ---------------------------------------------------------------------------
# Helpers: body analysis for evidence rules (spec §4.6.3)
# ---------------------------------------------------------------------------


def _pascal_to_snake(name: str) -> str:
    """Convert PascalCase to snake_case.

    ``'LLMAdapter'`` → ``'llm_adapter'``
    ``'MessageGateway'`` → ``'message_gateway'``
    """
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


def _extract_identifiers(body: str) -> set[str]:
    """Extract all identifiers used in Python body text.

    Uses ``ast.parse`` for accuracy, falls back to regex if parsing fails.
    Walks all nested scopes (inner functions, classes) via ``ast.walk``.
    Extracts root names from attribute chains (e.g. ``pytest`` from
    ``pytest.mark.asyncio``).
    """
    if not body or not body.strip():
        return set()
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return set(re.findall(r"\b([a-zA-Z_]\w*)\b", body))

    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
            # Extract root name from attribute chains
            root: ast.expr = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                identifiers.add(root.id)
    return identifiers


def _module_scope_name_refs(body: str) -> set[str]:
    """Names referenced at module-scope EXECUTION positions in a body.

    DSL-M2 (0.8.0, ADR-011 §(c)): the evidence scan behind
    ``DEFERRED_IMPORT_MODULE_SCOPE``. A reference is module-scope iff
    it is NOT lexically inside some def's body — the positions Python
    evaluates while the emitted module (or a class/def statement in
    it) is being created: CONSTANT/TYPE cell assignments, class-scope
    statements (field defaults, base classes), decorator expressions,
    parameter defaults, annotations, and return annotations. Lambda
    BODIES are call-time (excluded); lambda defaults are def-time
    (included). A deferred import cannot serve any of these positions
    — the name is consumed before any injected in-body import could
    run.
    """
    if not body or not body.strip():
        return set()
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return set()

    refs: set[str] = set()

    def collect(node: ast.AST) -> None:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                refs.add(sub.id)

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Decorators, defaults, and annotations execute at def
                # (module/class-creation) time; the BODY is call time
                # — do not descend into it.
                for dec in child.decorator_list:
                    collect(dec)
                args = child.args
                for default in list(args.defaults) + [
                    d for d in args.kw_defaults if d is not None
                ]:
                    collect(default)
                annotated = (
                    list(args.posonlyargs)
                    + list(args.args)
                    + list(args.kwonlyargs)
                    + ([args.vararg] if args.vararg else [])
                    + ([args.kwarg] if args.kwarg else [])
                )
                for arg in annotated:
                    if arg.annotation is not None:
                        collect(arg.annotation)
                if child.returns is not None:
                    collect(child.returns)
            elif isinstance(child, ast.Lambda):
                for default in list(child.args.defaults) + [
                    d for d in child.args.kw_defaults if d is not None
                ]:
                    collect(default)
            else:
                if isinstance(child, ast.Name):
                    refs.add(child.id)
                walk(child)

    walk(tree)
    return refs


def _extract_call_targets(body: str) -> set[str]:
    """Extract all names that appear as direct function call targets.

    Covers ``Name`` calls (``foo()``) and ``Attribute`` calls
    (``obj.foo()``).
    """
    if not body or not body.strip():
        return set()
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return set()

    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                targets.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                targets.add(node.func.attr)
    return targets


def _extract_parameters(body: str) -> set[str]:
    """Extract parameter names from the top-level function definition(s).

    Returns the names of all parameters (excluding ``self``) from
    ``def`` statements at any nesting level in the body.
    """
    if not body or not body.strip():
        return set()
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return set()

    params: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in node.args.args:
                if arg.arg != "self":
                    params.add(arg.arg)
            for arg in node.args.kwonlyargs:
                params.add(arg.arg)
            if node.args.vararg:
                params.add(node.args.vararg.arg)
            if node.args.kwarg:
                params.add(node.args.kwarg.arg)
    return params


def _has_relation_evidence(
    body: str,
    target: str,
    relation: Relation,
) -> bool:
    """Check if body contains evidence matching a specific relation type.

    Evidence rules per spec §4.6.3:
      CALLS       → target appears as a call target, or snake_case
                    version appears as a parameter (injection)
      CONSTRUCTS  → structural relation, exempt from body evidence
      READS       → target appears as any name reference
      CONFIGURES  → target appears as any name reference
      PRODUCES    → target appears as a call target (creating/emitting)
                    or as a return type annotation
      CONSUMES    → target appears as a parameter type annotation or
                    in an isinstance check or as any name reference
    """
    # CONSTRUCTS is structural — the concrete implementation never calls
    # the abstract interface by name (e.g. dependency injection pattern)
    if relation == Relation.CONSTRUCTS:
        return True

    identifiers = _extract_identifiers(body)
    call_targets = _extract_call_targets(body)

    if relation == Relation.CALLS:
        if target in call_targets:
            return True
        snake = _pascal_to_snake(target)
        return snake in _extract_parameters(body)
    elif relation in (Relation.READS, Relation.CONFIGURES):
        return target in identifiers
    elif relation == Relation.PRODUCES:
        # Producer creates/constructs the event or returns it
        return target in call_targets or target in identifiers
    elif relation == Relation.CONSUMES:
        # Consumer receives the event as a parameter, type annotation,
        # or references it (e.g. isinstance check)
        return target in identifiers
    # Derived relations (RAISES, TYPE_USES) don't have authored evidence
    return True


# ---------------------------------------------------------------------------
# DependencyResolver
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_DependencyResolver",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent=(
        "Implements the four-phase cross-module dependency resolution algorithm for validating a "
        "s0ma project."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class DependencyResolver:
    """Four-phase cross-module dependency resolver.

    Validates a collection of parsed ``S0maModule`` objects for
    cross-module consistency: cycle detection, export validation,
    external importability, usage verification, and standalone axon
    validation.
    """

    mode: StrictnessMode = StrictnessMode.DEV
    attribute_budgets: dict[str, str] = field(default_factory=dict)
    """M18 (feedback 5–6): project-level
    ``[tool.s0ma.attribute_budgets]`` mapping. When non-empty, the
    resolver runs an ``ATTRIBUTE_BUDGET_VIOLATION`` pass after the
    other phases. Empty by default so explicit-mode CLI invocations
    that don't have a project handle are unaffected — the field is
    purely descriptive without a budget."""

    test_layering: str = "strict"
    """M-10 (POST-6, 0.16.0): project-level
    ``[tool.s0ma].test_layering`` stance for the cross-module
    layer-reachability check.

    ``"strict"`` (default) — every module's ``uses:`` entries are
    checked against the cross-layer matrix (spec §4.0.2), including
    test-context modules. Pre-0.16.0 behaviour.

    ``"permissive"`` — modules containing at least one ``test``
    declaration are exempt from the check. Production modules (zero
    ``test`` declarations) still get the strict check, so the
    opt-in does not relax the rule for shipped code. The carve-out
    mirrors the M13 helper-access rule: "module with ≥1 test
    declaration" is the trigger.

    Defaulted to ``"strict"`` so explicit-mode CLI invocations that
    don't have a project handle stay at the strict behaviour."""

    def resolve(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str] | None = None,
        *,
        check_imports: bool = True,
    ) -> list[S0maResolutionError]:
        """Run all four phases of cross-module dependency resolution.

        Parameters
        ----------
        modules:
            Dict mapping module names to parsed S0maModules.
        filenames:
            Dict mapping module names to source file paths (for
            diagnostics).  If ``None``, defaults to
            ``"<module_name>.s0ma"``.
        check_imports:
            If ``True``, Phase 3 verifies requires entries are
            importable.  Set to ``False`` in test environments where
            packages may not be installed.

        Returns
        -------
        list[S0maResolutionError]
            All errors and warnings found.
        """
        if filenames is None:
            filenames = {name: f"{name}.s0ma" for name in modules}

        errors: list[S0maResolutionError] = []

        # Phase 1: Module graph + cycle detection (fatal)
        phase1_errors = self._phase1_module_graph(modules, filenames)
        errors.extend(phase1_errors)
        if any(e.code == "CIRCULAR_DEPENDENCY" for e in phase1_errors):
            return errors  # Cycles are fatal — stop resolution

        # Phase 2: Export validation
        errors.extend(self._phase2_export_validation(modules, filenames))

        # DSL-M2 (0.8.0, ADR-011 §(d)): qualified in-project
        # ``depends_on:`` target resolution — project module set,
        # declaration existence, export surface.
        errors.extend(
            self._check_qualified_depends_on(modules, filenames)
        )

        # Phase 3: External validation
        if check_imports:
            errors.extend(
                self._phase3_external_validation(modules, filenames)
            )

        # Phase 4: Usage verification
        errors.extend(self._phase4_usage_verification(modules, filenames))

        # DSL-M2 (0.8.0, ADR-011 §(c)): deferred-import contracts —
        # DUPLICATE_REQUIRES_ENTRY (one failure-time choice per
        # target) and DEFERRED_IMPORT_MODULE_SCOPE (a deferred name
        # consumed at a module-scope execution position).
        errors.extend(
            self._check_deferred_requires_contracts(modules, filenames)
        )

        # Standalone axon cross-module validation
        errors.extend(
            self._validate_standalone_axons_cross_module(modules, filenames)
        )

        # Cross-module abstract interface validation (MS 11b)
        errors.extend(
            self._validate_cross_module_abstract_interfaces(modules, filenames)
        )

        # DSL-M1 (0.8.0, ADR-011 §(b)): project-scope serves_as
        # uniqueness — one flat served-name namespace across the build.
        errors.extend(
            self._check_serves_as_collisions(modules, filenames)
        )

        # Release-mode: test coverage for PUBLIC nerves
        errors.extend(
            self._check_release_test_coverage(modules, filenames)
        )

        # M9: cross-module ``uses:`` layer enforcement
        errors.extend(
            self._check_cross_layer_dependencies(modules, filenames)
        )

        # M18 (feedback 5–6): project-level
        # ``[tool.s0ma.attribute_budgets]`` enforcement. Short-circuits
        # when no budgets are configured so projects that don't opt in
        # are unaffected.
        if self.attribute_budgets:
            from s0ma_dsl.semantic.attribute_budgets import (
                check_attribute_budgets,
            )
            errors.extend(check_attribute_budgets(
                modules,
                attribute_budgets=self.attribute_budgets,
                mode=self.mode,
                filenames=filenames,
            ))

        return errors

    # -------------------------------------------------------------------
    # Phase 1: Module graph construction and cycle detection
    # -------------------------------------------------------------------

    def _phase1_module_graph(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str],
    ) -> list[S0maResolutionError]:
        """Build directed module graph from uses and detect cycles.

        Each module's ``uses`` entries create edges to target modules.
        Cycles are detected via DFS with three-colour marking and
        path tracking.  Fatal error — resolution cannot continue.
        """
        errors: list[S0maResolutionError] = []

        # Build adjacency list (deterministic ordering)
        graph: dict[str, list[str]] = {name: [] for name in modules}
        for mod_name in sorted(modules):
            mod = modules[mod_name]
            seen_targets: set[str] = set()
            for use in mod.module.uses:
                target_mod = _module_from_qualified(use.qualified_name)
                if target_mod in modules and target_mod not in seen_targets:
                    graph[mod_name].append(target_mod)
                    seen_targets.add(target_mod)
            # DSL-M2 (0.8.0, ADR-011 §(d) rule 4): qualified inline
            # ``depends_on:`` targets join module-graph construction
            # with the same fatal-cycle rule as ``uses:`` — a cycle in
            # declared architecture edges is structural entanglement
            # regardless of emission.
            for decl in mod.all_declarations:
                for axon in getattr(decl, "depends_on", ()):
                    if "." not in axon.target:
                        continue
                    target_mod = axon.target.split(".", 1)[0]
                    if (
                        target_mod in modules
                        and target_mod != mod_name
                        and target_mod not in seen_targets
                    ):
                        graph[mod_name].append(target_mod)
                        seen_targets.add(target_mod)
            graph[mod_name].sort()

        # DFS cycle detection with three-colour marking
        WHITE, GRAY, BLACK = 0, 1, 2  # noqa: N806 — algorithmic-constant convention (CLRS three-colour DFS)
        colour: dict[str, int] = dict.fromkeys(graph, WHITE)

        def dfs(node: str, path: list[str]) -> None:
            colour[node] = GRAY
            path.append(node)
            for neighbour in graph[node]:
                if colour[neighbour] == GRAY:
                    # Found cycle — extract cycle path
                    cycle_start = path.index(neighbour)
                    cycle = path[cycle_start:] + [neighbour]
                    errors.append(S0maResolutionError(
                        code="CIRCULAR_DEPENDENCY",
                        message=(
                            f"Circular dependency detected: "
                            f"{' → '.join(cycle)}"
                        ),
                        file=filenames.get(node, f"{node}.s0ma"),
                        line=1,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Break the dependency cycle by removing one "
                            f"of the uses entries (or qualified "
                            f"depends_on targets) in the chain: "
                            f"{' → '.join(cycle)}. Consider whether a "
                            f"dependency can be inverted or mediated "
                            f"through a shared module."
                        ),
                        context={
                            "cycle": cycle,
                            "detected_at": node,
                        },
                    ))
                elif colour[neighbour] == WHITE:
                    dfs(neighbour, path)
            path.pop()
            colour[node] = BLACK

        for node in sorted(graph):  # Sorted for determinism
            if colour[node] == WHITE:
                dfs(node, [])

        return errors

    # -------------------------------------------------------------------
    # Phase 2: Export validation
    # -------------------------------------------------------------------

    def _phase2_export_validation(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str],
    ) -> list[S0maResolutionError]:
        """Validate that every uses reference targets an exported component.

        For each ``uses`` entry in each module:
        1. The target module must exist in the project → DOES_NOT_EXIST
        2. If the target component has ``visibility: TEST`` (M8 / ADR-008):
           - The source module must contain at least one ``test`` declaration,
             otherwise → TEST_VISIBILITY_VIOLATION.
           - TEST components are exempt from the export check; they are not
             part of the public export surface by design.
        3. Otherwise the component must be in the target module's
           ``exports:`` list → NOT_EXPORTED.
        """
        errors: list[S0maResolutionError] = []

        for mod_name in sorted(modules):
            mod = modules[mod_name]
            filename = filenames.get(mod_name, f"{mod_name}.s0ma")

            for use in mod.module.uses:
                target_mod = _module_from_qualified(use.qualified_name)
                target_comp = _component_from_qualified(use.qualified_name)
                line = use.location.start_line if use.location else 0

                if target_mod not in modules:
                    errors.append(S0maResolutionError(
                        code="DOES_NOT_EXIST",
                        message=(
                            f"Module '{mod_name}' uses "
                            f"'{use.qualified_name}', but module "
                            f"'{target_mod}' does not exist in the "
                            f"project."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Ensure module '{target_mod}' exists as a "
                            f".s0ma file in the project, or remove "
                            f"'{use.qualified_name}' from this module's "
                            f"uses list."
                        ),
                        context={
                            "source_module": mod_name,
                            "target_module": target_mod,
                            "target_component": target_comp,
                        },
                    ))
                    continue

                target_module = modules[target_mod]

                # M13 (feedback 5–6): helpers are module-private functions.
                # A ``uses:`` entry that targets a helper is allowed only
                # from a module that contains at least one ``test``
                # declaration (mirroring the ``visibility: TEST`` carve-out
                # from M8). Production cross-module access raises
                # ``HELPER_PRIVATE_TO_MODULE``. Helpers are also exempt
                # from the export check — they are never in the public
                # surface by construction.
                #
                # POST-4c (0.15.0): ``exports_helpers:`` widens the
                # reachability surface but NOT the access-control surface
                # — production consumers still hit
                # ``HELPER_PRIVATE_TO_MODULE`` even when the helper is
                # listed in the source module's ``exports_helpers:``.
                # Test-context consumers continue to qualify (the
                # ``uses:`` entry resolves cleanly). The
                # ``re_exported`` context field lets diagnostics-friendly
                # tooling distinguish the two cases.
                target_helper = _lookup_helper(target_module, target_comp)
                if target_helper is not None:
                    re_exported = (
                        target_comp in target_module.module.exports_helpers
                    )
                    if not mod.tests:
                        errors.append(S0maResolutionError(
                            code="HELPER_PRIVATE_TO_MODULE",
                            message=(
                                f"Module '{mod_name}' uses "
                                f"'{use.qualified_name}', but "
                                f"'{target_comp}' is a helper declaration "
                                f"in module '{target_mod}'. Helpers are "
                                f"module-private — production modules "
                                f"cannot consume them across module "
                                f"boundaries, even when listed in the "
                                f"source module's `exports_helpers:`. "
                                f"Test modules in any project module may "
                                f"import a helper via uses:."
                            ),
                            file=filename,
                            line=line,
                            column=0,
                            severity="error",
                            remediation=(
                                f"Either (a) move '{target_comp}' from "
                                f"'helper' to a 'nerve' declaration in "
                                f"module '{target_mod}' and add it to "
                                f"that module's exports list, or (b) add "
                                f"a test declaration to module "
                                f"'{mod_name}' if this is a test-only "
                                f"consumer, or (c) inline the helper's "
                                f"behaviour in module '{mod_name}'."
                            ),
                            context={
                                "source_module": mod_name,
                                "target_module": target_mod,
                                "target_component": target_comp,
                                "target_kind": "helper",
                                "re_exported": re_exported,
                            },
                        ))
                    # Helpers are not exported; skip the export check
                    # whether or not the consumer qualifies as a test
                    # consumer.
                    continue

                # POST-5 (0.16.0): integration declarations are exempt
                # from the ``NOT_EXPORTED`` check. The integration's
                # name resolves to a module-level marker symbol that
                # bundles the four auto-emitted helpers; the codegen
                # emits the symbol unconditionally, so the export check
                # would always fail (the integration name is not in
                # ``exports:`` by design). Cross-module consumers reach
                # an integration the same way they reach any other
                # public surface — by naming it in their ``uses:`` list.
                # The four auto-emitted helpers carry their own
                # ``module_scoped=True`` registry entries.
                target_integration = _lookup_integration(
                    target_module, target_comp,
                )
                if target_integration is not None:
                    # Integration is reachable; skip the export check.
                    continue

                # M8: resolve the target component's visibility (if any).
                target_visibility = _lookup_component_visibility(
                    target_module, target_comp,
                )

                # M8: TEST-visibility components are reachable cross-module
                # only from modules that declare at least one test. They
                # are also exempt from the export check — TEST components
                # are not in the public export surface by design.
                if target_visibility == Visibility.TEST:
                    if not mod.tests:
                        errors.append(S0maResolutionError(
                            code="TEST_VISIBILITY_VIOLATION",
                            message=(
                                f"Module '{mod_name}' uses "
                                f"'{use.qualified_name}', but "
                                f"'{target_comp}' has visibility "
                                f"TEST. TEST-visibility components are "
                                f"reachable cross-module only from "
                                f"modules that contain at least one "
                                f"test declaration."
                            ),
                            file=filename,
                            line=line,
                            column=0,
                            severity="error",
                            remediation=(
                                f"Either add a test declaration to "
                                f"module '{mod_name}' (so it qualifies "
                                f"as a test consumer), or change the "
                                f"visibility of '{target_comp}' in "
                                f"module '{target_mod}' to PUBLIC and "
                                f"add it to that module's exports list."
                            ),
                            context={
                                "source_module": mod_name,
                                "target_module": target_mod,
                                "target_component": target_comp,
                                "target_visibility": "TEST",
                            },
                        ))
                    # TEST components are not exported; skip the export
                    # check unconditionally (whether or not this is a
                    # legitimate test consumer).
                    continue

                # Check component is exported by target module
                if target_comp not in target_module.module.exports:
                    errors.append(S0maResolutionError(
                        code="NOT_EXPORTED",
                        message=(
                            f"Module '{mod_name}' uses "
                            f"'{use.qualified_name}', but "
                            f"'{target_comp}' is not exported by "
                            f"module '{target_mod}'."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Add '{target_comp}' to the exports list "
                            f"of module '{target_mod}', or remove "
                            f"'{use.qualified_name}' from this module's "
                            f"uses list."
                        ),
                        context={
                            "source_module": mod_name,
                            "target_module": target_mod,
                            "target_component": target_comp,
                            "available_exports": list(
                                target_module.module.exports
                            ),
                        },
                    ))

        return errors

    # -------------------------------------------------------------------
    # DSL-M2 (0.8.0, ADR-011 §(d)): qualified depends_on resolution
    # -------------------------------------------------------------------

    def _check_qualified_depends_on(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str],
    ) -> list[S0maResolutionError]:
        """Resolve qualified (``module.declaration``) depends_on targets.

        Resolution rules (ADR-011 §(d)):

        1. The dotted target's module segment must name a module in the
           project's module set, else ``DOES_NOT_EXIST`` naming the
           qualified form as authored and listing the project's module
           names. Single-module/synthetic invocations fail here by
           construction; their remediation says qualified targets
           require a ``[tool.s0ma]`` project build.
        2. The declaration segment must be a declaration in the target
           module, else ``DOES_NOT_EXIST`` (qualified variant of the
           in-module message).
        3. Cross-module targets must appear in the target module's
           ``exports:`` — the same public-surface rule as ``uses:``
           Phase 2, reusing ``NOT_EXPORTED``.
        6. A self-module-qualified target (``m.x`` authored inside
           ``m``) resolves as the local declaration — idempotent,
           permitted, and exempt from the export rule exactly like a
           bare local target.

        (Rule 4 — fatal cycles — lives in ``_phase1_module_graph``;
        rule 5 — the cross-layer matrix — in
        ``_check_cross_layer_dependencies``; evidence rules — Phase 4c.)
        """
        errors: list[S0maResolutionError] = []

        for mod_name in sorted(modules):
            mod = modules[mod_name]
            filename = filenames.get(mod_name, f"{mod_name}.s0ma")

            for decl in mod.all_declarations:
                parent_name = getattr(decl, "name", "<unknown>")
                for axon in getattr(decl, "depends_on", ()):
                    if "." not in axon.target:
                        continue
                    target_mod, target_decl = axon.target.split(".", 1)
                    line = (
                        axon.location.start_line
                        if axon.location
                        else (
                            decl.location.start_line
                            if decl.location
                            else 0
                        )
                    )

                    # Rule 1 — module in the project module set.
                    if target_mod not in modules:
                        if len(modules) == 1:
                            remediation = (
                                f"Qualified depends_on targets resolve "
                                f"against the project's module set — "
                                f"run this check/build as a "
                                f"[tool.s0ma] project that includes "
                                f"module '{target_mod}', or use a "
                                f"local declaration name."
                            )
                        else:
                            remediation = (
                                f"Ensure module '{target_mod}' exists "
                                f"as a .s0ma file in the project, or "
                                f"fix the qualified target. Project "
                                f"modules: "
                                f"{', '.join(sorted(modules))}."
                            )
                        errors.append(S0maResolutionError(
                            code="DOES_NOT_EXIST",
                            message=(
                                f"Inline dependency target "
                                f"'{axon.target}' in '{parent_name}' "
                                f"(module '{mod_name}') names module "
                                f"'{target_mod}', which does not "
                                f"exist in the project."
                            ),
                            file=filename,
                            line=line,
                            column=0,
                            severity="error",
                            remediation=remediation,
                            context={
                                "source": parent_name,
                                "source_module": mod_name,
                                "target": axon.target,
                                "target_module": target_mod,
                                "project_modules": sorted(modules),
                            },
                        ))
                        continue

                    # Rule 2 — declaration exists in the target module.
                    target_module = modules[target_mod]
                    declared_names = {
                        getattr(d, "name", None)
                        for d in target_module.all_declarations
                    }
                    declared_names.discard(None)
                    if target_decl not in declared_names:
                        errors.append(S0maResolutionError(
                            code="DOES_NOT_EXIST",
                            message=(
                                f"Inline dependency target "
                                f"'{axon.target}' in '{parent_name}' "
                                f"(module '{mod_name}') does not "
                                f"exist: module '{target_mod}' has no "
                                f"declaration named '{target_decl}'."
                            ),
                            file=filename,
                            line=line,
                            column=0,
                            severity="error",
                            remediation=(
                                f"Ensure '{target_decl}' is declared "
                                f"in module '{target_mod}'. Check "
                                f"spelling — the qualified form is "
                                f"module.declaration."
                            ),
                            context={
                                "source": parent_name,
                                "source_module": mod_name,
                                "target": axon.target,
                                "target_module": target_mod,
                                "target_component": target_decl,
                            },
                        ))
                        continue

                    # Rule 6 — self-module-qualified targets resolve as
                    # the local declaration; no export demand.
                    if target_mod == mod_name:
                        continue

                    # Rule 3 — public-surface rule, reusing NOT_EXPORTED.
                    if target_decl not in target_module.module.exports:
                        errors.append(S0maResolutionError(
                            code="NOT_EXPORTED",
                            message=(
                                f"Inline dependency target "
                                f"'{axon.target}' in '{parent_name}' "
                                f"(module '{mod_name}') is not "
                                f"exported by module '{target_mod}'."
                            ),
                            file=filename,
                            line=line,
                            column=0,
                            severity="error",
                            remediation=(
                                f"Add '{target_decl}' to the exports "
                                f"list of module '{target_mod}', or "
                                f"point the depends_on entry at an "
                                f"exported declaration."
                            ),
                            context={
                                "source": parent_name,
                                "source_module": mod_name,
                                "target_module": target_mod,
                                "target_component": target_decl,
                                "available_exports": list(
                                    target_module.module.exports
                                ),
                            },
                        ))

        return errors

    # -------------------------------------------------------------------
    # Phase 3: External validation
    # -------------------------------------------------------------------

    def _phase3_external_validation(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str],
    ) -> list[S0maResolutionError]:
        """Verify that requires entries are importable.

        Uses ``importlib.util.find_spec`` to check for package
        availability without actually importing (no side effects).
        Severity follows strictness mode.
        """
        errors: list[S0maResolutionError] = []
        severity = get_severity("MISSING_PACKAGE", self.mode)
        if severity is None:
            return errors

        for mod_name in sorted(modules):
            mod = modules[mod_name]
            filename = filenames.get(mod_name, f"{mod_name}.s0ma")

            # DSL-M2 (0.8.0, ADR-011 §(c)): Phase-3 importability
            # applies to ``deferred_requires:`` entries unchanged —
            # deferral moves the import to call time, it does not
            # weaken the static dependency record. (Severity follows
            # mode: warning in migration/dev, which is what lets the
            # broken-dependency fixture build and prove the per-call
            # failure semantics.) M1 (0.13.0, batch-01c): the two import
            # fields are swept separately so a corrected block names the
            # right declaration; each is consolidated per module (one
            # block dropping every removable entry, not one per error).
            for field_name, field_entries in (
                ("requires", list(mod.module.requires)),
                ("deferred_requires", list(mod.module.deferred_requires)),
            ):
                # First pass: which entries are unresolvable, and does the
                # import path name a s0ma module in this project (→ the
                # entry belongs in `uses:`, an ambiguity the checker will
                # NOT paper over with a removal block — spec (e)).
                missing: list[tuple[RequiresEntry, str, bool]] = []
                for req in field_entries:
                    # Determine the top-level package to check
                    if req.is_from_import:
                        # from uuid import UUID → check 'uuid'
                        parts = req.module_path.rsplit(".", 1)
                        import_path = (
                            parts[0] if len(parts) == 2 else req.module_path
                        )
                    else:
                        # import os.path → check 'os'
                        import_path = req.module_path.split(".")[0]

                    try:
                        spec = importlib.util.find_spec(import_path)
                        if spec is None:
                            raise ImportError(
                                f"No module named '{import_path}'"
                            )
                    except (ImportError, ModuleNotFoundError, ValueError):
                        is_s0ma_module = import_path in modules
                        missing.append((req, import_path, is_s0ma_module))

                if not missing:
                    continue

                # M1: the consolidated corrected block drops every
                # *removable* (non-s0ma-module) unresolvable entry at once.
                # s0ma-module entries are left in the rendered remainder —
                # their fix is a cross-declaration move (see the guard
                # remediation below), not a silent drop.
                removable_ids = {
                    id(req) for req, _ip, is_mod in missing if not is_mod
                }
                remainder = [
                    req for req in field_entries if id(req) not in removable_ids
                ]
                corrected_block = (
                    render_requires_block(remainder, field=field_name)
                    if removable_ids
                    else None
                )
                drop_word = (
                    "entries" if len(removable_ids) > 1 else "entry"
                )

                for req, import_path, is_s0ma_module in missing:
                    line = req.location.start_line if req.location else 0
                    if is_s0ma_module:
                        remediation = (
                            f"'{import_path}' is a s0ma module in this "
                            f"project, not an installed package — a s0ma "
                            f"component belongs in `uses:` (e.g. "
                            f"`uses: [{req.module_path}]`), not "
                            f"`{field_name}:`. The checker does not emit a "
                            f"verbatim corrected block because the fix "
                            f"spans two declarations (drop it from "
                            f"`{field_name}:` and add it to `uses:`)."
                        )
                        suggested = None
                    else:
                        remediation = (
                            f"Install the package providing "
                            f"'{import_path}', or remove "
                            f"'{req.module_path}' from the `{field_name}:` "
                            f"list (the suggested block below drops the "
                            f"unresolvable {drop_word})."
                        )
                        suggested = corrected_block
                    errors.append(S0maResolutionError(
                        code="MISSING_PACKAGE",
                        message=(
                            f"Module '{mod_name}' requires "
                            f"'{req.module_path}', but '{import_path}' "
                            f"could not be found."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity=severity,
                        remediation=remediation,
                        context={
                            "module": mod_name,
                            "requires": req.module_path,
                            "import_path": import_path,
                        },
                        suggested_declaration=suggested,
                    ))

        return errors

    # -------------------------------------------------------------------
    # Phase 4: Usage verification
    # -------------------------------------------------------------------

    def _phase4_usage_verification(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str],
    ) -> list[S0maResolutionError]:
        """Detect vestigial imports and verify relation-specific evidence.

        Checks:
        1. Module-level ``uses`` entries are referenced in bodies or
           DSL metadata fields. The "is this name used?" check
           computes a *closure* (POST-10a): a name counts as used if
           it appears in any code body **or** in any
           ``depends_on:`` / ``raises:`` / ``tests:`` target **or**
           in any standalone axon target. A name reachable through
           any of those edges is alive — single-pass union semantics.
        2. Module-level ``requires`` entries are referenced in bodies.
           ``runtime_only_requires:`` entries (POST-10b) are exempt
           from this check; they emit the import line on the
           generated module but never trigger ``VESTIGIAL_IMPORT``.
        3. Inline ``depends_on`` entries have relation-specific body
           evidence per spec §4.6.3.
        """
        errors: list[S0maResolutionError] = []
        vestigial_severity = get_severity("VESTIGIAL_IMPORT", self.mode)
        if vestigial_severity is None:
            return errors

        for mod_name in sorted(modules):
            mod = modules[mod_name]
            filename = filenames.get(mod_name, f"{mod_name}.s0ma")

            # POST-10a (0.16.0): compute the cross-field reference
            # closure once per module — the union of every name
            # appearing in (a) any authored body, (b) any
            # ``depends_on:`` / ``raises:`` / ``tests:`` metadata
            # field, or (c) any standalone axon target. The closure
            # is the single source of truth for the 4a vestigial-uses
            # check below: a ``uses:`` entry is vestigial iff its
            # local name is absent from *every* member of the
            # closure. Pre-POST-10a the union was effectively the
            # same shape but split across two reads (body identifiers
            # vs metadata names) — folding them together makes the
            # invariant explicit and prevents future drift between
            # the two sources.
            all_body_identifiers: set[str] = set()
            all_call_targets: set[str] = set()
            for decl in mod.all_declarations:
                body = getattr(decl, "body", None)
                if body:
                    all_body_identifiers.update(_extract_identifiers(body))
                    all_call_targets.update(_extract_call_targets(body))

            metadata_referenced_names: set[str] = set()
            for decl in mod.all_declarations:
                for axon in getattr(decl, "depends_on", ()):
                    metadata_referenced_names.add(axon.target)
                    # DSL-M2 (0.8.0, ADR-011 §(d)): a qualified target
                    # also keeps the LEAF name alive in the closure —
                    # bodies (and ``uses:`` locals) reference the leaf,
                    # never the dotted form.
                    if "." in axon.target:
                        metadata_referenced_names.add(
                            axon.target.rsplit(".", 1)[-1]
                        )
                for exc in getattr(decl, "raises", ()):
                    metadata_referenced_names.add(exc)
                for test_target in getattr(decl, "tests", ()):
                    metadata_referenced_names.add(test_target)
                # POST-10a extension: ``mocks:`` targets on test
                # declarations also count — a test that mocks a
                # nerve refers to it even when the body never
                # imports the symbol directly.
                for mock_target in getattr(decl, "mocks", ()):
                    metadata_referenced_names.add(mock_target)
            for axon in mod.axons:
                metadata_referenced_names.add(axon.target)

            # Single closure: the union the 4a check consults.
            usage_closure: set[str] = (
                all_body_identifiers | metadata_referenced_names
            )
            # Retain the legacy alias so reads further down keep
            # their meaning. (The metadata-only set,
            # ``metadata_referenced_names``, is still read directly
            # by the diagnostic remediation text below to explain
            # *why* a name is live.)
            all_identifiers = all_body_identifiers

            # --- 4a: Vestigial uses detection ---
            for use in mod.module.uses:
                local = _uses_local_name(use)
                if local not in usage_closure:
                    line = use.location.start_line if use.location else 0
                    errors.append(S0maResolutionError(
                        code="VESTIGIAL_IMPORT",
                        message=(
                            f"uses entry '{use.qualified_name}' "
                            f"(as '{local}') has no evidence of use "
                            f"in any code body or DSL metadata field."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity=vestigial_severity,
                        remediation=(
                            f"Remove '{use.qualified_name}' from the "
                            f"uses list, or add code that references "
                            f"'{local}'."
                        ),
                        context={
                            "module": mod_name,
                            "uses": use.qualified_name,
                            "local_name": local,
                        },
                    ))

            # --- 4b: Vestigial requires detection ---
            for req in mod.module.requires:
                local = _requires_local_name(req)
                if local not in all_identifiers:
                    line = req.location.start_line if req.location else 0
                    errors.append(S0maResolutionError(
                        code="VESTIGIAL_IMPORT",
                        message=(
                            f"requires entry '{req.module_path}' "
                            f"(as '{local}') has no evidence of use "
                            f"in any code body."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity=vestigial_severity,
                        remediation=(
                            f"Remove '{req.module_path}' from the "
                            f"requires list."
                        ),
                        context={
                            "module": mod_name,
                            "requires": req.module_path,
                            "local_name": local,
                        },
                    ))

            # --- 4b2: Vestigial soft_requires detection ---
            for req in mod.module.soft_requires:
                local = _requires_local_name(req)
                if local not in all_identifiers:
                    line = req.location.start_line if req.location else 0
                    errors.append(S0maResolutionError(
                        code="VESTIGIAL_IMPORT",
                        message=(
                            f"soft_requires entry '{req.module_path}' "
                            f"(as '{local}') has no evidence of use "
                            f"in any code body."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity=vestigial_severity,
                        remediation=(
                            f"Remove '{req.module_path}' from the "
                            f"soft_requires list."
                        ),
                        context={
                            "module": mod_name,
                            "soft_requires": req.module_path,
                            "local_name": local,
                        },
                    ))

            # --- 4b3: Vestigial deferred_requires detection ---
            # DSL-M2 (0.8.0, ADR-011 §(c)): deferred entries use the
            # SAME body-reference evidence rule as ``requires:``
            # entries. An unconsumed deferred entry is vestigial by
            # construction — no import would be emitted anywhere. They
            # are NOT ``runtime_only_requires``-exempt: a deferred
            # entry with no consuming body is always a mistake.
            for req in mod.module.deferred_requires:
                local = _requires_local_name(req)
                if local not in all_identifiers:
                    line = req.location.start_line if req.location else 0
                    errors.append(S0maResolutionError(
                        code="VESTIGIAL_IMPORT",
                        message=(
                            f"deferred_requires entry "
                            f"'{req.module_path}' (as '{local}') has "
                            f"no evidence of use in any code body."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity=vestigial_severity,
                        remediation=(
                            f"Remove '{req.module_path}' from the "
                            f"deferred_requires list."
                        ),
                        context={
                            "module": mod_name,
                            "deferred_requires": req.module_path,
                            "local_name": local,
                        },
                    ))

            # --- 4c: Inline depends_on evidence checking ---
            for decl in mod.all_declarations:
                body = getattr(decl, "body", None)
                parent_name = getattr(decl, "name", "<unknown>")

                for axon in getattr(decl, "depends_on", ()):
                    # DSL-M2 (0.8.0, ADR-011 §(d) rule 8): evidence
                    # rules are target-location-agnostic — the
                    # relation determines the evidence; for qualified
                    # targets the body references the LEAF name (the
                    # dotted form is a header-side spelling, never a
                    # Python binding).
                    evidence_name = (
                        axon.target.rsplit(".", 1)[-1]
                        if "." in axon.target
                        else axon.target
                    )
                    if body and not _has_relation_evidence(
                        body, evidence_name, axon.relation
                    ):
                        axon_line = (
                            axon.location.start_line
                            if axon.location
                            else (
                                decl.location.start_line
                                if decl.location
                                else 0
                            )
                        )
                        evidence_type = (
                            "calls"
                            if axon.relation
                            in (Relation.CALLS, Relation.CONSTRUCTS)
                            else "references"
                        )
                        errors.append(S0maResolutionError(
                            code="VESTIGIAL_IMPORT",
                            message=(
                                f"Inline dependency '{parent_name}' → "
                                f"'{axon.target}' with relation "
                                f"{axon.relation.value} has no matching "
                                f"evidence in the body."
                            ),
                            file=filename,
                            line=axon_line,
                            column=0,
                            severity=vestigial_severity,
                            remediation=(
                                f"Add code in '{parent_name}' that "
                                f"{evidence_type} '{axon.target}', or "
                                f"remove the depends_on entry."
                            ),
                            context={
                                "source": parent_name,
                                "target": axon.target,
                                "relation": axon.relation.value,
                                "evidence_type": evidence_type,
                            },
                        ))

        return errors

    # -------------------------------------------------------------------
    # DSL-M2 (0.8.0, ADR-011 §(c)): deferred-import contracts
    # -------------------------------------------------------------------

    def _check_deferred_requires_contracts(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str],
    ) -> list[S0maResolutionError]:
        """Validate ``deferred_requires:`` against its two contracts.

        1. ``DUPLICATE_REQUIRES_ENTRY`` (error in every mode): the same
           import target appears in ``deferred_requires:`` AND another
           requires-family list of the same module header. Softness at
           module top and deferral to call time are different
           failure-time choices — pick one.
        2. ``DEFERRED_IMPORT_MODULE_SCOPE`` (error in every mode): a
           deferred name is referenced from a module-scope execution
           position — a CONSTANT/TYPE cell body, a class body at class
           scope (field defaults execute at class creation), or a
           decorator expression / parameter default / annotation on an
           emitted def. Deferring those imports is semantically
           impossible: the name is consumed at import time, before any
           injected in-body import could run.
        """
        errors: list[S0maResolutionError] = []

        for mod_name in sorted(modules):
            mod = modules[mod_name]
            header = mod.module
            if not header.deferred_requires:
                continue
            filename = filenames.get(mod_name, f"{mod_name}.s0ma")
            header_line = (
                header.location.start_line if header.location else 1
            )

            duplicate_severity = get_severity(
                "DUPLICATE_REQUIRES_ENTRY", self.mode
            )
            if duplicate_severity is not None:
                other_lists: dict[str, str] = {}
                for list_name, entries in (
                    ("requires", header.requires),
                    ("soft_requires", header.soft_requires),
                    (
                        "runtime_only_requires",
                        header.runtime_only_requires,
                    ),
                ):
                    for entry in entries:
                        other_lists.setdefault(entry.module_path, list_name)
                for entry in header.deferred_requires:
                    other = other_lists.get(entry.module_path)
                    if other is None:
                        continue
                    line = (
                        entry.location.start_line
                        if entry.location
                        else header_line
                    )
                    errors.append(S0maResolutionError(
                        code="DUPLICATE_REQUIRES_ENTRY",
                        message=(
                            f"Import target '{entry.module_path}' in "
                            f"module '{mod_name}' appears in both "
                            f"'deferred_requires:' and '{other}:'. "
                            f"Module-top import and call-time deferral "
                            f"are different failure-time choices — one "
                            f"target, one list."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity=duplicate_severity,
                        remediation=(
                            f"Remove '{entry.module_path}' from either "
                            f"'deferred_requires:' or '{other}:'. Keep "
                            f"it in '{other}:' for a module-top import "
                            f"that fails at import time; keep it in "
                            f"'deferred_requires:' for a call-time "
                            f"import with per-call failure semantics."
                        ),
                        context={
                            "module": mod_name,
                            "target": entry.module_path,
                            "other_list": other,
                        },
                    ))

            module_scope_severity = get_severity(
                "DEFERRED_IMPORT_MODULE_SCOPE", self.mode
            )
            if module_scope_severity is None:
                continue
            deferred_locals: dict[str, RequiresEntry] = {}
            for entry in header.deferred_requires:
                deferred_locals.setdefault(
                    _requires_local_name(entry), entry
                )
            for decl in mod.all_declarations:
                body = getattr(decl, "body", None)
                if not body:
                    continue
                module_scope_refs = _module_scope_name_refs(body)
                decl_name = getattr(decl, "name", "<unknown>")
                decl_line = (
                    decl.location.start_line if decl.location else 0
                )
                for local in sorted(deferred_locals):
                    if local not in module_scope_refs:
                        continue
                    entry = deferred_locals[local]
                    errors.append(S0maResolutionError(
                        code="DEFERRED_IMPORT_MODULE_SCOPE",
                        message=(
                            f"Deferred import '{entry.module_path}' "
                            f"(as '{local}') is consumed at a "
                            f"module-scope execution position in "
                            f"'{decl_name}' (module '{mod_name}'). "
                            f"Module-scope positions — cell bodies, "
                            f"class-scope statements, decorator "
                            f"expressions, parameter defaults, "
                            f"annotations — execute at import time, "
                            f"before any injected in-body import "
                            f"could run."
                        ),
                        file=filename,
                        line=decl_line,
                        column=0,
                        severity=module_scope_severity,
                        remediation=(
                            f"Move '{entry.module_path}' back to the "
                            f"'requires:' list, or restructure "
                            f"'{decl_name}' so the name is consumed "
                            f"inside a function body."
                        ),
                        context={
                            "module": mod_name,
                            "declaration": decl_name,
                            "target": entry.module_path,
                            "local_name": local,
                        },
                    ))

        return errors

    # -------------------------------------------------------------------
    # Standalone axon cross-module validation
    # -------------------------------------------------------------------

    def _validate_standalone_axons_cross_module(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str],
    ) -> list[S0maResolutionError]:
        """Validate standalone axons for cross-module consistency.

        Checks:
        1. Target is from a ``uses`` entry (cross-module reference) —
           intra-module deps should use inline ``depends_on``.
        2. No duplicate with inline ``depends_on`` entries.
        3. No duplicate among standalone axons themselves.
        4. Source body has evidence matching the declared relation.
        """
        errors: list[S0maResolutionError] = []
        dup_severity = get_severity("DUPLICATE_AXON", self.mode)
        vestigial_severity = get_severity("VESTIGIAL_IMPORT", self.mode)

        for mod_name in sorted(modules):
            mod = modules[mod_name]
            filename = filenames.get(mod_name, f"{mod_name}.s0ma")
            ns, _ = build_namespaces(mod, filename)

            # Collect inline depends_on triples for duplicate checking
            inline_deps: set[tuple[str, str, str]] = set()
            for decl in mod.all_declarations:
                parent_name = getattr(decl, "name", None)
                if parent_name is None:
                    continue
                for axon in getattr(decl, "depends_on", ()):
                    inline_deps.add((
                        parent_name,
                        axon.target,
                        axon.relation.value,
                    ))

            # Track standalone axon triples for self-duplication
            standalone_seen: set[tuple[str, str, str]] = set()

            for axon in mod.axons:
                line = axon.location.start_line if axon.location else 0

                # --- Check target is from uses (cross-module) ---
                entry = ns.lookup_component_ref(axon.target)
                if entry is not None and entry.origin == "local":
                    errors.append(S0maResolutionError(
                        code="DOES_NOT_EXIST",
                        message=(
                            f"Standalone axon target '{axon.target}' "
                            f"is a local declaration. Standalone axons "
                            f"are for cross-module dependencies only."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Use an inline depends_on entry within "
                            f"'{axon.source}' instead of a standalone "
                            f"axon for intra-module dependencies."
                        ),
                        context={
                            "source": axon.source,
                            "target": axon.target,
                            "target_origin": "local",
                        },
                    ))

                # --- Check for duplicate with inline depends_on ---
                triple = (
                    axon.source,
                    axon.target,
                    axon.relation.value,
                )
                if triple in inline_deps and dup_severity is not None:
                    errors.append(S0maResolutionError(
                        code="DUPLICATE_AXON",
                        message=(
                            f"Standalone axon '{axon.source} → "
                            f"{axon.target}' ({axon.relation.value}) "
                            f"duplicates an inline depends_on entry."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity=dup_severity,
                        remediation=(
                            "Remove either the standalone axon or the "
                            "inline depends_on entry — they declare "
                            "the same relationship."
                        ),
                        context={
                            "source": axon.source,
                            "target": axon.target,
                            "relation": axon.relation.value,
                        },
                    ))

                # --- Check for duplicate among standalone axons ---
                if triple in standalone_seen and dup_severity is not None:
                    errors.append(S0maResolutionError(
                        code="DUPLICATE_AXON",
                        message=(
                            f"Duplicate standalone axon: "
                            f"'{axon.source} → {axon.target}' "
                            f"({axon.relation.value}) is declared "
                            f"more than once."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity=dup_severity,
                        remediation=(
                            "Remove the duplicate standalone axon "
                            "declaration."
                        ),
                        context={
                            "source": axon.source,
                            "target": axon.target,
                            "relation": axon.relation.value,
                        },
                    ))
                standalone_seen.add(triple)

                # --- Evidence check: source body ---
                if vestigial_severity is not None:
                    source_decl = None
                    for decl in mod.all_declarations:
                        if getattr(decl, "name", None) == axon.source:
                            source_decl = decl
                            break

                    if source_decl is not None:
                        body = getattr(source_decl, "body", None)
                        if body and not _has_relation_evidence(
                            body, axon.target, axon.relation
                        ):
                            evidence_type = (
                                "calls"
                                if axon.relation
                                in (Relation.CALLS, Relation.CONSTRUCTS)
                                else "references"
                            )
                            errors.append(S0maResolutionError(
                                code="VESTIGIAL_IMPORT",
                                message=(
                                    f"Standalone axon "
                                    f"'{axon.source} → {axon.target}' "
                                    f"({axon.relation.value}) has no "
                                    f"matching evidence in "
                                    f"'{axon.source}' body."
                                ),
                                file=filename,
                                line=line,
                                column=0,
                                severity=vestigial_severity,
                                remediation=(
                                    f"Add code in '{axon.source}' that "
                                    f"{evidence_type} '{axon.target}', "
                                    f"or remove the standalone axon."
                                ),
                                context={
                                    "source": axon.source,
                                    "target": axon.target,
                                    "relation": axon.relation.value,
                                },
                            ))

        return errors

    # -------------------------------------------------------------------
    # Cross-module abstract interface validation (MS 11b)
    # -------------------------------------------------------------------

    def _validate_cross_module_abstract_interfaces(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str],
    ) -> list[S0maResolutionError]:
        """Validate that cross-module CONSTRUCTS relations satisfy abstract interfaces.

        When a concrete nerve in module A has a standalone axon with
        ``relation: CONSTRUCTS`` targeting an abstract nerve in module B,
        verify that the concrete nerve's body defines all methods listed
        in the abstract nerve's ``interface`` field.

        Intra-module CONSTRUCTS are handled by the semantic validator
        (``IntraModuleValidator._check_abstract_fields``), so this method
        only checks cross-module (standalone axon) relationships.
        """
        from s0ma_dsl.semantic.validator import _extract_def_names

        errors: list[S0maResolutionError] = []

        # Build a lookup of all nerves across all modules by qualified name
        nerve_index: dict[str, tuple[str, NerveDecl]] = {}
        for mod_name, mod in modules.items():
            for nerve in mod.nerves:
                nerve_index[f"{mod_name}.{nerve.name}"] = (mod_name, nerve)
                # Also index by bare name for unqualified lookups
                nerve_index.setdefault(nerve.name, (mod_name, nerve))

        for mod_name in sorted(modules):
            mod = modules[mod_name]
            filename = filenames.get(mod_name, f"{mod_name}.s0ma")

            # Index local nerves by name for source lookup
            local_nerves: dict[str, NerveDecl] = {
                n.name: n for n in mod.nerves
            }

            for axon in mod.axons:
                if axon.relation != Relation.CONSTRUCTS:
                    continue

                line = axon.location.start_line if axon.location else 0

                # Resolve target: standalone axons use qualified names
                # (e.g., "adapters.LLMAdapter") or bare names from uses
                target_key = axon.target
                target_entry = nerve_index.get(target_key)

                if target_entry is None:
                    # Try resolving via uses aliases
                    for use in mod.module.uses:
                        local = use.alias or use.qualified_name.rsplit(".", 1)[-1]
                        if local == axon.target:
                            target_entry = nerve_index.get(use.qualified_name)
                            if target_entry is None:
                                # Try qualified form: module.component
                                comp = use.qualified_name.rsplit(".", 1)[-1]
                                target_mod = (
                                    use.qualified_name.rsplit(".", 1)[0]
                                    if "." in use.qualified_name
                                    else use.qualified_name
                                )
                                target_entry = nerve_index.get(f"{target_mod}.{comp}")
                            break

                if target_entry is None:
                    # Target not found — Phase 2 will catch DOES_NOT_EXIST
                    continue

                target_mod_name, target_nerve = target_entry

                # Skip intra-module — handled by the semantic validator
                if target_mod_name == mod_name:
                    continue

                # Only validate abstract nerves with interfaces
                if not target_nerve.abstract or not target_nerve.interface:
                    continue

                # Find the source nerve in this module
                source_nerve = local_nerves.get(axon.source)
                if source_nerve is None:
                    continue

                # Validate interface implementation
                if not source_nerve.body:
                    errors.append(S0maResolutionError(
                        code="MISSING_INTERFACE_METHODS",
                        message=(
                            f"Nerve '{source_nerve.name}' in module "
                            f"'{mod_name}' CONSTRUCTS abstract nerve "
                            f"'{target_nerve.name}' in module "
                            f"'{target_mod_name}' but has no body to "
                            f"implement the required interface."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Add a body to '{source_nerve.name}' with "
                            f"definitions for: "
                            f"{', '.join(target_nerve.interface)}."
                        ),
                        context={
                            "source_module": mod_name,
                            "nerve": source_nerve.name,
                            "target_module": target_mod_name,
                            "abstract_nerve": target_nerve.name,
                            "required_methods": list(target_nerve.interface),
                        },
                    ))
                    continue

                body_defs = _extract_def_names(source_nerve.body)
                missing = [
                    m for m in target_nerve.interface if m not in body_defs
                ]
                if missing:
                    errors.append(S0maResolutionError(
                        code="MISSING_INTERFACE_METHODS",
                        message=(
                            f"Nerve '{source_nerve.name}' in module "
                            f"'{mod_name}' CONSTRUCTS abstract nerve "
                            f"'{target_nerve.name}' in module "
                            f"'{target_mod_name}' but is missing "
                            f"interface methods: {', '.join(missing)}."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity="error",
                        remediation=(
                            f"Add the following definitions to "
                            f"'{source_nerve.name}': "
                            + ", ".join(f"def {m}(...)" for m in missing)
                            + "."
                        ),
                        context={
                            "source_module": mod_name,
                            "nerve": source_nerve.name,
                            "target_module": target_mod_name,
                            "abstract_nerve": target_nerve.name,
                            "required_methods": list(target_nerve.interface),
                            "missing_methods": missing,
                            "body_functions": sorted(body_defs),
                        },
                    ))

        return errors

    # -------------------------------------------------------------------
    # Release-mode: test coverage for PUBLIC nerves
    # -------------------------------------------------------------------

    def _check_serves_as_collisions(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str],
    ) -> list[S0maResolutionError]:
        """Project-scope ``serves_as`` uniqueness (DSL-M1, ADR-011 §(b)).

        Served names form ONE flat namespace across all declarations in
        the project build (L-2, conservative by design — relaxable
        post-evidence if distinct serving namespaces ever need the same
        name). The intra-module case is already reported by the
        semantic validator (``IntraModuleValidator._check_serves_as_fields``);
        this pass reports only collisions that SPAN modules, so one
        authoring mistake never produces two diagnostics.
        """
        errors: list[S0maResolutionError] = []
        carriers: dict[str, list[tuple[str, str, int]]] = {}

        for mod_name in sorted(modules):
            mod = modules[mod_name]
            for nerve in mod.nerves:
                served = getattr(nerve, "serves_as", None)
                if served is None:
                    continue
                line = nerve.location.start_line if nerve.location else 0
                carriers.setdefault(served, []).append(
                    (mod_name, nerve.name, line),
                )

        for served, decls in sorted(carriers.items()):
            owning_modules = {mod_name for mod_name, _, _ in decls}
            if len(decls) < 2 or len(owning_modules) < 2:
                continue
            qualified = ", ".join(
                f"'{mod_name}.{decl_name}'" for mod_name, decl_name, _ in decls
            )
            first_mod, _first_decl, first_line = decls[0]
            errors.append(S0maResolutionError(
                code="SERVES_AS_COLLISION",
                message=(
                    f"serves_as '{served}' is carried by declarations in "
                    f"more than one module: {qualified}. Served names form "
                    f"one flat namespace across the project build and must "
                    f"be unique."
                ),
                file=filenames.get(first_mod, f"{first_mod}.s0ma"),
                line=first_line,
                column=0,
                severity="error",
                remediation=(
                    f"Rename the serves_as value on all but one of "
                    f"{qualified}."
                ),
                context={
                    "serves_as": served,
                    "declarations": [
                        f"{mod_name}::{decl_name}"
                        for mod_name, decl_name, _ in decls
                    ],
                },
            ))

        return errors

    def _check_release_test_coverage(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str],
    ) -> list[S0maResolutionError]:
        """Check that all PUBLIC nerves have test coverage (release mode).

        For each PUBLIC nerve across all modules, at least one
        ``TestDecl`` must reference it in its ``tests`` field.
        Cross-module coverage is valid (module B's test can cover
        module A's nerve).

        Targets in ``test.tests`` may be authored as bare names
        (``MyNerve``) or qualified names (``my_module.MyNerve``); both
        forms are canonicalised to ``module::component`` before
        comparison via :func:`resolve_test_target_canonical`. A bare
        target that matches multiple modules emits a separate
        ``AMBIGUOUS_TEST_TARGET`` error so the user knows to qualify
        it; the underlying nerve still appears uncovered until the
        ambiguity is resolved.
        """
        errors: list[S0maResolutionError] = []
        severity = get_severity("MISSING_TEST_COVERAGE", self.mode)

        # AMBIGUOUS_TEST_TARGET is error-severity in every mode (a real
        # ambiguity is a correctness bug, not a style preference). We
        # walk test targets even when MISSING_TEST_COVERAGE is silent in
        # the current mode so ambiguity is surfaced regardless.
        ambiguous_severity = get_severity(
            "AMBIGUOUS_TEST_TARGET", self.mode
        )

        # Walk every test target in the project, canonicalising on the
        # spot. Track ambiguity diagnostics keyed by (file, line, raw)
        # so the same authored entry only produces one error.
        all_test_targets: set[str] = set()
        seen_ambiguous: set[tuple[str, int, str]] = set()

        for src_mod_name in sorted(modules):
            src_mod = modules[src_mod_name]
            src_filename = filenames.get(
                src_mod_name, f"{src_mod_name}.s0ma"
            )
            for test in src_mod.tests:
                test_line = (
                    test.location.start_line if test.location else 0
                )
                for raw_target in test.tests:
                    canonical = resolve_test_target_canonical(
                        raw_target, src_mod_name, modules
                    )
                    if isinstance(canonical, AmbiguousTestTarget):
                        if ambiguous_severity is not None:
                            key = (src_filename, test_line, raw_target)
                            if key in seen_ambiguous:
                                continue
                            seen_ambiguous.add(key)
                            errors.append(S0maResolutionError(
                                code="AMBIGUOUS_TEST_TARGET",
                                message=(
                                    f"Test target '{raw_target}' in test "
                                    f"'{test.name}' (module "
                                    f"'{src_mod_name}') is ambiguous: it "
                                    f"matches components in multiple "
                                    f"modules: "
                                    f"{', '.join(canonical.candidates)}."
                                ),
                                file=src_filename,
                                line=test_line,
                                column=0,
                                severity=ambiguous_severity,
                                remediation=(
                                    f"Qualify the target with the owning "
                                    f"module name, e.g. "
                                    f"'tests: [<module>.{raw_target}]', "
                                    f"choosing one of: "
                                    f"{', '.join(canonical.candidates)}."
                                ),
                                context={
                                    "source_module": src_mod_name,
                                    "test": test.name,
                                    "raw_target": raw_target,
                                    "candidates": list(
                                        canonical.candidates
                                    ),
                                },
                            ))
                        continue
                    if canonical is None:
                        # Target points at nothing the registry can
                        # resolve — leave it for other passes (e.g.,
                        # IR-level verification edges) or future
                        # validation. The release-coverage check is
                        # purely about whether each PUBLIC nerve is
                        # covered, not whether every authored target is
                        # well-formed.
                        continue
                    all_test_targets.add(canonical)

        if severity is None:
            return errors

        # Check each PUBLIC nerve has coverage
        for mod_name in sorted(modules):
            mod = modules[mod_name]
            filename = filenames.get(mod_name, f"{mod_name}.s0ma")

            for nerve in mod.nerves:
                if nerve.visibility != Visibility.PUBLIC:
                    continue
                # DSL-M2 (0.8.0, ADR-011 §(e)): a non-empty
                # ``covered_by:`` is the external test-evidence
                # credit — the gate passes on EITHER in-language
                # ``tests:`` coverage OR the authored claim. The
                # credit does NOT inject synthetic test targets: the
                # IR/registry keep "tested in-language" and
                # "externally covered" distinguishable (the honest
                # record F-M5-3 demanded).
                if nerve.covered_by:
                    continue
                check_key = f"{mod_name}::{nerve.name}"
                if check_key not in all_test_targets:
                    line = (
                        nerve.location.start_line if nerve.location else 0
                    )
                    errors.append(S0maResolutionError(
                        code="MISSING_TEST_COVERAGE",
                        message=(
                            f"PUBLIC nerve '{nerve.name}' in module "
                            f"'{mod_name}' has no test coverage. In "
                            f"release mode, every PUBLIC nerve must be "
                            f"referenced by at least one test declaration "
                            f"or carry a covered_by: claim."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity=severity,
                        remediation=(
                            f"Add a test declaration with "
                            f"'tests: [{nerve.name}]' (intra-module) or "
                            f"'tests: [{mod_name}.{nerve.name}]' "
                            f"(cross-module) in this module or another "
                            f"module in the project — or declare "
                            f"'covered_by:' on '{nerve.name}' naming "
                            f"the external suite that covers it."
                        ),
                        context={
                            "module": mod_name,
                            "nerve": nerve.name,
                            "visibility": "PUBLIC",
                            "canonical_id": check_key,
                        },
                    ))

        return errors

    # -------------------------------------------------------------------
    # M9: Cross-module ``uses:`` layer enforcement
    # -------------------------------------------------------------------

    def _check_cross_layer_dependencies(
        self,
        modules: dict[str, S0maModule],
        filenames: dict[str, str],
    ) -> list[S0maResolutionError]:
        """Check that every ``uses:`` target's layer is reachable from the source.

        For each module ``M`` with declared layer ``L_M``, walk
        ``M.module.uses``. If a ``uses:`` entry's target module is in
        the project (registered) and its layer is *not* in
        ``_ALLOWED_TARGET_LAYERS[L_M]``, emit
        ``CROSS_LAYER_DEPENDENCY``.

        External modules (those resolved via ``requires:`` for
        third-party Python packages) are out of scope — they have no
        ``Layer`` to compare against. Test modules' ``uses:`` entries
        are checked at the layer the test declares (a DOMAIN-layer
        test importing a PRESENTATION component is the same
        architectural smell as a DOMAIN production module doing it —
        spec §4.0.1 cross-module rule).

        Severity follows :data:`s0ma_dsl.config.SEVERITY_MATRIX` for
        ``CROSS_LAYER_DEPENDENCY``: warning in migration/dev, error in
        strict and release.

        **M-10 (POST-6, 0.16.0):** when the project opts in via
        ``[tool.s0ma].test_layering = "permissive"``, modules that
        contain at least one ``test`` declaration are exempt from
        this check. Production modules (zero ``test`` declarations)
        still get the strict check regardless. The carve-out mirrors
        the M13 helper-access rule (test-context modules are
        identified by ``len(module.tests) > 0``).
        """
        errors: list[S0maResolutionError] = []
        severity = get_severity("CROSS_LAYER_DEPENDENCY", self.mode)
        if severity is None:
            return errors

        permissive = self.test_layering == "permissive"

        for src_name in sorted(modules):
            src_mod = modules[src_name]
            # M-10 (POST-6): permissive mode exempts test-context
            # modules from the cross-layer check. The carve-out
            # trigger is "module has ≥1 test declaration" — same shape
            # as the M13 helper-access rule (see ``HELPER_PRIVATE_TO_MODULE``
            # consumer check above). Production modules (zero ``test``
            # declarations) are unaffected.
            if permissive and src_mod.tests:
                continue
            src_layer = src_mod.module.layer
            allowed = _ALLOWED_TARGET_LAYERS.get(src_layer, set())
            filename = filenames.get(src_name, f"{src_name}.s0ma")

            # The cross-module edge population: every ``uses:`` entry,
            # plus (DSL-M2, ADR-011 §(d) rule 5) every QUALIFIED inline
            # ``depends_on:`` target — the reachability matrix applies
            # unchanged to declared architecture edges regardless of
            # which header field authored them. Each item is
            # ``(qualified_name, location)``.
            cross_module_edges: list[tuple[str, SourceLocation | None]] = [
                (use.qualified_name, use.location)
                for use in src_mod.module.uses
            ]
            for decl in src_mod.all_declarations:
                for axon in getattr(decl, "depends_on", ()):
                    if "." not in axon.target:
                        continue
                    axon_target_mod = axon.target.split(".", 1)[0]
                    if axon_target_mod == src_name:
                        # Self-module-qualified — intra-module edge.
                        continue
                    cross_module_edges.append(
                        (axon.target, axon.location or decl.location)
                    )

            for qualified_name, location in cross_module_edges:
                target_mod_name = _module_from_qualified(qualified_name)

                # External modules (not registered as project ``.s0ma``
                # modules) carry no ``Layer`` and are out of scope.
                if target_mod_name not in modules:
                    continue

                target_mod = modules[target_mod_name]
                target_layer = target_mod.module.layer

                if target_layer in allowed:
                    continue

                line = location.start_line if location else 0
                suggested = _suggest_lower_layer(src_layer, target_layer)

                errors.append(S0maResolutionError(
                    code="CROSS_LAYER_DEPENDENCY",
                    message=(
                        f"Module '{src_name}' (layer "
                        f"{src_layer.value}) cannot depend on module "
                        f"'{target_mod_name}' (layer "
                        f"{target_layer.value}) via "
                        f"'{qualified_name}'. The cross-module "
                        f"layer rule allows "
                        f"{src_layer.value} → "
                        f"{{{', '.join(sorted(layer.value for layer in allowed))}}}; "
                        f"{target_layer.value} is not reachable."
                    ),
                    file=filename,
                    line=line,
                    column=0,
                    severity=severity,
                    remediation=(
                        f"Resolve the layer violation in one of two "
                        f"ways: (1) move the shared concept down to "
                        f"layer {suggested.value} (or any layer "
                        f"{src_layer.value} can consume) so both "
                        f"sides can reach it; or (2) invert the "
                        f"dependency — have "
                        f"'{target_mod_name}' depend on "
                        f"'{src_name}' instead, typically by "
                        f"introducing an abstract interface in a "
                        f"lower layer that '{target_mod_name}' "
                        f"implements."
                    ),
                    context={
                        "source_module": src_name,
                        "source_layer": src_layer.value,
                        "target_module": target_mod_name,
                        "target_layer": target_layer.value,
                        "qualified_name": qualified_name,
                        "allowed_target_layers": sorted(
                            layer.value for layer in allowed
                        ),
                    },
                ))

        return errors


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_resolve_dependencies",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Convenience function to run all four phases of cross-module dependency resolution on a "
        "s0ma project."
    ),
    idempotent=True,
    is_framework=True,
)
def resolve_dependencies(
    modules: dict[str, S0maModule],
    *,
    mode: StrictnessMode = StrictnessMode.DEV,
    filenames: dict[str, str] | None = None,
    check_imports: bool = True,
    attribute_budgets: dict[str, str] | None = None,
    test_layering: str = "strict",
) -> list[S0maResolutionError]:
    """Run all four phases of cross-module dependency resolution.

    Parameters
    ----------
    modules:
        Dict mapping module names to parsed ``S0maModule`` objects.
    mode:
        Active strictness mode.
    filenames:
        Dict mapping module names to source file paths.
    check_imports:
        If ``True``, verify requires entries are importable.
    attribute_budgets:
        M18 (feedback 5–6) — project-level
        ``[tool.s0ma.attribute_budgets]`` mapping. When ``None`` or
        empty, the budget pass is a no-op and ``declares_attributes:``
        on nerves remains purely descriptive.
    test_layering:
        M-10 (POST-6, 0.16.0) — project-level
        ``[tool.s0ma].test_layering`` stance. ``"strict"`` (default)
        applies the cross-module layer-reachability check to every
        module; ``"permissive"`` exempts modules with at least one
        ``test`` declaration from that check (production modules
        stay strict regardless).

    Returns
    -------
    list[S0maResolutionError]
        All errors and warnings found.
    """
    resolver = DependencyResolver(
        mode=mode,
        attribute_budgets=dict(attribute_budgets or {}),
        test_layering=test_layering,
    )
    return resolver.resolve(
        modules, filenames, check_imports=check_imports
    )
