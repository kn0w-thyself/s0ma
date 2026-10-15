"""The learning collection: thirty-seven pages, a glossary and an anatomy.

Milestone F5 of the docs-function plan (internal) §11. The collection is the
human half of the coverage policy made real: architecture §11.1 asks
whether every concept has *a human page and an agent topic response*, and
until this milestone the human page was something a renderer could produce
on demand rather than a file anybody could open. Four claims, and the
milestone is only worth having if it makes all four.

* **Every concept has a page, and the set is the gate's set.** Not a set
  this file recounts — the required concepts are read *out of*
  :func:`~s0ma_dsl.docs_model.resolve.check_coverage` by running it against
  an index that addresses nothing and collecting what it names. A test
  that recomputed the requirement from the same bundle the renderer walked
  would pass by construction and prove nothing, which is the vacuity trap
  that gate was built around.
* **A page carries the facts and nothing else.** B5's residue definition,
  applied to this channel's own declaration: the facts are extracted back
  **out of the rendered page** and compared with the topic view, over all
  thirty-seven, and every heading on every page is one the declaration
  accounts for.
* **A reader is never sent nowhere.** Every link on every page is resolved
  with ``scripts/check_links.py``'s own resolver — the A5 gate's, not a
  second opinion — against the rendered collection plus what git tracks.
* **The voice rule reaches every rendered page.** This is the teaching
  collection: the words on it are the words a person learning s0ma reads
  first. The battery runs over all forty-one pages and over every field
  those pages are assembled from, and a planted violation turns it red.

**Why the negative half is as long as the positive half.** Every claim
above is about an absence — no missing page, no invented sentence, no dead
link, no forbidden word — and an absence is exactly what a green test can
report without having looked. So each one is paired with a mutation that
must turn it red: a concept hidden from the collection, a section added to
a page, a link pointed at nothing, a forbidden word planted in a record.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.docs_model.application import (
    DOCS_ROOT,
    PRODUCT_CONCEPTS,
    PRODUCT_DOMAIN,
    build,
)
from s0ma_dsl.docs_model.ids import AliasIndex
from s0ma_dsl.docs_model.inventories import GENERATED_NOTE
from s0ma_dsl.docs_model.learn_pages import (
    ANATOMY_OUTPUT,
    ANATOMY_SECTIONS,
    ANATOMY_TITLE,
    CHANNEL,
    ENVELOPE,
    FILE_CONCEPT,
    GLOSSARY_OUTPUT,
    GLOSSARY_TITLE,
    LEARN_DIR,
    NEXT_HEADING,
    PART_OF,
    REFERENCE_LINKS,
    TRANSFORMATIONS,
    DocsLearnError,
    anatomy_page,
    catalog_rows,
    concept_page,
    declaration_kinds,
    extract,
    glossary_page,
    learn_outputs,
    learn_pages,
    page_slug,
    relative_to_learn,
    spec_for_concept,
    stale_pages,
    undeclared_headings,
)
from s0ma_dsl.docs_model.map_of_record import UNDERSTAND, category_of
from s0ma_dsl.docs_model.providers_catalog import (
    AUDIENCES,
    KINDS,
    STATUSES,
    CatalogProvider,
)
from s0ma_dsl.docs_model.providers_concepts import (
    FORBIDDEN_IN_AUTHORED_PROSE,
    ConceptsProvider,
)
from s0ma_dsl.docs_model.records import DocsBundle
from s0ma_dsl.docs_model.render_agent import render_agent
from s0ma_dsl.docs_model.render_human import EMPTY_MARKER, IDENTITY_HEADING, render_human
from s0ma_dsl.docs_model.render_human import spec_for as human_spec_for
from s0ma_dsl.docs_model.resolve import (
    DOC_CONCEPT_UNCOVERED,
    IDENTITY_FACTS,
    TopicIndex,
    canonical_fact,
    check_coverage,
    facts_of,
)

if TYPE_CHECKING:
    from types import ModuleType

    from s0ma_dsl.docs_model.records import ConceptRecord

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CHECK_LINKS = REPO_ROOT / "scripts" / "check_links.py"

#: The journey this collection's anatomy page is the reference shape of.
FIRST_MODULE = "journey:first-module"


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


# ---------------------------------------------------------------------------
# The composition these pages are rendered from
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def live_bundle() -> DocsBundle:
    """One composition of this checkout, once per process."""
    return build(REPO_ROOT).bundle


@lru_cache(maxsize=1)
def live_aliases() -> AliasIndex:
    """Both concept files' authored aliases, merged into one index.

    The same merge :func:`~s0ma_dsl.docs_model.application.build` makes
    before it arms the coverage gate. Read from the providers rather than
    from the bundle because no record type carries an alias field in
    ``@1`` — C1 defers that to F6 — so the providers are where they are.
    """
    language = ConceptsProvider.language(REPO_ROOT).alias_index()
    product = ConceptsProvider(
        root=REPO_ROOT, relative=PRODUCT_CONCEPTS, domain=PRODUCT_DOMAIN
    ).alias_index()
    return AliasIndex.of([*language.entries, *product.entries])


@lru_cache(maxsize=1)
def rendered_pages() -> dict[str, str]:
    """The whole collection, rendered once per process.

    Module-level and cached so the hash-seed subprocess can import exactly
    this, rather than a second assembly that might differ from the one the
    assertions here ran against.
    """
    return learn_pages(live_bundle(), aliases=live_aliases())


def concept_pages() -> dict[str, str]:
    """The collection minus its two collection pages."""
    return {
        relative: text
        for relative, text in rendered_pages().items()
        if relative not in {GLOSSARY_OUTPUT, ANATOMY_OUTPUT}
    }


def _concepts() -> tuple[ConceptRecord, ...]:
    return tuple(sorted(live_bundle().concepts, key=lambda item: item.id))


def _by_id() -> dict[str, ConceptRecord]:
    return {record.id: record for record in live_bundle().concepts}


def _leaf() -> ConceptRecord:
    """A concept nothing in the collection points at.

    Neither another concept's relation nor an alias's see-reference. The
    mutation tests below remove or rename one concept, and doing that to a
    concept somebody cites would fail for the *wrong* reason — the renderer
    refusing a dead link rather than the assertion under test. Chosen from
    the model rather than named, so it survives the day somebody declares
    an edge onto whichever one is first today.
    """
    targets = {
        target
        for record in live_bundle().concepts
        for _, target in (tuple(edge) for edge in record.related_concepts)
    }
    targets.update(new for _, new in live_aliases().entries)
    leaves = [record for record in _concepts() if record.id not in targets]
    assert leaves, "every concept is cited — the mutations below have no subject"
    return leaves[0]


@lru_cache(maxsize=1)
def _checker() -> ModuleType:
    """Import ``scripts/check_links.py`` — the A5 gate's own resolver.

    Registered in ``sys.modules`` before execution for the reason
    ``test_check_links_script.py`` gives: ``@dataclass`` resolves a class's
    module through it.
    """
    spec = importlib.util.spec_from_file_location("s0ma_check_links", CHECK_LINKS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _empty_index() -> TopicIndex:
    """An index that addresses nothing at all."""
    whole = live_bundle()
    return TopicIndex.of(
        DocsBundle(
            stamp=whole.stamp,
            authorities=(),
            concepts=(),
            surfaces=(),
            journeys=(),
            sequences=(),
            documents=(),
        )
    )


@lru_cache(maxsize=1)
def required_concepts() -> frozenset[str]:
    """What the coverage gate requires a read surface for, read out of the gate.

    Not recomputed from the bundle. The gate is run against an index that
    addresses nothing, so every concept it composed comes back as a
    ``DOC_CONCEPT_UNCOVERED`` finding naming itself, and the set of names
    is the requirement — measured rather than restated. A test that read
    the requirement from the same place the renderer read it would pass
    however wrong both were.
    """
    findings = check_coverage(
        live_bundle(),
        renderers={"human": render_human, "agent": render_agent},
        index=_empty_index(),
    )
    return frozenset(
        finding.message.split(" ", 1)[0]
        for finding in findings
        if finding.code == DOC_CONCEPT_UNCOVERED
    )


# ---------------------------------------------------------------------------
# T1 — one concept as a page
# ---------------------------------------------------------------------------


@requires_checkout
class TestAConceptPage:
    """What a reader meets, and that nothing on it was invented."""

    def test_every_page_carries_the_declared_sections_of_its_facts(self) -> None:
        """A section is present exactly when its fact has something to say."""
        spec = spec_for_concept()
        for record in _concepts():
            page = rendered_pages()[f"{LEARN_DIR}/{page_slug(record.id)}.md"]
            view = facts_of(live_bundle(), record)
            for fact in spec.order:
                label = spec.label_of(fact)
                if not label.startswith("## "):
                    continue
                value = view.value(fact)
                empty = not value if isinstance(value, tuple) else not value.strip()
                present = f"\n{label}\n" in page
                if empty and fact not in {"example_ids", "authority_refs"}:
                    assert not present, f"{record.id} shows an empty {fact}"
                else:
                    assert present, f"{record.id} is missing {label}"

    def test_the_facts_read_back_out_of_the_page(self) -> None:
        """B5's three rules over this channel, all thirty-seven pages.

        Rule (a): the identity core is carried and equal. Rule (b): every
        other fact the page carries is verbatim — verbatim *or absent*, so
        a section left off is legal. What this file adds to B5 is the
        other half of that licence: absent only where the fact is empty,
        which is what stops "verbatim or absent" from excusing a renderer
        that has quietly stopped writing a section.
        """
        spec = spec_for_concept()
        for record in _concepts():
            page = rendered_pages()[f"{LEARN_DIR}/{page_slug(record.id)}.md"]
            view = facts_of(live_bundle(), record)
            read = extract(page, spec)
            for fact in IDENTITY_FACTS:
                assert fact in read, f"{record.id} leaves {fact} off"
            for fact in spec.order:
                truth = canonical_fact(fact, view.value(fact))
                if fact not in read:
                    assert not truth, f"{record.id} silently dropped {fact}"
                    continue
                assert canonical_fact(fact, read[fact]) == truth, (
                    f"{record.id}.{fact} differs"
                )

    def test_an_edited_page_reads_back_differently(self) -> None:
        """The extractor reads the page, not the renderer's memory of it."""
        spec = spec_for_concept()
        record = _by_id()["concept:nerve"]
        page = rendered_pages()[f"{LEARN_DIR}/nerve.md"]
        edited = page.replace(
            record.summary, "A thing that does something, probably."
        )
        assert edited != page
        assert extract(edited, spec)["summary"] != extract(page, spec)["summary"]

    def test_no_page_carries_a_heading_no_declaration_accounts_for(self) -> None:
        spec = spec_for_concept()
        for relative, page in concept_pages().items():
            assert undeclared_headings(page, spec) == (), relative

    def test_a_planted_section_is_reported_as_undeclared(self) -> None:
        """The heading check is not passing by finding no headings."""
        spec = spec_for_concept()
        page = rendered_pages()[f"{LEARN_DIR}/nerve.md"]
        planted = page.replace(NEXT_HEADING, "## What we think about this\n\nMuch.\n")
        assert undeclared_headings(planted, spec) == ("## What we think about this",)

    def test_every_page_says_it_is_generated_once(self) -> None:
        for relative, page in rendered_pages().items():
            assert page.count(GENERATED_NOTE) == 1, relative

    def test_the_identity_block_carries_the_build_it_describes(self) -> None:
        stamp = live_bundle().stamp
        for record in _concepts():
            page = rendered_pages()[f"{LEARN_DIR}/{page_slug(record.id)}.md"]
            foot = page.split(f"\n{IDENTITY_HEADING}\n", 1)[1]
            assert f"- Topic id: `{record.id}`" in foot
            assert f"- Release: `{stamp.version_line()}`" in foot
            assert f"- Documentation snapshot: `{stamp.snapshot_hash}`" in foot

    def test_a_written_form_is_the_records_own_lines_unedited(self) -> None:
        """The syntax block is quoted, never reflowed."""
        shown = 0
        for record in _concepts():
            if not record.syntax:
                continue
            page = rendered_pages()[f"{LEARN_DIR}/{page_slug(record.id)}.md"]
            assert "```text\n" + "\n".join(record.syntax) + "\n```" in page
            shown += 1
        assert shown >= 15, "the written forms stopped being rendered"

    def test_a_typed_relation_is_a_link_to_a_page_in_this_collection(self) -> None:
        """Every edge is written as its relation word and a page that exists."""
        edges = 0
        for record in _concepts():
            page = rendered_pages()[f"{LEARN_DIR}/{page_slug(record.id)}.md"]
            for relation, target in (tuple(edge) for edge in record.related_concepts):
                canonical = live_aliases().canonical(target)
                slug = page_slug(canonical)
                term = _by_id()[canonical].term
                assert f"- {relation} [{term}]({slug}.md)" in page, (
                    f"{record.id} -> {target}"
                )
                assert f"{LEARN_DIR}/{slug}.md" in rendered_pages()
                edges += 1
        assert edges >= 50, "the relation graph stopped being rendered"

    def test_the_authority_citation_names_the_source_and_the_section(self) -> None:
        cited = 0
        authorities = {item.id: item for item in live_bundle().authorities}
        for record in _concepts():
            page = rendered_pages()[f"{LEARN_DIR}/{page_slug(record.id)}.md"]
            for identifier in record.governed_by:
                assert f"- `{identifier}`" in page
                authority = authorities[identifier]
                written = (
                    f"{authority.source}#{authority.section}"
                    if authority.section
                    else authority.source
                )
                assert f"- `{written}`" in page, f"{record.id} cites {identifier}"
                cited += 1
        assert cited >= 37, "the citations stopped being rendered"

    def test_a_concept_with_no_worked_example_says_so(self) -> None:
        """An absence stated is a fact; a missing section is a silence."""
        without = [record for record in _concepts() if not record.examples]
        assert without, "every concept now binds an example — update this proof"
        for record in without:
            page = rendered_pages()[f"{LEARN_DIR}/{page_slug(record.id)}.md"]
            assert "## Worked examples\n\n- none recorded\n" in page

    def test_the_next_block_offers_the_glossary_and_the_two_references(self) -> None:
        for relative, page in concept_pages().items():
            block = page.split(f"{NEXT_HEADING}\n", 1)[1].split("\n---\n", 1)[0]
            assert f"[{GLOSSARY_TITLE}](glossary.md)" in block, relative
            for reference, text in REFERENCE_LINKS:
                assert f"[{text}](../{reference})" in block, relative

    def test_a_declaration_kind_is_pointed_at_the_anatomy_and_others_are_not(
        self,
    ) -> None:
        kinds = {record.id for record in declaration_kinds(live_bundle())}
        assert len(kinds) == 11
        anatomy_link = f"[{ANATOMY_TITLE}](anatomy-of-a-s0ma-file.md)"
        for record in _concepts():
            page = rendered_pages()[f"{LEARN_DIR}/{page_slug(record.id)}.md"]
            block = page.split(f"{NEXT_HEADING}\n", 1)[1]
            wanted = record.id in kinds or record.id == FILE_CONCEPT
            assert (anatomy_link in block) is wanted, record.id

    def test_the_guide_that_teaches_a_concept_is_offered_on_its_page(self) -> None:
        """The first-module guide reaches ``concept:nerve`` through the journey."""
        page = rendered_pages()[f"{LEARN_DIR}/nerve.md"]
        assert "](../guides/first-module.md)" in page

    def test_the_authored_data_files_are_not_offered_as_further_reading(self) -> None:
        """A page never sends a reader back into the file it was rendered from."""
        for relative, page in rendered_pages().items():
            assert "concepts/language.json" not in page, relative
            assert "concepts/product.json" not in page, relative

    def test_the_channel_declares_what_it_does_beyond_the_human_one(self) -> None:
        human = human_spec_for("concepts")
        spec = spec_for_concept()
        assert spec.channel == CHANNEL != human.channel
        assert spec.order == human.order
        assert spec.labels == human.labels
        assert set(human.transformations) < set(TRANSFORMATIONS)
        assert GENERATED_NOTE in ENVELOPE
        assert NEXT_HEADING in ENVELOPE


# ---------------------------------------------------------------------------
# T2 — the collection is complete
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheCollectionIsComplete:
    """The page set, the glossary and the anatomy, all against the model."""

    def test_the_rendered_set_is_the_coverage_gates_required_set(self) -> None:
        """Equality, both ways, against a requirement read out of the gate."""
        required = required_concepts()
        assert required, "the coverage gate required nothing — it is vacuous"
        assert required == {record.id for record in _concepts()}
        assert {f"{LEARN_DIR}/{page_slug(item)}.md" for item in required} == set(
            concept_pages()
        )

    def test_a_concept_the_collection_missed_would_be_visible(self) -> None:
        """The equality above is not satisfied by rendering nothing."""
        whole = live_bundle()
        dropped = _leaf()
        narrowed = replace(
            whole,
            concepts=tuple(
                item for item in whole.concepts if item.id != dropped.id
            ),
        )
        rendered = learn_pages(narrowed, aliases=live_aliases())
        assert dropped.id in required_concepts()
        assert f"{LEARN_DIR}/{page_slug(dropped.id)}.md" not in rendered
        assert {f"{LEARN_DIR}/{page_slug(item)}.md" for item in required_concepts()} != {
            relative
            for relative in rendered
            if relative not in {GLOSSARY_OUTPUT, ANATOMY_OUTPUT}
        }

    def test_the_collection_is_thirty_seven_pages_and_two(self) -> None:
        assert len(concept_pages()) == len(_concepts())
        assert set(rendered_pages()) - set(concept_pages()) == {
            GLOSSARY_OUTPUT,
            ANATOMY_OUTPUT,
        }

    def test_every_page_is_inside_the_collection_and_ends_in_one_line_feed(
        self,
    ) -> None:
        for relative, page in rendered_pages().items():
            assert relative.startswith(f"{LEARN_DIR}/"), relative
            assert relative.endswith(".md"), relative
            assert page.endswith("\n") and not page.endswith("\n\n"), relative
            assert "\r" not in page, relative
            page.encode("utf-8")

    def test_the_glossary_carries_every_concept_with_its_short_form(self) -> None:
        page = rendered_pages()[GLOSSARY_OUTPUT]
        assert f"# {GLOSSARY_TITLE}" in page
        assert f"s0ma's vocabulary is {len(_concepts())} ideas." in page
        for record in _concepts():
            slug = page_slug(record.id)
            assert f"| [{record.term}]({slug}.md) | `{record.id}` |" in page
            assert record.summary in page

    def test_every_alias_is_a_see_reference_onto_a_page_that_exists(self) -> None:
        page = rendered_pages()[GLOSSARY_OUTPUT]
        entries = live_aliases().entries
        assert entries, "no alias is declared — the see-references prove nothing"
        assert f"{len(entries)} other names resolve onto one of the terms" in page
        for old, new in entries:
            canonical = live_aliases().canonical(new)
            slug = page_slug(canonical)
            term = _by_id()[canonical].term
            assert f"| `{old}` | [{term}]({slug}.md) |" in page
            assert f"{LEARN_DIR}/{slug}.md" in rendered_pages()

    def test_the_glossary_states_no_count_it_has_not_computed(self) -> None:
        """Every number on the page is one of the two computed ones."""
        page = rendered_pages()[GLOSSARY_OUTPUT]
        prose = [
            line
            for line in page.splitlines()
            if line and not line.startswith(("|", "-", "#"))
        ]
        counted = {str(len(_concepts())), str(len(live_aliases().entries))}
        for line in prose:
            for number in re.findall(r"\b\d+\b", line):
                assert number in counted, f"{number!r} in {line!r} is written down"

    def test_the_anatomy_carries_the_eleven_declaration_kinds_in_order(self) -> None:
        page = rendered_pages()[ANATOMY_OUTPUT]
        kinds = declaration_kinds(live_bundle())
        assert len(kinds) == 11
        headings = [
            line[4:] for line in page.splitlines() if line.startswith("### ")
        ]
        assert headings == [record.term for record in kinds]
        for record in kinds:
            assert f"- Whole entry: [{record.term}]({page_slug(record.id)}.md)" in page

    def test_the_eleven_are_the_parts_the_records_declare(self) -> None:
        """Derived from the model, never listed in the renderer."""
        declared = {
            record.id
            for record in _concepts()
            if (PART_OF, FILE_CONCEPT) in {tuple(e) for e in record.related_concepts}
        }
        assert {record.id for record in declaration_kinds(live_bundle())} == declared

    def test_the_anatomy_shows_only_written_forms_the_records_carry(self) -> None:
        """Every fenced block on the page is some concept's syntax, verbatim."""
        page = rendered_pages()[ANATOMY_OUTPUT]
        blocks = re.findall(r"```text\n(.*?)\n```", page, re.DOTALL)
        assert len(blocks) == len(declaration_kinds(live_bundle())) + 2
        forms = {"\n".join(record.syntax) for record in _concepts() if record.syntax}
        smallest = blocks[-1]
        assert smallest not in forms, "the smallest file is two forms, not one"
        for block in blocks[:-1]:
            assert block in forms, f"an invented written form:\n{block}"

    def test_the_smallest_complete_file_is_two_records_forms_unedited(self) -> None:
        page = rendered_pages()[ANATOMY_OUTPUT]
        smallest = re.findall(r"```text\n(.*?)\n```", page, re.DOTALL)[-1]
        header, _, declaration = smallest.partition("\n\n")
        assert header == "\n".join(_by_id()["concept:module"].syntax)
        assert declaration == "\n".join(_by_id()["concept:nerve"].syntax)
        assert ANATOMY_SECTIONS[-1] in page

    def test_the_anatomy_closes_by_pointing_at_the_journeys_guide(self) -> None:
        page = rendered_pages()[ANATOMY_OUTPUT]
        guides = [
            document
            for document in live_bundle().documents
            if FIRST_MODULE in document.covers
        ]
        assert len(guides) == 1
        guide = guides[0]
        block = page.split(f"{NEXT_HEADING}\n", 1)[1]
        assert block.splitlines()[1] == (
            f"- [{guide.title}]"
            f"({relative_to_learn(guide.canonical_source, docs_root=DOCS_ROOT)})"
        )

    def test_the_anatomy_says_nothing_the_records_do_not(self) -> None:
        """Every prose line is a concept's own summary, definition or purpose."""
        page = rendered_pages()[ANATOMY_OUTPUT]
        authored = {
            text
            for record in _concepts()
            for text in (record.summary, record.plain_definition, record.purpose)
        }
        computed = {
            GENERATED_NOTE,
            f"A file may contain {len(declaration_kinds(live_bundle()))} kinds of "
            f"declaration. They are listed here in the order the specification "
            f"defines them, each with the section that defines it and a link to "
            f"its whole entry.",
            f"A header and one declaration. Both written forms below are the "
            f"ones {_by_id()['concept:module'].term} and "
            f"{_by_id()['concept:nerve'].term} carry above, unedited.",
        }
        fenced = False
        for line in page.splitlines():
            if line.startswith("```"):
                fenced = not fenced
                continue
            if fenced or not line or line.startswith(("#", "-", "|")):
                continue
            assert line in authored or line in computed, f"invented prose: {line!r}"

    def test_the_collection_pages_carry_the_build_and_no_topic_id(self) -> None:
        stamp = live_bundle().stamp
        for relative in (GLOSSARY_OUTPUT, ANATOMY_OUTPUT):
            foot = rendered_pages()[relative].split(f"\n{IDENTITY_HEADING}\n", 1)[1]
            assert f"- Release: `{stamp.version_line()}`" in foot
            assert f"- Documentation snapshot: `{stamp.snapshot_hash}`" in foot
            assert "Topic id" not in foot, relative

    def test_a_slug_is_the_ids_term_and_never_the_records(self) -> None:
        """The terms that would not survive being turned into file names."""
        assert page_slug("concept:s0ma-file") == "s0ma-file"
        assert _by_id()["concept:s0ma-file"].term == ".s0ma file"
        assert page_slug("concept:canonical-ir") == "canonical-ir"
        assert _by_id()["concept:canonical-ir"].term == "canonical IR"
        assert page_slug("concept:requires") == "requires"
        assert _by_id()["concept:requires"].term == "requires:"
        assert len({page_slug(record.id) for record in _concepts()}) == len(_concepts())


# ---------------------------------------------------------------------------
# T3 — the proofs
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheVoiceRule:
    """The words a person learning s0ma reads first."""

    def test_no_rendered_page_uses_a_word_the_product_does_not(self) -> None:
        for relative, page in rendered_pages().items():
            for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
                found = pattern.search(page)
                assert found is None, (
                    f"{relative} uses {found.group(0)!r}, which is {label}"
                    if found is not None
                    else ""
                )

    def test_the_battery_is_not_passing_by_having_nothing_to_read(self) -> None:
        assert len(rendered_pages()) == 41
        assert sum(len(page) for page in rendered_pages().values()) > 50_000
        assert any(
            pattern.search("this page mentions a payload")
            for _, pattern in FORBIDDEN_IN_AUTHORED_PROSE
        )

    # The middle word is the legacy spelling the voice battery forbids, and
    # this proof has to plant the real thing to show the rule catches it.
    @pytest.mark.parametrize(
        "planted",
        ["payload", "soma", "Studio"],  # legacy-spelling: intentional
    )
    def test_a_forbidden_word_in_a_record_reaches_the_page_and_is_caught(
        self, planted: str
    ) -> None:
        """The rule reaches rendered prose, not only the authored file."""
        whole = live_bundle()
        record = _by_id()["concept:nerve"]
        spoiled = replace(record, purpose=f"It exists to carry the {planted}.")
        bundle = replace(
            whole,
            concepts=tuple(
                spoiled if item.id == record.id else item for item in whole.concepts
            ),
        )
        page = concept_page(bundle, spoiled, aliases=live_aliases())
        assert any(
            pattern.search(page) is not None
            for _, pattern in FORBIDDEN_IN_AUTHORED_PROSE
        )

    def test_the_generated_note_and_every_heading_are_in_the_voice(self) -> None:
        """The words this module contributes, checked apart from the records."""
        written = [GENERATED_NOTE, NEXT_HEADING, ANATOMY_TITLE, GLOSSARY_TITLE]
        written.extend(ANATOMY_SECTIONS)
        written.extend(text for _, text in REFERENCE_LINKS)
        written.extend(TRANSFORMATIONS)
        for text in written:
            for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
                assert pattern.search(text) is None, f"{text!r} is {label}"


@requires_checkout
class TestEveryLinkResolves:
    """The A5 gate's own resolver, over the collection and the live tree."""

    def _links(self) -> list[tuple[str, str, str]]:
        """``(page, target, fragment)`` for every clickable link rendered."""
        checker = _checker()
        found: list[tuple[str, str, str]] = []
        for relative, page in rendered_pages().items():
            source = f"{DOCS_ROOT}/{relative}"
            for link in checker.document_links(source, page):
                target, _, fragment = link.target.partition("#")
                if ":" in target.split("/", 1)[0]:
                    continue  # an external scheme; the gate skips these too
                found.append((source, target, fragment))
        return found

    def test_every_link_lands_on_a_tracked_file_or_a_rendered_page(self) -> None:
        checker = _checker()
        tracked = checker.tracked_files(REPO_ROOT)
        staged = {f"{DOCS_ROOT}/{relative}" for relative in rendered_pages()}
        links = self._links()
        assert len(links) >= 200, "the collection stopped linking anywhere"
        for source, target, _ in links:
            resolved = checker._resolve(source, target)  # noqa: SLF001
            assert resolved is not None, f"{source} -> {target} escapes the checkout"
            assert resolved in tracked or resolved in staged, (
                f"{source} -> {target} resolves to {resolved}, which is neither "
                f"tracked nor rendered by this collection"
            )

    def test_every_fragment_names_a_real_heading(self) -> None:
        checker = _checker()
        staged = {f"{DOCS_ROOT}/{relative}": text for relative, text in rendered_pages().items()}
        for source, target, fragment in self._links():
            if not fragment:
                continue
            resolved = checker._resolve(source, target)  # noqa: SLF001
            text = staged.get(resolved)
            if text is None:
                path = REPO_ROOT / resolved
                if not path.is_file() or not resolved.endswith(".md"):
                    continue
                text = path.read_text(encoding="utf-8")
            assert fragment in checker.document_anchors(text), (
                f"{source} -> {target}#{fragment}"
            )

    def test_a_link_pointed_at_nothing_would_be_caught(self) -> None:
        """The resolver is doing work, not returning True."""
        checker = _checker()
        tracked = checker.tracked_files(REPO_ROOT)
        resolved = checker._resolve(  # noqa: SLF001
            f"{DOCS_ROOT}/{LEARN_DIR}/nerve.md", "no-such-page.md"
        )
        assert resolved == f"{DOCS_ROOT}/{LEARN_DIR}/no-such-page.md"
        assert resolved not in tracked
        assert resolved not in {f"{DOCS_ROOT}/{item}" for item in rendered_pages()}

    def test_the_sections_a_written_form_looks_like_are_not_read_as_headings(
        self,
    ) -> None:
        """``concept:s0ma-file``'s own form contains a line beginning with a hash."""
        checker = _checker()
        page = rendered_pages()[ANATOMY_OUTPUT]
        assert "\n# then one or more declarations" in page
        assert "then-one-or-more-declarations-in-any-order" not in "".join(
            checker.document_anchors(page)
        )


@requires_checkout
class TestTheBytesAreTheBytes:
    """Deterministic, and proved rather than asserted."""

    def test_rendering_twice_in_one_process_gives_the_same_bytes(self) -> None:
        first = dict(rendered_pages())
        rendered_pages.cache_clear()
        live_bundle.cache_clear()
        live_aliases.cache_clear()
        assert dict(rendered_pages()) == first

    def test_three_hash_seeds_in_three_processes_agree(self, tmp_path: Path) -> None:
        """Dictionary order cannot reach the bytes."""
        script = tmp_path / "render_once.py"
        script.write_text(
            "import hashlib, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from tests.test_docs_learn_pages import rendered_pages\n"
            "digest = hashlib.sha256()\n"
            "for name, text in sorted(rendered_pages().items()):\n"
            "    digest.update(name.encode('utf-8'))\n"
            "    digest.update(text.encode('utf-8'))\n"
            "print(digest.hexdigest())\n",
            encoding="utf-8",
            newline="\n",
        )
        digests = set()
        for seed in ("0", "1", "4242"):
            done = subprocess.run(  # noqa: S603
                [sys.executable, str(script), str(PACKAGE_ROOT)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(tmp_path),
                # Inherit the real environment (as the sibling determinism
                # tests do) and vary only the hash seed. A hand-built minimal
                # env dropped SystemRoot, which Winsock needs to initialize —
                # importing asyncio then dies with WinError 10106 on Windows,
                # a failure that has nothing to do with what this test checks.
                env={**os.environ, "PYTHONHASHSEED": seed},
                check=False,
            )
            assert done.returncode == 0, done.stderr
            digests.add(done.stdout.strip())
        assert len(digests) == 1, "the bytes moved between hash seeds"
        here = hashlib.sha256()
        for name, text in sorted(rendered_pages().items()):
            here.update(name.encode("utf-8"))
            here.update(text.encode("utf-8"))
        assert digests == {here.hexdigest()}


@requires_checkout
class TestTheWiringProposal:
    """The rows this collection needs, checked against the catalog's own rules.

    Written while they were a proposal and kept now that they are wired:
    every claim below is one the catalog has to keep making, and the two
    that were about the rows being *absent* are now about them being
    present and being exactly these.
    """

    def test_there_is_exactly_one_row_for_every_rendered_page(self) -> None:
        rows = catalog_rows(live_bundle())
        sources = [str(row["canonical_source"]) for row in rows]
        assert sorted(sources) == sorted(
            f"{DOCS_ROOT}/{relative}" for relative in rendered_pages()
        )
        assert len(set(sources)) == len(sources), "two rows over one file"

    def test_every_row_satisfies_the_catalogs_closed_vocabularies(self) -> None:
        for row in catalog_rows(live_bundle()):
            assert row["kind"] in KINDS, row
            assert row["status"] in STATUSES, row
            assert set(row["audiences"]) <= set(AUDIENCES), row  # type: ignore[arg-type]
            assert str(row["id"]).startswith("doc:generated/"), row
            assert row["canonical_source"] == row["prose_locator"], row
            assert row["status"] == "generated", row

    def test_every_row_id_is_unique_and_composed(self) -> None:
        """Unique among themselves, and every one of them now a real row.

        The proposal half of this test — that no id existed yet — was true
        exactly once, on the run before the rows were written into
        ``docs/s0ma_src/catalog.json``. What has to stay true afterwards is
        the other direction: the composition holds a document record for
        every page this collection renders, which is what keeps the
        completeness gate from reporting forty-one uncataloged files.
        """
        rows = catalog_rows(live_bundle())
        proposed = [str(row["id"]) for row in rows]
        assert len(set(proposed)) == len(proposed)
        existing = {record.id for record in live_bundle().documents}
        assert set(proposed) <= existing, sorted(set(proposed) - existing)

    def test_the_committed_catalog_rows_are_exactly_these(self) -> None:
        """The authored catalog equals what this module computes, field for field.

        The gate that closes the loop. Forty-one rows are more than
        anybody should hand-write, so they are computed here and pasted
        there — and a paste is a copy, which goes stale. This is the
        comparison that makes it not go stale: rename a concept and the
        computed row moves while the committed one does not, and this test
        says so by name rather than the drift surfacing as a rendered page
        nobody can explain.

        Read out of the file rather than out of the composed bundle,
        because a ``DocumentRecord`` does not carry ``kind``, ``status`` or
        ``audiences`` — those three are exactly the fields a comparison
        against the composition would silently not check.
        """
        import json

        catalog = json.loads(
            (REPO_ROOT / DOCS_ROOT / "s0ma_src" / "catalog.json").read_text(
                encoding="utf-8"
            )
        )
        computed = {str(row["id"]): row for row in catalog_rows(live_bundle())}
        committed = {
            str(row["id"]): row
            for row in catalog["documents"]
            if str(row["id"]) in computed
        }
        assert sorted(committed) == sorted(computed), (
            f"{len(computed)} row(s) computed, {len(committed)} committed; "
            f"missing {sorted(set(computed) - set(committed))}"
        )
        for identifier, expected in computed.items():
            assert committed[identifier] == expected, identifier

    def test_every_page_is_accounted_for_by_its_own_row(self) -> None:
        """One row per page, and it is the row this module computes.

        ``cataloged_paths`` is the corpus the completeness gate compares
        the tracked Markdown against, so a page missing from it is a
        ``DOC_DOCUMENT_UNCATALOGED`` finding waiting to happen.
        """
        accounted = CatalogProvider(root=REPO_ROOT).cataloged_paths()
        for row in catalog_rows(live_bundle()):
            assert row["canonical_source"] in accounted, row["canonical_source"]

    def test_wiring_the_rows_in_does_not_change_a_single_byte(self) -> None:
        """The proposal is a fixed point, which is what makes it safe to wire.

        Every proposed row ``covers`` the concept its page renders, and a
        concept page offers links to the documents that cover it — so
        without care, adding the rows would make every page link to
        itself, and the byte gate would go red the run *after* the wiring
        rather than during it. It does not, because a document inside the
        collection is not further reading; this is that rule, proved
        against the rows the orchestrator will actually add.

        The stamp is deliberately held still. Wiring the rows in *does*
        move one line on every page — the snapshot digest, because the
        composed model grew forty-one document records — and that is the
        identity fact doing its job rather than a page changing its mind.
        What must not move is anything else, so the comparison varies the
        documents and nothing else.
        """
        whole = live_bundle()
        sample = next(iter(whole.documents))
        added = tuple(
            replace(
                sample,
                id=str(row["id"]),
                title=str(row["title"]),
                canonical_source=str(row["canonical_source"]),
                prose_locator=str(row["prose_locator"]),
                authority="",
                governed_by=(),
                covers=tuple(row["covers"]),  # type: ignore[arg-type]
            )
            for row in catalog_rows(whole)
        )
        wired = replace(whole, documents=(*whole.documents, *added))
        assert len(wired.documents) == len(whole.documents) + len(rendered_pages())
        assert learn_pages(wired, aliases=live_aliases()) == rendered_pages()

    def test_the_declared_output_set_is_the_set_that_is_rendered(self) -> None:
        assert learn_outputs(live_bundle()) == tuple(sorted(rendered_pages()))
        assert len(learn_outputs(live_bundle())) == len(_concepts()) + 2

    def test_a_page_left_behind_by_a_deleted_concept_is_reported(self) -> None:
        """The half a declared-output set cannot see: an orphan already committed."""
        rendered = learn_outputs(live_bundle())
        assert stale_pages(rendered, live_bundle()) == ()
        orphan = f"{LEARN_DIR}/a-concept-that-was-deleted.md"
        assert stale_pages([*rendered, orphan], live_bundle()) == (orphan,)
        assert stale_pages(["reference/concepts-index.md"], live_bundle()) == ()

    def test_the_rows_file_the_collection_under_understand_s0ma(self) -> None:
        """Rule 5 of the map: a document covering only concepts is teaching."""
        catalog = CatalogProvider(root=REPO_ROOT)
        sample = next(iter(catalog.rows()))
        for row in catalog_rows(live_bundle()):
            record = replace(
                next(iter(live_bundle().documents)),
                id=str(row["id"]),
                title=str(row["title"]),
                canonical_source=str(row["canonical_source"]),
                prose_locator=str(row["prose_locator"]),
                governed_by=(),
                covers=tuple(row["covers"]),  # type: ignore[arg-type]
            )
            placed = replace(
                sample,
                kind=str(row["kind"]),
                status=str(row["status"]),
                audiences=tuple(row["audiences"]),  # type: ignore[arg-type]
            )
            assert category_of(record, placed) == UNDERSTAND, row["id"]

    def test_every_row_covers_something_the_build_composed(self) -> None:
        known = {record.id for record in live_bundle().concepts}
        for row in catalog_rows(live_bundle()):
            covers = tuple(row["covers"])  # type: ignore[arg-type]
            assert covers, row
            assert set(covers) <= known, row

    def test_every_id_list_in_a_row_is_sorted_and_unique(self) -> None:
        """The catalog's reader refuses an unsorted list, and says why."""
        for row in catalog_rows(live_bundle()):
            for field in ("audiences", "covers", "governed_by"):
                values = list(row[field])  # type: ignore[call-overload]
                assert values == sorted(set(values)), f"{row['id']}.{field}"


@requires_checkout
class TestWhatIsRefused:
    """A page that cannot be rendered honestly is not rendered at all."""

    def test_a_page_is_refused_for_something_that_is_not_a_concept(self) -> None:
        with pytest.raises(DocsLearnError, match="renders concepts"):
            page_slug("cli:s0ma/build")

    def test_a_page_is_refused_for_an_id_of_no_form(self) -> None:
        with pytest.raises(DocsLearnError):
            page_slug("not an id")

    def test_a_relation_pointing_at_nothing_refuses_the_page(self) -> None:
        whole = live_bundle()
        record = _by_id()["concept:nerve"]
        broken = replace(record, related_concepts=(("requires", "concept:nothing"),))
        bundle = replace(
            whole,
            concepts=tuple(
                broken if item.id == record.id else item for item in whole.concepts
            ),
        )
        with pytest.raises(DocsLearnError, match="concept:nothing"):
            concept_page(bundle, broken, aliases=live_aliases())

    def test_an_anatomy_with_no_file_concept_is_refused(self) -> None:
        whole = live_bundle()
        without = replace(
            whole,
            concepts=tuple(
                item for item in whole.concepts if item.id != FILE_CONCEPT
            ),
        )
        with pytest.raises(DocsLearnError, match=FILE_CONCEPT):
            anatomy_page(without)

    def test_an_anatomy_with_no_declaration_kinds_is_refused(self) -> None:
        whole = live_bundle()
        flattened = tuple(
            replace(
                item,
                related_concepts=tuple(
                    edge
                    for edge in item.related_concepts
                    if tuple(edge) != (PART_OF, FILE_CONCEPT)
                ),
            )
            for item in whole.concepts
        )
        with pytest.raises(DocsLearnError, match="no concept in this build"):
            anatomy_page(replace(whole, concepts=flattened))

    def test_a_concept_that_would_overwrite_the_glossary_is_refused(self) -> None:
        whole = live_bundle()
        record = _leaf()
        renamed = replace(record, id="concept:glossary")
        bundle = replace(
            whole,
            concepts=tuple(
                renamed if item.id == record.id else item for item in whole.concepts
            ),
        )
        with pytest.raises(DocsLearnError, match=GLOSSARY_TITLE):
            learn_pages(bundle, aliases=live_aliases())

    def test_a_glossary_with_no_alias_says_so_rather_than_showing_nothing(
        self,
    ) -> None:
        page = glossary_page(live_bundle(), aliases=AliasIndex.of(()))
        assert "No alternate name is declared in this build." in page
        assert EMPTY_MARKER not in page

    def test_a_link_out_of_the_collection_is_relative_to_it(self) -> None:
        assert relative_to_learn("docs/learn/nerve.md") == "nerve.md"
        assert relative_to_learn("docs/guides/first-module.md") == (
            "../guides/first-module.md"
        )
        assert relative_to_learn("packages/s0ma-dsl/README.md") == (
            "../../packages/s0ma-dsl/README.md"
        )
