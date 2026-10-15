"""Privileged import, observes resolution, and ganglion/test emission tests (Milestone 12).

Tests the three observes pattern forms, privileged import scoping,
privileged import marking in IR, and full ganglion/test code generation.

PRD references: FR-20 (ganglion observes), FR-21 (tests), FR-22 (privileged imports)
                §2.2.4 (ganglion), §2.2.5 (test), §2.3.3 (registry namespace)
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
    CellDecl,
    GanglionDecl,
    InlineAxon,
    ModuleDecl,
    NerveDecl,
    S0maModule,
    SourceLocation,
    TestDecl,
    UsesEntry,
)
from s0ma_dsl.codegen.observes_resolver import (
    ObservesResolver,
    PrivilegedImportInfo,
    ProjectContext,
    ResolvedObserves,
    _classify_pattern,
    determine_privileged_imports,
    resolve_observes,
)
from s0ma_dsl.codegen.python_emitter import PythonEmitter, emit_python
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.ir.builder import build_ir
from tests.conftest import assert_has_error, assert_no_errors

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _loc(start: int = 1, end: int = 5) -> SourceLocation:
    return SourceLocation(start_line=start, start_column=0, end_line=end, end_column=0)


def _make_module(
    name: str,
    layer: Layer = Layer.DOMAIN,
    nerves: tuple[NerveDecl, ...] = (),
    cells: tuple[CellDecl, ...] = (),
    ganglia: tuple[GanglionDecl, ...] = (),
    tests: tuple[TestDecl, ...] = (),
    exports: tuple[str, ...] = (),
    uses: tuple[UsesEntry, ...] = (),
) -> S0maModule:
    """Build a minimal S0maModule for testing."""
    return S0maModule(
        module=ModuleDecl(
            name=name,
            layer=layer,
            version="1.0.0",
            intent=f"Test module {name}",
            exports=exports,
            uses=uses,
            location=_loc(1, 3),
        ),
        nerves=nerves,
        cells=cells,
        ganglia=ganglia,
        tests=tests,
    )


def _make_nerve(
    name: str,
    layer: Layer = Layer.DOMAIN,
    visibility: Visibility = Visibility.PUBLIC,
    kind: Kind = Kind.FUNCTION,
) -> NerveDecl:
    """Build a minimal NerveDecl for testing."""
    return NerveDecl(
        name=name,
        layer=layer,
        kind=kind,
        visibility=visibility,
        intent=f"Test nerve {name}",
        expects="some input",
        guarantees="some output",
        evaluates_at=EvaluatesAt.FUNCTION_BOUNDARY,
        body=f"def {name}():\n    pass",
        location=_loc(10, 20),
    )


def _make_ganglion(
    name: str,
    observes: tuple[str, ...],
    layer: Layer = Layer.DOMAIN,
    visibility: Visibility = Visibility.INTERNAL,
) -> GanglionDecl:
    """Build a minimal GanglionDecl for testing."""
    return GanglionDecl(
        name=name,
        layer=layer,
        visibility=visibility,
        intent=f"Test ganglion {name}",
        observes=observes,
        scope=EvaluatesAt.FUNCTION_BOUNDARY,
        priors="Expects normal signal patterns",
        on_anomaly="Log and escalate",
        body=f"def {name}(signal):\n    return signal",
        location=_loc(30, 40),
    )


def _make_test(
    name: str,
    tests_field: tuple[str, ...],
    layer: Layer = Layer.DOMAIN,
) -> TestDecl:
    """Build a minimal TestDecl for testing."""
    return TestDecl(
        name=name,
        layer=layer,
        intent=f"Test declaration {name}",
        tests=tests_field,
        body=f"def {name}():\n    assert True",
        location=_loc(50, 60),
    )


def _build_project_context(*modules: S0maModule) -> ProjectContext:
    """Build a ProjectContext from modules."""
    return ProjectContext(modules=list(modules))


# ===========================================================================
# Test 12.1: Pattern classification
# ===========================================================================


class TestPatternClassification:
    """Tests for observes pattern type classification."""

    def test_exact_name(self):
        assert _classify_pattern("process_signal") == "exact"

    def test_module_glob(self):
        assert _classify_pattern("signal_processor.*") == "module_glob"

    def test_layer_glob(self):
        assert _classify_pattern("DOMAIN::*") == "layer_glob"

    def test_exact_with_underscore(self):
        assert _classify_pattern("my_nerve_name") == "exact"

    def test_layer_glob_with_uppercase(self):
        assert _classify_pattern("INFRASTRUCTURE::*") == "layer_glob"


# ===========================================================================
# Test 12.1: Observes pattern resolution — exact name
# ===========================================================================


class TestObservesExactName:
    """Tests for exact-name observes pattern resolution."""

    def test_exact_match_single_nerve(self):
        nerve = _make_nerve("process_signal")
        mod = _make_module("sig_proc", nerves=(nerve,), exports=("process_signal",))
        ctx = _build_project_context(mod)

        resolver = ObservesResolver(mode=StrictnessMode.DEV)
        resolved, errors = resolver.resolve_patterns(("process_signal",), ctx)

        assert len(resolved) == 1
        assert resolved[0].pattern == "process_signal"
        assert resolved[0].pattern_type == "exact"
        assert "sig_proc::process_signal" in resolved[0].resolved_targets
        assert_no_errors(errors)

    def test_exact_match_across_modules(self):
        """Exact name matches the nerve in any module."""
        nerve1 = _make_nerve("shared_nerve")
        nerve2 = _make_nerve("shared_nerve")
        mod1 = _make_module("mod_a", nerves=(nerve1,), exports=("shared_nerve",))
        mod2 = _make_module("mod_b", nerves=(nerve2,), exports=("shared_nerve",))
        ctx = _build_project_context(mod1, mod2)

        resolver = ObservesResolver(mode=StrictnessMode.DEV)
        resolved, errors = resolver.resolve_patterns(("shared_nerve",), ctx)

        assert len(resolved) == 1
        # Both modules have a nerve with that name
        assert len(resolved[0].resolved_targets) == 2
        assert "mod_a::shared_nerve" in resolved[0].resolved_targets
        assert "mod_b::shared_nerve" in resolved[0].resolved_targets

    def test_exact_no_match_empty_observes(self):
        """No matching nerve → EMPTY_OBSERVES error."""
        mod = _make_module("empty_mod")
        ctx = _build_project_context(mod)

        resolver = ObservesResolver(mode=StrictnessMode.DEV, filename="test.s0ma")
        resolved, errors = resolver.resolve_patterns(("nonexistent",), ctx)

        assert len(resolved) == 1
        assert len(resolved[0].resolved_targets) == 0
        assert len(errors) == 1
        assert errors[0].code == "EMPTY_OBSERVES"


# ===========================================================================
# Test 12.1: Observes pattern resolution — module glob
# ===========================================================================


class TestObservesModuleGlob:
    """Tests for module glob observes pattern resolution."""

    def test_module_glob_matches_all_nerves_in_module(self):
        nerve1 = _make_nerve("nerve_a")
        nerve2 = _make_nerve("nerve_b")
        mod = _make_module("target_mod", nerves=(nerve1, nerve2), exports=("nerve_a", "nerve_b"))
        ctx = _build_project_context(mod)

        resolver = ObservesResolver(mode=StrictnessMode.DEV)
        resolved, errors = resolver.resolve_patterns(("target_mod.*",), ctx)

        assert len(resolved) == 1
        assert resolved[0].pattern_type == "module_glob"
        assert len(resolved[0].resolved_targets) == 2
        assert "target_mod::nerve_a" in resolved[0].resolved_targets
        assert "target_mod::nerve_b" in resolved[0].resolved_targets

    def test_module_glob_excludes_other_modules(self):
        nerve1 = _make_nerve("nerve_a")
        nerve2 = _make_nerve("nerve_c")
        mod1 = _make_module("target", nerves=(nerve1,))
        mod2 = _make_module("other", nerves=(nerve2,))
        ctx = _build_project_context(mod1, mod2)

        resolver = ObservesResolver(mode=StrictnessMode.DEV)
        resolved, errors = resolver.resolve_patterns(("target.*",), ctx)

        assert len(resolved[0].resolved_targets) == 1
        assert "target::nerve_a" in resolved[0].resolved_targets

    def test_module_glob_no_nerves_empty_observes(self):
        """Module exists but has no nerves → EMPTY_OBSERVES."""
        mod = _make_module("no_nerves")
        ctx = _build_project_context(mod)

        resolver = ObservesResolver(mode=StrictnessMode.DEV, filename="test.s0ma")
        resolved, errors = resolver.resolve_patterns(("no_nerves.*",), ctx)

        assert len(resolved[0].resolved_targets) == 0
        assert_has_error(errors, "EMPTY_OBSERVES")


# ===========================================================================
# Test 12.1: Observes pattern resolution — layer glob
# ===========================================================================


class TestObservesLayerGlob:
    """Tests for layer glob observes pattern resolution."""

    def test_layer_glob_matches_nerves_at_layer(self):
        domain_nerve = _make_nerve("domain_fn", layer=Layer.DOMAIN)
        infra_nerve = _make_nerve("infra_fn", layer=Layer.INFRASTRUCTURE)
        mod1 = _make_module("mod1", layer=Layer.DOMAIN, nerves=(domain_nerve,))
        mod2 = _make_module("mod2", layer=Layer.INFRASTRUCTURE, nerves=(infra_nerve,))
        ctx = _build_project_context(mod1, mod2)

        resolver = ObservesResolver(mode=StrictnessMode.DEV)
        resolved, errors = resolver.resolve_patterns(("DOMAIN::*",), ctx)

        assert len(resolved) == 1
        assert resolved[0].pattern_type == "layer_glob"
        assert len(resolved[0].resolved_targets) == 1
        assert "mod1::domain_fn" in resolved[0].resolved_targets

    def test_layer_glob_multiple_modules(self):
        n1 = _make_nerve("fn1", layer=Layer.DOMAIN)
        n2 = _make_nerve("fn2", layer=Layer.DOMAIN)
        mod1 = _make_module("mod_a", layer=Layer.DOMAIN, nerves=(n1,))
        mod2 = _make_module("mod_b", layer=Layer.DOMAIN, nerves=(n2,))
        ctx = _build_project_context(mod1, mod2)

        resolver = ObservesResolver(mode=StrictnessMode.DEV)
        resolved, _ = resolver.resolve_patterns(("DOMAIN::*",), ctx)

        assert len(resolved[0].resolved_targets) == 2

    def test_layer_glob_no_match(self):
        nerve = _make_nerve("fn", layer=Layer.DOMAIN)
        mod = _make_module("mod", layer=Layer.DOMAIN, nerves=(nerve,))
        ctx = _build_project_context(mod)

        resolver = ObservesResolver(mode=StrictnessMode.STRICT, filename="test.s0ma")
        resolved, errors = resolver.resolve_patterns(("PRESENTATION::*",), ctx)

        assert len(resolved[0].resolved_targets) == 0
        assert_has_error(errors, "EMPTY_OBSERVES")


# ===========================================================================
# Test 12.1: EMPTY_OBSERVES strictness mode behavior
# ===========================================================================


class TestEmptyObservesStrictness:
    """Tests that EMPTY_OBSERVES severity follows the strictness mode."""

    def test_dev_mode_warning(self):
        ctx = _build_project_context(_make_module("empty"))
        resolver = ObservesResolver(mode=StrictnessMode.DEV, filename="test.s0ma")
        _, errors = resolver.resolve_patterns(("missing.*",), ctx)

        assert len(errors) == 1
        assert errors[0].severity == "warning"

    def test_strict_mode_error(self):
        ctx = _build_project_context(_make_module("empty"))
        resolver = ObservesResolver(mode=StrictnessMode.STRICT, filename="test.s0ma")
        _, errors = resolver.resolve_patterns(("missing.*",), ctx)

        assert len(errors) == 1
        assert errors[0].severity == "error"

    def test_migration_mode_warning(self):
        ctx = _build_project_context(_make_module("empty"))
        resolver = ObservesResolver(mode=StrictnessMode.MIGRATION, filename="test.s0ma")
        _, errors = resolver.resolve_patterns(("missing.*",), ctx)

        assert len(errors) == 1
        assert errors[0].severity == "warning"


# ===========================================================================
# Test 12.2: Privileged import determination
# ===========================================================================


class TestPrivilegedImportDetermination:
    """Tests for determining which references need privileged imports."""

    def test_cross_module_internal_needs_privilege(self):
        """INTERNAL nerves in another module require privileged imports."""
        internal_nerve = _make_nerve("secret_fn", visibility=Visibility.INTERNAL)
        target_mod = _make_module("target", nerves=(internal_nerve,), exports=())
        ctx = _build_project_context(target_mod)

        privileged = determine_privileged_imports(
            current_module_name="observer",
            resolved_canonical_ids=["target::secret_fn"],
            context=ctx,
            import_kind="privileged_observation",
            referenced_in="observes",
        )

        assert len(privileged) == 1
        assert privileged[0].canonical_id == "target::secret_fn"
        assert privileged[0].module_name == "target"
        assert privileged[0].component_name == "secret_fn"
        assert privileged[0].import_kind == "privileged_observation"

    def test_cross_module_exported_no_privilege(self):
        """Exported (PUBLIC) nerves don't need privileged imports."""
        public_nerve = _make_nerve("public_fn", visibility=Visibility.PUBLIC)
        target_mod = _make_module(
            "target", nerves=(public_nerve,), exports=("public_fn",)
        )
        ctx = _build_project_context(target_mod)

        privileged = determine_privileged_imports(
            current_module_name="observer",
            resolved_canonical_ids=["target::public_fn"],
            context=ctx,
            import_kind="privileged_observation",
            referenced_in="observes",
        )

        assert len(privileged) == 0

    def test_local_reference_no_privilege(self):
        """References to the current module don't need privileged imports."""
        nerve = _make_nerve("local_fn", visibility=Visibility.INTERNAL)
        local_mod = _make_module("observer", nerves=(nerve,))
        ctx = _build_project_context(local_mod)

        privileged = determine_privileged_imports(
            current_module_name="observer",
            resolved_canonical_ids=["observer::local_fn"],
            context=ctx,
            import_kind="privileged_observation",
            referenced_in="observes",
        )

        assert len(privileged) == 0

    def test_test_privileged_verification(self):
        """Tests reference INTERNAL components with privileged_verification kind."""
        internal_nerve = _make_nerve("internal_fn", visibility=Visibility.INTERNAL)
        target_mod = _make_module("target", nerves=(internal_nerve,))
        ctx = _build_project_context(target_mod)

        privileged = determine_privileged_imports(
            current_module_name="test_mod",
            resolved_canonical_ids=["target::internal_fn"],
            context=ctx,
            import_kind="privileged_verification",
            referenced_in="tests",
        )

        assert len(privileged) == 1
        assert privileged[0].import_kind == "privileged_verification"
        assert privileged[0].referenced_in == "tests"


# ===========================================================================
# Test 12.2: Privileged imports only in ganglion/test files
# ===========================================================================


class TestPrivilegedImportScoping:
    """Tests that privileged imports are ONLY emitted for ganglia and tests."""

    def test_normal_module_no_privileged_imports(self):
        """A module with only nerves and cells gets no privileged imports."""
        nerve = _make_nerve("fn")
        mod = _make_module("normal", nerves=(nerve,), exports=("fn",))

        emitter = PythonEmitter()
        emitter.emit(mod)

        assert len(emitter.privileged_imports) == 0

    def test_ganglion_module_gets_privileged_imports(self):
        """A module with ganglia that observe INTERNAL cross-module nerves
        gets privileged imports."""
        # Target module with INTERNAL nerve
        internal_nerve = _make_nerve("secret", visibility=Visibility.INTERNAL)
        target_mod = _make_module("target", nerves=(internal_nerve,))

        # Observer module with ganglion
        ganglion = _make_ganglion("watcher", observes=("secret",))
        observer_mod = _make_module("observer", ganglia=(ganglion,))

        ctx = _build_project_context(target_mod, observer_mod)

        emitter = PythonEmitter(
            project_context=ctx,
            mode=StrictnessMode.DEV,
        )
        result = emitter.emit(observer_mod)

        assert len(emitter.privileged_imports) == 1
        assert emitter.privileged_imports[0].canonical_id == "target::secret"
        # Verify privileged import appears in emitted code
        assert "# Privileged imports" in result
        assert "from target import secret" in result

    def test_test_module_gets_privileged_imports(self):
        """A module with tests referencing INTERNAL cross-module components
        gets privileged imports."""
        internal_nerve = _make_nerve("internal_fn", visibility=Visibility.INTERNAL)
        target_mod = _make_module("target", nerves=(internal_nerve,))

        test_decl = _make_test("test_internal", tests_field=("internal_fn",))
        test_mod = _make_module("test_suite", tests=(test_decl,), exports=())

        ctx = _build_project_context(target_mod, test_mod)

        emitter = PythonEmitter(project_context=ctx, mode=StrictnessMode.DEV)
        result = emitter.emit(test_mod)

        assert len(emitter.privileged_imports) == 1
        assert emitter.privileged_imports[0].import_kind == "privileged_verification"
        assert "from target import internal_fn" in result


# ===========================================================================
# Test 12.2: Privileged imports marked in IR
# ===========================================================================


class TestPrivilegedImportsInIR:
    """Tests that privileged imports are correctly recorded in the IR."""

    def test_privileged_imports_appear_in_ir(self):
        """Privileged imports from emitter should be included in IR."""
        priv = PrivilegedImportInfo(
            canonical_id="target::secret",
            module_name="target",
            component_name="secret",
            import_kind="privileged_observation",
            referenced_in="observes",
        )

        mod = _make_module("observer")
        ir_doc = build_ir(mod, privileged_imports=[priv])

        assert len(ir_doc.imports.privileged) == 1
        priv_ir = ir_doc.imports.privileged[0]
        assert priv_ir.canonical_id == "target::secret"
        assert priv_ir.import_kind == "privileged_observation"
        assert priv_ir.referenced_in == "observes"

    def test_privileged_imports_in_ir_dict(self):
        """Privileged imports serialize correctly in IR JSON."""
        priv = PrivilegedImportInfo(
            canonical_id="target::secret",
            module_name="target",
            component_name="secret",
            import_kind="privileged_verification",
            referenced_in="tests",
        )

        mod = _make_module("test_suite")
        ir_doc = build_ir(mod, privileged_imports=[priv])
        ir_dict = ir_doc.to_dict()

        priv_list = ir_dict["imports"]["privileged"]
        assert len(priv_list) == 1
        assert priv_list[0]["canonical_id"] == "target::secret"
        assert priv_list[0]["import_kind"] == "privileged_verification"
        assert priv_list[0]["referenced_in"] == "tests"

    def test_no_privileged_imports_empty_list(self):
        """Without privileged imports, the IR has an empty list."""
        mod = _make_module("plain")
        ir_doc = build_ir(mod)

        assert len(ir_doc.imports.privileged) == 0


# ===========================================================================
# Test 12.3: Test file generation
# ===========================================================================


class TestTestFileGeneration:
    """Tests for test declaration code generation."""

    def test_test_emits_pytest_function(self):
        """Test declarations emit as pytest-compatible functions."""
        test_decl = _make_test("test_process_signal", tests_field=("process_signal",))
        mod = _make_module("tests_module", tests=(test_decl,), exports=())

        result = emit_python(mod)

        # Should contain the test function body
        assert "def test_process_signal():" in result
        assert "assert True" in result

    def test_test_emits_register_test(self):
        """Test declarations emit register_test() call."""
        test_decl = _make_test("test_fn", tests_field=("some_nerve",))
        mod = _make_module("tests_module", tests=(test_decl,), exports=())

        result = emit_python(mod)

        assert "register_test(" in result
        assert '"tests_module::test_fn"' in result
        assert '"some_nerve"' in result

    def test_test_validates_comment(self):
        """Test declarations include a comment about what they validate."""
        test_decl = _make_test("test_fn", tests_field=("nerve_a", "nerve_b"))
        mod = _make_module("tests_module", tests=(test_decl,), exports=())

        result = emit_python(mod)

        assert "# Test: validates nerve_a, nerve_b" in result

    def test_test_register_test_import(self):
        """When tests exist, register_test is imported."""
        test_decl = _make_test("test_fn", tests_field=("x",))
        mod = _make_module("tests_module", tests=(test_decl,), exports=())

        result = emit_python(mod)

        assert "register_test" in result


# ===========================================================================
# Test 12.4: Ganglion code generation
# ===========================================================================


class TestGanglionGeneration:
    """Tests for ganglion declaration code generation."""

    def test_ganglion_emits_component_decorator(self):
        """Ganglia emit with @component decorator."""
        ganglion = _make_ganglion("signal_watcher", observes=("process_signal",))
        mod = _make_module("eval_module", ganglia=(ganglion,))

        result = emit_python(mod)

        assert "@component(" in result
        assert '"signal_watcher"' in result
        assert "ComponentKind.SERVICE" in result

    def test_ganglion_metadata_includes_observes(self):
        """Ganglion metadata includes observes patterns (unresolved without context)."""
        ganglion = _make_ganglion("watcher", observes=("target.*",))
        mod = _make_module("eval_module", ganglia=(ganglion,))

        # Without project context — raw patterns
        result = emit_python(mod)

        assert '"observes"' in result
        assert '"target.*"' in result

    def test_ganglion_resolved_observes_with_context(self):
        """With project context, ganglia get resolved_observes in metadata."""
        nerve = _make_nerve("the_nerve")
        target_mod = _make_module("target", nerves=(nerve,), exports=("the_nerve",))

        ganglion = _make_ganglion("watcher", observes=("the_nerve",))
        observer_mod = _make_module("eval", ganglia=(ganglion,))

        ctx = _build_project_context(target_mod, observer_mod)

        result = emit_python(observer_mod, project_context=ctx)

        assert '"resolved_observes"' in result
        assert '"target::the_nerve"' in result

    def test_ganglion_metadata_includes_priors_and_on_anomaly(self):
        """Ganglion metadata includes priors and on_anomaly fields."""
        ganglion = _make_ganglion("watcher", observes=("x",))
        mod = _make_module("eval", ganglia=(ganglion,))

        result = emit_python(mod)

        assert '"priors"' in result
        assert '"on_anomaly"' in result

    def test_ganglion_metadata_includes_scope(self):
        """Ganglion metadata includes scope field."""
        ganglion = _make_ganglion("watcher", observes=("x",))
        mod = _make_module("eval", ganglia=(ganglion,))

        result = emit_python(mod)

        assert '"scope"' in result

    def test_ganglion_body_preserved(self):
        """Ganglion body is preserved in emitted code."""
        ganglion = _make_ganglion("watcher", observes=("x",))
        mod = _make_module("eval", ganglia=(ganglion,))

        result = emit_python(mod)

        assert "def watcher(signal):" in result
        assert "return signal" in result

    def test_ganglion_with_depends_on(self):
        """Ganglia with depends_on emit dependencies."""
        ganglion = GanglionDecl(
            name="watcher",
            layer=Layer.DOMAIN,
            visibility=Visibility.INTERNAL,
            intent="Test ganglion with deps",
            observes=("x",),
            scope=EvaluatesAt.FUNCTION_BOUNDARY,
            priors="None",
            on_anomaly="Log",
            depends_on=(
                InlineAxon(
                    target="helper",
                    relation=Relation.CALLS,
                    carries="signal data",
                    coupling=Coupling.TIGHT,
                ),
            ),
            body="def watcher():\n    pass",
            location=_loc(30, 40),
        )
        mod = _make_module("eval", ganglia=(ganglion,))

        result = emit_python(mod)

        assert 'dependencies=["helper"]' in result


# ===========================================================================
# Test 12.5: resolve_observes convenience function
# ===========================================================================


class TestResolveObservesConvenience:
    """Tests for the resolve_observes convenience function."""

    def test_resolve_observes_returns_all_three_outputs(self):
        nerve = _make_nerve("fn")
        target = _make_module("t", nerves=(nerve,))
        ganglion = _make_ganglion("w", observes=("fn",))
        observer = _make_module("o", ganglia=(ganglion,))
        ctx = _build_project_context(target, observer)

        resolved, privileged, errors = resolve_observes(
            ganglion, "o", ctx, mode=StrictnessMode.DEV
        )

        assert len(resolved) == 1
        assert isinstance(resolved[0], ResolvedObserves)
        assert isinstance(privileged, list)
        assert isinstance(errors, list)


# ===========================================================================
# Test: Emitted code compiles
# ===========================================================================


class TestEmittedCodeCompiles:
    """Tests that emitted Python is syntactically valid."""

    def test_ganglion_output_compiles(self):
        ganglion = _make_ganglion("watcher", observes=("x",))
        mod = _make_module("eval", ganglia=(ganglion,))
        result = emit_python(mod)
        compile(result, "<ganglion_test>", "exec")

    def test_test_output_compiles(self):
        test_decl = _make_test("test_fn", tests_field=("x",))
        mod = _make_module("test_mod", tests=(test_decl,), exports=())
        result = emit_python(mod)
        compile(result, "<test_test>", "exec")

    def test_mixed_module_compiles(self):
        """Module with nerves, ganglia, and tests all compiles."""
        nerve = _make_nerve("fn")
        ganglion = _make_ganglion("watcher", observes=("fn",))
        test_decl = _make_test("test_fn", tests_field=("fn",))
        mod = _make_module(
            "mixed",
            nerves=(nerve,),
            ganglia=(ganglion,),
            tests=(test_decl,),
            exports=("fn",),
        )
        result = emit_python(mod)
        compile(result, "<mixed_test>", "exec")

    def test_ganglion_with_project_context_compiles(self):
        """Ganglion emission with resolved observes compiles."""
        nerve = _make_nerve("target_nerve")
        target = _make_module("target", nerves=(nerve,), exports=("target_nerve",))
        ganglion = _make_ganglion("watcher", observes=("target_nerve",))
        observer = _make_module("observer", ganglia=(ganglion,))
        ctx = _build_project_context(target, observer)

        result = emit_python(observer, project_context=ctx)
        compile(result, "<ganglion_ctx_test>", "exec")


# ===========================================================================
# Test: Determinism
# ===========================================================================


class TestDeterminism:
    """Tests that observes resolution and emission are deterministic."""

    def test_observes_resolution_deterministic(self):
        """Repeated resolution produces identical output."""
        n1 = _make_nerve("b_nerve")
        n2 = _make_nerve("a_nerve")
        mod = _make_module("mod", nerves=(n1, n2))
        ctx = _build_project_context(mod)

        resolver = ObservesResolver(mode=StrictnessMode.DEV)
        r1, _ = resolver.resolve_patterns(("mod.*",), ctx)
        r2, _ = resolver.resolve_patterns(("mod.*",), ctx)

        assert r1[0].resolved_targets == r2[0].resolved_targets

    def test_privileged_imports_sorted(self):
        """Privileged imports are sorted by canonical_id."""
        n1 = _make_nerve("b_fn", visibility=Visibility.INTERNAL)
        n2 = _make_nerve("a_fn", visibility=Visibility.INTERNAL)
        mod = _make_module("target", nerves=(n1, n2))
        ctx = _build_project_context(mod)

        privileged = determine_privileged_imports(
            current_module_name="observer",
            resolved_canonical_ids=["target::b_fn", "target::a_fn"],
            context=ctx,
            import_kind="privileged_observation",
            referenced_in="observes",
        )

        # Should be sorted by canonical_id
        assert privileged[0].canonical_id == "target::a_fn"
        assert privileged[1].canonical_id == "target::b_fn"


# ===========================================================================
# Test: Emitter errors property
# ===========================================================================


class TestEmitterErrors:
    """Tests that the emitter exposes resolution errors."""

    def test_emitter_collects_empty_observes_errors(self):
        """Emitter exposes EMPTY_OBSERVES errors from ganglion resolution."""
        ganglion = _make_ganglion("watcher", observes=("nonexistent.*",))
        mod = _make_module("observer", ganglia=(ganglion,))
        ctx = _build_project_context(mod)

        emitter = PythonEmitter(
            project_context=ctx,
            mode=StrictnessMode.STRICT,
            filename="observer.s0ma",
        )
        emitter.emit(mod)

        assert len(emitter.errors) == 1
        assert emitter.errors[0].code == "EMPTY_OBSERVES"
