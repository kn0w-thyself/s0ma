"""Gates for C4 — the repository and governance provider.

Milestone C4 of the docs-function plan (internal) §8, over
``s0ma_dsl.docs_model.providers_repo``. What these tests hold in place:

* **the index is complete.** Every ADR in every tree is present with its
  current decision — the dsl tree's superseded ADR-004 visible as
  ``Superseded``, the new 012/013 as ``Accepted``, and the one in
  ``packages/s0ma-mcp/docs/adr`` that no index lists present at all. Every
  frozen contract, the current specification, the release, and the four
  distributions likewise.
* **a change to a source moves the records that cite it.** The hash a PRD
  record carries is the PRD's, so an edit anywhere in the PRD re-stamps
  every PRD record and nothing else. Proved against a copied tree rather
  than by editing the repository.
* **the delegation is real.** FR-DSL-1 hands the language domain to the
  specification, the handover is cited, and the authority comparison
  actually follows it.
* **the output is deterministic.** Same checkout, same records, same
  bytes; no absolute path anywhere; no wall clock anywhere.
* **it composes clean.** The provider's records pass every C2 gate with
  zero findings, which is what makes them usable as the thing everything
  else cites.

The live repository is the fixture for the counting tests, on purpose: an
index of *this* repository's authority that agreed with a synthetic tree
and disagreed with the checkout would be worthless. The floors are honest
minimums, not pins — they are set below the live counts so that ordinary
authoring never turns a green suite red, and far above what a provider
that has stopped seeing its sources produces.
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.docs_model.compose import compose
from s0ma_dsl.docs_model.ids import validate_id
from s0ma_dsl.docs_model.providers import (
    DocsProviderError,
    ProviderRegistry,
    ProviderResult,
    record_key,
)
from s0ma_dsl.docs_model.providers_repo import (
    CHANGELOG,
    CONTRACTS_DIR,
    DECISION_WORDS,
    LANGUAGE_DOMAIN,
    PRD,
    PRD_DELEGATIONS,
    PROVIDER_ID,
    REPOSITORY_FLOORS,
    UNKNOWN_DECISION,
    RepoProvider,
    decision_of,
    facts_of,
    status_line,
)
from s0ma_dsl.docs_model.records import (
    AUTHORITY_ORDER,
    SCHEMA,
    AuthorityRef,
    DocsModelError,
)
from s0ma_dsl.docs_model.serialize import serialize_bundle
from s0ma_dsl.docs_model.validate import AuthorityClaim, governing_authority, validate_bundle

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "s0ma_dsl"
    / "docs_model"
    / "providers_repo.py"
)

RELEASE = "0.18.1"

# ---------------------------------------------------------------------------
# Floors
#
# Honest minimums for this repository, each below the live count. A floor
# that equalled the count would be a pin: every new ADR and every new
# requirement would turn this suite red for no reason. A floor far below
# the count still catches the failure that matters — a source that moved
# and a provider that consequently reads nothing.
# ---------------------------------------------------------------------------

#: 83 requirement ids live (57 FR + 9 INV + 8 NFR + 9 P) plus 23 glossary
#: terms plus the document itself.
PRD_FLOOR = 90

#: 18 live: six in ``docs/adr``, eleven in the dsl tree, one in the mcp
#: tree. Every tree has to contribute.
ADR_FLOOR = {"repo": 5, "s0ma-dsl": 10, "s0ma-mcp": 1}

#: The four distributions, and nothing pretends there could be fewer.
PACKAGES = ("s0ma-core", "s0ma-dsl", "s0ma-mcp", "s0ma-studi0")


def _authorities(result: ProviderResult) -> tuple[AuthorityRef, ...]:
    """The result's records, typed. A repository record is a citation."""
    found: list[AuthorityRef] = []
    for item in result.records:
        assert isinstance(item.record, AuthorityRef), (
            f"{item.record.id} is a {type(item.record).__name__}; this provider "
            f"emits written authority and nothing else"
        )
        found.append(item.record)
    return tuple(found)


def _by_id(result: ProviderResult) -> dict[str, AuthorityRef]:
    return {record.id: record for record in _authorities(result)}


@pytest.fixture(scope="module")
def live() -> ProviderResult:
    """The provider's reading of this checkout, done once."""
    return RepoProvider(root=REPO_ROOT).provide()


@pytest.fixture(scope="module")
def index(live: ProviderResult) -> dict[str, AuthorityRef]:
    return _by_id(live)


# ---------------------------------------------------------------------------
# The status field's grammar
# ---------------------------------------------------------------------------


class TestStatusGrammar:
    """``<word>[; <key>=<value>]*`` — read back only through these."""

    def test_a_word_alone_is_a_status(self) -> None:
        assert status_line("Accepted") == "Accepted"
        assert decision_of("Accepted") == "Accepted"
        assert facts_of("Accepted") == {}

    def test_facts_are_written_in_sorted_order(self) -> None:
        """Sorted at the source, so two equal fact sets are one string."""
        one = status_line("Declared", {"version": "0.18.1", "depends": "s0ma-core"})
        two = status_line("Declared", {"depends": "s0ma-core", "version": "0.18.1"})
        assert one == two == "Declared; depends=s0ma-core; version=0.18.1"

    def test_the_facts_read_back(self) -> None:
        written = status_line("Accepted", {"tree": "repo", "index": "none"})
        assert decision_of(written) == "Accepted"
        assert facts_of(written) == {"tree": "repo", "index": "none"}

    @pytest.mark.parametrize("word", ["", "Accepted; x=1", "version=1"])
    def test_a_word_that_is_not_a_word_is_refused(self, word: str) -> None:
        """The separators cannot appear in the word or the grammar folds."""
        with pytest.raises(DocsProviderError):
            status_line(word)


# ---------------------------------------------------------------------------
# The contract every provider is held to
# ---------------------------------------------------------------------------


class TestProviderContract:
    """Architecture plan §7.1, at the points it is checkable."""

    def test_the_result_is_stamped_with_this_provider(self, live: ProviderResult) -> None:
        assert live.provider_id == PROVIDER_ID
        assert all(item.provenance.adapter_id == PROVIDER_ID for item in live.records)

    def test_every_record_names_the_schema_it_was_emitted_against(
        self, live: ProviderResult
    ) -> None:
        assert {item.provenance.schema_version for item in live.records} == {SCHEMA}

    def test_the_records_come_back_sorted(self, live: ProviderResult) -> None:
        """``ProviderResult`` refuses otherwise; this says so out loud."""
        assert list(live.records) == sorted(live.records, key=record_key)

    def test_every_id_is_valid_and_claimed_once(self, live: ProviderResult) -> None:
        ids = [record.id for record in _authorities(live)]
        for identifier in ids:
            assert validate_id(identifier) == "authority"
        assert len(ids) == len(set(ids))

    def test_the_class_and_the_id_agree(self, live: ProviderResult) -> None:
        """The disagreement C1 put the repeated field there to catch."""
        for record in _authorities(live):
            segment = record.id.partition(":")[2].partition("/")[0]
            assert segment == record.authority_class
            assert record.authority_class in AUTHORITY_ORDER

    def test_the_digest_is_a_full_sha256_of_the_named_file(
        self, live: ProviderResult
    ) -> None:
        """And the record's own digest equals its provenance's.

        Two digests of one file that differed in shape would read as a
        mismatch to every later gate, so they are one value.
        """
        for item in live.records:
            record = item.record
            assert isinstance(record, AuthorityRef)
            assert len(record.content_sha256) == 64
            assert record.content_sha256 == record.content_sha256.lower()
            assert int(record.content_sha256, 16) >= 0
            assert record.content_sha256 == item.provenance.source_sha256
            assert record.source == item.provenance.source

    def test_one_file_hash_is_shared_by_every_record_from_that_file(
        self, live: ProviderResult
    ) -> None:
        """Sections are not separable byte ranges; files are."""
        per_source: dict[str, set[str]] = {}
        for item in live.records:
            assert isinstance(item.record, AuthorityRef)
            per_source.setdefault(item.record.source, set()).add(item.record.content_sha256)
        assert all(len(digests) == 1 for digests in per_source.values())
        assert per_source[PRD] != set()

    def test_calling_twice_gives_the_same_records(self) -> None:
        """``provide()`` takes no arguments and reads nothing at call time."""
        provider = RepoProvider(root=REPO_ROOT)
        assert [item.record for item in provider.provide().records] == [
            item.record for item in provider.provide().records
        ]

    def test_two_providers_on_one_root_agree(self, live: ProviderResult) -> None:
        second = RepoProvider(root=REPO_ROOT).provide()
        assert [item.record for item in second.records] == [
            item.record for item in live.records
        ]

    def test_no_record_carries_an_absolute_path(self, live: ProviderResult) -> None:
        """INV-5: no artifact embeds an absolute machine path.

        Every string a record carries is checked, not only the two path
        fields, because a section anchor or a status fact copied from a
        path would embed the machine just as thoroughly.
        """
        machine = str(REPO_ROOT)
        for record in _authorities(live):
            for value in (record.id, record.source, record.section, record.status):
                assert machine not in value
                assert not value.startswith("/")
            assert not record.source.startswith("/")
            assert "\\" not in record.source

    def test_the_module_imports_nothing_it_should_not(self) -> None:
        """Stdlib and this model only — no core, no mcp, no studi0, no spikes.

        The D-4 guard, and ADR-012's placement rule: this provider reads
        files, so it needs no runtime at all. A test importing a spike
        would tie the shipped index to a script under ``scripts/``.
        """
        forbidden = ("s0ma.", "s0ma_mcp", "s0ma_studi0", "spike_", "scripts.")
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = [name for name in imported if name == "s0ma" or name.startswith(forbidden)]
        assert offenders == []

    def test_the_source_is_utf8_with_line_feeds(self) -> None:
        raw = MODULE.read_bytes()
        raw.decode("utf-8")
        assert b"\r\n" not in raw


# ---------------------------------------------------------------------------
# The product requirements
# ---------------------------------------------------------------------------


class TestRequirements:
    """Every numbered requirement in the PRD, addressable, once."""

    def test_the_families_are_all_represented(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        for identifier in (
            "authority:prd/FR-CORE-1",
            "authority:prd/FR-DSL-1",
            "authority:prd/FR-MCP-11",
            "authority:prd/FR-STUDI0-10",
            "authority:prd/FR-FB-12",
            "authority:prd/FR-COM-1",
            "authority:prd/FR-X-1",
            "authority:prd/INV-9",
            "authority:prd/NFR-8",
            "authority:prd/P-9",
        ):
            assert identifier in index, f"{identifier} is not in the authority index"

    def test_there_are_dozens_of_them(self, index: dict[str, AuthorityRef]) -> None:
        """An honest floor, well under the live count (107 PRD records)."""
        prd = [key for key in index if key.startswith("authority:prd/")]
        assert len(prd) >= PRD_FLOOR

    def test_a_requirement_names_the_section_it_lives_in(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        record = index["authority:prd/FR-DSL-1"]
        assert record.source == PRD
        assert record.section.startswith("7.2")
        assert "FR-DSL" in record.section

    def test_a_family_is_complete_and_stops_where_the_family_stops(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        numbers = {
            key.rsplit("-", 1)[1]
            for key in index
            if key.startswith("authority:prd/FR-FB-")
        }
        assert numbers == {str(number) for number in range(1, 13)}

    def test_every_requirement_reads_as_current(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        """One status word for all of them: the PRD marks no requirement
        individually, and inventing a per-requirement status out of the
        prose around it is the inference §7.6 refuses.
        """
        statuses = {
            record.status
            for key, record in index.items()
            if key.startswith("authority:prd/")
            and not key.startswith("authority:prd/glossary.")
            and key != "authority:prd/document"
        }
        assert statuses == {"Current"}

    def test_the_glossary_terms_are_addressable(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        """Including the four kinds that share one row, and studi0/sh0w."""
        for term in (
            "self-knowledge",
            "proprioception",
            "interoception",
            "metacognition",
            "nerve",
            "cell",
            "ganglion",
            "axon",
            "doc-ref",
            "doc-guide",
            "example",
            "studi0",
            "sh0w",
        ):
            assert f"authority:prd/glossary.{term}" in index

    def test_the_glossary_terms_all_point_at_the_glossary(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        sections = {
            record.section
            for key, record in index.items()
            if key.startswith("authority:prd/glossary.")
        }
        assert len(sections) == 1
        assert "glossary" in next(iter(sections)).lower()

    def test_the_document_itself_is_addressable_with_its_version(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        record = index["authority:prd/document"]
        assert record.section == ""
        assert decision_of(record.status) in DECISION_WORDS.values()
        assert facts_of(record.status)["version"][0].isdigit()


# ---------------------------------------------------------------------------
# The decisions
# ---------------------------------------------------------------------------


class TestDecisionRecords:
    """Every ADR of every tree, with the status it declares today."""

    def test_every_tracked_adr_file_has_a_record(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        """Derived from the filesystem, never from a list written here.

        A hardcoded list is how the mcp tree went missing in the first
        place: two indexes named two trees, and the third was nobody's.
        """
        on_disk = {
            path.resolve()
            for path in REPO_ROOT.glob("docs/adr/ADR-*.md")
            if path.is_file()
        } | {
            path.resolve()
            for path in REPO_ROOT.glob("packages/*/docs/adr/ADR-*.md")
            if path.is_file()
        }
        recorded = {
            (REPO_ROOT / record.source).resolve()
            for key, record in index.items()
            if key.startswith("authority:adr/")
        }
        assert recorded == on_disk

    def test_each_tree_contributes(self, index: dict[str, AuthorityRef]) -> None:
        counted: dict[str, int] = {}
        for key, record in index.items():
            if not key.startswith("authority:adr/"):
                continue
            tree = facts_of(record.status)["tree"]
            counted[tree] = counted.get(tree, 0) + 1
        for tree, floor in ADR_FLOOR.items():
            assert counted.get(tree, 0) >= floor, f"{tree} contributed {counted.get(tree, 0)}"

    def test_the_ids_are_tree_qualified_because_the_numbers_collide(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        """Three trees each number from 001. A flat id would be a merge
        conflict between decisions that have nothing to do with each other.
        """
        for identifier in (
            "authority:adr/repo.ADR-001",
            "authority:adr/s0ma-dsl.ADR-001",
            "authority:adr/s0ma-mcp.ADR-001",
        ):
            assert identifier in index
        sources = {
            index[identifier].source
            for identifier in (
                "authority:adr/repo.ADR-001",
                "authority:adr/s0ma-dsl.ADR-001",
                "authority:adr/s0ma-mcp.ADR-001",
            )
        }
        assert len(sources) == 3

    def test_the_superseded_one_says_so(self, index: dict[str, AuthorityRef]) -> None:
        """A3's finding: the dsl's ADR-004 was reversed by the monorepo
        consolidation and its Status line says ``**Superseded**``.
        """
        record = index["authority:adr/s0ma-dsl.ADR-004"]
        assert decision_of(record.status) == "Superseded"
        assert record.source == "packages/s0ma-dsl/docs/adr/ADR-004-separate-project.md"

    @pytest.mark.parametrize("number", ["012", "013"])
    def test_the_new_ones_are_accepted(
        self, index: dict[str, AuthorityRef], number: str
    ) -> None:
        """The B-gate ratification, visible in the index it produced."""
        record = index[f"authority:adr/repo.ADR-{number}"]
        assert decision_of(record.status) == "Accepted"

    def test_no_status_line_went_unread(self, index: dict[str, AuthorityRef]) -> None:
        """A decision word this module has never seen would read as
        ``Unknown`` rather than as ``Accepted``, which is the safe
        direction — and this says none of them does today.
        """
        for key, record in index.items():
            if key.startswith("authority:adr/"):
                assert decision_of(record.status) != UNKNOWN_DECISION, key

    def test_an_adr_names_its_own_title_as_its_section(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        record = index["authority:adr/repo.ADR-012"]
        assert record.section.startswith("ADR-012:")

    def test_the_mcp_decision_is_indexed_by_nothing(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        """The A6 audit's find: an accepted ADR in a third tree that no
        index lists. It is in this index anyway, and it says where it is
        and that nothing catalogs it.
        """
        record = index["authority:adr/s0ma-mcp.ADR-001"]
        facts = facts_of(record.status)
        assert decision_of(record.status) == "Accepted"
        assert facts["tree"] == "s0ma-mcp"
        assert facts["index"] == "none"
        assert record.source == "packages/s0ma-mcp/docs/adr/ADR-001-selfhost-layout.md"

    def test_an_indexed_decision_names_the_index_that_lists_it(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        record = index["authority:adr/s0ma-dsl.ADR-011"]
        assert facts_of(record.status)["index"] == "packages/s0ma-dsl/docs/adr/README.md"

    def test_the_root_tree_keeps_no_index_and_the_records_say_so(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        """Recorded, not hidden. ``none`` is a fact about the tree; an
        index that existed and omitted a decision would read ``unlisted``.
        """
        assert not (REPO_ROOT / "docs" / "adr" / "README.md").exists()
        for number in ("001", "012", "013"):
            assert facts_of(index[f"authority:adr/repo.ADR-{number}"].status)["index"] == "none"


# ---------------------------------------------------------------------------
# Contracts, spec, release, distributions
# ---------------------------------------------------------------------------


class TestFrozenContracts:
    def test_every_contract_file_has_a_record(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        on_disk = {
            path.stem
            for path in (REPO_ROOT / CONTRACTS_DIR).glob("*.md")
            if path.stem.lower() != "readme"
        }
        recorded = {
            key.partition("/")[2]
            for key in index
            if key.startswith("authority:frozen_contract/")
        }
        assert recorded == on_disk
        assert "feedback-v1" in recorded

    def test_a_contract_reads_as_frozen(self, index: dict[str, AuthorityRef]) -> None:
        record = index["authority:frozen_contract/feedback-v1"]
        assert decision_of(record.status) == "Frozen"
        assert record.source == f"{CONTRACTS_DIR}/feedback-v1.md"
        assert "feedback" in record.section.lower()


class TestSpecIdentity:
    def test_exactly_one_spec_record_and_it_is_the_current_one(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        """One, because the delegation falls to a single ``spec`` record.

        The version is derived from the filenames present — the highest —
        and the file it names has to be the one on disk.
        """
        spec = [key for key in index if key.startswith("authority:spec/")]
        assert spec == ["authority:spec/current"]
        record = index["authority:spec/current"]
        version = facts_of(record.status)["version"]
        assert record.source == f"packages/s0ma-dsl/docs/s0ma-dsl-spec-v{version}.md"
        assert (REPO_ROOT / record.source).is_file()

    def test_the_derived_version_is_the_highest_on_disk(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        present = sorted(
            tuple(int(part) for part in path.stem.rpartition("-v")[2].split("."))
            for path in (REPO_ROOT / "packages/s0ma-dsl/docs").glob("s0ma-dsl-spec-v*.md")
        )
        derived = facts_of(index["authority:spec/current"].status)["version"]
        assert tuple(int(part) for part in derived.split(".")) == present[-1]


class TestReleaseIdentity:
    def test_the_release_comes_from_the_one_changelog(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        record = index["authority:declared/release"]
        facts = facts_of(record.status)
        assert record.source == CHANGELOG
        assert decision_of(record.status) == "Released"
        assert facts["version"][0].isdigit()
        assert facts["unreleased"] in {"present", "absent"}
        assert f"[{facts['version']}]" in record.section

    def test_the_unreleased_section_is_not_mistaken_for_a_release(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        record = index["authority:declared/release"]
        assert "unreleased" not in record.section.lower()


class TestDistributions:
    """T2 as taken: the version and dependency direction ride on
    ``declared`` authority records, because ``@1`` has no record type for
    a distribution. The facts are what INV-4 and INV-6 are checkable
    against, so they belong in the graph even in a stopgap shape.
    """

    def test_all_four_distributions_are_recorded(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        recorded = {
            key.rpartition(".")[2]
            for key in index
            if key.startswith("authority:declared/package.")
        }
        assert recorded == set(PACKAGES)

    def test_the_versions_are_in_lockstep(self, index: dict[str, AuthorityRef]) -> None:
        """INV-4, checkable because the records carry the versions."""
        versions = {
            facts_of(index[f"authority:declared/package.{name}"].status)["version"]
            for name in PACKAGES
        }
        assert len(versions) == 1

    def test_the_dependency_direction_is_the_one_inv_6_names(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        """``s0ma-mcp → s0ma-dsl → s0ma-core``, and studi0 a leaf.

        Only in-workspace dependencies are recorded; ``lark`` and
        ``fastapi`` are facts about a build environment, not about this
        architecture.
        """

        def depends(name: str) -> set[str]:
            written = facts_of(index[f"authority:declared/package.{name}"].status)["depends"]
            return set() if written == "none" else set(written.split(","))

        assert depends("s0ma-core") == set()
        assert depends("s0ma-dsl") == {"s0ma-core"}
        assert depends("s0ma-mcp") == {"s0ma-core", "s0ma-dsl"}
        assert depends("s0ma-studi0") == {"s0ma-core", "s0ma-dsl"}
        assert "s0ma-studi0" not in set().union(*(depends(name) for name in PACKAGES))

    def test_a_package_record_points_at_its_own_pyproject(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        for name in PACKAGES:
            record = index[f"authority:declared/package.{name}"]
            assert record.source == f"packages/{name}/pyproject.toml"
            assert record.section == "[project]"


# ---------------------------------------------------------------------------
# The delegation
# ---------------------------------------------------------------------------


class TestDelegation:
    """Plan §5's ratified status, on the record that states it."""

    def test_only_fr_dsl_1_delegates(self, live: ProviderResult) -> None:
        delegating = {record.id for record in _authorities(live) if record.delegates}
        assert delegating == {"authority:prd/FR-DSL-1"}

    def test_it_hands_the_language_to_the_specification_and_cites_where(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        (delegation,) = index["authority:prd/FR-DSL-1"].delegates
        assert delegation.domain == LANGUAGE_DOMAIN
        assert delegation.to_class == "spec"
        assert "FR-DSL-1" in delegation.stated_in
        assert "7.2" in delegation.stated_in

    def test_the_citation_is_the_section_the_record_sits_in(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        """A delegation nobody can find is an assumption. Its citation and
        the record's own section have to name the same place.
        """
        record = index["authority:prd/FR-DSL-1"]
        (delegation,) = record.delegates
        assert record.section.startswith(delegation.stated_in.split()[0].lstrip("§"))

    def test_the_comparison_actually_follows_it(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        """The PRD outranks the spec; for the language domain the spec
        still wins, because the PRD says so in its own words.
        """
        decision = governing_authority(
            record_id="concept:nerve",
            cited=("authority:prd/FR-DSL-1", "authority:spec/current"),
            authorities=index,
            domain=LANGUAGE_DOMAIN,
        )
        assert decision.governing == ("authority:spec/current",)
        assert decision.delegated_from == ("authority:prd/FR-DSL-1",)
        assert decision.findings == ()

    def test_a_different_domain_stays_with_the_prd(
        self, index: dict[str, AuthorityRef]
    ) -> None:
        """The handover is one domain wide. Everything else the PRD keeps."""
        decision = governing_authority(
            record_id="concept:nerve",
            cited=("authority:prd/FR-DSL-1", "authority:spec/current"),
            authorities=index,
            domain="purpose",
        )
        assert decision.governing == ("authority:prd/FR-DSL-1",)
        assert decision.findings == ()

    def test_a_delegation_whose_citation_has_gone_stops_the_build(
        self, tmp_path: Path
    ) -> None:
        """The anti-staleness guard on the one hand-authored table here.

        If the PRD stops declaring the requirement the delegation cites,
        the honest answer is to stop, not to keep handing the language
        over on the strength of a citation nobody can follow.
        """
        root = _copy_sources(tmp_path)
        prd = root / PRD
        text = prd.read_text(encoding="utf-8")
        assert "- **FR-DSL-1**" in text
        prd.write_text(text.replace("- **FR-DSL-1**", "- **FR-DSL-99**", 1), encoding="utf-8")
        with pytest.raises(DocsProviderError) as caught:
            RepoProvider(root=root).provide()
        assert "FR-DSL-1" in str(caught.value)
        assert PRD in str(caught.value)


# ---------------------------------------------------------------------------
# What a source edit does
# ---------------------------------------------------------------------------


def _copy_sources(destination: Path) -> Path:
    """A checkout holding only what this provider reads.

    Copied rather than edited in place, because the alternative is a test
    that mutates the repository it is testing.
    """
    root = destination / "checkout"
    for relative in (PRD, CHANGELOG):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    for tree in ("docs/adr", CONTRACTS_DIR):
        shutil.copytree(REPO_ROOT / tree, root / tree)
    for name in PACKAGES:
        (root / "packages" / name).mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            REPO_ROOT / "packages" / name / "pyproject.toml",
            root / "packages" / name / "pyproject.toml",
        )
    for tree in ("packages/s0ma-dsl/docs/adr", "packages/s0ma-mcp/docs/adr"):
        shutil.copytree(REPO_ROOT / tree, root / tree)
    specs = root / "packages/s0ma-dsl/docs"
    specs.mkdir(parents=True, exist_ok=True)
    for path in (REPO_ROOT / "packages/s0ma-dsl/docs").glob("s0ma-dsl-spec-v*.md"):
        shutil.copy2(path, specs / path.name)
    return root


@pytest.fixture()
def checkout(tmp_path: Path) -> Iterator[Path]:
    yield _copy_sources(tmp_path)


class TestSourceEdits:
    """Plan §8 C4: a PRD hash change flips the affected records."""

    def test_a_copy_reads_the_same_as_the_original(
        self, checkout: Path, live: ProviderResult
    ) -> None:
        """The copy is the control. Without this, the flip test could pass
        because the copy differs from the repository for some other reason.
        """
        copied = _by_id(RepoProvider(root=checkout).provide())
        original = _by_id(live)
        assert copied.keys() == original.keys()
        assert copied == original

    def test_editing_the_prd_restamps_every_prd_record(self, checkout: Path) -> None:
        before = _by_id(RepoProvider(root=checkout).provide())
        prd = checkout / PRD
        prd.write_text(prd.read_text(encoding="utf-8") + "\nA later edit.\n", encoding="utf-8")
        after = _by_id(RepoProvider(root=checkout).provide())

        assert before.keys() == after.keys()
        moved = {key for key in before if before[key] != after[key]}
        assert moved == {key for key in before if key.startswith("authority:prd/")}
        assert len(moved) >= PRD_FLOOR
        for key in moved:
            assert before[key].content_sha256 != after[key].content_sha256
            assert before[key].section == after[key].section

    def test_editing_one_adr_moves_only_that_record(self, checkout: Path) -> None:
        """The other half of the same rule: a file hash is a file's."""
        before = _by_id(RepoProvider(root=checkout).provide())
        target = checkout / "docs/adr/ADR-012-docs-application.md"
        target.write_text(target.read_text(encoding="utf-8") + "\nA note.\n", encoding="utf-8")
        after = _by_id(RepoProvider(root=checkout).provide())
        assert {key for key in before if before[key] != after[key]} == {
            "authority:adr/repo.ADR-012"
        }

    def test_a_status_line_changing_changes_the_record(self, checkout: Path) -> None:
        """What the index is for: a decision that is reversed says so."""
        target = checkout / "docs/adr/ADR-012-docs-application.md"
        text = target.read_text(encoding="utf-8")
        target.write_text(
            text.replace("**Status:** Accepted", "**Status:** Superseded", 1), encoding="utf-8"
        )
        record = _by_id(RepoProvider(root=checkout).provide())["authority:adr/repo.ADR-012"]
        assert decision_of(record.status) == "Superseded"

    def test_an_adr_dropped_out_of_an_index_says_unlisted(
        self, checkout: Path
    ) -> None:
        """The third value, and the only one that means somebody forgot."""
        readme = checkout / "packages/s0ma-dsl/docs/adr/README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8").replace("ADR-011-", "ADR-0011-"),
            encoding="utf-8",
        )
        record = _by_id(RepoProvider(root=checkout).provide())["authority:adr/s0ma-dsl.ADR-011"]
        assert facts_of(record.status)["index"] == "unlisted"

    def test_an_id_mentioned_in_a_row_does_not_become_a_record(
        self, checkout: Path
    ) -> None:
        """The PRD cites its own ids constantly — in prose, in the change
        log table, in cross-references — and a citation is not a
        declaration. Only a line that opens a requirement counts, or the
        index would carry ids the document never defined, under whatever
        section the mention happened to sit in.
        """
        prd = checkout / PRD
        prd.write_text(
            prd.read_text(encoding="utf-8")
            + "\n| 2.0 | 2026-09-01 | FR-CORE-99 and INV-42 as amended |\n"
            + "\nSee **FR-CORE-98** and NFR-41 for the rest.\n",
            encoding="utf-8",
        )
        keys = _by_id(RepoProvider(root=checkout).provide()).keys()
        for absent in ("FR-CORE-99", "FR-CORE-98", "INV-42", "NFR-41"):
            assert f"authority:prd/{absent}" not in keys

    def test_a_source_that_is_not_there_is_simply_absent(self, checkout: Path) -> None:
        """Absence is empty, never an exception. Which sources a checkout
        *ought* to have is the floor gate's question, not this provider's,
        and a provider that raised would make an unrelated build fail.
        """
        shutil.rmtree(checkout / CONTRACTS_DIR)
        (checkout / PRD).unlink()
        result = RepoProvider(root=checkout).provide()
        keys = {record.id for record in _authorities(result)}
        assert not [key for key in keys if key.startswith("authority:frozen_contract/")]
        assert not [key for key in keys if key.startswith("authority:prd/")]
        assert "authority:adr/repo.ADR-012" in keys

    def test_an_empty_tree_produces_nothing_at_all(self, tmp_path: Path) -> None:
        result = RepoProvider(root=tmp_path).provide()
        assert result.records == ()
        assert result.counts()["authorities"] == 0

    def test_an_unaddressable_adr_filename_is_refused_rather_than_skipped(
        self, checkout: Path
    ) -> None:
        """Silently dropping it would take a written decision out of the
        index without saying so, which is the failure this whole
        application exists against.
        """
        (checkout / "docs/adr/ADR-nonsense.md").write_text(
            "# Nope\n\n**Status:** Accepted\n", encoding="utf-8"
        )
        with pytest.raises(DocsProviderError) as caught:
            RepoProvider(root=checkout).provide()
        assert "ADR-nonsense.md" in str(caught.value)


# ---------------------------------------------------------------------------
# Determinism and composition
# ---------------------------------------------------------------------------


class TestComposition:
    """The records have to survive C2's gates to be worth citing."""

    def test_the_provider_composes_with_nothing_reported(self) -> None:
        composition = compose(
            ProviderRegistry.of(RepoProvider(root=REPO_ROOT)), release_version=RELEASE
        )
        assert composition.findings == ()
        assert composition.ok

    def test_every_gate_is_green_over_the_composed_bundle(self) -> None:
        """Including the floors, and including a domain-scoped authority
        question — the delegation is exercised through the aggregate, not
        only through the comparison in isolation.
        """
        composition = compose(
            ProviderRegistry.of(RepoProvider(root=REPO_ROOT)), release_version=RELEASE
        )
        assert (
            validate_bundle(
                composition.bundle,
                results=composition.results,
                floors=dict(REPOSITORY_FLOORS),
                claims=(),
            )
            == ()
        )

    def test_the_floor_this_module_publishes_is_met_and_is_not_a_pin(self) -> None:
        """A floor equal to the count would turn red on the next ADR."""
        counted = RepoProvider(root=REPO_ROOT).provide().counts()["authorities"]
        floor = REPOSITORY_FLOORS[(PROVIDER_ID, "authorities")]
        assert counted >= floor
        assert floor < counted

    def test_the_bundle_is_byte_stable(self) -> None:
        first = compose(
            ProviderRegistry.of(RepoProvider(root=REPO_ROOT)), release_version=RELEASE
        )
        second = compose(
            ProviderRegistry.of(RepoProvider(root=REPO_ROOT)), release_version=RELEASE
        )
        assert serialize_bundle(first.bundle) == serialize_bundle(second.bundle)
        assert first.bundle.stamp.snapshot_hash == second.bundle.stamp.snapshot_hash

    def test_the_snapshot_moves_when_a_source_moves(self, checkout: Path) -> None:
        before = compose(
            ProviderRegistry.of(RepoProvider(root=checkout)), release_version=RELEASE
        ).bundle.stamp.snapshot_hash
        prd = checkout / PRD
        prd.write_text(prd.read_text(encoding="utf-8") + "\nA later edit.\n", encoding="utf-8")
        after = compose(
            ProviderRegistry.of(RepoProvider(root=checkout)), release_version=RELEASE
        ).bundle.stamp.snapshot_hash
        assert before != after

    def test_an_authority_claim_over_the_bundle_resolves_through_it(self) -> None:
        """``validate_bundle`` refuses a claim about a record that cites no
        authority, which every record here is — so the claim path is
        exercised through ``governing_authority`` and the aggregate is
        asked for the rest.
        """
        composition = compose(
            ProviderRegistry.of(RepoProvider(root=REPO_ROOT)), release_version=RELEASE
        )
        authorities = {record.id: record for record in composition.bundle.authorities}
        decision = governing_authority(
            record_id="doc:normative/prd",
            cited=("authority:prd/FR-DSL-1", "authority:spec/current"),
            authorities=authorities,
            domain=LANGUAGE_DOMAIN,
        )
        assert decision.governing == ("authority:spec/current",)
        with pytest.raises(DocsModelError, match="addresses nothing"):
            validate_bundle(
                composition.bundle,
                claims=(AuthorityClaim("concept:nerve", LANGUAGE_DOMAIN),),
            )


# ---------------------------------------------------------------------------
# The D-4 guard, said in the tests too
# ---------------------------------------------------------------------------


class TestReadsIdsNotProse:
    """Architecture §7.6: ids, statuses, hashes and authored relationships.

    There is no way to prove a negative about what a module *could* read,
    so these check the two things that would show up if it started reading
    prose: a record carrying a sentence, and the one relationship in the
    output being anything other than the hand-written, cited one.
    """

    def test_no_record_carries_a_sentence(self, live: ProviderResult) -> None:
        """Sections are headings, statuses are words and facts. A field
        holding prose would be a field somebody has to review for voice,
        and none of these is classified as prose.
        """
        for record in _authorities(live):
            assert "\n" not in record.section
            assert "\n" not in record.status
            assert not record.section.endswith(".")
            assert len(record.status) < 200

    def test_the_only_authored_relationship_is_the_declared_one(
        self, live: ProviderResult
    ) -> None:
        found = {
            (record.id, item.domain, item.to_class)
            for record in _authorities(live)
            for item in record.delegates
        }
        expected = {
            (f"authority:prd/{key}", item.domain, item.to_class)
            for key, delegations in PRD_DELEGATIONS.items()
            for item in delegations
        }
        assert found == expected
