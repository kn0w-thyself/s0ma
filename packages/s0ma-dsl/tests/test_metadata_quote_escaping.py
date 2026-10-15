"""Regression tests for M2 (feedback 5–6 plan).

The Python emitter must round-trip every metadata-field string verbatim
through the ``.py`` artifact, regardless of whether the string contains
``"``, ``'``, backslashes, or Unicode characters. Historically the
emitter hand-rolled escape sequences and corrupted ``\"`` (see
feedback-5.5 lines 90–176). M2 replaces every metadata interpolation
with :func:`_py_str_literal` (a thin wrapper over Python's ``repr``)
and adds a post-emission ``ast.parse`` build invariant.

This module covers:

* All six metadata fields: ``intent``, ``expects``, ``guarantees``,
  ``schema``, ``priors``, ``on_anomaly``.
* The post-emission ``validate_emitted_python`` invariant — a corrupted
  emitter must raise ``TranspilerInternalError`` rather than silently
  writing broken Python.
* End-to-end round-trip via ``ast.parse`` and ``exec()`` so we verify
  the emitted source is semantically faithful to the .s0ma source.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from s0ma_dsl.codegen import emit_python, python_emitter, validate_emitted_python
from s0ma_dsl.errors import TranspilerInternalError
from s0ma_dsl.parser.s0ma_parser import parse_s0ma

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES_DIR / "metadata_with_quotes.s0ma"


# ---------------------------------------------------------------------------
# Fixture-driven round-trip tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixture_module():
    """Parsed S0maModule for the metadata_with_quotes fixture."""
    src = FIXTURE.read_text(encoding="utf-8")
    mod = parse_s0ma(src, str(FIXTURE))
    return mod


@pytest.fixture()
def emitted_python(fixture_module):
    """Emitted Python source for the metadata_with_quotes fixture."""
    return emit_python(fixture_module, filename=str(FIXTURE))


def test_fixture_parses_without_error(fixture_module):
    """The .s0ma fixture parses cleanly (no escape-handling required)."""
    assert fixture_module is not None
    assert fixture_module.module.name == "metadata_with_quotes"


def test_emitted_python_parses(emitted_python):
    """Emitted .py output passes ast.parse — the M2 build invariant."""
    ast.parse(emitted_python, filename=str(FIXTURE))


def test_validate_emitted_python_accepts_valid(emitted_python, tmp_path):
    """``validate_emitted_python`` is a no-op for syntactically valid Python."""
    validate_emitted_python(tmp_path / "metadata_with_quotes.py", emitted_python)


def test_module_intent_round_trips_double_quote(fixture_module, emitted_python):
    """Module-level ``intent`` containing ``\\"`` survives through emission."""
    assert '\\"' in fixture_module.module.intent
    namespace = _exec_emitted(emitted_python)
    intent = _registered_module_intent(namespace, "metadata_with_quotes")
    assert intent == fixture_module.module.intent
    assert '\\"' in intent


def test_nerve_intent_round_trips(fixture_module, emitted_python):
    nerve = _find_nerve(fixture_module, "render")
    assert '\\"' in nerve.intent
    namespace = _exec_emitted(emitted_python)
    captured = _registered_component_field(namespace, "render", "intent")
    assert captured == nerve.intent


def test_nerve_expects_round_trips(fixture_module, emitted_python):
    """``expects`` is emitted into Contract(preconditions=[...])."""
    nerve = _find_nerve(fixture_module, "render")
    assert '\\"' in nerve.expects
    namespace = _exec_emitted(emitted_python)
    contract = _registered_component_field(namespace, "render", "contracts")
    assert contract is not None
    assert list(contract.preconditions) == [nerve.expects]


def test_nerve_guarantees_round_trips(fixture_module, emitted_python):
    """``guarantees`` is emitted into Contract(postconditions=[...])."""
    nerve = _find_nerve(fixture_module, "render")
    assert '\\"' in nerve.guarantees
    namespace = _exec_emitted(emitted_python)
    contract = _registered_component_field(namespace, "render", "contracts")
    assert contract is not None
    assert list(contract.postconditions) == [nerve.guarantees]


def test_cell_schema_round_trips(fixture_module, emitted_python):
    """``schema`` (cell metadata) survives quote characters."""
    cell = _find_cell(fixture_module, "HTML_ENTITY_TABLE")
    assert '\\"' in cell.schema
    namespace = _exec_emitted(emitted_python)
    schema_meta = _registered_constant_metadata_field(
        namespace, "HTML_ENTITY_TABLE", "schema"
    )
    assert schema_meta == cell.schema


def test_ganglion_priors_round_trips(fixture_module, emitted_python):
    """``priors`` (ganglion metadata) survives quote characters."""
    ganglion = _find_ganglion(fixture_module, "entity_observer")
    assert '\\"' in ganglion.priors
    namespace = _exec_emitted(emitted_python)
    priors_meta = _registered_component_metadata_field(
        namespace, "entity_observer", "priors"
    )
    assert priors_meta == ganglion.priors


def test_ganglion_on_anomaly_round_trips(fixture_module, emitted_python):
    """``on_anomaly`` (ganglion metadata) survives quote characters."""
    ganglion = _find_ganglion(fixture_module, "entity_observer")
    assert '\\"' in ganglion.on_anomaly
    namespace = _exec_emitted(emitted_python)
    on_anomaly_meta = _registered_component_metadata_field(
        namespace, "entity_observer", "on_anomaly"
    )
    assert on_anomaly_meta == ganglion.on_anomaly


def test_all_six_metadata_fields_present_in_emitted_python(emitted_python):
    """Sanity sweep: each of the six metadata fields appears in the output."""
    # intent, expects/guarantees (Contract), schema, priors, on_anomaly
    assert "intent=" in emitted_python
    assert "preconditions=[" in emitted_python  # expects
    assert "postconditions=[" in emitted_python  # guarantees
    assert "schema" in emitted_python
    assert "priors" in emitted_python
    assert "on_anomaly" in emitted_python


# ---------------------------------------------------------------------------
# Build-invariant tests for validate_emitted_python
# ---------------------------------------------------------------------------


def test_validate_emitted_python_rejects_invalid(tmp_path):
    """Syntactically invalid Python triggers TranspilerInternalError."""
    bad = "def broken(:\n    pass\n"
    with pytest.raises(TranspilerInternalError) as exc_info:
        validate_emitted_python(tmp_path / "broken.py", bad)
    assert "syntactically invalid" in str(exc_info.value)
    assert "broken.py" in str(exc_info.value)
    assert "transpiler bug" in str(exc_info.value).lower()


def test_emitter_validates_output_with_corrupted_helper(
    monkeypatch, fixture_module, tmp_path,
):
    """If ``_py_str_literal`` is corrupted to produce broken Python, the
    post-emission build invariant must catch it before the file is
    written. This is the canonical end-to-end M2 regression: an emitter
    bug becomes a loud build error, not a silent broken artifact.
    """

    def broken_literal(value: str) -> str:
        # Deliberately produce an unterminated string literal regardless
        # of input. A real bug like the original ``\"`` corruption would
        # produce broken Python only for some inputs; this guarantees
        # invalidity for the test.
        return '"' + value  # missing closing quote

    monkeypatch.setattr(python_emitter, "_py_str_literal", broken_literal)

    broken_output = emit_python(fixture_module, filename=str(FIXTURE))
    target = tmp_path / "broken.py"
    with pytest.raises(TranspilerInternalError):
        validate_emitted_python(target, broken_output)


# ---------------------------------------------------------------------------
# Helper-level unit tests (exercise the core invariant directly)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "plain text",
        'with "double" quotes',
        "with 'single' quotes",
        'mixed "double" and \'single\'',
        "trailing backslash\\",
        r"escape sequence \" in text",
        "newline\nhere",
        "unicode é è ñ ✓",
        "control \x01 char",
        "",
    ],
    ids=[
        "plain",
        "double_quotes",
        "single_quotes",
        "mixed_quotes",
        "trailing_backslash",
        "escaped_quote",
        "newline",
        "unicode",
        "control_char",
        "empty",
    ],
)
def test_py_str_literal_round_trip(value):
    """``_py_str_literal`` produces a literal that ``ast.parse`` accepts
    and that evaluates back to the original value."""
    literal = python_emitter._py_str_literal(value)
    expr = ast.parse(literal, mode="eval")
    parsed = eval(compile(expr, "<test>", mode="eval"))
    assert parsed == value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_nerve(module, name):
    for n in module.nerves:
        if n.name == name:
            return n
    raise AssertionError(f"nerve {name!r} not in fixture module")


def _find_cell(module, name):
    for c in module.cells:
        if c.name == name:
            return c
    raise AssertionError(f"cell {name!r} not in fixture module")


def _find_ganglion(module, name):
    for g in module.ganglia:
        if g.name == name:
            return g
    raise AssertionError(f"ganglion {name!r} not in fixture module")


def _exec_emitted(source):
    """Exec the emitted Python in a fresh namespace and return it.

    The runtime-bridge ``register_*`` functions write into a real
    registry. We don't introspect the registry here — we patch them
    out to capture their calls so the test does not depend on global
    state.
    """
    namespace = {}
    captured = {
        "module": None,
        "components": {},
        "constants": {},
    }

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

    # Stub out s0ma framework so module imports don't depend on full
    # runtime state.
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

    namespace.update({
        "register_module": fake_register_module,
        "register_constant": fake_register_constant,
        "register_type": fake_register_type,
        "register_relationship": fake_register_relationship,
        "register_test": fake_register_test,
    })

    # Strip the imports so we don't pull from the live runtime, then
    # exec with our stubs. Easier: provide a custom global namespace and
    # replace the import lines via simple substitution.
    safe = source
    safe = safe.replace(
        "from s0ma_dsl.runtime_bridge.registration import",
        "# stripped:",
    )
    safe = safe.replace("from s0ma.decorators import component", "")
    safe = safe.replace("from s0ma.types import ComponentKind, Layer", "")
    safe = safe.replace("from s0ma.models import Contract", "")
    namespace["component"] = stub_component
    # Provide minimal stand-ins for ComponentKind/Layer/Contract so the
    # source can be exec'd without the live framework.
    namespace["ComponentKind"] = _Enum("ComponentKind")
    namespace["Layer"] = _Enum("Layer")
    namespace["Contract"] = _Contract
    # Re-add the captured-callbacks after stripping.
    namespace.setdefault("register_module", fake_register_module)
    namespace.setdefault("register_constant", fake_register_constant)
    namespace.setdefault("register_type", fake_register_type)
    namespace.setdefault("register_relationship", fake_register_relationship)
    namespace.setdefault("register_test", fake_register_test)
    exec(compile(safe, "<emitted>", "exec"), namespace)
    namespace["__captured__"] = captured
    return namespace


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


class _Contract:
    def __init__(self, preconditions=(), postconditions=(), max_latency_ms=None):
        self.preconditions = preconditions
        self.postconditions = postconditions
        self.max_latency_ms = max_latency_ms


def _registered_module_intent(namespace, module_name):
    captured = namespace["__captured__"]
    assert captured["module"] is not None
    assert captured["module"]["name"] == module_name
    return captured["module"]["intent"]


def _registered_component_field(namespace, component_name, field):
    captured = namespace["__captured__"]
    assert component_name in captured["components"], (
        f"component {component_name!r} not registered; "
        f"have {list(captured['components'])}"
    )
    return captured["components"][component_name][field]


def _registered_component_metadata_field(namespace, component_name, key):
    md = _registered_component_field(namespace, component_name, "metadata")
    assert key in md, f"metadata key {key!r} not in {list(md)}"
    return md[key]


def _registered_constant_metadata_field(namespace, constant_name, key):
    captured = namespace["__captured__"]
    assert constant_name in captured["constants"]
    md = captured["constants"][constant_name]["metadata"]
    assert key in md, f"metadata key {key!r} not in {list(md)}"
    return md[key]
