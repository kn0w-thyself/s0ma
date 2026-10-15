"""The gates a composed bundle has to pass, and the reverse index they build.

Milestone C2 of the docs-function plan (internal) §8, task T3. Five rules
over one bundle:

* **every reference resolves** (architecture plan §6.7: "all targets must
  resolve"), and the walk that proves it also produces the reverse index
  §11.2 needs — a change to an authority can list the concepts, surfaces,
  documents and journeys that would have to be re-read;
* **who governs** a claim, honoring the delegation status plan §5
  ratified;
* **every record can be traced** to a source, a schema and a digest
  (``DOC_PROVENANCE_MISSING``);
* **no provider resolved empty** below a floor its caller supplied
  (``DOC_GATE_VACUOUS``);
* **an ordered teaching sequence resolves and repeats nothing**
  (``DOC_SEQUENCE_REPEATS``);
* **a journey can actually be walked** — E1's four rules over the paths
  themselves: the failure a recovery is written against is real and
  unambiguous, nothing is taught before the ideas it rests on, an
  approval boundary is declared exactly where one is crossed, and
  something has run the path (:func:`check_journeys`);
* **one manifest describes one build of one version**
  (``DOC_VERSION_MISMATCH``, armed at H1): the four distributions agree
  with the product version, every listed artifact represents that version,
  came from that snapshot and was rendered on that channel, and no
  provider is emitting against an older model version
  (:func:`check_manifest`).

Everything returns :class:`~s0ma_dsl.docs_model.providers.Finding`
values; nothing raises for a documentation problem. Three unresolved
references are three findings in one run, not three runs.

**These are documentation-application findings, not DSL diagnostics.**
They never enter the transpiler's severity matrix and
``s0ma_dsl.config`` is untouched by this module. The names follow the
architecture plan's §11 table wherever a row fits; the three that had no
row are in :data:`MINTED_CODES` with the reason each exists, awaiting the
C gate the way C1's ``sequence:`` id form awaits it.

**What a location can be here.** ``@1`` records no line numbers. A
finding is placed at the source the *citing record itself* names — a
surface's provenance source, a document's prose locator, an authority's
source and section. A concept, a journey and a teaching sequence name no
file, so findings about them carry no location and say what is wrong by
id instead. Line-anchored findings arrive when the records do: B6 proved
a JSON catalog can locate its own rows, and the milestone that reads
those files is where that lands.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.ids import id_form, normalize_id
from s0ma_dsl.docs_model.manifest import LOCKSTEP_ANCHOR
from s0ma_dsl.docs_model.providers import (
    GROUP_NAMES,
    DocsRecord,
    Finding,
    ProviderResult,
    sort_findings,
)
from s0ma_dsl.docs_model.records import (
    AUTHORITY_ORDER,
    BUILD_CHANNELS,
    HISTORICAL_CHANNEL,
    AuthorityDelegation,
    AuthorityRef,
    ConceptRecord,
    DocsBundle,
    DocsModelError,
    DocumentRecord,
    JourneyRecord,
    Provenance,
    SurfaceRecord,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from s0ma_dsl.docs_model.manifest import ArtifactRecord, DocsManifest
    from s0ma_dsl.docs_model.records import BuildStamp

__all__ = [
    "APPROVAL_EFFECT",
    "CHANNEL_EFFECTS",
    "DEFERRED_GATES",
    "DOC_APPROVAL_UNDECLARED",
    "DOC_AUTHORITY_CONFLICT",
    "DOC_AUTHORITY_MISDECLARED",
    "DOC_CONCEPT_UNRESOLVED",
    "DOC_GATE_VACUOUS",
    "DOC_JOURNEY_UNRESOLVED",
    "DOC_JOURNEY_UNTESTED",
    "DOC_PROVENANCE_MISSING",
    "DOC_SEQUENCE_REPEATS",
    "DOC_SIDE_EFFECT_UNDECLARED",
    "DOC_SURFACE_UNBOUND",
    "DOC_TEACHING_ORDER",
    "DOC_TOPIC_UNRESOLVED",
    "DOC_VERSION_MISMATCH",
    "JOURNEY_REFERENCE_CLASSES",
    "MINTED_CODES",
    "SIDE_EFFECT_WORDS",
    "TEACHING_PREREQUISITE",
    "AuthorityClaim",
    "AuthorityDecision",
    "EvidenceResolver",
    "Reference",
    "ReferenceIndex",
    "check_authority_records",
    "check_floors",
    "check_journeys",
    "check_manifest",
    "check_provenance",
    "check_references",
    "check_sequences",
    "check_side_effects",
    "check_surface_binding",
    "governing_authority",
    "location_of",
    "records_of",
    "references",
    "validate_bundle",
]

# ---------------------------------------------------------------------------
# Diagnostic names
# ---------------------------------------------------------------------------

#: A guide, journey, alias or relationship names an absent concept (§11).
DOC_CONCEPT_UNRESOLVED = "DOC_CONCEPT_UNRESOLVED"

#: A journey step names a missing surface, example, diagnostic or
#: authority (§11). Keyed on the *citing* record, exactly as §11 words it.
DOC_JOURNEY_UNRESOLVED = "DOC_JOURNEY_UNRESOLVED"

#: A journey has no executable example or transcript evidence (§11).
#: **Armed at E1** behind :data:`EvidenceResolver`: the question is only
#: asked of a caller that can answer it, and E2's runner is what will
#: answer it. See :func:`check_journeys`.
DOC_JOURNEY_UNTESTED = "DOC_JOURNEY_UNTESTED"

#: A public surface cannot resolve to an implementing component (§11).
DOC_SURFACE_UNBOUND = "DOC_SURFACE_UNBOUND"

#: A served surface says nothing about what calling it does to the world
#: (§11). **Armed at D5b**, once the D-phase surface providers existed to
#: derive the fact; the gate is :func:`check_side_effects`.
DOC_SIDE_EFFECT_UNDECLARED = "DOC_SIDE_EFFECT_UNDECLARED"

#: A lower-authority assertion contradicts a higher-authority one (§11).
#: Here: a domain-scoped question with no single answer.
DOC_AUTHORITY_CONFLICT = "DOC_AUTHORITY_CONFLICT"

#: A derived record lacks source identity, schema or hash (§11).
DOC_PROVENANCE_MISSING = "DOC_PROVENANCE_MISSING"

#: A provider, catalog class, coverage set or mirror set unexpectedly
#: resolves empty (§11).
DOC_GATE_VACUOUS = "DOC_GATE_VACUOUS"

#: A release-bound document or artifact represents another version without
#: historical status (§11). **Armed at H1**, over the documentation
#: manifest, which is the first artifact in this application that states a
#: version and a channel and can therefore be caught disagreeing with
#: itself. The gate is :func:`check_manifest`.
DOC_VERSION_MISMATCH = "DOC_VERSION_MISMATCH"

#: A reference is well formed and names nothing this build knows about,
#: and neither §11 row above fits: a concept citing an absent authority,
#: a catalog row covering an absent journey, a teaching step naming an
#: absent surface. **Minted at B6**, proved there against real guide
#: prose, and used unchanged here.
DOC_TOPIC_UNRESOLVED = "DOC_TOPIC_UNRESOLVED"

#: An ordered teaching sequence names one topic twice. **Minted at B6**
#: (finding 9): the one constraint only an ordered form can carry, and
#: the reason ``TeachingSequence`` exists rather than a sorted set.
DOC_SEQUENCE_REPEATS = "DOC_SEQUENCE_REPEATS"

#: A journey teaches a concept before anything has taught, or declared as
#: already known, something that concept rests on. **Minted at E1.**
DOC_TEACHING_ORDER = "DOC_TEACHING_ORDER"

#: A journey step crosses an approval-class boundary without telling the
#: reader, or tells them about one it does not cross. **Minted at E1.**
DOC_APPROVAL_UNDECLARED = "DOC_APPROVAL_UNDECLARED"

#: An authority record contradicts itself: its class field disagrees with
#: the class segment of its id, its class is not a ranked one, or it
#: delegates a domain it cannot cite or hands one *up* the order.
#: **Minted at C2**, because C1 built ``authority_class`` to be compared
#: against the id and nothing had compared them yet.
DOC_AUTHORITY_MISDECLARED = "DOC_AUTHORITY_MISDECLARED"

#: Codes this milestone uses that the architecture plan's §11 table does
#: not name, with where each came from. Flagged for the C gate the way C1
#: flagged the ``sequence:`` id form: they are needed, they are used, and
#: they are not silently added to a frozen namespace.
MINTED_CODES: Mapping[str, str] = {
    DOC_SEQUENCE_REPEATS: (
        "B6 finding 9. The constraint only an ordered teaching form can "
        "carry; §11 predates the TeachingSequence record."
    ),
    DOC_TOPIC_UNRESOLVED: (
        "B6. §11 names the unresolved concept and the unresolved journey "
        "step; a catalog row covering an absent journey, or a concept "
        "citing an absent authority, is neither."
    ),
    DOC_AUTHORITY_MISDECLARED: (
        "C2. C1 repeats an authority's class on the record so a gate can "
        "catch a provider that mints the id and the class separately and "
        "lets them disagree. This is that gate, and §11 has no row for a "
        "record that contradicts itself rather than another record."
    ),
    DOC_TEACHING_ORDER: (
        "E1. §11's DOC_CONCEPT_UNRESOLVED is about a concept nothing "
        "addresses; this is about a concept the build addresses perfectly "
        "well and the reader meets too late. Every reference resolves and "
        "the journey still cannot be followed, which is a failure class "
        "§11's table has no row for."
    ),
    DOC_APPROVAL_UNDECLARED: (
        "E1. §11's DOC_SIDE_EFFECT_UNDECLARED keys on a *surface* whose "
        "own record does not say what calling it does. This keys on a "
        "*journey step*: the surface declares the approval honestly and "
        "the path walks a reader into it without saying so. The record "
        "that is wrong is a different one, so the code is a different one."
    ),
}

#: Failure classes over these same records that this module deliberately
#: does not implement, and what each is waiting for. The code naming its
#: own gaps is the point: a reader who expects a coverage gate here finds
#: out why it is not, rather than concluding the rule was forgotten.
DEFERRED_GATES: Mapping[str, str] = {
    "DOC_COVERAGE_UNMENTIONED": (
        "F. A catalog row may not claim a topic its document's prose never "
        "names (B6 finding 3). It needs the prose, and no renderer or prose "
        "reader exists before the F phase — resolution alone makes "
        "over-claiming free, which is exactly why the rule was raised."
    ),
    # DOC_CONCEPT_UNCOVERED and DOC_SURFACE_UNCOVERED left this map at C8:
    # they are armed by resolve.check_coverage, called from
    # application.build alongside validate_bundle (see resolve.FOLD_IN for
    # why the fold-in was rejected).
    # DOC_SIDE_EFFECT_UNDECLARED left this map at D5b: the D-phase surface
    # providers arrived, and check_side_effects below is the gate they made
    # answerable. What it waited for was never the comparison — it was a
    # corpus in which the question has a right answer to compare against.
    # DOC_JOURNEY_UNTESTED is deliberately *not* in this map, though this
    # repository's composition never fires it. The map is for gates that
    # do not exist; check_journeys implements this one and the battery
    # fires it. What is missing is a caller able to answer the question,
    # which is the EvidenceResolver seam E2's runner lands behind — and
    # whether the question is asked at all is a release-mode policy
    # (architecture §11.1), not a gap in this module.
    # DOC_VERSION_MISMATCH left this map at H1. What it was waiting for was
    # never the comparison — it was an artifact that states a version and a
    # channel, which is what the documentation manifest is. check_manifest
    # below is that gate, and it is where a provider's
    # Provenance.schema_version is finally compared against the model
    # version the build was written in: C1 gave the field its own name so a
    # lagging provider stays *visible*, and the manifest is where visible
    # becomes reported.
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Where a finding points
# ---------------------------------------------------------------------------


def records_of(bundle: DocsBundle) -> tuple[DocsRecord, ...]:
    """Every record in ``bundle``, group by group, typed as the union.

    Reaching the groups by name would hand a type checker ``Any`` and
    quietly disable every check downstream of the walk, so the six fields
    are named. ``providers.GROUP_NAMES`` holds the same six for the
    places that need the *names*.
    """
    return (
        *bundle.authorities,
        *bundle.concepts,
        *bundle.surfaces,
        *bundle.journeys,
        *bundle.sequences,
        *bundle.documents,
    )


def location_of(record: DocsRecord) -> str:
    """The source ``record`` itself names, or "" when it names none.

    Not a guess and not a search: each record type is asked for the
    location it actually carries. A surface knows the file its provider
    read; a catalog row knows where its prose is, which is not always the
    file it is about (C1's ``prose_locator``, B6 finding 2); an authority
    knows its source and section. The three authored types name nothing,
    and an empty location is the honest answer for them.
    """
    if isinstance(record, SurfaceRecord):
        return record.provenance.source
    if isinstance(record, DocumentRecord):
        return record.prose_locator or record.canonical_source
    if isinstance(record, AuthorityRef):
        if record.section:
            return f"{record.source}#{record.section}"
        return record.source
    return ""


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Reference:
    """One record citing another id, and where the citation is written.

    ``edge`` is the architecture plan's §6.7 vocabulary; ``field`` is the
    place on the record, indexed, so a finding can say *which* of five
    governing authorities does not resolve.
    """

    source_id: str
    source_group: str
    field: str
    edge: str
    target: str
    location: str


def references(bundle: DocsBundle) -> tuple[Reference, ...]:
    """Every edge in ``bundle``, in a stable order.

    The §6.7 edge set, restricted to the edges ``@1`` can actually carry:
    ``concept --governed_by--> authority``, ``concept
    --illustrated_by--> example``, ``surface --implemented_by-->
    component``, ``surface --governed_by--> authority``, ``journey
    --uses--> surface`` (steps and recovery paths both), ``journey
    --teaches--> concept``, ``journey --requires--> concept``, ``journey
    --demonstrated_by--> example``, ``sequence --teaches--> topic``,
    ``document --covers--> anything`` and ``document --governed_by-->
    authority``.

    The three journey edges arrived at E1 with the fields that carry
    them, which closes B4's deferral-list entries for ``journey
    --teaches/requires--> concept`` and ``journey --demonstrated_by-->
    example``. The rest of §6.7 waits for the records that carry it:
    ``generated_as`` and ``mirrors`` need the artifact record nothing
    produces yet, and ``supersedes`` needs the supersession form.
    """
    found: list[Reference] = []

    def cite(record: DocsRecord, group: str, field: str, edge: str, target: str) -> None:
        found.append(
            Reference(
                source_id=record.id,
                source_group=group,
                field=field,
                edge=edge,
                target=target,
                location=location_of(record),
            )
        )

    for concept in bundle.concepts:
        for index, authority in enumerate(concept.governed_by):
            cite(concept, "concepts", f"governed_by[{index}]", "governed_by", authority)
        for index, example in enumerate(concept.examples):
            cite(concept, "concepts", f"examples[{index}].id", "illustrated_by", example.id)

    for surface in bundle.surfaces:
        for index, component in enumerate(surface.component_refs):
            cite(surface, "surfaces", f"component_refs[{index}]", "implemented_by", component)
        for index, authority in enumerate(surface.governed_by):
            cite(surface, "surfaces", f"governed_by[{index}]", "governed_by", authority)

    for journey in bundle.journeys:
        for index, step in enumerate(journey.steps):
            cite(journey, "journeys", f"steps[{index}].surface", "uses", step.surface)
        for index, path in enumerate(journey.recovery_paths):
            cite(
                journey,
                "journeys",
                f"recovery_paths[{index}].next_surface",
                "uses",
                path.next_surface,
            )
        for index, concept_id in enumerate(journey.concepts_taught):
            cite(journey, "journeys", f"concepts_taught[{index}]", "teaches", concept_id)
        for index, concept_id in enumerate(journey.concepts_required):
            cite(
                journey, "journeys", f"concepts_required[{index}]", "requires", concept_id
            )
        for index, evidence in enumerate(journey.evidence):
            cite(
                journey,
                "journeys",
                f"evidence[{index}].id",
                "demonstrated_by",
                evidence.id,
            )

    for sequence in bundle.sequences:
        for index, teaching in enumerate(sequence.steps):
            cite(sequence, "sequences", f"steps[{index}].topic", "teaches", teaching.topic)

    for document in bundle.documents:
        for index, covered in enumerate(document.covers):
            cite(document, "documents", f"covers[{index}]", "covers", covered)
        for index, authority in enumerate(document.governed_by):
            cite(document, "documents", f"governed_by[{index}]", "governed_by", authority)

    return tuple(sorted(found))


@dataclass(frozen=True)
class ReferenceIndex:
    """What this build addresses, what cites what, and what cites that.

    ``ids`` is the whole universe, and it is deliberately the *caller's*
    universe rather than the bundle's. Two of the §6.7 edge targets are
    not bundle records in ``@1`` — a registered component and a
    registered example both live outside the documentation model — so the
    caller passes them in as ``external_ids``. A target absent from the
    union is unresolved, and this module does not guess which absences
    were expected: an empty ``external_ids`` means every component
    reference is unresolved, which is the truthful answer when nobody has
    said what components exist.
    """

    ids: frozenset[str]
    references: tuple[Reference, ...]
    referrers_by_target: Mapping[str, tuple[str, ...]]

    @classmethod
    def of(cls, bundle: DocsBundle, external_ids: Iterable[str] = ()) -> ReferenceIndex:
        """Index ``bundle``, plus any ids the caller vouches for."""
        known = {normalize_id(record.id) for record in records_of(bundle)}
        known.update(normalize_id(identifier) for identifier in external_ids)
        found = references(bundle)
        reverse: dict[str, set[str]] = {}
        for reference in found:
            reverse.setdefault(normalize_id(reference.target), set()).add(reference.source_id)
        return cls(
            ids=frozenset(known),
            references=found,
            referrers_by_target={
                target: tuple(sorted(citers)) for target, citers in sorted(reverse.items())
            },
        )

    def knows(self, identifier: str) -> bool:
        """Is ``identifier`` something this build addresses?"""
        return normalize_id(identifier) in self.ids

    def referrers(self, target: str) -> tuple[str, ...]:
        """The ids of the records that cite ``target`` directly, sorted."""
        return self.referrers_by_target.get(normalize_id(target), ())

    def impact_of(self, target: str) -> tuple[str, ...]:
        """Everything a change to ``target`` reaches, however indirectly.

        The reverse walk architecture plan §11.2 asks for: a changed
        authority reaches the concepts and surfaces that cite it, then
        the journeys and catalog rows that cite *those*. Cycles are
        walked once and ``target`` itself is not in its own impact set,
        so a review list never contains the thing being reviewed.
        """
        start = normalize_id(target)
        reached: set[str] = set()
        queue = [start]
        while queue:
            current = queue.pop()
            for citer in self.referrers(current):
                if citer not in reached:
                    reached.add(citer)
                    queue.append(citer)
        reached.discard(start)
        return tuple(sorted(reached))


def _unresolved_code(reference: Reference) -> str:
    """The diagnostic an unresolved ``reference`` raises.

    Ordered so the architecture plan's own wording decides first: §11
    keys ``DOC_JOURNEY_UNRESOLVED`` on the citing record being a journey
    and ``DOC_SURFACE_UNBOUND`` on a surface failing to reach a
    component, and only then does the target's own class decide.
    """
    if reference.source_group == "journeys":
        return DOC_JOURNEY_UNRESOLVED
    if reference.edge == "implemented_by":
        return DOC_SURFACE_UNBOUND
    if reference.target.startswith("concept:"):
        return DOC_CONCEPT_UNRESOLVED
    return DOC_TOPIC_UNRESOLVED


#: What each journey edge is a reference *to*, in the words §11 uses for
#: ``DOC_JOURNEY_UNRESOLVED`` — "a missing surface, example, diagnostic or
#: authority". A journey names three of those four by id and the fourth by
#: a failure's own name, so a finding that only said "does not resolve"
#: would leave an author guessing which kind of thing they had misspelled.
#: The diagnostic class is not here because it is not an edge: see
#: :func:`check_journeys`, which reads ``RecoveryPath.when``.
JOURNEY_REFERENCE_CLASSES: Mapping[str, str] = {
    "uses": (
        "a served capability — a cli:, mcp:, rest:, studi0: or python: id. "
        "A journey step and a recovery path both name one"
    ),
    "teaches": (
        "a concept — the ideas this path leaves a reader with, in the "
        "order they are met"
    ),
    "requires": (
        "a concept — what the reader is assumed to know before step one"
    ),
    "demonstrated_by": (
        "a registered runnable example or transcript fixture, which is the "
        "evidence that this path still works"
    ),
}


def _unresolved(reference: Reference, index: ReferenceIndex) -> Finding | None:
    """One finding if ``reference`` resolves to nothing, else ``None``.

    A malformed target and a well-formed absent one get the same code and
    different remediations, because the fixes are different: one is a
    mistake in the *form* of the id and the other is a mistake in the id
    or a thing nobody has written yet. A journey's remediation also names
    the class of thing the edge points at
    (:data:`JOURNEY_REFERENCE_CLASSES`), because a journey is the one
    record type that cites four different classes and §11's own wording
    for its code names all four.
    """
    if index.knows(reference.target):
        return None
    expected = (
        JOURNEY_REFERENCE_CLASSES.get(reference.edge, "")
        if reference.source_group == "journeys"
        else ""
    )
    if id_form(reference.target) is None:
        remediation = (
            f"{reference.target!r} matches no id form the model addresses "
            f"things by, so nothing could ever resolve it. Check the form "
            f"first — a flat component name and a doubled colon after "
            f"'example' are the two that look right and are not."
        )
    else:
        remediation = (
            f"either {reference.source_id} names the wrong id, or "
            f"{reference.target} is a thing no provider produced. If it "
            f"should exist, the provider that owns it has to emit it; if it "
            f"lives outside the documentation model, the composition has to "
            f"be given its id."
        )
    if expected:
        remediation = f"{remediation} At {reference.field} the model expects {expected}."
    return Finding(
        code=_unresolved_code(reference),
        location=reference.location,
        message=(
            f"{reference.source_id} {reference.edge} {reference.target} "
            f"(at {reference.field}), which this build does not address"
        ),
        remediation=remediation,
    )


def check_references(index: ReferenceIndex) -> list[Finding]:
    """Every edge target resolves (architecture plan §6.7).

    The code is keyed on what is citing rather than on what is missing —
    ``DOC_JOURNEY_UNRESOLVED``, ``DOC_SURFACE_UNBOUND``,
    ``DOC_CONCEPT_UNRESOLVED`` or ``DOC_TOPIC_UNRESOLVED``, decided by
    :func:`_unresolved_code` — because an author fixing a dangling edge
    goes to the record that made the claim, not to the id that answers
    nothing.
    """
    findings = [_unresolved(reference, index) for reference in index.references]
    return [finding for finding in findings if finding is not None]


# ---------------------------------------------------------------------------
# The surface-to-component axes
# ---------------------------------------------------------------------------


def check_surface_binding(bundle: DocsBundle) -> list[Finding]:
    """Every served capability is bound, or says in writing why it is not.

    ``component_refs`` and ``manual_exception`` are independent axes (B7
    register row 4, C1's ``SurfaceRecord``): a surface may map to
    registered components *and* carry hand-transcribed facts. What no
    surface may do is neither — a capability that reaches no component
    and offers no written reason is unbound, and ``DOC_SURFACE_UNBOUND``
    is §11's name for that.

    Whether the components it names exist is the reference resolver's
    question, not this one.
    """
    findings: list[Finding] = []
    for surface in bundle.surfaces:
        if surface.component_refs or surface.manual_exception.strip():
            continue
        findings.append(
            Finding(
                code=DOC_SURFACE_UNBOUND,
                location=location_of(surface),
                message=(
                    f"{surface.id} reaches no registered component and gives "
                    f"no reason, so nothing connects what it says to what runs"
                ),
                remediation=(
                    "name the components that implement it in component_refs, "
                    "or write a manual exception saying why its facts were "
                    "transcribed by hand. The two are independent — a surface "
                    "may honestly carry both."
                ),
            )
        )
    return findings


# ---------------------------------------------------------------------------
# The side-effect axis
# ---------------------------------------------------------------------------

#: Every word a surface may use to say what calling it does to the world
#: (architecture plan §6.3).
#:
#: ``none`` is an **answer**, not an absence. That single decision is what
#: makes this gate possible at all: a surface that genuinely changes
#: nothing says so in a word, which leaves the empty tuple free to mean
#: the one thing it should mean — nobody has said. Three providers had
#: already written that convention down before this gate existed
#: (``providers_cli._effects`` refuses an empty classification in as many
#: words), and the model adopts theirs rather than minting a second one.
#:
#: Held here rather than in any one provider because a provider-local copy
#: can only police its own output. Core's records are emitted by a module
#: that has no reason to import the CLI's vocabulary, and a word core
#: invented would be indistinguishable from a declared one to every gate
#: downstream.
SIDE_EFFECT_WORDS: frozenset[str] = frozenset(
    {
        "approval",
        "credential",
        "network",
        "none",
        "read",
        "subprocess",
        "write",
    }
)

#: Each channel this model knows, and whether a caller reaches the product
#: *through* it — which is what decides whether "what does calling this do"
#: is even a question with an answer.
#:
#: ``True`` is a serving mechanism: a person types a command, an agent
#: calls a tool or reads a resource or asks for a prompt, a caller imports
#: and calls a name, a client requests a route, a browser requests a page.
#: Every one of those is an invocation, and every invocation does something
#: to the world even if the something is nothing.
#:
#: ``False`` is a record that *names a thing* rather than a way to reach
#: one. D2 minted both of them deliberately and said why — "a diagnostic is
#: not served over a mechanism, it is emitted by all of them" — and a
#: configuration key is read by the loader rather than called by anybody.
#: Neither is in §6.3's transport list, and neither should be. They answer
#: ``none``, and this table is what holds them to it: a config key that
#: claimed to write would have contradicted its own classification, and
#: before this table nothing could have noticed.
#:
#: §6.3 also names ``artifact``, and it is deliberately **absent**. Nothing
#: emits an artifact surface yet, so classifying one now would be a guess
#: recorded as a decision. An unclassified channel is a finding rather than
#: a default, so the first provider to emit one is asked the question
#: instead of inheriting somebody's answer.
CHANNEL_EFFECTS: Mapping[str, bool] = {
    "cli": True,
    "config": False,
    "diagnostic": False,
    "mcp_prompt": True,
    "mcp_resource": True,
    "mcp_tool": True,
    "python": True,
    "rest": True,
    "studi0": True,
}


def _allowance_key(surface: SurfaceRecord) -> tuple[str, str]:
    """What an allowance is written against: the reading, and the channel.

    Not the surface id. An allowance names a *source* that cannot answer
    the question — an SDK listing that exposes no annotation, say — and a
    source's inability is a property of the reading, not of each of the
    twelve records it produced. Keyed per id, the same fact would be
    restated twelve times and could rot in eleven of them.
    """
    return (surface.provenance.adapter_id, surface.channel)


def check_side_effects(
    bundle: DocsBundle,
    allowances: Mapping[tuple[str, str], str] | None = None,
) -> list[Finding]:
    """Every surface says what calling it does, or a named source says why not.

    Four failures, all of which end with a reader unable to find out
    whether running something is safe:

    * **undeclared** — a surface's ``side_effects`` is empty and no
      allowance covers its source. ``DOC_SIDE_EFFECT_UNDECLARED``;
    * **unclassified channel** — the surface is served on a channel
      :data:`CHANNEL_EFFECTS` does not name, so nothing has said whether
      the question even applies to it. Also
      ``DOC_SIDE_EFFECT_UNDECLARED``, because the honest reading of an
      unclassified channel is that its surfaces are unclassified too;
    * **a word outside the vocabulary, or ``none`` mixed with one** — a
      word no gate recognizes reads as a class of effect nobody has
      thought about, and "none and write" is not a partial answer but a
      contradiction;
    * **a described channel claiming an effect** — a channel classified
      ``False`` names a thing rather than a way to reach one, so a
      surface on it that claims to write has outgrown its classification.

    ``allowances`` is the caller's, exactly as the floors are (see
    :func:`check_floors`): which sources may be silent is a fact about a
    particular repository's providers reading particular packages, and the
    model has no business asserting one. Each entry maps
    ``(adapter_id, channel)`` to the written reason.

    **An allowance nothing uses is itself a finding** — ``DOC_GATE_VACUOUS``,
    the same rule a floor naming an absent provider gets. This is the half
    that stops an allowance from outliving the gap it excuses: the day the
    source it names starts declaring, the allowance stops matching, and the
    build says so rather than quietly carrying a permission nobody needs.
    """
    written = dict(allowances or {})
    findings: list[Finding] = []
    used: set[tuple[str, str]] = set()

    for surface in bundle.surfaces:
        location = location_of(surface)
        invocable = CHANNEL_EFFECTS.get(surface.channel)
        key = _allowance_key(surface)

        if invocable is None:
            findings.append(
                Finding(
                    code=DOC_SIDE_EFFECT_UNDECLARED,
                    location=location,
                    message=(
                        f"{surface.id} is served on the channel "
                        f"{surface.channel!r}, which nothing has classified, so "
                        f"there is no saying whether calling it can change "
                        f"anything"
                    ),
                    remediation=(
                        "add the channel to validate.CHANNEL_EFFECTS with True "
                        "if a caller reaches the product through it and False "
                        "if the record names a thing rather than a way to reach "
                        "one. A channel left out defaults to nothing on "
                        "purpose: the answer is a decision, and a decision "
                        "nobody made is not the same as a safe one."
                    ),
                )
            )
            continue

        if not surface.side_effects:
            reason = written.get(key)
            if reason is None:
                findings.append(
                    Finding(
                        code=DOC_SIDE_EFFECT_UNDECLARED,
                        location=location,
                        message=(
                            f"{surface.id} is served and says nothing about what "
                            f"calling it does to the world"
                        ),
                        remediation=(
                            "give it the words that describe its effects — "
                            f"{', '.join(sorted(SIDE_EFFECT_WORDS))} — in the "
                            "provider that emits it. A surface that genuinely "
                            "changes nothing is written as ('none',): the empty "
                            "tuple is the unanswered question, which is why it "
                            "is the one thing this gate refuses. If the source "
                            "truly cannot say, allow "
                            f"{key} where the composition is defined and write "
                            "down why."
                        ),
                    )
                )
            else:
                used.add(key)
            continue

        unknown = sorted(set(surface.side_effects) - SIDE_EFFECT_WORDS)
        if unknown:
            findings.append(
                Finding(
                    code=DOC_SIDE_EFFECT_UNDECLARED,
                    location=location,
                    message=(
                        f"{surface.id} declares {unknown}, which no word of the "
                        f"side-effect vocabulary means"
                    ),
                    remediation=(
                        f"the words are: {', '.join(sorted(SIDE_EFFECT_WORDS))}. "
                        "A word outside them is worse than no word at all, "
                        "because it reads to every later gate as a classified "
                        "surface."
                    ),
                )
            )
        elif "none" in surface.side_effects and len(surface.side_effects) > 1:
            findings.append(
                Finding(
                    code=DOC_SIDE_EFFECT_UNDECLARED,
                    location=location,
                    message=(
                        f"{surface.id} declares {list(surface.side_effects)}, "
                        f"which says it changes nothing and also says what it "
                        f"changes"
                    ),
                    remediation=(
                        "drop 'none' and keep the words that are true, or keep "
                        "'none' alone if it really is. 'none' is the whole "
                        "answer or it is not part of one."
                    ),
                )
            )

        if not invocable and tuple(surface.side_effects) != ("none",):
            findings.append(
                Finding(
                    code=DOC_SIDE_EFFECT_UNDECLARED,
                    location=location,
                    message=(
                        f"{surface.id} is on {surface.channel!r}, a channel that "
                        f"names a thing rather than a way to reach one, and it "
                        f"declares {list(surface.side_effects)}"
                    ),
                    remediation=(
                        "either the surface is genuinely invoked, and the "
                        "channel belongs in validate.CHANNEL_EFFECTS as True, "
                        "or it is not, and its effects are 'none' — whatever it "
                        "describes has its effects on the surface that is "
                        "actually called."
                    ),
                )
            )

    for key in sorted(set(written) - used):
        findings.append(
            Finding(
                code=DOC_GATE_VACUOUS,
                location="",
                message=(
                    f"an allowance lets {key[0]!r} say nothing about the side "
                    f"effects of its {key[1]!r} surfaces, and no surface in this "
                    f"build used it"
                ),
                remediation=(
                    "either the source now declares its effects and the "
                    "allowance should go with the gap it excused, or the "
                    "reading has stopped producing that family entirely. An "
                    "allowance nobody uses is a standing permission for a "
                    "silence that may no longer exist, which is exactly how a "
                    "temporary exception becomes a permanent one."
                ),
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Provenance completeness
# ---------------------------------------------------------------------------


def _provenance_findings(record_id: str, provenance: Provenance, location: str) -> list[Finding]:
    """What is missing from one record's account of where it came from."""
    missing = sorted(
        name
        for name in ("adapter_id", "schema_version", "source", "source_sha256")
        if not getattr(provenance, name).strip()
    )
    findings: list[Finding] = []
    if missing:
        findings.append(
            Finding(
                code=DOC_PROVENANCE_MISSING,
                location=location,
                message=(
                    f"{record_id} carries no {', '.join(missing)}, so it "
                    f"cannot be traced back to what it was read from"
                ),
                remediation=(
                    "the provider that emitted it has to stamp all four: its "
                    "adapter id, the schema version it emitted against, the "
                    "source identity, and that source's sha256. Provenance "
                    "survives every projection (SDA-INV-10), so a record "
                    "without it cannot enter a snapshot."
                ),
            )
        )
    digest = provenance.source_sha256.strip()
    if digest and not _SHA256.match(digest):
        findings.append(
            Finding(
                code=DOC_PROVENANCE_MISSING,
                location=location,
                message=(
                    f"{record_id} names {digest!r} as its source digest, which "
                    f"is not a sha256"
                ),
                remediation=(
                    "write the full sha256 of the source's UTF-8 bytes with "
                    "line feeds — 64 lowercase hex characters, equal to what "
                    "sha256sum reports for the tracked file. A placeholder "
                    "here reads as a real digest to every later gate."
                ),
            )
        )
    return findings


def check_provenance(
    bundle: DocsBundle, results: Sequence[ProviderResult] = ()
) -> list[Finding]:
    """Every record can be traced to a source, a schema and a digest.

    ``DOC_PROVENANCE_MISSING``.
    Both halves are checked because they cover different record sets. The
    bundle's surfaces carry provenance in the model itself, and a bundle
    read back from a committed file is all a checker has. The provider
    results carry provenance for *every* record, authored ones included,
    and they also still hold the records that merged away — a record with
    no provenance that lost a merge is still a provider that has to be
    fixed.

    The two sets overlap on the surfaces, so each ``(record, provenance)``
    pair is asked once. One mistake is one finding even for a caller that
    does not run this through :func:`validate_bundle`.
    """
    asked: set[tuple[str, Provenance]] = set()
    findings: list[Finding] = []

    def ask(record: DocsRecord, provenance: Provenance) -> None:
        if (record.id, provenance) in asked:
            return
        asked.add((record.id, provenance))
        findings.extend(_provenance_findings(record.id, provenance, location_of(record)))

    for surface in bundle.surfaces:
        ask(surface, surface.provenance)
    for result in results:
        for item in result.records:
            ask(item.record, item.provenance)
    return findings


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------


def _rank(authority_class: str) -> int:
    """Where a class sits in the repository order; unranked classes last."""
    try:
        return AUTHORITY_ORDER.index(authority_class)
    except ValueError:
        return len(AUTHORITY_ORDER)


def check_authority_records(bundle: DocsBundle) -> list[Finding]:
    """No authority record contradicts itself.

    ``DOC_AUTHORITY_MISDECLARED``, in four ways, all of which make the
    ranking that governs every other comparison unreliable:

    * its ``authority_class`` is not one of the ranked classes, so it has
      no rank;
    * its class disagrees with the class segment of its own id — the
      disagreement C1 put the repeated field there to catch;
    * a delegation names an unranked class, or names one at least as
      strong as the delegator. Delegation is a stronger authority handing
      a domain *down* (plan §5); handing it up is a claim the order
      already refuses;
    * a delegation has no domain or no ``stated_in``. A delegation
      nobody can cite is an assumption, and this model does not carry
      assumptions.
    """
    findings: list[Finding] = []
    for authority in bundle.authorities:
        location = location_of(authority)
        rank = _rank(authority.authority_class)
        if rank == len(AUTHORITY_ORDER):
            findings.append(
                Finding(
                    code=DOC_AUTHORITY_MISDECLARED,
                    location=location,
                    message=(
                        f"{authority.id} is class {authority.authority_class!r}, "
                        f"which is not a ranked authority class, so nothing can "
                        f"compare it"
                    ),
                    remediation=(
                        f"use one of: {', '.join(AUTHORITY_ORDER)}, strongest "
                        f"first."
                    ),
                )
            )
        segment = authority.id.partition(":")[2].partition("/")[0]
        if segment and segment != authority.authority_class:
            findings.append(
                Finding(
                    code=DOC_AUTHORITY_MISDECLARED,
                    location=location,
                    message=(
                        f"{authority.id} calls itself class "
                        f"{authority.authority_class!r} while its id says "
                        f"{segment!r}"
                    ),
                    remediation=(
                        "the id and the class are one fact written twice; make "
                        "them agree. Whichever is wrong, a record that ranks "
                        "differently depending on which field is read cannot "
                        "govern anything."
                    ),
                )
            )
        for delegation in authority.delegates:
            findings.extend(_delegation_findings(authority, delegation, location, rank))
    return findings


def _delegation_findings(
    authority: AuthorityRef,
    delegation: AuthorityDelegation,
    location: str,
    rank: int,
) -> list[Finding]:
    """What is wrong with one recorded delegation, if anything."""
    domain = delegation.domain
    to_class = delegation.to_class
    findings: list[Finding] = []
    if not domain.strip() or not delegation.stated_in.strip():
        findings.append(
            Finding(
                code=DOC_AUTHORITY_MISDECLARED,
                location=location,
                message=(
                    f"{authority.id} delegates to {to_class!r} without saying "
                    f"which domain, or where it says so"
                ),
                remediation=(
                    "a delegation names the domain it hands over and the "
                    "section of this authority's own source that hands it "
                    "over. A delegation nobody can cite is an assumption."
                ),
            )
        )
    delegate_rank = _rank(to_class)
    if delegate_rank <= rank:
        stronger = "an unranked class" if delegate_rank == len(AUTHORITY_ORDER) else "up"
        findings.append(
            Finding(
                code=DOC_AUTHORITY_MISDECLARED,
                location=location,
                message=(
                    f"{authority.id} (class {authority.authority_class!r}) "
                    f"delegates {domain!r} to {to_class!r}, which is {stronger} "
                    f"the order rather than down it"
                ),
                remediation=(
                    "delegation is a stronger authority handing one domain to "
                    "a weaker one in its own words. A weaker authority cannot "
                    "hand anything to a stronger one — the order already gives "
                    "the stronger one the answer."
                ),
            )
        )
    return findings


@dataclass(frozen=True)
class AuthorityClaim:
    """A question for the authority comparison: this record, this domain.

    The domain has to come from the caller. No record in ``@1`` says what
    domain its claim is in, and inventing one from a field would be a
    guess about the one thing plan §5's delegation rule turns on.
    """

    record_id: str
    domain: str


@dataclass(frozen=True)
class AuthorityDecision:
    """Who governs one claim, how it got there, and what is unanswerable.

    ``governing`` holds more than one id only where the question has more
    than one answer: an undomained question several sections co-govern
    (no finding), or a domain-scoped question two equal-ranked
    authorities both claim (a finding). ``delegated_from`` is the chain
    that handed the domain down, strongest first, so a reader can see
    *why* a weaker authority won.
    """

    record_id: str
    domain: str
    governing: tuple[str, ...]
    delegated_from: tuple[str, ...]
    findings: tuple[Finding, ...]


def governing_authority(
    *,
    record_id: str,
    cited: Sequence[str],
    authorities: Mapping[str, AuthorityRef],
    domain: str = "",
    location: str = "",
) -> AuthorityDecision:
    """Which cited authority governs ``record_id``, per plan §5.

    The repository order decides, strongest first, with one ratified
    exception: where the strongest cited authority **says in its own
    source** that a domain belongs to a weaker class, and an authority of
    that class is also cited, the weaker one wins for that domain and no
    conflict is reported. FR-DSL-1 is the case — the product requirements
    name the versioned specification the normative language authority and
    decline to duplicate it — and the delegation is written on the
    authority record so it can be cited rather than assumed.

    **Two questions, deliberately different.** With no ``domain``, this
    answers "what governs this record", and several sections of one
    document legitimately co-govern a concept: every authority at the
    strongest cited rank is returned and nothing is reported. With a
    ``domain``, this answers "who decides *this*", which needs one
    answer; two authorities at the strongest rank and no delegation
    between them is the undeclared equal-rank case plan §5 refuses, and
    it reports ``DOC_AUTHORITY_CONFLICT``.

    An id that names no known authority is skipped here. That absence is
    an unresolved reference and :func:`check_references` reports it; two
    findings for one mistake would be noise.
    """
    known = [
        authorities[identifier]
        for identifier in sorted(set(cited))
        if identifier in authorities
    ]
    if not known:
        return AuthorityDecision(record_id, domain, (), (), ())

    best = min(_rank(item.authority_class) for item in known)
    top = sorted(
        (item for item in known if _rank(item.authority_class) == best),
        key=lambda item: item.id,
    )
    if not domain:
        return AuthorityDecision(record_id, domain, tuple(item.id for item in top), (), ())
    if len(top) > 1:
        return AuthorityDecision(
            record_id,
            domain,
            tuple(item.id for item in top),
            (),
            (_conflict(record_id, domain, top, location, "rank"),),
        )
    return _follow_delegation(record_id, domain, top[0], known, location)


def _conflict(
    record_id: str,
    domain: str,
    contenders: Sequence[AuthorityRef],
    location: str,
    reason: str,
) -> Finding:
    """One ``DOC_AUTHORITY_CONFLICT``, naming every contender."""
    names = ", ".join(item.id for item in contenders)
    if reason == "rank":
        message = (
            f"{record_id} cites {names} for {domain!r}; they rank equally and "
            f"none of them delegates the domain, so nothing decides between them"
        )
        remediation = (
            "record the delegation on whichever authority hands the domain "
            "over, citing the section that says so, or drop the citation that "
            "does not govern this claim. An equal-rank disagreement is "
            "reported, never resolved silently."
        )
    elif reason == "split":
        message = (
            f"{names} hands {domain!r} to more than one class at once, so "
            f"{record_id} has no single delegate to fall to"
        )
        remediation = (
            "one domain goes to one class. Split the domain into the parts "
            "that really go to different authorities, and name each part."
        )
    else:
        message = (
            f"{record_id} cites {names} for {domain!r} and their delegations "
            f"lead in a circle, so none of them is the one that decides"
        )
        remediation = (
            "two authorities each handing the same domain to the other leaves "
            "nobody holding it. One of the two delegations has to go."
        )
    return Finding(
        code=DOC_AUTHORITY_CONFLICT,
        location=location,
        message=message,
        remediation=remediation,
    )


def _follow_delegation(
    record_id: str,
    domain: str,
    start: AuthorityRef,
    known: Sequence[AuthorityRef],
    location: str,
) -> AuthorityDecision:
    """Hand ``domain`` down the chain of delegations, refusing a circle."""
    chain: list[str] = []
    seen = {start.id}
    current = start
    while True:
        handed = [item for item in current.delegates if item.domain == domain]
        if not handed:
            break
        if len({item.to_class for item in handed}) > 1:
            return AuthorityDecision(
                record_id,
                domain,
                (current.id,),
                tuple(chain),
                (_conflict(record_id, domain, [current], location, "split"),),
            )
        candidates = sorted(
            (item for item in known if item.authority_class == handed[0].to_class),
            key=lambda item: item.id,
        )
        if not candidates:
            # The delegate is not cited. The delegator's own citation
            # stands; requiring the delegate to be cited is a coverage
            # rule, and coverage is not this milestone's.
            break
        if len(candidates) > 1:
            return AuthorityDecision(
                record_id,
                domain,
                tuple(item.id for item in candidates),
                tuple(chain),
                (_conflict(record_id, domain, candidates, location, "rank"),),
            )
        nxt = candidates[0]
        if nxt.id in seen:
            circle = sorted({*seen, nxt.id})
            contenders = [item for item in known if item.id in circle]
            return AuthorityDecision(
                record_id,
                domain,
                tuple(circle),
                tuple(chain),
                (_conflict(record_id, domain, contenders, location, "circle"),),
            )
        chain.append(current.id)
        seen.add(nxt.id)
        current = nxt
    return AuthorityDecision(record_id, domain, (current.id,), tuple(chain), ())


# ---------------------------------------------------------------------------
# Anti-vacuity floors
# ---------------------------------------------------------------------------


def check_floors(
    results: Sequence[ProviderResult],
    floors: Mapping[tuple[str, str], int],
) -> list[Finding]:
    """No provider quietly stopped producing (``DOC_GATE_VACUOUS``).

    The floors are the caller's, never this module's. A floor is a claim
    about a particular provider reading a particular tree — "core emits
    at least sixty-one components" is true of this repository and of
    nothing else — so hard-coding one here would make the model lie about
    someone else's build. B3 derived every floor it used from a pin the
    repository already keeps; that is the shape a caller should follow.

    A floor naming a provider that did not run is itself a finding. The
    empty-provider failure this gate exists to catch looks exactly like a
    provider that was never registered.
    """
    unknown = sorted({group for _, group in floors if group not in GROUP_NAMES})
    if unknown:
        raise DocsModelError(
            f"a floor names {unknown}, which is not a bundle group. The groups "
            f"are: {', '.join(GROUP_NAMES)}."
        )
    counted = {result.provider_id: result.counts() for result in results}
    findings: list[Finding] = []
    for (provider_id, group), floor in sorted(floors.items()):
        if provider_id not in counted:
            findings.append(
                Finding(
                    code=DOC_GATE_VACUOUS,
                    location="",
                    message=(
                        f"a floor expects at least {floor} {group} from "
                        f"provider {provider_id!r}, which did not run"
                    ),
                    remediation=(
                        f"register {provider_id!r} with the composition, or "
                        f"drop the floor. A provider that never ran and a "
                        f"provider that produced nothing are the same failure."
                    ),
                )
            )
            continue
        observed = counted[provider_id][group]
        if observed < floor:
            findings.append(
                Finding(
                    code=DOC_GATE_VACUOUS,
                    location="",
                    message=(
                        f"provider {provider_id!r} produced {observed} {group} "
                        f"and its floor is {floor}"
                    ),
                    remediation=(
                        "either the source it reads has changed shape and the "
                        "provider has stopped seeing it, or the floor is stale. "
                        "Check the provider first: a gate that resolves empty "
                        "passes everything downstream of it."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Teaching sequences
# ---------------------------------------------------------------------------


def check_sequences(bundle: DocsBundle, index: ReferenceIndex) -> list[Finding]:
    """Every step of every ordered sequence resolves, and none repeats.

    ``DOC_SEQUENCE_REPEATS`` for a repeated step, ``DOC_GATE_VACUOUS`` for
    a sequence with nothing in it, and whichever resolution code
    :func:`_unresolved_code` keys for a step that names nothing.
    The repeat rule is the whole reason the record type exists (B6
    finding 9). A catalog row's ``covers`` is a sorted set, so it throws
    order away and cannot say a topic twice; an ordered form can, and a
    teaching order that teaches one topic twice has lost its order
    somewhere.

    Resolution is re-checked here rather than left to
    :func:`check_references` so this gate is complete on its own — the
    aggregate drops the exact repeat.
    """
    findings: list[Finding] = []
    by_sequence: dict[str, list[Reference]] = {}
    for reference in index.references:
        if reference.source_group == "sequences":
            by_sequence.setdefault(reference.source_id, []).append(reference)

    for sequence in bundle.sequences:
        if not sequence.steps:
            findings.append(
                Finding(
                    code=DOC_GATE_VACUOUS,
                    location=location_of(sequence),
                    message=f"{sequence.id} teaches nothing; it has no steps",
                    remediation=(
                        "give it the topics it teaches, in the order they are "
                        "taught, or remove it. An empty sequence passes every "
                        "check it is subject to and teaches no one."
                    ),
                )
            )
        for reference in by_sequence.get(sequence.id, ()):
            finding = _unresolved(reference, index)
            if finding is not None:
                findings.append(finding)
        seen: set[str] = set()
        for position, step in enumerate(sequence.steps, start=1):
            topic = normalize_id(step.topic)
            if topic in seen:
                findings.append(
                    Finding(
                        code=DOC_SEQUENCE_REPEATS,
                        location=location_of(sequence),
                        message=(
                            f"{sequence.id} teaches {step.topic} again at step "
                            f"{position}; a teaching order names each topic once"
                        ),
                        remediation=(
                            "keep the position where the topic is actually "
                            "taught and drop the other. If the second mention "
                            "is a different lesson about the same topic, it is "
                            "a different topic and needs its own record."
                        ),
                    )
                )
            seen.add(topic)
    return findings


# ---------------------------------------------------------------------------
# Journeys
# ---------------------------------------------------------------------------

#: The side-effect word that means a person is asked before anything
#: happens. One of :data:`SIDE_EFFECT_WORDS`, named here because the
#: journey gate reads it and a second spelling of it would silently stop
#: the gate firing.
APPROVAL_EFFECT = "approval"

#: The concept relation a teaching order is checked against. The
#: vocabulary itself is closed and lives with the loader that reads it
#: (``providers_concepts.RELATIONS``, whose entry for this word says in as
#: many words that it "is the edge a teaching order is built from"). The
#: word is repeated here rather than imported so this module keeps its
#: import discipline — it depends on the model, never on a provider — and
#: a test pins the two spellings equal so the repetition cannot drift.
TEACHING_PREREQUISITE = "requires"

#: What a caller hands :func:`check_journeys` so that
#: ``DOC_JOURNEY_UNTESTED`` can be asked at all: one journey id in, the
#: ids of the evidence that actually ran and passed for it out.
#:
#: The *presence* of a resolver is the arming, which is the same shape
#: :func:`check_floors` and :func:`check_side_effects` already use for the
#: two other things this module refuses to know on a caller's behalf.
#: Whether a journey must be tested is a release-mode policy (architecture
#: §11.1), and a model that assumed the answer would either turn every
#: pre-E2 build red or make the release gate impossible to arm later. So
#: no resolver means the question is not being asked, and a resolver means
#: it is.
EvidenceResolver = Callable[[str], "tuple[str, ...]"]


def _surfaces_by_id(bundle: DocsBundle) -> Mapping[str, SurfaceRecord]:
    """Every served capability of ``bundle``, by its comparable id."""
    return {normalize_id(record.id): record for record in bundle.surfaces}


def _approval_findings(
    journey: JourneyRecord, surfaces: Mapping[str, SurfaceRecord]
) -> list[Finding]:
    """Every step that crosses an approval boundary says so, and only those.

    Both directions, because both are lies of a different kind. A step
    whose surface declares ``approval`` and carries no boundary walks a
    reader up to an irreversible thing without telling them it is one. A
    step that declares a boundary its surface never asks for teaches the
    reader to expect a prompt that never comes, which is how a person
    learns to click past the real ones.

    A step naming a surface this build does not address is skipped: that
    is :func:`check_references`' finding, and two findings for one mistake
    is noise.
    """
    findings: list[Finding] = []
    for index, step in enumerate(journey.steps):
        surface = surfaces.get(normalize_id(step.surface))
        if surface is None:
            continue
        asks = APPROVAL_EFFECT in surface.side_effects
        declared = bool(step.approval_boundary.strip())
        if asks and not declared:
            findings.append(
                Finding(
                    code=DOC_APPROVAL_UNDECLARED,
                    location=location_of(surface),
                    message=(
                        f"{journey.id} takes step {index + 1} to {surface.id}, "
                        f"which declares {APPROVAL_EFFECT!r} among its side "
                        f"effects, and the step says nothing about what the "
                        f"reader is being asked to approve"
                    ),
                    remediation=(
                        "write the step's approval_boundary: what the person "
                        "is approving, and that nothing happens until they "
                        "do. The surface already says an approval is asked "
                        "for; this is the sentence that says so on the path "
                        "the reader is actually walking."
                    ),
                )
            )
        elif declared and not asks:
            findings.append(
                Finding(
                    code=DOC_APPROVAL_UNDECLARED,
                    location=location_of(surface),
                    message=(
                        f"{journey.id} declares an approval boundary at step "
                        f"{index + 1}, and {surface.id} declares "
                        f"{list(surface.side_effects)} — no approval is asked "
                        f"for there"
                    ),
                    remediation=(
                        "either the step is not where the reader is asked, "
                        "and the boundary belongs on the step that is, or the "
                        "surface really does ask and its own record is the "
                        "thing that is wrong. A boundary nobody crosses "
                        "teaches a reader to expect a prompt that never comes."
                    ),
                )
            )
    return findings


def _recovery_findings(
    journey: JourneyRecord, surfaces: Mapping[str, SurfaceRecord], index: ReferenceIndex
) -> list[Finding]:
    """Every failure a journey recovers from is one this build can name.

    Two ways it can be answerable, and the model carries both because the
    product does: the build addresses ``diagnostic:<when>``, or one of
    this journey's own step surfaces declares the failure among its
    ``errors``. Neither is a subset of the other — ``NOT_BUILT`` is a route
    error and no diagnostic, ``GENERATED_FILE_DRIFT`` is a registered
    diagnostic that no step surface's record repeats — so requiring either
    one alone would refuse a truthful journey.

    B7's ambiguity rule is the third case: two step surfaces declaring one
    failure leaves a reader who has just seen it unable to tell which step
    they are recovering from.
    """
    declared_by: dict[str, list[str]] = {}
    for step in journey.steps:
        surface = surfaces.get(normalize_id(step.surface))
        if surface is None:
            continue
        for code in surface.errors:
            declared_by.setdefault(code, []).append(surface.id)

    findings: list[Finding] = []
    for position, path in enumerate(journey.recovery_paths):
        naming = sorted(set(declared_by.get(path.when, ())))
        if len(naming) > 1:
            findings.append(
                Finding(
                    code=DOC_JOURNEY_UNRESOLVED,
                    location="",
                    message=(
                        f"{journey.id} recovers from {path.when} (at "
                        f"recovery_paths[{position}]) and {len(naming)} of its "
                        f"own steps declare that failure: {', '.join(naming)}"
                    ),
                    remediation=(
                        "a reader who has just seen this failure has to know "
                        "which step they are recovering from. Split the "
                        "recovery, or name a failure only one of the steps "
                        "can raise."
                    ),
                )
            )
        elif not naming and not index.knows(f"diagnostic:{path.when}"):
            findings.append(
                Finding(
                    code=DOC_JOURNEY_UNRESOLVED,
                    location="",
                    message=(
                        f"{journey.id} recovers from {path.when} (at "
                        f"recovery_paths[{position}]), which is not a "
                        f"diagnostic this build addresses and which none of "
                        f"this journey's step surfaces declares among its "
                        f"errors"
                    ),
                    remediation=(
                        f"a recovery is written against a failure that really "
                        f"happens. Either diagnostic:{path.when} should exist "
                        f"and the provider that owns it has to emit it, or the "
                        f"failure is a step surface's own declared error and "
                        f"the surface's record has to say so, or the name is "
                        f"simply wrong. An invented failure name reads as a "
                        f"real one to every reader who meets it."
                    ),
                )
            )
    return findings


def _teaching_order_findings(
    journey: JourneyRecord, concepts: Mapping[str, ConceptRecord]
) -> list[Finding]:
    """Nothing rests on an idea the reader has not met yet.

    The rule ``concepts_taught`` is ordered *for*: walking the list in
    order, a concept is in scope once it is declared as already required
    or once it has been taught. A concept whose own ``requires`` edges
    point at something not yet in scope is taught too early, and the
    finding names the position, the concept and the prerequisite — the
    three things an author needs to move one line.

    The prerequisites come from the concept graph a person authored
    (C5a's ``requires`` relation), never from prose. That is what makes
    this a gate rather than a guess: nobody restates a prerequisite on the
    journey, so nobody can restate it wrongly.
    """
    findings: list[Finding] = []
    scope = {normalize_id(item) for item in journey.concepts_required}
    for position, taught in enumerate(journey.concepts_taught, start=1):
        scope.add(normalize_id(taught))
        record = concepts.get(normalize_id(taught))
        if record is None:
            # An unresolved concept is check_references' finding.
            continue
        for relation, target in record.related_concepts:
            if relation != TEACHING_PREREQUISITE or normalize_id(target) in scope:
                continue
            findings.append(
                Finding(
                    code=DOC_TEACHING_ORDER,
                    location="",
                    message=(
                        f"{journey.id} teaches {taught} at step {position} of "
                        f"its teaching order, and {taught} requires {target}, "
                        f"which nothing has taught yet and which the journey "
                        f"does not list as already known"
                    ),
                    remediation=(
                        f"either teach {target} earlier in concepts_taught, or "
                        f"add it to concepts_required because a reader "
                        f"starting this path is expected to have it already. "
                        f"A reader meets these ideas in this order, and an "
                        f"idea that arrives after the thing resting on it "
                        f"arrives too late to help."
                    ),
                )
            )
    return findings


def _untested_findings(
    journey: JourneyRecord, resolver: EvidenceResolver
) -> list[Finding]:
    """This path is known to still work, because something ran it."""
    declared = tuple(item.id for item in journey.evidence)
    if not declared:
        return [
            Finding(
                code=DOC_JOURNEY_UNTESTED,
                location="",
                message=(
                    f"{journey.id} names no executable evidence, so nothing "
                    f"has walked this path since it was written"
                ),
                remediation=(
                    "give it evidence: a registered runnable example, or a "
                    "transcript fixture that replays the steps and checks what "
                    "comes back. A journey nobody runs is a claim about the "
                    "product that goes stale silently, which is the one kind "
                    "of documentation failure a reader cannot see coming."
                ),
            )
        ]
    passed = frozenset(resolver(journey.id))
    return [
        Finding(
            code=DOC_JOURNEY_UNTESTED,
            location="",
            message=(
                f"{journey.id} names {identifier} as its evidence and this "
                f"build has no passing run of it"
            ),
            remediation=(
                f"run {identifier} and fix what it reports, or correct the id. "
                f"Evidence that is named and not green is worse than none: it "
                f"says the path was checked when it was not."
            ),
        )
        for identifier in declared
        if identifier not in passed
    ]


def check_journeys(
    bundle: DocsBundle,
    index: ReferenceIndex,
    *,
    evidence_resolver: EvidenceResolver | None = None,
) -> list[Finding]:
    """The four rules a journey has to satisfy beyond resolving.

    Resolution itself is :func:`check_references`' — every step surface,
    taught concept, required concept and piece of evidence is an edge it
    already walks, and repeating the walk here would report one mistake
    twice. What is left is everything resolution cannot see:

    * **the failure a recovery is written against is real** — a
      ``diagnostic:`` the build addresses, or an error one of this
      journey's own step surfaces declares, and not two of them
      (``DOC_JOURNEY_UNRESOLVED``, the diagnostic class §11's wording
      names);
    * **the teaching order holds** — nothing rests on an idea the reader
      has not met (``DOC_TEACHING_ORDER``);
    * **an approval boundary is declared exactly where one is crossed**
      (``DOC_APPROVAL_UNDECLARED``);
    * **something has actually run the path**, when a caller can say
      (``DOC_JOURNEY_UNTESTED``).

    A journey with no steps is ``DOC_GATE_VACUOUS``, the same finding
    :func:`check_sequences` gives an empty teaching order, though the
    loader refuses one first — this is the half that catches a bundle
    built by hand or read back from a file.
    """
    surfaces = _surfaces_by_id(bundle)
    concepts = {normalize_id(record.id): record for record in bundle.concepts}
    findings: list[Finding] = []
    for journey in bundle.journeys:
        if not journey.steps:
            findings.append(
                Finding(
                    code=DOC_GATE_VACUOUS,
                    location="",
                    message=f"{journey.id} leads nowhere; it has no steps",
                    remediation=(
                        "give it the surfaces a reader passes through, in "
                        "order, or remove it. A journey with no steps passes "
                        "every check it is subject to and leads no one "
                        "anywhere."
                    ),
                )
            )
        findings.extend(_recovery_findings(journey, surfaces, index))
        findings.extend(_teaching_order_findings(journey, concepts))
        findings.extend(_approval_findings(journey, surfaces))
        if evidence_resolver is not None:
            findings.extend(_untested_findings(journey, evidence_resolver))
    return findings


# ---------------------------------------------------------------------------
# The release-currency rule (H1)
# ---------------------------------------------------------------------------


def _mismatch(location: str, message: str, remediation: str) -> Finding:
    """One ``DOC_VERSION_MISMATCH``, said the way every finding is said."""
    return Finding(
        code=DOC_VERSION_MISMATCH,
        location=location,
        message=message,
        remediation=remediation,
    )


def check_manifest(
    manifest: DocsManifest,
    *,
    stamp: BuildStamp | None = None,
    location: str = "",
) -> list[Finding]:
    """One documentation manifest describes one build of one version.

    ``DOC_VERSION_MISMATCH`` (architecture §11, §13.2). Five ways a
    manifest can fail to be about a single release, each of which has
    happened to a real project and none of which a manifest of paths and
    digests alone could notice:

    1. **the lockstep is broken** — a distribution ships at a version the
       product version does not name. Four wheels that do not agree about
       what release they are is the failure PRD INV-4 exists against, and
       a manifest that recorded it silently would be the record of a
       shipped inconsistency;
    2. **an artifact represents another version** — a page rendered for
       0.17.0 sitting in a manifest for 0.18.1. §11's row, verbatim;
    3. **an artifact came from another build** — its source snapshot is
       not this manifest's. Two builds mixed into one manifest, which
       version numbers alone cannot see because both builds can be of the
       same version;
    4. **an artifact was rendered on another channel** — a preview page
       inside a release manifest. This is the one §13.2 cares about most:
       preview documentation presented as installed release documentation
       is the failure that invariant is written against, and it is
       invisible to every check that only compares versions, because a
       preview build of 0.18.1 and a release build of 0.18.1 carry the
       same number;
    5. **a provider is lagging** — records emitted against a model version
       other than the one this manifest is written in.

    **Historical is the declared exception**, and the only one. §11 words
    the rule as "represents another version *without historical status*",
    so an artifact that says it is historical may differ in version and in
    snapshot: that is what an immutable older snapshot is. It may not
    differ in nothing else — a historical artifact still has to be a
    channel this model knows.

    ``stamp`` is the composed build's own, when the caller has it. It
    closes the third side of the triangle the manifest sits in: the
    package versions agree with the product version, the artifacts agree
    with the product version, and the *bundle the artifacts were rendered
    from* agrees with both. Optional because a manifest read back from
    disk — H2's case, and a fixture's — has no bundle beside it, and a
    gate that could only run beside a live composition would not be the
    gate H2 needs.
    """
    findings: list[Finding] = []
    product = manifest.product_version

    if manifest.build_channel not in BUILD_CHANNELS:
        findings.append(
            _mismatch(
                location,
                f"this manifest is on the {manifest.build_channel!r} channel, "
                f"which is not one of {', '.join(BUILD_CHANNELS)}",
                "Architecture §13.2 defines three channels and every rule "
                "about what a build may contain is written in terms of them. "
                "A fourth word is not a stricter channel; it is a build "
                "nothing downstream knows how to treat.",
            )
        )

    for package in manifest.package_versions:
        if package.version != product:
            findings.append(
                _mismatch(
                    location,
                    f"{package.distribution} ships at {package.version} and "
                    f"this manifest describes {product}",
                    f"All four distributions ship one version (PRD INV-4, "
                    f"anchored on {LOCKSTEP_ANCHOR}). Bump the eight lockstep "
                    f"sites together — `uv run python "
                    f"scripts/check_version_refs.py` names every one of them — "
                    f"rather than editing this manifest, which is generated.",
                )
            )

    for provider in manifest.provider_schemas:
        if provider.schema_version != manifest.schema:
            findings.append(
                _mismatch(
                    location,
                    f"provider {provider.provider_id} emitted records against "
                    f"{provider.schema_version} and this manifest is written "
                    f"in {manifest.schema}",
                    "A provider stamps the model version it was written "
                    "against onto every record it produces. One that lags "
                    "behind the bundle is emitting a shape the rest of the "
                    "build no longer reads the same way; update the adapter "
                    "rather than the stamp.",
                )
            )

    for artifact in manifest.artifacts:
        findings.extend(_check_artifact(artifact, manifest))

    if stamp is not None:
        if stamp.release_version != product:
            findings.append(
                _mismatch(
                    location,
                    f"the composed snapshot is stamped {stamp.release_version} "
                    f"and this manifest describes {product}",
                    f"The stamp carries the version of the toolchain that "
                    f"composed the snapshot and the manifest carries "
                    f"{LOCKSTEP_ANCHOR}'s. In lockstep they are one number, so "
                    f"a difference here means a distribution was bumped "
                    f"without the others.",
                )
            )
        if stamp.build_channel != manifest.build_channel:
            findings.append(
                _mismatch(
                    location,
                    f"the composed snapshot was built on the "
                    f"{stamp.build_channel!r} channel and this manifest says "
                    f"{manifest.build_channel!r}",
                    "The manifest reads the channel off the stamp precisely "
                    "so the two cannot differ. A difference means the "
                    "manifest was assembled from a bundle other than the one "
                    "its artifacts were rendered from.",
                )
            )
        if stamp.snapshot_hash != manifest.snapshot_hash:
            findings.append(
                _mismatch(
                    location,
                    f"the composed snapshot is {stamp.snapshot_hash} and this "
                    f"manifest describes {manifest.snapshot_hash}",
                    "A manifest describes the build it was made from. Two "
                    "digests here means two builds, and the artifacts listed "
                    "belong to neither in full.",
                )
            )
    return findings


def _check_artifact(artifact: ArtifactRecord, manifest: DocsManifest) -> list[Finding]:
    """One listed artifact against the manifest that lists it.

    Split out because the historical exception applies to three of the
    four questions and to none of the manifest-level ones, and a single
    loop body carrying that condition three times reads as three separate
    rules rather than as one.
    """
    where = artifact.path_or_uri
    if artifact.build_channel not in BUILD_CHANNELS:
        return [
            _mismatch(
                where,
                f"{artifact.id} was rendered on the "
                f"{artifact.build_channel!r} channel, which is not one of "
                f"{', '.join(BUILD_CHANNELS)}",
                "Every artifact records the channel it was rendered on so a "
                "manifest can be checked for mixing. An unrecognized word "
                "makes that check unanswerable rather than passing it.",
            )
        ]

    historical = artifact.build_channel == HISTORICAL_CHANNEL
    findings: list[Finding] = []

    if artifact.build_channel != manifest.build_channel and not historical:
        findings.append(
            _mismatch(
                where,
                f"{artifact.id} was rendered on the "
                f"{artifact.build_channel} channel and this manifest is a "
                f"{manifest.build_channel} manifest",
                "A release manifest describes outputs built from the release "
                "commit and verified against the release payloads "
                "(architecture §13.2). A preview artifact inside one is "
                "preview documentation presented as installed release "
                "documentation, which is the one thing §13.2 forbids "
                "outright. Rebuild the artifact on this channel, or declare "
                "it historical if it is deliberately an older snapshot.",
            )
        )

    if artifact.release_version != manifest.product_version and not historical:
        findings.append(
            _mismatch(
                where,
                f"{artifact.id} represents {artifact.release_version} and "
                f"this manifest describes {manifest.product_version}",
                "Every output of one build represents that build's version. "
                "An output carrying another one was rendered by a different "
                "build; re-render it here, or mark it historical, which is "
                "the declared status for a snapshot deliberately kept "
                "against an older version.",
            )
        )

    if artifact.source_snapshot != manifest.snapshot_hash and not historical:
        findings.append(
            _mismatch(
                where,
                f"{artifact.id} was rendered from snapshot "
                f"{artifact.source_snapshot} and this manifest describes "
                f"{manifest.snapshot_hash}",
                "Two snapshot digests in one manifest is two builds mixed "
                "together — which version numbers cannot catch, because both "
                "builds can be of the same version. Re-render the whole "
                "declared set from one composition.",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Everything, once
# ---------------------------------------------------------------------------


def validate_bundle(
    bundle: DocsBundle,
    *,
    results: Sequence[ProviderResult] = (),
    floors: Mapping[tuple[str, str], int] | None = None,
    allowances: Mapping[tuple[str, str], str] | None = None,
    external_ids: Iterable[str] = (),
    claims: Sequence[AuthorityClaim] = (),
    evidence_resolver: EvidenceResolver | None = None,
) -> tuple[Finding, ...]:
    """Run every gate this milestone owns and return one sorted report.

    Exact repeats are dropped: the sequence gate and the reference
    resolver ask the same question of a teaching step on purpose, and an
    author should see one finding for one mistake.

    ``claims`` is how a caller asks the authority comparison a
    domain-scoped question. Nothing is asked by default, because nothing
    in ``@1`` says what domain a record's claim is in.

    ``floors``, ``allowances`` and ``evidence_resolver`` are the three
    things this module refuses to know: how much a provider should
    produce, which source may stay silent about its effects, and whether
    a journey's evidence actually ran. All three are claims about one
    repository's readings and one release policy, and all three are the
    caller's to make.
    """
    index = ReferenceIndex.of(bundle, external_ids)
    findings: list[Finding] = []
    findings.extend(check_references(index))
    findings.extend(check_surface_binding(bundle))
    findings.extend(check_side_effects(bundle, allowances))
    findings.extend(check_provenance(bundle, results))
    findings.extend(check_authority_records(bundle))
    findings.extend(check_sequences(bundle, index))
    findings.extend(check_journeys(bundle, index, evidence_resolver=evidence_resolver))
    findings.extend(check_floors(results, floors or {}))

    authorities = {authority.id: authority for authority in bundle.authorities}
    for claim in claims:
        record = _record_by_id(bundle, claim.record_id)
        if not isinstance(record, ConceptRecord | SurfaceRecord | DocumentRecord):
            raise DocsModelError(
                f"{claim.record_id} is a {type(record).__name__}, which cites "
                f"no authority, so there is no governing question to ask of it"
            )
        decision = governing_authority(
            record_id=claim.record_id,
            cited=record.governed_by,
            authorities=authorities,
            domain=claim.domain,
            location=location_of(record),
        )
        findings.extend(decision.findings)
    return sort_findings(findings)


def _record_by_id(bundle: DocsBundle, record_id: str) -> DocsRecord:
    """The record ``record_id`` addresses, refusing an id nothing answers to."""
    wanted = normalize_id(record_id)
    for record in records_of(bundle):
        if normalize_id(record.id) == wanted:
            return record
    raise DocsModelError(f"this build addresses nothing called {record_id!r}")
