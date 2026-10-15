"""Milestone 2 structural checks — layer, cycles, completeness, erosion.

Contains the check functions added in Phase 2 Milestone 2:
- Layer conformance checking (architectural boundary enforcement)
- Dependency cycle detection (per-component and full-graph)
- Component completeness checking (intent, version, deps)
- de Silva erosion coverage analysis (minimise/prevent/repair)
"""

from __future__ import annotations

import importlib
import re
from typing import TYPE_CHECKING

from s0ma.models import Anomaly, ErosionCoverageReport
from s0ma.types import AnomalyKind, AnomalySeverity, Layer

if TYPE_CHECKING:
    from s0ma.models import ComponentSpec
    from s0ma.registry import ComponentRegistry

__all__: list[str] = []  # All functions are internal

# Semver pattern: major.minor.patch with optional pre-release/build
_SEMVER_PATTERN = re.compile(
    r"^\d+\.\d+\.\d+(?:[-+].+)?$"
)

# Layer ordering: lower index = lower layer.
# FRAMEWORK is exempt — it can depend on anything.
_LAYER_ORDER: dict[Layer, int] = {
    Layer.DOMAIN: 0,
    Layer.APPLICATION: 1,
    Layer.INFRASTRUCTURE: 2,
    Layer.PRESENTATION: 3,
    Layer.FRAMEWORK: 99,
}

# Placeholder intent patterns indicating incomplete metadata
_PLACEHOLDER_PATTERNS = frozenset({
    "todo", "placeholder", "tbd", "fixme", "xxx",
    "fill in", "describe me", "update this",
})


# ======================================================================
# Layer conformance
# ======================================================================


def check_layer_violations(
    spec: ComponentSpec,
    registry: ComponentRegistry,
) -> tuple[list[Anomaly], int]:
    """Check for layer violations between a component and its dependencies.

    Enforces the allowed dependency directions:
      PRESENTATION -> APPLICATION -> DOMAIN
      PRESENTATION -> INFRASTRUCTURE
      APPLICATION -> INFRASTRUCTURE
      FRAMEWORK -> (any)

    DOMAIN depending on PRESENTATION is always an ERROR.
    Other upward dependencies are WARNINGs.

    Returns:
        Tuple of (anomalies, checks_performed).
    """
    anomalies: list[Anomaly] = []
    checks = 0
    spec_level = _LAYER_ORDER.get(spec.layer, -1)

    for dep_name in spec.dependencies:
        dep_spec = registry.get(dep_name)
        if dep_spec is None:
            continue

        checks += 1
        dep_level = _LAYER_ORDER.get(dep_spec.layer, -1)

        # Framework layer is exempt
        if (
            spec.layer == Layer.FRAMEWORK
            or dep_spec.layer == Layer.FRAMEWORK
        ):
            continue

        # Domain -> Presentation is a hard violation
        if (
            spec.layer == Layer.DOMAIN
            and dep_spec.layer == Layer.PRESENTATION
        ):
            anomalies.append(Anomaly(
                kind=AnomalyKind.INFLAMMATION,
                severity=AnomalySeverity.ERROR,
                component_name=spec.name,
                message=(
                    f"Layer violation: '{spec.name}' "
                    f"({spec.layer.name}) depends on "
                    f"'{dep_name}' ({dep_spec.layer.name}). "
                    f"DOMAIN components should not depend "
                    f"on PRESENTATION."
                ),
                details={
                    "component_layer": spec.layer.name,
                    "dependency_layer": dep_spec.layer.name,
                    "dependency": dep_name,
                },
            ))
        # Lower depending on higher (excluding INFRASTRUCTURE)
        elif (
            spec_level < dep_level
            and dep_spec.layer != Layer.INFRASTRUCTURE
        ):
            anomalies.append(Anomaly(
                kind=AnomalyKind.INFLAMMATION,
                severity=AnomalySeverity.WARNING,
                component_name=spec.name,
                message=(
                    f"Potential layer violation: '{spec.name}' "
                    f"({spec.layer.name}) depends on "
                    f"'{dep_name}' ({dep_spec.layer.name})"
                ),
                details={
                    "component_layer": spec.layer.name,
                    "dependency_layer": dep_spec.layer.name,
                    "dependency": dep_name,
                },
            ))

    return anomalies, checks


# ======================================================================
# Per-component cycle detection (for verify_incremental)
# ======================================================================


def check_cycle_for_component(
    spec: ComponentSpec,
    registry: ComponentRegistry,
) -> tuple[list[Anomaly], int]:
    """Check if a component introduces a cycle in the dependency graph.

    Uses DFS from the component through its dependencies to detect
    if any path leads back to the component itself.

    Returns:
        Tuple of (anomalies, checks_performed).
    """
    anomalies: list[Anomaly] = []
    checks = 1

    visited: set[str] = set()
    path: list[str] = []

    def _dfs(current: str) -> list[str] | None:
        """Return the cycle path if found, None otherwise."""
        if current in visited:
            return None
        if current == spec.name and path:
            return [*path, current]

        visited.add(current)
        path.append(current)

        current_spec = registry.get(current)
        if current_spec is not None:
            for dep in current_spec.dependencies:
                if dep == spec.name and path:
                    return [*path, dep]
                result = _dfs(dep)
                if result is not None:
                    return result

        path.pop()
        return None

    for dep in spec.dependencies:
        cycle = _dfs(dep)
        if cycle is not None:
            cycle_path = [spec.name, *cycle]
            anomalies.append(Anomaly(
                kind=AnomalyKind.INFLAMMATION,
                severity=AnomalySeverity.ERROR,
                component_name=spec.name,
                message=(
                    f"Dependency cycle detected: "
                    f"{' -> '.join(cycle_path)}"
                ),
                details={"cycle_path": cycle_path},
            ))
            break  # Only report one cycle per component

    return anomalies, checks


# ======================================================================
# Full-graph cycle detection (for verify)
# ======================================================================


def check_all_cycles(
    registry: ComponentRegistry,
) -> tuple[list[Anomaly], int]:
    """Detect all cycles in the full dependency graph.

    Uses iterative DFS with back-edge detection.
    Reports each distinct cycle as an INFLAMMATION/ERROR anomaly.

    Returns:
        Tuple of (anomalies, checks_performed).
    """
    anomalies: list[Anomaly] = []
    checks = 1

    graph = registry.get_dependency_graph()
    if not graph:
        return anomalies, checks

    # States: 0 = unvisited, 1 = in current path, 2 = finished
    state: dict[str, int] = dict.fromkeys(graph, 0)
    reported_cycles: set[frozenset[str]] = set()

    def _dfs(start: str) -> None:
        """Iterative DFS to detect cycles via back-edges."""
        stack: list[tuple[str, int]] = [(start, 0)]
        state[start] = 1

        while stack:
            node, dep_idx = stack[-1]
            deps = graph.get(node, [])

            if dep_idx < len(deps):
                stack[-1] = (node, dep_idx + 1)
                dep = deps[dep_idx]

                if dep not in state:
                    continue

                if state[dep] == 0:
                    state[dep] = 1
                    stack.append((dep, 0))
                elif state[dep] == 1:
                    cycle_path = _reconstruct_cycle(stack, dep)
                    cycle_set = frozenset(cycle_path[:-1])
                    if cycle_set not in reported_cycles:
                        reported_cycles.add(cycle_set)
                        anomalies.append(Anomaly(
                            kind=AnomalyKind.INFLAMMATION,
                            severity=AnomalySeverity.ERROR,
                            component_name=dep,
                            message=(
                                f"Dependency cycle detected: "
                                f"{' -> '.join(cycle_path)}"
                            ),
                            details={"cycle_path": cycle_path},
                        ))
            else:
                state[node] = 2
                stack.pop()

    for name in graph:
        if state[name] == 0:
            _dfs(name)

    return anomalies, checks


def _reconstruct_cycle(
    stack: list[tuple[str, int]],
    target: str,
) -> list[str]:
    """Reconstruct the cycle path from the DFS stack."""
    path: list[str] = []
    collecting = False
    for node, _ in stack:
        if node == target:
            collecting = True
        if collecting:
            path.append(node)
    path.append(target)
    return path


# ======================================================================
# Component completeness checking
# ======================================================================


def check_completeness(
    spec: ComponentSpec,
    registry: ComponentRegistry,
) -> tuple[list[Anomaly], int, list[str]]:
    """Verify that registry metadata is complete and meaningful.

    Checks:
    - Intent is non-placeholder (not generic TODO/placeholder text)
    - All declared dependencies are registered
    - Version follows semver pattern
    - Module path points to an importable module

    Returns:
        Tuple of (anomalies, checks_performed, convergences).
    """
    anomalies: list[Anomaly] = []
    checks = 0
    convergences: list[str] = []

    # Check intent quality
    checks += 1
    intent_lower = spec.intent.lower().strip()
    if any(p in intent_lower for p in _PLACEHOLDER_PATTERNS):
        anomalies.append(Anomaly(
            kind=AnomalyKind.VESTIGIAL_ORGAN,
            severity=AnomalySeverity.WARNING,
            component_name=spec.name,
            message=(
                f"Component '{spec.name}' has a placeholder "
                f"intent: '{spec.intent}'"
            ),
            details={"intent": spec.intent},
        ))
    else:
        convergences.append(
            f"{spec.name}: intent is meaningful "
            f"({len(spec.intent)} chars)"
        )

    # Check all declared dependencies are registered. ``contains`` resolves
    # bare names and qualified ``module::name`` claims alike, so a
    # cross-module claim on a bare-keyed registration is not a phantom limb.
    checks += 1
    unregistered_deps = [
        dep for dep in spec.dependencies
        if not registry.contains(dep)
    ]
    if unregistered_deps:
        for dep in unregistered_deps:
            anomalies.append(Anomaly(
                kind=AnomalyKind.PHANTOM_LIMB,
                severity=AnomalySeverity.WARNING,
                component_name=spec.name,
                message=(
                    f"Component '{spec.name}' declares dependency "
                    f"'{dep}' which is not registered"
                ),
                details={
                    "unregistered_dependency": dep,
                    "declared_dependencies": spec.dependencies,
                },
            ))
    else:
        convergences.append(
            f"{spec.name}: all dependencies registered"
        )

    # Check version follows semver
    checks += 1
    if not _SEMVER_PATTERN.match(spec.version):
        anomalies.append(Anomaly(
            kind=AnomalyKind.VESTIGIAL_ORGAN,
            severity=AnomalySeverity.INFO,
            component_name=spec.name,
            message=(
                f"Component '{spec.name}' version "
                f"'{spec.version}' does not follow "
                f"semver pattern (X.Y.Z)"
            ),
            details={"version": spec.version},
        ))
    else:
        convergences.append(
            f"{spec.name}: version '{spec.version}' follows semver"
        )

    # Check module_path is importable (if set)
    if spec.module_path:
        checks += 1
        try:
            importlib.import_module(spec.module_path)
            convergences.append(
                f"{spec.name}: module_path importable"
            )
        except ImportError:
            anomalies.append(Anomaly(
                kind=AnomalyKind.PHANTOM_LIMB,
                severity=AnomalySeverity.ERROR,
                component_name=spec.name,
                message=(
                    f"Component '{spec.name}' module_path "
                    f"'{spec.module_path}' cannot be imported"
                ),
                details={"module_path": spec.module_path},
            ))

    return anomalies, checks, convergences


# ======================================================================
# de Silva erosion coverage analysis
# ======================================================================


def compute_erosion_coverage(
    registry: ComponentRegistry,
    components_checked: int,
) -> ErosionCoverageReport:
    """Compute de Silva et al. (2012) erosion-control strategy coverage.

    Checks the three strategies:
    - Minimise: @component decorator usage
    - Prevent: import hook installation
    - Repair: verification engine running (this call proves it)

    Args:
        registry: The registry to analyse.
        components_checked: Number of components verified in this run.

    Returns:
        ErosionCoverageReport with strategy activation and coverage.
    """
    from s0ma.import_hook import is_hook_installed

    total_components = registry.count()

    minimise_active = total_components > 0
    minimise_coverage = 1.0 if total_components > 0 else 0.0

    prevent_active = is_hook_installed()
    prevent_coverage = 1.0 if prevent_active else 0.0

    repair_active = True
    repair_coverage = (
        components_checked / total_components
        if total_components > 0
        else 1.0
    )

    return ErosionCoverageReport(
        minimise_active=minimise_active,
        prevent_active=prevent_active,
        repair_active=repair_active,
        minimise_coverage=minimise_coverage,
        prevent_coverage=prevent_coverage,
        repair_coverage=repair_coverage,
    )
