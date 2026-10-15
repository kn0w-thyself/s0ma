"""The learning collection: one page per concept, a glossary, an anatomy.

Milestone F5 of the docs-function plan (internal) §11. Architecture §8.1
asks for general knowledge as a first-class authored layer rendered into
"a human learning collection, a concise glossary, CLI topic responses, MCP
topic responses, and relationship maps". This module is the first two of
those five, as files a person can open: ``docs/learn/<term>.md`` for every
concept the build composed, ``docs/learn/glossary.md`` over all of them at
once, and ``docs/learn/anatomy-of-a-s0ma-file.md`` — the reference-shaped
account of what a source file is made of.

**This is C7's page renderer, aimed at a file rather than at a terminal.**
A concept page *is* a human-channel rendering of a topic:
:func:`~s0ma_dsl.docs_model.resolve.facts_of` produces the view, C7's
:func:`~s0ma_dsl.docs_model.render_human.spec_for` produces the headings
and their order, and this module writes them out. What it adds is what a
file needs and a terminal does not — the sentence saying the page is
generated, and links, because a page on disk sits beside its neighbours
and a reader should be able to walk to them.

**Why that makes it a channel of its own and not a flag on C7's.** B5
clause 2 says a rendering has to be readable back into the facts it
carries. C7 writes a related concept as a backticked id and reads it back
by taking the backticks off; this channel writes it as a link to that
concept's page, and a reader that stripped backticks would hand back
``[contract](contract.md)`` and call it a fact. So the transformation is
declared here, :func:`extract` reads it back here, and the residue proof
runs against this channel's own declaration. One renderer with two
irreconcilable read-backs would be a renderer that agrees with a page it
has corrupted.

The declaration, in the same four parts C7 declares in:

* **labels** — C7's, unchanged and imported rather than copied. A concept
  page's headings are the human channel's headings because a concept page
  is a human page; a second table here would be a second opinion about
  what ``do_not_use_when`` is called, and the two would drift.
* **order** — C7's, with one section added at the end
  (:data:`NEXT_HEADING`) and the identity block after it. The added
  section carries no fact of the topic, so it is envelope rather than a
  fact with a label.
* **envelope** — the generated-page sentence, the "where to look next"
  heading, the rule above the identity block, and the identity heading.
* **transformations** — C7's, plus the five this channel applies: the
  generated note, the linked relations, the navigation block, the
  relative link out of this directory, and the collection pages'
  two-bullet identity block.

**Nothing on any of these pages is written by this module except headings,
labels and computed counts.** Every sentence a reader meets is authored
prose from a concept record, reproduced word for word — including on the
anatomy page, which is assembled entirely out of ``concept:s0ma-file`` and
the eleven declaration kinds rather than narrated. Every number is
computed at render time and none is written down, which is the rule
architecture §8.2 states for a living document and the reason the two
generated indexes exist at all.

**Where the eleven declaration kinds come from.** Not a list in this file.
A declaration kind is a concept that declares ``part-of
concept:s0ma-file``, and their order on the anatomy page is the order the
specification numbers their sections in — read from the authorities those
concepts cite. Both are facts of the composed model, so a twelfth
declaration kind appears on the anatomy page by being authored, and this
module never has to hear about it.

Every path is repository-relative POSIX (INV-5), every page ends in
exactly one line feed, and nothing here writes, reads a file, or opens a
socket: the caller supplies the bundle, the alias index and nothing else.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.ids import DocsIdError, normalize_id, validate_id
from s0ma_dsl.docs_model.inventories import GENERATED_NOTE, cell
from s0ma_dsl.docs_model.render_human import EMPTY_MARKER, IDENTITY_HEADING, SECTION_FACTS
from s0ma_dsl.docs_model.render_human import TRANSFORMATIONS as HUMAN_TRANSFORMATIONS
from s0ma_dsl.docs_model.render_human import spec_for as human_spec_for
from s0ma_dsl.docs_model.resolve import (
    IDENTITY_FACTS,
    LIST_FACTS,
    DocsResolveError,
    PresentationSpec,
    facts_of,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from s0ma_dsl.docs_model.ids import AliasIndex
    from s0ma_dsl.docs_model.records import (
        AuthorityRef,
        ConceptRecord,
        DocsBundle,
        DocumentRecord,
        JourneyRecord,
    )
    from s0ma_dsl.docs_model.resolve import FactValue, TopicView

__all__ = [
    "ANATOMY_OUTPUT",
    "ANATOMY_SECTIONS",
    "ANATOMY_TITLE",
    "CHANNEL",
    "CONCEPT_PREFIX",
    "ENVELOPE",
    "FILE_CONCEPT",
    "GLOSSARY_OUTPUT",
    "GLOSSARY_TITLE",
    "LEARN_DIR",
    "NEXT_HEADING",
    "PAGE_TITLE",
    "PART_OF",
    "REFERENCE_LINKS",
    "TRANSFORMATIONS",
    "DocsLearnError",
    "anatomy_page",
    "catalog_rows",
    "concept_page",
    "declaration_kinds",
    "extract",
    "glossary_page",
    "learn_outputs",
    "learn_pages",
    "page_path",
    "page_slug",
    "relative_to_learn",
    "spec_for_concept",
    "stale_pages",
    "undeclared_headings",
]


class DocsLearnError(DocsResolveError):
    """A page cannot be rendered honestly from the model it was handed.

    A :class:`~s0ma_dsl.docs_model.resolve.DocsResolveError` because that
    is what it is: every one of these is a rendering asked to point at
    something the composed model does not address — a related concept with
    no record, two concepts whose terms want the same file, a collection
    whose anchor concept is absent. Raised rather than reported, for the
    reason a provider raises on a malformed source: a page with a dead
    link in it is worse than no page, because a reader follows it.
    """


# ---------------------------------------------------------------------------
# Where the collection lives
# ---------------------------------------------------------------------------

#: The collection's directory, relative to
#: :data:`~s0ma_dsl.docs_model.application.DOCS_ROOT`. Reader-facing
#: Markdown, so ``docs/`` rather than ``docs/_generated/`` (ADR-012 §1) —
#: only these pages' *provenance* is generated, and each one says so.
LEARN_DIR = "learn"

#: The two collection pages, relative to the documentation root. Named
#: here rather than derived because they are decisions about the
#: collection's shape; the thirty-seven concept pages are derived, because
#: which concepts exist is not this module's decision to make.
GLOSSARY_OUTPUT = f"{LEARN_DIR}/glossary.md"
ANATOMY_OUTPUT = f"{LEARN_DIR}/anatomy-of-a-s0ma-file.md"

#: The id prefix every page in this collection is rendered from.
CONCEPT_PREFIX = "concept:"

#: The concept the anatomy page is about. It is an id rather than a
#: heading of prose because the page is a rendering of that record: if the
#: record goes, the page must fail loudly rather than render an anatomy of
#: nothing.
FILE_CONCEPT = "concept:s0ma-file"

#: The relation that makes a concept one of the file's parts. The eleven
#: declaration kinds are exactly the concepts that declare it against
#: :data:`FILE_CONCEPT`, and nothing in this module writes their names
#: down (see :func:`declaration_kinds`).
PART_OF = "part-of"


# ---------------------------------------------------------------------------
# The declaration (B5 clause 1)
# ---------------------------------------------------------------------------

#: This channel's name. Not ``human``: same headings, different read-back
#: (see the module docstring), and two channels sharing a name would make
#: a residue proof ambiguous about which declaration it was proving.
CHANNEL = "learn"

#: The heading over the block of links at the foot of a page, above the
#: identity block. It carries no fact of the topic — every link in it is
#: derived from the model, but *which* neighbours a page offers is a
#: decision about the collection — so it is envelope.
NEXT_HEADING = "## Where to look next"

#: The blocks these pages add that carry no fact.
ENVELOPE: tuple[str, ...] = (GENERATED_NOTE, NEXT_HEADING, IDENTITY_HEADING, "---")

#: What this channel does that C7's does not.
TRANSFORMATIONS: tuple[str, ...] = (
    *HUMAN_TRANSFORMATIONS,
    "the generated-page sentence is written once, under the title",
    "a related concept is written as its relation word and a link to its "
    "page in this collection",
    "the links to neighbouring pages are written under one heading at the "
    "foot, above the identity block",
    "a link out of this directory is written relative to it",
    "a collection page's identity block carries the release and the "
    "snapshot and no topic id, because a collection is not a topic",
)

#: The generated references a concept page points at, in the order a
#: reader meets them, as ``(path relative to the documentation root,
#: link text)``. Written here rather than read from the catalog because a
#: link's *text* is presentation: the catalog's title for the surfaces
#: index is the page's own ``# What s0ma can do``, and a navigation block
#: that repeated it would read as a sentence rather than as a signpost.
#:
#: The quick reference first: it is the one page that holds every kind of
#: declaration and every line of each, so it is where a reader who has
#: just read about one of them goes to see it among the rest. Then two
#: indexes, then the five per-family references F3 and F4 added
#: — broadest first, because a reader who has just learned what a nerve is
#: wants the shape of the whole surface before one family of it. The two
#: remaining generated references are deliberately absent: the packages
#: page and the component index answer *how this repository is built*,
#: which is a contributor's next question and not this reader's, and a
#: signpost block that offered every generated page would stop being a
#: signpost. Both stay one click away through the map of record.
REFERENCE_LINKS: tuple[tuple[str, str], ...] = (
    ("reference/quick-reference-readable.md", "Every kind of declaration, line by line"),
    ("reference/concepts-index.md", "Every concept, in one table"),
    ("reference/surfaces-index.md", "Everything s0ma can do"),
    ("reference/cli.md", "Every command, and what it takes"),
    ("reference/configuration.md", "Every setting a project can declare"),
    ("reference/diagnostics.md", "Every report s0ma can make"),
    ("reference/mcp.md", "What s0ma answers an agent with"),
    ("reference/studi0.md", "What the viewer shows you"),
)

#: The anatomy page's sections, in the order they are rendered. Its own
#: rather than C7's: the page is a rendering of one concept *and* of the
#: eleven concepts that are parts of it, which is a shape no topic view
#: has, so its headings are declared here and the suite asserts every one
#: of them appears exactly once.
ANATOMY_TITLE = "Anatomy of a .s0ma file"
ANATOMY_SECTIONS: tuple[str, ...] = (
    "## In short",
    "## What it is",
    "## Why it exists",
    "## The shape of the file",
    "## The parts a file is made of",
    "## The smallest complete file",
)

#: How a concept page is named in the document catalog, given the concept's
#: term. The page's own H1 is the bare term — that is what a reader who has
#: opened the file needs — and this is the name the rest of the model knows
#: the *document* by, which has to be a name no concept already has. See
#: :func:`catalog_rows` for what goes wrong when it is not.
PAGE_TITLE = "{term}, explained"

#: The glossary's title. The audit's missing-public-glossary gap closes at
#: this page, so it is named for what a reader would search for.
GLOSSARY_TITLE = "Glossary"

#: The glossary's second section: the alternate names that resolve onto a
#: term above it.
GLOSSARY_ALIASES_HEADING = "## Other names for the same ideas"

_RULE = "---"
_FENCE = "```"
_OPEN_FENCE = "```text"
_HEADING_LINE = re.compile(r"^(#{1,6})\s+(.*)$")
_FOOTER_LINE = re.compile(r"^- ([^:]+): `(.*)`$")
_BACKTICKED_ITEM = re.compile(r"^`(.*)`$", re.DOTALL)
#: One related-concept line: the relation word, then the link to the page.
_RELATED_ITEM = re.compile(r"^(?P<relation>\S+) \[(?P<term>.*)\]\((?P<slug>[^)]*)\.md\)$")

#: The list facts C7 writes between backticks and this channel writes the
#: same way. ``related_concepts`` is deliberately absent: it is the one
#: this channel links instead, which is the whole reason it is a channel.
_BACKTICKED: frozenset[str] = frozenset({"authority_refs", "authority_sources", "example_ids"})

#: The identity bullets a concept page carries — C7's three, unchanged.
_FOOTER: Mapping[str, str] = {
    "topic_id": "Topic id",
    "release_version": "Release",
    "snapshot_hash": "Documentation snapshot",
}

#: The identity bullets a collection page carries. A glossary is not a
#: topic and has no topic id; saying it had one would put an id into the
#: model's only join key that answers to no record. What it can honestly
#: say is which build it describes, and that is what a reader needs.
_COLLECTION_FOOTER: tuple[str, ...] = ("release_version", "snapshot_hash")


def spec_for_concept() -> PresentationSpec:
    """This channel's declaration for a concept page.

    C7's, with this channel's name and this channel's transformations. The
    labels and the order are imported rather than restated so that a
    heading reworded there is reworded here, and so the proof that the
    sections are a permutation of the group's facts — which C7's suite
    owns — covers this channel too.
    """
    human = human_spec_for("concepts")
    return PresentationSpec(
        channel=CHANNEL,
        labels=human.labels,
        order=human.order,
        envelope=ENVELOPE,
        transformations=TRANSFORMATIONS,
    )


# ---------------------------------------------------------------------------
# Paths and links
# ---------------------------------------------------------------------------


def page_slug(identifier: str) -> str:
    """The file name stem for a concept page: the id's term.

    The id's term and never the record's, for two reasons that are really
    one. An id's term is already a slug — ``concept:<lowercase, hyphens>``
    is the form :mod:`~s0ma_dsl.docs_model.ids` refuses anything else for
    — so it needs no lossy transliteration, and ids are unique by
    construction, so two pages cannot collide. A term does neither:
    ``.s0ma file``, ``requires:`` and ``canonical IR`` are three of the
    thirty-seven, and slugging them would invent a name a reader could not
    predict and a second concept could land on.
    """
    normalized = normalize_id(identifier)
    try:
        form = validate_id(normalized)
    except DocsIdError as error:
        raise DocsLearnError(str(error)) from None
    if form != "concept":
        raise DocsLearnError(
            f"{identifier} is a {form} id and this collection renders "
            f"concepts. A page named for something that is not a concept "
            f"would be a page nothing in the model answers for."
        )
    return normalized[len(CONCEPT_PREFIX) :]


def page_path(identifier: str) -> str:
    """One concept page's path, relative to the documentation root."""
    return f"{LEARN_DIR}/{page_slug(identifier)}.md"


def relative_to_learn(relative: str, *, docs_root: str = "docs") -> str:
    """``relative`` as a link from a page inside :data:`LEARN_DIR`.

    Repository-relative POSIX in, a link out. Three cases and no fourth:
    a sibling in this collection is a bare file name, a page elsewhere
    under the documentation root is one step up, and anything else is two
    — the collection sits one directory below the documentation root,
    which sits one below the checkout. No machine path can reach a
    rendered link (INV-5).
    """
    inside = f"{docs_root}/{LEARN_DIR}/"
    if relative.startswith(inside):
        return relative[len(inside) :]
    if relative.startswith(f"{docs_root}/"):
        return f"../{relative[len(docs_root) + 1 :]}"
    return f"../../{relative}"


def _docs_link(text: str, relative: str, docs_root: str) -> str:
    """A link to ``relative`` (under the documentation root) with ``text``."""
    return _link(text, relative_to_learn(f"{docs_root}/{relative}", docs_root=docs_root))


def _link(text: str, target: str) -> str:
    """One Markdown link, with the text's own brackets refused.

    A title containing a bracket would end the link text early and leave
    the rest of it as prose beside a broken link — the failure
    ``scripts/check_links.py`` reads as an unresolvable target. Titles
    come from records, so this is a real input, and the honest answer is
    to escape rather than to silently truncate.
    """
    escaped = text.replace("[", "\\[").replace("]", "\\]")
    return f"[{escaped}]({target})"


# ---------------------------------------------------------------------------
# Reading the model
# ---------------------------------------------------------------------------


def _concepts(bundle: DocsBundle) -> tuple[ConceptRecord, ...]:
    """Every concept this build composed, by id."""
    return tuple(sorted(bundle.concepts, key=lambda item: item.id))


def _by_id(bundle: DocsBundle) -> dict[str, ConceptRecord]:
    return {normalize_id(record.id): record for record in bundle.concepts}


def _resolved(
    identifier: str, known: Mapping[str, ConceptRecord], aliases: AliasIndex | None
) -> ConceptRecord:
    """The concept ``identifier`` addresses, through aliases, or refuse.

    Aliases are followed because a related concept may legitimately cite
    the name an idea used to have, and a link to a page that was never
    rendered is a link a reader follows into a 404. What is refused is an
    id nothing answers to: :func:`~s0ma_dsl.docs_model.providers_concepts.check_concept_relations`
    reports that as a finding over the whole corpus, and a renderer that
    guessed past it would put the finding in front of a reader instead.
    """
    normalized = normalize_id(identifier)
    if aliases is not None:
        normalized = normalize_id(aliases.canonical(normalized))
    record = known.get(normalized)
    if record is None:
        raise DocsLearnError(
            f"{identifier} is cited by a concept in this build and no "
            f"concept record answers to it, so no page in this collection "
            f"can be linked to. Either the citation is stale or the "
            f"provider that should emit it did not run."
        )
    return record


def _authorities(bundle: DocsBundle) -> dict[str, AuthorityRef]:
    return {normalize_id(item.id): item for item in bundle.authorities}


def _section_key(section: str) -> tuple[tuple[int, str], ...]:
    """A specification section number, ordered the way it is numbered.

    ``4.12.1`` sorts after ``4.2`` and ``4.4a`` between ``4.4`` and
    ``4.5``. Comparing the strings would put ``4.12`` before ``4.2`` and
    file the three documentation declarations in the middle of the page.
    """
    parts: list[tuple[int, str]] = []
    for piece in section.split("."):
        digits = _LEADING_DIGITS.match(piece).group(0)  # type: ignore[union-attr]
        parts.append((int(digits) if digits else 0, piece[len(digits) :]))
    return tuple(parts)


#: The leading run of digits in one dotted piece of a section number.
#: Always matches, possibly emptily, which is what lets an unnumbered
#: piece sort as zero rather than raise.
_LEADING_DIGITS = re.compile(r"\d*")


def declaration_kinds(bundle: DocsBundle) -> tuple[ConceptRecord, ...]:
    """The declaration kinds a source file may contain, in specification order.

    Derived twice over and written down nowhere. *Which* concepts they are
    is the set that declares :data:`PART_OF` against :data:`FILE_CONCEPT`
    — the authored fact that says a thing is one of the file's parts. The
    *order* is the order the specification numbers the sections that
    define them, read from the authorities each one cites.

    A part that cites no authority with a section number sorts last, by
    id, rather than being dropped: a declaration kind missing from the
    anatomy page is exactly the omission the page exists to make
    impossible, and an unnumbered one is still one of the file's parts.
    """
    authorities = _authorities(bundle)
    parts: list[tuple[tuple[tuple[int, str], ...], str, ConceptRecord]] = []
    for record in _concepts(bundle):
        edges = {tuple(edge) for edge in record.related_concepts}
        if (PART_OF, FILE_CONCEPT) not in edges:
            continue
        sections = [
            authorities[normalize_id(cited)].section
            for cited in record.governed_by
            if normalize_id(cited) in authorities
            and authorities[normalize_id(cited)].section
        ]
        key = min((_section_key(item) for item in sections), default=((999, ""),))
        parts.append((key, record.id, record))
    if not parts:
        raise DocsLearnError(
            f"no concept in this build declares {PART_OF} {FILE_CONCEPT}, so "
            f"the anatomy of a source file would render as an empty list. A "
            f"page that says a file has no parts is worse than no page."
        )
    return tuple(record for _, _, record in sorted(parts, key=lambda item: item[:2]))


def _section_of(record: ConceptRecord, authorities: Mapping[str, AuthorityRef]) -> str:
    """The lowest-numbered section defining ``record``, or nothing."""
    found = sorted(
        (
            _section_key(authorities[normalize_id(cited)].section),
            authorities[normalize_id(cited)].section,
        )
        for cited in record.governed_by
        if normalize_id(cited) in authorities and authorities[normalize_id(cited)].section
    )
    return found[0][1] if found else ""


def _further_reading(document: DocumentRecord, docs_root: str) -> bool:
    """Is ``document`` somewhere a reader of this collection should be sent?

    Two exclusions, both of them about not sending a reader in a circle.

    A document that is not written as Markdown is not further reading: the
    two authored concepts files are catalog rows over ``.json`` sources,
    and they are what these pages were *rendered from* rather than a
    deeper account of the same idea. A reader who followed one would meet
    the same sentences again, in a shape they were not written to be read
    in.

    A document inside this collection is not further reading either, and
    that one is sharper than it looks: every page here gets a catalog row
    that covers the concept it renders, so without this rule
    ``nerve.md``'s own row would put ``nerve.md`` in its own list of
    places to look next the moment the rows land.
    """
    inside = f"{docs_root}/{LEARN_DIR}/"
    if document.canonical_source.startswith(inside):
        return False
    return document.prose_locator.endswith(".md")


def _teaching_documents(
    bundle: DocsBundle, *, docs_root: str
) -> dict[str, list[DocumentRecord]]:
    """For each concept id, the documents that teach it, sorted by title.

    Two ways a document teaches a concept, both facts of the model and
    neither invented here: its catalog row says it ``covers`` the concept,
    or it covers a journey whose ordered teaching names it. The second is
    what puts the first-module guide on ``concept:nerve``'s page — the
    guide's row covers the journey, and the journey teaches the nerve.
    """
    journeys: dict[str, JourneyRecord] = {
        normalize_id(item.id): item for item in bundle.journeys
    }
    found: dict[str, dict[str, DocumentRecord]] = {}
    for document in bundle.documents:
        if not _further_reading(document, docs_root):
            continue
        taught: set[str] = set()
        for covered in document.covers:
            normalized = normalize_id(covered)
            if normalized.startswith(CONCEPT_PREFIX):
                taught.add(normalized)
                continue
            journey = journeys.get(normalized)
            if journey is None:
                continue
            taught.update(normalize_id(item) for item in journey.concepts_taught)
            taught.update(normalize_id(item) for item in journey.concepts_required)
        for concept_id in taught:
            found.setdefault(concept_id, {})[document.id] = document
    return {
        concept_id: sorted(
            documents.values(), key=lambda item: (item.title.casefold(), item.id)
        )
        for concept_id, documents in found.items()
    }


# ---------------------------------------------------------------------------
# One concept page
# ---------------------------------------------------------------------------


def _related_lines(
    value: Sequence[str], known: Mapping[str, ConceptRecord], aliases: AliasIndex | None
) -> list[str]:
    """The typed relations, each one linked to the page it points at."""
    lines: list[str] = []
    for edge in value:
        relation, _, target = edge.partition(" ")
        record = _resolved(target, known, aliases)
        lines.append(f"- {relation} {_link(record.term, f'{page_slug(record.id)}.md')}")
    return lines


def _section_body(
    fact: str,
    value: FactValue,
    known: Mapping[str, ConceptRecord],
    aliases: AliasIndex | None,
) -> list[str]:
    """One section's lines, below its heading."""
    if isinstance(value, str):
        return [value]
    if fact == "syntax":
        return [_OPEN_FENCE, *(value or (EMPTY_MARKER,)), _FENCE]
    if not value:
        return [f"- {EMPTY_MARKER}"]
    if fact == "related_concepts":
        return _related_lines(value, known, aliases)
    if fact in _BACKTICKED:
        return [f"- `{item}`" for item in value]
    return [f"- {item}" for item in value]


def _next_links(
    record: ConceptRecord,
    *,
    kinds: Sequence[ConceptRecord],
    teaching: Mapping[str, Sequence[DocumentRecord]],
    docs_root: str,
) -> list[str]:
    """The neighbours this page offers, in the order a reader meets them.

    Nearest first: the glossary, then the anatomy page where this concept
    is part of a file's anatomy, then the two generated references, then
    every document that teaches this idea. Each one derived — the anatomy
    link from the ``part-of`` edges, the documents from the catalog's own
    ``covers`` — so a page never offers a route the model does not have.
    """
    normalized = normalize_id(record.id)
    part_ids = {normalize_id(item.id) for item in kinds}
    links = [f"- {_link(GLOSSARY_TITLE, 'glossary.md')}"]
    if normalized in part_ids or normalized == normalize_id(FILE_CONCEPT):
        links.append(f"- {_docs_link(ANATOMY_TITLE, ANATOMY_OUTPUT, docs_root)}")
    links.extend(
        f"- {_docs_link(text, relative, docs_root)}"
        for relative, text in REFERENCE_LINKS
    )
    links.extend(
        f"- {_link(item.title, relative_to_learn(item.canonical_source, docs_root=docs_root))}"
        for item in teaching.get(normalized, ())
    )
    return links


def _identity_block(view: TopicView, footer: Sequence[str]) -> list[str]:
    """The identity bullets at the foot of a page, in their frozen order."""
    lines: list[str] = []
    for fact in footer:
        value = view.value(fact)
        written = ", ".join(value) if isinstance(value, tuple) else value
        lines.append(f"- {_FOOTER[fact]}: `{written or EMPTY_MARKER}`")
    return lines


def concept_page(
    bundle: DocsBundle,
    record: ConceptRecord,
    *,
    aliases: AliasIndex | None = None,
    spec: PresentationSpec | None = None,
    docs_root: str = "docs",
) -> str:
    """One concept as a page in the learning collection.

    C7's page, written for a file: the same title, the same sections in
    the same order, the same rule that a section whose fact is empty is
    left out unless the fact is identity — and then the generated-page
    sentence under the title and the block of links at the foot.
    """
    declared = spec if spec is not None else spec_for_concept()
    view = facts_of(bundle, record)
    declared.check(view)
    known = _by_id(bundle)
    kinds = declaration_kinds(bundle)
    teaching = _teaching_documents(bundle, docs_root=docs_root)

    lines: list[str] = []
    footer: list[str] = []
    for fact in declared.order:
        label = declared.label_of(fact)
        value = view.value(fact)
        if label.startswith("- "):
            footer.append(fact)
        elif label.startswith("# "):
            lines.extend([f"# {value}", "", GENERATED_NOTE, ""])
        elif _is_empty(value) and fact not in IDENTITY_FACTS:
            continue
        else:
            lines.extend([label, "", *_section_body(fact, value, known, aliases), ""])
    lines.extend(
        [
            NEXT_HEADING,
            "",
            *_next_links(record, kinds=kinds, teaching=teaching, docs_root=docs_root),
            "",
            _RULE,
            "",
            IDENTITY_HEADING,
            "",
            *_identity_block(view, footer),
        ]
    )
    return "\n".join(lines) + "\n"


def _is_empty(value: FactValue) -> bool:
    return not value if isinstance(value, tuple) else not value.strip()


# ---------------------------------------------------------------------------
# The glossary
# ---------------------------------------------------------------------------


def _collection_identity(bundle: DocsBundle) -> list[str]:
    """A collection page's identity block: which build it describes.

    The version is written the way
    :func:`~s0ma_dsl.docs_model.resolve.facts_of` writes it for a topic
    page — :meth:`~s0ma_dsl.docs_model.records.BuildStamp.version_line`,
    so a preview build says so here too (H1, architecture §13.2). A
    collection page is not a topic and has no
    :class:`~s0ma_dsl.docs_model.resolve.TopicView` to read the fact off,
    which is exactly how the glossary and the anatomy page came to be the
    only two rendered pages that could have carried the version unlabelled.
    """
    values = {
        "release_version": bundle.stamp.version_line(),
        "snapshot_hash": bundle.stamp.snapshot_hash,
    }
    return [
        _RULE,
        "",
        IDENTITY_HEADING,
        "",
        *(f"- {_FOOTER[fact]}: `{values[fact] or EMPTY_MARKER}`" for fact in _COLLECTION_FOOTER),
    ]


def glossary_page(
    bundle: DocsBundle,
    *,
    aliases: AliasIndex | None = None,
    docs_root: str = "docs",
) -> str:
    """Every concept in one table, with the alternate names under it.

    The audit's missing-public-glossary gap closes here. Two tables: every
    concept with its short form and a link to its page, then every
    alternate name with the page it resolves onto. Both counts are
    computed; neither is written down.

    Sorted by term rather than by id, because a glossary is looked up by
    the word a reader has in mind, and case-folded so ``.s0ma file`` and
    ``canonical IR`` file where a reader would look for them.
    """
    records = sorted(bundle.concepts, key=lambda item: (item.term.casefold(), item.id))
    known = _by_id(bundle)
    entries = tuple(aliases.entries) if aliases is not None else ()

    lines = [
        f"# {GLOSSARY_TITLE}",
        "",
        GENERATED_NOTE,
        "",
        f"s0ma's vocabulary is {len(records)} ideas. Each row gives the short "
        f"form; the term links to the whole entry — what it is, why it "
        f"exists, when to reach for it and when not to.",
        "",
        "| Term | Id | In short |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {_link(cell(item.term), f'{page_slug(item.id)}.md')} "
        f"| `{cell(item.id)}` | {cell(item.summary)} |"
        for item in records
    )
    lines.extend(["", GLOSSARY_ALIASES_HEADING, ""])
    if entries:
        lines.extend(
            [
                f"{len(entries)} other names resolve onto one of the terms "
                f"above. Every one of them can be asked for by name and "
                f"answers with the entry it points at.",
                "",
                "| Also called | See |",
                "| --- | --- |",
            ]
        )
        for old, new in entries:
            target = _resolved(new, known, aliases)
            lines.append(
                f"| `{cell(old)}` "
                f"| {_link(cell(target.term), f'{page_slug(target.id)}.md')} |"
            )
    else:
        lines.append(
            "No alternate name is declared in this build. Every idea above is "
            "addressed by one name only."
        )
    lines.extend(
        [
            "",
            NEXT_HEADING,
            "",
            f"- {_docs_link(ANATOMY_TITLE, ANATOMY_OUTPUT, docs_root)}",
            *(
                f"- {_docs_link(text, relative, docs_root)}"
                for relative, text in REFERENCE_LINKS
            ),
            "",
            *_collection_identity(bundle),
        ]
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# The anatomy
# ---------------------------------------------------------------------------


def anatomy_page(bundle: DocsBundle, *, docs_root: str = "docs") -> str:
    """What a source file is made of, as a reference rather than a walk.

    Every word of prose on this page is a concept record's, reproduced
    verbatim: the file's own summary, definition and purpose, then each of
    its parts with that part's summary and the section that defines it.
    The written forms are the concepts' ``syntax`` fields, unedited, and
    the smallest complete file is two of them — the module header, then
    the written form of the first declaration kind the first-module
    journey teaches, which is a fact of that journey and not a preference
    of this module.

    It complements the first-module guide rather than repeating it. The
    guide walks somebody through writing one; this page says what the
    parts are and where each is defined, and closes by pointing at the
    walk.
    """
    known = _by_id(bundle)
    anchor = known.get(normalize_id(FILE_CONCEPT))
    if anchor is None:
        raise DocsLearnError(
            f"{FILE_CONCEPT} is not a concept this build composed, so there "
            f"is no account of what a source file is to render an anatomy "
            f"from. The page would be headings over nothing."
        )
    kinds = declaration_kinds(bundle)
    authorities = _authorities(bundle)
    header, first = _exemplar(bundle, kinds, known)
    teaching = _teaching_documents(bundle, docs_root=docs_root)

    lines = [
        f"# {ANATOMY_TITLE}",
        "",
        GENERATED_NOTE,
        "",
        ANATOMY_SECTIONS[0],
        "",
        anchor.summary,
        "",
        ANATOMY_SECTIONS[1],
        "",
        anchor.plain_definition,
        "",
        ANATOMY_SECTIONS[2],
        "",
        anchor.purpose,
        "",
        ANATOMY_SECTIONS[3],
        "",
        _OPEN_FENCE,
        *(anchor.syntax or (EMPTY_MARKER,)),
        _FENCE,
        "",
        ANATOMY_SECTIONS[4],
        "",
        f"A file may contain {len(kinds)} kinds of declaration. They are "
        f"listed here in the order the specification defines them, each with "
        f"the section that defines it and a link to its whole entry.",
        "",
    ]
    for record in kinds:
        section = _section_of(record, authorities)
        lines.extend(
            [
                f"### {record.term}",
                "",
                record.summary,
                "",
                f"- Whole entry: {_link(record.term, f'{page_slug(record.id)}.md')}",
                f"- Defined in: `{_defining_source(record, authorities)}`"
                + (f", section `{section}`" if section else ""),
                "",
                _OPEN_FENCE,
                *(record.syntax or (EMPTY_MARKER,)),
                _FENCE,
                "",
            ]
        )
    lines.extend(
        [
            ANATOMY_SECTIONS[5],
            "",
            f"A header and one declaration. Both written forms below are the "
            f"ones {header.term} and {first.term} carry above, unedited.",
            "",
            _OPEN_FENCE,
            *header.syntax,
            "",
            *first.syntax,
            _FENCE,
            "",
            NEXT_HEADING,
            "",
            *_anatomy_links(bundle, teaching, docs_root=docs_root),
            "",
            *_collection_identity(bundle),
        ]
    )
    return "\n".join(lines) + "\n"


def _defining_source(
    record: ConceptRecord, authorities: Mapping[str, AuthorityRef]
) -> str:
    """The document that defines ``record``, or a stated absence."""
    found = sorted(
        {
            authorities[normalize_id(cited)].source
            for cited in record.governed_by
            if normalize_id(cited) in authorities
        }
    )
    return found[0] if found else EMPTY_MARKER


def _exemplar(
    bundle: DocsBundle,
    kinds: Sequence[ConceptRecord],
    known: Mapping[str, ConceptRecord],
) -> tuple[ConceptRecord, ConceptRecord]:
    """The two written forms the smallest complete file is made of.

    The header is the concept every file opens with — the one part whose
    id the file concept itself ``requires``. The declaration is the first
    of the eleven that the first-module journey teaches: a fact of that
    journey's ordered teaching, so the exemplar on this page and the
    declaration the guide writes first are the same one by construction.

    Where no journey teaches any of them, the first in specification order
    stands in, because a page that showed a header and nothing under it
    would not be a complete file.
    """
    parts = {normalize_id(item.id): item for item in kinds}
    anchor = known[normalize_id(FILE_CONCEPT)]
    required = [
        normalize_id(target)
        for relation, target in (tuple(edge) for edge in anchor.related_concepts)
        if relation == "requires" and normalize_id(target) in parts
    ]
    if not required:
        raise DocsLearnError(
            f"{FILE_CONCEPT} requires none of the {len(parts)} declaration "
            f"kinds, so this page cannot say which part a file opens with. "
            f"The header is the one part a file cannot be written without."
        )
    header = parts[required[0]]
    taught: list[str] = []
    for journey in sorted(bundle.journeys, key=lambda item: item.id):
        if normalize_id(journey.id) != normalize_id(_FIRST_MODULE):
            continue
        taught = [normalize_id(item) for item in journey.concepts_taught]
    ordered = [item for item in taught if item in parts and item != normalize_id(header.id)]
    if ordered:
        return header, parts[ordered[0]]
    rest = [item for item in kinds if normalize_id(item.id) != normalize_id(header.id)]
    if not rest:
        raise DocsLearnError(
            "a file's anatomy has a header and no other part, so no complete "
            "file can be shown. A header alone declares nothing."
        )
    return header, rest[0]


#: The journey whose teaching order chooses the exemplar declaration, and
#: whose guide this page closes by pointing at (plan §11 F5).
_FIRST_MODULE = "journey:first-module"


def _anatomy_links(
    bundle: DocsBundle,
    teaching: Mapping[str, Sequence[DocumentRecord]],
    *,
    docs_root: str,
) -> list[str]:
    """The walk, the glossary and the references, in that order.

    The walk first and by name: this page is the reference shape of what
    the first-module guide teaches by doing, and a reader who wants to be
    walked through it should not have to find that out at the bottom of a
    list. The guide is found through the catalog — the document whose row
    covers :data:`_FIRST_MODULE` — rather than by its path, so moving the
    guide moves the link.
    """
    guides = [
        document
        for document in sorted(bundle.documents, key=lambda item: item.id)
        if normalize_id(_FIRST_MODULE) in {normalize_id(item) for item in document.covers}
    ]
    if not guides:
        raise DocsLearnError(
            f"no document in this build covers {_FIRST_MODULE}, so this page "
            f"cannot point at the walk it is the reference for. The anatomy "
            f"and the journey are two halves of one answer."
        )
    links = [
        f"- {_link(item.title, relative_to_learn(item.canonical_source, docs_root=docs_root))}"
        for item in guides
    ]
    links.append(f"- {_link(GLOSSARY_TITLE, 'glossary.md')}")
    links.extend(
        f"- {_docs_link(text, relative, docs_root)}"
        for relative, text in REFERENCE_LINKS
    )
    return links


# ---------------------------------------------------------------------------
# The collection
# ---------------------------------------------------------------------------


def learn_pages(
    bundle: DocsBundle,
    *,
    aliases: AliasIndex | None = None,
    docs_root: str = "docs",
) -> dict[str, str]:
    """Every page of the learning collection: path relative to ``docs/``, content.

    One entry per concept, plus the glossary and the anatomy. Returned as
    a mapping rather than written, for the reason every other renderer in
    this application returns a string: the one function that knows about
    files is :func:`~s0ma_dsl.docs_model.application.write`, and a
    renderer that wrote would be a renderer a check gate could not run
    without touching the tree.

    A collision between two pages is refused rather than resolved. Ids are
    unique and slugs are derived from ids, so this cannot happen through
    the concepts alone — what it catches is a concept whose term collided
    with a collection page's name, which is a real authoring mistake and
    would silently overwrite the glossary.
    """
    pages: dict[str, str] = {}
    reserved = {GLOSSARY_OUTPUT: GLOSSARY_TITLE, ANATOMY_OUTPUT: ANATOMY_TITLE}
    for record in _concepts(bundle):
        relative = page_path(record.id)
        if relative in reserved:
            raise DocsLearnError(
                f"{record.id} renders to {relative}, which is this "
                f"collection's {reserved[relative]}. Two pages at one path "
                f"means one of them is not written; rename the concept."
            )
        if relative in pages:
            raise DocsLearnError(
                f"two concepts render to {relative}. A page can only carry "
                f"one of them, and which one would depend on the order the "
                f"records happened to arrive in."
            )
        pages[relative] = concept_page(
            bundle, record, aliases=aliases, docs_root=docs_root
        )
    pages[GLOSSARY_OUTPUT] = glossary_page(bundle, aliases=aliases, docs_root=docs_root)
    pages[ANATOMY_OUTPUT] = anatomy_page(bundle, docs_root=docs_root)
    return dict(sorted(pages.items()))


def learn_outputs(bundle: DocsBundle) -> tuple[str, ...]:
    """Every path this collection declares, sorted, relative to ``docs/``.

    The declared-output set for this collection, computed from the bundle
    rather than written down. The application's own
    :data:`~s0ma_dsl.docs_model.application.STATIC_OUTPUTS` is a fixed
    tuple because its artifacts are decisions; these are not —
    which concepts exist is authored elsewhere, so a fixed list of
    thirty-nine paths would be an independently maintained inventory of
    exactly the kind architecture §8.2 forbids, and a thirty-eighth
    concept would ship with no page until somebody remembered to edit it.
    :func:`~s0ma_dsl.docs_model.application.generated_outputs` is the two
    halves together, and it is what the build writes and compares.

    Derived from the same walk :func:`learn_pages` makes, so the two
    cannot disagree about what the collection contains.
    """
    return tuple(
        sorted(
            [
                *(page_path(record.id) for record in _concepts(bundle)),
                GLOSSARY_OUTPUT,
                ANATOMY_OUTPUT,
            ]
        )
    )


def stale_pages(present: Iterable[str], bundle: DocsBundle) -> tuple[str, ...]:
    """Committed pages in this collection that this build does not render.

    The half a declared-output set cannot cover on its own. Writing and
    comparing both walk what the build *produces*, so a page left behind
    by a concept somebody deleted is a file no gate ever looks at: it
    stays in the tree, stays linked from nowhere, and goes stale silently
    — which is the exact failure the August 2026 audit named as *the
    orphaned docs are the stale docs*.

    ``present`` is the set of paths found under the collection, relative
    to the documentation root, and it arrives from the caller for the
    reason every floor and every renderer in this application does: a gate
    that enumerated its own subject could satisfy itself.
    """
    rendered = set(learn_outputs(bundle))
    return tuple(
        sorted(
            relative
            for relative in present
            if relative.startswith(f"{LEARN_DIR}/") and relative not in rendered
        )
    )


def catalog_rows(bundle: DocsBundle, *, docs_root: str = "docs") -> tuple[dict[str, object], ...]:
    """The catalog row every page of this collection needs, computed.

    The completeness gate
    (:func:`~s0ma_dsl.docs_model.providers_catalog.check_completeness`)
    asks the catalog about every tracked Markdown file, and a page with no
    row is ``DOC_DOCUMENT_UNCATALOGED``. Thirty-nine rows is more than
    anybody should hand-write and exactly the kind of independently
    authored inventory architecture §8.2 forbids, so they are computed
    here and the authored catalog is asserted equal to them.

    Rows only — this function writes nothing and knows nothing about where
    the catalog file is. What the caller does with them is the wiring
    decision, and it is recorded in this milestone's note.

    **A page's title is not its concept's term** (:data:`PAGE_TITLE`), and
    that is a decision rather than decoration. A page's H1 is the bare
    term, which is right for somebody who has just opened the file; a
    *catalog title* is the name the whole model knows this document by, and
    a document named exactly ``nerve`` is a second thing in the composed
    model called what ``concept:nerve`` is called.
    :func:`~s0ma_dsl.docs_model.resolve.resolve` refuses to choose between
    two candidates of one match class — deliberately, because "several
    things are equally called what you asked for" is the reader's question
    to answer — so titling these rows with the bare term would have made
    ``s0ma docs show nerve`` ambiguous for every concept in the build, and
    the ambiguity would have been between a concept and the page about that
    concept. Suffixing the title keeps the collection sorted by term
    wherever titles are sorted, and leaves the concept the only exact
    name-match for its own name.
    """
    rows: list[dict[str, object]] = []
    for record in _concepts(bundle):
        rows.append(
            {
                "audiences": ["agent", "user"],
                "authority": "",
                "canonical_source": f"{docs_root}/{page_path(record.id)}",
                "covers": [record.id],
                "governed_by": [],
                "id": f"doc:generated/learn-{page_slug(record.id)}",
                "kind": "guide",
                "prose_locator": f"{docs_root}/{page_path(record.id)}",
                "status": "generated",
                "title": PAGE_TITLE.format(term=record.term),
            }
        )
    rows.append(
        {
            "audiences": ["agent", "user"],
            "authority": "",
            "canonical_source": f"{docs_root}/{GLOSSARY_OUTPUT}",
            "covers": sorted(record.id for record in _concepts(bundle)),
            "governed_by": [],
            "id": "doc:generated/learn-glossary",
            "kind": "reference",
            "prose_locator": f"{docs_root}/{GLOSSARY_OUTPUT}",
            "status": "generated",
            "title": GLOSSARY_TITLE,
        }
    )
    rows.append(
        {
            "audiences": ["agent", "user"],
            "authority": "",
            "canonical_source": f"{docs_root}/{ANATOMY_OUTPUT}",
            # Sorted, like every id list in the catalog: the file's reader
            # refuses an unsorted one, because two readings of an unsorted
            # list are not byte-identical.
            "covers": sorted(
                {FILE_CONCEPT, *(item.id for item in declaration_kinds(bundle))}
            ),
            "governed_by": [],
            "id": "doc:generated/learn-anatomy",
            "kind": "guide",
            "prose_locator": f"{docs_root}/{ANATOMY_OUTPUT}",
            "status": "generated",
            "title": ANATOMY_TITLE,
        }
    )
    return tuple(sorted(rows, key=lambda item: str(item["id"])))


# ---------------------------------------------------------------------------
# Reading a page back (B5 clause 2)
# ---------------------------------------------------------------------------


def _sections(text: str) -> dict[str, list[str]]:
    """Every heading in the page, with the lines under it.

    C7's reading, for C7's reasons: fence-aware, because a written form
    may legitimately contain a line beginning with a hash, and the rule
    ends the section above it so the envelope's own lines are never read
    as somebody's prose.
    """
    found: dict[str, list[str]] = {}
    current = ""
    fenced = False
    for line in text.split("\n"):
        if line.strip().startswith(_FENCE):
            fenced = not fenced
        elif not fenced:
            if line.strip() == _RULE:
                current = ""
                continue
            match = _HEADING_LINE.match(line)
            if match is not None:
                current = f"{match.group(1)} {match.group(2)}"
                found[current] = []
                continue
        if current:
            found[current].append(line)
    return found


def _read_body(fact: str, lines: list[str]) -> FactValue:
    """One section's lines back into the fact they carry."""
    body = [line for line in lines if line.strip() and line != GENERATED_NOTE]
    if fact not in LIST_FACTS:
        return " ".join(body)
    if fact == "syntax":
        inside = [line for line in lines if not line.strip().startswith(_FENCE)]
        while inside and not inside[0].strip():
            inside.pop(0)
        while inside and not inside[-1].strip():
            inside.pop()
        return () if inside == [EMPTY_MARKER] else tuple(inside)
    if body == [f"- {EMPTY_MARKER}"]:
        return ()
    items = [line[2:] for line in body if line.startswith("- ")]
    if fact == "related_concepts":
        read: list[str] = []
        for item in items:
            matched = _RELATED_ITEM.match(item)
            if matched is None:
                read.append(item)
                continue
            read.append(
                f"{matched.group('relation')} {CONCEPT_PREFIX}{matched.group('slug')}"
            )
        return tuple(read)
    if fact not in _BACKTICKED:
        return tuple(items)
    unwrapped: list[str] = []
    for item in items:
        matched = _BACKTICKED_ITEM.match(item)
        unwrapped.append(matched.group(1) if matched is not None else item)
    return tuple(unwrapped)


def extract(text: str, spec: PresentationSpec) -> dict[str, FactValue]:
    """Read the facts back out of a rendered concept page, declaration in hand.

    C7's :func:`~s0ma_dsl.docs_model.render_human.extract`, with this
    channel's two differences: the generated-page sentence sits under the
    title and is not part of any fact, and a related concept is read back
    out of its link. Only the declaration is used, so an edit to an
    already-rendered page changes what this returns — which is what makes
    the residue proof a proof rather than a renderer agreeing with itself.
    """
    sections = _sections(text)
    footer_lines = sections.get(IDENTITY_HEADING, [])
    title_heading = next((key for key in sections if key.startswith("# ")), None)
    found: dict[str, FactValue] = {}
    for fact in spec.order:
        label = spec.label_of(fact)
        if label.startswith("# "):
            if title_heading is not None:
                found[fact] = title_heading[2:]
        elif label.startswith("- "):
            for line in footer_lines:
                match = _FOOTER_LINE.match(line)
                if match is not None and match.group(1) == label[2:]:
                    written = match.group(2)
                    found[fact] = "" if written == EMPTY_MARKER else written
        elif label in sections:
            found[fact] = _read_body(fact, sections[label])
    return found


def undeclared_headings(text: str, spec: PresentationSpec) -> tuple[str, ...]:
    """Headings on the page that no declaration accounts for.

    B5 clause 1's enforcement for this channel. The residue can only
    compare facts that are there; this is what sees a section somebody
    added that no fact backs.
    """
    declared = {NEXT_HEADING, IDENTITY_HEADING}
    titled = False
    for fact in spec.order:
        label = spec.label_of(fact)
        if label.startswith("# "):
            titled = True
        elif label.startswith("## "):
            declared.add(label)
    return tuple(
        sorted(
            heading
            for heading in _sections(text)
            if heading not in declared and not (titled and heading.startswith("# "))
        )
    )


#: What C7's concept sections are, restated as a set for the proof that
#: this channel presents exactly them. Imported rather than listed, so a
#: section added there is a failing assertion here rather than a page that
#: quietly stopped carrying a fact.
CONCEPT_SECTIONS: tuple[str, ...] = SECTION_FACTS["concepts"]
