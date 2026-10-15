"""``s0ma adopt status``, run for real at every rung of the ladder.

The command for coming back. Every test here drives the real CLI against a
throwaway copy of the ``layered_app`` brownfield fixture that has been taken
through the real commands to the state under test, so what is asserted is
what somebody at a terminal would see after a fortnight away.

Four promises carry the milestone.

**It says where you are.** Nine states, walked with the real commands —
untouched, perimeter set, baseline taken, drafted, authored, built, compared,
compared with a difference planted on purpose, and the original deleted and
aliased — and each one asserts the rung, the counts, the one next command and
the fifteen-line budget.

**It chooses one next step, by a table.** The table is in the module docstring
of :mod:`s0ma_dsl.adopt.status` and every row of it is asserted here, on the
fixture where the fixture reaches the row and on a minimal synthetic tree
where it does not. Where several modules are half converted the step is for
the one furthest along, which is the rule that stops a retrofit turning into
several half-conversions, and the output says so.

**It writes nothing** (retrofit rule R-2). Proved by hashing the whole tree
before and after — on *every* call this suite makes, because :func:`_status`
does the hashing itself, including the states that carry a build directory,
a build cache and a committed baseline.

**It never imports the code it reads** (rule R-1). Proved against a module
planted in the copy whose import would leave a file behind and then raise.

One more gate lives here, and it is about somebody else's promise: ``s0ma
adopt init`` writes a block into the project's ``AGENTS.md`` that names
commands, and until this milestone one of them did not exist. Every command
line in that block is now parsed out of the block itself and offered to the
live CLI parser, so the block can never again name a command that is not
there.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.adopt.status import (
    MAX_STATUS_LINES,
    STATE_AUTHORED,
    STATE_BASELINE_TAKEN,
    STATE_BUILT_WITHOUT_BASELINE,
    STATE_CONVERTED,
    STATE_DRAFTED,
    STATE_PARITY_CLEAN,
    STATE_PARITY_DIFFERS,
    STATE_PLAIN_PYTHON,
    STATUS_SCHEMA,
)
from s0ma_dsl.cli.main import S0maCLI

# The programmatic placeholder fill lives with the milestone that wrote it
# (E2's end-to-end proof) and there is one of it on purpose: two tests that
# author a draft slightly differently would be two different drafts.
from tests.test_adopt_parity_cli import _author

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

_TESTS_DIR = Path(__file__).parent
_BROWNFIELD = _TESTS_DIR / "fixtures" / "brownfield"

EXIT_SUCCESS = 0
EXIT_USAGE_ERROR = 2

#: How many application modules ``layered_app`` offers a conversion: eleven
#: Python files, less the package marker and less the entry point the
#: perimeter declares as a bootstrap file. Restated rather than counted so a
#: fixture that grows a module is a decision somebody takes.
CONVERSION_SET = 9

#: The placeholders ``bookshelf.errors`` draws, pinned by D2's golden, D3's
#: diagnostics and D4's closing message. A fourth reader of the same number.
PLACEHOLDERS = 21

#: The first module of ``layered_app``'s leaf-first conversion order, which
#: is what a status at rung 1 sends somebody to.
FIRST_MODULE = "bookshelf.config"

#: One minimal, valid module, for the synthetic trees that test rows the
#: brownfield fixture cannot reach — a project with nothing left to convert.
WIDGET = """module widget
    layer: DOMAIN
    version: 0.1.0
    intent: "The one thing this synthetic project is made of."
    exports: [describe_self]
    requires: []
    uses: []

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve describe_self :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return a one-line description of what this component does."
    expects: "No input."
    guarantees: "Returns a non-empty human-readable string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def describe_self() -> str:
        \"\"\"Describe this component in one line.\"\"\"
        return "A component that knows what it is."
"""

#: The two bindings a package needs once one of its modules lives in the
#: build directory. E2 found that both are required and the guide's rung 3
#: spells them out; this suite reaches the state they create.
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


# ---------------------------------------------------------------------------
# A real project in a temporary directory
# ---------------------------------------------------------------------------


def _copy_fixture(tmp_path: Path, name: str = "layered_app") -> Path:
    """Copy one brownfield fixture application into *tmp_path*."""
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


def _tree(root: Path) -> dict[str, str]:
    """Every file under *root*, by project-relative path and content hash."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _status(
    root: Path,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
    expect: int = EXIT_SUCCESS,
) -> str:
    """Run ``adopt status`` against *root* and return what it printed.

    The zero-write proof (rule R-2) is taken here rather than in one test of
    its own, so that *every* reading this suite takes — in every state,
    including the ones carrying a build directory, a build cache and a
    committed baseline — proves it as a side effect of being taken.
    """
    before = _tree(root)
    assert _run(root, "adopt", "status", *argv) == expect
    assert _tree(root) == before, "adopt status wrote to the tree (rule R-2)"
    captured = capsys.readouterr()
    return captured.out if expect == EXIT_SUCCESS else captured.err


def _document(root: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """The same reading as its ``s0ma-adopt-status@1`` document."""
    parsed: dict[str, Any] = json.loads(_status(root, capsys, "--format", "json"))
    return parsed


def _counts(document: Mapping[str, Any]) -> dict[str, int]:
    """The document's count pairs as a mapping, for readable assertions."""
    return dict(document["counts"])


def _state_of(document: Mapping[str, Any], module: str) -> dict[str, Any]:
    """One module's row of the document's per-module list."""
    for row in document["modules"]:
        if row["module"] == module:
            return dict(row)
    raise AssertionError(f"{module} is not in the status document")


def _build(root: Path) -> None:
    """Build the project's sources, the way its own guide says to."""
    assert _run(root, "build", str(root / "src")) in (0, 1)


def _synthetic(root: Path, *, mode: str = "migration", module: str = WIDGET) -> Path:
    """A minimal s0ma project with one converted module and no Python.

    For the rows of the decision table a half-retrofitted fixture cannot
    reach: a project where there is nothing left to convert, so the work
    that remains is the strictness mode.
    """
    (root / "src").mkdir(parents=True)
    (root / "src" / "widget.s0ma").write_text(module, encoding="utf-8", newline="\n")
    _write_mode(root, mode)
    return root


def _write_mode(root: Path, mode: str) -> None:
    """Write the synthetic project's ``pyproject.toml`` at *mode*.

    Called again after the build for the ratchet rows: a project is built
    in the mode it was converted in and *then* moved up, which is what rung
    4 is — building a starter module straight into ``release`` would fail
    for want of the coverage that mode demands, and would be testing the
    build rather than the status.
    """
    (root / "pyproject.toml").write_text(
        '[project]\nname = "synthetic"\nversion = "0.1.0"\n'
        "\n"
        "[tool.s0ma]\n"
        'source_roots = ["src"]\n'
        "test_roots = []\n"
        f'mode = "{mode}"\n',
        encoding="utf-8",
        newline="\n",
    )


# ---------------------------------------------------------------------------
# The ladder, one rung at a time, walked with the real commands
# ---------------------------------------------------------------------------


@pytest.fixture
def untouched(tmp_path: Path) -> Path:
    """``layered_app`` exactly as it ships: plain Python, no perimeter."""
    return _copy_fixture(tmp_path)


@pytest.fixture
def project(untouched: Path, capsys: pytest.CaptureFixture[str]) -> Iterator[Path]:
    """Rung 1: the perimeter written by the real ``adopt init``."""
    assert _run(untouched, "adopt", "init") == EXIT_SUCCESS
    capsys.readouterr()
    yield untouched


@pytest.fixture
def baselined(project: Path, capsys: pytest.CaptureFixture[str]) -> Iterator[Path]:
    """One module's promise recorded, and nothing drafted."""
    assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
    capsys.readouterr()
    yield project


@pytest.fixture
def drafted(baselined: Path, capsys: pytest.CaptureFixture[str]) -> Iterator[Path]:
    """A draft with every one of its placeholders still in it."""
    assert _run(baselined, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
    capsys.readouterr()
    yield baselined


@pytest.fixture
def authored(drafted: Path, capsys: pytest.CaptureFixture[str]) -> Iterator[Path]:
    """The placeholders written, mechanically, the way E2's proof writes them."""
    assert _author(drafted / "src" / "bookshelf" / "errors.s0ma") == PLACEHOLDERS
    capsys.readouterr()
    yield drafted


@pytest.fixture
def built(authored: Path, capsys: pytest.CaptureFixture[str]) -> Iterator[Path]:
    """The converted module, emitted, with its baseline still to answer to."""
    _build(authored)
    capsys.readouterr()
    yield authored


class TestEachRungOfTheLadder:
    """Nine states, each read back the way somebody returning would read it."""

    def test_an_untouched_tree_is_rung_zero(
        self, untouched: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _status(untouched, capsys)

        assert text.startswith("This codebase — rung 0 of 4: nothing set up yet.")
        assert "no [tool.s0ma] table" in text
        assert "s0ma adopt scan" in text
        assert len(text.splitlines()) <= MAX_STATUS_LINES

    def test_the_perimeter_alone_is_rung_one(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _status(project, capsys)
        document = _document(project, capsys)

        assert document["rung"] == 1
        assert document["rung_label"] == "perimeter set, nothing converted yet"
        assert _counts(document) == {
            "adopted-in-place": 0,
            "baselines": 0,
            "converted": 0,
            "drafted": 0,
            "modules": CONVERSION_SET,
            "placeholders": 0,
            "plain-python": CONVERSION_SET,
        }
        assert document["next_command"] == f"s0ma adopt baseline {FIRST_MODULE}"
        assert f"Nothing converted yet: {CONVERSION_SET} modules" in text
        assert len(text.splitlines()) <= MAX_STATUS_LINES

    def test_the_parity_counts_are_absent_until_something_is_built(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Four zeroes would read as four answers to a question nobody asked."""
        assert not [
            name for name in _counts(_document(project, capsys)) if "parity" in name
        ]
        assert "parity" not in _status(project, capsys)

    def test_a_baseline_starts_a_module_without_converting_anything(
        self, baselined: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _status(baselined, capsys)
        document = _document(baselined, capsys)

        assert document["rung"] == 1, "recording a promise converts nothing"
        assert _counts(document)["baselines"] == 1
        assert _counts(document)["plain-python"] == CONVERSION_SET
        assert _state_of(document, "bookshelf.errors")["state"] == STATE_BASELINE_TAKEN
        assert document["next_command"] == "s0ma adopt draft bookshelf.errors"
        assert "In flight: bookshelf.errors" in text
        assert len(text.splitlines()) <= MAX_STATUS_LINES

    def test_a_draft_with_placeholders_counts_them_and_asks_for_them(
        self, drafted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _status(drafted, capsys)
        document = _document(drafted, capsys)
        counts = _counts(document)

        assert document["rung"] == 3
        assert counts["drafted"] == 1
        assert counts["converted"] == 0
        assert counts["placeholders"] == PLACEHOLDERS
        row = _state_of(document, "bookshelf.errors")
        assert row["state"] == STATE_DRAFTED
        assert row["placeholders"] == PLACEHOLDERS
        assert row["path"] == "src/bookshelf/errors.s0ma"
        assert document["next_command"] == "s0ma check"
        assert f"still carries {PLACEHOLDERS} placeholders" in " ".join(text.split())
        assert len(text.splitlines()) <= MAX_STATUS_LINES

    def test_an_authored_draft_is_converted_and_asks_to_be_built(
        self, authored: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _status(authored, capsys)
        document = _document(authored, capsys)
        counts = _counts(document)

        assert document["rung"] == 3
        assert counts["converted"] == 1
        assert counts["drafted"] == 0
        assert counts["placeholders"] == 0
        assert counts["plain-python"] == CONVERSION_SET - 1
        assert _state_of(document, "bookshelf.errors")["state"] == STATE_AUTHORED
        assert document["next_command"] == "s0ma build"
        assert f"1 of {CONVERSION_SET} modules converted" in text
        assert len(text.splitlines()) <= MAX_STATUS_LINES

    def test_the_build_step_is_the_bare_command_and_it_runs(
        self, authored: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Friction F-E2-2, closed: `s0ma build` runs with no argument now.

        The source root is still reported — it is a fact about the
        project an agent wants — but the step no longer has to carry it
        into the command line.
        """
        document = _document(authored, capsys)

        assert document["source_root"] == "src"
        assert document["next_command"] == "s0ma build"
        assert _run(authored, "build") == EXIT_SUCCESS
        capsys.readouterr()

    def test_a_built_module_is_compared_without_being_asked_to_be(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Nothing records a verdict, so the status computes one every time."""
        text = _status(built, capsys)
        document = _document(built, capsys)
        counts = _counts(document)

        assert counts["parity-same-surface"] == 1
        assert counts["parity-differences"] == 0
        assert counts["parity-baseline-not-built"] == 0
        assert counts["parity-built-without-baseline"] == 0
        row = _state_of(document, "bookshelf.errors")
        assert row["state"] == STATE_PARITY_CLEAN
        assert row["parity"] == "same-surface"
        assert row["baseline"] is True
        assert "parity: 1 same surface" in text
        assert len(text.splitlines()) <= MAX_STATUS_LINES

    def test_running_verify_parity_first_changes_nothing_it_says(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = _status(built, capsys)
        assert _run(built, "adopt", "verify-parity", "bookshelf.errors") == EXIT_SUCCESS
        capsys.readouterr()

        assert _status(built, capsys) == before

    def test_parity_clean_says_the_original_is_safe_to_delete_and_needs_an_alias(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Row 3 carries the fact itself and names a command that runs.

        It used to send the reader to a guide section — which an
        installed toolchain cannot always open, and which is a document
        rather than an answer. G3b (G1's H-8): the one line that matters
        is here, the lines themselves are one runnable command away, and
        the JSON carries the whole plan as fields.
        """
        printed = _status(built, capsys)
        text = " ".join(printed.split())
        document = _document(built, capsys)
        # The closing line names the guide on every screen (G3c) and is
        # not part of the answer; what is asserted here is the answer.
        answer = " ".join(printed.split("The whole path")[0].split())

        assert "Before you delete src/bookshelf/errors.py" in text
        assert "point its old name at the built module" in text
        assert "in src/bookshelf/__init__.py" in text, "this project's own file"
        assert document["next_command"] == "s0ma adopt verify-parity bookshelf.errors"
        assert "doc:guide/" not in answer, "no document stands in for the answer"
        assert "http" not in text, "nothing is linked by URL"

    def test_the_document_carries_the_whole_alias_plan_for_this_project(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The three facts as fields, additive under the same schema."""
        plan = _document(built, capsys)["before_you_delete"]

        assert plan["declare_runtime"] == ["s0ma-core", "s0ma-dsl"]
        assert plan["ship_build_dir"] == "bookshelf_build"
        assert plan["modules"] == ["bookshelf.errors"]
        alias = plan["alias"]
        assert alias["package_init"] == "src/bookshelf/__init__.py"
        assert alias["python_path"] == "src/bookshelf/errors.py"
        assert alias["built_module"] == "errors"
        # `parents[2]`: src/bookshelf/__init__.py → src/bookshelf → src →
        # the project root. A flat package would need parents[1], which
        # is why this is computed rather than quoted from the guide.
        assert 'parents[2] / "bookshelf_build"' in "\n".join(alias["lines"])
        assert 'sys.modules[f"{__name__}.errors"] = errors' in alias["lines"]

    def test_no_alias_plan_before_the_step_that_needs_one(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert "before_you_delete" not in _document(project, capsys)

    def test_a_planted_difference_is_counted_and_the_step_is_about_that_module(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        draft = built / "src" / "bookshelf" / "errors.s0ma"
        faithful = draft.read_text(encoding="utf-8")
        draft.write_text(
            faithful.replace(
                "        def __init__(self, isbn: str) -> None:\n"
                "            super().__init__("
                'f"no title with ISBN {isbn} is in the catalogue")',
                '        def __init__(self, isbn: str, shelf: str = "unknown") -> None:\n'
                "            super().__init__("
                'f"no title with ISBN {isbn} is in the catalogue")',
                1,
            ),
            encoding="utf-8",
            newline="\n",
        )
        assert draft.read_text(encoding="utf-8") != faithful
        _build(built)
        capsys.readouterr()

        text = " ".join(_status(built, capsys).split())
        document = _document(built, capsys)
        row = _state_of(document, "bookshelf.errors")

        assert row["state"] == STATE_PARITY_DIFFERS
        assert row["parity"] == "differences"
        assert row["differences"] == 1
        assert _counts(document)["parity-differences"] == 1
        assert _counts(document)["parity-same-surface"] == 0
        assert (
            document["next_command"] == "s0ma adopt verify-parity bookshelf.errors"
        )
        assert "one difference" in text
        assert len(_status(built, capsys).splitlines()) <= MAX_STATUS_LINES

    def test_the_deleted_original_finishes_that_module_and_moves_to_the_next(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The last step of rung 3: the Python file goes and its name is aliased."""
        (built / "src" / "bookshelf" / "errors.py").unlink()
        init = built / "src" / "bookshelf" / "__init__.py"
        init.write_text(
            init.read_text(encoding="utf-8").replace(
                "from .catalog import Catalog\n", ALIAS + "from .catalog import Catalog\n", 1
            ),
            encoding="utf-8",
            newline="\n",
        )

        text = _status(built, capsys)
        document = _document(built, capsys)
        row = _state_of(document, "bookshelf.errors")

        assert row["state"] == STATE_CONVERTED
        assert row["python_path"] is None
        assert row["path"] == "src/bookshelf/errors.s0ma"
        assert document["in_flight"] == [], "nothing is half done any more"
        assert document["rung"] == 3, "eight modules are still plain Python"
        assert _counts(document)["converted"] == 1
        assert document["next_command"] == f"s0ma adopt baseline {FIRST_MODULE}"
        assert len(text.splitlines()) <= MAX_STATUS_LINES


class TestEveryPrintedPathIsForwardSlashed:
    """NFR-7, in the one family that prints a path in nearly every sentence."""

    def test_no_output_carries_a_backslash_or_a_machine_path(
        self, drafted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _status(drafted, capsys)
        document = _status(drafted, capsys, "--format", "json")

        assert "src/bookshelf/errors.s0ma" in text
        assert '"path": "src/bookshelf/errors.s0ma"' in document
        for rendered in (text, document):
            assert "\\" not in rendered
            assert str(drafted) not in rendered


class TestItNeverImportsTheCodeItReads:
    """Retrofit rule R-1, proved against a module that would tell on it."""

    def test_a_module_whose_import_leaves_evidence_never_springs(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        marker = built / "src" / "bookshelf" / "IMPORT_HAPPENED.txt"
        (built / "src" / "bookshelf" / "booby_trap.py").write_text(
            '"""A module that cannot be imported without leaving evidence."""\n'
            "\n"
            "from pathlib import Path\n"
            "\n"
            'TRAP_NAME = "booby trap"\n'
            "\n"
            'Path(__file__).with_name("IMPORT_HAPPENED.txt").write_text(\n'
            '    "imported", encoding="utf-8"\n'
            ")\n"
            'raise RuntimeError("this module must never be imported")\n',
            encoding="utf-8",
            newline="\n",
        )

        document = _document(built, capsys)

        assert not marker.exists()
        assert _state_of(document, "bookshelf.booby_trap")["state"] == (
            STATE_PLAIN_PYTHON
        )


# ---------------------------------------------------------------------------
# The decision table, row by row
# ---------------------------------------------------------------------------


class TestTheDecisionTable:
    """Every row of the table in ``adopt/status.py``'s module docstring."""

    def test_row_1_no_project_reads_the_codebase_first(
        self, untouched: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _document(untouched, capsys)["next_command"] == "s0ma adopt scan"

    def test_row_2_a_project_with_nothing_to_convert_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A perimeter around a directory holding no application code."""
        root = tmp_path / "empty"
        (root / "src" / "pkg").mkdir(parents=True)
        (root / "src" / "pkg" / "__init__.py").write_text(
            "", encoding="utf-8", newline="\n"
        )
        (root / "pyproject.toml").write_text(
            '[project]\nname = "empty"\nversion = "0.1.0"\n'
            '\n[tool.s0ma]\nsource_roots = ["src"]\ntest_roots = []\n'
            'mode = "migration"\n',
            encoding="utf-8",
            newline="\n",
        )

        document = _document(root, capsys)

        assert _counts(document)["modules"] == 0
        assert document["next_command"] == "s0ma adopt scan"
        assert "No application code was found" in document["next_step"]

    def test_row_5_built_with_no_baseline_asks_for_one_while_it_can_be_taken(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The baseline was skipped; the Python file is still there to record."""
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _author(project / "src" / "bookshelf" / "errors.s0ma")
        _build(project)
        capsys.readouterr()

        document = _document(project, capsys)
        row = _state_of(document, "bookshelf.errors")

        assert row["state"] == STATE_BUILT_WITHOUT_BASELINE
        assert row["parity"] == "built-without-baseline"
        assert _counts(document)["parity-built-without-baseline"] == 1
        assert document["next_command"] == "s0ma adopt baseline bookshelf.errors"
        assert "still there" in document["next_step"]

    def test_a_baseline_with_nothing_built_of_it_is_named_as_such(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The fourth parity verdict: recorded, and not built yet."""
        assert _run(built, "adopt", "baseline", "bookshelf.models") == EXIT_SUCCESS
        capsys.readouterr()

        document = _document(built, capsys)

        assert _state_of(document, "bookshelf.models")["parity"] == (
            "baseline-not-built"
        )
        assert _counts(document)["parity-baseline-not-built"] == 1

    @pytest.mark.parametrize(
        ("mode", "command"),
        [
            ("migration", "s0ma check --mode dev"),
            ("dev", "s0ma check --mode strict"),
            ("strict", "s0ma check --mode release"),
            ("release", "s0ma score --gate --gate-mode release"),
        ],
    )
    def test_rows_10_and_11_nothing_left_to_convert_is_the_mode_ladder(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        mode: str,
        command: str,
    ) -> None:
        root = _synthetic(tmp_path / mode)
        _build(root)
        _write_mode(root, mode)
        capsys.readouterr()

        text = _status(root, capsys)
        document = _document(root, capsys)

        assert document["rung"] == 4
        assert document["rung_label"] == "ratcheting"
        assert document["mode"] == mode
        assert document["next_command"] == command
        assert document["next_module"] is None
        assert "All 1 module converted." in text
        assert len(text.splitlines()) <= MAX_STATUS_LINES

    def test_the_furthest_along_module_chooses_the_step(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Two modules in flight: the one nearest the end wins, and it says so."""
        assert _run(built, "adopt", "baseline", "bookshelf.models") == EXIT_SUCCESS
        assert _run(built, "adopt", "draft", "bookshelf.models") == EXIT_SUCCESS
        capsys.readouterr()

        text = _status(built, capsys)
        document = _document(built, capsys)

        assert document["in_flight"] == ["bookshelf.errors", "bookshelf.models"]
        assert document["next_module"] == "bookshelf.errors"
        assert "finish what is started before starting another" in text
        assert "In flight: bookshelf.errors (2 unfinished)" in text
        assert len(text.splitlines()) <= MAX_STATUS_LINES

    def test_a_tie_in_progress_is_broken_by_the_conversion_order(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Two baselines and no drafts: the earlier module of the order wins."""
        assert _run(project, "adopt", "baseline", "bookshelf.models") == EXIT_SUCCESS
        assert _run(project, "adopt", "baseline", "bookshelf.errors") == EXIT_SUCCESS
        capsys.readouterr()

        document = _document(project, capsys)

        # `bookshelf.errors` comes before `bookshelf.models` in the scan's
        # leaf-first order, whatever order the baselines were taken in.
        assert document["in_flight"] == ["bookshelf.errors", "bookshelf.models"]
        assert document["next_command"] == "s0ma adopt draft bookshelf.errors"


# ---------------------------------------------------------------------------
# The document an agent reads
# ---------------------------------------------------------------------------


class TestTheJsonDocument:
    """``s0ma-adopt-status@1``: complete, deterministic, and only that."""

    def test_the_schema_is_named_and_the_document_is_all_there_is(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        raw = _status(built, capsys, "--format", "json")
        document = json.loads(raw)

        assert document["schema"] == STATUS_SCHEMA
        assert raw.endswith("\n")
        assert set(document) == {
            # `before_you_delete` is additive under @1 and appears only
            # at the one rung it is about — which this fixture is at.
            "before_you_delete",
            "counts",
            "in_flight",
            "modules",
            "mode",
            "next_command",
            "next_module",
            "next_step",
            "project",
            "rung",
            "rung_label",
            "schema",
            "score",
            "score_floor",
            "source_root",
        }

    def test_two_runs_are_byte_identical(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        first = _status(built, capsys, "--format", "json")
        second = _status(built, capsys, "--format", "json")

        assert first == second

    def test_every_module_of_the_conversion_set_carries_its_whole_state(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        document = _document(built, capsys)

        assert len(document["modules"]) == CONVERSION_SET
        for row in document["modules"]:
            assert set(row) == {
                "baseline",
                "differences",
                "module",
                "parity",
                "path",
                "placeholders",
                "python_path",
                "quarantined",
                "state",
            }
        assert [row["module"] for row in document["modules"]][:2] == [
            FIRST_MODULE,
            "bookshelf.errors",
        ], "the scan's leaf-first conversion order, not alphabetical"

    def test_the_next_step_is_both_a_sentence_and_a_command(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        document = _document(project, capsys)

        assert document["next_command"] == f"s0ma adopt baseline {FIRST_MODULE}"
        assert document["next_step"].endswith(".")
        assert FIRST_MODULE in document["next_step"]
        assert document["next_command"] not in document["next_step"]

    def test_the_counts_are_sorted_pairs(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        names = [name for name, _ in _document(built, capsys)["counts"]]

        assert names == sorted(names)

    def test_the_mode_and_its_floor_are_reported_and_the_score_may_be_honestly_absent(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The floor is what pinning this mode would demand; the score is real."""
        document = _document(built, capsys)

        assert document["mode"] == "migration"
        assert document["score_floor"] == 50.0
        assert document["score"] is None, (
            "nothing measurable yet — an n/a faculty is not a zero"
        )

    def test_a_finished_project_reports_a_real_score_against_its_floor(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The number is `s0ma score`'s own, composed and never re-derived.

        Fifty per cent: the one module's structure is wholly in s0ma and its
        public nerve has no doc-ref and no declared test, which is exactly
        what ``s0ma score`` says about the same tree.
        """
        root = _synthetic(tmp_path / "scored", mode="dev")
        _build(root)
        capsys.readouterr()

        document = _document(root, capsys)

        assert document["score"] == 50.0
        assert document["score_floor"] == 50.0
        assert "score 50.0%" in _status(root, capsys)

    def test_rung_zero_has_no_mode_no_score_and_no_floor(
        self, untouched: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        document = _document(untouched, capsys)

        assert document["mode"] is None
        assert document["score"] is None
        assert document["score_floor"] is None
        assert document["project"] is None


# ---------------------------------------------------------------------------
# The argument, and the two ways this can refuse
# ---------------------------------------------------------------------------


class TestThePathArgument:
    """``[PATH]`` behaves the way ``adopt scan``'s does, including rung 0."""

    def test_a_path_is_read_instead_of_the_project_root(
        self, untouched: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert S0maCLI().run(["adopt", "status", str(untouched)]) == EXIT_SUCCESS
        out, _ = capsys.readouterr().out, None

        assert "rung 0 of 4" in out

    def test_a_tree_inside_a_s0ma_project_is_still_read_as_its_own(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The table has to be on *this* tree, exactly as the scan requires."""
        outer = _synthetic(tmp_path / "outer", mode="dev")
        inner = _copy_fixture(outer, "layered_app")

        assert _document(inner, capsys)["rung"] == 0

    def test_a_path_that_is_not_a_directory_is_refused(
        self, untouched: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = untouched / "pyproject.toml"
        assert (
            S0maCLI().run(["adopt", "status", str(target)]) == EXIT_USAGE_ERROR
        )
        err = capsys.readouterr().err

        assert "is not a directory" in err
        assert "s0ma adopt status:" in err

    def test_a_half_converted_project_is_still_exit_zero(
        self, drafted: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A status is a reading, never a verdict: 21 placeholders is not a failure."""
        _status(drafted, capsys, expect=EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# G3c — one id for the guide
# ---------------------------------------------------------------------------


class TestTheClosingLineNamesTheGuide:
    """Two commands named one thing "the guide" and pointed at two pages.

    ``adopt init``'s ``AGENTS.md`` block sends the reader to
    ``doc:guide/retrofit-existing-codebase``; this closing line used to
    send them to ``journey:retrofit-existing-codebase``. Both resolve,
    both are about the retrofit, and nothing on either screen said which
    of them was the one to read — so the reader had to open both to find
    out. The guide is the page a person reads; the journey is the
    machine-checked path, and it is not offered as a substitute for it.
    """

    #: What the closing line says, in every state.
    GUIDE = "s0ma docs show doc:guide/retrofit-existing-codebase"

    @pytest.mark.parametrize(
        "tree", ["untouched", "project", "drafted", "built"]
    )
    def test_every_state_closes_on_the_same_line(
        self,
        request: pytest.FixtureRequest,
        capsys: pytest.CaptureFixture[str],
        tree: str,
    ) -> None:
        root = request.getfixturevalue(tree)
        text = _status(root, capsys)

        assert text.rstrip("\n").endswith(f"rung by rung: {self.GUIDE}")
        assert "journey:retrofit-existing-codebase" not in text
        assert len(text.splitlines()) <= MAX_STATUS_LINES

    def test_it_is_the_id_the_written_block_already_names(
        self, project: Path
    ) -> None:
        """One id, said by both surfaces a retrofitted repository carries."""
        from s0ma_dsl.adopt.perimeter import render_agents_block

        assert f"`{self.GUIDE}`" in render_agents_block("some_build")


# ---------------------------------------------------------------------------
# The block `adopt init` writes, and the commands it names
# ---------------------------------------------------------------------------


class TestTheAgentsBlockNamesOnlyLiveCommands:
    """``adopt init`` promises commands to whoever opens the repository next.

    Until this milestone the block named ``s0ma adopt status``, which did not
    exist — a promise a reader would have found out about by typing it. Every
    command line in the block is now offered to the live parser, so the block
    cannot name an unbuilt command again without this failing.
    """

    #: Commands the block names in prose rather than offering as a line to
    #: run. ``s0ma verify`` appears in the sentence that explains what
    #: ``UNKNOWN`` means, and it takes a target it is not given there. The
    #: set is pinned, so a *new* un-runnable line is a decision somebody
    #: takes rather than something the gate quietly allows.
    NAMED_NOT_RUN = frozenset({"s0ma verify"})

    @staticmethod
    def _commands(text: str) -> list[str]:
        """Every ``s0ma …`` command the block names, in the order it names them."""
        found = re.findall(r"`(s0ma [^`]+)`", text)
        assert found, "the block names no commands at all"
        return found

    @staticmethod
    def _block(project: Path) -> str:
        from s0ma_dsl.adopt.perimeter import (
            AGENTS_BLOCK_BEGIN,
            AGENTS_BLOCK_END,
        )

        written = (project / "AGENTS.md").read_text(encoding="utf-8")
        return written[
            written.index(AGENTS_BLOCK_BEGIN) : written.index(AGENTS_BLOCK_END)
        ]

    def test_every_command_the_block_names_exists(self, project: Path) -> None:
        """The gate that would have caught this milestone's own absence.

        The block promised ``s0ma adopt status`` to whoever opened the
        repository next, and until now there was no such command — a promise
        a reader would have discovered by typing it. Each command's name is
        walked down the live parser's sub-command tree here, so a block that
        names something unbuilt fails before it is written again.
        """
        parser = S0maCLI().build_parser()

        for command in self._commands(self._block(project)):
            words = command.split()
            assert words[0] == "s0ma"
            where = parser
            for word in words[1:]:
                if word.startswith("-"):
                    break
                choices = _subcommands(where)
                if choices is None or word not in choices:
                    break
                where = choices[word]
            else:  # pragma: no cover - the all-words-resolved path
                continue
            assert where is not parser, (
                f"AGENTS.md names `{command}`, which is not a s0ma command"
            )

    def test_every_runnable_line_the_block_names_really_parses(
        self, project: Path
    ) -> None:
        """Naming a command is not enough: the line has to run as written."""
        parser = S0maCLI().build_parser()

        for command in self._commands(self._block(project)):
            if command in self.NAMED_NOT_RUN:
                continue
            try:
                parser.parse_args(command.split()[1:])
            except SystemExit as refused:  # pragma: no cover - the failure path
                raise AssertionError(
                    f"AGENTS.md offers `{command}` as a line to run, and the "
                    f"CLI does not accept it"
                ) from refused

    def test_the_block_still_sends_a_lost_reader_to_this_command(
        self, project: Path
    ) -> None:
        written = (project / "AGENTS.md").read_text(encoding="utf-8")

        assert "s0ma adopt status" in written
        assert "which rung the project is on and the one command to run now" in (
            written
        )

    def test_the_command_the_block_names_really_runs_in_that_project(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert "rung 1 of 4" in _status(project, capsys)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


class TestItIsWiredTheWayTheLedgersNeed:
    """A method on the registered class, classified, and reachable."""

    def test_the_handler_is_a_method_of_the_registered_cli_class(self) -> None:
        from s0ma_dsl.docs_model.providers_cli import _HANDLERS

        assert (
            _HANDLERS["adopt/status"]
            == "s0ma_dsl.cli.main.S0maCLI._cmd_adopt_status"
        )
        assert callable(S0maCLI._cmd_adopt_status)  # noqa: SLF001 - the contract

    def test_it_says_that_it_only_reads(self) -> None:
        from s0ma_dsl.docs_model.providers_cli import _SIDE_EFFECTS

        effects, sentence = _SIDE_EFFECTS["adopt/status"]

        assert effects == ("read",)
        assert "writes nothing at all" in sentence

    def test_the_parser_serves_the_frozen_command_line(self) -> None:
        """§5.3's line, exactly: ``adopt status [PATH] [--format text|json]``."""
        parser = S0maCLI().build_parser()
        status = _subparsers(_subparsers(parser)["adopt"])["status"]

        assert _options(status) == ["--format"]
        assert _positionals(status) == ["path"]
        # argparse folds help text and breaks on hyphens, so the schema
        # string arrives split across two lines; the join is about the
        # rendering, not about the promise.
        assert STATUS_SCHEMA in re.sub(r"-\s+", "-", status.format_help())

    def test_the_bare_usage_line_names_it(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt") == EXIT_USAGE_ERROR
        err = capsys.readouterr().err

        assert "s0ma adopt status [PATH]" in err

    def test_it_resolves_its_own_project_so_rung_zero_is_an_answer(
        self, untouched: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No "operating without project discovery" warning in front of rung 0."""
        text = _status(untouched, capsys)

        assert "without project discovery" not in text
        assert text.startswith("This codebase — rung 0")


def _subcommands(parser: Any) -> dict[str, Any] | None:
    """The sub-parsers of *parser*, or ``None`` when it has none."""
    for action in parser._actions:  # noqa: SLF001 - the parser is the contract
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            return choices
    return None


def _subparsers(parser: Any) -> dict[str, Any]:
    """The sub-parsers of *parser*, by the name a person types."""
    choices = _subcommands(parser)
    if choices is None:
        raise AssertionError("no sub-commands on this parser")
    return choices


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
# G3a — status counts what score and verify count (defect G2-6)
# ---------------------------------------------------------------------------


class TestTheThreeCommandsAgree:
    """One tree, one moment, one number.

    The pilot found ``adopt status`` counting the whole directory while
    ``score`` and ``verify`` counted the perimeter — "455 modules to
    convert" beside "30". A status that is wrong by a factor of fifteen is
    worse than no status, because it is the command somebody runs to find
    out where they are.
    """

    def test_status_counts_only_the_perimeter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _copy_fixture(tmp_path, "multi_pkg_app")
        assert _run(root, "adopt", "init") == EXIT_SUCCESS
        capsys.readouterr()

        assert _run(root, "adopt", "status", "--format", "json") == EXIT_SUCCESS
        status = json.loads(capsys.readouterr().out)
        counts = dict(
            (row["name"], row["count"]) if isinstance(row, dict) else tuple(row)
            for row in status["counts"]
        )

        from s0ma_dsl.adopt.report import build_scan_report

        classification = build_scan_report(root).classification
        assert classification is not None
        assert counts["modules"] == classification["UNKNOWN"]

    def test_the_sample_applications_are_not_modules_to_convert(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _copy_fixture(tmp_path, "multi_pkg_app")
        assert _run(root, "adopt", "init") == EXIT_SUCCESS
        capsys.readouterr()

        assert _run(root, "adopt", "status", "--format", "json") == EXIT_SUCCESS
        status = json.loads(capsys.readouterr().out)
        assert "samples" not in json.dumps(status)

    def test_after_a_conversion_all_three_still_say_one(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """G1's H-10 / pilot G2-9: the source root is not hollow any more.

        One module converted, built and parity-clean. ``adopt status``
        said one converted and ``score`` one componentized, while ``s0ma
        verify --all src`` — the command ``adopt init`` recommends —
        reported ``HOLLOW_MODEL`` and "0 modeled". Three commands, three
        answers, on the product whose claim is self-knowledge.
        """
        assert _run(built, "adopt", "status", "--format", "json") == EXIT_SUCCESS
        status = json.loads(capsys.readouterr().out)
        assert dict(status["counts"])["converted"] == 1

        assert _run(built, "score", "--format", "json") == EXIT_SUCCESS
        score = json.loads(capsys.readouterr().out)
        registration = score["faculties"]["proprioception"]["metrics"]["registration"]
        assert registration["componentized"] == 1

        for target in ("src", "bookshelf_build"):
            assert (
                _run(built, "verify", "--all", str(built / target), "--format", "json")
                == EXIT_SUCCESS
            )
            rows = json.loads(capsys.readouterr().out)
            statuses = [row["status"] for row in rows]
            assert "HOLLOW_MODEL" not in statuses, target
            modeled = [
                row for row in rows
                if row["status"] in {"CLEAN", "CONVERTED", "EDITED", "STALE", "CONFLICT"}
            ]
            assert len(modeled) == 1, f"{target} counts the one module once"

    def test_the_whole_tree_counts_the_converted_module_exactly_once(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`verify --all .` sees the source and the build: still one module."""
        assert (
            _run(built, "verify", "--all", str(built), "--format", "json") == EXIT_SUCCESS
        )
        rows = json.loads(capsys.readouterr().out)
        modeled = [
            row for row in rows
            if row["status"] in {"CLEAN", "CONVERTED", "EDITED", "STALE", "CONFLICT"}
        ]
        assert len(modeled) == 1
        assert modeled[0]["status"] == "CLEAN", "the built .py is the row here"

    def test_the_retrofits_own_records_do_not_break_verify(
        self, built: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Pilot G2-2: `adopt-baseline.s0ma.json` is a record, not IR.

        It matches ``*.s0ma.json`` and carries its own schema, so the IR
        guard refused it and `s0ma verify --all .` exited 1 with
        ``UNSUPPORTED_IR_SCHEMA_MAJOR`` on any project whose source root
        contains the project root — which is what `adopt init` proposes
        on a flat tree.
        """
        from s0ma_dsl.adopt.model import BASELINE_FILENAME

        assert (built / BASELINE_FILENAME).is_file()
        assert _run(built, "verify", "--all", str(built)) == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "UNSUPPORTED_IR_SCHEMA_MAJOR" not in out
        assert "All files are clean." in out

    def test_status_writes_nothing_on_a_multi_package_tree(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _copy_fixture(tmp_path, "multi_pkg_app")
        assert _run(root, "adopt", "init") == EXIT_SUCCESS
        capsys.readouterr()

        before = _tree(root)
        assert _run(root, "adopt", "status") == EXIT_SUCCESS
        capsys.readouterr()
        assert _tree(root) == before
