"""The document catalog, and the four claims it is only worth having if it makes.

Milestone C6 of the docs-function plan (internal) §8. The catalog succeeds
the A6 classification ledger, so the first job of this module is to prove
that succession is real rather than asserted:

* **it covers the same corpus.** Every documentation row of
  ``docs/s0ma_src/doc-classification.json`` is a catalog row, every
  ``non-documentation`` row is a recorded exclusion with a written reason,
  and the ledger's disposition and the catalog's status agree row for row
  through one table — :data:`STATUS_BY_DISPOSITION`, which lives here
  because the catalog itself must not know what a disposition is. That
  table is the seed of the equivalence proof F2 needs before the A6 guard
  can be deleted (plan §10.3);
* **it is complete against the tree, not against the ledger.** The gate
  compares the catalog to what git tracks, so a Markdown file that reaches
  neither artifact is still caught;
* **it binds to the authority index.** Every ``authority`` a row claims is
  a record the repository provider emits *for that same file*, and every
  decision record and frozen contract the index knows about is claimed by
  its catalog row. A binding that only resolves is a binding that can
  point at the wrong document;
* **it composes clean.** Core, the repository, the language concepts and
  the catalog compose into one bundle with zero findings, and the bytes do
  not depend on the order the four ran in.

The negative fixtures are small trees written into ``tmp_path``: a catalog
naming files that are really there, plus whatever one mutation the test is
about. C9 owns the full negative battery; what is here is the subset C6's
acceptance names — an uncataloged file, a duplicated id, a duplicated
canonical source — plus the shape refusals this loader is the only place
to catch.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model.application import SIDE_EFFECT_ALLOWANCES
from s0ma_dsl.docs_model.application import registry as application_registry
from s0ma_dsl.docs_model.compose import compose
from s0ma_dsl.docs_model.evidence import EvidenceLibrary
from s0ma_dsl.docs_model.providers import ProviderRegistry
from s0ma_dsl.docs_model.providers_catalog import (
    AUDIENCES,
    CATALOG_FILE,
    CATALOG_FLOORS,
    CATALOG_SCHEMA,
    DOC_CANONICAL_DUPLICATE,
    DOC_DOCUMENT_UNCATALOGED,
    DOC_TOPIC_UNRESOLVED,
    KINDS,
    PROVIDER_ID,
    STATUS_BY_CATEGORY,
    STATUSES,
    CatalogProvider,
    DocsCatalogError,
    check_canonical_sources,
    check_completeness,
    check_document_authorities,
    tracked_markdown,
)
from s0ma_dsl.docs_model.providers_concepts import LANGUAGE_FLOORS, ConceptsProvider
from s0ma_dsl.docs_model.providers_core import CoreProvider
from s0ma_dsl.docs_model.providers_repo import RepoProvider
from s0ma_dsl.docs_model.records import SCHEMA, DocumentRecord
from s0ma_dsl.docs_model.serialize import canonical_json, serialize_bundle
from s0ma_dsl.docs_model.validate import MINTED_CODES, check_floors, validate_bundle

if TYPE_CHECKING:
    from collections.abc import Iterator

    from s0ma_dsl.docs_model.providers import ProviderResult

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "s0ma_dsl"
    / "docs_model"
    / "providers_catalog.py"
)
DATA = REPO_ROOT / CATALOG_FILE
LEDGER_REL = "docs/s0ma_src/doc-classification.json"
ARCH_PLAN_REL = "plans/complete/s0ma-self-documenting-application-1.md"

RELEASE = "0.18.1"

#: The A6 ledger's frozen disposition enum (plan §5) mapped onto the
#: catalog's status vocabulary. Seven of the eight dispositions map onto a
#: status arch §6.5 already named; ``working-plan`` maps onto the one
#: status this milestone added, and ``non-documentation`` maps onto no
#: status at all because those rows leave the catalog as exclusions.
#:
#: This table is the C6 half of the equivalence proof plan §10.3 requires
#: before ``test_doc_classification_ledger.py`` may be deleted at F2. It
#: lives in the test rather than in the provider on purpose: the catalog
#: is the ledger's successor and must not carry knowledge of what a
#: disposition is.
STATUS_BY_DISPOSITION = {
    "normative-current": "normative",
    "living-authored": "living",
    "generated": "generated",
    "mirror": "mirror",
    "historical": "historical",
    "superseded-pointer": "superseded",
    "working-plan": "working-plan",
}

#: The one document the catalog carries that the ledger cannot: the
#: authored language concepts, which are a ``.json`` file and so never
#: appear in a Markdown corpus. Named here so the coverage comparison is
#: an equality rather than a subset — a catalog quietly growing rows
#: nobody reviewed is the failure a subset test would miss.
BEYOND_THE_LEDGER = frozenset(
    {
        "docs/s0ma_src/concepts/language.json",
        "docs/s0ma_src/concepts/product.json",
        # The quick reference's data twin and the packaged copy the
        # authoring server serves it from (owner ruling 2026-09-29). Both
        # are JSON: the twin is cataloged because the mirror rule requires
        # every served copy's original to be a document the catalog holds,
        # and the ledger, which is a ledger of Markdown files, has no row
        # for either — its summary says so in as many words.
        "docs/_generated/quick-reference-machine.json",
        "packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-machine.json",
    }
)

#: The catalog's row for itself, synthesized by the provider from the
#: identity the file declares.
SELF_ID = "doc:catalog/document-catalog"

#: An honest minimum, well under the live count, for the same reason the
#: provider's floor is: a floor at the count fails the day somebody writes
#: the next document.
DOCUMENT_FLOOR = 150


# ---------------------------------------------------------------------------
# Fixtures over the real catalog
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def provider() -> CatalogProvider:
    return CatalogProvider(root=REPO_ROOT)


@pytest.fixture(scope="module")
def live(provider: CatalogProvider) -> ProviderResult:
    return provider.provide()


@pytest.fixture(scope="module")
def rows(provider: CatalogProvider) -> dict[str, DocumentRecord]:
    return {record.id: record for record in provider.documents()}


@pytest.fixture(scope="module")
def authored() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(DATA.read_text(encoding="utf-8"))
    return document


@pytest.fixture(scope="module")
def ledger() -> dict[str, Any]:
    path = REPO_ROOT / LEDGER_REL
    if not path.is_file():  # pragma: no cover - wheel-install context
        pytest.skip(f"{LEDGER_REL} not available (not a repo checkout)")
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


@pytest.fixture(scope="module")
def composition() -> Any:
    # Since the E wave, catalog rows cover journeys, journeys step through
    # D-phase surfaces and recover through diagnostics — the subset claim
    # this fixture originally made cannot compose clean by construction any
    # more, so the claim it now makes is the application's own: the full
    # registry, composed the way `build` composes it.
    return compose(application_registry(REPO_ROOT), release_version=RELEASE)


# ---------------------------------------------------------------------------
# Fixture trees for the negative cases
# ---------------------------------------------------------------------------


def _row(**overrides: Any) -> dict[str, Any]:
    """One well-formed catalog row, ready to be broken in one place."""
    row = {
        "id": "doc:guide/readme",
        "title": "A fixture document",
        "kind": "guide",
        "audiences": ["contributor"],
        "status": "living",
        "canonical_source": "README.md",
        "prose_locator": "README.md",
        "authority": "",
        "governed_by": [],
        "covers": [],
    }
    row.update(overrides)
    return row


def _tree(
    tmp_path: Path,
    documents: list[dict[str, Any]] | None = None,
    excluded: list[dict[str, str]] | None = None,
    **overrides: Any,
) -> CatalogProvider:
    """A checkout holding a catalog and every file that catalog names."""
    rows = [_row()] if documents is None else documents
    document: dict[str, Any] = {
        "schema": CATALOG_SCHEMA,
        "self": {
            "id": SELF_ID,
            "title": "The document catalog",
            "kind": "reference",
            "audiences": ["contributor"],
            "status": "living",
        },
        "excluded": [] if excluded is None else excluded,
        "documents": rows,
    }
    document.update(overrides)
    for row in rows:
        for value in (row.get("canonical_source"), row.get("prose_locator")):
            if isinstance(value, str) and value:
                _touch(tmp_path / value.partition("#")[0])
    for item in document["excluded"]:
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            _touch(tmp_path / item["path"])
    target = tmp_path / CATALOG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(document), encoding="utf-8", newline="\n")
    return CatalogProvider(root=tmp_path)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# A fixture document\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# The succession: catalog against ledger
# ---------------------------------------------------------------------------


class TestTheCatalogSucceedsTheLedger:
    """One row per classified document, and the two agree about each."""

    def test_every_documentation_row_of_the_ledger_is_cataloged(
        self, provider: CatalogProvider, ledger: dict[str, Any]
    ) -> None:
        classified = {
            entry["path"]
            for entry in ledger["entries"]
            if entry["disposition"] != "non-documentation"
        }
        cataloged = {
            record.canonical_source
            for record in provider.documents()
            if record.id != SELF_ID
        }
        assert cataloged - BEYOND_THE_LEDGER == classified
        assert cataloged & BEYOND_THE_LEDGER == BEYOND_THE_LEDGER

    def test_every_non_documentation_row_is_an_exclusion_with_a_reason(
        self, provider: CatalogProvider, ledger: dict[str, Any]
    ) -> None:
        expected = {
            entry["path"]
            for entry in ledger["entries"]
            if entry["disposition"] == "non-documentation"
        }
        exclusions = provider.exclusions()
        assert {item.path for item in exclusions} == expected
        for item in exclusions:
            assert len(item.reason.split()) >= 8, (
                f"{item.path}: an exclusion whose reason is a phrase is not "
                f"reviewable; say why the file is not documentation"
            )

    def test_the_disposition_and_the_status_agree_row_for_row(
        self, provider: CatalogProvider, ledger: dict[str, Any]
    ) -> None:
        """The F2 equivalence seed: one mapping, applied to every row."""
        by_source = {
            record.canonical_source: record
            for record in provider.documents()
            if record.id != SELF_ID
        }
        status_by_category = dict(STATUS_BY_CATEGORY)
        for entry in ledger["entries"]:
            if entry["disposition"] == "non-documentation":
                continue
            record = by_source[entry["path"]]
            category = record.id.partition(":")[2].partition("/")[0]
            assert status_by_category[category] == STATUS_BY_DISPOSITION[
                entry["disposition"]
            ], f"{entry['path']}: {record.id} does not carry its ledger disposition"

    def test_every_recorded_audience_survived_the_conversion(
        self, provider: CatalogProvider, ledger: dict[str, Any], authored: dict[str, Any]
    ) -> None:
        """A ledger audience is a claim about a reader; it may not be dropped."""
        audiences = {
            row["canonical_source"]: row["audiences"] for row in authored["documents"]
        }
        for entry in ledger["entries"]:
            if entry["disposition"] == "non-documentation" or not entry.get("audience"):
                continue
            assert entry["audience"] in audiences[entry["path"]], (
                f"{entry['path']}: the ledger records the audience "
                f"{entry['audience']!r} and the catalog row does not carry it"
            )

    def test_the_mapping_table_covers_the_frozen_disposition_enum(
        self, ledger: dict[str, Any]
    ) -> None:
        """No disposition may reach the catalog without a decided status."""
        used = {entry["disposition"] for entry in ledger["entries"]}
        assert used - {"non-documentation"} <= set(STATUS_BY_DISPOSITION)
        assert set(STATUS_BY_DISPOSITION.values()) <= set(STATUSES)


# ---------------------------------------------------------------------------
# Completeness against the tree
# ---------------------------------------------------------------------------


class TestCompleteness:
    """Every tracked document has a row, or a written reason for having none."""

    def test_the_repository_is_completely_cataloged(
        self, provider: CatalogProvider
    ) -> None:
        findings = check_completeness(provider, _tracked())
        assert [item.rendered() for item in findings] == []

    def test_an_uncataloged_file_is_reported_with_its_path(self, tmp_path: Path) -> None:
        catalog = _tree(tmp_path)
        _touch(tmp_path / "docs/brand-new.md")
        findings = check_completeness(catalog, ["README.md", "docs/brand-new.md"])
        assert [item.code for item in findings] == [DOC_DOCUMENT_UNCATALOGED]
        assert findings[0].location == "docs/brand-new.md"
        assert CATALOG_FILE in findings[0].remediation

    def test_a_recorded_exclusion_answers_for_a_file(self, tmp_path: Path) -> None:
        catalog = _tree(
            tmp_path,
            excluded=[
                {
                    "path": "tests/fixture.md",
                    "reason": "Test data: a golden file whose bytes a test asserts against.",
                }
            ],
        )
        assert check_completeness(catalog, ["README.md", "tests/fixture.md"]) == []

    def test_a_file_cannot_be_cataloged_and_excluded_at_once(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="both"):
            _tree(
                tmp_path,
                excluded=[{"path": "README.md", "reason": "A reason nobody can act on."}],
            ).provide()

    def test_the_corpus_is_the_one_the_a6_guard_reads(self) -> None:
        """Until F2 retires that guard, the two must ask git the same question."""
        direct = subprocess.run(  # noqa: S603
            ["git", "-C", str(REPO_ROOT), "ls-files", "*.md"],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if direct.returncode != 0:  # pragma: no cover - environment-dependent
            pytest.skip("git ls-files failed")
        assert tracked_markdown(REPO_ROOT) == tuple(
            sorted(line for line in direct.stdout.splitlines() if line)
        )

    def test_the_corpus_is_not_allowed_to_resolve_empty(self, tmp_path: Path) -> None:
        """A corpus of nothing would make this gate pass everything.

        Two ways to get nothing — git refusing to answer, and git
        answering with an empty list — and both are refused, because a
        gate that reports no omissions from an empty corpus is worse than
        no gate.
        """
        with pytest.raises(DocsCatalogError, match="corpus"):
            tracked_markdown(tmp_path)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestIdentity:
    """A ``doc:`` id is a claim about a document, and it is checked."""

    def test_every_id_is_a_document_id_in_a_known_category(
        self, rows: dict[str, DocumentRecord]
    ) -> None:
        for identifier in rows:
            category = identifier.partition(":")[2].partition("/")[0]
            assert identifier.startswith("doc:")
            assert category in STATUS_BY_CATEGORY

    def test_two_rows_cannot_share_an_id(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="row ids repeat"):
            _tree(tmp_path, documents=[_row(), _row()]).provide()

    def test_rows_are_sorted_by_id(self, authored: dict[str, Any]) -> None:
        identifiers = [row["id"] for row in authored["documents"]]
        assert identifiers == sorted(identifiers)

    def test_an_id_that_matches_no_form_is_refused_by_name(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="not a document id"):
            _tree(tmp_path, documents=[_row(id="document:readme")]).provide()

    def test_an_unknown_category_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="not a catalog category"):
            _tree(tmp_path, documents=[_row(id="doc:invented/readme")]).provide()

    def test_the_category_and_the_status_have_to_agree(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="One of the two is wrong"):
            _tree(tmp_path, documents=[_row(status="historical")]).provide()

    def test_every_category_asserts_a_status_the_model_knows(self) -> None:
        assert set(STATUS_BY_CATEGORY.values()) <= set(STATUSES)

    def test_the_self_row_is_the_catalog_itself(
        self, rows: dict[str, DocumentRecord]
    ) -> None:
        record = rows[SELF_ID]
        assert record.canonical_source == CATALOG_FILE
        assert record.prose_locator == CATALOG_FILE
        assert record.covers == ()

    def test_the_self_row_cannot_also_be_written_out_by_hand(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(DocsCatalogError, match="also an ordinary row"):
            _tree(
                tmp_path,
                documents=[
                    _row(
                        id=SELF_ID,
                        kind="reference",
                        canonical_source=CATALOG_FILE,
                        prose_locator=CATALOG_FILE,
                    )
                ],
            ).provide()


# ---------------------------------------------------------------------------
# Canonical sources
# ---------------------------------------------------------------------------


class TestCanonicalSources:
    """One file, one document."""

    def test_the_live_catalog_reports_nothing(self, provider: CatalogProvider) -> None:
        assert [item.rendered() for item in provider.findings()] == []

    def test_two_rows_over_one_file_are_reported_naming_both(
        self, tmp_path: Path
    ) -> None:
        catalog = _tree(
            tmp_path,
            documents=[_row(), _row(id="doc:guide/second-opinion")],
        )
        findings = catalog.findings()
        assert [item.code for item in findings] == [DOC_CANONICAL_DUPLICATE]
        assert "doc:guide/readme" in findings[0].message
        assert "doc:guide/second-opinion" in findings[0].message
        assert findings[0].location == "README.md"

    def test_the_rule_runs_over_a_whole_composition_too(
        self, composition: Any
    ) -> None:
        """The reading that catches a derived row colliding with an authored one."""
        assert check_canonical_sources(composition.bundle.documents) == []

    def test_a_row_naming_a_file_that_is_not_there_is_refused(
        self, tmp_path: Path
    ) -> None:
        catalog = _tree(tmp_path)
        (tmp_path / "README.md").unlink()
        with pytest.raises(DocsCatalogError, match="not a file in this checkout"):
            catalog.provide()

    def test_an_absolute_path_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="repository-relative"):
            _tree(tmp_path, documents=[_row(canonical_source="/etc/hosts")]).provide()


# ---------------------------------------------------------------------------
# Where the words are
# ---------------------------------------------------------------------------


class TestProseLocator:
    """A finding about prose has to point at a line somebody may edit."""

    def test_a_mirror_points_at_the_document_it_copies(
        self, rows: dict[str, DocumentRecord]
    ) -> None:
        mirrors = [record for record in rows.values() if record.id.startswith("doc:mirror/")]
        assert mirrors, "the repository keeps nine gated mirrors; the catalog lost them"
        for record in mirrors:
            assert record.prose_locator != record.canonical_source, (
                f"{record.id}: a mirror's words live in the document it copies, "
                f"not in the copy — the copy is byte-gated against it"
            )

    def test_a_generated_page_points_at_the_declaration_it_came_from(
        self, rows: dict[str, DocumentRecord]
    ) -> None:
        located = [
            record
            for record in rows.values()
            if "#" in record.prose_locator
        ]
        assert len(located) >= 3
        for record in located:
            path, _, fragment = record.prose_locator.partition("#")
            assert path.endswith(".s0ma")
            assert fragment.split(":")[0] in {"doc-guide", "doc-ref"}

    def test_a_locator_naming_no_declaration_kind_is_refused(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(DocsCatalogError, match="not a declaration reference"):
            _tree(
                tmp_path,
                documents=[_row(prose_locator="README.md#section-two")],
            ).provide()


# ---------------------------------------------------------------------------
# The field this milestone re-added
# ---------------------------------------------------------------------------


class TestAuthorityBinding:
    """A document that is an authority says which one, and it is the same file."""

    def test_every_claimed_authority_is_one_a_provider_emits(
        self, composition: Any
    ) -> None:
        assert [item.rendered() for item in check_document_authorities(composition.bundle)] == []

    def test_a_claimed_authority_names_this_very_document(
        self, composition: Any
    ) -> None:
        """Resolution is not enough: it has to resolve to the same file."""
        by_id = {record.id: record for record in composition.bundle.authorities}
        checked = 0
        for record in composition.bundle.documents:
            if not record.authority:
                continue
            authority = by_id[record.authority]
            assert authority.source == record.canonical_source, (
                f"{record.id} claims to be {record.authority}, which the "
                f"authority index reads from {authority.source}"
            )
            checked += 1
        assert checked >= 20, "the repository has 22 normative documents; most claim an id"

    def test_every_decision_and_contract_is_claimed_by_its_row(
        self, composition: Any
    ) -> None:
        """The direction that catches a binding somebody forgot to write."""
        claimed = {
            record.authority for record in composition.bundle.documents if record.authority
        }
        by_source = {
            record.canonical_source: record for record in composition.bundle.documents
        }
        missing: list[str] = []
        for authority in composition.bundle.authorities:
            if authority.authority_class not in {"adr", "frozen_contract"}:
                continue
            if authority.source not in by_source:
                missing.append(f"{authority.id} ({authority.source}) has no catalog row")
            elif authority.id not in claimed:
                missing.append(f"{authority.id} is not claimed by {by_source[authority.source].id}")
        assert missing == []

    def test_an_authority_nobody_emits_is_reported_rather_than_ignored(
        self, tmp_path: Path
    ) -> None:
        catalog = _tree(
            tmp_path,
            documents=[
                _row(
                    id="doc:normative/readme",
                    status="normative",
                    kind="normative",
                    authority="authority:adr/repo.ADR-999",
                )
            ],
        )
        bundle = compose(
            ProviderRegistry.of(catalog), release_version=RELEASE
        ).bundle
        findings = check_document_authorities(bundle)
        assert [item.code for item in findings] == [DOC_TOPIC_UNRESOLVED]
        assert "authority:adr/repo.ADR-999" in findings[0].message

    def test_a_value_that_is_not_an_authority_id_is_refused(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(DocsCatalogError, match="not an authority id"):
            _tree(tmp_path, documents=[_row(authority="concept:drift")]).provide()

    def test_a_document_that_is_not_an_authority_leaves_it_empty(
        self, rows: dict[str, DocumentRecord]
    ) -> None:
        assert rows["doc:guide/readme"].authority == ""
        assert rows[SELF_ID].authority == ""


# ---------------------------------------------------------------------------
# The rest of the shape
# ---------------------------------------------------------------------------


class TestShape:
    """The file says what it is, and what it says has to be true."""

    def test_the_file_declares_the_catalog_schema(self, authored: dict[str, Any]) -> None:
        assert authored["schema"] == CATALOG_SCHEMA
        assert authored["schema"] != SCHEMA, (
            "the catalog is an input to the model, not a serialization of it"
        )

    def test_a_file_declaring_another_schema_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="this loader reads"):
            _tree(tmp_path, schema="s0ma-docs-catalog@2").provide()

    def test_an_unexpected_key_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="unexpected"):
            _tree(tmp_path, notes="a key nobody reads").provide()

    def test_an_unexpected_key_on_a_row_is_refused(self, tmp_path: Path) -> None:
        row = _row()
        row["owner"] = "the owner"
        with pytest.raises(DocsCatalogError, match="unexpected"):
            _tree(tmp_path, documents=[row]).provide()

    def test_a_kind_outside_the_enum_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="not a document kind"):
            _tree(tmp_path, documents=[_row(kind="explainer")]).provide()

    def test_an_audience_outside_the_enum_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="not an audience"):
            _tree(tmp_path, documents=[_row(audiences=["machine"])]).provide()

    def test_a_row_written_for_nobody_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="written for"):
            _tree(tmp_path, documents=[_row(audiences=[])]).provide()

    def test_an_unsorted_reference_list_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="not sorted"):
            _tree(
                tmp_path,
                documents=[_row(covers=["concept:nerve", "concept:drift"])],
            ).provide()

    def test_an_empty_catalog_is_refused_before_any_floor_sees_it(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(DocsCatalogError, match="is empty"):
            _tree(tmp_path, documents=[]).provide()

    def test_an_absent_file_is_refused_by_name(self, tmp_path: Path) -> None:
        with pytest.raises(DocsCatalogError, match="not a file in this checkout"):
            CatalogProvider(root=tmp_path).provide()

    def test_a_file_that_is_not_json_is_refused_with_its_position(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / CATALOG_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{not json", encoding="utf-8", newline="\n")
        with pytest.raises(DocsCatalogError, match="not readable as JSON"):
            CatalogProvider(root=tmp_path).provide()

    def test_every_kind_and_status_used_is_one_the_model_names(
        self, authored: dict[str, Any]
    ) -> None:
        for row in authored["documents"]:
            assert row["kind"] in KINDS
            assert row["status"] in STATUSES
            for audience in row["audiences"]:
                assert audience in AUDIENCES

    def test_the_file_is_in_canonical_form(self, authored: dict[str, Any]) -> None:
        assert canonical_json(authored) == DATA.read_text(encoding="utf-8")

    def test_the_file_is_utf8_with_line_feeds_and_one_trailing_newline(self) -> None:
        raw = DATA.read_bytes()
        assert b"\r" not in raw
        assert raw.decode("utf-8").endswith("\n")
        assert not raw.decode("utf-8").endswith("\n\n")

    def test_the_module_itself_is_utf8_with_line_feeds(self) -> None:
        assert b"\r" not in MODULE.read_bytes()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Same file, same records, same bytes."""

    def test_calling_twice_gives_the_same_records(self) -> None:
        catalog = CatalogProvider(root=REPO_ROOT)
        assert [item.record for item in catalog.provide().records] == [
            item.record for item in catalog.provide().records
        ]

    def test_two_providers_on_one_root_agree(self, live: ProviderResult) -> None:
        second = CatalogProvider(root=REPO_ROOT).provide()
        assert [item.record for item in second.records] == [
            item.record for item in live.records
        ]

    def test_the_records_are_sorted_and_normalized(self, live: ProviderResult) -> None:
        identifiers = [item.record.id for item in live.records]
        assert identifiers == sorted(identifiers)
        assert len(set(identifiers)) == len(identifiers)

    def test_every_record_is_stamped_with_the_catalog(self, live: ProviderResult) -> None:
        assert [source for source, _ in live.sources()] == [CATALOG_FILE]
        for item in live.records:
            assert item.provenance.adapter_id == PROVIDER_ID
            assert item.provenance.schema_version == SCHEMA

    def test_the_provider_emits_documents_and_nothing_else(
        self, live: ProviderResult
    ) -> None:
        counts = live.counts()
        assert counts["documents"] == len(live.records)
        assert sum(counts.values()) == counts["documents"]

    def test_no_record_carries_an_absolute_path(self, live: ProviderResult) -> None:
        """INV-5: nothing a record holds names the machine that built it."""
        for item in live.records:
            for value in _strings_of(item.record):
                assert not value.startswith("/"), value
                assert "\\" not in value, value

    def test_a_serialized_bundle_is_byte_stable(self) -> None:
        first = compose(
            ProviderRegistry.of(CatalogProvider(root=REPO_ROOT)), release_version=RELEASE
        ).bundle
        second = compose(
            ProviderRegistry.of(CatalogProvider(root=REPO_ROOT)), release_version=RELEASE
        ).bundle
        assert serialize_bundle(first) == serialize_bundle(second)

    def test_a_row_round_trips_through_the_canonical_form(self) -> None:
        """The new field survives the reader as well as the writer."""
        from s0ma_dsl.docs_model.serialize import deserialize_bundle

        bundle = compose(
            ProviderRegistry.of(CatalogProvider(root=REPO_ROOT)), release_version=RELEASE
        ).bundle
        assert deserialize_bundle(serialize_bundle(bundle)) == bundle
        assert any(record.authority for record in bundle.documents)


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


class TestComposition:
    """Four providers, one bundle, nothing wrong with it."""

    def test_core_repo_concepts_and_catalog_compose_with_zero_findings(self) -> None:
        # Since the E wave the catalog's rows reach journeys, surfaces and
        # diagnostics, so the subset this test originally composed cannot be
        # clean by construction. The surviving strong claim is the
        # application's own composition, validated with the same seams
        # `build` wires: every provider's external ids plus the evidence
        # library's, the merged floors, and the written allowances.
        registry = application_registry(REPO_ROOT)
        composed = compose(registry, release_version=RELEASE)
        assert composed.findings == ()
        external: set[str] = set(EvidenceLibrary.load(REPO_ROOT).ids())
        floors: dict[tuple[str, str], int] = {}
        for item in registry.providers():
            if hasattr(item, "external_ids"):
                external.update(item.external_ids())
            for name in ("FLOORS", "floors"):
                held = getattr(item, name, None)
                if held:
                    floors.update(dict(held))
        findings = validate_bundle(
            composed.bundle,
            results=composed.results,
            external_ids=frozenset(external),
            floors={**dict(LANGUAGE_FLOORS), **dict(CATALOG_FLOORS)},
            allowances=SIDE_EFFECT_ALLOWANCES,
        )
        assert [item.rendered() for item in findings] == []

    def test_registration_order_does_not_reach_the_bundle(self) -> None:
        core = CoreProvider()
        repo = RepoProvider(root=REPO_ROOT)
        concepts = ConceptsProvider.language(REPO_ROOT)
        catalog = CatalogProvider(root=REPO_ROOT)
        forwards = compose(
            ProviderRegistry.of(core, repo, concepts, catalog), release_version=RELEASE
        ).bundle
        backwards = compose(
            ProviderRegistry.of(catalog, concepts, repo, core), release_version=RELEASE
        ).bundle
        assert serialize_bundle(forwards) == serialize_bundle(backwards)

    def test_the_composed_bundle_holds_every_row(
        self, composition: Any, rows: dict[str, DocumentRecord]
    ) -> None:
        assert {record.id for record in composition.bundle.documents} == set(rows)

    def test_every_covered_topic_resolves(self, composition: Any) -> None:
        """The D-4 claim, proved on the real catalog: binding without grammar.

        Since the E wave a row may cover a concept, a journey or a served
        surface, so the resolvable universe is every addressable record in
        the composed bundle rather than the concepts alone.
        """
        known = {
            record.id
            for group in (
                composition.bundle.concepts,
                composition.bundle.journeys,
                composition.bundle.surfaces,
            )
            for record in group
        }
        covered = {
            topic for record in composition.bundle.documents for topic in record.covers
        }
        assert covered, "a catalog that covers nothing proves nothing about binding"
        assert covered <= known


# ---------------------------------------------------------------------------
# Floors and diagnostic names
# ---------------------------------------------------------------------------


class TestFloorsAndCodes:
    """A gate that resolves empty passes everything downstream of it."""

    def test_the_floor_is_met(self, live: ProviderResult) -> None:
        assert check_floors([live], dict(CATALOG_FLOORS)) == []
        assert live.counts()["documents"] >= DOCUMENT_FLOOR

    def test_the_floor_is_honest_rather_than_a_pin(self, live: ProviderResult) -> None:
        floor = CATALOG_FLOORS[(PROVIDER_ID, "documents")]
        assert floor <= live.counts()["documents"], "the floor has outgrown the corpus"
        assert floor >= DOCUMENT_FLOOR

    def test_a_floor_above_the_count_is_reported(self, live: ProviderResult) -> None:
        findings = check_floors([live], {(PROVIDER_ID, "documents"): 10_000})
        assert [item.code for item in findings] == ["DOC_GATE_VACUOUS"]

    def test_this_milestone_mints_no_new_diagnostic(self) -> None:
        """Two codes come from arch §11 and the third from B6. None is new."""
        plan = REPO_ROOT / ARCH_PLAN_REL
        if not plan.is_file():  # pragma: no cover - wheel-install context
            pytest.skip(f"{ARCH_PLAN_REL} not available (not a repo checkout)")
        text = plan.read_text(encoding="utf-8")
        assert DOC_DOCUMENT_UNCATALOGED in text
        assert DOC_CANONICAL_DUPLICATE in text
        assert DOC_TOPIC_UNRESOLVED in MINTED_CODES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracked() -> tuple[str, ...]:
    if not (REPO_ROOT / ".git").exists():  # pragma: no cover - wheel-install context
        pytest.skip("not a git checkout")
    return tracked_markdown(REPO_ROOT)


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
