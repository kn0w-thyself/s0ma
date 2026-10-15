"""Census: everything one Python file tells a static reader (B1).

``adopt/census.py`` turns one file into one
:class:`~s0ma_dsl.adopt.model.ModuleCensus`. Four milestones read those
records — the import graph, the layer proposals, the scan report and the
harvester — so what matters is not that the numbers exist but that each
one means exactly what its name says:

- **Every rule has a negative.** ``MAX_LOANS = 5`` is a constant and
  ``max_loans = 5`` is not; ``class Foo(Protocol)`` is a protocol hint
  and ``class Foo(Prototype)`` is not; an import inside a function is
  deferred and one inside a class body is not.
- **Order carries meaning.** Entities and imports come back in source
  order and ``__all__`` in its declared order — not sorted, not
  de-duplicated — because the draft a module becomes is supposed to read
  like the file it came from.
- **A bad file is a fact, not an exception.** A syntax error and a
  non-UTF-8 file each produce a census carrying a plain-language
  ``parse_error``, and still carry the facts that survive it.
- **Nothing is written and nothing is imported** (retrofit rules R-1 and
  R-2), proved here over a whole tree rather than asserted.

Sources are written inline into ``tmp_path`` so these tests own their
inputs outright.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.adopt.census import census_file
from s0ma_dsl.adopt.discovery import discover_sources
from s0ma_dsl.adopt.model import EntityFact, ImportFact, ModuleCensus, SourceFile
from s0ma_dsl.adoption import compute_adopted_hash

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def census_of(
    tmp_path: Path,
    text: str,
    *,
    relative: str = "bookshelf/catalog.py",
    module: str = "bookshelf.catalog",
    source_root: str = ".",
    role: str = "app",
) -> ModuleCensus:
    """Write *text* to *relative* and return its census.

    The :class:`SourceFile` is built directly rather than discovered, so
    a census test states the module identity it is exercising instead of
    depending on how discovery happens to derive it.
    """
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    source = SourceFile(path=relative, module=module, source_root=source_root, role=role)
    return census_file(tmp_path, source)


def entity(census: ModuleCensus, name: str) -> EntityFact:
    """Return the named entity, failing loudly with what was found instead."""
    for fact in census.entities:
        if fact.name == name:
            return fact
    raise AssertionError(f"no entity {name!r}; found {[e.name for e in census.entities]}")


def imported(census: ModuleCensus, module: str) -> ImportFact:
    """Return the fact for the named import target."""
    for fact in census.imports:
        if fact.module == module:
            return fact
    raise AssertionError(f"no import of {module!r}; found {[i.module for i in census.imports]}")


def tree_fingerprint(root: Path) -> list[tuple[str, str]]:
    """Return every path under *root* with a hash of its bytes."""
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            entries.append((f"{relative}/", ""))
        else:
            entries.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return entries


# ---------------------------------------------------------------------------
# Entities: what a module defines
# ---------------------------------------------------------------------------


def test_top_level_definitions_are_recorded_in_source_order(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        '"""Catalog."""\n\n'
        "MAX_LOANS = 5\n\n\n"
        "def find(title):\n"
        "    return title\n\n\n"
        "async def fetch(title):\n"
        "    return title\n\n\n"
        "class Shelf:\n"
        "    pass\n",
    )
    assert [(e.name, e.category) for e in census.entities] == [
        ("MAX_LOANS", "constant"),
        ("find", "function"),
        ("fetch", "async_function"),
        ("Shelf", "class"),
    ]
    assert [e.line for e in census.entities] == [3, 6, 10, 14]


def test_definitions_that_are_not_top_level_are_not_entities(tmp_path: Path) -> None:
    """The negative: the census describes a module's own surface only."""
    census = census_of(
        tmp_path,
        "class Shelf:\n"
        "    ROWS = 3\n\n"
        "    def find(self):\n"
        "        def inner():\n"
        "            return 1\n\n"
        "        return inner\n",
    )
    assert [e.name for e in census.entities] == ["Shelf"]


def test_upper_case_assignments_are_constants_and_others_are_not(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "MAX_LOANS = 5\n"
        "DEFAULT_SHELF: str = 'a'\n"
        "_PRIVATE_LIMIT = 1\n"
        "FIRST, SECOND = 1, 2\n"
        "max_loans = 5\n"
        "Shelf = None\n"
        "PENDING: int\n"
        "__all__ = ['MAX_LOANS']\n",
    )
    assert [e.name for e in census.entities] == [
        "MAX_LOANS",
        "DEFAULT_SHELF",
        "_PRIVATE_LIMIT",
        "FIRST",
        "SECOND",
    ]
    assert entity(census, "MAX_LOANS").category == "constant"
    assert entity(census, "DEFAULT_SHELF").category == "constant"


def test_an_annotation_without_a_value_declares_nothing(tmp_path: Path) -> None:
    """``PENDING: int`` binds no attribute, so it is not an entity.

    The negative of the constant rule where it is easiest to get wrong:
    the name looks like a constant and the statement runs nothing at
    all, so the runtime never sees it and a draft would have no value to
    carry.
    """
    census = census_of(tmp_path, "PENDING: int\nSETTLED: int = 1\n")
    assert [e.name for e in census.entities] == ["SETTLED"]
    assert census.top_level_effects == 0


def test_public_follows_no_leading_underscore(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "def find():\n    return 1\n\n\ndef _helper():\n    return 1\n\n\n"
        "class Shelf:\n    pass\n\n\nclass _Internal:\n    pass\n",
    )
    assert entity(census, "find").public is True
    assert entity(census, "Shelf").public is True
    assert entity(census, "_helper").public is False
    assert entity(census, "_Internal").public is False


def test_a_literal_dunder_all_narrows_what_counts_as_public(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "__all__ = ['find']\n\n\ndef find():\n    return 1\n\n\ndef also_public():\n    return 1\n",
    )
    assert entity(census, "find").public is True
    assert entity(census, "also_public").public is False


def test_public_constants_are_public_even_though_the_import_hook_ignores_them(
    tmp_path: Path,
) -> None:
    """The one deliberate widening over core's runtime rule.

    Core enforces registration on classes and functions only, so it never
    calls a constant public. The conversion has to know, because a public
    constant becomes a declared CONSTANT and belongs in the module's
    ``exports:``.
    """
    census = census_of(tmp_path, "MAX_LOANS = 5\n_INTERNAL_LIMIT = 1\n")
    assert entity(census, "MAX_LOANS").public is True
    assert entity(census, "_INTERNAL_LIMIT").public is False


@pytest.mark.parametrize(
    ("source", "name", "expected"),
    [
        ("class ShelfError(Exception):\n    pass\n", "ShelfError", "EXCEPTION"),
        ("class Missing(ShelfError):\n    pass\n", "Missing", "EXCEPTION"),
        ("class Odd(BaseException):\n    pass\n", "Odd", "EXCEPTION"),
        ("import enum\n\n\nclass Status(enum.Enum):\n    A = 1\n", "Status", "ENUM"),
        ("class Status(StrEnum):\n    A = 'a'\n", "Status", "ENUM"),
        ("class Flags(Flag):\n    A = 1\n", "Flags", "ENUM"),
        ("@dataclass\nclass Book:\n    title: str\n", "Book", "MODEL"),
        (
            "@dataclasses.dataclass(frozen=True)\nclass Book:\n    title: str\n",
            "Book",
            "MODEL",
        ),
        ("class Book(NamedTuple):\n    title: str\n", "Book", "MODEL"),
        ("class Book(TypedDict, total=False):\n    title: str\n", "Book", "MODEL"),
        ("class Book(BaseModel):\n    title: str\n", "Book", "MODEL"),
        ("class Notifier(Protocol):\n    pass\n", "Notifier", "PROTOCOL"),
        ("class Notifier(typing.Protocol):\n    pass\n", "Notifier", "PROTOCOL"),
        ("class Notifier(Protocol[T]):\n    pass\n", "Notifier", "PROTOCOL"),
        ("class Shelf:\n    pass\n", "Shelf", "CLASS"),
        ("class Shelf(Prototype):\n    pass\n", "Shelf", "CLASS"),
        ("class Shelf(BaseModeller):\n    pass\n", "Shelf", "CLASS"),
        ("def find():\n    return 1\n", "find", "FUNCTION"),
        ("async def fetch():\n    return 1\n", "fetch", "FUNCTION"),
        ("MAX_LOANS = 5\n", "MAX_LOANS", "CONSTANT"),
    ],
)
def test_kind_hints_are_read_from_shape(
    tmp_path: Path, source: str, name: str, expected: str
) -> None:
    assert entity(census_of(tmp_path, source), name).kind_hint == expected


def test_an_exception_base_outranks_every_other_hint(tmp_path: Path) -> None:
    """Order matters when a class matches more than one rule."""
    census = census_of(tmp_path, "@dataclass\nclass ShelfError(ValueError):\n    pass\n")
    assert entity(census, "ShelfError").kind_hint == "EXCEPTION"


def test_decorators_and_bases_are_normalised_source_order(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "@functools.lru_cache(\n    maxsize=128,\n)\n"
        "@staticmethod\n"
        "def find():\n    return 1\n\n\n"
        "class Shelf(Base, Mixin, metaclass=Meta):\n    pass\n",
    )
    assert entity(census, "find").decorators == (
        "functools.lru_cache(maxsize=128)",
        "staticmethod",
    )
    assert entity(census, "find").bases == ()
    assert entity(census, "Shelf").bases == ("Base", "Mixin")
    assert entity(census, "Shelf").decorators == ()


@pytest.mark.parametrize(
    "decorator",
    ["@component(name='X')", "@s0ma.component(name='X')", "@internal", "@internal()"],
)
def test_a_registration_decorator_is_carried_forward(tmp_path: Path, decorator: str) -> None:
    census = census_of(tmp_path, f"{decorator}\ndef find():\n    return 1\n")
    assert entity(census, "find").registered is True


@pytest.mark.parametrize("decorator", ["@dataclass", "@functools.lru_cache", "@property"])
def test_an_ordinary_decorator_is_not_a_registration(tmp_path: Path, decorator: str) -> None:
    """The negative of the rule above."""
    census = census_of(tmp_path, f"{decorator}\ndef find():\n    return 1\n")
    assert entity(census, "find").registered is False


def test_docstrings_are_noticed_on_definitions(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        'def documented():\n    """Say what it does."""\n    return 1\n\n\n'
        "def bare():\n    return 1\n\n\n"
        'class Documented:\n    """Say what it is."""\n\n\nclass Bare:\n    pass\n',
    )
    assert entity(census, "documented").has_docstring is True
    assert entity(census, "bare").has_docstring is False
    assert entity(census, "Documented").has_docstring is True
    assert entity(census, "Bare").has_docstring is False


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------


def test_dunder_all_keeps_its_declared_order(tmp_path: Path) -> None:
    census = census_of(tmp_path, "__all__ = ['zebra', 'alpha', 'zebra']\n")
    assert census.dunder_all == ("zebra", "alpha", "zebra")


def test_a_tuple_dunder_all_reads_the_same_way(tmp_path: Path) -> None:
    assert census_of(tmp_path, "__all__ = ('b', 'a')\n").dunder_all == ("b", "a")


def test_no_dunder_all_is_none(tmp_path: Path) -> None:
    assert census_of(tmp_path, "def find():\n    return 1\n").dunder_all is None


@pytest.mark.parametrize(
    "source",
    [
        "__all__ = [n for n in dir()]\n",
        "__all__ = _EXPORTS\n",
        "__all__ = ['a'] + _EXTRA\n",
        "__all__ = ['a', SOMETHING]\n",
        "__all__ = ['a']\n__all__ += _EXTRA\n",
        "__all__ = ['a']\n__all__.extend(_EXTRA)\n",
        "__all__ = ['a']\n__all__.append('b')\n",
    ],
)
def test_a_computed_dunder_all_reads_as_none(tmp_path: Path, source: str) -> None:
    """A partly-true export list is worse than none; the report warns instead."""
    assert census_of(tmp_path, source).dunder_all is None


def test_dunder_all_is_not_itself_an_entity(tmp_path: Path) -> None:
    assert census_of(tmp_path, "__all__ = ['find']\n").entities == ()


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def test_imports_are_recorded_in_source_order_with_their_names(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "import json\nimport os.path\nfrom pathlib import Path, PurePath\n",
    )
    assert [(i.module, i.names, i.line) for i in census.imports] == [
        ("json", (), 1),
        ("os.path", (), 2),
        ("pathlib", ("Path", "PurePath"), 3),
    ]


def test_one_import_statement_of_several_modules_is_several_facts(tmp_path: Path) -> None:
    census = census_of(tmp_path, "import json, csv\n")
    assert [(i.module, i.line) for i in census.imports] == [("csv", 1), ("json", 1)]


def test_a_star_import_records_the_star(tmp_path: Path) -> None:
    assert imported(census_of(tmp_path, "from os import *\n"), "os").names == ("*",)


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("from . import storage", "bookshelf"),
        ("from .storage import Store", "bookshelf.storage"),
        ("from .deep.store import Store", "bookshelf.deep.store"),
    ],
)
def test_relative_imports_resolve_against_the_modules_package(
    tmp_path: Path, statement: str, expected: str
) -> None:
    census = census_of(tmp_path, f"{statement}\n")
    assert census.imports[0].module == expected
    assert not census.imports[0].module.startswith(".")


def test_a_packages_own_init_resolves_relatives_against_itself(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "from . import catalog\nfrom .storage import Store\n",
        relative="bookshelf/__init__.py",
        module="bookshelf",
        role="package_marker",
    )
    assert [i.module for i in census.imports] == ["bookshelf", "bookshelf.storage"]


def test_a_relative_import_climbing_two_levels_resolves(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "from ..shared import helper\n",
        relative="bookshelf/api/handlers.py",
        module="bookshelf.api.handlers",
    )
    assert imported(census, "bookshelf.shared").origin == "unresolved"


@pytest.mark.parametrize(
    ("module", "statement", "expected"),
    [
        ("bookshelf.api", "from ..shared import helper", "..shared"),
        ("bookshelf.api", "from .. import shared", ".."),
        ("bookshelf.api", "from ...far import helper", "...far"),
        ("inventory", "from . import sibling", "."),
        ("inventory", "from .sibling import thing", ".sibling"),
    ],
)
def test_a_relative_import_beyond_the_top_keeps_its_written_form(
    tmp_path: Path, module: str, statement: str, expected: str
) -> None:
    """The agreed hand-off signal to the import graph (B2).

    A relative import that climbs past the top of the project is exactly
    what Python itself refuses ("attempted relative import beyond
    top-level package"). It cannot become a dotted name, so it keeps its
    written spelling and stays ``"unresolved"``. The leading dot is the
    signal ``adopt/graph.py`` matches on: a ``module`` that is empty or
    begins with ``"."`` is never resolved against a discovered module,
    and every import that *could* be resolved carries a plain dotted
    name with no leading dot.
    """
    relative = f"{module.replace('.', '/')}.py"
    census = census_of(tmp_path, f"{statement}\n", relative=relative, module=module)
    assert census.imports[0].module == expected
    assert census.imports[0].module.startswith(".")
    assert census.imports[0].origin == "unresolved"


def test_an_import_inside_a_function_is_deferred(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "import json\n\n\ndef load():\n    import csv\n\n    return csv, json\n",
    )
    assert imported(census, "json").deferred is False
    assert imported(census, "csv").deferred is True


def test_an_import_inside_a_method_is_deferred_too(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "class Store:\n    def load(self):\n        import csv\n\n        return csv\n",
    )
    assert imported(census, "csv").deferred is True


def test_an_import_in_a_class_body_is_not_deferred(tmp_path: Path) -> None:
    """The negative: a class body runs at import time, a function body does not."""
    census = census_of(tmp_path, "class Store:\n    import csv\n")
    assert imported(census, "csv").deferred is False


def test_a_type_checking_import_is_flagged_and_still_recorded(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n    from bookshelf.models import Book\n",
    )
    assert imported(census, "bookshelf.models").type_checking is True
    assert imported(census, "typing").type_checking is False


def test_typing_dot_type_checking_is_recognised(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "import typing\n\nif typing.TYPE_CHECKING:\n    from bookshelf.models import Book\n",
    )
    assert imported(census, "bookshelf.models").type_checking is True


def test_the_else_of_a_type_checking_block_is_the_runtime_branch(tmp_path: Path) -> None:
    """The negative: only the body never runs; the ``else:`` always does."""
    census = census_of(
        tmp_path,
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n    from bookshelf.fake import Book\n"
        "else:\n    from bookshelf.real import Book\n",
    )
    assert imported(census, "bookshelf.fake").type_checking is True
    assert imported(census, "bookshelf.real").type_checking is False


def test_an_import_inside_a_try_block_is_still_an_import(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "try:\n    import tomllib\nexcept ImportError:\n    import tomli as tomllib\n",
    )
    assert [i.module for i in census.imports] == ["tomllib", "tomli"]
    assert all(i.deferred is False for i in census.imports)


def test_origin_is_stdlib_only_where_the_interpreter_says_so(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        "import json\nimport os.path\nimport lark\nfrom bookshelf import models\n",
    )
    assert imported(census, "json").origin == "stdlib"
    assert imported(census, "os.path").origin == "stdlib"
    assert imported(census, "lark").origin == "unresolved"
    assert imported(census, "bookshelf").origin == "unresolved"


# ---------------------------------------------------------------------------
# Module-level facts
# ---------------------------------------------------------------------------


def test_main_guards_are_noticed_written_either_way_round(tmp_path: Path) -> None:
    assert census_of(tmp_path, 'if __name__ == "__main__":\n    pass\n').has_main_guard is True
    assert census_of(tmp_path, 'if "__main__" == __name__:\n    pass\n').has_main_guard is True
    assert census_of(tmp_path, 'if __name__ == "__console__":\n    pass\n').has_main_guard is False
    assert census_of(tmp_path, "def main():\n    return 1\n").has_main_guard is False


def test_the_ordinary_furniture_of_a_module_is_not_an_effect(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        '"""Catalog."""\n\n'
        "from __future__ import annotations\n\n"
        "import json\n"
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n    from bookshelf.models import Book\n\n"
        "MAX_LOANS = 5\n"
        "PENDING: int\n"
        "__all__ = ['find']\n\n\n"
        "def find():\n    return json\n\n\n"
        "class Shelf:\n    pass\n\n\n"
        'if __name__ == "__main__":\n    find()\n',
    )
    assert census.top_level_effects == 0


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("logger = logging.getLogger(__name__)\n", 1),
        ("register()\n", 1),
        ("for item in range(3):\n    print(item)\n", 1),
        ("logger = None\nregister()\n", 2),
        ("if FEATURE_ON:\n    enable()\n", 1),
        ("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    x = 1\n", 1),
        (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n    import csv\nelse:\n    csv = None\n",
            1,
        ),
        ("try:\n    import tomllib\nexcept ImportError:\n    tomllib = None\n", 1),
    ],
)
def test_work_that_runs_on_import_is_counted(
    tmp_path: Path, source: str, expected: int
) -> None:
    assert census_of(tmp_path, source).top_level_effects == expected


def test_lines_and_sloc_count_what_they_say(tmp_path: Path) -> None:
    census = census_of(
        tmp_path,
        '"""Catalog."""\n\n# a comment\n   \ndef find():\n    return 1\n',
    )
    assert census.lines == 6
    assert census.sloc == 3


def test_the_content_hash_matches_the_adopted_file_convention(tmp_path: Path) -> None:
    census = census_of(tmp_path, "MAX_LOANS = 5\n")
    assert census.content_hash == compute_adopted_hash(tmp_path / "bookshelf/catalog.py")
    assert census.content_hash.startswith("sha256:")


def test_a_crlf_checkout_censuses_exactly_like_an_lf_one(tmp_path: Path) -> None:
    """Windows CI is a real target: line endings must not move a number.

    Text-mode reading normalises ``\\r\\n`` before anything is measured
    or hashed, which is the same convention
    :func:`~s0ma_dsl.adoption.compute_adopted_hash` relies on — so a
    Windows checkout of the same commit produces the same census and the
    same hash as a POSIX one.
    """
    body = '"""Catalog."""\n\nimport json\n\n\ndef find():\n    return json\n'
    lf_census = census_of(tmp_path, body, relative="lf.py", module="lf")

    crlf = tmp_path / "crlf.py"
    crlf.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))
    crlf_census = census_file(
        tmp_path, SourceFile(path="crlf.py", module="crlf", source_root=".", role="app")
    )

    assert crlf_census.content_hash == lf_census.content_hash
    assert (crlf_census.lines, crlf_census.sloc) == (lf_census.lines, lf_census.sloc)
    assert [e.name for e in crlf_census.entities] == [e.name for e in lf_census.entities]
    assert [i.module for i in crlf_census.imports] == [i.module for i in lf_census.imports]


def test_a_file_without_a_trailing_newline_counts_its_last_line(tmp_path: Path) -> None:
    assert census_of(tmp_path, "MAX_LOANS = 5\nMIN_LOANS = 1").lines == 2


# ---------------------------------------------------------------------------
# Files that cannot be read
# ---------------------------------------------------------------------------


def test_a_syntax_error_is_a_fact_not_an_exception(tmp_path: Path) -> None:
    census = census_of(tmp_path, "MAX_LOANS = 5\ndef broken(:\n    return 1\n")
    assert census.parse_error is not None
    assert "not valid Python" in census.parse_error
    assert "line 2" in census.parse_error
    assert census.entities == ()
    assert census.imports == ()
    assert census.dunder_all is None
    assert census.top_level_effects == 0
    # The facts that survive a broken parse are still reported.
    assert census.lines == 3
    assert census.sloc == 3
    assert census.content_hash == compute_adopted_hash(tmp_path / "bookshelf/catalog.py")


def test_a_file_that_is_not_utf8_is_a_fact_not_an_exception(tmp_path: Path) -> None:
    path = tmp_path / "latin.py"
    path.write_bytes(b'VALUE = "caf\xe9"\n')
    source = SourceFile(path="latin.py", module="latin", source_root=".", role="app")
    census = census_file(tmp_path, source)
    assert census.parse_error is not None
    assert "UTF-8" in census.parse_error
    assert census.entities == ()
    assert census.imports == ()
    assert census.content_hash == f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def test_a_file_that_has_gone_missing_is_a_fact_not_an_exception(tmp_path: Path) -> None:
    source = SourceFile(path="vanished.py", module="vanished", source_root=".", role="app")
    census = census_file(tmp_path, source)
    assert census.parse_error is not None
    assert "could not be opened" in census.parse_error
    assert census.content_hash.startswith("sha256:")


def test_an_empty_file_is_an_ordinary_census(tmp_path: Path) -> None:
    census = census_of(tmp_path, "")
    assert census.parse_error is None
    assert census.lines == 0
    assert census.sloc == 0
    assert census.entities == ()


# ---------------------------------------------------------------------------
# Determinism and the zero-write promise
# ---------------------------------------------------------------------------


def test_the_same_file_censuses_identically_every_time(tmp_path: Path) -> None:
    source = (
        '"""Catalog."""\n\nimport json\n\n__all__ = ["find"]\n\n\n'
        "def find():\n    return json\n"
    )
    first = census_of(tmp_path, source)
    second = census_of(tmp_path, source)
    assert first == second
    assert first.to_dict() == second.to_dict()


def test_nothing_recorded_carries_an_absolute_path(tmp_path: Path) -> None:
    census = census_of(tmp_path, "import json\n")
    dumped = repr(census.to_dict())
    assert str(tmp_path) not in dumped
    assert "\\" not in census.source.path


def test_the_census_writes_nothing_at_all(tmp_path: Path) -> None:
    """Retrofit rule R-2, over a whole tree rather than one file."""
    (tmp_path / "src" / "demo").mkdir(parents=True)
    (tmp_path / "src" / "demo" / "__init__.py").write_text(
        '"""Demo."""\n', encoding="utf-8", newline="\n"
    )
    (tmp_path / "src" / "demo" / "service.py").write_text(
        "import json\n\n\ndef load():\n    return json\n", encoding="utf-8", newline="\n"
    )
    (tmp_path / "src" / "demo" / "broken.py").write_text(
        "def broken(:\n", encoding="utf-8", newline="\n"
    )
    (tmp_path / "src" / "demo" / "latin.py").write_bytes(b'VALUE = "caf\xe9"\n')

    sources = discover_sources(tmp_path)
    assert sources
    before = tree_fingerprint(tmp_path)
    for source in sources:
        census_file(tmp_path, source)
    assert tree_fingerprint(tmp_path) == before
    # The derived-surface cache is the one this rule exists to keep out.
    assert not (tmp_path / ".s0ma.cache").exists()


def test_nothing_in_the_tree_is_ever_imported(tmp_path: Path) -> None:
    """Retrofit rule R-1: a module that detonates on import censuses fine."""
    census = census_of(
        tmp_path,
        "import definitely_not_installed_anywhere\n\n"
        'raise SystemExit("this module must never be executed")\n',
    )
    assert census.parse_error is None
    assert imported(census, "definitely_not_installed_anywhere").origin == "unresolved"
    assert census.top_level_effects == 1
