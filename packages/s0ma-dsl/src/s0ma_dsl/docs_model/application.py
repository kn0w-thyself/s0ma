"""The documentation application: one composition, run one way, twice.

Milestone C8 of the docs-function plan (internal) §8. Everything before
this module is machinery that *could* be composed; this is the one place
that says how this repository's documentation actually is composed — which
providers, which gates, which artifacts — so that the write command and
the check command cannot disagree about it.

That single-definition property is the whole design. ``s0ma docs compose``
and ``s0ma docs check`` both call :func:`build` and differ only in what
they do with the result: one writes the bytes, the other compares them.
A drift report is therefore never an artifact of two code paths drifting
apart, which is the failure a check gate built beside its writer always
eventually has.

**The ordered phases** (architecture plan §10.1), and where each lands:

1. *catalog syntax, canonical paths, status, authority records* —
   :class:`~s0ma_dsl.docs_model.providers_catalog.CatalogProvider` refuses
   a malformed file while loading; ``check_completeness``,
   ``check_canonical_sources`` and ``check_document_authorities``, all in
   :mod:`~s0ma_dsl.docs_model.providers_catalog`, report the rest.
2. *fresh package snapshots* — :class:`~s0ma_dsl.docs_model.providers_core.CoreProvider`
   boots its own registry per build (ADR-012 §3: no persisted registry).
3. *deterministic source adapters* — the eleven providers of
   :func:`registry`.
4. *compose* — :func:`~s0ma_dsl.docs_model.compose.compose`.
5. *resolve every edge* — :func:`~s0ma_dsl.docs_model.validate.check_references`,
   through :func:`~s0ma_dsl.docs_model.validate.validate_bundle`.
6. *authority conflicts, duplicate identity* — the composition's own
   findings plus :func:`~s0ma_dsl.docs_model.validate.check_authority_records`.
7. *assertions and coverage* — :func:`~s0ma_dsl.docs_model.resolve.check_coverage`
   over the real renderers,
   :func:`~s0ma_dsl.docs_model.providers_concepts.check_concept_relations`,
   and, since E8, :func:`~s0ma_dsl.docs_model.resolve.check_journey_coverage`
   over the policy authored at :data:`COVERAGE_POLICY` — the two halves of
   architecture §11.1: can every topic be *shown*, and is every primary
   capability *taught*.
8. *examples and transcript fixtures* — :class:`~s0ma_dsl.docs_model.evidence.EvidenceLibrary`,
   **read but not run** (E2 T3). The library resolves each journey's
   evidence to a committed fixture and arms
   ``DOC_JOURNEY_UNTESTED`` by handing
   :func:`~s0ma_dsl.docs_model.validate.validate_bundle` a resolver;
   replaying a fixture starts subprocesses and a server, which SDA-INV-8
   forbids this build from doing, so the execution half lives in the
   suite (``test_docs_evidence.py``) and a test there pins the resolved
   set equal to the executed one.
9. *render every artifact in memory* — :attr:`Build.artifacts`.
   The composed snapshot, the machine-readable inventories and the two
   reader indexes from :mod:`~s0ma_dsl.docs_model.inventories`, the map
   of record, the generated references of
   :mod:`~s0ma_dsl.docs_model.reference_pages` and
   :mod:`~s0ma_dsl.docs_model.reference_pages_surfaces`, the
   self-description of
   :mod:`~s0ma_dsl.docs_model.self_description`, the core teaching
   slice of :mod:`~s0ma_dsl.docs_model.bundle_core`, the learning
   collection of :mod:`~s0ma_dsl.docs_model.learn_pages`, the media
   packages of :mod:`~s0ma_dsl.docs_model.render_media`, I2's coverage
   report from :mod:`~s0ma_dsl.docs_model.coverage_report`, the quick
   reference of :mod:`~s0ma_dsl.docs_model.quick_reference` in its two
   renderings, and the documentation manifest of
   :mod:`~s0ma_dsl.docs_model.manifest`. The
   paths in :data:`STATIC_OUTPUTS` are decided and the rest are computed
   — the learning collection from the concepts the build composed, the
   media packages from the journeys its catalog publishes — and
   :func:`generated_outputs` is the whole set. Counting them is
   :func:`generated_outputs`'s job and not this paragraph's: a number
   written here is a number that stops being true the first time a
   concept is added. Nothing this module does touches the filesystem.
10. *write, or compare* — :func:`write` and :func:`check`, the only two
    functions here that know a filesystem exists, and only one of them
    writes to it.
11. *package mirrors and release manifests* — F phase.

**Check mode never writes** (SDA-INV-9). :func:`check` is handed the same
in-memory artifacts :func:`write` would have written and compares them
against what is committed. It needs no temporary directory to do that,
which is a stronger guarantee than rendering to one: there is no path
through this module on which check mode opens a file for writing.

**Determinism.** No wall clock, no network, no randomness, no machine
path. The one process this build runs is ``git ls-files``, in
:func:`~s0ma_dsl.docs_model.providers_catalog.tracked_markdown`, and it is
a read of the local checkout. Every artifact is UTF-8 with LF endings and
a trailing newline, and every collection that reaches an artifact is
sorted before it gets there.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model import learn_pages, quick_reference, render_media
from s0ma_dsl.docs_model.bundle_core import core_teaching_slice
from s0ma_dsl.docs_model.compose import compose
from s0ma_dsl.docs_model.coverage_report import (
    DiscoveryEdge,
    coverage_sets,
    render_coverage,
)
from s0ma_dsl.docs_model.evidence import EvidenceLibrary, check_evidence_voice
from s0ma_dsl.docs_model.ids import AliasIndex
from s0ma_dsl.docs_model.inventories import (
    component_facts,
    components_inventory,
    concepts_index,
    concepts_inventory,
    surfaces_index,
    surfaces_inventory,
)
from s0ma_dsl.docs_model.manifest import (
    channel_of,
    manifest_from_json,
    manifest_of,
    render_manifest,
)
from s0ma_dsl.docs_model.map_of_record import map_of_record
from s0ma_dsl.docs_model.providers import Finding, ProviderRegistry, sort_findings
from s0ma_dsl.docs_model.providers_catalog import (
    CATALOG_FLOORS,
    CatalogProvider,
    check_canonical_sources,
    check_completeness,
    check_document_authorities,
    tracked_markdown,
)
from s0ma_dsl.docs_model.providers_cli import (
    BOUND_DIRECTLY,
    BOUND_TO_OWNING_CLASS,
    CliProvider,
)
from s0ma_dsl.docs_model.providers_cli import FLOORS as CLI_FLOORS
from s0ma_dsl.docs_model.providers_concepts import (
    CONCEPTS_DIR,
    LANGUAGE_FLOORS,
    ConceptsProvider,
    check_concept_relations,
)
from s0ma_dsl.docs_model.providers_config import CONFIG_FLOORS, ConfigProvider
from s0ma_dsl.docs_model.providers_core import FLOORS as CORE_FLOORS
from s0ma_dsl.docs_model.providers_core import CoreProvider
from s0ma_dsl.docs_model.providers_diagnostics import (
    DIAGNOSTIC_FLOORS,
    DiagnosticsProvider,
)
from s0ma_dsl.docs_model.providers_journeys import JOURNEY_FLOORS, JourneysProvider
from s0ma_dsl.docs_model.providers_mcp import MCP_FLOORS, McpProvider
from s0ma_dsl.docs_model.providers_repo import (
    REPOSITORY_FLOORS,
    RepoProvider,
    package_facts,
)
from s0ma_dsl.docs_model.providers_studi0 import FLOORS as STUDI0_FLOORS
from s0ma_dsl.docs_model.providers_studi0 import Studi0Provider
from s0ma_dsl.docs_model.quick_reference import (
    QUICK_REFERENCE_MACHINE_OUTPUT,
    QUICK_REFERENCE_OUTPUT,
    check_quick_reference_voice,
    quick_reference_source,
)
from s0ma_dsl.docs_model.records import AliasEntry, DocsModelError
from s0ma_dsl.docs_model.reference_pages import (
    CLI_REFERENCE_OUTPUT,
    CONFIGURATION_REFERENCE_OUTPUT,
    DIAGNOSTICS_REFERENCE_OUTPUT,
    cli_reference,
    configuration_reference,
    diagnostics_reference,
)
from s0ma_dsl.docs_model.reference_pages_surfaces import (
    component_index,
    distribution_facts,
    mcp_reference,
    packages_reference,
    studi0_reference,
)
from s0ma_dsl.docs_model.render_agent import render_agent
from s0ma_dsl.docs_model.render_human import render_human
from s0ma_dsl.docs_model.resolve import (
    DOC_SURFACE_UNCOVERED,
    CoveragePolicy,
    DocsResolveError,
    TopicIndex,
    check_coverage,
    check_journey_coverage,
    coverage_policy_from_mapping,
)
from s0ma_dsl.docs_model.self_description import (
    application_module,
    docs_application,
    gate_facts,
)
from s0ma_dsl.docs_model.serialize import serialize_bundle
from s0ma_dsl.docs_model.validate import check_manifest, validate_bundle

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path
    from types import ModuleType
    from typing import Any

    from s0ma_dsl.docs_model.providers import ProviderResult
    from s0ma_dsl.docs_model.providers_catalog import CatalogRow, Exclusion
    from s0ma_dsl.docs_model.providers_cli import CommandInterface
    from s0ma_dsl.docs_model.providers_mcp import MirrorDocument
    from s0ma_dsl.docs_model.records import DocsBundle

__all__ = [
    "APPLICATION_FLOORS",
    "APPLICATION_IR",
    "ARTIFACT_FLOOR",
    "BOUND_CLASSES",
    "CLI_REFERENCE_OUTPUT",
    "COMPONENTS_INVENTORY_OUTPUT",
    "COMPONENT_INDEX_OUTPUT",
    "CONCEPTS_INDEX_OUTPUT",
    "CONCEPTS_INVENTORY_OUTPUT",
    "CONFIGURATION_REFERENCE_OUTPUT",
    "CORE_SLICE_OUTPUT",
    "COVERAGE_FLOORS",
    "COVERAGE_POLICY",
    "COVERAGE_REPORT_OUTPUT",
    "DIAGNOSTICS_REFERENCE_OUTPUT",
    "DISCOVERY_CONTRACT",
    "DOC_GATE_VACUOUS",
    "DOC_OUTPUT_DRIFT",
    "DOCS_APPLICATION_OUTPUT",
    "DOCS_MANIFEST_OUTPUT",
    "DOCS_ROOT",
    "MAP_OUTPUT",
    "MCP_REFERENCE_OUTPUT",
    "PACKAGES_REFERENCE_OUTPUT",
    "PRODUCT_CONCEPTS",
    "PRODUCT_DOMAIN",
    "PRODUCT_FLOORS",
    "QUICK_REFERENCE_MACHINE_OUTPUT",
    "QUICK_REFERENCE_OUTPUT",
    "REFERENCE_ONLY_CEILING",
    "SIDE_EFFECT_ALLOWANCES",
    "SNAPSHOT_OUTPUT",
    "STATIC_OUTPUTS",
    "STUDI0_REFERENCE_OUTPUT",
    "SURFACES_INDEX_OUTPUT",
    "SURFACES_INVENTORY_OUTPUT",
    "UNBOUND_CEILING",
    "UNREGISTERED_HANDLERS",
    "Artifact",
    "Build",
    "build",
    "check",
    "check_surface_index",
    "coverage_policy",
    "gate_modules",
    "generated_outputs",
    "registry",
    "release_version",
    "write",
]

# ---------------------------------------------------------------------------
# Where the application lives
# ---------------------------------------------------------------------------

#: The documentation application's root, relative to the checkout
#: (ADR-012 §1). Also the base that declared outputs resolve against, which
#: is what makes the renderer's confinement rule mean "inside ``docs/``".
DOCS_ROOT = "docs"

#: The composed snapshot, relative to :data:`DOCS_ROOT`. ADR-012 §1 puts
#: structured outputs under ``_generated/`` — machine-readable only, never
#: a reader-facing page.
SNAPSHOT_OUTPUT = "_generated/s0ma-docs-model.json"

#: The three machine-readable inventories (D6). Same directory as the
#: snapshot and for the same reason: a program reads them and a person does
#: not. They are not a second copy of the snapshot — each is one question
#: answered completely, with the counts computed rather than written, which
#: is what lets another document cite a number instead of counting.
CONCEPTS_INVENTORY_OUTPUT = "_generated/inventory-concepts.json"
SURFACES_INVENTORY_OUTPUT = "_generated/inventory-surfaces.json"
COMPONENTS_INVENTORY_OUTPUT = "_generated/inventory-components.json"

#: The two reader-facing indexes (D6) — the first generated Markdown this
#: application commits. ``reference/`` rather than ``_generated/`` is
#: ADR-012 §1's other half: a page a person opens lives where reader-facing
#: pages live, and only its *provenance* makes it generated. Each carries a
#: sentence saying so and where the edit really goes.
CONCEPTS_INDEX_OUTPUT = "reference/concepts-index.md"
SURFACES_INDEX_OUTPUT = "reference/surfaces-index.md"

#: The map of record (F2): every document this repository keeps, grouped by
#: architecture §9.1's information architecture. It is ``README.md`` at the
#: documentation root rather than another page under ``reference/`` because
#: it is the page a reader arrives at — GitHub renders it when somebody
#: opens ``docs/``, and the docs audit's finding was precisely that no such
#: page existed. Generated for the same reason the two indexes are: a map
#: maintained by hand is a map that stops naming the newest document first.
MAP_OUTPUT = "README.md"

#: The four surface references (F4). ``reference/`` for the three a reader
#: opens to find out what one server, one viewer or one distribution
#: offers; ``architecture/`` for the component index, which answers a
#: contributor's question about where the code is rather than a user's
#: about what the product does — and which succeeds the hand-maintained
#: architecture document the August 2026 audit found had stopped naming
#: half of them.
#:
#: The three F3 references are imported rather than declared here, because
#: :func:`~s0ma_dsl.docs_model.reference_pages.deep_link` has to name a
#: page and a second copy of a path is a second thing that can be edited
#: alone. F4's renderers take the page they render as a parameter, so
#: theirs are declared where the application decides them: here.
MCP_REFERENCE_OUTPUT = "reference/mcp.md"
STUDI0_REFERENCE_OUTPUT = "reference/studi0.md"
PACKAGES_REFERENCE_OUTPUT = "reference/packages.md"
COMPONENT_INDEX_OUTPUT = "architecture/component-index.md"

#: The self-description (I1, architecture §15's M7 acceptance): the
#: readings this application composes from, the gates it runs, what its
#: own s0ma module registers, and every file it writes.
#:
#: ``architecture/`` beside the component index and for the same reason —
#: it answers a contributor's question about how this repository is put
#: together rather than a user's about what the product does — and it is a
#: reader-facing page rather than a ``_generated/`` artifact, so it carries
#: a catalog row exactly as its neighbour does.
DOCS_APPLICATION_OUTPUT = "architecture/docs-application.md"

#: The documentation application's own committed canonical IR,
#: repository-relative: what ``s0ma build --project-root docs`` emits from
#: ``docs/s0ma_src/application.s0ma``. It is where the self-description
#: reads the application's own registrations, which is the same reading
#: :func:`~s0ma_dsl.docs_model.inventories.component_facts` makes of the
#: two transpiled packages — pointed at the third s0ma project in this
#: repository, which is this one.
APPLICATION_IR = f"{DOCS_ROOT}/_built/application.s0ma.json"

#: The core teaching slice (F8, owner decision D-9). ``_generated/``
#: because it is a machine artifact and not a page: nobody opens it, a
#: program reads it, and the reader is
#: :mod:`s0ma.api.teaching` in another distribution entirely.
#:
#: It is the one declared output of this application that is *also* copied
#: somewhere else — byte for byte into ``s0ma/_teaching/slice.json``, inside
#: the packaged tree, so the core wheel ships it and a pip-installed core
#: can answer a teaching question without the repository. The copy is held
#: equal to this file by a drift gate in core's own suite, the way every
#: other committed mirror in this repository is; what this application owns
#: is the one file it renders, and it writes nothing outside ``docs/``
#: (ADR-012 §2.3 rule B-3).
CORE_SLICE_OUTPUT = "_generated/core-teaching-slice.json"

#: The coverage report (I2, architecture §11.1): the size of every
#: required set, how much of it this build covers, and every standing
#: exception by name with the ledger that grants it. ``_generated/`` for
#: the reason the inventories are — a program reads it, and the reader
#: this one is for is a release review comparing one build's exception
#: count against the last one's.
#:
#: It has no reader-facing companion page of its own, and that is a
#: decision rather than an omission: the human rendering is a section of
#: :data:`DOCS_APPLICATION_OUTPUT`, because what a documentation build
#: covers is a fact *about this application*, and I1 established one page
#: as the application's account of itself. A second page carrying the
#: other half of that account would be one topic with two homes — the
#: fork Phase G spent its budget closing — so the JSON is the machine
#: artifact and the self-description is where a person reads it.
COVERAGE_REPORT_OUTPUT = "_generated/coverage-report.json"

#: The documentation manifest (H1, architecture §13.1): what this build is,
#: written down so another build can be compared against it. ``_generated/``
#: for the same reason the snapshot is — nobody opens it, and its readers
#: are programs: H2's wheel verification compares the slice a wheel carries
#: against this file's snapshot digest, and a release build's manifest is
#: the record of what a release actually shipped.
#:
#: It is rendered **last** among the declared outputs and it does not list
#: itself: see :func:`_artifacts`.
DOCS_MANIFEST_OUTPUT = "_generated/docs-manifest.json"

#: Every path this application writes that is a **decision**, relative to
#: :data:`DOCS_ROOT`. Twenty: the composed snapshot, three machine-
#: readable inventories, two reader indexes, the map of record, F3's three
#: per-family references, F4's four surface references, I1's
#: self-description, F8's core teaching slice, H1's documentation
#: manifest, I2's coverage report, and the quick reference in its two
#: renderings — the page a person reads and the same facts as data (owner
#: decision, 2026-09-29; their paths are declared in
#: :mod:`~s0ma_dsl.docs_model.quick_reference`, beside the one value both
#: are rendered from). Each one is here because
#: somebody decided this repository should commit that page, and the order
#: is the order they are introduced above.
#:
#: This is no longer the whole declared-output set — see
#: :func:`generated_outputs`, which is what :func:`write` writes and
#: :func:`check` compares. The split is F5's: a page per concept is not a
#: decision anybody takes page by page, so listing thirty-nine of them
#: here would be exactly the independently maintained inventory
#: architecture §8.2 forbids, and the thirty-eighth concept would ship
#: with no page until somebody remembered this tuple.
STATIC_OUTPUTS: tuple[str, ...] = (
    SNAPSHOT_OUTPUT,
    CONCEPTS_INVENTORY_OUTPUT,
    SURFACES_INVENTORY_OUTPUT,
    COMPONENTS_INVENTORY_OUTPUT,
    CONCEPTS_INDEX_OUTPUT,
    SURFACES_INDEX_OUTPUT,
    MAP_OUTPUT,
    CLI_REFERENCE_OUTPUT,
    CONFIGURATION_REFERENCE_OUTPUT,
    DIAGNOSTICS_REFERENCE_OUTPUT,
    MCP_REFERENCE_OUTPUT,
    STUDI0_REFERENCE_OUTPUT,
    PACKAGES_REFERENCE_OUTPUT,
    COMPONENT_INDEX_OUTPUT,
    DOCS_APPLICATION_OUTPUT,
    CORE_SLICE_OUTPUT,
    COVERAGE_REPORT_OUTPUT,
    QUICK_REFERENCE_OUTPUT,
    QUICK_REFERENCE_MACHINE_OUTPUT,
    # H1's manifest describes every artifact above it and is rendered
    # last for that reason; it stays last here too, so the declared order
    # and the render order tell one story.
    DOCS_MANIFEST_OUTPUT,
)


def generated_outputs(bundle: DocsBundle) -> tuple[str, ...]:
    """Every path this application writes for ``bundle``.

    The declared-output set: :func:`write` writes exactly these and
    :func:`check` compares exactly these, so neither can grow an output the
    other has not heard of.

    The decided half is :data:`STATIC_OUTPUTS` and the rest is
    computed, by two collections and for one reason.
    :func:`~s0ma_dsl.docs_model.learn_pages.learn_outputs` derives the
    learning collection from the concepts the composition actually holds
    and :func:`~s0ma_dsl.docs_model.render_media.media_outputs` derives
    H3's media packages from the journeys the catalog publishes — each by
    the same walk that renders them, so the set that is compared and the
    set that is written cannot disagree about what either collection
    contains.

    It takes a bundle rather than reading one for the reason every gate in
    this application takes its subject from its caller: a declared-output
    set that composed its own bundle could declare an output no build
    renders, and nothing would notice.
    """
    return (
        *STATIC_OUTPUTS,
        *learn_pages.learn_outputs(bundle),
        *render_media.media_outputs(bundle),
    )

#: The second authored concepts domain. C5a's language file has a named
#: constructor on the provider; C5b's product file does not, so its two
#: constants live here — with the composition that reads them — rather than
#: in a test, which is where they were until this milestone needed them.
PRODUCT_DOMAIN = "product"
PRODUCT_CONCEPTS = f"{CONCEPTS_DIR}/{PRODUCT_DOMAIN}.json"

#: The authored coverage policy (E8), repository-relative. Beside the
#: journeys and the concepts it is about, under ``docs/s0ma_src/``, because
#: it is the same kind of thing all three are: a file a person writes that
#: the build reads and cannot write back.
#:
#: It is **not** a provider's source, and that is deliberate. A provider
#: turns a source into records that enter the snapshot; this file produces
#: no record, changes no artifact byte, and exists only to be a gate's
#: caller-supplied policy — the shape ``check_floors`` and
#: ``check_side_effects`` already use, read from a file instead of written
#: in this module because nine capabilities and twenty-seven exceptions
#: with a paragraph on each is something an owner reviews, and a Python
#: constant is not where an owner reviews things.
COVERAGE_POLICY = f"{DOCS_ROOT}/s0ma_src/coverage-policy.json"


# ---------------------------------------------------------------------------
# Diagnostic names
# ---------------------------------------------------------------------------

#: A generated artifact differs from deterministic rendering (architecture
#: plan §11). Reported by :func:`check`, never by :func:`write`: writing is
#: how the drift is fixed, so a writer that reported it would report it
#: once and never again.
DOC_OUTPUT_DRIFT = "DOC_OUTPUT_DRIFT"

#: A gate resolved empty (architecture plan §11). Used here for the one
#: floor this module owns rather than delegates — :data:`ARTIFACT_FLOOR`.
DOC_GATE_VACUOUS = "DOC_GATE_VACUOUS"


# ---------------------------------------------------------------------------
# The floors this application asserts
# ---------------------------------------------------------------------------

#: Anti-vacuity floors for C5b's product concepts, in the shape
#: :func:`~s0ma_dsl.docs_model.validate.check_floors` reads. Honest
#: minimums under the live counts, for the reason every other floor in the
#: model is: a floor at the count fails the day somebody writes one more.
PRODUCT_FLOORS: Mapping[tuple[str, str], int] = {
    (f"concepts-{PRODUCT_DOMAIN}", "concepts"): 8,
    (f"concepts-{PRODUCT_DOMAIN}", "authorities"): 2,
}

#: Every provider's floor, merged. ``check_floors`` says the floors belong
#: to the caller and never to the model, and this application is that
#: caller: a floor naming a provider that did not run is itself a finding,
#: so this mapping doubles as the assertion that all eleven providers ran.
APPLICATION_FLOORS: Mapping[tuple[str, str], int] = {
    **dict(CORE_FLOORS),
    **dict(REPOSITORY_FLOORS),
    **dict(LANGUAGE_FLOORS),
    **dict(PRODUCT_FLOORS),
    **dict(CATALOG_FLOORS),
    **dict(CLI_FLOORS),
    **dict(DIAGNOSTIC_FLOORS),
    **dict(CONFIG_FLOORS),
    **dict(MCP_FLOORS),
    **dict(STUDI0_FLOORS),
    **dict(JOURNEY_FLOORS),
}

#: The build renders at least this many artifacts whatever it composed.
#: Exactly :data:`STATIC_OUTPUTS`, the half of the declared set that is
#: decided rather than derived — its length, so the floor moves when the
#: tuple does and never because somebody remembered to move it. It exists
#: for the reason every other floor
#: does: a render step that silently stopped producing would leave a check
#: gate comparing an empty set against an empty set and reporting success.
#:
#: The **exact** count is asserted too, and it has to be asserted where a
#: bundle is in hand: since F5 half the declared set is computed from the
#: composed concepts, so "how many artifacts should this build have
#: rendered" is a question about a particular build. :func:`_artifact_floor`
#: asks it that way; this constant is the part of the answer that holds
#: before anything has been composed, which is what a caller with no
#: bundle — a floor in a script, a smoke test — can still check against.
ARTIFACT_FLOOR = len(STATIC_OUTPUTS)


# ---------------------------------------------------------------------------
# The binding policy (D5b T2)
# ---------------------------------------------------------------------------

#: The two CLI binding classes that count as **bound**.
#:
#: ``handler-registered`` is uncontroversial: the callable the dispatch
#: reaches is itself a registered component.
#:
#: ``class-granular`` is the ruling. Twenty-two commands dispatch to a
#: method of ``S0maCLI``, which *is* registered; a method is not
#: separately registered because nothing registers methods. So the record
#: names the class — the finest granularity the registration offers — and
#: its exception names the method. That is a bound surface described at
#: an honest granularity, not an unbound one wearing a note: the
#: component exists, the model addresses it, and a reader following
#: ``component_refs`` arrives at code that really implements the command.
#: Counting it as unbound would say the opposite of what is true, and
#: would put twenty-two entries into a ledger meant to hold decisions
#: nobody has taken yet.
#:
#: What remains genuinely unbound is :data:`UNREGISTERED_HANDLERS`.
BOUND_CLASSES: frozenset[str] = frozenset({BOUND_DIRECTLY, BOUND_TO_OWNING_CLASS})

#: The commands whose handler is a module-level callable nothing
#: registers, exactly. Seven, and the exact list is the point: these are
#: the only served CLI surfaces that reach no component the model can
#: address, so they are the whole of what "the CLI is not fully bound"
#: means. Each carries a written exception naming the callable, which is
#: what architecture §6.3 asks for and what makes this a counted,
#: reviewable artifact rather than an ignore file.
#:
#: Registering them is a **product decision**, not a documentation one:
#: five of the seven are the feedback family, whose commands were written
#: as plain functions, and turning them into registered components changes
#: what the framework says about itself. D5b declines to take that
#: decision on the product's behalf and hands it to the F/G phases or the
#: owner with the list already made. Whoever takes it deletes entries
#: here; whoever adds an eighth unregistered handler has to add it here,
#: and the test that reads this constant is the review moment.
UNREGISTERED_HANDLERS: tuple[str, ...] = (
    "cli:s0ma/adopt/file",
    "cli:s0ma/feedback/delete",
    "cli:s0ma/feedback/drafts",
    "cli:s0ma/feedback/enroll",
    "cli:s0ma/feedback/list",
    "cli:s0ma/feedback/submit",
    "cli:s0ma/migrate/grammar",
)

#: The most surfaces this composition may leave reaching no component.
#:
#: One hundred and seventy today, in four groups of two kinds. The
#: thirty-six that are *decisions* — the seven above and core's
#: twenty-nine MCP and Python surfaces — are enumerated by id in
#: ``test_docs_binding_policy.py``, so any change to them fails a test
#: that names them. The remaining hundred and thirty-four are *rulings
#: about a source*: a diagnostic code is a label on a report and a
#: configuration key is a value in a table, and neither has an
#: implementing component by its nature rather than by anyone's
#: omission. Those grow when the product grows a diagnostic or a key.
#:
#: So the ceiling is a backstop and the enumeration is the gate. The
#: headroom under it (six today; two went to the retrofit draft's two
#: refusal codes, and three to the reports on a line the check could
#: not read and a test the runner would never run) lets an ordinary
#: code or key land without a red test; anything larger than ordinary
#: — a whole new unbound family — arrives through the enumerated list
#: first and is refused there by name.
UNBOUND_CEILING = 175

#: Which readings may leave ``side_effects`` empty, and why each cannot
#: answer. Handed to
#: :func:`~s0ma_dsl.docs_model.validate.check_side_effects`, which reads
#: an empty tuple as the unanswered question it is.
#:
#: All three are core's, and they are the asymmetry the plan flagged
#: rather than an exemption granted to it: **s0ma-mcp's tools declare
#: ``ToolAnnotations`` and core's do not**, so one provider reads
#: ``readOnlyHint`` off every tool and the other has nothing to read.
#: The gate does not paper over that. It records it, per source, with the
#: reason and what would close it — and an allowance no surface uses is a
#: ``DOC_GATE_VACUOUS`` finding, so the day core declares annotations
#: this permission stops matching and the build says so. That is the
#: difference between a written exception and a silent excuse: this one
#: expires by itself.
SIDE_EFFECT_ALLOWANCES: Mapping[tuple[str, str], str] = {
    ("core", "mcp_tool"): (
        "Core's MCP server registers its tools without ToolAnnotations, so "
        "its public listing carries no readOnlyHint and there is nothing to "
        "read. The authoring server's tools do declare them, and its "
        "provider reads every one — the silence is core's, not the "
        "protocol's. Closed by core declaring annotations on its tools, "
        "after which this allowance goes vacuous and has to be removed."
    ),
    ("core", "mcp_resource"): (
        "The protocol gives a resource no annotation at all: a listing "
        "carries its address, name and description and says nothing about "
        "what reading it does. Unlike the tools above, no amount of "
        "declaring on core's side changes that. Closed by the model "
        "learning to carry a hand classification for a resource the way "
        "core's REST reading already carries one for its POST route."
    ),
    ("core", "python"): (
        "A module-level export declares its effects nowhere a reading can "
        "reach — two of the nine are string constants, and the rest offer "
        "only a docstring, which is prose. Closed by the same move core's "
        "unsafe REST method already got: a person reads the nine and "
        "writes down what they found. That is a decision this milestone "
        "leaves to whoever owns core's public API rather than guessing at."
    ),
}


# ---------------------------------------------------------------------------
# The coverage policy (E8)
# ---------------------------------------------------------------------------

#: The most surfaces the coverage policy may excuse **one at a time** from
#: needing a journey.
#:
#: The ceiling counts only the per-surface ledger
#: because that is the one made of decisions — how many that ledger holds
#: today is in the authored file and in I2's coverage report, not written
#: here, because a count in a comment beside the number that bounds it is
#: two facts where one would do and only one of them is enforced. (It was
#: written here, said "twenty-two", and had been wrong since the ledger
#: and this ceiling were both raised by four.) The channel rulings are not
#: counted here for :data:`UNBOUND_CEILING`'s reason, said again about a
#: different ledger: a hundred and nine diagnostic codes are not a hundred
#: and nine decisions to leave something untaught, they are one ruling
#: about what a diagnostic is, and a budget over them would rise every
#: time the product grew a code and would mean nothing when it did.
#:
#: What the budget is for is the other direction. A surface the product
#: grows tomorrow is already refused by the completeness half of
#: :func:`~s0ma_dsl.docs_model.resolve.check_journey_coverage` until
#: somebody classifies it, and the cheapest classification is always the
#: ledger. Four of headroom lets a small family land while somebody thinks
#: about it; a whole new family of capabilities cannot arrive here quietly,
#: because the ceiling turns red first and the conversation is about
#: whether a journey should teach them.
REFERENCE_ONLY_CEILING = 30


def coverage_policy(root: Path) -> CoveragePolicy:
    """Read :data:`COVERAGE_POLICY` out of ``root``, refusing a bad file.

    The reading half of the gate, here rather than in
    :mod:`~s0ma_dsl.docs_model.resolve` because this is the module that
    knows where this repository keeps things — the same division
    :func:`registry` draws, where the machinery knows how to read a source
    and the application says which sources. ``resolve`` gets a value it
    can check and never a path it would have to find.

    A missing file, malformed JSON and a policy that does not satisfy its
    schema all raise
    :class:`~s0ma_dsl.docs_model.resolve.DocsResolveError`, which is a
    :class:`~s0ma_dsl.docs_model.records.DocsModelError` — so a build with
    no readable policy does not compose at all. That is the C5a line and
    it matters more here than anywhere: a coverage gate that fell back to
    an empty policy would require a journey of nothing and excuse
    everything, silently.
    """
    import json

    target = root.joinpath(*COVERAGE_POLICY.split("/"))
    if not target.is_file():
        raise DocsResolveError(
            f"{COVERAGE_POLICY} is not there. The documentation application "
            f"reads its coverage policy from that file, and without it "
            f"nothing has said which capabilities a journey has to teach."
        )
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DocsResolveError(f"{COVERAGE_POLICY} is not valid JSON: {exc}") from exc
    return coverage_policy_from_mapping(raw, source=COVERAGE_POLICY)


#: This repository's anti-vacuity minimum per coverage set (I2).
#:
#: Honest minimums well under the live counts, for the reason every other
#: floor in this application is: a floor at the count fails the day
#: somebody writes one more concept. What they defend against is the one
#: way a coverage report can lie without any number in it being wrong —
#: a reading that stopped producing leaves a small required set, every
#: member of which is covered, and the report says complete.
#:
#: They are stated here and not in the renderer because they are a claim
#: about *this* product. A caller composing a fixture's records passes
#: none and gets an honest report of a small corpus, exactly as
#: :func:`~s0ma_dsl.docs_model.validate.check_floors` allows.
COVERAGE_FLOORS: Mapping[str, int] = {
    "catalog": 100,
    "concepts": 20,
    "discovery": 14,
    "journeys": 8,
    "surfaces": 100,
}


# ---------------------------------------------------------------------------
# The discovery contract (I2, over F9)
# ---------------------------------------------------------------------------

#: Every guaranteed route by which somebody finds out this documentation
#: exists: architecture §9.3's seven for a person, §9.6's seven for an
#: agent, each named with the suite that proves it still resolves.
#:
#: **Why this is a declared ledger and not a derivation.** Every other
#: coverage set in this application is measured from records the build
#: composed. These routes are not records — they are properties of the
#: *running product's output*, which is exactly why F9 put their gate in
#: two contract suites rather than in ``validate`` (a build-time
#: validator has no server, no argparse tree and no scaffolded project in
#: front of it). So the report cannot measure them, and the honest thing
#: is to say which routes the contract has and where each one is proven,
#: rather than to compute a number that would mean nothing.
#:
#: **What keeps it honest.** The routes and the ``proof`` names are held
#: against the two suites' own registries by
#: ``test_docs_negative_inventory.py``, which reads
#: ``HUMAN_ENTRY_POINTS`` and ``AGENT_ENTRY_POINTS`` out of their source
#: rather than importing them, and against the architecture plan's own
#: numbered lists. A route added to either contract, or a proving class
#: renamed away, turns that test red with the route named — which is the
#: only thing that stops a contract shrinking quietly. The two suites
#: each check their own seven and neither can see the other; this ledger
#: is the first place both halves are written down together.
DISCOVERY_CONTRACT: tuple[DiscoveryEdge, ...] = (
    *(
        DiscoveryEdge(
            id=f"human-{index}",
            audience="human",
            clause=f"architecture §9.3.{index}",
            route=route,
            proof=f"s0ma-dsl tests/test_docs_discovery_contract.py::{owner}",
        )
        for index, (route, owner) in enumerate(
            (
                ("root README has one Start-here route", "TestRootReadmeRoute"),
                ("--help advertises learning", "TestHelpAdvertisesLearning"),
                ("bare `s0ma docs` navigates", "TestBareDocsNavigates"),
                ("setup results name a next step", "TestSetupResultsNameANextStep"),
                (
                    "diagnostics point at their topic",
                    "TestDiagnosticsPointAtTheirTopic",
                ),
                (
                    "generated instructions name both routes",
                    "TestGeneratedInstructions",
                ),
                (
                    "installed bundles need no checkout",
                    "TestInstalledBundlesNeedNoCheckout",
                ),
            ),
            start=1,
        )
    ),
    *(
        DiscoveryEdge(
            id=f"agent-{index}",
            audience="agent",
            clause=f"architecture §9.6.{index}",
            route=route,
            proof=f"s0ma-mcp tests/test_docs_discovery_mcp.py::{owner}",
        )
        for index, (route, owner) in enumerate(
            (
                (
                    "server instructions name the query and index",
                    "TestInstructionsNameTheQuery",
                ),
                (
                    "tool descriptions say when to consult",
                    "TestToolDescriptionsSayWhen",
                ),
                (
                    "high-traffic results carry a pointer",
                    "TestHighTrafficResultsCarryAPointer",
                ),
                ("failing diagnostics deep-link", "TestFailingDiagnosticsDeepLink"),
                (
                    "prompts name their dependencies",
                    "TestPromptsNameTheirDependencies",
                ),
                ("generated AGENTS.md establishes both", "TestGeneratedAgentsMd"),
                (
                    "the index describes its own retrieval",
                    "TestTheIndexDescribesItself",
                ),
            ),
            start=1,
        )
    ),
)


# ---------------------------------------------------------------------------
# What a build is
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Artifact:
    """One rendered output: where it goes, and what it says.

    ``relative`` is forward-slashed and relative to the documentation root
    (ADR-012 §2.3 rule B-3), so the same build describes the same artifact
    on every platform and no machine path can reach a rendered byte.
    """

    relative: str
    content: str

    def path(self, base: Path) -> Path:
        """This artifact's place under ``base``."""
        return base.joinpath(*self.relative.split("/"))


@dataclass(frozen=True)
class Build:
    """One composed snapshot, what it renders to, and what is wrong with it.

    The findings are collected rather than raised, and they are collected
    from every gate rather than up to the first failing one: an author
    fixing documentation should see the whole report, not one line per run
    (ADR-012 §4, charter item 7).
    """

    bundle: DocsBundle
    artifacts: tuple[Artifact, ...]
    findings: tuple[Finding, ...]

    @property
    def ok(self) -> bool:
        """True when every gate this application runs found nothing."""
        return not self.findings

    def artifact(self, relative: str) -> Artifact:
        """The artifact at ``relative``, refusing one this build never made."""
        for item in self.artifacts:
            if item.relative == relative:
                return item
        raise DocsModelError(f"this build renders nothing at {relative!r}")


# ---------------------------------------------------------------------------
# The composition
# ---------------------------------------------------------------------------


def release_version() -> str:
    """The version this build stamps its snapshot with.

    The installed ``s0ma-dsl`` version, because the model, the providers
    and the renderers all ship in that wheel: a snapshot claims to have
    been composed by a particular toolchain, and this is that toolchain's
    name for itself. Read at call time rather than at import so a caller
    that pins a version does not have to reload this module.
    """
    from s0ma_dsl import __version__

    return __version__


def registry(root: Path) -> ProviderRegistry:
    """The eleven providers this repository's documentation is composed from.

    This tuple *is* the application (ADR-012 §1): the reusable machinery
    knows how to read a source, and this is the only place that says which
    sources. Registration order is recorded for readability and reaches
    nothing — :func:`~s0ma_dsl.docs_model.compose.compose` sorts every
    group before the bundle is built, and the suite proves the bytes are
    the same backwards, over all eleven.

    Five readings arrived with the C phase and describe what the product
    *says*: what the framework registers about itself, what the
    repository's governing documents say, two files of authored teaching
    vocabulary, and the catalog of every document that exists. Five
    arrived with the D phase and describe what the product *serves*: the
    command line, the diagnostics it can emit, the keys it can be
    configured with, the authoring MCP server, and the studi0 viewer.

    ``CoreProvider`` and ``CliProvider`` take no root: each boots or
    builds the thing it reads — a component registry, an argparse tree —
    which is what ADR-012 §3's "every build boots its own registry" means
    in practice. The other eight read files under ``root``.
    """
    return ProviderRegistry.of(
        CoreProvider(),
        RepoProvider(root=root),
        ConceptsProvider.language(root),
        ConceptsProvider(root=root, relative=PRODUCT_CONCEPTS, domain=PRODUCT_DOMAIN),
        CatalogProvider(root=root),
        CliProvider(),
        DiagnosticsProvider(root=root),
        ConfigProvider(root=root),
        McpProvider(root=root),
        Studi0Provider(root=root),
        JourneysProvider(root=root),
    )


def gate_modules() -> tuple[ModuleType, ...]:
    """Which modules hold this application's gates (I1).

    The same kind of statement :func:`registry` is, about the other half
    of the build: that function is the only place that says which sources
    are read, and this is the only place that says where the gates that
    judge them live. Neither names the individual things — a registry that
    listed records, or a battery that listed gates, would be the
    independently maintained inventory architecture §8.2 forbids.
    :func:`~s0ma_dsl.docs_model.self_description.gate_facts` finds the
    gates inside these modules, so a gate added to one of them is a gate
    the self-description reports without anybody editing a list.

    ``sys.modules`` rather than an import for this module's own entry:
    :func:`check_surface_index` is a gate and lives here, and a module
    cannot import itself. It is resolved at call time, by which point this
    module is fully initialized.

    The suite proves the tuple is complete — ``test_docs_self_description``
    walks every module of the package and refuses a gate outside it — for
    the reason ``check_surface_index`` takes its index as text: a
    completeness claim checked against the thing that made it passes by
    construction and proves nothing.
    """
    import sys

    from s0ma_dsl.docs_model import (
        evidence,
        providers_catalog,
        providers_concepts,
        providers_journeys,
        render_agent,
        resolve,
        validate,
    )

    return (
        sys.modules[__name__],
        evidence,
        providers_catalog,
        providers_concepts,
        providers_journeys,
        quick_reference,
        render_agent,
        resolve,
        validate,
    )


def _artifacts(
    bundle: DocsBundle,
    root: Path,
    component_ids: Sequence[str],
    *,
    rows: Sequence[CatalogRow],
    exclusions: Sequence[Exclusion],
    interfaces: Sequence[CommandInterface],
    modes: Sequence[str],
    mirrors: Sequence[MirrorDocument],
    aliases: AliasIndex,
    results: Sequence[ProviderResult],
    policy: CoveragePolicy,
    coverage_floors: Mapping[str, int],
    quick_words: Mapping[str, Any] | DocsModelError,
) -> tuple[tuple[Artifact, ...], list[Finding]]:
    """Every artifact this build renders, in memory (phase 9).

    Exactly :func:`generated_outputs`, in its order: the decided ones,
    one page per concept the composition holds, and one
    media package per journey its catalog publishes. How many that is, is
    a question about a particular build and is answered by
    :func:`_artifact_floor` rather than written here. Nothing
    is post-processed on the way out:
    :func:`~s0ma_dsl.docs_model.serialize.serialize_bundle` and
    :func:`~s0ma_dsl.docs_model.serialize.canonical_json` already sort
    every key and already end with exactly one line feed, and a second
    opinion about the trailing byte here is how an artifact grows one the
    model does not know about. Every Markdown page is joined from lines
    and gets its single trailing newline the same way, once, in the module
    that renders it.

    ``root`` reaches this function for three reasons: the component facts
    of the two transpiled packages are read from their committed canonical
    IR rather than by importing them, F4's packages page reads each
    distribution's license and one-line description off the same
    ``pyproject.toml`` its version already comes from, and I1's
    self-description reads this application's *own* committed IR
    (:data:`APPLICATION_IR`) for the same reason the first does — the
    documentation application is written in s0ma, and reading what it
    registers beats importing and running it. A file has to be found to be
    read. Nothing else here touches the filesystem, and nothing here
    writes.

    Everything else arrives from the caller, and all of it for one reason,
    which is C6's: **one reading of one source**. ``rows`` and
    ``exclusions`` are the catalog's two answers the bundle has nowhere to
    carry — what kind of document a row is and who it is for, and which
    tracked files are deliberately not documents. ``interfaces`` is the
    argparse tree
    :class:`~s0ma_dsl.docs_model.providers_cli.CliProvider` already built,
    ``modes`` the strictness ladder
    :class:`~s0ma_dsl.docs_model.providers_diagnostics.DiagnosticsProvider`
    already read, ``mirrors`` the resource-to-document correspondence
    :class:`~s0ma_dsl.docs_model.providers_mcp.McpProvider` already
    resolved, and ``aliases`` the alternate terms the two concept
    providers already declare. A renderer that re-read any of them could
    describe a source nobody composed.

    ``results`` is H1's addition and arrives for the same reason: the
    manifest states which schema version each adapter emitted against and
    which sources this build read with which digests, and both facts live
    on the provenance of records the providers already handed over. A
    manifest that re-derived them would be a second reading of the one
    thing the whole model exists to keep singular.

    ``quick_words`` is the quick reference's authored file as
    :func:`build` read it — or the refusal reading it ended in, which the
    two renderings then report as their own. It arrives rather than being
    read here because the voice gate has already read it, and one file
    read twice is two chances to describe different bytes.

    **A renderer that refuses is reported, not raised** — see
    :func:`_refused`. Phase 9 is inside the collect-everything contract
    that ADR-012 §4 states and :func:`build` keeps, and a caller composing
    a smaller provider set is supported, so an artifact whose renderer had
    nothing honest to say leaves a finding and no artifact rather than
    ending the run at the first one. The build is then short of its
    declared set, which :func:`_artifact_floor` reports in the same breath
    — so the refusal says *why* and the floor says *that*, and nothing
    incomplete is ever written.
    """
    facts, readings = component_facts(root, component_ids)
    packages = [(item.distribution, item.version) for item in package_facts(root)]
    rendered: dict[str, str] = {}
    refusals: list[Finding] = []

    def keep(relative: str, render: Callable[[], str]) -> None:
        try:
            rendered[relative] = render()
        except DocsModelError as error:
            refusals.append(_refused(relative, error))

    keep(SNAPSHOT_OUTPUT, lambda: serialize_bundle(bundle))
    keep(CONCEPTS_INVENTORY_OUTPUT, lambda: concepts_inventory(bundle))
    keep(SURFACES_INVENTORY_OUTPUT, lambda: surfaces_inventory(bundle))
    keep(
        COMPONENTS_INVENTORY_OUTPUT,
        lambda: components_inventory(bundle, facts, readings),
    )
    keep(CONCEPTS_INDEX_OUTPUT, lambda: concepts_index(bundle))
    keep(SURFACES_INDEX_OUTPUT, lambda: surfaces_index(bundle))
    keep(
        MAP_OUTPUT,
        lambda: map_of_record(
            bundle, rows=rows, exclusions=exclusions, docs_root=DOCS_ROOT
        ),
    )
    keep(CLI_REFERENCE_OUTPUT, lambda: cli_reference(bundle, interfaces=interfaces))
    keep(CONFIGURATION_REFERENCE_OUTPUT, lambda: configuration_reference(bundle))
    keep(
        DIAGNOSTICS_REFERENCE_OUTPUT,
        lambda: diagnostics_reference(bundle, modes=modes),
    )
    keep(
        MCP_REFERENCE_OUTPUT,
        lambda: mcp_reference(
            bundle,
            mirrors=mirrors,
            page=MCP_REFERENCE_OUTPUT,
            docs_root=DOCS_ROOT,
        ),
    )
    keep(
        STUDI0_REFERENCE_OUTPUT,
        lambda: studi0_reference(
            bundle, page=STUDI0_REFERENCE_OUTPUT, docs_root=DOCS_ROOT
        ),
    )
    keep(
        PACKAGES_REFERENCE_OUTPUT,
        lambda: packages_reference(
            bundle,
            distributions=distribution_facts(root),
            components=facts,
            page=PACKAGES_REFERENCE_OUTPUT,
            docs_root=DOCS_ROOT,
        ),
    )
    keep(
        COMPONENT_INDEX_OUTPUT,
        lambda: component_index(
            bundle,
            components=facts,
            page=COMPONENT_INDEX_OUTPUT,
            docs_root=DOCS_ROOT,
        ),
    )
    # I2, and architecture §11.1 turned from a claim into an artifact:
    # what this build covers, and every standing exception by name. The
    # policy, the two ceilings and the discovery contract arrive as values
    # for the reason every gate's floors do — a report that fetched its
    # own ceiling could raise one. ``learn_outputs`` is the learning
    # collection's own walk rather than the concepts group, so the concept
    # measure is a second reading and not the required set counted twice.
    #
    # Measured here, above both artifacts that state it, because two
    # renderers doing their own arithmetic could disagree about one build.
    # A measurement that refused leaves an empty tuple and no finding of
    # its own: each of the two artifacts below refuses on its own behalf,
    # which puts the refusal on the path a reader would go looking at.
    try:
        measured = coverage_sets(
            bundle,
            policy=policy,
            pages=learn_pages.learn_outputs(bundle),
            exclusions=exclusions,
            discovery=DISCOVERY_CONTRACT,
            unbound_ceiling=UNBOUND_CEILING,
            reference_only_ceiling=REFERENCE_ONLY_CEILING,
            floors=coverage_floors,
        )
    except DocsModelError:
        measured = ()
    # I1, and architecture §15's M7 acceptance: the one page whose subject
    # is this application. ``results`` and ``bundle`` are the composition
    # it is describing, the gates are found in the modules this
    # application says hold them, and its own registrations are read from
    # the canonical IR its own build committed — the third filesystem read
    # this function makes, and the last.
    keep(
        DOCS_APPLICATION_OUTPUT,
        lambda: docs_application(
            bundle,
            results=results,
            gates=gate_facts(gate_modules()),
            module=application_module(root, relative=APPLICATION_IR),
            outputs=generated_outputs(bundle),
            decided=STATIC_OUTPUTS,
            packaged=frozenset({CORE_SLICE_OUTPUT}),
            media=frozenset(render_media.media_outputs(bundle)),
            # I2. The same derivation the report renders, handed over
            # once rather than measured twice: the page and the artifact
            # disagreeing about what this build covers is the exact
            # failure a self-description exists to make impossible.
            coverage=measured,
            page=DOCS_APPLICATION_OUTPUT,
            docs_root=DOCS_ROOT,
        ),
    )
    keep(
        COVERAGE_REPORT_OUTPUT,
        lambda: render_coverage(
            bundle, sets=measured, discovery=DISCOVERY_CONTRACT
        ),
    )
    # The quick reference, composed once and rendered twice: the page and
    # the data are two renderings of one value, so a fact is on both or on
    # neither. A composition that refused hands back two renderings that
    # raise it, which puts the reason on each output that was not written.
    readable, machine = quick_reference.compose(
        bundle,
        quick_words,
        interfaces=interfaces,
        modes=modes,
        packages=packages,
        docs_root=DOCS_ROOT,
    )
    keep(QUICK_REFERENCE_OUTPUT, readable)
    keep(QUICK_REFERENCE_MACHINE_OUTPUT, machine)
    # F8. The one artifact rendered for a reader in another distribution:
    # the aliases reach it for the same reason the learning collection gets
    # them, which is that an alternate name a reader arrives holding has to
    # resolve on every channel and not only on the page.
    keep(CORE_SLICE_OUTPUT, lambda: core_teaching_slice(bundle, aliases=aliases))
    # The collection is one call for all of its pages, because one walk of
    # the concepts is what keeps two pages from disagreeing about what the
    # collection contains — so it refuses as one thing too.
    try:
        rendered.update(learn_pages.learn_pages(bundle, aliases=aliases))
    except DocsModelError as error:
        refusals.append(_refused(f"{learn_pages.LEARN_DIR}/", error))

    # H3. The second computed collection, and one call for the same reason
    # the first is: one walk of the approved journeys is what keeps two
    # packages from disagreeing about which journeys the catalog publishes.
    # ``rows`` reaches it because a package states the title and audience of
    # the document that publishes its journey, and the catalog's
    # presentation half is the one reading of those this build makes.
    try:
        rendered.update(render_media.media_packages(bundle, rows=rows))
    except DocsModelError as error:
        refusals.append(_refused(f"{render_media.MEDIA_DIR}/", error))

    # H1, and deliberately last: the manifest describes every other
    # artifact this build rendered, so it is the one output that has to
    # wait for the rest. It does not describe itself — a content hash of
    # bytes containing that hash has no fixed point — and what covers it
    # instead is the byte gate over the committed file, which is the same
    # gate that covers everything it lists.
    keep(
        DOCS_MANIFEST_OUTPUT,
        lambda: render_manifest(
            manifest_of(
                bundle,
                results=results,
                packages=packages,
                artifacts=sorted(rendered.items()),
                docs_root=DOCS_ROOT,
                packaged=frozenset({CORE_SLICE_OUTPUT}),
                media=frozenset(render_media.media_outputs(bundle)),
            )
        ),
    )

    return (
        tuple(
            Artifact(relative=relative, content=rendered[relative])
            for relative in generated_outputs(bundle)
            if relative in rendered
        ),
        refusals,
    )


def _refused(relative: str, error: DocsModelError) -> Finding:
    """One renderer declined to render, said in the report rather than raised.

    ``DOC_GATE_VACUOUS`` because that is what every one of these is: a
    renderer handed nothing to describe, refusing to commit a page of
    empty tables that would read as a product that has stopped serving
    something. The renderers state their own reason and it is quoted
    whole — they know which reading came back empty and this function
    does not.
    """
    return Finding(
        code=DOC_GATE_VACUOUS,
        location=f"{DOCS_ROOT}/{relative}",
        message=f"{relative} was not rendered: {error}",
        remediation=(
            "A declared output whose renderer refused is a reading that "
            "stopped working, not a page to write by hand. The renderer says "
            "which one above; check that its provider ran and is still "
            "producing before changing anything here."
        ),
    )


def _artifact_floor(
    artifacts: tuple[Artifact, ...], bundle: DocsBundle
) -> list[Finding]:
    """The render step produced everything it declared (``DOC_GATE_VACUOUS``).

    Exact rather than honestly low, and the only floor in this application
    that is: the artifacts are *declared* rather than discovered, so "at
    least as many as this build declared" is the only floor over them that
    means anything. Since F5 half the declaration is computed from the
    composed concepts, which is why the bundle is here.
    """
    expected = len(generated_outputs(bundle))
    if len(artifacts) >= expected:
        return []
    return [
        Finding(
            code=DOC_GATE_VACUOUS,
            location=DOCS_ROOT,
            message=(
                f"this build rendered {len(artifacts)} artifacts and at least "
                f"{expected} was expected"
            ),
            remediation=(
                "A build that renders nothing passes every byte comparison "
                "downstream of it, because there are no bytes to compare. "
                "Either a renderer has stopped producing, or the floor is "
                "stale — check the renderer first."
            ),
        )
    ]


def _check_manifest_artifact(
    artifacts: tuple[Artifact, ...], bundle: DocsBundle
) -> list[Finding]:
    """The rendered manifest describes one build of one version (H1).

    ``DOC_VERSION_MISMATCH``, via
    :func:`~s0ma_dsl.docs_model.validate.check_manifest`. The document is
    parsed back out of the bytes that were just rendered rather than passed
    across as an object, for the reason
    :func:`check_surface_index` takes the index as text: a gate handed the
    value its subject was built from passes by construction, and this one
    is supposed to be able to catch a manifest that does not round-trip.

    A build whose manifest renderer refused has nothing here to check, and
    saying so with an exception would replace a reported refusal with a
    crash and lose every gate after it.
    """
    document = next(
        (item.content for item in artifacts if item.relative == DOCS_MANIFEST_OUTPUT),
        None,
    )
    if document is None:
        return []
    return check_manifest(
        manifest_from_json(document),
        stamp=bundle.stamp,
        location=f"{DOCS_ROOT}/{DOCS_MANIFEST_OUTPUT}",
    )


def check_surface_index(bundle: DocsBundle, *, index: str) -> list[Finding]:
    """Every served capability appears in the rendered index of them.

    ``DOC_SURFACE_UNCOVERED``, v1 (plan §9 D6 T2, architecture §11). The
    coverage gate in :func:`~s0ma_dsl.docs_model.resolve.check_coverage`
    asks whether a surface can be *resolved and rendered on a reader
    channel*; this one asks the narrower, blunter question the plan named:
    is it in the reference this build commits. Both are needed — a
    capability that renders on demand and appears in no index is one nobody
    finds, and a capability listed in an index that no channel can render
    is a line of text.

    **The index arrives as text rather than being rendered here**, for the
    reason :func:`~s0ma_dsl.docs_model.validate.check_floors` takes its
    floors from its caller and :func:`check_coverage` takes its renderers:
    a gate that produced the thing it checks would pass by construction and
    prove nothing. In this build the caller passes the rendered artifact,
    so the gate reads what will actually be committed.

    What it can catch today, honestly stated: a renderer that drops a
    channel, a grouping that loses a family, a truncated or partially
    written page. What it cannot yet catch is a *surface with no reference
    entry of its own* — the index lists every one, so the requirement is
    met by construction until F3/F4 author per-family reference pages and
    the index stops being the whole answer. That is the deepening the plan
    schedules, not a hole this milestone leaves open.
    """
    findings: list[Finding] = []
    for record in sorted(bundle.surfaces, key=lambda item: item.id):
        if record.id in index:
            continue
        findings.append(
            Finding(
                code=DOC_SURFACE_UNCOVERED,
                location=f"{DOCS_ROOT}/{SURFACES_INDEX_OUTPUT}",
                message=(
                    f"{record.id} is a served capability this build composed "
                    f"and the generated index of served capabilities does not "
                    f"list it"
                ),
                remediation=(
                    "Every capability s0ma serves has to be findable in the "
                    "reference this build commits, or it is a capability "
                    "nobody can be told about. Either the index renderer is "
                    "dropping it — check that its channel is rendered — or "
                    "the record is one this build should not have composed."
                ),
            )
        )
    return findings


def build(
    root: Path,
    *,
    version: str | None = None,
    head_tag: str = "",
    providers: ProviderRegistry | None = None,
    floors: Mapping[tuple[str, str], int] | None = None,
    allowances: Mapping[tuple[str, str], str] | None = None,
    evidence: EvidenceLibrary | None = None,
    coverage: CoveragePolicy | None = None,
) -> Build:
    """Compose, validate, and render this repository's documentation.

    Phases 1–9 of architecture plan §10.1, in order, collecting rather
    than stopping. Nothing here reads or writes a rendered file: the
    result is a bundle and the bytes it renders to, and what the caller
    does with those is :func:`write`'s business or :func:`check`'s.

    ``providers``, ``floors`` and ``allowances`` default to
    :func:`registry`, :data:`APPLICATION_FLOORS` and
    :data:`SIDE_EFFECT_ALLOWANCES`, which together *are* this
    repository's documentation. They are parameters rather than constants
    for the reason ADR-012 §1 gives for shipping the machinery in the
    s0ma-dsl wheel at all — "the documentation application is the first
    consumer of the machinery, not its owner" — and because a gate wiring
    nothing can reach from outside is a gate nothing can prove.

    Every provider-specific gate below is reached by asking the registry
    what it holds rather than by naming the eleven providers again. A
    registry missing one of them is not silently under-gated: a floor
    naming a provider that did not run is itself a
    ``DOC_GATE_VACUOUS`` finding, so the floors are what make the
    provider-shaped gates non-optional. An allowance nothing uses is the
    same finding for the same reason.

    ``evidence`` is the fourth override and the newest (E2). It defaults
    to the fixtures committed under
    :data:`~s0ma_dsl.docs_model.evidence.EVIDENCE_DIR`, and it is **read,
    never run**: handing a resolver over is what arms
    ``DOC_JOURNEY_UNTESTED``, and what the resolver can answer offline is
    whether a journey's evidence exists in this tree and names the
    journey back. Replaying it starts processes, which SDA-INV-8 keeps
    out of this build — so a fixture that has stopped describing the
    product is the suite's finding, and a journey with no evidence at all
    is this build's.

    ``coverage`` is the fifth (E8), and it defaults to the policy authored
    at :data:`COVERAGE_POLICY`. It is the caller's for the same reason the
    floors are: which capabilities a product is *for* is a fact about that
    product, and a default written into the machinery would be a claim
    about somebody else's. Unlike ``evidence``, there is no seam that can
    turn it off — an unreadable policy refuses the build rather than
    quieting the gate, because a coverage policy that can be absent is a
    coverage policy that excuses everything.

    ``version`` overrides the stamped release version. It exists for the
    suite, which needs two builds of one tree to be comparable across a
    version bump, and for nothing else.

    ``head_tag`` is the tag the built commit is *exactly* at, as a value
    (H2b). It is the one input this build takes about the world outside
    the sources, and it is taken rather than looked up: nothing here runs
    ``git``, so a build cannot promote itself to a release by standing
    somewhere. Empty — the default, and every build nobody told — composes
    the ``preview`` channel exactly as it did before this parameter
    existed. The whole rule is
    :func:`~s0ma_dsl.docs_model.manifest.channel_of`, applied here once, so
    a tag naming some other version composes a preview rather than a
    release nobody cut.
    """
    known = providers if providers is not None else registry(root)
    library = evidence if evidence is not None else EvidenceLibrary.load(root)
    policy = coverage if coverage is not None else coverage_policy(root)

    # Phases 2-4: every provider reads its own source, and the merge is the
    # only place they meet.
    stamped_version = version or release_version()
    composed = compose(
        known,
        release_version=stamped_version,
        build_channel=channel_of(
            product_version=stamped_version, head_tag=head_tag
        ),
    )
    bundle = composed.bundle

    findings: list[Finding] = list(composed.findings)

    # What each provider knows that a ProviderResult has nowhere to carry:
    # the authored file's own complaints, the alternate terms it declares,
    # and the ids it cites but expects somebody else to emit.
    catalogs: list[CatalogProvider] = []
    commands: list[CliProvider] = []
    registries: list[DiagnosticsProvider] = []
    servers: list[McpProvider] = []
    alias_pairs: list[tuple[str, str]] = []
    external: set[str] = set()
    for provider in known.providers():
        if isinstance(provider, ConceptsProvider | CatalogProvider | JourneysProvider):
            findings.extend(provider.findings())
        if isinstance(provider, ConceptsProvider):
            alias_pairs.extend(provider.alias_index().entries)
        # Six readings vouch for ids they do not hold — registered
        # components, mostly. Every one of them is asked, and the union is
        # what the resolver checks against: a surface of the dsl's own CLI
        # binds to a dsl component, which core's inventory has never heard
        # of, so a build that asked only core would report seventy-one
        # honest bindings as unresolved.
        if isinstance(
            provider,
            ConceptsProvider | CoreProvider | CliProvider | McpProvider | Studi0Provider,
        ):
            external.update(provider.external_ids())
        if isinstance(provider, CatalogProvider):
            catalogs.append(provider)
        # Three more readings hold something a ProviderResult has nowhere
        # to carry and phase 9 needs: the argparse tree behind the command
        # records, the strictness ladder the diagnostic severities are
        # laddered over, and which served resources are packaged copies of
        # which documents. Collected the same way the catalog is, so a
        # registry without one of them renders a page that says so rather
        # than a page that guesses.
        if isinstance(provider, CliProvider):
            commands.append(provider)
        if isinstance(provider, DiagnosticsProvider):
            registries.append(provider)
        if isinstance(provider, McpProvider):
            servers.append(provider)

    # Phase 8, before phase 5 asks about it: a transcript fixture is
    # registered runnable evidence and lives outside the documentation
    # model, exactly like a registered component, so the resolver is told
    # about it rather than asked to find it.
    external.update(library.ids())

    # Phases 5-6: every edge resolves, no record contradicts itself, every
    # served surface says what calling it does, and no provider quietly
    # stopped producing.
    findings.extend(
        validate_bundle(
            bundle,
            results=composed.results,
            external_ids=sorted(external),
            floors=APPLICATION_FLOORS if floors is None else floors,
            allowances=SIDE_EFFECT_ALLOWANCES if allowances is None else allowances,
            evidence_resolver=library.resolver(),
        )
    )
    findings.extend(library.findings(bundle))
    for record in library.records:
        findings.extend(check_evidence_voice(record))

    # The quick reference's authored words, read once. A file that cannot
    # be read is not a finding here: it is kept, and the two outputs that
    # could not be rendered from it each say so in phase 9 — which is
    # where a caller composing over a fixture directory meets it, located
    # at the pages rather than at the top of the run.
    quick_words: Mapping[str, Any] | DocsModelError
    try:
        quick_words = quick_reference_source(root)
    except DocsModelError as error:
        quick_words = error
    else:
        findings.extend(check_quick_reference_voice(quick_words))

    # Phase 1's remainder, over the composed catalog rather than over the
    # file: a derived row colliding with an authored one is only visible
    # here.
    for catalog in catalogs:
        findings.extend(check_completeness(catalog, tracked_markdown(root)))
    findings.extend(check_canonical_sources(bundle.documents))
    findings.extend(check_document_authorities(bundle))

    # The alternate terms every concept file declares, indexed once. Three
    # things need them and they must be the same three answers: the
    # coverage gate resolves an old name onto the topic that replaced it,
    # the learning collection's glossary lists those old names for a reader
    # who arrives holding one, and — since F9 — the snapshot itself carries
    # them, so a wheel and the MCP server's packaged copy answer to the
    # same alternate terms a checkout does. That last one is why the pairs
    # go onto the bundle here rather than staying a build-local value: a
    # reading that only exists while the composer is running is a reading
    # no installed toolchain ever gets.
    aliases = AliasIndex.of(alias_pairs)
    bundle = replace(
        bundle,
        aliases=tuple(
            AliasEntry(id=old, canonical=new) for old, new in aliases.entries
        ),
    )

    # Phase 7. Coverage is asked over the real reader channels and over the
    # index this build actually serves, which is what stops it passing by
    # having nothing to look at.
    findings.extend(
        check_coverage(
            bundle,
            renderers={"human": render_human, "agent": render_agent},
            index=TopicIndex.of(bundle, aliases),
        )
    )
    findings.extend(check_concept_relations(bundle))

    # Phase 7's other half (E8). check_coverage asks whether a topic can be
    # *shown*; this asks whether a capability is *taught*, which is the row
    # of architecture §11.1 that a rendered page can satisfy and a reader
    # still be left with no path through it.
    findings.extend(check_journey_coverage(bundle, policy))

    # Phase 9. The component ids come from the same external-id seam the
    # reference resolver was handed above, so the inventory describes
    # exactly what this build can point at — not what some registry in this
    # process happens to hold. The catalog's own two extra answers come
    # from the providers collected above rather than from a second reading
    # of the file: the map of record has to say what kind of document a
    # row is and which tracked files are not documents at all, and neither
    # is a fact a DocumentRecord carries.
    artifacts, refusals = _artifacts(
        bundle,
        root,
        sorted(external),
        rows=[row for catalog in catalogs for row in catalog.rows()],
        exclusions=[item for catalog in catalogs for item in catalog.exclusions()],
        interfaces=[item for provider in commands for item in provider.interface()],
        modes=next((provider.modes() for provider in registries), ()),
        mirrors=[
            item for provider in servers for item in provider.mirrored_documents()
        ],
        aliases=aliases,
        results=composed.results,
        policy=policy,
        # I2's anti-vacuity minimums ride the same seam the provider
        # floors do, and for the same reason: a caller that brought its
        # own providers brought its own idea of how much there should be,
        # and this repository's minimums over somebody else's composition
        # would refuse a build that is exactly as large as it meant to be.
        coverage_floors=COVERAGE_FLOORS if floors is None else {},
        quick_words=quick_words,
    )
    findings.extend(refusals)
    findings.extend(_artifact_floor(artifacts, bundle))
    # H1. The manifest is read back out of what was just rendered rather
    # than built a second time here, so the gate reads the exact document
    # that will be committed. A build whose manifest renderer refused has
    # no manifest to check, and that refusal is already a finding above.
    findings.extend(_check_manifest_artifact(artifacts, bundle))
    # The index is handed over rather than rendered here, so a build whose
    # index renderer refused has no index to ask about — and that refusal
    # is already a finding above. Asking anyway would replace it with an
    # exception and lose every gate after this one.
    served = next(
        (
            item.content
            for item in artifacts
            if item.relative == SURFACES_INDEX_OUTPUT
        ),
        None,
    )
    if served is not None:
        findings.extend(check_surface_index(bundle, index=served))

    return Build(bundle=bundle, artifacts=artifacts, findings=sort_findings(findings))


# ---------------------------------------------------------------------------
# Phase 10 — the only two functions that know about files
# ---------------------------------------------------------------------------


def write(result: Build, base: Path) -> tuple[Path, ...]:
    """Update every declared output under ``base``. Returns what was written.

    Writes with an explicit ``newline="\\n"`` so a Windows run produces the
    same bytes a POSIX run does; the drift gate compares bytes, and a
    platform that helpfully translated them would report drift on every
    machine but the one that wrote the file.
    """
    written: list[Path] = []
    for artifact in sorted(result.artifacts, key=lambda item: item.relative):
        target = artifact.path(base)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(artifact.content, encoding="utf-8", newline="\n")
        written.append(target)
    return tuple(written)


def _diff(relative: str, committed: str, rendered: str) -> str:
    """The first place two texts differ, said in one line.

    A unified diff of a 200KB canonical JSON document is not a report a
    person can read, and the line number plus both sides of the first
    difference is what actually locates the edit. The count of differing
    lines is carried too, so a whole-file change does not read like a
    one-character one.
    """
    import difflib

    left = committed.splitlines()
    right = rendered.splitlines()
    changed = sum(
        1
        for line in difflib.unified_diff(left, right, n=0, lineterm="")
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )
    for number, (was, now) in enumerate(zip(left, right, strict=False), start=1):
        if was != now:
            return (
                f"{relative} line {number} differs ({changed} line(s) in all): "
                f"committed {was.strip()[:120]!r}, rendered {now.strip()[:120]!r}"
            )
    if len(left) != len(right):
        shorter, longer = ("committed", "rendered") if len(left) < len(right) else (
            "rendered",
            "committed",
        )
        return (
            f"{relative}: the {longer} text has "
            f"{abs(len(left) - len(right))} line(s) the {shorter} one does not "
            f"({changed} line(s) in all)"
        )
    return f"{relative} differs in {changed} line(s)"


def _stale_learn_pages(bundle: DocsBundle, base: Path) -> list[Finding]:
    """Pages committed under the learning collection that nothing renders.

    The directory is read rather than written to (SDA-INV-9), and it is
    read here rather than inside
    :func:`~s0ma_dsl.docs_model.learn_pages.stale_pages` for that module's
    own reason: a gate that enumerated its own subject could satisfy
    itself. This finds the files; the collection says which of them it
    accounts for.

    A collection directory that is not there yet is not an error — it is a
    tree before the first write, and every page in it is already reported
    missing by the comparison below.
    """
    collection = base / learn_pages.LEARN_DIR
    if not collection.is_dir():
        return []
    present = sorted(
        path.relative_to(base).as_posix()
        for path in collection.glob("*.md")
        if path.is_file()
    )
    return [
        Finding(
            code=DOC_OUTPUT_DRIFT,
            location=f"{DOCS_ROOT}/{relative}",
            message=(
                f"{relative} is committed and this build renders nothing at "
                f"that path"
            ),
            remediation=(
                "A page in the learning collection is written for a concept "
                "the composition holds, so a page with no concept behind it "
                "is a page the build stopped keeping up to date. Either the "
                "concept was removed and this file should go with it, or it "
                "was renamed and this is the old name — delete the file."
            ),
        )
        for relative in learn_pages.stale_pages(present, bundle)
    ]


def _stale_media_packages(bundle: DocsBundle, base: Path) -> list[Finding]:
    """Packages committed under ``_generated/media`` that nothing renders.

    The same sweep :func:`_stale_learn_pages` makes and for the same
    reason, which is the only reason either exists: membership in this
    collection is *computed* — from the journeys the catalog publishes —
    so a package left behind by a journey that was unpublished or renamed
    is a file the declared-set comparison never looks at.
    """
    collection = base / render_media.MEDIA_DIR
    if not collection.is_dir():
        return []
    present = sorted(
        path.relative_to(base).as_posix()
        for path in collection.glob("*.json")
        if path.is_file()
    )
    return [
        Finding(
            code=DOC_OUTPUT_DRIFT,
            location=f"{DOCS_ROOT}/{relative}",
            message=(
                f"{relative} is committed and this build renders nothing at "
                f"that path"
            ),
            remediation=(
                "A media package is rendered for a journey some catalog "
                "document publishes, so a package with no such journey "
                "behind it is a walkthrough input the build stopped keeping "
                "up to date. Either the journey was retired, or its "
                "publishing document stopped covering it, or it was renamed "
                "and this is the old name — delete the file."
            ),
        )
        for relative in render_media.stale_packages(present, bundle)
    ]


def check(result: Build, base: Path) -> tuple[Finding, ...]:
    """Compare every rendered artifact against what is committed under ``base``.

    ``DOC_OUTPUT_DRIFT``, one finding per artifact, located at the
    artifact. **Nothing is written** — not the artifact, not a temporary
    copy, not a parent directory (SDA-INV-9). The comparison is between
    the string this build rendered and the string on disk, so there is no
    filesystem write for a caller to have to trust is absent.

    It also reports the other direction, which comparing a declared set
    against disk cannot see on its own: a file **committed under one of the
    two computed collections that this build does not render**. Writing and
    comparing both walk what the build produces, so a page left behind by
    a concept somebody deleted is a file no gate ever looks at — it stays
    in the tree, stays linked from nowhere, and goes stale silently, which
    is exactly the failure the August 2026 audit named. Only the learning
    collection and H3's media packages are swept, because they are the only
    output families whose membership is computed: every other declared
    output is a decision, and a decision that was reversed is a line
    somebody deleted from :data:`STATIC_OUTPUTS` in the same commit.
    """
    findings: list[Finding] = []
    findings.extend(_stale_learn_pages(result.bundle, base))
    findings.extend(_stale_media_packages(result.bundle, base))
    for artifact in sorted(result.artifacts, key=lambda item: item.relative):
        target = artifact.path(base)
        if not target.is_file():
            findings.append(
                Finding(
                    code=DOC_OUTPUT_DRIFT,
                    location=f"{DOCS_ROOT}/{artifact.relative}",
                    message=f"{artifact.relative} is missing — it has never been written",
                    remediation=(
                        "Run the write command to render it, then commit the "
                        "result. A declared output nobody has written is not a "
                        "clean build; it is an unfinished one."
                    ),
                )
            )
            continue
        committed = target.read_text(encoding="utf-8")
        if committed == artifact.content:
            continue
        findings.append(
            Finding(
                code=DOC_OUTPUT_DRIFT,
                location=f"{DOCS_ROOT}/{artifact.relative}",
                message=_diff(artifact.relative, committed, artifact.content),
                remediation=(
                    "Run the write command and commit what it produces. If the "
                    "committed file was edited by hand, that edit is lost either "
                    "way — a generated artifact is written by its build, and the "
                    "place to make the change is the source the build reads."
                ),
            )
        )
    return sort_findings(findings)
