"""Gates for E2 — transcript fixtures, their replay, and the T3 split.

Milestone E2 of the docs-function plan (internal) §10. Four things are held
in place here, in the order a fixture meets them:

* **the format** (T1/T2) — one file per fixture, its shape refused with
  the JSON path of the value that is wrong, its placeholder vocabulary
  closed, its regex escape hatch fenced behind a written reason;
* **the comparison** — pure, over a captured transcript, so a stale
  expectation is located at a command index and a line without anything
  having to run;
* **the three real fixtures** (T4) — replayed for real against the
  installed command line and the real authoring server, green, and
  **byte-equal across two replays**, which is the property that makes a
  transcript evidence rather than a snapshot of one machine;
* **the split** (T3) — the build *resolves* evidence and the suite *runs*
  it, with a test pinning the two sets equal so a fixture cannot be
  resolved by one and run by nobody.

``DOC_EXAMPLE_FAILED`` itself is fired in the C9 battery
(``test_docs_model_negative.py``, ``TestEvidence``), which is where every
``DOC_*`` code in the ``docs_model`` tree is accounted for. What is here
is the other half: that a real fixture with a real divergence produces it,
and that the three committed fixtures do not.

**Cost.** The live class replays each fixture twice, once for the green
check and once for the determinism comparison, and caches both — six
replays for the module rather than one per test.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.docs_model.application import build as build_documentation
from s0ma_dsl.docs_model.evidence import (
    CHANNEL_CLI,
    CHANNEL_MCP,
    CHANNELS,
    DOC_EXAMPLE_FAILED,
    EVIDENCE_DIR,
    EVIDENCE_SCHEMA,
    MATCHES,
    PLACEHOLDERS,
    PROGRAMS,
    CallStep,
    CommandStep,
    DocsEvidenceError,
    EvidenceLibrary,
    EvidenceRecord,
    Expectation,
    FieldExpectation,
    Observed,
    Replay,
    WriteStep,
    check_evidence_voice,
    compare,
    normalize,
    passing,
    replay,
    verify,
)
from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.providers_concepts import DOC_VOICE_VIOLATION
from s0ma_dsl.docs_model.validate import (
    DOC_GATE_VACUOUS,
    DOC_JOURNEY_UNRESOLVED,
    DOC_JOURNEY_UNTESTED,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The three fixtures E2 commits, with the channel each speaks and the
#: journey each evidences. Written down rather than globbed: the point of
#: the milestone is that *these three paths* have evidence, and a fixture
#: quietly disappearing should fail here by name.
EXPECTED_FIXTURES: tuple[tuple[str, str, str], ...] = (
    ("example:transcript/drift-recovery", CHANNEL_CLI, "journey:drift-recovery"),
    ("example:transcript/first-module", CHANNEL_CLI, "journey:first-module"),
    ("example:transcript/first-project", CHANNEL_CLI, "journey:first-project"),
    (
        "example:transcript/mcp-authoring-loop",
        CHANNEL_MCP,
        "journey:mcp-authoring-loop",
    ),
    (
        "example:transcript/retrofit-existing-codebase",
        CHANNEL_CLI,
        "journey:retrofit-existing-codebase",
    ),
    ("example:transcript/studi0-feedback", CHANNEL_CLI, "journey:studi0-feedback"),
    ("example:transcript/studi0-viewing", CHANNEL_CLI, "journey:studi0-viewing"),
)

#: The journey count is a claim about the journeys directory, not about the
#: fixture table — the E wave proved the two can drift apart mid-flight, so
#: the armed-gate proof counts this constant rather than EXPECTED_FIXTURES.
EXPECTED_JOURNEY_COUNT = 7

has_server = importlib.util.find_spec("s0ma_mcp") is not None

requires_server = pytest.mark.skipif(
    not has_server, reason="the authoring server is not installed in this environment"
)


# ---------------------------------------------------------------------------
# Fixture material
# ---------------------------------------------------------------------------


def _valid() -> dict[str, Any]:
    """A minimal fixture that loads, for the refusals to deviate from."""
    return {
        "schema": EVIDENCE_SCHEMA,
        "record": {
            "channel": CHANNEL_CLI,
            "covers": ["cli:s0ma/check"],
            "id": "example:transcript/sample",
            "intent": "A short path, walked for real.",
            "journey": "journey:sample",
            "not_covered": [],
            "scaffold": {
                "argv": ["s0ma", "new", "project", "demo"],
                "kind": "new-project",
                "workdir": "demo",
            },
            "steps": [
                {
                    "argv": ["s0ma", "check"],
                    "exit_code": 0,
                    "stderr": [],
                    "stdout": [{"match": "line", "text": "3 file(s) checked. No errors."}],
                }
            ],
        },
    }


def _written(tmp_path: Path, document: dict[str, Any], *, stem: str = "sample") -> EvidenceLibrary:
    """Write one fixture into a throwaway library and read it back."""
    directory = tmp_path / "evidence"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{stem}.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return EvidenceLibrary.load(tmp_path, relative="evidence")


def _refused(tmp_path: Path, document: dict[str, Any], *, stem: str = "sample") -> str:
    """The refusal one malformed fixture produces, as text."""
    with pytest.raises(DocsEvidenceError) as raised:
        _written(tmp_path, document, stem=stem)
    return str(raised.value)


def _observed(text: str = "", *, exit_code: int | None = 0, **extra: Any) -> Observed:
    """One captured step, for the pure comparison tests."""
    return Observed(
        label=extra.get("label", "$ s0ma check"),
        streams=extra.get("streams", (("stdout", text), ("stderr", ""))),
        exit_code=exit_code,
        structured=extra.get("structured"),
        timed_out=extra.get("timed_out", False),
    )


def _captured(record: EvidenceRecord, *observed: Observed) -> Replay:
    """A replay nobody ran: the scaffold line, then the given steps."""
    scaffold = Observed(
        label="# scaffold", streams=(), exit_code=0, structured=None, timed_out=False
    )
    return Replay(
        record_id=record.id, observed=(scaffold, *observed), transcript="<captured>"
    )


def _sample(**overrides: Any) -> EvidenceRecord:
    """One in-memory record, for tests that never touch a file."""
    document = _valid()
    document["record"].update(overrides)
    from s0ma_dsl.docs_model.evidence import _read_record  # noqa: PLC0415

    return _read_record(document["record"], "#/record", "sample.json", "sample")


# ---------------------------------------------------------------------------
# The format (T1, T2)
# ---------------------------------------------------------------------------


class TestTheFormat:
    """What an author may write, and what is refused with a path."""

    def test_a_minimal_fixture_loads(self, tmp_path: Path) -> None:
        library = _written(tmp_path, _valid())
        (record,) = library.records
        assert record.id == "example:transcript/sample"
        assert record.channel == CHANNEL_CLI
        assert record.source == "evidence/sample.json"

    def test_an_absent_directory_is_an_empty_library(self, tmp_path: Path) -> None:
        """Not a refusal: a repository with no evidence has written none.

        ``DOC_JOURNEY_UNTESTED`` tells that story per journey, which is a
        better report than an exception that stops the build telling any
        story at all.
        """
        assert EvidenceLibrary.load(tmp_path, relative="nowhere").records == ()

    def test_a_file_that_is_there_and_broken_is_refused(self, tmp_path: Path) -> None:
        directory = tmp_path / "evidence"
        directory.mkdir()
        (directory / "sample.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(DocsEvidenceError) as raised:
            EvidenceLibrary.load(tmp_path, relative="evidence")
        assert "is not readable as JSON" in str(raised.value)

    def test_the_schema_is_the_fixture_format_and_not_the_models(
        self, tmp_path: Path
    ) -> None:
        document = _valid()
        document["schema"] = "s0ma-docs-model@1"
        assert EVIDENCE_SCHEMA in _refused(tmp_path, document)

    def test_a_stray_key_is_refused_by_name(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["notes"] = "extra"
        found = _refused(tmp_path, document)
        assert "unexpected: ['notes']" in found

    def test_the_file_stem_is_the_ids_last_segment(self, tmp_path: Path) -> None:
        found = _refused(tmp_path, _valid(), stem="other")
        assert "the file is named other.json" in found

    def test_an_id_that_is_not_an_example_id_is_refused(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["id"] = "journey:sample"
        assert "is not an example id" in _refused(tmp_path, document)

    def test_a_journey_that_is_not_a_journey_id_is_refused(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["journey"] = "concept:module"
        assert "is not a journey id" in _refused(tmp_path, document)

    def test_a_channel_nobody_can_replay_is_refused(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["channel"] = "rest"
        assert "is not one of" in _refused(tmp_path, document)

    def test_a_program_outside_the_closed_set_is_refused(self, tmp_path: Path) -> None:
        """The no-network guard with teeth: the whole list of runnable things."""
        document = _valid()
        document["record"]["steps"][0]["argv"] = ["curl", "https://example.invalid"]
        found = _refused(tmp_path, document)
        assert "is not a program a transcript may run" in found
        assert str(list(PROGRAMS)) in found

    def test_a_shell_string_is_not_a_command(self, tmp_path: Path) -> None:
        """argv or nothing — a string would eventually be asked about a pipe."""
        document = _valid()
        document["record"]["steps"][0]["argv"] = "s0ma check"
        assert "expected a list" in _refused(tmp_path, document)

    def test_an_unknown_placeholder_is_refused_rather_than_never_matching(
        self, tmp_path: Path
    ) -> None:
        document = _valid()
        document["record"]["steps"][0]["stdout"] = [
            {"match": "contains", "text": "wrote {tmpdir}/build"}
        ]
        found = _refused(tmp_path, document)
        assert "{tmpdir}" in found
        assert str(sorted(PLACEHOLDERS)) in found

    def test_a_regex_without_a_written_reason_is_refused(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["steps"][0]["stdout"] = [
            {"match": "regex", "text": r"^\d+ file"}
        ]
        assert "absent: ['reason']" in _refused(tmp_path, document)

    def test_a_regex_with_a_reason_is_allowed(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["steps"][0]["stdout"] = [
            {
                "match": "regex",
                "reason": "the count moves with the starter template, and the "
                "shape of the line is what this step is evidence of",
                "text": r"^\d+ file\(s\) checked\. No errors\.$",
            }
        ]
        (record,) = _written(tmp_path, document).records
        step = record.steps[0]
        assert isinstance(step, CommandStep)
        assert step.stdout[0].match == "regex"
        assert step.stdout[0].reason

    def test_an_unreadable_regex_is_refused(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["steps"][0]["stdout"] = [
            {"match": "regex", "reason": "because", "text": "([unclosed"}
        ]
        assert "is not a readable regular expression" in _refused(tmp_path, document)

    def test_a_match_kind_nobody_implements_is_refused(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["steps"][0]["stdout"] = [{"match": "roughly", "text": "x"}]
        assert str(list(MATCHES)) in _refused(tmp_path, document)

    def test_a_path_that_leaves_the_throwaway_tree_is_refused(
        self, tmp_path: Path
    ) -> None:
        document = _valid()
        document["record"]["steps"].append(
            {"path": "../../etc/passwd", "text": "nothing"}
        )
        assert "is not a path inside the throwaway project" in _refused(tmp_path, document)

    def test_a_transcript_that_runs_nothing_is_refused(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["steps"] = [{"path": "src/x.s0ma", "text": "module x\n"}]
        assert "runs nothing" in _refused(tmp_path, document)

    def test_a_step_may_write_a_file_between_two_commands(self, tmp_path: Path) -> None:
        """The loop is check, change what it told you about, check again."""
        document = _valid()
        document["record"]["steps"].insert(0, {"path": "src/x.s0ma", "text": "module x\n"})
        (record,) = _written(tmp_path, document).records
        assert isinstance(record.steps[0], WriteStep)
        assert isinstance(record.steps[1], CommandStep)

    def test_an_authored_tree_scaffold_needs_files(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["scaffold"] = {
            "files": {},
            "kind": "authored-tree",
            "workdir": ".",
        }
        assert "prepares nothing" in _refused(tmp_path, document)

    def test_the_ledger_halves_do_not_overlap(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["not_covered"] = [
            {"reason": "it does not run here", "surface": "cli:s0ma/check"}
        ]
        assert "both as covered and as not covered" in _refused(tmp_path, document)

    def test_the_ledger_is_sorted(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["covers"] = ["cli:s0ma/check", "cli:s0ma/build"]
        assert "is not sorted" in _refused(tmp_path, document)

    def test_one_id_cannot_be_declared_twice(self, tmp_path: Path) -> None:
        """Structurally, and by the stem rule rather than by a second check.

        The file's stem is the id's last segment and a directory holds one
        file per name, so two files under one id is a shape that cannot be
        written down. The refusal a reader gets says the true thing — this
        file is not named after this record — rather than a collision
        message about a state the format forbids.
        """
        directory = tmp_path / "evidence"
        directory.mkdir()
        for stem in ("sample", "other"):
            document = _valid()
            document["record"]["id"] = "example:transcript/sample"
            (directory / f"{stem}.json").write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(DocsEvidenceError) as raised:
            EvidenceLibrary.load(tmp_path, relative="evidence")
        assert "the file is named other.json" in str(raised.value)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    """Every machine fact becomes a placeholder, and only those."""

    def test_the_project_wins_over_the_temporary_root(self, tmp_path: Path) -> None:
        """Longest first, or ``{tmp}/demo`` would appear where ``{project}`` belongs."""
        project = tmp_path / "demo"
        found = normalize(
            f"wrote {project}/build", tmp=tmp_path, project=project, version="9.9.9"
        )
        assert found == "wrote {project}/build"

    def test_the_temporary_root_is_replaced_too(self, tmp_path: Path) -> None:
        project = tmp_path / "demo"
        found = normalize(
            f"cwd {tmp_path}", tmp=tmp_path, project=project, version="9.9.9"
        )
        assert found == "cwd {tmp}"

    def test_the_resolved_spelling_of_a_path_is_replaced(self, tmp_path: Path) -> None:
        """macOS hands one run both ``/var/...`` and ``/private/var/...``."""
        project = tmp_path / "demo"
        project.mkdir()
        found = normalize(
            f"real {project.resolve()}", tmp=tmp_path, project=project, version="9.9.9"
        )
        assert found == "real {project}"

    def test_the_toolchain_version_is_replaced(self, tmp_path: Path) -> None:
        found = normalize(
            '"transpiler_version": "9.9.9"',
            tmp=tmp_path,
            project=tmp_path,
            version="9.9.9",
        )
        assert found == '"transpiler_version": "{version}"'

    def test_a_measured_duration_is_elided(self, tmp_path: Path) -> None:
        """The one normalizer no live fixture needs yet, and the reason it exists.

        A duration is the classic byte that differs between two runs of
        one command. Nothing the three committed fixtures call reports
        one — which is why this is proved here rather than by a fixture —
        and the day a tool result grows a ``duration_ms``, the
        two-replay gate would go red without it.
        """
        found = normalize(
            '{"duration_ms": 12.5, "latency_ms": 40}',
            tmp=tmp_path,
            project=tmp_path,
            version="9.9.9",
        )
        assert found == '{"duration_ms": {duration}, "latency_ms": 40}'

    def test_line_endings_and_trailing_space_are_flattened(self, tmp_path: Path) -> None:
        found = normalize(
            "one   \r\ntwo\r", tmp=tmp_path, project=tmp_path, version="9.9.9"
        )
        assert found == "one\ntwo\n"

    def test_the_vocabulary_is_closed_and_documented(self) -> None:
        """Every token an author may write says what it stands for."""
        assert set(PLACEHOLDERS) == {"{tmp}", "{project}", "{version}", "{duration}"}
        for token, meaning in PLACEHOLDERS.items():
            assert token.startswith("{") and token.endswith("}")
            assert meaning.strip()


# ---------------------------------------------------------------------------
# The comparison (pure)
# ---------------------------------------------------------------------------


class TestTheComparison:
    """A stale expectation, located, without anything having to run."""

    def test_a_transcript_that_still_agrees_passes(self) -> None:
        record = _sample()
        found = compare(record, _captured(record, _observed("3 file(s) checked. No errors.")))
        assert found.ok
        assert found.divergence is None
        assert found.findings == ()

    def test_a_stale_expected_line_is_located(self) -> None:
        record = _sample()
        ran = _captured(record, _observed("nothing at all\n4 file(s) checked. No errors."))
        found = compare(record, ran)
        assert not found.ok
        assert found.divergence is not None
        assert found.divergence.step == 0
        assert found.divergence.stream == "stdout"
        assert found.divergence.expectation == 0
        assert found.divergence.line == 1
        assert "3 file(s) checked. No errors." in found.divergence.detail

    def test_the_divergence_is_a_finding_with_remediation(self) -> None:
        record = _sample()
        found = compare(record, _captured(record, _observed("different")))
        (finding,) = found.findings
        assert finding.code == DOC_EXAMPLE_FAILED
        assert finding.location == record.source
        assert record.id in finding.message
        assert finding.remediation.strip()

    def test_expectations_are_an_ordered_subsequence(self) -> None:
        """Output that arrived in the other order is a divergence."""
        record = _sample(
            steps=[
                {
                    "argv": ["s0ma", "check"],
                    "exit_code": 0,
                    "stderr": [],
                    "stdout": [
                        {"match": "contains", "text": "first"},
                        {"match": "contains", "text": "second"},
                    ],
                }
            ]
        )
        assert compare(record, _captured(record, _observed("first\nsecond"))).ok
        backwards = compare(record, _captured(record, _observed("second\nfirst")))
        assert not backwards.ok
        assert backwards.divergence is not None
        assert backwards.divergence.expectation == 1

    def test_two_fragments_may_share_one_line(self) -> None:
        """A structured result is one long line; a line cursor would refuse it."""
        record = _sample(
            steps=[
                {
                    "argv": ["s0ma", "check"],
                    "exit_code": 0,
                    "stderr": [],
                    "stdout": [
                        {"match": "contains", "text": "alpha"},
                        {"match": "contains", "text": "omega"},
                    ],
                }
            ]
        )
        assert compare(record, _captured(record, _observed("alpha then omega"))).ok

    def test_an_absent_expectation_fires_on_the_line_it_found(self) -> None:
        record = _sample(
            steps=[
                {
                    "argv": ["s0ma", "check"],
                    "exit_code": 0,
                    "stderr": [],
                    "stdout": [{"match": "absent", "text": "Traceback"}],
                }
            ]
        )
        found = compare(record, _captured(record, _observed("fine\nTraceback (most recent)")))
        assert not found.ok
        assert found.divergence is not None
        assert found.divergence.line == 2

    def test_an_exit_code_that_moved_is_reported_before_the_output(self) -> None:
        record = _sample()
        found = compare(record, _captured(record, _observed("anything", exit_code=2)))
        assert found.divergence is not None
        assert found.divergence.stream == "exit"
        assert "exited 2" in found.divergence.detail

    def test_a_timeout_is_a_divergence_and_not_a_pass(self) -> None:
        record = _sample()
        ran = _captured(record, _observed("partial", timed_out=True))
        found = compare(record, ran)
        assert not found.ok
        assert found.divergence is not None
        assert "timeout" in found.divergence.detail

    def test_a_replay_with_the_wrong_number_of_steps_is_a_divergence(self) -> None:
        record = _sample()
        found = compare(record, _captured(record))
        assert not found.ok
        assert found.divergence is not None
        assert "1 step(s)" in found.divergence.detail

    def test_a_structured_field_that_moved_is_reported(self) -> None:
        record = _sample(
            channel=CHANNEL_MCP,
            steps=[
                {
                    "arguments": {"project_root": "{project}"},
                    "fields": [{"equals": "dev", "path": "mode"}],
                    "text": [],
                    "tool": "project_status",
                }
            ],
        )
        item = _observed(streams=(("text", ""),), exit_code=None, structured={"mode": "release"})
        found = compare(record, _captured(record, item))
        assert not found.ok
        assert found.divergence is not None
        assert found.divergence.stream == "fields"
        assert "'release'" in found.divergence.detail

    def test_a_structured_field_that_is_gone_is_reported(self) -> None:
        record = _sample(
            channel=CHANNEL_MCP,
            steps=[
                {
                    "arguments": {},
                    "fields": [{"equals": "x", "path": "build.status"}],
                    "text": [],
                    "tool": "project_status",
                }
            ],
        )
        item = _observed(streams=(("text", ""),), exit_code=None, structured={"build": {}})
        found = compare(record, _captured(record, item))
        assert found.divergence is not None
        assert "no build.status" in found.divergence.detail

    def test_a_field_path_walks_lists_by_position(self) -> None:
        record = _sample(
            channel=CHANNEL_MCP,
            steps=[
                {
                    "arguments": {},
                    "fields": [{"equals": "core_domain", "path": "modules.1.name"}],
                    "text": [],
                    "tool": "project_status",
                }
            ],
        )
        item = _observed(
            streams=(("text", ""),),
            exit_code=None,
            structured={"modules": [{"name": "app_map"}, {"name": "core_domain"}]},
        )
        assert compare(record, _captured(record, item)).ok


# ---------------------------------------------------------------------------
# The committed fixtures, replayed for real (T4)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def library() -> EvidenceLibrary:
    """This repository's evidence, read once."""
    return EvidenceLibrary.load(REPO_ROOT)


@pytest.fixture(scope="module")
def replays(library: EvidenceLibrary) -> dict[str, tuple[Replay, Replay]]:
    """Two replays of every fixture, run once for the whole module.

    Two because determinism is the property under test and one replay
    cannot show it; once because a replay scaffolds a project and runs a
    toolchain, and a per-test fixture would do that a dozen times.
    """
    return {
        record.id: (replay(record), replay(record))
        for record in sorted(library.records, key=lambda held: held.id)
    }


@requires_server
class TestTheCommittedFixtures:
    """The three paths E1 wrote, walked by a machine rather than asserted."""

    def test_exactly_the_expected_fixtures_are_committed(
        self, library: EvidenceLibrary
    ) -> None:
        found = tuple(
            (record.id, record.channel, record.journey)
            for record in sorted(library.records, key=lambda held: held.id)
        )
        assert found == EXPECTED_FIXTURES

    def test_both_channels_are_exercised(self, library: EvidenceLibrary) -> None:
        """Anti-vacuity: a format with one channel proved is one channel proved."""
        assert {record.channel for record in library.records} == set(CHANNELS)

    @pytest.mark.parametrize("identifier", [name for name, _, _ in EXPECTED_FIXTURES])
    def test_the_fixture_still_describes_the_product(
        self,
        identifier: str,
        library: EvidenceLibrary,
        replays: dict[str, tuple[Replay, Replay]],
    ) -> None:
        record = library.by_id(identifier)
        found = compare(record, replays[identifier][0])
        assert found.ok, [item.rendered() for item in found.findings]

    @pytest.mark.parametrize("identifier", [name for name, _, _ in EXPECTED_FIXTURES])
    def test_two_replays_are_byte_equal(
        self, identifier: str, replays: dict[str, tuple[Replay, Replay]]
    ) -> None:
        """The determinism gate: two runs, two temporary directories, one text."""
        first, second = replays[identifier]
        assert first.transcript == second.transcript
        assert first.transcript.endswith("\n")
        assert "\r" not in first.transcript

    @pytest.mark.parametrize("identifier", [name for name, _, _ in EXPECTED_FIXTURES])
    def test_no_machine_path_survives_normalization(
        self, identifier: str, replays: dict[str, tuple[Replay, Replay]]
    ) -> None:
        """What the placeholders are for, checked against the real transcript."""
        text = replays[identifier][0].transcript
        assert str(REPO_ROOT) not in text
        assert "/var/folders/" not in text
        assert "s0ma-evidence-" not in text

    def test_a_stale_expectation_fails_with_the_divergence_located(
        self, library: EvidenceLibrary, replays: dict[str, tuple[Replay, Replay]]
    ) -> None:
        """The acceptance clause, against a real transcript rather than a stub.

        One expectation of the real first-project fixture is edited to
        say what the product no longer says, and the same captured replay
        is compared again — so the failure is the fixture's, not a
        different run's.
        """
        record = library.by_id("example:transcript/first-project")
        step = record.steps[0]
        assert isinstance(step, CommandStep)
        stale = CommandStep(
            argv=step.argv,
            exit_code=step.exit_code,
            stdout=(Expectation(match="line", text="7 file(s) checked. No errors."),),
            stderr=step.stderr,
        )
        mutated = EvidenceRecord(
            id=record.id,
            journey=record.journey,
            channel=record.channel,
            intent=record.intent,
            scaffold=record.scaffold,
            steps=(stale, *record.steps[1:]),
            covers=record.covers,
            not_covered=record.not_covered,
            source=record.source,
        )
        found = compare(mutated, replays[record.id][0])
        assert not found.ok
        assert found.divergence is not None
        assert found.divergence.step == 0
        assert "7 file(s) checked" in found.divergence.detail
        assert "3 file(s) checked" in found.divergence.detail or "the search had reached" in (
            found.divergence.detail
        )
        (finding,) = found.findings
        assert finding.code == DOC_EXAMPLE_FAILED

    def test_a_replay_writes_nothing_into_the_checkout(
        self, library: EvidenceLibrary
    ) -> None:
        """Every byte a fixture writes goes into the directory it made."""
        before = {path.name for path in REPO_ROOT.joinpath("docs").iterdir()}
        verify(library.by_id("example:transcript/studi0-viewing"))
        assert {path.name for path in REPO_ROOT.joinpath("docs").iterdir()} == before


# ---------------------------------------------------------------------------
# The T3 split
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def composed() -> Any:
    """This repository's documentation, composed once."""
    return build_documentation(REPO_ROOT)


@requires_server
class TestTheSplit:
    """Resolution in the build, execution in the suite, pinned equal."""

    def test_the_build_resolves_every_journeys_evidence(self, composed: Any) -> None:
        library = EvidenceLibrary.load(REPO_ROOT)
        resolve = library.resolver()
        for journey in composed.bundle.journeys:
            declared = tuple(item.id for item in journey.evidence)
            assert declared, f"{journey.id} names no evidence"
            assert set(declared) <= set(resolve(journey.id)), journey.id

    def test_the_resolved_set_is_the_executed_set(
        self, library: EvidenceLibrary, replays: dict[str, tuple[Replay, Replay]]
    ) -> None:
        """The seam the split rests on.

        The build resolves; the suite runs. If a fixture could be
        resolved and never run, ``DOC_JOURNEY_UNTESTED`` would be green
        for a path nothing has walked — which is the exact failure the
        gate exists against. This is what stops that: the two sets are
        the same set.
        """
        resolved = set(library.ids())
        executed = set(
            passing(
                compare(library.by_id(identifier), ran[0])
                for identifier, ran in sorted(replays.items())
            )
        )
        assert resolved == executed

    def test_the_composed_build_reports_nothing(self, composed: Any) -> None:
        assert [item.rendered() for item in composed.findings] == []

    def test_the_untested_gate_is_armed_in_the_real_build(self) -> None:
        """A journey whose evidence this tree does not hold is red.

        Composed with an empty library rather than with a hand-built
        bundle, because the claim is about the *application*: the arming
        is unconditional there, so the only thing standing between this
        repository and three ``DOC_JOURNEY_UNTESTED`` findings is that
        the fixtures are committed.
        """
        stranded = build_documentation(REPO_ROOT, evidence=EvidenceLibrary(records=()))
        untested = [
            item for item in stranded.findings if item.code == DOC_JOURNEY_UNTESTED
        ]
        assert len(untested) == EXPECTED_JOURNEY_COUNT
        assert all("has no passing run of it" in item.message for item in untested)

    def test_the_build_runs_no_subprocess_for_evidence(self) -> None:
        """SDA-INV-8, as a property of the source rather than of a promise.

        The resolver reads files. The two imports that start something —
        the subprocess runner and the authoring server — are written
        inside the functions that replay, so importing this module for a
        build pulls neither of them in.
        """
        import ast

        source = (
            REPO_ROOT
            / "packages"
            / "s0ma-dsl"
            / "src"
            / "s0ma_dsl"
            / "docs_model"
            / "evidence.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        top: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top.append(node.module)
        assert not [name for name in top if name.startswith(("s0ma.", "s0ma_mcp"))], top
        assert "subprocess" not in top


# ---------------------------------------------------------------------------
# The honesty ledger
# ---------------------------------------------------------------------------


class TestTheLedger:
    """Every step of an evidenced journey is covered or explained."""

    def test_every_step_of_every_journey_is_accounted_for(self, composed: Any) -> None:
        library = EvidenceLibrary.load(REPO_ROOT)
        for journey in composed.bundle.journeys:
            steps = {normalize_id(step.surface) for step in journey.steps}
            for record in library.for_journey(journey.id):
                accounted = {normalize_id(name) for name in record.covers} | {
                    normalize_id(name) for name, _ in record.not_covered
                }
                assert accounted == steps, record.id

    def test_something_is_actually_covered(self, composed: Any) -> None:
        """Anti-vacuity: a ledger that explains everything away proves nothing."""
        library = EvidenceLibrary.load(REPO_ROOT)
        assert sum(len(record.covers) for record in library.records) >= 6

    def test_every_uncovered_step_says_why(self, library: EvidenceLibrary) -> None:
        for record in library.records:
            for surface, reason in record.not_covered:
                assert len(reason) > 60, f"{record.id} dismisses {surface} in a phrase"

    def test_a_ledger_naming_a_step_the_journey_never_takes_is_reported(
        self, composed: Any
    ) -> None:
        record = EvidenceLibrary.load(REPO_ROOT).by_id("example:transcript/studi0-viewing")
        stray = EvidenceRecord(
            id=record.id,
            journey=record.journey,
            channel=record.channel,
            intent=record.intent,
            scaffold=record.scaffold,
            steps=record.steps,
            covers=("cli:s0ma/doctor", *record.covers),
            not_covered=record.not_covered,
            source=record.source,
        )
        findings = EvidenceLibrary(records=(stray,)).findings(composed.bundle)
        codes = [item.code for item in findings]
        assert DOC_JOURNEY_UNRESOLVED in codes
        assert any("cli:s0ma/doctor" in item.message for item in findings)

    def test_a_fixture_no_journey_claims_is_a_vacuous_gate(self, composed: Any) -> None:
        orphan = _sample(journey="journey:first-project", covers=[], not_covered=[])
        findings = EvidenceLibrary(records=(orphan,)).findings(composed.bundle)
        assert DOC_GATE_VACUOUS in [item.code for item in findings]

    def test_a_fixture_for_a_journey_nobody_wrote_is_unresolved(
        self, composed: Any
    ) -> None:
        stranded = _sample(journey="journey:nobody-wrote-this")
        findings = EvidenceLibrary(records=(stranded,)).findings(composed.bundle)
        assert DOC_JOURNEY_UNRESOLVED in [item.code for item in findings]

    def test_a_citation_pointing_at_the_wrong_file_is_unresolved(
        self, composed: Any
    ) -> None:
        """``ExampleRef`` carries a source so it can be checked; this checks it."""
        record = EvidenceLibrary.load(REPO_ROOT).by_id("example:transcript/first-project")
        moved = EvidenceRecord(
            id=record.id,
            journey=record.journey,
            channel=record.channel,
            intent=record.intent,
            scaffold=record.scaffold,
            steps=record.steps,
            covers=record.covers,
            not_covered=record.not_covered,
            source="docs/s0ma_src/evidence/somewhere-else.json",
        )
        findings = EvidenceLibrary(records=(moved,)).findings(composed.bundle)
        assert any(
            item.code == DOC_JOURNEY_UNRESOLVED and "written in" in item.message
            for item in findings
        )

    def test_a_composition_without_journeys_reports_nothing_about_evidence(self) -> None:
        """A claim about these readings, asserted over somebody else's.

        The same rule the application states for its floors and its
        allowances: a build that never read the journeys has not
        disproved anything about this library.
        """
        from s0ma_dsl.docs_model.records import SCHEMA, BuildStamp, DocsBundle

        empty = DocsBundle(
            stamp=BuildStamp(schema=SCHEMA, release_version="0.0.0", snapshot_hash=""),
            authorities=(),
            concepts=(),
            surfaces=(),
            journeys=(),
            sequences=(),
            documents=(),
        )
        assert EvidenceLibrary.load(REPO_ROOT).findings(empty) == ()


# ---------------------------------------------------------------------------
# Voice and source discipline
# ---------------------------------------------------------------------------


class TestSourceDiscipline:
    """A fixture is an authored file and is held to the authored rules."""

    def test_every_committed_fixture_is_in_the_products_voice(
        self, library: EvidenceLibrary
    ) -> None:
        for record in library.records:
            assert check_evidence_voice(record) == []

    def test_the_voice_rule_really_reaches_a_fixture(self) -> None:
        """Anti-vacuity: the rule above passes because the prose is clean."""
        loud = _sample(intent="The payload is written back for review.")
        (finding,) = check_evidence_voice(loud)
        assert finding.code == DOC_VOICE_VIOLATION

    def test_every_fixture_file_is_canonical_json(self) -> None:
        """Sorted keys, two-space indent, one trailing line feed.

        The form E3 to E7 will write four more of these in. Pinned rather
        than hoped for: a hand-edited fixture that reorders its keys makes
        a diff nobody can review, and this is what keeps the file a
        reviewable artifact.
        """
        for path in sorted((REPO_ROOT / EVIDENCE_DIR).glob("*.json")):
            raw = path.read_bytes()
            assert b"\r\n" not in raw
            text = raw.decode("utf-8")
            canonical = (
                json.dumps(json.loads(text), sort_keys=True, indent=2, ensure_ascii=False)
                + "\n"
            )
            assert text == canonical, path.name

    def test_the_module_is_utf8_with_line_feeds(self) -> None:
        raw = (
            REPO_ROOT
            / "packages"
            / "s0ma-dsl"
            / "src"
            / "s0ma_dsl"
            / "docs_model"
            / "evidence.py"
        ).read_bytes()
        raw.decode("utf-8")
        assert b"\r\n" not in raw

    def test_the_fixtures_live_where_the_module_says(self) -> None:
        assert EVIDENCE_DIR == "docs/s0ma_src/evidence"
        assert (REPO_ROOT / EVIDENCE_DIR).is_dir()


# ---------------------------------------------------------------------------
# What this milestone does not do
# ---------------------------------------------------------------------------


class TestTheCallStepShape:
    """The MCP half of the format, read without a server."""

    def test_a_call_carries_its_arguments_sorted(self, tmp_path: Path) -> None:
        document = _valid()
        document["record"]["channel"] = CHANNEL_MCP
        document["record"]["steps"] = [
            {
                "arguments": {"project_root": "{project}", "mode": "dev"},
                "fields": [{"equals": True, "path": "ok"}],
                "text": [{"match": "contains", "text": "\"exit_code\": 0"}],
                "tool": "check",
            }
        ]
        (record,) = _written(tmp_path, document).records
        step = record.steps[0]
        assert isinstance(step, CallStep)
        assert step.arguments == (("mode", "dev"), ("project_root", "{project}"))
        assert step.fields == (FieldExpectation(path="ok", equals=True),)

    def test_an_argument_may_not_name_an_unknown_placeholder(
        self, tmp_path: Path
    ) -> None:
        document = _valid()
        document["record"]["channel"] = CHANNEL_MCP
        document["record"]["steps"] = [
            {
                "arguments": {"project_root": "{root}"},
                "fields": [],
                "text": [],
                "tool": "check",
            }
        ]
        assert "{root}" in _refused(tmp_path, document)
