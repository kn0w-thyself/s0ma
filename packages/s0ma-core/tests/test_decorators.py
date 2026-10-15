"""Comprehensive tests for the @component and @internal decorators.

Tests cover:
    - Basic class and function decoration
    - Auto-derived fields (module_path, qualified_name, source_file)
    - @internal decorator (bare and with reason)
    - Introspection utilities (is_component, is_internal, get_component_spec,
      get_all_components_in_module)
    - Edge cases: double decoration, name collisions, missing fields,
      non-callable targets
    - Entity identity preservation (no wrapping, no proxying)
    - Registry integration
"""

from __future__ import annotations

import types

import pytest

from s0ma.decorators import (
    component,
    get_all_components_in_module,
    get_component_spec,
    internal,
    is_component,
    is_internal,
)
from s0ma.exceptions import RegistrationError
from s0ma.models import ComponentSpec, Contract, ResourceProfile
from s0ma.registry import ComponentRegistry, get_registry, set_registry
from s0ma.types import ComponentKind, Layer


@pytest.fixture()
def decorator_registry() -> ComponentRegistry:
    """A fresh in-memory registry installed as the global singleton.

    The @component decorator registers into the global singleton, so tests
    that want to inspect registration results need the fixture registry
    to BE the global registry.
    """
    reg = ComponentRegistry(persist=False)
    set_registry(reg)
    return reg


# ======================================================================
# Helpers — define decorated entities inside tests to avoid polluting
# the module-level registry (the autouse fixture resets it each test)
# ======================================================================


class TestComponentDecoratorClass:
    """Tests for decorating classes with @component."""

    def test_class_is_registered(self, decorator_registry: ComponentRegistry) -> None:
        """A @component-decorated class appears in the registry."""

        @component(
            name="TestService",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A test service for decorator validation",
        )
        class TestService:
            pass

        assert decorator_registry.contains("TestService")

    def test_class_has_component_attribute(self) -> None:
        """A @component-decorated class has __component__ attached."""

        @component(
            name="AnnotatedClass",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="A class to verify __component__ attribute attachment",
        )
        class AnnotatedClass:
            pass

        assert hasattr(AnnotatedClass, "__component__")
        assert isinstance(AnnotatedClass.__component__, ComponentSpec)

    def test_class_spec_fields_are_correct(self) -> None:
        """The ComponentSpec attached to a class has correct field values."""
        contracts = Contract(
            preconditions=["input is valid"],
            postconditions=["returns result"],
            invariants=["no side effects on failure"],
            max_latency_ms=200.0,
        )

        @component(
            name="DetailedService",
            kind=ComponentKind.SERVICE,
            layer=Layer.APPLICATION,
            intent="Service with fully specified metadata for testing",
            contracts=contracts,
            dependencies=["SomeDep"],
            version="1.2.3",
            metadata={"team": "platform"},
        )
        class DetailedService:
            pass

        spec = DetailedService.__component__
        assert spec.name == "DetailedService"
        assert spec.kind == ComponentKind.SERVICE
        assert spec.layer == Layer.APPLICATION
        assert spec.intent == "Service with fully specified metadata for testing"
        assert spec.contracts == contracts
        assert spec.dependencies == ["SomeDep"]
        assert spec.version == "1.2.3"
        assert spec.metadata == {"team": "platform"}

    def test_class_identity_preserved(self) -> None:
        """The decorated class is the exact same object — no wrapping."""

        @component(
            name="IdentityClass",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="Verifies that the decorator preserves class identity",
        )
        class IdentityClass:
            pass

        # The class should still be usable normally
        instance = IdentityClass()
        assert isinstance(instance, IdentityClass)
        assert type(instance).__name__ == "IdentityClass"

    def test_class_isinstance_works(self) -> None:
        """isinstance() checks work correctly on decorated classes."""

        @component(
            name="BaseModel",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="Base class for testing isinstance preservation",
        )
        class BaseModel:
            pass

        class ChildModel(BaseModel):
            pass

        base_instance = BaseModel()
        child_instance = ChildModel()
        assert isinstance(base_instance, BaseModel)
        assert isinstance(child_instance, BaseModel)
        assert isinstance(child_instance, ChildModel)

    def test_class_methods_work(self) -> None:
        """Methods on a decorated class work normally."""

        @component(
            name="Calculator",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Simple calculator to verify method calls work after decoration",
        )
        class Calculator:
            def add(self, a: int, b: int) -> int:
                return a + b

        calc = Calculator()
        assert calc.add(2, 3) == 5

    def test_module_path_derived(self) -> None:
        """The module_path is correctly derived from the entity."""

        @component(
            name="ModPathClass",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="Verifies module_path derivation for decorated classes",
        )
        class ModPathClass:
            pass

        spec = ModPathClass.__component__
        assert spec.module_path == "tests.test_decorators"

    def test_qualified_name_derived(self) -> None:
        """The qualified_name is correctly derived from the entity."""

        @component(
            name="QualNameClass",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="Verifies qualified_name derivation for decorated classes",
        )
        class QualNameClass:
            pass

        spec = QualNameClass.__component__
        # qualified_name should include the enclosing test method
        assert "QualNameClass" in spec.qualified_name
        assert spec.qualified_name.startswith("tests.test_decorators.")

    def test_source_file_derived(self) -> None:
        """The source_file is derived and points to a real file."""

        @component(
            name="SourceFileClass",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="Verifies source_file derivation for decorated classes",
        )
        class SourceFileClass:
            pass

        spec = SourceFileClass.__component__
        assert spec.source_file is not None
        assert "test_decorators" in spec.source_file


class TestComponentDecoratorFunction:
    """Tests for decorating functions with @component."""

    def test_function_is_registered(self, decorator_registry: ComponentRegistry) -> None:
        """A @component-decorated function appears in the registry."""

        @component(
            name="calculate_tax",
            kind=ComponentKind.FUNCTION,
            layer=Layer.DOMAIN,
            intent="Calculates applicable tax for a given order by jurisdiction",
        )
        def calculate_tax(amount: float) -> float:
            return amount * 0.1

        assert decorator_registry.contains("calculate_tax")

    def test_function_has_component_attribute(self) -> None:
        """A @component-decorated function has __component__ attached."""

        @component(
            name="transform_data",
            kind=ComponentKind.FUNCTION,
            layer=Layer.DOMAIN,
            intent="Transforms raw data into a normalized form for processing",
        )
        def transform_data(raw: str) -> dict[str, str]:
            return {"data": raw}

        assert hasattr(transform_data, "__component__")
        assert isinstance(transform_data.__component__, ComponentSpec)

    def test_function_still_callable(self) -> None:
        """A decorated function still executes correctly."""

        @component(
            name="add_numbers",
            kind=ComponentKind.FUNCTION,
            layer=Layer.DOMAIN,
            intent="Adds two numbers together and returns the sum result",
        )
        def add_numbers(a: int, b: int) -> int:
            return a + b

        assert add_numbers(3, 4) == 7

    def test_function_module_path(self) -> None:
        """The module_path is correctly derived for functions."""

        @component(
            name="func_mod_path",
            kind=ComponentKind.FUNCTION,
            layer=Layer.DOMAIN,
            intent="Verifies module_path derivation for decorated functions",
        )
        def func_mod_path() -> None:
            pass

        spec = func_mod_path.__component__
        assert spec.module_path == "tests.test_decorators"

    def test_function_source_file(self) -> None:
        """The source_file is derived for functions."""

        @component(
            name="func_source",
            kind=ComponentKind.FUNCTION,
            layer=Layer.DOMAIN,
            intent="Verifies source_file derivation for decorated functions",
        )
        def func_source() -> None:
            pass

        spec = func_source.__component__
        assert spec.source_file is not None
        assert "test_decorators" in spec.source_file


class TestComponentWithResourceProfile:
    """Tests for @component with resource_profile."""

    def test_resource_profile_attached(self) -> None:
        """A resource profile is correctly stored in the spec."""
        profile = ResourceProfile(
            expected_memory_mb=128.0,
            expected_latency_p50_ms=50.0,
            expected_latency_p99_ms=200.0,
        )

        @component(
            name="ProfiledService",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Service with resource profile for interoception monitoring",
            resource_profile=profile,
        )
        class ProfiledService:
            pass

        spec = ProfiledService.__component__
        assert spec.resource_profile is not None
        assert spec.resource_profile.expected_memory_mb == 128.0
        assert spec.resource_profile.expected_latency_p50_ms == 50.0
        assert spec.resource_profile.expected_latency_p99_ms == 200.0


class TestComponentIsFramework:
    """Tests for the is_framework flag."""

    def test_default_is_not_framework(self) -> None:
        """Components are not framework components by default."""

        @component(
            name="UserComp",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A user-space component that is not part of the framework",
        )
        class UserComp:
            pass

        assert not UserComp.__component__.is_framework

    def test_framework_flag(self) -> None:
        """The is_framework flag is passed through to the spec."""

        @component(
            name="FrameworkComp",
            kind=ComponentKind.FRAMEWORK,
            layer=Layer.FRAMEWORK,
            intent="A framework component used for S0ma internals only",
            is_framework=True,
        )
        class FrameworkComp:
            pass

        assert FrameworkComp.__component__.is_framework


class TestInternalDecorator:
    """Tests for the @internal decorator."""

    def test_internal_bare_decorator(self) -> None:
        """@internal without arguments marks the entity as internal."""

        @internal
        def _helper() -> None:
            pass

        assert hasattr(_helper, "__s0ma_internal__")
        assert _helper.__s0ma_internal__ is True

    def test_internal_with_reason(self) -> None:
        """@internal(reason=...) marks the entity and stores the reason."""

        @internal(reason="Legacy helper scheduled for removal")
        def _old_helper() -> None:
            pass

        assert _old_helper.__s0ma_internal__ is True
        assert _old_helper.__s0ma_internal_reason__ == "Legacy helper scheduled for removal"

    def test_internal_not_in_registry(self, decorator_registry: ComponentRegistry) -> None:
        """@internal entities are NOT registered in the registry."""

        @internal
        def _private_helper() -> None:
            pass

        assert decorator_registry.count() == 0

    def test_internal_class(self) -> None:
        """@internal works on classes too."""

        @internal
        class _PrivateHelper:
            pass

        assert _PrivateHelper.__s0ma_internal__ is True

    def test_internal_function_still_callable(self) -> None:
        """An @internal function still works normally."""

        @internal
        def _parse_config(raw: str) -> dict[str, str]:
            return {"key": raw}

        assert _parse_config("value") == {"key": "value"}


class TestIntrospectionUtilities:
    """Tests for is_component, is_internal, get_component_spec,
    and get_all_components_in_module."""

    def test_is_component_true(self) -> None:
        """is_component returns True for @component entities."""

        @component(
            name="CheckableComp",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component to verify is_component introspection returns True",
        )
        class CheckableComp:
            pass

        assert is_component(CheckableComp) is True

    def test_is_component_false_plain(self) -> None:
        """is_component returns False for plain classes."""

        class PlainClass:
            pass

        assert is_component(PlainClass) is False

    def test_is_component_false_internal(self) -> None:
        """is_component returns False for @internal entities."""

        @internal
        class InternalClass:
            pass

        assert is_component(InternalClass) is False

    def test_is_component_false_primitives(self) -> None:
        """is_component returns False for primitives and None."""
        assert is_component(42) is False
        assert is_component("hello") is False
        assert is_component(None) is False

    def test_is_internal_true(self) -> None:
        """is_internal returns True for @internal entities."""

        @internal
        def _helper() -> None:
            pass

        assert is_internal(_helper) is True

    def test_is_internal_false_plain(self) -> None:
        """is_internal returns False for plain entities."""

        def plain_func() -> None:
            pass

        assert is_internal(plain_func) is False

    def test_is_internal_false_component(self) -> None:
        """is_internal returns False for @component entities."""

        @component(
            name="NotInternal",
            kind=ComponentKind.FUNCTION,
            layer=Layer.DOMAIN,
            intent="A component that should not be flagged as internal helper",
        )
        def not_internal() -> None:
            pass

        assert is_internal(not_internal) is False

    def test_get_component_spec_returns_spec(self) -> None:
        """get_component_spec returns the spec for decorated entities."""

        @component(
            name="SpecRetrievalTest",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="Tests that get_component_spec returns correct ComponentSpec",
        )
        class SpecRetrievalTest:
            pass

        spec = get_component_spec(SpecRetrievalTest)
        assert spec is not None
        assert spec.name == "SpecRetrievalTest"
        assert spec.kind == ComponentKind.MODEL

    def test_get_component_spec_returns_none(self) -> None:
        """get_component_spec returns None for undecorated entities."""

        class Undecorated:
            pass

        assert get_component_spec(Undecorated) is None

    def test_get_all_components_in_module(self) -> None:
        """get_all_components_in_module finds all decorated entities in a module."""
        # Create a mock module with decorated entities
        mod = types.ModuleType("fake_module")

        @component(
            name="ModCompA",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="First component in the test module for scanning test",
        )
        class CompA:
            pass

        @component(
            name="ModCompB",
            kind=ComponentKind.FUNCTION,
            layer=Layer.DOMAIN,
            intent="Second component in the test module for scanning test",
        )
        def comp_b() -> None:
            pass

        @internal
        def _helper() -> None:
            pass

        class PlainClass:
            pass

        mod.CompA = CompA  # type: ignore[attr-defined]
        mod.comp_b = comp_b  # type: ignore[attr-defined]
        mod._helper = _helper  # type: ignore[attr-defined]
        mod.PlainClass = PlainClass  # type: ignore[attr-defined]

        specs = get_all_components_in_module(mod)
        names = [s.name for s in specs]
        assert "ModCompA" in names
        assert "ModCompB" in names
        assert len(specs) == 2

    def test_get_all_components_sorted_by_name(self) -> None:
        """get_all_components_in_module returns specs sorted by name."""
        mod = types.ModuleType("sorted_module")

        @component(
            name="Zebra",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component with Z name for alphabetical sort test",
        )
        class Zebra:
            pass

        @component(
            name="Alpha",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component with A name for alphabetical sort test",
        )
        class Alpha:
            pass

        mod.Zebra = Zebra  # type: ignore[attr-defined]
        mod.Alpha = Alpha  # type: ignore[attr-defined]

        specs = get_all_components_in_module(mod)
        assert specs[0].name == "Alpha"
        assert specs[1].name == "Zebra"

    def test_get_all_components_empty_module(self) -> None:
        """get_all_components_in_module returns empty list for undecorated modules."""
        mod = types.ModuleType("empty_module")
        specs = get_all_components_in_module(mod)
        assert specs == []


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_double_decoration_raises(self) -> None:
        """Applying @component twice raises RegistrationError."""
        with pytest.raises(RegistrationError, match="already has a @component decorator"):

            @component(
                name="DoubleDec2",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Second decoration that should fail with error message",
            )
            @component(
                name="DoubleDec1",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="First decoration that should succeed without issues",
            )
            class DoubleDecorated:
                pass

    def test_duplicate_name_raises(self) -> None:
        """Registering two components with the same name raises RegistrationError."""

        @component(
            name="DuplicateName",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="First component with this name should register fine",
        )
        class First:
            pass

        with pytest.raises(RegistrationError, match="already registered"):

            @component(
                name="DuplicateName",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Second component with same name should fail to register",
            )
            class Second:
                pass

    def test_empty_name_raises(self) -> None:
        """Empty component name raises RegistrationError."""
        with pytest.raises(RegistrationError, match="must not be empty"):

            @component(
                name="",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="This should fail because the name is empty string",
            )
            class EmptyName:
                pass

    def test_short_intent_raises(self) -> None:
        """Intent shorter than 10 chars raises RegistrationError."""
        with pytest.raises(RegistrationError, match="at least 10 characters"):

            @component(
                name="ShortIntent",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Too short",
            )
            class ShortIntent:
                pass

    def test_whitespace_in_name_raises(self) -> None:
        """Whitespace in component name raises RegistrationError."""
        with pytest.raises(RegistrationError, match="whitespace"):

            @component(
                name="Bad Name",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="This should fail because name has a space in it",
            )
            class BadName:
                pass

    def test_self_dependency_raises(self) -> None:
        """Self-dependency raises RegistrationError."""
        with pytest.raises(RegistrationError, match="cannot depend on itself"):

            @component(
                name="SelfRef",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="This component incorrectly lists itself as dependency",
                dependencies=["SelfRef"],
            )
            class SelfRef:
                pass

    def test_invalid_contract_raises(self) -> None:
        """Invalid contract (negative latency) raises RegistrationError."""
        with pytest.raises(RegistrationError, match="max_latency_ms must be positive"):

            @component(
                name="BadContract",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Component with invalid contract that should be rejected",
                contracts=Contract(max_latency_ms=-100),
            )
            class BadContract:
                pass

    def test_component_with_invalid_configurable_properties_raises(self) -> None:
        """@component with invalid configurable_properties raises RegistrationError."""
        from s0ma.models import ConfigurableProperty

        # Test invalid type
        with pytest.raises(RegistrationError, match="type must be one of"):
            @component(
                name="BadConfigurableType",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Component with invalid configurable property type",
                contracts=Contract(
                    configurable_properties={
                        "bad_prop": ConfigurableProperty(type="invalid", default="value")
                    }
                ),
            )
            class BadConfigurableType:
                pass

        # Test type mismatch
        with pytest.raises(RegistrationError, match="type mismatch"):
            @component(
                name="BadConfigurableTypeMismatch",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Component with configurable property type mismatch",
                contracts=Contract(
                    configurable_properties={
                        "bad_prop": ConfigurableProperty(type="int", default="not_an_int")
                    }
                ),
            )
            class BadConfigurableTypeMismatch:
                pass

        # Test invalid numeric constraints
        with pytest.raises(RegistrationError, match="min.*must be less than max"):
            @component(
                name="BadNumericConstraints",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Component with invalid numeric constraints",
                contracts=Contract(
                    configurable_properties={
                        "bad_prop": ConfigurableProperty(
                            type="int",
                            default=5,
                            constraints={"min": 10, "max": 5}
                        )
                    }
                ),
            )
            class BadNumericConstraints:
                pass

        # Test invalid enum constraints
        with pytest.raises(RegistrationError, match="must have non-empty 'allowed_values'"):
            @component(
                name="BadEnumConstraints",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Component with invalid enum constraints",
                contracts=Contract(
                    configurable_properties={
                        "bad_enum": ConfigurableProperty(
                            type="enum",
                            default="red",
                            constraints={}
                        )
                    }
                ),
            )
            class BadEnumConstraints:
                pass


class TestRegistryIntegration:
    """Tests verifying the decorator correctly integrates with the registry."""

    def test_decorated_component_in_global_registry(self) -> None:
        """Decorated components appear in the global registry."""

        @component(
            name="GlobalRegistryComp",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Verifies that decoration registers in the global singleton",
        )
        class GlobalRegistryComp:
            pass

        reg = get_registry(persist=False)
        assert reg.contains("GlobalRegistryComp")
        retrieved = reg.get("GlobalRegistryComp")
        assert retrieved is not None
        assert retrieved.name == "GlobalRegistryComp"

    def test_spec_in_registry_matches_attribute(self) -> None:
        """The spec in the registry is the same object as __component__."""

        @component(
            name="SpecMatchTest",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Verifies registry spec is same object as the attribute",
        )
        class SpecMatchTest:
            pass

        reg = get_registry(persist=False)
        registry_spec = reg.get("SpecMatchTest")
        attribute_spec = SpecMatchTest.__component__
        assert registry_spec is attribute_spec

    def test_multiple_components_registered(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """Multiple decorated components all appear in the registry."""

        @component(
            name="MultiA",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="First of multiple components for multi-registration test",
        )
        class MultiA:
            pass

        @component(
            name="MultiB",
            kind=ComponentKind.FUNCTION,
            layer=Layer.APPLICATION,
            intent="Second of multiple components for multi-registration test",
        )
        def multi_b() -> None:
            pass

        @component(
            name="MultiC",
            kind=ComponentKind.MODEL,
            layer=Layer.INFRASTRUCTURE,
            intent="Third of multiple components for multi-registration test",
        )
        class MultiC:
            pass

        assert decorator_registry.count() == 3
        assert decorator_registry.contains("MultiA")
        assert decorator_registry.contains("MultiB")
        assert decorator_registry.contains("MultiC")

    def test_layer_query_after_decoration(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """query_by_layer works for decorated components."""

        @component(
            name="DomainComp",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Domain layer component for hierarchical query testing",
        )
        class DomainComp:
            pass

        @component(
            name="InfraComp",
            kind=ComponentKind.ADAPTER,
            layer=Layer.INFRASTRUCTURE,
            intent="Infrastructure layer component for hierarchical query testing",
        )
        class InfraComp:
            pass

        domain = decorator_registry.query_by_layer(Layer.DOMAIN)
        assert len(domain) == 1
        assert domain[0].name == "DomainComp"

        infra = decorator_registry.query_by_layer(Layer.INFRASTRUCTURE)
        assert len(infra) == 1
        assert infra[0].name == "InfraComp"

    def test_kind_query_after_decoration(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """query_by_kind works for decorated components."""

        @component(
            name="ServiceComp",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Service component for kind-based query verification test",
        )
        class ServiceComp:
            pass

        @component(
            name="ModelComp",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="Model component for kind-based query verification test",
        )
        class ModelComp:
            pass

        services = decorator_registry.query_by_kind(ComponentKind.SERVICE)
        assert len(services) == 1
        assert services[0].name == "ServiceComp"

    def test_snapshot_includes_decorated_components(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """Registry snapshot includes all decorated components."""

        @component(
            name="SnapshotComp",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component to verify it appears in registry snapshot output",
        )
        class SnapshotComp:
            pass

        snap = decorator_registry.snapshot()
        assert snap.component_count == 1
        assert "SnapshotComp" in snap.components
        description = snap.describe()
        assert "SnapshotComp" in description


class TestDefaultValues:
    """Tests that optional fields use correct defaults."""

    def test_default_contracts(self) -> None:
        """Default contracts is an empty Contract."""

        @component(
            name="DefaultContracts",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component with default contracts for default value testing",
        )
        class DefaultContracts:
            pass

        spec = DefaultContracts.__component__
        assert spec.contracts.preconditions == []
        assert spec.contracts.postconditions == []
        assert spec.contracts.invariants == []
        assert spec.contracts.max_latency_ms is None

    def test_default_dependencies(self) -> None:
        """Default dependencies is an empty list."""

        @component(
            name="DefaultDeps",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component with no declared dependencies for default test",
        )
        class DefaultDeps:
            pass

        assert DefaultDeps.__component__.dependencies == []

    def test_default_version(self) -> None:
        """Default version is '0.1.0'."""

        @component(
            name="DefaultVersion",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component with default version string for testing defaults",
        )
        class DefaultVersion:
            pass

        assert DefaultVersion.__component__.version == "0.1.0"

    def test_default_resource_profile(self) -> None:
        """Default resource_profile is None."""

        @component(
            name="DefaultProfile",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component with no resource profile for default value test",
        )
        class DefaultProfile:
            pass

        assert DefaultProfile.__component__.resource_profile is None

    def test_default_metadata(self) -> None:
        """Default metadata is an empty dict."""

        @component(
            name="DefaultMeta",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component with default empty metadata for testing defaults",
        )
        class DefaultMeta:
            pass

        assert DefaultMeta.__component__.metadata == {}

    def test_default_is_framework_false(self) -> None:
        """Default is_framework is False."""

        @component(
            name="DefaultFramework",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component with default is_framework flag for testing defaults",
        )
        class DefaultFramework:
            pass

        assert DefaultFramework.__component__.is_framework is False


class TestABCInheritanceHandling:
    """Tests for @component handling of ABC inheritance and direct-vs-inherited __component__."""

    def test_component_on_subclass_of_component_abc_succeeds(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """@component on a subclass of a @component-decorated ABC registers both."""
        import abc

        @component(
            name="ABC_AbstractBase",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Abstract base class decorated with component for inheritance test",
        )
        class AbstractBase(abc.ABC):
            @abc.abstractmethod
            def process(self) -> str: ...

        @component(
            name="ABC_ConcreteImpl",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Concrete implementation of abstract base for inheritance test",
        )
        class ConcreteImpl(AbstractBase):
            def process(self) -> str:
                return "processed"

        assert decorator_registry.contains("ABC_AbstractBase")
        assert decorator_registry.contains("ABC_ConcreteImpl")

    def test_component_on_subclass_has_own_spec(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """A @component-decorated subclass holds its own spec, not the parent's."""
        import abc

        @component(
            name="ABC_Parent",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Parent component for own-spec inheritance validation test",
        )
        class ParentComponent(abc.ABC):
            @abc.abstractmethod
            def contract(self) -> str: ...

        @component(
            name="ABC_Child",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Child component establishing its own independent spec entry",
        )
        class ChildComponent(ParentComponent):
            def contract(self) -> str:
                return "child"

        assert ChildComponent.__component__.name == "ABC_Child"
        assert ParentComponent.__component__.name == "ABC_Parent"
        # Each has its own spec in its own __dict__
        assert "__component__" in ChildComponent.__dict__
        assert "__component__" in ParentComponent.__dict__

    def test_undecorated_subclass_inherits_but_can_be_independently_decorated(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """An undecorated subclass inheriting __component__ can receive @component."""

        @component(
            name="ABC_InheritBase",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Base class whose __component__ would be inherited by plain subclass",
        )
        class InheritBase:
            pass

        # Plain subclass inherits __component__ via hasattr, but not in its own __dict__
        class PlainSubclass(InheritBase):
            pass

        assert hasattr(PlainSubclass, "__component__")
        assert "__component__" not in PlainSubclass.__dict__

        # Applying @component to this subclass must now succeed
        @component(
            name="ABC_DecoratedSubclass",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Decorated subclass establishing its own registration independently",
        )
        class DecoratedSubclass(InheritBase):
            pass

        assert decorator_registry.contains("ABC_DecoratedSubclass")
        assert "__component__" in DecoratedSubclass.__dict__
        assert DecoratedSubclass.__component__.name == "ABC_DecoratedSubclass"

    def test_double_decoration_same_class_still_raises(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """Double @component on the exact same class still raises RegistrationError."""
        with pytest.raises(RegistrationError, match="already has a @component decorator"):

            @component(
                name="ABC_DoubleDec_Outer",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Outer decoration on an already-decorated class should fail",
            )
            @component(
                name="ABC_DoubleDec_Inner",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Inner decoration that registers first before the outer fails",
            )
            class DoubleDecorated:
                pass

    def test_double_decoration_error_mentions_inheritance(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """The duplicate-decoration error message mentions inherited parent class."""
        with pytest.raises(RegistrationError, match="inherited from a parent class"):

            @component(
                name="ABC_InheritHint_Outer",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Outer decoration whose error should contain the inheritance hint",
            )
            @component(
                name="ABC_InheritHint_Inner",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="Inner decoration that succeeds before triggering the error",
            )
            class DoubleDecorated2:
                pass

    def test_internal_on_abc_component_on_subclass_is_recommended_pattern(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """@internal on ABC + @component on concrete subclass is the recommended pattern."""
        import abc

        @internal
        class InternalABC(abc.ABC):
            @abc.abstractmethod
            def execute(self) -> str: ...

        @component(
            name="ABC_ConcreteFromInternal",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Concrete subclass of an internal ABC following recommended pattern",
        )
        class ConcreteFromInternal(InternalABC):
            def execute(self) -> str:
                return "executed"

        # ABC is not registered (it's @internal)
        assert not decorator_registry.contains("InternalABC")
        # Concrete implementation is registered
        assert decorator_registry.contains("ABC_ConcreteFromInternal")


# ===========================================================================
# Idempotent Decorator Tests
# ===========================================================================

class TestIdempotentDecorator:
    """Tests for @component(..., idempotent=True)."""

    def test_idempotent_true_allows_reload_from_same_source(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """@component(idempotent=True) succeeds on re-decoration from same source file."""

        @component(
            name="Idempotent_ReloadTarget",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component that will be re-decorated to simulate a module reload",
            idempotent=True,
        )
        class ReloadTarget:
            pass

        assert decorator_registry.contains("Idempotent_ReloadTarget")

        # Simulate a second decoration pass (same source file, idempotent=True)
        # Build a spec with the same source_file as the entity above
        import inspect
        source_file = inspect.getfile(ReloadTarget)

        spec = ComponentSpec(
            name="Idempotent_ReloadTarget",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Re-registered component from the same source file",
            module_path=ReloadTarget.__module__,
            qualified_name=f"{ReloadTarget.__module__}.{ReloadTarget.__qualname__}",
            source_file=source_file,
        )
        # idempotent=True on the registry call should not raise
        decorator_registry.register(spec, idempotent=True)
        assert decorator_registry.count() == 1

    def test_idempotent_false_default_behavior_unchanged(
        self, decorator_registry: ComponentRegistry
    ) -> None:
        """@component without idempotent=True uses default behavior (raises on dup)."""

        @component(
            name="Idempotent_DefaultBehavior",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Component registered with default (non-idempotent) behavior",
        )
        class DefaultBehaviorComp:
            pass

        assert decorator_registry.contains("Idempotent_DefaultBehavior")
        # Registering again without idempotent=True should raise
        with pytest.raises(RegistrationError, match="already registered"):
            decorator_registry.register(
                ComponentSpec(
                    name="Idempotent_DefaultBehavior",
                    kind=ComponentKind.SERVICE,
                    layer=Layer.DOMAIN,
                    intent="Duplicate without idempotent should raise",
                    module_path="tests",
                    qualified_name="tests.DefaultBehaviorComp",
                )
            )
