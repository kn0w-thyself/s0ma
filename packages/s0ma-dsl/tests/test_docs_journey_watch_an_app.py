"""Gates for ``journey:watch-an-app-being-built``, its guide, and its evidence.

The guide has a reader look at a finished example in studi0 and then watch
their own coding agent build one like it in three requests. Half of that
path is deterministic and half is not, and the line between them is what
this suite holds in place:

* **the path**: seven steps over surfaces this build really serves, in
  the order a reader walks them, composing with nothing to report;
* **the evidence replays the half that needs no agent**, in two
  transcripts, one per project the reader makes. In the first the example
  is made and its graph read back. In the second the reader's own project
  is made, and the example's three builds are landed in it one after
  another from the sources committed under
  ``packages/s0ma-studi0/tests/fixtures/pipeline_builds/.sources/``, byte
  for byte, with the graph read back after each. ``s0ma build`` stands in
  for the agent's ``build_project`` call, and both ledgers say so. Two
  transcripts rather than one because a transcript prepares one project
  and runs in it, and this path has the reader make two;
* **the guide agrees with the evidence**: every command a reader is shown
  is one the transcript runs, save the two that serve until interrupted,
  and the commands that only stand in for the agent are never shown to the
  reader as theirs;
* **the guide quotes the page**: every fixed sentence it quotes from
  studi0 is a string in the page's own source, so a reworded page fails
  here rather than leaving the guide describing a page nobody has.

**Cost.** Each fixture is replayed twice, once for the green check and once
for the determinism comparison, cached for the whole module.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model.application import build as build_documentation
from s0ma_dsl.docs_model.evidence import (
    CHANNEL_CLI,
    CommandStep,
    EvidenceLibrary,
    Replay,
    WriteStep,
    check_evidence_voice,
    compare,
    replay,
)
from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.providers_concepts import FORBIDDEN_IN_AUTHORED_PROSE
from s0ma_dsl.docs_model.providers_journeys import check_journey_voice
from s0ma_dsl.docs_model.validate import TEACHING_PREREQUISITE

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.evidence import EvidenceRecord
    from s0ma_dsl.docs_model.records import JourneyRecord

REPO_ROOT = Path(__file__).resolve().parents[3]

JOURNEY_ID = "journey:watch-an-app-being-built"
JOURNEY_SOURCE = "docs/s0ma_src/journeys/watch-an-app-being-built.json"
EXAMPLE_ID = "example:transcript/watch-an-app-being-built-example"
GROWTH_ID = "example:transcript/watch-an-app-being-built-growth"
EVIDENCE: tuple[tuple[str, str], ...] = (
    (EXAMPLE_ID, "docs/s0ma_src/evidence/watch-an-app-being-built-example.json"),
    (GROWTH_ID, "docs/s0ma_src/evidence/watch-an-app-being-built-growth.json"),
)
GUIDE = "docs/guides/watch-an-app-being-built.md"

#: The page's own source, read as text and never imported.
APP_JS = REPO_ROOT / "packages" / "s0ma-studi0" / "s0ma_src" / "assets" / "app.js"

#: The three builds the guide's requests describe, as studi0's own tests
#: keep them.
SOURCES = REPO_ROOT.joinpath(
    "packages", "s0ma-studi0", "tests", "fixtures", "pipeline_builds", ".sources"
)
BUILDS = ("build_1", "build_2", "build_3")

#: The path as authored. Written down rather than read off the record, so
#: a step quietly appearing or moving fails here by name.
EXPECTED_STEPS: tuple[str, ...] = (
    "cli:s0ma/new",
    "cli:s0ma/studi0",
    "studi0:action/api/graph",
    "cli:s0ma/new",
    "cli:s0ma/studi0",
    "mcp:tool/build_project",
    "studi0:action/api/state",
)

#: The four ideas the path leaves a reader with, in the order they are met.
EXPECTED_TAUGHT: tuple[str, ...] = (
    "concept:layer",
    "concept:intent",
    "concept:module",
    "concept:contract",
)

#: The commands the guide shows that no transcript can replay: each serves
#: until it is interrupted. Pinned so a third appearing is a failure.
UNREPLAYABLE_IN_GUIDE: frozenset[str] = frozenset({"s0ma studi0 example", "s0ma studi0 song"})

#: The transcript's own reading commands and its stand-in for the agent's
#: build. A reader never types these, so the guide must not show them as
#: commands; they are how the transcript sees what the page would draw.
STAND_INS: frozenset[str] = frozenset(
    {
        "s0ma graph . --format json --detail full",
        "s0ma build",
    }
)

#: Sentences the guide quotes from studi0 that the page prints whole.
#: Sentences the page assembles from counts ("Build 2 · added 2 parts,
#: changed 1") are not here: they are read off the example's real builds,
#: which the evidence lands, and the page's assembly of them is studi0's
#: own suite's to pin.
PAGE_QUOTES: tuple[str, ...] = (
    "What changed since you opened this page",
    "Nothing yet.",
    "Outlined parts arrived in the newest build.",
    "more parts are hidden by the toolbar toggles.",
    "Show the rest",
    "Nothing is built yet.",
    "changed since the last build",
    "agent narration",
    "self-reported by the agent working here",
    "On this page",
    "what it is for",
    "what it promises",
    "what it must never do",
    "what it needs before it runs",
    "what it leans on",
    "what leans on it",
    " is explained under ",
    "tests and docs",
)

_FENCE = re.compile(r"^```(?P<info>[A-Za-z0-9_-]*)\s*$")


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


@pytest.fixture(scope="module")
def live() -> Any:
    """The whole documentation build, composed once for this module."""
    return build_documentation(REPO_ROOT)


@pytest.fixture(scope="module")
def journey(live: Any) -> JourneyRecord:
    for record in live.bundle.journeys:
        if normalize_id(record.id) == normalize_id(JOURNEY_ID):
            return record
    raise AssertionError(f"{JOURNEY_ID} is not in the composed build")


@pytest.fixture(scope="module")
def fixtures() -> dict[str, EvidenceRecord]:
    library = EvidenceLibrary.load(REPO_ROOT)
    return {identifier: library.by_id(identifier) for identifier, _ in EVIDENCE}


@pytest.fixture(scope="module")
def replays(fixtures: dict[str, EvidenceRecord]) -> dict[str, tuple[Replay, Replay]]:
    """Two replays of each fixture, run once for the whole module."""
    return {key: (replay(record), replay(record)) for key, record in fixtures.items()}


@pytest.fixture(scope="module")
def guide_text() -> str:
    return (REPO_ROOT / GUIDE).read_text(encoding="utf-8")


def _commands_in(text: str) -> list[str]:
    """Every command line inside a ``bash`` fence, in document order."""
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
    return " ".join(part if " " not in part else f'"{part}"' for part in argv)


def _source_files(build: str) -> dict[str, str]:
    root = SOURCES / build
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ---------------------------------------------------------------------------
# The path
# ---------------------------------------------------------------------------


@requires_checkout
class TestThePath:
    """Seven steps over surfaces this build serves, in the authored order."""

    def test_the_steps_are_the_ones_this_guide_walks(self, journey: JourneyRecord) -> None:
        assert tuple(step.surface for step in journey.steps) == EXPECTED_STEPS
        assert all(not step.approval_boundary.strip() for step in journey.steps)

    def test_this_journey_composes_with_nothing_to_report(self, live: Any) -> None:
        mine = [
            item.rendered()
            for item in live.findings
            if any(key in item.rendered() for key in (JOURNEY_ID, EXAMPLE_ID, GROWTH_ID))
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

    def test_the_teaching_order_holds_against_the_authored_concept_graph(
        self, live: Any, journey: JourneyRecord
    ) -> None:
        concepts = {normalize_id(record.id): record for record in live.bundle.concepts}
        assert journey.concepts_taught == EXPECTED_TAUGHT
        scope = {normalize_id(item) for item in journey.concepts_required}
        for taught in journey.concepts_taught:
            scope.add(normalize_id(taught))
            for relation, target in concepts[normalize_id(taught)].related_concepts:
                if relation == TEACHING_PREREQUISITE:
                    assert normalize_id(target) in scope, (taught, target)

    def test_the_files_are_utf8_with_line_feeds_and_one_trailing_newline(self) -> None:
        for relative in (JOURNEY_SOURCE, *(source for _, source in EVIDENCE), GUIDE):
            raw = (REPO_ROOT / relative).read_bytes()
            assert b"\r" not in raw, relative
            assert raw.endswith(b"\n") and not raw.endswith(b"\n\n"), relative
            raw.decode("utf-8")


# ---------------------------------------------------------------------------
# The evidence
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheEvidence:
    """The half of the path that needs no agent, replayed for real."""

    def test_both_fixtures_evidence_this_journey_from_the_files_they_are_cited_at(
        self, fixtures: dict[str, EvidenceRecord], journey: JourneyRecord
    ) -> None:
        assert [(item.id, item.source) for item in journey.evidence] == list(EVIDENCE)
        for identifier, source in EVIDENCE:
            record = fixtures[identifier]
            assert record.journey == JOURNEY_ID
            assert record.channel == CHANNEL_CLI
            assert record.source == source

    @pytest.mark.parametrize("identifier", [name for name, _ in EVIDENCE])
    def test_each_ledger_accounts_for_exactly_the_steps_this_path_takes(
        self, identifier: str, fixtures: dict[str, EvidenceRecord], journey: JourneyRecord
    ) -> None:
        record = fixtures[identifier]
        steps = {normalize_id(step.surface) for step in journey.steps}
        covered = {normalize_id(item) for item in record.covers}
        uncovered = {normalize_id(item) for item, _ in record.not_covered}
        assert covered | uncovered == steps
        assert covered & uncovered == set()
        assert covered == {normalize_id("cli:s0ma/new")}

    @pytest.mark.parametrize("identifier", [name for name, _ in EVIDENCE])
    def test_the_agents_build_is_never_claimed_as_covered(
        self, identifier: str, fixtures: dict[str, EvidenceRecord]
    ) -> None:
        """The one step a model takes is in the ledger of what is not replayed."""
        record = fixtures[identifier]
        assert "mcp:tool/build_project" in dict(record.not_covered)
        assert "mcp:tool/build_project" not in record.covers

    @pytest.mark.parametrize("identifier", [name for name, _ in EVIDENCE])
    def test_every_uncovered_step_says_why_in_a_written_sentence(
        self, identifier: str, fixtures: dict[str, EvidenceRecord]
    ) -> None:
        for surface, reason in fixtures[identifier].not_covered:
            assert len(reason.split()) >= 20, surface

    def test_the_two_projects_are_the_two_the_reader_makes(
        self, fixtures: dict[str, EvidenceRecord]
    ) -> None:
        assert fixtures[EXAMPLE_ID].scaffold.argv == (
            "s0ma",
            "new",
            "project",
            "example",
            "--template",
            "pipeline",
        )
        assert fixtures[GROWTH_ID].scaffold.argv == ("s0ma", "new", "project", "song")

    def test_the_writes_are_the_three_committed_builds_byte_for_byte(
        self, fixtures: dict[str, EvidenceRecord]
    ) -> None:
        """Each build writes exactly the files that differ from the build before.

        The transcript carries the sources as text, because a replay writes
        nowhere but its own folder. This is what stops that copy drifting
        from the one studi0's own tests build: the writes are regrouped at
        each build command and compared with the committed tree.
        """
        groups: list[dict[str, str]] = []
        pending: dict[str, str] = {}
        for step in fixtures[GROWTH_ID].steps:
            if isinstance(step, WriteStep):
                pending[step.path] = step.text
            elif isinstance(step, CommandStep) and step.argv == ("s0ma", "build"):
                groups.append(pending)
                pending = {}
        assert pending == {}
        assert len(groups) == len(BUILDS)
        previous: dict[str, str] = {}
        for build, written in zip(BUILDS, groups, strict=True):
            current = _source_files(build)
            changed = {path: text for path, text in current.items() if previous.get(path) != text}
            assert written == changed, build
            previous = current

    @pytest.mark.parametrize("identifier", [name for name, _ in EVIDENCE])
    def test_the_transcript_still_describes_the_product(
        self,
        identifier: str,
        fixtures: dict[str, EvidenceRecord],
        replays: dict[str, tuple[Replay, Replay]],
    ) -> None:
        found = compare(fixtures[identifier], replays[identifier][0])
        assert found.ok, [item.rendered() for item in found.findings]

    @pytest.mark.parametrize("identifier", [name for name, _ in EVIDENCE])
    def test_two_replays_are_byte_equal(
        self, identifier: str, replays: dict[str, tuple[Replay, Replay]]
    ) -> None:
        first, second = replays[identifier]
        assert first.transcript == second.transcript
        assert first.transcript.endswith("\n")
        assert "\r" not in first.transcript

    @pytest.mark.parametrize("identifier", [name for name, _ in EVIDENCE])
    def test_no_machine_path_survives_normalization(
        self, identifier: str, replays: dict[str, tuple[Replay, Replay]]
    ) -> None:
        text = replays[identifier][0].transcript
        assert str(REPO_ROOT) not in text
        assert "/var/folders/" not in text
        assert "s0ma-evidence-" not in text


# ---------------------------------------------------------------------------
# The guide
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheGuide:
    """What a reader is told, held against what the machine ran and the page says."""

    def test_every_command_shown_is_one_a_transcript_runs(
        self, fixtures: dict[str, EvidenceRecord], guide_text: str
    ) -> None:
        """Both ways: every command a reader types is run, and the stand-ins are not shown."""
        shown = set(_commands_in(guide_text))
        ran: set[str] = set()
        for record in fixtures.values():
            ran.add(_rendered(record.scaffold.argv))
            ran.update(
                _rendered(step.argv) for step in record.steps if isinstance(step, CommandStep)
            )
        assert ran >= STAND_INS
        assert shown == (ran - STAND_INS) | UNREPLAYABLE_IN_GUIDE

    def test_the_guide_says_plainly_that_the_agents_work_is_not_replayed(
        self, guide_text: str
    ) -> None:
        flowed = " ".join(guide_text.split())
        assert "**Not replayed:** your agent's work." in flowed
        assert "What your agent builds will differ from the example." in flowed

    @pytest.mark.parametrize("quote", PAGE_QUOTES)
    def test_every_fixed_sentence_quoted_from_the_page_is_the_pages_own(
        self, quote: str, guide_text: str
    ) -> None:
        flowed = " ".join(guide_text.split())
        assert quote.strip() in flowed, quote
        assert quote in APP_JS.read_text(encoding="utf-8"), quote

    def test_every_intra_repo_link_resolves_to_a_file_that_is_there(self, guide_text: str) -> None:
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
# The voice
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheVoice:
    def test_the_journey_record_is_in_the_products_voice(self, journey: JourneyRecord) -> None:
        assert [item.rendered() for item in check_journey_voice(journey, JOURNEY_SOURCE)] == []

    @pytest.mark.parametrize("identifier", [name for name, _ in EVIDENCE])
    def test_the_fixtures_written_sentences_are_in_the_products_voice(
        self, identifier: str, fixtures: dict[str, EvidenceRecord]
    ) -> None:
        assert [item.rendered() for item in check_evidence_voice(fixtures[identifier])] == []

    def test_the_guide_prose_never_uses_a_word_this_product_does_not(self, guide_text: str) -> None:
        offences = [
            (label, found.group(0))
            for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE
            for found in [pattern.search(guide_text)]
            if found is not None
        ]
        assert offences == []
