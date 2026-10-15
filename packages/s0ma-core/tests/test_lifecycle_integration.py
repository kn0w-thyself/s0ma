"""End-to-end integration tests for lifecycle management.

Milestone 6 (Phase 2.5): Verifies that the full lifecycle pipeline
(create, read, update, delete) works correctly with the registry,
verification engine, persistence, and bootstrap infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from s0ma._bootstrap import bootstrap_register
from s0ma.exceptions import LifecycleError
from s0ma.lifecycle import LifecycleManager
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer, LifecycleAction

if TYPE_CHECKING:
    from pathlib import Path


# -- Helpers ---------------------------------------------------------------

def _make_spec(name: str, **overrides: object) -> ComponentSpec:
    """Create a minimal ComponentSpec for integration tests."""
    defaults = {
        "name": name,
        "kind": ComponentKind.FUNCTION,
        "layer": Layer.DOMAIN,
        "intent": f"Integration test component {name}",
        "module_path": f"test_module.{name.lower()}",
        "qualified_name": f"test_module.{name.lower()}.{name}",
    }
    defaults.update(overrides)
    return ComponentSpec(**defaults)  # type: ignore[arg-type]


def _make_source(class_name: str) -> str:
    """Create minimal Python source for a runtime component."""
    return f'class {class_name}:\n    """Test class."""\n    pass\n'


# -- Fixtures --------------------------------------------------------------

@pytest.fixture()
def registry() -> ComponentRegistry:
    return ComponentRegistry(persist=False)


@pytest.fixture()
def lm(registry: ComponentRegistry) -> LifecycleManager:
    return LifecycleManager(registry, verify_after=False)


# -- Tests: Full CRUD Cycle ------------------------------------------------

class TestLifecycleIntegration:
    """End-to-end lifecycle integration tests."""

    def test_full_crud_cycle(
        self, lm: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Create -> Read -> Update -> Delete lifecycle on one component."""
        # Create
        source = _make_source("CrudTest")
        spec = _make_spec("CrudTest")
        lm.create_component_at_runtime(source, spec, target_dir=tmp_path)

        # Read
        retrieved = lm.registry.get("CrudTest")
        assert retrieved is not None
        assert retrieved.name == "CrudTest"

        # Update
        updated = lm.update_component(
            "CrudTest", intent="Updated integration test component for CRUD",
        )
        assert "Updated" in updated.intent

        # Delete
        removed = lm.remove_component("CrudTest")
        assert removed.name == "CrudTest"
        assert not lm.registry.contains("CrudTest")

    def test_create_update_remove_with_transactions(
        self, lm: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Full lifecycle within a single transaction."""
        # Pre-register a component to update and another to remove
        lm.registry.register(_make_spec("TxnUpdate"))
        lm.registry.register(_make_spec("TxnRemove"))

        with lm.transaction() as txn:
            # Create
            txn.create_component(
                _make_source("TxnCreate"),
                _make_spec("TxnCreate"),
                target_dir=tmp_path,
            )
            # Update
            txn.update_component(
                "TxnUpdate",
                intent="Transactional update to this component's intent",
            )
            # Remove
            txn.remove_component("TxnRemove")

        assert txn.committed
        assert not txn.rolled_back
        assert lm.registry.contains("TxnCreate")
        assert lm.registry.contains("TxnUpdate")
        assert not lm.registry.contains("TxnRemove")

        # Verify the update actually applied
        updated = lm.registry.get("TxnUpdate")
        assert updated is not None
        assert "Transactional" in updated.intent

    def test_lifecycle_with_verification(
        self, tmp_path: Path,
    ) -> None:
        """Lifecycle operations with verification enabled produce events."""
        registry = ComponentRegistry(persist=False)
        lm = LifecycleManager(registry, verify_after=True)

        # Register a component to update — use a real module path so
        # the verifier can find it
        spec = _make_spec(
            "VerifyComp",
            module_path="s0ma.models",
            qualified_name="s0ma.models.ComponentSpec",
        )
        registry.register(spec)

        # Update should pass verification (component exists)
        updated = lm.update_component(
            "VerifyComp",
            intent="Updated intent for verification integration test",
        )
        assert "Updated" in updated.intent

    def test_lifecycle_events_audit_trail(
        self, lm: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Full lifecycle produces a complete event log."""
        # Create
        lm.create_component_at_runtime(
            _make_source("AuditComp"),
            _make_spec("AuditComp"),
            target_dir=tmp_path,
        )
        # Update
        lm.update_component(
            "AuditComp",
            intent="Updated audit trail test component for verification",
        )
        # Remove
        lm.remove_component("AuditComp")

        events = lm.events
        assert len(events) == 3

        # Verify event actions in order
        assert events[0].action == LifecycleAction.CREATE_RUNTIME
        assert events[0].success is True
        assert events[0].component_name == "AuditComp"

        assert events[1].action == LifecycleAction.UPDATE
        assert events[1].success is True

        assert events[2].action == LifecycleAction.UNREGISTER
        assert events[2].success is True

    def test_lifecycle_with_dependencies(
        self, lm: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Create A, create B depending on A, verify, remove B, remove A."""
        # Create A (no dependencies)
        lm.create_component_at_runtime(
            _make_source("DepA"),
            _make_spec("DepA"),
            target_dir=tmp_path / "dep_a",
        )
        assert lm.registry.contains("DepA")

        # Create B depending on A
        lm.create_component_at_runtime(
            _make_source("DepB"),
            _make_spec("DepB", dependencies=["DepA"]),
            target_dir=tmp_path / "dep_b",
        )
        assert lm.registry.contains("DepB")

        # Verify dependency is recorded
        spec_b = lm.registry.get("DepB")
        assert spec_b is not None
        assert "DepA" in spec_b.dependencies

        # Remove B first (no dependents)
        lm.remove_component("DepB")
        assert not lm.registry.contains("DepB")

        # Remove A (no dependents after B removed)
        lm.remove_component("DepA")
        assert not lm.registry.contains("DepA")

    def test_lifecycle_rollback_preserves_existing_components(
        self, lm: LifecycleManager,
    ) -> None:
        """A failed creation doesn't affect pre-existing components."""
        # Register an existing component
        lm.registry.register(_make_spec("Existing"))
        assert lm.registry.count() == 1

        # Try to create a component with a missing dependency (should fail)
        bad_spec = _make_spec("BadComp", dependencies=["NonExistent"])
        with pytest.raises(LifecycleError, match="NonExistent"):
            lm.create_component_at_runtime(
                _make_source("BadComp"), bad_spec,
            )

        # Existing component is untouched
        assert lm.registry.count() == 1
        assert lm.registry.contains("Existing")
        existing = lm.registry.get("Existing")
        assert existing is not None
        assert existing.name == "Existing"

    def test_bootstrap_test_still_passes(self) -> None:
        """After lifecycle operations, bootstrap verification passes."""
        from s0ma._bootstrap import EXPECTED_FRAMEWORK_COMPONENT_COUNT

        registry = ComponentRegistry(persist=False)
        bootstrap_register(registry)

        assert registry.count() == EXPECTED_FRAMEWORK_COMPONENT_COUNT

        # Run lifecycle operations on the bootstrapped registry
        lm = LifecycleManager(registry, verify_after=False)
        lm.registry.register(_make_spec("TempComp"))
        lm.remove_component("TempComp")

        # Framework components are still intact
        assert registry.count() == EXPECTED_FRAMEWORK_COMPONENT_COUNT

    def test_self_model_test_passes_with_lifecycle_components(self) -> None:
        """verify_all() passes with lifecycle components registered."""
        from s0ma.verifiers import verify_all

        registry = ComponentRegistry(persist=False)
        bootstrap_register(registry)

        report = verify_all(registry)
        assert report.passed, (
            f"Self-model verification failed after bootstrap:\n"
            f"{report.describe()}"
        )

    def test_snapshot_reflects_lifecycle_state(
        self, lm: LifecycleManager, tmp_path: Path,
    ) -> None:
        """snapshot().describe() includes lifecycle-created components."""
        # Create a component
        lm.create_component_at_runtime(
            _make_source("SnapComp"),
            _make_spec("SnapComp"),
            target_dir=tmp_path,
        )

        snapshot = lm.registry.snapshot()
        assert snapshot.component_count == 1
        assert "SnapComp" in snapshot.components

        description = snapshot.describe()
        assert "SnapComp" in description

    def test_persistence_survives_lifecycle_operations(
        self, tmp_path: Path,
    ) -> None:
        """SQLite persistence reflects create/update/remove operations."""
        db_path = tmp_path / "lifecycle_test.db"

        # Phase 1: Create and update with persistence
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        lm1 = LifecycleManager(reg1, verify_after=False)

        reg1.register(_make_spec("PersistComp"))
        lm1.update_component(
            "PersistComp",
            intent="Persisted lifecycle test component updated intent",
        )
        reg1.close()

        # Phase 2: New registry reads from same DB
        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        assert reg2.contains("PersistComp")
        spec = reg2.get("PersistComp")
        assert spec is not None
        assert "Persisted" in spec.intent

        # Phase 3: Remove and verify persistence
        lm2 = LifecycleManager(reg2, verify_after=False)
        lm2.remove_component("PersistComp")
        reg2.close()

        # Phase 4: Verify removal persisted
        reg3 = ComponentRegistry(persist=True, db_path=db_path)
        assert not reg3.contains("PersistComp")
        reg3.close()

    def test_transaction_rollback_on_failure(
        self, lm: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Transaction rolls back all operations when one fails."""
        # Register a component to update
        lm.registry.register(_make_spec("RollbackComp"))
        original = lm.registry.get("RollbackComp")
        assert original is not None

        with pytest.raises(Exception), lm.transaction() as txn:  # noqa: B017
                # This succeeds
                txn.update_component(
                    "RollbackComp",
                    intent="This update should be rolled back on failure",
                )
                # This fails (missing dependency)
                txn.create_component(
                    _make_source("FailComp"),
                    _make_spec("FailComp", dependencies=["NonExistent"]),
                    target_dir=tmp_path,
                )

        # The update should be rolled back
        assert txn.rolled_back
        assert not txn.committed
        restored = lm.registry.get("RollbackComp")
        assert restored is not None
        assert restored.intent == original.intent
        assert not lm.registry.contains("FailComp")
