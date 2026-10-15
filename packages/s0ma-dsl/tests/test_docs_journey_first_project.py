"""Gates for E3 — the install-and-first-project journey, end to end.

Milestone E3 of the docs-function plan (internal) §10. One authored path,
one transcript that walks it for real, and one guide that teaches it, held
together by four questions this file asks in the order a reader meets
them:

* **does the path compose** — every step surface, every taught concept,
  every recovered failure resolving against the *live* ten-provider build
  rather than against a fixture written to agree with them, and this
  journey contributing no finding of its own (T4);
* **does the teaching order hold** — green on the real concept graph, and
  red the moment one idea is moved in front of the idea it rests on, so
  the gate is shown to be looking rather than assumed to be (T4);
* **does the evidence still describe the product** — replayed against the
  installed command line, green, and byte-equal across two replays (T2);
* **does the guide teach only what the evidence proves** — every command
  it shows a reader, every line of output it quotes, and the whole module
  source it asks them to write, checked against the fixture rather than
  against somebody's memory of a session (T3).

**The write-class boundary, recorded rather than assumed.** Every step of
this journey carries an empty ``approval_boundary``, including the two
that write files. E1's gate reads
:data:`~s0ma_dsl.docs_model.validate.APPROVAL_EFFECT` — the ``approval``
side effect — and refuses a declared boundary in *both* directions, so a
boundary on ``cli:s0ma/new`` or ``cli:s0ma/build``, which declare
``read`` and ``write`` and ask the reader for nothing, would be the
"prompt that never comes" half of ``DOC_APPROVAL_UNDECLARED``. Writing is
taught in the guide's prose, where it belongs; an approval boundary is
for the moment something irreversible is asked for, and this path asks
for nothing. ``TestTheApprovalBoundaries`` pins both halves of that so a
later surface gaining an ``approval`` effect turns this file red rather
than passing silently.

**Cost.** The evidence class replays the fixture twice — once for the
green comparison and once for the determinism check — and caches both, so
the module pays two replays rather than one per test.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model.application import build as build_documentation
from s0ma_dsl.docs_model.evidence import (
    CHANNEL_CLI,
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
from s0ma_dsl.docs_model.providers_journeys import check_journey_voice
from s0ma_dsl.docs_model.validate import (
    APPROVAL_EFFECT,
    DOC_TEACHING_ORDER,
    ReferenceIndex,
    check_journeys,
)

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.records import JourneyRecord

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The three artefacts of this milestone, addressed the way the model
#: addresses them.
JOURNEY = "journey:first-project"
EVIDENCE = "example:transcript/first-project"
GUIDE = "docs/getting-started/first-project.md"

#: What the path is, written down rather than counted off the file. The
#: point of the milestone is *this* arc — make it, ask about it, add to
#: it, ask again, build it, then ask it what it now knows — so a step
#: quietly appearing or leaving should fail here by name.
EXPECTED_STEPS: tuple[str, ...] = (
    "cli:s0ma/new",
    "cli:s0ma/check",
    "cli:s0ma/new",
    "cli:s0ma/check",
    "cli:s0ma/build",
    "cli:s0ma/inspect",
    "cli:s0ma/graph",
)

#: The teaching order, in the order a reader meets it. Ordered rather than
#: sorted for the reason the field is ordered: the order is the content.
EXPECTED_TAUGHT: tuple[str, ...] = (
    "concept:intent",
    "concept:layer",
    "concept:module",
    "concept:s0ma-file",
    "concept:strictness-mode",
    "concept:check-and-build-loop",
    "concept:registry-snapshot",
    "concept:self-model",
    "concept:authored-vs-generated-boundary",
)

#: The two failures this path recovers from, with the capability the
#: reader goes to. One is proven by the transcript itself; the other is
#: the environment question the health report exists to answer.
EXPECTED_RECOVERY: tuple[tuple[str, str], ...] = (
    ("MISSING_PACKAGE", "cli:s0ma/doctor"),
    ("PARSE_ERROR", "cli:s0ma/check"),
)

#: Lines a guide may show inside a ``bash`` block without the fixture
#: proving them, because they are not commands the product serves: moving
#: into the scaffolded directory is what the fixture's ``workdir`` does
#: structurally, and it has no transcript line of its own. Deliberately
#: exact strings rather than a pattern — an allowance that matched
#: ``cd anything`` would let a guide walk a reader somewhere the replay
#: never went.
NAVIGATION: frozenset[str] = frozenset({"cd demo"})

#: The stand-in the guide writes where a real run prints the project's
#: absolute location. The fixture normalizes the same place to
#: ``{project}``, so the two are compared through this substitution.
GUIDE_PROJECT = "/path/to/demo"
FIXTURE_PROJECT = "{project}"

#: Output the guide quotes inline rather than in a fenced block, each of
#: which must be something the transcript actually asserted. Written down
#: because an inline span is prose and cannot be told from a term of art
#: by looking at it; the companion test checks each one is really in the
#: page, so the list cannot rot into a vacuous pass.
#:
#: Nothing printed by ``s0ma new project`` appears here, and the guide
#: quotes none of it, for a reason worth writing down: that command is the
#: fixture's *scaffold*, and a scaffold declares no expectations by
#: construction (``evidence._scaffold`` builds its step with empty
#: streams). Output nothing can assert is output this page does not quote,
#: so the promise its opening makes stays true.
QUOTED_INLINE: tuple[str, ...] = (
    "4 file(s) checked. No errors.",
    "Results: 1 error(s), 0 warning(s) [mode: dev]",
    "Results: 0 error(s), 1 warning(s) [mode: dev]",
)

has_server = importlib.util.find_spec("s0ma_mcp") is not None

requires_server = pytest.mark.skipif(
    not has_server, reason="the authoring server is not installed in this environment"
)


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


# ---------------------------------------------------------------------------
# What the whole build says
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live() -> Any:
    """The whole documentation build, composed once for this module."""
    return build_documentation(REPO_ROOT)


@pytest.fixture(scope="module")
def journey(live: Any) -> JourneyRecord:
    """This milestone's path, as the composition holds it."""
    for record in live.bundle.journeys:
        if normalize_id(record.id) == normalize_id(JOURNEY):
            return record
    raise AssertionError(f"{JOURNEY} is not in the composed bundle")


@pytest.fixture(scope="module")
def fixture_record(live: Any) -> EvidenceRecord:
    """This milestone's transcript, read from the tree it is committed in."""
    return EvidenceLibrary.load(REPO_ROOT).by_id(EVIDENCE)


@pytest.fixture(scope="module")
def guide_text() -> str:
    """The authored guide, read once."""
    return (REPO_ROOT / GUIDE).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Guide reading
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"^```([a-z0-9]*)\n(.*?)^```$", re.MULTILINE | re.DOTALL)
_SPAN = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\]\(([^)]+)\)")


def _blocks(text: str, language: str) -> tuple[str, ...]:
    """Every fenced block of one language, in the order the page shows them."""
    return tuple(body for tongue, body in _FENCE.findall(text) if tongue == language)


def _prose(text: str) -> str:
    """The page with its fenced blocks removed — the sentences a person wrote."""
    return _FENCE.sub("", text)


def _spans(text: str) -> tuple[str, ...]:
    """Every inline code span outside a fenced block."""
    return tuple(_SPAN.findall(_prose(text)))


def _commands(record: EvidenceRecord) -> frozenset[str]:
    """Every command line the fixture really runs, scaffold included.

    Rendered the way a reader types it rather than as an argv list,
    because that is the form a guide shows and the form this comparison
    has to be able to make.
    """
    lines = {" ".join(record.scaffold.argv)}
    lines.update(
        " ".join(step.argv) for step in record.steps if isinstance(step, CommandStep)
    )
    return frozenset(lines)


def _expectations(record: EvidenceRecord) -> frozenset[str]:
    """Every literal the fixture asserts about a stream, on any step."""
    found: set[str] = set()
    for step in record.steps:
        if not isinstance(step, CommandStep):
            continue
        for expectation in (*step.stdout, *step.stderr):
            found.add(expectation.text)
    return frozenset(found)


def _writes(record: EvidenceRecord) -> tuple[WriteStep, ...]:
    """Every file the transcript writes between two commands."""
    return tuple(step for step in record.steps if isinstance(step, WriteStep))


# ---------------------------------------------------------------------------
# The path itself
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheJourneyComposes:
    """The authored path, checked against the build that composed it."""

    def test_this_journey_contributes_no_finding(self, live: Any) -> None:
        """Filtered to this id on purpose.

        Four other journeys are being authored in parallel and their
        findings are theirs; what this milestone owns is that *this* path
        adds none. A finding naming another journey is not evidence about
        this one either way.
        """
        mine = [
            item
            for item in live.findings
            if JOURNEY in item.message or GUIDE in (item.location or "")
        ]
        assert [item.rendered() for item in mine] == []

    def test_the_steps_are_the_arc_this_milestone_authored(
        self, journey: JourneyRecord
    ) -> None:
        assert tuple(step.surface for step in journey.steps) == EXPECTED_STEPS

    def test_every_step_says_why_the_reader_is_there_and_what_they_see(
        self, journey: JourneyRecord
    ) -> None:
        """Anti-vacuity: a step with an empty purpose leads nobody anywhere."""
        for index, step in enumerate(journey.steps):
            assert len(step.purpose) > 40, index
            assert len(step.expected_outcome) > 40, index

    def test_every_step_surface_is_one_this_build_really_serves(
        self, journey: JourneyRecord, live: Any
    ) -> None:
        served = {normalize_id(record.id) for record in live.bundle.surfaces}
        for step in journey.steps:
            assert normalize_id(step.surface) in served, step.surface

    def test_the_two_recoveries_are_the_ones_the_milestone_asked_for(
        self, journey: JourneyRecord
    ) -> None:
        found = tuple((path.when, path.next_surface) for path in journey.recovery_paths)
        assert found == EXPECTED_RECOVERY

    def test_every_recovery_goes_somewhere_this_build_serves(
        self, journey: JourneyRecord, live: Any
    ) -> None:
        served = {normalize_id(record.id) for record in live.bundle.surfaces}
        for path in journey.recovery_paths:
            assert normalize_id(path.next_surface) in served, path.next_surface
            assert len(path.action) > 60, path.when

    def test_both_recovered_failures_are_failures_this_build_can_name(
        self, journey: JourneyRecord, live: Any
    ) -> None:
        """The other half of the recovery gate, asserted positively.

        ``check_journeys`` reports a recovery written against an invented
        failure; this says the two named here really are addressed, so a
        green run is a green run rather than a gate looking elsewhere.
        """
        addressed = {normalize_id(record.id) for record in live.bundle.surfaces}
        for path in journey.recovery_paths:
            assert normalize_id(f"diagnostic:{path.when}") in addressed, path.when

    def test_the_path_assumes_one_thing_of_its_reader_and_teaches_the_rest(
        self, journey: JourneyRecord
    ) -> None:
        """The first journey is the one that may barely assume anything.

        It assumes exactly what its own opening assumes: that somebody
        who has installed s0ma knows what s0ma is. Every other idea it
        rests on is taught on the way, which is what makes the
        teaching-order gate below a real check of the whole list rather
        than of the tail of it.
        """
        assert journey.concepts_required == ("concept:s0ma",)

    def test_it_names_its_evidence_at_the_file_the_evidence_is_in(
        self, journey: JourneyRecord
    ) -> None:
        assert [(item.id, item.source) for item in journey.evidence] == [
            (EVIDENCE, "docs/s0ma_src/evidence/first-project.json")
        ]
        assert (REPO_ROOT / journey.evidence[0].source).is_file()


# ---------------------------------------------------------------------------
# The teaching order
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheTeachingOrder:
    """Nothing rests on an idea the reader has not met yet."""

    def test_the_order_is_the_one_this_milestone_authored(
        self, journey: JourneyRecord
    ) -> None:
        assert journey.concepts_taught == EXPECTED_TAUGHT

    def test_every_taught_concept_is_one_somebody_wrote(
        self, journey: JourneyRecord, live: Any
    ) -> None:
        written = {normalize_id(record.id) for record in live.bundle.concepts}
        for identifier in journey.concepts_taught:
            assert normalize_id(identifier) in written, identifier

    def test_the_gate_has_real_prerequisites_to_walk(
        self, journey: JourneyRecord, live: Any
    ) -> None:
        """Anti-vacuity: a green order over concepts with no edges proves nothing."""
        concepts = {normalize_id(record.id): record for record in live.bundle.concepts}
        edges = sum(
            1
            for taught in journey.concepts_taught
            for relation, _ in concepts[normalize_id(taught)].related_concepts
            if relation == "requires"
        )
        assert edges >= 6, "the teaching gate is passing by having nothing to check"

    def test_the_order_is_green_on_the_real_concept_graph(
        self, journey: JourneyRecord, live: Any
    ) -> None:
        index = ReferenceIndex.of(live.bundle)
        bundle = dataclasses.replace(live.bundle, journeys=(journey,))
        codes = [item.code for item in check_journeys(bundle, index)]
        assert DOC_TEACHING_ORDER not in codes

    def test_moving_one_idea_in_front_of_what_it_rests_on_is_red(
        self, journey: JourneyRecord, live: Any
    ) -> None:
        """The mutation the gate exists for, over the real graph.

        ``concept:self-model`` rests on two ideas, ``concept:intent`` and
        ``concept:registry-snapshot``, and the authored order teaches both
        before it. Moving it to just behind the first leaves that one
        satisfied and the second not, so the mutation isolates a single
        edge: every reference still resolves, and the path is still
        wrong, which is the failure only an ordered field can carry.
        """
        moved = list(journey.concepts_taught)
        moved.remove("concept:self-model")
        moved.insert(moved.index("concept:intent") + 1, "concept:self-model")
        mutated = dataclasses.replace(journey, concepts_taught=tuple(moved))
        index = ReferenceIndex.of(live.bundle)
        bundle = dataclasses.replace(live.bundle, journeys=(mutated,))
        found = [
            item for item in check_journeys(bundle, index) if item.code == DOC_TEACHING_ORDER
        ]
        assert len(found) == 1
        assert "concept:self-model" in found[0].message
        assert "concept:registry-snapshot" in found[0].message
        assert "step 2" in found[0].message


# ---------------------------------------------------------------------------
# The approval boundaries — the milestone's judgement call, pinned
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheApprovalBoundaries:
    """Writing is not approving, and this path asks the reader for nothing."""

    def test_no_step_declares_a_boundary(self, journey: JourneyRecord) -> None:
        assert journey.approval_boundaries() == ()

    def test_and_none_of_its_surfaces_asks_for_one(
        self, journey: JourneyRecord, live: Any
    ) -> None:
        """The other direction, which is what makes the first one correct.

        A boundary is owed where a surface declares the ``approval`` side
        effect. Two of this path's surfaces write files and neither asks,
        so an empty boundary is the answer rather than a silence — and if
        one of them ever starts asking, this is the test that says so.
        """
        surfaces = {normalize_id(record.id): record for record in live.bundle.surfaces}
        writing = set()
        for step in journey.steps:
            record = surfaces[normalize_id(step.surface)]
            assert APPROVAL_EFFECT not in record.side_effects, record.id
            if "write" in record.side_effects:
                writing.add(record.id)
        assert writing == {"cli:s0ma/new", "cli:s0ma/build", "cli:s0ma/check"}


# ---------------------------------------------------------------------------
# The evidence
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def replays(fixture_record: EvidenceRecord) -> tuple[Replay, Replay]:
    """Two replays of the fixture, run once and shared by the class."""
    return replay(fixture_record), replay(fixture_record)


@requires_checkout
class TestTheEvidence:
    """The transcript still describes the product, twice, identically."""

    def test_the_ledger_accounts_for_exactly_the_journey_steps(
        self, fixture_record: EvidenceRecord, journey: JourneyRecord
    ) -> None:
        steps = {normalize_id(step.surface) for step in journey.steps}
        accounted = {normalize_id(name) for name in fixture_record.covers} | {
            normalize_id(name) for name, _ in fixture_record.not_covered
        }
        assert accounted == steps

    def test_nothing_is_explained_away(self, fixture_record: EvidenceRecord) -> None:
        """Every step of this path is reachable from the command line.

        The prototype this milestone enriched had two steps on other
        channels and a written reason for each; the enriched path is one
        channel end to end, so an empty ``not_covered`` is a stronger
        claim rather than a missing one.
        """
        assert fixture_record.not_covered == ()
        assert fixture_record.channel == CHANNEL_CLI
        assert len(fixture_record.covers) == len(set(EXPECTED_STEPS))

    def test_the_transcript_writes_the_module_wrong_then_right(
        self, fixture_record: EvidenceRecord
    ) -> None:
        """The loop the guide teaches, present in the evidence as two edits."""
        written = _writes(fixture_record)
        assert len(written) == 2
        broken, fixed = written
        assert broken.path == fixed.path == "src/greeting.s0ma"
        assert "layer: domain" in broken.text
        assert broken.text == fixed.text.replace("layer: DOMAIN", "layer: domain", 1)

    @requires_server
    def test_the_fixture_still_describes_the_product(
        self, fixture_record: EvidenceRecord, replays: tuple[Replay, Replay]
    ) -> None:
        found = compare(fixture_record, replays[0])
        assert found.ok, [item.rendered() for item in found.findings]

    @requires_server
    def test_two_replays_are_byte_equal(
        self, replays: tuple[Replay, Replay]
    ) -> None:
        """The determinism gate: two runs, two temporary directories, one text."""
        first, second = replays
        assert first.transcript == second.transcript
        assert first.transcript.endswith("\n")
        assert "\r" not in first.transcript

    @requires_server
    def test_no_machine_path_survives_normalization(
        self, replays: tuple[Replay, Replay]
    ) -> None:
        text = replays[0].transcript
        assert str(REPO_ROOT) not in text
        assert "/var/folders/" not in text
        assert "s0ma-evidence-" not in text


# ---------------------------------------------------------------------------
# The guide
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheGuide:
    """The page teaches only what the transcript proves."""

    def test_the_guide_is_where_the_journey_says_it_is(self) -> None:
        assert (REPO_ROOT / GUIDE).is_file()

    def test_it_is_utf8_with_line_feeds_and_one_trailing_newline(self) -> None:
        raw = (REPO_ROOT / GUIDE).read_bytes()
        assert b"\r" not in raw
        assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
        raw.decode("utf-8")

    def test_every_command_it_shows_is_one_the_fixture_runs(
        self, guide_text: str, fixture_record: EvidenceRecord
    ) -> None:
        """The rule the whole guide rests on: shown means proven.

        Every line of every ``bash`` block either invokes the product —
        in which case the transcript has to have run exactly it — or is
        one of the navigation lines the replay performs structurally
        instead of as a command.
        """
        ran = _commands(fixture_record)
        shown: list[str] = []
        for block in _blocks(guide_text, "bash"):
            for line in block.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                shown.append(stripped)
                if stripped in NAVIGATION:
                    continue
                assert stripped in ran, stripped
        assert len(shown) >= 6, "a guide showing nothing proves nothing"

    def test_every_command_the_fixture_runs_is_shown_at_least_once(
        self, guide_text: str, fixture_record: EvidenceRecord
    ) -> None:
        """The converse, which is what stops the page teaching half a path.

        A transcript may legitimately run more than a guide shows; what it
        may not do is prove a path the page never walks its reader down.
        """
        shown = {
            line.strip()
            for block in _blocks(guide_text, "bash")
            for line in block.splitlines()
            if line.strip()
        }
        assert _commands(fixture_record) <= shown

    def test_every_line_of_output_it_quotes_was_really_asserted(
        self, guide_text: str, fixture_record: EvidenceRecord
    ) -> None:
        """Quoted output is a claim about the product, checked as one."""
        asserted = _expectations(fixture_record)
        quoted = 0
        for block in _blocks(guide_text, "text"):
            for line in block.splitlines():
                if not line.strip():
                    continue
                claim = line.replace(GUIDE_PROJECT, FIXTURE_PROJECT)
                assert claim in asserted, claim
                quoted += 1
        assert quoted >= 4

    def test_the_inline_output_it_quotes_was_really_asserted_too(
        self, guide_text: str, fixture_record: EvidenceRecord
    ) -> None:
        asserted = _expectations(fixture_record)
        spans = set(_spans(guide_text))
        for quoted in QUOTED_INLINE:
            assert quoted in asserted, quoted
            assert quoted in spans, f"{quoted} is no longer quoted by the guide"

    def test_the_module_it_asks_the_reader_to_write_is_the_one_that_was_run(
        self, guide_text: str, fixture_record: EvidenceRecord
    ) -> None:
        """The strongest form of the rule: the source itself, byte for byte."""
        blocks = _blocks(guide_text, "s0ma")
        assert len(blocks) == 1
        _, fixed = _writes(fixture_record)
        assert blocks[0] == fixed.text

    def test_every_command_it_names_in_prose_is_one_this_path_addresses(
        self, guide_text: str, journey: JourneyRecord
    ) -> None:
        """A pointer is not a transcript, but it still has to point at something.

        An inline ``s0ma <command>`` is not a line the reader is told to
        type, so the fixture does not have to have run it — but it must
        name a capability this journey either steps through or sends a
        reader to when something fails, or the page is teaching a surface
        nobody checked.
        """
        addressed = {normalize_id(step.surface) for step in journey.steps}
        addressed |= {
            normalize_id(path.next_surface) for path in journey.recovery_paths
        }
        named = 0
        for span in _spans(guide_text):
            parts = span.split()
            if len(parts) < 2 or parts[0] != "s0ma":
                continue
            named += 1
            assert normalize_id(f"cli:s0ma/{parts[1]}") in addressed, span
        assert named >= 2

    def test_it_sends_the_reader_at_the_install_route_by_name(
        self, guide_text: str
    ) -> None:
        """The prerequisite this journey starts after, cited rather than repeated.

        By document, never by an address: the route the public repository
        offers is stated once in the cold-start guide's first section, and a
        guide that pasted a URL would be the one copy of it nobody updates.
        The keyed installer's page is not named — that route is not the
        public repository's.
        """
        assert "../getting-started.md" in guide_text
        assert "../hosting-getting-started.md" not in guide_text
        assert "http://" not in guide_text
        assert "https://" not in guide_text

    def test_it_closes_on_troubleshooting_and_uninstalling(
        self, guide_text: str
    ) -> None:
        assert "../troubleshooting.md" in guide_text
        assert "../uninstall.md" in guide_text

    def test_every_link_it_makes_resolves_on_disk(self, guide_text: str) -> None:
        """Relative, and to something that is really there.

        On disk rather than in the index, because this page is untracked
        until the milestone's own commit lands; the repository's link gate
        asks the tracked question afterwards.
        """
        directory = (REPO_ROOT / GUIDE).parent
        found = 0
        for target in _LINK.findall(guide_text):
            if ":" in target:
                continue
            path, _, anchor = target.partition("#")
            assert not path.startswith("/"), target
            assert (directory / path).resolve().is_file(), target
            assert anchor == "", "this guide cites documents, not headings"
            found += 1
        assert found >= 4


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheVoice:
    """Everything a reader reads is in the product's own words."""

    def test_the_journey_is_clean(self, journey: JourneyRecord) -> None:
        assert check_journey_voice(journey, GUIDE) == []

    def test_the_fixture_is_clean(self, fixture_record: EvidenceRecord) -> None:
        assert check_evidence_voice(fixture_record) == []

    def test_the_guide_is_clean(self, guide_text: str) -> None:
        """The same battery the model runs over authored fields, over the page.

        A guide is not a record and no provider reads it, so nothing else
        would ever ask this of it — which is exactly why it is asked here.
        """
        offences = [
            (label, found.group(0))
            for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE
            for found in pattern.finditer(guide_text)
        ]
        assert offences == []
