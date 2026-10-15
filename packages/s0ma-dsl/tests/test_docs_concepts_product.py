"""Gates for C5b — the product concepts and the loader that reads them.

Milestone C5b of the docs-function plan (internal) §8, over
``docs/s0ma_src/concepts/product.json`` read through C5a's shared
``ConceptsProvider``. Where C5a teaches the language a person writes, this
file teaches the product that language serves: what s0ma is, the three
faculties of self-knowledge and the model they are exercised on, what it
means for hardware to be embodied, and the four working ideas a reader
meets in the documentation itself — the authored-vs-generated boundary, a
mirror, the drift gate, the release channel — plus the feedback path, whose
whole promise is that a person reads the report before it goes.

What these tests hold in place:

* **the vocabulary is complete where the PRD can prove it.** The three
  faculties are *derived* from the PRD's own §1 table rather than listed
  here, so a fourth faculty added to the product turns this suite red until
  somebody writes the concept that teaches it. Every product term that also
  carries a PRD glossary entry is required to cite that entry, and the list
  of glossary entries is read live from C4.
* **every citation is a written authority, and it resolves.** Nine of the
  twelve concepts cite requirement or glossary ids that C4 emits from the
  PRD; the three section anchors this file declares are checked against the
  live headings and the live digest. Nothing is cited that no provider
  produces.
* **the embodiment record uses the ratified words.** Hardware is
  *embodied* — brought inside the boundary as ordinary declared parts. The
  record says so, and never says the hardware was represented from outside
  the system; the two forbidden spellings are asserted by pattern over the
  record's own prose and over the whole file.
* **the two concept files are one graph.** Six of this file's edges point
  into the language concepts, and they are checked after composition, where
  both readings are visible at once.
* **it composes clean.** Core, the repository and both concept files
  compose to one bundle with zero findings from every gate C2 owns and from
  both concept providers' relation check.

**Why the anchors are what they are.** Nine concepts cite a requirement or
a glossary entry and need no explanation. Three are judgement calls,
recorded here because a reader deserves to see them rather than infer them:

* ``concept:embodiment`` cites ``authority:adr/repo.ADR-003`` first. **The
  PRD carries no embodiment requirement at all** — the word appears nowhere
  in it — and the decision that ratified both the mechanism and the word is
  the ADR. The nearest PRD ids are cited alongside it: FR-CORE-1 and
  ``glossary.component``, which together carry the "declared like every
  other part" claim the record rests on, and P-1, which is why being
  declared is load-bearing. Nothing was invented to fill the gap.
* ``concept:release-channel`` has no governing PRD id either. The channel
  rules for documentation builds are an owner decision recorded in the
  plan (D-8) and executed at H1, and a plan is not an authority this model
  cites. The three nearest PRD ids are cited instead: NFR-3 for the
  release identity a channel labels, FR-COM-4 for every released version
  staying installable, and FR-X-3 for the one place the PRD itself uses
  "historical" as a label on documentation.
* ``concept:mirror`` is governed by FR-MCP-3 and FR-MCP-10 — the
  requirement that the served guides resolve from an installed wheel and
  stay drift-gated against their in-repo sources. That is *why* a mirror
  exists rather than a definition of one; the PRD has no entry for the
  arrangement itself, and P-2 is cited for the rule it is an exception to.

**Why this file declares three PRD section anchors.** The loader requires
every concepts file to declare at least one cited section, and §1, §2 and
§3 of the PRD genuinely govern things no requirement id covers: the
three-faculty table, the drift problem the product exists against, and the
four-layer packaging. They are minted as ``authority:prd/section.<slug>``,
which is disjoint from every id C4 claims (``document``, the requirement
ids, and ``glossary.*``) by construction and by an assertion below — the
same arrangement C5a has with ``authority:spec/current``.

**Why no concept here binds an executable example.** The one ``example``
declaration in product code, ``describe_the_running_server``, lives in
``packages/s0ma-mcp/s0ma_src/tools.s0ma`` and demonstrates exactly what
``concept:self-model`` teaches. No provider in this phase reads the mcp
package, so binding it now would put a citation in the bundle that nothing
answers to. The binding belongs to the milestone that adds the mcp surface
provider, and it is recorded here so that milestone finds it.
"""

from __future__ import annotations

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
    CONCEPTS_DIR,
    CONCEPTS_SCHEMA,
    DOC_RELATION_ONE_SIDED,
    DOC_VOICE_VIOLATION,
    RELATION_NAMES,
    SYMMETRIC_RELATIONS,
    ConceptsProvider,
    DocsConceptsError,
    check_concept_relations,
    check_voice,
    headings_by_number,
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
from s0ma_dsl.docs_model.validate import DOC_GATE_VACUOUS, check_floors, validate_bundle
from tests import _internal_corpus

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from s0ma_dsl.docs_model.providers import ProviderResult

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The product domain and its file. Written here rather than imported
#: because the loader is C5a's and this milestone adds no Python source:
#: the domain name is the one thing a second configuration of that loader
#: contributes, and the file refuses to load under any other.
PRODUCT_DOMAIN = "product"
PRODUCT_CONCEPTS = f"{CONCEPTS_DIR}/{PRODUCT_DOMAIN}.json"

DATA = REPO_ROOT / PRODUCT_CONCEPTS
PRD = "references/s0ma-prd.md"
ADR_003 = "docs/adr/ADR-003-hardware-embodiment-foundation.md"
PLAN = "plans/complete/s0ma-doc-function-1.md"

RELEASE = "0.18.1"

#: Anti-vacuity floors for this file, each below the live count. Twelve
#: concepts and three section anchors are authored; a floor at the count
#: would turn the suite red the moment somebody writes a thirteenth. What
#: these catch is the failure that matters — a file that moved, or a
#: loader that has stopped seeing it.
PRODUCT_FLOORS: Mapping[tuple[str, str], int] = {
    (f"concepts-{PRODUCT_DOMAIN}", "concepts"): 8,
    (f"concepts-{PRODUCT_DOMAIN}", "authorities"): 2,
}

#: What the ratified hardware language forbids in this file's prose. The
#: owner's call is that hardware is *embodied*, never represented from
#: outside the system and never spoken of as something the product takes
#: on: those two framings put the hardware back outside the boundary, which
#: is the one thing the word exists to deny.
FORBIDDEN_HARDWARE_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("modeled", re.compile(r"\bmodell?ed\b", re.IGNORECASE)),
    ("modeling", re.compile(r"\bmodell?ing\b", re.IGNORECASE)),
    ("integrating", re.compile(r"\bintegrating\b", re.IGNORECASE)),
    ("adopting", re.compile(r"\badopting\b", re.IGNORECASE)),
)


# ---------------------------------------------------------------------------
# Facts derived from the PRD rather than written down here
# ---------------------------------------------------------------------------


def _section_of(text: str, heading: str) -> str:
    """One ``##`` section of a Markdown document, by its exact heading."""
    after = text.split(f"## {heading}", 1)
    assert len(after) == 2, f"{heading!r} is no longer a heading of the PRD"
    return after[1].split("\n## ", 1)[0]


def prd_faculties() -> frozenset[str]:
    """The faculties of self-knowledge, read from the PRD's own §1 table.

    Derived rather than listed, for C5a's reason: a fourth faculty added
    to the product should turn this suite red until somebody writes the
    concept that teaches it. The table's first column is bolded and the
    header row is not, so the pattern reads the rows and skips the header.
    """
    text = (REPO_ROOT / PRD).read_text(encoding="utf-8")
    found = re.findall(
        r"^\|\s*\*\*([A-Za-z]+)\*\*\s*\|", _section_of(text, "1. Vision"), re.MULTILINE
    )
    assert found, "the PRD's vision section no longer carries a faculty table"
    return frozenset(name.lower() for name in found)


def prd_glossary_rows() -> dict[str, str]:
    """The PRD glossary as ``{slug: meaning}``, emphasis marks removed.

    The ``Term`` column holds names and the ``Meaning`` column holds prose;
    only the first is slugged, and the second is returned as written so a
    test can look for the product's own wording in it.
    """
    text = (REPO_ROOT / PRD).read_text(encoding="utf-8")
    rows: dict[str, str] = {}
    for line in _section_of(text, "11. Glossary").split("\n"):
        found = re.match(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|\s*$", line)
        if found is not None:
            rows[_slug(found.group(1))] = found.group(2).replace("*", "")
    assert rows, "the PRD glossary no longer has bolded terms"
    return rows


def _slug(text: str) -> str:
    """A term as the slug an id carries — the loader's own rule."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def product_provider(root: Path) -> ConceptsProvider:
    """The product-concepts provider for a checkout at ``root``."""
    return ConceptsProvider(root=root, relative=PRODUCT_CONCEPTS, domain=PRODUCT_DOMAIN)


@pytest.fixture(scope="module")
def provider() -> ConceptsProvider:
    return product_provider(REPO_ROOT)


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


@pytest.fixture(scope="module")
def repo_authorities() -> dict[str, AuthorityRef]:
    """Every authority C4 emits, which is where this file's citations land."""
    return {
        item.record.id: item.record
        for item in RepoProvider(root=REPO_ROOT).provide().records
        if isinstance(item.record, AuthorityRef)
    }


@pytest.fixture()
def tree(tmp_path: Path) -> Callable[[Callable[[dict[str, Any]], None]], Path]:
    """A copy of just enough of the checkout to read this concepts file.

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
        out = tmp_path / PRODUCT_CONCEPTS
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
# The product vocabulary is complete where something can prove it
# ---------------------------------------------------------------------------


class TestProductVocabulary:
    """Coverage keyed on the PRD, never on a list kept here."""

    def test_every_faculty_the_prd_names_is_taught(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        faculties = prd_faculties()
        assert faculties == {"proprioception", "interoception", "metacognition"}
        for faculty in sorted(faculties):
            assert f"concept:{faculty}" in concepts, (
                f"the PRD names {faculty} as a faculty of self-knowledge and no "
                f"concept teaches it"
            )

    def test_every_faculty_is_part_of_the_umbrella_and_not_the_umbrella(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """The relationship the repositioning turns on, made structural."""
        assert "concept:self-knowledge" in concepts
        for faculty in sorted(prd_faculties()):
            record = concepts[f"concept:{faculty}"]
            assert ("part-of", "concept:self-knowledge") in record.related_concepts
            assert "self-knowledge" in record.plain_definition

    def test_the_faculties_are_told_apart_from_each_other(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """Three ideas one reader has to separate, so all three pairs say so."""
        faculties = sorted(f"concept:{name}" for name in prd_faculties())
        for identifier in faculties:
            others = {other for other in faculties if other != identifier}
            declared = {
                target
                for relation, target in concepts[identifier].related_concepts
                if relation == "contrasts-with"
            }
            assert declared == others

    def test_every_term_with_a_glossary_entry_cites_it(
        self, concepts: dict[str, ConceptRecord], repo_authorities: dict[str, AuthorityRef]
    ) -> None:
        """A concept the PRD defines must answer to the PRD's definition.

        The glossary list is read live from C4, so a term that gains an
        entry later is caught here rather than drifting quietly away from
        it.
        """
        glossary = {
            identifier.partition("glossary.")[2]
            for identifier in repo_authorities
            if identifier.startswith("authority:prd/glossary.")
        }
        proved = 0
        for record in concepts.values():
            slug = record.id.partition(":")[2]
            if slug not in glossary:
                continue
            cited = f"authority:prd/glossary.{slug}"
            assert cited in record.governed_by, (
                f"the PRD glossary defines {record.term} and {record.id} does "
                f"not cite {cited}"
            )
            proved += 1
        assert proved >= 5, f"only {proved} concepts were held to a glossary entry"

    def test_the_product_idea_and_the_model_are_taught_separately(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """Self-knowledge is the capability; the self-model is the artifact."""
        assert ("requires", "concept:self-model") in concepts[
            "concept:self-knowledge"
        ].related_concepts
        assert "self-model" in concepts["concept:self-knowledge"].do_not_use_when
        assert "self-knowledge" in concepts["concept:self-model"].do_not_use_when


# ---------------------------------------------------------------------------
# The anchors and the citations
# ---------------------------------------------------------------------------


class TestAuthorityAnchors:
    """Every citation names a written authority, and every one resolves."""

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
                f"{identifier} records the heading as {recorded[identifier]!r} and "
                f"it now reads {headings[0]!r}"
            )

    def test_every_anchor_carries_the_live_digest_of_its_document(
        self, anchors: dict[str, AuthorityRef]
    ) -> None:
        for authority in anchors.values():
            text = (REPO_ROOT / authority.source).read_text(encoding="utf-8")
            assert authority.content_sha256 == _sha256_of(text)

    def test_the_pinned_digest_matches_the_document(self, authored: dict[str, Any]) -> None:
        for entry in authored["sources"]:
            text = (REPO_ROOT / entry["path"]).read_text(encoding="utf-8")
            assert entry["sha256"] == _sha256_of(text), (
                f"{entry['path']} has moved since its digest was pinned; re-read "
                f"the sections that cite it before re-pinning"
            )

    def test_every_anchor_declares_itself_a_prd_section(
        self, anchors: dict[str, AuthorityRef]
    ) -> None:
        for identifier, authority in sorted(anchors.items()):
            validate_id(identifier)
            assert authority.authority_class == "prd"
            assert identifier.startswith("authority:prd/section.")
            assert authority.source == PRD
            assert authority.delegates == ()
            assert authority.status == "Current"

    def test_no_anchor_collides_with_the_repository_provider(
        self, anchors: dict[str, AuthorityRef], repo_authorities: dict[str, AuthorityRef]
    ) -> None:
        """C4 owns the PRD's identity and its ids; this file owns three sections.

        The two never claim one id, so they merge without a word between
        them — the arrangement C5a has with ``authority:spec/current``.
        """
        assert "authority:prd/document" in repo_authorities
        assert set(anchors) & set(repo_authorities) == set()

    def test_every_declared_anchor_is_cited_by_a_concept(
        self, anchors: dict[str, AuthorityRef], concepts: dict[str, ConceptRecord]
    ) -> None:
        """A section anchor nobody cites is a pin nobody re-reads."""
        cited = {item for record in concepts.values() for item in record.governed_by}
        assert set(anchors) <= cited

    def test_every_citation_resolves_here_or_in_the_repository_provider(
        self,
        concepts: dict[str, ConceptRecord],
        anchors: dict[str, AuthorityRef],
        repo_authorities: dict[str, AuthorityRef],
    ) -> None:
        """The seam: what this file declares, plus what C4 promises to emit."""
        for record in concepts.values():
            assert record.governed_by, f"{record.id} cites nothing"
            for item in record.governed_by:
                assert item in anchors or item in repo_authorities, (
                    f"{record.id} cites {item}, which neither this file declares "
                    f"nor the repository provider emits"
                )

    def test_every_citation_is_a_prd_id_or_the_one_ratifying_decision(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """``governed_by`` is the PRD, with one recorded exception.

        The plan says PRD ids; the PRD carries no embodiment requirement,
        and the decision that ratified both the mechanism and the word is
        ADR-003. That exception is named here so it stays one exception.
        """
        elsewhere = {
            (record.id, item)
            for record in concepts.values()
            for item in record.governed_by
            if not item.startswith("authority:prd/")
        }
        assert elsewhere == {("concept:embodiment", "authority:adr/repo.ADR-003")}

    def test_the_external_citations_are_the_ones_the_file_promises(
        self,
        concepts: dict[str, ConceptRecord],
        authored: dict[str, Any],
        provider: ConceptsProvider,
    ) -> None:
        promised = set(provider.external_ids())
        assert promised == set(authored["external_ids"])
        cited = {
            item
            for record in concepts.values()
            for item in record.governed_by
            if item.startswith("authority:")
        }
        assert cited - promised <= {item["id"] for item in authored["authorities"]}

    def test_a_dead_citation_is_refused_with_its_json_path(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:self-model")
            document["records"][index]["governed_by"] = ["authority:prd/no-such-thing"]

        with pytest.raises(DocsConceptsError) as raised:
            product_provider(tree(mutate)).provide()
        message = str(raised.value)
        assert "records/" in message
        assert "governed_by/0" in message
        assert "authority:prd/no-such-thing" in message

    def test_a_citation_dropped_from_external_ids_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        """The seam only holds if an unpromised citation fails loudly."""

        def mutate(document: dict[str, Any]) -> None:
            document["external_ids"] = [
                item for item in document["external_ids"] if item != "authority:prd/INV-1"
            ]

        with pytest.raises(DocsConceptsError, match="external_ids"):
            product_provider(tree(mutate)).provide()

    def test_a_section_number_nothing_answers_to_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            document["authorities"][0]["section"] = "99.99"

        with pytest.raises(DocsConceptsError, match="no heading numbered"):
            product_provider(tree(mutate)).provide()


# ---------------------------------------------------------------------------
# The embodiment record and the words the owner ratified
# ---------------------------------------------------------------------------


class TestEmbodiment:
    """Hardware is embodied. The record has to say it, and only that."""

    def test_the_record_teaches_the_word(self, concepts: dict[str, ConceptRecord]) -> None:
        record = concepts["concept:embodiment"]
        written = _prose_of(record)
        assert re.search(r"\bembodied\b", written), (
            "the embodiment record never uses the word the concept is named for"
        )
        assert re.search(r"\bembodied\b", record.use_when)

    def test_the_record_never_puts_the_hardware_back_outside(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """The grep that matters: the two framings the owner rejected.

        Hardware described from outside the system, or spoken of as
        something the product takes on, is hardware outside the boundary —
        which is precisely what the ratified word denies.
        """
        written = _prose_of(concepts["concept:embodiment"])
        for label, pattern in FORBIDDEN_HARDWARE_WORDS:
            found = pattern.search(written)
            assert found is None, (
                f"the embodiment record says {found.group(0)!r}, which is the "
                f"{label} framing the owner rejected: hardware is embodied, "
                f"brought inside the boundary as ordinary declared parts"
            )
        assert "outside the boundary" in written

    def test_no_record_in_this_file_uses_the_rejected_framings(self) -> None:
        """The same grep over the whole authored file, not one record."""
        text = DATA.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN_HARDWARE_WORDS:
            found = pattern.search(text)
            assert found is None, f"{found.group(0)!r} ({label}) appears in {PRODUCT_CONCEPTS}"

    def test_the_record_cites_the_decision_that_ratified_the_word(
        self, concepts: dict[str, ConceptRecord], repo_authorities: dict[str, AuthorityRef]
    ) -> None:
        """The PRD has no embodiment id; ADR-003 is the written authority.

        Asserted against the live ADR record rather than trusted: the
        decision has to still be accepted, and the document it points at
        has to still use the word.
        """
        record = concepts["concept:embodiment"]
        assert "authority:adr/repo.ADR-003" in record.governed_by
        adr = repo_authorities["authority:adr/repo.ADR-003"]
        assert adr.status.startswith("Accepted")
        assert adr.source == ADR_003
        assert "embodied" in (REPO_ROOT / ADR_003).read_text(encoding="utf-8")

    def test_the_prd_now_carries_the_word_and_the_record_is_anchored_on_it(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """The gap closed in PRD v1.10: FR-X-4 plus a glossary entry.

        Inverted from the pin that asserted the gap, exactly as that pin's
        own docstring prescribed. The PRD must keep saying "embodied", and
        the record must answer to the ids it gained.
        """
        text = (REPO_ROOT / PRD).read_text(encoding="utf-8")
        assert re.search(r"\bembodied\b", text, re.IGNORECASE)
        record = concepts["concept:embodiment"]
        assert "authority:prd/FR-X-4" in record.governed_by
        assert "authority:prd/glossary.embodiment" in record.governed_by

    def test_the_record_names_the_declaration_kinds_it_reuses(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """ADR-003's first decision: no new declaration kind, ever.

        The record's edges are the proof — it requires the existing kinds
        rather than teaching a hardware declaration that does not exist.
        """
        record = concepts["concept:embodiment"]
        targets = {target for relation, target in record.related_concepts}
        assert {"concept:integration", "concept:nerve", "concept:cell"} <= targets
        for kind in ("integration", "nerve", "cell"):
            assert kind in record.plain_definition


# ---------------------------------------------------------------------------
# The relationship graph, within this file and across the seam
# ---------------------------------------------------------------------------


class TestRelationships:
    """Typed edges: closed vocabulary, real targets, honest symmetry."""

    def test_every_edge_uses_the_closed_vocabulary(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        for record in concepts.values():
            for relation, _ in record.related_concepts:
                assert relation in RELATION_NAMES

    def test_every_target_is_declared_here_or_promised(
        self, concepts: dict[str, ConceptRecord], provider: ConceptsProvider
    ) -> None:
        known = set(concepts) | set(provider.external_ids())
        for record in concepts.values():
            for _, target in record.related_concepts:
                assert target in known
                assert target != record.id

    def test_the_file_reaches_into_the_language_concepts(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """The product concepts are not a separate island."""
        crossing = {
            (record.id, relation, target)
            for record in concepts.values()
            for relation, target in record.related_concepts
            if target not in concepts
        }
        assert len(crossing) >= 6
        assert ("concept:drift-gate", "requires", "concept:drift") in crossing

    def test_no_symmetric_edge_crosses_into_the_language_file(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """C5a's constraint, kept structurally rather than by memory.

        A symmetric relation has to be declared from both ends, and this
        milestone may not edit ``language.json`` — so every edge that
        leaves this file uses a relation that runs one way.
        """
        for record in concepts.values():
            for relation, target in record.related_concepts:
                if target in concepts:
                    continue
                assert relation not in SYMMETRIC_RELATIONS, (
                    f"{record.id} declares the symmetric relation {relation} to "
                    f"{target}, which lives in another file that cannot declare "
                    f"it back"
                )

    def test_every_symmetric_edge_here_is_declared_from_both_ends(
        self, provider: ConceptsProvider
    ) -> None:
        one_sided = [
            item for item in provider.findings() if item.code == DOC_RELATION_ONE_SIDED
        ]
        assert [item.message for item in one_sided] == []

    def test_a_one_sided_symmetric_edge_is_reported(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        """The gate has to be able to go red, or it proves nothing above."""

        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:interoception")
            document["records"][index]["related_concepts"] = [
                pair
                for pair in document["records"][index]["related_concepts"]
                if pair != ["contrasts-with", "concept:proprioception"]
            ]

        findings = product_provider(tree(mutate)).findings()
        one_sided = [item for item in findings if item.code == DOC_RELATION_ONE_SIDED]
        assert len(one_sided) == 1
        assert "concept:proprioception" in one_sided[0].message
        assert "concept:interoception" in one_sided[0].message

    def test_a_relation_word_outside_the_vocabulary_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:mirror")
            document["records"][index]["related_concepts"] = [
                ["is-kind-of", "concept:drift-gate"]
            ]

        with pytest.raises(DocsConceptsError, match="closed"):
            product_provider(tree(mutate)).provide()

    def test_a_target_nothing_answers_to_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:mirror")
            document["records"][index]["related_concepts"] = [
                ["requires", "concept:no-such-concept"]
            ]

        with pytest.raises(DocsConceptsError, match="external_ids"):
            product_provider(tree(mutate)).provide()


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
        """The bounded-channel short form is a short form or it is nothing."""
        for record in concepts.values():
            assert len(record.summary) < len(record.plain_definition)

    def test_the_id_is_the_term(self, concepts: dict[str, ConceptRecord]) -> None:
        for record in concepts.values():
            assert record.id == f"concept:{_slug(record.term)}"

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
            concepts["concept:feedback"],
            summary="A payload sent to the people who make the product.",
        )
        findings = check_voice(record, "somewhere.json")
        assert [item.code for item in findings] == [DOC_VOICE_VIOLATION]
        assert "summary" in findings[0].message
        assert "feedback data" in findings[0].remediation

    def test_the_feedback_record_says_what_it_is_allowed_to_say(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """FR-FB-11 is product language, so it is asserted as language.

        The reviewed-before-sent promise and the refusal of the word
        "anonymous" are the two things a reader must take away, and both
        are checked rather than trusted to survive an edit.
        """
        record = concepts["concept:feedback"]
        written = _prose_of(record)
        assert "approve" in written or "approved" in written
        assert "pseudonymous" in record.do_not_use_when
        assert "locally redacted" in record.do_not_use_when
        assert "anonymous" in record.do_not_use_when
        assert "feedback data" in written
        assert "authority:prd/FR-FB-11" in record.governed_by

    def test_the_product_names_are_spelled_with_a_digit_zero(self) -> None:
        """INV-1 over the whole authored file, not only the prose fields."""
        text = DATA.read_text(encoding="utf-8")
        assert not re.search(r"\bs[o]ma\b", text, re.IGNORECASE)
        assert not re.search(r"\bstudi[o]\b", text, re.IGNORECASE)
        assert "s0ma" in text

    def test_no_concept_declares_a_written_form(
        self, concepts: dict[str, ConceptRecord]
    ) -> None:
        """A product idea has no syntax; only a declaration kind does.

        ``syntax`` stays empty here by design — inventing a skeleton for
        "self-knowledge" would put a written form in the model that no
        parser would accept.
        """
        assert all(record.syntax == () for record in concepts.values())

    def test_no_concept_binds_an_example(self, concepts: dict[str, ConceptRecord]) -> None:
        """Recorded rather than assumed — see this module's own docstring.

        The one product-code example lives in the mcp package, which no
        provider in this phase reads; binding it now would put a citation
        in the bundle that nothing answers to.
        """
        assert all(record.examples == () for record in concepts.values())
        example = REPO_ROOT / "packages/s0ma-mcp/s0ma_src/tools.s0ma"
        assert "example describe_the_running_server" in example.read_text(encoding="utf-8")


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

    def test_no_alias_collides_with_the_language_file(
        self, provider: ConceptsProvider
    ) -> None:
        """Two files, one concept namespace: an alias may not shadow a concept."""
        language = ConceptsProvider.language(REPO_ROOT)
        others = {
            item.record.id
            for item in language.provide().records
            if isinstance(item.record, ConceptRecord)
        }
        mine = dict(provider.alias_index().entries)
        assert set(mine) & others == set()
        assert set(mine) & set(dict(language.alias_index().entries)) == set()

    def test_the_faculty_aliases_are_the_prd_s_own_words(
        self, provider: ConceptsProvider
    ) -> None:
        """"Aliases where real", proved rather than asserted.

        Each faculty's glossary row opens "The <sense> faculty of
        self-knowledge", and that phrase is the alias. Interoception's row
        names two senses at once ("internal/runtime-state"), so the alias
        is the tail of the derived slug rather than the whole of it — the
        one relaxation, and it is why this compares by suffix.
        """
        forward = dict(provider.alias_index().entries)
        rows = prd_glossary_rows()
        proved = 0
        for faculty in sorted(prd_faculties()):
            found = re.search(r"[Tt]he (.+?) faculty", rows[faculty])
            assert found is not None, f"the {faculty} glossary row no longer names a faculty"
            derived = _slug(f"{found.group(1)} faculty")
            aliases = [
                alias
                for alias, target in forward.items()
                if target == f"concept:{faculty}"
                and derived.endswith(alias.partition(":")[2])
            ]
            assert aliases, (
                f"the PRD calls {faculty} the {derived.replace('-', ' ')} and no "
                f"alias reaches the concept by that name"
            )
            proved += len(aliases)
        assert proved == 3

    def test_every_other_alias_is_a_phrase_the_repository_uses(
        self, provider: ConceptsProvider
    ) -> None:
        """No alias is invented: each is a phrase somebody already writes.

        The PRD carries four of them, the ratifying ADR one, and the
        owner's standing voice rule — recorded in the plan — the last. A
        term nobody uses is a search key nobody types.
        """
        expected = {
            "concept:authored-vs-derived-split": (PRD, "authored-vs-derived split"),
            "concept:check-drift": (PRD, "check-drift"),
            "concept:software-self-knowledge": (PRD, "software self-knowledge"),
            "concept:embodied-hardware": (ADR_003, "embodied"),
            "concept:feedback-report": (PLAN, "feedback report"),
        }
        _internal_corpus.internal_document(
            PLAN, what="the docs-function initiative's plan"
        )
        forward = dict(provider.alias_index().entries)
        assert set(expected) <= set(forward)
        for alias, (path, phrase) in sorted(expected.items()):
            assert phrase in (REPO_ROOT / path).read_text(encoding="utf-8"), (
                f"{alias} is meant to be the phrase {phrase!r} from {path}, and "
                f"that phrase is no longer there"
            )
        assert set(forward) - set(expected) == {
            f"concept:{_slug(faculty)}-faculty"
            for faculty in ("structural", "runtime-state", "reasoning")
        }

    def test_an_alias_that_leads_nowhere_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            document["aliases"]["concept:whatever"] = "concept:no-such-thing"

        with pytest.raises(DocsConceptsError, match="leads nowhere"):
            product_provider(tree(mutate)).provide()


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
        assert authored["domain"] == PRODUCT_DOMAIN

    def test_the_file_sits_where_concept_files_live(self) -> None:
        assert PRODUCT_CONCEPTS.startswith(f"{CONCEPTS_DIR}/")
        assert PRODUCT_CONCEPTS.endswith(f"/{PRODUCT_DOMAIN}.json")
        assert DATA.is_file()

    def test_the_records_and_the_promises_are_sorted(
        self, authored: dict[str, Any]
    ) -> None:
        ids = [record["id"] for record in authored["records"]]
        assert ids == sorted(ids)
        assert authored["external_ids"] == sorted(authored["external_ids"])
        for record in authored["records"]:
            assert record["governed_by"] == sorted(record["governed_by"])
            assert record["related_concepts"] == sorted(record["related_concepts"])

    def test_a_file_declaring_another_domain_is_refused(self, tmp_path: Path) -> None:
        root = _copy_tree(tmp_path)
        data = root / PRODUCT_CONCEPTS
        document = json.loads(data.read_text(encoding="utf-8"))
        document["domain"] = "language"
        data.write_text(canonical_json(document), encoding="utf-8", newline="\n")
        with pytest.raises(DocsConceptsError, match="domain"):
            product_provider(root).provide()

    def test_an_unexpected_key_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            index = _index_of(document, "concept:s0ma")
            document["records"][index]["tagline"] = "software that knows itself"

        with pytest.raises(DocsConceptsError, match="unexpected"):
            product_provider(tree(mutate)).provide()

    def test_an_unsorted_record_list_is_refused(
        self, tree: Callable[[Callable[[dict[str, Any]], None]], Path]
    ) -> None:
        def mutate(document: dict[str, Any]) -> None:
            document["records"].reverse()

        with pytest.raises(DocsConceptsError, match="not sorted"):
            product_provider(tree(mutate)).provide()

    def test_an_absent_file_is_refused_by_name(self, tmp_path: Path) -> None:
        with pytest.raises(DocsConceptsError, match=PRODUCT_CONCEPTS):
            product_provider(tmp_path).provide()


# ---------------------------------------------------------------------------
# Determinism and composition
# ---------------------------------------------------------------------------


def _registry() -> ProviderRegistry:
    """Core, the repository and both concept files — the C5b composition."""
    return ProviderRegistry.of(
        CoreProvider(),
        RepoProvider(root=REPO_ROOT),
        ConceptsProvider.language(REPO_ROOT),
        product_provider(REPO_ROOT),
    )


@pytest.fixture(scope="module")
def composition() -> Any:
    return compose(_registry(), release_version=RELEASE)


class TestDeterminism:
    """Same file, same records, same bytes."""

    def test_calling_twice_gives_the_same_records(self) -> None:
        provider = product_provider(REPO_ROOT)
        assert [item.record for item in provider.provide().records] == [
            item.record for item in provider.provide().records
        ]

    def test_two_providers_on_one_root_agree(self, live: ProviderResult) -> None:
        second = product_provider(REPO_ROOT).provide()
        assert [item.record for item in second.records] == [
            item.record for item in live.records
        ]

    def test_the_records_are_sorted_and_unique(self, live: ProviderResult) -> None:
        ids = [item.record.id for item in live.records]
        assert ids == sorted(ids)
        assert len(set(ids)) == len(ids)

    def test_every_record_is_stamped_with_the_authored_file(
        self, live: ProviderResult
    ) -> None:
        """One source, and it is the file a person opens to change anything."""
        assert live.sources() == (
            (PRODUCT_CONCEPTS, _sha256_of(DATA.read_text(encoding="utf-8"))),
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
        first = compose(_registry(), release_version=RELEASE).bundle
        second = compose(_registry(), release_version=RELEASE).bundle
        assert serialize_bundle(first) == serialize_bundle(second)

    def test_registration_order_does_not_reach_the_bundle(self) -> None:
        core = CoreProvider()
        repo = RepoProvider(root=REPO_ROOT)
        language = ConceptsProvider.language(REPO_ROOT)
        product = product_provider(REPO_ROOT)
        forwards = compose(
            ProviderRegistry.of(core, repo, language, product), release_version=RELEASE
        ).bundle
        backwards = compose(
            ProviderRegistry.of(product, language, repo, core), release_version=RELEASE
        ).bundle
        assert serialize_bundle(forwards) == serialize_bundle(backwards)


class TestComposition:
    """Four providers, one bundle, nothing wrong with it."""

    def test_the_whole_composition_has_zero_findings(self, composition: Any) -> None:
        assert composition.findings == ()
        findings = validate_bundle(
            composition.bundle,
            results=composition.results,
            external_ids=CoreProvider().external_ids(),
            floors=dict(PRODUCT_FLOORS),
            # Core's twenty-nine MCP and Python surfaces declare no side
            # effects, and D5b's gate reads an empty tuple as the
            # unanswered question it is. The application's written
            # allowances say why those may be silent.
            allowances=SIDE_EFFECT_ALLOWANCES,
        )
        assert [item.rendered() for item in findings] == []

    def test_both_concept_providers_report_a_holding_graph(
        self, composition: Any, provider: ConceptsProvider
    ) -> None:
        """The relation check is run from both readings, not just this one."""
        assert [item.rendered() for item in check_concept_relations(composition.bundle)] == []
        assert [item.rendered() for item in provider.findings()] == []
        assert [
            item.rendered() for item in ConceptsProvider.language(REPO_ROOT).findings()
        ] == []

    def test_the_bundle_holds_both_domains(
        self, composition: Any, concepts: dict[str, ConceptRecord]
    ) -> None:
        composed = {record.id for record in composition.bundle.concepts}
        language = {
            item.record.id
            for item in ConceptsProvider.language(REPO_ROOT).provide().records
            if isinstance(item.record, ConceptRecord)
        }
        assert set(concepts) <= composed
        assert language <= composed
        assert set(concepts) & language == set()
        assert composed == set(concepts) | language

    def test_every_cross_file_edge_resolves_in_the_bundle(
        self, composition: Any, concepts: dict[str, ConceptRecord]
    ) -> None:
        addressed = {record.id for record in composition.bundle.concepts}
        crossing = [
            (record.id, relation, target)
            for record in concepts.values()
            for relation, target in record.related_concepts
            if target not in concepts
        ]
        assert crossing
        for _, _, target in crossing:
            assert target in addressed

    def test_every_citation_resolves_in_the_bundle(
        self, composition: Any, concepts: dict[str, ConceptRecord]
    ) -> None:
        addressed = {record.id for record in composition.bundle.authorities}
        for record in concepts.values():
            for cited in record.governed_by:
                assert cited in addressed, f"{record.id} cites {cited}, which is absent"

    def test_the_provider_id_names_its_domain(self) -> None:
        assert product_provider(REPO_ROOT).provider_id == f"concepts-{PRODUCT_DOMAIN}"
        assert (
            product_provider(REPO_ROOT).provider_id
            != ConceptsProvider.language(REPO_ROOT).provider_id
        )

    def test_the_floors_are_honest_minimums(self, live: ProviderResult) -> None:
        """Below the live counts, and armed: a floor at the count would lie."""
        counts = {
            "concepts": sum(
                1 for item in live.records if isinstance(item.record, ConceptRecord)
            ),
            "authorities": sum(
                1 for item in live.records if isinstance(item.record, AuthorityRef)
            ),
        }
        for (_, group), floor in PRODUCT_FLOORS.items():
            assert 0 < floor < counts[group], (
                f"the {group} floor of {floor} is not below the live count of "
                f"{counts[group]}"
            )
        assert check_floors([live], dict(PRODUCT_FLOORS)) == []

    def test_a_floor_above_the_live_count_goes_red(self, live: ProviderResult) -> None:
        """Proof the floors above are checked rather than decorative."""
        findings = check_floors(
            [live], {(f"concepts-{PRODUCT_DOMAIN}", "concepts"): 10_000}
        )
        assert [item.code for item in findings] == [DOC_GATE_VACUOUS]


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
    out = tmp_path / PRODUCT_CONCEPTS
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DATA, out)
    return tmp_path


def _prose_of(record: ConceptRecord) -> str:
    """Every authored prose field of one record, as one body of text."""
    return " ".join(getattr(record, name) for name in authored_prose_fields(ConceptRecord))


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
