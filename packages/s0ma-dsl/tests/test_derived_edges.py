"""Tests for derived edge analysis (Milestone 9).

Covers:
  - 9.1: RAISES edge derivation from raises fields
  - 9.2: TYPE_USES edge derivation from function signature annotations
  - 9.3: Edge deduplication and conflict detection
  - 9.4: Golden fixture derived edges
  - Derivation skips requires names
  - Conflict detection between authored and derived edges
  - Strictness mode severity differences for conflicts
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
    UsesEntry,
)
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.resolver.namespaces import build_namespaces
from s0ma_dsl.semantic.derived_edges import (
    _extract_annotation_names,
    _extract_constructor_type_uses,
    analyze_derived_edges,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _loc(line: int = 1) -> SourceLocation:
    return SourceLocation(
        start_line=line, start_column=0, end_line=line, end_column=0
    )


def _make_module(
    name: str = "test_module",
    layer: Layer = Layer.APPLICATION,
    version: str = "1.0.0",
    exports: tuple[str, ...] = (),
    requires: tuple[RequiresEntry, ...] = (),
    uses: tuple[UsesEntry, ...] = (),
) -> ModuleDecl:
    return ModuleDecl(
        name=name,
        layer=layer,
        version=version,
        intent="Test module for derived edge analysis",
        exports=exports,
        requires=requires,
        uses=uses,
        location=_loc(1),
    )


def _make_nerve(
    name: str,
    line: int = 10,
    layer: Layer = Layer.APPLICATION,
    kind: Kind = Kind.FUNCTION,
    visibility: Visibility = Visibility.INTERNAL,
    raises: tuple[str, ...] = (),
    depends_on: tuple[InlineAxon, ...] = (),
    body: str | None = None,
) -> NerveDecl:
    return NerveDecl(
        name=name,
        layer=layer,
        kind=kind,
        visibility=visibility,
        intent=f"Test nerve {name}",
        expects="None",
        guarantees="None",
        evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
        raises=raises,
        depends_on=depends_on,
        body=body or f"def {name}(): pass",
        location=_loc(line),
    )


def _make_cell(
    name: str,
    line: int = 20,
    layer: Layer = Layer.APPLICATION,
    kind: Kind = Kind.MODEL,
    visibility: Visibility = Visibility.INTERNAL,
) -> CellDecl:
    return CellDecl(
        name=name,
        layer=layer,
        kind=kind,
        visibility=visibility,
        intent=f"Test cell {name}",
        schema=f"{name} schema",
        body=f"class {name}: pass",
        location=_loc(line),
    )


def _make_ganglion(
    name: str,
    line: int = 30,
    layer: Layer = Layer.APPLICATION,
    visibility: Visibility = Visibility.INTERNAL,
    body: str | None = None,
) -> GanglionDecl:
    return GanglionDecl(
        name=name,
        layer=layer,
        visibility=visibility,
        intent=f"Test ganglion {name}",
        observes=("some_nerve",),
        scope=EvaluatesAt.SUBSYSTEM,
        priors="Expected normal signal patterns",
        on_anomaly="Log and escalate",
        body=body or f"def {name}(signals): pass",
        location=_loc(line),
    )


# ===================================================================
# 9.1 — RAISES edge derivation
# ===================================================================


class TestRaisesEdgeDerivation:
    """Tests for deriving RAISES edges from nerve raises fields."""

    def test_raises_edge_from_local_exception(self):
        """A nerve that raises a local exception cell produces a RAISES edge."""
        exc_cell = _make_cell(
            "MyError", kind=Kind.EXCEPTION, line=5,
        )
        nerve = _make_nerve(
            "do_work", raises=("MyError",), line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc_cell,),
        )

        edges, errors = analyze_derived_edges(module)

        assert len(edges) == 1
        edge = edges[0]
        assert edge.source == "do_work"
        assert edge.target == "MyError"
        assert edge.target_canonical == "test_module::MyError"
        assert edge.relation == Relation.RAISES
        assert edge.origin == "raises_field"
        assert edge.source_line == 15
        assert len(errors) == 0

    def test_raises_edge_from_uses_exception(self):
        """A nerve raising an exception from uses produces a RAISES edge."""
        nerve = _make_nerve(
            "do_work", raises=("RemoteError",), line=10,
        )
        module = S0maModule(
            module=_make_module(
                uses=(UsesEntry(
                    qualified_name="errors.RemoteError",
                    location=_loc(3),
                ),),
            ),
            nerves=(nerve,),
        )

        edges, errors = analyze_derived_edges(module)

        assert len(edges) == 1
        edge = edges[0]
        assert edge.source == "do_work"
        assert edge.target == "RemoteError"
        assert edge.target_canonical == "errors::RemoteError"
        assert edge.relation == Relation.RAISES
        assert edge.origin == "raises_field"

    def test_multiple_raises_produce_multiple_edges(self):
        """A nerve raising multiple exceptions produces one edge per exception."""
        exc1 = _make_cell("ErrorA", kind=Kind.EXCEPTION, line=5)
        exc2 = _make_cell("ErrorB", kind=Kind.EXCEPTION, line=8)
        nerve = _make_nerve(
            "risky_work",
            raises=("ErrorA", "ErrorB"),
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc1, exc2),
        )

        edges, errors = analyze_derived_edges(module)

        assert len(edges) == 2
        assert edges[0].target == "ErrorA"
        assert edges[1].target == "ErrorB"
        assert all(e.relation == Relation.RAISES for e in edges)

    def test_raises_skips_unknown_targets(self):
        """Raises entries not in the component-ref namespace are skipped.

        (Already reported by intra-module validator.)
        """
        nerve = _make_nerve(
            "do_work", raises=("UnknownError",), line=10,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
        )

        edges, errors = analyze_derived_edges(module)

        assert len(edges) == 0
        assert len(errors) == 0  # No errors — validator already caught it

    def test_raises_skips_requires_names(self):
        """Raises entries that are requires names are skipped.

        External exceptions must be wrapped in s0ma exception cells.
        The validator already produces INVALID_RAISES_TARGET for these.
        """
        nerve = _make_nerve(
            "do_work", raises=("ValueError",), line=10,
        )
        module = S0maModule(
            module=_make_module(
                requires=(RequiresEntry(
                    module_path="builtins.ValueError",
                    is_from_import=True,
                    location=_loc(3),
                ),),
            ),
            nerves=(nerve,),
        )

        edges, errors = analyze_derived_edges(module)

        # ValueError is in code namespace but NOT in component-ref namespace
        assert len(edges) == 0

    def test_nerve_without_raises_produces_no_edges(self):
        """A nerve with no raises field produces no RAISES edges."""
        nerve = _make_nerve("do_work", line=10)
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
        )

        edges, errors = analyze_derived_edges(module)

        assert len(edges) == 0

    def test_multiple_nerves_with_raises(self):
        """Multiple nerves each raising exceptions produce independent edges."""
        exc = _make_cell("SharedError", kind=Kind.EXCEPTION, line=5)
        nerve1 = _make_nerve("work_a", raises=("SharedError",), line=10)
        nerve2 = _make_nerve("work_b", raises=("SharedError",), line=20)
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve1, nerve2),
            cells=(exc,),
        )

        edges, errors = analyze_derived_edges(module)

        assert len(edges) == 2
        assert edges[0].source == "work_a"
        assert edges[1].source == "work_b"
        assert all(e.target == "SharedError" for e in edges)


# ===================================================================
# 9.2 — TYPE_USES edge derivation
# ===================================================================


class TestTypeUsesEdgeDerivation:
    """Tests for deriving TYPE_USES edges from function signature annotations."""

    def test_type_uses_from_parameter_annotation(self):
        """A nerve using a local cell in parameter type produces TYPE_USES edge."""
        cell = _make_cell("Envelope", line=5)
        nerve = _make_nerve(
            "process",
            body="def process(envelope: Envelope) -> bool:\n    return True",
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(cell,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 1
        assert type_uses[0].source == "process"
        assert type_uses[0].target == "Envelope"
        assert type_uses[0].target_canonical == "test_module::Envelope"
        assert type_uses[0].origin == "function_signature"

    def test_type_uses_from_return_annotation(self):
        """A nerve with a return type annotation referencing a cell produces TYPE_USES."""
        cell = _make_cell("Result", line=5)
        nerve = _make_nerve(
            "compute",
            body="def compute(x: int) -> Result:\n    return Result()",
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(cell,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 1
        assert type_uses[0].target == "Result"

    def test_type_uses_from_multiple_annotations(self):
        """Multiple annotations in one function produce multiple TYPE_USES edges."""
        cell_a = _make_cell("Input", line=5)
        cell_b = _make_cell("Output", line=8)
        nerve = _make_nerve(
            "transform",
            body="def transform(data: Input) -> Output:\n    pass",
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(cell_a, cell_b),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 2
        targets = {e.target for e in type_uses}
        assert targets == {"Input", "Output"}

    def test_type_uses_deduplicates_same_type(self):
        """A type used in both parameter and return annotations produces one edge."""
        cell = _make_cell("Data", line=5)
        nerve = _make_nerve(
            "identity",
            body="def identity(x: Data) -> Data:\n    return x",
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(cell,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 1

    def test_type_uses_skips_builtin_types(self):
        """Builtin types (str, int, bool) don't produce TYPE_USES edges."""
        nerve = _make_nerve(
            "process",
            body="def process(x: str, y: int) -> bool:\n    return True",
            line=10,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
        )

        edges, errors = analyze_derived_edges(module)

        assert len(edges) == 0

    def test_type_uses_skips_requires_types(self):
        """Types from requires (external Python deps) don't produce TYPE_USES edges."""
        nerve = _make_nerve(
            "create_id",
            body="def create_id() -> UUID:\n    return UUID()",
            line=10,
        )
        module = S0maModule(
            module=_make_module(
                requires=(RequiresEntry(
                    module_path="uuid.UUID",
                    is_from_import=True,
                    location=_loc(3),
                ),),
            ),
            nerves=(nerve,),
        )

        edges, errors = analyze_derived_edges(module)

        # UUID is in code namespace but NOT in component-ref namespace
        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 0

    def test_type_uses_from_uses_entries(self):
        """Types from uses entries produce TYPE_USES edges."""
        nerve = _make_nerve(
            "validate",
            body="def validate(e: RemoteType) -> bool:\n    return True",
            line=10,
        )
        module = S0maModule(
            module=_make_module(
                uses=(UsesEntry(
                    qualified_name="models.RemoteType",
                    location=_loc(3),
                ),),
            ),
            nerves=(nerve,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 1
        assert type_uses[0].target == "RemoteType"
        assert type_uses[0].target_canonical == "models::RemoteType"

    def test_type_uses_from_ganglion_body(self):
        """Ganglion function signatures also produce TYPE_USES edges."""
        cell = _make_cell("SignalData", line=5)
        ganglion = _make_ganglion(
            "watcher",
            body="def watcher(signals: SignalData) -> bool:\n    return True",
            line=20,
        )
        module = S0maModule(
            module=_make_module(),
            cells=(cell,),
            ganglia=(ganglion,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 1
        assert type_uses[0].source == "watcher"
        assert type_uses[0].target == "SignalData"

    def test_type_uses_from_generic_annotations(self):
        """Types inside generics like list[Foo] produce TYPE_USES for Foo."""
        cell = _make_cell("Item", line=5)
        nerve = _make_nerve(
            "process_all",
            body="def process_all(items: list[Item]) -> None:\n    pass",
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(cell,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        # Should find Item inside list[Item]
        assert len(type_uses) == 1
        assert type_uses[0].target == "Item"

    def test_type_uses_empty_body_no_edges(self):
        """A nerve with no body produces no TYPE_USES edges."""
        nerve = NerveDecl(
            name="empty",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.INTERNAL,
            intent="Test nerve",
            expects="None",
            guarantees="None",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body=None,
            location=_loc(10),
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
        )

        edges, errors = analyze_derived_edges(module)

        assert len(edges) == 0


# ===================================================================
# 9.1.5 — TYPE_USES from constructor calls (MS 9 Task 9.1)
# ===================================================================


class TestTypeUsesFromConstructorCalls:
    """Tests for deriving TYPE_USES edges from constructor calls in bodies."""

    def test_constructor_call_derives_type_uses(self):
        """ToolParameter(...) in body derives TYPE_USES → ToolParameter."""
        cell = _make_cell("ToolParameter", kind=Kind.MODEL, line=5)
        nerve = _make_nerve(
            "build_tool",
            body=(
                "def build_tool():\n"
                "    param = ToolParameter(name='file', required=True)\n"
                "    return param"
            ),
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(cell,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 1
        assert type_uses[0].source == "build_tool"
        assert type_uses[0].target == "ToolParameter"
        assert type_uses[0].target_canonical == "test_module::ToolParameter"
        assert type_uses[0].origin == "constructor_call"

    def test_constructor_call_non_cell_no_edge(self):
        """SomeClass() where SomeClass is NOT a cell produces no edge."""
        nerve = _make_nerve(
            "build_thing",
            body="def build_thing():\n    x = SomeClass()\n    return x",
            line=10,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 0

    def test_constructor_call_exception_cell(self):
        """Constructing an EXCEPTION cell derives TYPE_USES."""
        exc = _make_cell("MyError", kind=Kind.EXCEPTION, line=5)
        nerve = _make_nerve(
            "fail",
            body="def fail():\n    raise MyError('boom')",
            raises=("MyError",),
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 1
        assert type_uses[0].target == "MyError"
        assert type_uses[0].origin == "constructor_call"

    def test_constructor_deduplicates_with_annotation(self):
        """If a cell appears in both annotation and constructor, one edge is produced."""
        cell = _make_cell("Envelope", line=5)
        nerve = _make_nerve(
            "process",
            body=(
                "def process(env: Envelope) -> bool:\n"
                "    copy = Envelope(data=env.data)\n"
                "    return True"
            ),
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(cell,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 1
        assert type_uses[0].target == "Envelope"
        # Annotation takes precedence for origin when both are present
        assert type_uses[0].origin == "function_signature"

    def test_constructor_call_via_uses(self):
        """Constructor call matching a uses entry derives TYPE_USES."""
        nerve = _make_nerve(
            "create",
            body="def create():\n    return RemoteModel(key='abc')",
            line=10,
        )
        module = S0maModule(
            module=_make_module(
                uses=(UsesEntry(
                    qualified_name="models.RemoteModel",
                    location=_loc(3),
                ),),
            ),
            nerves=(nerve,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 1
        assert type_uses[0].target == "RemoteModel"
        assert type_uses[0].target_canonical == "models::RemoteModel"

    def test_constant_cell_not_matched(self):
        """CONSTANT cells are not constructable — calls to their name are ignored."""
        cell = CellDecl(
            name="MAX_SIZE",
            layer=Layer.APPLICATION,
            kind=Kind.CONSTANT,
            visibility=Visibility.INTERNAL,
            intent="Max size constant",
            schema="int",
            body="MAX_SIZE = 100",
            location=_loc(5),
        )
        nerve = _make_nerve(
            "check",
            body="def check():\n    x = MAX_SIZE()\n    return x",
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(cell,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 0

    def test_multiple_constructor_calls(self):
        """Multiple distinct constructors produce one edge per type."""
        cell_a = _make_cell("TypeA", kind=Kind.MODEL, line=5)
        cell_b = _make_cell("TypeB", kind=Kind.ENUM, line=8)
        nerve = _make_nerve(
            "build",
            body=(
                "def build():\n"
                "    a = TypeA()\n"
                "    b = TypeB()\n"
                "    return a, b"
            ),
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(cell_a, cell_b),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 2
        targets = {e.target for e in type_uses}
        assert targets == {"TypeA", "TypeB"}

    def test_ganglion_constructor_call(self):
        """Constructor calls in ganglion bodies also derive TYPE_USES."""
        cell = _make_cell("MetricData", kind=Kind.MODEL, line=5)
        ganglion = _make_ganglion(
            "monitor",
            body=(
                "def monitor(signals):\n"
                "    data = MetricData(value=signals)\n"
                "    return data"
            ),
            line=20,
        )
        module = S0maModule(
            module=_make_module(),
            cells=(cell,),
            ganglia=(ganglion,),
        )

        edges, errors = analyze_derived_edges(module)

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]
        assert len(type_uses) == 1
        assert type_uses[0].source == "monitor"
        assert type_uses[0].target == "MetricData"


# ===================================================================
# 9.1.6 — _extract_constructor_type_uses helper
# ===================================================================


class TestExtractConstructorTypeUses:
    """Tests for the constructor call extraction helper."""

    def test_simple_call(self):
        names = _extract_constructor_type_uses(
            "x = Foo(bar=1)", {"Foo", "Baz"},
        )
        assert names == {"Foo"}

    def test_no_match(self):
        names = _extract_constructor_type_uses(
            "x = Unknown()", {"Foo"},
        )
        assert names == set()

    def test_attribute_call(self):
        names = _extract_constructor_type_uses(
            "x = mod.Foo()", {"Foo"},
        )
        assert names == {"Foo"}

    def test_empty_body(self):
        names = _extract_constructor_type_uses("", {"Foo"})
        assert names == set()

    def test_syntax_error(self):
        names = _extract_constructor_type_uses("{{invalid}}", {"Foo"})
        assert names == set()


# ===================================================================
# 9.2 (continued) — _extract_annotation_names helper
# ===================================================================


class TestExtractAnnotationNames:
    """Tests for the annotation name extraction helper."""

    def test_simple_parameter_type(self):
        names = _extract_annotation_names("def f(x: int): pass")
        assert "int" in names

    def test_return_type(self):
        names = _extract_annotation_names("def f() -> str: pass")
        assert "str" in names

    def test_multiple_params(self):
        names = _extract_annotation_names("def f(a: Foo, b: Bar) -> Baz: pass")
        assert names == {"Foo", "Bar", "Baz"}

    def test_generic_extracts_inner(self):
        names = _extract_annotation_names("def f(x: list[Foo]) -> dict[str, Bar]: pass")
        assert "Foo" in names
        assert "Bar" in names

    def test_optional_extracts_inner(self):
        names = _extract_annotation_names("def f(x: Foo | None) -> None: pass")
        assert "Foo" in names

    def test_no_annotations(self):
        names = _extract_annotation_names("def f(x, y): pass")
        assert len(names) == 0

    def test_empty_body(self):
        names = _extract_annotation_names("")
        assert len(names) == 0

    def test_syntax_error_body(self):
        names = _extract_annotation_names("this is not valid python {{{}}")
        assert len(names) == 0

    def test_class_body_no_annotations(self):
        """Class bodies are ignored — TYPE_USES only comes from function sigs."""
        names = _extract_annotation_names("class Foo:\n    x: int = 5")
        assert len(names) == 0

    def test_async_function(self):
        names = _extract_annotation_names("async def f(x: Foo) -> Bar: pass")
        assert names == {"Foo", "Bar"}

    def test_kwargs_annotation(self):
        names = _extract_annotation_names("def f(**kwargs: Mapping) -> None: pass")
        assert "Mapping" in names

    def test_varargs_annotation(self):
        names = _extract_annotation_names("def f(*args: Sequence) -> None: pass")
        assert "Sequence" in names


# ===================================================================
# 9.3 — Edge conflict detection (authored vs. derived)
# ===================================================================


class TestEdgeConflictDetection:
    """Tests for detecting conflicts between authored and derived edges."""

    def test_inline_depends_on_overlaps_with_raises(self):
        """An inline depends_on targeting the same exception as a raises edge → conflict."""
        exc = _make_cell("MyError", kind=Kind.EXCEPTION, line=5)
        nerve = _make_nerve(
            "do_work",
            raises=("MyError",),
            depends_on=(InlineAxon(
                target="MyError",
                relation=Relation.READS,
                carries="error type",
                coupling=Coupling.TIGHT,
                location=_loc(12),
            ),),
            line=10,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc,),
        )

        edges, errors = analyze_derived_edges(module)

        # Should produce a DUPLICATE_AXON warning/error
        conflict_errors = [e for e in errors if e.code == "DUPLICATE_AXON"]
        assert len(conflict_errors) == 1
        assert "overlaps with derived RAISES" in conflict_errors[0].message

    def test_inline_depends_on_overlaps_with_type_uses(self):
        """An inline depends_on targeting a type annotation → conflict."""
        cell = _make_cell("Envelope", line=5)
        nerve = _make_nerve(
            "process",
            body="def process(e: Envelope) -> bool:\n    return True",
            depends_on=(InlineAxon(
                target="Envelope",
                relation=Relation.CONSTRUCTS,
                carries="data type",
                coupling=Coupling.TIGHT,
                location=_loc(12),
            ),),
            line=10,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(cell,),
        )

        edges, errors = analyze_derived_edges(module)

        conflict_errors = [e for e in errors if e.code == "DUPLICATE_AXON"]
        assert len(conflict_errors) == 1
        assert "overlaps with derived TYPE_USES" in conflict_errors[0].message

    def test_standalone_axon_overlaps_with_derived(self):
        """A standalone axon targeting the same as a derived edge → conflict."""
        exc = _make_cell("MyError", kind=Kind.EXCEPTION, line=5)
        nerve = _make_nerve(
            "do_work",
            raises=("MyError",),
            line=10,
        )
        axon = StandaloneAxonDecl(
            source="do_work",
            target="MyError",
            relation=Relation.READS,
            intent="test",
            carries="error",
            coupling=Coupling.TIGHT,
            location=_loc(25),
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc,),
            axons=(axon,),
        )

        edges, errors = analyze_derived_edges(module)

        conflict_errors = [e for e in errors if e.code == "DUPLICATE_AXON"]
        assert len(conflict_errors) == 1

    def test_no_conflict_when_no_overlap(self):
        """Authored edges to different targets don't conflict with derived edges."""
        exc = _make_cell("MyError", kind=Kind.EXCEPTION, line=5)
        other = _make_cell("Config", kind=Kind.CONFIG, line=8)
        nerve = _make_nerve(
            "do_work",
            raises=("MyError",),
            depends_on=(InlineAxon(
                target="Config",
                relation=Relation.READS,
                carries="config data",
                coupling=Coupling.LOOSE,
                location=_loc(12),
            ),),
            line=10,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc, other),
        )

        edges, errors = analyze_derived_edges(module)

        assert len(errors) == 0
        # Should have 1 RAISES edge from raises field
        raises_edges = [e for e in edges if e.relation == Relation.RAISES]
        assert len(raises_edges) == 1

    def test_conflict_severity_warning_in_dev(self):
        """Conflict is a warning in DEV mode."""
        exc = _make_cell("MyError", kind=Kind.EXCEPTION, line=5)
        nerve = _make_nerve(
            "do_work",
            raises=("MyError",),
            depends_on=(InlineAxon(
                target="MyError",
                relation=Relation.READS,
                carries="error",
                coupling=Coupling.TIGHT,
            ),),
            line=10,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc,),
        )

        edges, errors = analyze_derived_edges(
            module, mode=StrictnessMode.DEV,
        )

        conflict_errors = [e for e in errors if e.code == "DUPLICATE_AXON"]
        assert len(conflict_errors) == 1
        assert conflict_errors[0].severity == "warning"

    def test_conflict_severity_error_in_strict(self):
        """Conflict is an error in STRICT mode."""
        exc = _make_cell("MyError", kind=Kind.EXCEPTION, line=5)
        nerve = _make_nerve(
            "do_work",
            raises=("MyError",),
            depends_on=(InlineAxon(
                target="MyError",
                relation=Relation.READS,
                carries="error",
                coupling=Coupling.TIGHT,
            ),),
            line=10,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc,),
        )

        edges, errors = analyze_derived_edges(
            module, mode=StrictnessMode.STRICT,
        )

        conflict_errors = [e for e in errors if e.code == "DUPLICATE_AXON"]
        assert len(conflict_errors) == 1
        assert conflict_errors[0].severity == "error"


# ===================================================================
# 9.4 — Golden fixture derived edge analysis
# ===================================================================


class TestGoldenFixtureDerivedEdges:
    """Tests using the signal_processor.s0ma golden fixture."""

    @pytest.fixture()
    def golden_module(self) -> S0maModule:
        """Construct the signal_processor golden module programmatically."""
        from s0ma_dsl.parser import S0maParser

        golden_path = (
            __import__("pathlib").Path(__file__).parent
            / "fixtures"
            / "valid"
            / "signal_processor.s0ma"
        )
        parser = S0maParser()
        return parser.parse(golden_path.read_text(), filename=str(golden_path))

    def test_golden_raises_edges(self, golden_module: S0maModule):
        """Golden fixture produces correct RAISES edges."""
        edges, errors = analyze_derived_edges(
            golden_module, filename="signal_processor.s0ma",
        )

        raises_edges = [e for e in edges if e.relation == Relation.RAISES]

        # validate_envelope raises SignalValidationError
        ve_edges = [e for e in raises_edges if e.source == "validate_envelope"]
        assert len(ve_edges) == 1
        assert ve_edges[0].target == "SignalValidationError"
        assert ve_edges[0].origin == "raises_field"

        # process_signal raises SignalValidationError
        ps_edges = [e for e in raises_edges if e.source == "process_signal"]
        assert len(ps_edges) == 1
        assert ps_edges[0].target == "SignalValidationError"
        assert ps_edges[0].origin == "raises_field"

    def test_golden_type_uses_edges(self, golden_module: S0maModule):
        """Golden fixture produces correct TYPE_USES edges.

        Both validate_envelope and process_signal use SignalEnvelope
        in their function signatures.
        """
        edges, errors = analyze_derived_edges(
            golden_module, filename="signal_processor.s0ma",
        )

        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]

        # validate_envelope(envelope: SignalEnvelope) -> bool
        ve_edges = [e for e in type_uses if e.source == "validate_envelope"]
        ve_targets = {e.target for e in ve_edges}
        assert "SignalEnvelope" in ve_targets

        # process_signal(envelope: SignalEnvelope) -> bool
        ps_edges = [e for e in type_uses if e.source == "process_signal"]
        ps_targets = {e.target for e in ps_edges}
        assert "SignalEnvelope" in ps_targets

    def test_golden_no_errors(self, golden_module: S0maModule):
        """Golden fixture produces no errors from derived edge analysis."""
        edges, errors = analyze_derived_edges(
            golden_module, filename="signal_processor.s0ma",
        )

        # The golden fixture has inline depends_on on validate_envelope
        # targeting MAX_STALENESS_SECONDS (READS), which is NOT the same
        # target as any derived edge, so no conflicts expected.
        semantic_errors = [e for e in errors if e.severity == "error"]
        assert len(semantic_errors) == 0

    def test_golden_edges_have_correct_canonical_ids(self, golden_module: S0maModule):
        """All derived edges have correctly-formed canonical IDs."""
        edges, errors = analyze_derived_edges(
            golden_module, filename="signal_processor.s0ma",
        )

        for edge in edges:
            assert "::" in edge.target_canonical, (
                f"Edge {edge.source} → {edge.target} has invalid "
                f"canonical ID: {edge.target_canonical}"
            )


# ===================================================================
# Combined RAISES + TYPE_USES tests
# ===================================================================


class TestCombinedDerivedEdges:
    """Tests for modules producing both RAISES and TYPE_USES edges."""

    def test_nerve_with_raises_and_typed_signature(self):
        """A nerve with both raises and typed params produces both edge types."""
        exc = _make_cell("MyError", kind=Kind.EXCEPTION, line=5)
        model = _make_cell("MyModel", line=8)
        nerve = _make_nerve(
            "process",
            raises=("MyError",),
            body="def process(data: MyModel) -> bool:\n    return True",
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc, model),
        )

        edges, errors = analyze_derived_edges(module)

        raises_edges = [e for e in edges if e.relation == Relation.RAISES]
        type_uses = [e for e in edges if e.relation == Relation.TYPE_USES]

        assert len(raises_edges) == 1
        assert raises_edges[0].target == "MyError"

        assert len(type_uses) == 1
        assert type_uses[0].target == "MyModel"

    def test_deterministic_edge_ordering(self):
        """Derived edges are produced in deterministic order."""
        exc = _make_cell("ZError", kind=Kind.EXCEPTION, line=5)
        model = _make_cell("AModel", line=8)
        nerve = _make_nerve(
            "work",
            raises=("ZError",),
            body="def work(m: AModel) -> bool:\n    return True",
            line=15,
        )
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc, model),
        )

        # Run analysis multiple times to verify determinism
        results = []
        for _ in range(5):
            edges, _ = analyze_derived_edges(module)
            results.append([(e.source, e.target, e.relation.value) for e in edges])

        # All runs should produce identical results
        assert all(r == results[0] for r in results)


# ===================================================================
# Convenience function tests
# ===================================================================


class TestAnalyzeDerivedEdgesConvenience:
    """Tests for the analyze_derived_edges convenience function."""

    def test_accepts_pre_built_namespace(self):
        """The convenience function accepts a pre-built NamespaceService."""
        exc = _make_cell("Err", kind=Kind.EXCEPTION, line=5)
        nerve = _make_nerve("do_it", raises=("Err",), line=10)
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc,),
        )

        ns, _ = build_namespaces(module, "<test>")
        edges, errors = analyze_derived_edges(module, ns=ns)

        assert len(edges) == 1
        assert edges[0].relation == Relation.RAISES

    def test_builds_namespace_if_not_provided(self):
        """The convenience function builds a namespace if none is provided."""
        exc = _make_cell("Err", kind=Kind.EXCEPTION, line=5)
        nerve = _make_nerve("do_it", raises=("Err",), line=10)
        module = S0maModule(
            module=_make_module(),
            nerves=(nerve,),
            cells=(exc,),
        )

        edges, errors = analyze_derived_edges(module)

        assert len(edges) == 1
