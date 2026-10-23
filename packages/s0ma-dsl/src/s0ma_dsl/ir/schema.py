"""IR schema types for the .s0ma.json intermediate representation.

Defines the typed data structures that represent a module's normalized,
fully-resolved JSON artifact per PRD §2.5.2. These are pure data
containers consumed by the IR builder and serialized to JSON.

Schema version: 1.0.0
PRD references: FR-23, §2.5 (IR schema, determinism, versioning)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from s0ma_dsl.semantic_state import SemanticState

__all__ = [
    "SCHEMA_VERSION",
    "IRSchemaVersionError",
    "validate_ir_schema_version",
    "TRANSPILER_VERSION",
    "RESERVED_COMPONENT_METADATA_KEYS",
    "IRModule",
    "IRComponent",
    "IRComponentLocation",
    "IRAuthoredEdge",
    "IRDerivedEdge",
    "IRVerificationEdge",
    "IREdges",
    "IRRequiresImport",
    "IRUsesImport",
    "IRPrivilegedImport",
    "IRImports",
    # M13 (feedback 5–6) — module-private helper declarations.
    "IRHelper",
    # POST-5 (0.16.0) — first-class integration declarations.
    "IRIntegration",
    # Documentation subsystem (plan M5)
    "IREntityRef",
    "IRComparisonPredicate",
    "IRBooleanPredicate",
    "IRFilterExpr",
    "IRSection",
    "IRAssertComparison",
    "IRAssertBoolean",
    "IRDocRef",
    "IRDocGuide",
    "IRExample",
    "IRDocument",
]

# Bumped to 1.3.0 in POST-5 (0.16.0): additive extension introducing the
# ``integrations`` IR section. Pre-POST-5 IR documents (1.2.0) remain
# readable; consumers that don't know about ``integrations`` simply
# ignore the new top-level array.
# Bumped to 2.0.0 in the s0ma consolidation (M3): BREAKING — the artifact
# extension family is renamed to ``.s0ma`` / ``.s0ma.json`` / ``.s0ma.map``
# (build manifest ``build.s0ma.json``) and the emitted hash placeholder
# markers are renamed to ``__S0MA_SOURCE_HASH__`` / ``__S0MA_OUTPUT_HASH__``
# (comment markers ``# s0ma-source-hash:`` / ``# s0ma-output-hash:``).
# Consumers of 1.x IR must regenerate; ``s0ma migrate-ext`` migrates
# on-disk artifacts of the old extension family.
# Bumped to 2.1.0 in DSL-M1 (0.8.0, ADR-011 §(g)): additive — new optional
# ``components[].fields`` keys ``metadata`` (authored declaration metadata,
# JSON object in authored key order) and ``serves_as`` (public serving
# name), plus M2's ``covered_by`` / ``imports.deferred_requires`` under the
# same version. Absent = not authored; consumers of 2.0.0 documents keep
# parsing 2.1.0 ones unchanged.
SCHEMA_VERSION = "3.0.0"
TRANSPILER_VERSION = "1.0.0"


class IRSchemaVersionError(ValueError):
    """Raised when a canonical IR reader encounters an unsupported major."""

    code = "UNSUPPORTED_IR_SCHEMA_MAJOR"


def validate_ir_schema_version(payload: dict[str, Any]) -> None:
    """Refuse unknown canonical-IR majors with an actionable migration path."""

    raw = payload.get("schema_version")
    if not isinstance(raw, str) or not raw:
        raise IRSchemaVersionError(
            "UNSUPPORTED_IR_SCHEMA_MAJOR: canonical IR is missing schema_version; "
            "rebuild it with `s0ma build` using this toolchain."
        )
    major = raw.split(".", 1)[0]
    supported = SCHEMA_VERSION.split(".", 1)[0]
    if major != supported:
        raise IRSchemaVersionError(
            f"UNSUPPORTED_IR_SCHEMA_MAJOR: found s0ma-ir@{major}, supported "
            f"major is s0ma-ir@{supported}; run `s0ma migrate grammar` on "
            "authored sources, then rebuild with `s0ma build`."
        )

# ---------------------------------------------------------------------------
# Reserved component-metadata keys (DSL-M1, 0.8.0 — ADR-011 §(a), rule L-1)
#
# The single source of truth (P-2) for the keys the EMITTER writes into the
# registration ``metadata=`` dicts it generates — authored ``metadata:``
# entries must not collide with them, because the authored map is appended
# into the same dict. One UNION set across all declaration kinds (not
# per-kind): predictable for authors, and it keeps the emitter free to
# extend any kind's emitted keys without a compat break. The set spans the
# five emission shapes (nerve / ganglion / class cell / CONSTANT+TYPE cell /
# integration helpers) plus this batch's two authored-but-emitter-written
# keys (``serves_as`` now, ``covered_by`` at M2). ``deferred`` here is the
# POST-12f stub-marker metadata key (a different record family from the M2
# ``deferred_requires:`` import field). ``value`` is the literal a CONSTANT
# cell's body assigns: the emitter passes it to ``register_constant``,
# which stores it in the same metadata dict (``ir/constant_values.py``).
#
# Consumers: ``semantic/validator.py`` rejects authored collisions with
# ``METADATA_RESERVED_KEY``; the emitter test
# ``test_every_emitter_written_metadata_key_is_reserved`` asserts every key
# the emitter writes is a member, so the set cannot silently drift when a
# future change adds an emitted key.
# ---------------------------------------------------------------------------

RESERVED_COMPONENT_METADATA_KEYS: frozenset[str] = frozenset({
    "abstract", "category", "consumes_via_dict", "covered_by", "dataclass_invariants",
    "deferred", "evaluates_at", "expected_exceptions", "integration", "integration_helper",
    "integration_manifest", "interface", "invariants", "kind_detail", "observes",
    "observes_patterns", "on_anomaly", "priors", "provides", "provides_contracts", "raises",
    "resolved_observes", "returns", "schema", "scope", "serves_as", "value", "visibility",
})


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_IRComponentLocation",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="Tracks the start and end line of a component in the .s0ma source file for the IR.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRComponentLocation:
    """Source location span for an IR component entry."""

    start_line: int
    end_line: int

    def to_dict(self) -> dict[str, Any]:
        return {"start_line": self.start_line, "end_line": self.end_line}


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_IRModule",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Module-level metadata block in the IR, carrying name, layer, version, intent, hashes, "
        "and file paths."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRModule:
    """Module metadata block in the .s0ma.json IR.

    POST-4c (0.15.0): ``exports_helpers`` lists helper names this
    module deliberately exposes for cross-module reachability. The
    access-control rule (test-context only) is unchanged — the field
    is a producer-side declaration of intent.
    """

    name: str
    layer: str
    version: str
    intent: str
    content_hash: str
    source_file: str
    transpiled_file: str
    tags: tuple[str, ...] = ()

    exports_helpers: tuple[str, ...] = ()
    """POST-4c (0.15.0): helper names exposed for cross-module reachability."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "layer": self.layer,
            "version": self.version,
            "intent": self.intent,
            "content_hash": self.content_hash,
            "source_file": self.source_file,
            "transpiled_file": self.transpiled_file,
            "tags": list(self.tags),
            "exports_helpers": list(self.exports_helpers),
        }


# ---------------------------------------------------------------------------
# Component entry
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_IRComponent",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "A single component entry in the IR, carrying canonical ID, declaration type, kind, "
        "visibility, intent, and fields."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRComponent:
    """A single component entry in the .s0ma.json IR."""

    canonical_id: str
    declaration_type: str
    kind: str | None
    visibility: str | None
    intent: str
    fields: dict[str, Any]
    location: IRComponentLocation

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "declaration_type": self.declaration_type,
            "kind": self.kind,
            "visibility": self.visibility,
            "intent": self.intent,
            # ``IRDocument.to_dict`` replaces state-aware leaves in this
            # serialized view. Do not leak those replacements back into the
            # typed component through a shared mutable dictionary.
            "fields": dict(self.fields),
            "location": self.location.to_dict(),
        }


# ---------------------------------------------------------------------------
# Edge types
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_IRAuthoredEdge",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "An authored dependency edge in the IR, carrying source, target, relation, carries, "
        "coupling, intent, and origin."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRAuthoredEdge:
    """An authored dependency edge in the IR."""

    source: str
    target: str
    relation: str
    carries: str
    coupling: str
    intent: str
    origin: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "carries": self.carries,
            "coupling": self.coupling,
            "intent": self.intent,
            "origin": self.origin,
        }


@component(
    name="S0maDSL_IRDerivedEdge",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "A derived dependency edge in the IR, carrying source, target, relation, and derivation "
        "origin."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRDerivedEdge:
    """A derived dependency edge (RAISES or TYPE_USES) in the IR."""

    source: str
    target: str
    relation: str
    origin: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "origin": self.origin,
        }


@component(
    name="S0maDSL_IRVerificationEdge",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="A verification edge in the IR, linking a test to the component it validates.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRVerificationEdge:
    """A verification (test→component) edge in the IR."""

    test: str
    validates: str
    origin: str = "tests_field"

    def to_dict(self) -> dict[str, Any]:
        return {
            "test": self.test,
            "validates": self.validates,
            "origin": self.origin,
        }


@component(
    name="S0maDSL_IREdges",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="Container for all edge categories (authored, derived, verification) in the IR.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IREdges:
    """All dependency and verification edges in the IR."""

    authored: tuple[IRAuthoredEdge, ...] = ()
    derived: tuple[IRDerivedEdge, ...] = ()
    verification: tuple[IRVerificationEdge, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "authored": [e.to_dict() for e in self.authored],
            "derived": [e.to_dict() for e in self.derived],
            "verification": [e.to_dict() for e in self.verification],
        }


# ---------------------------------------------------------------------------
# Import entries
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_IRRequiresImport",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="A requires (external Python dependency) import entry in the IR.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRRequiresImport:
    """A requires import entry in the IR.

    DSL-M2 (0.8.0, ADR-011 §(c)/(g)): entries built from
    ``deferred_requires:`` carry ``deferred=True`` and serialize the
    self-describing ``"deferred": true`` key, so consumers reading
    flattened entry lists keep the fact without knowing the list name.
    Entries in the other three requires-family lists do NOT serialize
    a ``deferred: false`` key — omitted-means-false keeps every
    existing build's IR bytes unchanged (L-7).
    """

    module_path: str
    alias: str | None
    is_from_import: bool
    deferred: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = {
            "module_path": self.module_path,
            "alias": self.alias,
            "is_from_import": self.is_from_import,
        }
        if self.deferred:
            d["deferred"] = True
        return d


@component(
    name="S0maDSL_IRUsesImport",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="A uses (cross-module s0ma component) import entry in the IR.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRUsesImport:
    """A uses import entry in the IR."""

    qualified_name: str
    alias: str | None
    resolved_canonical_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualified_name": self.qualified_name,
            "alias": self.alias,
            "resolved_canonical_id": self.resolved_canonical_id,
        }


@component(
    name="S0maDSL_IRPrivilegedImport",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "A privileged import entry in the IR for cross-module INTERNAL access in tests and "
        "ganglia."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRPrivilegedImport:
    """A privileged import entry in the IR."""

    canonical_id: str
    import_kind: str
    referenced_in: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "import_kind": self.import_kind,
            "referenced_in": self.referenced_in,
        }


@component(
    name="S0maDSL_IRImports",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="Container for all import categories (requires, uses, privileged) in the IR.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRImports:
    """All import entries in the IR.

    POST-10b (0.16.0): ``runtime_only_requires`` mirrors
    ``requires`` in surface shape but is the carve-out for imports
    that should land on the generated module without contributing
    to the Phase 4 vestigial check (canonically: ``pytest`` pulled
    in via the runner's fixture machinery rather than an explicit
    ``pytest.<symbol>`` body reference).
    """

    requires: tuple[IRRequiresImport, ...] = ()
    soft_requires: tuple[IRRequiresImport, ...] = ()
    uses: tuple[IRUsesImport, ...] = ()
    privileged: tuple[IRPrivilegedImport, ...] = ()
    runtime_only_requires: tuple[IRRequiresImport, ...] = ()
    # DSL-M2 (0.8.0, ADR-011 §(c)/(g)): imports the emitter injects
    # into each consuming def body instead of the module top. Each
    # entry serializes with ``"deferred": true``. The key is OMITTED
    # from the serialized document when the list is empty so existing
    # builds' IR bytes stay unchanged (L-7).
    deferred_requires: tuple[IRRequiresImport, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = {
            "requires": [i.to_dict() for i in self.requires],
            "soft_requires": [i.to_dict() for i in self.soft_requires],
            "uses": [i.to_dict() for i in self.uses],
            "privileged": [i.to_dict() for i in self.privileged],
            "runtime_only_requires": [
                i.to_dict() for i in self.runtime_only_requires
            ],
        }
        if self.deferred_requires:
            d["deferred_requires"] = [
                i.to_dict() for i in self.deferred_requires
            ]
        return d


# ---------------------------------------------------------------------------
# Documentation subsystem IR (plan M5, design §11.7)
# ---------------------------------------------------------------------------
#
# Structured representations of M2/M3 doc-subsystem AST nodes used in the
# canonical `.s0ma.json`. Per the M2 handoff notes, the `raw` field on the
# AST node is debugging-only and is NOT part of the IR — only the
# structured form is serialised, so renderers and content-hashers see a
# whitespace-independent representation.


@component(
    name="S0maDSL_IREntityRef",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="An entity reference (kind + name + optional dotted field path) in the IR.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IREntityRef:
    """An entity reference in the IR — ``kind::name[.field_path]``."""

    kind: str
    name: str
    field_path: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "field_path": list(self.field_path),
        }


@component(
    name="S0maDSL_IRComparisonPredicate",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="A binary comparison predicate (==/!=/in) inside a filter expression in the IR.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRComparisonPredicate:
    """A filter-context comparison predicate in the IR.

    The left-hand side is always a bare field-path tuple; the entity context
    is supplied by the enclosing :class:`IRFilterExpr`. Asserts use
    :class:`IRAssertComparison` instead, where the lhs is an entity ref.
    """

    lhs: tuple[str, ...]
    operator: str
    rhs: str | tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "comparison",
            "lhs": list(self.lhs),
            "operator": self.operator,
            "rhs": list(self.rhs) if isinstance(self.rhs, tuple) else self.rhs,
        }


@component(
    name="S0maDSL_IRBooleanPredicate",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="Boolean composition (and/or/not) of filter predicates in the IR.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRBooleanPredicate:
    """Boolean composition of filter predicates in the IR."""

    operator: str
    operands: tuple[IRComparisonPredicate | IRBooleanPredicate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "boolean",
            "operator": self.operator,
            "operands": [op.to_dict() for op in self.operands],
        }


@component(
    name="S0maDSL_IRFilterExpr",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "A filter expression (kind selector + optional predicate / ordering / grouping) in the "
        "IR."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRFilterExpr:
    """A doc-ref filter expression in the IR."""

    kind: str
    predicate: IRComparisonPredicate | IRBooleanPredicate | None = None
    ordered_by: tuple[str, ...] = ()
    group_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "predicate": self.predicate.to_dict() if self.predicate else None,
            "ordered_by": list(self.ordered_by),
            "group_by": self.group_by,
        }


@component(
    name="S0maDSL_IRSection",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="A doc-ref sections entry — bare field reference or iteration — in the IR.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRSection:
    """A single ``sections:`` entry in the IR.

    Exactly one of ``field_name`` or ``iteration`` is populated, mirroring
    the M2 :class:`SectionAst` discriminated union.
    """

    field_name: str | None = None
    iteration: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "iteration": self.iteration,
        }


@component(
    name="S0maDSL_IRAssertComparison",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="A doc-guide assert comparison (entity ref vs literal) in the IR.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRAssertComparison:
    """An assert comparison in the IR — ``entity::name.field OP literal``."""

    lhs: IREntityRef
    operator: str
    rhs: str | tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "comparison",
            "lhs": self.lhs.to_dict(),
            "operator": self.operator,
            "rhs": list(self.rhs) if isinstance(self.rhs, tuple) else self.rhs,
        }


@component(
    name="S0maDSL_IRAssertBoolean",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="Boolean composition (and/or/not) of doc-guide assert comparisons in the IR.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRAssertBoolean:
    """Boolean composition of assert comparisons in the IR."""

    operator: str
    operands: tuple[IRAssertComparison | IRAssertBoolean, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "boolean",
            "operator": self.operator,
            "operands": [op.to_dict() for op in self.operands],
        }


@component(
    name="S0maDSL_IRDocRef",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "A doc-ref declaration entry in the IR carrying name, format, output, covers, sections, "
        "and source location."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRDocRef:
    """A doc-ref declaration in the IR.

    The ``covers`` field is a discriminated union: the historic form is a
    tuple of :class:`IRFilterExpr` selecting project entities; G7a added
    the ``covers_source`` form for derived registries
    (``covers: { source: error_codes }``). Exactly one is set; the other
    is the empty tuple / ``None``. The discriminator round-trips through
    ``to_dict`` so consumers can re-derive it without re-parsing.
    """

    name: str
    module: str
    intent: str
    format: str
    output: str
    covers: tuple[IRFilterExpr, ...]
    sections: tuple[IRSection, ...]
    content_hash: str
    location: IRComponentLocation
    tags: tuple[str, ...] = ()
    covers_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "module": self.module,
            "intent": self.intent,
            "format": self.format,
            "output": self.output,
            "covers": [c.to_dict() for c in self.covers],
            "covers_source": self.covers_source,
            "sections": [s.to_dict() for s in self.sections],
            "content_hash": self.content_hash,
            "location": self.location.to_dict(),
            "tags": list(self.tags),
        }


@component(
    name="S0maDSL_IRDocGuide",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "A doc-guide declaration entry in the IR carrying covers, asserts, examples, prose body, "
        "and source location."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRDocGuide:
    """A doc-guide declaration in the IR.

    The prose body is stored byte-exactly. Prose tokens are NOT serialised
    to the IR — they are deterministically rederivable from the body by
    re-running the M3 prose parser, and excluding them keeps the IR small.
    """

    name: str
    module: str
    intent: str
    format: str
    output: str
    covers: tuple[IREntityRef, ...]
    asserts: tuple[IRAssertComparison | IRAssertBoolean, ...]
    examples: tuple[IREntityRef, ...]
    body: str
    content_hash: str
    location: IRComponentLocation
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "module": self.module,
            "intent": self.intent,
            "format": self.format,
            "output": self.output,
            "covers": [c.to_dict() for c in self.covers],
            "asserts": [a.to_dict() for a in self.asserts],
            "examples": [e.to_dict() for e in self.examples],
            "body": self.body,
            "content_hash": self.content_hash,
            "location": self.location.to_dict(),
            "tags": list(self.tags),
        }


@component(
    name="S0maDSL_IRExample",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "An example declaration entry in the IR carrying demonstrates, runs_in, python body, and "
        "source location."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRExample:
    """An example declaration in the IR."""

    name: str
    module: str
    intent: str
    demonstrates: tuple[IREntityRef, ...]
    runs_in: str
    body: str
    location: IRComponentLocation
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "module": self.module,
            "intent": self.intent,
            "demonstrates": [d.to_dict() for d in self.demonstrates],
            "runs_in": self.runs_in,
            "body": self.body,
            "location": self.location.to_dict(),
            "tags": list(self.tags),
        }


# ---------------------------------------------------------------------------
# M13 (feedback 5–6) — helper declarations
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_IRHelper",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "A helper declaration entry in the IR — module-private, not registered as a component, "
        "but introspectable via s0ma inspect."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRHelper:
    """A helper declaration in the IR (M13, feedback 5–6).

    Helpers are module-private functions or classes that are
    introspectable but *not* registered as components. They have no
    ``kind`` or ``visibility`` field. The IR record carries the
    canonical id, the helper's intent, the body text, and source
    location so that ``s0ma inspect`` can render a separate
    ``[helpers]`` section.

    POST-4a (0.15.0): ``body_kind`` records whether the helper's body
    is a function (``"function"``, the M13 default) or a class
    (``"class"``, the new shape). POST-4b adds ``inline`` to mark
    helpers declared via the ``@inline`` shorthand inside the module
    header.
    """

    canonical_id: str
    """Canonical id ``module::name`` — same form as IRComponent."""

    name: str
    """Helper name (by convention starts with ``_``)."""

    module: str
    """Owning module name."""

    layer: str
    """Layer string (matches the module's layer)."""

    intent: str
    """Required intent prose recorded on the declaration."""

    body: str
    """Verbatim function or class body as captured from the .s0ma source."""

    location: IRComponentLocation
    """Source location of the declaration."""

    tags: tuple[str, ...] = ()

    body_kind: str = "function"
    """POST-4a (0.15.0): ``"function"`` or ``"class"`` — the structural
    shape of the body. Pre-POST-4a helpers always recorded
    ``"function"``."""

    inline: bool = False
    """POST-4b (0.15.0): True iff the helper was declared via the
    ``@inline`` shorthand inside a module header's ``helpers:`` list."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "name": self.name,
            "module": self.module,
            "layer": self.layer,
            "intent": self.intent,
            "body": self.body,
            "body_kind": self.body_kind,
            "inline": self.inline,
            "location": self.location.to_dict(),
            "tags": list(self.tags),
        }


# ---------------------------------------------------------------------------
# POST-5 (0.16.0) — first-class integration declarations
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_IRIntegration",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "An integration declaration entry in the IR — a first-class external-system adapter "
        "carrying factory, smoke-test, and manifest metadata."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRIntegration:
    """An integration declaration in the IR (POST-5, 0.16.0).

    First-class external-system adapters declared via ``integration
    <Name> :: INFRASTRUCTURE``. The IR records the four metadata
    fields the codegen reads when synthesising the auto-emitted
    ``get_factory`` / ``get_manifest`` / ``smoke_test_primary`` /
    ``get_smoke_test`` helpers.

    The integration itself is *not* a registered component — it lives
    in a separate IR section (``integrations``) parallel to ``helpers``.
    The four auto-emitted helpers are the public surface that downstream
    consumers reach via ``uses:`` (resolved through
    ``IRIntegration.canonical_id``).
    """

    canonical_id: str
    """``module::name`` — same form as IRComponent / IRHelper."""

    name: str
    """Integration declaration name (the bare identifier after
    ``integration``)."""

    module: str
    """Owning module name."""

    layer: str
    """Layer string — always ``"INFRASTRUCTURE"`` (validated upstream)."""

    version: str
    """Semver string declared on the integration."""

    intent: str
    """Required intent prose recorded on the declaration."""

    factory: str
    """Name of a SERVICE nerve in the same module that this integration
    wraps."""

    smoke_test_primary: str
    """Name of a nerve providing the primary smoke-test entry point."""

    manifest: dict[str, Any]
    """Structured manifest map (provides / required_env /
    requires_oauth / arbitrary keys). Round-trips verbatim."""

    location: IRComponentLocation
    """Source location of the declaration."""

    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "name": self.name,
            "module": self.module,
            "layer": self.layer,
            "version": self.version,
            "intent": self.intent,
            "factory": self.factory,
            "smoke_test_primary": self.smoke_test_primary,
            "manifest": dict(self.manifest),
            "location": self.location.to_dict(),
            "tags": list(self.tags),
        }


# ---------------------------------------------------------------------------
# Top-level IR document
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_IRDocument",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="Top-level IR document representing the complete .s0ma.json output for a single module.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IRDocument:
    """Top-level IR document — the complete .s0ma.json for a module.

    This is the primary machine interface for AI tools to query a
    module's self-model per PRD §2.5.
    """

    schema_version: str
    transpiler_version: str
    source_hash: str
    module: IRModule
    components: tuple[IRComponent, ...]
    edges: IREdges
    imports: IRImports
    exports: tuple[str, ...]

    # Documentation subsystem (plan M5, additive — schema bumped to 1.1.0)
    doc_refs: tuple[IRDocRef, ...] = ()
    doc_guides: tuple[IRDocGuide, ...] = ()
    examples: tuple[IRExample, ...] = ()

    # M13 (feedback 5–6, additive — schema bumped to 1.2.0). Helpers are
    # module-private, not registered as components, but introspectable
    # via ``s0ma inspect``. Pre-M13 IR readers see this as an empty
    # array on legacy modules; new modules emit non-empty arrays when
    # they contain ``helper`` declarations.
    helpers: tuple[IRHelper, ...] = ()

    # POST-5 (0.16.0, additive — schema bumped to 1.3.0). Integrations
    # are first-class external-system adapters that auto-emit four
    # module-scoped helper functions (get_factory / get_manifest /
    # smoke_test_primary / get_smoke_test). The integration declaration
    # itself is *not* a registered component; the four auto-emitted
    # helpers are. The IR records each integration separately so
    # ``s0ma inspect`` can render an ``Integrations`` section parallel
    # to ``Helpers``. Pre-POST-5 IR readers see this as an empty array.
    integrations: tuple[IRIntegration, ...] = ()

    # M3A compatibility carrier: paths are applied only while serialising.
    # The established typed IR records keep their primitive in-memory view
    # for emitters; canonical JSON is exclusively the tagged s0ma-ir@3 view.
    semantic_state_paths: tuple[
        tuple[tuple[str | int, ...], SemanticState], ...
    ] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary.

        Keys are sorted for deterministic output per PRD §2.5.3.
        """
        payload: dict[str, Any] = {
            "components": [c.to_dict() for c in self.components],
            "doc_guides": [g.to_dict() for g in self.doc_guides],
            "doc_refs": [r.to_dict() for r in self.doc_refs],
            "edges": self.edges.to_dict(),
            "examples": [e.to_dict() for e in self.examples],
            "exports": list(self.exports),
            "helpers": [h.to_dict() for h in self.helpers],
            "imports": self.imports.to_dict(),
            "integrations": [
                i.to_dict() for i in self.integrations
            ],
            "module": self.module.to_dict(),
            "schema_version": self.schema_version,
            "source_hash": self.source_hash,
            "transpiler_version": self.transpiler_version,
        }
        for path, state in self.semantic_state_paths:
            cursor: Any = payload
            for part in path[:-1]:
                if isinstance(part, int):
                    cursor = cursor[part]
                else:
                    if part not in cursor:
                        cursor[part] = {}
                    cursor = cursor[part]
            leaf = path[-1]
            if state.state == "value":
                if isinstance(state.value, (str, int, float, bool, list, dict)):
                    value = state.value
                elif isinstance(cursor, list) and isinstance(leaf, int):
                    value = cursor[leaf]
                else:
                    value = cursor.get(leaf)
                rendered = {"state": "value", "value": value}
            else:
                rendered = state.to_dict()
            if isinstance(cursor, list) and isinstance(leaf, int):
                cursor[leaf] = rendered
            else:
                cursor[leaf] = rendered
        return payload
