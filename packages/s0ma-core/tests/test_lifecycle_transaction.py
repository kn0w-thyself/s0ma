"""Tests for transactional lifecycle operations.

Phase 2.5, Milestone 5 — TransactionContext wraps multiple lifecycle
operations with automatic rollback on failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from s0ma.exceptions import (
    RegistryIntegrityError,
    TransactionError,
)
from s0ma.lifecycle import LifecycleManager, TransactionContext
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer, LifecycleAction

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


SIMPLE_SOURCE_A = '''\
"""Service A for transaction testing."""


class ServiceA:
    """A simple service."""

    def run(self) -> str:
        return "A"
'''

SIMPLE_SOURCE_B = '''\
"""Service B for transaction testing."""


class ServiceB:
    """Another simple service."""

    def run(self) -> str:
        return "B"
'''


@pytest.fixture()
def registry() -> ComponentRegistry:
    """A fresh in-memory registry with no persistence."""
    return ComponentRegistry(persist=False)


@pytest.fixture()
def lifecycle_manager(registry: ComponentRegistry) -> LifecycleManager:
    """A LifecycleManager with verification disabled for testing."""
    return LifecycleManager(registry, verify_after=False)


# ======================================================================
# Successful transaction (commit) scenarios
# ======================================================================


class TestTransactionCommit:
    """Successful transaction scenarios."""

    def test_single_create_commits(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """A transaction with one create operation commits on exit."""
        spec = make_spec("ServiceA")
        with lifecycle_manager.transaction() as txn:
            txn.create_component(SIMPLE_SOURCE_A, spec, target_dir=tmp_path)

        assert registry.contains("ServiceA")
        assert txn.committed
        assert not txn.rolled_back

    def test_single_update_commits(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """A transaction with one update operation commits on exit."""
        spec = make_spec("Updatable")
        registry.register(spec)

        with lifecycle_manager.transaction() as txn:
            txn.update_component(
                "Updatable", intent="Updated intent via transaction context"
            )

        retrieved = registry.get("Updatable")
        assert retrieved is not None
        assert retrieved.intent == "Updated intent via transaction context"
        assert txn.committed

    def test_single_remove_commits(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """A transaction with one remove operation commits on exit."""
        spec = make_spec("Removable")
        registry.register(spec)

        with lifecycle_manager.transaction() as txn:
            txn.remove_component("Removable")

        assert not registry.contains("Removable")
        assert txn.committed

    def test_multiple_operations_commit(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """A transaction with create + update + remove commits all."""
        # Pre-register components for update and remove
        update_spec = make_spec("ForUpdate")
        remove_spec = make_spec("ForRemoval")
        registry.register(update_spec)
        registry.register(remove_spec)

        spec_a = make_spec("ServiceA")

        with lifecycle_manager.transaction() as txn:
            txn.create_component(SIMPLE_SOURCE_A, spec_a, target_dir=tmp_path)
            txn.update_component(
                "ForUpdate", intent="Updated intent within transaction here"
            )
            txn.remove_component("ForRemoval")

        # All changes should be visible
        assert registry.contains("ServiceA")
        retrieved = registry.get("ForUpdate")
        assert retrieved is not None
        assert retrieved.intent == "Updated intent within transaction here"
        assert not registry.contains("ForRemoval")
        assert txn.committed

    def test_committed_changes_visible(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """After transaction, all changes are visible in registry."""
        spec = make_spec("NewService")

        with lifecycle_manager.transaction() as txn:
            txn.create_component(SIMPLE_SOURCE_A, spec, target_dir=tmp_path)

        # Should be queryable through normal registry API
        assert registry.count() >= 1
        all_components = registry.get_all()
        assert "NewService" in all_components

    def test_operations_property_tracks_events(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """txn.operations lists all events in order."""
        update_spec = make_spec("ForUpdate")
        registry.register(update_spec)

        spec_a = make_spec("ServiceA")

        with lifecycle_manager.transaction() as txn:
            txn.create_component(SIMPLE_SOURCE_A, spec_a, target_dir=tmp_path)
            txn.update_component(
                "ForUpdate", intent="Updated intent for events tracking test"
            )

        events = txn.operations
        assert len(events) == 2
        assert events[0].action == LifecycleAction.CREATE_RUNTIME
        assert events[0].component_name == "ServiceA"
        assert events[1].action == LifecycleAction.UPDATE
        assert events[1].component_name == "ForUpdate"


# ======================================================================
# Rollback scenarios
# ======================================================================


class TestTransactionRollback:
    """Rollback scenarios."""

    def test_exception_triggers_rollback(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """An exception inside the transaction rolls back all operations."""
        spec_a = make_spec("ServiceA")

        with (
            pytest.raises(ValueError, match="deliberate"),
            lifecycle_manager.transaction() as txn,
        ):
            txn.create_component(
                SIMPLE_SOURCE_A, spec_a, target_dir=tmp_path,
            )
            raise ValueError("deliberate failure")

        # ServiceA should have been rolled back
        assert not registry.contains("ServiceA")
        assert txn.rolled_back
        assert not txn.committed

    def test_rollback_restores_registry(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """After rollback, registry matches pre-transaction state."""
        spec = make_spec("Existing")
        registry.register(spec)
        original_intent = spec.intent
        count_before = registry.count()

        with (
            pytest.raises(ValueError, match="boom"),
            lifecycle_manager.transaction() as txn,
        ):
            txn.update_component(
                "Existing",
                intent="This intent should be rolled back completely",
            )
            raise ValueError("boom")

        # Registry should be restored
        assert registry.count() == count_before
        restored = registry.get("Existing")
        assert restored is not None
        assert restored.intent == original_intent

    def test_rollback_removes_created_files(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """Files created during the transaction are deleted on rollback."""
        spec = make_spec("ServiceA")

        with (
            pytest.raises(ValueError, match="fail"),
            lifecycle_manager.transaction() as txn,
        ):
            txn.create_component(
                SIMPLE_SOURCE_A, spec, target_dir=tmp_path,
            )
            raise ValueError("fail")

        # File should be cleaned up
        file_path = tmp_path / "service_a.py"
        assert not file_path.exists()

    def test_rollback_restores_updated_components(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """Updated components are restored to original specs on rollback."""
        spec = make_spec("Mutable", version="1.0.0")
        registry.register(spec)

        with (
            pytest.raises(ValueError, match="cancel"),
            lifecycle_manager.transaction() as txn,
        ):
            txn.update_component("Mutable", version="2.0.0")
            raise ValueError("cancel")

        restored = registry.get("Mutable")
        assert restored is not None
        assert restored.version == "1.0.0"

    def test_rollback_re_registers_removed_components(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """Removed components are re-registered on rollback."""
        spec = make_spec("Recoverable")
        registry.register(spec)

        with (
            pytest.raises(ValueError, match="undo"),
            lifecycle_manager.transaction() as txn,
        ):
            txn.remove_component("Recoverable")
            raise ValueError("undo")

        # Component should be back
        assert registry.contains("Recoverable")
        restored = registry.get("Recoverable")
        assert restored is not None
        assert restored.intent == spec.intent

    def test_explicit_rollback(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """txn.rollback() can be called manually inside the context."""
        spec = make_spec("ManualRollback")
        registry.register(spec)

        with lifecycle_manager.transaction() as txn:
            txn.update_component(
                "ManualRollback",
                intent="This should not persist after manual rollback",
            )
            txn.rollback()

        restored = registry.get("ManualRollback")
        assert restored is not None
        assert restored.intent == spec.intent
        assert txn.rolled_back

    def test_rollback_is_idempotent(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """Calling rollback() twice doesn't raise."""
        spec = make_spec("Idempotent")
        registry.register(spec)

        with lifecycle_manager.transaction() as txn:
            txn.update_component(
                "Idempotent",
                intent="Updated intent that will be rolled back twice",
            )
            txn.rollback()
            txn.rollback()  # Second call should be a no-op

        assert txn.rolled_back

    def test_partial_rollback_failure_raises_transaction_error(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """If a rollback action fails, TransactionError is raised."""
        spec = make_spec("PartialFail")
        registry.register(spec)

        with lifecycle_manager.transaction() as txn:
            txn.remove_component("PartialFail")
            # Manually inject a failing rollback action
            def _failing_rollback() -> None:
                msg = "simulated rollback failure"
                raise RuntimeError(msg)

            txn._rollback_actions.append(
                ("intentional failure", _failing_rollback)
            )

        # Now manually trigger rollback (we can't trigger it through
        # the context manager since it already committed)
        # Instead, let's test via an exception path
        spec2 = make_spec("PartialFail2")
        registry.register(spec2)

        with (
            pytest.raises(TransactionError, match="rollback failure"),
            lifecycle_manager.transaction() as txn2,
        ):
            txn2.remove_component("PartialFail2")
            # Inject a failing rollback
            txn2._rollback_actions.append(
                ("intentional failure", _failing_rollback)
            )
            raise ValueError("trigger rollback")


# ======================================================================
# Mixed operation scenarios
# ======================================================================


class TestTransactionMixed:
    """Mixed operation scenarios."""

    def test_create_then_update(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """Create a component, then update it, within one transaction."""
        spec = make_spec("CreatedThenUpdated")

        with lifecycle_manager.transaction() as txn:
            txn.create_component(
                SIMPLE_SOURCE_A, spec, target_dir=tmp_path,
            )
            txn.update_component(
                "CreatedThenUpdated",
                intent="Updated after creation in same transaction",
            )

        retrieved = registry.get("CreatedThenUpdated")
        assert retrieved is not None
        assert retrieved.intent == "Updated after creation in same transaction"

    def test_create_then_remove(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """Create a component, then remove it, within one transaction."""
        spec = make_spec("Ephemeral")

        with lifecycle_manager.transaction() as txn:
            txn.create_component(
                SIMPLE_SOURCE_A, spec, target_dir=tmp_path,
            )
            txn.remove_component("Ephemeral", force=True)

        assert not registry.contains("Ephemeral")

    def test_update_then_remove(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """Update a component, then remove it, within one transaction."""
        spec = make_spec("UpdateThenRemove")
        registry.register(spec)

        with lifecycle_manager.transaction() as txn:
            txn.update_component(
                "UpdateThenRemove",
                intent="Updated right before removal in transaction",
            )
            txn.remove_component("UpdateThenRemove")

        assert not registry.contains("UpdateThenRemove")

    def test_failure_mid_transaction_rolls_back_first(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """First operation succeeds, second fails -- first is rolled back."""
        spec_a = make_spec("SuccessfulCreate")

        with (
            pytest.raises(RegistryIntegrityError, match="not registered"),
            lifecycle_manager.transaction() as txn,
        ):
            txn.create_component(
                SIMPLE_SOURCE_A, spec_a, target_dir=tmp_path,
            )
            # This will fail because "NonExistent" is not registered
            txn.update_component(
                "NonExistent",
                intent="This should fail and roll back create",
            )

        # The create should be rolled back
        assert not registry.contains("SuccessfulCreate")
        file_path = tmp_path / "successful_create.py"
        assert not file_path.exists()

    def test_empty_transaction(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """A transaction with no operations is a no-op."""
        count_before = registry.count()

        with lifecycle_manager.transaction() as txn:
            pass

        assert registry.count() == count_before
        assert txn.committed
        assert not txn.rolled_back
        assert len(txn.operations) == 0

    def test_rollback_of_mixed_create_update_remove(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """Rollback of create + update + remove restores everything."""
        update_spec = make_spec("ForUpdate", version="1.0.0")
        remove_spec = make_spec("ForRemoval")
        registry.register(update_spec)
        registry.register(remove_spec)
        count_before = registry.count()

        with (
            pytest.raises(ValueError, match="abort"),
            lifecycle_manager.transaction() as txn,
        ):
            spec_a = make_spec("ServiceA")
            txn.create_component(
                SIMPLE_SOURCE_A, spec_a, target_dir=tmp_path,
            )
            txn.update_component("ForUpdate", version="2.0.0")
            txn.remove_component("ForRemoval")
            raise ValueError("abort all changes")

        # Everything should be restored
        assert not registry.contains("ServiceA")
        assert (tmp_path / "service_a.py").exists() is False
        assert registry.count() == count_before

        updated = registry.get("ForUpdate")
        assert updated is not None
        assert updated.version == "1.0.0"

        assert registry.contains("ForRemoval")


# ======================================================================
# Transaction and LifecycleManager integration
# ======================================================================


class TestTransactionIntegration:
    """Integration tests for transaction behavior."""

    def test_nested_transactions_raise_transaction_error(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """Attempting to nest transactions raises TransactionError."""
        spec = make_spec("NestTarget")
        registry.register(spec)

        with lifecycle_manager.transaction() as outer_txn:
            outer_txn.update_component(
                "NestTarget", intent="Outer transaction update for nesting"
            )
            with (
                pytest.raises(TransactionError, match="[Nn]ested"),
                lifecycle_manager.transaction(),
            ):
                pass  # pragma: no cover — never reached

        # Outer transaction should still have committed successfully
        assert outer_txn.committed

    def test_transaction_returns_context(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """LifecycleManager.transaction() returns a TransactionContext."""
        txn = lifecycle_manager.transaction()
        assert isinstance(txn, TransactionContext)

    def test_events_recorded_on_manager(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """Transaction operations also record events on the manager."""
        spec = make_spec("EventTarget")
        registry.register(spec)

        with lifecycle_manager.transaction() as txn:
            txn.update_component(
                "EventTarget", intent="Updated for manager event recording"
            )

        # The manager should have events from the internal methods
        manager_events = lifecycle_manager.events
        assert len(manager_events) >= 1
        assert any(
            e.action == LifecycleAction.UPDATE
            and e.component_name == "EventTarget"
            for e in manager_events
        )

    def test_create_returns_module(
        self,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """Transaction create_component returns the imported module."""
        spec = make_spec("ServiceA")

        with lifecycle_manager.transaction() as txn:
            module = txn.create_component(
                SIMPLE_SOURCE_A, spec, target_dir=tmp_path,
            )

        assert hasattr(module, "ServiceA")
        service = module.ServiceA()
        assert service.run() == "A"

    def test_update_returns_new_spec(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """Transaction update_component returns the updated spec."""
        spec = make_spec("Returnable")
        registry.register(spec)

        with lifecycle_manager.transaction() as txn:
            new_spec = txn.update_component(
                "Returnable", intent="Returns the new spec from transaction"
            )

        assert new_spec.intent == "Returns the new spec from transaction"

    def test_remove_returns_old_spec(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        """Transaction remove_component returns the removed spec."""
        spec = make_spec("ReturnableRemoval")
        registry.register(spec)

        with lifecycle_manager.transaction() as txn:
            removed = txn.remove_component("ReturnableRemoval")

        assert removed.name == "ReturnableRemoval"
        assert removed.intent == spec.intent
