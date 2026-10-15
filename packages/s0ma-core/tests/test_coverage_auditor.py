"""Tests for the coverage auditor — Milestone 5 of Phase 2.

Validates the coverage auditor that detects dead code, unreachable
components, and code-model discrepancies using the full biological
pathology taxonomy. Tests cover:

- Phantom limb detection (component registered but code deleted)
- Vestigial organ detection (import-based and metrics-based)
- Atrophied muscle detection (deprecated component with recent calls)
- Immune response status (import hook check)
- Kounev & Spinner automation metric
- Framework component exclusion from vestigial detection
- Full coverage audit on S0ma itself
"""

from __future__ import annotations

import pytest

from s0ma.models import ComponentSpec, Contract, ResourceProfile
from s0ma.registry import ComponentRegistry
from s0ma.types import (
    AnomalyKind,
    AnomalySeverity,
    ComponentKind,
    Layer,
    VerificationScope,
)
from s0ma.verifiers.coverage import CoverageAuditor
from s0ma.verifiers.interoception import MetricsCollector

# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture()
def collector() -> MetricsCollector:
    """Fresh MetricsCollector for testing."""
    return MetricsCollector()


@pytest.fixture()
def auditor(collector: MetricsCollector) -> CoverageAuditor:
    """CoverageAuditor with a test collector."""
    return CoverageAuditor(metrics_collector=collector)


@pytest.fixture()
def auditor_no_metrics() -> CoverageAuditor:
    """CoverageAuditor with no metrics collector."""
    return CoverageAuditor(metrics_collector=None)


@pytest.fixture()
def registry_with_components() -> ComponentRegistry:
    """Registry with a small dependency graph for coverage testing.

    Graph:
        ServiceA -> ModelA
        ServiceA -> AdapterB
        AdapterB (standalone leaf)
        ModelA (standalone leaf)
        OrphanedService (no one depends on it)
    """
    reg = ComponentRegistry(persist=False)
    reg.register(ComponentSpec(
        name="ModelA",
        kind=ComponentKind.MODEL,
        layer=Layer.DOMAIN,
        intent="Core data model for testing coverage detection",
        module_path="test.models",
        qualified_name="test.models.ModelA",
    ))
    reg.register(ComponentSpec(
        name="AdapterB",
        kind=ComponentKind.ADAPTER,
        layer=Layer.INFRASTRUCTURE,
        intent="External system adapter for coverage testing",
        module_path="test.adapters",
        qualified_name="test.adapters.AdapterB",
    ))
    reg.register(ComponentSpec(
        name="ServiceA",
        kind=ComponentKind.SERVICE,
        layer=Layer.APPLICATION,
        intent="Application service that uses ModelA and AdapterB",
        dependencies=["ModelA", "AdapterB"],
        module_path="test.services",
        qualified_name="test.services.ServiceA",
    ))
    reg.register(ComponentSpec(
        name="OrphanedService",
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="A service that nobody depends on — should be vestigial",
        module_path="test.orphaned",
        qualified_name="test.orphaned.OrphanedService",
    ))
    return reg


@pytest.fixture()
def registry_with_deprecated(collector: MetricsCollector) -> ComponentRegistry:
    """Registry with a deprecated component that has recent calls."""
    reg = ComponentRegistry(persist=False)
    reg.register(ComponentSpec(
        name="ActiveService",
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="An active, healthy service used for testing",
        module_path="test.active",
        qualified_name="test.active.ActiveService",
    ))
    reg.register(ComponentSpec(
        name="DeprecatedHandler",
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="A deprecated handler still receiving traffic",
        metadata={"deprecated": True},
        module_path="test.deprecated",
        qualified_name="test.deprecated.DeprecatedHandler",
    ))
    reg.register(ComponentSpec(
        name="StatusDeprecated",
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="Another deprecated handler using status field",
        metadata={"status": "deprecated"},
        module_path="test.status_deprecated",
        qualified_name="test.status_deprecated.StatusDeprecated",
    ))
    # Record calls on the deprecated handler
    collector.record_call("DeprecatedHandler", 1_000_000)
    collector.record_call("DeprecatedHandler", 2_000_000)
    collector.record_call("StatusDeprecated", 500_000)
    return reg


@pytest.fixture()
def registry_with_profiles() -> ComponentRegistry:
    """Registry with components that have ResourceProfiles."""
    reg = ComponentRegistry(persist=False)
    reg.register(ComponentSpec(
        name="ProfiledService",
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="A service with a resource profile for monitoring",
        resource_profile=ResourceProfile(
            expected_latency_p50_ms=10.0,
            expected_error_rate=0.01,
        ),
        module_path="test.profiled",
        qualified_name="test.profiled.ProfiledService",
    ))
    reg.register(ComponentSpec(
        name="NoProfileService",
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="A service without a resource profile for testing",
        module_path="test.noprofile",
        qualified_name="test.noprofile.NoProfileService",
    ))
    return reg


# ======================================================================
# Phantom Limb Detection
# ======================================================================


class TestPhantomLimbDetection:
    """Test that phantom limb detection catches missing code."""

    def test_phantom_limb_unresolvable_module(
        self, auditor: CoverageAuditor
    ) -> None:
        """Registered component with non-existent module is a phantom."""
        reg = ComponentRegistry(persist=False)
        reg.register(ComponentSpec(
            name="GhostComponent",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A component whose module does not actually exist",
            module_path="nonexistent.module.path",
            qualified_name="nonexistent.module.path.GhostComponent",
        ))
        result = auditor.verify(reg)
        phantom_anomalies = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.PHANTOM_LIMB
        ]
        assert len(phantom_anomalies) > 0
        assert any(
            "GhostComponent" in a.message for a in phantom_anomalies
        )

    def test_phantom_limb_missing_attribute(
        self, auditor: CoverageAuditor
    ) -> None:
        """Component referencing a non-existent attr is a phantom."""
        reg = ComponentRegistry(persist=False)
        reg.register(ComponentSpec(
            name="MissingAttr",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="References an attribute that doesn't exist in os",
            module_path="os",
            qualified_name="os.ThisDoesNotExist",
        ))
        result = auditor.verify(reg)
        phantom_anomalies = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.PHANTOM_LIMB
        ]
        assert len(phantom_anomalies) > 0

    def test_valid_component_no_phantom(
        self, auditor: CoverageAuditor
    ) -> None:
        """Component referencing real code produces no phantom."""
        reg = ComponentRegistry(persist=False)
        reg.register(ComponentSpec(
            name="RealComponent",
            kind=ComponentKind.MODEL,
            layer=Layer.FRAMEWORK,
            intent="References a real Python entity for testing",
            module_path="s0ma.models",
            qualified_name="s0ma.models.ComponentSpec",
            is_framework=True,
        ))
        result = auditor.verify(reg)
        phantom_anomalies = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.PHANTOM_LIMB
        ]
        assert len(phantom_anomalies) == 0


# ======================================================================
# Vestigial Organ Detection
# ======================================================================


class TestVestigialOrganDetection:
    """Test that vestigial organ detection identifies unused code."""

    def test_vestigial_organ_not_in_any_dependency(
        self,
        auditor: CoverageAuditor,
        registry_with_components: ComponentRegistry,
    ) -> None:
        """Component not depended on by anyone is flagged."""
        result = auditor.verify(registry_with_components)
        vestigial_anomalies = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.VESTIGIAL_ORGAN
            and a.component_name == "OrphanedService"
        ]
        assert len(vestigial_anomalies) >= 1
        assert "OrphanedService" in vestigial_anomalies[0].message

    def test_depended_component_not_vestigial(
        self,
        auditor: CoverageAuditor,
        registry_with_components: ComponentRegistry,
    ) -> None:
        """Components that others depend on are not vestigial."""
        result = auditor.verify(registry_with_components)
        vestigial_names = {
            a.component_name for a in result.anomalies
            if a.kind == AnomalyKind.VESTIGIAL_ORGAN
        }
        # ModelA and AdapterB are depended on by ServiceA
        assert "ModelA" not in vestigial_names
        assert "AdapterB" not in vestigial_names

    def test_vestigial_organ_zero_calls_with_profile(
        self,
        collector: MetricsCollector,
        registry_with_profiles: ComponentRegistry,
    ) -> None:
        """Component with ResourceProfile but zero calls is vestigial."""
        auditor = CoverageAuditor(metrics_collector=collector)
        result = auditor.verify(registry_with_profiles)
        vestigial_anomalies = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.VESTIGIAL_ORGAN
            and a.component_name == "ProfiledService"
        ]
        assert len(vestigial_anomalies) >= 1

    def test_framework_components_excluded_from_vestigial(
        self, auditor: CoverageAuditor
    ) -> None:
        """Framework components are not flagged as vestigial."""
        reg = ComponentRegistry(persist=False)
        reg.register(ComponentSpec(
            name="FrameworkInfra",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent="Framework infrastructure component for testing",
            module_path="s0ma.registry",
            qualified_name="s0ma.registry.ComponentRegistry",
            is_framework=True,
        ))
        result = auditor.verify(reg)
        vestigial_anomalies = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.VESTIGIAL_ORGAN
        ]
        assert len(vestigial_anomalies) == 0


# ======================================================================
# Atrophied Muscle Detection
# ======================================================================


class TestAtrophiedMuscleDetection:
    """Test that deprecated but active components are caught."""

    def test_deprecated_with_calls_is_atrophied(
        self,
        collector: MetricsCollector,
        registry_with_deprecated: ComponentRegistry,
    ) -> None:
        """Deprecated component with recent calls is atrophied muscle."""
        auditor = CoverageAuditor(metrics_collector=collector)
        result = auditor.verify(registry_with_deprecated)
        atrophied_anomalies = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.ATROPHIED_MUSCLE
        ]
        assert len(atrophied_anomalies) >= 1
        names = {a.component_name for a in atrophied_anomalies}
        assert "DeprecatedHandler" in names

    def test_deprecated_status_field_detected(
        self,
        collector: MetricsCollector,
        registry_with_deprecated: ComponentRegistry,
    ) -> None:
        """Deprecated via metadata['status'] is also detected."""
        auditor = CoverageAuditor(metrics_collector=collector)
        result = auditor.verify(registry_with_deprecated)
        atrophied_anomalies = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.ATROPHIED_MUSCLE
        ]
        names = {a.component_name for a in atrophied_anomalies}
        assert "StatusDeprecated" in names

    def test_atrophied_includes_call_details(
        self,
        collector: MetricsCollector,
        registry_with_deprecated: ComponentRegistry,
    ) -> None:
        """Atrophied anomaly includes call count and last call time."""
        auditor = CoverageAuditor(metrics_collector=collector)
        result = auditor.verify(registry_with_deprecated)
        atrophied_anomalies = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.ATROPHIED_MUSCLE
            and a.component_name == "DeprecatedHandler"
        ]
        assert len(atrophied_anomalies) == 1
        details = atrophied_anomalies[0].details
        assert details["call_count"] == 2
        assert details["deprecated"] is True

    def test_non_deprecated_not_atrophied(
        self,
        collector: MetricsCollector,
        registry_with_deprecated: ComponentRegistry,
    ) -> None:
        """Non-deprecated component with calls is not atrophied."""
        # Record some calls for the active service
        collector.record_call("ActiveService", 1_000_000)
        auditor = CoverageAuditor(metrics_collector=collector)
        result = auditor.verify(registry_with_deprecated)
        atrophied_names = {
            a.component_name for a in result.anomalies
            if a.kind == AnomalyKind.ATROPHIED_MUSCLE
        }
        assert "ActiveService" not in atrophied_names


# ======================================================================
# Immune Response Status
# ======================================================================


class TestImmuneResponseStatus:
    """Test import hook (immune system) status reporting."""

    def test_immune_response_hook_not_installed(
        self, auditor: CoverageAuditor
    ) -> None:
        """When import hook is not installed, INFO anomaly reported."""
        reg = ComponentRegistry(persist=False)
        result = auditor.verify(reg)
        immune_anomalies = [
            a for a in result.anomalies
            if a.kind == AnomalyKind.IMMUNE_RESPONSE
        ]
        # Hook is not installed in tests, so we expect the INFO
        assert len(immune_anomalies) == 1
        assert immune_anomalies[0].severity == AnomalySeverity.INFO
        assert "not installed" in immune_anomalies[0].message


# ======================================================================
# Kounev & Spinner Automation Metric
# ======================================================================


class TestAutomationMetric:
    """Test the Kounev & Spinner automation percentage."""

    def test_automation_metric_empty_registry(
        self, auditor: CoverageAuditor
    ) -> None:
        """Empty registry reports zero evidence, not perfect automation."""
        reg = ComponentRegistry(persist=False)
        metric = auditor.get_automation_metric(reg)
        assert metric == 0.0

    def test_automation_metric_well_instrumented(
        self, auditor: CoverageAuditor
    ) -> None:
        """Component with module_path + contracts + profile scores high.

        Structural (6 auto / 6 total) + contracts (2 * 0.75 / 2 total)
        + profile (1 auto / 1 total) = 8.5 / 9 ≈ 94.4%
        """
        reg = ComponentRegistry(persist=False)
        reg.register(ComponentSpec(
            name="WellInstrumented",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A fully instrumented service with all metadata",
            contracts=Contract(
                preconditions=["input is valid"],
                postconditions=["returns result"],
            ),
            resource_profile=ResourceProfile(
                expected_latency_p50_ms=10.0,
            ),
            module_path="test.well",
            qualified_name="test.well.WellInstrumented",
        ))
        metric = auditor.get_automation_metric(reg)
        # High but not 100% because string contracts are 75% auto
        assert metric > 0.90
        assert metric < 1.0

    def test_automation_metric_structural_only(
        self, auditor: CoverageAuditor
    ) -> None:
        """Component with only structural data is 100% auto-verified.

        When no contracts or profiles are declared, all verifiable
        properties (structural checks) are fully automatic.
        """
        reg = ComponentRegistry(persist=False)
        reg.register(ComponentSpec(
            name="StructuralOnly",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A component with only structural metadata for testing",
            module_path="test.structural",
            qualified_name="test.structural.StructuralOnly",
        ))
        metric = auditor.get_automation_metric(reg)
        # No contracts or profiles → only structural checks → 100%
        assert metric == 1.0

    def test_automation_metric_in_result_details(
        self, auditor: CoverageAuditor
    ) -> None:
        """Automation metric is included in verification result details."""
        reg = ComponentRegistry(persist=False)
        reg.register(ComponentSpec(
            name="TestComp",
            kind=ComponentKind.SERVICE,
            layer=Layer.FRAMEWORK,
            intent="Test component for automation metric check",
            module_path="test.comp",
            qualified_name="test.comp.TestComp",
            is_framework=True,
        ))
        result = auditor.verify(reg)
        assert "automation_metric" in result.details
        assert isinstance(result.details["automation_metric"], float)

    def test_automation_metric_exceeds_target_on_s0ma(self) -> None:
        """When run against S0ma itself, metric exceeds 93%.

        Kounev & Spinner (2015) achieved 85.4% on legacy systems.
        S0ma significantly exceeds this because the self-model is built
        from inception — every component has structural data and most
        have declared contracts. The target is 93%+ (deliberately above
        the 85.4% baseline) and will fluctuate slightly as new string-
        contract components are added over time.
        """
        from s0ma import initialize

        registry = initialize(persist=False)
        auditor = CoverageAuditor()
        metric = auditor.get_automation_metric(registry)
        assert metric > 0.93, (
            f"Automation metric {metric:.1%} is below 93% target. "
            f"Framework components should be well-instrumented."
        )


# ======================================================================
# Verifier Protocol Compliance
# ======================================================================


class TestVerifierProtocol:
    """Test that CoverageAuditor follows the Verifier protocol."""

    def test_name_property(self) -> None:
        """Verifier has a human-readable name."""
        auditor = CoverageAuditor()
        assert auditor.name == "Coverage Auditor"

    def test_scope_property(self) -> None:
        """Verifier reports COVERAGE scope."""
        auditor = CoverageAuditor()
        assert auditor.scope == VerificationScope.COVERAGE

    def test_verify_returns_result(self) -> None:
        """verify() returns a VerificationResult."""
        auditor = CoverageAuditor()
        reg = ComponentRegistry(persist=False)
        result = auditor.verify(reg)
        assert result.verifier_name == "Coverage Auditor"
        assert result.scope == VerificationScope.COVERAGE

    def test_verify_incremental_returns_result(self) -> None:
        """verify_incremental() returns a VerificationResult."""
        auditor = CoverageAuditor()
        reg = ComponentRegistry(persist=False)
        reg.register(ComponentSpec(
            name="IncrTest",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="Test component for incremental verification",
            module_path="s0ma.models",
            qualified_name="s0ma.models.Anomaly",
        ))
        result = auditor.verify_incremental(reg, "IncrTest")
        assert result.components_checked == 1

    def test_verify_incremental_unregistered(self) -> None:
        """verify_incremental() catches unregistered component."""
        auditor = CoverageAuditor()
        reg = ComponentRegistry(persist=False)
        result = auditor.verify_incremental(reg, "NonExistent")
        assert not result.passed
        assert result.anomalies[0].kind == AnomalyKind.PHANTOM_LIMB


# ======================================================================
# Integration: handles no metrics gracefully
# ======================================================================


class TestGracefulDegradation:
    """Test auditor handles missing data gracefully."""

    def test_no_metrics_collector(self) -> None:
        """Auditor works when no MetricsCollector is available."""
        auditor = CoverageAuditor(metrics_collector=None)
        reg = ComponentRegistry(persist=False)
        result = auditor.verify(reg)
        assert result.verifier_name == "Coverage Auditor"

    def test_empty_registry(self, auditor: CoverageAuditor) -> None:
        """Auditor handles empty registry without error."""
        reg = ComponentRegistry(persist=False)
        result = auditor.verify(reg)
        assert result.components_checked == 0

    def test_pathology_counts_in_details(
        self,
        auditor: CoverageAuditor,
        registry_with_components: ComponentRegistry,
    ) -> None:
        """Result details include pathology counts by kind."""
        result = auditor.verify(registry_with_components)
        assert "pathology_counts" in result.details
        counts = result.details["pathology_counts"]
        assert isinstance(counts, dict)

    def test_full_audit_on_s0ma_no_errors(self) -> None:
        """Full coverage audit on S0ma itself produces no errors.

        The framework's own components should be well-formed with
        no phantom limbs or other ERROR-level pathologies.
        """
        from s0ma import initialize

        registry = initialize(persist=False)
        auditor = CoverageAuditor()
        result = auditor.verify(registry)
        errors = [
            a for a in result.anomalies
            if a.severity == AnomalySeverity.ERROR
        ]
        assert len(errors) == 0, (
            f"Coverage audit found {len(errors)} errors on S0ma: "
            + "; ".join(a.message for a in errors)
        )
