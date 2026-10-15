"""The map of record — ``docs/README.md`` — and the guard it retires.

Milestone F2 of the docs-function plan (internal) §11. Two things happen at
this milestone and this module proves both.

**The map.** The August 2026 docs audit measured an absence and named its
consequence: *the orphaned docs are the stale docs*. There was no index,
and ten documents sat outside every location the audit's own table listed —
four of them the package front doors a reader meets first. The map exists
to make that impossible to repeat, so the assertions here are about
completeness rather than about prose: every catalog row is on the page,
every excluded file is on the page, the ten are on the page by name, and
every link on it resolves.

**The retirement.** ``test_doc_classification_ledger.py`` was A6's
temporary presence guard over ``docs/s0ma_src/doc-classification.json``,
and it is deleted at this milestone. Plan §10.3 forbids removing a proven
gate without an explicit equivalence test, so
:class:`TestTheRetirementOfTheA6Guard` below plants the fixture input that
guard caught — a tracked Markdown file nobody classified — and shows the
catalog's completeness gate rejecting the *same* input, naming the *same*
file, before proving the guard's file is gone. The end-to-end half of that
proof already exists and is cited rather than repeated:
``test_docs_application_gate.py::TestTheStageAgainstACopy::test_an_uncataloged_document_is_named``
runs the whole ``docs-application`` stage against a planted checkout copy.

**What the retirement does not claim.** The A6 guard also checked the
ledger file's own shape, and after this milestone nothing does. That is the
point rather than an oversight: the catalog is the live classification and
carries every one of those properties over its own file (schema, sorted
unique ids, closed vocabularies, a row naming a file that is really
there), while the ledger becomes the A6 record of how the corpus was
classified and Phase G's migration map. :class:`TestTheCatalogCarriesTheGuardsProperties`
asserts the carry-over rather than assuming it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model.application import DOCS_ROOT, MAP_OUTPUT, build
from s0ma_dsl.docs_model.map_of_record import (
    ARCHIVE,
    CATEGORIES,
    CATEGORY_BY_KIND,
    GUARD_BYTES,
    GUARD_LINKS,
    GUARD_ONLY_LISTED,
    GUARD_VERSION,
    GUARD_WORDS,
    MIRRORS,
    SECTIONS,
    STANDING_WORDS,
    TRAILING,
    UNDERSTAND,
    VERSION_CHECKED,
    WORKING_NOTES,
    anchor,
    category_of,
    guards_of,
    links_checked,
    map_of_record,
    sections_of,
)
from s0ma_dsl.docs_model.providers_catalog import (
    DOC_DOCUMENT_UNCATALOGED,
    KINDS,
    STATUSES,
    CatalogProvider,
    DocsCatalogError,
    check_completeness,
    tracked_markdown,
)
from s0ma_dsl.docs_model.providers_concepts import FORBIDDEN_IN_AUTHORED_PROSE

if TYPE_CHECKING:
    from types import ModuleType

    from s0ma_dsl.docs_model.application import Build

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
MAP = REPO_ROOT / DOCS_ROOT / MAP_OUTPUT
SCRIPTS = REPO_ROOT / "scripts"

#: A6's temporary guard, deleted at this milestone. Named so its return is
#: a red test rather than a quiet regression.
RETIRED_GUARD = REPO_ROOT / "packages" / "s0ma-dsl" / "tests" / (
    "test_doc_classification_ledger.py"
)

#: The end-to-end half of the equivalence proof, cited rather than copied.
F1_GATE_TEST = REPO_ROOT / "packages" / "s0ma-dsl" / "tests" / (
    "test_docs_application_gate.py"
)

#: The classification ledger and its human summary. Ordinary tracked files
#: under ``docs/s0ma_src/`` since the front-door move: gate inputs like the
#: catalog beside them, read here directly rather than through the
#: internal-corpus helper — that helper is for documents the public export
#: withholds, and these are not withheld any more. Both sites below sit
#: under ``requires_checkout``, which is the only absence left to cover.
LEDGER_REL = "docs/s0ma_src/doc-classification.json"
SUMMARY_REL = "docs/s0ma_src/doc-classification.md"

#: The ten documents the docs audit's eight-location table has no home for
#: (``docs/s0ma_src/doc-classification.md`` §2). Seven are documents and
#: three are test fixtures the catalog excludes. The audit's finding was
#: that unreachable documents are where drift concentrates, and four of
#: these are the package front doors; a map that did not carry them would
#: reproduce the finding it was built to close.
OUTSIDE_THE_EIGHT_LOCATIONS: tuple[str, ...] = (
    "packages/s0ma-core/CHANGELOG.md",
    "packages/s0ma-core/README.md",
    "packages/s0ma-dsl/CHANGELOG.md",
    "packages/s0ma-dsl/README.md",
    "packages/s0ma-mcp/README.md",
    "packages/s0ma-mcp/docs/adr/ADR-001-selfhost-layout.md",
    "packages/s0ma-studi0/README.md",
)

#: The three of the ten that are test data rather than documentation. They
#: are on the page too, in the excluded table with the reason.
OUTSIDE_AND_EXCLUDED: tuple[str, ...] = (
    "packages/s0ma-dsl/tests/fixtures/golden/docs/greetings.md",
    "packages/s0ma-dsl/tests/fixtures/golden/docs/walkthrough.md",
    "packages/s0ma-dsl/tests/fixtures/legacy_layout_project/README.md",
)

#: Documents whose standing is current and whose subject is the past, so
#: they render in the archive rather than in one of the five reader
#: categories (mapping rule 2's ``kind`` half). Enumerated rather than
#: counted: a second one arriving is a decision somebody takes here.
#:
#: G5 took that decision twice. Archiving the two pre-monorepo plan trees
#: under ``docs/archive/pre-monorepo/`` gave each one a tombstone note at
#: its root, and a note saying "everything beside me is frozen, here is
#: what replaced it" is the same class as the 0.9.0 one: maintained today,
#: about the past, and belonging in the archive section rather than in a
#: reader category. Their catalog rows say so — ``status: living`` with
#: ``kind: historical`` — which is exactly the pair this set exists to
#: allow.
CURRENT_BUT_ARCHIVED: frozenset[str] = frozenset(
    {
        "doc:guide/archive-0-9-0-readme",
        "doc:guide/archive-pre-monorepo-s0ma-core-readme",
        "doc:guide/archive-pre-monorepo-s0ma-dsl-readme",
    }
)

#: The statuses that describe s0ma as it is now — the rows plan §11 F2
#: requires the map to carry in full.
CURRENT_STATUSES: frozenset[str] = frozenset({"generated", "living", "normative"})

#: One table row of the rendered map: ``| [title](link) | `path` | ...``.
#: The title may itself contain one level of brackets — an ADR titled
#: "Declarative Project Discovery via ``[tool.s0ma]``" is why this reads
#: the same nesting ``scripts/check_links.py`` reads rather than stopping
#: at the first ``]``. A row this pattern missed would be a row the
#: completeness assertions below silently forgave.
_ROW = re.compile(
    r"^\| \[(?:[^\[\]]|\[[^\[\]]*\])*\]\((?P<link>[^)]*)\) \| `(?P<path>[^`]*)` \|"
)

#: One row of the excluded table: ``| [`path`](link) | reason |``.
_EXCLUDED_ROW = re.compile(r"^\| \[`(?P<path>[^`]*)`\]\((?P<link>[^)]*)\) \|")


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


@cache
def _script(name: str) -> ModuleType:
    """Import a ``scripts/`` guard for the pins below.

    Registered in ``sys.modules`` before execution for the reason
    ``test_check_links_script.py`` gives: ``@dataclass`` resolves a class's
    module through it.
    """
    spec = importlib.util.spec_from_file_location(f"s0ma_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def catalog() -> CatalogProvider:
    """The repository's own catalog, read once."""
    return CatalogProvider(root=REPO_ROOT)


@pytest.fixture(scope="module")
def composed() -> Build:
    """One composition of this checkout, for the byte-level proofs."""
    return build(REPO_ROOT)


@pytest.fixture(scope="module")
def page() -> str:
    """The committed map. D6's suite pins it equal to a fresh render."""
    if not MAP.is_file():  # pragma: no cover - guarded by the marker
        pytest.skip("the map has never been written")
    return MAP.read_text(encoding="utf-8")


def _rows(page: str) -> list[tuple[str, str]]:
    """``(path, link)`` for every document row of the rendered page."""
    found: list[tuple[str, str]] = []
    for line in page.splitlines():
        match = _ROW.match(line)
        if match:
            found.append((match.group("path"), match.group("link")))
    return found


def _excluded_rows(page: str) -> list[tuple[str, str]]:
    """``(path, link)`` for every row of the excluded table."""
    return [
        (match.group("path"), match.group("link"))
        for line in page.splitlines()
        if (match := _EXCLUDED_ROW.match(line))
    ]


# ---------------------------------------------------------------------------
# T1 — the map carries the corpus
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheMapCarriesTheCorpus:
    """Every document, every exclusion, and nothing invented."""

    def test_every_catalog_row_is_on_the_page(
        self, page: str, catalog: CatalogProvider
    ) -> None:
        """Equality, not containment.

        A subset test passes a map that lost half the corpus, and a
        superset test passes one that invented a document. The page's
        claim is that it *is* the catalog, rendered — so the two sets are
        compared as sets.
        """
        listed = {path for path, _ in _rows(page)}
        cataloged = {record.canonical_source for record in catalog.documents()}
        assert listed == cataloged

    def test_every_current_row_is_in_a_reader_category(
        self, catalog: CatalogProvider
    ) -> None:
        """100% of the living/normative/generated rows, by id (plan §11 F2).

        The one exception is enumerated: a maintained page *about* the
        archive belongs with the archive, and naming it here is what makes
        a second such page a decision rather than a drift.
        """
        rows = {row.id: row for row in catalog.rows()}
        reader_sections = {section.key for section in CATEGORIES}
        current = {
            record.id
            for record in catalog.documents()
            if rows[record.id].status in CURRENT_STATUSES
        }
        placed = {
            record.id
            for record in catalog.documents()
            if category_of(record, rows[record.id]) in reader_sections
        }
        # The public export withholds the whole of ``docs/archive/`` (owner
        # ruling O-2, 2026-09-18), and the export drops those catalog rows
        # with it. So the exception is exactly the enumerated three where the
        # archive is in the checkout, and exactly nothing where it is not —
        # never "whichever of the three happen to be here".
        archive_here = (REPO_ROOT / "docs" / "archive").is_dir()
        expected = CURRENT_BUT_ARCHIVED if archive_here else frozenset()
        assert current - placed == expected
        assert placed <= current, "a non-current document reached a reader category"

    def test_the_ten_outside_the_audits_locations_are_all_present(
        self, page: str
    ) -> None:
        """The audit's own uncovered ten, closed by name."""
        listed = {path for path, _ in _rows(page)}
        excluded = {path for path, _ in _excluded_rows(page)}
        for path in OUTSIDE_THE_EIGHT_LOCATIONS:
            assert path in listed, path
        for path in OUTSIDE_AND_EXCLUDED:
            assert path in excluded, path
        assert len(OUTSIDE_THE_EIGHT_LOCATIONS) + len(OUTSIDE_AND_EXCLUDED) == 10

    def test_the_four_package_front_doors_are_where_a_reader_starts(
        self, catalog: CatalogProvider
    ) -> None:
        """Mapping rule 4, over the four documents that motivated it."""
        rows = {row.id: row for row in catalog.rows()}
        front_doors = {
            record.canonical_source: category_of(record, rows[record.id])
            for record in catalog.documents()
            if record.canonical_source.endswith("README.md")
            and record.canonical_source.count("/") <= 2
        }
        for source in (
            "README.md",
            "packages/s0ma-core/README.md",
            "packages/s0ma-dsl/README.md",
            "packages/s0ma-mcp/README.md",
            "packages/s0ma-studi0/README.md",
        ):
            assert front_doors[source] == UNDERSTAND, source

    def test_every_exclusion_is_on_the_page_with_its_reason(
        self, page: str, catalog: CatalogProvider
    ) -> None:
        excluded = {path for path, _ in _excluded_rows(page)}
        assert excluded == {item.path for item in catalog.exclusions()}
        for item in catalog.exclusions():
            assert item.reason.split()[0] in page

    def test_the_map_carries_its_own_row(
        self, page: str, catalog: CatalogProvider
    ) -> None:
        """The page names itself, and the catalog agrees it is generated."""
        assert f"{DOCS_ROOT}/{MAP_OUTPUT}" in {path for path, _ in _rows(page)}
        rows = {row.id: row for row in catalog.rows()}
        own = next(
            record
            for record in catalog.documents()
            if record.canonical_source == f"{DOCS_ROOT}/{MAP_OUTPUT}"
        )
        assert rows[own.id].status == "generated"
        assert own.id.startswith("doc:generated/")

    def test_the_counts_in_the_prose_are_the_counts_on_the_page(
        self, page: str, catalog: CatalogProvider
    ) -> None:
        """A map of record that miscounts itself teaches nobody to trust it."""
        total = len(catalog.documents())
        excluded = len(catalog.exclusions())
        assert f"There are {total} documents." in page
        assert f"{excluded} more tracked files" in page
        assert len(_rows(page)) == total
        assert len(_excluded_rows(page)) == excluded

    def test_every_section_is_rendered_and_none_is_empty(self, page: str) -> None:
        """A heading with no table under it is a mapping that stopped matching."""
        for section in SECTIONS:
            assert f"\n## {section.title}\n" in page, section.title
            assert section.blurb in page, section.title
        assert "Nothing is filed here in this build" not in page


# ---------------------------------------------------------------------------
# T1 — the information architecture and the guard column
# ---------------------------------------------------------------------------


class TestTheInformationArchitecture:
    """Architecture §9.1's five categories, and the rules that fill them."""

    def test_the_five_categories_are_the_architectures_five(self) -> None:
        assert [section.title for section in CATEGORIES] == [
            "Understand s0ma",
            "Build with s0ma",
            "Use the toolchain",
            "Reference",
            "Operate and contribute",
        ]

    def test_every_catalog_kind_has_a_home(self) -> None:
        """A kind the mapping has never heard of is a kind nobody placed.

        ``historical`` is deliberately absent from the table: rule 2
        catches it first, and a row here would say the archive is one of
        the five reader categories.
        """
        assert set(CATEGORY_BY_KIND) == set(KINDS) - {"historical"}
        assert set(CATEGORY_BY_KIND.values()) <= {
            section.key for section in CATEGORIES
        }

    def test_every_catalog_status_has_a_reader_word(self) -> None:
        assert set(STANDING_WORDS) == set(STATUSES)

    def test_the_trailing_sections_are_the_three_that_are_not_current(self) -> None:
        assert [section.key for section in TRAILING] == [
            MIRRORS,
            ARCHIVE,
            WORKING_NOTES,
        ]

    @requires_checkout
    def test_every_document_lands_in_exactly_one_section(
        self, composed: Build, catalog: CatalogProvider
    ) -> None:
        grouped = sections_of(composed.bundle, catalog.rows())
        placed = [identifier for ids in grouped.values() for identifier in ids]
        assert len(placed) == len(set(placed)) == len(composed.bundle.documents)

    @requires_checkout
    def test_mirrors_and_plans_never_reach_a_reader_category(
        self, catalog: CatalogProvider
    ) -> None:
        """Rules 1 and 3: a reader sent to a copy edits the copy."""
        rows = {row.id: row for row in catalog.rows()}
        for record in catalog.documents():
            row = rows[record.id]
            if row.status == "mirror":
                assert category_of(record, row) == MIRRORS, record.id
            if row.status == "working-plan":
                assert category_of(record, row) == WORKING_NOTES, record.id
            if row.status in {"historical", "superseded"}:
                assert category_of(record, row) == ARCHIVE, record.id

    @requires_checkout
    def test_the_language_authority_is_reference_and_the_decisions_are_not(
        self, catalog: CatalogProvider
    ) -> None:
        """Rule 6, over the three authority classes the catalog carries."""
        rows = {row.id: row for row in catalog.rows()}
        placed = {
            record.authority: category_of(record, rows[record.id])
            for record in catalog.documents()
            if record.authority
        }
        assert placed["authority:spec/current"] == "reference"
        assert placed["authority:prd/document"] == UNDERSTAND
        assert placed["authority:adr/repo.ADR-012"] == "operate"
        assert placed["authority:frozen_contract/feedback-v1"] == "operate"


class TestTheGuardColumn:
    """What the map says about a gate is what the gate does."""

    def test_the_version_gated_set_is_the_scripts_own_list(self) -> None:
        """The map restates ``LIVING_DOCS``; this is the pin that keeps it true."""
        living = frozenset(_script("check_version_refs").LIVING_DOCS)
        assert living == VERSION_CHECKED

    @requires_checkout
    def test_the_link_scope_agrees_with_the_link_checker_file_for_file(self) -> None:
        """Not the rule restated — the rule applied, over the whole corpus.

        Two predicates that agree on a handful of hand-picked paths can
        still disagree on the tree, which is the only place either of them
        is ever asked.
        """
        in_scope = _script("check_links").in_scope
        for relative in tracked_markdown(REPO_ROOT):
            assert links_checked(relative) is in_scope(relative), relative

    @requires_checkout
    def test_a_generated_page_is_byte_gated_and_a_plan_is_not(
        self, catalog: CatalogProvider
    ) -> None:
        rows = {row.id: row for row in catalog.rows()}
        by_source = {record.canonical_source: record for record in catalog.documents()}

        own = by_source[f"{DOCS_ROOT}/{MAP_OUTPUT}"]
        assert guards_of(own, rows[own.id]) == (GUARD_BYTES, GUARD_LINKS)

        readme = by_source["README.md"]
        assert guards_of(readme, rows[readme.id]) == (GUARD_LINKS, GUARD_VERSION)

        prd = by_source["references/s0ma-prd.md"]
        assert guards_of(prd, rows[prd.id]) == ()

    def test_the_page_explains_every_word_it_uses_in_that_column(
        self, page: str
    ) -> None:
        for word in (*GUARD_WORDS.values(), GUARD_ONLY_LISTED):
            assert f"`{word}`" in page, word


# ---------------------------------------------------------------------------
# T3 — links, anchors, voice, and byte stability
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheRenderedPage:
    """What the page owes its reader, and what the gates owe the page."""

    def test_every_link_on_the_map_names_a_tracked_file(self, page: str) -> None:
        """The unit form of the A5 gate, so a failure names the row."""
        tracked = _script("check_links").tracked_files(REPO_ROOT)
        for path, link in (*_rows(page), *_excluded_rows(page)):
            resolved = _script("check_links")._resolve(
                f"{DOCS_ROOT}/{MAP_OUTPUT}", link
            )
            assert resolved == path, (link, path)
            assert resolved in tracked, link

    def test_every_contents_entry_names_a_heading_on_the_page(
        self, page: str
    ) -> None:
        """The page's own anchors, slugged by the real slugger.

        :func:`~s0ma_dsl.docs_model.map_of_record.anchor` is a narrow case
        of github-slugger's rules. This asserts the section titles stay
        inside that case by checking the anchors against the rules
        ``scripts/check_links.py`` actually applies.
        """
        anchors = _script("check_links").document_anchors(page)
        for section in SECTIONS:
            assert anchor(section.title) in anchors, section.title
            assert f"(#{anchor(section.title)})" in page, section.title

    def test_the_a5_checker_passes_over_the_staged_tree(self) -> None:
        """The real exit code of the gate the map is now a subject of."""
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, str(SCRIPTS / "check_links.py")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "docs-links: PASS" in result.stdout

    def test_the_authored_framing_is_in_the_products_voice(self, page: str) -> None:
        """Rule 10, over the half of the page a person wrote.

        The tables are quotations — a document's own title, its path — and
        the voice rule deliberately does not reach a quotation (B4 finding
        4). What it reaches is the navigation: the headings, the sentences
        under them, and the column legend. Those are asserted through the
        rendered page rather than through the constants, so a sentence
        composed at render time is covered too.
        """
        authored = [
            line
            for line in page.splitlines()
            if not line.startswith("| ") and not line.startswith("|-")
        ]
        for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
            found = pattern.search("\n".join(authored))
            assert found is None, f"{label}: {found.group(0) if found else ''!r}"

    def test_rendering_twice_produces_the_same_bytes(self, composed: Build) -> None:
        again = build(REPO_ROOT, version=composed.bundle.stamp.release_version)
        assert again.artifact(MAP_OUTPUT).content == composed.artifact(
            MAP_OUTPUT
        ).content

    def test_the_committed_page_is_what_this_build_renders(
        self, composed: Build, page: str
    ) -> None:
        assert page == composed.artifact(MAP_OUTPUT).content

    def test_the_page_is_canonical_text(self, composed: Build) -> None:
        content = composed.artifact(MAP_OUTPUT).content
        assert "\r" not in content
        assert content.endswith("\n")
        assert not content.endswith("\n\n")
        assert str(REPO_ROOT) not in content


# ---------------------------------------------------------------------------
# T2 — the equivalence proof and the retirement
# ---------------------------------------------------------------------------


def _fixture_corpus(root: Path) -> tuple[list[str], Path]:
    """A two-file corpus: one classified document and one orphan.

    The orphan is the input A6's guard was written to catch — a tracked
    Markdown file nobody classified. Both gates are asked about the same
    tree, so "equivalent" means the same rejection of the same file rather
    than two rejections that happen to be red at the same time.
    """
    (root / "docs" / "s0ma_src").mkdir(parents=True)
    (root / "docs" / "guides").mkdir(parents=True)
    kept = root / "docs" / "guides" / "kept.md"
    kept.write_text("# Kept\n", encoding="utf-8", newline="\n")
    orphan = root / "docs" / "guides" / "orphan.md"
    orphan.write_text("# Nobody classified this\n", encoding="utf-8", newline="\n")

    (root / "docs" / "s0ma_src" / "catalog.json").write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "audiences": ["user"],
                        "authority": "",
                        "canonical_source": "docs/guides/kept.md",
                        "covers": [],
                        "governed_by": [],
                        "id": "doc:guide/kept",
                        "kind": "guide",
                        "prose_locator": "docs/guides/kept.md",
                        "status": "living",
                        "title": "A document somebody cataloged",
                    }
                ],
                "excluded": [],
                "schema": "s0ma-docs-catalog@1",
                "self": {
                    "audiences": ["contributor"],
                    "id": "doc:catalog/document-catalog",
                    "kind": "reference",
                    "status": "living",
                    "title": "The document catalog",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    ledger = root / "ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "audience": "user",
                        "disposition": "living-authored",
                        "note": "A document somebody classified.",
                        "path": "docs/guides/kept.md",
                    }
                ],
                "schema": "doc-classification@1",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return ["docs/guides/kept.md", "docs/guides/orphan.md"], ledger


def _the_retired_rule(ledger: Path, tracked: list[str]) -> list[str]:
    """A6's rule, restated exactly: every tracked ``.md`` has a ledger row.

    The deleted module's ``test_every_tracked_markdown_file_is_classified``
    and nothing else from it. Restated here so the equivalence proof can
    still run the old rule after the old file is gone — which is the only
    way the comparison outlives the thing being compared.
    """
    classified = {
        entry["path"]
        for entry in json.loads(ledger.read_text(encoding="utf-8"))["entries"]
    }
    return sorted(set(tracked) - classified)


class TestTheRetirementOfTheA6Guard:
    """Plan §10.3: prove the replacement rejects the same input, then delete."""

    def test_both_gates_reject_the_same_uncataloged_file(
        self, tmp_path: Path
    ) -> None:
        """The equivalence, on one fixture corpus, in one assertion each."""
        tracked, ledger = _fixture_corpus(tmp_path)

        caught_by_the_guard = _the_retired_rule(ledger, tracked)
        assert caught_by_the_guard == ["docs/guides/orphan.md"]

        findings = check_completeness(CatalogProvider(root=tmp_path), tracked)
        assert [finding.code for finding in findings] == [DOC_DOCUMENT_UNCATALOGED]
        assert [finding.location for finding in findings] == caught_by_the_guard
        assert "no row for it" in findings[0].message
        assert findings[0].remediation

    def test_both_gates_are_silent_once_the_file_is_accounted_for(
        self, tmp_path: Path
    ) -> None:
        """The other side of it: neither gate is red about everything.

        A replacement that rejected every input would also reject the one
        the old guard rejected, and would prove nothing.
        """
        tracked, ledger = _fixture_corpus(tmp_path)
        classified = tracked[:1]
        assert _the_retired_rule(ledger, classified) == []
        assert check_completeness(CatalogProvider(root=tmp_path), classified) == []

    def test_the_end_to_end_half_of_the_proof_is_where_f1_left_it(self) -> None:
        """The citation, pinned.

        F1 wrote the same rejection through the whole ``docs-application``
        stage against a planted checkout copy, and called it "the half F2
        will cite". Citing it in prose alone would let it be deleted
        without this milestone's claim noticing.
        """
        source = F1_GATE_TEST.read_text(encoding="utf-8")
        assert "def test_an_uncataloged_document_is_named" in source
        assert DOC_DOCUMENT_UNCATALOGED in source

    def test_the_temporary_guard_is_gone(self) -> None:
        """The deletion, recorded where a revert turns red.

        A6 wrote the guard as explicitly temporary and F2 owns removing
        it. This assertion is what stops it coming back by accident, and
        what makes bringing it back deliberately a conversation about the
        equivalence above.
        """
        assert not RETIRED_GUARD.exists(), (
            f"{RETIRED_GUARD.name} was retired at F2 — the catalog "
            f"completeness gate rejects the same input, proved above."
        )

    @requires_checkout
    def test_the_ledger_summary_says_the_retirement_happened(self) -> None:
        """The record, in the file that used to claim the guard was live."""
        summary = (REPO_ROOT / SUMMARY_REL).read_text(encoding="utf-8")
        assert "Milestone F2 retired it" in summary
        assert "test_doc_classification_ledger.py" in summary
        assert "temporary — the F2\ncatalog gate subsumes it" not in summary


@requires_checkout
class TestTheCatalogCarriesTheGuardsProperties:
    """What the retired guard checked about the ledger, the catalog checks."""

    def test_the_corpus_is_covered_with_nothing_left_over(
        self, catalog: CatalogProvider
    ) -> None:
        """The guard's coverage question, asked of the live tree."""
        missing = set(tracked_markdown(REPO_ROOT)) - catalog.cataloged_paths()
        assert missing == set()
        assert check_completeness(catalog, tracked_markdown(REPO_ROOT)) == []

    def test_the_ledger_still_classifies_every_tracked_file(self) -> None:
        """The record stays complete even though nothing enforces its shape.

        Not a re-implementation of the retired guard: this asserts that
        the A6 record was kept current through F2, which is what makes it
        usable as Phase G's migration map. C6's suite already holds the
        catalog and the ledger to the same corpus row for row; if the two
        ever have to diverge, this is the assertion that says so out loud.
        """
        entries = json.loads(
            (REPO_ROOT / LEDGER_REL).read_text(encoding="utf-8")
        )["entries"]
        assert set(tracked_markdown(REPO_ROOT)) <= {
            entry["path"] for entry in entries
        }

    def test_a_row_naming_a_file_that_is_not_there_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The guard's ``every classified path still exists``, carried over."""
        tracked, _ = _fixture_corpus(tmp_path)
        (tmp_path / tracked[0]).unlink()
        with pytest.raises(DocsCatalogError, match="not a file in this checkout"):
            CatalogProvider(root=tmp_path).documents()

    def test_a_status_outside_the_vocabulary_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The guard's frozen-enum check, carried over to the catalog's own."""
        _fixture_corpus(tmp_path)
        target = tmp_path / "docs" / "s0ma_src" / "catalog.json"
        document = json.loads(target.read_text(encoding="utf-8"))
        document["documents"][0]["status"] = "provisional"
        target.write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        with pytest.raises(DocsCatalogError, match="not a catalog status"):
            CatalogProvider(root=tmp_path).documents()

    def test_rows_out_of_order_or_repeated_are_refused(
        self, tmp_path: Path
    ) -> None:
        """The guard's ``unique and sorted``, carried over."""
        _fixture_corpus(tmp_path)
        target = tmp_path / "docs" / "s0ma_src" / "catalog.json"
        document: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
        document["documents"].append(dict(document["documents"][0]))
        target.write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        with pytest.raises(DocsCatalogError, match="repeat"):
            CatalogProvider(root=tmp_path).documents()


# ---------------------------------------------------------------------------
# The renderer's own refusals
# ---------------------------------------------------------------------------


class TestTheRendererRefusesAHole:
    """A map with a document it cannot describe is not rendered at all."""

    @requires_checkout
    def test_a_document_with_no_catalog_facts_is_refused(
        self, composed: Build, catalog: CatalogProvider
    ) -> None:
        from s0ma_dsl.docs_model.map_of_record import DocsMapError

        short = list(catalog.rows())[1:]
        with pytest.raises(DocsMapError, match="do not describe"):
            map_of_record(
                composed.bundle,
                rows=short,
                exclusions=catalog.exclusions(),
                docs_root=DOCS_ROOT,
            )
