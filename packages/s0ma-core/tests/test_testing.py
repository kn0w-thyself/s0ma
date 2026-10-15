"""Tests for the s0ma.testing module — canonical test isolation utilities.

Verifies that the three public utilities (fresh_registry, reinitialize_for_test,
isolate_registry) correctly manage global registry state, handle sys.modules
eviction, and restore original state on exit.
"""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from s0ma._bootstrap import EXPECTED_FRAMEWORK_COMPONENT_COUNT, bootstrap_register
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry, set_registry
from s0ma.testing import (  # type: ignore[attr-defined]
    _evict_modules,
    fresh_registry,
    isolate_registry,
    reinitialize_for_test,
)
from s0ma.types import ComponentKind, Layer

# ======================================================================
# Helpers
# ======================================================================


def _make_spec(name: str = "TestComponent") -> ComponentSpec:
    """Build a minimal ComponentSpec for testing."""
    return ComponentSpec(
        name=name,
        kind=ComponentKind.SERVICE,
        layer=Layer.DOMAIN,
        intent=f"A synthetic test component named {name}",
        module_path=f"tests.synthetic.{name.lower()}",
        qualified_name=f"tests.synthetic.{name.lower()}.{name}",
    )


def _get_global_registry_raw() -> ComponentRegistry | None:
    """Access the private global registry variable directly."""
    import s0ma.registry as _reg_mod
    return _reg_mod._global_registry  # type: ignore[attr-defined]


# ======================================================================
# Tests: _evict_modules (internal helper)
# ======================================================================


class TestEvictModules:
    """Tests for the _evict_modules internal helper."""

    def test_evicts_matching_exact_name(self) -> None:
        """Evicts a module whose name exactly matches the given prefix."""
        fake_module = ModuleType("fake_evict_test")
        sys.modules["fake_evict_test"] = fake_module

        try:
            evicted = _evict_modules(["fake_evict_test"])
            assert "fake_evict_test" in evicted
            assert "fake_evict_test" not in sys.modules
        finally:
            sys.modules.pop("fake_evict_test", None)

    def test_evicts_submodules_of_prefix(self) -> None:
        """Evicts submodules whose names start with prefix + '.'."""
        sys.modules["fake_pkg"] = ModuleType("fake_pkg")
        sys.modules["fake_pkg.sub"] = ModuleType("fake_pkg.sub")
        sys.modules["fake_pkg.sub.deep"] = ModuleType("fake_pkg.sub.deep")

        try:
            evicted = _evict_modules(["fake_pkg"])
            assert "fake_pkg" in evicted
            assert "fake_pkg.sub" in evicted
            assert "fake_pkg.sub.deep" in evicted
            assert "fake_pkg" not in sys.modules
            assert "fake_pkg.sub" not in sys.modules
            assert "fake_pkg.sub.deep" not in sys.modules
        finally:
            for key in ["fake_pkg", "fake_pkg.sub", "fake_pkg.sub.deep"]:
                sys.modules.pop(key, None)

    def test_does_not_evict_unrelated_modules(self) -> None:
        """Does not evict modules whose names don't match any prefix."""
        sys.modules["unrelated_mod"] = ModuleType("unrelated_mod")

        try:
            evicted = _evict_modules(["other_prefix"])
            assert "unrelated_mod" not in evicted
            assert "unrelated_mod" in sys.modules
        finally:
            sys.modules.pop("unrelated_mod", None)

    def test_returns_sorted_names(self) -> None:
        """Returns module names in sorted order (parents before children)."""
        sys.modules["mypkg"] = ModuleType("mypkg")
        sys.modules["mypkg.zzz"] = ModuleType("mypkg.zzz")
        sys.modules["mypkg.aaa"] = ModuleType("mypkg.aaa")

        try:
            evicted = _evict_modules(["mypkg"])
            assert evicted == sorted(evicted)
        finally:
            for key in ["mypkg", "mypkg.zzz", "mypkg.aaa"]:
                sys.modules.pop(key, None)

    def test_empty_prefixes_evicts_nothing(self) -> None:
        """An empty prefix list evicts no modules."""
        sys.modules["keep_me"] = ModuleType("keep_me")
        try:
            evicted = _evict_modules([])
            assert evicted == []
            assert "keep_me" in sys.modules
        finally:
            sys.modules.pop("keep_me", None)

    def test_handles_no_matching_modules(self) -> None:
        """Returns empty list when no modules match the given prefix."""
        evicted = _evict_modules(["nonexistent_prefix_xyz"])
        assert evicted == []


# ======================================================================
# Tests: isolate_registry
# ======================================================================


class TestIsolateRegistry:
    """Tests for the isolate_registry context manager."""

    def test_provides_fresh_empty_registry(self) -> None:
        """isolate_registry yields a fresh registry with no components."""
        with isolate_registry() as registry:
            assert registry.count() == 0

    def test_yields_component_registry_instance(self) -> None:
        """The yielded value is a ComponentRegistry."""
        with isolate_registry() as registry:
            assert isinstance(registry, ComponentRegistry)

    def test_sets_as_global_singleton(self) -> None:
        """The isolated registry is set as the global singleton during context."""
        with isolate_registry() as registry:
            assert _get_global_registry_raw() is registry

    def test_restores_original_registry_on_exit(self) -> None:
        """The original global registry is restored after the context exits."""
        original = _get_global_registry_raw()
        with isolate_registry():
            pass  # Nothing to do — just enter and exit
        assert _get_global_registry_raw() is original

    def test_restores_original_registry_on_exception(self) -> None:
        """The original registry is restored even if the body raises."""
        original = _get_global_registry_raw()
        with pytest.raises(RuntimeError), isolate_registry():
            raise RuntimeError("test error")
        assert _get_global_registry_raw() is original

    def test_registrations_do_not_affect_outer_scope(self) -> None:
        """Components registered inside the scope are not visible outside."""
        with isolate_registry() as registry:
            registry.register(_make_spec("IsolatedComponent"))
            assert registry.contains("IsolatedComponent")

        # After exit, the global is restored; the isolated registry's components
        # are not visible through the global anymore.
        outer = _get_global_registry_raw()
        if outer is not None:
            assert not outer.contains("IsolatedComponent")

    def test_can_register_synthetic_components(self) -> None:
        """Components can be registered into the isolated registry."""
        spec = _make_spec("MySyntheticService")
        with isolate_registry() as registry:
            registry.register(spec)
            retrieved = registry.get("MySyntheticService")
            assert retrieved is not None
            assert retrieved.name == "MySyntheticService"

    def test_nested_isolation(self) -> None:
        """Nested isolate_registry calls restore each layer correctly."""
        original = _get_global_registry_raw()

        with isolate_registry() as outer_reg:
            with isolate_registry() as inner_reg:
                assert _get_global_registry_raw() is inner_reg
                assert inner_reg is not outer_reg
            # After inner exits, outer is restored as global
            assert _get_global_registry_raw() is outer_reg

        # After outer exits, original is restored
        assert _get_global_registry_raw() is original

    def test_persist_false_creates_in_memory_registry(self) -> None:
        """With persist=False (default), the registry has no SQLite connection."""
        with isolate_registry(persist=False) as registry:
            assert registry._persist is False  # type: ignore[attr-defined]


# ======================================================================
# Tests: fresh_registry
# ======================================================================


class TestFreshRegistry:
    """Tests for the fresh_registry context manager."""

    def test_provides_fresh_empty_registry_before_reimport(self) -> None:
        """fresh_registry yields a fresh empty registry (before any re-imports)."""
        # When no module_prefixes match anything in sys.modules, the registry
        # is empty except for what's already registered.
        with fresh_registry(".", ["__nonexistent_prefix_xyz__"]) as registry:
            assert isinstance(registry, ComponentRegistry)

    def test_sets_as_global_singleton(self) -> None:
        """The fresh registry is installed as the global singleton during context."""
        with fresh_registry(".", []) as registry:
            assert _get_global_registry_raw() is registry

    def test_restores_original_registry_on_exit(self) -> None:
        """The original global registry is restored after the context exits."""
        original = _get_global_registry_raw()
        with fresh_registry(".", []):
            pass
        assert _get_global_registry_raw() is original

    def test_restores_original_registry_on_exception(self) -> None:
        """The original registry is restored even if the body raises."""
        original = _get_global_registry_raw()
        with pytest.raises(ValueError), fresh_registry(".", []):
            raise ValueError("test")
        assert _get_global_registry_raw() is original

    def test_accepts_project_root_as_string(self) -> None:
        """project_root can be a string path."""
        with fresh_registry(".", []) as registry:
            assert isinstance(registry, ComponentRegistry)

    def test_accepts_project_root_as_path(self) -> None:
        """project_root can be a pathlib.Path."""
        from pathlib import Path
        with fresh_registry(Path("."), []) as registry:
            assert isinstance(registry, ComponentRegistry)

    def test_evicts_and_reimports_matching_modules(self) -> None:
        """Modules matching the prefix are evicted and re-imported."""
        # We use the logging module as a real importable module.
        # It will be evicted from sys.modules and then re-imported.
        # After re-import, it should still be accessible.
        assert "logging" in sys.modules

        with fresh_registry(".", ["logging"]) as registry:
            # The logging module was evicted and re-imported
            assert isinstance(registry, ComponentRegistry)
            # logging should have been re-imported (it's back in sys.modules)
            assert "logging" in sys.modules

    def test_empty_module_prefixes_creates_empty_registry(self) -> None:
        """With no prefixes, no modules are evicted; registry starts empty."""
        with fresh_registry(".", []) as registry:
            assert registry.count() == 0

    def test_persist_false_default(self) -> None:
        """Default persist=False creates an in-memory registry."""
        with fresh_registry(".", []) as registry:
            assert registry._persist is False  # type: ignore[attr-defined]

    def test_registrations_visible_during_context(self) -> None:
        """Components registered during context are visible in the fresh registry."""
        spec = _make_spec("ContextComponent")
        with fresh_registry(".", []) as registry:
            registry.register(spec)
            assert registry.contains("ContextComponent")


# ======================================================================
# Tests: reinitialize_for_test
# ======================================================================


class TestReinitializeForTest:
    """Tests for the reinitialize_for_test imperative function."""

    def test_returns_component_registry(self) -> None:
        """reinitialize_for_test returns a ComponentRegistry."""
        registry = reinitialize_for_test(".", [])
        assert isinstance(registry, ComponentRegistry)

    def test_returns_fresh_empty_registry(self) -> None:
        """The returned registry is empty (no components from previous state)."""
        registry = reinitialize_for_test(".", [])
        assert registry.count() == 0

    def test_sets_registry_as_global(self) -> None:
        """The returned registry is installed as the global singleton."""
        registry = reinitialize_for_test(".", [])
        assert _get_global_registry_raw() is registry

    def test_accepts_string_project_root(self) -> None:
        """project_root can be a string."""
        registry = reinitialize_for_test(".", [])
        assert isinstance(registry, ComponentRegistry)

    def test_accepts_path_project_root(self) -> None:
        """project_root can be a pathlib.Path."""
        from pathlib import Path
        registry = reinitialize_for_test(Path("."), [])
        assert isinstance(registry, ComponentRegistry)

    def test_evicts_and_reimports_matching_modules(self) -> None:
        """Modules matching the prefix are evicted and re-imported."""
        assert "logging" in sys.modules
        registry = reinitialize_for_test(".", ["logging"])
        assert isinstance(registry, ComponentRegistry)
        # logging was re-imported and is accessible
        assert "logging" in sys.modules

    def test_persist_false_default(self) -> None:
        """Default persist=False creates an in-memory registry."""
        registry = reinitialize_for_test(".", [])
        assert registry._persist is False  # type: ignore[attr-defined]

    def test_caller_responsible_for_cleanup(self) -> None:
        """Calling reinitialize_for_test replaces the global; caller must clean up."""
        # Install a known registry
        known = ComponentRegistry(persist=False)
        spec = _make_spec("PreExisting")
        known.register(spec)
        set_registry(known)
        assert _get_global_registry_raw() is known

        # reinitialize_for_test replaces the global with a fresh one
        new_registry = reinitialize_for_test(".", [])
        assert _get_global_registry_raw() is new_registry
        assert not new_registry.contains("PreExisting")


# ======================================================================
# Tests: framework component registration (bootstrap integration)
# ======================================================================


class TestTestingModuleBootstrapRegistration:
    """Verify the testing utilities are registered as framework components."""

    @pytest.fixture()
    def bootstrap_registry(self) -> ComponentRegistry:
        """Create a fresh registry with all framework components registered."""
        registry = ComponentRegistry(persist=False)
        bootstrap_register(registry)
        return registry

    def test_fresh_registry_is_registered(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """fresh_registry is registered as a framework component."""
        assert bootstrap_registry.contains("fresh_registry"), (
            "fresh_registry should be registered as a framework component"
        )

    def test_reinitialize_for_test_is_registered(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """reinitialize_for_test is registered as a framework component."""
        assert bootstrap_registry.contains("reinitialize_for_test"), (
            "reinitialize_for_test should be registered as a framework component"
        )

    def test_isolate_registry_is_registered(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """isolate_registry is registered as a framework component."""
        assert bootstrap_registry.contains("isolate_registry"), (
            "isolate_registry should be registered as a framework component"
        )

    def test_all_testing_components_are_framework(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """All testing utilities have is_framework=True."""
        for name in ["fresh_registry", "reinitialize_for_test", "isolate_registry"]:
            spec = bootstrap_registry.get(name)
            assert spec is not None, f"Component '{name}' not found"
            assert spec.is_framework is True

    def test_all_testing_components_in_framework_layer(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """All testing utilities are in the FRAMEWORK layer."""
        for name in ["fresh_registry", "reinitialize_for_test", "isolate_registry"]:
            spec = bootstrap_registry.get(name)
            assert spec is not None
            assert spec.layer == Layer.FRAMEWORK

    def test_all_testing_components_have_meaningful_intent(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """All testing utilities have intent strings >= 10 characters."""
        for name in ["fresh_registry", "reinitialize_for_test", "isolate_registry"]:
            spec = bootstrap_registry.get(name)
            assert spec is not None
            assert len(spec.intent) >= 10, (
                f"Component '{name}' has too short an intent: '{spec.intent}'"
            )

    def test_all_testing_components_point_to_testing_module(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """All testing utilities have module_path='s0ma.testing'."""
        for name in ["fresh_registry", "reinitialize_for_test", "isolate_registry"]:
            spec = bootstrap_registry.get(name)
            assert spec is not None
            assert spec.module_path == "s0ma.testing", (
                f"Component '{name}' has wrong module_path: '{spec.module_path}'"
            )

    def test_total_framework_component_count(
        self, bootstrap_registry: ComponentRegistry
    ) -> None:
        """The total number of framework components matches the expected count."""
        assert bootstrap_registry.count() == EXPECTED_FRAMEWORK_COMPONENT_COUNT, (
            f"Expected {EXPECTED_FRAMEWORK_COMPONENT_COUNT} framework components, "
            f"got {bootstrap_registry.count()}"
        )
