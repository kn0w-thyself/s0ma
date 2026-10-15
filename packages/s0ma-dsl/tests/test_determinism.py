"""Determinism hardening tests for the s0ma DSL transpiler (Milestone 21).

Systematically verifies and enforces deterministic output across every artifact.
Non-determinism is a correctness bug per PRD P6 and NFR-01.

This module provides repeat-run CI tests that compile the same fixtures
multiple times, diff all outputs, and fail on any difference.

Ordering rules enforced (PRD §2.5.3):
  - Components: preserved in source declaration order.
  - Edges (authored): sorted by (source canonical ID, target canonical ID).
  - Edges (derived): sorted by (source canonical ID, target canonical ID).
  - Edges (verification): sorted by (test canonical ID, validates canonical ID).
  - Import lists: preserve source declaration order.
  - Privileged imports: sorted by canonical_id.
  - Python imports: PEP 8 groups, sorted alphabetically within each group.
  - Diagnostics: per-file in source order, cross-file in sorted filename order.
  - JSON keys: always sorted via sort_keys=True.
  - Content hash: SHA-256 over raw source text — deterministic by definition.
  - File discovery: sorted(Path.rglob("*.s0ma")).
  - Module graph iteration: sorted(modules) in all resolver phases.
  - Glob resolution: sorted by canonical_id.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.codegen.python_emitter import emit_python
from s0ma_dsl.codegen.source_map import generate_source_map
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma, parse_s0ma_with_warnings
from s0ma_dsl.resolver.dependency import resolve_dependencies
from s0ma_dsl.semantic.derived_edges import analyze_derived_edges
from s0ma_dsl.semantic.validator import validate_module
from tests.conftest import (
    INVALID_FIXTURES_DIR,
    VALID_FIXTURES_DIR,
    assert_artifacts_identical,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOLDEN_FIXTURE = VALID_FIXTURES_DIR / "signal_processor.s0ma"
GOLDEN_PROJECT_DIR = VALID_FIXTURES_DIR / "golden_project"
MULTI_MODULE_DIR = VALID_FIXTURES_DIR / "multi_module"

NUM_REPEAT_RUNS = 3  # Triple-run per M21 task 21.2


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------


def _run_full_pipeline(
    source_path: Path,
    mode: StrictnessMode = StrictnessMode.DEV,
) -> dict:
    """Run the complete single-file pipeline, returning all artifacts."""
    source_text = source_path.read_text(encoding="utf-8")

    # Parse
    module = parse_s0ma(source_text, str(source_path), mode)

    # Validate
    sem_errors = list(validate_module(module, mode=mode, filename=str(source_path)))

    # Derived edges
    derived_edges, der_errors = analyze_derived_edges(
        module, mode=mode, filename=str(source_path)
    )
    derived_edges = list(derived_edges)
    der_errors = list(der_errors)

    # Python emission
    py_code = emit_python(module, mode=mode, filename=str(source_path))

    # IR generation
    transpiled_path = str(source_path).replace(".s0ma", ".py")
    ir_doc = build_ir(
        module,
        derived_edges=derived_edges,
        source_file=str(source_path),
        source_text=source_text,
        transpiled_file=transpiled_path,
    )
    ir_json = json.dumps(ir_doc.to_dict(), indent=2, sort_keys=True)

    # Source map
    smap = generate_source_map(
        module, py_code,
        source_file=str(source_path),
        output_file=transpiled_path,
    )
    smap_json = smap.to_json()

    return {
        "module": module,
        "sem_errors": sem_errors,
        "der_errors": der_errors,
        "derived_edges": derived_edges,
        "python_code": py_code,
        "ir_json": ir_json,
        "ir_dict": ir_doc.to_dict(),
        "source_map_json": smap_json,
        "source_text": source_text,
    }


def _run_multi_module_pipeline(
    project_dir: Path,
    mode: StrictnessMode = StrictnessMode.DEV,
) -> dict:
    """Run the full pipeline on a multi-module project."""
    s0ma_files = sorted(project_dir.glob("*.s0ma"))
    module_results: dict[str, dict] = {}
    parsed_modules: dict[str, object] = {}
    filenames: dict[str, str] = {}

    for f in s0ma_files:
        result = _run_full_pipeline(f, mode)
        mod_name = result["module"].module.name
        module_results[mod_name] = result
        parsed_modules[mod_name] = result["module"]
        filenames[mod_name] = str(f)

    resolution_errors = resolve_dependencies(
        parsed_modules, mode=mode, filenames=filenames, check_imports=False
    )

    return {
        "module_results": module_results,
        "resolution_errors": list(resolution_errors),
    }


def _collect_diagnostics(
    source_path: Path,
    mode: StrictnessMode = StrictnessMode.DEV,
) -> list[tuple[str, str, int]]:
    """Parse and validate, returning diagnostics as (code, severity, line) tuples."""
    source_text = source_path.read_text(encoding="utf-8")
    try:
        module, warnings = parse_s0ma_with_warnings(
            source_text, str(source_path), mode
        )
    except Exception as exc:
        # Parse failures still produce structured errors
        if hasattr(exc, "code"):
            return [(exc.code, exc.severity, exc.line)]
        return [("PARSE_ERROR", "error", 0)]

    errors = list(validate_module(module, mode=mode, filename=str(source_path)))
    _, der_errors = analyze_derived_edges(
        module, mode=mode, filename=str(source_path)
    )
    all_diags = list(warnings) + errors + list(der_errors)
    return [(d.code, d.severity, d.line) for d in all_diags]


# ===========================================================================
# TRIPLE-RUN TESTS — Single File
# ===========================================================================


class TestTripleRunSingleFile:
    """Triple-run on the golden fixture produces identical output (M21 Task 21.2).

    Compiles the same fixture 3 times and diffs all outputs. Any difference
    is a determinism bug per PRD P6.
    """

    def test_python_output_triple_run(self) -> None:
        """Python emission is identical across 3 runs."""
        outputs = [_run_full_pipeline(GOLDEN_FIXTURE)["python_code"]
                   for _ in range(NUM_REPEAT_RUNS)]
        for i in range(1, NUM_REPEAT_RUNS):
            assert outputs[0] == outputs[i], (
                f"Python output differs: run 0 vs run {i}"
            )

    def test_ir_json_triple_run(self) -> None:
        """IR JSON is identical across 3 runs."""
        outputs = [_run_full_pipeline(GOLDEN_FIXTURE)["ir_json"]
                   for _ in range(NUM_REPEAT_RUNS)]
        for i in range(1, NUM_REPEAT_RUNS):
            assert outputs[0] == outputs[i], (
                f"IR JSON differs: run 0 vs run {i}"
            )

    def test_source_map_triple_run(self) -> None:
        """Source map JSON is identical across 3 runs."""
        outputs = [_run_full_pipeline(GOLDEN_FIXTURE)["source_map_json"]
                   for _ in range(NUM_REPEAT_RUNS)]
        for i in range(1, NUM_REPEAT_RUNS):
            assert outputs[0] == outputs[i], (
                f"Source map JSON differs: run 0 vs run {i}"
            )

    def test_content_hash_triple_run(self) -> None:
        """Content hash is identical across 3 runs."""
        hashes = [_run_full_pipeline(GOLDEN_FIXTURE)["ir_dict"]["module"]["content_hash"]
                  for _ in range(NUM_REPEAT_RUNS)]
        for i in range(1, NUM_REPEAT_RUNS):
            assert hashes[0] == hashes[i], (
                f"Content hash differs: run 0 vs run {i}"
            )

    def test_derived_edges_triple_run(self) -> None:
        """Derived edges are identical across 3 runs."""
        runs = [_run_full_pipeline(GOLDEN_FIXTURE) for _ in range(NUM_REPEAT_RUNS)]
        edges_0 = [(e.source, e.target_canonical, e.relation.value, e.origin)
                    for e in runs[0]["derived_edges"]]
        for i in range(1, NUM_REPEAT_RUNS):
            edges_i = [(e.source, e.target_canonical, e.relation.value, e.origin)
                       for e in runs[i]["derived_edges"]]
            assert edges_0 == edges_i, (
                f"Derived edges differ: run 0 vs run {i}"
            )

    def test_diagnostics_triple_run(self) -> None:
        """Diagnostics (codes, severity, line) are identical across 3 runs."""
        outputs = [_collect_diagnostics(GOLDEN_FIXTURE)
                   for _ in range(NUM_REPEAT_RUNS)]
        for i in range(1, NUM_REPEAT_RUNS):
            assert outputs[0] == outputs[i], (
                f"Diagnostics differ: run 0 vs run {i}"
            )


# ===========================================================================
# TRIPLE-RUN TESTS — Multi-Module Project
# ===========================================================================


class TestTripleRunMultiModule:
    """Triple-run on multi-module projects produces identical output.

    Exercises cross-module resolution ordering, module graph construction,
    and multi-file diagnostic aggregation.
    """

    def _run_and_collect(self, project_dir: Path) -> dict[str, dict[str, str]]:
        """Run pipeline and collect all string artifacts per module."""
        result = _run_multi_module_pipeline(project_dir)
        collected = {}
        for mod_name, mod_result in result["module_results"].items():
            collected[mod_name] = {
                "python_code": mod_result["python_code"],
                "ir_json": mod_result["ir_json"],
                "source_map_json": mod_result["source_map_json"],
            }
        # Also collect resolution error codes
        collected["__resolution_errors__"] = {
            "codes": str([(e.code, e.severity, e.line)
                          for e in result["resolution_errors"]]),
        }
        return collected

    def test_golden_project_triple_run(self) -> None:
        """Golden project (5+ modules) produces identical artifacts across 3 runs."""
        runs = [self._run_and_collect(GOLDEN_PROJECT_DIR)
                for _ in range(NUM_REPEAT_RUNS)]
        for i in range(1, NUM_REPEAT_RUNS):
            assert runs[0].keys() == runs[i].keys(), (
                f"Module set differs: run 0 vs run {i}"
            )
            for mod_name in runs[0]:
                for artifact_name in runs[0][mod_name]:
                    assert runs[0][mod_name][artifact_name] == runs[i][mod_name][artifact_name], (
                        f"Module {mod_name}, artifact {artifact_name} differs: "
                        f"run 0 vs run {i}"
                    )

    def test_multi_module_triple_run(self) -> None:
        """Multi-module fixture produces identical artifacts across 3 runs."""
        runs = [self._run_and_collect(MULTI_MODULE_DIR)
                for _ in range(NUM_REPEAT_RUNS)]
        for i in range(1, NUM_REPEAT_RUNS):
            assert runs[0].keys() == runs[i].keys(), (
                f"Module set differs: run 0 vs run {i}"
            )
            for mod_name in runs[0]:
                for artifact_name in runs[0][mod_name]:
                    assert runs[0][mod_name][artifact_name] == runs[i][mod_name][artifact_name], (
                        f"Module {mod_name}, artifact {artifact_name} differs: "
                        f"run 0 vs run {i}"
                    )

    def test_resolution_errors_deterministic(self) -> None:
        """Cross-module resolution errors are in identical order across runs."""
        runs = [_run_multi_module_pipeline(MULTI_MODULE_DIR)
                for _ in range(NUM_REPEAT_RUNS)]
        codes_0 = [(e.code, e.severity, e.line) for e in runs[0]["resolution_errors"]]
        for i in range(1, NUM_REPEAT_RUNS):
            codes_i = [(e.code, e.severity, e.line)
                       for e in runs[i]["resolution_errors"]]
            assert codes_0 == codes_i, (
                f"Resolution errors differ: run 0 vs run {i}"
            )


# ===========================================================================
# TRIPLE-RUN TESTS — Invalid Fixtures (Diagnostic Ordering)
# ===========================================================================


class TestTripleRunDiagnostics:
    """Diagnostic ordering for invalid fixtures is deterministic across runs.

    Each invalid fixture should produce the same error codes in the same
    order every time.
    """

    @pytest.fixture(params=sorted(INVALID_FIXTURES_DIR.glob("*.s0ma")),
                    ids=lambda p: p.stem)
    def invalid_fixture(self, request: pytest.FixtureRequest) -> Path:
        """Parametrize over all invalid .s0ma fixtures."""
        return request.param

    def test_invalid_fixture_diagnostics_deterministic(
        self, invalid_fixture: Path
    ) -> None:
        """Diagnostics for an invalid fixture are identical across 3 runs."""
        outputs = [_collect_diagnostics(invalid_fixture, StrictnessMode.STRICT)
                   for _ in range(NUM_REPEAT_RUNS)]
        for i in range(1, NUM_REPEAT_RUNS):
            assert outputs[0] == outputs[i], (
                f"Diagnostics for {invalid_fixture.name} differ: run 0 vs run {i}"
            )


# ===========================================================================
# TRIPLE-RUN TESTS — All Valid Fixtures
# ===========================================================================


class TestTripleRunAllValidFixtures:
    """All valid single-file fixtures produce identical output across runs."""

    @pytest.fixture(params=sorted(VALID_FIXTURES_DIR.glob("*.s0ma")),
                    ids=lambda p: p.stem)
    def valid_fixture(self, request: pytest.FixtureRequest) -> Path:
        """Parametrize over all valid single-file .s0ma fixtures."""
        return request.param

    def test_valid_fixture_all_artifacts_deterministic(
        self, valid_fixture: Path
    ) -> None:
        """All artifacts (Python, IR, source map) are identical across 3 runs."""
        runs = [_run_full_pipeline(valid_fixture) for _ in range(NUM_REPEAT_RUNS)]
        for i in range(1, NUM_REPEAT_RUNS):
            assert runs[0]["python_code"] == runs[i]["python_code"], (
                f"{valid_fixture.name}: Python differs run 0 vs {i}"
            )
            assert runs[0]["ir_json"] == runs[i]["ir_json"], (
                f"{valid_fixture.name}: IR differs run 0 vs {i}"
            )
            assert runs[0]["source_map_json"] == runs[i]["source_map_json"], (
                f"{valid_fixture.name}: source map differs run 0 vs {i}"
            )


# ===========================================================================
# TRIPLE-RUN TESTS — Stress Project (File I/O Path)
# ===========================================================================


class TestTripleRunFileIO:
    """Triple-run through the full file I/O path (write-to-disk artifacts).

    This exercises the _transpile_single_file function that writes .py,
    .s0ma.json, and .s0ma.map to disk — verifying that the file-level
    output is deterministic.

    Comparisons are RAW bytes, deliberately without path normalisation
    (WIN-M3): artifacts reference their sibling .py by basename, so two
    builds of the same source must be byte-identical even into different
    output directories, on every OS. The old replace-based normalisation
    masked embedded absolute paths on POSIX while silently no-opping on
    Windows (JSON escapes backslashes, so a native-form needle never
    matched the artifact bytes) — do not reintroduce it.
    """

    def test_file_io_triple_run(self, tmp_path: Path) -> None:
        """Three transpile-to-disk runs produce identical files."""
        from s0ma_dsl.cli.main import _transpile_single_file

        source_path = GOLDEN_FIXTURE
        dirs = []
        for i in range(NUM_REPEAT_RUNS):
            d = tmp_path / f"run_{i}"
            d.mkdir()
            _transpile_single_file(
                source_path, mode=StrictnessMode.DEV,
                output_dir=d, emit_ir=True, emit_source_map=True,
            )
            dirs.append(d)

        suffixes = [".py", ".s0ma.json", ".s0ma.map"]
        for suffix in suffixes:
            contents = []
            for d in dirs:
                fname = f"signal_processor{suffix}"
                f = d / fname
                assert f.exists(), f"Missing {f}"
                contents.append(f.read_text(encoding="utf-8"))

            for i in range(1, NUM_REPEAT_RUNS):
                assert_artifacts_identical(
                    f"signal_processor{suffix} (run 0 vs run {i})",
                    contents[0], contents[i],
                )

    def test_multi_module_file_io_triple_run(self, tmp_path: Path) -> None:
        """Three transpile-to-disk runs of a multi-module project are identical."""
        from s0ma_dsl.cli.main import _transpile_single_file

        s0ma_files = sorted(GOLDEN_PROJECT_DIR.glob("*.s0ma"))
        dirs = []
        for i in range(NUM_REPEAT_RUNS):
            d = tmp_path / f"run_{i}"
            d.mkdir()
            for sf in s0ma_files:
                _transpile_single_file(
                    sf, mode=StrictnessMode.DEV,
                    output_dir=d, emit_ir=True, emit_source_map=True,
                )
            dirs.append(d)

        # Collect all generated files from run 0
        run0_files = sorted(dirs[0].iterdir())
        for i in range(1, NUM_REPEAT_RUNS):
            run_i_files = sorted(dirs[i].iterdir())
            assert len(run0_files) == len(run_i_files), (
                f"Different file count: run 0 ({len(run0_files)}) vs "
                f"run {i} ({len(run_i_files)})"
            )
            for f0, fi in zip(run0_files, run_i_files, strict=False):
                assert f0.name == fi.name, (
                    f"File name mismatch: {f0.name} vs {fi.name}"
                )
                assert_artifacts_identical(
                    f"{f0.name} (run 0 vs run {i})",
                    f0.read_text(encoding="utf-8"),
                    fi.read_text(encoding="utf-8"),
                )

    def test_artifacts_reference_outputs_by_basename(
        self, tmp_path: Path
    ) -> None:
        """IR/map reference the generated .py by basename, never by full path.

        Regression guard for the WIN-M3 Windows nondeterminism cluster:
        the IR's ``transpiled_file`` and the map's ``output_file`` used to
        embed the build's own output path, so every build directory (and
        every machine) produced different artifact bytes — and on Windows
        the JSON-escaped backslash rendering hid the path from every
        replace-based normalisation. The artifacts sit next to the .py
        they reference, so the basename is the complete reference.

        Checks both the raw and the JSON-escaped rendering of the output
        dir so the assertion stays meaningful on Windows, where the two
        renderings differ.
        """
        from s0ma_dsl.cli.main import _transpile_single_file

        out = tmp_path / "out"
        out.mkdir()
        _transpile_single_file(
            GOLDEN_FIXTURE, mode=StrictnessMode.DEV,
            output_dir=out, emit_ir=True, emit_source_map=True,
        )

        raw_ir = (out / "signal_processor.s0ma.json").read_text(
            encoding="utf-8"
        )
        raw_map = (out / "signal_processor.s0ma.map").read_text(
            encoding="utf-8"
        )

        ir = json.loads(raw_ir)
        smap = json.loads(raw_map)
        assert ir["module"]["transpiled_file"] == "signal_processor.py"
        assert smap["output_file"] == "signal_processor.py"

        # json.dumps(...)[1:-1] is the JSON-escaped rendering without the
        # surrounding quotes (identical to str() on POSIX, backslash-doubled
        # on Windows).
        for needle in {str(out), json.dumps(str(out))[1:-1]}:
            assert needle not in raw_ir, (
                f"output dir leaked into IR artifact: {needle!r}"
            )
            assert needle not in raw_map, (
                f"output dir leaked into map artifact: {needle!r}"
            )


# ===========================================================================
# ORDERING RULE ENFORCEMENT
# ===========================================================================


class TestIROrderingRules:
    """Verify IR ordering rules per PRD §2.5.3 are correctly applied."""

    def _get_ir(self) -> dict:
        """Get the golden fixture IR as a dict."""
        result = _run_full_pipeline(GOLDEN_FIXTURE)
        return result["ir_dict"]

    def test_components_in_source_declaration_order(self) -> None:
        """Components are ordered by declaration order in the source file.

        Standalone axons are not components — they produce edges, not
        component entries — so they are excluded from the ordering check.
        """
        from s0ma_dsl.ast_nodes.nodes import StandaloneAxonDecl

        result = _run_full_pipeline(GOLDEN_FIXTURE)
        module = result["module"]
        ir = result["ir_dict"]

        # Collect names from AST in declaration order, excluding standalone axons
        declared_order = [
            d.name for d in module.all_declarations
            if not isinstance(d, StandaloneAxonDecl)
        ]

        # Collect names from IR components
        ir_order = [c["canonical_id"].split("::")[-1] for c in ir["components"]]

        assert ir_order == declared_order, (
            f"IR component order doesn't match declaration order.\n"
            f"Declared: {declared_order}\n"
            f"IR:       {ir_order}"
        )

    def test_authored_edges_sorted(self) -> None:
        """Authored edges are sorted by (source, target)."""
        ir = self._get_ir()
        edges = ir["edges"]["authored"]
        if len(edges) < 2:
            pytest.skip("Need at least 2 authored edges to test ordering")

        pairs = [(e["source"], e["target"]) for e in edges]
        assert pairs == sorted(pairs), (
            f"Authored edges not sorted by (source, target): {pairs}"
        )

    def test_derived_edges_sorted(self) -> None:
        """Derived edges are sorted by (source, target)."""
        ir = self._get_ir()
        edges = ir["edges"]["derived"]
        if len(edges) < 2:
            pytest.skip("Need at least 2 derived edges to test ordering")

        pairs = [(e["source"], e["target"]) for e in edges]
        assert pairs == sorted(pairs), (
            f"Derived edges not sorted by (source, target): {pairs}"
        )

    def test_verification_edges_sorted(self) -> None:
        """Verification edges are sorted by (test, validates)."""
        ir = self._get_ir()
        edges = ir["edges"]["verification"]
        if len(edges) < 2:
            pytest.skip("Need at least 2 verification edges to test ordering")

        pairs = [(e["test"], e["validates"]) for e in edges]
        assert pairs == sorted(pairs), (
            f"Verification edges not sorted by (test, validates): {pairs}"
        )

    def test_json_keys_sorted(self) -> None:
        """IR JSON has sorted keys at all levels."""
        result = _run_full_pipeline(GOLDEN_FIXTURE)
        ir_json = result["ir_json"]

        # Re-serialize with sort_keys and compare
        ir_dict = json.loads(ir_json)
        re_serialized = json.dumps(ir_dict, indent=2, sort_keys=True)
        assert ir_json == re_serialized, (
            "IR JSON keys are not consistently sorted"
        )


class TestPythonEmissionOrderingRules:
    """Verify Python emission ordering rules."""

    def test_import_groups_pep8_sorted(self) -> None:
        """Import lines within each PEP 8 group are alphabetically sorted."""
        result = _run_full_pipeline(GOLDEN_FIXTURE)
        py_code = result["python_code"]

        # Extract import lines
        [
            line for line in py_code.splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]

        # Group consecutive import lines (separated by blank lines)
        groups: list[list[str]] = []
        current_group: list[str] = []
        prev_was_import = False
        for line in py_code.splitlines():
            is_import = line.startswith("import ") or line.startswith("from ")
            if is_import:
                current_group.append(line)
                prev_was_import = True
            elif prev_was_import and line.strip() == "":
                if current_group:
                    groups.append(current_group)
                    current_group = []
                prev_was_import = False
            else:
                if current_group:
                    groups.append(current_group)
                    current_group = []
                prev_was_import = False
        if current_group:
            groups.append(current_group)

        # Each group should be sorted
        for i, group in enumerate(groups):
            assert group == sorted(group), (
                f"Import group {i} is not sorted: {group}"
            )

    def test_all_list_deterministic(self) -> None:
        """__all__ list is deterministic (matches exports)."""
        result = _run_full_pipeline(GOLDEN_FIXTURE)
        py_code = result["python_code"]

        # Find __all__ line
        for line in py_code.splitlines():
            if line.startswith("__all__"):
                # Run it twice and compare
                result2 = _run_full_pipeline(GOLDEN_FIXTURE)
                for line2 in result2["python_code"].splitlines():
                    if line2.startswith("__all__"):
                        assert line == line2, (
                            f"__all__ differs between runs:\n  {line}\n  {line2}"
                        )
                        return
        # If no __all__ found, that's also fine (some modules have empty exports)


class TestStressProjectDeterminism:
    """Determinism with synthetic stress projects."""

    def test_stress_project_triple_run(self, tmp_path: Path) -> None:
        """A 10-module stress project produces identical artifacts across 3 runs."""
        from tests.stress_fixture_generator import generate_stress_project

        project_dir = tmp_path / "stress"
        s0ma_files = generate_stress_project(project_dir, num_modules=10, seed=42)

        runs = []
        for _ in range(NUM_REPEAT_RUNS):
            artifacts = {}
            for sf in s0ma_files:
                result = _run_full_pipeline(sf)
                mod_name = result["module"].module.name
                artifacts[mod_name] = {
                    "python": result["python_code"],
                    "ir": result["ir_json"],
                    "smap": result["source_map_json"],
                }
            runs.append(artifacts)

        for i in range(1, NUM_REPEAT_RUNS):
            assert runs[0].keys() == runs[i].keys(), (
                f"Module set differs: run 0 vs run {i}"
            )
            for mod_name in runs[0]:
                for key in ("python", "ir", "smap"):
                    assert runs[0][mod_name][key] == runs[i][mod_name][key], (
                        f"Stress module {mod_name} {key} differs: run 0 vs run {i}"
                    )


# ===========================================================================
# STRICTNESS MODE DETERMINISM
# ===========================================================================


class TestStrictnessModeDeterminism:
    """Verify that each strictness mode produces deterministic output."""

    @pytest.fixture(params=[
        StrictnessMode.MIGRATION,
        StrictnessMode.DEV,
        StrictnessMode.STRICT,
        StrictnessMode.RELEASE,
    ], ids=lambda m: m.value)
    def mode(self, request: pytest.FixtureRequest) -> StrictnessMode:
        return request.param

    def test_mode_diagnostics_deterministic(self, mode: StrictnessMode) -> None:
        """Diagnostics are deterministic in every strictness mode."""
        outputs = [_collect_diagnostics(GOLDEN_FIXTURE, mode)
                   for _ in range(NUM_REPEAT_RUNS)]
        for i in range(1, NUM_REPEAT_RUNS):
            assert outputs[0] == outputs[i], (
                f"Diagnostics in {mode.value} mode differ: run 0 vs run {i}"
            )
