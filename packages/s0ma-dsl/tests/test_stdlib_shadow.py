"""B3 (s0ma 0.11.0, batch-01a) — stdlib-shadow collision safety.

A s0ma module named after a Python stdlib module (``io``, ``json`` …)
cannot be imported by its bare name: the stdlib module is already
resident in ``sys.modules`` at interpreter start, so
``bootstrap_imports`` / ``importlib.import_module`` returns the stdlib
module and cross-module ``uses:`` resolution fails at runtime. This
detonated bench run ``P1_P_r02`` (a module named ``io`` forced the
agent into a hand-written importlib shim).

Three defences, tested here:
  1. ``MODULE_SHADOWS_STDLIB`` — a validator diagnostic (warning in
     migration/dev, error in strict/release) steering the author to
     rename the module.
  2. ``s0ma new module <stdlibname>`` warns at scaffold time.
  3. The emitter emits a collision-safe sibling-file load for a
     ``uses:`` entry that targets a shadowing module, so a dev build's
     emitted code works at runtime (no hand shim needed). Non-shadowing
     projects are byte-identical.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.config import ERROR_CODE_DESCRIPTIONS, StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.semantic.validator import validate_module

if TYPE_CHECKING:
    from pathlib import Path

_IO_MODULE = """\
module io
    layer: DOMAIN
    version: 0.1.0
    intent: "IO helper whose name shadows the stdlib io module."
    exports: [read_data]
    requires: []
    uses: []

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve read_data :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Read tabular data from a path."
    expects: "A filesystem path."
    guarantees: "Returns a list of rows."
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
    def read_data(path):
        return ["s0ma-io", path]
"""

_SAFE_MODULE = _IO_MODULE.replace("module io", "module reader").replace(
    "shadows the stdlib io module", "does not shadow a stdlib module"
)


def _validate(source: str, *, mode: StrictnessMode):
    module, warnings = parse_s0ma_with_warnings(source, "io.s0ma", mode=mode)
    errors = validate_module(module, mode=mode, filename="io.s0ma")
    return list(warnings) + list(errors)


class TestModuleShadowsStdlibDiagnostic:
    def test_warns_in_dev_errors_in_strict(self) -> None:
        expected = {
            StrictnessMode.MIGRATION: "warning",
            StrictnessMode.DEV: "warning",
            StrictnessMode.STRICT: "error",
            StrictnessMode.RELEASE: "error",
        }
        for mode, severity in expected.items():
            diags = [
                d for d in _validate(_IO_MODULE, mode=mode)
                if d.code == "MODULE_SHADOWS_STDLIB"
            ]
            assert len(diags) == 1, f"mode {mode}: {[d.code for d in diags]}"
            assert diags[0].severity == severity, f"mode {mode}"
            assert diags[0].context["module_name"] == "io"
            assert "rename" in diags[0].remediation.lower()

    def test_non_stdlib_module_name_is_clean(self) -> None:
        for mode in StrictnessMode:
            diags = [
                d for d in _validate(_SAFE_MODULE, mode=mode)
                if d.code == "MODULE_SHADOWS_STDLIB"
            ]
            assert not diags, f"mode {mode} falsely flagged 'reader'"

    def test_code_is_cataloged(self) -> None:
        assert "MODULE_SHADOWS_STDLIB" in ERROR_CODE_DESCRIPTIONS


class TestScaffoldWarnsOnStdlibName:
    def test_new_module_warns_on_stdlib_name(
        self, tmp_path: Path, capsys,
    ) -> None:
        rc = S0maCLI().run([
            "new", "module", "io", "--output-dir", str(tmp_path),
        ])
        out = capsys.readouterr().out
        assert rc == 0  # scaffold still succeeds
        assert "shadows the Python standard-library module 'io'" in out
        assert (tmp_path / "io.s0ma").exists()

    def test_new_module_no_warning_for_safe_name(
        self, tmp_path: Path, capsys,
    ) -> None:
        rc = S0maCLI().run([
            "new", "module", "reader", "--output-dir", str(tmp_path),
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "shadows the Python standard-library" not in out


class TestEmitterCollisionSafeAliasing:
    def _emit(self, source: str) -> str:
        module, _ = parse_s0ma_with_warnings(
            source, "consumer.s0ma", mode=StrictnessMode.DEV,
        )
        return PythonEmitter(filename="consumer.s0ma").emit(module)

    def test_shadowing_uses_emits_sibling_loader(self) -> None:
        consumer = textwrap.dedent("""\
module consumer
    layer: APPLICATION
    version: 0.1.0
    intent: "Consumer that uses the io module."
    exports: [run]
    requires: []
    uses: [io.read_data]

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve run :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Run the consumer pipeline."
    expects: "No arguments."
    guarantees: "Returns the read rows."
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
    def run():
        return read_data("x")
""")
        emitted = self._emit(consumer)
        assert "_s0ma_import_shadowed" in emitted
        assert 'read_data = _s0ma_import_shadowed("io").read_data' in emitted
        # The plain from-import must NOT be emitted for the shadowing module.
        assert "from io import read_data" not in emitted

    def test_non_shadowing_uses_is_unchanged(self) -> None:
        consumer = textwrap.dedent("""\
module consumer
    layer: APPLICATION
    version: 0.1.0
    intent: "Consumer that uses a non-stdlib module."
    exports: [run]
    requires: []
    uses: [reader.read_data]

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve run :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Run the consumer pipeline."
    expects: "No arguments."
    guarantees: "Returns the read rows."
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
    def run():
        return read_data("x")
""")
        emitted = self._emit(consumer)
        assert "_s0ma_import_shadowed" not in emitted
        assert "from reader import read_data" in emitted

    def test_shadowing_module_consumer_works_at_runtime(
        self, tmp_path: Path,
    ) -> None:
        """End-to-end: a dev build of an `io`-named module + consumer
        bootstraps and runs, resolving to the s0ma module (not stdlib)."""
        (tmp_path / "pyproject.toml").write_text(textwrap.dedent("""\
            [project]
            name = "shadowdemo"
            version = "0.0.1"

            [tool.s0ma]
            source_roots = ["src"]
            test_roots = ["tests"]
            build_dir = "build"
            """))
        src = tmp_path / "src"
        src.mkdir()
        (src / "io.s0ma").write_text(_IO_MODULE)
        (src / "consumer.s0ma").write_text(textwrap.dedent("""\
module consumer
    layer: APPLICATION
    version: 0.1.0
    intent: "Consumer that uses the io module."
    exports: [run]
    requires: []
    uses: [io.read_data]

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve run :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Run the consumer pipeline."
    expects: "No arguments."
    guarantees: "Returns the read rows."
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
    def run():
        return read_data("x")
"""))
        # dev mode — strict/release would error MODULE_SHADOWS_STDLIB.
        rc = S0maCLI().run([
            "--project-root", str(tmp_path),
            "build", str(tmp_path), "--mode", "dev",
        ])
        assert rc == 0

        build_dir = tmp_path / "build"
        proc = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(f"""\
                from s0ma.bootstrap import bootstrap_imports
                mods = bootstrap_imports(r"{build_dir}")
                print(mods["consumer"].run())
                import io as stdlib_io
                assert hasattr(stdlib_io, "StringIO"), "stdlib io clobbered"
                """)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        # Resolved to the s0ma io module, not the stdlib one.
        assert "['s0ma-io', 'x']" in proc.stdout
