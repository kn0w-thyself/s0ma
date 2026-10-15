"""``s0ma adopt scan`` — rung 0 of the retrofit ladder, end to end.

What is pinned here, and why each one is worth a test:

- **The report is a golden.** Two fixture applications, four committed
  files: the whole ``s0ma-adopt-scan@1`` document for each, and the one
  screen a person reads. A scan whose numbers move is either a fixture
  that moved or a reading that changed, and both are things somebody
  should have to look at. Regenerate with
  ``S0MA_UPDATE_ADOPT_GOLDENS=1``; otherwise the comparison is
  byte-for-byte, and the bytes are LF-only with no absolute path in them
  so the same goldens hold on macOS, Linux and Windows.
- **``layered_app`` has no load-time cycle.** ``catalog`` and ``lending``
  refer to each other and the project imports perfectly, because one
  side's import is inside a function. So the report says zero cycles —
  and says, in one sentence, that the pair is one edit away from one and
  the import has to stay where it is. Load-time cycle detection itself
  is B2's, proved on synthetic graphs.
- **One screen.** At most forty lines, however many warnings a tree
  produces, ending in the one command to run next.
- **Zero writes.** The tree is hashed before and after, and the project
  root is listed before and after. Nothing is written, nothing appears —
  no report file, no cache, and no ``__pycache__``, because nothing in
  the scanned tree is ever imported.
- **A scan reports; it never refuses.** A file that will not parse is a
  warning and an exit code of zero. The refusals are about the request.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.adopt.model import SCAN_SCHEMA, dump_json
from s0ma_dsl.adopt.report import (
    MAX_TEXT_LINES,
    WARNING_DEFERRED_CYCLE,
    WARNING_DYNAMIC_EXPORTS,
    WARNING_PARSE_ERROR,
    build_scan_report,
    read_scan,
    render_detail_text,
    render_scan_text,
)
from s0ma_dsl.cli.main import EXIT_SUCCESS, EXIT_USAGE_ERROR, S0maCLI

if TYPE_CHECKING:
    from s0ma_dsl.adopt.model import ScanReport
    from s0ma_dsl.adopt.report import ScanReading

FIXTURES = Path(__file__).parent / "fixtures" / "brownfield"
GOLDEN_DIR = FIXTURES / "_golden" / "scan"

#: Set this to 1 to re-stamp the goldens from the current reading, then
#: read the diff before committing it. The same switch the draft goldens
#: use, so one habit covers the whole ``adopt`` family.
UPDATE_ENV = "S0MA_UPDATE_ADOPT_GOLDENS"

APPS = ("layered_app", "multi_pkg_app", "tiny_app")

#: Skipped when the fixture applications are not on disk — a wheel
#: install carries the package without its test fixtures.
requires_fixtures = pytest.mark.skipif(
    not (FIXTURES / "layered_app").is_dir(),
    reason="brownfield fixture applications are not installed",
)

_IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "*.egg-info")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _copy_app(name: str, destination: Path) -> Path:
    """A private copy of one fixture application, caches left behind."""
    target = destination / name
    shutil.copytree(FIXTURES / name, target, ignore=_IGNORED)
    return target


def _tree_hashes(root: Path) -> dict[str, str]:
    """Every file under *root* as ``relative posix path -> sha256``."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _golden(name: str, text: str) -> None:
    """Compare *text* against the committed golden, or re-stamp it."""
    path = GOLDEN_DIR / name
    if os.environ.get(UPDATE_ENV) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        return
    assert path.is_file(), (
        f"{path.name} has never been stamped. Run the suite once with "
        f"{UPDATE_ENV}=1 and read the diff before committing it."
    )
    assert text == path.read_text(encoding="utf-8"), (
        f"the scan of this fixture no longer matches {path.name}. Either the "
        f"fixture moved or the reading changed — decide which, then re-stamp "
        f"with {UPDATE_ENV}=1."
    )


@pytest.fixture()
def cli() -> S0maCLI:
    return S0maCLI()


@pytest.fixture()
def layered(tmp_path: Path) -> Path:
    return _copy_app("layered_app", tmp_path)


@pytest.fixture()
def tiny(tmp_path: Path) -> Path:
    return _copy_app("tiny_app", tmp_path)


def _report(root: Path) -> ScanReport:
    return build_scan_report(root)


def _reading(root: Path) -> ScanReading:
    """The report together with the scope that says which files it covers."""
    return read_scan(root)


def _flat(text: str) -> str:
    """The rendered screen with its folding undone, for sentence assertions."""
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# The goldens
# ---------------------------------------------------------------------------


@requires_fixtures
@pytest.mark.parametrize("app", APPS)
def test_the_json_report_matches_its_golden(app: str, tmp_path: Path) -> None:
    """The whole document, byte for byte.

    Taken from a copy rather than from the committed fixture, so that a
    reading that did write something could not write it into the
    repository — and so the goldens prove the paths in the report are
    relative to the scanned tree and not to where it happens to sit.
    """
    _golden(f"{app}.json", dump_json(_reading(_copy_app(app, tmp_path)).to_dict()))


@requires_fixtures
@pytest.mark.parametrize("app", APPS)
def test_the_text_report_matches_its_golden(app: str, tmp_path: Path) -> None:
    _golden(f"{app}.txt", render_scan_text(_reading(_copy_app(app, tmp_path))))


@requires_fixtures
@pytest.mark.parametrize("app", APPS)
def test_the_goldens_carry_no_machine_path_and_no_crlf(app: str) -> None:
    """A golden that held only on the machine that stamped it is no golden.

    Both files are read as bytes: no carriage return anywhere, and none
    of the three shapes an absolute path takes (a leading slash on a
    path-looking line, a Windows drive letter, a home directory).
    """
    for name in (f"{app}.json", f"{app}.txt"):
        raw = (GOLDEN_DIR / name).read_bytes()
        assert b"\r" not in raw, name
        text = raw.decode("utf-8")
        assert "/Users/" not in text, name
        assert "/home/" not in text, name
        assert "C:\\" not in text, name
        assert "\\" not in text, name
        assert str(FIXTURES) not in text, name


@requires_fixtures
def test_two_scans_of_one_tree_are_byte_identical(layered: Path) -> None:
    """Determinism, stated over the document people diff."""
    first = dump_json(read_scan(layered).to_dict())
    second = dump_json(read_scan(layered).to_dict())
    assert first == second
    assert first.endswith("}\n")


@requires_fixtures
def test_the_report_declares_its_schema(layered: Path) -> None:
    assert _report(layered).schema == SCAN_SCHEMA


# ---------------------------------------------------------------------------
# The deferred pair — the B4 ruling, in the data and in the prose
# ---------------------------------------------------------------------------


@requires_fixtures
def test_layered_app_has_no_load_time_cycle(layered: Path) -> None:
    """The fixture's `catalog`/`lending` pair is not a cycle, and is not called one.

    ``bookshelf.lending`` imports ``bookshelf.catalog`` at the top of the
    file; ``bookshelf.catalog`` imports ``bookshelf.lending`` inside
    ``Catalog.copies_available``. Only one of those runs when the module
    loads, so the project imports in either order and there is no cycle
    to report. Saying there was one would send somebody off to break an
    import that works.
    """
    report = _report(layered)
    assert report.graph.cycles == ()
    assert report.summary["cycles"] == 0
    assert not [
        warning for warning in report.warnings if warning.code == "ADOPT_SCAN_CYCLE"
    ]


@requires_fixtures
def test_the_function_scoped_import_is_among_the_deferred_edges(
    layered: Path,
) -> None:
    """The edge is not lost, it is filed under the thing it actually is."""
    report = _report(layered)
    assert ("bookshelf.catalog", "bookshelf.lending") in report.graph.deferred_edges
    assert ("bookshelf.catalog", "bookshelf.lending") not in report.graph.edges
    assert ("bookshelf.lending", "bookshelf.catalog") in report.graph.edges


@requires_fixtures
def test_the_pair_is_warned_about_once_and_says_it_must_stay_deferred(
    layered: Path,
) -> None:
    """The one sentence the ruling asks for, on the record and on the screen."""
    reading = _reading(layered)
    report = reading.report
    deferred = [
        warning
        for warning in report.warnings
        if warning.code == WARNING_DEFERRED_CYCLE
    ]
    assert len(deferred) == 1, [warning.message for warning in deferred]
    warning = deferred[0]
    assert warning.module == "bookshelf.catalog"
    assert "bookshelf.lending" in warning.message
    assert "inside a function" in warning.message
    assert "deferred_requires:" in warning.message

    text = render_scan_text(reading)
    assert WARNING_DEFERRED_CYCLE in text
    assert "deferred_requires:" in text


@requires_fixtures
def test_a_type_checking_only_import_is_not_warned_about(layered: Path) -> None:
    """`notifications` imports `models` under TYPE_CHECKING and nothing else.

    That import never runs, so it can never close a circle by being left
    alone, and a warning about it would be a warning about nothing. It is
    still carried as a deferred edge, which is the truth about the file.
    """
    report = _report(layered)
    assert (
        "bookshelf.notifications",
        "bookshelf.models",
    ) in report.graph.deferred_edges
    assert not [
        warning
        for warning in report.warnings
        if warning.code == WARNING_DEFERRED_CYCLE
        and warning.module == "bookshelf.notifications"
    ]


def test_a_real_deferred_pair_is_warned_about_and_a_top_level_one_is_not(
    tmp_path: Path,
) -> None:
    """The rule stated on a tree built for it, three cases at once.

    ``a``/``b`` are the pair. ``c`` imports ``a`` inside a function and
    ``a`` never imports ``c``, so there is no pair and no warning.
    ``d``/``e`` import each other at the top of both files, which is a
    real cycle and belongs in ``cycles``, not here.
    """
    (tmp_path / "a.py").write_text(
        "import b\n\n\ndef go() -> None:\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text(
        "def go() -> None:\n    import a\n\n    return a.go()\n", encoding="utf-8"
    )
    (tmp_path / "c.py").write_text(
        "def go() -> None:\n    import a\n\n    return a.go()\n", encoding="utf-8"
    )
    (tmp_path / "d.py").write_text("import e\n", encoding="utf-8")
    (tmp_path / "e.py").write_text("import d\n", encoding="utf-8")

    report = build_scan_report(tmp_path)
    warned = {
        warning.module
        for warning in report.warnings
        if warning.code == WARNING_DEFERRED_CYCLE
    }
    assert warned == {"b"}
    assert report.graph.cycles == (("d", "e"),)
    assert [
        warning.module
        for warning in report.warnings
        if warning.code == "ADOPT_SCAN_CYCLE"
    ] == ["d"]


# ---------------------------------------------------------------------------
# The one screen
# ---------------------------------------------------------------------------


@requires_fixtures
@pytest.mark.parametrize("app", APPS)
def test_the_text_report_fits_one_screen(app: str, tmp_path: Path) -> None:
    text = render_scan_text(_reading(_copy_app(app, tmp_path)))
    assert len(text.splitlines()) <= MAX_TEXT_LINES, text


@requires_fixtures
@pytest.mark.parametrize("app", APPS)
def test_the_text_report_ends_with_the_next_command(
    app: str, tmp_path: Path
) -> None:
    """The last thing on the screen is the thing to type next."""
    lines = render_scan_text(_reading(_copy_app(app, tmp_path))).splitlines()
    assert any(line.startswith("Next: `s0ma adopt ") for line in lines)
    assert lines[-1].strip()


def test_a_fifty_module_project_with_many_warnings_still_fits(
    tmp_path: Path,
) -> None:
    """The budget is enforced, not hoped for.

    Fifty modules, ten of which will not parse, plus a cycle: far more
    warnings than the screen has room for. The report still fits, and it
    says how many it left out rather than quietly dropping them.
    """
    for index in range(50):
        body = (
            "def broken(\n"
            if index < 10
            else f"VALUE_{index} = {index}\n\n\ndef go() -> int:\n    return VALUE_{index}\n"
        )
        (tmp_path / f"mod_{index:02d}.py").write_text(body, encoding="utf-8")
    (tmp_path / "ring_a.py").write_text("import ring_b\n", encoding="utf-8")
    (tmp_path / "ring_b.py").write_text("import ring_a\n", encoding="utf-8")

    reading = read_scan(tmp_path)
    report = reading.report
    assert report.summary["parse_errors"] == 10
    assert len(report.warnings) > 10

    text = render_scan_text(reading)
    assert len(text.splitlines()) <= MAX_TEXT_LINES, text
    assert "... and " in text
    assert text.splitlines()[-1].startswith("  no application file.") or text.rstrip(
        "\n"
    ).splitlines()[-2].startswith("Next: ")


@requires_fixtures
def test_the_detail_view_prints_one_module_in_full(layered: Path) -> None:
    """`--detail` answers the four questions the summary had no room for."""
    detail = render_detail_text(_report(layered), "bookshelf.catalog")
    assert detail.startswith("bookshelf.catalog — src/bookshelf/catalog.py")
    assert "Proposed layer:" in detail
    assert "Defines (" in detail
    assert "Imports (" in detail
    assert "Imported by (" in detail
    assert "`bookshelf.errors`" in detail


@requires_fixtures
def test_the_detail_view_refuses_a_module_it_never_saw(layered: Path) -> None:
    with pytest.raises(KeyError):
        render_detail_text(_report(layered), "bookshelf.nope")


# ---------------------------------------------------------------------------
# Zero writes (retrofit rule R-2)
# ---------------------------------------------------------------------------


@requires_fixtures
def test_the_scan_writes_nothing_anywhere(layered: Path) -> None:
    """The whole tree, hashed before and after, plus the root's own listing.

    The hash map catches a changed file and the listing catches a new
    one — a report written beside the sources, a ``.s0ma.cache``
    directory, or the ``__pycache__`` that would appear the moment
    anything in the tree was imported.
    """
    before = _tree_hashes(layered)
    before_root = sorted(entry.name for entry in layered.iterdir())

    reading = read_scan(layered)
    render_scan_text(reading)
    render_detail_text(reading.report, "bookshelf.catalog")
    dump_json(reading.to_dict())

    assert _tree_hashes(layered) == before
    assert sorted(entry.name for entry in layered.iterdir()) == before_root
    assert not list(layered.rglob("__pycache__"))
    assert not list(layered.rglob(".s0ma.cache"))


@requires_fixtures
def test_the_command_writes_nothing_either(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same promise, made about the command rather than the function."""
    before = _tree_hashes(layered)
    assert cli.run(["adopt", "scan", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()
    assert _tree_hashes(layered) == before
    assert not list(layered.rglob("__pycache__"))


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


@requires_fixtures
def test_the_command_prints_the_report_and_exits_zero(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.run(["adopt", "scan", str(layered)]) == EXIT_SUCCESS
    out = capsys.readouterr().out
    assert out == render_scan_text(read_scan(layered))


@requires_fixtures
def test_json_format_prints_the_report_and_nothing_else(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stdout is one document an agent can parse without stripping anything."""
    assert (
        cli.run(["adopt", "scan", str(layered), "--format", "json"]) == EXIT_SUCCESS
    )
    out = capsys.readouterr().out
    document = json.loads(out)
    assert document["schema"] == SCAN_SCHEMA
    assert out == dump_json(read_scan(layered).to_dict())


@requires_fixtures
def test_the_detail_option_prints_one_module(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        cli.run(["adopt", "scan", str(layered), "--detail", "bookshelf.errors"])
        == EXIT_SUCCESS
    )
    out = capsys.readouterr().out
    assert out.startswith("bookshelf.errors — src/bookshelf/errors.py")
    assert "Convert in this order" not in out


@requires_fixtures
def test_the_source_root_option_decides_what_the_modules_are_called(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Naming a root scopes the scan to it, and the names stay Python's.

    ``src/bookshelf`` is itself a package, so its modules are still called
    what an ``import`` statement calls them — a root that is a package is
    reached by its own name. What the flag changes is *what is scanned*:
    everything outside the named root is counted, not read.
    """
    assert (
        cli.run(
            [
                "adopt",
                "scan",
                str(layered),
                "--source-root",
                "src/bookshelf",
                "--format",
                "json",
            ]
        )
        == EXIT_SUCCESS
    )
    document = json.loads(capsys.readouterr().out)
    modules = {entry["source"]["module"] for entry in document["modules"]}
    assert "bookshelf.catalog" in modules
    assert all(
        name == "bookshelf" or name.startswith("bookshelf.") for name in modules
    ), modules
    assert document["scope"]["source_roots"] == ["src/bookshelf"]
    assert document["scope"]["origin"] == "given"
    assert document["scope"]["outside_files"] == 5


@requires_fixtures
def test_without_a_path_it_scans_the_project_root_it_was_given(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--project-root` is honoured the way the rest of the family honours it."""
    assert (
        cli.run(["--project-root", str(layered), "adopt", "scan", "--format", "json"])
        == EXIT_SUCCESS
    )
    document = json.loads(capsys.readouterr().out)
    assert "bookshelf.catalog" in {
        entry["source"]["module"] for entry in document["modules"]
    }


def test_it_refuses_a_path_that_is_not_a_directory(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nowhere"
    assert cli.run(["adopt", "scan", str(missing)]) == EXIT_USAGE_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "is not a directory that can be scanned" in captured.err


def test_it_refuses_a_tree_with_no_python_in_it(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "README.txt").write_text("nothing here\n", encoding="utf-8")
    assert cli.run(["adopt", "scan", str(tmp_path)]) == EXIT_USAGE_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no Python files were found" in captured.err
    assert "--source-root" in captured.err


@requires_fixtures
def test_it_refuses_a_detail_module_it_did_not_find(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        cli.run(["adopt", "scan", str(layered), "--detail", "bookshelf.nope"])
        == EXIT_USAGE_ERROR
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no module called bookshelf.nope" in captured.err


def test_no_machine_path_reaches_the_screen(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """NFR-7, on the one command most likely to be run outside a project."""
    (tmp_path / "solo.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert cli.run(["adopt", "scan", str(tmp_path)]) == EXIT_SUCCESS
    out = capsys.readouterr().out
    assert str(tmp_path) not in out
    assert "\\" not in out


# ---------------------------------------------------------------------------
# A scan reports; it never refuses
# ---------------------------------------------------------------------------


def test_a_file_that_will_not_parse_is_a_warning_and_not_a_failure(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "fine.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def oops(\n", encoding="utf-8")

    report = build_scan_report(tmp_path)
    assert report.summary["parse_errors"] == 1
    codes = [warning.code for warning in report.warnings]
    assert WARNING_PARSE_ERROR in codes

    assert cli.run(["adopt", "scan", str(tmp_path)]) == EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "could not be read as Python" in out


def test_a_dunder_all_built_at_run_time_is_reported(tmp_path: Path) -> None:
    """The one fact a census cannot carry, drawn here instead.

    ``dunder_all`` is ``None`` both for a module that declares no
    ``__all__`` and for one that builds it out of a loop. The first is
    ordinary and the second means the scan cannot say what the module
    exports, so only the second is warned about.
    """
    (tmp_path / "quiet.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "declared.py").write_text(
        '__all__ = ["VALUE"]\n\nVALUE = 1\n', encoding="utf-8"
    )
    (tmp_path / "computed.py").write_text(
        "VALUE = 1\n\n__all__ = [name for name in dir() if not name.startswith('_')]\n",
        encoding="utf-8",
    )

    report = build_scan_report(tmp_path)
    warned = {
        warning.module
        for warning in report.warnings
        if warning.code == WARNING_DYNAMIC_EXPORTS
    }
    assert warned == {"computed"}


# ---------------------------------------------------------------------------
# Reconciliation with `s0ma verify`
# ---------------------------------------------------------------------------


_TOOL_TABLE = """
[tool.s0ma]
mode = "migration"
source_roots = ["src"]
build_dir = "build"
bootstrap_files = ["src/bookshelf/__main__.py"]
package_markers = ["src/bookshelf/__init__.py"]
"""


@requires_fixtures
def test_a_tree_with_no_perimeter_has_no_classification(layered: Path) -> None:
    """`None` rather than zeroes: there is nothing to classify against yet."""
    report = _report(layered)
    assert report.classification is None
    assert report.project["has_s0ma_config"] is False


@requires_fixtures
def test_a_s0ma_project_is_classified_the_way_verify_classifies_it(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One classifier, so the two commands cannot report different backlogs.

    The scan's ``UNKNOWN`` is compared against the rows ``s0ma verify``
    itself emits over the same source root — not against a number this
    test worked out, which would only prove the test agrees with itself.
    """
    with (layered / "pyproject.toml").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(_TOOL_TABLE)

    report = build_scan_report(layered)
    assert report.project["has_s0ma_config"] is True
    assert report.project["mode"] == "migration"
    assert report.classification is not None

    assert (
        cli.run(
            [
                "--project-root",
                str(layered),
                "verify",
                str(layered / "src"),
                "--all",
                "--format",
                "json",
            ]
        )
        in (EXIT_SUCCESS, 4)
    )
    rows = json.loads(capsys.readouterr().out)
    counted = {
        status: sum(1 for row in rows if row.get("status") == status)
        for status in ("UNKNOWN", "BOOTSTRAP", "PACKAGE_MARKER", "ADOPTED")
    }
    assert report.classification["UNKNOWN"] == counted["UNKNOWN"]
    assert report.classification["BOOTSTRAP"] == counted["BOOTSTRAP"]
    assert report.classification["PACKAGE_MARKER"] == counted["PACKAGE_MARKER"]
    assert report.classification["ADOPTED"] == counted["ADOPTED"]
    assert counted["UNKNOWN"] > 0


@requires_fixtures
def test_the_next_command_changes_once_the_perimeter_exists(layered: Path) -> None:
    """Rung 0 hands over to rung 1, and then rung 1 hands over to rung 3."""
    assert "s0ma adopt init" in render_scan_text(read_scan(layered))

    with (layered / "pyproject.toml").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(_TOOL_TABLE)

    text = render_scan_text(read_scan(layered))
    assert "Next: `s0ma adopt baseline bookshelf.config`" in text
    # The extra sentence a classified tree earns must not cost the screen.
    assert len(text.splitlines()) <= MAX_TEXT_LINES, text


# ---------------------------------------------------------------------------
# G3a — the scope of a scan, and the numbers agreeing
# ---------------------------------------------------------------------------


@requires_fixtures
def test_the_scan_is_about_the_packages_the_project_declares(
    tmp_path: Path,
) -> None:
    """G2-1: several packages side by side are proposed by name, not as `.`."""
    root = _copy_app("multi_pkg_app", tmp_path)
    reading = _reading(root)

    assert reading.scope.source_roots == ("evallib", "harnesslib", "metrics")
    assert reading.scope.origin == "proposed"
    assert reading.report.perimeter.source_roots == ("evallib", "harnesslib", "metrics")
    assert "." not in reading.report.perimeter.source_roots


@requires_fixtures
def test_the_sample_applications_are_counted_and_never_read(tmp_path: Path) -> None:
    """G2-5: a directory of sample applications is data, and is said to be."""
    root = _copy_app("multi_pkg_app", tmp_path)
    reading = _reading(root)

    censused = {census.source.path for census in reading.report.modules}
    assert not any(path.startswith("samples/") for path in censused)
    assert reading.scope.outside_files == 6
    assert dict(reading.scope.directories) == {"samples": 3, "tests_suite": 3}

    sentence = reading.scope.sentence()
    assert sentence is not None
    assert "samples/ 3" in sentence
    assert sentence in _flat(render_scan_text(reading))


@requires_fixtures
def test_a_collision_inside_a_sample_application_is_not_warned_about(
    tmp_path: Path,
) -> None:
    """The fixture's sample deliberately defines `Anomaly`; it is not our code."""
    root = _copy_app("multi_pkg_app", tmp_path)
    assert (root / "samples" / "demo_one" / "app.py").read_text(
        encoding="utf-8"
    ).count("class Anomaly") == 1
    assert _report(root).warnings == ()


@requires_fixtures
@pytest.mark.parametrize("app", APPS)
def test_an_exempt_entry_point_is_not_offered_for_conversion(
    app: str, tmp_path: Path
) -> None:
    """G2-11: one screen must not declare a file bootstrap and list it to convert."""
    reading = _reading(_copy_app(app, tmp_path))
    text = render_scan_text(reading)
    exempt = reading.report.perimeter.bootstrap_files
    if not exempt:
        pytest.skip(f"{app} declares no bootstrap files")

    modules = {
        census.source.module
        for census in reading.report.modules
        if census.source.path in exempt
    }
    order_rows = [
        line.split()[0]
        for line in text.splitlines()
        if line.startswith("  ") and not line.startswith("    ")
    ]
    assert modules
    assert not modules.intersection(order_rows), text
    assert "bootstrap_files`" in text
    for path in exempt:
        assert path in text


@requires_fixtures
def test_the_headline_and_the_classification_count_the_same_files(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """G2-7: one source of truth, in the text and in the JSON."""
    root = _copy_app("multi_pkg_app", tmp_path)
    assert cli.run(["adopt", "init", str(root)]) == EXIT_SUCCESS
    capsys.readouterr()

    reading = _reading(root)
    classification = reading.report.classification
    assert classification is not None
    assert reading.report.summary["modules"] == sum(classification.values())

    text = _flat(render_scan_text(reading))
    total = sum(classification.values())
    assert f"of the {total} files inside the perimeter" in text
    assert f"{classification['UNKNOWN']} are not converted yet" in text

    assert cli.run(["adopt", "scan", str(root), "--format", "json"]) == EXIT_SUCCESS
    document = json.loads(capsys.readouterr().out)
    assert document["summary"]["modules"] == sum(document["classification"].values())


@requires_fixtures
def test_the_json_carries_no_census_for_a_file_outside_the_perimeter(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """G2-12: what is outside is a count by directory, not a file-by-file census."""
    root = _copy_app("multi_pkg_app", tmp_path)
    assert cli.run(["adopt", "scan", str(root), "--format", "json"]) == EXIT_SUCCESS
    document = json.loads(capsys.readouterr().out)

    paths = {entry["source"]["path"] for entry in document["modules"]}
    assert not any(path.startswith("samples/") for path in paths)
    assert document["scope"]["outside_files"] == 6
    assert document["scope"]["directories_outside"] == [
        {"directory": "samples", "files": 3},
        {"directory": "tests_suite", "files": 3},
    ]
    assert document["summary"]["outside_files"] == 6


@requires_fixtures
def test_the_scope_names_the_test_directories_init_will_declare(
    tmp_path: Path,
) -> None:
    """G2-10's input: the scan knows where the tests are, wherever they sit."""
    assert _reading(_copy_app("multi_pkg_app", tmp_path)).scope.test_directories == (
        "tests_suite",
    )
    assert _reading(_copy_app("layered_app", tmp_path)).scope.test_directories == (
        "tests",
    )
