"""``s0ma adopt baseline`` and ``s0ma adopt verify-parity``, run for real.

Every test here drives the real CLI against a throwaway copy of the
``layered_app`` brownfield fixture that has been through the real
``s0ma adopt init``, so what is asserted is what somebody at a terminal
would see. The fixture tree itself is never written to.

Four promises carry the milestone, and each has a section below.

**The baseline is taken before anything is lost.** It records what a
module's Python offers today into one committed file, it resolves the
way ``adopt scan`` and ``adopt draft`` resolve, taking it twice writes
the same bytes, and every refusal exits 2 having written nothing. The
expensive mistake — the Python file already deleted — is refused in its
own words rather than as a typo.

**Parity compares the built module with that record.** Clean means the
public surface is what it was; any difference exits 1 and names itself
on one line. It writes nothing anywhere (rule R-2, proved by hashing the
tree) and it parses the built module rather than importing it (rule
R-1, proved by a module planted in the copy whose import would leave
evidence).

**The headline proof.** One module goes the whole way — baseline, draft,
author, check, build, parity — then a signature is changed on purpose
and parity reports exactly that one difference; then the original
``.py`` is deleted and the fixture's *own* fifteen tests are run against
the built module. That last step is the one no s0ma command can stand in
for.

**What the last step cost.** A built module is emitted flat, as
``errors``, into the build directory — not as ``bookshelf.errors``. So
deleting ``src/bookshelf/errors.py`` from a package breaks every
``from .errors import ...`` in its siblings until the package's own
``__init__.py`` points the old name at the built module. Both halves are
asserted below: the failure a person hits with no alias, and the six
lines that make the suite green. The retrofit guide's rung 3 now spells
those lines out; before this milestone it named the technique in outline
only.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.adopt.model import BASELINE_FILENAME, BASELINE_SCHEMA, DRAFT_INTENT_MARKER
from s0ma_dsl.adopt.parity import PARITY_SCHEMA
from s0ma_dsl.cli.main import S0maCLI

if TYPE_CHECKING:
    from collections.abc import Iterator

_TESTS_DIR = Path(__file__).parent
_BROWNFIELD = _TESTS_DIR / "fixtures" / "brownfield"

EXIT_SUCCESS = 0
EXIT_FINDINGS = 1
EXIT_USAGE_ERROR = 2

#: How many tests the fixture application ships with. Restated rather
#: than counted at runtime: "the project's own suite is still green" is
#: only a claim if the number it is green at is the number it started
#: with.
FIXTURE_TESTS = 15

#: Every placeholder a draft leaves is ``<field>: "FIXME(adopt): …"`` on
#: one line. Filling them is a person's job; filling them *mechanically*
#: is how a test walks the loop without pretending to have written
#: meaning.
_PLACEHOLDER = re.compile(
    rf'^(?P<indent>\s*)(?P<field>[a-z_]+): "{re.escape(DRAFT_INTENT_MARKER)}[^"]*"$',
    re.MULTILINE,
)

#: What each filled field says. One sentence, long enough for the
#: language's own minimum, and honest about being written by a test.
_AUTHORED = (
    "Written by this test so the draft carries a real sentence where a "
    "person would have written one."
)


# ---------------------------------------------------------------------------
# A real project in a temporary directory
# ---------------------------------------------------------------------------


def _copy_fixture(tmp_path: Path, name: str = "layered_app") -> Path:
    """Copy one brownfield fixture application into *tmp_path*.

    The fixture tree is read-only as far as this suite is concerned
    (``test_brownfield_fixtures.py`` pins its bytes), and every command
    under test writes, so everything happens to a copy.
    """
    destination = tmp_path / name
    shutil.copytree(
        _BROWNFIELD / name,
        destination,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return destination


def _run(root: Path, *argv: str) -> int:
    """Run the real CLI against *root* and return its exit code."""
    return S0maCLI().run(["--project-root", str(root), *argv])


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    """``layered_app``, copied and taken through rung 1 for real."""
    root = _copy_fixture(tmp_path)
    assert _run(root, "adopt", "init") == EXIT_SUCCESS
    yield root


def _output(capsys: pytest.CaptureFixture[str]) -> tuple[str, str]:
    """This command's stdout and stderr, as one pair."""
    captured = capsys.readouterr()
    return captured.out, captured.err


def _flat(text: str) -> str:
    """*text* with every run of whitespace collapsed to one space."""
    return " ".join(text.split())


def _tree(root: Path) -> dict[str, str]:
    """Every file under *root*, by project-relative path and content hash."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _record(root: Path) -> dict[str, Any]:
    """The committed baselines file, read as JSON."""
    return json.loads((root / BASELINE_FILENAME).read_text(encoding="utf-8"))


def _author(draft: Path) -> int:
    """Replace every placeholder in *draft* with a real sentence; return the count.

    The structure is left exactly as the draft wrote it — only the value
    of each ``FIXME(adopt):`` field changes — which is what a person
    does too.
    """
    text = draft.read_text(encoding="utf-8")
    filled, count = _PLACEHOLDER.subn(
        lambda match: f'{match.group("indent")}{match.group("field")}: "{_AUTHORED}"',
        text,
    )
    draft.write_text(filled, encoding="utf-8", newline="\n")
    assert DRAFT_INTENT_MARKER not in filled
    return count


def _build(root: Path) -> None:
    """Build the project's sources, the way its own guide says to."""
    assert _run(root, "build", str(root / "src")) in (EXIT_SUCCESS, EXIT_FINDINGS)


# ---------------------------------------------------------------------------
# T3 — the baseline
# ---------------------------------------------------------------------------


class TestTheBaselineRecordsWhatThePythonPromised:
    """One committed file, deterministic bytes, and a reminder to commit it."""

    def test_one_module_is_captured_into_the_one_record(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
        out, _ = _output(capsys)

        document = _record(project)
        assert document["schema"] == BASELINE_SCHEMA
        assert list(document["modules"]) == ["bookshelf.errors"]
        entry = document["modules"]["bookshelf.errors"]
        assert entry["source_path"] == "src/bookshelf/errors.py"
        assert entry["source_hash"].startswith("sha256:")
        names = {row["name"] for row in entry["captured_surface"]["entries"]}
        assert "BookshelfError" in names
        assert "BookNotFoundError.__init__" in names
        assert out.startswith("Captured 1 baseline:\n")

    def test_it_says_where_the_record_is_and_to_commit_it(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "adopt", "baseline", "bookshelf.errors")
        out, _ = _output(capsys)

        said = _flat(out)
        assert BASELINE_FILENAME in said
        assert "Commit it with your code" in said
        assert "cannot be taken again once the Python file is gone" in said
        assert "s0ma adopt draft bookshelf.errors" in said

    def test_a_path_and_a_dotted_name_reach_the_same_record(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The resolver is `adopt draft`'s, so the three commands agree."""
        by_name = _copy_fixture(tmp_path / "a")
        by_path = _copy_fixture(tmp_path / "b")
        for root in (by_name, by_path):
            assert _run(root, "adopt", "init") == EXIT_SUCCESS
        _output(capsys)

        assert _run(by_name, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
        assert (
            _run(by_path, "adopt", "baseline", "src/bookshelf/errors.py")
            == EXIT_SUCCESS
        )
        _output(capsys)

        assert (by_name / BASELINE_FILENAME).read_bytes() == (
            by_path / BASELINE_FILENAME
        ).read_bytes()

    def test_several_modules_at_once_land_sorted(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(
                project,
                "adopt",
                "baseline",
                "bookshelf.models",
                "bookshelf.errors",
                "bookshelf.config",
            )
            == EXIT_SUCCESS
        )
        out, _ = _output(capsys)

        assert list(_record(project)["modules"]) == [
            "bookshelf.config",
            "bookshelf.errors",
            "bookshelf.models",
        ]
        listed = [
            line.split()[0] for line in out.splitlines() if line.startswith("  bookshelf")
        ]
        assert listed == sorted(listed)

    def test_all_takes_the_application_code_and_leaves_the_tests(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt", "baseline", "--all") == EXIT_SUCCESS
        _output(capsys)

        captured = set(_record(project)["modules"])
        assert "bookshelf.errors" in captured
        assert "bookshelf.storage" in captured
        # Never a test, never the package marker.
        assert not any(name.startswith("tests") for name in captured)
        assert "bookshelf" not in captured

    def test_capturing_an_unchanged_module_again_is_a_byte_for_byte_no_op(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A record that churns is a record nobody reviews."""
        _run(project, "adopt", "baseline", "--all")
        first = (project / BASELINE_FILENAME).read_bytes()
        _run(project, "adopt", "baseline", "--all")
        second = (project / BASELINE_FILENAME).read_bytes()
        _output(capsys)

        assert first == second
        assert b"\r" not in first

    def test_a_second_capture_of_a_changed_module_says_the_record_was_replaced(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, "adopt", "baseline", "bookshelf.errors")
        _output(capsys)
        before = _record(project)["modules"]["bookshelf.errors"]["source_hash"]

        source = project / "src" / "bookshelf" / "errors.py"
        source.write_text(
            source.read_text(encoding="utf-8") + "\n\nclass LateError(LendingError):\n"
            '    """Added after the first baseline was taken."""\n',
            encoding="utf-8",
            newline="\n",
        )
        assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
        out, _ = _output(capsys)

        after = _record(project)["modules"]["bookshelf.errors"]
        assert after["source_hash"] != before
        assert "the old record has been replaced" in _flat(out)
        assert "bookshelf.errors" in _flat(out)
        assert "LateError" in {
            row["name"] for row in after["captured_surface"]["entries"]
        }

    def test_the_python_file_is_not_touched(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = _tree(project)

        assert _run(project, "adopt", "baseline", "--all") == EXIT_SUCCESS
        _output(capsys)

        after = _tree(project)
        assert set(after) - set(before) == {BASELINE_FILENAME}
        assert all(after[path] == digest for path, digest in before.items())


class TestTheBaselineRefuses:
    """Five refusals, each exit 2, each having written nothing."""

    def test_a_tree_that_is_not_a_project_yet(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _copy_fixture(tmp_path)
        before = _tree(root)

        assert _run(root, "adopt", "baseline", "bookshelf.errors") == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "not a s0ma project yet" in err
        assert "s0ma adopt init" in err
        assert _tree(root) == before

    def test_nothing_named_and_no_all(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = _tree(project)

        assert _run(project, "adopt", "baseline") == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "no module was named" in err
        assert "--all" in err
        assert _tree(project) == before

    def test_names_and_all_together(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "adopt", "baseline", "bookshelf.errors", "--all")
            == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        assert "two ways of saying which modules" in _flat(err)

    def test_a_name_nothing_matches_offers_the_nearest(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = _tree(project)

        assert (
            _run(project, "adopt", "baseline", "bookshelf.erors") == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        assert "no module called bookshelf.erors" in err
        assert "bookshelf.errors" in err
        assert _tree(project) == before

    def test_a_test_file(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "adopt", "baseline", "tests/test_api.py") == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        assert "is a test" in err

    def test_a_module_whose_python_is_already_gone_says_so_in_its_own_words(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The one mistake this whole command exists to prevent."""
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        (project / "src" / "bookshelf" / "errors.py").unlink()
        _output(capsys)

        assert (
            _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        said = _flat(err)
        assert "has been converted already" in said
        assert "src/bookshelf/errors.s0ma" in said
        assert "before the file is deleted" in said
        assert not (project / BASELINE_FILENAME).exists()

    def test_re_capturing_a_recorded_module_whose_file_is_gone_quotes_the_store(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The store wrote that sentence for this moment; the command surfaces it."""
        assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
        (project / "src" / "bookshelf" / "errors.py").unlink()
        _output(capsys)

        assert (
            _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        said = _flat(err)
        assert "there is no file at src/bookshelf/errors.py any more" in said
        assert "git restore src/bookshelf/errors.py" in said


class TestTheBaselineNeverImportsTheCodeItReads:
    """Retrofit rule R-1, proved against a module that would tell on it."""

    @staticmethod
    def _plant(project: Path) -> Path:
        """A module whose import writes a file and then raises."""
        marker = project / "src" / "bookshelf" / "IMPORT_HAPPENED.txt"
        (project / "src" / "bookshelf" / "booby_trap.py").write_text(
            '"""A module that cannot be imported without leaving evidence."""\n'
            "\n"
            "from pathlib import Path\n"
            "\n"
            'TRAP_NAME = "booby trap"\n'
            "\n"
            'Path(__file__).with_name("IMPORT_HAPPENED.txt").write_text(\n'
            '    "imported", encoding="utf-8"\n'
            ")\n"
            'raise RuntimeError("this module must never be imported")\n'
            "\n"
            "\n"
            "def unreachable() -> str:\n"
            '    """Never runs, and still has to be recorded."""\n'
            "    return TRAP_NAME\n",
            encoding="utf-8",
            newline="\n",
        )
        return marker

    def test_the_surface_is_recorded_and_the_trap_never_springs(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        marker = self._plant(project)

        assert (
            _run(project, "adopt", "baseline", "bookshelf.booby_trap") == EXIT_SUCCESS
        )
        _output(capsys)

        assert not marker.exists()
        entries = _record(project)["modules"]["bookshelf.booby_trap"][
            "captured_surface"
        ]["entries"]
        assert {"TRAP_NAME", "unreachable"} <= {row["name"] for row in entries}


# ---------------------------------------------------------------------------
# T2 — verify-parity
# ---------------------------------------------------------------------------


@pytest.fixture
def converted(project: Path, capsys: pytest.CaptureFixture[str]) -> Iterator[Path]:
    """``bookshelf.errors`` taken all the way to a build, once."""
    assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
    assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
    _author(project / "src" / "bookshelf" / "errors.s0ma")
    _build(project)
    _output(capsys)
    yield project


class TestParityComparesTheBuildWithTheRecord:
    """A clean verdict, a real finding, and the two renderings of each."""

    def test_a_faithful_conversion_has_the_surface_it_had(
        self, converted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(converted, "adopt", "verify-parity", "bookshelf.errors")
            == EXIT_SUCCESS
        )
        out, _ = _output(capsys)

        assert out.splitlines()[0] == (
            "bookshelf.errors — same surface "
            "(compared with bookshelf_build/errors.py)"
        )
        assert "run the project's own tests" in _flat(out).lower()

    def test_the_registration_the_build_added_is_not_a_finding(
        self, converted: Path
    ) -> None:
        """The ignore list, checked against real emitted code rather than a stub."""
        emitted = (converted / "bookshelf_build" / "errors.py").read_text(
            encoding="utf-8"
        )
        assert "@component(" in emitted
        assert "register_module(" in emitted
        assert "__all__ = [" in emitted
        assert "# s0ma-source-hash:" in emitted

    def test_json_carries_the_schema_and_is_deterministic(
        self, converted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(converted, "adopt", "verify-parity", "bookshelf.errors", "--format", "json")
        first, _ = _output(capsys)
        _run(converted, "adopt", "verify-parity", "bookshelf.errors", "--format", "json")
        second, _ = _output(capsys)

        assert first == second
        document = json.loads(first)
        assert document["schema"] == PARITY_SCHEMA
        assert document["clean"] is True
        assert document["modules"][0]["built_path"] == "bookshelf_build/errors.py"

    def test_all_compares_what_is_built_and_names_what_is_not(
        self, converted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(converted, "adopt", "baseline", "bookshelf.models") == EXIT_SUCCESS
        _output(capsys)

        assert _run(converted, "adopt", "verify-parity", "--all") == EXIT_SUCCESS
        out, _ = _output(capsys)

        said = _flat(out)
        assert "bookshelf.errors — same surface" in said
        assert "bookshelf.models" in said
        assert "nothing built to compare it with yet" in said

    def test_it_writes_nothing_anywhere(
        self, converted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Retrofit rule R-2, proved by hashing every file in the project."""
        before = _tree(converted)

        assert (
            _run(converted, "adopt", "verify-parity", "--all") == EXIT_SUCCESS
        )
        _output(capsys)

        assert _tree(converted) == before

    def test_it_parses_the_built_module_rather_than_importing_it(
        self, converted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Rule R-1 where it matters most: a check must not run what it judges."""
        built = converted / "bookshelf_build" / "errors.py"
        marker = converted / "bookshelf_build" / "IMPORT_HAPPENED.txt"
        built.write_text(
            built.read_text(encoding="utf-8")
            + "\n"
            'Path(__file__).with_name("IMPORT_HAPPENED.txt").write_text(\n'
            '    "imported", encoding="utf-8"\n'
            ")\n"
            'raise RuntimeError("the built module must never be imported")\n',
            encoding="utf-8",
            newline="\n",
        )

        assert (
            _run(converted, "adopt", "verify-parity", "bookshelf.errors")
            == EXIT_SUCCESS
        )
        _output(capsys)

        assert not marker.exists()


class TestParityRefuses:
    """Each refusal exits 2, and says which rung is really missing."""

    def test_a_tree_that_is_not_a_project_yet(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _copy_fixture(tmp_path)

        assert (
            _run(root, "adopt", "verify-parity", "bookshelf.errors")
            == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        assert "not a s0ma project yet" in err

    def test_nothing_named_and_no_all(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt", "verify-parity") == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "no module was named" in err

    def test_nothing_built_yet(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
        _output(capsys)

        assert (
            _run(project, "adopt", "verify-parity", "bookshelf.errors")
            == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        said = _flat(err)
        assert "nothing has been built here yet" in said
        assert said.endswith("run `s0ma build` first.")

    def test_a_module_with_no_baseline_while_its_python_is_still_there(
        self, converted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(converted, "adopt", "draft", "bookshelf.config") == EXIT_SUCCESS
        _author(converted / "src" / "bookshelf" / "config.s0ma")
        _build(converted)
        _output(capsys)

        assert (
            _run(converted, "adopt", "verify-parity", "bookshelf.config")
            == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        said = _flat(err)
        assert "there is no baseline for bookshelf.config" in said
        assert "s0ma adopt baseline bookshelf.config" in said
        assert "src/bookshelf/config.py is still there" in said

    def test_a_module_with_no_baseline_whose_python_is_gone(
        self, converted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The comparison cannot be made any more, said plainly."""
        assert _run(converted, "adopt", "draft", "bookshelf.config") == EXIT_SUCCESS
        _author(converted / "src" / "bookshelf" / "config.s0ma")
        _build(converted)
        (converted / "src" / "bookshelf" / "config.py").unlink()
        _output(capsys)

        assert (
            _run(converted, "adopt", "verify-parity", "bookshelf.config")
            == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        said = _flat(err)
        assert "no Python file left to take one from" in said
        assert "cannot be made any more" in said
        assert "restore the file from version control" in said
        assert "the project's own tests" in said

    def test_a_module_with_a_baseline_that_is_not_in_the_build(
        self, converted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(converted, "adopt", "baseline", "bookshelf.models") == EXIT_SUCCESS
        _output(capsys)

        assert (
            _run(converted, "adopt", "verify-parity", "bookshelf.models")
            == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        said = _flat(err)
        assert "the build does not contain it" in said
        assert "s0ma adopt draft bookshelf.models" in said

    def test_a_refusal_answers_in_json_when_json_was_asked_for(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "adopt", "verify-parity", "--all", "--format", "json")
            == EXIT_USAGE_ERROR
        )
        out, _ = _output(capsys)

        assert json.loads(out)["ok"] is False


# ---------------------------------------------------------------------------
# T4 — the headline proof
# ---------------------------------------------------------------------------


#: The six lines that point a package's old module name at the module
#: s0ma built, written into the package's own ``__init__.py`` before it
#: imports anything of its own. This is the retrofit guide's "final
#: flip", made concrete: ``bootstrap_imports`` is the migration guide's
#: documented entry point, and the two bindings cover both ways a caller
#: reaches the module — ``from .errors import X`` through ``sys.modules``
#: and ``bookshelf.errors.X`` through the package attribute.
ALIAS = (
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "from s0ma.bootstrap import bootstrap_imports\n"
    "\n"
    '_BUILT = bootstrap_imports(Path(__file__).resolve().parents[2] / "bookshelf_build")\n'
    'errors = _BUILT["errors"]\n'
    'sys.modules[f"{__name__}.errors"] = errors\n'
    "\n"
)


def _run_fixture_suite(root: Path) -> subprocess.CompletedProcess[str]:
    """Run the fixture application's own pytest suite, in a subprocess.

    ``python -m pytest`` rather than ``uv run``: the fixture carries a
    ``[project]`` table of its own, and ``uv`` would write a lockfile and
    a virtual environment into it (the fixture's NOTES.txt says so). The
    interpreter running this suite already has s0ma installed, which is
    what a converted module needs at import time.
    """
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "pytest", "-q"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


class TestOneModuleConvertedEndToEnd:
    """Baseline, draft, author, check, build, parity — then the real tests.

    One test rather than ten: each step's input is the previous step's
    output on disk, and splitting them would mean either rebuilding the
    project ten times or sharing mutable state between tests that read
    as independent. It carries no ``slow`` marker because it does not
    need one — three builds and two pytest subprocesses come to well
    under a second — so it runs in the ordinary dsl suite, which is
    where a proof of the product's headline promise belongs.
    """

    def test_the_whole_ladder(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        errors_py = project / "src" / "bookshelf" / "errors.py"
        draft = project / "src" / "bookshelf" / "errors.s0ma"

        # 1. Record what the Python promises, while it is still there.
        assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
        assert (project / BASELINE_FILENAME).is_file()

        # 2. Draft it. The Python file is not touched.
        before = errors_py.read_bytes()
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        assert errors_py.read_bytes() == before

        # 3. Author every placeholder the draft left.
        assert _author(draft) == 21

        # 4. The checker is happy with it.
        assert _run(project, "check") == EXIT_SUCCESS

        # 5. Build, and 6. compare: the surface is what it was.
        _build(project)
        _output(capsys)
        assert (
            _run(project, "adopt", "verify-parity", "bookshelf.errors")
            == EXIT_SUCCESS
        )
        out, _ = _output(capsys)
        assert "same surface" in out

        # 7. Change one signature on purpose. Exactly one finding.
        faithful = draft.read_text(encoding="utf-8")
        changed = faithful.replace(
            "        def __init__(self, isbn: str) -> None:\n"
            "            super().__init__("
            'f"no title with ISBN {isbn} is in the catalogue")',
            '        def __init__(self, isbn: str, shelf: str = "unknown") -> None:\n'
            "            super().__init__("
            'f"no title with ISBN {isbn} is in the catalogue")',
            1,
        )
        assert changed != faithful
        draft.write_text(changed, encoding="utf-8", newline="\n")
        _build(project)
        _output(capsys)

        assert (
            _run(
                project,
                "adopt",
                "verify-parity",
                "bookshelf.errors",
                "--format",
                "json",
            )
            == EXIT_FINDINGS
        )
        out, _ = _output(capsys)
        findings = json.loads(out)["modules"][0]["findings"]
        assert [(one["kind"], one["symbol"]) for one in findings] == [
            ("signature_changed", "BookNotFoundError.__init__")
        ]
        assert findings[0]["before"] == "(self, isbn: str) -> None"
        assert findings[0]["after"] == "(self, isbn: str, shelf: str='unknown') -> None"

        # 8. Put it back. Clean again.
        draft.write_text(faithful, encoding="utf-8", newline="\n")
        _build(project)
        _output(capsys)
        assert (
            _run(project, "adopt", "verify-parity", "bookshelf.errors")
            == EXIT_SUCCESS
        )
        _output(capsys)

        # 9. Delete the Python file. Without an alias, the package breaks:
        #    the built module is flat (`errors`), not `bookshelf.errors`.
        init = project / "src" / "bookshelf" / "__init__.py"
        errors_py.unlink()
        broken = _run_fixture_suite(project)
        assert broken.returncode != 0
        assert "No module named 'bookshelf.errors'" in broken.stdout + broken.stderr

        # 10. Point the old name at the built module, and the project's
        #     own fifteen tests pass against the converted module.
        init.write_text(
            init.read_text(encoding="utf-8").replace(
                "from .catalog import Catalog\n",
                ALIAS + "from .catalog import Catalog\n",
                1,
            ),
            encoding="utf-8",
            newline="\n",
        )
        green = _run_fixture_suite(project)
        assert green.returncode == 0, green.stdout + green.stderr
        assert f"{FIXTURE_TESTS} passed" in green.stdout


# ---------------------------------------------------------------------------
# T5 — wiring
# ---------------------------------------------------------------------------


class TestBothCommandsAreWiredTheWayTheLedgersNeed:
    """Methods on the owning class, classified, and reachable."""

    @pytest.mark.parametrize(
        ("command", "method"),
        [
            ("adopt/baseline", "_cmd_adopt_baseline"),
            ("adopt/verify-parity", "_cmd_adopt_verify_parity"),
        ],
    )
    def test_the_handler_is_a_method_of_the_registered_cli_class(
        self, command: str, method: str
    ) -> None:
        from s0ma_dsl.docs_model.providers_cli import _HANDLERS

        assert _HANDLERS[command] == f"s0ma_dsl.cli.main.S0maCLI.{method}"
        assert callable(getattr(S0maCLI, method))

    def test_the_baseline_says_that_it_reads_and_writes(self) -> None:
        from s0ma_dsl.docs_model.providers_cli import _SIDE_EFFECTS

        effects, sentence = _SIDE_EFFECTS["adopt/baseline"]
        assert effects == ("read", "write")
        assert "never imported" in sentence

    def test_parity_says_that_it_only_reads(self) -> None:
        from s0ma_dsl.docs_model.providers_cli import _SIDE_EFFECTS

        effects, sentence = _SIDE_EFFECTS["adopt/verify-parity"]
        assert effects == ("read",)
        assert "writes nothing anywhere" in sentence

    def test_the_parser_serves_the_frozen_command_lines(self) -> None:
        """§5.3's two lines, exactly: no flag added, renamed or dropped."""
        parser = S0maCLI().build_parser()
        adopt = _subparsers(parser)["adopt"]

        baseline = _subparsers(adopt)["baseline"]
        assert _options(baseline) == ["--all"]
        assert _positionals(baseline) == ["modules"]

        parity = _subparsers(adopt)["verify-parity"]
        assert _options(parity) == ["--all", "--format"]
        assert _positionals(parity) == ["modules"]

    def test_the_json_schema_is_named_in_the_help(self) -> None:
        """An agent has to be able to find out what it will be reading."""
        parser = S0maCLI().build_parser()
        parity = _subparsers(_subparsers(parser)["adopt"])["verify-parity"]

        assert PARITY_SCHEMA in parity.format_help()

    def test_the_bare_usage_line_names_them(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt") == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "s0ma adopt baseline <module or file>..." in err
        assert "s0ma adopt verify-parity <module>..." in err


def _subparsers(parser: Any) -> dict[str, Any]:
    """The sub-parsers of *parser*, by the name a person types."""
    for action in parser._actions:  # noqa: SLF001 - the parser is the contract
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            return choices
    raise AssertionError("no sub-commands on this parser")


def _options(parser: Any) -> list[str]:
    """Every long option of *parser*, sorted, minus ``--help``."""
    return sorted(
        option
        for action in parser._actions  # noqa: SLF001 - the parser is the contract
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    )


def _positionals(parser: Any) -> list[str]:
    """Every positional argument of *parser*, in order."""
    return [
        action.dest
        for action in parser._actions  # noqa: SLF001 - as above
        if not action.option_strings
    ]


# ---------------------------------------------------------------------------
# G3b — the clean verdict carries the last step of the ladder
# ---------------------------------------------------------------------------


#: Where the code block starts in the printed step: numbered prose is
#: indented two (and its continuations five), the lines to paste six.
_BLOCK_INDENT = "      "


def _printed_alias_lines(out: str) -> list[str]:
    """The alias block, lifted out of the verdict exactly as printed.

    This is what makes the test a proof rather than a restatement:
    nothing about the block is spelled out here. The lines are taken
    from the command's own output, dedented, and written into the
    package — so if what the command prints ever stops being runnable
    Python, the fixture's own suite says so.
    """
    lines: list[str] = []
    seen = False
    for line in out.splitlines():
        if line.startswith(_BLOCK_INDENT) and not line[len(_BLOCK_INDENT):].startswith(" "):
            seen = True
            lines.append(line[len(_BLOCK_INDENT):])
        elif seen and not line.strip():
            lines.append("")
        elif seen:
            break
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _placement_index(source: str) -> int:
    """The line the printed sentence points at, as a rule a program can follow.

    "Below its docstring and any ``from __future__`` line, above the
    package's own imports" — read literally, and with the blank lines
    between them skipped, which is where a person would put it too. With
    none of those present the answer is line one, and the sentence is
    then simply "at the top".
    """
    module = ast.parse(source)
    index = 0
    if module.body and ast.get_docstring(module) is not None:
        index = module.body[0].end_lineno or 0
    for node in module.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            index = max(index, node.end_lineno or 0)
    lines = source.splitlines()
    while index < len(lines) and not lines[index].strip():
        index += 1
    return index


def _apply_alias(init: Path, out: str) -> None:
    """Put the printed lines exactly where the printed sentence says.

    Nothing here knows the block or the file: the lines come out of the
    command's own output and the position comes out of the command's own
    instruction. That is what makes the sentence testable rather than
    merely readable — if it ever stops being followable, this stops
    producing a file that compiles.
    """
    printed = _printed_alias_lines(out)
    assert printed, "the clean verdict printed no alias block"
    source = init.read_text(encoding="utf-8")
    lines = source.splitlines()
    at = _placement_index(source)
    init.write_text(
        "\n".join([*lines[:at], *printed, "", *lines[at:]]) + "\n",
        encoding="utf-8",
        newline="\n",
    )


class TestTheCleanVerdictSaysWhatIsLeftToDo:
    """G1's H-8, H-12 and the pilot's G2-4, in the place the person is looking.

    A clean parity verdict is the moment before the dangerous step, and
    until now it ended there. Three facts follow it: the lines that bind
    the old name to the built module (computed for *this* project, since
    the one value nobody can derive is how far the package sits below
    the project root), that the runtime has to be declared and
    installed, and that the build directory now ships with the
    application.

    Both tests below follow the printed lines **literally** — parsed out
    of the output and written into the package — and then run the
    fixture application's own suite with the original Python deleted.
    """

    def test_the_printed_lines_convert_the_src_layout_for_real(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        errors_py = project / "src" / "bookshelf" / "errors.py"
        draft = project / "src" / "bookshelf" / "errors.s0ma"

        assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _author(draft)
        _build(project)
        _output(capsys)

        assert (
            _run(project, "adopt", "verify-parity", "bookshelf.errors")
            == EXIT_SUCCESS
        )
        out, _ = _output(capsys)
        said = _flat(out)

        assert "Before you delete src/bookshelf/errors.py:" in out
        assert "s0ma-core and s0ma-dsl" in said, "the runtime, named"
        assert "[project].dependencies" in said
        assert "Ship bookshelf_build with the application" in said
        assert "packages your wheel installs" in said
        assert "run this project's tests with the Python file still there" in said

        _apply_alias(project / "src" / "bookshelf" / "__init__.py", out)
        errors_py.unlink()
        green = _run_fixture_suite(project)
        assert green.returncode == 0, green.stdout + green.stderr
        assert f"{FIXTURE_TESTS} passed" in green.stdout

    def test_the_printed_lines_convert_a_top_level_package_for_real(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The pilot's shape: packages at the repository root, no ``src/``.

        The guide's worked example needs ``parents[2]`` and this layout
        needs ``parents[1]`` — the pilot had to work that out by hand
        (``retrofit-g2-pilot.md``). Nothing is quoted here either: the
        lines come from the command.
        """
        root = _copy_fixture(tmp_path, "multi_pkg_app")
        assert (
            _run(
                root, "adopt", "init",
                "--source-root", "harnesslib",
                "--source-root", "evallib",
                "--source-root", "metrics",
            )
            == EXIT_SUCCESS
        )
        counters_py = root / "metrics" / "counters.py"
        draft = root / "metrics" / "counters.s0ma"

        assert _run(root, "adopt", "baseline", "metrics.counters") == EXIT_SUCCESS
        assert _run(root, "adopt", "draft", "metrics.counters") == EXIT_SUCCESS
        assert draft.is_file(), "the draft belongs beside the module it came from"
        _author(draft)
        assert _run(root, "build") == EXIT_SUCCESS
        _output(capsys)

        assert (
            _run(root, "adopt", "verify-parity", "metrics.counters") == EXIT_SUCCESS
        )
        out, _ = _output(capsys)

        assert "same surface" in out
        assert 'parents[1] / "orchard_bench_build"' in out, "this layout's own climb"
        _apply_alias(root / "metrics" / "__init__.py", out)
        counters_py.unlink()
        green = _run_fixture_suite(root)
        assert green.returncode == 0, green.stdout + green.stderr
        assert "13 passed" in green.stdout

    def test_the_document_carries_the_same_three_facts(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        draft = project / "src" / "bookshelf" / "errors.s0ma"
        assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _author(draft)
        _build(project)
        _output(capsys)

        assert (
            _run(
                project, "adopt", "verify-parity", "bookshelf.errors",
                "--format", "json",
            )
            == EXIT_SUCCESS
        )
        out, _ = _output(capsys)
        document = json.loads(out)

        assert document["schema"] == PARITY_SCHEMA, "additive, under the same schema"
        plan = document["before_you_delete"]
        assert plan["declare_runtime"] == ["s0ma-core", "s0ma-dsl"]
        assert plan["ship_build_dir"] == "bookshelf_build"
        assert plan["alias"]["package_init"] == "src/bookshelf/__init__.py"
        assert plan["alias"]["lines"] == _printed_alias_lines(
            _text_verdict(project, capsys)
        )

    def test_several_modules_at_once_get_the_facts_and_a_way_to_the_lines(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The block is per package, so `--all` points at the one-module run."""
        for module in ("bookshelf.errors", "bookshelf.config"):
            assert _run(project, "adopt", "baseline", module) == EXIT_SUCCESS
            assert _run(project, "adopt", "draft", module) == EXIT_SUCCESS
            _author(project / "src" / "bookshelf" / f"{module.split('.')[-1]}.s0ma")
        _build(project)
        _output(capsys)

        assert _run(project, "adopt", "verify-parity", "--all") == EXIT_SUCCESS
        out, _ = _output(capsys)
        said = _flat(out)

        assert "Before you delete the Python of bookshelf.config, bookshelf.errors" in said
        assert "`s0ma adopt verify-parity <module>` prints the exact lines" in said
        assert "import sys" not in out, "no block where there is no one answer"
        assert "s0ma-core and s0ma-dsl" in said
        assert "Ship bookshelf_build" in said

    def test_nothing_extra_once_the_original_is_gone(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The step is over: the verdict goes back to being a verdict."""
        draft = project / "src" / "bookshelf" / "errors.s0ma"
        assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _author(draft)
        _build(project)
        _output(capsys)
        assert (
            _run(project, "adopt", "verify-parity", "bookshelf.errors")
            == EXIT_SUCCESS
        )
        out, _ = _output(capsys)
        _apply_alias(project / "src" / "bookshelf" / "__init__.py", out)
        (project / "src" / "bookshelf" / "errors.py").unlink()

        assert (
            _run(project, "adopt", "verify-parity", "bookshelf.errors")
            == EXIT_SUCCESS
        )
        after, _ = _output(capsys)

        assert "same surface" in after
        assert "Before you delete" not in after


def _text_verdict(root: Path, capsys: pytest.CaptureFixture[str]) -> str:
    """The text form of the same verdict, for comparing with the document."""
    assert _run(root, "adopt", "verify-parity", "bookshelf.errors") == EXIT_SUCCESS
    out, _ = _output(capsys)
    return out


# ---------------------------------------------------------------------------
# G3c — the alias sentence has to be followable to the letter
# ---------------------------------------------------------------------------


def _clean_verdict_for_errors(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> str:
    """Take ``bookshelf.errors`` to a clean verdict and return what it printed."""
    assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
    assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
    _author(project / "src" / "bookshelf" / "errors.s0ma")
    _build(project)
    _output(capsys)
    assert _run(project, "adopt", "verify-parity", "bookshelf.errors") == EXIT_SUCCESS
    out, _ = _output(capsys)
    return out


class TestTheAliasSentenceIsLiterallyFollowable:
    """G3c: "at the top … above its own imports" was not a place.

    A package's ``__init__.py`` usually opens with a docstring and a
    ``from __future__`` import, and Python refuses a ``from __future__``
    that is not the first statement after the docstring. So a reader who
    did exactly what the old sentence said wrote a ``SyntaxError`` into
    the one step of the ladder where the application is briefly unable to
    import itself — the worst possible place to be debugging the tool
    instead of the conversion.

    The tests below follow the sentence rather than quoting it: the
    position comes from :func:`_placement_index`, which is the sentence
    turned into a rule, and what comes out has to compile and then carry
    the application's own suite.
    """

    def test_this_package_has_the_two_lines_that_have_to_stay_first(
        self, project: Path
    ) -> None:
        """The hazard is the ordinary case, not a corner of one."""
        source = (project / "src" / "bookshelf" / "__init__.py").read_text(
            encoding="utf-8"
        )

        assert source.startswith('"""'), "it opens with a docstring"
        assert "from __future__ import annotations" in source

    def test_the_sentence_says_where_the_block_goes(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        said = _flat(_clean_verdict_for_errors(project, capsys))

        assert "below its docstring and any `from __future__` line" in said
        assert "above the package's own imports" in said
        assert "at the top of src/bookshelf/__init__.py" not in said

    def test_the_document_says_the_same_thing_in_a_field(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An agent reading JSON places the lines as carefully as a person."""
        _clean_verdict_for_errors(project, capsys)
        assert (
            _run(
                project, "adopt", "verify-parity", "bookshelf.errors",
                "--format", "json",
            )
            == EXIT_SUCCESS
        )
        out, _ = _output(capsys)
        alias = json.loads(out)["before_you_delete"]["alias"]

        assert alias["place"] == (
            "below its docstring and any `from __future__` line, above the "
            "package's own imports"
        )
        assert alias["place"] in _flat(_text_verdict(project, capsys))

    def test_following_it_to_the_letter_leaves_a_file_that_compiles(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The whole claim: do what it says, delete the file, stay green."""
        init = project / "src" / "bookshelf" / "__init__.py"
        out = _clean_verdict_for_errors(project, capsys)

        _apply_alias(init, out)
        written = init.read_text(encoding="utf-8")
        compile(written, str(init), "exec")

        (project / "src" / "bookshelf" / "errors.py").unlink()
        green = _run_fixture_suite(project)
        assert green.returncode == 0, green.stdout + green.stderr
        assert f"{FIXTURE_TESTS} passed" in green.stdout

    def test_the_old_reading_of_it_would_not_even_compile(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Why the sentence had to change, as one assertion.

        "At the top" put above everything, which is what the words said
        and what a careful reader would do.
        """
        init = project / "src" / "bookshelf" / "__init__.py"
        printed = _printed_alias_lines(_clean_verdict_for_errors(project, capsys))
        at_the_very_top = "\n".join(
            [*printed, "", init.read_text(encoding="utf-8")]
        )

        with pytest.raises(SyntaxError):
            compile(at_the_very_top, str(init), "exec")

    def test_an_empty_package_init_takes_the_block_at_the_top(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The other end of the same sentence, where "at the top" is right.

        With no docstring and no ``from __future__`` line there is
        nothing to go below, so the rule lands on line one — and the
        sentence is still true, which is the thing worth proving about a
        wording that now names two things that may not be there.
        """
        root = _copy_fixture(tmp_path, "multi_pkg_app")
        init = root / "metrics" / "__init__.py"
        init.write_text("", encoding="utf-8", newline="\n")
        assert (
            _run(
                root, "adopt", "init",
                "--source-root", "harnesslib",
                "--source-root", "evallib",
                "--source-root", "metrics",
            )
            == EXIT_SUCCESS
        )
        assert _run(root, "adopt", "baseline", "metrics.counters") == EXIT_SUCCESS
        assert _run(root, "adopt", "draft", "metrics.counters") == EXIT_SUCCESS
        _author(root / "metrics" / "counters.s0ma")
        assert _run(root, "build") == EXIT_SUCCESS
        _output(capsys)

        assert _run(root, "adopt", "verify-parity", "metrics.counters") == EXIT_SUCCESS
        out, _ = _output(capsys)
        assert "below its docstring and any `from __future__` line" in _flat(out)

        _apply_alias(init, out)
        written = init.read_text(encoding="utf-8")
        compile(written, str(init), "exec")
        assert written.splitlines()[0] == "import sys", "nothing above it to go below"

        (root / "metrics" / "counters.py").unlink()
        green = _run_fixture_suite(root)
        assert green.returncode == 0, green.stdout + green.stderr
        assert "13 passed" in green.stdout
