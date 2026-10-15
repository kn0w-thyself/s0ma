"""Static surface reading — what a Python module promises, without running it (E1).

``s0ma_dsl/adopt/surface.py`` answers one question: what does this file
offer its callers? A conversion is only provably safe if that answer can
be taken before the conversion and again afterwards, so these tests lock
the three properties the rest of the retrofit family depends on:

- **Nothing is imported or executed.** A module whose top level would
  raise, write a file or import a package that is not installed still
  reads cleanly. That is retrofit rule R-1, and it is what makes a
  parity check impossible to fool with an import side effect.
- **Normalisation is the whole point.** Blank lines, comments, import
  order, quote style, trailing commas and where a long signature was
  wrapped must all be invisible. Each claim gets its own test, because a
  single "cosmetics do not matter" test that passes for the wrong reason
  would let the whole idea rot quietly.
- **Only real promises are recorded.** Public names, the two sanctioned
  dunder members, one level of nesting, and a computed value marked as
  computed rather than guessed at.

Sources are written inline into ``tmp_path`` — the reader takes a file
— and every one of them is deliberately small, so a failure points at
one rule rather than at a fixture.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from s0ma_dsl.adopt.model import ModuleSurface, SurfaceEntry, dump_json
from s0ma_dsl.adopt.surface import (
    SURFACE_DUNDER_MEMBERS,
    SURFACE_NON_LITERAL,
    SurfaceReadError,
    static_surface,
    surface_from_source,
)

#: The brownfield fixture application's noun module — real converted-shaped
#: Python, where the declared types E1b adds are the whole content of a
#: dataclass field.
_FIXTURE_MODELS = (
    Path(__file__).parent
    / "fixtures"
    / "brownfield"
    / "layered_app"
    / "src"
    / "bookshelf"
    / "models.py"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, source: str, *, name: str = "sample.py") -> Path:
    """Write *source* (dedented) to *name* under *tmp_path* and return the path."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(source), encoding="utf-8", newline="\n")
    return path


def _read(tmp_path: Path, source: str, *, name: str = "sample.py") -> ModuleSurface:
    """The surface of *source*, read from a real file as callers do."""
    return static_surface(_write(tmp_path, source, name=name), module="sample")


def _names(surface: ModuleSurface) -> list[str]:
    return [entry.name for entry in surface.entries]


def _entry(surface: ModuleSurface, name: str) -> SurfaceEntry:
    for entry in surface.entries:
        if entry.name == name:
            return entry
    raise AssertionError(f"{name!r} is not on the surface: {_names(surface)}")


# ---------------------------------------------------------------------------
# Categories and shape
# ---------------------------------------------------------------------------


def test_top_level_categories(tmp_path: Path) -> None:
    """Functions, async functions, classes and constants are told apart."""
    surface = _read(
        tmp_path,
        """
        def plain(): ...

        async def awaited(): ...

        class Shape: ...

        LIMIT = 10
        """,
    )
    categories = {entry.name: entry.category for entry in surface.entries}
    assert categories == {
        "plain": "function",
        "awaited": "async_function",
        "Shape": "class",
        "LIMIT": "constant",
    }


def test_class_members_are_flat_dotted_entries(tmp_path: Path) -> None:
    """A class contributes itself plus one ``Class.member`` entry per member."""
    surface = _read(
        tmp_path,
        """
        class Book:
            COUNT = 3
            title: str = "untitled"

            def borrow(self): ...

            async def fetch(self): ...
        """,
    )
    categories = {entry.name: entry.category for entry in surface.entries}
    assert categories == {
        "Book": "class",
        "Book.COUNT": "attribute",
        "Book.title": "attribute",
        "Book.borrow": "method",
        "Book.fetch": "async_method",
    }


def test_entries_are_sorted_and_class_members_follow_their_class(tmp_path: Path) -> None:
    """Sorting by name is what keeps two captures of one module identical."""
    surface = _read(
        tmp_path,
        """
        ZEBRA = 1

        class Book:
            def read(self): ...
            def annotate(self): ...

        def borrow(): ...
        """,
    )
    assert _names(surface) == sorted(_names(surface))
    assert _names(surface) == ["Book", "Book.annotate", "Book.read", "ZEBRA", "borrow"]


# ---------------------------------------------------------------------------
# Who is public
# ---------------------------------------------------------------------------


def test_underscore_names_are_not_on_the_surface(tmp_path: Path) -> None:
    """Leading underscore means private, at the top level and inside a class."""
    surface = _read(
        tmp_path,
        """
        _SECRET = 1

        def _helper(): ...

        class _Hidden: ...

        class Book:
            _cache = {}

            def _internal(self): ...

            def borrow(self): ...
        """,
    )
    assert _names(surface) == ["Book", "Book.borrow"]


def test_dunder_all_narrows_the_top_level_surface(tmp_path: Path) -> None:
    """A literal ``__all__`` is the module's own statement of what is public."""
    surface = _read(
        tmp_path,
        """
        __all__ = ["Book", "borrow"]

        LIMIT = 10

        class Book:
            def read(self): ...

        def borrow(): ...

        def lend(): ...
        """,
    )
    assert _names(surface) == ["Book", "Book.read", "borrow"]
    assert surface.dunder_all == ("Book", "borrow")


def test_dunder_all_keeps_its_declared_order(tmp_path: Path) -> None:
    """The record says what the module wrote; the comparer is what ignores order."""
    surface = _read(
        tmp_path,
        """
        __all__ = ["zebra", "apple"]

        def zebra(): ...

        def apple(): ...
        """,
    )
    assert surface.dunder_all == ("zebra", "apple")


def test_absent_dunder_all_is_none(tmp_path: Path) -> None:
    surface = _read(tmp_path, "def borrow(): ...\n")
    assert surface.dunder_all is None


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("computed", '__all__ = [name for name in ("borrow",)]\n'),
        ("built up", '__all__ = ["borrow"]\n__all__ += ["lend"]\n'),
        ("assigned twice", '__all__ = ["borrow"]\n__all__ = ["lend"]\n'),
        ("not strings", "__all__ = [borrow]\n"),
    ],
)
def test_dynamic_dunder_all_falls_back_to_the_underscore_rule(
    tmp_path: Path, label: str, source: str,
) -> None:
    """A list nobody can read statically is recorded as no list at all.

    Falling back to the underscore rule captures *more* names than the
    module may have meant to export, which is the safe direction: a
    surface that is too wide reports a change that is not one, while a
    surface that is too narrow misses a break.
    """
    surface = _read(tmp_path, source + "\ndef borrow(): ...\n\ndef lend(): ...\n")
    assert surface.dunder_all is None, label
    assert _names(surface) == ["borrow", "lend"], label


def test_only_init_and_call_dunder_members_are_captured(tmp_path: Path) -> None:
    """The sanctioned two are part of how a class is used; the rest are not."""
    surface = _read(
        tmp_path,
        """
        class Book:
            def __init__(self, title): ...

            def __call__(self): ...

            def __repr__(self): ...

            def __eq__(self, other): ...

            def __enter__(self): ...
        """,
    )
    assert _names(surface) == ["Book", "Book.__call__", "Book.__init__"]
    assert SURFACE_DUNDER_MEMBERS == ("__call__", "__init__")


def test_definitions_inside_if_or_try_are_not_promises(tmp_path: Path) -> None:
    """A conditional definition is not a surface a caller can rely on."""
    surface = _read(
        tmp_path,
        """
        import sys

        if sys.version_info >= (3, 12):
            def modern(): ...

        try:
            def attempted(): ...
        except Exception:
            pass

        def always(): ...
        """,
    )
    assert _names(surface) == ["always"]


def test_imported_names_are_not_entries_but_stay_in_dunder_all(tmp_path: Path) -> None:
    """An entry describes what the module defines; a re-export is still recorded."""
    surface = _read(
        tmp_path,
        """
        from collections import OrderedDict

        __all__ = ["OrderedDict", "borrow"]

        def borrow(): ...
        """,
    )
    assert _names(surface) == ["borrow"]
    assert surface.dunder_all == ("OrderedDict", "borrow")


# ---------------------------------------------------------------------------
# Signatures, decorators, bases, docstrings
# ---------------------------------------------------------------------------


def test_signature_records_every_parameter_form(tmp_path: Path) -> None:
    """Positional-only, defaults, ``*args``, keyword-only and ``**kwargs`` all show."""
    surface = _read(
        tmp_path,
        """
        def borrow(book, /, days=14, *extras: str, notify: bool = True, **rest) -> int: ...
        """,
    )
    assert _entry(surface, "borrow").signature == (
        "(book, /, days=14, *extras: str, notify: bool=True, **rest) -> int"
    )


def test_signature_keeps_self_and_cls(tmp_path: Path) -> None:
    """Dropping the receiver changes the calling convention — it must be visible."""
    surface = _read(
        tmp_path,
        """
        class Book:
            def borrow(self, days: int): ...

            @classmethod
            def make(cls): ...
        """,
    )
    assert _entry(surface, "Book.borrow").signature == "(self, days: int)"
    assert _entry(surface, "Book.make").signature == "(cls)"


def test_a_missing_return_annotation_is_not_invented(tmp_path: Path) -> None:
    surface = _read(tmp_path, "def borrow(): ...\n")
    assert _entry(surface, "borrow").signature == "()"


def test_decorators_are_unparsed_in_source_order(tmp_path: Path) -> None:
    """Order matters: two decorators applied the other way round behave differently."""
    surface = _read(
        tmp_path,
        """
        import functools

        @functools.lru_cache(maxsize=None)
        @staticmethod
        def borrow(): ...
        """,
    )
    assert _entry(surface, "borrow").decorators == (
        "functools.lru_cache(maxsize=None)",
        "staticmethod",
    )


def test_bases_include_class_keywords(tmp_path: Path) -> None:
    """A changed metaclass changes every instance, so it belongs on the surface."""
    surface = _read(
        tmp_path,
        """
        class Book(Item, mixins.Timestamped, metaclass=Registry, frozen=True): ...
        """,
    )
    assert _entry(surface, "Book").bases == (
        "Item",
        "mixins.Timestamped",
        "metaclass=Registry",
        "frozen=True",
    )


def test_docstrings_are_cleaned_not_copied(tmp_path: Path) -> None:
    """``inspect.cleandoc`` gives one canonical form for one piece of prose."""
    surface = _read(
        tmp_path,
        '''
        class Book:
            """A book.

            Second paragraph.
            """

            def borrow(self):
                """Borrow it."""
        ''',
    )
    assert _entry(surface, "Book").docstring == "A book.\n\nSecond paragraph."
    assert _entry(surface, "Book.borrow").docstring == "Borrow it."


def test_the_same_prose_at_different_depths_reads_the_same(tmp_path: Path) -> None:
    """How far a docstring was indented is an accident of where it was written.

    The selfhost friction log's F-M3-8 is the same lesson from the other
    side: raw docstring text differs between CPython versions and
    between nesting depths, and cleaning is what collapses both into one
    comparable string. A converted module writes its bodies at a
    different depth, so without this every moved definition would report
    a documentation change.
    """
    flat = _read(
        tmp_path,
        '''
        def borrow():
            """Borrow a book.

            Returns nothing.
            """
        ''',
        name="flat.py",
    )
    deep = _read(
        tmp_path,
        '''
        class Shelf:
            def borrow(self):
                """Borrow a book.

                Returns nothing.
                """
        ''',
        name="deep.py",
    )
    expected = "Borrow a book.\n\nReturns nothing."
    assert _entry(flat, "borrow").docstring == expected
    assert _entry(deep, "Shelf.borrow").docstring == expected


def test_no_docstring_is_none_not_empty(tmp_path: Path) -> None:
    surface = _read(tmp_path, "def borrow(): ...\n")
    assert _entry(surface, "borrow").docstring is None


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "recorded"),
    [
        ("10", "10"),
        ("1_000", "1000"),
        ('"text"', "'text'"),
        ("'text'", "'text'"),
        ("True", "True"),
        ("None", "None"),
        ("-1", "-1"),
        ("(1, 2)", "(1, 2)"),
        ('{"a": [1, 2]}', "{'a': [1, 2]}"),
        ("...", "..."),
    ],
)
def test_written_out_values_are_recorded_as_written(
    tmp_path: Path, written: str, recorded: str,
) -> None:
    """A literal is comparable, so it is kept — in one canonical rendering."""
    surface = _read(tmp_path, f"LIMIT = {written}\n")
    assert _entry(surface, "LIMIT").value == recorded


@pytest.mark.parametrize(
    "written",
    [
        "compute()",
        "OTHER",
        "1 + len('ab')",
        'f"{name}"',
        "[item for item in range(3)]",
        "lambda: 1",
    ],
)
def test_computed_values_are_marked_rather_than_guessed(tmp_path: Path, written: str) -> None:
    """Claiming to know a computed value statically would be a lie."""
    surface = _read(tmp_path, f"LIMIT = {written}\n")
    assert _entry(surface, "LIMIT").value == SURFACE_NON_LITERAL


def test_a_name_declared_without_a_value_has_none(tmp_path: Path) -> None:
    """``count: int`` promises a name, not a value."""
    surface = _read(
        tmp_path,
        """
        class Book:
            title: str
        """,
    )
    entry = _entry(surface, "Book.title")
    assert entry.category == "attribute"
    assert entry.value is None


def test_unpacked_names_are_marked_as_computed(tmp_path: Path) -> None:
    """No single written-out value belongs to either name in ``A, B = ...``."""
    surface = _read(tmp_path, "FIRST, SECOND = 1, 2\n")
    assert [entry.value for entry in surface.entries] == [SURFACE_NON_LITERAL] * 2
    assert _names(surface) == ["FIRST", "SECOND"]


def test_chained_assignment_records_both_names(tmp_path: Path) -> None:
    surface = _read(tmp_path, "FIRST = SECOND = 5\n")
    assert [(entry.name, entry.value) for entry in surface.entries] == [
        ("FIRST", "5"),
        ("SECOND", "5"),
    ]


# ---------------------------------------------------------------------------
# Declared types (E1b)
#
# The point of the milestone: a dataclass field changing from ``str`` to
# ``int`` changes nothing else about its entry, so without an annotation
# it would pass a parity check in silence.
# ---------------------------------------------------------------------------


def test_a_class_attribute_records_its_declared_type(tmp_path: Path) -> None:
    """``title: str`` records ``"str"`` and no value; it binds nothing."""
    surface = _read(
        tmp_path,
        """
        class Book:
            title: str
        """,
    )
    entry = _entry(surface, "Book.title")
    assert entry.category == "attribute"
    assert entry.annotation == "str"
    assert entry.value is None


def test_a_declared_type_and_a_value_are_both_recorded(tmp_path: Path) -> None:
    """``copies: int = 1`` is two separate promises, and both are kept."""
    surface = _read(
        tmp_path,
        """
        class Book:
            copies: int = 1
        """,
    )
    entry = _entry(surface, "Book.copies")
    assert entry.annotation == "int"
    assert entry.value == "1"


def test_a_module_constant_records_its_declared_type(tmp_path: Path) -> None:
    surface = _read(tmp_path, "LIMIT: int = 10\n")
    entry = _entry(surface, "LIMIT")
    assert entry.category == "constant"
    assert entry.annotation == "int"
    assert entry.value == "10"


def test_an_un_annotated_assignment_declares_no_type(tmp_path: Path) -> None:
    """Un-annotated is ``None``, not ``""`` — nothing was promised."""
    surface = _read(
        tmp_path,
        """
        LIMIT = 10

        class Book:
            tags = ["new"]
        """,
    )
    assert _entry(surface, "LIMIT").annotation is None
    assert _entry(surface, "Book.tags").annotation is None


def test_unpacked_and_chained_assignments_declare_no_type(tmp_path: Path) -> None:
    """Neither form can be annotated in Python, so neither invents one."""
    surface = _read(tmp_path, "FIRST, SECOND = 1, 2\nTHIRD = FOURTH = 3\n")
    assert [entry.annotation for entry in surface.entries] == [None] * 4


def test_callables_and_classes_declare_no_type(tmp_path: Path) -> None:
    """Their types live in ``signature`` and ``bases``; recording them twice
    would make one change read as two findings."""
    surface = _read(
        tmp_path,
        """
        def borrow(book: str) -> bool: ...

        async def fetch(book: str) -> bytes: ...

        class Book(Item):
            def read(self) -> str: ...
        """,
    )
    assert [entry.annotation for entry in surface.entries] == [None] * 4
    assert _entry(surface, "borrow").signature == "(book: str) -> bool"


@pytest.mark.parametrize(
    ("written", "recorded"),
    [
        ("Final[int]", "Final[int]"),
        ("ClassVar[str]", "ClassVar[str]"),
        ("list[Book] | None", "list[Book] | None"),
        ("dict[str, int]", "dict[str, int]"),
        # A quoted forward reference is recorded as written — a reader
        # that never imports the module cannot resolve it, and should
        # not pretend to. Only the quote style is normalised.
        ('"Book"', "'Book'"),
        ("'Book'", "'Book'"),
    ],
)
def test_declared_types_are_recorded_as_written(
    tmp_path: Path, written: str, recorded: str,
) -> None:
    surface = _read(
        tmp_path,
        f"""
        class Shelf:
            held: {written}
        """,
    )
    assert _entry(surface, "Shelf.held").annotation == recorded


def test_a_module_level_bare_annotation_stays_on_the_surface(tmp_path: Path) -> None:
    """E1b ruling: today's behaviour is kept, so one rule covers both levels.

    ``current: Session`` at module level binds nothing at all — reading
    the name before something assigns it raises ``NameError``. It is
    still a promise the module makes about a name it will have, callers
    write ``module.current`` against it, and the class-level form of
    exactly the same statement is a dataclass field. Two rules for one
    syntax would be the surprising choice, so it is recorded as it
    already was: an entry, with a value of ``None``.
    """
    surface = _read(tmp_path, "current: Session\n")
    entry = _entry(surface, "current")
    assert entry.category == "constant"
    assert entry.annotation == "Session"
    assert entry.value is None


def test_a_dataclass_field_that_changes_type_changes_the_surface(tmp_path: Path) -> None:
    """The headline: this is what E1b exists to stop passing in silence."""
    before = """
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class Book:
            isbn: str
            copies: int = 1
    """
    after = before.replace("copies: int = 1", "copies: str = 1")

    original = _read(tmp_path, before, name="before.py")
    converted = _read(tmp_path, after, name="after.py")

    assert original != converted
    changed = _entry(original, "Book.copies"), _entry(converted, "Book.copies")
    assert (changed[0].annotation, changed[1].annotation) == ("int", "str")
    # Nothing else about the entry moved: without the annotation the two
    # would have compared equal.
    assert changed[0].value == changed[1].value
    assert changed[0].category == changed[1].category
    assert _entry(original, "Book.isbn") == _entry(converted, "Book.isbn")


def test_annotation_quote_style_does_not_change_the_surface(tmp_path: Path) -> None:
    """A forward reference is normalised like every other written value."""
    double = 'class Shelf:\n    held: "Book"\n'
    single = "class Shelf:\n    held: 'Book'\n"
    assert _read(tmp_path, double, name="double.py") == _read(
        tmp_path, single, name="single.py",
    )


# ---------------------------------------------------------------------------
# Declared types over the fixture application (E1b)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _FIXTURE_MODELS.is_file(),
    reason=f"the brownfield fixture application is not present at {_FIXTURE_MODELS}",
)
def test_the_fixture_dataclasses_carry_their_declared_types() -> None:
    """Real converted-shaped Python, not an inline sample of four lines."""
    surface = static_surface(_FIXTURE_MODELS, module="bookshelf.models")
    annotated = {
        entry.name: entry.annotation
        for entry in surface.entries
        if entry.annotation is not None
    }

    # Every dataclass, TypedDict and NamedTuple field in the module, and
    # nothing else: 17 names that would otherwise compare only on a
    # value none of them has.
    assert len(annotated) == 17
    assert annotated["Book.isbn"] == "str"
    assert annotated["Book.copies"] == "int"
    assert annotated["Loan.window"] == "LoanWindow"
    assert annotated["Loan.renewals"] == "int"
    assert annotated["LoanWindow.due"] == "date"
    assert annotated["BookRecord.title"] == "str"
    assert sorted(annotated) == [
        "Book.author",
        "Book.copies",
        "Book.isbn",
        "Book.title",
        "BookRecord.author",
        "BookRecord.copies",
        "BookRecord.isbn",
        "BookRecord.title",
        "Loan.card_number",
        "Loan.isbn",
        "Loan.renewals",
        "Loan.window",
        "LoanWindow.due",
        "LoanWindow.start",
        "Member.card_number",
        "Member.email",
        "Member.name",
    ]

    # `date` is only ever imported under `if TYPE_CHECKING:` in that
    # module, and `from __future__ import annotations` is in force — the
    # exact combination that defeats a runtime reader (F-M2-5). Reading
    # the syntax tree is untroubled by either.
    assert "LoanWindow.start" in annotated
    # Methods and classes stay unannotated even in a dataclass-heavy module.
    assert _entry(surface, "Book.label").annotation is None
    assert _entry(surface, "Book").annotation is None
    # The enum's members are assigned, not declared, so they keep values
    # and no type.
    assert _entry(surface, "Availability.ON_LOAN").annotation is None
    assert _entry(surface, "Availability.ON_LOAN").value == "'on_loan'"


# ---------------------------------------------------------------------------
# Normalisation — one claim per test (E1.T2)
# ---------------------------------------------------------------------------

_PLAIN = '''
"""A shelf."""
import os
import sys

__all__ = ["Book", "borrow"]

LIMIT = 10

class Book(Item):
    """A book."""

    tags = ["new", "loan"]

    def borrow(self, days: int = 14, *, notify: bool = True) -> bool:
        """Borrow it."""
'''


def _plain(tmp_path: Path) -> ModuleSurface:
    return _read(tmp_path, _PLAIN, name="plain.py")


def test_blank_lines_do_not_change_the_surface(tmp_path: Path) -> None:
    spaced = _PLAIN.replace("\n\n", "\n\n\n\n")
    assert _read(tmp_path, spaced, name="spaced.py") == _plain(tmp_path)


def test_comments_do_not_change_the_surface(tmp_path: Path) -> None:
    commented = _PLAIN.replace(
        "LIMIT = 10", "# how many books at once\nLIMIT = 10  # trailing note",
    )
    assert _read(tmp_path, commented, name="commented.py") == _plain(tmp_path)


def test_import_order_does_not_change_the_surface(tmp_path: Path) -> None:
    reordered = _PLAIN.replace("import os\nimport sys", "import sys\nimport os")
    assert _read(tmp_path, reordered, name="reordered.py") == _plain(tmp_path)


def test_quote_style_does_not_change_the_surface(tmp_path: Path) -> None:
    requoted = _PLAIN.replace('["new", "loan"]', "['new', 'loan']").replace(
        '__all__ = ["Book", "borrow"]', "__all__ = ['Book', 'borrow']",
    )
    assert _read(tmp_path, requoted, name="requoted.py") == _plain(tmp_path)


def test_trailing_commas_do_not_change_the_surface(tmp_path: Path) -> None:
    trailing = _PLAIN.replace('["new", "loan"]', '["new", "loan",]').replace(
        "notify: bool = True) -> bool", "notify: bool = True,) -> bool",
    )
    assert _read(tmp_path, trailing, name="trailing.py") == _plain(tmp_path)


def test_a_wrapped_signature_does_not_change_the_surface(tmp_path: Path) -> None:
    wrapped = _PLAIN.replace(
        "    def borrow(self, days: int = 14, *, notify: bool = True) -> bool:",
        "    def borrow(\n"
        "        self,\n"
        "        days: int = 14,\n"
        "        *,\n"
        "        notify: bool = True,\n"
        "    ) -> bool:",
    )
    assert _read(tmp_path, wrapped, name="wrapped.py") == _plain(tmp_path)


def test_future_annotations_do_not_change_the_surface(tmp_path: Path) -> None:
    """The F-M2-5 trap cannot reach a reader that never imports anything.

    Adding ``from __future__ import annotations`` changes what
    ``inspect.signature`` prints at runtime — stringified annotations —
    which is exactly how a runtime comparator false-positives across a
    conversion. Reading the syntax tree sees the same signature either
    way.
    """
    futured = _PLAIN.replace(
        '"""A shelf."""', '"""A shelf."""\nfrom __future__ import annotations',
    )
    assert _read(tmp_path, futured, name="futured.py") == _plain(tmp_path)


# ---------------------------------------------------------------------------
# Nesting, redefinition, properties
# ---------------------------------------------------------------------------


def test_a_nested_class_is_recorded_one_level_deep(tmp_path: Path) -> None:
    """The nested class itself is a promise; its members are out of shape."""
    surface = _read(
        tmp_path,
        '''
        class Book:
            class Meta:
                """How it is stored."""

                indexed = True

                def describe(self): ...
        ''',
    )
    assert _names(surface) == ["Book", "Book.Meta"]
    assert _entry(surface, "Book.Meta").category == "class"
    assert _entry(surface, "Book.Meta").docstring == "How it is stored."


def test_a_function_inside_a_function_is_not_on_the_surface(tmp_path: Path) -> None:
    surface = _read(
        tmp_path,
        """
        def borrow():
            def inner(): ...
            return inner
        """,
    )
    assert _names(surface) == ["borrow"]


def test_a_name_defined_twice_keeps_the_last_definition(tmp_path: Path) -> None:
    """The interpreter keeps the last one, so the surface does too."""
    surface = _read(
        tmp_path,
        """
        def borrow(days): ...

        def borrow(days, *, notify): ...
        """,
    )
    assert _entry(surface, "borrow").signature == "(days, *, notify)"


def test_a_redefined_class_does_not_leave_stale_members_behind(tmp_path: Path) -> None:
    surface = _read(
        tmp_path,
        """
        class Book:
            def read(self): ...

        class Book:
            def borrow(self): ...
        """,
    )
    assert _names(surface) == ["Book", "Book.borrow"]


def test_a_property_pair_records_the_setter(tmp_path: Path) -> None:
    """Last definition wins, so dropping the setter shows up as a change."""
    surface = _read(
        tmp_path,
        """
        class Book:
            @property
            def title(self) -> str: ...

            @title.setter
            def title(self, value: str) -> None: ...
        """,
    )
    entry = _entry(surface, "Book.title")
    assert entry.decorators == ("title.setter",)
    assert entry.signature == "(self, value: str) -> None"


# ---------------------------------------------------------------------------
# Never imported, never executed (R-1)
# ---------------------------------------------------------------------------


def test_reading_a_module_never_runs_it(tmp_path: Path) -> None:
    """The proof that a parity check cannot be fooled by an import side effect."""
    sentinel = tmp_path / "ran.txt"
    surface = _read(
        tmp_path,
        f"""
        import pathlib

        pathlib.Path({str(sentinel)!r}).write_text("ran", encoding="utf-8")

        raise RuntimeError("this module refuses to be imported")

        def borrow(): ...
        """,
    )
    assert not sentinel.exists()
    assert _names(surface) == ["borrow"]


def test_a_module_whose_imports_are_missing_still_reads(tmp_path: Path) -> None:
    surface = _read(
        tmp_path,
        """
        import definitely_not_an_installed_package as missing

        def borrow() -> missing.Thing: ...
        """,
    )
    assert _entry(surface, "borrow").signature == "() -> missing.Thing"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_file_that_is_not_there_is_refused_with_advice(tmp_path: Path) -> None:
    with pytest.raises(SurfaceReadError) as caught:
        static_surface(tmp_path / "gone.py")
    message = str(caught.value)
    assert "gone.py" in message
    assert "version control" in message


def test_invalid_python_is_refused_with_the_line(tmp_path: Path) -> None:
    path = _write(tmp_path, "def borrow(\n")
    with pytest.raises(SurfaceReadError) as caught:
        static_surface(path)
    message = str(caught.value)
    assert "not valid Python" in message
    assert "line" in message


def test_a_file_that_is_not_utf8_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "latin.py"
    path.write_bytes(b'TITLE = "caf\xe9"\n')
    with pytest.raises(SurfaceReadError) as caught:
        static_surface(path)
    assert "UTF-8" in str(caught.value)


def test_reading_source_text_names_the_module_when_it_cannot_parse() -> None:
    with pytest.raises(SurfaceReadError) as caught:
        surface_from_source("def borrow(\n", "bookshelf.lending")
    assert "bookshelf.lending" in str(caught.value)


# ---------------------------------------------------------------------------
# Determinism and module naming
# ---------------------------------------------------------------------------


def test_two_reads_of_one_file_are_identical(tmp_path: Path) -> None:
    path = _write(tmp_path, _PLAIN)
    first = static_surface(path, module="sample")
    second = static_surface(path, module="sample")
    assert first == second
    assert dump_json(first.to_dict()) == dump_json(second.to_dict())


def test_non_ascii_prose_survives_the_reading(tmp_path: Path) -> None:
    surface = _read(
        tmp_path,
        '''
        def prêter():
            """Prêter un livre — déjà."""
        ''',
    )
    assert _entry(surface, "prêter").docstring == "Prêter un livre — déjà."


def test_the_module_name_is_recorded_as_given(tmp_path: Path) -> None:
    path = _write(tmp_path, "def borrow(): ...\n")
    assert static_surface(path, module="bookshelf.lending").module == "bookshelf.lending"


def test_without_a_module_name_the_filename_stands_in(tmp_path: Path) -> None:
    """Enough for a one-off read; the store always passes the dotted name."""
    flat = _write(tmp_path, "def borrow(): ...\n", name="lending.py")
    package = _write(tmp_path, "def borrow(): ...\n", name="bookshelf/__init__.py")
    assert static_surface(flat).module == "lending"
    assert static_surface(package).module == "bookshelf"
