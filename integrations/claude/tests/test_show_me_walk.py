"""The start skill's "show me" walk, held to its decided words and to s0ma.

The walk says five sentences word for word. Their gaps are filled from what
``s0ma new project --sample --step N --format json`` prints, so the skill
itself holds none of the sample's own words: a new sample, or new words for
this one, needs no edit here or in the skill.

Unlike ``test_skills.py``, this suite lays the sample down once, in a
temporary folder, through the CLI in this process, so the filled sentences are
checked against the JSON a person's walk would read. It makes no subprocess
call and runs no model.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.cli.templates import FIRST_RUN_SAMPLE, Archetype, get_archetype

#: ``integrations/``, from ``integrations/claude/tests/test_show_me_walk.py``.
INTEGRATIONS = Path(__file__).resolve().parents[2]
START_SKILL = INTEGRATIONS / "claude" / "plugin" / "skills" / "start" / "SKILL.md"
MCP_SURFACE = (
    INTEGRATIONS.parent / "packages" / "s0ma-mcp" / "tests" / "snapshots" / "mcp_surface.json"
)

#: The walk's five decided sentences, with their gaps in braces.
WHAT_S0MA_IS = (
    "s0ma does two things. It keeps what you want from your software, its "
    "intent, requirements, and guidelines, inside the code itself, next to the "
    "part each one belongs to. And it makes that available to AI models like "
    "me, so I work from a live, accurate picture of your system instead of "
    "guessing."
)
BEFORE_THE_FIRST_STEP = (
    "I'll build {called} one step at a time so you can watch. studi0 is open "
    "beside the chat. It's empty for now, and each step will appear there as I "
    "build it."
)
AFTER_A_STEP = '{line} Say "next" to go on, or "finish" and I\'ll build the rest.'
AFTER_THE_LAST_STEP = (
    "That's the whole {noun}: {M} steps, {N} parts, all checks pass. Now the "
    'part s0ma is for. Ask me anything about it, for example "{example_question}" '
    "I'll answer from the {noun}'s own model, not by guessing from its code."
)
THE_CLOSE = (
    "Tell me what to change, or ask how any part works. Or tell me what you "
    'want to build. Two things you can say any time: "always use s0ma" and '
    '"always show studi0".'
)
DECIDED = (
    WHAT_S0MA_IS,
    BEFORE_THE_FIRST_STEP,
    AFTER_A_STEP,
    AFTER_THE_LAST_STEP,
    THE_CLOSE,
)

#: The two sentences filled from the agent sample, as the owner decided them.
FILLED_BEFORE = "I'll build a small agent one step at a time so you can watch."
FILLED_AFTER = (
    "That's the whole agent: 5 steps, 16 parts, all checks pass. Now the part "
    "s0ma is for. Ask me anything about it, for example \"what is this agent "
    "never allowed to do?\" I'll answer from the agent's own model, not by "
    "guessing from its code."
)

#: Where the walk's own section starts in the skill.
WALK_HEADING = "## Show me, one step at a time"

#: An inline code span, which is how a command is named in prose.
INLINE_CODE = re.compile(r"`([^`\n]+)`")

#: What each placeholder in a walk command stands for when it is parsed.
PLACEHOLDERS = {"<folder>": "support", "<n>": "1", "<module>": "rules"}


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _fill(sentence: str, report: dict[str, Any], line: str | None = None) -> str:
    return (
        sentence.replace("{called}", report["called"])
        .replace("{noun}", report["noun"])
        .replace("{M}", str(report["step"]["of"]))
        .replace("{N}", str(report["parts"]))
        .replace("{example_question}", report["example_question"])
        .replace("{line}", line if line is not None else report["line"])
    )


def _json_of(argv: list[str]) -> dict[str, Any]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = S0maCLI().run([*argv, "--format", "json"])
    report: dict[str, Any] = json.loads(out.getvalue())
    assert code == EXIT_SUCCESS, report
    assert report["ok"] is True, report
    return report


@pytest.fixture(scope="module")
def skill() -> str:
    return START_SKILL.read_bytes().decode("utf-8")


@pytest.fixture(scope="module")
def walk(skill: str) -> str:
    """The walk's own section, from its heading to the end of the skill."""
    assert WALK_HEADING in skill, f"the start skill has no {WALK_HEADING!r}"
    return skill[skill.index(WALK_HEADING):]


@pytest.fixture(scope="module")
def sample() -> Archetype:
    return get_archetype(FIRST_RUN_SAMPLE)


@pytest.fixture(scope="module")
def reports(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """The JSON of step 0 and of the last step, from a real walk."""
    folder = tmp_path_factory.mktemp("walk") / "sample"
    first = _json_of(["new", "project", str(folder), "--sample", "--step", "0"])
    root = first["project_root"]
    last = _json_of(
        ["new", "project", root, "--sample", "--step", str(first["step"]["of"])]
    )
    return {"first": first, "last": last}


class TestTheDecidedWords:
    @pytest.mark.parametrize("sentence", DECIDED)
    def test_every_sentence_is_in_the_skill_word_for_word(
        self, sentence: str, walk: str
    ) -> None:
        assert sentence in _one_line(walk), sentence

    def test_the_terminal_says_where_studi0_is_running(self, walk: str) -> None:
        text = _one_line(walk)
        assert 'the middle sentence is "studi0 is running at <address>."' in text

    def test_the_agent_sample_fills_them_as_decided(
        self, reports: dict[str, dict[str, Any]]
    ) -> None:
        first, last = reports["first"], reports["last"]
        assert _fill(BEFORE_THE_FIRST_STEP, first).startswith(FILLED_BEFORE)
        assert last["finished"] is True
        assert _fill(AFTER_THE_LAST_STEP, last) == FILLED_AFTER

    def test_after_a_step_starts_with_what_s0ma_printed(
        self, reports: dict[str, dict[str, Any]]
    ) -> None:
        last = reports["last"]
        said = _fill(AFTER_A_STEP, last)
        assert said.startswith(last["line"] + " Say ")

    def test_both_reports_say_the_same_sample(
        self, reports: dict[str, dict[str, Any]]
    ) -> None:
        first, last = reports["first"], reports["last"]
        for key in ("called", "noun", "example_question", "project_root"):
            assert first[key] == last[key], key
        assert first["step"]["of"] == last["step"]["number"]


class TestTheSkillHoldsNoneOfTheSamplesWords:
    def test_none_of_what_the_sample_says_about_itself(
        self, skill: str, sample: Archetype
    ) -> None:
        text = _one_line(skill).lower()
        words = [
            sample.name,
            sample.default_project_name,
            sample.called,
            sample.noun,
            sample.example_question,
        ]
        for step in sample.steps:
            words += [step.name, step.intent]
        assert all(words), "the sample left a field empty"
        for word in words:
            found = re.search(rf"(?<![\w-]){re.escape(word.lower())}(?![\w-])", text)
            assert found is None, f"the start skill holds the sample's own {word!r}"

    def test_no_count_of_steps_or_parts(
        self, skill: str, reports: dict[str, dict[str, Any]]
    ) -> None:
        last = reports["last"]
        text = _one_line(skill)
        assert f"{last['step']['of']} steps" not in text
        assert f"of {last['step']['of']}" not in text
        assert f"{last['parts']} parts" not in text
        assert f"{last['modules']} modules" not in text

    def test_no_template_name_and_no_folder_for_the_sample(
        self, skill: str, sample: Archetype
    ) -> None:
        assert "tip-calculator" not in skill
        assert "--template pipeline" not in skill
        assert f"--template {sample.name}" not in skill
        assert sample.default_project_name not in skill


def _walk_commands(walk: str) -> list[list[str]]:
    """The words of every ``s0ma`` command the walk names."""
    found: list[list[str]] = []
    in_fence = False
    for line in walk.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        for candidate in [line.strip()] if in_fence else INLINE_CODE.findall(line):
            words = candidate.split()
            if len(words) > 1 and words[0] == "s0ma":
                found.append(words)
    return found


class TestTheWalksCommands:
    def test_the_walk_names_each_command_it_runs(self, walk: str) -> None:
        named = {" ".join(words) for words in _walk_commands(walk)}
        assert {
            "s0ma new project --sample --step 0 --format json",
            "s0ma new project <folder> --sample --step <n> --format json",
            "s0ma check",
            "s0ma build .",
            "s0ma inspect --all",
            "s0ma inspect <module> --format json",
        } <= named, sorted(named)

    def test_every_command_parses(self, walk: str) -> None:
        parser = S0maCLI().build_parser()
        commands = _walk_commands(walk)
        assert commands
        for words in commands:
            argv = [PLACEHOLDERS.get(word, word) for word in words[1:]]
            assert not any(w.startswith("<") for w in argv), words
            try:
                parsed = parser.parse_args(argv)
            except SystemExit as exc:  # argparse refuses by exiting
                raise AssertionError(f"`{' '.join(words)}` does not parse") from exc
            assert isinstance(parsed, argparse.Namespace)

    def test_the_tools_it_names_are_served(self, walk: str) -> None:
        served = {
            tool["name"]
            for tool in json.loads(MCP_SURFACE.read_text(encoding="utf-8"))["tools"]
        }
        for tool in ("project_status", "inspect_module"):
            assert f"`{tool}`" in walk, f"the walk never names `{tool}`"
            assert tool in served, f"the server serves no tool called {tool}"

    def test_it_answers_from_the_model_and_not_the_code(self, walk: str) -> None:
        text = _one_line(walk)
        assert "Answer from the project's own model." in text
        assert "Do not read the `.s0ma` sources, the `build/` folder or `bootstrap/` to answer" in text

    def test_it_waits_for_the_person_between_steps(self, walk: str) -> None:
        text = _one_line(walk)
        assert "Then stop and wait for the person." in text
        for said in ('"next"', '"go on"', '"continue"', '"finish"', '"build the rest"', '"all of it"'):
            assert said in text, said

    def test_a_failure_stops_the_walk(self, walk: str) -> None:
        text = _one_line(walk)
        assert "say plainly what it printed and stop the walk there" in text
        assert '`"ok": false`' in text
