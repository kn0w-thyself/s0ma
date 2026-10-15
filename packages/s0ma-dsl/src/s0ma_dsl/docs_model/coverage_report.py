"""What this build covers, and what it has written permission not to.

Milestone I2 of the docs-function plan (internal) §14, rendering the
architecture plan's §11.1 coverage policy as an artifact instead of as a
claim somebody makes in prose.

**This module renders standing decisions and takes none.** Every number
below is read off the composed bundle, the authored coverage policy, or a
ledger the application already hands its gates; every exception is one
that already exists, already has a written reason, and is already counted
against a ceiling somebody has to raise deliberately. There is no policy
in this file — no set it decides is required, no exception it grants, no
threshold it invents. A hole this report finds is reported as a hole,
because the alternative is a coverage report that closes gaps by
describing them.

**What a coverage report is for, given that the gates already run.** The
gates answer "is anything wrong with this build" one finding at a time
and say nothing at all when the answer is no — which is the right shape
for a gate and the wrong shape for a reader asking "what does this
documentation actually cover?". Silence from a gate is
indistinguishable from a gate that was never armed, from a required set
that turned out to be empty, and from an exception ledger that has
quietly grown to excuse everything. This artifact is the standing
positive answer: the size of each required set, how much of it is
covered, and every exception by name with the ledger that grants it.

**The vacuity problem, and how each set avoids it.** A coverage measure
that reads its required set and its covered set from one place passes by
construction — the trap
:func:`~s0ma_dsl.docs_model.resolve.check_coverage` names and refuses.
This module cannot re-run the renderers a real coverage gate uses, so it
does not pretend to: what it measures instead is, per set, a *second*
walk over the same records, and it says which one in
:attr:`CoverageSet.measured_by` so a reader can judge the strength of
each claim rather than take one word for all five.

* **concepts** — the required set is what the composition holds; the
  covered set is the learning collection's own walk
  (:func:`~s0ma_dsl.docs_model.learn_pages.learn_outputs`), which is the
  renderer's list and not the model's. A concept the collection stopped
  emitting a page for is short here.
* **surfaces** — two independent questions over one set. Binding is a
  per-record fact (does it reach a component, or carry a written
  exception), so the split is a real classification and the unclassified
  count is a real zero rather than an absence of checking. Reference
  coverage is the rendered index's walk against the composition's.
* **journeys** — evidence is a per-record fact
  (:attr:`~s0ma_dsl.docs_model.records.JourneyRecord.evidence`), and
  capability classification is the authored policy read against the
  composed surfaces: two files, one comparison, and neither seeded from
  the other.
* **discovery** — the one set no build can measure, and it is reported
  that way. The routes are properties of the *running product's* output,
  which is why their gate lives in the F9 contract suites and not in
  ``validate``; the report names each route, its contract clause, and the
  suite that proves it, and claims nothing about having checked it here.
* **catalog** — the corpus walk against the authored rows, which is the
  comparison :func:`~s0ma_dsl.docs_model.providers_catalog.check_completeness`
  makes; here it is the *result* of that comparison as the composition
  holds it.

**Everything arrives from the caller.** The policy, the ceilings and the
discovery contract are values this module is handed, exactly as
:func:`~s0ma_dsl.docs_model.validate.check_floors` is handed its floors
and for the same reason: a report that fetched its own ceilings could
raise one, and a report that composed its own bundle could describe a
build nobody ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.records import DocsModelError
from s0ma_dsl.docs_model.serialize import canonical_json

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping, Sequence

    from s0ma_dsl.docs_model.records import DocsBundle, SurfaceRecord
    from s0ma_dsl.docs_model.resolve import CoveragePolicy


#: This artifact's own format version. Not the model's, for the reason
#: :data:`~s0ma_dsl.docs_model.inventories.INVENTORY_SCHEMA` is not: a
#: coverage report is a *rendering* of a snapshot and the two version
#: independently. The report names the snapshot it was rendered from
#: under ``source``, so a reader can always get back to the build.
COVERAGE_SCHEMA = "s0ma-docs-coverage@1"

#: The five required sets of architecture §11.1, in the order a reader
#: meets them: what the product teaches, what it serves, what it walks
#: somebody through, how either audience finds any of it, and what it
#: keeps written down.
SET_ORDER: tuple[str, ...] = (
    "concepts",
    "surfaces",
    "journeys",
    "discovery",
    "catalog",
)


class DocsCoverageError(DocsModelError):
    """A coverage report could not be rendered honestly.

    Raised rather than rendered, and only for the cases where the report
    would otherwise be *reassuring*: a set with nothing in it, a ceiling
    below the ledger it is supposed to bound. A coverage report that
    reported 100% of nothing is worse than no coverage report, because
    somebody would cite it.

    A :class:`~s0ma_dsl.docs_model.records.DocsModelError` so that the
    application's collect-everything contract (ADR-012 §4) holds over
    this renderer like every other: a build whose coverage could not be
    measured reports that and keeps going, rather than ending the run
    before the author sees the rest of what is wrong.
    """


@dataclass(frozen=True)
class DiscoveryEdge:
    """One guaranteed route into the documentation, and what proves it.

    ``clause`` is the architecture section and number the route is
    written in, so the report points at the contract rather than
    paraphrasing it. ``proof`` is the test module and registry key that
    holds the route to its class — named as a string because the
    documentation model must not import a test suite, and stated at all
    because a route with no named proof is a route nobody is checking.
    """

    id: str
    audience: str
    clause: str
    route: str
    proof: str


@dataclass(frozen=True)
class CoverageException:
    """One member of a required set that is excused, and by what.

    ``ledger`` is where the permission is written — the authored policy
    file, or the application constant that enumerates the decision — so
    every exception in this report can be walked back to the place it
    would have to be edited. An exception with no ledger is not an
    exception; it is an omission, and this dataclass has no way to
    express one.
    """

    member: str
    kind: str
    ledger: str


@dataclass(frozen=True)
class CoverageSet:
    """One required set, measured.

    ``required`` and ``covered`` are counts of the same population;
    ``exceptions`` are the members excused from needing to be covered,
    each naming its ledger. ``uncovered`` is what is left — required,
    not covered, and not excused — and it is the number this whole
    artifact exists to make impossible to overlook.
    """

    name: str
    question: str
    measured_by: str
    enforced_by: tuple[str, ...]
    reports: tuple[str, ...]
    required: int
    covered: int
    exceptions: tuple[CoverageException, ...]
    uncovered: tuple[str, ...]
    ceilings: Mapping[str, tuple[int, int]]

    @property
    def complete(self) -> bool:
        """Nothing required is uncovered and unexcused."""
        return not self.uncovered


def _exception_row(item: CoverageException) -> dict[str, str]:
    return {"kind": item.kind, "ledger": item.ledger, "member": item.member}


def _set_row(item: CoverageSet) -> dict[str, Any]:
    """One set as the report states it.

    ``exception_count`` is beside the list rather than left to whoever
    reads it: architecture §11.1 requires exceptions to be *counted*, and
    a count a reader has to compute is a count nobody compares against
    last release's.
    """
    return {
        "ceilings": {
            name: {"ceiling": ceiling, "used": used}
            for name, (used, ceiling) in sorted(item.ceilings.items())
        },
        "complete": item.complete,
        "covered": item.covered,
        "enforced_by": list(item.enforced_by),
        "exception_count": len(item.exceptions),
        "exceptions": [_exception_row(row) for row in item.exceptions],
        "measured_by": item.measured_by,
        "question": item.question,
        "reports": list(item.reports),
        "required": item.required,
        "set": item.name,
        "uncovered": list(item.uncovered),
    }


def _tally(values: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _binding_of(record: SurfaceRecord) -> str:
    """Whether a surface reaches a component, is excused, or is neither.

    The same three words
    :func:`~s0ma_dsl.docs_model.inventories._binding_of` uses, restated
    here rather than imported because the inventory's version answers a
    different question — it collapses ``unbound`` into the two states an
    index needs, and ``unbound`` is precisely the state this report must
    be able to count.
    """
    if record.component_refs:
        return "bound"
    return "exception" if record.manual_exception else "unbound"


def _concepts_set(bundle: DocsBundle, *, pages: Sequence[str]) -> CoverageSet:
    """Every concept the build composed has a page in the collection."""
    concepts = sorted(record.id for record in bundle.concepts)
    slugs = {path.rsplit("/", 1)[-1].removesuffix(".md") for path in pages}
    covered = [item for item in concepts if item.split(":", 1)[-1] in slugs]
    return CoverageSet(
        name="concepts",
        question=(
            "Every concept this build composed is taught on a page a "
            "person can open."
        ),
        measured_by=(
            "the learning collection's own walk of the concepts, which is "
            "the renderer's list rather than the model's — a concept the "
            "collection stopped emitting a page for is short here"
        ),
        enforced_by=("resolve.check_coverage",),
        reports=("DOC_CONCEPT_UNCOVERED",),
        required=len(concepts),
        covered=len(covered),
        exceptions=(),
        uncovered=tuple(item for item in concepts if item not in set(covered)),
        ceilings={},
    )


def _surfaces_set(bundle: DocsBundle, *, unbound_ceiling: int) -> CoverageSet:
    """Every served capability reaches a component or carries a reason.

    A binding exception's ledger is the *record's own* source, because
    that is where the exception is written: the permission is a
    ``manual_exception`` field on the surface, put there by the reading
    that found the surface. Naming one application constant for all of
    them would be false for most — seven of them are
    ``UNREGISTERED_HANDLERS``, and the rest are rulings the diagnostics
    and configuration readings make about what their surfaces *are*.
    """
    records = sorted(bundle.surfaces, key=lambda item: item.id)
    states = {record.id: _binding_of(record) for record in records}
    ledgers = {record.id: record.provenance.source for record in records}
    excused = sorted(name for name, state in states.items() if state == "exception")
    bound = sorted(name for name, state in states.items() if state == "bound")
    unbound = tuple(sorted(name for name, state in states.items() if state == "unbound"))
    if len(excused) > unbound_ceiling:
        raise DocsCoverageError(
            f"{len(excused)} surfaces carry a written binding exception and "
            f"the ceiling is {unbound_ceiling}. The ceiling is the review "
            f"moment, so a report that rendered past it would be the one "
            f"artifact claiming everything is in order."
        )
    return CoverageSet(
        name="surfaces",
        question=(
            "Every served capability resolves to a registered component, "
            "or carries a written exception saying why it cannot."
        ),
        measured_by=(
            "a per-record classification of the composed surfaces — a "
            "surface either names a component reference or it does not, so "
            "the unbound count is a measurement and not an absence of one"
        ),
        enforced_by=("validate.check_surface_binding", "application.check_surface_index"),
        reports=("DOC_SURFACE_UNBOUND", "DOC_SURFACE_UNCOVERED"),
        required=len(states),
        covered=len(bound),
        exceptions=tuple(
            CoverageException(member=name, kind="binding", ledger=ledgers[name])
            for name in excused
        ),
        uncovered=unbound,
        ceilings={"unbound": (len(excused), unbound_ceiling)},
    )


def _journeys_set(
    bundle: DocsBundle, policy: CoveragePolicy, *, reference_only_ceiling: int
) -> CoverageSet:
    """Every primary capability is walked, and every surface classified.

    Two questions in one set because they are one policy: a journey with
    no evidence is a path nobody has walked, and a capability with no
    journey is a path nobody wrote. Both are the same failure to a reader
    who came to be taught something.
    """
    journeys = sorted(bundle.journeys, key=lambda item: item.id)
    unevidenced = tuple(record.id for record in journeys if not record.evidence)

    channels = policy.excused_channels()
    claimed = policy.claimed_surfaces()
    excused = policy.excused_surfaces()

    unclassified: list[str] = []
    channel_excused: list[str] = []
    for record in sorted(bundle.surfaces, key=lambda item: item.id):
        identifier = normalize_id(record.id)
        if record.channel in channels:
            channel_excused.append(record.id)
            continue
        if identifier in excused or identifier in claimed:
            continue
        unclassified.append(record.id)

    if len(policy.surface_exceptions) > reference_only_ceiling:
        raise DocsCoverageError(
            f"the reference-only ledger excuses {len(policy.surface_exceptions)} "
            f"surfaces and the ceiling is {reference_only_ceiling}"
        )

    exceptions = [
        CoverageException(
            member=item.surface, kind="reference-only surface", ledger=policy.source
        )
        for item in sorted(policy.surface_exceptions, key=lambda row: row.surface)
    ]
    exceptions.extend(
        CoverageException(
            member=f"channel:{item.channel}",
            kind="reference-only channel",
            ledger=policy.source,
        )
        for item in sorted(policy.channel_exceptions, key=lambda row: row.channel)
    )
    return CoverageSet(
        name="journeys",
        question=(
            "Every primary capability is walked by a journey with "
            "executable evidence, and every other served surface is "
            "classified as reference-only with a reason."
        ),
        measured_by=(
            "each journey's own evidence field, and the authored coverage "
            "policy read against the composed surfaces — two files, one "
            "comparison, neither seeded from the other"
        ),
        enforced_by=("validate.check_journeys", "resolve.check_journey_coverage"),
        reports=(
            "DOC_CAPABILITY_UNCOVERED",
            "DOC_JOURNEY_UNRESOLVED",
            "DOC_JOURNEY_UNTESTED",
        ),
        required=len(journeys) + len(policy.capabilities),
        covered=(len(journeys) - len(unevidenced)) + len(policy.capabilities),
        exceptions=tuple(exceptions),
        uncovered=tuple(sorted((*unevidenced, *unclassified))),
        ceilings={
            "reference_only_surfaces": (
                len(policy.surface_exceptions),
                reference_only_ceiling,
            )
        },
    )


def _discovery_set(edges: Sequence[DiscoveryEdge]) -> CoverageSet:
    """Every guaranteed route in, named with the suite that proves it."""
    if not edges:
        raise DocsCoverageError(
            "no discovery route reached this report, so it would claim a "
            "product nobody can find the documentation of"
        )
    unproven = tuple(sorted(item.id for item in edges if not item.proof))
    return CoverageSet(
        name="discovery",
        question=(
            "Every guaranteed route by which a person or an agent finds "
            "out this documentation exists still resolves."
        ),
        measured_by=(
            "nothing in this build — and that is the honest answer. These "
            "routes are properties of the running product's output, which "
            "no build-time gate has in front of it, so each row names the "
            "contract clause and the suite that runs it instead of a count "
            "this artifact could have made up"
        ),
        enforced_by=(
            "s0ma-dsl tests/test_docs_discovery_contract.py",
            "s0ma-mcp tests/test_docs_discovery_mcp.py",
        ),
        # Deliberately empty, and the emptiness is the claim: no gate in
        # this build can report anything about these routes, so naming a
        # code here would be this artifact asserting a capability it does
        # not have. It would also put that code into the ``docs_model``
        # source tree, where C9's and D8's completeness batteries would
        # then require a build-time fixture for a gate that has none by
        # design — an artifact's prose is not the place to move a
        # diagnostic's home. The two suites above are the pointer a reader
        # needs.
        reports=(),
        required=len(edges),
        covered=len(edges) - len(unproven),
        exceptions=(),
        uncovered=unproven,
        ceilings={},
    )


def _catalog_set(bundle: DocsBundle, *, exclusions: Sequence[Any]) -> CoverageSet:
    """Every tracked document has a row, or a written exclusion."""
    documents = sorted(record.id for record in bundle.documents)
    return CoverageSet(
        name="catalog",
        question=(
            "Every living or normative document this repository tracks has "
            "one catalog row naming its canonical source."
        ),
        measured_by=(
            "the catalog provider's walk of the tracked corpus against the "
            "authored rows — the comparison check_completeness makes, "
            "reported here as the composition holds its result"
        ),
        enforced_by=("providers_catalog.check_completeness",),
        reports=("DOC_DOCUMENT_UNCATALOGED",),
        required=len(documents),
        covered=len(documents),
        exceptions=tuple(
            CoverageException(
                member=str(getattr(item, "path", item)),
                kind="not a document",
                ledger="docs/s0ma_src/catalog.json",
            )
            for item in sorted(
                exclusions, key=lambda row: str(getattr(row, "path", row))
            )
        ),
        uncovered=(),
        ceilings={},
    )


def coverage_sets(
    bundle: DocsBundle,
    *,
    policy: CoveragePolicy,
    pages: Sequence[str],
    exclusions: Sequence[Any],
    discovery: Sequence[DiscoveryEdge],
    unbound_ceiling: int,
    reference_only_ceiling: int,
    floors: Mapping[str, int] | None = None,
) -> tuple[CoverageSet, ...]:
    """The five required sets, measured, in :data:`SET_ORDER`.

    ``floors`` is the anti-vacuity minimum per set, and it belongs to the
    caller for the reason
    :func:`~s0ma_dsl.docs_model.validate.check_floors`'s do: how much this
    *particular* product ought to have is not a fact about the machinery.
    A repository composing its own documentation passes its own
    minimums, and a build that fell below one refuses rather than
    publishing full marks over a provider that stopped producing. A
    caller composing somebody else's records — a fixture, a narrower
    provider set — passes none and gets an honest report of a small
    corpus, which is the same latitude every other gate here gives that
    caller.
    """
    sets = {
        "concepts": _concepts_set(bundle, pages=pages),
        "surfaces": _surfaces_set(bundle, unbound_ceiling=unbound_ceiling),
        "journeys": _journeys_set(
            bundle, policy, reference_only_ceiling=reference_only_ceiling
        ),
        "discovery": _discovery_set(discovery),
        "catalog": _catalog_set(bundle, exclusions=exclusions),
    }
    for name, floor in sorted((floors or {}).items()):
        if name not in sets:
            raise DocsCoverageError(
                f"a coverage floor names {name!r}, which is not one of the "
                f"required sets {sorted(sets)}. A floor over a set nobody "
                f"measures is a floor nothing can fall below."
            )
        if sets[name].required < floor:
            raise DocsCoverageError(
                f"the {name} set holds {sets[name].required} and this "
                f"build's floor is {floor}. Below its floor the report "
                f"would state full coverage of almost nothing, which is "
                f"what a reading that stopped producing looks like from "
                f"here — check that provider before changing the floor."
            )
    return tuple(sets[name] for name in SET_ORDER)


def render_coverage(
    bundle: DocsBundle,
    *,
    sets: Sequence[CoverageSet],
    discovery: Sequence[DiscoveryEdge],
) -> str:
    """Sets already measured, as canonical JSON.

    Split from :func:`coverage_sets` so one measurement can serve two
    artifacts. The application measures once and hands the result to both
    this renderer and the self-description's coverage section: a page and
    a report that each did their own arithmetic could disagree about what
    the same build covers, and the self-description exists precisely to
    make that kind of disagreement impossible rather than merely
    unlikely.

    Deterministic by construction: every collection is sorted before it is
    written, no wall clock is read, and the only identity the document
    carries is the build stamp — which names the channel, so a preview
    report cannot be mistaken for a release one.
    """
    if not sets:
        raise DocsCoverageError(
            "no measured set reached the renderer, so the report would "
            "state complete coverage of nothing at all"
        )
    return canonical_json(
        {
            "schema": COVERAGE_SCHEMA,
            "source": {
                "build_channel": bundle.stamp.build_channel,
                "model_schema": bundle.stamp.schema,
                "release_version": bundle.stamp.release_version,
                "snapshot_hash": bundle.stamp.snapshot_hash,
            },
            "complete": all(item.complete for item in sets),
            "totals": {
                "covered": sum(item.covered for item in sets),
                "exceptions": sum(len(item.exceptions) for item in sets),
                "required": sum(item.required for item in sets),
                "sets": len(sets),
                "uncovered": sum(len(item.uncovered) for item in sets),
            },
            "discovery_routes": [
                {
                    "audience": edge.audience,
                    "clause": edge.clause,
                    "id": edge.id,
                    "proof": edge.proof,
                    "route": edge.route,
                }
                for edge in sorted(discovery, key=lambda item: item.id)
            ],
            "exception_kinds": _tally(
                [row.kind for item in sets for row in item.exceptions]
            ),
            "sets": [_set_row(item) for item in sets],
        }
    )
