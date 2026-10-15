"""Tests for the S0ma component registry.

Comprehensive tests covering registration, retrieval, hierarchical queries,
dependency graph traversal, snapshot generation, SQLite persistence,
thread safety, global singleton management, and error handling.
"""

from __future__ import annotations

import json
import logging
import types
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import pytest

from s0ma.exceptions import RegistrationError, RegistryIntegrityError
from s0ma.models import (
    ComponentSpec,
    Contract,
    ResourceProfile,
)
from s0ma.registry import (
    ComponentRegistry,
    get_registry,
    reset_registry,
    set_registry,
)
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_spec(name: str = "TestComponent", **overrides: object) -> ComponentSpec:
    """Create a valid ComponentSpec with sensible defaults."""
    defaults: dict[str, object] = {
        "name": name,
        "kind": ComponentKind.SERVICE,
        "layer": Layer.DOMAIN,
        "intent": "A test component used in unit tests for validation",
        "module_path": f"tests.{name.lower()}",
        "qualified_name": f"tests.{name.lower()}.{name}",
    }
    defaults.update(overrides)
    return ComponentSpec(**defaults)  # type: ignore[arg-type]


# ===========================================================================
# Registration and Retrieval Tests
# ===========================================================================

class TestRegistration:
    """Tests for component registration and retrieval."""

    def test_register_and_retrieve(self, registry: ComponentRegistry) -> None:
        """A registered component can be retrieved by name."""
        spec = make_spec("MyService")
        registry.register(spec)
        result = registry.get("MyService")
        assert result is not None
        assert result.name == "MyService"
        assert result.kind == ComponentKind.SERVICE

    def test_register_increments_count(self, registry: ComponentRegistry) -> None:
        """Each registration increases the component count."""
        assert registry.count() == 0
        registry.register(make_spec("A"))
        assert registry.count() == 1
        registry.register(make_spec("B"))
        assert registry.count() == 2

    def test_get_nonexistent_returns_none(self, registry: ComponentRegistry) -> None:
        """Querying a non-existent component returns None."""
        assert registry.get("DoesNotExist") is None

    def test_get_all_returns_copy(self, registry: ComponentRegistry) -> None:
        """get_all() returns a copy of the components dict."""
        registry.register(make_spec("A"))
        all_components = registry.get_all()
        assert "A" in all_components
        # Modifying the returned dict doesn't affect the registry
        all_components.pop("A")
        assert registry.get("A") is not None

    def test_duplicate_name_raises(self, registry: ComponentRegistry) -> None:
        """Registering a duplicate name raises RegistrationError."""
        registry.register(make_spec("Dup"))
        with pytest.raises(RegistrationError, match="already registered"):
            registry.register(make_spec("Dup"))

    def test_duplicate_error_message_includes_module_paths(
        self, registry: ComponentRegistry
    ) -> None:
        """The duplicate error message includes both old and new module paths."""
        registry.register(make_spec("Dup", module_path="old.module"))
        with pytest.raises(RegistrationError, match="old.module") as exc_info:
            registry.register(make_spec("Dup", module_path="new.module"))
        assert "new.module" in str(exc_info.value)

    def test_register_with_full_metadata(self, registry: ComponentRegistry) -> None:
        """A component with all fields populated registers correctly."""
        spec = ComponentSpec(
            name="FullComponent",
            kind=ComponentKind.ORCHESTRATOR,
            layer=Layer.APPLICATION,
            intent="A fully specified test component with all metadata",
            contracts=Contract(
                preconditions=["input is valid"],
                postconditions=["returns result"],
                invariants=["no side effects on failure"],
                max_latency_ms=100.0,
                error_rate_threshold=0.01,
            ),
            dependencies=[],
            resource_profile=ResourceProfile(
                expected_memory_mb=256.0,
                expected_latency_p50_ms=10.0,
            ),
            version="1.2.3",
            metadata={"owner": "team-a"},
            module_path="myapp.orchestrators.full",
            qualified_name="myapp.orchestrators.full.FullComponent",
            source_file="/path/to/full.py",
            is_framework=False,
        )
        registry.register(spec)
        result = registry.get("FullComponent")
        assert result is not None
        assert result.version == "1.2.3"
        assert result.metadata["owner"] == "team-a"
        assert result.resource_profile is not None
        assert result.resource_profile.expected_memory_mb == 256.0


# ===========================================================================
# Dependency Validation Tests
# ===========================================================================

class TestDependencyValidation:
    """Tests for lenient vs. strict dependency checking."""

    def test_lenient_mode_warns_on_missing_dependency(
        self, registry: ComponentRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        """In lenient mode, missing deps produce a warning but succeed."""
        import logging
        with caplog.at_level(logging.WARNING, logger="s0ma"):
            registry.register(make_spec("A", dependencies=["NotYetRegistered"]))
        assert "NotYetRegistered" in caplog.text
        assert registry.count() == 1

    def test_strict_mode_raises_on_missing_dependency(
        self, strict_registry: ComponentRegistry
    ) -> None:
        """In strict mode, missing deps raise RegistrationError."""
        with pytest.raises(RegistrationError, match="not yet registered"):
            strict_registry.register(
                make_spec("A", dependencies=["NotRegistered"])
            )

    def test_strict_mode_allows_registered_dependency(
        self, strict_registry: ComponentRegistry
    ) -> None:
        """In strict mode, registered deps pass validation."""
        strict_registry.register(make_spec("Base"))
        strict_registry.register(
            make_spec("Dependent", dependencies=["Base"])
        )
        assert strict_registry.count() == 2

    def test_register_or_update_accepts_qualified_claim(
        self, registry: ComponentRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The upsert path validates the emitter's canonical qualified
        claims exactly like ``register`` (both route through
        ``_resolve_key`` — pinned in test_registry_qualified_resolution.py).
        """
        import logging
        registry.register(
            make_spec("LightReading", module_path="reading_models")
        )
        with caplog.at_level(logging.WARNING, logger="s0ma"):
            registry.register_or_update(
                make_spec(
                    "read_light",
                    module_path="senses",
                    dependencies=["reading_models::LightReading"],
                )
            )
        assert "not yet registered" not in caplog.text


# ===========================================================================
# Hierarchical Query Tests
# ===========================================================================

class TestHierarchicalQueries:
    """Tests for query_by_layer, query_by_kind, and dependency traversal."""

    def test_query_by_layer(self, populated_registry: ComponentRegistry) -> None:
        """query_by_layer returns only components in the specified layer."""
        domain_specs = populated_registry.query_by_layer(Layer.DOMAIN)
        names = {s.name for s in domain_specs}
        assert names == {"UserService", "UserModel"}

    def test_query_by_layer_empty(self, populated_registry: ComponentRegistry) -> None:
        """query_by_layer returns empty list for layers with no components."""
        result = populated_registry.query_by_layer(Layer.PRESENTATION)
        assert result == []

    def test_query_by_kind(self, populated_registry: ComponentRegistry) -> None:
        """query_by_kind returns only components of the specified kind."""
        services = populated_registry.query_by_kind(ComponentKind.SERVICE)
        assert len(services) == 1
        assert services[0].name == "UserService"

    def test_query_by_kind_multiple(self, registry: ComponentRegistry) -> None:
        """query_by_kind returns multiple components of the same kind."""
        registry.register(make_spec("SvcA", kind=ComponentKind.SERVICE))
        registry.register(make_spec("SvcB", kind=ComponentKind.SERVICE))
        services = registry.query_by_kind(ComponentKind.SERVICE)
        assert len(services) == 2

    def test_query_by_kind_empty(self, populated_registry: ComponentRegistry) -> None:
        """query_by_kind returns empty list when no components match."""
        result = populated_registry.query_by_kind(ComponentKind.ORCHESTRATOR)
        assert result == []

    def test_get_dependencies(self, populated_registry: ComponentRegistry) -> None:
        """get_dependencies returns resolved dependency specs."""
        deps = populated_registry.get_dependencies("UserService")
        assert len(deps) == 1
        assert deps[0].name == "DatabaseAdapter"

    def test_get_dependencies_empty(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """get_dependencies returns empty list for components with no deps."""
        deps = populated_registry.get_dependencies("UserModel")
        assert deps == []

    def test_get_dependencies_unregistered_raises(
        self, registry: ComponentRegistry
    ) -> None:
        """get_dependencies raises for a component not in the registry."""
        with pytest.raises(RegistryIntegrityError, match="not registered"):
            registry.get_dependencies("Ghost")

    def test_get_dependents(self, populated_registry: ComponentRegistry) -> None:
        """get_dependents returns components that depend on the target."""
        dependents = populated_registry.get_dependents("DatabaseAdapter")
        assert len(dependents) == 1
        assert dependents[0].name == "UserService"

    def test_get_dependents_none(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """get_dependents returns empty list when nobody depends on target."""
        dependents = populated_registry.get_dependents("UserService")
        assert dependents == []

    def test_get_dependents_unregistered_raises(
        self, registry: ComponentRegistry
    ) -> None:
        """get_dependents raises for a component not in the registry."""
        with pytest.raises(RegistryIntegrityError, match="not registered"):
            registry.get_dependents("Ghost")

    def test_get_dependents_counts_qualified_claims(
        self, registry: ComponentRegistry
    ) -> None:
        """Reverse lookup sees dependents that claim the qualified form."""
        registry.register(
            make_spec("LightReading", module_path="reading_models")
        )
        registry.register(
            make_spec(
                "read_light",
                dependencies=["reading_models::LightReading"],
            )
        )
        dependents = registry.get_dependents("LightReading")
        assert [d.name for d in dependents] == ["read_light"]


# ===========================================================================
# Dependency Graph Tests
# ===========================================================================

class TestDependencyGraph:
    """Tests for the full dependency graph."""

    def test_dependency_graph_structure(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """get_dependency_graph returns correct adjacency list."""
        graph = populated_registry.get_dependency_graph()
        assert graph["UserService"] == ["DatabaseAdapter"]
        assert graph["DatabaseAdapter"] == []
        assert graph["UserModel"] == []

    def test_dependency_graph_empty_registry(
        self, registry: ComponentRegistry
    ) -> None:
        """An empty registry produces an empty graph."""
        graph = registry.get_dependency_graph()
        assert graph == {}

    def test_dependency_graph_chain(self, registry: ComponentRegistry) -> None:
        """A -> B -> C dependency chain is represented correctly."""
        registry.register(make_spec("C"))
        registry.register(make_spec("B", dependencies=["C"]))
        registry.register(make_spec("A", dependencies=["B"]))
        graph = registry.get_dependency_graph()
        assert graph["A"] == ["B"]
        assert graph["B"] == ["C"]
        assert graph["C"] == []

    def test_dependency_graph_diamond(self, registry: ComponentRegistry) -> None:
        """A diamond dependency pattern is represented correctly.

            A
           / \\
          B   C
           \\ /
            D
        """
        registry.register(make_spec("D"))
        registry.register(make_spec("B", dependencies=["D"]))
        registry.register(make_spec("C", dependencies=["D"]))
        registry.register(make_spec("A", dependencies=["B", "C"]))
        graph = registry.get_dependency_graph()
        assert set(graph["A"]) == {"B", "C"}
        assert graph["B"] == ["D"]
        assert graph["C"] == ["D"]
        assert graph["D"] == []

    def test_import_order_honours_qualified_claims(
        self, registry: ComponentRegistry
    ) -> None:
        """Qualified claims contribute their cross-module ordering edges."""
        registry.register(
            make_spec("LightReading", module_path="reading_models")
        )
        registry.register(
            make_spec(
                "read_light",
                module_path="senses",
                dependencies=["reading_models::LightReading"],
            )
        )
        order = registry.import_order()
        assert order.index("reading_models") < order.index("senses")


# ===========================================================================
# Snapshot Tests
# ===========================================================================

class TestSnapshot:
    """Tests for registry snapshot generation."""

    def test_snapshot_component_count(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """Snapshot has correct component count."""
        snap = populated_registry.snapshot()
        assert snap.component_count == 3

    def test_snapshot_framework_count(self, registry: ComponentRegistry) -> None:
        """Snapshot correctly counts framework components."""
        registry.register(make_spec("FwComponent", is_framework=True))
        registry.register(make_spec("UserComponent"))
        snap = registry.snapshot()
        assert snap.framework_component_count == 1
        assert snap.component_count == 2

    def test_snapshot_layers(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """Snapshot layers dict groups components correctly."""
        snap = populated_registry.snapshot()
        assert "DOMAIN" in snap.layers
        assert "INFRASTRUCTURE" in snap.layers
        assert set(snap.layers["DOMAIN"]) == {"UserService", "UserModel"}
        assert snap.layers["INFRASTRUCTURE"] == ["DatabaseAdapter"]

    def test_snapshot_dependency_graph(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """Snapshot dependency graph is accurate."""
        snap = populated_registry.snapshot()
        assert snap.dependency_graph["UserService"] == ["DatabaseAdapter"]
        assert snap.dependency_graph["DatabaseAdapter"] == []

    def test_snapshot_contains_all_components(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """Snapshot contains every registered component."""
        snap = populated_registry.snapshot()
        assert set(snap.components.keys()) == {
            "UserService", "DatabaseAdapter", "UserModel"
        }

    def test_snapshot_describe_is_readable(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """snapshot().describe() produces readable output."""
        snap = populated_registry.snapshot()
        desc = snap.describe()
        assert "S0MA SYSTEM SELF-DESCRIPTION" in desc
        assert "UserService" in desc
        assert "DatabaseAdapter" in desc
        assert "Total components: 3" in desc
        assert len(desc) > 500

    def test_snapshot_empty_registry(self, registry: ComponentRegistry) -> None:
        """An empty registry produces a valid snapshot."""
        snap = registry.snapshot()
        assert snap.component_count == 0
        assert snap.framework_component_count == 0
        assert snap.layers == {}
        assert snap.dependency_graph == {}

    def test_snapshot_is_frozen(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """The snapshot does not change when the registry changes."""
        snap1 = populated_registry.snapshot()
        populated_registry.register(make_spec("NewComponent"))
        snap2 = populated_registry.snapshot()
        assert snap1.component_count == 3
        assert snap2.component_count == 4

    def test_snapshot_captures_modules(
        self, registry: ComponentRegistry
    ) -> None:
        """Snapshot includes registered modules."""
        registry.register_module(
            name="config",
            layer="DOMAIN",
            version="0.1.0",
            intent="Application configuration settings",
            exports=["DEFAULT_MODEL"],
        )
        snap = registry.snapshot()
        assert "config" in snap.modules
        assert snap.modules["config"].layer == "DOMAIN"
        assert snap.modules["config"].exports == ["DEFAULT_MODEL"]

    def test_snapshot_captures_edges(
        self, registry: ComponentRegistry
    ) -> None:
        """Snapshot includes registered relationship edges."""
        registry.register_relationship(
            source="Orchestrator",
            target="LLMAdapter",
            relation="CALLS",
            carries="ChatMessage",
        )
        snap = registry.snapshot()
        assert len(snap.edges) == 1
        assert snap.edges[0].source == "Orchestrator"
        assert snap.edges[0].relation == "CALLS"

    def test_snapshot_captures_test_registrations(
        self, registry: ComponentRegistry
    ) -> None:
        """Snapshot includes registered test declarations."""
        registry.register_test(
            name="test_orchestrator",
            intent="Validates orchestrator flow",
            validates=["Orchestrator"],
        )
        snap = registry.snapshot()
        assert "test_orchestrator" in snap.test_registrations
        assert snap.test_registrations["test_orchestrator"].validates == [
            "Orchestrator"
        ]


# ===========================================================================
# Registry to_dict Tests
# ===========================================================================


class TestRegistryToDict:
    """Tests for ComponentRegistry.to_dict() serialization."""

    def test_to_dict_empty_registry(self, registry: ComponentRegistry) -> None:
        """to_dict() returns valid structure with no registrations."""
        d = registry.to_dict()
        assert d["components"] == {}
        assert d["modules"] == {}
        assert d["edges"] == []
        assert d["test_registrations"] == {}
        assert d["summary"]["component_count"] == 0
        assert d["summary"]["module_count"] == 0
        assert d["summary"]["edge_count"] == 0
        assert d["summary"]["test_count"] == 0

    def test_to_dict_with_components(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """to_dict() includes registered components."""
        d = populated_registry.to_dict()
        assert "UserService" in d["components"]
        assert "DatabaseAdapter" in d["components"]
        assert d["summary"]["component_count"] == 3

    def test_to_dict_with_modules(self, registry: ComponentRegistry) -> None:
        """to_dict() includes registered modules."""
        registry.register_module(
            name="models",
            layer="DOMAIN",
            version="0.2.0",
            intent="Core domain data models",
            exports=["User", "Order"],
        )
        d = registry.to_dict()
        assert "models" in d["modules"]
        assert d["modules"]["models"]["version"] == "0.2.0"
        assert d["summary"]["module_count"] == 1

    def test_to_dict_with_edges(self, registry: ComponentRegistry) -> None:
        """to_dict() includes registered relationship edges."""
        registry.register_relationship(
            source="A",
            target="B",
            relation="CALLS",
        )
        d = registry.to_dict()
        assert len(d["edges"]) == 1
        assert d["edges"][0]["source"] == "A"
        assert d["summary"]["edge_count"] == 1

    def test_to_dict_with_test_registrations(
        self, registry: ComponentRegistry
    ) -> None:
        """to_dict() includes registered test declarations."""
        registry.register_test(
            name="test_user_service",
            intent="Validates user registration",
            validates=["UserService"],
        )
        d = registry.to_dict()
        assert "test_user_service" in d["test_registrations"]
        assert d["summary"]["test_count"] == 1

    def test_to_dict_summary_counts(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """Summary dict has correct counts across all stores."""
        populated_registry.register_module(
            name="mod1",
            layer="DOMAIN",
            version="0.1.0",
            intent="First test module for validation",
        )
        populated_registry.register_relationship(
            source="X", target="Y", relation="READS",
        )
        populated_registry.register_relationship(
            source="Y", target="Z", relation="CALLS",
        )
        populated_registry.register_test(
            name="t1",
            intent="Test for component validation",
        )
        d = populated_registry.to_dict()
        assert d["summary"]["component_count"] == 3
        assert d["summary"]["module_count"] == 1
        assert d["summary"]["edge_count"] == 2
        assert d["summary"]["test_count"] == 1

    def test_to_dict_is_json_serializable(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """to_dict() output can be serialized to JSON."""
        populated_registry.register_module(
            name="core",
            layer="DOMAIN",
            version="1.0.0",
            intent="Core module for application logic",
            exports=["MainService"],
        )
        populated_registry.register_relationship(
            source="A", target="B", relation="CALLS",
        )
        populated_registry.register_test(
            name="test_main",
            intent="Main service integration test",
            validates=["MainService"],
        )
        d = populated_registry.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["summary"]["component_count"] == 3


# ===========================================================================
# Containment and Iteration Tests
# ===========================================================================

class TestContainmentAndIteration:
    """Tests for Pythonic container interface."""

    def test_contains_via_method(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """contains() returns True for registered components."""
        assert populated_registry.contains("UserService")
        assert not populated_registry.contains("Unknown")

    def test_contains_via_in_operator(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """'in' operator works with the registry."""
        assert "UserService" in populated_registry
        assert "Unknown" not in populated_registry

    def test_contains_non_string_returns_false(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """Non-string values return False for 'in' operator."""
        assert 42 not in populated_registry  # type: ignore[operator]

    def test_len(self, populated_registry: ComponentRegistry) -> None:
        """len() returns the component count."""
        assert len(populated_registry) == 3

    def test_iter(self, populated_registry: ComponentRegistry) -> None:
        """Iteration yields component names."""
        names = set(populated_registry)
        assert names == {"UserService", "DatabaseAdapter", "UserModel"}


# ===========================================================================
# Reset Tests
# ===========================================================================

class TestReset:
    """Tests for registry reset."""

    def test_reset_clears_all_components(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """reset() removes all components."""
        assert populated_registry.count() == 3
        populated_registry.reset()
        assert populated_registry.count() == 0
        assert populated_registry.get("UserService") is None

    def test_reset_allows_re_registration(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """After reset, previously used names can be registered again."""
        populated_registry.reset()
        populated_registry.register(make_spec("UserService"))
        assert populated_registry.count() == 1


# ===========================================================================
# SQLite Persistence Tests
# ===========================================================================

class TestPersistence:
    """Tests for SQLite persistence."""

    def test_persistence_survives_reinstantiation(
        self, tmp_path: Path
    ) -> None:
        """Components persist through registry destruction and recreation."""
        db_path = tmp_path / "persist_test.db"

        # Create and populate
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        reg1.register(make_spec("PersistentService"))
        reg1.register(
            make_spec(
                "PersistentModel",
                kind=ComponentKind.MODEL,
                layer=Layer.DOMAIN,
            )
        )
        assert reg1.count() == 2
        reg1.close()

        # Recreate from same db path
        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        assert reg2.count() == 2
        result = reg2.get("PersistentService")
        assert result is not None
        assert result.kind == ComponentKind.SERVICE
        reg2.close()

    def test_persistence_preserves_all_fields(
        self, tmp_path: Path
    ) -> None:
        """All ComponentSpec fields survive the serialization round-trip."""
        db_path = tmp_path / "fields_test.db"
        contract = Contract(
            preconditions=["input is valid"],
            postconditions=["returns result"],
            invariants=["no side effects"],
            max_latency_ms=50.0,
            error_rate_threshold=0.05,
            input_type="str",
            output_type="dict",
        )
        resource_profile = ResourceProfile(
            expected_memory_mb=128.0,
            expected_latency_p50_ms=5.0,
            expected_latency_p99_ms=25.0,
            expected_error_rate=0.01,
            expected_call_frequency_per_min=1000.0,
        )
        original = ComponentSpec(
            name="FullPersistence",
            kind=ComponentKind.ORCHESTRATOR,
            layer=Layer.APPLICATION,
            intent="Tests that every field survives SQLite round-trip",
            contracts=contract,
            dependencies=["SomeDep"],
            resource_profile=resource_profile,
            version="2.0.0",
            metadata={"team": "core", "priority": 1},
            module_path="myapp.orchestrators.full",
            qualified_name="myapp.orchestrators.full.FullPersistence",
            source_file="/path/to/full.py",
            is_framework=True,
        )

        # Persist
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        reg1.register(original)
        reg1.close()

        # Reload
        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        loaded = reg2.get("FullPersistence")
        assert loaded is not None

        # Verify all fields
        assert loaded.name == original.name
        assert loaded.kind == original.kind
        assert loaded.layer == original.layer
        assert loaded.intent == original.intent
        assert loaded.version == original.version
        assert loaded.module_path == original.module_path
        assert loaded.qualified_name == original.qualified_name
        assert loaded.source_file == original.source_file
        assert loaded.is_framework == original.is_framework
        assert loaded.dependencies == original.dependencies
        assert loaded.metadata == original.metadata

        # Contracts
        assert loaded.contracts.preconditions == original.contracts.preconditions
        assert loaded.contracts.postconditions == original.contracts.postconditions
        assert loaded.contracts.invariants == original.contracts.invariants
        assert loaded.contracts.max_latency_ms == original.contracts.max_latency_ms
        assert loaded.contracts.error_rate_threshold == original.contracts.error_rate_threshold
        assert loaded.contracts.input_type == original.contracts.input_type
        assert loaded.contracts.output_type == original.contracts.output_type

        # Resource profile
        assert loaded.resource_profile is not None
        assert loaded.resource_profile.expected_memory_mb == 128.0
        assert loaded.resource_profile.expected_latency_p50_ms == 5.0
        assert loaded.resource_profile.expected_latency_p99_ms == 25.0
        assert loaded.resource_profile.expected_error_rate == 0.01
        assert loaded.resource_profile.expected_call_frequency_per_min == 1000.0

        # Timestamp round-trip
        assert loaded.registered_at == original.registered_at

        reg2.close()

    def test_persistence_reset_clears_database(
        self, tmp_path: Path
    ) -> None:
        """reset() clears both memory and the SQLite database."""
        db_path = tmp_path / "reset_test.db"
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        reg1.register(make_spec("Ephemeral"))
        assert reg1.count() == 1
        reg1.reset()
        assert reg1.count() == 0
        reg1.close()

        # Verify the db was cleared
        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        assert reg2.count() == 0
        reg2.close()

    def test_no_persistence_mode(self, registry: ComponentRegistry) -> None:
        """With persist=False, no SQLite operations occur."""
        registry.register(make_spec("InMemoryOnly"))
        assert registry.count() == 1
        # No db_path, no connection
        assert registry._db_path is None
        assert registry._connection is None

    def test_persistence_creates_directory(self, tmp_path: Path) -> None:
        """The registry creates the parent directory for the db if needed."""
        db_path = tmp_path / "subdir" / "nested" / "registry.db"
        reg = ComponentRegistry(persist=True, db_path=db_path)
        reg.register(make_spec("DeepComponent"))
        assert db_path.exists()
        reg.close()


# ===========================================================================
# Thread Safety Tests
# ===========================================================================

class TestThreadSafety:
    """Tests for thread-safe operations."""

    def test_concurrent_registrations(self, registry: ComponentRegistry) -> None:
        """Concurrent registrations from multiple threads succeed."""
        num_components = 50

        def register_component(i: int) -> str:
            name = f"ThreadComponent_{i}"
            registry.register(make_spec(name))
            return name

        registered_names: set[str] = set()
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(register_component, i)
                for i in range(num_components)
            }
            for future in as_completed(futures):
                registered_names.add(future.result())

        assert len(registered_names) == num_components
        assert registry.count() == num_components

    def test_concurrent_read_during_write(
        self, registry: ComponentRegistry
    ) -> None:
        """Reading during concurrent writes doesn't corrupt state."""
        # Pre-populate
        for i in range(10):
            registry.register(make_spec(f"Pre_{i}"))

        def register_more(i: int) -> None:
            registry.register(make_spec(f"Concurrent_{i}"))

        def read_all() -> int:
            return registry.count()

        with ThreadPoolExecutor(max_workers=10) as executor:
            write_futures = [
                executor.submit(register_more, i) for i in range(20)
            ]
            read_futures = [executor.submit(read_all) for _ in range(20)]

            for f in write_futures:
                f.result()  # raises if any failed
            for f in read_futures:
                count = f.result()
                assert count >= 10  # at least the pre-populated ones

        assert registry.count() == 30  # 10 pre + 20 concurrent


# ===========================================================================
# Global Registry Singleton Tests
# ===========================================================================

class TestGlobalSingleton:
    """Tests for get_registry, set_registry, reset_registry."""

    def test_get_registry_creates_singleton(self) -> None:
        """get_registry() returns the same instance on repeated calls."""
        reg1 = get_registry(persist=False)
        reg2 = get_registry(persist=False)
        assert reg1 is reg2

    def test_reset_registry_clears_singleton(self) -> None:
        """reset_registry() allows a fresh instance on next get_registry()."""
        reg1 = get_registry(persist=False)
        reset_registry()
        reg2 = get_registry(persist=False)
        assert reg1 is not reg2

    def test_set_registry_replaces_singleton(self) -> None:
        """set_registry() replaces the global instance."""
        custom = ComponentRegistry(persist=False)
        set_registry(custom)
        assert get_registry() is custom

    def test_get_registry_with_persistence(self, tmp_path: Path) -> None:
        """get_registry() can create a persistent registry."""
        db_path = tmp_path / "global_test.db"
        reg = get_registry(persist=True, db_path=db_path)
        reg.register(make_spec("GlobalComponent"))
        assert reg.contains("GlobalComponent")
        assert db_path.exists()


# ===========================================================================
# Large-Scale Registration Tests
# ===========================================================================

class TestScalability:
    """Tests for handling larger numbers of components."""

    def test_register_100_components(self, registry: ComponentRegistry) -> None:
        """Registry correctly handles 100+ component registrations."""
        for i in range(100):
            registry.register(
                make_spec(
                    f"Component_{i}",
                    kind=ComponentKind(i % 6 + 1),
                    layer=Layer(i % 5 + 1),
                )
            )
        assert registry.count() == 100

        # Verify queries still work
        services = registry.query_by_kind(ComponentKind.SERVICE)
        assert len(services) > 0

        domain = registry.query_by_layer(Layer.DOMAIN)
        assert len(domain) > 0

        # Verify snapshot works
        snap = registry.snapshot()
        assert snap.component_count == 100
        desc = snap.describe()
        assert "Total components: 100" in desc

    def test_snapshot_describe_with_100_components(
        self, registry: ComponentRegistry
    ) -> None:
        """describe() produces accurate output for a large registry."""
        for i in range(100):
            registry.register(make_spec(f"Comp_{i}"))
        snap = registry.snapshot()
        desc = snap.describe()
        # Every component should appear in the description
        for i in range(100):
            assert f"Comp_{i}" in desc


# ===========================================================================
# register_from_module() Tests
# ===========================================================================

def _make_synthetic_module(
    specs: list[ComponentSpec],
    module_name: str = "test_synthetic_module",
) -> types.ModuleType:
    """Create a synthetic module with @component-decorated entities.

    Builds a ModuleType with one attribute per spec. Each attribute is a
    simple class with ``__component__`` set to the given spec — matching
    the structure that the @component decorator produces.
    """
    mod = types.ModuleType(module_name)
    for spec in specs:
        # Mimic what @component attaches: a class bearing __component__
        cls = type(spec.name, (), {"__component__": spec})
        setattr(mod, spec.name, cls)
    return mod


class TestRegisterFromModule:
    """Tests for ComponentRegistry.register_from_module()."""

    def test_register_from_module_registers_components(
        self, registry: ComponentRegistry
    ) -> None:
        """register_from_module() registers all @component-decorated entities."""
        specs = [make_spec("Alpha"), make_spec("Beta")]
        mod = _make_synthetic_module(specs)

        result = registry.register_from_module(mod)

        assert len(result) == 2
        assert registry.contains("Alpha")
        assert registry.contains("Beta")

    def test_register_from_module_returns_newly_registered(
        self, registry: ComponentRegistry
    ) -> None:
        """register_from_module() returns only specs registered in this call."""
        specs = [make_spec("X"), make_spec("Y")]
        mod = _make_synthetic_module(specs)

        result = registry.register_from_module(mod)

        assert {s.name for s in result} == {"X", "Y"}

    def test_register_from_module_skips_already_registered(
        self, registry: ComponentRegistry
    ) -> None:
        """register_from_module() skips components already in the registry."""
        spec = make_spec("Existing")
        registry.register(spec)

        mod = _make_synthetic_module([spec, make_spec("NewOne")])
        result = registry.register_from_module(mod)

        # Only the new component should be in the return list
        assert len(result) == 1
        assert result[0].name == "NewOne"
        # Both should now be in the registry
        assert registry.count() == 2

    def test_register_from_module_empty_module_returns_empty_list(
        self, registry: ComponentRegistry
    ) -> None:
        """register_from_module() on a module with no components returns []."""
        empty_mod = types.ModuleType("empty_module")
        result = registry.register_from_module(empty_mod)
        assert result == []
        assert registry.count() == 0

    def test_register_from_module_skips_internal_decorated_entities(
        self, registry: ComponentRegistry
    ) -> None:
        """register_from_module() ignores @internal-decorated entities."""
        from s0ma.decorators import internal

        mod = types.ModuleType("mixed_module")

        # A @component entity
        component_cls = type("Registered", (), {"__component__": make_spec("Registered")})
        mod.Registered = component_cls

        # An @internal entity (has __s0ma_internal__ but no __component__)
        @internal
        class _Helper:
            pass

        mod._Helper = _Helper

        result = registry.register_from_module(mod)
        assert len(result) == 1
        assert result[0].name == "Registered"
        assert not registry.contains("_Helper")

    def test_register_from_module_works_after_reset(
        self, registry: ComponentRegistry
    ) -> None:
        """register_from_module() correctly re-registers after registry reset."""
        specs = [make_spec("ServiceA"), make_spec("ServiceB")]
        mod = _make_synthetic_module(specs)

        # First pass
        first = registry.register_from_module(mod)
        assert len(first) == 2

        # Reset and re-register
        registry.reset()
        assert registry.count() == 0

        second = registry.register_from_module(mod)
        assert len(second) == 2
        assert registry.contains("ServiceA")
        assert registry.contains("ServiceB")

    def test_register_from_module_idempotent_on_second_call(
        self, registry: ComponentRegistry
    ) -> None:
        """Calling register_from_module() twice returns [] on the second call."""
        specs = [make_spec("Stable")]
        mod = _make_synthetic_module(specs)

        first = registry.register_from_module(mod)
        assert len(first) == 1

        second = registry.register_from_module(mod)
        assert second == []
        assert registry.count() == 1

    def test_register_from_module_increments_registry_count(
        self, registry: ComponentRegistry
    ) -> None:
        """register_from_module() adds all discovered components to the registry."""
        num = 5
        specs = [make_spec(f"BatchComp_{i}") for i in range(num)]
        mod = _make_synthetic_module(specs)

        registry.register_from_module(mod)
        assert registry.count() == num

    def test_register_from_module_with_multiple_modules(
        self, registry: ComponentRegistry
    ) -> None:
        """register_from_module() can be called for multiple modules."""
        mod_a = _make_synthetic_module([make_spec("CompA1"), make_spec("CompA2")])
        mod_b = _make_synthetic_module([make_spec("CompB1")])

        registry.register_from_module(mod_a)
        registry.register_from_module(mod_b)

        assert registry.count() == 3
        assert registry.contains("CompA1")
        assert registry.contains("CompA2")
        assert registry.contains("CompB1")


# ===========================================================================
# Idempotent Registration Tests
# ===========================================================================

class TestIdempotentRegistration:
    """Tests for idempotent=True parameter on register()."""

    def test_idempotent_true_same_source_file_succeeds_silently(
        self, registry: ComponentRegistry
    ) -> None:
        """register(spec, idempotent=True) silently succeeds when source_file matches."""
        spec = make_spec("Idempotent1", source_file="/project/my_module.py")
        registry.register(spec)

        # Re-register same spec with same source_file — should not raise
        registry.register(spec, idempotent=True)
        assert registry.count() == 1
        assert registry.contains("Idempotent1")

    def test_idempotent_true_different_source_file_raises(
        self, registry: ComponentRegistry
    ) -> None:
        """register(spec, idempotent=True) raises when source_file differs (name collision)."""
        spec_a = make_spec("CollisionComp", source_file="/project/module_a.py")
        spec_b = make_spec("CollisionComp", source_file="/project/module_b.py")

        registry.register(spec_a)

        with pytest.raises(RegistrationError, match="already registered"):
            registry.register(spec_b, idempotent=True)

    def test_idempotent_false_raises_on_duplicate(
        self, registry: ComponentRegistry
    ) -> None:
        """register(spec, idempotent=False) still raises on any duplicate (backward compat)."""
        spec = make_spec("BwCompatComp", source_file="/project/module.py")
        registry.register(spec)

        # Same source file, but idempotent=False (default) — should still raise
        with pytest.raises(RegistrationError, match="already registered"):
            registry.register(spec, idempotent=False)

    def test_idempotent_default_raises_on_duplicate(
        self, registry: ComponentRegistry
    ) -> None:
        """register() default behavior is unchanged — raises on any duplicate."""
        spec = make_spec("DefaultBwComp")
        registry.register(spec)

        with pytest.raises(RegistrationError, match="already registered"):
            registry.register(spec)

    def test_idempotent_true_none_source_files_treated_as_same(
        self, registry: ComponentRegistry
    ) -> None:
        """register(idempotent=True) treats both source_file=None as matching."""
        spec = make_spec("NullSourceComp", source_file=None)
        registry.register(spec)

        # Both have source_file=None — should succeed silently
        registry.register(spec, idempotent=True)
        assert registry.count() == 1


# ===========================================================================
# Register-or-Update Tests
# ===========================================================================

class TestRegisterOrUpdate:
    """Tests for register_or_update() upsert semantics."""

    def test_register_or_update_registers_new_component(
        self, registry: ComponentRegistry
    ) -> None:
        """register_or_update() registers a component that doesn't exist yet."""
        spec = make_spec("NewUpsertComp")
        result = registry.register_or_update(spec)

        assert result == spec
        assert registry.contains("NewUpsertComp")
        assert registry.count() == 1

    def test_register_or_update_updates_existing_same_source(
        self, registry: ComponentRegistry
    ) -> None:
        """register_or_update() replaces existing spec when source_file matches."""
        spec_v1 = make_spec(
            "UpdateableComp",
            source_file="/project/module.py",
            version="0.1.0",
        )
        spec_v2 = make_spec(
            "UpdateableComp",
            source_file="/project/module.py",
            version="0.2.0",
        )

        registry.register_or_update(spec_v1)
        result = registry.register_or_update(spec_v2)

        assert result == spec_v2
        assert registry.count() == 1
        retrieved = registry.get("UpdateableComp")
        assert retrieved is not None
        assert retrieved.version == "0.2.0"

    def test_register_or_update_raises_on_different_source(
        self, registry: ComponentRegistry
    ) -> None:
        """register_or_update() raises when name exists from a different source file."""
        spec_a = make_spec("CollidingComp", source_file="/project/module_a.py")
        spec_b = make_spec("CollidingComp", source_file="/project/module_b.py")

        registry.register_or_update(spec_a)

        with pytest.raises(RegistrationError, match="name collision"):
            registry.register_or_update(spec_b)

    def test_register_or_update_returns_spec(
        self, registry: ComponentRegistry
    ) -> None:
        """register_or_update() returns the registered ComponentSpec."""
        spec = make_spec("ReturnSpec")
        result = registry.register_or_update(spec)
        assert result is spec

    def test_register_or_update_persists_to_storage(
        self, tmp_path: Path
    ) -> None:
        """register_or_update() persists the component when persistence is enabled."""
        db_path = tmp_path / "test.db"
        registry = ComponentRegistry(persist=True, db_path=db_path)
        try:
            spec = make_spec("PersistUpsert", source_file="/project/mod.py")
            registry.register_or_update(spec)
            assert registry.contains("PersistUpsert")

            updated = make_spec("PersistUpsert", source_file="/project/mod.py", version="1.0.0")
            registry.register_or_update(updated)

            fresh = ComponentRegistry(persist=True, db_path=db_path)
            try:
                loaded = fresh.get("PersistUpsert")
                assert loaded is not None
                assert loaded.version == "1.0.0"
            finally:
                fresh.close()
        finally:
            registry.close()


# ---------------------------------------------------------------------------
# M15: Advanced query APIs
# ---------------------------------------------------------------------------


class TestCanonicalIdLookup:
    """Tests for get_component_by_canonical_id."""

    def test_simple_name_lookup(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = make_spec("MyNerve", module_path="signal_processor")
        registry.register(spec)

        result = registry.get_component_by_canonical_id("MyNerve")
        assert result is not None
        assert result.name == "MyNerve"

    def test_canonical_id_lookup(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = make_spec("process_signal", module_path="signal_processor")
        registry.register(spec)

        result = registry.get_component_by_canonical_id(
            "signal_processor::process_signal"
        )
        assert result is not None
        assert result.name == "process_signal"

    def test_canonical_id_not_found(self) -> None:
        registry = ComponentRegistry(persist=False)
        result = registry.get_component_by_canonical_id(
            "nonexistent::component"
        )
        assert result is None

    def test_canonical_id_wrong_module(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = make_spec("process_signal", module_path="other_module")
        registry.register(spec)

        result = registry.get_component_by_canonical_id(
            "signal_processor::process_signal"
        )
        assert result is None

    def test_canonical_id_module_suffix_match(self) -> None:
        """Module path 'myapp.signal_processor' should match canonical 'signal_processor::x'."""
        registry = ComponentRegistry(persist=False)
        spec = make_spec("process_signal", module_path="myapp.signal_processor")
        registry.register(spec)

        result = registry.get_component_by_canonical_id(
            "signal_processor::process_signal"
        )
        assert result is not None
        assert result.name == "process_signal"

    def test_canonical_id_suffix_requires_dot_boundary(self) -> None:
        """'nosignal_processor' must not satisfy 'signal_processor::x'."""
        registry = ComponentRegistry(persist=False)
        registry.register(
            make_spec("process_signal", module_path="nosignal_processor")
        )
        result = registry.get_component_by_canonical_id(
            "signal_processor::process_signal"
        )
        assert result is None

    def test_canonical_id_ambiguous_returns_none(self) -> None:
        """Multiple matches resolve to None — never an arbitrary winner."""
        registry = ComponentRegistry(persist=False)
        registry.register(make_spec("process_signal", module_path="a.dsp"))
        registry.register(
            make_spec(
                "process_signal",
                module_path="b.dsp",
                module_scoped=True,
            )
        )
        assert (
            registry.get_component_by_canonical_id("dsp::process_signal")
            is None
        )
        # The fully qualified forms stay unambiguous.
        assert (
            registry.get_component_by_canonical_id("a.dsp::process_signal")
            is not None
        )
        assert (
            registry.get_component_by_canonical_id("b.dsp::process_signal")
            is not None
        )


class TestEdgeQueries:
    """Tests for get_incoming_edges, get_outgoing_edges, get_observers."""

    def _setup_edges(self, registry: ComponentRegistry) -> None:
        registry.register_relationship(
            source="mod_a::func_a",
            target="mod_b::func_b",
            relation="CALLS",
            intent="a calls b",
            carries="request data",
            coupling="LOOSE",
            origin="authored",
        )
        registry.register_relationship(
            source="mod_c::evaluator",
            target="mod_a::func_a",
            relation="OBSERVES",
            intent="evaluator observes func_a",
            carries="metrics",
            coupling="LOOSE",
            origin="authored",
        )
        registry.register_relationship(
            source="mod_a::func_a",
            target="mod_d::exception",
            relation="RAISES",
            intent="func_a raises exception",
            carries="error info",
            coupling="TIGHT",
            origin="derived",
        )

    def test_get_outgoing_edges(self) -> None:
        registry = ComponentRegistry(persist=False)
        self._setup_edges(registry)

        outgoing = registry.get_outgoing_edges("mod_a::func_a")
        assert len(outgoing) == 2  # CALLS + RAISES
        relations = {e.relation for e in outgoing}
        assert "CALLS" in relations
        assert "RAISES" in relations

    def test_get_incoming_edges(self) -> None:
        registry = ComponentRegistry(persist=False)
        self._setup_edges(registry)

        incoming = registry.get_incoming_edges("mod_a::func_a")
        assert len(incoming) == 1
        assert incoming[0].relation == "OBSERVES"

    def test_get_observers(self) -> None:
        registry = ComponentRegistry(persist=False)
        self._setup_edges(registry)

        observers = registry.get_observers("mod_a::func_a")
        assert len(observers) == 1
        assert observers[0].source == "mod_c::evaluator"

    def test_get_observers_empty(self) -> None:
        registry = ComponentRegistry(persist=False)
        self._setup_edges(registry)

        observers = registry.get_observers("mod_b::func_b")
        assert observers == []

    def test_get_incoming_edges_target_not_in_edges(self) -> None:
        registry = ComponentRegistry(persist=False)
        result = registry.get_incoming_edges("nonexistent::comp")
        assert result == []

    def test_register_produces_relationship(self) -> None:
        registry = ComponentRegistry(persist=False)
        edge = registry.register_relationship(
            source="mod_a::service",
            target="mod_b::event",
            relation="PRODUCES",
            intent="service emits event",
            carries="OrderCreated",
        )
        assert edge.relation == "PRODUCES"
        assert edge.carries == "OrderCreated"

        edges = registry.get_edges(source="mod_a::service", relation="PRODUCES")
        assert len(edges) == 1
        assert edges[0].target == "mod_b::event"

    def test_register_consumes_relationship(self) -> None:
        registry = ComponentRegistry(persist=False)
        edge = registry.register_relationship(
            source="mod_c::handler",
            target="mod_b::event",
            relation="CONSUMES",
            intent="handler reacts to event",
            carries="OrderCreated",
        )
        assert edge.relation == "CONSUMES"

        edges = registry.get_edges(source="mod_c::handler", relation="CONSUMES")
        assert len(edges) == 1
        assert edges[0].target == "mod_b::event"

    def test_produces_consumes_in_snapshot(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register_relationship(
            source="mod_a::service",
            target="mod_b::event",
            relation="PRODUCES",
            carries="OrderCreated",
        )
        registry.register_relationship(
            source="mod_c::handler",
            target="mod_b::event",
            relation="CONSUMES",
            carries="OrderCreated",
        )
        snap = registry.snapshot()
        relations = {e.relation for e in snap.edges}
        assert "PRODUCES" in relations
        assert "CONSUMES" in relations

    def test_produces_consumes_in_to_dict(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register_relationship(
            source="mod_a::service",
            target="mod_b::event",
            relation="PRODUCES",
        )
        registry.register_relationship(
            source="mod_c::handler",
            target="mod_b::event",
            relation="CONSUMES",
        )
        d = registry.to_dict()
        edge_relations = {e["relation"] for e in d["edges"]}
        assert "PRODUCES" in edge_relations
        assert "CONSUMES" in edge_relations


class TestVerifierQueries:
    """Tests for get_verifiers."""

    def test_get_verifiers(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register_test(
            name="tests::test_func_a",
            intent="validates func_a",
            validates=["mod_a::func_a"],
        )
        registry.register_test(
            name="tests::test_func_a_edge",
            intent="edge case test for func_a",
            validates=["mod_a::func_a", "mod_b::func_b"],
        )

        verifiers = registry.get_verifiers("mod_a::func_a")
        assert len(verifiers) == 2
        names = {v.name for v in verifiers}
        assert "tests::test_func_a" in names
        assert "tests::test_func_a_edge" in names

    def test_get_verifiers_none(self) -> None:
        registry = ComponentRegistry(persist=False)
        result = registry.get_verifiers("mod_a::func_a")
        assert result == []


class TestPublicNerveCoverage:
    """Tests for get_public_nerve_coverage and get_untested_public_nerves."""

    def _setup_modules_and_tests(self, registry: ComponentRegistry) -> None:
        registry.register_module(
            name="mod_a",
            layer="APPLICATION",
            version="1.0.0",
            intent="Module A",
            exports=["func_a", "func_b"],
        )
        registry.register_module(
            name="mod_b",
            layer="DOMAIN",
            version="1.0.0",
            intent="Module B",
            exports=["func_c"],
        )
        # Only func_a has a test
        registry.register_test(
            name="tests::test_func_a",
            intent="tests func_a",
            validates=["mod_a::func_a"],
        )

    def test_coverage_map(self) -> None:
        registry = ComponentRegistry(persist=False)
        self._setup_modules_and_tests(registry)

        coverage = registry.get_public_nerve_coverage()
        assert "mod_a::func_a" in coverage
        assert len(coverage["mod_a::func_a"]) == 1
        assert "mod_a::func_b" in coverage
        assert coverage["mod_a::func_b"] == []
        assert "mod_b::func_c" in coverage
        assert coverage["mod_b::func_c"] == []

    def test_untested_public_nerves(self) -> None:
        registry = ComponentRegistry(persist=False)
        self._setup_modules_and_tests(registry)

        untested = registry.get_untested_public_nerves()
        assert "mod_a::func_b" in untested
        assert "mod_b::func_c" in untested
        assert "mod_a::func_a" not in untested

    def test_all_tested(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register_module(
            name="mod_a",
            layer="APPLICATION",
            version="1.0.0",
            intent="Module A",
            exports=["func_a"],
        )
        registry.register_test(
            name="tests::test_func_a",
            intent="tests func_a",
            validates=["mod_a::func_a"],
        )
        untested = registry.get_untested_public_nerves()
        assert untested == []

    def test_no_modules(self) -> None:
        registry = ComponentRegistry(persist=False)
        coverage = registry.get_public_nerve_coverage()
        assert coverage == {}
        untested = registry.get_untested_public_nerves()
        assert untested == []


# ===========================================================================
# IR Storage Tests
# ===========================================================================


class TestIRStorage:
    """Tests for runtime IR storage on ComponentRegistry."""

    def test_store_and_retrieve_ir(self, registry: ComponentRegistry) -> None:
        """Store IR data, retrieve by module name."""
        ir_data: dict[str, object] = {
            "module": "config",
            "nerves": [{"name": "DEFAULT_MODEL", "kind": "MODEL"}],
        }
        registry.store_ir("config", ir_data)
        result = registry.get_ir("config")
        assert result == ir_data

    def test_get_ir_returns_none_for_unknown(
        self, registry: ComponentRegistry
    ) -> None:
        """get_ir() returns None for an unregistered module."""
        assert registry.get_ir("nonexistent") is None

    def test_get_all_ir(self, registry: ComponentRegistry) -> None:
        """get_all_ir() returns all stored IR entries."""
        registry.store_ir("mod_a", {"nerves": []})
        registry.store_ir("mod_b", {"nerves": ["x"]})
        all_ir = registry.get_all_ir()
        assert "mod_a" in all_ir
        assert "mod_b" in all_ir
        assert len(all_ir) == 2

    def test_get_all_ir_returns_copy(
        self, registry: ComponentRegistry
    ) -> None:
        """get_all_ir() returns a copy, not the internal store."""
        registry.store_ir("mod_a", {"nerves": []})
        all_ir = registry.get_all_ir()
        all_ir["injected"] = {"bad": True}
        assert registry.get_ir("injected") is None

    def test_ir_included_in_to_dict(
        self, registry: ComponentRegistry
    ) -> None:
        """store_ir() data appears in to_dict() output."""
        registry.store_ir("config", {"version": "1.0"})
        d = registry.to_dict()
        assert "ir" in d
        assert "config" in d["ir"]
        assert d["ir"]["config"]["version"] == "1.0"
        assert d["summary"]["ir_count"] == 1

    def test_ir_included_in_snapshot(
        self, registry: ComponentRegistry
    ) -> None:
        """store_ir() data appears in snapshot."""
        registry.store_ir("config", {"version": "1.0"})
        snap = registry.snapshot()
        assert "config" in snap.ir
        assert snap.ir["config"]["version"] == "1.0"

    def test_reset_clears_ir(self, registry: ComponentRegistry) -> None:
        """reset() empties the IR store."""
        registry.store_ir("config", {"version": "1.0"})
        registry.reset()
        assert registry.get_all_ir() == {}
        assert registry.get_ir("config") is None

    def test_store_ir_overwrites(
        self, registry: ComponentRegistry
    ) -> None:
        """Storing IR for the same module twice keeps the latest data."""
        registry.store_ir("config", {"version": "1.0"})
        registry.store_ir("config", {"version": "2.0"})
        result = registry.get_ir("config")
        assert result is not None
        assert result["version"] == "2.0"

    def test_ir_is_json_serializable_in_to_dict(
        self, registry: ComponentRegistry
    ) -> None:
        """IR data in to_dict() can be serialized to JSON."""
        registry.store_ir("config", {"nerves": ["a", "b"], "count": 2})
        d = registry.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["ir"]["config"]["count"] == 2


class TestPluginRegistration:
    """Tests for plugin registration on ComponentRegistry."""

    def test_register_plugin_basic(
        self, registry: ComponentRegistry
    ) -> None:
        """Register a plugin and retrieve it."""
        plugin = registry.register_plugin(
            name="tool_extensions",
            version="1.0.0",
            intent="Adds tool execution capabilities",
            registers=["ToolExecutor", "ToolCache"],
        )
        assert plugin.name == "tool_extensions"
        assert plugin.version == "1.0.0"
        retrieved = registry.get_plugin("tool_extensions")
        assert retrieved is not None
        assert retrieved.name == "tool_extensions"

    def test_register_plugin_validates_core_deps(
        self, registry: ComponentRegistry
    ) -> None:
        """Plugin with unregistered requires_core raises error."""
        with pytest.raises(RegistryIntegrityError, match="requires core component"):
            registry.register_plugin(
                name="bad_plugin",
                version="1.0.0",
                intent="Should fail",
                requires_core=["NonexistentComponent"],
            )

    def test_register_plugin_core_deps_satisfied(
        self, registry: ComponentRegistry
    ) -> None:
        """Plugin succeeds when required core components exist."""
        spec = make_spec("Orchestrator")
        registry.register(spec)
        plugin = registry.register_plugin(
            name="tool_extensions",
            version="1.0.0",
            intent="Adds tool execution capabilities",
            requires_core=["Orchestrator"],
        )
        assert plugin.requires_core == ["Orchestrator"]

    def test_get_plugin_returns_none_for_unknown(
        self, registry: ComponentRegistry
    ) -> None:
        """get_plugin() returns None for unregistered plugin."""
        assert registry.get_plugin("nonexistent") is None

    def test_get_all_plugins(
        self, registry: ComponentRegistry
    ) -> None:
        """get_all_plugins() returns all registered plugins."""
        registry.register_plugin(
            name="plugin_a",
            version="1.0.0",
            intent="Plugin A",
        )
        registry.register_plugin(
            name="plugin_b",
            version="2.0.0",
            intent="Plugin B",
        )
        all_plugins = registry.get_all_plugins()
        assert len(all_plugins) == 2
        assert "plugin_a" in all_plugins
        assert "plugin_b" in all_plugins

    def test_plugin_in_to_dict(
        self, registry: ComponentRegistry
    ) -> None:
        """Registered plugin appears in to_dict() output."""
        registry.register_plugin(
            name="tool_extensions",
            version="1.0.0",
            intent="Adds tool execution capabilities",
            registers=["ToolExecutor"],
        )
        d = registry.to_dict()
        assert "plugins" in d
        assert "tool_extensions" in d["plugins"]
        assert d["plugins"]["tool_extensions"]["version"] == "1.0.0"
        assert d["summary"]["plugin_count"] == 1

    def test_plugin_in_snapshot(
        self, registry: ComponentRegistry
    ) -> None:
        """Registered plugin appears in snapshot."""
        registry.register_plugin(
            name="tool_extensions",
            version="1.0.0",
            intent="Adds tool execution capabilities",
        )
        snap = registry.snapshot()
        assert "tool_extensions" in snap.plugins
        assert snap.plugins["tool_extensions"].version == "1.0.0"

    def test_reset_clears_plugins(
        self, registry: ComponentRegistry
    ) -> None:
        """reset() empties the plugin store."""
        registry.register_plugin(
            name="tool_extensions",
            version="1.0.0",
            intent="Adds tool execution capabilities",
        )
        registry.reset()
        assert registry.get_all_plugins() == {}
        assert registry.get_plugin("tool_extensions") is None

    def test_plugin_describe_output(
        self, registry: ComponentRegistry
    ) -> None:
        """Plugin info appears in snapshot describe() output."""
        spec = make_spec("Orchestrator")
        registry.register(spec)
        registry.register_plugin(
            name="tool_extensions",
            version="1.0.0",
            intent="Adds tool execution capabilities",
            registers=["ToolExecutor", "ToolCache"],
            requires_core=["Orchestrator"],
        )
        snap = registry.snapshot()
        desc = snap.describe()
        assert "PLUGINS" in desc
        assert "tool_extensions v1.0.0" in desc
        assert "registers: [ToolExecutor, ToolCache]" in desc
        assert "requires: [Orchestrator]" in desc

    def test_plugin_to_dict_is_json_serializable(
        self, registry: ComponentRegistry
    ) -> None:
        """Plugin data in to_dict() survives JSON round-trip."""
        registry.register_plugin(
            name="tool_extensions",
            version="1.0.0",
            intent="Adds tool execution capabilities",
            registers=["ToolExecutor"],
            source_file="plugins/tools.py",
        )
        d = registry.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["plugins"]["tool_extensions"]["version"] == "1.0.0"

    def test_plugin_overwrites_on_reregister(
        self, registry: ComponentRegistry
    ) -> None:
        """Re-registering same plugin name keeps latest data."""
        registry.register_plugin(
            name="my_plugin",
            version="1.0.0",
            intent="Version one",
        )
        registry.register_plugin(
            name="my_plugin",
            version="2.0.0",
            intent="Version two",
        )
        plugin = registry.get_plugin("my_plugin")
        assert plugin is not None
        assert plugin.version == "2.0.0"
        assert plugin.intent == "Version two"


# ===========================================================================
# Adopted-file registration tests (0.11.0, batch-01a D2)
# ===========================================================================

class TestAdoptedFiles:
    """``register_adopted_file`` — the per-file adoption primitive.

    Adoption makes real (non-generated) files first-class in the
    self-model: registered by path, verified by content hash, counted
    in registration ratios. These tests pin the registry store, the
    snapshot/to_dict/describe surfaces, SQLite persistence, and reset.
    """

    @pytest.mark.parametrize("description", ["", "   "])
    def test_description_is_mandatory_end_to_end(
        self, registry: ComponentRegistry, description: str
    ) -> None:
        with pytest.raises(ValueError, match="description is required"):
            registry.register_adopted_file(
                path="src/legacy_impl.py",
                content_hash="sha256:aa",
                description=description,
            )

    def test_register_and_retrieve(self, registry: ComponentRegistry) -> None:
        record = registry.register_adopted_file(
            path="src/legacy_impl.py",
            content_hash="sha256:" + "ab" * 32,
            description="Hand-written implementation adopted as-is",
        )
        assert record.path == "src/legacy_impl.py"
        assert record.content_hash == "sha256:" + "ab" * 32
        stored = registry.get_adopted_file("src/legacy_impl.py")
        assert stored is not None
        assert stored.description == "Hand-written implementation adopted as-is"
        assert registry.get_all_adopted_files() == {"src/legacy_impl.py": stored}

    def test_reregister_replaces_previous_entry(
        self, registry: ComponentRegistry
    ) -> None:
        """Idempotent re-adoption: the latest hash wins (the re-adopt path)."""
        registry.register_adopted_file(
            path="src/legacy_impl.py", content_hash="sha256:old",
            description="Legacy implementation",
        )
        registry.register_adopted_file(
            path="src/legacy_impl.py", content_hash="sha256:new",
            description="Legacy implementation",
            re_adopt_count=1,
        )
        stored = registry.get_adopted_file("src/legacy_impl.py")
        assert stored is not None
        assert stored.content_hash == "sha256:new"
        assert len(registry.get_all_adopted_files()) == 1

    def test_metadata_is_copied_not_aliased(
        self, registry: ComponentRegistry
    ) -> None:
        facts: dict[str, object] = {"adopt_source": "bench P2_P_r02"}
        record = registry.register_adopted_file(
            path="a.py", content_hash="sha256:aa", description="Legacy A",
            metadata=facts,
        )
        facts["adopt_source"] = "mutated"
        assert record.metadata == {"adopt_source": "bench P2_P_r02"}

    def test_snapshot_carries_adopted_files(
        self, registry: ComponentRegistry
    ) -> None:
        registry.register_adopted_file(
            path="src/legacy_impl.py", content_hash="sha256:aa",
            description="Legacy implementation",
        )
        snapshot = registry.snapshot()
        assert "src/legacy_impl.py" in snapshot.adopted_files
        assert (
            snapshot.adopted_files["src/legacy_impl.py"].content_hash
            == "sha256:aa"
        )

    def test_snapshot_to_dict_omits_key_when_empty(
        self, registry: ComponentRegistry
    ) -> None:
        """Additive-compat policy: no new key until adoption is in use."""
        assert "adopted_files" not in registry.snapshot().to_dict()
        registry.register_adopted_file(
            path="a.py", content_hash="sha256:aa", description="Legacy A"
        )
        payload = registry.snapshot().to_dict()
        assert payload["adopted_files"] == {
            "a.py": {
                "path": "a.py",
                "content_hash": "sha256:aa",
                "description": "Legacy A",
                "re_adopt_count": 0,
                "metadata": {},
            }
        }
        # The whole payload stays JSON-serializable.
        json.dumps(payload)

    def test_registry_to_dict_counts_adopted_files(
        self, registry: ComponentRegistry
    ) -> None:
        registry.register_adopted_file(
            path="a.py", content_hash="sha256:aa", description="Legacy A"
        )
        payload = registry.to_dict()
        assert payload["adopted_files"] == {
            "a.py": {
                "path": "a.py",
                "content_hash": "sha256:aa",
                "description": "Legacy A",
                "re_adopt_count": 0,
                "metadata": {},
            }
        }
        summary = payload["summary"]
        assert isinstance(summary, dict)
        assert summary["adopted_file_count"] == 1

    def test_describe_lists_adopted_files_with_hashes(
        self, registry: ComponentRegistry
    ) -> None:
        registry.register_adopted_file(
            path="src/legacy_impl.py",
            content_hash="sha256:feed",
            description="adopted helper",
        )
        described = registry.snapshot().describe()
        assert "ADOPTED FILES" in described
        assert "src/legacy_impl.py (sha256:feed)" in described
        assert "adopted helper" in described

    def test_describe_omits_section_when_empty(
        self, registry: ComponentRegistry
    ) -> None:
        assert "ADOPTED FILES" not in registry.snapshot().describe()

    def test_persistence_round_trip(self, tmp_path: Path) -> None:
        """Adopted records survive process restart via SQLite."""
        db_path = tmp_path / "adopted_test.db"
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        try:
            reg1.register_adopted_file(
                path="src/legacy_impl.py",
                content_hash="sha256:cafe",
                description="persisted record",
                metadata={"origin": "test"},
            )
        finally:
            reg1.close()

        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        try:
            stored = reg2.get_adopted_file("src/legacy_impl.py")
            assert stored is not None
            assert stored.content_hash == "sha256:cafe"
            assert stored.description == "persisted record"
            assert stored.metadata == {"origin": "test"}
        finally:
            reg2.close()

    def test_reset_clears_adopted_files(
        self, registry: ComponentRegistry
    ) -> None:
        registry.register_adopted_file(
            path="a.py", content_hash="sha256:aa", description="Legacy A"
        )
        registry.reset()
        assert registry.get_all_adopted_files() == {}
        assert registry.get_adopted_file("a.py") is None


class TestGlobalRegistryKnowsTheFramework:
    """The singleton registers s0ma's own components as it is created.

    A ``@component`` that runs before ``s0ma.initialize()`` — at import
    time, or in a toolchain process that never initializes — used to
    register against an empty singleton, so a declared dependency on a
    framework component was logged as "not yet registered".
    """

    def test_fresh_singleton_holds_the_framework(self) -> None:
        from s0ma._bootstrap import EXPECTED_FRAMEWORK_COMPONENT_COUNT

        reset_registry()
        reg = get_registry(persist=False)
        assert reg.count() == EXPECTED_FRAMEWORK_COMPONENT_COUNT
        assert reg.contains("ComponentRegistry")
        assert reg.contains("ComponentSpec")

    def test_a_dependency_on_the_framework_resolves_before_initialize(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        reset_registry()
        reg = get_registry(persist=False)
        with caplog.at_level(logging.WARNING, logger="s0ma"):
            reg.register(ComponentSpec(
                name="EarlyRiser",
                kind=ComponentKind.SERVICE,
                layer=Layer.APPLICATION,
                intent="Registers before initialize and leans on a framework part",
                dependencies=["ComponentSpec"],
            ))
        assert "not yet registered" not in caplog.text

    def test_initialize_is_idempotent_over_the_bootstrapped_singleton(self) -> None:
        from s0ma import initialize
        from s0ma._bootstrap import EXPECTED_FRAMEWORK_COMPONENT_COUNT

        reset_registry()
        first = get_registry(persist=False)
        second = initialize(persist=False)
        assert second is first
        assert second.count() == EXPECTED_FRAMEWORK_COMPONENT_COUNT
