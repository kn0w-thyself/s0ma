# ADR-011: First-Class Declaration Metadata & the 0.8.0 Language-Surface Batch (`metadata:`, `serves_as:`, `deferred_requires:`, qualified `depends_on:`, `covered_by:`)

**Status:** Accepted (DSL-M0, dsl-improvements plan). Later milestones implement this ADR without relitigating it; anything outside its enumeration follows the plan's STOP-and-report rule.
**Date:** 2026-06-11
**Context:** `plans/s0ma-new-dsl-improvements-1.md` (Part 1 §1.3 design rules L-1..L-7 are the binding plan-level policy this ADR concretizes; milestone M0). Requirements ground truth: `plans/notes/mcp-selfhost-friction-log.md` §FINAL items 1, 2, 5, 6, 7, 8 and the F-* entries they cite (F-M0-6/7, F-M1-4, F-M2-2/3, F-M3-1/3/4, F-M4-1/2, F-M5-3/5 + the M6 postscript).
**References:** spec `docs/s0ma-dsl-spec-v0.16.0.md` (§2.4, §4.1–4.16, §8, Appendix A — section/line anchors below use v0.16.0 numbering), `packages/s0ma-mcp/docs/adr/ADR-001` (registry self/global disjointness, emitter pass-through Decision 3), [ADR-006](ADR-006-canonical-module-identity.md) (flat module names), [ADR-010](ADR-010-derived-doc-targets.md) (error-code registry in `s0ma_dsl.config`). All code anchors re-verified 2026-06-11 against `dsl-improvements` @ `9aa0a32`; drift vs the plan's Appendix A is recorded in the final section.

---

## Summary of decisions

| # | Decision | One-liner |
|---|---|---|
| (a) | `metadata:` | Block-map declaration field (integration `manifest:` syntax precedent), flat string keys → scalar or list-of-strings, shape-validated only, 27 reserved keys held in one frozen constant, merged into the existing emitted `metadata=` dict after the emitter-written keys. |
| (b) | `serves_as:` | Bare-identifier nerve field; uniqueness validated per module and per project build; emitted as reserved metadata key plus a two-line `__name__`/`__qualname__` stamp immediately after the decorated def; ComponentSpec identity unchanged (decorate-then-stamp). |
| (c) | deferred imports | New module-header sibling field `deferred_requires:` (same entry grammar as `requires:`, the POST-10b/POST-10j family pattern); emitter injects the import at the top of each consuming def body after the docstring; IR entries carry `deferred: true`. |
| (d) | qualified `depends_on:` | Dotted target form `module.declaration` (one dot, ADR-006 flat modules); **grammar.lark change required — definitive yes**; resolved against the project module set with export + layer + cycle rules identical to `uses:`; emitted `dependencies=[...]` carries the canonical `module::declaration` form for qualified targets. |
| (e) | `covered_by:` | Bracketed list of non-empty strings on nerve/cell/ganglion; release-mode `MISSING_TEST_COVERAGE` is satisfied by `tests:` coverage OR `covered_by:`; rides the IR and the emitted metadata (reserved key) so doc-refs render it from the registry snapshot. |
| (f) | doc front-matter version | **Drop** the front-matter `transpiler_version` field (F-M5-5's lead suggestion); `schema_version` stays as the contract identity; hash stamping unchanged; the manifest + `.pyi` header remain the only distribution-version carriers, preserving the no-churn-on-release property for rendered docs. |
| (g) | IR delta | `SCHEMA_VERSION` 2.0.0 → 2.1.0 at M1 (`ir/schema.py:61`); additive fields: `components[].fields.metadata` / `.serves_as` / `.covered_by`, `imports.deferred_requires` (entries with `deferred: true`); qualified targets widen the value space of existing edge/dependency strings to `module::declaration`. |
| (h) | spec v0.17.0 | One rename at M1 (rename + 198-byte breadcrumb + GUIDE_DOCS provenance + `_docs` copy + mcp rebuild); section-by-section diff plan below, split M1 (a/b), M2 (c/d/e), M4 (f + doc-subsystem v1.1). |

New diagnostic codes introduced by this batch (all registered in `s0ma_dsl.config`'s `SEVERITY_MATRIX` + `ERROR_CODE_DESCRIPTIONS`, all **error in every mode** — these are shape/contract violations, not style; `docs/_generated/common_errors.md` regenerates per ADR-010): `METADATA_INVALID_KEY`, `METADATA_INVALID_VALUE`, `METADATA_RESERVED_KEY`, `SERVES_AS_INVALID`, `SERVES_AS_COLLISION`, `COVERED_BY_EMPTY`, `DEFERRED_IMPORT_MODULE_SCOPE`, `DUPLICATE_REQUIRES_ENTRY`.

---

## (a) `metadata:` — the authored per-declaration metadata map (L-1; closes friction items F-M0-7, F-M3-3, F-M4-1)

### Syntax

Block-map form only, mirroring the one existing authored map field in the language (integration `manifest:`, spec §4.4b). Keys are identifiers at one indent level below the field; values are a quoted string, an integer, a float, a boolean (`true`/`false`), or a bracketed list of strings (list entries quoted, or bare when identifier-shaped — the same lexing `declares_attributes:` values use today).

```
nerve system_prompt_resource :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Serves the s0ma authoring system prompt guide document"
    evaluates_at: FUNCTION_BOUNDARY
    metadata:
        mcp_uri: "s0ma://guide/system-prompt"
        mcp_mime_type: "text/markdown"
        wraps: "s0ma_dsl.cli.main.S0maCLI"
        composes: [project_status, run_example]
        max_retries: 3
        experimental: false
    ---
    def system_prompt_resource() -> str:
        ...
```

There is no inline `metadata: {…}` form in this batch (rejected-for-now, see Rejected Alternatives). Nested maps and null values are out at plan level (L-1).

### Validation (shape only — the language never interprets values, P-2)

- `METADATA_INVALID_KEY`: key not identifier-shaped (`[A-Za-z_][A-Za-z0-9_]*`) or duplicated within the map.
- `METADATA_INVALID_VALUE`: value not in the L-1 shape set (string | int | float | bool | list-of-strings); nested maps, null, and heterogeneous/non-string lists are rejected here.
- `METADATA_RESERVED_KEY`: key collides with the reserved set below. Remediation names the colliding key and points at the declaration field that owns it (e.g. authored `visibility` in `metadata:` → "set the declaration's `visibility:` field instead").

### The reserved-key rule — verified per kind against the emitter (anchor A-6, re-verified)

The plan's L-1 names `visibility` and `evaluates_at` as examples; the verified truth is larger. The emitter writes registration-metadata dicts for FIVE emission shapes, with these keys:

| Emission shape (verified site in `codegen/python_emitter.py`) | Keys written |
|---|---|
| nerve — `_build_nerve_metadata` :843 (params :791, rendered :814-816) | `visibility`, `evaluates_at` always; `provides`, `provides_contracts`, `returns`, `raises`, `abstract`, `interface`, `expected_exceptions`, `deferred`, `consumes_via_dict` conditionally |
| ganglion — `_emit_ganglion` metadata block :1193-1241 | `visibility`, `scope`, `priors`, `on_anomaly` always; `resolved_observes` + `observes_patterns` OR `observes`; `deferred` conditionally |
| class cell (MODEL/ENUM/EXCEPTION/CONFIG) :975-1008 | `visibility`, `kind_detail` always; `schema`, `invariants`, `category`, `deferred`, `dataclass_invariants` conditionally |
| CONSTANT cell (`register_constant`) :1044-1065 / TYPE cell (`register_type`) :1080-1101 | `visibility` always; `schema`, `category`, `deferred` conditionally |
| integration helpers (`register_integration_helper`) :1426-1460 | fixed dict `integration`, `integration_manifest`, `integration_helper` |

Kinds with NO emitted metadata dict (also verified): `test` (`register_test` — bridge `runtime_bridge/registration.py:376` and core `registry.py:1076` accept no `metadata` parameter), `helper` (no registration call at all, emitter :1293), standalone `axon` (`register_relationship`, bridge :312 — no metadata parameter).

**Decision: one UNION reserved set across all kinds**, not per-kind sets — predictable for authors, future-proof for the emitter (an authored key that is reserved on any kind is reserved everywhere; the friction-log key family `mcp_*`/`composes`/`wraps` collides with nothing). The set includes this batch's two new emitter-written keys. The frozen constant:

```python
# ir/schema.py (new, M1) — single source of truth (P-2); the semantic validator imports it for
# METADATA_RESERVED_KEY, and an emitter test asserts every key the emitter writes is a member.
RESERVED_COMPONENT_METADATA_KEYS: frozenset[str] = frozenset({
    "abstract", "category", "consumes_via_dict", "covered_by", "dataclass_invariants",
    "deferred", "evaluates_at", "expected_exceptions", "integration", "integration_helper",
    "integration_manifest", "interface", "invariants", "kind_detail", "observes",
    "observes_patterns", "on_anomaly", "priors", "provides", "provides_contracts", "raises",
    "resolved_observes", "returns", "schema", "scope", "serves_as", "visibility",
})
```

(27 keys. `deferred` here is the POST-12f stub-marker metadata key — see the homonym note under (c). The constant lives in `ir/schema.py` because that module is already the artifact-contract home both the validator side and the codegen side may import without layering violations.)

### Pipeline and exact touch list (anchors re-verified)

Parser → AST → validation → IR → emitter → runtime, per L-1:

- `parser/s0ma_parser.py`: block-map field extraction in the per-kind builders — `_build_nerve` :3340, `_build_cell` ~:3703 region, ganglion builder; reuse the manifest map machinery (`_parse_manifest_scalar` :1442, map parsing ~:1498-1589) narrowed to the L-1 value shapes. The line-based preprocessor already captures block-form field bodies (depends_on block precedent at :5134); no lark change (anchor A-1: scalar/list/map FIELDS are preprocessor territory).
- `ast_nodes/nodes.py`: `metadata: tuple[tuple[str, MetadataValue], ...] | Mapping` — concretely a `tuple[tuple[str, str | int | float | bool | tuple[str, ...]], ...] = ()` on `NerveDecl` (:405), `CellDecl` (:555), `GanglionDecl` (:686), preserving authored order (frozen-dataclass house pattern; order is meaningful — F-M2-3 relied on attribute order, and the emitted dict preserves it).
- `semantic/validator.py`: the three `METADATA_*` checks (new check method beside `_check_inline_axons` :551).
- `ir/builder.py`: `fields["metadata"] = {…}` in `_nerve_to_ir` (:341, beside `declares_attributes` :393-394) and the cell/ganglion equivalents — authored map as a JSON object, omitted when absent.
- `codegen/python_emitter.py`: authored items APPEND to the existing dict literal AFTER the emitter-written items, in authored order, in `_build_nerve_metadata` :843, the ganglion block :1193+, the class-cell block :975+, and the constant/type blocks :1044/:1080 (collision already impossible at this point — rejected at validation).
- Runtime: zero work — `@component(metadata=…)` (core `decorators.py:51`, param :61) and `register_constant`/`register_type` (bridge :179/:248) already carry dicts to `ComponentSpec.metadata` (core `models.py:509`, field :533). Core is untouched (plan rule 11, anchor A-7).
- Tests at every stage + goldens + mcp rebuild per plan law 7.

---

## (b) `serves_as:` — the public serving name (L-2; closes friction items F-M2-2, F-M3-4, F-M4-2)

### Syntax

A bare identifier value on nerve declarations (quoted form also accepted by the scalar lexer; bare is canonical and what the quick reference shows):

```
nerve check_tool :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Validates .s0ma source without emitting artifacts — the agent's inner loop"
    serves_as: check
    evaluates_at: FUNCTION_BOUNDARY
    metadata:
        mcp_tool_annotations: ["readOnlyHint=true", "openWorldHint=false"]
    ---
    @_safe
    def check_tool(path: str | None = None) -> dict[str, Any]:
        ...
```

### Validation

- `SERVES_AS_INVALID`: value not identifier-shaped. (Served names that are NOT identifier-shaped — resource URIs — are exactly what `metadata: mcp_uri:` carries; `serves_as` is deliberately identifier-only because its emitted form must be a legal `__name__`.)
- `SERVES_AS_COLLISION`: two declarations carry the same `serves_as` value — validated per module (semantic phase) AND per project build (cross-module resolver phase), one flat namespace across all declarations carrying the field (L-2 fixes both scopes; conservative — can be relaxed post-evidence if distinct serving namespaces ever need the same name). Equality with the declaration's own identifier is permitted (harmless idempotent rename); equality with ANOTHER declaration's identifier is not this check's concern (the registry namespace is the declaration-name namespace and stays disjoint by construction).

### Emitter mechanics — exact placement (the F-M4-2 fix at the artifact level)

The emitter appends a two-statement stamp IMMEDIATELY after the decorated def's last body line, at module scope, separated by one blank line, BEFORE any subsequent emitted statement for the next declaration. Nerves emit only module-level defs/classes, so the `__qualname__` leaf is the whole `__qualname__` — the stamp is the plain form:

```python
@component(
    name="check_tool",
    ...,
    metadata={"visibility": "PUBLIC", "evaluates_at": "FUNCTION_BOUNDARY", "serves_as": "check", "mcp_tool_annotations": ["readOnlyHint=true", "openWorldHint=false"]},
)
@_safe
def check_tool(path: str | None = None) -> dict[str, Any]:
    ...

check_tool.__name__ = "check"
check_tool.__qualname__ = "check"
```

**Decorate-then-stamp ordering is the load-bearing invariant:** `@component` runs at def time and derives `qualified_name` from the symbol BEFORE the stamp executes, so `ComponentSpec` keeps the declaration identifier (registry/self disjointness per mcp ADR-001 is preserved), the module attribute (`exports:` / `__all__` / `tools.check_tool`) keeps the declaration name, and only the callable's `__name__`/`__qualname__` carry the served name — which is precisely what FastMCP's `func_metadata` reads for schema titles (F-M4-2). The IR records `fields["serves_as"]`; the emitted metadata records the reserved key `serves_as` so registry-deriving consumers (the mcp bootstrap bridge) read the served name without IR access. Spec §4.10 documents the stamp explicitly (risk register: introspection consumers must learn `__name__` ≠ attribute name when `serves_as` is authored).

Touch list: parser scalar field in `_build_nerve` :3340 region; `NerveDecl.serves_as: str | None = None` (:405 region); module-scope validation in `semantic/validator.py` + project-scope in `resolver/dependency.py`; `ir/builder.py` `_nerve_to_ir` :341 (`fields["serves_as"]`); `codegen/python_emitter.py` — reserved-key write in `_build_nerve_metadata` :843 + stamp emission in the nerve emission path (decorator assembly :723-727/:775-783); TextMate; spec; goldens; mcp rebuild. mcp dogfood note for M1: the bootstrap factory's `_served_as` rename becomes redundant for converted declarations — recommended disposition is keep it as an idempotent guard for any handwritten binding (it is exactly parallel to `normalize_docstring`), record the call either way.

---

## (c) Deferred imports — `deferred_requires:` (L-3; closes friction item F-M3-1, top-10 #6)

### Syntax — a sibling requires-family field, not a per-entry marker

The verified house pattern for "imports with different treatment" is a sibling module-header list with identical entry grammar: `soft_requires:` (try/except wrapping, POST-10j) and `runtime_only_requires:` (vestigial-exempt, POST-10b). `deferred_requires:` joins the family — same entry grammar (`module`, `module.Name`, colon-override `pkg:name`, `as` aliases, inline and block-list forms), parsed by the same `_build_requires` machinery (`parser/s0ma_parser.py:3294`, raw fields at :3181-3193):

```
module tools
    layer: PRESENTATION
    version: 0.8.0
    intent: "MCP tool surface; dsl/core machinery imports are deferred so the server starts degraded and fails per-call"
    requires: [json, typing:Any, typing:cast]
    deferred_requires: [s0ma_dsl.cli.main:S0maCLI, s0ma_dsl.runtime:bootstrap_imports, s0ma:get_registry]
    exports: [check_tool, _run_cli]
```

**The homonym note:** `deferred:` already exists as a DECLARATION field (POST-12f stub marker, `NerveDecl.deferred` :488 / `CellDecl` :628 / `GanglionDecl` :718, reserved metadata key). The field name `deferred_requires:` reads unambiguously against it ("requires, deferred"), while the IR keeps L-3's fixed `deferred: true` flag on import entries — a different record family (imports, not component fields), so no structural collision; spec prose must keep "deferred declaration (stub)" and "deferred import" terminologically distinct.

### Emission shape

Entries in `deferred_requires:` emit NOTHING at module top. For each emitted def whose AUTHORED body references an entry's bound name (the same body-reference evidence the vestigial machinery uses), the emitter injects the import statement at the top of that def's body — after the docstring when present (PEP 257; `__doc__` unaffected), before the first authored statement; multiple consumed entries form one contiguous block in `deferred_requires:` entry order:

```python
@component(...)
def check_tool(path: str | None = None) -> dict[str, Any]:
    """Validate .s0ma source WITHOUT emitting output — your inner loop."""
    from s0ma_dsl.cli.main import S0maCLI
    ...authored body...
```

Python caches modules in `sys.modules`, so the per-call cost after the first success is one dict lookup; on a broken environment each CALL raises `ImportError` inside the body — which the `@_safe`-style boundary converts to a structured failure. That is the F-M3-1 "start degraded, fail per-call" semantics, restored as an authored choice. The static dependency record stays COMPLETE: Phase-3 importability checking (`MISSING_PACKAGE`) applies to deferred entries unchanged.

### Diagnostics

- `BARE_IMPORT` (`parser/body_extractor.py:733/:748`) — the law is UNCHANGED for authored in-body imports; its remediation text gains the deferred option ("add a `requires:` entry, or a `deferred_requires:` entry if you want the import deferred to call time with per-call failure semantics"). No validator carve-out is needed for the injected imports: validation runs on authored source; injection is a post-validation emitter step.
- `VESTIGIAL_IMPORT` (`resolver/dependency.py:891/:954/:982`) — deferred entries use the SAME body-reference evidence rule as `requires:` entries. An unconsumed deferred entry is vestigial by construction (no import would be emitted anywhere); severity ladder unchanged. They are NOT `runtime_only_requires`-exempt — a deferred entry with no consuming body is always a mistake.
- `DEFERRED_IMPORT_MODULE_SCOPE` (new, error in every mode): a deferred name is referenced from a module-scope execution position — a CONSTANT/TYPE cell body, a class-cell body at class scope (field defaults execute at class creation), or a decorator expression on any emitted def. Deferring those imports is semantically impossible (the name is consumed at import time); the remediation says "move the entry back to `requires:` or restructure the consumer into a function body".
- `DUPLICATE_REQUIRES_ENTRY` (new, error in every mode; fits the verified `DUPLICATE_*` family): the same import target appears in `deferred_requires:` and any other requires-family list of the same module header. `soft_requires` + `deferred_requires` combinations are inexpressible in v1 — softness at module top and deferral to call time are different failure-time choices; pick one (rejected alternative below).

### IR shape (rides (g))

`ModuleImports` gains a fourth list, `deferred_requires`, built in `ir/builder.py::_build_imports` (:722-786) exactly parallel to `soft_requires`/`runtime_only_requires`; each serialized entry carries the same `{module_path, alias, is_from_import}` shape PLUS `"deferred": true` (L-3's self-describing flag, present so consumers reading flattened entry lists keep the fact without knowing the list name). Entries in the other three lists do NOT gain a `deferred: false` key — omitted-means-false keeps existing IR bytes unchanged (L-7).

Touch list: `parser/s0ma_parser.py` :3181-3193 (fourth raw field) + `_build_requires` reuse; `ast_nodes/nodes.py` `ModuleHeader.deferred_requires` (:362-389 region, beside `runtime_only_requires` :389); `parser/body_extractor.py` :733-748 remediation text; `resolver/dependency.py` vestigial evidence wiring + `DUPLICATE_REQUIRES_ENTRY` + `DEFERRED_IMPORT_MODULE_SCOPE` (module-scope reference scan); `ir/schema.py` `ModuleImports` + `ir/builder.py` :722-786; `codegen/python_emitter.py` import-block assembly (~:435 region where soft_requires wrapping lives) + per-body injection in the def emission paths; `config.py` severity/description registries + `common_errors.md` regen; TextMate; spec §4.5/§4.7; tests incl. the broken-dependency fixture (M2 acceptance: import-time success, per-call structured failure).

---

## (d) Qualified in-project `depends_on:` targets (L-4; closes the in-scope core of F-M1-4/F-M2-3, top-10 #7)

### Syntax — dotted, one level, matching every existing qualified component reference

```
nerve author_module_prompt :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Renders the author-a-module journey prompt with the client's arguments substituted"
    serves_as: author_module
    depends_on:
        AUTHOR_MODULE_TEMPLATE: {relation: READS, carries: "journey prompt copy", coupling: TIGHT}
        tools.scaffold_module_tool: {relation: CALLS, carries: "referential journey edge — the rendered copy instructs the agent to call scaffold_module", coupling: LOOSE}
    ---
    def author_module_prompt(project_root: str, module_name: str) -> str:
        ...
```

The qualified form is `module.declaration` — exactly one dot, because module names are flat (ADR-006); deeper dotting is a parse error. The dot is the established s0ma-component-space qualifier everywhere the language crosses modules: `uses: [routing.select_evaluator]`, cross-module `tests:` targets (`MISSING_TEST_COVERAGE` remediation emits `{mod_name}.{nerve.name}` at `resolver/dependency.py:1543`), and standalone axon targets (dotted targets already resolve via `_resolve_axon_target`, `python_emitter.py:1133-1161`). The colon stays what it is today: the PYTHON-import override marker on the `requires:` side of the §4.6.4 self-awareness boundary (rejected alternative below — the plan's "existing colon convention is the candidate" was evaluated and declined for boundary-consistency reasons).

### Grammar — definitive: `grammar.lark` changes

`depends_on_entry: NAME ":" "{" depends_on_fields "}"` (:34 of the 133-line grammar) parses the target as a single `NAME` token; the qualified form does not fit. The rule becomes `depends_on_entry: dep_target ":" "{" depends_on_fields "}"` with `dep_target: NAME ("." NAME)?` — LALR(1)-clean (the existing `entity_ref`/`field_path` rules already use the identical `NAME ("." NAME)*` shape). The `_FieldValueTransformer.depends_on_entry` handler (`s0ma_parser.py:2458`) joins the segments back into the target string; `InlineAxon.target` (nodes.py :305-312) stays a plain string now carrying either form. This is the ONLY lark change in the whole plan (anchor A-1's prediction confirmed).

### Resolution rules (project builds) and diagnostics

1. A dotted target `m.d` must name a module `m` in the project's module set, else `DOES_NOT_EXIST` naming the qualified form as authored and listing the project's module names.
2. `d` must be a declaration in `m`, else `DOES_NOT_EXIST` (same shape as the existing :635 in-module message, qualified variant).
3. `d` must appear in `m`'s `exports:` — the same public-surface rule as `uses:` Phase 2, reusing `NOT_EXPORTED`.
4. The edge joins Phase-1 module-graph construction with the same fatal-cycle rule as `uses:` (§4.6.1's "uses covers all cross-module s0ma references" extends to this form — a cycle in declared architecture edges is structural entanglement regardless of emission).
5. The cross-layer reachability matrix applies unchanged (`CROSS_LAYER_DEPENDENCY` — no new layer policy; plan §1.5 keeps the layer model closed).
6. A self-module-qualified target (`tools.x` authored inside `tools`) resolves as the local declaration (idempotent, permitted).
7. Synthetic/single-module invocations: dotted targets fail step 1 by construction (no project module set) → `DOES_NOT_EXIST` whose remediation says qualified targets require a `[tool.s0ma]` project build.
8. Evidence rules (§4.6.3) are unchanged and target-location-agnostic: the relation still determines the evidence. Referential edges whose evidence lives in embedded template DATA rather than the body keep `metadata:` as the documented carrier (plan M2 step 5b: convert `mcp_dependency` entries to qualified `depends_on:` only where the relation's evidence is honestly satisfiable; URI/catalog-shaped targets stay metadata).

Cross-PACKAGE targets remain inexpressible (plan §1.5 — not reopened here).

### Emitted and IR forms

The emitted decorator's `dependencies=[…]` (assembled at `python_emitter.py:809-812`) carries the canonical `module::declaration` string for qualified targets (the registry's canonical-ID alphabet, matching `register_relationship` targets and `_resolve_axon_target`'s dotted→`::` conversion); unqualified local targets keep today's bare-name strings byte-identically (L-7). The IR's inline-axon/edge records likewise canonicalize qualified targets to `module::declaration` — a value-space widening of existing string fields, not a schema-field change.

Touch list: `parser/grammar.lark` :34-38 (+ `dep_target`); `parser/s0ma_parser.py` :2458 transformer + `_parse_depends_on_entry` :2666 (call site :5134); `semantic/validator.py` `_check_inline_axons` :551-635 (dotted branch routes to project-set resolution instead of the local namespace check); `resolver/dependency.py` (project-phase resolution, `NOT_EXPORTED` reuse, module-graph edge); `ir/builder.py` canonicalization; `codegen/python_emitter.py` :809-812; spec §4.6/§4.11/§8; TextMate unaffected (field name unchanged); tests incl. a two-module fixture proving resolution, `NOT_EXPORTED`, cycle fatality, and the synthetic-invocation arm.

---

## (e) `covered_by:` — external test-evidence credit (L-5; closes friction item F-M5-3, top-10 #5)

### Syntax

```
nerve check_tool :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Validates .s0ma source without emitting artifacts and returns structured diagnostics"
    covered_by: ["packages/s0ma-mcp/tests/test_tools.py — boundary-contract suite", "wheel smoke exercises the served surface end-to-end"]
    ---
    def check_tool(path: str | None = None) -> dict[str, Any]:
        ...
```

A bracketed list of non-empty strings — suite paths or rationale prose, authored-opaque (the language validates shape, never resolves the strings; honesty is the author's burden and the IR makes the claim auditable). Same list lexing as `declares_attributes:` values (quoted for anything beyond bare identifiers).

### Validation and release-gate semantics

- `COVERED_BY_EMPTY` (new, error in every mode): the field is present with an empty list, or any entry is empty/whitespace.
- The release-mode gate at `resolver/dependency.py:1496-1545` changes exactly one predicate: a PUBLIC nerve passes if `module::name` ∈ test-target set (today's rule) **OR** the nerve carries a non-empty `covered_by:`. The `MISSING_TEST_COVERAGE` remediation (:1538-1545) gains the third option ("…or declare `covered_by:` naming the external suite that covers it"). `covered_by:` does NOT inject synthetic test targets — the IR/registry keep "tested in-language" and "externally covered" distinguishable, which is the honest record F-M5-3 demanded (a gate satisfiable by never-executing tests is worse than no gate).

### Rendering and runtime ride

`covered_by` is emitted as a RESERVED metadata key (POST-12a/12f precedent: surface in the registered metadata so consumers introspect without re-parsing source) — this is what makes doc-ref rendering work, because the doc index builds from the registry snapshot, not the IR: `resolver/doc_resolver.py` `_FIELDS_BY_KIND` (:305-329) gains `covered_by` for nerve/cell/ganglion, the index builder surfaces it from `spec.metadata` (one special case beside the `module_short` extraction :227-228 — `ComponentSpec` has no `covered_by` attribute for the `getattr` walk), and `codegen/doc_emitter/markdown.py::_render_entity_summary` (:265-273) renders a `Covered by: …` line after the intent when present. The wrapper-import recipe (pytest collects imported `test_*` names) is documented at M2 in the doc-subsystem guide + quick reference as the blessed pattern alongside the field (plan-fixed; this ADR just names the homes).

Touch list: parser list field in the nerve/cell/ganglion builders; AST fields (`covered_by: tuple[str, ...] = ()`); `COVERED_BY_EMPTY` in `semantic/validator.py`; `ir/builder.py` `fields["covered_by"]`; emitter reserved-key write in the three metadata builders; gate predicate + remediation at `resolver/dependency.py:1496-1545`; `doc_resolver.py` :305-329/:223-235 + `markdown.py` :265-273; `config.py` registries + `common_errors.md`; spec §2.4 (:349 release row), §4.1/§4.2/§4.3 field tables, §4.8, §4.12; TextMate; tests incl. the M2 acceptance fixture (public nerve, no `tests:` coverage, `covered_by:` authored, `--mode release` passes; and the negative arm without the field).

---

## (f) Doc front-matter version field — DROP `transpiler_version` (F-M5-5 + M6 postscript)

**Decision: drop the `transpiler_version` field from rendered doc front matter.** `schema_version` (= `ir/schema.py` `SCHEMA_VERSION`, an honest name for the artifact-contract version, which this plan bumps to 2.1.0 anyway) remains the front matter's contract identity; the content-hash computation (`codegen/doc_emitter/content_hashes.py:128` stamps `TRANSPILER_VERSION` into every hash) is UNTOUCHED — the codegen-contract version still participates in drift detection, it just stops being a rendered field with a misleading name.

Why drop beats the alternatives (both weighed per the plan's M0 step 2(f) mandate):

- **Re-source from the distribution** (make it match the manifest): the M6 postscript proves a distribution bump currently churns exactly TWO committed files (`build.s0ma.json` `transpiler_version` + the `build.s0ma.pyi` "Produced by s0ma-dsl <version>." header) while `_built/docs/` churns ZERO. Re-sourcing trades that property away — every release would churn every rendered doc in every committed build for zero reader value. Consciously declined; the property is kept.
- **Rename** (e.g. `doc_contract_version`): keeps TWO stable constants in the front matter where `schema_version` already identifies the contract; more spec surface, no discriminating power for readers, and the one-time churn cost is identical to dropping.
- **Drop**: F-M5-5's own lead suggestion. Afterwards exactly ONE artifact field named `transpiler_version` exists (the manifest's, carrying the distribution version, consistent with the `.pyi` header's wording) — "one field name, one semantics" restored at GA. The front matter keeps a version field (`schema_version`); rendered docs churn ONCE (one deleted line per artifact; `content_hash` values unchanged because hash inputs are unchanged — M4 must verify this expectation when regenerating goldens).

Mechanics (owner: M4 step 3, per Appendix D): `codegen/doc_emitter/frontmatter.py` `_FIELD_ORDER` (:32-41) and `FrontmatterFields` (:44-72) lose the field/param; `renderer.py` call-site kwargs (~:142-196, six sites) and `html.py` (~:222-280, six sites) drop it; spec §4.12's front-matter contract table updates; `docs/_generators/common_errors.s0ma`-derived `_generated/common_errors.md` regenerates (its front matter carries the field today — verified); doc goldens regenerate; mcp rebuild per law 7 (the `_built/docs/` churn is the point and is CHANGELOGed). M7 note: after this decision a distribution bump still churns exactly the two files the M6 postscript enumerated.

---

## (g) IR 2.1.0 delta (anchor A-5 re-verified: `SCHEMA_VERSION = "2.0.0"` at `ir/schema.py:61`, `TRANSPILER_VERSION = "1.0.0"` at :62)

`SCHEMA_VERSION` bumps 2.0.0 → 2.1.0 ONCE, at M1, at `ir/schema.py:61`. All additions are additive (L-6; absent = not authored; consumers of 2.0.0 documents keep parsing 2.1.0 ones). `TRANSPILER_VERSION` does not change. The complete delta:

| Surface | New key | Shape | Lands |
|---|---|---|---|
| `components[].fields` | `metadata` | JSON object: identifier keys → string \| int \| float \| bool \| list-of-strings; authored order preserved; omitted when not authored | M1 |
| `components[].fields` | `serves_as` | string (identifier); omitted when absent | M1 |
| `components[].fields` | `covered_by` | non-empty list of strings; omitted when absent | M2 |
| `imports` | `deferred_requires` | list of import entries, same `{module_path, alias, is_from_import}` shape as `imports.requires`, each entry additionally carrying `"deferred": true`; omitted/empty when none | M2 |
| edge / inline-dependency target strings (existing fields) | — | value space widens to include canonical `module::declaration` ids for qualified targets; no schema-field change | M2 |

Entries in `requires`/`soft_requires`/`runtime_only_requires` do NOT gain `deferred: false` — omitted-means-false keeps every existing build's IR bytes unchanged (L-7). Expected mechanical churn at M1's rebuild (law 7): every committed `.s0ma.json` and every rendered doc front-matter `schema_version` line moves to 2.1.0 — including `packages/s0ma-mcp/_built/` and `docs/_generated/common_errors.md`; M1 must treat that diff as mechanical-only. Builder sites: `fields` dict writes beside :393-394; `_build_imports` :722-786; `ModuleImports` schema class in `ir/schema.py`.

---

## (h) Spec v0.17.0 — rename mechanics and section-by-section diff plan (PLANNED here; text lands in M1/M2/M4)

**Rename mechanics (M1, once — L-6 / anchor A-2 re-verified):** `git mv docs/s0ma-dsl-spec-v0.16.0.md docs/s0ma-dsl-spec-v0.17.0.md`; create the 198-byte breadcrumb stub at the v0.16.0 path mirroring the verified v0.15.0 stub format ("# Pointer / This spec has been superseded by […v0.17.0…] / scheduled for deletion in the release after 0.17.0"); update the GUIDE_DOCS `spec` entry's `filename:` + `source:` lines in `packages/s0ma-mcp/s0ma_src/resources.s0ma` (verified at :70-73); sync the `_docs` packaged copy under `packages/s0ma-mcp/src/s0ma_mcp/_docs/` (renamed file); mcp rebuild (the GUIDE_DOCS edit forces it anyway); update the v0.15.0 stub's pointer target or delete it per its own deletion schedule (M1's judgment, CHANGELOGed).

**Section diff plan** (v0.16.0 line anchors; M1 lands metadata/serves_as text, M2 lands deferred/qualified/covered_by text, M4 lands the (f) + doc-subsystem v1.1 text):

| Spec section (v0.16.0 anchor) | Change | Milestone |
|---|---|---|
| §2.4 Strictness Modes (:342-354) | release row: "all PUBLIC nerves must have tests" gains "or `covered_by:`" | M2 |
| §4.1 nerve (:437) | field table + prose: `metadata:`, `serves_as:` (cross-ref §4.10), `covered_by:` rows + examples | M1, M2 |
| §4.2 cell (:866) | field table: `metadata:`, `covered_by:` rows | M1, M2 |
| §4.3 ganglion (:1087) | field table: `metadata:`, `covered_by:` rows | M1, M2 |
| §4.5 module (:1410) | `deferred_requires:` subsection beside the POST-10b `runtime_only_requires` block (~:1500-1510), incl. the pick-the-right-field guidance paragraph extension | M2 |
| §4.6 Dependency Resolution (:1598) | qualified target resolution rules (the 8 rules under (d)); §4.6.2 error table rows; §4.6.3 note that evidence rules are target-location-agnostic | M2 |
| §4.7 Import Semantics (:1643) | deferred emission shape, per-call failure semantics, `BARE_IMPORT` remediation update, `DEFERRED_IMPORT_MODULE_SCOPE` | M2 |
| §4.8 test (:1724) | coverage-credit paragraph (tests: OR covered_by:) | M2 |
| §4.10 Component Identity (:1815) | `serves_as` — served identity vs declaration identifier; decorate-then-stamp; uniqueness scopes | M1 |
| §4.12 Documentation Declarations (:1937) | covered_by doc-ref rendering line; front-matter field table loses `transpiler_version` (decision (f)); M4 also adds the `module` predicate field + output base-dir rule per the plan | M2, M4 |
| §4.14 Build Output (:2405) | IR 2.1.0 delta table (per (g)); emitted metadata merge + reserved-key rule; the `__name__`/`__qualname__` stamp in emitted output; deferred in-body import shape | M1, M2 |
| §4.16 `s0ma check` (:2669) | the eight new diagnostic codes | M1, M2 |
| §8 Example (:2869) | the complete module example gains `metadata:`, `serves_as:`, `covered_by:`, `deferred_requires:`, and one qualified `depends_on:` entry | M2 |
| Appendix A Field Reference (:2978) | rows for the four new fields + the qualified target form note on `depends_on` | M1, M2 |

Companion doc surfaces riding the same milestones (law 8 `_docs` sync each time): quick reference field tables; `config.py` `SEVERITY_MATRIX`/`OUT_OF_MATRIX…`/`ERROR_CODE_DESCRIPTIONS` + regenerated `docs/_generated/common_errors.md` (ADR-010 pipeline); the TextMate grammar (below); patterns guide (M2: wrapper-import recipe; M4 per plan).

---

## Field-to-declaration-kind applicability matrix

| Field | nerve | cell | ganglion | axon | helper | test | integration | doc-ref / doc-guide / example |
|---|---|---|---|---|---|---|---|---|
| `metadata:` | yes | yes | yes | no | no | no | no | no |
| `serves_as:` | yes | no | no | no | no | no | no | no |
| `covered_by:` | yes | yes | yes | no | no | no | no | no |
| `deferred_requires:` | — module-header field (all declaration bodies may consume its entries, subject to `DEFERRED_IMPORT_MODULE_SCOPE`) | | | | | | | |
| qualified `depends_on:` target | inherits `depends_on:`'s existing kind set unchanged (nerve :437, ganglion :703, test :748 in `nodes.py`); standalone axons already accept dotted targets today | | | | | | | |

One-line rationale per row:

- `metadata:` nerve/cell/ganglion: these are exactly the kinds whose emitter already writes a runtime `metadata=` dict (verified five emission shapes) — the merge is mechanical and L-1's parser→runtime flow is real, not partial.
- `metadata:` axon: `register_relationship` carries no metadata parameter (bridge :312) and edges are not ComponentSpecs — a runtime carrier would be a core change (plan rule 11).
- `metadata:` helper: helpers deliberately register nothing (emitter :1293 — IR-visible, registry-invisible by design); an IR-only field would break L-1's flow promise and the kind's privacy stance.
- `metadata:` test: `register_test` accepts no metadata (bridge :376, core registry.py:1076) — runtime carrier requires core work; no evidenced need (every friction entry concerned served/registered components).
- `metadata:` integration: the emitter stamps a fixed three-key dict on four auto-emitted helpers — authored-merge semantics are ambiguous (which helper?) and unevidenced; the free-form `manifest:` map already carries arbitrary authored keys for integrations.
- `metadata:` doc-*: doc declarations register render targets, not components; no metadata surface exists, no evidence.
- `serves_as:` nerve-only: every served surface in evidence (resources F-M0-7, prompts F-M2-2, tools F-M3-4/F-M4-2) is a nerve, and the stamp needs an emitted module-level callable with a meaningful `__name__`.
- `covered_by:` nerve/cell/ganglion: the release gate reads PUBLIC nerves; cells/ganglions accept it as honest coverage documentation riding the same IR/metadata/doc-ref path ("broad" per plan), and the gate simply does not consult them.
- `covered_by:` test: a test declaring itself externally covered is circular; doc-*/axon/helper/integration: not coverage subjects.
- `deferred_requires:` module-header: the requires family is module-level by construction; per-declaration import scoping exists nowhere in the language and the consuming-body analysis makes per-declaration placement automatic anyway.

---

## TextMate additions (anchor A-12 re-verified — file is repo-root `editors/s0ma.tmLanguage.json`, NOT under `packages/s0ma-dsl/`)

The line-87 explicit field alternation gains four names: `covered_by` (between `coupling|` and `covers`), `deferred_requires` (placed BEFORE `deferred` — `…|dataclass_invariants|declares_attributes|deferred_requires|deferred|demonstrates|…` — alternation order spares the engine a backtrack even though the trailing `(:)` lookahead would disambiguate), `metadata` (between `manifest|` and `mocks`), `serves_as` (between `sections|` and `smoke_test_primary`). `depends_on` and the unknown-field fallback (:94) are untouched. The comment on :84 ("harvested from spec v0.16.0") updates to v0.17.0 in the same M1 commit.

---

## The mcp `mcp_*` conversion mapping (input to M1 step 4 / M2 step 5)

| Today (`declares_attributes` namespace) | Becomes |
|---|---|
| `mcp_uri:s0ma://guide/system-prompt` | `metadata:` → `mcp_uri: "s0ma://guide/system-prompt"` |
| `mcp_mime_type:application/json` | `metadata:` → `mcp_mime_type: "application/json"` |
| `mcp_tool:check` | `serves_as: check` |
| `mcp_prompt:author_module` | `serves_as: author_module` |
| `mcp_prompt_title:Author a new s0ma module` | `metadata:` → `mcp_prompt_title: "Author a new s0ma module"` |
| `mcp_tool_annotations:readOnlyHint=true` (×N entries) | `metadata:` → `mcp_tool_annotations: ["readOnlyHint=true", …]` (one list; the bridge keeps its frozenset field-name validation + one `=` split — L-1 excludes nested maps, so the `field=bool` strings stay, and the seven per-namespace prefix parsers still all die) |
| `mcp_dependency:scaffold_module` (in-project declaration target) | qualified `depends_on:` entry (M2), where the relation's evidence is honestly satisfiable |
| `mcp_dependency:s0ma://guide/quick-reference` (URI/catalog-shaped) | `metadata:` → `mcp_dependency: ["s0ma://guide/quick-reference", …]` (the language cannot and should not spell catalog names) |
| (restored, F-M3-3) | `metadata:` → `composes: [project_status, run_example]` on the orchestrating tools; `wraps: "s0ma_dsl.cli.main.S0maCLI"` on `_run_cli` |

`declares_attributes` itself remains a valid generic field (L-6) — only the mcp namespace convention migrates.

---

## Rejected alternatives (recorded with reasons; plan-level exclusions not reopened)

1. **Per-entry deferred marker** (`requires: [x deferred]`, `requires: [x: {deferred: true}]`, or a `deferred:` prefix): the verified house pattern for import-treatment variants is the sibling list field (`soft_requires` POST-10j, `runtime_only_requires` POST-10b — "same grammar as requires:"); entry-suffix forms need new entry lexing for zero expressiveness gain; a `deferred:` PREFIX form would collide with the colon-override's `module:name` reading; and the existing `deferred:` declaration field (POST-12f stub marker) makes a bare `deferred` token inside entry lists ambiguous to human readers. The field-level marker IS the concrete syntax of L-3's "deferred marker"; the IR keeps L-3's per-entry `deferred: true` flag verbatim.
2. **Colon-form qualified `depends_on:`** (`tools:check_tool`, the plan's named candidate): declined — the colon marks the Python-import boundary (requires colon-override), while every existing qualified s0ma-component reference is dotted (`uses:`, cross-module `tests:` targets, standalone axon targets); one qualifier per side of the §4.6.4 self-awareness boundary.
3. **`uses:`-only cross-module edges** (no qualified depends_on; author `uses: [tools.check_tool]` + a local-name entry): mechanically possible today but L-4 ships the direct form by plan-level decision; the two-step shape splits one architectural fact across two header locations and the friction evidence (F-M2-3) wants the edge authored at the declaration it belongs to. `uses:` remains the right tool when the BODY also consumes the symbol.
4. **Inline `metadata: {k: v}` one-line form**: deferred, not rejected forever — block-only matches the `manifest:` precedent, keeps the parser addition minimal, and can be added additively if authoring evidence demands it.
5. **Nested metadata maps / null values / non-string lists**: plan-level out (L-1); the integration `manifest:`'s wider JSON-primitive set is deliberately NOT inherited — `metadata:` is a registration-surface contract, and the flat shape keeps every consumer (IR readers, the emitted dict, `ComponentSpec.metadata` introspection) trivially total.
6. **Per-kind reserved-key sets** (allow `scope` in nerve metadata since only ganglions write it): declined — the union rule is predictable for authors, costs nothing in evidence (no friction-log key collides), and keeps the emitter free to extend any kind's emitted keys without a compat break.
7. **`metadata:` on tests via a core `register_test` metadata parameter**: core is out of scope by plan rule 11; revisit only with evidence.
8. **Re-source or rename the front-matter `transpiler_version`**: per (f) — re-sourcing trades away the no-churn-on-release property the M6 postscript prices; renaming keeps a redundant second constant.
9. **Cross-package dependency edges and per-declaration layer overrides**: excluded at plan level (§1.5), not redesigned here; the in-module ADAPTER re-layer recipe gets documented in M4's patterns-guide work per the plan.

---

## Anchor verification record (vs plan Appendix A, re-verified 2026-06-11 on `9aa0a32`)

All sixteen rows substantively hold. Deltas found, none blocking: **A-3** — `_parse_attribute_list` def is at `s0ma_parser.py:2865` (row's :2868 is its docstring) and `_require_field` is DEFINED at :5146 (the row's :3347-3350 is its call region inside `_build_nerve`); **A-4** — the depends_on `DOES_NOT_EXIST` production emits at `semantic/validator.py:635` (row said :634); **A-6** — the nerve reserved-key reality is 11 keys (the row's "visibility :847, evaluates_at" were examples; the full verified per-kind enumeration is in (a) above), and `metadata=` is emitted at SEVEN sites across five emission shapes, not only the nerve path; **A-12** — the TextMate grammar is at repo root `editors/s0ma.tmLanguage.json` (the row's path reads package-relative); **A-14** — re-measured 217 errors / 21 of 53 files with an identical histogram, but `cli/main.py` counts 32 (row said 35; total unchanged — three errors sit in other files). A-1, A-2, A-5, A-7, A-8, A-9, A-10, A-11, A-13, A-15, A-16 verified exactly as written.
