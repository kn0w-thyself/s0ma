"""Bootstrap self-registration and self-verification tests — Milestones 6 & 7.

Milestone 6 tests verify that S0ma can register its own components
using the bootstrap mechanism (direct ComponentSpec construction) and
that the initialize() function correctly sets up the framework.

Milestone 7 tests (TestSelfVerification, TestSelfDescriptionNarrative)
verify that the system can *accurately describe itself*. These are THE
tests — the north star of the entire project. If these fail, nothing
else matters.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from s0ma import initialize
from s0ma._bootstrap import EXPECTED_FRAMEWORK_COMPONENT_COUNT, bootstrap_register
from s0ma._verifier import verify_self_model
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry, get_registry, reset_registry
from s0ma.types import AnomalyKind, ComponentKind, Layer

# ======================================================================
# Helpers
# ======================================================================


def _get_initialized_registry() -> ComponentRegistry:
    """Create a fresh registry and run bootstrap registration."""
    registry = ComponentRegistry(persist=False)
    bootstrap_register(registry)
    return registry


# ======================================================================
# Test: bootstrap_register() basics
# ======================================================================


class TestBootstrapRegister:
    """Tests for the bootstrap_register() function."""

    def test_registers_expected_component_count(self) -> None:
        """bootstrap_register() registers exactly the expected number of components."""
        registry = _get_initialized_registry()
        assert registry.count() == EXPECTED_FRAMEWORK_COMPONENT_COUNT

    def test_all_components_are_framework(self) -> None:
        """Every bootstrap-registered component has is_framework=True."""
        registry = _get_initialized_registry()
        for name in registry:
            spec = registry.get(name)
            assert spec is not None
            assert spec.is_framework is True, (
                f"Component '{name}' should have is_framework=True"
            )

    def test_all_components_in_framework_layer(self) -> None:
        """Every bootstrap-registered component is in the FRAMEWORK layer."""
        registry = _get_initialized_registry()
        framework_components = registry.query_by_layer(Layer.FRAMEWORK)
        assert len(framework_components) == registry.count()

    def test_all_components_have_framework_kind(self) -> None:
        """Every bootstrap-registered component has FRAMEWORK kind."""
        registry = _get_initialized_registry()
        framework_kind = registry.query_by_kind(ComponentKind.FRAMEWORK)
        assert len(framework_kind) == registry.count()

    def test_all_components_have_nonempty_intent(self) -> None:
        """Every component has a meaningful intent (>10 characters)."""
        registry = _get_initialized_registry()
        for name in registry:
            spec = registry.get(name)
            assert spec is not None
            assert len(spec.intent) >= 10, (
                f"Component '{name}' has insufficient intent: '{spec.intent}'"
            )

    def test_idempotent_registration(self) -> None:
        """Calling bootstrap_register() twice does not duplicate components."""
        registry = ComponentRegistry(persist=False)
        bootstrap_register(registry)
        count_after_first = registry.count()
        bootstrap_register(registry)
        count_after_second = registry.count()
        assert count_after_first == count_after_second

    def test_does_not_overwrite_existing_registrations(self) -> None:
        """bootstrap_register() skips already-registered components."""
        registry = ComponentRegistry(persist=False)
        # Pre-register a component with the same name
        registry.register(
            ComponentSpec(
                name="ComponentSpec",
                kind=ComponentKind.FRAMEWORK,
                layer=Layer.FRAMEWORK,
                intent="Pre-existing registration that should not be overwritten",
                module_path="test.module",
                qualified_name="test.module.ComponentSpec",
                is_framework=True,
            )
        )
        bootstrap_register(registry)
        # The pre-existing registration should be preserved
        spec = registry.get("ComponentSpec")
        assert spec is not None
        assert spec.module_path == "test.module"


# ======================================================================
# Test: specific framework components are registered
# ======================================================================


class TestFrameworkComponentsPresent:
    """Verify that each expected framework component is registered."""

    EXPECTED_COMPONENTS = [
        "ComponentSpec",
        "Contract",
        "ResourceProfile",
        "Anomaly",
        "RegistrySnapshot",
        "ComponentRegistry",
        "ComponentDecorator",
        "InternalDecorator",
        "S0maFinder",
        "S0maLoader",
    ]

    @pytest.fixture()
    def bootstrap_registry(self) -> ComponentRegistry:
        return _get_initialized_registry()

    @pytest.mark.parametrize("component_name", EXPECTED_COMPONENTS)
    def test_component_is_registered(
        self, bootstrap_registry: ComponentRegistry, component_name: str
    ) -> None:
        """Each expected framework component is present in the registry."""
        assert bootstrap_registry.contains(component_name), (
            f"Framework component '{component_name}' is not registered"
        )

    @pytest.mark.parametrize("component_name", EXPECTED_COMPONENTS)
    def test_component_has_valid_spec(
        self, bootstrap_registry: ComponentRegistry, component_name: str
    ) -> None:
        """Each component's spec has all required fields populated."""
        spec = bootstrap_registry.get(component_name)
        assert spec is not None
        assert spec.name == component_name
        assert spec.kind == ComponentKind.FRAMEWORK
        assert spec.layer == Layer.FRAMEWORK
        assert len(spec.intent) >= 10
        assert spec.module_path.startswith("s0ma.")
        assert spec.qualified_name.startswith("s0ma.")
        assert spec.is_framework is True


# ======================================================================
# Test: source file accuracy
# ======================================================================


class TestSourceFileAccuracy:
    """Verify that registered source_file paths point to real files."""

    @pytest.fixture()
    def bootstrap_registry(self) -> ComponentRegistry:
        return _get_initialized_registry()

    def test_all_source_files_exist(self, bootstrap_registry: ComponentRegistry) -> None:
        """Every registered source_file points to a real file on disk."""
        for name in bootstrap_registry:
            spec = bootstrap_registry.get(name)
            assert spec is not None
            assert spec.source_file is not None, (
                f"Component '{name}' has no source_file"
            )
            path = Path(spec.source_file)
            assert path.exists(), (
                f"Component '{name}' source_file does not exist: {spec.source_file}"
            )
            assert path.is_file(), (
                f"Component '{name}' source_file is not a file: {spec.source_file}"
            )

    def test_source_files_are_in_s0ma_package(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """All source files are within the s0ma package directory."""
        for name in bootstrap_registry:
            spec = bootstrap_registry.get(name)
            assert spec is not None
            assert spec.source_file is not None
            # The source file path should contain 's0ma' as a directory
            assert "s0ma" in Path(spec.source_file).parts, (
                f"Component '{name}' source_file is outside s0ma: {spec.source_file}"
            )


# ======================================================================
# Test: module path accuracy
# ======================================================================


class TestModulePathAccuracy:
    """Verify that module_path and qualified_name fields are accurate."""

    @pytest.fixture()
    def bootstrap_registry(self) -> ComponentRegistry:
        return _get_initialized_registry()

    def test_module_paths_are_importable(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """Every module_path can be imported."""
        import importlib

        seen_modules: set[str] = set()
        for name in bootstrap_registry:
            spec = bootstrap_registry.get(name)
            assert spec is not None
            if spec.module_path not in seen_modules:
                mod = importlib.import_module(spec.module_path)
                assert mod is not None, (
                    f"Cannot import module '{spec.module_path}' "
                    f"for component '{name}'"
                )
                seen_modules.add(spec.module_path)

    def test_qualified_names_resolve_to_entities(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """Every qualified_name resolves to an actual code entity."""
        import importlib

        for name in bootstrap_registry:
            spec = bootstrap_registry.get(name)
            assert spec is not None
            # Parse "s0ma.module.EntityName" → module="s0ma.module", attr="EntityName"
            parts = spec.qualified_name.rsplit(".", 1)
            assert len(parts) == 2, (
                f"Component '{name}' has invalid qualified_name: {spec.qualified_name}"
            )
            module_path, attr_name = parts
            mod = importlib.import_module(module_path)
            assert hasattr(mod, attr_name), (
                f"Module '{module_path}' has no attribute '{attr_name}' "
                f"for component '{name}'"
            )

    def test_models_module_path(self, bootstrap_registry: ComponentRegistry) -> None:
        """Model components have correct module_path."""
        model_names = [
            "ComponentSpec", "Contract", "ResourceProfile", "Anomaly", "RegistrySnapshot",
        ]
        for name in model_names:
            spec = bootstrap_registry.get(name)
            assert spec is not None
            assert spec.module_path == "s0ma.models"

    def test_registry_module_path(self, bootstrap_registry: ComponentRegistry) -> None:
        """Registry component has correct module_path."""
        spec = bootstrap_registry.get("ComponentRegistry")
        assert spec is not None
        assert spec.module_path == "s0ma.registry"

    def test_decorators_module_path(self, bootstrap_registry: ComponentRegistry) -> None:
        """Decorator components have correct module_path."""
        for name in ("ComponentDecorator", "InternalDecorator"):
            spec = bootstrap_registry.get(name)
            assert spec is not None
            assert spec.module_path == "s0ma.decorators"

    def test_import_hook_module_path(self, bootstrap_registry: ComponentRegistry) -> None:
        """Import hook components have correct module_path."""
        for name in ("S0maFinder", "S0maLoader"):
            spec = bootstrap_registry.get(name)
            assert spec is not None
            assert spec.module_path == "s0ma.import_hook"


# ======================================================================
# Test: dependency graph
# ======================================================================


class TestDependencyGraph:
    """Verify the dependency relationships between framework components."""

    @pytest.fixture()
    def bootstrap_registry(self) -> ComponentRegistry:
        return _get_initialized_registry()

    def test_component_registry_dependencies(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """ComponentRegistry depends on ComponentSpec and RegistrySnapshot."""
        spec = bootstrap_registry.get("ComponentRegistry")
        assert spec is not None
        assert "ComponentSpec" in spec.dependencies
        assert "RegistrySnapshot" in spec.dependencies

    def test_component_decorator_dependencies(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """ComponentDecorator depends on ComponentRegistry and ComponentSpec."""
        spec = bootstrap_registry.get("ComponentDecorator")
        assert spec is not None
        assert "ComponentRegistry" in spec.dependencies
        assert "ComponentSpec" in spec.dependencies

    def test_s0ma_finder_dependencies(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """S0maFinder depends on S0maLoader."""
        spec = bootstrap_registry.get("S0maFinder")
        assert spec is not None
        assert "S0maLoader" in spec.dependencies

    def test_standalone_components_have_no_dependencies(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """Leaf components (models) have no declared dependencies."""
        standalone = [
            "ComponentSpec", "Contract", "ResourceProfile",
            "Anomaly", "RegistrySnapshot", "InternalDecorator", "S0maLoader",
        ]
        for name in standalone:
            spec = bootstrap_registry.get(name)
            assert spec is not None
            assert spec.dependencies == [], (
                f"Component '{name}' should have no dependencies, "
                f"but has: {spec.dependencies}"
            )

    def test_dependency_graph_is_complete(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """The dependency graph includes all registered components."""
        graph = bootstrap_registry.get_dependency_graph()
        for name in bootstrap_registry:
            assert name in graph


# ======================================================================
# Test: initialize() function
# ======================================================================


class TestInitialize:
    """Tests for the s0ma.initialize() function."""

    def test_initialize_returns_registry(self) -> None:
        """initialize() returns a ComponentRegistry."""
        registry = initialize(persist=False)
        assert isinstance(registry, ComponentRegistry)

    def test_initialize_registers_framework_components(self) -> None:
        """initialize() registers all framework components."""
        registry = initialize(persist=False)
        assert registry.count() == EXPECTED_FRAMEWORK_COMPONENT_COUNT

    def test_initialize_without_project_root(self) -> None:
        """initialize() without project_root does not install import hook."""
        from s0ma.import_hook import is_hook_installed

        registry = initialize(persist=False)
        assert not is_hook_installed()
        assert registry.count() >= EXPECTED_FRAMEWORK_COMPONENT_COUNT

    def test_initialize_with_project_root(self, tmp_path: Path) -> None:
        """initialize() with project_root installs the import hook."""
        from s0ma.import_hook import is_hook_installed, uninstall_import_hook

        try:
            registry = initialize(project_root=tmp_path, persist=False)
            assert is_hook_installed()
            assert registry.count() >= EXPECTED_FRAMEWORK_COMPONENT_COUNT
        finally:
            uninstall_import_hook()

    def test_initialize_idempotent(self) -> None:
        """Calling initialize() twice does not double-register."""
        registry1 = initialize(persist=False)
        count1 = registry1.count()
        registry2 = initialize(persist=False)
        count2 = registry2.count()
        assert count1 == count2
        # Both calls should return the same global registry
        assert registry1 is registry2

    def test_initialize_with_persistence(self, tmp_path: Path) -> None:
        """initialize() with persistence creates SQLite database."""
        db_path = tmp_path / "test.db"
        # We need to reset the global registry first to force a new one
        reset_registry()
        registry = get_registry(persist=True, db_path=db_path)
        bootstrap_register(registry)
        assert db_path.exists()
        registry.close()


# ======================================================================
# Test: snapshot and self-description
# ======================================================================


class TestSnapshotAndDescription:
    """Verify that the bootstrapped registry produces accurate snapshots."""

    @pytest.fixture()
    def bootstrap_registry(self) -> ComponentRegistry:
        return _get_initialized_registry()

    def test_snapshot_component_count(self, bootstrap_registry: ComponentRegistry) -> None:
        """Snapshot reports correct component count."""
        snapshot = bootstrap_registry.snapshot()
        assert snapshot.component_count == EXPECTED_FRAMEWORK_COMPONENT_COUNT

    def test_snapshot_framework_count(self, bootstrap_registry: ComponentRegistry) -> None:
        """Snapshot reports correct framework component count."""
        snapshot = bootstrap_registry.snapshot()
        assert snapshot.framework_component_count == EXPECTED_FRAMEWORK_COMPONENT_COUNT

    def test_snapshot_layers(self, bootstrap_registry: ComponentRegistry) -> None:
        """Snapshot has FRAMEWORK layer with all components."""
        snapshot = bootstrap_registry.snapshot()
        assert "FRAMEWORK" in snapshot.layers
        assert len(snapshot.layers["FRAMEWORK"]) == EXPECTED_FRAMEWORK_COMPONENT_COUNT

    def test_describe_output_is_nonempty(self, bootstrap_registry: ComponentRegistry) -> None:
        """describe() produces non-trivial output."""
        snapshot = bootstrap_registry.snapshot()
        description = snapshot.describe()
        assert len(description) > 500

    def test_describe_mentions_all_components(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """describe() mentions every component by name."""
        snapshot = bootstrap_registry.snapshot()
        description = snapshot.describe()
        for name in bootstrap_registry:
            assert name in description, (
                f"Component '{name}' is not mentioned in describe() output"
            )

    def test_describe_mentions_s0ma(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """describe() mentions S0ma by name."""
        snapshot = bootstrap_registry.snapshot()
        description = snapshot.describe()
        assert "s0ma" in description.lower()

    def test_describe_contains_layer_section(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """describe() output has a components-by-layer section."""
        snapshot = bootstrap_registry.snapshot()
        description = snapshot.describe()
        assert "COMPONENTS BY LAYER" in description
        assert "FRAMEWORK" in description

    def test_describe_contains_component_count(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """describe() contains the accurate component count."""
        snapshot = bootstrap_registry.snapshot()
        description = snapshot.describe()
        assert str(EXPECTED_FRAMEWORK_COMPONENT_COUNT) in description

    def test_snapshot_to_dict_is_serializable(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """snapshot.to_dict() produces JSON-serializable output."""
        import json

        snapshot = bootstrap_registry.snapshot()
        data = snapshot.to_dict()
        # Should not raise
        json_str = json.dumps(data)
        assert len(json_str) > 100

    def test_snapshot_to_json_roundtrip(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """snapshot.to_json() produces valid JSON."""
        import json

        snapshot = bootstrap_registry.snapshot()
        json_str = snapshot.to_json()
        data = json.loads(json_str)
        assert data["component_count"] == EXPECTED_FRAMEWORK_COMPONENT_COUNT


# ======================================================================
# Test: contracts on framework components
# ======================================================================


class TestFrameworkContracts:
    """Verify that framework components have meaningful contracts."""

    @pytest.fixture()
    def bootstrap_registry(self) -> ComponentRegistry:
        return _get_initialized_registry()

    def test_component_registry_has_invariants(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """ComponentRegistry declares its invariants."""
        spec = bootstrap_registry.get("ComponentRegistry")
        assert spec is not None
        assert len(spec.contracts.invariants) > 0

    def test_component_decorator_has_contracts(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """ComponentDecorator declares pre and postconditions."""
        spec = bootstrap_registry.get("ComponentDecorator")
        assert spec is not None
        assert len(spec.contracts.preconditions) > 0
        assert len(spec.contracts.postconditions) > 0

    def test_internal_decorator_has_postconditions(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """InternalDecorator declares postconditions."""
        spec = bootstrap_registry.get("InternalDecorator")
        assert spec is not None
        assert len(spec.contracts.postconditions) > 0

    def test_contract_has_validate(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """All contracts pass validation."""
        for name in bootstrap_registry:
            spec = bootstrap_registry.get(name)
            assert spec is not None
            # Should not raise
            spec.contracts.validate()


# ======================================================================
# Milestone 7: The Bootstrap Verification Tests
# ======================================================================
# These tests verify that the framework can *accurately describe itself*.
# If these tests fail, nothing else matters. This is the s0ma:
# the snake examining its own tail and confirming it matches.
# ======================================================================


class TestSelfVerification:
    """The S0ma Bootstrap Verification Suite (Milestone 7).

    Unlike the Milestone 6 tests above (which verify the mechanical
    correctness of registration), these tests verify *semantic accuracy* —
    the system's self-model matches reality as verified by AST-based
    source code analysis.
    """

    @pytest.fixture()
    def bootstrap_registry(self) -> ComponentRegistry:
        return _get_initialized_registry()

    def test_system_can_list_its_own_components(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """The registry knows about all its own parts."""
        snapshot = bootstrap_registry.snapshot()
        assert snapshot.component_count >= EXPECTED_FRAMEWORK_COMPONENT_COUNT
        # Every registered component must be in the snapshot
        for name in bootstrap_registry:
            assert name in snapshot.components, (
                f"Component '{name}' is registered but missing from snapshot"
            )

    def test_no_phantom_limbs(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """Every registered component has corresponding source code.

        A phantom limb is a registry entry with no matching code.
        The verifier resolves each component's qualified_name to an
        actual attribute in an actual module.
        """
        anomalies = verify_self_model(bootstrap_registry)
        phantom_limbs = [
            a for a in anomalies
            if a.kind == AnomalyKind.PHANTOM_LIMB
        ]
        assert phantom_limbs == [], (
            "Phantom limbs found:\n"
            + "\n".join(f"  - {a.message}" for a in phantom_limbs)
        )

    def test_no_blind_spots(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """Every public entity in S0ma is accounted for.

        A blind spot is a public class or function that exists in
        source but is not registered, not exempt (enum/exception),
        and not in the known utilities list. The verifier uses AST
        parsing to find every public entity in every S0ma module.
        """
        anomalies = verify_self_model(bootstrap_registry)
        blind_spots = [
            a for a in anomalies
            if a.kind == AnomalyKind.IMMUNE_RESPONSE
        ]
        assert blind_spots == [], (
            "Blind spots found:\n"
            + "\n".join(f"  - {a.message}" for a in blind_spots)
        )

    def test_module_paths_are_accurate(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """Registered module_path fields match actual module locations.

        Verified by the metadata accuracy check: every module_path
        must be importable, and the source file must match.
        """
        anomalies = verify_self_model(bootstrap_registry)
        path_errors = [
            a for a in anomalies
            if "module_path" in a.message or "cannot be imported" in a.message
        ]
        assert path_errors == [], (
            "Module path errors:\n"
            + "\n".join(f"  - {a.message}" for a in path_errors)
        )

    def test_source_files_exist(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """Registered source_file fields point to real files."""
        anomalies = verify_self_model(bootstrap_registry)
        file_errors = [
            a for a in anomalies
            if "source file" in a.message.lower()
            or "source_file" in a.message
        ]
        assert file_errors == [], (
            "Source file errors:\n"
            + "\n".join(f"  - {a.message}" for a in file_errors)
        )

    def test_intents_are_meaningful(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """Every component's intent is non-trivial and not a placeholder."""
        placeholders = {"todo", "placeholder", "tbd", "fixme", "xxx"}
        for name in bootstrap_registry:
            spec = bootstrap_registry.get(name)
            assert spec is not None
            assert len(spec.intent) >= 10, (
                f"Component '{name}' has insufficient intent: "
                f"'{spec.intent}'"
            )
            intent_lower = spec.intent.lower()
            for ph in placeholders:
                assert ph not in intent_lower, (
                    f"Component '{name}' has placeholder intent: "
                    f"'{spec.intent}'"
                )

    def test_self_description_is_accurate(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """The capstone test: run the verifier and assert zero anomalies.

        This is the single most important test in the entire project.
        It runs the full self-description verifier — checking for
        phantom limbs, blind spots, and metadata accuracy — and
        asserts that the system accurately describes itself.
        """
        anomalies = verify_self_model(bootstrap_registry)
        assert anomalies == [], (
            f"Self-description is inaccurate — "
            f"{len(anomalies)} anomalies found:\n"
            + "\n".join(
                f"  [{a.severity.name}] {a.message}" for a in anomalies
            )
        )

    def test_framework_component_count_is_stable(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """The number of framework components matches the expected count.

        Update EXPECTED_FRAMEWORK_COMPONENT_COUNT in _bootstrap.py
        whenever you add or remove a framework component. This test
        catches accidental omissions in bootstrap registration.
        """
        actual = bootstrap_registry.count()
        assert actual == EXPECTED_FRAMEWORK_COMPONENT_COUNT, (
            f"Expected {EXPECTED_FRAMEWORK_COMPONENT_COUNT} framework "
            f"components, found {actual}"
        )

    def test_snapshot_round_trip(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """The snapshot can be serialized and deserialized without loss."""
        import json

        snapshot = bootstrap_registry.snapshot()
        data = snapshot.to_dict()
        json_str = json.dumps(data)
        restored = json.loads(json_str)

        assert restored["component_count"] == snapshot.component_count
        assert (
            restored["framework_component_count"]
            == snapshot.framework_component_count
        )
        assert set(restored["components"].keys()) == set(
            snapshot.components.keys()
        )
        # Verify each component's intent survives the round trip
        for name in snapshot.components:
            assert (
                restored["components"][name]["intent"]
                == snapshot.components[name].intent
            )

    def test_describe_output_contains_all_component_names(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """The human-readable description mentions every component."""
        snapshot = bootstrap_registry.snapshot()
        description = snapshot.describe()
        for name in bootstrap_registry:
            assert name in description, (
                f"Component '{name}' not found in describe() output"
            )


class TestSelfDescriptionNarrative:
    """The 'Can I Describe Myself?' test suite.

    Simulates what an LLM or new developer would experience when
    asking the system 'what are you?'. The registry should produce
    a coherent, accurate description that a fresh reader could use
    to understand the system's architecture.
    """

    def test_self_description_narrative(self) -> None:
        """The system produces a coherent, substantive self-description."""
        registry = _get_initialized_registry()
        snapshot = registry.snapshot()
        description = snapshot.describe()

        # The description should mention S0ma
        assert "s0ma" in description.lower()

        # It should describe the major subsystems
        assert "registry" in description.lower()
        assert "decorator" in description.lower()
        assert "import" in description.lower()

        # It should be non-trivial (not just a list of names)
        assert len(description) > 500

        # It should contain the accurate component count
        assert str(snapshot.component_count) in description

    def test_description_identifies_framework_vs_user(self) -> None:
        """The description distinguishes framework from user components."""
        registry = _get_initialized_registry()
        snapshot = registry.snapshot()
        description = snapshot.describe()

        assert "framework" in description.lower()
        assert "user" in description.lower()

    def test_description_shows_dependency_relationships(self) -> None:
        """The description includes dependency graph information."""
        registry = _get_initialized_registry()
        snapshot = registry.snapshot()
        description = snapshot.describe()

        # ComponentRegistry has dependencies, so the graph should appear
        assert "DEPENDENCY" in description.upper()

    def test_description_covers_all_layers(self) -> None:
        """The description organizes components by architectural layer."""
        registry = _get_initialized_registry()
        snapshot = registry.snapshot()
        description = snapshot.describe()

        # All framework components are in the FRAMEWORK layer
        assert "FRAMEWORK" in description
        assert "COMPONENTS BY LAYER" in description

    def test_description_is_self_referential(self) -> None:
        """The description acknowledges it was generated by the self-model."""
        registry = _get_initialized_registry()
        snapshot = registry.snapshot()
        description = snapshot.describe()

        assert "self-model" in description.lower() or (
            "self-description" in description.lower()
        )


# ======================================================================
# Test: Serialization Round-Trip Integrity
# ======================================================================


class TestSerializationRoundTrip:
    """Verify that all framework components can be serialized and deserialized.

    This tests the from_dict() / to_dict() round-trip for every registered
    framework component, ensuring the self-model's self-description is
    faithfully reconstructable.
    """

    @pytest.fixture()
    def bootstrap_registry(self) -> ComponentRegistry:
        return _get_initialized_registry()

    def test_all_framework_components_round_trip(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """Every framework component can be serialized and deserialized accurately.

        This is the round-trip test mandated by Milestone 5: verify that
        ComponentSpec.from_dict(spec.to_dict()) == spec for every registered
        framework component.
        """
        for name in bootstrap_registry:
            spec = bootstrap_registry.get(name)
            assert spec is not None, f"Component '{name}' not found in registry"

            # Serialize to dict
            serialized = spec.to_dict()

            # Deserialize back
            reconstructed = ComponentSpec.from_dict(serialized)

            # Verify all fields match
            assert reconstructed.name == spec.name, (
                f"Round-trip failed for '{name}': name mismatch"
            )
            assert reconstructed.kind == spec.kind, (
                f"Round-trip failed for '{name}': kind mismatch"
            )
            assert reconstructed.layer == spec.layer, (
                f"Round-trip failed for '{name}': layer mismatch"
            )
            assert reconstructed.intent == spec.intent, (
                f"Round-trip failed for '{name}': intent mismatch"
            )
            assert reconstructed.dependencies == spec.dependencies, (
                f"Round-trip failed for '{name}': dependencies mismatch"
            )
            assert reconstructed.version == spec.version, (
                f"Round-trip failed for '{name}': version mismatch"
            )
            assert reconstructed.metadata == spec.metadata, (
                f"Round-trip failed for '{name}': metadata mismatch"
            )
            assert reconstructed.module_path == spec.module_path, (
                f"Round-trip failed for '{name}': module_path mismatch"
            )
            assert reconstructed.qualified_name == spec.qualified_name, (
                f"Round-trip failed for '{name}': qualified_name mismatch"
            )
            assert reconstructed.source_file == spec.source_file, (
                f"Round-trip failed for '{name}': source_file mismatch"
            )
            assert reconstructed.is_framework == spec.is_framework, (
                f"Round-trip failed for '{name}': is_framework mismatch"
            )

            # Contract round-trip (compare field-by-field since Contract has no __eq__)
            assert reconstructed.contracts.preconditions == spec.contracts.preconditions
            assert reconstructed.contracts.postconditions == spec.contracts.postconditions
            assert reconstructed.contracts.invariants == spec.contracts.invariants
            assert reconstructed.contracts.max_latency_ms == spec.contracts.max_latency_ms
            assert (
                reconstructed.contracts.error_rate_threshold
                == spec.contracts.error_rate_threshold
            )
            assert reconstructed.contracts.input_type == spec.contracts.input_type
            assert reconstructed.contracts.output_type == spec.contracts.output_type
            assert (
                reconstructed.contracts.configurable_properties
                == spec.contracts.configurable_properties
            )

            # ResourceProfile round-trip
            if spec.resource_profile is None:
                assert reconstructed.resource_profile is None
            else:
                assert reconstructed.resource_profile is not None
                assert (
                    reconstructed.resource_profile.expected_memory_mb
                    == spec.resource_profile.expected_memory_mb
                )
                assert (
                    reconstructed.resource_profile.expected_latency_p50_ms
                    == spec.resource_profile.expected_latency_p50_ms
                )
                assert (
                    reconstructed.resource_profile.expected_latency_p99_ms
                    == spec.resource_profile.expected_latency_p99_ms
                )
                assert (
                    reconstructed.resource_profile.expected_error_rate
                    == spec.resource_profile.expected_error_rate
                )
                assert (
                    reconstructed.resource_profile.expected_call_frequency_per_min
                    == spec.resource_profile.expected_call_frequency_per_min
                )

    def test_framework_components_with_configurable_properties_round_trip(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """Framework components with configurable properties round-trip correctly."""
        # Find any framework component with configurable_properties
        components_with_props = [
            spec
            for name in bootstrap_registry
            if (spec := bootstrap_registry.get(name)) is not None
            and spec.contracts.configurable_properties is not None
        ]

        if not components_with_props:
            pytest.skip("No framework components have configurable_properties yet")

        for spec in components_with_props:
            serialized = spec.to_dict()
            reconstructed = ComponentSpec.from_dict(serialized)

            # Verify configurable_properties round-trip
            assert reconstructed.contracts.configurable_properties is not None
            assert (
                reconstructed.contracts.configurable_properties
                == spec.contracts.configurable_properties
            ), f"Configurable properties round-trip failed for '{spec.name}'"
