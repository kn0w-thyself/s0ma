"""AST node dataclasses for the s0ma DSL.

Every declaration type from the spec has a corresponding frozen dataclass.
Every field from Appendix A is represented.  Nodes carry ``SourceLocation``
for diagnostics and are the output of the parser (Stages 1-2).

These are pure data structures — no parsing or validation logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma.decorators import component
from s0ma.types import ComponentKind
from s0ma.types import Layer as S0maLayer

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.enums import (
        Coupling,
        EvaluatesAt,
        Kind,
        Layer,
        Relation,
        Visibility,
    )
    from s0ma_dsl.semantic_state import SemanticState

__all__ = [
    "SourceLocation",
    "MetadataValue",
    "METADATA_INVALID_VALUE_MARKER",
    "SemanticStateMap",
    "RequiresEntry",
    "UsesEntry",
    "ProvidesEntry",
    "InternalHelperEntry",
    "ConsumesViaDictEntry",
    "InlineAxon",
    "ModuleDecl",
    "NerveDecl",
    "CellDecl",
    "GanglionDecl",
    "TestDecl",
    "StandaloneAxonDecl",
    "HelperDecl",
    "IntegrationDecl",
    "S0maModule",
    # Documentation subsystem
    "EntityRefAst",
    "ComparisonPredicate",
    "BooleanPredicate",
    "FilterExprAst",
    "IterationAst",
    "SectionAst",
    "AssertComparison",
    "AssertBoolean",
    "DocRefDecl",
    "DocGuideDecl",
    "ExampleDecl",
    # Documentation subsystem prose body (M3)
    "TextChunk",
    "ReferenceToken",
    "ExampleEmbedToken",
    "ProseToken",
]


# ---------------------------------------------------------------------------
# Source location
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_SourceLocation",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Tracks the start/end line and column of a declaration in .s0ma source for diagnostics "
        "and source maps."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class SourceLocation:
    """Source location span in a ``.s0ma`` file.

    Attached to every AST node so diagnostics and source maps can reference
    the original source precisely.
    """

    start_line: int
    start_column: int
    end_line: int
    end_column: int
    file: str = ""


# ---------------------------------------------------------------------------
# Authored declaration metadata (DSL-M1, 0.8.0 — ADR-011 §(a), rule L-1)
# ---------------------------------------------------------------------------

#: The L-1 value shape set for authored ``metadata:`` entries: a string,
#: an int, a float, a bool, or a tuple of strings (the bracketed-list
#: form). Nested maps and null values are out at plan level.
MetadataValue = str | int | float | bool | tuple[str, ...]
SemanticStateMap = tuple[tuple[str, "SemanticState"], ...]

#: Sentinel prefix marking a ``metadata:`` entry value the parser could
#: not represent in the L-1 shape set (nested map, null, unquoted bare
#: token, malformed list, or the unsupported inline ``metadata: {...}``
#: form). The format is ``<marker><reason>\x00<raw-display>``. Parsing
#: never fails on these — the semantic validator owns the diagnostic
#: (``METADATA_INVALID_VALUE``) so authors get structured
#: code/line/remediation output instead of a parse abort. Real string
#: values can never collide with the marker: authored .s0ma source
#: cannot contain NUL bytes in a field value position.
METADATA_INVALID_VALUE_MARKER = "\x00<METADATA_INVALID_VALUE>\x00"


# ---------------------------------------------------------------------------
# Dependency-related sub-nodes
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_RequiresEntry",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Represents a single external Python dependency in a module's requires list, with "
        "optional alias and from-import detection."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class RequiresEntry:
    """A single entry in a module's ``requires`` list.

    ``module_path`` is the dotted Python import path (e.g. ``"uuid.UUID"``).
    If the path contains a dot and the final segment is capitalised, it is
    treated as a from-import (``from uuid import UUID``).
    ``alias`` is the optional ``as`` name.
    """

    module_path: str
    alias: str | None = None
    is_from_import: bool = False
    location: SourceLocation | None = None


@component(
    name="S0maDSL_UsesEntry",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Represents a cross-module s0ma component dependency in a module's uses list, with "
        "optional alias."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class UsesEntry:
    """A single entry in a module's ``uses`` list.

    ``qualified_name`` is ``module.component`` (e.g. ``"routing.select_evaluator"``).
    ``alias`` is the optional ``as`` name.
    """

    qualified_name: str
    alias: str | None = None
    location: SourceLocation | None = None


@component(
    name="S0maDSL_ProvidesEntry",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Represents one entry in a SERVICE nerve's provides list — the operation name plus "
        "a per-method returns/expects/guarantees contract triple whose three slots are each "
        "optional."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class ProvidesEntry:
    """A single entry in a SERVICE nerve's ``provides`` list.

    The flat form (``provides: [foo, bar]``) parses to entries with
    ``name`` set and every triple slot ``None``. The structured form
    (``provides: - foo: { returns: ..., expects: ..., guarantees: ... }``,
    introduced in 0.15.0 via POST-3a) populates one or more of the
    triple slots. All three slots are independently optional so authors
    can declare just the corner that disambiguates their contract.

    The triple is *descriptive only* — it rides through the IR and the
    emitted Python's ``metadata`` dict so introspecting agents (fr3d's
    settings/OAuth nerves are the motivating consumers) can read the
    per-method contract without re-parsing the source. The validator's
    existing ``MISSING_PROVIDED_FUNCTION`` / ``MISSING_RETURN_KEY``
    checks operate on the entry names exactly as before — the triple
    does not introduce a new error code in this milestone.
    """

    name: str
    returns: str | None = None
    expects: str | None = None
    guarantees: str | None = None
    location: SourceLocation | None = None

    @property
    def has_triple(self) -> bool:
        """True iff at least one of ``returns`` / ``expects`` / ``guarantees`` is set."""
        return any(
            v is not None for v in (self.returns, self.expects, self.guarantees)
        )


@component(
    name="S0maDSL_InternalHelperEntry",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Represents one entry in a nerve's internal-helpers list — an inner function "
        "defined within the nerve body that is introspectable via s0ma inspect but never "
        "registered as a component."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class InternalHelperEntry:
    """A single entry in a nerve's ``internal:`` list (POST-3d, 0.15.0).

    Inner helper functions defined inside a SERVICE nerve body (the
    common case is a closure-style factory that returns a dict of
    callables, where each callable depends on small private helpers
    declared above it) are *not* components — they live behind the
    factory's closure and never reach the registry. The ``internal:``
    field surfaces them for introspection without promoting them to
    public components:

        nerve PromptAssembler :: APPLICATION
            kind: SERVICE
            ...
            internal:
              - _normalize_topic: "Strip whitespace and lowercase the topic"
              - _escape_html: "Escape HTML-special chars"
            ---
            def _normalize_topic(topic): ...
            def _escape_html(s): ...
            ...

    ``name`` is a Python identifier (the parser enforces this via
    ``PARSE_ERROR`` if violated). ``intent`` is an optional one-line
    description; the inline form ``internal: [_foo, _bar]`` parses
    each entry with ``intent=None``, while the block form
    ``internal:\\n      - _foo: "..."`` populates ``intent``.

    The entry is purely descriptive — the validator does not enforce
    that every named inner function actually appears as a top-level
    ``def`` in the body (that check is deferred per the milestone
    spec). Codegen ignores ``internal:`` entirely; the nerve body
    emits unchanged. ``s0ma inspect`` renders the entries under a
    separate "Internal helpers" sub-section so a reader can see the
    private surface at a glance without scrolling the body.
    """

    name: str
    intent: str | None = None
    location: SourceLocation | None = None


@component(
    name="S0maDSL_ConsumesViaDictEntry",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Represents one entry in a nerve's consumes_via_dict list — a duck-typed coupling where "
        "the nerve reads a contract via dict-key access rather than attribute access."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class ConsumesViaDictEntry:
    """A single entry in a nerve's ``consumes_via_dict:`` list (POST-12d, 0.16.0).

    Surfaces a duck-typed coupling between a nerve body and an
    injected dependency that the body accesses by dict key rather
    than attribute. The motivating case: a nerve receives a
    ``SettingsDict`` (a CONSUMES :: TypedDict cell) on a ``config``
    parameter and reads it via ``config["api_key"]``. Without this
    field, the contract relationship is invisible — neither the
    validator nor the registry can see that the nerve consumes the
    ``SettingsDict`` contract because the access shape is keyed
    indirection, not direct name resolution.

    ``contract`` MUST resolve to either a known cell in the current
    module OR a ``uses:`` target. ``param`` MUST be a parameter on
    the nerve body's outer function (closure-scoped parameters do
    not count). The validator enforces both — see
    :data:`CONSUMES_VIA_DICT_INVALID` for the diagnostic — but the
    parser accepts arbitrary identifiers so authors can correct the
    mistake at validator time without the parser failing first.

    Surface form (block list)::

        consumes_via_dict:
          - contract: SettingsDict
            param: config
          - contract: FeatureFlags
            param: flags

    Inline form (one entry, single line) is intentionally NOT
    supported: the ``contract:`` / ``param:`` pair is structural, so
    the block form is the canonical surface.
    """

    contract: str
    param: str
    location: SourceLocation | None = None


@component(
    name="S0maDSL_InlineAxon",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Represents an inline authored dependency declared in a depends_on block within a nerve, "
        "ganglion, or test."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class InlineAxon:
    """An inline axon entry from a ``depends_on`` block.

    Represents an intra-module authored dependency with its target name,
    relation type, data carried, and coupling strength.
    """

    target: str
    relation: Relation
    carries: str
    coupling: Coupling
    location: SourceLocation | None = None


# ---------------------------------------------------------------------------
# Declaration nodes
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_ModuleDecl",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a module declaration — the mandatory header of every .s0ma file carrying "
        "layer, version, imports, and exports."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class ModuleDecl:
    """Module declaration — must be the first declaration in every ``.s0ma`` file.

    Defines the module's layer, version, intent, external dependencies,
    cross-module s0ma references, and exported public interface.

    POST-4c (0.15.0): ``exports_helpers`` lists helper names whose
    cross-module reachability is opened up — consumers may name them in
    their ``uses:`` list as ``<module>.<helper>``. The M13 access-control
    rule still applies: test-context consumers reach them, production
    consumers still hit ``HELPER_PRIVATE_TO_MODULE``. The validator
    cross-checks every entry against the module's actual ``helper``
    declarations (``EXPORTED_HELPER_NOT_FOUND`` otherwise).
    """

    name: str
    layer: Layer
    version: str
    intent: str
    exports: tuple[str, ...]

    # Conditionally mandatory
    requires: tuple[RequiresEntry, ...] = ()
    uses: tuple[UsesEntry, ...] = ()

    # Optional
    soft_requires: tuple[RequiresEntry, ...] = ()
    tags: tuple[str, ...] = ()

    # POST-4c (0.15.0): names of helpers exposed for cross-module
    # reachability. Lookups in ``uses:`` of the form
    # ``<this_module>.<helper>`` resolve to the named helper iff the
    # helper appears here. The access-control rule from M13 still
    # applies (test-context only); ``exports_helpers:`` widens the
    # reachability surface, not the access-control surface.
    exports_helpers: tuple[str, ...] = ()

    # POST-10b (0.16.0): runtime-only Python dependencies that should
    # be imported in the emitted ``.py`` (exactly like ``requires:``)
    # but are exempt from the Phase 4 ``VESTIGIAL_IMPORT`` body-
    # evidence check. Closes the long-running ``pytest`` false-
    # positive: ``def test_foo(monkeypatch): ...`` pulls ``pytest``
    # in via the runner's fixture machinery without any body-side
    # ``pytest.<symbol>`` reference; listing it in
    # ``runtime_only_requires:`` keeps the import line on the
    # generated module while silencing the vestigial check. The
    # field is also a clean carve-out for any future "imported for
    # side effect at import time" case (registering hooks, etc.).
    runtime_only_requires: tuple[RequiresEntry, ...] = ()

    # DSL-M2 (0.8.0, ADR-011 §(c)): deferred Python dependencies —
    # same entry grammar as ``requires:`` (the soft/runtime_only
    # sibling-field precedent), but the emitter places the import
    # INSIDE each consuming def body (after the docstring) instead of
    # at module top. Per-call failure semantics: on a broken
    # environment the module still imports; each call of a consuming
    # def raises ``ImportError`` at the injected line (the F-M3-1
    # "start degraded, fail per-call" idiom, restored as an authored
    # choice). The static dependency record stays complete — the IR
    # lists these entries under ``imports.deferred_requires`` with
    # ``deferred: true``; ``MISSING_PACKAGE`` and the Phase 4
    # vestigial body-evidence check apply unchanged. Terminology note:
    # this is a deferred IMPORT field; the per-declaration
    # ``deferred:`` field (POST-12f) is the unrelated stub marker.
    deferred_requires: tuple[RequiresEntry, ...] = ()

    # M3A (0.14.0): canonical tagged state for every semantic field.
    # Existing attributes remain the compatibility projection until M3B.
    semantic_states: SemanticStateMap = ()

    location: SourceLocation | None = None


@component(
    name="S0maDSL_NerveDecl",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a nerve declaration — an observable function with kind, visibility, "
        "contracts, and optional dependencies."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class NerveDecl:
    """Nerve declaration — executable logic that serves the system.

    The body must be a ``def`` statement (not a class).
    """

    name: str
    layer: Layer
    kind: Kind
    visibility: Visibility
    intent: str
    expects: str
    guarantees: str
    evaluates_at: EvaluatesAt
    # What the nerve must never do, however it is called and whatever
    # happens while it runs. Required by the field table; ``none`` and
    # ``pending`` project to the empty string here, and the tagged state
    # is in ``semantic_states``.
    forbids: str = ""

    # Optional fields
    provides: tuple[str, ...] = ()
    # POST-3a (0.15.0): per-method ``returns:`` / ``expects:`` /
    # ``guarantees:`` triples for the ``provides:`` field. The legacy
    # flat form (``provides: [foo, bar]``) parses with ``provides_entries``
    # mirroring ``provides`` (one entry per name, every triple slot
    # ``None``). The structured form (``provides: - foo: { returns: ... }``)
    # populates the triple slots. Both forms keep ``provides`` itself
    # synchronised as the canonical ordered tuple of operation names so
    # every existing consumer (validator, emitter, IR) reads it
    # unchanged.
    provides_entries: tuple[ProvidesEntry, ...] = ()
    returns: tuple[str, ...] = ()
    raises: tuple[str, ...] = ()
    abstract: bool = False
    interface: tuple[str, ...] = ()
    latency_ms: int | None = None
    depends_on: tuple[InlineAxon, ...] = ()
    version: str | None = None
    tags: tuple[str, ...] = ()

    # POST-3d (0.15.0): inner-helper introspection surface. SERVICE
    # nerves frequently expose a public ``provides:`` set whose
    # implementations share small private helpers declared as inner
    # ``def`` statements above the factory's return dict. Those
    # helpers stay invisible to the registry — they are not
    # components, they are not exported, and ``s0ma inspect`` would
    # otherwise have no way to surface them. ``internal:`` is a
    # descriptive sub-list of those inner helpers so an introspecting
    # reader can see the private surface at a glance without scrolling
    # the body. The field carries no codegen effect — the nerve body
    # emits unchanged, no ``register_*`` call is generated for any
    # entry, and the registry stays unaware that the entries exist.
    # The validator does not enforce that every named entry actually
    # appears in the body (deferred per the milestone spec); the
    # field is the author's own descriptive contract with future
    # readers and tooling.
    internal_helpers: tuple[InternalHelperEntry, ...] = ()

    # POST-12a (0.16.0): Python-side exceptions the nerve catches by
    # design. Distinct from ``raises:`` (which lists s0ma cells the
    # nerve may raise) — ``expected_exceptions:`` is metadata about
    # Python-namespace exception types the body deliberately handles
    # via ``try/except``. Entries are dotted Python paths
    # (``json.JSONDecodeError``, ``urllib.error.HTTPError``) so they
    # round-trip cleanly through the IR and emitted metadata dict.
    # No validation side effect today — the field is purely metadata
    # for downstream tooling (future linters, doc renderers, and the
    # ``s0ma deferred-surface`` companion that reports a nerve's
    # declared exception envelope alongside its deferred status).
    # The IR and emitted ``metadata={}`` dict carry the list under
    # ``"expected_exceptions"``; legacy nerves with no field carry no
    # new IR surface (the key is omitted).
    expected_exceptions: tuple[str, ...] = ()

    # POST-12f (0.16.0): stub-marker annotation. When set to a
    # non-empty string, marks the nerve body as a deferred stub
    # awaiting fill — the string carries the reason ("waiting on
    # Phase 3 spec finalisation", "needs reviewer signoff", etc.).
    # ``s0ma check --report-deferred`` (and the standalone
    # ``s0ma deferred-surface`` subcommand) enumerate every deferred
    # declaration with its reason so authors can see the project's
    # stub surface at a glance. No build-blocking semantics — the
    # nerve body still emits and the registered component still
    # works; the field is informational metadata only. The IR and
    # emitted ``metadata={}`` dict carry the value under
    # ``"deferred"``; legacy nerves with no field carry no new IR
    # surface (the key is omitted).
    deferred: str | None = None

    # POST-12d (0.16.0): duck-typed-coupling surface. Each entry
    # declares ``(contract, param)`` — the nerve body reads
    # ``<param>["<key>"]`` instead of ``<param>.<key>``, and the
    # contract relationship was historically invisible because the
    # access shape is dict-key indirection rather than attribute
    # access. ``contract`` must resolve to a known cell or
    # ``uses:`` target (validator enforces — see
    # ``CONSUMES_VIA_DICT_INVALID``); ``param`` must be a parameter
    # on the nerve body's outer function. The validator wires the
    # appropriate dependency edge so the registry's introspection
    # surface includes the dict-keyed coupling. Pure metadata at
    # codegen time — the field rides through the IR and emitted
    # ``metadata={}`` dict but does not change body emission.
    consumes_via_dict: tuple[ConsumesViaDictEntry, ...] = ()

    # M18 (feedback 5–6): structural attribute claims this nerve produces.
    # Each entry is a ``<namespace>:<attribute>`` string such as
    # ``landmark:header``, ``route:GET /self``, or ``css_class:btn-primary``.
    # Purely descriptive without an ``[tool.s0ma.attribute_budgets]`` table;
    # when a budget is configured for ``<namespace>``, the validator
    # enforces that budget across the project (see plan M18).
    declares_attributes: tuple[str, ...] = ()

    # DSL-M1 (0.8.0): authored per-declaration ``metadata:`` map
    # (ADR-011 §(a), design rule L-1). An ordered tuple of
    # ``(key, value)`` pairs — pairs rather than a dict so duplicate
    # keys survive to the semantic validator (``METADATA_INVALID_KEY``)
    # and authored order is preserved end-to-end (IR object key order,
    # emitted dict literal order, runtime ``ComponentSpec.metadata``
    # insertion order). Values are the L-1 shape set
    # (:data:`MetadataValue`); entries the parser could not represent
    # carry a :data:`METADATA_INVALID_VALUE_MARKER`-prefixed string for
    # the validator to reject (``METADATA_INVALID_VALUE``). The language
    # validates SHAPE only and never interprets values (P-2) — the map
    # flows verbatim: parser → AST → IR ``fields.metadata`` → emitted
    # ``@component(metadata={...})`` merge (authored items appended
    # after the emitter-written registration keys) → runtime
    # ``ComponentSpec.metadata``. Reserved-key collisions
    # (``METADATA_RESERVED_KEY``) are rejected at validation against
    # ``s0ma_dsl.ir.schema.RESERVED_COMPONENT_METADATA_KEYS``.
    metadata: tuple[tuple[str, MetadataValue], ...] = ()

    # DSL-M2 (0.8.0): external test-evidence credit (ADR-011 (e),
    # design rule L-5). A tuple of free-form strings naming the
    # out-of-DSL suites (or rationale prose) that cover this
    # declaration. Authored-opaque: the language validates SHAPE only
    # (non-empty list of non-empty strings, COVERED_BY_EMPTY otherwise
    # - an authored-but-empty list rides as one empty-string marker)
    # and never resolves the strings. Release-mode
    # MISSING_TEST_COVERAGE is satisfied by EITHER in-language tests:
    # coverage OR a non-empty covered_by:; the field rides the IR
    # (fields.covered_by) and the emitted metadata dict under the
    # reserved covered_by key so doc-refs render it from the registry
    # snapshot.
    covered_by: tuple[str, ...] = ()

    # DSL-M1 (0.8.0): optional public serving name (ADR-011 §(b),
    # design rule L-2). The declaration identifier remains the
    # registry/module symbol; ``serves_as`` carries the name the
    # component is served under (an MCP tool/prompt name, a public API
    # alias, ...). Identifier-shaped only (``SERVES_AS_INVALID``);
    # unique per module and per project build (``SERVES_AS_COLLISION``,
    # one flat namespace across all declarations carrying the field).
    # Lands in the IR (``fields.serves_as``), in the emitted metadata
    # dict under the reserved ``serves_as`` key, and the emitter stamps
    # the emitted callable's ``__name__``/``__qualname__`` with the
    # served name one blank line after the decorated def
    # (decorate-then-stamp: ``@component`` runs at def time, so
    # ``ComponentSpec`` keeps the declaration identifier and only the
    # callable's introspection identity carries the served name —
    # closing the F-M4-2 schema-title leak at the artifact level).
    serves_as: str | None = None

    # F3 (feedback 5–6 follow-up): explicit page-composer marker. A nerve
    # marked ``is_page_composer: true`` is a scope root for the
    # ``exactly_one_per_page`` shape of ``[tool.s0ma.attribute_budgets]``.
    # The validator walks the ``uses:`` graph from each marked nerve's
    # owning module to compute the reachable set; the budget enforces
    # exactly-one occurrence of every governed ``<namespace>:<attribute>``
    # within that set. Default ``False`` keeps existing nerves unchanged.
    # If a project configures an ``exactly_one_per_page`` budget but no
    # nerve carries the marker, the resolver emits the
    # ``NO_PAGE_COMPOSER_DECLARED`` error (every mode) — silent no-op is
    # explicitly forbidden by the principle "no silent failures."
    is_page_composer: bool = False

    # Body text in canonical (dedented) form — Python-ready.
    # F1 (feedback 5–6 follow-up): bodies are dedented exactly once at
    # parse time by ``parser.body_extractor.extract_body``. Every
    # downstream consumer (validator, codegen, IR, source map, doc
    # subsystem) reads this canonical value directly. Calling
    # ``textwrap.dedent`` or any hand-rolled dedent on this field is a
    # bug — the body is already column-0.
    body: str | None = None

    # Raw body text exactly as it appeared in the .s0ma source, with
    # the source's leading indentation preserved. Diagnostics-only —
    # do not feed into ``ast.parse`` or codegen. ``body`` is the
    # production form. ``None`` whenever ``body`` is ``None``.
    raw_body: str | None = None

    semantic_states: SemanticStateMap = ()

    location: SourceLocation | None = None


@component(
    name="S0maDSL_CellDecl",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a cell declaration — a structural artifact (model, constant, config, enum, "
        "exception, or type)."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class CellDecl:
    """Cell declaration — a structural artifact that does not perform system logic.

    Body can be a class definition, constant assignment, or type statement
    depending on ``kind``.

    M12 (feedback 5–6): CONSTANT cells may use ``content: @file("path")``
    instead of an inline ``--- ... ---`` body. When the embed directive is
    used, ``body`` is ``None`` and the four ``embedded_file_*`` fields are
    populated by the parser at parse time. The codegen synthesises the
    ``<NAME> = <literal>`` assignment from ``embedded_content``; the
    manifest records ``embedded_file_path`` + ``embedded_file_hash`` under
    ``external_content_files``; the source map records the embedded file
    as the canonical origin of the cell's body.
    """

    name: str
    layer: Layer
    kind: Kind
    visibility: Visibility
    intent: str
    schema: str

    # Optional fields
    invariants: str | None = None
    version: str | None = None
    tags: tuple[str, ...] = ()

    # Body text in canonical (dedented) form — Python-ready (F1).
    # See :class:`NerveDecl` for the parse-time dedenting invariant.
    body: str | None = None

    # Raw body text with the source's original indentation preserved
    # (diagnostics-only). See :class:`NerveDecl` for the contract.
    raw_body: str | None = None

    # M12: ``content: @file("path")`` embed directive (CONSTANT cells only).
    # All four fields are populated together or all None.
    embedded_file_path: str | None = None
    """Original ``@file("...")`` argument as written in the .s0ma source —
    relative to the .s0ma file's directory unless absolute. Recorded in
    ``build.s0ma.json`` under ``external_content_files`` so consumers see
    the path the author wrote, not the absolute resolution."""

    embedded_file_resolved: str | None = None
    """Absolute resolved filesystem path to the embedded file. Used by
    the source map and cache-invalidation hash to identify the source."""

    embedded_content: str | None = None
    """The full file contents, read as UTF-8 text at parse time. Emitted
    verbatim into the generated Python via ``r\"\"\"...\"\"\"`` (when safe)
    or ``repr()`` (when ``\"\"\"`` appears in content)."""

    embedded_file_hash: str | None = None
    """``sha256:<hex>`` of ``embedded_content``. Recorded in the build
    manifest and folded into the cache invalidation hash so editing the
    embedded file invalidates the consuming module's cache."""

    # POST-2 (0.15.0): cells can declare a high-level role via
    # ``category: capability | behaviour``. The field is optional — legacy
    # cells parse with ``category=None`` and remain unchanged. When set,
    # the value is round-tripped through the IR and surfaced in
    # ``s0ma inspect`` so downstream consumers (fr3d's MS 19 ConfigDiff
    # classifier in particular) can derive event classification from the
    # registry instead of a static rule table.
    category: str | None = None
    """``"capability"`` or ``"behaviour"`` when set; ``None`` otherwise."""

    # POST-12f (0.16.0): stub-marker annotation. See
    # :class:`NerveDecl.deferred` for the contract — cells use the
    # same field shape so MODEL/CONFIG/EXCEPTION cells whose body is
    # a placeholder ``pass`` can surface in the deferred-surface
    # report alongside stub nerves and ganglia.
    deferred: str | None = None

    # POST-12c (0.16.0): machine-readable invariant declarations
    # for MODEL cells. Each entry is a string carrying a small
    # assertion expression authored against the dataclass's fields
    # (``"len(latency_samples) <= 100"``, ``"0.0 <= ratio <= 1.0"``,
    # ...). The parser/validator syntax-checks every entry as a
    # Python boolean expression via ``ast.parse(expr, mode="eval")``;
    # a syntax-invalid entry raises ``INVALID_DATACLASS_INVARIANT``
    # in every strictness mode. The invariants are *not* runtime-
    # evaluated by s0ma — they are pure metadata for downstream
    # introspection (a future linter, doc renderer, or runtime
    # contract-enforcer might consume them). The field is meaningful
    # only on MODEL cells; declaring ``dataclass_invariants:`` on a
    # non-MODEL cell raises ``PARSE_ERROR``. Inline
    # (``dataclass_invariants: ["len(x) <= 10"]``) and block-list
    # (``dataclass_invariants:\n      - "..."``) forms are both
    # accepted. Empty tuple = no invariants declared; legacy MODEL
    # cells carry no new IR surface.
    dataclass_invariants: tuple[str, ...] = ()

    # POST-12b (0.16.0): magic-string placeholders declared by a
    # CONSTANT cell whose content is embedded via ``content: @file(...)``.
    # The field carries the placeholder identifiers an embedded
    # template asserts it contains (e.g. ``__SYSTEM_NAME__``,
    # ``__GRAPH_DATA_JSON__``) so a downstream template renderer can
    # substitute them at runtime. Each entry matches the regex
    # ``__[A-Z][A-Z0-9_]*__`` (uppercase + underscore between dunders).
    # The validator cross-checks at check time:
    #
    # * Every declared placeholder MUST appear in the file's content
    #   (otherwise ``PLACEHOLDER_NOT_FOUND``, error in every mode).
    # * Any placeholder-shaped string present in the file but NOT
    #   declared fires ``UNDECLARED_PLACEHOLDER`` (warning in
    #   dev/migration, error in strict/release).
    #
    # The field is only meaningful when ``kind == Kind.CONSTANT`` and
    # ``embedded_file_path is not None`` (i.e. the cell uses
    # ``content: @file(...)``). The parser rejects ``placeholders:``
    # on any other cell shape with a ``PARSE_ERROR`` so the field's
    # contract stays tied to the embed directive. Inline and block
    # list forms (per PRE-7) are both accepted.
    placeholders: tuple[str, ...] = ()

    # DSL-M1 (0.8.0): authored per-declaration ``metadata:`` map —
    # see :class:`NerveDecl.metadata` for the full contract (ordered
    # ``(key, value)`` pairs, L-1 shape set, shape-only validation,
    # parser → AST → IR → emitted-dict merge → runtime flow). Cells
    # use the same field shape; the emitted merge lands in the
    # class-cell ``@component(metadata={...})`` dict or the
    # CONSTANT/TYPE ``register_constant``/``register_type``
    # ``metadata=`` dict, depending on ``kind``.
    metadata: tuple[tuple[str, MetadataValue], ...] = ()

    # DSL-M2 (0.8.0): external test-evidence credit (ADR-011 (e),
    # design rule L-5). A tuple of free-form strings naming the
    # out-of-DSL suites (or rationale prose) that cover this
    # declaration. Authored-opaque: the language validates SHAPE only
    # (non-empty list of non-empty strings, COVERED_BY_EMPTY otherwise
    # - an authored-but-empty list rides as one empty-string marker)
    # and never resolves the strings. Release-mode
    # MISSING_TEST_COVERAGE is satisfied by EITHER in-language tests:
    # coverage OR a non-empty covered_by:; the field rides the IR
    # (fields.covered_by) and the emitted metadata dict under the
    # reserved covered_by key so doc-refs render it from the registry
    # snapshot.
    covered_by: tuple[str, ...] = ()

    semantic_states: SemanticStateMap = ()

    location: SourceLocation | None = None


@component(
    name="S0maDSL_GanglionDecl",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a ganglion declaration — an evaluator that observes nerves and assesses "
        "their behaviour."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class GanglionDecl:
    """Ganglion declaration — receives signals from nerves and evaluates them.

    ``observes`` patterns are resolved against the registry namespace at
    project-level resolution time.
    """

    name: str
    layer: Layer
    visibility: Visibility
    intent: str
    observes: tuple[str, ...]
    scope: EvaluatesAt
    priors: str
    on_anomaly: str
    # What the ganglion must never do, however it is called and whatever
    # happens while it runs. Required by the field table; ``none`` and
    # ``pending`` project to the empty string here, and the tagged state
    # is in ``semantic_states``.
    forbids: str = ""

    # Optional fields
    depends_on: tuple[InlineAxon, ...] = ()
    tags: tuple[str, ...] = ()

    # Body text in canonical (dedented) form — Python-ready (F1).
    # See :class:`NerveDecl` for the parse-time dedenting invariant.
    body: str | None = None

    # Raw body text with original .s0ma indentation (diagnostics-only).
    raw_body: str | None = None

    # POST-12f (0.16.0): stub-marker annotation. See
    # :class:`NerveDecl.deferred` for the contract — ganglia use the
    # same field shape so an evaluator whose ``on_anomaly`` body is
    # a placeholder ``pass`` can surface in the deferred-surface
    # report alongside stub nerves and cells.
    deferred: str | None = None

    # DSL-M1 (0.8.0): authored per-declaration ``metadata:`` map —
    # see :class:`NerveDecl.metadata` for the full contract. Ganglia
    # use the same field shape; the emitted merge lands in the
    # evaluator's ``@component(metadata={...})`` dict after the
    # emitter-written keys (visibility/scope/observes/priors/...).
    metadata: tuple[tuple[str, MetadataValue], ...] = ()

    # DSL-M2 (0.8.0): external test-evidence credit (ADR-011 (e),
    # design rule L-5). A tuple of free-form strings naming the
    # out-of-DSL suites (or rationale prose) that cover this
    # declaration. Authored-opaque: the language validates SHAPE only
    # (non-empty list of non-empty strings, COVERED_BY_EMPTY otherwise
    # - an authored-but-empty list rides as one empty-string marker)
    # and never resolves the strings. Release-mode
    # MISSING_TEST_COVERAGE is satisfied by EITHER in-language tests:
    # coverage OR a non-empty covered_by:; the field rides the IR
    # (fields.covered_by) and the emitted metadata dict under the
    # reserved covered_by key so doc-refs render it from the registry
    # snapshot.
    covered_by: tuple[str, ...] = ()

    semantic_states: SemanticStateMap = ()

    location: SourceLocation | None = None


@component(
    name="S0maDSL_TestDecl",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a test declaration — a first-class verification artifact that registers "
        "which components it validates."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class TestDecl:
    """Test declaration — a first-class structural test artifact.

    ``tests`` entries reference component names resolved against the
    registry namespace.
    """

    name: str
    layer: Layer
    intent: str
    tests: tuple[str, ...]

    # Optional fields
    expects: str | None = None
    depends_on: tuple[InlineAxon, ...] = ()
    tags: tuple[str, ...] = ()

    # POST-3b (0.15.0): a list of nerve names whose public ``provides:``
    # surface this test mocks. The validator cross-checks that any
    # mock-shape dict literal in the test body exposes keys that match
    # the named nerve's ``provides:`` (flat or structured). Targets are
    # resolved against ``uses:`` so cross-module mocks work the same way
    # as cross-module ``tests:`` targets. The field is purely
    # descriptive on its own; the cross-check fires
    # ``MOCK_KEY_MISMATCH`` (warning in dev/migration, error in
    # strict/release) when a mock dict's keys drift from the target's
    # provides. An unknown target name resolves through the existing
    # ``DOES_NOT_EXIST`` path (re-used; not a new code). Inline and
    # block list forms (per PRE-7) are both accepted.
    mocks: tuple[str, ...] = ()

    # Body text in canonical (dedented) form — Python-ready (F1).
    # See :class:`NerveDecl` for the parse-time dedenting invariant.
    body: str | None = None

    # Raw body text with original .s0ma indentation (diagnostics-only).
    raw_body: str | None = None

    semantic_states: SemanticStateMap = ()

    location: SourceLocation | None = None


@component(
    name="S0maDSL_HelperDecl",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a helper declaration — a module-private function that is introspectable "
        "via s0ma inspect but not registered as a component."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class HelperDecl:
    """Helper declaration — a module-private function (M13, feedback 5–6).

    Helpers live at module scope but are *not* registered as components.
    They have no ``kind`` and no ``visibility`` field: access control is
    governed by the M13 rule — intra-module access is unconstrained;
    cross-module access is allowed only from modules that contain at
    least one ``test`` declaration; production cross-module access
    raises ``HELPER_PRIVATE_TO_MODULE``.

    Codegen emits a helper as a plain module-scope ``def`` (or ``class``,
    per POST-4a, 0.15.0) with no ``register_*()`` call. The helper still
    appears in the IR's ``helpers`` array so ``s0ma inspect`` can list it
    under a separate ``[helpers]`` section. The "machines sense their own
    components" principle is preserved: helpers are introspectable, just
    not in the component graph.

    POST-4a (0.15.0): helper bodies may be class definitions, not just
    function definitions. ``body_kind`` records ``"function"`` or
    ``"class"`` so codegen and downstream consumers can branch without
    re-parsing the body. Class-bodied helpers retire the legacy
    ``cell kind: MODEL visibility: INTERNAL`` workaround that previously
    routed module-private classes through the registry.

    POST-4b (0.15.0): helpers may be declared via an ``@inline``
    shorthand inside the module header's ``helpers:`` list, with no
    separate ``---`` block. ``inline`` records whether the helper was
    declared inline (``True``) or via the block form (``False``).
    Inline helpers must use ``body_kind == "function"`` — the shorthand
    does not accept class bodies.
    """

    name: str
    layer: Layer
    intent: str

    # Optional fields
    tags: tuple[str, ...] = ()

    # Body text in canonical (dedented) form — Python-ready (F1).
    # Required for HelperDecl by the parser, but typed as Optional to share
    # the body-extraction code path with nerves/cells/etc. See
    # :class:`NerveDecl` for the parse-time dedenting invariant.
    body: str | None = None

    # Raw body text with original .s0ma indentation (diagnostics-only).
    raw_body: str | None = None

    # POST-4a (0.15.0): ``"function"`` (default) or ``"class"`` — records
    # the structural shape of the body so codegen can emit the right
    # construct without re-parsing the body. Inline helpers (POST-4b)
    # are always ``"function"``.
    body_kind: str = "function"

    # POST-4b (0.15.0): True when the helper was declared via the
    # ``@inline`` shorthand inside a module header's ``helpers:`` list;
    # False when declared via the block form (``helper <name> :: <layer>``
    # ... ``---`` ... body). Inline helpers always carry
    # ``body_kind == "function"``.
    inline: bool = False

    semantic_states: SemanticStateMap = ()

    location: SourceLocation | None = None


@component(
    name="S0maDSL_IntegrationDecl",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for an integration declaration — a first-class external-system adapter that "
        "auto-emits four module-scoped helper functions."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IntegrationDecl:
    """``integration`` declaration — a first-class external-system adapter (POST-5, 0.16.0).

    Promoted from the D-15 IntegrationManifest pattern to a first-class
    declaration kind that auto-emits four module-scoped helper functions
    so two integration modules can declare ``get_factory`` /
    ``get_manifest`` / ``smoke_test_primary`` / ``get_smoke_test``
    without registry collisions. The four helpers leverage the
    pre-Phase-2 ``module_scoped`` flag on ``ComponentSpec`` (s0ma-core
    0.3.0) so that the bare helper names live behind module-qualified
    registry keys and only ever collide intra-module.

    The integration is always INFRASTRUCTURE-layered — the validator
    enforces this with ``LAYER_MISMATCH``. The declaration is metadata
    plus codegen affordances: the ``factory:`` and
    ``smoke_test_primary:`` fields name nerves declared in the same
    module (the validator cross-checks that the factory is a SERVICE
    nerve via ``INTEGRATION_FACTORY_NOT_SERVICE``; the smoke-test
    target merely has to exist via ``INTEGRATION_SMOKE_TEST_NOT_FOUND``).

    ``manifest:`` carries the structured map historically encoded by the
    IntegrationManifest dataclass — ``provides:`` / ``required_env:`` /
    ``requires_oauth:`` are the canonical keys, but the validator
    accepts arbitrary additional keys (a basic shape check; no
    semantic interpretation). The map round-trips through the IR and
    seeds the emitted ``get_manifest()`` return value verbatim.

    The optional ``body`` slot is allowed but typically empty — the
    integration's smoke-test function lives in the same module as a
    separate nerve declaration. The integration declaration itself is
    metadata + auto-emitted helpers.

    The existing IntegrationManifest pattern (Phase 1 / Phase 3
    consumers) continues to work unchanged — the new ``integration``
    declaration kind is opt-in, not a forced migration.
    """

    name: str
    layer: Layer
    version: str
    intent: str
    factory: str
    """Name of a SERVICE nerve declared in this module."""

    smoke_test_primary: str
    """Name of a nerve declared in this module (or imported via ``uses:``)."""

    manifest: dict[str, Any]
    """Manifest dict literal — the structured payload that
    ``get_manifest()`` returns. Keys are arbitrary strings; values are
    ``str | int | float | bool | list | dict``. Round-tripped through
    the IR verbatim."""

    # Optional fields (mirror the standard declaration shape)
    requires: tuple[RequiresEntry, ...] = ()
    uses: tuple[UsesEntry, ...] = ()
    raises: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    # Optional body. Most integration declarations leave this None; the
    # smoke-test function is declared as a separate nerve in the same
    # module. The body slot exists so authors *can* attach an inline
    # adapter helper if the integration is small enough to justify it.
    body: str | None = None
    raw_body: str | None = None

    semantic_states: SemanticStateMap = ()

    location: SourceLocation | None = None


@component(
    name="S0maDSL_StandaloneAxonDecl",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a standalone axon declaration — an explicit cross-module authored "
        "dependency between two components."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class StandaloneAxonDecl:
    """Standalone axon declaration — an explicit cross-module dependency.

    Source must exist in the current module; target must be a cross-module
    reference (intra-module uses inline ``depends_on`` instead).
    Relation must be an authored type (never RAISES or TYPE_USES).
    """

    source: str
    target: str
    relation: Relation
    intent: str
    carries: str
    coupling: Coupling

    semantic_states: SemanticStateMap = ()

    location: SourceLocation | None = None


# ---------------------------------------------------------------------------
# Root node
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Documentation subsystem expression AST (M2)
#
# Two narrow expression grammars back these nodes:
#   - Template expression grammar — supports entity references, field access,
#     filter predicates (equality, membership, boolean composition), ordering,
#     grouping, and iteration. Used in doc-ref covers/sections and in the
#     ``{{...}}`` tokens inside doc-guide prose.
#   - Assert expression grammar — a deliberately narrower grammar: entity
#     field access, ``==`` / ``!=``, ``in``, and boolean composition. No
#     iteration, no ordering, no grouping. Used in doc-guide ``asserts:``.
#
# These grammars are the structural enforcement of design P3 — no
# unverifiable claims. Any construct outside them is a parse error.
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_EntityRefAst",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for an entity reference (e.g. nerve::X or nerve::X.intent) inside a doc "
        "declaration or template expression."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class EntityRefAst:
    """A typed reference to a registered entity, optionally with a field path.

    Examples:
      - ``nerve::greet`` → kind=``"nerve"``, name=``"greet"``, field_path=()
      - ``nerve::greet.intent`` → field_path=("intent",)
      - ``cell::Message.schema.fields`` → field_path=("schema", "fields")
    """

    kind: str
    """Entity kind: ``nerve``, ``cell``, ``ganglion``, ``module``, ``example``, ``test``."""

    name: str
    """Entity name (the identifier after ``::``)."""

    field_path: tuple[str, ...] = ()
    """Optional dotted field-access chain, e.g. ``("expects", "schema")``."""

    raw: str = ""
    """Original source text of the reference, preserved for diagnostics/debugging."""

    location: SourceLocation | None = None


@component(
    name="S0maDSL_ComparisonPredicate",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Predicate AST node for a single binary comparison inside a filter or assert expression."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class ComparisonPredicate:
    """A binary comparison inside a filter or assert expression.

    The *lhs* is a field-access chain relative to the enclosing iteration
    context (in filters) or an entity reference (in asserts). The operator
    is one of ``==``, ``!=``, or ``in``. The *rhs* is a literal value or
    tuple of literal values (for the ``in`` operator).
    """

    lhs: EntityRefAst | tuple[str, ...]
    """Left-hand side. For asserts: an :class:`EntityRefAst` with a non-empty
    ``field_path``. For filters: a bare field-path tuple (no entity ref)."""

    operator: str
    """One of ``"=="``, ``"!="``, ``"in"``."""

    rhs: str | tuple[str, ...]
    """Right-hand side literal. A single string for ``==``/``!=``; a tuple
    of strings for ``in``."""

    location: SourceLocation | None = None


@component(
    name="S0maDSL_BooleanPredicate",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Predicate AST node for boolean composition (and/or/not) of filter or assert predicates."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class BooleanPredicate:
    """Boolean composition node.

    ``operator`` is one of ``"and"``, ``"or"``, or ``"not"``. ``operands``
    holds the sub-predicates; ``"not"`` always has exactly one operand.
    """

    operator: str
    operands: tuple[ComparisonPredicate | BooleanPredicate, ...]
    location: SourceLocation | None = None


@component(
    name="S0maDSL_FilterExprAst",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a template filter expression, selecting registry entities of a given kind "
        "with optional predicate, ordering, and grouping."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class FilterExprAst:
    """A template filter expression.

    Shape: ``<kind> [where <predicate>] [ordered_by <fields>] [group_by <field>]``.

    Used in a doc-ref ``covers:`` entry and (indirectly) as the collection
    side of an iteration. The bare ``kind`` selects every registered entity
    of that kind; the optional ``predicate`` narrows that set.
    """

    kind: str
    """Entity kind (e.g. ``nerve``, ``cell``). Accepts both singular and
    plural surface forms (``nerve`` / ``nerves``), normalised to singular."""

    predicate: ComparisonPredicate | BooleanPredicate | None = None
    """Optional ``where`` clause predicate."""

    ordered_by: tuple[str, ...] = ()
    """Optional list of field names to order by."""

    group_by: str | None = None
    """Optional field name to group by."""

    raw: str = ""
    """Original source text, preserved for diagnostics/debugging."""

    location: SourceLocation | None = None


@component(
    name="S0maDSL_IterationAst",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a template iteration (for <var> in <collection>) with optional ordering "
        "and grouping directives."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class IterationAst:
    """A template iteration construct.

    Shape: ``for <var> in <collection> [ordered_by <fields>] [group_by <field>]``.

    ``collection`` is either a filter expression (``nerves where ...``) or a
    direct entity reference (``module::chat``).
    """

    var: str
    collection: FilterExprAst | EntityRefAst
    ordered_by: tuple[str, ...] = ()
    group_by: str | None = None
    raw: str = ""
    location: SourceLocation | None = None


@component(
    name="S0maDSL_SectionAst",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a doc-ref sections entry — either a simple field reference or a template "
        "iteration."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class SectionAst:
    """A single entry in a doc-ref ``sections:`` list.

    In v1 a section is either:

    - a bare field reference (e.g. ``intent``) — renders that field of the
      covered entities, or
    - an iteration (``for <var> in <collection>``) — iterates and renders.

    Exactly one of ``field_name`` or ``iteration`` is populated.
    """

    field_name: str | None = None
    iteration: IterationAst | None = None
    raw: str = ""
    location: SourceLocation | None = None


@component(
    name="S0maDSL_AssertComparison",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent="AST node for a single entity-level comparison inside a doc-guide asserts expression.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class AssertComparison:
    """A single comparison inside an assert expression.

    The *lhs* is always an :class:`EntityRefAst` with a non-empty
    ``field_path`` (e.g. ``nerve::greet.visibility``). The operator is
    one of ``==``, ``!=``, or ``in``. The *rhs* is a literal value or a
    tuple of literal values (for ``in``).
    """

    lhs: EntityRefAst
    operator: str
    rhs: str | tuple[str, ...]
    location: SourceLocation | None = None


@component(
    name="S0maDSL_AssertBoolean",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for boolean composition (and/or/not) of assert comparisons in a doc-guide "
        "asserts expression."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class AssertBoolean:
    """Boolean composition of assert comparisons.

    ``operator`` is one of ``"and"``, ``"or"``, ``"not"``. ``operands`` holds
    the sub-asserts; ``"not"`` always carries exactly one operand.
    """

    operator: str
    operands: tuple[AssertComparison | AssertBoolean, ...]
    location: SourceLocation | None = None


# ---------------------------------------------------------------------------
# Documentation subsystem prose body tokens (M3)
#
# A ``doc-guide`` prose body is tokenised into an ordered sequence of
# :class:`TextChunk`, :class:`ReferenceToken`, and :class:`ExampleEmbedToken`
# nodes. The tokenisation preserves the original source exactly — the
# invariant ``"".join(t.raw for t in tokens) == prose_body`` holds for every
# successfully parsed guide.
#
# References (``{{nerve::X}}``, ``{{cell::Y.field}}``) are classified as
# :class:`ReferenceToken`; the narrower ``{{example::X}}`` form is
# classified as :class:`ExampleEmbedToken` so renderers can embed the
# example body inline. Both carry the same underlying
# :class:`EntityRefAst` and differ only in which rendering strategy the
# emitter applies.
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_TextChunk",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Prose token representing a run of plain text inside a doc-guide body between reference "
        "tokens."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class TextChunk:
    """A run of plain prose text between reference tokens.

    ``raw`` is the original source text exactly as it appeared in the
    ``.s0ma`` file, including whitespace and newlines. The prose-parser
    guarantees that concatenating every token's ``raw`` reproduces the
    original body byte-for-byte.
    """

    raw: str
    location: SourceLocation | None = None


@component(
    name="S0maDSL_ReferenceToken",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent="Prose token representing an entity reference inside {{...}} in a doc-guide body.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class ReferenceToken:
    """A ``{{entity::name[.field]}}`` reference inside a doc-guide body.

    The ``entity_ref`` holds the parsed :class:`EntityRefAst`; ``raw`` is
    the original ``{{...}}`` source text (braces included) for round-trip
    preservation.
    """

    entity_ref: EntityRefAst
    raw: str
    location: SourceLocation | None = None


@component(
    name="S0maDSL_ExampleEmbedToken",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Prose token representing an {{example::X}} embed — a pointer to an example whose body "
        "is inlined at render time."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class ExampleEmbedToken:
    """An ``{{example::NAME}}`` embed inside a doc-guide body.

    Structurally identical to :class:`ReferenceToken` but distinguished
    so that renderers can substitute the example's registered Python body
    as a fenced code block rather than a rendered field value.
    """

    entity_ref: EntityRefAst  # kind == "example"
    raw: str
    location: SourceLocation | None = None


ProseToken = TextChunk | ReferenceToken | ExampleEmbedToken
"""Union of prose token types produced by the M3 prose parser."""


# ---------------------------------------------------------------------------
# Documentation subsystem declaration nodes (M1)
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_DocRefDecl",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a doc-ref declaration — a generated reference artifact that iterates over "
        "registry state or a derived source registry."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class DocRefDecl:
    """``doc-ref`` declaration — a generated reference artifact.

    A doc-ref has no ``---`` body. Its output is synthesised by the renderer
    from ``covers`` + ``sections`` expressions evaluated against the registry
    snapshot (M6).

    The ``covers`` field is a discriminated union: a doc-ref either selects
    project entities via filter expressions (``covers: [nerve where ...]``,
    populating :attr:`covers`) or pulls from a derived non-component source
    registry (``covers: { source: error_codes }``, populating
    :attr:`covers_source`). Exactly one of the two is set; the other is
    empty / ``None``. The discriminator is enforced at parse time — see
    ``_build_doc_ref`` in ``s0ma_dsl.parser.s0ma_parser``.
    """

    name: str
    module_location: str
    intent: str
    format: str
    output: str
    covers: tuple[FilterExprAst, ...]
    sections: tuple[SectionAst, ...]

    # G7a (feedback 5–6 cleanup): when the ``covers:`` field uses the
    # ``{ source: <name> }`` form, this carries the source identifier and
    # ``covers`` is the empty tuple. Today the only legal value is
    # ``"error_codes"``; the parser rejects any other value with a
    # ``PARSE_ERROR``. Adding a future source (e.g. ``cli_commands``) is a
    # one-line grammar change plus a new renderer branch.
    covers_source: str | None = None

    tags: tuple[str, ...] = ()
    semantic_states: SemanticStateMap = ()
    location: SourceLocation | None = None


@component(
    name="S0maDSL_DocGuideDecl",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for a doc-guide declaration — a hand-authored guide that may embed examples "
        "and carry self-model assertions."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class DocGuideDecl:
    """``doc-guide`` declaration — a hand-authored guide.

    The prose body (``prose_body``) appears after the ``---`` separator and
    is preserved byte-for-byte. ``prose_tokens`` is the M3 tokenised form:
    a sequence of :class:`TextChunk`, :class:`ReferenceToken`, and
    :class:`ExampleEmbedToken` nodes satisfying the round-trip invariant
    ``"".join(t.raw for t in prose_tokens) == prose_body``.
    """

    name: str
    module_location: str
    intent: str
    format: str
    output: str
    covers: tuple[EntityRefAst, ...]
    asserts: tuple[AssertComparison | AssertBoolean, ...]
    examples: tuple[EntityRefAst, ...]
    prose_body: str
    prose_tokens: tuple[ProseToken, ...] = ()

    tags: tuple[str, ...] = ()
    semantic_states: SemanticStateMap = ()
    location: SourceLocation | None = None


@component(
    name="S0maDSL_ExampleDecl",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "AST node for an example declaration — an executable code sample demonstrating one or "
        "more components."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class ExampleDecl:
    """``example`` declaration — an executable demonstration.

    The python body is validated for syntactic correctness and prohibited
    runtime escape hatches (``exec``/``eval``/``__import__``) but — unlike
    nerve bodies — is not constrained to a single top-level construct
    and is permitted to contain bare ``import`` statements (examples
    legitimately need to demonstrate imports).
    """

    name: str
    module_location: str
    intent: str
    demonstrates: tuple[EntityRefAst, ...]
    runs_in: str
    # Python body in canonical (dedented) form — Python-ready (F1).
    # See :class:`NerveDecl` for the parse-time dedenting invariant.
    python_body: str

    # Raw body text with original .s0ma indentation (diagnostics-only).
    raw_python_body: str | None = None

    tags: tuple[str, ...] = ()
    semantic_states: SemanticStateMap = ()
    location: SourceLocation | None = None


# ---------------------------------------------------------------------------
# Root node
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_S0maModule",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Root AST node representing a fully parsed .s0ma file, containing the module declaration "
        "and all component declarations."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class S0maModule:
    """Root AST node — the complete parsed representation of a ``.s0ma`` file.

    Contains the mandatory module declaration and all top-level component
    declarations in source order.
    """

    module: ModuleDecl
    nerves: tuple[NerveDecl, ...] = ()
    cells: tuple[CellDecl, ...] = ()
    ganglia: tuple[GanglionDecl, ...] = ()
    tests: tuple[TestDecl, ...] = ()
    axons: tuple[StandaloneAxonDecl, ...] = ()
    helpers: tuple[HelperDecl, ...] = ()
    integrations: tuple[IntegrationDecl, ...] = ()
    doc_refs: tuple[DocRefDecl, ...] = ()
    doc_guides: tuple[DocGuideDecl, ...] = ()
    examples: tuple[ExampleDecl, ...] = ()

    @property
    def all_declarations(
        self,
    ) -> tuple[
        NerveDecl
        | CellDecl
        | GanglionDecl
        | TestDecl
        | StandaloneAxonDecl
        | HelperDecl
        | IntegrationDecl
        | DocRefDecl
        | DocGuideDecl
        | ExampleDecl,
        ...,
    ]:
        """All non-module declarations in source order (by start line)."""
        decls: list[
            NerveDecl
            | CellDecl
            | GanglionDecl
            | TestDecl
            | StandaloneAxonDecl
            | HelperDecl
            | IntegrationDecl
            | DocRefDecl
            | DocGuideDecl
            | ExampleDecl
        ] = []
        decls.extend(self.nerves)
        decls.extend(self.cells)
        decls.extend(self.ganglia)
        decls.extend(self.tests)
        decls.extend(self.axons)
        decls.extend(self.helpers)
        decls.extend(self.integrations)
        decls.extend(self.doc_refs)
        decls.extend(self.doc_guides)
        decls.extend(self.examples)
        decls.sort(key=lambda d: (d.location.start_line if d.location else 0))
        return tuple(decls)
