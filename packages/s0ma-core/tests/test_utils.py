"""Tests for the s0ma.utils module — topological sort and bootstrap utilities.

Tests cover:
- topological_sort_modules() — simple chains, diamonds, cycles, independent modules
- registry.import_order() — module ordering from registered component dependencies
- bootstrap_modules() — dependency-safe module import and registration
"""

from __future__ import annotations

import types

import pytest

from s0ma.exceptions import RegistrationError
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer
from s0ma.utils import bootstrap_modules, topological_sort_modules

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
# topological_sort_modules() Tests
# ===========================================================================


class TestTopologicalSortModules:
    """Tests for the topological_sort_modules() utility."""

    def test_simple_dependency_chain(self) -> None:
        """A -> B -> C is sorted as C, B, A."""
        module_specs = [
            ("myapp.api", ["myapp.services"]),
            ("myapp.services", ["myapp.models"]),
            ("myapp.models", []),
        ]
        result = topological_sort_modules(module_specs)
        assert result.index("myapp.models") < result.index("myapp.services")
        assert result.index("myapp.services") < result.index("myapp.api")

    def test_diamond_dependency_pattern(self) -> None:
        """Diamond: A depends on B and C, both depend on D.

            A
           / \\
          B   C
           \\ /
            D
        """
        module_specs = [
            ("A", ["B", "C"]),
            ("B", ["D"]),
            ("C", ["D"]),
            ("D", []),
        ]
        result = topological_sort_modules(module_specs)
        assert result.index("D") < result.index("B")
        assert result.index("D") < result.index("C")
        assert result.index("B") < result.index("A")
        assert result.index("C") < result.index("A")

    def test_no_dependencies_returns_stable_sorted_order(self) -> None:
        """Modules with no deps return in a deterministic (sorted) order."""
        module_specs = [
            ("zebra", []),
            ("alpha", []),
            ("mango", []),
        ]
        result = topological_sort_modules(module_specs)
        assert len(result) == 3
        assert set(result) == {"zebra", "alpha", "mango"}
        # Should be deterministic (sorted)
        assert result == ["alpha", "mango", "zebra"]

    def test_circular_dependency_raises(self) -> None:
        """Circular A -> B -> C -> A raises RegistrationError."""
        module_specs = [
            ("A", ["B"]),
            ("B", ["C"]),
            ("C", ["A"]),
        ]
        with pytest.raises(RegistrationError, match="[Cc]ircular"):
            topological_sort_modules(module_specs)

    def test_circular_dependency_includes_cycle_info(self) -> None:
        """The error message includes the cycle path."""
        module_specs = [
            ("alpha", ["beta"]),
            ("beta", ["alpha"]),
        ]
        with pytest.raises(RegistrationError, match="alpha.*beta|beta.*alpha"):
            topological_sort_modules(module_specs)

    def test_self_dependency_raises(self) -> None:
        """A module depending on itself creates a cycle."""
        module_specs = [
            ("self_ref", ["self_ref"]),
        ]
        with pytest.raises(RegistrationError, match="[Cc]ircular"):
            topological_sort_modules(module_specs)

    def test_external_dependencies_are_ignored(self) -> None:
        """Dependencies not in the input list are ignored for ordering."""
        module_specs = [
            ("myapp.services", ["myapp.models", "sqlalchemy"]),
            ("myapp.models", []),
        ]
        result = topological_sort_modules(module_specs)
        assert result == ["myapp.models", "myapp.services"]

    def test_empty_input_returns_empty(self) -> None:
        """An empty input list returns an empty result."""
        result = topological_sort_modules([])
        assert result == []

    def test_single_module_no_deps(self) -> None:
        """A single module with no dependencies returns itself."""
        result = topological_sort_modules([("only_module", [])])
        assert result == ["only_module"]

    def test_complex_graph(self) -> None:
        """A more complex graph with multiple dependency levels."""
        module_specs = [
            ("app.api.routes", ["app.services.users", "app.services.orders"]),
            ("app.services.users", ["app.models.user", "app.adapters.db"]),
            ("app.services.orders", ["app.models.order", "app.adapters.db"]),
            ("app.models.user", []),
            ("app.models.order", []),
            ("app.adapters.db", []),
        ]
        result = topological_sort_modules(module_specs)

        # Leaf modules must come before their dependents
        for leaf in ["app.models.user", "app.models.order", "app.adapters.db"]:
            assert result.index(leaf) < result.index("app.api.routes")

        assert result.index("app.adapters.db") < result.index("app.services.users")
        assert result.index("app.adapters.db") < result.index("app.services.orders")
        assert result.index("app.models.user") < result.index("app.services.users")
        assert result.index("app.models.order") < result.index("app.services.orders")


# ===========================================================================
# registry.import_order() Tests
# ===========================================================================


class TestImportOrder:
    """Tests for ComponentRegistry.import_order()."""

    def test_import_order_simple_chain(self, registry: ComponentRegistry) -> None:
        """import_order() returns correct order for a dependency chain."""
        registry.register(make_spec("Base", module_path="app.models"))
        registry.register(make_spec(
            "Service",
            module_path="app.services",
            dependencies=["Base"],
        ))
        registry.register(make_spec(
            "Api",
            module_path="app.api",
            dependencies=["Service"],
        ))

        order = registry.import_order()
        assert order.index("app.models") < order.index("app.services")
        assert order.index("app.services") < order.index("app.api")

    def test_import_order_independent_modules(self, registry: ComponentRegistry) -> None:
        """import_order() handles modules with no cross-module dependencies."""
        registry.register(make_spec("CompA", module_path="module_a"))
        registry.register(make_spec("CompB", module_path="module_b"))
        registry.register(make_spec("CompC", module_path="module_c"))

        order = registry.import_order()
        assert set(order) == {"module_a", "module_b", "module_c"}

    def test_import_order_intra_module_deps_ignored(
        self, registry: ComponentRegistry
    ) -> None:
        """Dependencies within the same module don't create self-edges."""
        registry.register(make_spec("Helper", module_path="app.services"))
        registry.register(make_spec(
            "MainService",
            module_path="app.services",
            dependencies=["Helper"],
        ))

        order = registry.import_order()
        # Both are in the same module, so only one module entry
        assert order == ["app.services"]

    def test_import_order_empty_registry(self, registry: ComponentRegistry) -> None:
        """import_order() on an empty registry returns an empty list."""
        order = registry.import_order()
        assert order == []

    def test_import_order_diamond_dependency(self, registry: ComponentRegistry) -> None:
        """import_order() correctly handles a diamond dependency pattern."""
        registry.register(make_spec("D", module_path="mod.d"))
        registry.register(make_spec("B", module_path="mod.b", dependencies=["D"]))
        registry.register(make_spec("C", module_path="mod.c", dependencies=["D"]))
        registry.register(make_spec("A", module_path="mod.a", dependencies=["B", "C"]))

        order = registry.import_order()
        assert order.index("mod.d") < order.index("mod.b")
        assert order.index("mod.d") < order.index("mod.c")
        assert order.index("mod.b") < order.index("mod.a")
        assert order.index("mod.c") < order.index("mod.a")

    def test_import_order_with_framework_components(self) -> None:
        """import_order() works on a bootstrapped registry with framework components."""
        from s0ma._bootstrap import bootstrap_register

        registry = ComponentRegistry(persist=False)
        bootstrap_register(registry)

        order = registry.import_order()
        assert len(order) > 0
        # All module paths should be s0ma modules
        for mod_path in order:
            assert mod_path.startswith("s0ma.")


# ===========================================================================
# bootstrap_modules() Tests
# ===========================================================================


def _make_synthetic_module(
    specs: list[ComponentSpec],
    module_name: str = "test_synthetic_module",
) -> types.ModuleType:
    """Create a synthetic module with @component-decorated entities."""
    mod = types.ModuleType(module_name)
    for spec in specs:
        cls = type(spec.name, (), {"__component__": spec})
        setattr(mod, spec.name, cls)
    return mod


class TestBootstrapModules:
    """Tests for bootstrap_modules() convenience function.

    Note: bootstrap_modules() uses importlib.import_module() which requires
    real importable modules. These tests use monkeypatching to simulate
    module imports.
    """

    def test_bootstrap_modules_imports_and_registers(
        self, registry: ComponentRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bootstrap_modules() imports modules and registers their components."""
        from s0ma import registry as registry_mod

        # Set up the global registry
        monkeypatch.setattr(registry_mod, "_global_registry", registry)

        # Create synthetic modules
        spec_models = make_spec("UserModel", module_path="testapp.models")
        spec_service = make_spec(
            "UserService",
            module_path="testapp.services",
            dependencies=["UserModel"],
        )

        mod_models = _make_synthetic_module([spec_models], "testapp.models")
        mod_services = _make_synthetic_module([spec_service], "testapp.services")

        # Monkeypatch importlib to return our synthetic modules
        import importlib

        original_import = importlib.import_module

        def mock_import(name: str, package: str | None = None) -> types.ModuleType:
            if name == "testapp.models":
                return mod_models
            if name == "testapp.services":
                return mod_services
            return original_import(name, package)

        monkeypatch.setattr(importlib, "import_module", mock_import)

        # Order is intentionally "wrong" — services before models
        result = bootstrap_modules(
            ["testapp.services", "testapp.models"],
        )

        assert len(result) == 2
        assert registry.contains("UserModel")
        assert registry.contains("UserService")

    def test_bootstrap_modules_returns_specs_in_order(
        self, registry: ComponentRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bootstrap_modules() returns specs in topological order."""
        from s0ma import registry as registry_mod

        monkeypatch.setattr(registry_mod, "_global_registry", registry)

        spec_a = make_spec("A", module_path="pkg.a")
        spec_b = make_spec("B", module_path="pkg.b", dependencies=["A"])

        mod_a = _make_synthetic_module([spec_a], "pkg.a")
        mod_b = _make_synthetic_module([spec_b], "pkg.b")

        import importlib

        original_import = importlib.import_module

        def mock_import(name: str, package: str | None = None) -> types.ModuleType:
            if name == "pkg.a":
                return mod_a
            if name == "pkg.b":
                return mod_b
            return original_import(name, package)

        monkeypatch.setattr(importlib, "import_module", mock_import)

        result = bootstrap_modules(["pkg.b", "pkg.a"])

        # A should be registered before B (dependency order)
        names = [s.name for s in result]
        assert names.index("A") < names.index("B")

    def test_bootstrap_modules_orders_by_qualified_claims(
        self, registry: ComponentRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Qualified ``module::name`` claims contribute cross-module edges."""
        from s0ma import registry as registry_mod

        monkeypatch.setattr(registry_mod, "_global_registry", registry)

        spec_model = make_spec(
            "LightReading", module_path="pkg.reading_models"
        )
        spec_sense = make_spec(
            "read_light",
            module_path="pkg.senses",
            dependencies=["reading_models::LightReading"],
        )

        mod_models = _make_synthetic_module([spec_model], "pkg.reading_models")
        mod_senses = _make_synthetic_module([spec_sense], "pkg.senses")

        import importlib

        original_import = importlib.import_module

        def mock_import(name: str, package: str | None = None) -> types.ModuleType:
            if name == "pkg.reading_models":
                return mod_models
            if name == "pkg.senses":
                return mod_senses
            return original_import(name, package)

        monkeypatch.setattr(importlib, "import_module", mock_import)

        # Order is intentionally "wrong" — senses before reading_models.
        result = bootstrap_modules(["pkg.senses", "pkg.reading_models"])

        names = [s.name for s in result]
        assert names.index("LightReading") < names.index("read_light")

    def test_bootstrap_modules_detects_circular_deps(
        self, registry: ComponentRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bootstrap_modules() raises on circular module-level dependencies."""
        from s0ma import registry as registry_mod

        monkeypatch.setattr(registry_mod, "_global_registry", registry)

        spec_x = make_spec("X", module_path="pkg.x", dependencies=["Y"])
        spec_y = make_spec("Y", module_path="pkg.y", dependencies=["X"])

        mod_x = _make_synthetic_module([spec_x], "pkg.x")
        mod_y = _make_synthetic_module([spec_y], "pkg.y")

        import importlib

        original_import = importlib.import_module

        def mock_import(name: str, package: str | None = None) -> types.ModuleType:
            if name == "pkg.x":
                return mod_x
            if name == "pkg.y":
                return mod_y
            return original_import(name, package)

        monkeypatch.setattr(importlib, "import_module", mock_import)

        with pytest.raises(RegistrationError, match="[Cc]ircular"):
            bootstrap_modules(["pkg.x", "pkg.y"])

    def test_bootstrap_modules_skips_already_registered(
        self, registry: ComponentRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bootstrap_modules() skips components already in the registry."""
        from s0ma import registry as registry_mod

        monkeypatch.setattr(registry_mod, "_global_registry", registry)

        spec = make_spec("Existing", module_path="pkg.existing")
        registry.register(spec)

        mod = _make_synthetic_module(
            [spec, make_spec("New", module_path="pkg.existing")],
            "pkg.existing",
        )

        import importlib

        original_import = importlib.import_module

        def mock_import(name: str, package: str | None = None) -> types.ModuleType:
            if name == "pkg.existing":
                return mod
            return original_import(name, package)

        monkeypatch.setattr(importlib, "import_module", mock_import)

        result = bootstrap_modules(["pkg.existing"])
        # Only the new component should be returned
        assert len(result) == 1
        assert result[0].name == "New"

    def test_bootstrap_modules_empty_list(
        self, registry: ComponentRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bootstrap_modules() with empty list returns empty result."""
        from s0ma import registry as registry_mod

        monkeypatch.setattr(registry_mod, "_global_registry", registry)

        result = bootstrap_modules([])
        assert result == []
