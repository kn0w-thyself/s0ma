"""Transactional context for multi-step lifecycle operations.

Provides TransactionContext — a context manager that wraps multiple
lifecycle operations (create, update, remove) and rolls them all back
if any operation fails or an exception is raised.

Operations are executed immediately (not deferred). The transaction
tracks rollback actions so it can undo everything if needed.

Usage::

    lm = LifecycleManager(registry)
    with lm.transaction() as txn:
        txn.create_component(source1, spec1, target_dir=path)
        txn.update_component("Foo", intent="New intent")
        txn.remove_component("Bar", force=True)
    # If any operation raises, all three are rolled back.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma.exceptions import TransactionError
from s0ma.lifecycle.manager import _SENTINEL
from s0ma.models import LifecycleEvent
from s0ma.types import LifecycleAction

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType, TracebackType

    from s0ma.lifecycle.manager import LifecycleManager
    from s0ma.models import ComponentSpec, Contract, ResourceProfile

logger = logging.getLogger("s0ma")


class TransactionContext:
    """Transactional wrapper for multi-step lifecycle operations.

    Records all operations and their rollback actions. On successful
    context exit, changes remain applied. On exception, all operations
    are rolled back in reverse order.

    Thread safety: The transaction acquires the lifecycle manager's lock
    on entry and holds it until exit, preventing concurrent transactions
    from interleaving.

    Args:
        manager: The LifecycleManager whose operations to wrap.
    """

    def __init__(self, manager: LifecycleManager) -> None:
        self._manager = manager
        self._rollback_actions: list[tuple[str, Callable[[], None]]] = []
        self._events: list[LifecycleEvent] = []
        self._committed = False
        self._rolled_back = False

    def __enter__(self) -> TransactionContext:
        self._manager._lifecycle_lock.acquire()
        if self._manager._in_transaction:
            self._manager._lifecycle_lock.release()
            raise TransactionError(
                "Nested transactions are not supported. "
                "A transaction is already in progress on this LifecycleManager."
            )
        self._manager._in_transaction = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is not None:
                # Exception occurred — rollback
                self.rollback()
            else:
                # No exception — commit (no-op, changes already applied)
                self._committed = True
        finally:
            self._manager._in_transaction = False
            self._manager._lifecycle_lock.release()

    @property
    def operations(self) -> list[LifecycleEvent]:
        """Events recorded during this transaction (in order)."""
        return list(self._events)

    @property
    def committed(self) -> bool:
        """Whether this transaction was committed (exited without error)."""
        return self._committed

    @property
    def rolled_back(self) -> bool:
        """Whether this transaction was rolled back."""
        return self._rolled_back

    # ------------------------------------------------------------------
    # Transaction-scoped lifecycle operations
    # ------------------------------------------------------------------

    def create_component(
        self,
        source_code: str,
        spec: ComponentSpec,
        *,
        target_dir: Path | None = None,
    ) -> ModuleType:
        """Create a component within this transaction.

        On rollback: removes the file, unregisters, clears sys.modules.

        Args:
            source_code: Python source code for the new module.
            spec: ComponentSpec describing the new component.
            target_dir: Directory for the source file.

        Returns:
            The imported Python module.

        Raises:
            LifecycleError: If creation fails.
        """
        # Call the internal implementation (we already hold the lock)
        module = self._manager._create_internal(
            source_code, spec, target_dir=target_dir,
        )

        # Record rollback actions for this creation
        registered_spec = self._manager._registry.get(spec.name)
        if registered_spec is not None:
            source_file = registered_spec.source_file
            module_name = registered_spec.module_path
        else:
            source_file = None
            module_name = None

        # Build a rollback that undoes the create: delete file,
        # unregister from registry, remove from sys.modules
        self._rollback_actions.append(
            (f"undo create '{spec.name}'",
             self._make_create_rollback(
                 spec.name,
                 Path(source_file) if source_file else None,
                 module_name,
             )),
        )

        # Record the event
        event = LifecycleEvent(
            action=LifecycleAction.CREATE_RUNTIME,
            component_name=spec.name,
            timestamp=self._now(),
            success=True,
            details={"transactional": True},
        )
        self._events.append(event)

        return module

    def update_component(
        self,
        name: str,
        *,
        intent: str | None = None,
        contracts: Contract | None = None,
        dependencies: list[str] | None = None,
        resource_profile: ResourceProfile | None = _SENTINEL,
        version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ComponentSpec:
        """Update a component within this transaction.

        On rollback: restores the original spec.

        Args:
            name: Name of the component to update.
            intent: New intent string.
            contracts: New Contract object.
            dependencies: New dependency list.
            resource_profile: New ResourceProfile or None.
            version: New version string.
            metadata: New metadata dict.

        Returns:
            The updated ComponentSpec.

        Raises:
            RegistryIntegrityError: If the component doesn't exist.
            LifecycleError: If validation or verification fails.
        """
        # Capture the old spec before update for rollback
        old_spec = self._manager._registry.get(name)
        if old_spec is None:
            from s0ma.exceptions import RegistryIntegrityError

            raise RegistryIntegrityError(
                f"Cannot update '{name}': component is not registered."
            )

        # Call the internal implementation (we already hold the lock)
        new_spec = self._manager._update_internal(
            name,
            intent=intent,
            contracts=contracts,
            dependencies=dependencies,
            resource_profile=resource_profile,
            version=version,
            metadata=metadata,
        )

        # Record rollback action: restore old spec
        self._rollback_actions.append(
            (f"undo update '{name}'",
             self._make_update_rollback(name, old_spec)),
        )

        # Record the event
        event = LifecycleEvent(
            action=LifecycleAction.UPDATE,
            component_name=name,
            timestamp=self._now(),
            success=True,
            details={"transactional": True},
        )
        self._events.append(event)

        return new_spec

    def remove_component(
        self,
        name: str,
        *,
        force: bool = False,
    ) -> ComponentSpec:
        """Remove a component within this transaction.

        On rollback: re-registers the removed spec.

        Args:
            name: Name of the component to remove.
            force: If True, remove even if dependents exist.

        Returns:
            The removed ComponentSpec.

        Raises:
            RegistryIntegrityError: If the component doesn't exist.
            LifecycleError: If dependents exist and force=False.
        """
        # Call the internal implementation (we already hold the lock)
        removed_spec = self._manager._remove_internal(name, force=force)

        # Record rollback action: re-register the removed spec
        self._rollback_actions.append(
            (f"undo remove '{name}'",
             self._make_remove_rollback(removed_spec)),
        )

        # Record the event
        event = LifecycleEvent(
            action=LifecycleAction.UNREGISTER,
            component_name=name,
            timestamp=self._now(),
            success=True,
            previous_spec=removed_spec,
            details={"transactional": True, "forced": force},
        )
        self._events.append(event)

        return removed_spec

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(self) -> None:
        """Roll back all operations in reverse order.

        Each rollback action is attempted even if previous ones fail.
        Failures are logged but do not prevent subsequent rollbacks.

        Raises:
            TransactionError: If any rollback actions fail (after all
                rollbacks have been attempted).
        """
        if self._rolled_back:
            return

        failures: list[str] = []
        for description, action in reversed(self._rollback_actions):
            try:
                action()
                logger.debug("Rolled back: %s", description)
            except Exception as e:
                msg = f"Rollback failed for '{description}': {e}"
                logger.warning(msg)
                failures.append(msg)

        self._rolled_back = True

        if failures:
            raise TransactionError(
                f"Transaction rollback completed with "
                f"{len(failures)} failure(s): {'; '.join(failures)}"
            )

    # ------------------------------------------------------------------
    # Rollback action factories (typed for mypy strict)
    # ------------------------------------------------------------------

    def _make_create_rollback(
        self,
        component_name: str,
        file_path: Path | None,
        module_name: str | None,
    ) -> Callable[[], None]:
        """Create a rollback action that undoes a create operation."""
        registry = self._manager._registry

        def _rollback() -> None:
            # 1. Remove from sys.modules
            if module_name is not None:
                sys.modules.pop(module_name, None)
            # 2. Unregister from registry
            if registry.contains(component_name):
                registry.unregister(component_name, force=True)
            # 3. Delete the source file
            if file_path is not None:
                file_path.unlink(missing_ok=True)

        return _rollback

    def _make_update_rollback(
        self,
        name: str,
        old_spec: ComponentSpec,
    ) -> Callable[[], None]:
        """Create a rollback action that restores a component to its old spec."""
        registry = self._manager._registry

        def _rollback() -> None:
            if registry.contains(name):
                registry._replace_internal(name, old_spec)
            elif registry.contains(old_spec.name):
                registry._replace_internal(old_spec.name, old_spec)
            else:
                # Component was removed in a later operation — re-register it
                registry.register(old_spec)

        return _rollback

    def _make_remove_rollback(
        self,
        removed_spec: ComponentSpec,
    ) -> Callable[[], None]:
        """Create a rollback action that re-registers a removed component."""
        registry = self._manager._registry

        def _rollback() -> None:
            if not registry.contains(removed_spec.name):
                registry.register(removed_spec)

        return _rollback

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> Any:
        """Get the current UTC timestamp."""
        from datetime import UTC, datetime

        return datetime.now(UTC)
