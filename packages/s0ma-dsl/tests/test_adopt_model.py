"""The frozen data model of the ``s0ma adopt`` retrofit family (A1).

``s0ma_dsl/adopt/model.py`` is the vocabulary every retrofit mechanism
meets in — scan, init, draft, baseline, verify-parity, status — written
by different hands at different times. These tests lock the properties
those mechanisms are allowed to rely on:

- **Determinism.** The same record dumps to byte-identical JSON twice,
  and key order never depends on construction order. Scan reports and
  the committed ``adopt-baseline.s0ma.json`` have to diff empty when
  nothing changed, on macOS, Linux and Windows alike.
- **Ordering is data.** ``to_dict`` never sorts a sequence. Source
  order in a draft, leaf-first order in the graph and declared order in
  ``__all__`` all carry meaning; a tidy-up would destroy it.
- **Immutability.** A record that has been measured cannot be edited
  afterwards, and ``slots=True`` is really in force.
- **Nothing silently dropped.** Every declared field appears in
  ``to_dict`` output, so adding a field to a record cannot leave it
  missing from the JSON that a later milestone's golden file compares.
- **Plain JSON out.** No tuples, no dataclasses, no sets survive into
  the dumped structure.

The sample records below are deliberately *unsorted* where a field's
order is meaningful, and carry non-ASCII text, so a regression in
either area fails rather than passes quietly.
"""

from __future__ import annotations

import json
from dataclasses import MISSING, FrozenInstanceError, fields, is_dataclass
from typing import Any

import pytest

from s0ma_dsl import adopt
from s0ma_dsl.adopt import model
from s0ma_dsl.adopt.model import (
    BASELINE_FILENAME,
    BASELINE_SCHEMA,
    DRAFT_INTENT_MARKER,
    DRAFT_UNPLACED_MARKER,
    SCAN_SCHEMA,
    DraftDeclaration,
    DraftModule,
    DraftUnplaced,
    EffortEstimate,
    EntityFact,
    GraphFacts,
    ImportFact,
    LadderStatus,
    ModuleCensus,
    ModuleSurface,
    ParityFinding,
    ParityResult,
    PerimeterSuggestion,
    Proposal,
    ScanReport,
    ScanWarning,
    SourceFile,
    SurfaceEntry,
    dump_json,
)

# ---------------------------------------------------------------------------
# Sample records — one per dataclass, every field supplied
# ---------------------------------------------------------------------------

SOURCE = SourceFile(
    path="src/bookshelf/lending.py",
    module="bookshelf.lending",
    source_root="src",
    role="app",
)

ENTITY = EntityFact(
    name="borrow",
    category="function",
    line=42,
    public=True,
    kind_hint="SERVICE",
    # Deliberately not alphabetical: source order is the contract.
    decorators=("staticmethod", "functools.lru_cache"),
    bases=(),
    has_docstring=True,
    registered=False,
)

IMPORT = ImportFact(
    module="bookshelf.catalog",
    names=("find_book", "Catalog"),
    line=7,
    deferred=True,
    type_checking=False,
    origin="first_party",
)

CENSUS = ModuleCensus(
    source=SOURCE,
    lines=180,
    sloc=131,
    entities=(ENTITY,),
    imports=(IMPORT,),
    dunder_all=("borrow", "Loan"),
    has_main_guard=False,
    top_level_effects=1,
    parse_error=None,
    content_hash="sha256:" + "0" * 64,
)

GRAPH = GraphFacts(
    edges=(("bookshelf.lending", "bookshelf.models"),),
    deferred_edges=(("bookshelf.lending", "bookshelf.catalog"),),
    cycles=(("bookshelf.catalog", "bookshelf.lending"),),
    # Leaf-first, so emphatically not alphabetical.
    order=("bookshelf.errors", "bookshelf.models", "bookshelf.catalog"),
    fan_in=(("bookshelf.models", 4),),
    fan_out=(("bookshelf.lending", 3),),
)

PROPOSAL = Proposal(
    module="bookshelf.lending",
    layer="domain",
    confidence="high",
    # Non-ASCII on purpose: ensure_ascii=False has to keep it readable.
    reasons=("imports no infrastructure", "names read as business rules — prêt, not I/O"),
    kind_mix=(("SERVICE", 3), ("MODEL", 1)),
)

PERIMETER = PerimeterSuggestion(
    source_roots=("src",),
    bootstrap_files=("src/bookshelf/__main__.py",),
    package_markers=("src/bookshelf/__init__.py",),
    mode="migration",
    notes=("The tests directory is left out of the perimeter.",),
)

EFFORT = EffortEstimate(
    # Band order is small/medium/large, never alphabetical.
    bands=(("small", 6), ("medium", 3), ("large", 1)),
    per_module=(("bookshelf.errors", "small"), ("bookshelf.lending", "large")),
    basis="Bands count declarations and top-level statements, not hours.",
)

WARNING = ScanWarning(
    code="ADOPT_SCAN_CYCLE",
    module="bookshelf.lending",
    message="This module and bookshelf.catalog import each other; convert them together.",
)

REPORT = ScanReport(
    schema=SCAN_SCHEMA,
    project={"has_s0ma_config": False, "mode": None, "name": None},
    summary={"modules": 11, "unplaced": 1},
    modules=(CENSUS,),
    graph=GRAPH,
    proposals=(PROPOSAL,),
    perimeter=PERIMETER,
    effort=EFFORT,
    classification=None,
    warnings=(WARNING,),
)

DECLARATION = DraftDeclaration(
    name="borrow",
    form="nerve",
    kind=None,
    intent=None,
    layer=None,
    fields=(("expects", "a known borrower"), ("guarantees", "the loan is recorded")),
    body="def borrow(book_id: str) -> Loan:\n    ...\n",
    start_line=40,
    end_line=48,
)

UNPLACED = DraftUnplaced(
    text="LOGGER = logging.getLogger(__name__)\n",
    start_line=12,
    end_line=12,
    reason="module-level statement with a side effect",
)

DRAFT = DraftModule(
    module="bookshelf.lending",
    source_path="src/bookshelf/lending.py",
    source_hash="sha256:" + "1" * 64,
    layer=None,
    intent=None,
    docstring="Lending rules for the bookshelf service.",
    requires=("datetime",),
    deferred_requires=("bookshelf.catalog",),
    uses=("bookshelf.models",),
    # __all__ order, which is the author's order and not sorted.
    exports=("borrow", "Loan"),
    declarations=(DECLARATION,),
    unplaced=(UNPLACED,),
    notes=("bookshelf.catalog is not converted yet, so it rides requires for now.",),
)

SURFACE_ENTRY = SurfaceEntry(
    name="Loan.due_on",
    category="attribute",
    signature=None,
    annotation="date",
    decorators=(),
    bases=(),
    docstring=None,
    value="<non-literal>",
)

SURFACE = ModuleSurface(
    module="bookshelf.lending",
    entries=(
        SurfaceEntry(
            name="Loan",
            category="class",
            signature=None,
            annotation=None,
            decorators=("dataclass(frozen=True)",),
            bases=("Record",),
            docstring="One book, out on loan.",
            value=None,
        ),
        SURFACE_ENTRY,
    ),
    dunder_all=("borrow", "Loan"),
)

FINDING = ParityFinding(
    kind="signature_changed",
    symbol="borrow",
    before="(book_id: str) -> Loan",
    after="(book_id: str, *, days: int = 14) -> Loan",
    detail="borrow gained a parameter; callers written against the old shape still work, "
    "but the promise changed — confirm that was intended.",
)

RESULT = ParityResult(
    module="bookshelf.lending",
    built_path="src/bookshelf/_built/lending.py",
    findings=(FINDING,),
)

STATUS = LadderStatus(
    rung=3,
    rung_label="converting, module by module",
    mode="migration",
    counts=(("adopted_files", 2), ("converted_modules", 4), ("unknown_files", 7)),
    score=61.5,
    score_floor=50.0,
    next_module="bookshelf.catalog",
    next_command="s0ma adopt baseline bookshelf.catalog",
)

#: Every dataclass in the model, with a fully-populated instance.
SAMPLES: dict[str, Any] = {
    "SourceFile": SOURCE,
    "EntityFact": ENTITY,
    "ImportFact": IMPORT,
    "ModuleCensus": CENSUS,
    "GraphFacts": GRAPH,
    "Proposal": PROPOSAL,
    "PerimeterSuggestion": PERIMETER,
    "EffortEstimate": EFFORT,
    "ScanWarning": WARNING,
    "ScanReport": REPORT,
    "DraftDeclaration": DECLARATION,
    "DraftUnplaced": UNPLACED,
    "DraftModule": DRAFT,
    "SurfaceEntry": SURFACE_ENTRY,
    "ModuleSurface": SURFACE,
    "ParityFinding": FINDING,
    "ParityResult": RESULT,
    "LadderStatus": STATUS,
}

SAMPLE_NAMES = sorted(SAMPLES)

JSON_SCALARS = (str, int, float, bool, type(None))


def _assert_json_pure(value: object, where: str) -> None:
    """Fail unless *value* is built only from types ``json`` writes natively."""
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str), f"{where}: dict key {key!r} is not a string"
            _assert_json_pure(item, f"{where}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_pure(item, f"{where}[{index}]")
        return
    assert isinstance(value, JSON_SCALARS), f"{where}: {type(value).__name__} is not a JSON type"


# ---------------------------------------------------------------------------
# The model is complete and self-consistent
# ---------------------------------------------------------------------------


def test_every_exported_dataclass_has_a_sample() -> None:
    """A new record type must arrive with a sample, or these tests miss it."""
    exported = {name for name in model.__all__ if is_dataclass(getattr(model, name))}
    assert exported == set(SAMPLES)


#: What ``adopt/__init__.py`` re-exports *beyond* the model: rung 0
#: whole, added at the B4 gate when ``s0ma adopt scan`` shipped. Written
#: out rather than computed, so a name that appears on the package
#: without anybody deciding to put it there still fails here.
PACKAGE_MECHANISMS = frozenset(
    {
        "EFFORT_BASIS",
        "ORIGIN_FIRST_PARTY",
        "ORIGIN_STDLIB",
        "ORIGIN_THIRD_PARTY",
        "ORIGIN_UNRESOLVED",
        "PERIMETER_MODE",
        "WARNING_CYCLE",
        "WARNING_DEFERRED_CYCLE",
        "WARNING_DYNAMIC_EXPORTS",
        "WARNING_NAME_COLLISION",
        "WARNING_PARSE_ERROR",
        "build_graph",
        "build_scan_report",
        "census_file",
        "classify_imports",
        "collision_warnings",
        "discover_sources",
        "estimate_effort",
        "framework_component_names",
        "is_transpiled_artifact",
        "propose",
        "render_detail_text",
        "render_scan_text",
        "resolve_source_roots",
        "suggest_perimeter",
    }
)


def test_package_reexports_the_model_surface_and_rung_zero() -> None:
    """``adopt/__init__.py`` re-exports the model, plus rung 0, and nothing else.

    Every model name is on the package and is the *same object*, so a
    caller importing from either place is holding one vocabulary. The
    only other names are the mechanisms rung 0 is made of, enumerated
    above: the package is a front door, not a dumping ground.
    """
    assert set(adopt.__all__) == set(model.__all__) | PACKAGE_MECHANISMS
    assert len(adopt.__all__) == len(set(adopt.__all__))
    assert list(adopt.__all__) == sorted(adopt.__all__, key=_export_order)
    for name in model.__all__:
        assert getattr(adopt, name) is getattr(model, name), name
    for name in PACKAGE_MECHANISMS:
        assert callable(getattr(adopt, name)) or isinstance(
            getattr(adopt, name), str
        ), name


def _export_order(name: str) -> tuple[int, str]:
    """The house's ``__all__`` order: constants first, then the rest."""
    return (0 if name[:1].isupper() and name.isupper() else 1, name)


@pytest.mark.parametrize("name", SAMPLE_NAMES)
def test_every_declared_field_reaches_the_dump(name: str) -> None:
    """No field is silently dropped from ``to_dict``."""
    sample = SAMPLES[name]
    dumped = sample.to_dict()
    declared = {entry.name for entry in fields(sample)}
    assert declared <= set(dumped), f"{name}: missing from to_dict: {declared - set(dumped)}"


@pytest.mark.parametrize("name", SAMPLE_NAMES)
def test_to_dict_returns_plain_json_types(name: str) -> None:
    """Tuples become lists, nested records become dicts, nothing exotic survives."""
    _assert_json_pure(SAMPLES[name].to_dict(), name)


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SAMPLE_NAMES)
def test_records_reject_mutation(name: str) -> None:
    """A measured record cannot be edited after the fact."""
    sample = SAMPLES[name]
    for entry in fields(sample):
        with pytest.raises(FrozenInstanceError):
            setattr(sample, entry.name, None)


@pytest.mark.parametrize("name", SAMPLE_NAMES)
def test_records_use_slots(name: str) -> None:
    """``slots=True`` is really in force: no instance dict to grow."""
    sample = SAMPLES[name]
    assert not hasattr(sample, "__dict__")
    assert type(sample).__slots__ == tuple(entry.name for entry in fields(sample))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SAMPLE_NAMES)
def test_two_dumps_are_byte_identical(name: str) -> None:
    """The same record dumps the same bytes twice — reports diff empty."""
    sample = SAMPLES[name]
    first = dump_json(sample.to_dict())
    second = dump_json(sample.to_dict())
    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")


@pytest.mark.parametrize("name", SAMPLE_NAMES)
def test_dump_round_trips_through_json(name: str) -> None:
    """What ``dump_json`` writes, ``json.loads`` reads back unchanged."""
    sample = SAMPLES[name]
    dumped = sample.to_dict()
    assert json.loads(dump_json(dumped)) == dumped


def test_key_order_never_depends_on_construction_order() -> None:
    """``sort_keys=True`` means two differently-built dicts dump identically."""
    assert dump_json({"b": 1, "a": 2}) == dump_json({"a": 2, "b": 1})


def test_dump_json_ends_with_exactly_one_newline() -> None:
    """One trailing newline: the POSIX convention, not two and not none."""
    for name in SAMPLE_NAMES:
        text = dump_json(SAMPLES[name].to_dict())
        assert text.endswith("\n")
        assert not text.endswith("\n\n")
        assert text.count("\n") == len(text.splitlines())


def test_dump_json_keeps_non_ascii_readable() -> None:
    """``ensure_ascii=False``: an accent stays an accent, not a ``\\u`` escape."""
    text = dump_json(PROPOSAL.to_dict())
    assert "prêt" in text
    assert "\\u" not in text


def test_dump_json_indents_two_spaces() -> None:
    """Reviewable in a pull request, and stable across runs."""
    text = dump_json({"outer": {"inner": 1}})
    assert text == '{\n  "outer": {\n    "inner": 1\n  }\n}\n'


# ---------------------------------------------------------------------------
# Ordering is data, not decoration
# ---------------------------------------------------------------------------


def test_sequence_order_survives_to_dict() -> None:
    """``to_dict`` never tidies a sequence: source order carries meaning."""
    assert GRAPH.to_dict()["order"] == [
        "bookshelf.errors",
        "bookshelf.models",
        "bookshelf.catalog",
    ]
    assert EFFORT.to_dict()["bands"] == [["small", 6], ["medium", 3], ["large", 1]]
    assert ENTITY.to_dict()["decorators"] == ["staticmethod", "functools.lru_cache"]
    assert DRAFT.to_dict()["exports"] == ["borrow", "Loan"]
    assert SURFACE.to_dict()["dunder_all"] == ["borrow", "Loan"]


def test_sequence_order_survives_the_json_text() -> None:
    """Sorted *keys* must not become sorted *values* in the dumped text."""
    text = dump_json(EFFORT.to_dict())
    assert text.index('"small"') < text.index('"medium"') < text.index('"large"')


def test_pairs_dump_as_two_item_lists() -> None:
    """A ``(name, count)`` pair is a two-item list, not a dict or a string."""
    assert GRAPH.to_dict()["fan_in"] == [["bookshelf.models", 4]]
    assert GRAPH.to_dict()["edges"] == [["bookshelf.lending", "bookshelf.models"]]
    assert PROPOSAL.to_dict()["kind_mix"] == [["SERVICE", 3], ["MODEL", 1]]


def test_absent_is_not_the_same_as_empty() -> None:
    """``None`` means "not declared"; ``[]`` would mean "declared empty"."""
    absent = ModuleSurface(module="m", entries=(), dunder_all=None)
    empty = ModuleSurface(module="m", entries=(), dunder_all=())
    assert absent.to_dict()["dunder_all"] is None
    assert empty.to_dict()["dunder_all"] == []


# ---------------------------------------------------------------------------
# Nesting
# ---------------------------------------------------------------------------


def test_nested_records_dump_as_dicts() -> None:
    """A report carries its censuses whole, not as repr strings."""
    dumped = REPORT.to_dict()
    assert dumped["modules"][0]["source"]["path"] == "src/bookshelf/lending.py"
    assert dumped["graph"]["cycles"] == [["bookshelf.catalog", "bookshelf.lending"]]
    assert dumped["perimeter"]["mode"] == "migration"
    assert dumped["classification"] is None


def test_draft_carries_both_declarations_and_unplaced_source() -> None:
    """Nothing in a converted module goes missing quietly."""
    dumped = DRAFT.to_dict()
    assert dumped["declarations"][0]["name"] == "borrow"
    assert dumped["declarations"][0]["intent"] is None
    assert dumped["unplaced"][0]["reason"] == "module-level statement with a side effect"
    assert dumped["unplaced"][0]["start_line"] == 12


def test_report_mappings_are_copied_not_aliased() -> None:
    """A caller editing the dumped dict cannot reach back into the record."""
    dumped = REPORT.to_dict()
    dumped["summary"]["modules"] = 999
    assert REPORT.summary["modules"] == 11


# ---------------------------------------------------------------------------
# Derived verdict
# ---------------------------------------------------------------------------


def test_parity_result_clean_is_derived_from_the_findings() -> None:
    """A result with findings cannot be labelled clean by accident."""
    assert RESULT.clean is False
    assert RESULT.to_dict()["clean"] is False
    quiet = ParityResult(module="m", built_path="src/_built/m.py", findings=())
    assert quiet.clean is True
    assert quiet.to_dict()["clean"] is True


# ---------------------------------------------------------------------------
# Declared types on the surface (E1b)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SAMPLE_NAMES)
def test_no_field_anywhere_in_the_model_has_a_default(name: str) -> None:
    """The house rule, enforced rather than remembered.

    An omitted field would be a silent zero in a report someone decides
    from — an empty ``findings``, a ``None`` intent, a surface with no
    declared types — so every field has to be supplied at every
    construction site, which is what makes adding one a visible change.
    """
    for entry in fields(SAMPLES[name]):
        assert entry.default is MISSING, f"{name}.{entry.name} has a default"
        assert entry.default_factory is MISSING, f"{name}.{entry.name} has a default"


def test_surface_entry_records_a_declared_type_next_to_the_signature() -> None:
    """``annotation`` sits directly after ``signature``: both say "what shape?"."""
    order = [entry.name for entry in fields(SurfaceEntry)]
    assert order.index("annotation") == order.index("signature") + 1


def test_a_declared_type_reaches_the_dump_and_the_json() -> None:
    """A dataclass field's type has to survive to the committed baseline."""
    assert SURFACE_ENTRY.annotation == "date"
    assert SURFACE_ENTRY.to_dict()["annotation"] == "date"
    assert '"annotation": "date"' in dump_json(SURFACE_ENTRY.to_dict())


def test_a_name_with_no_declared_type_dumps_null_rather_than_omitting_the_key() -> None:
    """Absent and "declared as nothing" must not look the same to a comparer."""
    entry = SURFACE.entries[0]
    assert entry.category == "class"
    assert entry.annotation is None
    assert entry.to_dict()["annotation"] is None
    assert "annotation" in entry.to_dict()


def test_the_parity_kinds_are_documented_where_the_comparer_will_look() -> None:
    """``kind`` is a plain string, so the docstring is the only list there is."""
    documented = ParityFinding.__doc__ or ""
    for kind in (
        "missing",
        "extra",
        "signature_changed",
        "annotation_changed",
        "doc_changed",
        "bases_changed",
        "decorators_changed",
        "value_changed",
    ):
        assert f'"{kind}"' in documented, kind


# ---------------------------------------------------------------------------
# Constants are contract
# ---------------------------------------------------------------------------


def test_schema_and_marker_constants() -> None:
    """These strings are matched by other tools; changing one is a break."""
    assert SCAN_SCHEMA == "s0ma-adopt-scan@1"
    assert BASELINE_SCHEMA == "s0ma-adopt-baseline@1"
    assert BASELINE_FILENAME == "adopt-baseline.s0ma.json"
    assert DRAFT_INTENT_MARKER == "FIXME(adopt):"
    assert DRAFT_UNPLACED_MARKER == "adopt: unplaced"


def test_baseline_filename_joins_the_established_family() -> None:
    """``<name>.s0ma.json``, at the project root, committed and diffable."""
    assert BASELINE_FILENAME.endswith(".s0ma.json")
    assert "/" not in BASELINE_FILENAME
    assert "\\" not in BASELINE_FILENAME


def test_no_record_carries_an_absolute_or_backslashed_path() -> None:
    """Committed artifacts must read the same on Windows as on POSIX."""
    for name in SAMPLE_NAMES:
        text = dump_json(SAMPLES[name].to_dict())
        assert "\\\\" not in text, name
        assert '"/' not in text, name
