"""Tests for the deterministic Markdown renderer (plan M6).

Covers:
* Front-matter contract (every required field present, in declared order).
* Reference / example substitutions in doc-guide bodies.
* Filter resolution + section rendering for doc-refs.
* Byte-equal reproducibility (rendering the same input twice yields the
  same bytes).
* Content-hash stability with respect to changes in irrelevant components.
"""

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
    """Parse every ``.s0ma`` file under *fixture_dir* into a module dict."""
    modules = {}
    for s0ma_file in sorted(fixture_dir.glob("*.s0ma")):
        module = parse_s0ma(s0ma_file.read_text(), filename=str(s0ma_file))
        modules[module.module.name] = module
    return modules


def _render(fixture_dir: Path, base_dir: Path) -> dict[str, str]:
    """Build hashes + project index, render every doc, return name → content."""
    modules = _parse_project(fixture_dir)
    hashes = compute_doc_hashes(
        modules, filenames={n: f"{n}.s0ma" for n in modules},
    )
    index = build_project_index(modules)

    rendered: dict[str, str] = {}
    for module in modules.values():
        outputs = render_module_docs(
            module, index=index, hashes=hashes, base_dir=base_dir,
        )
        for out in outputs:
            rendered[out.name] = out.content
    return rendered


class TestMarkdownFrontmatter:
    def test_doc_ref_frontmatter_has_canonical_field_order(
        self, tmp_path: Path,
    ) -> None:
        rendered = _render(FIXTURE_DIR, tmp_path)
        md = rendered["greetings_md"]
        assert md.startswith("---\n")
        # The keys after the opening "---" must be the canonical
        # FrontmatterFields order, regardless of input order. DSL-M4
        # (ADR-011 §(f)) dropped ``transpiler_version`` — seven fields now.
        body = md.split("\n---\n", 2)[0].splitlines()
        keys = [line.split(":", 1)[0] for line in body[1:]]
        assert keys == [
            "s0ma_kind",
            "name",
            "module",
            "format",
            "intent",
            "schema_version",
            "content_hash",
        ]

    def test_doc_ref_frontmatter_carries_real_hash(
        self, tmp_path: Path,
    ) -> None:
        rendered = _render(FIXTURE_DIR, tmp_path)
        md = rendered["greetings_md"]
        # Look for the version-prefixed transitive hash.
        assert 'content_hash: "1:' in md

    def test_doc_guide_frontmatter_distinct_from_doc_ref(
        self, tmp_path: Path,
    ) -> None:
        rendered = _render(FIXTURE_DIR, tmp_path)
        guide = rendered["greetings_walkthrough"]
        assert 's0ma_kind: "doc-guide"' in guide
        assert 'name: "greetings_walkthrough"' in guide


class TestMarkdownBodySubstitution:
    def test_reference_token_substituted_with_intent(
        self, tmp_path: Path,
    ) -> None:
        rendered = _render(FIXTURE_DIR, tmp_path)
        guide = rendered["greetings_walkthrough"]
        # The `{{nerve::greet}}` token resolves to a backticked name plus
        # the entity's intent in parens.
        assert "`nerve::greet`" in guide
        assert "Returns a greeting for the given username." in guide

    def test_example_embed_renders_as_python_fence(
        self, tmp_path: Path,
    ) -> None:
        rendered = _render(FIXTURE_DIR, tmp_path)
        guide = rendered["greetings_walkthrough"]
        # The raw {{example::...}} token must not survive in the output.
        assert "{{example::" not in guide
        # Code fence with language tag and dedented body.
        assert "```python\nfrom greetings import greet" in guide

    def test_doc_ref_filter_resolves_public_nerves(
        self, tmp_path: Path,
    ) -> None:
        rendered = _render(FIXTURE_DIR, tmp_path)
        md = rendered["greetings_md"]
        # The greet nerve is the only public nerve in the project.
        assert "### nerve::greet" in md


class TestMarkdownReproducibility:
    def test_rendering_twice_is_byte_equal(self, tmp_path: Path) -> None:
        first = _render(FIXTURE_DIR, tmp_path / "a")
        second = _render(FIXTURE_DIR, tmp_path / "b")
        assert first == second

    def test_renders_are_byte_equal_across_module_iteration(
        self, tmp_path: Path,
    ) -> None:
        # Sanity check: the renderer doesn't depend on dict iteration
        # order. Build the project, then re-shuffle the modules dict and
        # confirm the rendered content for each declaration is identical.
        modules = _parse_project(FIXTURE_DIR)
        hashes_a = compute_doc_hashes(modules)
        index_a = build_project_index(modules)

        # Reverse iteration order
        reversed_modules = dict(reversed(list(modules.items())))
        hashes_b = compute_doc_hashes(reversed_modules)
        index_b = build_project_index(reversed_modules)

        outs_a: dict[str, str] = {}
        for m in modules.values():
            for out in render_module_docs(
                m, index=index_a, hashes=hashes_a, base_dir=tmp_path / "a",
            ):
                outs_a[out.name] = out.content

        outs_b: dict[str, str] = {}
        for m in reversed_modules.values():
            for out in render_module_docs(
                m, index=index_b, hashes=hashes_b, base_dir=tmp_path / "b",
            ):
                outs_b[out.name] = out.content

        assert outs_a == outs_b


class TestContentHashStability:
    def test_same_input_same_hash(self) -> None:
        modules = _parse_project(FIXTURE_DIR)
        h1 = compute_doc_hashes(modules)
        h2 = compute_doc_hashes(modules)
        assert h1.hashes == h2.hashes

    def test_unreferenced_change_does_not_change_hash(self) -> None:
        # Add a brand-new module that the doc-ref's `nerve where ...`
        # filter will never pick up (no nerves in it). Hashes should be
        # invariant.
        modules = _parse_project(FIXTURE_DIR)
        baseline = compute_doc_hashes(modules)

        extra = parse_s0ma(
            (
                "module unrelated\n"
                "    layer: DOMAIN\n"
                "    version: 1.0.0\n"
                '    intent: "Unrelated module that no doc covers."\n'
                "    exports: []\n"
                "    requires: none\n"
                "    uses: none\n"
                "    soft_requires: none\n"
                "    runtime_only_requires: none\n"
                "    deferred_requires: none\n"
                "    exports_helpers: none\n"
            ),
            filename="unrelated.s0ma",
        )
        # NB: the extra module has no nerves — the filter `nerve where
        # visibility == PUBLIC` resolves to the same set in both runs,
        # so the hash must not change.
        modules_with_extra = dict(modules)
        modules_with_extra[extra.module.name] = extra
        with_extra = compute_doc_hashes(modules_with_extra)

        assert baseline.hashes == with_extra.hashes

    def test_referenced_change_changes_hash(self) -> None:
        # Edit the greet nerve's intent → every doc-ref that covers
        # `nerve where visibility == PUBLIC` must rehash differently.
        modules = _parse_project(FIXTURE_DIR)
        baseline = compute_doc_hashes(modules)

        # Re-parse a mutated greetings.s0ma in memory.
        original = (FIXTURE_DIR / "greetings.s0ma").read_text()
        mutated = original.replace(
            "Returns a greeting for the given username.",
            "Returns a courteous greeting for the named user.",
        )
        new_module = parse_s0ma(mutated, filename="greetings.s0ma")
        modules[new_module.module.name] = new_module
        after = compute_doc_hashes(modules)

        assert baseline.get("doc-ref", "greetings_md") != \
            after.get("doc-ref", "greetings_md")
        # The doc-guide that covers `nerve::greet` should also rehash.
        assert baseline.get("doc-guide", "greetings_walkthrough") != \
            after.get("doc-guide", "greetings_walkthrough")
