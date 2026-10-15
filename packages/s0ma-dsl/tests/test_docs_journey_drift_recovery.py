"""Gates for E6 — the journey that teaches recovery from a refusal.

Milestone E6 of the docs-function plan (internal) §10. This is the journey
whose subject is the product saying *no*: a generated file edited by hand,
and a promise left unwritten before a release. Four things are held here,
in the order a reader meets them:

* **the record composes** — ``journey:drift-recovery`` loads, resolves,
  and draws no finding of its own out of the whole documentation build.
  Filtered to this journey rather than asserted over the build's total,
  because four sibling journeys land in the same wave and one executor's
  red must not read as another's;
* **every recovery is answerable** — each ``when`` is a failure this
  build can name, checked by the gate rather than by eye, with a mutation
  that makes one ambiguous proving the gate still has teeth;
* **the evidence runs** — the transcript is replayed for real against the
  installed command line, green, and **byte-equal across two replays**,
  which is the property that makes it evidence of the product rather than
  a snapshot of one machine;
* **the guide and the fixture agree** — every command the guide prints is
  a command the fixture runs, in order, and every line of output the guide
  quotes is a line the fixture pins. A guide is allowed to say less than
  the transcript; it is never allowed to say something the transcript does
  not check.

**Cost.** The live class replays the fixture twice — once for the green
check and once for the determinism comparison — and caches both, so the
module pays two replays rather than one per test.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.docs_model.application import build as build_documentation
from s0ma_dsl.docs_model.evidence import (
    CHANNEL_CLI,
    CommandStep,
    EvidenceLibrary,
    Expectation,
    WriteStep,
    check_evidence_voice,
    compare,
    replay,
)
from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.providers_concepts import FORBIDDEN_IN_AUTHORED_PROSE
from s0ma_dsl.docs_model.providers_journeys import JourneysProvider
from s0ma_dsl.docs_model.records import DocsBundle, RecoveryPath
from s0ma_dsl.docs_model.validate import (
    DOC_JOURNEY_UNRESOLVED,
    ReferenceIndex,
    check_journeys,
)

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.evidence import EvidenceRecord, Replay
    from s0ma_dsl.docs_model.records import JourneyRecord

REPO_ROOT = Path(__file__).resolve().parents[3]

JOURNEY_ID = "journey:drift-recovery"
EVIDENCE_ID = "example:transcript/drift-recovery"
GUIDE = "docs/guides/drift-recovery.md"

#: The two failures this path exists to recover from, plus the one it
#: sends a lost reader to the health report for. Written down rather than
#: read back off the record: the point of the milestone is that *these*
#: refusals are taught, and a recovery quietly disappearing should fail
#: here by name rather than pass a weaker count.
EXPECTED_RECOVERIES: tuple[tuple[str, str], ...] = (
    ("GENERATED_FILE_DRIFT", "cli:s0ma/build"),
    ("HOST_RUNTIME_UNDECLARED", "cli:s0ma/doctor"),
    ("SEMANTIC_PENDING_DEBT", "cli:s0ma/check"),
)

#: The surfaces the path walks, in the order it walks them. Two of the
#: three are visited twice, which is the shape of the lesson rather than
#: an accident: the same question asked after a change is what a refusal
#: is recovered *to*.
EXPECTED_STEPS: tuple[str, ...] = (
    "cli:s0ma/check",
    "cli:s0ma/build",
    "cli:s0ma/build",
    "cli:s0ma/check",
    "cli:s0ma/check",
    "cli:s0ma/doctor",
)

#: The fences this module reads out of the guide. ``bash`` is what a
#: reader types and ``text`` is what the product answers; everything else
#: on the page — the two edits, in their own languages — is prose about a
#: file rather than a transcript, and is checked separately.
_FENCE = re.compile(r"^```(\w*)$(.*?)^```$", re.MULTILINE | re.DOTALL)


def _fences(markdown: str, language: str) -> list[list[str]]:
    """Every fenced block of one language, as its non-blank lines."""
    return [
        [line for line in body.split("\n") if line.strip()]
        for found, body in _FENCE.findall(markdown)
        if found == language
    ]


# ---------------------------------------------------------------------------
# Shared readings
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def guide() -> str:
    """The guide as written, refusing to pass if it is not there."""
    path = REPO_ROOT / GUIDE
    assert path.is_file(), f"{GUIDE} is the journey's guide and is not in this tree"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def journey() -> JourneyRecord:
    """The authored record, read through the provider that owns it."""
    provider = JourneysProvider(root=REPO_ROOT)
    for item in provider.provide().records:
        if item.record.id == JOURNEY_ID:
            return item.record  # type: ignore[return-value]
    pytest.fail(f"{JOURNEY_ID} is not in {REPO_ROOT}")


@pytest.fixture(scope="module")
def fixture() -> EvidenceRecord:
    """The transcript fixture this journey names as its evidence."""
    return EvidenceLibrary.load(REPO_ROOT).by_id(EVIDENCE_ID)


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


class TestRecord:
    """What the authored journey says, before anything runs it."""

    def test_walks_the_two_refusals_and_the_health_report(
        self, journey: JourneyRecord
    ) -> None:
        assert tuple(step.surface for step in journey.steps) == EXPECTED_STEPS

    def test_declares_no_approval_boundary(self, journey: JourneyRecord) -> None:
        """Reading, writing a build directory, reporting — nothing asks.

        The gate refuses this field in both directions, so an empty
        boundary here is an assertion rather than an omission: none of
        these three surfaces declares an approval-class effect, and a
        boundary written on one would teach a reader to expect a prompt
        that never comes.
        """
        assert journey.approval_boundaries() == ()

    def test_teaches_drift_before_the_gate_that_refuses_it(
        self, journey: JourneyRecord
    ) -> None:
        """The order is the content: a gate cannot precede what it gates."""
        taught = list(journey.concepts_taught)
        assert taught.index("concept:drift") < taught.index("concept:drift-gate")
        assert "concept:strictness-mode" in taught

    def test_assumes_the_loop_it_is_a_departure_from(
        self, journey: JourneyRecord
    ) -> None:
        """This path starts where the everyday cycle already is."""
        assert "concept:check-and-build-loop" in journey.concepts_required

    def test_names_the_transcript_at_the_file_it_is_written_in(
        self, journey: JourneyRecord, fixture: EvidenceRecord
    ) -> None:
        cited = [item for item in journey.evidence if item.id == EVIDENCE_ID]
        assert len(cited) == 1
        assert cited[0].source == fixture.source

    def test_is_written_in_the_products_voice(self, journey: JourneyRecord) -> None:
        """Every sentence of the record, against the forbidden vocabulary.

        The provider reports this as a finding rather than a refusal, so
        the assertion is over what it found rather than over an exception
        it does not raise.
        """
        provider = JourneysProvider(root=REPO_ROOT)
        provider.provide()
        assert [
            finding
            for finding in provider.findings()
            if "drift-recovery" in finding.location
        ] == []


# ---------------------------------------------------------------------------
# The recovery paths
# ---------------------------------------------------------------------------


def _bundle_and_index() -> tuple[DocsBundle, ReferenceIndex, JourneyRecord]:
    """The composed build, and this journey out of it."""
    result = build_documentation(REPO_ROOT)
    journeys = tuple(
        record for record in result.bundle.journeys if record.id == JOURNEY_ID
    )
    assert journeys, f"{JOURNEY_ID} did not reach the composition"
    external = tuple(sorted(EvidenceLibrary.load(REPO_ROOT).ids()))
    index = ReferenceIndex.of(result.bundle, external)
    return result.bundle, index, journeys[0]


class TestRecoveryPaths:
    """Every failure this path recovers from is one the build can name."""

    @pytest.fixture(scope="class")
    def composed(self) -> tuple[DocsBundle, ReferenceIndex, JourneyRecord]:
        return _bundle_and_index()

    def test_the_three_recoveries_are_the_ones_authored(
        self, journey: JourneyRecord
    ) -> None:
        found = tuple(
            (path.when, path.next_surface) for path in journey.recovery_paths
        )
        assert found == EXPECTED_RECOVERIES

    @pytest.mark.parametrize("when", [name for name, _ in EXPECTED_RECOVERIES])
    def test_each_when_resolves_as_a_diagnostic(
        self,
        when: str,
        composed: tuple[DocsBundle, ReferenceIndex, JourneyRecord],
    ) -> None:
        """Answerability, asked the way the gate asks it.

        A ``when`` is answerable two ways — the build addresses
        ``diagnostic:<when>``, or one of this journey's own step surfaces
        declares it among its errors. All three of these take the first
        route, and the assertion says so rather than accepting either:
        the command line's surface records declare no errors of their
        own, so a ``when`` that stopped resolving as a diagnostic would
        have nothing left to be answered by.
        """
        _, index, _ = composed
        assert index.knows(f"diagnostic:{when}")

    def test_the_gate_is_silent_on_this_journey(
        self, composed: tuple[DocsBundle, ReferenceIndex, JourneyRecord]
    ) -> None:
        bundle, index, journey = composed
        one = replace(bundle, journeys=(journey,))
        assert check_journeys(one, index) == []

    def test_an_invented_failure_name_is_caught(
        self, composed: tuple[DocsBundle, ReferenceIndex, JourneyRecord]
    ) -> None:
        """A ``when`` nothing answers to is a finding, not a silence.

        The mutation is the one an author actually makes: a plausible
        code, spelled from memory, that no provider emits.
        """
        bundle, index, journey = composed
        broken = replace(
            journey,
            recovery_paths=(
                *journey.recovery_paths,
                RecoveryPath(
                    when="GENERATED_FILE_DRIFTED",
                    next_surface="cli:s0ma/build",
                    action="Build again and hope.",
                ),
            ),
        )
        findings = check_journeys(replace(bundle, journeys=(broken,)), index)
        assert [finding.code for finding in findings] == [DOC_JOURNEY_UNRESOLVED]
        assert "GENERATED_FILE_DRIFTED" in findings[0].message

    def test_an_ambiguous_when_is_caught(
        self, composed: tuple[DocsBundle, ReferenceIndex, JourneyRecord]
    ) -> None:
        """Two step surfaces declaring one failure leaves a reader stuck.

        B7's rule, exercised against this journey rather than a synthetic
        one: the failure is attached to two of the surfaces the path
        actually walks, and the recovery that names it can no longer say
        which step it is recovering from. Both surfaces are copied from
        the composed build, so the mutation is a change to the world the
        gate reads rather than to the gate.
        """
        bundle, index, journey = composed
        walked = {normalize_id(step.surface) for step in journey.steps}
        surfaces = tuple(
            replace(record, errors=(*record.errors, "SEMANTIC_PENDING_DEBT"))
            if normalize_id(record.id) in walked
            else record
            for record in bundle.surfaces
        )
        findings = check_journeys(
            replace(bundle, journeys=(journey,), surfaces=surfaces), index
        )
        assert [finding.code for finding in findings] == [DOC_JOURNEY_UNRESOLVED]
        assert "SEMANTIC_PENDING_DEBT" in findings[0].message
        assert "3 of its own steps declare that failure" in findings[0].message


# ---------------------------------------------------------------------------
# The composition
# ---------------------------------------------------------------------------


class TestComposes:
    """This journey's own contribution to the build, filtered to itself.

    Four sibling journeys land in the same wave and the orchestrator pays
    the cascade at the gate, so an assertion over the build's total
    findings would report somebody else's work. What is asserted is the
    honest half: nothing this milestone owns produced a finding.
    """

    @pytest.fixture(scope="class")
    def findings(self) -> tuple[str, ...]:
        result = build_documentation(REPO_ROOT)
        return tuple(
            f"{finding.code} {finding.location} {finding.message}"
            for finding in result.findings
            if "drift-recovery" in f"{finding.location} {finding.message}"
        )

    def test_nothing_this_milestone_owns_is_red(
        self, findings: tuple[str, ...]
    ) -> None:
        assert findings == ()

    def test_the_journey_reaches_the_composition(self) -> None:
        result = build_documentation(REPO_ROOT)
        assert JOURNEY_ID in {record.id for record in result.bundle.journeys}


# ---------------------------------------------------------------------------
# The evidence
# ---------------------------------------------------------------------------


class TestFixture:
    """What the transcript declares, before it is run."""

    def test_evidences_this_journey_over_the_command_line(
        self, fixture: EvidenceRecord
    ) -> None:
        assert fixture.journey == JOURNEY_ID
        assert fixture.channel == CHANNEL_CLI

    def test_the_ledger_is_exact(
        self, fixture: EvidenceRecord, journey: JourneyRecord
    ) -> None:
        """Every step is covered, and nothing is excused.

        The composition asks this too, and it is asserted here as well
        because the two ask it for different reasons: there it is a gate
        over whatever the build happens to hold, and here it is this
        milestone's claim that the transcript really does reach all three
        surfaces rather than three of four with a reason for the fourth.
        """
        assert fixture.not_covered == ()
        assert set(fixture.covers) == {step.surface for step in journey.steps}

    def test_both_faults_are_introduced_by_a_written_file(
        self, fixture: EvidenceRecord
    ) -> None:
        """The beats are edits, and the edits are in the transcript.

        Three writes: the hand edit under ``build/``, the promise
        replaced by a note, and the note replaced by the promise. A
        transcript that only ran commands could evidence a path nobody
        walks — the refusals need somebody to have broken something
        first, and this is where they do it.
        """
        written = [step for step in fixture.steps if isinstance(step, WriteStep)]
        assert [step.path for step in written] == [
            "build/core_domain.py",
            "src/core/core_domain.s0ma",
            "src/core/core_domain.s0ma",
        ]

    @pytest.mark.parametrize("when", [name for name, _ in EXPECTED_RECOVERIES])
    def test_every_failure_recovered_from_is_one_the_transcript_saw(
        self, when: str, fixture: EvidenceRecord
    ) -> None:
        """A recovery is written against a failure this run actually met.

        The gate upstream asks whether the name resolves; this asks the
        harder question, which resolution cannot: did anything here ever
        print it. A path that taught a recovery from a failure its own
        evidence never provoked would resolve perfectly and be untested
        exactly where it matters.
        """
        pinned = "\n".join(
            expectation.text
            for step in fixture.steps
            if isinstance(step, CommandStep)
            for expectation in (*step.stdout, *step.stderr)
            if expectation.match != "absent"
        )
        assert f"[{when}]" in pinned

    def test_every_refusal_is_a_refusal_and_not_a_crash(
        self, fixture: EvidenceRecord
    ) -> None:
        """The two failing commands assert an empty error stream.

        A stack trace on the way out is a different product than a
        refusal, and it would satisfy a fixture that only checked the
        exit code.
        """
        failing = [
            step
            for step in fixture.steps
            if isinstance(step, CommandStep) and step.exit_code != 0
        ]
        assert len(failing) == 2
        for step in failing:
            assert Expectation(match="absent", text="Traceback") in step.stderr

    def test_is_written_in_the_products_voice(self, fixture: EvidenceRecord) -> None:
        assert check_evidence_voice(fixture) == []


class TestReplay:
    """The transcript, run for real against the installed command line.

    Unmarked, and deliberately so: this repository registers one marker
    and skips nothing by cost, and evidence that only runs when somebody
    remembers to ask for it is the failure ``DOC_JOURNEY_UNTESTED``
    exists against.
    """

    @pytest.fixture(scope="class")
    def runs(self, fixture: EvidenceRecord) -> tuple[Replay, Replay]:
        return replay(fixture), replay(fixture)

    def test_replays_green(
        self, fixture: EvidenceRecord, runs: tuple[Replay, Replay]
    ) -> None:
        verification = compare(fixture, runs[0])
        assert verification.ok, (
            verification.divergence.rendered()
            if verification.divergence is not None
            else ""
        )

    def test_a_refusal_that_stopped_refusing_is_caught(
        self, fixture: EvidenceRecord, runs: tuple[Replay, Replay]
    ) -> None:
        """The two exit codes are load-bearing, not decoration.

        Compared against the captured run rather than a second one, so
        this costs nothing: the mutation says the build succeeded where
        the fixture says it refused, which is exactly what a regression
        that quietly dropped the drift guard would produce.
        """
        steps = list(fixture.steps)
        refusing = next(
            index
            for index, step in enumerate(steps)
            if isinstance(step, CommandStep) and step.exit_code != 0
        )
        steps[refusing] = replace(steps[refusing], exit_code=0)
        verification = compare(replace(fixture, steps=tuple(steps)), runs[0])
        assert not verification.ok
        assert verification.divergence is not None
        assert verification.divergence.step == refusing
        assert "exited 1 and the fixture says 0" in verification.divergence.detail

    def test_two_replays_are_byte_equal(self, runs: tuple[Replay, Replay]) -> None:
        """Determinism, over the whole session rather than the assertions.

        The transcript carries every stream of every step, so a byte that
        moves between two runs turns this red here rather than turning
        the fixture flaky on somebody else's machine.
        """
        assert runs[0].transcript == runs[1].transcript


# ---------------------------------------------------------------------------
# The guide
# ---------------------------------------------------------------------------


class TestGuide:
    """The page a person reads, held to the transcript that was run.

    This is the gate the whole milestone turns on. A recovery guide is
    read at the worst moment — something has just refused, and the reader
    is deciding whether to trust the page in front of them — so a command
    it prints that nobody ran, or an answer it quotes that nobody
    checked, is the most expensive kind of wrong this repository can
    ship.
    """

    def test_every_command_shown_is_a_command_the_transcript_runs(
        self, guide: str, fixture: EvidenceRecord
    ) -> None:
        """Ordered equality, scaffold included.

        Ordered rather than set-wise because the order *is* the recovery:
        a page that showed the force rebuild before the refusal would
        teach the wrong reflex while passing every membership check.
        """
        shown = [line for block in _fences(guide, "bash") for line in block]
        ran = [" ".join(fixture.scaffold.argv)]
        ran.extend(
            " ".join(step.argv)
            for step in fixture.steps
            if isinstance(step, CommandStep)
        )
        assert shown == ran

    def test_every_line_of_output_shown_is_a_line_the_transcript_pins(
        self, guide: str, fixture: EvidenceRecord
    ) -> None:
        """The page may quote less than the run; never more.

        Only whole-line expectations count as a licence to print a line.
        An ``absent`` says what never appeared and a fragment says a line
        contains something — neither is evidence that the line the guide
        prints is the line the product printed.
        """
        pinned = {
            expectation.text
            for step in fixture.steps
            if isinstance(step, CommandStep)
            for expectation in (*step.stdout, *step.stderr)
            if expectation.match == "line"
        }
        shown = [line for block in _fences(guide, "text") for line in block]
        assert shown, "the guide quotes no output at all"
        assert [line for line in shown if line not in pinned] == []

    def test_both_edits_shown_are_the_edits_the_transcript_makes(
        self, guide: str, fixture: EvidenceRecord
    ) -> None:
        """The faults themselves, not only the commands around them.

        Each fenced edit on the page is one line, and each has to appear
        verbatim in a file the transcript writes — otherwise a reader
        following the page introduces a different fault from the one the
        evidence recovers from, and every quoted answer below it is
        answering a question they did not ask.
        """
        written = "\n".join(
            step.text for step in fixture.steps if isinstance(step, WriteStep)
        )
        edits = [
            line
            for language in ("python", "s0ma")
            for block in _fences(guide, language)
            for line in block
        ]
        assert len(edits) == 3
        assert [line for line in edits if line not in written.split("\n")] == []

    def test_points_at_the_troubleshooting_page_rather_than_forking_it(
        self, guide: str
    ) -> None:
        """The humanized page is linked, and its content is not copied.

        A recovery guide and a troubleshooting page overlap by nature,
        and the failure to guard against is the second copy: two accounts
        of one refusal, one of which is wrong. The link is asserted, and
        so is the absence of the table the other page owns.
        """
        assert "(../troubleshooting.md)" in guide
        assert "| You see |" not in guide

    def test_is_written_in_the_products_voice(self, guide: str) -> None:
        """The rule that reaches every word a reader sees.

        Quoted product output is authored on this page in the sense that
        matters — somebody typed it into a markdown file — so it is
        governed too, and it passes because the product does not use
        those words either.
        """
        for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
            found = pattern.search(guide)
            assert found is None, f"{GUIDE} uses {found.group(0)!r}, which is {label}"

    def test_carries_the_finding_the_page_exists_to_explain(self, guide: str) -> None:
        """The audit's sentence, quoted rather than paraphrased.

        The claim that a gated document stays current and an ungated one
        drifts is the reason a reader should accept a refusal, and it is
        somebody's finding rather than this page's opinion. Quoting it is
        what makes it checkable.
        """
        assert (
            "Every documentation surface under a mechanical gate is current"
            in guide
        )
