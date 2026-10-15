"""The parity-baseline store — one committed record, deterministic bytes (E1).

``adopt-baseline.s0ma.json`` is the retrofit family's one irreplaceable
artifact. Every other file the toolchain writes can be regenerated from
source; a baseline cannot, because the source it describes is exactly
what the conversion deletes. These tests hold the store to that
standard:

- **One file, at the project root, and nothing else.** Capturing reads;
  only saving writes.
- **Byte-for-byte deterministic.** Sorted keys, two-space indent, one
  trailing newline, LF endings, no timestamps — so re-capturing an
  unchanged module diffs empty, and the same capture on macOS, Linux and
  Windows produces the same bytes.
- **Refusals that help.** Capturing a module whose Python file is
  already gone is the mistake this tool exists to prevent, so its
  message has to say what happened, that the baseline had to come first,
  and how to get back to a state where it can be taken. A record that
  cannot be read is never answered with "delete it".
- **The shape is the contract.** ``{schema, modules: {<dotted name>:
  {source_path, source_hash, captured_surface}}}``, and a stored surface
  reads back as the surface that was captured.
"""

from __future__ import annotations

import json
from textwrap import dedent
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.adopt.model import BASELINE_FILENAME, BASELINE_SCHEMA, ModuleSurface
from s0ma_dsl.adopt.parity import (
    BASELINE_MODULES_KEY,
    BaselineEntry,
    BaselineRecordError,
    baseline_record_path,
    capture_baseline,
    load_baselines,
    save_baselines,
    surface_from_dict,
)
from s0ma_dsl.adopt.surface import static_surface
from s0ma_dsl.adoption import compute_adopted_hash

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures written inline — a small project, one module in it
# ---------------------------------------------------------------------------

_LENDING = '''
"""Lending rules."""

__all__ = ["Loan", "borrow"]

DAYS = 14


class Loan:
    """One loan."""

    def __init__(self, book: str) -> None:
        """Start a loan."""

    def extend(self, days: int = DAYS) -> bool: ...


def borrow(book: str, *, notify: bool = True) -> Loan:
    """Borrow a book."""
'''

_ERRORS = '''
"""Lending errors."""


class LoanRefused(Exception):
    """The book cannot be lent."""
'''

_MODELS = '''
"""The nouns."""

from dataclasses import dataclass

LIMIT: int = 5


@dataclass(frozen=True)
class Book:
    """A title."""

    title: str
    copies: int = 1

    def read(self) -> str: ...
'''

_MODULE = "bookshelf.lending"
_RELATIVE = "src/bookshelf/lending.py"
_MODELS_MODULE = "bookshelf.models"


def _project(tmp_path: Path) -> Path:
    """A project root with ``src/bookshelf/lending.py`` and ``errors.py`` in it."""
    package = tmp_path / "src" / "bookshelf"
    package.mkdir(parents=True)
    (package / "lending.py").write_text(dedent(_LENDING), encoding="utf-8", newline="\n")
    (package / "errors.py").write_text(dedent(_ERRORS), encoding="utf-8", newline="\n")
    return tmp_path


def _snapshot(root: Path) -> dict[str, bytes]:
    """Every file under *root*, by relative path, for a written-nothing proof."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _captured(root: Path) -> BaselineEntry:
    return capture_baseline(root, _MODULE, _RELATIVE)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def test_capture_records_the_surface_its_path_and_its_hash(tmp_path: Path) -> None:
    root = _project(tmp_path)
    entry = _captured(root)

    assert entry.module == _MODULE
    assert entry.source_path == _RELATIVE
    assert entry.source_hash == compute_adopted_hash(root / _RELATIVE)
    assert entry.surface == static_surface(root / _RELATIVE, module=_MODULE)
    assert [item.name for item in entry.surface.entries] == [
        "Loan",
        "Loan.__init__",
        "Loan.extend",
        "borrow",
    ]


def test_capture_accepts_an_absolute_path_and_records_it_relative(tmp_path: Path) -> None:
    """Records are committed and read on other machines — never absolute."""
    root = _project(tmp_path)
    entry = capture_baseline(root, _MODULE, root / "src" / "bookshelf" / "lending.py")
    assert entry.source_path == _RELATIVE


def test_capture_writes_nothing(tmp_path: Path) -> None:
    """Capturing is a read; saving is the only thing that touches the tree."""
    root = _project(tmp_path)
    before = _snapshot(root)
    _captured(root)
    assert _snapshot(root) == before


def test_capture_refuses_a_file_that_is_already_gone(tmp_path: Path) -> None:
    """The mistake this tool exists to prevent, answered in plain words."""
    root = _project(tmp_path)
    (root / _RELATIVE).unlink()

    with pytest.raises(BaselineRecordError) as caught:
        _captured(root)

    message = str(caught.value)
    assert _MODULE in message
    assert _RELATIVE in message
    assert "before that file is deleted" in message
    assert "version control" in message
    assert "git restore" in message


def test_capture_refuses_a_path_outside_the_project(tmp_path: Path) -> None:
    root = _project(tmp_path)
    with pytest.raises(BaselineRecordError) as caught:
        capture_baseline(root, _MODULE, "../elsewhere/lending.py")
    assert "outside this project" in str(caught.value)


def test_capture_refuses_something_that_is_not_a_python_file(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "notes.txt").write_text("nothing here\n", encoding="utf-8", newline="\n")
    with pytest.raises(BaselineRecordError) as caught:
        capture_baseline(root, "notes", "notes.txt")
    assert "not a Python file" in str(caught.value)


def test_capture_refuses_source_that_will_not_parse(tmp_path: Path) -> None:
    """One error type out of the store, with the reader's detail kept."""
    root = _project(tmp_path)
    (root / _RELATIVE).write_text("def borrow(\n", encoding="utf-8", newline="\n")
    with pytest.raises(BaselineRecordError) as caught:
        _captured(root)
    message = str(caught.value)
    assert _MODULE in message
    assert "not valid Python" in message


@pytest.mark.parametrize(
    ("label", "break_it"),
    [
        ("gone", "delete"),
        ("unparsable", "damage"),
    ],
)
def test_a_refusal_never_names_this_machine(
    tmp_path: Path, label: str, break_it: str,
) -> None:
    """Paths in anything printed or recorded are project-relative (rule 4).

    A message that quotes ``/Users/someone/work/...`` is both noise to
    the reader and a machine detail leaking out of a tool whose whole
    output is meant to travel.
    """
    root = _project(tmp_path)
    if break_it == "delete":
        (root / _RELATIVE).unlink()
    else:
        (root / _RELATIVE).write_text("def borrow(\n", encoding="utf-8", newline="\n")

    with pytest.raises(BaselineRecordError) as caught:
        _captured(root)

    message = str(caught.value)
    assert str(root) not in message, label
    assert root.as_posix() not in message, label


# ---------------------------------------------------------------------------
# Saving: one file, deterministic bytes
# ---------------------------------------------------------------------------


def test_save_writes_exactly_one_file_at_the_project_root(tmp_path: Path) -> None:
    root = _project(tmp_path)
    before = set(_snapshot(root))

    written = save_baselines(root, {_MODULE: _captured(root)})

    assert written == root / BASELINE_FILENAME
    assert written == baseline_record_path(root)
    assert set(_snapshot(root)) - before == {BASELINE_FILENAME}


def test_saved_bytes_are_deterministic(tmp_path: Path) -> None:
    """Re-capturing an unchanged module has to leave the file byte-identical."""
    root = _project(tmp_path)
    first = save_baselines(root, {_MODULE: _captured(root)}).read_bytes()
    second = save_baselines(root, {_MODULE: _captured(root)}).read_bytes()
    assert first == second


def test_saved_bytes_are_lf_utf8_with_one_trailing_newline(tmp_path: Path) -> None:
    root = _project(tmp_path)
    raw = save_baselines(root, {_MODULE: _captured(root)}).read_bytes()

    assert b"\r\n" not in raw
    assert raw.endswith(b"}\n")
    assert not raw.endswith(b"\n\n")
    raw.decode("utf-8")


def test_the_order_modules_are_captured_in_does_not_change_the_bytes(tmp_path: Path) -> None:
    root = _project(tmp_path)
    lending = _captured(root)
    errors = capture_baseline(root, "bookshelf.errors", "src/bookshelf/errors.py")

    one_way = save_baselines(
        root, {_MODULE: lending, "bookshelf.errors": errors},
    ).read_bytes()
    other_way = save_baselines(
        root, {"bookshelf.errors": errors, _MODULE: lending},
    ).read_bytes()

    assert one_way == other_way


def test_non_ascii_prose_is_stored_readable(tmp_path: Path) -> None:
    """``ensure_ascii=False``: a French docstring stays French in the diff."""
    root = _project(tmp_path)
    (root / _RELATIVE).write_text(
        '"""Prêter un livre."""\n\n\ndef borrow() -> None:\n    """Déjà prêté."""\n',
        encoding="utf-8",
        newline="\n",
    )
    raw = save_baselines(root, {_MODULE: _captured(root)}).read_text(encoding="utf-8")
    assert "Déjà prêté." in raw
    assert "\\u" not in raw


def test_saving_no_baselines_still_writes_a_valid_record(tmp_path: Path) -> None:
    """Nothing captured yet is a reviewable state, not a reason to skip the file."""
    root = _project(tmp_path)
    document = json.loads(save_baselines(root, {}).read_text(encoding="utf-8"))
    assert document == {"schema": BASELINE_SCHEMA, BASELINE_MODULES_KEY: {}}


def test_save_refuses_a_baseline_filed_under_the_wrong_module(tmp_path: Path) -> None:
    root = _project(tmp_path)
    with pytest.raises(BaselineRecordError) as caught:
        save_baselines(root, {"bookshelf.other": _captured(root)})
    assert "bookshelf.other" in str(caught.value)
    assert not baseline_record_path(root).exists()


# ---------------------------------------------------------------------------
# The stored shape
# ---------------------------------------------------------------------------


def test_the_record_has_the_shape_the_schema_promises(tmp_path: Path) -> None:
    root = _project(tmp_path)
    save_baselines(root, {_MODULE: _captured(root)})
    document: dict[str, Any] = json.loads(
        baseline_record_path(root).read_text(encoding="utf-8")
    )

    assert sorted(document) == ["modules", "schema"]
    assert document["schema"] == BASELINE_SCHEMA
    assert list(document[BASELINE_MODULES_KEY]) == [_MODULE]

    entry = document[BASELINE_MODULES_KEY][_MODULE]
    assert sorted(entry) == ["captured_surface", "source_hash", "source_path"]
    assert entry["source_path"] == _RELATIVE
    assert entry["source_hash"].startswith("sha256:")
    assert entry["captured_surface"]["module"] == _MODULE
    assert entry["captured_surface"]["dunder_all"] == ["Loan", "borrow"]
    assert entry["captured_surface"]["entries"][0] == {
        "name": "Loan",
        "category": "class",
        "signature": None,
        "annotation": None,
        "decorators": [],
        "bases": [],
        "docstring": "One loan.",
        "value": None,
    }


def test_json_keys_are_sorted_so_the_file_diffs_cleanly(tmp_path: Path) -> None:
    root = _project(tmp_path)
    save_baselines(root, {_MODULE: _captured(root)})
    text = baseline_record_path(root).read_text(encoding="utf-8")
    assert text.index('"modules"') < text.index('"schema"')
    assert text.index('"source_hash"') < text.index('"source_path"')


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_nothing_captured_yet_is_not_an_error(tmp_path: Path) -> None:
    assert load_baselines(_project(tmp_path)) == {}


def test_a_saved_record_loads_back_as_what_was_captured(tmp_path: Path) -> None:
    root = _project(tmp_path)
    captured = _captured(root)
    save_baselines(root, {_MODULE: captured})

    loaded = load_baselines(root)

    assert list(loaded) == [_MODULE]
    assert loaded[_MODULE] == captured
    assert isinstance(loaded[_MODULE].surface, ModuleSurface)


def test_modules_come_back_in_a_stable_order(tmp_path: Path) -> None:
    root = _project(tmp_path)
    save_baselines(
        root,
        {
            _MODULE: _captured(root),
            "bookshelf.errors": capture_baseline(
                root, "bookshelf.errors", "src/bookshelf/errors.py",
            ),
        },
    )
    assert list(load_baselines(root)) == ["bookshelf.errors", _MODULE]


def test_saving_one_module_keeps_the_others(tmp_path: Path) -> None:
    """The load-merge-save loop a command runs, proved end to end."""
    root = _project(tmp_path)
    save_baselines(root, {_MODULE: _captured(root)})

    entries = load_baselines(root)
    entries["bookshelf.errors"] = capture_baseline(
        root, "bookshelf.errors", "src/bookshelf/errors.py",
    )
    save_baselines(root, entries)

    assert sorted(load_baselines(root)) == ["bookshelf.errors", _MODULE]


def test_entries_are_sorted_on_load_even_if_the_file_was_edited(tmp_path: Path) -> None:
    """Everything downstream may assume a surface is ordered by name."""
    root = _project(tmp_path)
    save_baselines(root, {_MODULE: _captured(root)})
    record = baseline_record_path(root)
    document = json.loads(record.read_text(encoding="utf-8"))
    surface = document[BASELINE_MODULES_KEY][_MODULE]["captured_surface"]
    surface["entries"] = list(reversed(surface["entries"]))
    record.write_text(json.dumps(document), encoding="utf-8", newline="\n")

    loaded = load_baselines(root)[_MODULE].surface
    assert [entry.name for entry in loaded.entries] == [
        "Loan",
        "Loan.__init__",
        "Loan.extend",
        "borrow",
    ]


def test_an_unknown_field_is_ignored_so_additions_ride_the_same_schema(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    save_baselines(root, {_MODULE: _captured(root)})
    record = baseline_record_path(root)
    document = json.loads(record.read_text(encoding="utf-8"))
    entry = document[BASELINE_MODULES_KEY][_MODULE]
    entry["captured_later_by_a_newer_s0ma"] = {"anything": True}
    entry["captured_surface"]["entries"][0]["something_new"] = "ignored"
    record.write_text(json.dumps(document), encoding="utf-8", newline="\n")

    assert load_baselines(root)[_MODULE].surface.entries[0].name == "Loan"


def test_surface_from_dict_is_the_inverse_of_to_dict(tmp_path: Path) -> None:
    root = _project(tmp_path)
    surface = _captured(root).surface
    assert surface_from_dict(surface.to_dict()) == surface


# ---------------------------------------------------------------------------
# Declared types through the store (E1b)
#
# A baseline cannot be recaptured once the Python it describes is gone,
# so a field arriving on the surface has to travel both ways: written
# into new records, and absent-means-None when an older record is read.
# ---------------------------------------------------------------------------


def _with_models(root: Path) -> Path:
    """Add an annotated module — a dataclass — to the fixture project."""
    (root / "src" / "bookshelf" / "models.py").write_text(
        dedent(_MODELS), encoding="utf-8", newline="\n",
    )
    return root


def _captured_models(root: Path) -> BaselineEntry:
    return capture_baseline(root, _MODELS_MODULE, "src/bookshelf/models.py")


def test_a_declared_type_survives_the_round_trip(tmp_path: Path) -> None:
    root = _with_models(_project(tmp_path))
    save_baselines(root, {_MODELS_MODULE: _captured_models(root)})

    loaded = load_baselines(root)[_MODELS_MODULE].surface
    annotated = {
        entry.name: entry.annotation for entry in loaded.entries if entry.annotation
    }
    assert annotated == {"Book.copies": "int", "Book.title": "str", "LIMIT": "int"}
    assert loaded == _captured_models(root).surface


def test_a_declared_type_is_written_into_the_record_itself(tmp_path: Path) -> None:
    """Not just in memory: the committed file is what survives the .py file."""
    root = _with_models(_project(tmp_path))
    save_baselines(root, {_MODELS_MODULE: _captured_models(root)})
    document = json.loads(baseline_record_path(root).read_text(encoding="utf-8"))

    entries = document[BASELINE_MODULES_KEY][_MODELS_MODULE]["captured_surface"]["entries"]
    stored = {entry["name"]: entry["annotation"] for entry in entries}
    assert stored["Book.title"] == "str"
    assert stored["Book.read"] is None


def test_a_record_written_before_declared_types_loads_with_none(tmp_path: Path) -> None:
    """The additive half of ``@1``: an older record is read, not refused.

    Hand-written the way an earlier s0ma wrote it — every entry without
    an ``annotation`` key at all. Refusing it would be the one
    unrecoverable failure in this family: the Python it describes may
    have been deleted the day after it was captured.
    """
    root = _project(tmp_path)
    baseline_record_path(root).write_text(
        json.dumps(
            {
                "schema": BASELINE_SCHEMA,
                BASELINE_MODULES_KEY: {
                    _MODELS_MODULE: {
                        "source_path": "src/bookshelf/models.py",
                        "source_hash": "sha256:0f" * 16,
                        "captured_surface": {
                            "module": _MODELS_MODULE,
                            "dunder_all": None,
                            "entries": [
                                {
                                    "name": "Book",
                                    "category": "class",
                                    "signature": None,
                                    "decorators": ["dataclass"],
                                    "bases": [],
                                    "docstring": "A title.",
                                    "value": None,
                                },
                                {
                                    "name": "Book.title",
                                    "category": "attribute",
                                    "signature": None,
                                    "decorators": [],
                                    "bases": [],
                                    "docstring": None,
                                    "value": None,
                                },
                            ],
                        },
                    },
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    surface = load_baselines(root)[_MODELS_MODULE].surface

    assert [entry.name for entry in surface.entries] == ["Book", "Book.title"]
    assert [entry.annotation for entry in surface.entries] == [None, None]
    # Everything else the older record did carry is read as written.
    assert surface.entries[0].decorators == ("dataclass",)
    assert surface.entries[0].docstring == "A title."


def test_the_new_key_leaves_the_bytes_sorted_and_deterministic(tmp_path: Path) -> None:
    """A key added to an entry must not unsort the committed file."""
    root = _with_models(_project(tmp_path))
    first = save_baselines(root, {_MODELS_MODULE: _captured_models(root)}).read_bytes()
    second = save_baselines(root, {_MODELS_MODULE: _captured_models(root)}).read_bytes()

    assert first == second
    text = first.decode("utf-8")
    assert text.index('"annotation"') < text.index('"bases"') < text.index('"category"')
    assert b"\r" not in first


# ---------------------------------------------------------------------------
# Refusals when reading
# ---------------------------------------------------------------------------


def test_an_unknown_schema_is_refused_and_never_answered_with_delete_it(
    tmp_path: Path,
) -> None:
    """A baseline cannot be re-taken once the original file is gone."""
    root = _project(tmp_path)
    baseline_record_path(root).write_text(
        json.dumps({"schema": "s0ma-adopt-baseline@99", BASELINE_MODULES_KEY: {}}),
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(BaselineRecordError) as caught:
        load_baselines(root)

    message = str(caught.value)
    assert "s0ma-adopt-baseline@99" in message
    assert BASELINE_SCHEMA in message
    assert "Do not delete the file" in message


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("not JSON at all", "{ this is not json"),
        ("not an object", "[]"),
        ("modules is a list", '{"schema": "s0ma-adopt-baseline@1", "modules": []}'),
    ],
)
def test_a_record_that_is_not_the_right_shape_is_refused(
    tmp_path: Path, label: str, text: str,
) -> None:
    root = _project(tmp_path)
    baseline_record_path(root).write_text(text, encoding="utf-8", newline="\n")

    with pytest.raises(BaselineRecordError) as caught:
        load_baselines(root)

    message = str(caught.value)
    assert BASELINE_FILENAME in message, label
    assert "Restore it from version control" in message, label


@pytest.mark.parametrize(
    ("label", "damage"),
    [
        ("no source path", {"source_path": None}),
        ("no source hash", {"source_hash": 12}),
        ("no surface", {"captured_surface": "gone"}),
    ],
)
def test_an_entry_missing_what_it_needs_is_refused(
    tmp_path: Path, label: str, damage: dict[str, Any],
) -> None:
    root = _project(tmp_path)
    save_baselines(root, {_MODULE: _captured(root)})
    record = baseline_record_path(root)
    document = json.loads(record.read_text(encoding="utf-8"))
    document[BASELINE_MODULES_KEY][_MODULE].update(damage)
    record.write_text(json.dumps(document), encoding="utf-8", newline="\n")

    with pytest.raises(BaselineRecordError) as caught:
        load_baselines(root)
    assert _MODULE in str(caught.value), label


@pytest.mark.parametrize(
    ("label", "damage"),
    [
        ("entries are not a list", {"entries": {}}),
        ("no module name", {"module": None}),
        ("dunder_all is not text", {"dunder_all": [1, 2]}),
    ],
)
def test_a_stored_surface_that_is_not_the_right_shape_is_refused(
    tmp_path: Path, label: str, damage: dict[str, Any],
) -> None:
    root = _project(tmp_path)
    save_baselines(root, {_MODULE: _captured(root)})
    record = baseline_record_path(root)
    document = json.loads(record.read_text(encoding="utf-8"))
    document[BASELINE_MODULES_KEY][_MODULE]["captured_surface"].update(damage)
    record.write_text(json.dumps(document), encoding="utf-8", newline="\n")

    with pytest.raises(BaselineRecordError) as caught:
        load_baselines(root)
    assert BASELINE_FILENAME in str(caught.value), label


def test_a_damaged_entry_names_the_field_that_is_wrong(tmp_path: Path) -> None:
    """A person has to be able to fix the file by hand if it comes to that."""
    root = _project(tmp_path)
    save_baselines(root, {_MODULE: _captured(root)})
    record = baseline_record_path(root)
    document = json.loads(record.read_text(encoding="utf-8"))
    document[BASELINE_MODULES_KEY][_MODULE]["captured_surface"]["entries"][0][
        "decorators"
    ] = "property"
    record.write_text(json.dumps(document), encoding="utf-8", newline="\n")

    with pytest.raises(BaselineRecordError) as caught:
        load_baselines(root)

    message = str(caught.value)
    assert "'decorators'" in message
    assert "'Loan'" in message
