"""Source map tests for the s0ma DSL transpiler (Milestone 13).

Tests source map generation linking .s0ma source line numbers to
generated .py output line numbers.  Verifies declaration mapping,
body mapping, decorator mapping, module header mapping, determinism,
and JSON serialization.

PRD references: FR-24, §2.6 (source map requirements)
ADR reference: ADR-003 (custom .s0ma.map format)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

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
    HelperDecl,
    ModuleDecl,
    NerveDecl,
    RequiresEntry,
    S0maModule,
    SourceLocation,
    StandaloneAxonDecl,
    TestDecl,
    UsesEntry,
)
from s0ma_dsl.codegen.python_emitter import emit_python
from s0ma_dsl.codegen.source_map import (
    SOURCE_MAP_VERSION,
    SOURCE_POINTER_PREFIX,
    DeclarationMapping,
    LineRange,
    ModuleHeaderMapping,
    ResolvedLocation,
    SourceMap,
    SourceMapGenerator,
    annotate_source_pointers,
    generate_source_map,
    load_source_map,
    resolve_output_line,
)
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from tests.conftest import VALID_FIXTURES_DIR

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _loc(start: int = 1, end: int = 5) -> SourceLocation:
    return SourceLocation(
        start_line=start, start_column=0, end_line=end, end_column=0
    )


def _minimal_module(
    name: str = "test_mod",
    layer: Layer = Layer.APPLICATION,
    exports: tuple[str, ...] = (),
    requires: tuple[RequiresEntry, ...] = (),
    uses: tuple[UsesEntry, ...] = (),
) -> ModuleDecl:
    return ModuleDecl(
        name=name,
        layer=layer,
        version="1.0.0",
        intent="Test module for source maps",
        exports=exports,
        requires=requires,
        uses=uses,
        location=_loc(1, 3),
    )


def _emit_and_map(
    module: S0maModule,
    source_file: str = "test.s0ma",
    output_file: str = "test.py",
) -> tuple[str, SourceMap]:
    """Emit Python and generate source map in one step."""
    output = emit_python(module)
    source_map = generate_source_map(module, output, source_file, output_file)
    return output, source_map


# ---------------------------------------------------------------------------
# Data type tests
# ---------------------------------------------------------------------------


class TestLineRange:
    def test_construction(self):
        lr = LineRange(start_line=1, end_line=5)
        assert lr.start_line == 1
        assert lr.end_line == 5

    def test_to_dict(self):
        lr = LineRange(start_line=10, end_line=20)
        assert lr.to_dict() == {"start_line": 10, "end_line": 20}

    def test_frozen(self):
        lr = LineRange(start_line=1, end_line=1)
        with pytest.raises(AttributeError):
            lr.start_line = 2  # type: ignore[misc]


class TestDeclarationMapping:
    def test_minimal_to_dict(self):
        dm = DeclarationMapping(
            name="foo",
            type="nerve",
            source=LineRange(1, 10),
            output=LineRange(5, 15),
        )
        d = dm.to_dict()
        assert d["name"] == "foo"
        assert d["type"] == "nerve"
        assert "body_source" not in d
        assert "body_output" not in d
        assert "decorator_output" not in d

    def test_full_to_dict(self):
        dm = DeclarationMapping(
            name="bar",
            type="cell",
            source=LineRange(10, 20),
            output=LineRange(30, 40),
            body_source=LineRange(15, 20),
            body_output=LineRange(35, 40),
            decorator_output=LineRange(30, 34),
        )
        d = dm.to_dict()
        assert d["body_source"] == {"start_line": 15, "end_line": 20}
        assert d["body_output"] == {"start_line": 35, "end_line": 40}
        assert d["decorator_output"] == {"start_line": 30, "end_line": 34}


class TestModuleHeaderMapping:
    def test_to_dict(self):
        mhm = ModuleHeaderMapping(
            source=LineRange(1, 8),
            output_header=LineRange(1, 5),
            output_imports=LineRange(7, 12),
            output_all=LineRange(14, 14),
            output_registration=LineRange(16, 22),
        )
        d = mhm.to_dict()
        assert d["source"] == {"start_line": 1, "end_line": 8}
        assert d["output_header"] == {"start_line": 1, "end_line": 5}
        assert d["output_all"] == {"start_line": 14, "end_line": 14}


class TestSourceMap:
    def test_to_dict_structure(self):
        sm = SourceMap(
            version="1.0.0",
            source_file="test.s0ma",
            output_file="test.py",
            declarations=(),
            module_header=ModuleHeaderMapping(
                source=LineRange(1, 3),
                output_header=LineRange(1, 5),
                output_imports=LineRange(7, 10),
                output_all=LineRange(12, 12),
                output_registration=LineRange(14, 18),
            ),
        )
        d = sm.to_dict()
        assert d["version"] == "1.0.0"
        assert d["source_file"] == "test.s0ma"
        assert d["output_file"] == "test.py"
        assert "mappings" in d
        assert "declarations" in d["mappings"]
        assert "module_header" in d["mappings"]

    def test_to_json_valid(self):
        sm = SourceMap(
            version="1.0.0",
            source_file="test.s0ma",
            output_file="test.py",
            declarations=(),
            module_header=ModuleHeaderMapping(
                source=LineRange(1, 3),
                output_header=LineRange(1, 5),
                output_imports=LineRange(7, 10),
                output_all=LineRange(12, 12),
                output_registration=LineRange(14, 18),
            ),
        )
        j = sm.to_json()
        parsed = json.loads(j)
        assert parsed["version"] == "1.0.0"

    def test_to_json_sorted_keys(self):
        sm = SourceMap(
            version="1.0.0",
            source_file="test.s0ma",
            output_file="test.py",
            declarations=(),
            module_header=ModuleHeaderMapping(
                source=LineRange(1, 3),
                output_header=LineRange(1, 5),
                output_imports=LineRange(7, 10),
                output_all=LineRange(12, 12),
                output_registration=LineRange(14, 18),
            ),
        )
        j = sm.to_json()
        parsed = json.loads(j)
        # Top-level keys should be sorted
        keys = list(parsed.keys())
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Source map generator: minimal module (no declarations)
# ---------------------------------------------------------------------------


class TestMinimalModule:
    def test_empty_declarations(self):
        """Module with no declarations produces empty declarations list."""
        mod = S0maModule(module=_minimal_module())
        _, source_map = _emit_and_map(mod)
        assert source_map.declarations == ()

    def test_module_header_present(self):
        """Module header mapping is always present."""
        mod = S0maModule(module=_minimal_module())
        _, source_map = _emit_and_map(mod)
        mh = source_map.module_header
        assert mh.output_header.start_line == 1
        assert mh.output_header.end_line >= 4  # docstring is at least 4 lines

    def test_module_source_range(self):
        """Module source range comes from AST SourceLocation."""
        mod = S0maModule(module=_minimal_module())
        _, source_map = _emit_and_map(mod)
        assert source_map.module_header.source.start_line == 1
        assert source_map.module_header.source.end_line == 3

    def test_imports_between_header_and_all(self):
        """Import region is between header and __all__."""
        mod = S0maModule(module=_minimal_module())
        _, source_map = _emit_and_map(mod)
        mh = source_map.module_header
        assert mh.output_imports.start_line > mh.output_header.end_line
        assert mh.output_imports.end_line < mh.output_all.start_line

    def test_registration_after_all(self):
        """register_module() is after __all__."""
        mod = S0maModule(module=_minimal_module())
        _, source_map = _emit_and_map(mod)
        mh = source_map.module_header
        assert mh.output_registration.start_line > mh.output_all.end_line


# ---------------------------------------------------------------------------
# Source map generator: nerve declarations
# ---------------------------------------------------------------------------


class TestNerveMapping:
    def _make_nerve_module(self) -> S0maModule:
        return S0maModule(
            module=_minimal_module(exports=("my_func",)),
            nerves=(
                NerveDecl(
                    name="my_func",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="A test function",
                    expects="valid input",
                    guarantees="valid output",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="    def my_func(x: int) -> int:\n        return x + 1",
                    location=_loc(5, 15),
                ),
            ),
        )

    def test_nerve_mapping_present(self):
        mod = self._make_nerve_module()
        _, source_map = _emit_and_map(mod)
        assert len(source_map.declarations) == 1
        dm = source_map.declarations[0]
        assert dm.name == "my_func"
        assert dm.type == "nerve"

    def test_nerve_source_range(self):
        mod = self._make_nerve_module()
        _, source_map = _emit_and_map(mod)
        dm = source_map.declarations[0]
        assert dm.source.start_line == 5
        assert dm.source.end_line == 15

    def test_nerve_has_decorator(self):
        mod = self._make_nerve_module()
        _, source_map = _emit_and_map(mod)
        dm = source_map.declarations[0]
        assert dm.decorator_output is not None
        assert dm.decorator_output.start_line <= dm.body_output.start_line

    def test_nerve_has_body(self):
        mod = self._make_nerve_module()
        _, source_map = _emit_and_map(mod)
        dm = source_map.declarations[0]
        assert dm.body_output is not None
        assert dm.body_output.start_line > dm.decorator_output.end_line

    def test_nerve_body_source_estimated(self):
        """Body source range is estimated from body text and declaration end."""
        mod = self._make_nerve_module()
        _, source_map = _emit_and_map(mod)
        dm = source_map.declarations[0]
        assert dm.body_source is not None
        assert dm.body_source.end_line == 15  # matches declaration end

    def test_nerve_output_within_file(self):
        """Output ranges fall within the output file."""
        mod = self._make_nerve_module()
        output, source_map = _emit_and_map(mod)
        total_lines = len(output.split("\n"))
        dm = source_map.declarations[0]
        assert dm.output.start_line >= 1
        assert dm.output.end_line <= total_lines


# ---------------------------------------------------------------------------
# Source map generator: cell declarations
# ---------------------------------------------------------------------------


class TestCellMapping:
    def _make_class_cell_module(self) -> S0maModule:
        return S0maModule(
            module=_minimal_module(exports=("MyModel",)),
            cells=(
                CellDecl(
                    name="MyModel",
                    layer=Layer.APPLICATION,
                    kind=Kind.MODEL,
                    visibility=Visibility.PUBLIC,
                    intent="A data model",
                    schema="Dataclass with name: str",
                    body="    class MyModel:\n        name: str = ''",
                    location=_loc(5, 12),
                ),
            ),
        )

    def _make_constant_cell_module(self) -> S0maModule:
        return S0maModule(
            module=_minimal_module(),
            cells=(
                CellDecl(
                    name="MAX_COUNT",
                    layer=Layer.APPLICATION,
                    kind=Kind.CONSTANT,
                    visibility=Visibility.INTERNAL,
                    intent="Maximum item count",
                    schema="int constant",
                    body="    MAX_COUNT: int = 100",
                    location=_loc(5, 10),
                ),
            ),
        )

    def test_class_cell_has_decorator(self):
        """Class cells (@component-decorated) have decorator_output."""
        mod = self._make_class_cell_module()
        _, source_map = _emit_and_map(mod)
        dm = source_map.declarations[0]
        assert dm.type == "cell"
        assert dm.decorator_output is not None

    def test_class_cell_has_body(self):
        mod = self._make_class_cell_module()
        _, source_map = _emit_and_map(mod)
        dm = source_map.declarations[0]
        assert dm.body_output is not None

    def test_constant_cell_no_decorator(self):
        """Constant cells (register_constant) have no decorator_output."""
        mod = self._make_constant_cell_module()
        _, source_map = _emit_and_map(mod)
        dm = source_map.declarations[0]
        assert dm.type == "cell"
        assert dm.decorator_output is None

    def test_constant_cell_has_body(self):
        mod = self._make_constant_cell_module()
        _, source_map = _emit_and_map(mod)
        dm = source_map.declarations[0]
        assert dm.body_output is not None


# ---------------------------------------------------------------------------
# Source map generator: helper declarations (F-M0-2, DSL-M3)
# ---------------------------------------------------------------------------


class TestHelperMapping:
    """Helpers now carry ``body_output`` like every other body-kind (F-M0-2).

    Before DSL-M3 a ``helper`` was the only declaration kind whose
    ``.s0ma.map`` entry recorded just the whole-declaration ``output``
    range — no ``body_output`` — so tooling that wanted "which emitted
    lines are authored" had to special-case helpers. The
    ``HelperDecl`` arm in ``_build_mapping`` closes that asymmetry.
    """

    def _make_helper_module(self) -> S0maModule:
        return S0maModule(
            module=_minimal_module(exports=("greet",)),
            helpers=(
                HelperDecl(
                    name="_shout",
                    layer=Layer.APPLICATION,
                    intent="Uppercase a string for emphasis",
                    body=(
                        "def _shout(text: str) -> str:\n"
                        "    return text.upper()"
                    ),
                    location=_loc(5, 8),
                ),
            ),
            nerves=(
                NerveDecl(
                    name="greet",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Greet by name",
                    expects="name is a string",
                    guarantees="returns a greeting",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body='def greet(name: str) -> str:\n    return _shout("hi ") + name',
                    location=_loc(10, 12),
                ),
            ),
        )

    def _helper_mapping(self) -> tuple[str, DeclarationMapping]:
        mod = self._make_helper_module()
        output, source_map = _emit_and_map(mod)
        (dm,) = [d for d in source_map.declarations if d.type == "helper"]
        return output, dm

    def test_helper_has_body_output(self) -> None:
        _, dm = self._helper_mapping()
        assert dm.body_output is not None, (
            "helper declarations must carry a body_output range (F-M0-2)"
        )

    def test_helper_body_output_skips_comment_anchor(self) -> None:
        """``body_output`` is ``output.start_line + 1 .. output.end_line``.

        The emitter prefixes a helper with a single ``# Helper: <intent>``
        comment anchor; the authored body is everything after it.
        """
        _, dm = self._helper_mapping()
        assert dm.body_output is not None
        # Exactly one line (the comment anchor) is skipped at the top.
        assert dm.body_output.start_line == dm.output.start_line + 1
        # The body runs to the declaration's end.
        assert dm.body_output.end_line == dm.output.end_line

    def test_helper_body_output_points_at_the_def(self) -> None:
        """The first ``body_output`` line is the emitted ``def`` line."""
        output, dm = self._helper_mapping()
        assert dm.body_output is not None
        lines = output.split("\n")
        # 1-based line number → 0-based index.
        first_body_line = lines[dm.body_output.start_line - 1]
        assert first_body_line.startswith("def _shout("), first_body_line
        # And the line just above it is the comment anchor.
        anchor_line = lines[dm.output.start_line - 1]
        assert anchor_line.startswith("# Helper:"), anchor_line


# ---------------------------------------------------------------------------
# Source map generator: standalone axon declarations
# ---------------------------------------------------------------------------


class TestAxonMapping:
    def _make_axon_module(self) -> S0maModule:
        return S0maModule(
            module=_minimal_module(
                exports=("do_stuff",),
                uses=(UsesEntry(qualified_name="other.helper"),),
            ),
            nerves=(
                NerveDecl(
                    name="do_stuff",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Does stuff",
                    expects="input",
                    guarantees="output",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="    def do_stuff():\n        return helper()",
                    location=_loc(5, 14),
                ),
            ),
            axons=(
                StandaloneAxonDecl(
                    source="do_stuff",
                    target="helper",
                    relation=Relation.CALLS,
                    intent="Calls helper in other module",
                    carries="request data",
                    coupling=Coupling.LOOSE,
                    location=_loc(16, 22),
                ),
            ),
        )

    def test_axon_mapping_present(self):
        mod = self._make_axon_module()
        _, source_map = _emit_and_map(mod)
        axon_mappings = [d for d in source_map.declarations if d.type == "axon"]
        assert len(axon_mappings) == 1

    def test_axon_name(self):
        mod = self._make_axon_module()
        _, source_map = _emit_and_map(mod)
        axon_mappings = [d for d in source_map.declarations if d.type == "axon"]
        assert axon_mappings[0].name == "do_stuff -> helper"

    def test_axon_no_body_no_decorator(self):
        """Standalone axons have no body or decorator."""
        mod = self._make_axon_module()
        _, source_map = _emit_and_map(mod)
        axon_mappings = [d for d in source_map.declarations if d.type == "axon"]
        dm = axon_mappings[0]
        assert dm.body_source is None
        assert dm.body_output is None
        assert dm.decorator_output is None


# ---------------------------------------------------------------------------
# Source map generator: test declarations
# ---------------------------------------------------------------------------


class TestTestDeclMapping:
    def _make_test_module(self) -> S0maModule:
        return S0maModule(
            module=_minimal_module(),
            nerves=(
                NerveDecl(
                    name="my_func",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.INTERNAL,
                    intent="A function",
                    expects="input",
                    guarantees="output",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="    def my_func():\n        return 1",
                    location=_loc(5, 10),
                ),
            ),
            tests=(
                TestDecl(
                    name="test_my_func",
                    layer=Layer.APPLICATION,
                    intent="Tests my_func",
                    tests=("my_func",),
                    body="    def test_my_func():\n        assert my_func() == 1",
                    location=_loc(12, 18),
                ),
            ),
        )

    def test_test_mapping_present(self):
        mod = self._make_test_module()
        _, source_map = _emit_and_map(mod)
        test_mappings = [d for d in source_map.declarations if d.type == "test"]
        assert len(test_mappings) == 1
        assert test_mappings[0].name == "test_my_func"

    def test_test_has_body(self):
        mod = self._make_test_module()
        _, source_map = _emit_and_map(mod)
        test_mappings = [d for d in source_map.declarations if d.type == "test"]
        dm = test_mappings[0]
        assert dm.body_output is not None

    def test_test_no_decorator(self):
        """Tests don't have @component decorators."""
        mod = self._make_test_module()
        _, source_map = _emit_and_map(mod)
        test_mappings = [d for d in source_map.declarations if d.type == "test"]
        dm = test_mappings[0]
        assert dm.decorator_output is None


# ---------------------------------------------------------------------------
# Golden fixture tests
# ---------------------------------------------------------------------------


class TestGoldenFixture:
    """Test source map generation for the golden fixture (signal_processor.s0ma)."""

    @pytest.fixture()
    def golden_data(self):
        """Parse and emit the golden fixture, returning module + output + source map."""
        s0ma_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)
        output = emit_python(module)
        source_map = generate_source_map(
            module, output,
            source_file="signal_processor.s0ma",
            output_file="signal_processor.py",
        )
        return module, output, source_map

    def test_produces_source_map(self, golden_data):
        """Golden fixture produces a valid source map."""
        _, _, source_map = golden_data
        assert source_map.version == SOURCE_MAP_VERSION
        assert source_map.source_file == "signal_processor.s0ma"
        assert source_map.output_file == "signal_processor.py"

    def test_declaration_count(self, golden_data):
        """Golden fixture has correct number of declaration mappings.

        signal_processor.s0ma has 5 declarations:
        - 2 cells (SignalEnvelope, MAX_STALENESS_SECONDS)
        - 2 nerves (validate_envelope, process_signal)
        - 1 standalone axon (process_signal -> select_evaluator)
        """
        _, _, source_map = golden_data
        assert len(source_map.declarations) == 5

    def test_declaration_types(self, golden_data):
        """Golden fixture has the right declaration types."""
        _, _, source_map = golden_data
        types = [d.type for d in source_map.declarations]
        assert types.count("cell") == 2
        assert types.count("nerve") == 2
        assert types.count("axon") == 1

    def test_declaration_names(self, golden_data):
        """Golden fixture maps all expected declaration names."""
        _, _, source_map = golden_data
        names = [d.name for d in source_map.declarations]
        assert "SignalEnvelope" in names
        assert "MAX_STALENESS_SECONDS" in names
        assert "validate_envelope" in names
        assert "process_signal" in names
        assert "process_signal -> select_evaluator" in names

    def test_source_ranges_within_bounds(self, golden_data):
        """All source ranges fall within the source file line count."""
        module, _, source_map = golden_data
        for dm in source_map.declarations:
            assert dm.source.start_line >= 1, f"{dm.name} source start >= 1"
            assert dm.source.end_line >= dm.source.start_line, (
                f"{dm.name} source end >= start"
            )
            if dm.body_source:
                assert dm.body_source.start_line >= dm.source.start_line
                assert dm.body_source.end_line <= dm.source.end_line

    def test_output_ranges_within_bounds(self, golden_data):
        """All output ranges fall within the output file line count."""
        _, output, source_map = golden_data
        total_lines = len(output.split("\n"))
        for dm in source_map.declarations:
            assert dm.output.start_line >= 1, f"{dm.name} output start >= 1"
            assert dm.output.end_line <= total_lines, (
                f"{dm.name} output end <= {total_lines}"
            )
            if dm.body_output:
                assert dm.body_output.start_line >= dm.output.start_line
                assert dm.body_output.end_line <= dm.output.end_line
            if dm.decorator_output:
                assert dm.decorator_output.start_line >= dm.output.start_line
                assert dm.decorator_output.end_line <= dm.output.end_line

    def test_declarations_in_source_order(self, golden_data):
        """Declaration mappings are in source declaration order."""
        _, _, source_map = golden_data
        source_starts = [d.source.start_line for d in source_map.declarations]
        assert source_starts == sorted(source_starts)

    def test_declarations_in_output_order(self, golden_data):
        """Declaration output ranges are in increasing order (no overlaps)."""
        _, _, source_map = golden_data
        output_starts = [d.output.start_line for d in source_map.declarations]
        assert output_starts == sorted(output_starts)
        # No overlaps
        for i in range(len(source_map.declarations) - 1):
            assert (
                source_map.declarations[i].output.end_line
                < source_map.declarations[i + 1].output.start_line
            )

    def test_module_header_present(self, golden_data):
        """Module header mapping covers the expected regions."""
        _, _, source_map = golden_data
        mh = source_map.module_header
        assert mh.output_header.start_line == 1
        assert mh.output_imports.start_line > mh.output_header.end_line
        assert mh.output_all.start_line > mh.output_imports.end_line
        assert mh.output_registration.start_line > mh.output_all.end_line

    def test_nerve_decorator_before_body(self, golden_data):
        """Nerve declarations have decorator before body."""
        _, _, source_map = golden_data
        nerve_mappings = [d for d in source_map.declarations if d.type == "nerve"]
        for dm in nerve_mappings:
            assert dm.decorator_output is not None, f"{dm.name} has decorator"
            assert dm.body_output is not None, f"{dm.name} has body"
            assert dm.decorator_output.end_line < dm.body_output.start_line, (
                f"{dm.name} decorator before body"
            )

    def test_class_cell_has_decorator(self, golden_data):
        """SignalEnvelope (MODEL cell) has a decorator."""
        _, _, source_map = golden_data
        se = next(d for d in source_map.declarations if d.name == "SignalEnvelope")
        assert se.decorator_output is not None

    def test_constant_cell_no_decorator(self, golden_data):
        """MAX_STALENESS_SECONDS (CONSTANT cell) has no decorator."""
        _, _, source_map = golden_data
        ms = next(
            d for d in source_map.declarations
            if d.name == "MAX_STALENESS_SECONDS"
        )
        assert ms.decorator_output is None
        assert ms.body_output is not None


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Source map output must be deterministic (PRD NFR-01)."""

    def test_repeated_generation_identical(self):
        """Same input produces identical source map JSON."""
        mod = S0maModule(
            module=_minimal_module(exports=("my_func",)),
            nerves=(
                NerveDecl(
                    name="my_func",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="A test function",
                    expects="input",
                    guarantees="output",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="    def my_func():\n        return 1",
                    location=_loc(5, 10),
                ),
            ),
        )
        output = emit_python(mod)

        sm1 = generate_source_map(mod, output, "a.s0ma", "a.py")
        sm2 = generate_source_map(mod, output, "a.s0ma", "a.py")
        sm3 = generate_source_map(mod, output, "a.s0ma", "a.py")

        assert sm1.to_json() == sm2.to_json() == sm3.to_json()

    def test_golden_fixture_determinism(self):
        """Golden fixture produces identical source map across runs."""
        s0ma_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)
        output = emit_python(module)

        sm1 = generate_source_map(module, output, "sp.s0ma", "sp.py")
        sm2 = generate_source_map(module, output, "sp.s0ma", "sp.py")

        assert sm1.to_json() == sm2.to_json()


# ---------------------------------------------------------------------------
# JSON output tests
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def test_valid_json(self):
        """to_json() produces parseable JSON."""
        mod = S0maModule(module=_minimal_module())
        _, source_map = _emit_and_map(mod)
        parsed = json.loads(source_map.to_json())
        assert parsed["version"] == SOURCE_MAP_VERSION

    def test_json_has_mappings(self):
        """JSON includes mappings with declarations and module_header."""
        mod = S0maModule(module=_minimal_module())
        _, source_map = _emit_and_map(mod)
        parsed = json.loads(source_map.to_json())
        assert "mappings" in parsed
        assert "declarations" in parsed["mappings"]
        assert "module_header" in parsed["mappings"]

    def test_json_sorted_keys_determinism(self):
        """JSON keys are sorted for deterministic output."""
        mod = S0maModule(
            module=_minimal_module(exports=("foo",)),
            nerves=(
                NerveDecl(
                    name="foo",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Test nerve",
                    expects="in",
                    guarantees="out",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="    def foo():\n        pass",
                    location=_loc(5, 10),
                ),
            ),
        )
        _, source_map = _emit_and_map(mod)
        j = source_map.to_json()

        # Verify top-level keys are sorted
        parsed = json.loads(j)
        assert list(parsed.keys()) == sorted(parsed.keys())

        # Verify mappings keys are sorted
        assert list(parsed["mappings"].keys()) == sorted(
            parsed["mappings"].keys()
        )


# ---------------------------------------------------------------------------
# Convenience function test
# ---------------------------------------------------------------------------


class TestConvenienceFunction:
    def test_generate_source_map_matches_class(self):
        """generate_source_map() produces same result as SourceMapGenerator."""
        mod = S0maModule(
            module=_minimal_module(exports=("foo",)),
            nerves=(
                NerveDecl(
                    name="foo",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Test nerve",
                    expects="in",
                    guarantees="out",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="    def foo():\n        pass",
                    location=_loc(5, 10),
                ),
            ),
        )
        output = emit_python(mod)

        sm_func = generate_source_map(mod, output, "x.s0ma", "x.py")
        gen = SourceMapGenerator()
        sm_class = gen.generate(mod, output, "x.s0ma", "x.py")

        assert sm_func.to_json() == sm_class.to_json()


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_source_location(self):
        """Declarations without SourceLocation get (0, 0) source range."""
        mod = S0maModule(
            module=ModuleDecl(
                name="test_mod",
                layer=Layer.APPLICATION,
                version="1.0.0",
                intent="Test module without locations",
                exports=("foo",),
                location=None,
            ),
            nerves=(
                NerveDecl(
                    name="foo",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="No location nerve",
                    expects="in",
                    guarantees="out",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="    def foo():\n        pass",
                    location=None,
                ),
            ),
        )
        _, source_map = _emit_and_map(mod)
        assert source_map.module_header.source == LineRange(1, 1)
        dm = source_map.declarations[0]
        assert dm.source == LineRange(0, 0)
        assert dm.body_source is None  # can't estimate without location

    def test_no_body(self):
        """Declarations without body text get no body_source."""
        mod = S0maModule(
            module=_minimal_module(exports=("foo",)),
            nerves=(
                NerveDecl(
                    name="foo",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Nerve without body",
                    expects="in",
                    guarantees="out",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body=None,
                    location=_loc(5, 10),
                ),
            ),
        )
        _, source_map = _emit_and_map(mod)
        dm = source_map.declarations[0]
        assert dm.body_source is None

    def test_multiple_declarations_ordered(self):
        """Multiple declarations are mapped in source order."""
        mod = S0maModule(
            module=_minimal_module(exports=("alpha", "beta")),
            nerves=(
                NerveDecl(
                    name="alpha",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="First function",
                    expects="in",
                    guarantees="out",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="    def alpha():\n        return 1",
                    location=_loc(5, 10),
                ),
                NerveDecl(
                    name="beta",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Second function",
                    expects="in",
                    guarantees="out",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="    def beta():\n        return 2",
                    location=_loc(12, 17),
                ),
            ),
        )
        _, source_map = _emit_and_map(mod)
        assert len(source_map.declarations) == 2
        assert source_map.declarations[0].name == "alpha"
        assert source_map.declarations[1].name == "beta"
        # No overlap in output ranges
        assert (
            source_map.declarations[0].output.end_line
            < source_map.declarations[1].output.start_line
        )


# ---------------------------------------------------------------------------
# Reverse resolver: resolve_output_line (DSL 0.13.0 M3, spec (a))
# ---------------------------------------------------------------------------


_MIXED_SOURCE = '''\
module mixed
    layer: APPLICATION
    version: 1.0.0
    intent: "A module with one of every body-bearing declaration kind."
    exports: [compute, Envelope]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell Envelope :: APPLICATION
    kind: MODEL
    visibility: PUBLIC
    intent: "Wraps a single integer payload for the compute nerve."
    schema: "Dataclass. n: int."
    invariants: none
    covered_by: none
    ---
    @dataclass
    class Envelope:
        n: int = 0

cell LIMIT :: APPLICATION
    kind: CONSTANT
    visibility: INTERNAL
    intent: "Ceiling applied to a computed value before it is returned."
    schema: "int constant. Value: 99."
    invariants: none
    covered_by: none
    ---
    LIMIT: int = 99

helper _double :: APPLICATION
    intent: "Double an integer, the compute nerve's private plumbing."
    ---
    def _double(n: int) -> int:
        return n * 2

nerve compute :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Compute a doubled value from an envelope's payload."
    expects: "envelope.n is an int"
    guarantees: "Returns 2 * envelope.n"
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
    def compute(envelope: Envelope) -> int:
        return _double(envelope.n)

test test_compute :: APPLICATION
    intent: "Verifies compute doubles the envelope payload."
    tests: [mixed.compute]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_compute():
        assert compute(Envelope(2)) == 4
'''


def _make_mixed_module() -> S0maModule:
    """A parsed module with one of every body-bearing declaration kind.

    Nerve + ``@component`` (MODEL) cell + CONSTANT cell + helper + test,
    parsed from real ``.s0ma`` source (so bodies are correctly dedented),
    exercising every arm of the annotator's include/exclude rule and the
    resolver's region classification in one build.
    """
    return parse_s0ma(_MIXED_SOURCE, "src/mixed.s0ma", StrictnessMode.DEV)


def _emit_annotate_map(
    module: S0maModule,
    source_file: str = "src/mixed.s0ma",
) -> tuple[str, SourceMap]:
    """Emit, annotate with source pointers, then map — the pipeline shape.

    Mirrors ``_transpile_module``'s ordering (emit -> annotate -> map),
    minus ``inject_hashes`` (irrelevant to spans), so the returned map is
    the one the committed ``.s0ma.map`` would carry over annotated text.
    """
    output = emit_python(module)
    annotated = annotate_source_pointers(module, output, source_file=source_file)
    source_map = generate_source_map(module, annotated, source_file, "mixed.py")
    return annotated, source_map


class TestResolveOutputLine:
    """``resolve_output_line`` — the reverse lookup the ``.s0ma.map`` lacked."""

    def test_body_line_is_exact(self) -> None:
        """A body output line resolves by exact arithmetic to its source line."""
        _, smap = _emit_annotate_map(_make_mixed_module())
        (nerve,) = [d for d in smap.declarations if d.name == "compute"]
        assert nerve.body_output is not None and nerve.body_source is not None
        # First authored body line -> first body source line.
        r = resolve_output_line(smap, nerve.body_output.start_line)
        assert r.region == "body"
        assert r.declaration == "compute"
        assert r.source_line == nerve.body_source.start_line
        assert r.source_file == smap.source_file
        # A line two into the body -> two into the source body.
        r2 = resolve_output_line(smap, nerve.body_output.start_line + 1)
        assert r2.source_line == nerve.body_source.start_line + 1

    def test_helper_body_resolves(self) -> None:
        _, smap = _emit_annotate_map(_make_mixed_module())
        (helper,) = [d for d in smap.declarations if d.type == "helper"]
        assert helper.body_output is not None and helper.body_source is not None
        r = resolve_output_line(smap, helper.body_output.start_line)
        assert r.region == "body"
        assert r.declaration == "_double"
        assert r.source_line == helper.body_source.start_line

    def test_decorator_region(self) -> None:
        _, smap = _emit_annotate_map(_make_mixed_module())
        (nerve,) = [d for d in smap.declarations if d.name == "compute"]
        assert nerve.decorator_output is not None
        r = resolve_output_line(smap, nerve.decorator_output.start_line)
        assert r.region == "decorator"
        assert r.declaration == "compute"
        assert r.source_line == nerve.source.start_line

    def test_module_header_regions(self) -> None:
        _, smap = _emit_annotate_map(_make_mixed_module())
        mh = smap.module_header
        assert resolve_output_line(smap, 1).region == "module-header"
        assert (
            resolve_output_line(smap, mh.output_imports.start_line).region
            == "imports"
        )
        assert (
            resolve_output_line(smap, mh.output_all.start_line).region
            == "exports"
        )
        assert (
            resolve_output_line(smap, mh.output_registration.start_line).region
            == "registration"
        )

    def test_between_declarations_is_unresolved(self) -> None:
        """A line past the last declaration resolves to a labelled gap."""
        annotated, smap = _emit_annotate_map(_make_mixed_module())
        total = len(annotated.split("\n"))
        r = resolve_output_line(smap, total)  # trailing blank
        assert r.declaration is None
        assert r.region in ("between-declarations", "registration")
        if r.region == "between-declarations":
            assert r.source_line is None

    def test_embedded_file_body_resolves_into_embed(self) -> None:
        """A prompts-style ``@file()`` cell resolves into the embedded file."""
        # Build via the shipped self-host prompts map, which carries an
        # embedded CONSTANT cell (body_source_file + body_source_lines).
        dm = DeclarationMapping(
            name="TPL",
            type="cell",
            source=LineRange(7, 14),
            output=LineRange(24, 69),
            body_output=LineRange(24, 62),
            body_source_file="src/prompts/author.txt",
            body_source_lines=LineRange(1, 39),
        )
        smap = SourceMap(
            version=SOURCE_MAP_VERSION,
            source_file="src/prompts.s0ma",
            output_file="prompts.py",
            declarations=(dm,),
            module_header=ModuleHeaderMapping(
                source=LineRange(1, 6),
                output_header=LineRange(1, 5),
                output_imports=LineRange(6, 12),
                output_all=LineRange(14, 14),
                output_registration=LineRange(16, 22),
            ),
        )
        r = resolve_output_line(smap, 30)  # 6 lines into the body
        assert r.region == "body"
        assert r.source_file == "src/prompts/author.txt"
        assert r.source_line == 7  # 1 + (30 - 24)
        # A line past the embedded literal clamps to the recorded end.
        r_end = resolve_output_line(smap, 62)
        assert r_end.source_line == 39

    def test_format_frame(self) -> None:
        loc = ResolvedLocation(
            source_file="src/rooms.s0ma",
            source_line=43,
            declaration="RoomsvcApi",
            region="body",
        )
        assert loc.format_frame("build/rooms.py", 65) == (
            "resolved: build/rooms.py:65 -> src/rooms.s0ma:43 (RoomsvcApi)"
        )


# ---------------------------------------------------------------------------
# Passive boundary comments (DSL 0.13.0 M3, spec (b))
# ---------------------------------------------------------------------------


class TestSourcePointerComments:
    """The passive ``# s0ma:`` pointers the emitter writes into generated .py."""

    def test_module_header_pointer_present(self) -> None:
        annotated, _ = _emit_annotate_map(_make_mixed_module())
        header_pointers = [
            line
            for line in annotated.split("\n")
            if line.startswith(f"{SOURCE_POINTER_PREFIX}generated from ")
        ]
        assert len(header_pointers) == 1
        assert "src/mixed.s0ma" in header_pointers[0]
        assert "never this file" in header_pointers[0]

    def test_one_pointer_per_annotated_declaration(self) -> None:
        """Nerve + MODEL cell + helper + test are annotated; CONSTANT is not."""
        annotated, _ = _emit_annotate_map(_make_mixed_module())
        pointers = [
            line
            for line in annotated.split("\n")
            if line.startswith(SOURCE_POINTER_PREFIX)
            and "generated from" not in line
        ]
        named = {line.split("(")[-1].rstrip(")") for line in pointers}
        assert named == {
            "nerve compute",
            "cell Envelope",
            "helper _double",
            "test test_compute",
        }
        # The CONSTANT cell (LIMIT) is deliberately not annotated.
        assert not any("LIMIT" in line for line in pointers)

    def test_pointer_sits_one_line_above_the_body(self) -> None:
        """The map's ``body_output.start`` is the line after each pointer.

        Checked for every *annotated* declaration (those named in a
        pointer); a CONSTANT cell carries body ranges but no pointer.
        """
        annotated, smap = _emit_annotate_map(_make_mixed_module())
        lines = annotated.split("\n")
        annotated_names = {
            line.rsplit(" ", 1)[-1].rstrip(")")
            for line in lines
            if line.startswith(SOURCE_POINTER_PREFIX) and "generated from" not in line
        }
        assert annotated_names  # sanity: some declarations were annotated
        checked = 0
        for dm in smap.declarations:
            if dm.name not in annotated_names:
                continue
            assert dm.body_output is not None and dm.body_source is not None
            pointer_line = lines[dm.body_output.start_line - 2]  # 0-indexed
            assert pointer_line.startswith(SOURCE_POINTER_PREFIX), (
                f"expected a source pointer immediately above {dm.name}'s body"
            )
            # The pointer names the body's source start line.
            assert f":{dm.body_source.start_line} " in pointer_line
            checked += 1
        assert checked == len(annotated_names)

    def test_annotation_is_deterministic(self) -> None:
        module = _make_mixed_module()
        output = emit_python(module)
        a = annotate_source_pointers(module, output, source_file="src/mixed.s0ma")
        b = annotate_source_pointers(module, output, source_file="src/mixed.s0ma")
        assert a == b

    def test_annotated_output_still_parses(self) -> None:
        import ast

        annotated, _ = _emit_annotate_map(_make_mixed_module())
        ast.parse(annotated)  # raises on invalid Python

    def test_round_trip_pointer_matches_resolver(self) -> None:
        """Every pointer's stated source line == resolver of the line below it."""
        import re

        annotated, smap = _emit_annotate_map(_make_mixed_module())
        pat = re.compile(r"^# s0ma: (.+):(\d+) \((\w+) (.+)\)$")
        seen = 0
        for i, line in enumerate(annotated.split("\n"), start=1):
            m = pat.match(line)
            if not m:
                continue
            seen += 1
            stated_line, _dtype, dname = int(m.group(2)), m.group(3), m.group(4)
            resolved = resolve_output_line(smap, i + 1)  # first body line
            assert resolved.region == "body"
            assert resolved.declaration == dname
            assert resolved.source_line == stated_line
        assert seen == 4  # nerve + cell + helper + test


class TestSourcePointerDriftGuard:
    """The pointers are inside the drift hash: regenerate clean, edit trips."""

    def test_regenerated_file_is_not_hand_edited(self, tmp_path) -> None:
        from s0ma_dsl.cli.main import _transpile_single_file
        from s0ma_dsl.codegen.python_emitter import is_hand_edited

        src = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        _transpile_single_file(
            src,
            mode=StrictnessMode.DEV,
            output_dir=tmp_path,
            emit_ir=False,
            emit_source_map=True,
        )
        py = (tmp_path / "signal_processor.py").read_text(encoding="utf-8")
        # The pointers are present ...
        assert any(
            line.startswith(SOURCE_POINTER_PREFIX) for line in py.splitlines()
        )
        # ... and the file the transpiler just wrote is NOT hand-edited:
        # the drift hash was computed over the final text, pointers included.
        assert is_hand_edited(py) is False

    def test_editing_a_body_line_trips_drift(self, tmp_path) -> None:
        from s0ma_dsl.cli.main import _transpile_single_file
        from s0ma_dsl.codegen.python_emitter import is_hand_edited

        src = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        _transpile_single_file(
            src,
            mode=StrictnessMode.DEV,
            output_dir=tmp_path,
            emit_ir=False,
            emit_source_map=True,
        )
        py = (tmp_path / "signal_processor.py").read_text(encoding="utf-8")
        tampered = py.replace("    return", "    return  # edit", 1)
        assert tampered != py
        assert is_hand_edited(tampered) is True


# ---------------------------------------------------------------------------
# Spans checked against the .s0ma text itself
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^(module|nerve|cell|ganglion|test|helper|axon) ")


def _relayout(source: str, *, blank_lines: int, final_newlines: int) -> str:
    """The same declarations, separated by a different amount of blank space.

    ``blank_lines`` blank lines go between consecutive declarations and
    ``final_newlines`` newlines end the file (0: the last line has none).
    Every declaration keeps its text; only where it sits moves.
    """
    blocks: list[list[str]] = []
    for line in source.split("\n"):
        if _HEADER_RE.match(line):
            blocks.append([])
        blocks[-1].append(line)
    for block in blocks:
        while not block[-1].strip():
            block.pop()
    separator = "\n" * (blank_lines + 1)
    return (
        separator.join("\n".join(block) for block in blocks)
        + "\n" * final_newlines
    )


_LAYOUTS = [
    pytest.param(1, 1, id="one-blank-line"),
    pytest.param(0, 1, id="no-blank-line"),
    pytest.param(3, 1, id="three-blank-lines"),
    pytest.param(1, 0, id="no-final-newline"),
    pytest.param(1, 3, id="blank-lines-at-end"),
]


class TestSpansMatchTheSourceText:
    """The map, the pointers and the resolver agree with the ``.s0ma`` text.

    The tests above check the map against itself — a pointer against
    ``body_source``, the resolver against the pointer — so a range that
    was consistently one line late passed all of them. These read the
    source lines the map names. The ranges used to run on through the
    blank lines after a declaration (and one line past the end of the
    file), so every pointer named the line after the ``def``.
    """

    @staticmethod
    def _build(
        blank_lines: int, final_newlines: int
    ) -> tuple[list[str], S0maModule, str, SourceMap]:
        source = _relayout(
            _MIXED_SOURCE, blank_lines=blank_lines, final_newlines=final_newlines
        )
        module = parse_s0ma(source, "src/mixed.s0ma", StrictnessMode.DEV)
        annotated, smap = _emit_annotate_map(module)
        return source.split("\n"), module, annotated, smap

    @pytest.mark.parametrize(("blank_lines", "final_newlines"), _LAYOUTS)
    def test_body_source_holds_the_body(
        self, blank_lines: int, final_newlines: int
    ) -> None:
        lines, module, _, smap = self._build(blank_lines, final_newlines)
        # ``raw_body`` is the body exactly as written, indentation included.
        bodies = {decl.name: decl.raw_body for decl in module.all_declarations}
        checked = 0
        for dm in smap.declarations:
            if dm.body_source is None:
                continue
            named = lines[dm.body_source.start_line - 1 : dm.body_source.end_line]
            assert "\n".join(named) == bodies[dm.name], dm.name
            checked += 1
        assert checked == 5  # both cells, the helper, the nerve, the test

    @pytest.mark.parametrize(("blank_lines", "final_newlines"), _LAYOUTS)
    def test_source_ranges_end_on_the_last_line_of_text(
        self, blank_lines: int, final_newlines: int
    ) -> None:
        lines, _, _, smap = self._build(blank_lines, final_newlines)
        ranges = [smap.module_header.source, *(dm.source for dm in smap.declarations)]
        for rng in ranges:
            assert lines[rng.end_line - 1].strip(), rng
        # The last declaration ends on the file's last line, never past it.
        last_text_line = max(i for i, line in enumerate(lines, start=1) if line.strip())
        assert smap.declarations[-1].source.end_line == last_text_line

    @pytest.mark.parametrize(("blank_lines", "final_newlines"), _LAYOUTS)
    def test_each_pointer_names_the_line_its_body_starts_on(
        self, blank_lines: int, final_newlines: int
    ) -> None:
        lines, _, annotated, _ = self._build(blank_lines, final_newlines)
        pattern = re.compile(r"^# s0ma: src/mixed\.s0ma:(\d+) \(")
        out = annotated.split("\n")
        seen = 0
        for i, line in enumerate(out):
            match = pattern.match(line)
            if match is None:
                continue
            first_body_line = out[i + 1]
            assert lines[int(match.group(1)) - 1].strip() == first_body_line.strip()
            seen += 1
        assert seen == 4  # nerve + cell + helper + test

    @pytest.mark.parametrize(("blank_lines", "final_newlines"), _LAYOUTS)
    def test_every_body_line_resolves_to_its_own_text(
        self, blank_lines: int, final_newlines: int
    ) -> None:
        lines, _, annotated, smap = self._build(blank_lines, final_newlines)
        out = annotated.split("\n")
        checked = 0
        for dm in smap.declarations:
            if dm.body_output is None or dm.body_source is None:
                continue
            for number in range(dm.body_output.start_line, dm.body_output.end_line + 1):
                resolved = resolve_output_line(smap, number)
                assert resolved.source_line is not None
                assert lines[resolved.source_line - 1].strip() == out[number - 1].strip()
                checked += 1
        assert checked


# ---------------------------------------------------------------------------
# Map deserialization: from_dict / load_source_map (M3 follow-up)
# ---------------------------------------------------------------------------


class TestSourceMapDeserialization:
    """``SourceMap.from_dict`` / ``load_source_map`` — the read half.

    ``to_dict``/``to_json`` shipped in 0.7.0 with no inverse, so nothing
    could consume a ``.s0ma.map`` from disk (the write-only-artifact gap
    the M3 evidence anchor measured). These pin the loader against the
    serializer and against the resolver.
    """

    def test_from_dict_mirrors_to_dict(self) -> None:
        _, smap = _emit_annotate_map(_make_mixed_module())
        assert SourceMap.from_dict(smap.to_dict()) == smap

    def test_json_round_trip_is_lossless(self) -> None:
        _, smap = _emit_annotate_map(_make_mixed_module())
        assert SourceMap.from_dict(json.loads(smap.to_json())) == smap

    def test_round_tripped_map_resolves_identically(self) -> None:
        """``resolve_output_line`` answers identically over the loaded map.

        Every output line of the annotated module — bodies, decorators,
        header regions, and gaps alike — resolves to the same
        ``ResolvedLocation`` through the ``to_json -> from_dict`` copy as
        through the in-memory original.
        """
        annotated, smap = _emit_annotate_map(_make_mixed_module())
        loaded = SourceMap.from_dict(json.loads(smap.to_json()))
        for line in range(1, len(annotated.split("\n")) + 1):
            assert resolve_output_line(loaded, line) == resolve_output_line(
                smap, line
            ), f"resolution diverged at output line {line}"

    def test_load_source_map_reads_disk(self, tmp_path: Path) -> None:
        _, smap = _emit_annotate_map(_make_mixed_module())
        map_path = tmp_path / "mixed.s0ma.map"
        map_path.write_text(smap.to_json() + "\n", encoding="utf-8")
        assert load_source_map(map_path) == smap
        # str paths are accepted too (the CLI hands strings around).
        assert load_source_map(str(map_path)) == smap


# ---------------------------------------------------------------------------
# Shipped map fixtures: the 3 committed self-host artifacts (M3 follow-up)
# ---------------------------------------------------------------------------

#: The committed self-host build of packages/s0ma-mcp — real shipped
#: ``.py`` + ``.s0ma.map`` pairs, regenerated byte-clean on every M3-era
#: build (the ``selfhost-build`` gate).
_BUILT_DIR = (
    Path(__file__).resolve().parents[2]
    / "s0ma-mcp"
    / "src"
    / "s0ma_mcp"
    / "_built"
)

_SELF_HOST_STEMS = ("prompts", "resources", "tools")

#: The per-declaration boundary pointer: ``# s0ma: <src>:<line> (<kind> <name>)``.
#: Deliberately does NOT match the module-header pointer (no ``:<line> (``).
_POINTER_RE = re.compile(r"^# s0ma: (.+):(\d+) \(([\w-]+) (.+)\)$")


@pytest.mark.skipif(
    not _BUILT_DIR.is_dir(),
    reason="s0ma-mcp _built dir not present (standalone s0ma-dsl checkout)",
)
class TestShippedMapFixtures:
    """The committed ``_built/*.s0ma.map`` files are consumable and honest.

    Loads each shipped map from disk (the exact artifact an agent or the
    0.14.0 traceback post-processor would read) and pins two contracts:
    the loader is lossless over real artifacts, and every ``# s0ma:``
    pointer in the sibling ``.py`` resolves — through the shipped map —
    back to exactly the source file/line/declaration it states.
    """

    @pytest.mark.parametrize("stem", _SELF_HOST_STEMS)
    def test_shipped_map_loads_losslessly(self, stem: str) -> None:
        map_path = _BUILT_DIR / f"{stem}.s0ma.map"
        payload = json.loads(map_path.read_text(encoding="utf-8"))
        smap = load_source_map(map_path)
        assert smap.to_dict() == payload
        assert smap.output_file == f"{stem}.py"

    @pytest.mark.parametrize("stem", _SELF_HOST_STEMS)
    def test_shipped_pointers_resolve_to_their_stated_source(
        self, stem: str
    ) -> None:
        """Pointer ↔ map self-consistency on the committed artifacts.

        For each ``# s0ma: <src>:<line> (<kind> <name>)`` at output line
        L, the first body line (L+1) resolves through the shipped map to
        that same source file, line, and declaration.
        """
        smap = load_source_map(_BUILT_DIR / f"{stem}.s0ma.map")
        py_lines = (
            (_BUILT_DIR / f"{stem}.py")
            .read_text(encoding="utf-8")
            .split("\n")
        )
        seen = 0
        for i, line in enumerate(py_lines, start=1):
            m = _POINTER_RE.match(line)
            if m is None:
                continue
            seen += 1
            stated_file = m.group(1)
            stated_line = int(m.group(2))
            stated_name = m.group(4)
            resolved = resolve_output_line(smap, i + 1)
            assert resolved.region == "body", (
                f"{stem}.py:{i + 1} (below pointer {line!r}) resolved to "
                f"region {resolved.region!r}, expected 'body'"
            )
            assert resolved.declaration == stated_name
            assert resolved.source_line == stated_line
            assert resolved.source_file == stated_file
        assert seen >= 4, (
            f"{stem}.py should carry at least 4 boundary pointers, "
            f"found {seen}"
        )
