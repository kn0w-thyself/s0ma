"""The twelve skills the s0ma plugin ships, held to what a skill has to be.

A skill is a file a model reads in full every time it is invoked, so the
things that can go wrong with one are not the things that go wrong with
code. Four of them are worth a gate, and this file is those four:

* **It has to be loadable.** Front matter present, the fields Claude Code
  reads and nothing else, and a ``name`` that matches the directory - the
  invocation name comes from the front matter, so a mismatch renames the
  skill and silently breaks every ``/s0ma:<name>`` a document promises.
* **It must never handle a secret.** A license key belongs in
  ``s0ma-launch activate``'s hidden prompt, or in the Claude Desktop
  extension's settings screen, and nowhere else. A skill that asks for one in the conversation puts it in a
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

#: The twelve skills the plugin ships, and the whole set: a thirteenth
#: directory that nobody added to this tuple is a skill no gate has ever read.
SKILL_NAMES: tuple[str, ...] = (
    "build",
    "doctor",
    "feedback",
    "new",
    "off",
    "on",
    "preferences",
    "retrofit",
    "setup",
    "start",
    "studi0",
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

    def test_the_twelve_are_there_and_no_others(self) -> None:
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
            f"`s0ma-launch activate` or the Desktop extension's settings, and "
            f"nowhere else: {offending}"
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
        for name in (
            "setup",
            "update",
            "doctor",
            "new",
            "retrofit",
            "off",
            "on",
            "preferences",
            "start",
            "build",
            "studi0",
        ):
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


# ---------------------------------------------------------------------------
# The preferences a person sets by saying so
# ---------------------------------------------------------------------------

#: What a person says, and the sentence Claude answers with, as the owner
#: decided them. Each must be in its skill word for word. Where an answer
#: names the machine, it is written as "this Mac", and the skill says to call
#: it "this PC" on Windows and "this computer" on Linux.
DECIDED_ANSWERS: tuple[tuple[str, str, str], ...] = (
    (
        "preferences",
        "always use s0ma",
        "Done. From now on I'll build new work with s0ma on this Mac without "
        'being asked. Say "only use s0ma when I ask" to change it.',
    ),
    (
        "preferences",
        "only use s0ma when I ask",
        "Done. I'll use s0ma only when you ask. Projects that are already s0ma "
        "keep working as they do now.",
    ),
    (
        "preferences",
        "always show studi0",
        "Done. I'll open studi0 at the first build of each session.",
    ),
    (
        "preferences",
        "only show studi0 when I ask",
        'Done. studi0 stays closed until you say "show me studi0".',
    ),
    (
        "preferences",
        "always use s0ma in this project",
        "Done, for this project only. Everywhere else stays as it was.",
    ),
    (
        "off",
        "turn s0ma off here",
        "s0ma is off in this project. I won't use it here, I won't check your "
        "edits, and studi0 stays closed. Nothing of yours was changed or "
        "removed; I added one small file, `.s0ma/preferences.json`, that says "
        's0ma is off here. Say "turn s0ma back on" or `/s0ma:on` any time. To '
        "switch it off everywhere, disable the s0ma plugin in Claude's plugin "
        "manager.",
    ),
    ("on", "turn s0ma back on", "s0ma is back on in this project."),
    (
        "preferences",
        "what are my s0ma settings?",
        "On this Mac: s0ma only when asked, studi0 offered once per project. In "
        "this project: s0ma is on.",
    ),
)

#: The command each phrase in the machine's half of the table runs.
DECIDED_COMMANDS: tuple[tuple[str, str], ...] = (
    ("always use s0ma", "s0ma-launch set use always"),
    ("only use s0ma when I ask", "s0ma-launch set use asked"),
    ("always show studi0", "s0ma-launch set studi0 always"),
    ("only show studi0 when I ask", "s0ma-launch set studi0 asked"),
)

#: The words that make Claude load each new skill.
TRIGGER_PHRASES: dict[str, tuple[str, ...]] = {
    "off": ("turn s0ma off here", "/s0ma:off"),
    "on": ("turn s0ma back on", "/s0ma:on"),
    "preferences": ("always use s0ma", "only show studi0 when I ask", "settings"),
    "start": ("start with s0ma", "/s0ma:start"),
    "build": ("add to or change a s0ma project", "build something with s0ma"),
    "studi0": ("show me studi0",),
}


def _one_line(text: str) -> str:
    """*text* with its line breaks and runs of spaces folded to single spaces."""
    return " ".join(text.split())


class TestThePreferenceSkills:
    """The decided words, and the commands and values they lean on."""

    @pytest.mark.parametrize(("name", "said", "answer"), DECIDED_ANSWERS)
    def test_every_decided_answer_is_in_its_skill_word_for_word(
        self, name: str, said: str, answer: str, skills: dict[str, str]
    ) -> None:
        text = _one_line(skills[name])
        assert answer in text, f"{name}: the answer to {said!r} is not there as written"
        assert said.rstrip("?").lower() in text.lower(), f"{name}: never names {said!r}"

    @pytest.mark.parametrize(("said", "command"), DECIDED_COMMANDS)
    def test_each_phrase_runs_its_command_on_the_same_row(
        self, said: str, command: str, skills: dict[str, str]
    ) -> None:
        rows = [
            line
            for line in skills["preferences"].splitlines()
            if line.startswith(f'| "{said}" |')
        ]
        assert len(rows) == 1, f"no single table row for {said!r}"
        assert f"`{command}`" in rows[0]

    def test_the_machine_is_named_for_each_platform(self, skills: dict[str, str]) -> None:
        text = _one_line(skills["preferences"])
        assert '"this Mac" on macOS, "this PC" on Windows and "this computer" on Linux' in text

    @pytest.mark.parametrize("name", sorted(TRIGGER_PHRASES))
    def test_the_description_names_what_people_say(
        self, name: str, skills: dict[str, str]
    ) -> None:
        description = parse_front_matter(skills[name])["description"]
        assert len(description) <= 1536
        for phrase in TRIGGER_PHRASES[name]:
            assert phrase in description, f"{name}: the description never says {phrase!r}"

    def test_every_set_command_a_skill_names_takes_that_value(
        self, skills: dict[str, str], launcher: ModuleType
    ) -> None:
        """``set`` is in the parser; its names and values are the launcher's own."""
        found = 0
        for name, text in skills.items():
            for candidate in INLINE_CODE.findall(text) + text.splitlines():
                words = candidate.split()
                if words[:2] != ["s0ma-launch", "set"]:
                    continue
                found += 1
                assert len(words) == 4, f"{name}: {candidate!r} names no value"
                setting, value = words[2], words[3]
                assert setting in launcher.SETTABLE, f"{name}: no setting {setting!r}"
                # ``<auto|notify|off>`` names every value at once.
                values = value.strip("<>").split("|")
                for each in values:
                    assert each in launcher.SETTABLE[setting], (
                        f"{name}: `{candidate}` - {setting} takes "
                        f"{launcher.SETTABLE[setting]}"
                    )
        assert found >= 5, "the skills name fewer set commands than the table holds"

    def test_the_prefs_command_is_in_the_parser_with_its_json_form(
        self, launcher: ModuleType, launcher_commands: frozenset[str]
    ) -> None:
        assert "prefs" in launcher_commands
        prefs = _subcommands(launcher.build_parser())["prefs"]
        assert any("--json" in action.option_strings for action in prefs._actions)

    def test_the_settings_answer_is_what_prefs_prints_first(
        self, launcher: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The decided example is the launcher's own first line on a clean Mac."""
        monkeypatch.setenv("S0MA_HOME", str(tmp_path / "home"))
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        project = tmp_path / "project"
        project.mkdir()
        report = launcher.prefs_report(project=project)
        answer = next(a for _, said, a in DECIDED_ANSWERS if said.startswith("what are"))
        assert launcher.prefs_summary(report, "darwin") == answer
        assert launcher.prefs_summary(report, "win32") == answer.replace("Mac", "PC")
        assert launcher.prefs_summary(report, "linux") == answer.replace("Mac", "computer")

    def test_the_skills_name_the_project_file_and_say_it_is_not_committed(
        self, skills: dict[str, str]
    ) -> None:
        for name in ("off", "on", "preferences"):
            text = _one_line(skills[name])
            assert ".s0ma/preferences.json" in text
            assert "never touch any other file" in text.lower()
        for name in ("off", "preferences"):
            text = _one_line(skills[name])
            assert "If there is no `.s0ma/` folder there, create it." in text
            assert "keep every key already in it" in text
            assert "not meant to be committed" in text

    def test_a_declined_studi0_offer_is_remembered_as_asked(
        self, skills: dict[str, str]
    ) -> None:
        text = _one_line(skills["preferences"])
        assert (
            '**"Just this once"**, **"No thanks"**, or no answer at all: write '
            '`"studi0": "asked"` into the project\'s file, so it is not offered in '
            "this project again."
        ) in text

    def test_yes_always_to_the_studi0_offer_is_set_for_the_machine(
        self, skills: dict[str, str]
    ) -> None:
        text = _one_line(skills["preferences"])
        assert '**"Yes, always"**: run `s0ma-launch set studi0 always`.' in text
        assert (
            "Nothing is written to the project's file for this answer." in text
        )


# ---------------------------------------------------------------------------
# The front door, the build skill and studi0
# ---------------------------------------------------------------------------

#: The sentences the owner decided for the three skills, each in its skill word
#: for word. Where one names the machine it says "this Mac", and the skill says
#: to call it "this PC" on Windows and "this computer" on Linux.
FRONT_DOOR_SENTENCES: tuple[tuple[str, str], ...] = (
    (
        "start",
        "Two things are missing on this Mac: uv, a small tool s0ma uses to manage "
        "its own Python, and s0ma itself. Both go in your home folder, and nothing "
        "in your projects changes. Install them?",
    ),
    (
        "start",
        "One thing is missing on this Mac: s0ma itself. It goes in your home "
        "folder, and nothing in your projects changes. Install it?",
    ),
    ("start", "Installed uv \u00b7 Installing s0ma\u2026 done"),
    (
        "start",
        "s0ma is ready. What do you want to build? One sentence is enough. Or say "
        '"show me" and I\'ll build a small sample so you can watch how it works.',
    ),
    (
        "start",
        "Created tip-calculator in this folder \u00b7 Built 3 modules, 7 parts "
        "\u00b7 All checks pass",
    ),
    (
        "start",
        "It's built, and studi0 is open beside the chat. That's your app as a live "
        "map: every part and how they connect. It updates as I build.",
    ),
    ("start", "It's built, and studi0 is running at <address>."),
    (
        "start",
        "Tell me what to change, or ask how any part works. Two things you can say "
        'any time: "always use s0ma" and "always show studi0".',
    ),
    (
        "build",
        "Want to watch changes like this land in studi0? It opens beside the chat.",
    ),
    (
        "build",
        "Want to watch changes like this land in studi0? I'll start it and give "
        "you the link.",
    ),
    ("build", '"Yes, always"'),
    ("build", '"Just this once"'),
    ("build", '"No thanks"'),
    (
        "build",
        "I'll start it with each session from now on. Say \"only show studi0 when I "
        'ask" to change that.',
    ),
    ("build", "studi0 is running: <address>"),
)

#: The MCP surface the authoring server serves, which names every tool it has.
MCP_SURFACE = INTEGRATIONS.parent / "packages" / "s0ma-mcp" / "tests" / "snapshots" / "mcp_surface.json"


@pytest.fixture(scope="session")
def cli_parsers() -> dict[str, argparse.ArgumentParser]:
    """Every top-level ``s0ma`` command's own parser, by name."""
    main = importlib.import_module("s0ma_dsl.cli.main")
    return _subcommands(main.S0maCLI().build_parser())


def _options_of(parser: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    """Every option string one parser takes, with the action behind it."""
    return {
        option: action for action in parser._actions for option in action.option_strings
    }


def _s0ma_command_lines(text: str) -> list[list[str]]:
    """The words of every ``s0ma`` command a skill names, in code or a fence."""
    lines: list[list[str]] = []
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        for candidate in [line] if in_fence else INLINE_CODE.findall(line):
            words = candidate.split()
            if len(words) > 1 and words[0] == "s0ma":
                lines.append(words)
    return lines


class TestTheFrontDoor:
    """``start``, ``build`` and ``studi0``: the decided words and what they lean on."""

    @pytest.mark.parametrize(("name", "sentence"), FRONT_DOOR_SENTENCES)
    def test_every_decided_sentence_is_there_word_for_word(
        self, name: str, sentence: str, skills: dict[str, str]
    ) -> None:
        assert sentence in _one_line(skills[name]), (
            f"{name}: the decided sentence is not there as written: {sentence!r}"
        )

    def test_the_start_skill_names_the_machine_for_each_platform(
        self, skills: dict[str, str]
    ) -> None:
        text = _one_line(skills["start"])
        assert '"this Mac" on macOS, "this PC" on Windows and "this computer" on Linux' in text

    def test_start_points_at_the_skills_that_hold_the_detail(
        self, skills: dict[str, str]
    ) -> None:
        for other in ("setup", "new", "build", "studi0"):
            assert f"/s0ma:{other}" in skills["start"], f"start never names /s0ma:{other}"

    def test_build_records_the_offer_as_the_preferences_skill_says(
        self, skills: dict[str, str]
    ) -> None:
        text = _one_line(skills["build"])
        assert "/s0ma:preferences" in text
        assert 'section "The studi0 offer"' in text
        assert "## The studi0 offer" in skills["preferences"]
        assert "/s0ma:studi0" in text

    def test_setup_and_new_name_the_quick_way_in(self, skills: dict[str, str]) -> None:
        for name in ("setup", "new"):
            assert "`/s0ma:start` is the quick way in" in _one_line(skills[name])

    @pytest.mark.parametrize("name", ["start", "build", "studi0"])
    def test_every_option_named_is_one_the_command_takes(
        self, name: str, skills: dict[str, str], cli_parsers: dict[str, argparse.ArgumentParser]
    ) -> None:
        """``s0ma studi0 --no-open``, ``s0ma new project --template pipeline``.

        Read from each command's own parser, so a flag or a template name the
        CLI does not have fails here rather than in a person's first session.
        """
        checked = 0
        for words in _s0ma_command_lines(skills[name]):
            parser = cli_parsers.get(words[1])
            assert parser is not None, f"{name}: `s0ma {words[1]}` is not a command"
            options = _options_of(parser)
            for index, word in enumerate(words[2:], start=2):
                if not word.startswith("-"):
                    continue
                assert word in options, (
                    f"{name}: `s0ma {words[1]}` takes no {word}; it takes {sorted(options)}"
                )
                checked += 1
                choices = options[word].choices
                if choices is not None and index + 1 < len(words):
                    assert words[index + 1] in choices, (
                        f"{name}: `{' '.join(words)}`: {word} takes {sorted(choices)}"
                    )
        assert name == "build" or checked, f"{name}: no option was checked at all"

    def test_every_template_any_skill_names_is_one_new_project_offers(
        self, skills: dict[str, str], cli_parsers: dict[str, argparse.ArgumentParser]
    ) -> None:
        offered = _options_of(cli_parsers["new"])["--template"].choices
        assert offered is not None
        named = {
            found
            for text in skills.values()
            for found in re.findall(r"--template ([a-z]+)", text)
        }
        assert {"pipeline", "service", "library", "cli"} <= named
        assert named <= set(offered), sorted(named - set(offered))

    def test_the_tools_build_names_are_tools_the_server_serves(
        self, skills: dict[str, str]
    ) -> None:
        import json

        served = {tool["name"] for tool in json.loads(MCP_SURFACE.read_text(encoding="utf-8"))["tools"]}
        for tool in ("project_status", "check", "build_project"):
            assert f"`{tool}`" in skills["build"], f"build never names `{tool}`"
            assert tool in served, f"the server serves no tool called {tool}"

    def test_studi0_shows_its_own_address_and_names_no_tool(
        self, skills: dict[str, str]
    ) -> None:
        text = _one_line(skills["studi0"])
        assert "http://studi0.localhost:5710/" in text
        assert ".s0ma/studi0/active.json" in text
        assert "a tool that opens a web page in a pane or preview beside the chat" in text
        assert "Never open anything but studi0's own local address this way" in text
        assert "give the address as a link" in text

    def test_start_reports_only_what_was_printed(self, skills: dict[str, str]) -> None:
        """Every fresh build warns HOST_RUNTIME_UNDECLARED, so "All checks pass"
        has to be held to what the commands said, and a warning said aloud."""
        text = _one_line(skills["start"])
        assert 'Say "All checks pass" only when' in text
        assert "A warning is not a failure, but it was printed, so say it" in text
