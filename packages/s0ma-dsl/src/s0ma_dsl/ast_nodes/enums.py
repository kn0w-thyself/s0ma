"""Enum types for the s0ma DSL AST.

Defines Layer, Kind, Visibility, Relation, Coupling, and EvaluatesAt enums
used throughout the transpiler's AST nodes, validators, and emitters.
Includes the kind-to-declaration-type compatibility mapping per spec §3.1.
"""

from __future__ import annotations

from enum import Enum, unique

from s0ma.decorators import component
from s0ma.types import ComponentKind
from s0ma.types import Layer as S0maLayer

__all__ = [
    "Layer",
    "Kind",
    "Visibility",
    "Relation",
    "Coupling",
    "EvaluatesAt",
    "DeclarationType",
    "VALID_KINDS_FOR_DECLARATION",
]


@component(
    name="S0maDSL_Layer",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Architectural layer enum for the s0ma DSL, classifying modules and components by their "
        "role in the system."
    ),
    idempotent=True,
    is_framework=True,
)
@unique
class Layer(Enum):
    """Architectural layer a module or component belongs to.

    Every module declares exactly one layer; all components in that module
    must share it (v1 — no mixed-layer modules).
    """

    DOMAIN = "DOMAIN"
    APPLICATION = "APPLICATION"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    PRESENTATION = "PRESENTATION"
    FRAMEWORK = "FRAMEWORK"


@component(
    name="S0maDSL_DeclarationType",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent="Enum of the seven top-level declaration types recognised by the s0ma DSL parser.",
    idempotent=True,
    is_framework=True,
)
@unique
class DeclarationType(Enum):
    """The seven top-level declaration types in a .s0ma file."""

    MODULE = "module"
    NERVE = "nerve"
    CELL = "cell"
    GANGLION = "ganglion"
    TEST = "test"
    AXON = "axon"
    # M13 (feedback 5–6): module-private helper functions. Helpers live at
    # module scope, are not registered as components, but are introspectable
    # via ``s0ma inspect``. They have no ``kind`` and no ``visibility`` field —
    # access control is the M13 access-control rule (intra-module + test
    # cross-module access only).
    HELPER = "helper"
    # Documentation subsystem declaration types (M1).
    DOC_REF = "doc_ref"
    DOC_GUIDE = "doc_guide"
    EXAMPLE = "example"


@component(
    name="S0maDSL_Kind",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Component kind enum for the s0ma DSL, distinguishing nerve kinds from cell kinds per "
        "spec §3.1."
    ),
    idempotent=True,
    is_framework=True,
)
@unique
class Kind(Enum):
    """Component kind — determines the archetype of a nerve or cell.

    Kind-to-declaration-type compatibility is enforced by
    ``VALID_KINDS_FOR_DECLARATION``.
    """

    # Nerve kinds
    SERVICE = "SERVICE"
    FUNCTION = "FUNCTION"
    ADAPTER = "ADAPTER"
    ORCHESTRATOR = "ORCHESTRATOR"

    # Cell kinds
    MODEL = "MODEL"
    CONSTANT = "CONSTANT"
    CONFIG = "CONFIG"
    ENUM = "ENUM"
    EXCEPTION = "EXCEPTION"
    TYPE = "TYPE"

    # Shared — reserved for framework internals
    FRAMEWORK = "FRAMEWORK"


@component(
    name="S0maDSL_Visibility",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Visibility enum controlling whether a component is exported (PUBLIC), module-private "
        "(INTERNAL), or test-accessible (TEST)."
    ),
    idempotent=True,
    is_framework=True,
)
@unique
class Visibility(Enum):
    """Component visibility level.

    PUBLIC components may be exported and used cross-module.
    INTERNAL components are callable only within the same module but remain
    observable/testable via the registry namespace.
    TEST components are callable within the same module and reachable from
    *test modules in any project module* via ``uses:``, but are hidden from
    production code in other modules. They never appear in ``exports:``.
    See ADR-008 and spec §4.10.1.
    """

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    TEST = "TEST"


@component(
    name="S0maDSL_Relation",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Dependency relation enum distinguishing authored relations (CALLS, READS, etc.) from "
        "derived relations (RAISES, TYPE_USES)."
    ),
    idempotent=True,
    is_framework=True,
)
@unique
class Relation(Enum):
    """Dependency relation type between two components.

    Authored relations (CALLS, CONSTRUCTS, READS, CONFIGURES) are declared
    explicitly via ``depends_on`` or standalone ``axon`` declarations.

    Derived relations (RAISES, TYPE_USES) are inferred by the transpiler
    and must never be authored manually.
    """

    # Authored relations
    CALLS = "CALLS"
    CONSTRUCTS = "CONSTRUCTS"
    READS = "READS"
    CONFIGURES = "CONFIGURES"
    PRODUCES = "PRODUCES"
    CONSUMES = "CONSUMES"

    # Derived relations
    RAISES = "RAISES"
    TYPE_USES = "TYPE_USES"

    def is_authored(self) -> bool:
        """Return True if this relation type may be declared by the author."""
        return self in _AUTHORED_RELATIONS

    def is_derived(self) -> bool:
        """Return True if this relation type is inferred by the transpiler."""
        return self in _DERIVED_RELATIONS


_AUTHORED_RELATIONS = frozenset({
    Relation.CALLS,
    Relation.CONSTRUCTS,
    Relation.READS,
    Relation.CONFIGURES,
    Relation.PRODUCES,
    Relation.CONSUMES,
})

_DERIVED_RELATIONS = frozenset({
    Relation.RAISES,
    Relation.TYPE_USES,
})


@component(
    name="S0maDSL_Coupling",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent="Coupling strength enum indicating whether a dependency is tightly or loosely coupled.",
    idempotent=True,
    is_framework=True,
)
@unique
class Coupling(Enum):
    """Coupling strength of a dependency relationship.

    TIGHT — changes to the target are likely to require source changes.
    LOOSE — the target implementation can change independently.
    """

    TIGHT = "TIGHT"
    LOOSE = "LOOSE"


@component(
    name="S0maDSL_EvaluatesAt",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Evaluation scope enum for nerves and ganglia, indicating at what granularity signals "
        "are assessed."
    ),
    idempotent=True,
    is_framework=True,
)
@unique
class EvaluatesAt(Enum):
    """Evaluation scope — at what level signals from this nerve are assessed.

    Also used as the ``scope`` field on ganglion declarations.
    """

    FUNCTION_BOUNDARY = "FUNCTION_BOUNDARY"
    SUBSYSTEM = "SUBSYSTEM"
    SYSTEM = "SYSTEM"


# ---------------------------------------------------------------------------
# Kind-to-declaration-type compatibility mapping (spec §3.1)
# ---------------------------------------------------------------------------

VALID_KINDS_FOR_DECLARATION: dict[DeclarationType, frozenset[Kind]] = {
    DeclarationType.NERVE: frozenset({
        Kind.SERVICE,
        Kind.FUNCTION,
        Kind.ADAPTER,
        Kind.ORCHESTRATOR,
        Kind.FRAMEWORK,
    }),
    DeclarationType.CELL: frozenset({
        Kind.MODEL,
        Kind.CONSTANT,
        Kind.CONFIG,
        Kind.ENUM,
        Kind.EXCEPTION,
        Kind.TYPE,
        Kind.FRAMEWORK,
    }),
    # Ganglia, tests, axons, modules, helpers, and doc declarations do not
    # have a kind field.
    DeclarationType.GANGLION: frozenset(),
    DeclarationType.TEST: frozenset(),
    DeclarationType.AXON: frozenset(),
    DeclarationType.MODULE: frozenset(),
    DeclarationType.HELPER: frozenset(),
    DeclarationType.DOC_REF: frozenset(),
    DeclarationType.DOC_GUIDE: frozenset(),
    DeclarationType.EXAMPLE: frozenset(),
}
