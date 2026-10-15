"""Tests for the SelfModelInterface core query methods.

Verifies that describe_system(), describe_component(), and
get_architecture_context() produce meaningful, LLM-ready text
output from a live registry populated with framework components.
"""

from __future__ import annotations

import pytest

from s0ma._bootstrap import bootstrap_register
from s0ma.exceptions import RegistryIntegrityError
from s0ma.models import ComponentSpec, Contract
from s0ma.registry import ComponentRegistry
from s0ma.self_model import SelfModelInterface
from s0ma.types import ComponentKind, Layer


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


@pytest.fixture
def registry_with_user_component(registry: ComponentRegistry) -> ComponentRegistry:
    """Registry with one additional user component."""
    registry.register(
        ComponentSpec(
            name="PaymentProcessor",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Processes customer payments through configured payment gateways",
            contracts=Contract(
                preconditions=["payment_request is valid"],
                postconditions=["returns PaymentResult"],
                invariants=["no side effects on failure"],
                max_latency_ms=500.0,
            ),
            dependencies=["ComponentRegistry"],
        )
    )
    return registry


# --- describe_system() tests ---


class TestDescribeSystem:
    def test_returns_non_empty_string(self, smi: SelfModelInterface) -> None:
        result = smi.describe_system()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_mentions_total_component_count(
        self, smi: SelfModelInterface, registry: ComponentRegistry
    ) -> None:
        result = smi.describe_system()
        count = registry.count()
        assert str(count) in result

    def test_groups_components_by_layer(self, smi: SelfModelInterface) -> None:
        result = smi.describe_system()
        # Framework components are all in the FRAMEWORK layer
        assert "FRAMEWORK" in result

    def test_includes_health_status(self, smi: SelfModelInterface) -> None:
        result = smi.describe_system()
        # Should have some health info (either HEALTHY or "No verification")
        assert (
            "HEALTHY" in result
            or "UNHEALTHY" in result
            or "No verification" in result
            or "Health status" in result
        )

    def test_includes_system_purpose(self, smi: SelfModelInterface) -> None:
        result = smi.describe_system()
        assert (
            "self-knowledge" in result.lower()
            or "proprioception" in result.lower()
            or "self-model" in result.lower()
        )

    def test_includes_architectural_patterns(self, smi: SelfModelInterface) -> None:
        result = smi.describe_system()
        assert "registration" in result.lower() or "load-bearing" in result.lower()

    def test_reflects_user_components(
        self, registry_with_user_component: ComponentRegistry
    ) -> None:
        smi = SelfModelInterface(registry_with_user_component)
        result = smi.describe_system()
        # Should mention the DOMAIN layer since we added a user component there
        assert "DOMAIN" in result

    def test_component_kind_breakdown(self, smi: SelfModelInterface) -> None:
        result = smi.describe_system()
        assert "framework" in result.lower()

    def test_shows_configurable_properties_count(
        self, registry: ComponentRegistry
    ) -> None:
        """describe_system() shows count when components have configurable properties."""
        from s0ma.models import ConfigurableProperty

        # Add a component with configurable properties
        registry.register(
            ComponentSpec(
                name="ConfigurableWidget",
                kind=ComponentKind.SERVICE,
                layer=Layer.PRESENTATION,
                intent="A widget with runtime-configurable options",
                contracts=Contract(
                    configurable_properties={
                        "theme": ConfigurableProperty(type="str", default="light"),
                        "max_items": ConfigurableProperty(type="int", default=10),
                    }
                ),
            )
        )

        smi = SelfModelInterface(registry)
        result = smi.describe_system()
        # Should mention components with configurable properties
        assert "runtime-configurable properties: 1" in result

    def test_no_configurable_properties_mention_when_none_exist(
        self, smi: SelfModelInterface
    ) -> None:
        """describe_system() doesn't show configurable count when zero."""
        result = smi.describe_system()
        # Framework components don't have configurable properties (yet)
        # So the count line should not appear
        assert "runtime-configurable properties:" not in result


# --- describe_component() tests ---


class TestDescribeComponent:
    def test_describes_registry(self, smi: SelfModelInterface) -> None:
        result = smi.describe_component("ComponentRegistry")
        assert isinstance(result, str)
        assert "ComponentRegistry" in result

    def test_includes_intent(self, smi: SelfModelInterface) -> None:
        result = smi.describe_component("ComponentRegistry")
        assert "registry" in result.lower() or "storing" in result.lower()

    def test_includes_contracts(self, smi: SelfModelInterface) -> None:
        result = smi.describe_component("ComponentRegistry")
        # ComponentRegistry has contracts with invariants
        assert "invariant" in result.lower() or "Invariants" in result

    def test_includes_dependencies(self, smi: SelfModelInterface) -> None:
        result = smi.describe_component("ComponentRegistry")
        # ComponentRegistry depends on ComponentSpec and RegistrySnapshot
        assert "ComponentSpec" in result or "Dependencies" in result

    def test_includes_dependents(self, smi: SelfModelInterface) -> None:
        result = smi.describe_component("ComponentSpec")
        # ComponentSpec is depended on by ComponentRegistry and others
        assert "Dependents" in result or "depend" in result.lower()

    def test_component_with_no_dependents(
        self, smi: SelfModelInterface
    ) -> None:
        # LifecycleManager has dependencies but may not have dependents
        # (only TransactionContext depends on it)
        result = smi.describe_component("TransactionContext")
        assert isinstance(result, str)
        assert "TransactionContext" in result

    def test_nonexistent_component_raises(self, smi: SelfModelInterface) -> None:
        with pytest.raises(RegistryIntegrityError, match="NonExistent"):
            smi.describe_component("NonExistent")

    def test_nonexistent_lists_registered(self, smi: SelfModelInterface) -> None:
        with pytest.raises(RegistryIntegrityError) as exc_info:
            smi.describe_component("NonExistent")
        # Error message should list registered components to help the caller
        assert "ComponentRegistry" in str(exc_info.value)

    def test_describes_user_component(
        self, registry_with_user_component: ComponentRegistry
    ) -> None:
        smi = SelfModelInterface(registry_with_user_component)
        result = smi.describe_component("PaymentProcessor")
        assert "PaymentProcessor" in result
        assert "payment" in result.lower()
        assert "Preconditions" in result or "precondition" in result.lower()


# --- get_architecture_context() tests ---


class TestGetArchitectureContext:
    def test_returns_non_empty_string(self, smi: SelfModelInterface) -> None:
        result = smi.get_architecture_context()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_is_comprehensive(self, smi: SelfModelInterface) -> None:
        result = smi.get_architecture_context()
        # For 28 framework components, should be substantial
        assert len(result) > 1000

    def test_includes_dependency_graph(self, smi: SelfModelInterface) -> None:
        result = smi.get_architecture_context()
        assert "Dependency" in result or "dependency" in result.lower()
        # Should show actual dependency arrows
        assert "->" in result

    def test_includes_verification_status(self, smi: SelfModelInterface) -> None:
        result = smi.get_architecture_context()
        assert (
            "Health" in result
            or "health" in result.lower()
            or "verification" in result.lower()
        )

    def test_includes_all_framework_components(
        self, smi: SelfModelInterface, registry: ComponentRegistry
    ) -> None:
        result = smi.get_architecture_context()
        # Check a sampling of key framework components appear
        assert "ComponentRegistry" in result
        assert "ComponentSpec" in result
        assert "StructuralVerifier" in result

    def test_produces_llm_suitable_text(self, smi: SelfModelInterface) -> None:
        result = smi.get_architecture_context()
        # Should not contain raw Python data structure literals
        assert "ComponentSpec(" not in result
        # Note: "dict(" is intentionally not checked here — the framework's
        # self-description legitimately references from_dict() / to_dict()
        # method names in postconditions (added in M5). The check is narrowed
        # to Python dict-constructor assignment patterns instead.
        assert "= dict(" not in result
        assert "<s0ma" not in result
        # Should have prose structure (headers, descriptions)
        assert "#" in result or ":" in result

    def test_includes_component_intents(self, smi: SelfModelInterface) -> None:
        result = smi.get_architecture_context()
        # Should include intents from component specs
        assert "Intent:" in result or "intent" in result.lower()

    def test_works_without_metrics_collector(
        self, registry: ComponentRegistry
    ) -> None:
        smi = SelfModelInterface(registry, metrics_collector=None)
        result = smi.get_architecture_context()
        assert isinstance(result, str)
        assert len(result) > 0


# --- describe_for_code_generation() tests ---


class TestDescribeForCodeGeneration:
    def test_returns_non_empty_string(self, smi: SelfModelInterface) -> None:
        result = smi.describe_for_code_generation("myapp")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_import_guidance(self, smi: SelfModelInterface) -> None:
        result = smi.describe_for_code_generation("myapp.services")
        assert "myapp.services" in result
        assert "Do not import from" in result

    def test_contains_layer_annotation(self, smi: SelfModelInterface) -> None:
        result = smi.describe_for_code_generation("myapp")
        assert "classification" in result.lower() or "label" in result.lower()
        assert "not" in result.lower()
        assert "package" in result.lower() or "director" in result.lower()

    def test_annotates_framework_components_as_non_importable(
        self, smi: SelfModelInterface
    ) -> None:
        result = smi.describe_for_code_generation("myapp")
        # Framework components should be grouped as platform-internal
        assert "platform internal" in result.lower()
        assert "not for import" in result.lower()
        # A known framework component should appear in that group
        assert "ComponentRegistry" in result

    def test_contains_component_decorator_template(
        self, smi: SelfModelInterface
    ) -> None:
        result = smi.describe_for_code_generation("myapp")
        # Should show a @component decorator template
        assert "@component" in result
        assert "ComponentKind" in result
        assert "Layer" in result
        assert "Contract" in result

    def test_decorator_template_uses_target_package(
        self, smi: SelfModelInterface
    ) -> None:
        result = smi.describe_for_code_generation("myapp.widgets")
        assert "myapp.widgets" in result

    def test_user_components_shown_with_import_path(
        self, registry_with_user_component: ComponentRegistry
    ) -> None:
        smi = SelfModelInterface(registry_with_user_component)
        result = smi.describe_for_code_generation("myapp")
        # User components should appear in Application Components section
        assert "PaymentProcessor" in result
        # Framework components in Platform section
        assert "platform internal" in result.lower()

    def test_includes_configurable_properties_when_present(
        self, registry: ComponentRegistry
    ) -> None:
        from s0ma.models import ConfigurableProperty

        registry.register(
            ComponentSpec(
                name="ThemedWidget",
                kind=ComponentKind.SERVICE,
                layer=Layer.PRESENTATION,
                intent="Widget with runtime-configurable theme",
                contracts=Contract(
                    configurable_properties={
                        "theme": ConfigurableProperty(
                            type="str",
                            default="light",
                            description="Color theme",
                        ),
                    }
                ),
            )
        )
        smi = SelfModelInterface(registry)
        result = smi.describe_for_code_generation("myapp")
        assert "theme" in result
        assert "light" in result

    def test_include_contracts_false_omits_contracts(
        self, registry_with_user_component: ComponentRegistry
    ) -> None:
        smi = SelfModelInterface(registry_with_user_component)
        result = smi.describe_for_code_generation(
            "myapp", include_contracts=False
        )
        # Preconditions should not appear when contracts are excluded
        assert "Preconditions" not in result

    def test_include_contracts_true_shows_contracts(
        self, registry_with_user_component: ComponentRegistry
    ) -> None:
        smi = SelfModelInterface(registry_with_user_component)
        result = smi.describe_for_code_generation(
            "myapp", include_contracts=True
        )
        # PaymentProcessor has preconditions
        assert "Preconditions" in result or "precondition" in result.lower()


# --- describe_for_agent() tests ---


class TestDescribeForAgent:
    def test_code_generation_delegates_to_describe_for_code_generation(
        self, smi: SelfModelInterface
    ) -> None:
        agent_result = smi.describe_for_agent(
            "code_generation", target_package="myapp"
        )
        direct_result = smi.describe_for_code_generation("myapp")
        assert agent_result == direct_result

    def test_code_generation_requires_target_package(
        self, smi: SelfModelInterface
    ) -> None:
        with pytest.raises(ValueError, match="target_package"):
            smi.describe_for_agent("code_generation")

    def test_architectural_review_delegates_to_get_architecture_context(
        self, smi: SelfModelInterface
    ) -> None:
        # Both calls invoke get_architecture_context(). Timing in the health
        # summary differs between calls, so we verify structural equivalence
        # rather than exact string equality.
        agent_result = smi.describe_for_agent("architectural_review")
        # Should contain the same key structural markers as get_architecture_context()
        assert "S0ma Architecture Context" in agent_result
        assert "Dependency Graph" in agent_result
        assert "Component Details" in agent_result

    def test_architectural_review_returns_architecture_context(
        self, smi: SelfModelInterface
    ) -> None:
        result = smi.describe_for_agent("architectural_review")
        # get_architecture_context() always includes these
        assert "ComponentRegistry" in result
        assert "Dependency" in result or "dependency" in result.lower()

    def test_debugging_returns_non_empty_string(
        self, smi: SelfModelInterface
    ) -> None:
        result = smi.describe_for_agent("debugging")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_debugging_includes_health_status(
        self, smi: SelfModelInterface
    ) -> None:
        result = smi.describe_for_agent("debugging")
        assert (
            "HEALTHY" in result
            or "UNHEALTHY" in result
            or "Health status" in result
        )

    def test_debugging_includes_dependency_graph(
        self, smi: SelfModelInterface
    ) -> None:
        result = smi.describe_for_agent("debugging")
        assert "Dependency" in result or "dependency" in result.lower()

    def test_unknown_context_raises_value_error(
        self, smi: SelfModelInterface
    ) -> None:
        with pytest.raises(ValueError, match="Unknown context"):
            smi.describe_for_agent("unknown_context")

    def test_unknown_context_lists_valid_options(
        self, smi: SelfModelInterface
    ) -> None:
        with pytest.raises(ValueError) as exc_info:
            smi.describe_for_agent("typo_context")
        error_msg = str(exc_info.value)
        assert "code_generation" in error_msg
        assert "architectural_review" in error_msg
        assert "debugging" in error_msg
