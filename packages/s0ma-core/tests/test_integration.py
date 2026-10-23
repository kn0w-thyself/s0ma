"""Integration tests — Milestone 8: Full end-to-end verification.

These tests verify the complete S0ma lifecycle: framework
initialization, user component registration via @component, import
hook enforcement, persistence round-trips, and mixed framework + user
component queries. They use a mini task management application
(tests/sample_project/mini_app/) as a realistic test bed.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma._bootstrap import EXPECTED_FRAMEWORK_COMPONENT_COUNT, bootstrap_register
from s0ma._verifier import verify_self_model
from s0ma.decorators import get_all_components_in_module, get_component_spec, is_component
from s0ma.exceptions import UnregisteredComponentError
from s0ma.import_hook import install_import_hook, uninstall_import_hook
from s0ma.registry import ComponentRegistry, reset_registry, set_registry
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from collections.abc import Generator


# ======================================================================
# Helpers
# ======================================================================

SAMPLE_PROJECT_ROOT = Path(__file__).parent / "sample_project"


def _fresh_registry_with_bootstrap() -> ComponentRegistry:
    """Create a fresh in-memory registry with bootstrap registration."""
    registry = ComponentRegistry(persist=False)
    bootstrap_register(registry)
    return registry


def _clear_mini_app_modules() -> None:
    """Remove mini_app modules from sys.modules to allow fresh import."""
    to_remove = [
        key for key in sys.modules
        if key.startswith("tests.sample_project.mini_app")
    ]
    for key in to_remove:
        del sys.modules[key]


@pytest.fixture()
def _clean_hook() -> Generator[None, None, None]:
    """Ensure the import hook is uninstalled after the test."""
    yield
    uninstall_import_hook()
    _clear_mini_app_modules()


# ======================================================================
# Test: Full Lifecycle
# ======================================================================


class TestFullLifecycle:
    """End-to-end test: initialize → import user code → query → describe."""

    def test_full_lifecycle(self) -> None:
        """Initialize S0ma, import user components, verify everything works."""
        # Step 1: Create registry with bootstrap
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        # Step 2: Import user components (triggers @component registration)
        _clear_mini_app_modules()
        from tests.sample_project.mini_app.adapters.storage import StorageAdapter
        from tests.sample_project.mini_app.models.task import Task
        from tests.sample_project.mini_app.services.task_service import TaskService

        # Step 3: Verify all components are registered
        assert registry.contains("Task")
        assert registry.contains("TaskService")
        assert registry.contains("StorageAdapter")

        # Step 4: Verify component metadata
        task_spec = registry.get("Task")
        assert task_spec is not None
        assert task_spec.kind == ComponentKind.MODEL
        assert task_spec.layer == Layer.DOMAIN

        service_spec = registry.get("TaskService")
        assert service_spec is not None
        assert service_spec.kind == ComponentKind.SERVICE
        assert service_spec.layer == Layer.APPLICATION
        assert "Task" in service_spec.dependencies
        assert "StorageAdapter" in service_spec.dependencies

        adapter_spec = registry.get("StorageAdapter")
        assert adapter_spec is not None
        assert adapter_spec.kind == ComponentKind.ADAPTER
        assert adapter_spec.layer == Layer.INFRASTRUCTURE

        # Step 5: Verify hierarchical queries work
        domain = registry.query_by_layer(Layer.DOMAIN)
        domain_names = [s.name for s in domain]
        assert "Task" in domain_names

        app = registry.query_by_layer(Layer.APPLICATION)
        app_names = [s.name for s in app]
        assert "TaskService" in app_names

        infra = registry.query_by_layer(Layer.INFRASTRUCTURE)
        infra_names = [s.name for s in infra]
        assert "StorageAdapter" in infra_names

        # Step 6: Verify dependency graph
        graph = registry.get_dependency_graph()
        assert "Task" in graph["TaskService"]
        assert "StorageAdapter" in graph["TaskService"]

        # Step 7: Verify snapshot and description
        snapshot = registry.snapshot()
        total = snapshot.component_count
        assert total == EXPECTED_FRAMEWORK_COMPONENT_COUNT + 3

        description = snapshot.describe()
        assert "Task" in description
        assert "TaskService" in description
        assert "StorageAdapter" in description
        assert "DOMAIN" in description
        assert "APPLICATION" in description
        assert "INFRASTRUCTURE" in description
        # The framework's own components are counted, not listed, unless asked
        assert "[FRAMEWORK]" not in description
        assert "[FRAMEWORK]" in snapshot.describe(include_framework=True)

        # Step 8: Verify the classes actually work
        task = Task(title="Test integration")
        assert task.title == "Test integration"
        assert task.status == "pending"
        task.complete()
        assert task.status == "completed"

        service = TaskService()
        new_task = service.create_task("Buy milk")
        assert new_task.title == "Buy milk"
        assert service.get_pending_count() == 1

        adapter = StorageAdapter()
        adapter.save("key", "value")
        assert adapter.load("key") == "value"

    def test_components_have_introspectable_metadata(self) -> None:
        """Imported user components carry __component__ metadata."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)
        _clear_mini_app_modules()

        from tests.sample_project.mini_app.models.task import Task

        assert is_component(Task)
        spec = get_component_spec(Task)
        assert spec is not None
        assert spec.name == "Task"
        assert spec.intent is not None
        assert len(spec.intent) >= 10

    def test_get_all_components_in_module(self) -> None:
        """get_all_components_in_module() finds components across a module."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)
        _clear_mini_app_modules()

        from tests.sample_project.mini_app.services import task_service

        specs = get_all_components_in_module(task_service)
        names = [s.name for s in specs]
        assert "TaskService" in names


# ======================================================================
# Test: Sabotage Test (Import Hook Enforcement)
# ======================================================================


class TestSabotageTest:
    """The sabotage test: intentionally unregistered code must be caught."""

    @pytest.mark.usefixtures("_clean_hook")
    def test_unregistered_intruder_caught_strict(self) -> None:
        """Importing unregistered code in strict mode raises UnregisteredComponentError."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        install_import_hook(
            project_root=SAMPLE_PROJECT_ROOT,
            allowlist={"s0ma"},
            strict=True,
        )

        _clear_mini_app_modules()

        with pytest.raises(UnregisteredComponentError, match="RogueService"):
            importlib.import_module(
                "tests.sample_project.mini_app.unregistered_intruder"
            )

    @pytest.mark.usefixtures("_clean_hook")
    def test_error_message_names_offending_entity(self) -> None:
        """The error message clearly identifies which entities are unregistered."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        install_import_hook(
            project_root=SAMPLE_PROJECT_ROOT,
            allowlist={"s0ma"},
            strict=True,
        )

        _clear_mini_app_modules()

        with pytest.raises(UnregisteredComponentError) as exc_info:
            importlib.import_module(
                "tests.sample_project.mini_app.unregistered_intruder"
            )

        error_msg = str(exc_info.value)
        assert "RogueService" in error_msg
        assert "class" in error_msg
        assert "@component" in error_msg

    @pytest.mark.usefixtures("_clean_hook")
    def test_registered_modules_pass_enforcement(self) -> None:
        """Properly registered modules import successfully with the hook active."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        install_import_hook(
            project_root=SAMPLE_PROJECT_ROOT,
            allowlist={"s0ma"},
            strict=True,
        )

        _clear_mini_app_modules()

        # These should import without error
        mod = importlib.import_module(
            "tests.sample_project.mini_app.models.task"
        )
        assert hasattr(mod, "Task")

        mod2 = importlib.import_module(
            "tests.sample_project.mini_app.adapters.storage"
        )
        assert hasattr(mod2, "StorageAdapter")

    @pytest.mark.usefixtures("_clean_hook")
    def test_internal_helpers_exempted(self) -> None:
        """@internal-decorated helpers pass enforcement in the mini app."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        install_import_hook(
            project_root=SAMPLE_PROJECT_ROOT,
            allowlist={"s0ma"},
            strict=True,
        )

        _clear_mini_app_modules()

        # task_service.py has @internal helper — should import fine
        mod = importlib.import_module(
            "tests.sample_project.mini_app.services.task_service"
        )
        assert hasattr(mod, "TaskService")


# ======================================================================
# Test: Persistence (Fresh Start)
# ======================================================================


class TestPersistence:
    """Verify SQLite persistence survives registry re-instantiation."""

    def test_fresh_start_persistence(self, tmp_path: Path) -> None:
        """Components survive registry destruction and re-creation."""
        db_path = tmp_path / "integration_test.db"

        # Phase 1: Create registry, register components, close
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        bootstrap_register(reg1)
        set_registry(reg1)

        _clear_mini_app_modules()
        # Side-effect import: @component decorators register on load
        importlib.import_module("tests.sample_project.mini_app.models.task")

        count_before = reg1.count()
        assert count_before == EXPECTED_FRAMEWORK_COMPONENT_COUNT + 1
        assert reg1.contains("Task")
        reg1.close()

        # Phase 2: Create a new registry from the same DB — components restored
        reset_registry()
        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        assert reg2.count() == count_before
        assert reg2.contains("Task")

        # Verify restored spec metadata
        task_spec = reg2.get("Task")
        assert task_spec is not None
        assert task_spec.kind == ComponentKind.MODEL
        assert task_spec.layer == Layer.DOMAIN
        assert task_spec.name == "Task"
        assert len(task_spec.intent) >= 10

        reg2.close()

    def test_persistence_preserves_dependency_graph(self, tmp_path: Path) -> None:
        """Dependency relationships survive persistence round-trip."""
        db_path = tmp_path / "dep_test.db"

        # Phase 1: Register components with dependencies
        reg1 = ComponentRegistry(persist=True, db_path=db_path)
        bootstrap_register(reg1)
        set_registry(reg1)

        _clear_mini_app_modules()
        # Side-effect imports: @component decorators register on load
        importlib.import_module("tests.sample_project.mini_app.adapters.storage")
        importlib.import_module("tests.sample_project.mini_app.models.task")
        importlib.import_module("tests.sample_project.mini_app.services.task_service")

        reg1.close()

        # Phase 2: Re-create from DB, verify dependencies
        reset_registry()
        reg2 = ComponentRegistry(persist=True, db_path=db_path)
        graph = reg2.get_dependency_graph()
        assert "Task" in graph.get("TaskService", [])
        assert "StorageAdapter" in graph.get("TaskService", [])

        reg2.close()


# ======================================================================
# Test: Mixed Framework + User Components
# ======================================================================


class TestMixedComponents:
    """Verify framework and user components coexist and can be queried separately."""

    def test_framework_and_user_components_coexist(self) -> None:
        """Registry contains both framework and user components after import."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        _clear_mini_app_modules()
        importlib.import_module("tests.sample_project.mini_app.models.task")
        importlib.import_module("tests.sample_project.mini_app.services.task_service")

        # Framework components present
        assert registry.contains("ComponentRegistry")
        assert registry.contains("ComponentDecorator")
        # User components present
        assert registry.contains("Task")
        assert registry.contains("TaskService")

    def test_filter_framework_vs_user(self) -> None:
        """Framework and user components can be separated by is_framework flag."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        _clear_mini_app_modules()
        importlib.import_module("tests.sample_project.mini_app.models.task")

        all_specs = registry.get_all()

        framework_specs = {
            name: spec for name, spec in all_specs.items() if spec.is_framework
        }
        user_specs = {
            name: spec for name, spec in all_specs.items() if not spec.is_framework
        }

        assert len(framework_specs) == EXPECTED_FRAMEWORK_COMPONENT_COUNT
        assert len(user_specs) >= 1
        assert "Task" in user_specs
        assert "ComponentRegistry" in framework_specs

    def test_snapshot_describes_both(self) -> None:
        """The description lists the application; asked, it lists the framework too."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        _clear_mini_app_modules()
        importlib.import_module("tests.sample_project.mini_app.adapters.storage")
        importlib.import_module("tests.sample_project.mini_app.models.task")

        snapshot = registry.snapshot()
        description = snapshot.describe()

        # User components are what the application's description lists
        assert "Task" in description
        assert "StorageAdapter" in description
        assert "DOMAIN" in description
        assert "INFRASTRUCTURE" in description
        # Framework components are counted, and said to be omitted, not listed
        assert f"Framework components: {EXPECTED_FRAMEWORK_COMPONENT_COUNT}" in description
        assert "framework components are omitted" in description
        assert "[FRAMEWORK]" not in description
        assert "- ComponentRegistry (framework)" not in description
        # Asked for, both are there
        everything = snapshot.describe(include_framework=True)
        assert "- ComponentRegistry (framework)" in everything
        assert "[FRAMEWORK]" in everything
        assert "Task" in everything
        # Counts are accurate
        assert snapshot.framework_component_count == EXPECTED_FRAMEWORK_COMPONENT_COUNT
        user_count = snapshot.component_count - snapshot.framework_component_count
        assert user_count == 2

    def test_layer_queries_across_both(self) -> None:
        """Layer queries return correct results for framework and user layers."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        _clear_mini_app_modules()
        importlib.import_module("tests.sample_project.mini_app.models.task")

        framework_layer = registry.query_by_layer(Layer.FRAMEWORK)
        assert len(framework_layer) == EXPECTED_FRAMEWORK_COMPONENT_COUNT

        domain_layer = registry.query_by_layer(Layer.DOMAIN)
        domain_names = [s.name for s in domain_layer]
        assert "Task" in domain_names


# ======================================================================
# Test: Bootstrap Verifier Still Passes After User Registration
# ======================================================================


class TestBootstrapIntegrity:
    """Verify bootstrap self-verification still passes after user components are added."""

    def test_bootstrap_verifier_with_user_components(self) -> None:
        """Adding user components does not break the bootstrap verifier."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        _clear_mini_app_modules()
        importlib.import_module("tests.sample_project.mini_app.adapters.storage")
        importlib.import_module("tests.sample_project.mini_app.models.task")
        importlib.import_module("tests.sample_project.mini_app.services.task_service")

        # The verifier checks framework components only — user components
        # should not cause false positives
        anomalies = verify_self_model(registry)
        assert anomalies == [], (
            "Bootstrap verifier found anomalies after user registration:\n"
            + "\n".join(f"  - {a.message}" for a in anomalies)
        )

    def test_framework_count_unchanged_after_user_registration(self) -> None:
        """User registrations don't inflate the framework component count."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        _clear_mini_app_modules()
        importlib.import_module("tests.sample_project.mini_app.models.task")

        snapshot = registry.snapshot()
        assert snapshot.framework_component_count == EXPECTED_FRAMEWORK_COMPONENT_COUNT


# ======================================================================
# Test: User Component Functionality Post-Registration
# ======================================================================


class TestUserComponentFunctionality:
    """Verify that @component-decorated classes and functions work normally."""

    def test_decorated_dataclass_works(self) -> None:
        """A @component-decorated @dataclass still works as a dataclass."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        _clear_mini_app_modules()
        from tests.sample_project.mini_app.models.task import Task

        task = Task(title="Integration test task")
        assert task.title == "Integration test task"
        assert task.status == "pending"

        task.assign("Alice")
        assert task.assignee == "Alice"
        assert task.status == "assigned"

        task.complete()
        assert task.status == "completed"

    def test_decorated_service_works(self) -> None:
        """A @component-decorated service class is fully functional."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        _clear_mini_app_modules()
        from tests.sample_project.mini_app.services.task_service import TaskService

        service = TaskService()
        t1 = service.create_task("Task 1")
        service.create_task("Task 2")
        assert len(service.get_all_tasks()) == 2
        assert service.get_pending_count() == 2

        t1.complete()
        assert service.get_pending_count() == 1

    def test_isinstance_works_on_decorated_class(self) -> None:
        """isinstance() works correctly on @component-decorated classes."""
        registry = _fresh_registry_with_bootstrap()
        set_registry(registry)

        _clear_mini_app_modules()
        from tests.sample_project.mini_app.models.task import Task

        task = Task(title="test")
        assert isinstance(task, Task)
