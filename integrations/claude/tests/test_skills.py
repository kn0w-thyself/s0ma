"""The six skills the s0ma plugin ships, held to what a skill has to be.

A skill is a file a model reads in full every time it is invoked, so the
things that can go wrong with one are not the things that go wrong with
code. Four of them are worth a gate, and this file is those four:

* **It has to be loadable.** Front matter present, the fields Claude Code
  reads and nothing else, and a ``name`` that matches the directory - the
  invocation name comes from the front matter, so a mismatch renames the
  skill and silently breaks every ``/s0ma:<name>`` a document promises.
* **It must never handle a secret.** A license key belongs in the plugin's
  configuration screen or in ``s0ma-launch activate``'s hidden prompt, and
  nowhere else. A skill that asks for one in the conversation puts it in a
  transcript for ever. Both halves are checked: no key-shaped string in the
  text, and no sentence that asks anybody for one.
* **Every command it names must exist.** A skill that tells a model to run
  a command nobody wrote wastes a turn and teaches the model to invent
  more. The launcher's command line and the ``s0ma`` CLI's are both read
  live - from the parser, not from a list kept beside it.
* **What does not exist yet must be marked.** Plan 1 is building the
  retrofit ladder; its commands are named here in their frozen form and
  each carries a ``TODO(plan-1)`` marker. The count is asserted, so
  removing them when plan 1 lands is a deliberate, visible edit rather
  than something anybody can forget.

The suite is offline, reads only this checkout, and makes no subprocess
call, so it behaves the same on Windows as it does here.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Where things are
# ---------------------------------------------------------------------------

#: ``integrations/``, from ``integrations/claude/tests/test_skills.py``.
INTEGRATIONS = Path(__file__).resolve().parents[2]

SKILLS_DIR = INTEGRATIONS / "claude" / "plugin" / "skills"
LAUNCHER_PATH = INTEGRATIONS / "launcher" / "s0ma_launch.py"

#: The six skills the plugin ships, and the whole set: a seventh directory
#: that nobody added to this tuple is a skill no gate has ever read.
SKILL_NAMES: tuple[str, ...] = (
    "doctor",
    "feedback",
    "new",
    "retrofit",
    "setup",
    "update",
)

#: Claude Code reads ``name`` and ``description``; ``allowed-tools`` is
#: documented for skills but is deliberately not used here - these skills
#: work by running commands in a terminal and by reading what a person
#: points them at, and a tool list is a way to break that later without
#: noticing. Exactly these two keys, so an invented field is caught.
FRONT_MATTER_KEYS: frozenset[str] = frozenset({"name", "description"})

#: The plugin's own limit on a description, which is what Claude shows when
#: it is deciding whether to invoke the skill at all.
MAX_DESCRIPTION = 200

#: Skills whose description is not this plugin's to word. ``feedback``
#: carries the one ``s0ma new project`` scaffolds, so that a project skill
#: and the plugin skill introduce themselves identically; rewording it here
#: would be a second divergence, and only the invocation name is meant to
#: differ. Every other skill's description has to say when to use it.
DESCRIPTION_WRITTEN_ELSEWHERE: frozenset[str] = frozenset({"feedback"})

#: The marker a line carries when it names something plan 1 has not built.
TODO_MARKER = "TODO(plan-1)"

#: How many marked lines there are, exactly. **Zero, since plan 1 landed.**
#: There were seven: the adoption ladder's six commands (plan 1 section 5.3,
#: frozen) and the guide topic ``s0ma docs show`` is pointed at. All seven
#: now exist, and the markers went in the same edit that set this to zero -
#: which is what asserting it was for. The count stays asserted rather than
#: deleted, so a future marker has to be added deliberately, here, with a
#: reason, instead of quietly accumulating.
EXPECTED_TODO_MARKERS = 0

#: The adoption ladder, exactly as plan 1 section 5.3 froze it. The
#: retrofit skill has to name every one of them, so that a rung cannot be
#: quietly dropped from the running order. This used to be the same set as
#: :data:`PLAN_1_COMMANDS` because none of them existed; they are separate
#: now because they mean different things - this one is "the ladder is
#: written out in full", which stays true for ever, and that one was "the
#: CLI has not caught up yet", which stopped being true.
LADDER_COMMANDS: frozenset[str] = frozenset(
    {
        "adopt scan",
        "adopt init",
        "adopt draft",
        "adopt baseline",
        "adopt verify-parity",
        "adopt status",
    }
)

#: Commands a skill may name that the live CLI does not have yet. Empty
#: since plan 1 landed: every command every skill names now resolves
#: against the parser, so the retrofit skill is held to exactly the
#: standard the other five always were. Adding a name here is how a future
#: plan buys itself the same allowance, and it costs a marker on the line
#: plus an entry in this set - never one without the other.
PLAN_1_COMMANDS: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Reading the skills
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    """One file, decoded from its bytes.

    Bytes rather than :meth:`Path.read_text` on purpose: the byte-identity
    test below means what it says, and universal-newline translation would
    quietly make a CRLF file pass it.
    """
    return path.read_bytes().decode("utf-8")


def skill_path(name: str) -> Path:
    """Where one skill's file is."""
    return SKILLS_DIR / name / "SKILL.md"


def split_front_matter(text: str) -> tuple[str, str]:
    """``(front matter, body)`` for a skill file, or a failure saying why.

    The body is everything after the closing fence, the first character
    included, so that two files with the same body compare equal whatever
    their front matter says.
    """
    parts = text.split("---\n", 2)
    if len(parts) != 3 or parts[0] != "":
        raise AssertionError(
            "a skill starts with a '---' line, then its front matter, then a "
            "second '---' line"
        )
    return parts[1], parts[2]


def parse_front_matter(text: str) -> dict[str, str]:
    """The front matter as fields, refusing anything that is not one line.

    Deliberately not a YAML parser: a skill's front matter is three short
    lines, and a value that needs more than one of them is a sign the
    description has become a document.
    """
    front, _ = split_front_matter(text)
    fields: dict[str, str] = {}
    for line in front.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise AssertionError(f"front-matter line is not `key: value`: {line!r}")
        fields[key.strip()] = value.strip()
    return fields


@pytest.fixture(scope="session")
def skills() -> dict[str, str]:
    """Every skill's text, keyed by its directory name."""
    return {name: _read(skill_path(name)) for name in SKILL_NAMES}


# ---------------------------------------------------------------------------
# Reading the two command lines, live
# ---------------------------------------------------------------------------


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """The sub-commands one parser offers, by name."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


@pytest.fixture(scope="session")
def launcher() -> ModuleType:
    """``s0ma_launch.py``, imported from its path.

    The launcher is one standalone file with no package around it, which
    is the point of it, so it is loaded the way ``uv run --script`` finds
    it. The module name is this suite's own, so nothing here disturbs the
    launcher's own tests if both run in one process.
    """
    spec = importlib.util.spec_from_file_location(
        "s0ma_launch_for_skill_tests", LAUNCHER_PATH
    )
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise RuntimeError(f"could not load the launcher from {LAUNCHER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def launcher_commands(launcher: ModuleType) -> frozenset[str]:
    """Every ``s0ma-launch`` sub-command, read from the parser itself."""
    return frozenset(_subcommands(launcher.build_parser()))


@pytest.fixture(scope="session")
def cli_commands() -> frozenset[str]:
    """Every ``s0ma`` command and sub-command the installed CLI offers.

    Two shapes: ``"doctor"`` for a top-level command, and ``"adopt file"``
    for one that lives under another. Read from the parser rather than
    from ``--help`` text, because the parser is what would actually refuse
    the command a skill tells a model to run.
    """
    main = importlib.import_module("s0ma_dsl.cli.main")
    top = _subcommands(main.S0maCLI().build_parser())
    names = set(top)
    for name, parser in top.items():
        names.update(f"{name} {nested}" for nested in _subcommands(parser))
    return frozenset(names)


# ---------------------------------------------------------------------------
# Finding the commands a skill names
# ---------------------------------------------------------------------------

#: An inline code span, which is how a command is named in prose.
INLINE_CODE = re.compile(r"`([^`\n]+)`")

#: The two programs a skill is allowed to call by bare name, because the
#: plugin's ``bin/`` directory is on the Bash tool's path.
PROGRAMS = ("s0ma-launch", "s0ma")


@dataclass(frozen=True)
class Mention:
    """One command a skill names, and where it says it."""

    line_number: int
    program: str
    command: str
    line: str


def command_mentions(text: str) -> list[Mention]:
    """Every ``s0ma`` or ``s0ma-launch`` command a skill names.

    Both places a command can appear are read: a fenced block, where the
    line is the command, and an inline code span in prose. The whole line
    comes back with the command, so the caller can look for a marker on
    it.
    """
    found: list[Mention] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        candidates = [line] if in_fence else INLINE_CODE.findall(line)
        for candidate in candidates:
            named = _command_of(candidate.strip())
            if named is not None:
                program, command = named
                found.append(Mention(number, program, command, line))
    return found


def _command_of(candidate: str) -> tuple[str, str] | None:
    """``(program, command)`` for a code span, or ``None`` for neither.

    ``s0ma adopt file x.py --description "..."`` is ``("s0ma", "adopt
    file")``; ``s0ma-launch update --check`` is ``("s0ma-launch",
    "update")``. Options and arguments are dropped, and a bare program
    name with nothing after it is not a command anybody has to run.
    """
    words = candidate.split()
    if not words or words[0] not in PROGRAMS:
        return None
    program = words[0]
    plain = [word for word in words[1:] if not word.startswith("-")]
    if not plain:
        return None
    if program == "s0ma-launch":
        return program, plain[0]
    # ``s0ma``: a second word may be a sub-command, which the caller
    # decides by looking both readings up in the parser.
    return program, " ".join(plain[:2])


def _resolved(name: str, known: frozenset[str]) -> str | None:
    """``name``, narrowed to what the parser actually offers.

    ``adopt file`` resolves whole; ``build .`` resolves to ``build``,
    because ``build`` takes no sub-commands and the second word is an
    argument. What comes back is what the parser knows, or ``None`` when
    it knows neither reading.
    """
    if name in known:
        return name
    head = name.split(" ", 1)[0]
    if head in known:
        return head
    return None


# ---------------------------------------------------------------------------
# What a skill must never contain
# ---------------------------------------------------------------------------

#: A license key, in the shape the product issues and the shape the gate
#: greps for. Case-sensitive on purpose: ``S0MA_TOOLCHAIN`` is an
#: environment variable a skill may legitimately name.
KEY_SHAPED = re.compile(r"s0ma_[A-Za-z0-9]{8,}")

#: Any long unbroken run of letters and digits - what a secret looks like
#: when it is not ours. No English word, path or URL fragment in these
#: files comes near it.
SECRET_SHAPED = re.compile(r"[A-Za-z0-9]{24,}")

#: Asking somebody to hand over a secret, in the words people use for it.
ASKS_FOR_A_SECRET = re.compile(
    r"(?:paste|type|enter|share|send|show|give|tell|read out|write out|repeat)"
    r"[^.\n]{0,40}?"
    r"(?:licen[cs]e key|api key|\bkey\b|\bsecret\b|\bcredential\b|\btoken\b)",
    re.IGNORECASE,
)

#: Words that turn such a sentence into the rule rather than the breach.
NEGATIONS = ("never", "not ", "n't", "without", "no need", "nobody", "none of")

#: Sentence ends, near enough for prose written in short sentences.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def sentences_asking_for_a_secret(text: str) -> list[str]:
    """Every sentence that asks anybody for a key, secret or token.

    A sentence that also carries a negation is the prohibition being
    written down, which is the opposite of the defect, so it does not
    count. That exemption is what lets these files say "never paste a
    license key here" out loud.
    """
    offending: list[str] = []
    for sentence in SENTENCE_END.split(text):
        if not ASKS_FOR_A_SECRET.search(sentence):
            continue
        if any(word in sentence.lower() for word in NEGATIONS):
            continue
        offending.append(" ".join(sentence.split()))
    return offending


# ---------------------------------------------------------------------------
# The skills exist and load
# ---------------------------------------------------------------------------


class TestEverySkillLoads:
    """What Claude Code needs before a skill is a skill at all."""

    def test_the_six_are_there_and_no_others(self) -> None:
        on_disk = sorted(
            entry.name for entry in SKILLS_DIR.iterdir() if entry.is_dir()
        )
        assert on_disk == sorted(SKILL_NAMES)
        for name in SKILL_NAMES:
            assert skill_path(name).is_file(), f"{name} has no SKILL.md"

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_the_front_matter_carries_exactly_what_is_read(
        self, name: str, skills: dict[str, str]
    ) -> None:
        fields = parse_front_matter(skills[name])
        assert set(fields) == FRONT_MATTER_KEYS, (
            f"{name}: front matter fields are {sorted(fields)}; Claude Code "
            f"reads {sorted(FRONT_MATTER_KEYS)} and an unknown field is a "
            f"fact nobody acts on"
        )

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_the_name_is_the_directory(
        self, name: str, skills: dict[str, str]
    ) -> None:
        """Otherwise the invocation name is not the one documents promise."""
        assert parse_front_matter(skills[name])["name"] == name

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_the_description_fits_and_says_when_to_use_it(
        self, name: str, skills: dict[str, str]
    ) -> None:
        description = parse_front_matter(skills[name])["description"]
        assert description, f"{name}: the description is empty"
        assert len(description) <= MAX_DESCRIPTION, (
            f"{name}: the description is {len(description)} characters; the "
            f"limit is {MAX_DESCRIPTION}"
        )
        if name in DESCRIPTION_WRITTEN_ELSEWHERE:
            return
        assert "use when" in description.lower(), (
            f"{name}: the description never says when to use the skill, which "
            f"is the half Claude reads to decide whether to invoke it"
        )

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_the_body_is_there_and_is_lf(
        self, name: str, skills: dict[str, str]
    ) -> None:
        _, body = split_front_matter(skills[name])
        assert body.strip(), f"{name}: the skill has no body"
        assert "\r" not in skills[name], f"{name}: carries a carriage return"


# ---------------------------------------------------------------------------
# No skill ever handles a secret
# ---------------------------------------------------------------------------


class TestNoSkillTouchesALicenseKey:
    """The one thing a skill must never do, checked two ways."""

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_no_key_shaped_string(self, name: str, skills: dict[str, str]) -> None:
        assert KEY_SHAPED.findall(skills[name]) == []
        assert SECRET_SHAPED.findall(skills[name]) == []

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_nothing_asks_anybody_for_one(
        self, name: str, skills: dict[str, str]
    ) -> None:
        offending = sentences_asking_for_a_secret(skills[name])
        assert offending == [], (
            f"{name}: asks for a secret in the conversation. The key goes in "
            f"the plugin's configuration screen or through `s0ma-launch "
            f"activate`, and nowhere else: {offending}"
        )

    def test_the_scanners_catch_what_they_are_for(self) -> None:
        """The anti-vacuity half: a clean sweep proves nothing on its own."""
        assert KEY_SHAPED.findall("key: s0ma_notarealkey00000000") != []
        assert SECRET_SHAPED.findall("Bearer abcdefghijklmnopqrstuvwxyz01") != []
        assert sentences_asking_for_a_secret(
            "Ask the user to paste their license key here."
        ) == ["Ask the user to paste their license key here."]
        assert sentences_asking_for_a_secret(
            "Never ask the user to paste their license key here."
        ) == []


# ---------------------------------------------------------------------------
# Every command named exists
# ---------------------------------------------------------------------------


class TestEveryCommandNamedExists:
    """Read from the two parsers, not from a list kept beside them."""

    def test_the_skills_do_name_commands(self, skills: dict[str, str]) -> None:
        """Anti-vacuity: an extractor that finds nothing passes for ever."""
        found = {
            name: [mention.command for mention in command_mentions(text)]
            for name, text in skills.items()
        }
        assert sum(len(commands) for commands in found.values()) >= 20, found
        for name in ("setup", "update", "doctor", "new", "retrofit"):
            assert found[name], f"{name} names no command at all"

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_every_launcher_command_is_in_the_parser(
        self, name: str, skills: dict[str, str], launcher_commands: frozenset[str]
    ) -> None:
        for mention in command_mentions(skills[name]):
            if mention.program != "s0ma-launch":
                continue
            assert mention.command in launcher_commands, (
                f"{name}:{mention.line_number}: `s0ma-launch "
                f"{mention.command}` is not a command. The launcher offers: "
                f"{sorted(launcher_commands)}"
            )

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_every_cli_command_exists_or_is_marked(
        self, name: str, skills: dict[str, str], cli_commands: frozenset[str]
    ) -> None:
        for mention in command_mentions(skills[name]):
            if mention.program != "s0ma":
                continue
            if _resolved(mention.command, cli_commands) is not None:
                continue
            assert TODO_MARKER in mention.line, (
                f"{name}:{mention.line_number}: `s0ma {mention.command}` is "
                f"not in this CLI and the line carries no {TODO_MARKER} "
                f"marker: {mention.line.strip()!r}"
            )
            assert mention.command in PLAN_1_COMMANDS, (
                f"{name}:{mention.line_number}: `s0ma {mention.command}` is "
                f"marked as plan 1 work, but plan 1 section 5.3 froze: "
                f"{sorted(PLAN_1_COMMANDS)}"
            )


# ---------------------------------------------------------------------------
# The plan-1 markers
# ---------------------------------------------------------------------------


class TestThePlanOneMarkers:
    """The markers are a promise to come back, so they are counted."""

    def test_there_are_exactly_the_expected_number(
        self, skills: dict[str, str]
    ) -> None:
        total = sum(text.count(TODO_MARKER) for text in skills.values())
        assert total == EXPECTED_TODO_MARKERS, (
            f"{total} {TODO_MARKER} markers, expected "
            f"{EXPECTED_TODO_MARKERS}. When plan 1 lands, the markers and "
            f"this number go in the same edit."
        )

    def test_every_marker_sits_on_a_line_that_names_something(
        self, skills: dict[str, str]
    ) -> None:
        """A marker with nothing on its line is a reminder about nothing."""
        for name, text in skills.items():
            for number, line in enumerate(text.splitlines(), start=1):
                if TODO_MARKER not in line:
                    continue
                assert INLINE_CODE.search(line), (
                    f"{name}:{number}: a {TODO_MARKER} marker on a line that "
                    f"names no command: {line.strip()!r}"
                )
            assert TODO_MARKER not in text or name == "retrofit", (
                f"{name}: only the retrofit skill waits on plan 1"
            )

    def test_every_ladder_command_is_named(self, skills: dict[str, str]) -> None:
        """The ladder is written out in full, so nothing is quietly dropped."""
        named = {
            mention.command
            for mention in command_mentions(skills["retrofit"])
            if mention.program == "s0ma"
        }
        assert LADDER_COMMANDS <= named, sorted(LADDER_COMMANDS - named)

    def test_the_allowance_is_empty_and_so_is_every_skill(
        self, skills: dict[str, str]
    ) -> None:
        """Both halves of the allowance went, and they went together.

        A marker with no entry would be a reminder the parser test never
        honours; an entry with no marker would be a standing permission
        for a command nobody names. Neither is a state this plugin should
        be able to reach quietly, so both are asserted at once.
        """
        assert PLAN_1_COMMANDS == frozenset(), sorted(PLAN_1_COMMANDS)
        assert not any(TODO_MARKER in text for text in skills.values())


# ---------------------------------------------------------------------------
# The feedback skill is the scaffolded one
# ---------------------------------------------------------------------------


class TestTheFeedbackSkillIsOneText:
    """Two copies of a journey are two journeys within a release."""

    def test_the_body_is_byte_identical_to_what_a_new_project_gets(
        self, skills: dict[str, str]
    ) -> None:
        scaffolded = importlib.import_module("s0ma_dsl.cli.new_project")
        _, expected = split_front_matter(scaffolded._feedback_skill_md())
        _, actual = split_front_matter(skills["feedback"])
        assert actual == expected, (
            "the plugin's feedback skill and the one `s0ma new project` "
            "writes have drifted; scripts/sync_integrations.py is the only "
            "thing that changes either"
        )

    def test_only_the_invocation_name_differs(
        self, skills: dict[str, str]
    ) -> None:
        """Namespacing is why: inside the plugin it is ``/s0ma:feedback``."""
        scaffolded = importlib.import_module("s0ma_dsl.cli.new_project")
        theirs = parse_front_matter(scaffolded._feedback_skill_md())
        ours = parse_front_matter(skills["feedback"])
        assert ours["name"] == "feedback"
        assert theirs["name"] == "s0ma-feedback"
        assert ours["description"] == theirs["description"]


# ---------------------------------------------------------------------------
# House rules the skills are held to
# ---------------------------------------------------------------------------


class TestTheHouseRules:
    """Three rules that are cheap to keep and expensive to notice late."""

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_no_plugin_root_variable_in_a_bash_command(
        self, name: str, skills: dict[str, str]
    ) -> None:
        """``CLAUDE_PLUGIN_ROOT`` is not set in the Bash tool's environment.

        It substitutes in ``.mcp.json`` and in hook commands; a skill that
        used it would hand the model an empty path and a confusing error.
        """
        assert "CLAUDE_PLUGIN_ROOT" not in skills[name]

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_the_word_the_product_does_not_use(
        self, name: str, skills: dict[str, str]
    ) -> None:
        """User-facing s0ma text never says "payload" (owner, 2026-08-27)."""
        assert "payload" not in skills[name].lower()

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_no_version_number_is_named(
        self, name: str, skills: dict[str, str]
    ) -> None:
        """A living document that names a version rots at the next release."""
        stamped = re.findall(r"\b\d+\.\d+\.\d+\b", skills[name])
        assert stamped == [], f"{name}: names version(s) {stamped}"
