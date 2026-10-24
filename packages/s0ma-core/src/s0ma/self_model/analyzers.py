"""Impact analysis and extension point detection for the self-model API.

Provides analytical functions that enable LLM orchestration layers to
understand change consequences, find safe insertion points, and
pre-validate new components against the current self-model.

Key functions:
    - compute_impact_analysis: what would be affected if a component changes
    - find_extension_points: where can new components be safely added
    - validate_proposed_component: pre-creation validation against constraints
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from s0ma.exceptions import RegistryIntegrityError
from s0ma.models import Anomaly
from s0ma.types import AnomalyKind, AnomalySeverity, ComponentKind, Layer

if TYPE_CHECKING:
    from s0ma.models import ComponentSpec
    from s0ma.registry import ComponentRegistry
    from s0ma.verifiers.interoception import MetricsCollector

__all__ = [
    "ImpactReport",
    "ExtensionPoint",
    "compute_impact_analysis",
    "find_extension_points",
    "validate_proposed_component",
    "explain_dependency_chain",
]


@dataclass(frozen=True)
class ImpactReport:
    """Structured impact analysis result.

    Describes what would be affected if a given component changes,
    including direct dependents, transitive dependents, affected
    architectural layers, documentation artifacts that cover the
    component, canonical examples that demonstrate it, and an
    overall risk assessment.
    """

    component_name: str
    direct_dependents: list[str]
    transitive_dependents: list[str]
    affected_layers: list[Layer]
    total_affected_count: int
    max_dependency_depth: int
    risk_level: str  # "low", "medium", "high"
    affected_docs: list[str] = field(default_factory=list)
    affected_examples: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtensionPoint:
    """A location in the architecture where a new component can be added.

    Describes a layer + kind combination where adding a component
    would not violate architectural constraints, along with potential
    dependency targets and a rationale for why this is a good
    extension point.
    """

    layer: Layer
    suggested_kinds: list[ComponentKind]
    potential_dependencies: list[str]
    rationale: str


def compute_impact_analysis(
    registry: ComponentRegistry,
    component_name: str,
    *,
    metrics_collector: MetricsCollector | None = None,
) -> ImpactReport:
    """Compute what would be affected if a component changes.

    Performs a breadth-first traversal of the reverse dependency graph
    to find all components that transitively depend on the target.

    Args:
        registry: The ComponentRegistry to analyze.
        component_name: The component to analyze impact for, or the name of
            an operation it provides; the report is then the providing
            component's and records the operation in ``details``.
        metrics_collector: Optional MetricsCollector for performance data.

    Returns:
        ImpactReport with structured analysis data.

    Raises:
        RegistryIntegrityError: If the component is not registered, or if
            the name is an operation that several components provide.
    """
    spec, operation = _resolve_or_raise(
        registry, component_name, "Cannot analyze impact"
    )
    component_name = spec.name

    # Get direct dependents
    direct_dependent_specs = registry.get_dependents(component_name)
    direct_dependents = sorted(s.name for s in direct_dependent_specs)

    # BFS for transitive dependents (excluding direct)
    all_dependents: set[str] = set(direct_dependents)
    queue: deque[str] = deque(direct_dependents)
    max_depth = 0
    depth_map: dict[str, int] = dict.fromkeys(direct_dependents, 1)

    while queue:
        current = queue.popleft()
        current_depth = depth_map[current]
        try:
            next_deps = registry.get_dependents(current)
        except RegistryIntegrityError:
            continue
        for dep_spec in next_deps:
            if dep_spec.name not in all_dependents:
                all_dependents.add(dep_spec.name)
                next_depth = current_depth + 1
                depth_map[dep_spec.name] = next_depth
                if next_depth > max_depth:
                    max_depth = next_depth
                queue.append(dep_spec.name)

    # If we have direct dependents but max_depth is still 0, set it to 1
    if direct_dependents and max_depth == 0:
        max_depth = 1

    transitive_only = sorted(all_dependents - set(direct_dependents))

    # Determine affected layers
    affected_layers_set: set[Layer] = set()
    affected_layers_set.add(spec.layer)
    for dep_name in all_dependents:
        affected_spec = registry.get(dep_name)
        if affected_spec is not None:
            affected_layers_set.add(affected_spec.layer)
    affected_layers = sorted(affected_layers_set, key=lambda layer: layer.value)

    # Risk assessment
    total_affected = len(all_dependents)
    if total_affected == 0:
        risk_level = "low"
    elif total_affected <= 3:
        risk_level = "medium"
    else:
        risk_level = "high"

    # Build details
    details: dict[str, Any] = {
        "component_kind": spec.kind.name,
        "component_layer": spec.layer.name,
        "is_framework": spec.is_framework,
    }
    if operation is not None:
        details["operation"] = operation

    if metrics_collector is not None:
        try:
            metrics = metrics_collector.get_metrics(component_name)
            if metrics is not None:
                details["has_runtime_metrics"] = True
                details["call_count"] = metrics.call_count
        except Exception:  # noqa: BLE001
            pass

    # Documentation and example artifacts that reference the component
    # (reverse-index lookups via RegistrySnapshot, M4 — §10.5).
    snapshot = registry.snapshot()
    docs_result = snapshot.docs_for(component_name)
    affected_docs = sorted(
        [ref.name for ref in docs_result.refs]
        + [guide.name for guide in docs_result.guides]
    )
    affected_examples = sorted(
        ex.name for ex in snapshot.examples_for(component_name)
    )

    return ImpactReport(
        component_name=component_name,
        direct_dependents=direct_dependents,
        transitive_dependents=transitive_only,
        affected_layers=affected_layers,
        total_affected_count=total_affected,
        max_dependency_depth=max_depth,
        risk_level=risk_level,
        affected_docs=affected_docs,
        affected_examples=affected_examples,
        details=details,
    )


def find_extension_points(
    registry: ComponentRegistry,
) -> list[ExtensionPoint]:
    """Identify where new components can be added without violating constraints.

    Analyzes the current architecture to find layers and component kinds
    where new components could be naturally added. Considers existing
    component distribution, dependency patterns, and architectural
    conventions.

    Args:
        registry: The ComponentRegistry to analyze.

    Returns:
        List of ExtensionPoint objects describing safe insertion locations.
    """
    all_components = registry.get_all()
    if not all_components:
        # Empty registry — all layers are open
        return [
            ExtensionPoint(
                layer=layer,
                suggested_kinds=[
                    k for k in ComponentKind if k != ComponentKind.FRAMEWORK
                ],
                potential_dependencies=[],
                rationale=f"The {layer.name} layer has no components yet. "
                f"Any non-framework component kind is appropriate.",
            )
            for layer in Layer
            if layer != Layer.FRAMEWORK
        ]

    # Group existing components by layer
    by_layer: dict[Layer, list[str]] = {}
    for spec in all_components.values():
        if spec.layer not in by_layer:
            by_layer[spec.layer] = []
        by_layer[spec.layer].append(spec.name)

    # Identify existing kinds per layer
    kinds_by_layer: dict[Layer, set[ComponentKind]] = {}
    for spec in all_components.values():
        if spec.layer not in kinds_by_layer:
            kinds_by_layer[spec.layer] = set()
        kinds_by_layer[spec.layer].add(spec.kind)

    # Find potential dependency targets (components with few or no dependents
    # that could serve as natural upstream dependencies)
    dependency_graph = registry.get_dependency_graph()

    extension_points: list[ExtensionPoint] = []

    # For each non-framework layer, determine extension opportunities
    for layer in Layer:
        if layer == Layer.FRAMEWORK:
            # Framework layer is reserved for S0ma internals
            continue

        existing = by_layer.get(layer, [])
        existing_kinds = kinds_by_layer.get(layer, set())

        # Determine which kinds are appropriate for this layer
        suggested_kinds = _suggest_kinds_for_layer(layer, existing_kinds)

        # Find potential dependencies — components in same or lower layers
        potential_deps = _find_potential_dependencies(
            layer, all_components, dependency_graph
        )

        if existing:
            rationale = (
                f"The {layer.name} layer has {len(existing)} existing "
                f"component(s). New components can be added alongside "
                f"them using the suggested kinds."
            )
        else:
            rationale = (
                f"The {layer.name} layer currently has no components. "
                f"This is a natural extension point for "
                f"{', '.join(k.name.lower() for k in suggested_kinds)} "
                f"components."
            )

        if suggested_kinds:
            extension_points.append(
                ExtensionPoint(
                    layer=layer,
                    suggested_kinds=suggested_kinds,
                    potential_dependencies=potential_deps,
                    rationale=rationale,
                )
            )

    return extension_points


def validate_proposed_component(
    registry: ComponentRegistry,
    spec: Any,
) -> list[Anomaly]:
    """Check if a proposed new component would violate any constraints.

    Pre-creation validation that catches problems before they happen.
    Returns a list of Anomaly objects (empty if the component is valid).

    Checks:
    - Name uniqueness (not already registered)
    - Dependency existence (all declared deps exist)
    - Layer conformance (no invalid cross-layer dependencies)
    - Naming conventions (name is non-empty, no whitespace)
    - Contract completeness (has meaningful intent)

    Args:
        registry: The ComponentRegistry to validate against.
        spec: The proposed ComponentSpec.

    Returns:
        List of Anomaly objects. Empty list means the component is valid.
    """
    anomalies: list[Anomaly] = []

    # 1. Name uniqueness
    if registry.contains(spec.name):
        anomalies.append(
            Anomaly(
                kind=AnomalyKind.IMMUNE_RESPONSE,
                severity=AnomalySeverity.ERROR,
                component_name=spec.name,
                message=(
                    f"Component '{spec.name}' is already registered. "
                    f"Choose a different name."
                ),
            )
        )

    # 2. Dependency existence
    for dep in spec.dependencies:
        if not registry.contains(dep):
            anomalies.append(
                Anomaly(
                    kind=AnomalyKind.PHANTOM_LIMB,
                    severity=AnomalySeverity.ERROR,
                    component_name=spec.name,
                    message=(
                        f"Declared dependency '{dep}' is not registered. "
                        f"Register it first or remove the dependency."
                    ),
                    details={"missing_dependency": dep},
                )
            )

    # 3. Layer conformance — check cross-layer dependency rules
    for dep in spec.dependencies:
        dep_spec = registry.get(dep)
        if dep_spec is not None:
            violation = _check_layer_violation(spec.layer, dep_spec.layer)
            if violation is not None:
                anomalies.append(
                    Anomaly(
                        kind=AnomalyKind.INFLAMMATION,
                        severity=AnomalySeverity.WARNING,
                        component_name=spec.name,
                        message=violation,
                        details={
                            "source_layer": spec.layer.name,
                            "target_layer": dep_spec.layer.name,
                            "dependency": dep,
                        },
                    )
                )

    # 4. Naming conventions
    if not spec.name:
        anomalies.append(
            Anomaly(
                kind=AnomalyKind.IMMUNE_RESPONSE,
                severity=AnomalySeverity.ERROR,
                component_name=spec.name,
                message="Component name must not be empty.",
            )
        )
    elif any(c.isspace() for c in spec.name):
        anomalies.append(
            Anomaly(
                kind=AnomalyKind.IMMUNE_RESPONSE,
                severity=AnomalySeverity.WARNING,
                component_name=spec.name,
                message=(
                    f"Component name '{spec.name}' contains whitespace. "
                    f"Use PascalCase or snake_case instead."
                ),
            )
        )

    # 5. Contract completeness — meaningful intent
    if len(spec.intent) < 10:
        anomalies.append(
            Anomaly(
                kind=AnomalyKind.VESTIGIAL_ORGAN,
                severity=AnomalySeverity.WARNING,
                component_name=spec.name,
                message=(
                    f"Component intent is too short ({len(spec.intent)} chars). "
                    f"Provide a meaningful description of the component's purpose "
                    f"(at least 10 characters)."
                ),
            )
        )

    return anomalies


def explain_dependency_chain(
    registry: ComponentRegistry,
    source: str,
    target: str,
) -> str:
    """Explain why component *source* depends on component *target*.

    Traces the dependency path from *source* to *target* and explains the
    architectural reason for the relationship based on component intents
    and layer structure.

    If *source* directly declares *target* as a dependency, the explanation
    is straightforward.  If the dependency is transitive (source → A → … →
    target), the shortest path is reported.  If no dependency path exists,
    a clear "no dependency" message is returned.

    Args:
        registry: The ComponentRegistry to query.
        source: Name of the component that (potentially) depends on target.
        target: Name of the component that is (potentially) depended upon.

    Returns:
        Natural-language explanation of the dependency relationship.

    Raises:
        RegistryIntegrityError: If either component is not registered.
            Either name may be an operation a component provides; the
            explanation is then about the providing component and says so.
    """
    source_spec, source_operation = _resolve_or_raise(
        registry, source, "Cannot explain dependency"
    )
    target_spec, target_operation = _resolve_or_raise(
        registry, target, "Cannot explain dependency"
    )
    notes = [
        f"{operation} is an operation of {spec.display_name}."
        for operation, spec in (
            (source_operation, source_spec),
            (target_operation, target_spec),
        )
        if operation is not None
    ]
    source = source_spec.name
    target = target_spec.name

    # Same component
    if source == target:
        return _with_notes(
            notes,
            f"'{source}' and '{target}' are the same component. "
            f"A component cannot depend on itself.",
        )

    # BFS from source following declared dependencies to find target
    visited: set[str] = {source}
    parent: dict[str, str] = {}
    queue: deque[str] = deque([source])

    while queue:
        current = queue.popleft()
        current_spec = registry.get(current)
        if current_spec is None:
            continue
        for dep_name in current_spec.dependencies:
            if dep_name in visited:
                continue
            visited.add(dep_name)
            parent[dep_name] = current
            if dep_name == target:
                # Found — reconstruct the path
                path = _reconstruct_path(parent, source, target)
                return _with_notes(
                    notes, _format_dependency_explanation(registry, path)
                )
            queue.append(dep_name)

    # No path found
    return _with_notes(
        notes,
        f"No dependency relationship found between '{source}' and '{target}'. "
        f"'{source}' ({source_spec.kind.name.lower()}, {source_spec.layer.name.lower()}) "
        f"does not depend on '{target}' ({target_spec.kind.name.lower()}, "
        f"{target_spec.layer.name.lower()}) either directly or transitively.",
    )


def _resolve_or_raise(
    registry: ComponentRegistry,
    name: str,
    what: str,
) -> tuple[ComponentSpec, str | None]:
    """Resolve *name* through the registry, raising the analyzer's own error.

    Returns the component and, when *name* was the name of an operation
    the component provides, that operation; ``None`` for a plain
    component name. The error names every provider when an operation is
    provided by several components, so the caller can ask by component.
    """
    resolution = registry.resolve_component(name)
    if resolution.spec is not None:
        return resolution.spec, resolution.operation
    if resolution.candidates:
        raise RegistryIntegrityError(
            f"{what}: '{name}' is an operation of {len(resolution.candidates)} "
            f"components; name one of them: {', '.join(resolution.candidates)}."
        )
    raise RegistryIntegrityError(
        f"{what}: component '{name}' is not registered."
    )


def _with_notes(notes: list[str], text: str) -> str:
    """Prefix *text* with the operation notes, when there are any."""
    if not notes:
        return text
    return "\n".join([*notes, "", text])


def _reconstruct_path(
    parent: dict[str, str],
    source: str,
    target: str,
) -> list[str]:
    """Reconstruct the shortest path from source to target using the parent map."""
    path = [target]
    current = target
    while current != source:
        current = parent[current]
        path.append(current)
    path.reverse()
    return path


def _format_dependency_explanation(
    registry: ComponentRegistry,
    path: list[str],
) -> str:
    """Format a dependency path as a natural-language explanation."""
    if len(path) == 2:
        # Direct dependency
        source_spec = registry.get(path[0])
        target_spec = registry.get(path[1])
        assert source_spec is not None
        assert target_spec is not None
        lines = [
            f"Direct dependency: '{path[0]}' -> '{path[1]}'",
            "",
            f"  '{path[0]}' ({source_spec.kind.name.lower()}, "
            f"{source_spec.layer.name.lower()}):",
            f"    Intent: {source_spec.intent}",
            f"    Declares dependency on: '{path[1]}'",
            "",
            f"  '{path[1]}' ({target_spec.kind.name.lower()}, "
            f"{target_spec.layer.name.lower()}):",
            f"    Intent: {target_spec.intent}",
            "",
            f"'{path[0]}' depends on '{path[1]}' because it needs the "
            f"functionality described above to fulfil its own purpose.",
        ]
        return "\n".join(lines)

    # Transitive dependency
    lines = [
        f"Transitive dependency: {' -> '.join(path)}",
        f"(chain length: {len(path) - 1} hops)",
        "",
    ]
    for i, name in enumerate(path):
        spec = registry.get(name)
        if spec is None:
            lines.append(f"  {i + 1}. '{name}' (unregistered)")
            continue
        lines.append(
            f"  {i + 1}. '{name}' ({spec.kind.name.lower()}, "
            f"{spec.layer.name.lower()})"
        )
        lines.append(f"     Intent: {spec.intent}")
        if i < len(path) - 1:
            lines.append(f"     -> depends on '{path[i + 1]}'")
        lines.append("")

    lines.append(
        f"'{path[0]}' does not depend on '{path[-1]}' directly, but "
        f"reaches it through the chain above."
    )
    return "\n".join(lines)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _suggest_kinds_for_layer(
    layer: Layer,
    existing_kinds: set[ComponentKind],
) -> list[ComponentKind]:
    """Suggest appropriate component kinds for a given layer.

    Uses architectural conventions to recommend kinds that make sense
    in each layer, prioritizing kinds not yet present.
    """
    # Natural kind affinities by layer
    layer_kind_affinities: dict[Layer, list[ComponentKind]] = {
        Layer.DOMAIN: [
            ComponentKind.MODEL,
            ComponentKind.FUNCTION,
            ComponentKind.SERVICE,
        ],
        Layer.APPLICATION: [
            ComponentKind.ORCHESTRATOR,
            ComponentKind.SERVICE,
            ComponentKind.FUNCTION,
        ],
        Layer.INFRASTRUCTURE: [
            ComponentKind.ADAPTER,
            ComponentKind.SERVICE,
            ComponentKind.FUNCTION,
        ],
        Layer.PRESENTATION: [
            ComponentKind.FUNCTION,
            ComponentKind.ADAPTER,
            ComponentKind.ORCHESTRATOR,
        ],
        Layer.FRAMEWORK: [
            ComponentKind.FRAMEWORK,
        ],
    }

    affinities = layer_kind_affinities.get(layer, [])

    # Prioritize kinds not yet present in this layer
    novel = [k for k in affinities if k not in existing_kinds]
    existing = [k for k in affinities if k in existing_kinds]

    return novel + existing if novel else affinities


def _find_potential_dependencies(
    layer: Layer,
    all_components: dict[str, Any],
    dependency_graph: dict[str, list[str]],
) -> list[str]:
    """Find components that could serve as dependencies for new components
    in the given layer.

    Components in the same layer or in layers that this layer
    conventionally depends on are preferred.
    """
    # Layers that each layer can conventionally depend on
    allowed_deps: dict[Layer, set[Layer]] = {
        Layer.PRESENTATION: {
            Layer.APPLICATION,
            Layer.DOMAIN,
            Layer.INFRASTRUCTURE,
            Layer.FRAMEWORK,
        },
        Layer.APPLICATION: {
            Layer.DOMAIN,
            Layer.INFRASTRUCTURE,
            Layer.FRAMEWORK,
        },
        Layer.DOMAIN: {
            Layer.DOMAIN,
            Layer.FRAMEWORK,
        },
        Layer.INFRASTRUCTURE: {
            Layer.DOMAIN,
            Layer.FRAMEWORK,
        },
        Layer.FRAMEWORK: {
            Layer.FRAMEWORK,
        },
    }

    valid_layers = allowed_deps.get(layer, set())
    # Also allow same-layer dependencies
    valid_layers.add(layer)

    candidates: list[str] = []
    for spec in all_components.values():
        if spec.layer in valid_layers and not spec.is_framework:
            candidates.append(spec.name)

    # Sort by how many things already depend on them (popular = stable API)
    dependent_counts: dict[str, int] = {}
    for deps in dependency_graph.values():
        for dep in deps:
            dependent_counts[dep] = dependent_counts.get(dep, 0) + 1

    return sorted(
        candidates,
        key=lambda name: dependent_counts.get(name, 0),
        reverse=True,
    )[:10]  # Limit to top 10 most useful targets


def _check_layer_violation(
    source_layer: Layer,
    target_layer: Layer,
) -> str | None:
    """Check if a dependency from source_layer to target_layer violates
    architectural conventions.

    Returns a violation message or None if the dependency is valid.
    """
    # Framework components can depend on anything
    if source_layer == Layer.FRAMEWORK:
        return None

    # Dependencies on framework are always OK
    if target_layer == Layer.FRAMEWORK:
        return None

    # Same-layer dependencies are OK
    if source_layer == target_layer:
        return None

    # Layer hierarchy (higher layers can depend on lower layers)
    layer_order: dict[Layer, int] = {
        Layer.PRESENTATION: 4,
        Layer.APPLICATION: 3,
        Layer.INFRASTRUCTURE: 2,
        Layer.DOMAIN: 1,
        Layer.FRAMEWORK: 0,
    }

    source_level = layer_order.get(source_layer, 0)
    target_level = layer_order.get(target_layer, 0)

    # Upward dependency (lower layer depending on higher layer)
    if source_level < target_level:
        return (
            f"Layer violation: {source_layer.name} -> {target_layer.name}. "
            f"Lower layers should not depend on higher layers. "
            f"Consider inverting the dependency or moving the component."
        )

    return None
