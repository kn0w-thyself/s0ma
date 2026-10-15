"""The Phase 2 Self-Model Test Suite — the capstone of the verification engine.

These tests verify that ALL verifiers can accurately assess the framework's
own codebase. If these tests fail, the verification engine itself is
untrustworthy.

This is the Phase 2 equivalent of the Phase 1 bootstrap test:
- Phase 1 asked: "Can the system describe itself?"
- Phase 2 asks: "Does the self-model match reality across all dimensions?"

The combined result from all verifiers must show zero errors when run
against S0ma itself.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from s0ma import verify
from s0ma._bootstrap import (
    EXPECTED_FRAMEWORK_COMPONENT_COUNT,
    bootstrap_register,
)
from s0ma.registry import ComponentRegistry
from s0ma.types import AnomalyKind, VerificationScope
from s0ma.verifiers import (
    verify_all,
    verify_contracts,
    verify_coverage,
    verify_structural,
)

if TYPE_CHECKING:
    from pathlib import Path

# ======================================================================
# Helpers
# ======================================================================


def _get_initialized_registry() -> ComponentRegistry:
    """Create a fresh registry and run bootstrap registration."""
    registry = ComponentRegistry(persist=False)
    bootstrap_register(registry)
    return registry


# ======================================================================
# Test: Full Verification Suite (THE Phase 2 test)
# ======================================================================


class TestSelfModelVerification:
    """The Phase 2 Self-Model Test Suite.

    These tests verify that the verification engine can accurately
    assess the framework's own codebase. If these tests fail,
    the verification engine itself is untrustworthy.
    """

    def test_full_verification_passes(self) -> None:
        """All verifiers pass when run against S0ma itself.

        This is the single most important test for Phase 2.
        It runs structural, contract, interoception, and coverage
        verifiers against the framework's own registry. The combined
        result must show zero ERROR-severity anomalies.
        """
        registry = _get_initialized_registry()
        report = verify_all(registry)
        assert report.passed, (
            f"Full verification FAILED with {report.total_errors} errors:\n"
            + report.describe()
        )

    def test_convenience_verify_function_passes(self) -> None:
        """The top-level verify() convenience function works correctly.

        verify() wraps verify_all() and uses the global registry
        when none is provided.
        """
        registry = _get_initialized_registry()
        report = verify(registry)
        assert report.passed, report.describe()

    def test_structural_verification_passes(self) -> None:
        """Structural verifier finds no drift in S0ma.

        The structural verifier uses AST analysis to compare registry
        declarations against actual source code. No structural
        discrepancies should exist in the framework itself.
        """
        registry = _get_initialized_registry()
        result = verify_structural(registry)
        assert result.passed, (
            "Structural verification FAILED:\n" + result.describe()
        )

    def test_contract_verification_passes(self) -> None:
        """Contract verifier finds no issues in S0ma.

        The contract verifier checks contract coverage and validates
        performance/error rate thresholds. Framework components should
        all have declared contracts.
        """
        registry = _get_initialized_registry()
        result = verify_contracts(registry)
        assert result.passed, (
            "Contract verification FAILED:\n" + result.describe()
        )

    def test_coverage_verification_passes(self) -> None:
        """Coverage auditor finds no errors in S0ma.

        The coverage auditor checks for phantom limbs, vestigial
        organs, and atrophied muscles. No ERROR-severity anomalies
        should be found in the framework itself.
        """
        registry = _get_initialized_registry()
        result = verify_coverage(registry)
        assert result.passed, (
            "Coverage verification FAILED:\n" + result.describe()
        )

    def test_no_phantom_limbs_in_framework(self) -> None:
        """Every framework component has corresponding source code.

        A phantom limb is a registry entry with no matching code.
        The structural verifier resolves each qualified_name to
        a real module attribute.
        """
        registry = _get_initialized_registry()
        result = verify_structural(registry)
        phantoms = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.PHANTOM_LIMB
        ]
        assert phantoms == [], (
            "Phantom limbs found:\n"
            + "\n".join(f"  - {a.message}" for a in phantoms)
        )

    def test_no_blind_spots_in_framework(self) -> None:
        """Every public entity is registered or accounted for.

        Verified by the Phase 1 bootstrap verifier (which is
        still run as part of backward compatibility). This test
        confirms structural verification doesn't introduce new
        blind spots.
        """
        from s0ma._verifier import verify_self_model

        registry = _get_initialized_registry()
        anomalies = verify_self_model(registry)
        blind_spots = [
            a for a in anomalies
            if a.kind == AnomalyKind.IMMUNE_RESPONSE
        ]
        assert blind_spots == [], (
            "Blind spots found:\n"
            + "\n".join(f"  - {a.message}" for a in blind_spots)
        )

    def test_no_dependency_cycles(self) -> None:
        """The framework dependency graph is acyclic.

        Dependency cycles are detected by the structural verifier's
        full-graph cycle detection (Tarjan's algorithm / DFS).
        """
        registry = _get_initialized_registry()
        result = verify_structural(registry)
        cycle_anomalies = [
            a for a in result.anomalies
            if "dependency cycle detected" in a.message.lower()
        ]
        assert cycle_anomalies == [], (
            "Dependency cycles found:\n"
            + "\n".join(f"  - {a.message}" for a in cycle_anomalies)
        )

    def test_layer_conformance(self) -> None:
        """All framework components respect layer boundaries.

        Layer violations (e.g., DOMAIN depending on PRESENTATION)
        are detected as INFLAMMATION anomalies by the structural
        verifier's layer conformance check.
        """
        registry = _get_initialized_registry()
        result = verify_structural(registry)
        layer_violations = [
            a for a in result.anomalies
            if "layer" in a.message.lower()
            and a.kind == AnomalyKind.INFLAMMATION
        ]
        assert layer_violations == [], (
            "Layer violations found:\n"
            + "\n".join(f"  - {a.message}" for a in layer_violations)
        )

    def test_contracts_are_declared(self) -> None:
        """Every framework component has non-empty contracts.

        Components should declare at least some behavioral
        expectations (preconditions, postconditions, or invariants).
        Components without any contracts are not necessarily errors
        but reduce the self-model's expressiveness.
        """
        registry = _get_initialized_registry()
        components_without_contracts = []
        for name in registry:
            spec = registry.get(name)
            if spec is None:
                continue
            total_contracts = (
                len(spec.contracts.preconditions)
                + len(spec.contracts.postconditions)
                + len(spec.contracts.invariants)
            )
            if total_contracts == 0:
                components_without_contracts.append(name)

        # Not every component needs contracts, but the majority should
        total = registry.count()
        with_contracts = total - len(components_without_contracts)
        coverage = with_contracts / total if total > 0 else 0
        # At least 40% of framework components should have contracts
        assert coverage >= 0.4, (
            f"Only {coverage:.0%} of components have contracts. "
            f"Components without: {components_without_contracts}"
        )


# ======================================================================
# Test: de Silva Erosion Coverage & Research Metrics
# ======================================================================


class TestResearchMetrics:
    """Verify the research-grounded metrics are met.

    These tests assert that S0ma meets the benchmarks from
    the academic literature that ground the project's research.
    """

    def test_de_silva_erosion_coverage(self, tmp_path: Path) -> None:
        """All three erosion-control strategies are active.

        de Silva et al. (2012) identified three strategies:
        - Minimise: prevent drift at creation (@component decorator)
        - Prevent: block unregistered code (import hook)
        - Repair: detect and report drift (verification engine)

        S0ma implements all three simultaneously.
        The import hook must be installed for 'prevent' to be active.
        """
        from s0ma.import_hook import (
            install_import_hook,
            uninstall_import_hook,
        )

        registry = _get_initialized_registry()

        # Install the import hook so the prevent strategy is active
        install_import_hook(
            project_root=tmp_path, allowlist={"s0ma"}, strict=False,
        )
        try:
            result = verify_structural(registry)
        finally:
            uninstall_import_hook()

        erosion = result.details.get("erosion_coverage", {})
        assert erosion.get("minimise_active") is True, (
            "Minimise strategy (@component) should be active"
        )
        assert erosion.get("prevent_active") is True, (
            "Prevent strategy (import hook) should be active"
        )
        assert erosion.get("repair_active") is True, (
            "Repair strategy (verification engine) should be active"
        )
        assert erosion.get("all_strategies_active") is True, (
            "All three de Silva strategies should be active"
        )

    def test_automation_metric_exceeds_target(self) -> None:
        """Kounev & Spinner automation metric exceeds 93%.

        Kounev & Spinner (2015) achieved 85.4% automation on legacy
        systems. S0ma targets >93% since the self-model is built
        from inception — every component has structural data from
        the start. The threshold is 93%+ (well above the 85.4%
        baseline) and adjusts slightly as new string-contract
        components are added to the framework.
        """
        registry = _get_initialized_registry()
        result = verify_coverage(registry)

        automation = result.details.get("automation_metric", 0.0)
        assert automation >= 0.93, (
            f"Automation metric is {automation:.1%}, "
            f"expected >= 93% (Kounev & Spinner 2015 baseline: 85.4%)"
        )

    def test_murphy_reflexion_categories(self) -> None:
        """The structural verifier produces Murphy's three output categories.

        Murphy, Notkin & Sullivan (2001) defined three categories:
        - Convergences: model and code agree
        - Divergences: model and code conflict
        - Absences: expected elements missing

        The structural verifier must explicitly classify output
        into these three categories.
        """
        registry = _get_initialized_registry()
        result = verify_structural(registry)

        reflexion = result.details.get("reflexion_analysis", {})
        assert "convergences" in reflexion, (
            "Reflexion analysis must include convergences"
        )
        assert "divergences" in reflexion, (
            "Reflexion analysis must include divergences"
        )
        assert "absences" in reflexion, (
            "Reflexion analysis must include absences"
        )

        # For a healthy codebase, convergences should be non-empty
        assert len(reflexion["convergences"]) > 0, (
            "A healthy codebase should have at least some convergences"
        )
        # And divergences should be minimal (only warnings, no errors)
        divergence_errors = [
            d for d in reflexion["divergences"]
            if d.get("severity") == "ERROR"
        ]
        assert divergence_errors == [], (
            "Found ERROR-level divergences in framework:\n"
            + "\n".join(str(d) for d in divergence_errors)
        )


# ======================================================================
# Test: Verification Report Quality
# ======================================================================


class TestVerificationReportQuality:
    """Verify that the verification report is useful and accurate."""

    def test_verification_report_is_substantive(self) -> None:
        """The verification report is detailed enough to be useful.

        A useful report must include information from all verifier
        scopes, summary statistics, and be at least 500 characters.
        """
        registry = _get_initialized_registry()
        report = verify_all(registry)
        description = report.describe()

        assert len(description) > 500, (
            f"Report description too short ({len(description)} chars)"
        )
        assert "structural" in description.lower(), (
            "Report should mention structural verification"
        )
        assert "contract" in description.lower(), (
            "Report should mention contract verification"
        )
        assert "coverage" in description.lower(), (
            "Report should mention coverage verification"
        )

    def test_verification_report_has_all_scopes(self) -> None:
        """The report includes results from all four verifier scopes."""
        registry = _get_initialized_registry()
        report = verify_all(registry)

        scopes_present = {r.scope for r in report.results}
        expected_scopes = {
            VerificationScope.STRUCTURAL,
            VerificationScope.CONTRACT,
            VerificationScope.INTEROCEPTION,
            VerificationScope.COVERAGE,
        }
        assert scopes_present == expected_scopes, (
            f"Missing scopes: {expected_scopes - scopes_present}"
        )

    def test_verification_report_round_trip(self) -> None:
        """The report can be serialized and deserialized without loss."""
        registry = _get_initialized_registry()
        report = verify_all(registry)

        data = report.to_dict()
        json_str = json.dumps(data)
        restored = json.loads(json_str)

        assert restored["passed"] == report.passed
        assert restored["total_errors"] == report.total_errors
        assert restored["total_warnings"] == report.total_warnings
        assert restored["total_anomalies"] == report.total_anomalies
        assert len(restored["results"]) == len(report.results)

        # Verify each result round-trips correctly
        for original, restored_r in zip(
            report.results, restored["results"], strict=True
        ):
            assert restored_r["verifier_name"] == original.verifier_name
            assert restored_r["passed"] == original.passed
            assert (
                restored_r["components_checked"]
                == original.components_checked
            )

    def test_verification_report_summary_statistics(self) -> None:
        """Summary statistics in the report are internally consistent."""
        registry = _get_initialized_registry()
        report = verify_all(registry)

        # Total anomalies should equal sum of per-verifier anomalies
        computed_total = sum(
            len(r.anomalies) for r in report.results
        )
        assert report.total_anomalies == computed_total

        # Total errors/warnings should match per-verifier sums
        computed_errors = sum(r.error_count for r in report.results)
        assert report.total_errors == computed_errors

        computed_warnings = sum(r.warning_count for r in report.results)
        assert report.total_warnings == computed_warnings

    def test_include_scopes_filter_works(self) -> None:
        """The include_scopes parameter correctly filters verifiers."""
        registry = _get_initialized_registry()

        # Run only structural verification
        report = verify_all(
            registry,
            include_scopes={VerificationScope.STRUCTURAL},
        )
        assert len(report.results) == 1
        assert report.results[0].scope == VerificationScope.STRUCTURAL


# ======================================================================
# Test: Backward Compatibility with Phase 1
# ======================================================================


class TestPhase1BackwardCompatibility:
    """Ensure Phase 2 additions don't break Phase 1 functionality."""

    def test_phase1_bootstrap_verifier_still_works(self) -> None:
        """The Phase 1 verify_self_model() still returns zero anomalies.

        Phase 2 is additive — it does not modify the Phase 1
        verification path. The original bootstrap verifier must
        continue to work unchanged.
        """
        from s0ma._verifier import verify_self_model

        registry = _get_initialized_registry()
        anomalies = verify_self_model(registry)
        assert anomalies == [], (
            f"Phase 1 bootstrap verifier failed with "
            f"{len(anomalies)} anomalies:\n"
            + "\n".join(
                f"  [{a.severity.name}] {a.message}" for a in anomalies
            )
        )

    def test_framework_component_count_is_stable(self) -> None:
        """The framework component count matches the expected constant.

        EXPECTED_FRAMEWORK_COMPONENT_COUNT is a tripwire — if a
        framework component is added or removed without updating
        this constant, the test fails.
        """
        registry = _get_initialized_registry()
        assert registry.count() == EXPECTED_FRAMEWORK_COMPONENT_COUNT, (
            f"Expected {EXPECTED_FRAMEWORK_COMPONENT_COUNT}, "
            f"found {registry.count()}"
        )

    def test_snapshot_describe_still_works(self) -> None:
        """The Phase 1 snapshot.describe() method still works."""
        registry = _get_initialized_registry()
        snapshot = registry.snapshot()
        description = snapshot.describe()

        assert len(description) > 500
        assert "S0MA SYSTEM SELF-DESCRIPTION" in description
        assert "COMPONENTS BY LAYER" in description
