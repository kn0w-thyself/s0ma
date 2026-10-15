"""Run every provider, merge one bundle, and report what cannot be merged.

Milestone C2 of the docs-function plan (internal) §8. Providers read their
sources independently and never see each other; this is the only place
their results meet, so it is the only place the duplicate rule can be
applied — and the only place a build can become order-dependent.

The rule, exactly as plan §5 froze it (as corrected at the B gate, B7
report §6 row 6):

* two providers emitting one id with **different** facts is a build
  error, and the error names **both** provenances;
* the same id with **identical** facts is not a conflict — two providers
  deriving one truth from two sources is the normal case the moment the
  application has more than one provider — and merges to one record whose
  surviving provenance is the first-sorting ``(provider_id, source)``.

"Identical facts" is :func:`~s0ma_dsl.docs_model.serialize.facts_hash`,
which C1 built for this comparison: it covers everything a record claims
and excludes the provenance that carries the claim. Comparing whole
records instead would make agreement impossible, since two providers
reading two sources have different provenance by definition.

**Determinism.** The composed bundle is invariant under the order the
providers were registered in, under ``PYTHONHASHSEED``, and across
platforms. Three things make that true and all three are load-bearing:

1. every claimant of an id is collected *before* any of them is judged,
   so a three-way disagreement reports the same finding whichever
   provider ran first;
2. the survivor is chosen by a total order on provenance rather than by
   arrival;
3. every group is sorted by id before the bundle is built —
   :func:`~s0ma_dsl.docs_model.serialize.snapshot_hash` hashes the groups
   as it finds them, so an unsorted group would put the provider order
   into the snapshot digest.

**Failure shape.** :func:`compose` always returns a
:class:`Composition` — a bundle *and* the findings — because a build that
stops at the first duplicate makes an author fix one collision per run.
:func:`compose_or_raise` is the build-mode wrapper that turns any finding
into the structured error the plan calls for. When facts do disagree the
bundle still holds one of the claimants, chosen by the same total order:
that is determinism in the presence of a reported error, not a
resolution of it, and the build is refused either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.providers import (
    DocsProviderError,
    Finding,
    ProviderResult,
    SourcedRecord,
    sort_findings,
)
from s0ma_dsl.docs_model.records import (
    PREVIEW_CHANNEL,
    SCHEMA,
    AuthorityRef,
    BuildStamp,
    ConceptRecord,
    DocsBundle,
    DocsModelError,
    DocumentRecord,
    JourneyRecord,
    Provenance,
    SurfaceRecord,
    TeachingSequence,
)
from s0ma_dsl.docs_model.serialize import facts_hash, stamped

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from s0ma_dsl.docs_model.providers import DocProvider, ProviderRegistry

__all__ = [
    "DOC_CANONICAL_DUPLICATE",
    "Composition",
    "DocsCompositionError",
    "compose",
    "compose_or_raise",
    "merge",
]

#: Architecture plan §11: "More than one current canonical source claims
#: the same document id or factual inventory."
DOC_CANONICAL_DUPLICATE = "DOC_CANONICAL_DUPLICATE"


class DocsCompositionError(DocsModelError):
    """A build was composed from records that cannot all be true.

    Carries the findings rather than a formatted string, so a caller can
    report them its own way; :meth:`report` is the default rendering.
    """

    def __init__(self, findings: Sequence[Finding]) -> None:
        self.findings = tuple(findings)
        super().__init__(self.report())

    def report(self) -> str:
        """Every finding, one per line, in reporting order."""
        lines = [finding.rendered() for finding in self.findings]
        return "\n".join([f"the documentation build reported {len(lines)} finding(s):", *lines])


@dataclass(frozen=True)
class Composition:
    """One build: the bundle, where each record came from, and what is wrong.

    Three things beside the bundle, each because something needs it:

    ``survivors``
        Every merged record still paired with the provenance that
        survived. Without this the merge rule would be unobservable for
        five of the six record types — only ``SurfaceRecord`` carries a
        provenance field of its own — and SDA-INV-10 says provenance
        survives every projection, not only the projections of surfaces.
    ``results``
        What each provider produced, before the merge. The anti-vacuity
        floors ask whether a *provider* resolved empty, and provenance
        completeness asks about every record a provider handed over,
        including one that merged away.
    ``findings``
        What stops the build. Empty is the only good answer.
    """

    bundle: DocsBundle
    survivors: tuple[SourcedRecord, ...]
    results: tuple[ProviderResult, ...]
    findings: tuple[Finding, ...]

    @property
    def ok(self) -> bool:
        """True when nothing was found. Composition findings are refusals."""
        return not self.findings

    def provenance_of(self, record_id: str) -> Provenance:
        """Where the surviving record with this id was read from."""
        wanted = normalize_id(record_id)
        for item in self.survivors:
            if normalize_id(item.record.id) == wanted:
                return item.provenance
        raise DocsModelError(f"this build composed nothing called {record_id!r}")


def _survivor_key(item: SourcedRecord) -> tuple[str, str, str, str]:
    """The total order the merge rule picks a survivor with.

    Plan §5 names the leading pair — ``(provider_id, source)`` — and says
    nothing about a tie inside it, because two records from one provider
    and one source with identical facts are the same record read twice.
    The remaining two fields make even that case decide, so the survivor
    is a function of the records alone and never of arrival order.
    """
    provenance = item.provenance
    return (
        provenance.adapter_id,
        provenance.source,
        provenance.source_sha256,
        provenance.schema_version,
    )


def _duplicate_finding(record_id: str, claimants: Sequence[SourcedRecord]) -> Finding:
    """One finding naming every provenance that claimed ``record_id``.

    One finding rather than one per pair: an author reading it needs the
    whole set of claimants, and pairwise findings over three claimants
    would depend on the order the pairs were formed.
    """
    lines = [
        f"  {item.provenance.adapter_id} read {item.provenance.source} "
        f"(facts {facts_hash(item.record)})"
        for item in claimants
    ]
    adapters = sorted({item.provenance.adapter_id for item in claimants})
    return Finding(
        code=DOC_CANONICAL_DUPLICATE,
        location=claimants[0].provenance.source,
        message="\n".join(
            [
                f"{record_id} is claimed by {len(claimants)} records with "
                f"different facts, which is a build error and never a merge:",
                *lines,
            ]
        ),
        remediation=(
            f"all but one of {', '.join(adapters)} must stop claiming "
            f"{record_id}, or every account of it must agree fact for fact. "
            f"Identical facts from two sources merge on their own; only a "
            f"disagreement stops here."
        ),
    )


def merge(
    results: Iterable[ProviderResult],
) -> tuple[dict[str, SourcedRecord], tuple[Finding, ...]]:
    """Every provider's records, merged by id, with the duplicates reported.

    Returns the survivors keyed by normalized id, and the findings. The
    keys are normalized (plan §5: identity gates compare a studi0 route
    slash-stripped) even though :class:`ProviderResult` already refuses an
    un-normalized id — the merge is where identity is decided, so it does
    not delegate the question.
    """
    claims: dict[str, list[SourcedRecord]] = {}
    for result in results:
        for item in result.records:
            claims.setdefault(normalize_id(item.record.id), []).append(item)

    kept: dict[str, SourcedRecord] = {}
    findings: list[Finding] = []
    for record_id in sorted(claims):
        claimants = sorted(claims[record_id], key=_survivor_key)
        distinct: dict[str, SourcedRecord] = {}
        for item in claimants:
            distinct.setdefault(facts_hash(item.record), item)
        if len(distinct) > 1:
            findings.append(_duplicate_finding(record_id, claimants))
        # The first-sorting claimant survives either way. Where the facts
        # agree that is the merge rule; where they do not it is only
        # determinism, and the finding above is what stops the build.
        kept[record_id] = claimants[0]
    return kept, tuple(findings)


def _bundle_of(
    kept: dict[str, SourcedRecord], release_version: str, build_channel: str
) -> DocsBundle:
    """The survivors as a stamped bundle, every group sorted by id.

    The records are sorted into their groups by type rather than through
    ``providers.RECORD_GROUPS``, because a bundle's six fields have six
    different element types and the dispatch has to be one a type checker
    can follow. ``group_of`` reads the same table for the counts and the
    floors, so the two cannot disagree about what a group holds.
    """
    authorities: list[AuthorityRef] = []
    concepts: list[ConceptRecord] = []
    surfaces: list[SurfaceRecord] = []
    journeys: list[JourneyRecord] = []
    sequences: list[TeachingSequence] = []
    documents: list[DocumentRecord] = []
    for record_id in sorted(kept):
        record = kept[record_id].record
        if isinstance(record, AuthorityRef):
            authorities.append(record)
        elif isinstance(record, ConceptRecord):
            concepts.append(record)
        elif isinstance(record, SurfaceRecord):
            surfaces.append(record)
        elif isinstance(record, JourneyRecord):
            journeys.append(record)
        elif isinstance(record, TeachingSequence):
            sequences.append(record)
        elif isinstance(record, DocumentRecord):
            documents.append(record)
        else:
            raise DocsProviderError(
                f"{type(record).__name__} is not a record type a bundle carries"
            )

    unstamped = DocsBundle(
        stamp=BuildStamp(schema=SCHEMA, release_version="", snapshot_hash=""),
        authorities=tuple(sorted(authorities, key=lambda item: item.id)),
        concepts=tuple(sorted(concepts, key=lambda item: item.id)),
        surfaces=tuple(sorted(surfaces, key=lambda item: item.id)),
        journeys=tuple(sorted(journeys, key=lambda item: item.id)),
        sequences=tuple(sorted(sequences, key=lambda item: item.id)),
        documents=tuple(sorted(documents, key=lambda item: item.id)),
    )
    return stamped(unstamped, release_version, build_channel=build_channel)


def compose(
    registry: ProviderRegistry,
    *,
    release_version: str,
    build_channel: str = PREVIEW_CHANNEL,
) -> Composition:
    """Run every registered provider once and merge one bundle out of them.

    Providers run in registration order and each is called exactly once.
    Neither fact reaches the result: the bundle, its snapshot digest and
    the findings are all functions of the records alone.

    ``build_channel`` is carried to the stamp and nowhere else (H1). It is
    a caller's declaration rather than something this function works out,
    for the reason every other input here is: composition reads sources
    and merges records, and asking a repository what tag it is standing on
    would be a reading of something that is not a documentation source —
    and, on a tree with no tags at all, a reading with no answer. The
    derivation rule lives in
    :func:`~s0ma_dsl.docs_model.manifest.channel_of`, which takes the tag
    as a value.
    """
    providers: tuple[DocProvider, ...] = registry.providers()
    results = tuple(provider.provide() for provider in providers)
    for provider, result in zip(providers, results, strict=True):
        if result.provider_id != provider.provider_id:
            raise DocsProviderError(
                f"provider registered as {provider.provider_id!r} returned a "
                f"result stamped {result.provider_id!r}. The registry's key and "
                f"the result's id are the same identity, and the merge rule "
                f"reads the second one."
            )
    kept, findings = merge(results)
    return Composition(
        bundle=_bundle_of(kept, release_version, build_channel),
        survivors=tuple(kept[record_id] for record_id in sorted(kept)),
        results=tuple(sorted(results, key=lambda item: item.provider_id)),
        findings=sort_findings(findings),
    )


def compose_or_raise(
    registry: ProviderRegistry,
    *,
    release_version: str,
    build_channel: str = PREVIEW_CHANNEL,
) -> DocsBundle:
    """The bundle, or a structured error naming everything that is wrong.

    Build mode (SDA-INV-9): a build either produces documentation that is
    true or produces nothing. Check mode calls :func:`compose` instead and
    reports the findings.
    """
    composition = compose(
        registry, release_version=release_version, build_channel=build_channel
    )
    if not composition.ok:
        raise DocsCompositionError(composition.findings)
    return composition.bundle
