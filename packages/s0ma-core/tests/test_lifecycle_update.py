"""Tests for lifecycle operations: replace, update, and remove.

Phase 2.5, Milestones 2-3 — ComponentSpec.replace(), atomic registry
replacement, LifecycleManager update and remove operations.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from s0ma.exceptions import LifecycleError, RegistrationError, RegistryIntegrityError
from s0ma.lifecycle import LifecycleManager
from s0ma.models import (
    Anomaly,
    ComponentSpec,
    Contract,
    ResourceProfile,
    VerificationResult,
)
from s0ma.registry import ComponentRegistry
from s0ma.types import (
    AnomalyKind,
    AnomalySeverity,
    ComponentKind,
    Layer,
    LifecycleAction,
    VerificationScope,
)

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


# ======================================================================
# ComponentSpec.replace() tests
# ======================================================================


class TestComponentSpecReplace:
    """Tests for ComponentSpec.replace() method."""

    def test_replace_intent(self) -> None:
        """Replace intent field -- new intent is stored, other fields unchanged."""
        spec = make_spec("Foo")
        new_spec = spec.replace(intent="This is a brand new intent for testing")
        assert new_spec.intent == "This is a brand new intent for testing"
        assert new_spec.name == "Foo"
        assert new_spec.kind == spec.kind
        assert new_spec.layer == spec.layer

    def test_replace_contracts(self) -> None:
        """Replace contracts -- new contracts stored."""
        spec = make_spec("Foo")
        new_contracts = Contract(
            preconditions=["input is valid"],
            postconditions=["returns result"],
            invariants=["no side effects"],
        )
        new_spec = spec.replace(contracts=new_contracts)
        assert new_spec.contracts == new_contracts
        assert new_spec.contracts.preconditions == ["input is valid"]

    def test_replace_dependencies(self) -> None:
        """Replace dependencies -- new list stored."""
        spec = make_spec("Foo")
        new_spec = spec.replace(dependencies=["BarService", "BazAdapter"])
        assert new_spec.dependencies == ["BarService", "BazAdapter"]
        assert spec.dependencies == []  # Original unchanged

    def test_replace_multiple_fields(self) -> None:
        """Replace multiple fields simultaneously."""
        spec = make_spec("Foo")
        new_spec = spec.replace(
            intent="Updated intent for testing purposes here",
            version="2.0.0",
            dependencies=["BarService"],
        )
        assert new_spec.intent == "Updated intent for testing purposes here"
        assert new_spec.version == "2.0.0"
        assert new_spec.dependencies == ["BarService"]
        assert new_spec.name == "Foo"  # Unchanged

    def test_replace_returns_new_instance(self) -> None:
        """replace() returns a new object, not the original."""
        spec = make_spec("Foo")
        new_spec = spec.replace(intent="Different intent for the component now")
        assert new_spec is not spec
        assert id(new_spec) != id(spec)

    def test_replace_validates_result(self) -> None:
        """replace() with invalid values raises RegistrationError."""
        spec = make_spec("Foo")
        with pytest.raises(RegistrationError):
            spec.replace(intent="short")  # Less than 10 chars

    def test_replace_empty_intent_raises(self) -> None:
        """replace(intent='') triggers __post_init__ validation."""
        spec = make_spec("Foo")
        with pytest.raises(RegistrationError, match="at least 10 characters"):
            spec.replace(intent="")

    def test_replace_self_dependency_raises(self) -> None:
        """replace(dependencies=['Foo']) where Foo is the component name raises."""
        spec = make_spec("Foo")
        with pytest.raises(RegistrationError, match="cannot depend on itself"):
            spec.replace(dependencies=["Foo"])

    def test_replace_unknown_field_raises(self) -> None:
        """replace(nonexistent_field=42) raises TypeError."""
        spec = make_spec("Foo")
        with pytest.raises(TypeError, match="Unknown ComponentSpec fields"):
            spec.replace(nonexistent_field=42)  # type: ignore[arg-type]

    def test_replace_unknown_field_lists_valid(self) -> None:
        """TypeError message lists valid fields for developer guidance."""
        spec = make_spec("Foo")
        with pytest.raises(TypeError) as exc_info:
            spec.replace(bogus=True)  # type: ignore[arg-type]
        error_msg = str(exc_info.value)
        assert "bogus" in error_msg
        assert "name" in error_msg  # Should list valid fields

    def test_replace_preserves_module_path(self) -> None:
        """Fields not mentioned in overrides retain their original values."""
        spec = make_spec(
            "Foo",
            module_path="myapp.services.foo",
            qualified_name="myapp.services.foo.Foo",
            source_file="/src/myapp/services/foo.py",
        )
        new_spec = spec.replace(intent="Updated intent for the component here")
        assert new_spec.module_path == "myapp.services.foo"
        assert new_spec.qualified_name == "myapp.services.foo.Foo"
        assert new_spec.source_file == "/src/myapp/services/foo.py"

    def test_replace_with_no_overrides(self) -> None:
        """replace() with no arguments creates an equivalent copy."""
        spec = make_spec("Foo")
        new_spec = spec.replace()
        assert new_spec is not spec
        assert new_spec.name == spec.name
        assert new_spec.kind == spec.kind
        assert new_spec.layer == spec.layer
        assert new_spec.intent == spec.intent
        assert new_spec.dependencies == spec.dependencies
        assert new_spec.version == spec.version

    def test_replace_name_change(self) -> None:
        """replace(name='Bar') creates a spec with the new name."""
        spec = make_spec("Foo")
        new_spec = spec.replace(name="Bar")
        assert new_spec.name == "Bar"
        assert spec.name == "Foo"  # Original unchanged

    def test_replace_kind_and_layer(self) -> None:
        """replace() can change kind and layer."""
        spec = make_spec("Foo", kind=ComponentKind.SERVICE, layer=Layer.DOMAIN)
        new_spec = spec.replace(
            kind=ComponentKind.ADAPTER,
            layer=Layer.INFRASTRUCTURE,
        )
        assert new_spec.kind == ComponentKind.ADAPTER
        assert new_spec.layer == Layer.INFRASTRUCTURE

    def test_replace_resource_profile(self) -> None:
        """replace() can add a resource profile."""
        spec = make_spec("Foo")
        assert spec.resource_profile is None
        profile = ResourceProfile(expected_memory_mb=128.0)
        new_spec = spec.replace(resource_profile=profile)
        assert new_spec.resource_profile is not None
        assert new_spec.resource_profile.expected_memory_mb == 128.0

    def test_replace_resource_profile_to_none(self) -> None:
        """replace(resource_profile=None) clears the profile."""
        profile = ResourceProfile(expected_memory_mb=64.0)
        spec = make_spec("Foo", resource_profile=profile)
        assert spec.resource_profile is not None

        new_spec = spec.replace(resource_profile=None)
        assert new_spec.resource_profile is None

    def test_replace_preserves_is_framework(self) -> None:
        """replace() preserves is_framework if not overridden."""
        spec = make_spec("Foo", is_framework=True)
        new_spec = spec.replace(intent="Updated intent for framework component")
        assert new_spec.is_framework is True

    def test_replace_invalid_contract_raises(self) -> None:
        """replace() with invalid contract raises RegistrationError."""
        spec = make_spec("Foo")
        bad_contract = Contract(max_latency_ms=-100)
        with pytest.raises(RegistrationError):
            spec.replace(contracts=bad_contract)

    def test_replace_original_unchanged(self) -> None:
        """replace() does not mutate the original spec."""
        spec = make_spec("Foo", version="1.0.0")
        spec.replace(version="2.0.0")
        assert spec.version == "1.0.0"


# ======================================================================
# ComponentRegistry._replace_internal() tests
# ======================================================================


class TestRegistryReplaceInternal:
    """Tests for ComponentRegistry._replace_internal()."""

    def test_replace_updates_spec(self, registry: ComponentRegistry) -> None:
        """After replace, get() returns the new spec."""
        spec = make_spec("Foo")
        registry.register(spec)

        new_spec = spec.replace(intent="Brand new intent for this component")
        registry._replace_internal("Foo", new_spec)

        retrieved = registry.get("Foo")
        assert retrieved is not None
        assert retrieved.intent == "Brand new intent for this component"

    def test_replace_returns_old_spec(self, registry: ComponentRegistry) -> None:
        """_replace_internal() returns the previous spec."""
        spec = make_spec("Foo")
        registry.register(spec)

        new_spec = spec.replace(intent="Updated intent for testing purposes")
        old_spec = registry._replace_internal("Foo", new_spec)

        assert old_spec.name == "Foo"
        assert old_spec.intent == spec.intent

    def test_replace_nonexistent_raises(self, registry: ComponentRegistry) -> None:
        """Replacing a non-registered component raises RegistryIntegrityError."""
        new_spec = make_spec("Ghost")
        with pytest.raises(RegistryIntegrityError, match="not registered"):
            registry._replace_internal("Ghost", new_spec)

    def test_replace_persists_to_sqlite(self, tmp_path: Path) -> None:
        """After replace, new spec survives registry re-instantiation."""
        db_path = tmp_path / "replace_test.db"
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        spec = make_spec("Persistent")
        reg1.register(spec)

        new_spec = spec.replace(intent="Persisted replacement intent works correctly")
        reg1._replace_internal("Persistent", new_spec)
        reg1.close()

        # Re-load from SQLite
        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        retrieved = reg2.get("Persistent")
        assert retrieved is not None
        assert retrieved.intent == "Persisted replacement intent works correctly"
        reg2.close()

    def test_replace_with_name_change(self, registry: ComponentRegistry) -> None:
        """Replacing with a different name works (rename)."""
        spec = make_spec("OldName")
        registry.register(spec)

        new_spec = spec.replace(name="NewName")
        old = registry._replace_internal("OldName", new_spec)

        assert old.name == "OldName"
        assert not registry.contains("OldName")
        assert registry.contains("NewName")
        retrieved = registry.get("NewName")
        assert retrieved is not None
        assert retrieved.name == "NewName"

    def test_replace_name_conflict_raises(self, registry: ComponentRegistry) -> None:
        """Renaming to an existing name raises RegistrationError."""
        spec_a = make_spec("Alpha")
        spec_b = make_spec("Beta")
        registry.register(spec_a)
        registry.register(spec_b)

        new_spec = spec_a.replace(name="Beta")
        with pytest.raises(RegistrationError, match="already registered"):
            registry._replace_internal("Alpha", new_spec)

        # Both originals should still be intact
        assert registry.contains("Alpha")
        assert registry.contains("Beta")

    def test_replace_is_atomic_on_name_conflict(
        self, registry: ComponentRegistry
    ) -> None:
        """If replace fails on name conflict, the old spec is still in the registry."""
        spec_a = make_spec("Alpha")
        spec_b = make_spec("Beta")
        registry.register(spec_a)
        registry.register(spec_b)

        new_spec = spec_a.replace(name="Beta")
        with pytest.raises(RegistrationError):
            registry._replace_internal("Alpha", new_spec)

        # Alpha's original spec should still be retrievable and unchanged
        retrieved = registry.get("Alpha")
        assert retrieved is not None
        assert retrieved.intent == spec_a.intent

    def test_replace_count_unchanged_same_name(
        self, registry: ComponentRegistry
    ) -> None:
        """Replacing with the same name doesn't change the component count."""
        spec = make_spec("Foo")
        registry.register(spec)
        assert registry.count() == 1

        new_spec = spec.replace(intent="Replaced intent for the same component")
        registry._replace_internal("Foo", new_spec)
        assert registry.count() == 1

    def test_replace_count_unchanged_rename(
        self, registry: ComponentRegistry
    ) -> None:
        """Renaming a component doesn't change the total count."""
        spec = make_spec("OldName")
        registry.register(spec)
        count_before = registry.count()

        new_spec = spec.replace(name="NewName")
        registry._replace_internal("OldName", new_spec)
        assert registry.count() == count_before

    def test_replace_snapshot_reflects_change(
        self, registry: ComponentRegistry
    ) -> None:
        """snapshot() reflects the replaced spec."""
        spec = make_spec("Foo")
        registry.register(spec)

        new_spec = spec.replace(intent="Updated intent appears in snapshot output")
        registry._replace_internal("Foo", new_spec)

        snapshot = registry.snapshot()
        assert "Foo" in snapshot.components
        assert snapshot.components["Foo"].intent == "Updated intent appears in snapshot output"

    def test_replace_name_change_persists_to_sqlite(
        self, tmp_path: Path
    ) -> None:
        """Name change via _replace_internal persists correctly to SQLite."""
        db_path = tmp_path / "rename_persist.db"
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        spec = make_spec("OldName")
        reg1.register(spec)

        new_spec = spec.replace(name="NewName")
        reg1._replace_internal("OldName", new_spec)
        reg1.close()

        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        assert not reg2.contains("OldName")
        assert reg2.contains("NewName")
        reg2.close()

    def test_replace_thread_safe(self, registry: ComponentRegistry) -> None:
        """Concurrent replaces on different components don't corrupt state."""
        # Register 10 components
        for i in range(10):
            registry.register(make_spec(f"Comp{i}"))

        def replace_component(idx: int) -> None:
            name = f"Comp{idx}"
            current = registry.get(name)
            assert current is not None
            new_spec = current.replace(
                intent=f"Updated intent for component number {idx} in test"
            )
            registry._replace_internal(name, new_spec)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(replace_component, i) for i in range(10)]
            for future in as_completed(futures):
                future.result()

        # All 10 should still exist with updated intents
        assert registry.count() == 10
        for i in range(10):
            spec = registry.get(f"Comp{i}")
            assert spec is not None
            assert f"component number {i}" in spec.intent


# ======================================================================
# LifecycleManager.update_component() tests (Milestone 3)
# ======================================================================


@pytest.fixture()
def lifecycle_manager(registry: ComponentRegistry) -> LifecycleManager:
    """A LifecycleManager with verification disabled for testing."""
    return LifecycleManager(registry, verify_after=False)


class TestLifecycleManagerUpdate:
    """Tests for LifecycleManager.update_component()."""

    def test_update_intent(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Update intent -- new intent is stored, other fields unchanged."""
        spec = make_spec("Updatable")
        registry.register(spec)

        result = lifecycle_manager.update_component(
            "Updatable", intent="This intent has been updated via lifecycle"
        )
        assert result.intent == "This intent has been updated via lifecycle"
        assert result.name == "Updatable"
        assert result.kind == spec.kind
        assert result.layer == spec.layer

    def test_update_contracts(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Update contracts -- new contracts stored."""
        spec = make_spec("Updatable")
        registry.register(spec)

        new_contracts = Contract(
            preconditions=["input is valid"],
            postconditions=["returns result"],
        )
        result = lifecycle_manager.update_component(
            "Updatable", contracts=new_contracts
        )
        assert result.contracts == new_contracts

    def test_update_dependencies(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Update dependencies -- new list stored."""
        dep = make_spec("DepService")
        spec = make_spec("Updatable")
        registry.register(dep)
        registry.register(spec)

        result = lifecycle_manager.update_component(
            "Updatable", dependencies=["DepService"]
        )
        assert result.dependencies == ["DepService"]

    def test_update_multiple_fields(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Update intent + version simultaneously."""
        spec = make_spec("Updatable")
        registry.register(spec)

        result = lifecycle_manager.update_component(
            "Updatable",
            intent="Updated intent for testing multiple fields",
            version="2.0.0",
        )
        assert result.intent == "Updated intent for testing multiple fields"
        assert result.version == "2.0.0"
        assert result.name == "Updatable"  # Unchanged

    def test_update_no_changes(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Calling update with no overrides returns current spec unchanged."""
        spec = make_spec("Updatable")
        registry.register(spec)

        result = lifecycle_manager.update_component("Updatable")
        assert result.intent == spec.intent
        # No event should be recorded for no-op
        assert len(lifecycle_manager.events) == 0

    def test_update_nonexistent_raises(
        self, lifecycle_manager: LifecycleManager
    ) -> None:
        """Updating a non-registered component raises RegistryIntegrityError."""
        with pytest.raises(RegistryIntegrityError, match="not registered"):
            lifecycle_manager.update_component(
                "Ghost", intent="Should not work at all"
            )

    def test_update_invalid_spec_raises(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Update with invalid values raises LifecycleError."""
        spec = make_spec("Updatable")
        registry.register(spec)

        with pytest.raises(LifecycleError, match="validation failed"):
            lifecycle_manager.update_component("Updatable", intent="short")

    def test_update_rollback_on_verification_failure(
        self, registry: ComponentRegistry
    ) -> None:
        """If verification fails, original spec is restored."""
        spec = make_spec("RollbackTarget")
        registry.register(spec)
        original_intent = spec.intent

        # Create manager with verification enabled
        lm = LifecycleManager(registry, verify_after=True)

        # Mock verify_incremental to return a failed result
        failed_result = VerificationResult(
            verifier_name="structural",
            scope=VerificationScope.STRUCTURAL,
            anomalies=[
                Anomaly(
                    kind=AnomalyKind.PHANTOM_LIMB,
                    severity=AnomalySeverity.ERROR,
                    component_name="RollbackTarget",
                    message="Simulated verification failure for rollback test",
                )
            ],
            components_checked=1,
            checks_performed=1,
        )

        with patch(
            "s0ma.verifiers.verify_incremental",
            return_value=failed_result,
        ), pytest.raises(LifecycleError, match="failed verification"):
            lm.update_component(
                "RollbackTarget",
                intent="This update should be rolled back completely",
            )

        # Verify rollback -- original spec should be restored
        restored = registry.get("RollbackTarget")
        assert restored is not None
        assert restored.intent == original_intent

    def test_update_records_success_event(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Successful update records a LifecycleEvent with action=UPDATE."""
        spec = make_spec("Updatable")
        registry.register(spec)

        lifecycle_manager.update_component(
            "Updatable", intent="Updated intent for event recording test"
        )

        events = lifecycle_manager.events
        assert len(events) == 1
        assert events[0].action == LifecycleAction.UPDATE
        assert events[0].component_name == "Updatable"
        assert events[0].success is True

    def test_update_records_failure_event(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Failed update records a LifecycleEvent with success=False."""
        spec = make_spec("Updatable")
        registry.register(spec)

        with pytest.raises(LifecycleError):
            lifecycle_manager.update_component("Updatable", intent="bad")

        events = lifecycle_manager.events
        assert len(events) == 1
        assert events[0].action == LifecycleAction.UPDATE
        assert events[0].success is False
        assert events[0].error_message is not None

    def test_update_event_includes_previous_spec(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """The lifecycle event includes the pre-update spec for rollback reference."""
        spec = make_spec("Updatable")
        registry.register(spec)
        original_intent = spec.intent

        lifecycle_manager.update_component(
            "Updatable", intent="Updated intent for previous spec event test"
        )

        events = lifecycle_manager.events
        assert len(events) == 1
        assert events[0].previous_spec is not None
        assert events[0].previous_spec.intent == original_intent

    def test_update_event_includes_updated_fields(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """The event details list which fields were updated."""
        spec = make_spec("Updatable")
        registry.register(spec)

        lifecycle_manager.update_component(
            "Updatable",
            intent="Updated intent for field tracking test",
            version="3.0.0",
        )

        events = lifecycle_manager.events
        assert len(events) == 1
        assert "updated_fields" in events[0].details
        assert sorted(events[0].details["updated_fields"]) == ["intent", "version"]

    def test_update_with_verify_disabled(
        self, registry: ComponentRegistry
    ) -> None:
        """verify_after=False skips verification (faster, no rollback)."""
        spec = make_spec("NoVerify")
        registry.register(spec)

        lm = LifecycleManager(registry, verify_after=False)
        result = lm.update_component(
            "NoVerify", intent="Updated without verification at all"
        )
        assert result.intent == "Updated without verification at all"
        # Should succeed even though the component has no real source file
        assert len(lm.events) == 1
        assert lm.events[0].success is True

    def test_update_resource_profile_to_none(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Explicitly setting resource_profile=None clears the profile."""
        profile = ResourceProfile(expected_memory_mb=128.0)
        spec = make_spec("Profiled", resource_profile=profile)
        registry.register(spec)

        result = lifecycle_manager.update_component(
            "Profiled", resource_profile=None
        )
        assert result.resource_profile is None

    def test_update_version_field(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Version can be updated independently."""
        spec = make_spec("Versioned", version="1.0.0")
        registry.register(spec)

        result = lifecycle_manager.update_component("Versioned", version="2.0.0")
        assert result.version == "2.0.0"
        assert result.intent == spec.intent  # Unchanged

    def test_update_metadata(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Metadata can be updated."""
        spec = make_spec("WithMeta")
        registry.register(spec)

        result = lifecycle_manager.update_component(
            "WithMeta", metadata={"author": "test", "priority": "high"}
        )
        assert result.metadata == {"author": "test", "priority": "high"}

    def test_update_registry_reflects_change(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """After update, registry.get() returns the updated spec."""
        spec = make_spec("Synced")
        registry.register(spec)

        lifecycle_manager.update_component(
            "Synced", intent="Registry should reflect this updated intent"
        )

        retrieved = registry.get("Synced")
        assert retrieved is not None
        assert retrieved.intent == "Registry should reflect this updated intent"

    def test_update_rollback_records_event(
        self, registry: ComponentRegistry
    ) -> None:
        """Verification failure rollback records a failure event."""
        spec = make_spec("EventRollback")
        registry.register(spec)

        lm = LifecycleManager(registry, verify_after=True)
        failed_result = VerificationResult(
            verifier_name="structural",
            scope=VerificationScope.STRUCTURAL,
            anomalies=[
                Anomaly(
                    kind=AnomalyKind.PHANTOM_LIMB,
                    severity=AnomalySeverity.ERROR,
                    component_name="EventRollback",
                    message="Simulated failure for event test",
                )
            ],
            components_checked=1,
            checks_performed=1,
        )

        with patch(
            "s0ma.verifiers.verify_incremental",
            return_value=failed_result,
        ), pytest.raises(LifecycleError):
            lm.update_component(
                "EventRollback",
                intent="This should fail and record event properly",
            )

        events = lm.events
        assert len(events) == 1
        assert events[0].success is False
        assert events[0].previous_spec is not None
        assert events[0].error_message is not None

    def test_update_resource_profile_omit_keeps_current(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Omitting resource_profile preserves the current value."""
        profile = ResourceProfile(expected_memory_mb=256.0)
        spec = make_spec("KeepProfile", resource_profile=profile)
        registry.register(spec)

        # Update intent only -- resource_profile should be preserved
        result = lifecycle_manager.update_component(
            "KeepProfile", intent="Updated but profile should remain unchanged"
        )
        assert result.resource_profile is not None
        assert result.resource_profile.expected_memory_mb == 256.0


# ======================================================================
# LifecycleManager.remove_component() tests (Milestone 3)
# ======================================================================


class TestLifecycleManagerRemove:
    """Tests for LifecycleManager.remove_component()."""

    def test_remove_standalone(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Remove a component with no dependents."""
        spec = make_spec("Removable")
        registry.register(spec)

        removed = lifecycle_manager.remove_component("Removable")
        assert removed.name == "Removable"
        assert not registry.contains("Removable")

    def test_remove_with_dependents_raises(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Remove a component with dependents raises LifecycleError."""
        dep = make_spec("BaseService")
        child = make_spec("ChildService", dependencies=["BaseService"])
        registry.register(dep)
        registry.register(child)

        with pytest.raises(LifecycleError, match="depend on it"):
            lifecycle_manager.remove_component("BaseService")

        # BaseService should still be registered
        assert registry.contains("BaseService")

    def test_remove_force(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """force=True removes despite dependents."""
        dep = make_spec("BaseService")
        child = make_spec("ChildService", dependencies=["BaseService"])
        registry.register(dep)
        registry.register(child)

        removed = lifecycle_manager.remove_component("BaseService", force=True)
        assert removed.name == "BaseService"
        assert not registry.contains("BaseService")
        # ChildService still exists (orphaned dependency)
        assert registry.contains("ChildService")

    def test_remove_records_event(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Removal records a LifecycleEvent with action=UNREGISTER."""
        spec = make_spec("Removable")
        registry.register(spec)

        lifecycle_manager.remove_component("Removable")

        events = lifecycle_manager.events
        assert len(events) == 1
        assert events[0].action == LifecycleAction.UNREGISTER
        assert events[0].component_name == "Removable"
        assert events[0].success is True

    def test_remove_event_includes_spec(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """The event includes the removed spec for rollback."""
        spec = make_spec("Removable")
        registry.register(spec)
        original_intent = spec.intent

        lifecycle_manager.remove_component("Removable")

        events = lifecycle_manager.events
        assert events[0].previous_spec is not None
        assert events[0].previous_spec.intent == original_intent

    def test_remove_nonexistent_raises(
        self, lifecycle_manager: LifecycleManager
    ) -> None:
        """Removing non-registered component raises RegistryIntegrityError."""
        with pytest.raises(RegistryIntegrityError, match="not registered"):
            lifecycle_manager.remove_component("Ghost")

    def test_remove_failure_records_event(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """Failed removal records a failure event."""
        dep = make_spec("BaseService")
        child = make_spec("ChildService", dependencies=["BaseService"])
        registry.register(dep)
        registry.register(child)

        with pytest.raises(LifecycleError):
            lifecycle_manager.remove_component("BaseService")

        events = lifecycle_manager.events
        assert len(events) == 1
        assert events[0].success is False
        assert events[0].error_message is not None

    def test_remove_event_details_include_forced(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """The event details include whether force was used."""
        spec = make_spec("Removable")
        registry.register(spec)

        lifecycle_manager.remove_component("Removable", force=True)

        events = lifecycle_manager.events
        assert events[0].details.get("forced") is True

    def test_remove_returns_spec_for_rollback(
        self, registry: ComponentRegistry, lifecycle_manager: LifecycleManager
    ) -> None:
        """The returned spec can be re-registered (manual rollback)."""
        spec = make_spec("Recoverable")
        registry.register(spec)

        removed = lifecycle_manager.remove_component("Recoverable")
        assert not registry.contains("Recoverable")

        # Manual rollback: re-register the removed spec
        registry.register(removed)
        assert registry.contains("Recoverable")
