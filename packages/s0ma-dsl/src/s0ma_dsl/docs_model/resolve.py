"""What a question resolves to, what a topic says, and how a channel says it.

Milestone C7 of the docs-function plan (internal) §8, task T1. Three things
live here, and they are one thing looked at from three sides:

``TopicIndex`` / :func:`resolve`
    A question in, a topic out — or a ranked list of what it could have
    meant, or a structured miss. Pure, total, and deterministic: the same
    index and the same question give the same answer on any platform,
    under any hash seed.
``TopicView`` / :func:`facts_of`
    What a resolved topic *says*, as a flat map of fact name to canonical
    value. This is the one place a record's fields become facts, so the
    three renderers cannot each have their own opinion about what a topic
    carries.
``PresentationSpec``
    The vocabulary a channel declares its presentation in — where it
    writes each fact, in what order, what it adds that carries no fact,
    and what it does to the text on the way out. B5's residue definition
    (``scripts/spikes/docs_model/spike_b5_channels/README.md``, clause 1)
    made this a channel's property rather than a record's; it is here
    rather than in a module of its own because C7's owned surface is the
    resolver and the three renderers, and the type has to sit somewhere
    all four can see it.

**Why the facts are computed once, here.** B5's rule (b) is that a channel
carries a fact word for word or leaves it out. That rule is only checkable
against a single account of what the facts *are*. If each renderer read
the records itself, two renderers could agree with each other and both be
wrong, and the residue comparison would pass. :func:`facts_of` is that
single account, and every renderer and every extractor is compared against
it.

**Why some facts are drawn from the bundle rather than the record.** A
concept cites ``authority:spec/nerve-declaration``; a person reading a page
needs the document that id names. The document is a fact of the authority
record, so ``authority_sources`` is computed here, from the bundle, and
declared as a fact like any other — a channel that shows it must show it
verbatim, and a channel that omits it omits it whole. The alternative,
letting a renderer look up prettier text at layout time, is exactly the
undeclared carrier B5's clause 1 refuses.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.ids import (
    ID_CLASSES,
    AliasIndex,
    id_form,
    normalize_id,
)
from s0ma_dsl.docs_model.providers import (
    DocsRecord,
    Finding,
    group_of,
)
from s0ma_dsl.docs_model.records import (
    AuthorityRef,
    ConceptRecord,
    DocsBundle,
    DocsModelError,
    DocumentRecord,
    JourneyRecord,
    SurfaceRecord,
    TeachingSequence,
)
from s0ma_dsl.docs_model.validate import CHANNEL_EFFECTS, DOC_GATE_VACUOUS, location_of

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "AGENT_SHORT_FACT",
    "COVERAGE_POLICY_SCHEMA",
    "DOC_CAPABILITY_UNCOVERED",
    "DOC_CONCEPT_UNCOVERED",
    "DOC_SURFACE_UNCOVERED",
    "DOC_TOPIC_UNRESOLVED",
    "FACT_ORDER",
    "FOLD_IN",
    "IDENTITY_FACTS",
    "LIST_FACTS",
    "MINTED_CODES",
    "MIN_REASON",
    "NEAREST_LIMIT",
    "PREFIX_FLOOR",
    "RELEASE_MODE",
    "REQUIRED_CHANNELS",
    "Candidate",
    "ChannelException",
    "CoveragePolicy",
    "DocsResolveError",
    "FactValue",
    "MatchClass",
    "PresentationSpec",
    "PrimaryCapability",
    "Renderer",
    "Resolution",
    "SurfaceException",
    "TopicIndex",
    "TopicView",
    "canonical_fact",
    "check_coverage",
    "check_journey_coverage",
    "collapse",
    "coverage_policy_from_mapping",
    "facts_of",
    "nearest",
    "resolve",
    "resolve_all",
]


#: A reference is well formed and names nothing this build knows about.
#: Minted at B6, used unchanged by C2 and reused here for the one question
#: this module answers with a finding: a topic nobody asked a resolvable
#: question about.
DOC_TOPIC_UNRESOLVED = "DOC_TOPIC_UNRESOLVED"


class DocsResolveError(DocsModelError):
    """A resolution or a rendering was asked for something it cannot do."""


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

#: What a fact's value may be. A string is prose or a single identifier; a
#: tuple is an ordered list of them. Nothing else, because the residue
#: comparison has to be able to write every value into text and read it
#: back without knowing what it means.
FactValue = str | tuple[str, ...]

#: The five facts every channel must carry (B5 residue rule (a)). Sorted,
#: because the identity core is compared as a set and a reader meeting it
#: twice should meet it in one order.
IDENTITY_FACTS: tuple[str, ...] = (
    "authority_refs",
    "example_ids",
    "release_version",
    "snapshot_hash",
    "topic_id",
)

#: The facts whose value is an ordered list rather than prose. A list fact
#: is compared element by element and each element verbatim; a prose fact
#: is compared with its whitespace collapsed, because a channel is allowed
#: to wrap it. Getting this wrong in the permissive direction would let a
#: channel drop a line of a syntax skeleton unnoticed, so the classification
#: is data and a proof asserts every fact name appears in it or is prose.
LIST_FACTS: frozenset[str] = frozenset(
    {
        "approval_boundaries",
        "authority_refs",
        "authority_sources",
        "component_refs",
        "concepts_required",
        "concepts_taught",
        "covers",
        "delegations",
        "errors",
        "example_ids",
        "recovery_paths",
        "related_concepts",
        "side_effects",
        "step_outcomes",
        "step_purposes",
        "step_surfaces",
        "step_topics",
        "syntax",
    }
)

#: The topical facts of each bundle group, in the order a page presents
#: them. The identity core is not here: it is carried by every group and
#: its order is :data:`IDENTITY_FACTS`.
FACT_ORDER: Mapping[str, tuple[str, ...]] = {
    "concepts": (
        "term",
        "summary",
        "plain_definition",
        "purpose",
        "use_when",
        "do_not_use_when",
        "syntax",
        "related_concepts",
        "authority_sources",
    ),
    "surfaces": (
        "public_name",
        "channel",
        "intent",
        "component_refs",
        "manual_exception",
        "side_effects",
        "errors",
        "read_from",
        "authority_sources",
    ),
    "journeys": (
        "intent",
        "concepts_required",
        "step_surfaces",
        "step_purposes",
        "step_outcomes",
        "approval_boundaries",
        "recovery_paths",
        "concepts_taught",
    ),
    "sequences": ("step_topics", "step_purposes"),
    "documents": (
        "title",
        "canonical_source",
        "prose_locator",
        "authority",
        "covers",
        "authority_sources",
    ),
    "authorities": (
        "authority_class",
        "written_in",
        "section",
        "status",
        "content_sha256",
        "delegations",
    ),
}

#: The one teaching fact the bounded channel carries for each group, beside
#: identity. B5 finding 1 said a bounded channel gets smaller by omitting,
#: never by paraphrasing, so it needs an authored short form to omit *down
#: to*; C1 added ``ConceptRecord.summary`` for exactly that, and this table
#: is where the other five groups say what plays the same part for them.
AGENT_SHORT_FACT: Mapping[str, str] = {
    "concepts": "summary",
    "surfaces": "intent",
    "journeys": "intent",
    "sequences": "",
    "documents": "title",
    "authorities": "written_in",
}


def collapse(text: str) -> str:
    """``text`` with every run of whitespace reduced to one space.

    The transformation that lets a wrapped terminal block and an unwrapped
    page paragraph compare equal. It is safe here only because ``@1``
    refuses a blank line inside authored prose
    (:func:`~s0ma_dsl.docs_model.records.validate_single_paragraph`): a
    paragraph-aware collapse is what a multi-paragraph decision would need
    first, and B5 finding 5 is where that is written down.
    """
    return " ".join(text.split())


def canonical_fact(name: str, value: FactValue) -> FactValue:
    """One fact reduced to the form two channels are compared on.

    Prose collapses; a list keeps every element exactly as written. The
    asymmetry is the point: a channel may re-wrap a sentence and may not
    re-wrap a syntax skeleton.
    """
    if name in LIST_FACTS:
        if isinstance(value, str):
            raise DocsResolveError(f"{name} is a list fact and was given text")
        return tuple(value)
    if not isinstance(value, str):
        raise DocsResolveError(f"{name} is a prose fact and was given a list")
    return collapse(value)


@dataclass(frozen=True)
class TopicView:
    """One resolved topic, and everything it says, read once.

    ``facts`` holds the identity core and the group's topical facts
    together, because a channel writes them together and the residue
    compares them together. ``identity()`` and ``topical()`` split them for
    the two rules that treat them differently — identity is mandatory,
    everything else is verbatim-or-absent.
    """

    id: str
    group: str
    record: DocsRecord
    facts: Mapping[str, FactValue]

    def identity(self) -> dict[str, FactValue]:
        """The five facts no channel may leave out, in their frozen order."""
        return {name: self.facts[name] for name in IDENTITY_FACTS}

    def topical(self) -> dict[str, FactValue]:
        """The group's own facts, in the order a page presents them."""
        return {name: self.facts[name] for name in FACT_ORDER[self.group]}

    def value(self, name: str) -> FactValue:
        """One fact, refusing a name this view does not carry."""
        try:
            return self.facts[name]
        except KeyError:
            raise DocsResolveError(
                f"{self.id} carries no fact called {name!r}; it carries "
                f"{', '.join(sorted(self.facts))}"
            ) from None

    def text(self, name: str) -> str:
        """One prose fact as text, refusing a list fact."""
        value = self.value(name)
        if not isinstance(value, str):
            raise DocsResolveError(f"{name} on {self.id} is a list, not text")
        return value

    def items(self, name: str) -> tuple[str, ...]:
        """One list fact, refusing a prose fact."""
        value = self.value(name)
        if isinstance(value, str):
            raise DocsResolveError(f"{name} on {self.id} is text, not a list")
        return value


def _authority_sources(bundle: DocsBundle, cited: Sequence[str]) -> tuple[str, ...]:
    """Where each cited authority is written, sorted, absent ones skipped.

    An unresolved citation is C2's finding, not a rendering's: a page that
    invented a location for an id nothing answers to would be the worse
    failure. The list is therefore shorter than ``authority_refs`` exactly
    when the build has something wrong with it, and both facts are carried
    so a reader can see which one.
    """
    by_id = {authority.id: authority for authority in bundle.authorities}
    found: list[str] = []
    for identifier in cited:
        authority = by_id.get(normalize_id(identifier))
        if authority is None:
            continue
        found.append(
            f"{authority.source}#{authority.section}" if authority.section else authority.source
        )
    return tuple(sorted(set(found)))


def facts_of(bundle: DocsBundle, record: DocsRecord) -> TopicView:
    """Everything ``record`` says, as facts, stamped with the build it is in.

    The identity core comes from :class:`~s0ma_dsl.docs_model.records.BuildStamp`
    and never from a copy on the record — C1 put ``release_version`` and
    ``snapshot_hash`` on the stamp and nowhere else for this reason, and
    :data:`~s0ma_dsl.docs_model.records.BUILD_STAMP_ONLY_FIELDS` is what
    keeps a second copy from appearing.

    The version fact is
    :meth:`~s0ma_dsl.docs_model.records.BuildStamp.version_line` rather
    than the bare field (H1, architecture §13.2). A preview build's pages
    say ``0.18.1 (preview)`` and a release build's say ``0.18.1``, and the
    labelling happens *here*, once, rather than in each renderer — which
    is what makes it true of every channel at the same time. Three of them
    read this function: the human page, the bounded agent response and the
    learning collection, so "visibly labelled in every rendered identity
    line" is a property of one expression instead of a rule three modules
    have to remember.
    """
    group = group_of(record)
    facts: dict[str, FactValue] = {
        "topic_id": record.id,
        "example_ids": (),
        "authority_refs": (),
        "release_version": bundle.stamp.version_line(),
        "snapshot_hash": bundle.stamp.snapshot_hash,
    }

    if isinstance(record, ConceptRecord):
        facts["example_ids"] = tuple(sorted(item.id for item in record.examples))
        facts["authority_refs"] = tuple(sorted(record.governed_by))
        facts["term"] = record.term
        facts["summary"] = record.summary
        facts["plain_definition"] = record.plain_definition
        facts["purpose"] = record.purpose
        facts["use_when"] = record.use_when
        facts["do_not_use_when"] = record.do_not_use_when
        facts["syntax"] = tuple(record.syntax)
        facts["related_concepts"] = tuple(
            sorted(" ".join(edge) for edge in record.related_concepts)
        )
        facts["authority_sources"] = _authority_sources(bundle, record.governed_by)
    elif isinstance(record, SurfaceRecord):
        facts["authority_refs"] = tuple(sorted(record.governed_by))
        facts["public_name"] = record.public_name
        facts["channel"] = record.channel
        facts["intent"] = record.intent
        facts["component_refs"] = tuple(sorted(record.component_refs))
        facts["manual_exception"] = record.manual_exception
        facts["side_effects"] = tuple(sorted(record.side_effects))
        facts["errors"] = tuple(sorted(record.errors))
        facts["read_from"] = record.provenance.source
        facts["authority_sources"] = _authority_sources(bundle, record.governed_by)
    elif isinstance(record, JourneyRecord):
        # A journey's evidence *is* its worked examples, so it is carried
        # on the identity fact every channel already writes rather than
        # under a name only this group would know — which is what lets the
        # evidence E2 lands reach all three channels without a renderer
        # learning anything new about journeys.
        facts["example_ids"] = tuple(sorted(item.id for item in record.evidence))
        facts["intent"] = record.intent
        facts["concepts_required"] = tuple(record.concepts_required)
        facts["step_surfaces"] = tuple(step.surface for step in record.steps)
        facts["step_purposes"] = tuple(step.purpose for step in record.steps)
        facts["step_outcomes"] = tuple(step.expected_outcome for step in record.steps)
        facts["approval_boundaries"] = record.approval_boundaries()
        facts["recovery_paths"] = tuple(
            f"{path.when} -> {path.next_surface}: {path.action}"
            for path in record.recovery_paths
        )
        # Not sorted, unlike every other id list in this reading: the
        # teaching order is the fact, and sorting it would throw away the
        # only thing it says.
        facts["concepts_taught"] = tuple(record.concepts_taught)
    elif isinstance(record, TeachingSequence):
        facts["step_topics"] = tuple(step.topic for step in record.steps)
        facts["step_purposes"] = tuple(step.purpose for step in record.steps)
    elif isinstance(record, DocumentRecord):
        facts["authority_refs"] = tuple(sorted(record.governed_by))
        facts["title"] = record.title
        facts["canonical_source"] = record.canonical_source
        facts["prose_locator"] = record.prose_locator
        facts["authority"] = record.authority
        facts["covers"] = tuple(sorted(record.covers))
        facts["authority_sources"] = _authority_sources(bundle, record.governed_by)
    elif isinstance(record, AuthorityRef):
        facts["authority_class"] = record.authority_class
        facts["written_in"] = record.source
        facts["section"] = record.section
        facts["status"] = record.status
        facts["content_sha256"] = record.content_sha256
        facts["delegations"] = tuple(
            sorted(
                f"{item.domain} -> {item.to_class} ({item.stated_in})"
                for item in record.delegates
            )
        )
    else:  # pragma: no cover - group_of already refused an unknown type
        raise DocsResolveError(f"{type(record).__name__} has no fact reading")

    expected = set(IDENTITY_FACTS) | set(FACT_ORDER[group])
    if set(facts) != expected:
        missing = sorted(expected - set(facts))
        extra = sorted(set(facts) - expected)
        raise DocsResolveError(
            f"the fact reading of {record.id} does not match what a {group} "
            f"record declares (absent: {missing}, unexpected: {extra})"
        )
    return TopicView(
        id=record.id,
        group=group,
        record=record,
        facts=dict(sorted(facts.items())),
    )


# ---------------------------------------------------------------------------
# Declared presentation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PresentationSpec:
    """What one channel declares about how it writes a topic.

    B5's residue clause 1, as a type. A channel declares the label or key
    path it writes each fact at, the order it writes them in, the blocks or
    keys it adds that carry no fact, and the named transformations it
    applies. Anything a channel puts in front of a reader that is neither
    declared presentation nor the carrier of a declared fact is
    **undeclared**, and undeclared is a violation — which is what makes
    "differ only in presentation" a gate rather than a sentence.

    ``carries`` is the set of fact names this channel writes. A bounded
    channel names fewer than the topic has, and that is the *only* way it
    is allowed to get smaller (rule (b)).

    ``width`` is the column a channel wraps prose at, or ``0`` for a
    channel that does not wrap. It is declared here rather than measured
    from a terminal on purpose: B6 finding 5 measured ``--help`` at 5,256
    bytes on a 40-column terminal and 3,436 on a 200-column one, and a
    documentation build that renders differently on two machines is not a
    build.
    """

    channel: str
    labels: Mapping[str, str]
    order: tuple[str, ...]
    envelope: tuple[str, ...]
    transformations: tuple[str, ...]
    width: int = 0

    def carries(self) -> frozenset[str]:
        """The facts this channel writes."""
        return frozenset(self.order)

    def label_of(self, fact: str) -> str:
        """Where this channel writes ``fact``, refusing an undeclared one."""
        try:
            return self.labels[fact]
        except KeyError:
            raise DocsResolveError(
                f"the {self.channel} channel writes {fact!r} at no declared "
                f"label; a fact with nowhere to go cannot be read back"
            ) from None

    def check(self, view: TopicView) -> None:
        """Refuse a spec that cannot honestly present ``view``.

        Two ways it cannot: it drops a fact from the identity core, which
        rule (a) forbids outright; or it names a fact the topic does not
        carry, which would put an empty section on a page and call it an
        answer.
        """
        carried = self.carries()
        absent = sorted(set(IDENTITY_FACTS) - carried)
        if absent:
            raise DocsResolveError(
                f"the {self.channel} channel would leave {absent} off "
                f"{view.id}. Every channel carries the topic id, its example "
                f"ids, its authority refs, the release and the snapshot: "
                f"presentation cannot drop identity."
            )
        unknown = sorted(carried - set(view.facts))
        if unknown:
            raise DocsResolveError(
                f"the {self.channel} channel writes {unknown} and a {view.group} "
                f"topic carries no such fact"
            )
        for fact in self.order:
            self.label_of(fact)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


class MatchClass(Enum):
    """Why a candidate matched, strongest first.

    The rank is an integer written here rather than derived from the
    declaration order, so the ordering is a fact of the code and not of the
    order somebody happened to list the members in.
    """

    EXACT_ID = (0, "its id is exactly what you asked for")
    ALIAS = (1, "it is what that id was renamed to")
    NAME = (2, "its name is exactly what you asked for")
    NAME_SUBSTRING = (3, "what you asked for appears in its name")
    TAG = (4, "it is filed under what you asked for")

    def __init__(self, rank: int, reason: str) -> None:
        self.rank = rank
        self.reason = reason


@dataclass(frozen=True, order=True)
class Candidate:
    """One thing a question could have meant, and why.

    The sort key is the rank then the id, in that order and nothing else:
    no score, no frequency, no length heuristic. Two candidates of one
    match class are ordered lexicographically, which is the only ordering
    that is the same on every platform and under every hash seed.
    """

    rank: int
    id: str
    group: str
    match_class: str
    reason: str


@dataclass(frozen=True)
class Resolution:
    """What one question came to.

    Exactly one of three shapes, and :meth:`state` says which:

    ``resolved``
        One candidate in the strongest matching class. ``topic`` is it.
    ``ambiguous``
        Several candidates share the strongest class. ``topic`` is
        ``None`` and ``candidates`` is the ranked list — the resolver
        returns the list rather than picking, because picking between
        equals is a guess and a guess is how ``s0ma docs show T`` and
        ``learn_s0ma(topic=T)`` stop being the same T.
    ``unresolved``
        Nothing matched. ``finding`` is a ``DOC_TOPIC_UNRESOLVED`` naming
        the nearest forms this build does address.
    """

    query: str
    topic: TopicView | None
    candidates: tuple[Candidate, ...]
    finding: Finding | None

    def state(self) -> str:
        """``resolved``, ``ambiguous`` or ``unresolved``."""
        if self.topic is not None:
            return "resolved"
        if self.candidates:
            return "ambiguous"
        return "unresolved"


def _display_name(record: DocsRecord) -> str:
    """The name a person would call ``record``, never its id.

    Every record type has one, even the three that carry no name field:
    the tail of the id is what an author wrote, and it is what a question
    will be spelled like.
    """
    if isinstance(record, ConceptRecord):
        return record.term
    if isinstance(record, SurfaceRecord):
        return record.public_name
    if isinstance(record, DocumentRecord):
        return record.title
    return record.id.partition(":")[2]


def _tags_of(record: DocsRecord) -> tuple[str, ...]:
    """What ``record`` is filed under, sorted.

    Derived, never authored: ``@1`` carries no tag field, so a tag here is
    something the record already says about itself — the kind word its id
    starts with, the channel a surface is served on, the class an authority
    belongs to. A question that is one of those words is a question about a
    category, and answering it with the whole category is more honest than
    answering it with one member.
    """
    found = {record.id.partition(":")[0]}
    form = id_form(record.id)
    if form is not None:
        found.add(form)
    if isinstance(record, SurfaceRecord):
        found.add(record.channel)
    if isinstance(record, AuthorityRef):
        found.add(record.authority_class)
    return tuple(sorted(found))


@dataclass(frozen=True)
class TopicIndex:
    """Everything one build can be asked about, and the ways of asking.

    Built from a bundle plus whatever alias pairs the concept providers
    declare. The aliases arrive through a plain
    :class:`~s0ma_dsl.docs_model.ids.AliasIndex` rather than through a
    provider, so this module never learns what a provider is: C5a keeps
    its authored aliases in exactly that helper, F6 and F7 will add more,
    and the seam is provider-agnostic by being a value.
    """

    views: Mapping[str, TopicView]
    names: Mapping[str, str]
    tags: Mapping[str, tuple[str, ...]]
    aliases: AliasIndex

    @classmethod
    def of(cls, bundle: DocsBundle, aliases: AliasIndex | None = None) -> TopicIndex:
        """Index every record of ``bundle``, resolvable and renderable."""
        views: dict[str, TopicView] = {}
        names: dict[str, str] = {}
        tags: dict[str, tuple[str, ...]] = {}
        # Named field by field rather than reached by group name, so the
        # union survives: a loop over ``getattr`` would hand a type checker
        # the shared base class and quietly disable every check below it.
        held: tuple[DocsRecord, ...] = (
            *bundle.authorities,
            *bundle.concepts,
            *bundle.surfaces,
            *bundle.journeys,
            *bundle.sequences,
            *bundle.documents,
        )
        for record in held:
            identifier = normalize_id(record.id)
            if identifier in views:
                raise DocsResolveError(
                    f"{identifier} is in this bundle twice; a topic index is "
                    f"keyed by id and cannot hold two answers to one question"
                )
            views[identifier] = facts_of(bundle, record)
            names[identifier] = _display_name(record)
            tags[identifier] = _tags_of(record)
        return cls(
            views=dict(sorted(views.items())),
            names=dict(sorted(names.items())),
            tags=dict(sorted(tags.items())),
            aliases=aliases if aliases is not None else AliasIndex(entries=()),
        )

    def merged_with(self, aliases: AliasIndex) -> TopicIndex:
        """This index with more alias pairs, the two sets merged and sorted.

        The way several concept providers' alias indexes reach one
        resolver without any of them knowing about the others.
        """
        return TopicIndex(
            views=self.views,
            names=self.names,
            tags=self.tags,
            aliases=AliasIndex.of([*self.aliases.entries, *aliases.entries]),
        )

    def ids(self) -> tuple[str, ...]:
        """Every id this build addresses, sorted."""
        return tuple(self.views)

    def view(self, identifier: str) -> TopicView:
        """The view of one id, refusing an id this build does not address."""
        try:
            return self.views[normalize_id(identifier)]
        except KeyError:
            raise DocsResolveError(
                f"this build addresses nothing called {identifier!r}"
            ) from None

    def group(self, name: str) -> tuple[str, ...]:
        """Every id in one bundle group, sorted."""
        return tuple(
            identifier for identifier, view in self.views.items() if view.group == name
        )


def _common_prefix(left: str, right: str) -> int:
    """How many leading characters two strings share. Integers only."""
    limit = min(len(left), len(right))
    shared = 0
    while shared < limit and left[shared] == right[shared]:
        shared += 1
    return shared


#: How many characters a query and an id must share before the miss
#: message is willing to call the id "near". Two is noise — every
#: ``concept:`` id shares seven with every other — and this floor is
#: applied to the *name* and the id tail as well as to the whole id, which
#: is what stops the common prefix of a namespace being mistaken for a
#: resemblance.
PREFIX_FLOOR = 3

#: How many near forms a miss lists. A miss that lists forty is a miss
#: nobody reads.
NEAREST_LIMIT = 5


def nearest(index: TopicIndex, query: str) -> tuple[str, ...]:
    """The ids that most resemble ``query``, by shared prefix, sorted.

    Integer arithmetic and nothing else. Edit distance, token overlap
    ratios and every other similarity measure worth having are either
    floating point or tie-break by insertion order, and both of those put
    the platform into the answer — plan §2.1 and this milestone's rule 4
    forbid that, so the resolver's idea of "near" is the crudest measure
    that is also exactly reproducible.

    Compared against three spellings of every record — the whole id, the
    id without its kind, and the display name — so that ``nerv``,
    ``concept:nerv`` and ``Nerve`` all reach the same place.
    """
    folded = query.strip().casefold()
    if not folded:
        return ()
    best = 0
    scored: dict[str, int] = {}
    for identifier, name in index.names.items():
        shared = max(
            _common_prefix(folded, identifier.casefold()),
            _common_prefix(folded, identifier.partition(":")[2].casefold()),
            _common_prefix(folded, name.casefold()),
        )
        scored[identifier] = shared
        best = max(best, shared)
    if best < PREFIX_FLOOR:
        return ()
    return tuple(
        sorted(identifier for identifier, shared in scored.items() if shared == best)
    )[:NEAREST_LIMIT]


def _miss(index: TopicIndex, query: str) -> Finding:
    """The structured miss: what was asked, and what is actually there."""
    near = nearest(index, query)
    if near:
        remediation = (
            f"the nearest things this build knows about are: "
            f"{', '.join(near)}. Ask for one of those by id, or by its name."
        )
    else:
        remediation = (
            f"nothing in this build resembles that. Every topic is addressed "
            f"by a kind and a colon — the kinds are: {', '.join(ID_CLASSES)} — "
            f"and a topic can also be asked for by its name."
        )
    return Finding(
        code=DOC_TOPIC_UNRESOLVED,
        location="",
        message=(
            f"{query!r} names no topic this build addresses, by id, by an "
            f"earlier name, by name or by category"
        ),
        remediation=remediation,
    )


def _named_candidates(index: TopicIndex, folded: str) -> list[Candidate]:
    """Candidates matched on a display name, exactly then by substring."""
    found: list[Candidate] = []
    for identifier, name in index.names.items():
        lowered = name.casefold()
        if lowered == folded:
            matched = MatchClass.NAME
        elif folded in lowered:
            matched = MatchClass.NAME_SUBSTRING
        else:
            continue
        found.append(
            Candidate(
                rank=matched.rank,
                id=identifier,
                group=index.views[identifier].group,
                match_class=matched.name,
                reason=matched.reason,
            )
        )
    return found


def resolve(index: TopicIndex, query: str) -> Resolution:
    """What ``query`` means in this build: one topic, several, or none.

    The order the classes are tried in is the plan's: an exact id, then an
    id something was renamed from, then a name, then part of a name, then
    a category. A strictly better class wins over a weaker one — that is
    not a guess, it is the whole point of having classes. What the resolver
    will not do is choose *between* candidates of one class: several things
    are equally called what you asked for, and saying which one you meant
    is your answer to give, not this function's.

    Total: every query returns a :class:`Resolution`. Nothing raises for a
    question that has no answer, because "no answer" is an answer a read
    surface has to be able to show.
    """
    trimmed = query.strip()
    normalized = normalize_id(trimmed)
    found: list[Candidate] = []

    if normalized in index.views:
        found.append(
            Candidate(
                rank=MatchClass.EXACT_ID.rank,
                id=normalized,
                group=index.views[normalized].group,
                match_class=MatchClass.EXACT_ID.name,
                reason=MatchClass.EXACT_ID.reason,
            )
        )
    else:
        canonical = index.aliases.canonical(normalized)
        if canonical != normalized and canonical in index.views:
            found.append(
                Candidate(
                    rank=MatchClass.ALIAS.rank,
                    id=canonical,
                    group=index.views[canonical].group,
                    match_class=MatchClass.ALIAS.name,
                    reason=MatchClass.ALIAS.reason,
                )
            )

    folded = trimmed.casefold()
    if folded:
        found.extend(_named_candidates(index, folded))
        for identifier, tags in index.tags.items():
            if folded in tags:
                found.append(
                    Candidate(
                        rank=MatchClass.TAG.rank,
                        id=identifier,
                        group=index.views[identifier].group,
                        match_class=MatchClass.TAG.name,
                        reason=MatchClass.TAG.reason,
                    )
                )

    strongest: dict[str, Candidate] = {}
    for candidate in found:
        held = strongest.get(candidate.id)
        if held is None or candidate.rank < held.rank:
            strongest[candidate.id] = candidate
    ranked = tuple(sorted(strongest.values()))

    if not ranked:
        return Resolution(query=query, topic=None, candidates=(), finding=_miss(index, query))
    best = [candidate for candidate in ranked if candidate.rank == ranked[0].rank]
    if len(best) == 1:
        return Resolution(
            query=query,
            topic=index.views[best[0].id],
            candidates=ranked,
            finding=None,
        )
    return Resolution(query=query, topic=None, candidates=ranked, finding=None)


def resolve_all(index: TopicIndex, queries: Iterable[str]) -> tuple[Resolution, ...]:
    """Several questions, in the order they were asked."""
    return tuple(resolve(index, query) for query in queries)


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

#: What a channel looks like from here: a topic in, its rendering out.
#: The coverage gate takes its renderers as values rather than importing
#: them, so this module never depends on a renderer and a caller cannot
#: satisfy the gate by handing it nothing.
Renderer = Callable[[TopicView], str]

#: A concept the build knows about that no read surface can show
#: (architecture plan §11, coverage policy §11.1).
DOC_CONCEPT_UNCOVERED = "DOC_CONCEPT_UNCOVERED"

#: A served capability the build knows about that is absent from the
#: rendered index of served capabilities (§11, with the row above).
DOC_SURFACE_UNCOVERED = "DOC_SURFACE_UNCOVERED"

#: Why these two gates live here rather than in ``validate.py``.
#:
#: C2 listed both in
#: :data:`~s0ma_dsl.docs_model.validate.DEFERRED_GATES` and said what they
#: were waiting for: "the coverage policy asks whether a concept has a
#: human page and an agent topic response. Nothing renders yet, so the
#: question has no subject." This milestone is where something renders, so
#: this is where they arm — in the module that owns the renderings, the way
#: C6 resolved ``DocumentRecord.authority`` in the module that added the
#: field rather than reaching into a gate it did not own.
#:
#: **They fold into ``validate.validate_bundle`` at C8**, which is the
#: milestone that builds the check flow and therefore the first caller with
#: all three renderers in hand. C8 examined the fold-in and rejected it:
#: this module imports ``validate.location_of`` at module level, so the
#: move is a circular import, and ``validate_bundle`` growing a
#: ``renderers`` argument would either break every existing caller or make
#: coverage silently skippable — the exact vacuity the gate exists to
#: refuse. The gates are armed where the flow runs.
FOLD_IN = (
    "check_coverage stays here by decision (C8): application.build arms it "
    "alongside validate.validate_bundle; folding it into validate was "
    "rejected for the circular import and the optional-argument vacuity "
    "trap. C2's DEFERRED_GATES no longer lists these two codes."
)

#: The two channels a coverage claim is about. Architecture §11.1 asks
#: whether a concept has *a human page and an agent topic response*; a
#: coverage gate run over neither of those would pass by having nothing to
#: check, which is the whole failure mode the gate exists for.
REQUIRED_CHANNELS: frozenset[str] = frozenset({"agent", "human"})


def _covered(
    view: TopicView, renderers: Mapping[str, Renderer]
) -> tuple[str, ...]:
    """The channels that failed to show ``view``, sorted."""
    failed: list[str] = []
    for channel in sorted(renderers):
        try:
            rendered = renderers[channel](view)
        except DocsModelError:
            failed.append(channel)
            continue
        if not rendered.strip() or view.id not in rendered:
            failed.append(channel)
    return tuple(failed)


def check_coverage(
    bundle: DocsBundle,
    *,
    renderers: Mapping[str, Renderer],
    index: TopicIndex | None = None,
) -> list[Finding]:
    """Everything this build knows about can actually be shown.

    Two questions, one walk. Every concept the build composed must resolve
    to itself and render on both reader channels
    (``DOC_CONCEPT_UNCOVERED``); every served capability must do the same,
    which is what makes the rendered index of served capabilities complete
    (``DOC_SURFACE_UNCOVERED``).

    **The vacuity trap is the point.** A coverage gate that reads its
    required set from the same place it reads its covered set passes by
    construction and proves nothing, so this one takes the *bundle* as the
    requirement and the *index* as what is actually reachable, and they are
    allowed to differ — a record that composed but that no read surface
    addresses is exactly the failure the gate is for. The renderers arrive
    as callables for the same reason a floor arrives from its caller
    (:func:`~s0ma_dsl.docs_model.validate.check_floors`): the gate must not
    be able to satisfy itself. An empty set of renderers, or one missing a
    reader channel, is refused rather than passed.

    ``index`` defaults to one built from ``bundle``, which is the healthy
    case; a caller that serves a narrower index passes it and finds out
    what it dropped.

    Findings are placed with C2's :func:`~s0ma_dsl.docs_model.validate.location_of`
    rather than with a second opinion about where a record lives: a surface
    knows the file its provider read, and an authored concept names none,
    which is the honest answer in ``@1``. The import is also the shape of
    the fold-in — when C8 moves this function into ``validate``, it goes
    away.
    """
    absent = sorted(REQUIRED_CHANNELS - set(renderers))
    if absent:
        raise DocsResolveError(
            f"a coverage check needs a renderer for {absent}. The coverage "
            f"policy asks whether a topic has a human page and an agent "
            f"answer; run over neither, it would pass by having nothing to "
            f"look at."
        )
    served = index if index is not None else TopicIndex.of(bundle)
    findings: list[Finding] = []
    concepts: tuple[DocsRecord, ...] = tuple(bundle.concepts)
    surfaces: tuple[DocsRecord, ...] = tuple(bundle.surfaces)
    groups: tuple[tuple[tuple[DocsRecord, ...], str, str], ...] = (
        (concepts, DOC_CONCEPT_UNCOVERED, "concept"),
        (surfaces, DOC_SURFACE_UNCOVERED, "served capability"),
    )
    for records, code, noun in groups:
        for record in sorted(records, key=lambda item: item.id):
            resolution = resolve(served, record.id)
            where = location_of(record)
            if resolution.topic is None or resolution.topic.id != normalize_id(record.id):
                findings.append(
                    Finding(
                        code=code,
                        location=where,
                        message=(
                            f"{record.id} is a {noun} this build composed and "
                            f"no read surface can be asked for it: its own id "
                            f"resolves to {resolution.state()}"
                        ),
                        remediation=(
                            f"the topic index this build serves does not "
                            f"address {record.id}. Either the index is built "
                            f"from less than the build composed, or something "
                            f"else has claimed that id — a record nobody can "
                            f"ask for is documentation nobody can read."
                        ),
                    )
                )
                continue
            failed = _covered(resolution.topic, renderers)
            if failed:
                findings.append(
                    Finding(
                        code=code,
                        location=where,
                        message=(
                            f"{record.id} is a {noun} this build composed and "
                            f"these channels render nothing for it: "
                            f"{', '.join(failed)}"
                        ),
                        remediation=(
                            "a topic that resolves and does not render is "
                            "worse than one that does neither, because every "
                            "count of what this build covers will include it. "
                            "Fix the renderer, or say in the model why this "
                            "record is not a topic."
                        ),
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Journey coverage (E8)
# ---------------------------------------------------------------------------

#: A capability a person came to s0ma for, and no journey takes them
#: through it. **Minted at E8.**
DOC_CAPABILITY_UNCOVERED = "DOC_CAPABILITY_UNCOVERED"

#: The code this module mints that the architecture plan's §11 table does
#: not name, with where it came from — the discipline
#: :data:`~s0ma_dsl.docs_model.validate.MINTED_CODES` and
#: :data:`~s0ma_dsl.docs_model.providers_concepts.MINTED_CODES` already
#: keep, applied to the module that raises the code rather than to a
#: module that would only be re-exporting it.
#:
#: E8 was handed a working name that put *journey* in the subject slot,
#: and it was not taken. Every ``*_UNCOVERED`` row of §11 names the thing
#: that lacks coverage first — a concept with no page, a surface with no
#: reference — and here the thing that lacks coverage is the
#: **capability**; a journey is what would cover it. Named the other way
#: round the code would read as a journey nothing documents, which is a
#: different failure and not one this gate can see. (The rejected spelling
#: is described rather than written, because the negative batteries grep
#: this tree for every ``DOC_*`` name and a code mentioned in a comment
#: would be a code they demand a fixture for.)
MINTED_CODES: Mapping[str, str] = {
    DOC_CAPABILITY_UNCOVERED: (
        "E8. §11's DOC_SURFACE_UNCOVERED is about a served capability that "
        "appears in no generated reference, and D6 armed it. This is about "
        "a capability that is in the reference, perfectly findable, and "
        "that nothing takes a reader *through* — the second half of the "
        "coverage policy §11.1 states and the half §11's table has no row "
        "for. The same code also carries the unclassified surface, because "
        "a capability nobody has said is primary or reference-only is one "
        "nobody can say is covered either."
    ),
}

#: The authored coverage policy's own schema. Not the model's, for the
#: reason ``providers_journeys`` gives for the same split: the policy is an
#: input to the documentation application rather than a serialization of
#: the model, and one version string over both would make a change to
#: either look like a change to both.
COVERAGE_POLICY_SCHEMA = "s0ma-docs-coverage-policy@1"

#: How many characters of written reason an exception has to carry.
#:
#: A floor rather than a shape, because no pattern can tell a reason from
#: an excuse and a floor at least refuses the ones that did not try. Sixty
#: is about a sentence: enough to say what the surface is and why no path
#: goes through it, not enough to fit "not needed".
MIN_REASON = 60

#: Which of this gate's findings §11.1 makes release-blocking, and which
#: are advisory in a development build. **All of them block, in both
#: modes, and the reason is that the alternative is a gate that turns
#: itself off.**
#:
#: ``DOC_JOURNEY_UNTESTED`` is the precedent E8 was pointed at, and it
#: reaches the gate by a seam rather than by a mode: a caller that can
#: answer "did this evidence run" hands over a resolver, and a caller that
#: cannot asks nothing (``validate.EvidenceResolver``). That shape works
#: there because the question genuinely has no answer offline. It does not
#: transfer here. Every input this gate needs — the authored policy, the
#: composed surfaces, the composed journeys — is present in every build
#: that runs at all, so a development mode that skipped it would not be
#: declining to ask an unanswerable question; it would be declining to
#: look at the answer.
#:
#: The mode itself does not exist yet, and this module does not invent it.
#: ``application.build`` takes no mode argument, ``s0ma docs check`` has no
#: ``--mode`` flag, and the milestone that adds both is **H1** — the
#: documentation manifest, its preview/release channel rules, and the
#: ``DOC_VERSION_MISMATCH`` those arm, which
#: :data:`~s0ma_dsl.docs_model.validate.DEFERRED_GATES` already names H1
#: for. When H1 lands, the decision recorded here is what it inherits: this
#: gate does not acquire a development mode that quiets it, and if a case
#: is ever made for one, the case has to be made against this note.
RELEASE_MODE = (
    "Every DOC_CAPABILITY_UNCOVERED and every DOC_GATE_VACUOUS this gate "
    "raises is release-blocking (architecture §11.1) and blocking in a "
    "development build too, by E8's decision. Mode plumbing lands at H1 "
    "with the manifest and DOC_VERSION_MISMATCH; nothing here is waiting "
    "for it, because a coverage gate that a mode can quiet is the vacuity "
    "the policy exists to refuse."
)


@dataclass(frozen=True)
class PrimaryCapability:
    """One thing a person came to s0ma for, and the paths that teach it.

    ``surfaces`` are the ways the product serves the capability, on every
    channel it is served on. They are deliberately more than one: a
    capability is what somebody wants done, and "check my project" is one
    want whether it arrives as ``cli:s0ma/check`` or ``mcp:tool/check``.
    That is also what keeps the two halves of D-10 apart — *reference*
    coverage is owed to every surface one at a time
    (:func:`check_coverage`, :func:`~s0ma_dsl.docs_model.application.check_surface_index`),
    and *journey* coverage is owed to the capability.

    ``journeys`` is an exact claim, not a list of things that might help:
    every journey named here has to walk at least one of ``surfaces``, and
    :func:`check_journey_coverage` reports the ones that stop.
    """

    id: str
    title: str
    why_primary: str
    journeys: tuple[str, ...]
    surfaces: tuple[str, ...]


@dataclass(frozen=True)
class SurfaceException:
    """One named surface no journey walks, and the written reason.

    A decision about one capability, taken one at a time, exactly like
    :data:`~s0ma_dsl.docs_model.application.UNREGISTERED_HANDLERS` — which
    is why these are counted against a ceiling and the channel rulings
    below are not.
    """

    surface: str
    reason: str


@dataclass(frozen=True)
class ChannelException:
    """A whole channel no journey walks, and the written reason.

    A ruling about a *kind* of record rather than a decision about a
    capability, and the same distinction
    :data:`~s0ma_dsl.docs_model.application.UNBOUND_CEILING` draws between
    the thirty-six unbound surfaces that are decisions and the hundred and
    twenty-eight that are rulings about a source. A hundred and nine
    diagnostic codes do not carry a hundred and nine reasons; they carry
    one, about what a diagnostic is.

    The form cannot become an ignore list, and two rules are what stop it:
    the channel has to be one
    :data:`~s0ma_dsl.docs_model.validate.CHANNEL_EFFECTS` names, so it can
    only ever name one of a closed set the model has classified; and a
    channel any primary capability is served on is refused *by the gate*,
    against the real bundle, so "the command line is reference-only" is
    unwritable while one command is in the ledger above.
    """

    channel: str
    reason: str


@dataclass(frozen=True)
class CoveragePolicy:
    """The authored answer to "which capabilities owe a journey".

    D-10 in one file: reference coverage is mandatory for every public
    surface and journey coverage is mandatory for the primary ones, with a
    structured exception that is *named, reasoned and counted* rather than
    a free-form ignore list.

    **Two ledgers, one exception mechanism.** The split is by the shape of
    the thing being excused rather than by how serious it is: a surface
    entry is a decision somebody took about one capability, and a channel
    entry is a ruling about what a whole kind of record *is*. Written as
    one flat list they would be indistinguishable, the count would be
    meaningless, and a ceiling over it could not mean anything either.

    ``source`` is where the file was read from, repository-relative, so
    every finding this policy produces points at the line an author edits
    rather than at nothing.

    **The empty policy is constructible and the empty authored file is
    not**, which is not an inconsistency. A caller that brings its own
    providers brings its own policy — the rule
    :func:`~s0ma_dsl.docs_model.validate.check_floors` states for floors
    and :func:`~s0ma_dsl.docs_model.validate.check_side_effects` for
    allowances — and for a composition of somebody else's records the
    honest policy is the one that claims nothing and excuses nothing. It
    is also the safest degenerate value there is: claiming nothing means
    every composed surface is unclassified, so an empty policy over a real
    build is loudly red rather than quietly permissive. What
    :func:`coverage_policy_from_mapping` refuses is different — a *file* a
    person wrote and left empty, which is a policy that has been thought
    about and says nothing.
    """

    source: str
    capabilities: tuple[PrimaryCapability, ...]
    surface_exceptions: tuple[SurfaceException, ...]
    channel_exceptions: tuple[ChannelException, ...]

    def excused_surfaces(self) -> frozenset[str]:
        """Every surface id the surface ledger names, comparable."""
        return frozenset(
            normalize_id(item.surface) for item in self.surface_exceptions
        )

    def excused_channels(self) -> frozenset[str]:
        """Every channel the channel ledger names."""
        return frozenset(item.channel for item in self.channel_exceptions)

    def claimed_surfaces(self) -> frozenset[str]:
        """Every surface id a primary capability claims, comparable."""
        return frozenset(
            normalize_id(surface)
            for capability in self.capabilities
            for surface in capability.surfaces
        )


# ---------------------------------------------------------------------------
# Reading the authored policy
# ---------------------------------------------------------------------------

_POLICY_KEYS = (
    "primary_capabilities",
    "reference_only_channels",
    "reference_only_surfaces",
    "schema",
)
_CAPABILITY_KEYS = ("id", "journeys", "surfaces", "title", "why_primary")
_SURFACE_EXCEPTION_KEYS = ("reason", "surface")
_CHANNEL_EXCEPTION_KEYS = ("channel", "reason")

#: A capability's own id: a lowercase hyphenated slug, and deliberately
#: **not** a model id. A capability is a fact of this policy rather than a
#: record any provider emits, and giving it a ``capability:`` form would
#: put a sixteenth entry in :data:`~s0ma_dsl.docs_model.ids.ID_FORMS` for
#: something nothing else in the model addresses.
_CAPABILITY_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _policy_object(value: object, where: str) -> Mapping[str, object]:
    """``value`` as a JSON object, refusing anything else by name."""
    if not isinstance(value, dict):
        raise DocsResolveError(f"{where}: expected an object")
    return value


def _policy_list(value: object, where: str) -> Sequence[object]:
    """``value`` as a JSON array, refusing anything else by name."""
    if not isinstance(value, list):
        raise DocsResolveError(f"{where}: expected a list")
    return value


def _policy_text(value: object, where: str) -> str:
    """``value`` as non-empty text, refusing anything else by name."""
    if not isinstance(value, str) or not value.strip():
        raise DocsResolveError(f"{where}: expected a non-empty string")
    return value


def _policy_reason(value: object, where: str) -> str:
    """``value`` as a reason long enough to have been written on purpose."""
    text = _policy_text(value, where)
    if len(text.strip()) < MIN_REASON:
        raise DocsResolveError(
            f"{where}: is {len(text.strip())} characters and an exception "
            f"needs at least {MIN_REASON}. The count is not the point — a "
            f"reason has to say what this is and why no path goes through "
            f"it, because the next person to read this ledger is deciding "
            f"whether the exception still holds."
        )
    return text


def _policy_keys(raw: Mapping[str, object], expected: Sequence[str], where: str) -> None:
    """Refuse an object that does not carry exactly the expected keys."""
    unknown = sorted(set(raw) - set(expected))
    missing = sorted(set(expected) - set(raw))
    if unknown or missing:
        raise DocsResolveError(
            f"{where}: does not match the {COVERAGE_POLICY_SCHEMA} shape "
            f"(unexpected: {unknown}, absent: {missing})"
        )


def _policy_ids(value: object, where: str, *, expected_form: str | None = None) -> tuple[str, ...]:
    """A sorted, duplicate-free, non-empty list of model ids."""
    items = [
        _policy_text(item, f"{where}[{index}]")
        for index, item in enumerate(_policy_list(value, where))
    ]
    if not items:
        raise DocsResolveError(
            f"{where}: is empty. An empty list here is not a smaller claim, "
            f"it is no claim at all, and every gate downstream would pass it."
        )
    if items != sorted(set(items)):
        raise DocsResolveError(
            f"{where}: is not sorted, or repeats an id. This file is read by "
            f"people and compared byte for byte; one order is the order."
        )
    for index, item in enumerate(items):
        form = id_form(item)
        if form is None:
            raise DocsResolveError(
                f"{where}[{index}]: {item!r} matches no id form the model "
                f"addresses things by."
            )
        if expected_form is not None and form != expected_form:
            raise DocsResolveError(
                f"{where}[{index}]: {item!r} is a {form} id and this list "
                f"names {expected_form} ids."
            )
    return tuple(items)


def _capability(raw: object, where: str) -> PrimaryCapability:
    """One primary capability, or the refusal that says what is wrong."""
    entry = _policy_object(raw, where)
    _policy_keys(entry, _CAPABILITY_KEYS, where)
    identifier = _policy_text(entry["id"], f"{where}.id")
    if not _CAPABILITY_ID.match(identifier):
        raise DocsResolveError(
            f"{where}.id: {identifier!r} is not a lowercase hyphenated slug. "
            f"A capability is named by this policy and by nothing else, so "
            f"the name is a slug rather than a model id."
        )
    title = _policy_text(entry["title"], f"{where}.title")
    if "\n" in title:
        raise DocsResolveError(f"{where}.title: contains a line break; write it as one line")
    return PrimaryCapability(
        id=identifier,
        title=title,
        why_primary=_policy_reason(entry["why_primary"], f"{where}.why_primary"),
        journeys=_policy_ids(entry["journeys"], f"{where}.journeys", expected_form="journey"),
        surfaces=_policy_ids(entry["surfaces"], f"{where}.surfaces"),
    )


def coverage_policy_from_mapping(raw: object, *, source: str) -> CoveragePolicy:
    """Read an authored coverage policy, refusing a file it cannot trust.

    The C5a line, kept: a file whose *shape* is wrong raises, because a
    policy that half-loaded would leave the gate below asking a smaller
    question than the author wrote and reporting success for the rest.
    Everything that needs the composed bundle to judge — does this journey
    still walk this capability, is this surface classified at all — is a
    :class:`~s0ma_dsl.docs_model.providers.Finding` from
    :func:`check_journey_coverage`.

    Three refusals are worth naming because they are what keep the
    exception structured rather than free-form:

    * **an id in both ledgers.** A surface a capability claims and an
      exception excuses is a file that says two things; whichever is true,
      nothing can read it;
    * **a channel outside the model's own vocabulary.** A channel
      exception may only name a channel
      :data:`~s0ma_dsl.docs_model.validate.CHANNEL_EFFECTS` classifies, so
      the wildest thing this ledger can say is one of nine known words;
    * **a capability with no journeys.** The whole content of "primary" is
      that a journey owes it a path, and an empty list is the claim
      withdrawn while the word stays.
    """
    document = _policy_object(raw, source)
    _policy_keys(document, _POLICY_KEYS, source)
    declared = _policy_text(document["schema"], f"{source}.schema")
    if declared != COVERAGE_POLICY_SCHEMA:
        raise DocsResolveError(
            f"{source}.schema: is {declared!r} and this reader is "
            f"{COVERAGE_POLICY_SCHEMA}."
        )

    capabilities = tuple(
        _capability(item, f"{source}.primary_capabilities[{index}]")
        for index, item in enumerate(
            _policy_list(document["primary_capabilities"], f"{source}.primary_capabilities")
        )
    )
    if not capabilities:
        raise DocsResolveError(
            f"{source}.primary_capabilities: is empty. A coverage policy "
            f"naming no primary capability requires no journey of anything, "
            f"which is the one answer this gate must never be able to give "
            f"itself."
        )
    identifiers = [item.id for item in capabilities]
    if identifiers != sorted(set(identifiers)):
        raise DocsResolveError(
            f"{source}.primary_capabilities: is not sorted by id, or names "
            f"one capability twice."
        )

    surface_exceptions: list[SurfaceException] = []
    for index, item in enumerate(
        _policy_list(document["reference_only_surfaces"], f"{source}.reference_only_surfaces")
    ):
        where = f"{source}.reference_only_surfaces[{index}]"
        entry = _policy_object(item, where)
        _policy_keys(entry, _SURFACE_EXCEPTION_KEYS, where)
        identifier = _policy_text(entry["surface"], f"{where}.surface")
        if id_form(identifier) is None:
            raise DocsResolveError(
                f"{where}.surface: {identifier!r} matches no id form the "
                f"model addresses things by."
            )
        surface_exceptions.append(
            SurfaceException(
                surface=identifier,
                reason=_policy_reason(entry["reason"], f"{where}.reason"),
            )
        )
    excused = [item.surface for item in surface_exceptions]
    if excused != sorted(set(excused)):
        raise DocsResolveError(
            f"{source}.reference_only_surfaces: is not sorted by surface, or "
            f"excuses one surface twice."
        )

    channel_exceptions: list[ChannelException] = []
    for index, item in enumerate(
        _policy_list(document["reference_only_channels"], f"{source}.reference_only_channels")
    ):
        where = f"{source}.reference_only_channels[{index}]"
        entry = _policy_object(item, where)
        _policy_keys(entry, _CHANNEL_EXCEPTION_KEYS, where)
        channel = _policy_text(entry["channel"], f"{where}.channel")
        if channel not in CHANNEL_EFFECTS:
            raise DocsResolveError(
                f"{where}.channel: {channel!r} is not a channel this model "
                f"has classified. The channels are: "
                f"{', '.join(sorted(CHANNEL_EFFECTS))}. A ruling about a "
                f"whole kind of record may only name a kind the model knows."
            )
        channel_exceptions.append(
            ChannelException(
                channel=channel,
                reason=_policy_reason(entry["reason"], f"{where}.reason"),
            )
        )
    channels = [item.channel for item in channel_exceptions]
    if channels != sorted(set(channels)):
        raise DocsResolveError(
            f"{source}.reference_only_channels: is not sorted by channel, or "
            f"excuses one channel twice."
        )

    policy = CoveragePolicy(
        source=source,
        capabilities=capabilities,
        surface_exceptions=tuple(surface_exceptions),
        channel_exceptions=tuple(channel_exceptions),
    )
    both = sorted(policy.claimed_surfaces() & policy.excused_surfaces())
    if both:
        raise DocsResolveError(
            f"{source}: {both} are claimed by a primary capability and "
            f"excused by the reference-only ledger at once. A surface is "
            f"one or the other; a file that says both cannot be read as "
            f"either."
        )
    return policy


# ---------------------------------------------------------------------------
# The journey-coverage gate
# ---------------------------------------------------------------------------


def _walked_by(journey: JourneyRecord) -> frozenset[str]:
    """Every surface ``journey`` takes a reader to, comparable.

    Steps *and* recovery paths. A recovery path is not a footnote to a
    journey, it is the branch a reader is actually on when something has
    gone wrong, and the surface at the end of it is one they are being
    walked to — ``journey:first-project`` teaches ``cli:s0ma/doctor``
    nowhere else.
    """
    return frozenset(
        {
            *(normalize_id(step.surface) for step in journey.steps),
            *(normalize_id(path.next_surface) for path in journey.recovery_paths),
        }
    )


def _capability_findings(
    capability: PrimaryCapability,
    policy: CoveragePolicy,
    surfaces: Mapping[str, SurfaceRecord],
    journeys: Mapping[str, JourneyRecord],
) -> list[Finding]:
    """What is wrong with one primary capability's claim, if anything."""
    findings: list[Finding] = []
    wanted = frozenset(normalize_id(item) for item in capability.surfaces)

    for surface in capability.surfaces:
        if normalize_id(surface) in surfaces:
            continue
        findings.append(
            Finding(
                code=DOC_TOPIC_UNRESOLVED,
                location=policy.source,
                message=(
                    f"the primary capability {capability.id!r} is served by "
                    f"{surface}, which this build does not address"
                ),
                remediation=(
                    "either the capability has stopped being served that "
                    "way and the id belongs out of this policy, or it was "
                    "renamed and the policy still says the old name. A "
                    "coverage claim about a surface nothing serves is a "
                    "claim nothing can check."
                ),
            )
        )

    covering = sorted(
        identifier
        for identifier in (normalize_id(item) for item in capability.journeys)
        if identifier in journeys and _walked_by(journeys[identifier]) & wanted
    )
    still = len(covering)
    for journey_id in capability.journeys:
        normalized = normalize_id(journey_id)
        record = journeys.get(normalized)
        if record is None:
            findings.append(
                Finding(
                    code=DOC_CAPABILITY_UNCOVERED,
                    location=policy.source,
                    message=(
                        f"the primary capability {capability.id!r} names "
                        f"{journey_id}, which this build does not address; "
                        f"{still} of its {len(capability.journeys)} declared "
                        f"journeys still walk it"
                    ),
                    remediation=(
                        f"a journey that has been renamed or removed leaves "
                        f"{capability.id!r} claiming a path that is not there. "
                        f"Point the policy at the journey that teaches it now, "
                        f"or write the journey. If neither is going to happen, "
                        f"the honest move is to move its surfaces into the "
                        f"reference-only ledger with the reason."
                    ),
                )
            )
        elif normalized not in covering:
            findings.append(
                Finding(
                    code=DOC_CAPABILITY_UNCOVERED,
                    location=policy.source,
                    message=(
                        f"the primary capability {capability.id!r} names "
                        f"{journey_id}, and that journey walks none of its "
                        f"surfaces; {still} of its {len(capability.journeys)} "
                        f"declared journeys still walk it"
                    ),
                    remediation=(
                        f"the journey's steps and recovery paths have moved "
                        f"off {sorted(capability.surfaces)}. Either the "
                        f"journey should still take a reader through one of "
                        f"them and its steps are what is wrong, or it never "
                        f"did and this policy is the thing to correct. A "
                        f"capability whose journeys all drift off it is "
                        f"documented and untaught."
                    ),
                )
            )
    return findings


def check_journey_coverage(
    bundle: DocsBundle, policy: CoveragePolicy
) -> list[Finding]:
    """Every primary capability is taught, and every surface is classified.

    D-10's second half, and the row of architecture §11.1 that reads
    "every primary capability appears in at least one journey or carries
    an explicit ``reference_only`` classification with rationale". Four
    failures, in the order an author meets them:

    * **a capability whose journey vanished, or stopped walking it** —
      ``DOC_CAPABILITY_UNCOVERED``, naming the capability, the journey and
      how many of its journeys still cover it. Reported per journey rather
      than per capability on purpose: a capability with four paths that
      loses one has lost something real, and a gate that only spoke up at
      zero would say nothing until the last one went;
    * **a surface in neither ledger** — also
      ``DOC_CAPABILITY_UNCOVERED``. This is the completeness half, and it
      is the half that makes the whole thing worth having: a policy seeded
      from the journeys that exist would pass by construction, and what
      stops that is that every surface the product grows tomorrow lands
      here and has to be classified by somebody;
    * **a surface in both ledgers at once** — the same code, because the
      state is the same one: nobody can say whether a journey owes it a
      path. (The single-file form of this contradiction is refused while
      loading; this is the form only the bundle can see, where a channel
      ruling has swallowed a capability's surface.);
    * **an exception nothing uses** — ``DOC_GATE_VACUOUS``, the
      self-expiring rule
      :func:`~s0ma_dsl.docs_model.validate.check_side_effects` already
      applies to its allowances. The day a surface is retired, the
      exception excusing it stops matching and the build says so, rather
      than carrying a permission for a silence that no longer exists.

    ``policy`` is the caller's, exactly as the floors, the allowances and
    the evidence resolver are. Which capabilities a product is *for* is
    not a fact about the machinery, and a default written into this module
    would be a claim about somebody else's build.

    Whether the findings block is not a mode here: see
    :data:`RELEASE_MODE`.
    """
    surfaces = {normalize_id(record.id): record for record in bundle.surfaces}
    journeys = {normalize_id(record.id): record for record in bundle.journeys}
    findings: list[Finding] = []

    for capability in policy.capabilities:
        findings.extend(_capability_findings(capability, policy, surfaces, journeys))

    claimed = policy.claimed_surfaces()
    excused = policy.excused_surfaces()
    channels = policy.excused_channels()
    used_surfaces: set[str] = set()
    used_channels: set[str] = set()

    for identifier, record in sorted(surfaces.items()):
        by_capability = identifier in claimed
        by_surface = identifier in excused
        by_channel = record.channel in channels
        if by_surface:
            used_surfaces.add(identifier)
        if by_channel:
            used_channels.add(record.channel)
        if by_capability and not (by_surface or by_channel):
            continue
        if not (by_capability or by_surface or by_channel):
            findings.append(
                Finding(
                    code=DOC_CAPABILITY_UNCOVERED,
                    location=location_of(record),
                    message=(
                        f"{record.id} is served and this coverage policy has "
                        f"not said whether it is a capability a journey has "
                        f"to teach"
                    ),
                    remediation=(
                        f"add it to the surfaces of the primary capability it "
                        f"belongs to in {policy.source}, or write it into the "
                        f"reference-only ledger with the reason no path goes "
                        f"through it. Every public surface is one or the "
                        f"other, and a new one that is neither is a decision "
                        f"nobody has taken rather than a capability nobody "
                        f"needs."
                    ),
                )
            )
        elif by_capability:
            excusing = "the reference-only ledger" if by_surface else (
                f"the ruling that all {record.channel!r} surfaces are "
                f"reference-only"
            )
            findings.append(
                Finding(
                    code=DOC_CAPABILITY_UNCOVERED,
                    location=location_of(record),
                    message=(
                        f"{record.id} is claimed by a primary capability and "
                        f"excused by {excusing} at once"
                    ),
                    remediation=(
                        f"a surface is a capability a journey owes a path, or "
                        f"it is a reference entry, and it cannot be read as "
                        f"both. If the whole channel really is reference-only, "
                        f"the capability claiming this surface is the thing to "
                        f"correct in {policy.source}."
                    ),
                )
            )

    for item in policy.surface_exceptions:
        if normalize_id(item.surface) in used_surfaces:
            continue
        findings.append(
            Finding(
                code=DOC_GATE_VACUOUS,
                location=policy.source,
                message=(
                    f"the reference-only ledger excuses {item.surface} from "
                    f"needing a journey, and this build serves no such surface"
                ),
                remediation=(
                    "either the surface is gone, and the exception goes with "
                    "it, or its id has changed and the ledger is pointing at "
                    "nothing. An exception nobody uses is a standing "
                    "permission for a gap that may already be closed, which "
                    "is exactly how a temporary decision becomes a permanent "
                    "one."
                ),
            )
        )

    for ruling in policy.channel_exceptions:
        if ruling.channel in used_channels:
            continue
        findings.append(
            Finding(
                code=DOC_GATE_VACUOUS,
                location=policy.source,
                message=(
                    f"the reference-only ledger rules that every "
                    f"{ruling.channel!r} surface is a reference entry, and "
                    f"this build composed no surface on that channel"
                ),
                remediation=(
                    "a ruling about a channel nothing is served on excuses "
                    "nothing. Either the provider that reads that channel has "
                    "stopped producing — check it first — or the channel is "
                    "gone and the ruling goes with it."
                ),
            )
        )
    return findings
