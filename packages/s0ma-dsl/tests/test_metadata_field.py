"""Tests for the authored ``metadata:`` declaration field (DSL-M1, 0.8.0).

ADR-011 §(a) / design rule L-1: ``metadata:`` is a per-declaration
block-map field on nerve / cell / ganglion holding a flat map of
identifier keys to scalar values (quoted string | int | float | bool)
or bracketed lists of strings. It is authored-opaque — the language
validates SHAPE only, never interprets values (P-2) — and flows
parser → AST → IR (``components[].fields.metadata``) → emitted
``@component(..., metadata={...})`` merge → runtime
``ComponentSpec.metadata``.

Behavioural contract pinned here:

- The block map parses to ordered ``(key, value)`` pairs on
  ``NerveDecl.metadata`` / ``CellDecl.metadata`` /
  ``GanglionDecl.metadata`` with native Python value types
  (str / int / float / bool / tuple-of-str), preserving authored order
  and duplicate keys (the validator's evidence).
- Shape violations are SEMANTIC diagnostics, never parse aborts:
  ``METADATA_INVALID_KEY`` (malformed or duplicate key),
  ``METADATA_INVALID_VALUE`` (null, bare token, nested map, malformed
  list entry, inline form), ``METADATA_RESERVED_KEY`` (collision with
  ``RESERVED_COMPONENT_METADATA_KEYS``) — all error in every mode.
- The IR carries ``components[].fields.metadata`` as a JSON object in
  authored key order; the key is omitted entirely when the field is
  not authored (L-7: no new IR surface on legacy builds).
- The emitter APPENDS authored items AFTER the emitter-written keys in
  the existing registration ``metadata=`` dict, at all five component
  emission shapes; values render as Python literals (``True``, never
  JSON ``true`` — the F7 rule).
- ``test_every_emitter_written_metadata_key_is_reserved`` pins the
  reserved-key constant against the emitter both behaviourally (a
  maximal corpus across the five emission shapes) and lexically (every
  dict-key literal written in ``python_emitter.py``), so a future
  emitter key cannot silently bypass the reserved set.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from s0ma_dsl.ast_nodes.enums import EvaluatesAt, Kind, Layer, Visibility
from s0ma_dsl.ast_nodes.nodes import CellDecl, GanglionDecl, NerveDecl
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.config import (
    ERROR_CODE_DESCRIPTIONS,
    SEVERITY_MATRIX,
    StrictnessMode,
)
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.ir.schema import RESERVED_COMPONENT_METADATA_KEYS
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.semantic.validator import IntraModuleValidator

# ---------------------------------------------------------------------------
# Source builders
# ---------------------------------------------------------------------------


def _nerve_module(metadata_block: str = "") -> str:
    """A minimal one-nerve module with an optional ``metadata:`` block."""
    return (
        "module demo_meta_mod\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Pins the DSL-M1 metadata: field behaviour."\n'
        "    exports: [demo_nerve]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "nerve demo_nerve :: APPLICATION\n"
        "    kind: SERVICE\n"
        "    visibility: PUBLIC\n"
        '    intent: "Demo nerve carrying authored metadata."\n'
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
        + metadata_block
        + "    ---\n"
        "    def demo_nerve():\n"
        "        return {}\n"
    )


_FULL_METADATA_BLOCK = (
    "    metadata:\n"
    '        mcp_uri: "s0ma://guide/x"\n'
    "        max_retries: 3\n"
    "        ratio: 0.5\n"
    "        experimental: false\n"
    "        enabled: true\n"
    "        composes: [a_thing, b_thing]\n"
    '        annotations: ["readOnlyHint=true", "openWorldHint=false"]\n'
)


def _cell_module(metadata_block: str = "", kind: str = "MODEL") -> str:
    body = {
        "MODEL": "    class DemoCell:\n        pass\n",
        "CONSTANT": "    DemoCell = 42\n",
        "TYPE": "    DemoCell = str\n",
    }[kind]
    return (
        "module demo_meta_mod\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Pins the DSL-M1 metadata: field on cells."\n'
        "    exports: [DemoCell]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        f"cell DemoCell :: APPLICATION\n"
        f"    kind: {kind}\n"
        "    visibility: PUBLIC\n"
        '    intent: "Demo cell carrying authored metadata."\n'
        '    schema: "demo schema."\n'
        '    invariants: none\n'
        '    covered_by: none\n'
        + metadata_block
        + "    ---\n"
        + body
    )


def _ganglion_module(metadata_block: str = "") -> str:
    return (
        "module demo_meta_mod\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Pins the DSL-M1 metadata: field on ganglia."\n'
        "    exports: [demo_nerve]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "nerve demo_nerve :: APPLICATION\n"
        "    kind: SERVICE\n"
        "    visibility: PUBLIC\n"
        '    intent: "Observed nerve."\n'
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
        "    ---\n"
        "    def demo_nerve():\n"
        "        return {}\n"
        "\n"
        "ganglion demo_watcher :: APPLICATION\n"
        "    visibility: INTERNAL\n"
        '    intent: "Demo evaluator carrying authored metadata."\n'
        "    observes: [demo_nerve]\n"
        "    scope: FUNCTION_BOUNDARY\n"
        '    priors: "none recorded"\n'
        '    on_anomaly: "log it"\n'
        '    forbids: none\n'
        '    depends_on: none\n'
        '    covered_by: none\n'
        + metadata_block
        + "    ---\n"
        "    def demo_watcher(signal):\n"
        "        return signal\n"
    )


def _validate(source: str) -> list:
    module = parse_s0ma(source, filename="demo_meta_mod.s0ma")
    return IntraModuleValidator(
        mode=StrictnessMode.STRICT, filename="demo_meta_mod.s0ma",
    ).validate(module)


def _codes(errors: list) -> list[str]:
    return [e.code for e in errors]


def _emitted_metadata_dict(py_source: str, owner: str) -> dict:
    """Extract the ``metadata={...}`` dict literal for *owner*.

    Walks the emitted module's AST for the ``@component`` call (or
    ``register_constant`` / ``register_type`` call) whose ``name=``
    equals *owner* and ``literal_eval``s its ``metadata=`` kwarg — i.e.
    exactly the dict the runtime registration will receive.
    """
    tree = ast.parse(py_source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        name_node = kwargs.get("name")
        if name_node is None or not isinstance(name_node, ast.Constant):
            continue
        if name_node.value != owner or "metadata" not in kwargs:
            continue
        return ast.literal_eval(kwargs["metadata"])
    raise AssertionError(
        f"no registration call with name={owner!r} and a metadata= kwarg "
        f"found in emitted source"
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestMetadataParsing:
    def test_nerve_metadata_parses_typed_and_ordered(self) -> None:
        module = parse_s0ma(
            _nerve_module(_FULL_METADATA_BLOCK), filename="demo_meta_mod.s0ma",
        )
        assert module.nerves[0].metadata == (
            ("mcp_uri", "s0ma://guide/x"),
            ("max_retries", 3),
            ("ratio", 0.5),
            ("experimental", False),
            ("enabled", True),
            ("composes", ("a_thing", "b_thing")),
            ("annotations", ("readOnlyHint=true", "openWorldHint=false")),
        )

    def test_cell_and_ganglion_metadata_parse(self) -> None:
        cell_mod = parse_s0ma(
            _cell_module('    metadata:\n        wraps: "x.y.Z"\n'),
            filename="demo_meta_mod.s0ma",
        )
        assert cell_mod.cells[0].metadata == (("wraps", "x.y.Z"),)
        gang_mod = parse_s0ma(
            _ganglion_module("    metadata:\n        channel: \"alerts\"\n"),
            filename="demo_meta_mod.s0ma",
        )
        assert gang_mod.ganglia[0].metadata == (("channel", "alerts"),)

    def test_absent_metadata_is_empty_tuple(self) -> None:
        module = parse_s0ma(_nerve_module(), filename="demo_meta_mod.s0ma")
        assert module.nerves[0].metadata == ()

    def test_duplicate_keys_and_authored_order_survive_to_ast(self) -> None:
        block = (
            "    metadata:\n"
            "        dup: 1\n"
            "        other: 2\n"
            "        dup: 3\n"
        )
        module = parse_s0ma(_nerve_module(block), filename="demo_meta_mod.s0ma")
        assert module.nerves[0].metadata == (
            ("dup", 1), ("other", 2), ("dup", 3),
        )

    def test_comments_and_blank_lines_inside_block_are_skipped(self) -> None:
        block = (
            "    metadata:\n"
            "        # a comment\n"
            "\n"
            "        kept: 1\n"
        )
        module = parse_s0ma(_nerve_module(block), filename="demo_meta_mod.s0ma")
        assert module.nerves[0].metadata == (("kept", 1),)


# ---------------------------------------------------------------------------
# Validation — the three METADATA_* diagnostics
# ---------------------------------------------------------------------------


class TestMetadataValidation:
    def test_valid_metadata_passes_strict(self) -> None:
        assert _validate(_nerve_module(_FULL_METADATA_BLOCK)) == []

    def test_empty_block_is_permitted(self) -> None:
        assert _validate(_nerve_module("    metadata:\n")) == []

    def test_duplicate_key_fires_invalid_key(self) -> None:
        errors = _validate(
            _nerve_module("    metadata:\n        dup: 1\n        dup: 2\n"),
        )
        assert _codes(errors) == ["METADATA_INVALID_KEY"]
        assert "more than once" in errors[0].message

    def test_malformed_key_fires_invalid_key(self) -> None:
        errors = _validate(
            _nerve_module("    metadata:\n        foo-bar: 1\n"),
        )
        assert "METADATA_INVALID_KEY" in _codes(errors)
        assert "identifier-shaped" in errors[0].message

    def test_reserved_key_fires_with_field_pointer(self) -> None:
        errors = _validate(
            _nerve_module('    metadata:\n        visibility: "PUBLIC"\n'),
        )
        assert _codes(errors) == ["METADATA_RESERVED_KEY"]
        assert "'visibility:' field" in errors[0].remediation

    def test_reserved_derived_key_points_at_owning_field(self) -> None:
        errors = _validate(
            _nerve_module('    metadata:\n        kind_detail: "MODEL"\n'),
        )
        assert _codes(errors) == ["METADATA_RESERVED_KEY"]
        assert "'kind:' field" in errors[0].remediation

    def test_null_value_fires_invalid_value(self) -> None:
        errors = _validate(_nerve_module("    metadata:\n        empty:\n"))
        assert _codes(errors) == ["METADATA_INVALID_VALUE"]
        assert "no value" in errors[0].message

    def test_bare_token_fires_invalid_value(self) -> None:
        errors = _validate(_nerve_module("    metadata:\n        v: oops\n"))
        assert _codes(errors) == ["METADATA_INVALID_VALUE"]
        assert "unquoted bare token" in errors[0].message
        assert "'oops'" in errors[0].message

    def test_capitalised_boolean_is_a_bare_token(self) -> None:
        # The L-1 boolean literals are lower-case ``true``/``false`` —
        # ``True`` must not silently become the string "True".
        errors = _validate(_nerve_module("    metadata:\n        b: True\n"))
        assert _codes(errors) == ["METADATA_INVALID_VALUE"]

    def test_nested_map_fires_invalid_value(self) -> None:
        block = (
            "    metadata:\n"
            "        outer:\n"
            "            inner: 1\n"
        )
        errors = _validate(_nerve_module(block))
        assert _codes(errors) == ["METADATA_INVALID_VALUE"]
        assert "nested map" in errors[0].message

    def test_malformed_list_entry_fires_invalid_value(self) -> None:
        errors = _validate(
            _nerve_module("    metadata:\n        xs: [ok, not ok]\n"),
        )
        assert _codes(errors) == ["METADATA_INVALID_VALUE"]
        assert "list entry" in errors[0].message

    def test_inline_form_fires_invalid_value(self) -> None:
        errors = _validate(
            _nerve_module("    metadata: {a: 1}\n"),
        )
        assert _codes(errors) == ["METADATA_INVALID_VALUE"]
        assert "block map" in errors[0].message

    def test_cell_and_ganglion_maps_are_validated_too(self) -> None:
        cell_errors = _validate(
            _cell_module('    metadata:\n        schema: "x"\n'),
        )
        assert _codes(cell_errors) == ["METADATA_RESERVED_KEY"]
        gang_errors = _validate(
            _ganglion_module('    metadata:\n        scope: "x"\n'),
        )
        assert _codes(gang_errors) == ["METADATA_RESERVED_KEY"]

    def test_codes_are_registered_with_descriptions(self) -> None:
        for code in (
            "METADATA_INVALID_KEY",
            "METADATA_INVALID_VALUE",
            "METADATA_RESERVED_KEY",
        ):
            assert code in SEVERITY_MATRIX
            assert all(
                SEVERITY_MATRIX[code][mode] == "error"
                for mode in StrictnessMode
            ), f"{code} must be error in every mode"
            assert code in ERROR_CODE_DESCRIPTIONS


# ---------------------------------------------------------------------------
# IR
# ---------------------------------------------------------------------------


class TestMetadataIR:
    def test_metadata_rides_ir_fields_in_authored_order(self) -> None:
        source = _nerve_module(_FULL_METADATA_BLOCK)
        module = parse_s0ma(source, filename="demo_meta_mod.s0ma")
        doc = build_ir(module, source_text=source).to_dict()
        ir_metadata = doc["components"][0]["fields"]["metadata"]
        assert ir_metadata == {
            "mcp_uri": "s0ma://guide/x",
            "max_retries": 3,
            "ratio": 0.5,
            "experimental": False,
            "enabled": True,
            "composes": ["a_thing", "b_thing"],
            "annotations": ["readOnlyHint=true", "openWorldHint=false"],
        }
        assert list(ir_metadata) == [
            "mcp_uri", "max_retries", "ratio", "experimental", "enabled",
            "composes", "annotations",
        ]

    def test_ir_omits_key_when_not_authored(self) -> None:
        source = _nerve_module()
        module = parse_s0ma(source, filename="demo_meta_mod.s0ma")
        doc = build_ir(module, source_text=source).to_dict()
        assert "metadata" not in doc["components"][0]["fields"]


# ---------------------------------------------------------------------------
# Emitter merge
# ---------------------------------------------------------------------------


class TestMetadataEmission:
    def test_nerve_merge_appends_after_emitter_keys(self) -> None:
        module = parse_s0ma(
            _nerve_module(_FULL_METADATA_BLOCK), filename="demo_meta_mod.s0ma",
        )
        py_source = PythonEmitter(module_name="demo_meta_mod").emit(module)
        ast.parse(py_source)
        merged = _emitted_metadata_dict(py_source, "demo_nerve")
        assert merged == {
            "visibility": "PUBLIC",
            "evaluates_at": "FUNCTION_BOUNDARY",
            "mcp_uri": "s0ma://guide/x",
            "max_retries": 3,
            "ratio": 0.5,
            "experimental": False,
            "enabled": True,
            "composes": ["a_thing", "b_thing"],
            "annotations": ["readOnlyHint=true", "openWorldHint=false"],
        }
        # Emitter-written keys come FIRST, authored keys after, in
        # authored order (dict literal insertion order is meaningful).
        assert list(merged) == [
            "visibility", "evaluates_at", "mcp_uri", "max_retries", "ratio",
            "experimental", "enabled", "composes", "annotations",
        ]

    def test_boolean_renders_as_python_literal(self) -> None:
        # F7: bare JSON ``true``/``false`` in emitted source is a
        # NameError at import time.
        module = parse_s0ma(
            _nerve_module("    metadata:\n        flag: true\n"),
            filename="demo_meta_mod.s0ma",
        )
        py_source = PythonEmitter(module_name="demo_meta_mod").emit(module)
        assert '"flag": True' in py_source
        assert '"flag": true' not in py_source

    def test_all_three_cell_shapes_merge(self) -> None:
        for kind, reg in (
            ("MODEL", "@component"),
            ("CONSTANT", "register_constant"),
            ("TYPE", "register_type"),
        ):
            module = parse_s0ma(
                _cell_module('    metadata:\n        wraps: "x.y.Z"\n', kind),
                filename="demo_meta_mod.s0ma",
            )
            py_source = PythonEmitter(module_name="demo_meta_mod").emit(module)
            ast.parse(py_source)
            merged = _emitted_metadata_dict(py_source, "DemoCell")
            assert merged["wraps"] == "x.y.Z", kind
            assert list(merged)[0] == "visibility", kind
            assert reg in py_source, kind

    def test_ganglion_merge_appends_after_emitter_keys(self) -> None:
        module = parse_s0ma(
            _ganglion_module('    metadata:\n        channel: "alerts"\n'),
            filename="demo_meta_mod.s0ma",
        )
        py_source = PythonEmitter(module_name="demo_meta_mod").emit(module)
        ast.parse(py_source)
        merged = _emitted_metadata_dict(py_source, "demo_watcher")
        assert merged["channel"] == "alerts"
        assert list(merged)[-1] == "channel"

    def test_no_metadata_emits_byte_identical_dict(self) -> None:
        # L-7: a declaration without ``metadata:`` emits exactly the
        # pre-DSL-M1 dict.
        module = parse_s0ma(_nerve_module(), filename="demo_meta_mod.s0ma")
        py_source = PythonEmitter(module_name="demo_meta_mod").emit(module)
        assert (
            'metadata={"visibility": "PUBLIC", '
            '"evaluates_at": "FUNCTION_BOUNDARY"},'
        ) in py_source


# ---------------------------------------------------------------------------
# The reserved-key constant cannot silently drift
# ---------------------------------------------------------------------------

#: Dict-key literals ``python_emitter.py`` writes INSIDE metadata
#: values (nested record dicts), not as top-level metadata keys. A new
#: key literal in the emitter must either join
#: ``RESERVED_COMPONENT_METADATA_KEYS`` (top-level metadata key) or be
#: consciously enumerated here (nested value structure).
_NESTED_VALUE_KEY_ALLOWLIST = frozenset({
    "name",        # provides_contracts entry dicts
    "expects",     # provides_contracts entry dicts
    "guarantees",  # provides_contracts entry dicts
    "contract",    # consumes_via_dict entry dicts
    "param",       # consumes_via_dict entry dicts
    # ``_emit_integration``-internal Python dicts (the per-helper
    # intents table and the manifest version key) — never rendered as
    # metadata keys into emitted source.
    "get_factory",
    "get_manifest",
    "get_smoke_test",
    "smoke_test_primary",
    "version",
})

_EMITTER_PATH = (
    Path(__file__).parent.parent
    / "src" / "s0ma_dsl" / "codegen" / "python_emitter.py"
)

#: Every ``"key": ...`` dict-item literal the emitter renders into
#: generated source (f-strings building metadata items and nested
#: record dicts alike).
_EMITTED_DICT_KEY_RE = re.compile(r'"(\w+)":\s')


def test_every_emitter_written_metadata_key_is_reserved() -> None:
    """Every metadata key the emitter writes is in the reserved set.

    Two layers, so the constant cannot silently drift:

    1. BEHAVIOURAL — emit a maximal corpus across the five emission
       shapes (nerve with every optional field, ganglion resolved and
       unresolved, MODEL/CONSTANT/TYPE cells with every optional
       field) and assert every top-level key of every emitted
       ``metadata=`` dict is a member of
       ``RESERVED_COMPONENT_METADATA_KEYS``.
    2. LEXICAL — scan ``python_emitter.py`` for every ``"key":``
       dict-item literal it can render; each must be in the reserved
       set or the consciously-maintained nested-value allowlist.

    A future emitter change that writes a new metadata key fails here
    until the key joins the constant (and therefore the
    ``METADATA_RESERVED_KEY`` guard) — exactly the drift the ADR-011
    §(a) reserved-key rule exists to prevent.
    """
    # --- Layer 1: behavioural corpus -----------------------------------
    nerve = NerveDecl(
        name="n_full",
        layer=Layer.APPLICATION,
        kind=Kind.SERVICE,
        visibility=Visibility.PUBLIC,
        intent="Maximal nerve.",
        expects="in",
        guarantees="out",
        evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
        body="def n_full():\n    return {}",
    )
    import dataclasses

    from s0ma_dsl.ast_nodes.nodes import ConsumesViaDictEntry, ProvidesEntry
    nerve = dataclasses.replace(
        nerve,
        provides=("op_a",),
        provides_entries=(
            ProvidesEntry(name="op_a", returns="r", expects="e", guarantees="g"),
        ),
        returns=("SomeCell",),
        raises=("SomeError",),
        abstract=True,
        interface=("op_a",),
        expected_exceptions=("ValueError",),
        deferred="stub",
        consumes_via_dict=(ConsumesViaDictEntry(contract="C", param="p"),),
    )
    cell_kwargs = {
        "layer": Layer.APPLICATION,
        "visibility": Visibility.PUBLIC,
        "intent": "Maximal cell.",
        "schema": "schema text",
        "invariants": "inv text",
        "category": "capability",
        "deferred": "stub",
    }
    class_cell = CellDecl(
        name="CFull", kind=Kind.MODEL,
        dataclass_invariants=("len(x) <= 1",),
        body="class CFull:\n    pass",
        **cell_kwargs,
    )
    constant_cell = CellDecl(
        name="K_FULL", kind=Kind.CONSTANT, body="K_FULL = 1", **cell_kwargs,
    )
    type_cell = CellDecl(
        name="TFull", kind=Kind.TYPE, body="TFull = str", **cell_kwargs,
    )
    ganglion = GanglionDecl(
        name="g_full",
        layer=Layer.APPLICATION,
        visibility=Visibility.INTERNAL,
        intent="Maximal ganglion.",
        observes=("n_full",),
        scope=EvaluatesAt.FUNCTION_BOUNDARY,
        priors="none",
        on_anomaly="log",
        deferred="stub",
        body="def g_full(signal):\n    return signal",
    )

    emitter = PythonEmitter(module_name="reserved_probe")

    class _FakeResolved:
        resolved_targets = ("reserved_probe::n_full",)

    rendered: list[str] = [
        emitter._build_nerve_metadata(nerve),
        emitter._emit_class_cell(class_cell),
        emitter._emit_constant_cell(constant_cell),
        emitter._emit_type_cell(type_cell),
        emitter._emit_ganglion(ganglion, None),  # unresolved observes arm
    ]
    emitter._resolved_observes = {"g_full": [_FakeResolved()]}
    rendered.append(emitter._emit_ganglion(ganglion, None))  # resolved arm

    seen_keys: set[str] = set()
    for chunk in rendered:
        if chunk.startswith("{"):
            seen_keys |= set(ast.literal_eval(chunk))
            continue
        for match in re.finditer(r"metadata=({.*}),\s*$", chunk, re.M):
            seen_keys |= set(ast.literal_eval(match.group(1)))
    assert seen_keys, "behavioural corpus rendered no metadata dicts"
    unexpected = seen_keys - RESERVED_COMPONENT_METADATA_KEYS
    assert not unexpected, (
        f"emitter wrote metadata keys outside "
        f"RESERVED_COMPONENT_METADATA_KEYS: {sorted(unexpected)} — add them "
        f"to the constant in ir/schema.py (ADR-011 §(a))"
    )

    # --- Layer 2: lexical scan ------------------------------------------
    # Scoped to the seven metadata-writing sites' owning functions (the
    # five emission shapes — A-6). A new metadata-writing FUNCTION must
    # be added here; a new key inside the known functions fails below.
    emitter_source = _EMITTER_PATH.read_text(encoding="utf-8")
    metadata_writers = {
        "_build_nerve_metadata",
        "_emit_class_cell",
        "_emit_constant_cell",
        "_emit_type_cell",
        "_emit_ganglion",
        "_emit_integration",
    }
    tree = ast.parse(emitter_source)
    scanned: list[str] = []
    found_writers: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in metadata_writers
        ):
            found_writers.add(node.name)
            segment = ast.get_source_segment(emitter_source, node)
            assert segment is not None
            scanned.append(segment)
    assert found_writers == metadata_writers, (
        f"metadata-writing functions missing from python_emitter.py: "
        f"{sorted(metadata_writers - found_writers)} — if one was renamed, "
        f"update this test's metadata_writers set"
    )
    written = set(_EMITTED_DICT_KEY_RE.findall("\n".join(scanned)))
    assert written >= {"visibility", "evaluates_at", "kind_detail"}, (
        "lexical scan stopped matching the emitter's dict-item style — "
        "update _EMITTED_DICT_KEY_RE"
    )
    stray = written - RESERVED_COMPONENT_METADATA_KEYS - _NESTED_VALUE_KEY_ALLOWLIST
    assert not stray, (
        f"python_emitter.py renders dict-key literals outside the reserved "
        f"set and the nested-value allowlist: {sorted(stray)} — either add "
        f"to RESERVED_COMPONENT_METADATA_KEYS (top-level metadata key) or "
        f"extend _NESTED_VALUE_KEY_ALLOWLIST (nested value structure)"
    )


def test_reserved_constant_matches_adr_enumeration() -> None:
    """The constant is exactly ADR-011 §(a)'s verified 27-key union."""
    assert frozenset(RESERVED_COMPONENT_METADATA_KEYS) == frozenset({
        "abstract", "category", "consumes_via_dict", "covered_by",
        "dataclass_invariants", "deferred", "evaluates_at",
        "expected_exceptions", "integration", "integration_helper",
        "integration_manifest", "interface", "invariants", "kind_detail",
        "observes", "observes_patterns", "on_anomaly", "priors", "provides",
        "provides_contracts", "raises", "resolved_observes", "returns",
        "schema", "scope", "serves_as", "value", "visibility",
    })
    assert len(RESERVED_COMPONENT_METADATA_KEYS) == 28
