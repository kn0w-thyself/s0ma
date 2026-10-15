"""The contract every documentation source adapter is held to.

Milestone C2 of the docs-function plan (internal) §8, implementing the
provider contract frozen by that plan's §5 and written out in the
architecture plan's §7.1:

```text
input              immutable source path/artifact/snapshot
output             sorted normalized records
provenance         adapter id + source identity + schema version + content hash
side effects       none
network            forbidden
filesystem writes  forbidden
errors             structured, source-located, non-lossy
```

Four of those seven lines are enforced here, at the boundary where the
cost of enforcing them is a few lines and the cost of not enforcing them
is a build whose output depends on who ran first:

* **sorted** — :class:`ProviderResult` refuses records that are not in
  order. Composition sorts anyway; a provider that hands over an
  arbitrary order is still wrong, because the order is what a reviewer
  reads and what a future in-provider gate would walk.
* **normalized** — every id must already be its comparable form
  (:func:`~s0ma_dsl.docs_model.ids.normalize_id`). The one id form that
  normalizes to something else is a studi0 route, and a provider that
  hands over the served name rather than the id is caught in the
  constructor rather than three merges later.
* **provenance** — every record enters composition inside a
  :class:`SourcedRecord`, so no record can arrive without an account of
  where it came from. A record type that carries its own provenance
  field must agree with the one the provider stamped, or construction
  refuses: two accounts of one origin that disagree is the exact failure
  provenance exists to prevent.
* **errors** — :class:`Finding` is the structured, source-located,
  non-lossy form. It lives here rather than in the composition or the
  gates because it is part of *this* contract; both of those import it.

The three that are **not** enforceable from here — no side effects, no
network, no filesystem writes — are honest documentation plus one
structural guard: :class:`ProviderRegistry` is keyed by provider id and
refuses a second registration of one id, so two adapters cannot quietly
share an identity and blame each other's output. A provider that opens a
socket is caught by the offline proof its own milestone owns (B3 armed a
socket guard for exactly this), not by a type.

Nothing here reads the filesystem, imports ``s0ma``, ``s0ma_mcp`` or
``s0ma_studi0``, or knows what any particular provider does. It is the
vocabulary four of them will share.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.records import (
    AuthorityRef,
    ConceptRecord,
    DocsModelError,
    DocumentRecord,
    JourneyRecord,
    Provenance,
    SurfaceRecord,
    TeachingSequence,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "GROUP_NAMES",
    "RECORD_GROUPS",
    "DocProvider",
    "DocsProviderError",
    "DocsRecord",
    "Finding",
    "ProviderRegistry",
    "ProviderResult",
    "SourcedRecord",
    "group_of",
    "record_key",
    "sort_findings",
    "sort_records",
]


class DocsProviderError(DocsModelError):
    """A provider broke the contract every provider is held to.

    Distinct from a :class:`Finding` on purpose. A finding is something
    wrong with the *documentation*, reported and collected so an author
    sees every problem at once. This is something wrong with the
    *provider* — an unsorted result, an unstamped record, two adapters
    claiming one id — which no author can fix and which makes the rest of
    the run meaningless, so it is raised where it happens.
    """


#: Every record type a provider may emit. The union is the model's, not
#: this module's: it is exactly the six groups :class:`DocsBundle`
#: declares, and a seventh record type would be a schema change.
DocsRecord = (
    AuthorityRef
    | ConceptRecord
    | DocumentRecord
    | JourneyRecord
    | SurfaceRecord
    | TeachingSequence
)

#: The bundle's groups, in the order :class:`DocsBundle` declares them.
GROUP_NAMES: tuple[str, ...] = (
    "authorities",
    "concepts",
    "surfaces",
    "journeys",
    "sequences",
    "documents",
)

#: Which group each record type lands in. A provider needs this to know
#: what it may emit, the composition needs it to build a bundle, and the
#: anti-vacuity floors need it to name what came out empty — one table,
#: read by all three, so they cannot disagree about what a "surface" is.
RECORD_GROUPS: Mapping[type[Any], str] = {
    AuthorityRef: "authorities",
    ConceptRecord: "concepts",
    SurfaceRecord: "surfaces",
    JourneyRecord: "journeys",
    TeachingSequence: "sequences",
    DocumentRecord: "documents",
}


def group_of(record: DocsRecord) -> str:
    """The bundle group ``record`` belongs to, refusing an unknown type."""
    try:
        return RECORD_GROUPS[type(record)]
    except KeyError:
        raise DocsProviderError(
            f"{type(record).__name__} is not a record type a bundle carries. "
            f"A provider may emit: "
            f"{', '.join(sorted(item.__name__ for item in RECORD_GROUPS))}."
        ) from None


# ---------------------------------------------------------------------------
# Structured findings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Finding:
    """One thing wrong with the documentation, said so a person can fix it.

    Four parts, because a finding with fewer than four is a finding
    somebody has to research before they can act on it:

    ``code``
        A ``DOC_*`` name. The architecture plan's §11 froze the names for
        the failure classes it foresaw; where none fits, the code is
        listed in ``validate.MINTED_CODES`` with the reason it exists,
        the way C1 flagged the ``sequence:`` id form for ratification.
    ``message``
        What is wrong, naming the records involved by id.
    ``remediation``
        What to write instead. Required, not optional: a gate that says
        only "no" is a gate people learn to disable.
    ``location``
        Where to go, as far as the model knows — the source a record
        itself names. Empty where the record names none, which in this
        version of the model is the honest answer for a concept, a
        journey and a teaching sequence: nothing in ``@1`` records the
        file an authored record was written in. The field order puts
        ``code`` first so the natural sort groups a run by failure class.

    Findings are collected, never raised. A build with three unresolved
    references should report three, not the first one.
    """

    code: str
    location: str
    message: str
    remediation: str

    def rendered(self) -> str:
        """The one-line form: ``<location>: <code>: <message>``.

        The location is omitted rather than rendered as an empty field,
        so a finding the model cannot place reads as a sentence instead
        of as a broken path.
        """
        if not self.location:
            return f"{self.code}: {self.message}"
        return f"{self.location}: {self.code}: {self.message}"


def sort_findings(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    """Findings in their reporting order, with exact repeats removed.

    Two gates asking the same question of the same record — the surface
    binding rule and the reference resolver, for instance — produce one
    finding, not two. The order is the dataclass order: code, then
    location, then message, then remediation, so a report groups by
    failure class and a run of the same build reports identically.
    """
    return tuple(sorted(set(findings)))


# ---------------------------------------------------------------------------
# What a provider hands over
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourcedRecord:
    """One record and the provider's account of where it came from.

    Every record enters composition through this, not just the ones whose
    type happens to carry a provenance field. Two reasons, and the second
    is the load-bearing one:

    1. ``DOC_PROVENANCE_MISSING`` is checkable for authored records too.
       A concept nobody can trace to a file is as unfixable as a surface
       nobody can trace to a registry.
    2. The merge rule's survivor is "the first-sorting
       ``(provider_id, source)``" (plan §5). For an authored record there
       is nowhere else that pair could come from.

    Where the record carries its own provenance — ``SurfaceRecord`` is
    the only one in ``@1`` — the two must be equal. A record's account of
    its origin and its provider's account of the same origin disagreeing
    is precisely what provenance exists to prevent, so it is refused at
    construction rather than reported later.
    """

    record: DocsRecord
    provenance: Provenance

    def __post_init__(self) -> None:
        own = getattr(self.record, "provenance", None)
        if own is not None and own != self.provenance:
            raise DocsProviderError(
                f"{self.record.id} carries its own provenance "
                f"({own.adapter_id} / {own.source}) and the provider stamped a "
                f"different one ({self.provenance.adapter_id} / "
                f"{self.provenance.source}). One record has one origin — pass "
                f"the record's own provenance, or use SourcedRecord.of()."
            )

    @property
    def id(self) -> str:
        """The record's id, so a sort key does not have to reach inside."""
        return self.record.id

    @classmethod
    def of(cls, record: SurfaceRecord) -> SourcedRecord:
        """Wrap a record that already carries its provenance."""
        return cls(record=record, provenance=record.provenance)


def record_key(item: SourcedRecord) -> tuple[str, str, str]:
    """The sort key for a provider's records: id, then where it came from.

    Sorting by id alone leaves two records with one id in an order that
    depends on how the provider happened to build them. The provenance
    breaks the tie the same way the merge rule breaks it, so a provider's
    own order and the composition's survivor rule agree.
    """
    return (item.record.id, item.provenance.adapter_id, item.provenance.source)


def sort_records(records: Iterable[SourcedRecord]) -> tuple[SourcedRecord, ...]:
    """Records in contract order. What a provider calls before returning."""
    return tuple(sorted(records, key=record_key))


@dataclass(frozen=True)
class ProviderResult:
    """What one provider returns: its id, and its records, in order.

    There is deliberately no ``sources`` field. The sources are already
    on the records — one per record, with its digest — and a second list
    of them would be a copy that can disagree with the first. Ask
    :meth:`sources` instead.
    """

    provider_id: str
    records: tuple[SourcedRecord, ...]

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise DocsProviderError(
                "a provider result carries no provider id; the merge rule's "
                "survivor is the first-sorting (provider_id, source), so an "
                "unnamed provider makes the result order-dependent"
            )
        for item in self.records:
            normalized = normalize_id(item.record.id)
            if normalized != item.record.id:
                raise DocsProviderError(
                    f"provider {self.provider_id!r} emitted {item.record.id!r}, "
                    f"which is not the comparable form of that id. Write "
                    f"{normalized!r} — identity comparisons run on the "
                    f"normalized form, so an un-normalized id silently fails "
                    f"to merge with the same thing under its real name."
                )
        if list(self.records) != sorted(self.records, key=record_key):
            raise DocsProviderError(
                f"provider {self.provider_id!r} returned its records out of "
                f"order. The contract says sorted; call sort_records() before "
                f"returning."
            )

    def sources(self) -> tuple[tuple[str, str], ...]:
        """Every distinct ``(source, digest)`` the records were read from."""
        distinct = {
            (item.provenance.source, item.provenance.source_sha256) for item in self.records
        }
        return tuple(sorted(distinct))

    def counts(self) -> dict[str, int]:
        """How many records this provider produced, per bundle group.

        Every group appears, including the empty ones. A floor on a group
        a provider stopped producing has to be able to see the zero.
        """
        counted = dict.fromkeys(GROUP_NAMES, 0)
        for item in self.records:
            counted[group_of(item.record)] += 1
        return counted


# ---------------------------------------------------------------------------
# The provider itself
# ---------------------------------------------------------------------------


class DocProvider(Protocol):
    """A source adapter: an id, and one deterministic reading of a source.

    ``provide`` takes no arguments on purpose. A provider is configured
    when it is built and reads nothing at call time, so calling it twice
    in one process must produce equal results — which is what makes the
    composition's determinism provable rather than asserted.

    Implementations must not write files, open sockets, mutate anything
    they were given, or read another provider's output. Providers run
    independently; composition is the only thing that sees them all.

    ``provider_id`` is declared read-only so a frozen dataclass, a plain
    attribute and a property all satisfy it. It must equal the
    ``adapter_id`` the provider stamps on its records' provenance —
    ``adapter_id`` is the model's word for the same thing, and plan §5
    speaks of ``(provider_id, source)``.
    """

    @property
    def provider_id(self) -> str:
        """This adapter's stable id, unique across the registry."""

    def provide(self) -> ProviderResult:
        """Read the configured source and return its records, sorted."""


class ProviderRegistry:
    """The providers of one build, keyed by id, each registered once.

    This is where "no two adapters share an identity" is enforced. It
    matters more than it looks: the merge rule breaks every tie with
    ``(provider_id, source)``, so two providers answering to one id make
    the surviving record depend on which of them ran first — the one
    thing the composition promises cannot happen.

    Registration order is kept, and the composition runs providers in it.
    That is deliberate: sorting the registry would make order-independence
    true by construction and therefore unprovable. The composition's
    result is order-independent because the *merge* is, and a permutation
    test proves it.
    """

    def __init__(self) -> None:
        self._providers: dict[str, DocProvider] = {}

    @classmethod
    def of(cls, *providers: DocProvider) -> ProviderRegistry:
        """A registry holding ``providers``, in the order given."""
        registry = cls()
        for provider in providers:
            registry.register(provider)
        return registry

    def register(self, provider: DocProvider) -> None:
        """Add ``provider``, refusing a second one under the same id."""
        provider_id = getattr(provider, "provider_id", None)
        if not isinstance(provider_id, str) or not provider_id:
            raise DocsProviderError(
                f"{type(provider).__name__} has no provider id; every provider "
                f"is registered under a stable id and the merge rule reads it"
            )
        if not callable(getattr(provider, "provide", None)):
            raise DocsProviderError(
                f"provider {provider_id!r} has no provide() method; a provider "
                f"is a source reading, and provide() is the reading"
            )
        held = self._providers.get(provider_id)
        if held is not None:
            raise DocsProviderError(
                f"provider id {provider_id!r} is already registered, by "
                f"{type(held).__name__}; {type(provider).__name__} cannot "
                f"share it. Two providers under one id make the merge rule's "
                f"survivor depend on which ran first."
            )
        self._providers[provider_id] = provider

    def providers(self) -> tuple[DocProvider, ...]:
        """Every registered provider, in registration order."""
        return tuple(self._providers.values())

    def ids(self) -> tuple[str, ...]:
        """Every registered provider id, sorted."""
        return tuple(sorted(self._providers))

    def __contains__(self, provider_id: object) -> bool:
        return provider_id in self._providers

    def __len__(self) -> int:
        return len(self._providers)
