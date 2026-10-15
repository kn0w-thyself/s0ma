"""Performance tests for the s0ma DSL transpiler.

Milestone 20 — PRD NFR-04 performance targets, §2.7.5 caching strategy.

Performance targets from PRD §1.14.4:
  - Single file parse + validate: < 100ms
  - Single file transpile (all outputs): < 500ms
  - 50-module project build: < 30s
  - Incremental single-file retranspile: < 1s
  - Memory usage: < 500MB for 100-module project

Determinism targets from PRD NFR-01 / P6:
  - Repeated runs produce byte-for-byte identical output for IR, Python,
    source maps, and diagnostics.

Caching targets from PRD §2.7.5:
  - Content-hash-based invalidation works correctly.
  - Cache hits skip the transpile pipeline.
  - Modification triggers retranspile.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import tracemalloc
from typing import TYPE_CHECKING

import s0ma_dsl.cache
from s0ma_dsl.cache import BuildCache
from s0ma_dsl.config import StrictnessMode
from tests.conftest import VALID_FIXTURES_DIR, assert_artifacts_identical

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

# D-7 (Windows plan): every hard perf/memory budget in this file scales
# by the optional ``S0MA_TEST_PERF_SCALE`` float (default 1.0 — strict).
# A CI matrix may set it per-OS if shared-runner variance (Windows
# Defender scans, coarser timers, noisy neighbors) makes the absolute
# budgets flake; scaled tests still catch order-of-magnitude
# regressions. Mirrors the CI 4x precedent in s0ma-core's
# test_structural_verifier_m2.py. The TestDeterminism class asserts
# byte-identity, not time, and takes no scaling.
_PERF_SCALE = float(os.environ.get("S0MA_TEST_PERF_SCALE", "1.0"))


def _budget(value: float) -> float:
    """Scale a hard perf budget by ``S0MA_TEST_PERF_SCALE``."""
    return value * _PERF_SCALE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_single(source_path: Path, mode: StrictnessMode = StrictnessMode.DEV):
    """Parse + validate a single .s0ma file (stages 1-3)."""
    from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
    from s0ma_dsl.semantic.validator import validate_module

    source_text = source_path.read_text(encoding="utf-8")
    module, warnings = parse_s0ma_with_warnings(source_text, str(source_path), mode)
    errors = validate_module(module, mode=mode, filename=str(source_path))
    return module, list(warnings) + list(errors)


def _transpile_single(
    source_path: Path, output_dir: Path, mode: StrictnessMode = StrictnessMode.DEV,
):
    """Full single-file transpile pipeline (stages 1-5)."""
    from s0ma_dsl.cli.main import _transpile_single_file

    return _transpile_single_file(
        source_path, mode=mode, output_dir=output_dir,
        emit_ir=True, emit_source_map=True,
    )


def _generate_stress_project(tmp_path: Path, num_modules: int = 55) -> list[Path]:
    """Generate a stress test project in the given directory."""
    from tests.stress_fixture_generator import generate_stress_project

    project_dir = tmp_path / "stress_project"
    return generate_stress_project(project_dir, num_modules=num_modules, seed=42)


# ---------------------------------------------------------------------------
# Single-file performance
# ---------------------------------------------------------------------------


class TestSingleFileParse:
    """Single file parse + validate < 100ms (NFR-04)."""

    def test_golden_fixture_parse_speed(self) -> None:
        """The golden fixture parses and validates in under 100ms."""
        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        assert source_path.exists(), f"Golden fixture not found: {source_path}"

        # Warm up (first run may be slower due to lazy imports)
        _parse_single(source_path)

        # Timed run
        start = time.perf_counter()
        module, errors = _parse_single(source_path)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert module is not None, "Golden fixture failed to parse"
        assert elapsed_ms < _budget(100), (
            f"Parse + validate took {elapsed_ms:.1f}ms (target: < {_budget(100):g}ms)"
        )

    def test_parse_speed_averaged(self) -> None:
        """Average of 5 parse+validate runs is under 100ms."""
        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        assert source_path.exists()

        # Warm up
        _parse_single(source_path)

        times = []
        for _ in range(5):
            start = time.perf_counter()
            _parse_single(source_path)
            times.append((time.perf_counter() - start) * 1000)

        avg_ms = sum(times) / len(times)
        assert avg_ms < _budget(100), (
            f"Avg parse+validate: {avg_ms:.1f}ms (target: < {_budget(100):g}ms)"
        )


class TestSingleFileTranspile:
    """Single file transpile (all outputs) < 500ms (NFR-04)."""

    def test_golden_fixture_transpile_speed(self, tmp_path: Path) -> None:
        """The golden fixture transpiles in under 500ms."""
        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Warm up
        _transpile_single(source_path, output_dir)

        # Clean for timed run
        for f in output_dir.iterdir():
            f.unlink()

        start = time.perf_counter()
        errors, outputs = _transpile_single(source_path, output_dir)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < _budget(500), (
            f"Transpile took {elapsed_ms:.1f}ms (target: < {_budget(500):g}ms)"
        )
        assert len(outputs) == 3, (
            f"Expected 3 outputs (.py, .s0ma.json, .s0ma.map), got {len(outputs)}"
        )

    def test_transpile_speed_averaged(self, tmp_path: Path) -> None:
        """Average of 5 transpile runs is under 500ms."""
        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Warm up
        _transpile_single(source_path, output_dir)

        times = []
        for _i in range(5):
            # Clean output
            for f in output_dir.iterdir():
                f.unlink()
            start = time.perf_counter()
            _transpile_single(source_path, output_dir)
            times.append((time.perf_counter() - start) * 1000)

        avg_ms = sum(times) / len(times)
        assert avg_ms < _budget(500), (
            f"Avg transpile: {avg_ms:.1f}ms (target: < {_budget(500):g}ms)"
        )


# ---------------------------------------------------------------------------
# Project build performance
# ---------------------------------------------------------------------------


class TestProjectBuild:
    """50-module project build < 30s (NFR-04)."""

    def test_stress_project_build_speed(self, tmp_path: Path) -> None:
        """A 55-module project builds in under 30 seconds."""
        s0ma_files = _generate_stress_project(tmp_path, num_modules=55)
        output_dir = tmp_path / "build_output"
        output_dir.mkdir()

        start = time.perf_counter()
        total_errors = 0
        total_outputs = 0
        for source_path in s0ma_files:
            errors, outputs = _transpile_single(source_path, output_dir)
            total_errors += len([e for e in errors if e.severity == "error"])
            total_outputs += len(outputs)
        elapsed_s = time.perf_counter() - start

        assert elapsed_s < _budget(30), (
            f"55-module build took {elapsed_s:.1f}s (target: < {_budget(30):g}s)"
        )
        # Expect outputs for each file (some may fail due to synthetic deps,
        # but at least the ones without cross-module deps should succeed)
        assert total_outputs > 0, "No outputs produced"

    def test_build_per_file_timing(self, tmp_path: Path) -> None:
        """Individual file transpile times are reasonable."""
        s0ma_files = _generate_stress_project(tmp_path, num_modules=20)
        output_dir = tmp_path / "build_output"
        output_dir.mkdir()

        # Warm up
        _transpile_single(s0ma_files[0], output_dir)

        file_times: list[float] = []
        for source_path in s0ma_files:
            start = time.perf_counter()
            _transpile_single(source_path, output_dir)
            file_times.append((time.perf_counter() - start) * 1000)

        avg_ms = sum(file_times) / len(file_times)
        max_ms = max(file_times)
        assert avg_ms < _budget(500), (
            f"Avg per-file transpile: {avg_ms:.1f}ms (target: < {_budget(500):g}ms)"
        )
        assert max_ms < _budget(2000), (
            f"Max per-file transpile: {max_ms:.1f}ms (target: < {_budget(2000):g}ms)"
        )


# ---------------------------------------------------------------------------
# Memory usage
# ---------------------------------------------------------------------------


class TestMemoryUsage:
    """Memory usage < 500MB for 100-module project (NFR-04)."""

    def test_stress_project_memory(self, tmp_path: Path) -> None:
        """Memory usage stays under 500MB for a large project build."""
        s0ma_files = _generate_stress_project(tmp_path, num_modules=55)
        output_dir = tmp_path / "build_output"
        output_dir.mkdir()

        tracemalloc.start()
        for source_path in s0ma_files:
            _transpile_single(source_path, output_dir)
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak_bytes / (1024 * 1024)
        assert peak_mb < _budget(500), (
            f"Peak memory: {peak_mb:.1f}MB (target: < {_budget(500):g}MB)"
        )


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestBuildCache:
    """Content-hash-based caching per PRD §2.7.5."""

    def test_cache_miss_on_first_run(self, tmp_path: Path) -> None:
        """First lookup is always a miss."""
        cache = BuildCache(cache_dir=tmp_path / "cache")
        source = tmp_path / "test.s0ma"
        source.write_text("module test\n    layer: DOMAIN\n    version: 1.0.0\n"
                          '    intent: "test"\n    exports: []\n', encoding="utf-8")

        result = cache.lookup(source)
        assert not result.hit
        assert cache.misses == 1
        assert cache.hits == 0

    def test_cache_hit_after_store(self, tmp_path: Path) -> None:
        """After storing, lookup returns a hit."""
        cache = BuildCache(cache_dir=tmp_path / "cache")
        source = tmp_path / "test.s0ma"
        source.write_text("module test\n    layer: DOMAIN\n    version: 1.0.0\n"
                          '    intent: "test"\n    exports: []\n', encoding="utf-8")

        cache.store(source, py_content="# generated\n", ir_content='{"schema": "1.0"}\n')

        result = cache.lookup(source)
        assert result.hit
        assert result.cached_py is not None
        assert result.cached_ir is not None
        assert cache.hits == 1

    def test_cache_invalidation_on_change(self, tmp_path: Path) -> None:
        """Modifying source invalidates the cache."""
        cache = BuildCache(cache_dir=tmp_path / "cache")
        source = tmp_path / "test.s0ma"
        source.write_text("module test\n    layer: DOMAIN\n    version: 1.0.0\n"
                          '    intent: "test"\n    exports: []\n', encoding="utf-8")

        cache.store(source, py_content="# original\n")
        assert cache.lookup(source).hit

        # Modify source
        source.write_text("module test\n    layer: DOMAIN\n    version: 2.0.0\n"
                          '    intent: "test updated"\n    exports: []\n', encoding="utf-8")

        result = cache.lookup(source)
        assert not result.hit, "Cache should miss after source modification"

    def test_a_hit_needs_the_published_copies_to_be_the_cached_ones(
        self, tmp_path: Path
    ) -> None:
        """With ``published_dir``, the build directory must still hold what
        the build wrote — edited, deleted or replaced files are a miss."""
        cache = BuildCache(cache_dir=tmp_path / "cache")
        source = tmp_path / "test.s0ma"
        source.write_text("module test\n    layer: DOMAIN\n    version: 1.0.0\n"
                          '    intent: "test"\n    exports: []\n', encoding="utf-8")
        cache.store(source, py_content="# gen\n", ir_content="{}\n", map_content="{}\n")
        published = tmp_path / "build"
        published.mkdir()
        for name, body in (
            ("test.py", "# gen\n"),
            ("test.s0ma.json", "{}\n"),
            ("test.s0ma.map", "{}\n"),
        ):
            (published / name).write_text(body, encoding="utf-8", newline="\n")

        assert cache.lookup(source, published_dir=published).hit

        (published / "test.py").write_text(
            "# gen\n# hand edit\n", encoding="utf-8", newline="\n"
        )
        assert not cache.lookup(source, published_dir=published).hit

        (published / "test.py").write_text("# gen\n", encoding="utf-8", newline="\n")
        (published / "test.s0ma.map").unlink()
        assert not cache.lookup(source, published_dir=published).hit

        assert (cache.hits, cache.misses) == (1, 2)
        # Without ``published_dir`` the lookup answers for the cache alone.
        assert cache.lookup(source).hit

    def test_cache_explicit_invalidate(self, tmp_path: Path) -> None:
        """Explicit invalidation removes cached files."""
        cache = BuildCache(cache_dir=tmp_path / "cache")
        source = tmp_path / "test.s0ma"
        source.write_text("module test\n    layer: DOMAIN\n    version: 1.0.0\n"
                          '    intent: "test"\n    exports: []\n', encoding="utf-8")

        cache.store(source, py_content="# gen\n", ir_content="{}\n", map_content="{}\n")
        assert cache.lookup(source).hit

        cache.invalidate(source)
        assert not cache.lookup(source).hit

    def test_cache_clear(self, tmp_path: Path) -> None:
        """Clear removes all cached artifacts."""
        cache = BuildCache(cache_dir=tmp_path / "cache")
        source = tmp_path / "test.s0ma"
        source.write_text("module test\n    layer: DOMAIN\n    version: 1.0.0\n"
                          '    intent: "test"\n    exports: []\n', encoding="utf-8")

        cache.store(source, py_content="# gen\n")
        assert cache.lookup(source).hit

        cache.clear()
        assert not (tmp_path / "cache").exists()

    def test_cache_stats(self, tmp_path: Path) -> None:
        """Hit/miss counters work correctly."""
        cache = BuildCache(cache_dir=tmp_path / "cache")
        source = tmp_path / "test.s0ma"
        source.write_text("content\n", encoding="utf-8")

        cache.lookup(source)  # miss
        cache.store(source, py_content="# gen\n")
        cache.lookup(source)  # hit
        cache.lookup(source)  # hit

        assert cache.hits == 2
        assert cache.misses == 1

        cache.reset_stats()
        assert cache.hits == 0
        assert cache.misses == 0

    def test_cache_misses_under_another_transpiler_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An entry another s0ma-dsl version wrote is never replayed.

        The key used to be the source text alone, so after an upgrade every
        unchanged module came back exactly as the old emitter wrote it
        (codebase review BLD-3).
        """
        cache = BuildCache(cache_dir=tmp_path / "cache")
        source = tmp_path / "test.s0ma"
        source.write_text("content\n", encoding="utf-8")
        cache.store(source, py_content="# gen\n")
        assert cache.lookup(source).hit

        monkeypatch.setattr(s0ma_dsl.cache, "__version__", "0.0.0+another")
        assert not cache.lookup(source).hit

    def test_entry_keyed_on_the_bare_source_hash_misses(self, tmp_path: Path) -> None:
        """What every release before the version was keyed wrote is a miss."""
        cache = BuildCache(cache_dir=tmp_path / "cache")
        source = tmp_path / "test.s0ma"
        source.write_text("content\n", encoding="utf-8")
        cache.store(source, py_content="# gen\n")
        (hash_file,) = (tmp_path / "cache").glob("*.hash")
        hash_file.write_text(
            hashlib.sha256(source.read_bytes()).hexdigest() + "\n", encoding="utf-8"
        )
        assert not cache.lookup(source).hit


class TestCacheIntegration:
    """Cache integration with the transpile pipeline."""

    def test_cached_retranspile_speed(self, tmp_path: Path) -> None:
        """Retranspile with cache hit takes < 1s (NFR-04)."""
        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        cache = BuildCache(cache_dir=tmp_path / "cache")

        from s0ma_dsl.cli.main import _transpile_single_file

        # First transpile (populates cache)
        _transpile_single_file(
            source_path, mode=StrictnessMode.DEV, output_dir=output_dir,
            cache=cache,
        )
        assert cache.misses == 1

        # Second transpile (cache hit — should be fast)
        start = time.perf_counter()
        errors, outputs = _transpile_single_file(
            source_path, mode=StrictnessMode.DEV, output_dir=output_dir,
            cache=cache,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert cache.hits == 1
        assert elapsed_ms < _budget(1000), (
            f"Cached retranspile: {elapsed_ms:.1f}ms (target: < {_budget(1000):g}ms)"
        )
        assert len(errors) == 0
        assert len(outputs) > 0

    def test_cache_miss_on_modified_file(self, tmp_path: Path) -> None:
        """Modified source triggers full retranspile through cache."""
        from s0ma_dsl.cli.main import _transpile_single_file

        # Create a copy of the golden fixture
        source = tmp_path / "signal_processor.s0ma"
        original = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        cache = BuildCache(cache_dir=tmp_path / "cache")

        # First transpile
        _transpile_single_file(source, mode=StrictnessMode.DEV,
                               output_dir=output_dir, cache=cache)
        assert cache.misses == 1

        # Modify source (change version)
        text = source.read_text(encoding="utf-8")
        text = text.replace("version: 1.0.0", "version: 1.1.0")
        source.write_text(text, encoding="utf-8")

        # Second transpile — should be a miss
        _transpile_single_file(source, mode=StrictnessMode.DEV,
                               output_dir=output_dir, cache=cache)
        assert cache.misses == 2
        assert cache.hits == 0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Repeated runs produce byte-for-byte identical output (NFR-01, P6).

    Comparisons are RAW bytes, deliberately without path normalisation
    (WIN-M3): the IR's ``transpiled_file`` and the map's ``output_file``
    are directory-independent basenames, and ``source_file`` is constant
    across runs of the same source, so artifacts must be byte-identical
    even across different output directories, on every OS. The old
    replace-based normalisation masked embedded absolute paths on POSIX
    while silently no-opping on Windows (JSON escapes backslashes, so a
    native-form needle never matched) — do not reintroduce it.
    """

    def test_python_output_deterministic(self, tmp_path: Path) -> None:
        """Two transpile runs produce identical .py output."""
        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        dir_a = tmp_path / "run_a"
        dir_b = tmp_path / "run_b"
        dir_a.mkdir()
        dir_b.mkdir()

        _transpile_single(source_path, dir_a)
        _transpile_single(source_path, dir_b)

        py_a = (dir_a / "signal_processor.py").read_text(encoding="utf-8")
        py_b = (dir_b / "signal_processor.py").read_text(encoding="utf-8")
        assert py_a == py_b, "Python output differs between runs"

    def test_ir_output_deterministic(self, tmp_path: Path) -> None:
        """Two transpile runs produce identical .s0ma.json output (modulo paths)."""
        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        dir_a = tmp_path / "run_a"
        dir_b = tmp_path / "run_b"
        dir_a.mkdir()
        dir_b.mkdir()

        _transpile_single(source_path, dir_a)
        _transpile_single(source_path, dir_b)

        ir_a = (dir_a / "signal_processor.s0ma.json").read_text(encoding="utf-8")
        ir_b = (dir_b / "signal_processor.s0ma.json").read_text(encoding="utf-8")
        assert_artifacts_identical(
            "signal_processor.s0ma.json (run a vs run b)", ir_a, ir_b,
        )

    def test_source_map_deterministic(self, tmp_path: Path) -> None:
        """Two transpile runs produce identical .s0ma.map output (modulo paths)."""
        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        dir_a = tmp_path / "run_a"
        dir_b = tmp_path / "run_b"
        dir_a.mkdir()
        dir_b.mkdir()

        _transpile_single(source_path, dir_a)
        _transpile_single(source_path, dir_b)

        map_a = (dir_a / "signal_processor.s0ma.map").read_text(encoding="utf-8")
        map_b = (dir_b / "signal_processor.s0ma.map").read_text(encoding="utf-8")
        assert_artifacts_identical(
            "signal_processor.s0ma.map (run a vs run b)", map_a, map_b,
        )

    def test_triple_run_all_artifacts(self, tmp_path: Path) -> None:
        """Three consecutive runs produce identical output across all artifacts."""
        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        dirs = []
        for i in range(3):
            d = tmp_path / f"run_{i}"
            d.mkdir()
            _transpile_single(source_path, d)
            dirs.append(d)

        suffixes = [".py", ".s0ma.json", ".s0ma.map"]
        for suffix in suffixes:
            contents = []
            for d in dirs:
                fname = f"signal_processor{suffix}"
                f = d / fname
                assert f.exists(), f"Missing {f}"
                contents.append(f.read_text(encoding="utf-8"))

            for i in range(1, len(contents)):
                assert_artifacts_identical(
                    f"signal_processor{suffix} (run 0 vs run {i})",
                    contents[0], contents[i],
                )

    def test_stress_project_determinism(self, tmp_path: Path) -> None:
        """Two builds of the stress project produce identical output."""
        s0ma_files = _generate_stress_project(tmp_path, num_modules=10)

        dir_a = tmp_path / "run_a"
        dir_b = tmp_path / "run_b"
        dir_a.mkdir()
        dir_b.mkdir()

        for source_path in s0ma_files:
            _transpile_single(source_path, dir_a)
            _transpile_single(source_path, dir_b)

        # Compare all generated files (raw bytes — see class docstring)
        files_a = sorted(dir_a.iterdir())
        files_b = sorted(dir_b.iterdir())

        assert len(files_a) == len(files_b), (
            f"Different number of output files: {len(files_a)} vs {len(files_b)}"
        )

        for fa, fb in zip(files_a, files_b, strict=False):
            assert fa.name == fb.name, f"File name mismatch: {fa.name} vs {fb.name}"
            assert_artifacts_identical(
                f"{fa.name} (run a vs run b)",
                fa.read_text(encoding="utf-8"),
                fb.read_text(encoding="utf-8"),
            )

    def test_ir_content_hash_deterministic(self, tmp_path: Path) -> None:
        """The content_hash in .s0ma.json is identical across runs."""
        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        dir_a = tmp_path / "run_a"
        dir_b = tmp_path / "run_b"
        dir_a.mkdir()
        dir_b.mkdir()

        _transpile_single(source_path, dir_a)
        _transpile_single(source_path, dir_b)

        ir_a = json.loads((dir_a / "signal_processor.s0ma.json").read_text(encoding="utf-8"))
        ir_b = json.loads((dir_b / "signal_processor.s0ma.json").read_text(encoding="utf-8"))

        assert ir_a["module"]["content_hash"] == ir_b["module"]["content_hash"]

    def test_diagnostics_order_deterministic(self, tmp_path: Path) -> None:
        """Diagnostics ordering is consistent across runs."""
        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"

        diags_a = _parse_single(source_path)[1]
        diags_b = _parse_single(source_path)[1]

        codes_a = [getattr(d, "code", "") for d in diags_a]
        codes_b = [getattr(d, "code", "") for d in diags_b]
        assert codes_a == codes_b, "Diagnostic ordering differs between runs"


# ---------------------------------------------------------------------------
# Profiling helpers (not assertions, just timing data)
# ---------------------------------------------------------------------------


class TestPipelineProfiling:
    """Profile individual pipeline stages to identify bottlenecks.

    These tests don't assert hard limits — they report stage-level timing
    for diagnostic purposes. Actual performance assertions are in the
    classes above.
    """

    def test_profile_pipeline_stages(self, tmp_path: Path) -> None:
        """Profile each stage of the transpile pipeline independently."""
        from s0ma_dsl.codegen.python_emitter import PythonEmitter
        from s0ma_dsl.codegen.source_map import SourceMapGenerator
        from s0ma_dsl.ir.builder import IRBuilder
        from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
        from s0ma_dsl.semantic.derived_edges import analyze_derived_edges
        from s0ma_dsl.semantic.validator import validate_module

        source_path = VALID_FIXTURES_DIR / "signal_processor.s0ma"
        source_text = source_path.read_text(encoding="utf-8")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Warm up all imports
        parse_s0ma_with_warnings(source_text, str(source_path), StrictnessMode.DEV)

        timings: dict[str, float] = {}

        # Stage 1-2: Parse
        start = time.perf_counter()
        module, warnings = parse_s0ma_with_warnings(
            source_text, str(source_path), StrictnessMode.DEV,
        )
        timings["parse"] = (time.perf_counter() - start) * 1000

        # Stage 3: Semantic validation
        start = time.perf_counter()
        validate_module(module, mode=StrictnessMode.DEV, filename=str(source_path))
        timings["validate"] = (time.perf_counter() - start) * 1000

        # Stage 4: Derived edges
        start = time.perf_counter()
        derived, edge_errors = analyze_derived_edges(
            module, mode=StrictnessMode.DEV, filename=str(source_path),
        )
        timings["derived_edges"] = (time.perf_counter() - start) * 1000

        # Stage 5a: Python emission
        start = time.perf_counter()
        emitter = PythonEmitter(mode=StrictnessMode.DEV, filename=str(source_path))
        python_output = emitter.emit(module)
        timings["emit_python"] = (time.perf_counter() - start) * 1000

        # Stage 5b: IR generation
        start = time.perf_counter()
        ir_builder = IRBuilder(
            source_file=str(source_path),
            source_text=source_text,
            transpiled_file=str(output_dir / "signal_processor.py"),
        )
        ir_builder.to_json(module, derived_edges=list(derived))
        timings["emit_ir"] = (time.perf_counter() - start) * 1000

        # Stage 5c: Source map
        start = time.perf_counter()
        gen = SourceMapGenerator()
        smap = gen.generate(
            module, python_output,
            source_file=str(source_path),
            output_file=str(output_dir / "signal_processor.py"),
        )
        smap.to_json()
        timings["emit_source_map"] = (time.perf_counter() - start) * 1000

        total = sum(timings.values())
        timings["total"] = total

        # Report
        print("\n--- Pipeline Stage Profiling ---")
        for stage, ms in timings.items():
            pct = (ms / total * 100) if total > 0 else 0
            print(f"  {stage:20s}: {ms:7.2f}ms  ({pct:5.1f}%)")

        # Basic sanity: total should be under 500ms
        assert total < _budget(500), (
            f"Total pipeline: {total:.1f}ms (target: < {_budget(500):g}ms)"
        )

    def test_profile_stress_build(self, tmp_path: Path) -> None:
        """Profile a stress project build with per-file timing."""
        s0ma_files = _generate_stress_project(tmp_path, num_modules=20)
        output_dir = tmp_path / "build_output"
        output_dir.mkdir()

        file_times: list[tuple[str, float]] = []
        total_start = time.perf_counter()

        for source_path in s0ma_files:
            start = time.perf_counter()
            errors, outputs = _transpile_single(source_path, output_dir)
            elapsed_ms = (time.perf_counter() - start) * 1000
            file_times.append((source_path.name, elapsed_ms))

        total_s = time.perf_counter() - total_start

        # Report
        print(f"\n--- Stress Build Profile ({len(s0ma_files)} modules) ---")
        print(f"  Total: {total_s:.2f}s")
        slowest = sorted(file_times, key=lambda x: x[1], reverse=True)[:5]
        print("  Slowest 5 files:")
        for name, ms in slowest:
            print(f"    {name}: {ms:.1f}ms")

        avg_ms = sum(t for _, t in file_times) / len(file_times)
        print(f"  Average per file: {avg_ms:.1f}ms")


# ---------------------------------------------------------------------------
# D-7 (Windows plan M2): the S0MA_TEST_PERF_SCALE knob itself.
# ---------------------------------------------------------------------------


class TestPerfScaleKnob:
    """The scale knob multiplies hard budgets; default stays strict."""

    def test_budget_scales_linearly(self, monkeypatch) -> None:
        import sys as _sys

        monkeypatch.setattr(_sys.modules[__name__], "_PERF_SCALE", 4.0)
        assert _budget(500) == 2000.0

    def test_budget_identity_at_default_scale(self, monkeypatch) -> None:
        import sys as _sys

        monkeypatch.setattr(_sys.modules[__name__], "_PERF_SCALE", 1.0)
        assert _budget(123.0) == 123.0

    def test_knob_default_parses_to_strict(self, monkeypatch) -> None:
        """An unset env var means scale 1.0 (the strict local default)."""
        monkeypatch.delenv("S0MA_TEST_PERF_SCALE", raising=False)
        assert float(os.environ.get("S0MA_TEST_PERF_SCALE", "1.0")) == 1.0
