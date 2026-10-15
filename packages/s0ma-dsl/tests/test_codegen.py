"""Python emitter tests for the s0ma DSL transpiler (Milestone 11).

Tests code generation from parsed S0maModule ASTs to valid Python.
Verifies PEP 8 import ordering, __all__ from exports, @component
decorator mapping, body preservation, and syntactic validity via
compile().

PRD references: FR-25 (Python emission), §2.2.1–2.2.6
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
    InlineAxon,
    ModuleDecl,
    NerveDecl,
    RequiresEntry,
    S0maModule,
    SourceLocation,
    StandaloneAxonDecl,
    UsesEntry,
)
from s0ma_dsl.codegen.python_emitter import (
    PythonEmitter,
    _is_stdlib,
    _requires_to_import_line,
    _uses_to_import_line,
    emit_python,
)
from s0ma_dsl.config import StrictnessMode

# F1 (feedback 5–6 follow-up): the codegen no longer owns a private
# ``_dedent_body`` — bodies are dedented exactly once at parse time by
# ``parser.body_extractor._dedent_body``. The legacy ``TestDedentBody``
# unit tests now exercise that single source of truth.
from s0ma_dsl.parser.body_extractor import _dedent_body
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from tests.conftest import VALID_FIXTURES_DIR

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _loc(start: int = 1, end: int = 5) -> SourceLocation:
    return SourceLocation(start_line=start, start_column=0, end_line=end, end_column=0)


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
        intent="Test module for codegen",
        exports=exports,
        requires=requires,
        uses=uses,
        location=_loc(1, 3),
    )


def _compile_check(source: str, filename: str = "<test>") -> None:
    """Assert that Python source compiles without SyntaxError."""
    try:
        compile(source, filename, "exec")
    except SyntaxError as e:
        pytest.fail(f"Generated Python has syntax error: {e}\n\nSource:\n{source}")


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------


class TestDedentBody:
    def test_simple_function(self):
        body = "    def foo():\n        return 1"
        result = _dedent_body(body)
        assert result == "def foo():\n    return 1"

    def test_column_zero_comment(self):
        body = "    def foo():\n        pass\n# column zero comment"
        result = _dedent_body(body)
        assert "def foo():" in result
        assert "# column zero comment" in result

    def test_empty_body(self):
        assert _dedent_body("") == ""

    def test_already_dedented(self):
        body = "def foo():\n    return 1"
        result = _dedent_body(body)
        assert result == body


class TestStdlibDetection:
    def test_stdlib_modules(self):
        assert _is_stdlib("os")
        assert _is_stdlib("os.path")
        assert _is_stdlib("uuid")
        assert _is_stdlib("uuid.UUID")
        assert _is_stdlib("dataclasses")
        assert _is_stdlib("time")

    def test_third_party(self):
        assert not _is_stdlib("lark")
        assert not _is_stdlib("requests")
        assert not _is_stdlib("numpy")


class TestImportLineGeneration:
    def test_simple_import(self):
        entry = RequiresEntry(module_path="time", is_from_import=False)
        assert _requires_to_import_line(entry) == "import time"

    def test_from_import(self):
        entry = RequiresEntry(module_path="uuid.UUID", is_from_import=True)
        assert _requires_to_import_line(entry) == "from uuid import UUID"

    def test_aliased_import(self):
        entry = RequiresEntry(module_path="time", alias="t", is_from_import=False)
        assert _requires_to_import_line(entry) == "import time as t"

    def test_aliased_from_import(self):
        entry = RequiresEntry(
            module_path="dataclasses.dataclass", alias="dc", is_from_import=True
        )
        assert _requires_to_import_line(entry) == "from dataclasses import dataclass as dc"

    def test_colon_from_import(self):
        """Colon-form produces correct from-import line."""
        entry = RequiresEntry(module_path="unittest.mock.patch", is_from_import=True)
        assert _requires_to_import_line(entry) == "from unittest.mock import patch"

    def test_colon_from_import_aliased(self):
        """Colon-form with alias produces correct from-import line."""
        entry = RequiresEntry(
            module_path="unittest.mock.patch", alias="p", is_from_import=True
        )
        assert _requires_to_import_line(entry) == "from unittest.mock import patch as p"

    def test_known_exception_from_import(self):
        """Known-exception (datetime.datetime) produces correct from-import."""
        entry = RequiresEntry(module_path="datetime.datetime", is_from_import=True)
        assert _requires_to_import_line(entry) == "from datetime import datetime"

    def test_uses_import(self):
        entry = UsesEntry(qualified_name="routing.select_evaluator")
        assert _uses_to_import_line(entry) == "from routing import select_evaluator"

    def test_uses_aliased_import(self):
        entry = UsesEntry(qualified_name="routing.select_evaluator", alias="sel")
        assert _uses_to_import_line(entry) == "from routing import select_evaluator as sel"


# ---------------------------------------------------------------------------
# Integration tests: minimal modules
# ---------------------------------------------------------------------------


class TestEmitMinimalModule:
    """Test emission of minimal valid modules."""

    def test_empty_module_compiles(self):
        mod = _minimal_module()
        s0ma_mod = S0maModule(module=mod)
        output = emit_python(s0ma_mod)
        _compile_check(output)

    def test_module_header(self):
        mod = _minimal_module(name="my_module")
        s0ma_mod = S0maModule(module=mod)
        output = emit_python(s0ma_mod)
        assert '"""my_module' in output
        assert "Auto-generated by s0ma DSL transpiler" in output

    def test_all_from_exports(self):
        mod = _minimal_module(exports=("foo", "bar"))
        s0ma_mod = S0maModule(module=mod)
        output = emit_python(s0ma_mod)
        assert '__all__ = ["foo", "bar"]' in output

    def test_empty_exports(self):
        mod = _minimal_module(exports=())
        s0ma_mod = S0maModule(module=mod)
        output = emit_python(s0ma_mod)
        assert "__all__: list[str] = []" in output

    def test_register_module_call(self):
        mod = _minimal_module(name="my_module")
        s0ma_mod = S0maModule(module=mod)
        output = emit_python(s0ma_mod)
        assert 'register_module(' in output
        assert 'name="my_module"' in output
        assert 'version="1.0.0"' in output

    def test_constant_only_module_has_layer_import(self):
        """Constant-only modules must import Layer for register_module().

        Finding 1.1: Modules with only CONSTANT cells (no nerves, no ganglia,
        no decorated cells) still emit register_module(layer=Layer.X), so
        Layer must always be imported.
        """
        mod = _minimal_module(name="constants_mod")
        cell = CellDecl(
            name="MAX_RETRIES",
            layer=Layer.APPLICATION,
            kind=Kind.CONSTANT,
            visibility=Visibility.PUBLIC,
            intent="Maximum retry count",
            schema="int",
            body='MAX_RETRIES = 3',
            location=_loc(5, 6),
        )
        s0ma_mod = S0maModule(module=mod, cells=(cell,))
        output = emit_python(s0ma_mod)
        assert "from s0ma.types import Layer" in output
        # ComponentKind should NOT be present (no decorated declarations)
        assert "ComponentKind" not in output
        _compile_check(output)

    def test_decorated_module_has_both_types(self):
        """Modules with nerves still import both ComponentKind and Layer."""
        mod = _minimal_module(name="nerve_mod", exports=("my_func",))
        nerve = NerveDecl(
            name="my_func",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="A function",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body="def my_func():\n    pass",
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        assert "from s0ma.types import ComponentKind, Layer" in output
        _compile_check(output)


class TestEmitImports:
    """Test PEP 8 import ordering."""

    def test_stdlib_before_third_party(self):
        mod = _minimal_module(
            requires=(
                RequiresEntry(module_path="lark", is_from_import=False),
                RequiresEntry(module_path="time", is_from_import=False),
            ),
        )
        s0ma_mod = S0maModule(module=mod)
        output = emit_python(s0ma_mod)
        time_pos = output.index("import time")
        lark_pos = output.index("import lark")
        assert time_pos < lark_pos, "stdlib imports should come before third-party"

    def test_s0ma_framework_after_third_party(self):
        mod = _minimal_module(
            requires=(
                RequiresEntry(module_path="lark", is_from_import=False),
            ),
        )
        s0ma_mod = S0maModule(
            module=mod,
            nerves=(
                NerveDecl(
                    name="my_func",
                    layer=Layer.APPLICATION,
                    kind=Kind.FUNCTION,
                    visibility=Visibility.PUBLIC,
                    intent="Test function",
                    expects="none",
                    guarantees="none",
                    evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                    body="def my_func():\n    pass",
                    location=_loc(5, 10),
                ),
            ),
        )
        output = emit_python(s0ma_mod)
        lark_pos = output.index("import lark")
        s0ma_pos = output.index("from s0ma")
        assert lark_pos < s0ma_pos, "third-party should come before s0ma framework"

    def test_uses_imports_last(self):
        mod = _minimal_module(
            requires=(
                RequiresEntry(module_path="time", is_from_import=False),
            ),
            uses=(
                UsesEntry(qualified_name="routing.select_evaluator"),
            ),
        )
        s0ma_mod = S0maModule(module=mod)
        output = emit_python(s0ma_mod)
        time_pos = output.index("import time")
        routing_pos = output.index("from routing import select_evaluator")
        assert time_pos < routing_pos, "uses imports should come after stdlib"

    def test_sorted_within_groups(self):
        mod = _minimal_module(
            requires=(
                RequiresEntry(module_path="uuid.UUID", is_from_import=True),
                RequiresEntry(module_path="dataclasses.dataclass", is_from_import=True),
                RequiresEntry(module_path="time", is_from_import=False),
            ),
        )
        s0ma_mod = S0maModule(module=mod)
        output = emit_python(s0ma_mod)
        # All stdlib — sorted alphabetically ("from ..." < "import ...")
        dc_pos = output.index("from dataclasses import dataclass")
        uuid_pos = output.index("from uuid import UUID")
        time_pos = output.index("import time")
        assert dc_pos < uuid_pos < time_pos, "stdlib imports should be sorted"

    def test_colon_syntax_end_to_end(self):
        """Parse colon-form requires and verify emitted import lines."""
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Colon import test."
    requires: [unittest.mock:patch, unittest.mock:MagicMock, dataclasses:dataclass]
    exports: []
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        parsed = parse_s0ma(source)
        output = emit_python(parsed)
        assert "from unittest.mock import patch" in output
        assert "from unittest.mock import MagicMock" in output
        assert "from dataclasses import dataclass" in output
        compile(output, "<colon_test>", "exec")

    def test_known_exceptions_end_to_end(self):
        """Parse known-exception requires and verify emitted import lines."""
        source = """\
module m
    layer: DOMAIN
    version: 1.0.0
    intent: "Known exception import test."
    requires: [datetime.datetime, functools.wraps, os.path]
    exports: []
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""
        parsed = parse_s0ma(source)
        output = emit_python(parsed)
        assert "from datetime import datetime" in output
        assert "from functools import wraps" in output
        assert "import os.path" in output
        compile(output, "<known_exc_test>", "exec")


# ---------------------------------------------------------------------------
# Nerve emission tests
# ---------------------------------------------------------------------------


class TestEmitNerve:
    """Test nerve declaration code generation."""

    def test_basic_nerve(self):
        mod = _minimal_module(exports=("my_func",))
        nerve = NerveDecl(
            name="my_func",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="A simple function",
            expects="valid input",
            guarantees="returns result",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body="def my_func(x: int) -> int:\n    return x + 1",
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        _compile_check(output)

        assert "@component(" in output
        assert 'name="my_func"' in output
        assert "kind=ComponentKind.FUNCTION" in output
        assert "Layer.APPLICATION" in output
        assert "def my_func(x: int) -> int:" in output
        assert "return x + 1" in output

    def test_nerve_with_contracts(self):
        mod = _minimal_module()
        nerve = NerveDecl(
            name="checked_func",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.INTERNAL,
            intent="A service with contracts",
            expects="input is not None",
            guarantees="output is valid",
            evaluates_at=EvaluatesAt.SUBSYSTEM,
            latency_ms=50,
            body="def checked_func():\n    pass",
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        _compile_check(output)

        assert "contracts=Contract(" in output
        assert "preconditions=" in output
        assert "postconditions=" in output
        assert "max_latency_ms=50" in output

    def test_nerve_with_dependencies(self):
        mod = _minimal_module()
        nerve = NerveDecl(
            name="orchestrator",
            layer=Layer.APPLICATION,
            kind=Kind.ORCHESTRATOR,
            visibility=Visibility.PUBLIC,
            intent="Orchestrates calls",
            expects="valid request",
            guarantees="request handled",
            evaluates_at=EvaluatesAt.SUBSYSTEM,
            depends_on=(
                InlineAxon(
                    target="helper_func",
                    relation=Relation.CALLS,
                    carries="request",
                    coupling=Coupling.TIGHT,
                ),
            ),
            body="def orchestrator():\n    helper_func()",
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        _compile_check(output)

        assert 'dependencies=["helper_func"]' in output

    def test_nerve_kind_mapping(self):
        """All nerve kinds map to valid ComponentKind references."""
        for kind in [Kind.SERVICE, Kind.FUNCTION, Kind.ADAPTER, Kind.ORCHESTRATOR]:
            mod = _minimal_module()
            nerve = NerveDecl(
                name=f"test_{kind.value.lower()}",
                layer=Layer.APPLICATION,
                kind=kind,
                visibility=Visibility.PUBLIC,
                intent=f"Test {kind.value} nerve",
                expects="none",
                guarantees="none",
                evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
                body=f"def test_{kind.value.lower()}():\n    pass",
                location=_loc(5, 10),
            )
            s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
            output = emit_python(s0ma_mod)
            _compile_check(output)
            assert f"kind=ComponentKind.{kind.value}" in output

    def test_nerve_metadata_includes_visibility(self):
        mod = _minimal_module()
        nerve = NerveDecl(
            name="internal_func",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.INTERNAL,
            intent="Internal function",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body="def internal_func():\n    pass",
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        assert '"visibility": "INTERNAL"' in output

    def test_nerve_metadata_includes_raises(self):
        mod = _minimal_module()
        nerve = NerveDecl(
            name="risky_func",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="Function that raises",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            raises=("ValueError", "TypeError"),
            body="def risky_func():\n    pass",
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        assert '"raises": ["ValueError", "TypeError"]' in output


# ---------------------------------------------------------------------------
# Class-based nerve emission tests (MS 8)
# ---------------------------------------------------------------------------


class TestEmitClassNerve:
    """Test class-based nerve emission with dict-compatible factory wrapper."""

    def test_service_class_nerve_compiles(self):
        """A SERVICE nerve with class body transpiles to valid Python."""
        mod = _minimal_module(exports=("FileService",))
        nerve = NerveDecl(
            name="FileService",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="File operations service",
            expects="valid path",
            guarantees="returns content",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body=(
                "class FileService:\n"
                "    def __init__(self, root_dir):\n"
                "        self.root_dir = root_dir\n"
                "    def read_file(self, path):\n"
                "        return 'content'\n"
                "    def write_file(self, path, data):\n"
                "        pass"
            ),
            location=_loc(5, 15),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        _compile_check(output)

    def test_class_nerve_has_impl_class(self):
        """The user class is renamed to _<Name>Impl."""
        mod = _minimal_module(exports=("MySvc",))
        nerve = NerveDecl(
            name="MySvc",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="A service",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body=(
                "class MySvc:\n"
                "    def do_work(self):\n"
                "        return 42"
            ),
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        assert "class _MySvcImpl:" in output
        assert "class MySvc:" not in output

    def test_class_nerve_has_factory_function(self):
        """A factory function with the original name is generated."""
        mod = _minimal_module(exports=("MySvc",))
        nerve = NerveDecl(
            name="MySvc",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="A service",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body=(
                "class MySvc:\n"
                "    def do_work(self):\n"
                "        return 42"
            ),
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        assert "def MySvc(" in output
        assert "Dict-compatible factory for MySvc" in output
        assert "_MySvcImpl(" in output

    def test_class_nerve_component_decorator_on_factory(self):
        """The @component decorator is applied to the factory function."""
        mod = _minimal_module(exports=("MySvc",))
        nerve = NerveDecl(
            name="MySvc",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="A service",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body=(
                "class MySvc:\n"
                "    def do_work(self):\n"
                "        return 42"
            ),
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        # The @component decorator should appear before "def MySvc("
        comp_pos = output.rindex("@component(")
        factory_pos = output.index("def MySvc(")
        assert comp_pos < factory_pos, "@component should decorate the factory function"

    def test_class_nerve_uses_provides_for_dict(self):
        """When provides is declared, the dict uses those specific methods."""
        mod = _minimal_module(exports=("FileSvc",))
        nerve = NerveDecl(
            name="FileSvc",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="File service",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            provides=("read_file", "write_file"),
            body=(
                "class FileSvc:\n"
                "    def __init__(self):\n"
                "        pass\n"
                "    def read_file(self):\n"
                "        return 'data'\n"
                "    def write_file(self, data):\n"
                "        pass\n"
                "    def _internal_helper(self):\n"
                "        pass"
            ),
            location=_loc(5, 15),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        assert '"read_file": instance.read_file' in output
        assert '"write_file": instance.write_file' in output
        assert "_internal_helper" not in output.split("return {")[1]
        _compile_check(output)

    def test_class_nerve_auto_detects_public_methods(self):
        """Without provides, the dict includes all public methods."""
        mod = _minimal_module(exports=("Svc",))
        nerve = NerveDecl(
            name="Svc",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="A service",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body=(
                "class Svc:\n"
                "    def op_a(self):\n"
                "        pass\n"
                "    def op_b(self):\n"
                "        pass\n"
                "    def _private(self):\n"
                "        pass"
            ),
            location=_loc(5, 12),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        assert '"op_a": instance.op_a' in output
        assert '"op_b": instance.op_b' in output
        assert '"_private"' not in output.split("return {")[1]
        _compile_check(output)

    def test_class_nerve_with_init_params(self):
        """Factory forwards __init__ parameters."""
        mod = _minimal_module(exports=("Svc",))
        nerve = NerveDecl(
            name="Svc",
            layer=Layer.APPLICATION,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="A service with dependencies",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body=(
                "class Svc:\n"
                "    def __init__(self, db, cache):\n"
                "        self.db = db\n"
                "        self.cache = cache\n"
                "    def query(self):\n"
                "        return self.db.query()"
            ),
            location=_loc(5, 12),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        assert "def Svc(db, cache):" in output
        assert "_SvcImpl(db, cache)" in output
        _compile_check(output)

    def test_adapter_class_nerve_compiles(self):
        """An ADAPTER nerve with class body also works."""
        mod = _minimal_module(exports=("LLMAdapter",))
        nerve = NerveDecl(
            name="LLMAdapter",
            layer=Layer.INFRASTRUCTURE,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="LLM adapter",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body=(
                "class LLMAdapter:\n"
                "    def __init__(self, api_key):\n"
                "        self.api_key = api_key\n"
                "    def chat(self, prompt):\n"
                "        return 'response'"
            ),
            location=_loc(5, 12),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        assert "class _LLMAdapterImpl:" in output
        assert "def LLMAdapter(api_key):" in output
        assert "kind=ComponentKind.ADAPTER" in output
        _compile_check(output)

    def test_function_nerve_unchanged(self):
        """Function-based nerves are emitted identically to before."""
        mod = _minimal_module(exports=("my_func",))
        nerve = NerveDecl(
            name="my_func",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="A function",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body="def my_func():\n    return 42",
            location=_loc(5, 8),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        assert "def my_func():" in output
        assert "class " not in output.split("def my_func")[0].split("register_module")[1]
        _compile_check(output)


# ---------------------------------------------------------------------------
# Cell emission tests
# ---------------------------------------------------------------------------


class TestEmitCell:
    """Test cell declaration code generation."""

    def test_model_cell(self):
        mod = _minimal_module(exports=("MyModel",))
        cell = CellDecl(
            name="MyModel",
            layer=Layer.APPLICATION,
            kind=Kind.MODEL,
            visibility=Visibility.PUBLIC,
            intent="A data model",
            schema="Dataclass with name: str",
            body="class MyModel:\n    name: str",
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, cells=(cell,))
        output = emit_python(s0ma_mod)
        _compile_check(output)

        assert "@component(" in output
        assert 'name="MyModel"' in output
        assert "kind=ComponentKind.MODEL" in output
        assert "class MyModel:" in output
        assert "name: str" in output

    def test_constant_cell(self):
        mod = _minimal_module()
        cell = CellDecl(
            name="MAX_VALUE",
            layer=Layer.APPLICATION,
            kind=Kind.CONSTANT,
            visibility=Visibility.INTERNAL,
            intent="Maximum allowed value",
            schema="int constant. Value: 100.",
            body="MAX_VALUE: int = 100",
            location=_loc(5, 8),
        )
        s0ma_mod = S0maModule(module=mod, cells=(cell,))
        output = emit_python(s0ma_mod)
        _compile_check(output)

        assert "MAX_VALUE: int = 100" in output
        assert "register_constant(" in output
        assert 'name="MAX_VALUE"' in output
        # CONSTANT cells use register_constant(), not @component
        # The @component decorator should only appear for non-CONSTANT cells
        # (the decorator for the register_module import section is fine)
        constant_section = output[output.index("MAX_VALUE: int = 100"):]
        assert "@component(" not in constant_section.split("register_constant(")[0]

    def test_enum_cell(self):
        mod = _minimal_module(exports=("Status",))
        cell = CellDecl(
            name="Status",
            layer=Layer.DOMAIN,
            kind=Kind.ENUM,
            visibility=Visibility.PUBLIC,
            intent="Status values",
            schema="Enum with ACTIVE, INACTIVE",
            body="class Status:\n    ACTIVE = 'active'\n    INACTIVE = 'inactive'",
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, cells=(cell,))
        output = emit_python(s0ma_mod)
        _compile_check(output)

        assert "@component(" in output
        assert "kind=ComponentKind.MODEL" in output
        assert '"kind_detail": "ENUM"' in output

    def test_exception_cell(self):
        mod = _minimal_module(exports=("AppError",))
        cell = CellDecl(
            name="AppError",
            layer=Layer.DOMAIN,
            kind=Kind.EXCEPTION,
            visibility=Visibility.PUBLIC,
            intent="Application-level error",
            schema="Exception subclass with message: str",
            body="class AppError(Exception):\n    pass",
            location=_loc(5, 8),
        )
        s0ma_mod = S0maModule(module=mod, cells=(cell,))
        output = emit_python(s0ma_mod)
        _compile_check(output)

        assert "@component(" in output
        assert '"kind_detail": "EXCEPTION"' in output
        assert "class AppError(Exception):" in output

    def test_type_cell(self):
        mod = _minimal_module()
        cell = CellDecl(
            name="UserId",
            layer=Layer.DOMAIN,
            kind=Kind.TYPE,
            visibility=Visibility.INTERNAL,
            intent="Type alias for user identifiers",
            schema="str alias",
            body="UserId = str",
            location=_loc(5, 7),
        )
        s0ma_mod = S0maModule(module=mod, cells=(cell,))
        output = emit_python(s0ma_mod)
        _compile_check(output)

        assert "UserId = str" in output
        assert "register_type(" in output
        assert 'name="UserId"' in output


# ---------------------------------------------------------------------------
# Standalone axon emission tests
# ---------------------------------------------------------------------------


class TestEmitStandaloneAxon:
    """Test standalone axon code generation."""

    def test_standalone_axon(self):
        mod = _minimal_module(
            uses=(UsesEntry(qualified_name="routing.select_evaluator"),),
        )
        axon = StandaloneAxonDecl(
            source="process_signal",
            target="select_evaluator",
            relation=Relation.CALLS,
            intent="Delegates evaluator selection to routing",
            carries="source layer string",
            coupling=Coupling.LOOSE,
            location=_loc(20, 25),
        )
        s0ma_mod = S0maModule(module=mod, axons=(axon,))
        output = emit_python(s0ma_mod)
        _compile_check(output)

        assert "register_relationship(" in output
        assert f'source="{mod.name}::process_signal"' in output
        assert 'target="routing::select_evaluator"' in output
        assert 'relation="CALLS"' in output
        assert 'coupling="LOOSE"' in output

    def test_axon_target_resolution_via_uses(self):
        """Standalone axon target resolves to canonical ID via uses."""
        mod = _minimal_module(
            uses=(UsesEntry(qualified_name="errors.SignalError"),),
        )
        axon = StandaloneAxonDecl(
            source="my_func",
            target="SignalError",
            relation=Relation.CONSTRUCTS,
            intent="Constructs signal error",
            carries="error data",
            coupling=Coupling.TIGHT,
            location=_loc(20, 25),
        )
        s0ma_mod = S0maModule(module=mod, axons=(axon,))
        output = emit_python(s0ma_mod)
        assert 'target="errors::SignalError"' in output


# ---------------------------------------------------------------------------
# Golden fixture test
# ---------------------------------------------------------------------------


class TestGoldenFixture:
    """Test emission of the golden fixture (signal_processor.s0ma)."""

    def test_golden_fixture_compiles(self):
        """The golden fixture transpiles to syntactically valid Python."""
        s0ma_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)
        output = emit_python(module)
        _compile_check(output, str(s0ma_path))

    def test_golden_fixture_has_all(self):
        """__all__ matches exports."""
        s0ma_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)
        output = emit_python(module)
        assert '"process_signal"' in output
        assert '"SignalEnvelope"' in output
        assert "__all__" in output

    def test_golden_fixture_imports(self):
        """Import ordering follows PEP 8."""
        s0ma_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)
        output = emit_python(module)

        # Stdlib imports present
        # Note: parser heuristic sets is_from_import based on capitalization
        # of last segment. uuid.UUID → from-import, dataclasses.dataclass → regular import
        assert "import time" in output
        assert "from uuid import UUID" in output
        assert "dataclasses" in output  # imported (heuristic: lowercase = regular import)

        # s0ma framework imports present
        assert "from s0ma.decorators import component" in output

        # Project imports present (uses entries)
        assert "from routing import select_evaluator" in output
        assert "from errors import SignalValidationError" in output

        # PEP 8 ordering: stdlib → s0ma → project
        stdlib_pos = output.index("import time")
        s0ma_pos = output.index("from s0ma")
        project_pos = output.index("from routing")
        assert stdlib_pos < s0ma_pos < project_pos, "PEP 8 import ordering"

    def test_golden_fixture_nerve_bodies_preserved(self):
        """Body text is preserved in emitted code."""
        s0ma_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)
        output = emit_python(module)

        # Key function definitions present
        assert "def validate_envelope(envelope: SignalEnvelope) -> bool:" in output
        assert "def process_signal(envelope: SignalEnvelope) -> bool:" in output

        # Body logic preserved
        assert 'raise SignalValidationError("Missing required fields")' in output
        assert "validate_envelope(envelope)" in output
        assert "evaluator = select_evaluator(envelope.source)" in output

    def test_golden_fixture_cell_emission(self):
        """Cell declarations emit correctly."""
        s0ma_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)
        output = emit_python(module)

        # MODEL cell with @component
        assert 'name="SignalEnvelope"' in output
        assert "class SignalEnvelope:" in output

        # CONSTANT cell with register_constant
        assert "MAX_STALENESS_SECONDS" in output
        assert "register_constant(" in output

    def test_golden_fixture_standalone_axon(self):
        """Standalone axon emits register_relationship()."""
        s0ma_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)
        output = emit_python(module)

        assert "register_relationship(" in output
        assert 'source="signal_processor::process_signal"' in output
        assert 'target="routing::select_evaluator"' in output

    def test_golden_fixture_component_decorators(self):
        """@component decorators include all metadata."""
        s0ma_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)
        output = emit_python(module)

        # Nerves have kind, intent, contracts
        assert "kind=ComponentKind.FUNCTION" in output  # validate_envelope
        assert "kind=ComponentKind.ORCHESTRATOR" in output  # process_signal
        assert "contracts=Contract(" in output

        # Dependencies
        assert 'dependencies=["MAX_STALENESS_SECONDS"]' in output  # validate_envelope
        assert 'dependencies=["validate_envelope"]' in output  # process_signal


# ---------------------------------------------------------------------------
# Multi-module fixture test
# ---------------------------------------------------------------------------


class TestMultiModuleFixture:
    """Test emission of multi-module fixtures."""

    def test_models_module_compiles(self):
        s0ma_path = VALID_FIXTURES_DIR / "multi_module" / "models.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)
        output = emit_python(module)
        _compile_check(output)

    def test_routing_module_compiles(self):
        s0ma_path = VALID_FIXTURES_DIR / "multi_module" / "routing.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)
        output = emit_python(module)
        _compile_check(output)
        # Verify uses import
        assert "from processing import process_user" in output
        assert "from models import UserModel" in output


# ---------------------------------------------------------------------------
# Determinism test
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Verify deterministic output across repeated emissions."""

    def test_repeated_emission_identical(self):
        """Same input produces identical output on repeated runs."""
        s0ma_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source = s0ma_path.read_text()
        module = parse_s0ma(source, str(s0ma_path), StrictnessMode.DEV)

        output1 = emit_python(module)
        output2 = emit_python(module)
        output3 = emit_python(module)

        assert output1 == output2 == output3, "Output must be deterministic"


# ---------------------------------------------------------------------------
# Convenience function test
# ---------------------------------------------------------------------------


class TestConvenienceFunction:
    """Test the emit_python() convenience function."""

    def test_emit_python_matches_emitter(self):
        mod = _minimal_module(name="conv_test", exports=("foo",))
        nerve = NerveDecl(
            name="foo",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="Convenience test function",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body="def foo():\n    return 42",
            location=_loc(5, 8),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))

        func_output = emit_python(s0ma_mod)
        emitter = PythonEmitter()
        class_output = emitter.emit(s0ma_mod)

        assert func_output == class_output


# ---------------------------------------------------------------------------
# Provides field emission
# ---------------------------------------------------------------------------


class TestProvidesEmission:
    """Tests for provides field in @component metadata."""

    def test_provides_in_metadata(self) -> None:
        mod = ModuleDecl(
            name="svc_mod",
            layer=Layer.DOMAIN,
            version="1.0.0",
            intent="Service module",
            exports=("FileService",),
            location=_loc(),
        )
        nerve = NerveDecl(
            name="FileService",
            layer=Layer.DOMAIN,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="File operations service",
            expects="path exists",
            guarantees="returns content",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            provides=("read_file", "write_file"),
            body="def FileService():\n    pass",
            location=_loc(5, 10),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)

        assert '"provides": ["read_file", "write_file"]' in output
        compile(output, "<test>", "exec")

    def test_provides_absent_not_in_metadata(self) -> None:
        mod = ModuleDecl(
            name="svc_mod",
            layer=Layer.DOMAIN,
            version="1.0.0",
            intent="Service module",
            exports=("fn",),
            location=_loc(),
        )
        nerve = NerveDecl(
            name="fn",
            layer=Layer.DOMAIN,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="A plain function",
            expects="none",
            guarantees="none",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body="def fn():\n    pass",
            location=_loc(5, 8),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)

        assert '"provides"' not in output


# ---------------------------------------------------------------------------
# Soft requires emission
# ---------------------------------------------------------------------------


class TestSoftRequiresEmission:
    """Tests for soft_requires try/except import emission."""

    def test_soft_requires_emits_try_except(self) -> None:
        mod = ModuleDecl(
            name="soft_mod",
            layer=Layer.DOMAIN,
            version="1.0.0",
            intent="Module with soft requires",
            exports=(),
            soft_requires=(
                RequiresEntry(module_path="anthropic"),
            ),
            location=_loc(),
        )
        s0ma_mod = S0maModule(module=mod)
        output = emit_python(s0ma_mod)

        assert "try:\n    import anthropic\nexcept ImportError:\n    anthropic = None" in output
        compile(output, "<test>", "exec")

    def test_soft_requires_from_import(self) -> None:
        mod = ModuleDecl(
            name="soft_mod",
            layer=Layer.DOMAIN,
            version="1.0.0",
            intent="Module with from-import soft requires",
            exports=(),
            soft_requires=(
                RequiresEntry(
                    module_path="unittest.mock.patch",
                    is_from_import=True,
                ),
            ),
            location=_loc(),
        )
        s0ma_mod = S0maModule(module=mod)
        output = emit_python(s0ma_mod)

        expected = (
            "try:\n    from unittest.mock import patch\n"
            "except ImportError:\n    patch = None"
        )
        assert expected in output
        compile(output, "<test>", "exec")

    def test_soft_requires_with_alias(self) -> None:
        mod = ModuleDecl(
            name="soft_mod",
            layer=Layer.DOMAIN,
            version="1.0.0",
            intent="Module with aliased soft requires",
            exports=(),
            soft_requires=(
                RequiresEntry(module_path="anthropic", alias="ant"),
            ),
            location=_loc(),
        )
        s0ma_mod = S0maModule(module=mod)
        output = emit_python(s0ma_mod)

        assert "try:\n    import anthropic as ant\nexcept ImportError:\n    ant = None" in output
        compile(output, "<test>", "exec")


# ===========================================================================
# MS 11: Abstract nerve emission
# ===========================================================================


class TestAbstractNerveEmission:
    """Verify abstract nerves emit correctly."""

    def test_abstract_nerve_generates_stubs(self) -> None:
        """Abstract nerve with interface and no body generates NotImplementedError stubs."""
        mod = _minimal_module(exports=("LLMAdapter",))
        nerve = NerveDecl(
            name="LLMAdapter",
            layer=Layer.INFRASTRUCTURE,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="Abstract LLM adapter interface",
            expects="None",
            guarantees="Subclasses implement chat and chat_stream",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            abstract=True,
            interface=("chat", "chat_stream"),
            body=None,
            location=_loc(10, 20),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)

        assert "NotImplementedError" in output
        assert "def chat(" in output
        assert "def chat_stream(" in output
        # F7: must be Python ``True`` (not JSON ``true``) so the emitted
        # module imports without NameError.
        assert '"abstract": True' in output
        assert '"abstract": true' not in output
        assert '"interface": ["chat", "chat_stream"]' in output
        compile(output, "<test>", "exec")

    def test_abstract_nerve_with_explicit_body(self) -> None:
        """Abstract nerve with user-provided body uses that body as-is."""
        mod = _minimal_module(exports=("LLMAdapter",))
        nerve = NerveDecl(
            name="LLMAdapter",
            layer=Layer.INFRASTRUCTURE,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="Abstract LLM adapter",
            expects="None",
            guarantees="Subclasses implement methods",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            abstract=True,
            interface=("chat",),
            body=(
                "def LLMAdapter():\n"
                "    def chat():\n"
                "        raise NotImplementedError('chat')\n"
                "    return {'chat': chat}"
            ),
            location=_loc(10, 20),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)

        assert "raise NotImplementedError" in output
        # F7: emit Python ``True``, not JSON ``true``.
        assert '"abstract": True' in output
        assert '"abstract": true' not in output
        compile(output, "<test>", "exec")

    def test_non_abstract_nerve_no_abstract_metadata(self) -> None:
        """Non-abstract nerve should not have abstract metadata."""
        mod = _minimal_module(exports=("MyFunc",))
        nerve = NerveDecl(
            name="MyFunc",
            layer=Layer.DOMAIN,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="Regular nerve",
            expects="None",
            guarantees="Returns result",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            abstract=False,
            body="def MyFunc():\n    return 42",
            location=_loc(10, 15),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)

        assert '"abstract"' not in output
        compile(output, "<test>", "exec")

    def test_abstract_nerve_emitted_python_imports_cleanly(
        self, tmp_path
    ) -> None:
        """F7 regression: emitted Python for abstract nerves must import.

        ``compile()`` only checks syntax. Bare ``true`` is a valid Python
        identifier, so the previous JSON-style emission slipped through
        compile() but raised ``NameError: name 'true' is not defined`` the
        moment any caller imported the module. This test exercises the full
        import path (``importlib.util.spec_from_file_location`` +
        ``loader.exec_module``) and asserts that the emitted ``metadata``
        dict contains the Python boolean ``True``.

        Reported by fr3d adoption cycle: see fr3d/docs/s0ma-dsl-feedback-7.md
        finding #1.
        """
        import importlib.util
        import sys

        mod = _minimal_module(exports=("LLMAdapter",))
        nerve = NerveDecl(
            name="LLMAdapter",
            layer=Layer.INFRASTRUCTURE,
            kind=Kind.ADAPTER,
            visibility=Visibility.PUBLIC,
            intent="Abstract LLM adapter interface",
            expects="None",
            guarantees="Subclasses implement chat",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            abstract=True,
            interface=("chat",),
            body=None,
            location=_loc(10, 20),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)

        # The emitted Python source must use the Python boolean literal
        # ``True`` (capitalized) rather than the JSON-style ``true``.
        assert '"abstract": True' in output
        assert '"abstract": true' not in output

        # Stronger assertion: the module imports without raising.
        # Pre-fix this would raise NameError on the metadata dict.
        out_path = tmp_path / "emitted_module.py"
        out_path.write_text(output, encoding="utf-8")

        spec = importlib.util.spec_from_file_location(
            "f7_emitted_module", str(out_path)
        )
        assert spec is not None
        assert spec.loader is not None
        loaded = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(loaded)
        finally:
            sys.modules.pop("f7_emitted_module", None)


# ===========================================================================
# MS 11: Returns metadata emission
# ===========================================================================


class TestReturnsEmission:
    """Verify returns field appears in emitted metadata."""

    def test_returns_in_metadata(self) -> None:
        mod = _minimal_module(exports=("MySvc",))
        nerve = NerveDecl(
            name="MySvc",
            layer=Layer.DOMAIN,
            kind=Kind.SERVICE,
            visibility=Visibility.PUBLIC,
            intent="Service with returns",
            expects="None",
            guarantees="Returns dict",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            returns=("op_a", "op_b"),
            body=(
                'def MySvc():\n'
                '    def op_a(): pass\n'
                '    def op_b(): pass\n'
                '    return {"op_a": op_a, "op_b": op_b}'
            ),
            location=_loc(10, 20),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)

        assert '"returns": ["op_a", "op_b"]' in output
        compile(output, "<test>", "exec")

    def test_empty_returns_not_in_metadata(self) -> None:
        mod = _minimal_module(exports=("MyFunc",))
        nerve = NerveDecl(
            name="MyFunc",
            layer=Layer.DOMAIN,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="Nerve without returns",
            expects="None",
            guarantees="Returns result",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            returns=(),
            body="def MyFunc():\n    return 42",
            location=_loc(10, 15),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)

        assert '"returns"' not in output
        compile(output, "<test>", "exec")


# ---------------------------------------------------------------------------
# MS 5b: Hash embedding tests
# ---------------------------------------------------------------------------


class TestHashEmbedding:
    """Tests for s0ma-source-hash / s0ma-output-hash embedding in emitted Python."""

    def test_header_contains_hash_placeholders(self) -> None:
        """Emitted header includes hash placeholder lines."""
        mod = _minimal_module(exports=("greet",))
        nerve = NerveDecl(
            name="greet",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="Say hello",
            expects="name: str",
            guarantees="Returns a greeting",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body="def greet(name: str) -> str:\n    return f'Hello, {name}!'",
            location=_loc(10, 15),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)

        # Before inject_hashes, placeholders should be present
        assert "# s0ma-source-hash: __S0MA_SOURCE_HASH__" in output
        assert "# s0ma-output-hash: __S0MA_OUTPUT_HASH__" in output

    def test_inject_hashes_replaces_placeholders(self) -> None:
        """inject_hashes replaces placeholders with actual SHA-256 hashes."""
        from s0ma_dsl.codegen.python_emitter import inject_hashes

        mod = _minimal_module(exports=("greet",))
        nerve = NerveDecl(
            name="greet",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="Say hello",
            expects="name: str",
            guarantees="Returns a greeting",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body="def greet(name: str) -> str:\n    return f'Hello, {name}!'",
            location=_loc(10, 15),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)

        source_text = "module test_mod\n    layer: APPLICATION\n"
        result = inject_hashes(output, source_text)

        # Placeholders should be gone
        assert "__S0MA_SOURCE_HASH__" not in result
        assert "__S0MA_OUTPUT_HASH__" not in result

        # Actual hashes should be present
        assert "# s0ma-source-hash: sha256:" in result
        assert "# s0ma-output-hash: sha256:" in result

        # Hashes should be 16 hex characters
        import re
        source_match = re.search(r"# s0ma-source-hash: sha256:([0-9a-f]+)", result)
        output_match = re.search(r"# s0ma-output-hash: sha256:([0-9a-f]+)", result)
        assert source_match is not None
        assert output_match is not None
        assert len(source_match.group(1)) == 16
        assert len(output_match.group(1)) == 16

        # Result should still be valid Python
        _compile_check(result)

    def test_inject_hashes_deterministic(self) -> None:
        """Same input produces same hashes."""
        from s0ma_dsl.codegen.python_emitter import inject_hashes

        mod = _minimal_module(exports=("greet",))
        nerve = NerveDecl(
            name="greet",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="Say hello",
            expects="name: str",
            guarantees="Returns a greeting",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body="def greet(name: str) -> str:\n    return f'Hello, {name}!'",
            location=_loc(10, 15),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)
        source_text = "module test_mod\n    layer: APPLICATION\n"

        result1 = inject_hashes(output, source_text)
        result2 = inject_hashes(output, source_text)
        assert result1 == result2

    def test_different_source_produces_different_source_hash(self) -> None:
        """Different .s0ma content produces different source hash."""
        import re

        from s0ma_dsl.codegen.python_emitter import inject_hashes

        mod = _minimal_module(exports=("greet",))
        nerve = NerveDecl(
            name="greet",
            layer=Layer.APPLICATION,
            kind=Kind.FUNCTION,
            visibility=Visibility.PUBLIC,
            intent="Say hello",
            expects="name: str",
            guarantees="Returns a greeting",
            evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
            body="def greet(name: str) -> str:\n    return f'Hello, {name}!'",
            location=_loc(10, 15),
        )
        s0ma_mod = S0maModule(module=mod, nerves=(nerve,))
        output = emit_python(s0ma_mod)

        result_a = inject_hashes(output, "source version A")
        result_b = inject_hashes(output, "source version B")

        hash_a = re.search(r"# s0ma-source-hash: sha256:(\w+)", result_a).group(1)
        hash_b = re.search(r"# s0ma-source-hash: sha256:(\w+)", result_b).group(1)
        assert hash_a != hash_b
