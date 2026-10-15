"""The map of record: every document this repository keeps, on one page.

Milestone F2 of the docs-function plan (internal) §11. The August 2026 docs
audit measured the absence this module fills and stated it in one line —
*the orphaned docs are the stale docs*. There was no index: no
``docs/README.md``, no map anywhere, and the drift had concentrated exactly
where nothing pointed (the Aug 2026 docs audit (internal) §2). Ten of
the corpus's documents sat outside every location the audit's own table
named, four of them the package front doors a reader meets first.

So this page exists to make "unreachable" impossible to reach quietly:
every tracked Markdown file in this repository is either a row here or on
the short excluded list at the bottom, with the reason it is not
documentation. The two lists come from the same catalog reading the
completeness gate uses, so a document cannot be in the catalog and missing
from the map, or on the map and unknown to the build.

**Authored navigation, generated contents.** The five categories and their
labels are architecture plan §9.1's information architecture, written by a
person: *Understand s0ma*, *Build with s0ma*, *Use the toolchain*,
*Reference*, *Operate and contribute*. What goes in them is a query. §9.1
also lists sub-topics under each category ("What s0ma is", "Concepts and
vocabulary", "How the pieces relate"); those appear in each category's
opening sentence rather than as headings, because a second level of
navigation needs a second level of assignment rule and the catalog carries
no fact that would decide it honestly. F5's ``docs/learn/`` is where that
depth arrives.

**The mapping**, in order — the first rule that matches a row wins, and
every key is a catalog fact:

1. ``status`` is ``mirror`` — a byte-for-byte copy shipped inside a wheel.
   It goes to :data:`MIRRORS`, never into the five: a reader sent to a copy
   instead of an original is a reader who edits the copy.
2. ``status`` is ``historical`` or ``superseded``, **or** ``kind`` is
   ``historical`` — a record of the past. :data:`ARCHIVE`. The ``kind``
   half of that test is what catches a maintained page *about* the archive:
   its standing is current and its subject is not.
3. ``status`` is ``working-plan`` — a plan, a review note, or a spike
   record. :data:`WORKING_NOTES`.
4. The document is a **front door**: its canonical source is ``README.md``
   at the repository root or at a package root. A front door is where a
   reader arrives to find out what a thing *is*, which is §9.1's
   *Understand s0ma* whatever else the row says. (A ``README.md`` deeper in
   a tree — an ADR index, an archive note — is not a front door and is not
   caught here.)
5. The document **covers concepts and nothing else**: every id in ``covers``
   is a ``concept:``. That is a vocabulary source, and vocabulary is where a
   reader starts — *Understand s0ma* again. A guide that covers concepts
   *and* a journey is teaching a task, not defining terms, so the "nothing
   else" is load-bearing.
6. The document **is a written authority**, by the class in its
   ``authority`` id: ``prd`` says what the product is for (*Understand
   s0ma*), ``spec`` is §9.1's *Reference / Language*, and ``adr`` or
   ``frozen_contract`` is a decision on record (*Operate and contribute*).
7. Otherwise :data:`CATEGORY_BY_KIND`, with one split: a ``guide`` written
   for coding agents alone is authoring guidance and belongs with the
   tutorials in *Build with s0ma*; a ``guide`` with any other reader is
   about a part of the toolchain.

**The guard column is derived, and it is derived honestly.** A map that
said "guarded" without saying by what would be the audit's finding wearing
a tick. Four states, and a row carries every one that is true of it:

* *rebuilt and compared* — the file is regenerated and compared byte for
  byte (``status`` ``generated`` or ``mirror``);
* *links checked* — it is in ``scripts/check_links.py``'s scanned set, so
  every repository link and heading anchor in it has to resolve;
* *version checked* — it is one of ``scripts/check_version_refs.py``'s
  ``LIVING_DOCS``, so every version number in it has to be the version this
  repository ships;
* *listed only* — none of the above: the one automatic check on this
  document is that the build refuses a tracked document the catalog has no
  row for.

The last two gates live in ``scripts/``, which no wheel ships, so
:data:`VERSION_CHECKED` and :func:`links_checked` are this module's own
statement of them. That is a second copy, and it is why
``test_docs_map_of_record.py`` pins both against the real scripts: a
statement about a gate that the gate has outgrown is worse than no column.

**Determinism.** No clock, no network, no machine path. Every table is
sorted before it is rendered, every count is computed from the rows rather
than written down, and every link is repository-relative POSIX resolved
against the documentation root the caller names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.inventories import GENERATED_NOTE, cell, list_cell
from s0ma_dsl.docs_model.records import DocsModelError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from s0ma_dsl.docs_model.providers_catalog import CatalogRow, Exclusion
    from s0ma_dsl.docs_model.records import DocsBundle, DocumentRecord

__all__ = [
    "ARCHIVE",
    "AUDIENCE_WORDS",
    "CATEGORIES",
    "CATEGORY_BY_AUTHORITY",
    "CATEGORY_BY_KIND",
    "EXCLUDED",
    "GUARD_BYTES",
    "GUARD_LINKS",
    "GUARD_ONLY_LISTED",
    "GUARD_ORDER",
    "GUARD_VERSION",
    "GUARD_WORDS",
    "LINK_EXCLUDED_DIRS",
    "LINK_SCANNED_ROOT_DOCS",
    "MIRRORS",
    "SECTIONS",
    "STANDING_WORDS",
    "TRAILING",
    "DocsMapError",
    "UNDERSTAND",
    "VERSION_CHECKED",
    "WORKING_NOTES",
    "Section",
    "anchor",
    "category_of",
    "guards_of",
    "links_checked",
    "map_of_record",
    "sections_of",
]


# ---------------------------------------------------------------------------
# The sections — architecture §9.1's five, and the four that follow them
# ---------------------------------------------------------------------------


class DocsMapError(DocsModelError):
    """The map cannot be rendered from what it was handed.

    Raised rather than reported, and there is exactly one condition: a
    composed document whose presentation facts nobody supplied. Today the
    catalog is the only provider that emits a
    :class:`~s0ma_dsl.docs_model.records.DocumentRecord`, so the two views
    always arrive together; the machinery for a *derived* catalog row
    exists in :mod:`~s0ma_dsl.docs_model.providers_core` and is unused.
    When it is used, whoever emits the row emits its kind, status and
    readers with it — and until then this refusal is what stops the map
    quietly listing a document with no standing and no reader.
    """


@dataclass(frozen=True)
class Section:
    """One heading on the map, and the sentence under it.

    ``key`` is what :func:`category_of` returns and is never rendered;
    ``title`` is the heading a reader sees and the anchor is slugged from
    it; ``blurb`` is the authored sentence that says what the section is
    for. ``by_path`` decides the sort inside it: the five reader
    categories are sorted by title, because a reader is looking for a
    subject, and the trailing three by path, because somebody looking
    through the archive or the plans is looking for a place.
    """

    key: str
    title: str
    blurb: str
    by_path: bool = False


#: Architecture §9.1's five categories, in §9.1's order, with the
#: sub-topics it lists under each named in the sentence rather than as a
#: second level of heading.
UNDERSTAND = "understand"

CATEGORIES: tuple[Section, ...] = (
    Section(
        key=UNDERSTAND,
        title="Understand s0ma",
        blurb=(
            "What s0ma is, the words it uses, and how its four packages fit "
            "together. Start here if you have not met s0ma before: the front "
            "doors say what each part is for, and the two vocabulary files "
            "define every term the rest of the documentation leans on."
        ),
    ),
    Section(
        key="build",
        title="Build with s0ma",
        blurb=(
            "Getting a project running and writing your first declarations, "
            "then checking, building and testing them. The tutorials go from "
            "an empty directory to a working module; the guides beside them "
            "are the same ground written for a coding agent doing the work."
        ),
    ),
    Section(
        key="toolchain",
        title="Use the toolchain",
        blurb=(
            "The parts you work through day to day: your editor, the server "
            "a coding agent talks to, and the viewer that shows you what you "
            "built. What each command and served capability does is in "
            "Reference below."
        ),
    ),
    Section(
        key="reference",
        title="Reference",
        blurb=(
            "Look-up material. The language specification is the authority "
            "on what a .s0ma file may say; the generated indexes are the "
            "complete lists of what s0ma knows and what it can do; the cards "
            "are short forms a coding agent reads before it starts."
        ),
    ),
    Section(
        key="operate",
        title="Operate and contribute",
        blurb=(
            "Running s0ma when something has gone wrong, releasing it, and "
            "working on s0ma itself. The decision records and frozen "
            "contracts are here because they are what this repository holds "
            "itself to, and reading them is how a change gets proposed "
            "without re-opening a settled question."
        ),
    ),
)

#: The three sections that come after the five, and the excluded list that
#: closes the page. Each is a place for documents that are real and are not
#: current guidance — kept visible rather than dropped, because a document
#: nothing points at is a document nobody notices going stale.
MIRRORS = "mirrors"
ARCHIVE = "archive"
WORKING_NOTES = "notes"
EXCLUDED = "excluded"

TRAILING: tuple[Section, ...] = (
    Section(
        key=MIRRORS,
        title="Copies inside the wheels",
        blurb=(
            "Byte-for-byte copies of documents listed above, packaged so a "
            "coding agent that installed s0ma has them without a checkout. "
            "Read the original: a copy that drifts from its source fails the "
            "build, and an edit made here is lost at the next one."
        ),
        by_path=True,
    ),
    Section(
        key=ARCHIVE,
        title="The archive",
        blurb=(
            "Records of how s0ma used to work, short stubs left behind where "
            "a document moved, and the maintained notes that describe the "
            "archive itself. They are kept so a decision can be traced back "
            "to what was true when it was taken. Do not read them as current "
            "guidance."
        ),
        by_path=True,
    ),
    Section(
        key=WORKING_NOTES,
        title="Working notes and plans",
        blurb=(
            "The plans, review notes and experiment records behind the "
            "documents above. They are internal, they are written to be "
            "worked through rather than read, and each one stops being true "
            "the day its work lands."
        ),
        by_path=True,
    ),
)

#: Every section, in the order they are rendered.
SECTIONS: tuple[Section, ...] = (*CATEGORIES, *TRAILING)


# ---------------------------------------------------------------------------
# The mapping (rules 6 and 7)
# ---------------------------------------------------------------------------

#: Where a document goes when nothing more specific has claimed it — the
#: last rule, keyed on the one catalog fact that is about what a document
#: *is* for a reader. ``historical`` is absent on purpose: rule 2 catches
#: it before this table is consulted, and a kind that meant "archive" here
#: would say the archive is one of the five categories.
CATEGORY_BY_KIND: Mapping[str, str] = {
    "contributing": "operate",
    "guide": "toolchain",
    "normative": "operate",
    "operations": "operate",
    "reference": "reference",
    "tutorial": "build",
}

#: Which category each class of written authority belongs to (rule 6). The
#: authority id's class is the part before the slash.
CATEGORY_BY_AUTHORITY: Mapping[str, str] = {
    "adr": "operate",
    "frozen_contract": "operate",
    "prd": UNDERSTAND,
    "spec": "reference",
}


def _is_front_door(canonical_source: str) -> bool:
    """True for the repository's README and each package's (rule 4)."""
    parts = canonical_source.split("/")
    if parts == ["README.md"]:
        return True
    return len(parts) == 3 and parts[0] == "packages" and parts[2] == "README.md"


def _covers_only_concepts(covers: Sequence[str]) -> bool:
    """True when every id this document covers is a concept (rule 5)."""
    return bool(covers) and all(item.startswith("concept:") for item in covers)


def category_of(record: DocumentRecord, row: CatalogRow) -> str:
    """Which section ``record`` belongs to — the module docstring's rules.

    Takes both views of one catalog row: the record carries the coverage,
    the authority and the file, and the row carries the kind, the status
    and the readers. Neither alone can answer, which is why the map is
    rendered from the catalog rather than from the bundle's documents.

    A kind outside :data:`CATEGORY_BY_KIND` is not silently dropped into a
    default section — the catalog's kind vocabulary is closed, so an
    unmapped kind is a new kind, and it goes to *Reference*, which is the
    section whose promise ("look it up here") stays true for a document
    nobody has classified yet. The map's completeness test is what turns
    that into a decision somebody takes.
    """
    if row.status == "mirror":
        return MIRRORS
    if row.status in {"historical", "superseded"} or row.kind == "historical":
        return ARCHIVE
    if row.status == "working-plan":
        return WORKING_NOTES
    if _is_front_door(record.canonical_source) or _covers_only_concepts(record.covers):
        return UNDERSTAND
    if record.authority:
        named = CATEGORY_BY_AUTHORITY.get(record.authority.partition(":")[2].partition("/")[0])
        if named is not None:
            return named
    if row.kind == "guide" and row.audiences == ("agent",):
        return "build"
    return CATEGORY_BY_KIND.get(row.kind, "reference")


# ---------------------------------------------------------------------------
# The guard column
# ---------------------------------------------------------------------------

GUARD_BYTES = "bytes"
GUARD_LINKS = "links"
GUARD_VERSION = "version"

#: The order guards are listed in a cell — strongest first, so two rows
#: with the same guards read the same way.
GUARD_ORDER: tuple[str, ...] = (GUARD_BYTES, GUARD_LINKS, GUARD_VERSION)

#: What each guard is called on a page a person reads.
GUARD_WORDS: Mapping[str, str] = {
    GUARD_BYTES: "rebuilt and compared",
    GUARD_LINKS: "links checked",
    GUARD_VERSION: "version checked",
}

#: What a row says when no gate but the catalog reaches it. Not "none":
#: being listed here at all is a check, and it is the one the whole page
#: exists to make mechanical.
GUARD_ONLY_LISTED = "listed only"

#: ``scripts/check_version_refs.py``'s ``LIVING_DOCS`` — the documents whose
#: version references are claims about the current release. Restated here
#: because that script ships in no wheel; pinned to it by the F2 suite.
VERSION_CHECKED: frozenset[str] = frozenset(
    {
        ".github/PULL_REQUEST_TEMPLATE.md",
        "AGENTS.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "README.md",
        "SECURITY.md",
        "docs/RELEASING.md",
        "docs/documentation-subsystem.md",
        "docs/getting-started.md",
        "docs/getting-started/first-project.md",
        "docs/guides/claude-integration.md",
        "docs/guides/drift-recovery.md",
        "docs/guides/first-module.md",
        "docs/guides/mcp-authoring.md",
        "docs/guides/retrofit-existing-codebase.md",
        "docs/guides/studi0-feedback.md",
        "docs/hosting-getting-started.md",
        "docs/operations/docs-maintenance.md",
        "docs/stability.md",
        "docs/troubleshooting.md",
        "docs/trust-model.md",
        "docs/uninstall.md",
        "docs/walkthrough.md",
        "editors/README.md",
        "integrations/claude/plugin/skills/doctor/SKILL.md",
        "integrations/claude/plugin/skills/feedback/SKILL.md",
        "integrations/claude/plugin/skills/new/SKILL.md",
        "integrations/claude/plugin/skills/retrofit/SKILL.md",
        "integrations/claude/plugin/skills/setup/SKILL.md",
        "integrations/claude/plugin/skills/update/SKILL.md",
        "packages/s0ma-core/README.md",
        "packages/s0ma-dsl/README.md",
        "packages/s0ma-mcp/README.md",
        "packages/s0ma-studi0/README.md",
    }
)

#: ``scripts/check_links.py``'s root-level scanned documents.
LINK_SCANNED_ROOT_DOCS: frozenset[str] = frozenset(
    {"AGENTS.md", "CONTRIBUTING.md", "README.md"}
)

#: The directory names that script excludes wherever they appear.
LINK_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {"_built", "_docs", "_generated", "historical", "plans"}
)


def links_checked(canonical_source: str) -> bool:
    """True when ``scripts/check_links.py`` scans this file.

    The same scope rule, restated: the three root documents, everything
    under ``docs/``, and each package's ``README.md`` plus its ``docs/``
    tree — minus the mirror, build, generated and historical directories,
    and minus ``plans/``.
    """
    if not canonical_source.endswith(".md"):
        return False
    parts = canonical_source.split("/")
    if LINK_EXCLUDED_DIRS.intersection(parts[:-1]):
        return False
    if canonical_source in LINK_SCANNED_ROOT_DOCS:
        return True
    if parts[0] == "docs":
        return True
    if parts[0] == "packages" and len(parts) >= 3:
        return parts[2] == "README.md" or (len(parts) >= 4 and parts[2] == "docs")
    return False


def guards_of(record: DocumentRecord, row: CatalogRow) -> tuple[str, ...]:
    """Every automatic check that reaches this document, in a fixed order."""
    found: set[str] = set()
    if row.status in {"generated", "mirror"}:
        found.add(GUARD_BYTES)
    if links_checked(record.canonical_source):
        found.add(GUARD_LINKS)
    if record.canonical_source in VERSION_CHECKED:
        found.add(GUARD_VERSION)
    return tuple(name for name in GUARD_ORDER if name in found)


# ---------------------------------------------------------------------------
# Reader words for the catalog's vocabularies
# ---------------------------------------------------------------------------

#: The catalog's audiences, in the words a reader uses about themselves.
AUDIENCE_WORDS: Mapping[str, str] = {
    "agent": "agents",
    "contributor": "contributors",
    "owner": "owner",
    "user": "users",
}

#: The catalog's statuses, said as what a reader should do about them. A
#: status absent here renders under its own name rather than being dropped,
#: for the reason the surfaces index renders an unknown channel: a row that
#: quietly lost its standing is worse than an ugly word.
STANDING_WORDS: Mapping[str, str] = {
    "generated": "generated",
    "historical": "historical",
    "living": "maintained",
    "mirror": "copy",
    "normative": "binding",
    "superseded": "moved",
    "working-plan": "working note",
}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def anchor(title: str) -> str:
    """A section heading's GitHub anchor.

    The narrow case of github-slugger's rules that every heading on this
    page stays inside: lowercase, drop anything that is not a letter, a
    digit, a space or a hyphen, then spaces become hyphens. The section
    titles are this module's own constants, and the suite asserts they stay
    inside that case, so the page's contents list resolves under
    ``scripts/check_links.py``'s real slugger rather than under this one.
    """
    kept = [
        character
        for character in title.lower()
        if character.isalnum() or character in {" ", "-"}
    ]
    return "".join(kept).strip().replace(" ", "-")


def _relative_link(canonical_source: str, docs_root: str) -> str:
    """``canonical_source`` as a link from a page inside ``docs_root``.

    The documentation root is one directory below the checkout root, so
    everything outside it is exactly one step up. Repository-relative
    POSIX in, repository-relative POSIX out; no machine path can reach a
    rendered link (INV-5).
    """
    prefix = f"{docs_root}/"
    if canonical_source.startswith(prefix):
        return canonical_source[len(prefix) :]
    return f"../{canonical_source}"


def _row(
    record: DocumentRecord, row: CatalogRow, docs_root: str
) -> str:
    """One document as a table row: what it is, where, for whom, and gated how."""
    guards = guards_of(record, row)
    return (
        f"| [{cell(record.title)}]({_relative_link(record.canonical_source, docs_root)}) "
        f"| `{cell(record.canonical_source)}` "
        f"| {list_cell([AUDIENCE_WORDS.get(name, name) for name in row.audiences], absent='—')} "
        f"| {cell(STANDING_WORDS.get(row.status, row.status))} "
        f"| {list_cell([GUARD_WORDS[name] for name in guards], absent=GUARD_ONLY_LISTED)} |"
    )


def _table(
    entries: Sequence[tuple[DocumentRecord, CatalogRow]],
    docs_root: str,
    *,
    by_path: bool,
) -> list[str]:
    """One section's table, sorted the way its section asked to be sorted."""
    if not entries:
        return [
            "Nothing is filed here in this build. That is either a corpus "
            "this small or a mapping that has stopped matching — the "
            "document catalog is where to look.",
            "",
        ]
    ordered = sorted(
        entries,
        key=(
            (lambda pair: (pair[0].canonical_source, pair[0].id))
            if by_path
            else (lambda pair: (pair[0].title.casefold(), pair[0].id))
        ),
    )
    lines = [
        "| Document | Where | For | Standing | Kept true by |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(_row(record, row, docs_root) for record, row in ordered)
    lines.append("")
    return lines


def _excluded_table(exclusions: Sequence[Exclusion], docs_root: str) -> list[str]:
    """The files the catalog accounts for by saying they are not documents."""
    if not exclusions:
        return [
            "Nothing. Every tracked Markdown file in this repository is a "
            "document with a row above.",
            "",
        ]
    lines = ["| File | Why it is not a document |", "| --- | --- |"]
    lines.extend(
        f"| [`{cell(item.path)}`]({_relative_link(item.path, docs_root)}) "
        f"| {cell(item.reason)} |"
        for item in sorted(exclusions, key=lambda item: item.path)
    )
    lines.append("")
    return lines


def _opening(
    grouped: Mapping[str, list[tuple[DocumentRecord, CatalogRow]]],
    excluded: int,
) -> list[str]:
    """The page's first screen: what it is, how big it is, how to read it.

    Every number here is counted from the rows this build composed. A
    hand-written total is the first thing a map of record gets wrong, and
    getting it wrong is how a reader learns not to trust the page.
    """
    current = sum(len(grouped[section.key]) for section in CATEGORIES)
    total = sum(len(entries) for entries in grouped.values())
    return [
        "# The s0ma documentation",
        "",
        GENERATED_NOTE,
        "",
        "This is the map of record: every document this repository keeps, "
        "what it is, who it is written for, and which automatic check keeps "
        "it honest. It is built from the same document catalog the "
        "documentation build reads, so a document cannot be on this page "
        "and unknown to the build, or known to the build and missing here.",
        "",
        "A row here is wrong, or a document is missing? The place to fix it "
        "is the catalog this page is rendered from — "
        "[`docs/s0ma_src/catalog.json`](s0ma_src/catalog.json) — and the "
        "next build writes the page again.",
        "",
        f"There are {total} documents. {current} of them describe s0ma as it "
        f"is now and are grouped below by what you would be trying to do; "
        f"the rest are copies that ship inside the wheels, records of the "
        f"past, and working notes, each behind its own heading further down. "
        f"{excluded} more tracked files are listed at the end as what they "
        f"are: test data rather than documentation.",
        "",
        "## Contents",
        "",
        *[f"- [{section.title}](#{anchor(section.title)})" for section in SECTIONS],
        f"- [Files this map does not carry](#{anchor('Files this map does not carry')})",
        "",
        "## How to read the tables",
        "",
        "Every table below has the same five columns. **Where** is the "
        "file's path from the top of the repository. **For** says who it is "
        "written for: `users` are people using or evaluating s0ma, `agents` "
        "are coding agents working through the command line or the MCP "
        "server, `contributors` are whoever works in this repository, and "
        "`owner` is whoever decides what s0ma is.",
        "",
        "**Standing** says what the document is. `binding` is a written "
        "authority the rest of the documentation defers to. `maintained` is "
        "hand-written and kept current. `generated` is written by the build "
        "from something else, so an edit to it is lost at the next build. "
        "`copy`, `historical`, `moved` and `working note` are the four kinds "
        "of document that are real and are not current guidance.",
        "",
        "**Kept true by** names the automatic checks that run on that file "
        "in this repository, and it is deliberately blunt about how few "
        "reach some of them:",
        "",
        f"- `{GUARD_WORDS[GUARD_BYTES]}` — the build renders the file again "
        f"and refuses any difference, so it cannot quietly stop describing "
        f"what it describes.",
        f"- `{GUARD_WORDS[GUARD_LINKS]}` — every link and heading it points "
        f"at has to resolve to something that is really there.",
        f"- `{GUARD_WORDS[GUARD_VERSION]}` — every version number in it has "
        f"to be the version this repository ships.",
        f"- `{GUARD_ONLY_LISTED}` — none of the above. The one automatic "
        f"check on this document is the one that put it on this page: the "
        f"build refuses a tracked document the catalog has no row for.",
        "",
    ]


def _joined(
    bundle: DocsBundle, rows: Iterable[CatalogRow]
) -> list[tuple[DocumentRecord, CatalogRow]]:
    """Every composed document beside the catalog facts about it.

    Joined on the id, which is the only key both views carry. A record
    with no row is refused rather than rendered with an absent standing,
    for the reason
    :func:`~s0ma_dsl.docs_model.inventories.component_facts` refuses a
    component no reading can describe: a listing with a hole in it makes
    every count taken from it wrong by an amount nobody can see.
    """
    by_id = {row.id: row for row in rows}
    joined: list[tuple[DocumentRecord, CatalogRow]] = []
    for record in bundle.documents:
        row = by_id.get(record.id)
        if row is None:
            raise DocsMapError(
                f"{record.id} is a document this build composed and the "
                f"catalog facts handed to the map do not describe: there is "
                f"no kind, no standing and no reader for it. Whatever "
                f"provider emitted the record has to emit those with it."
            )
        joined.append((record, row))
    return joined


def map_of_record(
    bundle: DocsBundle,
    *,
    rows: Sequence[CatalogRow],
    exclusions: Sequence[Exclusion],
    docs_root: str,
) -> str:
    """The whole map, as Markdown.

    ``rows`` are the catalog's presentation facts, joined to the bundle's
    document records by id. A record with no row is not rendered with an
    absent standing: it is refused, for the reason
    :func:`~s0ma_dsl.docs_model.inventories.component_facts` refuses a
    component no reading can describe — a map with a hole in it makes every
    count taken from it wrong by an amount nobody can see.

    ``exclusions`` are the tracked files the catalog accounts for by saying
    they are not documents. They are rendered because the page's claim is
    about the whole corpus: every tracked Markdown file is a row here or a
    line at the bottom, and a claim with a silent third option is not a
    claim.
    """
    grouped: dict[str, list[tuple[DocumentRecord, CatalogRow]]] = {
        section.key: [] for section in SECTIONS
    }
    for record, row in _joined(bundle, rows):
        grouped[category_of(record, row)].append((record, row))

    lines = _opening(grouped, len(exclusions))
    for section in SECTIONS:
        lines.append(f"## {section.title}")
        lines.append("")
        lines.append(section.blurb)
        lines.append("")
        lines.extend(_table(grouped[section.key], docs_root, by_path=section.by_path))
    lines.append("## Files this map does not carry")
    lines.append("")
    lines.append(
        "Tracked Markdown files that are not documentation. Each one says "
        "why, because a file left off a map of record silently and a file "
        "left off it for a written reason look the same from outside, and "
        "only one of them is reviewable."
    )
    lines.append("")
    lines.extend(_excluded_table(exclusions, docs_root))
    return "\n".join(lines).rstrip("\n") + "\n"


def sections_of(
    bundle: DocsBundle, rows: Iterable[CatalogRow]
) -> Mapping[str, tuple[str, ...]]:
    """Which section every document landed in, by id — the mapping, queryable.

    The renderer's grouping without the rendering, so a test can assert the
    mapping over the real catalog without parsing a page back out of its
    own Markdown.
    """
    grouped: dict[str, list[str]] = {section.key: [] for section in SECTIONS}
    for record, row in _joined(bundle, rows):
        grouped[category_of(record, row)].append(record.id)
    return {key: tuple(sorted(values)) for key, values in grouped.items()}
