"""Tests for self-model text formatters.

Verifies that the formatter functions produce well-structured,
non-empty text output suitable for LLM consumption.
"""

from __future__ import annotations

import pytest

from s0ma.models import (
    Anomaly,
    ComponentSpec,
    Contract,
    ResourceProfile,
    VerificationReport,
    VerificationResult,
)
from s0ma.self_model.formatters import (
    format_component_detail,
    format_component_summary,
    format_contracts_text,
    format_dependency_graph_text,
    format_health_summary,
    format_layer_breakdown,
)
from s0ma.types import (
    AnomalyKind,
    AnomalySeverity,
    ComponentKind,
    Layer,
    VerificationScope,
)

# --- Fixtures ---


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
def simple_spec() -> ComponentSpec:
    return _make_spec()


@pytest.fixture
def detailed_spec() -> ComponentSpec:
    return _make_spec(
        name="PaymentProcessor",
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent="Processes customer payments through configured payment gateways",
        contracts=Contract(
            preconditions=["payment_request is valid"],
            postconditions=["returns PaymentResult"],
            invariants=["no side effects on failure"],
            max_latency_ms=500.0,
            error_rate_threshold=0.01,
        ),
        dependencies=["GatewayAdapter", "TransactionLog"],
        resource_profile=ResourceProfile(
            expected_memory_mb=128.0,
            expected_latency_p50_ms=100.0,
            expected_latency_p99_ms=450.0,
            expected_error_rate=0.005,
            expected_call_frequency_per_min=1000.0,
        ),
        version="2.1.0",
    )


@pytest.fixture
def framework_spec() -> ComponentSpec:
    return _make_spec(
        name="ComponentRegistry",
        kind=ComponentKind.FRAMEWORK,
        layer=Layer.FRAMEWORK,
        intent="Central registry storing all registered components",
        is_framework=True,
    )


# --- format_component_summary tests ---


class TestFormatComponentSummary:
    def test_produces_non_empty_output(self, simple_spec: ComponentSpec) -> None:
        result = format_component_summary(simple_spec)
        assert len(result) > 0

    def test_includes_name_and_kind(self, simple_spec: ComponentSpec) -> None:
        result = format_component_summary(simple_spec)
        assert "TestComponent" in result
        assert "service" in result

    def test_includes_intent(self, simple_spec: ComponentSpec) -> None:
        result = format_component_summary(simple_spec)
        assert "Intent:" in result
        assert "unit testing" in result

    def test_includes_dependencies(self, detailed_spec: ComponentSpec) -> None:
        result = format_component_summary(detailed_spec)
        assert "Dependencies:" in result
        assert "GatewayAdapter" in result

    def test_shows_non_default_version(self, detailed_spec: ComponentSpec) -> None:
        result = format_component_summary(detailed_spec)
        assert "2.1.0" in result

    def test_hides_default_version(self, simple_spec: ComponentSpec) -> None:
        result = format_component_summary(simple_spec)
        assert "0.1.0" not in result

    def test_marks_framework_component(self, framework_spec: ComponentSpec) -> None:
        result = format_component_summary(framework_spec)
        assert "framework component" in result.lower()


class TestFormatComponentDetail:
    def test_includes_all_sections(self, detailed_spec: ComponentSpec) -> None:
        result = format_component_detail(detailed_spec)
        assert "PaymentProcessor" in result
        assert "Purpose:" in result
        assert "Contracts:" in result
        assert "Dependencies" in result
        assert "Resource Profile:" in result

    def test_includes_resource_profile(self, detailed_spec: ComponentSpec) -> None:
        result = format_component_detail(detailed_spec)
        assert "128" in result  # memory
        assert "100" in result  # p50 latency

    def test_minimal_spec(self, simple_spec: ComponentSpec) -> None:
        result = format_component_detail(simple_spec)
        assert "TestComponent" in result
        assert "Purpose:" in result
        # Should not have resource profile or dependencies sections
        assert "Resource Profile:" not in result


# --- format_dependency_graph_text tests ---


class TestFormatDependencyGraphText:
    def test_empty_graph(self) -> None:
        result = format_dependency_graph_text({})
        assert "no dependency" in result.lower()

    def test_graph_with_no_dependencies(self) -> None:
        graph: dict[str, list[str]] = {"A": [], "B": []}
        result = format_dependency_graph_text(graph)
        assert "Independent" in result or "independent" in result.lower()
        assert "A" in result
        assert "B" in result

    def test_graph_with_dependencies(self) -> None:
        graph = {
            "PaymentProcessor": ["GatewayAdapter", "TransactionLog"],
            "GatewayAdapter": [],
            "TransactionLog": [],
        }
        result = format_dependency_graph_text(graph)
        assert "PaymentProcessor" in result
        assert "GatewayAdapter" in result
        assert "->" in result

    def test_complex_graph(self) -> None:
        graph = {
            "A": ["B", "C"],
            "B": ["D"],
            "C": ["D"],
            "D": [],
        }
        result = format_dependency_graph_text(graph)
        assert "A -> " in result
        assert "B -> " in result
        assert "C -> " in result
        assert "D" in result


# --- format_layer_breakdown tests ---


class TestFormatLayerBreakdown:
    def test_empty_components(self) -> None:
        result = format_layer_breakdown({})
        assert "no components" in result.lower()

    def test_groups_by_layer(self) -> None:
        components = {
            "A": _make_spec("A", layer=Layer.DOMAIN),
            "B": _make_spec("B", layer=Layer.FRAMEWORK),
        }
        result = format_layer_breakdown(components)
        assert "DOMAIN" in result
        assert "FRAMEWORK" in result

    def test_includes_component_names(self) -> None:
        components = {
            "PaymentProcessor": _make_spec(
                "PaymentProcessor", layer=Layer.DOMAIN
            ),
        }
        result = format_layer_breakdown(components)
        assert "PaymentProcessor" in result

    def test_includes_intents(self) -> None:
        components = {
            "A": _make_spec(
                "A",
                layer=Layer.DOMAIN,
                intent="Processes customer payments through gateways",
            ),
        }
        result = format_layer_breakdown(components)
        assert "Processes customer payments" in result

    def test_shows_component_count_per_layer(self) -> None:
        components = {
            "A": _make_spec("A", layer=Layer.DOMAIN),
            "B": _make_spec("B", layer=Layer.DOMAIN),
        }
        result = format_layer_breakdown(components)
        assert "2 components" in result


# --- format_health_summary tests ---


class TestFormatHealthSummary:
    def test_no_report(self) -> None:
        result = format_health_summary(None)
        assert "no verification" in result.lower()

    def test_healthy_report(self) -> None:
        report = VerificationReport(
            results=[
                VerificationResult(
                    verifier_name="StructuralVerifier",
                    scope=VerificationScope.STRUCTURAL,
                    anomalies=[],
                    components_checked=10,
                    checks_performed=50,
                    duration_ms=42.0,
                ),
            ],
            total_anomalies=0,
            total_errors=0,
            total_warnings=0,
            total_duration_ms=42.0,
        )
        result = format_health_summary(report)
        assert "HEALTHY" in result
        assert "No anomalies" in result

    def test_unhealthy_report(self) -> None:
        anomaly = Anomaly(
            kind=AnomalyKind.PHANTOM_LIMB,
            severity=AnomalySeverity.ERROR,
            component_name="Ghost",
            message="Registry entry has no corresponding code",
        )
        report = VerificationReport(
            results=[
                VerificationResult(
                    verifier_name="StructuralVerifier",
                    scope=VerificationScope.STRUCTURAL,
                    anomalies=[anomaly],
                    components_checked=10,
                    checks_performed=50,
                    duration_ms=42.0,
                ),
            ],
            total_anomalies=1,
            total_errors=1,
            total_warnings=0,
            total_duration_ms=42.0,
        )
        result = format_health_summary(report)
        assert "UNHEALTHY" in result
        assert "1" in result  # anomaly count

    def test_includes_erosion_coverage(self) -> None:
        report = VerificationReport(
            results=[
                VerificationResult(
                    verifier_name="StructuralVerifier",
                    scope=VerificationScope.STRUCTURAL,
                    details={
                        "erosion_coverage": {
                            "minimise_active": True,
                            "prevent_active": True,
                            "repair_active": True,
                            "minimise_coverage": 1.0,
                            "prevent_coverage": 0.95,
                            "repair_coverage": 0.90,
                        },
                    },
                ),
            ],
        )
        result = format_health_summary(report)
        assert "erosion" in result.lower() or "Erosion" in result

    def test_includes_automation_metric(self) -> None:
        report = VerificationReport(
            results=[
                VerificationResult(
                    verifier_name="CoverageAuditor",
                    scope=VerificationScope.COVERAGE,
                    details={"automation_metric": 0.95},
                ),
            ],
        )
        result = format_health_summary(report)
        assert "95%" in result or "automation" in result.lower()


# --- format_contracts_text tests ---


class TestFormatContractsText:
    def test_full_contract(self) -> None:
        contract = Contract(
            preconditions=["input is valid"],
            postconditions=["output is not None"],
            invariants=["state is consistent"],
            max_latency_ms=100.0,
            error_rate_threshold=0.05,
        )
        result = format_contracts_text(contract)
        assert "Preconditions:" in result
        assert "input is valid" in result
        assert "Postconditions:" in result
        assert "Invariants:" in result
        assert "100" in result  # latency
        assert "5" in result  # error rate percentage

    def test_minimal_contract(self) -> None:
        contract = Contract()
        result = format_contracts_text(contract)
        assert result == ""

    def test_partial_contract(self) -> None:
        contract = Contract(
            invariants=["thread-safe operations"],
        )
        result = format_contracts_text(contract)
        assert "Invariants:" in result
        assert "thread-safe" in result
        assert "Preconditions:" not in result

    def test_contract_with_configurable_properties(self) -> None:
        """format_contracts_text includes configurable properties when present."""
        from s0ma.models import ConfigurableProperty

        contract = Contract(
            preconditions=["user is authenticated"],
            configurable_properties={
                "theme_color": ConfigurableProperty(
                    type="str",
                    default="blue",
                    description="Primary theme color for UI",
                ),
                "max_items": ConfigurableProperty(
                    type="int",
                    default=10,
                    constraints={"min": 1, "max": 100},
                    description="Maximum items to display",
                ),
                "mode": ConfigurableProperty(
                    type="enum",
                    default="auto",
                    constraints={"allowed_values": ["light", "dark", "auto"]},
                ),
            },
        )
        result = format_contracts_text(contract)
        # Verify configurable properties section exists
        assert "Configurable Properties:" in result
        # Verify individual properties are listed
        assert "theme_color (str): default=blue" in result
        assert "Primary theme color" in result
        assert "max_items (int): default=10" in result
        assert "Maximum items to display" in result
        # Verify constraints are shown
        assert "range [1..100]" in result
        assert "mode (enum): default=auto" in result
        assert "values: light, dark, auto" in result

    def test_contract_without_configurable_properties(self) -> None:
        """format_contracts_text doesn't show configurable section when absent."""
        contract = Contract(
            preconditions=["input is valid"],
            postconditions=["output is valid"],
        )
        result = format_contracts_text(contract)
        # Should have normal contract content
        assert "Preconditions:" in result
        # But not configurable properties
        assert "Configurable Properties:" not in result


# --- format_component_detail: the operations a component provides ---


class TestFormatComponentDetailOperations:
    """The ``provides:`` list and its per-operation contracts reach the text."""

    @pytest.fixture
    def executor_spec(self) -> ComponentSpec:
        return _make_spec(
            name="CodeExecutor",
            kind=ComponentKind.SERVICE,
            layer=Layer.INFRASTRUCTURE,
            intent="Runs Python snippets and installs packages for the agent.",
            metadata={
                "provides": ["get_spec", "pip_install"],
                "provides_contracts": [
                    {"name": "get_spec", "returns": "list[ToolSpec]"},
                    {
                        "name": "pip_install",
                        "expects": "a wired run_shell",
                        "guarantees": "fails with the shell's reason when run_shell is off",
                        "returns": "ToolResult",
                    },
                ],
            },
        )

    def test_lists_every_operation_under_one_heading(
        self, executor_spec: ComponentSpec
    ) -> None:
        result = format_component_detail(executor_spec)
        assert "Operations (provides):" in result
        assert "  - get_spec" in result
        assert "  - pip_install" in result

    def test_prints_each_operation_contract_under_its_operation(
        self, executor_spec: ComponentSpec
    ) -> None:
        result = format_component_detail(executor_spec)
        pip = result.index("  - pip_install")
        assert result.index("Expects: a wired run_shell") > pip
        assert result.index(
            "Guarantees: fails with the shell's reason when run_shell is off"
        ) > pip
        assert result.index("Returns: ToolResult") > pip
        # get_spec authored only a return type; nothing is invented for it.
        get_spec = result.index("  - get_spec")
        assert "Expects" not in result[get_spec:pip]
        assert "Returns: list[ToolSpec]" in result[get_spec:pip]

    def test_flat_provides_list_prints_names_alone(self) -> None:
        spec = _make_spec(
            name="WebBrowser",
            kind=ComponentKind.SERVICE,
            layer=Layer.INFRASTRUCTURE,
            intent="Fetches pages and searches the web for the agent.",
            metadata={"provides": ["fetch_url", "web_search"]},
        )
        result = format_component_detail(spec)
        assert "Operations (provides):" in result
        assert "  - fetch_url" in result
        assert "Expects:" not in result

    def test_component_without_operations_has_no_heading(
        self, simple_spec: ComponentSpec
    ) -> None:
        assert "Operations" not in format_component_detail(simple_spec)
