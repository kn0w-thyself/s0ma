"""Tests for POST-12a + POST-12f (M-17, 0.16.0):

- **POST-12a — ``expected_exceptions:`` on nerves.** Declarative metadata
  for Python-side exceptions caught by design (distinct from ``raises:``
  which is restricted to s0ma cells). The field has no validation side
  effect today; it is metadata for downstream tooling and authors-of-
  future-validators.

- **POST-12f — ``deferred:`` annotation on stubs.** A nerve / cell /
  ganglion can carry ``deferred: "<reason>"`` to mark its body as a
  stub awaiting fill. ``s0ma deferred-surface`` (and the
  ``s0ma check --report-deferred`` flag) enumerate every deferred
  declaration with its reason.

Behavioural contract pinned here:

- ``expected_exceptions: [json.JSONDecodeError, urllib.error.HTTPError]``
  parses to ``NerveDecl.expected_exceptions == (
  "json.JSONDecodeError", "urllib.error.HTTPError")``. Block form
  parses identically (PRE-7 block-list re-assembler).
- The dotted Python path round-trips unmodified — the parser does
  NOT enforce that entries name actual s0ma cells.
- The field rides through the IR
  (``components[].fields.expected_exceptions``) and surfaces in the
  emitted ``metadata={...}`` dict on the ``@component`` call.
- ``deferred:`` parses on nerve / cell / ganglion to the matching
  ``.deferred`` attribute.
- The reason string round-trips through the IR
  (``components[].fields.deferred``) and surfaces in the emitted
  ``metadata={...}`` dict.
- ``s0ma inspect`` text output flags deferred declarations with a
  ``deferred`` tag in the bracket label and renders the reason on
  its own sub-line. Expected exceptions render as a dedicated
  sub-section.
- ``s0ma check --report-deferred`` and the standalone
  ``s0ma deferred-surface`` subcommand enumerate every deferred
  declaration. Both always exit 0 (informational, never a build
  blocker).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from typing import TYPE_CHECKING

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

# ---------------------------------------------------------------------------
# Source-builder helpers
# ---------------------------------------------------------------------------


def _nerve_module(
    extra_nerve_fields: str = "",
    *,
    module_name: str = "demo_nerve_mod",
) -> str:
    """Return a minimal ``.s0ma`` source defining one nerve.

    The nerve is named ``demo_nerve``; the module exports it.
    Additional optional fields can be appended via
    ``extra_nerve_fields``.
    """
    return (
        f"module {module_name}\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Test module pinning POST-12a/f behaviour."\n'
        "    exports: [demo_nerve]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "nerve demo_nerve :: APPLICATION\n"
        "    kind: SERVICE\n"
        "    visibility: PUBLIC\n"
        '    intent: "Demo nerve exercising the new fields."\n'
        '    expects: "an input dict"\n'
        '    guarantees: "returns a dict"\n'
        '    forbids: none\n'
        "    evaluates_at: FUNCTION_BOUNDARY\n"
        "    provides: none\n"
        "    returns: none\n"
        "    raises: none\n"
        "    interface: none\n"
        "    latency_ms: none\n"
        "    depends_on: none\n"
        "    internal: none\n"
        "    expected_exceptions: none\n"
        "    consumes_via_dict: none\n"
        "    declares_attributes: none\n"
        "    covered_by: none\n"
        + extra_nerve_fields
        + "    ---\n"
        "    def demo_nerve():\n"
        "        return {}\n"
    )


def _cell_module(extra_cell_fields: str = "") -> str:
    """Return a minimal ``.s0ma`` source defining one cell."""
    return (
        "module demo_cell_mod\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Test module pinning the POST-12f deferred field."\n'
        "    exports: [DemoCell]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "cell DemoCell :: APPLICATION\n"
        "    kind: MODEL\n"
        "    visibility: PUBLIC\n"
        '    intent: "Demo cell exercising the deferred field."\n'
        '    schema: "demo schema describing the cell."\n'
        '    invariants: none\n'
        '    covered_by: none\n'
        + extra_cell_fields
        + "    ---\n"
        "    class DemoCell:\n"
        "        pass\n"
    )


def _ganglion_module(extra_ganglion_fields: str = "") -> str:
    """Return a minimal ``.s0ma`` source defining one ganglion."""
    return (
        "module demo_ganglion_mod\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Test module pinning the POST-12f deferred field."\n'
        "    exports: [demo_ganglion]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "ganglion demo_ganglion :: APPLICATION\n"
        "    visibility: PUBLIC\n"
        '    intent: "Demo ganglion exercising the deferred field."\n'
        "    observes: [some_pattern]\n"
        "    scope: FUNCTION_BOUNDARY\n"
        '    priors: "no prior signals"\n'
        '    on_anomaly: "log and continue"\n'
        '    forbids: none\n'
        '    depends_on: none\n'
        '    covered_by: none\n'
        + extra_ganglion_fields
        + "    ---\n"
        "    def demo_ganglion():\n"
        "        pass\n"
    )


# ---------------------------------------------------------------------------
# POST-12a — ``expected_exceptions:`` on nerves
# ---------------------------------------------------------------------------


class TestExpectedExceptionsParsing:
    """``expected_exceptions:`` parses to the right tuple on NerveDecl."""

    def test_inline_form_parses(self) -> None:
        """Inline ``expected_exceptions: [a, b]`` form parses."""
        src = _nerve_module(
            "    expected_exceptions: [json.JSONDecodeError, urllib.error.HTTPError]\n"
        )
        module = parse_s0ma(src, filename="inline.s0ma")
        assert module.nerves[0].expected_exceptions == (
            "json.JSONDecodeError",
            "urllib.error.HTTPError",
        )

    def test_block_form_parses(self) -> None:
        """Block ``- a`` / ``- b`` form parses identically."""
        src = _nerve_module(
            "    expected_exceptions:\n"
            "      - json.JSONDecodeError\n"
            "      - urllib.error.HTTPError\n"
        )
        module = parse_s0ma(src, filename="block.s0ma")
        assert module.nerves[0].expected_exceptions == (
            "json.JSONDecodeError",
            "urllib.error.HTTPError",
        )

    def test_dotted_python_paths_round_trip_unchanged(self) -> None:
        """Dotted paths (``json.JSONDecodeError``) round-trip verbatim.

        The parser must not collapse, rewrite, or resolve dotted
        entries — the field is metadata for Python types, not s0ma
        component references.
        """
        src = _nerve_module(
            "    expected_exceptions: [json.JSONDecodeError, "
            "urllib.error.HTTPError, requests.exceptions.Timeout]\n"
        )
        module = parse_s0ma(src, filename="dotted.s0ma")
        assert module.nerves[0].expected_exceptions == (
            "json.JSONDecodeError",
            "urllib.error.HTTPError",
            "requests.exceptions.Timeout",
        )

    def test_omitted_leaves_field_empty(self) -> None:
        """A nerve with no ``expected_exceptions:`` parses with the empty tuple."""
        src = _nerve_module()
        module = parse_s0ma(src, filename="absent.s0ma")
        assert module.nerves[0].expected_exceptions == ()

    def test_no_validation_against_s0ma_namespace(self) -> None:
        """Entries are Python types, NOT s0ma cells — no namespace check.

        The contrast with ``raises:`` (which is restricted to s0ma
        cells) is the whole point of the new field; the parser /
        validator must accept dotted Python paths even when no cell
        with that name exists.
        """
        # No cell or class named "BuiltinException" exists anywhere
        # in the module — the parser must accept the entry anyway.
        src = _nerve_module(
            "    expected_exceptions: [json.JSONDecodeError, "
            "some.deeply.nested.Custom]\n"
        )
        module = parse_s0ma(src, filename="no_namespace.s0ma")
        assert module.nerves[0].expected_exceptions == (
            "json.JSONDecodeError",
            "some.deeply.nested.Custom",
        )


class TestExpectedExceptionsIRRoundTrip:
    """The expected_exceptions list rides through the IR builder."""

    def test_ir_carries_expected_exceptions_list(self) -> None:
        src = _nerve_module(
            "    expected_exceptions: [json.JSONDecodeError]\n"
        )
        module = parse_s0ma(src, filename="ir.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        assert (
            ir_dict["components"][0]["fields"]["expected_exceptions"]
            == {
                "state": "value",
                "value": ["json.JSONDecodeError"],
            }
        )

    def test_absent_expected_exceptions_omitted_from_ir(self) -> None:
        src = _nerve_module()
        module = parse_s0ma(src, filename="absent_ir.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        assert ir_dict["components"][0]["fields"]["expected_exceptions"] == {
            "state": "none",
        }

    def test_ir_round_trips_through_json(self) -> None:
        """``json.dumps`` / ``json.loads`` round-trips the list."""
        src = _nerve_module(
            "    expected_exceptions: [json.JSONDecodeError, ValueError]\n"
        )
        module = parse_s0ma(src, filename="json_round.s0ma")
        doc = build_ir(module, source_text=src)
        rehydrated = json.loads(json.dumps(doc.to_dict()))
        assert (
            rehydrated["components"][0]["fields"]["expected_exceptions"]
            == {
                "state": "value",
                "value": ["json.JSONDecodeError", "ValueError"],
            }
        )


class TestExpectedExceptionsEmittedInMetadata:
    """Emitted Python carries ``"expected_exceptions": [...]`` in metadata."""

    def test_expected_exceptions_in_metadata(self) -> None:
        src = _nerve_module(
            "    expected_exceptions: [json.JSONDecodeError, urllib.error.HTTPError]\n"
        )
        module = parse_s0ma(src, filename="emit.s0ma")
        emitter = PythonEmitter(module_name="demo_nerve_mod")
        py_source = emitter.emit(module)
        assert '"expected_exceptions"' in py_source
        assert '"json.JSONDecodeError"' in py_source
        assert '"urllib.error.HTTPError"' in py_source

    def test_absent_expected_exceptions_omitted_from_metadata(self) -> None:
        src = _nerve_module()
        module = parse_s0ma(src, filename="emit_absent.s0ma")
        emitter = PythonEmitter(module_name="demo_nerve_mod")
        py_source = emitter.emit(module)
        assert '"expected_exceptions"' not in py_source


# ---------------------------------------------------------------------------
# POST-12f — ``deferred:`` annotation on stubs
# ---------------------------------------------------------------------------


class TestDeferredParsing:
    """``deferred:`` parses on nerve, cell, and ganglion declarations."""

    def test_deferred_on_nerve_parses(self) -> None:
        src = _nerve_module(
            '    deferred: "waiting on Phase 3 spec finalisation"\n'
        )
        module = parse_s0ma(src, filename="nerve_def.s0ma")
        assert (
            module.nerves[0].deferred
            == "waiting on Phase 3 spec finalisation"
        )

    def test_deferred_on_cell_parses(self) -> None:
        src = _cell_module('    deferred: "schema reviewer signoff pending"\n')
        module = parse_s0ma(src, filename="cell_def.s0ma")
        assert module.cells[0].deferred == "schema reviewer signoff pending"

    def test_deferred_on_ganglion_parses(self) -> None:
        src = _ganglion_module(
            '    deferred: "need observability decisions"\n'
        )
        module = parse_s0ma(src, filename="gang_def.s0ma")
        assert module.ganglia[0].deferred == "need observability decisions"

    def test_omitted_deferred_is_none(self) -> None:
        """No ``deferred:`` line → attribute defaults to ``None``."""
        assert parse_s0ma(
            _nerve_module(), filename="n_abs.s0ma",
        ).nerves[0].deferred is None
        assert parse_s0ma(
            _cell_module(), filename="c_abs.s0ma",
        ).cells[0].deferred is None
        assert parse_s0ma(
            _ganglion_module(), filename="g_abs.s0ma",
        ).ganglia[0].deferred is None


class TestDeferredIRRoundTrip:
    """The deferred reason rides through the IR for all three decl types."""

    def test_nerve_deferred_in_ir(self) -> None:
        src = _nerve_module('    deferred: "Phase 3 fill"\n')
        module = parse_s0ma(src, filename="ir_n.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        assert ir_dict["components"][0]["fields"]["deferred"] == "Phase 3 fill"

    def test_cell_deferred_in_ir(self) -> None:
        src = _cell_module('    deferred: "schema review"\n')
        module = parse_s0ma(src, filename="ir_c.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        assert ir_dict["components"][0]["fields"]["deferred"] == "schema review"

    def test_ganglion_deferred_in_ir(self) -> None:
        src = _ganglion_module('    deferred: "observability TBD"\n')
        module = parse_s0ma(src, filename="ir_g.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        assert (
            ir_dict["components"][0]["fields"]["deferred"]
            == "observability TBD"
        )

    def test_absent_deferred_omitted_from_ir(self) -> None:
        src = _nerve_module()
        module = parse_s0ma(src, filename="ir_abs.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = doc.to_dict()
        assert "deferred" not in ir_dict["components"][0]["fields"]


class TestDeferredEmittedInMetadata:
    """Emitted Python carries ``"deferred": "..."`` in the metadata dict."""

    def test_deferred_on_nerve_in_metadata(self) -> None:
        src = _nerve_module('    deferred: "phase 3"\n')
        module = parse_s0ma(src, filename="emit_n.s0ma")
        emitter = PythonEmitter(module_name="demo_nerve_mod")
        py_source = emitter.emit(module)
        assert '"deferred": "phase 3"' in py_source

    def test_deferred_on_cell_in_metadata(self) -> None:
        src = _cell_module('    deferred: "review"\n')
        module = parse_s0ma(src, filename="emit_c.s0ma")
        emitter = PythonEmitter(module_name="demo_cell_mod")
        py_source = emitter.emit(module)
        assert '"deferred": "review"' in py_source

    def test_deferred_on_ganglion_in_metadata(self) -> None:
        src = _ganglion_module('    deferred: "obs"\n')
        module = parse_s0ma(src, filename="emit_g.s0ma")
        emitter = PythonEmitter(module_name="demo_ganglion_mod")
        py_source = emitter.emit(module)
        assert '"deferred": "obs"' in py_source


# ---------------------------------------------------------------------------
# s0ma inspect text output
# ---------------------------------------------------------------------------


class TestInspectSurfacesDeferredAndExpectedExceptions:
    """``s0ma inspect`` text output reveals both new fields."""

    def test_inspect_flags_deferred_in_bracket_label(self) -> None:
        src = _nerve_module(
            '    deferred: "waiting on Phase 3 fill"\n'
        )
        module = parse_s0ma(src, filename="ins_n.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = json.loads(json.dumps(doc.to_dict()))

        cli = S0maCLI()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_inspect_text(ir_dict)
        output = buf.getvalue()

        # The deferred flag appears in the bracket label.
        assert "deferred" in output
        # The reason renders in its own sub-section.
        assert "Deferred: waiting on Phase 3 fill" in output

    def test_inspect_surfaces_expected_exceptions(self) -> None:
        src = _nerve_module(
            "    expected_exceptions: [json.JSONDecodeError, urllib.error.HTTPError]\n"
        )
        module = parse_s0ma(src, filename="ins_ee.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = json.loads(json.dumps(doc.to_dict()))

        cli = S0maCLI()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_inspect_text(ir_dict)
        output = buf.getvalue()

        # Both Python paths render in a single dedicated sub-section.
        assert "Expected exceptions:" in output
        assert "json.JSONDecodeError" in output
        assert "urllib.error.HTTPError" in output

    def test_inspect_absent_fields_omit_subsections(self) -> None:
        src = _nerve_module()
        module = parse_s0ma(src, filename="ins_abs.s0ma")
        doc = build_ir(module, source_text=src)
        ir_dict = json.loads(json.dumps(doc.to_dict()))

        cli = S0maCLI()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_inspect_text(ir_dict)
        output = buf.getvalue()

        assert "Expected exceptions" not in output
        assert "Deferred:" not in output
        # Plain bracket label has no ``deferred`` tag.
        assert "[PUBLIC SERVICE nerve]" in output


# ---------------------------------------------------------------------------
# s0ma deferred-surface + s0ma check --report-deferred
# ---------------------------------------------------------------------------


def _scaffold_deferred_project(root: Path) -> None:
    """Lay down a project with mixed deferred / non-deferred declarations.

    Three modules, each contributing one deferred declaration so the
    reporter has the full nerve / cell / ganglion spread to enumerate.
    A fourth (non-deferred) nerve confirms the reporter only lists
    deferred-marked entries.
    """
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    # Module 1: deferred nerve + plain nerve (only the deferred one
    # should appear in the report). File stem must match the declared
    # module name (MODULE_NAME_STEM_MISMATCH).
    (src / "a_mod.s0ma").write_text(
        "module a_mod\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Module A — has deferred nerve."\n'
        "    exports: [a_deferred, a_plain]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "nerve a_deferred :: APPLICATION\n"
        "    kind: SERVICE\n"
        "    visibility: PUBLIC\n"
        '    intent: "Deferred nerve."\n'
        '    expects: "x"\n'
        '    guarantees: "y"\n'
        '    forbids: none\n'
        "    evaluates_at: FUNCTION_BOUNDARY\n"
        "    provides: none\n"
        "    returns: none\n"
        "    raises: none\n"
        "    interface: none\n"
        "    latency_ms: none\n"
        "    depends_on: none\n"
        "    internal: none\n"
        "    expected_exceptions: none\n"
        "    consumes_via_dict: none\n"
        "    declares_attributes: none\n"
        "    covered_by: none\n"
        '    deferred: "needs reviewer signoff"\n'
        "    ---\n"
        "    def a_deferred():\n"
        "        return {}\n"
        "\n"
        "nerve a_plain :: APPLICATION\n"
        "    kind: SERVICE\n"
        "    visibility: PUBLIC\n"
        '    intent: "Non-deferred nerve."\n'
        '    expects: "x"\n'
        '    guarantees: "y"\n'
        '    forbids: none\n'
        "    evaluates_at: FUNCTION_BOUNDARY\n"
        "    provides: none\n"
        "    returns: none\n"
        "    raises: none\n"
        "    interface: none\n"
        "    latency_ms: none\n"
        "    depends_on: none\n"
        "    internal: none\n"
        "    expected_exceptions: none\n"
        "    consumes_via_dict: none\n"
        "    declares_attributes: none\n"
        "    covered_by: none\n"
        "    ---\n"
        "    def a_plain():\n"
        "        return {}\n",
        encoding="utf-8",
    )
    # Module 2: deferred cell.
    (src / "b_mod.s0ma").write_text(
        "module b_mod\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Module B — has deferred cell."\n'
        "    exports: [BDeferred]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "cell BDeferred :: APPLICATION\n"
        "    kind: MODEL\n"
        "    visibility: PUBLIC\n"
        '    intent: "Deferred cell."\n'
        '    schema: "demo schema."\n'
        '    invariants: none\n'
        '    covered_by: none\n'
        '    deferred: "schema review pending"\n'
        "    ---\n"
        "    class BDeferred:\n"
        "        pass\n",
        encoding="utf-8",
    )
    # Module 3: deferred ganglion.
    (src / "c_mod.s0ma").write_text(
        "module c_mod\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Module C — has deferred ganglion."\n'
        "    exports: [c_ganglion]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "ganglion c_ganglion :: APPLICATION\n"
        "    visibility: PUBLIC\n"
        '    intent: "Deferred ganglion."\n'
        "    observes: [pattern_x]\n"
        "    scope: FUNCTION_BOUNDARY\n"
        '    priors: "none"\n'
        '    on_anomaly: "log"\n'
        '    forbids: none\n'
        '    depends_on: none\n'
        '    covered_by: none\n'
        '    deferred: "observability decisions pending"\n'
        "    ---\n"
        "    def c_ganglion():\n"
        "        pass\n",
        encoding="utf-8",
    )
    pyproject = (
        '[project]\n'
        'name = "deferred_proj"\n'
        'version = "0.0.1"\n'
        '\n'
        '[tool.s0ma]\n'
        'source_roots = ["src"]\n'
        'test_roots = ["tests"]\n'
        'build_dir = "build"\n'
        'bootstrap_files = []\n'
    )
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")


class TestDeferredSurfaceCLI:
    """``s0ma check --report-deferred`` + ``s0ma deferred-surface`` reporters."""

    def test_check_report_deferred_lists_every_deferred_decl(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _scaffold_deferred_project(tmp_path)
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(tmp_path),
            "check", str(tmp_path / "src"),
            "--mode", "dev",
            "--report-deferred",
        ])
        # ``--report-deferred`` is informational — exit must stay 0
        # whenever there are no actual errors. The fixture has none.
        assert rc == EXIT_SUCCESS
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        # Every deferred declaration appears with its module-qualified
        # name and a "reason:" line.
        assert "a_deferred" in combined
        assert "BDeferred" in combined
        assert "c_ganglion" in combined
        assert "needs reviewer signoff" in combined
        assert "schema review pending" in combined
        assert "observability decisions pending" in combined
        # The non-deferred nerve is not listed under the deferred
        # surface (it still passes through ``s0ma check`` of course).
        assert "Deferred surface" in combined
        # Sanity check: the deferred-surface section's count line
        # carries the right total.
        assert "3 declaration(s)" in combined

    def test_check_report_deferred_exits_zero_even_when_present(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Deferred declarations are explicitly NOT a build blocker."""
        _scaffold_deferred_project(tmp_path)
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(tmp_path),
            "check", str(tmp_path / "src"),
            "--mode", "dev",
            "--report-deferred",
        ])
        assert rc == EXIT_SUCCESS

    def test_deferred_surface_subcommand_lists_every_decl(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _scaffold_deferred_project(tmp_path)
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(tmp_path),
            "deferred-surface", str(tmp_path / "src"),
        ])
        assert rc == EXIT_SUCCESS
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "a_deferred" in combined
        assert "BDeferred" in combined
        assert "c_ganglion" in combined

    def test_deferred_surface_json_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--format json`` emits a parseable envelope."""
        _scaffold_deferred_project(tmp_path)
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(tmp_path),
            "deferred-surface", str(tmp_path / "src"),
            "--format", "json",
        ])
        assert rc == EXIT_SUCCESS
        captured = capsys.readouterr()
        # The JSON envelope is the entire stdout (the subcommand
        # emits nothing else when --format json is set).
        payload = json.loads(captured.out)
        assert "deferred" in payload
        names = {entry["name"] for entry in payload["deferred"]}
        assert names == {"a_deferred", "BDeferred", "c_ganglion"}
        decl_types = {
            entry["declaration_type"] for entry in payload["deferred"]
        }
        assert decl_types == {"nerve", "cell", "ganglion"}

    def test_deferred_surface_empty_project_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A project with zero deferred declarations renders a friendly empty notice."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "plain_mod.s0ma").write_text(
            _nerve_module(module_name="plain_mod"),
            encoding="utf-8",
        )
        (tmp_path / "pyproject.toml").write_text(
            '[project]\n'
            'name = "plain_proj"\n'
            'version = "0.0.1"\n'
            '\n'
            '[tool.s0ma]\n'
            'source_roots = ["src"]\n'
            'test_roots = ["tests"]\n'
            'build_dir = "build"\n'
            'bootstrap_files = []\n',
            encoding="utf-8",
        )
        cli = S0maCLI()
        rc = cli.run([
            "--project-root", str(tmp_path),
            "deferred-surface", str(tmp_path / "src"),
        ])
        assert rc == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert "no deferred:-marked declarations found" in captured.out
