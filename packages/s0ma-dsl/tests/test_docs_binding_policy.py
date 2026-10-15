"""The binding ledger and the side-effect ledger, as counted artifacts.

Milestone D5b of the docs-function plan (internal) §9. The D phase gave the
composition five readings of what s0ma *serves*, and with them two
questions the architecture plan requires an answer to for every served
surface: what implements it (§6.3, ``component_refs`` required), and what
calling it does to the world (§6.3's side-effect vocabulary).

Most surfaces answer both from their own source. This module is about the
ones that do not, and it exists because §6.3's rule for them is not "add
an exception" but "add a *counted, reviewable* exception": the difference
between an ignore file and a ledger is that somebody has to look at a
ledger, and something has to make them.

**This module is that something.** Every exception is enumerated by id or
counted against a stated number, so the ledger cannot grow by one without
a test failing and naming what grew. That failure is the review moment.
Fixing it is never "raise the number" on its own — it is deciding whether
the new exception should exist, and then recording the decision.

**Four rulings D5b took, and where each one is proved below.**

1. *``class-granular`` binding counts as bound.* Twenty-eight commands
   dispatch to a method of ``S0maCLI``, which is a registered component;
   the record names the class, because a method is not separately
   registered, and its exception names the method. That is one honest
   description of a real binding, not an unbound surface with a note —
   ``TestTheCliLedger``.
2. *Seven handlers stay unregistered, and the list is the artifact.*
   Registering them changes what the framework says about itself, which
   is a product decision. D5b declines to take it and hands over the list
   — ``TestTheUnregisteredHandlers``.
3. *Core's twenty-nine, enumerated exactly.* Twelve MCP tools, eight MCP
   resources and nine Python exports that reach no component *because
   there is none to reach* — ``TestCoresUnboundSurfaces``.
4. *Three sources may stay silent about their effects, in writing, and
   the permission expires by itself.* The plan asked for the honest-empty
   case to be handled "without excusing the asymmetry"; what makes this
   not an excuse is that an allowance no surface uses is a finding —
   ``TestTheSideEffectAllowances``.

**Nothing here parses prose.** The CLI hands over its ledger as data
(``CliProvider.exceptions()``), the hand-classified effects are tables in
the providers that own them, and the unbound set is read off
``component_refs``. A ledger derived from the wording of an exception
would move when somebody improved a sentence.
"""

from __future__ import annotations

import collections
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.docs_model.application import (
    BOUND_CLASSES,
    SIDE_EFFECT_ALLOWANCES,
    UNBOUND_CEILING,
    UNREGISTERED_HANDLERS,
    build,
    registry,
)
from s0ma_dsl.docs_model.providers_cli import (
    BOUND_DIRECTLY,
    BOUND_TO_OWNING_CLASS,
    UNBOUND_MACHINERY,
    CliProvider,
)
from s0ma_dsl.docs_model.validate import (
    CHANNEL_EFFECTS,
    DOC_GATE_VACUOUS,
    DOC_SIDE_EFFECT_UNDECLARED,
    SIDE_EFFECT_WORDS,
    check_side_effects,
)

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.application import Build
    from s0ma_dsl.docs_model.records import SurfaceRecord

REPO_ROOT = Path(__file__).resolve().parents[3]


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


@pytest.fixture(scope="module")
def composed() -> Build:
    """One build of the real checkout. The ledger is about this build."""
    return build(REPO_ROOT)


@pytest.fixture(scope="module")
def surfaces(composed: Build) -> tuple[SurfaceRecord, ...]:
    return composed.bundle.surfaces


def _unbound(surfaces: tuple[SurfaceRecord, ...]) -> list[SurfaceRecord]:
    """Every surface that reaches no registered component.

    ``component_refs`` and nothing else. Whether a surface carries a
    written exception is a different axis — ``check_surface_binding`` says
    so in as many words — and conflating them is how a ledger of
    exceptions turns into a ledger of records that happen to have prose.
    """
    return [surface for surface in surfaces if not surface.component_refs]


# ---------------------------------------------------------------------------
# Ruling 1 — the CLI ledger, and what "bound" means for a method
# ---------------------------------------------------------------------------


class TestTheCliLedger:
    """Forty-four commands in three classes, and only one class is unbound."""

    @pytest.fixture(scope="class")
    def ledger(self) -> dict[str, int]:
        return dict(collections.Counter(cls for _, cls in CliProvider().exceptions()))

    def test_the_three_classes_are_counted_exactly(self, ledger: dict[str, int]) -> None:
        """The ledger as of D5b. Any movement is a decision, so it fails here.

        Twenty-eight, nine and seven. A command added or removed changes
        one of these numbers and this test names which — which is the whole
        point of writing them down rather than asserting a total.

        `adopt scan` (beta-prep-1-retrofit B4) was the twenty-third,
        `adopt init` (C1) the twenty-fourth, `adopt draft` (D4) the
        twenty-fifth, `adopt baseline` and `adopt verify-parity` (E2) the
        twenty-sixth and twenty-seventh, and `adopt status` (E3) the
        twenty-eighth: each handler is a method of ``S0maCLI`` written as
        a one-line delegation for exactly this reason, so the product grew
        six commands without the unbound ledger moving at all.
        """
        assert ledger == {
            BOUND_TO_OWNING_CLASS: 28,
            BOUND_DIRECTLY: 9,
            UNBOUND_MACHINERY: 7,
        }
        assert sum(ledger.values()) == 44

    def test_class_granular_counts_as_bound(self) -> None:
        """Ruling 1, stated where the constant that carries it lives."""
        assert frozenset({BOUND_DIRECTLY, BOUND_TO_OWNING_CLASS}) == BOUND_CLASSES
        assert UNBOUND_MACHINERY not in BOUND_CLASSES

    def test_every_bound_class_really_reaches_a_component(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        """The ruling is only honest if the data agrees with it.

        A ruling that ``class-granular`` counts as bound would be a
        convenient fiction if any of those twenty-eight records reached
        nothing. Each is looked up in the composed bundle and asked for
        its ``component_refs``, so the claim is about the surfaces this
        build really emitted.
        """
        by_id = {surface.id: surface for surface in surfaces}
        for identifier, binding_class in CliProvider().exceptions():
            surface = by_id[identifier]
            if binding_class in BOUND_CLASSES:
                assert surface.component_refs, identifier
            else:
                assert not surface.component_refs, identifier

    def test_a_class_granular_exception_names_the_method_it_stands_for(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        """What makes the coarser binding honest rather than merely passing.

        The record names ``S0maCLI`` because that is what is registered.
        The exception names the method the dispatch actually reaches, so a
        reader who wants the callable is not left at the class. Without
        that sentence the ruling would be a way of rounding a hard
        question off.
        """
        by_id = {surface.id: surface for surface in surfaces}
        granular = [
            identifier
            for identifier, binding_class in CliProvider().exceptions()
            if binding_class == BOUND_TO_OWNING_CLASS
        ]
        assert len(granular) == 28
        for identifier in granular:
            surface = by_id[identifier]
            assert surface.component_refs == ("component:s0ma_dsl.cli.main.S0maCLI",)
            assert "a method of a registered component" in surface.manual_exception
            assert "S0maCLI._cmd_" in surface.manual_exception


# ---------------------------------------------------------------------------
# Ruling 2 — the seven nobody registers
# ---------------------------------------------------------------------------


class TestTheUnregisteredHandlers:
    """The D5-inherited decision list, enumerated and handed on."""

    def test_the_seven_are_exactly_these(self) -> None:
        """Enumerated by id. An eighth is a decision, and this is where it lands."""
        assert UNREGISTERED_HANDLERS == (
            "cli:s0ma/adopt/file",
            "cli:s0ma/feedback/delete",
            "cli:s0ma/feedback/drafts",
            "cli:s0ma/feedback/enroll",
            "cli:s0ma/feedback/list",
            "cli:s0ma/feedback/submit",
            "cli:s0ma/migrate/grammar",
        )

    def test_the_list_is_what_the_provider_actually_found(self) -> None:
        """Read against the live reading, not against itself.

        A hand-written list that nothing compares to the parser is a list
        that rots the first time a command is renamed. This is the
        comparison: the provider classifies each command by asking the
        handler what registers it, and the two answers have to match.
        """
        found = tuple(
            sorted(
                identifier
                for identifier, binding_class in CliProvider().exceptions()
                if binding_class == UNBOUND_MACHINERY
            )
        )
        assert found == UNREGISTERED_HANDLERS

    def test_five_of_the_seven_are_the_feedback_family(self) -> None:
        """Why this is a product decision rather than a documentation one.

        The shape of the list is the argument. Five of seven are one
        family of commands written as plain functions; registering them
        changes what the framework says about itself, which is not a call
        the documentation build gets to make on the product's behalf.
        """
        family = [name for name in UNREGISTERED_HANDLERS if "feedback" in name]
        assert len(family) == 5

    def test_each_one_says_in_writing_what_it_reaches(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        """§6.3's rule: an exception, written, naming the callable."""
        by_id = {surface.id: surface for surface in surfaces}
        for identifier in UNREGISTERED_HANDLERS:
            surface = by_id[identifier]
            assert not surface.component_refs, identifier
            assert "which nothing registers" in surface.manual_exception, identifier


# ---------------------------------------------------------------------------
# Ruling 3 — core's twenty-nine
# ---------------------------------------------------------------------------

#: Every core surface that reaches no registered component, exactly.
#:
#: Three families, and the reason is the same in all three: there is
#: nothing to reach. The MCP SDK's public listing gives a tool or a
#: resource its name and its description and not the callable behind it,
#: and reaching into the server's private managers would bind a record to
#: an SDK internal. A ``python:`` surface is a module-level name of core's
#: public API, which the component inventory holds nothing for *because it
#: is not a component* — its id is its binding.
CORE_UNBOUND: tuple[str, ...] = (
    "mcp:resource/s0ma://docs/architecture",
    "mcp:resource/s0ma://docs/compliance-rules",
    "mcp:resource/s0ma://docs/registered-docs",
    "mcp:resource/s0ma://docs/user-guide",
    "mcp:resource/s0ma://model/component-template",
    "mcp:resource/s0ma://model/docs-for/{component}",
    "mcp:resource/s0ma://model/examples-for/{component}",
    "mcp:resource/s0ma://model/registry-summary",
    "mcp:tool/check_health",
    "mcp:tool/describe_system",
    "mcp:tool/explain_dependency",
    "mcp:tool/find_component",
    "mcp:tool/get_compliance_checklist",
    "mcp:tool/get_component_example",
    "mcp:tool/get_examples_for",
    "mcp:tool/get_extension_points",
    "mcp:tool/get_impact",
    "mcp:tool/learn_about_s0ma",
    "mcp:tool/query_system",
    "mcp:tool/suggest_fix",
    "python:s0ma.HASH_ALGORITHM_VERSION",
    "python:s0ma.__version__",
    "python:s0ma.canonicalize",
    "python:s0ma.content_hash",
    "python:s0ma.initialize",
    "python:s0ma.register_doc_guide",
    "python:s0ma.register_doc_ref",
    "python:s0ma.register_example",
    "python:s0ma.verify",
)


class TestCoresUnboundSurfaces:
    """Twenty-nine ids, written out, so a thirtieth cannot arrive quietly."""

    @requires_checkout
    def test_the_twenty_nine_are_exactly_these(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        found = tuple(
            sorted(
                surface.id
                for surface in _unbound(surfaces)
                if surface.provenance.adapter_id == "core"
            )
        )
        assert found == CORE_UNBOUND
        assert len(CORE_UNBOUND) == 29

    @requires_checkout
    def test_they_fall_into_the_three_families_the_reason_names(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        """Twelve tools, eight resources, nine exports.

        Counted per family rather than in total, because the three have
        different reasons and different ways of being closed: annotations
        would answer the tools, a model change would answer the
        resources, and a person reading nine functions would answer the
        exports.
        """
        by_channel = collections.Counter(
            surface.channel
            for surface in _unbound(surfaces)
            if surface.provenance.adapter_id == "core"
        )
        assert dict(by_channel) == {
            "mcp_tool": 12,
            "mcp_resource": 8,
            "python": 9,
        }


# ---------------------------------------------------------------------------
# The ceiling over the whole ledger
# ---------------------------------------------------------------------------


class TestTheCountedCeiling:
    """One hundred and sixty-nine unbound today, and a stated ceiling of 175."""

    @requires_checkout
    def test_the_ledger_is_within_its_ceiling(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        unbound = _unbound(surfaces)
        assert len(unbound) <= UNBOUND_CEILING, sorted(
            surface.id for surface in unbound
        )
        assert UNBOUND_CEILING == 175

    @requires_checkout
    def test_the_ledger_is_these_four_sources_and_no_others(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        """The shape, which is what the ceiling is a backstop for.

        Thirty-six of these are decisions about particular surfaces and
        are enumerated by id above. The other hundred and thirty-three are
        one ruling each about a whole source: a diagnostic code is a label
        on a report and a configuration key is a value in a table, and
        neither has an implementing component by its nature. A fifth
        source appearing here is a new *kind* of unbound thing, which is
        what this test refuses.
        """
        counted = collections.Counter(
            surface.provenance.adapter_id for surface in _unbound(surfaces)
        )
        assert dict(counted) == {
            "cli": 7,
            "config": 19,
            "core": 29,
            "diagnostics": 114,
        }
        assert sum(counted.values()) == 169

    @requires_checkout
    def test_no_surface_is_unbound_and_silent(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        """§6.3's actual requirement, which the ceiling exists to bound.

        Zero silent unbounds. Every one of the hundred and sixty-nine
        says, in writing, why it reaches nothing — that is what makes it
        an entry in a ledger rather than a gap.
        """
        silent = [
            surface.id for surface in _unbound(surfaces) if not surface.manual_exception.strip()
        ]
        assert silent == []

    @requires_checkout
    def test_the_composed_build_reports_nothing(self, composed: Build) -> None:
        """The ledger is not a list of things the build tolerates in the red.

        Every gate the application runs is green over this composition.
        An exception that still produced a finding would be an exception
        that is not doing its job.
        """
        assert [finding.rendered() for finding in composed.findings] == []


# ---------------------------------------------------------------------------
# Ruling 4 — the side-effect ledger
# ---------------------------------------------------------------------------

#: The two hand-classified effect tables, which are the *other* axis: a
#: surface here reaches a component perfectly well and still needed a
#: person to say what calling it does, because no annotation carried the
#: fact. Four in all — core's one unsafe REST method, and the three
#: authoring tools whose hints escalate past the ordinary local case.
HAND_CLASSIFIED_EFFECTS: tuple[str, ...] = (
    "mcp:tool/run_example",
    "mcp:tool/submit_feedback",
    "mcp:tool/verify_host",
    "rest:POST:/self/query",
)


class TestTheSideEffectAllowances:
    """Which sources may say nothing, why, and what makes it not an excuse."""

    def test_exactly_three_sources_may_be_silent(self) -> None:
        assert sorted(SIDE_EFFECT_ALLOWANCES) == [
            ("core", "mcp_resource"),
            ("core", "mcp_tool"),
            ("core", "python"),
        ]

    def test_every_allowance_says_why_and_what_would_close_it(self) -> None:
        """An allowance without an exit is an exemption wearing a reason.

        Each entry has to say both what it cannot answer and what would
        make it able to. The second half is the one that matters: it is
        the difference between "this cannot be known" and "nobody has
        done it yet", and only one of those should survive review.
        """
        for key, reason in SIDE_EFFECT_ALLOWANCES.items():
            assert reason.strip(), key
            assert "Closed by" in reason, key

    def test_the_asymmetry_is_named_rather_than_smoothed_over(self) -> None:
        """The plan's ask, in the text of the allowance it is about.

        Core's MCP tools declare no ``ToolAnnotations`` and the authoring
        server's do. The allowance says so, which is what stops it reading
        as a property of MCP rather than as a gap on one side of it.
        """
        tools = SIDE_EFFECT_ALLOWANCES[("core", "mcp_tool")]
        assert "ToolAnnotations" in tools
        assert "readOnlyHint" in tools
        assert "the silence is core's" in tools

    @requires_checkout
    def test_every_allowance_is_used_by_this_build(self, composed: Build) -> None:
        """The expiry mechanism, proved on the real composition.

        An allowance no surface uses is ``DOC_GATE_VACUOUS``. So these
        three cannot outlive the silence they permit: the day core
        declares annotations, this build starts failing until somebody
        removes the permission.
        """
        assert (
            check_side_effects(composed.bundle, SIDE_EFFECT_ALLOWANCES) == []
        )
        stale = check_side_effects(
            composed.bundle,
            {**SIDE_EFFECT_ALLOWANCES, ("nobody", "cli"): "Never read."},
        )
        assert [finding.code for finding in stale] == [DOC_GATE_VACUOUS]

    @requires_checkout
    def test_removing_an_allowance_turns_its_surfaces_red(self, composed: Build) -> None:
        """The other direction: the permission is load-bearing, not decorative.

        Drop the tools' allowance and twelve surfaces report that nobody
        has said what calling them does. That count is the size of the
        debt the allowance records, stated as a number rather than
        implied.
        """
        without = {
            key: reason
            for key, reason in SIDE_EFFECT_ALLOWANCES.items()
            if key != ("core", "mcp_tool")
        }
        findings = check_side_effects(composed.bundle, without)
        assert [finding.code for finding in findings] == [DOC_SIDE_EFFECT_UNDECLARED] * 12


class TestTheHandClassifiedEffects:
    """Four surfaces where a person read the code and wrote down what they found."""

    def test_the_four_are_exactly_these(self) -> None:
        from s0ma_dsl.docs_model.providers_core import _HAND_CLASSIFIED as CORE_TABLE
        from s0ma_dsl.docs_model.providers_mcp import _HAND_CLASSIFIED as MCP_TABLE

        assert tuple(sorted({*CORE_TABLE, *MCP_TABLE})) == HAND_CLASSIFIED_EFFECTS

    @requires_checkout
    def test_each_carries_its_effects_and_a_reason(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        by_id = {surface.id: surface for surface in surfaces}
        for identifier in HAND_CLASSIFIED_EFFECTS:
            surface = by_id[identifier]
            assert surface.side_effects, identifier
            assert "by hand" in surface.manual_exception, identifier

    @requires_checkout
    def test_the_approval_and_network_facts_reach_the_surfaces_that_have_them(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        """D5's acceptance, in the records rather than in prose about them.

        "feedback submit/prepare and installer-touching surfaces show
        approval/network facts." Submitting feedback asks the user to
        approve the exact feedback data and only then sends it; verifying
        a host runs an installer under the user's decision. Both facts are
        on the record, and both were classified by a person because no
        annotation carries either.
        """
        by_id = {surface.id: surface for surface in surfaces}
        submit = by_id["mcp:tool/submit_feedback"]
        assert set(submit.side_effects) == {"approval", "network", "write"}

        host = by_id["mcp:tool/verify_host"]
        assert set(host.side_effects) == {"approval", "subprocess", "write"}

        enroll = by_id["cli:s0ma/feedback/enroll"]
        assert "credential" in enroll.side_effects
        assert "network" in enroll.side_effects


# ---------------------------------------------------------------------------
# The convention itself
# ---------------------------------------------------------------------------


class TestTheSideEffectConvention:
    """One convention across ten readings, and the table that classifies it."""

    @requires_checkout
    def test_every_surface_but_the_allowed_ones_answers(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        """The convention, stated over the whole composition.

        ``()`` is the unanswered question and ``('none',)`` is the answer
        "nothing". Two hundred and sixty-one surfaces, twenty-nine of them
        allowed to be silent, and no third case.
        """
        silent = [surface for surface in surfaces if not surface.side_effects]
        assert len(surfaces) == 261
        assert len(silent) == 29
        for surface in silent:
            key = (surface.provenance.adapter_id, surface.channel)
            assert key in SIDE_EFFECT_ALLOWANCES, surface.id

    @requires_checkout
    def test_every_declared_word_is_in_the_vocabulary(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        used = {word for surface in surfaces for word in surface.side_effects}
        assert used <= SIDE_EFFECT_WORDS
        assert used, "no surface declares anything, which is not a passing build"

    @requires_checkout
    def test_every_channel_this_build_serves_is_classified(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        """A channel the table does not name is a finding, so none may be missing.

        The nine channels this composition emits, listed here as well as
        classified there: an unclassified tenth would be caught by the
        gate, and a *classified* tenth that nothing emits would not be —
        so the two sets are compared both ways.
        """
        served = {surface.channel for surface in surfaces}
        assert served == {
            "cli",
            "config",
            "diagnostic",
            "mcp_prompt",
            "mcp_resource",
            "mcp_tool",
            "python",
            "rest",
            "studi0",
        }
        assert served == set(CHANNEL_EFFECTS)

    def test_the_two_described_channels_are_the_ones_d2_minted(self) -> None:
        """Which channels name a thing rather than a way to reach one.

        Both are D2's, and D2 said why when it minted them: neither is one
        of §6.3's transport words, because a diagnostic is emitted by every
        mechanism rather than served over one, and a configuration key is
        read by the loader rather than called. The table is where that
        reasoning became checkable.
        """
        described = {name for name, invocable in CHANNEL_EFFECTS.items() if not invocable}
        assert described == {"config", "diagnostic"}

    def test_the_artifact_channel_is_deliberately_unclassified(self) -> None:
        """§6.3 names it and nothing emits one, so nobody has answered for it.

        Classifying it now would record a guess as a decision. Leaving it
        out means the first provider to emit an artifact surface is asked,
        which is the same rule every other unclassified channel gets.
        """
        assert "artifact" not in CHANNEL_EFFECTS


# ---------------------------------------------------------------------------
# The composition the ledger is about
# ---------------------------------------------------------------------------


class TestTheLedgerDescribesTheRealComposition:
    """Guards against a ledger that is true of a build nobody runs."""

    @requires_checkout
    def test_all_eleven_providers_are_registered(self) -> None:
        """Ten through the D phase; E1 added the authored journeys."""
        assert len(tuple(registry(REPO_ROOT).ids())) == 11

    @requires_checkout
    def test_the_surface_count_is_what_the_d_phase_added(
        self, surfaces: tuple[SurfaceRecord, ...]
    ) -> None:
        """Forty-three before D5b, two hundred and sixty-one today.

        The C phase composed forty-three surfaces, all of them core's.
        Wiring the five D-phase readings added a hundred and ninety-nine:
        the command line, the diagnostics, the configuration keys, the
        authoring server and the viewer. The quick reference's data twin
        (owner ruling 2026-09-29, surface contract R5) is the two hundred
        and sixty-first. A number that moves without a milestone behind it
        is a reading that changed shape.
        """
        assert len(surfaces) == 261
        by_adapter = collections.Counter(
            surface.provenance.adapter_id for surface in surfaces
        )
        assert dict(by_adapter) == {
            "cli": 44,
            "config": 19,
            "core": 43,
            "diagnostics": 114,
            "mcp": 36,
            "studi0": 5,
        }
