"""Verification engine — checks whether the self-model matches reality.

This package provides verifiers that detect structural drift, contract
violations, resource profile deviations, and dead code. Each verifier
implements the Verifier protocol and returns VerificationResult objects.

Public API:
    verify_all()            — Run all registered verifiers
    verify_structural()     — Run only the structural verifier
    verify_contracts()      — Run only the contract verifier
    verify_interoception()  — Run only the interoception monitor
    verify_coverage()       — Run only the coverage auditor
    verify_incremental()    — Verify a single component and its deps
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from s0ma.models import VerificationReport, VerificationResult
from s0ma.verifiers.contracts import ContractVerifier
from s0ma.verifiers.coverage import CoverageAuditor
from s0ma.verifiers.discovery import DiscoveredDeclaration, DiscoveredSurface
from s0ma.verifiers.interoception import InteroceptionVerifier
from s0ma.verifiers.structural import StructuralVerifier

if TYPE_CHECKING:
    from pathlib import Path

    from s0ma.registry import ComponentRegistry
    from s0ma.types import VerificationScope
    from s0ma.verifiers.interoception import MetricsCollector

__all__ = [
    "verify_all",
    "verify_structural",
    "verify_contracts",
    "verify_interoception",
    "verify_coverage",
    "verify_incremental",
    "DiscoveredDeclaration",
    "DiscoveredSurface",
]


def verify_all(
    registry: ComponentRegistry,
    *,
    metrics_collector: MetricsCollector | None = None,
    coverage_data_path: Path | None = None,
    include_scopes: set[VerificationScope] | None = None,
    discovered_surface: DiscoveredSurface | None = None,
) -> VerificationReport:
    """Run all registered verifiers and return an aggregated report.

    Args:
        registry: The registry to verify.
        metrics_collector: Optional MetricsCollector for interoception.
            Uses the global singleton if None.
        coverage_data_path: Optional path to .coverage file for the
            coverage auditor.
        include_scopes: If set, only run verifiers matching these scopes.
            Default: run all available verifiers.

    Returns:
        VerificationReport aggregating results from all verifiers.
    """
    verifiers = _get_available_verifiers(
        metrics_collector=metrics_collector,
        coverage_data_path=coverage_data_path,
    )

    if include_scopes is not None:
        verifiers = [v for v in verifiers if v.scope in include_scopes]

    results: list[VerificationResult] = []
    for verifier in verifiers:
        if isinstance(verifier, StructuralVerifier):
            result = verifier.verify(registry)
        else:
            result = verifier.verify(
                registry, discovered_surface=discovered_surface,
            )
        results.append(result)

    total_anomalies = sum(len(r.anomalies) for r in results)
    total_errors = sum(r.error_count for r in results)
    total_warnings = sum(r.warning_count for r in results)
    total_duration_ms = sum(r.duration_ms for r in results)

    return VerificationReport(
        results=results,
        total_anomalies=total_anomalies,
        total_errors=total_errors,
        total_warnings=total_warnings,
        total_duration_ms=total_duration_ms,
        report_at=datetime.now(UTC),
    )


def verify_structural(registry: ComponentRegistry) -> VerificationResult:
    """Run only the structural verifier.

    Args:
        registry: The registry to verify.

    Returns:
        VerificationResult from the structural verifier.
    """
    verifier = StructuralVerifier()
    return verifier.verify(registry)


def verify_contracts(
    registry: ComponentRegistry,
    *,
    discovered_surface: DiscoveredSurface | None = None,
) -> VerificationResult:
    """Run only the contract verifier.

    Args:
        registry: The registry to verify.

    Returns:
        VerificationResult from the contract verifier.
    """
    verifier = ContractVerifier()
    return verifier.verify(registry, discovered_surface=discovered_surface)


def verify_interoception(
    registry: ComponentRegistry,
    collector: MetricsCollector | None = None,
    *,
    discovered_surface: DiscoveredSurface | None = None,
) -> VerificationResult:
    """Run only the interoception monitor.

    Args:
        registry: The registry to verify.
        collector: Optional MetricsCollector. Uses the global singleton
            if None.

    Returns:
        VerificationResult from the interoception monitor.
    """
    verifier = InteroceptionVerifier(collector=collector)
    return verifier.verify(registry, discovered_surface=discovered_surface)


def verify_coverage(
    registry: ComponentRegistry,
    metrics_collector: MetricsCollector | None = None,
    coverage_data_path: Path | None = None,
    *,
    discovered_surface: DiscoveredSurface | None = None,
) -> VerificationResult:
    """Run only the coverage auditor.

    Args:
        registry: The registry to verify.
        metrics_collector: Optional MetricsCollector for metrics-based
            detection. Uses the global singleton if None.
        coverage_data_path: Optional path to .coverage file.

    Returns:
        VerificationResult from the coverage auditor.
    """
    verifier = CoverageAuditor(
        metrics_collector=metrics_collector,
        coverage_data_path=coverage_data_path,
    )
    return verifier.verify(registry, discovered_surface=discovered_surface)


def verify_incremental(
    registry: ComponentRegistry, component_name: str
) -> VerificationResult:
    """Verify only the named component and its direct dependencies.

    Runs structural checks scoped to the component: integrity, dependency
    existence, layer conformance, cycle introduction. Designed for tight
    iteration loops where per-component verification must be fast.

    Args:
        registry: The registry to verify.
        component_name: Name of the component to verify.

    Returns:
        VerificationResult scoped to the named component and its deps.
    """
    verifier = StructuralVerifier()
    return verifier.verify_incremental(registry, component_name)


def _get_available_verifiers(
    *,
    metrics_collector: MetricsCollector | None = None,
    coverage_data_path: Path | None = None,
) -> list[Any]:
    """Return instances of all available verifiers.

    Returns structural, contract, interoception, and coverage verifiers.
    """
    return [
        StructuralVerifier(),
        ContractVerifier(),
        InteroceptionVerifier(collector=metrics_collector),
        CoverageAuditor(
            metrics_collector=metrics_collector,
            coverage_data_path=coverage_data_path,
        ),
    ]
