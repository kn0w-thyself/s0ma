"""Tests for the ``covered_by:`` declaration field (DSL-M2, 0.8.0).

ADR-011 §(e) / design rule L-5: ``covered_by:`` is a non-empty list of
non-empty strings on nerve / cell / ganglion naming external test
evidence — suite paths or rationale prose, authored-opaque (the
language validates SHAPE only and never resolves the strings; honesty
is the author's burden and the IR makes the claim auditable).

Behavioural contract pinned here:

- Parsing: bracketed list, quoted strings or bare identifiers; the
  quote-aware comma split tolerates commas/dashes inside quotes.
- ``COVERED_BY_EMPTY`` (error in every mode): present-but-empty list,
  or any empty/whitespace entry.
- Release-gate credit: ``MISSING_TEST_COVERAGE`` is satisfied by EITHER
  in-language ``tests:`` coverage OR a non-empty ``covered_by:`` —
  proven both at the resolver and end-to-end through
  ``s0ma check --mode release`` on the on-disk fixture project (the M2
  acceptance criterion), with the negative arm asserted both ways. The
  credit injects NO synthetic test targets.
- The field rides the IR (``components[].fields.covered_by``, omitted
  when absent — L-7) and the emitted registration metadata under the
  reserved ``covered_by`` key (already a member of
  ``RESERVED_COMPONENT_METADATA_KEYS``), which is what doc-ref
  rendering reads from the registry snapshot.
- Doc-ref rendering: ``_render_entity_summary`` emits a
  ``Covered by: …`` line after the intent when present.
"""

from __future__ import annotations

import ast
from pathlib import Path

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.config import (
    ERROR_CODE_DESCRIPTIONS,
    SEVERITY_MATRIX,
    StrictnessMode,
)
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.ir.schema import RESERVED_COMPONENT_METADATA_KEYS
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.resolver.dependency import DependencyResolver
from s0ma_dsl.semantic.validator import IntraModuleValidator

_FIXTURE_PROJECT = (
    Path(__file__).parent / "fixtures" / "covered_by_release_gate"
)


def _module(nerve_fields: str = "", extra_decls: str = "") -> str:
    return (
        "module demo_cov_mod\n"
        "    layer: APPLICATION\n"
        "    version: 0.1.0\n"
        '    intent: "Pins the DSL-M2 covered_by: field behaviour."\n'
        "    exports: [demo_tool]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "nerve demo_tool :: APPLICATION\n"
        "    kind: FUNCTION\n"
        "    visibility: PUBLIC\n"
        '    intent: "Demo nerve."\n'
        '    expects: "nothing"\n'
        '    guarantees: "a dict"\n'
        '    forbids: none\n'
        "    evaluates_at: FUNCTION_BOUNDARY\n"
        "    covered_by: none\n"
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
        + nerve_fields
        + "    ---\n"
        "    def demo_tool():\n"
        "        return {}\n"
        + extra_decls
    )


def _parse(src: str):
    return parse_s0ma(src, filename="demo_cov_mod.s0ma")


def _validate(src: str, mode: StrictnessMode = StrictnessMode.DEV):
    return IntraModuleValidator(
        filename="demo_cov_mod.s0ma", mode=mode,
    ).validate(_parse(src))


# ---------------------------------------------------------------------------
# Parsing + shape validation
# ---------------------------------------------------------------------------


class TestCoveredByParsing:
    def test_quoted_and_bare_entries(self) -> None:
        src = _module(
            '    covered_by: ["tests/test_x.py — suite, with comma", wheel_smoke]\n',
        )
        mod = _parse(src)
        assert mod.nerves[0].covered_by == (
            "tests/test_x.py — suite, with comma",
            "wheel_smoke",
        )

    def test_absent_field_is_empty_tuple(self) -> None:
        mod = _parse(_module())
        assert mod.nerves[0].covered_by == ()

    def test_cell_and_ganglion_accept_the_field(self) -> None:
        src = _module(
            "",
            extra_decls=(
                "\n"
                "cell Payload :: APPLICATION\n"
                "    kind: MODEL\n"
                "    visibility: PUBLIC\n"
                '    intent: "Covered cell."\n'
                '    schema: "payload"\n'
                '    invariants: none\n'
                '    covered_by: ["tests/test_payload.py"]\n'
                "    ---\n"
                "    class Payload:\n"
                "        pass\n"
                "\n"
                "ganglion watcher :: APPLICATION\n"
                "    visibility: INTERNAL\n"
                '    intent: "Covered ganglion."\n'
                "    observes: [demo_tool]\n"
                "    scope: SUBSYSTEM\n"
                '    priors: "none"\n'
                '    on_anomaly: "log"\n'
                '    forbids: none\n'
                '    depends_on: none\n'
                '    covered_by: ["tests/test_watcher.py"]\n'
                "    ---\n"
                "    def watcher():\n"
                "        return demo_tool\n"
            ),
        )
        mod = _parse(src)
        assert mod.cells[0].covered_by == ("tests/test_payload.py",)
        assert mod.ganglia[0].covered_by == ("tests/test_watcher.py",)

    def test_covered_by_empty_variants(self) -> None:
        for variant in (
            "    covered_by: []\n",
            '    covered_by: ["", "x"]\n',
            '    covered_by: ["   "]\n',
        ):
            errors = _validate(_module(variant))
            codes = [e.code for e in errors]
            assert codes == ["COVERED_BY_EMPTY"], (variant, codes)
            assert errors[0].severity == "error"

    def test_matrix_and_description_registration(self) -> None:
        assert "COVERED_BY_EMPTY" in SEVERITY_MATRIX
        assert all(
            SEVERITY_MATRIX["COVERED_BY_EMPTY"][mode] == "error"
            for mode in StrictnessMode
        )
        assert "COVERED_BY_EMPTY" in ERROR_CODE_DESCRIPTIONS


# ---------------------------------------------------------------------------
# IR + emitted metadata ride
# ---------------------------------------------------------------------------


class TestCoveredByIRAndEmission:
    def test_ir_field_present_when_authored_absent_otherwise(self) -> None:
        src = _module('    covered_by: ["tests/test_x.py"]\n')
        doc = build_ir(_parse(src), source_text=src).to_dict()
        assert doc["components"][0]["fields"]["covered_by"] == {
            "state": "value",
            "value": ["tests/test_x.py"],
        }
        src_plain = _module()
        doc_plain = build_ir(_parse(src_plain), source_text=src_plain).to_dict()
        assert doc_plain["components"][0]["fields"]["covered_by"] == {
            "state": "none",
        }

    def test_reserved_metadata_key_membership_and_emission(self) -> None:
        assert "covered_by" in RESERVED_COMPONENT_METADATA_KEYS
        src = _module('    covered_by: ["tests/test_x.py", wheel_smoke]\n')
        emitted = PythonEmitter(module_name="demo_cov_mod").emit(_parse(src))
        ast.parse(emitted)
        assert (
            '"covered_by": ["tests/test_x.py", "wheel_smoke"]'
        ) in emitted

    def test_authored_metadata_cannot_spoof_the_reserved_key(self) -> None:
        src = _module(
            "    metadata:\n"
            '        covered_by: ["spoofed"]\n',
        )
        errors = _validate(src)
        assert [e.code for e in errors] == ["METADATA_RESERVED_KEY"]

    def test_emitted_module_registers_covered_by_metadata(self) -> None:
        """Exec against a FRESH non-persistent registry (swap via
        ``set_registry``, restore in ``finally``) — the default
        singleton persists to ``.s0ma/registry.db`` and a leaked
        registration collides on the NEXT pytest run."""
        src = _module('    covered_by: ["tests/test_x.py"]\n')
        emitted = PythonEmitter(module_name="demo_cov_mod").emit(_parse(src))
        from s0ma.registry import ComponentRegistry, get_registry, set_registry

        previous = get_registry(persist=False)
        set_registry(ComponentRegistry(persist=False))
        try:
            namespace: dict = {"__name__": "demo_cov_mod_exec"}
            exec(compile(emitted, "demo_cov_mod.py", "exec"), namespace)
            spec = namespace["demo_tool"].__component__
            assert spec.metadata["covered_by"] == ["tests/test_x.py"]
        finally:
            set_registry(previous)


# ---------------------------------------------------------------------------
# Release-gate credit — resolver level + end-to-end CLI fixture
# ---------------------------------------------------------------------------


class TestReleaseGateCredit:
    def test_resolver_credits_covered_by(self) -> None:
        src = _module('    covered_by: ["tests/test_x.py"]\n')
        errors = DependencyResolver(mode=StrictnessMode.RELEASE).resolve(
            {"demo_cov_mod": _parse(src)}, check_imports=False,
        )
        assert [e for e in errors if e.code == "MISSING_TEST_COVERAGE"] == []

    def test_resolver_negative_arm_names_the_third_option(self) -> None:
        errors = DependencyResolver(mode=StrictnessMode.RELEASE).resolve(
            {"demo_cov_mod": _parse(_module())}, check_imports=False,
        )
        missing = [e for e in errors if e.code == "MISSING_TEST_COVERAGE"]
        assert len(missing) == 1
        assert "covered_by" in missing[0].remediation

    def test_fixture_project_passes_mode_release_via_cli(self) -> None:
        """The M2 acceptance criterion: a PUBLIC nerve with covered_by
        and NO tests: coverage passes ``s0ma check --mode release``."""
        cli = S0maCLI()
        rc = cli.run([
            "check", str(_FIXTURE_PROJECT / "gated.s0ma"),
            "--mode", "release",
        ])
        assert rc == EXIT_SUCCESS

    def test_fixture_negative_arm_fails_mode_release_via_cli(
        self, tmp_path: Path,
    ) -> None:
        source = (_FIXTURE_PROJECT / "gated.s0ma").read_text(encoding="utf-8")
        lines = [
            line for line in source.split("\n")
            if "covered_by:" not in line
        ]
        stripped = tmp_path / "gated.s0ma"
        stripped.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        cli = S0maCLI()
        rc = cli.run(["check", str(stripped), "--mode", "release"])
        assert rc != EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Doc-ref rendering
# ---------------------------------------------------------------------------


class TestCoveredByDocRendering:
    def test_entity_summary_renders_covered_by_line(self) -> None:
        from s0ma_dsl.codegen.doc_emitter.markdown import (
            _render_entity_summary,
        )
        from s0ma_dsl.resolver.doc_resolver import build_project_index

        src = _module('    covered_by: ["tests/test_x.py — suite"]\n')
        index = build_project_index({"demo_cov_mod": _parse(src)})
        entity = index.lookup("nerve", "demo_tool")
        assert entity is not None
        assert entity.fields["covered_by"] == ("tests/test_x.py — suite",)
        lines = _render_entity_summary(entity)
        assert "Covered by: tests/test_x.py — suite" in lines

    def test_snapshot_index_surfaces_covered_by_from_metadata(self) -> None:
        """The doc index builds from the registry snapshot, where the
        claim rides ``spec.metadata['covered_by']`` (``ComponentSpec``
        has no covered_by attribute for the getattr walk)."""
        from s0ma_dsl.resolver.doc_resolver import ProjectIndex

        class _Spec:
            kind = "FUNCTION"
            visibility = "PUBLIC"
            intent = "Demo."
            module_path = "pkg.demo_cov_mod"
            metadata = {"covered_by": ["tests/test_x.py"]}

        class _Snapshot:
            modules: dict = {}
            components = {"demo_tool": _Spec()}
            test_registrations: dict = {}
            examples: dict = {}

        index = ProjectIndex.from_snapshot(_Snapshot())
        entity = index.lookup("nerve", "demo_tool")
        assert entity is not None
        assert entity.fields["covered_by"] == ["tests/test_x.py"]
