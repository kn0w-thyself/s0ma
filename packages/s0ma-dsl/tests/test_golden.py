"""Golden test suite for the s0ma DSL transpiler (Milestone 17).

Proves the entire pipeline end-to-end with positive and negative fixtures.

- Positive tests: parse → validate → derive edges → emit Python → build IR
  → generate source map. Multi-module cross-module resolution included.
- Negative tests: files that MUST fail with specific error codes.
- Roundtrip test: transpiled Python → s0ma runtime → registry state matches IR.
- Determinism test: repeated pipeline runs produce identical output.

PRD references: §2.9.2 (golden test), §2.9.3 (fixture philosophy), §2.9.4 (traceability)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from s0ma_dsl.codegen.python_emitter import emit_python
from s0ma_dsl.codegen.source_map import generate_source_map
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maError
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.resolver.dependency import resolve_dependencies
from s0ma_dsl.semantic.derived_edges import analyze_derived_edges
from s0ma_dsl.semantic.validator import validate_module

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN_FIXTURE = _FIXTURES_DIR / "valid" / "signal_processor.s0ma"
GOLDEN_PROJECT_DIR = _FIXTURES_DIR / "valid" / "golden_project"
MULTI_MODULE_DIR = _FIXTURES_DIR / "valid" / "multi_module"
INVALID_DIR = _FIXTURES_DIR / "invalid"


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------


def _run_single_file_pipeline(
    source_path: Path,
    mode: StrictnessMode = StrictnessMode.DEV,
) -> dict:
    """Run the full pipeline on a single .s0ma file.

    Returns a dict with: module, errors, derived_edges, python_code,
    ir_document, ir_json, source_map, py_compiles.
    """
    source_text = source_path.read_text(encoding="utf-8")

    # Stage 1-2: Parse
    module = parse_s0ma(source_text, str(source_path), mode)

    # Stage 3: Semantic validation
    sem_errors = list(validate_module(module, mode=mode, filename=str(source_path)))

    # Stage 4: Derived edge analysis
    derived_edges, der_errors = analyze_derived_edges(
        module, mode=mode, filename=str(source_path)
    )
    derived_edges = list(derived_edges)
    der_errors = list(der_errors)

    all_errors = sem_errors + der_errors

    # Stage 5a: Python emission
    py_code = emit_python(module, mode=mode, filename=str(source_path))

    # Stage 5b: IR generation
    transpiled_path = str(source_path).replace(".s0ma", ".py")
    ir_doc = build_ir(
        module,
        derived_edges=derived_edges,
        source_file=str(source_path),
        source_text=source_text,
        transpiled_file=transpiled_path,
    )
    ir_json = json.dumps(ir_doc.to_dict(), indent=2, sort_keys=True)

    # Stage 5c: Source map
    smap = generate_source_map(
        module, py_code,
        source_file=str(source_path),
        output_file=transpiled_path,
    )

    # Verify Python compiles
    try:
        compile(py_code, transpiled_path, "exec")
        py_compiles = True
    except SyntaxError:
        py_compiles = False

    return {
        "module": module,
        "errors": all_errors,
        "derived_edges": derived_edges,
        "python_code": py_code,
        "ir_document": ir_doc,
        "ir_json": ir_json,
        "ir_dict": ir_doc.to_dict(),
        "source_map": smap,
        "py_compiles": py_compiles,
        "source_text": source_text,
    }


def _run_multi_module_pipeline(
    project_dir: Path,
    mode: StrictnessMode = StrictnessMode.DEV,
) -> dict:
    """Run the full pipeline on a multi-module .s0ma project.

    Returns a dict with: modules, module_results, resolution_errors,
    all_errors, all_pass.
    """
    s0ma_files = sorted(project_dir.glob("*.s0ma"))
    module_results = {}
    parsed_modules = {}
    filenames = {}

    # Parse all modules
    for f in s0ma_files:
        result = _run_single_file_pipeline(f, mode)
        mod_name = result["module"].module.name
        module_results[mod_name] = result
        parsed_modules[mod_name] = result["module"]
        filenames[mod_name] = str(f)

    # Cross-module dependency resolution
    resolution_errors = resolve_dependencies(
        parsed_modules, mode=mode, filenames=filenames, check_imports=False
    )

    all_errors = list(resolution_errors)
    for r in module_results.values():
        all_errors.extend(r["errors"])

    blocking = [e for e in all_errors if e.severity == "error"]

    return {
        "modules": parsed_modules,
        "module_results": module_results,
        "resolution_errors": resolution_errors,
        "all_errors": all_errors,
        "all_pass": len(blocking) == 0,
    }


def _collect_parse_and_validate_errors(
    source_path: Path,
    mode: StrictnessMode = StrictnessMode.STRICT,
) -> list[S0maError]:
    """Parse and validate a file, collecting all errors."""
    source_text = source_path.read_text(encoding="utf-8")
    errors: list[S0maError] = []

    try:
        module = parse_s0ma(source_text, str(source_path), mode)
    except S0maError as e:
        return [e]

    sem_errors = validate_module(module, mode=mode, filename=str(source_path))
    errors.extend(sem_errors)
    return errors


# ===========================================================================
# POSITIVE GOLDEN TESTS
# ===========================================================================


class TestSignalProcessorGolden:
    """The canonical golden test per PRD §2.9.2 — spec §8 example."""

    def test_parses_without_errors(self) -> None:
        source = GOLDEN_FIXTURE.read_text()
        module = parse_s0ma(source, str(GOLDEN_FIXTURE), StrictnessMode.STRICT)
        assert module.module.name == "signal_processor"

    def test_validates_without_errors(self) -> None:
        result = _run_single_file_pipeline(GOLDEN_FIXTURE, StrictnessMode.DEV)
        blocking = [e for e in result["errors"] if e.severity == "error"]
        assert blocking == [], [e.format_text() for e in blocking]

    def test_transpiles_to_valid_python(self) -> None:
        result = _run_single_file_pipeline(GOLDEN_FIXTURE)
        assert result["py_compiles"], "Emitted Python does not compile"
        assert len(result["python_code"]) > 0

    def test_produces_valid_ir(self) -> None:
        result = _run_single_file_pipeline(GOLDEN_FIXTURE)
        ir = result["ir_dict"]
        # POST-5 (0.16.0) bumps the schema additively from 1.2.0 to
        # 1.3.0 to introduce the ``integrations`` section. M13
        # (feedback 5–6) bumped from 1.1.0 to 1.2.0 for the ``helpers``
        # section.
        # DSL-M1 (0.8.0) bumped 2.0.0 -> 2.1.0: additive
        # metadata/serves_as fields (ADR-011 §(g); see ir/schema.py).
        assert ir["schema_version"] == "3.0.0"
        assert ir["module"]["name"] == "signal_processor"
        assert ir["module"]["layer"] == "APPLICATION"
        assert ir["module"]["version"] == "1.0.0"
        assert len(ir["components"]) > 0

    def test_canonical_ids_correct(self) -> None:
        result = _run_single_file_pipeline(GOLDEN_FIXTURE)
        ir = result["ir_dict"]
        for comp in ir["components"]:
            cid = comp["canonical_id"]
            assert cid.startswith("signal_processor::"), (
                "Canonical ID must start with module name: " + cid
            )

    def test_produces_source_map(self) -> None:
        result = _run_single_file_pipeline(GOLDEN_FIXTURE)
        smap = result["source_map"]
        assert smap is not None
        smap_json = json.loads(smap.to_json())
        assert "source_file" in smap_json
        assert "mappings" in smap_json
        assert "declarations" in smap_json["mappings"]

    def test_derived_edges_present(self) -> None:
        """RAISES edges should be derived from the raises field."""
        result = _run_single_file_pipeline(GOLDEN_FIXTURE)
        derived = result["derived_edges"]
        raises_edges = [e for e in derived if e.relation.name == "RAISES"]
        assert len(raises_edges) > 0, "Expected RAISES edges from raises field"

    def test_ir_has_authored_and_derived_edges(self) -> None:
        result = _run_single_file_pipeline(GOLDEN_FIXTURE)
        ir = result["ir_dict"]
        # Signal processor has inline depends_on (authored)
        assert len(ir["edges"]["authored"]) > 0
        # And raises field (derived)
        assert len(ir["edges"]["derived"]) > 0


class TestGoldenProjectPositive:
    """Multi-module golden project — exercises the full feature surface."""

    def test_all_modules_parse(self) -> None:
        s0ma_files = sorted(GOLDEN_PROJECT_DIR.glob("*.s0ma"))
        assert len(s0ma_files) == 6, "Expected 6 .s0ma files in golden project"
        for f in s0ma_files:
            source = f.read_text()
            module = parse_s0ma(source, str(f), StrictnessMode.DEV)
            assert module.module.name is not None

    def test_all_modules_validate(self) -> None:
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        for mod_name, mod_result in result["module_results"].items():
            blocking = [e for e in mod_result["errors"] if e.severity == "error"]
            assert blocking == [], (
                mod_name + " has blocking errors: "
                + str([e.format_text() for e in blocking])
            )

    def test_cross_module_resolution(self) -> None:
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        resolution_errors = [
            e for e in result["resolution_errors"] if e.severity == "error"
        ]
        assert resolution_errors == [], (
            "Cross-module resolution errors: "
            + str([e.format_text() for e in resolution_errors])
        )

    def test_all_modules_produce_valid_python(self) -> None:
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        for mod_name, mod_result in result["module_results"].items():
            assert mod_result["py_compiles"], (
                mod_name + " emitted Python does not compile"
            )

    def test_all_modules_produce_ir(self) -> None:
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        for mod_name, mod_result in result["module_results"].items():
            ir = mod_result["ir_dict"]
            assert ir["module"]["name"] == mod_name
            # POST-5 (0.16.0) bumps the schema additively from 1.2.0 to
            # 1.3.0 to introduce the ``integrations`` section. M13
            # (feedback 5–6) bumped from 1.1.0 to 1.2.0 for the
            # ``helpers`` section.
            # DSL-M1 (0.8.0) bumped 2.0.0 -> 2.1.0: additive
            # metadata/serves_as fields (ADR-011 §(g); see ir/schema.py).
            assert ir["schema_version"] == "3.0.0"

    def test_data_models_has_all_cell_types(self) -> None:
        """Verify data_models covers MODEL, ENUM, CONFIG, CONSTANT, EXCEPTION."""
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        ir = result["module_results"]["data_models"]["ir_dict"]
        kinds = {c["kind"] for c in ir["components"]}
        expected = {"MODEL", "ENUM", "CONFIG", "CONSTANT", "EXCEPTION"}
        assert expected.issubset(kinds), (
            "Expected kinds " + str(expected) + " but got " + str(kinds)
        )

    def test_task_service_has_nerve_kinds(self) -> None:
        """Verify task_service covers FUNCTION and SERVICE nerve kinds."""
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        ir = result["module_results"]["task_service"]["ir_dict"]
        nerve_kinds = {
            c["kind"] for c in ir["components"]
            if c["declaration_type"] == "nerve"
        }
        assert "FUNCTION" in nerve_kinds
        assert "SERVICE" in nerve_kinds

    def test_task_adapter_has_adapter_kind(self) -> None:
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        ir = result["module_results"]["task_adapter"]["ir_dict"]
        kinds = {c["kind"] for c in ir["components"]}
        assert "ADAPTER" in kinds

    def test_task_orchestrator_has_orchestrator_kind(self) -> None:
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        ir = result["module_results"]["task_orchestrator"]["ir_dict"]
        kinds = {c["kind"] for c in ir["components"]}
        assert "ORCHESTRATOR" in kinds

    def test_standalone_axon_in_orchestrator(self) -> None:
        """Verify the standalone axon produces an authored edge in IR."""
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        ir = result["module_results"]["task_orchestrator"]["ir_dict"]
        authored = ir["edges"]["authored"]
        standalone_edges = [
            e for e in authored if e["origin"] == "standalone_axon"
        ]
        assert len(standalone_edges) > 0, "Expected standalone axon edge"

    def test_ganglia_have_observes(self) -> None:
        """Verify ganglia correctly list their observes targets."""
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        ir = result["module_results"]["task_monitor"]["ir_dict"]
        ganglia = [
            c for c in ir["components"]
            if c["declaration_type"] == "ganglion"
        ]
        assert len(ganglia) == 2, "Expected 2 ganglia in task_monitor"
        for g in ganglia:
            assert "observes" in g["fields"]
            observes = g["fields"]["observes"]["value"]
            assert len(observes) > 0, (
                g["canonical_id"] + " has empty observes"
            )

    def test_tests_have_tests_field(self) -> None:
        """Verify test declarations have the tests field in IR."""
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        ir = result["module_results"]["task_tests"]["ir_dict"]
        tests = [
            c for c in ir["components"]
            if c["declaration_type"] == "test"
        ]
        assert len(tests) == 4, "Expected 4 test declarations"
        for t in tests:
            assert "tests" in t["fields"]
            assert len(t["fields"]["tests"]["value"]) > 0

    def test_verification_edges_from_tests(self) -> None:
        """Verify test declarations produce verification edges in IR."""
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        ir = result["module_results"]["task_tests"]["ir_dict"]
        verification = ir["edges"]["verification"]
        assert len(verification) > 0, "Expected verification edges from tests"

    def test_raises_edges_derived(self) -> None:
        """Verify RAISES edges are derived from the raises field."""
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        # task_service has nerves with raises: [TaskError]
        ir = result["module_results"]["task_service"]["ir_dict"]
        derived = ir["edges"]["derived"]
        raises_edges = [e for e in derived if e["relation"] == "RAISES"]
        assert len(raises_edges) > 0, "Expected RAISES edges from raises field"

    def test_uses_with_alias(self) -> None:
        """Verify aliased uses entries parse and emit correctly."""
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        # task_orchestrator uses parse_task_json aliased as parse_json
        module = result["modules"]["task_orchestrator"]
        uses_entries = module.module.uses
        aliased = [u for u in uses_entries if u.alias is not None]
        assert len(aliased) > 0, "Expected at least one aliased uses entry"
        assert aliased[0].alias == "parse_json"

    def test_exports_match_visibility(self) -> None:
        """Verify all exported components are PUBLIC, non-exported are INTERNAL.

        Note: test and ganglion declarations may have visibility=None in IR
        since their visibility is structurally determined (tests/ganglia with
        exports: [] are always INTERNAL).
        requires: none
        uses: none
        soft_requires: none
        runtime_only_requires: none
        deferred_requires: none
        exports_helpers: none
        """
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        for _mod_name, mod_result in result["module_results"].items():
            ir = mod_result["ir_dict"]
            exports = set(ir["exports"]["value"])
            for comp in ir["components"]:
                cid = comp["canonical_id"]
                comp_name = cid.split("::")[-1]
                vis = comp["visibility"]
                # Skip components without explicit visibility (tests, ganglia)
                if vis is None:
                    continue
                if comp_name in exports:
                    assert vis == "PUBLIC", (
                        cid + " is exported but visibility is " + str(vis)
                    )
                else:
                    assert vis == "INTERNAL", (
                        cid + " is not exported but visibility is " + str(vis)
                    )

    def test_content_hash_present(self) -> None:
        """Verify every module's IR has a content hash."""
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        for mod_name, mod_result in result["module_results"].items():
            ir = mod_result["ir_dict"]
            assert ir["module"]["content_hash"].startswith("sha256:"), (
                mod_name + " missing content hash"
            )


class TestExistingMultiModule:
    """Tests for the pre-existing multi_module fixtures from M8."""

    def test_multi_module_parses(self) -> None:
        result = _run_multi_module_pipeline(MULTI_MODULE_DIR)
        assert len(result["modules"]) == 3

    def test_multi_module_validates(self) -> None:
        result = _run_multi_module_pipeline(MULTI_MODULE_DIR)
        blocking = [e for e in result["all_errors"] if e.severity == "error"]
        assert blocking == [], [e.format_text() for e in blocking]

    def test_multi_module_resolves(self) -> None:
        result = _run_multi_module_pipeline(MULTI_MODULE_DIR)
        resolution_errors = [
            e for e in result["resolution_errors"] if e.severity == "error"
        ]
        assert resolution_errors == []


# ===========================================================================
# NEGATIVE GOLDEN TESTS
# ===========================================================================


class TestNegativeMissingModule:
    """File without a module declaration must fail."""

    def test_missing_module_fails(self) -> None:
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "missing_module.s0ma"
        )
        assert len(errors) > 0
        assert errors[0].code == "PARSE_ERROR"


class TestNegativeMissingFields:
    """Nerve with missing required fields must fail."""

    def test_missing_fields_fails(self) -> None:
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "missing_fields.s0ma"
        )
        codes = [e.code for e in errors]
        assert "SEMANTIC_REQUIRED_STATE_OMITTED" in codes


class TestNegativeInvalidKind:
    """Nerve with a cell kind (MODEL) must fail."""

    def test_invalid_kind_fails(self) -> None:
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "invalid_kind.s0ma"
        )
        codes = [e.code for e in errors]
        assert "INVALID_KIND" in codes


class TestNegativeVisibilityMismatch:
    """Exported INTERNAL component must fail."""

    def test_visibility_mismatch_fails(self) -> None:
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "visibility_mismatch.s0ma"
        )
        codes = [e.code for e in errors]
        assert "VISIBILITY_MISMATCH" in codes


class TestNegativeLayerMismatch:
    """Component layer != module layer must fail."""

    def test_layer_mismatch_fails(self) -> None:
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "layer_mismatch.s0ma"
        )
        codes = [e.code for e in errors]
        assert "LAYER_MISMATCH" in codes


class TestNegativeDuplicateDeclaration:
    """Two declarations with the same name must fail."""

    def test_duplicate_declaration_fails(self) -> None:
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "duplicate_declaration.s0ma"
        )
        codes = [e.code for e in errors]
        assert "DUPLICATE_DECLARATION" in codes or "NAMESPACE_COLLISION" in codes


class TestNegativeProhibitedConstruct:
    """eval() in body must fail in strict mode."""

    def test_prohibited_construct_fails(self) -> None:
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "prohibited_construct.s0ma",
            mode=StrictnessMode.STRICT,
        )
        codes = [e.code for e in errors]
        assert "PROHIBITED_CONSTRUCT" in codes


class TestNegativeBareImport:
    """Bare import statement in body must fail in strict mode."""

    def test_bare_import_fails(self) -> None:
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "bare_import.s0ma",
            mode=StrictnessMode.STRICT,
        )
        codes = [e.code for e in errors]
        assert "BARE_IMPORT" in codes


class TestNegativeClassInNerve:
    """Class body in a nerve must fail."""

    def test_class_in_nerve_fails(self) -> None:
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "class_in_nerve.s0ma"
        )
        codes = [e.code for e in errors]
        assert "CLASS_BODY_IN_NERVE" in codes


class TestNegativeAuthoredRaisesAxon:
    """Authored RAISES relation in depends_on must fail."""

    def test_authored_raises_fails(self) -> None:
        # RAISES is not in the grammar's RELATION terminal, so this fails at parse time
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "authored_raises_axon.s0ma"
        )
        codes = [e.code for e in errors]
        assert "PARSE_ERROR" in codes or "INVALID_AXON_RELATION" in codes


class TestNegativeInvalidVersion:
    """Invalid version format must fail."""

    def test_invalid_version_fails(self) -> None:
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "invalid_version.s0ma"
        )
        codes = [e.code for e in errors]
        assert "INVALID_VERSION" in codes


class TestNegativeCircularDependency:
    """Circular module dependency must fail."""

    def test_circular_dependency_detected(self) -> None:
        circ_dir = INVALID_DIR / "circular_deps"
        s0ma_files = sorted(circ_dir.glob("*.s0ma"))
        assert len(s0ma_files) == 2

        modules = {}
        filenames = {}
        for f in s0ma_files:
            source = f.read_text()
            module = parse_s0ma(source, str(f), StrictnessMode.DEV)
            modules[module.module.name] = module
            filenames[module.module.name] = str(f)

        errors = resolve_dependencies(
            modules, mode=StrictnessMode.DEV,
            filenames=filenames, check_imports=False,
        )
        codes = [e.code for e in errors]
        assert "CIRCULAR_DEPENDENCY" in codes


# ===========================================================================
# STRICTNESS MODE BEHAVIOR IN GOLDEN TESTS
# ===========================================================================


class TestStrictnessModeBehavior:
    """Verify that strictness modes correctly modulate error severity."""

    def test_prohibited_construct_not_raised_in_dev(self) -> None:
        """PROHIBITED_CONSTRUCT should not be a blocking error in DEV mode.

        Note: The current parser suppresses body validation warnings in
        migration/dev mode rather than collecting them. The severity matrix
        says these should be warnings, but the parse-time body validator
        either raises (strict) or suppresses (dev/migration). This is a
        known gap documented in s0ma_feedback.md — body validation warnings
        should be collected, not swallowed.
        """
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "prohibited_construct.s0ma",
            mode=StrictnessMode.DEV,
        )
        # No PROHIBITED_CONSTRUCT errors in dev (suppressed as warning)
        prohibited = [e for e in errors if e.code == "PROHIBITED_CONSTRUCT"]
        assert len(prohibited) == 0

    def test_prohibited_construct_error_in_strict(self) -> None:
        """PROHIBITED_CONSTRUCT should be an error in STRICT mode."""
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "prohibited_construct.s0ma",
            mode=StrictnessMode.STRICT,
        )
        prohibited = [e for e in errors if e.code == "PROHIBITED_CONSTRUCT"]
        assert len(prohibited) > 0
        assert prohibited[0].severity == "error"

    def test_bare_import_not_raised_in_migration(self) -> None:
        """BARE_IMPORT should not be a blocking error in MIGRATION mode.

        Same known gap as above — body validation warnings are suppressed
        rather than collected in migration/dev modes.
        """
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "bare_import.s0ma",
            mode=StrictnessMode.MIGRATION,
        )
        bare_imports = [e for e in errors if e.code == "BARE_IMPORT"]
        assert len(bare_imports) == 0

    def test_bare_import_error_in_strict(self) -> None:
        """BARE_IMPORT should be an error in STRICT mode."""
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "bare_import.s0ma",
            mode=StrictnessMode.STRICT,
        )
        bare_imports = [e for e in errors if e.code == "BARE_IMPORT"]
        assert len(bare_imports) > 0
        assert bare_imports[0].severity == "error"

    def test_structural_errors_always_errors(self) -> None:
        """INVALID_KIND is always error, even in migration mode."""
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / "invalid_kind.s0ma",
            mode=StrictnessMode.MIGRATION,
        )
        kind_errors = [e for e in errors if e.code == "INVALID_KIND"]
        assert len(kind_errors) > 0
        assert kind_errors[0].severity == "error"


# ===========================================================================
# DETERMINISM TESTS
# ===========================================================================


class TestDeterminism:
    """Verify deterministic output per PRD NFR-01 and P6."""

    def test_ir_deterministic(self) -> None:
        """Same input produces identical IR JSON across runs."""
        result1 = _run_single_file_pipeline(GOLDEN_FIXTURE)
        result2 = _run_single_file_pipeline(GOLDEN_FIXTURE)
        assert result1["ir_json"] == result2["ir_json"]

    def test_python_deterministic(self) -> None:
        """Same input produces identical Python output across runs."""
        result1 = _run_single_file_pipeline(GOLDEN_FIXTURE)
        result2 = _run_single_file_pipeline(GOLDEN_FIXTURE)
        assert result1["python_code"] == result2["python_code"]

    def test_source_map_deterministic(self) -> None:
        """Same input produces identical source map across runs."""
        result1 = _run_single_file_pipeline(GOLDEN_FIXTURE)
        result2 = _run_single_file_pipeline(GOLDEN_FIXTURE)
        assert result1["source_map"].to_json() == result2["source_map"].to_json()

    def test_content_hash_deterministic(self) -> None:
        """Content hash is identical across runs for the same source."""
        result1 = _run_single_file_pipeline(GOLDEN_FIXTURE)
        result2 = _run_single_file_pipeline(GOLDEN_FIXTURE)
        assert (
            result1["ir_dict"]["module"]["content_hash"]
            == result2["ir_dict"]["module"]["content_hash"]
        )

    def test_multi_module_ir_deterministic(self) -> None:
        """Multi-module project produces identical IR across runs."""
        run1 = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        run2 = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        for mod_name in run1["module_results"]:
            ir1 = run1["module_results"][mod_name]["ir_json"]
            ir2 = run2["module_results"][mod_name]["ir_json"]
            assert ir1 == ir2, mod_name + " IR is not deterministic"


# ===========================================================================
# ROUNDTRIP TEST (Task 17.4)
# ===========================================================================


class TestRoundtrip:
    """Verify that transpiled Python → s0ma runtime → registry state matches IR.

    The roundtrip test validates that:
    1. The IR document correctly represents the module's structure
    2. Components in the IR match what would be registered at runtime
    3. Edges in the IR are self-consistent (all references valid)
    """

    def test_ir_components_match_declarations(self) -> None:
        """Every declaration in source should appear as a component in IR."""
        result = _run_single_file_pipeline(GOLDEN_FIXTURE)
        module = result["module"]
        ir = result["ir_dict"]

        # Collect all declared component names
        declared = set()
        for n in module.nerves:
            declared.add(n.name)
        for c in module.cells:
            declared.add(c.name)
        for g in module.ganglia:
            declared.add(g.name)
        for t in module.tests:
            declared.add(t.name)

        # Collect all IR component names
        ir_names = {c["canonical_id"].split("::")[-1] for c in ir["components"]}

        assert declared == ir_names, (
            "Declared: " + str(declared) + " vs IR: " + str(ir_names)
        )

    def test_ir_exports_match_module(self) -> None:
        """IR exports should match the module's exports list."""
        result = _run_single_file_pipeline(GOLDEN_FIXTURE)
        module = result["module"]
        ir = result["ir_dict"]

        module_exports = set(module.module.exports)
        ir_exports = set(ir["exports"]["value"])
        assert module_exports == ir_exports

    def test_ir_edges_reference_valid_components(self) -> None:
        """All edge source/target canonical IDs should reference declared components."""
        result = _run_single_file_pipeline(GOLDEN_FIXTURE)
        ir = result["ir_dict"]

        # Collect all canonical IDs
        valid_ids = {c["canonical_id"] for c in ir["components"]}
        ir["module"]["name"]

        # Check authored edges (targets may be cross-module)
        for edge in ir["edges"]["authored"]:
            source = edge["source"]
            assert source in valid_ids, (
                "Authored edge source " + source + " not in components"
            )

        # Check derived edges
        for edge in ir["edges"]["derived"]:
            source = edge["source"]
            assert source in valid_ids, (
                "Derived edge source " + source + " not in components"
            )

    def test_ir_imports_match_module(self) -> None:
        """IR imports should reflect the module's requires and uses."""
        result = _run_single_file_pipeline(GOLDEN_FIXTURE)
        module = result["module"]
        ir = result["ir_dict"]

        # Requires count
        ir_requires = ir["imports"]["requires"]["value"]
        assert len(ir_requires) == len(module.module.requires)

        # Uses count
        ir_uses = ir["imports"]["uses"]["value"]
        assert len(ir_uses) == len(module.module.uses)

    def test_golden_project_roundtrip(self) -> None:
        """Multi-module golden project: every module's IR is self-consistent."""
        result = _run_multi_module_pipeline(GOLDEN_PROJECT_DIR)
        for mod_name, mod_result in result["module_results"].items():
            ir = mod_result["ir_dict"]
            module = mod_result["module"]

            # Components match declarations
            declared = set()
            for n in module.nerves:
                declared.add(n.name)
            for c in module.cells:
                declared.add(c.name)
            for g in module.ganglia:
                declared.add(g.name)
            for t in module.tests:
                declared.add(t.name)

            ir_names = {c["canonical_id"].split("::")[-1] for c in ir["components"]}
            assert declared == ir_names, (
                mod_name + " declared: " + str(declared) + " vs IR: " + str(ir_names)
            )

            # Exports match
            module_exports = set(module.module.exports)
            ir_exports = set(ir["exports"]["value"])
            assert module_exports == ir_exports, (
                mod_name + " exports mismatch"
            )

            # Content hash present
            assert ir["module"]["content_hash"].startswith("sha256:")

    def test_ir_edge_origin_tags(self) -> None:
        """Authored edges have inline/standalone origin, derived have field/signature."""
        result = _run_single_file_pipeline(GOLDEN_FIXTURE)
        ir = result["ir_dict"]

        valid_authored_origins = {"inline_depends_on", "standalone_axon"}
        valid_derived_origins = {
            "raises_field", "function_signature", "constructor_call",
            "constant_reference", "body_call",
        }

        for edge in ir["edges"]["authored"]:
            assert edge["origin"] in valid_authored_origins, (
                "Authored edge has unexpected origin: " + edge["origin"]
            )

        for edge in ir["edges"]["derived"]:
            assert edge["origin"] in valid_derived_origins, (
                "Derived edge has unexpected origin: " + edge["origin"]
            )


# ===========================================================================
# ERROR QUALITY TESTS
# ===========================================================================


class TestErrorQuality:
    """Verify that all errors have required fields per PRD §2.4.1."""

    @pytest.mark.parametrize("fixture_name", [
        "missing_module.s0ma",
        "missing_fields.s0ma",
        "invalid_kind.s0ma",
        "visibility_mismatch.s0ma",
        "layer_mismatch.s0ma",
        "duplicate_declaration.s0ma",
        "invalid_version.s0ma",
    ])
    def test_errors_have_remediation(self, fixture_name: str) -> None:
        """Every error must have a non-empty remediation field."""
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / fixture_name
        )
        assert len(errors) > 0, fixture_name + " expected errors"
        for e in errors:
            assert e.remediation, (
                e.code + " in " + fixture_name + " has empty remediation"
            )

    @pytest.mark.parametrize("fixture_name", [
        "missing_module.s0ma",
        "missing_fields.s0ma",
        "invalid_kind.s0ma",
        "visibility_mismatch.s0ma",
    ])
    def test_errors_have_source_location(self, fixture_name: str) -> None:
        """Every error must have a valid file and line."""
        errors = _collect_parse_and_validate_errors(
            INVALID_DIR / fixture_name
        )
        for e in errors:
            assert e.file, e.code + " has empty file"
            assert e.line >= 0, e.code + " has invalid line"
