"""Project-level reference resolver for the documentation subsystem.

Implements validation layer 3 of the documentation subsystem (design §8.3):
every entity reference, field access, and filter predicate in a ``doc-ref``,
``doc-guide``, or ``example`` declaration is walked against a project-level
view of the registry namespace and checked for existence, kind correctness,
field reachability, and example registration.

The resolver is deliberately agnostic about *where* the project state comes
from. A :class:`ProjectIndex` can be built from a ``dict[str, S0maModule]``
(parsed ``.s0ma`` sources, which is what the transpiler has in hand) or
from any other source that produces the same shape. At runtime integration
time (M5) the resolver will additionally accept a populated
``RegistrySnapshot``; for M4 the index is built from parsed AST alone.

Diagnostic codes emitted (all ``error`` in every strictness mode, see
``s0ma_dsl.config.SEVERITY_MATRIX``):

- ``UNRESOLVED_REFERENCE`` — the referenced entity does not exist in the
  project.
- ``ENTITY_KIND_MISMATCH`` — a component with the same name exists but is
  registered as a different kind than was requested.
- ``FIELD_NOT_FOUND`` — a field-access chain reaches into a field the
  target entity does not expose.
- ``UNREGISTERED_EXAMPLE`` — an ``{{example::X}}`` embed or
  ``examples:`` list entry does not match any registered example.

PRD references: FR-12, FR-13, §2.3.3 (registry namespace).
Design references: §8.3 reference resolution, §11 doc-subsystem pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.nodes import (
    BooleanPredicate,
    CellDecl,
    ComparisonPredicate,
    DocGuideDecl,
    DocRefDecl,
    EntityRefAst,
    ExampleDecl,
    ExampleEmbedToken,
    FilterExprAst,
    GanglionDecl,
    IterationAst,
    NerveDecl,
    ReferenceToken,
    S0maModule,
    SectionAst,
    SourceLocation,
    TestDecl,
)
from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maResolutionError

__all__ = [
    "ProjectIndex",
    "DocReferenceResolver",
    "build_project_index",
    "materialize_filter",
    "predicate_matches",
]


# ---------------------------------------------------------------------------
# ProjectIndex — a kind-indexed view of every entity in the project
# ---------------------------------------------------------------------------


# Declaration classes that participate as entities that doc references may
# point at. Mapped to the singular kind names used on EntityRefAst.kind
# (M2 normalises plural surface forms to singular strings).
_DECL_KIND: dict[type, str] = {
    NerveDecl: "nerve",
    CellDecl: "cell",
    GanglionDecl: "ganglion",
    TestDecl: "test",
    ExampleDecl: "example",
    # "module" is handled specially — it lives on S0maModule.module.
}

# Set of kind strings the resolver recognises as legal entity-reference kinds.
_KNOWN_KINDS: frozenset[str] = frozenset({
    "nerve", "cell", "ganglion", "test", "example", "module",
})


@component(
    name="S0maDSL_ProjectIndex",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Kind-indexed view of every doc-addressable entity in a parsed s0ma project, used by the "
        "doc reference resolver."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class ProjectIndex:
    """Project-wide index of every entity a doc declaration may reference.

    Entities are keyed by their ``(kind, name)`` pair. ``kind`` uses the
    singular-string form produced by the M2 entity-ref parser. Names are
    bare component names (``greet``), not canonical IDs — doc references
    do not encode a module prefix in v1 because the existing registry
    namespace (spec §4.10.1) is flat.

    The index also records each entity's home ``module_name`` so
    diagnostics can disambiguate when the same name appears in two
    modules (a condition separately flagged as ``NAMESPACE_COLLISION``
    by the existing namespace validator).
    """

    by_kind_and_name: dict[tuple[str, str], _IndexedEntity] = field(default_factory=dict)
    """Maps ``(kind, name)`` to a single indexed entity. Where the same
    ``(kind, name)`` appears in multiple modules, the first occurrence wins
    and subsequent occurrences are recorded in ``duplicates``."""

    duplicates: dict[tuple[str, str], list[_IndexedEntity]] = field(default_factory=dict)
    """Duplicate entities discovered during indexing. Not directly used by
    the resolver (collision detection is already handled upstream) but
    retained so diagnostics can mention them."""

    names_by_kind: dict[str, set[str]] = field(default_factory=dict)
    """Kind → set of names. Used for "did you mean?" diagnostics."""

    def lookup(self, kind: str, name: str) -> _IndexedEntity | None:
        """Look up a single entity by kind and name."""
        return self.by_kind_and_name.get((kind, name))

    def names_in_kind(self, kind: str) -> set[str]:
        """Return every registered name for the given kind (empty set if none)."""
        return self.names_by_kind.get(kind, set())

    def find_in_any_kind(self, name: str) -> list[tuple[str, _IndexedEntity]]:
        """Return every ``(kind, entity)`` pair matching the given name.

        Used by :class:`DocReferenceResolver` to produce
        ``ENTITY_KIND_MISMATCH`` diagnostics of the form
        "did you mean nerve::X?" when the requested kind is wrong.
        """
        out: list[tuple[str, _IndexedEntity]] = []
        for (k, n), ent in self.by_kind_and_name.items():
            if n == name:
                out.append((k, ent))
        return out

    def entities_of_kind(self, kind: str) -> list[_IndexedEntity]:
        """Return every indexed entity of a given kind."""
        return [
            ent
            for (k, _n), ent in self.by_kind_and_name.items()
            if k == kind
        ]

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> ProjectIndex:
        """Build a :class:`ProjectIndex` from a populated s0ma RegistrySnapshot.

        Plan M5 deliverable: post-import integration tests need to validate
        doc references against the runtime registry's view of the world,
        not just the parsed AST. This factory reads the snapshot's
        component / module / doc-subsystem stores and produces the same
        ``(kind, name)`` keying the AST-based path uses.

        The AST-based :func:`build_project_index` remains the primary
        entry point for the transpiler's pre-import pipeline; this method
        is the runtime-side counterpart.
        """
        index = cls()

        def _add(ent: _IndexedEntity) -> None:
            # DSL-M4 (F-M5-2): expose the owning module as an addressable
            # ``module`` field so ``covers: [<kind> where module == X]``
            # filters and ``<kind>::Y.module`` field-access both resolve.
            ent.fields.setdefault("module", ent.module_name)
            key = (ent.kind, ent.name)
            if key in index.by_kind_and_name:
                index.duplicates.setdefault(key, []).append(ent)
            else:
                index.by_kind_and_name[key] = ent
            index.names_by_kind.setdefault(ent.kind, set()).add(ent.name)

        # Modules — every snapshot.modules entry maps name → ModuleMetadata.
        for mod_name, mod_meta in getattr(snapshot, "modules", {}).items():
            fields: dict[str, Any] = {
                "name": mod_name,
                "layer": _enum_to_str(getattr(mod_meta, "layer", "")),
                "version": getattr(mod_meta, "version", ""),
                "intent": getattr(mod_meta, "intent", ""),
                "exports": list(getattr(mod_meta, "exports", []) or []),
                "tags": list(getattr(mod_meta, "tags", []) or []),
            }
            _add(_IndexedEntity(
                kind="module",
                name=mod_name,
                module_name=mod_name,
                decl=mod_meta,
                fields=fields,
            ))

        # Components — bucket by ComponentKind; map onto the doc-resolver
        # singular kind strings.
        kind_map = {
            "SERVICE": "nerve",
            "FUNCTION": "nerve",
            "ADAPTER": "nerve",
            "ORCHESTRATOR": "nerve",
            "MODEL": "cell",
            "ENUM": "cell",
            "EXCEPTION": "cell",
            "CONFIG": "cell",
            "CONSTANT": "cell",
            "TYPE": "cell",
        }
        for spec_name, spec in getattr(snapshot, "components", {}).items():
            spec_kind = _enum_to_str(getattr(spec, "kind", ""))
            kind_str = kind_map.get(spec_kind)
            if kind_str is None:
                continue
            allowed = _FIELDS_BY_KIND.get(kind_str, frozenset())
            fields = {fname: _enum_to_str(getattr(spec, fname, None))
                      for fname in allowed
                      if hasattr(spec, fname)}
            # DSL-M2 (0.8.0, ADR-011 §(e)): ``ComponentSpec`` has no
            # ``covered_by`` attribute for the getattr walk — the claim
            # rides the registered metadata under the reserved
            # ``covered_by`` key (that is what makes doc-ref rendering
            # from the registry snapshot work).
            spec_metadata = getattr(spec, "metadata", None) or {}
            if "covered_by" in spec_metadata:
                fields["covered_by"] = list(spec_metadata["covered_by"])
            module_name = getattr(spec, "module_path", "") or ""
            module_short = module_name.rsplit(".", 1)[-1] if module_name else ""
            _add(_IndexedEntity(
                kind=kind_str,
                name=spec_name,
                module_name=module_short,
                decl=spec,
                fields=fields,
            ))

        # Tests — TestRegistration objects.
        for test_name, test_reg in getattr(snapshot, "test_registrations", {}).items():
            fields = {
                "name": test_name,
                "intent": getattr(test_reg, "intent", ""),
                "tests": list(getattr(test_reg, "validates", []) or []),
            }
            _add(_IndexedEntity(
                kind="test",
                name=test_name,
                module_name="",
                decl=test_reg,
                fields=fields,
            ))

        # Examples — registered via register_example.
        for ex_name, ex_reg in getattr(snapshot, "examples", {}).items():
            fields = {
                "name": ex_name,
                "intent": getattr(ex_reg, "intent", ""),
                "demonstrates": [
                    {"kind": d.kind, "name": d.name, "module": d.module}
                    for d in getattr(ex_reg, "demonstrates", []) or []
                ],
                "runs_in": getattr(ex_reg, "runs_in", ""),
            }
            _add(_IndexedEntity(
                kind="example",
                name=ex_name,
                module_name=getattr(ex_reg, "module", ""),
                decl=ex_reg,
                fields=fields,
            ))

        return index


@dataclass(frozen=True)
class _IndexedEntity:
    """A single entity in the :class:`ProjectIndex`.

    ``decl`` is the AST node (``NerveDecl``, ``CellDecl``, …, or the
    ``ModuleDecl`` for a module entity). ``module_name`` is the name of
    the module the entity lives in (for module entities this equals
    ``decl.name``). ``fields`` is a dict of the declaration's addressable
    field values, resolved at index-build time so the resolver can do
    fast field-access lookups without repeated ``getattr`` scans.
    """

    kind: str
    name: str
    module_name: str
    decl: Any
    fields: dict[str, Any]


# ---------------------------------------------------------------------------
# Field exposure per entity kind
# ---------------------------------------------------------------------------
#
# Doc declarations may reach into an entity's fields with a dotted
# field-access chain (e.g. ``nerve::greet.intent``, ``module::chat.version``).
# The set of addressable fields is deliberately restricted to the
# self-describing metadata fields — not body text, not derived edges.
# Field access into a nested structure is supported only when the nested
# object is itself dict-shaped and the key exists; otherwise ``FIELD_NOT_FOUND``
# fires so the author can be pointed at the correct spelling.

_FIELDS_BY_KIND: dict[str, frozenset[str]] = {
    # DSL-M2 (0.8.0, ADR-011 §(e)): ``covered_by`` is addressable on
    # the three kinds that accept the field, so doc-refs can render
    # the external test-evidence claim.
    #
    # DSL-M4 (0.8.0, F-M5-2): ``module`` — the owning module's name — is
    # addressable on EVERY kind so multi-module projects can render
    # per-module references (``covers: [nerve where module == tools]``).
    # The value is supplied at index-build time from each entity's
    # ``module_name`` (see ``_with_module`` below); it is not pulled off
    # the declaration's own attributes, so it rides every kind uniformly.
    "nerve": frozenset({
        "name", "kind", "visibility", "layer", "intent",
        "expects", "guarantees", "forbids", "evaluates_at",
        "provides", "returns", "raises", "abstract",
        "interface", "latency_ms", "version", "tags",
        "covered_by", "module",
    }),
    "cell": frozenset({
        "name", "kind", "visibility", "layer", "intent",
        "schema", "invariants", "version", "tags",
        "covered_by", "module",
    }),
    "ganglion": frozenset({
        "name", "visibility", "layer", "intent",
        "observes", "scope", "priors", "on_anomaly", "forbids", "tags",
        "covered_by", "module",
    }),
    "test": frozenset({
        "name", "layer", "intent", "tests", "expects", "tags",
        "module",
    }),
    "example": frozenset({
        "name", "intent", "demonstrates", "runs_in", "tags",
        "module",
    }),
    "module": frozenset({
        "name", "layer", "version", "intent", "exports", "tags",
        "module",
    }),
}


def _enum_to_str(value: Any) -> Any:
    """Convert enum values to their ``.value`` for comparison.

    Keeps non-enum values untouched. Applied recursively to tuples so
    ``raises = ("ValidationError", "HTTPError")`` stays a tuple of
    strings.
    """
    if hasattr(value, "value") and not isinstance(value, (str, int, float, bool, tuple, list)):
        return value.value
    if isinstance(value, tuple):
        return tuple(_enum_to_str(v) for v in value)
    if isinstance(value, list):
        return [_enum_to_str(v) for v in value]
    return value


def _extract_fields(decl: Any, allowed: frozenset[str]) -> dict[str, Any]:
    """Pull the addressable fields off a declaration, normalising enums."""
    out: dict[str, Any] = {}
    for fname in allowed:
        if hasattr(decl, fname):
            out[fname] = _enum_to_str(getattr(decl, fname))
    return out


# ---------------------------------------------------------------------------
# ProjectIndex builder
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_build_project_index",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Build a ProjectIndex from a dict of parsed S0maModule ASTs for use by the doc reference "
        "resolver."
    ),
    idempotent=True,
    is_framework=True,
)
def build_project_index(modules: dict[str, S0maModule]) -> ProjectIndex:
    """Construct a :class:`ProjectIndex` from a dict of parsed modules.

    The argument maps module names to their parsed ``S0maModule`` — the
    same shape the cross-module dependency resolver already consumes.
    """
    index = ProjectIndex()

    def _add(ent: _IndexedEntity) -> None:
        # DSL-M4 (F-M5-2): expose the owning module as an addressable
        # ``module`` field so ``covers: [<kind> where module == X]``
        # filters and ``<kind>::Y.module`` field-access both resolve.
        ent.fields.setdefault("module", ent.module_name)
        key = (ent.kind, ent.name)
        if key in index.by_kind_and_name:
            index.duplicates.setdefault(key, []).append(ent)
        else:
            index.by_kind_and_name[key] = ent
        index.names_by_kind.setdefault(ent.kind, set()).add(ent.name)

    for _module_name, s0ma_module in modules.items():
        mod_decl = s0ma_module.module
        # The module itself is addressable as module::<name>.
        _add(_IndexedEntity(
            kind="module",
            name=mod_decl.name,
            module_name=mod_decl.name,
            decl=mod_decl,
            fields=_extract_fields(mod_decl, _FIELDS_BY_KIND["module"]),
        ))

        # Flatten every non-module declaration.
        for decl in s0ma_module.all_declarations:
            decl_kind = _DECL_KIND.get(type(decl))
            if decl_kind is None:
                # Standalone axons and doc declarations are not entity
                # targets. Doc declarations can in principle be referenced
                # as doc-guide::X in a v2 design, but v1 confines entity
                # references to nerve/cell/ganglion/test/example/module.
                continue
            _add(_IndexedEntity(
                kind=decl_kind,
                # decl_kind is None (and skipped above) for name-less
                # decls like StandaloneAxonDecl, so the reached decls
                # always carry a .name.
                name=getattr(decl, "name", ""),
                module_name=mod_decl.name,
                decl=decl,
                fields=_extract_fields(decl, _FIELDS_BY_KIND[decl_kind]),
            ))

    return index


# ---------------------------------------------------------------------------
# DocReferenceResolver
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_DocReferenceResolver",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent=(
        "Walks doc-ref, doc-guide, and example declarations against a project index to validate "
        "every entity reference, field access, and example embed."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class DocReferenceResolver:
    """Project-level resolver for doc-subsystem references (design §8.3).

    Given a :class:`ProjectIndex`, walks the reference surface of each
    doc declaration and collects :class:`S0maResolutionError` diagnostics
    for unresolved references, kind mismatches, missing fields, and
    unregistered example embeds. The resolver does not mutate AST nodes
    and does not resolve assert expressions — that is
    :class:`s0ma_dsl.resolver.assert_evaluator.AssertEvaluator`.
    """

    index: ProjectIndex
    mode: StrictnessMode = StrictnessMode.DEV
    """Active strictness mode. Controls the severity of mode-dependent
    diagnostics (currently :code:`EMPTY_DOC_FILTER`). Defaults to
    :class:`StrictnessMode.DEV` so existing call sites that construct
    a resolver without a mode keep their pre-M7 behaviour."""

    # -----------------------------------------------------------------------
    # Declaration entry points
    # -----------------------------------------------------------------------

    def resolve_doc_ref(
        self,
        decl: DocRefDecl,
        *,
        filename: str = "<unknown>",
    ) -> list[S0maResolutionError]:
        """Walk a ``doc-ref`` declaration. Returns diagnostics."""
        errors: list[S0maResolutionError] = []
        base_loc = decl.location

        # ``covers:`` is a tuple[FilterExprAst, ...].
        for fexpr in decl.covers:
            errors.extend(self._resolve_filter(fexpr, filename, base_loc))

        # ``sections:`` is a tuple[SectionAst, ...]. Each section is either
        # a bare field reference (field_name set) or an iteration. Bare
        # field references apply to every entity in every ``covers:``
        # filter, so we validate the field against every covered kind.
        covered_kinds = tuple(fexpr.kind for fexpr in decl.covers)
        for section in decl.sections:
            errors.extend(
                self._resolve_section(section, covered_kinds, filename, base_loc)
            )

        return errors

    def resolve_doc_guide(
        self,
        decl: DocGuideDecl,
        *,
        filename: str = "<unknown>",
    ) -> list[S0maResolutionError]:
        """Walk a ``doc-guide`` declaration. Returns diagnostics."""
        errors: list[S0maResolutionError] = []
        base_loc = decl.location

        # ``covers:`` is a tuple[EntityRefAst, ...].
        for ref in decl.covers:
            errors.extend(self._resolve_entity_ref(ref, filename, base_loc))

        # ``examples:`` is a tuple[EntityRefAst, ...] — every entry must
        # resolve to a registered example.
        for ref in decl.examples:
            errors.extend(self._resolve_example_ref(ref, filename, base_loc))

        # Prose ``{{...}}`` tokens each carry an EntityRefAst.
        for tok in decl.prose_tokens:
            if isinstance(tok, ExampleEmbedToken):
                errors.extend(self._resolve_example_ref(tok.entity_ref, filename, base_loc))
            elif isinstance(tok, ReferenceToken):
                errors.extend(self._resolve_entity_ref(tok.entity_ref, filename, base_loc))
            # TextChunk tokens are never references — nothing to resolve.

        return errors

    def resolve_example(
        self,
        decl: ExampleDecl,
        *,
        filename: str = "<unknown>",
    ) -> list[S0maResolutionError]:
        """Walk an ``example`` declaration. Returns diagnostics."""
        errors: list[S0maResolutionError] = []
        base_loc = decl.location
        for ref in decl.demonstrates:
            errors.extend(self._resolve_entity_ref(ref, filename, base_loc))
        return errors

    # -----------------------------------------------------------------------
    # Entity-ref resolution
    # -----------------------------------------------------------------------

    def _resolve_entity_ref(
        self,
        ref: EntityRefAst,
        filename: str,
        base_loc: SourceLocation | None,
    ) -> list[S0maResolutionError]:
        """Resolve a single entity reference and optional field path."""
        errors: list[S0maResolutionError] = []

        if ref.kind not in _KNOWN_KINDS:
            # The grammar already rejects unknown kinds, but be defensive:
            # a kind string that sneaks through to the resolver is treated
            # as unresolved.
            errors.append(self._unresolved(ref, filename, base_loc))
            return errors

        ent = self.index.lookup(ref.kind, ref.name)
        if ent is None:
            # Same name registered under a different kind? Produce a
            # targeted "did you mean ...?" diagnostic.
            alt_kinds = [k for k, _ in self.index.find_in_any_kind(ref.name)]
            if alt_kinds:
                errors.append(self._kind_mismatch(ref, alt_kinds, filename, base_loc))
            else:
                errors.append(self._unresolved(ref, filename, base_loc))
            return errors

        # Field path walk.
        if ref.field_path:
            errors.extend(
                self._walk_field_path(ent, ref, ref.field_path, filename, base_loc)
            )
        return errors

    def _resolve_example_ref(
        self,
        ref: EntityRefAst,
        filename: str,
        base_loc: SourceLocation | None,
    ) -> list[S0maResolutionError]:
        """Resolve an ``example::X`` reference with dedicated diagnostic."""
        # Enforce kind=="example" — a non-example ref in examples:/prose
        # is flagged as a kind mismatch.
        if ref.kind != "example":
            # Delegate to the generic walker; it will emit ENTITY_KIND_MISMATCH
            # if an example with the same name exists in a different role,
            # or UNRESOLVED_REFERENCE otherwise.
            return self._resolve_entity_ref(ref, filename, base_loc)

        ent = self.index.lookup("example", ref.name)
        if ent is None:
            return [self._unregistered_example(ref, filename, base_loc)]

        if ref.field_path:
            return self._walk_field_path(ent, ref, ref.field_path, filename, base_loc)
        return []

    # -----------------------------------------------------------------------
    # Filter + section resolution
    # -----------------------------------------------------------------------

    def _resolve_filter(
        self,
        fexpr: FilterExprAst,
        filename: str,
        base_loc: SourceLocation | None,
    ) -> list[S0maResolutionError]:
        """Validate a ``covers:`` filter expression against the project.

        A filter is well-formed iff the kind is recognised and every
        field referenced in its predicate / ordered_by / group_by clause
        exists on that kind. M7 additionally materialises the filter
        and emits :code:`EMPTY_DOC_FILTER` when no entity matches —
        mirroring the :code:`EMPTY_OBSERVES` semantics for ganglia.
        """
        errors: list[S0maResolutionError] = []

        if fexpr.kind not in _KNOWN_KINDS:
            errors.append(S0maResolutionError(
                code="UNRESOLVED_REFERENCE",
                message=f"Filter references unknown entity kind '{fexpr.kind}'.",
                file=filename,
                line=_line(base_loc),
                column=_col(base_loc),
                severity="error",
                remediation=(
                    f"Replace '{fexpr.kind}' with one of: "
                    f"{', '.join(sorted(_KNOWN_KINDS))}."
                ),
                context={"kind": fexpr.kind, "raw": fexpr.raw},
            ))
            return errors

        # Validate predicate field paths.
        if fexpr.predicate is not None:
            errors.extend(
                self._validate_predicate_fields(
                    fexpr.predicate, fexpr.kind, fexpr.raw,
                    filename, base_loc,
                )
            )

        # Validate ordered_by fields.
        for field_name in fexpr.ordered_by:
            if not _field_exists(fexpr.kind, field_name):
                errors.append(self._unknown_filter_field(
                    fexpr.kind, field_name, fexpr.raw,
                    clause="ordered_by", filename=filename, base_loc=base_loc,
                ))

        # Validate group_by field.
        if fexpr.group_by and not _field_exists(fexpr.kind, fexpr.group_by):
            errors.append(self._unknown_filter_field(
                fexpr.kind, fexpr.group_by, fexpr.raw,
                clause="group_by", filename=filename, base_loc=base_loc,
            ))

        # Empty-filter detection (M7 subtask 6). Only run when the
        # filter is structurally sound — emitting EMPTY_DOC_FILTER on
        # top of FIELD_NOT_FOUND would be noise.
        if not errors:
            severity = get_severity("EMPTY_DOC_FILTER", self.mode)
            if severity is not None:
                matched = materialize_filter(fexpr, self.index)
                if not matched:
                    errors.append(S0maResolutionError(
                        code="EMPTY_DOC_FILTER",
                        message=(
                            f"covers: filter '{fexpr.raw or fexpr.kind}' "
                            f"materialises to no entities of kind "
                            f"'{fexpr.kind}'."
                        ),
                        file=filename,
                        line=_line(base_loc),
                        column=_col(base_loc),
                        severity=severity,
                        remediation=(
                            f"Register at least one {fexpr.kind} that "
                            f"satisfies the predicate, or relax the "
                            f"filter so it matches an existing entity."
                        ),
                        context={
                            "kind": fexpr.kind,
                            "raw": fexpr.raw,
                        },
                    ))

        return errors

    def _resolve_section(
        self,
        section: SectionAst,
        covered_kinds: tuple[str, ...],
        filename: str,
        base_loc: SourceLocation | None,
    ) -> list[S0maResolutionError]:
        """Validate a ``sections:`` entry against the doc-ref's covered kinds."""
        errors: list[S0maResolutionError] = []

        if section.field_name is not None:
            # A bare field reference applies to every covered kind; all of
            # them must expose the field.
            for kind in covered_kinds:
                if kind in _KNOWN_KINDS and not _field_exists(kind, section.field_name):
                    errors.append(S0maResolutionError(
                        code="FIELD_NOT_FOUND",
                        message=(
                            f"Section field '{section.field_name}' is not a "
                            f"known field on kind '{kind}'."
                        ),
                        file=filename,
                        line=_line(base_loc),
                        column=_col(base_loc),
                        severity="error",
                        remediation=(
                            f"Use one of {sorted(_FIELDS_BY_KIND[kind])} "
                            f"for section entries of kind '{kind}', or narrow "
                            f"the doc-ref's covers: list to kinds that expose "
                            f"'{section.field_name}'."
                        ),
                        context={
                            "kind": kind,
                            "field": section.field_name,
                            "section_raw": section.raw,
                        },
                    ))
        elif section.iteration is not None:
            # The iteration's collection is a FilterExprAst (or, in future
            # grammar extensions, an EntityRefAst).
            errors.extend(
                self._resolve_iteration(section.iteration, filename, base_loc)
            )
        # If neither field_name nor iteration is set, the parser already
        # rejected the declaration — nothing to do.

        return errors

    def _resolve_iteration(
        self,
        iteration: IterationAst,
        filename: str,
        base_loc: SourceLocation | None,
    ) -> list[S0maResolutionError]:
        """Validate the collection side of an iteration."""
        errors: list[S0maResolutionError] = []
        coll = iteration.collection
        if isinstance(coll, FilterExprAst):
            errors.extend(self._resolve_filter(coll, filename, base_loc))
        elif isinstance(coll, EntityRefAst):
            errors.extend(self._resolve_entity_ref(coll, filename, base_loc))

        # Validate ordered_by / group_by against the inferred kind of
        # the collection. For FilterExprAst we have the kind directly;
        # for EntityRefAst the kind carries through the reference.
        kind: str | None = None
        if isinstance(coll, (FilterExprAst, EntityRefAst)):
            kind = coll.kind

        if kind and kind in _KNOWN_KINDS:
            for field_name in iteration.ordered_by:
                if not _field_exists(kind, field_name):
                    errors.append(self._unknown_filter_field(
                        kind, field_name, iteration.raw,
                        clause="ordered_by",
                        filename=filename, base_loc=base_loc,
                    ))
            if iteration.group_by and not _field_exists(kind, iteration.group_by):
                errors.append(self._unknown_filter_field(
                    kind, iteration.group_by, iteration.raw,
                    clause="group_by",
                    filename=filename, base_loc=base_loc,
                ))

        return errors

    def _validate_predicate_fields(
        self,
        pred: ComparisonPredicate | BooleanPredicate,
        kind: str,
        raw: str,
        filename: str,
        base_loc: SourceLocation | None,
    ) -> list[S0maResolutionError]:
        """Walk a filter predicate and flag unknown field paths."""
        errors: list[S0maResolutionError] = []
        if isinstance(pred, BooleanPredicate):
            for sub in pred.operands:
                errors.extend(
                    self._validate_predicate_fields(sub, kind, raw, filename, base_loc)
                )
            return errors

        # Comparison predicate. lhs in a filter context is a bare
        # tuple[str, ...] (entity context comes from the enclosing filter).
        lhs = pred.lhs
        if isinstance(lhs, tuple):  # noqa: SIM102 — comment on inner branch describes the field-shape check
            # The first segment must be a known field on the kind; deeper
            # segments are not validated against the entity because the
            # resolver does not inspect nested field shapes at this layer.
            if lhs and not _field_exists(kind, lhs[0]):
                errors.append(self._unknown_filter_field(
                    kind, lhs[0], raw,
                    clause="where",
                    filename=filename, base_loc=base_loc,
                ))
        return errors

    # -----------------------------------------------------------------------
    # Field-path walking
    # -----------------------------------------------------------------------

    def _walk_field_path(
        self,
        ent: _IndexedEntity,
        ref: EntityRefAst,
        path: tuple[str, ...],
        filename: str,
        base_loc: SourceLocation | None,
    ) -> list[S0maResolutionError]:
        """Walk a dotted field path and emit FIELD_NOT_FOUND if invalid."""
        if not path:
            return []
        first = path[0]
        if not _field_exists(ent.kind, first):
            known = sorted(_FIELDS_BY_KIND.get(ent.kind, frozenset()))
            return [S0maResolutionError(
                code="FIELD_NOT_FOUND",
                message=(
                    f"Entity {ent.kind}::{ent.name} has no field "
                    f"'{first}' (reference: {ref.raw or first})."
                ),
                file=filename,
                line=_line(ref.location or base_loc),
                column=_col(ref.location or base_loc),
                severity="error",
                remediation=(
                    f"Use one of {known} or remove the field access."
                ),
                context={
                    "kind": ent.kind,
                    "name": ent.name,
                    "field": first,
                    "known_fields": known,
                    "raw": ref.raw,
                },
            )]
        # Deeper segments: only walk if the field value is a dict we
        # understand. For v1 most entity fields are flat strings/tuples/
        # enums, so a second field access is a FIELD_NOT_FOUND.
        current = ent.fields.get(first)
        for segment in path[1:]:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
                continue
            return [S0maResolutionError(
                code="FIELD_NOT_FOUND",
                message=(
                    f"Field path {'.'.join(path)} on {ent.kind}::{ent.name} "
                    f"does not reach a readable field at segment '{segment}'."
                ),
                file=filename,
                line=_line(ref.location or base_loc),
                column=_col(ref.location or base_loc),
                severity="error",
                remediation=(
                    f"Field '{first}' on {ent.kind}::{ent.name} is not a "
                    f"nested structure with key '{segment}'. Reference only "
                    f"top-level fields in v1."
                ),
                context={
                    "kind": ent.kind,
                    "name": ent.name,
                    "field_path": list(path),
                    "failed_at": segment,
                    "raw": ref.raw,
                },
            )]
        return []

    # -----------------------------------------------------------------------
    # Diagnostic constructors
    # -----------------------------------------------------------------------

    def _unresolved(
        self,
        ref: EntityRefAst,
        filename: str,
        base_loc: SourceLocation | None,
    ) -> S0maResolutionError:
        alt_names = sorted(self.index.names_in_kind(ref.kind))
        suggestion = _did_you_mean(ref.name, alt_names)
        hint = f" Did you mean {ref.kind}::{suggestion}?" if suggestion else ""
        return S0maResolutionError(
            code="UNRESOLVED_REFERENCE",
            message=(
                f"Reference {ref.kind}::{ref.name} does not resolve to any "
                f"registered entity."
            ),
            file=filename,
            line=_line(ref.location or base_loc),
            column=_col(ref.location or base_loc),
            severity="error",
            remediation=(
                f"Register a {ref.kind} named '{ref.name}' in one of the "
                f"project's .s0ma modules, or correct the reference.{hint}"
            ),
            context={
                "kind": ref.kind,
                "name": ref.name,
                "raw": ref.raw,
                "known_names": alt_names,
            },
        )

    def _kind_mismatch(
        self,
        ref: EntityRefAst,
        actual_kinds: list[str],
        filename: str,
        base_loc: SourceLocation | None,
    ) -> S0maResolutionError:
        alt = ", ".join(sorted(f"{k}::{ref.name}" for k in actual_kinds))
        return S0maResolutionError(
            code="ENTITY_KIND_MISMATCH",
            message=(
                f"Reference {ref.kind}::{ref.name} has the wrong kind — "
                f"'{ref.name}' exists but is registered as: {alt}."
            ),
            file=filename,
            line=_line(ref.location or base_loc),
            column=_col(ref.location or base_loc),
            severity="error",
            remediation=f"Did you mean {alt}?",
            context={
                "requested_kind": ref.kind,
                "actual_kinds": sorted(actual_kinds),
                "name": ref.name,
                "raw": ref.raw,
            },
        )

    def _unregistered_example(
        self,
        ref: EntityRefAst,
        filename: str,
        base_loc: SourceLocation | None,
    ) -> S0maResolutionError:
        alt_names = sorted(self.index.names_in_kind("example"))
        suggestion = _did_you_mean(ref.name, alt_names)
        hint = f" Did you mean example::{suggestion}?" if suggestion else ""
        return S0maResolutionError(
            code="UNREGISTERED_EXAMPLE",
            message=(
                f"Example embed example::{ref.name} does not match any "
                f"registered example declaration."
            ),
            file=filename,
            line=_line(ref.location or base_loc),
            column=_col(ref.location or base_loc),
            severity="error",
            remediation=(
                f"Declare an `example {ref.name}` in one of the project's "
                f".s0ma modules, or correct the reference.{hint}"
            ),
            context={
                "name": ref.name,
                "raw": ref.raw,
                "known_examples": alt_names,
            },
        )

    def _unknown_filter_field(
        self,
        kind: str,
        field_name: str,
        raw: str,
        *,
        clause: str,
        filename: str,
        base_loc: SourceLocation | None,
    ) -> S0maResolutionError:
        known = sorted(_FIELDS_BY_KIND.get(kind, frozenset()))
        return S0maResolutionError(
            code="FIELD_NOT_FOUND",
            message=(
                f"Filter {clause} clause references field '{field_name}' "
                f"which is not a known field on kind '{kind}'."
            ),
            file=filename,
            line=_line(base_loc),
            column=_col(base_loc),
            severity="error",
            remediation=(
                f"Use one of {known} for {clause} on kind '{kind}', or "
                f"remove the clause."
            ),
            context={
                "kind": kind,
                "field": field_name,
                "clause": clause,
                "raw": raw,
                "known_fields": known,
            },
        )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _field_exists(kind: str, field_name: str) -> bool:
    return field_name in _FIELDS_BY_KIND.get(kind, frozenset())


# ---------------------------------------------------------------------------
# Filter materialisation (M7)
#
# The renderer (codegen/doc_emitter/markdown.py) and the resolver both
# need to evaluate a ``covers:`` filter against the project index — the
# renderer to emit a section per matching entity, the resolver (M7
# subtask 6) to detect filters that materialise to zero entities. The
# implementation lives here so the two callers cannot diverge on
# predicate semantics.
# ---------------------------------------------------------------------------


def _scalar_equal(actual: Any, expected: Any) -> bool:
    """Compare two scalar-ish values stringily, matching predicate semantics."""
    if actual is None and expected is None:
        return True
    if isinstance(actual, (list, tuple)):
        return False  # lists never == scalars in v1
    return str(actual) == str(expected)


def predicate_matches(fields: dict[str, Any], pred: Any) -> bool:
    """Evaluate a structured predicate AST against an entity's fields.

    Booleans short-circuit; ``in`` is set-style on string-equal members.
    Returns False on unrecognised predicate shapes rather than raising —
    upstream validation already flagged them.
    """
    if isinstance(pred, BooleanPredicate):
        if pred.operator == "and":
            return all(predicate_matches(fields, o) for o in pred.operands)
        if pred.operator == "or":
            return any(predicate_matches(fields, o) for o in pred.operands)
        if pred.operator == "not":
            return not predicate_matches(fields, pred.operands[0])
        return False

    if isinstance(pred, ComparisonPredicate):
        lhs = pred.lhs
        lookup_field = (lhs[0] if lhs else "") if isinstance(lhs, tuple) else ""
        actual = _enum_to_str(fields.get(lookup_field))
        rhs = pred.rhs
        if pred.operator == "==":
            return _scalar_equal(actual, rhs)
        if pred.operator == "!=":
            return not _scalar_equal(actual, rhs)
        if pred.operator == "in":
            if isinstance(rhs, tuple):
                return any(_scalar_equal(actual, item) for item in rhs)
            return _scalar_equal(actual, rhs)
        return False

    return False


def materialize_filter(
    fexpr: FilterExprAst, index: ProjectIndex,
) -> list[_IndexedEntity]:
    """Return the entities a ``covers:`` filter selects, in deterministic order.

    Used by the renderer to enumerate matching entities and by the
    resolver to detect ``EMPTY_DOC_FILTER``. Both share semantics so a
    filter that renders to zero entities is exactly the one the
    resolver flags.
    """
    if fexpr.kind not in _KNOWN_KINDS:
        return []
    entities = index.entities_of_kind(fexpr.kind)
    if fexpr.predicate is not None:
        entities = [e for e in entities if predicate_matches(e.fields, fexpr.predicate)]
    return entities


def _line(loc: SourceLocation | None) -> int:
    return loc.start_line if loc else 0


def _col(loc: SourceLocation | None) -> int:
    return loc.start_column if loc else 0


def _did_you_mean(name: str, candidates: list[str], *, max_distance: int = 2) -> str | None:
    """Return the closest candidate name by edit distance, if within threshold.

    Used for "did you mean?" hints. Uses a small custom Levenshtein rather
    than pulling in ``difflib`` so the diagnostic is deterministic across
    Python versions.
    """
    if not candidates:
        return None
    best: tuple[int, str] | None = None
    for cand in candidates:
        d = _levenshtein(name, cand)
        if d <= max_distance and (best is None or d < best[0]):
            best = (d, cand)
    return best[1] if best else None


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            ins = curr[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            curr.append(min(ins, dele, sub))
        prev = curr
    return prev[-1]
