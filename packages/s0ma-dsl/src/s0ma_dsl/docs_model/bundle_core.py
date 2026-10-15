"""The core teaching slice: what s0ma-core can honestly teach, on its own.

Milestone F8 of the docs-function plan (internal) §11, owner decision D-9.

**The defect this closes.** ``s0ma.api.teaching`` mapped a dozen topic
keywords onto section headings of a Markdown user guide it located by
walking up from its own ``__file__``. No wheel has ever contained that
guide — ``packages = ["src/s0ma"]`` ships the package and nothing beside
it — so every pip-installed core answered every teaching question with
"Documentation files are not available in this installation." The
framework whose whole claim is that software should carry an accurate
model of itself shipped unable to say what it was.

**The rule D-9 sets.** Core's teaching content ships *inside* the wheel,
is *generated* rather than hand-copied, and creates **no upward
dependency**: nothing in s0ma-core may import s0ma-dsl, s0ma-mcp or
s0ma-studi0 to read it. So this module renders a self-contained JSON
document — plain objects, arrays, strings and numbers — that the standard
library alone can read, and core reads it with :mod:`json` and nothing
else. The direction of knowledge is preserved: the documentation
application knows about core, core knows about a file.

**What is selected, and why each rule is the honest one.**

*Every concept the build composed, without exception.* A language concept
is not a fact about which packages you installed — a nerve is a nerve
whether or not the transpiler that reads one is on this machine — so
trimming the concepts to "the ones core implements" would teach a reader
a smaller product than the one they are using. The concepts are the half
of this corpus that is *product-wide knowledge*, and all of it travels.
The count is not written down here or anywhere in the file: it is
computed from what was selected, so a concept authored tomorrow ships
without anybody remembering this module.

*Core's own served capabilities, and only those.* A surface is a claim
that something answers when you call it, so a slice that listed the
authoring CLI would be telling a core-only installation about commands it
does not have. The selection is by provenance —
:data:`~s0ma_dsl.docs_model.providers_core.PROVIDER_ID` is stamped on
every record :class:`~s0ma_dsl.docs_model.providers_core.CoreProvider`
emits — rather than by a list of channel words, because a list would go
stale the day core grows a channel and nothing would notice.

*Journeys as pointers, with their availability computed.* Every journey
in this corpus walks the authoring toolchain; not one of their steps is a
core surface. :func:`_availability` counts that rather than asserting it,
so a journey that becomes walkable on core alone starts saying so by
itself, and the reader is told what an installed core can and cannot do
instead of being handed steps that name commands it lacks.

**The legacy vocabulary lives here.** :data:`LEGACY_KEYWORDS` is the
twelve keyword groups core's old ``_TOPIC_TO_HEADING`` table mapped onto
guide headings, re-pointed at the topic ids that answer them now. It sits
in the generator rather than in core for one reason: here every target is
checked against the composed bundle, so a concept somebody renames breaks
the documentation build with a named finding. In core it would be twelve
strings nothing checks, which is precisely the arrangement that rotted.

**The channel's presentation is declared, and most of it is borrowed.**
Section headings come from C7's human channel
(:func:`~s0ma_dsl.docs_model.render_human.spec_for`), so the wording a
reader meets in ``learn_about_s0ma`` is the wording on the same topic's
page — one opinion, in one place. The strings this module adds itself are
enumerated in :data:`ENVELOPE`; nothing else here writes a sentence, and
every fact travels verbatim from the record that carries it.

**Identity.** ``release_version`` and ``snapshot_hash`` are written once,
under ``source``, and on no topic — the
:data:`~s0ma_dsl.docs_model.records.BUILD_STAMP_ONLY_FIELDS` rule said
about an artifact. Every topic carries its id, its authority references
and its example ids, so the identity core of B5's residue rule survives
the trip into core.

**Determinism.** No clock, no network, no machine path, no filesystem.
Every collection is sorted before it reaches the document, every count is
computed from what was selected, and the text is
:func:`~s0ma_dsl.docs_model.serialize.canonical_json` — UTF-8, sorted
keys, one trailing line feed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.inventories import CHANNEL_TITLES
from s0ma_dsl.docs_model.providers_core import PROVIDER_ID as CORE_PROVIDER_ID
from s0ma_dsl.docs_model.records import DocsModelError
from s0ma_dsl.docs_model.render_human import SECTION_FACTS, TITLE_FACT
from s0ma_dsl.docs_model.render_human import spec_for as human_spec_for
from s0ma_dsl.docs_model.resolve import facts_of
from s0ma_dsl.docs_model.serialize import canonical_json

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from s0ma_dsl.docs_model.ids import AliasIndex
    from s0ma_dsl.docs_model.records import (
        ConceptRecord,
        DocsBundle,
        DocumentRecord,
        JourneyRecord,
        SurfaceRecord,
    )

__all__ = [
    "ALL_INDEX",
    "CONCEPTS_INDEX",
    "CORE_TEACHING_SCHEMA",
    "ENVELOPE",
    "INDEX_PREFIX",
    "JOURNEYS_INDEX",
    "LEGACY_KEYWORDS",
    "LINES_NAMES",
    "LINES_SUMMARIES",
    "LIVE_EXAMPLE_TOPICS",
    "SURFACES_INDEX",
    "DocsCoreSliceError",
    "core_surfaces",
    "core_teaching_slice",
]


class DocsCoreSliceError(DocsModelError):
    """The composed bundle cannot back an honest core teaching slice."""


#: The slice's own format version. Not the model's ``s0ma-docs-model@1``:
#: this is a *rendering* of a snapshot for one reader, and the two version
#: independently — exactly the distinction
#: :data:`~s0ma_dsl.docs_model.inventories.INVENTORY_SCHEMA` draws for the
#: same reason. Core validates this string before it trusts a byte of the
#: file, so a slice from a future shape is refused rather than
#: half-understood.
CORE_TEACHING_SCHEMA = "s0ma-core-teaching@1"

#: The prefix the slice's own navigation entries are addressed by. Not a
#: form in :data:`~s0ma_dsl.docs_model.ids.ID_FORMS`, and deliberately so:
#: an index is a fact about *this document* — which topics it happens to
#: carry — and not a record anything in the model resolves against. The
#: prefix is unused by every model form, so nothing can collide.
INDEX_PREFIX = "index:"

ALL_INDEX = f"{INDEX_PREFIX}all"
CONCEPTS_INDEX = f"{INDEX_PREFIX}concepts"
SURFACES_INDEX = f"{INDEX_PREFIX}surfaces"
JOURNEYS_INDEX = f"{INDEX_PREFIX}journeys"

#: How long a line an index writes per entry. A navigation entry declares
#: this rather than leaving its reader to guess from the shape, because the
#: choice is about *this* list — how many entries it holds and whether
#: somebody arrived at it on purpose — and a reader inferring it from the
#: number of groups would get it wrong the day a group is added.
LINES_NAMES = "names"
LINES_SUMMARIES = "summaries"

#: Every string this module contributes that is not a fact of a record and
#: not a heading borrowed from the human channel. B5 clause 1 as applied to
#: a data file: anything in front of a reader that is neither declared
#: presentation nor the carrier of a declared fact is a violation, so the
#: presentation is enumerated and a test reads this constant back.
#:
#: The four index titles and summaries are the navigation a reader arrives
#: at. The two availability sentences are the honest answer to "can I walk
#: this here" — which one is written is *computed*, never chosen.
ENVELOPE: Mapping[str, str] = {
    "index-all-title": "What s0ma can teach you here",
    "index-all-summary": (
        "Every topic this installation carries, grouped: the ideas the "
        "product is built out of, what this package serves, and the guided "
        "paths that walk the whole toolchain."
    ),
    "index-concepts-title": "The ideas, defined",
    "index-concepts-summary": (
        "Every idea s0ma is built out of, with a one-line definition. Ask "
        "for any term by name to read the whole entry."
    ),
    "index-surfaces-title": "What this package serves",
    "index-surfaces-summary": (
        "Every capability s0ma-core answers to, grouped by where it is "
        "served. Ask for one by name to read what it does and what it "
        "changes."
    ),
    "index-journeys-title": "The guided paths",
    "index-journeys-summary": (
        "Ordered walks through the product, from a first project to "
        "recovering a refused build. Each one names the ideas it teaches "
        "along the way."
    ),
    "availability-none": (
        "Every step of this path is taken with the full s0ma toolchain, "
        "which this package does not include on its own. The ideas it "
        "teaches are all here — ask for any of them by name — and the steps "
        "themselves are waiting once the toolchain is installed."
    ),
    "availability-partial": (
        "Some steps of this path are taken with capabilities this package "
        "serves and the rest with the full s0ma toolchain. The ideas it "
        "teaches are all here, whichever you have installed."
    ),
}

#: Core's twelve pre-slice topic keyword groups, re-pointed at the ids that
#: answer them now. The keys are exactly the words
#: ``s0ma.api.teaching._TOPIC_TO_HEADING`` matched on before this
#: milestone, so every question that used to be answerable still is — with
#: current content instead of a heading of a guide the wheel never had.
#:
#: A few are re-pointed at a *capability* rather than an idea, because that
#: is the honest current answer: somebody asking about "setup" wants the
#: function they call, and core serves it. The mapping is per keyword
#: rather than per group so that each word lands where it actually belongs
#: — "verify" is a thing you run and "verification" is a thing you write,
#: and the old table could not tell them apart.
#:
#: Every value is checked against the selected topics when the slice is
#: rendered: a keyword pointing at a topic this build did not select is
#: refused, so a rename shows up here as a red documentation build rather
#: than in a user's terminal as an empty answer.
LEGACY_KEYWORDS: Mapping[str, str] = {
    # "Section 1: Project Setup"
    "setup": "python:s0ma.initialize",
    "initialize": "python:s0ma.initialize",
    "install": "python:s0ma.initialize",
    "init": "python:s0ma.initialize",
    "getting started": "python:s0ma.initialize",
    # "Section 2: Creating Components"
    "creating": "concept:s0ma-file",
    "component": "concept:nerve",
    "decorator": "concept:nerve",
    "@component": "concept:nerve",
    # "Section 3: Modifying Components"
    "modifying": "concept:check-and-build-loop",
    "modify": "concept:check-and-build-loop",
    "changing": "concept:check-and-build-loop",
    "change": "concept:check-and-build-loop",
    # "Section 4: Removing Components"
    "removing": "concept:drift-gate",
    "remove": "concept:drift-gate",
    "deleting": "concept:drift-gate",
    "delete": "concept:drift-gate",
    "deletion": "concept:drift-gate",
    # "Section 5: Querying the Self-Model"
    "querying": "concept:self-model",
    "query": "concept:self-model",
    "self-model": "concept:self-model",
    "selfmodel": "concept:self-model",
    "api": "concept:self-model",
    # "Section 6: Understanding Anomaly Reports"
    "anomalies": "concept:drift",
    "anomaly": "concept:drift",
    "report": "concept:drift",
    "verification": "concept:test",
    "verify": "python:s0ma.verify",
    "health": "mcp:tool/check_health",
    # "Section 7: Best Practices"
    "best": "concept:authored-vs-generated-boundary",
    "practices": "concept:authored-vs-generated-boundary",
    "best practices": "concept:authored-vs-generated-boundary",
    # "Section 8: Troubleshooting"
    "troubleshooting": "concept:drift-gate",
    "errors": "concept:drift-gate",
    "error": "concept:drift-gate",
    "debug": "concept:drift-gate",
    "fix": "mcp:tool/suggest_fix",
    # "Appendix A: Glossary"
    "glossary": CONCEPTS_INDEX,
    "terms": CONCEPTS_INDEX,
    "definitions": CONCEPTS_INDEX,
    # "Appendix B: Python API Reference"
    "reference": SURFACES_INDEX,
    "api reference": SURFACES_INDEX,
    # "Appendix C: Compliance Rules"
    "compliance": "concept:strictness-mode",
    "rules": "concept:strictness-mode",
    "rule": "concept:strictness-mode",
    # "C.11 Summary: Quick Compliance Checklist"
    "checklist": "concept:check-and-build-loop",
    "pre-flight": "concept:check-and-build-loop",
    "preflight": "concept:check-and-build-loop",
}

#: The topics a live component template is worth showing beside.
#:
#: The old ``learn_topic`` appended a real registered component, formatted
#: as a copyable declaration, whenever the matched heading mentioned
#: creating or components. That was the most useful half of the old
#: behaviour — a template read off the running registry is current by
#: construction — and it is kept, aimed at ids instead of at a substring of
#: a heading. Core reads this list; it does not decide it, so the same
#: topic shows the same thing on every channel that grows one.
LIVE_EXAMPLE_TOPICS: tuple[str, ...] = (
    "concept:cell",
    "concept:nerve",
    "concept:s0ma-file",
)


def core_surfaces(bundle: DocsBundle) -> tuple[SurfaceRecord, ...]:
    """Every capability s0ma-core itself serves, sorted by id.

    By provenance rather than by channel: ``CoreProvider`` stamps its
    adapter id on every record it emits, and asking that question keeps
    the answer right through a channel core grows tomorrow. The REST
    routes, core's own MCP tools and resources, and the module-level
    Python exports all come back; the authoring CLI, the authoring MCP
    server, the viewer, the diagnostics and the configuration keys do
    not, because a core-only installation does not serve them.
    """
    return tuple(
        sorted(
            (
                record
                for record in bundle.surfaces
                if record.provenance.adapter_id == CORE_PROVIDER_ID
            ),
            key=lambda record: record.id,
        )
    )


def _headings(group: str) -> dict[str, str]:
    """The human channel's section heading for each fact of ``group``.

    Borrowed rather than restated: ``spec_for`` labels a section ``"## In
    short"`` and this strips the level, so the words a reader meets here
    are the words on that topic's page and there is one place to change
    them.
    """
    spec = human_spec_for(group)
    return {
        fact: spec.label_of(fact).removeprefix("## ").strip()
        for fact in SECTION_FACTS[group]
    }


def _sections(
    bundle: DocsBundle,
    record: ConceptRecord | SurfaceRecord | JourneyRecord,
    group: str,
) -> list[dict[str, Any]]:
    """One topic's facts, in reading order, empty ones left out.

    The values come from :func:`~s0ma_dsl.docs_model.resolve.facts_of` —
    the same reading every channel resolves through — so nothing here can
    describe a record differently from the page that describes it. A fact
    with nothing in it is omitted rather than written as an empty section,
    which is the human channel's rule and for its reason: an empty heading
    reads as a product that has stopped answering.
    """
    view = facts_of(bundle, record)
    headings = _headings(group)
    title_fact = TITLE_FACT[group]
    sections: list[dict[str, Any]] = []
    for fact in SECTION_FACTS[group]:
        if fact == title_fact:
            continue
        value = view.value(fact)
        if isinstance(value, str):
            if not value.strip():
                continue
            sections.append({"fact": fact, "heading": headings[fact], "text": value})
            continue
        if not value:
            continue
        sections.append(
            {"fact": fact, "heading": headings[fact], "items": list(value)}
        )
    return sections


def _title(
    record: ConceptRecord | SurfaceRecord | JourneyRecord, group: str
) -> str:
    """What a reader is shown this topic as.

    :data:`~s0ma_dsl.docs_model.render_human.TITLE_FACT` again, so a topic
    is titled here the way it is titled on its page. A journey has no name
    a person would use, so its id is its title — which is the human
    channel's answer too.
    """
    title_fact = TITLE_FACT[group]
    if title_fact == "topic_id":
        return record.id
    value = getattr(record, title_fact)
    if not isinstance(value, str):  # pragma: no cover - guarded by TITLE_FACT
        raise DocsCoreSliceError(f"{record.id} has no text title under {title_fact!r}")
    return value


def _summary(
    record: ConceptRecord | SurfaceRecord | JourneyRecord, group: str
) -> str:
    """The one line an index writes this topic as.

    A concept carries an authored short form for exactly this purpose; a
    capability and a journey carry an intent, which is the one sentence
    each of them already has. Nothing is paraphrased — a bounded channel
    may only get smaller by omitting (C1's ruling on ``summary``), so the
    short form is quoted whole or the topic has none.
    """
    if group == "concepts":
        return getattr(record, "summary", "")
    return getattr(record, "intent", "")


def _documents(
    documents: Sequence[DocumentRecord], topic_id: str
) -> list[dict[str, str]]:
    """Where this topic is written up at length, from the catalog's own edges.

    ``DocumentRecord.covers`` is the catalog's answer to "which documents
    are about this", so the pointer is derived rather than guessed. It is
    a pointer and not content: the pages themselves stay in the
    repository, and a reader on an installed wheel gets a path they can
    look up rather than a copy that would need its own drift gate.
    """
    return [
        {
            "id": document.id,
            "title": document.title,
            "canonical_source": document.canonical_source,
        }
        for document in sorted(documents, key=lambda item: item.id)
        if topic_id in document.covers
    ]


def _search_terms(topic_id: str, title: str, aliases: AliasIndex) -> list[str]:
    """The words that reach this topic, besides its id.

    Its own name, and every alternate name the concept files declare for
    it — the old term somebody arrives holding. Lowercased, hyphens and
    the id prefix taken off, sorted and de-duplicated, so the reader that
    matches on them can do it with one comparison and no cleverness.
    """
    found = {title.strip().lower()}
    for old, new in aliases.entries:
        if new != topic_id:
            continue
        _, _, tail = old.partition(":")
        found.add(tail.replace("-", " ").strip().lower())
    found.discard("")
    return sorted(found)


def _availability(record: JourneyRecord, servable: frozenset[str]) -> str:
    """Whether this installation can walk this path, counted and not assumed.

    Every journey in the corpus today walks the authoring toolchain and
    none of its steps is a core surface, so every one of them gets the
    first sentence. The count is taken rather than written down, so the
    day a journey's steps become core capabilities it starts saying the
    other thing without anybody editing this module.
    """
    taken = sum(1 for step in record.steps if step.surface in servable)
    if taken == 0:
        return ENVELOPE["availability-none"]
    return ENVELOPE["availability-partial"]


def _concept_topic(
    bundle: DocsBundle, record: ConceptRecord, aliases: AliasIndex
) -> dict[str, Any]:
    title = _title(record, "concepts")
    return {
        "id": record.id,
        "group": "concepts",
        "title": title,
        "summary": _summary(record, "concepts"),
        "search_terms": _search_terms(record.id, title, aliases),
        "sections": _sections(bundle, record, "concepts"),
        "documents": _documents(bundle.documents, record.id),
    }


def _surface_topic(
    bundle: DocsBundle, record: SurfaceRecord, aliases: AliasIndex
) -> dict[str, Any]:
    title = _title(record, "surfaces")
    return {
        "id": record.id,
        "group": "surfaces",
        "title": title,
        "summary": _summary(record, "surfaces"),
        "search_terms": _search_terms(record.id, title, aliases),
        "channel": record.channel,
        "sections": _sections(bundle, record, "surfaces"),
        "documents": _documents(bundle.documents, record.id),
    }


def _journey_topic(
    bundle: DocsBundle,
    record: JourneyRecord,
    aliases: AliasIndex,
    servable: frozenset[str],
) -> dict[str, Any]:
    title = _title(record, "journeys")
    return {
        "id": record.id,
        "group": "journeys",
        "title": title,
        "summary": _summary(record, "journeys"),
        "search_terms": _search_terms(record.id, title, aliases),
        "availability": _availability(record, servable),
        "sections": _sections(bundle, record, "journeys"),
        "documents": _documents(bundle.documents, record.id),
    }


def _indexes(
    concepts: Sequence[str],
    surfaces: Sequence[SurfaceRecord],
    journeys: Sequence[str],
) -> list[dict[str, Any]]:
    """The four navigation entries, each a grouped list of ids.

    They are addressable topics of the slice's own — a reader who asks for
    "glossary" is asking for a list, and handing them one is a better
    answer than picking a concept and hoping. The capability index groups
    by channel with
    :data:`~s0ma_dsl.docs_model.inventories.CHANNEL_TITLES`, which is the
    same wording the generated surface index uses.
    """
    by_channel: dict[str, list[str]] = {}
    for record in surfaces:
        by_channel.setdefault(record.channel, []).append(record.id)
    surface_groups = [
        {"title": CHANNEL_TITLES.get(channel, channel), "topics": sorted(ids)}
        for channel, ids in sorted(by_channel.items())
    ]
    concept_group = {
        "title": ENVELOPE["index-concepts-title"],
        "topics": list(concepts),
    }
    journey_group = {
        "title": ENVELOPE["index-journeys-title"],
        "topics": list(journeys),
    }
    surface_group = {
        "title": ENVELOPE["index-surfaces-title"],
        "topics": [record.id for record in surfaces],
    }
    return [
        {
            "id": ALL_INDEX,
            "title": ENVELOPE["index-all-title"],
            "summary": ENVELOPE["index-all-summary"],
            # Names only. This is the list a question nothing answered
            # falls back to, so it is the one a reader meets by accident,
            # a description of every topic in the corpus is not a helpful
            # answer to a typing mistake. The three lists below carry the
            # descriptions, and this one says so.
            "lines": LINES_NAMES,
            "groups": [concept_group, surface_group, journey_group],
        },
        {
            "id": CONCEPTS_INDEX,
            "title": ENVELOPE["index-concepts-title"],
            "summary": ENVELOPE["index-concepts-summary"],
            "lines": LINES_SUMMARIES,
            "groups": [concept_group],
        },
        {
            "id": SURFACES_INDEX,
            "title": ENVELOPE["index-surfaces-title"],
            "summary": ENVELOPE["index-surfaces-summary"],
            "lines": LINES_SUMMARIES,
            "groups": surface_groups,
        },
        {
            "id": JOURNEYS_INDEX,
            "title": ENVELOPE["index-journeys-title"],
            "summary": ENVELOPE["index-journeys-summary"],
            "lines": LINES_SUMMARIES,
            "groups": [journey_group],
        },
    ]


def _check_selection(
    concepts: Sequence[ConceptRecord],
    surfaces: Sequence[SurfaceRecord],
    journeys: Sequence[JourneyRecord],
) -> None:
    """Refuse a slice with a family missing from it.

    The renderer's own anti-vacuity floor, and it refuses rather than
    returns: :func:`~s0ma_dsl.docs_model.application.build` turns a
    refusal into a ``DOC_GATE_VACUOUS`` finding and writes nothing, which
    is what should happen when a provider has quietly stopped producing.
    A slice with no concepts would ship a wheel that teaches nothing while
    passing every byte comparison downstream, because there would be no
    bytes to compare.
    """
    for name, selected in (
        ("concepts", concepts),
        ("core surfaces", surfaces),
        ("journeys", journeys),
    ):
        if not selected:
            raise DocsCoreSliceError(
                f"this build composed no {name}, so the core teaching slice "
                f"would ship a wheel that cannot answer. Check that the "
                f"provider behind them ran before changing anything here."
            )


def _check_keywords(topics: Sequence[str]) -> None:
    """Every legacy keyword points at a topic this slice carries.

    The compatibility promise, checked at the one moment it can be: a
    keyword aimed at a concept somebody renamed is a question that used to
    be answerable and is not, and this is where that becomes a failing
    documentation build instead of a shrug in somebody's terminal.
    """
    known = set(topics)
    missing = sorted(
        {target for target in LEGACY_KEYWORDS.values() if target not in known}
    )
    if missing:
        raise DocsCoreSliceError(
            f"the core teaching slice's keyword vocabulary points at "
            f"{missing}, which this build did not select. Every keyword core "
            f"answered before this milestone has to keep answering — repoint "
            f"the keyword in LEGACY_KEYWORDS at the topic that replaced it."
        )


def core_teaching_slice(bundle: DocsBundle, *, aliases: AliasIndex) -> str:
    """The core-neutral teaching slice for ``bundle``, as canonical JSON.

    Readable with the standard library alone: the document is objects,
    arrays, strings and numbers, and nothing in it is a Python
    construction s0ma-core would need s0ma-dsl to understand. That is the
    whole point of the file — see this module's own notes for what it
    carries and why each rule of selection is the honest one.
    """
    concepts = sorted(bundle.concepts, key=lambda item: item.id)
    surfaces = core_surfaces(bundle)
    journeys = sorted(bundle.journeys, key=lambda item: item.id)
    _check_selection(concepts, surfaces, journeys)

    servable = frozenset(record.id for record in surfaces)
    topics: list[dict[str, Any]] = [
        *(_concept_topic(bundle, record, aliases) for record in concepts),
        *(_surface_topic(bundle, record, aliases) for record in surfaces),
        *(_journey_topic(bundle, record, aliases, servable) for record in journeys),
    ]
    topics.sort(key=lambda item: str(item["id"]))

    indexes = _indexes(
        [record.id for record in concepts],
        surfaces,
        [record.id for record in journeys],
    )
    addressable = {str(item["id"]) for item in topics}
    _check_keywords(sorted(addressable | {str(item["id"]) for item in indexes}))

    document: dict[str, Any] = {
        "schema": CORE_TEACHING_SCHEMA,
        # ``build_channel`` arrived at H2 and is the fourth source field
        # (architecture §13.2). Core renders an identity line on every
        # answer it serves, and until this field existed that line was the
        # one identity line in the product that could not say which channel
        # it came from: a wheel built from ``main`` told its reader "This
        # answer came from s0ma 0.18.1" flat, which is the sentence §13.2
        # exists to forbid. It is a *structured* field rather than a label
        # baked into ``release_version`` because the two answer different
        # questions — the bare version is what a machine compares, the
        # labelled line is what a reader meets — and that is the same split
        # :meth:`~s0ma_dsl.docs_model.bundle.Snapshot.version_line` keeps
        # on the other side of the wall. Core composes the line itself,
        # from these two fields, by the same rule.
        "source": {
            "build_channel": bundle.stamp.build_channel,
            "model_schema": bundle.stamp.schema,
            "release_version": bundle.stamp.release_version,
            "snapshot_hash": bundle.stamp.snapshot_hash,
        },
        "counts": {
            "topics": len(topics),
            "concepts": len(concepts),
            "surfaces": len(surfaces),
            "journeys": len(journeys),
            "indexes": len(indexes),
            "aliases": sum(1 for _, new in aliases.entries if new in addressable),
            "keywords": len(LEGACY_KEYWORDS),
        },
        "topics": topics,
        "indexes": indexes,
        # Only the alternate names that reach a topic this slice carries: an
        # alias forwarding to something core was not given would be a
        # promise the file cannot keep.
        "aliases": {
            old: new for old, new in aliases.entries if new in addressable
        },
        "keywords": dict(sorted(LEGACY_KEYWORDS.items())),
        "live_example_topics": [
            topic for topic in LIVE_EXAMPLE_TOPICS if topic in addressable
        ],
    }
    return canonical_json(document)
