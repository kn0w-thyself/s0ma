"""Self-model query interface for S0ma.

Provides a Python-native API that makes the self-model queryable
by in-process consumers — especially LLM orchestration layers.

All methods return ``str`` (not data structures) because the primary
consumer is an LLM that needs natural language context. Structured
data is available through the underlying ``ComponentRegistry`` for
consumers that need it.

Design principles:
- Produces *text* (not data structures)
- Pure Python layer on top of registry + verifiers
- Zero external dependencies
- All methods are registered S0ma components (dogfooding via _bootstrap.py)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from s0ma.exceptions import RegistryIntegrityError
from s0ma.self_model.analyzers import (
    compute_impact_analysis,
    find_extension_points,
    validate_proposed_component,
)
from s0ma.self_model.formatters import (
    format_code_generation_context,
    format_component_detail,
    format_component_summary,
    format_contracts_text,
    format_dependency_graph_text,
    format_doc_guide_detail,
    format_doc_ref_detail,
    format_doc_refs_overview,
    format_docs_for_component,
    format_drift_status,
    format_examples_for_component,
    format_extension_points,
    format_health_summary,
    format_impact_report,
    format_layer_breakdown,
    format_lifecycle_events,
)

if TYPE_CHECKING:
    from s0ma.lifecycle.manager import LifecycleManager
    from s0ma.models import Anomaly, ComponentResolution, ComponentSpec, VerificationReport
    from s0ma.registry import ComponentRegistry
    from s0ma.verifiers.interoception import MetricsCollector

__all__ = ["SelfModelInterface"]


class SelfModelInterface:
    """Python-native self-model query interface.

    Produces text (not data structures) because the primary consumer
    is an LLM that needs natural language context.

    Args:
        registry: The ComponentRegistry to query.
        metrics_collector: Optional MetricsCollector for runtime data.
        lifecycle_manager: Optional LifecycleManager for lifecycle event
            history. When provided, ``get_recent_changes()`` returns
            lifecycle event data, and ``get_architecture_context()``
            includes recent change history.
    """

    def __init__(
        self,
        registry: ComponentRegistry,
        *,
        metrics_collector: MetricsCollector | None = None,
        lifecycle_manager: LifecycleManager | None = None,
    ) -> None:
        self._registry = registry
        self._metrics_collector = metrics_collector
        self._lifecycle_manager = lifecycle_manager

    def describe_system(self, *, include_framework: bool | None = None) -> str:
        """Natural language system overview for LLM context.

        Returns a comprehensive but concise description of:
        - System purpose and architecture style
        - Component count by layer and kind
        - Key architectural patterns
        - Current health status (if verification data available)

        Optimized for: injecting into an LLM system prompt as
        "here is what this system is."

        Args:
            include_framework: Whether s0ma's own framework components
                are listed and counted in the layer and kind breakdowns.
                ``None`` (the default) lists the application's components
                alone whenever any are registered, and the framework's
                when nothing else is, so an application's overview is
                about the application; ``True`` lists everything and
                ``False`` the application alone. The summary's total,
                framework and application counts are always all three.
        """
        snapshot = self._registry.snapshot()
        components = snapshot.visible_components(include_framework)
        framework_listed = any(spec.is_framework for spec in components.values())

        lines: list[str] = []

        # System identity
        lines.append("# S0ma System Overview")
        lines.append("")
        lines.append(
            "S0ma is a Python framework for software self-knowledge — "
            "software that cannot exist without understanding itself. "
            "Self-knowledge spans three faculties: proprioception "
            "(structure), interoception (runtime state), and metacognition "
            "(reasoning over the model). Every component must register in a "
            "hierarchical self-model as a condition of existing. The "
            "self-model is a structural runtime dependency (load-bearing), "
            "not optional documentation."
        )
        lines.append("")

        # Component summary
        user_count = snapshot.component_count - snapshot.framework_component_count
        # Count components with configurable properties
        configurable_count = len([
            comp
            for comp in components.values()
            if comp.contracts and comp.contracts.configurable_properties
        ])
        lines.append("## Component Summary")
        lines.append(f"Total registered components: {snapshot.component_count}")
        lines.append(f"Framework components: {snapshot.framework_component_count}")
        lines.append(f"User/application components: {user_count}")
        if configurable_count > 0:
            lines.append(f"Components with runtime-configurable properties: {configurable_count}")
        if not framework_listed and snapshot.framework_component_count:
            lines.append(
                f"Listed below: the {len(components)} application components "
                "(framework components omitted; pass include_framework=True "
                "to list them)."
            )
        lines.append("")

        # Layer breakdown
        lines.append(format_layer_breakdown(components))
        lines.append("")

        # Kind breakdown
        kind_counts = self._count_by_kind(components)
        if kind_counts:
            lines.append("## Component Kinds")
            for kind_name, count in sorted(kind_counts.items()):
                lines.append(f"  {kind_name}: {count}")
            lines.append("")

        # Key architectural patterns
        lines.append("## Key Architectural Patterns")
        lines.append(
            "- Registration-as-creation: code cannot be imported without "
            "registering in the self-model"
        )
        lines.append(
            "- Load-bearing self-model: removing the registry causes "
            "system failure"
        )
        lines.append(
            "- Hierarchical self-description: system -> layer -> component"
        )
        lines.append(
            "- Biological pathology taxonomy: code-model discrepancies "
            "classified as phantom limbs, vestigial organs, etc."
        )
        lines.append("")

        # Health status (run verification if possible)
        report = self._try_verify()
        lines.append(format_health_summary(report))

        return "\n".join(lines)

    def describe_component(self, name: str) -> str:
        """Detailed description of one component for LLM context.

        Returns:
        - Component identity (name, kind, layer, version)
        - Intent (the developer's description of purpose)
        - Contracts (pre/postconditions, invariants, performance bounds)
        - Dependencies (what it uses) and dependents (who uses it)
        - Resource profile (if declared)
        - Source location

        Args:
            name: The name of the component to describe, or the name of an
                operation it provides; an operation name describes the one
                component that provides it, and the text opens by saying so.

        Raises:
            RegistryIntegrityError: If no component or operation has the
                name, or if several components provide the operation (the
                message names them so the caller can ask by component).
        """
        resolution = self._registry.resolve_component(name)
        return self._describe_resolution(resolution)

    def _describe_resolution(self, resolution: ComponentResolution) -> str:
        """Render one authoritative resolution for text and structured adapters."""
        name = resolution.name
        spec = resolution.spec
        if spec is None:
            if resolution.candidates:
                kind = "an operation of" if resolution.operation else "ambiguous between"
                raise RegistryIntegrityError(
                    f"'{name}' is {kind} {len(resolution.candidates)} "
                    f"components; describe one of them by canonical name: "
                    f"{', '.join(resolution.candidates)}"
                )
            msg = (
                f"Component '{name}' is not registered in the self-model. "
                f"Registered components: "
                f"{', '.join(sorted(self._registry.get_all().keys()))}"
            )
            raise RegistryIntegrityError(msg)

        lines: list[str] = []

        if resolution.note is not None:
            lines.append(f"{resolution.note}; this describes that component.")
            lines.append("")

        # Detailed component description
        lines.append(format_component_detail(spec))
        lines.append("")

        # Dependents (who uses this component)
        try:
            dependents = self._registry.get_dependents(spec.display_name)
        except RegistryIntegrityError:
            dependents = []

        if dependents:
            lines.append("Dependents (components that depend on this):")
            for dep_spec in sorted(dependents, key=lambda s: s.name):
                lines.append(
                    f"  - {dep_spec.name} ({dep_spec.kind.name.lower()})"
                )
            lines.append("")
        else:
            lines.append("No other components depend on this component.")
            lines.append("")

        return "\n".join(lines).rstrip()

    def get_architecture_context(self, *, include_framework: bool | None = None) -> str:
        """Full architectural context for LLM planning.

        Returns everything an LLM would need to understand the system
        before making changes:
        - System overview
        - All components grouped by layer
        - Full dependency graph (text representation)
        - Current verification status
        - Current anomalies (if any) with severity

        Optimized for: providing maximum context to an LLM that is
        about to generate code, plan a modification, or debug an issue.

        Args:
            include_framework: As for :meth:`describe_system`: ``None``
                lists the application's components alone whenever any
                are registered, ``True`` lists s0ma's framework
                components too, ``False`` never lists them.
        """
        snapshot = self._registry.snapshot()
        components = snapshot.visible_components(include_framework)
        framework_listed = any(spec.is_framework for spec in components.values())

        lines: list[str] = []

        # System overview (compact version)
        lines.append("# S0ma Architecture Context")
        lines.append("")
        user_count = snapshot.component_count - snapshot.framework_component_count
        lines.append(
            f"System: S0ma (software self-knowledge framework). "
            f"{snapshot.component_count} components total "
            f"({snapshot.framework_component_count} framework, "
            f"{user_count} user)."
        )
        if not framework_listed and snapshot.framework_component_count:
            lines.append(
                f"This context lists the {len(components)} application components; "
                "framework components are omitted (include_framework=True lists them)."
            )
        lines.append("")

        # Full layer breakdown with intents
        lines.append(format_layer_breakdown(components))
        lines.append("")

        # Full dependency graph
        lines.append("## Dependency Graph")
        lines.append(
            format_dependency_graph_text(
                {name: snapshot.dependency_graph.get(name, []) for name in components}
            )
        )
        lines.append("")

        # All components with full detail
        lines.append("## Component Details")
        lines.append("")
        for name in sorted(components):
            spec = components[name]
            lines.append(format_component_summary(spec))
            # Include contracts inline for architecture context
            contracts_text = format_contracts_text(spec.contracts)
            if contracts_text:
                lines.append(contracts_text)
            lines.append("")

        # Verification status
        lines.append("## System Health")
        report = self._try_verify()
        lines.append(format_health_summary(report))
        lines.append("")

        # Recent lifecycle changes (if lifecycle manager is wired)
        if self._lifecycle_manager is not None:
            events = self._lifecycle_manager.events
            if events:
                # Include the most recent events (up to 10)
                recent = events[-10:]
                lines.append(format_lifecycle_events(recent))
                lines.append("")

        return "\n".join(lines)

    def get_impact_analysis(self, component: str) -> str:
        """What would be affected if this component changes?

        Returns natural language impact analysis including:
        - Direct and transitive dependents
        - Affected layers
        - Risk assessment
        - Specific warnings if this is a high-impact component

        Args:
            component: Name of the component to analyze, or of an operation
                it provides (the analysis is then the providing component's).

        Returns:
            Natural language impact analysis text.

        Raises:
            RegistryIntegrityError: If the component is not registered.
        """
        report = compute_impact_analysis(
            self._registry,
            component,
            metrics_collector=self._metrics_collector,
        )
        return format_impact_report(report)

    def get_available_extension_points(self) -> str:
        """Where can new components be added without violating contracts?

        Returns a description of available extension points organized
        by architectural layer, with suggestions for component kinds
        and potential dependency targets.

        Returns:
            Natural language description of extension points.
        """
        points = find_extension_points(self._registry)
        return format_extension_points(points)

    def get_recent_changes(self, limit: int = 10) -> str:
        """Describe recent lifecycle events (create/update/remove).

        Returns natural language description of the most recent
        lifecycle events, useful for an LLM to understand what
        has changed recently.

        Args:
            limit: Maximum number of events to include (most recent
                first). Defaults to 10.

        Returns:
            Natural language description of recent changes. If no
            lifecycle manager is wired, returns a message indicating
            that lifecycle tracking is not available.
        """
        if self._lifecycle_manager is None:
            return (
                "Lifecycle change tracking is not available. "
                "Wire a LifecycleManager to enable change history."
            )

        events = self._lifecycle_manager.events
        if limit < len(events):
            events = events[-limit:]

        return format_lifecycle_events(events)

    def validate_proposed_component(
        self, spec: ComponentSpec,
    ) -> list[Anomaly]:
        """Check if a proposed new component would violate any constraints.

        Pre-creation validation that catches problems before they happen:
        - Name uniqueness (not already registered)
        - Dependency existence (all declared deps exist)
        - Layer conformance (no invalid cross-layer dependencies)
        - Naming conventions (follows project patterns)
        - Contract completeness (has meaningful intent, non-empty contracts)

        Args:
            spec: The proposed ComponentSpec to validate.

        Returns:
            List of Anomaly objects (empty if the component is valid).
        """
        return validate_proposed_component(self._registry, spec)

    def describe_for_code_generation(
        self,
        target_package: str,
        *,
        include_contracts: bool = True,
        include_configurable_properties: bool = True,
    ) -> str:
        """Produce self-model output specifically formatted for LLM code generation.

        Key differences from ``describe_system()``:

        - Framework module paths are annotated as non-importable so LLMs don't
          pattern-match them as valid import roots for generated code.
        - Explicitly lists valid import roots for ``target_package``.
        - Annotates layer names as classification metadata, not Python packages.
        - Includes a filled-in ``@component`` decorator template.
        - Includes configurable property schemas for components that declare them.

        Args:
            target_package: The Python package where generated code will live
                (e.g., ``"myapp.services"``).
            include_contracts: Whether to include contract details per component.
                Defaults to ``True``.
            include_configurable_properties: Whether to include configurable
                property schemas. Defaults to ``True``.

        Returns:
            LLM-optimized text for code generation prompts.
        """
        snapshot = self._registry.snapshot()
        return format_code_generation_context(
            snapshot.components,
            target_package,
            include_contracts=include_contracts,
            include_configurable_properties=include_configurable_properties,
        )

    def describe_for_agent(
        self,
        context: str,
        *,
        target_package: str | None = None,
        include_framework: bool | None = None,
    ) -> str:
        """Format self-model output for a specific agent context.

        Dispatches to the appropriate self-model method based on the
        requested context, allowing callers to select the most relevant
        presentation without knowing which underlying method to call.

        Args:
            context: One of:

                - ``"code_generation"`` — delegates to
                  ``describe_for_code_generation()``; requires
                  ``target_package``.
                - ``"architectural_review"`` — delegates to
                  ``get_architecture_context()``.
                - ``"debugging"`` — includes verification status,
                  active anomalies, and the dependency graph.

            target_package: Required when ``context`` is
                ``"code_generation"``.
            include_framework: Whether the architectural-review and
                debugging contexts list s0ma's framework components; see
                :meth:`describe_system`. The code-generation context
                always shows them, annotated as not importable.

        Returns:
            Context-optimized self-model text.

        Raises:
            ValueError: If ``context`` is ``"code_generation"`` and no
                ``target_package`` is provided, or if ``context`` is not a
                recognized value.
        """
        if context == "code_generation":
            if target_package is None:
                raise ValueError(
                    "describe_for_agent('code_generation') requires "
                    "target_package. "
                    "Example: describe_for_agent('code_generation', "
                    "target_package='myapp')"
                )
            return self.describe_for_code_generation(target_package)

        if context == "architectural_review":
            return self.get_architecture_context(include_framework=include_framework)

        if context == "debugging":
            return self._describe_for_debugging(include_framework=include_framework)

        valid = ("code_generation", "architectural_review", "debugging")
        raise ValueError(
            f"Unknown context '{context}'. "
            f"Valid contexts: {', '.join(valid)}"
        )

    def describe_docs(self) -> str:
        """Registry-wide overview of documentation artifacts.

        Returns a natural-language summary of every registered
        ``doc-ref``, ``doc-guide``, and ``example``. When nothing is
        registered, returns an informative message rather than raising,
        so LLM callers can read the response directly.
        """
        snapshot = self._registry.snapshot()
        return format_doc_refs_overview(
            snapshot.doc_refs,
            snapshot.doc_guides,
            snapshot.examples,
        )

    def describe_doc(self, name: str) -> str:
        """Detailed description of a single doc-ref or doc-guide.

        Looks up ``name`` first in the doc-ref store, then in the
        doc-guide store. Returns a "not found" message (not an
        exception) when the name is unknown, matching the
        informational contract documented for the M5 doc surface.

        Args:
            name: The registered doc name (bare ``name`` — matches the
                registry key used by ``register_doc_ref`` /
                ``register_doc_guide``).
        """
        snapshot = self._registry.snapshot()
        ref = snapshot.doc_refs.get(name)
        if ref is not None:
            return format_doc_ref_detail(ref)

        guide = snapshot.doc_guides.get(name)
        if guide is not None:
            return format_doc_guide_detail(guide)

        known_refs = sorted(snapshot.doc_refs)
        known_guides = sorted(snapshot.doc_guides)
        known = sorted(known_refs + known_guides)
        if not known:
            return (
                f"No documentation named '{name}' is registered. The "
                f"documentation subsystem is in place but no doc-ref or "
                f"doc-guide has been registered yet."
            )
        return (
            f"No documentation named '{name}' is registered. "
            f"Registered docs: {', '.join(known)}"
        )

    def get_docs_for_component(self, name: str) -> str:
        """Documentation artifacts that cover a named component.

        Uses the M4 reverse-index (``RegistrySnapshot.docs_for``) to
        surface every doc-ref filter match and every doc-guide whose
        ``covers`` list references the component.

        Args:
            name: Component name. Accepts the same inputs as
                ``RegistrySnapshot.docs_for`` — a bare component name or
                a ``"module::name"`` string shortcut.
        """
        snapshot = self._registry.snapshot()
        result = snapshot.docs_for(name)
        return format_docs_for_component(name, result.refs, result.guides)

    def get_examples_for_component(self, name: str) -> str:
        """Canonical examples that demonstrate a named component.

        Uses the M4 reverse-index (``RegistrySnapshot.examples_for``).

        Args:
            name: Component name. Accepts a bare component name or a
                ``"module::name"`` string shortcut.
        """
        snapshot = self._registry.snapshot()
        examples = snapshot.examples_for(name)
        return format_examples_for_component(name, examples)

    def get_drift_status(self, *, transpiler_version: str = "unknown") -> str:
        """Current documentation drift status.

        Recomputes the transitive content hash for every registered
        doc-ref and doc-guide and compares it against the stored value
        on each registration. Any divergence is reported as drift.

        Args:
            transpiler_version: The s0ma-dsl transpiler version to feed
                into the hash. Drift checks emitted from CI should pass
                the version tag that generated the stored hashes;
                callers without that context may leave the default.

        Returns:
            Multi-line text describing hash-presence, drift count, and
            the stored/recomputed value for every drifted registration.
        """
        from s0ma.hashing import content_hash

        snapshot = self._registry.snapshot()
        recomputed: dict[str, str] = {}
        for name, ref in snapshot.doc_refs.items():
            if ref.content_hash:
                recomputed[f"doc-ref:{name}"] = content_hash(
                    ref, snapshot, transpiler_version=transpiler_version
                )
        for name, guide in snapshot.doc_guides.items():
            if guide.content_hash:
                recomputed[f"doc-guide:{name}"] = content_hash(
                    guide, snapshot, transpiler_version=transpiler_version
                )
        return format_drift_status(snapshot, recomputed_hashes=recomputed)

    def _describe_for_debugging(self, *, include_framework: bool | None = None) -> str:
        """Produce debugging-focused self-model output.

        Includes current verification status, all active anomalies,
        and the full dependency graph — the three pieces of context
        most useful when diagnosing a system problem.
        """
        snapshot = self._registry.snapshot()
        components = snapshot.visible_components(include_framework)
        report = self._try_verify()

        lines: list[str] = []
        lines.append("# System Context for Debugging")
        lines.append("")

        # Verification status and anomaly summary
        lines.append(format_health_summary(report))
        lines.append("")

        # Full anomaly list when problems exist
        if report is not None and report.total_anomalies > 0:
            lines.append("## Active Anomalies")
            for result in report.results:
                for anomaly in result.anomalies:
                    lines.append(
                        f"  [{anomaly.severity.name}] "
                        f"[{result.verifier_name}] {anomaly.message}"
                    )
            lines.append("")

        # Dependency graph for tracing component relationships
        lines.append("## Dependency Graph")
        lines.append(
            format_dependency_graph_text(
                {name: snapshot.dependency_graph.get(name, []) for name in components}
            )
        )
        lines.append("")

        # Recent lifecycle events (most recent 5)
        if self._lifecycle_manager is not None:
            events = self._lifecycle_manager.events
            if events:
                lines.append(format_lifecycle_events(events[-5:]))

        return "\n".join(lines)

    def _try_verify(self) -> VerificationReport | None:
        """Return a completed report, or None when verification is unavailable."""
        return self._verification_observation()[0]

    def _verification_observation(self) -> tuple[VerificationReport | None, str | None]:
        """Keep missing checks and execution failures out of the pass/fail domain.

        Diagnostic codes are fixed strings: exception messages may carry secrets.
        This result is per request, never mutable cached state on the interface.
        """
        try:
            from s0ma.verifiers import verify_all

            report = verify_all(
                self._registry,
                metrics_collector=self._metrics_collector,
            )
        except ImportError:
            return None, "VERIFIER_UNAVAILABLE"
        except Exception:  # noqa: BLE001
            return None, "VERIFICATION_ERROR"
        if report is None or not report.results:
            return None, "NO_VERIFICATION_RESULTS"
        return report, None

    @staticmethod
    def _count_by_kind(
        components: dict[str, Any],
    ) -> dict[str, int]:
        """Count components grouped by kind."""
        counts: dict[str, int] = {}
        for spec in components.values():
            kind_name = spec.kind.name.lower()
            counts[kind_name] = counts.get(kind_name, 0) + 1
        return counts
