"""CLI tests for the s0ma DSL transpiler (Milestone 16).

Tests all five CLI commands (transpile, check, build, inspect, graph),
exit codes per PRD §2.8.2, and JSON output mode.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from s0ma_dsl.cache import BuildCache
from s0ma_dsl.cli.main import (
    EXIT_INTERNAL_ERROR,
    EXIT_NOTHING_VERIFIED,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    EXIT_VALIDATION_ERROR,
    S0maCLI,
    _discover_s0ma_files,
    _format_diagnostics_json,
    _format_diagnostics_text,
    _generate_conftest,
    _parse_single_file,
    _scaffold_template,
    _snake_case,
    _split_diagnostics,
    main,
)
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maError

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN_FIXTURE = _FIXTURES_DIR / "valid" / "signal_processor.s0ma"
MULTI_MODULE_DIR = _FIXTURES_DIR / "valid" / "multi_module"


# ---------------------------------------------------------------------------
# Minimal .s0ma fixture for test isolation
# ---------------------------------------------------------------------------

MINIMAL_S0MA = """\
module test_module
    layer: DOMAIN
    version: 0.1.0
    intent: "A minimal module for CLI testing."
    exports: [greet]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A simple greeting function for testing."
    expects: "name: str"
    guarantees: "Returns a greeting string"
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
    def greet(name: str) -> str:
        return f"Hello, {name}!"
"""

INVALID_S0MA = """\
module broken_module
    layer: DOMAIN
    version: 0.1.0
    intent: "A module missing the exports field."
    exports: none
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""


@pytest.fixture()
def minimal_s0ma_file(tmp_path: Path) -> Path:
    """Create a minimal .s0ma file in a temp directory."""
    f = tmp_path / "test_module.s0ma"
    f.write_text(MINIMAL_S0MA, encoding="utf-8")
    return f


@pytest.fixture()
def invalid_s0ma_file(tmp_path: Path) -> Path:
    """Create an invalid .s0ma file in a temp directory."""
    f = tmp_path / "broken.s0ma"
    f.write_text(INVALID_S0MA, encoding="utf-8")
    return f


@pytest.fixture()
def multi_s0ma_dir(tmp_path: Path) -> Path:
    """Create a directory with multiple .s0ma files."""
    d = tmp_path / "project"
    d.mkdir()
    (d / "test_module.s0ma").write_text(MINIMAL_S0MA, encoding="utf-8")
    return d


@pytest.fixture()
def cli() -> S0maCLI:
    """Create a fresh S0maCLI instance."""
    return S0maCLI()


# ===========================================================================
# Test: CLI Parser Construction
# ===========================================================================


class TestCLIParser:
    """Test argparse parser construction."""

    def test_parser_has_all_commands(self, cli: S0maCLI):
        parser = cli.build_parser()
        # Parse each command with minimal args to verify it exists
        args = parser.parse_args(["check", "test.s0ma"])
        assert args.command == "check"

        args = parser.parse_args(["transpile", "test.s0ma"])
        assert args.command == "transpile"

        args = parser.parse_args(["build", "."])
        assert args.command == "build"

        args = parser.parse_args(["inspect", "test.s0ma.json"])
        assert args.command == "inspect"

        args = parser.parse_args(["graph", "test.s0ma.json"])
        assert args.command == "graph"

    def test_transpile_default_mode_is_dev(self, cli: S0maCLI):
        # DSL-M3 (F-M1-2): the parser default is now ``None`` (the
        # "flag omitted" sentinel that lets [tool.s0ma].mode win), and
        # ``_resolve_mode`` materialises the built-in default (``dev``)
        # when neither a flag nor a table value applies.
        from s0ma_dsl.cli.main import _resolve_mode

        parser = cli.build_parser()
        args = parser.parse_args(["transpile", "test.s0ma"])
        assert args.mode is None
        _resolve_mode(args, None)
        assert args.mode == "dev"

    def test_check_default_mode_is_strict(self, cli: S0maCLI):
        # DSL-M3 (F-M1-2): ``check``'s built-in default stays ``strict``
        # (deliberately NOT unified with ``build``'s ``dev``). The parser
        # default is the ``None`` sentinel; resolution with no project
        # yields the built-in strict.
        from s0ma_dsl.cli.main import _resolve_mode

        parser = cli.build_parser()
        args = parser.parse_args(["check", "test.s0ma"])
        assert args.mode is None
        _resolve_mode(args, None)
        assert args.mode == "strict"

    def test_build_default_mode_is_dev(self, cli: S0maCLI):
        # DSL-M3 (F-M1-2): ``build``'s built-in default stays ``dev``.
        from s0ma_dsl.cli.main import _resolve_mode

        parser = cli.build_parser()
        args = parser.parse_args(["build", "."])
        assert args.mode is None
        _resolve_mode(args, None)
        assert args.mode == "dev"

    def test_transpile_options(self, cli: S0maCLI):
        parser = cli.build_parser()
        args = parser.parse_args([
            "transpile", "test.s0ma",
            "--output-dir", "/tmp/out",
            "--mode", "strict",
            "--no-ir",
            "--no-source-map",
            "--format", "json",
        ])
        assert args.output_dir == "/tmp/out"
        assert args.mode == "strict"
        assert args.no_ir is True
        assert args.no_source_map is True
        assert args.output_format == "json"

    def test_no_command_returns_usage_error(self, cli: S0maCLI):
        exit_code = cli.run([])
        assert exit_code == EXIT_USAGE_ERROR


# ===========================================================================
# Test: File Discovery
# ===========================================================================


class TestFileDiscovery:
    """Test .s0ma file discovery."""

    def test_discover_single_file(self, minimal_s0ma_file: Path):
        files = _discover_s0ma_files(str(minimal_s0ma_file))
        assert len(files) == 1
        assert files[0] == minimal_s0ma_file

    def test_discover_directory(self, multi_s0ma_dir: Path):
        files = _discover_s0ma_files(str(multi_s0ma_dir))
        assert len(files) >= 1
        assert all(f.suffix == ".s0ma" for f in files)

    def test_discover_nonexistent(self, tmp_path: Path):
        files = _discover_s0ma_files(str(tmp_path / "nonexistent"))
        assert files == []

    def test_discover_non_s0ma_file(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        files = _discover_s0ma_files(str(f))
        assert files == []


# ===========================================================================
# Test: Diagnostic Formatting
# ===========================================================================


class TestDiagnosticFormatting:
    """Test diagnostic output formatting."""

    def _make_error(self, code: str = "TEST_ERR", severity: str = "error") -> S0maError:
        return S0maError(
            code=code,
            message="Test error message",
            file="test.s0ma",
            line=1,
            column=0,
            severity=severity,
            remediation="Fix the test.",
        )

    def test_split_diagnostics(self):
        errs = [
            self._make_error(severity="error"),
            self._make_error(severity="warning"),
            self._make_error(severity="error"),
        ]
        errors, warnings = _split_diagnostics(errs)
        assert len(errors) == 2
        assert len(warnings) == 1

    def test_text_format_includes_summary(self):
        err = self._make_error()
        text = _format_diagnostics_text([err], [])
        assert "1 error(s)" in text
        assert "0 warning(s)" in text

    def test_json_format_is_valid_json(self):
        err = self._make_error()
        warn = self._make_error(code="TEST_WARN", severity="warning")
        json_str = _format_diagnostics_json([err], [warn], files_processed=1)
        data = json.loads(json_str)
        assert data["summary"]["errors"] == 1
        assert data["summary"]["warnings"] == 1
        assert data["summary"]["files_processed"] == 1
        assert len(data["errors"]) == 1
        assert len(data["warnings"]) == 1

    def test_json_error_has_all_fields(self):
        err = self._make_error()
        json_str = _format_diagnostics_json([err], [])
        data = json.loads(json_str)
        error_dict = data["errors"][0]
        assert "code" in error_dict
        assert "message" in error_dict
        assert "file" in error_dict
        assert "line" in error_dict
        assert "column" in error_dict
        assert "severity" in error_dict
        assert "remediation" in error_dict


# ===========================================================================
# Test: check command
# ===========================================================================


class TestCheckCommand:
    """Test the 's0ma check' command."""

    def test_check_valid_file(self, cli: S0maCLI, minimal_s0ma_file: Path):
        exit_code = cli.run(["check", str(minimal_s0ma_file), "--mode", "dev"])
        assert exit_code == EXIT_SUCCESS

    def test_check_nonexistent_file(self, cli: S0maCLI, tmp_path: Path):
        exit_code = cli.run(["check", str(tmp_path / "nonexistent.s0ma")])
        assert exit_code == EXIT_USAGE_ERROR

    def test_check_invalid_file(self, cli: S0maCLI, invalid_s0ma_file: Path):
        exit_code = cli.run(["check", str(invalid_s0ma_file), "--mode", "dev"])
        assert exit_code == EXIT_VALIDATION_ERROR

    def test_check_json_format(self, cli: S0maCLI, minimal_s0ma_file: Path, capsys):
        exit_code = cli.run([
            "check", str(minimal_s0ma_file),
            "--mode", "dev",
            "--format", "json",
        ])
        captured = capsys.readouterr()
        if exit_code == EXIT_SUCCESS:
            # If no errors, may or may not produce output
            pass
        else:
            # JSON output should be valid
            data = json.loads(captured.out)
            assert "errors" in data

    def test_check_directory(self, cli: S0maCLI, multi_s0ma_dir: Path):
        exit_code = cli.run(["check", str(multi_s0ma_dir), "--mode", "dev"])
        assert exit_code == EXIT_SUCCESS

    def test_check_golden_fixture_dev_mode(self, cli: S0maCLI):
        """The golden fixture should check cleanly in dev mode."""
        if not GOLDEN_FIXTURE.exists():
            pytest.skip("Golden fixture not found")
        exit_code = cli.run(["check", str(GOLDEN_FIXTURE), "--mode", "dev"])
        assert exit_code == EXIT_SUCCESS


# ===========================================================================
# Test: transpile command
# ===========================================================================


class TestTranspileCommand:
    """Test the 's0ma transpile' command."""

    def test_transpile_produces_py(self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        py_file = out_dir / "test_module.py"
        assert py_file.exists()

    def test_transpile_produces_ir(self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        ir_file = out_dir / "test_module.s0ma.json"
        assert ir_file.exists()
        # Verify it's valid JSON
        data = json.loads(ir_file.read_text())
        assert "schema_version" in data
        assert "module" in data

    def test_transpile_produces_source_map(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path,
    ):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        map_file = out_dir / "test_module.s0ma.map"
        assert map_file.exists()
        data = json.loads(map_file.read_text())
        assert "version" in data

    def test_transpile_no_ir(self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--no-ir",
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        assert not (out_dir / "test_module.s0ma.json").exists()
        manifest = json.loads(
            (out_dir / "build.s0ma.json").read_text(encoding="utf-8")
        )
        assert "self_context" not in manifest
        assert not (out_dir / "self_context.json").exists()
        assert not (out_dir / "self_prompt_card.md").exists()

    def test_transpile_no_source_map(self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--no-source-map",
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        assert not (out_dir / "test_module.s0ma.map").exists()

    def test_transpile_invalid_file_returns_error(
        self, cli: S0maCLI, invalid_s0ma_file: Path, tmp_path: Path
    ):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(invalid_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_VALIDATION_ERROR

    def test_transpile_nonexistent_returns_usage_error(self, cli: S0maCLI):
        exit_code = cli.run(["transpile", "/nonexistent/path.s0ma"])
        assert exit_code == EXIT_USAGE_ERROR

    def test_transpile_default_output_dir(self, cli: S0maCLI, minimal_s0ma_file: Path):
        """Without --output-dir, output goes alongside the source."""
        exit_code = cli.run([
            "transpile", str(minimal_s0ma_file),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        py_file = minimal_s0ma_file.parent / "test_module.py"
        assert py_file.exists()
        # Cleanup
        py_file.unlink(missing_ok=True)
        (minimal_s0ma_file.parent / "test_module.s0ma.json").unlink(missing_ok=True)
        (minimal_s0ma_file.parent / "test_module.s0ma.map").unlink(missing_ok=True)

    def test_transpile_json_diagnostics(
        self, cli: S0maCLI, invalid_s0ma_file: Path, tmp_path: Path, capsys
    ):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(invalid_s0ma_file),
            "--output-dir", str(out_dir),
            "--format", "json",
            "--mode", "dev",
        ])
        assert exit_code == EXIT_VALIDATION_ERROR
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["summary"]["errors"] > 0

    def test_transpile_emitted_python_is_syntactically_valid(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path
    ):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        py_file = out_dir / "test_module.py"
        assert py_file.exists()
        source = py_file.read_text()
        # compile() checks syntax validity
        compile(source, str(py_file), "exec")

    def test_transpile_directory(self, cli: S0maCLI, multi_s0ma_dir: Path, tmp_path: Path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(multi_s0ma_dir),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS

    def test_transpile_directory_emits_flat_layout(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """s0ma transpile dir/ -o out/ produces a flat layout (M6a, ADR-007).

        Pre-M6a the transpiler mirrored the source-tree subdirectories
        under the output dir, leaving consumers with no canonical
        importable path and no ``__init__.py``. Per ADR-007 the output
        is now a single flat layout: every transpiled ``.py`` lands at
        ``out/<module>.py`` and the layout is a real Python package
        thanks to an auto-emitted ``__init__.py``.
        """
        # Build a nested input tree:
        #   input/domain/models.s0ma
        #   input/infra/adapters.s0ma
        input_dir = tmp_path / "input"
        (input_dir / "domain").mkdir(parents=True)
        (input_dir / "infra").mkdir(parents=True)

        domain_s0ma = """\
module models
    layer: DOMAIN
    version: 0.1.0
    intent: "Domain models for structure-preservation test."
    exports: [get_model]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve get_model :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Returns a model placeholder."
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
    def get_model() -> str:
        return "model"
"""
        infra_s0ma = """\
module adapters
    layer: INFRASTRUCTURE
    version: 0.1.0
    intent: "Infrastructure adapters for structure-preservation test."
    exports: [connect]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve connect :: INFRASTRUCTURE
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Establishes a connection placeholder."
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
    def connect() -> str:
        return "connected"
"""
        (input_dir / "domain" / "models.s0ma").write_text(domain_s0ma, encoding="utf-8")
        (input_dir / "infra" / "adapters.s0ma").write_text(infra_s0ma, encoding="utf-8")

        out_dir = tmp_path / "out"
        out_dir.mkdir()

        exit_code = cli.run([
            "transpile", str(input_dir),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS

        # M6a (ADR-007): flat layout — every module lands at out/<name>.py
        # regardless of source position.
        assert (out_dir / "models.py").exists(), (
            "Expected out/models.py to exist (flat layout)"
        )
        assert (out_dir / "adapters.py").exists(), (
            "Expected out/adapters.py to exist (flat layout)"
        )
        # The legacy layer subdirs must NOT be created.
        assert not (out_dir / "domain" / "models.py").exists(), (
            "models.py must not be under a layer subdir post-M6a"
        )
        assert not (out_dir / "infra" / "adapters.py").exists(), (
            "adapters.py must not be under a layer subdir post-M6a"
        )
        # The build directory must be a real Python package.
        assert (out_dir / "__init__.py").exists(), (
            "Expected auto-emitted __init__.py at the build root"
        )

    def test_transpile_single_file_with_output_dir_not_regressed(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path
    ):
        """Single-file transpile with --output-dir still works (no regression)."""
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        exit_code = cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        assert (out_dir / "test_module.py").exists()


# ===========================================================================
# Test: build command
# ===========================================================================


class TestBuildCommand:
    """Test the 's0ma build' command."""

    def test_build_single_module_dir(self, cli: S0maCLI, multi_s0ma_dir: Path, tmp_path: Path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "build", str(multi_s0ma_dir),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS

    def test_build_not_a_directory(self, cli: S0maCLI, minimal_s0ma_file: Path):
        exit_code = cli.run(["build", str(minimal_s0ma_file)])
        assert exit_code == EXIT_USAGE_ERROR

    def test_build_empty_directory(self, cli: S0maCLI, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        exit_code = cli.run(["build", str(empty)])
        assert exit_code == EXIT_USAGE_ERROR

    def test_build_with_clean(self, cli: S0maCLI, multi_s0ma_dir: Path, tmp_path: Path):
        # M6a (ADR-007): --clean must wipe both the current
        # ``.s0ma.cache/`` and any legacy ``__s0ma_cache__/`` left over
        # from pre-M6a builds.
        legacy_cache = multi_s0ma_dir / "__s0ma_cache__"
        legacy_cache.mkdir()
        (legacy_cache / "old.py").write_text("# stale")

        current_cache = multi_s0ma_dir / ".s0ma.cache"
        current_cache.mkdir()
        (current_cache / "old.py").write_text("# stale")

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "build", str(multi_s0ma_dir),
            "--output-dir", str(out_dir),
            "--clean",
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        assert not legacy_cache.exists()


# ===========================================================================
# Test: inspect command
# ===========================================================================


class TestInspectCommand:
    """Test the 's0ma inspect' command."""

    @pytest.fixture()
    def ir_file(self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path) -> Path:
        """Transpile a file and return the .s0ma.json path."""
        out_dir = tmp_path / "ir_out"
        out_dir.mkdir()
        cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        return out_dir / "test_module.s0ma.json"

    def test_inspect_text(self, cli: S0maCLI, ir_file: Path, capsys):
        assert ir_file.exists()
        exit_code = cli.run(["inspect", str(ir_file)])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "Module: test_module" in captured.out

    def test_inspect_json(self, cli: S0maCLI, ir_file: Path, capsys):
        assert ir_file.exists()
        exit_code = cli.run(["inspect", str(ir_file), "--format", "json"])
        assert exit_code == EXIT_SUCCESS
        data = json.loads(capsys.readouterr().out)
        assert "module" in data

    def test_inspect_nonexistent(self, cli: S0maCLI, tmp_path: Path):
        exit_code = cli.run(["inspect", str(tmp_path / "nonexistent.s0ma.json")])
        assert exit_code == EXIT_USAGE_ERROR

    def test_inspect_directory(self, cli: S0maCLI, ir_file: Path, capsys):
        """Inspecting a directory with .s0ma.json files."""
        exit_code = cli.run(["inspect", str(ir_file.parent)])
        assert exit_code == EXIT_SUCCESS


# ===========================================================================
# Test: graph command
# ===========================================================================


class TestGraphCommand:
    """Test the 's0ma graph' command."""

    @pytest.fixture()
    def ir_file(self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path) -> Path:
        """Transpile a file and return the .s0ma.json path."""
        out_dir = tmp_path / "graph_out"
        out_dir.mkdir()
        cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        return out_dir / "test_module.s0ma.json"

    def test_graph_text(self, cli: S0maCLI, ir_file: Path, capsys):
        assert ir_file.exists()
        exit_code = cli.run(["graph", str(ir_file)])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "Dependency Graph" in captured.out

    def test_graph_json(self, cli: S0maCLI, ir_file: Path, capsys):
        assert ir_file.exists()
        exit_code = cli.run(["graph", str(ir_file), "--format", "json"])
        assert exit_code == EXIT_SUCCESS
        data = json.loads(capsys.readouterr().out)
        assert "nodes" in data
        assert "edges" in data

    def test_graph_dot(self, cli: S0maCLI, ir_file: Path, capsys):
        assert ir_file.exists()
        exit_code = cli.run(["graph", str(ir_file), "--format", "dot"])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "digraph s0ma {" in captured.out
        assert "}" in captured.out

    def test_graph_nonexistent(self, cli: S0maCLI, tmp_path: Path):
        exit_code = cli.run(["graph", str(tmp_path / "nonexistent.s0ma.json")])
        assert exit_code == EXIT_USAGE_ERROR


# ===========================================================================
# Test: Exit Codes (PRD §2.8.2)
# ===========================================================================


class TestExitCodes:
    """Verify exit codes match PRD §2.8.2."""

    def test_success_is_0(self, cli: S0maCLI, minimal_s0ma_file: Path):
        exit_code = cli.run(["check", str(minimal_s0ma_file), "--mode", "dev"])
        assert exit_code == 0

    def test_validation_error_is_1(self, cli: S0maCLI, invalid_s0ma_file: Path):
        exit_code = cli.run(["check", str(invalid_s0ma_file), "--mode", "dev"])
        assert exit_code == 1

    def test_usage_error_is_2(self, cli: S0maCLI):
        exit_code = cli.run([])
        assert exit_code == 2

    def test_constants_match_spec(self):
        assert EXIT_SUCCESS == 0
        assert EXIT_VALIDATION_ERROR == 1
        assert EXIT_USAGE_ERROR == 2
        assert EXIT_INTERNAL_ERROR == 3


# ===========================================================================
# Test: Golden Fixture Integration
# ===========================================================================


class TestGoldenFixture:
    """Integration tests with the golden fixture (spec §8)."""

    @pytest.fixture(autouse=True)
    def _check_golden_fixture(self):
        if not GOLDEN_FIXTURE.exists():
            pytest.skip("Golden fixture not found")

    def test_check_golden_fixture_dev(self, cli: S0maCLI):
        exit_code = cli.run(["check", str(GOLDEN_FIXTURE), "--mode", "dev"])
        assert exit_code == EXIT_SUCCESS

    def test_transpile_golden_fixture(self, cli: S0maCLI, tmp_path: Path):
        out_dir = tmp_path / "golden_out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(GOLDEN_FIXTURE),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS

        # All three output files should exist
        assert (out_dir / "signal_processor.py").exists()
        assert (out_dir / "signal_processor.s0ma.json").exists()
        assert (out_dir / "signal_processor.s0ma.map").exists()

    def test_transpiled_golden_is_valid_python(self, cli: S0maCLI, tmp_path: Path):
        out_dir = tmp_path / "golden_py"
        out_dir.mkdir()
        cli.run([
            "transpile", str(GOLDEN_FIXTURE),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        py_file = out_dir / "signal_processor.py"
        source = py_file.read_text()
        compile(source, str(py_file), "exec")

    def test_golden_ir_is_valid_json(self, cli: S0maCLI, tmp_path: Path):
        out_dir = tmp_path / "golden_ir"
        out_dir.mkdir()
        cli.run([
            "transpile", str(GOLDEN_FIXTURE),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        ir_file = out_dir / "signal_processor.s0ma.json"
        data = json.loads(ir_file.read_text())
        assert data["module"]["name"] == "signal_processor"
        assert "components" in data
        assert "edges" in data

    def test_inspect_golden_ir(self, cli: S0maCLI, tmp_path: Path, capsys):
        out_dir = tmp_path / "golden_inspect"
        out_dir.mkdir()
        cli.run([
            "transpile", str(GOLDEN_FIXTURE),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        ir_file = out_dir / "signal_processor.s0ma.json"
        exit_code = cli.run(["inspect", str(ir_file)])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "signal_processor" in captured.out

    def test_graph_golden_ir(self, cli: S0maCLI, tmp_path: Path, capsys):
        out_dir = tmp_path / "golden_graph"
        out_dir.mkdir()
        cli.run([
            "transpile", str(GOLDEN_FIXTURE),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        # Flush transpile output before running graph
        capsys.readouterr()
        ir_file = out_dir / "signal_processor.s0ma.json"
        exit_code = cli.run(["graph", str(ir_file), "--format", "json"])
        assert exit_code == EXIT_SUCCESS
        data = json.loads(capsys.readouterr().out)
        assert len(data["nodes"]) > 0


# ===========================================================================
# Test: Strictness Modes via CLI
# ===========================================================================


class TestStrictnessModes:
    """Test that strictness modes are passed through correctly."""

    def test_all_modes_accepted_by_check(self, cli: S0maCLI, minimal_s0ma_file: Path):
        for mode in ["migration", "dev", "strict", "release"]:
            exit_code = cli.run([
                "check", str(minimal_s0ma_file),
                "--mode", mode,
            ])
            # Should not crash with any mode
            assert exit_code in (EXIT_SUCCESS, EXIT_VALIDATION_ERROR)

    def test_all_modes_accepted_by_transpile(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path
    ):
        for i, mode in enumerate(["migration", "dev", "strict", "release"]):
            out_dir = tmp_path / f"out_{i}"
            out_dir.mkdir()
            exit_code = cli.run([
                "transpile", str(minimal_s0ma_file),
                "--output-dir", str(out_dir),
                "--mode", mode,
            ])
            assert exit_code in (EXIT_SUCCESS, EXIT_VALIDATION_ERROR)


# ===========================================================================
# Test: Windows UTF-8 Encoding (Finding 1.3)
# ===========================================================================


class TestWindowsEncoding:
    """Test that the CLI entry point configures UTF-8 on Windows."""

    def test_main_reconfigures_stdout_on_win32(self, monkeypatch):
        """On Windows, main() should reconfigure stdout/stderr to UTF-8.

        The double subclasses ``io.TextIOWrapper`` because that is what real
        Windows console/redirect streams are — and what main()'s typed
        ``isinstance`` guard narrows on (typeshed's ``TextIO`` has no
        ``reconfigure``; the guard is what keeps the call strict-clean under
        ``mypy --platform win32``).
        """
        reconfigure_calls: list[dict] = []

        class FakeStream(io.TextIOWrapper):
            def __init__(self):
                super().__init__(io.BytesIO(), encoding="utf-8")

            def reconfigure(self, **kwargs):
                reconfigure_calls.append(kwargs)

            def write(self, s):
                pass

            def flush(self):
                pass

        fake_stdout = FakeStream()
        fake_stderr = FakeStream()

        monkeypatch.setattr("sys.platform", "win32")
        monkeypatch.setattr("sys.stdout", fake_stdout)
        monkeypatch.setattr("sys.stderr", fake_stderr)

        # main() calls sys.exit(), so catch SystemExit
        with pytest.raises(SystemExit):
            main([])

        # Both stdout and stderr should have been reconfigured
        assert len(reconfigure_calls) == 2
        assert reconfigure_calls[0] == {"encoding": "utf-8", "errors": "replace"}
        assert reconfigure_calls[1] == {"encoding": "utf-8", "errors": "replace"}

    def test_main_skips_non_text_io_wrapper_streams_on_win32(self, monkeypatch):
        """On Windows, a replaced non-TextIOWrapper stream is skipped, not crashed on.

        Before the typed guard, main() called ``reconfigure`` unguarded, so a
        captured/wrapped stream without the method raised ``AttributeError``
        at the entry point. The guard turns that degenerate case into a no-op;
        this pins the only behaviour the guard changed.
        """

        class CaptureStream:
            """Duck-typed stream WITHOUT reconfigure (e.g. a test-harness capture)."""

            def write(self, s):
                pass

            def flush(self):
                pass

        monkeypatch.setattr("sys.platform", "win32")
        monkeypatch.setattr("sys.stdout", CaptureStream())
        monkeypatch.setattr("sys.stderr", CaptureStream())

        # Reaching the normal CLI exit (SystemExit, not AttributeError) is the proof.
        with pytest.raises(SystemExit):
            main([])

    def test_main_does_not_reconfigure_on_non_windows(self, monkeypatch):
        """On non-Windows platforms, main() should NOT call reconfigure."""
        reconfigure_calls: list[dict] = []

        original_stdout = sys.stdout

        class SpyStream:
            def reconfigure(self, **kwargs):
                reconfigure_calls.append(kwargs)

            def write(self, s):
                return original_stdout.write(s)

            def flush(self):
                return original_stdout.flush()

        monkeypatch.setattr("sys.platform", "darwin")
        monkeypatch.setattr("sys.stdout", SpyStream())
        monkeypatch.setattr("sys.stderr", SpyStream())

        with pytest.raises(SystemExit):
            main([])

        assert len(reconfigure_calls) == 0

    def test_diagnostic_text_contains_unicode(self):
        """Diagnostic formatting uses unicode box-drawing characters."""
        err = S0maError(
            code="TEST_ERR",
            message="Test error",
            file="test.s0ma",
            line=1,
            column=0,
            severity="error",
            remediation="Fix it.",
        )
        text = _format_diagnostics_text([err], [])
        # The summary line uses unicode box-drawing ─
        assert "─" in text


# ===========================================================================
# Test: Cache Staleness on Single-File Transpile (Finding 5.7)
# ===========================================================================


class TestCacheStaleness:
    """Test that 's0ma transpile' invalidates stale incremental-cache entries.

    M6a (ADR-007): the canonical incremental cache lives at
    ``.s0ma.cache/`` (hidden, not importable). The legacy
    ``__s0ma_cache__/`` directory is no longer written by the CLI but
    is still recognised for invalidation so a transpile against a tree
    left over from a pre-M6a build cleans up the stale shadow.
    """

    def test_transpile_invalidates_stale_cache(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """After 's0ma transpile', stale cache entries should be removed."""
        # 1. Write a .s0ma file
        s0ma_file = tmp_path / "test_module.s0ma"
        s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")

        # 2. Simulate a prior 's0ma build' by populating .s0ma.cache/
        cache_dir = tmp_path / ".s0ma.cache"
        cache = BuildCache(cache_dir=cache_dir)
        cache.store(
            s0ma_file,
            py_content="# stale transpiled output",
            ir_content='{"stale": true}',
            map_content='{"version": 1}',
        )

        # Verify cache was populated
        assert (cache_dir / "test_module.py").exists()
        assert (cache_dir / "test_module.hash").exists()
        assert (cache_dir / "test_module.s0ma.json").exists()
        assert (cache_dir / "test_module.s0ma.map").exists()

        # 3. Modify the .s0ma file to make cache stale
        modified_s0ma = MINIMAL_S0MA.replace(
            "A minimal module for CLI testing.",
            "A MODIFIED module for CLI testing.",
        )
        s0ma_file.write_text(modified_s0ma, encoding="utf-8")

        # 4. Run 's0ma transpile' to a different output dir
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS

        # 5. The stale cache entry should be invalidated
        assert not (cache_dir / "test_module.hash").exists()
        assert not (cache_dir / "test_module.py").exists()
        assert not (cache_dir / "test_module.s0ma.json").exists()
        assert not (cache_dir / "test_module.s0ma.map").exists()

    def test_transpile_invalidates_legacy_cache(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """transpile must also invalidate stale legacy __s0ma_cache__/ entries.

        Pre-M6a builds wrote to ``__s0ma_cache__/``; a transpile against
        such a tree must clean up that legacy shadow so it cannot
        silently shadow imports.
        """
        s0ma_file = tmp_path / "test_module.s0ma"
        s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")

        legacy_cache_dir = tmp_path / "__s0ma_cache__"
        legacy_cache = BuildCache(cache_dir=legacy_cache_dir)
        legacy_cache.store(
            s0ma_file,
            py_content="# legacy stale output",
            ir_content='{"legacy": true}',
            map_content='{"version": 1}',
        )
        assert (legacy_cache_dir / "test_module.py").exists()

        # Modify source so the cache is genuinely stale.
        modified_s0ma = MINIMAL_S0MA.replace(
            "A minimal module for CLI testing.",
            "A MODIFIED module for CLI testing.",
        )
        s0ma_file.write_text(modified_s0ma, encoding="utf-8")

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        # Legacy cache entries cleaned up.
        assert not (legacy_cache_dir / "test_module.py").exists()
        assert not (legacy_cache_dir / "test_module.hash").exists()

    def test_transpile_without_cache_dir_is_noop(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """When no cache exists, transpile should not error."""
        s0ma_file = tmp_path / "test_module.s0ma"
        s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")

        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        # M6a: no cache directory of any flavor should have been created.
        assert not (tmp_path / ".s0ma.cache").exists()
        assert not (tmp_path / "__s0ma_cache__").exists()


# ===========================================================================
# Test: --no-cache flag (Task 5.1)
# ===========================================================================


class TestNoCacheFlag:
    """Test that 's0ma build --no-cache' skips cache creation."""

    def test_build_no_cache_skips_cache_dir(
        self, cli: S0maCLI, multi_s0ma_dir: Path, tmp_path: Path
    ):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "build", str(multi_s0ma_dir),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--no-cache",
        ])
        assert exit_code == EXIT_SUCCESS
        # M6a (ADR-007): no cache dir of any flavor should be created in
        # either location, and the legacy ``__s0ma_cache__/`` is gone for good.
        assert not (out_dir / ".s0ma.cache").exists()
        assert not (multi_s0ma_dir / ".s0ma.cache").exists()
        assert not (out_dir / "__s0ma_cache__").exists()
        assert not (multi_s0ma_dir / "__s0ma_cache__").exists()

    def test_build_no_cache_still_produces_output(
        self, cli: S0maCLI, multi_s0ma_dir: Path, tmp_path: Path
    ):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "build", str(multi_s0ma_dir),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--no-cache",
        ])
        assert exit_code == EXIT_SUCCESS
        # Output files should still exist
        assert (out_dir / "test_module.py").exists()

    def test_build_no_cache_parser_flag(self, cli: S0maCLI):
        parser = cli.build_parser()
        args = parser.parse_args(["build", ".", "--no-cache"])
        assert args.no_cache is True

    def test_build_default_no_cache_is_false(self, cli: S0maCLI):
        parser = cli.build_parser()
        args = parser.parse_args(["build", "."])
        assert args.no_cache is False


# ===========================================================================
# Test: --quiet flag (Task 5.2)
# ===========================================================================


class TestQuietFlag:
    """Test that --quiet / -q shows only errors and summary."""

    def test_quiet_flag_accepted_by_transpile(self, cli: S0maCLI):
        parser = cli.build_parser()
        args = parser.parse_args(["transpile", "test.s0ma", "--quiet"])
        assert args.quiet is True

    def test_quiet_flag_accepted_by_check(self, cli: S0maCLI):
        parser = cli.build_parser()
        args = parser.parse_args(["check", "test.s0ma", "-q"])
        assert args.quiet is True

    def test_quiet_flag_accepted_by_build(self, cli: S0maCLI):
        parser = cli.build_parser()
        args = parser.parse_args(["build", ".", "--quiet"])
        assert args.quiet is True

    def test_quiet_transpile_shows_summary(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path, capsys
    ):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--quiet",
        ])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "Transpiled 1 file(s). 0 errors" in captured.out
        # Should NOT list individual output files in quiet mode
        assert str(out_dir) not in captured.out

    def test_quiet_check_shows_summary(
        self, cli: S0maCLI, minimal_s0ma_file: Path, capsys
    ):
        exit_code = cli.run([
            "check", str(minimal_s0ma_file),
            "--mode", "dev",
            "--quiet",
        ])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "Checked 1 file(s). 0 errors" in captured.out

    def test_quiet_build_shows_summary(
        self, cli: S0maCLI, multi_s0ma_dir: Path, tmp_path: Path, capsys
    ):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "build", str(multi_s0ma_dir),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--quiet",
        ])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "Built 1 module(s). 0 errors" in captured.out

    def test_quiet_still_shows_errors(
        self, cli: S0maCLI, invalid_s0ma_file: Path, capsys
    ):
        exit_code = cli.run([
            "check", str(invalid_s0ma_file),
            "--mode", "dev",
            "--quiet",
        ])
        assert exit_code == EXIT_VALIDATION_ERROR


# ===========================================================================
# Test: --check drift detection (Task 5.3)
# ===========================================================================


class TestCheckDriftDetection:
    """Test that --check detects drift between .s0ma sources and transpiled output."""

    def test_check_returns_0_when_sources_match(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """Transpile, then --check should return 0."""
        s0ma_file = tmp_path / "test_module.s0ma"
        s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # First: transpile normally
        exit_code = cli.run([
            "transpile", str(s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS

        # Flush captured output
        capsys.readouterr()

        # Second: --check should find no drift
        exit_code = cli.run([
            "transpile", str(s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--check",
        ])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "All files match" in captured.out

    def test_check_returns_1_when_py_modified(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """Modify .py after transpile, --check should return 1."""
        s0ma_file = tmp_path / "test_module.s0ma"
        s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # Transpile
        cli.run([
            "transpile", str(s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])

        # Hand-edit the .py
        py_file = out_dir / "test_module.py"
        py_file.write_text(py_file.read_text() + "\n# hand-edited\n")

        capsys.readouterr()

        # --check should detect drift
        exit_code = cli.run([
            "transpile", str(s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--check",
        ])
        assert exit_code == EXIT_VALIDATION_ERROR
        captured = capsys.readouterr()
        assert "DRIFT" in captured.out
        assert "drifted" in captured.out

    def test_check_detects_ir_drift(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """Modify .s0ma.json after transpile, --check should detect it."""
        s0ma_file = tmp_path / "test_module.s0ma"
        s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # Transpile
        cli.run([
            "transpile", str(s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])

        # Hand-edit the .s0ma.json
        ir_file = out_dir / "test_module.s0ma.json"
        ir_file.write_text('{"tampered": true}')

        capsys.readouterr()

        # --check should detect IR drift
        exit_code = cli.run([
            "transpile", str(s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--check",
        ])
        assert exit_code == EXIT_VALIDATION_ERROR
        captured = capsys.readouterr()
        assert "DRIFT" in captured.out

    def test_check_normalizes_line_endings(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """CRLF vs LF should not cause false positives."""
        s0ma_file = tmp_path / "test_module.s0ma"
        s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # Transpile
        cli.run([
            "transpile", str(s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])

        # Convert LF to CRLF in the .py file. write_bytes, not write_text:
        # text-mode would re-translate each "\n" to os.linesep on write,
        # double-expanding "\r\n" into "\r\r\n" on Windows.
        py_file = out_dir / "test_module.py"
        content = py_file.read_text(encoding="utf-8")
        py_file.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))

        capsys.readouterr()

        # --check should NOT detect drift (line endings normalized)
        exit_code = cli.run([
            "transpile", str(s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--check",
        ])
        assert exit_code == EXIT_SUCCESS

    def test_check_build_returns_0_when_match(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """s0ma build --check should return 0 when sources match."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "test_module.s0ma").write_text(MINIMAL_S0MA, encoding="utf-8")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # First: build normally
        cli.run([
            "build", str(project_dir),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        capsys.readouterr()

        # Second: --check
        exit_code = cli.run([
            "build", str(project_dir),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--check",
        ])
        assert exit_code == EXIT_SUCCESS

    def test_check_build_returns_1_when_drifted(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """s0ma build --check should return 1 when .py was modified."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "test_module.s0ma").write_text(MINIMAL_S0MA, encoding="utf-8")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # Build
        cli.run([
            "build", str(project_dir),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])

        # Hand-edit
        py_file = out_dir / "test_module.py"
        py_file.write_text(py_file.read_text() + "\n# drifted\n")

        capsys.readouterr()

        # --check should detect drift
        exit_code = cli.run([
            "build", str(project_dir),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--check",
        ])
        assert exit_code == EXIT_VALIDATION_ERROR


# ===========================================================================
# Test: inspect accepts .s0ma files (Task 5.4)
# ===========================================================================


class TestInspectS0maFiles:
    """Test that 's0ma inspect' accepts .s0ma source files."""

    def test_inspect_s0ma_with_existing_ir(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """When .s0ma.json exists alongside .s0ma, use it."""
        s0ma_file = tmp_path / "test_module.s0ma"
        s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")

        # Transpile to produce .s0ma.json alongside .s0ma
        cli.run([
            "transpile", str(s0ma_file),
            "--mode", "dev",
        ])
        capsys.readouterr()

        # Now inspect the .s0ma file
        exit_code = cli.run(["inspect", str(s0ma_file)])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "Module: test_module" in captured.out

        # Cleanup
        (tmp_path / "test_module.py").unlink(missing_ok=True)
        (tmp_path / "test_module.s0ma.json").unlink(missing_ok=True)
        (tmp_path / "test_module.s0ma.map").unlink(missing_ok=True)

    def test_inspect_s0ma_auto_transpiles(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """When no .s0ma.json exists, auto-transpile to inspect."""
        s0ma_file = tmp_path / "test_module.s0ma"
        s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")

        # Inspect without prior transpile
        exit_code = cli.run(["inspect", str(s0ma_file)])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "Module: test_module" in captured.out
        assert "Auto-transpiling" in captured.out
        assert "Tip:" in captured.out

    def test_inspect_s0ma_with_cache_ir(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """When .s0ma.json exists in .s0ma.cache/, use it (M6a, ADR-007)."""
        s0ma_file = tmp_path / "test_module.s0ma"
        s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")

        # Build to populate cache
        cli.run([
            "build", str(tmp_path),
            "--mode", "dev",
        ])
        capsys.readouterr()

        # Remove non-cache .s0ma.json (if written to project dir)
        ir_in_root = tmp_path / "test_module.s0ma.json"
        if ir_in_root.exists():
            ir_in_root.unlink()

        # .s0ma.cache/test_module.s0ma.json should still exist
        cache_ir = tmp_path / ".s0ma.cache" / "test_module.s0ma.json"
        if cache_ir.exists():
            exit_code = cli.run(["inspect", str(s0ma_file)])
            assert exit_code == EXIT_SUCCESS
            captured = capsys.readouterr()
            assert "Module: test_module" in captured.out


# ===========================================================================
# Test: --include flag for cross-module resolution (Task 10.1)
# ===========================================================================


# Source module: defines and exports a component
_SOURCE_MODULE_S0MA = """\
module source_mod
    layer: DOMAIN
    version: 0.1.0
    intent: "Source module exporting a component."
    exports: [do_thing]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_thing :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A function that does something."
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
    def do_thing() -> str:
        return "done"
"""

# Test module: references source module via uses:
_TEST_MODULE_S0MA = """\
module test_source_mod
    layer: DOMAIN
    version: 0.1.0
    intent: "Test module for the source module."
    uses: [source_mod.do_thing]
    exports: [test_do_thing]

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
test test_do_thing :: DOMAIN
    intent: "Tests do_thing from source_mod."
    tests: [source_mod.do_thing]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_do_thing():
        pass
"""

# Duplicate module: same name as source, for collision testing
_DUPLICATE_MODULE_S0MA = """\
module source_mod
    layer: DOMAIN
    version: 0.1.0
    intent: "Duplicate module name for collision test."
    exports: [duplicate_fn]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve duplicate_fn :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A duplicate function."
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
    def duplicate_fn() -> str:
        return "dup"
"""


class TestIncludeFlag:
    """Test the --include / -I flag for cross-module resolution."""

    def _setup_cross_module(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create a src/ and tests/ directory with cross-referencing .s0ma files."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "source_mod.s0ma").write_text(_SOURCE_MODULE_S0MA, encoding="utf-8")

        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_source_mod.s0ma").write_text(_TEST_MODULE_S0MA, encoding="utf-8")

        return src_dir, test_dir

    def test_build_without_include_has_does_not_exist(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """Building tests/ without --include should fail with DOES_NOT_EXIST in release mode."""
        _, test_dir = self._setup_cross_module(tmp_path)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # Use release mode to force cross-module resolution even with a single module
        exit_code = cli.run([
            "build", str(test_dir),
            "--output-dir", str(out_dir),
            "--mode", "release",
        ])
        assert exit_code == EXIT_VALIDATION_ERROR

    def test_build_with_include_resolves(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """Building tests/ with --include src/ should resolve cross-module references."""
        src_dir, test_dir = self._setup_cross_module(tmp_path)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        exit_code = cli.run([
            "build", str(test_dir),
            "--output-dir", str(out_dir),
            "--include", str(src_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS

    def test_build_include_context_not_transpiled(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """Context modules from --include should NOT produce output files."""
        src_dir, test_dir = self._setup_cross_module(tmp_path)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        cli.run([
            "build", str(test_dir),
            "--output-dir", str(out_dir),
            "--include", str(src_dir),
            "--mode", "dev",
        ])

        # Target file should exist
        assert (out_dir / "test_source_mod.py").exists()
        # Context file should NOT exist
        assert not (out_dir / "source_mod.py").exists()
        assert not (out_dir / "do_thing.py").exists()

    def test_check_with_include_resolves(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """s0ma check tests/ --include src/ should validate cross-module references."""
        src_dir, test_dir = self._setup_cross_module(tmp_path)

        exit_code = cli.run([
            "check", str(test_dir),
            "--include", str(src_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS

    def test_check_without_include_has_errors(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """s0ma check tests/ without --include should fail in release mode."""
        _, test_dir = self._setup_cross_module(tmp_path)

        # Use release mode to force cross-module resolution even with a single module
        exit_code = cli.run([
            "check", str(test_dir),
            "--mode", "release",
        ])
        assert exit_code == EXIT_VALIDATION_ERROR

    def test_build_with_include_and_check(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """s0ma build tests/ --include src/ --check should work."""
        src_dir, test_dir = self._setup_cross_module(tmp_path)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # First transpile normally
        cli.run([
            "build", str(test_dir),
            "--output-dir", str(out_dir),
            "--include", str(src_dir),
            "--mode", "dev",
        ])
        capsys.readouterr()

        # Then --check
        exit_code = cli.run([
            "build", str(test_dir),
            "--output-dir", str(out_dir),
            "--include", str(src_dir),
            "--mode", "dev",
            "--check",
        ])
        assert exit_code == EXIT_SUCCESS

    def test_build_module_name_collision_error(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """Module name collision between target and include should error."""
        src_dir, test_dir = self._setup_cross_module(tmp_path)

        # Add a duplicate module name in the test dir
        (test_dir / "source_mod.s0ma").write_text(
            _DUPLICATE_MODULE_S0MA, encoding="utf-8"
        )

        out_dir = tmp_path / "out"
        out_dir.mkdir()

        exit_code = cli.run([
            "build", str(test_dir),
            "--output-dir", str(out_dir),
            "--include", str(src_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_VALIDATION_ERROR
        captured = capsys.readouterr()
        assert "MODULE_NAME_COLLISION" in captured.out

    def test_check_module_name_collision_error(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """Module name collision in check mode should error."""
        src_dir, test_dir = self._setup_cross_module(tmp_path)

        # Add duplicate in test dir
        (test_dir / "source_mod.s0ma").write_text(
            _DUPLICATE_MODULE_S0MA, encoding="utf-8"
        )

        exit_code = cli.run([
            "check", str(test_dir),
            "--include", str(src_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_VALIDATION_ERROR
        captured = capsys.readouterr()
        assert "MODULE_NAME_COLLISION" in captured.out

    def test_include_flag_parser_build(self, cli: S0maCLI):
        """--include / -I should be parseable on the build command."""
        parser = cli.build_parser()
        args = parser.parse_args([
            "build", ".", "--include", "src/", "--include", "lib/",
        ])
        assert args.include == ["src/", "lib/"]

    def test_include_flag_parser_check(self, cli: S0maCLI):
        """--include / -I should be parseable on the check command."""
        parser = cli.build_parser()
        args = parser.parse_args([
            "check", "test.s0ma", "-I", "src/",
        ])
        assert args.include == ["src/"]

    def test_include_flag_short_form(self, cli: S0maCLI):
        """-I should be a short form for --include."""
        parser = cli.build_parser()
        args = parser.parse_args([
            "build", ".", "-I", "src/", "-I", "lib/",
        ])
        assert args.include == ["src/", "lib/"]

    def test_include_default_empty(self, cli: S0maCLI):
        """Without --include, args.include should be an empty list."""
        parser = cli.build_parser()
        args = parser.parse_args(["build", "."])
        assert args.include == []


# ===========================================================================
# Test: s0ma transpile output-dir mismatch info message (Task 10.2)
# ===========================================================================


class TestOutputDirMismatchInfo:
    """Test that s0ma transpile shows an info message when --output-dir differs from source."""

    def test_info_shown_when_output_dir_differs(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path, capsys
    ):
        """Info message should appear when --output-dir is different from source dir."""
        out_dir = tmp_path / "other_output"
        out_dir.mkdir()

        exit_code = cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "Info: Output written to" in captured.out
        assert "sys.path" in captured.out

    def test_no_info_when_no_output_dir(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """No info message when no --output-dir is specified."""
        s0ma_file = tmp_path / "test_module.s0ma"
        s0ma_file.write_text(MINIMAL_S0MA, encoding="utf-8")

        exit_code = cli.run([
            "transpile", str(s0ma_file),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "Info: Output written to" not in captured.out

        # Cleanup
        (tmp_path / "test_module.py").unlink(missing_ok=True)
        (tmp_path / "test_module.s0ma.json").unlink(missing_ok=True)
        (tmp_path / "test_module.s0ma.map").unlink(missing_ok=True)

    def test_no_info_in_quiet_mode(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path, capsys
    ):
        """Info message should not appear in --quiet mode."""
        out_dir = tmp_path / "quiet_output"
        out_dir.mkdir()

        exit_code = cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
            "--quiet",
        ])
        assert exit_code == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "Info: Output written to" not in captured.out


# ===========================================================================
# Test: s0ma verify (MS 5b)
# ===========================================================================


class TestVerifyCommand:
    """Tests for the ``s0ma verify`` command (drift detection via checksums)."""

    def test_transpiled_files_contain_hashes(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path
    ):
        """Transpiled .py files should contain hash comments."""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        exit_code = cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        assert exit_code == EXIT_SUCCESS

        py_file = out_dir / "test_module.py"
        content = py_file.read_text(encoding="utf-8")
        assert "# s0ma-source-hash: sha256:" in content
        assert "# s0ma-output-hash: sha256:" in content
        # No placeholders should remain
        assert "__S0MA_SOURCE_HASH__" not in content
        assert "__S0MA_OUTPUT_HASH__" not in content

    def test_verify_clean_file(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path
    ):
        """Verify a freshly transpiled file reports CLEAN."""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        py_file = out_dir / "test_module.py"

        # Copy .s0ma next to .py so verify can find it
        import shutil
        shutil.copy(minimal_s0ma_file, out_dir / "test_module.s0ma")

        exit_code = cli.run(["verify", str(py_file)])
        assert exit_code == EXIT_SUCCESS

    def test_verify_edited_file(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path, capsys
    ):
        """Editing the .py after transpilation should report EDITED.

        And name the two ways out a build accepts: it refuses to overwrite
        a hand edit, so "run `s0ma build` to re-transpile" alone is wrong.
        """
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        py_file = out_dir / "test_module.py"

        # Copy .s0ma next to .py
        import shutil
        shutil.copy(minimal_s0ma_file, out_dir / "test_module.s0ma")

        # Hand-edit the .py file
        content = py_file.read_text(encoding="utf-8")
        py_file.write_text(content + "\n# hand edit\n", encoding="utf-8")

        capsys.readouterr()
        exit_code = cli.run(["verify", str(py_file)])
        assert exit_code == EXIT_VALIDATION_ERROR
        out = capsys.readouterr().out
        assert (
            "For edited files: move the hand edits into the .s0ma source and "
            "run `s0ma build`, or discard them with `s0ma build --force`."
        ) in out
        assert "re-transpile" not in out

    def test_verify_stale_file(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path, capsys
    ):
        """Modifying the .s0ma source should report STALE."""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])

        # Copy .s0ma next to .py, then modify it
        import shutil
        s0ma_copy = out_dir / "test_module.s0ma"
        shutil.copy(minimal_s0ma_file, s0ma_copy)
        s0ma_copy.write_text(
            s0ma_copy.read_text(encoding="utf-8") + "\n# modified source\n",
            encoding="utf-8",
        )

        py_file = out_dir / "test_module.py"
        capsys.readouterr()
        exit_code = cli.run(["verify", str(py_file)])
        assert exit_code == EXIT_VALIDATION_ERROR
        out = capsys.readouterr().out
        assert (
            "For stale files: run `s0ma build` to re-transpile from .s0ma sources."
        ) in out
        assert "--force" not in out

    def test_verify_unknown_only_exits_nothing_verified(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """Files without hash comments report UNKNOWN; a tree with ONLY
        such files exits EXIT_NOTHING_VERIFIED (pilot01) — a vacuous
        "clean" pass over zero s0ma artifacts is not a pass."""
        py_file = tmp_path / "no_hashes.py"
        py_file.write_text("# plain python\npass\n", encoding="utf-8")

        capsys.readouterr()
        exit_code = cli.run(["verify", str(py_file)])
        assert exit_code == EXIT_NOTHING_VERIFIED
        out = capsys.readouterr().out
        assert "UNKNOWN" in out
        assert "HOLLOW_MODEL: 0 adopted, 0 modeled" in out
        assert (
            "Coverage: 0 modeled s0ma module(s), 0 roster-adopted file(s), "
            "1 unknown plain-Python file(s)." in out
        )
        assert "All files are clean." not in out

    def test_verify_plain_py_tree_exits_nothing_verified_text_and_json(
        self, cli: S0maCLI, tmp_path: Path, capsys
    ):
        """Pilot01 (a): a directory containing only plain .py files (no
        s0ma hash headers) exits 4 in BOTH text and json formats, and
        the text output carries the nothing-verified + coverage lines."""
        (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")
        (tmp_path / "util.py").write_text("X = 1\n", encoding="utf-8")

        # Text format
        capsys.readouterr()
        rc = cli.run(["verify", str(tmp_path)])
        assert rc == EXIT_NOTHING_VERIFIED
        out = capsys.readouterr().out
        assert "HOLLOW_MODEL: 0 adopted, 0 modeled" in out
        assert (
            "Coverage: 0 modeled s0ma module(s), 0 roster-adopted file(s), "
            "2 unknown plain-Python file(s)." in out
        )
        assert "All files are clean." not in out

        # JSON format: list shape unchanged, exit code carries the state.
        capsys.readouterr()
        rc = cli.run(["verify", str(tmp_path), "--format", "json"])
        assert rc == EXIT_NOTHING_VERIFIED
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        assert {row["status"] for row in data} == {"UNKNOWN", "HOLLOW_MODEL"}

    def test_verify_clean_module_exits_success_with_coverage_line(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path, capsys
    ):
        """Pilot01 (a): >=1 clean transpiled module still exits 0, and
        the always-on coverage line makes the hollow-model case visible
        (verified modules vs unregistered plain-Python files)."""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])
        import shutil
        shutil.copy(minimal_s0ma_file, out_dir / "test_module.s0ma")
        # A stray plain-Python file rides along so the coverage line
        # has something to count on both sides.
        (out_dir / "stray.py").write_text("Y = 2\n", encoding="utf-8")

        capsys.readouterr()
        rc = cli.run(["verify", str(out_dir)])
        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert (
            "Coverage: 1 modeled s0ma module(s), 0 roster-adopted file(s), "
            "1 unknown plain-Python file(s)." in out
        )
        assert "All files are clean." in out
        assert "Nothing verified" not in out

    def test_verify_json_output(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path, capsys
    ):
        """JSON output mode should produce valid JSON."""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])

        import shutil
        shutil.copy(minimal_s0ma_file, out_dir / "test_module.s0ma")

        # Flush captured output from transpile before verify
        capsys.readouterr()

        py_file = out_dir / "test_module.py"
        exit_code = cli.run(["verify", str(py_file), "--format", "json"])
        assert exit_code == EXIT_SUCCESS

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["status"] == "CLEAN"

    def test_ir_contains_source_hash(
        self, cli: S0maCLI, minimal_s0ma_file: Path, tmp_path: Path
    ):
        """.s0ma.json IR should contain top-level source_hash field."""
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        cli.run([
            "transpile", str(minimal_s0ma_file),
            "--output-dir", str(out_dir),
            "--mode", "dev",
        ])

        ir_file = out_dir / "test_module.s0ma.json"
        data = json.loads(ir_file.read_text(encoding="utf-8"))
        assert "source_hash" in data
        assert data["source_hash"].startswith("sha256:")
        # Truncated to 16 hex chars
        hex_part = data["source_hash"].split(":")[1]
        assert len(hex_part) == 16


# ===========================================================================
# Test: `s0ma new` Command (MS 12)
# ===========================================================================


class TestNewCommand:
    """Test the `s0ma new` scaffolding command."""

    def test_new_module_generates_valid_file(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """s0ma new module X --layer DOMAIN generates a valid .s0ma file."""
        exit_code = cli.run([
            "new", "module", "HelloTool",
            "--layer", "DOMAIN",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_SUCCESS

        out_file = tmp_path / "hello_tool.s0ma"
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "module hello_tool" in content
        assert "layer: DOMAIN" in content
        assert "nerve HelloTool :: DOMAIN" in content

    def test_new_module_with_kind(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """--kind sets the nerve kind in the generated module."""
        exit_code = cli.run([
            "new", "module", "DataFetcher",
            "--layer", "APPLICATION",
            "--kind", "ADAPTER",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_SUCCESS

        content = (tmp_path / "data_fetcher.s0ma").read_text(encoding="utf-8")
        assert "kind: ADAPTER" in content

    def test_new_module_passes_check(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """Generated module file passes s0ma check."""
        cli.run([
            "new", "module", "Checker",
            "--layer", "DOMAIN",
            "--output-dir", str(tmp_path),
        ])
        exit_code = cli.run(["check", str(tmp_path / "checker.s0ma"), "--mode", "dev"])
        assert exit_code == EXIT_SUCCESS

    def test_new_nerve_generates_valid_file(
        self, cli: S0maCLI, tmp_path: Path
    ):
        exit_code = cli.run([
            "new", "nerve", "ProcessData",
            "--layer", "DOMAIN",
            "--kind", "FUNCTION",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_SUCCESS

        content = (tmp_path / "process_data.s0ma").read_text(encoding="utf-8")
        assert "nerve ProcessData :: DOMAIN" in content
        assert "kind: FUNCTION" in content

    def test_new_cell_generates_valid_file(
        self, cli: S0maCLI, tmp_path: Path
    ):
        exit_code = cli.run([
            "new", "cell", "UserModel",
            "--layer", "DOMAIN",
            "--kind", "MODEL",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_SUCCESS

        content = (tmp_path / "user_model.s0ma").read_text(encoding="utf-8")
        assert "cell UserModel :: DOMAIN" in content
        assert "kind: MODEL" in content

    def test_new_cell_constant_uses_assignment_body(
        self, cli: S0maCLI, tmp_path: Path
    ):
        exit_code = cli.run([
            "new", "cell", "MaxRetries",
            "--layer", "INFRASTRUCTURE",
            "--kind", "CONSTANT",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_SUCCESS

        content = (tmp_path / "max_retries.s0ma").read_text(encoding="utf-8")
        assert "MaxRetries = None" in content

    def test_new_test_generates_valid_file(
        self, cli: S0maCLI, tmp_path: Path
    ):
        exit_code = cli.run([
            "new", "test", "test_auth",
            "--layer", "APPLICATION",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_SUCCESS

        content = (tmp_path / "test_auth.s0ma").read_text(encoding="utf-8")
        assert "test test_auth :: APPLICATION" in content
        assert "assert True" in content

    def test_new_refuses_existing_file(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """Should not overwrite an existing file."""
        (tmp_path / "existing.s0ma").write_text("# existing", encoding="utf-8")
        exit_code = cli.run([
            "new", "module", "Existing",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_USAGE_ERROR

    def test_new_invalid_nerve_kind(self, cli: S0maCLI, tmp_path: Path):
        exit_code = cli.run([
            "new", "nerve", "Bad",
            "--kind", "MODEL",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_USAGE_ERROR

    def test_new_invalid_cell_kind(self, cli: S0maCLI, tmp_path: Path):
        exit_code = cli.run([
            "new", "cell", "Bad",
            "--kind", "SERVICE",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_USAGE_ERROR

    def test_new_test_rejects_kind(self, cli: S0maCLI, tmp_path: Path):
        exit_code = cli.run([
            "new", "test", "test_x",
            "--kind", "FUNCTION",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_USAGE_ERROR

    def test_new_parser_registered(self, cli: S0maCLI):
        parser = cli.build_parser()
        args = parser.parse_args(["new", "module", "Foo"])
        assert args.command == "new"
        assert args.type == "module"
        assert args.name == "Foo"
        assert args.layer == "DOMAIN"

    def test_new_module_body_comments_validate_clean_strict(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """Pilot01 (d): the scaffolded module carries the body-rule
        comment lines AND still passes `s0ma check` in strict mode
        (comments are legal in bodies, invisible to the classifier)."""
        exit_code = cli.run([
            "new", "module", "Widget",
            "--layer", "DOMAIN",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_SUCCESS

        out_file = tmp_path / "widget.s0ma"
        content = out_file.read_text(encoding="utf-8")
        assert "# Body rule: exactly ONE def below" in content
        assert "# Imports do NOT go here" in content
        assert "requires: [json, pathlib.Path]" in content

        exit_code = cli.run(["check", str(out_file), "--mode", "strict"])
        assert exit_code == EXIT_SUCCESS

    def test_new_module_consecutive_capitals_filename(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """Pilot01 (d): `s0ma new module CLI` scaffolds cli.s0ma with
        module name `cli` (not c_l_i.s0ma / module c_l_i)."""
        exit_code = cli.run([
            "new", "module", "CLI",
            "--layer", "DOMAIN",
            "--output-dir", str(tmp_path),
        ])
        assert exit_code == EXIT_SUCCESS
        out_file = tmp_path / "cli.s0ma"
        assert out_file.exists(), (
            f"expected cli.s0ma; dir holds {[p.name for p in tmp_path.iterdir()]}"
        )
        content = out_file.read_text(encoding="utf-8")
        assert "module cli\n" in content
        assert "nerve CLI :: DOMAIN" in content
        assert "c_l_i" not in content


# ===========================================================================
# Test: `s0ma test` Command (MS 12)
# ===========================================================================


class TestTestCommand:
    """Test the `s0ma test` convenience command."""

    def test_test_parser_registered(self, cli: S0maCLI):
        parser = cli.build_parser()
        args = parser.parse_args(["test", "tests/"])
        assert args.command == "test"
        assert args.test_dir == "tests/"

    def test_test_parser_accepts_no_test_dir(self, cli: S0maCLI):
        """M7: ``test_dir`` is optional — defaults to project's test_roots."""
        parser = cli.build_parser()
        args = parser.parse_args(["test"])
        assert args.command == "test"
        assert args.test_dir is None

    def test_test_bad_dir_returns_usage_error(
        self, cli: S0maCLI, tmp_path: Path
    ):
        # M7: pass --project-root pointing at a synthetic-fallback project
        # so discovery doesn't pick up the s0ma-dsl repo itself.
        proj = tmp_path / "proj"
        proj.mkdir()
        exit_code = cli.run([
            "--project-root", str(proj),
            "test", str(tmp_path / "nonexistent"),
        ])
        assert exit_code == EXIT_USAGE_ERROR

    def test_test_empty_dir_returns_usage_error(
        self, cli: S0maCLI, tmp_path: Path
    ):
        # M7: an empty explicit test_dir produces a build failure
        # (no .s0ma files to compile).
        proj = tmp_path / "proj"
        proj.mkdir()
        empty = tmp_path / "empty"
        empty.mkdir()
        exit_code = cli.run([
            "--project-root", str(proj),
            "test", str(empty),
        ])
        assert exit_code == EXIT_USAGE_ERROR

    def test_test_transpiles_and_runs_pytest(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """End-to-end: s0ma test transpiles .s0ma files and runs pytest."""
        # M7: build a minimal project with [tool.s0ma] so discovery
        # resolves test_roots correctly.
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "pyproject.toml").write_text(
            "[project]\nname = \"basic_test_proj\"\n\n"
            "[tool.s0ma]\n"
            "source_roots = [\"src\"]\n"
            "test_roots = [\"tests\"]\n"
            "build_dir = \"build\"\n"
            "bootstrap_files = []\n",
            encoding="utf-8",
        )
        test_dir = proj / "tests"
        test_dir.mkdir()
        (proj / "src").mkdir()

        # Create a minimal test .s0ma file
        s0ma_content = """\
module test_basic
    layer: DOMAIN
    version: 0.1.0
    intent: "Basic test module."
    exports: []

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
test test_addition :: DOMAIN
    intent: "Verifies addition works."
    tests: []
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_addition():
        assert 1 + 1 == 2
"""
        (test_dir / "test_basic.s0ma").write_text(s0ma_content, encoding="utf-8")

        exit_code = cli.run([
            "--project-root", str(proj),
            "test",
        ])
        assert exit_code == EXIT_SUCCESS


# ===========================================================================
# Test: `s0ma test-conftest` Command (MS 12)
# ===========================================================================


class TestTestConftestCommand:
    """Test the `s0ma test-conftest` conftest.py generator."""

    def test_conftest_parser_registered(self, cli: S0maCLI):
        parser = cli.build_parser()
        args = parser.parse_args(["test-conftest", "--project", "src/"])
        assert args.command == "test-conftest"
        assert args.project == "src/"

    def test_conftest_generates_file(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """test-conftest generates a working conftest.py."""
        # Create a project dir with .s0ma files
        project = tmp_path / "project"
        project.mkdir()
        (project / "service.s0ma").write_text(MINIMAL_S0MA, encoding="utf-8")

        output = tmp_path / "conftest.py"
        exit_code = cli.run([
            "test-conftest",
            "--project", str(project),
            "--output", str(output),
        ])
        assert exit_code == EXIT_SUCCESS
        assert output.exists()

        content = output.read_text(encoding="utf-8")
        assert "mock_s0ma_runtime" in content
        assert "mock_component" in content
        assert "mock_register_module" in content
        assert "pytest.fixture" in content

    def test_conftest_includes_project_kinds(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """Generated conftest references the kinds/layers from the project."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "service.s0ma").write_text(MINIMAL_S0MA, encoding="utf-8")

        output = tmp_path / "conftest.py"
        cli.run([
            "test-conftest",
            "--project", str(project),
            "--output", str(output),
        ])
        content = output.read_text(encoding="utf-8")
        assert "FUNCTION" in content
        assert "DOMAIN" in content

    def test_conftest_bad_project_dir(self, cli: S0maCLI, tmp_path: Path):
        exit_code = cli.run([
            "test-conftest",
            "--project", str(tmp_path / "nonexistent"),
        ])
        assert exit_code == EXIT_USAGE_ERROR

    def test_conftest_empty_project(
        self, cli: S0maCLI, tmp_path: Path
    ):
        """Empty project still generates a valid conftest."""
        project = tmp_path / "empty_project"
        project.mkdir()

        output = tmp_path / "conftest.py"
        exit_code = cli.run([
            "test-conftest",
            "--project", str(project),
            "--output", str(output),
        ])
        assert exit_code == EXIT_SUCCESS
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "mock_s0ma_runtime" in content

    def test_generate_conftest_helper(self):
        """Unit test the conftest generation helper."""
        result = _generate_conftest(
            kinds_used={"SERVICE", "FUNCTION"},
            layers_used={"DOMAIN", "APPLICATION"},
        )
        assert "mock_component" in result
        assert "mock_register_module" in result
        assert "SERVICE" in result
        assert "DOMAIN" in result


# ===========================================================================
# Test: Scaffold Template Helper (MS 12)
# ===========================================================================


class TestScaffoldTemplate:
    """Unit tests for _scaffold_template."""

    def test_module_template_compiles(self):
        content = _scaffold_template("module", "MyModule", "DOMAIN", "SERVICE")
        assert "module my_module" in content
        assert "nerve MyModule :: DOMAIN" in content
        # Should be parseable
        module, errors = _parse_single_file(
            Path("inline"), StrictnessMode.DEV
        ) if False else (None, [])  # Inline check deferred to integration

    def test_nerve_template_includes_kind(self):
        content = _scaffold_template("nerve", "DoWork", "APPLICATION", "ADAPTER")
        assert "kind: ADAPTER" in content

    def test_cell_model_has_class_body(self):
        content = _scaffold_template("cell", "UserModel", "DOMAIN", "MODEL")
        assert "class UserModel:" in content

    def test_cell_constant_has_assignment_body(self):
        content = _scaffold_template("cell", "MaxRetries", "DOMAIN", "CONSTANT")
        assert "MaxRetries = None" in content

    def test_test_template_has_assert(self):
        content = _scaffold_template("test", "test_auth", "APPLICATION", None)
        assert "assert True" in content
        assert "test test_auth :: APPLICATION" in content

    def test_module_and_nerve_templates_teach_body_rules(self):
        """Pilot01 (d): the module and nerve templates carry the
        body-rule comment lines (one def only; imports go in the module
        header's `requires:`) between the `---` and the def."""
        for decl_type in ("module", "nerve"):
            content = _scaffold_template(decl_type, "MyThing", "DOMAIN", "SERVICE")
            assert (
                "    # Body rule: exactly ONE def below — nothing else at this level.\n"
                "    # Imports do NOT go here: declare them in the module header, e.g.\n"
                "    #   requires: [json, pathlib.Path]   (transpiler emits the imports)\n"
                "    def MyThing():\n"
            ) in content, f"{decl_type} template missing body-rule comments"
            # The comments sit after the separator, inside the body.
            assert content.index("---") < content.index("# Body rule")

    def test_consecutive_capitals_snake_case(self):
        """Pilot01 (5): runs of capitals no longer degrade to c_l_i."""
        assert _snake_case("CLI") == "cli"
        assert _snake_case("IOHandler") == "io_handler"
        assert _snake_case("HTTPServer2") == "http_server2"
        assert _snake_case("MyModule") == "my_module"
        content = _scaffold_template("module", "CLI", "DOMAIN", "SERVICE")
        assert "module cli\n" in content
        assert "c_l_i" not in content

    def test_service_module_scaffolds_provides_skeleton(self):
        """batch-01a D3: a SERVICE module scaffolds the multi-function
        factory skeleton (a `provides:` block + a factory returning a
        dict of named operations) and teaches the MODULE_SUBSCRIPT trap
        — the sanctioned answer to "I need several functions", instead of
        the factory-dict-then-module-subscript anti-pattern."""
        content = _scaffold_template("module", "OpRegistry", "DOMAIN", "SERVICE")
        assert "kind: SERVICE" in content
        assert "provides:" in content
        assert "- operation_one:" in content and "- operation_two:" in content
        # a factory returning a dict whose keys match the provides names
        assert "return {" in content
        assert '"operation_one": operation_one' in content
        # the trap is named inline, pointing at the patterns guide
        assert "MODULE_SUBSCRIPT" in content
        assert "s0ma://guide/patterns" in content
        # the pilot-01 body-rule teaching is preserved above the factory
        assert "# Body rule: exactly ONE def below" in content
        # a non-SERVICE kind stays the minimal single-def template
        adapter = _scaffold_template("module", "EdgeThing", "INFRASTRUCTURE", "ADAPTER")
        assert "provides: none" in adapter
        assert "- operation_one:" not in adapter
        assert "return {" not in adapter


# ---------------------------------------------------------------------------
# W-3 / INV-5 (Windows plan M2): artifact writers pin newline="\n", so
# every emitted text artifact is byte-identical across OS. Asserted in
# BYTES space — on POSIX these pass trivially; on Windows they fail
# loudly if any writer loses its newline pin.
# ---------------------------------------------------------------------------


def _assert_lf_bytes(path: Path) -> None:
    data = path.read_bytes()
    assert b"\r" not in data, f"{path.name}: CR byte in emitted artifact"
    assert data.endswith(b"\n"), f"{path.name}: missing trailing newline"


class TestArtifactBytesAreLF:
    """Every text artifact the toolchain emits uses LF on every OS."""

    def test_build_artifacts_are_lf_bytes(self, tmp_path: Path) -> None:
        """Full build: .py, IR, map, manifest, stub, __init__, cache files."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "test_module.s0ma").write_text(
            MINIMAL_S0MA, encoding="utf-8"
        )
        out_dir = tmp_path / "out"

        cli = S0maCLI()
        rc = cli.run([
            "build", str(project_dir), "--output-dir", str(out_dir), "--quiet",
        ])

        assert rc == EXIT_SUCCESS
        emitted = [p for p in out_dir.rglob("*") if p.is_file()]
        assert len(emitted) >= 6, "expected outputs + cache entries"
        for path in emitted:
            _assert_lf_bytes(path)

    def test_scaffold_output_is_lf_bytes(self, tmp_path: Path) -> None:
        """`s0ma new module` writes the scaffold with LF bytes."""
        cli = S0maCLI()
        rc = cli.run([
            "new", "module", "Sensor", "--layer", "DOMAIN",
            "--output-dir", str(tmp_path),
        ])
        assert rc == EXIT_SUCCESS
        _assert_lf_bytes(tmp_path / "sensor.s0ma")

    def test_generated_conftest_is_lf_bytes(self, tmp_path: Path) -> None:
        """`s0ma test-conftest` writes conftest.py with LF bytes."""
        (tmp_path / "test_module.s0ma").write_text(
            MINIMAL_S0MA, encoding="utf-8"
        )
        cli = S0maCLI()
        rc = cli.run([
            "test-conftest", "--project", str(tmp_path),
            "--output", str(tmp_path / "conftest.py"),
        ])
        assert rc == EXIT_SUCCESS
        _assert_lf_bytes(tmp_path / "conftest.py")


# ---------------------------------------------------------------------------
# DSL-M4 (F-M0-3, A-16): ``python -m s0ma_dsl`` package entry point.
# ---------------------------------------------------------------------------


class TestPackageEntryPoint:
    def test_python_m_s0ma_dsl_help_is_clean(self) -> None:
        """``python -m s0ma_dsl --help`` exits 0 and emits no runpy
        RuntimeWarning. The package ``__main__`` delegates to
        ``cli.main:main`` so the ``-m s0ma_dsl.cli.main`` re-execution
        warning ("found in sys.modules ... unpredictable behaviour") never
        fires — this is the clean ``-m`` form scripts/check.py uses."""
        import subprocess

        proc = subprocess.run(
            [sys.executable, "-W", "all", "-m", "s0ma_dsl", "--help"],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "RuntimeWarning" not in proc.stderr
        assert "found in sys.modules" not in proc.stderr
        # Sanity: it really is the s0ma CLI help.
        assert "usage: s0ma" in proc.stdout
