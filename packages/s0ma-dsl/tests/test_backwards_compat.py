"""Backwards compatibility validation per PRD §2.7.4.

Verifies that mixed .s0ma and .py projects work correctly in the same
s0ma registry. Both the existing path (.py with @component → import hook →
registry) and the new path (.s0ma → transpiler → .py → import hook →
registry) must coexist without interference.
"""

from __future__ import annotations

from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(name: str, **overrides: object) -> ComponentSpec:
    """Create a valid ComponentSpec with sensible defaults."""
    defaults: dict[str, object] = {
        "name": name,
        "kind": ComponentKind.SERVICE,
        "layer": Layer.DOMAIN,
        "intent": "A test component used for backwards compatibility validation",
        "module_path": f"tests.compat.{name.lower()}",
        "qualified_name": f"tests.compat.{name.lower()}.{name}",
    }
    defaults.update(overrides)
    return ComponentSpec(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMixedRegistration:
    """Verify that @component-decorated .py and transpiled .s0ma components
    coexist in the same registry."""

    def test_py_and_s0ma_components_in_same_registry(self) -> None:
        """Register both a manually-decorated component and a transpiler-
        registered module in the same registry."""
        registry = ComponentRegistry(persist=False)

        # Simulate a .py module with @component
        py_spec = _make_spec(
            "PyComponent",
            module_path="myapp.services",
            source_file="myapp/services.py",
        )
        registry.register(py_spec)

        # Simulate a .s0ma-transpiled module via register_module + register
        registry.register_module(
            name="s0ma_module",
            layer="DOMAIN",
            version="1.0.0",
            intent="A module from a .s0ma file",
            exports=["S0maService"],
        )
        s0ma_spec = _make_spec(
            "S0maService",
            module_path="myapp.s0ma_module",
            source_file="myapp/s0ma_module.s0ma",
        )
        registry.register(s0ma_spec)

        # Both are queryable
        assert registry.get("PyComponent") is not None
        assert registry.get("S0maService") is not None
        assert registry.count() >= 2

    def test_dependencies_across_py_and_s0ma(self) -> None:
        """A .py component can declare a dependency on a .s0ma component
        and vice versa."""
        registry = ComponentRegistry(persist=False)

        # Register the s0ma-originated component first
        s0ma_spec = _make_spec(
            "S0maModel",
            kind=ComponentKind.MODEL,
            module_path="myapp.models",
        )
        registry.register(s0ma_spec)

        # Register a .py component that depends on the s0ma one
        py_spec = _make_spec(
            "PyService",
            dependencies=["S0maModel"],
            module_path="myapp.services",
        )
        registry.register(py_spec)

        # Dependency graph works
        deps = registry.get_dependencies("PyService")
        assert len(deps) == 1
        assert deps[0].name == "S0maModel"

        dependents = registry.get_dependents("S0maModel")
        assert len(dependents) == 1
        assert dependents[0].name == "PyService"

    def test_edges_across_py_and_s0ma(self) -> None:
        """Relationship edges can connect .py and .s0ma components."""
        registry = ComponentRegistry(persist=False)

        # Register both
        registry.register(_make_spec("PyFunc"))
        registry.register(_make_spec("S0maFunc"))

        # Register a cross-boundary edge
        registry.register_relationship(
            source="py_module::PyFunc",
            target="s0ma_module::S0maFunc",
            relation="CALLS",
            intent="PyFunc calls S0maFunc",
            carries="request data",
            coupling="LOOSE",
            origin="authored",
        )

        edges = registry.get_edges(source="py_module::PyFunc")
        assert len(edges) == 1
        assert edges[0].target == "s0ma_module::S0maFunc"

    def test_test_registrations_across_py_and_s0ma(self) -> None:
        """Tests from .s0ma files can validate .py components and vice versa."""
        registry = ComponentRegistry(persist=False)

        # A test from a .s0ma test file validates a .py component
        registry.register_test(
            name="s0ma_tests::test_py_service",
            intent="Tests the PyService component",
            validates=["services::PyService"],
        )

        tests = registry.get_tests_for_component("services::PyService")
        assert len(tests) == 1
        assert tests[0].name == "s0ma_tests::test_py_service"


class TestModuleMetadataCoexistence:
    """Verify that module metadata from .s0ma files doesn't interfere
    with .py modules that don't have module metadata."""

    def test_py_modules_have_no_module_metadata(self) -> None:
        """Existing .py modules don't register module metadata, and that's fine."""
        registry = ComponentRegistry(persist=False)

        # Register a .py component (no module metadata)
        registry.register(_make_spec("PyComponent"))

        # Register a .s0ma module (with module metadata)
        registry.register_module(
            name="s0ma_module",
            layer="DOMAIN",
            version="1.0.0",
            intent="A s0ma module",
            exports=["S0maComponent"],
        )
        registry.register(_make_spec("S0maComponent"))

        # Module metadata only exists for s0ma modules
        assert registry.get_module("s0ma_module") is not None
        assert registry.get_module("py_module") is None

        # Both components are still queryable
        all_components = registry.get_all()
        assert "PyComponent" in all_components
        assert "S0maComponent" in all_components

    def test_query_apis_work_with_mixed_registry(self) -> None:
        """All query APIs work even when only some modules have metadata."""
        registry = ComponentRegistry(persist=False)

        # Register mixed content
        registry.register(
            _make_spec("PyService", kind=ComponentKind.SERVICE, layer=Layer.APPLICATION)
        )
        registry.register(
            _make_spec("S0maModel", kind=ComponentKind.MODEL, layer=Layer.DOMAIN)
        )
        registry.register_module(
            name="s0ma_mod",
            layer="DOMAIN",
            version="1.0.0",
            intent="Domain models",
            exports=["S0maModel"],
        )

        # Layer queries work
        app_layer = registry.query_by_layer(Layer.APPLICATION)
        assert any(s.name == "PyService" for s in app_layer)

        domain_layer = registry.query_by_layer(Layer.DOMAIN)
        assert any(s.name == "S0maModel" for s in domain_layer)

        # Kind queries work
        services = registry.query_by_kind(ComponentKind.SERVICE)
        assert any(s.name == "PyService" for s in services)

        models = registry.query_by_kind(ComponentKind.MODEL)
        assert any(s.name == "S0maModel" for s in models)

        # Graph works
        graph = registry.get_dependency_graph()
        assert "PyService" in graph
        assert "S0maModel" in graph


class TestRegistryResetWithMixed:
    """Verify reset clears both .py and .s0ma state cleanly."""

    def test_reset_clears_all(self) -> None:
        registry = ComponentRegistry(persist=False)

        # Add mixed content
        registry.register(_make_spec("PyComp"))
        registry.register(_make_spec("S0maComp"))
        registry.register_module(
            name="s0ma_mod",
            layer="DOMAIN",
            version="1.0.0",
            intent="test",
            exports=["S0maComp"],
        )
        registry.register_relationship(
            source="mod::PyComp",
            target="s0ma_mod::S0maComp",
            relation="CALLS",
            intent="test edge",
            carries="data",
            coupling="LOOSE",
            origin="authored",
        )
        registry.register_test(
            name="tests::test_s0ma",
            intent="test",
            validates=["s0ma_mod::S0maComp"],
        )

        # Reset
        registry.reset()

        # Everything cleared
        assert registry.count() == 0
        assert registry.get_all_modules() == {}
        assert registry.get_edges() == []
        assert registry.get_all_tests() == {}


class TestPublicNerveCoverageWithMixed:
    """Coverage queries work with mixed .s0ma/.py content."""

    def test_coverage_only_includes_s0ma_modules(self) -> None:
        """get_public_nerve_coverage only reports modules with metadata
        (i.e., .s0ma modules that called register_module). Pure .py
        modules without metadata are not included."""
        registry = ComponentRegistry(persist=False)

        # .py component (no module metadata)
        registry.register(_make_spec("PyService"))

        # .s0ma module (with metadata)
        registry.register_module(
            name="s0ma_mod",
            layer="DOMAIN",
            version="1.0.0",
            intent="test",
            exports=["S0maService"],
        )
        registry.register(_make_spec("S0maService"))

        coverage = registry.get_public_nerve_coverage()

        # Only s0ma module exports appear
        assert "s0ma_mod::S0maService" in coverage
        # PyService has no module metadata, so it's not in coverage
        assert not any("PyService" in k for k in coverage)
