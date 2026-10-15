"""The ``s0ma-docs-model@1`` record types.

The typed vocabulary the documentation application is built from: what a
concept is, what a served capability is, what a journey is, what a catalog
row is, and where each fact came from. Milestone C1 of
the docs-function plan (internal) §8, placed here by ADR-012.

Three properties are load-bearing and every change to this module has to
keep them:

1. **Stdlib only.** Records are plain frozen dataclasses. They import
   nothing from ``s0ma``, ``s0ma_mcp`` or ``s0ma_studi0`` so that any
   consumer — a provider, a renderer, a gate, a future package — can read
   the model without taking on a dependency it does not otherwise want.
2. **Additive within ``@1``.** :data:`SCHEMA` names the version. Fields may
   be added inside ``@1``; a removal or a rename is a new version.
3. **One build stamp per bundle.** ``release_version`` and
   ``snapshot_hash`` are facts of a *build*, not of a concept, so they live
   on :class:`BuildStamp` and nowhere else. See
   :data:`BUILD_STAMP_ONLY_FIELDS`.

Field rulings this version carries, with the evidence they came from
(the Phase B gate record (internal) §7):

* ``ConceptRecord.summary`` exists (row 1). A bounded channel — the agent
  tool response — may only get smaller by omitting, never by paraphrasing,
  so the author needs a short form to omit *down to*.
* ``SurfaceRecord.governed_by`` and ``DocumentRecord.governed_by`` exist
  (row 3), so a served capability and a catalog row can cite the section
  that defines them instead of leaving it orphaned.
* ``component_refs`` and ``manual_exception`` are independent axes (row 4).
  A surface may carry both: hand-transcribed facts about a capability that
  does map to registered components. Nothing here refuses that pairing.
* Every field is classified authored or sourced (row 5) in
  :data:`FIELD_CLASS`, which is data, not runtime state — the voice and
  quotation gates read it, they never set it.
* ``DocumentRecord.prose_locator`` exists (row 6), because a guide's words
  can be a declaration body inside a ``.s0ma`` file rather than a file of
  its own, and a finding has to point at the line an author may edit.
* :class:`TeachingSequence` and :class:`TeachingStep` are the ordered
  teaching form (row 7). The record is here; the gate that resolves its
  steps belongs to C2.
* Teaching prose is a single paragraph in ``@1`` (row 9). The rule is
  enforced at construction by :func:`validate_single_paragraph`, and that
  function is the one place a future multi-paragraph decision has to
  change. Whitespace collapse across channels erases paragraph structure;
  refusing the blank line keeps the residue check honest while nothing in
  the corpus needs long form.

Re-added on schedule, by the milestone row 10 named:

* ``ConceptRecord.syntax`` and ``ConceptRecord.related_concepts`` arrived
  at **C5a**, the first two fields the deferral schedule promised back.
  Both carry a default of ``()``, which is what makes the addition
  additive in practice as well as on paper: every construction written
  against the previous version still builds, and a concept with no syntax
  form and no declared relations — most product concepts — says so by
  saying nothing.
* ``DocumentRecord.authority`` arrived at **C6**, the milestone row 10
  named for it. B4's cost line was ``doc:normative/prd`` — a normative
  document with no way to say so — and the catalog is where that stopped
  being hypothetical: twenty-two rows of this repository's catalog are a
  written authority, and each one now names the ``authority:`` id the
  repository provider emits for the same file. It is the document's own
  identity, not what governs it: ``governed_by`` already answers the
  second question, and an ADR that is ``authority:adr/repo.ADR-012`` is
  not governed by itself. Empty for every document that is not an
  authority, which is most of them, and that default is what keeps the
  addition additive.

* ``JourneyRecord.concepts_taught`` and ``concepts_required`` arrived at
  **E1**, the milestone row 10 named for them, and with them
  ``JourneyRecord.evidence`` and ``JourneyStep.approval_boundary`` — the
  two fields E1's gates needed and which B4 had deferred for the same
  reason, that no gate read them. All four default to empty, which is
  what keeps the addition additive in practice as well as on paper. What
  each is for, and why it sits where it does, is written on
  :class:`JourneyRecord` and :class:`JourneyStep`.

Deferred on purpose, with the milestone that re-adds them (row 10 and
``scripts/spikes/docs_model/spike_b4_schemas/DEFERRED.md``):

* ``review_triggers`` → **F**.
* ``ArtifactRecord`` in full. Nothing in Phase C renders, so no artifact
  exists to record; it arrives with the renderers that produce one.

Landed at **F9**, which is where the deferral stopped being free:

* :class:`AliasEntry` and :attr:`DocsBundle.aliases`. Row 10 scheduled an
  ``aliases`` field on concepts for F6 and on surfaces for F7, and neither
  milestone took it — the alternate terms stayed in the authored concept
  files and reached a reader through a second reading of those files. That
  reading only works in a checkout, so every alternate term was dead on the
  served snapshot: a wheel and the MCP server's packaged copy resolved every
  id and every name, and no earlier name at all. The pairs are a property of
  a *build* rather than of any one record — an alias names the id that
  survives, which is a statement about two records — so they sit beside the
  stamp on the bundle instead of on either record type. Empty is a real
  answer, and a snapshot written before this field is read as carrying none.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, fields
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from s0ma_dsl.docs_model.ids import AliasIndex

__all__ = [
    "AUTHORITY_ORDER",
    "BUILD_CHANNELS",
    "BUILD_STAMP_ONLY_FIELDS",
    "FIELD_CLASS",
    "HISTORICAL_CHANNEL",
    "PREVIEW_CHANNEL",
    "RECORD_TYPES",
    "RELEASE_CHANNEL",
    "SCHEMA",
    "AliasEntry",
    "AuthorityDelegation",
    "AuthorityRef",
    "BuildStamp",
    "ConceptRecord",
    "DocsBundle",
    "DocsModelError",
    "DocsSchemaVersionError",
    "DocumentRecord",
    "ExampleRef",
    "FieldClass",
    "JourneyRecord",
    "JourneyStep",
    "Provenance",
    "RecoveryPath",
    "SurfaceRecord",
    "TeachingSequence",
    "TeachingStep",
    "authored_prose_fields",
    "field_class",
    "validate_schema_version",
    "validate_single_paragraph",
]

#: The model's identity. Stamped once per serialized bundle, never per
#: record. Additive-only within ``@1`` (plan §5).
SCHEMA = "s0ma-docs-model@1"

#: Written authority, strongest first (architecture §6.1, plan §5). The
#: ordering is data here; the comparison that uses it belongs to C2.
#:
#: Delegation is the ratified exception (plan §5, B7 report §6 row 7): a
#: stronger authority may hand one domain to a weaker one in its own words,
#: and where it does, the delegate wins for that domain without a conflict
#: being reported. The delegation is written down on the delegating record
#: as :class:`AuthorityDelegation`, so it is citable rather than assumed.
AUTHORITY_ORDER: tuple[str, ...] = (
    "owner",
    "prd",
    "spec",
    "adr",
    "frozen_contract",
    "declared",
    "derived",
    "observed",
    "editorial",
)

#: The three channels a documentation build can belong to (architecture
#: §13.2). ``preview`` is built from ``main`` and is visibly labelled as
#: such wherever a version is written; ``release`` is built from the exact
#: commit a version tag names; ``historical`` is an immutable snapshot kept
#: against an older version.
#:
#: The word is ``build_channel`` rather than ``channel`` everywhere it is a
#: field, because this model already spends ``channel`` twice —
#: :class:`SurfaceRecord` carries the channel a capability is *served* on,
#: and the renderers are named for the channel a topic is *presented* on.
#: A third meaning under the same word would make
#: :data:`BUILD_STAMP_ONLY_FIELDS` unusable, since that rule is exactly
#: "no record may declare a field the stamp declares".
PREVIEW_CHANNEL = "preview"
RELEASE_CHANNEL = "release"
HISTORICAL_CHANNEL = "historical"

#: All three, in the order architecture §13.2 introduces them.
BUILD_CHANNELS: tuple[str, ...] = (PREVIEW_CHANNEL, RELEASE_CHANNEL, HISTORICAL_CHANNEL)

#: Field names only :class:`BuildStamp` may declare. A copy of a build fact
#: on a record is the first thing to go stale, and the staleness would be
#: nobody's fault, so the model has nowhere to put one.
BUILD_STAMP_ONLY_FIELDS = frozenset(
    {"build_channel", "release_version", "schema", "snapshot_hash"}
)


class DocsModelError(ValueError):
    """A record does not satisfy the documentation model."""


class DocsSchemaVersionError(DocsModelError):
    """A bundle names a schema version this reader does not understand."""


def validate_schema_version(value: str) -> None:
    """Refuse any schema string but this version's.

    The house idiom from ``s0ma_dsl.ir.schema``: one constant, one error
    type, one validator that readers call before they trust a document.
    """
    if value != SCHEMA:
        raise DocsSchemaVersionError(
            f"this reader understands {SCHEMA!r}; the bundle names {value!r}"
        )


class FieldClass(Enum):
    """Who wrote a field, which decides which rules may touch it.

    ``AUTHORED_PROSE``
        A person wrote it, in the product voice, for a reader. The voice
        gate governs it and the single-paragraph rule applies to it.
    ``AUTHORED_DATA``
        A person wrote it, but it is an identifier, a reference, or a list
        of them — not prose. No voice rule applies; a resolution gate does.
    ``SOURCED``
        Copied or derived from a source. It is verbatim or it is absent,
        and no rule may rewrite it. ``SurfaceRecord.intent`` is the case
        that forced the distinction: it quotes a component's real intent,
        and a voice rule applied to a quotation makes either a false
        quotation or a permanently failing gate.
    """

    AUTHORED_PROSE = "authored-prose"
    AUTHORED_DATA = "authored-data"
    SOURCED = "sourced"


class _Record:
    """Construction-time validation shared by every record type.

    Not a dataclass itself and it declares no fields, so it adds nothing to
    any subclass but the hook.
    """

    def __post_init__(self) -> None:
        validate_single_paragraph(self)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provenance(_Record):
    """Where a derived record's facts came from (plan §5 provider contract).

    The four items the frozen contract names: adapter id, source identity,
    schema version, content hash. Authored records carry authority
    references instead — a person citing a document is making a different
    claim from a provider reading a file, and the model keeps them apart.

    ``source_sha256`` is the full sha256 of the source's UTF-8 bytes with
    newlines normalized to LF, so it equals ``sha256sum`` of the tracked
    file and stays equal in a checkout that lost the LF attribute.

    ``schema_version`` is not a copy of the build stamp. The stamp says
    what version a bundle *is*; this says what version a provider emitted
    against, which is the same string in a healthy build and a different
    one the moment a provider falls behind — which is precisely what a
    gate wants to be able to see. The field names differ for that reason,
    and :data:`BUILD_STAMP_ONLY_FIELDS` keeps them apart.
    """

    adapter_id: str
    schema_version: str
    source: str
    source_sha256: str


@dataclass(frozen=True)
class AuthorityDelegation(_Record):
    """One domain an authority hands to a lower-ranked authority.

    The ratified delegation status (plan §5). The worked case is FR-DSL-1:
    the product requirements name the versioned language specification the
    normative authority for the language and decline to duplicate it, so
    for language questions the specification wins and no conflict is
    reported.

    ``domain`` names what is delegated, ``to_class`` names who wins for it,
    and ``stated_in`` names the section of this authority's own source that
    says so — a delegation nobody can cite is an assumption, and this model
    does not carry assumptions.
    """

    domain: str
    to_class: str
    stated_in: str


@dataclass(frozen=True)
class AuthorityRef(_Record):
    """A citation of a written authority (architecture §6.1).

    ``authority_class`` repeats the class segment of ``id`` on purpose: a
    gate that compares the two catches a provider that mints an id and a
    class separately and lets them disagree.
    """

    id: str
    authority_class: str
    source: str
    section: str
    content_sha256: str
    status: str
    delegates: tuple[AuthorityDelegation, ...]


@dataclass(frozen=True)
class ExampleRef(_Record):
    """A registered runnable example a record points at.

    The smallest carrier for the concept-to-example edge. A bare id string
    cannot be checked against a source file; this can.
    """

    id: str
    source: str


@dataclass(frozen=True)
class ConceptRecord(_Record):
    """Authored teaching knowledge with explicit normative references.

    ``summary`` is the short form a bounded channel may fall back to. It is
    not a paraphrase of ``plain_definition`` produced at render time — the
    channel rule is verbatim or absent, so the short form has to be
    authored here, once, and quoted everywhere.

    ``syntax`` holds the smallest valid written form of the thing, one
    line per line, where the concept has one. B4 named the cost of not
    having it: ``concept:nerve`` is precisely the concept nobody can learn
    from prose alone, because the specification's field block *is* the
    concept for an author. A concept that is not a written form — drift,
    the check-and-build loop — carries an empty tuple, and that is an
    answer rather than an omission.

    ``related_concepts`` holds typed edges to other concepts: each entry is
    a relation word and the id it points at, in that order. The relation
    vocabulary and the resolution of the targets belong to the loader that
    reads the authored file, not here — this record carries the edge, and
    the gate decides what a legal edge is.

    Two notes on the shape of that field, both load-bearing. The inner
    tuple is exactly two strings, enforced by that loader; it is annotated
    as the homogeneous form because
    :func:`~s0ma_dsl.docs_model.serialize.record_from_plain` reads
    ``tuple[X, ...]`` and nothing else, and a field the canonical reader
    cannot read back would quietly break the round trip this model rests
    on. And both new fields default to ``()`` so that adding them is
    additive for every existing caller, which is what point 2 above asks of
    any addition inside ``@1``.
    """

    id: str
    term: str
    summary: str
    plain_definition: str
    purpose: str
    use_when: str
    do_not_use_when: str
    governed_by: tuple[str, ...]
    examples: tuple[ExampleRef, ...]
    syntax: tuple[str, ...] = ()
    related_concepts: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class SurfaceRecord(_Record):
    """One served capability on one channel.

    ``component_refs`` and ``manual_exception`` are independent. The first
    says the capability maps to registered components; the second says some
    of its facts were transcribed by hand rather than derived. A surface
    may honestly have both, and the studi0 route that maps to two
    registered components while carrying hand-written facts is exactly that
    case.

    ``intent`` is classified as sourced even when a person transcribed it,
    because it is a quotation of the real intent either way.
    """

    id: str
    channel: str
    public_name: str
    intent: str
    component_refs: tuple[str, ...]
    manual_exception: str
    governed_by: tuple[str, ...]
    side_effects: tuple[str, ...]
    errors: tuple[str, ...]
    provenance: Provenance


@dataclass(frozen=True)
class JourneyStep(_Record):
    """One ordered step: a surface, why you are there, what you should see.

    ``approval_boundary`` is what the reader is told before the step is
    taken, where taking it asks them for something irreversible: what they
    are approving, and that nothing happens until they do. It is a field
    rather than a sentence somewhere in ``purpose`` because a gate has to
    be able to *ask* whether the boundary was declared, and reading prose
    for the word "approve" would pass a step that mentions approval while
    saying nothing about this one and fail a step that says it in other
    words. Empty is the answer — and the only correct one — for a step
    whose surface declares no approval-class effect; the gate that reads
    it is :func:`~s0ma_dsl.docs_model.validate.check_journeys`, and it
    refuses the field in both directions.
    """

    surface: str
    purpose: str
    expected_outcome: str
    approval_boundary: str = ""


@dataclass(frozen=True)
class RecoveryPath(_Record):
    """What to do when a named failure of a step's surface happens.

    ``when`` is the failure's own name as the product spells it —
    ``NOT_BUILT``, ``GENERATED_FILE_DRIFT`` — and deliberately not an id.
    A failure a journey recovers from is answerable in two ways and the
    model carries both: the build addresses ``diagnostic:<when>``, or one
    of this journey's own step surfaces declares it among its ``errors``.
    Writing it as an id would have to pick one of those and would make the
    other unsayable, so the name stays a name and
    :func:`~s0ma_dsl.docs_model.validate.check_journeys` is what holds it
    to being answerable at all.
    """

    when: str
    next_surface: str
    action: str


@dataclass(frozen=True)
class JourneyRecord(_Record):
    """Authored sequencing over surfaces. Data only — no grammar (D-4).

    ``concepts_taught`` is the ideas walking this path leaves a reader
    with, **in the order they are met**. It is the journey's list rather
    than a field on each step, for the reason architecture §6.4 writes it
    that way: a step is a thing you *do* and a concept is a thing you
    *learn*, and the two orders are not the same one — a step can teach
    nothing new and one step can be where three ideas land. Ordered rather
    than sorted, because the order is the whole content of the teaching
    rule: a concept must be taught, or already required, before anything
    that rests on it. Duplicates are refused by the loader for the reason
    :data:`~s0ma_dsl.docs_model.validate.DOC_SEQUENCE_REPEATS` exists.

    ``concepts_required`` is what a reader is assumed to know before step
    one, sorted because it is a set and nothing about it is ordered. It is
    the other end of the same rule: a prerequisite is either taught on the
    way or declared here, and a journey that does neither has a hole in it
    that only its reader will find.

    ``evidence`` is the registered executable evidence that this path
    still works — a runnable example, or the transcript fixtures E2
    introduces, each carried as an :class:`ExampleRef` so the id can be
    checked against the file it names. ``DOC_JOURNEY_UNTESTED`` is the
    gate; it is armed by handing
    :func:`~s0ma_dsl.docs_model.validate.check_journeys` a resolver that
    says which evidence actually ran, which is the seam E2's runner lands
    behind. Empty is honest until then and red once release mode asks.
    """

    id: str
    intent: str
    steps: tuple[JourneyStep, ...]
    recovery_paths: tuple[RecoveryPath, ...]
    concepts_taught: tuple[str, ...] = ()
    concepts_required: tuple[str, ...] = ()
    evidence: tuple[ExampleRef, ...] = ()

    def approval_boundaries(self) -> tuple[str, ...]:
        """Every boundary this path declares, in the order it is crossed.

        A method rather than a field: architecture §6.4 lists
        ``approval_boundaries`` on the journey, and the steps are where
        the boundaries actually are, so a field here would be a second
        copy of what the steps already say — and a second copy is what
        this whole model exists against. Each entry names the step's
        surface so a reader knows which one asks.
        """
        return tuple(
            f"{step.surface}: {step.approval_boundary}"
            for step in self.steps
            if step.approval_boundary.strip()
        )


@dataclass(frozen=True)
class TeachingStep(_Record):
    """One position in an ordered teaching sequence."""

    topic: str
    purpose: str


@dataclass(frozen=True)
class TeachingSequence(_Record):
    """Topics taught in a deliberate order.

    No other record can hold this. A catalog row's ``covers`` is a sorted
    set, so order is thrown away on the way in; a journey's steps resolve
    against surfaces only, and a concept is not a surface. The whole answer
    is an ordered tuple of topic ids, resolved against the same index
    everything else resolves against.

    The constraint only an ordered form can carry — say each topic once —
    belongs to the gate that walks these steps, which is C2's.
    """

    id: str
    steps: tuple[TeachingStep, ...]


@dataclass(frozen=True)
class DocumentRecord(_Record):
    """A catalog row binding a document to what it covers.

    ``canonical_source`` is the file. ``prose_locator`` is where the words
    actually are, which is not always the same place: ``<path>`` names a
    whole file and ``<path>#doc-guide:<name>`` names one declaration body
    inside a ``.s0ma`` source. Without it, a finding about a guide's prose
    points at generated output the author is forbidden to edit.

    ``authority`` is the written authority this document *is*, where it is
    one — architecture §6.5's "AuthorityRef when normative, otherwise
    evidence class", carried as the id rather than as a second copy of the
    citation, so the catalog row and the authority index cannot drift into
    two accounts of one file. It is not ``governed_by``, which says what
    governs the document; a decision record is an authority and is not
    governed by itself. Empty is the answer for every document that is
    not one, and the default keeps the field additive within ``@1``.
    """

    id: str
    title: str
    canonical_source: str
    prose_locator: str
    governed_by: tuple[str, ...]
    covers: tuple[str, ...]
    authority: str = ""


@dataclass(frozen=True)
class BuildStamp(_Record):
    """What build a bundle is, recorded once for the whole bundle.

    The release the documentation describes, the digest of the record set
    it was built from, and the model version it is written in. No record
    carries a copy: see :data:`BUILD_STAMP_ONLY_FIELDS`.

    ``build_channel`` arrived at H1 and is the fourth (architecture §13.2).
    It is an additive field with a default, which is the ``@1`` rule
    property 2 states: every bundle constructed before H1 still builds, and
    every snapshot written before H1 still reads. The default is
    :data:`PREVIEW_CHANNEL` and that is deliberate — a build that has not
    been told it is a release **is not one**, and the failure mode worth
    designing against is preview documentation quietly presenting itself as
    the installed release (architecture §13.2, SDA-INV-11).

    It is on the stamp rather than derived where it is read, because the
    channel is a fact of the *build* in exactly the way the release version
    is: several presentation channels render one snapshot and must agree
    about which build they are showing, and a value recomputed per renderer
    is a value two renderers can disagree about.

    The channel is deliberately **outside**
    :func:`~s0ma_dsl.docs_model.serialize.snapshot_hash`, like everything
    else on the stamp: the digest is the identity of what a build *says*,
    and the same records say the same things whether they were composed on
    ``main`` or at a tag. What changes between the two is how the version
    is written down, which is :meth:`version_line`.
    """

    schema: str
    release_version: str
    snapshot_hash: str
    build_channel: str = PREVIEW_CHANNEL

    def version_line(self) -> str:
        """The version as a reader meets it, labelled unless it is released.

        One string, produced once, so that every identity line on every
        channel says the same thing: ``0.18.1`` for a release build and
        ``0.18.1 (preview)`` for a build from ``main``.

        The label rides *on the version* rather than beside it because the
        unlabelled sentence is the false one. A preview build describes a
        tree that is ahead of the last tag; writing "Release: 0.18.1" flat
        claims it documents released 0.18.1, which is the one thing
        architecture §13.2 says preview documentation must never be
        presented as. Attaching the label to the fact that would otherwise
        lie also means no channel has to remember to carry a second field:
        the human page, the agent response and the read commands all render
        this fact already.
        """
        if self.build_channel == RELEASE_CHANNEL:
            return self.release_version
        return f"{self.release_version} ({self.build_channel})"


@dataclass(frozen=True)
class AliasEntry(_Record):
    """One alternate way of asking, and the id that answers it.

    ``id`` is the spelling somebody arrives holding — a term a concept was
    renamed from, a name a capability used to be served under — and
    ``canonical`` is the id this build actually addresses. Both are ids, so
    both are checkable against :data:`~s0ma_dsl.docs_model.ids.ID_FORMS`;
    the gate that checks them is the composer's, because only the composer
    knows the whole id set an alias may point into.

    Why this is a record and not a field on :class:`ConceptRecord`: an
    alias is a statement about *two* records, and putting it on either one
    makes the other's identity depend on a list it does not hold. It is
    also not a fact about a concept in particular — a renamed command or a
    superseded resource wants the same treatment — so the pairs live on
    the bundle, in one place, where every channel reads them.
    """

    id: str
    canonical: str


@dataclass(frozen=True)
class DocsBundle:
    """Every record of one build, grouped by type, under one stamp.

    A container rather than a record: it has no id, nothing cites it, and
    the authored-or-sourced classification does not apply to it.
    Composition of several providers into one bundle is C2's; this is the
    shape the result has.

    ``aliases`` is deliberately **not** a seventh record group. A record
    group is a thing the model resolves *against* and digests, and adding
    one is the schema revision
    :mod:`~s0ma_dsl.docs_model.inventories` argues against at length. An
    alias resolves against nothing and states no fact: it says a question
    spelled one way is the question already answered under another id. So
    it is an additive field with an empty default — every construction
    written before F9 still builds and every snapshot written before F9
    still reads — and it is outside ``serialize._GROUPS``, which is what
    keeps it outside the snapshot digest.
    """

    stamp: BuildStamp
    authorities: tuple[AuthorityRef, ...]
    concepts: tuple[ConceptRecord, ...]
    surfaces: tuple[SurfaceRecord, ...]
    journeys: tuple[JourneyRecord, ...]
    sequences: tuple[TeachingSequence, ...]
    documents: tuple[DocumentRecord, ...]
    aliases: tuple[AliasEntry, ...] = ()

    def alias_index(self) -> AliasIndex:
        """This build's aliases as the resolver's own index.

        :class:`~s0ma_dsl.docs_model.ids.AliasIndex` is imported inside the
        body rather than at module scope because ``ids`` imports *this*
        module for :data:`AUTHORITY_ORDER` — the deferred import is what
        keeps the dependency one-directional, and it is the same idiom
        ``bundle.snapshot_relative_path`` uses on the composer. The
        annotation resolves through ``TYPE_CHECKING``, so a type checker
        still sees the real type.

        This is the one supported way to get from a bundle to a resolvable
        alias table, so no reader has to know that the entries are sorted
        pairs, and no second reading of the concept files can disagree
        with the snapshot about what the alternate terms are.
        """
        from s0ma_dsl.docs_model.ids import AliasIndex

        return AliasIndex.of((entry.id, entry.canonical) for entry in self.aliases)


#: Every classified record type. :class:`DocsBundle` is deliberately absent
#: — it is a container of records, not a record.
RECORD_TYPES: tuple[type[Any], ...] = (
    AliasEntry,
    AuthorityDelegation,
    AuthorityRef,
    BuildStamp,
    ConceptRecord,
    DocumentRecord,
    ExampleRef,
    JourneyRecord,
    JourneyStep,
    Provenance,
    RecoveryPath,
    SurfaceRecord,
    TeachingSequence,
    TeachingStep,
)


# ---------------------------------------------------------------------------
# Authored versus sourced, per field
# ---------------------------------------------------------------------------

_AUTHORED_PROSE = FieldClass.AUTHORED_PROSE
_AUTHORED_DATA = FieldClass.AUTHORED_DATA
_SOURCED = FieldClass.SOURCED

#: Who wrote each field, keyed by ``(record type name, field name)``.
#:
#: This is the line between what a provider may derive and what a person
#: must write, and it is the line the voice gate stops at. It is a constant
#: the gates read; nothing sets a classification at run time, so no record
#: can quietly change which rules apply to it.
#:
#: Completeness is pinned by a test: every field of every type in
#: :data:`RECORD_TYPES` appears here, so a field added without a
#: classification fails the suite rather than defaulting to something.
FIELD_CLASS: Mapping[tuple[str, str], FieldClass] = {
    # A provider's account of where it read something.
    ("Provenance", "adapter_id"): _SOURCED,
    ("Provenance", "schema_version"): _SOURCED,
    ("Provenance", "source"): _SOURCED,
    ("Provenance", "source_sha256"): _SOURCED,
    # A citation, written by a person; only the digest is computed.
    ("AuthorityDelegation", "domain"): _AUTHORED_DATA,
    ("AuthorityDelegation", "to_class"): _AUTHORED_DATA,
    ("AuthorityDelegation", "stated_in"): _AUTHORED_DATA,
    ("AuthorityRef", "id"): _AUTHORED_DATA,
    ("AuthorityRef", "authority_class"): _AUTHORED_DATA,
    ("AuthorityRef", "source"): _AUTHORED_DATA,
    ("AuthorityRef", "section"): _AUTHORED_DATA,
    ("AuthorityRef", "content_sha256"): _SOURCED,
    ("AuthorityRef", "status"): _AUTHORED_DATA,
    ("AuthorityRef", "delegates"): _AUTHORED_DATA,
    ("ExampleRef", "id"): _AUTHORED_DATA,
    ("ExampleRef", "source"): _AUTHORED_DATA,
    # Teaching knowledge: five prose fields, the rest references.
    ("ConceptRecord", "id"): _AUTHORED_DATA,
    ("ConceptRecord", "term"): _AUTHORED_DATA,
    ("ConceptRecord", "summary"): _AUTHORED_PROSE,
    ("ConceptRecord", "plain_definition"): _AUTHORED_PROSE,
    ("ConceptRecord", "purpose"): _AUTHORED_PROSE,
    ("ConceptRecord", "use_when"): _AUTHORED_PROSE,
    ("ConceptRecord", "do_not_use_when"): _AUTHORED_PROSE,
    ("ConceptRecord", "governed_by"): _AUTHORED_DATA,
    ("ConceptRecord", "examples"): _AUTHORED_DATA,
    # A written form and a typed edge: authored, and neither is prose. The
    # voice rule must not reach `syntax` — a declaration skeleton is a
    # quotation of the language, and rewording it would make it false.
    ("ConceptRecord", "syntax"): _AUTHORED_DATA,
    ("ConceptRecord", "related_concepts"): _AUTHORED_DATA,
    # A served capability: derived, except the exception reason and the
    # authority a person cites for it.
    ("SurfaceRecord", "id"): _SOURCED,
    ("SurfaceRecord", "channel"): _SOURCED,
    ("SurfaceRecord", "public_name"): _SOURCED,
    ("SurfaceRecord", "intent"): _SOURCED,
    ("SurfaceRecord", "component_refs"): _SOURCED,
    ("SurfaceRecord", "manual_exception"): _AUTHORED_PROSE,
    ("SurfaceRecord", "governed_by"): _AUTHORED_DATA,
    ("SurfaceRecord", "side_effects"): _SOURCED,
    ("SurfaceRecord", "errors"): _SOURCED,
    ("SurfaceRecord", "provenance"): _SOURCED,
    # Journeys and their steps are written, not derived.
    ("JourneyStep", "surface"): _AUTHORED_DATA,
    ("JourneyStep", "purpose"): _AUTHORED_PROSE,
    ("JourneyStep", "expected_outcome"): _AUTHORED_PROSE,
    # What a reader is told before they approve something irreversible.
    # Prose, so the voice rule reaches it: this is the sentence that has
    # to be plain, and it is the one a person acts on.
    ("JourneyStep", "approval_boundary"): _AUTHORED_PROSE,
    ("RecoveryPath", "when"): _AUTHORED_PROSE,
    ("RecoveryPath", "next_surface"): _AUTHORED_DATA,
    ("RecoveryPath", "action"): _AUTHORED_PROSE,
    ("JourneyRecord", "id"): _AUTHORED_DATA,
    ("JourneyRecord", "intent"): _AUTHORED_PROSE,
    ("JourneyRecord", "steps"): _AUTHORED_DATA,
    ("JourneyRecord", "recovery_paths"): _AUTHORED_DATA,
    # Three lists of references a person writes. Data, never prose: the
    # voice rule must not reach a citation, and a teaching order is an
    # ordered list of ids rather than something anyone reads as a sentence.
    ("JourneyRecord", "concepts_taught"): _AUTHORED_DATA,
    ("JourneyRecord", "concepts_required"): _AUTHORED_DATA,
    ("JourneyRecord", "evidence"): _AUTHORED_DATA,
    ("TeachingStep", "topic"): _AUTHORED_DATA,
    ("TeachingStep", "purpose"): _AUTHORED_PROSE,
    ("TeachingSequence", "id"): _AUTHORED_DATA,
    ("TeachingSequence", "steps"): _AUTHORED_DATA,
    # A catalog row: a written title over derived-or-written locations.
    ("DocumentRecord", "id"): _AUTHORED_DATA,
    ("DocumentRecord", "title"): _AUTHORED_PROSE,
    ("DocumentRecord", "canonical_source"): _AUTHORED_DATA,
    ("DocumentRecord", "prose_locator"): _AUTHORED_DATA,
    ("DocumentRecord", "governed_by"): _AUTHORED_DATA,
    ("DocumentRecord", "covers"): _AUTHORED_DATA,
    # An id a person writes, citing the authority this document is. Data,
    # never prose: the voice rule must not reach a citation.
    ("DocumentRecord", "authority"): _AUTHORED_DATA,
    # Two ids a person wrote down as naming one thing. Data, never prose:
    # an alias is an identifier, and the voice rule must not reach one.
    ("AliasEntry", "id"): _AUTHORED_DATA,
    ("AliasEntry", "canonical"): _AUTHORED_DATA,
    # Facts of the build, all three computed or read at build time.
    ("BuildStamp", "schema"): _SOURCED,
    ("BuildStamp", "release_version"): _SOURCED,
    ("BuildStamp", "snapshot_hash"): _SOURCED,
    ("BuildStamp", "build_channel"): _SOURCED,
}


def field_class(record_type: type[Any], field_name: str) -> FieldClass:
    """Who writes ``field_name`` on ``record_type``.

    Raises :class:`DocsModelError` for an unclassified field rather than
    guessing, because guessing here decides which rules a field escapes.
    """
    try:
        return FIELD_CLASS[(record_type.__name__, field_name)]
    except KeyError:
        raise DocsModelError(
            f"{record_type.__name__}.{field_name} has no authored-or-sourced "
            f"classification; add one to FIELD_CLASS before any gate reads it"
        ) from None


def authored_prose_fields(record_type: type[Any]) -> tuple[str, ...]:
    """The fields of ``record_type`` a person writes as prose, in order."""
    return tuple(
        item.name
        for item in fields(record_type)
        if FIELD_CLASS.get((record_type.__name__, item.name)) is _AUTHORED_PROSE
    )


# ---------------------------------------------------------------------------
# The single-paragraph rule
# ---------------------------------------------------------------------------


def validate_single_paragraph(record: Any) -> None:
    """Refuse a blank line inside any authored prose field of ``record``.

    In this version a teaching field is one paragraph. The reason is
    channel residue: comparing a wrapped, indented terminal block against
    an unwrapped page paragraph needs whitespace collapsed, and collapsing
    whitespace erases paragraph structure — so a channel could silently
    drop a paragraph break and no check would notice. Refusing the break
    keeps every channel comparable while nothing in the corpus needs long
    form.

    **This function is where a multi-paragraph decision lands.** Allowing
    two paragraphs means teaching the channel comparison to preserve
    structure first; the two changes go together, and nothing else in the
    model has to move.
    """
    if not dataclasses.is_dataclass(record) or isinstance(record, type):
        return
    for name in authored_prose_fields(type(record)):
        value = getattr(record, name)
        if not isinstance(value, str):
            continue
        # An empty field is a different question — whether a field may be
        # empty at all is a resolution gate's business, not this rule's —
        # and surrounding whitespace is not a paragraph break, so only the
        # blank lines *inside* written text are refused.
        written = value.strip()
        if not written:
            continue
        for line in written.split("\n"):
            if not line.strip():
                raise DocsModelError(
                    f"{type(record).__name__}.{name} contains a blank line. "
                    f"In this version of the model a teaching field is a "
                    f"single paragraph — write it as one paragraph, or raise "
                    f"the multi-paragraph question at the milestone that "
                    f"needs it."
                )
