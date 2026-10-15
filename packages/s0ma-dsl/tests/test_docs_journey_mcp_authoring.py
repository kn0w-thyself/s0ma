"""Gates for E5 — the agent loop: its journey, its evidence, and its guide.

Milestone E5 of the docs-function plan (internal) §10. One journey is one
milestone, and this module is the whole of what E5 claims, in the order a
reader meets it:

* **the record** — ``journey:mcp-authoring-loop`` walks five ``mcp:tool/``
  surfaces in the canonical order, teaches its concepts in an order that
  holds, declares an approval boundary at exactly the steps that ask for
  one (which here is none of them, and the surfaces are what says so), and
  recovers from three failures this build can name;
* **the gates, armed** — the composed build reports nothing about this
  journey or its evidence, and each of the four journey gates is shown red
  under a one-field mutation of *this* record, so a green result is a fact
  about the record rather than about a gate that never fires;
* **the evidence** — the transcript replays green against the real
  authoring server and is byte-equal across two replays, its honesty
  ledger accounts for exactly the journey's five steps, and a stale
  expectation is located rather than merely failed;
* **the guide** — ``docs/guides/mcp-authoring.md`` is held to the fixture
  it teaches from: every tool call it shows is the call the fixture makes,
  and every line it quotes from an answer is a line the real server
  produced in this replay. A guide that quotes something the product never
  said is the failure this whole phase exists against.

**Cost.** The live class replays the fixture twice — once for the green
check and once for determinism — and caches both for the module, so the
guide's quotations are checked against a transcript that was already
produced rather than against a third run.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.docs_model.application import build as build_documentation
from s0ma_dsl.docs_model.evidence import (
    CHANNEL_MCP,
    DOC_EXAMPLE_FAILED,
    CallStep,
    EvidenceLibrary,
    EvidenceRecord,
    FieldExpectation,
    Replay,
    compare,
    replay,
)
from s0ma_dsl.docs_model.providers_concepts import (
    DOC_VOICE_VIOLATION,
    FORBIDDEN_IN_AUTHORED_PROSE,
)
from s0ma_dsl.docs_model.providers_journeys import JourneysProvider, check_journey_voice
from s0ma_dsl.docs_model.records import JourneyRecord
from s0ma_dsl.docs_model.validate import (
    APPROVAL_EFFECT,
    DOC_APPROVAL_UNDECLARED,
    DOC_JOURNEY_UNRESOLVED,
    DOC_TEACHING_ORDER,
    ReferenceIndex,
    check_journeys,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

JOURNEY_ID = "journey:mcp-authoring-loop"
EVIDENCE_ID = "example:transcript/mcp-authoring-loop"
EVIDENCE_SOURCE = "docs/s0ma_src/evidence/mcp-authoring-loop.json"
GUIDE_REL = "docs/guides/mcp-authoring.md"

#: The loop, in the order the journey walks it. Written down rather than
#: read off the record: the point of the milestone is that *this* sequence
#: is the canonical one, so a step quietly disappearing or moving should
#: fail here by name rather than pass a test that asks the record to agree
#: with itself.
STEP_SURFACES: tuple[str, ...] = (
    "mcp:tool/project_status",
    "mcp:tool/scaffold_module",
    "mcp:tool/check",
    "mcp:tool/build_project",
    "mcp:tool/inspect_module",
)

#: The failures the journey recovers from, each with where it sends the
#: reader. Two of the three go back to the check because the product's own
#: standing rule does ("after editing a source: run check, then build").
RECOVERIES: tuple[tuple[str, str], ...] = (
    ("MISSING_PROVIDED_FUNCTION", "mcp:prompt/fix_check_failures"),
    ("BARE_IMPORT", "mcp:tool/check"),
    ("GENERATED_FILE_DRIFT", "mcp:tool/check"),
)

#: The project root the guide writes in its examples. A replay's real root
#: is a temporary directory, and the fixture says ``{project}`` for it, so
#: the quotation check maps one onto the other rather than asking a guide
#: to print a placeholder at a reader.
GUIDE_ROOT = "/work/app"

#: The elision marker a guide may use inside a quoted answer. Anything
#: else in a quoted block is held to being a line the product produced.
ELISION = "..."

#: The registration commands the guide gives, each of which must be the
#: form ``docs/walkthrough.md`` already documents. Two milestones telling a
#: reader to register the server two different ways is how one of them ends
#: up wrong with nobody noticing.
REGISTRATIONS: tuple[str, ...] = (
    "claude mcp add s0ma -- s0ma-mcp",
    "claude mcp add s0ma --scope project -- uv run s0ma-mcp",
)

_FENCE = re.compile(r"^\s*```(\w*)\s*$")

has_server = importlib.util.find_spec("s0ma_mcp") is not None

requires_server = pytest.mark.skipif(
    not has_server, reason="the authoring server is not installed in this environment"
)


# ---------------------------------------------------------------------------
# Reading what E5 owns
# ---------------------------------------------------------------------------


def _fenced(text: str) -> list[tuple[str, list[str]]]:
    """Every fenced block of a Markdown document, as (language, lines).

    A line scanner rather than a Markdown parser, and deliberately: the
    two things this module asks of the guide are "which calls does it
    show" and "which product lines does it quote", and both are answered
    by the fences. An indented fence inside a list item is still a fence,
    which is why the pattern allows leading space.
    """
    found: list[tuple[str, list[str]]] = []
    language: str | None = None
    held: list[str] = []
    for line in text.split("\n"):
        matched = _FENCE.match(line)
        if matched is None:
            if language is not None:
                held.append(line)
            continue
        if language is None:
            language, held = matched.group(1), []
            continue
        found.append((language, held))
        language = None
    assert language is None, "the guide has an unclosed fenced block"
    return found


def _guide_text() -> str:
    """The guide as written, refusing an absent file by name."""
    path = REPO_ROOT / GUIDE_REL
    assert path.is_file(), f"{GUIDE_REL} is the guide this milestone owns and it is not here"
    return path.read_text(encoding="utf-8")


def _guide_calls(text: str) -> list[dict[str, Any]]:
    """Every tool call the guide shows, in the order it shows them."""
    return [
        json.loads("\n".join(body)) for language, body in _fenced(text) if language == "json"
    ]


def _guide_quotations(text: str) -> list[str]:
    """Every line the guide quotes from a real answer, elisions dropped."""
    return [
        stripped
        for language, body in _fenced(text)
        if language == "text"
        for stripped in (line.strip() for line in body)
        if stripped and stripped != ELISION
    ]


@pytest.fixture(scope="module")
def journey() -> JourneyRecord:
    """This repository's authored journey, read through its own provider."""
    provider = JourneysProvider(REPO_ROOT)
    for sourced in provider.provide().records:
        record = sourced.record
        if isinstance(record, JourneyRecord) and record.id == JOURNEY_ID:
            return record
    raise AssertionError(f"{JOURNEY_ID} is not in {REPO_ROOT}")


@pytest.fixture(scope="module")
def library() -> EvidenceLibrary:
    """This repository's evidence, read once."""
    return EvidenceLibrary.load(REPO_ROOT)


@pytest.fixture(scope="module")
def composed() -> Any:
    """This repository's documentation, composed once."""
    return build_documentation(REPO_ROOT)


@pytest.fixture(scope="module")
def replays(library: EvidenceLibrary) -> tuple[Replay, Replay]:
    """Two replays of the fixture, run once for the whole module."""
    record = library.by_id(EVIDENCE_ID)
    return replay(record), replay(record)


def _one_journey(composed: Any, record: JourneyRecord) -> Any:
    """The composed bundle with ``record`` standing alone in it.

    Every journey gate walks the bundle's journeys, so asking a question
    about one record means handing over a bundle that holds one record.
    Everything else — the surfaces the steps name, the concepts the
    teaching order rests on, the diagnostics a recovery is answerable
    against — stays exactly as this repository composed it.
    """
    return dataclasses.replace(composed.bundle, journeys=(record,))


def _findings(composed: Any, record: JourneyRecord) -> list[Any]:
    """Every journey finding about ``record``, against the real build."""
    bundle = _one_journey(composed, record)
    return check_journeys(bundle, ReferenceIndex.of(bundle))


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


class TestTheJourneyRecord:
    """The loop, as the file says it."""

    def test_the_steps_are_the_canonical_loop_in_order(self, journey: JourneyRecord) -> None:
        assert tuple(step.surface for step in journey.steps) == STEP_SURFACES

    def test_every_step_says_why_it_is_there_and_what_comes_back(
        self, journey: JourneyRecord
    ) -> None:
        for index, step in enumerate(journey.steps):
            assert step.purpose.strip(), f"step {index + 1} says nothing about why"
            assert step.expected_outcome.strip(), f"step {index + 1} promises nothing"

    def test_no_step_is_approval_class_and_none_claims_to_be(
        self, journey: JourneyRecord, composed: Any
    ) -> None:
        """The honest half of E5 T1, checked against the served records.

        The five tools read and write inside the project root they are
        handed; not one of them asks a person to approve anything. So
        every boundary is empty, and the reason it is empty is the
        surfaces' own ``side_effects`` rather than an author's opinion —
        the same fact ``check_journeys`` reads, asserted here so the
        emptiness cannot be mistaken for an omission.
        """
        effects = {
            record.id: record.side_effects
            for record in composed.bundle.surfaces
            if record.id in STEP_SURFACES
        }
        assert set(effects) == set(STEP_SURFACES)
        for identifier, declared in effects.items():
            assert APPROVAL_EFFECT not in declared, identifier
        assert journey.approval_boundaries() == ()

    def test_the_recoveries_are_the_three_failures_that_happen(
        self, journey: JourneyRecord
    ) -> None:
        found = tuple((path.when, path.next_surface) for path in journey.recovery_paths)
        assert found == RECOVERIES

    def test_every_recovery_is_answerable_as_a_diagnostic(
        self, journey: JourneyRecord, composed: Any
    ) -> None:
        """The answerability choice this journey had to make, pinned.

        A recovery's ``when`` is answerable two ways: the build addresses
        ``diagnostic:<when>``, or a step surface declares it among its
        ``errors``. Every ``mcp:tool/`` record declares no errors at all,
        so the second door is shut for this journey and all three
        recoveries go through the first one. If D3's records ever start
        declaring tool errors, this test is where that shows up.
        """
        index = ReferenceIndex.of(composed.bundle)
        for path in journey.recovery_paths:
            assert index.knows(f"diagnostic:{path.when}"), path.when
            assert index.knows(path.next_surface), path.next_surface
        declared = {
            code
            for record in composed.bundle.surfaces
            if record.id in STEP_SURFACES
            for code in record.errors
        }
        assert declared == set()

    def test_the_teaching_order_starts_from_the_first_module_journey(
        self, journey: JourneyRecord
    ) -> None:
        """What a reader arriving here is assumed to have, and what is new.

        The prerequisites are the module basics the first-module journey
        teaches; what this path adds is the agent-loop half — the record
        the tools answer from, the loop itself, and the boundary the build
        refuses to cross.
        """
        assert journey.concepts_required == (
            "concept:intent",
            "concept:layer",
            "concept:module",
            "concept:nerve",
            "concept:s0ma-file",
        )
        assert journey.concepts_taught == (
            "concept:registry-snapshot",
            "concept:self-model",
            "concept:self-knowledge",
            "concept:strictness-mode",
            "concept:check-and-build-loop",
            "concept:authored-vs-generated-boundary",
            "concept:metacognition",
        )
        assert not set(journey.concepts_required) & set(journey.concepts_taught)

    def test_the_journey_names_its_evidence_at_the_file_it_is_written_in(
        self, journey: JourneyRecord
    ) -> None:
        assert [(item.id, item.source) for item in journey.evidence] == [
            (EVIDENCE_ID, EVIDENCE_SOURCE)
        ]

    def test_the_record_is_in_the_product_voice(self, journey: JourneyRecord) -> None:
        assert check_journey_voice(journey, GUIDE_REL) == []


# ---------------------------------------------------------------------------
# The gates, green here and red under a mutation
# ---------------------------------------------------------------------------


class TestTheGatesAreArmed:
    """Green because the record is right, shown by making it wrong."""

    def test_the_composed_build_reports_nothing_about_this_journey(
        self, composed: Any
    ) -> None:
        """Targeted rather than whole-build: four other journeys are in flight.

        The wave gate owns the whole report. What E5 owns is this journey
        and this fixture, so the filter is by id and by source file.
        """
        mine = [
            item
            for item in composed.findings
            if JOURNEY_ID in item.message
            or EVIDENCE_ID in item.message
            or item.location == EVIDENCE_SOURCE
        ]
        assert [item.rendered() for item in mine] == []

    def test_the_four_journey_gates_pass_on_this_record(
        self, composed: Any, journey: JourneyRecord
    ) -> None:
        assert [item.rendered() for item in _findings(composed, journey)] == []

    def test_dropping_a_prerequisite_turns_the_teaching_order_red(
        self, composed: Any, journey: JourneyRecord
    ) -> None:
        """The mutation E5's acceptance asks for, on the real record.

        ``concept:self-model`` requires ``concept:intent``, which this
        journey declares as already known rather than teaching. Take the
        prerequisites away and the second thing taught rests on an idea
        the reader has not met — which is exactly the hole the gate
        exists to find, and it names the position, the concept and the
        prerequisite.
        """
        mutated = dataclasses.replace(journey, concepts_required=())
        found = _findings(composed, mutated)
        codes = {item.code for item in found}
        assert DOC_TEACHING_ORDER in codes
        assert any(
            "concept:self-model" in item.message and "concept:intent" in item.message
            for item in found
        )

    def test_reordering_the_teaching_turns_it_red(
        self, composed: Any, journey: JourneyRecord
    ) -> None:
        """The order is the content, so moving one line is a real defect."""
        taught = list(journey.concepts_taught)
        taught.remove("concept:registry-snapshot")
        taught.append("concept:registry-snapshot")
        found = _findings(composed, dataclasses.replace(journey, concepts_taught=tuple(taught)))
        assert DOC_TEACHING_ORDER in {item.code for item in found}

    def test_claiming_an_approval_nobody_asks_for_turns_it_red(
        self, composed: Any, journey: JourneyRecord
    ) -> None:
        """Both directions of the approval gate matter; this is the one E5 can show.

        None of these tools is approval-class, so the failure available
        to this journey is the invented boundary — the one that teaches a
        reader to expect a prompt that never comes, which is how a person
        learns to click past the real ones.
        """
        first = dataclasses.replace(
            journey.steps[0], approval_boundary="You will be asked to approve this."
        )
        mutated = dataclasses.replace(journey, steps=(first, *journey.steps[1:]))
        found = _findings(composed, mutated)
        assert DOC_APPROVAL_UNDECLARED in {item.code for item in found}

    def test_an_invented_failure_name_turns_the_recovery_red(
        self, composed: Any, journey: JourneyRecord
    ) -> None:
        """A recovery is written against a failure that really happens."""
        first = dataclasses.replace(journey.recovery_paths[0], when="CHECK_WENT_WRONG")
        mutated = dataclasses.replace(
            journey, recovery_paths=(first, *journey.recovery_paths[1:])
        )
        found = _findings(composed, mutated)
        assert DOC_JOURNEY_UNRESOLVED in {item.code for item in found}
        assert any("CHECK_WENT_WRONG" in item.message for item in found)


# ---------------------------------------------------------------------------
# The evidence
# ---------------------------------------------------------------------------


class TestTheEvidence:
    """The fixture, as a reading — no server needed for any of this."""

    def test_it_is_an_mcp_transcript_of_this_journey(self, library: EvidenceLibrary) -> None:
        record = library.by_id(EVIDENCE_ID)
        assert record.channel == CHANNEL_MCP
        assert record.journey == JOURNEY_ID
        assert record.source == EVIDENCE_SOURCE

    def test_it_calls_every_step_of_the_journey_in_order(
        self, library: EvidenceLibrary
    ) -> None:
        record = library.by_id(EVIDENCE_ID)
        called = tuple(
            f"mcp:tool/{step.tool}" for step in record.steps if isinstance(step, CallStep)
        )
        assert called == STEP_SURFACES

    def test_the_ledger_is_exact(self, library: EvidenceLibrary) -> None:
        """Every step covered, nothing excused, nothing claimed beyond it."""
        record = library.by_id(EVIDENCE_ID)
        assert record.covers == tuple(sorted(STEP_SURFACES))
        assert record.not_covered == ()

    def test_every_call_asks_something_of_what_comes_back(
        self, library: EvidenceLibrary
    ) -> None:
        """Anti-vacuity: a call with no expectations evidences nothing."""
        for index, step in enumerate(library.by_id(EVIDENCE_ID).steps):
            assert isinstance(step, CallStep)
            assert step.fields, f"call {index + 1} ({step.tool}) checks no field"
            assert step.text, f"call {index + 1} ({step.tool}) checks no text"

    def test_the_library_reports_nothing_about_this_fixture(
        self, library: EvidenceLibrary, composed: Any
    ) -> None:
        mine = [
            item for item in library.findings(composed.bundle) if item.location == EVIDENCE_SOURCE
        ]
        assert [item.rendered() for item in mine] == []


@requires_server
class TestTheEvidenceReplays:
    """The half that runs: the real server, twice."""

    def test_the_fixture_still_describes_the_product(
        self, library: EvidenceLibrary, replays: tuple[Replay, Replay]
    ) -> None:
        found = compare(library.by_id(EVIDENCE_ID), replays[0])
        assert found.ok, [item.rendered() for item in found.findings]

    def test_two_replays_are_byte_equal(self, replays: tuple[Replay, Replay]) -> None:
        """Determinism: two runs, two temporary directories, one text."""
        first, second = replays
        assert first.transcript == second.transcript
        assert first.transcript.endswith("\n")
        assert "\r" not in first.transcript

    def test_no_machine_fact_survives_normalization(
        self, replays: tuple[Replay, Replay]
    ) -> None:
        text = replays[0].transcript
        assert str(REPO_ROOT) not in text
        assert "/var/folders/" not in text
        assert "s0ma-evidence-" not in text

    def test_a_stale_field_expectation_is_located(
        self, library: EvidenceLibrary, replays: tuple[Replay, Replay]
    ) -> None:
        """A structured expectation that no longer holds, against a real run.

        The read-back step is the one mutated because it is the step this
        milestone added, and its canonical name is the fact the guide
        leans on hardest.
        """
        record = library.by_id(EVIDENCE_ID)
        last = record.steps[-1]
        assert isinstance(last, CallStep)
        stale = dataclasses.replace(
            last,
            fields=(FieldExpectation(path="ir.components.0.canonical_id", equals="greeting"),),
        )
        mutated: EvidenceRecord = dataclasses.replace(
            record, steps=(*record.steps[:-1], stale)
        )
        found = compare(mutated, replays[0])
        assert not found.ok
        assert found.divergence is not None
        assert found.divergence.step == len(record.steps) - 1
        assert found.divergence.stream == "fields"
        assert "greeting::greeting" in found.divergence.detail
        assert [item.code for item in found.findings] == [DOC_EXAMPLE_FAILED]


# ---------------------------------------------------------------------------
# The guide
# ---------------------------------------------------------------------------


class TestTheGuide:
    """The page, held to the fixture it teaches from."""

    def test_it_shows_the_five_calls_the_fixture_makes(
        self, library: EvidenceLibrary
    ) -> None:
        """Byte-consistency on the calls, which is what a reader copies.

        Tool names and argument names must match exactly, and so must
        every argument value except the project root — the guide names a
        readable directory where the fixture names the throwaway one it
        made, and that single substitution is the whole of the licence
        this test grants.
        """
        shown = _guide_calls(_guide_text())
        steps = [step for step in library.by_id(EVIDENCE_ID).steps if isinstance(step, CallStep)]
        assert [call["tool"] for call in shown] == [step.tool for step in steps]
        for call, step in zip(shown, steps, strict=True):
            arguments = dict(step.arguments)
            assert sorted(call["arguments"]) == sorted(arguments)
            for name, value in call["arguments"].items():
                if name == "project_root":
                    assert value == GUIDE_ROOT
                    assert arguments[name] == "{project}"
                    continue
                assert value == arguments[name], f"{step.tool}.{name}"

    def test_it_registers_the_server_the_way_the_walkthrough_does(self) -> None:
        """One product, one registration command, checked across two files."""
        text = _guide_text()
        walkthrough = (REPO_ROOT / "docs/walkthrough.md").read_text(encoding="utf-8")
        for command in REGISTRATIONS:
            assert command in text, command
            assert command in walkthrough, command

    def test_it_is_in_the_product_voice(self) -> None:
        text = _guide_text()
        offences = [
            label for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE if pattern.search(text)
        ]
        assert offences == [], f"{DOC_VOICE_VIOLATION}: {offences} in {GUIDE_REL}"

    def test_every_relative_link_resolves(self) -> None:
        """A link to a file that is not there is a reader's dead end."""
        text = _guide_text()
        here = (REPO_ROOT / GUIDE_REL).parent
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path, _, fragment = target.partition("#")
            if not path:
                assert fragment.strip(), target
                continue
            assert (here / path).resolve().exists(), target

    def test_it_names_the_evidence_that_keeps_it_true(self) -> None:
        text = _guide_text()
        assert EVIDENCE_ID in text
        assert JOURNEY_ID in text


@requires_server
class TestTheGuideQuotesTheProduct:
    """Nothing on the page is a line somebody typed from memory."""

    def test_every_quoted_line_is_a_line_the_server_produced(
        self, replays: tuple[Replay, Replay]
    ) -> None:
        """The strongest form of the E2 rule, applied to prose.

        Architecture §8.4 allows a transcript fixture as a runner
        extension and words the boundary it is allowed against: not
        "permission to paste unverified sessions into prose". So every
        line the guide quotes is looked for in the transcript this
        milestone's own replay produced, under the same one substitution
        the calls get.
        """
        transcript = replays[0].transcript
        quoted = _guide_quotations(_guide_text())
        assert len(quoted) >= 25, "the guide quotes almost nothing back at its reader"
        missing = [
            line for line in quoted if line.replace(GUIDE_ROOT, "{project}") not in transcript
        ]
        assert missing == []

    def test_the_quotation_gate_would_catch_an_invented_line(
        self, replays: tuple[Replay, Replay]
    ) -> None:
        """The check above is only worth having if it can fail. Here it does.

        The same predicate is run over the guide's real quotations plus
        one sentence the product has never said, and it picks out exactly
        the invented one — so a green result on the test above is a fact
        about the page rather than about a search that always matches.
        """
        transcript = replays[0].transcript
        invented = '"suggested_next_action": "Ship it."'
        missing = [
            line
            for line in (*_guide_quotations(_guide_text()), invented)
            if line.replace(GUIDE_ROOT, "{project}") not in transcript
        ]
        assert missing == [invented]
