"""IR generation tests for the s0ma DSL transpiler (Milestone 10).

Tests the IR schema types, content hash generation, and IR builder.
Verifies that the golden fixture produces valid, deterministic JSON
with correct canonical IDs, edge categories, and ordering.

PRD references: FR-23, §2.5 (IR schema), §2.5.3 (determinism), NFR-01
"""

from __future__ import annotations

import json

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
from s0ma_dsl.ir.builder import IRBuilder, build_ir, compute_content_hash
from s0ma_dsl.ir.schema import (
    SCHEMA_VERSION,
    TRANSPILER_VERSION,
    IRAuthoredEdge,
    IRComponent,
    IRComponentLocation,
    IRDerivedEdge,
    IRDocument,
    IREdges,
    IRImports,
    IRModule,
    IRRequiresImport,
    IRUsesImport,
    IRVerificationEdge,
)
from s0ma_dsl.semantic.derived_edges import DerivedEdge
from tests.conftest import VALID_FIXTURES_DIR

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _loc(start: int = 1, end: int = 5) -> SourceLocation:
    return SourceLocation(start_line=start, start_column=0, end_line=end, end_column=0)


def _make_minimal_module() -> S0maModule:
    """Create a minimal valid S0maModule for testing."""
    return S0maModule(
        module=ModuleDecl(
            name="test_module",
            layer=Layer.APPLICATION,
            version="1.0.0",
            intent="A test module",
            exports=("my_func",),
            location=_loc(1, 5),
        ),
        nerves=(
            NerveDecl(
                name="my_func",
                layer=Layer.APPLICATION,
                kind=Kind.FUNCTION,
                visibility=Visibility.PUBLIC,
                intent="A test function",
                expects="valid input",
                guarantees="returns result",
                evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                location=_loc(7, 15),
            ),
        ),
    )


def _make_full_module() -> S0maModule:
    """Create a feature-rich S0maModule with all declaration types."""
    return S0maModule(
        module=ModuleDecl(
            name="signal_proc",
            layer=Layer.APPLICATION,
            version="1.0.0",
            intent="Signal processing module",
            exports=("process_signal", "SignalEnvelope"),
            requires=(
                RequiresEntry(module_path="uuid.UUID", is_from_import=True),
                RequiresEntry(module_path="time"),
            ),
            uses=(
                UsesEntry(qualified_name="routing.select_evaluator"),
                UsesEntry(qualified_name="errors.SignalValidationError"),
            ),
            tags=("processing",),
            location=_loc(1, 8),
        ),
        cells=(
            CellDecl(
                name="SignalEnvelope",
                layer=Layer.APPLICATION,
                kind=Kind.MODEL,
                visibility=Visibility.PUBLIC,
                intent="Wraps a raw nerve signal",
                schema="Immutable dataclass",
                body="@dataclass(frozen=True)\nclass SignalEnvelope:\n    source: str\n",
                location=_loc(10, 18),
            ),
            CellDecl(
                name="MAX_STALENESS",
                layer=Layer.APPLICATION,
                kind=Kind.CONSTANT,
                visibility=Visibility.INTERNAL,
                intent="Max staleness in seconds",
                schema="int constant",
                body="MAX_STALENESS: int = 300\n",
                location=_loc(20, 25),
            ),
        ),
        nerves=(
            NerveDecl(
                name="validate_envelope",
                layer=Layer.APPLICATION,
                kind=Kind.FUNCTION,
                visibility=Visibility.INTERNAL,
                intent="Validates signal envelopes",
                expects="envelope is not None",
                guarantees="Returns True if valid",
                evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                raises=("SignalValidationError",),
                latency_ms=5,
                depends_on=(
                    InlineAxon(
                        target="MAX_STALENESS",
                        relation=Relation.READS,
                        carries="threshold",
                        coupling=Coupling.TIGHT,
                        location=_loc(35, 35),
                    ),
                ),
                body="def validate_envelope(envelope: SignalEnvelope) -> bool:\n    pass\n",
                location=_loc(27, 40),
            ),
            NerveDecl(
                name="process_signal",
                layer=Layer.APPLICATION,
                kind=Kind.ORCHESTRATOR,
                visibility=Visibility.PUBLIC,
                intent="Primary entry point for signal processing",
                expects="envelope is a valid SignalEnvelope",
                guarantees="Signal reaches exactly one subsystem evaluator",
                evaluates_at=EvaluatesAt.SUBSYSTEM,
                raises=("SignalValidationError",),
                latency_ms=50,
                depends_on=(
                    InlineAxon(
                        target="validate_envelope",
                        relation=Relation.CALLS,
                        carries="SignalEnvelope",
                        coupling=Coupling.TIGHT,
                        location=_loc(55, 55),
                    ),
                ),
                body="def process_signal(envelope: SignalEnvelope) -> bool:\n    pass\n",
                location=_loc(42, 60),
            ),
        ),
        axons=(
            StandaloneAxonDecl(
                source="process_signal",
                target="routing.select_evaluator",
                relation=Relation.CALLS,
                intent="process_signal delegates evaluator selection",
                carries="source layer string",
                coupling=Coupling.LOOSE,
                location=_loc(62, 68),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Test: Schema types (10.1)
# ---------------------------------------------------------------------------


class TestIRSchemaTypes:
    """Test IR schema dataclass construction and serialization."""

    def test_ir_component_location(self) -> None:
        loc = IRComponentLocation(start_line=10, end_line=20)
        d = loc.to_dict()
        assert d == {"start_line": 10, "end_line": 20}

    def test_ir_module(self) -> None:
        m = IRModule(
            name="test_mod",
            layer="APPLICATION",
            version="1.0.0",
            intent="A test module",
            content_hash="sha256:abc123",
            source_file="test.s0ma",
            transpiled_file="test.py",
            tags=("tag1",),
        )
        d = m.to_dict()
        assert d["name"] == "test_mod"
        assert d["layer"] == "APPLICATION"
        assert d["tags"] == ["tag1"]
        assert d["content_hash"] == "sha256:abc123"

    def test_ir_component(self) -> None:
        c = IRComponent(
            canonical_id="mod::func",
            declaration_type="nerve",
            kind="FUNCTION",
            visibility="PUBLIC",
            intent="A function",
            fields={"expects": "valid input"},
            location=IRComponentLocation(start_line=5, end_line=10),
        )
        d = c.to_dict()
        assert d["canonical_id"] == "mod::func"
        assert d["declaration_type"] == "nerve"
        assert d["fields"]["expects"] == "valid input"

    def test_ir_authored_edge(self) -> None:
        e = IRAuthoredEdge(
            source="mod::a",
            target="mod::b",
            relation="CALLS",
            carries="data",
            coupling="TIGHT",
            intent="a calls b",
            origin="inline_depends_on",
        )
        d = e.to_dict()
        assert d["source"] == "mod::a"
        assert d["origin"] == "inline_depends_on"

    def test_ir_derived_edge(self) -> None:
        e = IRDerivedEdge(
            source="mod::a",
            target="mod::b",
            relation="RAISES",
            origin="raises_field",
        )
        d = e.to_dict()
        assert d["relation"] == "RAISES"
        assert d["origin"] == "raises_field"

    def test_ir_verification_edge(self) -> None:
        e = IRVerificationEdge(
            test="mod::test_func",
            validates="mod::my_func",
        )
        d = e.to_dict()
        assert d["test"] == "mod::test_func"
        assert d["origin"] == "tests_field"

    def test_ir_imports(self) -> None:
        imports = IRImports(
            requires=(
                IRRequiresImport(module_path="uuid.UUID", alias=None, is_from_import=True),
            ),
            uses=(
                IRUsesImport(
                    qualified_name="routing.select_evaluator",
                    alias=None,
                    resolved_canonical_id="routing::select_evaluator",
                ),
            ),
        )
        d = imports.to_dict()
        assert len(d["requires"]) == 1
        assert d["requires"][0]["is_from_import"] is True
        assert d["uses"][0]["resolved_canonical_id"] == "routing::select_evaluator"
        assert d["privileged"] == []

    def test_ir_document_to_dict_has_sorted_keys(self) -> None:
        """Verify top-level keys are alphabetically sorted for determinism."""
        doc = IRDocument(
            schema_version=SCHEMA_VERSION,
            transpiler_version=TRANSPILER_VERSION,
            source_hash="sha256:0000000000000000",
            module=IRModule(
                name="m", layer="APPLICATION", version="1.0.0",
                intent="x", content_hash="", source_file="",
                transpiled_file="",
            ),
            components=(),
            edges=IREdges(),
            imports=IRImports(),
            exports=(),
        )
        d = doc.to_dict()
        keys = list(d.keys())
        assert keys == sorted(keys), f"Top-level keys not sorted: {keys}"


# ---------------------------------------------------------------------------
# Test: Content hash (10.2)
# ---------------------------------------------------------------------------


class TestContentHash:
    """Test content hash generation."""

    def test_hash_deterministic(self) -> None:
        """Same input produces same hash."""
        text = "module test\n    layer: APPLICATION\n"
        h1 = compute_content_hash(text)
        h2 = compute_content_hash(text)
        assert h1 == h2

    def test_hash_prefix(self) -> None:
        """Hash is prefixed with sha256:."""
        h = compute_content_hash("hello")
        assert h.startswith("sha256:")

    def test_hash_hex_length(self) -> None:
        """SHA-256 hex digest is 64 characters."""
        h = compute_content_hash("test")
        hex_part = h.removeprefix("sha256:")
        assert len(hex_part) == 64

    def test_different_input_different_hash(self) -> None:
        """Different inputs produce different hashes."""
        h1 = compute_content_hash("input a")
        h2 = compute_content_hash("input b")
        assert h1 != h2

    def test_empty_input(self) -> None:
        """Empty string still produces a valid hash."""
        h = compute_content_hash("")
        assert h.startswith("sha256:")
        assert len(h.removeprefix("sha256:")) == 64


# ---------------------------------------------------------------------------
# Test: IR Builder — minimal module (10.3)
# ---------------------------------------------------------------------------


class TestIRBuilderMinimal:
    """Test IR builder with a minimal module."""

    def test_build_returns_ir_document(self) -> None:
        module = _make_minimal_module()
        builder = IRBuilder(source_file="test.s0ma", source_text="source")
        doc = builder.build(module)
        assert isinstance(doc, IRDocument)

    def test_schema_version(self) -> None:
        module = _make_minimal_module()
        doc = build_ir(module)
        assert doc.schema_version == SCHEMA_VERSION

    def test_transpiler_version(self) -> None:
        module = _make_minimal_module()
        doc = build_ir(module)
        assert doc.transpiler_version == TRANSPILER_VERSION

    def test_module_metadata(self) -> None:
        module = _make_minimal_module()
        doc = build_ir(module, source_file="test.s0ma", source_text="content")
        assert doc.module.name == "test_module"
        assert doc.module.layer == "APPLICATION"
        assert doc.module.version == "1.0.0"
        assert doc.module.intent == "A test module"
        assert doc.module.source_file == "test.s0ma"
        assert doc.module.content_hash.startswith("sha256:")

    def test_component_canonical_id(self) -> None:
        module = _make_minimal_module()
        doc = build_ir(module)
        assert len(doc.components) == 1
        assert doc.components[0].canonical_id == "test_module::my_func"

    def test_component_declaration_type(self) -> None:
        module = _make_minimal_module()
        doc = build_ir(module)
        assert doc.components[0].declaration_type == "nerve"

    def test_component_fields(self) -> None:
        module = _make_minimal_module()
        doc = build_ir(module)
        fields = doc.components[0].fields
        assert fields["expects"] == "valid input"
        assert fields["guarantees"] == "returns result"
        assert fields["evaluates_at"] == "FUNCTION_BOUNDARY"

    def test_exports(self) -> None:
        module = _make_minimal_module()
        doc = build_ir(module)
        assert doc.exports == ("my_func",)

    def test_no_edges_in_minimal(self) -> None:
        module = _make_minimal_module()
        doc = build_ir(module)
        assert doc.edges.authored == ()
        assert doc.edges.derived == ()
        assert doc.edges.verification == ()


# ---------------------------------------------------------------------------
# Test: IR Builder — full module (10.3)
# ---------------------------------------------------------------------------


class TestIRBuilderFull:
    """Test IR builder with a feature-rich module."""

    def setup_method(self) -> None:
        self.module = _make_full_module()
        self.doc = build_ir(
            self.module,
            source_file="signal_proc.s0ma",
            source_text="full module source text",
            transpiled_file="signal_proc.py",
        )

    def test_module_tags(self) -> None:
        assert self.doc.module.tags == ("processing",)

    def test_component_count(self) -> None:
        """4 components: 2 cells + 2 nerves (standalone axon is not a component)."""
        assert len(self.doc.components) == 4

    def test_components_in_source_order(self) -> None:
        """Components ordered by declaration line, not alphabetically."""
        ids = [c.canonical_id for c in self.doc.components]
        assert ids == [
            "signal_proc::SignalEnvelope",       # line 10
            "signal_proc::MAX_STALENESS",        # line 20
            "signal_proc::validate_envelope",    # line 27
            "signal_proc::process_signal",       # line 42
        ]

    def test_cell_model_ir(self) -> None:
        envelope = self.doc.components[0]
        assert envelope.declaration_type == "cell"
        assert envelope.kind == "MODEL"
        assert envelope.visibility == "PUBLIC"
        assert envelope.fields["schema"] == "Immutable dataclass"

    def test_cell_constant_ir(self) -> None:
        const = self.doc.components[1]
        assert const.kind == "CONSTANT"
        assert const.visibility == "INTERNAL"

    def test_nerve_with_optional_fields(self) -> None:
        validate = self.doc.components[2]
        assert validate.fields["raises"] == ["SignalValidationError"]
        assert validate.fields["latency_ms"] == 5

    def test_standalone_axon_not_in_components(self) -> None:
        """Standalone axons produce edges, not component entries."""
        ids = [c.canonical_id for c in self.doc.components]
        assert all("axon" not in cid for cid in ids)

    # -- Authored edges --

    def test_inline_depends_on_edges(self) -> None:
        """Inline depends_on entries expanded to full authored edges."""
        authored = self.doc.edges.authored
        inline_edges = [e for e in authored if e.origin == "inline_depends_on"]
        assert len(inline_edges) == 2

    def test_inline_edge_canonical_ids(self) -> None:
        authored = self.doc.edges.authored
        inline_edges = [e for e in authored if e.origin == "inline_depends_on"]
        # Sort by source for deterministic checking
        by_source = sorted(inline_edges, key=lambda e: e.source)

        # process_signal -> validate_envelope
        ps_edge = [e for e in by_source if "process_signal" in e.source][0]
        assert ps_edge.source == "signal_proc::process_signal"
        assert ps_edge.target == "signal_proc::validate_envelope"
        assert ps_edge.relation == "CALLS"
        assert ps_edge.coupling == "TIGHT"

        # validate_envelope -> MAX_STALENESS
        ve_edge = [e for e in by_source if "validate_envelope" in e.source][0]
        assert ve_edge.source == "signal_proc::validate_envelope"
        assert ve_edge.target == "signal_proc::MAX_STALENESS"
        assert ve_edge.relation == "READS"

    def test_inline_edge_auto_intent(self) -> None:
        """Inline edges get auto-generated intent per PRD §2.2.7."""
        authored = self.doc.edges.authored
        inline_edges = [e for e in authored if e.origin == "inline_depends_on"]
        for edge in inline_edges:
            assert edge.intent  # Non-empty
            assert "::" not in edge.intent  # Uses short names, not canonical IDs

    def test_standalone_axon_edge(self) -> None:
        authored = self.doc.edges.authored
        standalone = [e for e in authored if e.origin == "standalone_axon"]
        assert len(standalone) == 1
        axon_edge = standalone[0]
        assert axon_edge.source == "signal_proc::process_signal"
        assert axon_edge.target == "routing::select_evaluator"
        assert axon_edge.relation == "CALLS"
        assert axon_edge.coupling == "LOOSE"

    def test_authored_edges_sorted(self) -> None:
        """Authored edges sorted by source, then target."""
        authored = self.doc.edges.authored
        keys = [(e.source, e.target) for e in authored]
        assert keys == sorted(keys)

    # -- Imports --

    def test_requires_imports(self) -> None:
        requires = self.doc.imports.requires
        assert len(requires) == 2
        assert requires[0].module_path == "uuid.UUID"
        assert requires[0].is_from_import is True
        assert requires[1].module_path == "time"

    def test_uses_imports(self) -> None:
        uses = self.doc.imports.uses
        assert len(uses) == 2
        assert uses[0].qualified_name == "routing.select_evaluator"
        assert uses[0].resolved_canonical_id == "routing::select_evaluator"
        assert uses[1].qualified_name == "errors.SignalValidationError"
        assert uses[1].resolved_canonical_id == "errors::SignalValidationError"

    def test_imports_preserve_source_order(self) -> None:
        """Import lists preserve declaration order, not alphabetical."""
        requires = self.doc.imports.requires
        assert requires[0].module_path == "uuid.UUID"
        assert requires[1].module_path == "time"

    def test_exports(self) -> None:
        assert self.doc.exports == ("process_signal", "SignalEnvelope")


# ---------------------------------------------------------------------------
# Test: Derived edges in IR (10.3 + M9 integration)
# ---------------------------------------------------------------------------


class TestIRBuilderDerivedEdges:
    """Test derived edge inclusion in IR."""

    def test_raises_edges_in_ir(self) -> None:
        module = _make_full_module()
        derived = [
            DerivedEdge(
                source="validate_envelope",
                target="SignalValidationError",
                target_canonical="errors::SignalValidationError",
                relation=Relation.RAISES,
                origin="raises_field",
                source_line=27,
            ),
            DerivedEdge(
                source="process_signal",
                target="SignalValidationError",
                target_canonical="errors::SignalValidationError",
                relation=Relation.RAISES,
                origin="raises_field",
                source_line=42,
            ),
        ]
        doc = build_ir(module, derived_edges=derived)
        ir_derived = doc.edges.derived
        assert len(ir_derived) == 2
        assert all(e.relation == "RAISES" for e in ir_derived)
        assert all(e.origin == "raises_field" for e in ir_derived)

    def test_type_uses_edges_in_ir(self) -> None:
        module = _make_full_module()
        derived = [
            DerivedEdge(
                source="validate_envelope",
                target="SignalEnvelope",
                target_canonical="signal_proc::SignalEnvelope",
                relation=Relation.TYPE_USES,
                origin="function_signature",
                source_line=27,
            ),
        ]
        doc = build_ir(module, derived_edges=derived)
        ir_derived = doc.edges.derived
        assert len(ir_derived) == 1
        assert ir_derived[0].source == "signal_proc::validate_envelope"
        assert ir_derived[0].target == "signal_proc::SignalEnvelope"
        assert ir_derived[0].relation == "TYPE_USES"

    def test_derived_edges_canonical_ids(self) -> None:
        """Derived edges use canonical IDs (module::component)."""
        module = _make_full_module()
        derived = [
            DerivedEdge(
                source="validate_envelope",
                target="SignalValidationError",
                target_canonical="errors::SignalValidationError",
                relation=Relation.RAISES,
                origin="raises_field",
            ),
        ]
        doc = build_ir(module, derived_edges=derived)
        edge = doc.edges.derived[0]
        assert "::" in edge.source
        assert "::" in edge.target

    def test_derived_edges_sorted(self) -> None:
        """Derived edges sorted by source, then target."""
        module = _make_full_module()
        derived = [
            DerivedEdge(
                source="process_signal",
                target="SignalValidationError",
                target_canonical="errors::SignalValidationError",
                relation=Relation.RAISES,
                origin="raises_field",
            ),
            DerivedEdge(
                source="validate_envelope",
                target="SignalValidationError",
                target_canonical="errors::SignalValidationError",
                relation=Relation.RAISES,
                origin="raises_field",
            ),
            DerivedEdge(
                source="process_signal",
                target="SignalEnvelope",
                target_canonical="signal_proc::SignalEnvelope",
                relation=Relation.TYPE_USES,
                origin="function_signature",
            ),
        ]
        doc = build_ir(module, derived_edges=derived)
        ir_derived = doc.edges.derived
        keys = [(e.source, e.target) for e in ir_derived]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Test: Verification edges
# ---------------------------------------------------------------------------


class TestIRBuilderVerification:
    """Test verification edge generation from test declarations."""

    def test_verification_edges(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="my_tests",
                layer=Layer.APPLICATION,
                version="1.0.0",
                intent="Tests",
                exports=(),
                location=_loc(1, 5),
            ),
            nerves=(
                NerveDecl(
                    name="my_func",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="A function",
                    expects="input",
                    guarantees="output",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    location=_loc(7, 10),
                ),
            ),
            tests=(
                TestDecl(
                    name="test_my_func",
                    layer=Layer.APPLICATION,
                    intent="Tests my_func",
                    tests=("my_func",),
                    location=_loc(12, 20),
                ),
            ),
        )
        doc = build_ir(module)
        verification = doc.edges.verification
        assert len(verification) == 1
        assert verification[0].test == "my_tests::test_my_func"
        assert verification[0].validates == "my_tests::my_func"
        assert verification[0].origin == "tests_field"

    def test_test_component_in_ir(self) -> None:
        """Test declarations appear as components with declaration_type='test'."""
        module = S0maModule(
            module=ModuleDecl(
                name="tests_mod",
                layer=Layer.APPLICATION,
                version="1.0.0",
                intent="Tests",
                exports=(),
                location=_loc(1, 3),
            ),
            tests=(
                TestDecl(
                    name="test_something",
                    layer=Layer.APPLICATION,
                    intent="Tests something",
                    tests=("target_func",),
                    expects="preconditions",
                    location=_loc(5, 15),
                ),
            ),
        )
        doc = build_ir(module)
        assert len(doc.components) == 1
        comp = doc.components[0]
        assert comp.declaration_type == "test"
        assert comp.kind is None
        assert comp.visibility is None
        assert comp.fields["tests"] == ["target_func"]
        assert comp.fields["expects"] == "preconditions"


# ---------------------------------------------------------------------------
# Test: Ganglion in IR
# ---------------------------------------------------------------------------


class TestIRBuilderGanglion:
    """Test ganglion component generation in IR."""

    def test_ganglion_component(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="eval_mod",
                layer=Layer.APPLICATION,
                version="1.0.0",
                intent="Evaluator module",
                exports=(),
                location=_loc(1, 3),
            ),
            ganglia=(
                GanglionDecl(
                    name="signal_evaluator",
                    layer=Layer.APPLICATION,
                    visibility=Visibility.INTERNAL,
                    intent="Evaluates signal quality",
                    observes=("validate_*", "process_signal"),
                    scope=EvaluatesAt.SUBSYSTEM,
                    priors="Signals should be valid",
                    on_anomaly="Alert ops team",
                    location=_loc(5, 20),
                ),
            ),
        )
        doc = build_ir(module)
        assert len(doc.components) == 1
        comp = doc.components[0]
        assert comp.canonical_id == "eval_mod::signal_evaluator"
        assert comp.declaration_type == "ganglion"
        assert comp.kind is None
        assert comp.visibility == "INTERNAL"
        assert comp.fields["observes"] == ["validate_*", "process_signal"]
        assert comp.fields["scope"] == "SUBSYSTEM"
        assert comp.fields["priors"] == "Signals should be valid"
        assert comp.fields["on_anomaly"] == "Alert ops team"


# ---------------------------------------------------------------------------
# Test: Determinism (NFR-01)
# ---------------------------------------------------------------------------


class TestIRDeterminism:
    """Verify deterministic output across repeated runs."""

    def test_repeated_build_identical(self) -> None:
        """Building the same module twice produces identical IR."""
        module = _make_full_module()
        derived = [
            DerivedEdge(
                source="validate_envelope",
                target="SignalValidationError",
                target_canonical="errors::SignalValidationError",
                relation=Relation.RAISES,
                origin="raises_field",
            ),
        ]
        builder = IRBuilder(
            source_file="test.s0ma",
            source_text="the source",
        )
        json1 = builder.to_json(module, derived)
        json2 = builder.to_json(module, derived)
        assert json1 == json2

    def test_content_hash_deterministic_across_builds(self) -> None:
        """Content hash is identical across repeated builds."""
        module = _make_full_module()
        source = "module signal_proc\n    layer: APPLICATION\n"
        doc1 = build_ir(module, source_text=source)
        doc2 = build_ir(module, source_text=source)
        assert doc1.module.content_hash == doc2.module.content_hash

    def test_json_output_sorted_keys(self) -> None:
        """JSON output has sorted keys at all levels."""
        module = _make_full_module()
        builder = IRBuilder(source_text="src")
        json_str = builder.to_json(module)
        data = json.loads(json_str)
        # Top-level keys sorted
        assert list(data.keys()) == sorted(data.keys())
        # Module keys sorted
        assert list(data["module"].keys()) == sorted(data["module"].keys())

    def test_edge_ordering_deterministic(self) -> None:
        """Edges are ordered by source then target, not insertion order."""
        module = S0maModule(
            module=ModuleDecl(
                name="m",
                layer=Layer.APPLICATION,
                version="1.0.0",
                intent="test",
                exports=("b_func", "a_func"),
                location=_loc(1, 3),
            ),
            nerves=(
                # Declared second in source but "a" sorts before "b"
                NerveDecl(
                    name="b_func",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Function b",
                    expects="x",
                    guarantees="y",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    depends_on=(
                        InlineAxon(
                            target="a_func",
                            relation=Relation.CALLS,
                            carries="data",
                            coupling=Coupling.TIGHT,
                        ),
                    ),
                    location=_loc(5, 10),
                ),
                NerveDecl(
                    name="a_func",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Function a",
                    expects="x",
                    guarantees="y",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    location=_loc(12, 18),
                ),
            ),
        )
        doc = build_ir(module)
        # Components in source order (b first, then a)
        assert doc.components[0].canonical_id == "m::b_func"
        assert doc.components[1].canonical_id == "m::a_func"
        # Edges sorted by source+target (alphabetically)
        if doc.edges.authored:
            keys = [(e.source, e.target) for e in doc.edges.authored]
            assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Test: JSON serialization round-trip
# ---------------------------------------------------------------------------


class TestIRJsonSerialization:
    """Test JSON serialization produces valid, parseable output."""

    def test_to_json_valid(self) -> None:
        module = _make_full_module()
        builder = IRBuilder(source_text="src")
        json_str = builder.to_json(module)
        data = json.loads(json_str)
        assert isinstance(data, dict)

    def test_json_contains_all_sections(self) -> None:
        module = _make_full_module()
        builder = IRBuilder(source_text="src")
        data = json.loads(builder.to_json(module))
        assert "schema_version" in data
        assert "transpiler_version" in data
        assert "module" in data
        assert "components" in data
        assert "edges" in data
        assert "imports" in data
        assert "exports" in data

    def test_json_edge_categories(self) -> None:
        module = _make_full_module()
        builder = IRBuilder(source_text="src")
        data = json.loads(builder.to_json(module))
        edges = data["edges"]
        assert "authored" in edges
        assert "derived" in edges
        assert "verification" in edges

    def test_json_import_categories(self) -> None:
        module = _make_full_module()
        builder = IRBuilder(source_text="src")
        data = json.loads(builder.to_json(module))
        imports = data["imports"]
        assert "requires" in imports
        assert "uses" in imports
        assert "privileged" in imports

    def test_build_ir_convenience_function(self) -> None:
        """build_ir convenience function produces same result as IRBuilder."""
        module = _make_full_module()
        doc = build_ir(
            module,
            source_file="test.s0ma",
            source_text="src",
        )
        assert isinstance(doc, IRDocument)
        assert doc.module.name == "signal_proc"


# ---------------------------------------------------------------------------
# Test: Golden fixture end-to-end
# ---------------------------------------------------------------------------


class TestIRGoldenFixture:
    """Test IR generation from the golden fixture (signal_processor.s0ma)."""

    @pytest.fixture()
    def golden_ir(self) -> IRDocument:
        """Parse the golden fixture and build its IR."""
        from s0ma_dsl.parser.s0ma_parser import parse_s0ma
        from s0ma_dsl.semantic.derived_edges import analyze_derived_edges

        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source_text = source_path.read_text()
        module = parse_s0ma(source_text, str(source_path))

        derived_edges, errors = analyze_derived_edges(
            module, filename=str(source_path),
        )

        return build_ir(
            module,
            derived_edges=derived_edges,
            source_file=str(source_path),
            source_text=source_text,
            transpiled_file="signal_processor.py",
        )

    def test_golden_module_name(self, golden_ir: IRDocument) -> None:
        assert golden_ir.module.name == "signal_processor"

    def test_golden_module_layer(self, golden_ir: IRDocument) -> None:
        assert golden_ir.module.layer == "APPLICATION"

    def test_golden_module_version(self, golden_ir: IRDocument) -> None:
        assert golden_ir.module.version == "1.0.0"

    def test_golden_content_hash(self, golden_ir: IRDocument) -> None:
        assert golden_ir.module.content_hash.startswith("sha256:")

    def test_golden_exports(self, golden_ir: IRDocument) -> None:
        assert set(golden_ir.exports) == {"process_signal", "SignalEnvelope"}

    def test_golden_component_count(self, golden_ir: IRDocument) -> None:
        """4 components: 2 cells + 2 nerves."""
        assert len(golden_ir.components) == 4

    def test_golden_component_canonical_ids(self, golden_ir: IRDocument) -> None:
        ids = {c.canonical_id for c in golden_ir.components}
        assert ids == {
            "signal_processor::SignalEnvelope",
            "signal_processor::MAX_STALENESS_SECONDS",
            "signal_processor::validate_envelope",
            "signal_processor::process_signal",
        }

    def test_golden_components_in_source_order(self, golden_ir: IRDocument) -> None:
        """Components are in source declaration order."""
        ids = [c.canonical_id for c in golden_ir.components]
        assert ids[0] == "signal_processor::SignalEnvelope"
        assert ids[1] == "signal_processor::MAX_STALENESS_SECONDS"
        assert ids[2] == "signal_processor::validate_envelope"
        assert ids[3] == "signal_processor::process_signal"

    def test_golden_authored_edges(self, golden_ir: IRDocument) -> None:
        """3 authored edges: 2 inline + 1 standalone."""
        authored = golden_ir.edges.authored
        assert len(authored) == 3
        inline = [e for e in authored if e.origin == "inline_depends_on"]
        standalone = [e for e in authored if e.origin == "standalone_axon"]
        assert len(inline) == 2
        assert len(standalone) == 1

    def test_golden_standalone_axon_target(self, golden_ir: IRDocument) -> None:
        standalone = [
            e for e in golden_ir.edges.authored
            if e.origin == "standalone_axon"
        ]
        assert standalone[0].target == "routing::select_evaluator"

    def test_golden_derived_edges(self, golden_ir: IRDocument) -> None:
        """RAISES edges derived from raises fields."""
        derived = golden_ir.edges.derived
        raises_edges = [e for e in derived if e.relation == "RAISES"]
        assert len(raises_edges) >= 1

    def test_golden_derived_edges_canonical(self, golden_ir: IRDocument) -> None:
        """All derived edges use canonical IDs."""
        for edge in golden_ir.edges.derived:
            assert "::" in edge.source, f"Source not canonical: {edge.source}"
            assert "::" in edge.target, f"Target not canonical: {edge.target}"

    def test_golden_requires_imports(self, golden_ir: IRDocument) -> None:
        requires = golden_ir.imports.requires
        paths = [r.module_path for r in requires]
        assert "uuid.UUID" in paths
        assert "time" in paths

    def test_golden_uses_imports(self, golden_ir: IRDocument) -> None:
        uses = golden_ir.imports.uses
        names = [u.qualified_name for u in uses]
        assert "routing.select_evaluator" in names
        assert "errors.SignalValidationError" in names

    def test_golden_uses_resolved_canonical(self, golden_ir: IRDocument) -> None:
        uses = golden_ir.imports.uses
        for u in uses:
            assert "::" in u.resolved_canonical_id

    def test_golden_json_valid(self, golden_ir: IRDocument) -> None:
        """Golden fixture produces valid JSON."""
        IRBuilder(source_text="x")
        # Use to_dict directly to test JSON serialization
        d = golden_ir.to_dict()
        json_str = json.dumps(d, indent=2, sort_keys=True, ensure_ascii=False)
        reparsed = json.loads(json_str)
        assert reparsed["module"]["name"] == "signal_processor"

    def test_golden_ir_self_consistent(self, golden_ir: IRDocument) -> None:
        """All edge references point to declared components or known imports."""
        component_ids = {c.canonical_id for c in golden_ir.components}
        uses_ids = {u.resolved_canonical_id for u in golden_ir.imports.uses}
        known_ids = component_ids | uses_ids

        for edge in golden_ir.edges.authored:
            assert edge.source in known_ids, (
                f"Authored edge source {edge.source} not in known IDs"
            )
            # Target may be cross-module (in uses)
            assert edge.target in known_ids, (
                f"Authored edge target {edge.target} not in known IDs"
            )

        for edge in golden_ir.edges.derived:
            assert edge.source in known_ids, (
                f"Derived edge source {edge.source} not in known IDs"
            )


# ---------------------------------------------------------------------------
# Test: Edge case — aliases
# ---------------------------------------------------------------------------


class TestIRBuilderAliases:
    """Test IR generation with aliased imports."""

    def test_uses_alias_in_ir(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="mod",
                layer=Layer.APPLICATION,
                version="1.0.0",
                intent="test",
                exports=(),
                uses=(
                    UsesEntry(
                        qualified_name="routing.select_evaluator",
                        alias="sel_eval",
                    ),
                ),
                location=_loc(1, 3),
            ),
        )
        doc = build_ir(module)
        uses = doc.imports.uses
        assert len(uses) == 1
        assert uses[0].alias == "sel_eval"
        assert uses[0].resolved_canonical_id == "routing::select_evaluator"

    def test_requires_alias_in_ir(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="mod",
                layer=Layer.APPLICATION,
                version="1.0.0",
                intent="test",
                exports=(),
                requires=(
                    RequiresEntry(module_path="datetime", alias="dt"),
                ),
                location=_loc(1, 3),
            ),
        )
        doc = build_ir(module)
        requires = doc.imports.requires
        assert len(requires) == 1
        assert requires[0].alias == "dt"


# ---------------------------------------------------------------------------
# Test: Empty module
# ---------------------------------------------------------------------------


class TestIRBuilderEmptyModule:
    """Test IR generation for a module with no declarations."""

    def test_empty_module(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="empty",
                layer=Layer.INFRASTRUCTURE,
                version="0.1.0",
                intent="Empty module",
                exports=(),
                location=_loc(1, 3),
            ),
        )
        doc = build_ir(module)
        assert doc.module.name == "empty"
        assert doc.module.layer == "INFRASTRUCTURE"
        assert len(doc.components) == 0
        assert doc.edges.authored == ()
        assert doc.edges.derived == ()
        assert doc.edges.verification == ()


# ===========================================================================
# Provides field in IR
# ===========================================================================


class TestProvidesIR:
    """Test that provides field appears in IR output."""

    def test_provides_in_nerve_ir(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="svc_mod",
                layer=Layer.DOMAIN,
                version="1.0.0",
                intent="Service module",
                exports=("FileSvc",),
                location=_loc(1, 3),
            ),
            nerves=(
                NerveDecl(
                    name="FileSvc",
                    layer=Layer.DOMAIN,
                    kind=Kind.SERVICE,
                    visibility=Visibility.PUBLIC,
                    intent="File service",
                    expects="path exists",
                    guarantees="returns content",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    provides=("read_file", "write_file"),
                    location=_loc(5, 10),
                ),
            ),
        )
        doc = build_ir(module)
        assert len(doc.components) == 1
        comp = doc.components[0]
        assert comp.fields["provides"] == ["read_file", "write_file"]

    def test_provides_absent_not_in_fields(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="mod",
                layer=Layer.DOMAIN,
                version="1.0.0",
                intent="Module",
                exports=("fn",),
                location=_loc(1, 3),
            ),
            nerves=(
                NerveDecl(
                    name="fn",
                    layer=Layer.DOMAIN,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="A function",
                    expects="none",
                    guarantees="none",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    location=_loc(5, 10),
                ),
            ),
        )
        doc = build_ir(module)
        assert "provides" not in doc.components[0].fields


# ===========================================================================
# Soft requires in IR
# ===========================================================================


class TestSoftRequiresIR:
    """Test that soft_requires field appears in IR output."""

    def test_soft_requires_in_ir_imports(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="soft_mod",
                layer=Layer.DOMAIN,
                version="1.0.0",
                intent="Module with soft requires",
                exports=(),
                soft_requires=(
                    RequiresEntry(module_path="anthropic"),
                    RequiresEntry(module_path="prompt_toolkit"),
                ),
                location=_loc(1, 3),
            ),
        )
        doc = build_ir(module)
        assert len(doc.imports.soft_requires) == 2
        assert doc.imports.soft_requires[0].module_path == "anthropic"
        assert doc.imports.soft_requires[1].module_path == "prompt_toolkit"

    def test_soft_requires_in_json(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="soft_mod",
                layer=Layer.DOMAIN,
                version="1.0.0",
                intent="Module with soft requires",
                exports=(),
                soft_requires=(
                    RequiresEntry(module_path="anthropic"),
                ),
                location=_loc(1, 3),
            ),
        )
        doc = build_ir(module)
        d = doc.to_dict()
        assert "soft_requires" in d["imports"]
        assert len(d["imports"]["soft_requires"]) == 1
        assert d["imports"]["soft_requires"][0]["module_path"] == "anthropic"

    def test_soft_requires_empty_by_default(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="mod",
                layer=Layer.DOMAIN,
                version="1.0.0",
                intent="Module",
                exports=(),
                location=_loc(1, 3),
            ),
        )
        doc = build_ir(module)
        assert doc.imports.soft_requires == ()
        assert doc.exports == ()


# ===========================================================================
# MS 11: Abstract, interface, and returns in IR
# ===========================================================================


class TestAbstractFieldsInIR:
    """Verify abstract, interface, and returns fields appear in IR."""

    def test_abstract_nerve_in_ir(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="adapter_mod",
                layer=Layer.INFRASTRUCTURE,
                version="1.0.0",
                intent="Module with abstract nerve",
                exports=("LLMAdapter",),
                location=_loc(1, 3),
            ),
            nerves=(
                NerveDecl(
                    name="LLMAdapter",
                    layer=Layer.INFRASTRUCTURE,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="Abstract LLM adapter",
                    expects="None",
                    guarantees="Subclasses implement methods",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    abstract=True,
                    interface=("chat", "chat_stream"),
                    location=_loc(5, 15),
                ),
            ),
        )
        doc = build_ir(module)
        comp = doc.components[0]
        assert comp.fields["abstract"] is True
        assert comp.fields["interface"] == ["chat", "chat_stream"]

    def test_non_abstract_nerve_no_abstract_in_ir(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="mod",
                layer=Layer.DOMAIN,
                version="1.0.0",
                intent="Module",
                exports=("Func",),
                location=_loc(1, 3),
            ),
            nerves=(
                NerveDecl(
                    name="Func",
                    layer=Layer.DOMAIN,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Regular nerve",
                    expects="None",
                    guarantees="Returns result",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="def Func(): return 42",
                    location=_loc(5, 10),
                ),
            ),
        )
        doc = build_ir(module)
        comp = doc.components[0]
        assert "abstract" not in comp.fields
        assert "interface" not in comp.fields

    def test_returns_in_ir(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="svc_mod",
                layer=Layer.DOMAIN,
                version="1.0.0",
                intent="Module with returns nerve",
                exports=("MySvc",),
                location=_loc(1, 3),
            ),
            nerves=(
                NerveDecl(
                    name="MySvc",
                    layer=Layer.DOMAIN,
                    kind=Kind.SERVICE,
                    visibility=Visibility.PUBLIC,
                    intent="Service with returns",
                    expects="None",
                    guarantees="Returns dict",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    returns=("op_a", "op_b"),
                    body='def MySvc():\n    return {"op_a": 1, "op_b": 2}',
                    location=_loc(5, 15),
                ),
            ),
        )
        doc = build_ir(module)
        comp = doc.components[0]
        assert comp.fields["returns"] == ["op_a", "op_b"]

    def test_empty_returns_not_in_ir(self) -> None:
        module = S0maModule(
            module=ModuleDecl(
                name="mod",
                layer=Layer.DOMAIN,
                version="1.0.0",
                intent="Module",
                exports=("Func",),
                location=_loc(1, 3),
            ),
            nerves=(
                NerveDecl(
                    name="Func",
                    layer=Layer.DOMAIN,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Nerve",
                    expects="None",
                    guarantees="Result",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    returns=(),
                    body="def Func(): return 42",
                    location=_loc(5, 10),
                ),
            ),
        )
        doc = build_ir(module)
        comp = doc.components[0]
        assert "returns" not in comp.fields

    def test_abstract_and_returns_in_json(self) -> None:
        """Verify both fields serialize correctly in to_dict."""
        module = S0maModule(
            module=ModuleDecl(
                name="mod",
                layer=Layer.INFRASTRUCTURE,
                version="1.0.0",
                intent="Module",
                exports=("Adapter",),
                location=_loc(1, 3),
            ),
            nerves=(
                NerveDecl(
                    name="Adapter",
                    layer=Layer.INFRASTRUCTURE,
                    kind=Kind.ADAPTER,
                    visibility=Visibility.PUBLIC,
                    intent="Abstract adapter with returns",
                    expects="None",
                    guarantees="Interface",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    abstract=True,
                    interface=("connect", "disconnect"),
                    returns=("connect", "disconnect"),
                    location=_loc(5, 15),
                ),
            ),
        )
        doc = build_ir(module)
        d = doc.to_dict()
        comp_d = d["components"][0]
        assert comp_d["fields"]["abstract"] is True
        assert comp_d["fields"]["interface"] == ["connect", "disconnect"]
        assert comp_d["fields"]["returns"] == ["connect", "disconnect"]
        # Verify it serializes to valid JSON
        json_str = json.dumps(d, sort_keys=True)
        assert '"abstract": true' in json_str
