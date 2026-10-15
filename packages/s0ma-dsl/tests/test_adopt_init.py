"""``s0ma adopt init`` — rung 1 of the retrofit ladder, end to end.

What is pinned here, and why each one is worth a test:

- **Your bytes are still your bytes.** The whole promise of rung 1 is
  that an existing codebase becomes a s0ma project without anything in it
  changing. So the tree is hashed before and after, and exactly two paths
  may differ: ``pyproject.toml``, whose previous bytes must remain a
  strict prefix of its new bytes, and ``AGENTS.md``. Every other file is
  compared hash for hash.
- **Rung 1 sets the perimeter and stops** (retrofit rule R-4). No starter
  module, no tests directory, no ``adopted.s0ma.json``, no build. The
  ``UNKNOWN`` backlog ``s0ma verify`` reports straight afterwards is the
  honest to-convert list, and it is asserted here as such: every
  application module ``UNKNOWN``, the entry point ``BOOTSTRAP``, the
  package marker ``PACKAGE_MARKER``.
- **A project that does not load is never left behind.** A tree whose
  code sits both in the project directory and under a sub-directory
  proposes two source roots, one inside the other, which s0ma refuses.
  That refusal is met *after* the table has been written, so the test
  proves the rollback: the command refuses, and ``pyproject.toml`` is
  byte-identical to what it was.
- **The warning that was exactly wrong.** Both rung 0 and rung 1 are
  pointed at trees that are not s0ma projects yet. "Add ``[tool.s0ma]``
  to pyproject.toml for full functionality" printed in front of the
  command whose job is to do that is noise, so it is asserted absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tomllib
from pathlib import Path

import pytest

from s0ma_dsl.adopt.perimeter import (
    AGENTS_BLOCK_BEGIN,
    AGENTS_BLOCK_END,
    AGENTS_FILENAME,
    PerimeterRefusedError,
    append_preserving,
    apply_perimeter,
    render_agents_block,
)
from s0ma_dsl.adopt.report import build_scan_report
from s0ma_dsl.cli.main import (
    EXIT_NOTHING_VERIFIED,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    S0maCLI,
)

FIXTURES = Path(__file__).parent / "fixtures" / "brownfield"

#: Skipped when the fixture applications are not on disk — a wheel
#: install carries the package without its test fixtures.
requires_fixtures = pytest.mark.skipif(
    not (FIXTURES / "layered_app").is_dir(),
    reason="brownfield fixture applications are not installed",
)

_IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "*.egg-info")

#: The only two paths rung 1 may create or change, ever.
ALLOWED_TO_DIFFER = frozenset({"pyproject.toml", AGENTS_FILENAME})


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


def _assert_only_the_perimeter_changed(
    before: dict[str, str], after: dict[str, str]
) -> None:
    """Fail naming any path that changed, appeared or vanished uninvited."""
    changed = {
        path
        for path in before.keys() | after.keys()
        if before.get(path) != after.get(path)
    }
    assert changed <= ALLOWED_TO_DIFFER, sorted(changed - ALLOWED_TO_DIFFER)


def _table(root: Path) -> dict[str, object]:
    """The ``[tool.s0ma]`` table as TOML actually parses it."""
    with (root / "pyproject.toml").open("rb") as handle:
        document = tomllib.load(handle)
    table = document["tool"]["s0ma"]
    assert isinstance(table, dict)
    return table


@pytest.fixture()
def cli() -> S0maCLI:
    return S0maCLI()


@pytest.fixture()
def layered(tmp_path: Path) -> Path:
    return _copy_app("layered_app", tmp_path)


@pytest.fixture()
def tiny(tmp_path: Path) -> Path:
    return _copy_app("tiny_app", tmp_path)


def _split_tree(root: Path) -> Path:
    """A tree whose code sits both at the top and under ``src/``.

    Left to itself the scan reads this as a ``src`` layout and says in one
    line that ``helper.py`` is outside the perimeter. It becomes the
    rollback path when a reader *names* both roots — ``--source-root .``
    beside ``--source-root src`` — which is a pair s0ma refuses because one
    sits inside the other.
    """
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "helper.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    (root / "src" / "pkg" / "__init__.py").write_text(
        "NAME = 'pkg'\n", encoding="utf-8", newline="\n"
    )
    (root / "src" / "pkg" / "core.py").write_text(
        "def run() -> int:\n    return 1\n", encoding="utf-8", newline="\n"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "split"\nversion = "0.1.0"\n',
        encoding="utf-8",
        newline="\n",
    )
    return root


# ---------------------------------------------------------------------------
# The perimeter it writes
# ---------------------------------------------------------------------------


@requires_fixtures
def test_it_appends_the_perimeter_the_scan_proposed(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The table written is the one rung 0 printed, key for key."""
    proposed = build_scan_report(layered).perimeter

    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()

    table = _table(layered)
    assert table["source_roots"] == list(proposed.source_roots)
    assert table["bootstrap_files"] == list(proposed.bootstrap_files)
    assert table["package_markers"] == list(proposed.package_markers)
    assert table["mode"] == "migration"


@requires_fixtures
def test_the_original_pyproject_bytes_stay_a_strict_prefix(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Appended, never rewritten — the contract the whole command rests on."""
    pyproject = layered / "pyproject.toml"
    before = pyproject.read_bytes()

    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()

    after = pyproject.read_bytes()
    assert after.startswith(before)
    assert len(after) > len(before)
    assert b"\r\n" not in after[len(before) :]


@requires_fixtures
def test_nothing_but_the_two_allowed_files_changes(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No application file, no starter module, no record, no build (R-4)."""
    before = _tree_hashes(layered)

    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()

    _assert_only_the_perimeter_changed(before, _tree_hashes(layered))
    for absent in ("adopted.s0ma.json", "CLAUDE.md", "bookshelf_build"):
        assert not (layered / absent).exists(), absent


@requires_fixtures
def test_a_tree_with_no_pyproject_gets_a_minimal_one(
    cli: S0maCLI, tiny: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Created, not appended — and it loads, which is the only test that counts."""
    assert not (tiny / "pyproject.toml").exists()

    assert cli.run(["adopt", "init", str(tiny)]) == EXIT_SUCCESS
    output = capsys.readouterr().out
    assert "Created pyproject.toml" in output

    with (tiny / "pyproject.toml").open("rb") as handle:
        document = tomllib.load(handle)
    assert document["project"]["name"] == "tiny_app"
    assert document["project"]["requires-python"] == ">=3.11"
    assert document["tool"]["s0ma"]["source_roots"] == ["."]


@requires_fixtures
def test_code_in_the_project_directory_declares_no_test_roots(
    cli: S0maCLI, tiny: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one extra key, and the reason it is not optional.

    ``test_roots`` defaults to ``tests``, and s0ma refuses a test root
    nested inside a source root. A tree whose code *is* the project
    directory would therefore be written a perimeter that will not load
    unless the key is written out as empty. It is, and the project loads.
    """
    assert cli.run(["adopt", "init", str(tiny)]) == EXIT_SUCCESS
    capsys.readouterr()

    assert _table(tiny)["test_roots"] == []

    from s0ma_dsl.project import S0maProject

    project = S0maProject.discover(tiny)
    assert project.test_roots == ()
    assert project.source_roots == (tiny.resolve(),)


@requires_fixtures
def test_a_source_root_override_is_what_gets_declared(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--source-root`` overrides the proposal and still has to load."""
    assert (
        cli.run(
            ["adopt", "init", str(layered), "--source-root", "src/bookshelf"]
        )
        == EXIT_SUCCESS
    )
    capsys.readouterr()

    assert _table(layered)["source_roots"] == ["src/bookshelf"]

    from s0ma_dsl.project import S0maProject

    assert S0maProject.discover(layered).source_roots == (
        (layered / "src" / "bookshelf").resolve(),
    )


# ---------------------------------------------------------------------------
# What the project then thinks of itself
# ---------------------------------------------------------------------------


@requires_fixtures
def test_after_init_the_toolchain_agrees_this_is_a_project(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``s0ma doctor`` exits 0 — the first of the three commands it prints."""
    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()

    assert (
        S0maCLI().run(["--project-root", str(layered), "doctor"]) == EXIT_SUCCESS
    )
    capsys.readouterr()


@requires_fixtures
def test_verify_reports_the_backlog_and_classifies_the_exceptions(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every application module UNKNOWN, and the two exceptions named.

    This is the reading rung 1 exists to produce, and the number the rest
    of the ladder makes fall. It is asserted from ``verify``'s own JSON
    so the classes are the classes verify uses, not a paraphrase.
    """
    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()

    assert (
        S0maCLI().run(
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
        in (EXIT_SUCCESS, 1, 4)
    )
    rows = json.loads(capsys.readouterr().out)
    by_status: dict[str, set[str]] = {}
    for entry in rows:
        if "file" not in entry:  # the HOLLOW_MODEL summary row
            continue
        by_status.setdefault(entry["status"], set()).add(Path(entry["file"]).name)

    assert by_status.get("BOOTSTRAP") == {"__main__.py"}
    assert by_status.get("PACKAGE_MARKER") == {"__init__.py"}
    assert by_status.get("UNKNOWN") == {
        "api.py",
        "catalog.py",
        "cli.py",
        "config.py",
        "errors.py",
        "lending.py",
        "models.py",
        "notifications.py",
        "storage.py",
    }


@requires_fixtures
def test_the_backlog_reads_as_one_line_per_file_and_one_explanation(
    cli: S0maCLI,
    layered: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The screen a retrofitting reader actually meets, and can actually read.

    This is the shape the journey promises — "One line per file … and the
    counts underneath" — and for a while it was not what the tool did: the
    ``UNKNOWN`` remediation was printed under every row, so one long
    sentence arrived nine times and the counts went off the bottom of the
    screen. What is pinned is that property rather than the prose: one row
    per file, the explanation once, and every line short enough to read on
    a narrow terminal without wrapping mid-word.

    Run from inside the project against a relative target, which is how
    the guide and the demo recording run it, so the rows carry the short
    project-relative paths a reader actually sees.
    """
    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()

    monkeypatch.chdir(layered)
    assert S0maCLI().run(["verify", "src", "--all"]) == EXIT_NOTHING_VERIFIED
    lines = capsys.readouterr().out.splitlines()

    unknown_rows = [ln for ln in lines if ln.startswith("  UNKNOWN  ")]
    assert len(unknown_rows) == 9, unknown_rows
    # One line per file: no row carries a trailing explanation of its own.
    for index, line in enumerate(lines):
        if line.startswith("  UNKNOWN  "):
            following = lines[index + 1]
            assert not following.startswith("           ("), (
                f"UNKNOWN rows should stand alone; {line!r} is followed by "
                f"{following!r}"
            )

    # …and the explanation is given once, under the list, ahead of the counts.
    notes = [ln for ln in lines if ln.startswith("UNKNOWN (")]
    assert len(notes) == 1, notes
    assert notes[0].startswith("UNKNOWN (9 files): "), notes[0]
    assert lines.index(notes[0]) > lines.index(unknown_rows[-1])
    assert lines.index(notes[0]) < lines.index(
        "Verified 0 module(s). 1 bootstrap file(s) recognized. "
        "1 package marker(s). 9 unknown."
    )

    # Rule 12: the note says what to do next, in words, without jargon.
    note_text = "\n".join(lines[lines.index(notes[0]) :])
    assert "not a fault" in note_text
    assert "s0ma build" in note_text
    assert "[tool.s0ma].bootstrap_files" in note_text
    assert "payload" not in note_text.lower()

    # Nothing the command prints wraps on a narrow terminal, save the
    # HOLLOW_MODEL row, its explanation and its footer — one block, said
    # once, that this change deliberately does not touch.
    hollow = next(i for i, ln in enumerate(lines) if "  HOLLOW_MODEL " in ln)
    exempt = {hollow, hollow + 1}
    too_long = [
        ln
        for i, ln in enumerate(lines)
        if len(ln) > 96 and i not in exempt and not ln.startswith("HOLLOW_MODEL:")
    ]
    assert too_long == [], too_long


@requires_fixtures
def test_the_backlog_keeps_its_per_row_detail_in_json(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Collapsing the *text* left the machine-readable surface alone.

    ``--format json`` is a contract: every row still carries its own
    ``detail``, spelled exactly as it was before the text output stopped
    repeating it, so a consumer that reads the remediation per file still
    finds it there.
    """
    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()

    assert (
        S0maCLI().run(
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
        == EXIT_NOTHING_VERIFIED
    )
    rows = json.loads(capsys.readouterr().out)
    unknown = [row for row in rows if row["status"] == "UNKNOWN"]
    assert len(unknown) == 9
    assert {row["detail"] for row in unknown} == {
        "no checksum and not declared under [tool.s0ma].bootstrap_files. "
        "Either declare this file under [tool.s0ma].bootstrap_files in "
        "pyproject.toml, or transpile a .s0ma source for it."
    }


@requires_fixtures
def test_a_scan_after_init_carries_the_classification(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rung 0 read on a tree rung 1 has been through now reconciles with verify."""
    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()

    assert (
        S0maCLI().run(["adopt", "scan", str(layered), "--format", "json"])
        == EXIT_SUCCESS
    )
    document = json.loads(capsys.readouterr().out)
    assert document["project"]["has_s0ma_config"] is True
    assert document["project"]["mode"] == "migration"
    assert document["classification"] == {
        "ADOPTED": 0,
        "BOOTSTRAP": 1,
        "COMPONENTIZED": 0,
        "PACKAGE_MARKER": 1,
        "UNKNOWN": 9,
    }


# ---------------------------------------------------------------------------
# AGENTS.md
# ---------------------------------------------------------------------------


def _subparsers(parser: object) -> dict[str, object]:
    """The sub-commands one parser offers; empty when it has none."""
    for action in parser._actions:  # type: ignore[attr-defined]  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return dict(action.choices)
    return {}


#: A bare sub-command word: no leading dash, no ``:`` or ``/``, so a flag
#: and an argument like ``doc:guide/retrofit-existing-codebase`` both stop
#: the walk rather than being mistaken for a deeper sub-command.
_BARE_WORD = re.compile(r"^[a-z][a-z0-9-]*$")

#: Every ``s0ma …`` span the block quotes, read back out of the rendered
#: text rather than typed here, so this test cannot drift from the block
#: it guards.
_QUOTED_COMMAND = re.compile(r"`s0ma ([^`]+)`")


def test_the_agents_block_names_only_commands_that_exist() -> None:
    """Every command the block quotes resolves in the shipped CLI.

    The block is written once into somebody else's repository. It carries
    no publication date, nobody narrates it, and the agent that reads it
    next will simply run what it finds — so a command that is only
    planned reaches that reader as a broken instruction with nothing to
    date it against. This is the test that stops one getting in.

    It was written because one had: for some weeks the block told the
    reader to run ``s0ma adopt status`` before that command was built,
    and the demo recording had to leave ``adopt init --dry-run`` out of
    the retrofit tape rather than put a non-existent command on screen.
    The command exists now and the block names it again; this test is
    what makes that safe to say, and what would have caught it then.

    The guide may name a planned command — it says which are not built
    yet, and a reader takes the whole page in one sitting. This file may
    not.
    """
    block = render_agents_block("some_build")
    quoted = _QUOTED_COMMAND.findall(block)
    assert quoted, "the block quotes no commands at all — has it moved?"

    parser = S0maCLI().build_parser()
    for span in quoted:
        available = _subparsers(parser)
        path: list[str] = []
        for token in span.split():
            if not available or not _BARE_WORD.match(token):
                break
            assert token in available, (
                f"the AGENTS.md block tells the reader to run "
                f"`s0ma {' '.join([*path, token])}`, which the CLI does "
                f"not offer. Name a command that exists today, or drop "
                f"the sentence — this block is written into somebody "
                f"else's repository and nothing there says when it was "
                f"true. Available here: {sorted(available)}"
            )
            path.append(token)
            available = _subparsers(available[token])
        assert path, f"`s0ma {span}` names no command at all"


@requires_fixtures
def test_an_existing_agents_file_is_appended_to_never_rewritten(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Somebody else's standing rules are still there, first, unchanged."""
    agents = layered / AGENTS_FILENAME
    house = "# bookshelf\n\nHouse rule: run the tests before you push.\n"
    agents.write_text(house, encoding="utf-8", newline="\n")

    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()

    written = agents.read_text(encoding="utf-8")
    assert written.startswith(house)
    assert written.count(AGENTS_BLOCK_BEGIN) == 1
    assert written.count(AGENTS_BLOCK_END) == 1
    for promised in (
        "s0ma docs show doc:guide/retrofit-existing-codebase",
        "bookshelf_build/",
        "s0ma adopt status",
    ):
        assert promised in written, promised


@requires_fixtures
def test_the_block_is_recognised_on_a_second_run(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tree whose table was removed keeps the one block it already has.

    The second run of the command itself refuses (the tree is a s0ma
    project by then), so the way to reach this path is the way somebody
    really reaches it: the table was taken out to start again. The block
    must not be appended twice.
    """
    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()
    agents_after_first = (layered / AGENTS_FILENAME).read_bytes()

    pyproject = layered / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(
        text.split("[tool.s0ma]")[0].rstrip() + "\n", encoding="utf-8", newline="\n"
    )

    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    output = capsys.readouterr().out
    assert "already carries the s0ma block" in output
    assert (layered / AGENTS_FILENAME).read_bytes() == agents_after_first


# ---------------------------------------------------------------------------
# Refusals — exit 2, nothing written
# ---------------------------------------------------------------------------


@requires_fixtures
def test_a_second_run_refuses_and_changes_nothing(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Idempotence, stated as a refusal that says where to go instead."""
    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()
    after_first = _tree_hashes(layered)

    assert cli.run(["adopt", "init", str(layered)]) == EXIT_USAGE_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "already a s0ma project" in captured.err
    assert "s0ma adopt scan" in captured.err
    assert _tree_hashes(layered) == after_first


def test_it_refuses_a_path_that_is_not_a_directory(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nowhere"
    assert cli.run(["adopt", "init", str(missing)]) == EXIT_USAGE_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "is not a directory" in captured.err
    assert not missing.exists()


def test_it_refuses_a_tree_with_no_python_in_it(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "README.txt").write_text("nothing here\n", encoding="utf-8")
    before = _tree_hashes(tmp_path)

    assert cli.run(["adopt", "init", str(tmp_path)]) == EXIT_USAGE_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no Python files were found" in captured.err
    assert _tree_hashes(tmp_path) == before


def test_it_refuses_a_pyproject_that_is_not_valid_toml(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refused before anything is read from the rest of the tree."""
    (tmp_path / "pyproject.toml").write_text(
        "[project\nname = broken\n", encoding="utf-8", newline="\n"
    )
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    before = _tree_hashes(tmp_path)

    assert cli.run(["adopt", "init", str(tmp_path)]) == EXIT_USAGE_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not valid TOML" in captured.err
    assert _tree_hashes(tmp_path) == before


def test_it_refuses_a_tool_s0ma_that_is_not_a_table(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Appending under a non-table ``tool.s0ma`` would write invalid TOML."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool]\ns0ma = "off"\n', encoding="utf-8", newline="\n"
    )
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    before = _tree_hashes(tmp_path)

    assert cli.run(["adopt", "init", str(tmp_path)]) == EXIT_USAGE_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "is not a table" in captured.err
    assert _tree_hashes(tmp_path) == before


def test_overlapping_source_roots_roll_the_pyproject_back(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one refusal that happens *after* a write, and undoes it exactly.

    Code in the project directory and code under ``src/`` propose two
    source roots, one inside the other. s0ma refuses that pair at load
    time — which is only discovered once the table has been written — so
    the table is taken back out, byte for byte, and the command refuses.
    """
    root = _split_tree(tmp_path)
    before = _tree_hashes(root)

    assert (
        cli.run(
            ["adopt", "init", str(root), "--source-root", ".", "--source-root", "src"]
        )
        == EXIT_USAGE_ERROR
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "does not load" in captured.err
    assert "OVERLAPPING_DISCOVERY_ROOTS" in captured.err
    assert "--source-root" in captured.err

    assert _tree_hashes(root) == before
    assert not (root / AGENTS_FILENAME).exists()


def test_a_dry_run_refuses_exactly_where_the_real_run_refuses(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """G2-8: the safe command must not approve what the real one rejects."""
    root = _split_tree(tmp_path)
    before = _tree_hashes(root)
    argv = ["adopt", "init", str(root), "--source-root", ".", "--source-root", "src"]

    assert cli.run([*argv, "--dry-run"]) == EXIT_USAGE_ERROR
    dry = capsys.readouterr()
    assert dry.out == ""
    assert "does not load" in dry.err
    assert "OVERLAPPING_DISCOVERY_ROOTS" in dry.err
    assert _tree_hashes(root) == before

    assert cli.run(argv) == EXIT_USAGE_ERROR
    real = capsys.readouterr()
    assert real.err == dry.err
    assert _tree_hashes(root) == before


def test_a_tree_with_code_beside_src_is_scoped_rather_than_refused(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """G2-1: the perimeter written is the perimeter decided, and it loads."""
    root = _split_tree(tmp_path)

    assert cli.run(["adopt", "scan", str(root)]) == EXIT_SUCCESS
    scanned = capsys.readouterr().out
    assert "source roots    src" in scanned
    assert "1 other Python file is outside them" in scanned

    assert cli.run(["adopt", "init", str(root)]) == EXIT_SUCCESS
    written = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'source_roots = ["src"]' in written

    from s0ma_dsl.project import S0maProject

    assert S0maProject.discover(root).source_roots == ((root / "src").resolve(),)


def test_the_rollback_also_removes_a_pyproject_it_created(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing was there before, so nothing is there after."""
    root = _split_tree(tmp_path)
    (root / "pyproject.toml").unlink()
    before = _tree_hashes(root)

    assert (
        cli.run(
            ["adopt", "init", str(root), "--source-root", ".", "--source-root", "src"]
        )
        == EXIT_USAGE_ERROR
    )
    capsys.readouterr()

    assert not (root / "pyproject.toml").exists()
    assert _tree_hashes(root) == before


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


@requires_fixtures
def test_dry_run_prints_both_and_writes_neither(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exactly what a real run would write, and not one byte of it written."""
    before = _tree_hashes(layered)

    assert cli.run(["adopt", "init", str(layered), "--dry-run"]) == EXIT_SUCCESS
    output = capsys.readouterr().out

    assert _tree_hashes(layered) == before
    assert "Dry run — nothing was written." in output
    assert "[tool.s0ma]" in output
    assert 'source_roots = ["src"]' in output
    assert 'mode = "migration"' in output
    assert AGENTS_BLOCK_BEGIN in output
    assert AGENTS_BLOCK_END in output

    # And what it printed is what a real run then writes.
    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()
    written = (layered / "pyproject.toml").read_text(encoding="utf-8")
    table = written.split("[tool.s0ma]")[1]
    for line in table.strip().splitlines():
        assert line in output, line


@requires_fixtures
def test_dry_run_on_a_tree_with_no_pyproject_says_it_would_create_one(
    cli: S0maCLI, tiny: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _tree_hashes(tiny)

    assert cli.run(["adopt", "init", str(tiny), "--dry-run"]) == EXIT_SUCCESS
    output = capsys.readouterr().out

    assert "Would create pyproject.toml" in output
    assert _tree_hashes(tiny) == before


# ---------------------------------------------------------------------------
# The closing output
# ---------------------------------------------------------------------------


@requires_fixtures
def test_it_ends_with_the_three_commands_and_what_unknown_means(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reader is told what to run and what they are about to see."""
    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    output = capsys.readouterr().out

    assert "s0ma doctor" in output
    assert "s0ma verify --all src" in output
    assert "s0ma score" in output
    assert "UNKNOWN" in output
    assert "not a fault" in output
    assert "No application file was touched" in output
    assert "payload" not in output.lower()


@requires_fixtures
def test_no_printed_path_is_absolute_or_back_slashed(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """NFR-7: what it prints is about the project, not about this machine."""
    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    output = capsys.readouterr().out

    assert str(layered) not in output
    assert "\\" not in output


# ---------------------------------------------------------------------------
# The discovery warning that was exactly wrong
# ---------------------------------------------------------------------------


@requires_fixtures
@pytest.mark.parametrize("subcommand", ["scan", "init"])
def test_neither_rung_warns_about_the_thing_it_is_there_to_do(
    subcommand: str, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rungs 0 and 1 are pointed at trees that are not projects yet.

    "Operating without project discovery. Add ``[tool.s0ma]`` to
    pyproject.toml for full functionality" in front of the command whose
    whole job is to do that is noise at best and a contradiction at
    worst, so both commands self-manage resolution and the warning is
    asserted absent — on the plain tree and with ``--project-root``.
    """
    assert S0maCLI().run(["adopt", subcommand, str(layered)]) == EXIT_SUCCESS
    assert "without project discovery" not in capsys.readouterr().err


@requires_fixtures
def test_project_root_is_still_honoured_without_a_resolved_project(
    tiny: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Self-managing resolution must not cost ``--project-root`` its meaning."""
    assert (
        S0maCLI().run(["--project-root", str(tiny), "adopt", "init"])
        == EXIT_SUCCESS
    )
    captured = capsys.readouterr()
    assert "without project discovery" not in captured.err
    assert (tiny / "pyproject.toml").is_file()


@requires_fixtures
def test_adopt_file_still_resolves_the_project(
    layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The rest of the family is untouched by the self-management carve-out.

    ``adopt file`` writes project state and must still refuse without a
    project — which it can only do if the CLI still resolves one for it.
    """
    assert (
        S0maCLI().run(
            [
                "--project-root",
                str(layered),
                "adopt",
                "file",
                str(layered / "src" / "bookshelf" / "errors.py"),
                "--description",
                "staying plain for now",
            ]
        )
        == EXIT_USAGE_ERROR
    )
    assert "no [tool.s0ma] project resolved" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The mechanism, on its own
# ---------------------------------------------------------------------------


def test_append_preserving_keeps_the_original_bytes_whatever_they_end_with(
    tmp_path: Path,
) -> None:
    """Three endings, one rule: what was there is still there, first."""
    cases = {
        "trailing-newline.txt": b"alpha\n",
        "no-trailing-newline.txt": b"alpha",
        "crlf.txt": b"alpha\r\nbeta\r\n",
    }
    for name, original in cases.items():
        path = tmp_path / name
        path.write_bytes(original)
        append_preserving(path, "added\n")
        after = path.read_bytes()
        assert after.startswith(original), name
        assert after.endswith(b"added\n"), name
        assert after[len(original) :].count(b"\r") == 0, name


def test_append_preserving_does_not_open_an_empty_file_with_blank_lines(
    tmp_path: Path,
) -> None:
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    append_preserving(path, "first\n")
    assert path.read_bytes() == b"first\n"


def test_apply_perimeter_refuses_rather_than_half_writing(tmp_path: Path) -> None:
    """The mechanism raises; it never returns a partly-applied perimeter."""
    root = _split_tree(tmp_path)
    before = _tree_hashes(root)
    suggestion = build_scan_report(root, [".", "src"]).perimeter

    with pytest.raises(PerimeterRefusedError) as refusal:
        apply_perimeter(root, suggestion, dry_run=False)

    assert "does not load" in str(refusal.value)
    assert _tree_hashes(root) == before


def test_apply_perimeter_dry_run_refuses_the_same_perimeter(tmp_path: Path) -> None:
    """The dry run loads a copy elsewhere, so it reaches the same verdict."""
    root = _split_tree(tmp_path)
    before = _tree_hashes(root)
    suggestion = build_scan_report(root, [".", "src"]).perimeter

    with pytest.raises(PerimeterRefusedError) as refusal:
        apply_perimeter(root, suggestion, dry_run=True)

    assert "does not load" in str(refusal.value)
    assert _tree_hashes(root) == before


def test_apply_perimeter_dry_run_touches_nothing(tmp_path: Path) -> None:
    root = _split_tree(tmp_path)
    before = _tree_hashes(root)
    suggestion = build_scan_report(root).perimeter

    result = apply_perimeter(root, suggestion, dry_run=True)

    assert result.dry_run is True
    assert result.written == ()
    assert "[tool.s0ma]" in result.table
    assert _tree_hashes(root) == before


# ---------------------------------------------------------------------------
# G3a — the perimeter a reader asked for, and one that always loads
# ---------------------------------------------------------------------------


def _pilot_shaped_tree(root: Path) -> Path:
    """The shape the first real pilot met: packages side by side, plus data.

    Four top-level packages, no ``src/``, a large directory of sample
    applications that are input rather than code, and a test suite in a
    directory that is not called ``tests``. This is the tree that made
    ``adopt init`` refuse the perimeter its own scan had proposed.
    """
    for package in ("harness", "evaluators", "telemetry", "analysis"):
        (root / package).mkdir(parents=True)
        (root / package / "__init__.py").write_text(
            f'"""{package}."""\n', encoding="utf-8", newline="\n"
        )
    (root / "harness" / "runner.py").write_text(
        "from telemetry.mining import dig\n\n\ndef run():\n    return dig()\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "harness" / "__main__.py").write_text(
        'def main():\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
        encoding="utf-8",
        newline="\n",
    )
    (root / "telemetry" / "mining.py").write_text(
        "def dig():\n    return 1\n", encoding="utf-8", newline="\n"
    )
    (root / "evaluators" / "judge.py").write_text(
        "from harness.runner import run\n\n\nVERDICT = run\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "analysis" / "report.py").write_text(
        "from evaluators.judge import VERDICT\n\n\nSUMMARY = VERDICT\n",
        encoding="utf-8",
        newline="\n",
    )
    for sample in ("F1", "F2"):
        (root / "fixtures" / sample / "tree").mkdir(parents=True)
        (root / "fixtures" / sample / "tree" / "app.py").write_text(
            f'NAME = "{sample}"\n', encoding="utf-8", newline="\n"
        )
    (root / "tests_harness").mkdir()
    (root / "tests_harness" / "test_runner.py").write_text(
        "def test_run():\n    assert True\n", encoding="utf-8", newline="\n"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "pilot-bench"\nversion = "0.1.0"\n\n'
        '[tool.pytest.ini_options]\ntestpaths = ["tests_harness"]\n\n'
        '[tool.setuptools]\npackages = ["harness", "evaluators", "telemetry", "analysis"]\n',
        encoding="utf-8",
        newline="\n",
    )
    return root


def test_the_roots_a_reader_names_are_the_roots_that_get_written(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """G2-1: four sibling packages, and `.` is never quietly added beside them."""
    root = _pilot_shaped_tree(tmp_path)

    assert (
        cli.run(
            [
                "adopt", "init", str(root),
                "--source-root", "harness",
                "--source-root", "evaluators",
                "--source-root", "telemetry",
                "--source-root", "analysis",
            ]
        )
        == EXIT_SUCCESS
    )
    capsys.readouterr()

    table = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert table["tool"]["s0ma"]["source_roots"] == [
        "harness",
        "evaluators",
        "telemetry",
        "analysis",
    ]

    from s0ma_dsl.project import S0maProject

    project = S0maProject.discover(root)
    assert len(project.source_roots) == 4


def test_the_scan_proposes_the_packages_and_init_takes_them(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """G2-1, unaided: nobody has to work out the perimeter by hand."""
    root = _pilot_shaped_tree(tmp_path)

    assert cli.run(["adopt", "scan", str(root)]) == EXIT_SUCCESS
    scanned = capsys.readouterr().out
    assert "source roots    analysis, evaluators, harness, telemetry" in scanned
    assert "fixtures/ 2" in " ".join(scanned.split())

    assert cli.run(["adopt", "init", str(root)]) == EXIT_SUCCESS
    capsys.readouterr()
    table = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert table["tool"]["s0ma"]["source_roots"] == [
        "analysis",
        "evaluators",
        "harness",
        "telemetry",
    ]


def test_init_writes_the_real_test_directories(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """G2-10: a test suite that is named is a test suite that can stop being UNKNOWN."""
    root = _pilot_shaped_tree(tmp_path)
    assert cli.run(["adopt", "init", str(root)]) == EXIT_SUCCESS
    capsys.readouterr()

    table = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert table["tool"]["s0ma"]["test_roots"] == ["tests_harness"]


@requires_fixtures
def test_a_flat_tree_still_gets_the_empty_test_roots_and_its_reason(
    cli: S0maCLI, tiny: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """C1's rule survives, for the one case it was written for."""
    assert cli.run(["adopt", "init", str(tiny)]) == EXIT_SUCCESS
    capsys.readouterr()
    written = (tiny / "pyproject.toml").read_text(encoding="utf-8")
    assert "test_roots = []" in written
    assert "counts as" in written


@requires_fixtures
def test_a_src_layout_leaves_the_default_test_root_unsaid(
    cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing is written where the default already says the same thing."""
    assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
    capsys.readouterr()
    assert "test_roots" not in (layered / "pyproject.toml").read_text(encoding="utf-8")


@requires_fixtures
@pytest.mark.parametrize(
    "app", ["layered_app", "multi_pkg_app", "tiny_app"]
)
def test_whatever_the_scan_proposes_init_accepts_and_the_project_loads(
    cli: S0maCLI, app: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The property this milestone exists for, over every fixture we have.

    ``suggest_perimeter`` must never propose a perimeter the project
    loader refuses. There is no shape of tree for which the first writing
    command is allowed to reject its own advice.
    """
    root = _copy_app(app, tmp_path)
    assert cli.run(["adopt", "scan", str(root)]) == EXIT_SUCCESS
    proposed = build_scan_report(root).perimeter.source_roots
    capsys.readouterr()

    assert cli.run(["adopt", "init", str(root), "--dry-run"]) == EXIT_SUCCESS
    capsys.readouterr()
    assert cli.run(["adopt", "init", str(root)]) == EXIT_SUCCESS
    capsys.readouterr()

    from s0ma_dsl.project import S0maProject

    project = S0maProject.discover(root)
    assert tuple(
        path.resolve().relative_to(root.resolve()).as_posix() or "."
        for path in project.source_roots
    ) == proposed


def test_the_pilot_shaped_tree_also_survives_the_property(
    cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same property on the shape that broke it in the field."""
    root = _pilot_shaped_tree(tmp_path)
    proposed = build_scan_report(root).perimeter.source_roots

    assert cli.run(["adopt", "init", str(root), "--dry-run"]) == EXIT_SUCCESS
    capsys.readouterr()
    assert cli.run(["adopt", "init", str(root)]) == EXIT_SUCCESS
    capsys.readouterr()

    from s0ma_dsl.project import S0maProject

    project = S0maProject.discover(root)
    assert tuple(
        path.resolve().relative_to(root.resolve()).as_posix()
        for path in project.source_roots
    ) == proposed


# ---------------------------------------------------------------------------
# G3b — what belongs in version control (G1's H-13)
# ---------------------------------------------------------------------------


class TestInitSaysWhichFilesBelongInGit:
    """The first command that writes into a repository answers the question.

    Nothing did, so the trial's agent wrote a ``.gitignore`` of its own
    and reasoned out each line. This says it once, where the reader is
    looking — and still writes nothing it was not asked to.
    """

    def test_the_records_are_committed_and_the_caches_are_not(
        self, cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
        out = capsys.readouterr().out
        said = " ".join(out.split())

        assert "What to keep in version control" in said
        assert "adopt-baseline.s0ma.json and adopted.s0ma.json" in said
        assert "once you have built something, commit that too" in said
        assert "  bookshelf_build/.s0ma.cache/" in out
        assert "  __pycache__/" in out

    def test_it_does_not_talk_about_the_build_directory_as_though_it_were_there(
        self, cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """G3c: this is printed four commands before anything is built.

        The trial agent read "commit the build directory and ignore
        `<build>/.s0ma.cache/`", went looking for both, found neither and
        stopped to check the line was not a typo. Advice about a file
        that does not exist yet has to say so at the moment it is read.
        The two ignore lines stay exactly as they were, so they can still
        be pasted straight into a `.gitignore`.
        """
        assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
        out = capsys.readouterr().out
        said = " ".join(out.split())

        assert not (layered / "bookshelf_build").exists(), "nothing is built yet"
        assert "There is no bookshelf_build/ yet" in said
        assert "the first of them appears with that build" in said
        assert out.rstrip("\n").endswith(
            "  bookshelf_build/.s0ma.cache/\n  __pycache__/"
        ), "the lines to paste are the last thing on the screen, and are two lines"

    def test_it_writes_no_gitignore(
        self, cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.run(["adopt", "init", str(layered)]) == EXIT_SUCCESS
        capsys.readouterr()

        assert not (layered / ".gitignore").exists()

    def test_a_dry_run_does_not_talk_about_files_it_did_not_write(
        self, cli: S0maCLI, layered: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.run(["adopt", "init", str(layered), "--dry-run"]) == EXIT_SUCCESS
        out = capsys.readouterr().out

        assert "What to keep in version control" not in out
