"""``s0ma adopt draft``: the command a person or an agent actually runs.

Every test here drives the real CLI against a throwaway copy of the
``layered_app`` brownfield fixture that has been through the real
``s0ma adopt init``, so what is asserted is what somebody at a terminal
would see. The fixture tree itself is never written to.

Four promises carry the milestone, and each has its own section below.

**It resolves the way the scan resolves.** A dotted name and a path reach
the same file and write the same bytes, because both go through the one
reading :func:`~s0ma_dsl.adopt.report.build_scan_report` does — so
``adopt scan`` and ``adopt draft`` can never disagree about what a module
is called. Everything that is not a module to draft is refused by name,
with a sentence saying what to type instead.

**It writes one file and touches nothing else.** Every pre-existing file
in the project is hashed before and after: the Python file the draft was
made from is byte-for-byte what it was, and so is everything around it.
``--dry-run`` writes nothing at all, and prints exactly the bytes a real
run would have written.

**It never imports the code it reads** (retrofit rule R-1). The proof is
a module planted in the copy whose import would write a file and then
raise: the draft is written, the file is not there, and the command exits
zero.

**Its drafts are the drafts D2 and D3 pinned.** The draft of
``bookshelf.errors`` is byte-identical to D2's golden, and
``s0ma check --mode migration`` then reports exactly the twenty-one
placeholder refusals D3 predicted against that golden — the two
milestones meet here, through the command, rather than only in a
library test.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.adopt.draft_emit import FALLBACK_LAYER
from s0ma_dsl.adopt.model import DRAFT_INTENT_MARKER, DRAFT_UNPLACED_MARKER
from s0ma_dsl.cli.main import S0maCLI

if TYPE_CHECKING:
    from collections.abc import Iterator

_TESTS_DIR = Path(__file__).parent
_BROWNFIELD = _TESTS_DIR / "fixtures" / "brownfield"
_GOLDEN_DRAFTS = _BROWNFIELD / "_golden" / "drafts"

EXIT_SUCCESS = 0
EXIT_USAGE_ERROR = 2

#: What the draft of ``bookshelf.errors`` costs its author, from D2's
#: own table. Restated rather than imported: this suite reaches the
#: number through the command, and two independent readings that agree
#: are worth more than one reading used twice.
ERRORS_PLACEHOLDERS = 21

#: The same, for ``bookshelf.notifications``, which additionally carries
#: one quarantined block (its ``if TYPE_CHECKING:`` guard reaches a
#: first-party module, so promoting it could close a cycle the guard is
#: holding open).
NOTIFICATIONS_PLACEHOLDERS = 17

#: The two warnings a mid-retrofit project honestly earns, and why each
#: one is right rather than noise. Asserted by name so that a third one
#: appearing is a decision somebody takes rather than a line nobody
#: reads.
#:
#: ``MISSING_PACKAGE`` — ``notifications`` is not a leaf: it requires
#: ``bookshelf.config``, which is still plain Python and so is not a
#: module this build can resolve. That is the whole argument for
#: converting leaves first, said by the checker at the moment somebody
#: ignores it.
#:
#: ``VESTIGIAL_IMPORT`` — ``from typing import TYPE_CHECKING`` runs at
#: load time and so rides in ``requires:``, while the only use of the
#: name is inside the block the harvester quarantined. Once the author
#: has placed that block the entry stops being vestigial; until then the
#: warning is accurate.
NOTIFICATIONS_WARNINGS = ("MISSING_PACKAGE", "VESTIGIAL_IMPORT")


# ---------------------------------------------------------------------------
# A real project in a temporary directory
# ---------------------------------------------------------------------------


def _copy_fixture(tmp_path: Path, name: str = "layered_app") -> Path:
    """Copy one brownfield fixture application into *tmp_path*.

    The fixture tree is read-only as far as this suite is concerned
    (``test_brownfield_fixtures.py`` pins its bytes), and every command
    under test writes, so everything happens to a copy. ``__pycache__``
    is left behind because it is a machine artifact of running the
    fixture's own suite and is not part of the application.
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
    """``layered_app``, copied and taken through rung 1 for real.

    ``s0ma adopt init`` rather than a hand-written ``[tool.s0ma]`` table:
    a draft is written into the perimeter the previous rung declared, so
    a test that wrote that table itself would be proving the two agree
    by construction.
    """
    root = _copy_fixture(tmp_path)
    assert _run(root, "adopt", "init") == EXIT_SUCCESS
    yield root


def _output(capsys: pytest.CaptureFixture[str]) -> tuple[str, str]:
    """This command's stdout and stderr, as one pair."""
    captured = capsys.readouterr()
    return captured.out, captured.err


def _flat(text: str) -> str:
    """*text* with every run of whitespace collapsed to one space.

    The closing message is folded to 88 columns with indented
    continuations, so a sentence a reader sees as one phrase may carry a
    newline in the middle of it. Assertions about what the command
    *says* are made against this, and assertions about what it *writes*
    are made against the bytes.
    """
    return " ".join(text.split())


def _tree(root: Path) -> dict[str, str]:
    """Every file under *root*, by project-relative path and content hash."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _golden(name: str) -> str:
    """One D2 golden draft, read as bytes so its line endings stay visible."""
    return (_GOLDEN_DRAFTS / f"{name}.s0ma").read_bytes().decode("utf-8")


def _check_findings(
    root: Path, capsys: pytest.CaptureFixture[str], *, mode: str = "migration"
) -> dict[str, list[tuple[str, str]]]:
    """Run the real checker and return its findings, by file.

    Each entry is ``(severity, code)`` in the order the checker reported
    it, keyed by the file's base name — the whole point being that this
    is what a person running ``s0ma check`` after a draft actually gets,
    not a validator called in isolation.
    """
    _run(root, "check", "--mode", mode, "--format", "json")
    out, _ = _output(capsys)
    report = json.loads(out)
    findings: dict[str, list[tuple[str, str]]] = {}
    for record in report["by_file"]:
        name = Path(str(record["file"])).name
        rows = findings.setdefault(name, [])
        for group in ("errors", "warnings"):
            rows.extend((group[:-1], str(entry["code"])) for entry in record[group])
    return findings


# ---------------------------------------------------------------------------
# T1 — resolving what somebody typed
# ---------------------------------------------------------------------------


class TestItResolvesTheWayTheScanResolves:
    """A dotted name and a path are two spellings of one answer."""

    def test_a_dotted_name_writes_the_draft_where_the_module_lives(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _output(capsys)

        assert (project / "src" / "bookshelf" / "errors.s0ma").is_file()

    def test_a_path_reaches_the_same_file_with_the_same_bytes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Two projects, two spellings, one draft."""
        by_name = _copy_fixture(tmp_path / "a")
        by_path = _copy_fixture(tmp_path / "b")
        for root in (by_name, by_path):
            assert _run(root, "adopt", "init") == EXIT_SUCCESS
        _output(capsys)

        assert _run(by_name, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        assert (
            _run(by_path, "adopt", "draft", "src/bookshelf/errors.py")
            == EXIT_SUCCESS
        )
        _output(capsys)

        written = "src/bookshelf/errors.s0ma"
        assert (by_name / written).read_bytes() == (by_path / written).read_bytes()

    def test_an_absolute_path_works_too(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = project / "src" / "bookshelf" / "errors.py"

        assert _run(project, "adopt", "draft", str(target)) == EXIT_SUCCESS
        _output(capsys)

        assert (project / "src" / "bookshelf" / "errors.s0ma").is_file()

    def test_a_path_is_read_from_where_you_are_standing(
        self,
        project: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Somebody in ``src/bookshelf`` types ``errors.py`` and means it."""
        monkeypatch.chdir(project / "src" / "bookshelf")

        assert S0maCLI().run(["adopt", "draft", "errors.py"]) == EXIT_SUCCESS
        out, _ = _output(capsys)

        assert out.startswith("Wrote src/bookshelf/errors.s0ma\n")

    def test_a_relative_path_is_not_taken_from_an_unrelated_directory(
        self,
        project: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Standing outside the project, only the project is looked in.

        Otherwise a bare name that happens to match a file where the
        person is standing would be picked up from there and then refused
        for being outside the project, which answers a question nobody
        asked. Read as a module name it gets the refusal that helps.
        """
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "README.md").write_text("", encoding="utf-8", newline="\n")
        monkeypatch.chdir(elsewhere)

        assert (
            S0maCLI().run(["--project-root", str(project), "adopt", "draft", "README.md"])
            == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        assert "no module called README.md was found in this project" in err

    def test_two_runs_write_identical_bytes(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Nothing in a draft depends on the clock, the machine or a set."""
        assert _run(project, "adopt", "draft", "bookshelf.catalog") == EXIT_SUCCESS
        first = (project / "src" / "bookshelf" / "catalog.s0ma").read_bytes()
        assert (
            _run(project, "adopt", "draft", "bookshelf.catalog", "--force")
            == EXIT_SUCCESS
        )
        _output(capsys)

        assert (project / "src" / "bookshelf" / "catalog.s0ma").read_bytes() == first

    def test_the_path_it_prints_is_project_relative_and_forward_slashed(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """NFR-7, on the one line a reader copies out of the output."""
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        out, _ = _output(capsys)

        assert out.startswith("Wrote src/bookshelf/errors.s0ma\n")
        assert "\\" not in out
        assert str(project) not in out


class TestWhatItRefuses:
    """Every refusal exits 2, writes nothing, and says what to do instead."""

    def test_a_test_file_is_refused(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = _tree(project)

        assert _run(project, "adopt", "draft", "tests/test_api.py") == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "is a test" in err
        assert "covered_by" in err
        assert _tree(project) == before

    def test_a_package_marker_is_refused_and_says_when_one_is_not(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``__init__.py`` here holds a docstring, imports and ``__all__``.

        The refusal says so, and says what the perimeter already did with
        it — and it says that an ``__init__.py`` carrying real code is
        drafted like anything else, because that is the case a reader
        will hit next and the role is what decides it.
        """
        assert _run(project, "adopt", "draft", "bookshelf") == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "only marks a package" in err
        assert "package_markers" in err
        assert "does carry real code" in err

    def test_a_generated_artifact_is_refused_as_already_converted(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A transpiled module has a ``.s0ma`` source already."""
        generated = project / "src" / "bookshelf" / "built.py"
        generated.write_text(
            "# s0ma-source-hash: sha256:"
            + "0" * 64
            + "\n# s0ma-output-hash: sha256:"
            + "1" * 64
            + "\n\nVALUE = 1\n",
            encoding="utf-8",
            newline="\n",
        )

        assert (
            _run(project, "adopt", "draft", "src/bookshelf/built.py")
            == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        assert "was generated by s0ma" in err
        assert not (project / "src" / "bookshelf" / "built.s0ma").exists()

    def test_a_path_that_is_not_python_is_refused(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "adopt", "draft", "pyproject.toml") == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        assert "is not a Python file, and a draft is made from Python" in err

    def test_a_file_in_a_directory_the_project_does_not_read_is_refused(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The build directory is the case a reader will actually hit."""
        built = project / "build" / "generated.py"
        built.parent.mkdir()
        built.write_text("VALUE = 1\n", encoding="utf-8", newline="\n")

        assert (
            _run(project, "adopt", "draft", "build/generated.py") == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        assert "does not read as source" in err
        assert not (built.parent / "generated.s0ma").exists()

    def test_a_file_outside_the_project_is_refused(
        self, project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        stranger = tmp_path / "elsewhere.py"
        stranger.write_text("VALUE = 1\n", encoding="utf-8", newline="\n")

        assert _run(project, "adopt", "draft", str(stranger)) == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "is outside this project" in err
        assert not (tmp_path / "elsewhere.s0ma").exists()

    def test_a_name_nothing_matches_offers_the_nearest_ones(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The commonest miss: the flat name for a module inside a package."""
        assert _run(project, "adopt", "draft", "errors") == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "no module called errors was found" in err
        assert "Did you mean bookshelf.errors?" in err
        assert "s0ma adopt scan" in err

    def test_the_suggestion_is_the_same_on_every_run(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Deterministic output includes the output of a refusal."""
        messages: list[str] = []
        for _ in range(2):
            assert _run(project, "adopt", "draft", "catalogue") == EXIT_USAGE_ERROR
            messages.append(_output(capsys)[1])

        assert messages[0] == messages[1]

    def test_an_ambiguous_name_names_both_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Two source roots can carry the same dotted module name."""
        root = tmp_path / "twinned"
        for where in ("src", "lib"):
            package = root / where / "pkg"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8", newline="\n")
            (package / "thing.py").write_text(
                f'"""The {where} one."""\n\n\ndef go() -> str:\n    return "{where}"\n',
                encoding="utf-8",
                newline="\n",
            )
        (root / "pyproject.toml").write_text(
            '[project]\nname = "twinned"\nversion = "0.1.0"\n\n'
            '[tool.s0ma]\nsource_roots = ["src", "lib"]\nmode = "migration"\n'
            'test_roots = []\n',
            encoding="utf-8",
            newline="\n",
        )

        assert _run(root, "adopt", "draft", "pkg.thing") == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "more than one file in this project is called pkg.thing" in err
        assert "lib/pkg/thing.py" in err
        assert "src/pkg/thing.py" in err

    def test_a_tree_with_no_perimeter_is_sent_to_rung_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _copy_fixture(tmp_path)

        assert _run(root, "adopt", "draft", "bookshelf.errors") == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "not a s0ma project yet" in err
        assert "s0ma adopt init" in err
        assert not (root / "src" / "bookshelf" / "errors.s0ma").exists()

    def test_an_unknown_layer_lists_the_real_ones(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "adopt", "draft", "bookshelf.errors", "--layer", "BUSINESS")
            == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        assert "BUSINESS is not one of this language's layers" in err
        for layer in ("DOMAIN", "APPLICATION", "INFRASTRUCTURE", "PRESENTATION"):
            assert layer in err
        assert not (project / "src" / "bookshelf" / "errors.s0ma").exists()

    def test_an_out_directory_outside_the_project_is_refused(
        self, project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(
                project,
                "adopt",
                "draft",
                "bookshelf.errors",
                "--out",
                str(tmp_path / "somewhere"),
            )
            == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        assert "is outside this project" in err
        assert not (tmp_path / "somewhere").exists()


# ---------------------------------------------------------------------------
# T2 — write, or show
# ---------------------------------------------------------------------------


class TestWhatItWrites:
    """One file, in the place the plan's §5.5 names, and nothing else."""

    def test_the_draft_is_byte_for_byte_the_one_the_emitter_pinned(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """D2's golden, reached through the command rather than the library.

        The proposal for this module is ``DOMAIN`` at medium confidence,
        which is not confident enough to write as the answer — and it is
        also the layer the emitter falls back to, so the command names no
        shortlist and the draft asks for the layer in the emitter's own
        words. That is why these bytes are the golden's bytes exactly.
        """
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _output(capsys)

        written = (project / "src" / "bookshelf" / "errors.s0ma").read_bytes()
        assert written.decode("utf-8") == _golden("layered_app/errors")

    def test_a_shortlist_is_named_when_it_says_something_new(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``storage`` is proposed ``INFRASTRUCTURE``, and not confidently.

        So the draft writes the fallback layer and names what the scan
        thought — which is the one difference between a draft written by
        this command and D2's golden, where the emitter was called with
        no scan behind it.
        """
        assert _run(project, "adopt", "draft", "bookshelf.storage") == EXIT_SUCCESS
        _output(capsys)

        text = (project / "src" / "bookshelf" / "storage.s0ma").read_text(
            encoding="utf-8"
        )
        assert f"the draft wrote {FALLBACK_LAYER}" in text
        assert "the candidates are INFRASTRUCTURE" in text
        assert text != _golden("layered_app/storage")

    def test_a_named_layer_is_written_without_a_question(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(
                project,
                "adopt",
                "draft",
                "bookshelf.errors",
                "--layer",
                "INFRASTRUCTURE",
            )
            == EXIT_SUCCESS
        )
        _output(capsys)

        text = (project / "src" / "bookshelf" / "errors.s0ma").read_text(
            encoding="utf-8"
        )
        assert "\n    layer: INFRASTRUCTURE\n" in text
        assert "Also choose this module's layer" not in text
        assert "cell BookshelfError :: INFRASTRUCTURE\n" in text

    def test_a_layer_is_taken_however_it_is_typed(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "adopt", "draft", "bookshelf.errors", "--layer", "domain")
            == EXIT_SUCCESS
        )
        _output(capsys)

        text = (project / "src" / "bookshelf" / "errors.s0ma").read_text(
            encoding="utf-8"
        )
        assert "\n    layer: DOMAIN\n" in text

    def test_a_module_outside_the_source_roots_lands_inside_them(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """§5.5, taken literally, and it is the answer that builds.

        A Python file the project owns but that sits outside its source
        roots is still application code, so it is still drafted — into
        the first source root, mirroring the path it came from. That is
        where a converted module has to live for the build to find it;
        leaving the draft beside its Python would put it somewhere
        ``s0ma build`` never looks. ``--out`` is there for anybody who
        wants it elsewhere.
        """
        loose = project / "scripts"
        loose.mkdir()
        (loose / "release.py").write_text(
            '"""Cut a release."""\n\n\ndef main() -> int:\n    return 0\n',
            encoding="utf-8",
            newline="\n",
        )

        assert _run(project, "adopt", "draft", "scripts/release.py") == EXIT_SUCCESS
        out, _ = _output(capsys)

        assert out.startswith("Wrote src/scripts/release.s0ma\n")
        assert (project / "src" / "scripts" / "release.s0ma").is_file()
        assert (loose / "release.py").is_file()
        assert not (loose / "release.s0ma").exists()

    def test_out_writes_where_it_is_told(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Including into a directory that does not exist yet."""
        assert (
            _run(project, "adopt", "draft", "bookshelf.errors", "--out", "drafts/new")
            == EXIT_SUCCESS
        )
        out, _ = _output(capsys)

        assert out.startswith("Wrote drafts/new/errors.s0ma\n")
        assert (project / "drafts" / "new" / "errors.s0ma").is_file()
        assert not (project / "src" / "bookshelf" / "errors.s0ma").exists()

    def test_the_file_is_utf8_with_lf_endings(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Windows is first-class: these bytes are the same on every platform."""
        assert _run(project, "adopt", "draft", "bookshelf.models") == EXIT_SUCCESS
        _output(capsys)

        written = (project / "src" / "bookshelf" / "models.s0ma").read_bytes()
        assert b"\r" not in written
        assert written.endswith(b"\n")
        written.decode("utf-8")

    def test_no_temporary_file_is_left_behind(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The write is atomic, through a temporary file that is then moved."""
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _output(capsys)

        leftovers = sorted(
            path.name for path in (project / "src" / "bookshelf").iterdir()
            if path.name.endswith(".tmp") or path.name.startswith(".errors")
        )
        assert leftovers == []


class TestItWritesOverNothingByAccident:
    """Two different clashes, two different answers, one flag that lifts both."""

    def test_a_draft_already_there_is_not_written_over(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _output(capsys)
        destination = project / "src" / "bookshelf" / "errors.s0ma"
        authored = destination.read_text(encoding="utf-8").replace(
            f"{DRAFT_INTENT_MARKER} say in one sentence why this exists and who reads it.",
            "The catalogue could not find the title that was asked for.",
        )
        destination.write_text(authored, encoding="utf-8", newline="\n")

        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "is already there" in err
        assert "--force" in err
        assert "--out" in err
        assert destination.read_text(encoding="utf-8") == authored

    def test_force_replaces_it(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        destination = project / "src" / "bookshelf" / "errors.s0ma"
        destination.write_text("stale\n", encoding="utf-8", newline="\n")

        assert (
            _run(project, "adopt", "draft", "bookshelf.errors", "--force")
            == EXIT_SUCCESS
        )
        _output(capsys)

        assert destination.read_text(encoding="utf-8") == _golden("layered_app/errors")

    def test_a_module_converted_already_is_refused_even_somewhere_else(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Module names are flat and unique, so a second draft is a trap."""
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _output(capsys)

        assert (
            _run(project, "adopt", "draft", "bookshelf.errors", "--out", "drafts")
            == EXIT_USAGE_ERROR
        )
        _, err = _output(capsys)

        assert "has already been converted" in err
        assert "src/bookshelf/errors.s0ma" in err
        assert not (project / "drafts").exists()


class TestTheDryRun:
    """What it prints is the file, and it is the only thing it does."""

    def test_it_writes_nothing_anywhere(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = _tree(project)

        assert (
            _run(project, "adopt", "draft", "bookshelf.errors", "--dry-run")
            == EXIT_SUCCESS
        )
        _output(capsys)

        assert _tree(project) == before

    def test_stdout_is_exactly_the_file_a_real_run_writes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        shown = _copy_fixture(tmp_path / "shown")
        written = _copy_fixture(tmp_path / "written")
        for root in (shown, written):
            assert _run(root, "adopt", "init") == EXIT_SUCCESS
        _output(capsys)

        assert (
            _run(shown, "adopt", "draft", "bookshelf.notifications", "--dry-run")
            == EXIT_SUCCESS
        )
        out, err = _output(capsys)
        assert (
            _run(written, "adopt", "draft", "bookshelf.notifications")
            == EXIT_SUCCESS
        )
        _output(capsys)

        assert err == ""
        assert out == (
            written / "src" / "bookshelf" / "notifications.s0ma"
        ).read_text(encoding="utf-8")

    def test_a_dry_run_does_not_mind_a_draft_already_being_there(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Showing is not writing, so nothing is at risk and nothing refuses."""
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _output(capsys)
        before = _tree(project)

        assert (
            _run(project, "adopt", "draft", "bookshelf.errors", "--dry-run")
            == EXIT_SUCCESS
        )
        out, _ = _output(capsys)

        assert out == _golden("layered_app/errors")
        assert _tree(project) == before


class TestTheClosingOutput:
    """What a reader is told once the file is there."""

    def test_it_counts_the_work_left_and_names_the_next_two_commands(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        out, _ = _output(capsys)
        said = _flat(out)

        assert "Wrote src/bookshelf/errors.s0ma" in said
        assert f"It carries {ERRORS_PLACEHOLDERS} placeholders" in said
        assert "s0ma adopt baseline bookshelf.errors" in said
        assert "s0ma check" in said
        assert "Baseline before you delete anything" in said

    def test_it_says_the_python_file_is_still_the_code_that_runs(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        out, _ = _output(capsys)

        assert "src/bookshelf/errors.py has not been touched" in _flat(out)

    def test_quarantined_code_is_counted_in_lines(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "adopt", "draft", "bookshelf.notifications")
            == EXIT_SUCCESS
        )
        out, _ = _output(capsys)
        said = _flat(out)

        assert f"It carries {NOTIFICATIONS_PLACEHOLDERS} placeholders" in said
        assert "It also holds 4 lines of code no declaration could take" in said

    def test_it_never_says_payload_and_never_prints_a_version(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """House voice: written for somebody who does not write Python."""
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        out, _ = _output(capsys)

        assert "payload" not in out.lower()
        assert "soma" not in out.lower().replace("s0ma", "")

    def test_the_baseline_line_goes_away_once_a_baseline_exists(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``adopt baseline`` is E2's command; its record is E1's file.

        Written here rather than waited for, because the closing message
        promises to stop asking for something that has been done, and a
        promise nothing tests is a promise.
        """
        from s0ma_dsl.adopt.parity import capture_baseline, save_baselines

        entry = capture_baseline(project, "bookshelf.errors", "src/bookshelf/errors.py")
        save_baselines(project, {"bookshelf.errors": entry})

        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        out, _ = _output(capsys)
        said = _flat(out)

        assert "s0ma adopt baseline" not in said
        assert "Baseline before you delete anything" not in said
        assert "Run this next:" in said
        assert "s0ma check" in said


# ---------------------------------------------------------------------------
# The two promises the whole milestone rests on
# ---------------------------------------------------------------------------


class TestItTouchesNothingElse:
    """The Python file is read, and that is all that happens to it."""

    def test_every_pre_existing_file_is_byte_for_byte_what_it_was(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = _tree(project)

        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _output(capsys)

        after = _tree(project)
        added = sorted(set(after) - set(before))
        assert added == ["src/bookshelf/errors.s0ma"]
        for name, digest in before.items():
            assert after[name] == digest, name

    def test_the_python_file_is_still_there_after_several_drafts(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for module in ("bookshelf.errors", "bookshelf.config", "bookshelf.models"):
            assert _run(project, "adopt", "draft", module) == EXIT_SUCCESS
        _output(capsys)

        for stem in ("errors", "config", "models"):
            assert (project / "src" / "bookshelf" / f"{stem}.py").is_file()


class TestItNeverImportsTheCodeItReads:
    """Retrofit rule R-1, proved against a module that would tell on it."""

    @staticmethod
    def _plant(project: Path) -> Path:
        """A module whose import writes a file and then raises.

        Planted in the copy, never in the fixture tree: a module that
        cannot be imported would break the fixture application's own
        suite, which later milestones use as their headline proof.
        """
        marker = project / "src" / "bookshelf" / "IMPORT_HAPPENED.txt"
        (project / "src" / "bookshelf" / "booby_trap.py").write_text(
            '"""A module that cannot be imported without leaving evidence."""\n'
            "\n"
            "from __future__ import annotations\n"
            "\n"
            "from pathlib import Path\n"
            "\n"
            "TRAP_NAME = \"booby trap\"\n"
            "\n"
            "Path(__file__).with_name(\"IMPORT_HAPPENED.txt\").write_text(\n"
            '    "imported", encoding="utf-8"\n'
            ")\n"
            "raise RuntimeError(\"this module must never be imported\")\n"
            "\n"
            "\n"
            "def unreachable() -> str:\n"
            '    """Never runs, and still has to be drafted."""\n'
            "    return TRAP_NAME\n",
            encoding="utf-8",
            newline="\n",
        )
        return marker

    def test_the_draft_is_written_and_the_trap_never_springs(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        marker = self._plant(project)

        assert _run(project, "adopt", "draft", "bookshelf.booby_trap") == EXIT_SUCCESS
        _output(capsys)

        assert not marker.exists()
        draft = project / "src" / "bookshelf" / "booby_trap.s0ma"
        assert draft.is_file()
        text = draft.read_text(encoding="utf-8")
        assert "nerve unreachable" in text
        assert DRAFT_UNPLACED_MARKER in text

    def test_even_a_dry_run_leaves_the_trap_alone(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        marker = self._plant(project)

        assert (
            _run(project, "adopt", "draft", "bookshelf.booby_trap", "--dry-run")
            == EXIT_SUCCESS
        )
        out, _ = _output(capsys)

        assert not marker.exists()
        assert out.startswith("# adopt_source: src/bookshelf/booby_trap.py@sha256:")


# ---------------------------------------------------------------------------
# T3 — and then the checker says exactly what D3 said it would
# ---------------------------------------------------------------------------


class TestTheCheckerRefusesTheDraftItJustWrote:
    """The whole point of rule R-5, end to end through two commands."""

    def test_errors_reports_its_placeholders_and_nothing_else(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _output(capsys)

        findings = _check_findings(project, capsys)

        assert findings["errors.s0ma"] == [
            ("error", "ADOPT_PLACEHOLDER_INTENT")
        ] * ERRORS_PLACEHOLDERS

    def test_notifications_reports_its_quarantine_as_well(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            _run(project, "adopt", "draft", "bookshelf.notifications")
            == EXIT_SUCCESS
        )
        _output(capsys)

        findings = _check_findings(project, capsys)

        assert findings["notifications.s0ma"] == (
            [("error", "ADOPT_PLACEHOLDER_INTENT")] * NOTIFICATIONS_PLACEHOLDERS
            + [("error", "ADOPT_UNPLACED_CODE")]
        )

    def test_two_drafts_in_one_project_also_say_what_is_not_converted_yet(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The state the journey is really in, and what it honestly costs.

        With two modules converted the checker has a package to resolve
        against, and it says two more things about ``notifications`` —
        both true, both warnings in migration mode, and both named in
        :data:`NOTIFICATIONS_WARNINGS` with the reason each is right.
        ``errors``, a real leaf, still reports nothing but its own
        placeholders.
        """
        for module in ("bookshelf.errors", "bookshelf.notifications"):
            assert _run(project, "adopt", "draft", module) == EXIT_SUCCESS
        _output(capsys)

        findings = _check_findings(project, capsys)
        rows = findings["notifications.s0ma"]

        assert findings["errors.s0ma"] == [
            ("error", "ADOPT_PLACEHOLDER_INTENT")
        ] * ERRORS_PLACEHOLDERS
        assert [code for severity, code in rows if severity == "error"] == (
            ["ADOPT_PLACEHOLDER_INTENT"] * NOTIFICATIONS_PLACEHOLDERS
            + ["ADOPT_UNPLACED_CODE"]
        )
        assert sorted(
            code for severity, code in rows if severity == "warning"
        ) == sorted(NOTIFICATIONS_WARNINGS)

    def test_the_refusal_names_the_command_that_wrote_the_draft(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """D3's message points back here, so a reader knows where to look."""
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        _output(capsys)

        _run(project, "check", "--mode", "migration")
        out, _ = _output(capsys)

        assert "s0ma adopt draft" in out


# ---------------------------------------------------------------------------
# The wiring the documentation application depends on
# ---------------------------------------------------------------------------


class TestTheCommandIsWiredTheWayTheLedgersNeed:
    """A method on the owning class, classified, and reachable."""

    def test_the_handler_is_a_method_of_the_registered_cli_class(self) -> None:
        from s0ma_dsl.docs_model.providers_cli import _HANDLERS

        assert (
            _HANDLERS["adopt/draft"]
            == "s0ma_dsl.cli.main.S0maCLI._cmd_adopt_draft"
        )
        assert callable(S0maCLI._cmd_adopt_draft)

    def test_it_says_that_it_reads_and_writes(self) -> None:
        from s0ma_dsl.docs_model.providers_cli import _SIDE_EFFECTS

        effects, sentence = _SIDE_EFFECTS["adopt/draft"]
        assert effects == ("read", "write")
        assert "never imported" in sentence

    def test_the_parser_serves_the_frozen_command_line(self) -> None:
        """§5.3's line, exactly: no flag added, renamed or dropped."""
        parser = S0maCLI().build_parser()
        adopt = _subparsers(parser)["adopt"]
        draft = _subparsers(adopt)["draft"]

        options = sorted(
            option
            for action in draft._actions  # noqa: SLF001 - the parser is the contract
            for option in action.option_strings
            if option.startswith("--") and option != "--help"
        )
        assert options == ["--dry-run", "--force", "--layer", "--out"]
        positionals = [
            action.dest
            for action in draft._actions  # noqa: SLF001 - as above
            if not action.option_strings
        ]
        assert positionals == ["module"]

    def test_the_bare_usage_line_names_it(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "adopt") == EXIT_USAGE_ERROR
        _, err = _output(capsys)

        assert "s0ma adopt draft <module or file>" in err


class TestADraftLandsInItsOwnPackage:
    """Pilot defect G2-3, and the miscount it caused (friction F-G3a-4).

    ``adopt draft telemetry.mining`` wrote ``analysis/mining.s0ma`` on
    the pilot's repository — the first source root in alphabetical order
    — and said nothing about having left the package. ``adopt status``
    then read the stray file as a second module and counted 31 where
    there were 30.
    """

    def test_the_draft_is_written_beside_the_module_it_came_from(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
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
        _output(capsys)

        assert _run(root, "adopt", "draft", "metrics.counters") == EXIT_SUCCESS
        out, _ = _output(capsys)

        assert (root / "metrics" / "counters.s0ma").is_file()
        # `evallib` sorts first and used to take every draft in the tree.
        assert not (root / "evallib" / "counters.s0ma").exists()
        assert not (root / "harnesslib" / "counters.s0ma").exists()
        assert out.startswith("Wrote metrics/counters.s0ma\n")

    def test_the_module_count_does_not_move_when_a_module_is_drafted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A drafted module is the same module, not an extra one."""
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
        _output(capsys)

        assert _run(root, "adopt", "status", "--format", "json") == EXIT_SUCCESS
        before = dict(json.loads(_output(capsys)[0])["counts"])

        assert _run(root, "adopt", "draft", "metrics.counters") == EXIT_SUCCESS
        _output(capsys)
        assert _run(root, "adopt", "status", "--format", "json") == EXIT_SUCCESS
        after = dict(json.loads(_output(capsys)[0])["counts"])

        assert after["modules"] == before["modules"]
        assert after["drafted"] == 1

    def test_one_source_root_is_unchanged(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The ordinary project has nothing to choose, and nothing moves."""
        assert _run(project, "adopt", "draft", "bookshelf.errors") == EXIT_SUCCESS
        out, _ = _output(capsys)

        assert (project / "src" / "bookshelf" / "errors.s0ma").is_file()
        assert out.startswith("Wrote src/bookshelf/errors.s0ma\n")


def _subparsers(parser: Any) -> dict[str, Any]:
    """The sub-parsers of *parser*, by the name a person types."""
    for action in parser._actions:  # noqa: SLF001 - the parser is the contract
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            return choices
    raise AssertionError("no sub-commands on this parser")
