"""Gates for E4 — the first-module journey, its transcript, and its guide.

Milestone E4 of the docs-function plan (internal) §10. One path is held in
place here: a reader who already has a project that builds writes a module
into it, checks it, builds it, and asks the built module what it now
contains. Four things are asserted, in the order the milestone lists them:

* **the journey composes** — the steps name surfaces this build really
  serves, the recovery path names a failure that really happens, and the
  whole composition reports nothing about any of it;
* **the teaching order holds, and holds for a reason** — the mandated
  progression (module, the declaration-kind selection, layer, visibility,
  contracts, dependencies, check, build) validates against the ``requires``
  edges somebody authored in the concept graph, and two mutations of that
  order go red — one that teaches a nerve before the fields a nerve rests
  on, and one that moves the layer behind the module header that needs it;
* **the transcript replays** — green against the installed command line,
  and byte-equal across two replays, which is what makes it evidence
  rather than a snapshot of one machine;
* **the guide says what the transcript ran** — every command and every
  byte of source on the page is the fixture's, every output line it shows
  is one the fixture pins, the concepts it teaches are the journey's
  teaching order in the journey's order, and its links land.

**The order refinement, recorded.** Architecture M3 words the progression
as *module → nerve/cell/ganglion/axon selection → layer → visibility →
contracts → dependencies → check → build*. That is the narrative arc, not
a total order: ``concept:module`` requires ``concept:layer`` and
``concept:nerve`` requires ``concept:kind``, ``concept:visibility`` and
``concept:contract``, so the literal reading teaches four ideas after the
ideas resting on them. :data:`TEACHING_ORDER` is the arc topologically
refined against the authored graph — the smallest rearrangement that keeps
every beat and lets the gate pass — and
``test_the_mandated_beats_are_all_taught`` is what stops the refinement
quietly dropping one of them.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.docs_model.application import build as build_documentation
from s0ma_dsl.docs_model.evidence import (
    CHANNEL_CLI,
    EVIDENCE_DIR,
    CommandStep,
    EvidenceLibrary,
    EvidenceRecord,
    Replay,
    WriteStep,
    check_evidence_voice,
    compare,
    replay,
)
from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.providers_concepts import FORBIDDEN_IN_AUTHORED_PROSE
from s0ma_dsl.docs_model.providers_journeys import JOURNEYS_DIR, check_journey_voice
from s0ma_dsl.docs_model.validate import (
    DOC_TEACHING_ORDER,
    ReferenceIndex,
    check_journeys,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The path, its evidence, and the page that walks a person through it.
JOURNEY_ID = "journey:first-module"
EVIDENCE_ID = "example:transcript/first-module"
JOURNEY_FILE = f"{JOURNEYS_DIR}/first-module.json"
EVIDENCE_FILE = f"{EVIDENCE_DIR}/first-module.json"
GUIDE_FILE = "docs/guides/first-module.md"

#: The surfaces the journey takes a step to, in order. Three commands and
#: no fourth: the authoring itself is a file the reader writes, which is a
#: step of the transcript rather than a capability anybody calls.
STEP_SURFACES: tuple[str, ...] = (
    "cli:s0ma/check",
    "cli:s0ma/build",
    "cli:s0ma/inspect",
)

#: What the reader arrives with, sorted. Every one of them is an idea the
#: first-project path either taught or already assumed, which is what makes
#: this journey the second one somebody walks rather than a restart.
REQUIRED: tuple[str, ...] = (
    "concept:check-and-build-loop",
    "concept:intent",
    "concept:registry-snapshot",
    "concept:self-model",
)

#: The teaching order, refined from architecture M3's arc against the
#: authored ``requires`` graph (see the module docstring). Pinned here
#: rather than read from the file, because the file is the thing under
#: test: a reordering that still validates is still a change to what a
#: reader meets first, and it should have to be made in two places.
TEACHING_ORDER: tuple[str, ...] = (
    "concept:layer",
    "concept:module",
    "concept:s0ma-file",
    "concept:kind",
    "concept:visibility",
    "concept:contract",
    "concept:nerve",
    "concept:cell",
    "concept:ganglion",
    "concept:axon",
    "concept:uses",
    "concept:canonical-ir",
)

#: The beats architecture M3 names, each mapped to the concept that carries
#: it. The refinement is allowed to move these; it is not allowed to lose
#: one, and this is what says so.
MANDATED_BEATS: tuple[tuple[str, str], ...] = (
    ("module", "concept:module"),
    ("nerve selection", "concept:nerve"),
    ("cell selection", "concept:cell"),
    ("ganglion selection", "concept:ganglion"),
    ("axon selection", "concept:axon"),
    ("layer", "concept:layer"),
    ("visibility", "concept:visibility"),
    ("contracts", "concept:contract"),
    ("dependencies", "concept:uses"),
    ("build", "concept:canonical-ir"),
)


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


# ---------------------------------------------------------------------------
# Reading what this milestone wrote
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live() -> Any:
    """The whole documentation build, composed once for this module."""
    return build_documentation(REPO_ROOT)


@pytest.fixture(scope="module")
def journey(live: Any) -> Any:
    """The composed journey this milestone authored."""
    for record in live.bundle.journeys:
        if normalize_id(record.id) == normalize_id(JOURNEY_ID):
            return record
    raise AssertionError(f"{JOURNEY_ID} is not in the composed bundle")


@pytest.fixture(scope="module")
def fixture() -> EvidenceRecord:
    """The transcript fixture this milestone authored."""
    return EvidenceLibrary.load(REPO_ROOT).by_id(EVIDENCE_ID)


@pytest.fixture(scope="module")
def replays(fixture: EvidenceRecord) -> tuple[Replay, Replay]:
    """Two replays of the fixture, run once for the whole module.

    Two because determinism is the property under test and one replay
    cannot show it; once because each of them scaffolds a project and runs
    a toolchain three times.
    """
    return replay(fixture), replay(fixture)


@pytest.fixture(scope="module")
def guide() -> str:
    """The page, as bytes on disk decoded as UTF-8."""
    return (REPO_ROOT / GUIDE_FILE).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Reading the guide the way a reader does
# ---------------------------------------------------------------------------


def _fenced(text: str) -> tuple[tuple[str, str], ...]:
    """Every fenced block of a markdown document, as (info string, body).

    Written here rather than imported because the guide is prose and the
    repository has no markdown reader: what is needed is small, and a
    parser small enough to read is one nobody has to trust.
    """
    blocks: list[tuple[str, str]] = []
    info: str | None = None
    body: list[str] = []
    for line in text.split("\n"):
        if line.startswith("```"):
            if info is None:
                info, body = line[3:].strip(), []
            else:
                blocks.append((info, "\n".join(body)))
                info = None
            continue
        if info is not None:
            body.append(line)
    assert info is None, "the guide has an unclosed fenced block"
    return tuple(blocks)


def _console(text: str) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """Every console block of the guide, as (argv, shown output lines).

    One command per block, which is a rule about the page rather than
    about markdown: a block holding two commands cannot be lined up
    against the fixture's steps, and a reader cannot tell which output
    belongs to which.
    """
    found: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for info, body in _fenced(text):
        if info != "console":
            continue
        lines = body.split("\n")
        typed = [line for line in lines if line.startswith("$ ")]
        assert len(typed) == 1, f"one command per console block, got {typed}"
        shown = tuple(
            line for line in lines if line.strip() and not line.startswith("$ ")
        )
        found.append((tuple(typed[0][2:].split()), shown))
    return tuple(found)


def _slug(heading: str) -> str:
    """A heading's anchor, the way the docs link checker spells one."""
    text = heading.lstrip("#").strip().lower()
    kept = "".join(held for held in text if held.isalnum() or held in " -_")
    return kept.replace(" ", "-")


# ---------------------------------------------------------------------------
# The journey, composed
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheAuthoredJourney:
    """What the file says, read back out of the whole composition."""

    def test_it_is_composed_with_the_steps_it_was_authored_with(
        self, journey: Any
    ) -> None:
        assert tuple(step.surface for step in journey.steps) == STEP_SURFACES

    def test_every_step_names_a_surface_this_build_really_serves(
        self, live: Any, journey: Any
    ) -> None:
        served = {normalize_id(record.id) for record in live.bundle.surfaces}
        for step in journey.steps:
            assert normalize_id(step.surface) in served, step.surface
        for path in journey.recovery_paths:
            assert normalize_id(path.next_surface) in served, path.next_surface

    def test_the_one_recovery_path_is_the_failure_a_learner_meets(
        self, journey: Any
    ) -> None:
        assert len(journey.recovery_paths) == 1
        path = journey.recovery_paths[0]
        assert path.when == "PARSE_ERROR"
        assert path.next_surface == "cli:s0ma/check"
        assert "line" in path.action

    def test_no_step_crosses_an_approval_boundary(
        self, live: Any, journey: Any
    ) -> None:
        """Correct rather than silent: none of these three asks for anything.

        The gate reads the surface's own declared effects, so this pins the
        answer on both sides — no step surface declares an approval, and no
        step claims one.
        """
        asking = {
            record.id
            for record in live.bundle.surfaces
            if "approval" in record.side_effects
        }
        assert asking, "no surface declares an approval, so the check has no subject"
        assert not (asking & {step.surface for step in journey.steps})
        assert all(step.approval_boundary == "" for step in journey.steps)

    def test_it_names_the_transcript_at_the_file_the_transcript_is_in(
        self, journey: Any
    ) -> None:
        assert [(item.id, item.source) for item in journey.evidence] == [
            (EVIDENCE_ID, EVIDENCE_FILE)
        ]

    def test_the_composition_reports_nothing_about_this_path(self, live: Any) -> None:
        mine = [
            item.rendered()
            for item in live.findings
            if "first-module" in item.rendered()
        ]
        assert mine == []


# ---------------------------------------------------------------------------
# The teaching order (T1, and the acceptance clause)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheTeachingOrder:
    """The mandated progression, validated against the authored graph."""

    def test_the_order_is_the_one_this_milestone_pinned(self, journey: Any) -> None:
        assert tuple(journey.concepts_taught) == TEACHING_ORDER
        assert tuple(journey.concepts_required) == REQUIRED

    def test_the_mandated_beats_are_all_taught(self, journey: Any) -> None:
        """The refinement may reorder architecture M3's arc; not lose a beat."""
        taught = set(journey.concepts_taught)
        missing = [beat for beat, identifier in MANDATED_BEATS if identifier not in taught]
        assert missing == []

    def test_what_the_reader_arrives_with_came_from_the_first_path(
        self, live: Any, journey: Any
    ) -> None:
        """Every prerequisite is one ``journey:first-project`` left behind."""
        first = next(
            record
            for record in live.bundle.journeys
            if normalize_id(record.id) == normalize_id("journey:first-project")
        )
        left = {normalize_id(item) for item in first.concepts_taught} | {
            normalize_id(item) for item in first.concepts_required
        }
        for identifier in journey.concepts_required:
            assert normalize_id(identifier) in left, identifier

    def test_the_gate_finds_nothing(self, live: Any, journey: Any) -> None:
        bundle = replace(live.bundle, journeys=(journey,))
        assert check_journeys(bundle, ReferenceIndex.of(bundle)) == []

    def test_the_gate_has_real_prerequisites_to_walk(
        self, live: Any, journey: Any
    ) -> None:
        """Anti-vacuity: a teaching gate with nothing to compare passes.

        Counted rather than asserted as a boolean. Twelve taught ideas
        resting on each other several times over is the reason the order
        had to be refined at all, and the number is what says the graph is
        carrying the rule rather than the pin above.
        """
        prerequisites = {
            normalize_id(record.id): tuple(
                target
                for relation, target in record.related_concepts
                if relation == "requires"
            )
            for record in live.bundle.concepts
        }
        walked = sum(
            len(prerequisites.get(normalize_id(taught), ()))
            for taught in journey.concepts_taught
        )
        assert walked >= 15, "the teaching gate is passing by having nothing to check"

    def test_teaching_a_nerve_before_its_fields_goes_red(
        self, live: Any, journey: Any
    ) -> None:
        """The acceptance clause: a shuffled order is refused, by name."""
        shuffled = ("concept:nerve", *[
            item for item in journey.concepts_taught if item != "concept:nerve"
        ])
        bundle = replace(
            live.bundle, journeys=(replace(journey, concepts_taught=shuffled),)
        )
        findings = check_journeys(bundle, ReferenceIndex.of(bundle))
        assert [item.code for item in findings] == [DOC_TEACHING_ORDER] * 4
        named = " ".join(item.message for item in findings)
        for prerequisite in (
            "concept:contract",
            "concept:kind",
            "concept:layer",
            "concept:visibility",
        ):
            assert prerequisite in named, prerequisite

    def test_moving_the_layer_behind_the_module_goes_red(
        self, live: Any, journey: Any
    ) -> None:
        """The edge that forced the refinement, proved to be a real edge.

        Architecture M3's arc opens with the module and reaches the layer
        four beats later. This is what that would cost: the header cannot
        be taught before the band it declares.
        """
        held = list(journey.concepts_taught)
        held.remove("concept:layer")
        held.insert(held.index("concept:module") + 1, "concept:layer")
        bundle = replace(
            live.bundle, journeys=(replace(journey, concepts_taught=tuple(held)),)
        )
        findings = check_journeys(bundle, ReferenceIndex.of(bundle))
        assert [item.code for item in findings] == [DOC_TEACHING_ORDER]
        assert "concept:module requires concept:layer" in findings[0].message


# ---------------------------------------------------------------------------
# The transcript (T2)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheTranscript:
    """Replayed for real, twice, and accounted for against the journey."""

    def test_it_is_the_shape_it_declares(self, fixture: EvidenceRecord) -> None:
        assert fixture.channel == CHANNEL_CLI
        assert fixture.journey == JOURNEY_ID
        assert fixture.source == EVIDENCE_FILE
        assert fixture.scaffold.kind == "new-project"
        assert fixture.scaffold.workdir == "demo"

    def test_it_writes_the_module_and_then_runs_the_three_commands(
        self, fixture: EvidenceRecord
    ) -> None:
        """The shape E2 built ``WriteStep`` for: author, then ask."""
        kinds = [type(step).__name__ for step in fixture.steps]
        assert kinds == ["WriteStep", "CommandStep", "CommandStep", "CommandStep"]
        written = fixture.steps[0]
        assert isinstance(written, WriteStep)
        assert written.path == "src/greeting/greeting_domain.s0ma"

    def test_the_ledger_accounts_for_every_step_of_the_journey(
        self, fixture: EvidenceRecord, journey: Any
    ) -> None:
        assert fixture.covers == tuple(sorted(STEP_SURFACES))
        assert fixture.not_covered == ()
        assert set(fixture.covers) == {step.surface for step in journey.steps}

    def test_every_command_expects_something_of_both_streams(
        self, fixture: EvidenceRecord
    ) -> None:
        """Anti-vacuity: a step that pins nothing passes on any output."""
        for step in fixture.steps:
            if not isinstance(step, CommandStep):
                continue
            assert step.stdout, step.argv
            assert step.stderr, step.argv

    def test_the_fixture_still_describes_the_product(
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

    def test_a_replay_writes_nothing_into_the_checkout(
        self, replays: tuple[Replay, Replay]
    ) -> None:
        """The fixture's project is the temporary one, start to finish."""
        assert not (REPO_ROOT / "demo").exists()
        assert replays[0].observed[0].label.startswith("# scaffold:")


# ---------------------------------------------------------------------------
# The guide (T3)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheGuide:
    """Every fact on the page is one the fixture or the journey holds."""

    def test_the_source_it_shows_is_the_source_the_fixture_writes(
        self, guide: str, fixture: EvidenceRecord
    ) -> None:
        written = fixture.steps[0]
        assert isinstance(written, WriteStep)
        shown = [body for info, body in _fenced(guide) if info == "s0ma"]
        assert len(shown) == 1, "the page shows exactly one module, once"
        assert shown[0] + "\n" == written.text

    def test_the_commands_it_shows_are_the_commands_the_fixture_runs(
        self, guide: str, fixture: EvidenceRecord
    ) -> None:
        ran = [fixture.scaffold.argv]
        ran.extend(
            step.argv for step in fixture.steps if isinstance(step, CommandStep)
        )
        assert [argv for argv, _ in _console(guide)] == ran

    def test_every_output_line_it_shows_is_one_the_fixture_pins(
        self, guide: str, fixture: EvidenceRecord
    ) -> None:
        """No unverified session pasted into prose (architecture §8.4).

        The scaffold pins nothing, so the page shows no output for it; each
        of the three commands after it may only show a line the fixture
        compares against a real run.
        """
        commands = [step for step in fixture.steps if isinstance(step, CommandStep)]
        blocks = _console(guide)
        assert blocks[0][1] == (), "the scaffold pins no output, so none is shown"
        for step, (_, shown) in zip(commands, blocks[1:], strict=True):
            pinned = {
                item.text.strip()
                for item in step.stdout
                if item.match in ("line", "contains")
            }
            for line in shown:
                assert line.strip() in pinned, line

    def test_the_concepts_it_teaches_are_the_journeys_teaching_order(
        self, guide: str, journey: Any
    ) -> None:
        """The T3 clause, as a gate: the page and the record teach one list.

        Order included. A page that introduced the ideas in a different
        order from the record would pass every other check here and still
        be teaching something the gate never validated.
        """
        seen: list[str] = []
        for found in re.findall(r"concept:[a-z0-9-]+", guide):
            if found not in seen:
                seen.append(found)
        assert tuple(seen) == tuple(journey.concepts_taught)

    def test_every_link_lands(self, guide: str) -> None:
        here = (REPO_ROOT / GUIDE_FILE).parent
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", guide)
        assert len(links) >= 4, "a page that links nowhere proves nothing here"
        for link in links:
            assert not link.startswith(("http://", "https://")), link
            target, _, anchor = link.partition("#")
            path = (here / target).resolve()
            assert path.is_file(), link
            if not anchor:
                continue
            headings = {
                _slug(line)
                for line in path.read_text(encoding="utf-8").split("\n")
                if line.startswith("#")
            }
            assert anchor in headings, link

    def test_it_is_written_in_the_products_voice(self, guide: str) -> None:
        for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
            found = pattern.search(guide)
            assert found is None, f"{found and found.group(0)!r} is {label}"


# ---------------------------------------------------------------------------
# Voice and file hygiene
# ---------------------------------------------------------------------------


@requires_checkout
class TestVoiceAndHygiene:
    """The rules every authored source in this tree is subject to."""

    def test_the_journey_is_written_in_the_products_voice(
        self, journey: Any
    ) -> None:
        assert check_journey_voice(journey, JOURNEY_FILE) == []

    def test_the_transcript_is_written_in_the_products_voice(
        self, fixture: EvidenceRecord
    ) -> None:
        assert check_evidence_voice(fixture) == []

    @pytest.mark.parametrize("relative", [JOURNEY_FILE, EVIDENCE_FILE, GUIDE_FILE])
    def test_utf8_with_line_feeds_and_one_trailing_newline(self, relative: str) -> None:
        raw = (REPO_ROOT / relative).read_bytes()
        assert b"\r" not in raw, relative
        assert raw.endswith(b"\n") and not raw.endswith(b"\n\n"), relative
        raw.decode("utf-8")

    @pytest.mark.parametrize("relative", [JOURNEY_FILE, EVIDENCE_FILE])
    def test_the_json_is_canonical(self, relative: str) -> None:
        """Sorted keys, two-space indent, one trailing newline.

        The same form every authored JSON source in this tree is written
        in, so a diff shows what changed rather than how it was serialized.
        """
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        document = json.loads(text)
        canonical = (
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        assert text == canonical
