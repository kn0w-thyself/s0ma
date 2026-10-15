"""Integration tests — full verification pipeline end-to-end.

Verifies that all four verifier scopes (structural, contract,
interoception, coverage) work together in a coordinated pipeline.
Tests sabotage detection, contract violation pipelines, interoception
thresholds, coverage auditing, and LLM-consumable output.

This is the Milestone 7 integration test file for Phase 2.
"""

from __future__ import annotations

import time

import pytest

from s0ma._bootstrap import bootstrap_register
from s0ma.models import (
    Anomaly,
    ComponentSpec,
    Contract,
    ResourceProfile,
    VerificationReport,
    VerificationResult,
)
from s0ma.registry import ComponentRegistry
from s0ma.types import (
    AnomalyKind,
    AnomalySeverity,
    ComponentKind,
    Layer,
    VerificationScope,
)
from s0ma.verifiers import (
    verify_all,
    verify_contracts,
    verify_coverage,
    verify_interoception,
    verify_structural,
)
from s0ma.verifiers.contracts import (
    ContractVerifier,
    postcondition,
    precondition,
    set_contract_verification,
)
from s0ma.verifiers.interoception import MetricsCollector

# ======================================================================
# Helpers
# ======================================================================


def _fresh_registry() -> ComponentRegistry:
    """Create a fresh in-memory registry with bootstrap components."""
    registry = ComponentRegistry(persist=False)
    bootstrap_register(registry)
    return registry


def _register_sample_components(
    registry: ComponentRegistry,
) -> None:
    """Register a set of sample user components for testing."""
    registry.register(ComponentSpec(
        name="TaskModel",
        kind=ComponentKind.MODEL,
        layer=Layer.DOMAIN,
        intent="Represents a task entity with title and status",
        module_path="tests.sample_project.mini_app.models.task",
        qualified_name="tests.sample_project.mini_app.models.task.Task",
    ))
    registry.register(ComponentSpec(
        name="StorageAdapter",
        kind=ComponentKind.ADAPTER,
        layer=Layer.INFRASTRUCTURE,
        intent="Provides in-memory storage for task persistence",
        module_path="tests.sample_project.mini_app.adapters.storage",
        qualified_name=(
            "tests.sample_project.mini_app.adapters.storage"
            ".StorageAdapter"
        ),
    ))
    registry.register(ComponentSpec(
        name="TaskService",
        kind=ComponentKind.SERVICE,
        layer=Layer.APPLICATION,
        intent="Manages task lifecycle: creation, assignment, completion",
        dependencies=["TaskModel", "StorageAdapter"],
        contracts=Contract(
            preconditions=["task title is non-empty"],
            postconditions=["returns created Task"],
        ),
        module_path="tests.sample_project.mini_app.services.task_service",
        qualified_name=(
            "tests.sample_project.mini_app.services.task_service"
            ".TaskService"
        ),
    ))


# ======================================================================
# Full Pipeline Tests
# ======================================================================


class TestFullPipeline:
    """Full verification pipeline exercising all verifier scopes."""

    def test_full_pipeline_contains_all_scopes(self) -> None:
        """verify_all() returns results from all four verifier scopes."""
        registry = _fresh_registry()
        report = verify_all(registry)

        scopes = {r.scope for r in report.results}
        expected = {
            VerificationScope.STRUCTURAL,
            VerificationScope.CONTRACT,
            VerificationScope.INTEROCEPTION,
            VerificationScope.COVERAGE,
        }
        assert scopes == expected, (
            f"Missing scopes: {expected - scopes}"
        )

    def test_full_pipeline_with_user_components(self) -> None:
        """Pipeline works with both framework and user components."""
        registry = _fresh_registry()
        _register_sample_components(registry)

        report = verify_all(registry)
        assert isinstance(report, VerificationReport)
        assert len(report.results) == 4
        # Framework + user components are both checked
        structural = next(
            r for r in report.results
            if r.scope == VerificationScope.STRUCTURAL
        )
        assert structural.components_checked > 25  # framework + user

    def test_full_pipeline_report_summary_consistent(self) -> None:
        """Report summary statistics match per-verifier aggregation."""
        registry = _fresh_registry()
        report = verify_all(registry)

        computed_anomalies = sum(
            len(r.anomalies) for r in report.results
        )
        assert report.total_anomalies == computed_anomalies

        computed_errors = sum(r.error_count for r in report.results)
        assert report.total_errors == computed_errors

    def test_empty_registry_produces_clean_report(self) -> None:
        """verify_all() on an empty registry produces a valid report."""
        registry = ComponentRegistry(persist=False)
        report = verify_all(registry)

        assert isinstance(report, VerificationReport)
        assert report.total_errors == 0
        assert len(report.results) == 4


# ======================================================================
# Sabotage Detection Tests
# ======================================================================


class TestSabotageDetection:
    """Deliberately introduce drift and verify it's caught."""

    def test_signature_drift_detected(self) -> None:
        """Changing a function signature without updating the contract
        is caught by the structural verifier."""
        registry = _fresh_registry()
        # Register a component claiming PaymentRequest/PaymentResult types
        # but the actual function takes (float, str) -> bool
        registry.register(ComponentSpec(
            name="SabotageTarget",
            kind=ComponentKind.FUNCTION,
            layer=Layer.DOMAIN,
            intent="A function whose signature will be sabotaged",
            contracts=Contract(
                input_type="PaymentRequest",
                output_type="PaymentResult",
            ),
            module_path="tests.test_fixtures.drifted_signatures",
            qualified_name=(
                "tests.test_fixtures.drifted_signatures"
                ".process_payment"
            ),
        ))

        result = verify_structural(registry)
        # Should detect a signature mismatch (actual: float, str -> bool)
        sig_anomalies = [
            a for a in result.anomalies
            if a.component_name == "SabotageTarget"
        ]
        assert len(sig_anomalies) > 0, (
            "Structural verifier should detect signature drift"
        )

    def test_phantom_dependency_detected(self) -> None:
        """A component that declares a dependency it doesn't import
        is flagged by the structural verifier."""
        registry = _fresh_registry()
        registry.register(ComponentSpec(
            name="PhantomDepTarget",
            kind=ComponentKind.SERVICE,
            layer=Layer.APPLICATION,
            intent="A service declaring a dependency it does not import",
            dependencies=["NonexistentService"],  # Declared but not real
            module_path="tests.test_fixtures.undeclared_deps",
            qualified_name=(
                "tests.test_fixtures.undeclared_deps"
                ".ServiceWithHiddenDep"
            ),
        ))

        result = verify_structural(registry)
        dep_anomalies = [
            a for a in result.anomalies
            if a.component_name == "PhantomDepTarget"
            and "dependency" in a.message.lower()
        ]
        assert len(dep_anomalies) > 0, (
            "Structural verifier should detect phantom dependencies"
        )


# ======================================================================
# Contract Violation Pipeline Tests
# ======================================================================


class TestContractViolationPipeline:
    """Contract verifier integration with executable validators."""

    def test_contract_coverage_reported(self) -> None:
        """Contract verifier reports coverage of executable contracts."""
        registry = _fresh_registry()
        result = verify_contracts(registry)

        coverage = result.details.get("contract_coverage", {})
        assert "total_string_contracts" in coverage
        assert "coverage_percentage" in coverage
        assert coverage["total_string_contracts"] >= 0

    def test_performance_contract_violation(self) -> None:
        """A function exceeding max_latency_ms produces INFLAMMATION."""
        def slow_func() -> str:
            time.sleep(0.05)
            return "done"

        _, anomalies = ContractVerifier.check_performance(
            slow_func,
            max_latency_ms=10.0,
            component_name="SlowService",
        )
        assert len(anomalies) == 1
        assert anomalies[0].kind == AnomalyKind.INFLAMMATION
        assert "SlowService" in anomalies[0].message

    def test_error_rate_violation(self) -> None:
        """Error rate exceeding threshold produces INFLAMMATION."""
        anomalies = ContractVerifier.check_error_rate(
            error_count=15,
            total_count=100,
            threshold=0.10,
            component_name="ErrorProne",
        )
        assert len(anomalies) == 1
        assert anomalies[0].kind == AnomalyKind.INFLAMMATION
        assert "ErrorProne" in anomalies[0].message

    def test_precondition_violation_raises(self) -> None:
        """Precondition decorator raises ContractViolationError."""
        from s0ma.exceptions import ContractViolationError

        set_contract_verification(True)
        try:

            @precondition(
                lambda x: x > 0, "x must be positive"
            )
            def positive_only(x: int) -> int:
                return x * 2

            with pytest.raises(ContractViolationError):
                positive_only(-1)

            # Valid input should work
            assert positive_only(5) == 10
        finally:
            set_contract_verification(True)

    def test_postcondition_violation_raises(self) -> None:
        """Postcondition decorator raises ContractViolationError."""
        from s0ma.exceptions import ContractViolationError

        set_contract_verification(True)
        try:

            @postcondition(
                lambda result: result > 0, "result must be positive"
            )
            def sometimes_negative(x: int) -> int:
                return x

            with pytest.raises(ContractViolationError):
                sometimes_negative(-5)

            assert sometimes_negative(10) == 10
        finally:
            set_contract_verification(True)


# ======================================================================
# Interoception Pipeline Tests
# ======================================================================


class TestInteroceptionPipeline:
    """Interoception verifier integration with metrics collection."""

    def test_latency_violation_detected(self) -> None:
        """Components exceeding latency profile produce INFLAMMATION."""
        registry = _fresh_registry()
        collector = MetricsCollector()

        # Register a component with a strict latency profile
        registry.register(ComponentSpec(
            name="FastService",
            kind=ComponentKind.SERVICE,
            layer=Layer.APPLICATION,
            intent="A service with strict latency requirements for testing",
            resource_profile=ResourceProfile(
                expected_latency_p50_ms=5.0,
                expected_latency_p99_ms=20.0,
            ),
            module_path="myapp.services.fast",
            qualified_name="myapp.services.fast.FastService",
        ))

        # Simulate slow calls (100ms each)
        for _ in range(20):
            collector.record_call(
                "FastService",
                latency_ns=100_000_000,  # 100ms
            )

        result = verify_interoception(registry, collector=collector)
        inflammation = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.INFLAMMATION
            and a.component_name == "FastService"
        ]
        assert len(inflammation) > 0, (
            "Interoception should detect latency violation"
        )

    def test_error_rate_violation_detected(self) -> None:
        """Components exceeding error rate produce INFLAMMATION."""
        registry = _fresh_registry()
        collector = MetricsCollector()

        registry.register(ComponentSpec(
            name="ReliableService",
            kind=ComponentKind.SERVICE,
            layer=Layer.APPLICATION,
            intent="A service with strict error rate threshold for testing",
            resource_profile=ResourceProfile(
                expected_error_rate=0.01,
            ),
            module_path="myapp.services.reliable",
            qualified_name="myapp.services.reliable.ReliableService",
        ))

        # Simulate high error rate (50% errors)
        for i in range(20):
            collector.record_call(
                "ReliableService",
                latency_ns=1_000_000,
                error=i % 2 == 0,
            )

        result = verify_interoception(registry, collector=collector)
        error_anomalies = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.INFLAMMATION
            and a.component_name == "ReliableService"
            and "error" in a.message.lower()
        ]
        assert len(error_anomalies) > 0, (
            "Interoception should detect error rate violation"
        )

    def test_no_profile_no_anomalies(self) -> None:
        """Components without ResourceProfile produce no anomalies."""
        registry = _fresh_registry()
        collector = MetricsCollector()

        result = verify_interoception(registry, collector=collector)
        # Framework components have no ResourceProfile, so no anomalies
        inflammation = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.INFLAMMATION
        ]
        assert inflammation == []


# ======================================================================
# Coverage Audit Pipeline Tests
# ======================================================================


class TestCoverageAuditPipeline:
    """Coverage auditor integration with pathology detection."""

    def test_vestigial_organ_detected(self) -> None:
        """Unused user component flagged as vestigial."""
        registry = _fresh_registry()
        # Register a standalone component no one depends on
        registry.register(ComponentSpec(
            name="OrphanedHelper",
            kind=ComponentKind.FUNCTION,
            layer=Layer.DOMAIN,
            intent="A helper function that no other component uses",
            module_path="myapp.helpers.orphan",
            qualified_name="myapp.helpers.orphan.OrphanedHelper",
        ))

        result = verify_coverage(registry)
        vestigial = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.VESTIGIAL_ORGAN
            and a.component_name == "OrphanedHelper"
        ]
        assert len(vestigial) > 0, (
            "Coverage auditor should flag unused components as vestigial"
        )

    def test_deprecated_with_calls_is_atrophied(self) -> None:
        """Deprecated component with metrics calls = ATROPHIED_MUSCLE."""
        registry = _fresh_registry()
        collector = MetricsCollector()

        registry.register(ComponentSpec(
            name="OldService",
            kind=ComponentKind.SERVICE,
            layer=Layer.APPLICATION,
            intent="A deprecated service that should no longer be called",
            metadata={"deprecated": True},
            module_path="myapp.services.old",
            qualified_name="myapp.services.old.OldService",
        ))

        # Simulate calls to the deprecated component
        for _ in range(5):
            collector.record_call(
                "OldService", latency_ns=1_000_000
            )

        result = verify_coverage(
            registry, metrics_collector=collector
        )
        atrophied = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.ATROPHIED_MUSCLE
            and a.component_name == "OldService"
        ]
        assert len(atrophied) > 0, (
            "Coverage auditor should flag deprecated+called as atrophied"
        )

    def test_automation_metric_in_details(self) -> None:
        """Coverage auditor includes automation metric in details."""
        registry = _fresh_registry()
        result = verify_coverage(registry)

        assert "automation_metric" in result.details
        metric = result.details["automation_metric"]
        assert isinstance(metric, float)
        assert 0.0 <= metric <= 1.0


# ======================================================================
# Mixed Health Tests
# ======================================================================


class TestMixedHealth:
    """Tests with a mix of healthy and unhealthy components."""

    def test_mixed_pass_fail_correctly_separated(self) -> None:
        """Report with some verifiers having anomalies, some clean."""
        registry = _fresh_registry()
        collector = MetricsCollector()

        # Add a component that will cause interoception failure
        registry.register(ComponentSpec(
            name="StressedService",
            kind=ComponentKind.SERVICE,
            layer=Layer.APPLICATION,
            intent="A service that will exceed its resource profile",
            resource_profile=ResourceProfile(
                expected_latency_p50_ms=1.0,
            ),
            module_path="myapp.services.stressed",
            qualified_name="myapp.services.stressed.StressedService",
        ))

        # Record very slow calls
        for _ in range(20):
            collector.record_call(
                "StressedService",
                latency_ns=500_000_000,  # 500ms
            )

        report = verify_all(registry, metrics_collector=collector)

        # Contract verifier should have no anomalies
        contract = next(
            r for r in report.results
            if r.scope == VerificationScope.CONTRACT
        )
        assert contract.passed
        assert len(contract.anomalies) == 0

        # Interoception verifier should detect the latency issue
        interoception = next(
            r for r in report.results
            if r.scope == VerificationScope.INTEROCEPTION
        )
        latency_anomalies = [
            a for a in interoception.anomalies
            if a.component_name == "StressedService"
            and a.kind == AnomalyKind.INFLAMMATION
        ]
        assert len(latency_anomalies) > 0, (
            "Interoception should detect latency violation for "
            "StressedService"
        )

        # Report should include anomalies from multiple verifiers
        assert report.total_anomalies > 0


# ======================================================================
# LLM-Consumable Output Tests
# ======================================================================


class TestExplainForLLM:
    """Tests for the explain_for_llm() method on verification models."""

    def test_result_explain_for_llm_clean(self) -> None:
        """explain_for_llm() on a clean result is informative."""
        registry = _fresh_registry()
        # Use contract verifier which produces zero anomalies
        result = verify_contracts(registry)
        output = result.explain_for_llm()

        assert "Contract Verifier" in output
        assert "PASSED" in output
        assert "No anomalies found" in output

    def test_result_explain_for_llm_with_anomalies(self) -> None:
        """explain_for_llm() on a failing result provides actionable context."""
        result = VerificationResult(
            verifier_name="Test Verifier",
            scope=VerificationScope.STRUCTURAL,
            anomalies=[
                Anomaly(
                    kind=AnomalyKind.PHANTOM_LIMB,
                    severity=AnomalySeverity.ERROR,
                    component_name="MissingComponent",
                    message=(
                        "Component 'MissingComponent' references "
                        "module 'myapp.gone' which cannot be imported"
                    ),
                    details={"module": "myapp.gone"},
                ),
            ],
            components_checked=10,
            checks_performed=30,
        )

        output = result.explain_for_llm()
        assert "FAILED" in output
        assert "Issue 1" in output
        assert "PHANTOM_LIMB" in output
        assert "MissingComponent" in output
        assert "Suggestion:" in output
        assert "module path" in output.lower() or "module" in output.lower()

    def test_report_explain_for_llm_groups_by_status(self) -> None:
        """explain_for_llm() groups failed verifiers before passed ones."""
        registry = _fresh_registry()
        report = verify_all(registry)

        output = report.explain_for_llm()
        assert "Verification Report" in output
        # On a healthy codebase, should have passed section
        assert "Passed Verifiers" in output

    def test_report_explain_for_llm_with_failures(self) -> None:
        """explain_for_llm() on a report with failures is actionable."""
        failed_result = VerificationResult(
            verifier_name="Test Verifier",
            scope=VerificationScope.STRUCTURAL,
            anomalies=[
                Anomaly(
                    kind=AnomalyKind.INFLAMMATION,
                    severity=AnomalySeverity.ERROR,
                    component_name="BadService",
                    message="Layer violation: DOMAIN depends on PRESENTATION",
                    details={"layer": "DOMAIN", "depends_on_layer": "PRESENTATION"},
                ),
            ],
            components_checked=5,
            checks_performed=15,
        )
        passed_result = VerificationResult(
            verifier_name="Contract Verifier",
            scope=VerificationScope.CONTRACT,
            components_checked=5,
            checks_performed=5,
        )

        report = VerificationReport(
            results=[failed_result, passed_result],
            total_anomalies=1,
            total_errors=1,
            total_warnings=0,
        )

        output = report.explain_for_llm()
        assert "Failed Verifiers" in output
        assert "action required" in output.lower()
        assert "Passed Verifiers" in output
        assert "Contract Verifier" in output

    def test_explain_for_llm_includes_suggestions(self) -> None:
        """explain_for_llm() includes fix suggestions for each anomaly."""
        result = VerificationResult(
            verifier_name="Test Verifier",
            scope=VerificationScope.COVERAGE,
            anomalies=[
                Anomaly(
                    kind=AnomalyKind.VESTIGIAL_ORGAN,
                    severity=AnomalySeverity.INFO,
                    component_name="UnusedHelper",
                    message="Component 'UnusedHelper' is never imported",
                ),
                Anomaly(
                    kind=AnomalyKind.ATROPHIED_MUSCLE,
                    severity=AnomalySeverity.WARNING,
                    component_name="OldAPI",
                    message="Deprecated component 'OldAPI' still called",
                    details={"call_count": 42},
                ),
            ],
            components_checked=10,
            checks_performed=20,
        )

        output = result.explain_for_llm()
        assert "Suggestion:" in output
        # Vestigial suggestion should mention unused/entry point
        assert "unused" in output.lower() or "entry point" in output.lower()
        # Atrophied suggestion should mention migration
        assert "deprecated" in output.lower() or "migrate" in output.lower()

    def test_explain_for_llm_includes_context_details(self) -> None:
        """explain_for_llm() includes anomaly details as context."""
        result = VerificationResult(
            verifier_name="Test Verifier",
            scope=VerificationScope.INTEROCEPTION,
            anomalies=[
                Anomaly(
                    kind=AnomalyKind.INFLAMMATION,
                    severity=AnomalySeverity.WARNING,
                    component_name="SlowDB",
                    message="Exceeded max_latency_ms",
                    details={
                        "max_latency_ms": 50.0,
                        "actual_latency_ms": 200.0,
                    },
                ),
            ],
            components_checked=1,
            checks_performed=3,
        )

        output = result.explain_for_llm()
        assert "Context:" in output
        assert "max_latency_ms" in output
        assert "actual_latency_ms" in output

    def test_report_explain_for_llm_includes_erosion(self) -> None:
        """explain_for_llm() includes erosion coverage when available."""
        result = VerificationResult(
            verifier_name="Structural Verifier",
            scope=VerificationScope.STRUCTURAL,
            details={
                "erosion_coverage": {
                    "minimise_active": True,
                    "prevent_active": True,
                    "repair_active": True,
                },
            },
        )
        report = VerificationReport(results=[result])

        output = report.explain_for_llm()
        assert "Erosion Coverage" in output

    def test_report_explain_for_llm_includes_automation(self) -> None:
        """explain_for_llm() includes automation metric when available."""
        result = VerificationResult(
            verifier_name="Coverage Auditor",
            scope=VerificationScope.COVERAGE,
            details={"automation_metric": 0.97},
        )
        report = VerificationReport(results=[result])

        output = report.explain_for_llm()
        assert "Automation Metric" in output
        assert "97.0%" in output
