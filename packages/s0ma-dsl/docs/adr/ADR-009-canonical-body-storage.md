# ADR-009: Canonical Body Storage — Dedent Once, At Parse Time

**Status:** Accepted (F1, feedback 5–6 follow-up).
**Date:** 2026-04-29
**Context:** Feedback 5–6 follow-up plan, Milestone F1 — Canonical dedented body single source of truth.
**References:** [plans/5-6_follow-up_plan.md](../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_follow-up_plan.md) ("Milestone F1"), [plans/feedback_5-6/feedback_5-6_smoke_results.md](../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/feedback_5-6_smoke_results.md) (M20 — Finding #1), [ADR-001](ADR-001-build-pipeline.md), [ADR-006](ADR-006-canonical-module-identity.md), `docs/s0ma-dsl-spec-v0.13.0.md` §4.5.5 ("Canonical body storage"), `docs/coding_agent_handbook.md` §1.3 ("Parse-time body dedenting").

---

## Decision

Every declaration body is dedented **exactly once, at parse time**, by `parser.body_extractor.extract_body`. The dedented form is stored on the AST node as `body` (or `python_body` for `ExampleDecl`) and is the **single canonical value** every downstream consumer reads — validator, codegen, IR builder, derived-edges analyzer, source map writer, and doc subsystem hash. The original raw text with the `.s0ma` source's leading indent preserved is kept on a parallel `raw_body` (or `raw_python_body`) field for diagnostics only.

The dedent strategy is: read the indentation of the first non-blank, non-comment line and strip that prefix from every subsequent line. Lines whose indentation is less than that prefix (e.g. column-0 trailing comments, or column-0 string content inside a multi-line literal) pass through unchanged. This strategy is the only correct one for `.s0ma` bodies because the body splitter may capture column-0 trailing comments and CONSTANT bodies routinely contain multi-line string literals whose interior is at column 0.

Production code paths must not call `textwrap.dedent`, `inspect.cleandoc`, or any hand-rolled dedent on a body. Calling them is a bug — they would either be redundant (the body is already at column 0) or actively wrong (`textwrap.dedent` collapses the common-prefix to the empty string when any line is already at column 0, leaving the still-indented assignment line for `ast.parse` to reject as `IndentationError`). The duplicate `_dedent_body` implementations in `codegen/python_emitter.py` and `semantic/derived_edges.py`, and the two `textwrap.dedent` call sites in `semantic/validator.py` (the M3 helper-collision check and the M17 constant-name check), are deleted as part of F1. The single source of truth is `parser/body_extractor._dedent_body`; one definition, one internal call site, no other live use anywhere in `src/s0ma_dsl/`.

## Context

Three milestones in feedback 5–6 introduced body-text analysis at validation time: M3 (helper-collision detection in `_extract_top_level_def_names`), M17 (CONSTANT cell name vs body identifier validation in `_body_top_level_assigned_names`), and M18 (attribute-budget walking, which reads body-derived call edges via `derived_edges.py`). Each landed independently; each implemented its own dedent strategy. By the end of M18 there were **three duplicate `_dedent_body` implementations in `src/s0ma_dsl/`**:

1. `parser/body_extractor.py:_dedent_body` (the original, anchor-on-first-non-blank-line).
2. `codegen/python_emitter.py:_dedent_body` (introduced for emission, identical strategy).
3. `semantic/derived_edges.py:_dedent_body` (introduced for derived-edge analysis, identical strategy).

Plus the two `textwrap.dedent` call sites in `semantic/validator.py`. Five different code paths each making their own decision about how to dedent a body.

The M20 smoke test against fr3d and kn0wthyself-website-2 surfaced the failure mode this fragmentation enables. Both consumer projects had at least one CONSTANT cell of the shape:

```
cell VizTemplate :: visibility: PUBLIC ---
    VIZ_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    ...
</head>
</html>
"""
```

The triple-quoted string's interior content is at column 0. The validator's M17 helper called `textwrap.dedent` on the raw body. `textwrap.dedent` requires a common leading-whitespace prefix on every non-blank line; finding none (the column-0 lines have no prefix), it returns the body unchanged. The still-indented assignment line `    VIZ_TEMPLATE = """...` then fails `ast.parse` with `IndentationError`, the helper swallows the parse error, and reports zero assigned names. The validator then concludes the cell name `VizTemplate` does not match its body's assignments and emits a spurious `CONSTANT_NAME_MISMATCH`. The codegen, meanwhile, dedented correctly using its own `_dedent_body` helper and emitted the constant correctly into the build artifact.

**Two pieces of code reading the same body, one rejecting it as malformed, one emitting it cleanly.** That is the canonical signature of a "no single source of truth" bug.

The post-M20 review enumerated seven options for the structural fix (Options A–G below). Option G — dedent once, at parse time, and have every consumer read the canonical form — was the only option that makes the failure mode unrepresentable. It is the option F1 implemented.

## Rationale

### Why "dedent once, at parse time" is the right architectural answer

**A) Unite code and information about code (Guiding Principle #1).** The dedented body is a derived fact about the source — readable by anyone who can read the AST. Pre-F1, every downstream consumer had to re-derive that fact, with different (possibly disagreeing) strategies. Post-F1, the AST node carries the fact directly. The IR's `body` field, the source map's line-offset math, the doc subsystem's content hash, and the validator's `ast.parse` invocation all see the same bytes. There is no possibility of the validator and codegen "disagreeing" about whether a particular body is malformed — they read the same value.

**B) Eliminate manual documentation (Guiding Principle #2).** Pre-F1, the rules around when to call `_dedent_body` (and which copy) lived as prose comments in the source files. Post-F1, the rule is structural: "downstream consumers consume `decl.body`, never re-dedent." There is nothing to remember; the wrong shape doesn't exist in the codebase.

**C) The hard right path, not the easy wrong path (Guiding Principle #4).** The easy fix would have been to swap `textwrap.dedent` for `inspect.cleandoc` in the validator (Option B below) — a one-line change that closes the M17 false-positive. That fix leaves three independent dedent paths in place, with no architectural pressure preventing the next divergence. The hard right path collapses the three paths into one and makes future divergence impossible.

**D) No silent failures (Guiding Principle #5).** Pre-F1, the validator's `try/except` around `ast.parse` swallowed `IndentationError` silently and reported zero assignments. The cell-name-mismatch diagnostic that resulted was a downstream effect of that swallowed error. Post-F1, the body comes pre-dedented and column-0; `ast.parse` either succeeds (the canonical case) or surfaces a real `PARSE_ERROR` at the parse phase, where it belongs. The failure mode that produced the M17 false-positive cannot recur — there is no `IndentationError` to swallow.

### Why parse-time is the right place

The parser already had the dedent helper (`body_extractor._dedent_body`), the right strategy (anchor-on-first-non-blank-line), and a natural moment to apply it (when assembling the AST node from the parsed body slice). The dedent had been latent in `body_extractor.extract_body`'s `BodyInfo` for several milestones — the helper produced both `source_text` (raw) and `dedented_text` (canonical), but downstream consumers ignored `dedented_text` and re-derived their own. F1 wires `dedented_text` into the AST node and removes the duplicates.

The alternative — defer the dedent to the first consumer that needs it (e.g. the validator's first call to `ast.parse`) — invites the same fragmentation: each consumer's "first need" runs at a different pipeline stage, with different invariants in scope, and the helper drifts. Parse-time is the unique earliest point where every downstream consumer can rely on the canonical value being available.

### Why `raw_body` is preserved (and why it's only for diagnostics)

The source map and certain error-reporting paths need to relate AST positions back to the original `.s0ma` source line, including the source's original indentation. Discarding the raw form would break those paths. F1 keeps the raw form on a parallel field (`raw_body` / `raw_python_body`) but explicitly scopes its use to diagnostics — error messages that quote the original source, source-map line offsets, and `s0ma inspect`'s "show me the original text" surface. Production code paths (analysis, codegen, IR serialization) must read `body`, never `raw_body`. The split surfaces in the field names so the rule is enforceable at code review.

### Why the duplicate `_dedent_body` copies were *deleted*, not just guarded

A guard ("call the canonical helper, but keep the local copy as a fallback") would re-introduce the fragmentation the structural fix eliminates. The hard right path is to remove the wrong shape from the codebase entirely — there is now exactly one `_dedent_body` definition (`parser/body_extractor.py`), one internal call site (within `body_extractor.extract_body`), and zero other live uses in `src/s0ma_dsl/`. A future contributor cannot accidentally call a stale copy; there is no copy to call.

## Consequences

- **One canonical body form.** Every downstream consumer reads the same bytes for any given declaration. Future consumers (a new validator pass, a new IR serializer, a new doc-subsystem renderer) cannot disagree about the dedent strategy because there is no choice to make.
- **The doc subsystem's content hash is now computed over canonical bodies.** The pre-F1 hash was computed over the raw, source-indented body via `decl.python_body`. Post-F1, `decl.python_body` is the canonical form. The hash for `tests/fixtures/golden/docs/walkthrough.md` (the only fixture with an embedded example) shifted from `1:f31e659c…` to `1:296208c1…`; the golden was regenerated in place as the documented invalidation event. No external consumer hashes are baked into this repo; consumer-side hashes recompute on the next `s0ma build`.
- **The IR's `body` field semantics shifted from "raw, with source indent" to "canonical, column-0".** The IR schema (1.2.0) keeps the same field name; only the bytes changed. Existing IR readers that round-trip the field see a Python-ready value and need no schema-aware migration. Tooling that *did* depend on raw-with-indent (none in this repo) now reads the new `raw_body` field.
- **Test fixtures that hand-built AST nodes were normalised.** Roughly 30 hand-constructed `NerveDecl` / `CellDecl` / `GanglionDecl` / `TestDecl` instances across `tests/test_codegen.py` and `tests/test_privileged.py` had `body="    def X():\n        ..."` (raw-indented). Those bodies were dedented in place to match the new contract. `tests/test_codegen.py:TestDedentBody` was redirected to import `_dedent_body` from `parser.body_extractor`. `tests/test_constant_name_validation.py:test_indented_body_is_dedented` was renamed to `test_canonical_body_parses_at_column_zero` because its premise (the validator does the dedent) is no longer true.
- **The M17 false-positive that fr3d and kn0wthyself-website-2 hit in the M20 smoke test is closed.** Pinned by the `tests/fixtures/m17_multiline_constant/m17_multiline_constant.s0ma` fixture (the exact `BIG_TEMPLATE = """\n<html>...` shape) and the five regression tests in `tests/test_canonical_dedent.py`.
- **Schema bump not required.** The IR's `body`/`python_body` field name and outer shape are unchanged; only the encoded bytes are now canonical. Schema stays at 1.2.0.
- **Forward-compatibility for future consumers is now structural.** Adding a new pass that needs to read a body — for example, a future `s0ma test`-time mutation analyzer or a new doc-subsystem reflection target — does not require a new dedent decision. Read `decl.body`. That's the rule.

## Alternatives Considered

The post-M20 review enumerated seven options. Each is summarized below with the reason for rejection.

### Option A — Extract `_dedent_body` to a shared utility module (rejected)

Move the parser's `_dedent_body` to `s0ma_dsl.utils.dedent` or similar; have the validator, codegen, derived-edges analyzer, and source map all import it from one place.

**Why rejected:** Solves the *implementation* duplication but not the *architectural* duplication. Every consumer would still call the helper at its own pipeline stage, with its own invariants in scope. A future consumer who did not know to import the shared helper would still write a new copy. The fragmentation pressure remains; the shared module just adds a layer of indirection. Moreover, "validator imports from codegen" or "codegen imports from validator" violates the Six-Stage Build Pipeline (ADR-001) layer separation; a shared `utils` module would have to live below both stages, which is exactly where the parser's helper already lives. Option G subsumes A by making the parser the single owner.

### Option B — Replace `textwrap.dedent` with `inspect.cleandoc` (rejected)

In the validator's two call sites, swap `textwrap.dedent(body)` for `inspect.cleandoc(body)`. `inspect.cleandoc` handles column-0 lines correctly (it's the docstring-cleaning helper used throughout the standard library) and would close the M17 false-positive in one line.

**Why rejected:** The easy wrong path. Closes the immediate symptom without addressing the architectural bug — three independent dedent paths still exist, each making its own decision, each able to drift. A future divergence (e.g. someone adds a fourth dedent path in a new pass) would be exactly as likely as the first three. Option B treats the M17 false-positive as a bug in *one* code path; F1 treats it as evidence that the architectural decomposition is wrong.

### Option C — Have the validator parse the codegen-generated Python (rejected)

Instead of dedenting the body and parsing it directly, run the body through codegen first (which already produces a clean, dedented `.py` artifact) and have the validator analyze the codegen output.

**Why rejected:** Inverts the pipeline (validation now depends on codegen, where ADR-001 puts validation before codegen). Defers semantic analysis until after a successful build, which means the validator can never report `CONSTANT_NAME_MISMATCH` in `s0ma check` on a project that fails to build for any other reason. Adds a circular dependency between two pipeline stages that should be linearly composed. Cure worse than disease.

### Option D — Hand-rolled token analysis in the validator (rejected)

Replace `ast.parse` in the validator's helpers with a hand-rolled tokeniser that is robust to indentation issues — find `IDENT = ...` patterns by token sequence rather than AST shape.

**Why rejected:** Reinvents `ast.parse`'s job, badly. The CPython tokeniser is the canonical Python lexer; reimplementing a subset of it inside the validator means maintaining a parallel grammar that the rest of the toolchain doesn't see. Any future Python feature (PEP 695 type parameters, PEP 701 nested f-string quotes, walrus operator extensions) requires a parallel update. The validator's job is "what does the Python compiler think this body says?" — `ast.parse` answers that question. The bug was upstream of `ast.parse`'s call site (the body wasn't column-0); fix the upstream, don't reimplement the downstream.

### Option E — Smarter dedent strategy ("if `textwrap.dedent` returns the body unchanged, fall back to anchor-on-first-line") (rejected)

Wrap the existing `textwrap.dedent` call with a heuristic: detect the no-op case and switch strategies.

**Why rejected:** Adds a heuristic to detect when the canonical strategy is wrong and switch to the right one. The right strategy was already known — the parser had it. The structural fix is to use the right strategy everywhere, not to add a heuristic that decides per-call. Heuristics drift; the explicit-is-better-than-implicit principle says: pick the right strategy, document it, use it everywhere.

### Option F — Validator imports the canonical helper from `parser/body_extractor` (partial rejected)

The validator and codegen import `_dedent_body` from the parser's body_extractor module directly.

**Why rejected:** Strictly closer to right than Options A–E, but still leaves the consumers responsible for *when* to dedent. A consumer that forgets to call the helper, or calls it twice, or calls it on the raw body when the canonical body is already available, is a bug shape that exists in F's world but not in G's. Option G eliminates the consumer-side decision entirely: there is nothing to call, the body is already canonical when the AST node is constructed.

### Option G — Single dedent at parse time; canonical body on the AST (chosen)

The parser dedents bodies exactly once, at parse time, when assembling the AST node. The dedented form is stored on the AST node as `body`; every downstream consumer reads `decl.body` directly. The duplicate `_dedent_body` implementations in codegen and derived_edges are deleted. The validator's `textwrap.dedent` calls are deleted.

**Why chosen:** Makes the wrong shape unrepresentable. There is no consumer-side dedent decision to get wrong. There are no duplicate helpers to drift. There is no "first call" to defer to. The canonical bytes flow through the entire pipeline from parse to emission. The infrastructure already existed (`body_extractor.extract_body` produced the canonical form on a `BodyInfo.dedented_text` field); F1's work is purely wiring that value into the AST node and deleting the duplicate paths that ignored it. Aligns with the Six-Stage Build Pipeline (ADR-001) layer separation: parse owns the body's canonical form, every later stage consumes it. Aligns with ADR-006's "single canonical identity" pattern: just as the module name is canonicalized once at parse time and every downstream stage reads the canonical form, F1 canonicalizes the body once at parse time and every downstream stage reads the canonical form. The architectural pattern is the same.

## Forward pointers

- **A future "private nested component" or "named body fragments" extension** would build on the canonical-body invariant: a fragment is identified by an offset into the canonical body, not the raw body. F1's `raw_body` field stays available for source-map round-tripping, but the analysis and codegen surfaces would consume the canonical fragments.
- **A future doc-subsystem `target: error_codes` extension** (M19c open question, deferred) would benefit from the canonical-body invariant: the error-code rendering would hash the canonical body of the validator's `SEVERITY_MATRIX` declarations, so the hash is stable across textwidth-of-the-source changes.
- **Source-map debugging tools** (ADR-003) continue to use `raw_body`-aware line math. F1 does not change the source-map format; the field rename (`body` → canonical, `raw_body` → raw) flows through the existing map-writer paths transparently.
