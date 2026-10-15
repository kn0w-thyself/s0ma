"""Tests for the deterministic JSON renderer (plan M6)."""

from __future__ import annotations

import json
from pathlib import Path

from s0ma_dsl.codegen.doc_emitter import (
    compute_doc_hashes,
    render_module_docs,
)
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.resolver.doc_resolver import build_project_index

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "valid" / "docs" / "render_formats"


def _parse_project(fixture_dir: Path) -> dict:
    modules = {}
    for s0ma_file in sorted(fixture_dir.glob("*.s0ma")):
        module = parse_s0ma(s0ma_file.read_text(), filename=str(s0ma_file))
        modules[module.module.name] = module
    return modules


def _render_json(name: str, fixture_dir: Path, base_dir: Path) -> dict:
    modules = _parse_project(fixture_dir)
    hashes = compute_doc_hashes(modules)
    index = build_project_index(modules)

    for module in modules.values():
        for out in render_module_docs(
            module, index=index, hashes=hashes, base_dir=base_dir,
        ):
            if out.name == name and out.format == "json":
                return json.loads(out.content)
    raise AssertionError(f"no JSON output named {name}")


class TestJsonStructure:
    def test_top_level_has_hash_and_meta(self, tmp_path: Path) -> None:
        doc = _render_json("greetings_json", FIXTURE_DIR, tmp_path)
        assert "_hash" in doc
        assert "_meta" in doc
        assert doc["_hash"].startswith("1:")
        # Front-matter fields are mirrored in _meta. JSON emission
        # sorts keys alphabetically for byte-determinism, so the order
        # is the alphabetical projection of the canonical FrontmatterFields
        # set rather than the source declaration order.
        meta_keys = list(doc["_meta"].keys())
        # DSL-M4 (ADR-011 §(f)) dropped ``transpiler_version``.
        assert set(meta_keys) == {
            "s0ma_kind",
            "name",
            "module",
            "format",
            "intent",
            "schema_version",
            "content_hash",
        }
        # Alphabetical sort is what makes the JSON file deterministic.
        assert meta_keys == sorted(meta_keys)

    def test_doc_ref_carries_covers_and_sections(
        self, tmp_path: Path,
    ) -> None:
        doc = _render_json("greetings_json", FIXTURE_DIR, tmp_path)
        assert "covers" in doc
        assert "sections" in doc
        # The single covers filter targets the nerve kind.
        assert any(c["target_kind"] == "nerve" for c in doc["covers"])
        # The bare-field `intent` section appears with at least one entry.
        intent_sections = [s for s in doc["sections"] if s.get("field") == "intent"]
        assert intent_sections
        assert intent_sections[0]["entries"]


class TestJsonDeterminism:
    def test_render_byte_equal(self, tmp_path: Path) -> None:
        modules = _parse_project(FIXTURE_DIR)
        hashes = compute_doc_hashes(modules)
        index = build_project_index(modules)

        def _render() -> str:
            for module in modules.values():
                for out in render_module_docs(
                    module, index=index, hashes=hashes, base_dir=tmp_path,
                ):
                    if out.name == "greetings_json":
                        return out.content
            raise AssertionError("greetings_json missing")

        assert _render() == _render()

    def test_json_keys_are_sorted(self, tmp_path: Path) -> None:
        # Re-decode without sorting; key order in the file must already
        # match a sorted order at every level.
        modules = _parse_project(FIXTURE_DIR)
        hashes = compute_doc_hashes(modules)
        index = build_project_index(modules)

        for module in modules.values():
            for out in render_module_docs(
                module, index=index, hashes=hashes, base_dir=tmp_path,
            ):
                if out.format != "json":
                    continue
                # json.loads preserves insertion order in Python 3.7+;
                # sorting the parsed dict and re-serialising must yield
                # the same bytes if the original was sorted.
                parsed = json.loads(out.content)
                resorted = json.dumps(parsed, indent=2, sort_keys=True) + "\n"
                assert resorted == out.content
