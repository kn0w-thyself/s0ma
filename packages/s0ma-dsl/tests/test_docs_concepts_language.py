"""Gates for C5a — the language concepts and the loader that reads them.

Milestone C5a of the docs-function plan (internal) §8, over
``s0ma_dsl.docs_model.providers_concepts`` and
``docs/s0ma_src/concepts/language.json``. What these tests hold in place:

* **every declaration kind is taught.** The list of kinds is *derived*,
  twice and independently, from the parser's own header table — never
  written down here — so adding a twelfth kind to the language turns this
  suite red until somebody writes the concept that teaches it. That is the
  point of the test, not a side effect of it.
* **every anchor is real and re-verified.** Each concept cites a numbered
  section of the current specification; each number resolves to exactly one
  heading, the recorded heading still reads the way the file says, and the
  digest on the record is the live one. An edit to the specification is
  visible here rather than a year later.
* **the graph holds.** Every concept-to-concept edge points at a concept
  this build addresses, and a symmetric relation declared from one end is
  reported until the other end says it back.
* **it composes clean.** Core, the repository and these concepts compose to
  one bundle with zero findings, which is what makes the concepts usable as
  something everything else can cite.
* **the file is authored, and authoring mistakes are refused by name.** A
  dead citation, a relation word nobody agreed on, an unsorted list and a
  word the product voice does not use each fail with the JSON path of the
  value that is wrong.

**Why the anchors are what they are.** Twenty-two of the twenty-five
concepts cite the section that defines them and nothing else needs saying.
Three are judgement calls, recorded here because a reader deserves to see
them rather than infer them:

* ``concept:check-and-build-loop`` cites §2.1, §4.15 and §4.16 — the build
  pipeline, test execution and the validation command. The loop as a *loop*
  is not a section of the specification: the fourth step, asking a built
  system what it contains, is described only inside §4.4a.2, which governs
  helpers rather than the command. Citing the three sections that do govern
  three of the four steps is the honest reading; inventing an anchor for
  the whole would not be.
* ``concept:executable-evidence`` cites §4.12 and §4.12.4 — the
  documentation declarations and their validation layers. §4.12's own KEY
  states the three-forms-and-no-fourth rule; §4.12.4 is where each form is
  actually checked.
* ``concept:s0ma-file`` cites §4 and §4.9 — the statement that every piece
  of code belongs to exactly one declaration, and the separator rule that
  divides a declaration's description from its code.

**Why no concept here binds an executable example.** Exactly one ``example``
declaration exists in product code, and it demonstrates a running server
answering from its own registry — which is a product concept, not a
language one. Binding it to a declaration kind to avoid an empty field
would have made the one real binding in the corpus a false one.
"""

from __future__ import annotations

import inspect
import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model.application import SIDE_EFFECT_ALLOWANCES
from s0ma_dsl.docs_model.compose import compose
from s0ma_dsl.docs_model.ids import validate_id
from s0ma_dsl.docs_model.providers import ProviderRegistry
from s0ma_dsl.docs_model.providers_concepts import (
    CONCEPTS_SCHEMA,
    DOC_AUTHORITY_STALE,
    DOC_RELATION_ONE_SIDED,
    DOC_VOICE_VIOLATION,
    FORBIDDEN_IN_AUTHORED_PROSE,
    LANGUAGE_CONCEPTS,
    LANGUAGE_DOMAIN,
    LANGUAGE_FLOORS,
    MINTED_CODES,
    RELATION_NAMES,
    RELATIONS,
    SYMMETRIC_RELATIONS,
    ConceptsProvider,
    DocsConceptsError,
    check_concept_relations,
    check_voice,
    headings_by_number,
    relation_of,
)
from s0ma_dsl.docs_model.providers_core import CoreProvider
from s0ma_dsl.docs_model.providers_repo import RepoProvider
from s0ma_dsl.docs_model.records import (
    SCHEMA,
    AuthorityRef,
    ConceptRecord,
    authored_prose_fields,
)
from s0ma_dsl.docs_model.serialize import canonical_json, serialize_bundle
from s0ma_dsl.docs_model.validate import DOC_CONCEPT_UNRESOLVED, validate_bundle
from s0ma_dsl.parser import s0ma_parser

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from s0ma_dsl.docs_model.providers import ProviderResult

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "s0ma_dsl"
    / "docs_model"
    / "providers_concepts.py"
)
DATA = REPO_ROOT / LANGUAGE_CONCEPTS

RELEASE = "0.18.1"

#: Honest minimums for this file, each below the live count. Twenty-five
#: concepts and thirty section anchors are authored; a floor at the count
#: would turn the suite red the moment somebody writes a twenty-sixth.
CONCEPT_FLOOR = 20
ANCHOR_FLOOR = 20


# ---------------------------------------------------------------------------
# The kind list, derived from the parser and never written down
# ---------------------------------------------------------------------------


def parser_declaration_kinds() -> frozenset[str]:
    """Every declaration kind the parser's header table can produce.

    Read out of :func:`s0ma_parser._try_match_header`, which is the
    dispatch every ``.s0ma`` source goes through: whatever it can label, the
    language has. Hyphens are restored because the dispatch spells the two
    documentation declarations with underscores while the syntax a person
    writes uses hyphens.
    """
    source = inspect.getsource(s0ma_parser._try_match_header)
    found = re.findall(r'decl_type="([a-z_]+)"', source)
    assert found, "the parser's header dispatch no longer labels its declarations"
    return frozenset(name.replace("_", "-") for name in found)


def parser_header_keywords() -> frozenset[str]:
    """The same list, derived a second time from the header patterns.

    Every module-level compiled pattern anchored on a lowercase keyword
    followed by whitespace is a declaration header. Two derivations of one
    fact, from two places in the same module, so a change that moves the
    table without moving the dispatch cannot slip past.
    """
    found: set[str] = set()
    for value in vars(s0ma_parser).values():
        if not isinstance(value, re.Pattern):
            continue
        opening = re.match(r"\^([a-z][a-z-]*)\\s", value.pattern)
        if opening is not None:
            found.add(opening.group(1))
    return frozenset(found)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def provider() -> ConceptsProvider:
    return ConceptsProvider.language(REPO_ROOT)


@pytest.fixture(scope="module")
def live(provider: ConceptsProvider) -> ProviderResult:
    return provider.provide()


@pytest.fixture(scope="module")
def concepts(live: ProviderResult) -> dict[str, ConceptRecord]:
    return {
        item.record.id: item.record
        for item in live.records
        if isinstance(item.record, ConceptRecord)
    }


@pytest.fixture(scope="module")
def anchors(live: ProviderResult) -> dict[str, AuthorityRef]:
    return {
        item.record.id: item.record
        for item in live.records
        if isinstance(item.record, AuthorityRef)
    }


@pytest.fixture(scope="module")
def authored() -> dict[str, Any]:
    document = json.loads(DATA.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


@pytest.fixture()
def tree(tmp_path: Path) -> Callable[[Callable[[dict[str, Any]], None]], Path]:
    """A copy of just enough of the checkout to read one concepts file.

    Mutations are applied to the copy, never to the repository, so a
    negative fixture proves a refusal without leaving anything behind.
    """

    def build(mutate: Callable[[dict[str, Any]], None]) -> Path:
        document = json.loads(DATA.read_text(encoding="utf-8"))
        for entry in document["sources"]:
            target = tmp_path / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / entry["path"], target)
        mutate(document)
        out = tmp_path / LANGUAGE_CONCEPTS
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(canonical_json(document), encoding="utf-8", newline="\n")
        return tmp_path

    return build


def _index_of(document: Mapping[str, Any], concept_id: str) -> int:
    """Where a concept sits in the authored list, so a refusal can be placed."""
    for index, record in enumerate(document["records"]):
        if record["id"] == concept_id:
            return index
    raise AssertionError(f"{concept_id} is not in the authored file")


# ---------------------------------------------------------------------------
# Every declaration kind is taught
# ---------------------------------------------------------------------------


class TestKindCoverage:
    """The completeness gate, keyed on the parser rather than on a list."""

    def test_the_two_derivations_of_the_kind_list_agree(self) -> None:
        assert parser_declaration_kinds() == parser_header_keywords()

    def test_the_language_still_has_eleven_declaration_kinds(self) -> None:
        """Plan §1.2 fact 1. A twelfth is a language change, not a typo."""
        assert len(parser_declaration_kinds()) == 11

    def test_every_declaration_kind_has_a_concept(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """The gate the milestone exists for.

        A kind added to the parser and not taught here fails this test,
        which is the signal that somebody has to write the concept — not a
        maintenance chore to be worked around by editing a list.
        """
        missing = sorted(
            kind for kind in parser_declaration_kinds() if f"concept:{kind}" not in concepts
        )
        assert missing == [], f"declaration kinds nobody teaches: {missing}"

    def test_every_declaration_kind_carries_a_written_form(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """B4 named the cost of a missing syntax form; this is the fix, pinned.

        A declaration kind is unteachable from prose alone — the field
        block *is* the concept for an author — so a kind whose record
        carries no skeleton fails here.
        """
        for kind in sorted(parser_declaration_kinds()):
            record = concepts[f"concept:{kind}"]
            assert record.syntax, f"{record.id} teaches a declaration kind with no syntax"
            assert record.syntax[0].startswith(kind), (
                f"{record.id} opens its skeleton with {record.syntax[0]!r}, which is "
                f"not the {kind!r} header a person writes"
            )

    def test_the_floors_are_met(self, live: ProviderResult) -> None:
        counts = live.counts()
        assert counts["concepts"] >= CONCEPT_FLOOR
        assert counts["authorities"] >= ANCHOR_FLOOR
        for (provider_id, group), floor in LANGUAGE_FLOORS.items():
            assert provider_id == live.provider_id
            assert counts[group] >= floor


# ---------------------------------------------------------------------------
# The anchors
# ---------------------------------------------------------------------------


class TestAuthorityAnchors:
    """Every citation names a real section of a document that has not moved."""

    def test_every_anchor_resolves_to_exactly_one_heading(
        self, anchors: dict[str, AuthorityRef], authored: dict[str, Any]
    ) -> None:
        recorded = {item["id"]: item["heading"] for item in authored["authorities"]}
        for identifier, authority in sorted(anchors.items()):
            text = (REPO_ROOT / authority.source).read_text(encoding="utf-8")
            headings = headings_by_number(text).get(authority.section, ())
            assert len(headings) == 1, (
                f"{identifier} cites section {authority.section} of "
                f"{authority.source}, which resolves to {len(headings)} headings"
            )
            assert headings[0] == recorded[identifier], (
                f"{identifier} records the heading as {recorded[identifier]!r} and it "
                f"now reads {headings[0]!r}"
            )

    def test_every_anchor_carries_the_live_digest_of_its_document(
        self, anchors: dict[str, AuthorityRef]
    ) -> None:
        """One file hash per file, the same discipline C4 keeps.

        Markdown sections are not separable byte ranges, so the honest unit
        is the document. Every anchor into one document therefore carries
        one digest, and it is the digest that document has right now.
        """
        per_source: dict[str, set[str]] = {}
        for authority in anchors.values():
            per_source.setdefault(authority.source, set()).add(authority.content_sha256)
        assert all(len(digests) == 1 for digests in per_source.values())
        for source, digests in per_source.items():
            text = (REPO_ROOT / source).read_text(encoding="utf-8")
            live = _sha256_of(text)
            assert digests == {live}

    def test_the_pinned_digest_matches_the_document(self, authored: dict[str, Any]) -> None:
        """The pin an author writes down, checked against the file itself."""
        for entry in authored["sources"]:
            text = (REPO_ROOT / entry["path"]).read_text(encoding="utf-8")
            assert entry["sha256"] == _sha256_of(text), (
                f"{entry['path']} has moved since its digest was pinned; re-read the "
                f"sections that cite it before re-pinning"
            )

    def test_every_anchor_declares_itself_a_specification_section(
        self, anchors: dict[str, AuthorityRef]
    ) -> None:
        for identifier, authority in sorted(anchors.items()):
            validate_id(identifier)
            assert authority.authority_class == "spec"
            assert identifier.startswith("authority:spec/")
            assert authority.delegates == ()
            assert authority.status == "Current"

    def test_no_anchor_collides_with_the_repository_provider(
        self, anchors: dict[str, AuthorityRef]
    ) -> None:
        """C4 owns the document's identity; this provider owns its sections.

        The two never claim one id, so they merge without a word between
        them. ``authority:spec/current`` is C4's and appears nowhere here.
        """
        repo_ids = {item.record.id for item in RepoProvider(root=REPO_ROOT).provide().records}
        assert "authority:spec/current" in repo_ids
        assert set(anchors) & repo_ids == set()

    def test_every_cited_authority_is_one_this_file_declares(
        self, concepts: dict[str, ConceptRecord], anchors: dict[str, AuthorityRef]
    ) -> None:
        for record in concepts.values():
            assert record.governed_by, f"{record.id} cites nothing"
            for cited in record.governed_by:
                assert cited in anchors

    def test_a_dead_citation_is_refused_with_its_json_path(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:nerve")
            document["records"][index]["governed_by"] = ["authority:spec/no-such-section"]

        root = tree(mutate)
        with pytest.raises(DocsConceptsError) as raised:
            ConceptsProvider.language(root).provide()
        message = str(raised.value)
        assert "records/" in message
        assert "governed_by/0" in message
        assert "authority:spec/no-such-section" in message

    def test_a_section_number_nothing_answers_to_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            document["authorities"][0]["section"] = "99.99"

        root = tree(mutate)
        with pytest.raises(DocsConceptsError, match="no heading numbered"):
            ConceptsProvider.language(root).provide()

    def test_an_ambiguous_section_number_is_refused_rather_than_guessed(
        self, tmp_path: Path
    ) -> None:
        """B4's discipline: a citation with two answers has none."""
        root = _copy_tree(tmp_path)
        spec = root / "packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md"
        spec.write_text(
            spec.read_text(encoding="utf-8") + "\n## 4.1 A second section, same number\n",
            encoding="utf-8",
            newline="\n",
        )
        with pytest.raises(DocsConceptsError, match="2 headings numbered"):
            ConceptsProvider.language(root).provide()


class TestStaleAnchors:
    """A document that moved is reported, and the record stays truthful."""

    def test_a_moved_document_is_reported_naming_every_section(
        self, tmp_path: Path
    ) -> None:
        root = _copy_tree(tmp_path)
        spec = root / "packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md"
        spec.write_text(spec.read_text(encoding="utf-8") + "\nOne more sentence.\n", "utf-8")
        provider = ConceptsProvider.language(root)
        findings = provider.findings()
        stale = [item for item in findings if item.code == DOC_AUTHORITY_STALE]
        assert len(stale) == 1
        assert "4.1 (authority:spec/nerve-declaration)" in stale[0].message
        assert "shasum -a 256" in stale[0].remediation
        assert "4.12.5 (authority:spec/drift-check)" in stale[0].message

    def test_the_record_carries_the_live_digest_even_when_the_pin_is_stale(
        self, tmp_path: Path
    ) -> None:
        """The finding says the pin is old; the record never lies about the file."""
        root = _copy_tree(tmp_path)
        spec = root / "packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md"
        spec.write_text(spec.read_text(encoding="utf-8") + "\nOne more sentence.\n", "utf-8")
        live = _sha256_of(spec.read_text(encoding="utf-8"))
        provider = ConceptsProvider.language(root)
        for item in provider.provide().records:
            if isinstance(item.record, AuthorityRef):
                assert item.record.content_sha256 == live

    def test_a_reworded_heading_is_reported_on_its_own(self, tmp_path: Path) -> None:
        """The number still resolves; the wording moved. Two different jobs."""
        root = _copy_tree(tmp_path)
        data = root / LANGUAGE_CONCEPTS
        document = json.loads(data.read_text(encoding="utf-8"))
        for entry in document["authorities"]:
            if entry["id"] == "authority:spec/drift-check":
                entry["heading"] = "4.12.5 Something Else Entirely"
        data.write_text(canonical_json(document), encoding="utf-8", newline="\n")
        findings = ConceptsProvider.language(root).findings()
        moved = [item for item in findings if item.code == DOC_AUTHORITY_STALE]
        assert len(moved) == 1
        assert "Something Else Entirely" in moved[0].message
        assert "Content Hashing and the Drift Check" in moved[0].message


# ---------------------------------------------------------------------------
# The relationship graph
# ---------------------------------------------------------------------------


class TestRelationships:
    """Typed edges: real vocabulary, real targets, symmetric where declared."""

    def test_the_vocabulary_is_closed_and_sorted(self) -> None:
        assert tuple(sorted(item.name for item in RELATIONS)) == RELATION_NAMES
        assert set(RELATION_NAMES) >= SYMMETRIC_RELATIONS
        assert SYMMETRIC_RELATIONS, "a graph with no symmetric relation cannot be checked"
        with pytest.raises(DocsConceptsError, match="closed"):
            relation_of("sort-of-like")

    def test_every_edge_is_a_pair_of_a_relation_and_a_concept(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        for record in concepts.values():
            for edge in record.related_concepts:
                assert len(edge) == 2, f"{record.id} declares {edge!r}"
                relation, target = edge
                assert relation in RELATION_NAMES
                assert target.startswith("concept:")

    def test_every_edge_is_sorted_and_declared_once(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        for record in concepts.values():
            edges = list(record.related_concepts)
            assert edges == sorted(edges)
            assert len(set(edges)) == len(edges)

    def test_every_target_resolves(self, concepts: dict[str, ConceptRecord]) -> None:
        for record in concepts.values():
            for _, target in record.related_concepts:
                assert target in concepts, f"{record.id} points at absent {target}"
                assert target != record.id

    def test_symmetric_relations_are_declared_from_both_ends(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        one_sided: list[str] = []
        for record in sorted(concepts.values(), key=lambda item: item.id):
            for relation, target in record.related_concepts:
                if relation not in SYMMETRIC_RELATIONS:
                    continue
                if (relation, record.id) not in concepts[target].related_concepts:
                    one_sided.append(f"{record.id} {relation} {target}")
        assert one_sided == []

    def test_the_graph_actually_carries_symmetric_edges(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """A file with no symmetric edge would pass the gate above vacuously."""
        symmetric = [
            (record.id, relation, target)
            for record in concepts.values()
            for relation, target in record.related_concepts
            if relation in SYMMETRIC_RELATIONS
        ]
        assert len(symmetric) >= 10

    def test_a_one_sided_symmetric_relation_is_reported(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:cell")
            record = document["records"][index]
            record["related_concepts"] = [
                edge for edge in record["related_concepts"] if edge[1] != "concept:nerve"
            ]

        findings = ConceptsProvider.language(tree(mutate)).findings()
        one_sided = [item for item in findings if item.code == DOC_RELATION_ONE_SIDED]
        assert len(one_sided) == 1
        assert "concept:nerve" in one_sided[0].message
        assert "concept:cell" in one_sided[0].message
        assert 'contrasts-with", "concept:nerve"' in one_sided[0].remediation

    def test_a_relation_word_outside_the_vocabulary_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:drift")
            document["records"][index]["related_concepts"] = [
                ["sort-of-like", "concept:nerve"]
            ]

        with pytest.raises(DocsConceptsError, match="closed"):
            ConceptsProvider.language(tree(mutate)).provide()

    def test_an_absent_target_is_refused_with_its_json_path(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:drift")
            document["records"][index]["related_concepts"] = [
                ["requires", "concept:no-such-thing"]
            ]

        with pytest.raises(DocsConceptsError) as raised:
            ConceptsProvider.language(tree(mutate)).provide()
        assert "related_concepts/0" in str(raised.value)
        assert "external_ids" in str(raised.value)

    def test_a_concept_may_not_relate_to_itself(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:drift")
            document["records"][index]["related_concepts"] = [["requires", "concept:drift"]]

        with pytest.raises(DocsConceptsError, match="itself"):
            ConceptsProvider.language(tree(mutate)).provide()

    def test_the_bundle_gate_reports_an_edge_no_provider_produced(
        self, live: ProviderResult
    ) -> None:
        """The validate-time half: resolution across the whole composition.

        Within one file the loader has already refused an unresolvable
        target, so this gate is proved against a bundle assembled by hand
        with one concept's edge pointing outside it.
        """
        from dataclasses import replace

        from s0ma_dsl.docs_model.records import BuildStamp, DocsBundle

        original = next(
            item.record for item in live.records if isinstance(item.record, ConceptRecord)
        )
        stranded = replace(
            original, related_concepts=(("requires", "concept:written-by-nobody"),)
        )
        bundle = DocsBundle(
            stamp=BuildStamp(schema=SCHEMA, release_version=RELEASE, snapshot_hash=""),
            authorities=(),
            concepts=(stranded,),
            surfaces=(),
            journeys=(),
            sequences=(),
            documents=(),
        )
        findings = check_concept_relations(bundle)
        assert [item.code for item in findings] == [DOC_CONCEPT_UNRESOLVED]
        assert "concept:written-by-nobody" in findings[0].message

    def test_the_bundle_gate_is_quiet_on_the_real_bundle(
        self, composition_bundle: Any
    ) -> None:
        assert check_concept_relations(composition_bundle) == []


# ---------------------------------------------------------------------------
# The teaching content
# ---------------------------------------------------------------------------


class TestTeachingContent:
    """What an author wrote, held to the rules an author agreed to."""

    def test_every_concept_carries_every_teaching_field(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        for record in concepts.values():
            for name in authored_prose_fields(ConceptRecord):
                written = getattr(record, name)
                assert isinstance(written, str)
                assert written.strip(), f"{record.id}.{name} is empty"
                assert "\n" not in written, f"{record.id}.{name} is more than one paragraph"

    def test_the_summary_is_shorter_than_the_definition(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """The bounded-channel short form is a short form or it is nothing.

        A channel that may only omit, never paraphrase, falls back to this
        field; a summary as long as the definition gives it nowhere to fall.
        """
        for record in concepts.values():
            assert len(record.summary) < len(record.plain_definition)

    def test_the_id_is_the_term(self, concepts: dict[str, ConceptRecord]) -> None:
        for record in concepts.values():
            slug = re.sub(r"[^a-z0-9]+", "-", record.term.lower()).strip("-")
            assert record.id == f"concept:{slug}"

    def test_every_teaching_field_passes_the_voice_gate(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        findings = [
            item for record in concepts.values() for item in check_voice(record, DATA.name)
        ]
        assert [item.message for item in findings] == []

    def test_the_voice_gate_catches_the_word_the_product_does_not_use(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """The gate has to be able to go red, or it proves nothing above."""
        from dataclasses import replace

        record = replace(
            concepts["concept:drift"],
            summary="The gap between the written record and the payload it describes.",
        )
        findings = check_voice(record, "somewhere.json")
        assert [item.code for item in findings] == [DOC_VOICE_VIOLATION]
        assert "summary" in findings[0].message
        assert "feedback data" in findings[0].remediation

    def test_the_voice_gate_reads_the_model_s_own_classification(self) -> None:
        """The field list is C1's, not this module's.

        ``syntax`` is authored *data* — a quotation of the language — and a
        voice rule applied to a quotation makes either a false quotation or
        a permanently failing gate. That boundary is what B4 found, and it
        lives in FIELD_CLASS rather than in a list here.
        """
        governed = authored_prose_fields(ConceptRecord)
        assert "summary" in governed
        assert "syntax" not in governed
        assert "related_concepts" not in governed
        assert "term" not in governed

    def test_the_forbidden_patterns_cover_the_product_names(self) -> None:
        labels = [label for label, _ in FORBIDDEN_IN_AUTHORED_PROSE]
        assert any("s0ma" in label for label in labels)
        assert any("studi0" in label for label in labels)

    def test_a_written_form_is_verbatim_and_never_blank(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        for record in concepts.values():
            for line in record.syntax:
                assert line.strip(), f"{record.id} carries a blank syntax line"
                assert line == line.rstrip()

    def test_a_blank_syntax_line_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:nerve")
            document["records"][index]["syntax"] = ["nerve <name> :: <LAYER>", "   "]

        with pytest.raises(DocsConceptsError, match="blank"):
            ConceptsProvider.language(tree(mutate)).provide()

    def test_no_concept_binds_an_example(self, concepts: dict[str, ConceptRecord]) -> None:
        """Recorded rather than assumed — see this module's own docstring.

        The one ``example`` declaration in product code demonstrates a
        product concept. Binding it to a declaration kind to fill the field
        would have made the corpus's only real binding a false one.
        """
        assert all(record.examples == () for record in concepts.values())


# ---------------------------------------------------------------------------
# Alternate terms
# ---------------------------------------------------------------------------


class TestAliases:
    """Alternate search terms, none invented, none colliding."""

    def test_every_alias_resolves_to_a_concept(
        self, provider: ConceptsProvider, concepts: dict[str, ConceptRecord]
    ) -> None:
        index = provider.alias_index()
        assert index.entries
        for alias, target in index.entries:
            validate_id(alias)
            assert alias not in concepts, f"{alias} is both a concept and an alias"
            assert index.canonical(alias) == target
            assert target in concepts

    def test_the_declaration_kind_aliases_are_the_specification_s_own_words(
        self,
        provider: ConceptsProvider,
        concepts: dict[str, ConceptRecord],
        anchors: dict[str, AuthorityRef],
    ) -> None:
        """"Aliases where real", proved rather than asserted.

        Each declaration kind's governing heading names the kind and then,
        in parentheses, says what it is in plain words — "(Observable
        Function)" for a nerve, "(Evaluator)" for a ganglion. Those are the
        aliases, so every one of them is derivable from a heading this
        suite has already verified resolves.
        """
        forward = dict(provider.alias_index().entries)
        proved = 0
        for kind in sorted(parser_declaration_kinds()):
            record = concepts[f"concept:{kind}"]
            for cited in record.governed_by:
                heading = _heading_of(anchors[cited])
                parenthetical = re.search(r"\(([^)]+)\)\s*$", heading)
                if parenthetical is None:
                    continue
                alias = "concept:" + re.sub(
                    r"[^a-z0-9]+", "-", parenthetical.group(1).lower()
                ).strip("-")
                if alias in forward:
                    assert forward[alias] == record.id
                    proved += 1
        assert proved >= 9, f"only {proved} declaration-kind aliases came from a heading"

    def test_an_alias_that_leads_nowhere_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            document["aliases"]["concept:whatever"] = "concept:no-such-thing"

        with pytest.raises(DocsConceptsError, match="leads nowhere"):
            ConceptsProvider.language(tree(mutate)).provide()

    def test_an_alias_that_is_also_a_concept_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            document["aliases"]["concept:drift"] = "concept:nerve"

        with pytest.raises(DocsConceptsError, match="one thing"):
            ConceptsProvider.language(tree(mutate)).provide()


# ---------------------------------------------------------------------------
# The file itself
# ---------------------------------------------------------------------------


class TestTheAuthoredFile:
    """The data file is the authored source, and it is canonical."""

    def test_the_file_is_in_canonical_form(self, authored: dict[str, Any]) -> None:
        assert DATA.read_text(encoding="utf-8") == canonical_json(authored)

    def test_the_file_is_utf8_with_line_feeds_and_one_trailing_newline(self) -> None:
        raw = DATA.read_bytes()
        raw.decode("utf-8")
        assert b"\r\n" not in raw
        assert raw.endswith(b"\n")
        assert not raw.endswith(b"\n\n")

    def test_the_file_declares_the_schema_and_the_domain(
        self, authored: dict[str, Any]
    ) -> None:
        assert authored["schema"] == CONCEPTS_SCHEMA
        assert authored["domain"] == LANGUAGE_DOMAIN

    def test_the_records_are_sorted_by_id(self, authored: dict[str, Any]) -> None:
        ids = [record["id"] for record in authored["records"]]
        assert ids == sorted(ids)

    def test_a_file_declaring_another_domain_is_refused(self, tmp_path: Path) -> None:
        root = _copy_tree(tmp_path)
        data = root / LANGUAGE_CONCEPTS
        document = json.loads(data.read_text(encoding="utf-8"))
        document["domain"] = "product"
        data.write_text(canonical_json(document), encoding="utf-8", newline="\n")
        with pytest.raises(DocsConceptsError, match="domain"):
            ConceptsProvider.language(root).provide()

    def test_a_file_declaring_another_schema_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            document["schema"] = "s0ma-docs-concepts@2"

        with pytest.raises(DocsConceptsError, match="schema"):
            ConceptsProvider.language(tree(mutate)).provide()

    def test_an_unexpected_key_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:drift")
            document["records"][index]["introduced_in"] = "0.19.0"

        with pytest.raises(DocsConceptsError, match="unexpected"):
            ConceptsProvider.language(tree(mutate)).provide()

    def test_an_unsorted_record_list_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            document["records"].reverse()

        with pytest.raises(DocsConceptsError, match="not sorted"):
            ConceptsProvider.language(tree(mutate)).provide()

    def test_an_absent_file_is_refused_by_name(self, tmp_path: Path) -> None:
        with pytest.raises(DocsConceptsError, match=LANGUAGE_CONCEPTS):
            ConceptsProvider.language(tmp_path).provide()

    def test_the_module_itself_is_utf8_with_line_feeds(self) -> None:
        raw = MODULE.read_bytes()
        raw.decode("utf-8")
        assert b"\r\n" not in raw

    def test_every_minted_code_says_where_it_came_from(self) -> None:
        assert set(MINTED_CODES) == {
            DOC_AUTHORITY_STALE,
            DOC_RELATION_ONE_SIDED,
            DOC_VOICE_VIOLATION,
        }
        for code, reason in MINTED_CODES.items():
            assert code.startswith("DOC_")
            assert "C5a" in reason


# ---------------------------------------------------------------------------
# Determinism and composition
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def composition_bundle() -> Any:
    core = CoreProvider()
    registry = ProviderRegistry.of(
        core,
        RepoProvider(root=REPO_ROOT),
        ConceptsProvider.language(REPO_ROOT),
    )
    return compose(registry, release_version=RELEASE).bundle


class TestDeterminism:
    """Same file, same records, same bytes."""

    def test_calling_twice_gives_the_same_records(self) -> None:
        provider = ConceptsProvider.language(REPO_ROOT)
        assert [item.record for item in provider.provide().records] == [
            item.record for item in provider.provide().records
        ]

    def test_two_providers_on_one_root_agree(self, live: ProviderResult) -> None:
        second = ConceptsProvider.language(REPO_ROOT).provide()
        assert [item.record for item in second.records] == [
            item.record for item in live.records
        ]

    def test_the_records_are_sorted_and_normalized(self, live: ProviderResult) -> None:
        ids = [item.record.id for item in live.records]
        assert ids == sorted(ids)
        assert len(set(ids)) == len(ids)

    def test_every_record_is_stamped_with_the_authored_file(
        self, live: ProviderResult
    ) -> None:
        """One source, and it is the file a person opens to change anything."""
        assert live.sources() == (
            (LANGUAGE_CONCEPTS, _sha256_of(DATA.read_text(encoding="utf-8"))),
        )
        for item in live.records:
            assert item.provenance.adapter_id == live.provider_id
            assert item.provenance.schema_version == SCHEMA

    def test_no_record_carries_an_absolute_path(self, live: ProviderResult) -> None:
        """INV-5: nothing a record holds names the machine that built it."""
        for item in live.records:
            for value in _strings_of(item.record):
                assert not value.startswith("/"), value
                assert "\\" not in value, value

    def test_a_serialized_bundle_is_byte_stable(self) -> None:
        first = compose(
            ProviderRegistry.of(ConceptsProvider.language(REPO_ROOT)),
            release_version=RELEASE,
        ).bundle
        second = compose(
            ProviderRegistry.of(ConceptsProvider.language(REPO_ROOT)),
            release_version=RELEASE,
        ).bundle
        assert serialize_bundle(first) == serialize_bundle(second)

    def test_a_concept_round_trips_through_the_canonical_form(self) -> None:
        """The two new fields survive the reader as well as the writer.

        ``related_concepts`` is a tuple of tuples, which is the one shape
        C1's reader supports in only its homogeneous form — so a concept
        with real relations round-tripping is the proof that the field was
        given a shape the model can actually read back.
        """
        from s0ma_dsl.docs_model.serialize import deserialize_bundle

        bundle = compose(
            ProviderRegistry.of(ConceptsProvider.language(REPO_ROOT)),
            release_version=RELEASE,
        ).bundle
        text = serialize_bundle(bundle)
        assert deserialize_bundle(text) == bundle
        assert any(record.related_concepts for record in bundle.concepts)
        assert any(record.syntax for record in bundle.concepts)


class TestComposition:
    """Three providers, one bundle, nothing wrong with it."""

    def test_core_repo_and_concepts_compose_with_zero_findings(self) -> None:
        core = CoreProvider()
        registry = ProviderRegistry.of(
            core,
            RepoProvider(root=REPO_ROOT),
            ConceptsProvider.language(REPO_ROOT),
        )
        composition = compose(registry, release_version=RELEASE)
        assert composition.findings == ()
        findings = validate_bundle(
            composition.bundle,
            results=composition.results,
            external_ids=core.external_ids(),
            floors=dict(LANGUAGE_FLOORS),
            # Core's twenty-nine MCP and Python surfaces declare no side
            # effects, and D5b's gate reads an empty tuple as the
            # unanswered question it is. The application's written
            # allowances are what say why those may be silent; a
            # composition that includes core and not them is asserting
            # zero findings with half the policy attached.
            allowances=SIDE_EFFECT_ALLOWANCES,
        )
        assert [item.rendered() for item in findings] == []

    def test_the_composed_bundle_holds_every_concept(
        self, composition_bundle: Any, concepts: dict[str, ConceptRecord]
    ) -> None:
        composed = {record.id for record in composition_bundle.concepts}
        assert composed == set(concepts)

    def test_registration_order_does_not_reach_the_bundle(self) -> None:
        core = CoreProvider()
        repo = RepoProvider(root=REPO_ROOT)
        concepts = ConceptsProvider.language(REPO_ROOT)
        forwards = compose(
            ProviderRegistry.of(core, repo, concepts), release_version=RELEASE
        ).bundle
        backwards = compose(
            ProviderRegistry.of(concepts, repo, core), release_version=RELEASE
        ).bundle
        assert serialize_bundle(forwards) == serialize_bundle(backwards)

    def test_the_provider_id_names_its_domain(self) -> None:
        assert ConceptsProvider.language(REPO_ROOT).provider_id == "concepts-language"
        assert ConceptsProvider(
            root=REPO_ROOT, relative=LANGUAGE_CONCEPTS, domain=LANGUAGE_DOMAIN
        ).provider_id == "concepts-language"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_of(text: str) -> str:
    import hashlib

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _copy_tree(tmp_path: Path) -> Path:
    """The concepts file plus every document it cites, copied for mutation."""
    document = json.loads(DATA.read_text(encoding="utf-8"))
    for entry in document["sources"]:
        target = tmp_path / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / entry["path"], target)
    out = tmp_path / LANGUAGE_CONCEPTS
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DATA, out)
    return tmp_path


def _heading_of(authority: AuthorityRef) -> str:
    text = (REPO_ROOT / authority.source).read_text(encoding="utf-8")
    headings = headings_by_number(text)[authority.section]
    assert len(headings) == 1
    return headings[0]


def _strings_of(value: Any) -> Iterator[str]:
    """Every string a record carries, however deeply nested."""
    import dataclasses

    if isinstance(value, str):
        yield value
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            yield from _strings_of(getattr(value, item.name))
    elif isinstance(value, tuple | list):
        for item in value:
            yield from _strings_of(item)
