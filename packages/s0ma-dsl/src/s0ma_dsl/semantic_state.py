"""Typed semantic-state values and the normative declaration-field matrix.

M3A keeps the legacy primitive projection on AST declarations for one
compatibility window, while every semantic field also carries one of these
tagged values in ``declaration.semantic_states``.  Canonical IR is emitted
from the tagged value; emitters and validators can continue reading the
primitive projection until M3B removes that compatibility reader.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from s0ma.decorators import component
from s0ma.types import ComponentKind
from s0ma.types import Layer as S0maLayer

SemanticStateKind = Literal["value", "none", "pending"]
FieldClass = Literal[
    "semantic-required-state",
    "semantic-conditional-state",
    "presentation-optional",
    "derived",
]


@component(
    name="S0maDSL_SemanticState",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Represents an authored declaration field as an explicit value, deliberate "
        "non-applicability, or acknowledged debt with a non-empty reason."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class SemanticState:
    """Canonical tagged state for one semantic declaration field."""

    state: SemanticStateKind
    value: Any = None
    reason: str | None = None

    @classmethod
    def valued(cls, value: Any) -> SemanticState:
        return cls(state="value", value=value)

    @classmethod
    def none(cls) -> SemanticState:
        return cls(state="none")

    @classmethod
    def pending(cls, reason: str) -> SemanticState:
        clean = reason.strip()
        if not clean:
            raise ValueError("pending semantic state requires a non-empty reason")
        return cls(state="pending", reason=clean)

    def to_dict(self) -> dict[str, Any]:
        if self.state == "value":
            return {"state": "value", "value": self.value}
        if self.state == "none":
            return {"state": "none"}
        assert self.reason is not None
        return {"state": "pending", "reason": self.reason}


@dataclass(frozen=True)
class FieldClassification:
    """One frozen row of the 0.14 declaration-field matrix."""

    field_class: FieldClass
    allow_value: bool = True
    allow_none: bool = False
    allow_pending: bool = False
    applicability: str = "always"


def _sr(*, none: bool = False, pending: bool = False) -> FieldClassification:
    return FieldClassification(
        "semantic-required-state", allow_none=none, allow_pending=pending
    )


def _sc(
    *, none: bool = False, pending: bool = False, applicability: str
) -> FieldClassification:
    return FieldClassification(
        "semantic-conditional-state",
        allow_none=none,
        allow_pending=pending,
        applicability=applicability,
    )


_PO = FieldClassification("presentation-optional")
_D = FieldClassification("derived")


# Machine-readable twin of docs/contracts/0.14.0-schema-and-surface-budget.md
# section 3. M3B enforcement and M3A migration both consume this table so the
# prose contract and executable compatibility path cannot independently drift.
FIELD_CLASSIFICATIONS: dict[str, dict[str, FieldClassification]] = {
    "module": {
        "name": _sr(), "layer": _sr(), "version": _sr(),
        "intent": _sr(pending=True),
        "exports": _sr(none=True, pending=True),
        "requires": _sr(none=True, pending=True),
        "uses": _sr(none=True, pending=True),
        "soft_requires": _sr(none=True, pending=True),
        "runtime_only_requires": _sr(none=True, pending=True),
        "deferred_requires": _sr(none=True, pending=True),
        "exports_helpers": _sr(none=True, pending=True),
        "tags": _PO,
        "location": _D,
    },
    "nerve": {
        "name": _sr(), "layer": _sr(), "kind": _sr(),
        "visibility": _sr(), "evaluates_at": _sr(),
        "intent": _sr(pending=True),
        "expects": _sr(none=True, pending=True),
        "guarantees": _sr(pending=True),
        "forbids": _sr(none=True, pending=True),
        "provides": _sr(none=True, pending=True),
        "returns": _sr(none=True, pending=True),
        "raises": _sr(none=True, pending=True),
        "interface": _sr(none=True, pending=True),
        "latency_ms": _sr(none=True, pending=True),
        "depends_on": _sr(none=True, pending=True),
        "internal_helpers": _sr(none=True, pending=True),
        "expected_exceptions": _sr(none=True, pending=True),
        "consumes_via_dict": _sr(none=True, pending=True),
        "declares_attributes": _sr(none=True, pending=True),
        "covered_by": _sr(none=True, pending=True),
        "abstract": _sc(applicability="author only when abstract"),
        "deferred": _sc(applicability="author only for a deferred stub"),
        "is_page_composer": _sc(applicability="author only when true"),
        "body": _sc(pending=True, applicability="required unless abstract/interface"),
        "version": _PO, "tags": _PO, "metadata": _PO, "serves_as": _PO,
        "provides_entries": _D, "raw_body": _D, "location": _D,
    },
    "cell": {
        "name": _sr(), "layer": _sr(), "kind": _sr(), "visibility": _sr(),
        "intent": _sr(pending=True), "schema": _sr(pending=True),
        "invariants": _sr(none=True, pending=True),
        "covered_by": _sr(none=True, pending=True),
        "body": _sc(pending=True, applicability="representation required by cell kind"),
        "category": _sc(pending=True, applicability="capability/behaviour kinds"),
        "deferred": _sc(applicability="author only for a deferred stub"),
        "dataclass_invariants": _sc(
            none=True, pending=True, applicability="MODEL cells"
        ),
        "placeholders": _sc(
            none=True, pending=True, applicability="embedded CONSTANT templates"
        ),
        "version": _PO, "tags": _PO, "metadata": _PO,
        "raw_body": _D, "embedded_file_path": _D,
        "embedded_file_resolved": _D, "embedded_content": _D,
        "embedded_file_hash": _D, "location": _D,
    },
    "ganglion": {
        "name": _sr(), "layer": _sr(), "visibility": _sr(), "scope": _sr(),
        "intent": _sr(pending=True), "observes": _sr(pending=True),
        "on_anomaly": _sr(pending=True),
        "forbids": _sr(none=True, pending=True),
        "priors": _sr(none=True, pending=True),
        "depends_on": _sr(none=True, pending=True),
        "covered_by": _sr(none=True, pending=True),
        "body": _sc(pending=True, applicability="executable evaluator shapes"),
        "deferred": _sc(applicability="author only for a deferred stub"),
        "tags": _PO, "metadata": _PO, "raw_body": _D, "location": _D,
    },
    "test": {
        "name": _sr(), "layer": _sr(), "intent": _sr(pending=True),
        "tests": _sr(pending=True), "expects": _sr(none=True, pending=True),
        "depends_on": _sr(none=True, pending=True),
        "mocks": _sr(none=True, pending=True), "body": _sr(pending=True),
        "tags": _PO, "raw_body": _D, "location": _D,
    },
    "helper": {
        "name": _sr(), "layer": _sr(), "intent": _sr(pending=True),
        "body": _sr(pending=True), "tags": _PO,
        "body_kind": _D, "inline": _D, "raw_body": _D, "location": _D,
    },
    "integration": {
        "name": _sr(), "layer": _sr(), "version": _sr(),
        "intent": _sr(pending=True), "factory": _sr(pending=True),
        "smoke_test_primary": _sr(pending=True), "manifest": _sr(pending=True),
        "requires": _sr(none=True, pending=True),
        "uses": _sr(none=True, pending=True),
        "raises": _sr(none=True, pending=True),
        "body": _sc(none=True, pending=True, applicability="embedded helper code"),
        "tags": _PO, "raw_body": _D, "location": _D,
    },
    "axon": {
        "source": _sr(), "target": _sr(), "relation": _sr(),
        "carries": _sr(), "coupling": _sr(), "intent": _sr(pending=True),
        "location": _D,
    },
    "doc_ref": {
        "name": _sr(), "module_location": _sr(), "format": _sr(), "output": _sr(),
        "intent": _sr(pending=True), "covers": _sr(pending=True),
        # ADR-013 §6 (spec 0.17.0 §4.14.5): SC, not SR. ``sections:`` is
        # required for the filter form and inapplicable to the
        # source-registry form, whose records come from the derived-source
        # registry. The filter-form requirement is unchanged and enforced
        # where the covers shape is known (``_build_doc_ref``); leaving the
        # field SR here would fire SEMANTIC_REQUIRED_STATE_OMITTED before
        # that shape has been parsed, which is what made the field dead
        # rather than optional. The 0.14.0 surface-budget contract records
        # the pre-ADR-013 classification and is not retrofitted.
        "sections": _sc(
            pending=True,
            applicability="required for the covers: filter form",
        ),
        "tags": _PO,
        "covers_source": _D, "location": _D,
    },
    "doc_guide": {
        "name": _sr(), "module_location": _sr(), "format": _sr(), "output": _sr(),
        "intent": _sr(pending=True), "covers": _sr(pending=True),
        "asserts": _sr(pending=True), "examples": _sr(pending=True),
        "prose_body": _sr(pending=True), "tags": _PO,
        "prose_tokens": _D, "location": _D,
    },
    "example": {
        "name": _sr(), "module_location": _sr(), "runs_in": _sr(),
        "intent": _sr(pending=True), "demonstrates": _sr(pending=True),
        "python_body": _sr(pending=True), "tags": _PO,
        "raw_python_body": _D, "location": _D,
    },
}

# The field matrix names the AST/IR field. A small number of established DSL
# spellings differ; migration and parsing share this map so they cannot drift.
FIELD_SOURCE_NAMES: dict[tuple[str, str], str] = {
    ("nerve", "internal_helpers"): "internal",
}


def semantic_source_field(declaration_type: str, field: str) -> str:
    """Return the authored DSL spelling for one normative semantic field."""

    return FIELD_SOURCE_NAMES.get((declaration_type, field), field)


# Where each row of the matrix is written. Most rows are a line of the
# description; the rest are read off the declaration's first line, or are the
# code after the ``---`` separator. Parsing, the line check and the generated
# quick reference all read these, so what the check accepts and what the
# reference lists cannot drift apart.
HEADER_LINE_FIELDS: dict[str, frozenset[str]] = {
    "module": frozenset({"name"}),
    "nerve": frozenset({"name", "layer"}),
    "cell": frozenset({"name", "layer"}),
    "ganglion": frozenset({"name", "layer"}),
    "test": frozenset({"name", "layer"}),
    "helper": frozenset({"name", "layer"}),
    "integration": frozenset({"name", "layer"}),
    "axon": frozenset({"source", "target"}),
    # Documentation/example declarations inherit ``module_location`` from
    # the required containing module declaration; there is no separate DSL
    # field to author and therefore no omission to migrate.
    "doc_ref": frozenset({"name", "module_location"}),
    "doc_guide": frozenset({"name", "module_location"}),
    "example": frozenset({"name", "module_location"}),
}
CODE_FIELDS = frozenset({"body", "prose_body", "python_body"})

# Spellings a person writes that the matrix does not list under their own
# name, with the matrix row each one stands for: ``content:`` is how a
# CONSTANT cell authors its ``body`` from a file (spec §4.2.2), and
# ``helpers:`` is the module header's inline-helper block (spec §4.4a.6),
# which declares helpers rather than holding a value and so stands for no row.
AUTHORED_ONLY_LINES: dict[str, dict[str, str | None]] = {
    "cell": {"content": "body"},
    "module": {"helpers": None},
}

LinePlace = Literal["first-line", "line", "code"]


@dataclass(frozen=True)
class AuthoredLine:
    """One thing a person writes on a declaration, and the row behind it.

    ``name`` is the spelling typed in a ``.s0ma`` file and ``field`` the
    matrix row it stands for, which differ for a handful of established
    spellings. ``classification`` is ``None`` only for a spelling that
    stands for no row at all.
    """

    name: str
    field: str | None
    place: LinePlace
    classification: FieldClassification | None


def authored_lines(declaration_type: str) -> tuple[AuthoredLine, ...]:
    """Everything a person writes on *declaration_type*, in matrix order.

    Derived rows are left out: s0ma computes them, and writing one has its
    own report (``SEMANTIC_DERIVED_FIELD_AUTHORED``).
    """

    header = HEADER_LINE_FIELDS.get(declaration_type, frozenset())
    rows = FIELD_CLASSIFICATIONS[declaration_type]
    found: list[AuthoredLine] = []
    for field, row in rows.items():
        if row.field_class == "derived":
            continue
        place: LinePlace = "line"
        if field in header:
            place = "first-line"
        elif field in CODE_FIELDS:
            place = "code"
        found.append(
            AuthoredLine(
                name=semantic_source_field(declaration_type, field),
                field=field,
                place=place,
                classification=row,
            )
        )
    for name, stands_for in AUTHORED_ONLY_LINES.get(declaration_type, {}).items():
        found.append(
            AuthoredLine(
                name=name,
                field=stands_for,
                place="line",
                classification=rows[stands_for] if stands_for is not None else None,
            )
        )
    return tuple(found)


def authored_field_names(declaration_type: str) -> frozenset[str]:
    """Every field line a person may write on *declaration_type*.

    The lines of the description only: what is written on the first line
    and the code itself are not fields a person can name.
    """

    return frozenset(
        line.name for line in authored_lines(declaration_type) if line.place == "line"
    )


def derived_field_names(declaration_type: str) -> frozenset[str]:
    """The fields of *declaration_type* s0ma computes, in authored spelling."""

    return frozenset(
        semantic_source_field(declaration_type, name)
        for name, row in FIELD_CLASSIFICATIONS[declaration_type].items()
        if row.field_class == "derived"
    )


def semantic_fields(declaration_type: str) -> dict[str, FieldClassification]:
    """Return only semantic rows for *declaration_type*."""

    return {
        name: row
        for name, row in FIELD_CLASSIFICATIONS[declaration_type].items()
        if row.field_class.startswith("semantic-")
    }


def completeness_credit(
    declaration_type: str, field: str, state: SemanticState
) -> int:
    """Return the frozen binary completeness credit for one state.

    ``pending`` is always zero. ``none`` is one only for a matrix row
    that explicitly allows non-applicability. A real value is one.
    """

    classification = FIELD_CLASSIFICATIONS[declaration_type][field]
    if state.state == "pending":
        return 0
    if state.state == "none":
        return int(classification.allow_none)
    return 1
