# ADR-010: Derived Doc Targets — `doc-ref covers: { source: <name> }` Sub-Key Form

**Status:** Accepted (G7a + G7b, feedback 5–6 cleanup).
**Date:** 2026-04-29
**Context:** Feedback 5–6 cleanup plan, Milestones G7a (grammar + renderer) and G7b (Common Errors table cutover).
**References:** [plans/5-6_cleanup_plan.md](../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_cleanup_plan.md) ("Milestone G7a", "Milestone G7b"), [ADR-005](ADR-005-project-discovery.md), [ADR-008](ADR-008-test-visibility.md), [ADR-009](ADR-009-canonical-body-storage.md), `docs/s0ma-dsl-spec-v0.13.0.md` §4.12.1 (`doc-ref` covers shapes), `docs/coding_agent_handbook.md` §9.11 (Derived docs internals), `docs/references/dsl_patterns_guide.md` §17.1 (`doc-ref` source-registry form).

---

## Decision

The `doc-ref` declaration's `covers:` field is a **discriminated union**. It accepts either:

1. The historic bracketed list of filter expressions targeting *project entities* (nerves / cells / ganglions filtered by `kind:`, `layer:`, `visibility:`, `where:` clauses). This is the shape every pre-G7a `doc-ref` used.
2. A new sub-key dictionary form `covers: { source: <name> }` targeting a **derived non-component registry** outside the project entity space. The renderer materialises the named registry into a deterministic Markdown table.

The first registered source name is `error_codes`. It pulls from the union of `SEVERITY_MATRIX` and `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`, joined with `ERROR_CODE_DESCRIPTIONS` (a hand-authored code → one-sentence-description mapping registered in `s0ma_dsl.config`). The renderer emits a Markdown table with columns `Code | Migration | Dev | Strict | Release | Description`, sorted alphabetically by code, with em-dashes in the four severity columns for codes that bypass the strictness ladder.

The two `covers:` shapes are mutually exclusive at parse time. A declaration that lists both bracketed filters and `source:`, or lists neither, fires `PARSE_ERROR` with a remediation pointing at the two clean shapes. The IR carries the discriminator on `IRDocRef`: the historic list-of-filters surface populates `covers: tuple[FilterExprAst, ...]`; the sub-key surface populates `covers_source: str | None`. Schema stays at 1.2.0 — the change is additive (the field gains a new variant; old IRs still parse; new IRs with `covers_source: None` round-trip identically to pre-G7a IRs because the JSON renderer omits the field when `None`).

The bracketed Common Errors region in `docs/s0ma-dsl_quick_reference.md` (G7b) consumes G7a's renderer output via the `make docs-derived` Makefile target. The s0ma-dsl repo does not itself carry a `[tool.s0ma]` table — it is the transpiler, not a project that consumes the transpiler — so the rendering invocation lives in the Makefile rather than in the project's build pipeline.

## Context

The post-G6 audit confirmed every error code literal in `src/s0ma_dsl/` was registered in either `SEVERITY_MATRIX` or `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`, and every registered code carried a row in `docs/spec_traceability.md`. But a third documentation surface — the Common Errors table in `docs/s0ma-dsl_quick_reference.md` — remained hand-authored: a curated subset of the registered codes, with a different column layout (`Code | Fix` two-column shape vs `docs/spec_traceability.md`'s longer-prose-per-row shape). Adding a new error code therefore required *three* coordinated edits — `SEVERITY_MATRIX`, `docs/spec_traceability.md`, and the quick reference's table. A forgotten edit on the quick reference produced silent doc drift that the meta-tests could only catch as a symptom (a missing traceability row), not as a root cause (the duplicated documentation surface).

The 0.11.0 doc subsystem was built precisely to retire this kind of duplication. `doc-ref` declarations enumerate "every PUBLIC nerve" or "every cell whose `kind:` is `MODEL`" and the renderer materialises a Markdown surface from the canonical project model. Pre-G7a, `doc-ref` only accepted *project entity* targets (filter expressions over nerves/cells/ganglions). The error-code registry is not a project entity; it is a derived fact about the transpiler itself, but it has the same documentation-duplication shape that `doc-ref` was designed to eliminate. M19c had logged this gap as an open question ("`target: error_codes` would let `doc-ref` cover the registry") deferred from the M19 series of follow-ups.

G1–G5 added new error codes to the registry. G6 audited the codes and registered the unregistered ones. G7's job was to close the documentation-duplication gap structurally — make the Common Errors table a derived artifact of the registry, not a hand-authored copy.

The grammar question — what shape should `covers:` take when the target is a non-component registry? — is the question this ADR resolves.

## Rationale

### Why this is structurally significant

The `covers:` field had a settled shape: a bracketed list of filter expressions, each targeting a project entity. Every pre-G7a `doc-ref` consumer (parser, renderer, IR builder, IR reader, every test fixture) assumed this shape. Adding a non-entity target type is the **first** structural extension to the field's grammar since 0.11.0 introduced `doc-ref`. The shape chosen now sets the precedent for every future "derived docs from a non-entity registry" pattern.

Future candidates already visible: rendering the `SEMANTIC_RULES` constant from the DSL spec generator, rendering the IR schema field reference from `ir_schema.py`, rendering the strictness-ladder semantics from `_compute_strictness_severity`. Each is a derived registry that lives in `s0ma_dsl.config` or a config-adjacent module. The shape of `covers:` for `error_codes` is the shape every future source uses.

The decision is therefore not "how do we render error codes?" — it is "what is the canonical grammar for derived doc targets?" — and is load-bearing for future toolchain evolution.

### Why the sub-key dictionary form (Option C) over alternatives

Three shapes were considered in the planning round (the cleanup plan §G7a step 4 names them as Alternatives A, B, C). The chosen shape is Option C; A and B were rejected.

**A — Keep hand-authored.** Reject the doc-subsystem extension entirely; document the Common Errors table by hand and rely on the meta-test to catch drift. Rejected on principle: pre-G7a's "duplicated documentation surface" was exactly the failure mode the doc subsystem was built to eliminate, and each new milestone (G1–G5) widened the gap. Hand-authoring scales linearly with code count; derivation is constant-cost.

**B — `covers: error_codes` polymorphic bare-string sentinel.** Extend the existing string-typed value space to admit a sentinel name. Rejected because bare-string sentinels overload the kind-name lookup space — pre-G7a, every value the parser sees for `covers:` is either a bracketed filter list or a kind name string. Adding `error_codes` as a third shape collapses the discriminator into a single string-comparison, forcing every future consumer (renderer, IR reader, future ADR-author) to encode "is this a kind name or a sentinel?" inline at every read site. The grammar becomes harder to extend (adding a fourth source means extending the sentinel allow-list with no syntactic change marking it as a sentinel) and harder to teach (readers can't tell from the field shape what target type is in play).

**C — `covers: { source: <name> }` sub-key form (chosen).** Make the discriminator structural rather than lexical: a brace-form value declares "this is a derived-source declaration"; the `source:` key names the registry; future keys (e.g. `format:`, `filter:`, `version_pin:`) are additive to the brace form without touching the historic list-of-filters shape. The discriminator is the brace form itself; readers can tell at a glance which target type the declaration uses.

The structural-correctness rationale aligns with the same pattern ADR-008 used for `visibility: TEST` (a discriminated value over a settled enum) and ADR-009 used for `body` / `raw_body` (a structured field separation that makes the consumer's intent explicit). The shape choice mirrors the codebase's standing convention: when a field's grammar admits two semantically distinct shapes, the discriminator is structural (brace form vs list form), not lexical (sentinel string vs kind-name string).

### Why `error_codes` is the only registered source today

`_DOC_REF_COVERS_SOURCES = frozenset({"error_codes"})` is a single-element allow-list. The single entry is intentional: G7's job is to close the Common Errors table gap, not to speculate about future sources. The allow-list shape (frozenset checked at parse time, with `PARSE_ERROR` on rejection) is extensible — adding a future source is a one-line constant edit plus a renderer branch — but each addition crosses an architectural review (does the registry's stable shape match the renderer's pivot expectations? does the rendered surface need different columns? is the registry stable enough that derived docs make sense?). G7a does not pre-commit to those reviews.

### Why `ERROR_CODE_DESCRIPTIONS` is hand-authored, not parsed from `docs/spec_traceability.md`

The renderer needs a code → human-readable-description mapping. Two sources were considered: hand-author in `s0ma_dsl.config` next to `SEVERITY_MATRIX`, or parse the description column from `docs/spec_traceability.md` at render time.

**Hand-authored (chosen).** Three reasons.

1. **The renderer must run without a docs-on-disk dependency.** Doc-subsystem renderers are pure functions of registry state, not of the documentation surface. Parsing markdown to render markdown introduces a circular shape (the documentation surface depends on its own parse) and couples the renderer to the host project's filesystem layout (the s0ma-dsl repo's docs path must be available; consumer projects rendering their own docs would need to vendor it). The pure-function-of-registry-state shape is the canonical invariant for every other doc-ref renderer; introducing a markdown-parsing dependency for a single source breaks the pattern.

2. **The two surfaces have different shapes.** `docs/spec_traceability.md` rows are multi-paragraph prose mixing trigger / remediation / spec-section / emit-sites in one cell, sized for an authoritative spec document. The Common Errors table needs one-sentence triggers — a quick-reference "what does this error mean?" gloss, not the full spec writeup. Reusing `docs/spec_traceability.md`'s prose would produce a quick reference that is dense and cross-referential, exactly the failure mode the quick reference is meant to avoid.

3. **The completeness pin is enforceable.** Two new meta-tests (`tests/test_doc_consistency.py::test_error_code_descriptions_match_severity_registries` and `tests/test_doc_ref_error_codes.py::test_error_code_descriptions_complete`) treat `ERROR_CODE_DESCRIPTIONS` as the canonical surface. Every code in `SEVERITY_MATRIX | OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE` MUST have a description; every key in `ERROR_CODE_DESCRIPTIONS` MUST be a registered code; no orphans in either direction. Both halves of the invariant are pinned at test time. A markdown-parsed alternative would have to pin the same invariant against a parsed-table shape, with the additional failure modes of malformed markdown, unstable column counts, and renderer-edits to the source.

### Why the bracketed-region cutover (G7b) inlines the rendered output rather than using a markdown include directive

The Common Errors table in `docs/s0ma-dsl_quick_reference.md` is replaced by an HTML-comment-bracketed region holding a copy of the rendered table portion of `docs/_generated/common_errors.md`. Two meta-tests pin the cutover: one re-renders the `doc-ref` at test time and compares against the bracketed region (catching drift between the registry and the quick reference); one pins the committed `_generated/` artifact to the renderer (catching a stale committed artifact that masks a registry edit).

A markdown include directive (e.g. `{{include docs/_generated/common_errors.md}}`) was considered and rejected. Markdown rendering is not standardised — GitHub's renderer, the agent-system markdown previewer, the spec preview pipeline, and the in-repo `make` documentation build each handle includes differently or not at all. Inlined content renders identically in every consumer; the bracketed-region-with-meta-test pattern is the portable equivalent of an include directive that every renderer respects.

The HTML comments themselves are markdown's portable hidden-content shape. Every renderer hides them from rendered output but preserves them in source. The marker carries the regeneration instruction inline (`<!-- BEGIN auto-generated common-errors-table; do not hand-edit; regenerate with `make docs-derived` -->`) so a future contributor reading the file in a vanilla editor sees the remediation without consulting a separate doc.

## Consequences

- **The first canonical grammar for derived doc targets exists.** Future sources (the SEMANTIC_RULES constant, the IR schema reference, the strictness-ladder semantics) can be added by a one-line `_DOC_REF_COVERS_SOURCES` extension plus a renderer branch in `codegen/doc_emitter/markdown.py`. No grammar change required.
- **Adding a new error code is now a one-edit change followed by `make docs-derived`.** Pre-G7, the workflow was three coordinated edits across `SEVERITY_MATRIX`, `docs/spec_traceability.md`, and the quick reference's Common Errors table. Post-G7, the canonical surface is the registry; derived surfaces are regenerated.
- **The IR schema gains an additive variant.** `IRDocRef.covers_source: str | None` is `None` for every pre-G7a IR; the JSON renderer omits the field when `None`; existing IR fixtures and content hashes are byte-stable. Schema stays at 1.2.0.
- **The s0ma-dsl repo carries a Makefile.** `make docs-derived` is the renderer-invocation entry point. The Makefile is intentionally minimal (one user-facing target plus `test` and `lint` aliases for ergonomic parity with `make docs-derived`). A future contributor adding a new derived doc adds a generator under `docs/_generators/` and the existing `make docs-derived` target picks it up.
- **The Common Errors table grew from ~20 to 58 rows.** The hand-authored table was a curated selection; the derived table covers every registered code. Per-mode severity columns let consumers answer "is this an error in dev?" with a column lookup instead of reading prose. Out-of-matrix codes render with em-dashes in the four severity columns since they bypass the strictness ladder.
- **Two meta-tests pin the cutover.** `test_common_errors_table_matches_doc_ref_output` and `test_common_errors_generated_artifact_matches_doc_ref_output`. Both fail with "regenerate via `make docs-derived` (or `s0ma docs render docs/_generators/ --output-dir docs/`)" remediation messages.
- **`docs/spec_traceability.md` remains hand-authored** and continues to carry the longer-prose per-row shape. The quick reference and the spec traceability serve different purposes; G7 explicitly does not consolidate them.

## Alternatives Considered

The cleanup plan §G7a step 4 names three alternatives (A, B, C above) and identifies C as the chosen shape. Three additional shapes surfaced during implementation review and are recorded here for completeness.

### Option D — Make `docs/spec_traceability.md` itself a derived `doc-ref` artefact (rejected — out of scope for G7)

The most ambitious shape: derive the spec traceability document from the registry too, using a different `doc-ref` source name (e.g. `covers: { source: error_codes_traceability }`). The per-row prose would need its own renderer branch (the table renderer is structurally the wrong shape for multi-paragraph rows).

**Why rejected:** the per-row prose layout doesn't fit the table renderer; would need a "long-form" or "section-per-row" renderer variant; the per-row prose is intentionally hand-authored at the spec-level abstraction (the rationale in each row is the kind of writing that needs a human author, not a derived emit-site list). The deviations log records this as the explicit out-of-scope decision for G7a.

### Option E — Two separate Markdown files (one per shape) instead of a bracketed region in the quick reference (rejected)

Emit `docs/_generated/common_errors.md` (the rendered artifact) and link to it from the quick reference instead of inlining the table.

**Why rejected:** the quick reference is the canonical lookup surface; sending readers to a second file for the most-asked-about table fragments the user experience. The bracketed-region-with-meta-test pattern delivers the same drift safety with the same single-page lookup surface.

### Option F — Generate a YAML / TOML / JSON intermediate, render Markdown from that (rejected)

Two-stage pipeline: registry → structured-data file → Markdown. The structured-data file would be the canonical machine-readable form; the Markdown is one of multiple downstream renderings.

**Why rejected:** premature generalisation. The doc subsystem already produces structured `_generated/<name>.json` outputs alongside the Markdown when invoked with the `format: json` field; the registry-as-canonical pattern doesn't need a third intermediate. Adding one introduces a synchronisation question (which renderer produces the canonical hash?) without offsetting benefit.

## Forward pointers

- **Future `covers: { source: <name> }` registrations** add to `_DOC_REF_COVERS_SOURCES` plus a renderer branch in `codegen/doc_emitter/markdown.py`. Each addition crosses an architectural review at the source level. The grammar is fixed; only the registry is extended.
- **A future "long-form section-per-row" renderer variant** (Option D revisited) would let the spec traceability document derive from the registry too. The grammar shape needed is the same brace form, with a `format:` key to discriminate `table` vs `section-per-row`. Out of scope for G7; tracked in the cleanup plan's "Out of scope" section as a future generalisation candidate.
- **Consumer-side derived docs** can use the same `covers: { source: error_codes }` shape today. The renderer is part of the published transpiler; the registry it consumes (`SEVERITY_MATRIX`, etc.) is part of `s0ma_dsl.config`. A consumer project's own `doc-ref` declaration with this shape produces the same Markdown table the s0ma-dsl repo produces — useful for projects that want to embed the s0ma error catalogue in their own documentation surface.
- **The `_generated/` prefix convention** is the human-readable marker for machine-output files. Future generators ship under `docs/_generators/` and emit under `docs/_generated/`. Both directories are committed; the `_generators/` source files are hand-authored, the `_generated/` artifacts are regenerated by `make docs-derived`. The meta-tests pin the artifacts to the renderer's current output, so a stale artifact fails CI loudly.
