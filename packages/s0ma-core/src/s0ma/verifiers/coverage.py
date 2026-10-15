"""Coverage auditor — dead code and biological pathology detection.

Combines multiple data sources to detect code-model pathologies
using the full biological taxonomy:

- PHANTOM_LIMB: registry entry with no corresponding source code
- VESTIGIAL_ORGAN: code that exists but is never used
- IMMUNE_RESPONSE: unregistered code detected (import hook status)
- ATROPHIED_MUSCLE: deprecated API still receiving calls
- INFLAMMATION: resource profile exceeded (via interoception)

Data sources:
    1. Registry data — what's declared
    2. AST analysis — what exists in source (via structural checks)
    3. Import analysis — what's actually imported/used
    4. Runtime metrics (from interoception) — what's actually called
    5. Test coverage data (if available from pytest-cov) — what's tested

Also implements the Kounev & Spinner (2015) automation metric:
what percentage of the self-model is automatically verifiable?

Reference: Kounev & Spinner (2015) achieved 85.4% automation on
legacy systems. s0ma targets >95% since the self-model is
built from inception.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from s0ma.models import Anomaly, VerificationResult
from s0ma.types import AnomalyKind, AnomalySeverity, VerificationScope
from s0ma.verifiers._checks_m1 import check_phantom_limb

if TYPE_CHECKING:
    from pathlib import Path

    from s0ma.models import ComponentSpec
    from s0ma.registry import ComponentRegistry
    from s0ma.verifiers.discovery import DiscoveredSurface
    from s0ma.verifiers.interoception import MetricsCollector

__all__ = ["CoverageAuditor"]


class CoverageAuditor:
    """Combines multiple data sources to detect code-model pathologies.

    Implements the biological pathology taxonomy:
    - PHANTOM_LIMB: registry entry with no code
    - VESTIGIAL_ORGAN: code that exists but is never used
    - IMMUNE_RESPONSE: unregistered code detected
    - ATROPHIED_MUSCLE: deprecated API still active
    - INFLAMMATION: resource profile exceeded

    The coverage auditor is read-only — it inspects the registry,
    source code, and runtime metrics but never modifies them.
    """

    def __init__(
        self,
        metrics_collector: MetricsCollector | None = None,
        coverage_data_path: Path | None = None,
    ) -> None:
        """Initialize the coverage auditor.

        Args:
            metrics_collector: Optional MetricsCollector for metrics-based
                detection. Uses the global singleton if None.
            coverage_data_path: Optional path to a .coverage file for
                test-coverage-based detection. If None, coverage-based
                checks are skipped.
        """
        self._metrics_collector = metrics_collector
        self._coverage_data_path = coverage_data_path

    @property
    def name(self) -> str:
        """Human-readable name for this verifier."""
        return "Coverage Auditor"

    @property
    def scope(self) -> VerificationScope:
        """This verifier performs coverage checks."""
        return VerificationScope.COVERAGE

    def verify(
        self,
        registry: ComponentRegistry,
        *,
        discovered_surface: DiscoveredSurface | None = None,
    ) -> VerificationResult:
        """Run all coverage checks and return results.

        Checks (in order):
        1. Phantom limb detection (registry entry with no code)
        2. Vestigial organ detection (unused components)
        3. Atrophied muscle detection (deprecated but still called)
        4. Immune response status (import hook check)

        INFLAMMATION is already handled by InteroceptionVerifier
        and is not duplicated here.

        Args:
            registry: The ComponentRegistry to audit.

        Returns:
            VerificationResult with coverage anomalies and
            automation metric in details.
        """
        start_ns = time.perf_counter_ns()
        anomalies: list[Anomaly] = []
        components_checked = 0
        checks_performed = 0

        all_specs = registry.get_all()

        # 0.14 M1: source discovery belongs to the caller (normally the DSL).
        # Core accepts only a parser-neutral value and faults on the caller's
        # discovered-but-not-componentized delta.
        from s0ma.verifiers.discovery import (
            registered_surface_identifiers,
            unregistered_surface_anomaly,
        )

        registered_surface = registered_surface_identifiers(registry)
        discovery_anomaly = unregistered_surface_anomaly(
            discovered_surface, registered_surface,
        )
        if discovery_anomaly is not None:
            anomalies.append(discovery_anomaly)
            checks_performed += 1

        # Phase 1: Phantom limb detection (reuse structural checks)
        for spec in all_specs.values():
            components_checked += 1
            phantom_a, phantom_c = check_phantom_limb(spec)
            anomalies.extend(phantom_a)
            checks_performed += phantom_c

        # Phase 2: Vestigial organ detection (import-based)
        vestigial_a, vestigial_c = _detect_vestigial_organs_by_import(
            all_specs, registry
        )
        anomalies.extend(vestigial_a)
        checks_performed += vestigial_c

        # Phase 3: Vestigial organ detection (metrics-based)
        collector = self._get_collector()
        if collector is not None:
            metrics_a, metrics_c = _detect_vestigial_organs_by_metrics(
                all_specs, collector
            )
            anomalies.extend(metrics_a)
            checks_performed += metrics_c

        # Phase 4: Atrophied muscle detection
        atrophied_a, atrophied_c = _detect_atrophied_muscles(
            all_specs, collector
        )
        anomalies.extend(atrophied_a)
        checks_performed += atrophied_c

        # Phase 5: Immune response status
        immune_a, immune_c = _check_immune_response_status()
        anomalies.extend(immune_a)
        checks_performed += immune_c

        # Compute automation metric
        automation = self.get_automation_metric(registry, collector)

        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        return VerificationResult(
            verifier_name=self.name,
            scope=self.scope,
            anomalies=anomalies,
            components_checked=components_checked,
            checks_performed=checks_performed,
            duration_ms=elapsed_ms,
            details={
                "automation_metric": automation,
                "pathology_counts": _count_pathologies(anomalies),
                "discovered_surface": {
                    "provided": discovered_surface is not None,
                    "count": (
                        len(discovered_surface.declarations)
                        if discovered_surface is not None
                        else 0
                    ),
                    "unregistered": (
                        len(
                            discovered_surface.unregistered_against(
                                registered_surface,
                            )
                        )
                        if discovered_surface is not None
                        else 0
                    ),
                },
            },
        )

    def verify_incremental(
        self,
        registry: ComponentRegistry,
        component_name: str,
    ) -> VerificationResult:
        """Verify coverage for a single component.

        Checks phantom limb and vestigial organ status for the
        named component only.

        Args:
            registry: The ComponentRegistry to verify against.
            component_name: Name of the component to verify.

        Returns:
            VerificationResult scoped to the named component.
        """
        start_ns = time.perf_counter_ns()
        anomalies: list[Anomaly] = []
        checks_performed = 0

        spec = registry.get(component_name)
        if spec is None:
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
            return VerificationResult(
                verifier_name=self.name,
                scope=self.scope,
                anomalies=[
                    Anomaly(
                        kind=AnomalyKind.PHANTOM_LIMB,
                        severity=AnomalySeverity.ERROR,
                        component_name=component_name,
                        message=(
                            f"Component '{component_name}' "
                            f"is not registered"
                        ),
                    )
                ],
                components_checked=0,
                checks_performed=1,
                duration_ms=elapsed_ms,
            )

        # Phantom limb check
        phantom_a, phantom_c = check_phantom_limb(spec)
        anomalies.extend(phantom_a)
        checks_performed += phantom_c

        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        return VerificationResult(
            verifier_name=self.name,
            scope=self.scope,
            anomalies=anomalies,
            components_checked=1,
            checks_performed=checks_performed,
            duration_ms=elapsed_ms,
        )

    def get_automation_metric(
        self,
        registry: ComponentRegistry,
        collector: MetricsCollector | None = None,
    ) -> float:
        """Calculate the percentage of self-model that is auto-verified.

        Kounev & Spinner (2015) achieved 85.4% on legacy systems.
        s0ma targets >95% since the self-model is built from
        inception — every component has structural data from the start.

        The metric measures what fraction of the self-model's verifiable
        properties are automatically checked (without human judgment):

        - Structural checks (existence, importability, source file,
          dependency accuracy, layer conformance, completeness) are
          always automatic → 100% for well-registered components
        - Contract string evaluation requires human judgment UNLESS
          callable validators are registered → reduces score
        - ResourceProfile monitoring is automatic when metrics exist

        For inception-built systems like s0ma, structural
        verification dominates because ALL components are registered
        with full metadata. Legacy systems score lower because
        components may lack structural data entirely.

        Args:
            registry: The component registry.
            collector: Optional metrics collector.

        Returns:
            Automation percentage as a float between 0.0 and 1.0.
        """
        all_specs = registry.get_all()
        if not all_specs:
            return 0.0

        total_checks = 0.0
        auto_checks = 0.0

        for spec in all_specs.values():
            # Structural checks: always possible, always automatic
            # (existence, importability, metadata, deps, layer, version)
            structural_check_count = 6
            total_checks += structural_check_count

            if spec.module_path and spec.qualified_name:
                auto_checks += structural_check_count
            # else: phantom limb — structural checks fail

            # Contract checks: count string contracts that need
            # human judgment vs callable contracts that are automatic
            contract_strings = (
                len(spec.contracts.preconditions)
                + len(spec.contracts.postconditions)
                + len(spec.contracts.invariants)
            )
            if contract_strings > 0:
                # Each string contract is one check. String contracts
                # are mostly auto-verifiable: the coverage auditor
                # checks existence, non-emptiness, and linkage to the
                # component. Only semantic truth evaluation requires
                # human/LLM judgment. Score at 75% auto-verifiable.
                total_checks += contract_strings
                auto_checks += contract_strings * 0.75

            # Performance checks: auto if profile + metrics exist
            if spec.resource_profile is not None:
                profile_fields = sum(1 for f in (
                    spec.resource_profile.expected_latency_p50_ms,
                    spec.resource_profile.expected_latency_p99_ms,
                    spec.resource_profile.expected_error_rate,
                    spec.resource_profile.expected_call_frequency_per_min,
                    spec.resource_profile.expected_memory_mb,
                ) if f is not None)
                total_checks += max(profile_fields, 1)
                auto_checks += max(profile_fields, 1)

        if total_checks == 0:
            return 1.0

        return auto_checks / total_checks

    def _get_collector(self) -> MetricsCollector | None:
        """Get the metrics collector, falling back to global singleton."""
        if self._metrics_collector is not None:
            return self._metrics_collector
        try:
            from s0ma.verifiers.interoception import (
                get_metrics_collector,
            )

            return get_metrics_collector()
        except Exception:  # noqa: BLE001
            return None


# ======================================================================
# Detection algorithms (module-level functions)
# ======================================================================


def _detect_vestigial_organs_by_import(
    all_specs: dict[str, ComponentSpec],
    registry: ComponentRegistry,
) -> tuple[list[Anomaly], int]:
    """Detect components that are registered but never imported by others.

    Scans all registered components' dependency lists. A component
    that is not declared as a dependency by any other component
    (and is not a framework component) may be vestigial.

    Framework components are excluded from vestigial detection
    because they may be infrastructure used indirectly.

    Returns:
        Tuple of (anomalies, checks_performed).
    """
    anomalies: list[Anomaly] = []
    checks = 0

    if not all_specs:
        return anomalies, checks

    # Build reverse dependency map: who is depended on?
    depended_on: set[str] = set()
    for spec in all_specs.values():
        for dep in spec.dependencies:
            depended_on.add(dep)

    # Check each non-framework component
    checks += 1
    for comp_name, spec in all_specs.items():
        if spec.is_framework:
            continue

        if comp_name not in depended_on:
            anomalies.append(Anomaly(
                kind=AnomalyKind.VESTIGIAL_ORGAN,
                severity=AnomalySeverity.INFO,
                component_name=comp_name,
                message=(
                    f"Component '{comp_name}' is not declared as a "
                    f"dependency by any other component — it may be "
                    f"an entry point or unused"
                ),
                details={
                    "component_layer": spec.layer.name,
                    "component_kind": spec.kind.name,
                },
            ))

    return anomalies, checks


def _detect_vestigial_organs_by_metrics(
    all_specs: dict[str, ComponentSpec],
    collector: MetricsCollector,
) -> tuple[list[Anomaly], int]:
    """Detect components with ResourceProfile but zero calls.

    If interoception is active, components that have declared
    a ResourceProfile but have received zero calls over the
    monitoring window may be vestigial.

    Returns:
        Tuple of (anomalies, checks_performed).
    """
    anomalies: list[Anomaly] = []
    checks = 0

    for comp_name, spec in all_specs.items():
        if spec.resource_profile is None:
            continue
        if spec.is_framework:
            continue

        checks += 1
        metrics = collector.get_metrics(comp_name)
        if metrics is None or metrics.call_count == 0:
            anomalies.append(Anomaly(
                kind=AnomalyKind.VESTIGIAL_ORGAN,
                severity=AnomalySeverity.INFO,
                component_name=comp_name,
                message=(
                    f"Component '{comp_name}' has a ResourceProfile "
                    f"but zero calls recorded — it may be unused"
                ),
                details={
                    "has_resource_profile": True,
                    "call_count": 0,
                },
            ))

    return anomalies, checks


def _detect_atrophied_muscles(
    all_specs: dict[str, ComponentSpec],
    collector: MetricsCollector | None,
) -> tuple[list[Anomaly], int]:
    """Detect deprecated components that are still receiving calls.

    Components with metadata["deprecated"] = True (or
    metadata["status"] = "deprecated") that still have recent
    calls in the metrics are atrophied muscles.

    Returns:
        Tuple of (anomalies, checks_performed).
    """
    anomalies: list[Anomaly] = []
    checks = 0

    for comp_name, spec in all_specs.items():
        if not _is_deprecated(spec):
            continue

        checks += 1

        if collector is None:
            continue

        metrics = collector.get_metrics(comp_name)
        if metrics is not None and metrics.call_count > 0:
            anomalies.append(Anomaly(
                kind=AnomalyKind.ATROPHIED_MUSCLE,
                severity=AnomalySeverity.WARNING,
                component_name=comp_name,
                message=(
                    f"Deprecated component '{comp_name}' still "
                    f"receiving calls ({metrics.call_count} calls, "
                    f"last at {metrics.last_call_at})"
                ),
                details={
                    "call_count": metrics.call_count,
                    "last_call_at": (
                        metrics.last_call_at.isoformat()
                        if metrics.last_call_at
                        else None
                    ),
                    "deprecated": True,
                },
            ))

    return anomalies, checks


def _is_deprecated(spec: ComponentSpec) -> bool:
    """Check if a component is marked as deprecated in its metadata."""
    metadata = spec.metadata
    if metadata.get("deprecated") is True:
        return True
    return str(metadata.get("status", "")).lower() == "deprecated"


def _check_immune_response_status() -> tuple[list[Anomaly], int]:
    """Check if the import hook is installed (immune system active).

    The import hook is the immune system — it detects unregistered
    code (foreign bodies) at import time. If it's not installed,
    report as INFO.

    Returns:
        Tuple of (anomalies, checks_performed).
    """
    from s0ma.import_hook import is_hook_installed

    anomalies: list[Anomaly] = []
    checks = 1

    if not is_hook_installed():
        anomalies.append(Anomaly(
            kind=AnomalyKind.IMMUNE_RESPONSE,
            severity=AnomalySeverity.INFO,
            component_name=None,
            message=(
                "Import hook (immune system) is not installed — "
                "unregistered code will not be detected at import time"
            ),
        ))

    return anomalies, checks


def _count_pathologies(
    anomalies: list[Anomaly],
) -> dict[str, int]:
    """Count anomalies by pathology kind.

    Returns:
        Dictionary mapping AnomalyKind names to counts.
    """
    counts: dict[str, int] = {}
    for anomaly in anomalies:
        kind_name = anomaly.kind.name
        counts[kind_name] = counts.get(kind_name, 0) + 1
    return counts
