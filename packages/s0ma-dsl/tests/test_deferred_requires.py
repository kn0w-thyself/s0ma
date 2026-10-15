"""Tests for the ``deferred_requires:`` module-header field (DSL-M2, 0.8.0).

ADR-011 §(c) / design rule L-3: ``deferred_requires:`` is a sibling
requires-family field (the ``soft_requires`` / ``runtime_only_requires``
precedent) with the same entry grammar — dotted paths, colon overrides,
``as`` aliases, inline and block-list forms. Entries emit NOTHING at
module top; the emitter injects the import at the top of each CONSUMING
def body, after the docstring when present, one contiguous block in
entry order. Per-call failure semantics: on a broken environment the
module still imports and each call raises ``ImportError`` inside the
body (the F-M3-1 "start degraded, fail per-call" idiom, restored as an
authored choice).

Behavioural contract pinned here:

- Entry grammar parity with ``requires:`` (colon override → from-import,
  aliases, heuristic from-import detection).
- IR: ``imports.deferred_requires`` entries carry ``"deferred": true``;
  the list key is OMITTED when the field is not authored, and no other
  requires-family entry gains a ``deferred`` key (L-7: no backfill).
- Emission: injection after the docstring, before the first authored
  statement; non-consuming defs untouched; class-cell and class-nerve
  METHOD bodies are injectable; module top carries no deferred import.
- Diagnostics: ``DUPLICATE_REQUIRES_ENTRY`` and
  ``DEFERRED_IMPORT_MODULE_SCOPE`` (both error in every mode, emitted by
  the resolver — which the CLI now also runs for single-module sets that
  author the field), ``VESTIGIAL_IMPORT`` for unconsumed entries,
  ``MISSING_PACKAGE`` applies to deferred entries unchanged, and the
  ``BARE_IMPORT`` remediation gains the deferred option.
- The broken-dependency fixture proves both arms end-to-end through
  ``s0ma build``: import-time success with the dependency absent, and
  per-call ``ImportError`` from the consuming nerve.
"""

from __future__ import annotations

import ast
from pathlib import Path

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.cli.migrate_grammar import current_grammar_source
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

_FIXTURE_PROJECT = (
    Path(__file__).parent / "fixtures" / "deferred_imports_project"
)


# ---------------------------------------------------------------------------
# Source builders
# ---------------------------------------------------------------------------


def _module(
    header_extra: str = "",
    decls: str = "",
) -> str:
    """A minimal module with configurable header lines and declarations."""
    source = (
        "module demo_defer_mod\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Pins the DSL-M2 deferred_requires: field behaviour."\n'
        + header_extra
        + "    exports: [demo_tool]\n"
        "    ---\n"
        "\n"
        + (decls or (
            "nerve demo_tool :: APPLICATION\n"
            "    kind: FUNCTION\n"
            "    visibility: PUBLIC\n"
            '    intent: "Demo nerve."\n'
            '    expects: "nothing"\n'
            '    guarantees: "a dict"\n'
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
            "    ---\n"
            "    def demo_tool():\n"
            '        """Doc line."""\n'
            "        return {\"ok\": json.dumps({})}\n"
        ))
    )
    return current_grammar_source(source, filename="demo_defer_mod.s0ma")


def _parse(src: str):
    return parse_s0ma(src, filename="demo_defer_mod.s0ma")


def _resolve(src: str, mode: StrictnessMode = StrictnessMode.DEV):
    mod = _parse(src)
    resolver = DependencyResolver(mode=mode)
    return resolver.resolve(
        {"demo_defer_mod": mod},
        filenames={"demo_defer_mod": "demo_defer_mod.s0ma"},
        check_imports=False,
    )


def _emit(src: str) -> str:
    mod = _parse(src)
    out = PythonEmitter(module_name="demo_defer_mod").emit(mod)
    ast.parse(out)
    return out


# ---------------------------------------------------------------------------
# Parsing — entry-grammar parity with requires:
# ---------------------------------------------------------------------------


class TestDeferredRequiresParsing:
    def test_entry_grammar_matches_requires(self) -> None:
        src = _module(
            "    deferred_requires: [json, s0ma_dsl.cli.main:S0maCLI, uuid as u]\n",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Consumes all three deferred bindings."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a dict"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        cli = S0maCLI()\n"
                "        return {\"j\": json.dumps({}), \"u\": u.uuid4(), \"cli\": cli}\n"
            ),
        )
        mod = _parse(src)
        entries = mod.module.deferred_requires
        assert [(e.module_path, e.alias, e.is_from_import) for e in entries] == [
            ("json", None, False),
            ("s0ma_dsl.cli.main.S0maCLI", None, True),
            ("uuid", "u", False),
        ]

    def test_absent_field_parses_to_empty_tuple(self) -> None:
        src = _module(
            "    requires: [json]\n",
        )
        mod = _parse(src)
        assert mod.module.deferred_requires == ()

    def test_semantic_validator_clean_on_consuming_module(self) -> None:
        src = _module(
            "    deferred_requires: [json]\n",
        )
        mod = _parse(src)
        errors = IntraModuleValidator(
            filename="demo_defer_mod.s0ma", mode=StrictnessMode.STRICT,
        ).validate(mod)
        assert [e for e in errors if e.severity == "error"] == []


# ---------------------------------------------------------------------------
# IR — deferred: true entries; omitted-when-absent; no backfill
# ---------------------------------------------------------------------------


class TestDeferredRequiresIR:
    def test_entries_carry_deferred_true(self) -> None:
        src = _module("    deferred_requires: [json]\n")
        doc = build_ir(_parse(src), source_text=src).to_dict()
        assert doc["imports"]["deferred_requires"] == {
            "state": "value",
            "value": ["json"],
        }

    def test_key_omitted_when_not_authored(self) -> None:
        src = _module(
            "    requires: [json]\n",
        )
        doc = build_ir(_parse(src), source_text=src).to_dict()
        assert doc["imports"]["deferred_requires"] == {"state": "none"}

    def test_no_deferred_key_backfilled_on_other_lists(self) -> None:
        src = _module(
            "    requires: [json]\n"
            "    deferred_requires: [uuid]\n",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Consumes both."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a dict"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        return {\"j\": json.dumps({}), \"u\": uuid.uuid4()}\n"
            ),
        )
        doc = build_ir(_parse(src), source_text=src).to_dict()
        assert doc["imports"]["requires"] == {
            "state": "value",
            "value": ["json"],
        }
        assert doc["imports"]["deferred_requires"] == {
            "state": "value",
            "value": ["uuid"],
        }


# ---------------------------------------------------------------------------
# Emission — body injection mechanics
# ---------------------------------------------------------------------------


class TestDeferredEmission:
    def test_no_module_top_import_and_injection_after_docstring(self) -> None:
        src = _module("    deferred_requires: [json]\n")
        out = _emit(src)
        module_top = out.split("def demo_tool")[0]
        assert "\nimport json" not in module_top
        assert (
            "def demo_tool():\n"
            '    """Doc line."""\n'
            "    import json\n"
        ) in out

    def test_contiguous_block_in_entry_order(self) -> None:
        src = _module(
            "    deferred_requires: [uuid, json]\n",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Consumes both deferred bindings."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a dict"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        return {\"u\": uuid.uuid4(), \"j\": json.dumps({})}\n"
            ),
        )
        out = _emit(src)
        assert (
            "def demo_tool():\n"
            "    import uuid\n"
            "    import json\n"
        ) in out

    def test_colon_override_injects_from_import(self) -> None:
        src = _module(
            "    deferred_requires: [s0ma_dsl.cli.main:S0maCLI]\n",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Consumes the colon-override binding."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a cli"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        return S0maCLI()\n"
            ),
        )
        out = _emit(src)
        assert (
            "def demo_tool():\n"
            "    from s0ma_dsl.cli.main import S0maCLI\n"
        ) in out
        assert "\nfrom s0ma_dsl.cli.main import S0maCLI" not in out.split(
            "def demo_tool",
        )[0]

    def test_non_consuming_def_untouched(self) -> None:
        src = _module(
            "    deferred_requires: [json]\n",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Consumes json."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a dict"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        return json.dumps({})\n"
                "\n"
                "helper _plain :: APPLICATION\n"
                '    intent: "Consumes nothing deferred."\n'
                "    ---\n"
                "    def _plain():\n"
                "        return 1\n"
            ),
        )
        out = _emit(src)
        assert (
            "def _plain():\n"
            "    return 1\n"
        ) in out

    def test_class_cell_method_receives_injection(self) -> None:
        src = _module(
            "    deferred_requires: [json]\n",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Consumes json."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a dict"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        return json.dumps({})\n"
                "\n"
                "cell Codec :: APPLICATION\n"
                "    kind: MODEL\n"
                "    visibility: PUBLIC\n"
                '    intent: "Class cell with a consuming method."\n'
                '    schema: "codec"\n'
                '    invariants: none\n'
                '    covered_by: none\n'
                "    ---\n"
                "    class Codec:\n"
                "        def encode(self, payload):\n"
                "            return json.dumps(payload)\n"
            ),
        )
        out = _emit(src)
        assert (
            "    def encode(self, payload):\n"
            "        import json\n"
            "        return json.dumps(payload)\n"
        ) in out

    def test_nested_def_reference_injects_at_outermost_def(self) -> None:
        src = _module(
            "    deferred_requires: [json]\n",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Nested def consumes json."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a callable"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        def _inner():\n"
                "            return json.dumps({})\n"
                "        return _inner\n"
            ),
        )
        out = _emit(src)
        assert (
            "def demo_tool():\n"
            "    import json\n"
            "    def _inner():\n"
        ) in out


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class TestDeferredDiagnostics:
    def test_matrix_and_description_registration(self) -> None:
        for code in ("DUPLICATE_REQUIRES_ENTRY", "DEFERRED_IMPORT_MODULE_SCOPE"):
            assert code in SEVERITY_MATRIX
            assert all(
                SEVERITY_MATRIX[code][mode] == "error"
                for mode in StrictnessMode
            )
            assert code in ERROR_CODE_DESCRIPTIONS

    def test_duplicate_requires_entry_fires_per_other_list(self) -> None:
        for other in ("requires", "soft_requires", "runtime_only_requires"):
            src = _module(
                f"    {other}: [json]\n"
                "    deferred_requires: [json]\n",
            )
            errors = _resolve(src)
            dupes = [e for e in errors if e.code == "DUPLICATE_REQUIRES_ENTRY"]
            assert len(dupes) == 1, f"expected one duplicate for {other}"
            assert dupes[0].severity == "error"
            assert other in dupes[0].message

    def test_module_scope_consumption_rejected(self) -> None:
        src = _module(
            "    deferred_requires: [json]\n",
            decls=(
                "cell PAYLOAD :: APPLICATION\n"
                "    kind: CONSTANT\n"
                "    visibility: PUBLIC\n"
                '    intent: "Consumes json at module scope."\n'
                '    schema: "str"\n'
                '    invariants: none\n'
                '    covered_by: none\n'
                "    ---\n"
                "    PAYLOAD = json.dumps({})\n"
                "\n"
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Consumes json legally."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a dict"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        return json.dumps({})\n"
            ),
        )
        errors = _resolve(src)
        scoped = [
            e for e in errors if e.code == "DEFERRED_IMPORT_MODULE_SCOPE"
        ]
        assert len(scoped) == 1
        assert scoped[0].severity == "error"
        assert scoped[0].context["declaration"] == "PAYLOAD"

    def test_decorator_default_and_annotation_are_module_scope(self) -> None:
        src = _module(
            "    deferred_requires: [functools, json, typing:Any]\n",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Consumes deferred names at def-time positions."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a dict"\n'
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
                "    ---\n"
                "    @functools.lru_cache\n"
                "    def demo_tool(x: Any = json.loads(\"1\")):\n"
                "        return {\"j\": json.dumps({}), \"f\": functools, \"a\": Any}\n"
            ),
        )
        errors = _resolve(src)
        hit_names = sorted(
            e.context["local_name"]
            for e in errors
            if e.code == "DEFERRED_IMPORT_MODULE_SCOPE"
        )
        assert hit_names == ["Any", "functools", "json"]

    def test_method_body_consumption_is_not_module_scope(self) -> None:
        src = _module(
            "    deferred_requires: [json]\n",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Consumes json in the body only."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a dict"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        return json.dumps({})\n"
            ),
        )
        errors = _resolve(src)
        assert [
            e for e in errors if e.code == "DEFERRED_IMPORT_MODULE_SCOPE"
        ] == []

    def test_unconsumed_deferred_entry_is_vestigial(self) -> None:
        src = _module(
            "    deferred_requires: [json]\n",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Never consumes the deferred binding."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a str"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        return \"static\"\n"
            ),
        )
        errors = _resolve(src)
        vestigial = [e for e in errors if e.code == "VESTIGIAL_IMPORT"]
        assert len(vestigial) == 1
        assert "deferred_requires entry 'json'" in vestigial[0].message

    def test_missing_package_applies_to_deferred_entries(self) -> None:
        src = _module(
            "    deferred_requires: [s0ma_m2_nonexistent_dep_proof]\n",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Consumes the absent package."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a value"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        return s0ma_m2_nonexistent_dep_proof.thing()\n"
            ),
        )
        mod = _parse(src)
        for mode, expected_severity in (
            (StrictnessMode.DEV, "warning"),
            (StrictnessMode.STRICT, "error"),
        ):
            resolver = DependencyResolver(mode=mode)
            errors = resolver.resolve(
                {"demo_defer_mod": mod}, check_imports=True,
            )
            missing = [e for e in errors if e.code == "MISSING_PACKAGE"]
            assert len(missing) == 1
            assert missing[0].severity == expected_severity

    def test_bare_import_remediation_names_deferred_option(self) -> None:
        src = _module(
            "",
            decls=(
                "nerve demo_tool :: APPLICATION\n"
                "    kind: FUNCTION\n"
                "    visibility: PUBLIC\n"
                '    intent: "Carries a bare import."\n'
                '    expects: "nothing"\n'
                '    guarantees: "a dict"\n'
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
                "    ---\n"
                "    def demo_tool():\n"
                "        import textwrap\n"
                "        return textwrap.dedent(\"x\")\n"
            ),
        )
        from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings

        _mod, warnings = parse_s0ma_with_warnings(
            src, "demo_defer_mod.s0ma", mode=StrictnessMode.DEV,
        )
        bare = [w for w in warnings if w.code == "BARE_IMPORT"]
        assert len(bare) == 1
        assert "deferred_requires" in (bare[0].remediation or "")


# ---------------------------------------------------------------------------
# The broken-dependency fixture — both arms, end-to-end through s0ma build
# ---------------------------------------------------------------------------


class TestBrokenDependencyFixture:
    def _build_fixture(self, tmp_path: Path) -> str:
        out_dir = tmp_path / "build"
        cli = S0maCLI()
        rc = cli.run([
            "build", str(_FIXTURE_PROJECT),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--no-cache",
        ])
        assert rc == EXIT_SUCCESS, (
            "fixture build must succeed in dev mode — MISSING_PACKAGE is "
            "a warning there, which is exactly what lets a degraded "
            "environment still build"
        )
        return (out_dir / "lazy_tools.py").read_text(encoding="utf-8")

    def test_arm_one_module_imports_with_dependency_absent(
        self, tmp_path: Path,
    ) -> None:
        """Import-time success: exec of the built module raises nothing.

        The exec runs against a FRESH non-persistent registry swapped in
        via ``set_registry`` (restored in ``finally``) so the executed
        module's registrations never leak into the process singleton —
        the default singleton persists to ``.s0ma/registry.db``.
        """
        py_source = self._build_fixture(tmp_path)
        assert "from s0ma_m2_nonexistent_dep_proof import missing_symbol" not in (
            py_source.split("def lazy_probe")[0]
        )
        from s0ma.registry import ComponentRegistry, get_registry, set_registry

        previous = get_registry(persist=False)
        set_registry(ComponentRegistry(persist=False))
        try:
            namespace: dict = {"__name__": "lazy_tools_exec"}
            exec(compile(py_source, "lazy_tools.py", "exec"), namespace)
        finally:
            set_registry(previous)
        assert namespace["eager_probe"]() == {"ok": True}

    def test_arm_two_call_fails_per_call_with_import_error(
        self, tmp_path: Path,
    ) -> None:
        """Per-call failure: each call raises ImportError inside the body."""
        import pytest

        py_source = self._build_fixture(tmp_path)
        assert (
            'def lazy_probe():\n'
            '    """Per-call deferred-import probe; the import lands below this docstring."""\n'
            "    from s0ma_m2_nonexistent_dep_proof import missing_symbol\n"
        ) in py_source
        from s0ma.registry import ComponentRegistry, get_registry, set_registry

        previous = get_registry(persist=False)
        set_registry(ComponentRegistry(persist=False))
        try:
            namespace: dict = {"__name__": "lazy_tools_exec_arm2"}
            exec(compile(py_source, "lazy_tools.py", "exec"), namespace)
            with pytest.raises(ImportError):
                namespace["lazy_probe"]()
            # Per-call, not once: a second call fails identically.
            with pytest.raises(ImportError):
                namespace["lazy_probe"]()
        finally:
            set_registry(previous)
