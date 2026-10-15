"""Structural verifier — AST-based drift detection.

Compares registry declarations against actual source code to detect
structural discrepancies. Orchestrates per-component and graph-wide
checks from the _checks_m1 and _checks_m2 modules.

Checks performed:
- Phantom limb detection (registry entry with no code)
- Signature verification (declared vs actual types)
- Dependency accuracy (declared vs actual imports)
- Metadata accuracy (module paths, source files)
- Layer conformance (architectural boundary enforcement)
- Dependency cycle detection (per-component and full-graph)
- Component completeness (intent quality, version, deps)
- Murphy's Reflexion Model output (convergences/divergences/absences)
- de Silva erosion coverage analysis (minimise/prevent/repair)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from s0ma.models import Anomaly, ReflexionAnalysis, VerificationResult
from s0ma.types import AnomalyKind, AnomalySeverity, VerificationScope
from s0ma.verifiers._checks_m1 import (
    check_dependency_accuracy,
    check_metadata_accuracy,
    check_phantom_limb,
    check_signatures,
)
from s0ma.verifiers._checks_m2 import (
    check_all_cycles,
    check_completeness,
    check_cycle_for_component,
    check_layer_violations,
    compute_erosion_coverage,
)

if TYPE_CHECKING:
    from s0ma.registry import ComponentRegistry

__all__ = ["StructuralVerifier"]


class StructuralVerifier:
    """AST-based structural drift detection verifier.

    Compares the registry's declarations against actual source code
    and import structure to detect model-reality discrepancies.

    Produces Murphy's Reflexion Model output categories:
    - Convergences: model and code agree
    - Divergences: model and code conflict
    - Absences: expected elements missing

    Also produces:
    - de Silva erosion coverage analysis
    - Component completeness checks
    - Layer conformance violations
    - Dependency cycle detection
    """

    @property
    def name(self) -> str:
        """Human-readable name for this verifier."""
        return "Structural Verifier"

    @property
    def scope(self) -> VerificationScope:
        """This verifier performs structural checks."""
        return VerificationScope.STRUCTURAL

    def verify(self, registry: ComponentRegistry) -> VerificationResult:
        """Run full structural verification against the registry.

        Checks all registered components for structural integrity,
        layer conformance, dependency cycles, and completeness.
        Computes Murphy's Reflexion Model and de Silva erosion coverage.

        Args:
            registry: The ComponentRegistry to verify against.

        Returns:
            VerificationResult with anomalies, reflexion analysis,
            and erosion coverage report.
        """
        start_ns = time.perf_counter_ns()
        anomalies: list[Anomaly] = []
        components_checked = 0
        checks_performed = 0
        convergences: list[str] = []

        all_specs = registry.get_all()

        for _name, spec in all_specs.items():
            components_checked += 1

            # Phantom limb detection
            phantom_anomalies, phantom_checks = check_phantom_limb(spec)
            anomalies.extend(phantom_anomalies)
            checks_performed += phantom_checks
            if phantom_anomalies:
                continue  # Skip further checks if code doesn't exist

            # Signature verification
            sig_anomalies, sig_checks, sig_conv = check_signatures(spec)
            anomalies.extend(sig_anomalies)
            checks_performed += sig_checks
            convergences.extend(sig_conv)

            # Dependency accuracy
            dep_anomalies, dep_checks, dep_conv = (
                check_dependency_accuracy(spec, registry)
            )
            anomalies.extend(dep_anomalies)
            checks_performed += dep_checks
            convergences.extend(dep_conv)

            # Metadata accuracy
            meta_anomalies, meta_checks, meta_conv = (
                check_metadata_accuracy(spec)
            )
            anomalies.extend(meta_anomalies)
            checks_performed += meta_checks
            convergences.extend(meta_conv)

            # Layer conformance (M2)
            layer_anomalies, layer_checks = (
                check_layer_violations(spec, registry)
            )
            anomalies.extend(layer_anomalies)
            checks_performed += layer_checks

            # Component completeness (M2)
            comp_anomalies, comp_checks, comp_conv = (
                check_completeness(spec, registry)
            )
            anomalies.extend(comp_anomalies)
            checks_performed += comp_checks
            convergences.extend(comp_conv)

        # Full-graph dependency cycle detection (M2)
        cycle_anomalies, cycle_checks = check_all_cycles(registry)
        anomalies.extend(cycle_anomalies)
        checks_performed += cycle_checks

        # de Silva erosion coverage analysis (M2)
        erosion_report = compute_erosion_coverage(
            registry, components_checked
        )

        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        # Build reflexion analysis
        divergences = [
            a for a in anomalies
            if a.severity in (
                AnomalySeverity.ERROR, AnomalySeverity.WARNING
            )
        ]
        absences = [
            a for a in anomalies
            if a.kind == AnomalyKind.PHANTOM_LIMB
        ]
        reflexion = ReflexionAnalysis(
            convergences=convergences,
            divergences=divergences,
            absences=absences,
        )

        return VerificationResult(
            verifier_name=self.name,
            scope=self.scope,
            anomalies=anomalies,
            components_checked=components_checked,
            checks_performed=checks_performed,
            duration_ms=elapsed_ms,
            details={
                "reflexion_analysis": reflexion.to_dict(),
                "erosion_coverage": erosion_report.to_dict(),
            },
        )

    def verify_incremental(
        self, registry: ComponentRegistry, component_name: str
    ) -> VerificationResult:
        """Verify only the named component and its direct dependencies.

        Checks:
        - Component's own structural integrity
        - Dependencies exist and are registered
        - No layer violations with direct dependencies
        - No cycles introduced by this component

        Args:
            registry: The ComponentRegistry to verify against.
            component_name: Name of the component to verify.

        Returns:
            VerificationResult scoped to the named component.
        """
        start_ns = time.perf_counter_ns()
        anomalies: list[Anomaly] = []
        components_checked = 0
        checks_performed = 0

        spec = registry.get(component_name)
        if spec is None:
            anomalies.append(Anomaly(
                kind=AnomalyKind.PHANTOM_LIMB,
                severity=AnomalySeverity.ERROR,
                component_name=component_name,
                message=(
                    f"Component '{component_name}' is not registered "
                    f"in the registry"
                ),
            ))
            checks_performed += 1
            elapsed_ms = (
                (time.perf_counter_ns() - start_ns) / 1_000_000
            )
            return VerificationResult(
                verifier_name=self.name,
                scope=self.scope,
                anomalies=anomalies,
                components_checked=0,
                checks_performed=checks_performed,
                duration_ms=elapsed_ms,
            )

        components_checked += 1

        phantom_anomalies, phantom_checks = check_phantom_limb(spec)
        anomalies.extend(phantom_anomalies)
        checks_performed += phantom_checks

        if not phantom_anomalies:
            sig_a, sig_c, _ = check_signatures(spec)
            anomalies.extend(sig_a)
            checks_performed += sig_c

            dep_a, dep_c, _ = check_dependency_accuracy(
                spec, registry
            )
            anomalies.extend(dep_a)
            checks_performed += dep_c

            meta_a, meta_c, _ = check_metadata_accuracy(spec)
            anomalies.extend(meta_a)
            checks_performed += meta_c

        # Check layer violations with direct dependencies
        layer_a, layer_c = check_layer_violations(spec, registry)
        anomalies.extend(layer_a)
        checks_performed += layer_c

        # Check for cycles introduced by this component
        cycle_a, cycle_c = check_cycle_for_component(spec, registry)
        anomalies.extend(cycle_a)
        checks_performed += cycle_c

        # Count direct dependencies
        for dep_name in spec.dependencies:
            dep_spec = registry.get(dep_name)
            if dep_spec is not None:
                components_checked += 1

        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        return VerificationResult(
            verifier_name=self.name,
            scope=self.scope,
            anomalies=anomalies,
            components_checked=components_checked,
            checks_performed=checks_performed,
            duration_ms=elapsed_ms,
        )
