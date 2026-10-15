"""End-to-end tests for the M5 doc-subsystem emitter, IR, and runtime bridge.

Covers PRD §2.2 declaration behavior, plan §M5 deliverables:

- ``register_doc_ref`` / ``register_doc_guide`` / ``register_example`` calls
  appear in the generated ``.py``.
- ``__s0ma_doc_ref__`` / ``__s0ma_doc_guide__`` / ``__s0ma_example__``
  module-level marker tuples are emitted for the import-hook contract.
- The IR document gains ``doc_refs``, ``doc_guides``, ``examples`` sections
  populated from structured AST fields (per the M2 handoff: ``raw`` is
  debug-only and is excluded from the IR).
- Schema version is ``3.0.0`` (0.14 M3A: tagged semantic state.
  Before that, the s0ma consolidation M3's 2.0.0: breaking extension-family
  + hash-marker rename. History: additive — M5 bumped to ``1.1.0``;
  M13 / feedback 5–6 bumped to ``1.2.0`` for the helpers section;
  POST-5 / 0.16.0 bumped to ``1.3.0`` for the integrations section).
- Importing the generated Python registers the declarations into the
  s0ma framework registry, validating the runtime-bridge adapters.
- Source maps cover doc declarations.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import s0ma

from s0ma_dsl.codegen.python_emitter import emit_python
from s0ma_dsl.codegen.source_map import generate_source_map
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma

FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "valid" / "docs" / "full_project"
)


def _parse_fixture(name: str):
    path = FIXTURE_ROOT / name
    return parse_s0ma(path.read_text(encoding="utf-8"), str(path)), path


# ---------------------------------------------------------------------------
# Python emission
# ---------------------------------------------------------------------------


class TestEmitterDocCalls:
    def test_doc_ref_call_emitted(self):
        module, _ = _parse_fixture("greetings_docs.s0ma")
        out = emit_python(module)
        assert "register_doc_ref(" in out
        assert 'name="greetings_api_reference"' in out
        assert 'format="markdown"' in out
        assert 'output="docs/greetings_reference.md"' in out

    def test_doc_guide_call_emitted(self):
        module, _ = _parse_fixture("greetings_docs.s0ma")
        out = emit_python(module)
        assert "register_doc_guide(" in out
        assert 'name="greetings_walkthrough"' in out
        # Prose body byte-preserved.
        assert "{{nerve::greet}}" in out
        assert "{{example::greet_example}}" in out

    def test_example_call_emitted(self):
        module, _ = _parse_fixture("greetings_docs.s0ma")
        out = emit_python(module)
        assert "register_example(" in out
        assert 'name="greet_example"' in out
        assert 'runs_in="standalone"' in out

    def test_doc_marker_attributes_emitted(self):
        module, _ = _parse_fixture("greetings_docs.s0ma")
        out = emit_python(module)
        assert '__s0ma_doc_ref__ = ("greetings_api_reference",)' in out
        assert '__s0ma_doc_guide__ = ("greetings_walkthrough",)' in out
        assert '__s0ma_example__ = ("greet_example",)' in out

    def test_doc_only_module_imports_doc_registration_funcs(self):
        module, _ = _parse_fixture("greetings_docs.s0ma")
        out = emit_python(module)
        assert "register_doc_ref" in out
        assert "register_doc_guide" in out
        assert "register_example" in out

    def test_module_with_no_doc_decls_omits_marker_attrs(self):
        module, _ = _parse_fixture("greetings.s0ma")
        out = emit_python(module)
        assert "__s0ma_doc_ref__" not in out
        assert "__s0ma_doc_guide__" not in out
        assert "__s0ma_example__" not in out

    def test_emitted_python_compiles(self):
        module, _ = _parse_fixture("greetings_docs.s0ma")
        out = emit_python(module)
        # Replace the hash placeholders so the file is valid Python.
        out = out.replace("__S0MA_SOURCE_HASH__", "x").replace(
            "__S0MA_OUTPUT_HASH__", "y"
        )
        compile(out, "<emitted>", "exec")

    def test_emitter_is_deterministic(self):
        """Plan §5 — byte-equal reproducibility."""
        module, _ = _parse_fixture("greetings_docs.s0ma")
        out_a = emit_python(module)
        out_b = emit_python(module)
        assert out_a == out_b


# ---------------------------------------------------------------------------
# IR
# ---------------------------------------------------------------------------


class TestIRDocSections:
    def test_schema_version_bumped(self):
        module, path = _parse_fixture("greetings_docs.s0ma")
        doc = build_ir(module, source_text=path.read_text(encoding="utf-8"))
        # POST-5 (0.16.0) bumps the schema additively from 1.2.0 to
        # 1.3.0 to introduce the ``integrations`` section. M13
        # (feedback 5–6) bumped from 1.1.0 to 1.2.0 for the ``helpers``
        # section.
        # DSL-M1 (0.8.0) bumped 2.0.0 -> 2.1.0: additive
        # metadata/serves_as fields (ADR-011 §(g); see ir/schema.py).
        assert doc.schema_version == "3.0.0"

    def test_doc_ref_in_ir(self):
        module, path = _parse_fixture("greetings_docs.s0ma")
        doc = build_ir(module, source_text=path.read_text(encoding="utf-8"))
        assert len(doc.doc_refs) == 1
        ref = doc.doc_refs[0]
        assert ref.name == "greetings_api_reference"
        assert ref.format == "markdown"
        assert ref.output == "docs/greetings_reference.md"
        assert len(ref.covers) == 1
        assert ref.covers[0].kind == "nerve"
        assert len(ref.sections) == 3
        # Sections are bare field references — no iteration.
        for s in ref.sections:
            assert s.iteration is None
            assert s.field_name in ("intent", "expects", "guarantees")

    def test_doc_guide_in_ir(self):
        module, path = _parse_fixture("greetings_docs.s0ma")
        doc = build_ir(module, source_text=path.read_text(encoding="utf-8"))
        assert len(doc.doc_guides) == 1
        guide = doc.doc_guides[0]
        assert guide.name == "greetings_walkthrough"
        assert len(guide.covers) == 1
        assert guide.covers[0].name == "greet"
        assert len(guide.examples) == 1
        assert len(guide.asserts) == 1
        assert "{{nerve::greet}}" in guide.body

    def test_example_in_ir(self):
        module, path = _parse_fixture("greetings_docs.s0ma")
        doc = build_ir(module, source_text=path.read_text(encoding="utf-8"))
        assert len(doc.examples) == 1
        ex = doc.examples[0]
        assert ex.name == "greet_example"
        assert ex.runs_in == "standalone"
        assert len(ex.demonstrates) == 1
        assert ex.demonstrates[0].kind == "nerve"
        assert ex.demonstrates[0].name == "greet"
        # Body is dedented (no leading 4 spaces).
        assert ex.body.startswith("from greetings import greet")

    def test_ir_omits_raw_field(self):
        """M2 handoff: ``raw`` is debug-only and must NOT appear in IR."""
        module, path = _parse_fixture("greetings_docs.s0ma")
        doc = build_ir(module, source_text=path.read_text(encoding="utf-8"))
        # Serialise to JSON-compatible dict and walk it.
        import json
        json.dumps(doc.to_dict(), sort_keys=True)
        # A whitespace marker would be present iff the raw text was leaked.
        assert True
        # More precisely: structured forms expose `kind` / `target_kind` /
        # `field_path`, never a `raw` key.
        d = doc.to_dict()
        assert all("raw" not in c for c in d["doc_refs"][0]["covers"])
        for entry in d["doc_guides"][0]["covers"]:
            assert "raw" not in entry

    def test_ir_is_deterministic(self):
        """Plan §5 — same input, byte-equal IR JSON."""
        module, path = _parse_fixture("greetings_docs.s0ma")
        text = path.read_text(encoding="utf-8")
        doc_a = build_ir(module, source_text=text)
        doc_b = build_ir(module, source_text=text)
        assert json.dumps(doc_a.to_dict(), sort_keys=True) == json.dumps(
            doc_b.to_dict(), sort_keys=True
        )


# ---------------------------------------------------------------------------
# Source map
# ---------------------------------------------------------------------------


class TestSourceMapDocCoverage:
    def test_doc_decls_appear_in_source_map(self):
        module, path = _parse_fixture("greetings_docs.s0ma")
        out = emit_python(module).replace(
            "__S0MA_SOURCE_HASH__", "x"
        ).replace("__S0MA_OUTPUT_HASH__", "y")
        smap = generate_source_map(module, out, source_file=str(path))
        types = {d.type for d in smap.declarations}
        assert {"doc-ref", "doc-guide", "example"}.issubset(types)

    def test_source_map_doc_decl_names(self):
        module, path = _parse_fixture("greetings_docs.s0ma")
        out = emit_python(module).replace(
            "__S0MA_SOURCE_HASH__", "x"
        ).replace("__S0MA_OUTPUT_HASH__", "y")
        smap = generate_source_map(module, out, source_file=str(path))
        names = {d.name for d in smap.declarations}
        assert {"greetings_api_reference", "greet_example", "greetings_walkthrough"}.issubset(
            names
        )


# ---------------------------------------------------------------------------
# Runtime bridge — importing emitted code registers into the framework registry
# ---------------------------------------------------------------------------


def _build_project(tmp_path: Path) -> Path:
    """Run the CLI build over the fixture project into ``tmp_path``."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # Copy fixture sources so build can write outputs alongside them.
    for src in FIXTURE_ROOT.glob("*.s0ma"):
        (out_dir / src.name).write_text(
            src.read_text(encoding="utf-8"), encoding="utf-8"
        )
    from s0ma_dsl.cli.main import S0maCLI
    rc = S0maCLI().run(["build", str(out_dir), "--mode", "dev", "--no-cache"])
    assert rc == 0
    return out_dir


def _import_module(path: Path, module_name: str):
    """Load a generated .py file as ``module_name`` without polluting sys.path."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fresh_registry(monkeypatch):
    """Reset the s0ma global registry between tests."""
    s0ma.registry.reset_registry()
    s0ma.initialize(persist=False)
    yield s0ma.registry.get_registry(persist=False)
    s0ma.registry.reset_registry()


class TestRuntimeBridge:
    def test_import_registers_doc_ref(self, tmp_path, fresh_registry):
        out_dir = _build_project(tmp_path)
        # Run import in-process by adding to sys.path.
        sys.path.insert(0, str(out_dir))
        try:
            # Import dependency module first so nerve::greet exists.
            _import_module(out_dir / "greetings.py", "greetings")
            _import_module(out_dir / "greetings_docs.py", "greetings_docs")
            ref = fresh_registry.get_doc_ref("greetings_api_reference")
            assert ref is not None
            assert ref.module == "greetings_docs"
            assert ref.format == "markdown"
            assert ref.output == "docs/greetings_reference.md"
            assert len(ref.covers) == 1
            assert ref.covers[0].target_kind == "nerve"
        finally:
            sys.path.remove(str(out_dir))
            sys.modules.pop("greetings", None)
            sys.modules.pop("greetings_docs", None)

    def test_import_registers_doc_guide(self, tmp_path, fresh_registry):
        out_dir = _build_project(tmp_path)
        sys.path.insert(0, str(out_dir))
        try:
            _import_module(out_dir / "greetings.py", "greetings")
            _import_module(out_dir / "greetings_docs.py", "greetings_docs")
            guide = fresh_registry.get_doc_guide("greetings_walkthrough")
            assert guide is not None
            assert guide.module == "greetings_docs"
            assert len(guide.covers) == 1
            assert guide.covers[0].name == "greet"
            assert len(guide.asserts) == 1
            assert "{{nerve::greet}}" in guide.body
        finally:
            sys.path.remove(str(out_dir))
            sys.modules.pop("greetings", None)
            sys.modules.pop("greetings_docs", None)

    def test_import_registers_example(self, tmp_path, fresh_registry):
        out_dir = _build_project(tmp_path)
        sys.path.insert(0, str(out_dir))
        try:
            _import_module(out_dir / "greetings.py", "greetings")
            _import_module(out_dir / "greetings_docs.py", "greetings_docs")
            ex = fresh_registry.get_example("greet_example")
            assert ex is not None
            assert ex.runs_in == "standalone"
            assert len(ex.demonstrates) == 1
            assert ex.demonstrates[0].name == "greet"
            assert "from greetings import greet" in ex.body
        finally:
            sys.path.remove(str(out_dir))
            sys.modules.pop("greetings", None)
            sys.modules.pop("greetings_docs", None)


# ---------------------------------------------------------------------------
# DocValidator wired into the build pipeline blocks emission on errors
# ---------------------------------------------------------------------------


class TestDocValidatorWiring:
    def test_unresolved_reference_blocks_build(self, tmp_path, fresh_registry):
        # Doc-guide references nerve::greet but no nerve module is present.
        proj = tmp_path / "broken"
        proj.mkdir()
        guide_src = (
            FIXTURE_ROOT.parent / "minimal_doc_guide.s0ma"
        ).read_text(encoding="utf-8")
        (proj / "minimal_doc_guide.s0ma").write_text(guide_src, encoding="utf-8")
        from s0ma_dsl.cli.main import S0maCLI
        rc = S0maCLI().run(["build", str(proj), "--mode", "dev", "--no-cache"])
        assert rc != 0  # validation error blocked emission

    def test_clean_project_builds(self, tmp_path, fresh_registry):
        out_dir = _build_project(tmp_path)
        # Each module should have produced its three artifacts.
        for stem in ("greetings", "greetings_docs"):
            assert (out_dir / f"{stem}.py").exists()
            assert (out_dir / f"{stem}.s0ma.json").exists()
            assert (out_dir / f"{stem}.s0ma.map").exists()


# ---------------------------------------------------------------------------
# ProjectIndex.from_snapshot
# ---------------------------------------------------------------------------


class TestProjectIndexFromSnapshot:
    def test_from_snapshot_indexes_modules(self, tmp_path, fresh_registry):
        out_dir = _build_project(tmp_path)
        sys.path.insert(0, str(out_dir))
        try:
            _import_module(out_dir / "greetings.py", "greetings")
            _import_module(out_dir / "greetings_docs.py", "greetings_docs")
            snapshot = fresh_registry.snapshot()
            from s0ma_dsl.resolver.doc_resolver import ProjectIndex
            idx = ProjectIndex.from_snapshot(snapshot)
            assert idx.lookup("module", "greetings") is not None
            assert idx.lookup("example", "greet_example") is not None
        finally:
            sys.path.remove(str(out_dir))
            sys.modules.pop("greetings", None)
            sys.modules.pop("greetings_docs", None)
