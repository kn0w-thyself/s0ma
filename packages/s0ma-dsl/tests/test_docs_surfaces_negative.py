"""The canonical negative battery for the Phase D surface providers.

Milestone D8 of the docs-function plan (internal) §9, the D-phase sibling of
C9's ``test_docs_model_negative.py``. C9 answers architecture plan §16.3
for the gates that were live at the end of Phase C; this module answers it
for what Phase D added — five surface providers, five id forms, the
derived-source registry, the armed ``DOC_SIDE_EFFECT_UNDECLARED`` with its
self-expiring allowances, the binding policy, and D6's inventories with
their ``DOC_SURFACE_UNCOVERED`` teeth.

**The contract, inherited from C9 and extended.**

1. *Every failure class Phase D added has a fixture here that reaches the
   real machinery.* Not a constructed :class:`Finding` asserting its own
   handiwork — a fixture fed through the gate, so the proof is that the
   gate fires.
2. *Every fixture asserts the diagnostic id, the source location exactly,
   and that remediation text is present.* A gate that says only "no" is a
   gate people learn to disable.
3. *The completeness table is derived, never written down.*
   :data:`FIXTURES` maps a diagnostic to the test(s) here that fire it, and
   the self-audits diff it against a code universe grepped out of the
   source tree at test time.
4. **The two-battery handshake (T3).** C9's audit is satisfied by *either*
   a fixture or a deferral, and it reads only its own table — so on the day
   a code's only proof moves from one battery to the other, nothing would
   notice. :class:`TestTheTwoBatteriesAccountForEveryCode` closes that: it
   reads C9's table out of C9's *source* with :mod:`ast` — never by
   importing it — and pins the three-way split of the universe. The
   overlap and the D8-only claim are written down as
   :data:`SHARED_WITH_C9` and :data:`CLAIMED_ONLY_HERE`, and both are
   compared against what the two tables actually say, so neither battery
   can quietly start assuming the other covers a code.

**Live-boundary parity (T2).** One class per provider, each reading the
boundary *independently of the provider under test* — a second parser
walked here, the severity matrix imported as live objects rather than
parsed, the project loader's key set observed by instrumenting the table it
is handed, a server listing asked over the SDK, and ``ROUTE_TABLE`` read
straight out of the committed build. A provider that drifts from the thing
it describes fails here; a provider compared against its own reading could
not.

**Why the D-phase reds are re-proved rather than imported.** Every one of
the five provider suites already proves its own refusals. This module
re-proves the *classes* through its own minimal fixtures for C9's reason: a
battery that imports another test module cannot be run against a future
tree on its own, and duplicated proof is cheap.

**No committed fixture files, deliberately** — the C9 precedent, kept.
Every T1 fixture is built into ``tmp_path`` or is a literal in this module:
no repository checkout, no git, no network, no wall clock, so two runs
report identically. The T2 parity tests are the deliberate exception and
could not be anything else: their whole subject is the live tree.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import dataclasses
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import s0ma_dsl.docs_model as docs_model
from s0ma_dsl.codegen.doc_emitter import derived_sources
from s0ma_dsl.codegen.doc_emitter.derived_sources import (
    DOC_SOURCE_FORMAT_UNSUPPORTED,
    SUPPORTED_DOC_FORMATS,
    DerivedField,
    DerivedFieldKind,
    DerivedInput,
    DerivedRecordSet,
    DerivedSource,
    records_for,
    register,
)
from s0ma_dsl.codegen.doc_emitter.renderer import DocRenderError
from s0ma_dsl.docs_model.application import (
    APPLICATION_FLOORS,
    BOUND_CLASSES,
    DOC_GATE_VACUOUS,
    DOC_OUTPUT_DRIFT,
    DOCS_ROOT,
    SIDE_EFFECT_ALLOWANCES,
    SURFACES_INDEX_OUTPUT,
    SURFACES_INVENTORY_OUTPUT,
    UNBOUND_CEILING,
    UNREGISTERED_HANDLERS,
    Build,
    build,
    check,
    check_surface_index,
    coverage_policy,
    write,
)
from s0ma_dsl.docs_model.ids import (
    ID_FORMS,
    DocsIdError,
    id_form,
    is_valid_id,
    studi0_action_id,
    studi0_public_name,
)
from s0ma_dsl.docs_model.inventories import surfaces_index
from s0ma_dsl.docs_model.providers import (
    Finding,
    ProviderRegistry,
    ProviderResult,
    SourcedRecord,
    sort_records,
)
from s0ma_dsl.docs_model.providers_cli import FLOORS as CLI_FLOORS
from s0ma_dsl.docs_model.providers_cli import (
    UNBOUND_MACHINERY,
    CliProvider,
)
from s0ma_dsl.docs_model.providers_config import CONFIG_FLOORS, ConfigProvider, config_id
from s0ma_dsl.docs_model.providers_diagnostics import (
    DIAGNOSTIC_FLOORS,
    NOT_APPLICABLE,
    DiagnosticsProvider,
    diagnostic_id,
    severity_of,
)
from s0ma_dsl.docs_model.providers_mcp import (
    MCP_FLOORS,
    SNAPSHOT_SOURCE,
    McpProvider,
    McpSurfaceDisagreementError,
)
from s0ma_dsl.docs_model.providers_studi0 import FLOORS as STUDI0_FLOORS
from s0ma_dsl.docs_model.providers_studi0 import (
    SERVER_SOURCE,
    Studi0Provider,
)
from s0ma_dsl.docs_model.records import (
    SCHEMA,
    BuildStamp,
    DocsBundle,
    Provenance,
    SurfaceRecord,
)
from s0ma_dsl.docs_model.resolve import (
    DOC_CAPABILITY_UNCOVERED,
    DOC_SURFACE_UNCOVERED,
    ChannelException,
    CoveragePolicy,
)
from s0ma_dsl.docs_model.serialize import stamped
from s0ma_dsl.docs_model.validate import (
    CHANNEL_EFFECTS,
    DEFERRED_GATES,
    DOC_SIDE_EFFECT_UNDECLARED,
    DOC_SURFACE_UNBOUND,
    check_floors,
    check_side_effects,
    validate_bundle,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    #: What the ``registered`` fixture hands a test: a function that adds
    #: one fixture source to the registry and takes it out again at
    #: teardown. Declared here because nothing evaluates it at run time.
    RegisterSource = Callable[[DerivedSource], DerivedSource]

REPO_ROOT = Path(__file__).resolve().parents[3]

#: C9's battery, as a path. Read as *source*, never imported: C9's own
#: docstring gives the reason a battery must not import a sibling, and the
#: handshake would be worth nothing if it ran C9's module to learn what C9
#: claims. :mod:`ast` reads the table without executing a line of it.
C_PHASE_BATTERY = Path(__file__).resolve().parent / "test_docs_model_negative.py"

#: The release a fixture bundle is stamped with. Fixed, never derived from
#: the installed version — C9's rule, for C9's reason.
RELEASE = "0.0.0"

#: What every fixture record was "read from": this module, which is where
#: they are really written. One string, so a test asserts a finding's
#: location by equality rather than by substring.
FIXTURE_SOURCE = "packages/s0ma-dsl/tests/test_docs_surfaces_negative.py"

_PROVENANCE = Provenance(
    adapter_id="d8",
    schema_version=SCHEMA,
    source=FIXTURE_SOURCE,
    source_sha256="0" * 64,
)


# ---------------------------------------------------------------------------
# The completeness table (T3)
# ---------------------------------------------------------------------------

#: Diagnostic → the test(s) in *this* module that deliberately fire it.
#: Same shape as C9's table and audited the same way, so the two can be
#: compared without either importing the other.
#:
#: This is not a second copy of C9's coverage. Every row here is either a
#: *second firing site* for a code C9 proves elsewhere — the composed-path
#: ``DOC_SURFACE_UNCOVERED`` in ``application.check_surface_index``, which
#: is a different gate from ``resolve.check_coverage`` reached by a
#: different path — or a D-phase shape of a gate C9 proved on C-phase
#: records.
FIXTURES: Mapping[str, tuple[str, ...]] = {
    DOC_CAPABILITY_UNCOVERED: (
        "TestASurfaceNoLedgerClassifies.test_a_newly_served_tool_lands_in_neither_ledger",
        "TestASurfaceNoLedgerClassifies.test_the_repository_policy_over_somebody_elses_records",
    ),
    DOC_GATE_VACUOUS: (
        "TestVacuousProviders.test_a_d_phase_provider_that_produced_nothing",
        "TestVacuousProviders.test_a_d_phase_floor_naming_a_provider_that_never_ran",
        "TestStaleAllowances.test_an_allowance_for_a_source_that_now_declares",
        "TestASurfaceNoLedgerClassifies.test_the_repository_policy_over_somebody_elses_records",
    ),
    DOC_OUTPUT_DRIFT: (
        "TestAHandEditedInventory.test_an_edited_count_is_named_line_by_line",
        "TestAHandEditedInventory.test_an_edited_index_row_is_named_too",
    ),
    DOC_SIDE_EFFECT_UNDECLARED: (
        "TestUndeclaredSideEffects.test_a_surface_on_an_effectful_channel_that_says_nothing",
    ),
    DOC_SOURCE_FORMAT_UNSUPPORTED: (
        "TestADerivedSourceFormatGap.test_a_format_the_source_does_not_declare",
    ),
    DOC_SURFACE_UNBOUND: (
        "TestASurfaceNamingAMissingComponent.test_a_d_phase_surface_reaching_a_component_nobody_registers",
    ),
    DOC_SURFACE_UNCOVERED: (
        "TestAnUninventoriedPublicTool.test_a_tool_the_committed_index_does_not_list",
        "TestAnUninventoriedPublicTool.test_the_composed_build_reports_it_itself",
    ),
}

#: The codes this battery fires that C9 also fires. Written down, then
#: compared against what the two tables actually say. A code that left
#: C9's table would shrink the computed overlap and turn the handshake red
#: by name, rather than being silently covered here — which is the whole
#: point of a handshake between two batteries.
SHARED_WITH_C9: tuple[str, ...] = (
    DOC_CAPABILITY_UNCOVERED,
    DOC_GATE_VACUOUS,
    DOC_OUTPUT_DRIFT,
    DOC_SIDE_EFFECT_UNDECLARED,
    DOC_SURFACE_UNBOUND,
    DOC_SURFACE_UNCOVERED,
)

#: The one code only this battery claims, and the reason it is not C9's to
#: claim: ``DOC_SOURCE_FORMAT_UNSUPPORTED`` is D7's, it lives in
#: ``codegen/doc_emitter/derived_sources.py``, and C9's universe is the
#: ``docs_model`` source tree — so C9 cannot see it and correctly does not
#: pretend to. D8 extends the accounting to cover it rather than leaving a
#: minted, armed code in nobody's table.
CLAIMED_ONLY_HERE: tuple[str, ...] = (DOC_SOURCE_FORMAT_UNSUPPORTED,)

#: Where the ``docs_model`` source tree lives, read off the imported
#: package so the audit works in a wheel-install context too.
DOCS_MODEL_SOURCE = Path(docs_model.__file__).resolve().parent

#: The derived-source registry's module, the second source tree this
#: battery accounts for.
DERIVED_SOURCES_SOURCE = Path(derived_sources.__file__).resolve()

#: Any ``DOC_*`` name, with C9's lookbehind so a code embedded in a longer
#: identifier does not contribute a phantom.
_CODE_NAME = re.compile(r"(?<![A-Z0-9_])DOC_[A-Z][A-Z0-9_]*")


def code_universe() -> frozenset[str]:
    """Every diagnostic name the ``docs_model`` source tree mentions.

    Grepped the same way C9 greps it, and deliberately *not* imported from
    C9: two independent readings of one tree can be compared, and one
    reading shared between two modules cannot.
    """
    found: set[str] = set()
    for module in sorted(DOCS_MODEL_SOURCE.glob("*.py")):
        found.update(_CODE_NAME.findall(module.read_text(encoding="utf-8")))
    return frozenset(found)


#: The universe as this run reads it.
CODE_UNIVERSE = code_universe()


def c_phase_claims() -> frozenset[str]:
    """The codes C9's ``FIXTURES`` table claims, read out of its source.

    The keys of C9's table are the imported ``DOC_*`` constants, written as
    names. Every one of those constants is defined as its own spelling —
    ``DOC_GATE_VACUOUS = "DOC_GATE_VACUOUS"`` — which
    :meth:`TestTheTwoBatteriesAccountForEveryCode.test_a_code_constant_is_its_own_spelling`
    proves rather than assumes, so reading the name is reading the code.
    """
    tree = ast.parse(C_PHASE_BATTERY.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        named = any(
            isinstance(target, ast.Name) and target.id == "FIXTURES"
            for target in targets
        )
        if not named or not isinstance(node.value, ast.Dict):
            continue
        return frozenset(
            key.id for key in node.value.keys if isinstance(key, ast.Name)
        )
    raise AssertionError(
        f"{C_PHASE_BATTERY.name} no longer defines a module-level FIXTURES "
        f"dict this module can read. The two batteries coordinate through "
        f"that table; if it has moved, this handshake has to move with it."
    )


# ---------------------------------------------------------------------------
# Shared fixture material
# ---------------------------------------------------------------------------


def _surface(
    identifier: str,
    *,
    channel: str,
    component_refs: tuple[str, ...] = (),
    manual_exception: str = "Written by hand for the fixture build it belongs to.",
    side_effects: tuple[str, ...] = ("read",),
    provenance: Provenance = _PROVENANCE,
) -> SurfaceRecord:
    """One served capability, ready to be broken in exactly one place.

    ``side_effects`` defaults to an answer rather than to the empty tuple,
    for the reason C9's helper does: D5b armed the gate that reads an empty
    tuple as an unanswered question, and a helper whose default is the
    unanswered form would put that failure into every fixture that meant to
    break something else.
    """
    return SurfaceRecord(
        id=identifier,
        channel=channel,
        public_name=identifier.partition("/")[2] or identifier,
        intent="Answer one question about the project being described.",
        component_refs=component_refs,
        manual_exception=manual_exception,
        governed_by=(),
        side_effects=side_effects,
        errors=(),
        provenance=provenance,
    )


def _bundle(*surfaces: SurfaceRecord) -> DocsBundle:
    """One stamped bundle of surfaces, built the only supported way."""
    return stamped(
        DocsBundle(
            stamp=BuildStamp(schema=SCHEMA, release_version="", snapshot_hash=""),
            authorities=(),
            concepts=(),
            surfaces=tuple(sorted(surfaces, key=lambda item: item.id)),
            journeys=(),
            sequences=(),
            documents=(),
        ),
        RELEASE,
    )


class PlantedProvider:
    """A provider whose records are whatever the fixture needs them to be.

    The seam ``application.build(providers=...)`` exists so a caller can
    bring its own composition and have every gate downstream of the merge
    run over it. That is how the composed-path fixtures below reach the
    real build without a repository checkout.
    """

    def __init__(self, provider_id: str, *records: SourcedRecord) -> None:
        self._id = provider_id
        self._records = records

    @property
    def provider_id(self) -> str:
        return self._id

    def provide(self) -> ProviderResult:
        return ProviderResult(provider_id=self._id, records=sort_records(self._records))


#: The written reason a fixture policy carries. One string, because what a
#: fixture exception says is never the subject of a test here — that it
#: says *something* is, and E8's loader is where the floor on it is proved.
_POLICY_REASON = (
    "A written reason long enough to have been thought about: this fixture "
    "channel is not a place anybody goes, and its reference entry is the "
    "whole of what a reader needs about it."
)


def _neutral_policy(*surfaces: SurfaceRecord) -> CoveragePolicy:
    """A coverage policy that classifies exactly the planted surfaces.

    E8's gate asks two questions of a build — is every primary capability
    taught, and has every served surface been classified at all — and a
    caller that brings its own providers has to answer the second one for
    its own records. This answers it the neutral way: no capability is
    claimed, and every channel the fixture actually planted is ruled
    reference-only, so the planted build is silent about coverage and
    every red below stays a statement about the one thing its test broke.

    Withholding it is how :class:`TestASurfaceNoLedgerClassifies` proves
    the composed path's red, which is why this is a helper rather than a
    default buried in :func:`_planted_build`.
    """
    return CoveragePolicy(
        source=FIXTURE_SOURCE,
        capabilities=(),
        surface_exceptions=(),
        channel_exceptions=tuple(
            ChannelException(channel=channel, reason=_POLICY_REASON)
            for channel in sorted({record.channel for record in surfaces})
        ),
    )


#: Where phase 9 refuses when the root under test is a fixture directory
#: rather than a workspace. Eight of this application's declared outputs are
#: *about a workspace* — F4's MCP, studi0 and packages references, the
#: component index, H1's manifest, which cannot name a product version
#: with no ``packages/`` to read it from, I1's self-description, which
#: reads the documentation project's own committed build, and the quick
#: reference in both its renderings, whose authored words are a file of
#: this repository — and F5's
#: learning collection refuses without
#: ``concept:s0ma-file``. None of them will render over a temp directory
#: holding a handful of planted surfaces, and each says so as a
#: ``DOC_GATE_VACUOUS`` finding located at the page it could not write,
#: with the artifact floor reporting the short set from the documentation
#: root. Right report, wrong subject: this file's assertions are about one
#: planted change, so they drop these by location and keep everything else.
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


def _planted_build(
    root: Path,
    *surfaces: SurfaceRecord,
    floors: Mapping[tuple[str, str], int] | None = None,
    allowances: Mapping[tuple[str, str], str] | None = None,
    coverage: CoveragePolicy | None = None,
) -> Build:
    """One whole application build over planted surfaces and nothing else.

    ``floors``, ``allowances`` and ``coverage`` default to none of this
    repository's: a caller that brings its own providers brings its own
    policy, and leaving the repository's in place would report ten
    providers this build never registered as missing and nine capabilities
    it never served. The coverage default is :func:`_neutral_policy` over
    the very surfaces being planted, which is the smallest honest answer
    to a question the gate is right to ask.
    """
    registry = ProviderRegistry.of(
        PlantedProvider("d8", *(SourcedRecord.of(record) for record in surfaces))
    )
    return build(
        root,
        version=RELEASE,
        providers=registry,
        floors={} if floors is None else floors,
        allowances={} if allowances is None else allowances,
        coverage=_neutral_policy(*surfaces) if coverage is None else coverage,
    )


def _one(findings: Sequence[Finding], code: str) -> Finding:
    """The single finding of ``code``, refusing none and refusing several."""
    found = [item for item in findings if item.code == code]
    assert len(found) == 1, [item.rendered() for item in findings]
    return found[0]


def _of(findings: Sequence[Finding], code: str) -> list[Finding]:
    return [item for item in findings if item.code == code]


def _located(finding: Finding, where: str) -> Finding:
    """Assert the finding's location exactly, and that it remediates."""
    assert finding.location == where, finding.rendered()
    assert finding.remediation.strip(), finding.rendered()
    return finding


def _results(*counted: tuple[str, tuple[SurfaceRecord, ...]]) -> list[ProviderResult]:
    """Provider results carrying exactly the records named, for the floors."""
    return [
        ProviderResult(
            provider_id=provider_id,
            records=sort_records(SourcedRecord.of(record) for record in records),
        )
        for provider_id, records in counted
    ]


#: The five D-phase readings and the floor each declares, so a fixture can
#: ask every family the same question. Read from the providers' own
#: constants rather than restated: a floor that moved would move here.
D_PHASE_FLOORS: tuple[tuple[str, Mapping[tuple[str, str], int]], ...] = (
    ("cli", CLI_FLOORS),
    ("diagnostics", DIAGNOSTIC_FLOORS),
    ("config", CONFIG_FLOORS),
    ("mcp", MCP_FLOORS),
    ("studi0", STUDI0_FLOORS),
)

#: Every channel a caller reaches the product *through*, with one id of the
#: right form for each. The classification is read live from
#: :data:`~s0ma_dsl.docs_model.validate.CHANNEL_EFFECTS` rather than
#: restated, so a channel promoted to effectful arrives in this battery
#: without anybody remembering to add it — and one added to the model with
#: no id written here fails
#: :meth:`TestUndeclaredSideEffects.test_every_effectful_channel_has_a_fixture`.
EFFECTFUL_IDS: Mapping[str, str] = {
    "cli": "cli:s0ma/docs/render",
    "mcp_tool": "mcp:tool/describe_component",
    "mcp_resource": "mcp:resource/s0ma://guide/errors",
    "mcp_prompt": "mcp:prompt/explain_component",
    "python": "python:s0ma.verify",
    "rest": "rest:GET:/self/components",
    "studi0": "studi0:action/api/graph",
}


# ---------------------------------------------------------------------------
# T1 — a public tool nothing inventoried
# ---------------------------------------------------------------------------


class TestAnUninventoriedPublicTool:
    """``DOC_SURFACE_UNCOVERED`` at D6's gate, and through the composed build.

    Two proofs, because there are two things to know. The first is that the
    gate has teeth when the bundle and the index disagree — D6 proved that
    at the seam and this re-proves it on its own minimal fixture. The second
    is the one this milestone adds: the gate is *wired into*
    :func:`~s0ma_dsl.docs_model.application.build`, over the artifact that
    build will commit, so a capability missing from the committed index
    fails the build that rendered it rather than waiting for somebody to
    call the gate by hand.

    **What the composed path can and cannot reach, stated honestly.**
    Inside ``build`` the requirement and the index come from one bundle, so
    every surface is listed by construction — with one exception, and it is
    a real one rather than a contrived one: the index is a Markdown table,
    a vertical bar ends a cell, and the renderer escapes it. An id carrying
    a bar is therefore written into the committed page under a different
    spelling, and a reader looking for that capability does not find it.
    That is precisely the class the gate exists for — a renderer changing
    what reaches the page — and it is the composed path's one reachable
    red. Nothing here asks for a source change: the gate catches it, which
    is what the gate is for.
    """

    def test_a_tool_the_committed_index_does_not_list(self, tmp_path: Path) -> None:
        """The seam: the bundle is the requirement, the index is the reach."""
        listed = _surface("mcp:tool/describe_component", channel="mcp_tool")
        composed = _planted_build(tmp_path, listed)
        index = composed.artifact(SURFACES_INDEX_OUTPUT).content
        assert check_surface_index(composed.bundle, index=index) == []

        invented = _surface("mcp:tool/invented_tool", channel="mcp_tool")
        planted = dataclasses.replace(
            composed.bundle, surfaces=(*composed.bundle.surfaces, invented)
        )
        findings = check_surface_index(planted, index=index)
        found = _located(
            _one(findings, DOC_SURFACE_UNCOVERED),
            f"{DOCS_ROOT}/{SURFACES_INDEX_OUTPUT}",
        )
        assert "mcp:tool/invented_tool" in found.message

        # Inventoried, it passes — which is what makes the failure above a
        # statement about coverage and not about the planted record.
        assert check_surface_index(planted, index=surfaces_index(planted)) == []

    def test_the_composed_build_reports_it_itself(self, tmp_path: Path) -> None:
        """The wiring: ``build`` runs the gate over the page it will commit."""
        listed = _surface("mcp:tool/describe_component", channel="mcp_tool")
        dropped = _surface("mcp:tool/pipe|probe", channel="mcp_tool")
        result = _planted_build(tmp_path, listed, dropped)

        found = _located(
            _one(result.findings, DOC_SURFACE_UNCOVERED),
            f"{DOCS_ROOT}/{SURFACES_INDEX_OUTPUT}",
        )
        assert "mcp:tool/pipe|probe" in found.message
        assert not result.ok

        index = result.artifact(SURFACES_INDEX_OUTPUT).content
        assert "mcp:tool/describe_component" in index
        assert "mcp:tool/pipe|probe" not in index
        assert r"mcp:tool/pipe\|probe" in index

    def test_the_same_build_without_it_is_clean(self, tmp_path: Path) -> None:
        """The control. Every red below is a statement about one change.

        Clean *of this corpus*: since F3–F5 the declared set includes five
        outputs a temp directory cannot produce, and those are dropped by
        :data:`_OFF_WORKSPACE` rather than by lowering what "clean" means.
        """
        result = _planted_build(
            tmp_path, _surface("mcp:tool/describe_component", channel="mcp_tool")
        )
        assert _in_corpus(result.findings) == (), [
            item.rendered() for item in _in_corpus(result.findings)
        ]
        assert result.artifacts


# ---------------------------------------------------------------------------
# T1 — a public surface no coverage ledger classifies (E8)
# ---------------------------------------------------------------------------


class TestASurfaceNoLedgerClassifies:
    """``DOC_CAPABILITY_UNCOVERED`` through the composed build.

    C9 fires this code against the gate directly, on hand-built records.
    This is the D-phase shape of the same class and the one the product
    actually meets: a provider starts serving something new, and the
    question is whether the build that composed it says so. It is
    deliberately the *composed* path — ``build`` runs the gate — because
    the failure this guards against is a capability shipping without
    anybody having decided whether a journey owes it a path, and nobody
    calls a gate by hand at the moment that happens.

    The neutral policy every other planted build here is handed rules the
    planted channels reference-only. Withholding that ruling for one
    surface is the whole fixture: everything else about the build is
    unchanged, and the surface arrives classified by nothing.
    """

    def test_a_newly_served_tool_lands_in_neither_ledger(self, tmp_path: Path) -> None:
        listed = _surface("mcp:tool/describe_component", channel="mcp_tool")
        arrived = _surface("mcp:tool/newly_served", channel="mcp_tool")
        result = _planted_build(
            tmp_path, listed, arrived, coverage=_neutral_policy(listed)
        )
        # The neutral policy above rules mcp_tool reference-only, so both
        # planted tools are excused — the red below is the *other* channel.
        assert _of(result.findings, DOC_CAPABILITY_UNCOVERED) == []

        elsewhere = _surface("cli:s0ma/newly-served", channel="cli")
        result = _planted_build(
            tmp_path, listed, elsewhere, coverage=_neutral_policy(listed)
        )
        found = _located(
            _one(result.findings, DOC_CAPABILITY_UNCOVERED), FIXTURE_SOURCE
        )
        assert "cli:s0ma/newly-served" in found.message
        assert "has not said whether" in found.message
        assert not result.ok

    def test_the_repository_policy_over_somebody_elses_records(
        self, tmp_path: Path
    ) -> None:
        """Why the fourth override exists, proved rather than asserted.

        This repository's policy names nine capabilities served by
        forty-nine surfaces none of which a planted composition holds. Left
        in place over somebody else's records it reports the absence of
        this repository, exactly as its floors and its allowances would —
        which is the reason ``build`` takes the policy as a parameter at
        all.
        """
        listed = _surface("mcp:tool/describe_component", channel="mcp_tool")
        stranded = _planted_build(
            tmp_path, listed, coverage=coverage_policy(REPO_ROOT)
        )
        codes = {item.code for item in stranded.findings}
        assert DOC_CAPABILITY_UNCOVERED in codes
        assert DOC_GATE_VACUOUS in codes


# ---------------------------------------------------------------------------
# T1 — a surface pointing at a component nobody registers
# ---------------------------------------------------------------------------


class TestASurfaceNamingAMissingComponent:
    """``DOC_SURFACE_UNBOUND`` from the reference resolver, on a D channel.

    The gate has two halves and they are different failures.
    :func:`~s0ma_dsl.docs_model.validate.check_surface_binding` asks whether
    a capability said anything at all about what implements it;
    :func:`~s0ma_dsl.docs_model.validate.check_references` asks whether what
    it said resolves. A surface can pass the first and fail the second,
    which is the shape a renamed component leaves behind, and it is the one
    proved here on a studi0 route because Phase D is where surfaces started
    naming components in bulk.
    """

    def test_a_d_phase_surface_reaching_a_component_nobody_registers(self) -> None:
        route = _surface(
            "studi0:action/api/graph",
            channel="studi0",
            component_refs=("component:s0ma_studi0.studi0_state.renamed_away",),
            manual_exception="",
        )
        findings = validate_bundle(_bundle(route), external_ids=())
        found = _located(_one(findings, DOC_SURFACE_UNBOUND), FIXTURE_SOURCE)
        assert "component:s0ma_studi0.studi0_state.renamed_away" in found.message
        assert "component_refs[0]" in found.message

    def test_the_same_reference_vouched_for_resolves(self) -> None:
        """The control: the resolver's universe is the caller's to declare."""
        route = _surface(
            "studi0:action/api/graph",
            channel="studi0",
            component_refs=("component:s0ma_studi0.studi0_state.graph_document",),
            manual_exception="",
        )
        findings = validate_bundle(
            _bundle(route),
            external_ids=("component:s0ma_studi0.studi0_state.graph_document",),
        )
        assert _of(findings, DOC_SURFACE_UNBOUND) == []


# ---------------------------------------------------------------------------
# T1 — the three-source refusal
# ---------------------------------------------------------------------------


class TestTheMcpSnapshotAndTheLiveServer:
    """A snapshot that no longer matches the server stops the reading.

    Architecture §7.4's rule, re-proved on this battery's own fixture root:
    the registrations, the committed snapshot and the live listing must
    agree before any record is emitted, and a disagreement names all three
    accounts rather than picking one. Structural rather than a
    :class:`~s0ma_dsl.docs_model.providers.Finding` — a provider that cannot
    trust its own sources has nothing to report about, so it refuses.
    """

    @staticmethod
    def _root(destination: Path, document: dict[str, Any]) -> Path:
        path = destination / SNAPSHOT_SOURCE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return destination

    @staticmethod
    def _committed() -> dict[str, Any]:
        loaded = json.loads(
            (REPO_ROOT / SNAPSHOT_SOURCE).read_text(encoding="utf-8")
        )
        assert isinstance(loaded, dict)
        return loaded

    def test_a_snapshot_that_lost_a_tool_names_all_three_sources(
        self, tmp_path: Path
    ) -> None:
        document = self._committed()
        dropped = sorted(tool["name"] for tool in document["tools"])[0]
        document["tools"] = [
            tool for tool in document["tools"] if tool["name"] != dropped
        ]
        with pytest.raises(McpSurfaceDisagreementError) as caught:
            McpProvider(root=self._root(tmp_path, document)).provide()
        message = str(caught.value)
        assert dropped in message
        for source in (
            "python:s0ma_mcp.get_self_registry",
            SNAPSHOT_SOURCE,
            "python:s0ma_mcp.create_server",
        ):
            assert source in message, source

    def test_a_snapshot_that_invented_a_prompt_is_refused_too(
        self, tmp_path: Path
    ) -> None:
        """Both directions. A snapshot may not have *more* than the server."""
        document = self._committed()
        document["prompts"] = [
            *document["prompts"],
            {"name": "invented_prompt", "description": "Nothing serves this."},
        ]
        with pytest.raises(McpSurfaceDisagreementError) as caught:
            McpProvider(root=self._root(tmp_path, document)).provide()
        assert "invented_prompt" in str(caught.value)

    def test_an_absent_snapshot_is_refused_rather_than_skipped(
        self, tmp_path: Path
    ) -> None:
        """A missing account is not two accounts agreeing."""
        with pytest.raises(Exception) as caught:
            McpProvider(root=tmp_path).provide()
        assert SNAPSHOT_SOURCE in str(caught.value)


# ---------------------------------------------------------------------------
# T1 — undeclared side effects, and an allowance that outlived its gap
# ---------------------------------------------------------------------------


class TestUndeclaredSideEffects:
    """``DOC_SIDE_EFFECT_UNDECLARED``, once per channel a caller reaches.

    D5b armed the gate; this asks it of every effectful channel the model
    knows, so a channel whose surfaces stopped being classified is caught
    wherever it is. The empty tuple is the unanswered question — ``none``
    is the answer — which is why an empty ``side_effects`` is the one thing
    the gate refuses.
    """

    def test_every_effectful_channel_has_a_fixture(self) -> None:
        """The parametrization is read off the model, never written down.

        A channel promoted from *describes a thing* to *is a way to reach
        one* arrives in the test below without anybody remembering it; a
        channel added with no id here fails right now.
        """
        effectful = {
            channel for channel, invocable in CHANNEL_EFFECTS.items() if invocable
        }
        assert set(EFFECTFUL_IDS) == effectful, sorted(
            effectful.symmetric_difference(EFFECTFUL_IDS)
        )
        for channel, identifier in sorted(EFFECTFUL_IDS.items()):
            assert is_valid_id(identifier), (channel, identifier)

    @pytest.mark.parametrize("channel", sorted(EFFECTFUL_IDS))
    def test_a_surface_on_an_effectful_channel_that_says_nothing(
        self, channel: str
    ) -> None:
        silent = _surface(
            EFFECTFUL_IDS[channel], channel=channel, side_effects=()
        )
        findings = check_side_effects(_bundle(silent))
        found = _located(
            _one(findings, DOC_SIDE_EFFECT_UNDECLARED), FIXTURE_SOURCE
        )
        assert EFFECTFUL_IDS[channel] in found.message
        assert "says nothing about what" in found.message

    @pytest.mark.parametrize("channel", sorted(EFFECTFUL_IDS))
    def test_the_same_surface_that_answers_is_not_a_finding(
        self, channel: str
    ) -> None:
        """The control, per channel: ``none`` is an answer and passes."""
        answered = _surface(
            EFFECTFUL_IDS[channel], channel=channel, side_effects=("none",)
        )
        assert check_side_effects(_bundle(answered)) == []


class TestStaleAllowances:
    """``DOC_GATE_VACUOUS`` — a standing permission for a silence that ended.

    The half of D5b's design that stops an exception outliving its gap. An
    allowance names a *source* that cannot answer, so the day the source
    starts answering, the allowance stops matching and the build says so.
    Without this the three real allowances would be indistinguishable from
    an ignore file.
    """

    def test_an_allowance_for_a_source_that_now_declares(self) -> None:
        declared = _surface(
            "mcp:tool/describe_component",
            channel="mcp_tool",
            side_effects=("read",),
        )
        findings = check_side_effects(
            _bundle(declared),
            allowances={("d8", "mcp_tool"): "The reading could not say, once."},
        )
        found = _located(_one(findings, DOC_GATE_VACUOUS), "")
        assert "'d8'" in found.message
        assert "'mcp_tool'" in found.message
        assert "no surface in this build used it" in found.message

    def test_the_allowance_a_silent_surface_uses_is_not_a_finding(self) -> None:
        """The control: an allowance covering a real silence stays quiet."""
        silent = _surface(
            "mcp:tool/describe_component", channel="mcp_tool", side_effects=()
        )
        assert (
            check_side_effects(
                _bundle(silent),
                allowances={("d8", "mcp_tool"): "The reading cannot say."},
            )
            == []
        )

    def test_the_repositorys_allowances_are_keyed_the_way_this_fixture_is(
        self,
    ) -> None:
        """The fixture's shape is the product's shape, not a lookalike.

        An allowance is keyed ``(adapter_id, channel)``. If that key ever
        became the surface id, every fixture above would still pass while
        proving something the application no longer does.
        """
        for key in SIDE_EFFECT_ALLOWANCES:
            assert len(key) == 2, key
            assert key[1] in CHANNEL_EFFECTS, key


# ---------------------------------------------------------------------------
# T1 — a provider that stopped producing
# ---------------------------------------------------------------------------


class TestVacuousProviders:
    """``DOC_GATE_VACUOUS`` for each of the five D-phase readings.

    Every one of the five floors is asserted to be a live gate rather than
    a decoration, using the provider's own floor constant. A gate that
    resolves empty passes everything downstream of it, and the five surface
    providers are exactly where an empty reading would be least visible:
    the composed build would still render, still validate, and still commit
    a smaller index.
    """

    @pytest.mark.parametrize(
        ("name", "floors"), D_PHASE_FLOORS, ids=[row[0] for row in D_PHASE_FLOORS]
    )
    def test_a_d_phase_provider_that_produced_nothing(
        self, name: str, floors: Mapping[tuple[str, str], int]
    ) -> None:
        results = _results((name, ()))
        findings = check_floors(results, floors)
        assert findings, f"{name}'s floor is not a gate"
        for finding in findings:
            _located(finding, "")
            assert f"provider {name!r} produced 0" in finding.message
        assert {item.code for item in findings} == {DOC_GATE_VACUOUS}

    @pytest.mark.parametrize(
        ("name", "floors"), D_PHASE_FLOORS, ids=[row[0] for row in D_PHASE_FLOORS]
    )
    def test_a_d_phase_floor_naming_a_provider_that_never_ran(
        self, name: str, floors: Mapping[tuple[str, str], int]
    ) -> None:
        """A provider never registered and one that produced nothing are one failure."""
        findings = check_floors([], floors)
        assert findings
        for finding in findings:
            _located(finding, "")
            assert f"provider {name!r}, which did not run" in finding.message

    def test_the_application_asserts_all_five_of_those_floors(self) -> None:
        """The floors this battery proves are the ones the application runs.

        Without this the five proofs above could be about constants nothing
        reads. ``APPLICATION_FLOORS`` is the merge the real build hands to
        ``check_floors``, and every D-phase entry has to survive into it.
        """
        for name, floors in D_PHASE_FLOORS:
            for key, floor in floors.items():
                assert APPLICATION_FLOORS.get(key) == floor, (name, key)

    def test_a_floor_met_exactly_is_not_a_finding(self) -> None:
        """The control: the gate fires below the floor and not at it."""
        floor = CONFIG_FLOORS[("config", "surfaces")]
        records = tuple(
            _surface(config_id(f"probe_key_{index}"), channel="config",
                     side_effects=("none",))
            for index in range(floor)
        )
        assert check_floors(_results(("config", records)), CONFIG_FLOORS) == []


# ---------------------------------------------------------------------------
# T1 — a hand-edited generated artifact
# ---------------------------------------------------------------------------


class TestAHandEditedInventory:
    """``DOC_OUTPUT_DRIFT`` on D6's artifacts, through the check command's path.

    :func:`~s0ma_dsl.docs_model.application.check` is what ``s0ma docs
    check`` runs, and it compares the bytes this build renders against what
    is committed. D6 added five artifacts to the one C8 had, and the reason
    to prove drift on an *inventory* rather than on the snapshot is that an
    inventory is the artifact a person is most likely to edit: it holds
    counts, and a count is the thing that looks safe to correct by hand.

    The copy is written into ``tmp_path`` and edited there, so the fixture
    never touches the checkout, and check mode is re-proved to write
    nothing (SDA-INV-9).
    """

    @staticmethod
    def _written(tmp_path: Path) -> tuple[Build, Path]:
        result = _planted_build(
            tmp_path, _surface("mcp:tool/describe_component", channel="mcp_tool")
        )
        base = tmp_path / "committed"
        write(result, base)
        assert check(result, base) == (), "the copy starts clean"
        return result, base

    def test_an_edited_count_is_named_line_by_line(self, tmp_path: Path) -> None:
        result, base = self._written(tmp_path)
        committed = base / Path(SURFACES_INVENTORY_OUTPUT)
        lines = committed.read_text(encoding="utf-8").split("\n")
        edited = next(
            index for index, line in enumerate(lines) if '"surfaces":' in line
        )
        lines[edited] = lines[edited].replace(": 1", ": 99")
        committed.write_text("\n".join(lines), encoding="utf-8", newline="\n")

        found = _located(
            _one(check(result, base), DOC_OUTPUT_DRIFT),
            f"{DOCS_ROOT}/{SURFACES_INVENTORY_OUTPUT}",
        )
        assert f"line {edited + 1} differs" in found.message
        assert "99" in found.message

    def test_an_edited_index_row_is_named_too(self, tmp_path: Path) -> None:
        """The reader-facing half: a Markdown page is generated the same way."""
        result, base = self._written(tmp_path)
        committed = base / Path(SURFACES_INDEX_OUTPUT)
        text = committed.read_text(encoding="utf-8")
        committed.write_text(
            text.replace("mcp:tool/describe_component", "mcp:tool/renamed_by_hand"),
            encoding="utf-8",
            newline="\n",
        )
        found = _located(
            _one(check(result, base), DOC_OUTPUT_DRIFT),
            f"{DOCS_ROOT}/{SURFACES_INDEX_OUTPUT}",
        )
        assert "renamed_by_hand" in found.message

    def test_check_mode_wrote_nothing(self, tmp_path: Path) -> None:
        """SDA-INV-9, re-proved here because these fixtures depend on it."""
        result = _planted_build(
            tmp_path, _surface("mcp:tool/describe_component", channel="mcp_tool")
        )
        base = tmp_path / "never" / "written"
        assert check(result, base)
        assert not base.exists()


# ---------------------------------------------------------------------------
# T1 — the derived-source registry
# ---------------------------------------------------------------------------


def _record_set(name: str) -> DerivedRecordSet:
    """One well-formed record set, so a registry fixture has something to return."""
    return DerivedRecordSet(
        provider_id=f"S0maDSL_d8_{name}",
        source_identity=FIXTURE_SOURCE,
        schema_version="1.0.0",
        sort_key="code",
        fields=(
            DerivedField(name="code", label="Code", kind=DerivedFieldKind.IDENTIFIER),
            DerivedField(name="note", label="Note", kind=DerivedFieldKind.TEXT),
        ),
        records=(("A_CODE", "What it means."),),
        content_hash="1:" + "0" * 64,
    )


@pytest.fixture
def registered() -> Iterator[Callable[[DerivedSource], DerivedSource]]:
    """Register fixture sources and take them out again afterwards.

    Registration is an import-time act with no public removal path, because
    nothing in production ever unregisters a source. A battery that left
    its stubs behind would change what every later test in the session sees
    from ``derived_source_names()`` — including the parser's allow-list.
    """
    names: list[str] = []

    def add(source: DerivedSource) -> DerivedSource:
        register(source)
        names.append(source.name)
        return source

    try:
        yield add
    finally:
        for name in names:
            derived_sources._REGISTRY.pop(name, None)


class TestADerivedSourceFormatGap:
    """``DOC_SOURCE_FORMAT_UNSUPPORTED`` — the end of silent-empty output.

    ADR-013 §4. Before the registry, a ``doc-ref`` asking for HTML or JSON
    over a derived source produced a document with a heading, an intent and
    no content, in every strictness mode. The named error is what replaced
    it, and this fixture proves it is raised rather than declared: a source
    that renders in Markdown only, asked for HTML, fails by name and says
    what to do.
    """

    def test_a_format_the_source_does_not_declare(self, registered: RegisterSource) -> None:
        registered(
            DerivedSource(
                name="d8_markdown_only",
                provider=lambda: _record_set("d8_markdown_only"),
                formats=frozenset({"markdown"}),
                schema_version="1.0.0",
                intent="Fixture source declaring one format.",
                narrowing_reason=(
                    "Fixture: the narrowed declaration is the thing under test."
                ),
            )
        )
        with pytest.raises(DocRenderError) as caught:
            records_for(
                "d8_markdown_only", doc_format="html", decl_name="D8Probe"
            )
        assert caught.value.code == DOC_SOURCE_FORMAT_UNSUPPORTED
        assert "d8_markdown_only" in str(caught.value)
        assert caught.value.remediation
        assert "markdown" in caught.value.remediation

    def test_the_format_it_does_declare_renders(self, registered: RegisterSource) -> None:
        """The control: the gate is about the gap, not about the source."""
        registered(
            DerivedSource(
                name="d8_markdown_only_control",
                provider=lambda: _record_set("d8_markdown_only_control"),
                formats=frozenset({"markdown"}),
                schema_version="1.0.0",
                intent="Fixture source declaring one format.",
                narrowing_reason="Fixture: the control for the refusal above.",
            )
        )
        rendered = records_for(
            "d8_markdown_only_control", doc_format="markdown", decl_name="D8Probe"
        )
        assert rendered.records

    def test_a_narrowed_declaration_with_no_reason_is_refused(self) -> None:
        """§4's other half: narrowing is a recorded decision, not a default."""
        with pytest.raises(ValueError, match="narrowing_reason"):
            register(
                DerivedSource(
                    name="d8_unreasoned",
                    provider=lambda: _record_set("d8_unreasoned"),
                    formats=frozenset({"markdown"}),
                    schema_version="1.0.0",
                    intent="Fixture source narrowing without saying why.",
                )
            )
        assert "d8_unreasoned" not in derived_sources.derived_source_names()


class TestACheckoutSourceCalledBare:
    """A ``needs_input`` source refuses to go looking for a root.

    ADR-013 §2: a provider is handed its input and never finds one for
    itself. The failure has to be *named*, because the alternative shape —
    an empty table — is indistinguishable in the rendered page from a
    source nobody wired up, which is the whole failure the registry
    replaced.
    """

    def test_a_source_that_describes_a_checkout_called_with_none(
        self, registered: RegisterSource
    ) -> None:
        registered(
            DerivedSource(
                name="d8_needs_checkout",
                provider=lambda _input: _record_set("d8_needs_checkout"),
                formats=SUPPORTED_DOC_FORMATS,
                schema_version="1.0.0",
                intent="Fixture source describing a checkout.",
                needs_input=True,
            )
        )
        with pytest.raises(DocRenderError) as caught:
            records_for(
                "d8_needs_checkout", doc_format="markdown", decl_name="D8Probe"
            )
        assert "describes a checkout" in str(caught.value)
        assert caught.value.remediation is not None
        assert "DerivedInput" in caught.value.remediation

    def test_the_same_source_handed_a_checkout_renders(
        self, registered: RegisterSource, tmp_path: Path
    ) -> None:
        """The control: what it refused was the missing input, not the call."""
        registered(
            DerivedSource(
                name="d8_needs_checkout_control",
                provider=lambda _input: _record_set("d8_needs_checkout_control"),
                formats=SUPPORTED_DOC_FORMATS,
                schema_version="1.0.0",
                intent="Fixture source describing a checkout.",
                needs_input=True,
            )
        )
        rendered = records_for(
            "d8_needs_checkout_control",
            doc_format="markdown",
            decl_name="D8Probe",
            derived_input=DerivedInput(root=tmp_path),
        )
        assert rendered.records

    def test_a_needs_input_declaration_the_provider_cannot_satisfy(self) -> None:
        """The registry checks the declaration against the provider's arity."""
        with pytest.raises(ValueError, match="needs_input"):
            register(
                DerivedSource(
                    name="d8_arity_mismatch",
                    provider=lambda: _record_set("d8_arity_mismatch"),
                    formats=SUPPORTED_DOC_FORMATS,
                    schema_version="1.0.0",
                    intent="Fixture source whose arity contradicts its row.",
                    needs_input=True,
                )
            )
        assert "d8_arity_mismatch" not in derived_sources.derived_source_names()


# ---------------------------------------------------------------------------
# T1 — the binding ledger's enumeration
# ---------------------------------------------------------------------------

#: A fixture ledger of the same shape as
#: :data:`~s0ma_dsl.docs_model.application.UNREGISTERED_HANDLERS`, and
#: deliberately not that constant. The failure being proved is what happens
#: when an eighth unregistered handler appears, and proving it against the
#: real ledger would mean either editing the product's constant or writing
#: a test that passes only while the product has exactly seven.
_FIXTURE_LEDGER: tuple[str, ...] = (
    "cli:s0ma/probe/alpha",
    "cli:s0ma/probe/beta",
)


class TestTheBindingLedgerEnumeration:
    """The eighth unregistered handler, and why the ceiling would not catch it.

    D5b's ruling has two mechanisms with different jobs.
    :data:`~s0ma_dsl.docs_model.application.UNBOUND_CEILING` is a backstop
    with deliberate headroom, so an ordinary new diagnostic or configuration
    key lands without a red test.
    :data:`~s0ma_dsl.docs_model.application.UNREGISTERED_HANDLERS` is the
    gate: it is enumerated by id, and an addition to it is a decision
    somebody has to take in writing.

    That division is only safe if the enumeration really is what catches a
    new entry — and this proves it does, on a fixture ledger, by showing the
    ceiling silently absorbing exactly the change the enumeration refuses.
    """

    def test_an_eighth_entry_fails_the_exact_enumeration(self) -> None:
        found = (*_FIXTURE_LEDGER, "cli:s0ma/probe/gamma")
        assert found != _FIXTURE_LEDGER
        difference = sorted(set(found) - set(_FIXTURE_LEDGER))
        assert difference == ["cli:s0ma/probe/gamma"]

    def test_the_ceiling_would_have_absorbed_it(self) -> None:
        """The backstop's headroom is real, which is why the list is the gate."""
        composed = len(UNREGISTERED_HANDLERS)
        assert composed < UNBOUND_CEILING
        assert composed + 1 <= UNBOUND_CEILING

    def test_the_real_ledger_is_what_the_real_reading_found(self) -> None:
        """The enumeration compares two readings, not a list with itself.

        Run against the live provider, because a ledger nothing compares to
        the parser is a ledger that rots the first time a command is
        renamed. This is the moment an eighth handler would actually be
        caught, and it is here so this battery fails when it appears rather
        than only the policy suite.
        """
        found = tuple(
            sorted(
                identifier
                for identifier, binding_class in CliProvider().exceptions()
                if binding_class == UNBOUND_MACHINERY
            )
        )
        assert found == UNREGISTERED_HANDLERS, sorted(
            set(found).symmetric_difference(UNREGISTERED_HANDLERS)
        )

    def test_the_bound_classes_do_not_include_the_unbound_one(self) -> None:
        """The partition the ledger's arithmetic rests on."""
        assert UNBOUND_MACHINERY not in BOUND_CLASSES
        assert len(BOUND_CLASSES) == 2


# ---------------------------------------------------------------------------
# T1 — the five id forms D5a widened
# ---------------------------------------------------------------------------

#: One acceptance and the refusals that pin its edges, per form D5a
#: completed. The refusals are the point: a charset widened to admit one
#: real spelling must not have admitted a family of others, and each entry
#: below is a spelling the form used to refuse and must still refuse.
D5A_FORMS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "python",
        "the import path a caller writes",
        "python:s0ma.verify",
        ("python:verify", "python:s0ma.", "python:.verify", "python:s0ma..verify"),
    ),
    (
        "config",
        "one key of the [tool.s0ma] table",
        "config:build_dir",
        ("config:Build_Dir", "config:build-dir", "config:9lives", "config:"),
    ),
    (
        "component",
        "package-qualified and never flat",
        "component:s0ma_mcp.create_server",
        ("component:flat", "component:s0ma_mcp.", "component:.create_server"),
    ),
    (
        "mcp_resource",
        "a served address with its braces intact",
        "mcp:resource/s0ma://model/docs-for/{component}",
        ("mcp:resource/s0ma:/guide/errors", "mcp:resource/guide/errors"),
    ),
    (
        "studi0",
        "a route whose last segment may be a filename",
        "studi0:action/assets/app.css",
        (
            "studi0:action/.hidden",
            "studi0:action/trailing.",
            "studi0:action/double..dot",
            "studi0:action//api/graph",
        ),
    ),
)


class TestTheIdFormsD5aWidened:
    """Each widened charset still holds the boundary it was widened past.

    Five gaps closed at D5a, and every one of them was a charset being
    loosened. A loosened charset is where a regression hides: the accepted
    spelling keeps working, and nobody notices that three neighbouring
    spellings started working too. Each row asserts the acceptance *and*
    the refusals that make it a boundary rather than an opening.
    """

    @pytest.mark.parametrize(
        ("name", "note", "accepted", "refused"),
        D5A_FORMS,
        ids=[row[0] for row in D5A_FORMS],
    )
    def test_the_form_accepts_its_spelling_and_refuses_its_neighbours(
        self, name: str, note: str, accepted: str, refused: tuple[str, ...]
    ) -> None:
        assert id_form(accepted) == name, (note, accepted)
        for spelling in refused:
            assert id_form(spelling) is None, (name, spelling)
            assert not is_valid_id(spelling), (name, spelling)

    def test_every_widened_form_is_still_one_form_and_not_two(self) -> None:
        """The forms are mutually exclusive: an id matches one or none."""
        for _name, _note, accepted, _refused in D5A_FORMS:
            matched = [
                form.name for form in ID_FORMS if form.pattern.match(accepted)
            ]
            assert matched == [id_form(accepted)], (accepted, matched)

    def test_the_root_route_keeps_its_documented_normalization(self) -> None:
        """D5a's one mapped spelling, and the collision it refuses by name."""
        assert studi0_action_id("/") == "studi0:action/index"
        assert studi0_public_name("studi0:action/index") == "/"
        assert studi0_public_name("studi0:action/api/graph") == "/api/graph"
        with pytest.raises(DocsIdError, match="index"):
            studi0_action_id("/index")

    def test_a_brace_free_resource_and_a_template_are_two_ids(self) -> None:
        """Why D3 asked for the charset rather than a normalization."""
        template = "mcp:resource/s0ma://model/docs-for/{component}"
        literal = "mcp:resource/s0ma://model/docs-for/"
        assert id_form(template) == "mcp_resource"
        assert template != literal


# ---------------------------------------------------------------------------
# T2 — live-boundary parity, one per provider
# ---------------------------------------------------------------------------


def _surfaces(records: ProviderResult, channel: str | None = None) -> list[SurfaceRecord]:
    """The surface records of one reading, optionally on one channel."""
    return sorted(
        (
            item.record
            for item in records.records
            if isinstance(item.record, SurfaceRecord)
            and (channel is None or item.record.channel == channel)
        ),
        key=lambda record: record.id,
    )


class TestCliParity:
    """The CLI records are the commands a second parser really serves.

    The parser is built here and walked here. A parity test that called
    ``providers_cli``'s own walker would compare the provider with itself
    and pass on the day the walker started missing a subcommand.
    """

    @staticmethod
    def _live_paths() -> set[tuple[str, ...]]:
        from s0ma_dsl.cli.main import S0maCLI

        found: set[tuple[str, ...]] = set()

        def walk(node: argparse.ArgumentParser, prefix: tuple[str, ...]) -> None:
            for action in node._actions:
                if not isinstance(action, argparse._SubParsersAction):
                    continue
                for name, sub in action.choices.items():
                    path = (*prefix, str(name))
                    found.add(path)
                    walk(sub, path)

        walk(S0maCLI().build_parser(), ())
        return found

    def test_the_record_set_is_the_served_command_set(self) -> None:
        live = {"cli:s0ma/" + "/".join(path) for path in self._live_paths()}
        emitted = {record.id for record in _surfaces(CliProvider().provide())}
        assert emitted == live, sorted(emitted.symmetric_difference(live))
        assert live, "a parser serving nothing is not a boundary"

    def test_every_record_is_named_the_way_a_person_types_it(self) -> None:
        """Parity on the second fact, not only on the count."""
        live = {
            "cli:s0ma/" + "/".join(path): "s0ma " + " ".join(path)
            for path in self._live_paths()
        }
        for record in _surfaces(CliProvider().provide()):
            assert record.public_name == live[record.id], record.id


class TestDiagnosticsParity:
    """The diagnostic records are the live severity matrix, per mode.

    The provider reads ``config.py`` with :mod:`ast`, deliberately, so it
    describes the file rather than whatever an import happened to build.
    This reads the *objects* — the imported matrix, the imported strictness
    enum — which is the other half: a matrix whose file and whose value
    disagreed would fail here and nowhere else.
    """

    @staticmethod
    def _live() -> tuple[dict[str, dict[str, str]], set[str]]:
        """The matrix as objects, with its one translation made explicit.

        A matrix entry of ``None`` says the code cannot arise in that mode,
        and the model spells that :data:`NOT_APPLICABLE` — a severity the
        matrix states — rather than leaving the record silent, which is
        what an out-of-matrix code answers. The two absences mean different
        things, so the translation is written here instead of being handled
        by comparing loosely.
        """
        from s0ma_dsl.config import (
            OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE,
            SEVERITY_MATRIX,
            StrictnessMode,
        )

        matrix: dict[str, dict[str, str]] = {}
        for code, severities in SEVERITY_MATRIX.items():
            stated: dict[str, str] = {}
            for mode in StrictnessMode:
                severity = severities[mode]
                stated[mode.value] = NOT_APPLICABLE if severity is None else severity
            matrix[code] = stated
        return matrix, set(OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE)

    def test_the_record_set_is_every_code_the_product_can_emit(self) -> None:
        matrix, out_of_matrix = self._live()
        live = {diagnostic_id(code) for code in set(matrix) | out_of_matrix}
        emitted = {
            record.id
            for record in _surfaces(DiagnosticsProvider(root=REPO_ROOT).provide())
        }
        assert emitted == live, sorted(emitted.symmetric_difference(live))
        assert matrix, "an empty matrix is not a boundary"

    def test_every_record_carries_the_severity_the_live_matrix_states(self) -> None:
        matrix, out_of_matrix = self._live()
        records = {
            record.id: record
            for record in _surfaces(DiagnosticsProvider(root=REPO_ROOT).provide())
        }
        for code, severities in sorted(matrix.items()):
            record = records[diagnostic_id(code)]
            for mode, severity in sorted(severities.items()):
                assert severity_of(record, mode) == severity, (code, mode)
        for code in sorted(out_of_matrix):
            record = records[diagnostic_id(code)]
            for mode in sorted(next(iter(matrix.values()))):
                assert severity_of(record, mode) is None, code


class TestConfigParity:
    """The config records are the keys the live loader actually reads.

    Read by watching the loader work rather than by reading its source: the
    table it is handed is replaced with one that records every key looked
    up, and the loader is then run. A key the loader consults and the
    provider missed appears here, and nowhere else — an AST reading and a
    runtime reading of one function are the two independent accounts this
    parity needs.
    """

    class _WatchedTable(dict[str, Any]):
        """A ``[tool.s0ma]`` table that remembers what was asked of it."""

        def __init__(self) -> None:
            super().__init__()
            self.seen: set[str] = set()

        def get(self, key: str, default: Any = None) -> Any:
            self.seen.add(key)
            return super().get(key, default)

        def __contains__(self, key: object) -> bool:
            if isinstance(key, str):
                self.seen.add(key)
            return super().__contains__(key)

        def __getitem__(self, key: str) -> Any:
            self.seen.add(key)
            return super().__getitem__(key)

    def _live_keys(self, tmp_path: Path) -> set[str]:
        from s0ma_dsl.project import S0maProject

        table = self._WatchedTable()
        S0maProject._from_tool_s0ma(
            root=tmp_path,
            project_name="d8_probe",
            table=table,
            requires_python_raw=">=3.11",
        )
        return set(table.seen)

    def test_the_record_set_is_the_loaders_key_set(self, tmp_path: Path) -> None:
        live = self._live_keys(tmp_path)
        emitted = {
            record.id for record in _surfaces(ConfigProvider(root=REPO_ROOT).provide())
        }
        expected = {config_id(key) for key in live}
        assert emitted == expected, sorted(emitted.symmetric_difference(expected))
        assert live, "a loader that reads no key is not a boundary"

    def test_every_key_is_addressed_by_the_form_d5a_completed(
        self, tmp_path: Path
    ) -> None:
        for key in sorted(self._live_keys(tmp_path)):
            assert id_form(config_id(key)) == "config", key


class TestMcpParity:
    """The MCP records are what a client is served, asked over the SDK.

    A second server object and a different set of calls, so the comparison
    is a parity check and not a restatement of the provider's own listing.
    """

    @staticmethod
    def _live() -> dict[str, set[str]]:
        from s0ma_mcp import create_server

        server = create_server()
        return {
            "mcp_tool": {
                f"mcp:tool/{tool.name}" for tool in asyncio.run(server.list_tools())
            },
            "mcp_resource": {
                f"mcp:resource/{resource.uri}"
                for resource in asyncio.run(server.list_resources())
            },
            "mcp_prompt": {
                f"mcp:prompt/{prompt.name}"
                for prompt in asyncio.run(server.list_prompts())
            },
        }

    def test_the_record_set_is_the_live_listing_on_every_kind(self) -> None:
        live = self._live()
        reading = McpProvider(root=REPO_ROOT).provide()
        for channel, expected in sorted(live.items()):
            emitted = {record.id for record in _surfaces(reading, channel)}
            assert emitted == expected, (
                channel,
                sorted(emitted.symmetric_difference(expected)),
            )
            assert expected, f"an empty {channel} listing is not a boundary"

    def test_a_read_only_tool_does_not_claim_to_write(self) -> None:
        """The annotation the server publishes and the fact the record carries.

        Read from the live listing rather than from the provider's copy of
        it: this is the one fact a reader uses to decide whether calling
        something is safe, and a record that disagreed with its own server
        would be worse than one that said nothing.
        """
        from s0ma_mcp import create_server

        server = create_server()
        hints = {
            f"mcp:tool/{tool.name}": (
                tool.annotations.model_dump(mode="json") if tool.annotations else {}
            )
            for tool in asyncio.run(server.list_tools())
        }
        records = {
            record.id: record
            for record in _surfaces(McpProvider(root=REPO_ROOT).provide(), "mcp_tool")
        }
        checked = 0
        for identifier, published in sorted(hints.items()):
            read_only = published.get("readOnlyHint")
            if read_only is None:
                continue
            checked += 1
            effects = set(records[identifier].side_effects)
            assert effects, identifier
            if read_only:
                assert "write" not in effects, identifier
            else:
                assert effects != {"read"}, identifier
        assert checked, "no served tool declared a readOnlyHint to compare against"


class TestStudi0Parity:
    """The studi0 records are the committed ``ROUTE_TABLE``, read here.

    Read with a literal evaluation of the assignment in the built module,
    not through ``providers_studi0``'s constant reader: the provider's
    account of the table and the table itself are the two things this
    parity exists to keep equal.
    """

    @staticmethod
    def _live_table() -> tuple[dict[str, str], ...]:
        tree = ast.parse((REPO_ROOT / SERVER_SOURCE).read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.AnnAssign) or node.value is None:
                continue
            if not (
                isinstance(node.target, ast.Name) and node.target.id == "ROUTE_TABLE"
            ):
                continue
            evaluated = ast.literal_eval(node.value)
            assert isinstance(evaluated, tuple)
            return evaluated
        raise AssertionError(
            f"{SERVER_SOURCE} declares no ROUTE_TABLE. D4a promoted the route "
            f"table into the package so the model could read it; if it has "
            f"moved, this parity has to move with it."
        )

    def test_the_record_set_is_the_declared_route_table(self) -> None:
        table = self._live_table()
        live = {studi0_action_id(entry["path"]) for entry in table}
        emitted = {
            record.id for record in _surfaces(Studi0Provider(REPO_ROOT).provide())
        }
        assert emitted == live, sorted(emitted.symmetric_difference(live))
        assert table, "an empty route table is not a boundary"

    def test_every_route_keeps_its_served_name_and_its_effects(self) -> None:
        """Parity on the facts a reader acts on, not only on the ids."""
        records = {
            record.id: record
            for record in _surfaces(Studi0Provider(REPO_ROOT).provide())
        }
        for entry in self._live_table():
            record = records[studi0_action_id(entry["path"])]
            assert record.public_name == entry["path"], entry["path"]
            assert record.side_effects == (entry["effects"].strip(),), entry["path"]


# ---------------------------------------------------------------------------
# T3 — the completeness self-audits, and the handshake with C9
# ---------------------------------------------------------------------------


class TestThisBatteryIsHonest:
    """The table against this module, in both directions."""

    def test_every_mapped_test_exists_in_this_module(self) -> None:
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
        """A negative fixture nobody recorded is coverage nobody can audit.

        Only the tests that *fire a DOC_\\* diagnostic* are in the table, so
        the controls, the structural refusals, the parity classes and these
        audits are named here as deliberate exceptions rather than left to a
        guess.
        """
        claimed = {name for names in FIXTURES.values() for name in names}
        exempt = {
            "TestAnUninventoriedPublicTool.test_the_same_build_without_it_is_clean",
            "TestASurfaceNamingAMissingComponent.test_the_same_reference_vouched_for_resolves",
            "TestTheMcpSnapshotAndTheLiveServer."
            "test_a_snapshot_that_lost_a_tool_names_all_three_sources",
            "TestTheMcpSnapshotAndTheLiveServer."
            "test_a_snapshot_that_invented_a_prompt_is_refused_too",
            "TestTheMcpSnapshotAndTheLiveServer."
            "test_an_absent_snapshot_is_refused_rather_than_skipped",
            "TestUndeclaredSideEffects.test_every_effectful_channel_has_a_fixture",
            "TestUndeclaredSideEffects.test_the_same_surface_that_answers_is_not_a_finding",
            "TestStaleAllowances.test_the_allowance_a_silent_surface_uses_is_not_a_finding",
            "TestStaleAllowances."
            "test_the_repositorys_allowances_are_keyed_the_way_this_fixture_is",
            "TestVacuousProviders.test_the_application_asserts_all_five_of_those_floors",
            "TestVacuousProviders.test_a_floor_met_exactly_is_not_a_finding",
            "TestAHandEditedInventory.test_check_mode_wrote_nothing",
            "TestADerivedSourceFormatGap.test_the_format_it_does_declare_renders",
            "TestADerivedSourceFormatGap."
            "test_a_narrowed_declaration_with_no_reason_is_refused",
            "TestACheckoutSourceCalledBare.test_a_source_that_describes_a_checkout_called_with_none",
            "TestACheckoutSourceCalledBare.test_the_same_source_handed_a_checkout_renders",
            "TestACheckoutSourceCalledBare."
            "test_a_needs_input_declaration_the_provider_cannot_satisfy",
            "TestTheBindingLedgerEnumeration.test_an_eighth_entry_fails_the_exact_enumeration",
            "TestTheBindingLedgerEnumeration.test_the_ceiling_would_have_absorbed_it",
            "TestTheBindingLedgerEnumeration.test_the_real_ledger_is_what_the_real_reading_found",
            "TestTheBindingLedgerEnumeration."
            "test_the_bound_classes_do_not_include_the_unbound_one",
            "TestTheIdFormsD5aWidened."
            "test_the_form_accepts_its_spelling_and_refuses_its_neighbours",
            "TestTheIdFormsD5aWidened.test_every_widened_form_is_still_one_form_and_not_two",
            "TestTheIdFormsD5aWidened.test_the_root_route_keeps_its_documented_normalization",
            "TestTheIdFormsD5aWidened.test_a_brace_free_resource_and_a_template_are_two_ids",
        }
        parity = {
            "TestCliParity",
            "TestDiagnosticsParity",
            "TestConfigParity",
            "TestMcpParity",
            "TestStudi0Parity",
        }
        found: set[str] = set()
        for class_name, owner in sorted(globals().items()):
            if not (isinstance(owner, type) and class_name.startswith("Test")):
                continue
            if class_name in parity or class_name in {
                "TestThisBatteryIsHonest",
                "TestTheTwoBatteriesAccountForEveryCode",
            }:
                continue
            found.update(
                f"{class_name}.{method}"
                for method in vars(owner)
                if method.startswith("test_")
            )
        unrecorded = sorted(found - claimed - exempt)
        assert unrecorded == [], (
            f"these tests are in the battery and in no row of FIXTURES: "
            f"{unrecorded}. Either they fire a diagnostic — record it — or "
            f"they are a control, in which case name them in the exempt set."
        )

    @pytest.mark.parametrize("code", sorted(FIXTURES))
    def test_each_fired_code_is_a_diagnostic_name(self, code: str) -> None:
        assert _CODE_NAME.fullmatch(code), code

    def test_a_parity_class_exists_for_every_d_phase_provider(self) -> None:
        """T2's own completeness: five providers, five parity classes.

        Read off the floors table, which is read off the providers'
        constants — so a sixth D-phase reading arrives here as a red rather
        than as a silence.
        """
        for name, _floors in D_PHASE_FLOORS:
            expected = f"Test{name.capitalize()}Parity"
            owner = globals().get(expected)
            assert isinstance(owner, type), (
                f"{name} has no live-boundary parity class; D8 T2 is one per "
                f"provider, and a provider compared against nothing can drift "
                f"from the thing it describes without a test noticing."
            )


class TestTheTwoBatteriesAccountForEveryCode:
    """The handshake: neither battery may assume the other covers a code.

    C9's audit reads C9's table and the source tree, and is satisfied by a
    fixture *or* a deferral. That is complete on its own terms and blind on
    one axis: it cannot see this module, so it cannot tell whether a code's
    only proof has quietly moved here — or whether a code this battery is
    the natural home for has been left to a deferral nobody revisited.

    This class supplies the missing axis. C9's table is read out of C9's
    source with :mod:`ast`, never imported, and the universe is grepped
    here rather than borrowed, so the two readings are independent and can
    be compared. What is pinned is the *split*: which codes both batteries
    fire, which this one fires alone, and that nothing falls between them.
    """

    def test_the_c_phase_battery_is_still_where_its_table_can_be_read(self) -> None:
        """The handshake's precondition, asserted before it is relied on.

        A missing sibling would otherwise read as a battery with nothing to
        coordinate with, which is indistinguishable from agreement.
        """
        assert C_PHASE_BATTERY.is_file(), C_PHASE_BATTERY
        claims = c_phase_claims()
        assert len(claims) >= 15, sorted(claims)
        for code in sorted(claims):
            assert _CODE_NAME.fullmatch(code), code

    def test_a_code_constant_is_its_own_spelling(self) -> None:
        """What lets C9's table be read as names rather than as values.

        Every ``DOC_*`` constant in the source tree is defined as its own
        spelling. Reading C9's dict keys — which are the imported names —
        is therefore reading the codes, and this is the assumption made
        explicit rather than trusted.
        """
        from s0ma_dsl.docs_model import (
            application,
            compose,
            providers_catalog,
            providers_concepts,
            render_agent,
            resolve,
            validate,
        )

        checked = 0
        for module in (
            application,
            compose,
            providers_catalog,
            providers_concepts,
            render_agent,
            resolve,
            validate,
            derived_sources,
        ):
            for name in dir(module):
                if not _CODE_NAME.fullmatch(name):
                    continue
                checked += 1
                assert getattr(module, name) == name, f"{module.__name__}.{name}"
        assert checked >= len(CODE_UNIVERSE)

    def test_the_universe_is_read_from_the_source_tree(self) -> None:
        """This audit's own precondition: the grep found a tree to read."""
        assert DOCS_MODEL_SOURCE.is_dir()
        assert len(sorted(DOCS_MODEL_SOURCE.glob("*.py"))) >= 10
        assert len(CODE_UNIVERSE) >= len(FIXTURES)

    def test_every_code_in_the_tree_is_fired_or_deferred_by_one_of_the_two(
        self,
    ) -> None:
        """The completeness claim, taken across both batteries at once."""
        accounted = c_phase_claims() | set(FIXTURES) | set(DEFERRED_GATES)
        unclaimed = sorted(CODE_UNIVERSE - accounted)
        assert unclaimed == [], (
            f"{unclaimed} appear in the docs_model source tree and neither "
            f"battery fires them nor records them as deferred. Add a fixture "
            f"to whichever battery owns the phase that minted the code, and "
            f"a row to its table."
        )

    def test_this_battery_claims_nothing_outside_the_two_source_trees(self) -> None:
        """The other direction: a fixture for a code that has been retired."""
        universe = CODE_UNIVERSE | set(
            _CODE_NAME.findall(DERIVED_SOURCES_SOURCE.read_text(encoding="utf-8"))
        )
        stale = sorted(set(FIXTURES) - universe)
        assert stale == [], (
            f"{stale} are claimed here and appear in neither the docs_model "
            f"source tree nor the derived-source registry. Either the code "
            f"was renamed or retired — remove the row and the fixture."
        )

    def test_the_declared_overlap_is_the_real_one(self) -> None:
        """The anti-assumption clause, in the direction that matters most.

        If C9 drops a fixture for a code both batteries claim, the computed
        overlap shrinks and this fails by name — instead of the code
        silently becoming this battery's sole responsibility without anybody
        deciding that.
        """
        shared = sorted(set(FIXTURES) & c_phase_claims())
        assert shared == sorted(SHARED_WITH_C9), (
            f"the two batteries' shared coverage is {shared} and this module "
            f"declares {sorted(SHARED_WITH_C9)}. A code that left C9's table "
            f"is not automatically this one's to carry alone: decide, then "
            f"write the decision here."
        )

    def test_the_codes_only_this_battery_claims_are_the_declared_ones(self) -> None:
        """And the other direction, with the reason each is not C9's.

        ``DOC_SOURCE_FORMAT_UNSUPPORTED`` is the only one today: D7 minted
        it outside ``docs_model``, so it is outside the universe C9 audits
        and C9 correctly does not claim it. Left to C9's rules alone it
        would be an armed, minted code in nobody's table.
        """
        only_here = sorted(set(FIXTURES) - c_phase_claims())
        assert only_here == sorted(CLAIMED_ONLY_HERE), (
            f"this battery uniquely claims {only_here} and declares "
            f"{sorted(CLAIMED_ONLY_HERE)}."
        )
        for code in CLAIMED_ONLY_HERE:
            assert code not in CODE_UNIVERSE, (
                f"{code} is now in the docs_model source tree, which is the "
                f"universe C9 audits. It is no longer this battery's alone."
            )

    def test_no_code_this_battery_fires_is_recorded_as_deferred(self) -> None:
        """A gate cannot be both armed here and waiting for a later phase."""
        overlap = sorted(set(FIXTURES) & set(DEFERRED_GATES))
        assert overlap == [], (
            f"{overlap} are fired by this battery and recorded in "
            f"validate.DEFERRED_GATES. If the gate has armed, drop the "
            f"deferral; if it has not, drop the fixture claim."
        )

    def test_the_second_firing_site_this_battery_claims_is_a_real_second_site(
        self,
    ) -> None:
        """``DOC_SURFACE_UNCOVERED`` is raised from two modules, not one.

        C9's rule is that a code reached by two paths is two gates. The
        coverage gate lives in ``resolve.py`` and D6 added a second in
        ``application.py``; C9 proves the first and this battery proves the
        second. If the two ever became one site, this battery's claim would
        be a duplicate of C9's rather than a complement, and that is worth
        finding out from a test rather than from a reader.
        """
        from s0ma_dsl.docs_model import application, resolve

        # One spelling: the application imports the resolver's constant
        # rather than minting a second name that renders identically.
        assert "DOC_SURFACE_UNCOVERED" in resolve.__all__
        assert (
            vars(application)["DOC_SURFACE_UNCOVERED"]
            == resolve.DOC_SURFACE_UNCOVERED
        )

        # Two gates: two callables, each defined in its own module.
        assert application.check_surface_index.__module__ == application.__name__
        assert resolve.check_coverage.__module__ == resolve.__name__
        assert (
            application.check_surface_index.__qualname__
            != resolve.check_coverage.__qualname__
        )

        # Both live in one composition, so neither is a gate nothing runs.
        source = Path(application.__file__).read_text(encoding="utf-8")
        assert "check_surface_index(" in source
        assert "check_coverage(" in source
