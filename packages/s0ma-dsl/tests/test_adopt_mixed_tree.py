"""The mixed-tree honesty sweep: one project, one moment, one set of numbers.

Milestone G3b's T2. A retrofit is walked over weeks, so the state a real
project spends nearly all its time in is *half done* — some modules
converted, one part-drafted, the rest plain Python. That is the state in
which the pilot and the unaided-agent trial found this family's worst
defect: ``s0ma adopt status`` said one module converted, ``s0ma score``
said one componentized, and ``s0ma verify --all src`` — the command
``s0ma adopt init`` recommends — said ``HOLLOW_MODEL``, "0 modeled". On
a product whose whole claim is that a codebase can carry an accurate
account of itself, three commands giving three answers reads as "you
broke it" (G1's H-10, pilot G2-9), and ``s0ma doctor`` added a fourth
voice by advising a greenfield command into a directory that may not
exist (H-2, G2-13).

So this file builds that state **through the real commands** — init,
baseline, draft, author, check, build, verify-parity, then one more
draft left unfinished on purpose — and asks every reading command what
it sees. Nothing is stubbed and nothing is hand-written into the tree:
if the loop stops producing a mixed tree, these tests stop having one.

The tree it builds, from the ``layered_app`` fixture (nine modules in
the conversion set):

* **three converted and parity-clean**, their Python still in place —
  ``config`` (which has a public function, so the score can move at all:
  friction F-E3-2), ``errors`` and ``models``;
* **one drafted and unfinished**, ``notifications``, still carrying every
  placeholder the harvester wrote and the one block it could not place;
* **five untouched**, plain Python.

What is asserted is agreement, not any particular number: the converted
count is read from each command that states one and they must all be the
same, the backlog adds up to the conversion set, no reading calls the
tree hollow, no command advises creating a first module, the unfinished
draft is refused with exactly its own findings and nothing else, and the
application's own fifteen tests still pass throughout.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.cli.main import S0maCLI

if TYPE_CHECKING:
    from collections.abc import Iterator

_TESTS_DIR = Path(__file__).parent
_BROWNFIELD = _TESTS_DIR / "fixtures" / "brownfield"

EXIT_SUCCESS = 0
EXIT_FINDINGS = 1

#: The modules taken all the way to a clean parity verdict. ``config``
#: leads for a reason that is not alphabetical: it is the only leaf with
#: a public function in it, and a project whose converted modules are all
#: cells has no measurable score at all (friction F-E3-2). A sweep that
#: could not show the score moving would be checking the wrong thing.
CONVERTED = ("bookshelf.config", "bookshelf.errors", "bookshelf.models")

#: The module left part-drafted, with every placeholder still in it.
DRAFTED = "bookshelf.notifications"

#: What that draft owes, from D3's own count: one refusal per unwritten
#: field, plus the single block the harvester quarantined rather than
#: guess at. Restated here rather than counted at runtime — "exactly its
#: own findings and nothing else" is only a claim if the number is.
DRAFTED_PLACEHOLDERS = 17
DRAFTED_UNPLACED = 1

#: The conversion set ``layered_app`` offers: eleven Python files, less
#: the package marker and the declared entry point.
CONVERSION_SET = 9

#: The application's own test count, unchanged by any of this.
FIXTURE_TESTS = 15

#: Every placeholder a draft leaves is ``<field>: "FIXME(adopt): …"`` on
#: one line; filling them mechanically is how a test walks the loop
#: without pretending to have written meaning.
_MARKER = "FIXME(adopt):"
_PLACEHOLDER = re.compile(
    rf'^(?P<indent>\s*)(?P<field>[a-z_]+): "{re.escape(_MARKER)}[^"]*"$',
    re.MULTILINE,
)
_AUTHORED = (
    "Written by this test so the draft carries a real sentence where a "
    "person would have written one."
)

#: Row statuses `s0ma verify` counts as a modeled module — the shared
#: definition this sweep compares every reading against.
_MODELED = frozenset({"CLEAN", "CONVERTED", "EDITED", "STALE", "CONFLICT"})


# ---------------------------------------------------------------------------
# The tree, built once, by the real commands
# ---------------------------------------------------------------------------


def _run(root: Path, *argv: str) -> int:
    """Run the real CLI against *root* and return its exit code."""
    return S0maCLI().run(["--project-root", str(root), *argv])


def _author(draft: Path) -> int:
    """Replace every placeholder in *draft* with a real sentence."""
    text = draft.read_text(encoding="utf-8")
    filled, count = _PLACEHOLDER.subn(
        lambda match: f'{match.group("indent")}{match.group("field")}: "{_AUTHORED}"',
        text,
    )
    draft.write_text(filled, encoding="utf-8", newline="\n")
    return count


@pytest.fixture(scope="module")
def mixed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """``layered_app``, taken one third of the way up rung 3 for real.

    Module-scoped: the state is expensive to reach (a dozen commands and
    a build) and every test here reads it rather than changing it. The
    one test that writes — the application's own suite, which only
    reads — runs in a subprocess against the same tree.
    """
    root = tmp_path_factory.mktemp("mixed") / "layered_app"
    shutil.copytree(
        _BROWNFIELD / "layered_app",
        root,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    assert _run(root, "adopt", "init") == EXIT_SUCCESS

    for module in CONVERTED:
        assert _run(root, "adopt", "baseline", module) == EXIT_SUCCESS
        assert _run(root, "adopt", "draft", module) == EXIT_SUCCESS
        stem = module.rsplit(".", 1)[-1]
        assert _author(root / "src" / "bookshelf" / f"{stem}.s0ma") > 0

    # Clean before the unfinished draft arrives, so the build has
    # something to build and the refusal below is about one file.
    assert _run(root, "check") == EXIT_SUCCESS
    assert _run(root, "build") == EXIT_SUCCESS
    assert _run(root, "adopt", "verify-parity", *CONVERTED) == EXIT_SUCCESS
    assert _run(root, "adopt", "draft", DRAFTED) == EXIT_SUCCESS
    yield root


def _json(
    root: Path, capsys: pytest.CaptureFixture[str], *argv: str, expect: int = EXIT_SUCCESS
) -> Any:
    """Run a reading command in its machine form and parse what it printed."""
    assert _run(root, *argv) == expect
    return json.loads(capsys.readouterr().out)


def _status(root: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    document: dict[str, Any] = _json(root, capsys, "adopt", "status", "--format", "json")
    return document


def _verify(
    root: Path, capsys: pytest.CaptureFixture[str], target: Path
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = _json(
        root, capsys, "verify", "--all", str(target), "--format", "json"
    )
    return rows


def _modeled(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["status"] in _MODELED]


# ---------------------------------------------------------------------------
# What each command says on its own
# ---------------------------------------------------------------------------


class TestEachCommandReadsTheTreeHonestly:
    """Every reading is true of the tree that is actually on disk."""

    def test_status_counts_the_three_states_the_tree_is_in(
        self, mixed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        counts = dict(_status(mixed, capsys)["counts"])

        assert counts["modules"] == CONVERSION_SET
        assert counts["converted"] == len(CONVERTED)
        assert counts["drafted"] == 1
        assert counts["placeholders"] == DRAFTED_PLACEHOLDERS
        assert counts["parity-same-surface"] == len(CONVERTED)
        # Converted + the one being drafted + what is left = the set.
        assert (
            counts["converted"] + counts["drafted"] + counts["plain-python"]
            == CONVERSION_SET
        )

    def test_the_score_is_measurable_and_moves(
        self, mixed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """F-E3-2's counter-example, as a standing test.

        The score is ``n/a`` for a project whose converted modules are
        all cells, because two required metrics are about public nerves.
        One converted module with a function in it is enough to make the
        whole roll-up measurable, which is what the guide promises a
        reader will see.
        """
        report = _json(mixed, capsys, "score", "--format", "json")
        registration = report["faculties"]["proprioception"]["metrics"]["registration"]

        assert registration["componentized"] == len(CONVERTED)
        assert report["overall"] is not None
        assert report["overall"] > 0

    def test_a_source_root_holding_converted_modules_is_not_hollow(
        self, mixed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """G1's H-10 and pilot G2-9, at the rung they were found on."""
        rows = _verify(mixed, capsys, mixed / "src")
        statuses = Counter(row["status"] for row in rows)

        assert "HOLLOW_MODEL" not in statuses
        assert statuses["CONVERTED"] == len(CONVERTED)
        for row in rows:
            if row["status"] == "CONVERTED":
                assert "converted — built at bookshelf_build/" in row["detail"]

    def test_the_build_directory_reads_the_same_three_modules(
        self, mixed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rows = _verify(mixed, capsys, mixed / "bookshelf_build")

        assert [row["status"] for row in _modeled(rows)] == ["CLEAN"] * len(CONVERTED)

    def test_the_whole_tree_counts_each_module_once(
        self, mixed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The source and the build are both under it; three modules, not six."""
        rows = _verify(mixed, capsys, mixed)

        assert len(_modeled(rows)) == len(CONVERTED)
        assert all(row["status"] == "CLEAN" for row in _modeled(rows))

    def test_doctor_defers_to_the_ladder(
        self, mixed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = _json(mixed, capsys, "doctor", "--format", "json")

        assert report["project"]["suggested_next_action"] == (
            "mid-retrofit — `s0ma adopt status` has the next command"
        )
        assert "new module" not in json.dumps(report)

    def test_the_unfinished_draft_is_refused_with_its_own_findings(
        self, mixed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exactly what that draft owes, in exactly one file."""
        report = _json(mixed, capsys, "check", "--format", "json", expect=EXIT_FINDINGS)
        codes = Counter(error["code"] for error in report["errors"])

        assert codes == {
            "ADOPT_PLACEHOLDER_INTENT": DRAFTED_PLACEHOLDERS,
            "ADOPT_UNPLACED_CODE": DRAFTED_UNPLACED,
        }
        assert {Path(error["file"]).name for error in report["errors"]} == {
            "notifications.s0ma"
        }

    def test_the_applications_own_tests_are_still_green(self, mixed: Path) -> None:
        """Nothing the retrofit has done so far changes what runs.

        The Python files are all still there, so this is the control
        rather than the proof — but a control that went red would mean
        the tooling had touched something it promises never to touch.
        """
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "pytest", "-q"],
            cwd=mixed,
            capture_output=True,
            text=True,
            check=False,
        )

        assert done.returncode == 0, done.stdout + done.stderr
        assert f"{FIXTURE_TESTS} passed" in done.stdout


# ---------------------------------------------------------------------------
# And the same thing, said by all of them at once
# ---------------------------------------------------------------------------


class TestTheCommandsAgreeWithEachOther:
    """The sweep's own question: does the project get one answer or four?"""

    def test_every_command_that_states_a_converted_count_states_the_same_one(
        self, mixed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        status = dict(_status(mixed, capsys)["counts"])["converted"]
        score = _json(mixed, capsys, "score", "--format", "json")
        componentized = score["faculties"]["proprioception"]["metrics"]["registration"][
            "componentized"
        ]
        from_source = len(_modeled(_verify(mixed, capsys, mixed / "src")))
        from_build = len(_modeled(_verify(mixed, capsys, mixed / "bookshelf_build")))

        assert {status, componentized, from_source, from_build} == {len(CONVERTED)}

    def test_the_backlog_is_the_same_number_in_both_places_that_state_it(
        self, mixed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``UNKNOWN`` is the backlog the guide tells a reader to watch.

        ``s0ma verify`` counts the Python files it has no model of, and
        ``s0ma score`` counts the same set; the three converted modules
        whose originals are still on disk are honestly in both, because
        that Python is still what runs until step 7 deletes it.
        """
        rows = _verify(mixed, capsys, mixed / "src")
        unknown_rows = [row for row in rows if row["status"] == "UNKNOWN"]
        score = _json(mixed, capsys, "score", "--format", "json")
        unknown_score = score["faculties"]["proprioception"]["metrics"]["registration"][
            "unknown"
        ]

        assert len(unknown_rows) == unknown_score

    def test_no_reading_of_this_tree_advises_making_a_first_module(
        self, mixed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A tree one third converted is not a tree with nothing in it."""
        said = json.dumps([
            _status(mixed, capsys),
            _json(mixed, capsys, "doctor", "--format", "json"),
            _verify(mixed, capsys, mixed / "src"),
        ])

        assert "s0ma new module" not in said
        assert "HOLLOW_MODEL" not in said

    def test_the_one_next_command_is_about_the_module_furthest_along(
        self, mixed: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Four modules are in flight; the step is for the one nearest done."""
        document = _status(mixed, capsys)

        assert document["next_module"] == CONVERTED[0]
        assert document["next_command"] == f"s0ma adopt verify-parity {CONVERTED[0]}"
        assert document["before_you_delete"]["alias"]["package_init"] == (
            "src/bookshelf/__init__.py"
        )
