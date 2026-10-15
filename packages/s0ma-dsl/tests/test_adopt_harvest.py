"""Tests for ``s0ma_dsl.adopt.harvest`` — Python module in, draft model out.

Three things are being proved here.

**Structure is derived and meaning is not.** Every declaration the
harvester builds comes from the file's own shape; every intent it cannot
lift from a real ``@component`` stays ``None`` so the emitter writes a
placeholder the checker refuses. Bodies are copied verbatim by line
range, so a test that compares a body against the source text is
comparing bytes, not a re-rendering.

**Nothing is lost.** :func:`account_lines` labels every physical line of
the file with its owner. The property test at the end runs it over every
module of the ``layered_app`` fixture and fails if one line is claimed
twice or by nobody.

**The unplaced carrier parses.** The D1.T3 decision (module docstring of
``harvest.py``) is only worth anything if a ``.s0ma`` file using it goes
through the real parser and the real intra-module validator without a
diagnostic. ``test_unplaced_carrier_parses_clean`` does exactly that, and
the round-trip tests beside it prove the carried text survives the trip
byte for byte for inputs chosen to break it.

Unit tests use inline sources written into ``tmp_path`` so they do not
depend on the fixture applications; only the closing property test reads
the fixture tree, and it skips itself when that tree is not there yet.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.adopt.harvest import (
    LINE_GAP,
    LINE_UNACCOUNTED,
    UNPLACED_CELL_KIND,
    UNPLACED_CELL_PREFIX,
    UNPLACED_CELL_VISIBILITY,
    HarvestError,
    account_lines,
    harvest_module,
    render_unplaced_value,
    unplaced_cell_name,
    unplaced_cell_schema,
)
from s0ma_dsl.adopt.model import DRAFT_UNPLACED_MARKER, SourceFile
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.semantic.validator import validate_module

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

    from s0ma_dsl.adopt.model import DraftModule
    from s0ma_dsl.errors import S0maError

_FIXTURE_APP = (
    Path(__file__).parent / "fixtures" / "brownfield" / "layered_app" / "src" / "bookshelf"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, relative: str, text: str) -> SourceFile:
    """Write a module into *tmp_path* and describe it as a discovered file."""
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    dotted = relative[: -len(".py")].replace("/", ".")
    return SourceFile(path=relative, module=dotted, source_root=".", role="app")


def _harvest(tmp_path: Path, relative: str, text: str, **kwargs: object) -> DraftModule:
    """Write a module and harvest it in one step."""
    source = _write(tmp_path, relative, text)
    return harvest_module(tmp_path, source, **kwargs)  # type: ignore[arg-type]


def _declaration(draft: DraftModule, name: str) -> object:
    """The one declaration called *name*, or a failure that says so."""
    for declaration in draft.declarations:
        if declaration.name == name:
            return declaration
    raise AssertionError(f"no declaration named {name} in {[d.name for d in draft.declarations]}")


# ---------------------------------------------------------------------------
# T1 — declarations
# ---------------------------------------------------------------------------


SAMPLE = '''"""A module that exercises one of every shape the harvester knows."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

MAX_ITEMS = 10

__all__ = ["Counter", "collect", "MAX_ITEMS"]


# The counter keeps its own tally so callers do not have to.
class Counter:
    """Counts things."""

    total: int = 0

    @property
    def doubled(self) -> int:
        return self.total * 2

    @classmethod
    def empty(cls) -> "Counter":
        return cls()


class _Hidden:
    """Not part of the public surface."""


@functools.lru_cache(maxsize=8)
def collect(limit: int) -> list[int]:
    """Gather up to ``limit`` items."""
    return list(range(min(limit, MAX_ITEMS)))


async def fetch(name: str) -> str:
    """Fetch one thing, eventually."""
    return name


def _normalise(name: str) -> str:
    return name.strip()
'''


def test_public_function_becomes_a_nerve_and_private_one_a_helper(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", SAMPLE)
    forms = {declaration.name: declaration.form for declaration in draft.declarations}
    assert forms["collect"] == "nerve"
    assert forms["fetch"] == "nerve"
    assert forms["_normalise"] == "helper"


def test_classes_become_cells_and_constants_become_constant_cells(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", SAMPLE)
    counter = _declaration(draft, "Counter")
    assert counter.form == "cell"  # type: ignore[attr-defined]
    hidden = _declaration(draft, "_Hidden")
    assert hidden.form == "cell"  # type: ignore[attr-defined]
    constant = _declaration(draft, "MAX_ITEMS")
    assert constant.form == "cell"  # type: ignore[attr-defined]
    assert constant.kind == "CONSTANT"  # type: ignore[attr-defined]


def test_declarations_keep_source_order(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", SAMPLE)
    assert [declaration.name for declaration in draft.declarations] == [
        "MAX_ITEMS",
        "Counter",
        "_Hidden",
        "collect",
        "fetch",
        "_normalise",
    ]


def test_body_is_verbatim_including_decorator_and_comment_above(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", SAMPLE)
    collect = _declaration(draft, "collect")
    assert collect.body.startswith("@functools.lru_cache(maxsize=8)\n")  # type: ignore[attr-defined]
    assert collect.body.endswith("return list(range(min(limit, MAX_ITEMS)))\n")  # type: ignore[attr-defined]

    counter = _declaration(draft, "Counter")
    first = counter.body.split("\n")[0]  # type: ignore[attr-defined]
    assert first == "# The counter keeps its own tally so callers do not have to."

    lines = SAMPLE.splitlines(keepends=True)
    for declaration in draft.declarations:
        span = "".join(lines[declaration.start_line - 1 : declaration.end_line])
        assert declaration.body == span, declaration.name


def test_property_and_classmethod_stay_inside_their_class(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", SAMPLE)
    names = {declaration.name for declaration in draft.declarations}
    assert "doubled" not in names
    assert "empty" not in names
    counter = _declaration(draft, "Counter")
    assert "@property" in counter.body  # type: ignore[attr-defined]
    assert "@classmethod" in counter.body  # type: ignore[attr-defined]


def test_no_intent_is_ever_invented(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", SAMPLE)
    assert draft.intent is None
    assert all(declaration.intent is None for declaration in draft.declarations)
    assert draft.docstring is not None
    assert draft.docstring.startswith("A module that exercises")


def test_a_module_with_no_docstring_carries_none(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", "VALUE = 1\n")
    assert draft.docstring is None
    assert draft.intent is None


def test_module_name_is_the_flat_stem(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "pkg/sample.py", "VALUE = 1\n")
    assert draft.module == "sample"
    assert draft.source_path == "pkg/sample.py"
    assert draft.source_hash.startswith("sha256:")
    assert any("flat" in note for note in draft.notes)


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("class Boom(Exception):\n    pass\n", "EXCEPTION"),
        ("class Level(Enum):\n    LOW = 1\n", "ENUM"),
        ("class Sender(Protocol):\n    ...\n", "TYPE"),
        ("class Row(TypedDict):\n    a: int\n", "MODEL"),
        ("class Pair(NamedTuple):\n    a: int\n", "MODEL"),
        ("@dataclass\nclass Book:\n    title: str\n", "MODEL"),
        ("class Plain:\n    pass\n", "MODEL"),
    ],
)
def test_class_kind_comes_from_shape(tmp_path: Path, source: str, kind: str) -> None:
    draft = _harvest(tmp_path, "shapes.py", source)
    assert draft.declarations[0].kind == kind


def test_a_plain_class_says_so_in_a_note(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "shapes.py", "class Plain:\n    pass\n")
    assert any("plain class" in note and "Plain" in note for note in draft.notes)
    shaped = _harvest(tmp_path, "shaped.py", "@dataclass\nclass Book:\n    title: str\n")
    assert not any("plain class" in note for note in shaped.notes)


# ---------------------------------------------------------------------------
# T2 — header facts
# ---------------------------------------------------------------------------


DEPENDENCIES = '''"""A module with one of every import shape."""

from __future__ import annotations

import json
import os.path
import unused_module
from typing import Any

from myapp.errors import NotFound
from myapp.registry import lookup


def find(key: str) -> Any:
    """Find one record."""
    where = os.path.join("var", "records")
    try:
        return lookup(json.loads(key), where)
    except KeyError as exc:
        raise NotFound(key) from exc


def load(key: str) -> Any:
    """Load one record, reaching for the slow path only when asked."""
    import pickle

    return pickle.loads(find(key))
'''

_FIRST_PARTY = frozenset({"myapp", "myapp.errors", "myapp.registry"})


def test_third_party_and_stdlib_imports_become_requires(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "myapp/finder.py", DEPENDENCIES, first_party=_FIRST_PARTY)
    assert "json" in draft.requires
    assert "os.path" in draft.requires
    assert "typing:Any" in draft.requires


def test_an_unused_import_is_left_out_and_named_in_a_note(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "myapp/finder.py", DEPENDENCIES, first_party=_FIRST_PARTY)
    assert "unused_module" not in draft.requires
    assert any("never used" in note and "unused_module" in note for note in draft.notes)


def test_a_function_scoped_import_becomes_a_deferred_require(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "myapp/finder.py", DEPENDENCIES, first_party=_FIRST_PARTY)
    assert draft.deferred_requires == ("pickle",)


def test_a_converted_first_party_import_becomes_uses(tmp_path: Path) -> None:
    draft = _harvest(
        tmp_path,
        "myapp/finder.py",
        DEPENDENCIES,
        first_party=_FIRST_PARTY,
        s0ma_modules=frozenset({"myapp.errors"}),
    )
    assert draft.uses == ("errors.NotFound",)
    assert "myapp.errors:NotFound" not in draft.requires


def test_an_unconverted_first_party_import_becomes_requires_with_a_note(tmp_path: Path) -> None:
    draft = _harvest(
        tmp_path,
        "myapp/finder.py",
        DEPENDENCIES,
        first_party=_FIRST_PARTY,
        s0ma_modules=frozenset({"myapp.errors"}),
    )
    assert "myapp.registry:lookup" in draft.requires
    assert any("myapp.registry" in note and "leaf-first" in note for note in draft.notes)


def test_a_deferred_import_of_a_converted_module_says_why_it_is_not_uses(tmp_path: Path) -> None:
    source = (
        "def find() -> None:\n"
        "    from myapp.errors import NotFound\n\n"
        "    raise NotFound()\n"
    )
    draft = _harvest(
        tmp_path,
        "myapp/finder.py",
        source,
        first_party=_FIRST_PARTY,
        s0ma_modules=frozenset({"myapp.errors"}),
    )
    assert draft.uses == ()
    assert draft.deferred_requires == ("myapp.errors:NotFound",)
    assert any("no deferred form of uses:" in note for note in draft.notes)


def test_an_export_that_the_draft_makes_a_helper_is_left_out(tmp_path: Path) -> None:
    source = (
        '__all__ = ["run", "_tidy"]\n\n\ndef run() -> None:\n    pass\n\n\n'
        "def _tidy() -> None:\n    pass\n"
    )
    draft = _harvest(tmp_path, "sample.py", source)
    assert draft.exports == ("run",)
    assert any("helper" in note and "_tidy" in note for note in draft.notes)


def test_a_relative_import_resolves_against_the_package(tmp_path: Path) -> None:
    source = "from .errors import NotFound\n\n\ndef find() -> None:\n    raise NotFound()\n"
    draft = _harvest(
        tmp_path,
        "myapp/finder.py",
        source,
        first_party=_FIRST_PARTY,
        s0ma_modules=frozenset({"myapp.errors"}),
    )
    assert draft.uses == ("errors.NotFound",)


def test_the_future_import_is_dropped_with_a_note(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "myapp/finder.py", DEPENDENCIES, first_party=_FIRST_PARTY)
    assert not any("__future__" in entry for entry in draft.requires)
    assert any("__future__" in note for note in draft.notes)


def test_exports_follow_dunder_all_when_it_is_declared(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", SAMPLE)
    assert draft.exports == ("Counter", "collect", "MAX_ITEMS")


def test_exports_fall_back_to_the_public_declarations(tmp_path: Path) -> None:
    source = (
        "VALUE = 1\n\n\ndef run() -> int:\n    return VALUE\n\n\n"
        "def _helper() -> None:\n    pass\n"
    )
    draft = _harvest(tmp_path, "sample.py", source)
    assert draft.exports == ("VALUE", "run")


def test_an_export_with_no_declaration_is_dropped_and_noted(tmp_path: Path) -> None:
    source = '__all__ = ["run", "logger"]\n\nlogger = 1\n\n\ndef run() -> None:\n    pass\n'
    draft = _harvest(tmp_path, "sample.py", source)
    assert draft.exports == ("run",)
    assert any("logger" in note and "__all__" in note for note in draft.notes)


def test_layer_argument_wins_and_none_is_left_alone(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", SAMPLE, layer="DOMAIN")
    assert draft.layer == "DOMAIN"
    assert all(declaration.layer == "DOMAIN" for declaration in draft.declarations)
    assert _harvest(tmp_path, "sample.py", SAMPLE).layer is None


# ---------------------------------------------------------------------------
# T3 — nothing is lost
# ---------------------------------------------------------------------------


UNPLACEABLE = '''"""A module with several shapes that have no declaration form."""

import logging

logger = logging.getLogger(__name__)
# The null handler keeps a quiet console quiet.
logger.addHandler(logging.NullHandler())

for _name in ("a", "b"):
    logging.getLogger(_name)


def run() -> None:
    """Do the thing."""
    logger.info("running")


if __name__ == "__main__":
    run()
'''


def test_unplaceable_statements_are_carried_not_dropped(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", UNPLACEABLE)
    assert len(draft.unplaced) == 2
    first, second = draft.unplaced
    assert "logger = logging.getLogger(__name__)" in first.text
    assert "null handler" in first.text
    assert "for _name in" in first.text
    assert "import time" not in first.text
    assert second.text.startswith('if __name__ == "__main__":')
    assert "bootstrap_files" in second.reason


def test_a_type_checking_block_is_unplaced_with_the_cycle_warning(tmp_path: Path) -> None:
    """A guard the header cannot absorb is still carried, cycle warning and all.

    D1b promotes a standard-library-only guard instead, so the block
    this test needs is one reaching something else — here another module
    of the project, which is the case the warning exists for.
    """
    source = (
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n    from myapp.models import Book\n\n\n"
        "def shelve(book: 'Book') -> None:\n    raise NotImplementedError\n"
    )
    draft = _harvest(tmp_path, "sample.py", source, first_party=_FIRST_PARTY)
    assert len(draft.unplaced) == 1
    assert draft.unplaced[0].text.startswith("if TYPE_CHECKING:")
    assert "cycle" in draft.unplaced[0].reason


# ---------------------------------------------------------------------------
# D1b — a standard-library-only TYPE_CHECKING block joins the header
# ---------------------------------------------------------------------------


PROMOTABLE = (
    "from typing import TYPE_CHECKING\n"
    "\n"
    "if TYPE_CHECKING:\n"
    "    from collections.abc import Iterator\n"
    "    from datetime import date\n"
    "\n"
    "\n"
    "def when(days: Iterator[int]) -> date:\n"
    "    raise NotImplementedError\n"
)


def _guarded(body: str, *, tail: str = "", prologue: str = "") -> str:
    """A tiny module whose only guard holds *body*, indented into it."""
    indented = "".join(f"    {line}\n" for line in body.split("\n") if line)
    opening = prologue or "from typing import TYPE_CHECKING\n"
    return f"{opening}\nif TYPE_CHECKING:\n{indented}{tail}"


def test_a_standard_library_only_type_checking_block_is_promoted(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", PROMOTABLE)
    assert draft.unplaced == ()
    assert "collections.abc:Iterator" in draft.requires
    assert "datetime:date" in draft.requires


def test_a_promoted_block_leaves_one_plain_sentence_behind(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", PROMOTABLE)
    said = [note for note in draft.notes if "if TYPE_CHECKING:" in note]
    assert len(said) == 1
    assert "lines 3-5" in said[0]
    assert "standard library" in said[0]
    assert "requires:" in said[0]
    assert "cannot create an import cycle" in said[0]


def test_a_promoted_block_is_accounted_as_a_header_import(tmp_path: Path) -> None:
    """The block's lines belong to the header now, not to a carrier."""
    draft = _harvest(tmp_path, "sample.py", PROMOTABLE)
    owners = account_lines(draft, PROMOTABLE)
    assert owners == (
        "header:import",
        LINE_GAP,
        "header:import",
        "header:import",
        "header:import",
        LINE_GAP,
        LINE_GAP,
        "declaration:when",
        "declaration:when",
    )
    assert LINE_UNACCOUNTED not in owners
    assert not [owner for owner in owners if owner.startswith("conflict:")]


@pytest.mark.parametrize(
    "prologue",
    ["import typing\n", "import typing as t\n"],
    ids=["dotted", "aliased"],
)
def test_a_dotted_or_aliased_guard_is_promoted_too(tmp_path: Path, prologue: str) -> None:
    attribute = "typing.TYPE_CHECKING" if prologue == "import typing\n" else "t.TYPE_CHECKING"
    source = (
        f"{prologue}\nif {attribute}:\n    from datetime import date\n\n\n"
        "def when() -> date:\n    raise NotImplementedError\n"
    )
    draft = _harvest(tmp_path, "sample.py", source)
    assert draft.unplaced == ()
    assert "datetime:date" in draft.requires


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            _guarded("from datetime import date\nfrom myapp.models import Book"),
            "myapp.models",
        ),
        (_guarded("import pydantic"), "pydantic"),
        (_guarded("from pydantic import BaseModel"), "pydantic"),
        (_guarded("import datetime, pydantic"), "pydantic"),
        (_guarded("from datetime import date", tail="else:\n    date = None\n"), "else:"),
        (
            _guarded("from collections.abc import Callable\nHandler = Callable[[int], None]"),
            "not an import",
        ),
        (_guarded("from .models import Book"), ".models"),
        (_guarded("from ..shelves import Shelf"), "..shelves"),
        (_guarded("from . import models"), "relative import"),
        (
            _guarded("import json", prologue="from typing import TYPE_CHECKING\n").replace(
                "if TYPE_CHECKING:", "if not TYPE_CHECKING:"
            ),
            "more than a plain TYPE_CHECKING check",
        ),
    ],
    ids=[
        "first_party",
        "third_party_plain",
        "third_party_from",
        "one_of_several",
        "else_branch",
        "assignment",
        "relative",
        "relative_climbing",
        "relative_bare",
        "runtime_only_fallback",
    ],
)
def test_a_block_the_header_cannot_absorb_stays_unplaced(
    tmp_path: Path, source: str, expected: str
) -> None:
    """Anything but standard library keeps the block, and says what kept it."""
    draft = _harvest(tmp_path, "myapp/sub/sample.py", source, first_party=_FIRST_PARTY)
    assert len(draft.unplaced) == 1, draft.unplaced
    block = draft.unplaced[0]
    assert block.text.startswith("if ")
    assert expected in block.reason
    assert "cycle" in block.reason
    assert not any("if TYPE_CHECKING:" in note for note in draft.notes)
    assert "datetime:date" not in draft.requires


def test_a_kept_block_is_still_accounted_for_exactly_once(tmp_path: Path) -> None:
    source = _guarded("from datetime import date\nfrom myapp.models import Book")
    draft = _harvest(tmp_path, "myapp/sample.py", source, first_party=_FIRST_PARTY)
    owners = account_lines(draft, source)
    assert LINE_UNACCOUNTED not in owners
    assert not [owner for owner in owners if owner.startswith("conflict:")]
    assert owners[2].startswith("unplaced:")


def test_a_promoted_import_is_kept_even_when_only_a_quoted_annotation_uses_it(
    tmp_path: Path,
) -> None:
    """A type-only name can hide inside a string, where the scan cannot read it."""
    source = (
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n    from datetime import date\n\n\n"
        "def when() -> 'date':\n    raise NotImplementedError\n"
    )
    draft = _harvest(tmp_path, "sample.py", source)
    assert "datetime:date" in draft.requires
    assert not any("never used" in note and "datetime" in note for note in draft.notes)


def test_promotion_does_not_duplicate_an_import_already_at_load_time(tmp_path: Path) -> None:
    source = (
        "from datetime import date\n"
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n    from datetime import date\n\n\n"
        "def when() -> date:\n    raise NotImplementedError\n"
    )
    draft = _harvest(tmp_path, "sample.py", source)
    assert draft.requires == ("datetime:date",)
    assert draft.unplaced == ()


def test_promotion_is_deterministic(tmp_path: Path) -> None:
    source = _write(tmp_path, "sample.py", PROMOTABLE)
    first = harvest_module(tmp_path, source)
    second = harvest_module(tmp_path, source)
    assert first.to_dict() == second.to_dict()
    assert first.requires == ("collections.abc:Iterator", "datetime:date")


def test_the_guard_name_import_is_reported_as_no_longer_needed(tmp_path: Path) -> None:
    """Nothing in the draft uses TYPE_CHECKING once the block is absorbed."""
    draft = _harvest(tmp_path, "sample.py", PROMOTABLE)
    assert "typing:TYPE_CHECKING" not in draft.requires
    assert any("never used" in note and "TYPE_CHECKING" in note for note in draft.notes)


def _fixture_draft(name: str) -> DraftModule:
    """Harvest one module of the ``layered_app`` fixture application."""
    root = _FIXTURE_APP.parents[1]
    relative = (_FIXTURE_APP / f"{name}.py").relative_to(root).as_posix()
    stems = {path.stem for path in _fixture_modules() if path.stem != "__init__"}
    source = SourceFile(
        path=relative, module=f"bookshelf.{name}", source_root="src", role="app"
    )
    first_party = frozenset({"bookshelf", *(f"bookshelf.{stem}" for stem in stems)})
    return harvest_module(root, source, first_party=first_party)


@pytest.mark.skipif(not _FIXTURE_APP.is_dir(), reason="milestone A2 owns the fixture application")
def test_the_fixture_model_module_has_its_guard_promoted() -> None:
    """``models.py``'s guard imports ``datetime`` and nothing else."""
    draft = _fixture_draft("models")
    assert draft.unplaced == ()
    assert "datetime:date" in draft.requires
    assert any("if TYPE_CHECKING:" in note for note in draft.notes)


@pytest.mark.skipif(not _FIXTURE_APP.is_dir(), reason="milestone A2 owns the fixture application")
def test_the_fixture_notifications_module_keeps_its_guard() -> None:
    """``notifications.py``'s guard also reaches ``.models``, so it stays."""
    draft = _fixture_draft("notifications")
    assert len(draft.unplaced) == 1
    block = draft.unplaced[0]
    assert block.text.startswith("if TYPE_CHECKING:")
    assert ".models" in block.reason
    assert "datetime:date" not in draft.requires
    assert not any("if TYPE_CHECKING:" in note for note in draft.notes)


def test_a_lower_case_module_assignment_is_unplaced(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", "import logging\n\nlogger = logging.getLogger('x')\n")
    assert len(draft.unplaced) == 1
    assert "upper-case constant" in draft.unplaced[0].reason


def test_unplaced_text_is_verbatim(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", UNPLACEABLE)
    lines = UNPLACEABLE.splitlines(keepends=True)
    for block in draft.unplaced:
        assert block.text == "".join(lines[block.start_line - 1 : block.end_line])


def test_every_line_is_accounted_for_exactly_once(tmp_path: Path) -> None:
    for text in (SAMPLE, DEPENDENCIES, UNPLACEABLE):
        draft = _harvest(tmp_path, "sample.py", text, first_party=_FIRST_PARTY)
        owners = account_lines(draft, text)
        assert len(owners) == len(text.splitlines())
        assert LINE_UNACCOUNTED not in owners
        assert not [owner for owner in owners if owner.startswith("conflict:")]


def test_accounting_reports_a_gap_for_a_stray_comment(tmp_path: Path) -> None:
    """A comment with a blank line under it belongs to nothing, and says so."""
    text = "VALUE = 1\n\n# A comment that belongs to nothing at all.\n\nOTHER = 2\n"
    draft = _harvest(tmp_path, "sample.py", text)
    owners = account_lines(draft, text)
    assert owners == (
        "declaration:VALUE",
        LINE_GAP,
        LINE_GAP,
        LINE_GAP,
        "declaration:OTHER",
    )
    assert any("Line 3" in note for note in draft.notes)


def test_the_gap_note_agrees_in_number(tmp_path: Path) -> None:
    """Pilot G2-15: one line holds and sits; several hold and sit.

    ``_gap_note`` branched the noun and left the verbs plural, so a
    single stray comment read "Line 58 of the Python file hold only
    comments and sit above nothing the draft declares, so they are not
    carried into it" — three of them in one draft of the pilot's.
    """
    one = _harvest(
        tmp_path,
        "one.py",
        "VALUE = 1\n\n# One stray comment.\n\nOTHER = 2\n",
    )
    several = _harvest(
        tmp_path,
        "several.py",
        "VALUE = 1\n\n# First stray line.\n# Second stray line.\n\nOTHER = 2\n",
    )

    singular = next(note for note in one.notes if note.startswith("Line 3"))
    plural = next(note for note in several.notes if note.startswith("Lines 3-4"))

    assert "holds only comments and sits above" in singular
    assert "so it is not carried into it. Read it before" in singular
    assert "hold only comments and sit above" in plural
    assert "so they are not carried into it. Read them before" in plural


def test_a_comment_directly_above_a_definition_is_absorbed_by_it(tmp_path: Path) -> None:
    text = "VALUE = 1\n\n# This one really does belong to OTHER.\nOTHER = 2\n"
    draft = _harvest(tmp_path, "sample.py", text)
    owners = account_lines(draft, text)
    assert owners == ("declaration:VALUE", LINE_GAP, "declaration:OTHER", "declaration:OTHER")
    assert not any("Line 3" in note for note in draft.notes)


def test_a_trailing_comment_block_is_reported_in_notes(tmp_path: Path) -> None:
    text = "VALUE = 1\n\n# Nothing follows this comment, so nothing carries it.\n"
    draft = _harvest(tmp_path, "sample.py", text)
    assert any("Lines 3-3" in note or "Line 3" in note for note in draft.notes)
    owners = account_lines(draft, text)
    assert owners[2] == LINE_GAP


def test_accounting_catches_a_draft_that_lost_a_line(tmp_path: Path) -> None:
    """The auditor has to be able to fail, or it proves nothing."""
    text = "VALUE = 1\nOTHER = 2\n"
    draft = _harvest(tmp_path, "sample.py", text)
    broken = type(draft)(
        module=draft.module,
        source_path=draft.source_path,
        source_hash=draft.source_hash,
        layer=draft.layer,
        intent=draft.intent,
        docstring=draft.docstring,
        requires=draft.requires,
        deferred_requires=draft.deferred_requires,
        uses=draft.uses,
        exports=draft.exports,
        declarations=draft.declarations[:1],
        unplaced=draft.unplaced,
        notes=draft.notes,
    )
    assert LINE_UNACCOUNTED in account_lines(broken, text)


# ---------------------------------------------------------------------------
# T3 — the unplaced carrier: it parses, and it loses no text
# ---------------------------------------------------------------------------


_HOSTILE = [
    "CACHE = {}\nload_defaults(CACHE)\n",
    "for item in DEFAULTS:\n    CACHE[item] = None\n",
    'DOC = """triple quoted"""\n',
    'X = "ends with a quote"',
    "PATTERN = re.compile('a\\\\tb')\n",
    'TEXT = """\n---\n"""\n',
    'TEXT = "cell Foo :: DOMAIN"\n',
    "try:\n    import ujson as json\nexcept ImportError:\n    import json\n",
    "A = 1\n   \nB = 2\n",
    "A = 1",
    'NAME = "café"\n',
    "TRAILING = 1\\\\",
]


@pytest.mark.parametrize("text", _HOSTILE)
def test_the_carried_text_survives_the_round_trip(text: str) -> None:
    literal = render_unplaced_value(text)
    tree = ast.parse(f"VALUE = {literal}")
    assignment = tree.body[0]
    assert isinstance(assignment, ast.Assign)
    assert ast.literal_eval(assignment.value) == text


def test_the_carrier_name_and_schema_say_where_the_text_came_from(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "sample.py", UNPLACEABLE)
    block = draft.unplaced[0]
    name = unplaced_cell_name(block)
    assert name.startswith(UNPLACED_CELL_PREFIX)
    assert name == f"{UNPLACED_CELL_PREFIX}{block.start_line:04d}_{block.end_line:04d}"
    schema = unplaced_cell_schema(block, draft.source_path)
    assert schema.startswith(DRAFT_UNPLACED_MARKER)
    assert draft.source_path in schema
    assert block.reason in schema


def _carrier_file(block_text: str, reason: str, start: int, end: int) -> str:
    """A complete, tiny ``.s0ma`` file whose only debt is one carrier cell."""
    from s0ma_dsl.adopt.model import DraftUnplaced

    block = DraftUnplaced(text=block_text, start_line=start, end_line=end, reason=reason)
    name = unplaced_cell_name(block)
    schema = unplaced_cell_schema(block, "src/sample.py")
    body = f"{name} = {render_unplaced_value(block_text)}"
    indented = "\n".join(("    " + line) if line.strip() else "" for line in body.split("\n"))
    return f"""module sample
    layer: DOMAIN
    version: 0.1.0
    intent: "A module the retrofit drafted from src/sample.py."
    exports: [KEEP]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell KEEP :: DOMAIN
    kind: CONSTANT
    visibility: PUBLIC
    intent: "A constant the module really does declare."
    schema: "int"
    invariants: none
    covered_by: none
    ---
    KEEP = 1

cell {name} :: DOMAIN
    kind: {UNPLACED_CELL_KIND}
    visibility: {UNPLACED_CELL_VISIBILITY}
    intent: "Source the retrofit could not place. Move it into a declaration, then delete this."
    schema: "{schema}"
    invariants: none
    covered_by: none
    ---
{indented}
"""


DRAFT_DEBT_PREFIX = "ADOPT_"
"""The diagnostic family the carrier is *supposed* to trip (D3).

``ADOPT_UNPLACED_CODE`` refuses a carrier in every strictness mode, by
design: that is the whole reason D1 chose a form the compiler can see.
These tests ask the other question — is the carrier legal ``.s0ma``,
whatever text and reason it holds — so :func:`_structural` sets the
family aside and everything else still has to be empty. The family's
own findings are asserted exactly in ``test_adopt_diagnostics.py``.
"""


def _structural(*groups: Iterable[S0maError]) -> list[S0maError]:
    """Every diagnostic in *groups* less the :data:`DRAFT_DEBT_PREFIX` family."""
    return [
        diagnostic
        for group in groups
        for diagnostic in group
        if not diagnostic.code.startswith(DRAFT_DEBT_PREFIX)
    ]


def test_unplaced_carrier_parses_clean(tmp_path: Path) -> None:
    """The D1.T3 decision, proved against the real parser and validator."""
    text = "logger = logging.getLogger(__name__)\nlogger.addHandler(logging.NullHandler())\n"
    source = _carrier_file(text, "a module-level assignment", 10, 11)
    path = tmp_path / "sample.s0ma"
    path.write_text(source, encoding="utf-8", newline="\n")

    module, warnings = parse_s0ma_with_warnings(
        source, str(path), mode=StrictnessMode.MIGRATION
    )
    errors = validate_module(module, mode=StrictnessMode.MIGRATION, filename=str(path))
    diagnostics = _structural(warnings, errors)
    assert diagnostics == [], [f"{d.code}: {d.message}" for d in diagnostics]

    carrier = [cell for cell in module.cells if cell.name.startswith(UNPLACED_CELL_PREFIX)]
    assert len(carrier) == 1
    assert DRAFT_UNPLACED_MARKER in carrier[0].schema


def test_every_harvested_reason_makes_a_schema_field_that_parses() -> None:
    """A ``.s0ma`` quoted string has no escape, so no reason may carry a quote."""
    from s0ma_dsl.adopt.model import DraftUnplaced

    hostile = DraftUnplaced(
        text="VALUE = 1\n",
        start_line=1,
        end_line=1,
        reason='a reason with a "double quote" in it',
    )
    schema = unplaced_cell_schema(hostile, "src/sample.py")
    assert '"' not in schema
    source = _carrier_file("VALUE = 1\n", hostile.reason, 1, 1)
    module, warnings = parse_s0ma_with_warnings(
        source, "sample.s0ma", mode=StrictnessMode.MIGRATION
    )
    errors = validate_module(module, mode=StrictnessMode.MIGRATION, filename="sample.s0ma")
    assert _structural(warnings, errors) == []


@pytest.mark.parametrize(
    "source",
    [
        UNPLACEABLE,
        # Standard-library-only guards are promoted (D1b), so the carrier
        # case is a guard that reaches another module of the project.
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n"
        "    from myapp.models import Book\n",
        "import logging\n\nlogger = logging.getLogger('x')\n",
        "configure()\n",
        "try:\n    import ujson as json\nexcept ImportError:\n    import json\n",
        "with open('x') as handle:\n    DATA = handle.read()\n",
        "while True:\n    break\n",
        "A = B = 1\n",
    ],
    ids=["mixed", "type_checking", "logger", "call", "try", "with", "while", "multi_target"],
)
def test_every_unplaced_block_the_harvester_makes_parses_as_a_carrier(
    tmp_path: Path, source: str
) -> None:
    """Whatever the shape or the reason, the carrier it produces is legal .s0ma."""
    draft = _harvest(tmp_path, "sample.py", source)
    assert draft.unplaced, "this source was meant to produce an unplaced block"
    for block in draft.unplaced:
        text = _carrier_file(block.text, block.reason, block.start_line, block.end_line)
        module, warnings = parse_s0ma_with_warnings(
            text, "sample.s0ma", mode=StrictnessMode.MIGRATION
        )
        errors = validate_module(module, mode=StrictnessMode.MIGRATION, filename="sample.s0ma")
        diagnostics = _structural(warnings, errors)
        assert diagnostics == [], [f"{d.code}: {d.message}" for d in diagnostics]

        carrier = next(
            cell for cell in module.cells if cell.name.startswith(UNPLACED_CELL_PREFIX)
        )
        assert carrier.body is not None
        assignment = ast.parse(carrier.body).body[0]
        assert isinstance(assignment, ast.Assign)
        assert ast.literal_eval(assignment.value) == block.text


def test_the_parsed_carrier_still_holds_the_original_text(tmp_path: Path) -> None:
    """The parser's own dedent gives the text back byte for byte."""
    text = "for item in DEFAULTS:\n    CACHE[item] = None\n"
    source = _carrier_file(text, "a top-level loop", 4, 5)
    module, _ = parse_s0ma_with_warnings(source, "sample.s0ma", mode=StrictnessMode.MIGRATION)
    carrier = next(cell for cell in module.cells if cell.name.startswith(UNPLACED_CELL_PREFIX))
    assert carrier.body is not None
    tree = ast.parse(carrier.body)
    assignment = tree.body[0]
    assert isinstance(assignment, ast.Assign)
    assert ast.literal_eval(assignment.value) == text


# ---------------------------------------------------------------------------
# T4 — registered Python (rung 2 carry-forward)
# ---------------------------------------------------------------------------


REGISTERED = '''"""A module that was already registered in place."""

from s0ma.decorators import component
from s0ma.models import Contract
from s0ma.types import ComponentKind, Layer


@component(
    name="ledger_total",
    kind=ComponentKind.FUNCTION,
    layer=Layer.DOMAIN,
    intent="Adds up every entry in one ledger so the balance is never guessed at",
    contracts=Contract(
        preconditions=["entries is not empty"],
        postconditions=["the result is the sum of every entry"],
    ),
    version="1.2.0",
    idempotent=True,
)
def ledger_total(entries: list[int]) -> int:
    """Sum the ledger."""
    return sum(entries)
'''


def test_a_real_intent_is_lifted_and_never_replaced(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "ledger.py", REGISTERED)
    declaration = _declaration(draft, "ledger_total")
    assert declaration.intent == (  # type: ignore[attr-defined]
        "Adds up every entry in one ledger so the balance is never guessed at"
    )
    assert declaration.layer == "DOMAIN"  # type: ignore[attr-defined]


def test_the_registration_decorator_is_dropped_from_the_body(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "ledger.py", REGISTERED)
    declaration = _declaration(draft, "ledger_total")
    assert "@component" not in declaration.body  # type: ignore[attr-defined]
    assert declaration.body.startswith("def ledger_total(")  # type: ignore[attr-defined]
    assert declaration.body.endswith("return sum(entries)\n")  # type: ignore[attr-defined]


def test_a_contract_forbids_rides_the_lifted_fields(tmp_path: Path) -> None:
    """``Contract(forbids=...)`` lands on the declaration's ``forbids`` line."""
    source = REGISTERED.replace(
        '        postconditions=["the result is the sum of every entry"],\n',
        '        postconditions=["the result is the sum of every entry"],\n'
        '        forbids=["Never change an entry in the ledger it adds up."],\n',
    )
    assert source != REGISTERED
    draft = _harvest(tmp_path, "ledger.py", source)
    fields = dict(_declaration(draft, "ledger_total").fields)  # type: ignore[attr-defined]
    assert fields["forbids"] == "Never change an entry in the ledger it adds up."


def test_contract_and_kind_ride_the_lifted_fields(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "ledger.py", REGISTERED)
    declaration = _declaration(draft, "ledger_total")
    fields = dict(declaration.fields)  # type: ignore[attr-defined]
    assert fields["kind"] == "FUNCTION"
    assert fields["expects"] == "entries is not empty"
    assert fields["guarantees"] == "the result is the sum of every entry"
    assert fields["version"] == "1.2.0"


def test_an_unhandled_registration_argument_is_named_in_a_note(tmp_path: Path) -> None:
    draft = _harvest(tmp_path, "ledger.py", REGISTERED)
    assert any("idempotent" in note for note in draft.notes)


def test_a_registered_class_keeps_its_kind_on_the_cell(tmp_path: Path) -> None:
    source = (
        "from s0ma.decorators import component\n"
        "from s0ma.types import ComponentKind, Layer\n\n\n"
        "@component(name='Book', kind=ComponentKind.MODEL, layer=Layer.DOMAIN,\n"
        "           intent='One title on the shelf, as the catalogue knows it')\n"
        "class Book:\n    title: str\n"
    )
    draft = _harvest(tmp_path, "models.py", source)
    declaration = _declaration(draft, "Book")
    assert declaration.kind == "MODEL"  # type: ignore[attr-defined]
    assert declaration.intent == "One title on the shelf, as the catalogue knows it"  # type: ignore[attr-defined]
    assert "@component" not in declaration.body  # type: ignore[attr-defined]


def test_the_internal_decorator_lifts_a_visibility(tmp_path: Path) -> None:
    source = (
        "from s0ma.decorators import internal\n\n\n@internal\ndef helper() -> None:\n    pass\n"
    )
    draft = _harvest(tmp_path, "sample.py", source)
    declaration = _declaration(draft, "helper")
    assert dict(declaration.fields)["visibility"] == "INTERNAL"  # type: ignore[attr-defined]
    assert "@internal" not in declaration.body  # type: ignore[attr-defined]


def test_a_registered_name_that_differs_is_noted(tmp_path: Path) -> None:
    source = (
        "from s0ma.decorators import component\n"
        "from s0ma.types import ComponentKind, Layer\n\n\n"
        "@component(name='LedgerTotal', kind=ComponentKind.FUNCTION, layer=Layer.DOMAIN,\n"
        "           intent='Adds up every entry in one ledger')\n"
        "def ledger_total(entries: list[int]) -> int:\n    return sum(entries)\n"
    )
    draft = _harvest(tmp_path, "ledger.py", source)
    assert any("LedgerTotal" in note for note in draft.notes)


# ---------------------------------------------------------------------------
# Refusals and determinism
# ---------------------------------------------------------------------------


def test_a_syntax_error_refuses_rather_than_half_drafting(tmp_path: Path) -> None:
    source = _write(tmp_path, "broken.py", "def run(:\n    pass\n")
    with pytest.raises(HarvestError) as caught:
        harvest_module(tmp_path, source)
    assert caught.value.path == "broken.py"
    assert caught.value.line == 1
    assert "not valid Python" in caught.value.message


def test_a_missing_file_refuses(tmp_path: Path) -> None:
    source = SourceFile(path="gone.py", module="gone", source_root=".", role="app")
    with pytest.raises(HarvestError) as caught:
        harvest_module(tmp_path, source)
    assert "could not be read" in caught.value.message


def test_a_file_that_is_not_utf8_refuses(tmp_path: Path) -> None:
    (tmp_path / "latin.py").write_bytes(b'NAME = "caf\xe9"\n')
    source = SourceFile(path="latin.py", module="latin", source_root=".", role="app")
    with pytest.raises(HarvestError) as caught:
        harvest_module(tmp_path, source)
    assert "UTF-8" in caught.value.message


def test_harvesting_twice_gives_the_same_draft(tmp_path: Path) -> None:
    source = _write(tmp_path, "sample.py", SAMPLE)
    first = harvest_module(tmp_path, source, first_party=_FIRST_PARTY)
    second = harvest_module(tmp_path, source, first_party=_FIRST_PARTY)
    assert first.to_dict() == second.to_dict()


def test_nothing_is_written_while_harvesting(tmp_path: Path) -> None:
    source = _write(tmp_path, "sample.py", SAMPLE)
    before = sorted((path.name, path.stat().st_mtime_ns) for path in tmp_path.rglob("*"))
    harvest_module(tmp_path, source)
    after = sorted((path.name, path.stat().st_mtime_ns) for path in tmp_path.rglob("*"))
    assert before == after


# ---------------------------------------------------------------------------
# T5 — the accounting invariant, over the fixture application
# ---------------------------------------------------------------------------


def _fixture_modules() -> list[Path]:
    """Every module of the brownfield fixture application, sorted."""
    if not _FIXTURE_APP.is_dir():
        return []
    return sorted(_FIXTURE_APP.glob("*.py"))


@pytest.mark.parametrize(
    "module_path",
    _fixture_modules() or [None],
    ids=lambda path: "missing" if path is None else path.name,
)
def test_every_fixture_module_is_accounted_for_line_by_line(module_path: Path | None) -> None:
    if module_path is None:
        pytest.skip(
            f"the brownfield fixture application is not present at {_FIXTURE_APP} "
            "(milestone A2 owns it); the accounting invariant is covered by the "
            "inline-source tests above in the meantime"
        )
    root = _FIXTURE_APP.parents[1]
    relative = module_path.relative_to(root).as_posix()
    stems = {path.stem for path in _fixture_modules() if path.stem != "__init__"}
    first_party = frozenset({"bookshelf", *(f"bookshelf.{stem}" for stem in stems)})
    dotted = "bookshelf" if module_path.stem == "__init__" else f"bookshelf.{module_path.stem}"
    source = SourceFile(path=relative, module=dotted, source_root="src", role="app")

    draft = harvest_module(root, source, first_party=first_party)
    text = module_path.read_text(encoding="utf-8")
    owners = account_lines(draft, text)

    assert len(owners) == len(text.splitlines())
    unaccounted = [index + 1 for index, owner in enumerate(owners) if owner == LINE_UNACCOUNTED]
    assert unaccounted == [], f"{relative} lost lines {unaccounted}"
    conflicts = [
        (index + 1, owner) for index, owner in enumerate(owners) if owner.startswith("conflict:")
    ]
    assert conflicts == [], f"{relative} claimed lines twice: {conflicts}"


def _tiny_app_modules() -> list[Path]:
    """The flat, script-style fixture application, if A2 has landed it."""
    tiny = _FIXTURE_APP.parents[2] / "tiny_app"
    return sorted(tiny.glob("*.py")) if tiny.is_dir() else []


@pytest.mark.parametrize(
    "module_path",
    _tiny_app_modules() or [None],
    ids=lambda path: "missing" if path is None else path.name,
)
def test_the_flat_fixture_application_is_accounted_for_too(module_path: Path | None) -> None:
    """The same invariant over a tree with no packaging and no source root."""
    if module_path is None:
        pytest.skip("the tiny_app brownfield fixture is not present (milestone A2 owns it)")
    root = module_path.parent
    stems = {path.stem for path in _tiny_app_modules()}
    source = SourceFile(
        path=module_path.name, module=module_path.stem, source_root=".", role="app"
    )
    draft = harvest_module(root, source, first_party=frozenset(stems))
    text = module_path.read_text(encoding="utf-8")
    owners = account_lines(draft, text)

    assert len(owners) == len(text.splitlines())
    assert LINE_UNACCOUNTED not in owners, module_path.name
    assert not [owner for owner in owners if owner.startswith("conflict:")], module_path.name
