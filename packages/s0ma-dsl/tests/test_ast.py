"""Tests for AST node definitions and enums (Milestone 3).

Covers:
- Enum value completeness and serialization
- Kind-to-declaration-type constraints
- Relation authored/derived classification
- AST node construction with all required fields
- Optional fields default to appropriate values
- Frozen immutability
- S0maModule root node and all_declarations ordering
- Dogfooding: @component decorators are applied
"""

from __future__ import annotations

import pytest

from s0ma_dsl.ast_nodes import (
    VALID_KINDS_FOR_DECLARATION,
    CellDecl,
    Coupling,
    DeclarationType,
    EvaluatesAt,
    GanglionDecl,
    InlineAxon,
    Kind,
    Layer,
    ModuleDecl,
    NerveDecl,
    Relation,
    RequiresEntry,
    S0maModule,
    SourceLocation,
    StandaloneAxonDecl,
    TestDecl,
    UsesEntry,
    Visibility,
)

# ===================================================================
# Enum tests
# ===================================================================


class TestLayerEnum:
    def test_all_values_present(self):
        expected = {"DOMAIN", "APPLICATION", "INFRASTRUCTURE", "PRESENTATION", "FRAMEWORK"}
        assert {m.value for m in Layer} == expected

    def test_string_serialization(self):
        assert Layer.DOMAIN.value == "DOMAIN"
        assert Layer("APPLICATION") is Layer.APPLICATION


class TestKindEnum:
    def test_nerve_kinds(self):
        nerve_kinds = {Kind.SERVICE, Kind.FUNCTION, Kind.ADAPTER, Kind.ORCHESTRATOR}
        for k in nerve_kinds:
            assert k in VALID_KINDS_FOR_DECLARATION[DeclarationType.NERVE]

    def test_cell_kinds(self):
        cell_kinds = {Kind.MODEL, Kind.CONSTANT, Kind.CONFIG, Kind.ENUM, Kind.EXCEPTION, Kind.TYPE}
        for k in cell_kinds:
            assert k in VALID_KINDS_FOR_DECLARATION[DeclarationType.CELL]

    def test_framework_kind_valid_for_both(self):
        assert Kind.FRAMEWORK in VALID_KINDS_FOR_DECLARATION[DeclarationType.NERVE]
        assert Kind.FRAMEWORK in VALID_KINDS_FOR_DECLARATION[DeclarationType.CELL]

    def test_nerve_kinds_invalid_for_cell(self):
        nerve_only = {Kind.SERVICE, Kind.FUNCTION, Kind.ADAPTER, Kind.ORCHESTRATOR}
        for k in nerve_only:
            assert k not in VALID_KINDS_FOR_DECLARATION[DeclarationType.CELL]

    def test_cell_kinds_invalid_for_nerve(self):
        cell_only = {Kind.MODEL, Kind.CONSTANT, Kind.CONFIG, Kind.ENUM, Kind.EXCEPTION, Kind.TYPE}
        for k in cell_only:
            assert k not in VALID_KINDS_FOR_DECLARATION[DeclarationType.NERVE]

    def test_ganglion_test_axon_module_have_no_kinds(self):
        for dt in (
            DeclarationType.GANGLION,
            DeclarationType.TEST,
            DeclarationType.AXON,
            DeclarationType.MODULE,
        ):
            assert len(VALID_KINDS_FOR_DECLARATION[dt]) == 0

    def test_string_serialization(self):
        assert Kind.SERVICE.value == "SERVICE"
        assert Kind("CONSTANT") is Kind.CONSTANT

    def test_all_values_present(self):
        expected = {
            "SERVICE", "FUNCTION", "ADAPTER", "ORCHESTRATOR",
            "MODEL", "CONSTANT", "CONFIG", "ENUM", "EXCEPTION", "TYPE",
            "FRAMEWORK",
        }
        assert {k.value for k in Kind} == expected


class TestVisibilityEnum:
    def test_values(self):
        assert {v.value for v in Visibility} == {"PUBLIC", "INTERNAL", "TEST"}


class TestRelationEnum:
    def test_authored_relations(self):
        authored = {
            Relation.CALLS, Relation.CONSTRUCTS, Relation.READS,
            Relation.CONFIGURES, Relation.PRODUCES, Relation.CONSUMES,
        }
        for r in authored:
            assert r.is_authored()
            assert not r.is_derived()

    def test_derived_relations(self):
        derived = {Relation.RAISES, Relation.TYPE_USES}
        for r in derived:
            assert r.is_derived()
            assert not r.is_authored()

    def test_all_values_present(self):
        expected = {
            "CALLS", "CONSTRUCTS", "READS", "CONFIGURES",
            "PRODUCES", "CONSUMES", "RAISES", "TYPE_USES",
        }
        assert {r.value for r in Relation} == expected


class TestCouplingEnum:
    def test_values(self):
        assert {c.value for c in Coupling} == {"TIGHT", "LOOSE"}


class TestEvaluatesAtEnum:
    def test_values(self):
        expected = {"FUNCTION_BOUNDARY", "SUBSYSTEM", "SYSTEM"}
        assert {e.value for e in EvaluatesAt} == expected


class TestDeclarationTypeEnum:
    def test_values(self):
        expected = {
            "module", "nerve", "cell", "ganglion", "test", "axon",
            # M13 (feedback 5–6): module-private helper functions.
            "helper",
            "doc_ref", "doc_guide", "example",
        }
        assert {d.value for d in DeclarationType} == expected


# ===================================================================
# Sub-node tests
# ===================================================================


class TestSourceLocation:
    def test_construction(self):
        loc = SourceLocation(
            start_line=1, start_column=0,
            end_line=5, end_column=40,
            file="test.s0ma",
        )
        assert loc.start_line == 1
        assert loc.end_line == 5
        assert loc.file == "test.s0ma"

    def test_default_file(self):
        loc = SourceLocation(start_line=1, start_column=0, end_line=1, end_column=10)
        assert loc.file == ""

    def test_frozen(self):
        loc = SourceLocation(start_line=1, start_column=0, end_line=1, end_column=10)
        with pytest.raises(AttributeError):
            loc.start_line = 2  # type: ignore[misc]


class TestRequiresEntry:
    def test_simple(self):
        entry = RequiresEntry(module_path="time")
        assert entry.module_path == "time"
        assert entry.alias is None
        assert entry.is_from_import is False

    def test_from_import_with_alias(self):
        entry = RequiresEntry(module_path="uuid.UUID", alias="UUID", is_from_import=True)
        assert entry.module_path == "uuid.UUID"
        assert entry.alias == "UUID"
        assert entry.is_from_import is True

    def test_frozen(self):
        entry = RequiresEntry(module_path="os")
        with pytest.raises(AttributeError):
            entry.module_path = "sys"  # type: ignore[misc]


class TestUsesEntry:
    def test_simple(self):
        entry = UsesEntry(qualified_name="routing.select_evaluator")
        assert entry.qualified_name == "routing.select_evaluator"
        assert entry.alias is None

    def test_with_alias(self):
        entry = UsesEntry(qualified_name="auth.validate_token", alias="verify_token")
        assert entry.alias == "verify_token"


class TestInlineAxon:
    def test_construction(self):
        axon = InlineAxon(
            target="validate_envelope",
            relation=Relation.CALLS,
            carries="SignalEnvelope",
            coupling=Coupling.TIGHT,
        )
        assert axon.target == "validate_envelope"
        assert axon.relation is Relation.CALLS
        assert axon.carries == "SignalEnvelope"
        assert axon.coupling is Coupling.TIGHT

    def test_frozen(self):
        axon = InlineAxon(
            target="x", relation=Relation.READS, carries="data", coupling=Coupling.LOOSE
        )
        with pytest.raises(AttributeError):
            axon.target = "y"  # type: ignore[misc]


# ===================================================================
# Declaration node tests
# ===================================================================


class TestModuleDecl:
    def test_required_fields(self):
        mod = ModuleDecl(
            name="signal_processor",
            layer=Layer.APPLICATION,
            version="1.0.0",
            intent="Processes signals",
            exports=("process_signal", "SignalEnvelope"),
        )
        assert mod.name == "signal_processor"
        assert mod.layer is Layer.APPLICATION
        assert mod.version == "1.0.0"
        assert mod.exports == ("process_signal", "SignalEnvelope")

    def test_optional_defaults(self):
        mod = ModuleDecl(
            name="m", layer=Layer.DOMAIN, version="0.1.0", intent="test", exports=()
        )
        assert mod.requires == ()
        assert mod.uses == ()
        assert mod.tags == ()
        assert mod.location is None

    def test_with_requires_and_uses(self):
        mod = ModuleDecl(
            name="sp",
            layer=Layer.APPLICATION,
            version="1.0.0",
            intent="test",
            exports=("process_signal",),
            requires=(RequiresEntry("time"),),
            uses=(UsesEntry("routing.select_evaluator"),),
        )
        assert len(mod.requires) == 1
        assert len(mod.uses) == 1

    def test_frozen(self):
        mod = ModuleDecl(
            name="m", layer=Layer.DOMAIN, version="0.1.0", intent="test", exports=()
        )
        with pytest.raises(AttributeError):
            mod.name = "other"  # type: ignore[misc]


class TestNerveDecl:
    def test_all_required_fields(self):
        nerve = NerveDecl(
            name="validate_envelope",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.INTERNAL,
            intent="Validates signal envelopes",
            expects="envelope is not None",
            guarantees="Returns True if valid",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
        )
        assert nerve.name == "validate_envelope"
        assert nerve.kind is Kind.FUNCTION
        assert nerve.visibility is Visibility.INTERNAL
        assert nerve.evaluates_at is EvaluatesAt.FUNCTION_BOUNDARY

    def test_optional_defaults(self):
        nerve = NerveDecl(
            name="n",
            layer=Layer.DOMAIN,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="test",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
        )
        assert nerve.raises == ()
        assert nerve.latency_ms is None
        assert nerve.depends_on == ()
        assert nerve.version is None
        assert nerve.tags == ()
        assert nerve.body is None

    def test_with_optional_fields(self):
        nerve = NerveDecl(
            name="process_signal",
            layer=Layer.APPLICATION,
            kind=Kind.ORCHESTRATOR,
            visibility=Visibility.PUBLIC,
            intent="Process signals",
            expects="valid envelope",
            guarantees="signal routed",
            evaluates_at=EvaluatesAt.SUBSYSTEM,
            raises=("SignalValidationError",),
            latency_ms=50,
            depends_on=(
                InlineAxon(
                    target="validate_envelope",
                    relation=Relation.CALLS,
                    carries="SignalEnvelope",
                    coupling=Coupling.TIGHT,
                ),
            ),
            version="1.0.0",
            tags=("signal", "processing"),
            body="def process_signal(envelope): ...",
        )
        assert nerve.raises == ("SignalValidationError",)
        assert nerve.latency_ms == 50
        assert len(nerve.depends_on) == 1
        assert nerve.body is not None


class TestCellDecl:
    def test_model_cell(self):
        cell = CellDecl(
            name="SignalEnvelope",
            layer=Layer.APPLICATION,
            kind=Kind.MODEL,
            visibility=Visibility.PUBLIC,
            intent="Wraps a raw signal with metadata",
            schema="Immutable dataclass with source, timestamp, trace_id, payload",
        )
        assert cell.kind is Kind.MODEL
        assert cell.schema == "Immutable dataclass with source, timestamp, trace_id, payload"

    def test_constant_cell(self):
        cell = CellDecl(
            name="MAX_STALENESS_SECONDS",
            layer=Layer.APPLICATION,
            kind=Kind.CONSTANT,
            visibility=Visibility.INTERNAL,
            intent="Max age for signal envelopes",
            schema="int constant. Value: 300.",
        )
        assert cell.kind is Kind.CONSTANT

    def test_exception_cell(self):
        cell = CellDecl(
            name="SignalValidationError",
            layer=Layer.APPLICATION,
            kind=Kind.EXCEPTION,
            visibility=Visibility.PUBLIC,
            intent="Raised when signal validation fails",
            schema="Exception with message string",
        )
        assert cell.kind is Kind.EXCEPTION

    def test_optional_defaults(self):
        cell = CellDecl(
            name="C", layer=Layer.DOMAIN, kind=Kind.MODEL, visibility=Visibility.PUBLIC,
            intent="test", schema="test schema",
        )
        assert cell.invariants is None
        assert cell.version is None
        assert cell.tags == ()
        assert cell.body is None

    def test_with_invariants(self):
        cell = CellDecl(
            name="C", layer=Layer.DOMAIN, kind=Kind.MODEL, visibility=Visibility.PUBLIC,
            intent="test", schema="test", invariants="all fields non-null",
        )
        assert cell.invariants == "all fields non-null"


class TestGanglionDecl:
    def test_required_fields(self):
        ganglion = GanglionDecl(
            name="latency_monitor",
            layer=Layer.APPLICATION,
            visibility=Visibility.INTERNAL,
            intent="Monitors signal processing latency",
            observes=("process_signal", "validate_envelope"),
            scope=EvaluatesAt.SUBSYSTEM,
            priors="Expected latency < 100ms",
            on_anomaly="Log warning and emit alert signal",
        )
        assert ganglion.name == "latency_monitor"
        assert ganglion.scope is EvaluatesAt.SUBSYSTEM
        assert len(ganglion.observes) == 2

    def test_optional_defaults(self):
        ganglion = GanglionDecl(
            name="g", layer=Layer.DOMAIN, visibility=Visibility.INTERNAL,
            intent="test", observes=("x",), scope=EvaluatesAt.FUNCTION_BOUNDARY,
            priors="none", on_anomaly="log",
        )
        assert ganglion.depends_on == ()
        assert ganglion.tags == ()
        assert ganglion.body is None

    def test_observes_patterns(self):
        """Ganglia support exact, module-glob, and layer-glob patterns."""
        ganglion = GanglionDecl(
            name="g",
            layer=Layer.APPLICATION,
            visibility=Visibility.INTERNAL,
            intent="Monitors all",
            observes=("validate_envelope", "signal_processor.*", "APPLICATION::*"),
            scope=EvaluatesAt.SYSTEM,
            priors="baseline",
            on_anomaly="alert",
        )
        assert ganglion.observes == ("validate_envelope", "signal_processor.*", "APPLICATION::*")


class TestTestDecl:
    def test_required_fields(self):
        test = TestDecl(
            name="test_validate_envelope",
            layer=Layer.APPLICATION,
            intent="Verifies envelope validation logic",
            tests=("validate_envelope",),
        )
        assert test.name == "test_validate_envelope"
        assert test.tests == ("validate_envelope",)

    def test_optional_defaults(self):
        test = TestDecl(
            name="t", layer=Layer.DOMAIN, intent="test", tests=("x",),
        )
        assert test.expects is None
        assert test.depends_on == ()
        assert test.tags == ()
        assert test.body is None

    def test_with_optional_fields(self):
        test = TestDecl(
            name="test_process",
            layer=Layer.APPLICATION,
            intent="Tests signal processing",
            tests=("process_signal", "validate_envelope"),
            expects="registry populated",
            tags=("integration",),
        )
        assert test.expects == "registry populated"
        assert len(test.tests) == 2


class TestStandaloneAxonDecl:
    def test_construction(self):
        axon = StandaloneAxonDecl(
            source="process_signal",
            target="select_evaluator",
            relation=Relation.CALLS,
            intent="process_signal delegates evaluator selection to routing module",
            carries="source layer string",
            coupling=Coupling.LOOSE,
        )
        assert axon.source == "process_signal"
        assert axon.target == "select_evaluator"
        assert axon.relation is Relation.CALLS
        assert axon.coupling is Coupling.LOOSE

    def test_frozen(self):
        axon = StandaloneAxonDecl(
            source="a", target="b", relation=Relation.READS,
            intent="test", carries="data", coupling=Coupling.TIGHT,
        )
        with pytest.raises(AttributeError):
            axon.source = "c"  # type: ignore[misc]


# ===================================================================
# Root node tests
# ===================================================================


class TestS0maModule:
    def _make_module(self) -> S0maModule:
        """Build a S0maModule matching the golden fixture structure."""
        def loc(sl, el):
            return SourceLocation(sl, 0, el, 0, "signal_processor.s0ma")

        mod_decl = ModuleDecl(
            name="signal_processor",
            layer=Layer.APPLICATION,
            version="1.0.0",
            intent="Receives raw nerve signals, validates, and routes them.",
            exports=("process_signal", "SignalEnvelope"),
            requires=(
                RequiresEntry("uuid.UUID", is_from_import=True),
                RequiresEntry("dataclasses.dataclass", is_from_import=True),
                RequiresEntry("time"),
            ),
            uses=(
                UsesEntry("routing.select_evaluator"),
                UsesEntry("errors.SignalValidationError"),
            ),
            location=loc(1, 8),
        )

        cell1 = CellDecl(
            name="SignalEnvelope",
            layer=Layer.APPLICATION,
            kind=Kind.MODEL,
            visibility=Visibility.PUBLIC,
            intent="Wraps a raw nerve signal with metadata for evaluation routing.",
            schema="Immutable dataclass. source, timestamp, trace_id, payload.",
            body="@dataclass(frozen=True)\nclass SignalEnvelope:\n    ...",
            location=loc(10, 23),
        )

        cell2 = CellDecl(
            name="MAX_STALENESS_SECONDS",
            layer=Layer.APPLICATION,
            kind=Kind.CONSTANT,
            visibility=Visibility.INTERNAL,
            intent="Max signal age before rejection.",
            schema="int constant. Value: 300.",
            body="MAX_STALENESS_SECONDS: int = 300",
            location=loc(25, 32),
        )

        nerve1 = NerveDecl(
            name="validate_envelope",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.INTERNAL,
            intent="Validates signal envelopes.",
            expects="envelope is not None",
            guarantees="Returns True if valid",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            raises=("SignalValidationError",),
            latency_ms=5,
            depends_on=(
                InlineAxon(
                    target="MAX_STALENESS_SECONDS",
                    relation=Relation.READS,
                    carries="threshold",
                    coupling=Coupling.TIGHT,
                ),
            ),
            body="def validate_envelope(envelope): ...",
            location=loc(34, 52),
        )

        nerve2 = NerveDecl(
            name="process_signal",
            layer=Layer.APPLICATION,
            kind=Kind.ORCHESTRATOR,
            visibility=Visibility.PUBLIC,
            intent="Primary entry point for signal processing.",
            expects="envelope is a valid SignalEnvelope",
            guarantees="Signal reaches exactly one evaluator",
            evaluates_at=EvaluatesAt.SUBSYSTEM,
            raises=("SignalValidationError",),
            latency_ms=50,
            depends_on=(
                InlineAxon(
                    target="validate_envelope",
                    relation=Relation.CALLS,
                    carries="SignalEnvelope",
                    coupling=Coupling.TIGHT,
                ),
            ),
            body="def process_signal(envelope): ...",
            location=loc(54, 71),
        )

        axon = StandaloneAxonDecl(
            source="process_signal",
            target="select_evaluator",
            relation=Relation.CALLS,
            intent="Delegates evaluator selection to routing module.",
            carries="source layer string",
            coupling=Coupling.LOOSE,
            location=loc(74, 80),
        )

        return S0maModule(
            module=mod_decl,
            cells=(cell1, cell2),
            nerves=(nerve1, nerve2),
            axons=(axon,),
        )

    def test_construction(self):
        sm = self._make_module()
        assert sm.module.name == "signal_processor"
        assert len(sm.cells) == 2
        assert len(sm.nerves) == 2
        assert len(sm.axons) == 1
        assert len(sm.ganglia) == 0
        assert len(sm.tests) == 0

    def test_all_declarations_ordering(self):
        sm = self._make_module()
        decls = sm.all_declarations
        assert len(decls) == 5  # 2 cells + 2 nerves + 1 axon
        # Verify source-order by start_line
        lines = [d.location.start_line for d in decls]
        assert lines == sorted(lines)

    def test_empty_module(self):
        mod = ModuleDecl(
            name="empty", layer=Layer.DOMAIN, version="0.1.0",
            intent="Empty module", exports=(),
        )
        sm = S0maModule(module=mod)
        assert sm.all_declarations == ()

    def test_frozen(self):
        sm = self._make_module()
        with pytest.raises(AttributeError):
            sm.module = None  # type: ignore[misc]


# ===================================================================
# Dogfooding verification
# ===================================================================


class TestDogfooding:
    """Verify that @component decorators are applied to all AST node types."""

    def test_enums_have_component_metadata(self):
        for cls in (Layer, Kind, Visibility, Relation, Coupling, EvaluatesAt, DeclarationType):
            assert hasattr(cls, "__component__"), f"{cls.__name__} missing @component"

    def test_nodes_have_component_metadata(self):
        for cls in (
            SourceLocation, RequiresEntry, UsesEntry, InlineAxon,
            ModuleDecl, NerveDecl, CellDecl, GanglionDecl, TestDecl,
            StandaloneAxonDecl, S0maModule,
        ):
            assert hasattr(cls, "__component__"), f"{cls.__name__} missing @component"

    def test_component_names_prefixed(self):
        """All transpiler components use 'S0maDSL_' prefix to avoid collisions."""
        for cls in (
            Layer, Kind, Visibility, Relation, Coupling, EvaluatesAt, DeclarationType,
            SourceLocation, RequiresEntry, UsesEntry, InlineAxon,
            ModuleDecl, NerveDecl, CellDecl, GanglionDecl, TestDecl,
            StandaloneAxonDecl, S0maModule,
        ):
            comp_name = cls.__component__.name
            assert comp_name.startswith("S0maDSL_"), (
                f"{cls.__name__} component name '{comp_name}' must start with 'S0maDSL_'"
            )
