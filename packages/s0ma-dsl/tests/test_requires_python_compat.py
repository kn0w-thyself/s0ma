"""Tests for the ``PARSE_GRAMMAR_FORWARD_INCOMPAT`` pass (M-12 / POST-8).

The pre-0.16.0 transpiler ran every body through Python 3.12's
``ast.parse`` and emitted the body verbatim. A project pinned
``requires-python = ">=3.11"`` that authored 3.12-only grammar
(PEP 701 nested-quote f-strings, walrus-in-comprehension, PEP 695
type-parameter syntax) would compile cleanly on a 3.12 dev box and
fail at import on a 3.11 consumer interpreter.

M-12 (POST-8, 0.16.0) closes the gap by adding a forward-compat
pass to ``IntraModuleValidator`` that walks each authored body's
AST and flags every known 3.12-only construct family. The pass is
gated on the project's declared ``[project].requires-python`` range:
fire only when the range explicitly admits 3.11; stay silent for
projects pinned ``>=3.12`` (they have opted in to the newer
grammar) or projects with no declared floor (conservative default).

The test plan covers ten invariants:

1. Project pinned ``>=3.11`` with a nested-quote f-string in a nerve
   body fires ``PARSE_GRAMMAR_FORWARD_INCOMPAT``.
2. Project pinned ``>=3.12`` with the same body fires nothing
   (the project has opted in).
3. Walrus-in-comprehension caught when pinned to 3.11.
4. PEP 695 type-parameter syntax (``def foo[T](...) -> T``) caught
   when pinned to 3.11.
5. Multiple 3.12-only constructs in one body each get their own
   diagnostic (no de-duplication / no early-exit).
6. Plain Python (no 3.12-only features) → no error regardless of pin.
7. ``requires-python`` absent → no check (conservative default).
8. ``requires-python = ">=3.13"`` → no check (higher than 3.12).
9. Cell body, ganglion body, and test body all checked (not just
   nerve).
10. AST-parse failure → falls back gracefully (no double-report;
    the existing ``PARSE_ERROR`` pass owns the diagnostic).

See:
  - ``src/s0ma_dsl/semantic/python_compat.py``
  - ``src/s0ma_dsl/semantic/validator.py`` (``_check_python_grammar_compat``)
  - ``src/s0ma_dsl/project.py`` (``S0maProject.requires_python``)
"""

from __future__ import annotations

import sys
from textwrap import dedent

import pytest

from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.semantic.python_compat import (
    flag_python_312_only,
    requires_python_includes_311,
)
from s0ma_dsl.semantic.validator import validate_module

# Some fixtures below embed 3.12-only grammar (PEP 701 nested-quote
# f-strings, PEP 695 type params). On a 3.11 host the stdlib ``ast.parse``
# rejects that grammar before the forward-compat pass can walk it, and the
# PARSE_ERROR pass owns the diagnostic instead — the designed graceful
# fallback (invariant 10, ``TestASTParseFailureGraceful``). The compat
# pass's own diagnostics are therefore only observable on a 3.12+ host.
_REQUIRES_312_HOST = pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason="fixture embeds 3.12-only grammar; a 3.11 host raises "
    "PARSE_ERROR before the forward-compat pass runs (invariant 10)",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _parse(source: str, filename: str = "fixture.s0ma"):
    """Parse a ``.s0ma`` source string into a S0maModule."""
    module, _ = parse_s0ma_with_warnings(
        source, filename, mode=StrictnessMode.DEV,
    )
    return module


def _diagnostics(
    source: str,
    *,
    requires_python: tuple[str, ...] | None,
    filename: str = "fixture.s0ma",
):
    """Parse + run the full intra-module validator, returning diagnostics."""
    module = _parse(source, filename)
    return validate_module(
        module,
        mode=StrictnessMode.DEV,
        filename=filename,
        requires_python=requires_python,
    )


def _compat_only(diagnostics):
    """Return only the PARSE_GRAMMAR_FORWARD_INCOMPAT subset."""
    return [
        d for d in diagnostics
        if d.code == "PARSE_GRAMMAR_FORWARD_INCOMPAT"
    ]


# ---------------------------------------------------------------------------
# Module-shape factory: produce ``.s0ma`` text with a given body.
# ---------------------------------------------------------------------------


_NERVE_TEMPLATE = """\
module compat_fixture
    layer: DOMAIN
    version: 1.0.0
    intent: "Synthetic fixture for the requires-python compat pass."
    exports: [demo]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve demo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Demo nerve with a body under compat test."
    expects: "Any input."
    guarantees: "Returns a value."
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
{body}
""".lstrip()


_CELL_TEMPLATE = """\
module compat_fixture_cell
    layer: DOMAIN
    version: 1.0.0
    intent: "Synthetic fixture exercising the compat pass on a cell body."
    exports: [DemoModel]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell DemoModel :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "Demo cell with a body under compat test."
    schema: "Has the relevant 3.12-only constructs."
    invariants: none
    covered_by: none
    ---
{body}
""".lstrip()


_GANGLION_TEMPLATE = """\
module compat_fixture_ganglion
    layer: FRAMEWORK
    version: 1.0.0
    intent: "Synthetic fixture exercising the compat pass on a ganglion body."
    exports: [demo_ganglion]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve demo :: FRAMEWORK
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Stub nerve so the ganglion's observes resolves."
    expects: "Any input."
    guarantees: "Returns a value."
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
    def demo():
        return None

ganglion demo_ganglion :: FRAMEWORK
    kind: EVALUATOR
    visibility: PUBLIC
    intent: "Demo ganglion with a body under compat test."
    observes: [demo]
    priors: ["demo body has been verified"]
    scope: SUBSYSTEM
    on_anomaly: "Log and continue"
    forbids: none
    depends_on: none
    covered_by: none
    ---
{body}
""".lstrip()


_TEST_TEMPLATE = """\
module compat_fixture_test
    layer: DOMAIN
    version: 1.0.0
    intent: "Synthetic fixture exercising the compat pass on a test body."
    exports: [demo]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve demo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Demo nerve under test."
    expects: "Any input."
    guarantees: "Returns a value."
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
    def demo():
        return 42

test test_demo :: DOMAIN
    intent: "Demo test that exercises 3.12-only grammar in its body."
    tests: [demo]
    expects: none
    depends_on: none
    mocks: none
    ---
{body}
""".lstrip()


def _indent_body(body: str, indent: str = "    ") -> str:
    """Indent every line of *body* by *indent* (four spaces by default)."""
    return "\n".join(indent + line for line in body.splitlines())


# ---------------------------------------------------------------------------
# Test 1 + 2 — nested-quote f-string gated by version-range
# ---------------------------------------------------------------------------


@_REQUIRES_312_HOST
class TestNestedQuoteFString:
    """Nested-quote f-strings fire only when 3.11 is in the range."""

    def _nerve_with_nested_fstring(self) -> str:
        body = _indent_body(dedent("""
            def demo(x):
                inner = "value"
                return f"outer {f"inner_{inner}"}"
        """).strip())
        return _NERVE_TEMPLATE.format(body=body)

    def test_pinned_311_fires(self) -> None:
        source = self._nerve_with_nested_fstring()
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        assert len(diagnostics) >= 1
        diag = diagnostics[0]
        assert diag.code == "PARSE_GRAMMAR_FORWARD_INCOMPAT"
        assert diag.severity == "error"
        assert diag.context["construct_kind"] == "nested_quote_fstring"
        assert "nerve" in diag.message.lower()
        assert "3.11" in diag.message
        assert "3.12" in diag.message

    def test_pinned_312_silent(self) -> None:
        source = self._nerve_with_nested_fstring()
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.12",),
        ))
        assert diagnostics == [], (
            f"Project pinned >=3.12 has opted in to 3.12 grammar; the "
            f"compat pass must stay silent. Got: {diagnostics}"
        )


# ---------------------------------------------------------------------------
# Test 3 — walrus-in-comprehension
# ---------------------------------------------------------------------------


class TestWalrusInComprehension:
    """Walrus inside a comprehension is flagged when pinned to 3.11."""

    def test_walrus_in_comprehension_fires(self) -> None:
        body = _indent_body(dedent("""
            def demo(xs):
                return [(y := x * 2) for x in xs]
        """).strip())
        source = _NERVE_TEMPLATE.format(body=body)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        assert len(diagnostics) >= 1
        kinds = {d.context["construct_kind"] for d in diagnostics}
        assert "walrus_in_comprehension" in kinds


# ---------------------------------------------------------------------------
# Test 4 — PEP 695 type-parameter syntax
# ---------------------------------------------------------------------------


@_REQUIRES_312_HOST
class TestPEP695TypeParams:
    """PEP 695 ``def foo[T](x: T) -> T`` syntax flagged on 3.11-admitting ranges."""

    def test_pep_695_function_type_param_fires(self) -> None:
        # PEP 695 syntax on the inner ``def`` inside the body. The
        # outer ``def demo()`` cannot use the syntax directly because
        # the parser would reject ``def demo[T]`` at the body's first
        # column (PEP 695 needs the parser to be 3.12-aware at the
        # ``def`` keyword level — and we are 3.12 here at transpile
        # time). So we use an inner function shape.
        body = _indent_body(dedent("""
            def demo(items):
                def identity[T](value: T) -> T:
                    return value
                return [identity(x) for x in items]
        """).strip())
        source = _NERVE_TEMPLATE.format(body=body)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        assert len(diagnostics) >= 1, (
            f"Expected PARSE_GRAMMAR_FORWARD_INCOMPAT for PEP 695 type "
            f"params; got {diagnostics}"
        )
        kinds = {d.context["construct_kind"] for d in diagnostics}
        assert "pep_695_type_params" in kinds


# ---------------------------------------------------------------------------
# Test 5 — multiple constructs in one body each fire
# ---------------------------------------------------------------------------


@_REQUIRES_312_HOST
class TestMultipleConstructsEachFire:
    """Two 3.12-only constructs in one body produce two diagnostics."""

    def test_walrus_and_pep_695_together(self) -> None:
        body = _indent_body(dedent("""
            def demo(items):
                def identity[T](value: T) -> T:
                    return value
                return [(y := identity(x)) for x in items]
        """).strip())
        source = _NERVE_TEMPLATE.format(body=body)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        kinds = {d.context["construct_kind"] for d in diagnostics}
        # Both constructs must be flagged. There can be more than one
        # walrus / type-params depending on the body; we only assert
        # the set membership.
        assert "walrus_in_comprehension" in kinds, (
            f"Walrus diagnostic missing; got kinds={kinds}"
        )
        assert "pep_695_type_params" in kinds, (
            f"PEP 695 diagnostic missing; got kinds={kinds}"
        )


# ---------------------------------------------------------------------------
# Test 6 — plain Python under any pin
# ---------------------------------------------------------------------------


class TestPlainPythonSilent:
    """Plain 3.11-compatible Python never fires the compat pass."""

    @pytest.mark.parametrize(
        "requires_python",
        [
            None,
            (">=3.11",),
            (">=3.11", "<3.13"),
            (">=3.12",),
            (">=3.13",),
        ],
    )
    def test_plain_python_no_diagnostic(self, requires_python) -> None:
        body = _indent_body(dedent("""
            def demo(x):
                # plain 3.11 grammar; mixed-quote f-string OK
                label = f"value={x!r}"
                names = [n.lower() for n in ["A", "B", "C"]]
                return label, names
        """).strip())
        source = _NERVE_TEMPLATE.format(body=body)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=requires_python,
        ))
        assert diagnostics == [], (
            f"Plain Python should not fire any compat diagnostic; got "
            f"{diagnostics}"
        )


# ---------------------------------------------------------------------------
# Test 7 — requires-python absent
# ---------------------------------------------------------------------------


class TestRequiresPythonAbsent:
    """An absent ``[project].requires-python`` suppresses the pass."""

    def test_walrus_silent_when_floor_absent(self) -> None:
        body = _indent_body(dedent("""
            def demo(xs):
                return [(y := x * 2) for x in xs]
        """).strip())
        source = _NERVE_TEMPLATE.format(body=body)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=None,
        ))
        assert diagnostics == [], (
            f"Project without [project].requires-python has not declared "
            f"a Python floor; the compat pass must stay silent. Got: "
            f"{diagnostics}"
        )


# ---------------------------------------------------------------------------
# Test 8 — pinned >=3.13 (higher than 3.12)
# ---------------------------------------------------------------------------


class TestPinnedHigherThan312:
    """``requires-python = ">=3.13"`` suppresses the pass (3.11 excluded)."""

    def test_walrus_silent_when_pinned_313(self) -> None:
        body = _indent_body(dedent("""
            def demo(xs):
                return [(y := x * 2) for x in xs]
        """).strip())
        source = _NERVE_TEMPLATE.format(body=body)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.13",),
        ))
        assert diagnostics == [], (
            f"Project pinned >=3.13 has opted in past 3.12; the compat "
            f"pass must stay silent. Got: {diagnostics}"
        )


# ---------------------------------------------------------------------------
# Test 9 — cell / ganglion / test bodies all checked
# ---------------------------------------------------------------------------


class TestNonNerveBodiesAlsoChecked:
    """The compat pass walks every body kind, not just nerve bodies."""

    def _walrus_body(self) -> str:
        return _indent_body(dedent("""
            def _demo_helper():
                xs = [1, 2, 3]
                return [(y := x * 2) for x in xs]
            DemoModel = _demo_helper()
        """).strip())

    def test_cell_body_checked(self) -> None:
        body = _indent_body(dedent("""
            class DemoModel:
                def __init__(self):
                    xs = [1, 2, 3]
                    self.values = [(y := x * 2) for x in xs]
        """).strip())
        source = _CELL_TEMPLATE.format(body=body)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        assert any(
            d.context["declaration_kind"] == "cell" for d in diagnostics
        ), (
            f"Expected at least one PARSE_GRAMMAR_FORWARD_INCOMPAT with "
            f"declaration_kind='cell'; got {diagnostics}"
        )

    def test_ganglion_body_checked(self) -> None:
        body = _indent_body(dedent("""
            def demo_ganglion(observations):
                xs = [1, 2, 3]
                return [(y := x * 2) for x in xs]
        """).strip())
        source = _GANGLION_TEMPLATE.format(body=body)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        assert any(
            d.context["declaration_kind"] == "ganglion" for d in diagnostics
        ), (
            f"Expected at least one PARSE_GRAMMAR_FORWARD_INCOMPAT with "
            f"declaration_kind='ganglion'; got {diagnostics}"
        )

    def test_test_body_checked(self) -> None:
        body = _indent_body(dedent("""
            def test_demo():
                xs = [1, 2, 3]
                vals = [(y := x * 2) for x in xs]
                assert vals == [2, 4, 6]
        """).strip())
        source = _TEST_TEMPLATE.format(body=body)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        assert any(
            d.context["declaration_kind"] == "test" for d in diagnostics
        ), (
            f"Expected at least one PARSE_GRAMMAR_FORWARD_INCOMPAT with "
            f"declaration_kind='test'; got {diagnostics}"
        )


# ---------------------------------------------------------------------------
# Test 10 — AST-parse failure falls back gracefully
# ---------------------------------------------------------------------------


class TestASTParseFailureGraceful:
    """An unparseable body does not produce a double-report.

    The outer ``PARSE_ERROR`` pass owns the diagnostic for a body
    that ``ast.parse`` rejects (the parser's body extractor already
    runs a body-shape syntax check). The compat pass intentionally
    skips the AST walk on ``SyntaxError`` so two diagnostics do not
    fire for the same root cause.

    This test asserts the compat pass alone — not the wider
    PARSE_ERROR pipeline — handles the unparseable body without
    crashing or emitting ``PARSE_GRAMMAR_FORWARD_INCOMPAT``.
    """

    def test_unparseable_body_no_compat_diagnostic(self) -> None:
        # ``flag_python_312_only`` is the body-level entry point;
        # call it directly to exercise the AST-parse fallback.
        findings = flag_python_312_only("def demo(:\n    pass")
        # Empty findings (no double-report) is the contract.
        assert findings == [], (
            f"Unparseable body must not produce compat findings (the "
            f"existing PARSE_ERROR pass owns the diagnostic). Got: "
            f"{findings}"
        )


# ---------------------------------------------------------------------------
# Version-range predicate sanity checks (helper-level)
# ---------------------------------------------------------------------------


class TestRequiresPythonIncludes311Predicate:
    """Direct tests of the version-range predicate."""

    @pytest.mark.parametrize(
        "requires_python,expected",
        [
            (None, False),
            ((), False),
            ((">=3.11",), True),
            ((">=3.10",), True),
            ((">=3.11", "<3.13"), True),
            ((">=3.11", "<4"), True),
            ((">=3.12",), False),
            ((">=3.13",), False),
            ((">=3.11", "<3.11"), False),  # contradictory range
            (("==3.11",), True),
            (("==3.11.5",), True),
            (("==3.12",), False),
            (("!=3.11",), False),
            (("~=3.11",), True),
            (("~=3.12",), False),
            # ``~=3.11.5`` means ``>=3.11.5, <3.12`` — 3.11.0 is below
            # the floor so the range does NOT include the 3.11 we
            # check against (we pin to 3.11.0 as the predicate's
            # canonical 3.11 representative).
            (("~=3.11.5",), False),
        ],
    )
    def test_predicate(self, requires_python, expected) -> None:
        assert requires_python_includes_311(requires_python) is expected
