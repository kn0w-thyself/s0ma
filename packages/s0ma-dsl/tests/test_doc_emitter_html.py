"""Tests for the deterministic HTML renderer (plan M6)."""

from __future__ import annotations

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


def _render_html(name: str, fixture_dir: Path, base_dir: Path) -> str:
    modules = _parse_project(fixture_dir)
    hashes = compute_doc_hashes(modules)
    index = build_project_index(modules)
    for module in modules.values():
        for out in render_module_docs(
            module, index=index, hashes=hashes, base_dir=base_dir,
        ):
            if out.name == name and out.format == "html":
                return out.content
    raise AssertionError(f"no HTML output named {name}")


class TestHtmlStructure:
    def test_html_skeleton(self, tmp_path: Path) -> None:
        html = _render_html("greetings_html", FIXTURE_DIR, tmp_path)
        assert html.startswith("<!doctype html>\n")
        assert "<html lang=\"en\">" in html
        assert "<head>" in html
        assert "</body>" in html
        assert html.endswith("</html>\n")

    def test_meta_tags_namespaced_under_s0ma(self, tmp_path: Path) -> None:
        html = _render_html("greetings_html", FIXTURE_DIR, tmp_path)
        # Every front-matter field becomes a <meta name="s0ma:..."> tag.
        assert '<meta name="s0ma:s0ma_kind" content="doc-ref">' in html
        assert '<meta name="s0ma:name" content="greetings_html">' in html
        assert 's0ma:content_hash' in html

    def test_headings_emitted(self, tmp_path: Path) -> None:
        html = _render_html("greetings_html", FIXTURE_DIR, tmp_path)
        # The Markdown body's H1 / H2 / H3 / H4 headings are translated.
        assert "<h1>greetings_html</h1>" in html
        assert "<h2>intent</h2>" in html
        assert "<h3>nerve::greet</h3>" in html


class TestHtmlReproducibility:
    def test_render_byte_equal(self, tmp_path: Path) -> None:
        a = _render_html("greetings_html", FIXTURE_DIR, tmp_path / "a")
        b = _render_html("greetings_html", FIXTURE_DIR, tmp_path / "b")
        assert a == b
