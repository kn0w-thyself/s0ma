"""Gates for E7 — ``journey:studi0-feedback``, its guide, and its evidence.

Milestone E7 of the docs-function plan (internal) §10. This path is the one
where a reader is asked for something irreversible, so the things held in
place here are the ones that make asking honest:

* **the path** — five steps over surfaces this build really serves, in the
  order a reader walks them, composing with nothing to report;
* **the approval boundary, in both directions** (T4) — declared on exactly
  the two steps whose surfaces ask for an approval, and
  ``DOC_APPROVAL_UNDECLARED`` red under a mutation in either direction.
  Both mutations are made against *this* journey rather than a stub,
  because a gate proven on a fixture is a gate proven on a fixture;
* **the evidence stops at the boundary** (T2) — the transcript runs the two
  approval-class commands for real and records that s0ma refuses to compose
  or send anything without a person at the keyboard. Nothing in this suite
  can reach the network: the two commands that could exit 5 with "Nothing
  was sent." on their error stream, and that is the assertion;
* **the guide agrees with the evidence** (T3) — every command in
  ``docs/guides/studi0-feedback.md`` is one the transcript replays, byte for
  byte, save the one command that serves until it is interrupted;
* **the voice rule** (T3) — the journey record, the fixture and the guide
  prose are all checked for the words this product does not use. The word
  that matters here is the one this whole path is about.

The four journey gates themselves are fired in the C9 battery
(``test_docs_model_negative.py``); the format and replay machinery is E2's
(``test_docs_evidence.py``). What is here is this milestone's own path.

**Cost.** The fixture is replayed twice, once for the green check and once
for the determinism comparison, cached for the whole module.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.cli.feedback_commands import (
    EXIT_VALIDATION,
    NON_INTERACTIVE_REFUSAL,
    PREVIEW_HEADING,
    SEND_QUESTION,
)
from s0ma_dsl.docs_model.application import build as build_documentation
from s0ma_dsl.docs_model.evidence import (
    CHANNEL_CLI,
    CommandStep,
    EvidenceLibrary,
    Replay,
    check_evidence_voice,
    compare,
    replay,
)
from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.providers_concepts import FORBIDDEN_IN_AUTHORED_PROSE
from s0ma_dsl.docs_model.providers_journeys import check_journey_voice
from s0ma_dsl.docs_model.records import JourneyRecord, JourneyStep
from s0ma_dsl.docs_model.validate import (
    APPROVAL_EFFECT,
    DOC_APPROVAL_UNDECLARED,
    TEACHING_PREREQUISITE,
    ReferenceIndex,
    check_journeys,
)

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.evidence import EvidenceRecord

REPO_ROOT = Path(__file__).resolve().parents[3]

JOURNEY_ID = "journey:studi0-feedback"
EVIDENCE_ID = "example:transcript/studi0-feedback"
EVIDENCE_SOURCE = "docs/s0ma_src/evidence/studi0-feedback.json"
GUIDE = "docs/guides/studi0-feedback.md"

#: The path as authored: each step's surface, and whether that step is one
#: where the reader is asked for something irreversible. Written down
#: rather than read off the record, because the whole milestone is the
#: claim that *these* five surfaces in *this* order are the reviewed
#: feedback path, and a step quietly appearing or moving should fail here
#: by name rather than pass by agreeing with itself.
EXPECTED_STEPS: tuple[tuple[str, bool], ...] = (
    ("cli:s0ma/studi0", False),
    ("studi0:action/api/graph", False),
    ("cli:s0ma/feedback", True),
    ("cli:s0ma/feedback/drafts", False),
    ("cli:s0ma/feedback/submit", True),
)

#: The two ideas this path leaves a reader with, in the order they are met.
EXPECTED_TAUGHT: tuple[str, ...] = ("concept:proprioception", "concept:feedback")

#: The one command the guide shows that no transcript can replay: it binds
#: a loopback port and serves until it is interrupted, which is the same
#: reason the fixture's ledger gives for not covering the step. Pinned as a
#: set of one so that a *second* unreplayable command appearing in the
#: guide is a failure rather than a silent widening.
UNREPLAYABLE_IN_GUIDE: frozenset[str] = frozenset({"s0ma studi0"})

#: The commands whose whole point is that they stop at the approval
#: boundary, with the exit code the feedback family's own contract gives a
#: run that cannot be honoured as invoked.
REFUSED_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("s0ma", "feedback", "-m", "the graph view did not say which reading it was showing"),
    ("s0ma", "feedback", "submit", "fbd_1a2b3c4d"),
)

_FENCE = re.compile(r"^```(?P<info>[A-Za-z0-9_-]*)\s*$")


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


# ---------------------------------------------------------------------------
# What every test reads, read once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live() -> Any:
    """The whole documentation build, composed once for this module."""
    return build_documentation(REPO_ROOT)


@pytest.fixture(scope="module")
def journey(live: Any) -> JourneyRecord:
    """This milestone's journey, as the live composition holds it."""
    for record in live.bundle.journeys:
        if normalize_id(record.id) == normalize_id(JOURNEY_ID):
            return record
    raise AssertionError(f"{JOURNEY_ID} is not in the composed build")


@pytest.fixture(scope="module")
def library() -> EvidenceLibrary:
    """This repository's evidence, read once."""
    return EvidenceLibrary.load(REPO_ROOT)


@pytest.fixture(scope="module")
def fixture(library: EvidenceLibrary) -> EvidenceRecord:
    """This milestone's transcript fixture."""
    return library.by_id(EVIDENCE_ID)


@pytest.fixture(scope="module")
def replays(fixture: EvidenceRecord) -> tuple[Replay, Replay]:
    """Two replays of the fixture, run once for the whole module."""
    return replay(fixture), replay(fixture)


@pytest.fixture(scope="module")
def guide_text() -> str:
    """The guide, read as the bytes it is committed as."""
    return (REPO_ROOT / GUIDE).read_text(encoding="utf-8")


def _commands_in(text: str) -> list[str]:
    """Every command line inside a ``bash`` fence, in document order.

    Fenced blocks only, and only the ``bash`` ones: an inline mention in a
    sentence is prose about a command, while a fenced line is the thing a
    reader copies, and only the second one has to be replayable.
    """
    found: list[str] = []
    info: str | None = None
    for line in text.splitlines():
        fence = _FENCE.match(line)
        if fence is not None:
            info = None if info is not None else fence.group("info")
            continue
        if info == "bash" and line.startswith("s0ma "):
            found.append(line)
    return found


def _rendered(argv: tuple[str, ...]) -> str:
    """One argv as a reader would have typed it — the replay's own rendering."""
    return " ".join(part if " " not in part else f'"{part}"' for part in argv)


def _with_steps(record: JourneyRecord, steps: tuple[JourneyStep, ...]) -> JourneyRecord:
    """The same journey with different steps, for a one-field mutation."""
    return JourneyRecord(
        id=record.id,
        intent=record.intent,
        steps=steps,
        recovery_paths=record.recovery_paths,
        concepts_taught=record.concepts_taught,
        concepts_required=record.concepts_required,
        evidence=record.evidence,
    )


def _approval_findings(live: Any, record: JourneyRecord) -> list[Any]:
    """``check_journeys``' approval half, over one journey, against the real build.

    The real surfaces decide the answer — the gate reads each step's
    surface record for the ``approval`` effect — so the mutation is made
    against the composed bundle rather than a hand-built one, and the
    findings are filtered to the single code under test because the other
    three gates in that function are not this test's question.
    """
    single = replace(live.bundle, journeys=(record,))
    return [
        item
        for item in check_journeys(single, ReferenceIndex.of(single))
        if item.code == DOC_APPROVAL_UNDECLARED
    ]


# ---------------------------------------------------------------------------
# The path (T1)
# ---------------------------------------------------------------------------


@requires_checkout
class TestThePath:
    """Five steps over surfaces this build serves, in the authored order."""

    def test_the_steps_are_the_ones_this_milestone_authored(
        self, journey: JourneyRecord
    ) -> None:
        found = tuple(
            (step.surface, bool(step.approval_boundary.strip())) for step in journey.steps
        )
        assert found == EXPECTED_STEPS

    def test_this_journey_composes_with_nothing_to_report(self, live: Any) -> None:
        """Filtered to this milestone's own records, per the wave protocol."""
        mine = [
            item.rendered()
            for item in live.findings
            if JOURNEY_ID in item.rendered() or EVIDENCE_ID in item.rendered()
        ]
        assert mine == []

    def test_every_step_names_a_surface_this_build_really_serves(
        self, live: Any, journey: JourneyRecord
    ) -> None:
        served = {normalize_id(record.id) for record in live.bundle.surfaces}
        for step in journey.steps:
            assert normalize_id(step.surface) in served, step.surface
        for path in journey.recovery_paths:
            assert normalize_id(path.next_surface) in served, path.next_surface

    def test_the_recovery_failure_is_one_a_step_of_this_path_declares(
        self, live: Any, journey: JourneyRecord
    ) -> None:
        """A recovery is written against a failure that really happens here.

        ``NOT_BUILT`` is a route error and no diagnostic, so the only thing
        that can answer for it is a step surface's own record — and exactly
        one of this journey's steps may declare it, or a reader who has just
        seen it cannot tell which step they are recovering from.
        """
        surfaces = {normalize_id(record.id): record for record in live.bundle.surfaces}
        for path in journey.recovery_paths:
            naming = [
                surfaces[normalize_id(step.surface)].id
                for step in journey.steps
                if path.when in surfaces[normalize_id(step.surface)].errors
            ]
            assert naming == ["studi0:action/api/graph"], (path.when, naming)

    def test_the_teaching_order_holds_against_the_authored_concept_graph(
        self, live: Any, journey: JourneyRecord
    ) -> None:
        concepts = {normalize_id(record.id): record for record in live.bundle.concepts}
        assert journey.concepts_taught == EXPECTED_TAUGHT
        scope = {normalize_id(item) for item in journey.concepts_required}
        for taught in journey.concepts_taught:
            record = concepts[normalize_id(taught)]
            scope.add(normalize_id(taught))
            for relation, target in record.related_concepts:
                if relation != TEACHING_PREREQUISITE:
                    continue
                assert normalize_id(target) in scope, (taught, target)

    def test_the_file_is_utf8_with_line_feeds_and_one_trailing_newline(self) -> None:
        for relative in (
            "docs/s0ma_src/journeys/studi0-feedback.json",
            EVIDENCE_SOURCE,
            GUIDE,
        ):
            raw = (REPO_ROOT / relative).read_bytes()
            assert b"\r" not in raw, relative
            assert raw.endswith(b"\n") and not raw.endswith(b"\n\n"), relative
            raw.decode("utf-8")


# ---------------------------------------------------------------------------
# The approval boundary, in both directions (T1, T4)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheApprovalBoundary:
    """Declared exactly where one is crossed — and nowhere else."""

    def test_a_boundary_is_declared_on_every_step_whose_surface_asks(
        self, live: Any, journey: JourneyRecord
    ) -> None:
        surfaces = {normalize_id(record.id): record for record in live.bundle.surfaces}
        for step in journey.steps:
            asks = APPROVAL_EFFECT in surfaces[normalize_id(step.surface)].side_effects
            assert bool(step.approval_boundary.strip()) is asks, step.surface

    def test_the_path_as_authored_reports_no_approval_finding(
        self, live: Any, journey: JourneyRecord
    ) -> None:
        assert _approval_findings(live, journey) == []

    def test_removing_the_boundary_from_the_send_step_is_red(
        self, live: Any, journey: JourneyRecord
    ) -> None:
        """The direction that matters most: an irreversible step, unannounced."""
        send = journey.steps[-1]
        assert send.surface == "cli:s0ma/feedback/submit"
        silent = JourneyStep(
            surface=send.surface,
            purpose=send.purpose,
            expected_outcome=send.expected_outcome,
            approval_boundary="",
        )
        found = _approval_findings(
            live, _with_steps(journey, (*journey.steps[:-1], silent))
        )
        assert len(found) == 1
        assert "cli:s0ma/feedback/submit" in found[0].message
        assert APPROVAL_EFFECT in found[0].message

    def test_declaring_a_boundary_where_nothing_is_asked_is_red(
        self, live: Any, journey: JourneyRecord
    ) -> None:
        """The other direction: a prompt that never comes, taught as one that does."""
        listing = journey.steps[3]
        assert listing.surface == "cli:s0ma/feedback/drafts"
        invented = JourneyStep(
            surface=listing.surface,
            purpose=listing.purpose,
            expected_outcome=listing.expected_outcome,
            approval_boundary="You are approving something here.",
        )
        found = _approval_findings(
            live,
            _with_steps(
                journey, (*journey.steps[:3], invented, *journey.steps[4:])
            ),
        )
        assert len(found) == 1
        assert "cli:s0ma/feedback/drafts" in found[0].message
        assert "no approval is asked" in found[0].message


# ---------------------------------------------------------------------------
# The evidence, replayed for real (T2)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheEvidence:
    """The transcript walks this path as far as consent allows, and stops."""

    def test_the_fixture_evidences_this_journey_from_the_file_it_is_cited_at(
        self, fixture: EvidenceRecord, journey: JourneyRecord
    ) -> None:
        assert fixture.journey == JOURNEY_ID
        assert fixture.channel == CHANNEL_CLI
        assert [(item.id, item.source) for item in journey.evidence] == [
            (EVIDENCE_ID, EVIDENCE_SOURCE)
        ]
        assert fixture.source == EVIDENCE_SOURCE

    def test_the_ledger_accounts_for_exactly_the_steps_this_path_takes(
        self, fixture: EvidenceRecord, journey: JourneyRecord
    ) -> None:
        steps = {normalize_id(step.surface) for step in journey.steps}
        covered = {normalize_id(item) for item in fixture.covers}
        uncovered = {normalize_id(item) for item, _ in fixture.not_covered}
        assert covered | uncovered == steps
        assert covered & uncovered == set()
        assert covered == {normalize_id("cli:s0ma/feedback/drafts")}

    def test_every_uncovered_step_says_why_in_a_written_sentence(
        self, fixture: EvidenceRecord
    ) -> None:
        for surface, reason in fixture.not_covered:
            assert len(reason.split()) >= 20, surface

    def test_the_transcript_never_sends_anything(
        self, fixture: EvidenceRecord
    ) -> None:
        """The E-phase consent rule, as a property of the committed fixture.

        The two commands that reach an approval-class surface are asserted
        to *refuse*: the feedback family's own exit contract for a run that
        cannot be honoured as invoked, and the sentence that says nothing
        left the machine. A fixture edited to expect a success from either
        of them fails here before it is ever run.
        """
        commands = [step for step in fixture.steps if isinstance(step, CommandStep)]
        by_argv = {step.argv: step for step in commands}
        assert set(REFUSED_COMMANDS) <= set(by_argv)
        for argv in REFUSED_COMMANDS:
            step = by_argv[argv]
            assert step.exit_code == EXIT_VALIDATION, argv
            written = [item.text for item in step.stderr]
            assert "Nothing was sent." in written, argv
            assert step.stdout == (), argv

    def test_the_transcript_still_describes_the_product(
        self, fixture: EvidenceRecord, replays: tuple[Replay, Replay]
    ) -> None:
        found = compare(fixture, replays[0])
        assert found.ok, [item.rendered() for item in found.findings]

    def test_two_replays_are_byte_equal(self, replays: tuple[Replay, Replay]) -> None:
        first, second = replays
        assert first.transcript == second.transcript
        assert first.transcript.endswith("\n")
        assert "\r" not in first.transcript

    def test_no_machine_path_survives_normalization(
        self, replays: tuple[Replay, Replay]
    ) -> None:
        text = replays[0].transcript
        assert str(REPO_ROOT) not in text
        assert "/var/folders/" not in text
        assert "s0ma-evidence-" not in text


# ---------------------------------------------------------------------------
# The guide (T3)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheGuide:
    """What a reader is told, held against what the machine ran."""

    def test_every_command_shown_is_one_the_transcript_replays(
        self, fixture: EvidenceRecord, guide_text: str
    ) -> None:
        """Byte-consistency, both ways.

        Every command in the guide is one the fixture runs — save the one
        that serves until it is interrupted — and every command the fixture
        runs is one the guide shows. The second half is what stops a step
        being quietly dropped from the prose while its evidence stays green.
        """
        shown = set(_commands_in(guide_text))
        ran = {
            _rendered(step.argv)
            for step in fixture.steps
            if isinstance(step, CommandStep)
        }
        assert shown == ran | UNREPLAYABLE_IN_GUIDE

    def test_the_guide_quotes_the_products_own_review_lines(
        self, guide_text: str
    ) -> None:
        """The two lines the whole review contract is made of, verbatim.

        Both are frozen copy — the heading over the report a reader is
        about to approve, and the confirmation the contract names as
        canonical — so the guide quotes them from the product rather than
        paraphrasing them into something a reader will not recognise when
        it appears on their screen.
        """
        assert PREVIEW_HEADING in guide_text
        assert SEND_QUESTION.strip() in guide_text

    def test_the_guide_quotes_the_refusal_the_transcript_recorded(
        self, guide_text: str
    ) -> None:
        """The consent claim in the prose is the product's own sentence."""
        assert NON_INTERACTIVE_REFUSAL in guide_text

    def test_the_guide_cites_the_frozen_contract_by_name(self, guide_text: str) -> None:
        assert "docs/contracts/feedback-v1.md" in guide_text
        assert "../contracts/feedback-v1.md" in guide_text

    def test_every_intra_repo_link_resolves_to_a_file_that_is_there(
        self, guide_text: str
    ) -> None:
        """A5's rule, asked of this one file before it is ever committed."""
        here = (REPO_ROOT / GUIDE).parent
        for target in re.findall(r"\]\((?!https?:)([^)#]+)(?:#[^)]*)?\)", guide_text):
            assert (here / target).resolve().is_file(), target

    def test_the_guide_teaches_what_the_journey_says_it_teaches(
        self, live: Any, guide_text: str, journey: JourneyRecord
    ) -> None:
        concepts = {normalize_id(record.id): record for record in live.bundle.concepts}
        for taught in journey.concepts_taught:
            assert concepts[normalize_id(taught)].term in guide_text.lower(), taught


# ---------------------------------------------------------------------------
# The voice rule (T3)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheVoice:
    """The word this whole path is about is the one that must not appear."""

    def test_the_journey_record_is_in_the_products_voice(
        self, journey: JourneyRecord
    ) -> None:
        found = check_journey_voice(journey, "docs/s0ma_src/journeys/studi0-feedback.json")
        assert [item.rendered() for item in found] == []

    def test_the_fixtures_written_sentences_are_in_the_products_voice(
        self, fixture: EvidenceRecord
    ) -> None:
        assert [item.rendered() for item in check_evidence_voice(fixture)] == []

    def test_the_guide_prose_never_uses_a_word_this_product_does_not(
        self, guide_text: str
    ) -> None:
        """The battery the milestone asks for, over every byte of the guide.

        The same three patterns the authored-prose rule uses, applied to a
        rendered document rather than to a record field: the guide is the
        half of this milestone a reader actually reads, and nothing else
        would check it.
        """
        offences = [
            (label, found.group(0), guide_text[: found.start()].count("\n") + 1)
            for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE
            for found in [pattern.search(guide_text)]
            if found is not None
        ]
        assert offences == []

    def test_the_guide_says_feedback_data_where_the_contract_says_to(
        self, guide_text: str
    ) -> None:
        """Anti-vacuity: the rule above passes on a guide about nothing."""
        assert "feedback data" in guide_text
        assert "feedback report" in guide_text
