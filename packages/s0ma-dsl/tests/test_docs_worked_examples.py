"""Worked examples from the read surface: ``s0ma docs show example:...``.

A journey lists the worked examples that walk it. These tests hold the
three things a reader needs from that list: each example opens with
``s0ma docs show``, the journey says so on its own page, and a page shown
from an installed wheel points at something the reader can open.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli import docs_commands
from s0ma_dsl.cli.docs_commands import (
    REPOSITORY_URL,
    evidence_places,
    listed_examples,
    load_example,
    read_more,
    read_more_targets,
    render_terminal,
    topic_index,
)
from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.docs_model.bundle import CHECKOUT, INSTALLED, Snapshot, load_snapshot
from s0ma_dsl.docs_model.evidence import EVIDENCE_DIR, CommandStep
from s0ma_dsl.docs_model.render_human import render_human

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.resolve import TopicIndex

REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = REPO_ROOT / "docs" / "s0ma_src" / "evidence"
FIRST = "example:transcript/first-project"


@pytest.fixture(scope="module")
def snapshot() -> Snapshot:
    return load_snapshot(REPO_ROOT)


@pytest.fixture(scope="module")
def installed(snapshot: Snapshot) -> Snapshot:
    """The checkout's bundle, as an installed wheel would present it."""
    return replace(snapshot, origin=INSTALLED, location="installed")


@pytest.fixture(scope="module")
def index(snapshot: Snapshot) -> TopicIndex:
    return topic_index(snapshot)


def _run(argv: list[str]) -> int:
    return S0maCLI().run(argv)


class TestShowAnExample:
    def test_every_listed_example_opens_with_its_commands(
        self, snapshot: Snapshot, capsys: pytest.CaptureFixture[str]
    ) -> None:
        listed = listed_examples(snapshot)
        assert len(listed) >= 9
        for identifier in listed:
            capsys.readouterr()
            assert _run(["docs", "show", identifier]) == 0, identifier
            out = capsys.readouterr().out
            assert out.splitlines()[0].startswith("s0ma ")
            assert f"# {identifier}" in out
            record = load_example(identifier, evidence_places(snapshot))
            assert record is not None
            for step in record.steps:
                if isinstance(step, CommandStep):
                    typed = " ".join(
                        part if " " not in part else f'"{part}"' for part in step.argv
                    )
                    assert f"Run `{typed}`" in out, (identifier, typed)
            assert out.rstrip().endswith(f"s0ma docs show {record.journey}")

    def test_json_carries_the_same_steps(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["docs", "show", FIRST, "--format", "json"]) == 0
        document = json.loads(capsys.readouterr().out)
        assert document["id"] == FIRST
        assert document["journey"] == "journey:first-project"
        assert document["setup"]["command"] == "s0ma new project demo --name demo"
        kinds = [step["kind"] for step in document["steps"]]
        assert "command" in kinds and "write" in kinds
        assert document["steps"][0]["command"] == "s0ma check"
        assert document["steps"][0]["exit_code"] == 0

    def test_an_mcp_example_shows_the_tool_and_its_arguments(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["docs", "show", "example:transcript/mcp-authoring-loop"]) == 0
        out = capsys.readouterr().out
        assert "Call the `project_status` tool" in out
        assert 'Arguments: {"project_root": "{project}"}' in out
        assert "- `{project}`: the project folder you work in" in out

    def test_an_example_no_journey_lists_still_misses(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(["docs", "show", "example:transcript/nope"]) == 1
        assert "names no topic this build addresses" in capsys.readouterr().err

    def test_a_listed_example_with_no_transcript_says_so(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(
            docs_commands, "evidence_places", lambda _snapshot: ((tmp_path, "none"),)
        )
        assert _run(["docs", "show", FIRST]) == 1
        err = capsys.readouterr().err
        assert "is a worked example for journey:first-project" in err
        assert "does not carry its transcript" in err


class TestWhereAnExampleIsRead:
    def test_a_checkout_reads_its_own_folder_first(self, snapshot: Snapshot) -> None:
        places = evidence_places(snapshot)
        assert snapshot.origin == CHECKOUT
        assert places[0] == (REPO_ROOT, EVIDENCE_DIR)
        assert places[-1] == (
            docs_commands.packaged_evidence_root(),
            docs_commands.PACKAGED_EVIDENCE,
        )

    def test_an_installed_snapshot_reads_only_the_packaged_copy(
        self, installed: Snapshot
    ) -> None:
        assert evidence_places(installed) == (
            (docs_commands.packaged_evidence_root(), docs_commands.PACKAGED_EVIDENCE),
        )

    def test_the_first_place_that_has_it_answers(self, tmp_path: Path) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        (first / "evidence").mkdir(parents=True)
        (second / "evidence").mkdir(parents=True)
        shutil.copy(EVIDENCE / "first-project.json", second / "evidence")
        found = load_example(FIRST, ((first, "evidence"), (second, "evidence")))
        assert found is not None
        assert found.source == "evidence/first-project.json"
        shutil.copy(EVIDENCE / "first-project.json", first / "evidence")
        assert load_example(FIRST, ((first, "evidence"), (second, "evidence"))) == found
        assert load_example(FIRST, ((tmp_path / "missing", "evidence"),)) is None

    def test_outside_a_checkout_the_packaged_copy_answers(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert _run(["docs", "show", FIRST]) == 0
        out = capsys.readouterr().out
        assert "(installed)" in out.splitlines()[0]
        assert "Run `s0ma check`" in out


class TestJourneyLines:
    def test_each_worked_example_names_the_command_that_opens_it(
        self, index: TopicIndex
    ) -> None:
        for identifier in index.group("journeys"):
            view = index.view(identifier)
            page = render_human(view)
            for example in view.items("example_ids"):
                assert (
                    f"- `{example}`: run `s0ma docs show {example}`" in page
                ), identifier

    def test_only_journeys_take_the_command(self, index: TopicIndex) -> None:
        for group in ("concepts", "surfaces"):
            for identifier in index.group(group):
                view = index.view(identifier)
                assert ": run `s0ma docs show" not in render_human(view), identifier


class TestReadMore:
    def test_a_checkout_keeps_the_repository_path(
        self, snapshot: Snapshot, index: TopicIndex
    ) -> None:
        view = index.view("journey:first-project")
        assert read_more_targets(snapshot, view) == read_more(snapshot, view)
        assert render_terminal(snapshot, view).rstrip().endswith(
            "Read more: docs/getting-started/first-project.md"
        )

    def test_no_journey_from_a_wheel_ends_in_a_repository_path(
        self, installed: Snapshot, index: TopicIndex
    ) -> None:
        for identifier in index.group("journeys"):
            view = index.view(identifier)
            for target in read_more_targets(installed, view):
                assert target.startswith(("s0ma docs show ", f"{REPOSITORY_URL}/")), (
                    identifier,
                    target,
                )
        view = index.view("journey:first-project")
        assert render_terminal(installed, view).rstrip().endswith(
            "Read more: s0ma docs show doc:guide/first-project"
        )

    def test_a_document_from_a_wheel_points_at_its_public_address(
        self, installed: Snapshot, index: TopicIndex
    ) -> None:
        view = index.view("doc:guide/first-project")
        assert read_more_targets(installed, view) == (
            f"{REPOSITORY_URL}/blob/v{installed.release_version()}/"
            f"docs/getting-started/first-project.md",
        )
