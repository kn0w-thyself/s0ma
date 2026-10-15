"""``compare_surfaces``: did the conversion change what the module promised?

The comparer is the whole reason a baseline is worth taking. It reads
two surfaces — one captured from the original Python, one read back from
the module ``s0ma build`` emitted — and says, name by name, what moved.

Three promises are tested here, each with a section of its own.

**Every kind of difference is reported.** A name gone or new, a
signature, a declared type, a docstring, a base class, a decorator, a
constant's value: eight kinds, and the list is not retyped here — it is
read off :class:`~s0ma_dsl.adopt.model.ParityFinding`'s own docstring,
which is the only place it is written down, so a kind that is
constructed but never documented fails.

**What the build adds is ignored, and only that.** Every entry of
:data:`~s0ma_dsl.adopt.parity.EMITTER_ADDITIONS` is tested twice over:
once with the emitter's own construct, which must produce no finding at
all, and once with the nearest thing a *person* writes, dropped in the
conversion, which must produce one. A table in this module pairs each
entry with its two cases and is checked against the list itself, so an
entry cannot be added to the ignore list without a case that shows it is
narrow.

**The report reads the same way twice.** Findings come back sorted by
symbol and then kind, the rendered text is one line per finding, and the
JSON document carries the schema string agents match on.

Everything below builds its surfaces out of real Python source through
:func:`~s0ma_dsl.adopt.surface.surface_from_source`, rather than
assembling :class:`~s0ma_dsl.adopt.model.SurfaceEntry` values by hand. A
comparer tested against hand-built entries proves only that it agrees
with the test author about what a reader would have seen.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from s0ma_dsl.adopt.model import ParityFinding, dump_json
from s0ma_dsl.adopt.parity import (
    EMITTER_ADDITIONS,
    FINDING_PHRASES,
    IGNORED_DECORATORS,
    PARITY_SCHEMA,
    compare_surfaces,
    parity_document,
    render_parity_text,
)
from s0ma_dsl.adopt.surface import surface_from_source

MODULE = "bookshelf.errors"

#: The eight kinds, read out of the model's own docstring rather than
#: restated. ``ParityFinding.kind`` is a plain string, so the docstring
#: is the only list there is and a second copy would drift from it.
DOCUMENTED_KINDS = tuple(
    sorted(
        {
            phrase.strip('"')
            for phrase in (ParityFinding.__doc__ or "").split("``")
            if phrase.startswith('"') and phrase.endswith('"')
        }
    )
)


def _compare(before: str, after: str) -> tuple[ParityFinding, ...]:
    """Compare two module sources and return the findings."""
    result = compare_surfaces(
        surface_from_source(before, MODULE),
        surface_from_source(after, MODULE),
        built_path="bookshelf_build/errors.py",
    )
    return result.findings


def _one(before: str, after: str) -> ParityFinding:
    """The single finding two sources must produce, or a failure that says so."""
    findings = _compare(before, after)
    assert len(findings) == 1, [
        (finding.kind, finding.symbol, finding.before, finding.after)
        for finding in findings
    ]
    return findings[0]


# ---------------------------------------------------------------------------
# The kinds
# ---------------------------------------------------------------------------


class TestEveryKindOfDifferenceIsReported:
    """One test per kind, each with the smallest source that shows it."""

    def test_the_documented_kinds_are_the_eight_the_plan_froze(self) -> None:
        """Anti-vacuity: the list read off the docstring has to be the real one."""
        assert DOCUMENTED_KINDS == (
            "annotation_changed",
            "bases_changed",
            "decorators_changed",
            "doc_changed",
            "extra",
            "missing",
            "signature_changed",
            "value_changed",
        )

    def test_a_name_that_is_gone(self) -> None:
        finding = _one(
            "LIBRARY = 'Fennel Street'\n\n\ndef shelve(book: str) -> None:\n    pass\n",
            "LIBRARY = 'Fennel Street'\n",
        )
        assert finding.kind == "missing"
        assert finding.symbol == "shelve"
        assert finding.before == "a function (book: str) -> None"
        assert finding.after is None
        assert "does not have it" in finding.detail

    def test_a_name_that_is_new(self) -> None:
        finding = _one(
            "LIBRARY = 'Fennel Street'\n",
            "LIBRARY = 'Fennel Street'\n\n\ndef shelve(book: str) -> None:\n    pass\n",
        )
        assert finding.kind == "extra"
        assert finding.symbol == "shelve"
        assert finding.before is None
        assert finding.after == "a function (book: str) -> None"

    def test_a_signature(self) -> None:
        finding = _one(
            "def shelve(book: str) -> None:\n    pass\n",
            "def shelve(book: str, shelf: int = 1) -> None:\n    pass\n",
        )
        assert finding.kind == "signature_changed"
        assert finding.before == "(book: str) -> None"
        assert finding.after == "(book: str, shelf: int=1) -> None"

    def test_a_declared_type_on_a_dataclass_field(self) -> None:
        """E1b's case, which is why ``annotation`` is on the surface at all."""
        finding = _one(
            "class Book:\n    title: str\n",
            "class Book:\n    title: int\n",
        )
        assert finding.kind == "annotation_changed"
        assert finding.symbol == "Book.title"
        assert (finding.before, finding.after) == ("str", "int")

    def test_a_base_class(self) -> None:
        finding = _one(
            "class BookNotFoundError(CatalogError):\n    pass\n",
            "class BookNotFoundError(Exception):\n    pass\n",
        )
        assert finding.kind == "bases_changed"
        assert (finding.before, finding.after) == ("CatalogError", "Exception")

    def test_a_constants_value(self) -> None:
        finding = _one("LOAN_DAYS = 21\n", "LOAN_DAYS = 14\n")
        assert finding.kind == "value_changed"
        assert (finding.before, finding.after) == ("21", "14")

    def test_a_value_that_stopped_being_written_out(self) -> None:
        """A literal replaced by a call is a change even though neither is comparable."""
        finding = _one("LOAN_DAYS = 21\n", "LOAN_DAYS = _from_config()\n")
        assert finding.kind == "value_changed"
        assert finding.after == "<non-literal>"

    def test_a_docstring_that_was_rewritten(self) -> None:
        finding = _one(
            'def shelve() -> None:\n    """Put a book back."""\n',
            'def shelve() -> None:\n    """Return a book to its shelf."""\n',
        )
        assert finding.kind == "doc_changed"
        assert finding.before == "Put a book back."

    @pytest.mark.parametrize(
        "decorator",
        ["functools.lru_cache(maxsize=1)", "staticmethod", "classmethod", "property"],
    )
    def test_a_decorator_the_conversion_dropped(self, decorator: str) -> None:
        """Each of these is behaviour, and losing one changes what a caller gets."""
        finding = _one(
            f"class Catalog:\n    @{decorator}\n    def sections() -> int:\n        return 1\n",
            "class Catalog:\n    def sections() -> int:\n        return 1\n",
        )
        assert finding.kind == "decorators_changed"
        assert finding.symbol == "Catalog.sections"
        assert (finding.before, finding.after) == (decorator, "none")

    def test_a_function_that_stopped_being_awaitable(self) -> None:
        """What something *is* changes: one finding naming both shapes, not five."""
        finding = _one(
            "async def remind(member: str) -> None:\n    pass\n",
            "def remind(member: str) -> None:\n    pass\n",
        )
        assert finding.kind == "signature_changed"
        assert finding.before == "an async function (member: str) -> None"
        assert finding.after == "a function (member: str) -> None"

    def test_a_name_dropped_from_dunder_all_that_nobody_defines(self) -> None:
        """A re-export is nobody's entry, and losing one still breaks callers."""
        finding = _one(
            "from .models import Book\n\n__all__ = ['Book']\n",
            "from .models import Book\n\n__all__ = []\n",
        )
        assert finding.kind == "missing"
        assert finding.symbol == "Book"
        assert finding.before == "an exported name"
        assert "passed through from somewhere else" in finding.detail

    def test_every_kind_this_comparer_builds_is_a_documented_one(self) -> None:
        """The anti-drift link: nothing may be constructed that is not written down."""
        assert set(FINDING_PHRASES) == set(DOCUMENTED_KINDS)


# ---------------------------------------------------------------------------
# Documentation: arriving is not a finding, changing is
# ---------------------------------------------------------------------------


class TestTheDocstringRule:
    """A conversion adds meaning on purpose; it must not lose it by accident."""

    def test_a_docstring_where_there_was_none_is_not_a_finding(self) -> None:
        """Nobody could have depended on its absence, so nothing broke.

        This is the case the retrofit really produces: the draft's
        authored ``intent:`` becomes the built module's docstring, and a
        Python file that carried none would otherwise fail parity for
        having been documented.
        """
        assert not _compare(
            "class Book:\n    pass\n",
            'class Book:\n    """One title in the catalogue."""\n',
        )

    def test_a_docstring_that_disappeared_is_a_finding(self) -> None:
        finding = _one(
            'class Book:\n    """One title in the catalogue."""\n',
            "class Book:\n    pass\n",
        )
        assert finding.kind == "doc_changed"
        assert finding.before == "One title in the catalogue."
        assert finding.after is None

    def test_indentation_alone_is_never_a_finding(self) -> None:
        """E1 cleans docstrings, and a converted body sits at another depth."""
        assert not _compare(
            'def shelve() -> None:\n    """Put it back.\n\n    Where it came from.\n    """\n',
            'def shelve() -> None:\n    """Put it back.\n\nWhere it came from."""\n',
        )


# ---------------------------------------------------------------------------
# The ignore list: what the build adds, and only that
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IgnoreCase:
    """Two sources for one ignore-list entry: the safe pair and the real one.

    ``ignored`` is (baseline, built) where the built side carries the
    emitter's own construct — it must compare clean. ``authored`` is
    (baseline, built) where the *person's* nearest equivalent was
    dropped in the conversion — it must produce ``kind`` on ``symbol``.
    Without the second half an ignore rule could be arbitrarily wide and
    still pass.
    """

    ignored: tuple[str, str]
    authored: tuple[str, str]
    kind: str
    symbol: str


#: The emitted header, as ``s0ma build`` really writes it. Read off a
#: converted ``bookshelf.errors`` rather than composed: the point of the
#: ignore list is that it describes real output.
EMITTED_HEADER = (
    '"""errors — Every error the lending service raises on purpose.\n'
    "\n"
    "Auto-generated by s0ma DSL transpiler.\n"
    'Do not edit manually — edit the .s0ma source instead.\n'
    '"""\n'
    "# s0ma-source-hash: sha256:fc9b60380c6ddc2e\n"
    "# s0ma-output-hash: sha256:7707efd4af8b612b\n"
    "# s0ma: generated from src/bookshelf/errors.s0ma — edit the .s0ma source.\n"
)

#: The import block and registration calls a generated module carries.
EMITTED_RUNTIME = (
    "from s0ma.decorators import component\n"
    "from s0ma.types import ComponentKind, Layer\n"
    "from s0ma_dsl.runtime_bridge.registration import register_constant, register_module\n"
    "\n"
    "register_module(\n"
    '    name="errors",\n'
    "    layer=Layer.DOMAIN,\n"
    '    intent="Every error the lending service raises on purpose.",\n'
    ")\n"
)

#: The registration decorator, as emitted above a cell.
EMITTED_COMPONENT = (
    "@component(\n"
    '    name="BookshelfError",\n'
    "    kind=ComponentKind.MODEL,\n"
    "    layer=Layer.DOMAIN,\n"
    '    intent="Every error the lending service raises on purpose.",\n'
    '    metadata={"visibility": "PUBLIC", "kind_detail": "EXCEPTION"},\n'
    ")\n"
    "# s0ma: src/bookshelf/errors.s0ma:41 (cell BookshelfError)\n"
)

#: One case per entry of ``EMITTER_ADDITIONS``, keyed by its
#: ``construct``. The keys are checked against the list itself, so an
#: entry without a case fails rather than passing unproved.
IGNORE_CASES: dict[str, IgnoreCase] = {
    "@component(...)": IgnoreCase(
        ignored=(
            "class BookshelfError(Exception):\n    pass\n",
            f"{EMITTED_COMPONENT}class BookshelfError(Exception):\n    pass\n",
        ),
        authored=(
            "import functools\n\n\n"
            "@functools.lru_cache(maxsize=1)\n"
            "def shelf_sections() -> tuple[str, ...]:\n"
            "    return ()\n",
            "import functools\n\n\n"
            "def shelf_sections() -> tuple[str, ...]:\n"
            "    return ()\n",
        ),
        kind="decorators_changed",
        symbol="shelf_sections",
    ),
    "the generated __all__ and its ordering": IgnoreCase(
        ignored=(
            "__all__ = ['shelve', 'Book']\n\n\n"
            "class Book:\n    pass\n\n\n"
            "def shelve() -> None:\n    pass\n",
            "__all__ = ['Book', 'shelve']\n\n\n"
            "class Book:\n    pass\n\n\n"
            "def shelve() -> None:\n    pass\n",
        ),
        authored=(
            "__all__ = ['Book', 'shelve']\n\n\n"
            "class Book:\n    pass\n\n\n"
            "def shelve() -> None:\n    pass\n",
            "__all__ = ['Book']\n\n\n"
            "class Book:\n    pass\n\n\n"
            "def shelve() -> None:\n    pass\n",
        ),
        kind="missing",
        symbol="shelve",
    ),
    "the generated module docstring, hash headers and source-reference comments": IgnoreCase(
        ignored=(
            '"""Every error the lending service raises on purpose."""\n\n\n'
            "# The base of the hierarchy.\n"
            'class BookshelfError(Exception):\n    """Base class."""\n',
            f"{EMITTED_HEADER}\n\n"
            f"{EMITTED_COMPONENT}"
            'class BookshelfError(Exception):\n    """Base class."""\n',
        ),
        authored=(
            'class BookshelfError(Exception):\n    """Base class."""\n',
            'class BookshelfError(Exception):\n    """The base of the hierarchy."""\n',
        ),
        kind="doc_changed",
        symbol="BookshelfError",
    ),
    "the runtime import block and its register_* calls": IgnoreCase(
        ignored=(
            "LOAN_DAYS = 21\n",
            f"{EMITTED_RUNTIME}\nLOAN_DAYS = 21\n"
            "register_constant(\n"
            '    name="LOAN_DAYS",\n'
            '    module_path="errors",\n'
            "    layer=Layer.DOMAIN,\n"
            ")\n",
        ),
        authored=("RENEWALS = 2\nLOAN_DAYS = 21\n", "RENEWALS = 2\n"),
        kind="missing",
        symbol="LOAN_DAYS",
    ),
}


class TestTheIgnoreListIsNarrow:
    """Each entry proved twice: it covers the build's construct and nothing else."""

    def test_every_entry_has_a_case(self) -> None:
        """An ignore rule nobody demonstrated is an ignore rule nobody checked."""
        assert set(IGNORE_CASES) == {
            addition.construct for addition in EMITTER_ADDITIONS
        }

    def test_every_entry_says_why_it_is_safe(self) -> None:
        """The comment per entry is part of the contract, not decoration."""
        for addition in EMITTER_ADDITIONS:
            assert len(addition.why) > 100, addition.construct

    def test_the_operative_decorator_set_comes_from_the_list(self) -> None:
        """One named constant, and the behaviour reads from it."""
        named = {
            addition.decorator
            for addition in EMITTER_ADDITIONS
            if addition.decorator is not None
        }
        assert set(IGNORED_DECORATORS) == named
        assert sorted(IGNORED_DECORATORS) == ["component"]

    @pytest.mark.parametrize("construct", sorted(IGNORE_CASES))
    def test_what_the_build_adds_produces_no_finding(self, construct: str) -> None:
        case = IGNORE_CASES[construct]
        findings = _compare(*case.ignored)
        assert not findings, [
            (finding.kind, finding.symbol, finding.before, finding.after)
            for finding in findings
        ]

    @pytest.mark.parametrize("construct", sorted(IGNORE_CASES))
    def test_the_same_thing_written_by_a_person_is_reported(
        self, construct: str
    ) -> None:
        case = IGNORE_CASES[construct]
        finding = _one(*case.authored)
        assert (finding.kind, finding.symbol) == (case.kind, case.symbol)

    def test_a_registration_decorator_is_dropped_from_both_sides(self) -> None:
        """Track A: a file registered in place carries one before the conversion.

        Dropping it from the baseline too means such a project neither
        gains a finding for a decorator the build re-writes nor loses one
        for a decorator somebody removed on purpose.
        """
        assert not _compare(
            f"{EMITTED_COMPONENT}class BookshelfError(Exception):\n    pass\n",
            "class BookshelfError(Exception):\n    pass\n",
        )

    def test_a_decorator_merely_shaped_like_the_emitters_is_compared(self) -> None:
        """The ignore test is the bare name ``component``, not "looks generated"."""
        finding = _one(
            "@component_of(catalogue)\nclass Book:\n    pass\n",
            "class Book:\n    pass\n",
        )
        assert finding.kind == "decorators_changed"
        assert finding.before == "component_of(catalogue)"


# ---------------------------------------------------------------------------
# The verdict, and how it reads
# ---------------------------------------------------------------------------


class TestTheVerdict:
    """Order, cleanliness and the two renderings."""

    BEFORE = (
        "__all__ = ['Book', 'shelve']\n\n\n"
        "class Book:\n"
        '    """One title."""\n\n'
        "    title: str\n\n"
        "    def label(self) -> str:\n"
        "        return self.title\n\n\n"
        "def shelve(book: Book) -> None:\n"
        "    pass\n"
    )
    AFTER = (
        "__all__ = ['Book']\n\n\n"
        "class Book:\n"
        '    """A title."""\n\n'
        "    title: int\n\n"
        "    def label(self, upper: bool = False) -> str:\n"
        "        return self.title\n"
    )

    def test_identical_surfaces_are_clean(self) -> None:
        result = compare_surfaces(
            surface_from_source(self.BEFORE, MODULE),
            surface_from_source(self.BEFORE, MODULE),
            built_path="bookshelf_build/errors.py",
        )
        assert result.clean
        assert result.findings == ()
        assert result.module == MODULE
        assert result.built_path == "bookshelf_build/errors.py"

    def test_findings_are_sorted_by_symbol_then_kind(self) -> None:
        findings = _compare(self.BEFORE, self.AFTER)
        keys = [(finding.symbol, finding.kind) for finding in findings]
        assert keys == sorted(keys)
        assert keys == [
            ("Book", "doc_changed"),
            ("Book.label", "signature_changed"),
            ("Book.title", "annotation_changed"),
            ("shelve", "missing"),
        ]

    def test_comparing_twice_gives_the_same_answer(self) -> None:
        assert _compare(self.BEFORE, self.AFTER) == _compare(self.BEFORE, self.AFTER)

    def test_the_text_puts_each_finding_on_one_line(self) -> None:
        result = compare_surfaces(
            surface_from_source(self.BEFORE, MODULE),
            surface_from_source(self.AFTER, MODULE),
            built_path="bookshelf_build/errors.py",
        )
        text = render_parity_text([result])

        assert text.endswith("\n")
        assert "\r" not in text
        assert text.splitlines()[0] == (
            "bookshelf.errors — 4 differences (compared with bookshelf_build/errors.py)"
        )
        findings = [line for line in text.splitlines() if line.startswith("  Book")]
        assert len(findings) == 3
        assert "declared type changed" in "\n".join(findings)
        assert "str → int" in "\n".join(findings)

    def test_a_clean_run_says_to_run_the_projects_own_tests(self) -> None:
        result = compare_surfaces(
            surface_from_source(self.BEFORE, MODULE),
            surface_from_source(self.BEFORE, MODULE),
            built_path="bookshelf_build/errors.py",
        )
        text = render_parity_text([result])

        assert "same surface" in text
        assert "run the project's own tests" in " ".join(text.lower().split())

    def test_a_multiline_docstring_is_folded_onto_its_line(self) -> None:
        """A finding is one line by contract, and a docstring is not."""
        result = compare_surfaces(
            surface_from_source(
                'def shelve() -> None:\n    """Put it back.\n\n    Where it was.\n    """\n',
                MODULE,
            ),
            surface_from_source('def shelve() -> None:\n    """Elsewhere."""\n', MODULE),
            built_path="bookshelf_build/errors.py",
        )
        lines = render_parity_text([result]).splitlines()

        assert sum(1 for line in lines if line.startswith("  shelve")) == 1
        assert "Put it back. Where it was. → Elsewhere." in "\n".join(lines)

    def test_modules_that_were_not_compared_are_named_rather_than_left_out(
        self,
    ) -> None:
        result = compare_surfaces(
            surface_from_source(self.BEFORE, MODULE),
            surface_from_source(self.BEFORE, MODULE),
            built_path="bookshelf_build/errors.py",
        )
        text = render_parity_text([result], waiting=["bookshelf.catalog"])

        assert "bookshelf.catalog" in text
        assert "nothing built to compare it with yet" in " ".join(text.split())


class TestTheJsonDocument:
    """What an agent reads, and what it can match on."""

    def test_it_carries_the_schema_and_the_findings(self) -> None:
        result = compare_surfaces(
            surface_from_source("LOAN_DAYS = 21\n", MODULE),
            surface_from_source("LOAN_DAYS = 14\n", MODULE),
            built_path="bookshelf_build/errors.py",
        )
        document = parity_document([result])

        assert document["schema"] == PARITY_SCHEMA == "s0ma-adopt-parity@1"
        assert document["clean"] is False
        assert document["modules"][0]["findings"][0]["kind"] == "value_changed"
        assert document["not_compared"] == []

    def test_it_is_byte_identical_twice_over(self) -> None:
        result = compare_surfaces(
            surface_from_source("LOAN_DAYS = 21\n", MODULE),
            surface_from_source("LOAN_DAYS = 14\n", MODULE),
            built_path="bookshelf_build/errors.py",
        )
        first = dump_json(parity_document([result]))
        second = dump_json(parity_document([result]))

        assert first == second
        assert first.endswith("\n")
        assert "\\u" not in first

    def test_what_was_not_compared_is_in_the_document_too(self) -> None:
        document = parity_document([], waiting=["bookshelf.catalog"])

        assert document["not_compared"] == [
            {
                "module": "bookshelf.catalog",
                "reason": "nothing of that name has been built yet",
            }
        ]
