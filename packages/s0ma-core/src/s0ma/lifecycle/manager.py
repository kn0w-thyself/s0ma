"""Lifecycle manager — orchestrates component lifecycle with verification.

The LifecycleManager wraps ComponentRegistry primitives (unregister,
_replace_internal) with:
- Pre-validation before mutations
- Structural verification after mutations
- Automatic rollback if verification fails
- Lifecycle event logging for audit trail
- Runtime component creation from source code
- Transactional multi-step operations with rollback

This is the public API for component lifecycle operations. Direct
registry manipulation should be avoided in favor of these methods.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma.exceptions import LifecycleError, RegistrationError, RegistryIntegrityError
from s0ma.models import LifecycleEvent
from s0ma.types import LifecycleAction

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from s0ma.lifecycle.transaction import TransactionContext
    from s0ma.models import ComponentSpec, Contract, ResourceProfile
    from s0ma.registry import ComponentRegistry
    from s0ma.self_model.interface import SelfModelInterface

logger = logging.getLogger("s0ma")

_SENTINEL: Any = object()


class LifecycleManager:
    """Orchestrates component lifecycle operations with verification.

    Wraps the ComponentRegistry with:
    - Pre-validation before mutations
    - Structural verification after mutations
    - Automatic rollback if verification fails
    - Lifecycle event logging for audit trail
    - Transactional multi-step operations

    Args:
        registry: The ComponentRegistry to manage.
        verify_after: If True (default), run verify_incremental() after
            each mutation. If False, skip verification (faster but unsafe).
        self_model: Optional SelfModelInterface for enhanced pre-validation.
            When provided, ``create_component_at_runtime()`` uses
            ``self_model.validate_proposed_component()`` for richer
            constraint checking (layer conformance, naming conventions,
            contract completeness) in addition to the basic name/dependency
            checks.
    """

    def __init__(
        self,
        registry: ComponentRegistry,
        *,
        verify_after: bool = True,
        self_model: SelfModelInterface | None = None,
    ) -> None:
        self._registry = registry
        self._verify_after = verify_after
        self._self_model = self_model
        self._lifecycle_lock = threading.RLock()
        self._in_transaction = False
        self._events: list[LifecycleEvent] = []

    @property
    def registry(self) -> ComponentRegistry:
        """The managed registry."""
        return self._registry

    @property
    def events(self) -> list[LifecycleEvent]:
        """Lifecycle events recorded by this manager (in order)."""
        return list(self._events)

    # ------------------------------------------------------------------
    # Public methods (acquire the lifecycle lock, delegate to internal)
    # ------------------------------------------------------------------

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
        """Update an existing component's metadata.

        Only provided fields are updated; None fields (except
        resource_profile when explicitly set) are left unchanged.

        After update, runs structural verification if enabled. If
        verification produces ERROR-severity anomalies, rolls back
        to the original spec.

        Args:
            name: Name of the component to update.
            intent: New intent string (>= 10 chars).
            contracts: New Contract object.
            dependencies: New dependency list.
            resource_profile: New ResourceProfile, or None to clear.
                Omit to keep current value.
            version: New version string.
            metadata: New metadata dict.

        Returns:
            The updated ComponentSpec.

        Raises:
            RegistryIntegrityError: If the component doesn't exist.
            LifecycleError: If validation or verification fails
                (the update is rolled back).
        """
        with self._lifecycle_lock:
            return self._update_internal(
                name,
                intent=intent,
                contracts=contracts,
                dependencies=dependencies,
                resource_profile=resource_profile,
                version=version,
                metadata=metadata,
            )

    def remove_component(
        self,
        name: str,
        *,
        force: bool = False,
    ) -> ComponentSpec:
        """Remove a component with lifecycle event logging.

        Wraps registry.unregister() with event recording.

        Args:
            name: Name of the component to remove.
            force: If True, remove even if dependents exist.

        Returns:
            The removed ComponentSpec.

        Raises:
            RegistryIntegrityError: If the component doesn't exist.
            LifecycleError: If dependents exist and force=False.
        """
        with self._lifecycle_lock:
            return self._remove_internal(name, force=force)

    def create_component_at_runtime(
        self,
        source_code: str,
        spec: ComponentSpec,
        *,
        target_dir: Path | None = None,
    ) -> ModuleType:
        """Create a new component at runtime from source code.

        Steps:
        1. Pre-validate: name uniqueness, dependency existence
        2. Write source code to a file in target_dir
        3. Register the component in the registry
        4. Import the new module
        5. Run structural verification (if enabled)
        6. On any failure after step 2: roll back file, registration, sys.modules

        The source code should be plain Python WITHOUT @component decorators.
        Registration is handled by this method, not by the source code itself.

        Args:
            source_code: Python source code for the new module.
            spec: ComponentSpec describing the new component.
            target_dir: Directory for the source file. If None, uses
                a '_s0ma_generated' subdirectory under cwd.

        Returns:
            The imported Python module.

        Raises:
            LifecycleError: If any step fails. All changes are rolled back.
        """
        with self._lifecycle_lock:
            return self._create_internal(source_code, spec, target_dir=target_dir)

    def transaction(self) -> TransactionContext:
        """Create a transactional context for multi-step operations.

        Returns a context manager that records all operations and
        rolls back on failure. The transaction holds the lifecycle lock
        for its entire duration, preventing concurrent modifications.

        Usage::

            with lifecycle_manager.transaction() as txn:
                txn.create_component(source, spec, target_dir=path)
                txn.update_component("Foo", intent="New intent")
                txn.remove_component("Bar", force=True)
            # If any operation raises, all three are rolled back.

        Returns:
            A TransactionContext that manages rollback on failure.
        """
        from s0ma.lifecycle.transaction import TransactionContext

        return TransactionContext(self)

    # ------------------------------------------------------------------
    # Internal methods (no lock — called by public methods and by
    # TransactionContext which holds the lock itself)
    # ------------------------------------------------------------------

    def _update_internal(
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
        """Internal update implementation (no lock acquisition).

        Called by update_component() (which holds the lock) and by
        TransactionContext (which also holds the lock).
        """
        # 1. Get current spec
        current = self._registry.get(name)
        if current is None:
            raise RegistryIntegrityError(
                f"Cannot update '{name}': component is not registered."
            )

        # 2. Build overrides dict (only non-None, non-sentinel values)
        overrides: dict[str, Any] = {}
        if intent is not None:
            overrides["intent"] = intent
        if contracts is not None:
            overrides["contracts"] = contracts
        if dependencies is not None:
            overrides["dependencies"] = dependencies
        if resource_profile is not _SENTINEL:
            overrides["resource_profile"] = resource_profile
        if version is not None:
            overrides["version"] = version
        if metadata is not None:
            overrides["metadata"] = metadata

        if not overrides:
            return current  # No changes requested

        # 3. Create new spec via replace (validates)
        try:
            new_spec = current.replace(**overrides)
        except (RegistrationError, TypeError) as e:
            self._record_event(
                LifecycleAction.UPDATE, name, success=False,
                error_message=str(e),
            )
            raise LifecycleError(
                f"Update validation failed for '{name}': {e}"
            ) from e

        # 4. Atomic replacement in registry
        old_spec = self._registry._replace_internal(name, new_spec)

        # 5. Verification (if enabled)
        if self._verify_after:
            from s0ma.verifiers import verify_incremental

            result = verify_incremental(self._registry, new_spec.name)
            if not result.passed:
                # Rollback
                self._registry._replace_internal(new_spec.name, old_spec)
                self._record_event(
                    LifecycleAction.UPDATE, name, success=False,
                    previous_spec=old_spec,
                    error_message=result.describe(),
                )
                raise LifecycleError(
                    f"Update of '{name}' failed verification and was "
                    f"rolled back: {result.describe()}"
                )

        # 6. Record success
        self._record_event(
            LifecycleAction.UPDATE, name, success=True,
            previous_spec=old_spec,
            details={"updated_fields": sorted(overrides.keys())},
        )
        return new_spec

    def _remove_internal(
        self,
        name: str,
        *,
        force: bool = False,
    ) -> ComponentSpec:
        """Internal remove implementation (no lock acquisition).

        Called by remove_component() (which holds the lock) and by
        TransactionContext (which also holds the lock).
        """
        try:
            removed_spec = self._registry.unregister(name, force=force)
        except (RegistryIntegrityError, LifecycleError) as e:
            self._record_event(
                LifecycleAction.UNREGISTER, name, success=False,
                error_message=str(e),
            )
            raise

        self._record_event(
            LifecycleAction.UNREGISTER, name, success=True,
            previous_spec=removed_spec,
            details={"forced": force},
        )
        return removed_spec

    def _create_internal(
        self,
        source_code: str,
        spec: ComponentSpec,
        *,
        target_dir: Path | None = None,
    ) -> ModuleType:
        """Internal create implementation (no lock acquisition).

        Called by create_component_at_runtime() (which holds the lock)
        and by TransactionContext (which also holds the lock).

        Returns:
            The imported module and a list of rollback actions that
            the caller (TransactionContext) can use for transaction-level
            rollback. When called from create_component_at_runtime(),
            rollback is handled internally on failure.
        """
        rollback_actions: list[tuple[str, Callable[[], None]]] = []

        try:
            # 1. Pre-validate
            self._validate_proposed_component(spec)

            # 2. Determine file path
            module_name = self._spec_to_module_name(spec.name)
            if target_dir is None:
                target_dir = self._default_target_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            file_path = target_dir / f"{module_name}.py"

            if file_path.exists():
                raise LifecycleError(
                    f"Cannot create '{spec.name}': file already exists "
                    f"at {file_path}"
                )

            # 3. Write source file
            self._write_source_file(source_code, file_path)
            rollback_actions.append(
                (f"delete file '{file_path}'",
                 self._make_file_rollback(file_path))
            )

            # 4. Update spec with derived fields
            spec.module_path = module_name
            spec.qualified_name = f"{module_name}.{spec.name}"
            spec.source_file = str(file_path)

            # 5. Register in registry
            self._registry.register(spec)
            rollback_actions.append(
                (f"unregister '{spec.name}'",
                 self._make_unregister_rollback(spec.name))
            )

            # 6. Import the module
            module = self._import_module_from_file(module_name, file_path)
            rollback_actions.append(
                (f"remove '{module_name}' from sys.modules",
                 self._make_sysmodules_rollback(module_name))
            )

            # 7. Verify (if enabled)
            if self._verify_after:
                from s0ma.verifiers import verify_incremental

                result = verify_incremental(self._registry, spec.name)
                if not result.passed:
                    raise LifecycleError(
                        f"Created component '{spec.name}' failed "
                        f"verification: {result.describe()}"
                    )

            # 8. Record success
            self._record_event(
                LifecycleAction.CREATE_RUNTIME, spec.name, success=True,
                details={
                    "file_path": str(file_path),
                    "module_name": module_name,
                },
            )
            return module

        except Exception as e:
            # Rollback in reverse order
            for description, action in reversed(rollback_actions):
                try:
                    action()
                    logger.debug("Rolled back: %s", description)
                except Exception as rollback_error:
                    logger.warning(
                        "Rollback action failed for '%s': %s",
                        description, rollback_error,
                    )

            # Record failure event
            self._record_event(
                LifecycleAction.CREATE_RUNTIME, spec.name, success=False,
                error_message=str(e),
            )

            # Re-raise as LifecycleError if not already
            if isinstance(e, LifecycleError):
                raise
            raise LifecycleError(
                f"Failed to create component '{spec.name}': {e}"
            ) from e

    # ------------------------------------------------------------------
    # Rollback action factories (typed for mypy strict)
    # ------------------------------------------------------------------

    @staticmethod
    def _make_file_rollback(file_path: Path) -> Callable[[], None]:
        """Create a rollback action that deletes a file."""
        def _rollback() -> None:
            file_path.unlink(missing_ok=True)
        return _rollback

    def _make_unregister_rollback(self, name: str) -> Callable[[], None]:
        """Create a rollback action that unregisters a component."""
        def _rollback() -> None:
            self._registry.unregister(name, force=True)
        return _rollback

    @staticmethod
    def _make_sysmodules_rollback(module_name: str) -> Callable[[], None]:
        """Create a rollback action that removes a module from sys.modules."""
        def _rollback() -> None:
            sys.modules.pop(module_name, None)
        return _rollback

    # ------------------------------------------------------------------
    # Helper methods for runtime creation
    # ------------------------------------------------------------------

    def _validate_proposed_component(self, spec: ComponentSpec) -> None:
        """Pre-validate a component before creation.

        When a SelfModelInterface is available, delegates to its
        ``validate_proposed_component()`` for richer constraint checking
        (layer conformance, naming conventions, contract completeness).
        Otherwise falls back to basic name/dependency checks.

        Args:
            spec: The proposed ComponentSpec.

        Raises:
            LifecycleError: If validation fails.
        """
        from s0ma.types import AnomalySeverity

        if self._self_model is not None:
            anomalies = self._self_model.validate_proposed_component(spec)
            errors = [
                a for a in anomalies
                if a.severity == AnomalySeverity.ERROR
            ]
            if errors:
                messages = "; ".join(a.message for a in errors)
                raise LifecycleError(
                    f"Pre-validation failed for '{spec.name}': {messages}"
                )
            return

        # Fallback: basic checks when no SelfModelInterface is wired
        if self._registry.contains(spec.name):
            raise LifecycleError(
                f"Component '{spec.name}' is already registered."
            )

        for dep in spec.dependencies:
            if not self._registry.contains(dep):
                raise LifecycleError(
                    f"Dependency '{dep}' of component '{spec.name}' "
                    f"is not registered."
                )

    @staticmethod
    def _spec_to_module_name(component_name: str) -> str:
        """Convert a PascalCase component name to a snake_case module name.

        Examples:
            'PaymentProcessor' -> 'payment_processor'
            'DatabaseAdapter' -> 'database_adapter'
            'HTTPClient' -> 'http_client'
            'SimpleService' -> 'simple_service'

        Args:
            component_name: The PascalCase component name.

        Returns:
            A snake_case module name suitable for a Python file.
        """
        # Insert underscores before uppercase letters (handling acronyms)
        s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", component_name)
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
        return s.lower()

    @staticmethod
    def _write_source_file(source_code: str, file_path: Path) -> None:
        """Write source code to a file.

        Writes to a temp file first, then replaces the target path
        (``Path.replace`` overwrites an existing target on every OS;
        ``rename`` refuses on Windows). This prevents partial writes
        from being imported. ``newline="\\n"`` keeps generated sources
        byte-identical across platforms (INV-5).

        Args:
            source_code: The Python source code to write.
            file_path: The target file path.
        """
        temp_path = file_path.with_suffix(".py.tmp")
        try:
            temp_path.write_text(source_code, encoding="utf-8", newline="\n")
            temp_path.replace(file_path)
        except Exception:
            # Clean up temp file on failure
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _delete_source_file(file_path: Path) -> None:
        """Delete a source file (rollback operation).

        Args:
            file_path: The file to delete.
        """
        file_path.unlink(missing_ok=True)

    @staticmethod
    def _import_module_from_file(
        module_name: str, file_path: Path,
    ) -> ModuleType:
        """Dynamically import a module from a file path.

        Args:
            module_name: The module name to register in sys.modules.
            file_path: The source file to load.

        Returns:
            The loaded Python module.

        Raises:
            LifecycleError: If the module cannot be loaded.
        """
        module_spec = importlib.util.spec_from_file_location(
            module_name, file_path,
        )
        if module_spec is None or module_spec.loader is None:
            raise LifecycleError(
                f"Could not create module spec for '{module_name}' "
                f"from {file_path}"
            )
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
        return module

    @staticmethod
    def _default_target_dir() -> Path:
        """Default directory for dynamically created source files.

        Returns:
            Path to the '_s0ma_generated' directory under cwd.
        """
        return Path.cwd() / "_s0ma_generated"

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    def _record_event(
        self,
        action: LifecycleAction,
        component_name: str,
        success: bool,
        *,
        details: dict[str, Any] | None = None,
        previous_spec: ComponentSpec | None = None,
        error_message: str | None = None,
    ) -> LifecycleEvent:
        """Record a lifecycle event."""
        event = LifecycleEvent(
            action=action,
            component_name=component_name,
            timestamp=datetime.now(UTC),
            success=success,
            details=details or {},
            previous_spec=previous_spec,
            error_message=error_message,
        )
        self._events.append(event)
        return event
