"""One question, one topic, three channels, one set of facts.

Milestone C7 of the docs-function plan (internal) §8. Four claims, and the
milestone is only worth having if it makes all four:

* **a question resolves the same way everywhere.** Exact id beats an old
  name beats a name beats part of a name beats a category; a question that
  is equally two things comes back as both, ranked, never as a guess; a
  question that is nothing comes back naming what this build does have.
  Nothing in the ranking is a score, so nothing in it can vary by platform
  or by hash seed;
* **the three channels differ only in declared presentation.** B5's residue
  definition, reimplemented from its README and adopted as written: each
  channel declares where it writes each fact, an extractor reads the facts
  back **out of the rendered artifact**, and the comparison runs on what
  the extractor found. Eight factual mutations go red; six presentation
  mutations stay green, each of them first proving that it actually changed
  the artifact;
* **the bytes are the bytes.** Fifteen golden files, compared byte for
  byte, and re-rendered in three subprocesses under three different hash
  seeds to prove the digest does not move;
* **nothing the build knows about is unreachable.** The two coverage gates
  C2 deferred to this milestone arm here, and the proof that they are not
  vacuous is a deliberately hidden concept and a deliberately hidden
  surface, each of which fires its own code.

**The residue utility is** :func:`divergences` **, and it is what F9
adopts.** It reads the declarations out of the renderer modules — which is
B5 finding 2's point, that the renderer registry is load-bearing for a gate
and not only for a build — so the product code carries the declaration and
the extractor, and only the comparison lives here.

**Regenerating the goldens.** They are deliberately strict, following the
house idiom in ``test_doc_emitter_golden.py``: when a change to them is
intended, regenerate in a single commit and say why. The nine live goldens
move when one of the three concepts moves, and also when a document one of
them cites is edited — the snapshot digest is over the golden build, and a
cited authority carries the fingerprint of its source.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model import render_agent, render_human, render_json
from s0ma_dsl.docs_model.compose import compose
from s0ma_dsl.docs_model.ids import AliasIndex, DocsIdError
from s0ma_dsl.docs_model.providers import ProviderRegistry
from s0ma_dsl.docs_model.providers_catalog import CatalogProvider
from s0ma_dsl.docs_model.providers_concepts import CONCEPTS_DIR, ConceptsProvider
from s0ma_dsl.docs_model.providers_core import CoreProvider
from s0ma_dsl.docs_model.providers_journeys import JourneysProvider
from s0ma_dsl.docs_model.providers_repo import RepoProvider
from s0ma_dsl.docs_model.records import (
    SCHEMA,
    AuthorityRef,
    BuildStamp,
    ConceptRecord,
    DocsBundle,
    ExampleRef,
    JourneyRecord,
    JourneyStep,
    Provenance,
    RecoveryPath,
    SurfaceRecord,
)
from s0ma_dsl.docs_model.render_agent import AGENT_BYTE_BUDGET, DOC_TOPIC_OVERSIZED
from s0ma_dsl.docs_model.resolve import (
    AGENT_SHORT_FACT,
    DOC_CONCEPT_UNCOVERED,
    DOC_SURFACE_UNCOVERED,
    DOC_TOPIC_UNRESOLVED,
    FACT_ORDER,
    IDENTITY_FACTS,
    LIST_FACTS,
    DocsResolveError,
    FactValue,
    MatchClass,
    PresentationSpec,
    TopicIndex,
    TopicView,
    canonical_fact,
    check_coverage,
    facts_of,
    nearest,
    resolve,
)
from s0ma_dsl.docs_model.serialize import stamped

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = Path(__file__).parent / "goldens" / "docs_model"
PRODUCT_CONCEPTS = f"{CONCEPTS_DIR}/product.json"

#: The release the golden build is stamped with. Pinned rather than read
#: live, exactly as the C5b and C6 suites pin it: a golden stamped with
#: whatever version happens to be in the tree would move on every release
#: for a reason that has nothing to do with the page.
RELEASE = "0.18.1"

#: The three concepts the milestone names, rendered from the real
#: composition. One language concept with a written form, one product
#: concept with two governing authorities, one concept with neither.
GOLDEN_CONCEPTS = ("concept:drift", "concept:nerve", "concept:self-knowledge")

#: The name F9 will report a residue failure under. Named here because B5
#: called this comparison the seed of that gate, and a seed with no name is
#: a seed nobody plants.
DOC_CHANNEL_DIVERGENCE = "DOC_CHANNEL_DIVERGENCE"


# ---------------------------------------------------------------------------
# The three channels, as one table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Channel:
    """One renderer, its extractor, its declaration and its shape gate.

    ``suffix`` is everything after the first dot of a golden's name. The
    human page is Markdown and is stored as ``.md.txt`` rather than as
    ``.md``, following B6's precedent for its own prose fixture: the
    catalog's completeness gate and the A6 guard both read *every tracked
    Markdown file* as a document of this repository, and a golden is test
    data, not documentation. Naming it ``.md`` would put five rendered
    pages into the corpus both of those gates are complete against.
    """

    name: str
    suffix: str
    render: Any
    extract: Any
    spec_for: Any
    undeclared: Any


CHANNELS: tuple[Channel, ...] = (
    Channel(
        "json",
        "json",
        render_json.render_json,
        render_json.extract,
        render_json.spec_for,
        render_json.undeclared_keys,
    ),
    Channel(
        "human",
        "md.txt",
        render_human.render_human,
        render_human.extract,
        render_human.spec_for,
        render_human.undeclared_headings,
    ),
    Channel(
        "agent",
        "agent.txt",
        render_agent.render_agent,
        render_agent.extract,
        render_agent.spec_for,
        render_agent.undeclared_labels,
    ),
)

BY_NAME = {channel.name: channel for channel in CHANNELS}


# ---------------------------------------------------------------------------
# The residue comparison — B5's definition, reimplemented
# ---------------------------------------------------------------------------


def residue_of(channel: Channel, view: TopicView, artifact: str) -> dict[str, FactValue]:
    """The facts left in ``artifact`` once the declared presentation is off.

    B5 clause 3. The declared transformations are undone — whitespace
    collapsed for prose, lists un-joined, the empty marker read back as an
    empty list, key paths flattened to fact names — and what is left is a
    flat map of fact name to canonical value.

    ``artifact`` is passed in rather than rendered here, so a test can hand
    this an artifact it has *edited*. That is clause 2, and it is the whole
    difference between proving three renderers agree and proving three
    renderers were called.
    """
    spec = channel.spec_for(view.group)
    return {
        name: canonical_fact(name, value)
        for name, value in channel.extract(artifact, spec).items()
    }


def divergences(view: TopicView, artifacts: Mapping[str, str]) -> list[str]:
    """B5's three comparison rules over one topic's renderings.

    Returns one line per violation, each opening with
    :data:`DOC_CHANNEL_DIVERGENCE`, so a caller asserts against ``[]`` and
    reads the failures rather than a boolean. Rule (c) is reported without
    blaming a channel, because nothing in the comparison alone says which
    of two disagreeing channels is wrong (B5 finding 7).
    """
    found: list[str] = []
    residues = {
        name: residue_of(BY_NAME[name], view, artifact)
        for name, artifact in artifacts.items()
    }
    truth = {name: canonical_fact(name, value) for name, value in view.facts.items()}

    for name, residue in sorted(residues.items()):
        spec = BY_NAME[name].spec_for(view.group)
        # Rule (a): the identity core is mandatory.
        for fact in IDENTITY_FACTS:
            if fact not in residue:
                found.append(
                    f"{DOC_CHANNEL_DIVERGENCE}: the {name} channel leaves "
                    f"{fact} off {view.id}; presentation cannot drop identity"
                )
            elif residue[fact] != truth[fact]:
                found.append(
                    f"{DOC_CHANNEL_DIVERGENCE}: the {name} channel says "
                    f"{fact} of {view.id} is {residue[fact]!r} and the record "
                    f"says {truth[fact]!r}"
                )
        # Rule (b): every other fact carried is verbatim.
        for fact, value in sorted(residue.items()):
            if fact in IDENTITY_FACTS:
                continue
            if value != truth[fact]:
                found.append(
                    f"{DOC_CHANNEL_DIVERGENCE}: the {name} channel carries "
                    f"{fact} of {view.id} as {value!r}, which is not what the "
                    f"record says: {truth[fact]!r}"
                )
        # Clause 1: nothing undeclared reached the reader.
        undeclared = BY_NAME[name].undeclared(artifacts[name], spec)
        if undeclared:
            found.append(
                f"{DOC_CHANNEL_DIVERGENCE}: the {name} channel puts "
                f"{list(undeclared)} in front of a reader and declares none "
                f"of it"
            )

    # Rule (c): channels agree with each other.
    shared: dict[str, dict[str, FactValue]] = {}
    for name, residue in residues.items():
        for fact, value in residue.items():
            shared.setdefault(fact, {})[name] = value
    for fact, said in sorted(shared.items()):
        distinct = {repr(value) for value in said.values()}
        if len(distinct) > 1:
            who = "; ".join(f"{name} says {said[name]!r}" for name in sorted(said))
            found.append(
                f"{DOC_CHANNEL_DIVERGENCE}: the channels disagree about "
                f"{fact} of {view.id} — {who}"
            )
    return found


def render_all(view: TopicView) -> dict[str, str]:
    """One topic through every channel."""
    return {channel.name: channel.render(view) for channel in CHANNELS}


# ---------------------------------------------------------------------------
# The builds under test
# ---------------------------------------------------------------------------


def _registry() -> ProviderRegistry:
    """The authored readings: core, the repository, both concept files, the
    catalog, and — since E1 — the journeys.

    Narrower than the application's registry on purpose: the D-phase
    surface providers are not here, because this suite is about how a
    topic is *written* on three channels and two hundred more surfaces
    would slow every test in it without changing an answer. The journeys
    are here because without them the journeys group would be the one
    group in :data:`~s0ma_dsl.docs_model.resolve.FACT_ORDER` that no test
    reads real data for.
    """
    return ProviderRegistry.of(
        CoreProvider(),
        RepoProvider(root=REPO_ROOT),
        ConceptsProvider.language(REPO_ROOT),
        ConceptsProvider(root=REPO_ROOT, relative=PRODUCT_CONCEPTS, domain="product"),
        CatalogProvider(root=REPO_ROOT),
        JourneysProvider(root=REPO_ROOT),
    )


def _aliases() -> AliasIndex:
    """Both concept files' authored aliases, merged into one index."""
    language = ConceptsProvider.language(REPO_ROOT).alias_index()
    product = ConceptsProvider(
        root=REPO_ROOT, relative=PRODUCT_CONCEPTS, domain="product"
    ).alias_index()
    return AliasIndex.of([*language.entries, *product.entries])


@lru_cache(maxsize=1)
def live_bundle() -> DocsBundle:
    """The whole composition, once per process."""
    return compose(_registry(), release_version=RELEASE).bundle


@lru_cache(maxsize=1)
def live_index() -> TopicIndex:
    """Everything this repository's documentation build addresses."""
    return TopicIndex.of(live_bundle(), _aliases())


def _empty_stamp() -> BuildStamp:
    return BuildStamp(schema=SCHEMA, release_version="", snapshot_hash="")


@lru_cache(maxsize=1)
def golden_bundle() -> DocsBundle:
    """The three golden concepts and their authorities, as a build of their own.

    A projection of the live composition, never a copy of it: the records
    are the composed records, so a page's facts are the repository's facts
    and a fifth copy of the concept text cannot drift into existence (B5
    made the same choice about B4's fixtures and for the same reason).

    It is a *narrower* build than the live one on purpose. The snapshot
    digest identifies a build, so a golden stamped with the whole
    composition would move whenever any of four hundred records moved —
    every later milestone would rewrite these files for reasons that have
    nothing to do with the pages in them.
    """
    whole = live_bundle()
    wanted = set(GOLDEN_CONCEPTS)
    concepts = tuple(record for record in whole.concepts if record.id in wanted)
    cited = {identifier for record in concepts for identifier in record.governed_by}
    authorities = tuple(record for record in whole.authorities if record.id in cited)
    return stamped(
        DocsBundle(
            stamp=_empty_stamp(),
            authorities=authorities,
            concepts=concepts,
            surfaces=(),
            journeys=(),
            sequences=(),
            documents=(),
        ),
        RELEASE,
    )


#: A provenance for the fixture build's derived records.
_FIXTURE_PROVENANCE = Provenance(
    adapter_id="fixture",
    schema_version=SCHEMA,
    source="tests/test_docs_resolve_render.py",
    source_sha256="0" * 64,
)

#: The authority the fixture records cite.
_FIXTURE_AUTHORITY = AuthorityRef(
    id="authority:spec/fixture-journey",
    authority_class="spec",
    source="tests/test_docs_resolve_render.py",
    section="fixtures",
    content_sha256="1" * 64,
    status="active",
    delegates=(),
)


@lru_cache(maxsize=1)
def fixture_bundle() -> DocsBundle:
    """A small build carrying the two shapes the live corpus has none of.

    Two things the repository cannot supply today, and both of them are
    things a parity claim is empty without:

    * **a journey with all of E1's fields carried.** The three composed
      journeys teach and require concepts and cross no approval boundary,
      so ``approval_boundaries`` would render empty on every live page and
      the claim about it would be vacuous — B5 finding 4's trap, one field
      along. This journey teaches a concept, assumes one, names its
      evidence and crosses one boundary, so every fact in
      ``FACT_ORDER["journeys"]`` is non-empty in at least one golden;
    * **a concept with a worked example.** Not one of the thirty-seven
      composed concepts carries an ``ExampleRef``, so ``example_ids`` is
      empty everywhere and the identity claim about it would be vacuous on
      every page. That is B5 finding 4 exactly, and this is the fixture it
      asks for.

    It is a valid build, not a scratch object: the journey's steps name
    surfaces this bundle carries, and both records cite an authority it
    carries.
    """
    surfaces = (
        SurfaceRecord(
            id="cli:s0ma/init",
            channel="cli",
            public_name="s0ma init",
            intent="Start a new project with a working skeleton in it.",
            component_refs=(),
            manual_exception="Written by hand for the fixture build this record belongs to.",
            governed_by=(_FIXTURE_AUTHORITY.id,),
            side_effects=("writes a project skeleton",),
            errors=(),
            provenance=_FIXTURE_PROVENANCE,
        ),
        SurfaceRecord(
            id="cli:s0ma/check",
            channel="cli",
            public_name="s0ma check",
            intent="Read a project and say whether everything in it holds together.",
            component_refs=(),
            manual_exception="Written by hand for the fixture build this record belongs to.",
            governed_by=(_FIXTURE_AUTHORITY.id,),
            side_effects=(),
            errors=("a declaration that does not hold together",),
            provenance=_FIXTURE_PROVENANCE,
        ),
        # The approval-class surface. Its side effects are the real ones
        # the composed record carries, because the point of the fixture is
        # a rendered approval boundary and a boundary written against a
        # capability that does not ask for one would be the thing E1's
        # gate exists to refuse.
        SurfaceRecord(
            id="cli:s0ma/feedback",
            channel="cli",
            public_name="s0ma feedback",
            intent="Write up feedback about s0ma and send it once you have read it back.",
            component_refs=(),
            manual_exception="Written by hand for the fixture build this record belongs to.",
            governed_by=(_FIXTURE_AUTHORITY.id,),
            side_effects=("approval", "network"),
            errors=(),
            provenance=_FIXTURE_PROVENANCE,
        ),
    )
    journey = JourneyRecord(
        id="journey:first-project",
        intent=(
            "Take somebody who has never written a s0ma project from an empty "
            "folder to a first check they can trust."
        ),
        steps=(
            JourneyStep(
                surface="cli:s0ma/init",
                purpose=(
                    "Get a folder that is already a project rather than one "
                    "you have to make into one."
                ),
                expected_outcome=(
                    "A project skeleton, and a note saying what was written where."
                ),
            ),
            JourneyStep(
                surface="cli:s0ma/check",
                purpose=(
                    "Find out whether what you have written holds together "
                    "before you build anything on it."
                ),
                expected_outcome=(
                    "Either a clean report, or a list of what does not hold "
                    "and where to look."
                ),
            ),
            JourneyStep(
                surface="cli:s0ma/feedback",
                purpose=(
                    "Say what got in your way while it is still fresh, in "
                    "your own words."
                ),
                expected_outcome=(
                    "The report you wrote, sent once, and a note of where it "
                    "went."
                ),
                approval_boundary=(
                    "Nothing leaves your machine until you have read the "
                    "report back and said yes. Decline and the draft stays "
                    "where it is."
                ),
            ),
        ),
        recovery_paths=(
            RecoveryPath(
                when="a declaration that does not hold together",
                next_surface="cli:s0ma/check",
                action=(
                    "Read the first finding rather than the last; the ones "
                    "below it are often the same mistake seen again."
                ),
            ),
        ),
        concepts_taught=("concept:worked-example",),
        concepts_required=("concept:first-idea",),
        evidence=(
            ExampleRef(
                id="example:first_project_walkthrough",
                source="tests/test_docs_resolve_render.py",
            ),
        ),
    )
    concept = ConceptRecord(
        id="concept:worked-example",
        term="worked example",
        summary="A small, runnable illustration of an idea, kept beside the idea itself.",
        plain_definition=(
            "A worked example is a small piece of real, running code that shows "
            "one idea doing its job. It is kept beside the idea rather than in a "
            "separate collection, so that a reader who has just been told what "
            "something is can see it work without going looking."
        ),
        purpose=(
            "An example that is run by the same machinery that runs everything "
            "else cannot quietly stop being true, which is what makes it worth "
            "more than a snippet somebody pasted into a page."
        ),
        use_when="Reach for a worked example when an idea is easier to recognize than to describe.",
        do_not_use_when=(
            "Do not use one as the definition. An example shows one case; the "
            "definition has to cover the ones nobody wrote an example for."
        ),
        governed_by=(_FIXTURE_AUTHORITY.id,),
        examples=(
            ExampleRef(
                id="example:first_project_walkthrough",
                source="tests/test_docs_resolve_render.py",
            ),
        ),
        syntax=("example <name> :: PRESENTATION", "    intent: \"<what it shows>\""),
        related_concepts=(("part-of", "journey:first-project"),),
    )
    # The one idea the journey assumes rather than teaches, so that
    # ``concepts_required`` is a resolvable citation on the page rather
    # than a name the fixture invented for itself.
    assumed = ConceptRecord(
        id="concept:first-idea",
        term="first idea",
        summary="The thing a reader has to already have before a path is worth walking.",
        plain_definition=(
            "A first idea is whatever a piece of teaching takes for granted. It "
            "is not taught on the way; it is what the way is built on."
        ),
        purpose=(
            "Naming it is how a path says who it is for, instead of losing the "
            "reader at the step that assumed something."
        ),
        use_when="Reach for it when a path would not make sense without it.",
        do_not_use_when=(
            "Do not list something the path itself teaches; a prerequisite and "
            "a lesson are different claims about the same idea."
        ),
        governed_by=(_FIXTURE_AUTHORITY.id,),
        examples=(),
    )
    return stamped(
        DocsBundle(
            stamp=_empty_stamp(),
            authorities=(_FIXTURE_AUTHORITY,),
            concepts=(assumed, concept),
            surfaces=surfaces,
            journeys=(journey,),
            sequences=(),
            documents=(),
        ),
        RELEASE,
    )


#: Which build each golden comes from, and under what name.
GOLDEN_TOPICS: tuple[tuple[str, str, str], ...] = (
    *(("live", identifier, identifier) for identifier in GOLDEN_CONCEPTS),
    ("fixture", "journey:first-project", "journey:first-project"),
    ("fixture", "concept:worked-example", "concept:worked-example"),
)


def _slug(identifier: str) -> str:
    return identifier.replace(":", "-").replace("/", "-")


@lru_cache(maxsize=1)
def golden_texts() -> dict[str, str]:
    """Every golden artifact, keyed by its path under the goldens directory.

    A module-level function rather than a fixture because the determinism
    proof calls it from a *different process*: three subprocesses import
    this module under three hash seeds and compare digests of what this
    returns, which is only a proof if all four processes run the same code.
    """
    builds = {"live": golden_bundle(), "fixture": fixture_bundle()}
    indexes = {name: TopicIndex.of(bundle) for name, bundle in builds.items()}
    found: dict[str, str] = {}
    for build, identifier, _ in GOLDEN_TOPICS:
        view = indexes[build].view(identifier)
        for channel in CHANNELS:
            found[f"{build}/{_slug(identifier)}.{channel.suffix}"] = channel.render(view)
    return found


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def index() -> TopicIndex:
    return live_index()


@pytest.fixture(scope="module")
def nerve(index: TopicIndex) -> TopicView:
    return index.view("concept:nerve")


@pytest.fixture(params=GOLDEN_CONCEPTS)
def concept_view(request: pytest.FixtureRequest, index: TopicIndex) -> TopicView:
    identifier: str = request.param
    return index.view(identifier)


# ---------------------------------------------------------------------------
# The fact reading
# ---------------------------------------------------------------------------


class TestTheFactReading:
    """One account of what a topic says, and every channel reads it."""

    def test_every_group_reads_exactly_the_facts_it_declares(self) -> None:
        bundle = live_bundle()
        seen: set[str] = set()
        for group in FACT_ORDER:
            for identifier in TopicIndex.of(bundle).group(group)[:3]:
                view = TopicIndex.of(bundle).view(identifier)
                assert set(view.facts) == set(IDENTITY_FACTS) | set(FACT_ORDER[group])
                seen.add(group)
        assert seen == set(FACT_ORDER) - {"sequences"}

    def test_the_list_classification_matches_what_the_values_actually_are(
        self, index: TopicIndex
    ) -> None:
        """A fact in the wrong class is compared by the wrong rule.

        A list mistaken for prose would have its order and its item breaks
        collapsed away, so a channel could drop a line of a written form
        and the residue would agree with it.
        """
        listed: set[str] = set()
        prose: set[str] = set()
        for identifier in (*index.ids(), *TopicIndex.of(fixture_bundle()).ids()):
            source = index if identifier in index.views else TopicIndex.of(fixture_bundle())
            for name, value in source.view(identifier).facts.items():
                (listed if isinstance(value, tuple) else prose).add(name)
        assert not listed & prose, "a fact is a list in one group and prose in another"
        assert listed == LIST_FACTS & (listed | prose)
        assert listed <= LIST_FACTS
        assert not prose & LIST_FACTS

    def test_a_list_fact_is_never_read_as_prose(self, nerve: TopicView) -> None:
        with pytest.raises(DocsResolveError, match="not text"):
            nerve.text("syntax")
        with pytest.raises(DocsResolveError, match="not a list"):
            nerve.items("summary")

    def test_identity_comes_from_the_stamp_and_never_from_a_record(self) -> None:
        """C1 put the release and the snapshot on the stamp and nowhere else.

        Since H1 the version fact is the stamp's *written* form rather than
        its bare field — a build that is not a release says so on the same
        line as the number (architecture §13.2). It still comes from the
        stamp and from nothing else, which is what this test is about.
        """
        bundle = golden_bundle()
        moved = stamped(replace(bundle, stamp=_empty_stamp()), "9.9.9")
        before = facts_of(bundle, bundle.concepts[0])
        after = facts_of(moved, moved.concepts[0])
        assert before.facts["release_version"] == f"{RELEASE} (preview)"
        assert after.facts["release_version"] == "9.9.9 (preview)"
        assert before.facts["snapshot_hash"] == after.facts["snapshot_hash"]

    def test_a_release_build_writes_the_version_with_nothing_added(self) -> None:
        """The other half: the label is what a *non*-release build carries.

        A release build's pages say the version and only the version, so
        the preview label cannot be mistaken for decoration that is always
        there — which is the whole of "visibly labelled" (§13.2).
        """
        bundle = golden_bundle()
        released = stamped(
            replace(bundle, stamp=_empty_stamp()), RELEASE, build_channel="release"
        )
        assert facts_of(released, released.concepts[0]).facts["release_version"] == RELEASE
        page = render_human.render_human(facts_of(released, released.concepts[0]))
        assert f"- Release: `{RELEASE}`" in page
        assert "(preview)" not in page

    def test_the_snapshot_moves_when_any_record_in_the_build_moves(self) -> None:
        """Every topic of one build carries one stamp; a record moving re-stamps all of them."""
        bundle = golden_bundle()
        first = bundle.concepts[0]
        edited = replace(
            bundle,
            concepts=(
                replace(first, purpose=first.purpose + " Again."),
                *bundle.concepts[1:],
            ),
        )
        restamped = stamped(replace(edited, stamp=_empty_stamp()), RELEASE)
        untouched = restamped.concepts[1]
        assert facts_of(restamped, untouched).facts["snapshot_hash"] != bundle.stamp.snapshot_hash

    def test_a_cited_authority_that_is_absent_is_not_invented(self) -> None:
        bundle = replace(golden_bundle(), authorities=())
        view = facts_of(bundle, bundle.concepts[0])
        assert view.facts["authority_sources"] == ()
        assert view.facts["authority_refs"] != ()

    def test_the_three_channels_and_the_model_name_the_same_facts(self) -> None:
        """A fact added to the model without a key, a heading and a rule is a fact that vanishes."""
        for group, topical in FACT_ORDER.items():
            declared = set(IDENTITY_FACTS) | set(topical)
            assert set(render_json.spec_for(group).order) == declared, group
            human = render_human.spec_for(group)
            assert set(human.order) == declared, group
            agent = render_agent.spec_for(group)
            assert set(agent.order) <= declared, group
            assert set(IDENTITY_FACTS) <= set(agent.order), group

    def test_the_page_order_is_a_permutation_of_the_records_facts(self) -> None:
        """The page orders its sections its own way and drops nothing doing it."""
        for group, sections in render_human.SECTION_FACTS.items():
            spec = render_human.spec_for(group)
            title = render_human.TITLE_FACT[group]
            footer = {
                fact
                for fact, label in spec.labels.items()
                if label.startswith("- ")
            }
            assert set(sections) | footer | {title} == set(IDENTITY_FACTS) | set(
                FACT_ORDER[group]
            ), group
            assert not set(sections) & (footer | {title}), group
            assert len(sections) == len(set(sections)), group

    def test_the_page_order_is_not_the_records_order(self) -> None:
        """A declaration that repeated the record would be doing no work."""
        differ = [
            group
            for group, sections in render_human.SECTION_FACTS.items()
            if tuple(fact for fact in sections if fact in FACT_ORDER[group])
            != tuple(fact for fact in FACT_ORDER[group] if fact in sections)
        ]
        assert differ, "no page presents its facts in an order of its own"


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------


class TestTheResolver:
    """A question in, one topic or an honest account of why not."""

    def test_an_exact_id_resolves_to_itself(self, index: TopicIndex) -> None:
        found = resolve(index, "concept:nerve")
        assert found.state() == "resolved"
        assert found.topic is not None
        assert found.topic.id == "concept:nerve"
        assert found.candidates[0].match_class == MatchClass.EXACT_ID.name

    def test_an_old_name_resolves_to_the_one_that_survives(self, index: TopicIndex) -> None:
        """C5b renamed the structural faculty; the old id still answers."""
        found = resolve(index, "concept:structural-faculty")
        assert found.topic is not None
        assert found.topic.id == "concept:proprioception"
        assert found.candidates[0].match_class == MatchClass.ALIAS.name
        assert "renamed" in found.candidates[0].reason

    def test_a_name_beats_part_of_a_name(self, index: TopicIndex) -> None:
        found = resolve(index, "nerve")
        assert found.topic is not None
        assert found.topic.id == "concept:nerve"
        assert found.candidates[0].match_class == MatchClass.NAME.name
        assert len(found.candidates) > 1, "the weaker matches are still reported"
        assert all(
            candidate.rank >= MatchClass.NAME_SUBSTRING.rank
            for candidate in found.candidates[1:]
        )

    def test_a_name_is_matched_whatever_case_it_is_written_in(
        self, index: TopicIndex
    ) -> None:
        for spelling in ("nerve", "Nerve", "NERVE"):
            found = resolve(index, spelling)
            assert found.topic is not None and found.topic.id == "concept:nerve"

    def test_a_category_returns_the_whole_category(self, index: TopicIndex) -> None:
        found = resolve(index, "rest")
        assert found.state() == "ambiguous"
        assert found.topic is None
        assert {candidate.group for candidate in found.candidates} == {"surfaces"}
        assert {candidate.match_class for candidate in found.candidates} == {
            MatchClass.TAG.name
        }
        assert len(found.candidates) == len(index.group("surfaces")) - len(
            [item for item in index.group("surfaces") if not item.startswith("rest:")]
        )

    def test_a_category_never_outranks_a_name(self, index: TopicIndex) -> None:
        """Asking for 'concept' reaches every concept, behind anything named that."""
        found = resolve(index, "concept")
        assert found.state() == "ambiguous"
        reached = {candidate.id for candidate in found.candidates}
        assert {record.id for record in live_bundle().concepts} <= reached
        by_class = {
            candidate.id: candidate.rank for candidate in found.candidates
        }
        assert by_class["concept:nerve"] == MatchClass.TAG.rank
        assert min(by_class.values()) == MatchClass.NAME_SUBSTRING.rank

    def test_an_ambiguous_question_is_never_guessed_at(self, index: TopicIndex) -> None:
        found = resolve(index, "self")
        assert found.state() == "ambiguous"
        assert found.topic is None
        assert len(found.candidates) > 1
        assert found.finding is None, "ambiguity is a list to choose from, not a failure"

    def test_the_ranked_list_is_ordered_by_class_then_by_id_and_nothing_else(
        self, index: TopicIndex
    ) -> None:
        found = resolve(index, "self")
        keys = [(candidate.rank, candidate.id) for candidate in found.candidates]
        assert keys == sorted(keys)

    def test_the_same_question_twice_gives_the_same_ranking(
        self, index: TopicIndex
    ) -> None:
        for query in ("self", "concept", "nerve", "drift"):
            first = resolve(index, query)
            second = resolve(live_index(), query)
            assert first.candidates == second.candidates

    def test_an_unknown_question_names_the_nearest_forms(
        self, index: TopicIndex
    ) -> None:
        found = resolve(index, "concept:nervee")
        assert found.state() == "unresolved"
        assert found.finding is not None
        assert found.finding.code == DOC_TOPIC_UNRESOLVED
        assert "concept:nerve" in found.finding.remediation

    def test_a_question_that_resembles_nothing_says_how_a_topic_is_addressed(
        self, index: TopicIndex
    ) -> None:
        found = resolve(index, "zzzz")
        assert found.finding is not None
        assert nearest(index, "zzzz") == ()
        assert "kind and a colon" in found.finding.remediation

    def test_an_empty_question_is_answered_rather_than_raised(
        self, index: TopicIndex
    ) -> None:
        found = resolve(index, "   ")
        assert found.state() == "unresolved"
        assert found.finding is not None

    def test_nearest_is_the_same_list_however_the_question_is_spelled(
        self, index: TopicIndex
    ) -> None:
        assert nearest(index, "nerv") == nearest(index, "NERV")

    def test_a_circle_of_renames_is_refused_rather_than_answered(self) -> None:
        circular = TopicIndex.of(live_bundle()).merged_with(
            AliasIndex.of([("concept:a", "concept:b"), ("concept:b", "concept:a")])
        )
        with pytest.raises(DocsIdError, match="circle"):
            resolve(circular, "concept:a")

    def test_every_composed_record_answers_to_its_own_id(
        self, index: TopicIndex
    ) -> None:
        """The floor under the coverage gate: nothing composed is unaddressable."""
        for identifier in index.ids():
            found = resolve(index, identifier)
            assert found.topic is not None, identifier
            assert found.topic.id == identifier

    def test_a_bundle_holding_one_id_twice_is_refused(self) -> None:
        bundle = golden_bundle()
        doubled = replace(bundle, concepts=(*bundle.concepts, bundle.concepts[0]))
        with pytest.raises(DocsResolveError, match="twice"):
            TopicIndex.of(doubled)


# ---------------------------------------------------------------------------
# The residue
# ---------------------------------------------------------------------------


class TestTheResidue:
    """Three artifacts of three shapes, one set of facts."""

    def test_the_three_renderings_of_a_concept_agree(
        self, concept_view: TopicView
    ) -> None:
        assert divergences(concept_view, render_all(concept_view)) == []

    def test_the_three_renderings_of_every_composed_topic_agree(
        self, index: TopicIndex
    ) -> None:
        """Not a sample: every one of the four hundred, on all three channels."""
        problems: list[str] = []
        for identifier in index.ids():
            view = index.view(identifier)
            problems.extend(divergences(view, render_all(view)))
        assert problems == []

    def test_the_fixture_shapes_agree_too(self) -> None:
        built = TopicIndex.of(fixture_bundle())
        for identifier in built.ids():
            view = built.view(identifier)
            assert divergences(view, render_all(view)) == [], identifier

    def test_the_artifacts_are_genuinely_different_documents(
        self, nerve: TopicView
    ) -> None:
        """The anti-vacuity floor: three renderings that agree because they are one."""
        artifacts = render_all(nerve)
        assert len(set(artifacts.values())) == 3
        sizes = {name: len(text.encode("utf-8")) for name, text in artifacts.items()}
        assert sizes["agent"] < sizes["human"] < sizes["json"]
        assert min(sizes.values()) * 2 < max(sizes.values())

    def test_the_residue_is_the_whole_fact_map_and_not_a_slice(
        self, nerve: TopicView
    ) -> None:
        residue = residue_of(BY_NAME["json"], nerve, render_json.render_json(nerve))
        assert set(residue) == set(nerve.facts)
        assert len(residue) >= 10

    def test_the_bounded_channel_omits_without_diverging(
        self, nerve: TopicView
    ) -> None:
        artifacts = render_all(nerve)
        agent = residue_of(BY_NAME["agent"], nerve, artifacts["agent"])
        page = residue_of(BY_NAME["human"], nerve, artifacts["human"])
        assert set(agent) < set(page), "the bounded channel carries strictly fewer facts"
        assert set(IDENTITY_FACTS) <= set(agent)
        assert "plain_definition" not in agent
        assert divergences(nerve, artifacts) == []

    def test_the_bounded_channel_says_where_the_rest_is(self, nerve: TopicView) -> None:
        answer = render_agent.render_agent(nerve)
        assert "Read more" in answer
        assert nerve.id in answer.split("Read more")[1]

    def test_the_definition_is_carried_whole_or_not_at_all(
        self, concept_view: TopicView
    ) -> None:
        """Rule (b): there is no shorter version of a fact to send."""
        page = render_human.render_human(concept_view)
        assert concept_view.text("plain_definition") in page
        assert concept_view.text("plain_definition") not in render_agent.render_agent(
            concept_view
        )

    def test_the_empty_marker_is_not_something_a_record_could_say(
        self, index: TopicIndex
    ) -> None:
        """An encoding a real value can collide with is an encoding that loses data."""
        assert render_human.EMPTY_MARKER == render_agent.EMPTY_MARKER
        for identifier in index.ids():
            for value in index.view(identifier).facts.values():
                items = (value,) if isinstance(value, str) else value
                for item in items:
                    assert item != render_human.EMPTY_MARKER

    def test_no_fact_contains_the_separators_the_page_joins_with(
        self, index: TopicIndex
    ) -> None:
        """The joins are only reversible while nothing carried collides with them.

        Two real hazards, and one of them is not hypothetical: a PRD
        section anchor quotes a package name in backticks, so an item that
        merely *contains* one is normal. What would be lossy is an item
        that begins or ends with one, and what would be lossy on the
        bounded channel is a comma-and-space inside an identity list, which
        is joined onto a single line there.
        """
        for identifier in index.ids():
            for name, value in index.view(identifier).facts.items():
                if not isinstance(value, tuple):
                    continue
                for item in value:
                    assert not item.startswith("`"), (identifier, name)
                    assert not item.endswith("`"), (identifier, name)
                    if name in IDENTITY_FACTS:
                        assert ", " not in item, (identifier, name)


# ---------------------------------------------------------------------------
# Mutations that must go red
# ---------------------------------------------------------------------------


def _edited(artifacts: dict[str, str], channel: str, old: str, new: str) -> dict[str, str]:
    """One channel's artifact, with one edit made to it after rendering."""
    assert old in artifacts[channel], f"{old!r} is not in the {channel} artifact"
    changed = dict(artifacts)
    changed[channel] = artifacts[channel].replace(old, new, 1)
    assert changed[channel] != artifacts[channel]
    return changed


class TestFactualMutationsGoRed:
    """Edit a fact in a rendered artifact and the comparison notices."""

    def test_a_rewritten_authority_on_the_page(self, nerve: TopicView) -> None:
        found = divergences(
            nerve,
            _edited(
                render_all(nerve),
                "human",
                "authority:spec/nerve-declaration",
                "authority:spec/cell-declaration",
            ),
        )
        assert any("authority_refs" in line for line in found)
        assert any(DOC_CHANNEL_DIVERGENCE in line for line in found)

    def test_a_rewritten_authority_in_the_json_document(self, nerve: TopicView) -> None:
        found = divergences(
            nerve,
            _edited(
                render_all(nerve),
                "json",
                "authority:spec/nerve-declaration",
                "authority:spec/cell-declaration",
            ),
        )
        assert any("authority_refs" in line for line in found)

    def test_a_rewritten_authority_in_the_agent_answer(self, nerve: TopicView) -> None:
        found = divergences(
            nerve,
            _edited(
                render_all(nerve),
                "agent",
                "authority:spec/nerve-declaration",
                "authority:spec/cell-declaration",
            ),
        )
        assert any("authority_refs" in line for line in found)

    def test_one_softened_sentence_on_the_human_page(self, nerve: TopicView) -> None:
        found = divergences(
            nerve,
            _edited(
                render_all(nerve),
                "human",
                "A nerve is a piece of working logic",
                "A nerve is usually a piece of working logic",
            ),
        )
        assert any("plain_definition" in line for line in found)

    def test_a_reworded_summary_disagrees_across_channels(
        self, nerve: TopicView
    ) -> None:
        """Rule (c): the summary rides three channels, so an edit to one is visible twice."""
        artifacts = render_all(nerve)
        found = divergences(
            nerve, _edited(artifacts, "json", "A piece of working logic", "Some logic")
        )
        assert any("summary" in line and "disagree" in line for line in found)
        assert any("summary" in line and "record says" in line for line in found)

    def test_a_stale_snapshot_stamp_on_one_channel(self, nerve: TopicView) -> None:
        stamp = nerve.text("snapshot_hash")
        found = divergences(
            nerve, _edited(render_all(nerve), "agent", stamp, "sha256:0000000000000000")
        )
        assert any("snapshot_hash" in line for line in found)

    def test_an_identity_line_left_off_altogether(self, nerve: TopicView) -> None:
        artifacts = render_all(nerve)
        line = f"Release: {nerve.text('release_version')}\n"
        found = divergences(nerve, _edited(artifacts, "agent", line, ""))
        assert any("release_version" in line and "cannot drop identity" in line for line in found)

    def test_a_dropped_syntax_line(self, nerve: TopicView) -> None:
        found = divergences(
            nerve, _edited(render_all(nerve), "human", "    kind: <KIND>\n", "")
        )
        assert any("syntax" in line for line in found)

    def test_a_reordered_syntax_skeleton(self, nerve: TopicView) -> None:
        """Whitespace collapse must not reach a written form: order is a fact of it."""
        found = divergences(
            nerve,
            _edited(
                render_all(nerve),
                "human",
                "    kind: <KIND>\n    visibility:",
                "    visibility:",
            ),
        )
        assert any("syntax" in line for line in found)

    def test_a_section_nobody_declared(self, nerve: TopicView) -> None:
        artifacts = render_all(nerve)
        artifacts["human"] += "\n## What we think about it\n\nIt is good.\n"
        found = divergences(nerve, artifacts)
        assert any("declares none of it" in line for line in found)

    def test_a_key_nobody_declared(self, nerve: TopicView) -> None:
        artifacts = render_all(nerve)
        document = json.loads(artifacts["json"])
        document["confidence"] = "high"
        artifacts["json"] = json.dumps(document, sort_keys=True, indent=2) + "\n"
        found = divergences(nerve, artifacts)
        assert any("confidence" in line for line in found)

    def test_a_label_nobody_declared(self, nerve: TopicView) -> None:
        artifacts = render_all(nerve)
        artifacts["agent"] += "Confidence: high\n"
        found = divergences(nerve, artifacts)
        assert any("Confidence" in line for line in found)


# ---------------------------------------------------------------------------
# Mutations that must stay green
# ---------------------------------------------------------------------------


def _respelled(spec: PresentationSpec, rewrite: Any) -> PresentationSpec:
    return replace(spec, labels={fact: rewrite(label) for fact, label in spec.labels.items()})


class TestPresentationMutationsStayGreen:
    """Change how it looks and the facts are still the facts.

    Every case asserts the artifact *changed* first, so a mutation that
    silently did nothing cannot pass as a proof.
    """

    def test_every_heading_and_label_reworded(self, nerve: TopicView) -> None:
        spec = _respelled(
            render_human.spec_for(nerve.group),
            lambda label: label if label == "# " else f"{label} (as it were)",
        )
        rewritten = render_human.render_human(nerve, spec)
        assert rewritten != render_human.render_human(nerve)
        residue = {
            name: canonical_fact(name, value)
            for name, value in render_human.extract(rewritten, spec).items()
        }
        truth = {name: canonical_fact(name, value) for name, value in nerve.facts.items()}
        assert residue == truth
        assert render_human.undeclared_headings(rewritten, spec) == ()

    def test_every_block_in_the_opposite_order(self, nerve: TopicView) -> None:
        spec = render_human.spec_for(nerve.group)
        title, rest = spec.order[0], spec.order[1:]
        footer = [fact for fact in rest if spec.labels[fact].startswith("- ")]
        sections = [fact for fact in rest if fact not in footer]
        flipped = replace(spec, order=(title, *reversed(sections), *footer))
        rewritten = render_human.render_human(nerve, flipped)
        assert rewritten != render_human.render_human(nerve)
        residue = {
            name: canonical_fact(name, value)
            for name, value in render_human.extract(rewritten, flipped).items()
        }
        assert residue == {
            name: canonical_fact(name, value) for name, value in nerve.facts.items()
        }

    def test_the_agent_answer_rewrapped_and_reindented(self, nerve: TopicView) -> None:
        """The transformation the residue exists to see through."""
        answer = render_agent.render_agent(nerve)
        rewrapped = answer.replace("\n  ", "\n      ").replace(
            "what it needs", "what\n      it needs"
        )
        assert rewrapped != answer
        artifacts = render_all(nerve)
        artifacts["agent"] = rewrapped
        assert divergences(nerve, artifacts) == []

    def test_every_key_renamed_and_renested_one_level_deeper(
        self, nerve: TopicView
    ) -> None:
        spec = _respelled(
            render_json.spec_for(nerve.group),
            lambda label: "answer." + label.replace(".", ".about_the_"),
        )
        rewritten = render_json.render_json(nerve, spec)
        assert rewritten != render_json.render_json(nerve)
        assert "about_the_" in rewritten
        residue = {
            name: canonical_fact(name, value)
            for name, value in render_json.extract(rewritten, spec).items()
        }
        assert residue == {
            name: canonical_fact(name, value) for name, value in nerve.facts.items()
        }

    def test_the_page_reflowed_to_a_narrower_column(self, nerve: TopicView) -> None:
        """A page whose paragraphs were hard-wrapped still says the same things."""
        page = render_human.render_human(nerve)
        reflowed = page.replace(
            "a piece of working logic that carries",
            "a piece of\nworking logic that carries",
        )
        assert reflowed != page
        artifacts = render_all(nerve)
        artifacts["human"] = reflowed
        assert divergences(nerve, artifacts) == []

    def test_an_empty_section_left_off_a_page(self, index: TopicIndex) -> None:
        """A concept with no written form has no section for one, and agrees anyway."""
        view = index.view("concept:drift")
        assert view.items("syntax") == ()
        page = render_human.render_human(view)
        assert "How it is written" not in page
        assert divergences(view, render_all(view)) == []


# ---------------------------------------------------------------------------
# The byte budget
# ---------------------------------------------------------------------------


def _oversized(view: TopicView, repeats: int) -> TopicView:
    """The same topic with a summary written ``repeats`` times over.

    Built from a real record rather than committed as a fixture, so the
    byte counts in the finding are the counts a genuinely overlong summary
    would produce. B5 built its oversized case the same way and for the
    same reason.
    """
    record = view.record
    assert isinstance(record, ConceptRecord)
    bundle = golden_bundle()
    grown = replace(record, summary=" ".join([record.summary] * repeats))
    return facts_of(bundle, grown)


class TestTheAgentBudget:
    """A budget on the record, said in a way an author can act on."""

    def test_the_budget_is_written_in_exactly_one_place(self) -> None:
        """A budget written twice is a budget that drifts (B5's own proof)."""
        source = (
            PACKAGE_ROOT / "src" / "s0ma_dsl" / "docs_model" / "render_agent.py"
        ).read_text(encoding="utf-8")
        assert source.count(str(AGENT_BYTE_BUDGET)) == 1
        for module in ("render_human.py", "render_json.py", "resolve.py"):
            other = (
                PACKAGE_ROOT / "src" / "s0ma_dsl" / "docs_model" / module
            ).read_text(encoding="utf-8")
            assert str(AGENT_BYTE_BUDGET) not in other

    def test_every_composed_topic_fits(self, index: TopicIndex) -> None:
        oversize = []
        for identifier in index.ids():
            view = index.view(identifier)
            oversize.extend(
                item.rendered()
                for item in render_agent.check_budget(view, render_agent.render_agent(view))
            )
        assert oversize == []

    def test_the_budget_has_headroom_and_not_room_for_a_teaching_field(
        self, index: TopicIndex
    ) -> None:
        """The number's whole reason: slack for an envelope, not for a field."""
        largest = max(
            len(render_agent.render_agent(index.view(identifier)).encode("utf-8"))
            for identifier in index.ids()
        )
        headroom = AGENT_BYTE_BUDGET - largest
        assert headroom > 0, "the budget has to fit the corpus that exists"
        shortest_definition = min(
            len(record.plain_definition.encode("utf-8"))
            for record in live_bundle().concepts
        )
        assert headroom < shortest_definition, (
            f"{headroom} bytes of slack would hold the shortest definition in "
            f"the corpus ({shortest_definition} bytes); a budget that can "
            f"absorb a teaching field is not bounding anything"
        )

    def test_an_oversized_topic_names_the_field_to_shorten(
        self, nerve: TopicView
    ) -> None:
        view = _oversized(nerve, 9)
        answer = render_agent.render_agent(view)
        findings = render_agent.check_budget(view, answer)
        assert [item.code for item in findings] == [DOC_TOPIC_OVERSIZED]
        message = findings[0].message
        assert "summary" in message
        assert str(AGENT_BYTE_BUDGET) in message
        assert str(len(answer.encode("utf-8"))) in message
        assert "shorten summary in the topic itself" in findings[0].remediation
        assert "word for word" in findings[0].remediation

    def test_the_finding_clears_when_the_writing_gets_shorter(
        self, nerve: TopicView
    ) -> None:
        sizes = []
        for repeats in range(9, 0, -1):
            view = _oversized(nerve, repeats)
            answer = render_agent.render_agent(view)
            sizes.append(len(answer.encode("utf-8")))
            if not render_agent.check_budget(view, answer):
                assert repeats < 9
                break
        else:  # pragma: no cover - a one-repeat summary is the live one
            pytest.fail("the budget never cleared, however short the writing got")
        assert sizes == sorted(sizes, reverse=True)

    def test_being_over_budget_is_a_finding_about_size_and_nothing_else(
        self, nerve: TopicView
    ) -> None:
        view = _oversized(nerve, 9)
        assert render_agent.check_budget(view, render_agent.render_agent(view))
        assert divergences(view, render_all(view)) == []

    def test_the_bounded_channel_carries_a_short_form_for_every_group(self) -> None:
        """B5 finding 1: a bounded channel needs something authored to omit down to."""
        for group in FACT_ORDER:
            short = AGENT_SHORT_FACT[group]
            assert short == "" or short in FACT_ORDER[group], group


# ---------------------------------------------------------------------------
# Goldens
# ---------------------------------------------------------------------------


class TestGoldens:
    """The bytes are the bytes, in this process and in three others."""

    @pytest.mark.parametrize("name", sorted(golden_texts()))
    def test_the_rendering_matches_its_golden(self, name: str) -> None:
        path = GOLDEN_DIR / name
        assert path.is_file(), f"{name} has no golden file"
        golden = path.read_bytes().decode("utf-8")
        assert "\r" not in golden, f"{name} is not stored with line feeds"
        assert golden == golden_texts()[name], (
            f"{name} drifted from its golden. If the change is intended, "
            f"regenerate the goldens in one commit and say why."
        )

    def test_no_golden_is_stale(self) -> None:
        """A golden nobody renders any more is a file nobody is checking."""
        on_disk = {
            str(path.relative_to(GOLDEN_DIR)).replace("\\", "/")
            for path in GOLDEN_DIR.rglob("*")
            if path.is_file()
        }
        assert on_disk == set(golden_texts())

    def test_rendering_twice_in_one_process_gives_the_same_bytes(self) -> None:
        golden_texts.cache_clear()
        first = dict(golden_texts())
        golden_texts.cache_clear()
        live_bundle.cache_clear()
        golden_bundle.cache_clear()
        fixture_bundle.cache_clear()
        assert dict(golden_texts()) == first

    def test_three_hash_seeds_in_three_processes_agree(self, tmp_path: Path) -> None:
        """Dictionary order cannot reach the bytes, and a proof rather than a claim."""
        script = tmp_path / "render_once.py"
        script.write_text(
            "import hashlib, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from tests.test_docs_resolve_render import golden_texts\n"
            "digest = hashlib.sha256()\n"
            "for name, text in sorted(golden_texts().items()):\n"
            "    digest.update(name.encode('utf-8'))\n"
            "    digest.update(text.encode('utf-8'))\n"
            "print(digest.hexdigest())\n",
            encoding="utf-8",
            newline="\n",
        )
        digests = set()
        for seed in ("0", "1", "4242"):
            done = subprocess.run(  # noqa: S603
                [sys.executable, str(script), str(PACKAGE_ROOT)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(tmp_path),
                # Inherit the real environment (as the sibling determinism
                # tests do) and vary only the hash seed. A hand-built minimal
                # env dropped SystemRoot, which Winsock needs to initialize —
                # importing asyncio then dies with WinError 10106 on Windows,
                # a failure that has nothing to do with what this test checks.
                env={**os.environ, "PYTHONHASHSEED": seed},
                check=False,
            )
            assert done.returncode == 0, done.stderr
            digests.add(done.stdout.strip())
        assert len(digests) == 1, "the bytes moved between hash seeds"
        here = hashlib.sha256()
        for name, text in sorted(golden_texts().items()):
            here.update(name.encode("utf-8"))
            here.update(text.encode("utf-8"))
        assert digests == {here.hexdigest()}

    def test_the_goldens_cover_all_three_channels_and_both_builds(self) -> None:
        stems = {name.rsplit("/", 1)[1].split(".", 1)[0] for name in golden_texts()}
        assert not any("." in stem for stem in stems), "a dotted stem breaks the suffix read"
        suffixes = {name.split(".", 1)[1] for name in golden_texts()}
        assert suffixes == {channel.suffix for channel in CHANNELS}
        assert {name.split("/", 1)[0] for name in golden_texts()} == {"live", "fixture"}
        assert len(golden_texts()) == len(GOLDEN_TOPICS) * len(CHANNELS)

    def test_no_golden_is_stored_where_a_corpus_gate_would_read_it(self) -> None:
        """A rendered page is test data; the catalog is complete against documents."""
        for name in golden_texts():
            assert not name.endswith(".md"), name


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def _renderers() -> dict[str, Any]:
    return {channel.name: channel.render for channel in CHANNELS}


class TestCoverage:
    """Everything this build knows about can be asked for and shown."""

    def test_the_live_build_covers_everything_it_composed(self) -> None:
        assert check_coverage(live_bundle(), renderers=_renderers(), index=live_index()) == []

    def test_a_hidden_concept_fires_its_own_code(self) -> None:
        """The vacuity trap: the requirement and the reachable set are different sets."""
        bundle = live_bundle()
        hidden = "concept:nerve"
        narrowed = replace(
            bundle, concepts=tuple(r for r in bundle.concepts if r.id != hidden)
        )
        findings = check_coverage(
            bundle, renderers=_renderers(), index=TopicIndex.of(narrowed)
        )
        assert [item.code for item in findings] == [DOC_CONCEPT_UNCOVERED]
        assert hidden in findings[0].message

    def test_a_hidden_surface_fires_its_own_code(self) -> None:
        bundle = live_bundle()
        hidden = bundle.surfaces[0].id
        narrowed = replace(
            bundle, surfaces=tuple(r for r in bundle.surfaces if r.id != hidden)
        )
        findings = check_coverage(
            bundle, renderers=_renderers(), index=TopicIndex.of(narrowed)
        )
        assert [item.code for item in findings] == [DOC_SURFACE_UNCOVERED]
        assert hidden in findings[0].message
        assert "served capability" in findings[0].message
        assert findings[0].location == bundle.surfaces[0].provenance.source, (
            "a surface knows the file its provider read; the finding says so"
        )

    def test_a_renderer_that_shows_nothing_is_caught(self) -> None:
        bundle = golden_bundle()
        renderers = dict(_renderers())
        renderers["human"] = lambda view: ""
        findings = check_coverage(bundle, renderers=renderers, index=TopicIndex.of(bundle))
        assert len(findings) == len(bundle.concepts)
        assert all(item.code == DOC_CONCEPT_UNCOVERED for item in findings)
        assert "human" in findings[0].message

    def test_a_renderer_that_loses_the_id_is_caught(self) -> None:
        bundle = golden_bundle()
        renderers = dict(_renderers())
        renderers["agent"] = lambda view: "a page about something\n"
        findings = check_coverage(bundle, renderers=renderers, index=TopicIndex.of(bundle))
        assert all("agent" in item.message for item in findings)

    def test_a_coverage_check_with_no_reader_channel_is_refused(self) -> None:
        with pytest.raises(DocsResolveError, match="human"):
            check_coverage(golden_bundle(), renderers={"json": render_json.render_json})
        with pytest.raises(DocsResolveError, match="pass by having nothing"):
            check_coverage(golden_bundle(), renderers={})

    def test_the_gate_says_where_it_belongs(self) -> None:
        """C2 deferred these to C7; C8 armed them in application.build and
        rejected the validate fold-in (circular import; optional-argument
        vacuity). The notes now record the decision, not a promise."""
        from s0ma_dsl.docs_model.resolve import FOLD_IN
        from s0ma_dsl.docs_model.validate import DEFERRED_GATES

        assert DOC_CONCEPT_UNCOVERED not in DEFERRED_GATES
        assert DOC_SURFACE_UNCOVERED not in DEFERRED_GATES
        assert "application.build" in FOLD_IN and "C8" in FOLD_IN
        assert "rejected" in FOLD_IN


# ---------------------------------------------------------------------------
# What the corpus does not have yet
# ---------------------------------------------------------------------------


class TestWhatTheCorpusDoesNotHaveYet:
    """Two absences this milestone works around, stated rather than implied."""

    def test_the_journeys_are_composed_now_and_the_sequences_are_not(self) -> None:
        """C7's T3 note, half discharged.

        C7 rendered ``journey:first-project`` from a fixture because no
        provider emitted a journey. E1's does, so the live composition
        carries three and this suite renders the real ones. No provider
        emits a ``TeachingSequence`` yet, and no milestone has been asked
        to — the record and its gate exist, and the corpus that would use
        one does not.

        The fixture stays for its original reason even after the E wave:
        it is the one journey rendering where every field is guaranteed
        non-empty by construction, so the channel proofs cannot go vacuous
        however the live corpus evolves (B5 finding 4).
        """
        assert [record.id for record in live_bundle().journeys] == [
            "journey:drift-recovery",
            "journey:first-module",
            "journey:first-project",
            "journey:mcp-authoring-loop",
            "journey:retrofit-existing-codebase",
            "journey:studi0-feedback",
            "journey:studi0-viewing",
        ]
        assert live_bundle().sequences == ()
        assert fixture_bundle().journeys[0].approval_boundaries()
        crossing = {
            record.id
            for record in live_bundle().journeys
            if record.approval_boundaries() != ()
        }
        assert crossing == {"journey:studi0-feedback"}

    def test_not_one_composed_concept_carries_an_example(self) -> None:
        """B5 finding 4: an identity field empty everywhere proves nothing."""
        assert all(record.examples == () for record in live_bundle().concepts)
        carried = TopicIndex.of(fixture_bundle()).view("concept:worked-example")
        assert carried.items("example_ids") == ("example:first_project_walkthrough",)
        for artifact in render_all(carried).values():
            assert "example:first_project_walkthrough" in artifact

    def test_the_document_and_authority_groups_render_too(
        self, index: TopicIndex
    ) -> None:
        """Nothing in the model is a topic the read surfaces cannot show."""
        for group in ("documents", "authorities", "surfaces"):
            identifier = index.group(group)[0]
            view = index.view(identifier)
            assert divergences(view, render_all(view)) == [], identifier


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------


class TestTheVoiceOfWhatTheRendererWrites:
    """The renderer's own words are held to the product's own rule."""

    #: The word this product does not use for feedback data (plan §3.1
    #: rule 10), and the letter-o spellings of the two product names
    #: (INV-1), written with a one-character class so this file's own
    #: source never contains a forbidden literal.
    FORBIDDEN = (
        re.compile(r"\bpay[l]oads?\b", re.IGNORECASE),
        re.compile(r"\bs[o]ma\b", re.IGNORECASE),
        re.compile(r"\bstudi[o]\b", re.IGNORECASE),
    )

    def test_no_heading_label_or_marker_uses_a_word_the_product_does_not(
        self,
    ) -> None:
        written = [
            *(
                label
                for group in FACT_ORDER
                for label in render_human.spec_for(group).labels.values()
            ),
            *(
                label
                for group in FACT_ORDER
                for label in render_agent.spec_for(group).labels.values()
            ),
            render_human.EMPTY_MARKER,
            render_human.IDENTITY_HEADING,
            *render_human.ENVELOPE,
            *render_agent.ENVELOPE,
        ]
        for phrase in written:
            for pattern in self.FORBIDDEN:
                assert pattern.search(phrase) is None, phrase

    def test_the_words_the_renderer_adds_to_a_page_are_only_its_labels(
        self, concept_view: TopicView
    ) -> None:
        """Every line of the page is a declared label, or a fact word for word.

        The strongest form of B5's clause 1 this milestone can state: not
        merely that every heading is declared, but that nothing between the
        headings is anything but a record's own words.
        """
        page = render_human.render_human(concept_view)
        spec = render_human.spec_for(concept_view.group)
        headings = {
            label for label in spec.labels.values() if label.startswith("## ")
        }
        footers = {label for label in spec.labels.values() if label.startswith("- ")}
        carried = set()
        for value in concept_view.facts.values():
            for item in (value,) if isinstance(value, str) else value:
                carried.add(item.strip())
        carried.add(render_human.EMPTY_MARKER)

        unbacked: list[str] = []
        for raw in page.split("\n"):
            line = raw.strip()
            if not line or line in headings or line in render_human.ENVELOPE:
                continue
            if line.startswith("```"):
                continue
            matched = re.match(r"^- ([^:]+): `(.*)`$", line)
            if matched is not None and f"- {matched.group(1)}" in footers:
                content = matched.group(2)
            elif raw.startswith("# "):
                content = line[2:]
            elif line.startswith("- "):
                item = line[2:]
                inner = re.match(r"^`(.*)`$", item)
                content = inner.group(1) if inner is not None else item
            else:
                content = line
            if content.strip() not in carried:
                unbacked.append(raw)
        assert unbacked == [], f"the page says what no fact backs: {unbacked}"


# ---------------------------------------------------------------------------
# The catalog row this milestone was asked to add
# ---------------------------------------------------------------------------


class TestTheProductConceptsCatalogRow:
    """T4, applied at the C7 wave gate by the orchestrator.

    C7 hit the STOP it was given: the row needed two edits in
    ``test_docs_provider_catalog.py``, a file outside its Owns (the frozen
    ``BEYOND_THE_LEDGER`` set and that suite's composition fixture). The
    orchestrator landed the row and both edits together, and this pin
    flipped from absence to presence at the same moment.
    """

    def test_the_product_concepts_file_has_a_catalog_row(self) -> None:
        rows = {record.canonical_source for record in live_bundle().documents}
        assert f"{CONCEPTS_DIR}/language.json" in rows
        assert PRODUCT_CONCEPTS in rows, (
            "the T4 row left the tree; docs/s0ma_src/catalog.json must carry "
            "doc:guide/product-concepts alongside the language row"
        )

    def test_the_five_provider_composition_would_resolve_every_covered_id(self) -> None:
        """What the row would claim, proved against the composition it belongs to."""
        composed = {record.id for record in live_bundle().concepts}
        product = json.loads(
            (REPO_ROOT / PRODUCT_CONCEPTS).read_text(encoding="utf-8")
        )
        covers = {record["id"] for record in product["records"]}
        assert len(covers) == 14
        assert covers <= composed
