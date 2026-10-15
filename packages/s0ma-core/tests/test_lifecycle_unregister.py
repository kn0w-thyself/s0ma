"""Tests for ComponentRegistry.unregister() — Phase 2.5, Milestone 1.

Tests the fundamental mutation operation: removing a single component
from the registry. Covers basic removal, dependency validation,
persistence, re-registration, and thread safety.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import pytest

from s0ma.exceptions import LifecycleError, RegistryIntegrityError
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from pathlib import Path


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


class TestUnregisterBasic:
    """Basic unregister operations."""

    def test_unregister_standalone_component(
        self, registry: ComponentRegistry
    ) -> None:
        """Unregister a component with no dependents."""
        spec = make_spec("Standalone")
        registry.register(spec)
        assert registry.contains("Standalone")

        registry.unregister("Standalone")
        assert not registry.contains("Standalone")

    def test_unregister_returns_removed_spec(
        self, registry: ComponentRegistry
    ) -> None:
        """unregister() returns the ComponentSpec that was removed."""
        spec = make_spec("ReturnTest")
        registry.register(spec)

        removed = registry.unregister("ReturnTest")
        assert removed.name == "ReturnTest"
        assert removed.kind == spec.kind
        assert removed.layer == spec.layer
        assert removed.intent == spec.intent

    def test_unregister_removes_from_contains(
        self, registry: ComponentRegistry
    ) -> None:
        """After unregister, contains() returns False."""
        spec = make_spec("ContainsTest")
        registry.register(spec)
        assert registry.contains("ContainsTest")

        registry.unregister("ContainsTest")
        assert not registry.contains("ContainsTest")

    def test_unregister_decrements_count(
        self, registry: ComponentRegistry
    ) -> None:
        """count() decreases by 1 after unregister."""
        specs = [make_spec(f"Comp{i}") for i in range(3)]
        for s in specs:
            registry.register(s)
        assert registry.count() == 3

        registry.unregister("Comp1")
        assert registry.count() == 2

    def test_unregister_removes_from_get_all(
        self, registry: ComponentRegistry
    ) -> None:
        """get_all() no longer includes the removed component."""
        specs = [make_spec(f"Comp{i}") for i in range(3)]
        for s in specs:
            registry.register(s)

        registry.unregister("Comp1")
        all_components = registry.get_all()
        assert "Comp1" not in all_components
        assert "Comp0" in all_components
        assert "Comp2" in all_components

    def test_unregister_removes_from_snapshot(
        self, registry: ComponentRegistry
    ) -> None:
        """snapshot() reflects the removal."""
        spec = make_spec("SnapshotTest")
        registry.register(spec)
        registry.unregister("SnapshotTest")

        snapshot = registry.snapshot()
        assert "SnapshotTest" not in snapshot.components
        assert snapshot.component_count == 0

    def test_unregister_removes_from_dependency_graph(
        self, registry: ComponentRegistry
    ) -> None:
        """get_dependency_graph() no longer includes the removed component as a key."""
        spec = make_spec("GraphTest")
        registry.register(spec)
        registry.unregister("GraphTest")

        graph = registry.get_dependency_graph()
        assert "GraphTest" not in graph

    def test_unregister_get_returns_none(
        self, registry: ComponentRegistry
    ) -> None:
        """After unregister, get() returns None for the removed component."""
        spec = make_spec("GetTest")
        registry.register(spec)
        registry.unregister("GetTest")

        assert registry.get("GetTest") is None


class TestUnregisterValidation:
    """Validation and error handling for unregister."""

    def test_unregister_nonexistent_raises(
        self, registry: ComponentRegistry
    ) -> None:
        """Attempting to unregister a non-existent component raises RegistryIntegrityError."""
        with pytest.raises(RegistryIntegrityError, match="not registered"):
            registry.unregister("DoesNotExist")

    def test_unregister_nonexistent_error_message(
        self, registry: ComponentRegistry
    ) -> None:
        """Error message includes the component name and lists registered components."""
        spec = make_spec("ExistingComp")
        registry.register(spec)

        with pytest.raises(RegistryIntegrityError) as exc_info:
            registry.unregister("Missing")

        error_msg = str(exc_info.value)
        assert "Missing" in error_msg
        assert "ExistingComp" in error_msg

    def test_unregister_with_dependents_raises(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """Unregistering a component with dependents raises LifecycleError."""
        # UserService depends on DatabaseAdapter — can't remove DatabaseAdapter
        with pytest.raises(LifecycleError, match="depend on it"):
            populated_registry.unregister("DatabaseAdapter")

    def test_unregister_dependents_error_lists_names(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """LifecycleError message lists the dependent component names."""
        with pytest.raises(LifecycleError) as exc_info:
            populated_registry.unregister("DatabaseAdapter")

        error_msg = str(exc_info.value)
        assert "UserService" in error_msg

    def test_unregister_blocked_by_qualified_dependent(
        self, registry: ComponentRegistry
    ) -> None:
        """A dependent claiming the qualified ``module::name`` form still
        protects its dependency from unregistration."""
        registry.register(
            make_spec("LightReading", module_path="reading_models")
        )
        registry.register(
            make_spec(
                "read_light",
                dependencies=["reading_models::LightReading"],
            )
        )
        with pytest.raises(LifecycleError, match="read_light"):
            registry.unregister("LightReading")
        # force=True still bypasses the guard.
        registry.unregister("LightReading", force=True)
        assert not registry.contains("LightReading")

    def test_unregister_with_dependents_force(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """force=True bypasses dependency check."""
        # Should succeed despite UserService depending on DatabaseAdapter
        populated_registry.unregister("DatabaseAdapter", force=True)
        assert not populated_registry.contains("DatabaseAdapter")
        # UserService is still registered (orphaned dependency)
        assert populated_registry.contains("UserService")

    def test_unregister_force_returns_spec(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """force=True still returns the removed spec."""
        removed = populated_registry.unregister("DatabaseAdapter", force=True)
        assert removed.name == "DatabaseAdapter"
        assert removed.kind == ComponentKind.ADAPTER

    def test_unregister_component_with_no_dependents_no_force_needed(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """A component with no dependents can be unregistered without force."""
        # UserModel has no dependents
        populated_registry.unregister("UserModel")
        assert not populated_registry.contains("UserModel")

    def test_unregister_preserves_other_components(
        self, populated_registry: ComponentRegistry
    ) -> None:
        """Unregistering one component does not affect others."""
        populated_registry.unregister("UserModel")
        assert populated_registry.contains("DatabaseAdapter")
        assert populated_registry.contains("UserService")
        assert populated_registry.count() == 2


class TestUnregisterPersistence:
    """SQLite persistence for unregister."""

    def test_unregister_removes_from_sqlite(
        self, tmp_path: Path
    ) -> None:
        """After unregister, component is gone from SQLite."""
        db_path = tmp_path / "test_persist.db"
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        spec = make_spec("PersistTest")
        reg1.register(spec)
        reg1.unregister("PersistTest")
        reg1.close()

        # Create a new registry from the same database
        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        assert not reg2.contains("PersistTest")
        assert reg2.count() == 0
        reg2.close()

    def test_unregister_other_components_survive_in_sqlite(
        self, tmp_path: Path
    ) -> None:
        """Other components remain in SQLite after one is unregistered."""
        db_path = tmp_path / "test_persist2.db"
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        spec_a = make_spec("CompA")
        spec_b = make_spec("CompB")
        reg1.register(spec_a)
        reg1.register(spec_b)
        reg1.unregister("CompA")
        reg1.close()

        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        assert not reg2.contains("CompA")
        assert reg2.contains("CompB")
        reg2.close()

    def test_unregister_no_persist_mode(
        self, registry: ComponentRegistry
    ) -> None:
        """Unregister works when persistence is disabled (no SQLite)."""
        spec = make_spec("NoPersist")
        registry.register(spec)
        removed = registry.unregister("NoPersist")
        assert removed.name == "NoPersist"
        assert not registry.contains("NoPersist")


class TestUnregisterReregistration:
    """Re-registration after unregister."""

    def test_reregister_after_unregister(
        self, registry: ComponentRegistry
    ) -> None:
        """A name can be re-registered after unregister."""
        spec = make_spec("Reusable")
        registry.register(spec)
        registry.unregister("Reusable")

        # Re-register with the same spec
        registry.register(spec)
        assert registry.contains("Reusable")
        assert registry.get("Reusable") is not None

    def test_reregister_with_different_spec(
        self, registry: ComponentRegistry
    ) -> None:
        """Re-registration can use a different spec for the same name."""
        spec_v1 = make_spec("Evolving", intent="Original intent for testing purposes")
        registry.register(spec_v1)
        registry.unregister("Evolving")

        spec_v2 = make_spec(
            "Evolving",
            intent="Updated intent with new functionality and features",
            kind=ComponentKind.FUNCTION,
        )
        registry.register(spec_v2)

        retrieved = registry.get("Evolving")
        assert retrieved is not None
        assert retrieved.intent == "Updated intent with new functionality and features"
        assert retrieved.kind == ComponentKind.FUNCTION


class TestUnregisterThreadSafety:
    """Thread safety for unregister."""

    def test_concurrent_unregister(self, registry: ComponentRegistry) -> None:
        """Unregistering different components concurrently doesn't corrupt registry."""
        # Register 20 components
        for i in range(20):
            registry.register(make_spec(f"ThreadComp{i}"))
        assert registry.count() == 20

        # Unregister 10 from 5 threads (2 per thread)
        targets = [f"ThreadComp{i}" for i in range(10)]

        def unregister_batch(names: list[str]) -> list[str]:
            removed = []
            for n in names:
                registry.unregister(n)
                removed.append(n)
            return removed

        # Split targets into 5 batches of 2
        batches = [targets[i : i + 2] for i in range(0, 10, 2)]

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(unregister_batch, batch) for batch in batches]
            for future in as_completed(futures):
                future.result()  # Raise if any thread failed

        # Verify 10 remain
        assert registry.count() == 10
        for i in range(10):
            assert not registry.contains(f"ThreadComp{i}")
        for i in range(10, 20):
            assert registry.contains(f"ThreadComp{i}")

    def test_concurrent_register_and_unregister(
        self, registry: ComponentRegistry
    ) -> None:
        """Concurrent register and unregister operations don't corrupt state."""
        # Pre-register components that will be unregistered
        for i in range(10):
            registry.register(make_spec(f"ToRemove{i}"))

        def register_batch(start: int) -> None:
            for i in range(start, start + 5):
                registry.register(make_spec(f"ToAdd{i}"))

        def unregister_batch(start: int) -> None:
            for i in range(start, start + 5):
                registry.unregister(f"ToRemove{i}")

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(register_batch, 0),
                executor.submit(register_batch, 5),
                executor.submit(unregister_batch, 0),
                executor.submit(unregister_batch, 5),
            ]
            for future in as_completed(futures):
                future.result()

        # All ToRemove should be gone, all ToAdd should exist
        for i in range(10):
            assert not registry.contains(f"ToRemove{i}")
            assert registry.contains(f"ToAdd{i}")
        assert registry.count() == 10
