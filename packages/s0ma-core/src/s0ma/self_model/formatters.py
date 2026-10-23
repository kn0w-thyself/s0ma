"""Text formatters for the self-model query API.

These functions transform S0ma data structures (ComponentSpec,
Contract, RegistrySnapshot, VerificationReport, dependency graphs)
into natural language text optimized for LLM consumption.

Design principles:
- All output is plain text (no raw data structures, no repr())
- Text is structured with headers, indentation, and bullet points
- Content is information-dense but human-readable
- Suitable for injection into LLM system prompts or context windows
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from s0ma.models import (
        ComponentSpec,
        Contract,
        DocGuideRegistration,
        DocRefRegistration,
        ExampleRegistration,
        LifecycleEvent,
        RegistrySnapshot,
        VerificationReport,
    )
    from s0ma.self_model.analyzers import ExtensionPoint, ImpactReport

__all__ = [
    "format_component_summary",
    "format_dependency_graph_text",
    "format_dependency_graph_dot",
    "format_layer_breakdown",
    "format_health_summary",
    "format_contracts_text",
    "format_impact_report",
    "format_extension_points",
    "format_lifecycle_events",
    "format_code_generation_context",
    "format_doc_refs_overview",
    "format_doc_ref_detail",
    "format_doc_guide_detail",
    "format_docs_for_component",
    "format_examples_for_component",
    "format_drift_status",
]


def format_component_summary(spec: ComponentSpec) -> str:
    """Format a single component as a concise text block.

    Produces a compact summary including name, kind, layer, intent,
    version, and dependency count. Suitable for use in lists or as
    a quick-reference entry.

    Args:
        spec: The ComponentSpec to format.

    Returns:
        A multi-line text summary of the component.
    """
    lines: list[str] = []
    lines.append(f"{spec.name} ({spec.kind.name.lower()}, {spec.layer.name.lower()})")
    lines.append(f"  Intent: {spec.intent}")
    if spec.version and spec.version != "0.1.0":
        lines.append(f"  Version: {spec.version}")
    if spec.dependencies:
        dep_str = ", ".join(spec.dependencies)
        lines.append(f"  Dependencies: {dep_str}")
    if spec.is_framework:
        lines.append("  [framework component]")
    return "\n".join(lines)


def format_component_detail(spec: ComponentSpec) -> str:
    """Format a component with full detail for LLM context.

    Includes all available metadata: identity, contracts, the operations
    the component provides with their per-operation contracts,
    dependencies, resource profile, and source location. Designed for the
    ``describe_component()`` method.

    Args:
        spec: The ComponentSpec to format.

    Returns:
        A comprehensive multi-line text description.
    """
    lines: list[str] = []

    # Identity block
    lines.append(f"## {spec.name}")
    lines.append(f"Kind: {spec.kind.name.lower()}")
    lines.append(f"Layer: {spec.layer.name.lower()}")
    lines.append(f"Version: {spec.version}")
    if spec.is_framework:
        lines.append("Role: Framework infrastructure component")
    lines.append("")

    # Intent
    lines.append(f"Purpose: {spec.intent}")
    lines.append("")

    # Contracts
    contracts_text = format_contracts_text(spec.contracts)
    if contracts_text:
        lines.append("Contracts:")
        lines.append(contracts_text)
        lines.append("")

    # Operations: the ``provides:`` list, with the per-operation contract
    # under each operation that authored one. This is where a reader
    # learns that ``pip_install`` is an operation of this component and
    # what that operation expects and guarantees; before these lines the
    # per-operation contracts stopped at registry metadata nothing read.
    operations = spec.provides
    if operations:
        contracts_by_name = {
            contract.name: contract for contract in spec.provides_contracts
        }
        lines.append("Operations (provides):")
        for operation in operations:
            lines.append(f"  - {operation}")
            contract = contracts_by_name.get(operation)
            if contract is None:
                continue
            if contract.expects is not None:
                lines.append(f"      Expects: {contract.expects}")
            if contract.guarantees is not None:
                lines.append(f"      Guarantees: {contract.guarantees}")
            if contract.returns is not None:
                lines.append(f"      Returns: {contract.returns}")
        lines.append("")

    # Dependencies
    if spec.dependencies:
        lines.append("Dependencies (components this uses):")
        for dep in spec.dependencies:
            lines.append(f"  - {dep}")
        lines.append("")

    # Resource profile
    if spec.resource_profile is not None:
        rp = spec.resource_profile
        lines.append("Resource Profile:")
        if rp.expected_memory_mb is not None:
            lines.append(f"  Expected memory: {rp.expected_memory_mb} MB")
        if rp.expected_latency_p50_ms is not None:
            lines.append(f"  Expected latency (p50): {rp.expected_latency_p50_ms} ms")
        if rp.expected_latency_p99_ms is not None:
            lines.append(f"  Expected latency (p99): {rp.expected_latency_p99_ms} ms")
        if rp.expected_error_rate is not None:
            lines.append(
                f"  Expected error rate: {rp.expected_error_rate:.1%}"
            )
        if rp.expected_call_frequency_per_min is not None:
            lines.append(
                f"  Expected call frequency: "
                f"{rp.expected_call_frequency_per_min}/min"
            )
        if rp.expected_max_current_ma is not None:
            lines.append(
                f"  Expected max current draw: {rp.expected_max_current_ma} mA"
            )
        if rp.expected_max_temperature_c is not None:
            lines.append(
                f"  Expected max temperature: {rp.expected_max_temperature_c} °C"
            )
        if rp.expected_min_voltage_v is not None:
            lines.append(
                f"  Expected min supply voltage: {rp.expected_min_voltage_v} V"
            )
        lines.append("")

    # Source location
    if spec.module_path:
        lines.append(f"Module: {spec.module_path}")
    if spec.source_file:
        lines.append(f"Source: {spec.source_file}")

    return "\n".join(lines)


def format_dependency_graph_text(
    graph: dict[str, list[str]],
) -> str:
    """Format a dependency graph as readable text.

    Produces an indented adjacency list showing which components
    depend on which others. Components with no dependencies are
    listed as leaf nodes.

    Args:
        graph: Adjacency list mapping component names to their
            dependency lists.

    Returns:
        A multi-line text representation of the dependency graph.
        Returns a short message if the graph is empty.
    """
    if not graph:
        return "No dependency relationships declared."

    # Separate components with and without dependencies
    has_deps = {name: deps for name, deps in graph.items() if deps}
    no_deps = [name for name, deps in graph.items() if not deps]

    if not has_deps and not no_deps:
        return "No dependency relationships declared."

    lines: list[str] = []

    if has_deps:
        lines.append("Dependency relationships:")
        for name in sorted(has_deps):
            deps = sorted(has_deps[name])
            dep_str = ", ".join(deps)
            lines.append(f"  {name} -> {dep_str}")

    if no_deps:
        if lines:
            lines.append("")
        lines.append(
            f"Independent components (no declared dependencies): "
            f"{', '.join(sorted(no_deps))}"
        )

    return "\n".join(lines)


def format_layer_breakdown(
    components: dict[str, ComponentSpec],
) -> str:
    """Format components grouped by architectural layer.

    Produces a structured breakdown showing each layer, the number
    of components in it, and a brief listing of each component.

    Args:
        components: All components, keyed by name.

    Returns:
        A multi-line text breakdown organized by layer.
    """
    from s0ma.types import Layer

    # Group components by layer
    by_layer: dict[str, list[ComponentSpec]] = {}
    for spec in components.values():
        layer_name = spec.layer.name
        if layer_name not in by_layer:
            by_layer[layer_name] = []
        by_layer[layer_name].append(spec)

    if not by_layer:
        return "No components registered."

    lines: list[str] = []
    lines.append("Components by architectural layer:")
    lines.append("")

    # Use Layer enum ordering for consistent display
    for layer in Layer:
        layer_name = layer.name
        specs = by_layer.get(layer_name, [])
        if not specs:
            continue

        lines.append(f"[{layer_name}] ({len(specs)} components)")
        for spec in sorted(specs, key=lambda s: s.name):
            kind_label = spec.kind.name.lower()
            lines.append(f"  - {spec.name} ({kind_label}): {spec.intent}")
        lines.append("")

    return "\n".join(lines).rstrip()


def format_health_summary(
    report: VerificationReport | None,
) -> str:
    """Format verification results as a health summary.

    Produces a concise health status suitable for inclusion in
    system descriptions. Handles the case where no verification
    data is available.

    Args:
        report: The VerificationReport to summarize, or None if
            no verification has been run.

    Returns:
        A multi-line text health summary.
    """
    if report is None:
        return "Health status: No verification data available."

    lines: list[str] = []
    status = "HEALTHY" if report.passed else "UNHEALTHY"
    lines.append(f"Health status: {status}")
    lines.append(
        f"  Verifiers run: {len(report.results)}, "
        f"Duration: {report.total_duration_ms:.1f}ms"
    )

    if report.total_anomalies == 0:
        lines.append("  No anomalies detected.")
    else:
        lines.append(
            f"  Anomalies: {report.total_anomalies} total "
            f"({report.total_errors} errors, "
            f"{report.total_warnings} warnings)"
        )

        # List individual verifier results
        for result in report.results:
            result_status = "passed" if result.passed else "FAILED"
            lines.append(
                f"  - {result.verifier_name} ({result.scope.name}): "
                f"{result_status}"
            )
            if result.anomalies:
                for anomaly in result.anomalies[:3]:
                    lines.append(
                        f"    [{anomaly.severity.name}] {anomaly.message}"
                    )
                remaining = len(result.anomalies) - 3
                if remaining > 0:
                    lines.append(f"    ... and {remaining} more")

    # Include erosion coverage if available
    for result in report.results:
        erosion = result.details.get("erosion_coverage")
        if erosion and isinstance(erosion, dict):
            lines.append("")
            lines.append("Erosion control coverage (de Silva et al.):")
            lines.append(
                f"  Minimise: "
                f"{'active' if erosion.get('minimise_active') else 'inactive'} "
                f"({erosion.get('minimise_coverage', 0.0):.0%})"
            )
            lines.append(
                f"  Prevent: "
                f"{'active' if erosion.get('prevent_active') else 'inactive'} "
                f"({erosion.get('prevent_coverage', 0.0):.0%})"
            )
            lines.append(
                f"  Repair: "
                f"{'active' if erosion.get('repair_active') else 'inactive'} "
                f"({erosion.get('repair_coverage', 0.0):.0%})"
            )
            break  # Only include once

    # Include automation metric if available
    for result in report.results:
        automation = result.details.get("automation_metric")
        if automation is not None:
            lines.append(
                f"  Automation metric (Kounev & Spinner): {automation:.0%}"
            )
            break  # Only include once

    return "\n".join(lines)


def format_contracts_text(contracts: Contract) -> str:
    """Format a component's contracts as readable text.

    Produces a bulleted list of preconditions, postconditions,
    invariants, forbids (what the component must never do), and
    performance constraints.

    Args:
        contracts: The Contract to format.

    Returns:
        Formatted text, or empty string if the contract has
        no meaningful content.
    """
    lines: list[str] = []

    if contracts.preconditions:
        lines.append("  Preconditions:")
        for pre in contracts.preconditions:
            lines.append(f"    - {pre}")

    if contracts.postconditions:
        lines.append("  Postconditions:")
        for post in contracts.postconditions:
            lines.append(f"    - {post}")

    if contracts.invariants:
        lines.append("  Invariants:")
        for inv in contracts.invariants:
            lines.append(f"    - {inv}")

    if contracts.forbids:
        lines.append("  Forbids:")
        for forbidden in contracts.forbids:
            lines.append(f"    - {forbidden}")

    if contracts.max_latency_ms is not None:
        lines.append(
            f"  Max latency: {contracts.max_latency_ms}ms"
        )

    if contracts.error_rate_threshold is not None:
        lines.append(
            f"  Error rate threshold: {contracts.error_rate_threshold:.1%}"
        )

    # Configurable properties
    if contracts.configurable_properties:
        lines.append("  Configurable Properties:")
        for prop_name, prop in contracts.configurable_properties.items():
            # Format: name (type): default_value - description
            prop_line = f"    - {prop_name} ({prop.type}): default={prop.default}"
            if prop.description:
                prop_line += f" — {prop.description}"
            lines.append(prop_line)
            # Add constraints if present
            if prop.constraints:
                constraint_parts = []
                if "min" in prop.constraints and "max" in prop.constraints:
                    constraint_parts.append(
                        f"range [{prop.constraints['min']}..{prop.constraints['max']}]"
                    )
                elif "min" in prop.constraints:
                    constraint_parts.append(f"min {prop.constraints['min']}")
                elif "max" in prop.constraints:
                    constraint_parts.append(f"max {prop.constraints['max']}")
                if "allowed_values" in prop.constraints:
                    values = ", ".join(str(v) for v in prop.constraints["allowed_values"])
                    constraint_parts.append(f"values: {values}")
                if constraint_parts:
                    lines.append(f"      Constraints: {', '.join(constraint_parts)}")

    # Protocol contract
    if contracts.protocol:
        proto = contracts.protocol
        msg_names = ", ".join(sorted(proto.message_types.keys()))
        lines.append(
            f"  Protocol ({proto.protocol_type}): "
            f"message types: {msg_names}"
        )
        if proto.description:
            lines.append(f"    {proto.description}")
        for msg_name, schema in sorted(proto.message_types.items()):
            if schema:
                schema_summary = ", ".join(
                    f"{k}: {v}" for k, v in schema.items()
                )
                lines.append(f"    {msg_name}: {schema_summary}")

    return "\n".join(lines)


def format_impact_report(report: ImpactReport) -> str:
    """Format an impact analysis as natural language text.

    Produces a structured description of what would be affected
    if a component changes, including risk level, direct and
    transitive dependents, and affected layers.

    Args:
        report: The ImpactReport to format.

    Returns:
        Natural language text suitable for LLM consumption.
    """
    lines: list[str] = []

    lines.append(f"## Impact Analysis: {report.component_name}")
    lines.append("")
    operation = report.details.get("operation")
    if isinstance(operation, str):
        lines.append(
            f"{operation} is an operation of {report.component_name}; "
            f"this is the impact of that component."
        )
        lines.append("")
    lines.append(f"Risk level: {report.risk_level.upper()}")
    lines.append(
        f"Total components affected: {report.total_affected_count}"
    )
    if report.max_dependency_depth > 0:
        lines.append(
            f"Maximum dependency depth: {report.max_dependency_depth}"
        )
    lines.append("")

    if report.direct_dependents:
        lines.append(
            f"Direct dependents ({len(report.direct_dependents)}):"
        )
        for dep in report.direct_dependents:
            lines.append(f"  - {dep}")
        lines.append("")
    else:
        lines.append(
            "No components directly depend on this component."
        )
        lines.append("")

    if report.transitive_dependents:
        lines.append(
            f"Transitive dependents ({len(report.transitive_dependents)}):"
        )
        for dep in report.transitive_dependents:
            lines.append(f"  - {dep}")
        lines.append("")

    if report.affected_layers:
        layer_names = [layer.name for layer in report.affected_layers]
        lines.append(
            f"Affected layers: {', '.join(layer_names)}"
        )
        lines.append("")

    if report.affected_docs:
        lines.append(
            f"Affected documentation ({len(report.affected_docs)}):"
        )
        for doc_name in report.affected_docs:
            lines.append(f"  - {doc_name}")
        lines.append("")

    if report.affected_examples:
        lines.append(
            f"Affected examples ({len(report.affected_examples)}):"
        )
        for ex_name in report.affected_examples:
            lines.append(f"  - {ex_name}")
        lines.append("")

    # Risk-level-specific guidance
    if report.risk_level == "high":
        lines.append(
            "WARNING: This is a high-impact component. Changes should be "
            "carefully reviewed and tested. Consider making changes "
            "incrementally with verification after each step."
        )
    elif report.risk_level == "medium":
        lines.append(
            "This component has moderate impact. Changes may affect "
            "a few other components. Verify dependents after modification."
        )
    else:
        lines.append(
            "This component has low impact. Changes are unlikely to "
            "affect other components."
        )

    return "\n".join(lines)


def format_extension_points(points: list[ExtensionPoint]) -> str:
    """Format extension points as actionable text for LLM planning.

    Produces a structured description of where new components can
    be safely added, organized by architectural layer.

    Args:
        points: List of ExtensionPoint objects to format.

    Returns:
        Natural language text suitable for LLM planning.
    """
    if not points:
        return "No extension points identified in the current architecture."

    lines: list[str] = []
    lines.append("## Available Extension Points")
    lines.append("")
    lines.append(
        "The following locations are available for adding new components "
        "without violating architectural constraints:"
    )
    lines.append("")

    for i, point in enumerate(points, 1):
        lines.append(f"### {i}. {point.layer.name} Layer")
        lines.append("")
        lines.append(point.rationale)
        lines.append("")

        kind_names = [k.name.lower() for k in point.suggested_kinds]
        lines.append(f"Suggested component kinds: {', '.join(kind_names)}")

        if point.potential_dependencies:
            lines.append("Potential dependency targets:")
            for dep in point.potential_dependencies[:5]:
                lines.append(f"  - {dep}")
        else:
            lines.append("No existing dependency targets in valid layers.")

        lines.append("")

    return "\n".join(lines).rstrip()


def format_lifecycle_events(events: list[LifecycleEvent]) -> str:
    """Format lifecycle events as a natural language change log.

    Produces a readable history of recent lifecycle operations
    (create, update, remove) suitable for LLM context about what
    has changed in the system recently.

    Args:
        events: List of LifecycleEvent objects to format, in
            chronological order (oldest first).

    Returns:
        Natural language text describing recent changes. Returns
        a short message if no events exist.
    """
    if not events:
        return "No lifecycle changes recorded."

    lines: list[str] = []
    lines.append("## Recent Lifecycle Changes")
    lines.append("")

    for event in events:
        action_label = event.action.name.lower().replace("_", " ")
        status = "succeeded" if event.success else "FAILED"
        timestamp = event.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        lines.append(
            f"- [{timestamp}] {action_label} '{event.component_name}': "
            f"{status}"
        )

        if event.details:
            detail_parts: list[str] = []
            for key, value in sorted(event.details.items()):
                detail_parts.append(f"{key}={value}")
            if detail_parts:
                lines.append(f"    Details: {', '.join(detail_parts)}")

        if not event.success and event.error_message:
            # Truncate long error messages for readability
            msg = event.error_message
            if len(msg) > 200:
                msg = msg[:197] + "..."
            lines.append(f"    Error: {msg}")

    lines.append("")
    total = len(events)
    succeeded = sum(1 for e in events if e.success)
    failed = total - succeeded
    lines.append(
        f"Total: {total} operations "
        f"({succeeded} succeeded, {failed} failed)"
    )

    return "\n".join(lines)


def format_code_generation_context(
    components: dict[str, ComponentSpec],
    target_package: str,
    *,
    include_contracts: bool = True,
    include_configurable_properties: bool = True,
) -> str:
    """Format self-model output optimized for LLM code generation prompts.

    Produces audience-aware output that reduces common LLM pitfalls:
    - Framework module paths are annotated as non-importable (not pattern-matched
      as valid import roots for generated code).
    - Layer names are explicitly called out as classification labels so LLMs don't
      treat them as Python package directories.
    - A filled-in ``@component`` decorator template anchors the target package.

    Args:
        components: All registered components, keyed by name.
        target_package: The Python package where generated code will live
            (e.g., ``"myapp.services"``). Used to build import guidance and
            the decorator template.
        include_contracts: Whether to include contract details per component.
        include_configurable_properties: Whether to include configurable
            property schemas for components that declare them.

    Returns:
        LLM-optimized text describing the system for code generation.
    """
    lines: list[str] = []

    # Header
    lines.append("# System Context for Code Generation")
    lines.append("")

    # Import guidance
    lines.append("## Import Guidance")
    lines.append(
        f"Generated code should import from: `{target_package}.*`. "
        "Do not import from `s0ma.*` or other framework packages — "
        "these are platform internals not available in generated code."
    )
    lines.append("")

    # Layer annotation note
    lines.append("## Architectural Layers")
    lines.append(
        "Layer values (DOMAIN, APPLICATION, INFRASTRUCTURE, PRESENTATION) are "
        "architectural classification labels, not Python packages or directories. "
        "Do not use layer names as package paths in import statements."
    )
    lines.append("")

    # Separate framework vs. application components
    framework_comps = sorted(
        (spec for spec in components.values() if spec.is_framework),
        key=lambda s: s.name,
    )
    user_comps = sorted(
        (spec for spec in components.values() if not spec.is_framework),
        key=lambda s: s.name,
    )

    # Component list
    lines.append("## System Components")
    lines.append("")

    if framework_comps:
        lines.append(
            "### Platform Components (platform internal — not for import)"
        )
        for spec in framework_comps:
            lines.append(
                f"- {spec.name} ({spec.kind.name.lower()}): {spec.intent}"
            )
        lines.append("")

    if user_comps:
        lines.append("### Application Components")
        for spec in user_comps:
            import_hint = (
                f" — importable from `{spec.module_path}`"
                if spec.module_path
                else ""
            )
            lines.append(
                f"- {spec.name} ({spec.kind.name.lower()}, "
                f"{spec.layer.name}): {spec.intent}{import_hint}"
            )
            if include_contracts:
                contracts_text = format_contracts_text(spec.contracts)
                if contracts_text:
                    lines.append(contracts_text)
            else:
                # Even without full contracts, show configurable properties
                # and protocol schemas since they're critical for code generation
                if (
                    include_configurable_properties
                    and spec.contracts
                    and spec.contracts.configurable_properties
                ):
                    lines.append("  Configurable Properties:")
                    for prop_name, prop in spec.contracts.configurable_properties.items():
                        prop_line = (
                            f"    - {prop_name} ({prop.type}): "
                            f"default={prop.default}"
                        )
                        if prop.description:
                            prop_line += f" — {prop.description}"
                        lines.append(prop_line)
                if spec.contracts and spec.contracts.protocol:
                    proto = spec.contracts.protocol
                    msg_names = ", ".join(sorted(proto.message_types.keys()))
                    lines.append(
                        f"  Protocol ({proto.protocol_type}): "
                        f"message types: {msg_names}"
                    )
        lines.append("")

    # @component decorator template
    lines.append("## @component Decorator Template")
    lines.append(
        f"Use this template when defining new components in `{target_package}`:"
    )
    lines.append("")
    lines.append("```python")
    lines.append("from s0ma import component")
    lines.append("from s0ma.models import Contract")
    lines.append("from s0ma.types import ComponentKind, Layer")
    lines.append("")
    lines.append("@component(")
    lines.append('    name="YourComponentName",')
    lines.append("    kind=ComponentKind.SERVICE,  # classification label, not a directory")
    lines.append("    layer=Layer.DOMAIN,  # label only — not a package path")
    lines.append('    intent="Describe what this component does",')
    lines.append("    contracts=Contract(")
    lines.append('        preconditions=["input is valid"],')
    lines.append('        postconditions=["returns expected result"],')
    lines.append("    ),")
    lines.append(")")
    lines.append("class YourComponentName:")
    lines.append(f'    """Component in {target_package}."""')
    lines.append("```")

    return "\n".join(lines)


def format_dependency_graph_dot(
    graph: dict[str, list[str]],
    components: dict[str, ComponentSpec] | None = None,
) -> str:
    """Format a dependency graph as Graphviz DOT for visualization.

    Produces a DOT-language representation of the dependency graph
    suitable for rendering with Graphviz. When component specs are
    provided, nodes are colored by architectural layer.

    Args:
        graph: Adjacency list mapping component names to their
            dependency lists.
        components: Optional dict of ComponentSpec keyed by name.
            When provided, nodes are styled by layer.

    Returns:
        A string in DOT format. Returns a minimal empty digraph
        if the graph has no edges.
    """
    lines: list[str] = []
    lines.append("digraph s0ma {")
    lines.append("  rankdir=LR;")
    lines.append('  node [shape=box, style=filled, fontname="Helvetica"];')
    lines.append("")

    # Layer-to-color mapping for visual distinction
    layer_colors: dict[str, str] = {
        "DOMAIN": "#E8F5E9",
        "APPLICATION": "#E3F2FD",
        "INFRASTRUCTURE": "#FFF3E0",
        "PRESENTATION": "#F3E5F5",
        "FRAMEWORK": "#F5F5F5",
    }

    # Emit node definitions with layer-based coloring
    all_nodes: set[str] = set(graph.keys())
    for deps in graph.values():
        all_nodes.update(deps)

    for node_name in sorted(all_nodes):
        attrs: list[str] = []
        if components and node_name in components:
            spec = components[node_name]
            layer_name = spec.layer.name
            color = layer_colors.get(layer_name, "#FFFFFF")
            attrs.append(f'fillcolor="{color}"')
            attrs.append(f'tooltip="{spec.intent[:80]}"')
            label = f"{node_name}\\n({spec.kind.name.lower()})"
            attrs.append(f'label="{label}"')
        else:
            attrs.append(f'label="{node_name}"')

        attr_str = ", ".join(attrs)
        lines.append(f'  "{node_name}" [{attr_str}];')

    lines.append("")

    # Emit edges
    for source in sorted(graph.keys()):
        for target in sorted(graph[source]):
            lines.append(f'  "{source}" -> "{target}";')

    lines.append("}")
    return "\n".join(lines)


def format_doc_refs_overview(
    doc_refs: dict[str, DocRefRegistration],
    doc_guides: dict[str, DocGuideRegistration],
    examples: dict[str, ExampleRegistration],
) -> str:
    """Format a registry-wide documentation overview.

    Produces a compact listing of all registered doc-refs, doc-guides,
    and examples suitable for answering "what docs does this system
    have?" from an LLM prompt.

    Args:
        doc_refs: All registered ``DocRefRegistration`` entries, keyed
            by name.
        doc_guides: All registered ``DocGuideRegistration`` entries,
            keyed by name.
        examples: All registered ``ExampleRegistration`` entries, keyed
            by name. Included so callers get a single natural-language
            summary of the documentation surface.

    Returns:
        Multi-line natural language text. Returns a short informative
        message when no documentation is registered.
    """
    if not doc_refs and not doc_guides and not examples:
        return (
            "No documentation artifacts registered. The documentation "
            "subsystem is in place but no doc-ref, doc-guide, or "
            "example declarations have been registered yet."
        )

    lines: list[str] = []
    lines.append("# Documentation Overview")
    lines.append("")
    lines.append(
        f"Registered artifacts: {len(doc_refs)} doc-ref(s), "
        f"{len(doc_guides)} doc-guide(s), {len(examples)} example(s)."
    )
    lines.append("")

    if doc_refs:
        lines.append("## Doc-refs (generated documentation)")
        for ref_name in sorted(doc_refs):
            ref = doc_refs[ref_name]
            lines.append(
                f"- {ref_name} ({ref.format} -> {ref.output})"
            )
            lines.append(f"    Intent: {ref.intent}")
            if ref.covers:
                covers_summary = ", ".join(c.raw for c in ref.covers)
                lines.append(f"    Covers: {covers_summary}")
        lines.append("")

    if doc_guides:
        lines.append("## Doc-guides (authored prose)")
        for guide_name in sorted(doc_guides):
            guide = doc_guides[guide_name]
            lines.append(
                f"- {guide_name} ({guide.format} -> {guide.output})"
            )
            lines.append(f"    Intent: {guide.intent}")
            if guide.covers:
                covers_summary = ", ".join(
                    f"{c.kind}:{c.name}" for c in guide.covers
                )
                lines.append(f"    Covers: {covers_summary}")
            if guide.examples:
                ex_summary = ", ".join(e.name for e in guide.examples)
                lines.append(f"    Examples: {ex_summary}")
        lines.append("")

    if examples:
        lines.append("## Examples (canonical runnable code)")
        for ex_name in sorted(examples):
            ex = examples[ex_name]
            demo_summary = ", ".join(
                f"{d.kind}:{d.name}" for d in ex.demonstrates
            )
            lines.append(f"- {ex_name} (runs_in={ex.runs_in})")
            lines.append(f"    Intent: {ex.intent}")
            lines.append(f"    Demonstrates: {demo_summary}")
        lines.append("")

    return "\n".join(lines).rstrip()


def format_doc_ref_detail(ref: DocRefRegistration) -> str:
    """Format a single ``DocRefRegistration`` as a full detail block."""
    lines: list[str] = []
    lines.append(f"## doc-ref: {ref.name}")
    lines.append(f"Module: {ref.module}")
    lines.append(f"Format: {ref.format}")
    lines.append(f"Output: {ref.output}")
    lines.append("")
    lines.append(f"Intent: {ref.intent}")
    lines.append("")

    if ref.covers:
        lines.append("Covers (filter expressions):")
        for cov in ref.covers:
            lines.append(f"  - target_kind={cov.target_kind}: {cov.raw}")
            if cov.predicate:
                lines.append(f"    predicate: {cov.predicate}")
        lines.append("")

    if ref.sections:
        lines.append("Sections:")
        for section in ref.sections:
            bits: list[str] = [section.title]
            if section.iterate:
                bits.append(f"iterate={section.iterate}")
            if section.group_by:
                bits.append(f"group_by={section.group_by}")
            lines.append(f"  - {' | '.join(bits)}")
        lines.append("")

    if ref.content_hash:
        lines.append(f"Content hash: {ref.content_hash}")
    else:
        lines.append("Content hash: (not set)")

    if ref.source_span is not None:
        span = ref.source_span
        lines.append(
            f"Source: {span.file}:{span.start_line}-{span.end_line}"
        )

    return "\n".join(lines).rstrip()


def format_doc_guide_detail(guide: DocGuideRegistration) -> str:
    """Format a single ``DocGuideRegistration`` as a full detail block."""
    lines: list[str] = []
    lines.append(f"## doc-guide: {guide.name}")
    lines.append(f"Module: {guide.module}")
    lines.append(f"Format: {guide.format}")
    lines.append(f"Output: {guide.output}")
    lines.append("")
    lines.append(f"Intent: {guide.intent}")
    lines.append("")

    if guide.covers:
        lines.append("Covers (typed entity references):")
        for cov in guide.covers:
            module_part = f" @ {cov.module}" if cov.module else ""
            lines.append(f"  - {cov.kind}:{cov.name}{module_part}")
        lines.append("")

    if guide.asserts:
        lines.append("Assertions:")
        for assertion in guide.asserts:
            lines.append(f"  - {assertion.expression}")
        lines.append("")

    if guide.examples:
        lines.append("Referenced examples:")
        for example in guide.examples:
            module_part = (
                f" @ {example.module}" if example.module else ""
            )
            lines.append(f"  - {example.name}{module_part}")
        lines.append("")

    if guide.body:
        body_preview = guide.body.strip()
        if len(body_preview) > 400:
            body_preview = body_preview[:397] + "..."
        lines.append("Body preview:")
        for body_line in body_preview.splitlines():
            lines.append(f"  {body_line}")
        lines.append("")

    if guide.content_hash:
        lines.append(f"Content hash: {guide.content_hash}")
    else:
        lines.append("Content hash: (not set)")

    if guide.source_span is not None:
        span = guide.source_span
        lines.append(
            f"Source: {span.file}:{span.start_line}-{span.end_line}"
        )

    return "\n".join(lines).rstrip()


def format_example_detail(example: ExampleRegistration) -> str:
    """Format a single ``ExampleRegistration`` as a full detail block."""
    lines: list[str] = []
    lines.append(f"## example: {example.name}")
    lines.append(f"Module: {example.module}")
    lines.append(f"Runs in: {example.runs_in}")
    lines.append("")
    lines.append(f"Intent: {example.intent}")
    lines.append("")

    if example.demonstrates:
        lines.append("Demonstrates:")
        for entity in example.demonstrates:
            module_part = (
                f" @ {entity.module}" if entity.module else ""
            )
            lines.append(f"  - {entity.kind}:{entity.name}{module_part}")
        lines.append("")

    if example.body:
        lines.append("Body:")
        for body_line in example.body.rstrip().splitlines():
            lines.append(f"  {body_line}")
        lines.append("")

    if example.source_span is not None:
        span = example.source_span
        lines.append(
            f"Source: {span.file}:{span.start_line}-{span.end_line}"
        )

    return "\n".join(lines).rstrip()


def format_docs_for_component(
    component_name: str,
    refs: list[DocRefRegistration],
    guides: list[DocGuideRegistration],
) -> str:
    """Format the docs that cover a named component.

    Args:
        component_name: The component being queried.
        refs: Matching ``DocRefRegistration`` entries (may be empty).
        guides: Matching ``DocGuideRegistration`` entries (may be empty).

    Returns:
        Multi-line natural language text. If no docs match, the returned
        text explicitly says so.
    """
    if not refs and not guides:
        return (
            f"No documentation artifacts cover '{component_name}'. "
            f"Neither a doc-ref filter nor a doc-guide's covers list "
            f"references this component."
        )

    lines: list[str] = []
    lines.append(f"## Documentation covering '{component_name}'")
    lines.append("")
    lines.append(
        f"Matches: {len(refs)} doc-ref(s), {len(guides)} doc-guide(s)."
    )
    lines.append("")

    if refs:
        lines.append("Doc-refs:")
        for ref in refs:
            lines.append(
                f"  - {ref.name} ({ref.format} -> {ref.output}): "
                f"{ref.intent}"
            )
        lines.append("")

    if guides:
        lines.append("Doc-guides:")
        for guide in guides:
            lines.append(
                f"  - {guide.name} ({guide.format} -> {guide.output}): "
                f"{guide.intent}"
            )
        lines.append("")

    return "\n".join(lines).rstrip()


def format_examples_for_component(
    component_name: str,
    examples: list[ExampleRegistration],
) -> str:
    """Format the canonical examples demonstrating a named component."""
    if not examples:
        return (
            f"No canonical examples demonstrate '{component_name}'. "
            f"Add an ``example`` declaration with this component in its "
            f"``demonstrates`` list to surface it here."
        )

    lines: list[str] = []
    lines.append(f"## Examples demonstrating '{component_name}'")
    lines.append("")
    lines.append(f"Matches: {len(examples)} example(s).")
    lines.append("")

    for example in examples:
        lines.append(
            f"- {example.name} (runs_in={example.runs_in}): "
            f"{example.intent}"
        )
    lines.append("")

    return "\n".join(lines).rstrip()


def format_drift_status(
    snapshot: RegistrySnapshot,
    *,
    recomputed_hashes: dict[str, str] | None = None,
) -> str:
    """Format a drift-status report for the documentation subsystem.

    When ``recomputed_hashes`` is provided (M7 and later), the report
    pairs each stored ``content_hash`` against the freshly-recomputed
    value and flags divergence as drift. When it is absent (fallback
    path), the report degrades to hash-presence reporting only — this
    keeps the formatter usable by callers that have not yet wired the
    content-hash utility.

    Args:
        snapshot: A :class:`RegistrySnapshot` produced by
            ``ComponentRegistry.snapshot()``.
        recomputed_hashes: Optional mapping from a canonical
            ``"<kind>:<name>"`` key (``"doc-ref:foo"`` or
            ``"doc-guide:bar"``) to the freshly-recomputed content
            hash. When omitted, no drift comparison is performed.

    Returns:
        Multi-line natural language text describing hash-presence and,
        when available, drift status for every registered doc-ref and
        doc-guide.
    """
    refs = snapshot.doc_refs
    guides = snapshot.doc_guides

    if not refs and not guides:
        return (
            "Drift status: no documentation registered. Nothing to check."
        )

    refs_hashed = sum(1 for r in refs.values() if r.content_hash)
    guides_hashed = sum(1 for g in guides.values() if g.content_hash)

    lines: list[str] = []
    if recomputed_hashes is None:
        lines.append("## Documentation Drift Status (v1)")
    else:
        lines.append("## Documentation Drift Status")
    lines.append("")
    lines.append(
        f"doc-refs: {refs_hashed}/{len(refs)} carry a stored content hash."
    )
    lines.append(
        f"doc-guides: {guides_hashed}/{len(guides)} carry a stored "
        f"content hash."
    )
    lines.append("")

    missing_refs = sorted(
        name for name, ref in refs.items() if not ref.content_hash
    )
    missing_guides = sorted(
        name for name, guide in guides.items() if not guide.content_hash
    )

    if missing_refs or missing_guides:
        lines.append("Registrations missing a content hash:")
        for name in missing_refs:
            lines.append(f"  - doc-ref: {name}")
        for name in missing_guides:
            lines.append(f"  - doc-guide: {name}")
        lines.append("")

    if recomputed_hashes is None:
        lines.append(
            "Full transitive drift computation (stored hash vs. hash "
            "recomputed from the current registry snapshot) is delivered by "
            "the M7 content-hash subsystem and will be wired into this "
            "surface when it lands."
        )
        return "\n".join(lines)

    drifted: list[tuple[str, str, str, str]] = []
    clean_count = 0
    for name, ref in refs.items():
        if not ref.content_hash:
            continue
        recomputed = recomputed_hashes.get(f"doc-ref:{name}")
        if recomputed is None:
            continue
        if recomputed == ref.content_hash:
            clean_count += 1
        else:
            drifted.append(("doc-ref", name, ref.content_hash, recomputed))
    for name, guide in guides.items():
        if not guide.content_hash:
            continue
        recomputed = recomputed_hashes.get(f"doc-guide:{name}")
        if recomputed is None:
            continue
        if recomputed == guide.content_hash:
            clean_count += 1
        else:
            drifted.append(("doc-guide", name, guide.content_hash, recomputed))

    total_checked = clean_count + len(drifted)
    if drifted:
        lines.append(
            f"Drift check: {len(drifted)}/{total_checked} registration(s) "
            "have drifted."
        )
        lines.append("")
        lines.append("Drifted registrations:")
        for kind, name, stored, recomputed in sorted(drifted):
            # ASCII "->" (not U+2192): runtime output must survive
            # cp1252-encoded Windows consoles (Windows-support plan C-3).
            lines.append(
                f"  - {kind}: {name} (stored {stored!r} -> "
                f"recomputed {recomputed!r})"
            )
    else:
        lines.append(f"Drift check: {total_checked}/{total_checked} clean.")

    return "\n".join(lines)
