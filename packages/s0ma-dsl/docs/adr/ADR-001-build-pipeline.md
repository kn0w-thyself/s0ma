# ADR-001: Six-Stage Build Pipeline

**Status:** Accepted
**Date:** 2026-03-08
**Context:** Milestone 2 — Architecture Decisions & Spec Traceability
**References:** PRD §2.1.1 (build pipeline), §2.1.5 (IR-first core), DSL Spec §2.1

---

## Decision

The s0ma DSL transpiler implements a six-stage build pipeline:

```
Stage 1 — Lexer + Parser        (outer grammar + body extraction)
Stage 2 — AST Construction       (typed, frozen dataclass nodes)
Stage 3 — Semantic Validation    (intra-module + cross-module rules)
Stage 4 — Derived Edge Analysis  (RAISES + TYPE_USES derivation)
Stage 5 — Code Generation        (.py + .s0ma.json + .s0ma.map)
Stage 6 — Output & Registration  (write files, update cache)
```

## Context

The transpiler must enforce the DSL spec's rules at multiple levels: grammar-level (mandatory fields, separator rules), semantic-level (visibility invariants, namespace constraints, kind compatibility), cross-module (dependency resolution, export validation), and derived (RAISES/TYPE_USES edge inference). A single-pass approach cannot cleanly separate these concerns.

The PRD design principle P2 establishes enforcement priority: grammar-level > semantic-level > runtime. Staging the pipeline makes this hierarchy explicit and testable.

## Rationale

### Why six stages (not fewer)

- **Stages 1-2 (Parse → AST)** are separated because the outer grammar (Lark LALR(1)) and inner grammar (Python `tokenize` for body extraction) use different tools. Combining them into a single stage would conflate structural parsing with Python-aware body handling.
- **Stage 3 (Semantic Validation)** cannot run during parsing because some rules require the complete module AST (e.g., visibility/export consistency, duplicate detection, layer uniformity).
- **Stage 4 (Derived Edges)** is separated from Stage 3 because derived edge analysis operates on validated AST nodes and requires Python `ast` inspection of function signatures. It also depends on cross-module resolution results for canonical ID mapping.
- **Stage 5 (Code Generation)** consumes the validated, edge-complete semantic model. Separating it from validation prevents emitters from re-deriving semantics independently.
- **Stage 6 (Output)** handles file I/O, caching, and registration — concerns orthogonal to generation logic.

### IR-First Core Principle (PRD §2.1.5)

The semantic model / IR is the canonical internal truth. All downstream consumers — Python emitter, IR emitter, source map generator, runtime bridge — read from the same resolved semantic model produced by Stages 1-4. No consumer re-derives semantics independently.

This prevents a class of bugs where the Python emitter and IR emitter disagree on edge counts, canonical IDs, or namespace resolution.

### Why not more stages

We considered splitting Stage 3 into separate intra-module and cross-module phases. While they execute sequentially (intra-module first), they share the same validator infrastructure and error system. Making them separate pipeline stages would add coordination complexity without meaningful isolation benefit. Instead, they are sub-phases within Stage 3.

## Consequences

- Each stage has a well-defined input/output contract, enabling independent testing.
- The `check` CLI command can stop after Stage 3 (or Stage 4) without running code generation.
- Incremental recompilation (v2) can cache per-stage results.
- The pipeline ordering is a hard constraint: later stages may not feed information back to earlier stages.

## Alternatives Considered

1. **Single-pass transpiler** — rejected because it cannot cleanly separate grammar enforcement from semantic validation, violating P2.
2. **AST-free direct emission** — rejected because it prevents the IR-first architecture and makes determinism harder to enforce.
3. **Python-native parser (no Lark)** — rejected because the outer DSL grammar is not Python and benefits from a dedicated parser generator with `strict=True` LALR(1) guarantees.
