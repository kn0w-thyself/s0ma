"""The one canonical negative battery for the Phase C documentation model.

Milestone C9 of the docs-function plan (internal) §8, answering architecture
plan §16.3's "every gate needs a deliberately failing fixture" for the gates
that are live at the end of Phase C.

**The contract this module holds, and the one I2 re-runs it for.**

1. *Every diagnostic the machinery can raise has a fixture here that raises
   it.* Not a fixture that constructs a :class:`Finding` and asserts its own
   handiwork — a fixture fed through the real gate, so the proof is that the
   gate fires rather than that the code name exists.
2. *Every fixture asserts three things*: the diagnostic id, the source
   location (exactly — including the empty string, which is the model's
   honest answer for the record types ``@1`` gives no file to point at), and
   that remediation text is present. A gate that says only "no" is a gate
   people learn to disable, so "it has remediation" is part of the gate.
3. *The completeness table is derived, never written down.* :data:`FIXTURES`
   maps a diagnostic to the test(s) that fire it, and two self-audits keep
   it honest: :data:`CODE_UNIVERSE` is grepped out of the ``docs_model``
   source tree at test time, and every mapped test name is resolved against
   this module. A code added to the machinery without a fixture here turns
   this module red; so does a fixture name that has been renamed away.
4. *A deferred gate stays visible.* The codes
   :data:`~s0ma_dsl.docs_model.validate.DEFERRED_GATES` names are recorded
   as unfireable-by-design with the milestone each waits for, rather than
   omitted — a code nobody can fire and nobody has written down is
   indistinguishable from a code somebody forgot. One remains, and the
   count is deliberately not written here: it is read off the map, so
   arming one moves the audit and not a sentence somebody has to notice.
   ``DOC_COVERAGE_UNMENTIONED`` waits for F.
   ``DOC_SIDE_EFFECT_UNDECLARED`` left the map at D5b and
   ``DOC_VERSION_MISMATCH`` at H1, each with its fixtures below — which
   is exactly the movement this clause exists to make visible.

**How I2 audits this.** Re-run the module. The two self-audits diff
:data:`FIXTURES` against the *then-current* code universe, so a phase that
mints a code, arms a deferred gate, or moves a firing site fails here with
the code named. The table below is not the audit; the audit reads the
source tree.

**What is deliberately not here.** ``DOC_CHANNEL_DIVERGENCE`` is a
test-utility code — it is defined in C7's ``test_docs_resolve_render.py``
(seeded by B5, landing in the product at F9) and appears nowhere in the
``docs_model`` source tree, so the source-derived universe does not contain
it and this battery does not claim it. Where an earlier milestone already
proves a red, the battery re-proves it with its own minimal fixture rather
than importing that module: duplicated proof is cheap, and a battery that
imports another test module cannot be run against a future tree on its own.

**No committed fixture files, deliberately.** C9 was offered a fixtures
directory and does not use one. Every fixture is built into ``tmp_path`` at
test time — no repository checkout, no git, no network, no wall clock — for
three reasons: a committed fixture tree is a second thing to keep in step
with the schemas it exercises; a battery that reads the checkout cannot run
against a future tree on its own; and a tracked Markdown fixture would land
in the corpus the completeness gate walks, so the battery would turn
``DOC_DOCUMENT_UNCATALOGED`` red on the real catalog just by existing. The
inputs are literals in this module, so they are byte-stable and two runs
report identically.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import s0ma_dsl.docs_model as docs_model
import s0ma_dsl.docs_model.evidence as evidence
from s0ma_dsl.docs_model.application import (
    DOC_GATE_VACUOUS,
    DOC_OUTPUT_DRIFT,
    DOCS_ROOT,
    SNAPSHOT_OUTPUT,
    Build,
    build,
    check,
    write,
)
from s0ma_dsl.docs_model.compose import DOC_CANONICAL_DUPLICATE, compose
from s0ma_dsl.docs_model.evidence import DOC_EXAMPLE_FAILED
from s0ma_dsl.docs_model.manifest import (
    ArtifactRecord,
    DocsManifest,
    PackageVersion,
    ProviderSchema,
    SourceHash,
    artifact_id,
)
from s0ma_dsl.docs_model.providers import (
    Finding,
    ProviderRegistry,
    ProviderResult,
    SourcedRecord,
    sort_records,
)
from s0ma_dsl.docs_model.providers_catalog import (
    CATALOG_FILE,
    CATALOG_SCHEMA,
    DOC_DOCUMENT_UNCATALOGED,
    CatalogProvider,
    check_canonical_sources,
    check_completeness,
    check_document_authorities,
)
from s0ma_dsl.docs_model.providers_concepts import (
    CONCEPTS_SCHEMA,
    DOC_AUTHORITY_STALE,
    DOC_RELATION_ONE_SIDED,
    DOC_VOICE_VIOLATION,
    FORBIDDEN_IN_AUTHORED_PROSE,
    ConceptsProvider,
    check_concept_relations,
)
from s0ma_dsl.docs_model.records import (
    HISTORICAL_CHANNEL,
    PREVIEW_CHANNEL,
    RELEASE_CHANNEL,
    SCHEMA,
    AuthorityRef,
    BuildStamp,
    ConceptRecord,
    DocsBundle,
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
from s0ma_dsl.docs_model.render_agent import DOC_TOPIC_OVERSIZED, check_budget, render_agent
from s0ma_dsl.docs_model.render_human import render_human
from s0ma_dsl.docs_model.resolve import (
    DOC_CAPABILITY_UNCOVERED,
    DOC_CONCEPT_UNCOVERED,
    DOC_SURFACE_UNCOVERED,
    ChannelException,
    CoveragePolicy,
    PrimaryCapability,
    SurfaceException,
    TopicIndex,
    check_coverage,
    check_journey_coverage,
    facts_of,
    resolve,
)
from s0ma_dsl.docs_model.serialize import canonical_json, stamped
from s0ma_dsl.docs_model.validate import (
    DEFERRED_GATES,
    DOC_APPROVAL_UNDECLARED,
    DOC_AUTHORITY_CONFLICT,
    DOC_AUTHORITY_MISDECLARED,
    DOC_CONCEPT_UNRESOLVED,
    DOC_JOURNEY_UNRESOLVED,
    DOC_JOURNEY_UNTESTED,
    DOC_PROVENANCE_MISSING,
    DOC_SEQUENCE_REPEATS,
    DOC_SIDE_EFFECT_UNDECLARED,
    DOC_SURFACE_UNBOUND,
    DOC_TEACHING_ORDER,
    DOC_TOPIC_UNRESOLVED,
    DOC_VERSION_MISMATCH,
    SIDE_EFFECT_WORDS,
    AuthorityClaim,
    ReferenceIndex,
    check_journeys,
    check_manifest,
    check_side_effects,
    validate_bundle,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

# ---------------------------------------------------------------------------
# The completeness table (T2)
# ---------------------------------------------------------------------------

#: Diagnostic → the test(s) in this module that deliberately fire it, named
#: ``Class.method`` so a reader can run one. A code has more than one entry
#: exactly where the machinery raises it from more than one site: the same
#: name reached by two paths is two gates, and a battery that proved only
#: one of them would report a coverage it does not have.
#:
#: This is the table I2 audits. It is not a list of codes — the codes come
#: from :data:`CODE_UNIVERSE`, which is read out of the source tree — it is
#: the claim that each of them has a proof, and where.
FIXTURES: Mapping[str, tuple[str, ...]] = {
    DOC_AUTHORITY_CONFLICT: (
        "TestAuthorityRecords.test_two_equal_ranked_authorities_over_one_domain",
    ),
    DOC_AUTHORITY_MISDECLARED: (
        "TestAuthorityRecords.test_a_class_that_disagrees_with_its_own_id",
        "TestAuthorityRecords.test_a_delegation_handed_up_the_order",
    ),
    DOC_AUTHORITY_STALE: (
        "TestTheAuthoredConceptsFile.test_a_pin_that_no_longer_matches_the_file",
    ),
    DOC_CANONICAL_DUPLICATE: (
        "TestDuplicateIdentity.test_two_providers_claim_one_id_with_different_facts",
        "TestDuplicateIdentity.test_two_catalog_rows_claim_one_canonical_source",
    ),
    DOC_CONCEPT_UNCOVERED: (
        "TestCoverage.test_a_composed_concept_no_read_surface_addresses",
    ),
    DOC_CONCEPT_UNRESOLVED: (
        "TestUnresolvedReferences.test_a_catalog_row_covering_an_absent_concept",
        "TestConceptRelations.test_a_relation_naming_a_concept_nobody_wrote",
    ),
    DOC_DOCUMENT_UNCATALOGED: (
        "TestCatalogCompleteness.test_a_tracked_document_with_no_row_and_no_exclusion",
    ),
    DOC_EXAMPLE_FAILED: (
        "TestEvidence.test_a_fixture_whose_expected_output_has_gone_stale",
        "TestEvidence.test_the_divergence_names_the_step_and_the_line",
    ),
    DOC_CAPABILITY_UNCOVERED: (
        "TestCoveragePolicy.test_a_capability_whose_journey_has_been_removed",
        "TestCoveragePolicy.test_a_journey_that_has_stopped_walking_the_capability",
        "TestCoveragePolicy.test_a_served_surface_no_ledger_classifies",
        "TestCoveragePolicy.test_a_capability_a_channel_ruling_has_swallowed",
    ),
    DOC_GATE_VACUOUS: (
        "TestVacuity.test_a_provider_that_produced_less_than_its_floor",
        "TestVacuity.test_a_floor_naming_a_provider_that_never_ran",
        "TestVacuity.test_a_sequence_that_teaches_nothing",
        "TestVacuity.test_a_build_that_renders_no_artifact",
        "TestVacuity.test_an_allowance_no_surface_uses",
        "TestCoveragePolicy.test_an_exception_for_a_surface_this_build_does_not_serve",
        "TestCoveragePolicy.test_a_channel_ruling_no_surface_uses",
    ),
    DOC_APPROVAL_UNDECLARED: (
        "TestJourneys.test_a_step_that_walks_into_an_approval_without_saying_so",
        "TestJourneys.test_a_boundary_declared_where_nothing_is_asked",
    ),
    DOC_JOURNEY_UNRESOLVED: (
        "TestUnresolvedReferences.test_a_journey_step_naming_an_absent_surface",
        "TestJourneys.test_a_recovery_written_against_a_failure_nothing_can_raise",
        "TestJourneys.test_a_failure_two_of_the_steps_can_raise",
    ),
    DOC_JOURNEY_UNTESTED: (
        "TestJourneys.test_a_journey_nothing_has_ever_run",
        "TestJourneys.test_evidence_that_is_named_and_not_green",
    ),
    DOC_OUTPUT_DRIFT: (
        "TestOutputDrift.test_a_hand_edited_artifact_is_named_line_by_line",
        "TestOutputDrift.test_a_declared_output_nobody_has_written",
    ),
    DOC_PROVENANCE_MISSING: (
        "TestProvenance.test_a_record_that_names_no_schema_version",
        "TestProvenance.test_a_placeholder_where_a_digest_belongs",
    ),
    DOC_RELATION_ONE_SIDED: (
        "TestTheAuthoredConceptsFile.test_a_symmetric_relation_declared_from_one_end",
        "TestConceptRelations.test_a_symmetric_relation_one_sided_across_the_bundle",
    ),
    DOC_SEQUENCE_REPEATS: (
        "TestTeachingSequences.test_a_teaching_order_that_says_one_topic_twice",
    ),
    DOC_TEACHING_ORDER: (
        "TestJourneys.test_a_concept_taught_after_the_thing_that_rests_on_it",
    ),
    DOC_SIDE_EFFECT_UNDECLARED: (
        "TestSideEffects.test_a_served_surface_that_says_nothing_about_what_it_does",
        "TestSideEffects.test_a_channel_nobody_has_classified",
        "TestSideEffects.test_a_word_outside_the_side_effect_vocabulary",
        "TestSideEffects.test_nothing_and_something_at_once",
        "TestSideEffects.test_a_described_channel_that_claims_an_effect",
    ),
    DOC_SURFACE_UNBOUND: (
        "TestSurfaceBinding.test_a_surface_that_reaches_nothing_and_says_nothing",
        "TestSurfaceBinding.test_a_component_reference_that_resolves_to_nothing",
    ),
    DOC_SURFACE_UNCOVERED: (
        "TestCoverage.test_a_composed_capability_no_read_surface_addresses",
    ),
    DOC_TOPIC_OVERSIZED: (
        "TestTheBoundedChannel.test_an_answer_that_does_not_fit_the_channel",
    ),
    DOC_TOPIC_UNRESOLVED: (
        "TestUnresolvedReferences.test_a_document_citing_an_authority_nobody_emits",
        "TestUnresolvedReferences.test_a_catalog_row_claiming_an_authority_nobody_emits",
        "TestUnresolvedReferences.test_a_question_this_build_has_no_answer_to",
        "TestPlantedFailureThroughTheApplication.test_a_planted_provider_fails_the_build",
        "TestCoveragePolicy.test_a_capability_serving_a_surface_nothing_serves",
    ),
    DOC_VERSION_MISMATCH: (
        "TestTheReleaseCurrency.test_a_preview_artifact_inside_a_release_manifest",
        "TestTheReleaseCurrency.test_an_artifact_that_represents_another_version",
        "TestTheReleaseCurrency.test_an_artifact_rendered_from_another_build",
        "TestTheReleaseCurrency.test_a_distribution_that_broke_the_lockstep",
        "TestTheReleaseCurrency.test_a_provider_emitting_against_an_older_model",
        "TestTheReleaseCurrency.test_a_channel_word_nothing_defines",
        "TestTheReleaseCurrency.test_a_manifest_assembled_from_another_bundle",
    ),
    DOC_VOICE_VIOLATION: (
        "TestTheAuthoredConceptsFile.test_a_word_the_product_voice_does_not_use",
    ),
}

#: Where the ``docs_model`` source tree lives, wherever this suite is run
#: from. Read off the imported package rather than off a repository-relative
#: path, so the audit works in a wheel-install context too — the thing being
#: audited is the machinery that is installed, not a checkout.
DOCS_MODEL_SOURCE = Path(docs_model.__file__).resolve().parent

#: Any ``DOC_*`` name. The bare ``DOC_*`` that appears in a docstring does
#: not match: a code has at least one letter after the underscore.
# The left lookbehind keeps a code embedded in a longer identifier out of
# the universe: MISSING_PUBLIC_DOC_REF must not contribute a phantom
# DOC_REF (found the hard way when a provider docstring first named it).
_CODE_NAME = re.compile(r"(?<![A-Z0-9_])DOC_[A-Z][A-Z0-9_]*")


def code_universe() -> frozenset[str]:
    """Every diagnostic name the ``docs_model`` source tree mentions.

    Grepped, never listed. A hand-written universe audits the fixtures
    against itself and would pass on the day somebody adds a code and
    forgets both — which is the failure this whole battery exists against.
    """
    found: set[str] = set()
    for module in sorted(DOCS_MODEL_SOURCE.glob("*.py")):
        found.update(_CODE_NAME.findall(module.read_text(encoding="utf-8")))
    return frozenset(found)


#: The universe as this run reads it. Held as a module constant so a reader
#: of a failure sees the same set the audit compared against.
CODE_UNIVERSE = code_universe()


# ---------------------------------------------------------------------------
# Shared fixture material
# ---------------------------------------------------------------------------

#: What every fixture record was "read from" — this module, which is where
#: they really are written. One string, so a test can assert a finding's
#: location by equality rather than by substring.
FIXTURE_SOURCE = "packages/s0ma-dsl/tests/test_docs_model_negative.py"

#: The release a fixture bundle is stamped with. Fixed, never derived from
#: the installed version: a battery whose stamps move on a version bump
#: would report drift for reasons that have nothing to do with a gate.
RELEASE = "0.0.0"

_PROVENANCE = Provenance(
    adapter_id="negative",
    schema_version=SCHEMA,
    source=FIXTURE_SOURCE,
    source_sha256="0" * 64,
)

_AUTHORITY = AuthorityRef(
    id="authority:spec/negative-fixture",
    authority_class="spec",
    source="docs/fixture-authority.md",
    section="1",
    content_sha256="1" * 64,
    status="Current",
    delegates=(),
)


def _empty_stamp() -> BuildStamp:
    return BuildStamp(schema=SCHEMA, release_version="", snapshot_hash="")


def _bundle(
    *,
    authorities: tuple[AuthorityRef, ...] = (),
    concepts: tuple[ConceptRecord, ...] = (),
    surfaces: tuple[SurfaceRecord, ...] = (),
    journeys: tuple[JourneyRecord, ...] = (),
    sequences: tuple[TeachingSequence, ...] = (),
    documents: tuple[DocumentRecord, ...] = (),
) -> DocsBundle:
    """One stamped bundle, built the only supported way."""
    return stamped(
        DocsBundle(
            stamp=_empty_stamp(),
            authorities=authorities,
            concepts=concepts,
            surfaces=surfaces,
            journeys=journeys,
            sequences=sequences,
            documents=documents,
        ),
        RELEASE,
    )


def _concept(
    identifier: str,
    *,
    term: str,
    summary: str = "A short form a bounded channel may fall back to.",
    governed_by: tuple[str, ...] = (),
    related: tuple[tuple[str, ...], ...] = (),
) -> ConceptRecord:
    """One well-formed concept, ready to be broken in exactly one place."""
    return ConceptRecord(
        id=identifier,
        term=term,
        summary=summary,
        plain_definition="A record written by this battery so a gate has something to find.",
        purpose="To prove that the gate this test is about fires, and says where.",
        use_when="Never outside this module.",
        do_not_use_when="Anywhere a person might read it as documentation.",
        governed_by=governed_by,
        examples=(),
        related_concepts=related,
    )


def _surface(
    identifier: str = "cli:s0ma/init",
    *,
    channel: str = "cli",
    component_refs: tuple[str, ...] = (),
    manual_exception: str = "Written by hand for the fixture build it belongs to.",
    governed_by: tuple[str, ...] = (),
    side_effects: tuple[str, ...] = ("read", "write"),
    errors: tuple[str, ...] = (),
    provenance: Provenance = _PROVENANCE,
) -> SurfaceRecord:
    """One served capability, bound by a written exception unless told not to.

    ``side_effects`` says what the ``intent`` below describes — starting a
    project reads a tree and writes a skeleton into it — rather than
    nothing. D5b armed the gate that reads an empty tuple as an
    unanswered question, and a shared helper whose default is the
    unanswered form would put that answer into every fixture that only
    meant to break something else.
    """
    return SurfaceRecord(
        id=identifier,
        channel=channel,
        public_name=identifier.partition(":")[2].replace("/", " "),
        intent="Start a new project with a working skeleton in it.",
        component_refs=component_refs,
        manual_exception=manual_exception,
        governed_by=governed_by,
        side_effects=side_effects,
        errors=errors,
        provenance=provenance,
    )


def _document(
    identifier: str = "doc:guide/readme",
    *,
    canonical_source: str = "README.md",
    prose_locator: str = "README.md",
    governed_by: tuple[str, ...] = (),
    covers: tuple[str, ...] = (),
    authority: str = "",
) -> DocumentRecord:
    """One catalog row as a record, without going through the catalog file."""
    return DocumentRecord(
        id=identifier,
        title="A fixture document",
        canonical_source=canonical_source,
        prose_locator=prose_locator,
        governed_by=governed_by,
        covers=covers,
        authority=authority,
    )


def _journey(
    identifier: str = "journey:first-project",
    *,
    steps: tuple[JourneyStep, ...] | None = None,
    recovery_paths: tuple[RecoveryPath, ...] = (),
    concepts_taught: tuple[str, ...] = (),
    concepts_required: tuple[str, ...] = (),
    evidence: tuple[ExampleRef, ...] = (),
) -> JourneyRecord:
    """One authored path, sound unless a test breaks it in one place.

    The default step names a surface no fixture bundle holds, which would
    be an unresolved reference — so every test that cares passes its own
    steps. The default exists for the tests that are about the journey
    rather than about its steps, and those pass a bundle with the surface
    in it or assert on one code only.
    """
    return JourneyRecord(
        id=identifier,
        intent="Take somebody from an empty folder to a first check they trust.",
        steps=steps if steps is not None else (),
        recovery_paths=recovery_paths,
        concepts_taught=concepts_taught,
        concepts_required=concepts_required,
        evidence=evidence,
    )


def _step(
    surface: str, *, approval_boundary: str = ""
) -> JourneyStep:
    """One step of a fixture journey, saying nothing unless told to."""
    return JourneyStep(
        surface=surface,
        purpose="Get a folder that is already a project.",
        expected_outcome="A skeleton, and a note saying what went where.",
        approval_boundary=approval_boundary,
    )


def _authority(
    identifier: str,
    *,
    authority_class: str,
    section: str = "1",
    delegates: tuple[Any, ...] = (),
) -> AuthorityRef:
    """One citation of a written authority, ranked unless told otherwise."""
    return AuthorityRef(
        id=identifier,
        authority_class=authority_class,
        source="docs/fixture-authority.md",
        section=section,
        content_sha256="1" * 64,
        status="Current",
        delegates=delegates,
    )


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _of(findings: Sequence[Finding], code: str) -> tuple[Finding, ...]:
    """Every finding with ``code``, in reporting order."""
    return tuple(item for item in findings if item.code == code)


#: Where phase 9 refuses when the root under test is a fixture directory
#: rather than a workspace. Eight of this application's declared outputs are
#: *about a workspace* — F4's MCP, studi0 and packages references and the
#: component index read the composed server and viewer families, the
#: distributions under ``packages/`` and the registered components,
#: H1's manifest cannot state which release it describes without those
#: distributions either, I1's self-description reads the documentation
#: project's own committed build, which a fixture directory does not have,
#: and the quick reference in both its renderings reads its authored words
#: from a file of this repository —
#: and F5's learning collection refuses without
#: ``concept:s0ma-file``. None of them will render over a temp directory
#: holding two planted records, and
#: each says so as a ``DOC_GATE_VACUOUS`` finding located at the page it
#: could not write, with the artifact floor reporting the short set from
#: the documentation root itself.
#:
#: That is the right report and the wrong subject: this file's assertions
#: are statements about *one planted change*, so they drop these by
#: location and keep everything else. Dropping them by *code* would hide
#: the vacuity plants this file makes on purpose, which is why the ledger
#: is a set of places rather than a code.
_OFF_WORKSPACE: frozenset[str] = frozenset(
    {
        "docs",
        "docs/_generated/core-teaching-slice.json",
        "docs/_generated/docs-manifest.json",
        "docs/_generated/quick-reference-machine.json",
        "docs/architecture/component-index.md",
        "docs/architecture/docs-application.md",
        "docs/learn/",
        "docs/reference/mcp.md",
        "docs/reference/packages.md",
        "docs/reference/quick-reference-readable.md",
        "docs/reference/studi0.md",
    }
)


def _in_corpus(findings: Sequence[Finding]) -> tuple[Finding, ...]:
    """Every finding except the ones a fixture root cannot avoid."""
    return tuple(item for item in findings if item.location not in _OFF_WORKSPACE)


def _one(findings: Sequence[Finding], code: str) -> Finding:
    """The single finding with ``code``, refusing none and refusing two."""
    found = _of(findings, code)
    assert len(found) == 1, (
        f"expected exactly one {code}; got {len(found)}. The whole report was: "
        f"{[item.rendered() for item in findings]}"
    )
    return found[0]


def _located(finding: Finding, location: str) -> Finding:
    """Assert the third and fourth halves of the contract: where, and what to do.

    ``location`` is compared by equality, empty string included. An empty
    location is a claim in ``@1`` — a concept, a journey and a teaching
    sequence name no file, so the model says nothing rather than guessing —
    and a test that only checked for a *non-empty* location would let a
    regression that dropped every location pass on those three types.
    """
    assert finding.location == location, (
        f"{finding.code} should be located at {location!r} and is at "
        f"{finding.location!r}"
    )
    assert finding.message.strip(), f"{finding.code} says nothing about what is wrong"
    assert finding.remediation.strip(), (
        f"{finding.code} offers no remediation; a gate that says only 'no' is a "
        f"gate people learn to disable"
    )
    return finding


# ---------------------------------------------------------------------------
# A provider that hands over exactly what a test wrote (T1, the C8 path)
# ---------------------------------------------------------------------------


class PlantedProvider:
    """A provider whose records are whatever the test needs them to be.

    The seam ``application.build(providers=...)`` exists for: a caller
    brings its own composition, and every gate downstream of the merge runs
    over it. That is how the application-level fixtures below reach the real
    build without a repository checkout, git, or the five real providers.
    """

    def __init__(self, provider_id: str, *records: SourcedRecord) -> None:
        self._id = provider_id
        self._records = records

    @property
    def provider_id(self) -> str:
        return self._id

    def provide(self) -> ProviderResult:
        return ProviderResult(provider_id=self._id, records=sort_records(self._records))


def _sourced(record: Any, provenance: Provenance = _PROVENANCE) -> SourcedRecord:
    return SourcedRecord(record=record, provenance=provenance)


def _clean_registry() -> ProviderRegistry:
    """One provider whose records pass every gate the application runs.

    The base every application-level fixture starts from. It is asserted
    clean by :meth:`TestPlantedFailureThroughTheApplication.test_the_base_build_is_clean`,
    which is what makes "this build reports X" a statement about the one
    thing the test broke.
    """
    concept = _concept(
        "concept:first-idea", term="first idea", governed_by=(_AUTHORITY.id,)
    )
    return ProviderRegistry.of(
        PlantedProvider("negative", _sourced(_AUTHORITY), _sourced(concept))
    )


#: The policy a planted build is judged against: one that claims nothing
#: and excuses nothing. E8's third instance of the same rule the floors and
#: the allowances already follow — a caller that brings its own providers
#: brings its own policy — and the empty value is the honest one here for
#: the reason ``CoveragePolicy`` records: it is not permissive, it is
#: neutral. A planted build that composed a surface and was handed this
#: reports that surface as unclassified, which is exactly what
#: :class:`TestCoveragePolicy` below relies on.
_NO_POLICY = CoveragePolicy(
    source=FIXTURE_SOURCE,
    capabilities=(),
    surface_exceptions=(),
    channel_exceptions=(),
)


def _planted_build(
    root: Path,
    *,
    providers: ProviderRegistry | None = None,
    floors: Mapping[tuple[str, str], int] | None = None,
    allowances: Mapping[tuple[str, str], str] | None = None,
    coverage: CoveragePolicy | None = None,
) -> Build:
    """One whole application build over planted records and nothing else.

    ``floors``, ``allowances`` and ``coverage`` all default to none at all
    rather than to this repository's, for the reason C8 gives and D5b and
    E8 extend: a caller that brings its own providers brings its own
    policy. Leaving the repository's floors in place would report ten
    providers it never registered as missing; leaving its allowances in
    place would report three standing permissions for a silence no planted
    surface is keeping; and leaving its coverage policy in place would
    report nine capabilities this composition has never served.
    """
    return build(
        root,
        version=RELEASE,
        providers=providers if providers is not None else _clean_registry(),
        floors={} if floors is None else floors,
        allowances={} if allowances is None else allowances,
        coverage=_NO_POLICY if coverage is None else coverage,
    )


# ---------------------------------------------------------------------------
# An authored concepts file, and its checkout (T1)
# ---------------------------------------------------------------------------

_CONCEPTS_DOMAIN = "negative"
_CONCEPTS_FILE = f"docs/s0ma_src/concepts/{_CONCEPTS_DOMAIN}.json"
_AUTHORITY_DOC = "docs/fixture-authority.md"
_AUTHORITY_HEADING = "1. The fixture section"
_AUTHORITY_TEXT = (
    "# A fixture authority\n"
    "\n"
    f"## {_AUTHORITY_HEADING}\n"
    "\n"
    "What this section says, so a concept has something to cite.\n"
)


def _digest_of(text: str) -> str:
    """The sha256 the concepts loader computes, computed the same way."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _authored_concept(slug: str, term: str, related: list[list[str]]) -> dict[str, Any]:
    """One concept as the authored file writes it, in the loader's key set."""
    return {
        "id": f"concept:{slug}",
        "term": term,
        "summary": "A short form a bounded channel may fall back to.",
        "plain_definition": "A record written by this battery so a gate has something to find.",
        "purpose": "To prove that the gate this test is about fires, and says where.",
        "use_when": "Never outside this module.",
        "do_not_use_when": "Anywhere a person might read it as documentation.",
        "governed_by": [_AUTHORITY.id],
        "examples": [],
        "syntax": [],
        "related_concepts": related,
    }


def _concepts_document(digest: str) -> dict[str, Any]:
    """A concepts file with nothing wrong with it, ready to be broken once."""
    return {
        "schema": CONCEPTS_SCHEMA,
        "domain": _CONCEPTS_DOMAIN,
        "sources": [{"path": _AUTHORITY_DOC, "sha256": digest}],
        "authorities": [
            {
                "heading": _AUTHORITY_HEADING,
                "id": _AUTHORITY.id,
                "section": "1",
                "source": _AUTHORITY_DOC,
            }
        ],
        "external_ids": [],
        "aliases": {},
        "records": [
            _authored_concept(
                "first-idea", "first idea", [["contrasts-with", "concept:second-idea"]]
            ),
            _authored_concept(
                "second-idea", "second idea", [["contrasts-with", "concept:first-idea"]]
            ),
        ],
    }


def _concepts_tree(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None] | None = None
) -> ConceptsProvider:
    """A checkout holding one authored concepts file and the document it cites."""
    document_path = tmp_path / _AUTHORITY_DOC
    document_path.parent.mkdir(parents=True, exist_ok=True)
    document_path.write_text(_AUTHORITY_TEXT, encoding="utf-8", newline="\n")

    authored = _concepts_document(_digest_of(_AUTHORITY_TEXT))
    if mutate is not None:
        mutate(authored)
    target = tmp_path / _CONCEPTS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(authored), encoding="utf-8", newline="\n")
    return ConceptsProvider(
        root=tmp_path, relative=_CONCEPTS_FILE, domain=_CONCEPTS_DOMAIN
    )


# ---------------------------------------------------------------------------
# A document catalog, and its checkout (T1)
# ---------------------------------------------------------------------------

_CATALOG_SELF = "doc:catalog/document-catalog"


def _catalog_row(**overrides: Any) -> dict[str, Any]:
    """One well-formed catalog row."""
    row: dict[str, Any] = {
        "id": "doc:guide/readme",
        "title": "A fixture document",
        "kind": "guide",
        "audiences": ["contributor"],
        "status": "living",
        "canonical_source": "README.md",
        "prose_locator": "README.md",
        "authority": "",
        "governed_by": [],
        "covers": [],
    }
    row.update(overrides)
    return row


def _catalog_tree(
    tmp_path: Path,
    documents: list[dict[str, Any]] | None = None,
    excluded: list[dict[str, str]] | None = None,
) -> CatalogProvider:
    """A checkout holding a catalog and every file that catalog names."""
    rows = [_catalog_row()] if documents is None else documents
    authored: dict[str, Any] = {
        "schema": CATALOG_SCHEMA,
        "self": {
            "id": _CATALOG_SELF,
            "title": "The document catalog",
            "kind": "reference",
            "audiences": ["contributor"],
            "status": "living",
        },
        "excluded": [] if excluded is None else excluded,
        "documents": rows,
    }
    for row in rows:
        for value in (row.get("canonical_source"), row.get("prose_locator")):
            if isinstance(value, str) and value:
                _touch(tmp_path / value.partition("#")[0])
    for item in authored["excluded"]:
        _touch(tmp_path / item["path"])
    target = tmp_path / CATALOG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(authored), encoding="utf-8", newline="\n")
    return CatalogProvider(root=tmp_path)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# A fixture document\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# Provenance completeness
# ---------------------------------------------------------------------------


class TestProvenance:
    """``DOC_PROVENANCE_MISSING`` — a record nobody can trace to a source."""

    def test_a_record_that_names_no_schema_version(self) -> None:
        surface = _surface(
            provenance=Provenance(
                adapter_id="negative",
                schema_version="",
                source=FIXTURE_SOURCE,
                source_sha256="0" * 64,
            )
        )
        findings = validate_bundle(_bundle(surfaces=(surface,)))
        found = _located(_one(findings, DOC_PROVENANCE_MISSING), FIXTURE_SOURCE)
        assert "schema_version" in found.message

    def test_a_placeholder_where_a_digest_belongs(self) -> None:
        """A placeholder reads as a real digest to every later gate."""
        surface = _surface(
            provenance=Provenance(
                adapter_id="negative",
                schema_version=SCHEMA,
                source=FIXTURE_SOURCE,
                source_sha256="not-a-real-digest",
            )
        )
        findings = validate_bundle(_bundle(surfaces=(surface,)))
        found = _located(_one(findings, DOC_PROVENANCE_MISSING), FIXTURE_SOURCE)
        assert "sha256" in found.message


# ---------------------------------------------------------------------------
# Surface binding
# ---------------------------------------------------------------------------


class TestSurfaceBinding:
    """``DOC_SURFACE_UNBOUND`` — a capability nothing connects to what runs."""

    def test_a_surface_that_reaches_nothing_and_says_nothing(self) -> None:
        surface = _surface(component_refs=(), manual_exception="")
        findings = validate_bundle(_bundle(surfaces=(surface,)))
        found = _located(_one(findings, DOC_SURFACE_UNBOUND), FIXTURE_SOURCE)
        assert "cli:s0ma/init" in found.message

    def test_a_component_reference_that_resolves_to_nothing(self) -> None:
        """The other axis: it names a component, and no build addresses it."""
        surface = _surface(
            component_refs=("component:s0ma_dsl.docs_model.absent",),
            manual_exception="",
        )
        findings = validate_bundle(_bundle(surfaces=(surface,)))
        found = _located(_one(findings, DOC_SURFACE_UNBOUND), FIXTURE_SOURCE)
        assert "component:s0ma_dsl.docs_model.absent" in found.message


# ---------------------------------------------------------------------------
# Side effects
# ---------------------------------------------------------------------------


class TestSideEffects:
    """``DOC_SIDE_EFFECT_UNDECLARED`` — armed at D5b, five ways to fire it.

    The gate's whole premise is that ``('none',)`` and ``()`` are
    different answers, so every fixture here is about the difference: one
    is a surface saying it changes nothing, the other is nobody having
    said. Four of the five are a surface that got it wrong; the fifth is a
    channel nobody classified, which is the same failure one level up.
    """

    def test_a_served_surface_that_says_nothing_about_what_it_does(self) -> None:
        """The gate proper: an empty tuple is the unanswered question."""
        surface = _surface(side_effects=())
        findings = validate_bundle(_bundle(surfaces=(surface,)))
        found = _located(_one(findings, DOC_SIDE_EFFECT_UNDECLARED), FIXTURE_SOURCE)
        assert "cli:s0ma/init" in found.message
        assert "('none',)" in found.remediation

    def test_a_source_allowed_to_be_silent_is_not_a_finding(self) -> None:
        """The control, and the asymmetry the plan asked for by name.

        Core's MCP tools declare no annotations and the authoring server's
        do. The silence is allowed *per source*, in writing — not excused
        per surface and not defaulted to — so the same record that fires
        above passes here only because somebody wrote down why.
        """
        surface = _surface(side_effects=())
        findings = validate_bundle(
            _bundle(surfaces=(surface,)),
            allowances={("negative", "cli"): "The fixture source cannot say."},
        )
        assert _of(findings, DOC_SIDE_EFFECT_UNDECLARED) == ()

    def test_a_channel_nobody_has_classified(self) -> None:
        """One level up: nothing said whether the question even applies."""
        surface = _surface("cli:s0ma/init", channel="telepathy")
        findings = validate_bundle(_bundle(surfaces=(surface,)))
        found = _located(_one(findings, DOC_SIDE_EFFECT_UNDECLARED), FIXTURE_SOURCE)
        assert "telepathy" in found.message
        assert "CHANNEL_EFFECTS" in found.remediation

    def test_a_word_outside_the_side_effect_vocabulary(self) -> None:
        """A word no gate recognizes reads as a classified surface."""
        surface = _surface(side_effects=("read", "teleports"))
        findings = validate_bundle(_bundle(surfaces=(surface,)))
        found = _located(_one(findings, DOC_SIDE_EFFECT_UNDECLARED), FIXTURE_SOURCE)
        assert "teleports" in found.message

    def test_nothing_and_something_at_once(self) -> None:
        """``none`` is the whole answer or it is not part of one."""
        surface = _surface(side_effects=("none", "write"))
        findings = validate_bundle(_bundle(surfaces=(surface,)))
        found = _located(_one(findings, DOC_SIDE_EFFECT_UNDECLARED), FIXTURE_SOURCE)
        assert "changes nothing and also says what it changes" in found.message

    def test_a_described_channel_that_claims_an_effect(self) -> None:
        """The classification has teeth in both directions.

        ``diagnostic`` and ``config`` name a thing rather than a way to
        reach one, which is why they answer ``none``. A record on one of
        them claiming to write has outgrown the classification, and before
        this table nothing could have noticed.
        """
        surface = _surface(
            "diagnostic:S0MA_FIXTURE", channel="diagnostic", side_effects=("write",)
        )
        findings = validate_bundle(_bundle(surfaces=(surface,)))
        found = _located(_one(findings, DOC_SIDE_EFFECT_UNDECLARED), FIXTURE_SOURCE)
        assert "names a thing rather than a way to reach one" in found.message

    def test_the_vocabulary_the_providers_refuse_against_is_the_model_s(self) -> None:
        """Three copies of one word list, pinned equal.

        Two providers refuse an unclassified surface where they read it,
        which is the right place to refuse; the model holds the list the
        gate compares against. Three lists that can disagree is how a word
        becomes legal in one reading and meaningless in another.
        """
        from s0ma_dsl.docs_model import providers_cli, providers_studi0

        assert providers_cli.SIDE_EFFECT_WORDS == SIDE_EFFECT_WORDS
        assert providers_studi0._EFFECT_WORDS == SIDE_EFFECT_WORDS


# ---------------------------------------------------------------------------
# Unresolved references
# ---------------------------------------------------------------------------


class TestUnresolvedReferences:
    """The four codes an edge that reaches nothing can raise, one each."""

    def test_a_journey_step_naming_an_absent_surface(self) -> None:
        """``DOC_JOURNEY_UNRESOLVED``. A journey names no file, so no location."""
        journey = JourneyRecord(
            id="journey:first-project",
            intent="Take somebody from an empty folder to a first check they trust.",
            steps=(
                JourneyStep(
                    surface="cli:s0ma/absent",
                    purpose="Get a folder that is already a project.",
                    expected_outcome="A skeleton, and a note saying what went where.",
                ),
            ),
            recovery_paths=(),
        )
        findings = validate_bundle(_bundle(journeys=(journey,)))
        found = _located(_one(findings, DOC_JOURNEY_UNRESOLVED), "")
        assert "cli:s0ma/absent" in found.message

    def test_a_catalog_row_covering_an_absent_concept(self) -> None:
        """``DOC_CONCEPT_UNRESOLVED``, located at the prose a person may edit."""
        document = _document(covers=("concept:nobody-wrote-this",))
        findings = validate_bundle(_bundle(documents=(document,)))
        found = _located(_one(findings, DOC_CONCEPT_UNRESOLVED), "README.md")
        assert "concept:nobody-wrote-this" in found.message

    def test_a_document_citing_an_authority_nobody_emits(self) -> None:
        """``DOC_TOPIC_UNRESOLVED``: well formed, and names nothing."""
        document = _document(governed_by=("authority:spec/absent",))
        findings = validate_bundle(_bundle(documents=(document,)))
        found = _located(_one(findings, DOC_TOPIC_UNRESOLVED), "README.md")
        assert "authority:spec/absent" in found.message

    def test_a_catalog_row_claiming_an_authority_nobody_emits(self) -> None:
        """The same code from the catalog's own gate over ``authority``.

        ``DocumentRecord.authority`` arrived after C2's edge walk was
        written, so C6 resolves its own field. Two firing sites, one code —
        the battery proves both rather than assuming the second follows.
        """
        document = _document(authority="authority:adr/absent")
        findings = check_document_authorities(_bundle(documents=(document,)))
        found = _located(_one(findings, DOC_TOPIC_UNRESOLVED), "README.md")
        assert "authority:adr/absent" in found.message

    def test_a_question_this_build_has_no_answer_to(self) -> None:
        """The resolver's miss: the same code, raised at a read surface."""
        bundle = _bundle(concepts=(_concept("concept:first-idea", term="first idea"),))
        resolution = resolve(TopicIndex.of(bundle), "something nobody wrote")
        assert resolution.state() == "unresolved"
        assert resolution.finding is not None
        _located(resolution.finding, "")
        assert resolution.finding.code == DOC_TOPIC_UNRESOLVED


# ---------------------------------------------------------------------------
# Teaching sequences
# ---------------------------------------------------------------------------


class TestJourneys:
    """E1's four rules, each fired once and located where ``@1`` can locate it.

    A journey names no file, so a finding about the path itself carries no
    location; a finding about a *step* is placed at the surface the step
    names, because that record does know where it was read from.
    """

    def test_a_concept_taught_after_the_thing_that_rests_on_it(self) -> None:
        """``DOC_TEACHING_ORDER``. Every reference resolves and it still fails."""
        layer = _concept("concept:layer", term="layer")
        nerve = _concept(
            "concept:nerve", term="nerve", related=(("requires", "concept:layer"),)
        )
        journey = _journey(concepts_taught=("concept:nerve", "concept:layer"))
        findings = validate_bundle(_bundle(concepts=(layer, nerve), journeys=(journey,)))
        found = _located(_one(findings, DOC_TEACHING_ORDER), "")
        assert "step 1" in found.message
        assert "concept:layer" in found.message

    def test_the_same_order_the_other_way_round_is_clean(self) -> None:
        """The gate is about order, not about the edge existing at all."""
        layer = _concept("concept:layer", term="layer")
        nerve = _concept(
            "concept:nerve", term="nerve", related=(("requires", "concept:layer"),)
        )
        journey = _journey(concepts_taught=("concept:layer", "concept:nerve"))
        findings = validate_bundle(_bundle(concepts=(layer, nerve), journeys=(journey,)))
        assert _of(findings, DOC_TEACHING_ORDER) == ()

    def test_a_prerequisite_declared_as_already_known_is_the_other_answer(self) -> None:
        """``concepts_required`` is the second way to satisfy the same rule."""
        layer = _concept("concept:layer", term="layer")
        nerve = _concept(
            "concept:nerve", term="nerve", related=(("requires", "concept:layer"),)
        )
        journey = _journey(
            concepts_taught=("concept:nerve",), concepts_required=("concept:layer",)
        )
        findings = validate_bundle(_bundle(concepts=(layer, nerve), journeys=(journey,)))
        assert _of(findings, DOC_TEACHING_ORDER) == ()

    def test_a_step_that_walks_into_an_approval_without_saying_so(self) -> None:
        """``DOC_APPROVAL_UNDECLARED``, located at the surface that asks."""
        surface = _surface("cli:s0ma/feedback", side_effects=("approval", "network"))
        journey = _journey(steps=(_step(surface.id),))
        findings = validate_bundle(_bundle(surfaces=(surface,), journeys=(journey,)))
        found = _located(_one(findings, DOC_APPROVAL_UNDECLARED), FIXTURE_SOURCE)
        assert "step 1" in found.message
        assert "approval" in found.message

    def test_a_boundary_declared_where_nothing_is_asked(self) -> None:
        """The other direction: a prompt the reader is promised and never gets."""
        surface = _surface("cli:s0ma/check", side_effects=("read",))
        journey = _journey(
            steps=(_step(surface.id, approval_boundary="You will be asked first."),)
        )
        findings = validate_bundle(_bundle(surfaces=(surface,), journeys=(journey,)))
        found = _located(_one(findings, DOC_APPROVAL_UNDECLARED), FIXTURE_SOURCE)
        assert "no approval is asked for there" in found.message

    def test_a_recovery_written_against_a_failure_nothing_can_raise(self) -> None:
        """``DOC_JOURNEY_UNRESOLVED`` — the diagnostic class §11's wording names."""
        surface = _surface("cli:s0ma/check", side_effects=("read",))
        journey = _journey(
            steps=(_step(surface.id),),
            recovery_paths=(
                RecoveryPath("NEVER_HAPPENS", surface.id, "Try it again."),
            ),
        )
        findings = validate_bundle(_bundle(surfaces=(surface,), journeys=(journey,)))
        found = _located(_one(findings, DOC_JOURNEY_UNRESOLVED), "")
        assert "NEVER_HAPPENS" in found.message
        assert "recovery_paths[0]" in found.message

    def test_a_failure_two_of_the_steps_can_raise(self) -> None:
        """B7's ambiguity rule: which step is the reader recovering from?"""
        first = _surface("cli:s0ma/build", side_effects=("write",), errors=("NOT_BUILT",))
        second = _surface(
            "cli:s0ma/inspect", side_effects=("read",), errors=("NOT_BUILT",)
        )
        journey = _journey(
            steps=(_step(first.id), _step(second.id)),
            recovery_paths=(RecoveryPath("NOT_BUILT", first.id, "Build it first."),),
        )
        findings = validate_bundle(
            _bundle(surfaces=(first, second), journeys=(journey,))
        )
        found = _located(_one(findings, DOC_JOURNEY_UNRESOLVED), "")
        assert "cli:s0ma/build, cli:s0ma/inspect" in found.message

    def test_a_step_surfaces_own_declared_error_answers_the_recovery(self) -> None:
        """One of the two ways a failure is answerable, proved green."""
        surface = _surface("cli:s0ma/build", side_effects=("write",), errors=("NOT_BUILT",))
        journey = _journey(
            steps=(_step(surface.id),),
            recovery_paths=(RecoveryPath("NOT_BUILT", surface.id, "Build it first."),),
        )
        findings = validate_bundle(_bundle(surfaces=(surface,), journeys=(journey,)))
        assert _of(findings, DOC_JOURNEY_UNRESOLVED) == ()

    def test_a_registered_diagnostic_answers_it_too(self) -> None:
        """The other way: no step declares it and the build addresses the code."""
        surface = _surface("cli:s0ma/build", side_effects=("write",))
        code = _surface("diagnostic:PARSE_ERROR", channel="diagnostic", side_effects=("none",))
        journey = _journey(
            steps=(_step(surface.id),),
            recovery_paths=(RecoveryPath("PARSE_ERROR", surface.id, "Fix the line."),),
        )
        findings = validate_bundle(_bundle(surfaces=(surface, code), journeys=(journey,)))
        assert _of(findings, DOC_JOURNEY_UNRESOLVED) == ()

    def test_a_journey_nothing_has_ever_run(self) -> None:
        """``DOC_JOURNEY_UNTESTED``, asked because a resolver was handed over."""
        journey = _journey()
        bundle = _bundle(journeys=(journey,))
        findings = check_journeys(
            bundle, ReferenceIndex.of(bundle), evidence_resolver=lambda _: ()
        )
        found = _located(_one(findings, DOC_JOURNEY_UNTESTED), "")
        assert "no executable evidence" in found.message

    def test_evidence_that_is_named_and_not_green(self) -> None:
        """The worse half: a path that says it was checked and was not."""
        journey = _journey(
            evidence=(ExampleRef("example:first_project_walkthrough", "tools.s0ma"),)
        )
        bundle = _bundle(journeys=(journey,))
        findings = check_journeys(
            bundle, ReferenceIndex.of(bundle), evidence_resolver=lambda _: ()
        )
        found = _located(_one(findings, DOC_JOURNEY_UNTESTED), "")
        assert "example:first_project_walkthrough" in found.message

    def test_no_resolver_asks_no_question(self) -> None:
        """The seam E2 arms: without a caller who can answer, nothing fires."""
        bundle = _bundle(journeys=(_journey(),))
        assert _of(check_journeys(bundle, ReferenceIndex.of(bundle)), DOC_JOURNEY_UNTESTED) == ()

    def test_the_repeated_relation_word_is_the_one_the_loader_declares(self) -> None:
        """``validate`` repeats the word rather than importing a provider.

        The vocabulary is closed and lives with the loader that reads it,
        so the repetition is pinned here — a rename on either side turns
        this red instead of turning the teaching gate silently vacuous.
        """
        from s0ma_dsl.docs_model.providers_concepts import RELATION_NAMES
        from s0ma_dsl.docs_model.validate import TEACHING_PREREQUISITE

        assert TEACHING_PREREQUISITE in RELATION_NAMES


# ---------------------------------------------------------------------------
# Transcript evidence
# ---------------------------------------------------------------------------


class TestEvidence:
    """``DOC_EXAMPLE_FAILED`` — a fixture that no longer describes the product.

    Fired against a *captured* transcript rather than a replayed one, and
    that is the point of E2 splitting the runner in two: the comparison is
    pure, so the battery keeps its no-checkout, no-subprocess, no-clock
    rule while still firing the real code path a real divergence takes.
    The replay half is proved in ``test_docs_evidence.py``, against the
    three fixtures this repository commits.
    """

    def test_a_fixture_whose_expected_output_has_gone_stale(self) -> None:
        record = _transcript()
        found = _one(
            evidence.compare(record, _replayed(record, "4 file(s) checked.")).findings,
            DOC_EXAMPLE_FAILED,
        )
        _located(found, "evidence/sample.json")
        assert record.id in found.message
        assert "3 file(s) checked." in found.message

    def test_the_divergence_names_the_step_and_the_line(self) -> None:
        """A report that says only "it failed" is one nobody can act on."""
        record = _transcript()
        outcome = evidence.compare(record, _replayed(record, "something else"))
        assert outcome.divergence is not None
        assert outcome.divergence.step == 0
        assert outcome.divergence.stream == "stdout"
        assert outcome.divergence.line == 1

    def test_a_transcript_that_still_agrees_fires_nothing(self) -> None:
        """The anti-vacuity half: the gate is about the output, not about running."""
        record = _transcript()
        assert evidence.compare(record, _replayed(record, "3 file(s) checked.")).ok


def _transcript() -> evidence.EvidenceRecord:
    """One minimal CLI fixture, built here rather than read from a file."""
    return evidence.EvidenceRecord(
        id="example:transcript/sample",
        journey="journey:first-project",
        channel=evidence.CHANNEL_CLI,
        intent="A short path, walked for real.",
        scaffold=evidence.Scaffold(
            kind="new-project",
            argv=("s0ma", "new", "project", "demo"),
            files=(),
            workdir="demo",
        ),
        steps=(
            evidence.CommandStep(
                argv=("s0ma", "check"),
                exit_code=0,
                stdout=(evidence.Expectation(match="line", text="3 file(s) checked."),),
                stderr=(),
            ),
        ),
        covers=("cli:s0ma/check",),
        not_covered=(),
        source="evidence/sample.json",
    )


def _replayed(record: evidence.EvidenceRecord, said: str) -> evidence.Replay:
    """A replay nobody ran: the scaffold line, then one command that said ``said``."""
    return evidence.Replay(
        record_id=record.id,
        observed=(
            evidence.Observed(
                label="# scaffold", streams=(), exit_code=0, structured=None, timed_out=False
            ),
            evidence.Observed(
                label="$ s0ma check",
                streams=(("stdout", said), ("stderr", "")),
                exit_code=0,
                structured=None,
                timed_out=False,
            ),
        ),
        transcript="<captured>",
    )


class TestTeachingSequences:
    """``DOC_SEQUENCE_REPEATS`` — the one constraint only an ordered form carries."""

    def test_a_teaching_order_that_says_one_topic_twice(self) -> None:
        concept = _concept("concept:first-idea", term="first idea")
        sequence = TeachingSequence(
            id="sequence:the-basics",
            steps=(
                TeachingStep(topic=concept.id, purpose="Meet the idea."),
                TeachingStep(topic=concept.id, purpose="Meet it again by mistake."),
            ),
        )
        findings = validate_bundle(_bundle(concepts=(concept,), sequences=(sequence,)))
        found = _located(_one(findings, DOC_SEQUENCE_REPEATS), "")
        assert "step 2" in found.message


# ---------------------------------------------------------------------------
# Authority records
# ---------------------------------------------------------------------------


class TestAuthorityRecords:
    """``DOC_AUTHORITY_MISDECLARED`` and ``DOC_AUTHORITY_CONFLICT``."""

    def test_a_class_that_disagrees_with_its_own_id(self) -> None:
        """C1 repeats the class on the record so a gate can catch exactly this."""
        authority = _authority("authority:spec/negative-fixture", authority_class="adr")
        findings = validate_bundle(_bundle(authorities=(authority,)))
        found = _located(
            _one(findings, DOC_AUTHORITY_MISDECLARED), f"{_AUTHORITY_DOC}#1"
        )
        assert "'adr'" in found.message and "'spec'" in found.message

    def test_a_delegation_handed_up_the_order(self) -> None:
        """Delegation runs down the order; handing one up is already refused."""
        from s0ma_dsl.docs_model.records import AuthorityDelegation

        authority = _authority(
            "authority:adr/negative-fixture",
            authority_class="adr",
            delegates=(
                AuthorityDelegation(
                    domain="wrapping", to_class="prd", stated_in="§1"
                ),
            ),
        )
        findings = validate_bundle(_bundle(authorities=(authority,)))
        found = _located(
            _one(findings, DOC_AUTHORITY_MISDECLARED), f"{_AUTHORITY_DOC}#1"
        )
        assert "up" in found.message

    def test_two_equal_ranked_authorities_over_one_domain(self) -> None:
        """``DOC_AUTHORITY_CONFLICT``: nothing decides, so nothing is decided."""
        left = _authority("authority:spec/left", authority_class="spec")
        right = _authority("authority:spec/right", authority_class="spec")
        document = _document(governed_by=(left.id, right.id))
        findings = validate_bundle(
            _bundle(authorities=(left, right), documents=(document,)),
            claims=(AuthorityClaim(record_id=document.id, domain="wrapping"),),
        )
        found = _located(_one(findings, DOC_AUTHORITY_CONFLICT), "README.md")
        assert left.id in found.message and right.id in found.message


# ---------------------------------------------------------------------------
# Duplicate identity
# ---------------------------------------------------------------------------


class TestDuplicateIdentity:
    """``DOC_CANONICAL_DUPLICATE``, from the merge and from the catalog."""

    def test_two_providers_claim_one_id_with_different_facts(self) -> None:
        """Identical facts merge; a disagreement is a build error and names both."""
        first = Provenance(
            adapter_id="alpha",
            schema_version=SCHEMA,
            source="alpha.json",
            source_sha256="0" * 64,
        )
        second = Provenance(
            adapter_id="beta",
            schema_version=SCHEMA,
            source="beta.json",
            source_sha256="0" * 64,
        )
        registry = ProviderRegistry.of(
            PlantedProvider(
                "alpha",
                _sourced(_concept("concept:first-idea", term="first idea"), first),
            ),
            PlantedProvider(
                "beta",
                _sourced(
                    _concept(
                        "concept:first-idea",
                        term="first idea",
                        summary="A different short form entirely.",
                    ),
                    second,
                ),
            ),
        )
        composition = compose(registry, release_version=RELEASE)
        assert not composition.ok
        found = _located(_one(composition.findings, DOC_CANONICAL_DUPLICATE), "alpha.json")
        assert "alpha" in found.message and "beta" in found.message

    def test_two_catalog_rows_claim_one_canonical_source(self) -> None:
        """One file, one document: two rows would show it twice under two names."""
        rows = (
            _document("doc:guide/readme"),
            _document("doc:guide/readme-again"),
        )
        found = _located(
            _one(check_canonical_sources(rows), DOC_CANONICAL_DUPLICATE), "README.md"
        )
        assert "doc:guide/readme" in found.message


# ---------------------------------------------------------------------------
# Catalog completeness
# ---------------------------------------------------------------------------


class TestCatalogCompleteness:
    """``DOC_DOCUMENT_UNCATALOGED`` — tracked documentation with no row."""

    def test_a_tracked_document_with_no_row_and_no_exclusion(self, tmp_path: Path) -> None:
        catalog = _catalog_tree(tmp_path)
        orphan = "docs/nobody-catalogued-this.md"
        _touch(tmp_path / orphan)
        findings = check_completeness(catalog, ["README.md", orphan])
        found = _located(_one(findings, DOC_DOCUMENT_UNCATALOGED), orphan)
        assert orphan in found.message

    def test_a_reasoned_exclusion_is_not_a_finding(self, tmp_path: Path) -> None:
        """The other half of the rule, so the fixture above proves the gate.

        A silent omission and a reasoned exclusion look the same from
        outside; only one of them is reviewable, and a battery that never
        showed the reviewable one would be proving that the gate fires on
        everything.
        """
        excluded = "docs/not-a-document.md"
        catalog = _catalog_tree(
            tmp_path, excluded=[{"path": excluded, "reason": "A fixture, not a document."}]
        )
        assert check_completeness(catalog, ["README.md", excluded]) == []


# ---------------------------------------------------------------------------
# Anti-vacuity
# ---------------------------------------------------------------------------


class TestVacuity:
    """``DOC_GATE_VACUOUS`` — the failure that passes everything downstream."""

    def test_a_provider_that_produced_less_than_its_floor(self) -> None:
        result = PlantedProvider(
            "negative", _sourced(_concept("concept:first-idea", term="first idea"))
        ).provide()
        findings = validate_bundle(
            _bundle(concepts=(_concept("concept:first-idea", term="first idea"),)),
            results=(result,),
            floors={("negative", "concepts"): 5},
        )
        found = _located(_one(findings, DOC_GATE_VACUOUS), "")
        assert "produced 1 concepts" in found.message

    def test_a_floor_naming_a_provider_that_never_ran(self, tmp_path: Path) -> None:
        """Through the whole application: the floors are what make gates non-optional."""
        result = _planted_build(tmp_path, floors={("nobody", "concepts"): 1})
        found = _located(_one(_in_corpus(result.findings), DOC_GATE_VACUOUS), "")
        assert "did not run" in found.message

    def test_a_sequence_that_teaches_nothing(self) -> None:
        """An empty sequence passes every check it is subject to and teaches no one."""
        sequence = TeachingSequence(id="sequence:the-basics", steps=())
        findings = validate_bundle(_bundle(sequences=(sequence,)))
        found = _located(_one(findings, DOC_GATE_VACUOUS), "")
        assert "teaches nothing" in found.message

    def test_a_build_that_renders_no_artifact(self) -> None:
        """A build that renders nothing passes every byte comparison after it."""
        from s0ma_dsl.docs_model.application import _artifact_floor

        bundle = _planted_build(Path(__file__).parent).bundle
        found = _located(
            _one(_artifact_floor((), bundle), DOC_GATE_VACUOUS), DOCS_ROOT
        )
        assert "rendered 0 artifacts" in found.message

    def test_an_allowance_no_surface_uses(self) -> None:
        """The half that stops a written exception becoming a permanent one.

        A side-effect allowance is a standing permission for one source to
        stay silent. The day that source starts declaring, the permission
        stops matching — and an unmatched permission is indistinguishable
        from one that was never true, which is why it is a finding rather
        than a no-op. Same rule as a floor naming a provider that did not
        run, and the same code.
        """
        findings = check_side_effects(
            _bundle(surfaces=(_surface(),)),
            allowances={("nobody", "cli"): "A source this build never read."},
        )
        found = _located(_one(findings, DOC_GATE_VACUOUS), "")
        assert "no surface in this build used it" in found.message


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


class TestCoverage:
    """``DOC_CONCEPT_UNCOVERED`` and ``DOC_SURFACE_UNCOVERED``.

    The vacuity trap is the point: the *bundle* is the requirement and the
    *index* is what is reachable, and they are allowed to differ. A record
    that composed and that no read surface addresses is exactly the failure,
    so the fixture serves a narrower index than it composed.
    """

    @staticmethod
    def _renderers() -> dict[str, Any]:
        return {"human": render_human, "agent": render_agent}

    def test_a_composed_concept_no_read_surface_addresses(self) -> None:
        concept = _concept("concept:first-idea", term="first idea")
        composed = _bundle(concepts=(concept,))
        served = TopicIndex.of(_bundle())
        findings = check_coverage(composed, renderers=self._renderers(), index=served)
        found = _located(_one(findings, DOC_CONCEPT_UNCOVERED), "")
        assert concept.id in found.message

    def test_a_composed_capability_no_read_surface_addresses(self) -> None:
        surface = _surface()
        composed = _bundle(surfaces=(surface,))
        served = TopicIndex.of(_bundle())
        findings = check_coverage(composed, renderers=self._renderers(), index=served)
        found = _located(_one(findings, DOC_SURFACE_UNCOVERED), FIXTURE_SOURCE)
        assert surface.id in found.message

    def test_the_same_build_served_whole_reports_nothing(self) -> None:
        """The positive control: the gate is about the gap, not about the records."""
        concept = _concept("concept:first-idea", term="first idea")
        composed = _bundle(concepts=(concept,), surfaces=(_surface(),))
        findings = check_coverage(
            composed, renderers=self._renderers(), index=TopicIndex.of(composed)
        )
        assert findings == []


# ---------------------------------------------------------------------------
# Journey coverage (E8)
# ---------------------------------------------------------------------------

_POLICY_SURFACE = "cli:s0ma/init"
_POLICY_REASON = (
    "A written reason long enough to have been thought about: nobody comes to "
    "the product for this, and its reference entry is the whole of what a "
    "reader needs about it."
)


def _policy(
    *,
    capabilities: tuple[PrimaryCapability, ...] = (),
    surfaces: tuple[SurfaceException, ...] = (),
    channels: tuple[ChannelException, ...] = (),
) -> CoveragePolicy:
    """One coverage policy, saying exactly what a test needs it to say."""
    return CoveragePolicy(
        source=FIXTURE_SOURCE,
        capabilities=capabilities,
        surface_exceptions=surfaces,
        channel_exceptions=channels,
    )


def _capability(
    *,
    journeys: tuple[str, ...] = ("journey:first-project",),
    surfaces: tuple[str, ...] = (_POLICY_SURFACE,),
) -> PrimaryCapability:
    """One primary capability, sound unless a test breaks it in one place."""
    return PrimaryCapability(
        id="start-a-project",
        title="Turn a folder into a project the toolchain can check.",
        why_primary=(
            "The first thing anybody does, and the step that decides whether "
            "they do a second one at all."
        ),
        journeys=journeys,
        surfaces=surfaces,
    )


class TestCoveragePolicy:
    """``DOC_CAPABILITY_UNCOVERED``, and the two ways this policy goes vacuous.

    The vacuity trap here is the mirror of :class:`TestCoverage`'s: the
    *policy* is the requirement and the *bundle* is what is actually
    served, and they are allowed to differ in both directions. A
    capability whose journeys have drifted off it and a surface no ledger
    classifies are the two failures that matter, and neither is visible to
    a gate that reads its requirement out of the thing it is checking.
    """

    def test_a_capability_whose_journey_has_been_removed(self) -> None:
        """The journey vanished; the capability still claims it."""
        bundle = _bundle(surfaces=(_surface(_POLICY_SURFACE),))
        findings = check_journey_coverage(
            bundle, _policy(capabilities=(_capability(),))
        )
        found = _located(_one(findings, DOC_CAPABILITY_UNCOVERED), FIXTURE_SOURCE)
        assert "start-a-project" in found.message
        assert "journey:first-project" in found.message
        assert "0 of its 1 declared journeys still walk it" in found.message

    def test_a_journey_that_has_stopped_walking_the_capability(self) -> None:
        """The journey is still there and no longer goes anywhere near it."""
        bundle = _bundle(
            surfaces=(_surface(_POLICY_SURFACE), _surface("cli:s0ma/check")),
            journeys=(_journey(steps=(_step("cli:s0ma/check"),)),),
        )
        findings = check_journey_coverage(
            bundle,
            _policy(
                capabilities=(_capability(),),
                surfaces=(
                    SurfaceException(surface="cli:s0ma/check", reason=_POLICY_REASON),
                ),
            ),
        )
        found = _located(_one(findings, DOC_CAPABILITY_UNCOVERED), FIXTURE_SOURCE)
        assert "walks none of its surfaces" in found.message

    def test_a_recovery_path_counts_as_walking_it(self) -> None:
        """The control for the rule above: a branch is a path a reader is on."""
        bundle = _bundle(
            surfaces=(_surface(_POLICY_SURFACE, errors=("NOT_BUILT",)),),
            journeys=(
                _journey(
                    steps=(_step(_POLICY_SURFACE),),
                    recovery_paths=(
                        RecoveryPath(
                            when="NOT_BUILT",
                            action="Build it once, then come back to this step.",
                            next_surface=_POLICY_SURFACE,
                        ),
                    ),
                ),
            ),
        )
        assert check_journey_coverage(bundle, _policy(capabilities=(_capability(),))) == []

    def test_a_served_surface_no_ledger_classifies(self) -> None:
        """The completeness half: a new capability nobody has decided about."""
        bundle = _bundle(surfaces=(_surface("cli:s0ma/brand-new"),))
        findings = check_journey_coverage(bundle, _policy())
        found = _located(_one(findings, DOC_CAPABILITY_UNCOVERED), FIXTURE_SOURCE)
        assert "cli:s0ma/brand-new" in found.message
        assert "has not said whether" in found.message

    def test_a_capability_a_channel_ruling_has_swallowed(self) -> None:
        """Claimed and excused at once, in the form only the bundle can see."""
        bundle = _bundle(
            surfaces=(_surface(_POLICY_SURFACE),),
            journeys=(_journey(steps=(_step(_POLICY_SURFACE),)),),
        )
        findings = check_journey_coverage(
            bundle,
            _policy(
                capabilities=(_capability(),),
                channels=(ChannelException(channel="cli", reason=_POLICY_REASON),),
            ),
        )
        found = _located(_one(findings, DOC_CAPABILITY_UNCOVERED), FIXTURE_SOURCE)
        assert "claimed by a primary capability and excused" in found.message

    def test_a_capability_serving_a_surface_nothing_serves(self) -> None:
        """A stale claim resolves to nothing, which is the resolver's word for it."""
        bundle = _bundle(
            surfaces=(_surface(_POLICY_SURFACE),),
            journeys=(_journey(steps=(_step(_POLICY_SURFACE),)),),
        )
        findings = check_journey_coverage(
            bundle,
            _policy(
                capabilities=(
                    _capability(surfaces=("cli:s0ma/gone", _POLICY_SURFACE)),
                ),
            ),
        )
        found = _located(_one(findings, DOC_TOPIC_UNRESOLVED), FIXTURE_SOURCE)
        assert "cli:s0ma/gone" in found.message

    def test_an_exception_for_a_surface_this_build_does_not_serve(self) -> None:
        """The self-expiring half: the gap it excused may already be closed."""
        findings = check_journey_coverage(
            _bundle(),
            _policy(
                surfaces=(SurfaceException(surface=_POLICY_SURFACE, reason=_POLICY_REASON),)
            ),
        )
        found = _located(_one(findings, DOC_GATE_VACUOUS), FIXTURE_SOURCE)
        assert _POLICY_SURFACE in found.message

    def test_a_channel_ruling_no_surface_uses(self) -> None:
        """The same rule over the other ledger: a ruling about nothing."""
        findings = check_journey_coverage(
            _bundle(),
            _policy(channels=(ChannelException(channel="rest", reason=_POLICY_REASON),)),
        )
        found = _located(_one(findings, DOC_GATE_VACUOUS), FIXTURE_SOURCE)
        assert "'rest'" in found.message

    def test_a_policy_that_matches_its_build_reports_nothing(self) -> None:
        """The positive control: the gate is about the gap, not about the policy."""
        bundle = _bundle(
            surfaces=(
                _surface(_POLICY_SURFACE),
                _surface("cli:s0ma/topo"),
                _surface("diagnostic:PARSE_ERROR", channel="diagnostic", side_effects=("none",)),
            ),
            journeys=(_journey(steps=(_step(_POLICY_SURFACE),)),),
        )
        findings = check_journey_coverage(
            bundle,
            _policy(
                capabilities=(_capability(),),
                surfaces=(SurfaceException(surface="cli:s0ma/topo", reason=_POLICY_REASON),),
                channels=(ChannelException(channel="diagnostic", reason=_POLICY_REASON),),
            ),
        )
        assert findings == []

    def test_the_empty_policy_over_an_empty_build_is_silent(self) -> None:
        """What every planted build in this module is handed, proved neutral."""
        assert check_journey_coverage(_bundle(), _policy()) == []


# ---------------------------------------------------------------------------
# The bounded channel
# ---------------------------------------------------------------------------


class TestTheBoundedChannel:
    """``DOC_TOPIC_OVERSIZED`` — an answer that does not fit its channel."""

    def test_an_answer_that_does_not_fit_the_channel(self) -> None:
        """The finding has to name the field, because the renderer may not shorten it."""
        oversized = (
            "A short form that is not short, written out at length so that the "
            "answer this channel produces cannot fit inside the budget it "
            "declares, which is the whole thing the budget exists to notice. "
            "The channel repeats a fact word for word and has no shorter "
            "version of it to send, so an answer only gets smaller when the "
            "writing does, and this sentence keeps going for exactly as long "
            "as it takes to make that arithmetic true rather than theoretical. "
            "A budget with no fixture over it is a number nobody has ever seen "
            "refuse anything, which is the same as having no budget at all."
        )
        concept = _concept("concept:first-idea", term="first idea", summary=oversized)
        bundle = _bundle(concepts=(concept,))
        view = facts_of(bundle, concept)
        found = _located(
            _one(check_budget(view, render_agent(view)), DOC_TOPIC_OVERSIZED), ""
        )
        assert "summary" in found.message
        assert "summary" in found.remediation

    def test_the_same_topic_written_short_fits(self) -> None:
        """The positive control, so the fixture above is about the writing."""
        concept = _concept("concept:first-idea", term="first idea")
        bundle = _bundle(concepts=(concept,))
        view = facts_of(bundle, concept)
        assert check_budget(view, render_agent(view)) == []


# ---------------------------------------------------------------------------
# Concept relations, over a composed bundle
# ---------------------------------------------------------------------------


class TestConceptRelations:
    """The two things a concept-to-concept edge can be wrong about."""

    def test_a_relation_naming_a_concept_nobody_wrote(self) -> None:
        """``DOC_CONCEPT_UNRESOLVED``, from the gate that runs after composition."""
        concept = _concept(
            "concept:first-idea",
            term="first idea",
            related=(("requires", "concept:nobody-wrote-this"),),
        )
        findings = check_concept_relations(_bundle(concepts=(concept,)))
        found = _located(_one(findings, DOC_CONCEPT_UNRESOLVED), "")
        assert "concept:nobody-wrote-this" in found.message

    def test_a_symmetric_relation_one_sided_across_the_bundle(self) -> None:
        """``DOC_RELATION_ONE_SIDED``: an edge visible from one end only."""
        left = _concept(
            "concept:first-idea",
            term="first idea",
            related=(("contrasts-with", "concept:second-idea"),),
        )
        right = _concept("concept:second-idea", term="second idea")
        findings = check_concept_relations(_bundle(concepts=(left, right)))
        found = _located(_one(findings, DOC_RELATION_ONE_SIDED), "")
        assert left.id in found.message and right.id in found.message


# ---------------------------------------------------------------------------
# The authored concepts file
# ---------------------------------------------------------------------------


class TestTheAuthoredConceptsFile:
    """The three codes the C5a loader reports about the file it just read."""

    def test_the_base_file_is_clean(self, tmp_path: Path) -> None:
        """Every fixture below differs from this one in exactly one place."""
        provider = _concepts_tree(tmp_path)
        assert provider.findings() == ()
        assert provider.provide().records

    def test_a_pin_that_no_longer_matches_the_file(self, tmp_path: Path) -> None:
        """``DOC_AUTHORITY_STALE``: cited, pinned, and changed since."""

        def stale(document: dict[str, Any]) -> None:
            document["sources"][0]["sha256"] = "0" * 64

        provider = _concepts_tree(tmp_path, stale)
        found = _located(_one(provider.findings(), DOC_AUTHORITY_STALE), _AUTHORITY_DOC)
        assert _AUTHORITY.id in found.message
        assert "re-read" in found.remediation

    def test_a_word_the_product_voice_does_not_use(self, tmp_path: Path) -> None:
        """``DOC_VOICE_VIOLATION``, reaching authored prose and nothing else.

        The forbidden word is read out of the gate's own table rather than
        written here, so this fixture cannot drift from the vocabulary it is
        testing — and this file never contains a forbidden literal of its
        own, which is the same self-excluding trick the gate uses.
        """
        word = FORBIDDEN_IN_AUTHORED_PROSE[0][0]

        def voice(document: dict[str, Any]) -> None:
            document["records"][0]["summary"] = f"A short form that says {word}."

        provider = _concepts_tree(tmp_path, voice)
        found = _located(
            _one(provider.findings(), DOC_VOICE_VIOLATION), f"{_CONCEPTS_FILE}#/records/0"
        )
        assert word in found.message
        assert "summary" in found.message

    def test_a_symmetric_relation_declared_from_one_end(self, tmp_path: Path) -> None:
        """``DOC_RELATION_ONE_SIDED`` at the file, located at the file."""

        def one_sided(document: dict[str, Any]) -> None:
            document["records"][1]["related_concepts"] = []

        provider = _concepts_tree(tmp_path, one_sided)
        found = _located(
            _one(provider.findings(), DOC_RELATION_ONE_SIDED), _CONCEPTS_FILE
        )
        assert "concept:first-idea" in found.message
        assert "concept:second-idea" in found.message


# ---------------------------------------------------------------------------
# The application: planted failures and output drift
# ---------------------------------------------------------------------------


class TestPlantedFailureThroughTheApplication:
    """C8's seam: a caller brings its own composition and every gate runs."""

    def test_the_base_build_is_clean(self, tmp_path: Path) -> None:
        """The control: nothing wrong with the corpus this file plants into.

        Not ``result.ok`` since F3–F5: four of the declared outputs are
        about a workspace and one is about the concepts, and a temp
        directory has neither — see :data:`_OFF_WORKSPACE`. What has to be
        empty is everything else, which is what makes every red below a
        statement about the one change that test planted.
        """
        result = _planted_build(tmp_path)
        assert _in_corpus(result.findings) == (), [
            item.rendered() for item in _in_corpus(result.findings)
        ]
        assert result.artifacts

    def test_a_planted_provider_fails_the_build(self, tmp_path: Path) -> None:
        """``DOC_TOPIC_UNRESOLVED`` raised by ``build``, not by a gate called by hand."""
        planted = ProviderRegistry.of(
            PlantedProvider(
                "negative",
                _sourced(_AUTHORITY),
                _sourced(
                    _concept(
                        "concept:first-idea",
                        term="first idea",
                        governed_by=("authority:adr/nobody-emits-this",),
                    )
                ),
            )
        )
        result = _planted_build(tmp_path, providers=planted)
        assert not result.ok
        found = _located(_one(result.findings, DOC_TOPIC_UNRESOLVED), "")
        assert "authority:adr/nobody-emits-this" in found.message

    def test_two_faults_are_two_findings_rather_than_the_first(self, tmp_path: Path) -> None:
        """Findings are collected. An author should see the whole report."""
        planted = ProviderRegistry.of(
            PlantedProvider(
                "negative",
                _sourced(_AUTHORITY),
                _sourced(
                    _concept(
                        "concept:first-idea",
                        term="first idea",
                        governed_by=("authority:adr/absent-one",),
                    )
                ),
                _sourced(
                    _concept(
                        "concept:second-idea",
                        term="second idea",
                        governed_by=("authority:adr/absent-two",),
                    )
                ),
            )
        )
        result = _planted_build(tmp_path, providers=planted)
        assert len(_of(result.findings, DOC_TOPIC_UNRESOLVED)) == 2
        assert result.artifacts, "a failing composition is still rendered, so every gate runs"


class TestOutputDrift:
    """``DOC_OUTPUT_DRIFT`` — a generated artifact that is not what the build renders."""

    def test_a_hand_edited_artifact_is_named_line_by_line(self, tmp_path: Path) -> None:
        result = _planted_build(tmp_path)
        base = tmp_path / "out"
        write(result, base)
        assert check(result, base) == ()

        committed = base / Path(SNAPSHOT_OUTPUT)
        lines = committed.read_text(encoding="utf-8").split("\n")
        edited = next(
            index for index, line in enumerate(lines) if '"release_version"' in line
        )
        lines[edited] = lines[edited].replace(RELEASE, "9.9.9")
        committed.write_text("\n".join(lines), encoding="utf-8", newline="\n")

        findings = check(result, base)
        found = _located(
            _one(findings, DOC_OUTPUT_DRIFT), f"{DOCS_ROOT}/{SNAPSHOT_OUTPUT}"
        )
        assert f"line {edited + 1} differs" in found.message
        assert "9.9.9" in found.message

    def test_a_declared_output_nobody_has_written(self, tmp_path: Path) -> None:
        """A declared output nobody has written is an unfinished build, not a clean one.

        Every declared output, not the first: D6 took the application from
        one artifact to six, and a check that reported only one missing
        file would leave five to be discovered one run at a time.
        """
        result = _planted_build(tmp_path)
        findings = check(result, tmp_path / "never" / "written")
        assert [item.code for item in findings] == [DOC_OUTPUT_DRIFT] * len(
            result.artifacts
        )
        assert {item.location for item in findings} == {
            f"{DOCS_ROOT}/{item.relative}" for item in result.artifacts
        }
        for finding in findings:
            assert "never been written" in finding.message
        assert f"{DOCS_ROOT}/{SNAPSHOT_OUTPUT}" in {
            item.location for item in findings
        }

    def test_check_mode_wrote_nothing(self, tmp_path: Path) -> None:
        """SDA-INV-9, re-proved here: the drift fixtures must not write to check."""
        result = _planted_build(tmp_path)
        base = tmp_path / "untouched"
        assert check(result, base)
        assert not base.exists()


# ---------------------------------------------------------------------------
# DOC_VERSION_MISMATCH — one manifest, one build, one version (H1)
# ---------------------------------------------------------------------------


def _artifact_record(
    relative: str = "reference/cli.md",
    *,
    release_version: str = RELEASE,
    source_snapshot: str = "sha256:0000000000000000",
    build_channel: str = PREVIEW_CHANNEL,
) -> ArtifactRecord:
    """One well-formed manifest row, ready to be broken in one place."""
    return ArtifactRecord(
        id=artifact_id(relative),
        format="markdown",
        source_document="",
        path_or_uri=f"docs/{relative}",
        content_hash="sha256:1111111111111111",
        release_version=release_version,
        source_snapshot=source_snapshot,
        build_channel=build_channel,
    )


def _manifest(
    *,
    product_version: str = RELEASE,
    build_channel: str = PREVIEW_CHANNEL,
    snapshot_hash: str = "sha256:0000000000000000",
    packages: tuple[tuple[str, str], ...] = (("s0ma-core", RELEASE),),
    schemas: tuple[tuple[str, str], ...] = (("negative", SCHEMA),),
    artifacts: tuple[ArtifactRecord, ...] = (),
) -> DocsManifest:
    """One manifest that agrees with itself unless a caller breaks it.

    Built by hand rather than through
    :func:`~s0ma_dsl.docs_model.manifest.manifest_of`, and deliberately:
    the composer produces a *consistent* manifest by construction, so a
    battery that could only build one through it could never present the
    gate with the state it exists to catch. Every fixture below is a
    manifest that a real mixed build would produce and this one cannot.
    """
    return DocsManifest(
        schema=SCHEMA,
        product_version=product_version,
        build_channel=build_channel,
        source_commit="sha256:2222222222222222",
        package_versions=tuple(
            PackageVersion(distribution=name, version=version)
            for name, version in packages
        ),
        provider_schemas=tuple(
            ProviderSchema(provider_id=name, schema_version=version)
            for name, version in schemas
        ),
        source_hashes=(SourceHash(source=FIXTURE_SOURCE, sha256="0" * 64),),
        snapshot_hash=snapshot_hash,
        artifacts=artifacts,
    )


class TestTheReleaseCurrency:
    """``DOC_VERSION_MISMATCH`` — architecture §11's row, armed at H1.

    Every fixture here is a manifest that is internally wrong in exactly
    one way, because that is the only way to tell which rule fired.
    """

    def test_a_manifest_that_agrees_with_itself_is_quiet(self) -> None:
        """The precondition. A gate that fires on a healthy input proves nothing."""
        assert check_manifest(_manifest(artifacts=(_artifact_record(),))) == []

    def test_a_preview_artifact_inside_a_release_manifest(self) -> None:
        """The acceptance case §13.2 cares about most.

        Both sides carry the same version, so nothing that compares only
        version numbers can see this: it is a preview page shipped as
        installed release documentation, and the channel is the only field
        that says so.
        """
        manifest = _manifest(
            build_channel=RELEASE_CHANNEL,
            artifacts=(_artifact_record(build_channel=PREVIEW_CHANNEL),),
        )
        findings = check_manifest(manifest)
        assert [finding.code for finding in findings] == [DOC_VERSION_MISMATCH]
        assert findings[0].location == "docs/reference/cli.md"
        assert "preview" in findings[0].message
        assert "release manifest" in findings[0].message

    def test_an_artifact_that_represents_another_version(self) -> None:
        """The version-switch case: one build's manifest, another's page."""
        manifest = _manifest(
            product_version="0.0.0",
            artifacts=(_artifact_record(release_version="9.9.9"),),
        )
        findings = check_manifest(manifest)
        assert [finding.code for finding in findings] == [DOC_VERSION_MISMATCH]
        assert "9.9.9" in findings[0].message
        assert "0.0.0" in findings[0].message

    def test_an_artifact_rendered_from_another_build(self) -> None:
        """Two snapshot digests in one manifest — two builds, mixed.

        Version numbers cannot catch this one at all: both builds can be
        of the same version, and often are.
        """
        manifest = _manifest(
            artifacts=(_artifact_record(source_snapshot="sha256:aaaaaaaaaaaaaaaa"),),
        )
        findings = check_manifest(manifest)
        assert [finding.code for finding in findings] == [DOC_VERSION_MISMATCH]
        assert "sha256:aaaaaaaaaaaaaaaa" in findings[0].message

    def test_a_historical_artifact_may_differ_and_says_so(self) -> None:
        """§11's declared exception, and the whole of it.

        "Represents another version *without historical status*" — so an
        artifact that declares itself historical is allowed to carry its
        own version and its own snapshot. That is what an immutable older
        snapshot is, and refusing it would make the third channel §13.2
        defines impossible to publish.
        """
        assert (
            check_manifest(
                _manifest(
                    build_channel=RELEASE_CHANNEL,
                    artifacts=(
                        _artifact_record(
                            release_version="0.9.0",
                            source_snapshot="sha256:bbbbbbbbbbbbbbbb",
                            build_channel=HISTORICAL_CHANNEL,
                        ),
                    ),
                )
            )
            == []
        )

    def test_a_distribution_that_broke_the_lockstep(self) -> None:
        """PRD INV-4: four wheels, one version, or the release is not one."""
        manifest = _manifest(
            packages=(("s0ma-core", RELEASE), ("s0ma-mcp", "0.17.0")),
        )
        findings = check_manifest(manifest)
        assert [finding.code for finding in findings] == [DOC_VERSION_MISMATCH]
        assert "s0ma-mcp" in findings[0].message

    def test_a_provider_emitting_against_an_older_model(self) -> None:
        """The comparison C2 deliberately left to this milestone."""
        manifest = _manifest(schemas=(("lagging", "s0ma-docs-model@0"),))
        findings = check_manifest(manifest)
        assert [finding.code for finding in findings] == [DOC_VERSION_MISMATCH]
        assert "lagging" in findings[0].message

    def test_a_channel_word_nothing_defines(self) -> None:
        """A fourth channel is not a stricter one; it is an unreadable one."""
        assert [
            finding.code for finding in check_manifest(_manifest(build_channel="nightly"))
        ] == [DOC_VERSION_MISMATCH]
        assert [
            finding.code
            for finding in check_manifest(
                _manifest(artifacts=(_artifact_record(build_channel="nightly"),))
            )
        ] == [DOC_VERSION_MISMATCH]

    def test_a_manifest_assembled_from_another_bundle(self) -> None:
        """The third side of the triangle: the stamp the artifacts came from.

        All three of the stamp's identity facts are compared, because a
        manifest built beside a different composition can disagree on any
        one of them and the caller would see a manifest that is internally
        perfect.
        """
        stamp = BuildStamp(
            schema=SCHEMA,
            release_version="9.9.9",
            snapshot_hash="sha256:cccccccccccccccc",
            build_channel=RELEASE_CHANNEL,
        )
        findings = check_manifest(_manifest(), stamp=stamp)
        assert {finding.code for finding in findings} == {DOC_VERSION_MISMATCH}
        assert len(findings) == 3


# ---------------------------------------------------------------------------
# Gates that are deliberately not armed yet
# ---------------------------------------------------------------------------


class TestDeferredGates:
    """The codes named in the source and fired by nothing, with their reasons.

    Recorded rather than omitted. A code nobody can fire and nobody has
    written down is indistinguishable from a code somebody forgot, and the
    milestone that arms one of these turns the completeness audit red, which
    is exactly the signal I2 wants.
    """

    def test_every_deferred_code_says_what_it_waits_for(self) -> None:
        for code, reason in DEFERRED_GATES.items():
            assert code.startswith("DOC_"), code
            assert reason.strip(), f"{code} is deferred and does not say why"

    def test_exactly_this_one_gate_remains_deferred(self) -> None:
        """The set itself is pinned, and the reason is which way is cheaper.

        The completeness audit is satisfied by *either* a fixture or a
        deferral, so a deferral is the cheap way to quiet it: a code
        added to ``DEFERRED_GATES`` needs one sentence, and a code given
        a fixture needs a gate that really fires. Nothing above can tell
        those apart. This can, and it is the only thing that does — an
        arming or a deferral now changes a list somebody has to look at.

        One remains. ``DOC_COVERAGE_UNMENTIONED`` needs prose no renderer
        reads before F. D5b armed ``DOC_SIDE_EFFECT_UNDECLARED``, and H1
        armed ``DOC_VERSION_MISMATCH`` over the documentation manifest —
        which is what turning this test red is for.
        """
        assert sorted(DEFERRED_GATES) == ["DOC_COVERAGE_UNMENTIONED"]
        assert "F." in DEFERRED_GATES["DOC_COVERAGE_UNMENTIONED"]
        assert DOC_VERSION_MISMATCH in FIXTURES

    def test_no_deferred_code_claims_a_fixture(self) -> None:
        """The two halves of the universe do not overlap."""
        overlap = sorted(set(FIXTURES) & set(DEFERRED_GATES))
        assert overlap == [], (
            f"{overlap} are recorded both as deferred and as fired. If a gate has "
            f"armed, drop it from validate.DEFERRED_GATES; if it has not, drop the "
            f"fixture claim."
        )


# ---------------------------------------------------------------------------
# The completeness self-audits (T2)
# ---------------------------------------------------------------------------


class TestTheBatteryIsComplete:
    """What I2 re-runs: the table against the source tree, and against itself."""

    def test_the_code_universe_is_read_from_the_source_tree(self) -> None:
        """The audit's own precondition: the grep found a source tree to read."""
        assert DOCS_MODEL_SOURCE.is_dir()
        assert len(sorted(DOCS_MODEL_SOURCE.glob("*.py"))) >= 10
        assert len(CODE_UNIVERSE) >= len(FIXTURES)

    def test_every_diagnostic_in_the_source_tree_has_a_fixture_or_a_reason(self) -> None:
        """The completeness claim. A code with neither turns this red by name."""
        accounted = set(FIXTURES) | set(DEFERRED_GATES)
        unclaimed = sorted(CODE_UNIVERSE - accounted)
        assert unclaimed == [], (
            f"{unclaimed} appear in the docs_model source tree and this battery "
            f"neither fires them nor records them as deferred. Add a fixture to "
            f"this module and a row to FIXTURES."
        )

    def test_the_battery_claims_nothing_the_source_tree_does_not_name(self) -> None:
        """The other direction: a fixture for a code that has been retired."""
        stale = sorted((set(FIXTURES) | set(DEFERRED_GATES)) - CODE_UNIVERSE)
        assert stale == [], (
            f"{stale} are claimed here and appear nowhere in the docs_model source "
            f"tree. Either the code was renamed or retired — remove the row and "
            f"the fixture with it."
        )

    def test_every_mapped_test_exists_in_this_module(self) -> None:
        """A renamed test is a broken table, and a broken table is a false report."""
        missing: list[str] = []
        for code, names in sorted(FIXTURES.items()):
            assert names, f"{code} maps to no test at all"
            for name in names:
                class_name, _, method = name.partition(".")
                owner = globals().get(class_name)
                if owner is None or not callable(getattr(owner, method, None)):
                    missing.append(f"{code} -> {name}")
        assert missing == [], (
            f"the completeness table names tests this module does not have: "
            f"{missing}"
        )

    def test_every_fixture_test_this_module_has_is_in_the_table(self) -> None:
        """The reverse: a negative fixture nobody recorded is coverage nobody can audit.

        Only the tests that *fire* a diagnostic are in the table, so the
        positive controls, the deferral proofs and these audits are named
        here as the deliberate exceptions rather than left to a guess.
        """
        claimed = {name for names in FIXTURES.values() for name in names}
        exempt = {
            "TestCatalogCompleteness.test_a_reasoned_exclusion_is_not_a_finding",
            "TestCoverage.test_the_same_build_served_whole_reports_nothing",
            "TestCoveragePolicy.test_a_recovery_path_counts_as_walking_it",
            "TestCoveragePolicy.test_a_policy_that_matches_its_build_reports_nothing",
            "TestCoveragePolicy.test_the_empty_policy_over_an_empty_build_is_silent",
            "TestSideEffects.test_a_source_allowed_to_be_silent_is_not_a_finding",
            "TestSideEffects.test_the_vocabulary_the_providers_refuse_against_is_the_model_s",
            "TestTheBoundedChannel.test_the_same_topic_written_short_fits",
            "TestTheAuthoredConceptsFile.test_the_base_file_is_clean",
            "TestOutputDrift.test_check_mode_wrote_nothing",
            "TestJourneys.test_the_same_order_the_other_way_round_is_clean",
            "TestJourneys.test_a_prerequisite_declared_as_already_known_is_the_other_answer",
            "TestJourneys.test_a_step_surfaces_own_declared_error_answers_the_recovery",
            "TestJourneys.test_a_registered_diagnostic_answers_it_too",
            "TestJourneys.test_no_resolver_asks_no_question",
            "TestEvidence.test_a_transcript_that_still_agrees_fires_nothing",
            "TestJourneys.test_the_repeated_relation_word_is_the_one_the_loader_declares",
            "TestPlantedFailureThroughTheApplication.test_the_base_build_is_clean",
            "TestPlantedFailureThroughTheApplication."
            "test_two_faults_are_two_findings_rather_than_the_first",
            "TestTheReleaseCurrency.test_a_manifest_that_agrees_with_itself_is_quiet",
            "TestTheReleaseCurrency.test_a_historical_artifact_may_differ_and_says_so",
        }
        found: set[str] = set()
        for class_name, owner in sorted(globals().items()):
            if not (isinstance(owner, type) and class_name.startswith("Test")):
                continue
            if class_name in {"TestDeferredGates", "TestTheBatteryIsComplete"}:
                continue
            found.update(
                f"{class_name}.{method}" for method in vars(owner) if method.startswith("test_")
            )
        unrecorded = sorted(found - claimed - exempt)
        assert unrecorded == [], (
            f"these tests are in the battery and in no row of FIXTURES: "
            f"{unrecorded}. Either they fire a diagnostic — record it — or they "
            f"are a control, in which case name them in the exempt set."
        )

    def test_one_code_has_one_spelling_wherever_it_is_raised(self) -> None:
        """Four codes are defined in two modules each; the strings must agree."""
        from s0ma_dsl.docs_model import providers_catalog, resolve, validate

        assert providers_catalog.DOC_CANONICAL_DUPLICATE == DOC_CANONICAL_DUPLICATE
        assert providers_catalog.DOC_TOPIC_UNRESOLVED == DOC_TOPIC_UNRESOLVED
        assert resolve.DOC_TOPIC_UNRESOLVED == DOC_TOPIC_UNRESOLVED
        assert validate.DOC_GATE_VACUOUS == DOC_GATE_VACUOUS

    @pytest.mark.parametrize("code", sorted(FIXTURES))
    def test_each_fired_code_is_a_diagnostic_name(self, code: str) -> None:
        """A row whose key is not a ``DOC_*`` name is a typo the audit would trust."""
        assert _CODE_NAME.fullmatch(code), code
