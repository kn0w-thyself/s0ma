"""Tests for POST-4 helper-declaration improvements (s0ma-dsl 0.15.0, M-7).

POST-4 bundles three independent helper-grammar enrichments under a
single minor release surface:

- **POST-4a** — ``helper`` accepts class bodies, not just ``def``. The
  body extractor's classification routes through a helper-specific
  validator that accepts both ``BodyType.FUNCTION`` and
  ``BodyType.CLASS``. Class-bodied helpers retire the legacy
  ``cell kind: MODEL visibility: INTERNAL`` workaround that routed
  module-private classes through the registry.

- **POST-4b** — ``helper @inline`` shorthand. The module header's
  ``helpers:`` block list accepts inline-helper entries shaped as
  ``- helper _name @inline: "intent" :: def _name(...): body``.
  Inline helpers parse to :class:`HelperDecl` with ``inline=True``
  and ``body_kind="function"``.

- **POST-4c** — ``exports_helpers:`` module-header field. Lets a
  module declare which of its helpers are intentionally reachable
  across module boundaries. The M13 access-control rule (test-context
  consumers only) still applies — ``exports_helpers:`` widens
  reachability, not access control. The validator fires
  ``EXPORTED_HELPER_NOT_FOUND`` when an entry doesn't resolve to an
  actual helper declaration in the same module.

These tests pin the three sub-features against the parser, validator,
codegen, IR, and dependency resolver. They share the existing
``tests/fixtures/helper_improvements/`` fixture tree.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.ast_nodes.nodes import HelperDecl, ModuleDecl, S0maModule
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.resolver.dependency import DependencyResolver
from s0ma_dsl.semantic.validator import validate_module

if TYPE_CHECKING:
    from s0ma_dsl.errors import S0maError

_FIXTURES = Path(__file__).parent / "fixtures" / "helper_improvements"


def _parse(source: str, filename: str = "<string>") -> S0maModule:
    """Parse a .s0ma source string in strict mode and return the AST."""
    module, _warnings = parse_s0ma_with_warnings(
        source, filename, mode=StrictnessMode.STRICT,
    )
    return module


def _load_project(fixture_dir: Path) -> tuple[
    dict[str, S0maModule], dict[str, str]
]:
    """Parse every ``.s0ma`` file under ``fixture_dir`` into a project view."""
    modules: dict[str, S0maModule] = {}
    filenames: dict[str, str] = {}
    for s0ma_path in sorted(fixture_dir.rglob("*.s0ma")):
        source = s0ma_path.read_text(encoding="utf-8")
        module, _warnings = parse_s0ma_with_warnings(
            source, str(s0ma_path), mode=StrictnessMode.STRICT,
        )
        modules[module.module.name] = module
        filenames[module.module.name] = str(s0ma_path)
    return modules, filenames


def _resolve(
    fixture_dir: Path, mode: StrictnessMode = StrictnessMode.STRICT,
) -> list[S0maError]:
    """Run the cross-module dependency resolver against a fixture project."""
    modules, filenames = _load_project(fixture_dir)
    resolver = DependencyResolver(mode=mode)
    return resolver.resolve(modules, filenames=filenames, check_imports=False)


# ---------------------------------------------------------------------------
# POST-4a — Class-bodied helpers
# ---------------------------------------------------------------------------


class TestClassBodiedHelpers:
    """POST-4a: ``helper`` accepts class definitions as bodies."""

    def test_class_bodied_helper_parses(self) -> None:
        """A helper whose body is ``class X:`` parses to ``HelperDecl``."""
        source = (
            'module test_class_helper\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Class-bodied helper."\n'
            '    exports: []\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: none\n'
            '\n'
            'helper _Cache :: APPLICATION\n'
            '    intent: "Module-private cache."\n'
            '    ---\n'
            '    class _Cache:\n'
            '        def __init__(self):\n'
            '            self._data = {}\n'
            '        def get(self, key):\n'
            '            return self._data.get(key)\n'
        )
        module = _parse(source)
        assert len(module.helpers) == 1
        helper = module.helpers[0]
        assert isinstance(helper, HelperDecl)
        assert helper.name == "_Cache"
        assert helper.body_kind == "class"
        assert helper.inline is False
        assert "class _Cache" in (helper.body or "")

    def test_class_bodied_helper_records_class_kind_in_ast(self) -> None:
        """``HelperDecl.body_kind`` is ``"class"`` for a class body."""
        module = _load_project(_FIXTURES / "class_body")[0]["prompt_formatter"]
        helper = next(h for h in module.helpers if h.name == "_LocalCache")
        assert helper.body_kind == "class"

    def test_function_bodied_helper_keeps_function_body_kind(self) -> None:
        """Function-bodied helpers continue to record ``body_kind=="function"``."""
        # Re-use the original helper_declarations fixture which carries
        # function-bodied helpers — pin that the M13 default still
        # records ``"function"`` as the canonical body_kind value.
        clean_dir = (
            Path(__file__).parent / "fixtures" / "helper_declarations" / "clean"
        )
        modules, _ = _load_project(clean_dir)
        event_builder = modules["event_builder"]
        for helper in event_builder.helpers:
            assert helper.body_kind == "function", (
                f"helper {helper.name!r} unexpectedly carries "
                f"body_kind={helper.body_kind!r}"
            )

    def test_class_bodied_helper_emits_plain_class(self, tmp_path: Path) -> None:
        """Codegen emits class-bodied helpers as ``class X:`` (no decorator)."""
        from s0ma_dsl.cli.main import S0maCLI

        fixture_dir = _FIXTURES / "class_body"
        build_dir = tmp_path / "build"
        cli = S0maCLI()
        rc = cli.run([
            "build",
            str(fixture_dir / "src" / "sample"),
            "--output-dir", str(build_dir),
        ])
        assert rc == 0, "build must succeed"

        py_path = build_dir / "prompt_formatter.py"
        assert py_path.exists(), f"emitted .py not found at {py_path}"
        py_content = py_path.read_text(encoding="utf-8")

        # The class-bodied helper appears as a plain top-level ``class``.
        assert "class _LocalCache:" in py_content

        # No @component decorator and no register_helper call.
        assert "register_helper(" not in py_content
        # No decorator immediately above the class — the body is anchored
        # by the ``# Helper:`` comment, with the 0.13.0 M3 ``# s0ma:``
        # source pointer sitting between that anchor and the class.
        cls_idx = py_content.index("class _LocalCache:")
        prefix_lines = py_content[:cls_idx].rstrip().split("\n")
        assert prefix_lines[-1].startswith("# s0ma:"), (
            f"class-bodied helper must be preceded by its M3 source "
            f"pointer; got preceding line: {prefix_lines[-1]!r}"
        )
        assert prefix_lines[-2].startswith("# Helper:"), (
            f"class-bodied helper must be anchored by a '# Helper:' "
            f"comment; got line above the pointer: {prefix_lines[-2]!r}"
        )

    def test_class_bodied_helper_no_register_call(
        self, tmp_path: Path,
    ) -> None:
        """Regression: class-bodied helpers do NOT route through the registry.

        The motivating fix is to retire the
        ``cell kind: MODEL visibility: INTERNAL`` workaround that
        previously routed module-private classes through the registry.
        Pin that no ``@component`` decorator and no ``register_*``
        call land near the helper's body.
        """
        from s0ma_dsl.cli.main import S0maCLI

        fixture_dir = _FIXTURES / "class_body"
        build_dir = tmp_path / "build"
        cli = S0maCLI()
        rc = cli.run([
            "build",
            str(fixture_dir / "src" / "sample"),
            "--output-dir", str(build_dir),
        ])
        assert rc == 0

        py_content = (build_dir / "prompt_formatter.py").read_text(
            encoding="utf-8",
        )

        # The class is in the file but is NOT referenced by any
        # registration call. The helper name must not appear inside
        # any register_* invocation argument.
        for register_fn in (
            "register_constant", "register_type", "register_model",
            "register_helper",
        ):
            # The function may not even appear in the emitted file —
            # that's fine. If it does, the helper class name must not
            # show up as an argument to it.
            for line in py_content.split("\n"):
                if register_fn in line:
                    assert "_LocalCache" not in line, (
                        f"class-bodied helper unexpectedly routed "
                        f"through {register_fn}: {line!r}"
                    )

    def test_class_bodied_helper_appears_in_inspect(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path,
    ) -> None:
        """``s0ma inspect`` lists the class-bodied helper in [helpers]."""
        from s0ma_dsl.cli.main import S0maCLI

        fixture_dir = _FIXTURES / "class_body"
        build_dir = tmp_path / "build"
        cli = S0maCLI()
        rc = cli.run([
            "build",
            str(fixture_dir / "src" / "sample"),
            "--output-dir", str(build_dir),
        ])
        capsys.readouterr()
        assert rc == 0

        ir_path = build_dir / "prompt_formatter.s0ma.json"
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        helpers = {h["name"]: h for h in ir.get("helpers", [])}
        assert "_LocalCache" in helpers
        assert helpers["_LocalCache"]["body_kind"] == "class"

        # s0ma inspect output mentions the helper.
        rc_inspect = cli.run(["inspect", str(ir_path)])
        captured = capsys.readouterr()
        assert rc_inspect == 0
        assert "prompt_formatter::_LocalCache [helper]" in captured.out


# ---------------------------------------------------------------------------
# POST-4b — ``@inline`` shorthand
# ---------------------------------------------------------------------------


class TestInlineHelpers:
    """POST-4b: helpers may be declared inline inside the module header."""

    def test_single_inline_helper_parses(self) -> None:
        """A single ``- helper _name @inline: ... :: ...`` parses."""
        source = (
            'module inline_test\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Module with one inline helper."\n'
            '    exports: [main]\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: none\n'
            '    helpers:\n'
            '      - helper _add @inline: "Add two numbers" '
            ':: def _add(a, b): return a + b\n'
            '\n'
            'nerve main :: APPLICATION\n'
            '    kind: FUNCTION\n'
            '    visibility: PUBLIC\n'
            '    intent: "Main entry point."\n'
            '    expects: "Two numbers."\n'
            '    guarantees: "Returns the sum."\n'
            '    forbids: none\n'
            '    evaluates_at: FUNCTION_BOUNDARY\n'
            '    provides: none\n'
            '    returns: none\n'
            '    raises: none\n'
            '    interface: none\n'
            '    latency_ms: none\n'
            '    depends_on: none\n'
            '    internal: none\n'
            '    expected_exceptions: none\n'
            '    consumes_via_dict: none\n'
            '    declares_attributes: none\n'
            '    covered_by: none\n'
            '    ---\n'
            '    def main(a, b):\n'
            '        return _add(a, b)\n'
        )
        module = _parse(source)
        assert len(module.helpers) == 1
        helper = module.helpers[0]
        assert helper.name == "_add"
        assert helper.intent == "Add two numbers"
        assert helper.inline is True
        assert helper.body_kind == "function"
        assert helper.body is not None
        assert "def _add(a, b)" in helper.body

    def test_multiple_inline_helpers_parse(self) -> None:
        """Multiple inline helpers all parse with the right shapes."""
        source = (
            'module multi_inline\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Module with several inline helpers."\n'
            '    exports: [main]\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: none\n'
            '    helpers:\n'
            '      - helper _add @inline: "Quick addition" '
            ':: def _add(a, b): return a + b\n'
            '      - helper _mul @inline: "Quick multiplication" '
            ':: def _mul(a, b): return a * b\n'
            '      - helper _sub @inline: "Quick subtraction" '
            ':: def _sub(a, b): return a - b\n'
            '\n'
            'nerve main :: APPLICATION\n'
            '    kind: FUNCTION\n'
            '    visibility: PUBLIC\n'
            '    intent: "Main entry point."\n'
            '    expects: "Two numbers."\n'
            '    guarantees: "Returns aggregate ops."\n'
            '    forbids: none\n'
            '    evaluates_at: FUNCTION_BOUNDARY\n'
            '    provides: none\n'
            '    returns: none\n'
            '    raises: none\n'
            '    interface: none\n'
            '    latency_ms: none\n'
            '    depends_on: none\n'
            '    internal: none\n'
            '    expected_exceptions: none\n'
            '    consumes_via_dict: none\n'
            '    declares_attributes: none\n'
            '    covered_by: none\n'
            '    ---\n'
            '    def main(a, b):\n'
            '        return _add(a, b), _mul(a, b), _sub(a, b)\n'
        )
        module = _parse(source)
        assert len(module.helpers) == 3
        names = {h.name for h in module.helpers}
        assert names == {"_add", "_mul", "_sub"}
        for helper in module.helpers:
            assert helper.inline is True
            assert helper.body_kind == "function"

    def test_inline_and_block_helpers_coexist(self) -> None:
        """A module may declare both inline and block-form helpers."""
        source = (
            'module mixed_forms\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Module with both inline and block helpers."\n'
            '    exports: [main]\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: none\n'
            '    helpers:\n'
            '      - helper _add @inline: "Quick addition" '
            ':: def _add(a, b): return a + b\n'
            '\n'
            'helper _multiply :: APPLICATION\n'
            '    intent: "Block-form multiplier."\n'
            '    ---\n'
            '    def _multiply(a, b):\n'
            '        return a * b\n'
            '\n'
            'nerve main :: APPLICATION\n'
            '    kind: FUNCTION\n'
            '    visibility: PUBLIC\n'
            '    intent: "Main entry point."\n'
            '    expects: "Two numbers."\n'
            '    guarantees: "Returns sum and product."\n'
            '    forbids: none\n'
            '    evaluates_at: FUNCTION_BOUNDARY\n'
            '    provides: none\n'
            '    returns: none\n'
            '    raises: none\n'
            '    interface: none\n'
            '    latency_ms: none\n'
            '    depends_on: none\n'
            '    internal: none\n'
            '    expected_exceptions: none\n'
            '    consumes_via_dict: none\n'
            '    declares_attributes: none\n'
            '    covered_by: none\n'
            '    ---\n'
            '    def main(a, b):\n'
            '        return _add(a, b), _multiply(a, b)\n'
        )
        module = _parse(source)
        assert len(module.helpers) == 2
        by_name = {h.name: h for h in module.helpers}
        assert by_name["_add"].inline is True
        assert by_name["_multiply"].inline is False
        assert by_name["_add"].body_kind == "function"
        assert by_name["_multiply"].body_kind == "function"

    def test_inline_helper_emits_plain_def(self, tmp_path: Path) -> None:
        """Codegen emits the inline helper as a plain top-level ``def``."""
        from s0ma_dsl.cli.main import S0maCLI

        source = (
            'module inline_emit\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Inline-helper emit test."\n'
            '    exports: [main]\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: none\n'
            '    helpers:\n'
            '      - helper _add @inline: "Quick addition" '
            ':: def _add(a, b): return a + b\n'
            '\n'
            'nerve main :: APPLICATION\n'
            '    kind: FUNCTION\n'
            '    visibility: PUBLIC\n'
            '    intent: "Main entry."\n'
            '    expects: "Two numbers."\n'
            '    guarantees: "Sum."\n'
            '    forbids: none\n'
            '    evaluates_at: FUNCTION_BOUNDARY\n'
            '    provides: none\n'
            '    returns: none\n'
            '    raises: none\n'
            '    interface: none\n'
            '    latency_ms: none\n'
            '    depends_on: none\n'
            '    internal: none\n'
            '    expected_exceptions: none\n'
            '    consumes_via_dict: none\n'
            '    declares_attributes: none\n'
            '    covered_by: none\n'
            '    ---\n'
            '    def main(a, b):\n'
            '        return _add(a, b)\n'
        )
        src_dir = tmp_path / "src" / "sample"
        src_dir.mkdir(parents=True)
        (src_dir / "inline_emit.s0ma").write_text(source, encoding="utf-8")

        build_dir = tmp_path / "build"
        cli = S0maCLI()
        rc = cli.run([
            "build", str(src_dir), "--output-dir", str(build_dir),
        ])
        assert rc == 0

        py_content = (build_dir / "inline_emit.py").read_text(
            encoding="utf-8",
        )
        assert "def _add(a, b)" in py_content
        # No register_helper call.
        assert "register_helper(" not in py_content
        # No @component decorator above the def — the ``# Helper:`` anchor
        # (with the 0.13.0 M3 ``# s0ma:`` pointer between it and the def).
        def_idx = py_content.index("def _add(")
        prefix_lines = py_content[:def_idx].rstrip().split("\n")
        assert prefix_lines[-1].startswith("# s0ma:")
        assert prefix_lines[-2].startswith("# Helper:")

    def test_inline_helper_duplicate_name_errors(self) -> None:
        """Two inline helpers with the same name raise ``PARSE_ERROR``."""
        from s0ma_dsl.errors import S0maParseError

        source = (
            'module dup_inline\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Duplicate inline names."\n'
            '    exports: []\n'
            '    exports_helpers: none\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    helpers:\n'
            '      - helper _add @inline: "First" '
            ':: def _add(a, b): return a + b\n'
            '      - helper _add @inline: "Second" '
            ':: def _add(x, y): return x + y\n'
        )
        with pytest.raises(S0maParseError) as excinfo:
            _parse(source)
        assert excinfo.value.code == "PARSE_ERROR"
        assert "duplicate" in excinfo.value.message.lower()


# ---------------------------------------------------------------------------
# POST-4c — ``exports_helpers:`` field
# ---------------------------------------------------------------------------


class TestExportsHelpersField:
    """POST-4c: module header may list helpers for cross-module reach."""

    def test_exports_helpers_inline_form_parses(self) -> None:
        """``exports_helpers: [_a, _b]`` parses to a tuple."""
        source = (
            'module exp_inline\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Inline-form exports_helpers."\n'
            '    exports: [main]\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: [_compare]\n'
            '\n'
            'helper _compare :: APPLICATION\n'
            '    intent: "Compare two values."\n'
            '    ---\n'
            '    def _compare(a, b):\n'
            '        return a == b\n'
            '\n'
            'nerve main :: APPLICATION\n'
            '    kind: FUNCTION\n'
            '    visibility: PUBLIC\n'
            '    intent: "Main entry."\n'
            '    expects: "Two values."\n'
            '    guarantees: "Returns bool."\n'
            '    forbids: none\n'
            '    evaluates_at: FUNCTION_BOUNDARY\n'
            '    provides: none\n'
            '    returns: none\n'
            '    raises: none\n'
            '    interface: none\n'
            '    latency_ms: none\n'
            '    depends_on: none\n'
            '    internal: none\n'
            '    expected_exceptions: none\n'
            '    consumes_via_dict: none\n'
            '    declares_attributes: none\n'
            '    covered_by: none\n'
            '    ---\n'
            '    def main(a, b):\n'
            '        return _compare(a, b)\n'
        )
        module = _parse(source)
        assert module.module.exports_helpers == ("_compare",)

    def test_exports_helpers_block_form_parses(self) -> None:
        """``exports_helpers:`` block-list form (PRE-7) parses."""
        source = (
            'module exp_block\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Block-form exports_helpers."\n'
            '    exports: [main]\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers:\n'
            '      - _compare\n'
            '      - _render\n'
            '\n'
            'helper _compare :: APPLICATION\n'
            '    intent: "Compare."\n'
            '    ---\n'
            '    def _compare(a, b):\n'
            '        return a == b\n'
            '\n'
            'helper _render :: APPLICATION\n'
            '    intent: "Render."\n'
            '    ---\n'
            '    def _render(x):\n'
            '        return str(x)\n'
            '\n'
            'nerve main :: APPLICATION\n'
            '    kind: FUNCTION\n'
            '    visibility: PUBLIC\n'
            '    intent: "Main entry."\n'
            '    expects: "A value."\n'
            '    guarantees: "String."\n'
            '    forbids: none\n'
            '    evaluates_at: FUNCTION_BOUNDARY\n'
            '    provides: none\n'
            '    returns: none\n'
            '    raises: none\n'
            '    interface: none\n'
            '    latency_ms: none\n'
            '    depends_on: none\n'
            '    internal: none\n'
            '    expected_exceptions: none\n'
            '    consumes_via_dict: none\n'
            '    declares_attributes: none\n'
            '    covered_by: none\n'
            '    ---\n'
            '    def main(x):\n'
            '        return _render(x)\n'
        )
        module = _parse(source)
        assert module.module.exports_helpers == ("_compare", "_render")

    def test_exports_helpers_absent_defaults_to_empty(self) -> None:
        """Modules without ``exports_helpers:`` have an empty tuple."""
        source = (
            'module no_exports_helpers\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Module without exports_helpers."\n'
            '    exports: []\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: none\n'
        )
        module = _parse(source)
        assert module.module.exports_helpers == ()

    def test_re_exported_helper_in_all(self, tmp_path: Path) -> None:
        """``exports_helpers:`` entries appear in the emitted ``__all__``."""
        from s0ma_dsl.cli.main import S0maCLI

        fixture_dir = _FIXTURES / "exports_clean"
        build_dir = tmp_path / "build"
        cli = S0maCLI()
        rc = cli.run([
            "build",
            str(fixture_dir / "src" / "sample"),
            "--output-dir", str(build_dir),
        ])
        assert rc == 0, "fixture build must succeed"

        py_content = (build_dir / "shared_utils.py").read_text(
            encoding="utf-8",
        )
        # The re-exported helper names appear in __all__.
        assert '"_compare"' in py_content
        assert '"_render_markdown"' in py_content
        # The regular export is also in __all__.
        assert '"render_attendee"' in py_content

    def test_test_context_module_can_consume_re_exported_helper(self) -> None:
        """A test module reaches a re-exported helper via ``uses:`` cleanly."""
        diagnostics = _resolve(_FIXTURES / "exports_clean")
        # No HELPER_PRIVATE_TO_MODULE — the consumer is test-context.
        helper_violations = [
            d for d in diagnostics if d.code == "HELPER_PRIVATE_TO_MODULE"
        ]
        assert helper_violations == [], (
            f"test-context consumer must not hit HELPER_PRIVATE_TO_MODULE; "
            f"got: {[(d.code, d.message) for d in helper_violations]}"
        )
        # No NOT_EXPORTED either — helpers are not in the regular
        # ``exports:`` set but are reachable through the re-export path.
        not_exported = [
            d for d in diagnostics
            if d.code == "NOT_EXPORTED"
            and (d.context or {}).get("target_component", "").startswith("_")
        ]
        assert not_exported == [], (
            f"helpers must not trigger NOT_EXPORTED; "
            f"got: {[(d.code, d.message) for d in not_exported]}"
        )

    def test_production_module_still_blocked_for_re_exported_helper(
        self,
    ) -> None:
        """Production consumer still hits HELPER_PRIVATE_TO_MODULE.

        ``exports_helpers:`` widens reachability but NOT access
        control. A production module (no ``test`` declarations) that
        imports a re-exported helper must still hit the M13
        access-control rule.
        """
        diagnostics = _resolve(_FIXTURES / "exports_violation")
        violations = [
            d for d in diagnostics if d.code == "HELPER_PRIVATE_TO_MODULE"
        ]
        assert len(violations) == 1, (
            f"expected exactly one HELPER_PRIVATE_TO_MODULE; got: "
            f"{[(d.code, d.message) for d in diagnostics]}"
        )
        ctx = violations[0].context or {}
        assert ctx.get("source_module") == "production_consumer"
        assert ctx.get("target_component") == "_compare"
        # Re-exported flag should be True — the helper is in the
        # source module's exports_helpers.
        assert ctx.get("re_exported") is True

    def test_exported_helper_not_found_typo(self) -> None:
        """``exports_helpers: [_typoo_helper]`` (no such helper) fires error."""
        source = (
            'module typo_check\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Typo in exports_helpers entry."\n'
            '    exports: []\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: [_typoo_helper]\n'
            '\n'
            'helper _typo_helper :: APPLICATION\n'
            '    intent: "Helper with a one-char typo in the exports_helpers entry."\n'
            '    ---\n'
            '    def _typo_helper(x):\n'
            '        return x\n'
        )
        module = _parse(source, filename="typo_check.s0ma")
        errors = validate_module(module, filename="typo_check.s0ma")
        codes = [e.code for e in errors]
        assert "EXPORTED_HELPER_NOT_FOUND" in codes, (
            f"expected EXPORTED_HELPER_NOT_FOUND; got codes: {codes}"
        )
        ehnf = next(
            e for e in errors if e.code == "EXPORTED_HELPER_NOT_FOUND"
        )
        assert ehnf.severity == "error"
        ctx = ehnf.context or {}
        assert ctx.get("missing_helper") == "_typoo_helper"
        assert "_typo_helper" in ctx.get("available_helpers", [])

    def test_exported_helper_not_found_nonexistent_identifier(self) -> None:
        """``exports_helpers: [_does_not_exist]`` fires when no helper at all."""
        source = (
            'module no_helper_exists\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "exports_helpers references non-existent identifier."\n'
            '    exports: []\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: [_does_not_exist]\n'
        )
        module = _parse(source, filename="no_helper_exists.s0ma")
        errors = validate_module(module, filename="no_helper_exists.s0ma")
        codes = [e.code for e in errors]
        assert "EXPORTED_HELPER_NOT_FOUND" in codes
        ehnf = next(
            e for e in errors if e.code == "EXPORTED_HELPER_NOT_FOUND"
        )
        ctx = ehnf.context or {}
        assert ctx.get("missing_helper") == "_does_not_exist"
        assert ctx.get("available_helpers") == []

    def test_exported_helper_not_found_severity_is_error_every_mode(
        self,
    ) -> None:
        """``EXPORTED_HELPER_NOT_FOUND`` is an error in every strictness mode."""
        from s0ma_dsl.config import SEVERITY_MATRIX

        matrix_row = SEVERITY_MATRIX["EXPORTED_HELPER_NOT_FOUND"]
        for mode in StrictnessMode:
            assert matrix_row[mode] == "error", (
                f"EXPORTED_HELPER_NOT_FOUND severity for mode "
                f"{mode.value!r} must be 'error', got: {matrix_row[mode]!r}"
            )

    def test_exports_helpers_clean_passes_validator(self) -> None:
        """A correctly-spelled ``exports_helpers:`` raises no errors."""
        source = (
            'module clean_exports\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Correctly spelled exports_helpers."\n'
            '    exports: []\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: [_compare]\n'
            '\n'
            'helper _compare :: APPLICATION\n'
            '    intent: "Compare values."\n'
            '    ---\n'
            '    def _compare(a, b):\n'
            '        return a == b\n'
        )
        module = _parse(source, filename="clean_exports.s0ma")
        errors = validate_module(module, filename="clean_exports.s0ma")
        ehnf = [e for e in errors if e.code == "EXPORTED_HELPER_NOT_FOUND"]
        assert ehnf == [], (
            f"clean exports_helpers must validate without "
            f"EXPORTED_HELPER_NOT_FOUND; got: {[(e.code, e.message) for e in ehnf]}"
        )


# ---------------------------------------------------------------------------
# Cross-cutting AST / IR shape pins
# ---------------------------------------------------------------------------


class TestPost4ASTShape:
    """The new fields land cleanly on the dataclasses."""

    def test_helperdecl_carries_body_kind_and_inline_fields(self) -> None:
        """:class:`HelperDecl` exposes ``body_kind`` and ``inline``."""
        # Construct via parse to exercise the public path. The fields
        # must be present on the dataclass with default values that
        # match the M13 baseline.
        source = (
            'module ast_pin\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Pin AST shape."\n'
            '    exports: []\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: none\n'
            '\n'
            'helper _foo :: APPLICATION\n'
            '    intent: "A plain helper."\n'
            '    ---\n'
            '    def _foo():\n'
            '        return 1\n'
        )
        module = _parse(source)
        helper = module.helpers[0]
        assert hasattr(helper, "body_kind")
        assert hasattr(helper, "inline")
        # Block-form default values.
        assert helper.body_kind == "function"
        assert helper.inline is False

    def test_moduledecl_carries_exports_helpers_field(self) -> None:
        """:class:`ModuleDecl` exposes ``exports_helpers``."""
        source = (
            'module ast_pin_module\n'
            '    layer: APPLICATION\n'
            '    version: 1.0.0\n'
            '    intent: "Pin module AST shape."\n'
            '    exports: []\n'
            '    requires: none\n'
            '    uses: none\n'
            '    soft_requires: none\n'
            '    runtime_only_requires: none\n'
            '    deferred_requires: none\n'
            '    exports_helpers: none\n'
        )
        module = _parse(source)
        assert hasattr(module.module, "exports_helpers")
        assert module.module.exports_helpers == ()
        assert isinstance(module.module, ModuleDecl)
