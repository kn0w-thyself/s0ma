# Architecture Decision Records

This directory holds the load-bearing architectural decisions made during the
s0ma DSL transpiler's development. Each ADR follows the same shape — Status,
Date, Context, Decision, Rationale, Consequences, Alternatives Considered —
and serves as the durable rationale for a choice that future contributors
must understand before they can safely change it.

ADRs are append-only. When a decision is superseded, write a new ADR that
references the prior one in its `## Context` and updates the prior one's
`Status` line.

## Index

| # | Title | Date | Triggering work | One-line summary |
|---|-------|------|-----------------|------------------|
| [001](ADR-001-build-pipeline.md) | Six-Stage Build Pipeline | 2026-03-08 | Pre-feedback Milestone 2 (architecture decisions) | The transpiler is six staged passes (Parse → AST → Semantic → Derived edges → Codegen → Output); each stage has a well-defined input/output contract so grammar, semantic, and cross-module rules stay separable. |
| [002](ADR-002-runtime-expansion.md) | Runtime Expansion & Backwards Compatibility | 2026-03-08 | Pre-feedback Milestone 2 | The s0ma runtime gains new registration functions (`register_module`, `register_constant`, `register_type`, `register_relationship`, `register_test`) additively; existing `@component` decorators and registry semantics are unchanged so handwritten `.py` modules coexist with transpiled `.s0ma` modules. |
| [003](ADR-003-source-map-format.md) | Custom `.s0ma.map` Source Map Format | 2026-03-08 | Pre-feedback Milestone 2 | A custom JSON-based source map (declaration-level + line-level) ships per module; we do not adopt the JavaScript Source Map v3 spec because the transpiler's needs are runtime-traceback-mapping and compiler-debugging, not browser DevTools. |
| [004](ADR-004-separate-project.md) | Transpiler as Separate Sister Project — **SUPERSEDED** | 2026-03-08 | Pre-feedback Milestone 2 | **Superseded 2026-08-28: reversed by the 0.5.0 monorepo consolidation — do not follow it.** As decided: the transpiler lives in its own repo (`kn0wthyself/s0ma-dsl`) alongside the s0ma framework (`kn0wthyself/s0ma`) rather than as a subpackage, keeping tooling concerns separable from the runtime's library concerns. Since 0.5.0: one monorepo, one uv workspace, lockstep versions, no editable sibling install — see the ADR's Status line for current truth. |
| [005](ADR-005-project-discovery.md) | Declarative Project Discovery via `[tool.s0ma]` | 2026-04-28 | Feedback 5–6 plan, M1 | Every CLI subcommand resolves a `S0maProject` (source roots, test roots, build dir, bootstrap files) from a `[tool.s0ma]` table in `pyproject.toml`; a synthetic-fallback warning replaces hard-erroring during the deprecation window. |
| [006](ADR-006-canonical-module-identity.md) | `module <name>` is the Canonical Module Identity | 2026-04-28 | Feedback 5–6 plan, M4 | The cache key, output filenames, and `uses:` import path all derive from the parsed `module <name>`, never from the source file's stem; a new `MODULE_NAME_STEM_MISMATCH` error fires at error severity in every strictness mode to keep the filesystem and the IR identity in sync. |
| [007](ADR-007-single-build-layout.md) | Single Flat Build-Output Layout | 2026-04-28 | Feedback 5–6 plan, M6a + M6b | `s0ma build` emits one flat directory per project (auto-emitted `__init__.py`, `<module>.py` / `<module>.s0ma.json` / `<module>.s0ma.map` per module, plus a `build.s0ma.json` manifest in M6b); the legacy `__s0ma_cache__/` and per-layer subdirs are gone, with `s0ma migrate-layout` shipping for one-shot upgrades. |
| [008](ADR-008-test-visibility.md) | `visibility: TEST` — A Third Declarative Visibility Level | 2026-04-28 | Feedback 5–6 plan, M8 | A new `TEST` value on the visibility enum lets test consumers (modules with ≥1 `test` declaration) reach a component cross-module while production callers cannot; the new `TEST_VISIBILITY_VIOLATION` error replaces the copy-paste-or-promote-to-`PUBLIC` workarounds without introducing a friend-annotation surface. |
| [009](ADR-009-canonical-body-storage.md) | Canonical Body Storage — Dedent Once, At Parse Time | 2026-04-29 | Feedback 5–6 follow-up plan, F1 | Every declaration body is dedented exactly once at parse time by `parser.body_extractor.extract_body`; the canonical (column-0, Python-ready) form is stored on the AST node as `body` and is the single source of truth for every downstream consumer (validator, codegen, IR, derived edges, source map, doc subsystem). Duplicate `_dedent_body` helpers in codegen and derived_edges, and the validator's `textwrap.dedent` calls, were deleted; the M17 `CONSTANT_NAME_MISMATCH` false-positive on multi-line CONSTANT bodies (M20 finding #1) is closed. |
| [010](ADR-010-derived-doc-targets.md) | Derived Doc Targets — `doc-ref covers: { source: <name> }` Sub-Key Form | 2026-04-29 | Feedback 5–6 cleanup plan, G7a + G7b | The `doc-ref` `covers:` field is a discriminated union: the historic bracketed list of filter expressions targets project entities; a new sub-key dictionary form `covers: { source: <name> }` targets derived non-component registries (today: `error_codes`). The brace form is the structural discriminator (rejected over a polymorphic bare-string sentinel); future sources are additive via a one-line `_DOC_REF_COVERS_SOURCES` extension plus a renderer branch. G7b cuts the hand-authored Common Errors table over to a bracketed-region copy of the rendered output, regenerated via `make docs-derived` and pinned by two meta-tests against the live renderer. Sets the canonical grammar precedent for future "derived docs from non-entity registries" patterns. |
| [011](ADR-011-declaration-metadata-and-language-surface-batch.md) | First-Class Declaration Metadata & the 0.8.0 Language-Surface Batch | 2026-06-11 | DSL improvements plan, M0 (friction log §FINAL items 1/2/5/6/7/8) | The five-field language batch from the mcp self-hosting friction log: `metadata:` (block-map declaration field merged into the emitted registration dict, 27-key reserved set), `serves_as:` (public serving name with `__name__`/`__qualname__` stamping after the decorated def), `deferred_requires:` (sibling requires-family field emitting per-call in-body imports), qualified dotted `depends_on:` targets (in-project cross-module edges, one grammar.lark change), and `covered_by:` (external test-evidence credit for the release coverage gate). Also fixes the doc front-matter version-field decision (drop `transpiler_version`), enumerates the IR 2.0.0 → 2.1.0 additive delta, and plans the spec v0.17.0 diff. |

## How to write a new ADR

1. Pick the next number. Names are kebab-case; the title goes in the
   `# ADR-NNN: <title>` heading and a short kebab-case form goes in the
   filename (e.g. `ADR-009-foo-bar.md`).
2. Copy the header structure from any existing ADR (Status / Date / Context /
   References).
3. Lead with `## Decision` — readers should see the conclusion first.
4. Fill `## Context` with the problem this ADR resolves. Cite feedback,
   PRs, or empirical evidence where possible.
5. Use `## Rationale` for the *why* — this is the durable artefact future
   readers come back for.
6. Spell out `## Consequences` (positive and negative).
7. Enumerate `## Alternatives Considered` and the reason each was rejected.
   Future readers proposing the same alternative should find their
   counter-argument here.
8. Append a row to the index above.
