"""One approved journey as a production script: the media manifest of §13.3.

Milestone H3 of the docs-function plan (internal) §13, implementing the
architecture plan's §13.3 field list:

```text
title and audience
learning outcome and prerequisites
ordered steps and exact surfaces
executable example/transcript source
expected visible state
cautions, consent, and recovery beats
suggested chapters and captions
product version and snapshot hash
```

**Every factual field is derived.** Nothing in this module writes a fact
about the product. Titles and audiences are read off the catalog row that
publishes the journey; the outcome is the journey's own intent; steps,
expected states, approval boundaries and recovery paths are the journey
record's own fields; surface names, channels and side effects are the
surface records the steps point at; the identity block is the build stamp.
A field this module could not derive would be a field it does not write,
which is why there is no ``notes`` key and no default text anywhere below.

**Why §13.3's creative fields are absent, and stay absent.** §13.3 ends by
saying that human scripting, performance and visual direction *remain
creative work*. Tone, visual direction, music and pacing are therefore not
fields this schema has and not fields it is missing: they are the H4
handoff's subject, and a schema carrying an empty ``tone`` key would be an
invitation to fill it in here — where the one thing that could be written
is somebody's opinion, byte-gated as though it were a fact.
:data:`CREATIVE_KEYS` names them so a proof can assert their absence
rather than a reader having to notice it.

**Placeholders stay placeholders.** ``{project}``, ``{tmp}``, ``{version}``
and ``{duration}`` are the transcript format's own closed set
(:data:`~s0ma_dsl.docs_model.evidence.PLACEHOLDERS`), and any of them that
reaches a package through an authored sentence is written through
unchanged. Two reasons, and either alone would settle it. A resolved path
is *wrong* in a production script — the person shooting this walkthrough
works in their own directory, not in the temporary one some replay used —
and a resolved path is not deterministic, so a package carrying one could
not be byte-gated at all. The package is a script for a human to perform
later; it is not a transcript of a run that already happened, and the
transcript it points at is named rather than inlined.

No journey quotes a placeholder today — they live in the fixtures, which
this module names and never reads — so the rule is a property of the
renderer rather than a visible feature of the committed packages: nothing
here substitutes anything into an authored sentence, and the proof plants
one to show it comes back verbatim.

**Approved, and what decides it.** §13.3 says *each approved journey* can
emit a media manifest, and this module reads that word structurally:
:func:`approved_journeys` keeps the journeys a catalog document covers.
That is the repository's existing publication decision rather than a
second one invented here — a journey somebody wrote a published guide for
is a journey the product stands behind, and one nothing publishes is a
prototype. It is the difference between the five canonical E3–E7 paths and
``journey:studi0-viewing``, the B7 prototype no document covers, and it is
a rule rather than a list: publishing a guide for a sixth journey emits a
sixth package with nothing here to edit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.records import SCHEMA, DocsModelError
from s0ma_dsl.docs_model.serialize import canonical_json
from s0ma_dsl.docs_model.validate import APPROVAL_EFFECT

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from s0ma_dsl.docs_model.providers_catalog import CatalogRow
    from s0ma_dsl.docs_model.records import (
        DocsBundle,
        JourneyRecord,
        JourneyStep,
        SurfaceRecord,
    )

__all__ = [
    "CREATIVE_KEYS",
    "JOURNEY_PREFIX",
    "MEDIA_DIR",
    "MEDIA_SCHEMA",
    "QUIET_EFFECTS",
    "DocsMediaError",
    "approved_journeys",
    "media_outputs",
    "media_package",
    "media_packages",
    "package_path",
    "stale_packages",
]


class DocsMediaError(DocsModelError):
    """A media package cannot be rendered from what this build composed."""


#: Where the packages live, relative to the documentation root. Under
#: ``_generated/`` because ADR-012 §1 puts machine-readable outputs there
#: and because this is one: nobody opens a media package to read it, a
#: producer's tooling and a person planning a shoot do, and it is JSON for
#: the same reason the manifest is.
MEDIA_DIR = "_generated/media"

#: The id prefix every package is rendered from.
JOURNEY_PREFIX = "journey:"

#: The package's ``schema`` field. The model's own, like the manifest's and
#: unlike the authored transcript fixtures': a fixture is an *input* to the
#: model and versions separately, and a media package is a rendering *of*
#: the model, so it is versioned with the model it renders.
MEDIA_SCHEMA = SCHEMA

#: Side-effect words that need no beat. ``read`` changes nothing and
#: ``none`` is the declared absence of an effect, so a step whose surface
#: says only these is a step a producer can film without warning anybody
#: about anything. Every other word in
#: :data:`~s0ma_dsl.docs_model.validate.SIDE_EFFECT_WORDS` earns a caution
#: beat, and :data:`~s0ma_dsl.docs_model.validate.APPROVAL_EFFECT` earns a
#: consent beat on top of it.
QUIET_EFFECTS: frozenset[str] = frozenset({"none", "read"})

#: The creative fields §13.3 hands to human production, named so a proof
#: can assert this schema does not carry them. They are H4's territory:
#: nothing derivable from a journey or a snapshot decides any of them, so a
#: key here would be filled in by whoever rendered it last.
CREATIVE_KEYS: tuple[str, ...] = (
    "colour",
    "look",
    "music",
    "mood",
    "narration",
    "pacing",
    "score",
    "soundtrack",
    "style",
    "tempo",
    "tone",
    "visual_direction",
    "voice",
)


def package_path(journey_id: str) -> str:
    """Where the package for ``journey_id`` is written, relative to ``docs/``.

    The journey's own last segment, so a reader holding
    ``journey:first-project`` opens ``first-project.json`` and never has to
    consult a table to find out which file is which.
    """
    if not journey_id.startswith(JOURNEY_PREFIX):
        raise DocsMediaError(
            f"{journey_id!r} is not a journey id, so it names no media "
            f"package; ids in this model start with {JOURNEY_PREFIX!r}."
        )
    slug = journey_id[len(JOURNEY_PREFIX) :]
    if not slug or "/" in slug:
        raise DocsMediaError(
            f"{journey_id!r} has no single-segment name, so the package it "
            f"would render to has no path inside {MEDIA_DIR}."
        )
    return f"{MEDIA_DIR}/{slug}.json"


# ---------------------------------------------------------------------------
# Which journeys are approved
# ---------------------------------------------------------------------------


def _publishers(bundle: DocsBundle) -> Mapping[str, str]:
    """Journey id to the id of the catalog document that publishes it.

    A journey covered by more than one document keeps the first in id
    order, which is a rule rather than a coincidence: the packages are
    byte-gated, so *which* row supplies the title has to be decided by
    something stable, and a set with no order would make the title depend
    on the order the catalog happened to load.
    """
    found: dict[str, str] = {}
    for document in sorted(bundle.documents, key=lambda record: record.id):
        for covered in document.covers:
            if covered.startswith(JOURNEY_PREFIX):
                found.setdefault(covered, document.id)
    return found


def approved_journeys(bundle: DocsBundle) -> tuple[JourneyRecord, ...]:
    """Every journey this build may emit a package for, in id order.

    §13.3's *approved* read structurally: a journey some catalog document
    covers. See the module docstring for why publication is the test and
    why the rule is not a list of five ids.
    """
    publishers = _publishers(bundle)
    return tuple(
        record
        for record in sorted(bundle.journeys, key=lambda item: item.id)
        if record.id in publishers
    )


# ---------------------------------------------------------------------------
# The parts of one package
# ---------------------------------------------------------------------------


def _ordinal(index: int) -> str:
    """A step's position, as text.

    Text rather than a number because
    :func:`~s0ma_dsl.docs_model.serialize.record_from_plain` reads only
    text and nested records back, and a package that could be written but
    not read would be the one artifact of this build that does not
    round-trip.

    It is written at all — rather than left implicit in the list's order —
    because a package is read out of order by the person it is for. A
    producer shoots chapter five on Tuesday, and a chapter that cannot be
    named cannot be referred to in the one conversation this file exists to
    support.
    """
    return str(index)


def _surfaces(bundle: DocsBundle) -> Mapping[str, SurfaceRecord]:
    return {record.id: record for record in bundle.surfaces}


def _surface(surfaces: Mapping[str, SurfaceRecord], surface_id: str, where: str) -> SurfaceRecord:
    record = surfaces.get(surface_id)
    if record is None:
        raise DocsMediaError(
            f"{where} walks {surface_id}, which this build composed no "
            f"surface for. A media package states the exact surface a step "
            f"is taken on; naming one nothing serves would put a command in "
            f"a walkthrough that the product does not answer."
        )
    return record


def _effects(surface: SurfaceRecord) -> tuple[str, ...]:
    """The step's declared effects, sorted, as the surface states them."""
    return tuple(sorted(surface.side_effects))


def _loud(surface: SurfaceRecord) -> tuple[str, ...]:
    """The effects that earn a caution beat: everything that is not quiet.

    ``approval`` is left out here and not anywhere: it is the *consent*
    beat's whole subject, and a step that both writes and asks gets both
    beats, each saying the thing only it can say — what the step does to
    the machine, and what it asks the person first.
    """
    return tuple(
        sorted(set(surface.side_effects) - QUIET_EFFECTS - {APPROVAL_EFFECT})
    )


def _step(index: int, step: JourneyStep, surface: SurfaceRecord) -> dict[str, object]:
    """One ordered step: where you are, why, and what should be on screen."""
    return {
        "channel": surface.channel,
        "expected_visible_state": step.expected_outcome,
        "ordinal": _ordinal(index),
        "purpose": step.purpose,
        "side_effects": list(_effects(surface)),
        "surface": surface.id,
        "surface_name": surface.public_name,
    }


def _chapters(
    record: JourneyRecord, surfaces: Mapping[str, SurfaceRecord]
) -> list[dict[str, object]]:
    """The suggested chapter outline: one chapter per step.

    The journey records carry no grouping structure — a journey is an
    ordered list of steps and nothing in the schema says which of them
    belong together — so the outline is the steps, said as such rather than
    invented. Grouping four steps into a chapter called "setup" would be a
    teaching decision, and this module is not where teaching decisions are
    taken; if journeys ever grow a grouping field, this is the one function
    that changes.

    The caption is the step's own ``purpose`` sentence, quoted rather than
    rewritten, for the reason
    :attr:`~s0ma_dsl.docs_model.records.ConceptRecord.summary` exists: the
    prose was voice-checked where it was authored, and a channel that
    paraphrased it would be a second, unchecked wording of one fact. The
    chapter title is the surface's public name, which is the exact thing a
    viewer watches being typed.
    """
    return [
        {
            "caption": step.purpose,
            "ordinal": _ordinal(index),
            "step": _ordinal(index),
            "title": _surface(surfaces, step.surface, record.id).public_name,
        }
        for index, step in enumerate(record.steps, start=1)
    ]


def _cautions(
    record: JourneyRecord, surfaces: Mapping[str, SurfaceRecord]
) -> list[dict[str, object]]:
    """A beat per step that does something to the machine.

    Derived from the surface's declared ``side_effects`` and from nothing
    else. The beat carries the effect words themselves rather than a
    sentence about them, because a sentence would be prose this module
    authored — and the words are the product's own classification, already
    gated by ``DOC_SIDE_EFFECT_UNDECLARED``.
    """
    beats: list[dict[str, object]] = []
    for index, step in enumerate(record.steps, start=1):
        surface = _surface(surfaces, step.surface, record.id)
        loud = _loud(surface)
        if not loud:
            continue
        beats.append(
            {
                "effects": list(loud),
                "step": _ordinal(index),
                "surface": surface.id,
                "surface_name": surface.public_name,
            }
        )
    return beats


def _consent(
    record: JourneyRecord, surfaces: Mapping[str, SurfaceRecord]
) -> list[dict[str, object]]:
    """A beat per step that asks the person before anything happens.

    The test is the surface's ``approval`` effect, which is the same test
    :func:`~s0ma_dsl.docs_model.validate.check_journeys` applies in both
    directions — so the boundary text quoted here is present exactly when
    this beat is emitted, and neither can drift away from the other without
    the journey gate going red first.

    The text is the journey's own ``approval_boundary``, verbatim. It is
    the sentence a reader is told before the step is taken, it was written
    and voice-checked as that sentence, and a walkthrough that performed a
    consent moment in different words than the product uses would teach the
    wrong words for the one moment where the words matter.
    """
    beats: list[dict[str, object]] = []
    for index, step in enumerate(record.steps, start=1):
        surface = _surface(surfaces, step.surface, record.id)
        if APPROVAL_EFFECT not in surface.side_effects:
            continue
        if not step.approval_boundary.strip():
            raise DocsMediaError(
                f"{record.id} step {index} is taken on {surface.id}, which "
                f"declares the {APPROVAL_EFFECT!r} effect, and the step "
                f"declares no approval boundary. A consent beat with nothing "
                f"to say is the 'prompt that never comes' half of "
                f"DOC_APPROVAL_UNDECLARED; the journey record is where it is "
                f"written."
            )
        beats.append(
            {
                "boundary": step.approval_boundary,
                "effects": list(_effects(surface)),
                "step": _ordinal(index),
                "surface": surface.id,
                "surface_name": surface.public_name,
            }
        )
    return beats


def _recovery(
    record: JourneyRecord, surfaces: Mapping[str, SurfaceRecord]
) -> list[dict[str, object]]:
    """A beat per named failure this path recovers from, in the record's order.

    ``when`` is the failure's name as the product spells it and ``action``
    is the journey's own remedy sentence. The surface a recovery leads to
    is resolved to its public name here for the same reason a step's is: a
    producer needs the thing that is typed, not the id it is filed under.
    """
    return [
        {
            "action": path.action,
            "next_surface": path.next_surface,
            "next_surface_name": _surface(
                surfaces, path.next_surface, record.id
            ).public_name,
            "when": path.when,
        }
        for path in record.recovery_paths
    ]


def _prerequisites(record: JourneyRecord, terms: Mapping[str, str]) -> list[dict[str, object]]:
    """What a viewer is assumed to know before step one.

    The journey's ``concepts_required``, each resolved to the term the
    concept record spells it with. The id travels beside the term rather
    than instead of it: the term is what a narrator says and the id is what
    a producer follows back into the documentation.
    """
    return [
        {"concept": concept, "term": terms.get(concept, "")}
        for concept in sorted(record.concepts_required)
    ]


def _outcome_concepts(record: JourneyRecord, terms: Mapping[str, str]) -> list[dict[str, object]]:
    """What walking this path leaves a viewer with, in teaching order.

    Ordered, not sorted, because the order is the content: it is the order
    the ideas are met in, and re-sorting it would turn a teaching sequence
    into an alphabetical list of words.
    """
    return [
        {"concept": concept, "term": terms.get(concept, "")}
        for concept in record.concepts_taught
    ]


# ---------------------------------------------------------------------------
# One package
# ---------------------------------------------------------------------------


def media_package(
    bundle: DocsBundle,
    record: JourneyRecord,
    *,
    rows: Sequence[CatalogRow],
) -> str:
    """One approved journey as its media manifest, canonical JSON.

    ``rows`` is the catalog's presentation half — the title and audiences a
    bundle has nowhere to carry — and it arrives from the caller for the
    reason every renderer in this application takes its sources from one:
    a second reading of the catalog could describe a row nobody composed.
    """
    publishers = _publishers(bundle)
    document_id = publishers.get(record.id)
    if document_id is None:
        raise DocsMediaError(
            f"{record.id} is not published by any catalog document, so no "
            f"media package is rendered for it. Architecture §13.3 emits a "
            f"media manifest for an *approved* journey; a journey nothing "
            f"documents has not been approved for a public walkthrough."
        )
    # The title is the document *record*'s and the audiences are the
    # catalog *row*'s, because that is where each of the two actually
    # lives: `@1` declares a title on the record and defers audience to
    # the row (see providers_catalog.CatalogRow). Reading each from its own
    # home is what keeps this renderer from needing a third copy of either.
    published = next((item for item in bundle.documents if item.id == document_id), None)
    row = next((item for item in rows if item.id == document_id), None)
    if published is None or row is None:
        raise DocsMediaError(
            f"{record.id} is covered by {document_id}, which this build "
            f"composed no catalog row for; the package's title and audience "
            f"are that row's, and there is nothing honest to write without it."
        )
    surfaces = _surfaces(bundle)
    terms = {concept.id: concept.term for concept in bundle.concepts}
    if not record.steps:
        raise DocsMediaError(
            f"{record.id} has no steps, so there is no walkthrough to script."
        )
    document = {
        "identity": {
            "channel": bundle.stamp.build_channel,
            "journey": record.id,
            "published_by": document_id,
            "release": bundle.stamp.version_line(),
            "snapshot": bundle.stamp.snapshot_hash,
        },
        "package": {
            "audience": list(row.audiences),
            "cautions": _cautions(record, surfaces),
            "chapters": _chapters(record, surfaces),
            "consent": _consent(record, surfaces),
            "evidence": [
                {"id": item.id, "source": item.source}
                for item in sorted(record.evidence, key=lambda item: item.id)
            ],
            "outcome": record.intent,
            "prerequisites": _prerequisites(record, terms),
            "recovery": _recovery(record, surfaces),
            "steps": [
                _step(index, step, _surface(surfaces, step.surface, record.id))
                for index, step in enumerate(record.steps, start=1)
            ],
            "teaches": _outcome_concepts(record, terms),
            "title": published.title,
        },
        "schema": MEDIA_SCHEMA,
    }
    return canonical_json(document)


def media_packages(
    bundle: DocsBundle, *, rows: Sequence[CatalogRow]
) -> dict[str, str]:
    """Every package this build renders, keyed by path relative to ``docs/``.

    One call for the whole collection, like the learning collection and for
    the same reason: one walk of the approved journeys is what keeps two
    packages from disagreeing about which journeys exist.

    **An empty collection is not this module's refusal to make**, and the
    reason is the one :func:`~s0ma_dsl.docs_model.application._artifacts`
    states: a caller composing a smaller provider set is supported, so a
    build with no journeys provider — every negative fixture in the suite —
    has an honestly empty collection rather than a broken renderer. What
    covers the emptiness is two gates that can see more than this function
    can. A composition that lost its journeys is reported by
    :data:`~s0ma_dsl.docs_model.providers_journeys.JOURNEY_FLOORS`, and a
    catalog that stopped publishing them leaves five committed packages
    that nothing renders — which
    :func:`~s0ma_dsl.docs_model.application._stale_media_packages` reports
    by name, one finding per file. Refusing here would report the same
    thing a third time, and would report it in every build that never had
    journeys to begin with.
    """
    packages: dict[str, str] = {}
    for record in approved_journeys(bundle):
        relative = package_path(record.id)
        if relative in packages:
            raise DocsMediaError(
                f"two journeys render to {relative}. A package can only carry "
                f"one of them, and which one would depend on the order the "
                f"records happened to arrive in."
            )
        packages[relative] = media_package(bundle, record, rows=rows)
    return dict(sorted(packages.items()))


def media_outputs(bundle: DocsBundle) -> tuple[str, ...]:
    """Every path this collection declares, sorted, relative to ``docs/``.

    Derived from the same walk :func:`media_packages` makes, so the set
    that is written and the set that is compared cannot disagree about what
    the collection contains. The application's
    :data:`~s0ma_dsl.docs_model.application.STATIC_OUTPUTS` is a fixed
    tuple because its artifacts are decisions; these are not — which
    journeys are approved is decided in the catalog, so a fixed list of
    five paths would be an independently maintained inventory of exactly
    the kind architecture §8.2 forbids.
    """
    return tuple(sorted(package_path(record.id) for record in approved_journeys(bundle)))


def stale_packages(present: Iterable[str], bundle: DocsBundle) -> tuple[str, ...]:
    """Committed packages in this collection that this build does not render.

    The half a declared-output set cannot cover on its own, and the reason
    this collection needs the sweep the decided outputs do not: membership
    here is *computed*, so a package left behind by a journey somebody
    unpublished is a file no gate ever looks at.

    ``present`` arrives from the caller — a gate that enumerated its own
    subject could satisfy itself, and reading a directory is a filesystem
    act this module does not perform.
    """
    return tuple(sorted(set(present) - set(media_outputs(bundle))))
