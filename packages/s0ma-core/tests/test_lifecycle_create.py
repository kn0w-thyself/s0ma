"""Tests for runtime component creation.

Phase 2.5, Milestone 4 — LifecycleManager.create_component_at_runtime()
with rollback, validation, and lifecycle event recording.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from s0ma.exceptions import LifecycleError
from s0ma.lifecycle import LifecycleManager
from s0ma.models import (
    Anomaly,
    ComponentSpec,
    VerificationResult,
)
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

    from s0ma.registry import ComponentRegistry


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


SIMPLE_SOURCE = '''\
"""A simple dynamically created component."""


class SimpleService:
    """A simple service for testing runtime creation."""

    def greet(self, name: str) -> str:
        """Return a greeting message."""
        return f"Hello, {name}!"
'''

FUNCTION_SOURCE = '''\
"""A module with a simple function."""


def calculate_total(items: list[float]) -> float:
    """Calculate the sum of items."""
    return sum(items)
'''

SYNTAX_ERROR_SOURCE = '''\
"""A module with a syntax error."""

def broken_func(
    # Missing closing paren and colon
'''

IMPORT_ERROR_SOURCE = '''\
"""A module that imports something that doesn't exist."""

from nonexistent_package_xyz import phantom_module

class BadImport:
    pass
'''

RUNTIME_ERROR_SOURCE = '''\
"""A module that raises at import time."""

raise RuntimeError("This module fails to load")
'''


@pytest.fixture()
def lifecycle_manager(registry: ComponentRegistry) -> LifecycleManager:
    """A LifecycleManager with verification disabled for testing."""
    return LifecycleManager(registry, verify_after=False)


# ======================================================================
# Basic runtime component creation
# ======================================================================


class TestCreateComponentBasic:
    """Basic runtime component creation."""

    def test_create_simple_component(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Create a component from source code -- module is importable."""
        spec = make_spec("SimpleService")
        module = lifecycle_manager.create_component_at_runtime(
            SIMPLE_SOURCE, spec, target_dir=tmp_path,
        )
        assert module is not None
        assert hasattr(module, "SimpleService")

    def test_create_returns_module(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """create_component_at_runtime returns the loaded module."""
        spec = make_spec("SimpleService")
        module = lifecycle_manager.create_component_at_runtime(
            SIMPLE_SOURCE, spec, target_dir=tmp_path,
        )
        # Module should be a real module object
        from types import ModuleType

        assert isinstance(module, ModuleType)

    def test_created_component_is_registered(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """After creation, component appears in registry."""
        spec = make_spec("SimpleService")
        lifecycle_manager.create_component_at_runtime(
            SIMPLE_SOURCE, spec, target_dir=tmp_path,
        )
        assert registry.contains("SimpleService")

    def test_created_component_has_correct_paths(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """module_path and source_file are set correctly."""
        spec = make_spec("SimpleService")
        lifecycle_manager.create_component_at_runtime(
            SIMPLE_SOURCE, spec, target_dir=tmp_path,
        )
        registered = lifecycle_manager.registry.get("SimpleService")
        assert registered is not None
        assert registered.module_path == "simple_service"
        assert registered.source_file is not None
        assert "simple_service.py" in registered.source_file

    def test_created_module_is_callable(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """The created module's classes/functions are callable."""
        spec = make_spec("SimpleService")
        module = lifecycle_manager.create_component_at_runtime(
            SIMPLE_SOURCE, spec, target_dir=tmp_path,
        )
        service = module.SimpleService()
        result = service.greet("World")
        assert result == "Hello, World!"

    def test_source_file_written(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """The .py file exists at the expected location."""
        spec = make_spec("SimpleService")
        lifecycle_manager.create_component_at_runtime(
            SIMPLE_SOURCE, spec, target_dir=tmp_path,
        )
        file_path = tmp_path / "simple_service.py"
        assert file_path.exists()
        content = file_path.read_text(encoding="utf-8")
        assert "class SimpleService" in content

    def test_target_dir_parameter(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """target_dir controls where the file is written."""
        custom_dir = tmp_path / "custom" / "output"
        spec = make_spec("SimpleService")
        lifecycle_manager.create_component_at_runtime(
            SIMPLE_SOURCE, spec, target_dir=custom_dir,
        )
        assert (custom_dir / "simple_service.py").exists()

    def test_create_function_component(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Create a component with a function (not a class)."""
        spec = make_spec(
            "CalculateTotal",
            kind=ComponentKind.FUNCTION,
        )
        module = lifecycle_manager.create_component_at_runtime(
            FUNCTION_SOURCE, spec, target_dir=tmp_path,
        )
        assert hasattr(module, "calculate_total")
        assert module.calculate_total([1.0, 2.0, 3.0]) == 6.0


# ======================================================================
# Pre-validation for runtime creation
# ======================================================================


class TestCreateComponentValidation:
    """Pre-validation for runtime creation."""

    def test_duplicate_name_raises(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """Creating a component with an existing name raises LifecycleError."""
        existing = make_spec("SimpleService")
        registry.register(existing)

        new_spec = make_spec("SimpleService")
        with pytest.raises(LifecycleError, match="already registered"):
            lifecycle_manager.create_component_at_runtime(
                SIMPLE_SOURCE, new_spec, target_dir=tmp_path,
            )

    def test_missing_dependency_raises(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Creating with a non-existent dependency raises LifecycleError."""
        spec = make_spec(
            "DependentService",
            dependencies=["NonExistentDep"],
        )
        with pytest.raises(LifecycleError, match="not registered"):
            lifecycle_manager.create_component_at_runtime(
                SIMPLE_SOURCE, spec, target_dir=tmp_path,
            )

    def test_syntax_error_raises(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Source code with syntax errors raises LifecycleError."""
        spec = make_spec("BrokenComponent")
        with pytest.raises(LifecycleError):
            lifecycle_manager.create_component_at_runtime(
                SYNTAX_ERROR_SOURCE, spec, target_dir=tmp_path,
            )

    def test_import_error_raises(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Source code that fails to import raises LifecycleError."""
        spec = make_spec("BadImportComponent")
        with pytest.raises(LifecycleError):
            lifecycle_manager.create_component_at_runtime(
                IMPORT_ERROR_SOURCE, spec, target_dir=tmp_path,
            )

    def test_runtime_error_in_module_raises(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Source code that raises at import time raises LifecycleError."""
        spec = make_spec("CrashingComponent")
        with pytest.raises(LifecycleError):
            lifecycle_manager.create_component_at_runtime(
                RUNTIME_ERROR_SOURCE, spec, target_dir=tmp_path,
            )

    def test_file_already_exists_raises(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Creating when the target file already exists raises LifecycleError."""
        # Pre-create the file
        (tmp_path / "simple_service.py").write_text("# existing", encoding="utf-8")

        spec = make_spec("SimpleService")
        with pytest.raises(LifecycleError, match="file already exists"):
            lifecycle_manager.create_component_at_runtime(
                SIMPLE_SOURCE, spec, target_dir=tmp_path,
            )


# ======================================================================
# Rollback behavior on creation failure
# ======================================================================


class TestCreateComponentRollback:
    """Rollback behavior on creation failure."""

    def test_import_failure_rollback_file(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Import failure removes the source file."""
        spec = make_spec("BadImportComponent")
        with pytest.raises(LifecycleError):
            lifecycle_manager.create_component_at_runtime(
                IMPORT_ERROR_SOURCE, spec, target_dir=tmp_path,
            )

        # File should have been cleaned up
        file_path = tmp_path / "bad_import_component.py"
        assert not file_path.exists()

    def test_import_failure_rollback_registry(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """Import failure removes the registry entry."""
        spec = make_spec("BadImportComponent")
        with pytest.raises(LifecycleError):
            lifecycle_manager.create_component_at_runtime(
                IMPORT_ERROR_SOURCE, spec, target_dir=tmp_path,
            )

        # Should not be in registry
        assert not registry.contains("BadImportComponent")

    def test_verification_failure_rollback(
        self,
        registry: ComponentRegistry,
        tmp_path: Path,
    ) -> None:
        """Verification failure removes file, registry entry, and sys.modules."""
        lm = LifecycleManager(registry, verify_after=True)
        spec = make_spec("VerifyFailComponent")

        # Mock verification to fail
        failed_result = VerificationResult(
            verifier_name="structural",
            scope=VerificationScope.STRUCTURAL,
            anomalies=[
                Anomaly(
                    kind=AnomalyKind.PHANTOM_LIMB,
                    severity=AnomalySeverity.ERROR,
                    component_name="VerifyFailComponent",
                    message="Simulated verification failure",
                )
            ],
            components_checked=1,
            checks_performed=1,
        )

        with patch(
            "s0ma.verifiers.verify_incremental",
            return_value=failed_result,
        ), pytest.raises(LifecycleError, match="failed verification"):
            lm.create_component_at_runtime(
                SIMPLE_SOURCE, spec, target_dir=tmp_path,
            )

        # File should be cleaned up
        file_path = tmp_path / "verify_fail_component.py"
        assert not file_path.exists()

        # Registry should be clean
        assert not registry.contains("VerifyFailComponent")

        # sys.modules should be clean
        assert "verify_fail_component" not in sys.modules

    def test_rollback_registry_state(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """After rollback, registry.contains() returns False."""
        spec = make_spec("CrashingComponent")
        with pytest.raises(LifecycleError):
            lifecycle_manager.create_component_at_runtime(
                RUNTIME_ERROR_SOURCE, spec, target_dir=tmp_path,
            )
        assert not registry.contains("CrashingComponent")

    def test_rollback_preserves_existing_components(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """A failed creation doesn't affect pre-existing components."""
        # Register an existing component
        existing = make_spec("ExistingService")
        registry.register(existing)

        spec = make_spec("CrashingComponent")
        with pytest.raises(LifecycleError):
            lifecycle_manager.create_component_at_runtime(
                RUNTIME_ERROR_SOURCE, spec, target_dir=tmp_path,
            )

        # Existing component should still be there, unchanged
        assert registry.contains("ExistingService")
        retrieved = registry.get("ExistingService")
        assert retrieved is not None
        assert retrieved.intent == existing.intent

    def test_duplicate_name_no_file_written(
        self,
        registry: ComponentRegistry,
        lifecycle_manager: LifecycleManager,
        tmp_path: Path,
    ) -> None:
        """Pre-validation failure (duplicate name) doesn't write any file."""
        existing = make_spec("SimpleService")
        registry.register(existing)

        new_spec = make_spec("SimpleService")
        with pytest.raises(LifecycleError, match="already registered"):
            lifecycle_manager.create_component_at_runtime(
                SIMPLE_SOURCE, new_spec, target_dir=tmp_path,
            )

        # No file should have been created
        file_path = tmp_path / "simple_service.py"
        assert not file_path.exists()

    def test_missing_dep_no_file_written(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Pre-validation failure (missing dep) doesn't write any file."""
        spec = make_spec(
            "DependentService",
            dependencies=["NonExistentDep"],
        )
        with pytest.raises(LifecycleError, match="not registered"):
            lifecycle_manager.create_component_at_runtime(
                SIMPLE_SOURCE, spec, target_dir=tmp_path,
            )

        # No file should have been created
        assert not any(tmp_path.iterdir())


# ======================================================================
# Sequential creation scenarios
# ======================================================================


class TestCreateComponentSequential:
    """Sequential creation scenarios."""

    def test_create_multiple_components(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Multiple sequential creations work."""
        spec1 = make_spec("ServiceAlpha")
        spec2 = make_spec("ServiceBeta")

        source1 = '"""Alpha service."""\n\nclass ServiceAlpha:\n    pass\n'
        source2 = '"""Beta service."""\n\nclass ServiceBeta:\n    pass\n'

        lifecycle_manager.create_component_at_runtime(
            source1, spec1, target_dir=tmp_path,
        )
        lifecycle_manager.create_component_at_runtime(
            source2, spec2, target_dir=tmp_path,
        )

        assert lifecycle_manager.registry.contains("ServiceAlpha")
        assert lifecycle_manager.registry.contains("ServiceBeta")
        assert (tmp_path / "service_alpha.py").exists()
        assert (tmp_path / "service_beta.py").exists()

    def test_second_depends_on_first(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Second component can declare dependency on first."""
        spec1 = make_spec("BaseService")
        source1 = '"""Base service."""\n\nclass BaseService:\n    pass\n'
        lifecycle_manager.create_component_at_runtime(
            source1, spec1, target_dir=tmp_path,
        )

        spec2 = make_spec(
            "DerivedService",
            dependencies=["BaseService"],
        )
        source2 = '"""Derived service."""\n\nclass DerivedService:\n    pass\n'
        lifecycle_manager.create_component_at_runtime(
            source2, spec2, target_dir=tmp_path,
        )

        assert lifecycle_manager.registry.contains("DerivedService")
        registered = lifecycle_manager.registry.get("DerivedService")
        assert registered is not None
        assert "BaseService" in registered.dependencies

    def test_lifecycle_events_recorded(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Creation records LifecycleEvent with action=CREATE_RUNTIME."""
        spec = make_spec("SimpleService")
        lifecycle_manager.create_component_at_runtime(
            SIMPLE_SOURCE, spec, target_dir=tmp_path,
        )

        events = lifecycle_manager.events
        assert len(events) == 1
        assert events[0].action == LifecycleAction.CREATE_RUNTIME
        assert events[0].component_name == "SimpleService"
        assert events[0].success is True

    def test_failure_event_recorded(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Failed creation records a LifecycleEvent with success=False."""
        spec = make_spec("CrashingComponent")
        with pytest.raises(LifecycleError):
            lifecycle_manager.create_component_at_runtime(
                RUNTIME_ERROR_SOURCE, spec, target_dir=tmp_path,
            )

        events = lifecycle_manager.events
        assert len(events) == 1
        assert events[0].action == LifecycleAction.CREATE_RUNTIME
        assert events[0].success is False
        assert events[0].error_message is not None

    def test_event_details_include_file_path(
        self, lifecycle_manager: LifecycleManager, tmp_path: Path,
    ) -> None:
        """Success event details include file_path and module_name."""
        spec = make_spec("SimpleService")
        lifecycle_manager.create_component_at_runtime(
            SIMPLE_SOURCE, spec, target_dir=tmp_path,
        )

        events = lifecycle_manager.events
        assert "file_path" in events[0].details
        assert "module_name" in events[0].details
        assert events[0].details["module_name"] == "simple_service"


# ======================================================================
# Module name conversion tests
# ======================================================================


class TestSpecToModuleName:
    """Tests for LifecycleManager._spec_to_module_name()."""

    def test_simple_pascal_case(self) -> None:
        """Simple PascalCase converts correctly."""
        assert LifecycleManager._spec_to_module_name("SimpleService") == "simple_service"

    def test_single_word(self) -> None:
        """Single word is just lowercased."""
        assert LifecycleManager._spec_to_module_name("Service") == "service"

    def test_three_words(self) -> None:
        """Three-word PascalCase."""
        assert (
            LifecycleManager._spec_to_module_name("PaymentGatewayAdapter")
            == "payment_gateway_adapter"
        )

    def test_acronym_prefix(self) -> None:
        """Acronym prefix like HTTP."""
        assert LifecycleManager._spec_to_module_name("HTTPClient") == "http_client"

    def test_acronym_suffix(self) -> None:
        """Acronym suffix like API."""
        assert LifecycleManager._spec_to_module_name("RestAPI") == "rest_api"

    def test_already_lowercase(self) -> None:
        """Already lowercase stays the same."""
        assert LifecycleManager._spec_to_module_name("simple") == "simple"

    def test_all_caps(self) -> None:
        """All caps becomes all lowercase."""
        assert LifecycleManager._spec_to_module_name("API") == "api"
