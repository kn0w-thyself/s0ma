"""IR builder — constructs .s0ma.json documents from parsed modules.

Consumes the semantic model (S0maModule + DerivedEdges) and produces
a fully-resolved, deterministic IRDocument per PRD §2.5. This is the
canonical internal truth per PRD §2.1.5 (IR-first core): the Python
emitter and runtime bridge consume this normalized model rather than
re-deriving semantics independently.

PRD references: FR-23, §2.5 (IR schema), §2.5.3 (determinism), NFR-01
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.nodes import (
    AssertBoolean,
    AssertComparison,
    BooleanPredicate,
    CellDecl,
    ComparisonPredicate,
    DocGuideDecl,
    DocRefDecl,
    EntityRefAst,
    ExampleDecl,
    FilterExprAst,
    GanglionDecl,
    HelperDecl,
    IntegrationDecl,
    IterationAst,
    NerveDecl,
    S0maModule,
    SectionAst,
    StandaloneAxonDecl,
    TestDecl,
)
from s0ma_dsl.ir.constant_values import constant_literal
from s0ma_dsl.ir.schema import (
    SCHEMA_VERSION,
    TRANSPILER_VERSION,
    IRAssertBoolean,
    IRAssertComparison,
    IRAuthoredEdge,
    IRBooleanPredicate,
    IRComparisonPredicate,
    IRComponent,
    IRComponentLocation,
    IRDerivedEdge,
    IRDocGuide,
    IRDocRef,
    IRDocument,
    IREdges,
    IREntityRef,
    IRExample,
    IRFilterExpr,
    IRHelper,
    IRImports,
    IRIntegration,
    IRModule,
    IRPrivilegedImport,
    IRRequiresImport,
    IRSection,
    IRUsesImport,
    IRVerificationEdge,
)
from s0ma_dsl.resolver.namespaces import canonicalize_qualified_target
from s0ma_dsl.semantic_state import SemanticState

if TYPE_CHECKING:
    from s0ma_dsl.codegen.observes_resolver import PrivilegedImportInfo
    from s0ma_dsl.semantic.derived_edges import DerivedEdge

__all__ = [
    "IRBuilder",
    "build_ir",
    "compute_content_hash",
]


# ---------------------------------------------------------------------------
# Content hash generation (Task 10.2)
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_compute_content_hash",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Compute a deterministic SHA-256 content hash over .s0ma source text for change "
        "detection and cache invalidation."
    ),
    idempotent=True,
    is_framework=True,
)
def compute_content_hash(source_text: str) -> str:
    """Compute a SHA-256 content hash over the source text.

    The hash is computed over the raw source bytes (UTF-8 encoded).
    This provides a deterministic, stable identifier for change
    detection per PRD §2.7.5.

    Parameters
    ----------
    source_text:
        The raw .s0ma source file content.

    Returns
    -------
    str
        Hex-encoded SHA-256 hash prefixed with ``sha256:``.
    """
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _metadata_to_ir(
    entries: tuple[tuple[str, object], ...],
) -> dict[str, object]:
    """Authored ``metadata:`` AST pairs → the IR's JSON object form.

    DSL-M1 (0.8.0, ADR-011 §(a)/(g)): keys keep authored order (JSON
    objects serialize in insertion order); ``tuple[str, ...]`` list
    values become JSON arrays. Validation has already rejected
    duplicate keys and out-of-shape values by the time the IR builds,
    so the plain dict construction is total.
    """
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in entries
    }


# ---------------------------------------------------------------------------
# IR Builder
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_IRBuilder",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent=(
        "Builds a normalized IRDocument from a parsed S0maModule and derived edges for "
        ".s0ma.json generation."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class IRBuilder:
    """Builds a normalized IRDocument from a parsed S0maModule.

    Consumes the semantic model and derived edges, canonicalises all
    IDs, expands inline axons to full edges, separates edge categories,
    preserves source declaration order, and applies deterministic
    ordering per PRD §2.5.3.

    Attributes
    ----------
    source_file:
        Path to the .s0ma source file.
    source_text:
        Raw source text for content hash computation.
    transpiled_file:
        Path to the transpiled .py output file (may be empty if
        not yet generated).
    """

    source_file: str = ""
    source_text: str = ""
    transpiled_file: str = ""

    def build(
        self,
        module: S0maModule,
        derived_edges: list[DerivedEdge] | None = None,
        privileged_imports: list[PrivilegedImportInfo] | None = None,
    ) -> IRDocument:
        """Build the complete IRDocument for a module.

        Parameters
        ----------
        module:
            A fully parsed and validated S0maModule.
        derived_edges:
            Derived edges from the DerivedEdgeAnalyzer (M9). If None,
            no derived edges are included.
        privileged_imports:
            Privileged imports determined during ganglion/test emission
            (M12). If None, no privileged imports are included.

        Returns
        -------
        IRDocument
            The complete, deterministic IR document.
        """
        if derived_edges is None:
            derived_edges = []
        if privileged_imports is None:
            privileged_imports = []

        module_name = module.module.name

        # Build each section
        ir_module = self._build_module_metadata(module)
        ir_components = self._build_components(module, module_name)
        ir_edges = self._build_edges(module, derived_edges, module_name)
        ir_imports = self._build_imports(module, module_name, privileged_imports)
        ir_exports = tuple(module.module.exports)
        ir_doc_refs = self._build_doc_refs(module)
        ir_doc_guides = self._build_doc_guides(module)
        ir_examples = self._build_examples(module)
        ir_helpers = self._build_helpers(module, module_name)
        ir_integrations = self._build_integrations(module, module_name)

        # Top-level source hash for fast staleness checks (MS 5b).
        # Uses truncated SHA-256 (16 hex chars) matching the .py header.
        source_hash = ""
        if self.source_text:
            digest = hashlib.sha256(self.source_text.encode("utf-8")).hexdigest()
            source_hash = f"sha256:{digest[:16]}"

        return IRDocument(
            schema_version=SCHEMA_VERSION,
            transpiler_version=TRANSPILER_VERSION,
            source_hash=source_hash,
            module=ir_module,
            components=ir_components,
            edges=ir_edges,
            imports=ir_imports,
            exports=ir_exports,
            doc_refs=ir_doc_refs,
            doc_guides=ir_doc_guides,
            examples=ir_examples,
            helpers=ir_helpers,
            integrations=ir_integrations,
            semantic_state_paths=self._semantic_state_paths(module),
        )

    @staticmethod
    def _semantic_state_paths(
        module: S0maModule,
    ) -> tuple[tuple[tuple[str | int, ...], SemanticState], ...]:
        """Map AST tagged states onto their canonical IR3 existing keys."""

        paths: list[tuple[tuple[str | int, ...], SemanticState]] = []

        def add_states(
            states: tuple[tuple[str, SemanticState], ...],
            mapping: dict[str, tuple[str | int, ...]],
        ) -> None:
            for field, state in states:
                path = mapping.get(field)
                if path is not None:
                    paths.append((path, state))

        def add(
            node: Any,
            mapping: dict[str, tuple[str | int, ...]],
        ) -> None:
            add_states(node.semantic_states, mapping)

        # Import state values use the authored canonical spelling rather than
        # the lower-level IRRequiresImport record shape. This is the frozen
        # s0ma-ir@3 field contract (e.g. ``["json"]``).
        module_states = dict(module.module.semantic_states)
        for field in (
            "requires", "soft_requires", "runtime_only_requires",
            "deferred_requires",
        ):
            state = module_states.get(field)
            if state is not None and state.state == "value":
                entries = getattr(module.module, field)
                rendered: list[str] = []
                for entry in entries:
                    token = entry.module_path
                    if entry.alias:
                        token = f"{token} as {entry.alias}"
                    rendered.append(token)
                module_states[field] = SemanticState.valued(rendered)
        uses_state = module_states.get("uses")
        if uses_state is not None and uses_state.state == "value":
            module_states["uses"] = SemanticState.valued([
                (
                    f"{entry.qualified_name} as {entry.alias}"
                    if entry.alias else entry.qualified_name
                )
                for entry in module.module.uses
            ])
        add_states(tuple(module_states.items()), {
            "intent": ("module", "intent"),
            "exports": ("exports",),
            "requires": ("imports", "requires"),
            "uses": ("imports", "uses"),
            "soft_requires": ("imports", "soft_requires"),
            "runtime_only_requires": ("imports", "runtime_only_requires"),
            "deferred_requires": ("imports", "deferred_requires"),
            "exports_helpers": ("module", "exports_helpers"),
        })

        component_index = 0
        for declaration in module.all_declarations:
            if not isinstance(declaration, (NerveDecl, CellDecl, GanglionDecl, TestDecl)):
                continue
            prefix: tuple[str | int, ...] = ("components", component_index)
            mapping: dict[str, tuple[str | int, ...]] = {
                "intent": (*prefix, "intent"),
            }
            names: tuple[str, ...]
            if isinstance(declaration, NerveDecl):
                names = (
                    "expects", "guarantees", "forbids", "provides", "returns",
                    "raises", "interface", "latency_ms", "depends_on",
                    "internal_helpers", "expected_exceptions",
                    "consumes_via_dict", "declares_attributes", "covered_by",
                )
            elif isinstance(declaration, CellDecl):
                names = (
                    "schema", "invariants", "covered_by", "category",
                    "dataclass_invariants", "placeholders",
                )
            elif isinstance(declaration, GanglionDecl):
                names = (
                    "observes", "on_anomaly", "forbids", "priors", "depends_on",
                    "covered_by",
                )
            else:
                names = ("tests", "expects", "depends_on", "mocks")
            mapping.update({name: (*prefix, "fields", name) for name in names})
            add(declaration, mapping)
            component_index += 1

        for index, declaration in enumerate(module.doc_refs):
            add(declaration, {
                "intent": ("doc_refs", index, "intent"),
                "covers": ("doc_refs", index, "covers"),
                "sections": ("doc_refs", index, "sections"),
            })
        for index, declaration in enumerate(module.doc_guides):
            add(declaration, {
                "intent": ("doc_guides", index, "intent"),
                "covers": ("doc_guides", index, "covers"),
                "asserts": ("doc_guides", index, "asserts"),
                "examples": ("doc_guides", index, "examples"),
                "prose_body": ("doc_guides", index, "body"),
            })
        for index, declaration in enumerate(module.examples):
            add(declaration, {
                "intent": ("examples", index, "intent"),
                "demonstrates": ("examples", index, "demonstrates"),
                "python_body": ("examples", index, "body"),
            })
        for index, declaration in enumerate(module.helpers):
            add(declaration, {
                "intent": ("helpers", index, "intent"),
                "body": ("helpers", index, "body"),
            })
        for index, declaration in enumerate(module.integrations):
            add(declaration, {
                "intent": ("integrations", index, "intent"),
                "factory": ("integrations", index, "factory"),
                "smoke_test_primary": ("integrations", index, "smoke_test_primary"),
                "manifest": ("integrations", index, "manifest"),
            })
        return tuple(paths)

    def to_json(
        self,
        module: S0maModule,
        derived_edges: list[DerivedEdge] | None = None,
        privileged_imports: list[PrivilegedImportInfo] | None = None,
    ) -> str:
        """Build the IRDocument and serialize to deterministic JSON.

        Parameters
        ----------
        module:
            A fully parsed and validated S0maModule.
        derived_edges:
            Derived edges from the DerivedEdgeAnalyzer.

        Returns
        -------
        str
            Deterministic JSON string (sorted keys, 2-space indent).
        """
        doc = self.build(module, derived_edges, privileged_imports)
        return json.dumps(
            doc.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )

    # -------------------------------------------------------------------
    # Module metadata
    # -------------------------------------------------------------------

    def _build_module_metadata(self, module: S0maModule) -> IRModule:
        """Build the module metadata block.

        POST-4c (0.15.0): records ``exports_helpers`` so downstream IR
        consumers can introspect the re-export surface.
        """
        content_hash = compute_content_hash(self.source_text) if self.source_text else ""
        return IRModule(
            name=module.module.name,
            layer=module.module.layer.value,
            version=module.module.version,
            intent=module.module.intent,
            content_hash=content_hash,
            source_file=self.source_file,
            transpiled_file=self.transpiled_file,
            tags=module.module.tags,
            exports_helpers=module.module.exports_helpers,
        )

    # -------------------------------------------------------------------
    # Components — in source declaration order (PRD §2.5.3)
    # -------------------------------------------------------------------

    def _build_components(
        self,
        module: S0maModule,
        module_name: str,
    ) -> tuple[IRComponent, ...]:
        """Build IR component entries in source declaration order."""
        components: list[IRComponent] = []

        # all_declarations returns declarations sorted by source line
        for decl in module.all_declarations:
            ir_comp = self._decl_to_ir_component(decl, module_name)
            if ir_comp is not None:
                components.append(ir_comp)

        return tuple(components)

    def _decl_to_ir_component(
        self,
        decl: (
            NerveDecl | CellDecl | GanglionDecl | TestDecl
            | StandaloneAxonDecl | HelperDecl | IntegrationDecl
            | DocRefDecl | DocGuideDecl | ExampleDecl
        ),
        module_name: str,
    ) -> IRComponent | None:
        """Convert a single declaration to an IR component entry.

        Standalone axons are not components — they produce edges, not
        component entries. Returns None for standalone axons.

        M13 (feedback 5–6): helpers are also *not* components — they
        emit a plain ``def`` and live in their own ``helpers`` IR
        section. Returns None for HelperDecl so the component graph
        stays clean.

        POST-5 (0.16.0): integration declarations are *not* components
        — the four auto-emitted helpers (get_factory / get_manifest /
        smoke_test_primary / get_smoke_test) ARE the public component
        surface; the IntegrationDecl itself lives in the ``integrations``
        IR section. Returns None for IntegrationDecl.
        """
        if isinstance(decl, StandaloneAxonDecl):
            return None
        if isinstance(decl, HelperDecl):
            return None
        if isinstance(decl, IntegrationDecl):
            return None

        canonical_id = f"{module_name}::{decl.name}"

        location = IRComponentLocation(
            start_line=decl.location.start_line if decl.location else 0,
            end_line=decl.location.end_line if decl.location else 0,
        )

        if isinstance(decl, NerveDecl):
            return self._nerve_to_ir(decl, canonical_id, location)
        elif isinstance(decl, CellDecl):
            return self._cell_to_ir(decl, canonical_id, location)
        elif isinstance(decl, GanglionDecl):
            return self._ganglion_to_ir(decl, canonical_id, location)
        elif isinstance(decl, TestDecl):
            return self._test_to_ir(decl, canonical_id, location)
        return None

    def _nerve_to_ir(
        self,
        nerve: NerveDecl,
        canonical_id: str,
        location: IRComponentLocation,
    ) -> IRComponent:
        """Convert a NerveDecl to an IRComponent."""
        fields: dict[str, Any] = {
            "expects": nerve.expects,
            "guarantees": nerve.guarantees,
            "forbids": nerve.forbids,
            "evaluates_at": nerve.evaluates_at.value,
        }
        if nerve.provides:
            fields["provides"] = list(nerve.provides)
        # POST-3a (0.15.0): per-method ``returns:`` / ``expects:`` /
        # ``guarantees:`` triples for the ``provides:`` field surface in
        # the IR under ``provides_contracts``. Each entry is a dict
        # ``{"name": ..., "returns"?: ..., "expects"?: ..., "guarantees"?: ...}``
        # — only the keys the author declared appear. The IR omits the
        # field entirely when every entry is bare (flat form) so legacy
        # nerves carry no new IR surface. Consumers (fr3d settings /
        # OAuth nerves) read this to introspect per-method contracts
        # without re-parsing the .s0ma source.
        if any(entry.has_triple for entry in nerve.provides_entries):
            contracts: list[dict[str, Any]] = []
            for provides_entry in nerve.provides_entries:
                contract_rec: dict[str, Any] = {"name": provides_entry.name}
                if provides_entry.returns is not None:
                    contract_rec["returns"] = provides_entry.returns
                if provides_entry.expects is not None:
                    contract_rec["expects"] = provides_entry.expects
                if provides_entry.guarantees is not None:
                    contract_rec["guarantees"] = provides_entry.guarantees
                contracts.append(contract_rec)
            fields["provides_contracts"] = contracts
        if nerve.returns:
            fields["returns"] = list(nerve.returns)
        if nerve.raises:
            fields["raises"] = list(nerve.raises)
        if nerve.abstract:
            fields["abstract"] = True
        if nerve.interface:
            fields["interface"] = list(nerve.interface)
        if nerve.latency_ms is not None:
            fields["latency_ms"] = nerve.latency_ms
        if nerve.version:
            fields["version"] = nerve.version
        if nerve.tags:
            fields["tags"] = list(nerve.tags)
        # M18 (feedback 5–6): expose declared structural attribute claims
        # (``landmark:header``, ``route:GET /self``, …) so ``s0ma inspect``
        # and downstream tools can see them in the IR.
        if nerve.declares_attributes:
            fields["declares_attributes"] = list(nerve.declares_attributes)
        # F3 (feedback 5–6 follow-up): explicit page-composer marker
        # surfaces in the IR so ``s0ma inspect`` shows it and downstream
        # tools (doc subsystem, future linters) can derive against it.
        # Only emitted when the nerve is marked — keeps the field
        # additive and backwards-compatible (schema stays at 1.2.0).
        if nerve.is_page_composer:
            fields["is_page_composer"] = True
        # POST-3d (0.15.0): the optional ``internal:`` field surfaces
        # under ``components[].fields.internal_helpers`` so ``s0ma
        # inspect`` can render the inner-helper sub-section without
        # promoting helpers to public components. Each entry is a
        # dict ``{"name": str, "intent"?: str}`` — the ``intent`` key
        # is omitted when the author did not declare one (matching
        # the bare ``- _foo`` form). Legacy nerves with no
        # ``internal:`` carry no new IR surface; the key is omitted
        # entirely when ``internal_helpers`` is empty.
        if nerve.internal_helpers:
            internal_records: list[dict[str, Any]] = []
            for internal_entry in nerve.internal_helpers:
                internal_rec: dict[str, Any] = {"name": internal_entry.name}
                if internal_entry.intent is not None:
                    internal_rec["intent"] = internal_entry.intent
                internal_records.append(internal_rec)
            fields["internal_helpers"] = internal_records
        # POST-12a (0.16.0): ``expected_exceptions:`` — Python-side
        # exceptions the nerve catches by design. Round-trips through
        # the IR under ``components[].fields.expected_exceptions``;
        # legacy nerves with no field carry no new IR surface.
        if nerve.expected_exceptions:
            fields["expected_exceptions"] = list(nerve.expected_exceptions)
        # POST-12f (0.16.0): ``deferred:`` — stub-marker annotation.
        # When set, the reason string surfaces in the IR under
        # ``components[].fields.deferred`` so ``s0ma check
        # --report-deferred`` can enumerate every deferred declaration
        # in the project. Absent → key omitted entirely.
        if nerve.deferred is not None:
            fields["deferred"] = nerve.deferred
        # POST-12d (0.16.0): ``consumes_via_dict:`` rides through the
        # IR under ``components[].fields.consumes_via_dict`` so the
        # registry's introspection surface exposes the duck-typed
        # coupling. Each entry is a dict ``{"contract": <C>, "param": <P>}``.
        # Absent / empty → key omitted entirely.
        if nerve.consumes_via_dict:
            records: list[dict[str, Any]] = []
            for consumes_entry in nerve.consumes_via_dict:
                records.append({
                    "contract": consumes_entry.contract,
                    "param": consumes_entry.param,
                })
            fields["consumes_via_dict"] = records
        # DSL-M1 (0.8.0, ADR-011 §(a)/(g)): the authored ``metadata:``
        # map rides the IR under ``components[].fields.metadata`` as a
        # JSON object in authored key order. Omitted entirely when not
        # authored — legacy builds carry no new IR surface (L-7).
        if nerve.metadata:
            fields["metadata"] = _metadata_to_ir(nerve.metadata)
        # DSL-M1 (0.8.0, ADR-011 §(b)/(g)): the public serving name
        # rides the IR under ``components[].fields.serves_as``.
        # Omitted when absent (L-7).
        if nerve.serves_as is not None:
            fields["serves_as"] = nerve.serves_as
        # DSL-M2 (0.8.0, ADR-011 §(e)/(g)): external test-evidence
        # credit rides the IR under ``components[].fields.covered_by``
        # — the auditable record behind the release-gate credit.
        # Omitted when absent (L-7).
        if nerve.covered_by:
            fields["covered_by"] = list(nerve.covered_by)

        return IRComponent(
            canonical_id=canonical_id,
            declaration_type="nerve",
            kind=nerve.kind.value,
            visibility=nerve.visibility.value,
            intent=nerve.intent,
            fields=fields,
            location=location,
        )

    def _cell_to_ir(
        self,
        cell: CellDecl,
        canonical_id: str,
        location: IRComponentLocation,
    ) -> IRComponent:
        """Convert a CellDecl to an IRComponent."""
        fields: dict[str, Any] = {
            "schema": cell.schema,
        }
        # A CONSTANT cell whose body assigns a simple literal carries that
        # literal at ``fields.value`` (``s0ma_dsl.ir.constant_values``
        # says exactly which bodies qualify). The key is absent for every
        # other cell, so a reader distinguishes "no literal" from a
        # constant whose value is null. The emitted ``register_constant``
        # call and the self-context carry the same value.
        has_value, value = constant_literal(cell)
        if has_value:
            fields["value"] = value
        if cell.invariants:
            fields["invariants"] = cell.invariants
        if cell.version:
            fields["version"] = cell.version
        if cell.tags:
            fields["tags"] = list(cell.tags)
        # POST-2 (0.15.0): the optional ``category:`` field rides through
        # the IR so downstream consumers (fr3d's MS 19 ConfigDiff
        # classifier, the ``s0ma inspect`` renderer) can pivot on it
        # without re-parsing the source. Absent → key omitted entirely.
        if cell.category:
            fields["category"] = cell.category
        # POST-12f (0.16.0): ``deferred:`` stub-marker — see the nerve
        # branch for the contract. Cells use the same IR shape.
        if cell.deferred is not None:
            fields["deferred"] = cell.deferred
        # POST-12b (0.16.0): ``placeholders:`` round-trips through the
        # IR under ``components[].fields.placeholders`` so downstream
        # template renderers (and authoring tools that need to know
        # which markers the embedded template carries) can read the
        # declared marker set without re-parsing the source. Legacy
        # cells with no field carry no new IR surface; the key is
        # omitted entirely when ``placeholders`` is empty.
        if cell.placeholders:
            fields["placeholders"] = list(cell.placeholders)
        # POST-12c (0.16.0): ``dataclass_invariants:`` round-trips
        # through the IR under
        # ``components[].fields.dataclass_invariants`` so downstream
        # consumers (future linters, doc renderers, runtime contract
        # enforcers) can read the declared invariants without
        # re-parsing the .s0ma source. Each entry is preserved as
        # a verbatim Python expression string. Absent / empty → key
        # omitted entirely; legacy MODEL cells with no
        # ``dataclass_invariants:`` carry no new IR surface.
        if cell.dataclass_invariants:
            fields["dataclass_invariants"] = list(
                cell.dataclass_invariants,
            )
        # DSL-M1 (0.8.0): authored ``metadata:`` — see the nerve branch.
        if cell.metadata:
            fields["metadata"] = _metadata_to_ir(cell.metadata)
        # DSL-M2 (0.8.0): ``covered_by:`` — see the nerve branch.
        if cell.covered_by:
            fields["covered_by"] = list(cell.covered_by)

        return IRComponent(
            canonical_id=canonical_id,
            declaration_type="cell",
            kind=cell.kind.value,
            visibility=cell.visibility.value,
            intent=cell.intent,
            fields=fields,
            location=location,
        )

    def _ganglion_to_ir(
        self,
        ganglion: GanglionDecl,
        canonical_id: str,
        location: IRComponentLocation,
    ) -> IRComponent:
        """Convert a GanglionDecl to an IRComponent."""
        fields: dict[str, Any] = {
            "observes": list(ganglion.observes),
            "scope": ganglion.scope.value,
            "priors": ganglion.priors,
            "on_anomaly": ganglion.on_anomaly,
            "forbids": ganglion.forbids,
        }
        if ganglion.tags:
            fields["tags"] = list(ganglion.tags)
        # POST-12f (0.16.0): ``deferred:`` stub-marker — see the nerve
        # branch for the contract. Ganglia use the same IR shape.
        if ganglion.deferred is not None:
            fields["deferred"] = ganglion.deferred
        # DSL-M1 (0.8.0): authored ``metadata:`` — see the nerve branch.
        if ganglion.metadata:
            fields["metadata"] = _metadata_to_ir(ganglion.metadata)
        # DSL-M2 (0.8.0): ``covered_by:`` — see the nerve branch.
        if ganglion.covered_by:
            fields["covered_by"] = list(ganglion.covered_by)

        return IRComponent(
            canonical_id=canonical_id,
            declaration_type="ganglion",
            kind=None,
            visibility=ganglion.visibility.value,
            intent=ganglion.intent,
            fields=fields,
            location=location,
        )

    def _test_to_ir(
        self,
        test: TestDecl,
        canonical_id: str,
        location: IRComponentLocation,
    ) -> IRComponent:
        """Convert a TestDecl to an IRComponent."""
        fields: dict[str, Any] = {
            "tests": list(test.tests),
        }
        if test.expects:
            fields["expects"] = test.expects
        if test.tags:
            fields["tags"] = list(test.tags)
        # POST-3b (0.15.0): ``mocks:`` list of mocked nerve targets rides
        # through to downstream tooling (fr3d's Phase 2 Frontend track is
        # the motivating consumer) so the test→target mock relationship
        # is queryable from the IR rather than re-parsed from source.
        if test.mocks:
            fields["mocks"] = list(test.mocks)

        return IRComponent(
            canonical_id=canonical_id,
            declaration_type="test",
            kind=None,
            visibility=None,
            intent=test.intent,
            fields=fields,
            location=location,
        )

    # -------------------------------------------------------------------
    # Edges — authored before derived, deterministic ordering (PRD §2.5.3)
    # -------------------------------------------------------------------

    def _build_edges(
        self,
        module: S0maModule,
        derived_edges: list[DerivedEdge],
        module_name: str,
    ) -> IREdges:
        """Build all edge categories with deterministic ordering."""
        authored = self._build_authored_edges(module, module_name)
        derived = self._build_derived_edges(derived_edges, module_name)
        verification = self._build_verification_edges(module, module_name)

        return IREdges(
            authored=tuple(authored),
            derived=tuple(derived),
            verification=tuple(verification),
        )

    def _build_authored_edges(
        self,
        module: S0maModule,
        module_name: str,
    ) -> list[IRAuthoredEdge]:
        """Build authored edges from inline depends_on and standalone axons.

        Ordering per PRD §2.5.3: by source canonical ID, then by target.
        """
        edges: list[IRAuthoredEdge] = []

        # Inline depends_on entries (expanded to full edges)
        for decl in module.all_declarations:
            if isinstance(decl, StandaloneAxonDecl):
                continue
            parent_name = getattr(decl, "name", None)
            if parent_name is None:
                continue
            for axon in getattr(decl, "depends_on", ()):
                source_canonical = f"{module_name}::{parent_name}"
                # Bare inline axon targets are intra-module. DSL-M2
                # (0.8.0, ADR-011 §(d)): QUALIFIED targets
                # (``module.declaration``) canonicalize to the
                # registry's ``module::declaration`` alphabet — a
                # value-space widening of the existing string field,
                # not a schema change.
                if "." in axon.target:
                    target_mod, target_decl = axon.target.split(".", 1)
                    target_canonical = f"{target_mod}::{target_decl}"
                else:
                    target_canonical = f"{module_name}::{axon.target}"
                # Auto-generate intent per PRD §2.2.7
                auto_intent = (
                    f"{parent_name} {axon.relation.value} "
                    f"{axon.target}: {axon.carries}"
                )
                edges.append(IRAuthoredEdge(
                    source=source_canonical,
                    target=target_canonical,
                    relation=axon.relation.value,
                    carries=axon.carries,
                    coupling=axon.coupling.value,
                    intent=auto_intent,
                    origin="inline_depends_on",
                ))

        # Standalone axons (cross-module edges)
        # Build a lookup from uses local names to canonical IDs
        uses_lookup = self._build_uses_lookup(module)

        for axon in module.axons:
            source_canonical = f"{module_name}::{axon.source}"
            # Standalone axon targets may be:
            # 1. Already qualified (module.component) — convert dot to ::
            # 2. Bare names resolved via uses list — cross-module reference
            # 3. Bare names not in uses — local reference (fallback)
            target_canonical = self._resolve_axon_target(
                axon.target, module_name, uses_lookup
            )
            edges.append(IRAuthoredEdge(
                source=source_canonical,
                target=target_canonical,
                relation=axon.relation.value,
                carries=axon.carries,
                coupling=axon.coupling.value,
                intent=axon.intent,
                origin="standalone_axon",
            ))

        # Deterministic ordering: by source, then by target
        edges.sort(key=lambda e: (e.source, e.target))
        return edges

    def _build_derived_edges(
        self,
        derived_edges: list[DerivedEdge],
        module_name: str,
    ) -> list[IRDerivedEdge]:
        """Build derived edges from the DerivedEdgeAnalyzer output.

        Ordering per PRD §2.5.3: by source canonical ID, then by target.
        """
        edges: list[IRDerivedEdge] = []

        for de in derived_edges:
            source_canonical = f"{module_name}::{de.source}"
            # Use the canonical target from derivation if available
            target_canonical = de.target_canonical
            if "::" not in target_canonical:
                target_canonical = f"{module_name}::{target_canonical}"

            edges.append(IRDerivedEdge(
                source=source_canonical,
                target=target_canonical,
                relation=de.relation.value,
                origin=de.origin,
            ))

        # Deterministic ordering: by source, then by target
        edges.sort(key=lambda e: (e.source, e.target))
        return edges

    def _build_verification_edges(
        self,
        module: S0maModule,
        module_name: str,
    ) -> list[IRVerificationEdge]:
        """Build verification edges from test declarations.

        Each test's ``tests`` field produces verification edges linking
        the test to the components it validates.
        """
        edges: list[IRVerificationEdge] = []

        for test in module.tests:
            test_canonical = f"{module_name}::{test.name}"
            for validated_name in test.tests:
                # Test targets may be local or qualified
                validated_canonical = self._resolve_target_canonical(
                    validated_name, module_name
                )
                edges.append(IRVerificationEdge(
                    test=test_canonical,
                    validates=validated_canonical,
                ))

        # Deterministic ordering: by test, then by validates
        edges.sort(key=lambda e: (e.test, e.validates))
        return edges

    # -------------------------------------------------------------------
    # Imports — preserve source declaration order (PRD §2.5.3)
    # -------------------------------------------------------------------

    def _build_imports(
        self,
        module: S0maModule,
        module_name: str,
        privileged_imports: list[PrivilegedImportInfo] | None = None,
    ) -> IRImports:
        """Build import entries preserving source declaration order."""
        requires = tuple(
            IRRequiresImport(
                module_path=r.module_path,
                alias=r.alias,
                is_from_import=r.is_from_import,
            )
            for r in module.module.requires
        )

        soft_requires = tuple(
            IRRequiresImport(
                module_path=r.module_path,
                alias=r.alias,
                is_from_import=r.is_from_import,
            )
            for r in module.module.soft_requires
        )

        # POST-10b (0.16.0): runtime-only requires — same shape as
        # ``requires``, surfaced in the IR so downstream consumers
        # (debugging tooling, IR diff) can distinguish the two
        # populations even though the emitted import lines look
        # identical.
        runtime_only_requires = tuple(
            IRRequiresImport(
                module_path=r.module_path,
                alias=r.alias,
                is_from_import=r.is_from_import,
            )
            for r in module.module.runtime_only_requires
        )

        # DSL-M2 (0.8.0, ADR-011 §(c)/(g)): deferred requires — same
        # entry shape, built exactly parallel to ``soft_requires`` /
        # ``runtime_only_requires``, with the self-describing
        # ``deferred=True`` flag (serialized as ``"deferred": true``
        # on each entry; the list key itself is omitted when empty).
        deferred_requires = tuple(
            IRRequiresImport(
                module_path=r.module_path,
                alias=r.alias,
                is_from_import=r.is_from_import,
                deferred=True,
            )
            for r in module.module.deferred_requires
        )

        uses = tuple(
            IRUsesImport(
                qualified_name=u.qualified_name,
                alias=u.alias,
                resolved_canonical_id=self._resolve_uses_canonical(u.qualified_name),
            )
            for u in module.module.uses
        )

        # Privileged imports from ganglion/test emission (M12)
        if privileged_imports:
            privileged = tuple(
                IRPrivilegedImport(
                    canonical_id=p.canonical_id,
                    import_kind=p.import_kind,
                    referenced_in=p.referenced_in,
                )
                for p in sorted(privileged_imports, key=lambda x: x.canonical_id)
            )
        else:
            privileged = ()

        return IRImports(
            requires=requires,
            soft_requires=soft_requires,
            uses=uses,
            privileged=privileged,
            runtime_only_requires=runtime_only_requires,
            deferred_requires=deferred_requires,
        )

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _build_uses_lookup(module: S0maModule) -> dict[str, str]:
        """Build a lookup from uses local names to canonical IDs.

        For each uses entry, the local name (alias or last segment of
        the qualified name) maps to its canonical ID.
        """
        lookup: dict[str, str] = {}
        for uses_entry in module.module.uses:
            qname = uses_entry.qualified_name
            canonical = IRBuilder._resolve_uses_canonical(qname)
            # Local name is the alias if present, otherwise the component
            # name (last segment after the dot)
            if uses_entry.alias:
                local = uses_entry.alias
            elif "." in qname:
                local = qname.rsplit(".", 1)[1]
            else:
                local = qname
            lookup[local] = canonical
        return lookup

    @staticmethod
    def _resolve_axon_target(
        target: str, module_name: str, uses_lookup: dict[str, str]
    ) -> str:
        """Resolve a standalone axon target to a canonical ID.

        Resolution order:
        1. If the target contains a dot (qualified), convert to canonical.
        2. If the target matches a uses entry local name, use its canonical ID.
        3. Otherwise, treat as a local reference.
        """
        if "." in target:
            parts = target.rsplit(".", 1)
            return f"{parts[0]}::{parts[1]}"
        if target in uses_lookup:
            return uses_lookup[target]
        return f"{module_name}::{target}"

    @staticmethod
    def _resolve_target_canonical(target: str, module_name: str) -> str:
        """Resolve a target reference to a canonical ID.

        Delegates to
        :func:`s0ma_dsl.resolver.namespaces.canonicalize_qualified_target`,
        which is the single source of truth for the syntactic
        ``module.component`` → ``module::component`` split. Both this
        helper and the dependency resolver's
        :func:`resolve_test_target_canonical` call into the same
        primitive so there is exactly one place where the rule lives.

        This is the syntactic layer only — it does not validate the
        target against the project registry. Per-module IR emission
        runs without a cross-module view, so verification edges are
        emitted as-authored; the dependency resolver performs
        registry-aware validation.
        """
        return canonicalize_qualified_target(target, module_name)

    @staticmethod
    def _resolve_uses_canonical(qualified_name: str) -> str:
        """Resolve a uses qualified name to a canonical ID.

        Converts ``module.component`` to ``module::component``.
        """
        if "." in qualified_name:
            parts = qualified_name.rsplit(".", 1)
            return f"{parts[0]}::{parts[1]}"
        return qualified_name

    # -------------------------------------------------------------------
    # Documentation subsystem (plan M5)
    # -------------------------------------------------------------------

    def _build_doc_refs(self, module: S0maModule) -> tuple[IRDocRef, ...]:
        """Build IR doc-ref entries in source declaration order."""
        out: list[IRDocRef] = []
        for decl in module.doc_refs:
            location = IRComponentLocation(
                start_line=decl.location.start_line if decl.location else 0,
                end_line=decl.location.end_line if decl.location else 0,
            )
            out.append(IRDocRef(
                name=decl.name,
                module=decl.module_location,
                intent=decl.intent,
                format=decl.format,
                output=decl.output,
                covers=tuple(_filter_expr_to_ir(c) for c in decl.covers),
                # G7a: round-trip the discriminator. When the ``covers:``
                # field uses the ``{ source: ... }`` shape, ``covers`` is
                # the empty tuple and this field carries the source name.
                covers_source=decl.covers_source,
                sections=tuple(_section_to_ir(s) for s in decl.sections),
                # Real content hash arrives in M6; use the empty string as a
                # placeholder per the M5 plan (subtask 1).
                content_hash="",
                location=location,
                tags=decl.tags,
            ))
        return tuple(out)

    def _build_doc_guides(self, module: S0maModule) -> tuple[IRDocGuide, ...]:
        """Build IR doc-guide entries in source declaration order."""
        out: list[IRDocGuide] = []
        for decl in module.doc_guides:
            location = IRComponentLocation(
                start_line=decl.location.start_line if decl.location else 0,
                end_line=decl.location.end_line if decl.location else 0,
            )
            out.append(IRDocGuide(
                name=decl.name,
                module=decl.module_location,
                intent=decl.intent,
                format=decl.format,
                output=decl.output,
                covers=tuple(_entity_ref_to_ir(r) for r in decl.covers),
                asserts=tuple(_assert_to_ir(a) for a in decl.asserts),
                examples=tuple(_entity_ref_to_ir(r) for r in decl.examples),
                body=decl.prose_body,
                content_hash="",
                location=location,
                tags=decl.tags,
            ))
        return tuple(out)

    def _build_examples(self, module: S0maModule) -> tuple[IRExample, ...]:
        """Build IR example entries in source declaration order."""
        out: list[IRExample] = []
        for decl in module.examples:
            location = IRComponentLocation(
                start_line=decl.location.start_line if decl.location else 0,
                end_line=decl.location.end_line if decl.location else 0,
            )
            # F1 (feedback 5–6 follow-up): the parser already dedented
            # ``decl.python_body`` at parse time. The IR carries that
            # canonical form directly so the runtime payload registered
            # via ``register_example`` and the IR remain byte-identical
            # without a second dedent here.
            body = decl.python_body or ""
            out.append(IRExample(
                name=decl.name,
                module=decl.module_location,
                intent=decl.intent,
                demonstrates=tuple(
                    _entity_ref_to_ir(r) for r in decl.demonstrates
                ),
                runs_in=decl.runs_in,
                body=body,
                location=location,
                tags=decl.tags,
            ))
        return tuple(out)

    def _build_integrations(
        self, module: S0maModule, module_name: str,
    ) -> tuple[IRIntegration, ...]:
        """Build IR integration entries in source declaration order (POST-5).

        Integrations are recorded under ``IRDocument.integrations`` —
        a section parallel to ``helpers``. The four auto-emitted
        helpers (``get_factory`` / ``get_manifest`` /
        ``smoke_test_primary`` / ``get_smoke_test``) appear in the
        regular components list under module-qualified canonical
        ids; this section preserves the declaration's metadata so
        ``s0ma inspect`` can render an ``Integrations`` section that
        groups the four helpers under the declaration's intent.
        """
        out: list[IRIntegration] = []
        for decl in module.integrations:
            location = IRComponentLocation(
                start_line=decl.location.start_line if decl.location else 0,
                end_line=decl.location.end_line if decl.location else 0,
            )
            out.append(IRIntegration(
                canonical_id=f"{module_name}::{decl.name}",
                name=decl.name,
                module=module_name,
                layer=decl.layer.value,
                version=decl.version,
                intent=decl.intent,
                factory=decl.factory,
                smoke_test_primary=decl.smoke_test_primary,
                manifest=dict(decl.manifest),
                location=location,
                tags=decl.tags,
            ))
        return tuple(out)

    def _build_helpers(
        self, module: S0maModule, module_name: str,
    ) -> tuple[IRHelper, ...]:
        """Build IR helper entries in source declaration order (M13).

        Helpers are recorded under ``IRDocument.helpers`` rather than
        under ``components`` because they are explicitly *not*
        registered as components (per the M13 plan / feedback 5–6 MS
        1, MS 13/16). The IR record carries the helper's intent and
        body so ``s0ma inspect`` can list them under a separate
        ``[helpers]`` section.

        POST-4a (0.15.0): ``body_kind`` carries the AST-classified
        structural shape (``"function"`` or ``"class"``); POST-4b
        adds ``inline`` to mark helpers declared via the ``@inline``
        shorthand inside the module header.
        """
        out: list[IRHelper] = []
        for decl in module.helpers:
            location = IRComponentLocation(
                start_line=decl.location.start_line if decl.location else 0,
                end_line=decl.location.end_line if decl.location else 0,
            )
            out.append(IRHelper(
                canonical_id=f"{module_name}::{decl.name}",
                name=decl.name,
                module=module_name,
                layer=decl.layer.value,
                intent=decl.intent,
                body=decl.body or "",
                location=location,
                tags=decl.tags,
                body_kind=decl.body_kind,
                inline=decl.inline,
            ))
        return tuple(out)


# ---------------------------------------------------------------------------
# AST → IR converters for the doc subsystem
# ---------------------------------------------------------------------------
#
# These intentionally drop the M2 ``raw`` field (debug-only per the M2
# Handoff Notes). Hashing later milestones perform must hash the structured
# representation; otherwise whitespace in source would change the hash.


def _entity_ref_to_ir(ref: EntityRefAst) -> IREntityRef:
    return IREntityRef(
        kind=ref.kind,
        name=ref.name,
        field_path=ref.field_path,
    )


def _comparison_to_ir_filter(
    pred: ComparisonPredicate,
) -> IRComparisonPredicate:
    # In a filter context, lhs is always a tuple[str, ...].
    lhs = pred.lhs
    if isinstance(lhs, tuple):
        lhs_path = lhs
    elif isinstance(lhs, EntityRefAst):
        # Defensive: filters should never carry an entity-ref lhs at this
        # stage. Flatten to its field path for IR purposes.
        lhs_path = lhs.field_path
    else:
        lhs_path = ()
    return IRComparisonPredicate(
        lhs=lhs_path,
        operator=pred.operator,
        rhs=pred.rhs,
    )


def _boolean_to_ir_filter(
    pred: BooleanPredicate,
) -> IRBooleanPredicate:
    return IRBooleanPredicate(
        operator=pred.operator,
        operands=tuple(_predicate_to_ir(o) for o in pred.operands),
    )


def _predicate_to_ir(
    pred: ComparisonPredicate | BooleanPredicate,
) -> IRComparisonPredicate | IRBooleanPredicate:
    if isinstance(pred, BooleanPredicate):
        return _boolean_to_ir_filter(pred)
    return _comparison_to_ir_filter(pred)


def _filter_expr_to_ir(fexpr: FilterExprAst) -> IRFilterExpr:
    return IRFilterExpr(
        kind=fexpr.kind,
        predicate=(
            _predicate_to_ir(fexpr.predicate)
            if fexpr.predicate is not None
            else None
        ),
        ordered_by=fexpr.ordered_by,
        group_by=fexpr.group_by,
    )


def _iteration_to_dict(it: IterationAst) -> dict[str, Any]:
    """Serialise an iteration's collection as a structured dict.

    The collection is either a :class:`FilterExprAst` or an
    :class:`EntityRefAst`; both are rendered through their structured
    forms.
    """
    coll = it.collection
    if isinstance(coll, FilterExprAst):
        coll_dict = {
            "type": "filter",
            "value": _filter_expr_to_ir(coll).to_dict(),
        }
    elif isinstance(coll, EntityRefAst):
        coll_dict = {
            "type": "entity_ref",
            "value": _entity_ref_to_ir(coll).to_dict(),
        }
    else:
        coll_dict = {"type": "unknown", "value": None}
    return {
        "var": it.var,
        "collection": coll_dict,
        "ordered_by": list(it.ordered_by),
        "group_by": it.group_by,
    }


def _section_to_ir(section: SectionAst) -> IRSection:
    iteration_dict: dict[str, Any] | None = None
    if section.iteration is not None:
        iteration_dict = _iteration_to_dict(section.iteration)
    return IRSection(
        field_name=section.field_name,
        iteration=iteration_dict,
    )


def _assert_to_ir(
    a: AssertComparison | AssertBoolean,
) -> IRAssertComparison | IRAssertBoolean:
    if isinstance(a, AssertBoolean):
        return IRAssertBoolean(
            operator=a.operator,
            operands=tuple(_assert_to_ir(o) for o in a.operands),
        )
    return IRAssertComparison(
        lhs=_entity_ref_to_ir(a.lhs),
        operator=a.operator,
        rhs=a.rhs,
    )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_build_ir",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Convenience function to build a normalized IRDocument from a parsed S0maModule and "
        "derived edges."
    ),
    idempotent=True,
    is_framework=True,
)
def build_ir(
    module: S0maModule,
    *,
    derived_edges: list[DerivedEdge] | None = None,
    privileged_imports: list[PrivilegedImportInfo] | None = None,
    source_file: str = "",
    source_text: str = "",
    transpiled_file: str = "",
) -> IRDocument:
    """Build a normalized IRDocument from a parsed S0maModule.

    Parameters
    ----------
    module:
        A fully parsed and validated S0maModule.
    derived_edges:
        Derived edges from the DerivedEdgeAnalyzer.
    privileged_imports:
        Privileged imports from ganglion/test emission (M12).
    source_file:
        Path to the .s0ma source file.
    source_text:
        Raw source text for content hash computation.
    transpiled_file:
        Path to the transpiled .py output file.

    Returns
    -------
    IRDocument
        The complete, deterministic IR document.
    """
    builder = IRBuilder(
        source_file=source_file,
        source_text=source_text,
        transpiled_file=transpiled_file,
    )
    return builder.build(module, derived_edges, privileged_imports)
