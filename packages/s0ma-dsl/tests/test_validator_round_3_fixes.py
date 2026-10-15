"""Tests for M-15 (POST-10h/i/j/k) — Validator improvements round 3.

Four independent validator/codegen improvements bundled in 0.16.0:

* **POST-10h** — A new ``MUTABLE_DEFAULT`` lint fires when a body
  calls ``dataclasses.field(default=[...])`` or
  ``dataclasses.field(default={...})``. Python evaluates ``default``
  once at class-body time, so every instance of the dataclass shares
  the same mutable collection. The correct shape is
  ``default_factory=list`` / ``default_factory=dict``. Severity:
  warning in migration/dev, error in strict/release.

* **POST-10i** — A new ``DUPLICATE_INNER_FUNCTION`` lint fires when a
  body contains two ``def`` declarations with the same name inside
  one enclosing function scope (the canonical example: a SERVICE
  factory body where the author accidentally re-typed the first
  inner function's name). Severity: error in every mode — this is a
  structural authoring bug, not a strictness preference.

* **POST-10j** — ``soft_requires:`` codegen now handles dotted names
  correctly. ``soft_requires: [importlib.metadata]`` emits a
  try/except wrapper of the from-import shape
  ``try: from importlib import metadata`` / ``except ImportError:
  metadata = None`` rather than the pre-0.16.0 broken shape that
  silently overwrote the ``importlib`` binding and left ``metadata``
  unbound on success.

* **POST-10k** — A new ``CROSS_MODULE_USES_ASYMMETRY`` lint fires
  when ``uses:`` imports two or more entries from the same parent
  module but the body only references a subset. Narrower than
  ``VESTIGIAL_IMPORT`` — only fires when ≥2 siblings from the same
  parent module are declared together. Severity: warning in
  migration/dev, error in strict/release.

Each ``TestPOST10*`` group reads top-to-bottom as the contract the
corresponding sub-fix promises.
"""

from __future__ import annotations

from textwrap import dedent

from s0ma_dsl.codegen.python_emitter import emit_python
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.semantic.validator import validate_module

# ===========================================================================
# POST-10h — Mutable-default lint
# ===========================================================================


class TestPOST10hMutableDefault:
    """``dataclasses.field(default=[...])`` and ``default={...}`` calls
    in any body fire ``MUTABLE_DEFAULT``; the corrected
    ``default_factory=list`` shape stays silent."""

    def test_default_list_literal_in_test_body_fires_warning_in_dev(self):
        """A test body that calls ``dataclasses.field(default=[])`` in
        a dataclass definition fires ``MUTABLE_DEFAULT`` at warning
        severity under dev mode."""
        source = dedent("""\
module mut_a
    layer: DOMAIN
    version: 0.1.0
    intent: "Mutable-default test fixture — list default in test body."
    requires: [dataclasses.dataclass, dataclasses.field]
    exports: [do_mut_a]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_mut_a :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Trivial nerve so the module has at least one export."
    expects: "none"
    guarantees: "Returns 0"
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
    def do_mut_a():
        return 0

test mut_a_test :: DOMAIN
    kind: TEST
    visibility: TEST
    intent: "Defines a dataclass with a buggy mutable default."
    tests: [do_mut_a]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_container():
        @dataclass
        class Container:
            items: list = field(default=[])
        a = Container()
        a.items.append(1)
        assert Container().items == []
""").lstrip()
        module = parse_s0ma(source, filename="mut_a.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="mut_a.s0ma",
        )
        muts = [e for e in errors if e.code == "MUTABLE_DEFAULT"]
        assert muts, f"Expected MUTABLE_DEFAULT; got {[e.code for e in errors]}"
        assert muts[0].severity == "warning"
        assert "list" in muts[0].message
        assert "default_factory" in (muts[0].remediation or "")

    def test_default_list_literal_in_test_body_fires_error_in_strict(self):
        """Same fixture under strict mode promotes to error."""
        source = dedent("""\
module mut_a
    layer: DOMAIN
    version: 0.1.0
    intent: "Mutable-default test fixture — list default in test body."
    requires: [dataclasses.dataclass, dataclasses.field]
    exports: [do_mut_a]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_mut_a :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Trivial nerve so the module has at least one export."
    expects: "none"
    guarantees: "Returns 0"
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
    def do_mut_a():
        return 0

test mut_a_test :: DOMAIN
    kind: TEST
    visibility: TEST
    intent: "Defines a dataclass with a buggy mutable default."
    tests: [do_mut_a]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_container():
        @dataclass
        class Container:
            items: list = field(default=[])
        pass
""").lstrip()
        module = parse_s0ma(source, filename="mut_a.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.STRICT, filename="mut_a.s0ma",
        )
        muts = [e for e in errors if e.code == "MUTABLE_DEFAULT"]
        assert muts
        assert muts[0].severity == "error"

    def test_default_dict_literal_in_test_body_also_caught(self):
        """``field(default={})`` is the dict counterpart of the same
        bug and must fire the same diagnostic."""
        source = dedent("""\
module mut_b
    layer: DOMAIN
    version: 0.1.0
    intent: "Mutable-default test fixture — dict default in test body."
    requires: [dataclasses.dataclass, dataclasses.field]
    exports: [do_mut_b]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_mut_b :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Trivial nerve."
    expects: "none"
    guarantees: "Returns 0"
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
    def do_mut_b():
        return 0

test mut_b_test :: DOMAIN
    kind: TEST
    visibility: TEST
    intent: "Defines a dataclass with a buggy dict default."
    tests: [do_mut_b]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_container():
        @dataclass
        class Container:
            items: dict = field(default={})
        pass
""").lstrip()
        module = parse_s0ma(source, filename="mut_b.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="mut_b.s0ma",
        )
        muts = [e for e in errors if e.code == "MUTABLE_DEFAULT"]
        assert muts
        assert "dict" in muts[0].message

    def test_default_factory_list_no_warning(self):
        """The correct shape ``default_factory=list`` does NOT fire the
        diagnostic — the lint must distinguish ``default=`` from
        ``default_factory=``."""
        source = dedent("""\
module mut_c
    layer: DOMAIN
    version: 0.1.0
    intent: "Negative case — uses default_factory=list correctly."
    requires: [dataclasses.dataclass, dataclasses.field]
    exports: [do_mut_c]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_mut_c :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Trivial nerve."
    expects: "none"
    guarantees: "Returns 0"
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
    def do_mut_c():
        return 0

test mut_c_test :: DOMAIN
    kind: TEST
    visibility: TEST
    intent: "Defines a dataclass with the correct factory shape."
    tests: [do_mut_c]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_container():
        @dataclass
        class Container:
            items: list = field(default_factory=list)
        pass
""").lstrip()
        module = parse_s0ma(source, filename="mut_c.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="mut_c.s0ma",
        )
        muts = [e for e in errors if e.code == "MUTABLE_DEFAULT"]
        assert muts == [], (
            f"Expected no MUTABLE_DEFAULT for default_factory=list; got {muts}"
        )

    def test_mutable_default_in_production_nerve_body_also_caught(self):
        """The same lint fires in a production nerve body (not just test
        bodies). Mutable defaults are a bug regardless of where the
        dataclass is declared."""
        source = dedent("""\
module mut_d
    layer: DOMAIN
    version: 0.1.0
    intent: "Mutable-default test fixture — production nerve body."
    requires: [dataclasses.dataclass, dataclasses.field]
    exports: [make_container]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve make_container :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Factory that defines a Container with a buggy mutable default."
    expects: "none"
    guarantees: "Returns a Container instance"
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
    def make_container():
        @dataclass
        class Container:
            items: list = field(default=[])
        return Container()
""").lstrip()
        module = parse_s0ma(source, filename="mut_d.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="mut_d.s0ma",
        )
        muts = [e for e in errors if e.code == "MUTABLE_DEFAULT"]
        assert muts, f"Expected MUTABLE_DEFAULT in nerve body; got {[e.code for e in errors]}"

    def test_dataclasses_field_qualified_call_also_caught(self):
        """``dataclasses.field(default=[])`` (qualified call) is the
        same authoring bug as ``field(default=[])`` (after
        ``from dataclasses import field``)."""
        source = dedent("""\
module mut_e
    layer: DOMAIN
    version: 0.1.0
    intent: "Mutable-default test fixture — qualified dataclasses.field call."
    requires: [dataclasses]
    exports: [make_e]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve make_e :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Defines a dataclass via qualified import."
    expects: "none"
    guarantees: "Returns 0"
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
    def make_e():
        @dataclasses.dataclass
        class Container:
            items: list = dataclasses.field(default=[])
        return 0
""").lstrip()
        module = parse_s0ma(source, filename="mut_e.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="mut_e.s0ma",
        )
        muts = [e for e in errors if e.code == "MUTABLE_DEFAULT"]
        assert muts


# ===========================================================================
# POST-10i — Duplicate inner-function lint
# ===========================================================================


class TestPOST10iDuplicateInnerFunction:
    """Two ``def`` declarations with the same name inside one outer
    ``def`` scope fire ``DUPLICATE_INNER_FUNCTION`` as an error in
    every strictness mode."""

    def test_duplicate_inner_def_in_service_body_fires_error(self):
        """The canonical motivating case: a SERVICE nerve's factory
        body contains ``def f(): ...`` twice as siblings."""
        source = dedent("""\
module dup_a
    layer: DOMAIN
    version: 0.1.0
    intent: "Duplicate-inner-def test fixture — SERVICE factory."
    exports: [factory]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve factory :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "SERVICE nerve whose factory body re-types an inner def."
    expects: "no preconditions"
    guarantees: "returns a dict of operations"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: [foo, bar]
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
    def factory():
        def foo():
            return 'first'
        def foo():
            return 'second'
        def bar():
            return 'bar'
        return {'foo': foo, 'bar': bar}
""").lstrip()
        module = parse_s0ma(source, filename="dup_a.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="dup_a.s0ma",
        )
        dups = [e for e in errors if e.code == "DUPLICATE_INNER_FUNCTION"]
        assert dups, (
            f"Expected DUPLICATE_INNER_FUNCTION; got {[e.code for e in errors]}"
        )
        assert dups[0].severity == "error"
        assert "foo" in dups[0].message
        assert "factory" in dups[0].message

    def test_duplicate_inner_def_is_error_in_every_mode(self):
        """``DUPLICATE_INNER_FUNCTION`` is a structural bug — error in
        every strictness mode, including migration."""
        source = dedent("""\
module dup_b
    layer: DOMAIN
    version: 0.1.0
    intent: "Duplicate-inner-def test fixture — every-mode check."
    exports: [factory]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve factory :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "SERVICE nerve whose factory body re-types an inner def."
    expects: "no preconditions"
    guarantees: "returns a dict of operations"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: [foo]
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
    def factory():
        def foo():
            return 'first'
        def foo():
            return 'second'
        return {'foo': foo}
""").lstrip()
        module = parse_s0ma(source, filename="dup_b.s0ma")
        for mode in StrictnessMode:
            errors = validate_module(
                module, mode=mode, filename="dup_b.s0ma",
            )
            dups = [e for e in errors if e.code == "DUPLICATE_INNER_FUNCTION"]
            assert dups, (
                f"Expected DUPLICATE_INNER_FUNCTION under mode {mode.value}; "
                f"got {[e.code for e in errors]}"
            )
            assert dups[0].severity == "error"

    def test_same_name_in_two_different_outer_functions_no_error(self):
        """Two sibling outer ``def factory()`` and ``def helper()`` each
        defining their own inner ``def foo()`` are NOT duplicates —
        they live in distinct scopes."""
        source = dedent("""\
module dup_c
    layer: DOMAIN
    version: 0.1.0
    intent: "Sibling-scope test fixture — same-name inner def OK."
    exports: [factory]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve factory :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "Factory with one inner def; sibling helper has its own."
    expects: "no preconditions"
    guarantees: "returns a dict of operations"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: [foo]
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
    def helper():
        def foo():
            return 'helper-foo'
        return foo

    def factory():
        def foo():
            return 'factory-foo'
        return {'foo': foo}
""").lstrip()
        module = parse_s0ma(source, filename="dup_c.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="dup_c.s0ma",
        )
        dups = [e for e in errors if e.code == "DUPLICATE_INNER_FUNCTION"]
        assert dups == [], (
            f"Expected no DUPLICATE_INNER_FUNCTION for sibling scopes; got "
            f"{[(e.code, e.message) for e in dups]}"
        )

    def test_class_method_redefinition_not_flagged(self):
        """Class bodies are out of scope: methods named the same as
        functions elsewhere don't participate in the lint."""
        source = dedent("""\
module dup_d
    layer: DOMAIN
    version: 0.1.0
    intent: "Class-body test fixture — methods not flagged."
    requires: [dataclasses.dataclass]
    exports: [make_thing]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve make_thing :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Nerve with a class def inside."
    expects: "none"
    guarantees: "Returns a Thing"
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
    def make_thing():
        class Thing:
            def foo(self):
                return 1
        return Thing()
""").lstrip()
        module = parse_s0ma(source, filename="dup_d.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="dup_d.s0ma",
        )
        dups = [e for e in errors if e.code == "DUPLICATE_INNER_FUNCTION"]
        assert dups == []


# ===========================================================================
# POST-10j — soft_requires dotted-name codegen
# ===========================================================================


class TestPOST10jSoftRequiresDottedName:
    """``soft_requires:`` with a dotted name emits the from-import
    shape in the try/except wrapper."""

    def test_soft_requires_dotted_lowercase_emits_from_import(self):
        """``soft_requires: [importlib.metadata]`` emits
        ``try: from importlib import metadata; except ImportError:
        metadata = None`` — the from-import shape that actually binds
        the submodule name."""
        source = dedent("""\
module soft_a
    layer: DOMAIN
    version: 0.1.0
    intent: "Soft-requires test fixture — dotted lowercase."
    soft_requires: [importlib.metadata]
    exports: [do_soft_a]

    requires: none
    uses: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_soft_a :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Trivial nerve so the module has at least one export."
    expects: "none"
    guarantees: "Returns version string"
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
    def do_soft_a():
        return metadata.version('s0ma-dsl') if metadata else 'unknown'
""").lstrip()
        module = parse_s0ma(source, filename="soft_a.s0ma")
        output = emit_python(module)
        expected = (
            "try:\n    from importlib import metadata\n"
            "except ImportError:\n    metadata = None"
        )
        assert expected in output, (
            f"Expected dotted soft_requires to emit from-import shape; "
            f"got:\n{output}"
        )
        # The emitted Python must compile cleanly.
        compile(output, "<test>", "exec")

    def test_soft_requires_colon_override_emits_from_import(self):
        """The colon-override form ``soft_requires: [requests:Session]``
        emits ``try: from requests import Session`` (already worked
        pre-POST-10j; this test is the regression pin)."""
        source = dedent("""\
module soft_b
    layer: DOMAIN
    version: 0.1.0
    intent: "Soft-requires test fixture — colon override."
    soft_requires: [requests:Session]
    exports: [do_soft_b]

    requires: none
    uses: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_soft_b :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Trivial nerve."
    expects: "none"
    guarantees: "Returns a Session or None"
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
    def do_soft_b():
        return Session() if Session else None
""").lstrip()
        module = parse_s0ma(source, filename="soft_b.s0ma")
        output = emit_python(module)
        expected = (
            "try:\n    from requests import Session\n"
            "except ImportError:\n    Session = None"
        )
        assert expected in output, (
            f"Expected colon-override soft_requires to emit from-import; "
            f"got:\n{output}"
        )
        compile(output, "<test>", "exec")

    def test_soft_requires_single_segment_still_plain_import(self):
        """The legacy single-segment form ``soft_requires: [anthropic]``
        still emits a plain ``try: import anthropic`` line — the
        POST-10j fix only affects dotted entries."""
        source = dedent("""\
module soft_c
    layer: DOMAIN
    version: 0.1.0
    intent: "Soft-requires test fixture — single segment regression."
    soft_requires: [anthropic]
    exports: [do_soft_c]

    requires: none
    uses: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_soft_c :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Trivial nerve."
    expects: "none"
    guarantees: "Returns a client or None"
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
    def do_soft_c():
        return anthropic.Client() if anthropic else None
""").lstrip()
        module = parse_s0ma(source, filename="soft_c.s0ma")
        output = emit_python(module)
        expected = (
            "try:\n    import anthropic\n"
            "except ImportError:\n    anthropic = None"
        )
        assert expected in output, (
            f"Expected single-segment soft_requires to emit plain import; "
            f"got:\n{output}"
        )
        compile(output, "<test>", "exec")


# ===========================================================================
# POST-10k — Cross-module ``uses:`` asymmetry warning
# ===========================================================================


class TestPOST10kCrossModuleUsesAsymmetry:
    """``uses: [other.A, other.B]`` with the body referencing only ``A``
    fires ``CROSS_MODULE_USES_ASYMMETRY``."""

    def test_two_siblings_one_referenced_fires_warning_in_dev(self):
        """The canonical motivating case: two siblings from the same
        parent module, only one referenced."""
        source = dedent("""\
module sym_a
    layer: DOMAIN
    version: 0.1.0
    intent: "Cross-module symmetry test fixture — asymmetric uses."
    uses: [other.alpha, other.beta]
    exports: [do_sym_a]

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_sym_a :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "References only alpha."
    expects: "none"
    guarantees: "Returns alpha's value"
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
    def do_sym_a():
        return alpha()
""").lstrip()
        module = parse_s0ma(source, filename="sym_a.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="sym_a.s0ma",
        )
        syms = [e for e in errors if e.code == "CROSS_MODULE_USES_ASYMMETRY"]
        assert syms, (
            f"Expected CROSS_MODULE_USES_ASYMMETRY; got {[e.code for e in errors]}"
        )
        assert syms[0].severity == "warning"
        assert "beta" in syms[0].message
        assert "other" in syms[0].message

    def test_two_siblings_one_referenced_fires_error_in_strict(self):
        """Same fixture under strict mode promotes to error."""
        source = dedent("""\
module sym_a2
    layer: DOMAIN
    version: 0.1.0
    intent: "Cross-module symmetry — strict-mode promotion."
    uses: [other.alpha, other.beta]
    exports: [do_sym_a2]

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_sym_a2 :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "References only alpha."
    expects: "none"
    guarantees: "Returns alpha's value"
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
    def do_sym_a2():
        return alpha()
""").lstrip()
        module = parse_s0ma(source, filename="sym_a2.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.STRICT, filename="sym_a2.s0ma",
        )
        syms = [e for e in errors if e.code == "CROSS_MODULE_USES_ASYMMETRY"]
        assert syms
        assert syms[0].severity == "error"

    def test_both_siblings_referenced_no_warning(self):
        """When all siblings are referenced, no asymmetry — no diagnostic."""
        source = dedent("""\
module sym_b
    layer: DOMAIN
    version: 0.1.0
    intent: "Cross-module symmetry — both siblings referenced."
    uses: [other.alpha, other.beta]
    exports: [do_sym_b]

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_sym_b :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "References both alpha and beta."
    expects: "none"
    guarantees: "Returns combined value"
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
    def do_sym_b():
        return alpha() + beta()
""").lstrip()
        module = parse_s0ma(source, filename="sym_b.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="sym_b.s0ma",
        )
        syms = [e for e in errors if e.code == "CROSS_MODULE_USES_ASYMMETRY"]
        assert syms == [], (
            f"Expected no asymmetry when both siblings referenced; got {syms}"
        )

    def test_single_uses_entry_no_warning(self):
        """``uses: [other.alpha]`` (single sibling) — even when
        unreferenced — does NOT fire the asymmetry lint. The narrower
        ``VESTIGIAL_IMPORT`` ladder handles the all-unused case."""
        source = dedent("""\
module sym_c
    layer: DOMAIN
    version: 0.1.0
    intent: "Cross-module symmetry — single uses entry."
    uses: [other.alpha]
    exports: [do_sym_c]

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_sym_c :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Body that references alpha as a name."
    expects: "none"
    guarantees: "Returns a string"
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
    def do_sym_c():
        return alpha()
""").lstrip()
        module = parse_s0ma(source, filename="sym_c.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="sym_c.s0ma",
        )
        syms = [e for e in errors if e.code == "CROSS_MODULE_USES_ASYMMETRY"]
        assert syms == []

    def test_siblings_from_different_parents_no_warning(self):
        """``uses: [other.alpha, third.beta]`` — two entries but
        different parent modules — do NOT participate in the lint.
        Only same-parent siblings fire the diagnostic."""
        source = dedent("""\
module sym_d
    layer: DOMAIN
    version: 0.1.0
    intent: "Cross-module symmetry — different parents."
    uses: [other.alpha, third.beta]
    exports: [do_sym_d]

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_sym_d :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "References only alpha."
    expects: "none"
    guarantees: "Returns alpha's value"
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
    def do_sym_d():
        return alpha()
""").lstrip()
        module = parse_s0ma(source, filename="sym_d.s0ma")
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="sym_d.s0ma",
        )
        syms = [e for e in errors if e.code == "CROSS_MODULE_USES_ASYMMETRY"]
        assert syms == []
