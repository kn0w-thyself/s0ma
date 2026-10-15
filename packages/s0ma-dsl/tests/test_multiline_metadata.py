"""Regression tests for M14 (feedback 5–6 plan).

YAML literal-block-scalar (``|``) form for string-valued metadata
fields. Multi-line content must:

* parse without error,
* round-trip through the IR (still a plain ``str``, content includes
  ``\\n``),
* round-trip through the M2 emission pipeline into valid Python (the
  generated ``.py`` contains the multi-line value with newlines
  preserved),
* render legibly through ``s0ma inspect`` (indented across multiple
  lines, not collapsed or truncated).

The four canonical M14 tests live below:

* ``test_block_scalar_preserves_line_breaks``
* ``test_block_scalar_strips_common_indent``
* ``test_block_scalar_round_trips_through_python``
* ``test_block_scalar_works_for_all_six_fields``
"""

from __future__ import annotations

import ast
import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from s0ma_dsl.codegen import emit_python
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.parser.s0ma_parser import parse_s0ma

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES_DIR / "multiline_metadata.s0ma"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def parsed_module():
    src = FIXTURE.read_text(encoding="utf-8")
    return parse_s0ma(src, str(FIXTURE))


@pytest.fixture()
def emitted_python(parsed_module):
    return emit_python(parsed_module, filename=str(FIXTURE))


def _find(seq, name):
    for item in seq:
        if item.name == name:
            return item
    raise AssertionError(f"item {name!r} not found")


# ---------------------------------------------------------------------------
# M14's four canonical tests
# ---------------------------------------------------------------------------


def test_block_scalar_preserves_line_breaks(parsed_module):
    """A ``|``-block-scalar value contains literal ``\\n`` line breaks."""
    assert "\n" in parsed_module.module.intent

    nerve = _find(parsed_module.nerves, "render")
    assert "\n" in nerve.intent
    assert "\n" in nerve.expects
    assert "\n" in nerve.guarantees

    # First and last block-scalar lines survive verbatim.
    assert parsed_module.module.intent.startswith(
        "This module exercises the YAML literal-block-scalar form"
    )
    assert parsed_module.module.intent.rstrip().endswith(
        "inline-quoted form forces."
    )


def test_block_scalar_strips_common_indent(parsed_module):
    """The smallest interior indent is stripped (YAML literal-block rule).

    The cell's ``schema`` field has structurally-nested content:

        schema: |
        invariants: none
        covered_by: none
            Mapping[str, str] with the following structure:
                - key: a canonical rule name (...)
                - value: the rendered HTML fragment

            Keys MUST be globally unique within the module.

    The 8-space baseline (the smallest non-blank indent under the field)
    must be stripped, leaving a 4-space relative indent on the inner
    bulleted lines. The blank line must remain blank (no stray indent).
    """
    cell = _find(parsed_module.cells, "LOOKUP_TABLE")
    schema = cell.schema
    lines = schema.split("\n")

    # First line is at baseline indent — it must be flush left now.
    assert lines[0] == "Mapping[str, str] with the following structure:"

    # Sub-bulleted lines were indented 4 extra spaces in the source —
    # that relative indent must be preserved.
    assert lines[1] == "    - key: a canonical rule name (snake_case, ASCII-only)"
    assert lines[2] == "    - value: the rendered HTML fragment"

    # Blank line preserved as empty (not " " * baseline).
    assert "" in lines

    # Final line is back at baseline.
    assert "Keys MUST be globally unique within the module." in lines


def test_block_scalar_round_trips_through_python(parsed_module, emitted_python):
    """Build → emit → ast.parse → exec round-trips multi-line metadata.

    The emitted ``.py`` must:
      1. ``ast.parse`` cleanly (M2 build invariant).
      2. Contain the multi-line content as ``\\n``-escaped string literals.
      3. When exec'd, surface the original (newline-bearing) value.
    """
    # 1. Parses as Python.
    ast.parse(emitted_python, filename=str(FIXTURE))

    # 2. The literal contains ``\n`` (escaped) where the source had
    #    line breaks. We grep for a substring known to follow a newline
    #    in the source — it must appear with a leading ``\n``.
    assert "\\nThe block-scalar form lets authors write" in emitted_python
    assert "\\n  - the parser (line breaks survive)" in emitted_python

    # 3. Exec the emitted source with stubbed registries and confirm the
    #    captured ``intent`` contains real (un-escaped) newlines.
    captured = _exec_emitted(emitted_python)
    module_intent = captured["module"]["intent"]
    assert "\n" in module_intent
    assert module_intent == parsed_module.module.intent

    nerve_kw = captured["components"]["render"]
    assert "\n" in nerve_kw["intent"]
    assert nerve_kw["intent"] == _find(parsed_module.nerves, "render").intent

    contract = nerve_kw["contracts"]
    assert list(contract.preconditions)[0] == _find(
        parsed_module.nerves, "render"
    ).expects
    assert list(contract.postconditions)[0] == _find(
        parsed_module.nerves, "render"
    ).guarantees


def test_block_scalar_works_for_all_six_fields(parsed_module):
    """All six string-valued metadata fields accept ``|`` block-scalar form.

    Fields covered: ``intent``, ``expects``, ``guarantees``, ``schema``,
    ``priors``, ``on_anomaly``. Each must contain a literal ``\\n`` in
    the parsed IR — that is the test that the parser actually consumed
    a multi-line block, rather than (e.g.) silently truncating to the
    first line.
    """
    # intent — module, nerve, cell, ganglion all use ``|`` form
    assert "\n" in parsed_module.module.intent
    nerve = _find(parsed_module.nerves, "render")
    cell = _find(parsed_module.cells, "LOOKUP_TABLE")
    ganglion = _find(parsed_module.ganglia, "observer")
    assert "\n" in nerve.intent
    assert "\n" in cell.intent
    assert "\n" in ganglion.intent

    # expects + guarantees — nerve.render
    assert "\n" in nerve.expects
    assert "\n" in nerve.guarantees

    # schema — cell.LOOKUP_TABLE
    assert "\n" in cell.schema

    # priors + on_anomaly — ganglion.observer
    assert "\n" in ganglion.priors
    assert "\n" in ganglion.on_anomaly


# ---------------------------------------------------------------------------
# Backward-compatibility guards: existing inline-quoted metadata still works
# ---------------------------------------------------------------------------


def test_inline_quoted_form_still_works():
    """The pre-M14 ``intent: "..."`` inline form continues to parse.

    M14 must not regress the dominant single-line form — see fixture
    ``metadata_with_quotes.s0ma`` (the M2 round-trip fixture, all
    inline-quoted) which uses none of the ``|`` syntax.
    """
    src = (FIXTURES_DIR / "metadata_with_quotes.s0ma").read_text(encoding="utf-8")
    mod = parse_s0ma(src, "metadata_with_quotes.s0ma")
    # Single-line intents have no embedded newlines.
    assert "\n" not in mod.module.intent
    nerve = _find(mod.nerves, "render")
    assert "\n" not in nerve.intent
    assert "\n" not in nerve.expects


# ---------------------------------------------------------------------------
# Error-handling guards: malformed block scalars produce clear errors
# ---------------------------------------------------------------------------


def test_empty_block_scalar_errors():
    """A ``|`` followed by no indented content must error (no silent failure).

    Per the M14 design, the parser refuses to silently treat
    ``intent: |`` followed by an immediate next field (or end-of-decl)
    as an empty intent — that would defeat the purpose of distinguishing
    a deliberate block scalar from a typo.
    """
    src = (
        "module bad_empty_block\n"
        "    layer: PRESENTATION\n"
        "    version: 1.0.0\n"
        "    intent: |\n"
        "    exports: [foo]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
    )
    with pytest.raises(S0maParseError) as excinfo:
        parse_s0ma(src, "bad_empty_block.s0ma")
    msg = str(excinfo.value)
    assert "block-scalar" in msg.lower()
    assert "intent" in msg


# ---------------------------------------------------------------------------
# Helpers — run the emitted Python in an isolated namespace
# ---------------------------------------------------------------------------


def _exec_emitted(source: str) -> dict:
    """Exec the emitted Python with stubbed registry callbacks."""
    captured = {"module": None, "components": {}, "constants": {}}

    def fake_register_module(**kwargs):
        captured["module"] = kwargs

    def fake_register_constant(**kwargs):
        captured["constants"][kwargs.get("name")] = kwargs

    def fake_register_type(**kwargs):
        captured["constants"][kwargs.get("name")] = kwargs

    def fake_register_relationship(**kwargs):
        pass

    def fake_register_test(**kwargs):
        pass

    class _StubComponent:
        def __init__(self, **kwargs):
            self._kwargs = kwargs

        def __call__(self, fn):
            captured["components"][self._kwargs["name"]] = {
                **self._kwargs,
                "_callable": fn,
            }
            return fn

    def stub_component(**kwargs):
        return _StubComponent(**kwargs)

    class _Contract:
        def __init__(self, preconditions=(), postconditions=(), max_latency_ms=None):
            self.preconditions = preconditions
            self.postconditions = postconditions
            self.max_latency_ms = max_latency_ms

    class _EnumMember:
        def __init__(self, name):
            self._name = name

        def __getattr__(self, item):
            return _EnumMember(f"{self._name}.{item}")

        def __repr__(self):
            return self._name

    class _Enum:
        def __init__(self, name):
            self._name = name

        def __getattr__(self, item):
            return _EnumMember(f"{self._name}.{item}")

    safe = source
    safe = safe.replace(
        "from s0ma_dsl.runtime_bridge.registration import",
        "# stripped:",
    )
    safe = safe.replace("from s0ma.decorators import component", "")
    safe = safe.replace("from s0ma.types import ComponentKind, Layer", "")
    safe = safe.replace("from s0ma.models import Contract", "")

    namespace = {
        "register_module": fake_register_module,
        "register_constant": fake_register_constant,
        "register_type": fake_register_type,
        "register_relationship": fake_register_relationship,
        "register_test": fake_register_test,
        "component": stub_component,
        "ComponentKind": _Enum("ComponentKind"),
        "Layer": _Enum("Layer"),
        "Contract": _Contract,
    }
    exec(compile(safe, "<emitted>", "exec"), namespace)
    return captured


# ---------------------------------------------------------------------------
# Inspect pretty-printer integration — multi-line metadata renders cleanly
# ---------------------------------------------------------------------------


def test_inspect_renders_multiline_metadata_indented(parsed_module):
    """The ``s0ma inspect`` text renderer prints multi-line fields as
    indented blocks rather than truncating or escaping them."""
    from s0ma_dsl.cli.main import S0maCLI
    from s0ma_dsl.ir import build_ir

    ir_doc = build_ir(parsed_module, source_file=str(FIXTURE))
    doc = ir_doc.to_dict()

    cli = S0maCLI()
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli._print_inspect_text(doc)
    out = buf.getvalue()

    # The module intent prints across multiple indented lines.
    assert "  Intent:" in out
    assert "    This module exercises the YAML literal-block-scalar form" in out
    assert "    The block-scalar form lets authors write multi-line metadata" in out

    # Component intents — each line of the nerve render's intent appears
    # on its own indented line.
    assert "    Render a value into a presentation-safe string." in out
    assert "    Multi-line intent is preserved exactly through:" in out
    assert "      - the parser (line breaks survive)" in out
