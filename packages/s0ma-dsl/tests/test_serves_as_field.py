"""Tests for the ``serves_as:`` declaration field (DSL-M1, 0.8.0).

ADR-011 §(b) / design rule L-2: ``serves_as:`` is an optional
nerve-only field carrying the PUBLIC SERVING NAME — the name a
component is served under when it differs from the declaration
identifier (MCP tool/prompt names being the founding evidence,
friction log F-M2-2 / F-M3-4 / F-M4-2). The declaration identifier
remains the registry/module symbol.

Behavioural contract pinned here:

- ``serves_as: check`` (bare identifier, canonical) and the quoted
  form parse to ``NerveDecl.serves_as == "check"``; absent → ``None``.
- ``SERVES_AS_INVALID`` (error, every mode): value not
  identifier-shaped.
- ``SERVES_AS_COLLISION`` (error, every mode): two declarations carry
  the same served name — per module (semantic validator) AND per
  project build (dependency resolver; resolver reports only
  collisions spanning modules so one mistake yields one diagnostic).
  Equality with the declaration's own identifier is permitted.
- IR: ``components[].fields.serves_as``; omitted when absent (L-7).
- Emitter: the reserved ``serves_as`` metadata key joins the
  registration dict (emitter-written, before any authored entries),
  and a two-line ``__name__``/``__qualname__`` stamp lands one blank
  line after the decorated def. Decorate-then-stamp: executing the
  emitted module yields a ComponentSpec named by the DECLARATION
  identifier while the callable's ``__name__`` carries the served
  name.
"""

from __future__ import annotations

import ast

from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.config import (
    ERROR_CODE_DESCRIPTIONS,
    SEVERITY_MATRIX,
    StrictnessMode,
)
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.resolver.dependency import DependencyResolver
from s0ma_dsl.semantic.validator import IntraModuleValidator

# ---------------------------------------------------------------------------
# Source builders
# ---------------------------------------------------------------------------


def _module(
    nerve_fields: str = "", *, second_nerve_fields: str | None = None,
    module_name: str = "demo_serves_mod",
) -> str:
    second = ""
    exports = "[demo_tool]"
    if second_nerve_fields is not None:
        exports = "[demo_tool, other_tool]"
        second = (
            "\n"
            "nerve other_tool :: APPLICATION\n"
            "    kind: SERVICE\n"
            "    visibility: PUBLIC\n"
            '    intent: "Second nerve for collision arms."\n'
            '    expects: "an input dict"\n'
            '    guarantees: "returns a dict"\n'
            '    forbids: none\n'
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    provides: none\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            + second_nerve_fields
            + "    ---\n"
            "    def other_tool():\n"
            "        return {}\n"
        )
    return (
        f"module {module_name}\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Pins the DSL-M1 serves_as: field behaviour."\n'
        f"    exports: {exports}\n"
        f"    requires: none\n"
        f"    uses: none\n"
        f"    soft_requires: none\n"
        f"    runtime_only_requires: none\n"
        f"    deferred_requires: none\n"
        f"    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "nerve demo_tool :: APPLICATION\n"
        "    kind: SERVICE\n"
        "    visibility: PUBLIC\n"
        '    intent: "Demo nerve carrying a public serving name."\n'
        '    expects: "an input dict"\n'
        '    guarantees: "returns a dict"\n'
        '    forbids: none\n'
        "    evaluates_at: FUNCTION_BOUNDARY\n"
        "    provides: none\n"
        "    returns: none\n"
        "    raises: none\n"
        "    interface: none\n"
        "    latency_ms: none\n"
        "    depends_on: none\n"
        "    internal: none\n"
        "    expected_exceptions: none\n"
        "    consumes_via_dict: none\n"
        "    declares_attributes: none\n"
        "    covered_by: none\n"
        + nerve_fields
        + "    ---\n"
        "    def demo_tool():\n"
        "        return {}\n"
        + second
    )


def _validate(source: str) -> list:
    module = parse_s0ma(source, filename="demo_serves_mod.s0ma")
    return IntraModuleValidator(
        mode=StrictnessMode.STRICT, filename="demo_serves_mod.s0ma",
    ).validate(module)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestServesAsParsing:
    def test_bare_identifier_is_canonical(self) -> None:
        module = parse_s0ma(
            _module("    serves_as: demo\n"), filename="demo_serves_mod.s0ma",
        )
        assert module.nerves[0].serves_as == "demo"

    def test_quoted_form_accepted(self) -> None:
        module = parse_s0ma(
            _module('    serves_as: "demo"\n'),
            filename="demo_serves_mod.s0ma",
        )
        assert module.nerves[0].serves_as == "demo"

    def test_absent_is_none(self) -> None:
        module = parse_s0ma(_module(), filename="demo_serves_mod.s0ma")
        assert module.nerves[0].serves_as is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestServesAsValidation:
    def test_valid_serves_as_passes_strict(self) -> None:
        assert _validate(_module("    serves_as: demo\n")) == []

    def test_non_identifier_fires_invalid(self) -> None:
        errors = _validate(_module('    serves_as: "s0ma://guide/x"\n'))
        assert [e.code for e in errors] == ["SERVES_AS_INVALID"]
        assert "identifier-shaped" in errors[0].message
        assert "metadata" in errors[0].remediation

    def test_module_scope_collision_fires(self) -> None:
        errors = _validate(_module(
            "    serves_as: shared\n",
            second_nerve_fields="    serves_as: shared\n",
        ))
        assert [e.code for e in errors] == ["SERVES_AS_COLLISION"]
        assert "'demo_tool'" in errors[0].message
        assert "'other_tool'" in errors[0].message

    def test_own_identifier_equality_is_permitted(self) -> None:
        # serves_as equal to the declaration's own name: harmless
        # idempotent rename (ADR-011 §(b)).
        assert _validate(_module("    serves_as: demo_tool\n")) == []

    def test_project_scope_collision_fires_across_modules(self) -> None:
        mod_a = parse_s0ma(
            _module("    serves_as: shared\n", module_name="mod_a"),
            filename="mod_a.s0ma",
        )
        mod_b = parse_s0ma(
            _module("    serves_as: shared\n", module_name="mod_b"),
            filename="mod_b.s0ma",
        )
        errors = DependencyResolver(mode=StrictnessMode.STRICT).resolve(
            {"mod_a": mod_a, "mod_b": mod_b}, check_imports=False,
        )
        collisions = [e for e in errors if e.code == "SERVES_AS_COLLISION"]
        assert len(collisions) == 1
        assert "'mod_a.demo_tool'" in collisions[0].message
        assert "'mod_b.demo_tool'" in collisions[0].message

    def test_resolver_skips_intra_module_collisions(self) -> None:
        # The semantic validator owns the module scope; the resolver
        # reports only collisions SPANNING modules, so one authoring
        # mistake never produces two diagnostics.
        mod_a = parse_s0ma(
            _module(
                "    serves_as: shared\n",
                second_nerve_fields="    serves_as: shared\n",
                module_name="mod_a",
            ),
            filename="mod_a.s0ma",
        )
        errors = DependencyResolver(mode=StrictnessMode.STRICT).resolve(
            {"mod_a": mod_a}, check_imports=False,
        )
        assert [e for e in errors if e.code == "SERVES_AS_COLLISION"] == []

    def test_distinct_served_names_pass_project_scope(self) -> None:
        mod_a = parse_s0ma(
            _module("    serves_as: name_a\n", module_name="mod_a"),
            filename="mod_a.s0ma",
        )
        mod_b = parse_s0ma(
            _module("    serves_as: name_b\n", module_name="mod_b"),
            filename="mod_b.s0ma",
        )
        errors = DependencyResolver(mode=StrictnessMode.STRICT).resolve(
            {"mod_a": mod_a, "mod_b": mod_b}, check_imports=False,
        )
        assert [e for e in errors if e.code == "SERVES_AS_COLLISION"] == []

    def test_codes_are_registered_with_descriptions(self) -> None:
        for code in ("SERVES_AS_INVALID", "SERVES_AS_COLLISION"):
            assert code in SEVERITY_MATRIX
            assert all(
                SEVERITY_MATRIX[code][mode] == "error"
                for mode in StrictnessMode
            ), f"{code} must be error in every mode"
            assert code in ERROR_CODE_DESCRIPTIONS

    def test_authored_metadata_serves_as_key_stays_reserved(self) -> None:
        # The emitter writes ``serves_as`` into the registration dict —
        # authoring it through ``metadata:`` must keep failing with the
        # reserved-key diagnostic and point at the field.
        errors = _validate(
            _module('    metadata:\n        serves_as: "demo"\n'),
        )
        assert [e.code for e in errors] == ["METADATA_RESERVED_KEY"]
        assert "'serves_as:' field" in errors[0].remediation


# ---------------------------------------------------------------------------
# IR
# ---------------------------------------------------------------------------


class TestServesAsIR:
    def test_serves_as_rides_ir_fields(self) -> None:
        source = _module("    serves_as: demo\n")
        module = parse_s0ma(source, filename="demo_serves_mod.s0ma")
        doc = build_ir(module, source_text=source).to_dict()
        assert doc["components"][0]["fields"]["serves_as"] == "demo"

    def test_ir_omits_key_when_absent(self) -> None:
        source = _module()
        module = parse_s0ma(source, filename="demo_serves_mod.s0ma")
        doc = build_ir(module, source_text=source).to_dict()
        assert "serves_as" not in doc["components"][0]["fields"]


# ---------------------------------------------------------------------------
# Emitter — reserved metadata key + the __name__/__qualname__ stamp
# ---------------------------------------------------------------------------


class TestServesAsEmission:
    def _emit(self, nerve_fields: str) -> str:
        module = parse_s0ma(
            _module(nerve_fields), filename="demo_serves_mod.s0ma",
        )
        py_source = PythonEmitter(module_name="demo_serves_mod").emit(module)
        ast.parse(py_source)
        return py_source

    def test_reserved_metadata_key_is_written(self) -> None:
        py_source = self._emit("    serves_as: demo\n")
        assert '"serves_as": "demo"' in py_source

    def test_stamp_lands_one_blank_line_after_the_def(self) -> None:
        py_source = self._emit("    serves_as: demo\n")
        assert (
            "def demo_tool():\n"
            "    return {}\n"
            "\n"
            'demo_tool.__name__ = "demo"\n'
            'demo_tool.__qualname__ = "demo"\n'
        ) in py_source + "\n"

    def test_emitter_keys_precede_authored_entries(self) -> None:
        py_source = self._emit(
            "    serves_as: demo\n"
            "    metadata:\n"
            '        mcp_prompt_title: "Demo title"\n',
        )
        assert (
            '"serves_as": "demo", "mcp_prompt_title": "Demo title"'
        ) in py_source

    def test_no_serves_as_means_no_stamp_no_key(self) -> None:
        py_source = self._emit("")
        assert "__name__ =" not in py_source
        assert "__qualname__ =" not in py_source
        assert '"serves_as"' not in py_source

    def test_decorate_then_stamp_preserves_spec_identity(self) -> None:
        """Execute the emitted module: ComponentSpec keeps the
        declaration identifier; the callable's ``__name__``/
        ``__qualname__`` carry the served name (the F-M4-2 fix).

        The exec runs against a FRESH non-persistent registry swapped
        in via ``set_registry`` (and restored in ``finally``) so the
        executed module's registrations never leak into the process
        singleton — the default singleton persists to
        ``.s0ma/registry.db``, where a leaked ``demo_tool`` would
        collide on the NEXT pytest run.
        """
        py_source = self._emit("    serves_as: demo\n")
        from s0ma.registry import ComponentRegistry, get_registry, set_registry

        previous = get_registry(persist=False)
        fresh = ComponentRegistry(persist=False)
        set_registry(fresh)
        try:
            namespace: dict = {"__name__": "demo_serves_mod_exec"}
            exec(compile(py_source, "demo_serves_mod.py", "exec"), namespace)
        finally:
            set_registry(previous)
        fn = namespace["demo_tool"]
        assert fn.__name__ == "demo"
        assert fn.__qualname__ == "demo"
        spec = fn.__component__
        assert spec.name == "demo_tool"
        assert spec.metadata["serves_as"] == "demo"
        assert "demo_tool" in namespace  # module attribute keeps the symbol
        assert "demo" not in namespace or not callable(
            namespace.get("demo"),
        )
        # The registration landed in the isolated registry under the
        # DECLARATION identifier (registry identity unchanged by the
        # stamp), and the served name is not a registry name.
        assert fresh.contains("demo_tool")
        assert not fresh.contains("demo")
