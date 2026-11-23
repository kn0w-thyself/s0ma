"""Parity accepts the quote a conversion needs, and nothing else.

``s0ma adopt draft`` drops ``from __future__ import annotations``, so an
annotation naming its own class has to be quoted in the ``.s0ma``. Under the
import ``-> Book`` holds the string ``'Book'``, and without it ``-> "Book"``
holds the same string, so that quote is not a difference. The baseline records
whether the original had the import, and only then does a built annotation that
is one whole string also read unquoted. Everything here runs through the real
commands.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.adopt.model import BASELINE_FILENAME, BASELINE_SCHEMA
from s0ma_dsl.adopt.parity import (
    BaselineRecordError,
    capture_baseline,
    compare_surfaces,
    load_baselines,
    save_baselines,
)
from s0ma_dsl.adopt.surface import surface_from_source
from s0ma_dsl.cli.main import S0maCLI

_BROWNFIELD = Path(__file__).parent / "fixtures" / "brownfield"

_MARKER = "FIXME(adopt):"
_PLACEHOLDER = re.compile(
    rf'^(?P<indent>\s*)(?P<field>[a-z_]+): "{re.escape(_MARKER)}[^"]*"$',
    re.MULTILINE,
)
_AUTHORED = "Written by this test so the draft carries a real sentence."

_FUTURE = "from __future__ import annotations\n\n"

_TEMPLATE = '''"""A probe module for the parity comparison."""
{future}from typing import Annotated, Literal

A = "a"


class Author:
    """An author."""


class Book:
    """A book."""


class Shelf:
    """A shelf."""

    item: {field} = None


def target({params}){returns}:
    """Probe."""
    return None
'''


def _run(root: Path, *argv: str) -> int:
    return S0maCLI().run(["--project-root", str(root), *argv])


def _author(draft: Path) -> None:
    text = draft.read_text(encoding="utf-8")
    filled, count = _PLACEHOLDER.subn(
        lambda match: f'{match.group("indent")}{match.group("field")}: "{_AUTHORED}"',
        text,
    )
    assert count > 0
    draft.write_text(filled, encoding="utf-8", newline="\n")


def _probe_project(
    root: Path, *, future: bool, params: str, returns: str, field: str,
) -> Path:
    (root / "src" / "probe").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\n'
        'build-backend = "hatchling.build"\n\n'
        '[project]\nname = "probe"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    (root / "src" / "probe" / "__init__.py").write_text(
        '"""Probe package."""\n', encoding="utf-8",
    )
    (root / "src" / "probe" / "mod.py").write_text(
        _TEMPLATE.format(
            future=_FUTURE if future else "",
            params=params,
            returns=returns,
            field=field,
        ),
        encoding="utf-8",
    )
    return root


def _convert(
    root: Path,
    original: tuple[str, str, str],
    built: tuple[str, str, str],
    *,
    drop_field: bool = False,
) -> None:
    """Baseline, draft, edit the draft to *built*, then check and build."""
    assert _run(root, "adopt", "init") == 0
    assert _run(root, "adopt", "baseline", "probe.mod") == 0
    assert _run(root, "adopt", "draft", "probe.mod") == 0
    if drop_field:
        record = root / BASELINE_FILENAME
        data = json.loads(record.read_text(encoding="utf-8"))
        data["modules"]["probe.mod"].pop("future_annotations", None)
        record.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
    draft = root / "src" / "probe" / "mod.s0ma"
    _author(draft)
    text = draft.read_text(encoding="utf-8")
    old_signature = f"def target({original[0]}){original[1]}:"
    old_field = f"item: {original[2]} = None"
    assert old_signature in text
    assert old_field in text
    draft.write_text(
        text.replace(old_signature, f"def target({built[0]}){built[1]}:").replace(
            old_field, f"item: {built[2]} = None",
        ),
        encoding="utf-8",
        newline="\n",
    )
    assert _run(root, "check") == 0
    assert _run(root, "build") == 0


def _parity(
    root: Path, capsys: pytest.CaptureFixture[str],
) -> tuple[int, list[dict[str, Any]]]:
    capsys.readouterr()
    code = _run(root, "adopt", "verify-parity", "probe.mod", "--format", "json")
    document = json.loads(capsys.readouterr().out)
    return code, [
        finding for module in document["modules"] for finding in module["findings"]
    ]


def _status_counts(
    root: Path, capsys: pytest.CaptureFixture[str],
) -> dict[str, int]:
    capsys.readouterr()
    assert _run(root, "adopt", "status", "--format", "json") == 0
    return dict(json.loads(capsys.readouterr().out)["counts"])


#: Each row: original (params, returns, field), then built (params, returns, field).
_Pair = tuple[tuple[str, str, str], tuple[str, str, str]]

_CLEARED: dict[str, _Pair] = {
    "return": (("", " -> Book", "Book"), ("", ' -> "Book"', "Book")),
    "return union": (
        ("", " -> Book | None", "Book"), ("", ' -> "Book | None"', "Book"),
    ),
    "return generic": (
        ("", " -> list[Book]", "Book"), ("", ' -> "list[Book]"', "Book"),
    ),
    "parameter": (("x: Book", "", "Book"), ('x: "Book"', "", "Book")),
    "parameter with a default": (
        ("x: Book = None", "", "Book"), ('x: "Book" = None', "", "Book"),
    ),
    "declared type": (("", "", "Book"), ("", "", '"Book"')),
    "quoted on both sides": (
        ("", ' -> "Book"', "Book"), ("", ' -> "Book"', "Book"),
    ),
    "one quoted by the original, one by the draft": (
        ('a: "Book", b: Book', "", "Book"), ('a: "Book", b: "Book"', "", "Book"),
    ),
}

_REPORTED: dict[str, tuple[_Pair, str]] = {
    "another class": (
        (("", " -> Book", "Book"), ("", ' -> "Author"', "Book")),
        "signature_changed",
    ),
    "a default": (
        (('x="a"', "", "Book"), ("x=A", "", "Book")), "signature_changed",
    ),
    "inside Literal": (
        (('x: Literal["a"]', "", "Book"), ("x: Literal[A]", "", "Book")),
        "signature_changed",
    ),
    "nested": (
        (("", " -> list[Book]", "Book"), ("", ' -> list["Book"]', "Book")),
        "signature_changed",
    ),
    "doubly quoted": (
        (("", " -> Book", "Book"), ("", " -> \"'Book'\"", "Book")),
        "signature_changed",
    ),
    "Annotated metadata": (
        (
            ('x: Annotated[int, "m"]', "", "Book"),
            ('x: Annotated[int, "n"]', "", "Book"),
        ),
        "signature_changed",
    ),
    "an unparseable string": (
        (("", " -> Book", "Book"), ("", ' -> "Book ("', "Book")),
        "signature_changed",
    ),
    "the reverse pair": (
        (("", ' -> "Book"', "Book"), ("", " -> Book", "Book")),
        "signature_changed",
    ),
    "the reverse pair on a declared type": (
        (("", "", '"Book"'), ("", "", "Book")), "annotation_changed",
    ),
    "two parameters swapped": (
        (
            ("a: Book, b: Author", "", "Book"),
            ('a: "Author", b: "Book"', "", "Book"),
        ),
        "signature_changed",
    ),
}


@pytest.mark.parametrize("label", sorted(_CLEARED))
def test_a_quote_the_conversion_needed_is_not_a_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], label: str,
) -> None:
    original, built = _CLEARED[label]
    root = _probe_project(
        tmp_path / "probe",
        future=True,
        params=original[0],
        returns=original[1],
        field=original[2],
    )

    _convert(root, original, built)

    assert _parity(root, capsys) == (0, [])
    counts = _status_counts(root, capsys)
    assert counts["parity-same-surface"] == 1
    assert counts.get("parity-differences", 0) == 0


@pytest.mark.parametrize("label", sorted(_REPORTED))
def test_a_real_difference_is_still_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], label: str,
) -> None:
    (original, built), kind = _REPORTED[label]
    root = _probe_project(
        tmp_path / "probe",
        future=True,
        params=original[0],
        returns=original[1],
        field=original[2],
    )

    _convert(root, original, built)

    code, findings = _parity(root, capsys)
    assert code == 1
    assert [finding["kind"] for finding in findings] == [kind]
    assert _status_counts(root, capsys)["parity-differences"] == 1


@pytest.mark.parametrize("drop_field", [False, True], ids=["no-import", "no-field"])
def test_a_quote_is_reported_without_the_recorded_import(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], drop_field: bool,
) -> None:
    original = ("", " -> Book", "Book")
    built = ("", ' -> "Book"', "Book")
    root = _probe_project(
        tmp_path / "probe",
        future=drop_field,
        params=original[0],
        returns=original[1],
        field=original[2],
    )

    _convert(root, original, built, drop_field=drop_field)

    code, findings = _parity(root, capsys)
    assert code == 1
    assert [finding["kind"] for finding in findings] == ["signature_changed"]
    assert _status_counts(root, capsys)["parity-differences"] == 1


def test_a_finding_shows_both_sides_as_written() -> None:
    baseline = surface_from_source(
        "def f(a: Book, b: Author) -> Book: ...\n", "probe.mod",
    )
    built = surface_from_source(
        'def f(a: "Book", b: "Book") -> "Book": ...\n', "probe.mod",
    )

    result = compare_surfaces(baseline, built, future_annotations=True)

    (finding,) = result.findings
    assert finding.before == "(a: Book, b: Author) -> Book"
    assert finding.after == "(a: 'Book', b: 'Book') -> 'Book'"


@pytest.mark.parametrize(
    "annotation",
    ['" Book"', '"Book; x"', '""', '"Book\\x00"', 'b"Book"', 'f"Book"'],
)
def test_a_string_that_spells_no_expression_stays_as_written(annotation: str) -> None:
    baseline = surface_from_source("def f() -> Book: ...\n", "probe.mod")
    built = surface_from_source(f"def f() -> {annotation}: ...\n", "probe.mod")

    assert not compare_surfaces(baseline, built, future_annotations=True).clean


def test_the_real_route_on_layered_app(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "layered_app"
    shutil.copytree(
        _BROWNFIELD / "layered_app",
        root,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    original = (root / "src" / "bookshelf" / "models.py").read_bytes()
    assert b"-> Book:" in original

    assert _run(root, "adopt", "init") == 0
    assert _run(root, "adopt", "baseline", "bookshelf.models") == 0
    assert _run(root, "adopt", "draft", "bookshelf.models") == 0
    draft = root / "src" / "bookshelf" / "models.s0ma"
    _author(draft)
    assert _run(root, "check") == 1

    text = draft.read_text(encoding="utf-8")
    assert "-> Book:" in text
    draft.write_text(text.replace("-> Book:", '-> "Book":'), encoding="utf-8", newline="\n")

    assert _run(root, "check") == 0
    assert _run(root, "build") == 0
    capsys.readouterr()
    assert _run(root, "adopt", "verify-parity", "bookshelf.models") == 0
    assert "same surface" in capsys.readouterr().out
    counts = _status_counts(root, capsys)
    assert counts["parity-same-surface"] == 1
    assert counts.get("parity-differences", 0) == 0
    assert (root / "src" / "bookshelf" / "models.py").read_bytes() == original


# ---------------------------------------------------------------------------
# The field on the record
# ---------------------------------------------------------------------------


def _capture(root: Path, source: str) -> dict[str, Any]:
    (root / "mod.py").write_text(source, encoding="utf-8")
    entry = capture_baseline(root, "mod", "mod.py")
    save_baselines(root, {"mod": entry})
    document: dict[str, Any] = json.loads(
        (root / BASELINE_FILENAME).read_text(encoding="utf-8"),
    )
    assert document["schema"] == BASELINE_SCHEMA
    entry_dict: dict[str, Any] = document["modules"]["mod"]
    return entry_dict


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from __future__ import annotations\nX = 1\n", id="first-line"),
        pytest.param(
            '"""Doc."""\nfrom __future__ import annotations\nX = 1\n',
            id="after-a-docstring",
        ),
        pytest.param(
            "from __future__ import division, annotations\nX = 1\n", id="in-a-list",
        ),
        pytest.param(
            "from __future__ import division\n"
            "from __future__ import annotations\nX = 1\n",
            id="second-future-import",
        ),
        pytest.param(
            "from __future__ import annotations as spelled\nX = 1\n", id="aliased",
        ),
    ],
)
def test_the_field_is_written_for_a_file_with_the_import(
    tmp_path: Path, source: str,
) -> None:
    assert _capture(tmp_path, source)["future_annotations"] is True


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("X = 1\n", id="no-import"),
        pytest.param("from __future__ import division\nX = 1\n", id="other-feature"),
        pytest.param(
            "X = 1\nfrom __future__ import annotations\n", id="after-other-code",
        ),
        pytest.param(
            "def f():\n    from __future__ import annotations\n", id="in-a-function",
        ),
        pytest.param(
            "from .__future__ import annotations\nX = 1\n", id="relative-module",
        ),
        pytest.param(
            '"""Doc."""\n"""Not a docstring."""\n'
            "from __future__ import annotations\n",
            id="after-a-second-string",
        ),
    ],
)
def test_the_field_is_left_out_otherwise(tmp_path: Path, source: str) -> None:
    assert "future_annotations" not in _capture(tmp_path, source)


@pytest.mark.parametrize("future", [True, False], ids=["import", "no-import"])
def test_a_second_capture_is_byte_identical(tmp_path: Path, future: bool) -> None:
    source = (_FUTURE if future else "") + "def f() -> int:\n    return 1\n"
    _capture(tmp_path, source)
    first = (tmp_path / BASELINE_FILENAME).read_bytes()

    _capture(tmp_path, source)

    assert (tmp_path / BASELINE_FILENAME).read_bytes() == first


def test_the_field_survives_a_load_and_a_save(tmp_path: Path) -> None:
    _capture(tmp_path, _FUTURE + "def f() -> int:\n    return 1\n")
    first = (tmp_path / BASELINE_FILENAME).read_bytes()

    records = load_baselines(tmp_path)
    assert records["mod"].future_annotations is True
    save_baselines(tmp_path, records)

    assert (tmp_path / BASELINE_FILENAME).read_bytes() == first


def test_a_record_without_the_field_loads_and_keeps_reporting(tmp_path: Path) -> None:
    _capture(tmp_path, _FUTURE + "def f() -> Book:\n    return Book()\n")
    record = tmp_path / BASELINE_FILENAME
    data = json.loads(record.read_text(encoding="utf-8"))
    del data["modules"]["mod"]["future_annotations"]
    record.write_text(json.dumps(data), encoding="utf-8")

    entry = load_baselines(tmp_path)["mod"]

    assert entry.future_annotations is False
    built = surface_from_source('def f() -> "Book":\n    return Book()\n', "mod")
    result = compare_surfaces(
        entry.surface, built, future_annotations=entry.future_annotations,
    )
    assert [finding.kind for finding in result.findings] == ["signature_changed"]


@pytest.mark.parametrize("value", ["yes", 1, [], {}])
def test_a_field_of_the_wrong_shape_is_refused(tmp_path: Path, value: object) -> None:
    _capture(tmp_path, _FUTURE + "X = 1\n")
    record = tmp_path / BASELINE_FILENAME
    data = json.loads(record.read_text(encoding="utf-8"))
    data["modules"]["mod"]["future_annotations"] = value
    record.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(BaselineRecordError, match="future_annotations"):
        load_baselines(tmp_path)
