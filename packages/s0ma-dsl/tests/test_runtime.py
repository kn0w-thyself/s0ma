"""Integration tests for the runtime bridge registration functions.

Tests M14: Runtime Registry Expansion — verifies that the transpiler's
runtime bridge correctly registers modules, constants, types,
relationships, and tests in the s0ma ComponentRegistry.

Covers:
- Task 14.2: register_module()
- Task 14.3: register_constant() and register_type()
- Task 14.4: register_relationship()
- Task 14.5: register_test()
- Task 14.6: Edge storage queries
- Task 14.7: Runtime bridge adapter layer
"""

from __future__ import annotations

import pytest
from s0ma.models import ModuleMetadata, RelationshipEdge, TestRegistration
from s0ma.registry import ComponentRegistry, reset_registry
from s0ma.types import Layer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset the global registry before and after each test."""
    reset_registry()
    yield
    reset_registry()


@pytest.fixture()
def registry() -> ComponentRegistry:
    """Create a fresh non-persisting registry for test isolation."""
    return ComponentRegistry(persist=False)


# ======================================================================
# Task 14.2 — register_module()
# ======================================================================


class TestRegisterModule:
    """Tests for registry.register_module()."""

    def test_register_module_basic(self, registry: ComponentRegistry) -> None:
        """Module metadata is stored and retrievable."""
        meta = registry.register_module(
            name="signal_processor",
            layer="DOMAIN",
            version="1.0.0",
            intent="Process signals from sensors",
            exports=["process_signal", "SignalConfig"],
        )

        assert isinstance(meta, ModuleMetadata)
        assert meta.name == "signal_processor"
        assert meta.layer == "DOMAIN"
        assert meta.version == "1.0.0"
        assert meta.exports == ["process_signal", "SignalConfig"]

    def test_register_module_retrievable(self, registry: ComponentRegistry) -> None:
        """Registered module is retrievable via get_module()."""
        registry.register_module(
            name="routing",
            layer="APPLICATION",
            version="0.2.0",
            intent="Route requests to handlers",
        )

        result = registry.get_module("routing")
        assert result is not None
        assert result.name == "routing"
        assert result.layer == "APPLICATION"

    def test_register_module_with_tags(self, registry: ComponentRegistry) -> None:
        """Module tags are preserved."""
        meta = registry.register_module(
            name="auth",
            layer="INFRASTRUCTURE",
            version="1.0.0",
            intent="Authentication and authorization",
            exports=["authenticate"],
            tags=["security", "core"],
        )

        assert meta.tags == ["security", "core"]

    def test_register_module_idempotent(self, registry: ComponentRegistry) -> None:
        """Re-registering the same module replaces the entry."""
        registry.register_module(
            name="auth",
            layer="DOMAIN",
            version="1.0.0",
            intent="First version of intent text",
        )
        registry.register_module(
            name="auth",
            layer="DOMAIN",
            version="2.0.0",
            intent="Updated version of intent text",
        )

        result = registry.get_module("auth")
        assert result is not None
        assert result.version == "2.0.0"

    def test_get_all_modules(self, registry: ComponentRegistry) -> None:
        """get_all_modules() returns all registered modules."""
        registry.register_module(
            name="mod_a",
            layer="DOMAIN",
            version="1.0.0",
            intent="Module A description",
        )
        registry.register_module(
            name="mod_b",
            layer="APPLICATION",
            version="1.0.0",
            intent="Module B description",
        )

        all_modules = registry.get_all_modules()
        assert len(all_modules) == 2
        assert "mod_a" in all_modules
        assert "mod_b" in all_modules

    def test_get_module_nonexistent(self, registry: ComponentRegistry) -> None:
        """get_module() returns None for unknown modules."""
        assert registry.get_module("nonexistent") is None

    def test_module_metadata_to_dict(self) -> None:
        """ModuleMetadata serialization round-trips correctly."""
        meta = ModuleMetadata(
            name="test_mod",
            layer="DOMAIN",
            version="1.0.0",
            intent="Testing module metadata",
            exports=["foo"],
            content_hash="abc123",
            tags=["test"],
            source_file="/tmp/test.s0ma",
        )
        d = meta.to_dict()
        restored = ModuleMetadata.from_dict(d)
        assert restored.name == meta.name
        assert restored.exports == meta.exports
        assert restored.content_hash == meta.content_hash
        assert restored.tags == meta.tags


# ======================================================================
# Task 14.3 — register_constant() and register_type()
# ======================================================================


class TestRegisterConstantAndType:
    """Tests for registry.register_constant() and register_type()."""

    def test_register_constant(self, registry: ComponentRegistry) -> None:
        """CONSTANT cells are registered as MODEL components with kind_detail."""
        spec = registry.register_constant(
            name="MAX_RETRIES",
            layer="DOMAIN",
            intent="Maximum retry count for transient failures",
            metadata={"visibility": "PUBLIC", "schema": "int"},
        )

        assert spec.name == "MAX_RETRIES"
        assert spec.kind.name == "MODEL"
        assert spec.layer.name == "DOMAIN"
        assert spec.metadata["kind_detail"] == "CONSTANT"
        assert spec.metadata["visibility"] == "PUBLIC"

    def test_register_type(self, registry: ComponentRegistry) -> None:
        """TYPE cells are registered as MODEL components with kind_detail."""
        spec = registry.register_type(
            name="SignalData",
            layer="DOMAIN",
            intent="Type alias for processed signal data structures",
            metadata={"visibility": "PUBLIC", "schema": "dict[str, float]"},
        )

        assert spec.name == "SignalData"
        assert spec.kind.name == "MODEL"
        assert spec.metadata["kind_detail"] == "TYPE"

    def test_constant_in_registry(self, registry: ComponentRegistry) -> None:
        """Constants are retrievable via the standard get() API."""
        registry.register_constant(
            name="DEFAULT_TIMEOUT",
            layer="INFRASTRUCTURE",
            intent="Default timeout for all external requests",
        )

        result = registry.get("DEFAULT_TIMEOUT")
        assert result is not None
        assert result.metadata["kind_detail"] == "CONSTANT"

    def test_type_in_registry(self, registry: ComponentRegistry) -> None:
        """Types are retrievable via the standard get() API."""
        registry.register_type(
            name="EventPayload",
            layer="DOMAIN",
            intent="Type alias for event payload structures",
        )

        result = registry.get("EventPayload")
        assert result is not None
        assert result.metadata["kind_detail"] == "TYPE"

    def test_constant_idempotent(self, registry: ComponentRegistry) -> None:
        """Re-registering the same constant is idempotent."""
        registry.register_constant(
            name="PI",
            layer="DOMAIN",
            intent="Mathematical constant for circle calculations",
        )
        # Should not raise
        registry.register_constant(
            name="PI",
            layer="DOMAIN",
            intent="Mathematical constant for circle calculations",
        )

    def test_kind_detail_defaults(self, registry: ComponentRegistry) -> None:
        """kind_detail is set even when metadata is None."""
        spec = registry.register_constant(
            name="ZERO",
            layer="DOMAIN",
            intent="Zero constant for comparison operations",
        )
        assert spec.metadata["kind_detail"] == "CONSTANT"

        spec2 = registry.register_type(
            name="ID",
            layer="DOMAIN",
            intent="Type alias for unique identifier strings",
        )
        assert spec2.metadata["kind_detail"] == "TYPE"


# ======================================================================
# Task 14.4 — register_relationship()
# ======================================================================


class TestRegisterRelationship:
    """Tests for registry.register_relationship()."""

    def test_register_relationship_basic(self, registry: ComponentRegistry) -> None:
        """Relationship edges are stored and retrievable."""
        edge = registry.register_relationship(
            source="signal_processor::process",
            target="models::SignalConfig",
            relation="READS",
            intent="Reads signal configuration",
            carries="SignalConfig",
            coupling="LOOSE",
        )

        assert isinstance(edge, RelationshipEdge)
        assert edge.source == "signal_processor::process"
        assert edge.target == "models::SignalConfig"
        assert edge.relation == "READS"
        assert edge.coupling == "LOOSE"
        assert edge.origin == "authored"

    def test_get_edges_all(self, registry: ComponentRegistry) -> None:
        """get_edges() returns all edges when no filters provided."""
        registry.register_relationship(
            source="a::x", target="b::y", relation="CALLS",
        )
        registry.register_relationship(
            source="a::x", target="c::z", relation="READS",
        )

        edges = registry.get_edges()
        assert len(edges) == 2

    def test_get_edges_filter_source(self, registry: ComponentRegistry) -> None:
        """get_edges() filters by source."""
        registry.register_relationship(
            source="mod_a::fn1", target="mod_b::fn2", relation="CALLS",
        )
        registry.register_relationship(
            source="mod_c::fn3", target="mod_b::fn2", relation="CALLS",
        )

        edges = registry.get_edges(source="mod_a::fn1")
        assert len(edges) == 1
        assert edges[0].source == "mod_a::fn1"

    def test_get_edges_filter_target(self, registry: ComponentRegistry) -> None:
        """get_edges() filters by target."""
        registry.register_relationship(
            source="a::x", target="shared::util", relation="CALLS",
        )
        registry.register_relationship(
            source="b::y", target="shared::util", relation="READS",
        )
        registry.register_relationship(
            source="c::z", target="other::thing", relation="CALLS",
        )

        edges = registry.get_edges(target="shared::util")
        assert len(edges) == 2

    def test_get_edges_filter_relation(self, registry: ComponentRegistry) -> None:
        """get_edges() filters by relation type."""
        registry.register_relationship(
            source="a::x", target="b::y", relation="CALLS",
        )
        registry.register_relationship(
            source="a::x", target="b::y", relation="RAISES",
            origin="derived",
        )

        calls = registry.get_edges(relation="CALLS")
        assert len(calls) == 1
        assert calls[0].relation == "CALLS"

    def test_get_edges_filter_origin(self, registry: ComponentRegistry) -> None:
        """get_edges() filters by origin (authored vs derived)."""
        registry.register_relationship(
            source="a::x", target="b::y", relation="CALLS",
            origin="authored",
        )
        registry.register_relationship(
            source="a::x", target="c::z", relation="RAISES",
            origin="derived",
        )

        authored = registry.get_edges(origin="authored")
        assert len(authored) == 1
        assert authored[0].origin == "authored"

        derived = registry.get_edges(origin="derived")
        assert len(derived) == 1
        assert derived[0].origin == "derived"

    def test_relationship_idempotent_replace(self, registry: ComponentRegistry) -> None:
        """Re-registering same (source, target, relation) replaces the edge."""
        registry.register_relationship(
            source="a::x", target="b::y", relation="CALLS",
            intent="Original intent",
        )
        registry.register_relationship(
            source="a::x", target="b::y", relation="CALLS",
            intent="Updated intent",
        )

        edges = registry.get_edges()
        assert len(edges) == 1
        assert edges[0].intent == "Updated intent"

    def test_get_edges_combined_filters(self, registry: ComponentRegistry) -> None:
        """Multiple filters are ANDed together."""
        registry.register_relationship(
            source="a::x", target="b::y", relation="CALLS", origin="authored",
        )
        registry.register_relationship(
            source="a::x", target="b::y", relation="RAISES", origin="derived",
        )
        registry.register_relationship(
            source="c::z", target="b::y", relation="CALLS", origin="authored",
        )

        edges = registry.get_edges(source="a::x", relation="CALLS")
        assert len(edges) == 1
        assert edges[0].target == "b::y"

    def test_relationship_edge_serialization(self) -> None:
        """RelationshipEdge round-trips through to_dict/from_dict."""
        edge = RelationshipEdge(
            source="mod::fn",
            target="other::cls",
            relation="CONSTRUCTS",
            intent="Creates instance",
            carries="MyClass",
            coupling="TIGHT",
            origin="authored",
        )
        d = edge.to_dict()
        restored = RelationshipEdge.from_dict(d)
        assert restored.source == edge.source
        assert restored.coupling == edge.coupling
        assert restored.origin == edge.origin


# ======================================================================
# Task 14.5 — register_test()
# ======================================================================


class TestRegisterTest:
    """Tests for registry.register_test()."""

    def test_register_test_basic(self, registry: ComponentRegistry) -> None:
        """Test registrations are stored and retrievable."""
        reg = registry.register_test(
            name="signal_processor::test_process_valid",
            intent="Validates process_signal with valid input",
            validates=["signal_processor::process_signal"],
        )

        assert isinstance(reg, TestRegistration)
        assert reg.name == "signal_processor::test_process_valid"
        assert reg.validates == ["signal_processor::process_signal"]

    def test_get_test(self, registry: ComponentRegistry) -> None:
        """Registered tests are retrievable via get_test()."""
        registry.register_test(
            name="auth::test_login",
            intent="Validates login authentication flow",
            validates=["auth::authenticate"],
        )

        result = registry.get_test("auth::test_login")
        assert result is not None
        assert result.intent == "Validates login authentication flow"

    def test_get_test_nonexistent(self, registry: ComponentRegistry) -> None:
        """get_test() returns None for unknown tests."""
        assert registry.get_test("nonexistent") is None

    def test_get_all_tests(self, registry: ComponentRegistry) -> None:
        """get_all_tests() returns all registered tests."""
        registry.register_test(
            name="mod::test_a",
            intent="Test A validates component A",
            validates=["mod::comp_a"],
        )
        registry.register_test(
            name="mod::test_b",
            intent="Test B validates component B",
            validates=["mod::comp_b"],
        )

        all_tests = registry.get_all_tests()
        assert len(all_tests) == 2

    def test_get_tests_for_component(self, registry: ComponentRegistry) -> None:
        """get_tests_for_component() finds tests validating a component."""
        registry.register_test(
            name="mod::test_a",
            intent="Test A validates X and Y",
            validates=["mod::x", "mod::y"],
        )
        registry.register_test(
            name="mod::test_b",
            intent="Test B validates Y and Z",
            validates=["mod::y", "mod::z"],
        )
        registry.register_test(
            name="mod::test_c",
            intent="Test C validates Z only",
            validates=["mod::z"],
        )

        tests_for_y = registry.get_tests_for_component("mod::y")
        assert len(tests_for_y) == 2
        names = {t.name for t in tests_for_y}
        assert names == {"mod::test_a", "mod::test_b"}

    def test_register_test_idempotent(self, registry: ComponentRegistry) -> None:
        """Re-registering same test name replaces the entry."""
        registry.register_test(
            name="mod::test_x",
            intent="Original test intent text",
            validates=["mod::comp_a"],
        )
        registry.register_test(
            name="mod::test_x",
            intent="Updated test intent text",
            validates=["mod::comp_a", "mod::comp_b"],
        )

        result = registry.get_test("mod::test_x")
        assert result is not None
        assert result.intent == "Updated test intent text"
        assert len(result.validates) == 2

    def test_test_registration_serialization(self) -> None:
        """TestRegistration round-trips through to_dict/from_dict."""
        reg = TestRegistration(
            name="mod::test_fn",
            intent="Verifies the function works",
            validates=["mod::fn_a", "mod::fn_b"],
            source_file="/tmp/test.py",
        )
        d = reg.to_dict()
        restored = TestRegistration.from_dict(d)
        assert restored.name == reg.name
        assert restored.validates == reg.validates
        assert restored.source_file == reg.source_file


# ======================================================================
# Task 14.6 — Registry reset clears expanded stores
# ======================================================================


class TestRegistryReset:
    """Tests that reset() clears all expanded stores."""

    def test_reset_clears_modules(self, registry: ComponentRegistry) -> None:
        """reset() clears module metadata."""
        registry.register_module(
            name="mod_x",
            layer="DOMAIN",
            version="1.0.0",
            intent="Module X for testing reset",
        )
        assert registry.get_module("mod_x") is not None

        registry.reset()
        assert registry.get_module("mod_x") is None
        assert registry.get_all_modules() == {}

    def test_reset_clears_edges(self, registry: ComponentRegistry) -> None:
        """reset() clears all relationship edges."""
        registry.register_relationship(
            source="a::x", target="b::y", relation="CALLS",
        )
        assert len(registry.get_edges()) == 1

        registry.reset()
        assert registry.get_edges() == []

    def test_reset_clears_tests(self, registry: ComponentRegistry) -> None:
        """reset() clears all test registrations."""
        registry.register_test(
            name="mod::test_fn",
            intent="Test function for testing reset",
            validates=["mod::fn"],
        )
        assert registry.get_test("mod::test_fn") is not None

        registry.reset()
        assert registry.get_test("mod::test_fn") is None
        assert registry.get_all_tests() == {}


# ======================================================================
# Task 14.7 — Runtime bridge adapter
# ======================================================================


class TestRuntimeBridge:
    """Tests for the runtime bridge adapter layer."""

    def test_bridge_import(self) -> None:
        """All registration functions are importable from the bridge."""
        from s0ma_dsl.runtime_bridge.registration import (
            register_constant,
            register_module,
            register_relationship,
            register_test,
            register_type,
        )

        assert callable(register_module)
        assert callable(register_constant)
        assert callable(register_type)
        assert callable(register_relationship)
        assert callable(register_test)

    def test_bridge_register_module(self) -> None:
        """Bridge register_module() accepts Layer enum and delegates."""
        from s0ma_dsl.runtime_bridge.registration import register_module

        meta = register_module(
            name="bridge_test",
            layer=Layer.DOMAIN,
            version="1.0.0",
            intent="Testing bridge module registration",
            exports=["foo"],
        )

        assert meta.name == "bridge_test"
        assert meta.layer == "DOMAIN"

    def test_bridge_register_constant(self) -> None:
        """Bridge register_constant() accepts Layer enum."""
        from s0ma_dsl.runtime_bridge.registration import register_constant

        register_constant(
            name="BRIDGE_CONST",
            layer=Layer.DOMAIN,
            intent="Testing bridge constant registration",
        )

    def test_bridge_register_type(self) -> None:
        """Bridge register_type() accepts Layer enum."""
        from s0ma_dsl.runtime_bridge.registration import register_type

        register_type(
            name="BridgeType",
            layer=Layer.DOMAIN,
            intent="Testing bridge type alias registration",
        )

    def test_bridge_register_relationship(self) -> None:
        """Bridge register_relationship() works end-to-end."""
        from s0ma_dsl.runtime_bridge.registration import register_relationship

        edge = register_relationship(
            source="mod::src",
            target="mod::tgt",
            relation="CALLS",
            intent="Test bridge relationship",
            carries="SomeData",
            coupling="LOOSE",
        )

        assert edge.origin == "authored"

    def test_bridge_register_test(self) -> None:
        """Bridge register_test() works end-to-end."""
        from s0ma_dsl.runtime_bridge.registration import register_test

        reg = register_test(
            name="mod::test_fn",
            intent="Testing bridge test registration",
            validates=["mod::fn_a"],
        )

        assert reg.validates == ["mod::fn_a"]

    def test_bridge_functions_are_components(self) -> None:
        """All bridge functions are registered s0ma components."""
        from s0ma.decorators import is_component

        from s0ma_dsl.runtime_bridge.registration import (
            register_constant,
            register_module,
            register_relationship,
            register_test,
            register_type,
        )

        assert is_component(register_module)
        assert is_component(register_constant)
        assert is_component(register_type)
        assert is_component(register_relationship)
        assert is_component(register_test)


# ======================================================================
# SQLite persistence
# ======================================================================


class TestSQLitePersistence:
    """Tests that expanded stores survive SQLite round-trips."""

    def test_module_persistence(self, tmp_path) -> None:
        """Module metadata persists across registry instances."""
        db = tmp_path / "test.db"

        reg1 = ComponentRegistry(persist=True, db_path=db)
        reg1.register_module(
            name="persisted_mod",
            layer="DOMAIN",
            version="1.0.0",
            intent="Module that should persist",
            exports=["foo"],
            tags=["test"],
        )
        reg1.close()

        reg2 = ComponentRegistry(persist=True, db_path=db)
        meta = reg2.get_module("persisted_mod")
        assert meta is not None
        assert meta.name == "persisted_mod"
        assert meta.exports == ["foo"]
        assert meta.tags == ["test"]
        reg2.close()

    def test_edge_persistence(self, tmp_path) -> None:
        """Relationship edges persist across registry instances."""
        db = tmp_path / "test.db"

        reg1 = ComponentRegistry(persist=True, db_path=db)
        reg1.register_relationship(
            source="a::x",
            target="b::y",
            relation="CALLS",
            intent="Persisted edge",
            coupling="TIGHT",
        )
        reg1.close()

        reg2 = ComponentRegistry(persist=True, db_path=db)
        edges = reg2.get_edges()
        assert len(edges) == 1
        assert edges[0].source == "a::x"
        assert edges[0].coupling == "TIGHT"
        reg2.close()

    def test_test_registration_persistence(self, tmp_path) -> None:
        """Test registrations persist across registry instances."""
        db = tmp_path / "test.db"

        reg1 = ComponentRegistry(persist=True, db_path=db)
        reg1.register_test(
            name="mod::test_fn",
            intent="Persisted test registration",
            validates=["mod::fn_a", "mod::fn_b"],
        )
        reg1.close()

        reg2 = ComponentRegistry(persist=True, db_path=db)
        reg = reg2.get_test("mod::test_fn")
        assert reg is not None
        assert reg.validates == ["mod::fn_a", "mod::fn_b"]
        reg2.close()
