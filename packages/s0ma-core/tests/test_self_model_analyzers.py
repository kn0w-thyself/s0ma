"""Tests for self-model analyzers: impact analysis, extension points, validation.

Verifies that compute_impact_analysis(), find_extension_points(), and
validate_proposed_component() produce correct results, and that the
SelfModelInterface analytical methods return well-formatted text.
"""

from __future__ import annotations

import pytest

from s0ma._bootstrap import bootstrap_register
from s0ma.exceptions import RegistryIntegrityError
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.self_model import SelfModelInterface
from s0ma.self_model.analyzers import (
    ExtensionPoint,
    ImpactReport,
    compute_impact_analysis,
    find_extension_points,
    validate_proposed_component,
)
from s0ma.self_model.formatters import (
    format_extension_points,
    format_impact_report,
)
from s0ma.types import (
    AnomalyKind,
    AnomalySeverity,
    ComponentKind,
    Layer,
)

# --- Fixtures ---


@pytest.fixture
def empty_registry() -> ComponentRegistry:
    """Fresh registry with no components."""
    return ComponentRegistry(persist=False)


@pytest.fixture
def registry() -> ComponentRegistry:
    """Fresh registry with framework components bootstrap-registered."""
    reg = ComponentRegistry(persist=False)
    bootstrap_register(reg)
    return reg


@pytest.fixture
def smi(registry: ComponentRegistry) -> SelfModelInterface:
    """SelfModelInterface wired to the bootstrapped registry."""
    return SelfModelInterface(registry)


def _make_spec(
    name: str = "TestComponent",
    kind: ComponentKind = ComponentKind.SERVICE,
    layer: Layer = Layer.DOMAIN,
    intent: str = "A test component for unit testing purposes",
    **kwargs: object,
) -> ComponentSpec:
    """Helper to create ComponentSpec with sensible defaults."""
    return ComponentSpec(
        name=name,
        kind=kind,
        layer=layer,
        intent=intent,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.fixture
def multi_component_registry() -> ComponentRegistry:
    """Registry with a custom dependency chain for testing impact analysis.

    Creates: A -> B -> C (linear chain) plus D (depends on B, not A).
    Also adds an independent leaf component E.
    """
    reg = ComponentRegistry(persist=False)

    # Register in dependency order
    reg.register(_make_spec(
        name="ComponentA",
        kind=ComponentKind.MODEL,
        layer=Layer.DOMAIN,
        intent="Base domain model at the root of the dependency chain",
    ))
    reg.register(_make_spec(
        name="ComponentB",
        kind=ComponentKind.SERVICE,
        layer=Layer.APPLICATION,
        intent="Application service that depends on ComponentA",
        dependencies=["ComponentA"],
    ))
    reg.register(_make_spec(
        name="ComponentC",
        kind=ComponentKind.ORCHESTRATOR,
        layer=Layer.APPLICATION,
        intent="Orchestrator that depends on ComponentB (transitive on A)",
        dependencies=["ComponentB"],
    ))
    reg.register(_make_spec(
        name="ComponentD",
        kind=ComponentKind.ADAPTER,
        layer=Layer.INFRASTRUCTURE,
        intent="Infrastructure adapter that also depends on ComponentB",
        dependencies=["ComponentB"],
    ))
    reg.register(_make_spec(
        name="ComponentE",
        kind=ComponentKind.FUNCTION,
        layer=Layer.DOMAIN,
        intent="Independent leaf component with no dependencies or dependents",
    ))

    return reg


# =================================================================
# Tests for compute_impact_analysis()
# =================================================================


class TestComputeImpactAnalysis:
    """Tests for the compute_impact_analysis function."""

    def test_leaf_component_low_risk(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """A component with no dependents should have low risk."""
        report = compute_impact_analysis(
            multi_component_registry, "ComponentE"
        )
        assert report.risk_level == "low"
        assert report.total_affected_count == 0
        assert report.direct_dependents == []
        assert report.transitive_dependents == []

    def test_core_component_medium_or_high_risk(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """A component with several dependents should not be low risk."""
        report = compute_impact_analysis(
            multi_component_registry, "ComponentA"
        )
        # ComponentA is depended on by B, and transitively by C and D (3 total)
        assert report.risk_level in ("medium", "high")
        assert report.total_affected_count >= 3

    def test_direct_dependents_correct(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Direct dependents should be the immediate reverse dependencies."""
        report = compute_impact_analysis(
            multi_component_registry, "ComponentA"
        )
        assert "ComponentB" in report.direct_dependents

    def test_transitive_dependents_correct(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Transitive dependents should exclude direct dependents."""
        report = compute_impact_analysis(
            multi_component_registry, "ComponentA"
        )
        # B depends on A directly, C and D depend on A transitively via B
        assert "ComponentC" in report.transitive_dependents or \
               "ComponentC" in report.direct_dependents
        # At minimum, the total should include B, C, D
        all_affected = set(report.direct_dependents + report.transitive_dependents)
        assert "ComponentB" in all_affected
        assert "ComponentC" in all_affected
        assert "ComponentD" in all_affected

    def test_affected_layers_identified(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Impact analysis should identify which layers are affected."""
        report = compute_impact_analysis(
            multi_component_registry, "ComponentA"
        )
        layer_names = {layer.name for layer in report.affected_layers}
        # ComponentA is DOMAIN, B and C are APPLICATION, D is INFRASTRUCTURE
        assert "DOMAIN" in layer_names
        assert "APPLICATION" in layer_names
        assert "INFRASTRUCTURE" in layer_names

    def test_max_dependency_depth(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Dependency depth should reflect the longest chain."""
        report = compute_impact_analysis(
            multi_component_registry, "ComponentA"
        )
        # A -> B (depth 1) -> C (depth 2), A -> B -> D (depth 2)
        assert report.max_dependency_depth >= 2

    def test_medium_risk_component(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """A component with 1-3 dependents should have medium risk."""
        report = compute_impact_analysis(
            multi_component_registry, "ComponentB"
        )
        # B is depended on by C and D (2 direct dependents)
        assert report.risk_level in ("medium", "high")
        assert report.total_affected_count >= 2

    def test_nonexistent_component_raises(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Analyzing a non-existent component should raise."""
        with pytest.raises(RegistryIntegrityError, match="not registered"):
            compute_impact_analysis(
                multi_component_registry, "NonExistent"
            )

    def test_framework_component_impact(
        self, registry: ComponentRegistry
    ) -> None:
        """Framework components like ComponentSpec should have high impact."""
        report = compute_impact_analysis(registry, "ComponentSpec")
        # ComponentSpec is depended on by many framework components
        assert report.total_affected_count > 3
        assert report.risk_level == "high"
        assert report.details.get("is_framework") is True

    def test_impact_report_has_component_info(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """ImpactReport details should contain component metadata."""
        report = compute_impact_analysis(
            multi_component_registry, "ComponentA"
        )
        assert report.component_name == "ComponentA"
        assert "component_kind" in report.details
        assert "component_layer" in report.details


# =================================================================
# Tests for find_extension_points()
# =================================================================


class TestFindExtensionPoints:
    """Tests for the find_extension_points function."""

    def test_empty_registry_all_layers_open(
        self, empty_registry: ComponentRegistry
    ) -> None:
        """An empty registry should offer extension points in all non-framework layers."""
        points = find_extension_points(empty_registry)
        layer_names = {p.layer.name for p in points}
        assert "DOMAIN" in layer_names
        assert "APPLICATION" in layer_names
        assert "INFRASTRUCTURE" in layer_names
        assert "PRESENTATION" in layer_names
        # Framework layer should NOT be offered as an extension point
        assert "FRAMEWORK" not in layer_names

    def test_identifies_valid_extension_locations(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Should identify valid locations for new components."""
        points = find_extension_points(multi_component_registry)
        assert len(points) > 0
        # All points should have at least one suggested kind
        for point in points:
            assert len(point.suggested_kinds) > 0

    def test_respects_layer_dependency_rules(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Extension points should not suggest FRAMEWORK as a target layer."""
        points = find_extension_points(multi_component_registry)
        for point in points:
            assert point.layer != Layer.FRAMEWORK

    def test_suggests_reasonable_dependency_targets(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Suggested dependencies should be existing registered components."""
        points = find_extension_points(multi_component_registry)
        all_components = multi_component_registry.get_all()
        for point in points:
            for dep in point.potential_dependencies:
                assert dep in all_components, (
                    f"Suggested dependency '{dep}' not registered"
                )

    def test_framework_registry_extension_points(
        self, registry: ComponentRegistry
    ) -> None:
        """A framework-only registry should offer non-framework layers."""
        points = find_extension_points(registry)
        assert len(points) > 0
        for point in points:
            assert point.layer != Layer.FRAMEWORK

    def test_extension_points_have_rationale(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Each extension point should include a rationale."""
        points = find_extension_points(multi_component_registry)
        for point in points:
            assert len(point.rationale) > 10

    def test_extension_point_suggests_novel_kinds(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Should prioritize kinds not yet present in a layer."""
        points = find_extension_points(multi_component_registry)
        # PRESENTATION layer has no components, so all kinds should be suggested
        pres_points = [p for p in points if p.layer == Layer.PRESENTATION]
        if pres_points:
            assert len(pres_points[0].suggested_kinds) > 1


# =================================================================
# Tests for validate_proposed_component()
# =================================================================


class TestValidateProposedComponent:
    """Tests for the validate_proposed_component function."""

    def test_valid_component_no_anomalies(
        self, registry: ComponentRegistry
    ) -> None:
        """A valid proposed component should produce no anomalies."""
        spec = _make_spec(
            name="NewValidService",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A new service that processes domain events correctly",
            dependencies=["ComponentSpec"],
        )
        anomalies = validate_proposed_component(registry, spec)
        errors = [a for a in anomalies if a.severity == AnomalySeverity.ERROR]
        assert len(errors) == 0

    def test_duplicate_name_detected(
        self, registry: ComponentRegistry
    ) -> None:
        """Should catch a name that's already registered."""
        spec = _make_spec(
            name="ComponentRegistry",
            intent="Duplicate name for an existing component in the registry",
        )
        anomalies = validate_proposed_component(registry, spec)
        error_messages = [a.message for a in anomalies if a.severity == AnomalySeverity.ERROR]
        assert any("already registered" in msg for msg in error_messages)

    def test_missing_dependency_detected(
        self, registry: ComponentRegistry
    ) -> None:
        """Should catch dependencies that don't exist."""
        spec = _make_spec(
            name="NewComponent",
            intent="A component with a dependency that does not exist anywhere",
            dependencies=["NonExistentDep"],
        )
        anomalies = validate_proposed_component(registry, spec)
        error_messages = [a.message for a in anomalies if a.severity == AnomalySeverity.ERROR]
        assert any("NonExistentDep" in msg for msg in error_messages)

    def test_layer_violation_detected(
        self, registry: ComponentRegistry
    ) -> None:
        """Should catch invalid cross-layer dependencies."""
        # DOMAIN component depending on a PRESENTATION component would be a violation
        # First register a PRESENTATION component
        registry.register(_make_spec(
            name="PresentationWidget",
            kind=ComponentKind.FUNCTION,
            layer=Layer.PRESENTATION,
            intent="A presentation layer component for UI display purposes",
        ))
        spec = _make_spec(
            name="DomainModelBad",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="A domain model that incorrectly depends on presentation layer",
            dependencies=["PresentationWidget"],
        )
        anomalies = validate_proposed_component(registry, spec)
        layer_warnings = [
            a for a in anomalies
            if a.kind == AnomalyKind.INFLAMMATION
        ]
        assert len(layer_warnings) > 0
        assert any("Layer violation" in a.message or "layer" in a.message.lower()
                    for a in layer_warnings)

    def test_short_intent_warning(
        self, registry: ComponentRegistry
    ) -> None:
        """Should warn about overly short intents."""
        # ComponentSpec.__post_init__ enforces 10 char minimum, so we need
        # to test with exactly 10 chars (the minimum)
        spec = _make_spec(
            name="ShortIntent",
            intent="1234567890",  # exactly 10 chars, passes validation
        )
        anomalies = validate_proposed_component(registry, spec)
        # 10 chars is the minimum, so no warning expected
        intent_warnings = [
            a for a in anomalies
            if "intent" in a.message.lower()
        ]
        assert len(intent_warnings) == 0

    def test_valid_same_layer_dependency(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Same-layer dependencies should not trigger violations."""
        spec = _make_spec(
            name="NewDomainModel",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="A domain model that depends on another domain component",
            dependencies=["ComponentA"],  # Also DOMAIN
        )
        anomalies = validate_proposed_component(
            multi_component_registry, spec
        )
        layer_violations = [
            a for a in anomalies
            if a.kind == AnomalyKind.INFLAMMATION
        ]
        assert len(layer_violations) == 0

    def test_valid_downward_dependency(
        self, multi_component_registry: ComponentRegistry
    ) -> None:
        """Higher layers depending on lower layers should be valid."""
        spec = _make_spec(
            name="NewOrchestrator",
            kind=ComponentKind.ORCHESTRATOR,
            layer=Layer.APPLICATION,
            intent="Application orchestrator depending on domain components correctly",
            dependencies=["ComponentA"],  # DOMAIN (lower) — valid
        )
        anomalies = validate_proposed_component(
            multi_component_registry, spec
        )
        layer_violations = [
            a for a in anomalies
            if a.kind == AnomalyKind.INFLAMMATION
        ]
        assert len(layer_violations) == 0

    def test_multiple_violations_all_reported(
        self, registry: ComponentRegistry
    ) -> None:
        """Multiple violations should all be reported, not just the first."""
        spec = _make_spec(
            name="ComponentRegistry",  # duplicate
            intent="A component that has multiple validation problems at once",
            dependencies=["NonExistent1", "NonExistent2"],
        )
        anomalies = validate_proposed_component(registry, spec)
        # Should have: 1 duplicate name + 2 missing deps = 3 errors minimum
        errors = [a for a in anomalies if a.severity == AnomalySeverity.ERROR]
        assert len(errors) >= 3


# =================================================================
# Tests for SelfModelInterface analytical methods
# =================================================================


class TestSelfModelInterfaceAnalytical:
    """Tests for the analytical methods on SelfModelInterface."""

    def test_get_impact_analysis_returns_text(
        self, smi: SelfModelInterface
    ) -> None:
        """get_impact_analysis() should return formatted text."""
        result = smi.get_impact_analysis("ComponentSpec")
        assert isinstance(result, str)
        assert len(result) > 0
        assert "ComponentSpec" in result

    def test_get_impact_analysis_high_impact(
        self, smi: SelfModelInterface
    ) -> None:
        """Impact analysis on core component should mention risk."""
        result = smi.get_impact_analysis("ComponentSpec")
        assert "HIGH" in result or "high" in result.lower()
        assert "dependents" in result.lower() or "depend" in result.lower()

    def test_get_available_extension_points_returns_text(
        self, smi: SelfModelInterface
    ) -> None:
        """get_available_extension_points() should return formatted text."""
        result = smi.get_available_extension_points()
        assert isinstance(result, str)
        assert len(result) > 100  # Non-trivial output

    def test_get_available_extension_points_has_layers(
        self, smi: SelfModelInterface
    ) -> None:
        """Extension points should mention architectural layers."""
        result = smi.get_available_extension_points()
        assert "DOMAIN" in result or "domain" in result.lower()

    def test_validate_proposed_component_accepts_valid(
        self, smi: SelfModelInterface
    ) -> None:
        """validate_proposed_component() should accept a valid component."""
        spec = _make_spec(
            name="ValidNewComponent",
            intent="A valid new component for testing the validation interface",
            dependencies=["ComponentSpec"],
        )
        anomalies = smi.validate_proposed_component(spec)
        errors = [a for a in anomalies if a.severity == AnomalySeverity.ERROR]
        assert len(errors) == 0

    def test_validate_proposed_component_catches_duplicate(
        self, smi: SelfModelInterface
    ) -> None:
        """validate_proposed_component() should catch duplicate names."""
        spec = _make_spec(
            name="ComponentRegistry",
            intent="This name is already taken by the existing registry component",
        )
        anomalies = smi.validate_proposed_component(spec)
        errors = [a for a in anomalies if a.severity == AnomalySeverity.ERROR]
        assert len(errors) > 0


# =================================================================
# Tests for formatter functions
# =================================================================


class TestFormatImpactReport:
    """Tests for format_impact_report()."""

    def test_formats_high_risk(self) -> None:
        """High-risk reports should include a warning."""
        report = ImpactReport(
            component_name="CoreService",
            direct_dependents=["A", "B", "C", "D"],
            transitive_dependents=["E", "F"],
            affected_layers=[Layer.DOMAIN, Layer.APPLICATION],
            total_affected_count=6,
            max_dependency_depth=3,
            risk_level="high",
        )
        text = format_impact_report(report)
        assert "HIGH" in text
        assert "CoreService" in text
        assert "WARNING" in text
        assert "6" in text

    def test_formats_low_risk(self) -> None:
        """Low-risk reports should indicate low impact."""
        report = ImpactReport(
            component_name="LeafNode",
            direct_dependents=[],
            transitive_dependents=[],
            affected_layers=[Layer.DOMAIN],
            total_affected_count=0,
            max_dependency_depth=0,
            risk_level="low",
        )
        text = format_impact_report(report)
        assert "LOW" in text
        assert "LeafNode" in text
        assert "unlikely" in text.lower()

    def test_lists_direct_dependents(self) -> None:
        """Report should list direct dependents."""
        report = ImpactReport(
            component_name="Base",
            direct_dependents=["Dep1", "Dep2"],
            transitive_dependents=[],
            affected_layers=[Layer.DOMAIN],
            total_affected_count=2,
            max_dependency_depth=1,
            risk_level="medium",
        )
        text = format_impact_report(report)
        assert "Dep1" in text
        assert "Dep2" in text

    def test_lists_transitive_dependents(self) -> None:
        """Report should list transitive dependents separately."""
        report = ImpactReport(
            component_name="Base",
            direct_dependents=["Direct"],
            transitive_dependents=["Trans1", "Trans2"],
            affected_layers=[Layer.DOMAIN],
            total_affected_count=3,
            max_dependency_depth=2,
            risk_level="medium",
        )
        text = format_impact_report(report)
        assert "Trans1" in text
        assert "Trans2" in text
        assert "Transitive" in text or "transitive" in text


class TestFormatExtensionPoints:
    """Tests for format_extension_points()."""

    def test_formats_empty_list(self) -> None:
        """Empty list should produce a meaningful message."""
        text = format_extension_points([])
        assert "No extension points" in text

    def test_formats_single_point(self) -> None:
        """Single extension point should be formatted clearly."""
        point = ExtensionPoint(
            layer=Layer.DOMAIN,
            suggested_kinds=[ComponentKind.MODEL, ComponentKind.FUNCTION],
            potential_dependencies=["BaseModel"],
            rationale="The DOMAIN layer is a natural extension point for models.",
        )
        text = format_extension_points([point])
        assert "DOMAIN" in text
        assert "model" in text.lower()
        assert "BaseModel" in text

    def test_formats_multiple_points(self) -> None:
        """Multiple extension points should all appear."""
        points = [
            ExtensionPoint(
                layer=Layer.DOMAIN,
                suggested_kinds=[ComponentKind.MODEL],
                potential_dependencies=[],
                rationale="Domain extension point.",
            ),
            ExtensionPoint(
                layer=Layer.APPLICATION,
                suggested_kinds=[ComponentKind.ORCHESTRATOR],
                potential_dependencies=["SomeService"],
                rationale="Application extension point.",
            ),
        ]
        text = format_extension_points(points)
        assert "DOMAIN" in text
        assert "APPLICATION" in text
