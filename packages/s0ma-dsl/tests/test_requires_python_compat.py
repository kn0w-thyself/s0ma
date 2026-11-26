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

import importlib.util
import sys
from collections import Counter
from pathlib import Path
from textwrap import dedent

import pytest

from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maError
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
# Test 11 — the nested-quote scan starts only at real f-string openers
# ---------------------------------------------------------------------------


def _nested_quote_findings(body: str):
    """Return only the nested-quote f-string findings for *body*."""
    return [
        f for f in flag_python_312_only(body)
        if f.kind == "nested_quote_fstring"
    ]


class TestFStringOpenerIsARealStringStart:
    """An ``f`` before a quote opens an f-string only as a string prefix.

    A name or a string that ends in ``f`` right before a quote is not an
    f-string opener, even when a brace with a quote inside follows on the
    same line. Every shape below is valid Python 3.11 and must check clean.
    """

    @pytest.mark.parametrize(
        "body",
        [
            # A dict key ending in ``f`` before ``": {"``.
            'x = {"brief": {"asks": 1}}',
            'return {"brief": {"asks": 1}}',
            # A JSON-style key ending in ``f`` before ``": {"``.
            'q = {"defaultBranchRef": {"name": "main"}}',
            # A string value ending in ``f`` before ``"}, {"``.
            'x = [{"id": "brief"}, {"id": "other"}]',
            # A subscript key ending in ``f``, then a dict later on the line.
            'ok = flag["ref"] == {"usage": {}}',
            # A string that merely contains ``f"`` text.
            'x = {"a f": {"b": 1}}',
            'x = ["self", {"a": 1}]',
            # Single-quote variants.
            "x = {'brief': {'asks': 1}}",
            "x = [{'id': 'brief'}, {'id': 'other'}]",
            "ok = flag['ref'] == {'usage': {}}",
            # Triple-quote variants.
            'x = {"""brief""": {"""asks""": 1}}',
            "x = {'''brief''': {'''asks''': 1}}",
            # Other string prefixes that are not f-strings.
            'x = {rb"brief": {b"asks": 1}}',
            # A real f-string with mismatched quotes stays valid on 3.11.
            'x = f"{d[\'brief\']}" + str({"a": {"b": 1}})',
        ],
    )
    def test_not_an_fstring_checks_clean(self, body: str) -> None:
        assert _nested_quote_findings(body) == []

    def test_dict_key_shape_checks_clean_in_a_nerve(self) -> None:
        body = _indent_body(dedent("""
            def demo(x):
                return {"brief": {"asks": 1}}
        """).strip())
        source = _NERVE_TEMPLATE.format(body=body)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        assert diagnostics == [], (
            f"A dict key ending in 'f' is not an f-string opener; got "
            f"{diagnostics}"
        )

    @pytest.mark.parametrize(
        "body,column",
        [
            ('x = f"outer {f"inner"}"', 4),
            ('x = f"{d["k"]}"', 4),
            ('x = F"{d["k"]}"', 4),
            ("x = f'{d['k']}'", 4),
            ('x = f"""{d["""k"""]}"""', 4),
            # Prefixed f-strings, in either order and either case. The
            # column is the ``f`` of the prefix.
            ('x = rf"{d["k"]}"', 5),
            ('x = fr"{d["k"]}"', 4),
            ('x = Rf"{d["k"]}"', 5),
            ('x = fR"{d["k"]}"', 4),
            # A real one after a decoy on the same line.
            ('x = {"brief": f"{d["k"]}"}', 14),
        ],
    )
    def test_real_nested_quote_fstring_still_fires(
        self, body: str, column: int,
    ) -> None:
        findings = _nested_quote_findings(body)
        assert len(findings) == 1, findings
        assert findings[0].line == 1
        assert findings[0].column == column
        assert "PEP 701" in findings[0].description

    def test_real_fstring_on_a_later_line_keeps_its_line(self) -> None:
        body = 'a = {"brief": {"asks": 1}}\nb = f"{d["k"]}"\n'
        findings = _nested_quote_findings(body)
        assert [(f.line, f.column) for f in findings] == [(2, 4)]

    @pytest.mark.parametrize(
        "body",
        [
            # An unclosed bracket at the end of the body.
            'x = f"{d["k"]}"\ny = (1,\n',
            # An unindent that matches no outer level.
            'x = f"{d["k"]}"\nif x:\n        a = 1\n    b = 2\n',
        ],
    )
    def test_untokenizable_body_does_not_crash(self, body: str) -> None:
        # The text scan has always run on bodies ``ast.parse`` rejects,
        # and it never raises. A body the tokenizer gives up on keeps the
        # openers it found before the failure.
        findings = _nested_quote_findings(body)
        assert [(f.line, f.column) for f in findings] == [(1, 4)]

    def test_untokenizable_body_without_fstrings_is_clean(self) -> None:
        assert flag_python_312_only('x = {"brief": (\n') == []


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


# ---------------------------------------------------------------------------
# The reported line is the line in the .s0ma file
# ---------------------------------------------------------------------------


def _line_of(source: str, needle: str) -> int:
    """The 1-based line of the only line in *source* that contains *needle*."""
    hits = [
        number
        for number, line in enumerate(source.splitlines(), start=1)
        if needle in line
    ]
    assert len(hits) == 1, f"{needle!r} is on lines {hits}"
    return hits[0]


class TestReportedLine:
    """A finding names the line where the offending body line sits.

    Every template here has a long header, so a line counted from the
    header instead of from the body lands many lines too early.
    """

    _WALRUS = "return [(y := x * 2) for x in xs]"

    def _nerve_source(self, *, leading_blank: bool = False) -> str:
        body = _indent_body(dedent(f"""
            def demo(xs):
                total = 0
                count = 0
                {self._WALRUS}
        """).strip())
        if leading_blank:
            body = "\n" + body
        return _NERVE_TEMPLATE.format(body=body)

    def test_nerve_line_is_the_body_line(self) -> None:
        source = self._nerve_source()
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        assert [d.line for d in diagnostics] == [_line_of(source, self._WALRUS)]
        assert diagnostics[0].context["body_line"] == 4

    def test_leading_blank_body_line_is_counted(self) -> None:
        source = self._nerve_source(leading_blank=True)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        assert [d.line for d in diagnostics] == [_line_of(source, self._WALRUS)]

    @pytest.mark.parametrize(
        "template,kind",
        [
            ("_CELL_TEMPLATE", "cell"),
            ("_GANGLION_TEMPLATE", "ganglion"),
            ("_TEST_TEMPLATE", "test"),
        ],
    )
    def test_other_kinds_report_the_body_line(self, template, kind) -> None:
        body = _indent_body(dedent(f"""
            def demo_{kind}(xs):
                xs = [1, 2, 3]
                {self._WALRUS}
        """).strip())
        if kind == "cell":
            body = _indent_body(dedent(f"""
                class DemoModel:
                    def __init__(self, xs):
                        {self._WALRUS}
            """).strip())
        source = globals()[template].format(body=body)
        diagnostics = [
            d for d in _compat_only(_diagnostics(
                source, requires_python=(">=3.11",),
            ))
            if d.context["declaration_kind"] == kind
        ]
        assert [d.line for d in diagnostics] == [_line_of(source, self._WALRUS)]

    @_REQUIRES_312_HOST
    def test_nested_fstring_line_is_the_body_line(self) -> None:
        needle = 'return f"outer {f"inner_{inner}"}"'
        body = _indent_body(dedent(f"""
            def demo(x):
                inner = "value"
                label = "x"
                {needle}
        """).strip())
        source = _NERVE_TEMPLATE.format(body=body)
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        assert [d.line for d in diagnostics] == [_line_of(source, needle)]

    def test_matches_the_parser_body_start_line(self) -> None:
        """The validator's first body line equals the one the parser records."""
        from s0ma_dsl.parser import s0ma_parser
        from s0ma_dsl.semantic.validator import _body_first_line

        source = self._nerve_source(leading_blank=True)
        raw = {
            decl.header_names[0]: decl.body_start_line
            for decl in s0ma_parser._split_declarations(source, "fixture.s0ma")
        }
        nerve = _parse(source).nerves[0]
        assert nerve.body is not None
        assert _body_first_line(nerve.location, nerve.body) == raw["demo"]


# ---------------------------------------------------------------------------
# The body fills the last lines of its declaration
# ---------------------------------------------------------------------------


_REPOSITORY = Path(__file__).resolve().parents[3]

#: Declaration kinds with a body, and the module attribute that lists them.
_BODY_KINDS: dict[str, str] = {
    "nerve": "nerves",
    "cell": "cells",
    "ganglion": "ganglia",
    "test": "tests",
    "helper": "helpers",
}


def _authored_trees() -> tuple[str, ...]:
    """The trees the gate's ``authored-lines`` stage reads."""
    path = _REPOSITORY / "scripts" / "check_authored_lines.py"
    spec = importlib.util.spec_from_file_location("_authored_lines_trees", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return tuple(module.TREES)


def _body_line_mismatches(source: str, filename: str) -> tuple[int, list[str]]:
    """Compare each body's first line with the parser's ``body_start_line``.

    Returns how many bodies were compared and one message per mismatch.
    A name that two declarations of one kind share is skipped, since it
    cannot be matched to one raw declaration.
    """
    from s0ma_dsl.parser import s0ma_parser
    from s0ma_dsl.semantic.validator import _body_first_line

    module, _ = parse_s0ma_with_warnings(source, filename, mode=StrictnessMode.DEV)
    starts: dict[tuple[str, str], int | None] = {}
    seen: Counter[tuple[str, str]] = Counter()
    for raw in s0ma_parser._split_declarations(source, filename):
        if raw.decl_type in _BODY_KINDS and raw.body:
            key = (raw.decl_type, raw.header_names[0])
            seen[key] += 1
            starts[key] = raw.body_start_line
    compared = 0
    problems: list[str] = []
    for kind, attribute in _BODY_KINDS.items():
        for decl in getattr(module, attribute):
            key = (kind, decl.name)
            if not decl.body or seen[key] != 1:
                continue
            if kind == "cell" and decl.embedded_file_path is not None:
                continue
            compared += 1
            derived = _body_first_line(decl.location, decl.body)
            if derived != starts[key]:
                problems.append(
                    f"{_shown(filename)}: {kind} {decl.name}: the validator counts "
                    f"the body from line {derived}, the parser recorded "
                    f"line {starts[key]}"
                )
    return compared, problems


def _shown(filename: str) -> str:
    """*filename* relative to the repository when it lies inside it."""
    path = Path(filename)
    if path.is_absolute() and path.is_relative_to(_REPOSITORY):
        return str(path.relative_to(_REPOSITORY))
    return filename


#: A short second declaration, so a body has something after it.
_NEXT_DECLARATION = """\
test test_other :: DOMAIN
    intent: "A declaration that follows the body under test."
    tests: [demo]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_other():
        assert True
"""

_WALRUS_LINE = "return [(y := x * 2) for x in xs]"


def _shaped_body(*, trailing: str = "", inside: str = "") -> str:
    """A nerve body with a finding on its third line.

    *inside* is put between the first two lines. *trailing* follows the
    body verbatim.
    """
    lines = ["    def demo(xs):", "        total = 0"]
    if inside:
        lines.insert(1, inside)
    lines.append(f"        {_WALRUS_LINE}")
    return "\n".join(lines) + trailing


#: Each shape: the text after ``---`` up to the end of the file.
_BODY_SHAPES: dict[str, str] = {
    "blank lines before the next declaration": (
        _shaped_body(trailing="\n\n\n\n") + _NEXT_DECLARATION
    ),
    "whitespace-only lines before the next declaration": (
        _shaped_body(trailing="\n    \n\t\n  \n") + _NEXT_DECLARATION
    ),
    "trailing spaces on body lines": (
        _shaped_body(inside="        x = 1   ").replace(
            "total = 0", "total = 0  ",
        ) + "   \n\n" + _NEXT_DECLARATION
    ),
    "column-0 comments after the body": (
        _shaped_body(trailing="\n# a note after the body\n# another one\n\n")
        + _NEXT_DECLARATION
    ),
    "indented comments after the body": (
        _shaped_body(trailing="\n    # an indented note\n\n") + _NEXT_DECLARATION
    ),
    "whitespace-only line inside the body": _shaped_body(inside="    ") + "\n",
    "last declaration, no final newline": _shaped_body(),
    "last declaration, blank and whitespace lines at the end": (
        _shaped_body(trailing="\n\n   \n\n")
    ),
    "leading blank line": "\n" + _shaped_body() + "\n",
}


class TestBodyFillsTheDeclarationEnd:
    """``_body_first_line`` rests on one claim about the parser.

    The body fills the last N lines of its declaration, N being its line
    count. These tests hold that claim on every authored source tree and
    on the shapes most likely to break it.
    """

    def test_authored_sources(self) -> None:
        files = 0
        compared = 0
        problems: list[str] = []
        for tree in _authored_trees():
            for path in sorted((_REPOSITORY / tree).rglob("*.s0ma")):
                if "_built" in path.parts or not path.is_file():
                    continue
                source = path.read_text(encoding="utf-8")
                try:
                    count, found = _body_line_mismatches(source, str(path))
                except S0maError:
                    # A fixture written to fail has no module to read.
                    continue
                files += 1
                compared += count
                problems.extend(found)
        assert problems == []
        # Today about 140 files and 400 bodies; the floors keep the test
        # from passing on an empty walk.
        assert files >= 100, files
        assert compared >= 300, compared

    @pytest.mark.parametrize("shape", sorted(_BODY_SHAPES))
    def test_body_shape(self, shape: str) -> None:
        header, _ = _NERVE_TEMPLATE.split("{body}")
        source = header + _BODY_SHAPES[shape]
        compared, problems = _body_line_mismatches(source, "fixture.s0ma")
        assert problems == []
        assert compared >= 1
        diagnostics = _compat_only(_diagnostics(
            source, requires_python=(">=3.11",),
        ))
        walrus = [
            d for d in diagnostics
            if d.context["construct_kind"] == "walrus_in_comprehension"
        ]
        assert [d.line for d in walrus] == [_line_of(source, _WALRUS_LINE)]
