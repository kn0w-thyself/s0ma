"""Tests for the namespace services (Milestone 6) and cross-module
dependency resolution (Milestone 8).

Covers:
  Milestone 6:
  - Code namespace contains local + uses + requires names
  - Component-reference namespace excludes requires names
  - Public API namespace reflects exports
  - Registry namespace stub contains local declarations
  - Alias-aware lookup for both uses and requires
  - Collision detection: local vs. local, local vs. uses, uses vs. uses,
    local vs. requires, uses vs. requires

  Milestone 8:
  - Phase 1: Module graph + cycle detection
  - Phase 2: Export validation (DOES_NOT_EXIST, NOT_EXPORTED)
  - Phase 3: External validation (MISSING_PACKAGE)
  - Phase 4: Usage verification (vestigial uses/requires, evidence rules)
  - Standalone axon cross-module validation (DUPLICATE_AXON, local target)
  - Strictness mode severity differences
  - Valid cross-module resolution (no errors)
"""

from __future__ import annotations

import pytest

from s0ma_dsl.ast_nodes.enums import (
    Coupling,
    EvaluatesAt,
    Kind,
    Layer,
    Relation,
    Visibility,
)
from s0ma_dsl.ast_nodes.nodes import (
    CellDecl,
    GanglionDecl,
    InlineAxon,
    ModuleDecl,
    NerveDecl,
    RequiresEntry,
    S0maModule,
    SourceLocation,
    StandaloneAxonDecl,
    TestDecl,
    UsesEntry,
)
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.resolver.dependency import (
    DependencyResolver,
    resolve_dependencies,
)
from s0ma_dsl.resolver.namespaces import (
    NamespaceEntry,
    NamespaceService,
    build_namespaces,
)

# ---------------------------------------------------------------------------
# Helpers for constructing test S0maModules
# ---------------------------------------------------------------------------


def _loc(line: int = 1) -> SourceLocation:
    return SourceLocation(start_line=line, start_column=0, end_line=line, end_column=0)


def _make_module(
    name: str = "test_module",
    layer: Layer = Layer.APPLICATION,
    version: str = "1.0.0",
    intent: str = "Test module for namespace resolution",
    exports: tuple[str, ...] = (),
    requires: tuple[RequiresEntry, ...] = (),
    uses: tuple[UsesEntry, ...] = (),
) -> ModuleDecl:
    return ModuleDecl(
        name=name,
        layer=layer,
        version=version,
        intent=intent,
        exports=exports,
        requires=requires,
        uses=uses,
        location=_loc(1),
    )


def _make_nerve(
    name: str,
    line: int = 10,
    kind: Kind = Kind.FUNCTION,
    visibility: Visibility = Visibility.PUBLIC,
) -> NerveDecl:
    return NerveDecl(
        name=name,
        layer=Layer.APPLICATION,
        kind=kind,
        visibility=visibility,
        intent=f"Test nerve {name}",
        expects="None",
        guarantees="None",
        evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
        body=f"def {name}(): pass",
        location=_loc(line),
    )


def _make_cell(
    name: str,
    line: int = 20,
    kind: Kind = Kind.MODEL,
    visibility: Visibility = Visibility.PUBLIC,
) -> CellDecl:
    return CellDecl(
        name=name,
        layer=Layer.APPLICATION,
        kind=kind,
        visibility=visibility,
        intent=f"Test cell {name}",
        schema=f"{name} schema",
        body=f"class {name}: pass",
        location=_loc(line),
    )


def _simple_s0ma_module(
    module_name: str = "test_module",
    exports: tuple[str, ...] = (),
    requires: tuple[RequiresEntry, ...] = (),
    uses: tuple[UsesEntry, ...] = (),
    nerves: tuple[NerveDecl, ...] = (),
    cells: tuple[CellDecl, ...] = (),
    ganglia: tuple[GanglionDecl, ...] = (),
    tests: tuple[TestDecl, ...] = (),
    axons: tuple[StandaloneAxonDecl, ...] = (),
) -> S0maModule:
    return S0maModule(
        module=_make_module(
            name=module_name,
            exports=exports,
            requires=requires,
            uses=uses,
        ),
        nerves=nerves,
        cells=cells,
        ganglia=ganglia,
        tests=tests,
        axons=axons,
    )


# ===========================================================================
# Namespace population tests
# ===========================================================================


class TestCodeNamespace:
    """Code namespace must contain local + uses + requires names."""

    def test_local_declarations_in_code_namespace(self):
        sm = _simple_s0ma_module(
            nerves=(_make_nerve("process_signal"),),
            cells=(_make_cell("SignalConfig"),),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_code_namespace("process_signal")
        assert ns.is_in_code_namespace("SignalConfig")
        assert len(errors) == 0

    def test_uses_in_code_namespace(self):
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(qualified_name="routing.select_evaluator", location=_loc(3)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_code_namespace("select_evaluator")
        assert len(errors) == 0

    def test_requires_in_code_namespace(self):
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(module_path="uuid.UUID", is_from_import=True, location=_loc(4)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_code_namespace("UUID")
        assert len(errors) == 0

    def test_all_three_sources_in_code_namespace(self):
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(module_path="os.path", location=_loc(3)),
            ),
            uses=(
                UsesEntry(qualified_name="routing.select_evaluator", location=_loc(4)),
            ),
            nerves=(_make_nerve("process_signal"),),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_code_namespace("process_signal")   # local
        assert ns.is_in_code_namespace("select_evaluator")  # uses
        assert ns.is_in_code_namespace("os")                # requires
        assert len(errors) == 0

    def test_empty_module_has_empty_code_namespace(self):
        sm = _simple_s0ma_module()
        ns, errors = build_namespaces(sm)
        assert len(ns.code_namespace) == 0
        assert len(errors) == 0


class TestComponentRefNamespace:
    """Component-reference namespace must contain local + uses only (NO requires)."""

    def test_local_in_component_ref(self):
        sm = _simple_s0ma_module(
            nerves=(_make_nerve("process_signal"),),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_component_ref_namespace("process_signal")

    def test_uses_in_component_ref(self):
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(qualified_name="routing.select_evaluator", location=_loc(3)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_component_ref_namespace("select_evaluator")

    def test_requires_excluded_from_component_ref(self):
        """Requires names must NOT appear in the component-reference namespace."""
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(module_path="uuid.UUID", is_from_import=True, location=_loc(3)),
            ),
        )
        ns, errors = build_namespaces(sm)
        # UUID is in code namespace...
        assert ns.is_in_code_namespace("UUID")
        # ...but NOT in component-reference namespace
        assert not ns.is_in_component_ref_namespace("UUID")

    def test_is_requires_name_helper(self):
        """The is_requires_name helper correctly identifies requires origins."""
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(module_path="time", location=_loc(3)),
            ),
            nerves=(_make_nerve("my_func"),),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_requires_name("time")
        assert not ns.is_requires_name("my_func")


class TestPublicAPINamespace:
    """Public API namespace reflects the module's exports."""

    def test_exports_populate_public_api(self):
        sm = _simple_s0ma_module(
            exports=("process_signal", "SignalConfig"),
            nerves=(_make_nerve("process_signal"),),
            cells=(_make_cell("SignalConfig"),),
        )
        ns, errors = build_namespaces(sm)
        assert ns.lookup_public_api("process_signal") is not None
        assert ns.lookup_public_api("SignalConfig") is not None
        assert len(ns.public_api_namespace) == 2

    def test_non_exported_not_in_public_api(self):
        sm = _simple_s0ma_module(
            exports=("process_signal",),
            nerves=(_make_nerve("process_signal"), _make_nerve("helper_func", line=15)),
        )
        ns, errors = build_namespaces(sm)
        assert ns.lookup_public_api("process_signal") is not None
        assert ns.lookup_public_api("helper_func") is None

    def test_empty_exports(self):
        sm = _simple_s0ma_module(exports=())
        ns, errors = build_namespaces(sm)
        assert len(ns.public_api_namespace) == 0


class TestRegistryNamespace:
    """Registry namespace stub should contain local declarations."""

    def test_local_in_registry_with_canonical_ids(self):
        sm = _simple_s0ma_module(
            module_name="signal_processor",
            nerves=(_make_nerve("process_signal"),),
            cells=(_make_cell("SignalConfig"),),
        )
        ns, errors = build_namespaces(sm)
        assert ns.lookup_registry("signal_processor::process_signal") is not None
        assert ns.lookup_registry("signal_processor::SignalConfig") is not None

    def test_standalone_axons_not_in_registry_as_components(self):
        """Standalone axons declare relationships, not components."""
        sm = _simple_s0ma_module(
            nerves=(_make_nerve("sender"),),
            axons=(
                StandaloneAxonDecl(
                    source="sender",
                    target="routing.receiver",
                    relation=Relation.CALLS,
                    intent="sender calls receiver",
                    carries="signal data",
                    coupling=Coupling.LOOSE,
                    location=_loc(30),
                ),
            ),
        )
        ns, errors = build_namespaces(sm)
        # sender is in registry
        assert ns.lookup_registry("test_module::sender") is not None
        # axon is NOT a component — only the source/target are
        assert len(ns.registry_namespace) == 1


# ===========================================================================
# Alias-aware lookup tests (Task 6.2)
# ===========================================================================


class TestAliasResolution:
    """Alias-aware lookup for uses and requires entries."""

    def test_uses_alias(self):
        """Uses entry with alias should be available under the alias name."""
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(
                    qualified_name="routing.select_evaluator",
                    alias="router",
                    location=_loc(3),
                ),
            ),
        )
        ns, errors = build_namespaces(sm)
        # Available under alias
        assert ns.is_in_code_namespace("router")
        assert ns.is_in_component_ref_namespace("router")
        # NOT available under original component name
        assert not ns.is_in_code_namespace("select_evaluator")

    def test_uses_without_alias_uses_component_name(self):
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(qualified_name="routing.select_evaluator", location=_loc(3)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_code_namespace("select_evaluator")

    def test_requires_alias(self):
        """Requires entry with alias should be available under the alias name."""
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(
                    module_path="uuid.UUID",
                    alias="UniqueId",
                    is_from_import=True,
                    location=_loc(3),
                ),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_code_namespace("UniqueId")
        assert not ns.is_in_code_namespace("UUID")

    def test_requires_from_import_no_alias(self):
        """From-import without alias uses the final segment."""
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(module_path="uuid.UUID", is_from_import=True, location=_loc(3)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_code_namespace("UUID")

    def test_requires_plain_import_no_alias(self):
        """Plain import without alias uses the first segment."""
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(module_path="os.path", is_from_import=False, location=_loc(3)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_code_namespace("os")

    def test_requires_simple_module_no_alias(self):
        """Simple module import without alias uses the module name."""
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(module_path="time", is_from_import=False, location=_loc(3)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_code_namespace("time")

    def test_alias_preserves_canonical_name(self):
        """Aliases change local name but not canonical identity."""
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(
                    qualified_name="routing.select_evaluator",
                    alias="router",
                    location=_loc(3),
                ),
            ),
        )
        ns, errors = build_namespaces(sm)
        entry = ns.lookup_code("router")
        assert entry is not None
        assert entry.canonical_name == "routing::select_evaluator"
        assert entry.local_name == "router"

    def test_requires_alias_preserves_canonical(self):
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(
                    module_path="uuid.UUID",
                    alias="UID",
                    is_from_import=True,
                    location=_loc(3),
                ),
            ),
        )
        ns, errors = build_namespaces(sm)
        entry = ns.lookup_code("UID")
        assert entry is not None
        assert entry.canonical_name == "uuid.UUID"
        assert entry.local_name == "UID"


# ===========================================================================
# Collision detection tests (Task 6.3 — R-25)
# ===========================================================================


class TestCollisionDetection:
    """Namespace collision detection per spec §4.10.3 (R-25)."""

    def test_no_collision_with_distinct_names(self):
        sm = _simple_s0ma_module(
            requires=(RequiresEntry(module_path="time", location=_loc(3)),),
            uses=(UsesEntry(qualified_name="routing.select_evaluator", location=_loc(4)),),
            nerves=(_make_nerve("process_signal"),),
        )
        ns, errors = build_namespaces(sm)
        assert len(errors) == 0

    def test_local_vs_local_collision(self):
        """Two local declarations with the same name."""
        sm = _simple_s0ma_module(
            nerves=(
                _make_nerve("duplicate", line=10),
            ),
            cells=(
                _make_cell("duplicate", line=20),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert len(errors) == 1
        assert errors[0].code == "NAMESPACE_COLLISION"
        assert "duplicate" in errors[0].message

    def test_local_vs_uses_collision(self):
        """A uses entry resolves to the same name as a local declaration."""
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(qualified_name="routing.process_signal", location=_loc(3)),
            ),
            nerves=(_make_nerve("process_signal", line=10),),
        )
        ns, errors = build_namespaces(sm)
        assert len(errors) == 1
        assert errors[0].code == "NAMESPACE_COLLISION"
        assert "process_signal" in errors[0].message

    def test_uses_vs_uses_collision(self):
        """Two uses entries resolve to the same local name."""
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(qualified_name="module_a.helper", location=_loc(3)),
                UsesEntry(qualified_name="module_b.helper", location=_loc(4)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert len(errors) == 1
        assert errors[0].code == "NAMESPACE_COLLISION"
        assert "helper" in errors[0].message

    def test_uses_vs_uses_collision_with_alias_avoidance(self):
        """Aliasing one uses entry avoids collision."""
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(qualified_name="module_a.helper", location=_loc(3)),
                UsesEntry(qualified_name="module_b.helper", alias="b_helper", location=_loc(4)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert len(errors) == 0
        assert ns.is_in_code_namespace("helper")
        assert ns.is_in_code_namespace("b_helper")

    def test_local_vs_requires_collision(self):
        """A requires entry resolves to the same name as a local declaration."""
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(module_path="time", location=_loc(3)),
            ),
            nerves=(_make_nerve("time", line=10),),
        )
        ns, errors = build_namespaces(sm)
        assert len(errors) == 1
        assert errors[0].code == "NAMESPACE_COLLISION"
        assert "time" in errors[0].message

    def test_uses_vs_requires_collision(self):
        """A uses and requires entry resolve to the same local name."""
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(module_path="json", location=_loc(3)),
            ),
            uses=(
                UsesEntry(qualified_name="module_a.json", location=_loc(4)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert len(errors) == 1
        assert errors[0].code == "NAMESPACE_COLLISION"
        assert "json" in errors[0].message

    def test_collision_error_has_remediation(self):
        """Collision errors must include actionable remediation."""
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(qualified_name="module_a.helper", location=_loc(3)),
                UsesEntry(qualified_name="module_b.helper", location=_loc(4)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert len(errors) == 1
        assert errors[0].remediation
        assert "alias" in errors[0].remediation.lower()

    def test_collision_error_has_context(self):
        """Collision errors must include structured context."""
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(qualified_name="module_a.helper", location=_loc(3)),
                UsesEntry(qualified_name="module_b.helper", location=_loc(4)),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert len(errors) == 1
        ctx = errors[0].context
        assert "name" in ctx
        assert ctx["name"] == "helper"

    def test_collision_severity_is_always_error(self):
        """NAMESPACE_COLLISION is always error severity in the config matrix."""
        sm = _simple_s0ma_module(
            nerves=(
                _make_nerve("dup", line=10),
            ),
            cells=(
                _make_cell("dup", line=20),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert all(e.severity == "error" for e in errors)

    def test_multiple_collisions_reported(self):
        """Multiple independent collisions are all reported."""
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(module_path="time", location=_loc(3)),
            ),
            uses=(
                UsesEntry(qualified_name="module_a.helper", location=_loc(4)),
                UsesEntry(qualified_name="module_b.helper", location=_loc(5)),
            ),
            nerves=(
                _make_nerve("time", line=10),
            ),
        )
        ns, errors = build_namespaces(sm)
        codes = [e.code for e in errors]
        assert codes.count("NAMESPACE_COLLISION") >= 2


# ===========================================================================
# Lookup method tests
# ===========================================================================


class TestLookupMethods:
    """Verify alias-aware lookup returns correct NamespaceEntry objects."""

    def test_lookup_code_returns_entry(self):
        sm = _simple_s0ma_module(nerves=(_make_nerve("my_func"),))
        ns, _ = build_namespaces(sm)
        entry = ns.lookup_code("my_func")
        assert entry is not None
        assert entry.local_name == "my_func"
        assert entry.origin == "local"

    def test_lookup_code_returns_none_for_unknown(self):
        sm = _simple_s0ma_module()
        ns, _ = build_namespaces(sm)
        assert ns.lookup_code("nonexistent") is None

    def test_lookup_component_ref_returns_uses_entry(self):
        sm = _simple_s0ma_module(
            uses=(UsesEntry(qualified_name="r.helper", location=_loc(3)),),
        )
        ns, _ = build_namespaces(sm)
        entry = ns.lookup_component_ref("helper")
        assert entry is not None
        assert entry.origin == "uses"
        assert entry.canonical_name == "r::helper"

    def test_lookup_component_ref_excludes_requires(self):
        sm = _simple_s0ma_module(
            requires=(RequiresEntry(module_path="json", location=_loc(3)),),
        )
        ns, _ = build_namespaces(sm)
        assert ns.lookup_component_ref("json") is None
        assert ns.lookup_code("json") is not None

    def test_lookup_public_api(self):
        sm = _simple_s0ma_module(
            exports=("my_func",),
            nerves=(_make_nerve("my_func"),),
        )
        ns, _ = build_namespaces(sm)
        entry = ns.lookup_public_api("my_func")
        assert entry is not None
        assert entry.canonical_name == "test_module::my_func"

    def test_lookup_registry_canonical_id(self):
        sm = _simple_s0ma_module(
            module_name="my_mod",
            nerves=(_make_nerve("my_func"),),
        )
        ns, _ = build_namespaces(sm)
        entry = ns.lookup_registry("my_mod::my_func")
        assert entry is not None


# ===========================================================================
# Bulk accessor tests
# ===========================================================================


class TestBulkAccessors:
    """Verify local_names(), uses_names(), requires_names() helpers."""

    def test_local_names(self):
        sm = _simple_s0ma_module(
            nerves=(_make_nerve("func_a"), _make_nerve("func_b", line=15)),
            cells=(_make_cell("CellA"),),
        )
        ns, _ = build_namespaces(sm)
        locals_ = ns.local_names()
        assert set(locals_) == {"func_a", "func_b", "CellA"}

    def test_uses_names(self):
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(qualified_name="r.a", location=_loc(3)),
                UsesEntry(qualified_name="r.b", alias="b_alias", location=_loc(4)),
            ),
        )
        ns, _ = build_namespaces(sm)
        uses_ = ns.uses_names()
        assert set(uses_) == {"a", "b_alias"}

    def test_requires_names(self):
        sm = _simple_s0ma_module(
            requires=(
                RequiresEntry(module_path="json", location=_loc(3)),
                RequiresEntry(
                    module_path="uuid.UUID", is_from_import=True,
                    alias="UID", location=_loc(4),
                ),
            ),
        )
        ns, _ = build_namespaces(sm)
        reqs = ns.requires_names()
        assert set(reqs) == {"json", "UID"}


# ===========================================================================
# Integration test with parser
# ===========================================================================


class TestNamespaceWithParsedModule:
    """Integration: build namespaces from a parser-produced S0maModule."""

    def test_minimal_parsed_module(self):
        """Parse a minimal .s0ma file and build namespaces."""
        from s0ma_dsl.parser import parse_s0ma

        source = """\
module signal_processor
    layer: APPLICATION
    version: 1.0.0
    intent: "Process signals from various sources"
    requires: [time]
    uses: [routing.select_evaluator]
    exports: [process_signal]

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve process_signal :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Processes incoming signals"
    expects: "A valid signal dict"
    guarantees: "Returns processed result"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def process_signal(signal: dict) -> dict:
        return signal
"""
        sm = parse_s0ma(source, "test.s0ma")
        ns, errors = build_namespaces(sm, "test.s0ma")

        # No collisions
        assert len(errors) == 0

        # Code namespace: local + uses + requires
        assert ns.is_in_code_namespace("process_signal")   # local
        assert ns.is_in_code_namespace("select_evaluator")  # uses
        assert ns.is_in_code_namespace("time")              # requires

        # Component-ref namespace: local + uses only
        assert ns.is_in_component_ref_namespace("process_signal")
        assert ns.is_in_component_ref_namespace("select_evaluator")
        assert not ns.is_in_component_ref_namespace("time")

        # Public API
        assert ns.lookup_public_api("process_signal") is not None

        # requires detection
        assert ns.is_requires_name("time")
        assert not ns.is_requires_name("process_signal")

    def test_golden_fixture_namespaces(self, valid_fixtures_dir):
        """Build namespaces from the golden fixture file."""
        from s0ma_dsl.parser import parse_s0ma

        golden = valid_fixtures_dir / "signal_processor.s0ma"
        if not golden.exists():
            pytest.skip("Golden fixture not available")

        source = golden.read_text()
        sm = parse_s0ma(source, str(golden))
        ns, errors = build_namespaces(sm, str(golden))

        # Golden fixture should not have namespace collisions
        assert len(errors) == 0

        # Module name should be populated
        assert ns.module_name == "signal_processor"

        # Should have local declarations
        assert len(ns.local_names()) > 0

        # All exports should be in public API
        for export in sm.module.exports:
            assert ns.lookup_public_api(export) is not None


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge cases for namespace resolution."""

    def test_ganglion_contributes_local_name(self):
        """Ganglia are local declarations in the namespace."""
        sm = _simple_s0ma_module(
            ganglia=(
                GanglionDecl(
                    name="signal_monitor",
                    layer=Layer.APPLICATION,
                    visibility=Visibility.INTERNAL,
                    intent="Monitors signals",
                    observes=("process_signal",),
                    scope=EvaluatesAt.SUBSYSTEM,
                    priors="Signals should be timely",
                    on_anomaly="Log and alert",
                    body="def signal_monitor(): pass",
                    location=_loc(30),
                ),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_code_namespace("signal_monitor")
        assert ns.is_in_component_ref_namespace("signal_monitor")

    def test_test_decl_contributes_local_name(self):
        """Test declarations are local declarations in the namespace."""
        sm = _simple_s0ma_module(
            tests=(
                TestDecl(
                    name="test_process_signal",
                    layer=Layer.APPLICATION,
                    intent="Tests process_signal nerve",
                    tests=("process_signal",),
                    body="def test_process_signal(): pass",
                    location=_loc(40),
                ),
            ),
        )
        ns, errors = build_namespaces(sm)
        assert ns.is_in_code_namespace("test_process_signal")
        assert ns.is_in_component_ref_namespace("test_process_signal")

    def test_standalone_axon_not_local_name(self):
        """Standalone axons do NOT contribute a local name — they're relationships."""
        sm = _simple_s0ma_module(
            nerves=(_make_nerve("sender"),),
            axons=(
                StandaloneAxonDecl(
                    source="sender",
                    target="routing.receiver",
                    relation=Relation.CALLS,
                    intent="sender calls receiver",
                    carries="signal",
                    coupling=Coupling.LOOSE,
                    location=_loc(30),
                ),
            ),
        )
        ns, errors = build_namespaces(sm)
        # Only the nerve is a local name
        assert ns.local_names() == ["sender"]

    def test_uses_qualified_name_to_canonical_id(self):
        """Uses entries convert dotted qualified names to canonical IDs."""
        sm = _simple_s0ma_module(
            uses=(
                UsesEntry(qualified_name="errors.ValidationError", location=_loc(3)),
            ),
        )
        ns, _ = build_namespaces(sm)
        entry = ns.lookup_code("ValidationError")
        assert entry is not None
        assert entry.canonical_name == "errors::ValidationError"

    def test_source_entry_preserved(self):
        """The original AST entry is preserved on namespace entries."""
        req = RequiresEntry(module_path="time", location=_loc(3))
        use = UsesEntry(qualified_name="r.helper", location=_loc(4))
        sm = _simple_s0ma_module(requires=(req,), uses=(use,))
        ns, _ = build_namespaces(sm)

        req_entry = ns.lookup_code("time")
        assert req_entry is not None
        assert req_entry.source_entry is req

        use_entry = ns.lookup_code("helper")
        assert use_entry is not None
        assert use_entry.source_entry is use


# ===========================================================================
# Dogfooding
# ===========================================================================


class TestDogfooding:
    """Verify namespace module components are registered with s0ma."""

    def test_namespace_service_has_component(self):
        assert hasattr(NamespaceService, "__component__")

    def test_namespace_entry_has_component(self):
        assert hasattr(NamespaceEntry, "__component__")

    def test_build_namespaces_has_component(self):
        assert hasattr(build_namespaces, "__component__")


# ===========================================================================
# Cross-module dependency resolution tests (Milestone 8)
# ===========================================================================


# ---------------------------------------------------------------------------
# Helper: build a multi-module dict for the resolver
# ---------------------------------------------------------------------------


def _make_nerve_with_body(
    name: str,
    body: str,
    line: int = 10,
    kind: Kind = Kind.FUNCTION,
    visibility: Visibility = Visibility.PUBLIC,
    depends_on: tuple[InlineAxon, ...] = (),
) -> NerveDecl:
    return NerveDecl(
        name=name,
        layer=Layer.APPLICATION,
        kind=kind,
        visibility=visibility,
        intent=f"Test nerve {name}",
        expects="None",
        guarantees="None",
        evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
        body=body,
        depends_on=depends_on,
        location=_loc(line),
    )


# ===========================================================================
# Phase 1: Module graph + cycle detection
# ===========================================================================


class TestPhase1CycleDetection:
    """Phase 1: DFS three-colour cycle detection on module graph."""

    def test_no_cycles_linear_chain(self):
        """A → B → C has no cycles."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.thing", location=_loc(3)),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("thing",),
            uses=(UsesEntry(qualified_name="c.other", location=_loc(3)),),
            nerves=(_make_nerve("thing"),),
        )
        mod_c = _simple_s0ma_module(
            module_name="c",
            exports=("other",),
            nerves=(_make_nerve("other"),),
        )
        modules = {"a": mod_a, "b": mod_b, "c": mod_c}
        errors = resolve_dependencies(modules, check_imports=False)
        cycle_errors = [e for e in errors if e.code == "CIRCULAR_DEPENDENCY"]
        assert len(cycle_errors) == 0

    def test_direct_cycle_detected(self):
        """A → B → A is a cycle."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.thing", location=_loc(3)),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("thing",),
            uses=(UsesEntry(qualified_name="a.other", location=_loc(3)),),
            nerves=(_make_nerve("thing"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        cycle_errors = [e for e in errors if e.code == "CIRCULAR_DEPENDENCY"]
        assert len(cycle_errors) >= 1
        assert cycle_errors[0].severity == "error"
        # Cycle path should mention both modules
        assert "a" in cycle_errors[0].message
        assert "b" in cycle_errors[0].message

    def test_cycle_includes_path_in_context(self):
        """Cycle errors include the full cycle path in context."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.x", location=_loc(3)),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("x",),
            uses=(UsesEntry(qualified_name="c.y", location=_loc(3)),),
            nerves=(_make_nerve("x"),),
        )
        mod_c = _simple_s0ma_module(
            module_name="c",
            exports=("y",),
            uses=(UsesEntry(qualified_name="a.z", location=_loc(3)),),
            nerves=(_make_nerve("y"),),
        )
        modules = {"a": mod_a, "b": mod_b, "c": mod_c}
        errors = resolve_dependencies(modules, check_imports=False)
        cycle_errors = [e for e in errors if e.code == "CIRCULAR_DEPENDENCY"]
        assert len(cycle_errors) >= 1
        assert "cycle" in cycle_errors[0].context

    def test_cycle_is_fatal_stops_resolution(self):
        """When a cycle is detected, further phases are NOT run."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.thing", location=_loc(3)),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("thing",),
            uses=(UsesEntry(qualified_name="a.other", location=_loc(3)),),
            nerves=(_make_nerve("thing"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        # Should only have cycle errors — no DOES_NOT_EXIST etc.
        non_cycle = [e for e in errors if e.code != "CIRCULAR_DEPENDENCY"]
        assert len(non_cycle) == 0

    def test_self_reference_is_cycle(self):
        """A module using itself via uses is correctly detected as a cycle.
        Self-references should use inline depends_on, not uses."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            exports=("thing",),
            uses=(UsesEntry(qualified_name="a.thing", location=_loc(3)),),
            nerves=(_make_nerve("thing"),),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        cycle_errors = [e for e in errors if e.code == "CIRCULAR_DEPENDENCY"]
        assert len(cycle_errors) == 1
        assert cycle_errors[0].context["cycle"] == ["a", "a"]

    def test_no_cycle_with_external_uses(self):
        """Uses targeting a module not in the project don't create graph edges."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="external.thing", location=_loc(3)),),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        cycle_errors = [e for e in errors if e.code == "CIRCULAR_DEPENDENCY"]
        assert len(cycle_errors) == 0


# ===========================================================================
# Phase 2: Export validation
# ===========================================================================


class TestPhase2ExportValidation:
    """Phase 2: Every uses reference must target an exported component."""

    def test_valid_export_no_error(self):
        """Using an exported component produces no error."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.helper", location=_loc(3)),),
            nerves=(_make_nerve_with_body("caller", "helper()"),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        export_errors = [e for e in errors if e.code in ("NOT_EXPORTED", "DOES_NOT_EXIST")]
        assert len(export_errors) == 0

    def test_not_exported_error(self):
        """Using a non-exported component produces NOT_EXPORTED."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.secret", location=_loc(3)),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("helper",),  # "secret" not exported
            nerves=(_make_nerve("helper"), _make_nerve("secret", line=15)),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        not_exported = [e for e in errors if e.code == "NOT_EXPORTED"]
        assert len(not_exported) == 1
        assert "secret" in not_exported[0].message
        assert not_exported[0].severity == "error"

    def test_not_exported_includes_available_exports(self):
        """NOT_EXPORTED context includes the available exports list."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.missing", location=_loc(3)),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("helper", "util"),
            nerves=(_make_nerve("helper"), _make_nerve("util", line=15)),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        not_exported = [e for e in errors if e.code == "NOT_EXPORTED"]
        assert len(not_exported) == 1
        assert "available_exports" in not_exported[0].context
        assert set(not_exported[0].context["available_exports"]) == {"helper", "util"}

    def test_does_not_exist_error(self):
        """Using a component from a non-existent module produces DOES_NOT_EXIST."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="phantom.thing", location=_loc(3)),),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        dne = [e for e in errors if e.code == "DOES_NOT_EXIST"]
        assert len(dne) == 1
        assert "phantom" in dne[0].message
        assert dne[0].severity == "error"

    def test_does_not_exist_has_remediation(self):
        """DOES_NOT_EXIST error includes actionable remediation."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="phantom.thing", location=_loc(3)),),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        dne = [e for e in errors if e.code == "DOES_NOT_EXIST"]
        assert len(dne) == 1
        assert dne[0].remediation
        assert "phantom" in dne[0].remediation

    def test_multiple_modules_multiple_errors(self):
        """Errors from multiple modules are all collected."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="phantom.x", location=_loc(3)),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            uses=(UsesEntry(qualified_name="phantom.y", location=_loc(3)),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        dne = [e for e in errors if e.code == "DOES_NOT_EXIST"]
        assert len(dne) == 2


# ===========================================================================
# Phase 3: External validation
# ===========================================================================


class TestPhase3ExternalValidation:
    """Phase 3: requires entries must be importable packages."""

    def test_stdlib_package_no_error(self):
        """Standard library packages like 'os' should not produce errors."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            requires=(RequiresEntry(module_path="os", location=_loc(3)),),
            nerves=(_make_nerve_with_body("func", "os.getcwd()"),),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=True)
        pkg_errors = [e for e in errors if e.code == "MISSING_PACKAGE"]
        assert len(pkg_errors) == 0

    def test_nonexistent_package_error(self):
        """A non-importable package produces MISSING_PACKAGE."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            requires=(
                RequiresEntry(
                    module_path="zzzz_definitely_not_a_real_package_xyz",
                    location=_loc(3),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=True)
        pkg_errors = [e for e in errors if e.code == "MISSING_PACKAGE"]
        assert len(pkg_errors) == 1

    def test_missing_package_severity_varies_by_mode(self):
        """MISSING_PACKAGE is warning in DEV, error in STRICT."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            requires=(
                RequiresEntry(
                    module_path="zzzz_definitely_not_a_real_package_xyz",
                    location=_loc(3),
                ),
            ),
        )
        modules = {"a": mod_a}

        dev_errors = resolve_dependencies(
            modules, mode=StrictnessMode.DEV, check_imports=True
        )
        dev_pkg = [e for e in dev_errors if e.code == "MISSING_PACKAGE"]
        assert len(dev_pkg) == 1
        assert dev_pkg[0].severity == "warning"

        strict_errors = resolve_dependencies(
            modules, mode=StrictnessMode.STRICT, check_imports=True
        )
        strict_pkg = [e for e in strict_errors if e.code == "MISSING_PACKAGE"]
        assert len(strict_pkg) == 1
        assert strict_pkg[0].severity == "error"

    def test_check_imports_false_skips_phase3(self):
        """When check_imports=False, Phase 3 is skipped entirely."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            requires=(
                RequiresEntry(
                    module_path="zzzz_not_real",
                    location=_loc(3),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        pkg_errors = [e for e in errors if e.code == "MISSING_PACKAGE"]
        assert len(pkg_errors) == 0

    def test_from_import_checks_parent_package(self):
        """``from uuid import UUID`` checks 'uuid', not 'uuid.UUID'."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            requires=(
                RequiresEntry(
                    module_path="uuid.UUID",
                    is_from_import=True,
                    location=_loc(3),
                ),
            ),
            nerves=(_make_nerve_with_body("func", "x = UUID()"),),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=True)
        pkg_errors = [e for e in errors if e.code == "MISSING_PACKAGE"]
        assert len(pkg_errors) == 0


# ===========================================================================
# Phase 4: Usage verification (vestigial imports + evidence rules)
# ===========================================================================


class TestPhase4UsageVerification:
    """Phase 4: Vestigial import detection and relation-specific evidence."""

    def test_used_uses_entry_no_vestigial(self):
        """A uses entry referenced in body code is not vestigial."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.helper", location=_loc(3)),),
            nerves=(_make_nerve_with_body("caller", "result = helper()"),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"]
        assert len(vestigial) == 0

    def test_unused_uses_entry_is_vestigial(self):
        """A uses entry with no reference in bodies or metadata is vestigial."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.helper", location=_loc(3)),),
            nerves=(_make_nerve_with_body("caller", "x = 1"),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "helper" in e.message]
        assert len(vestigial) == 1

    def test_uses_referenced_in_metadata_not_vestigial(self):
        """A uses entry referenced in depends_on metadata is not vestigial."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.helper", location=_loc(3)),),
            nerves=(
                _make_nerve_with_body(
                    "caller",
                    "x = helper()",
                    depends_on=(
                        InlineAxon(
                            target="helper",
                            relation=Relation.CALLS,
                            carries="data",
                            coupling=Coupling.LOOSE,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "uses" in e.message and "helper" in e.message]
        assert len(vestigial) == 0

    def test_unused_requires_entry_is_vestigial(self):
        """A requires entry with no reference in bodies is vestigial."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            requires=(RequiresEntry(module_path="json", location=_loc(3)),),
            nerves=(_make_nerve_with_body("func", "x = 1"),),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "json" in e.message]
        assert len(vestigial) == 1

    def test_used_requires_entry_no_vestigial(self):
        """A requires entry referenced in body code is not vestigial."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            requires=(RequiresEntry(module_path="json", location=_loc(3)),),
            nerves=(_make_nerve_with_body("func", "data = json.loads(s)"),),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "json" in e.message]
        assert len(vestigial) == 0

    def test_vestigial_severity_varies_by_mode(self):
        """VESTIGIAL_IMPORT is warning in DEV, error in STRICT."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            requires=(RequiresEntry(module_path="json", location=_loc(3)),),
            nerves=(_make_nerve_with_body("func", "x = 1"),),
        )
        modules = {"a": mod_a}

        dev_errors = resolve_dependencies(
            modules, mode=StrictnessMode.DEV, check_imports=False
        )
        dev_vest = [e for e in dev_errors if e.code == "VESTIGIAL_IMPORT"]
        assert all(e.severity == "warning" for e in dev_vest)

        strict_errors = resolve_dependencies(
            modules, mode=StrictnessMode.STRICT, check_imports=False
        )
        strict_vest = [e for e in strict_errors if e.code == "VESTIGIAL_IMPORT"]
        assert all(e.severity == "error" for e in strict_vest)


# ===========================================================================
# Evidence rules per relation type (spec §4.6.3)
# ===========================================================================


class TestEvidenceRules:
    """Relation-specific evidence checking for inline depends_on."""

    def test_calls_relation_needs_call_evidence(self):
        """CALLS relation requires target to appear as a call target."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            nerves=(
                _make_nerve_with_body(
                    "caller",
                    "result = helper()",
                    depends_on=(
                        InlineAxon(
                            target="helper",
                            relation=Relation.CALLS,
                            carries="data",
                            coupling=Coupling.LOOSE,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        evidence_errors = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                          and "helper" in e.message and "CALLS" in e.message]
        assert len(evidence_errors) == 0

    def test_calls_relation_fails_without_call(self):
        """CALLS relation with no call evidence produces VESTIGIAL_IMPORT."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            nerves=(
                _make_nerve_with_body(
                    "caller",
                    "x = helper",  # reference but no call
                    depends_on=(
                        InlineAxon(
                            target="helper",
                            relation=Relation.CALLS,
                            carries="data",
                            coupling=Coupling.LOOSE,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        evidence_errors = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                          and "helper" in e.message and "CALLS" in e.message]
        assert len(evidence_errors) == 1

    def test_reads_relation_accepts_name_reference(self):
        """READS relation requires any name reference (not necessarily a call)."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            nerves=(
                _make_nerve_with_body(
                    "reader",
                    "x = Config.value",
                    depends_on=(
                        InlineAxon(
                            target="Config",
                            relation=Relation.READS,
                            carries="config data",
                            coupling=Coupling.LOOSE,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        evidence_errors = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                          and "Config" in e.message and "READS" in e.message]
        assert len(evidence_errors) == 0

    def test_constructs_relation_needs_call_evidence(self):
        """CONSTRUCTS relation requires target to appear as a constructor call."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            nerves=(
                _make_nerve_with_body(
                    "builder",
                    "obj = Widget()",
                    depends_on=(
                        InlineAxon(
                            target="Widget",
                            relation=Relation.CONSTRUCTS,
                            carries="widget instance",
                            coupling=Coupling.TIGHT,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        evidence_errors = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                          and "Widget" in e.message]
        assert len(evidence_errors) == 0

    def test_configures_relation_accepts_name_reference(self):
        """CONFIGURES relation requires any name reference."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            nerves=(
                _make_nerve_with_body(
                    "configurator",
                    "Settings.debug = True",
                    depends_on=(
                        InlineAxon(
                            target="Settings",
                            relation=Relation.CONFIGURES,
                            carries="config update",
                            coupling=Coupling.TIGHT,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        evidence_errors = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                          and "Settings" in e.message]
        assert len(evidence_errors) == 0

    def test_no_evidence_for_missing_target(self):
        """A depends_on target not found in the body produces evidence error."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            nerves=(
                _make_nerve_with_body(
                    "caller",
                    "x = 1",
                    depends_on=(
                        InlineAxon(
                            target="NotUsed",
                            relation=Relation.CALLS,
                            carries="data",
                            coupling=Coupling.LOOSE,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        evidence_errors = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                          and "NotUsed" in e.message]
        assert len(evidence_errors) == 1


# ===========================================================================
# Standalone axon cross-module validation
# ===========================================================================


class TestStandaloneAxonCrossModule:
    """Standalone axon validation: cross-module targets, duplicates, evidence."""

    def test_standalone_axon_local_target_error(self):
        """Standalone axon targeting a local component produces error."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            nerves=(
                _make_nerve_with_body("sender", "receiver()"),
                _make_nerve_with_body("receiver", "pass", line=20),
            ),
            axons=(
                StandaloneAxonDecl(
                    source="sender",
                    target="receiver",
                    relation=Relation.CALLS,
                    intent="sender calls receiver",
                    carries="data",
                    coupling=Coupling.LOOSE,
                    location=_loc(30),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        local_errors = [e for e in errors if e.code == "DOES_NOT_EXIST"
                       and "local" in e.message.lower()]
        assert len(local_errors) == 1
        assert "inline depends_on" in local_errors[0].remediation

    def test_standalone_axon_uses_target_ok(self):
        """Standalone axon targeting a uses entry is valid."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.receiver", location=_loc(3)),),
            nerves=(_make_nerve_with_body("sender", "receiver()"),),
            axons=(
                StandaloneAxonDecl(
                    source="sender",
                    target="receiver",
                    relation=Relation.CALLS,
                    intent="sender calls receiver",
                    carries="data",
                    coupling=Coupling.LOOSE,
                    location=_loc(30),
                ),
            ),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("receiver",),
            nerves=(_make_nerve("receiver"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        local_errors = [e for e in errors if e.code == "DOES_NOT_EXIST"
                       and "local" in e.message.lower()]
        assert len(local_errors) == 0

    def test_duplicate_standalone_with_inline_axon(self):
        """Standalone axon duplicating inline depends_on produces DUPLICATE_AXON."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.helper", location=_loc(3)),),
            nerves=(
                _make_nerve_with_body(
                    "caller",
                    "helper()",
                    depends_on=(
                        InlineAxon(
                            target="helper",
                            relation=Relation.CALLS,
                            carries="data",
                            coupling=Coupling.LOOSE,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
            axons=(
                StandaloneAxonDecl(
                    source="caller",
                    target="helper",
                    relation=Relation.CALLS,
                    intent="duplicate",
                    carries="data",
                    coupling=Coupling.LOOSE,
                    location=_loc(30),
                ),
            ),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        dup_errors = [e for e in errors if e.code == "DUPLICATE_AXON"]
        assert len(dup_errors) == 1

    def test_duplicate_among_standalone_axons(self):
        """Two identical standalone axons produce DUPLICATE_AXON."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.helper", location=_loc(3)),),
            nerves=(_make_nerve_with_body("caller", "helper()"),),
            axons=(
                StandaloneAxonDecl(
                    source="caller",
                    target="helper",
                    relation=Relation.CALLS,
                    intent="first",
                    carries="data",
                    coupling=Coupling.LOOSE,
                    location=_loc(30),
                ),
                StandaloneAxonDecl(
                    source="caller",
                    target="helper",
                    relation=Relation.CALLS,
                    intent="duplicate",
                    carries="data",
                    coupling=Coupling.LOOSE,
                    location=_loc(35),
                ),
            ),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        dup_errors = [e for e in errors if e.code == "DUPLICATE_AXON"]
        assert len(dup_errors) == 1

    def test_standalone_axon_evidence_check(self):
        """Standalone axon with no body evidence produces VESTIGIAL_IMPORT."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.helper", location=_loc(3)),),
            nerves=(_make_nerve_with_body("caller", "x = 1"),),
            axons=(
                StandaloneAxonDecl(
                    source="caller",
                    target="helper",
                    relation=Relation.CALLS,
                    intent="caller calls helper",
                    carries="data",
                    coupling=Coupling.LOOSE,
                    location=_loc(30),
                ),
            ),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        evidence_errors = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                          and "standalone" in e.message.lower()
                          and "helper" in e.message]
        assert len(evidence_errors) == 1


# ===========================================================================
# Valid cross-module resolution (integration)
# ===========================================================================


class TestValidCrossModuleResolution:
    """Integration: valid multi-module project produces no errors."""

    def test_two_module_chain_no_errors(self):
        """models → processing: valid chain with correct exports/uses."""
        mod_models = _simple_s0ma_module(
            module_name="models",
            exports=("UserModel", "UserRole"),
            cells=(
                _make_cell("UserModel", line=10, kind=Kind.MODEL),
                _make_cell("UserRole", line=20, kind=Kind.ENUM),
            ),
        )
        mod_processing = _simple_s0ma_module(
            module_name="processing",
            exports=("process_user",),
            requires=(RequiresEntry(module_path="logging", location=_loc(5)),),
            uses=(
                UsesEntry(qualified_name="models.UserModel", location=_loc(6)),
                UsesEntry(qualified_name="models.UserRole", location=_loc(7)),
            ),
            nerves=(
                _make_nerve_with_body(
                    "process_user",
                    (
                        'def process_user(user: UserModel) -> dict:\n'
                        '    logging.info("Processing %s", user.name)\n'
                        '    if user.role == UserRole.ADMIN:\n'
                        '        return {"access": "full"}\n'
                        '    return {"access": "limited"}'
                    ),
                    depends_on=(
                        InlineAxon(
                            target="UserModel",
                            relation=Relation.READS,
                            carries="user data",
                            coupling=Coupling.LOOSE,
                            location=_loc(17),
                        ),
                    ),
                ),
            ),
        )
        modules = {"models": mod_models, "processing": mod_processing}
        errors = resolve_dependencies(modules, check_imports=False)
        # Filter out vestigial errors for UserRole since it's used in body
        # but declared via uses — all identifiers should resolve
        real_errors = [e for e in errors if e.severity == "error"]
        assert len(real_errors) == 0

    def test_three_module_chain_no_errors(self):
        """models → processing → routing: valid 3-module chain."""
        mod_models = _simple_s0ma_module(
            module_name="models",
            exports=("UserModel", "UserRole"),
            cells=(
                _make_cell("UserModel", line=10, kind=Kind.MODEL),
                _make_cell("UserRole", line=20, kind=Kind.ENUM),
            ),
        )
        mod_processing = _simple_s0ma_module(
            module_name="processing",
            exports=("process_user",),
            requires=(RequiresEntry(module_path="logging", location=_loc(5)),),
            uses=(
                UsesEntry(qualified_name="models.UserModel", location=_loc(6)),
                UsesEntry(qualified_name="models.UserRole", location=_loc(7)),
            ),
            nerves=(
                _make_nerve_with_body(
                    "process_user",
                    (
                        'def process_user(user: UserModel) -> dict:\n'
                        '    logging.info("Processing")\n'
                        '    if user.role == UserRole.ADMIN:\n'
                        '        return {"access": "full"}\n'
                        '    return {"access": "limited"}'
                    ),
                ),
            ),
        )
        mod_routing = _simple_s0ma_module(
            module_name="routing",
            exports=("route_request",),
            requires=(RequiresEntry(module_path="logging", location=_loc(5)),),
            uses=(
                UsesEntry(qualified_name="processing.process_user", location=_loc(6)),
                UsesEntry(qualified_name="models.UserModel", location=_loc(7)),
            ),
            nerves=(
                _make_nerve_with_body(
                    "route_request",
                    (
                        'def route_request(request: dict) -> dict:\n'
                        '    user = UserModel(name=request["name"], role=request["role"])\n'
                        '    logging.info("Routing")\n'
                        '    return process_user(user)'
                    ),
                    depends_on=(
                        InlineAxon(
                            target="process_user",
                            relation=Relation.CALLS,
                            carries="user operation",
                            coupling=Coupling.LOOSE,
                            location=_loc(18),
                        ),
                        InlineAxon(
                            target="UserModel",
                            relation=Relation.READS,
                            carries="user data",
                            coupling=Coupling.LOOSE,
                            location=_loc(19),
                        ),
                    ),
                ),
            ),
        )
        modules = {
            "models": mod_models,
            "processing": mod_processing,
            "routing": mod_routing,
        }
        errors = resolve_dependencies(modules, check_imports=False)
        real_errors = [e for e in errors if e.severity == "error"]
        assert len(real_errors) == 0


# ===========================================================================
# Strictness mode severity
# ===========================================================================


class TestStrictnessModeSeverity:
    """CIRCULAR_DEPENDENCY is always error; VESTIGIAL/MISSING vary by mode."""

    def test_circular_dependency_always_error(self):
        """CIRCULAR_DEPENDENCY is error even in MIGRATION mode."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.x", location=_loc(3)),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("x",),
            uses=(UsesEntry(qualified_name="a.y", location=_loc(3)),),
            nerves=(_make_nerve("x"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        for mode in StrictnessMode:
            errors = resolve_dependencies(
                modules, mode=mode, check_imports=False
            )
            cycle_errors = [e for e in errors if e.code == "CIRCULAR_DEPENDENCY"]
            assert all(e.severity == "error" for e in cycle_errors), (
                f"CIRCULAR_DEPENDENCY should be error in {mode.value}"
            )

    def test_not_exported_always_error(self):
        """NOT_EXPORTED is always error regardless of mode."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.secret", location=_loc(3)),),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("other",),
            nerves=(_make_nerve("other"), _make_nerve("secret", line=15)),
        )
        modules = {"a": mod_a, "b": mod_b}
        for mode in StrictnessMode:
            errors = resolve_dependencies(
                modules, mode=mode, check_imports=False
            )
            ne = [e for e in errors if e.code == "NOT_EXPORTED"]
            assert all(e.severity == "error" for e in ne), (
                f"NOT_EXPORTED should be error in {mode.value}"
            )


# ===========================================================================
# DependencyResolver class and convenience function
# ===========================================================================


class TestResolverAPI:
    """DependencyResolver class API and resolve_dependencies convenience."""

    def test_resolver_class_has_component(self):
        """DependencyResolver is decorated with @component."""
        assert hasattr(DependencyResolver, "__component__")

    def test_resolve_dependencies_has_component(self):
        """resolve_dependencies is decorated with @component."""
        assert hasattr(resolve_dependencies, "__component__")

    def test_resolver_default_mode_is_dev(self):
        """Default mode is DEV."""
        resolver = DependencyResolver()
        assert resolver.mode == StrictnessMode.DEV

    def test_convenience_function_matches_class(self):
        """resolve_dependencies produces same results as DependencyResolver.resolve."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="phantom.x", location=_loc(3)),),
        )
        modules = {"a": mod_a}

        resolver = DependencyResolver(mode=StrictnessMode.DEV)
        class_errors = resolver.resolve(modules, check_imports=False)
        func_errors = resolve_dependencies(
            modules, mode=StrictnessMode.DEV, check_imports=False
        )

        assert len(class_errors) == len(func_errors)
        assert [e.code for e in class_errors] == [e.code for e in func_errors]

    def test_custom_filenames(self):
        """Custom filenames dict is used in error file fields."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="phantom.x", location=_loc(3)),),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(
            modules,
            filenames={"a": "src/modules/a.s0ma"},
            check_imports=False,
        )
        assert any(e.file == "src/modules/a.s0ma" for e in errors)

    def test_default_filenames_generated(self):
        """Without filenames dict, defaults to <module_name>.s0ma."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="phantom.x", location=_loc(3)),),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        assert any(e.file == "a.s0ma" for e in errors)


# ===========================================================================
# Integration with parser: multi-module fixture files
# ===========================================================================


class TestMultiModuleFixtureIntegration:
    """Integration: parse real fixture files and run dependency resolution."""

    def test_multi_module_fixtures(self, valid_fixtures_dir):
        """Parse multi-module fixtures and resolve dependencies."""
        from s0ma_dsl.parser import parse_s0ma

        multi_dir = valid_fixtures_dir / "multi_module"
        if not multi_dir.exists():
            pytest.skip("Multi-module fixtures not available")

        modules: dict[str, S0maModule] = {}
        filenames: dict[str, str] = {}
        for s0ma_file in sorted(multi_dir.glob("*.s0ma")):
            source = s0ma_file.read_text()
            sm = parse_s0ma(source, str(s0ma_file))
            modules[sm.module.name] = sm
            filenames[sm.module.name] = str(s0ma_file)

        assert len(modules) >= 2, "Expected at least 2 fixture modules"

        errors = resolve_dependencies(
            modules, filenames=filenames, check_imports=False
        )
        real_errors = [e for e in errors if e.severity == "error"]
        assert len(real_errors) == 0, (
            f"Multi-module fixtures should resolve cleanly, got: "
            f"{[e.format_text() for e in real_errors]}"
        )


# ===========================================================================
# Milestone 4: VESTIGIAL_IMPORT false positive suppression
# ===========================================================================


class TestVestigialImportParameterInjection:
    """Task 4.1: Suppress VESTIGIAL_IMPORT when depends_on target is
    received as a snake_case parameter (dependency injection pattern)."""

    def test_calls_with_snake_case_parameter_no_vestigial(self):
        """depends_on: LLMAdapter {CALLS} with llm_adapter parameter → no error."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            nerves=(
                _make_nerve_with_body(
                    "my_service",
                    "def my_service(llm_adapter):\n    return llm_adapter.generate()",
                    depends_on=(
                        InlineAxon(
                            target="LLMAdapter",
                            relation=Relation.CALLS,
                            carries="request data",
                            coupling=Coupling.LOOSE,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "LLMAdapter" in e.message]
        assert len(vestigial) == 0

    def test_calls_without_parameter_or_call_still_vestigial(self):
        """depends_on: LLMAdapter {CALLS} with no evidence → still VESTIGIAL."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            nerves=(
                _make_nerve_with_body(
                    "my_service",
                    "def my_service():\n    x = 1",
                    depends_on=(
                        InlineAxon(
                            target="LLMAdapter",
                            relation=Relation.CALLS,
                            carries="request data",
                            coupling=Coupling.LOOSE,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "LLMAdapter" in e.message]
        assert len(vestigial) == 1

    def test_constructs_relation_exempt_from_evidence(self):
        """depends_on: MessageGateway {CONSTRUCTS} → always exempt."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            nerves=(
                _make_nerve_with_body(
                    "builder",
                    "def builder():\n    x = 1",  # No reference at all
                    depends_on=(
                        InlineAxon(
                            target="MessageGateway",
                            relation=Relation.CONSTRUCTS,
                            carries="gateway instance",
                            coupling=Coupling.TIGHT,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "MessageGateway" in e.message]
        assert len(vestigial) == 0

    def test_acronym_pascal_to_snake_conversion(self):
        """LLMAdapter → llm_adapter (acronym handling)."""
        from s0ma_dsl.resolver.dependency import _pascal_to_snake

        assert _pascal_to_snake("LLMAdapter") == "llm_adapter"
        assert _pascal_to_snake("MessageGateway") == "message_gateway"
        assert _pascal_to_snake("HTTPClient") == "http_client"
        assert _pascal_to_snake("UserModel") == "user_model"
        assert _pascal_to_snake("simple") == "simple"


class TestVestigialImportTestBodies:
    """Task 4.2: Verify nested scope identifiers in test bodies are found."""

    def test_pytest_in_decorator_not_vestigial(self):
        """requires: [pytest] with @pytest.mark.asyncio usage → no VESTIGIAL."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            requires=(RequiresEntry(module_path="pytest", location=_loc(3)),),
            tests=(
                TestDecl(
                    name="test_something",
                    layer=Layer.APPLICATION,
                    intent="Tests something",
                    tests=("process_signal",),
                    body=(
                        "@pytest.mark.asyncio\n"
                        "async def test_something():\n"
                        "    result = await process()\n"
                        "    assert result is not None"
                    ),
                    location=_loc(40),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "pytest" in e.message]
        assert len(vestigial) == 0

    def test_pathlib_in_nested_function_not_vestigial(self):
        """requires: [pathlib.Path] used inside nested def → no VESTIGIAL."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            requires=(
                RequiresEntry(
                    module_path="pathlib.Path",
                    is_from_import=True,
                    location=_loc(3),
                ),
            ),
            tests=(
                TestDecl(
                    name="test_paths",
                    layer=Layer.APPLICATION,
                    intent="Tests path handling",
                    tests=("path_handler",),
                    body=(
                        "def test_paths():\n"
                        "    result = Path('/test')\n"
                        "    assert result.exists()"
                    ),
                    location=_loc(40),
                ),
            ),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "pathlib" in e.message]
        assert len(vestigial) == 0

    def test_attribute_chain_root_extracted(self):
        """Root name from attribute chains (e.g. pytest from pytest.mark) is extracted."""
        from s0ma_dsl.resolver.dependency import _extract_identifiers

        ids = _extract_identifiers("pytest.mark.asyncio")
        assert "pytest" in ids
        assert "mark" in ids
        assert "asyncio" in ids


class TestVestigialImportStandaloneAxonParameterInjection:
    """Task 4.3: Standalone axon targets matched via snake_case parameters."""

    def test_standalone_axon_constructs_exempt(self):
        """Standalone axon with CONSTRUCTS relation is exempt from body evidence."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.Gateway", location=_loc(3)),),
            nerves=(_make_nerve_with_body("builder", "def builder():\n    x = 1"),),
            axons=(
                StandaloneAxonDecl(
                    source="builder",
                    target="Gateway",
                    relation=Relation.CONSTRUCTS,
                    intent="builder constructs Gateway",
                    carries="gateway instance",
                    coupling=Coupling.TIGHT,
                    location=_loc(30),
                ),
            ),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("Gateway",),
            nerves=(_make_nerve("Gateway"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "Gateway" in e.message
                     and "standalone" in e.message.lower()]
        assert len(vestigial) == 0

    def test_standalone_axon_calls_with_snake_case_param(self):
        """Standalone axon CALLS with snake_case parameter → no VESTIGIAL."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            uses=(UsesEntry(qualified_name="b.DataService", location=_loc(3)),),
            nerves=(
                _make_nerve_with_body(
                    "handler",
                    "def handler(data_service):\n    return data_service.get()",
                ),
            ),
            axons=(
                StandaloneAxonDecl(
                    source="handler",
                    target="DataService",
                    relation=Relation.CALLS,
                    intent="handler calls DataService",
                    carries="data request",
                    coupling=Coupling.LOOSE,
                    location=_loc(30),
                ),
            ),
        )
        mod_b = _simple_s0ma_module(
            module_name="b",
            exports=("DataService",),
            nerves=(_make_nerve("DataService"),),
        )
        modules = {"a": mod_a, "b": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "DataService" in e.message
                     and "standalone" in e.message.lower()]
        assert len(vestigial) == 0

    def test_genuinely_unused_still_detected(self):
        """Genuinely unused import still produces VESTIGIAL_IMPORT."""
        mod_a = _simple_s0ma_module(
            module_name="a",
            requires=(RequiresEntry(module_path="json", location=_loc(3)),),
            nerves=(_make_nerve_with_body("func", "x = 1"),),
        )
        modules = {"a": mod_a}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "json" in e.message]
        assert len(vestigial) == 1


# ===========================================================================
# Soft requires tests
# ===========================================================================


class TestSoftRequiresResolver:
    """Tests for soft_requires behaviour in the dependency resolver."""

    def test_soft_requires_skips_phase3_external_validation(self):
        """soft_requires entries must NOT produce MISSING_PACKAGE errors."""
        mod = S0maModule(
            module=ModuleDecl(
                name="soft_mod",
                layer=Layer.APPLICATION,
                version="1.0.0",
                intent="Module with soft requires",
                exports=(),
                soft_requires=(
                    RequiresEntry(
                        module_path="nonexistent_fake_package_xyz",
                        location=_loc(3),
                    ),
                ),
                location=_loc(1),
            ),
            nerves=(
                _make_nerve_with_body("func", "x = nonexistent_fake_package_xyz.do()"),
            ),
        )
        modules = {"soft_mod": mod}
        errors = resolve_dependencies(modules, check_imports=True)
        missing = [e for e in errors if e.code == "MISSING_PACKAGE"]
        assert len(missing) == 0

    def test_soft_requires_vestigial_fires_when_unused(self):
        """Unused soft_requires should produce VESTIGIAL_IMPORT."""
        mod = S0maModule(
            module=ModuleDecl(
                name="soft_mod",
                layer=Layer.APPLICATION,
                version="1.0.0",
                intent="Module with unused soft requires",
                exports=(),
                soft_requires=(
                    RequiresEntry(module_path="anthropic", location=_loc(3)),
                ),
                location=_loc(1),
            ),
            nerves=(
                _make_nerve_with_body("func", "x = 1"),
            ),
        )
        modules = {"soft_mod": mod}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "anthropic" in e.message]
        assert len(vestigial) == 1

    def test_soft_requires_used_no_vestigial(self):
        """Used soft_requires should NOT produce VESTIGIAL_IMPORT."""
        mod = S0maModule(
            module=ModuleDecl(
                name="soft_mod",
                layer=Layer.APPLICATION,
                version="1.0.0",
                intent="Module with used soft requires",
                exports=(),
                soft_requires=(
                    RequiresEntry(module_path="anthropic", location=_loc(3)),
                ),
                location=_loc(1),
            ),
            nerves=(
                _make_nerve_with_body("func", "client = anthropic.Client()"),
            ),
        )
        modules = {"soft_mod": mod}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "anthropic" in e.message]
        assert len(vestigial) == 0


# ===========================================================================
# MS 9 Task 9.2: PRODUCES and CONSUMES relation evidence
# ===========================================================================


class TestProducesConsumesEvidence:
    """Evidence matching for the PRODUCES and CONSUMES relation types."""

    def test_produces_with_constructor_evidence(self):
        """PRODUCES relation: target appears as constructor call → no vestigial."""
        cell = CellDecl(
            name="DomainEvent",
            layer=Layer.APPLICATION,
            kind=Kind.MODEL,
            visibility=Visibility.PUBLIC,
            intent="A domain event",
            schema="DomainEvent schema",
            body="class DomainEvent: pass",
            location=_loc(5),
        )
        mod = _simple_s0ma_module(
            module_name="a",
            exports=("emit_event",),
            nerves=(
                _make_nerve_with_body(
                    "emit_event",
                    "def emit_event():\n    event = DomainEvent()\n    return event",
                    depends_on=(
                        InlineAxon(
                            target="DomainEvent",
                            relation=Relation.PRODUCES,
                            carries="domain event instance",
                            coupling=Coupling.LOOSE,
                            location=_loc(15),
                        ),
                    ),
                ),
            ),
            cells=(cell,),
        )
        modules = {"a": mod}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "DomainEvent" in e.message]
        assert len(vestigial) == 0

    def test_produces_without_evidence(self):
        """PRODUCES with no body evidence → VESTIGIAL_IMPORT."""
        cell = CellDecl(
            name="DomainEvent",
            layer=Layer.APPLICATION,
            kind=Kind.MODEL,
            visibility=Visibility.PUBLIC,
            intent="A domain event",
            schema="DomainEvent schema",
            body="class DomainEvent: pass",
            location=_loc(5),
        )
        mod = _simple_s0ma_module(
            module_name="a",
            exports=("emit_event",),
            nerves=(
                _make_nerve_with_body(
                    "emit_event",
                    "def emit_event():\n    return 42",
                    depends_on=(
                        InlineAxon(
                            target="DomainEvent",
                            relation=Relation.PRODUCES,
                            carries="domain event instance",
                            coupling=Coupling.LOOSE,
                            location=_loc(15),
                        ),
                    ),
                ),
            ),
            cells=(cell,),
        )
        modules = {"a": mod}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "DomainEvent" in e.message]
        assert len(vestigial) == 1

    def test_consumes_with_name_reference(self):
        """CONSUMES relation: target appears as name reference → no vestigial."""
        cell = CellDecl(
            name="IncomingEvent",
            layer=Layer.APPLICATION,
            kind=Kind.MODEL,
            visibility=Visibility.PUBLIC,
            intent="An incoming event",
            schema="IncomingEvent schema",
            body="class IncomingEvent: pass",
            location=_loc(5),
        )
        mod = _simple_s0ma_module(
            module_name="a",
            exports=("handle_event",),
            nerves=(
                _make_nerve_with_body(
                    "handle_event",
                    (
                        "def handle_event(event):\n"
                        "    if isinstance(event, IncomingEvent):\n"
                        "        return True"
                    ),
                    depends_on=(
                        InlineAxon(
                            target="IncomingEvent",
                            relation=Relation.CONSUMES,
                            carries="event payload",
                            coupling=Coupling.LOOSE,
                            location=_loc(15),
                        ),
                    ),
                ),
            ),
            cells=(cell,),
        )
        modules = {"a": mod}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "IncomingEvent" in e.message]
        assert len(vestigial) == 0

    def test_consumes_with_parameter_annotation(self):
        """CONSUMES relation: target as param type annotation → no vestigial."""
        cell = CellDecl(
            name="TaskEvent",
            layer=Layer.APPLICATION,
            kind=Kind.MODEL,
            visibility=Visibility.PUBLIC,
            intent="A task event",
            schema="TaskEvent schema",
            body="class TaskEvent: pass",
            location=_loc(5),
        )
        mod = _simple_s0ma_module(
            module_name="a",
            exports=("process_task",),
            nerves=(
                _make_nerve_with_body(
                    "process_task",
                    "def process_task(event: TaskEvent):\n    return event",
                    depends_on=(
                        InlineAxon(
                            target="TaskEvent",
                            relation=Relation.CONSUMES,
                            carries="task event",
                            coupling=Coupling.LOOSE,
                            location=_loc(15),
                        ),
                    ),
                ),
            ),
            cells=(cell,),
        )
        modules = {"a": mod}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "TaskEvent" in e.message]
        assert len(vestigial) == 0

    def test_consumes_without_evidence(self):
        """CONSUMES with no body evidence → VESTIGIAL_IMPORT."""
        cell = CellDecl(
            name="TaskEvent",
            layer=Layer.APPLICATION,
            kind=Kind.MODEL,
            visibility=Visibility.PUBLIC,
            intent="A task event",
            schema="TaskEvent schema",
            body="class TaskEvent: pass",
            location=_loc(5),
        )
        mod = _simple_s0ma_module(
            module_name="a",
            exports=("process_task",),
            nerves=(
                _make_nerve_with_body(
                    "process_task",
                    "def process_task():\n    return 42",
                    depends_on=(
                        InlineAxon(
                            target="TaskEvent",
                            relation=Relation.CONSUMES,
                            carries="task event",
                            coupling=Coupling.LOOSE,
                            location=_loc(15),
                        ),
                    ),
                ),
            ),
            cells=(cell,),
        )
        modules = {"a": mod}
        errors = resolve_dependencies(modules, check_imports=False)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"
                     and "TaskEvent" in e.message]
        assert len(vestigial) == 1


# ===========================================================================
# Cross-module abstract interface validation (MS 11b)
# ===========================================================================


class TestCrossModuleAbstractInterfaceValidation:
    """Tests for cross-module CONSTRUCTS validation against abstract interfaces."""

    def test_cross_module_constructs_all_methods_present(self):
        """No error when concrete nerve implements all abstract interface methods."""
        # Module A: abstract nerve with interface
        mod_a = _simple_s0ma_module(
            module_name="adapters",
            exports=("LLMAdapter",),
            nerves=(
                NerveDecl(
                    name="LLMAdapter",
                    layer=Layer.INFRASTRUCTURE,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="Abstract LLM adapter",
                    expects="None",
                    guarantees="Interface methods",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    abstract=True,
                    interface=("chat", "chat_stream"),
                    body=None,
                    location=_loc(10),
                ),
            ),
        )

        # Module B: concrete nerve with CONSTRUCTS standalone axon
        mod_b = _simple_s0ma_module(
            module_name="openai_adapter",
            exports=("OpenAIAdapter",),
            uses=(
                UsesEntry(
                    qualified_name="adapters.LLMAdapter",
                    location=_loc(3),
                ),
            ),
            nerves=(
                NerveDecl(
                    name="OpenAIAdapter",
                    layer=Layer.INFRASTRUCTURE,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="OpenAI LLM adapter",
                    expects="API key",
                    guarantees="Implements LLM interface",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body=(
                        "def OpenAIAdapter():\n"
                        "    def chat(): pass\n"
                        "    def chat_stream(): pass\n"
                        '    return {"chat": chat, "chat_stream": chat_stream}'
                    ),
                    location=_loc(10),
                ),
            ),
            axons=(
                StandaloneAxonDecl(
                    source="OpenAIAdapter",
                    target="LLMAdapter",
                    relation=Relation.CONSTRUCTS,
                    intent="Implements LLM adapter interface",
                    carries="implementation",
                    coupling=Coupling.TIGHT,
                    location=_loc(25),
                ),
            ),
        )

        modules = {"adapters": mod_a, "openai_adapter": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        missing = [e for e in errors if e.code == "MISSING_INTERFACE_METHODS"]
        assert len(missing) == 0

    def test_cross_module_constructs_missing_methods(self):
        """Error when concrete nerve is missing an interface method."""
        mod_a = _simple_s0ma_module(
            module_name="adapters",
            exports=("LLMAdapter",),
            nerves=(
                NerveDecl(
                    name="LLMAdapter",
                    layer=Layer.INFRASTRUCTURE,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="Abstract LLM adapter",
                    expects="None",
                    guarantees="Interface methods",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    abstract=True,
                    interface=("chat", "chat_stream"),
                    body=None,
                    location=_loc(10),
                ),
            ),
        )

        # Concrete nerve only defines chat, missing chat_stream
        mod_b = _simple_s0ma_module(
            module_name="openai_adapter",
            exports=("OpenAIAdapter",),
            uses=(
                UsesEntry(
                    qualified_name="adapters.LLMAdapter",
                    location=_loc(3),
                ),
            ),
            nerves=(
                NerveDecl(
                    name="OpenAIAdapter",
                    layer=Layer.INFRASTRUCTURE,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="OpenAI LLM adapter",
                    expects="API key",
                    guarantees="Implements chat",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body=(
                        "def OpenAIAdapter():\n"
                        "    def chat(): pass\n"
                        '    return {"chat": chat}'
                    ),
                    location=_loc(10),
                ),
            ),
            axons=(
                StandaloneAxonDecl(
                    source="OpenAIAdapter",
                    target="LLMAdapter",
                    relation=Relation.CONSTRUCTS,
                    intent="Implements LLM adapter interface",
                    carries="implementation",
                    coupling=Coupling.TIGHT,
                    location=_loc(25),
                ),
            ),
        )

        modules = {"adapters": mod_a, "openai_adapter": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        missing = [e for e in errors if e.code == "MISSING_INTERFACE_METHODS"]
        assert len(missing) == 1
        assert "chat_stream" in missing[0].message
        assert missing[0].context["source_module"] == "openai_adapter"
        assert missing[0].context["target_module"] == "adapters"

    def test_cross_module_constructs_no_body(self):
        """Error when concrete nerve has no body."""
        mod_a = _simple_s0ma_module(
            module_name="adapters",
            exports=("LLMAdapter",),
            nerves=(
                NerveDecl(
                    name="LLMAdapter",
                    layer=Layer.INFRASTRUCTURE,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="Abstract LLM adapter",
                    expects="None",
                    guarantees="Interface methods",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    abstract=True,
                    interface=("chat",),
                    body=None,
                    location=_loc(10),
                ),
            ),
        )

        mod_b = _simple_s0ma_module(
            module_name="openai_adapter",
            exports=("OpenAIAdapter",),
            uses=(
                UsesEntry(
                    qualified_name="adapters.LLMAdapter",
                    location=_loc(3),
                ),
            ),
            nerves=(
                NerveDecl(
                    name="OpenAIAdapter",
                    layer=Layer.INFRASTRUCTURE,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="OpenAI LLM adapter",
                    expects="API key",
                    guarantees="Implements chat",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body=None,
                    location=_loc(10),
                ),
            ),
            axons=(
                StandaloneAxonDecl(
                    source="OpenAIAdapter",
                    target="LLMAdapter",
                    relation=Relation.CONSTRUCTS,
                    intent="Implements LLM adapter interface",
                    carries="implementation",
                    coupling=Coupling.TIGHT,
                    location=_loc(25),
                ),
            ),
        )

        modules = {"adapters": mod_a, "openai_adapter": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        missing = [e for e in errors if e.code == "MISSING_INTERFACE_METHODS"]
        assert len(missing) == 1
        assert "no body" in missing[0].message

    def test_non_abstract_target_no_validation(self):
        """CONSTRUCTS targeting a non-abstract nerve should not trigger interface checking."""
        mod_a = _simple_s0ma_module(
            module_name="utils",
            exports=("Helper",),
            nerves=(
                NerveDecl(
                    name="Helper",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Non-abstract helper",
                    expects="None",
                    guarantees="None",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    abstract=False,
                    body="def Helper(): pass",
                    location=_loc(10),
                ),
            ),
        )

        mod_b = _simple_s0ma_module(
            module_name="consumer",
            exports=("Consumer",),
            uses=(
                UsesEntry(
                    qualified_name="utils.Helper",
                    location=_loc(3),
                ),
            ),
            nerves=(
                NerveDecl(
                    name="Consumer",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Consumer",
                    expects="None",
                    guarantees="None",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="def Consumer(): pass",
                    location=_loc(10),
                ),
            ),
            axons=(
                StandaloneAxonDecl(
                    source="Consumer",
                    target="Helper",
                    relation=Relation.CONSTRUCTS,
                    intent="Uses helper",
                    carries="data",
                    coupling=Coupling.TIGHT,
                    location=_loc(25),
                ),
            ),
        )

        modules = {"utils": mod_a, "consumer": mod_b}
        errors = resolve_dependencies(modules, check_imports=False)
        missing = [e for e in errors if e.code == "MISSING_INTERFACE_METHODS"]
        assert len(missing) == 0

    def test_intra_module_constructs_unaffected(self):
        """Intra-module CONSTRUCTS handled by the semantic validator, not resolver."""
        # Both abstract and concrete in the same module — no standalone axon
        mod = _simple_s0ma_module(
            module_name="single",
            exports=("Base", "Impl"),
            nerves=(
                NerveDecl(
                    name="Base",
                    layer=Layer.APPLICATION,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="Abstract base",
                    expects="None",
                    guarantees="Interface",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    abstract=True,
                    interface=("do_work",),
                    body=None,
                    location=_loc(5),
                ),
                NerveDecl(
                    name="Impl",
                    layer=Layer.APPLICATION,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="Concrete impl",
                    expects="None",
                    guarantees="Does work",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    depends_on=(
                        InlineAxon(
                            target="Base",
                            relation=Relation.CONSTRUCTS,
                            carries="implementation",
                            coupling=Coupling.TIGHT,
                            location=_loc(20),
                        ),
                    ),
                    body="def Impl():\n    def do_work(): pass\n    return {'do_work': do_work}",
                    location=_loc(15),
                ),
            ),
        )

        modules = {"single": mod}
        errors = resolve_dependencies(modules, check_imports=False)
        # Resolver should NOT produce MISSING_INTERFACE_METHODS for intra-module
        # (that's the semantic validator's job)
        resolver_missing = [
            e for e in errors
            if e.code == "MISSING_INTERFACE_METHODS"
        ]
        assert len(resolver_missing) == 0

    def test_context_module_as_abstract_source(self):
        """Abstract nerve from a context module (--include) should still be validated."""
        # Context module = just another entry in the modules dict (from --include)
        context_mod = _simple_s0ma_module(
            module_name="base_adapters",
            exports=("BaseAdapter",),
            nerves=(
                NerveDecl(
                    name="BaseAdapter",
                    layer=Layer.INFRASTRUCTURE,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="Abstract base adapter",
                    expects="None",
                    guarantees="Interface",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    abstract=True,
                    interface=("connect", "disconnect"),
                    body=None,
                    location=_loc(10),
                ),
            ),
        )

        target_mod = _simple_s0ma_module(
            module_name="my_adapter",
            exports=("MyAdapter",),
            uses=(
                UsesEntry(
                    qualified_name="base_adapters.BaseAdapter",
                    location=_loc(3),
                ),
            ),
            nerves=(
                NerveDecl(
                    name="MyAdapter",
                    layer=Layer.INFRASTRUCTURE,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="My adapter",
                    expects="Config",
                    guarantees="Connects",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body=(
                        "def MyAdapter():\n"
                        "    def connect(): pass\n"
                        "    return {'connect': connect}"
                    ),
                    location=_loc(10),
                ),
            ),
            axons=(
                StandaloneAxonDecl(
                    source="MyAdapter",
                    target="BaseAdapter",
                    relation=Relation.CONSTRUCTS,
                    intent="Implements base adapter",
                    carries="implementation",
                    coupling=Coupling.TIGHT,
                    location=_loc(25),
                ),
            ),
        )

        # Both modules in the dict (context modules are treated the same)
        modules = {"base_adapters": context_mod, "my_adapter": target_mod}
        errors = resolve_dependencies(modules, check_imports=False)
        missing = [e for e in errors if e.code == "MISSING_INTERFACE_METHODS"]
        # Should find missing 'disconnect'
        assert len(missing) == 1
        assert "disconnect" in missing[0].message
        assert missing[0].context["target_module"] == "base_adapters"
