"""Tests for M-13 (POST-10a/b/c) — Validator improvements round 1.

Three independent fixes bundled in 0.16.0:

* **POST-10a** — Vestigial-import detector closure: a single-pass union
  of body identifiers + ``depends_on:`` / ``raises:`` / ``tests:`` /
  ``mocks:`` metadata targets + standalone axon targets. A ``uses:``
  entry that participates in any of those edges is alive.

* **POST-10b** — ``runtime_only_requires:`` module-header field. The
  generated module imports each entry exactly like a ``requires:``
  line, but the Phase 4 vestigial check ignores them. Closes the
  long-running ``pytest`` false positive: a test that uses pytest
  fixtures (``def test_x(monkeypatch): ...``) but never writes
  ``pytest.<symbol>`` in the body still needs the import line on the
  emitted module so the runner can wire the fixture.

* **POST-10c** — ``HELPER_NAME_COLLISION`` D-27 inner-class regression
  pin. The collision detector restricts itself to ``def`` nodes
  whose enclosing scope is the module root of the body (sibling
  top-level functions). Class methods and inner-function closures
  do not participate. The rule was effectively established in
  earlier work; this file pins it with explicit, named regression
  cases.

Each ``TestPOST10*`` group can be read top-to-bottom as the contract
the corresponding sub-fix promises.
"""

from __future__ import annotations

from s0ma_dsl.ast_nodes.enums import (
    Coupling,
    EvaluatesAt,
    Kind,
    Layer,
    Relation,
    Visibility,
)
from s0ma_dsl.ast_nodes.nodes import (
    InlineAxon,
    ModuleDecl,
    NerveDecl,
    RequiresEntry,
    S0maModule,
    SourceLocation,
    TestDecl,
    UsesEntry,
)
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.resolver.dependency import resolve_dependencies
from s0ma_dsl.semantic.validator import validate_module

# ---------------------------------------------------------------------------
# Local helpers (mirrors the shapes used by test_resolver.py / test_semantic.py
# so a maintainer can read this file standalone without chasing imports).
# ---------------------------------------------------------------------------


def _loc(line: int = 1) -> SourceLocation:
    return SourceLocation(start_line=line, start_column=0, end_line=line, end_column=0)


def _make_module(
    name: str = "modA",
    layer: Layer = Layer.APPLICATION,
    version: str = "1.0.0",
    intent: str = "test fixture",
    exports: tuple[str, ...] = (),
    requires: tuple[RequiresEntry, ...] = (),
    uses: tuple[UsesEntry, ...] = (),
    runtime_only_requires: tuple[RequiresEntry, ...] = (),
) -> ModuleDecl:
    return ModuleDecl(
        name=name,
        layer=layer,
        version=version,
        intent=intent,
        exports=exports,
        requires=requires,
        uses=uses,
        runtime_only_requires=runtime_only_requires,
        location=_loc(1),
    )


def _make_nerve(
    name: str,
    body: str = "pass",
    line: int = 10,
    depends_on: tuple[InlineAxon, ...] = (),
    visibility: Visibility = Visibility.PUBLIC,
) -> NerveDecl:
    return NerveDecl(
        name=name,
        layer=Layer.APPLICATION,
        kind=Kind.FUNCTION,
        visibility=visibility,
        intent=f"test nerve {name}",
        expects="None",
        guarantees="None",
        evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
        body=body,
        depends_on=depends_on,
        location=_loc(line),
    )


def _simple_module(
    name: str = "modA",
    exports: tuple[str, ...] = (),
    requires: tuple[RequiresEntry, ...] = (),
    uses: tuple[UsesEntry, ...] = (),
    runtime_only_requires: tuple[RequiresEntry, ...] = (),
    nerves: tuple[NerveDecl, ...] = (),
    tests: tuple[TestDecl, ...] = (),
) -> S0maModule:
    return S0maModule(
        module=_make_module(
            name=name,
            exports=exports,
            requires=requires,
            uses=uses,
            runtime_only_requires=runtime_only_requires,
        ),
        nerves=nerves,
        tests=tests,
    )


def _vestigial(errors, name_fragment: str | None = None):
    """Return VESTIGIAL_IMPORT errors, optionally filtered by message fragment."""
    out = [e for e in errors if e.code == "VESTIGIAL_IMPORT"]
    if name_fragment is None:
        return out
    return [e for e in out if name_fragment in e.message]


def _uses_vestigial(errors, name_fragment: str):
    """Return VESTIGIAL_IMPORT errors that flag a ``uses:`` entry.

    The Phase 4 detector has three buckets: ``uses`` entries (4a),
    ``requires`` / ``soft_requires`` entries (4b/4b2), and inline
    ``depends_on`` body-evidence checks (4c). Each carries a distinct
    leading-phrase in its message. Tests targeting the 4a bucket
    should filter on the "uses entry" prefix specifically so a 4c
    finding does not leak into the assertion.
    """
    return [
        e
        for e in errors
        if e.code == "VESTIGIAL_IMPORT"
        and "uses entry" in e.message
        and name_fragment in e.message
    ]


def _collisions(errors):
    return [e for e in errors if e.code == "HELPER_NAME_COLLISION"]


# ===========================================================================
# POST-10a — Vestigial-import detector closure
# ===========================================================================


class TestPOST10aVestigialClosure:
    """The closure across uses ↔ depends_on ↔ body references is single-pass.

    A ``uses:`` entry is vestigial iff its local name is absent from
    every member of the closure. The cases below pin every branch of
    that rule.
    """

    def test_uses_referenced_only_via_depends_on_not_vestigial(self):
        """Closure: ``uses:`` entry kept alive by a ``depends_on:`` target.

        The depends_on target ``helper`` itself does have its own 4c
        body-evidence check (which here fires because the body does
        not reference ``helper`` — that's expected for
        ``CONFIGURES``). The 4a bucket — the ``uses:`` entry vs the
        closure — must stay quiet: the ``depends_on`` target counts
        as live-name evidence. Pre-POST-10a regression for the
        silent-drift class where a ``uses:`` entry that participates
        only as metadata would slip through if the closure were ever
        split across two passes.
        """
        mod_a = _simple_module(
            name="a",
            uses=(UsesEntry(qualified_name="b.helper", location=_loc(3)),),
            nerves=(
                _make_nerve(
                    "caller",
                    body="def caller():\n    x = 1\n    return x",
                    depends_on=(
                        InlineAxon(
                            target="helper",
                            relation=Relation.CONFIGURES,
                            carries="config",
                            coupling=Coupling.LOOSE,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        mod_b = _simple_module(
            name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper", body="def helper(): pass"),),
        )
        errors = resolve_dependencies(
            {"a": mod_a, "b": mod_b}, check_imports=False
        )
        assert _uses_vestigial(errors, "helper") == []

    def test_uses_referenced_only_in_body_not_vestigial(self):
        """Closure: name used only in body (no depends_on) is not vestigial.

        Regression for the body-evidence branch — the most common
        live-name path. A ``uses:`` entry that participates only as
        a body identifier (no inline ``depends_on`` referencing it)
        is alive.
        """
        mod_a = _simple_module(
            name="a",
            uses=(UsesEntry(qualified_name="b.helper", location=_loc(3)),),
            nerves=(
                _make_nerve(
                    "caller",
                    body="def caller():\n    return helper()",
                ),
            ),
        )
        mod_b = _simple_module(
            name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper", body="def helper(): pass"),),
        )
        errors = resolve_dependencies(
            {"a": mod_a, "b": mod_b}, check_imports=False
        )
        assert _uses_vestigial(errors, "helper") == []

    def test_uses_referenced_in_body_and_depends_on_not_vestigial(self):
        """Closure: name referenced in both body and depends_on is not vestigial.

        The double-reference case — the canonical happy path —
        regression-pinned so future refactors of the closure cannot
        silently flag the most common "dependency is fully wired"
        shape.
        """
        mod_a = _simple_module(
            name="a",
            uses=(UsesEntry(qualified_name="b.helper", location=_loc(3)),),
            nerves=(
                _make_nerve(
                    "caller",
                    body="def caller():\n    return helper()",
                    depends_on=(
                        InlineAxon(
                            target="helper",
                            relation=Relation.CALLS,
                            carries="data",
                            coupling=Coupling.LOOSE,
                            location=_loc(12),
                        ),
                    ),
                ),
            ),
        )
        mod_b = _simple_module(
            name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper", body="def helper(): pass"),),
        )
        errors = resolve_dependencies(
            {"a": mod_a, "b": mod_b}, check_imports=False
        )
        assert _vestigial(errors, "helper") == []
        # Also: the 4a "uses entry" bucket is specifically empty —
        # the body+metadata pair fully satisfies the closure.
        assert _uses_vestigial(errors, "helper") == []

    def test_truly_unused_uses_entry_still_vestigial(self):
        """Closure floor: a name absent from body, depends_on, and metadata fires.

        The closure is union of (body, metadata). When a name is in
        neither, the existing diagnostic semantics are preserved —
        the entry is genuinely dead and the agent should remove it.
        """
        mod_a = _simple_module(
            name="a",
            uses=(UsesEntry(qualified_name="b.helper", location=_loc(3)),),
            nerves=(
                _make_nerve(
                    "caller",
                    body="def caller():\n    return 1",
                ),
            ),
        )
        mod_b = _simple_module(
            name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper", body="def helper(): pass"),),
        )
        errors = resolve_dependencies(
            {"a": mod_a, "b": mod_b}, check_imports=False
        )
        assert len(_uses_vestigial(errors, "helper")) == 1

    def test_uses_referenced_via_standalone_axon_target_not_vestigial(self):
        """Closure includes standalone axon targets.

        A ``uses:`` entry referenced only by a top-level
        ``axon source -> target`` (not by any body or
        ``depends_on:``) is still alive — the axon target counts as
        metadata evidence per the existing rule, and the closure
        unifies that with the body identifiers as one set.
        """
        from s0ma_dsl.ast_nodes.nodes import StandaloneAxonDecl

        mod_a = S0maModule(
            module=_make_module(
                name="a",
                exports=(),
                uses=(
                    UsesEntry(qualified_name="b.helper", location=_loc(3)),
                ),
            ),
            nerves=(
                _make_nerve(
                    "caller",
                    body="def caller():\n    return 1",
                ),
            ),
            axons=(
                StandaloneAxonDecl(
                    source="caller",
                    target="helper",
                    relation=Relation.CONFIGURES,
                    intent="caller is configured by helper",
                    carries="config",
                    coupling=Coupling.LOOSE,
                    location=_loc(20),
                ),
            ),
        )
        mod_b = _simple_module(
            name="b",
            exports=("helper",),
            nerves=(_make_nerve("helper", body="def helper(): pass"),),
        )
        errors = resolve_dependencies(
            {"a": mod_a, "b": mod_b}, check_imports=False
        )
        # ``uses helper`` is not vestigial — referenced via the
        # standalone axon target. The standalone axon's own
        # body-evidence check is a separate concern (not in scope
        # for POST-10a).
        assert _uses_vestigial(errors, "helper") == []


# ===========================================================================
# POST-10b — ``runtime_only_requires:`` field + pytest carve-out
# ===========================================================================


class TestPOST10bRuntimeOnlyRequires:
    """``runtime_only_requires:`` opts a module out of the vestigial check
    for the listed imports while emitting the import line as usual."""

    def test_pytest_in_requires_still_flagged_when_unused(self):
        """Regression: pre-existing ``requires: [pytest]`` rule unchanged.

        ``runtime_only_requires:`` is the *new* surface; the legacy
        ``requires:`` semantics are preserved. A test body that has
        no ``pytest.<symbol>`` reference and lists pytest in
        ``requires:`` (not the new field) still fires
        VESTIGIAL_IMPORT — the carve-out is opt-in.
        """
        mod_a = _simple_module(
            name="a",
            requires=(RequiresEntry(module_path="pytest", location=_loc(3)),),
            tests=(
                TestDecl(
                    name="test_block",
                    layer=Layer.APPLICATION,
                    intent="verify",
                    tests=("some_nerve",),
                    body=(
                        "def test_block(monkeypatch):\n"
                        "    x = 1\n"
                        "    assert x == 1\n"
                    ),
                    location=_loc(20),
                ),
            ),
        )
        errors = resolve_dependencies({"a": mod_a}, check_imports=False)
        assert len(_vestigial(errors, "pytest")) == 1

    def test_pytest_used_in_body_not_vestigial(self):
        """Regression: when a body actually uses ``pytest.<symbol>``,
        ``requires: [pytest]`` is alive.

        Pin for the canonical "pytest in requires is right" path —
        bodies that call ``pytest.raises`` or ``pytest.fixture``
        directly satisfy the existing rule with no need for
        ``runtime_only_requires:``.
        """
        mod_a = _simple_module(
            name="a",
            requires=(RequiresEntry(module_path="pytest", location=_loc(3)),),
            tests=(
                TestDecl(
                    name="test_block",
                    layer=Layer.APPLICATION,
                    intent="verify",
                    tests=("some_nerve",),
                    body=(
                        "def test_block():\n"
                        "    with pytest.raises(ValueError):\n"
                        "        raise ValueError('boom')\n"
                    ),
                    location=_loc(20),
                ),
            ),
        )
        errors = resolve_dependencies({"a": mod_a}, check_imports=False)
        assert _vestigial(errors, "pytest") == []

    def test_runtime_only_requires_parses_via_inline_form(self):
        """The new field parses from a real ``.s0ma`` source."""
        source = (
            "module mod1\n"
            "    layer: APPLICATION\n"
            "    version: 1.0.0\n"
            '    intent: "fixture body uses monkeypatch"\n'
            "    requires: []\n"
            "    runtime_only_requires: [pytest]\n"
            "    exports: []\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
        )
        module, _ = parse_s0ma_with_warnings(
            source, filename="mod1.s0ma", mode=StrictnessMode.DEV
        )
        assert len(module.module.runtime_only_requires) == 1
        assert module.module.runtime_only_requires[0].module_path == "pytest"

    def test_runtime_only_requires_parses_via_block_form(self):
        """The block-list form (POST-PRE-7) works on the new field too —
        same parser path as ``requires:`` / ``soft_requires:``."""
        source = (
            "module mod1\n"
            "    layer: APPLICATION\n"
            "    version: 1.0.0\n"
            '    intent: "fixture body uses fixtures"\n'
            "    requires: []\n"
            "    runtime_only_requires:\n"
            "      - pytest\n"
            "    exports: []\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
        )
        module, _ = parse_s0ma_with_warnings(
            source, filename="mod1.s0ma", mode=StrictnessMode.DEV
        )
        assert len(module.module.runtime_only_requires) == 1
        assert module.module.runtime_only_requires[0].module_path == "pytest"

    def test_runtime_only_requires_exempts_from_vestigial(self):
        """A ``runtime_only_requires:`` entry never fires VESTIGIAL_IMPORT —
        even in STRICT mode, even when the body never names the symbol."""
        mod_a = _simple_module(
            name="a",
            runtime_only_requires=(
                RequiresEntry(module_path="pytest", location=_loc(3)),
            ),
            tests=(
                TestDecl(
                    name="test_block",
                    layer=Layer.APPLICATION,
                    intent="verify behaviour via fixture",
                    tests=("some_nerve",),
                    body=(
                        "def test_block(monkeypatch):\n"
                        "    monkeypatch.setattr('os.environ', {})\n"
                        "    assert True\n"
                    ),
                    location=_loc(20),
                ),
            ),
        )
        errors_dev = resolve_dependencies(
            {"a": mod_a}, mode=StrictnessMode.DEV, check_imports=False
        )
        assert _vestigial(errors_dev, "pytest") == []
        errors_strict = resolve_dependencies(
            {"a": mod_a}, mode=StrictnessMode.STRICT, check_imports=False
        )
        assert _vestigial(errors_strict, "pytest") == []

    def test_runtime_only_requires_emits_import_line(self):
        """The carve-out is only on the *vestigial* check — the import
        line still lands on the generated ``.py``."""
        source = (
            "module mod1\n"
            "    layer: APPLICATION\n"
            "    version: 1.0.0\n"
            '    intent: "fixture body uses monkeypatch"\n'
            "    requires: []\n"
            "    runtime_only_requires: [pytest]\n"
            "    exports: []\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "\n"
            "test test_check :: APPLICATION\n"
            '    intent: "verify"\n'
            "    tests: [some_func]\n"
            "    expects: none\n"
            "    depends_on: none\n"
            "    mocks: none\n"
            "    ---\n"
            "    def test_check(monkeypatch):\n"
            "        assert True\n"
        )
        module, _ = parse_s0ma_with_warnings(
            source, filename="mod1.s0ma", mode=StrictnessMode.DEV
        )
        emitter = PythonEmitter()
        py_source = emitter.emit(module)
        assert "import pytest" in py_source

    def test_runtime_only_requires_alongside_requires(self):
        """``requires:`` and ``runtime_only_requires:`` co-exist — each
        keeps its own semantics."""
        mod_a = _simple_module(
            name="a",
            requires=(RequiresEntry(module_path="json", location=_loc(3)),),
            runtime_only_requires=(
                RequiresEntry(module_path="pytest", location=_loc(4)),
            ),
            tests=(
                TestDecl(
                    name="test_block",
                    layer=Layer.APPLICATION,
                    intent="verify json behaviour",
                    tests=("some_nerve",),
                    body=(
                        "def test_block(monkeypatch):\n"
                        "    data = json.loads('{}')\n"
                        "    assert data == {}\n"
                    ),
                    location=_loc(20),
                ),
            ),
        )
        errors = resolve_dependencies({"a": mod_a}, check_imports=False)
        # ``json`` is referenced — alive. ``pytest`` is in the
        # carve-out — also alive (despite no body reference).
        assert _vestigial(errors, "json") == []
        assert _vestigial(errors, "pytest") == []


# ===========================================================================
# POST-10c — HELPER_NAME_COLLISION inner-class regression pin (D-27)
# ===========================================================================


class TestPOST10cHelperCollisionScope:
    """The collision detector restricts itself to module-root ``def`` nodes.

    Class methods and inner-function closures are not at risk of
    silent overwrite when test bodies are concatenated into the
    emitted module — the detector correctly excludes them. The cases
    below pin the rule end-to-end so future refactors of
    ``_extract_top_level_def_names`` cannot regress.
    """

    @staticmethod
    def _two_tests(body_a: str, body_b: str):
        mod = _make_module(name="a", exports=())
        test_a = TestDecl(
            name="test_block_one",
            layer=Layer.APPLICATION,
            intent="first block",
            tests=("some_nerve",),
            body=body_a,
            location=_loc(10),
        )
        test_b = TestDecl(
            name="test_block_two",
            layer=Layer.APPLICATION,
            intent="second block",
            tests=("other_nerve",),
            body=body_b,
            location=_loc(20),
        )
        return S0maModule(module=mod, tests=(test_a, test_b))

    def test_class_method_collision_does_not_fire(self):
        """Two test bodies that both define ``def _setup(self)`` *inside
        a class* must not fire HELPER_NAME_COLLISION.

        D-27 long-running regression: pre-fix, the regex-based
        detector counted any ``def _setup`` in the body as a
        top-level helper and warned. Now the AST-walk restricts
        itself to module-root ``def`` nodes, so class methods are
        invisible to the detector by construction.
        """
        body_a = (
            "def test_block_one():\n"
            "    class _Recorder:\n"
            "        def _setup(self): self.x = 1\n"
            "        def request(self): return self.x\n"
            "    r = _Recorder()\n"
            "    r._setup()\n"
            "    assert r.request() == 1\n"
        )
        body_b = (
            "def test_block_two():\n"
            "    class _OtherRecorder:\n"
            "        def _setup(self): self.x = 2\n"
            "        def request(self): return self.x\n"
            "    r = _OtherRecorder()\n"
            "    r._setup()\n"
            "    assert r.request() == 2\n"
        )
        module = self._two_tests(body_a, body_b)
        errors = validate_module(module, mode=StrictnessMode.DEV)
        assert _collisions(errors) == []

    def test_real_top_level_collision_still_fires(self):
        """Regression: when both test bodies define ``def _setup()`` at
        the module root, the collision detector still fires.

        The opposite case from the class-method test above —
        verifies the restriction did not over-correct into "always
        silent."
        """
        body_a = (
            "def _setup():\n"
            "    return 1\n"
            "def test_block_one():\n"
            "    assert _setup() == 1\n"
        )
        body_b = (
            "def _setup():\n"
            "    return 2\n"
            "def test_block_two():\n"
            "    assert _setup() == 2\n"
        )
        module = self._two_tests(body_a, body_b)
        errors = validate_module(module, mode=StrictnessMode.DEV)
        coll = _collisions(errors)
        assert len(coll) == 1
        assert "_setup" in coll[0].message

    def test_mixed_class_method_and_top_level_top_level_wins(self):
        """Mixed shape: one test has *both* a class method and a top-
        level ``_setup``; the other test has just a top-level
        ``_setup``. The collision still fires — the class method is
        invisible but the two module-root ``_setup`` defs collide.

        Encodes the "top-level wins" rule: class members do not
        substitute for, but also do not suppress, a real top-level
        clash.
        """
        body_a = (
            "class _Helpers:\n"
            "    def _setup(self): self.x = 1\n"
            "def _setup():\n"
            "    return 1\n"
            "def test_block_one():\n"
            "    assert _setup() == 1\n"
        )
        body_b = (
            "def _setup():\n"
            "    return 2\n"
            "def test_block_two():\n"
            "    assert _setup() == 2\n"
        )
        module = self._two_tests(body_a, body_b)
        errors = validate_module(module, mode=StrictnessMode.DEV)
        coll = _collisions(errors)
        assert len(coll) == 1
        assert "_setup" in coll[0].message

    def test_inner_function_collision_does_not_fire(self):
        """Two test bodies whose inner-function closures share a name
        must not fire HELPER_NAME_COLLISION. Inner ``def``s are
        scoped to their parent ``def`` and cannot be silently
        overwritten at module emit time."""
        body_a = (
            "def test_block_one():\n"
            "    def _setup():\n"
            "        return 1\n"
            "    assert _setup() == 1\n"
        )
        body_b = (
            "def test_block_two():\n"
            "    def _setup():\n"
            "        return 2\n"
            "    assert _setup() == 2\n"
        )
        module = self._two_tests(body_a, body_b)
        errors = validate_module(module, mode=StrictnessMode.DEV)
        assert _collisions(errors) == []

    def test_class_only_in_one_top_level_in_other_does_not_fire(self):
        """When only one test has a top-level ``_setup`` (the other
        carries the name only via a class method), there is no
        collision — exactly one module-root ``_setup`` exists,
        which is fine."""
        body_a = (
            "def test_block_one():\n"
            "    class _R:\n"
            "        def _setup(self): self.x = 1\n"
            "    r = _R()\n"
            "    r._setup()\n"
            "    assert r.x == 1\n"
        )
        body_b = (
            "def _setup():\n"
            "    return 2\n"
            "def test_block_two():\n"
            "    assert _setup() == 2\n"
        )
        module = self._two_tests(body_a, body_b)
        errors = validate_module(module, mode=StrictnessMode.DEV)
        assert _collisions(errors) == []
