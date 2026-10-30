# s0ma DSL — Language Specification & Coding Agent Rulebook

**Version:** 0.17.0

> A transpiler-first domain-specific language for self-aware software.
>
> **Every component. Every line. Fully described. No exceptions.**

> **What's new in 0.17.0 — the DSL-improvements batch (June 2026, ships with distribution 0.8.0).** The language batch decided in ADR-011 from the mcp self-hosting friction log, landed milestone by milestone in this one spec version. DSL-M1 surfaces: **§4.1/§4.2/§4.3 (`metadata:` field)** — nerve / cell / ganglion declarations gain an authored block-map metadata field (flat identifier keys → quoted string | int | float | bool | list of strings) that is shape-validated only, rides the IR under `components[].fields.metadata`, and merges into the emitted registration `metadata=` dict after the emitter-written keys, reaching runtime `ComponentSpec.metadata`; three always-error codes (`METADATA_INVALID_KEY`, `METADATA_INVALID_VALUE`, `METADATA_RESERVED_KEY`) guard the shape, with the reserved-key set published as `RESERVED_COMPONENT_METADATA_KEYS` (§4.14). **§4.1/§4.10 (`serves_as:` field)** — nerves gain an optional bare-identifier public serving name; the declaration identifier stays the registry/module symbol while the emitter writes the reserved `serves_as` metadata key and stamps the emitted callable's `__name__`/`__qualname__` with the served name after the decorated def (decorate-then-stamp, §4.10); uniqueness is validated per module and per project build (`SERVES_AS_INVALID`, `SERVES_AS_COLLISION`). **§4.14 (IR 2.1.0)** — additive schema bump: optional `components[].fields.metadata` / `.serves_as` (this milestone) and `.covered_by` / `imports.deferred_requires` (M2) under one version; 2.0.0 consumers keep parsing 2.1.0 documents. DSL-M2 surfaces: **§4.5/§4.7 (`deferred_requires:`)** — a fourth requires-family module-header list whose imports are injected at the top of each consuming def body (after the docstring) instead of module top, restoring the "start degraded, fail per-call" resilience idiom with a complete static record (`"deferred": true` IR entries; `DUPLICATE_REQUIRES_ENTRY`, `DEFERRED_IMPORT_MODULE_SCOPE`); **§4.1.2/§4.6 (qualified `depends_on:`)** — inline dependency targets accept the dotted in-project form `module.declaration`, resolved against the project module set (existence, exports, fatal cycles, cross-layer matrix) and emitted as canonical `module::declaration` dependency strings; **§4.1.13/§4.8/§2.4 (`covered_by:`)** — nerve/cell/ganglion gain the external test-evidence credit that satisfies release-mode `MISSING_TEST_COVERAGE` alongside in-language `tests:` coverage (`COVERED_BY_EMPTY`). M4 lands the doc-subsystem v1.1 + front-matter changes per ADR-011 §(h). Detailed rationale lives in `docs/adr/ADR-011-declaration-metadata-and-language-surface-batch.md` and the CHANGELOG `## [Unreleased]` block.

> **What's new in 0.16.0 — historical entry (11 May 2026, the post-Phase-2 second release boundary).** The companion bump alongside `s0ma-core 0.4.0`
> bundling eleven milestones (M-8 through M-19) of the post-Phase-2
> plan. This batch is wider than the 0.15.0 cut: it covers grammar
> enrichment round 2 (M-9 / M-17 / M-18 / M-19), build / CLI
> maturity (M-8 / M-11 / M-16), the bulk of the validator round
> (M-13 / M-14 / M-15), permissive test-layer routing (M-10), and
> the `requires-python` forward-incompat check (M-12). Every change
> is additive and backward-compatible — pre-0.16.0 modules parse
> unchanged, no consumer call site is mandated to change, and the
> only mandatory rotation is the spec-pointer (v0.11.0 retires, the
> single live pointer is now v0.15.0 → v0.16.0). Headline surfaces,
> in spec / numbered-milestone order:
> **§4.14 (manifest emits Python stubs, M-8 / POST-14)** —
> `s0ma build` writes `<build_dir>/build.s0ma.pyi` alongside the
> manifest so `bootstrap_imports` consumers see typed module names
> under mypy / pyright instead of falling back to `Any`-keyed dicts.
> **§4.7 (`integration` declaration kind, M-9 / POST-5)** — D-15 is
> promoted to a first-class declaration that auto-emits
> `get_factory`, `get_manifest`, `smoke_test_primary`, and
> `get_smoke_test` helper functions without the IntegrationManifest
> constructor verbosity. **§4.13 (`test_layering: permissive`,
> M-10 / POST-6)** — opt-in project-config flag that skips
> `CROSS_LAYER_DEPENDENCY` checks for `test` declarations only;
> strict remains the default. **§4.15 CLI banner (M-11, POST-7;
> M-16, POST-11)** — `s0ma check src/ tests/` accepts multiple
> paths and resolves project context from subdirs; `--output-dir`
> warns against `[tool.s0ma].build_dir` mismatch and refuses
> without `--force-output-dir`; `s0ma test --quiet` suppresses the
> driver banner; `s0ma build` exit-code semantics gain regression
> pins. **§4.13 (`requires-python` compat, M-12 / POST-8)** —
> `s0ma check` walks emitted bodies' ASTs against the project's
> `[project].requires-python` floor; 3.12-only constructs
> (nested-quote f-strings, walrus-in-comprehension) fire
> `PARSE_GRAMMAR_FORWARD_INCOMPAT`. **Validator round 1 (M-13 /
> POST-10a/b/c)** — vestigial-import closure now walks
> `uses:` ↔ `depends_on:` ↔ body references in one pass; new
> `runtime_only_requires:` field carves out pytest-style imports
> from the vestigial-detector; the long-running D-27
> `HELPER_NAME_COLLISION` false-positive is pinned with regression
> tests. **Validator round 2 (M-14 / POST-10d/e/f/g)** —
> `MODULE_NAME_COLLISION` remediation suggests descriptive
> suffixes (plus opt-in
> `[tool.s0ma].test_module_name_prefix_by_dir`); `s0ma check tests/`
> now surfaces project-level invariants; `BARE_IMPORT` remediation
> reworded; `uuid.uuid4` warning suggests the `uuid:uuid4`
> colon-override. **Validator round 3 (M-15 / POST-10h/i/j/k)** —
> three new strict-mode lints (`MUTABLE_DEFAULT`,
> `DUPLICATE_INNER_FUNCTION`, `CROSS_MODULE_USES_ASYMMETRY`) and
> the `soft_requires:` dotted-name codegen fix. **§4.1
> (`expected_exceptions:` and `deferred:`, M-17 / POST-12a/f)** —
> nerves gain a Python-side `expected_exceptions:` declaration
> (distinct from `raises:` which is reserved for s0ma cells);
> stubs gain a `deferred:` annotation; `s0ma check
> --report-deferred` enumerates the deferred surface. **§4.2.2
> (`placeholders:`, M-18 / POST-12b)** — CONSTANT cells with
> `@file()` content gain an opt-in `placeholders:` list whose
> magic-string slots are validated at check time. **§4.13
> (`fixtures_format`, M-18 / POST-12g)** — project-config map for
> validating non-`.s0ma` test fixtures (`{"*.jsonl": "ndjson"}`).
> **§4.2 + §4.1.2 (`dataclass_invariants:` and
> `consumes_via_dict:`, M-19 / POST-12c/d)** — MODEL cells may
> declare machine-readable invariants like
> `len(latency_samples) <= 100`; `depends_on:` entries may declare
> a `consumes_via_dict: [<contract>: <param>]` pairing to surface
> duck-typed coupling explicitly. The IR / manifest schemas stay
> unchanged for round-trip; every new error code is registered in
> `SEVERITY_MATRIX` and `ERROR_CODE_DESCRIPTIONS`. Detailed
> per-milestone rationale and test pins live in the CHANGELOG
> `## [0.16.0]` block; the consumer-facing migration walkthrough
> lives in `docs/migration_guide.md` (`# 0.15.0 → 0.16.0`).

> **What's new in 0.15.0 — historical entry (11 May 2026, post-Phase-2
> grammar-enrichment batch).** A focused minor release that landed six
> milestones (M-2 through M-7) of the post-Phase-2 plan, all targeting
> grammar enrichment and documentation consolidation surfaces fr3d's
> Phase 2 work surfaced as recurring friction. Every change was
> additive and backward-compatible — pre-0.15.0 modules parse
> unchanged, no consumer call site is mandated to change, and
> `s0ma-core` stayed pinned at 0.3.0 (no companion bump). Headline
> surfaces, in spec order: **§4.1.3 (per-method `provides:` triples)**
> — SERVICE-nerve `provides:` entries gained an optional structured
> form letting authors declare per-method `returns:` / `expects:` /
> `guarantees:` inline; the legacy flat form (`provides: [foo, bar]`)
> parses unchanged. Two new always-error codes
> (`MIXED_PROVIDES_FORMS`, `DUPLICATE_PROVIDES_NAME`) guard the
> structured form's shape. **§4.1.7 (`internal:` on nerves)** —
> nerves may declare a structured list of inner helper functions
> (`internal: [_foo: "intent", _bar]`) that `s0ma inspect` surfaces
> in a dedicated sub-section. The field has no codegen effect — the
> helpers stay module-private — but the public-surface introspection
> finally covers the private one. **§4.2.5 (cell `category:` field)**
> — cells gained an optional `category: capability | behaviour` field
> woven into the emitted `metadata={}` dict and surfaced in
> `s0ma inspect`'s bracket label. fr3d's MS 19 ConfigDiff classifier
> reads the value at runtime, retiring the static name-pattern rule
> table. **§4.4a (helper enrichments)** — three sub-features shipped
> together: `helper` accepts `class` bodies in addition to `def`
> (retires the `cell kind: MODEL visibility: INTERNAL` workaround for
> module-private classes); the new `helper @inline` shorthand lets
> short helpers live in the module header's `helpers:` block; the new
> `exports_helpers:` module-header field widens reachability so test
> consumers can name re-exported helpers via `uses:`. New error code
> `EXPORTED_HELPER_NOT_FOUND` (error in every mode) guards the
> cross-module re-export contract. **§4.8.4 (`mocks:` on tests +
> provides cross-validation)** — test declarations gained a
> `mocks: [<NerveName>]` field; the validator cross-checks any dict
> literal mocking a named target against the target's `provides:` set
> and fires `MOCK_KEY_MISMATCH` (warning in migration/dev, error in
> strict/release) on key mismatch. The companion
> `PROVIDES_KEY_MISMATCH` code (same severity profile) generalised
> the structured-form `MISSING_RETURN_KEY` check to the flat form and
> to the extra-key direction so `provides:` ↔ `return {...}` literal
> keys round-trip cleanly. **Documentation additions (POST-9 a-i)** —
> the patterns guide grew §18-§22 with the Decision-1
> abstract-down-to-DOMAIN, late-bind dependency slot, helper-as-fixture,
> patch-via-context-manager, and cross-thread `asyncio.Queue` recipes;
> §4.5.1 (requires-import heuristic) documents four recurring stdlib
> gotchas (urllib collisions, `uuid:uuid4`, `dataclasses` /
> `dataclasses:field`, `argparse.REMAINDER`); §4.1.3 made the
> `provides:` ↔ returned-dict-key three-way coupling explicit; §4.1.4
> normalised the `abstract: true` lowercase boolean convention; the
> coding-agent handbook gained §1.5 on the thin-CLI dispatch pattern
> and the `argparse.REMAINDER` `--`-swallow gotcha. Detailed
> per-milestone rationale and test pins live in the CHANGELOG
> `## [0.15.0]` block; the consumer-facing migration walkthrough lives
> in `docs/migration_guide.md` (`# 0.14.0 → 0.15.0`).

> **What's new in 0.14.0 — the pre-Phase-2 batch (10 May 2026).** A
> short, focused release that lands the upstream half of the changes
> identified ahead of fr3d's Phase 2 (Local) milestone work. Headline
> surfaces, in spec order: §4.2.4 (when to use `visibility: TEST` for
> test-only cells, not `INTERNAL` — closes the recurring trap where
> sibling-module tests hit `NOT_EXPORTED`); the parser accepts
> block-style YAML lists on `uses:` / `requires:` / `exports:` /
> `raises:` (`- entry` per line, items strictly more indented than the
> field key); `register_constant` and `register_type` thread the
> owning module's canonical name through to the registry so the
> resulting `ComponentSpec.module_path` is populated (parity with
> `register_module` and `@component`); `ModuleManifestEntry` carries
> a `role: "source" | "test"` tag so a single `build.s0ma.json` can
> hold both source and test modules and `bootstrap_imports` filters
> by role (`roles=("source",)` is the back-compat default).
> Implementation-side: `s0ma test` no longer overwrites the
> production manifest, `s0ma build` prunes orphan `.py`/`.s0ma.json`/
> `.s0ma.map` triples, and `s0ma test` discovers raw `.py` test files
> under `[tool.s0ma].test_roots` when no `.s0ma` sibling exists.
> Every change is additive and backward-compatible; pre-0.14.0
> manifests, transpiled artefacts, and consumer call sites continue
> to work unchanged. Pairs with `s0ma-core 0.3.0` (which adds the
> `compute_registry_diff` API, the `module_scoped` flag, and the
> `module_path` parameter on `register_constant` / `register_type`).
> Detailed rationale and test pins live in the CHANGELOG
> `## [0.14.0]` block.

> **What's new in 0.13.0 — the feedback 5–6 cleanup release.** Closeout
> of the feedback 5–6 cycle. This release lands five real consumer-bug
> fixes (Tier A: G1 `PACKAGE_MARKER` auto-classification; G2
> `OVERLAPPING_DISCOVERY_ROOTS` pre-flight; G3 default `build_dir`
> sanitization; G4 cross-source-root `uses:` resolution; G5 versioned
> `s0ma test-conftest` banner + `STALE_GENERATED_CONFTEST` pre-flight),
> plus two doc-drift-prevention refinements (Tier B: G6 error-code
> registry audit + AST-walking meta-test; G7a/b `doc-ref`
> `covers: { source: error_codes }` grammar that derives the Common
> Errors table from the canonical registry). Spec additions for these
> milestones are folded into the already-numbered sections — §4.13
> schema rows for `package_markers` and the disjoint-roots / sanitized-
> `build_dir` rules; §4.15 the `STALE_GENERATED_CONFTEST` classifier
> contract and the sibling-include behaviour for `s0ma test`'s per-
> source-root build pass; §4.12.1 the `doc-ref` `covers:` discriminated
> union with the `{ source: <name> }` sub-key form. The change is
> additive in language terms (IR schema stays at 1.2.0), but behaviour-
> changing in three places that warrant the minor bump: the
> `build_dir` sanitization changes the default value; the
> `STALE_GENERATED_CONFTEST` pre-flight is a new loud refusal that
> consumers must address (or opt past with `--force`); `__init__.py`
> files now auto-classify as `PACKAGE_MARKER` instead of `UNKNOWN`.
> The detailed per-milestone rationale, test pins, and consumer-migration
> notes live in the CHANGELOG `## [0.13.0]` block and
> `docs/migration_guide.md` "0.12.0 → 0.13.0" — this preface
> intentionally points there rather than duplicating it.

> **What's new in 0.12.0 — the consumer-feedback release.** The release
> consolidates the corrections surfaced by feedback rounds 5, 5.5, and 6
> into one coherent surface. The headline additions, in spec order:
>
> - **§4.4a `helper` (Module-Private Function)** — a fourth declaration
>   kind that emits a plain `def` with no component registration but
>   remains introspectable via `s0ma inspect`. Cross-module access is
>   gated by `HELPER_PRIVATE_TO_MODULE` (the same test-consumer carve-out
>   as `visibility: TEST`).
> - **§5 — `visibility: TEST`** — a third declarative visibility level.
>   Test consumers (modules with ≥1 `test` declaration) may reach
>   TEST-visibility components cross-module; production callers cannot.
>   See ADR-008.
> - **§4.13 `[tool.s0ma]` project model** — every CLI subcommand
>   resolves a `S0maProject` from `pyproject.toml` first (source roots,
>   test roots, build dir, bootstrap files, attribute budgets). See
>   ADR-005.
> - **§4.14 single flat build layout + `build.s0ma.json` manifest** —
>   `s0ma build` emits one flat directory with an auto-generated
>   `__init__.py`, a manifest, and topological import order. The legacy
>   `__s0ma_cache__/` and per-layer subdirs are gone. See ADR-007.
> - **§4.5.3** the source filename's stem must equal the declared
>   `module <name>` (canonical identity, see ADR-006).
> - **§4.0.2 cross-module layer reachability**, **§4.2.2 `@file()`
>   embedded content**, **§4.2.3 `CONSTANT` cell name mirrors body
>   identifier**, **§4.1.6 `declares_attributes:` + project-level
>   attribute budgets**, **§4.8.3 scope-aware helper-collision
>   detection**, **§4.15 project-aware test execution** — all new
>   normative surfaces in 0.12.0.
>
> The change is additive: every 0.11.0 module parses unchanged. Projects
> without a `[tool.s0ma]` table operate in a synthetic-fallback "legacy
> mode" with a one-line warning. Layout-breaking parts (the flat build
> output) ship with `s0ma migrate-layout` for one-shot upgrade.

> **What's new in 0.11.0:** Three new declaration types — `doc-ref`,
> `doc-guide`, and `example` — bring documentation under the same
> grammar-level enforcement as nerves, cells, and ganglia. See §4.12
> for the declaration grammar and `docs/references/documentation_subsystem.md`
> for the user-facing guide. The change is additive: every 0.10.1 module
> parses unchanged.

---

## 1. Purpose & Design Principles

The s0ma DSL is a domain-specific language for writing self-aware software. It transpiles to Python decorated with s0ma framework annotations, but it is **not** Python. It is a language whose grammar enforces, at the syntactic level, the principles that s0ma currently enforces at runtime.

The DSL exists to serve four non-negotiable design principles:

### Principle 1 — Structural Self-Awareness

A system cannot be self-aware unless accurate information reaches the systems that act on it. The architecture must ensure that every piece of self-knowledge — component descriptions, dependency graphs, contracts, evaluator signals, anomaly reports — is queryable at runtime, surfaceable through tool-use interfaces, and integrated into the AI's reasoning and decision-making process. A self-model that exists but cannot be accessed is architecturally equivalent to no self-model at all.

This is the distinction between documentation and *proprioception* — here in its structural-faculty sense, the structural faculty of self-knowledge. Documentation is information that exists alongside a system. Proprioception (structure) is information that is structurally wired into the organism's ability to perceive and act on its own state. The s0ma DSL does not produce documentation. It produces a load-bearing self-model whose value is realised only when it is connected — through the registry, the evaluator network, and the AI's tool-use interface — to the systems that consume it.

The implication for language design: every declaration field, every dependency relationship, every evaluator signal must be designed not just to exist, but to be discoverable and consumable by an AI agent through structured queries. If a piece of self-knowledge cannot be queried, it cannot inform action, and it fails this principle.

### Principle 2 — Unity of Code and Description

Every component's self-description is not documentation alongside the code. It is structurally inseparable from the code. You cannot write a component in this language without simultaneously declaring what it is, why it exists, what it does, and how it relates to the rest of the system. The description is load-bearing.

### Principle 3 — AI as Primary User

This language is designed for LLMs, coding agents, and future AI systems first. Human readability is valued but secondary. Every construct must be unambiguous, consistently structured, and fully parseable by a language model without contextual inference.

### Principle 4 — Total Observability, No Exceptions

There is no code category exempt from description. The level of description required may vary by component type, but the requirement to describe is universal. Obscurity is never permitted, even when complexity is.

> **KEY:** The question is never "does this need to be described?" It is always "what is the right level of description for this component type?"

---

## 2. Architecture: Transpiler-First

The s0ma DSL is implemented as a transpiler: source files written in the `.s0ma` extension are compiled to valid Python + s0ma-decorated code before execution.

- LLMs are trained overwhelmingly on Python. Staying close to Python keeps the AI fluent.
- Transpilation allows grammar-level enforcement before any runtime check.
- The transpiler output is inspectable, debuggable Python — not a black box.

### 2.1 Build Pipeline

```
.s0ma source file
       │
       ▼
Lexer + Parser (grammar enforces mandatory fields at parse time)
       │
       ▼
AST (Abstract Syntax Tree of s0ma declarations + Python bodies)
       │
       ▼
Transpiler (emits @component-decorated Python + normalized IR)
       │
       ▼
Output validation invariant (every emitted .py round-trips through ast.parse)
       │
       ▼
.py output (valid Python, importable by s0ma runtime)
  + .s0ma.json (normalized IR for AI tools)
  + .s0ma.map (source map: .s0ma line → .py line)
       │
       ▼
s0ma import hook (registers all components at import time)
```

#### 2.1.1 Metadata-field emission

All metadata-field string values (`intent`, `expects`, `guarantees`, `schema`, `invariants`, `priors`, `on_anomaly`, axon `carries`, doc-* `format`/`output`, example `runs_in`) are emitted via Python's `repr()` and are guaranteed to round-trip through `ast.parse()`. Authors may use any character — including `"`, `'`, backslashes, or Unicode — without escape concerns. The transpiler's internal `_py_str_literal()` helper is the canonical interpolation path; hand-rolled escape patterns are forbidden because they have historically corrupted strings containing `\"` (see CHANGELOG 0.12.0 → Fixed).

**Multi-line content via the `|` block-scalar form.** Every string-valued metadata field accepts either the inline-quoted form (one line, surrounded by `"..."`) or YAML's literal-block-scalar form (`|` followed by indented content). The two forms produce identical IR — both store a plain `str` — and identical generated Python; the choice is purely a source-readability preference.

```
intent: |
    First line of the intent.
    Second line, with line break preserved.

    A blank line is preserved as an empty line.
        Sub-indented lines retain their relative indent.
```

**De-indenting rule.** The smallest interior indentation across all non-blank content lines becomes the baseline. The transpiler strips exactly that many leading spaces from every line of the block. Lines that were indented more than the baseline retain the *difference* as relative indent (so structured content — bulleted sub-lists, nested code samples — is preserved). Blank lines inside the block are emitted as empty strings (no stray indent).

**Termination rule.** The block ends at the first line whose indentation is at or below the field key's column (the standard 4-space field indent), at a `---` body separator, at a top-level declaration header, or at end-of-file. Trailing whitespace on the joined value is stripped (default chomping).

**Scope.** M14 ships the literal form (`|`) only. The folded form (`>`) and explicit chomping indicators (`|+`, `|-`) are out of scope and are *not* recognised; if you need single-paragraph "fold whitespace into one line" behaviour, use the inline-quoted form.

**Backwards compatibility.** Inline-quoted (`"..."`) and unquoted single-line metadata continue to parse exactly as before. The block-scalar form is opt-in — fixtures written before M14 require no migration.

#### 2.1.2 Output validation invariant

Before any emitted `.py` payload is written to disk (CLI build, cache store, or any future writer), the transpiler parses it back with `ast.parse()`. If parsing fails the writer raises `TranspilerInternalError` naming the path and the underlying `SyntaxError`, and the file is *not* written. The invariant holds for every write site without exception — there is no flag to disable it. It catches the entire class of "emitter produced syntactically-invalid Python" bugs at build time rather than at handoff or runtime, and it is one of the build-pipeline guarantees that consumers may rely on (per Principle 5: no silent failures).

### 2.2 Relationship to the s0ma Runtime

The DSL does not replace the s0ma runtime. The runtime's architectural core — the registry, import hook, contract system, and anomaly detection — remains sound. However, the DSL introduces declaration types beyond the current `@component` decorator, requiring meaningful evolution of the registration API and registry schema.

**Runtime expansion required:** Module-level registration, relationship registration (axons), test registration, and cell registration for constants, enums, type aliases, and config objects. The current import hook's exclusion of constants, type aliases, and module-level variables must be revised. The DSL specifies *what* gets registered; the framework implementation plan specifies *how*.

### 2.3 Parser Strategy

**Outer grammar:** Lark with LALR(1) and `strict=True`. Handles all declaration types, fields, and structural validation.

**Inner grammar:** Body extraction via Python's `tokenize` module for exact source preservation and boundary detection. Semantic validation (banning imports, detecting `exec`/`eval`) via Python's `ast` module.

**Canonical body storage (F1).** Every declaration body is dedented exactly once, at parse time, by `parser.body_extractor.extract_body`. The dedent strategy reads the indentation of the first non-blank, non-comment line and strips that prefix from every subsequent line (lines with less indentation, e.g. column-0 comments or column-0 string content inside a multi-line literal, are passed through unchanged). The dedented form is stored on the AST node as `body` (or `python_body` for examples) and is the canonical, Python-ready value every downstream consumer reads — validator analysis, codegen emission, IR serialization, source map line math, and the doc subsystem hash all consume the same bytes. The original raw text with the .s0ma source's leading indent preserved is kept on a parallel `raw_body` (or `raw_python_body`) field for diagnostics only; production code paths must not call `textwrap.dedent`, `inspect.cleandoc`, or any hand-rolled dedent on a body. Calling them is a bug — they would either be redundant (the body is already at column 0) or actively wrong (they collapse the common-prefix when a multi-line string contains column-0 lines). Every consumer reads `decl.body` directly.

Source maps (`.s0ma` → `.py`) emitted alongside transpiled output.

### 2.4 Strictness Modes

| Mode | Behaviour | Use Case |
|------|-----------|----------|
| `migration` | Maximum leniency. Most issues produce warnings. | Adopting s0ma in an existing codebase. |
| `dev` | Balanced. Vestigial imports, empty observes, duplicate axons are warnings. | Day-to-day development. |
| `strict` | Nearly everything is an error. | CI pipelines. Pre-merge checks. |
| `release` | Strict plus: all PUBLIC nerves must have tests or a `covered_by:` external-evidence claim (§4.8), all modules must have non-zero version, all cross-module axons must have hand-written intent. | Production releases. |

> **KEY:** In a system built on architectural explicitness, silent behaviour is the wrong default. Strictness modes allow forgiveness during adoption and rigour in production.

---

## 3. Primitive Vocabulary

| Primitive | Analogy | Definition |
|-----------|---------|------------|
| `component` | Cell / Organ | Any named, declared unit of code. The atom of the language. |
| `nerve` | Nerve fibre | Observable executable logic. Emits signals. Body is a function definition, or a class definition for SERVICE/ADAPTER kinds. |
| `intent` | Purpose / Reason | Why this component exists. Mandatory for every component. |
| `contract` | Promise | Preconditions, postconditions, prohibitions, performance bounds. |
| `layer` | Organ system | `DOMAIN`, `APPLICATION`, `INFRASTRUCTURE`, `PRESENTATION`, `FRAMEWORK`. |
| `kind` | Cell type | Functional archetype. Context-sensitive by declaration type. See Section 3.1. |
| `evaluates_at` | Ganglion / Synapse | Which convergence points monitor this component. |
| `visibility` | Tissue depth | `PUBLIC`, `INTERNAL`, or `TEST` (see §5). Routing attribute, not exemption. |
| `relation` | Synapse type | Kind of authored dependency: `CALLS`, `CONSTRUCTS`, `READS`, `CONFIGURES`, `PRODUCES`, `CONSUMES`. |

### 3.1 The `kind` Taxonomy

| Kind | Applies To | Meaning |
|------|-----------|---------|
| `SERVICE` | nerve | Long-running process. Body may be a function (dict-of-closures pattern) or a class (transpiled to a dict-compatible factory). |
| `FUNCTION` | nerve | Stateless transformation or computation. |
| `ADAPTER` | nerve | Interface to an external system. |
| `ORCHESTRATOR` | nerve | Coordinates other components. |
| `MODEL` | cell | Data structure with fields and optional invariants. |
| `CONSTANT` | cell | Immutable value (int, str, tuple, etc.). |
| `CONFIG` | cell | Configuration object or settings container. |
| `ENUM` | cell | Enumeration type. |
| `EXCEPTION` | cell | Exception class. |
| `TYPE` | cell | Type alias, NewType, Protocol, or abstract base type. |
| `FRAMEWORK` | nerve, cell | s0ma's own infrastructure. Reserved for framework internals. |

The transpiler validates kind-to-declaration-type compatibility.

### 3.2 Nerve Body Constraints

**Nerve bodies are function definitions by default** (`def` statements). **SERVICE and ADAPTER nerves may also use class bodies** (`class` statements). When a class body is used, the transpiler generates a dict-compatible factory wrapper so that the `service["method"](args)` calling convention is preserved. FUNCTION and ORCHESTRATOR nerves must use function bodies.

If a service uses the class body form, the class is emitted with a `@component` decorator and a factory function that returns a dict mapping public method names to bound methods.

> **▲** V1 visibility is three-level: `PUBLIC` (cross-module via exports), `INTERNAL` (same module only), and `TEST` (same module + test consumers in any project module — see §5 and ADR-008). `PRIVATE` will be introduced when nested component syntax is defined.

---

## 4. Declaration Types

Every piece of code in a `.s0ma` file belongs to exactly one declaration type. The parser rejects unrecognised code blocks.

The eight declaration types are: `module` (§4.5 — the file-level header), `nerve` (§4.1), `cell` (§4.2), `ganglion` (§4.3), `axon` (§4.4), `helper` (§4.4a — added in v0.12.0), `integration` (§4.4b — added in v0.16.0), and `test` (§4.8). The documentation subsystem adds three further declaration kinds — `doc-ref`, `doc-guide`, and `example` — which are described separately in §4.12.

### 4.0 Declaration Granularity

**The unit of declaration is the top-level definition within a `.s0ma` file.** Methods, nested functions, lambdas, property accessors, and comprehensions belong to their containing declaration.

#### 4.0.1 Layer Consistency Rule

**In v1, all components in a module must share the module's layer.** Enforced in all strictness modes.

#### 4.0.2 Cross-Module Layer Reachability Rule

Layer discipline applies cross-module as well: a module's `uses:` entries cannot reach into a layer that is not reachable from the consuming module's layer. The reachable-set table is the authoritative reference:

| Source layer (`uses:` written here) | Target layer must be one of |
|---|---|
| `DOMAIN` | `DOMAIN`, `FRAMEWORK` |
| `APPLICATION` | `DOMAIN`, `APPLICATION`, `FRAMEWORK` |
| `PRESENTATION` | `DOMAIN`, `APPLICATION`, `PRESENTATION`, `FRAMEWORK` |
| `INFRASTRUCTURE` | `DOMAIN`, `APPLICATION`, `INFRASTRUCTURE`, `FRAMEWORK` |
| `FRAMEWORK` | `FRAMEWORK` |

The matrix is the canonical Clean Architecture reachability table. Reading it in plain English: domain models cannot reach up into application services or presentation/infrastructure adapters; application services consume domain plus framework; presentation and infrastructure are sibling boundary layers that consume domain and application but not each other; framework is at the bottom and sees only itself.

**Scope.** The rule applies to `uses:` declarations (cross-module s0ma references). It does *not* apply to `requires:` entries (third-party Python imports — those carry no `Layer`). Test modules' `uses:` entries are checked at the layer the test declares: a DOMAIN-layer test importing a PRESENTATION component is the same architectural smell as a DOMAIN production module doing it.

> **Test-layer opt-in (POST-6, 0.16.0).** Projects whose tests legitimately span layers (e.g. PRESENTATION test fixtures wiring INFRASTRUCTURE services for end-to-end coverage) can opt in to a relaxation: setting `[tool.s0ma].test_layering = "permissive"` exempts modules with at least one `test` declaration from this check. Production modules (zero `test` declarations) still receive the strict check regardless. The default `"strict"` preserves the pre-0.16.0 behaviour exactly. See §4.13 "Test-layer opt-in" for the full surface and rationale.

**Violation code.** `CROSS_LAYER_DEPENDENCY` (warning in migration/dev, error in strict and release; see [`spec_traceability.md`](spec_traceability.md) and the [DSL Patterns Guide §13 Layer Discipline](references/dsl_patterns_guide.md)).

**Remediation.** Two options when the rule fires:
1. **Move the shared concept down.** If two modules need to share a type or constant, place it in a layer both can reach (typically DOMAIN, which every other layer can consume).
2. **Invert the dependency** ("Decision-1" pattern). Have the lower layer publish an abstract interface (e.g., a port) and the higher layer implement it as an adapter. The dependency edge then runs from infrastructure/presentation *down to* domain, not the other way around. The canonical recipe — abstract nerve in DOMAIN with `abstract: true` + `interface: [...]`, concrete nerve in INFRASTRUCTURE with `depends_on: <Name>: {relation: CONSTRUCTS, ...}` carrying matching method definitions — is the [DSL Patterns Guide §18](references/dsl_patterns_guide.md). The patterns guide carries three working instantiations (`LLMAdapter` / `MessageGateway` / `EventStore`) for agents to copy.

The intra-module rule (§4.0.1) and the cross-module rule (§4.0.2) are consistent: intra-module is "exact match" while cross-module is "reachable per the matrix." A module's components all share its layer, and a `uses:` entry crosses module boundaries — the matrix governs which layer pairs the boundary may carry.

#### 4.0.3 Every Line of a Description Is Read, or Reported

Between a declaration's header line and its `---` separator, every line is one of four things: a **field** (`<name>: <value>`, starting with exactly four spaces), a line that **belongs to the field above it** (an entry of a block, or the continuation of a value, indented further), a **comment** (starting with `#`), or blank. A line that is none of these, and a field whose name the declaration kind does not have, is never silently dropped. Two diagnostics report them:

| Code | Reported when | migration | dev | strict | release |
|------|---------------|-----------|-----|--------|---------|
| `UNKNOWN_FIELD` | A well-formed field line names a field that kind of declaration does not have: a misspelling (`guarantes:`), a field of another kind (`expects:` on a `helper`), or a fact that belongs on the header line (`layer:` on a `nerve`). | warning | warning | error | error |
| `UNRECOGNIZED_LINE` | A line is not a field, not part of a block, and not a comment. In practice a field, or a `depends_on:` entry, indented by the wrong number of spaces. | warning | warning | error | error |

The fields a declaration kind has are exactly the non-derived rows of §4.14.5 for that kind, in the spelling an author writes, together with the two authored spellings that table does not name: `content:` on a `cell` (§4.2.2) and `helpers:` on a `module` (§4.4a.6). Authoring a derived field keeps its own diagnostic, `SEMANTIC_DERIVED_FIELD_AUTHORED`.

`UNKNOWN_FIELD` names the field that was probably meant when one is close, and says where the fact belongs when it is a header-line fact or the code. `UNRECOGNIZED_LINE` names the field the line looks like and how many spaces it starts with.

**Interaction with `SEMANTIC_REQUIRED_STATE_OMITTED`.** A required field that is on the page under a misspelt name, or at the wrong indentation, is an omitted field: the omission is an error in every mode and is raised first. Its remediation therefore names the line — "Line 18 holds 'guarantees:' and starts with 2 space(s); a field starts with exactly 4." — so the author is told where the field is and not only that it is missing.

### 4.1 `nerve` (Observable Function)

A nerve is executable logic that serves the system. Nerves emit signals, can be monitored, and contribute to the behavioral self-model. Body is a function definition, or a class definition for SERVICE/ADAPTER kinds.

```
nerve <n> :: <LAYER>
    kind: <KIND>
    visibility: <PUBLIC | INTERNAL | TEST>
    intent: "<why this component exists>"
    expects: "<preconditions>"
    guarantees: "<postconditions>"
    forbids: "<what it must never do>"
    raises: [<exception types>]
    latency_ms: <max acceptable latency>
    evaluates_at: <FUNCTION_BOUNDARY | SUBSYSTEM | SYSTEM>
    provides: [<operation names>]
    abstract: true | false
    interface: [<method names>]
    returns: [<return key names>]
    declares_attributes: [<namespace>:<attribute>, ...]
    is_page_composer: true | false
    internal: [<inner helper names>]
    expected_exceptions: [<dotted Python paths>]
    deferred: "<reason this body is a stub>"
    serves_as: <public_serving_name>
    covered_by: ["<external suite path or rationale>", ...]
    metadata:
        <key>: <"string" | int | float | true | false | [list, "of", strings]>
    consumes_via_dict:
      - contract: <ContractName>
        param: <param_name>
    depends_on:
        <target | module.target>: {relation: <RELATION>, carries: "<data>", coupling: <TIGHT|LOOSE>}
    ---
    def <n>(<args>) -> <return_type>:
        <Python body>
    # OR for SERVICE/ADAPTER:
    class <N>:
        <Python class body>
```

**Which lines to write:** §4.14.5 is the one table of which lines a nerve must write and which of them may be `none` or `pending("reason")`; it is generated from the toolchain's field classification, so it is not repeated here. The subsections below give each field's contract.

#### 4.1.1 The `raises` Field

`raises` is the authoritative declaration of which exception types a nerve may raise. The transpiler derives `RAISES` edges automatically (Section 4.11). No separate axon declaration is needed or permitted.

> **KEY:** Each exception type in `raises` must be a declared cell in the module's component-reference namespace (locally declared or imported via `uses`). The transpiler validates this at build time.

**Exception normalization policy:** Because the component-reference namespace excludes `requires` names, external exceptions (Python builtins, stdlib exceptions, third-party library exceptions) cannot appear directly in `raises` fields. V1 requires exception normalization at system boundaries: adapter nerves must catch external exceptions and re-raise them as declared s0ma `EXCEPTION` cells. This is a deliberate architectural choice — the self-model can only reason about exceptions it can self-describe. Adapter layers are the natural normalization point.

#### 4.1.2 The `depends_on` Field (Inline Axon Declarations)

`depends_on` declares authored dependencies — relationships representing architectural decisions that cannot be derived from code. Each entry requires `relation`, `carries`, and `coupling`.

```
depends_on:
    validate_envelope: {relation: CALLS, carries: "SignalEnvelope", coupling: TIGHT}
    tools.scaffold_module_tool: {relation: CALLS, carries: "referential journey edge", coupling: LOOSE}
```

**Qualified in-project targets (DSL-M2, 0.17.0).** A target may name another module's declaration in the dotted form `module.declaration` — exactly one dot, because module names are flat (ADR-006); deeper dotting is a parse error. The dot is the established s0ma-component-space qualifier (`uses:`, cross-module `tests:` targets, standalone axon targets); the colon stays the Python-import override marker on the `requires:` side of the §4.6.4 self-awareness boundary. Resolution runs against the project's module set (§4.6.1 rules): the named module must exist (`DOES_NOT_EXIST`), the declaration must exist in it (`DOES_NOT_EXIST`), and cross-module targets must appear in the target module's `exports:` (`NOT_EXPORTED`). A self-module-qualified target (`m.x` authored inside `m`) resolves as the local declaration — idempotent, permitted, exempt from the export rule. Qualified edges join module-graph construction with the same fatal-cycle rule as `uses:` and the cross-layer reachability matrix applies unchanged. Single-module/synthetic invocations cannot resolve qualified targets — `DOES_NOT_EXIST` fires with a remediation saying qualified targets require a `[tool.s0ma]` project build. The emitted decorator's `dependencies=[...]` carries the canonical `module::declaration` form for qualified targets; bare local targets keep their byte-identical bare-name strings. Cross-PACKAGE targets remain inexpressible.

#### 4.1.3 The `provides` Field

`provides` declares the public operations a SERVICE nerve exposes. When present, the transpiler validates that each listed name appears as a `def` in the nerve's body.

```
nerve FileSystemTool :: INFRASTRUCTURE
    kind: SERVICE
    provides: [read_file, write_file, edit_file]
```

**Three-way coupling.** For SERVICE nerves whose body is a function returning a dict-of-closures (the factory pattern; see Patterns Guide §2.1), `provides:` is one corner of a three-way coupling that the author and validator must keep aligned:

1. The names in `provides:` — the declared public surface.
2. The inner `def` names inside the function body — what the implementation actually defines.
3. The keys in the body's terminal `return {...}` literal — what callers receive when they call the factory.

All three must be the same set of strings (and `returns:` declares this set explicitly when present — see §4.1.5). A mismatch surfaces as either `MISSING_PROVIDED_FUNCTION` (a `provides:` name has no `def`) or `MISSING_RETURN_KEY` (a `returns:` key is absent from the return dict). The most common author error is a typo in the dict literal:

```
nerve assembler :: APPLICATION
    kind: SERVICE
    provides: [assemble, disassemble]
    returns: [assemble, disassemble]
    ---
    def assembler() -> dict:
        def assemble(parts: list) -> str:
            return "".join(parts)

        def disassemble(whole: str) -> list:
            return list(whole)

        return {
            "asemble": assemble,         # ❌ typo: returned-dict key is 'asemble' not 'assemble'
            "disassemble": disassemble,
        }
```

The validator catches the typo via the returned-dict-keys ↔ `returns:` comparison and surfaces `MISSING_RETURN_KEY` naming the missing `assemble`. Without `returns:`, the typo would still ship; with it, the three-way coupling is enforced at build time. When the SERVICE nerve uses the class-bodied pattern instead of the factory pattern (see §2.2), the coupling reduces to two corners (`provides:` and `def` names — no returned dict); the validator's check is the same set comparison applied to the `def` names directly.

For class-bodied SERVICE nerves (no return dict), `provides:` is paired with `def` names only — the validator checks each `provides:` entry has a matching `def` inside the class body.

**Two surface forms.** `provides:` accepts two interchangeable surface forms. Choose per nerve based on what the author wants to declare.

*Flat form* (the original, unchanged since 0.x). One bare name per entry, inline or as a YAML block list:

```
provides: [read_file, write_file]

# or, equivalently, the PRE-7 block form:
provides:
  - read_file
  - write_file
```

*Structured form* (new in 0.15.0 — POST-3a). Each entry is `- <name>:` followed by an indented per-method `returns:` / `expects:` / `guarantees:` triple. Every triple slot is independently optional; an entry can declare just `returns:` or just `guarantees:` without supplying the others:

```
provides:
  - assemble:
      returns: "str — the assembled prompt"
      expects: "topic: str (non-empty)"
      guarantees: "result is non-empty; topic is escaped"
  - validate:
      returns: "bool — True iff topic is well-formed"
```

The per-method triple rides through the IR (under `components[].fields.provides_contracts`) and the emitted Python's `metadata={...}` dict (under the `"provides_contracts"` key). Introspecting agents (fr3d's MS 11/12/17 settings, budget, and OAuth nerves are the motivating consumers) read the per-method contract from the registry without re-parsing the source or recovering it from docstrings + type-hints. The IR omits the `provides_contracts` key entirely when every entry is bare — legacy flat-form nerves carry no new IR surface.

The structured form also tightens the three-way coupling above. When at least one entry carries a triple AND the body terminates with a `return {...}` literal, the validator additionally checks the returned-dict keys against the structured `provides:` names — closing the `"asemble"` typo class without requiring a separate `returns:` declaration. Class-bodied SERVICE nerves (no terminal return dict) skip the dict-key check silently; the flat `def`-name check still applies.

**Error guards on the structured form:**

- `MIXED_PROVIDES_FORMS` — a block mixes `- name:` items with bare `- name` items. Pick one form per block.
- `DUPLICATE_PROVIDES_NAME` — the same operation name appears twice in a structured block. Rename or remove the duplicate.
- `PARSE_ERROR` — an unknown sub-field (anything other than `returns`, `expects`, `guarantees`) appears under a `- name:` entry; or a sub-field repeats for the same entry.

**Strict-mode `return {...}` literal-key check (0.15.0 — POST-3c).** When a nerve declares `provides:` (flat or structured) AND its body terminates with a `return {...}` literal whose keys are all literal strings, the validator additionally compares the literal-string keys against the `provides:` set in both directions. A `provides:` name missing from the return dict OR a return-dict key absent from `provides:` fires `PROVIDES_KEY_MISMATCH` (warning in migration/dev, error in strict/release). This is the strict-mode generalisation of the structured-form `MISSING_RETURN_KEY` check (M-4 / POST-3a) extended to cover both directions and the flat form too — the canonical motivating typo (`return {"asemble": assemble}` vs `provides: [assemble]`) now surfaces on the flat form as well, not just the structured form. For structured nerves, POST-3c only fires the *extra-key* direction so `MISSING_RETURN_KEY` (which already covers the missing direction) and `PROVIDES_KEY_MISMATCH` never duplicate on the same author error.

The check is *literal-keys-only* by design: a body that builds its return dict via `dict(assemble=assemble, ...)` or a comprehension is silently skipped. False positives on legitimate dynamic returns would erode author trust in the check, and recovering the key set from a computed return would require running the body. Authors who need the strict-mode coverage on a body with computed keys should refactor to a literal `return {...}` (the canonical SERVICE-factory pattern already uses one).

#### 4.1.4 The `abstract` and `interface` Fields

`abstract: true` marks a nerve as an abstract interface definition. Abstract nerves may omit a body (the transpiler generates `NotImplementedError` stubs) or provide a body containing `raise NotImplementedError`. `interface` lists the method names that concrete implementations must define.

When a non-abstract nerve declares `depends_on` with `relation: CONSTRUCTS` targeting an abstract nerve, the transpiler validates that the concrete nerve's body defines all methods listed in the abstract's `interface`.

```
nerve LLMAdapter :: INFRASTRUCTURE
    kind: ADAPTER
    abstract: true
    interface: [chat, chat_stream]
```

**Capitalisation.** The boolean literals are **lowercase** — `abstract: true` and `abstract: false`. The Python-cased form `abstract: True` is a frequent agent slip (Python's `True` / `False` is title-case; the DSL's mirrors YAML / TOML, which are lowercase). The parser normalises both forms to the canonical lowercase value in the IR, so existing source with `abstract: True` continues to parse, but **new authoring should use `true` / `false`**: it keeps `.s0ma` files visually consistent with the other boolean-valued fields (`is_page_composer:`, `module_scoped:`), and it removes a low-grade source of review friction. The same rule applies to every boolean-valued DSL field — the canonical form is always lowercase.

A future strictness-mode pass may surface a warning on Python-cased boolean literals to nudge authors toward the canonical form; the current behaviour is parse-and-normalise (no warning).

#### 4.1.5 The `returns` Field

`returns` declares the keys in the dict returned by a function-bodied nerve (the dict-of-closures pattern). When present, the transpiler validates that the return statement includes a dict with all declared keys. Distinct from `provides` (which validates `def` names in the body for class-bodied nerves).

```
nerve CLIGateway :: PRESENTATION
    kind: SERVICE
    returns: [receive_message, send_response, start, stop]
```

#### 4.1.6 The `declares_attributes` Field (M18)

`declares_attributes` carries a list of `<namespace>:<attribute>` strings — structural claims a nerve makes about its output. The mechanism is domain-agnostic: HTML projects use it for landmarks (`landmark:header`, `landmark:main`, `landmark:nav`), HTTP projects use it for routes (`"route:GET /self"`), CSS-heavy projects use it for class names (`css_class:btn-primary`), RPC projects use it for method names (`rpc:projects.list`).

Each entry's namespace must match `[A-Za-z_][A-Za-z0-9_]*`; the attribute portion (everything after the first colon) is free-form non-empty text. Quoted entries (`"route:GET /self"`) accommodate attributes with spaces, slashes, or commas.

The field is purely descriptive on its own — it surfaces in the IR JSON (under `components[].fields.declares_attributes`) and `s0ma inspect`'s text output. To enforce uniqueness, the project configures a budget under `[tool.s0ma.attribute_budgets]` (see §4.13). When a budget for the namespace is configured, violations surface as `ATTRIBUTE_BUDGET_VIOLATION` at `s0ma check` / `s0ma build` time rather than at runtime.

```
nerve render_header :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Render the page <header> landmark."
    expects: "No arguments."
    guarantees: "Returns a <header>...</header> string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: [landmark:header]
    ---
    def render_header() -> str:
        return "<header>Site title</header>"
```

The parser rejects malformed entries (missing colon, empty namespace, non-identifier namespace, empty attribute) with a structural `PARSE_ERROR` carrying remediation; this guards against typos like `[header]` (no namespace) silently disabling the budget.

##### `is_page_composer:` (F3, feedback 5–6 follow-up)

`is_page_composer: true | false` marks a nerve as the scope root for the `exactly_one_per_page` shape of `[tool.s0ma.attribute_budgets]` (see §4.13). Default is `false`; the field is optional and additive — pre-F3 nerves stay unchanged.

When the project configures an `exactly_one_per_page` budget, the validator walks the `uses:` graph from each marked nerve's owning module, computes the reachable module set, and counts `<namespace>:<attribute>` occurrences across every nerve in that set. The budget enforces exactly-one occurrence per marked composer's reachable set. Marking is **explicit**: the validator only treats nerves with `is_page_composer: true` as scope roots. If the project configures `exactly_one_per_page` but no nerve in the project is marked, the resolver emits `NO_PAGE_COMPOSER_DECLARED` (error in every mode) — silent no-op is forbidden.

F3 replaces M18's heuristic interpretation ("a page is a top-level module in the `uses:` graph") with explicit declaration. The heuristic had documented edge cases (test modules looking like top-level pages, projects without `uses:` edges, fully-circular graphs) that F3 closes by promoting the page-composer role to first-class metadata in the IR. The field surfaces in `s0ma inspect` (the component's bracket label includes `page_composer` for marked nerves) and the IR JSON (under `components[].fields.is_page_composer` when `true`).

```
nerve compose_page :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Top-level page composer that assembles header, main, and footer landmarks."
    expects: "A string of body content."
    guarantees: "Returns a full HTML page."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    is_page_composer: true
    ---
    def compose_page(body: str) -> str:
        return render_header() + render_main(body) + render_footer()
```

#### 4.1.7 The `internal:` Field (POST-3d, 0.15.0)

`internal:` is an optional, purely descriptive sub-list of inner helper functions defined inside a nerve body. SERVICE nerves frequently follow a factory-closure pattern: the public `provides:` operations share small private helpers declared as inner `def` statements above the factory's `return {...}` dict. Those helpers live behind the closure — they are not components, they are not exported, and they have no `register_*()` call. Without `internal:`, an introspecting reader (or `s0ma inspect`) has no way to see the private surface short of reading the body.

```
nerve PromptAssembler :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Assemble and validate a topic-keyed prompt."
    expects: "topic: a non-empty string."
    guarantees: "assemble returns a non-empty rendered prompt; validate returns bool."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: [assemble, validate]
    internal:
      - _normalize_topic: "Strip whitespace and lowercase the topic"
      - _escape_html: "Escape HTML-special chars in the rendered prompt"
    ---
    def assembler():
        def _normalize_topic(topic):
            return topic.strip().lower()
        def _escape_html(s):
            return s.replace("<", "&lt;")
        def assemble(topic):
            return _escape_html(_normalize_topic(topic))
        def validate(topic):
            return bool(_normalize_topic(topic))
        return {"assemble": assemble, "validate": validate}
```

**Two surface forms.** `internal:` accepts the same inline / block-list duality as every other list-valued field on nerves, with one additional shape on the block form: each entry may carry an optional intent string after the colon.

*Inline form* (bare names only, no intents):

```
internal: [_normalize_topic, _escape_html]
```

*Block form* (each entry is either bare `- _name` or `- _name: "intent"`; the two shapes may be mixed in the same block):

```
internal:
  - _normalize_topic: "Strip whitespace and lowercase the topic"
  - _escape_html: "Escape HTML-special chars in the rendered prompt"
  - _build_context_dict   # bare entry — no intent declared
```

Each entry name must be a Python identifier (`[A-Za-z_][A-Za-z0-9_]*`); a non-identifier name is a `PARSE_ERROR`. Duplicate names within the same block are also a `PARSE_ERROR`. The intent string is optional per entry; quoted (`"..."` / `'...'`) and bare-text forms both parse, with one matched pair of outer quotes stripped from the stored value.

**No codegen effect, no registry effect.** `internal:` is descriptive only:

- The Python emitter ignores the field entirely — no `register_*()` call is generated for any entry, and no new key appears in the emitted `metadata={...}` dict on the `@component` decorator. The nerve body emits unchanged; the inner helpers remain inner helpers.
- The validator does not enforce that every named entry actually appears as a `def` inside the body. The author's `internal:` declaration is the author's own contract with future readers and tooling — silent drift between the list and the body is acceptable (the field exists for introspection, not for cross-check).

**IR and inspect semantics.** When at least one entry is declared, the value rides through the nerve IR record (`fields.internal_helpers` in the `.s0ma.json`) as an ordered list of dicts `{"name": str, "intent"?: str}` — the `intent` key is omitted for bare entries. `s0ma inspect`'s text output renders a separate `Internal helpers (<n>):` sub-section under each nerve that has them, so a reader can see the private surface at a glance without scrolling the body:

```
Components (1):
  internal_demo::assembler [PUBLIC SERVICE nerve]
    A SERVICE nerve with private inner helpers.
    Internal helpers (2):
      - _normalize_topic: Strip whitespace and lowercase the topic
      - _escape_html: Escape HTML-special chars in the rendered prompt
```

Legacy nerves without `internal:` carry no new IR surface — the key is omitted from `components[].fields` entirely when `internal_helpers` is empty.

**Why this exists.** fr3d's MS 2 BundleEmitter and MS 16-core update-diff nerves carry deep factory-closure bodies with several inner helpers each. Without an introspection surface, the only way for a contributor (or downstream tooling) to discover the private API was to read every nerve body. `internal:` lets the author publish that surface as structured metadata while keeping the runtime semantics unchanged — the helpers stay invisible to the registry, stay non-importable across modules, and stay free to evolve without a deprecation cycle.

#### 4.1.8 The `expected_exceptions:` Field (POST-12a, 0.16.0)

`expected_exceptions:` is an optional list of Python-namespace exception types that a nerve catches by design — typically inside `try / except` blocks in the body. It is the Python-side companion to `raises:` (§4.1.1) and exists specifically because `raises:` is restricted to s0ma cells in the component-reference namespace, so the canonical place to declare that, say, a nerve catches `json.JSONDecodeError` had been "nowhere structured" — only the body's `except` clause or a hand-rolled docstring.

```
nerve fetch_settings :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Fetch user settings from the upstream JSON endpoint."
    expects: "user_id: str (uuid)"
    guarantees: "returns a UserSettings dict; never raises on transport failure."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    expected_exceptions: [json.JSONDecodeError, urllib.error.HTTPError]
    ---
    def fetch_settings(user_id):
        try:
            ...
        except json.JSONDecodeError:
            ...
        except urllib.error.HTTPError:
            ...
```

**Surface forms.** `expected_exceptions:` accepts the standard inline / block-list duality. The inline form is a bracketed list of dotted Python paths:

```
expected_exceptions: [json.JSONDecodeError, urllib.error.HTTPError]
```

The block form (PRE-7 block-list re-assembler) is identical in semantics:

```
expected_exceptions:
  - json.JSONDecodeError
  - urllib.error.HTTPError
  - requests.exceptions.Timeout
```

**Why the distinction with `raises:` matters.** `raises:` is a structural contract: every entry must be a declared s0ma `EXCEPTION` cell, the validator wires a `RAISES` edge into the dependency graph, and the registry uses it to reason about exception propagation across the self-model. `expected_exceptions:` is *metadata*: dotted Python paths are accepted verbatim with no namespace check, no edge is derived, and the registry does not introspect the entries beyond echoing them in the registered `metadata={...}` dict. The two fields document the two sides of the exception envelope — what a nerve might raise (s0ma cells) versus what it deliberately catches (Python types).

**No validation side effect today.** The 0.16.0 release lands `expected_exceptions:` as pure metadata: the parser accepts any dotted Python path (`json.JSONDecodeError`, `some.deeply.nested.Custom`), the IR round-trips the list, and the emitter weaves it into the `metadata={...}` dict. A future minor release may add a strict-mode pass that cross-checks the body's `except` clauses against the declared envelope, but today the field is declarative only — its primary value is downstream tooling (doc renderers, future linters, the `s0ma deferred-surface` report mentioned in §4.1.9).

**IR and inspect semantics.** When at least one entry is declared, the value rides through the nerve IR record (`fields.expected_exceptions` in the `.s0ma.json`) as an ordered list of strings. `s0ma inspect`'s text output surfaces the list on its own line under the nerve row:

```
Components (1):
  fetch_settings_demo::fetch_settings [PUBLIC SERVICE nerve]
    Fetch user settings from the upstream JSON endpoint.
    Expected exceptions: json.JSONDecodeError, urllib.error.HTTPError
```

Legacy nerves without the field carry no new IR surface — the key is omitted from `components[].fields` entirely when `expected_exceptions` is empty.

#### 4.1.9 The `deferred:` Field (POST-12f, 0.16.0)

`deferred:` is an optional string-valued annotation that marks a nerve body as a stub awaiting fill. The value is a free-form reason — anything from a one-word "TODO" to a paragraph describing the unblocking signal — so the project's stub surface is discoverable from the registry rather than from inline `# TODO:` comments.

```
nerve build_settings_diff :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Compute a settings diff between two snapshots."
    expects: "before, after: UserSettings"
    guarantees: "returns a SettingsDiff record."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    deferred: "Waiting on Phase 3 SettingsDiff schema finalisation (see ADR-014)."
    ---
    def build_settings_diff(before, after):
        raise NotImplementedError  # POST-12f stub
```

**Surface form.** `deferred:` is a single string value (quoted or bare), parsed via the standard `_parse_string_field` path. An empty or absent line is equivalent to no annotation (the `.deferred` attribute is `None`).

**Same field on cells and ganglia.** The annotation is identical on `cell` (§4.2) and `ganglion` (§4.3) declarations: a MODEL cell whose body is a placeholder `class X: pass`, or a ganglion whose `on_anomaly` body is a `pass`, can carry the same `deferred: "<reason>"` line. The reporter described below enumerates entries across all three declaration types.

**IR and inspect semantics.** The reason string rides through the IR (`components[].fields.deferred`) and into the emitted `metadata={"deferred": "..."}` dict. `s0ma inspect`'s text output appends a `deferred` tag to the row's bracket label and renders the reason on its own sub-line:

```
Components (1):
  diff_demo::build_settings_diff [PUBLIC SERVICE nerve, deferred]
    Compute a settings diff between two snapshots.
    Deferred: Waiting on Phase 3 SettingsDiff schema finalisation (see ADR-014).
```

**Reporter — `s0ma deferred-surface` + `s0ma check --report-deferred`.** The 0.16.0 CLI gains both a standalone subcommand and a flag on `s0ma check` that enumerate every deferred-marked declaration in the resolved project:

```bash
$ s0ma deferred-surface src/

Deferred surface (3 declaration(s)):
  a_mod::a_deferred [nerve]
    reason: needs reviewer signoff
    at: src/a_mod.s0ma:8
  b_mod::BDeferred [cell]
    reason: schema review pending
    at: src/b_mod.s0ma:8
  c_mod::c_ganglion [ganglion]
    reason: observability decisions pending
    at: src/c_mod.s0ma:8
```

The same payload is available as JSON via `--format json`. **The reporter always exits 0** — deferred declarations are explicitly not a build blocker; the field exists to make the stub surface visible, not to gate releases. When run as `s0ma check --report-deferred`, the report appears after the standard diagnostic block so warnings/errors stay visible alongside the deferred surface.

#### 4.1.10 The `consumes_via_dict:` field (POST-12d, 0.16.0)

`consumes_via_dict:` declares **duck-typed couplings** — contract relationships where the nerve body reads an injected dependency via dict-key access (`config["api_key"]`) rather than attribute access (`config.api_key`). The contract relationship was historically invisible because the body's access shape is dict-key indirection, not direct name resolution; the field makes the relationship explicit so the registry's introspection surface exposes the coupling.

```
nerve fetch_secrets :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Fetch API secrets from the settings dict."
    expects: "config: SettingsDict, flags: FeatureFlags"
    guarantees: "Returns the requested secret value."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    consumes_via_dict:
      - contract: SettingsDict
        param: config
      - contract: FeatureFlags
        param: flags
    ---
    def fetch_secrets(config, flags):
        if flags["billing_v2"]:
            return config["billing_api_key"]
        return config["api_key"]
```

**Surface form.** Each entry is a structured block-list item with two MANDATORY sub-fields: `contract:` (the named contract) and `param:` (the parameter name on the nerve body's outer function). The block-list form is the only legal surface; an inline `consumes_via_dict: [...]` shape is intentionally not supported because the structural pair is the field's reason for existing.

**Validator passes.** `s0ma check` enforces both halves of every entry:

* **Contract resolution.** Each `contract:` value MUST resolve to either a known cell in the current module OR a `uses:` target. Unknown contracts fire `CONSUMES_VIA_DICT_INVALID` at error severity in every strictness mode — the field declares a real dependency, so an unresolvable target is a hard authoring bug.
* **Param resolution.** Each `param:` value MUST be a parameter on the nerve body's outer function (closure-scoped or local-variable shadows do not count). The check parses the body via `ast.parse`, takes the first top-level `FunctionDef` / `AsyncFunctionDef`, and looks at every positional / keyword-only / vararg / kwarg parameter. Mis-resolution fires the same `CONSUMES_VIA_DICT_INVALID` code.

**Why the explicit declaration matters.** When a SERVICE nerve takes `config: SettingsDict` and reads `config.api_key`, the body's `Attribute(value=Name("config"), attr="api_key")` AST node lets the registry trace the type-based coupling. When the same SERVICE reads `config["api_key"]`, the body's `Subscript(value=Name("config"), slice=Constant("api_key"))` carries no contract reference at all — the dict is opaque at the registry level. `consumes_via_dict:` is the explicit declaration that closes that introspection gap. The motivating consumer is fr3d's settings / OAuth pipeline (where many SERVICEs intentionally accept the entire settings map and read keys directly to avoid threading a 30-attribute dataclass).

**No codegen side effect.** The field rides through the IR (`components[].fields.consumes_via_dict` as a list of `{"contract": ..., "param": ...}` records) and the emitted `metadata={...}` dict (under the same key). The body emits unchanged — the field is metadata, not a binding; no import for the contract is added.

**IR and inspect semantics.** `s0ma inspect`'s text output renders a "Consumes via dict (N):" sub-section under the nerve row, with each entry shown as `<contract> via param '<name>'`:

```
Components (1):
  cvd_module::fetch_secrets [PUBLIC SERVICE nerve]
    Fetch API secrets from the settings dict.
    Consumes via dict (2):
      - SettingsDict via param 'config'
      - FeatureFlags via param 'flags'
```

Legacy nerves with no field carry no new IR surface — the key is omitted when `consumes_via_dict` is empty.

#### 4.1.11 The `metadata:` Field (DSL-M1, 0.17.0)

`metadata:` is an authored, per-declaration block map of opaque facts that ride the declaration end to end — IR, emitted registration, runtime `ComponentSpec.metadata`. It exists for exactly the facts the language deliberately does not model: served-surface identities (`mcp_uri`, `mcp_prompt_title`), informational architecture notes (`wraps`, `composes`), tool annotations, retry budgets — anything a downstream consumer wants to read from the registry without re-parsing source.

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

**Shape (the L-1 set).** Block-map form only — there is no inline `metadata: {...}` form. Keys are identifiers, unique within the map, one `key: value` line per entry at one indent level below the field. Values are exactly one of: a quoted string, an integer, a float, a boolean (the lower-case literals `true` / `false`), or a bracketed list of strings (entries quoted, or bare when identifier-shaped — the same list lexing `declares_attributes:` uses). Nested maps and null values are out.

**Shape-only validation (P-2).** The language validates the shape and NEVER interprets values — `metadata:` must not become a side-channel for derived facts. Three always-error codes guard it: `METADATA_INVALID_KEY` (key not identifier-shaped, or authored twice), `METADATA_INVALID_VALUE` (value outside the shape set: null entries, unquoted bare tokens, nested maps, malformed list entries, the inline form), and `METADATA_RESERVED_KEY` (key collides with an emitter-written registration key — see the reserved-key rule in §4.14; the remediation points at the declaration field that owns the fact, e.g. authored `visibility` → "set the declaration's `visibility:` field instead").

**Flow.** Authored order is preserved everywhere: the IR carries the map as a JSON object under `components[].fields.metadata` (omitted entirely when not authored), the emitter APPENDS the authored items after its own registration keys in the existing `metadata={...}` dict (§4.14), and the runtime `ComponentSpec.metadata` therefore carries emitter keys first, authored keys after, in authored order. Applicability: `metadata:` is accepted on `nerve`, `cell`, and `ganglion` — exactly the declaration kinds whose emitted registration already carries a runtime `metadata=` dict. Other kinds do not accept the field.

#### 4.1.12 The `serves_as:` Field (DSL-M1, 0.17.0)

`serves_as:` carries a nerve's PUBLIC SERVING NAME when it differs from the declaration identifier. The founding evidence is MCP surfaces: tool and prompt names are identifier-shaped, so registry-disjointness forces suffixed declarations (`check_tool` serving as `check`) — before this field, every consumer re-invented the rename at its binding layer and the suffixed identifier leaked into client-visible schema titles via the emitted callable's `__name__`.

```
nerve check_tool :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Validates .s0ma source without emitting artifacts — the agent's inner loop"
    serves_as: check
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def check_tool(path: str | None = None) -> dict[str, Any]:
        ...
```

**Shape and uniqueness.** A bare identifier (the quoted form is accepted; bare is canonical). `SERVES_AS_INVALID` (error, every mode) rejects non-identifier values — the served name becomes the emitted callable's `__name__`, so it must be a legal identifier; URI-shaped served names belong in `metadata:`. `SERVES_AS_COLLISION` (error, every mode) enforces one flat served-name namespace, validated per module AND per project build; equality with the declaration's own identifier is permitted (a harmless idempotent rename). Nerve-only: every served surface in evidence is a nerve, and the stamp needs an emitted module-level callable.

**Artifacts.** The IR carries `components[].fields.serves_as`; the emitted registration dict carries the reserved `serves_as` metadata key; and the emitter stamps the emitted callable's `__name__` and `__qualname__` with the served name immediately after the decorated def (see §4.10 for the identity semantics and §4.14 for the emitted shape).

#### 4.1.13 The `covered_by:` Field (DSL-M2, 0.17.0)

`covered_by:` is the external test-evidence credit — a bracketed list of non-empty strings naming the out-of-DSL suites (or rationale prose) that cover this declaration. Entries are quoted for anything beyond a bare identifier. The field is accepted on nerve, cell, and ganglion.

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

**Semantics.** Authored-opaque: the language validates SHAPE only (`COVERED_BY_EMPTY`, error in every mode, for an empty list or any empty/whitespace entry) and never resolves the strings — honesty is the author's burden, and the claim is auditable because it rides the IR (`components[].fields.covered_by`), the emitted registration metadata (reserved `covered_by` key), and doc-ref renderings (a `Covered by:` line after the intent, §4.12).

**Release-gate credit.** Release-mode `MISSING_TEST_COVERAGE` is satisfied by EITHER in-language `tests:` coverage OR a non-empty `covered_by:` (§4.8). The credit injects no synthetic test targets — "tested in-language" and "externally covered" stay distinguishable in the record. For the wrapper-import recipe (running DSL-authored tests inside a plain pytest suite), see the documentation-subsystem guide.

#### 4.1.14 The `forbids:` Field

`forbids:` names what a part must never do. Its meaning is normative:

> **KEY:** What the part must never do, however it is called and whatever happens while it runs. s0ma checks that the line is there and what state it is in; it does not read the sentence. `none` states that nothing is ruled out. It is an answer, not a way to skip the line.

The line belongs to `nerve` and `ganglion`. A nerve writes it directly after `guarantees`; a ganglion writes it directly after `on_anomaly`, and there it says what the evaluator must never do while it assesses. Each sentence below restates its declaration's own `intent`, and each body keeps it:

```
nerve read_settings :: INFRASTRUCTURE
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Reads the project's settings file without changing anything on disk"
    expects: "path names an existing UTF-8 text file"
    guarantees: "Returns the text of the file at path"
    forbids: "Never creates, changes or deletes a file, even when the read fails."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def read_settings(path: str) -> str:
        with open(path, encoding="utf-8") as handle:
            return handle.read()

ganglion watch_settings_reads :: INFRASTRUCTURE
    visibility: INTERNAL
    intent: "Watches settings reads from outside and passes each signal on unchanged"
    observes: [read_settings]
    scope: FUNCTION_BOUNDARY
    priors: "A settings read returns the file's text and raises nothing"
    on_anomaly: "Reports the failed read so a person can check the file"
    forbids: "Never calls the part it observes or changes the signal it receives."
    ---
    def watch_settings_reads(signal):
        return signal
```

**Shape and states.** One text value, in every shape `expects` accepts: an inline quoted string, a multi-line quoted string, or a `|` block. The whole-value forms `none` and `pending("reason")` are states; a quoted `"none"` is content, like any other sentence. Every shape, the empty quoted string included, is handled exactly as `expects` handles it.

```
forbids: "<what it must never do>"
forbids: |
    <what it must never do, written as a block>
forbids: none
forbids: pending("<why the answer is not written yet>")
```

The line is required on both kinds: an omitted line is `SEMANTIC_REQUIRED_STATE_OMITTED` in every mode. `none` earns completeness credit, because the line's state set includes N; `pending("reason")` earns none, warns in `migration` and `dev`, errors in `strict` and `release`, and always blocks a release (§4.14.5). On any other declaration the line is `UNKNOWN_FIELD`, and the report says where it belongs. It is a line of the whole declaration: a `provides:` entry (§4.1.3) does not accept it, and a nerve's one `forbids:` covers every operation the nerve provides.

**What s0ma checks, and what it does not.** s0ma checks that the line is written and which state it is in. It does not read the sentence: no part of the toolchain interprets it, executes it or tests the body against it, and core's coverage and contract verifiers neither count nor run it. Whether the body keeps the prohibition is the author's burden and a reviewer's question; the line makes the claim visible wherever the part is read.

**Where the line travels.** The IR carries it at `components[].fields.forbids`, as a state object like its siblings (§4.14.5). A written sentence reaches the runtime in `Contract.forbids`, a list of strings: a nerve's emitted `Contract(...)` gains `forbids=[...]` after `postconditions`, a ganglion's `@component(...)` gains `contracts=Contract(forbids=[...])`, and core's self-model text lists the sentence under `Forbids:`; `none` and `pending` emit nothing. The build's self-context companion, `self_context.json`, carries a written sentence or a `pending` state with the component's other authored details, and `none` adds nothing there. A `doc-ref` renders the line when `sections:` names `forbids` (§4.12.1). An adoption draft gives each drafted nerve a placeholder asking the person to say what the part must never do, however it is called, or to write `none` if there is nothing to rule out; project and declaration scaffolds write the line as `none` or as a `TODO` sentence to replace.

**How it differs from `guarantees`.** `guarantees` is a promise about the result once the part has run; `forbids` is a prohibition that holds on every path, a failed call included. In the example above, the nerve's guarantee is the text it returns, while its prohibition holds as well when the read raises. A sentence about what the part delivers belongs in `guarantees`; a sentence that rules out something the part could otherwise do belongs in `forbids`.

**Migration.** A source written before the release that carries this change has no `forbids:` line. `s0ma migrate grammar --apply` (§4.14.5) writes `forbids: none` into each nerve and ganglion that lacks one; wherever there is something to rule out, the author then replaces that `none` with a sentence.

### 4.2 `cell` (Structural Component)

**A cell is a structural artifact that does not perform system-level logic.** Use `cell` for data models, configuration, constants, type definitions, exception types, and enums.

The boundary: *does this logic serve the data model's own invariants (cell) or the system (nerve)?*

```
cell <n> :: <LAYER>
    kind: <KIND>
    visibility: <PUBLIC | INTERNAL | TEST>
    intent: "<why this component exists>"
    schema: "<what data this represents>"
    invariants: "<what must always be true>"
    deferred: "<reason this body is a stub>"
    dataclass_invariants: [<Python boolean expressions>]  # MODEL only
    covered_by: ["<external suite path or rationale>", ...]
    metadata:
        <key>: <"string" | int | float | true | false | [list, "of", strings]>
    ---
    <Python class, constant, or type definition>
```

**Which lines to write:** §4.14.5 is the one table of which lines a cell must write and which of them may be `none` or `pending("reason")`; it is generated from the toolchain's field classification, so it is not repeated here. Fields a cell shares with a nerve keep one contract each: `deferred` (POST-12f) is §4.1.9; `metadata` (DSL-M1) is §4.1.11, merging into the class-cell `@component` dict or the CONSTANT/TYPE `register_constant`/`register_type` dict per `kind`; and `covered_by` (DSL-M2) is §4.1.13, riding the same IR/metadata/doc-ref path as honest coverage documentation — the release gate reads PUBLIC nerves and does not consult cells. `category` is §4.2.5, and `dataclass_invariants` (POST-12c, MODEL only) is §4.2.7.

#### 4.2.1 Exception Types as Cells

Declared as cells with `kind: EXCEPTION`.

```
cell SignalValidationError :: APPLICATION
    kind: EXCEPTION
    visibility: PUBLIC
    intent: "Raised when a SignalEnvelope fails validation."
    schema: "Exception subclass. message: str."
    invariants: "message is non-empty."
    ---
    class SignalValidationError(Exception):
        def __init__(self, message: str):
            self.message = message
            super().__init__(message)
```

#### 4.2.2 Embedded Content via `@file()`

A `CONSTANT` cell whose value is a large block of text — HTML, SQL, prompt templates, JSON schemas — should not be inlined as a triple-quoted Python string. Triple-quoted bodies suppress editor highlighting and linting for the embedded language, drown the cell's metadata in noise, and turn `.s0ma` files into 1000-line walls of unrelated syntax. The `@file()` directive solves this by referencing the content as an external file.

**Grammar.** A `CONSTANT` cell may use *either* an inline `--- ... ---` body *or* a `content: @file("path")` field, but not both. Combining the two forms is a `PARSE_ERROR`. The directive is currently restricted to `kind: CONSTANT`; using it on any other cell kind is a `PARSE_ERROR`.

```
cell VIZ_TEMPLATE :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Self-contained HTML5 visualization template."
    schema: "string of valid HTML5"
    content: @file("templates/viz.html")
```

**Path resolution.** Relative paths resolve against the `.s0ma` source's directory. Absolute paths are accepted but discouraged — they break portability across checkout locations. The path is captured verbatim in the build manifest so authors recognise what they wrote.

**Build-time semantics.** The transpiler reads the file as UTF-8 text at parse time, computes its `sha256:<hex>`, and embeds the content into the generated Python via `<NAME> = r"""..."""` (or `<NAME> = repr(content)` when the content contains the triple-quote sequence — the M2 `ast.parse` build invariant catches any encoding mistake). The `build.s0ma.json` manifest gains an `external_content_files` map keyed by `"<module>::<cell>"` listing the path-as-written and the content hash. Binary content is out of scope for v0.12.0 — only UTF-8 text files embed.

**Cache invalidation.** The cache key for a module that uses `@file()` includes the SHA-256 of every embedded file. Editing the embedded HTML/SQL/prompt invalidates the consuming module's cache and triggers a re-transpile, so the `.py` is never stale relative to its inputs.

**Source maps.** The `.s0ma.map` for a module with `@file()` records `body_source_file` (the path of the embedded file) and `body_source_lines` (the line range within that file) on the affected cell. Project-resolved invocations (a `[tool.s0ma]` table was found) record the path **project-root-relative in POSIX form** — the same INV-5 portable-path policy the map's `source_file` field follows — so committed build output containing embedded templates stays byte-identical across machines, working directories, and operating systems; synthetic (no-project) invocations keep the resolved absolute path, since there is no root to be relative to. Debuggers and error reporters resolve a relative redirect against the project root and follow it so a runtime error in the embedded literal points at the original `.html` / `.sql` / `.txt` rather than the `.s0ma` line that carries the directive.

**Errors.** `EMBEDDED_FILE_NOT_FOUND` (severity `error` in every strictness mode) fires when the referenced file is missing, unreadable, or not decodable as UTF-8. The diagnostic carries the cell name, the path-as-written, and the absolute resolved path so the author can fix either side.

#### 4.2.3 CONSTANT Cell Name Mirrors Body Identifier

For `kind: CONSTANT` cells with an inline body, the cell declaration name **must equal** the Python identifier the body assigns to at top level. The transpiler emits `from <module> import <cell_name>` so consumers reach the value via the cell's name; if the body assigns to a different identifier, the import resolves to a `NameError` / `ImportError` at runtime.

```
# Correct — cell name matches the body's top-level assignment.
cell VIZ_TEMPLATE :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Self-contained HTML5 template."
    schema: "string of valid HTML5"
    ---
    VIZ_TEMPLATE = """<!doctype html>..."""
```

```
# Incorrect — cell name and body identifier disagree.
cell VizTemplate :: PRESENTATION        # <-- declared name
    kind: CONSTANT
    visibility: PUBLIC
    intent: "..."
    schema: "..."
    ---
    VIZ_TEMPLATE = """..."""             # <-- assigned name
# Validator emits CONSTANT_NAME_MISMATCH; the transpiler would
# otherwise emit `from <module> import VizTemplate`, against an
# actual identifier of `VIZ_TEMPLATE` — a runtime ImportError.
```

A body with multiple top-level assignments is allowed as long as the cell name appears among the assigned identifiers — the canonical pattern is `_X = compute(); FOO = _X`, where `FOO` is the public cell name and `_X` is a private helper.

**Errors.** `CONSTANT_NAME_MISMATCH` (severity `error` in every strictness mode) fires when no top-level `Assign` or `AnnAssign` in the body targets the cell name. The diagnostic carries the cell name and the list of identifiers the body actually assigns to, so the author can pick which side to rename. Cells whose body is supplied via `content: @file("...")` (§4.2.2) are exempt from this check by construction: the codegen synthesises `<cell_name> = <literal>` from the embedded file contents, guaranteeing equality.

**Style.** Use `UPPER_SNAKE_CASE` for both the cell name and the body identifier; this is the convention the project's other CONSTANT cells follow.

**The literal rides the IR.** When a `CONSTANT` cell's body assigns a simple literal to the cell's name at top level, the canonical IR carries that literal at `components[].fields.value`, the emitted `register_constant(...)` call passes it as `value=`, the registry keeps it as `metadata["value"]`, and the build's self-context companion carries it, so a self-model answers "what is the floor" with the number rather than only with the sentence written about it. A simple literal is an `int`, a finite `float`, a `str`, a `bool` or `None`, or a flat tuple or list of those; tuples are carried as JSON arrays on every surface so the surfaces agree. The key is present only when such a literal exists, so a constant whose value is `None` is told apart from a constant assigned an expression, a name, a dict, a nested sequence, an embedded `content: @file(...)` body (the file is recorded by hash in the build manifest instead), or a literal whose JSON form exceeds 1,024 bytes; those carry no value at all. `value` is therefore a reserved registration-metadata key (§4.14).

#### 4.2.4 Choosing visibility for cells consumed only by tests

When a `cell` (or `nerve`) exists only to support a test — a fixture-style `CONSTANT`, a stub `MODEL`, a helper `EXCEPTION` — the impulse to reach for `visibility: INTERNAL` is wrong. `INTERNAL` forbids cross-module `uses:` from any other module (§4.10.1, ADR-008), *including* test modules. The transpiler emits `NOT_EXPORTED` the moment a sibling-module test references the component. The fix is `visibility: TEST`: TEST-visibility components are reachable from any module that contains at least one `test` declaration (a "test consumer"), but invisible to production callers. They never appear in `exports:` and are exempt from `NOT_EXPORTED`. Use `INTERNAL` only when you genuinely mean "no cross-module access, including tests" — typically when the component captures private invariants the tests for *this* module exercise indirectly.

```
cell SAMPLE_PROMPT :: APPLICATION
    kind: CONSTANT
    visibility: TEST          # not INTERNAL — tests in test_*.s0ma need this.
    intent: "Canonical prompt fixture used across prompt-formatter tests."
    schema: "string"
    ---
    SAMPLE_PROMPT = "Tell me a joke about {topic}."
```

See §5 (the `visibility: TEST` semantic surface) and ADR-008 for the underlying rule. A future `s0ma check` info-severity finding (`TEST_REACHABLE_FROM_INTERNAL_HINT`) will surface this trap automatically; until then, this paragraph is the canonical reference.

#### 4.2.5 The `category` field: `capability` vs `behaviour`

A cell may declare a high-level role via the optional `category:` field. Two values are accepted, both lower-case:

| Value | Meaning |
|---|---|
| `capability` | The cell encodes a capability of the system — a static configuration value, an enabled feature, a registered handler, anything whose presence/absence changes *what the system can do*. Adding or removing a capability cell is a meaningful surface change. |
| `behaviour` | The cell encodes the behaviour of an existing capability — tuning constants, default thresholds, branching policy, anything that adjusts *how the system acts within its existing capabilities*. Editing a behaviour cell is an in-place tweak, not a surface change. |

The field is optional. Cells without `category:` parse with the field absent (the IR omits the key entirely; downstream tools see no metadata entry). Any value other than `capability` or `behaviour` is a `PARSE_ERROR` with a remediation naming the two valid alternatives.

```
cell EnabledIntegrations :: APPLICATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Set of integration names the runtime activates at startup."
    schema: "frozenset[str]"
    category: capability
    ---
    EnabledIntegrations: frozenset[str] = frozenset({"gmail", "slack"})

cell RateLimitWindow :: APPLICATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Tuning constant for the per-user rate limit window."
    schema: "int (seconds)"
    category: behaviour
    ---
    RateLimitWindow: int = 60
```

**IR and emit semantics.** When set, the value rides through the cell IR record (`fields.category` in the `.s0ma.json`) and is woven into the cell's `metadata` dict on the emitted `@component` / `register_constant` / `register_type` call. `s0ma inspect` surfaces the value in the cell row's bracket label (`[PUBLIC CONSTANT cell, category=capability]`) so the role is visible at a glance, parallel to how `is_page_composer:` surfaces on nerves.

**Why this exists.** Snapshot-diff tooling that classifies registry changes for downstream consumers (notification subsystems, audit logs, deployment gates) has historically maintained a static name-pattern rule table to derive "capability vs behaviour" from cell names. The `category:` field lets the classification come from the registry itself, eliminating the drift between the rule table and the live surface.

#### 4.2.6 The `placeholders:` field on embedded CONSTANT cells (POST-12b, 0.16.0)

A `CONSTANT` cell whose body comes from an embedded file (`content: @file("path.html")`, §4.2.2) may declare which **magic-string markers** the embedded file is asserted to contain. The motivating shape is a downstream template renderer that substitutes runtime values (`__SYSTEM_NAME__`, `__GRAPH_DATA_JSON__`, `__USER_ID__`) into the cell's string at runtime — the `placeholders:` field is the author's explicit declaration of which markers the file carries so the build can cross-check the surface before runtime.

```
cell VIZ_TEMPLATE :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Self-contained HTML5 viz with runtime-substituted system name and graph data."
    schema: "HTML5 with two embedded placeholder markers"
    placeholders: [__SYSTEM_NAME__, __GRAPH_DATA_JSON__]
    content: @file("templates/viz.html")
```

Inline and block-list forms are both accepted (PRE-7 grammar):

```
    placeholders:
      - __SYSTEM_NAME__
      - __GRAPH_DATA_JSON__
```

**Placeholder convention.** Each entry MUST match the pattern `__[A-Z][A-Z0-9_]*__` — two underscores, an uppercase letter, zero or more uppercase letters / digits / underscores, two underscores. The convention deliberately excludes lowercase or mixed-case dunders so Python's own `__init__` / `__name__` / `__all__` shapes are never false-positive matches. The pattern is the *exact* regex the validator uses when scanning the embedded file for present-but-undeclared markers.

**Field contract — `placeholders:` is only meaningful with `@file()`.** Declaring `placeholders:` on a CONSTANT cell whose body is inline (`--- ... ---`) is a `PARSE_ERROR`. The field describes which markers the *external* file contains; an inline body can interpolate values directly via string formatting at runtime, so there is no external content for the validator to cross-check against. The parser raises a diagnostic naming the cell and pointing at the two clean shapes (drop the field, or replace the inline body with `content: @file("...")`).

**Validator passes.** `s0ma check` runs two cross-checks against the embedded file's verbatim content:

* **Declared → present.** Every entry in `placeholders:` MUST appear at least once in the file. A declared placeholder that is absent fires `PLACEHOLDER_NOT_FOUND` at error severity in every strictness mode — the build would emit a constant string missing the marker the runtime needs, producing a silent rendering bug.
* **Present → declared.** Any placeholder-shaped string in the file (matching the regex above) that is NOT listed in `placeholders:` fires `UNDECLARED_PLACEHOLDER` (warning in migration/dev, error in strict/release). The lint catches the silent-drift class where a marker is added to the file without updating the cell declaration.

The two passes together pin the symmetry: the declared marker set and the actual marker set must agree. Authors who do not declare `placeholders:` at all still get the second pass (the file is scanned, any markers found are reported as undeclared) so adopting the convention has no migration cost — the lint nudges authors toward the explicit declaration once they introduce markers.

**IR semantics.** The declared list rides through the IR under `components[].fields.placeholders` so downstream template renderers (and authoring tools that need to know which markers the embedded template carries) can read the declared set without re-parsing the source. Legacy cells with no field carry no new IR surface; the key is omitted when `placeholders` is empty.

#### 4.2.7 The `dataclass_invariants:` field on MODEL cells (POST-12c, 0.16.0)

A `MODEL` cell may declare a list of **machine-readable invariants** — small Python boolean expressions authored against the dataclass's fields — that describe properties the model is expected to satisfy. The motivating shapes are bounded-collection contracts (`len(latency_samples) <= 100`), ratio / probability ranges (`0.0 <= ratio <= 1.0`), and structural invariants on enum-like state machines (`stage in ("init", "running", "done")`).

```
cell Stats :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "Rolling statistics window."
    schema: "Dataclass with samples list and a normalised ratio."
    dataclass_invariants:
      - "len(samples) <= 100"
      - "0.0 <= ratio <= 1.0"
    ---
    @dataclass
    class Stats:
        samples: list = field(default_factory=list)
        ratio: float = 0.5
```

Inline and block-list forms are both accepted (PRE-7 grammar):

```
    dataclass_invariants: ["len(samples) <= 100", "0.0 <= ratio <= 1.0"]
```

**Field contract — only on MODEL cells.** Declaring `dataclass_invariants:` on a CONSTANT / CONFIG / ENUM / EXCEPTION / TYPE cell is a `PARSE_ERROR`. The field is named for its scope — it describes invariants the *dataclass's fields* must satisfy — and other cell shapes (a CONSTANT literal, an EXCEPTION class) carry no fields to constrain. The parser raises a diagnostic naming the cell and pointing at the remediation (change kind to MODEL or drop the field).

**Not runtime-evaluated by s0ma.** The invariants ride through the IR and the registered `metadata={...}` dict as verbatim Python expression strings; the build does *not* generate runtime assertions, post-init checks, or any enforcement code. The field is **pure metadata** for downstream introspection — a future linter, doc renderer, or contract-enforcing runtime might pick the list up and `eval` it, but the 0.16.0 surface is declarative only. Authors who want runtime enforcement still write a `__post_init__` (or use a `dataclass` validator library) explicitly.

**Syntax check.** Every entry is fed through `ast.parse(expr, mode="eval")` at `s0ma check` time. A syntactically invalid expression (mismatched parens, illegal operator chains, etc.) raises `INVALID_DATACLASS_INVARIANT` in every strictness mode. The check exists so a downstream consumer that *does* try to evaluate the expressions never crashes opaquely on a malformed entry — the contract pinned by the field is that every declared invariant is at least machine-readable as a Python expression. Validation of *semantic* correctness (does the expression reference real fields? does the type system permit the comparison?) is out of scope for 0.16.0 and intentionally deferred.

**IR + metadata.** The declared list rides through the IR under `components[].fields.dataclass_invariants` and through the emitted `metadata={...}` dict under the same key. Legacy MODEL cells with no field carry no new IR surface; the key is omitted when the list is empty.

### 4.3 `ganglion` (Evaluator)

A ganglion receives signals from nerves and performs evaluation.

```
ganglion <n> :: <LAYER>
    visibility: <PUBLIC | INTERNAL | TEST>
    intent: "<what this evaluator assesses>"
    observes: [<nerve names or wildcard patterns>]
    scope: <FUNCTION_BOUNDARY | SUBSYSTEM | SYSTEM>
    priors: "<baseline/expected-outcome knowledge>"
    on_anomaly: "<action when anomaly detected>"
    forbids: "<what it must never do while it assesses>"
    deferred: "<reason this body is a stub>"
    metadata:
        <key>: <"string" | int | float | true | false | [list, "of", strings]>
    depends_on:
        <target>: {relation: <RELATION>, carries: "<data>", coupling: <TIGHT|LOOSE>}
    ---
    def <n>(signal: Signal) -> EvaluationResult:
        <Python body>
```

**Which lines to write:** §4.14.5 is the one table of which lines a ganglion must write and which of them may be `none` or `pending("reason")`; it is generated from the toolchain's field classification, so it is not repeated here. Fields a ganglion shares with a nerve keep one contract each: `deferred` (POST-12f) is §4.1.9; `metadata` (DSL-M1) is §4.1.11, merging into the evaluator's `@component` dict after the emitter-written keys; and `covered_by` (DSL-M2) is §4.1.13 — the release gate reads PUBLIC nerves and does not consult ganglia. `forbids` is shared the same way, and its one contract is §4.1.14: a ganglion writes it directly after `on_anomaly`, saying what this evaluator must never do while it assesses, or `none`.

#### 4.3.1 The `observes` Field: Pattern Specification

| Pattern Form | Syntax | Matches |
|-------------|--------|---------|
| Exact name | `<nerve_name>` or `<module>::<nerve>` | A single nerve |
| Module-scoped glob | `<module_name>.*` | All nerves in the module |
| Layer-scoped glob | `<LAYER>::*` | All nerves in the layer |

`observes` resolves against the **registry namespace**, not the component-reference namespace. A ganglion can observe nerves in other modules regardless of export status. Total observability (Principle 4) requires that the evaluator network can reach any nerve. The transpiler emits privileged imports for cross-module INTERNAL nerve references in generated ganglion files (see Section 4.10.6).

In strict mode, empty resolution is an error. In dev mode, a warning.

### 4.4 `axon` (Inter-Component Connection)

An axon declares an explicit, authored dependency between two components — an architectural decision that cannot be reliably derived from code. Axons may originate from any executable declaration type: nerve, ganglion, or test. All three have code bodies that may call helpers, read configuration, or construct objects, and those dependencies should be explicit.

#### 4.4.1 Authored Relations

| Relation | Meaning |
|----------|---------|
| `CALLS` | Source invokes target as a function/method. |
| `CONSTRUCTS` | Source creates instances of target. |
| `READS` | Source reads configuration or state from target. |
| `CONFIGURES` | Source provides configuration to target. |
| `PRODUCES` | Source creates/emits instances of target (event production). |
| `CONSUMES` | Source receives/processes instances of target (event consumption). |

Derived relations (`RAISES`, `TYPE_USES`) are **never** declared via axons. See Section 4.11.

V1 models the authored relationship to routing/factory functions, not to dynamically selected callees. The dependency graph captures the decision point, not the fan-out behind it. Modelling dynamic dispatch is a v2 consideration.

#### 4.4.2 Inline Form (`depends_on`)

For intra-module authored dependencies:

```
depends_on:
    validate_envelope: {relation: CALLS, carries: "SignalEnvelope", coupling: TIGHT}
```

#### 4.4.3 Standalone Form

Required for cross-module authored dependencies:

```
axon process_signal -> select_evaluator
    relation: CALLS
    intent: "process_signal delegates evaluator selection to the routing
        module. Loose coupling: routing strategy can change independently."
    carries: "source layer string"
    coupling: LOOSE
```

**Mandatory fields:** `relation`, `intent`, `carries`, `coupling`.

#### 4.4.4 When to Use Which Form

| Scenario | Form |
|----------|------|
| Intra-module authored dependency | Inline (`depends_on`) |
| Cross-module authored dependency | Standalone axon (enforced by transpiler) |
| Architecturally significant decision | Standalone axon |

#### 4.4.5 Duplicate Declaration

One declaration per authored relationship. Duplicates: warning in migration/dev, error in strict/release.

### 4.4a `helper` (Module-Private Function)

> **Added in v0.12.0** (feedback 5–6, plan M13).

A `helper` is a module-private function that lives at module scope but is **not** registered as a component. Helpers exist to address two concrete patterns the v0.11.0 grammar could not express cleanly: deeply-nested helper functions inside a single nerve body (feedback-5 MS 1: ~160 lines of nested helpers in `viz_graph_builder`) and recorder-class duplication across test blocks (feedback-6 MS 13/16, D-36).

```
helper _<name> :: <LAYER>
    intent: "<why this helper exists>"
    tags: [<optional, free-form>]
    ---
    def _<name>(...) -> ...:
        <body>
```

**Mandatory fields:** `intent`, `---` separator and function body. `<LAYER>` must match the module's layer (per §4.0.1).

**Optional fields:** `tags`.

**Excluded fields (by design):** `kind`, `visibility`, `expects`, `guarantees`, `provides`, `returns`, `raises`, `evaluates_at`, `latency_ms`, `depends_on`. Helpers are not component contracts; they are scaffolding for the components that *do* carry contracts. Excluding these fields is a structural enforcement of that distinction — writing one on a `helper` is reported as `UNKNOWN_FIELD` (§4.0.3).

**Naming convention.** By convention, helper names start with an underscore (`_format_attendee`, `_build_event_body`). The parser does not enforce the underscore (any valid identifier is accepted), but the convention is consistent with Python's "private" convention and makes the intra-module / cross-module asymmetry visually obvious in body code.

#### 4.4a.1 Codegen — Plain `def` with No Registration

The transpiler emits a helper as a top-level Python `def` preceded by a `# Helper: <intent>` comment. There is **no** `@component` decorator and **no** `register_*()` call. The helper is therefore not part of the s0ma component registry; the framework's import-hook contract (`s0ma.import_hook`) ignores it because it does not announce itself as a registerable entity.

The helper is also **not** added to the module's `__all__` list. This is consistent with the leading-underscore convention: helpers are module-private, not part of the public surface.

#### 4.4a.2 Introspection — Helpers Appear in `s0ma inspect`

Helpers ARE introspectable. Each helper is recorded under `IRDocument.helpers` (a top-level array on the IR introduced in schema version 1.2.0 — additive). The `s0ma inspect` text pretty-printer renders a separate `Helpers (N):` block listing each helper by canonical id (`<module>::<name>`) tagged `[helper]` so the reader can distinguish helper rows from component rows above. The "machines sense their own components" principle holds: every function that exists in a module is queryable from the IR, even when it is not part of the component graph.

#### 4.4a.3 Access Control — `HELPER_PRIVATE_TO_MODULE`

The cross-module access-control rule mirrors `visibility: TEST` from M8 (§4.10.1):

| Consumer position | Access to a helper in another module |
|---|---|
| **Same module** (intra-module reference) | Allowed. Helpers are in scope for all components in their module — no `uses:` entry needed. |
| **Test module** (`uses:` from a module that contains ≥1 `test` declaration) | Allowed. The helper appears in the consumer's component-reference namespace and may be referenced in test bodies. |
| **Production module** (`uses:` from a module with zero `test` declarations) | **Hard error.** Raises `HELPER_PRIVATE_TO_MODULE` at error severity in every strictness mode (migration, dev, strict, release). |

The rationale is the same as for the `TEST` visibility level: helpers are plumbing, not API. Allowing production cross-module access would dissolve the distinction between a helper and a `nerve` — at which point the consumer should just promote the helper to a `nerve` and add it to the target module's exports.

**Remediation.** When `HELPER_PRIVATE_TO_MODULE` fires, the author has three options: (a) promote the helper to a `nerve`, add it to its module's `exports`, and adjust the consuming `uses:` entry; (b) add a `test` declaration to the consuming module if it is genuinely test-only; or (c) inline the helper's behaviour in the consuming module if the helper is small.

#### 4.4a.4 Body Validation

Helper bodies pass through the same validation as nerve, ganglion, and test bodies, with one POST-4a (0.15.0) widening:

- The body must be a function definition (a `def` statement) **or a class definition** (a `class` statement) — see §4.4a.5 for the rationale.
- The body must parse cleanly as Python (the M2 `ast.parse` invariant).
- Bare `import` statements in the body are rejected (`BARE_IMPORT`).
- Prohibited constructs (`exec`, `eval`, `__import__`, monkey-patching) are rejected (`PROHIBITED_CONSTRUCT`).

#### 4.4a.5 Class-Bodied Helpers (POST-4a, 0.15.0)

> **Added in v0.15.0** (plan post-Phase-2 M-7 / POST-4a).

A `helper` body may be a `class` definition in addition to the original `def` shape:

```
helper _LocalCache :: APPLICATION
    intent: "Module-private LRU cache for the prompt formatter."
    ---
    class _LocalCache:
        def __init__(self):
            self._data = {}
        def get(self, key):
            return self._data.get(key)
        def set(self, key, value):
            self._data[key] = value
```

Class-bodied helpers retire the legacy `cell kind: MODEL visibility: INTERNAL` workaround that previously routed module-private classes through the registry. The class is **not** registered as a component, carries **no** `@component` decorator, and is **not** added to `__all__`. The codegen emits a plain top-level `class <Name>:` preceded by the same `# Helper: <intent>` comment as a function-bodied helper.

The IR records the structural shape under `IRHelper.body_kind` — `"function"` (the pre-POST-4a default) or `"class"`. The access-control rule (§4.4a.3) is unchanged: production consumers still hit `HELPER_PRIVATE_TO_MODULE`; test-context consumers continue to qualify.

Body kinds outside `function` and `class` (assignments, type aliases, bare values) are still rejected with `PARSE_ERROR` — a helper must declare a callable surface, not a value.

#### 4.4a.6 Inline Helper Shorthand `@inline` (POST-4b, 0.15.0)

> **Added in v0.15.0** (plan post-Phase-2 M-7 / POST-4b).

A helper may be declared inline inside the module header's `helpers:` block, dropping the separate `helper <name> :: <layer>` header and `---` separator. The canonical shape:

```
module foo
    layer: APPLICATION
    intent: "..."
    helpers:
      - helper _add @inline: "Quick addition" :: def _add(a, b): return a + b
      - helper _mul @inline: "Quick multiplication" :: def _mul(a, b): return a * b
    ---
```

The entry is a block-list item carrying: the literal `helper`, the helper name, the `@inline` marker, a quoted intent string (single- or double-quoted), `::`, and a single-line Python `def` body. Inline helpers always parse with `body_kind="function"` and `inline=True`; the IR records both.

Inline and block-form helpers may coexist freely in the same module — the rule is "pick the right shape per helper", not "pick one shape per module". The `@inline` form is intended for one-line utility helpers; multi-line bodies or class bodies must use the block form.

Inline helpers obey the same access-control rule as block-form helpers (§4.4a.3): test-context consumers reach them via `uses:`, production consumers hit `HELPER_PRIVATE_TO_MODULE`.

#### 4.4a.7 Cross-Module Re-Export — `exports_helpers:` (POST-4c, 0.15.0)

> **Added in v0.15.0** (plan post-Phase-2 M-7 / POST-4c).

A module may declare which of its helpers are intentionally exposed for cross-module reachability via an `exports_helpers:` field on the module declaration:

```
module shared_utils
    layer: APPLICATION
    intent: "..."
    exports_helpers: [_compare, _render_markdown]
    ---
```

Each entry must name an actual `helper` declaration in the same module; otherwise the validator fires `EXPORTED_HELPER_NOT_FOUND` (error in every strictness mode). The field accepts both the inline form (`exports_helpers: [_a, _b]`) and the block-list form (PRE-7 / 0.14.0):

```
exports_helpers:
  - _compare
  - _render_markdown
```

**Reachability vs access control.** `exports_helpers:` widens reachability — it tells `s0ma inspect` consumers, the IR (`IRModule.exports_helpers`), and the emitted `__all__` that these helpers are intentional cross-module-reachable surface. It does **not** widen access control. The §4.4a.3 rule still applies on the consumer side:

| Consumer position | Reach to a re-exported helper |
|---|---|
| **Same module** (intra-module reference) | Allowed (the original M13 rule). |
| **Test-context module** (`uses:` from a module with ≥1 `test` declaration) | Allowed — `uses: [<module>.<helper>]` resolves cleanly. |
| **Production module** (`uses:` from a module with zero `test` declarations) | **Hard error.** Still raises `HELPER_PRIVATE_TO_MODULE`. The diagnostic context carries `re_exported: true` so tooling can distinguish "production tried to reach a re-exported helper" from "production tried to reach a strictly-private helper". |

The `exports_helpers:` entries are appended to the emitted `__all__` list after the regular `exports:` entries, in declaration order. A `from <module> import *` therefore reaches the re-exported helpers — but the access-control rule above is enforced at validation time, before any import resolution runs.

**Re-exporting only this module's helpers.** `exports_helpers:` cannot list helpers from other modules. The validator enforces this through the same `EXPORTED_HELPER_NOT_FOUND` check that catches typos: every entry must be a `helper` declared in *this* module.

### 4.4b `integration` (External-System Adapter)

*Added in 0.16.0 (POST-5).* The `integration` declaration is a first-class external-system adapter declaration kind. It promotes the legacy D-15 IntegrationManifest pattern — a hand-rolled SERVICE nerve constructing an `IntegrationManifest` dataclass — to a structural shape the transpiler recognises, validates, and auto-emits boilerplate for. Adopting the new declaration is **opt-in**: the legacy IntegrationManifest pattern continues to work unchanged.

```
integration <Name> :: INFRASTRUCTURE
    version: <MAJOR.MINOR.PATCH>
    intent: "<why this integration exists>"
    requires: [<external Python deps>]            # optional
    smoke_test_primary: <SmokeTestNerveName>
    factory: <FactoryNerveName>                   # must be `kind: SERVICE`
    manifest:
      provides: [<operation names>]
      required_env: [<env var names>]
      requires_oauth: true | false
      <arbitrary identifier keys>: <JSON primitive value>
    ---
    # Optional body. Most integrations leave this empty — the
    # canonical smoke-test function and factory nerve live in the
    # same module as separate `nerve` declarations.
```

**Fields.**

| Field | Required | Type | Notes |
|---|---|---|---|
| `version` | yes | semver string | Validated by the existing `INVALID_VERSION` check. |
| `intent` | yes | string | Required intent prose. Surfaces in `s0ma inspect` and on each auto-emitted helper's `ComponentSpec.intent`. |
| `factory` | yes | identifier | Must name a SERVICE nerve in *this* module. `INTEGRATION_FACTORY_NOT_FOUND` if missing; `INTEGRATION_FACTORY_NOT_SERVICE` if the named nerve is not `kind: SERVICE`. |
| `smoke_test_primary` | yes | identifier | Must name a nerve in this module OR a name reachable via `uses:`. `INTEGRATION_SMOKE_TEST_NOT_FOUND` otherwise. |
| `manifest` | yes | map | Identifier keys + JSON-primitive values (`str` / `int` / `float` / `bool` / `list` / `dict` / `None`). `INTEGRATION_INVALID_MANIFEST_KEY` for invalid keys or non-JSON values. Common keys: `provides`, `required_env`, `requires_oauth`. Authors may add arbitrary additional keys (no semantic interpretation). |
| `requires` | no | list | Same shape as on other declarations. |
| `uses` | no | list | Same shape as on other declarations. |
| `raises` | no | list | Same shape as on other declarations. |
| `tags` | no | list | Same shape as on other declarations. |

**Layer invariant.** The `:: <LAYER>` header MUST be `INFRASTRUCTURE`. External-system adapters are an infrastructure concern by definition; a non-INFRASTRUCTURE layer raises `LAYER_MISMATCH`. The intra-module layer-consistency rule (§4.0.1) requires the module's layer to be INFRASTRUCTURE too.

**Auto-emitted helpers.** Every integration declaration produces four module-scoped helper functions:

| Helper | Signature | Behaviour |
|---|---|---|
| `get_factory` | `() -> <factory return type>` | Calls the named factory nerve and returns its return value (typically a dict of callables). |
| `get_manifest` | `() -> dict` | Returns the declared `manifest:` map verbatim. |
| `smoke_test_primary` | `(*args, **kwargs) -> Any` | Wraps the named smoke-test nerve, forwarding arguments. |
| `get_smoke_test` | `() -> Callable[..., Any]` | Returns the `smoke_test_primary` callable so orchestrators can hold a reference, defer invocation, or compose it. |

Each helper is registered with `module_scoped=True` (the [pre-Phase-2 PRE-10 flag](references/dsl_patterns_guide.md) on `ComponentSpec`) so two integrations declared in different modules can share these bare names without registry collision. The registry stores them under `<module>::get_factory` etc.; bare-name lookup still works thanks to the back-compat probe in `ComponentRegistry.get`. Every helper carries the integration's `intent` prose plus a per-helper qualifier (so `s0ma inspect` shows four distinct entries rather than four identical ones), and its `ComponentSpec.metadata` includes `"integration": <Name>` and `"integration_manifest": {…}` for runtime introspection.

**Marker symbol.** The integration's bare name is exposed as a module attribute — a dict bundling the four helpers and the integration's metadata:

```python
# Emitted automatically; consumers see this as a top-level symbol.
GoogleCalendarIntegration = {
    "get_factory": get_factory,
    "get_manifest": get_manifest,
    "smoke_test_primary": smoke_test_primary,
    "get_smoke_test": get_smoke_test,
    "name": "GoogleCalendarIntegration",
    "version": "0.1.0",
}
```

This lets cross-module consumers write `uses: [gcal_integration.GoogleCalendarIntegration]` and reach the four helpers through one import.

**`uses:` resolution.** The integration declaration's name is reachable from other modules' `uses:` lists. The cross-module resolver treats the integration as exempt from the standard `NOT_EXPORTED` check — the four auto-emitted helpers ARE the public surface, and they live behind their `module_scoped=True` registry entries.

**IR.** The IR carries an `integrations` section parallel to `helpers`:

```json
{
  "integrations": [
    {
      "canonical_id": "gcal_integration::GoogleCalendarIntegration",
      "name": "GoogleCalendarIntegration",
      "module": "gcal_integration",
      "layer": "INFRASTRUCTURE",
      "version": "0.1.0",
      "intent": "...",
      "factory": "GoogleCalendarClient",
      "smoke_test_primary": "smoke_calendar_read",
      "manifest": { "provides": [...], "required_env": [...], "requires_oauth": true },
      "location": { "start_line": 33, "end_line": 42 },
      "tags": []
    }
  ]
}
```

The IR schema version bumped to `1.3.0` with this addition (additive — pre-0.16.0 readers see the empty array on legacy modules).

**`s0ma inspect`.** The `Integrations` section renders parallel to the `Helpers` section, showing the canonical id, intent, factory + smoke-test targets, manifest keys, and the four auto-emitted helper names.

**Relationship to the legacy IntegrationManifest pattern.** The Phase 1 Google Calendar integration (and Phase 3's Gmail / Slack) shipped with a hand-rolled `get_manifest` nerve constructing an `IntegrationManifest` Python dataclass, plus per-tool helper conversion gymnastics described in feedback-7 M-A3.2. The new `integration` declaration replaces that boilerplate. Adopting the new form is opt-in — the legacy pattern continues to parse, validate, and emit unchanged.

### 4.5 `module` (File-Level Declaration)

Every `.s0ma` file must begin with a module declaration. The module declaration is the sole authority on what enters and exits the file.

```
module <n>
    layer: <LAYER>
    version: <MAJOR.MINOR.PATCH>
    intent: "<what this module is responsible for>"
    requires: [<external Python dependencies>]
    soft_requires: [<optional Python dependencies>]
    runtime_only_requires: [<imported on emit, exempt from vestigial check>]
    deferred_requires: [<imported inside each consuming def body, per-call failure>]
    uses: [<s0ma component dependencies>]
    exports: [<public component names>]
```

**Which lines to write:** §4.14.5 is the one table of which lines a module header must write and which of them may be `none` or `pending("reason")`; it is generated from the toolchain's field classification, so it is not repeated here. A dependency category with nothing in it is written as `none` — `requires: none` for a module whose bodies import nothing — and §4.5.1 says what each category is for.

#### 4.5.1 The Dependency Categories

**`requires`** — External Python dependencies. Available in the code namespace but not the component-reference namespace. Three forms:

```
requires: [time, os.path]                # emits 'import time', 'import os.path'
requires: [uuid.UUID, typing.List]       # emits 'from uuid import UUID', etc. (capitalization heuristic)
requires: [unittest.mock:patch]          # emits 'from unittest.mock import patch' (explicit colon override)
```

The transpiler converts `requires` entries to Python imports using these rules in priority order: (1) **colon override** — `package:name` always generates `from package import name`; (2) **known-exceptions list** — common stdlib patterns like `datetime.datetime` are recognized; (3) **capitalization heuristic** — uppercase last segment triggers `from ... import`; (4) **single-segment names** — always `import name`.

**Common stdlib gotchas.** The capitalization heuristic is correct most of the time, but four stdlib patterns recur in agent-authored code where the heuristic guesses the wrong form. Reach for the colon override for these specifically:

- **`urllib.<sub>` collisions** — `urllib.parse`, `urllib.request`, `urllib.error`, `urllib.response`. The submodule names are lowercase, so the heuristic emits `import urllib.parse` (correct), but bodies typically call `urllib.parse.urlencode(...)`, which forces the full dotted call site through emit. When you want the un-dotted `urlencode` symbol, declare the colon override explicitly:
  ```
  requires: [urllib.parse:urlencode]   # emits 'from urllib.parse import urlencode'
  ```
- **`uuid.uuid4`** — `uuid4` is lowercase, so the heuristic emits `import uuid.uuid4`, which is wrong (uuid4 is a function, not a submodule). The colon form is mandatory:
  ```
  requires: [uuid:uuid4]               # emits 'from uuid import uuid4'
  ```
  **POST-10g hint (0.16.0).** A `requires:` (or `soft_requires:` / `runtime_only_requires:`) entry authored as `uuid.uuid4` whose body references the lowercase last segment (`uuid4()`) as a bare identifier fires `REQUIRES_DOTTED_LOWERCASE_HINT` (warning in every mode). The diagnostic names the colon-override shape so the steer is immediate; the original code path still works (or fails through a separate `VESTIGIAL_IMPORT` / `NameError` ladder), but the hint shortens the diagnostic loop. The trigger generalises: any dotted-form entry whose last segment starts with a lowercase letter and whose lowercase last segment is referenced bare in a body in the same module qualifies.
- **`dataclasses`** — MODEL cells with `kind: MODEL` almost always carry a `@dataclass`-decorated body; the `requires:` block needs to declare `dataclasses` (often plus `field`):
  ```
  requires: [dataclasses, dataclasses:field]   # 'import dataclasses' + 'from dataclasses import field'
  ```
  If the body only uses `@dataclasses.dataclass`, the single-segment form suffices; the moment the body uses `field(default=...)`, the colon override for `field` is required to avoid a fully-qualified `dataclasses.field(...)` call.
- **`argparse.REMAINDER`** — `REMAINDER` is uppercase, so the heuristic emits `from argparse import REMAINDER` (correct), but the symbol is a sentinel constant, not a class. The body typically uses it as `argparse.REMAINDER` in a `nargs=` keyword. Pick the form that matches the body's call site to avoid `VESTIGIAL_IMPORT`:
  ```
  requires: [argparse]                 # body writes 'argparse.REMAINDER'
  # OR
  requires: [argparse:REMAINDER]       # body writes 'REMAINDER' bare
  ```

**Body-evidence scope.** The vestigial-import detector walks every nerve / cell / test body in the module and counts `requires:` entries as "live" if any body references the imported name. For SERVICE / ADAPTER nerves whose body is a class definition, the scope includes **inner closures and nested function definitions** inside the class — the detector recurses into every `def` and lambda. An import used only inside a method's nested helper still counts as live; the heuristic does not require the reference to be at the top level of the body.

**`soft_requires`** — Optional external Python dependencies that may not be installed. Same syntax as `requires`. The transpiler emits try/except import blocks:

```
soft_requires: [anthropic, prompt_toolkit]
```

Emits:
```python
try:
    import anthropic
except ImportError:
    anthropic = None
```

`soft_requires` entries skip Phase 3 external validation (they may not be installed) but are still checked for vestigial usage in Phase 4.

**Dotted-name codegen (0.16.0, POST-10j).** When a `soft_requires:` entry carries a dotted module path (e.g. `soft_requires: [importlib.metadata]`), the transpiler emits the try/except wrapper in the *from-import* shape rather than the plain-import shape:

```
soft_requires: [importlib.metadata]
```

Emits:
```python
try:
    from importlib import metadata
except ImportError:
    metadata = None
```

Pre-0.16.0 this same input produced `try: import importlib.metadata; except ImportError: importlib = None`, which (a) silently overwrote the top-level `importlib` binding when the import failed and (b) left the `metadata` name unbound when the import succeeded. POST-10j auto-promotes every dotted-form entry to the from-import shape for the wrapper so the local binding name is always the last segment (or the explicit `alias` if one was supplied). The colon-override form (`soft_requires: [requests:Session]`) already produced the from-import shape pre-0.16.0; POST-10j makes the two forms equivalent for dotted names.

**`runtime_only_requires` (0.16.0, POST-10b)** — External Python dependencies whose import is needed on the generated module but whose body-level reference is provided by a runtime mechanism the static checker cannot see. Same grammar as `requires:` / `soft_requires:` (inline `[a, b]` and YAML block-list form, colon-override and alias forms supported). The transpiler emits the same import line as `requires:` (no try/except wrapper — these *are* installed by assumption) and the Phase 4 vestigial-import check skips them entirely.

```
runtime_only_requires: [pytest]
```

The canonical use case is `pytest` for test modules whose bodies use pytest fixtures (`def test_foo(monkeypatch): ...`) but never write `pytest.<symbol>` directly. The runner discovers and injects the `monkeypatch` argument; the static heuristic does not see the import as live; `runtime_only_requires:` is the explicit, named carve-out that lets the import land on the generated module without the warning. The field is also the right home for any future "imported for side effect at import time" case — e.g. registering a hook by simply importing the package.

**`deferred_requires` (0.17.0, DSL-M2 — ADR-011 §(c))** — External Python dependencies whose import is deferred to call time. Same entry grammar as `requires:` / `soft_requires:` / `runtime_only_requires:` (dotted paths, colon override, `as` aliases, inline and block-list forms). Entries emit NOTHING at module top; for each emitted def whose authored BODY references an entry's bound name (the same body-reference evidence the vestigial machinery uses), the transpiler injects the import statement at the top of that def's body — after the docstring when present (PEP 257; `__doc__` unaffected), before the first authored statement; multiple consumed entries form one contiguous block in `deferred_requires:` entry order. Injection targets are module-level defs and class-body methods; a reference inside a nested def counts for its outermost enclosing def.

```
deferred_requires: [s0ma_dsl.cli.main:S0maCLI]
```

Emits, inside each consuming def:
```python
def check_tool(path: str | None = None) -> dict[str, Any]:
    """Validate .s0ma source WITHOUT emitting output — your inner loop."""
    from s0ma_dsl.cli.main import S0maCLI
    ...
```

Python caches modules in `sys.modules`, so the per-call cost after the first success is one dict lookup; on a broken environment each CALL raises `ImportError` inside the body — which a structured-result boundary converts to a per-call failure instead of an import-time crash. That is the "start degraded, fail per-call" resilience idiom (the F-M3-1 friction finding), restored as an authored choice. The static dependency record stays COMPLETE: the IR lists deferred entries under `imports.deferred_requires` with `"deferred": true` per entry, Phase-3 importability checking (`MISSING_PACKAGE`) applies unchanged, and Phase-4 `VESTIGIAL_IMPORT` uses the same body-evidence rule as `requires:` (deferred entries are NOT `runtime_only_requires`-exempt — an unconsumed deferred entry would emit no import anywhere and is always a mistake).

Two contracts are enforced (both error in every mode; see §4.7.4 and §4.16): `DUPLICATE_REQUIRES_ENTRY` — the same import target may not appear in `deferred_requires:` and another requires-family list (module-top import and call-time deferral are different failure-time choices; pick one — `soft_requires` + `deferred_requires` combinations are deliberately inexpressible); and `DEFERRED_IMPORT_MODULE_SCOPE` — a deferred name may not be consumed at a module-scope execution position (a CONSTANT/TYPE cell body, a class-scope statement such as a field default, a decorator expression, a parameter default, or an annotation on an emitted def): those evaluate at import time, before any injected in-body import could run; move the entry back to `requires:` or restructure the consumer into a function body. Terminology note: `deferred_requires:` defers IMPORTS; the per-declaration `deferred:` field (§4.1.9) is the unrelated stub marker.

Pick `requires:` (the default) when the body references the symbol directly. Pick `runtime_only_requires:` when the import is needed at runtime but the static checker has no way to see it. Pick `soft_requires:` when the package may not be installed and module-top try/except softness is the right failure shape. Pick `deferred_requires:` when the module must import even in a degraded environment and each CALL should surface the import failure instead — the agent-facing-server resilience idiom.

**Body-evidence scope (continued).** The vestigial-import detector also computes a *closure* across `uses:` ↔ `depends_on:` ↔ `raises:` ↔ body references in a single pass (POST-10a, 0.16.0). A `uses:` entry counts as live if its local name appears in *any* member of that union — body identifier, inline `depends_on:` target, top-level `raises:` entry, `tests:` target, or standalone axon target. The closure is single-pass: there is no second-pass cascade that would re-flag a name as vestigial after a sibling field is updated.

**`uses`** — Cross-module s0ma component dependencies. Declares which s0ma components are available in the module's component-reference namespace. This includes components that are called, raised, constructed, read, configured, or referenced in type annotations — any cross-module s0ma reference that appears in declaration fields or is needed to resolve derived edges. Cross-module validation at build time.

```
uses: [routing.select_evaluator, errors.SignalValidationError]
```

**Cross-module symmetry warning (0.16.0, POST-10k).** When `uses:` imports two or more entries from the same parent module (e.g. `uses: [other.A, other.B]`) but the module's bodies only reference a subset of those names, the validator fires `CROSS_MODULE_USES_ASYMMETRY`. The lint groups `uses:` entries by their parent-module path (`other.A` and `other.B` share parent `other`; `a.b.X` and `a.b.Y` share parent `a.b`), collects every bare identifier reference across every authored body, and flags any group with both referenced and unreferenced siblings. Narrower than `VESTIGIAL_IMPORT`: the lint only fires when ≥2 siblings from the same parent module are declared together AND at least one of them IS referenced; the all-unused case is left to the broader vestigial-import ladder. Severity ladders with mode: warning in migration/dev so authors see the finding while iterating, error in strict and release where the silent symmetry-asymmetry pattern signals real drift (perhaps a copy-paste of the symmetric pair from a sibling module that the body never quite caught up to). Remediation: remove the unreferenced entry from `uses:`, or ensure at least one body references it directly so the asymmetry resolves.

```
# Flagged:
uses: [other.alpha, other.beta]      # CROSS_MODULE_USES_ASYMMETRY on `other.beta`
exports: [do_thing]

nerve do_thing :: APPLICATION
    ...
    ---
    def do_thing():
        return alpha()                # references only alpha; beta is unreferenced

# Not flagged (both siblings referenced):
uses: [other.alpha, other.beta]
exports: [do_thing]

nerve do_thing :: APPLICATION
    ...
    ---
    def do_thing():
        return alpha() + beta()
```

**`exports`** — The module's public cross-module interface. The transpiler generates `__all__` and enforces cross-module visibility at the transpiler level. Because `uses` covers all cross-module s0ma references (calls, types, exceptions, config, etc.), `exports` governs the full cross-module interface, not just calling.

> **KEY:** `requires` marks the boundary of self-knowledge. Everything in `uses` is fully self-aware. Everything in `requires` is opaque.

#### 4.5.2 Version Declaration

`version` is mandatory on modules, optional on components. Semantic versioning. Authored, not auto-generated.

| Component | Interpretation |
|-----------|---------------|
| MAJOR | Breaking changes to exported interface. |
| MINOR | Backward-compatible additions. |
| PATCH | Internal changes. Authored by developer or coding agent. |

The transpiler emits a deterministic `content_hash` in the `.s0ma.json` IR. `version` = compatibility semantics (authored); `content_hash` = change detection (generated).

#### 4.5.3 Source Filename Mirrors the Declared Module Name

The source filename's stem must equal the declared module name. The module name is the canonical identity used as the cache key, the basis for emitted `.py` / `.s0ma.json` / `.s0ma.map` filenames, and the import name resolved by `uses:` references; the source filename mirrors that identity. A `.s0ma` file declaring `module google_calendar_integration` must live at `google_calendar_integration.s0ma`. Divergence raises `MODULE_NAME_STEM_MISMATCH` at error severity in every strictness mode (migration, dev, strict, release) — see [`docs/adr/ADR-006-canonical-module-identity.md`](adr/ADR-006-canonical-module-identity.md) for the design rationale.

#### 4.5.4 Block-Form Lists on `uses` / `requires` / `exports` / `raises` (0.14.0)

The four list-valued module-header fields — `uses`, `requires`, `exports`, and the per-nerve `raises` — accept both the inline form and a YAML-style block form. The two forms are exactly equivalent: the parser reassembles the block form into the inline shape before any downstream pass sees it.

**Inline form** (unchanged from prior releases):

```
uses: [routing.select_evaluator, errors.SignalValidationError, application.events.AppEvent]
```

**Block form** (added in 0.14.0):

```
uses:
  - routing.select_evaluator
  - errors.SignalValidationError
  - application.events.AppEvent
```

**Grammar rules.**

- Block-form items are introduced by `-` followed by a space (or end-of-line for an empty item — which is rejected; see below).
- Items must be indented **strictly more** than the field key. The field key sits in the 4-space-indent column for module headers, so the canonical item column is 6 spaces (4 for the field + 2 for the list marker). The parser accepts any indent `> field_indent` as long as **all items in one block share the same indent column**.
- Comments (`# ...`) inside a block are skipped silently. Inline comments at the end of an item line (`- foo  # note`) are stripped before the item is captured (the `#` outside a quoted string ends the item).
- Quoted items (`- "foo.bar"`) are supported and follow the same quoting rules as the inline form.
- A block is terminated by: a blank line, the body separator `---`, a top-level declaration, any line with indent `<= field_indent`, or a non-`-`-prefixed indented line.

**Mixed inline + block in the same field is rejected.** If the value after `:` is non-empty, the parser stays on the inline path and ignores subsequent `-` lines. Pick one form per field.

**Empty list:** use the inline form `field: []`. The block form cannot express an empty list — `EMPTY_BLOCK_LIST` (error in every strictness mode) fires if zero items are present.

**Inconsistent indent:** if two items in one block use different indent columns, `INCONSISTENT_BLOCK_LIST_INDENT` (error in every strictness mode) fires.

**When to use which form.** Inline is the right call when the list is short enough to fit comfortably on one screen-width line; block is the right call when the list grows past ~5 entries or contains long canonical paths. A typical Phase 2 web-view module's `uses:` runs 8–15 entries and reads much better as a block. Either form is grammatically equivalent; the choice is purely about source-file readability.

### 4.6 Dependency Resolution

#### 4.6.1 Resolution Phases

1. **Phase 1 — Module graph construction.** Directed graph from `uses` plus qualified `depends_on:` targets (DSL-M2, §4.1.2). Cycles are fatal.
2. **Phase 2 — Export validation.** Every `uses` reference must exist in target's `exports`.
3. **Phase 3 — External validation.** Every `requires` (and `deferred_requires`) entry must be importable (optional, can be disabled).
4. **Phase 4 — Usage verification.** Every declared dependency must have valid evidence of use (see Section 4.6.3).

**Note on cycle strictness:** Because `uses` covers all cross-module s0ma references (not just calls), circular dependencies are detected even for type-only or exception-only relationships. Module A using a type from Module B while Module B uses a type from Module A is a fatal cycle. This is a deliberate architectural constraint: circular module dependencies indicate structural entanglement that should be resolved by extracting shared types, exceptions, or config into a common module. This is stricter than Python's native import system, which permits some circular patterns. Qualified `depends_on:` edges (DSL-M2) join this rule — a cycle in declared architecture edges is structural entanglement regardless of emission — and the cross-layer reachability matrix applies to them unchanged.

**Qualified `depends_on:` target resolution (DSL-M2).** A dotted target `m.d` resolves in three steps: `m` must be a module in the project's module set (`DOES_NOT_EXIST` naming the qualified form and listing the project's modules; in single-module/synthetic invocations the remediation says qualified targets require a `[tool.s0ma]` project build), `d` must be a declaration in `m` (`DOES_NOT_EXIST`, qualified variant of the in-module message), and for cross-module targets `d` must appear in `m`'s `exports:` (`NOT_EXPORTED` — the same public-surface rule as `uses:` Phase 2). A self-module-qualified target resolves as the local declaration (idempotent, permitted, no export demand). Cross-PACKAGE targets remain inexpressible.

#### 4.6.2 Error Semantics

| Error Type | Trigger | Remediation |
|-----------|---------|-------------|
| `NOT_EXPORTED` | `uses` entry or qualified `depends_on:` target references non-exported component | Add to exports or remove dependency. |
| `DOES_NOT_EXIST` | `uses` entry or `depends_on:` target (bare or qualified `module.declaration`) references unknown component or module | Check for typos. Run registry scan. Qualified targets require a `[tool.s0ma]` project build. |
| `CIRCULAR_DEPENDENCY` | Module graph (from `uses` + qualified `depends_on:` edges) has a cycle | Refactor. Extract shared components. |
| `MISSING_PACKAGE` | `requires` or `deferred_requires` references unimportable module | Install package or correct name. |
| `VESTIGIAL_IMPORT` | Declared dependency has no valid evidence | Remove unused entry (see 4.6.3 for evidence rules). |
| `NAME_COLLISION` | Two names collide in visible namespace | Rename or use an alias. |

#### 4.6.3 Usage Verification Evidence Rules

Phase 4 verifies that every declared dependency is actually used. What counts as valid evidence depends on the dependency category:

| Declaration | Valid Evidence |
|------------|---------------|
| `uses` entry | Reference in code body, OR reference in `raises` field, OR reference in `depends_on` target, OR standalone axon target, OR transpiler-derived `TYPE_USES` edge from a signature referencing this component. |
| `requires` entry | Reference in code body (Python name used in the function/class body after the `---` separator). |
| `deferred_requires` entry | Same rule as `requires` (DSL-M2): reference in a code body. An unconsumed deferred entry would emit no import anywhere, so it is vestigial by construction — deferred entries are NOT `runtime_only_requires`-exempt. |
| Authored `CALLS` axon | Function call to the target name in the source component's code body, OR a snake_case version of the target name appears as a parameter in the nerve's function signature (dependency injection pattern). |
| Authored `READS` axon | Name reference to the target in the source component's code body. |
| Authored `CONSTRUCTS` axon | Exempt from body evidence matching — the CONSTRUCTS relation is structural (the concrete implementation never calls the abstract interface by name). Always valid. |
| Authored `CONFIGURES` axon | Name reference to the target in a code body, OR the target appears as a `depends_on` entry of a component that this component also depends on. |
| Authored `PRODUCES` axon | Target name appears in a constructor call or return value in the source component's code body (creating the event/data). |
| Authored `CONSUMES` axon | Target name appears as a parameter type annotation or in an isinstance check in the source component's code body (receiving the event/data). |

> **KEY:** The evidence model is relation-aware. A `uses` entry referenced only in a `raises` field is valid — that is a legitimate architectural reference. An authored `CALLS` axon without a corresponding function call in the body is a vestigial declaration. This prevents the linter from punishing the explicit architectural declarations the language exists to encourage.
>
> **Parameter injection:** When a nerve receives a dependency as a constructor parameter (e.g., `def MyService(llm_adapter)`), the transpiler matches the snake_case parameter name against the PascalCase `depends_on` target name. This avoids false VESTIGIAL_IMPORT diagnostics for dependency injection patterns.
>
> **Target-location-agnostic (DSL-M2):** the evidence rules above do not change for qualified `depends_on:` targets — the relation still determines the evidence, checked against the target's LEAF name (the dotted form is a header-side spelling, never a Python binding). Referential edges whose evidence lives in embedded template DATA rather than the body keep `metadata:` as the documented carrier.

#### 4.6.4 The Self-Awareness Boundary

Everything through `uses` is fully described and evaluatable. Everything through `requires` is outside the self-model.

### 4.7 Import Semantics & the No-Bare-Import Rule

#### 4.7.1 The Rule

**No `.s0ma` file may contain a bare Python import statement.** All imports declared in module header, emitted by transpiler. The `BARE_IMPORT` remediation names both header homes: add a `requires:` entry, or a `deferred_requires:` entry if you want the import deferred to call time with per-call failure semantics (§4.7.4). Validation runs on authored source; the deferred-import body injection is a post-validation emitter step, so `BARE_IMPORT` never fires on injected lines.

#### 4.7.2 Transpiler Emission Rules

PEP 8 order: stdlib, third-party, s0ma components, then `__all__`.

#### 4.7.3 Aliasing

```
requires: [collections.OrderedDict as OD, json]
uses: [auth.validate_token as verify_token]
```

#### 4.7.4 Conditional and Deferred Imports

Conditional imports are not supported. Deferred imports ARE expressible since 0.17.0 (DSL-M2) — as a module-header DECLARATION, never as in-body Python: list the entry in `deferred_requires:` (§4.5.1) and the transpiler injects the import at the top of each consuming def body, after the docstring. The declaration stays unconditional and module-level (the static dependency record is complete, with `"deferred": true` on the IR entries); only the EMISSION POINT moves, giving per-call failure semantics on a broken environment.

```
deferred_requires: [s0ma_dsl.cli.main:S0maCLI]
```

Emits:
```python
def check_tool(path: str | None = None) -> dict[str, Any]:
    """Validate .s0ma source WITHOUT emitting output — your inner loop."""
    from s0ma_dsl.cli.main import S0maCLI
    ...
```

`DEFERRED_IMPORT_MODULE_SCOPE` (error in every mode) rejects a deferred name consumed at a module-scope execution position — a CONSTANT/TYPE cell body, a class-scope statement (field defaults execute at class creation), a decorator expression, a parameter default, or an annotation on an emitted def — because those evaluate at import time, before any injected in-body import could run. `DUPLICATE_REQUIRES_ENTRY` (error in every mode) rejects the same import target appearing in `deferred_requires:` and any other requires-family list of the same module header.

#### 4.7.5 Prohibited Runtime Escape Hatches

**Prohibited in `.s0ma` bodies:** `exec()`, `eval()`, `__import__()`, `importlib.import_module()`, and monkey-patching. Strict mode: error. Dev mode: warning.

> **KEY:** The dependency graph must be fully determinable from module declarations alone, without executing any code.

#### 4.7.6 Body-Shape Lints (0.16.0)

A small family of lints fires on body shapes that compile cleanly but encode known-buggy author patterns. The lints walk every authored body (nerves, cells, ganglia, tests, helpers) and emit a structured diagnostic with the body declaration's start line as the location anchor.

**`MUTABLE_DEFAULT` (POST-10h).** A body calls `dataclasses.field(default=[...])` or `dataclasses.field(default={...})` — i.e. supplies a mutable collection literal as the `default=` argument. Python evaluates `default` once at class-body time, so every instance of the dataclass shares the same list/dict/set object and mutating one mutates them all (the classic shared-mutable-default bug). The correct shape is `default_factory=list` / `default_factory=dict` / `default_factory=set` so each instance gets a fresh collection. The lint recognises both the bare-call form (`field(default=[])`, after `requires: [dataclasses.field]`) and the qualified-call form (`dataclasses.field(default=[])`); it also catches zero-argument `list()` / `dict()` / `set()` calls as mutable defaults. Severity ladders with mode: warning in migration/dev (so authors see the finding while iterating), error in strict and release (where shipping a known-buggy default is unacceptable). Aliased imports (`from dataclasses import field as df; df(default=[])`) are intentionally not recognised — the lint is conservative there to avoid false positives on unrelated single-name `field(...)` calls in unrelated APIs.

```
# Flagged:
@dataclass
class Container:
    items: list = field(default=[])     # MUTABLE_DEFAULT (warning/error)
    seen: dict = field(default={})      # MUTABLE_DEFAULT (warning/error)

# Correct:
@dataclass
class Container:
    items: list = field(default_factory=list)
    seen: dict = field(default_factory=dict)
```

**`DUPLICATE_INNER_FUNCTION` (POST-10i).** A body contains two `def` (or `async def`) declarations with the same name inside one enclosing function scope. The canonical motivating case is a SERVICE nerve's factory body where the author meant the second `def` to be a sibling but accidentally re-typed the first inner function's name; Python silently accepts the redefinition and the second binding shadows the first, so the dict the factory returns ends up keyed to a function the author did not intend. The lint walks every authored body and, for each `ast.FunctionDef` / `ast.AsyncFunctionDef` node, scans its direct `ast.FunctionDef` / `ast.AsyncFunctionDef` children for name collisions. Class bodies and methods inside classes are intentionally excluded — Python allows `def foo` once per method-name in a class body, and the parallel collision detector for nerves is `CLASS_BODY_IN_NERVE`. Always an error in every strictness mode: this is a structural authoring bug, not a strictness preference (same precedent as `DUPLICATE_DECLARATION` at module scope).

```
# Flagged:
nerve factory :: APPLICATION
    kind: SERVICE
    ...
    provides: [foo, bar]
    ---
    def factory():
        def foo():
            return 'first'
        def foo():               # DUPLICATE_INNER_FUNCTION (error)
            return 'second'
        def bar():
            return 'bar'
        return {'foo': foo, 'bar': bar}

# Two sibling outer scopes with same-named inner defs are OK:
nerve factory :: APPLICATION
    kind: SERVICE
    ...
    provides: [foo]
    ---
    def helper():
        def foo():               # OK — distinct outer scope
            return 'helper-foo'
        return foo
    def factory():
        def foo():               # OK — distinct outer scope
            return 'factory-foo'
        return {'foo': foo}
```

### 4.8 `test` (Verification Component)

Tests are first-class citizens: described, registered, and queryable. The system can reason about its own test coverage structurally.

```
test <n> :: <LAYER>
    intent: "<what behaviour this test verifies>"
    tests: [<component names this test validates>]
    expects: "<preconditions>"
    tags: [<categorisation tags>]
    depends_on:
        <target>: {relation: <RELATION>, carries: "<data>", coupling: <TIGHT|LOOSE>}
    ---
    def <n>():
        <Python test body>
```

**Which lines to write:** §4.14.5 is the one table of which lines a test must write and which of them may be `none` or `pending("reason")`; it is generated from the toolchain's field classification, so it is not repeated here. `mocks` (0.15.0, POST-3b) is §4.8.4.

The `tests` field is an authored relationship queryable directly from the registry. `tests` resolves against the **registry namespace** — a test can verify components in other modules, including INTERNAL components. The transpiler emits privileged imports for cross-module INTERNAL references in generated test files (see Section 4.10.6).

In release mode, all PUBLIC nerves must be referenced by at least one test — OR carry a non-empty `covered_by:` claim (DSL-M2, §4.1.13). The two routes stay distinguishable in the record: in-language `tests:` coverage produces verification edges and registry test registrations, while `covered_by:` is an authored, auditable claim that an EXTERNAL suite covers the nerve (the credit injects no synthetic test targets). Use `covered_by:` when the real coverage lives in an out-of-DSL pytest suite; use `test` declarations (with the wrapper-import recipe when the build is committed inside a package with its own pytest suite — see the documentation-subsystem guide) when the coverage should be expressed and executed in-language. The `MISSING_TEST_COVERAGE` remediation names all three options.

**Test target naming.** The `tests:` field accepts both bare names (`MyNerve`) and qualified names (`my_module.MyNerve`). Both forms are canonicalised to `module::component` internally — the same canonical ID the IR uses for verification edges and the dependency resolver uses for release-mode coverage. The qualified form is preferred when the target lives in a different module from the test, because it resolves unambiguously and aids greppability. A bare name resolves intra-module first, then cross-module by unique match; if the bare name matches components in two or more modules the resolver emits `AMBIGUOUS_TEST_TARGET` (error in every mode) and the user must qualify the target. Both `_resolve_test_target_canonical` (registry-aware, used by the dependency resolver) and `canonicalize_qualified_target` (purely syntactic, used by the IR builder) live in `s0ma_dsl.resolver.namespaces` and are the single source of truth — no other code may reimplement the bare-vs-qualified split.

#### 4.8.1 Design Decisions

**No `evaluates_at`** — tests are themselves evaluation. **No `kind`** — single role. **No `visibility`** — invoked by test runner. **No `guarantees`** — passes or fails.

#### 4.8.2 Test File Conventions

Test files are `.s0ma` files with `exports: []` and names ending `_tests`. The transpiler generates pytest-compatible Python.

**The function's name decides whether the test runs.** The transpiler emits a test's code as it was authored, and the test runner collects by name: a function whose name starts with `test`, or a `test…` method of a class whose name starts with `Test`. The declaration's own name plays no part. A `test` declaration whose code defines nothing the runner collects is emitted, registered as coverage for the components it names, and never executed; it is reported as `TEST_NOT_COLLECTED` — warning in migration and dev, error in strict and release. A project that has configured the runner to collect other names (`python_functions` or `python_classes`, in `pytest.ini`, `pyproject.toml`, `tox.ini` or `setup.cfg`) is checked against the names it configured.

> **KEY:** `tests` is the fourth scale: import hook (component) → decorator (function) → module declaration (file) → test declaration (verification).

#### 4.8.3 Helper-Collision Detection (Scope-Aware)

When two `test` declarations are emitted into the same Python module, their bodies share a single module namespace. A `def` at the *top level* of one test body silently overwrites a same-named `def` at the top level of another. The transpiler emits `HELPER_NAME_COLLISION` (warning) when it detects this.

**Detection is scope-aware.** The check applies only to `def` and `async def` declarations at the **top level** of a test body. Methods inside `class` declarations and functions inside other `def`s are scope-isolated and are **not** flagged:

| Construct | At top level | Inside `class` | Inside another `def` |
|-----------|--------------|----------------|----------------------|
| `def helper(): ...` | flagged on collision | exempt (method) | exempt (closure) |
| `async def helper(): ...` | flagged on collision | exempt (method) | exempt (closure) |

The transpiler parses the test body with `ast.parse` and walks only the top-level nodes; class methods (`__init__`, `__aenter__`, `__aexit__`, `request`, etc.) and inner-function closures (factory patterns: `def inner()` inside `def factory()`) cannot collide and are silently ignored.

**Remediation when a collision is genuine.** Either rename the colliding `def`, or — if the duplicated name is structural (a recorder class's `__init__`, a factory's inner closure) — wrap the definition in a `class` or outer `def` so it is not at top level. The warning's `remediation` field surfaces both options.

#### 4.8.4 The `mocks:` Field (0.15.0 — POST-3b)

A `test` declaration may carry an optional `mocks: [<NerveName>, ...]` field naming the SERVICE / ADAPTER nerves whose public surface the test mocks. The field is the test-declaration counterpart of `provides:` on the production side: it makes the mock relationship structurally visible and lets the validator cross-check that mock dicts in the body expose the same key set as the real `provides:`.

```
test test_assembler :: APPLICATION
    intent: "Verify the assembler factory exposes the right ops."
    tests: [assembler]
    mocks: [assembler]
    ---
    def test_assembler():
        mock_assembler = {
            "assemble": lambda parts: "".join(parts),
            "validate": lambda topic: True,
        }
        # ... drive the test against the mock surface
        assert mock_assembler["assemble"](["a", "b"]) == "ab"
```

Inline (`mocks: [a, b]`) and PRE-7 block forms parse identically.

**What the validator checks.** When the body assigns a dict literal to a variable whose lowercased name matches a `mocks:` entry's lowercased name (optionally with a leading `mock_` / `fake_` / `stub_` / `dummy_` / `fixture_` prefix), the validator compares the dict's literal-string keys against the target nerve's `provides:` set. Missing or extra keys fire `MOCK_KEY_MISMATCH` (warning in migration/dev, error in strict/release). The check is conservative by design — false positives are worse than false negatives, so it fires only when (a) the variable-name convention matches, (b) every key is a literal string, and (c) the target is a local nerve with a non-empty `provides:`. Dynamic mock construction (`dict(...)`, comprehensions, str-formatted keys, `**spread` operators) is silently skipped.

**Target resolution.** A `mocks:` entry resolves first against the local module's nerves, then against `uses:`. Cross-module targets resolved via `uses:` are accepted as known but the dict-key cross-check is skipped at the intra-module validator layer (only the local-module check has access to the target's `provides:` set without a full cross-module resolution pass). A target that is neither a local nerve nor a `uses:` import raises `DOES_NOT_EXIST` (re-using the existing axon-target pattern).

**Motivating consumer.** fr3d's Phase 2 Frontend track relies heavily on mock dicts for SERVICE-nerve fakes; before POST-3b, those mock dicts drifted silently from the production `provides:` surface and the next test author had no structural signal that the mock was out of date. The `mocks:` field + cross-check closes that drift class without forcing the test to import production code.

### 4.9 The `---` Separator

| Property | Specification |
|----------|--------------|
| Characters | Exactly three ASCII hyphen-minus (`U+002D U+002D U+002D`) |
| Indentation | Column 0 (no leading whitespace) |
| Line content | Only non-whitespace content on its line |
| Context | Between declaration header and Python body only |
| Multiplicity | One per declaration block with a code body |

`axon` and `module` may omit the separator. All others require separator and code body.

### 4.10 Component Identity & Name Resolution

Every component has a canonical identity:

```
<module_name>::<component_name>
```

#### 4.10.1 The Namespace Model

The s0ma DSL defines four namespaces that govern how names resolve in different contexts. This separation exists because calling a component, referencing it in DSL metadata, observing it, and exporting it are fundamentally different operations.

| Namespace | Populated By | Used In | Access Rule |
|-----------|-------------|---------|-------------|
| **Code namespace** | Local declarations + `uses` imports + `requires` imports | Python code bodies (after `---` separator) | Full Python namespace. All names available for runtime use. |
| **Component-reference namespace** | Local declarations + `uses` imports only (no `requires`) | `depends_on`, `raises`, standalone axon targets | s0ma components only. `requires` names excluded. Ensures DSL fields reference only self-describable entities. |
| **Registry namespace** | All components in the project (full registry) | `observes` patterns, `tests` field, qualified references, `doc-ref` `covers:`/`sections:`, `doc-guide` `covers:`/`asserts:`/`examples:`/prose `{{...}}` tokens, `example` `demonstrates:` | Not limited by exports. Total observability for evaluation, verification, and documentation. |
| **Public API namespace** | `exports` list | Cross-module `uses` declarations from production modules | Module's external cross-module interface. Covers all reference types, not just calls. |
| **Test API namespace** | All `visibility: TEST` components in the project | Cross-module `uses` declarations from *test consumers* (modules with ≥1 `test` declaration) | Reachable from any test consumer. Hidden from production modules with no `test` declarations. Not part of the public export surface. |

**The code namespace** is available inside Python bodies. It contains everything the code might need to reference at runtime: local s0ma components, cross-module s0ma components from `uses`, and external Python names from `requires`.

**The component-reference namespace** is available in DSL metadata fields (`depends_on`, `raises`, standalone axon targets). It contains only s0ma components: local declarations and `uses` imports. `requires` names are excluded. This ensures that every name in a DSL field refers to something the system can fully self-describe. You cannot write `raises: [ValueError]` because `ValueError` is a Python builtin (in `requires` at best), not a declared s0ma cell.

**The registry namespace** is available in `observes` and `tests` fields and across the entire documentation subsystem (`doc-ref`, `doc-guide`, and `example` declarations — see §4.12). It contains every component in the project, regardless of visibility or export status. This is how Principle 4 operates: the evaluator network, test system, and documentation system are never limited by calling access control. A `doc-guide` may legitimately reference an INTERNAL nerve from another module; the transpiler resolves it through the same registry the evaluators use.

**The public API namespace** is the subset of a module's components available for cross-module reference. Defined by `exports`, enforced during Phase 2. Because `uses` now covers all cross-module s0ma references (not just calls), the public API namespace governs the full cross-module surface.

**The test API namespace** is the subset of a module's components declared with `visibility: TEST`. It is *not* part of the module's `exports:` list — TEST components are reachable cross-module via `uses:` only from modules that contain at least one `test` declaration ("test consumers"). A production module with zero test declarations that adds a `TEST`-visibility component to its `uses:` produces `TEST_VISIBILITY_VIOLATION` (error in every strictness mode). The check is local: source module declares ≥1 test? OK to use TEST. Else, error. There is no transitive analysis. See ADR-008.

> **KEY:** `uses`/`exports` governs who can CALL across modules. `uses` of a `TEST`-visibility component is permitted only from test consumers. The registry governs who can OBSERVE or TEST. `requires` provides Python names for code bodies but not for DSL metadata. This four-way separation is the operational meaning of total observability combined with architectural access control.

**Cross-module access-control matrix** (which source module can `uses:` which target visibility):

| Target visibility | Source: production module (no tests) | Source: test consumer (≥1 test) |
|---|---|---|
| `PUBLIC`, in `exports:` | OK | OK |
| `PUBLIC`, omitted from `exports:` | `VISIBILITY_MISMATCH` (intra-module) | `VISIBILITY_MISMATCH` (intra-module) |
| `INTERNAL` | `NOT_EXPORTED` | `NOT_EXPORTED` |
| `TEST` | **`TEST_VISIBILITY_VIOLATION`** | OK (and exempt from `NOT_EXPORTED`) |

The `INTERNAL` row is unchanged from the v0.11 model: INTERNAL forbids cross-module `uses:` from any source. The new `TEST` row is the load-bearing addition: it grants test consumers cross-module access to a target without that target appearing in the public export surface.

#### 4.10.2 Name Resolution Rules

**In the component-reference namespace (`depends_on`, `raises`, axon targets):**

1. Locally declared components in the current module.
2. Names imported via `uses`.
3. If neither matches, parse error.

**In the code namespace (Python bodies):** All names from local declarations, `uses`, and `requires` are available.

**In the registry namespace (`observes`, `tests`):** Bare names resolve within the current module. Qualified names (`module::component`) resolve against the full registry.

**Aliases:** If `uses: [auth.validate_token as verify_token]`, then `verify_token` is the name in both the code and component-reference namespaces. The registry stores canonical ID `auth::validate_token`.

#### 4.10.3 Namespace Collision Rules

**Any collision in the module's code or component-reference namespaces is a transpile-time error.** Local vs. `uses`, `uses` vs. `uses`, `uses` vs. `requires` — all errors. No silent shadowing.

#### 4.10.4 Registry Storage

All components stored by canonical ID. Two modules may each have a component named `validate` without collision.

#### 4.10.5 The `.s0ma.json` Intermediate Representation

Normalised JSON artifact per module: complete metadata, all names canonical, all inline axons expanded, all globs resolved, all derived edges materialised, `content_hash` included. Primary interface for AI tools.

#### 4.10.6 Privileged Imports for Observation and Verification

The spec guarantees that tests and ganglia can reach INTERNAL components cross-module (via the registry namespace). But the generated Python still needs a concrete import mechanism. The transpiler resolves this through **privileged imports**:

When a test's `tests` field references a component in another module that is not in that module's `exports`, the transpiler emits a direct Python import in the generated test file, bypassing normal `uses`/`exports` validation. The same mechanism applies when a ganglion's `observes` field references cross-module INTERNAL nerves.

Privileged imports are tightly scoped:

- Available only in generated test files and ganglion files.
- Only for names referenced via the registry namespace (`tests` field, `observes` field).
- Never available in normal module code bodies.

The transpiler marks these imports distinctly in the IR: `"import_kind": "privileged_observation"` or `"import_kind": "privileged_verification"`. This makes them auditable and distinguishable from normal imports.

> **▲** Privileged imports exist to close the gap between the language promise (total observability) and the execution model (Python's import system). They are an implementation mechanism, not a loophole. Normal module code cannot use them. Their scope is enforced by the transpiler, not by convention.

#### 4.10.7 Served Identity — the `serves_as:` Field (DSL-M1, 0.17.0)

`serves_as:` (§4.1.12) introduces a SECOND, deliberately narrow identity: the public serving name. The rules keep the two identities from ever blurring:

- **The declaration identifier remains the component identity.** The canonical ID stays `<module>::<declaration_name>`, the registry stores the declaration name, the emitted module attribute (and `__all__` entry, and every `uses:`/`exports:` reference) stays the declaration name, and the runtime `ComponentSpec.name` is the declaration name. Nothing in the language resolves against served names.
- **The served name is carried, not resolved.** It rides the IR (`fields.serves_as`) and the emitted registration dict (reserved key `serves_as`) so registry-deriving consumers can bind their public surface from registry data alone.
- **The emitter stamps the callable's introspection identity.** Immediately after the decorated def — separated by one blank line, before any subsequent emitted statement — the emitter writes the two-line stamp:

```python
@component(
    name="check_tool",
    ...,
    metadata={"visibility": "PUBLIC", "evaluates_at": "FUNCTION_BOUNDARY", "serves_as": "check"},
)
def check_tool(path: str | None = None) -> dict[str, Any]:
    ...

check_tool.__name__ = "check"
check_tool.__qualname__ = "check"
```

**Decorate-then-stamp is the load-bearing ordering:** `@component` executes at def time and derives `qualified_name` from the symbol BEFORE the stamp runs, so the registered spec keeps the declaration identifier while only the callable's `__name__`/`__qualname__` carry the served name — which is precisely what schema-title derivation in serving frameworks reads. Nerves emit only module-level callables, so the `__qualname__` leaf is the whole `__qualname__`. Introspection consumers must learn that `__name__` ≠ attribute name when `serves_as:` is authored — that asymmetry is the feature, documented here so it is never a surprise.

**Uniqueness scopes.** Served names form one flat namespace: `SERVES_AS_COLLISION` fires per module (semantic phase) and per project build (cross-module resolver phase). Equality with the declaration's own identifier is permitted; equality with ANOTHER declaration's identifier is not this check's concern — the registry namespace is the declaration-name namespace and stays disjoint by construction.

### 4.11 Authored vs. Derived Relationships

The dependency graph contains two categories of edges. Each relationship has exactly one authoritative source. Redundant declarations: warning in dev, error in strict.

#### 4.11.1 Authored Relationships

| Relation | Declared Via | Authoritative Source |
|----------|-------------|---------------------|
| `CALLS` | `depends_on` or standalone axon | The axon declaration |
| `CONSTRUCTS` | `depends_on` or standalone axon | The axon declaration |
| `READS` | `depends_on` or standalone axon | The axon declaration |
| `CONFIGURES` | `depends_on` or standalone axon | The axon declaration |
| `PRODUCES` | `depends_on` or standalone axon | The axon declaration |
| `CONSUMES` | `depends_on` or standalone axon | The axon declaration |
| `tests` (verification) | `tests` field on test declarations | The `tests` field |

#### 4.11.2 Derived Relationships

| Relation | Derived From | Authoritative Source |
|----------|-------------|---------------------|
| `RAISES` | `raises` field on nerve declarations | The `raises` field |
| `TYPE_USES` | Python type annotations in nerve/ganglion signatures, and constructor calls to known cells in nerve/ganglion bodies | The Python signature and body |
| `READS` (derived form) | References in nerve/ganglion bodies to CONSTANT cells, of the module or imported through `uses` | The Python body, unless an axon already covers the pair |
| `CALLS` (derived form) | Calls in nerve/ganglion bodies to the nerves and ganglia of the same module | The Python body, unless an axon already covers the pair |

**RAISES:** Derived from `raises`. Transpiler resolves to canonical IDs and emits edges. Authors must not declare `RAISES` axons.

**TYPE_USES:** Derived from two sources: (1) Python type annotations in nerve and ganglion function signatures (parameter types and return types), and (2) constructor calls in nerve and ganglion bodies where the callee is a known cell (e.g., `ToolParameter(name="file")` where `ToolParameter` is a MODEL cell). Cell field annotations, base class references, and Protocol implementations are not in scope for v1 derivation — cell-internal type relationships are structural details covered by the `schema` field. Authors must not declare `TYPE_USES` axons. No exceptions.

**READS to a constant:** Derived from the body. A nerve or ganglion body that refers by name to a `CONSTANT` cell, one of its own module or one imported through `uses`, depends on that constant: the limit is connected to the part it governs. The transpiler emits a `READS` edge with origin `constant_reference` for each such pair; a name the body also binds (a parameter, a local assignment) is not read as the constant. `READS` stays an authored relation as well. An authored edge between the same source and target, whatever its relation, is the architectural statement and wins: no derived edge is emitted for that pair and no `DUPLICATE_AXON` is raised, so a project that already authors `READS` to its constants keeps its declarations as the one record of each. Imported constants are derived when the build has the whole project parsed, which `s0ma build` does; a single-file transpile derives the module's own constants alone.

**CALLS to a sibling:** Derived from the body. A nerve or ganglion body that calls another nerve or ganglion of its own module by bare name (`return neutral_payload_text(cfg)`) depends on it, and nothing else records that pair: the module's `uses:` list names what the module imports, never which component calls what, and a sibling is not imported through it at all. The transpiler emits a `CALLS` edge with origin `body_call` for each such pair, once per callee, so the self-model's dependency statements reach inside a module. Only direct calls by bare name count: a call through an attribute (`obj.method()`), a name the body binds itself (a parameter, a local assignment), a body's call to itself, and a call to anything that is not a component of the module (a helper, a `requires` import, a builtin) derive nothing. A call to a component of another module keeps the derivation it already had: through `uses:`, a constructor call to a cell derives `TYPE_USES` with origin `constructor_call`, and this rule does not change it. `CALLS` stays an authored relation as well, and the authored edge wins exactly as it does for `READS`: an axon between the same source and target, whatever its relation, is the one record of the pair, no derived edge is emitted and no `DUPLICATE_AXON` is raised. The derivation needs no project view; `s0ma check` and `s0ma build` derive the same edges from the module alone.

> **KEY:** Each relationship has exactly one authoritative source. If derivable, do not author it. If not derivable, you must author it. A `READS` edge to a constant and a `CALLS` edge to a sibling are the two exceptions in the other direction: derivable, and still yours to author when you want to say what they carry.

#### 4.11.3 What the Transpiler Derives

Per nerve and ganglion: `RAISES` edges (from `raises`), `TYPE_USES` edges (from function signature annotations and constructor calls to known cells), `READS` edges to the constants the body refers to, `CALLS` edges to the nerves and ganglia of the same module the body calls, auto-generated intent for inline `depends_on`.

Per `CONSTANT` cell: the literal value at `components[].fields.value` (§4.2.3).

Per module: `content_hash`, resolved `observes` lists, import statements.

Per `doc-ref` and `doc-guide`: a transitive `content_hash` over the doc declaration's canonical form plus the registry state of every entity it touches (see §4.12.5).

### 4.12 Documentation Declarations

A self-aware system whose documentation can drift away from its code is, by Principle 1, no longer self-aware in the dimension that matters most for human and AI consumers. Three declaration types — `doc-ref`, `doc-guide`, and `example` — bring documentation under the same grammar-level enforcement as nerves, cells, and ganglia.

| Declaration | Role |
|-------------|------|
| `doc-ref` | Generated reference material rendered entirely from registry state. No prose body. |
| `doc-guide` | Hand-authored narrative whose every named factual claim is either a typed `{{...}}` reference, a registered `example`, or a verifiable `asserts:` expression. |
| `example` | First-class executable demonstration of one or more registered components. |

All three declarations resolve references in the **registry namespace** (§4.10.1) — total observability, not limited by exports. All three are subject to the validation layers in §4.12.4 and the content-hash drift check in §4.12.5.

> **KEY:** Documentation is a projection of the self-model, not a parallel surface. Every claim a doc makes must be either rendered from a registry field, asserted as a verifiable expression, or demonstrated by an executable example. There is no fourth option.

#### 4.12.1 `doc-ref` (Structural Projection)

A `doc-ref` declaration renders part of the registry according to an authored template. It has no Python body and no prose body. The only authored prose it may contain is its own `intent` and the `title` field on each section.

```
doc-ref <n>
    intent: "<why this doc-ref exists>"
    format: <markdown | html | json>
    output: <relative file path>
    covers: [<filter expression>(, <filter expression>)*]
    sections: [<section name>(, <section name>)* | for <var> in <filter expression>]
```

**Mandatory fields:** `intent`, `format`, `output`, `covers`, and — in the component filter form only — `sections`. In the source-registry form `sections:` is optional; §4.14.5 classifies it **SC** for `doc-ref` accordingly.

**Optional fields:** `tags`

**Body:** Prohibited. The `---` separator must not appear. Violations produce `PARSE_DOC_REF_BODY_PROHIBITED` in all strictness modes.

**`covers:` accepts** one of two shapes (a discriminated union):

1. **Component filter form (historic).** One or more filter expressions over registry entity types. The expression grammar is narrow by design (see §4.12.4 Layer 2):

   ```
   covers: [nerve where visibility == PUBLIC]
   covers: [nerve where visibility == PUBLIC, cell where kind in [MODEL, CONSTANT]]
   covers: [nerve where module == tools]
   ```

   A `where` predicate addresses an entity's per-kind fields (§4.1–§4.3, §4.8) plus one field every kind shares: **`module`** (added in 0.17.0, ADR-011 §(h), F-M5-2) — the name of the module that owns the entity. `module` lets a multi-module project render per-module references (`covers: [nerve where module == tools]`) rather than one project-wide doc; it is equally addressable in field-access (`{{nerve::X.module}}`) and `asserts:`. Comparison is by name; an unrecognised module value matches no entity (surfacing as `EMPTY_DOC_FILTER` like any other empty predicate — there is no separate unknown-module diagnostic).

2. **Source-registry form (added in 0.12, G7a).** A single-key dictionary naming a derived non-component registry the renderer materialises directly. The derived-source registry (ADR-013) is the authority for which names are valid, and the set is release-bound: a name a given release does not register is a parse error at that release. The names valid in this release are `error_codes` (the canonical union of `SEVERITY_MATRIX` and `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`), `cli_commands` (every command the `s0ma` command line serves, with its positionals, its flags, and what running it touches), `document_catalog` (every document a checkout catalogs, with its canonical source, standing, and the authority it is), and `package_inventory` (the distributions a checkout ships, their versions, and which of them depends on which). The last two describe a *checkout* rather than the toolchain, so a renderer that has not been handed one cannot materialise them; the registry declares that per source and the failure is named, never an empty table.

   ```
   covers: { source: error_codes }
   ```

   In the source-registry form `sections:` is optional — the renderer emits a single deterministic table directly from the named registry's records. An empty `sections: []` still parses; a non-empty one is rejected at parse time (`PARSE_ERROR`), as is mixing `kind:` and `source:` keys in the dictionary. Both discriminators are exclusive.

**`sections:` accepts** either a list of registry field names to render per covered entity, or an iteration expression `for <var> in <filter expression>`:

```
sections: [intent, expects, guarantees, raises]
sections: [for n in nerve where visibility == PUBLIC ordered_by name]
```

`sections:` may name `forbids` for nerves and ganglia alike; `sections: [intent, expects, guarantees, forbids]` renders what each covered nerve must never do beside what it needs and what it promises.

A `doc-ref` whose `covers:` filter materialises to zero matching entities emits `EMPTY_DOC_FILTER` — warning in `migration` / `dev` / `strict`, error in `release` (mirrors `EMPTY_OBSERVES` for ganglia). The source-registry form does not emit `EMPTY_DOC_FILTER` — the registry it pulls from is part of the transpiler's own configuration, not user-authored components, so a "zero matches" outcome would indicate a structural transpiler bug rather than authoring drift.

#### 4.12.2 `doc-guide` (Narrative With Registry-Bound References)

A `doc-guide` declaration is the concession to genuine narrative needs — task-oriented walkthroughs, conceptual explanations, migration guides. Prose is allowed, but every claim about a named system entity must be a typed `{{...}}` reference, a registered `example` embed, or a verifiable `asserts:` expression.

```
doc-guide <n>
    intent: "<why this guide exists>"
    format: <markdown | html | json>
    output: <relative file path>
    covers: [<entity ref>(, <entity ref>)*]
    asserts: [<assert expression>(, <assert expression>)*]
    examples: [example::<n>(, example::<n>)*]
    ---
    <prose body with {{nerve::X}}, {{cell::Y.intent}}, {{example::Z}} tokens>
```

**Mandatory fields:** `intent`, `format`, `output`, `covers`, `asserts`, `examples`, body

**Optional fields:** `tags`

**Allowed in the prose body:**

- Headings, paragraphs, bullet lists, and standard Markdown structural elements
- Narrative connective text ("welcome", "next we will", "note that")
- `{{kind::name[.field]}}` reference tokens that resolve against the registry
- `{{example::X}}` tokens that embed the actual rendered source of a registered example

**Prohibited in the prose body:**

- Raw fenced code blocks (triple-backtick or triple-tilde) — emits `PROSE_RAW_CODE_BLOCK` in all strictness modes. All code blocks must be example embeds.
- Implicit named references (an identifier-shaped backtick span such as `` `ChatRouter` `` that isn't wrapped in `{{...}}`) — emits `POSSIBLE_UNRESOLVED_REFERENCE` (warning in `migration`/`dev`/`strict`, error in `release`). Either wrap as `{{nerve::ChatRouter}}` or move the claim into `asserts:`.
- Any factual claim about a named component, cell, module, or edge that bypasses the reference / example / assert mechanism.

**The `asserts:` field** captures narrative claims that aren't directly rendered from a registry field. Each assert is a narrow expression — field access, `==` / `!=` / `in`, boolean composition (`and` / `or` / `not`). No iteration, no ordering, no grouping, no arithmetic, no string concatenation. Failed asserts produce `ASSERT_FAILED` (with expected-vs-actual context) in all modes; unevaluable asserts produce `ASSERT_UNEVALUABLE`.

```
asserts: [nerve::ChatRouter.visibility == PUBLIC, nerve::ChatRouter.kind == FUNCTION]
```

#### 4.12.3 `example` (Executable Demonstration)

An `example` is a first-class registered component whose purpose is to demonstrate a scenario involving other registered components.

```
example <n>
    intent: "<what this example teaches>"
    demonstrates: [<entity ref>(, <entity ref>)*]
    runs_in: <standalone | pytest | integration>
    ---
    <Python body>
```

**Mandatory fields:** `intent`, `demonstrates`, `runs_in`, body

**Optional fields:** `tags`

**Critical property:** Examples execute. An example that cannot be run against the live system is not an example. A failing example fails the build the same way a failing test does — see §4.12.4 Layer 6.

**Body restrictions:** Example bodies are free-form Python and may use bare `import` statements (unlike nerve bodies). The single body-shape check applied is the prohibited-construct check inherited from nerves (`exec`, `eval`, `__import__`, `importlib.import_module`, monkey-patching). This is a deliberate deviation from `nerve` body validation: examples are read by humans, and forcing an example to declare every import in a synthetic module header would obscure rather than illuminate.

**Why `demonstrates:` is mandatory and non-empty:** it creates the reverse index that powers `get_examples_for_component(name)` in the framework registry — a coding agent editing `nerve::X` can ask the registry which examples teach `X` and update them in the same change.

**Example vs. test:**

| Aspect | `test` | `example` |
|--------|--------|-----------|
| Primary consumer | Verification pipeline | Human / AI comprehension |
| Pass/fail is | The point | A side effect of being valid |
| Source visibility | Implementation detail | Part of the rendered output |
| Brevity | Not required | Required (it will be read) |

Examples are not a substitute for tests. Tests validate behaviour; examples teach it.

#### 4.12.4 Validation Layers

Documentation declarations pass through six validation layers, each running cheaper checks first. Failure at any layer fails the build.

| Layer | Check | Cost | Where |
|-------|-------|------|-------|
| 1. Grammar | Mandatory fields present, body rules respected, separator usage correct. | µs | Per file |
| 2. Template / Reference parsing | `{{...}}` tokens, `where` predicates, `ordered_by` / `group_by` / `for` clauses parse into the narrow expression AST. | ms | Per file |
| 3. Reference resolution | Every entity ref, field access, and filter predicate resolves against the project's registry namespace. Diagnostics include "did you mean ...?" suggestions. | ms | Project-wide |
| 4. Assert evaluation | Every `asserts:` expression evaluates true against the registry. Failures include expected-vs-actual context. | ms | Project-wide |
| 5. Content fingerprinting | The transpiler computes a transitive `content_hash` over the doc and every registry entity it touches; CI re-renders and compares. | s per project | CI / `docs check-drift` |
| 6. Example execution | Every registered `example` is run in its declared `runs_in` context; raising or failing is a build failure. | varies | Test pipeline |

Layers 1–4 run inside the transpile pipeline. Layer 5 runs explicitly via `s0ma-dsl docs check-drift` and inside `s0ma-dsl compile` when rendering. Layer 6 runs through the framework's `ExampleRunner` (`s0ma-dsl examples run`).

**The template expression grammar** supports: entity refs (`nerve::X`), field access (`nerve::X.intent`), filter predicates (`where visibility == PUBLIC and kind in [SERVICE, FUNCTION]`), ordering (`ordered_by <field>(, <field>)*`), grouping (`group_by <field>`), iteration (`for <var> in <filter expression>`), and boolean composition (`and`, `or`, `not`). It deliberately does not support arbitrary Python, string concatenation, or arithmetic — anything that could be used to synthesise a claim the registry cannot verify is rejected as `TEMPLATE_SYNTAX_ERROR`.

**The assert expression grammar** is strictly narrower: field access, `==` / `!=` / `in`, boolean composition. No iteration, ordering, or grouping. Violations are `ASSERT_SYNTAX_ERROR`.

#### 4.12.5 Content Hashing and the Drift Check

Each rendered doc carries a transitive `content_hash` computed over: (1) the doc declaration's canonical form, (2) the registry state of every entity touched (transitively, through references and `covers:` filters), (3) the source of every embedded example, and (4) the transpiler version (the `ir.schema.TRANSPILER_VERSION` codegen-contract constant). The hash is emitted into both the rendered output's front-matter and the registration call in the generated `.py`. The transpiler version participates in the hash but — since 0.17.0 (ADR-011 §(f)) — is no longer a separate rendered front-matter field (see below).

**Front-matter contract** (seven fields, declared order):

```
s0ma_kind | name | module | format | intent | schema_version | content_hash
```

`transpiler_version` was DROPPED from the front matter in 0.17.0 (ADR-011 §(f), F-M5-5). It collided in name with the build manifest's `transpiler_version`, which carries the *distribution* version, whereas the front-matter field carried the *codegen-contract* constant (`1.0.0`). `schema_version` (= `ir.schema.SCHEMA_VERSION`) remains the front matter's contract identity; the distribution version lives only in the manifest's `transpiler_version` and the `.pyi` header. Dropping the field means rendered docs no longer churn on a distribution bump (only the manifest and stub do). The content hash is unchanged by the drop (its inputs did not change).

For Markdown the front-matter is YAML between `---` delimiters; for HTML it is `<meta name="s0ma:...">` tags; for JSON it is a top-level `_meta` block. Adding, removing, or reordering fields is a contract change carried by `SCHEMA_VERSION` — the 0.17.0 drop of `transpiler_version` rides the same 2.1.0 bump as the rest of the additive language batch (pre-1.0 minor, INV-4).

**The drift check** (CI gate, runs on every merge to `main`):

```
for each doc-ref / doc-guide:
    re-render at HEAD
    compare computed hash to the committed hash
    if different: fail with DRIFT_DETECTED
```

`DRIFT_DETECTED` severity by mode: warning in `migration` and `dev`; error in `strict` and `release`. This is the structural invariant that makes drift not merely detectable but impossible in `main`.

**Output base directory (added in 0.17.0, ADR-011 §(h), F-M5-4).** A doc's `output:` is a relative path resolved against a base directory chosen by a fixed precedence shared by `s0ma build`, `s0ma docs render`, and `s0ma docs check-drift`, so the drift gate always re-renders into the directory the build wrote: (1) an explicit `--output-dir` flag wins; (2) otherwise the resolved project's `[tool.s0ma].build_dir` — a project build emits docs under `<build_dir>/<output:>`, so the rendered docs ride the committed build and its byte-equality gate; (3) otherwise (a synthetic invocation with no `[tool.s0ma]` table) the source path if it is a directory, else its parent. The relative-path constraint (`output:` may not escape the base) is enforced regardless of which base is selected.

#### 4.12.6 Strictness Mode Behaviour

| Code | migration | dev | strict | release |
|------|-----------|-----|--------|---------|
| `PARSE_DOC_REF_BODY_PROHIBITED` | error | error | error | error |
| `TEMPLATE_SYNTAX_ERROR` | error | error | error | error |
| `ASSERT_SYNTAX_ERROR` | error | error | error | error |
| `PROSE_RAW_CODE_BLOCK` | error | error | error | error |
| `UNRESOLVED_REFERENCE` | error | error | error | error |
| `ENTITY_KIND_MISMATCH` | error | error | error | error |
| `FIELD_NOT_FOUND` | error | error | error | error |
| `UNREGISTERED_EXAMPLE` | error | error | error | error |
| `ASSERT_FAILED` | error | error | error | error |
| `ASSERT_UNEVALUABLE` | error | error | error | error |
| `POSSIBLE_UNRESOLVED_REFERENCE` | warning | warning | warning | error |
| `EMPTY_DOC_FILTER` | warning | warning | warning | error |
| `DRIFT_DETECTED` | warning | warning | error | error |
| `MISSING_PUBLIC_DOC_REF` | — | — | — | error |
| `MISSING_EMBEDDED_EXAMPLE` | — | — | — | error |

`MISSING_PUBLIC_DOC_REF` fires when a PUBLIC nerve is not covered by at least one `doc-ref`. `MISSING_EMBEDDED_EXAMPLE` fires when a registered `example` is not embedded in at least one `doc-guide`. Both are release-only, mirroring the existing `MISSING_TEST_COVERAGE` pattern for tests (§4.8).

#### 4.12.7 Documentation Type Taxonomy

| Document type | Implementation |
|---------------|----------------|
| Pure projection (API references, entity catalogues) | `doc-ref` only |
| Narrative with registry-bound references (user guides, walkthroughs) | `doc-guide` plus embedded `example`s |
| Conceptual / framework teaching (this spec, theory of operation) | Hand-authored Markdown, exempt under P7 |

Application repositories should default to (1) and (2). Conceptual documentation that does not name registered components is not subject to the documentation subsystem and remains hand-authored. The DSL spec itself remains hand-authored under P7 in perpetuity — it is conceptual framework teaching by definition.

---

### 4.13 Project Configuration

A s0ma project is a **declarative artifact** rooted at the consumer's `pyproject.toml`. The `[tool.s0ma]` table tells every CLI subcommand where source lives, where build artifacts go, which test directories to walk, and which plain-Python files are intentional bootstrap exceptions. This replaces ad-hoc per-command flags and the implicit "wherever you ran `s0ma` from" behaviour of earlier versions.

**Discovery algorithm.** When invoked, every CLI subcommand resolves a `S0maProject` by walking upward from the working directory (or the path given to `--project-root`) until it finds a `pyproject.toml` containing a `[tool.s0ma]` table. The directory containing that `pyproject.toml` becomes the project `root`. If no `[tool.s0ma]` table is reachable, the CLI falls back to a synthetic project rooted at the working directory and emits a one-line warning:

```
warning: Operating without project discovery. Add `[tool.s0ma]` to pyproject.toml for full functionality.
```

**Schema.** All keys in `[tool.s0ma]` are optional; defaults apply when a key is omitted. Paths are interpreted relative to the project root (the directory containing `pyproject.toml`).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `source_roots` | list of strings | `["src"]` | Directories holding `.s0ma` source modules. **G2 (feedback 5–6 cleanup):** must be disjoint from every `test_roots` entry and from every other `source_roots` entry — no root may be a subpath of another, and no two roots may resolve to the same path. Violations raise `OVERLAPPING_DISCOVERY_ROOTS` at project-load time. |
| `test_roots` | list of strings | `["tests"]` | Directories holding `.s0ma` test modules. **G2 (feedback 5–6 cleanup):** must be disjoint from every `source_roots` entry and from every other `test_roots` entry (same rule as `source_roots`). |
| `build_dir` | string | `"<sanitized_project_name>_build"` | Directory for transpiled artifacts. The default is derived from `[project].name`: every non-word character (`\W`) is replaced with `_` so a hyphenated / dotted / spaced project name still produces a valid Python identifier (e.g. `kn0wthyself-website-2` → `kn0wthyself_website_2_build`). **G3 (feedback 5–6 cleanup):** the directory's last path component is the importable token consumed by the runtime bridge (`from <build_dir_basename> import <module>`); when the author sets `build_dir` explicitly the basename must be a valid Python identifier (e.g. `out/foo_bar` is fine; `out/foo-bar` is rejected because `foo-bar` is not an identifier). Project names that cannot be sanitized to a valid identifier (digit-start, sanitizes-to-empty) raise `INVALID_PROJECT_NAME_FOR_BUILD_DIR` at project-load time with a remediation message instructing the author to set `build_dir` explicitly. |
| `bootstrap_files` | list of strings | `[]` | Plain-Python files (relative paths) that are intentional bootstrap exceptions. `s0ma verify` recognises every entry as status `BOOTSTRAP` (informational, hidden by default; `--verbose` re-introduces the per-file rows). The runtime bridge does not register bootstrap files as components — the build manifest is the registration set, and bootstrap files are by construction outside it. |
| `package_markers` | list of strings | `[]` | **G1 (feedback 5–6 cleanup):** Python `__init__.py` files (relative paths) that the author explicitly acknowledges as package markers. `s0ma verify` reports every entry as status `PACKAGE_MARKER` (informational, hidden by default; `--verbose` surfaces the per-file rows and the count). Most package markers do not need to be declared — `s0ma verify` auto-classifies any `__init__.py` whose body is empty, whitespace only, or a single docstring (see "Status taxonomy for `s0ma verify`" below). The escape hatch exists for `__init__.py` files carrying `__all__` re-exports, imports, or any executable content the author wants acknowledged as a marker rather than reported as `UNKNOWN`. A file appearing in both `bootstrap_files` and `package_markers` raises `CONFLICTING_PACKAGE_DECLARATION` at project-load time. |
| `test_runner` | string | `"pytest"` | The test-runner identity. Today only `"pytest"` is supported; an unsupported value (e.g. `"nose"`) raises `ValueError` at project-discovery time naming the supported set. The runner identity is what makes runner-discovery semantics possible (see "Test-runner discovery" below): test functions are auto-discovered by the named runner, so a test module whose body has no `pytest.<symbol>` reference does not need `pytest` in `requires:`. The transpiler uses this key to decide what runner-specific stubs to emit (today: none — pytest discovers `test_*` functions by name). |
| `attribute_budgets` | sub-table (string → string) | `{}` | Project-level uniqueness budgets for `declares_attributes:` namespaces. Each key is a namespace (the left-hand side of a `<namespace>:<attribute>` entry on a nerve); each value is one of the three supported budget shapes: `"exactly_one_per_page"`, `"unique_in_project"`, or `"warn_on_duplicate"`. See "Attribute budgets" below. |
| `test_layering` | string | `"strict"` | **POST-6 (0.16.0):** project-level stance for the cross-module layer-reachability check (§4.0.2). `"strict"` (default) preserves the pre-0.16.0 behaviour: every module's `uses:` is checked against the reachability matrix, including test-context modules. `"permissive"` exempts modules with at least one `test` declaration from the cross-layer check; production modules (zero `test` declarations) still get the strict check regardless. The carve-out trigger mirrors the M13 helper-access rule (`HELPER_PRIVATE_TO_MODULE`): "module has ≥1 test declaration" is the test-context predicate. Unknown values raise `ValueError` at project-load time naming the supported set. See "Test-layer opt-in" below for the full rationale. |
| `test_module_name_prefix_by_dir` | boolean | `false` | **POST-10d (0.16.0):** auto-prefix test modules by their immediate parent directory when running the `MODULE_NAME_COLLISION` check. The default `false` preserves the pre-0.16.0 behaviour: any two source files declaring the same `module <name>` collide regardless of directory. Set to `true` to opt the project into a directory-aware discriminator for test-context files: a `tests/unit/foo.s0ma` and a `tests/integration/foo.s0ma` may both keep `module foo` because the effective names used by the collision check are `unit_foo` and `integration_foo`. Production modules under `source_roots` are unaffected — they always require unique declared names. The flag affects the collision check only; cross-module `uses:` references continue to resolve against the AST-declared name. Authored as a TOML boolean; a non-boolean value (including the string `"true"`) raises a friendly `ValueError` at project-load time. See "Test-module dir-prefix opt-in" below for the rationale and worked example. |
| `fixtures_format` | sub-table (string → string) | unset (`None`) | **POST-12g (0.16.0):** expected format for non-`.s0ma` test fixtures. Each key is a filename glob (e.g. `"*.jsonl"`, `"*.yaml"`); each value names a supported validator: `"ndjson"` (one JSON object per line, blank lines tolerated), `"json"` (one whole-document JSON value), or `"yaml"` (one whole-document YAML value via `yaml.safe_load`; requires PyYAML at runtime). `s0ma check` walks every configured `test_roots` directory looking for files matching each glob and validates them via the format-specific parser. Failures fire `FIXTURE_FORMAT_INVALID` (warning in dev/migration, error in strict/release). Files that do not match any configured glob are ignored — fixtures stay opt-in. Unknown format values raise `ValueError` at project-load time naming the supported set. See "Fixture-format validation" below for the full surface. |
| `venv_path` | string | unset | **0.14 M2:** project-relative host virtual-environment directory (or Python executable) used exclusively by explicit `s0ma verify-host`. Absolute values and values whose resolved path escapes the project root are refused. External interpreters are allowed only through the caller's explicit `--python` argument. |

**Minimum example.**

```toml
[tool.s0ma]
source_roots = ["src"]
```

**Full example.**

```toml
[project]
name = "myproj"

[tool.s0ma]
source_roots = ["src"]
test_roots = ["tests"]
build_dir = "myproj_build"
bootstrap_files = ["src/myproj/main.py"]
# Most __init__.py files do not need to be declared — empty /
# docstring-only ones are auto-classified as PACKAGE_MARKER. Only
# list __init__.py files that carry __all__ re-exports or other
# executable content the author wants acknowledged as a marker.
package_markers = ["src/myproj/exports/__init__.py"]
test_runner = "pytest"
venv_path = ".venv"
```

**Test-runner discovery (M15, feedback 5–6).** A test module is *discovered* by the configured `test_runner` — pytest finds functions named `test_*` automatically; no import is required for discovery. The transpiler treats the runner as an environment dependency, not a body dependency, with the following rules:

- **Body-level use of `pytest.<symbol>`** (e.g. `pytest.raises`, `pytest.fixture`, `pytest.mark`) **requires `pytest` in `requires:`.** The generated `.py` then carries `import pytest` and the existing `VESTIGIAL_IMPORT` checker is unchanged: `pytest` in `requires:` without a body reference still produces `VESTIGIAL_IMPORT`.
- **Mere runner discovery** — test functions named `test_*` or test files named `*_tests.py` — **does not require `pytest` in `requires:`.** Omission is correct and idiomatic; the runner is configured by `[tool.s0ma].test_runner`, not declared per-module.

The 0.11.0 papercut "strip `pytest` from `requires:` to silence `VESTIGIAL_IMPORT`" is gone. The IR's dependency model is now coherent in both directions: a body that uses `pytest.<symbol>` records the dependency in `requires:`; a body that does not use any `pytest.<symbol>` records nothing — and the build is clean either way.

**Attribute budgets (M18, feedback 5–6).** A nerve may carry an optional `declares_attributes:` field whose entries are `<namespace>:<attribute>` strings (HTML landmarks, HTTP routes, CSS classes, RPC method names — any structural claim the project models). The field is purely descriptive on its own — it surfaces in the IR JSON and `s0ma inspect`. To enforce uniqueness, a project adds a `[tool.s0ma.attribute_budgets]` sub-table mapping the namespace to one of three budget shapes:

| Shape | Semantics |
|---|---|
| `exactly_one_per_page` | Exactly one nerve in the reachable nerve set of each *page* must declare a given `<namespace>:<attribute>` string. **F3 (feedback 5–6 follow-up):** a "page" is the module owning a nerve marked `is_page_composer: true` (see §4.1.6). The reachable nerve set is computed by walking the transitive closure of `module.uses` from each marked nerve's owning module. The shape requires at least one nerve in the project to be marked; if none is, the resolver emits `NO_PAGE_COMPOSER_DECLARED` (error in every mode). Zero or more-than-one occurrences of any governed attribute fire `ATTRIBUTE_BUDGET_VIOLATION`. |
| `unique_in_project` | The `<namespace>:<attribute>` string may appear at most once across every nerve in the project. Independent of the `uses:` graph. |
| `warn_on_duplicate` | Same shape as `unique_in_project` but surfaced as warnings in every strictness mode. |

Severity ladder for the error-shaped budgets follows the standard hygiene-rule pattern: `warning` in migration, `error` in dev / strict / release. `warn_on_duplicate` is always a warning. `NO_PAGE_COMPOSER_DECLARED` is `error` in every mode (including migration) — the project is mis-configured, not stylistically lax. The grammar of `declares_attributes:` accepts both bare-token entries (`landmark:header`) and double-quoted entries (`"route:GET /self"`); the latter form lets attributes contain commas, spaces, and slashes without ambiguity.

**Worked examples.**

HTML project — exactly one of each landmark per page:

```toml
[tool.s0ma.attribute_budgets]
landmark = "exactly_one_per_page"
```

```
nerve compose_page :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Top-level page composer that assembles every landmark."
    expects: "Body content."
    guarantees: "Returns a full HTML page."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    is_page_composer: true
    ---
    def compose_page(body: str) -> str:
        return render_header() + render_main(body) + render_footer()

nerve render_header :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Render the page <header> landmark."
    expects: "No arguments."
    guarantees: "Returns a <header>...</header> string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: [landmark:header]
    ---
    def render_header() -> str:
        return "<header>Site title</header>"
```

`compose_page` carries `is_page_composer: true`; the validator walks `uses:` from its owning module and counts `landmark:header` occurrences in the reachable set. A second nerve declaring `landmark:header` reachable from the same composer is `ATTRIBUTE_BUDGET_VIOLATION` at `s0ma check` time. If no nerve carries `is_page_composer: true` while this budget is configured, `NO_PAGE_COMPOSER_DECLARED` fires (error in every mode) — the budget cannot run without an explicit composer.

HTTP project — unique routes across the project:

```toml
[tool.s0ma.attribute_budgets]
route = "unique_in_project"
```

```
nerve handle_self :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Handle GET /self."
    expects: "No arguments."
    guarantees: "Returns a JSON response."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["route:GET /self"]
    ---
    def handle_self() -> str:
        return "{}"
```

A second nerve declaring `"route:GET /self"` anywhere in the project is `ATTRIBUTE_BUDGET_VIOLATION`.

Non-HTML / non-HTTP project — CSS class uniqueness as a warning:

```toml
[tool.s0ma.attribute_budgets]
css_class = "warn_on_duplicate"
```

This is the mechanism that catches the original feedback-5.5 "two `<nav>` landmarks made it to runtime" regression at build time, generalised so HTTP projects (duplicate routes), CSS-heavy projects (duplicate class names), and RPC projects (duplicate method names) all benefit from the same uniformly-typed surface. Without an `[tool.s0ma.attribute_budgets]` table, the `declares_attributes:` field is purely descriptive and no validation fires — projects that don't opt in are unaffected.

**Test-layer opt-in (POST-6, 0.16.0).** The cross-module layer-reachability check (§4.0.2) applies to every module by default, including test modules. The motivating example: a PRESENTATION-layer test fixture that instantiates an INFRASTRUCTURE service for end-to-end coverage fires `CROSS_LAYER_DEPENDENCY` even though the architectural smell the rule targets ("production code reaching across boundary layers") does not apply — tests legitimately span layers as part of their job.

The `[tool.s0ma].test_layering` key carves out test-context modules from the cross-layer check on an opt-in basis:

```toml
[tool.s0ma]
test_layering = "permissive"
```

The carve-out trigger is "module has at least one `test` declaration" — the same predicate the M13 helper-access rule uses to gate `HELPER_PRIVATE_TO_MODULE`. A module with zero `test` declarations stays a production module under both rules; a module with one or more `test` declarations is a test context. Mixed modules (a `nerve` plus a `test` in the same file) qualify for the carve-out — the trigger checks `len(module.tests) > 0`, not "the module is exclusively tests".

The default value `"strict"` preserves the pre-0.16.0 behaviour exactly: every module's `uses:` entries are checked against the matrix regardless of test context. Existing projects are unaffected; opting in is a deliberate choice the author makes once at the project root.

Production modules' `uses:` entries are checked under either value — the opt-in only relaxes the rule for the test surface. A DOMAIN nerve reaching APPLICATION still fires `CROSS_LAYER_DEPENDENCY` in a project configured with `test_layering = "permissive"`. This keeps the rule load-bearing for shipped code while eliminating the persistent warning noise across test modules that mirror real test layouts.

**Test-module dir-prefix opt-in (POST-10d, 0.16.0).** Pre-0.16.0, two `.s0ma` files declaring the same `module <name>` always fired `MODULE_NAME_COLLISION` regardless of where on disk the files lived. The motivating friction: a project with parallel test subdirs (`tests/unit/foo.s0ma` + `tests/integration/foo.s0ma`) had to hand-rename one of the modules even though the *purpose* of the two `foo` declarations is unambiguous from the directory layout.

The `[tool.s0ma].test_module_name_prefix_by_dir` key opts a project into a directory-aware discriminator for the collision check on test-context files:

```toml
[tool.s0ma]
test_module_name_prefix_by_dir = true
```

With the flag on, the immediate parent-directory name of a `.s0ma` file under any configured `test_roots` becomes an implicit prefix on the declared module name when the collision check runs (`tests/unit/foo.s0ma` → effective name `unit_foo`; `tests/integration/foo.s0ma` → effective name `integration_foo`). The two files no longer collide because their effective names are distinct. Files under `source_roots` are unaffected by the flag — production modules always require unique declared names, regardless of directory.

Important boundary conditions:

- The flag only affects the `MODULE_NAME_COLLISION` discriminator; cross-module `uses:` references (e.g. `uses: [foo.do_foo]`) continue to resolve against the AST-declared name. The flag is a check-time discriminator, not a runtime rename.
- The descriptive-suffix steering hint on the collision diagnostic surfaces the flag as an alternative remediation when at least one of the colliding files lives under a configured `test_root` — so projects that haven't opted in see the option in their first collision diagnostic, not buried in the spec.
- Parent directories whose names cannot be sanitized to a Python identifier (e.g. `tests/01_unit/foo.s0ma`) fall through to the un-prefixed name; the flag does not invent garbage prefixes.
- The default `false` preserves the pre-0.16.0 collision behaviour exactly. Existing projects are unaffected.

The flag opts the project into directory layout *being part of the module identity for tests*. Projects that prefer the explicit-rename approach can leave the flag off and use the descriptive-suffix hint instead.

**`requires-python` forward-compat pass (POST-8, 0.16.0).** The standard PEP 621 `[project].requires-python` field declares the project's Python version floor. `s0ma check` reads it once per invocation (no override knob — the floor is a project-level fact, not a per-command flag) and the resolved value is stored on the `S0maProject` instance as `requires_python: tuple[str, ...] | None`. Examples of how the raw string maps onto the tuple:

```toml
[project]
name = "my-project"
requires-python = ">=3.11"          # → (">=3.11",)
# requires-python = ">=3.11,<3.13"  # → (">=3.11", "<3.13")
# requires-python = ">=3.12"        # → (">=3.12",)
# (field absent)                    # → None
```

When the resolved range explicitly admits Python 3.11 (every clause must be satisfied by 3.11), `s0ma check` and `s0ma build` run a forward-compat grammar pass over every emitted body (nerve / cell / ganglion / test). The pass flags three known 3.12-only construct families:

- **PEP 701 nested-quote f-strings** — `f"outer {f"inner"}"` (same-quote nesting inside a brace expression). PEP 701 (Python 3.12) lifted the restriction; earlier 3.x versions raise `SyntaxError` at import. The detector scans the body text directly because the AST does not preserve quote-style.
- **Walrus operator inside a comprehension** — `[(y := x * 2) for x in xs]`. Python 3.10 / 3.11 tightened the placement rules; Python 3.12 reopened them. The detector walks the AST and flags every `NamedExpr` inside a `ListComp` / `SetComp` / `DictComp` / `GeneratorExp`.
- **PEP 695 type-parameter / type-alias syntax** — `def foo[T](x: T) -> T: ...`, `class Foo[T]: ...`, `type Vector = list[T]`. The 3.12 AST exposes `type_params` on `FunctionDef` / `AsyncFunctionDef` / `ClassDef` and adds the dedicated `ast.TypeAlias` node; either is the signal.

Each detection fires `PARSE_GRAMMAR_FORWARD_INCOMPAT` (error in every mode — there is no migration runway because the cost of shipping un-importable code to a 3.11 environment is total). The diagnostic names the declaration kind, declaration name, construct family, and body-relative line / column so the author has a precise pointer at the offending construct. Remediation prose surfaces in the message: either rewrite the body using 3.11-portable grammar (mismatched-quote nested f-strings, walrus outside the comprehension, `TypeVar` from `typing` instead of `[T]` syntax) or tighten `[project].requires-python` to `>=3.12` to declare the 3.12 floor explicitly.

Suppression rules — the pass stays silent when:

- `[project].requires-python` is absent (no declared Python floor — the conservative default refuses to invent one);
- the range excludes 3.11 (`>=3.12`, `>=3.13`, `==3.12`, `!=3.11`, `~=3.12` — the project has opted in to the newer grammar);
- the body cannot be parsed by `ast.parse` (the outer `PARSE_ERROR` pass owns the diagnostic; the compat pass intentionally never double-reports);
- the declaration is a `cell` supplying its body via `content: @file("path")` (the embedded content is verbatim text the codegen writes into a string literal — not Python source).

Helper declarations are out of scope for the compat pass: they emit as module-level `def` / `class` and would fail the same way on import, but the M-12 decision focuses on the four canonical body-bearing declaration kinds (nerve / cell / ganglion / test) where the body is authored Python the consumer interpreter parses directly. Helpers will be revisited if a future motivating case surfaces.

The motivating case: an operator workstation running 3.11 builds a project pinned `requires-python = ">=3.11"` on a 3.12 dev box. Without the compat pass, 3.12-only grammar inside a body compiles cleanly under the transpiler's 3.12 `ast.parse` and the resulting `.py` lands in the wheel; the failure surfaces only when the wheel is imported on the 3.11 workstation, several CI steps downstream from the actual mistake. The compat pass catches the gap at check time, before the codegen step ever runs. See plan post-Phase-2 M-12 (POST-8) for the surrounding context and `src/s0ma_dsl/semantic/python_compat.py` for the detection helpers.

**Fixture-format validation (POST-12g, 0.16.0).** Projects ship non-`.s0ma` fixtures (`.jsonl` event logs, `.yaml` snapshots, `.json` configuration samples) alongside their `.s0ma` test modules. Pre-0.16.0 the build pipeline had no way to assert those fixtures were well-formed; a malformed `.jsonl` would silently corrupt a test or fail at import time several frames removed from the actual file. `[tool.s0ma].fixtures_format` closes the gap by declaring an expected format for each fixture glob:

```toml
[tool.s0ma.fixtures_format]
"*.jsonl" = "ndjson"
"*.yaml" = "yaml"
"*.json" = "json"
```

`s0ma check` walks every configured `test_roots` directory looking for files that match each glob (top-level and nested — the helper uses `Path.rglob`). For each match the validator runs a format-specific parser:

| Format | Validator | Semantics |
|---|---|---|
| `"ndjson"` | `json.loads` per non-empty line | One JSON document per line; blank lines and trailing whitespace are tolerated. The first invalid line surfaces with its 1-based line number. |
| `"json"` | `json.loads` on the full text | One JSON document for the whole file. `json.JSONDecodeError.lineno` (when set) is the reported line number; otherwise `1`. |
| `"yaml"` | `yaml.safe_load` on the full text | One YAML document for the whole file. PyYAML's `problem_mark.line + 1` is the reported line number when available. Requires PyYAML in the project environment (the validator emits a friendly diagnostic if PyYAML cannot be imported). |

Failures fire `FIXTURE_FORMAT_INVALID` with the offending path, the format the project asserted, the parser-thrown error message, and the offending line number. Severity ladders with mode — warning in migration/dev so authors writing fixtures see the finding without being blocked, error in strict/release where shipping malformed fixtures is unacceptable. Files outside every configured glob are ignored (fixtures are opt-in: a project with zero `fixtures_format` entries continues to behave exactly as before).

Empty `test_roots` and missing-on-disk roots short-circuit the pass with zero diagnostics. Unknown format values (`"yaml-stream"`, `"toml"`, …) raise `ValueError` at project-discovery time naming the supported set — a typo cannot silently disable the check.

The pass runs after the standard `.s0ma` validation. Fixtures are non-`.s0ma` so they never go through the parser; the format validator is the only path that ever inspects them. See plan post-Phase-2 M-18 (POST-12g) for the surrounding context and `cli/main.py::_validate_fixtures_format` for the implementation.

**Validation rules.**

- `source_roots`, `test_roots`, `bootstrap_files`, and `package_markers` must each be lists of strings; otherwise the CLI raises `ValueError` at startup with a message naming the offending key.
- `build_dir` must be a string. **G3 (feedback 5–6 cleanup):** the directory's last path component (`Path(build_dir).name`) must be a valid Python identifier — it is the importable token consumed by the runtime bridge (`from <build_dir_basename> import <module>`). When `build_dir` is not set, the default derives from `[project].name` via the sanitization rule `re.sub(r"\W", "_", project_name) + "_build"` so hyphenated / dotted / spaced project names still produce a valid identifier (e.g. `kn0wthyself-website-2` → `kn0wthyself_website_2_build`). Names that cannot be sanitized to a valid identifier — names that start with a digit (`123foo`) or that sanitize to the empty string — raise `INVALID_PROJECT_NAME_FOR_BUILD_DIR` (error in every mode) at project-load time with a remediation instructing the author to set `[tool.s0ma].build_dir` explicitly. Explicit `build_dir` values are validated the same way: `out/foo_bar` is fine; `out/foo-bar` is rejected because `foo-bar` is not an identifier.
- A `bootstrap_files` entry that does not exist on disk produces a one-line discovery warning (not an error). This lets fresh consumer projects declare bootstrap entries before the files are scaffolded. The same accommodation applies to `package_markers`.
- A file path that appears in both `bootstrap_files` and `package_markers` raises `CONFLICTING_PACKAGE_DECLARATION` (error in every mode) at project-discovery time. Each file must be declared in exactly one list — `bootstrap_files` for runtime entry-point code, `package_markers` for re-export-bearing `__init__.py` files.
- **Source and test roots must be disjoint** *(G2 — feedback 5–6 cleanup)*: no `test_roots` entry may be a subpath of any `source_roots` entry (or vice versa), and no two entries within either list may overlap (one being a subpath of the other, or both resolving to the same path). Violations raise `OVERLAPPING_DISCOVERY_ROOTS` (error in every mode) at project-discovery time, before any subcommand runs. Pre-G2, overlap caused every `.s0ma` file under the nested path to be discovered twice — once during the source-root walk, once during the test-root walk — producing an opaque `MODULE_NAME_COLLISION` against a file colliding with itself, several command invocations downstream from the actual mistake. The pre-flight diagnostic names every offending pair plus the two clean-config remediation options: (1) move tests outside the source root (`test_roots = ["tests"]` at top level), or (2) narrow `source_roots` to disjoint layer subdirectories (e.g. `["src/<proj>/application", "src/<proj>/domain", "src/<proj>/presentation"]`). Multiple offending pairs surface together so a misconfigured project clears every overlap in a single edit.
- `test_layering` must be the string `"strict"` or `"permissive"`. Any other value (including `"lax"`, `"loose"`, `"off"`, or a TOML scalar of the wrong type) raises `ValueError` at project-discovery time naming the supported set — typos cannot silently disable the cross-layer check.
- `test_module_name_prefix_by_dir` must be a TOML boolean. A non-boolean value (including the string `"true"`) raises `ValueError` at project-discovery time so a typo cannot silently disable the dir-aware collision discriminator (POST-10d).
- `fixtures_format` must be a TOML table mapping non-empty glob strings to one of the supported format names (`"ndjson"`, `"json"`, `"yaml"`). Unknown format values raise `ValueError` at project-discovery time naming the supported set; non-string keys or non-string values raise a friendly type error pointing at the offending entry (POST-12g).

**Status taxonomy for `s0ma verify` (M11 + G1).** `s0ma verify` classifies every `.py` file under inspection into one of the following statuses; the per-file remediation is surfaced under `--format json` and (where applicable) the default text output, and the summary footer reports the project-wide tallies.

- **`OK` / `CLEAN`** — transpiled artifact whose embedded source-hash and output-hash comments both match the current bytes (the file was emitted by `s0ma build` and has not drifted).
- **`BOOTSTRAP`** — no checksum comments, but the file's absolute path matches a declared `[tool.s0ma].bootstrap_files` entry. Informational; hidden from the default text output, surfaced under `--verbose` and in `--format json`. The summary footer's `M bootstrap file(s) recognized` count includes this status at every verbosity level.
- **`PACKAGE_MARKER`** *(G1 — feedback 5–6 cleanup)* — no checksum comments, and either:
  - the file's absolute path matches a declared `[tool.s0ma].package_markers` entry (the explicit declarative escape hatch), OR
  - the file is auto-classified as an empty Python package marker — its stem is `__init__`, its suffix is `.py`, and its body (after `ast.parse`) is either empty or a single module-level string-literal expression (whitespace-only files take the empty-body branch; multi-paragraph docstrings take the single-statement branch). Any executable content — imports, `__all__`, assignments, calls, classes, functions — disqualifies auto-classification, and the file falls through to `UNKNOWN` unless explicitly declared.
  Informational; hidden from the default text output the same way `BOOTSTRAP` is. Surfaces under `--verbose` (per-file rows) and `--format json` (always). The default summary footer omits the package-marker count to keep the OK / BOOTSTRAP / UNKNOWN signal-to-noise ratio matching M11's noise-floor-zero promise; `--verbose` includes it. **Precedence:** an explicit `package_markers` declaration wins over auto-detection (a non-empty `__init__.py` with `__all__` re-exports listed under `package_markers` is `PACKAGE_MARKER`, not `UNKNOWN`); a file declared under both `bootstrap_files` and `package_markers` raises `CONFLICTING_PACKAGE_DECLARATION` at project-load time. A redundantly-declared file (under `package_markers` and also matching the auto-detector's structural rule) is idempotent — no diagnostic, the user is allowed to be explicit.
- **`UNKNOWN`** — no checksum comments, no declaration in either list, and the auto-detector's structural rule did not classify the file as a package marker. The default text output surfaces every `UNKNOWN` row at every verbosity level. The remediation names the declarative fix (`[tool.s0ma].bootstrap_files`) and the transpile alternative; a file whose right fix is `[tool.s0ma].package_markers` is covered by the declaration precedence above rather than by the text of this remediation.
- **`CONVERTED`** — a `.s0ma` source under the target whose built module is recorded in the project's build manifest. It is the one status that describes a file that is not Python: a module that has been converted no longer has a `.py` in its source root, and without this row a source root whose modules had all been converted read as `HOLLOW_MODEL` with zero modeled modules while `s0ma score` and `s0ma adopt status` counted them. The row names where the module was built. It counts as **modeled**. It is emitted only when the built `.py` is not itself under the target, so `s0ma verify --all .` on a tree that holds both the source and the build directory counts one module once. The source is never read and nothing is imported.
- **`EDITED`**, **`STALE`**, **`CONFLICT`** — drift statuses surfaced when a hash-bearing transpiled artifact has been edited, the source has been updated without re-transpilation, or both. Always loud; exit code 1.

**Text rendering: one line per file (B4, beta-prep-5).** The text output prints one row per file. An explanation that would otherwise be identical on every row of a status is printed once, as a note between the list and the summary, in the order the statuses it explains first appeared. A status is rendered that way when every shown row of it carries the same remediation and either more than one such row exists, or the status is `UNKNOWN` — the one a freshly-adopted codebase meets on nearly every file, whose shape therefore does not change between a one-file project and a fifty-file one. A status whose rows carry genuinely different remediations (`ADOPTED_DRIFT`, which names the file; `PACKAGE_MARKER`, which has two classification reasons) keeps each on its row. Notes are wrapped, with backticked commands and hyphenated words held together across the break. **`--format json` is unaffected: every row carries its own `detail` exactly as before.** The `HOLLOW_MODEL` row, being a single synthetic row rather than a per-file one, keeps its explanation beside it.

**Default summary line.** `Verified N module(s). M bootstrap file(s) recognized. K unknown.` Under `--verbose` (or its synonym `--all`): `Verified N module(s). M bootstrap file(s) recognized. P package marker(s). K unknown.`

**Coverage line (0.10.0 — pilot-01 memo P1-4).** The text output always follows the summary with `Coverage: N verified s0ma module(s) vs K unregistered plain-Python file(s).` — making the hollow-model case (a green-checking `.s0ma` husk beside a plain-Python implementation) visible at a glance.

**Exit codes (0.14 gate-integrity clarification).** `s0ma verify` exits: **0** — at least one hash-bearing modeled module was verified and all checked content is clean; **1** — drift found (`EDITED` / `STALE` / `CONFLICT` / `ADOPTED_DRIFT`; always wins); **2** — usage error (missing target, no `.py` files); **4** — `EXIT_NOTHING_VERIFIED` with `HOLLOW_MODEL`: zero modeled modules. An adopted-only tree now exits 4 because roster adoption verifies bytes but carries no canonical semantic model. Text always prints `Coverage: N modeled s0ma module(s), A roster-adopted file(s), U unknown plain-Python file(s).`; JSON appends a structured `HOLLOW_MODEL` row when the modeled count is zero.

**Intent-first adoption (0.14 M4).** `s0ma adopt file` is migration intake for pre-existing code, not a creation path for newly-written code. `--description` is a required non-empty one-line intent and persists with the content hash in `adopted.s0ma.json`; a legacy entry without it is refused with a named repair rather than silently assigned intent. The JSON result uses `s0ma-tool-result@1`, carries `status: "interim"`, current componentized/roster counts, and an `author_module` next action because roster entries cannot answer semantic queries. The sidecar also records advisory `re_adopt_count` per path. Three re-adopts after initial intake emit `ADOPTED_CHURN`; the history counter is mutable telemetry and never gate input. Drift remediation orders componentization before hash refresh.

The local check baseline stores an additive immutable Python-path first-contact anchor. A path first seen after that anchor and currently roster-adopted emits `NEW_FILE_ROSTER_ONLY` (authoring warning) plus a reproducible pinned-mode gate-relevant count. Project-local `adoption_exempt = [{path_glob, category, reason}]` entries (`vendored`, `generated`, `data`, or `bootstrap`) classify and enumerate only. A gate waiver requires an explicit `s0ma score --adoption-policy <path>` `s0ma-adoption-policy@1` document; `--expected-adoption-policy-hash sha256:<hex>` pins its canonical sorted JSON hash. Every match is enumerated. The loader refuses catch-all/root-wide or wildcard-root patterns, including a wildcard immediately beneath any configured source root, test root, or build directory even when a pure-legacy project has no modeled source yet. It also refuses root escapes, missing reasons, unknown categories, and any pattern matching canonical `.s0ma` source or hash-bearing generated output. Scoped patterns such as `src/vendor/acme/**` and `vendor/acme/**` are valid.

The runtime bridge (`s0ma_dsl.runtime_bridge.registration.import_modules_from_manifest`, `s0ma.bootstrap.bootstrap_imports`) does not register bootstrap files as components: every entry in `build.s0ma.json` is the product of a `.s0ma` source being transpiled, so bootstrap files are by construction outside the manifest and never imported through the bridge. The bootstrap-file declaration is the consumer-facing answer to "which `.py` files are intentional plain-Python exceptions"; the framework's `.s0ma.cache/` mechanism is unrelated.

**Synthetic fallback (legacy mode).** When no `[tool.s0ma]` table is reachable, `S0maProject.synthetic_fallback(start)` produces a project with the standard defaults rooted at `start`. The `synthetic` flag on the resulting `S0maProject` is `True`; tools may use this flag to short-circuit features that depend on declared project metadata. Synthetic projects are a transitional accommodation — every consumer project should add `[tool.s0ma]` before relying on `s0ma test`, `s0ma build` cross-project resolution, or any future project-aware tooling.

**Why pyproject.toml, not a separate `s0ma.toml`?** A project's build configuration already lives in `pyproject.toml` for hatch / setuptools / poetry. Asking authors to maintain a parallel `s0ma.toml` would split a single coherent fact (project layout) across two files. PEP 518 explicitly carves out the `[tool.<name>]` namespace for exactly this purpose.

**Why a declarative project model rather than per-command flags?** Per-command flags require every consumer to memorise (and every CLI invocation to re-derive) the same facts: where the `src/` is, where the build goes, which `.py` files are exceptions. A declarative model collapses that knowledge to a single source of truth and makes the project itself a queryable artifact, in keeping with the spec's "registration is creation" principle.

**See also:** ADR-005 (project discovery), `docs/migration_guide.md` ("0.11.0 → 0.12.0: Adding `[tool.s0ma]`"), `docs/coding_agent_handbook.md` (handler architecture).

### 4.14 Build Output

> **Status:** Complete (M6a — layout; M6b — manifest, runtime-bridge integration, `s0ma migrate-layout`). See `docs/adr/ADR-007-single-build-layout.md` for the rationale.

A successful `s0ma build` invocation produces a **single flat layout** rooted at the resolved project's `build_dir` (per §4.13). The build directory's contents are exactly:

```
<build_dir>/
    __init__.py            # auto-emitted; marks the directory as a Python package
    build.s0ma.json        # build manifest (M6b)
    build.s0ma.pyi         # companion typed stub (M-8, 0.15.x — POST-14)
    <module_a>.py          # transpiled Python; one per .s0ma module
    <module_a>.s0ma.json   # IR document
    <module_a>.s0ma.map    # source map
    <module_b>.py
    <module_b>.s0ma.json
    <module_b>.s0ma.map
    …
```

Filenames are derived from the canonical module identity (the declared `module <name>`, per §4.10 and ADR-006). The flat layout is uniform across all modules — there are no layer-prefixed subdirectories.

**Auto-emitted `__init__.py`.** Every successful build writes a single `<build_dir>/__init__.py` whose body is a one-line module docstring marking the file as generated by `s0ma build`. The presence of this file is what makes the directory a real Python package: `sys.path.insert(0, <build_dir>); import <module>` works without any further surgery. The file is idempotent — repeated builds with matching content do not rewrite it.

**Import contract.** Every successful build prints exactly one stdout line specifying the import idiom:

```
Build complete. Import via: from <build_dir_basename> import <module>
```

The `<build_dir_basename>` is the leaf name of `<build_dir>` (typically `<project_name>_build`). Consumer code, test harnesses, and runtime bridges should rely on this idiom.

**Hidden incremental cache.** Hash-based incremental-rebuild bookkeeping is stored under `<anchor>/.s0ma.cache/`, where `<anchor>` is the build's input or output directory. The cache directory:

- begins with a leading dot, so Python's importer never picks it up;
- is *not* a Python package — there is deliberately no `__init__.py`;
- is implementation detail and may be deleted at any time without affecting build correctness;
- never appears under `<build_dir>` (the importable surface and the cache surface are kept disjoint).

The `--clean` flag wipes the cache (and any stray legacy `__s0ma_cache__/` directories — see "Removed in 0.12.0" below) before building.

**Removed in 0.12.0.**

- The legacy `__s0ma_cache__/` directory is no longer emitted by `s0ma build` or `s0ma transpile`. It was the source of the stale-cache failure mode flagged across feedback-5 MS 3–5 and every milestone of feedback-5.5 (MS00–M14). Consumer projects with leftover `__s0ma_cache__/` directories are migrated by `s0ma migrate-layout` (lands in M6b).
- Per-layer subdirectories (`presentation/`, `application/`, `domain/`, `infrastructure/`) are no longer emitted under the build directory. The flat layout uses module identity — not architectural layer — as the on-disk organising principle, matching the canonical module identity established in ADR-006.
- `s0ma transpile dir/ -o out/` no longer mirrors `dir/`'s subdirectory structure into `out/`. Every transpiled module lands at `out/<module>.py`.

**Build manifest (`build.s0ma.json`).** Every successful build emits a single `build.s0ma.json` at the build root. The manifest is the canonical "what's in this build" answer — the runtime bridge reads it to discover what to import, downstream tooling consumes it instead of walking the filesystem, and `s0ma verify` / `s0ma migrate-layout` consult it for hashes and module identity. Filesystem traversal as a fallback is deliberately not supported: a missing or schema-mismatched manifest raises `ManifestSchemaError` with a remediation pointing at `s0ma build` or `s0ma migrate-layout`.

The manifest's JSON schema:

```json
{
  "schema": "s0ma-build-manifest@1",
  "project": "<project name from [project].name>",
  "build_dir": "<project-root-relative POSIX path of the build directory>",
  "transpiler_version": "<value of s0ma_dsl.__version__>",
  "modules": [
    {
      "name": "<canonical module identity, per §4.10 / ADR-006>",
      "source": "<project-root-relative POSIX path of the .s0ma source>",
      "output": "<basename of the .py, e.g. scheduler_service.py>",
      "ir": "<basename of the .s0ma.json>",
      "source_map": "<basename of the .s0ma.map>",
      "source_hash": "sha256:<hex>",
      "output_hash": "sha256:<hex>"
    }
  ],
  "topological_import_order": [
    "<module>",
    "..."
  ]
}
```

Field meanings:

- **`schema`** — fixed canonical string `"s0ma-build-manifest@1"`. Readers MUST validate this and reject unknown values (see *Schema versioning* below).
- **`project`** — the `[project].name` from `pyproject.toml`. Synthetic-mode (no `[tool.s0ma]`) projects use the discovery start path's basename as the project name.
- **`build_dir`** — path of the build directory, recorded **relative to the project root in POSIX form** (forward slashes on every OS) when the build ran against a resolved `[tool.s0ma]` project; synthetic-mode builds keep the legacy as-invoked form. The same directory the manifest lives in; recorded explicitly so consumers reading the manifest standalone (e.g., a CI artifact upload) know where it came from. *(SH-M1, INV-5: pre-SH-M1 manifests recorded the absolute machine path — readers must tolerate both forms.)*
- **`transpiler_version`** — the `s0ma_dsl.__version__` value at build time. Lets downstream tooling branch on the transpiler that wrote the manifest.
- **`built_at`** — *(optional; absent since SH-M1)* legacy UTC ISO 8601 timestamp. The build pipeline no longer emits it: wall-clock time in an emitted artifact violates INV-5 and made every rebuild differ byte-wise, which committed-build projects (FR-MCP-11) byte-compare against. Readers MUST tolerate its absence; pre-SH-M1 manifests still carry it and continue to load.
- **`modules`** — list of per-module records, sorted by `name`. The `modules` list is the inventory of what was built; the `topological_import_order` field below is the import-time directive.
- **`modules[].name`** — the canonical module identity (the value of `module <name>` in the source, per §4.10 / ADR-006).
- **`modules[].source`** — path of the `.s0ma` source, recorded **relative to the project root in POSIX form** when the build ran against a resolved `[tool.s0ma]` project (synthetic-mode builds keep the legacy as-invoked form; pre-SH-M1 manifests recorded the as-invoked, possibly absolute, path). Lives outside the build directory; readers resolve relative values against the project root (`s0ma doctor` / `project_status` do). The same recorded form appears as `source_file` in the module's IR (`.s0ma.json`) and source map (`.s0ma.map`) — emitted artifacts carry no absolute machine paths (INV-5), so committed builds are byte-identical across machines, working directories, and operating systems.
- **`modules[].output`** / **`.ir`** / **`.source_map`** — basenames of the three emitted artifacts, relative to `build_dir`. Stored as basenames so the manifest is portable across absolute paths.
- **`modules[].source_hash`** — `sha256:<hex>` of the `.s0ma` source bytes (UTF-8 encoded).
- **`modules[].output_hash`** — `sha256:<hex>` of the emitted `.py` bytes (UTF-8 encoded), computed *after* the M2 `ast.parse()` build invariant runs.
- **`topological_import_order`** — *(M10)* the dependency-first import order computed from every module's `uses:` edges. A module declaring `uses: [B.X]` appears after `B`. Computed via Kahn's algorithm with alphabetical tie-breaking, so the value is reproducible across runs of the same source. The `s0ma.bootstrap.bootstrap_imports(build_dir)` runtime helper consumes this field; consumer projects no longer hand-maintain a `MODULE_IMPORT_ORDER` list. Older manifests that pre-date M10 omit this field; readers default it to the empty list and fall back to alphabetical (the `modules` list's order).

**Schema versioning.** The schema string `s0ma-build-manifest@1` is intentional. Future extensions are *additive* under the same `@1` version: M10 has added `topological_import_order`; M12 has added `external_content_files`. Readers branch on the *presence* of optional fields rather than the version number. A `s0ma-build-manifest@2` is reserved for breaking changes — renamed or removed fields, or any change that would break a `@1` reader. Until that happens, the schema string remains `@1`.

**`external_content_files` (M12).** When a `CONSTANT` cell uses `content: @file("path")` (§4.2.2), the manifest records the embed under `external_content_files`: a map keyed by `"<module>::<cell>"` whose values carry the path the author wrote (relative paths stay relative; absolute paths stay absolute) and the SHA-256 hash of the file's content at build time. Projects with zero embeds omit the field entirely so the manifest stays byte-identical to pre-M12 builds. The hash exists for cache-invalidation: editing an embedded file changes its hash, which propagates through the consuming module's cache key and triggers a re-transpile.

**Cycle detection.** When the topological sort detects a cycle in the project's `uses:` graph, `s0ma build` and `s0ma topo` raise `MODULE_DEPENDENCY_CYCLE` (severity `error` in every strictness mode). The error message names every module that participates in the cycle so the offending chain is locatable. The four-phase resolver's existing `CIRCULAR_DEPENDENCY` (DFS-based, Phase 1 of cross-module resolution) fires first in normal `s0ma build` flow; `MODULE_DEPENDENCY_CYCLE` is the topological-sort-path's defensive backstop and the only signal `s0ma topo` raises when invoked standalone (without a full resolver pass).

**Runtime bridge integration.** Two import paths read the manifest:

- `s0ma.bootstrap.bootstrap_imports(build_dir)` — *(M10, recommended; moved from `s0ma_dsl.runtime` to **s0ma-core** in 0.16.x so a deployed application needs no authoring package at runtime — INV-9. The old import path still works and delegates, with a `DeprecationWarning`.)* the user-facing entry point. Reads `topological_import_order` (or, when absent, the `modules` list's alphabetical order) and imports each module via `importlib.import_module`. Idempotently inserts `build_dir` at the head of `sys.path`. Returns a `dict[str, ModuleType]` keyed by canonical module name.
- `s0ma_dsl.runtime_bridge.registration.import_modules_from_manifest(build_dir)` — *(M6b)* the original manifest reader. Imports modules in the order the `modules` list records (alphabetical, pre-M10). Retained for back-compat with consumers that integrated against M6b before M10 landed.

Filesystem walking is *not* a fallback for either entry point; the manifest is the contract.

**Self-hosting ordering guarantee (0.17.0, F-M4-4).** A package MAY commit its own `s0ma build` output inside itself (`build_dir = "src/<pkg>/_built"`, shipped in the wheel) and bootstrap at import time — the package `__init__.py` calls `bootstrap_imports(Path(__file__).parent / "_built")` and aliases each returned module into its own namespace (`sys.modules["<pkg>.<m>"] = modules["<m>"]`). The runtime identity is always the flat canonical name; a built module is never imported as `<pkg>._built.<m>` at runtime (that re-executes it and doubles its registrations). The guarantee this places on authors: **a package hosting its own build output may be imported back by its built modules only for names defined ABOVE the `bootstrap_imports` call.** A built module declaring `requires: [<pkg>:<name>]` emits `from <pkg> import <name>`, which executes against the still-`partially initialized` `__init__` *while* `bootstrap_imports` is running — so `<name>` resolves iff it was bound before that call. A violation is not silent: it fails at import time with `ImportError: cannot import name ... from partially initialized module`. (`packages/s0ma-mcp` is the shipping worked example; the contributor-facing form is in the quick reference's Bootstrap Pattern section.)

**See also:** ADR-007 (single build layout), `docs/migration_guide.md` ("0.11.0 → 0.12.0: Output layout migration").

#### 4.14.1 Manifest `role` Field + Unified `s0ma test` Manifest (0.14.0)

Each entry in `modules[]` carries an additional `role` field with one of two values:

```json
{
  "name": "scheduler_service",
  "source": "/abs/path/to/scheduler_service.s0ma",
  "output": "scheduler_service.py",
  "ir": "scheduler_service.s0ma.json",
  "source_map": "scheduler_service.s0ma.map",
  "source_hash": "sha256:...",
  "output_hash": "sha256:...",
  "role": "source"
}
```

Allowed values are `"source"` and `"test"` (`VALID_ROLES` in `s0ma_dsl.codegen.build_manifest`). Any other value rejected at `__post_init__` with `ValueError`. Pre-0.14.0 manifests omit the field; `load_manifest()` reads it with a `"source"` back-compat default so every legacy manifest loads unchanged.

**Schema versioning.** The `role` field is additive under the existing `s0ma-build-manifest@1` schema string, following the M10 (`topological_import_order`) / M12 (`external_content_files`) precedent.

**Unified `s0ma test` manifest.** Prior to 0.14.0, running `s0ma test` overwrote `build.s0ma.json` with a manifest containing only test modules — production smoke (e.g. `docker compose up` reading the manifest via `bootstrap_imports`) then failed until `s0ma build .` was re-run. Starting in 0.14.0, `s0ma test` performs two consecutive build passes against the same `build_dir` (source roots first with `role="source"`, then test roots with `role="test"`) and the build pipeline **merges** with any pre-existing manifest: each pass overwrites only its own modules (matched by name), so a single coherent `build.s0ma.json` ends up carrying both roles. `--clean` skips the merge (a clean build always starts from an empty manifest).

**How a build decides the role.** A build records each module with the role of the configured root its `.s0ma` file lives under: `"test"` under a `[tool.s0ma].test_roots` entry, `"source"` under a `source_roots` entry. The answer does not depend on the path the caller named, so a bare `s0ma build`, `s0ma build .`, `s0ma build <project root>` and the MCP `build_project` tool all record a test module as a test, and `bootstrap_imports` with its default roles loads the source modules alone. The roots are disjoint by construction (a project whose roots overlap is refused at load time with `OVERLAPPING_DISCOVERY_ROOTS`), so at most one root encloses any file and the answer is never ambiguous. The test runner's build helper states its role explicitly for each of its two passes, and that statement wins over the root's answer. A module whose file lies under no configured root is still built and recorded with role `"source"`, because nothing declares it a test, and the build reports it with `MODULE_OUTSIDE_PROJECT_ROOTS`, a warning in every strictness mode, so the build gate never counts it. A build that finds no `[tool.s0ma]` table (a synthetic project) has no configured roots to ask: it records `"source"` unless the test runner's helper states a role, and it reports nothing.

The runtime helper `s0ma.bootstrap.bootstrap_imports(build_dir, *, roles=("source",))` filters the topological import order by role. Default behaviour is unchanged from prior releases — production callers see source modules only. Test harnesses pass `roles=("source", "test")` to load both; an empty `roles` tuple returns the empty dict; an unknown role raises `ValueError`.

#### 4.14.2 Orphan Artefact Pruning (0.14.0)

After every successful build (`errors_so_far == 0`), `s0ma build` removes `.py` / `.s0ma.json` / `.s0ma.map` triples whose `<stem>` no longer appears in the manifest. The safety predicate is a triple-check: a `.py` is only pruned when **all three** sibling artefacts exist under `<build_dir>`. Hand-written `.py` files without IR/map siblings are never touched. `__init__.py` is always skipped; the manifest file (`build.s0ma.json`) is never matched by the `*.py` glob. Builds with errors skip the prune so partially-produced work remains recoverable.

A single info-level log line summarises the action: `Pruned <N> orphan artefact(s): <names>`. The prune runs at the end of every `_cmd_build` invocation, so the test-role build pass in §4.14.1 does not prune the prior source-role pass's artefacts — both passes' module names are in the merged manifest by the time the prune runs.

#### 4.14.3 `build.s0ma.pyi` Typed Stub (0.15.x / POST-14)

> **Added in 0.15.x (M-8 / POST-14).** The stub is emitted by every successful `s0ma build`. The runtime helper `s0ma.bootstrap.bootstrap_imports` still returns `dict[str, ModuleType]` — the stub is *advisory* type metadata; pre-M-8 build directories without a stub keep working unchanged.

Every successful build (gated on `errors_so_far == 0`, the same predicate that controls manifest emission) writes a companion Python type stub at `<build_dir>/build.s0ma.pyi`. The stub lives next to `__init__.py` and `build.s0ma.json`; its job is to declare the typed identity of every module the build emitted so consumers of `s0ma.bootstrap.bootstrap_imports` get mypy / pyright coverage on `modules["<name>"]` lookups without falling back to `getattr` + duck-typing on a plain `dict[str, ModuleType]`.

The stub's structure (deterministic, byte-identical across repeat builds of the same project at the same s0ma-dsl version — no timestamps):

```python
# Auto-generated by `s0ma build` — do not edit.
#
# This stub declares the typed identity of every module the build emitted,
# so consumers of `s0ma.bootstrap.bootstrap_imports` can have their type
# checker (mypy / pyright) verify `modules["<name>"]` resolves to the real
# module shape. Point your type-checker at this directory (MYPYPATH or
# equivalent) and use `BootstrapModules` as the return type of your
# bootstrap wrapper.
#
# Produced by s0ma-dsl 0.15.x.

from types import ModuleType
from typing import TypedDict

domain_constants: ModuleType
domain_types: ModuleType
http_gateway: ModuleType
…

class BootstrapModules(TypedDict):
    domain_constants: ModuleType
    domain_types: ModuleType
    http_gateway: ModuleType
    …

modules: BootstrapModules
```

Field meanings:

- **Header comment** — names `s0ma build` as the producer (do-not-edit marker) and pins the s0ma-dsl version that wrote the file. The version string is the only build-specific fact that changes the stub bytes between otherwise-identical builds.
- **Module-level `<name>: ModuleType` declarations** — one line per module the build emitted, sorted alphabetically. With the build directory on `MYPYPATH` (or pyright's `extraPaths`), these let a type checker resolve `modules["http_gateway"].run(...)` against the canonical module shape.
- **`BootstrapModules` TypedDict** — enumerates every module name as a `ModuleType`-typed key. Callers can declare their bootstrap wrapper as `def startup() -> BootstrapModules: …` and the type checker verifies the wrapper's downstream usages against the build's actual contents.
- **`modules: BootstrapModules`** — a bare module-level declaration of the canonical dict shape. Optional from a type-checker standpoint (the TypedDict carries the keys) but useful for human readers grepping the stub for the import-time shape.

**Determinism.** The renderer is a pure function of the manifest plus the transpiler version string — no clocks, no environment, no filesystem reads. Two clean builds of the same project at the same s0ma-dsl version produce byte-identical stub files, matching the manifest's diff-friendly intent (since SH-M1 the manifest itself is also byte-identical across repeat builds — the `built_at` timestamp that used to churn is no longer emitted; the stub never carried one).

**Empty projects.** A project with zero `.s0ma` sources still produces a valid stub: the header, the imports, and a `BootstrapModules` TypedDict with a `pass` body. Consumer code referencing `BootstrapModules` resolves the name even before any sources land.

**Regeneration.** The stub is overwritten on every successful build; there is no incremental-merge step (unlike the manifest itself, which the PRE-3 source+test merge preserves across passes). The PRE-6 orphan-prune does not need to know about the stub: the stub is per-build, not per-module, so it always lands fresh.

**Runtime impact: none.** The stub is purely a type-checker surface. `s0ma.bootstrap.bootstrap_imports` does not read it at runtime; its return type stays `dict[str, ModuleType]` in code, so legacy callers keep working byte-for-byte. The constant `MANIFEST_STUB_FILENAME` in `s0ma_dsl.codegen.build_manifest` names the file for tooling that needs to reference it without importing the emitter module (e.g., `s0ma migrate-layout`, `s0ma verify`).

#### 4.14.4 Historical IR Schema 2.1.0 + the Emitted Metadata Merge (DSL-M1, 0.17.0)

**IR schema 2.1.0 delta (additive).** `SCHEMA_VERSION` bumped 2.0.0 → 2.1.0 once, at DSL-M1, covering the whole 0.17.0 language batch. Absent = not authored; consumers of 2.0.0 documents keep parsing 2.1.0 ones unchanged. The complete delta:

| Surface | New key | Shape | Lands |
|---|---|---|---|
| `components[].fields` | `metadata` | JSON object: identifier keys → string \| int \| float \| bool \| list-of-strings; authored order preserved; omitted when not authored | M1 |
| `components[].fields` | `serves_as` | string (identifier); omitted when absent | M1 |
| `components[].fields` | `covered_by` | non-empty list of strings; omitted when absent | M2 |
| `imports` | `deferred_requires` | list of import entries, same shape as `imports.requires`, each carrying `"deferred": true`; omitted/empty when none | M2 |
| edge / inline-dependency target strings (existing fields) | — | value space widens to include canonical `module::declaration` ids for qualified targets; no schema-field change | M2 |

Entries in `requires`/`soft_requires`/`runtime_only_requires` do NOT gain a `deferred: false` key — omitted-means-false keeps every existing build's IR bytes unchanged. A build that authors none of the new fields differs from its 2.0.0 predecessor by exactly one byte sequence: the `schema_version` value.

**The emitted metadata merge and the reserved-key rule.** The emitter has always written registration metadata (`metadata={"visibility": ..., "evaluates_at": ..., ...}`) for the component shapes it registers. Authored `metadata:` entries (§4.1.11) APPEND to that same dict literal AFTER the emitter-written items, in authored order. Collisions are impossible at emit time because they are rejected at validation: the union of every key the emitter writes — across nerve, ganglion, class-cell, CONSTANT/TYPE-cell, and integration-helper emission — is published as `s0ma_dsl.ir.schema.RESERVED_COMPONENT_METADATA_KEYS` (27 keys at 0.17.0), and `METADATA_RESERVED_KEY` rejects any authored key in that set. The constant is the single source of truth: the validator imports it, and an emitter test asserts every emitter-written key is a member, so the set cannot drift silently.

**The `serves_as` stamp in emitted output.** When a nerve authors `serves_as:`, the emitter (a) writes the reserved `serves_as` key into the registration metadata dict and (b) appends the two-line `__name__`/`__qualname__` stamp one blank line after the decorated def — see §4.10.7 for the full identity semantics and the emitted shape.

**The deferred in-body import shape (DSL-M2).** When a module authors `deferred_requires:` (§4.5.1), those entries emit NOTHING in the module-top import block; instead each consuming def body carries the import statement at its top, after the docstring when present, one contiguous block in entry order (§4.7.4 shows the emitted shape). A module that authors no `deferred_requires:` emits byte-identically to its 0.16.0 predecessor. Qualified `depends_on:` targets (§4.1.2) reach the emitted decorator's `dependencies=[...]` in the canonical `module::declaration` form; bare local targets keep their bare-name strings byte-identically. The `covered_by:` claim (§4.1.13) emits as the reserved `covered_by` metadata key on the registration dict.

#### 4.14.5 Semantic State and Canonical IR 3.0.0 (0.14 M3A)

Every declaration field has exactly one normative class. **SR** (`semantic-required-state`) must be authored as a value, `none`, or `pending("reason")` according to its allowed states. **SC** (`semantic-conditional-state`) is required only when its declaration shape makes the concept applicable. **PO** (`presentation-optional`) stays unwrapped and may be absent. **D** (`derived`) is computed and may not be authored. `V`, `N` and `P` below mean value, none and pending are allowed; each SC field is followed by the states it accepts and, in parentheses, when it applies. Structural identity is `SR / V`: compilation cannot proceed without it. A field is named as it is written in a `.s0ma` file, with the canonical IR's name beside it where the two differ; `body`, `prose_body` and `python_body` are the code or prose after the `---` separator, not lines of their own.

This table is the one statement of which lines each declaration must write; the declaration sections point here rather than repeat it. It is generated from the toolchain's own classification, `s0ma_dsl.semantic_state.FIELD_CLASSIFICATIONS`, by `scripts/generate_spec_field_table.py`, and `packages/s0ma-dsl/tests/test_doc_consistency.py` fails whenever the two differ. Changing a field's class is a change to the language: it is made in that classification, with the owner's approval, and this table is regenerated in the same commit.

<!-- BEGIN GENERATED FIELD TABLE: scripts/generate_spec_field_table.py -->
| Declaration | SR / V | SR / V,P | SR / V,N,P | SC | PO | D |
|---|---|---|---|---|---|---|
| module | `name`, `layer`, `version` | `intent` | `exports`, `requires`, `uses`, `soft_requires`, `runtime_only_requires`, `deferred_requires`, `exports_helpers` | — | `tags` | `location` |
| nerve | `name`, `layer`, `kind`, `visibility`, `evaluates_at` | `intent`, `guarantees` | `expects`, `forbids`, `provides`, `returns`, `raises`, `interface`, `latency_ms`, `depends_on`, `internal` (IR: `internal_helpers`), `expected_exceptions`, `consumes_via_dict`, `declares_attributes`, `covered_by` | `abstract` V (author only when abstract); `deferred` V (author only for a deferred stub); `is_page_composer` V (author only when true); `body` V,P (required unless abstract/interface) | `version`, `tags`, `metadata`, `serves_as` | `provides_entries`, `raw_body`, `location` |
| cell | `name`, `layer`, `kind`, `visibility` | `intent`, `schema` | `invariants`, `covered_by` | `body` V,P (representation required by cell kind); `category` V,P (capability/behaviour kinds); `deferred` V (author only for a deferred stub); `dataclass_invariants` V,N,P (MODEL cells); `placeholders` V,N,P (embedded CONSTANT templates) | `version`, `tags`, `metadata` | `raw_body`, `embedded_file_path`, `embedded_file_resolved`, `embedded_content`, `embedded_file_hash`, `location` |
| ganglion | `name`, `layer`, `visibility`, `scope` | `intent`, `observes`, `on_anomaly` | `forbids`, `priors`, `depends_on`, `covered_by` | `body` V,P (executable evaluator shapes); `deferred` V (author only for a deferred stub) | `tags`, `metadata` | `raw_body`, `location` |
| test | `name`, `layer` | `intent`, `tests`, `body` | `expects`, `depends_on`, `mocks` | — | `tags` | `raw_body`, `location` |
| helper | `name`, `layer` | `intent`, `body` | — | — | `tags` | `body_kind`, `inline`, `raw_body`, `location` |
| integration | `name`, `layer`, `version` | `intent`, `factory`, `smoke_test_primary`, `manifest` | `requires`, `uses`, `raises` | `body` V,N,P (embedded helper code) | `tags` | `raw_body`, `location` |
| standalone axon | `source`, `target`, `relation`, `carries`, `coupling` | `intent` | — | — | — | `location` |
| doc-ref | `name`, `module_location`, `format`, `output` | `intent`, `covers` | — | `sections` V,P (required for the covers: filter form) | `tags` | `covers_source`, `location` |
| doc-guide | `name`, `module_location`, `format`, `output` | `intent`, `covers`, `asserts`, `examples`, `prose_body` | — | — | `tags` | `prose_tokens`, `location` |
| example | `name`, `module_location`, `runs_in` | `intent`, `demonstrates`, `python_body` | — | — | `tags` | `raw_python_body`, `location` |
<!-- END GENERATED FIELD TABLE -->

Nested entries keep their existing required member shapes; the state wrapper applies to the containing field. Existing authored syntax is the value form. A state-aware field additionally accepts whole-value `none` and `pending("non-empty explanation")`. Quoted `"none"` and text containing either word are ordinary authored content, never sentinels. Empty/malformed pending reasons are `SEMANTIC_PENDING_*` errors.

The AST carries `SemanticState(state="value"|"none"|"pending", value=..., reason=...)`. Canonical JSON is `s0ma-ir@3` (`schema_version: "3.0.0"`) and writes the tag at the field's existing key: `{"state":"value","value":...}`, `{"state":"none"}`, or `{"state":"pending","reason":"..."}`. Unknown IR majors are refused as `UNSUPPORTED_IR_SCHEMA_MAJOR` with the exact recovery: run `s0ma migrate grammar`, then `s0ma build`.

A nerve's or a ganglion's `forbids` line is written at `components[].fields.forbids` in the same state object as its siblings; carrying it does not change `schema_version`.

`pending` earns zero completeness credit, warns in migration/dev, errors in strict/release, and always blocks release. `none` earns credit only on a row whose state set includes N. `project_status.semantic_debt` inventories pending count, owners, fields, reasons, source paths, zero credit, and the release block.

`s0ma migrate grammar [PROJECT_DIR]` is dry-run by default and prints a deterministic `s0ma-grammar-migration@1` manifest. `--apply` first parses the entire project with the legacy-omission compatibility reader, verifies every planned input hash, stages same-directory replacements, applies the complete set atomically, and restores already-replaced files on failure. Conflicts refuse the whole plan. A rerun after success is a zero-change no-op. Normal parse, check, transpile, and build paths do not use that compatibility reader: an omitted SR field raises `SEMANTIC_REQUIRED_STATE_OMITTED`; `none` or `pending(...)` outside the field matrix raises `SEMANTIC_NONE_NOT_ALLOWED` or `SEMANTIC_PENDING_NOT_ALLOWED`; and attempting to author a D field raises `SEMANTIC_DERIVED_FIELD_AUTHORED`. Each diagnostic identifies the declaration owner and field and gives migration or source-edit remediation.

### 4.15 Test Execution

> **Status:** Complete (M7 — feedback 5–6, CRIT-3). See `docs/migration_guide.md` "0.11.0 → 0.12.0: Removing per-project pytest workarounds" for the consumer migration path.

`s0ma test` is the project-aware test runner. It is a thin, deterministic wrapper around `pytest` whose every behavioural input is computed from the resolved `S0maProject` (§4.13) — there is no per-project conftest hack required to make cross-module imports resolve, and the runner never writes `.py` files into the source or test trees.

**Contract.** A successful `s0ma test` invocation:

1. **Discovers the project** via `S0maProject.discover` (§4.13). The project supplies `source_roots`, `test_roots`, and `build_dir`.
2. **Builds source + test roots** to `build_dir` using the §4.14 single-flat layout. Source roots are built first (so cross-module `uses:` in tests resolve against their source counterparts); test roots are built next, with the source roots passed as `--include` context. Both passes share the same `build_dir`, so the build dir ends with a single coherent flat layout containing every transpiled `.py`, IR, source map, the auto-emitted `__init__.py`, and the `build.s0ma.json` manifest. `--no-cache` is set for both passes (correctness-first; the test command is not the place to debug stale-cache surprises). When the project declares multiple sibling `source_roots` (e.g. `["domain", "application", "presentation"]`), each per-source-root build pass automatically threads the *other* configured source roots through `--include` so cross-source-root `uses:` references resolve as context modules. Per-root iteration is preserved (it is the canonical surface for build-error attribution: a parse / validation failure still names the offending file's actual source-root path); only the resolution context expands. Single-source-root projects produce an empty sibling list and behaviour is identical to pre-G4. Each invocation is one-shot, so circular sibling-include patterns (A↔B, A→B→C→A) cannot induce a cycle — the build does not recursively descend into `--include` paths. (G4 — feedback 5–6 cleanup; closes M20 finding #6.)
3. **Invokes pytest** as a subprocess with:
   - `PYTHONPATH = <build_dir>` prepended to any pre-existing value, so cross-module imports inside test bodies (`from <other_module> import <component>`) resolve via the flat-layout package.
   - `-o python_files=test_*.py *_tests.py` — extends pytest's default `python_files` glob (which is `test_*.py`) so files emitted under the `*_tests.py` naming convention are also collected. Pre-M7 behaviour silently missed every such file (feedback-5.5 M01).
   - `--ignore=<abs_path>` for every plausible cache directory: `<build_dir>/.s0ma.cache/`, `<build_dir>/__s0ma_cache__/`, `<project.root>/.s0ma.cache/`, `<project.root>/__s0ma_cache__/`, plus `__s0ma_cache__/` under each configured `source_root` and `test_root`. The hidden `.s0ma.cache/` directory holds transpiled `.py` artefacts whose names match the `python_files` glob; without this exclusion they would be double-collected and produce `RegistrationError: Component 'X' is already registered`. The legacy `__s0ma_cache__/` exclusions cover mid-migration consumers that have not yet run `s0ma migrate-layout`. The flag values are absolute paths (no globs, no relative paths) and pytest accepts non-existent `--ignore` paths harmlessly, so the exclusion is unconditional. F2 (feedback 5–6 follow-up) added this behaviour after fr3d's M20 smoke test surfaced the regression.
   - The pytest target is `<build_dir>` (the build dir contains both source and test modules; pytest collects only files matching `python_files`).

**Argument pass-through.** Every argument after a literal `--` on the command line is forwarded to pytest unmodified. The split happens before argparse runs, so `s0ma test`'s own parser cannot consume flags like `-o`, `-k`, or `--maxfail`. Examples:

```bash
s0ma test                            # build + run all tests
s0ma test -- -k specific_test        # narrow collection
s0ma test -- -v --maxfail 1          # verbose, stop on first failure
s0ma test -- -o python_files='*.py'  # override the glob (rarely needed)
```

A pre-M7 `s0ma test ... -- -o python_files='...'` invocation greedy-consumed `-o` as `s0ma test`'s `--output-dir` short flag and produced a directory literally named `python_files=...`. M7 fixes this; the `-o`-after-`--` form now reaches pytest verbatim.

**Preflight.** The runner refuses to start (exit code 2) and prints a remediation when:

- `pytest` is not importable in the active environment — message: "Install pytest in the active environment: `pip install pytest`."
- The project has no `test_roots` configured — message: "No tests configured — add `test_roots = ['tests']` under `[tool.s0ma]` in pyproject.toml."

The runner emits a friendly notice (exit 0) when `test_roots` is configured but no test root exists on disk yet — a fresh project may legitimately have configured the path before scaffolding.

**Source-tree pollution prohibited.** The build dir is the only output. `s0ma test` no longer accepts `--output-dir <test_dir>`-style flags that would write `.py` files alongside `.s0ma` sources. Any consumer relying on the legacy behaviour migrates by removing the flag and reading the test output from `build_dir`.

**Test runner abstraction.** M15 introduces the `[tool.s0ma].test_runner` key (default `"pytest"`); the runner identity is now a project-level declaration consumed by both `s0ma test` and the transpiler. Today only `"pytest"` is supported — an unsupported value rejected at project-discovery time. The key powers the runner-discovery semantics described in §4.13: a test module whose body has no `pytest.<symbol>` reference does not list `pytest` in `requires:`. See `docs/migration_guide.md` "0.11.0 → 0.12.0: Removing per-project pytest workarounds" §4 for the consumer-side cleanup.

**Generated conftest banner + staleness detection (G5).** `s0ma test-conftest` emits a four-line banner at the top of every generated `conftest.py`:

```python
# Generated by s0ma-dsl 0.16.0
# Content checksum: <sha256 of body below>
# Do not hand-edit unless you know what you're doing.
# Run `s0ma test-conftest --force` to regenerate after upgrading s0ma-dsl.
```

The first line carries the s0ma-dsl version that produced the file; the second line carries the SHA256 hex digest of the body **below** the banner (the banner itself is excluded from the checksum input, so re-running `s0ma test-conftest` against the same s0ma-dsl version produces a banner whose checksum line agrees with the body byte-for-byte). The banner is the staleness contract: `s0ma test`'s pre-flight check reads it before invoking pytest and classifies the conftest into one of five states:

- `absent` — file does not exist; `s0ma test` proceeds without one (the M11+ runner does not require a conftest).
- `current` — banner version matches `s0ma_dsl.__version__`; proceed.
- `untouched_stale` — banner version mismatched but the body checksum matches the canonical checksum that older version would have produced; auto-regenerate non-destructively with a one-line stderr notice. Only fires for entries explicitly registered in `STALE_GENERATED_CONFTEST_VERSION_CHECKSUMS`; the initial G5 registry is empty, so this branch never fires today.
- `customized_stale` — banner version mismatched and the body checksum does not match the registered checksum (or no checksum is registered for the banner's version); refuse to proceed and surface `STALE_GENERATED_CONFTEST`.
- `unrecognized` — file exists but has no parseable banner (pre-G5 generated conftest, or a hand-rolled file). Treated identically to `customized_stale`.

The `customized_stale` and `unrecognized` paths fire `STALE_GENERATED_CONFTEST` (error in every strictness mode) with a remediation pointing at `s0ma test-conftest --force`. The pre-flight check is the structural fix for M20 finding #7: kn0wthyself-website-2 carried a months-old generated conftest that patched `s0ma.runtime_bridge.registration.register_module`; the runtime bridge moved in 0.12 and pytest aborted at import time with an opaque `AttributeError`. The fail-safe choice (treat unknown bodies as customized rather than rewriting them) is deliberate — silent rewrites of files that may carry hidden user customizations are a worse failure mode than a loud one-time error that asks the user to inspect, preserve, and run `--force`.

`s0ma test-conftest` itself defaults to refusing to overwrite an existing file; `--force` is the documented escape hatch for the "I have customizations and want a clean regeneration after preserving them" flow.

**See also:** `docs/migration_guide.md` "0.11.0 → 0.12.0: Removing per-project pytest workarounds", `docs/coding_agent_handbook.md` "s0ma test runner internals".

#### 4.15.1 Raw Python Test Discovery (0.14.0)

`s0ma test` discovers and adds raw `.py` test files under `[tool.s0ma].test_roots` to the pytest invocation when **no same-stem `.s0ma` sibling exists in the same directory**. The rule closes the long-standing gap where integration tests that shell out to `docker compose`, lint linters that walk file trees, or any other test logic that does not fit a `.s0ma` body required a separate `pytest` invocation.

**Discovery rules.**

- The file's basename must match pytest's collection patterns: `test_*.py`, `*_test.py`, or `*_tests.py`. Files outside that shape are skipped.
- `conftest.py` and `__init__.py` are always skipped (they are pytest infrastructure, not test cases).
- `.s0ma.cache` and `__s0ma_cache__` subtrees are excluded (those caches hold transpiled artefacts that the §4.15 double-collection guard already excludes via `--ignore`).
- A `.py` file that has a same-stem `.s0ma` sibling in the same directory is **not** discovered — the `.s0ma` is the source of truth and the build emits the canonical `.py` into `build_dir`. The "no `.s0ma` sibling" rule plus the flat-layout invariant guarantees the discovered raw files and the build-dir collection set are structurally disjoint.

**pytest invocation.** Discovered raw paths are appended to `pytest_args` after the `build_dir` target, sorted lexicographically. pytest's own deduplication handles any pathological overlap.

**When to use this.** Raw `.py` test files are the right call when the test logic genuinely does not fit a `.s0ma` body — typically because it shells out to a subprocess (`docker compose`, `gh`, `curl`), walks the filesystem, or operates on cross-language assets. For ordinary unit and integration tests that exercise registered components, prefer authored `.s0ma` tests; they participate in the dependency-resolution and visibility-matrix flow that the rest of the project uses.

### 4.16 Validation Command (`s0ma check`)

> **Status:** Argument shape updated in 0.16.0 (POST-7 / M-11) — `nargs="*"` plus subdir-aware project-context resolution. Pre-0.16.0 invocations (`s0ma check <single-path>`) continue to work unchanged.

`s0ma check` validates `.s0ma` sources without emitting any build artefacts. It runs the parser, the per-module semantic pass, cross-module resolution, doc-subsystem validation, and release-mode coverage checks against whatever inputs the invocation names. The exit code aggregates across every input: any `error`-severity finding produces `EXIT_VALIDATION_ERROR` (1); a clean run with zero `error` rows produces `EXIT_SUCCESS` (0).

**Argument shape.** The positional `source` is `nargs="*"` — zero or more file or directory paths. The shapes the command accepts:

| Invocation | Behaviour |
|---|---|
| `s0ma check` | No positional args — discovery walks every configured `source_roots` + `test_roots` entry from the resolved :class:`S0maProject` (§4.13). Diagnostics from every root are aggregated into one output. An empty configured set (or a set whose entries do not yet exist on disk) yields a friendly one-line no-op message on stderr and exit code 0. |
| `s0ma check <path>` | One path — a single `.s0ma` file, or a directory the command recursively walks for `*.s0ma`. The legacy single-argument form (pre-0.16.0) is unchanged in behaviour. |
| `s0ma check <path-a> <path-b> ...` | Two or more paths — each is processed in sequence; diagnostics are aggregated. Overlapping inputs (a directory and a file inside it; two directories that resolve to the same path) are deduplicated by resolved path so each `.s0ma` module is parsed exactly once and `MODULE_NAME_COLLISION` does not fire against a module colliding with itself. |
| `s0ma check <subdir-of-project>` | The input path lives inside a project but below the project root. The command walks upward from the input for a `pyproject.toml` carrying `[tool.s0ma]` and uses the resulting `S0maProject` as the invocation's project context — `attribute_budgets`, `test_layering`, and every other `[tool.s0ma]` key applies. The pre-0.16.0 behaviour (treat the subdir as the project boundary and fall back to a synthetic project) was the surprise this fix retires. |
| `s0ma check --project-root <dir> <paths>` | An explicit `--project-root` always wins over the input-path walk-up. The override is the escape hatch for the rare case where the invocation deliberately wants to bind the inputs to a different project context (e.g., when checking a shared `.s0ma` snippet against multiple consumer projects). |

**Argument-shape rationale.** Pre-0.16.0 the command accepted exactly one positional, so authors looking to validate both source and test trees had to chain two invocations (`s0ma check src/ && s0ma check tests/`), often forgetting the `&&` and missing failures in the second tree. The one-command shape (`s0ma check src/ tests/`) closes that footgun; the no-args shape (`s0ma check`) makes the configured roots the canonical "check everything" idiom. Subdir-aware project resolution closes a related class of surprise: a path like `s0ma check src/some_module/` would previously treat `src/some_module/` as the project root, miss the `[tool.s0ma]` table at the actual project root, and silently fall back to synthetic mode with the resulting attribute-budget and test-layering checks disabled.

**Diagnostics output.** `--format text` (default) prints one diagnostic per line followed by a single summary footer (`N file(s) checked. No errors.` for the happy path; the per-diagnostic block for the failure path). `--format json` emits exactly one JSON document with an `errors: [...]` array spanning every input path; multi-path inputs never produce two concatenated JSON documents (a downstream pitfall the aggregation step explicitly avoids).

**Forward-compat grammar pass (POST-8, 0.16.0).** When the resolved project's `[project].requires-python` range admits Python 3.11 (see §4.13 "`requires-python` forward-compat pass"), `s0ma check` runs an additional intra-module pass over every authored body (nerve / cell / ganglion / test). The pass flags three 3.12-only construct families — PEP 701 nested-quote f-strings, walrus-in-comprehension, and PEP 695 type-parameter / type-alias syntax — and fires `PARSE_GRAMMAR_FORWARD_INCOMPAT` (error in every mode) on each occurrence. The pass is gated on `requires-python` so projects opted in to `>=3.12` see no extra diagnostics; projects with no declared floor also stay silent under the conservative default. `s0ma build` runs the same pass before the codegen step so a project that goes straight to `s0ma build` (skipping `s0ma check`) still catches the gap before un-importable code reaches a wheel.

**New diagnostic codes in 0.17.0 (DSL-M1).** The 0.17.0 language batch registers five new always-error codes, all in `SEVERITY_MATRIX` / `ERROR_CODE_DESCRIPTIONS` and the generated common-errors table: `METADATA_INVALID_KEY`, `METADATA_INVALID_VALUE`, and `METADATA_RESERVED_KEY` guard the authored `metadata:` shape in the per-module semantic pass (§4.1.11); `SERVES_AS_INVALID` (semantic pass) and `SERVES_AS_COLLISION` (semantic pass per module, cross-module resolution per project build) guard the served-name contract (§4.1.12, §4.10.7).

**New diagnostic codes in 0.17.0 (DSL-M2).** Three more always-error codes: `DUPLICATE_REQUIRES_ENTRY` and `DEFERRED_IMPORT_MODULE_SCOPE` guard the `deferred_requires:` contracts (§4.5.1, §4.7.4 — resolver-emitted; the CLI runs resolution even for single-module invocations that author the field, so every mode can fire them), and `COVERED_BY_EMPTY` guards the `covered_by:` shape (§4.1.13, semantic pass). Qualified `depends_on:` targets reuse the existing `DOES_NOT_EXIST` / `NOT_EXPORTED` / `CIRCULAR_DEPENDENCY` / `CROSS_LAYER_DEPENDENCY` codes with qualified-form messages (§4.6).

**Fixture-format validation (POST-12g, 0.16.0).** When the resolved project's `[tool.s0ma].fixtures_format` table is non-empty, `s0ma check` walks every configured `test_roots` directory looking for non-`.s0ma` files that match a declared glob and validates each via the format-specific parser (see §4.13 "Fixture-format validation" for the format table). Failures fire `FIXTURE_FORMAT_INVALID` (warning in dev/migration, error in strict/release) with the offending path, the format the project asserted, the parser error message, and the offending line number. Files outside every configured glob are ignored. Projects with no `fixtures_format` table (the default) skip the entire pass. The validator runs after the standard `.s0ma` validation so fixture diagnostics surface alongside parser / semantic / cross-module / doc / coverage findings in one aggregated diagnostic block.

**See also:** §4.13 "Project Configuration" (the source of `source_roots` / `test_roots`, `requires-python`, and `fixtures_format`), §4.15 "Test Execution" (`s0ma test` invokes the same project discovery walk-up), `docs/s0ma-dsl_quick_reference.md` "CLI Commands" table.

### 4.17 Build / Test CLI Flags (POST-11, 0.16.0)

> **Status:** POST-11a (`--force-output-dir`), POST-11b (`s0ma test --quiet`), and POST-11c (`s0ma build` exit codes) shipped together in 0.16.0 (M-16). All three are pin-the-contract changes — the underlying behaviour was either already in place or one targeted addition to an existing surface.

#### 4.17.1 `s0ma build --output-dir` vs `[tool.s0ma].build_dir` (POST-11a)

> **Status:** Implemented in 0.16.0. New pre-flight refusal + escape-hatch flag.

When the user passes `--output-dir <path>` to `s0ma build` against a project with a configured `[tool.s0ma].build_dir`, the two paths may agree or disagree. Pre-0.16.0 the override was applied silently — the build landed at the supplied path while the project model's `build_dir` stayed unbuilt, scattering build artefacts across two locations and producing a subtle drift between `[tool.s0ma].build_dir`-based consumers (`bootstrap_imports`, `s0ma test`'s default path) and the actual build output.

POST-11a makes the project model the canonical source of truth. When an explicit `--output-dir` resolves to a different absolute path than `s0ma_project.build_dir`, the CLI refuses at pre-flight time with `BUILD_DIR_OVERRIDE_CONFLICT` and a remediation naming both paths plus the `--force-output-dir` escape hatch. The refusal exits `EXIT_USAGE_ERROR` (2). Pre-flight semantics mean the refusal fires before any `.s0ma` parsing happens — no partial build artefacts are produced.

**`--force-output-dir`.** The escape hatch for the legitimate ad-hoc-override case (e.g. a CI script that wants to inspect a build in a tmpdir without touching the steady-state path). When set, the override applies; the build lands at the supplied path; a one-line stderr notice still announces the override so the override remains visible in logs and CI output.

| Invocation | Behaviour |
|---|---|
| `s0ma build` (no flag) | Build at `[tool.s0ma].build_dir`. No diagnostic. The common case. |
| `s0ma build --output-dir <path>` (with `<path>` ≠ `build_dir`) | `BUILD_DIR_OVERRIDE_CONFLICT` pre-flight refusal. Exit `EXIT_USAGE_ERROR`. |
| `s0ma build --output-dir <build_dir>` (paths resolve to the same absolute path) | Silent. The flag is redundant but harmless. |
| `s0ma build --output-dir <path> --force-output-dir` | Override applies. One-line stderr notice. Exit code follows the build's diagnostic outcome. |
| `s0ma build --output-dir <path>` against a synthetic-fallback project (no `[tool.s0ma]`) | Override applies. No diagnostic. (Synthetic projects have no canonical `build_dir` to disagree with.) |

The `s0ma test` runner's internal build helper (`_run_build_for_test`) is exempt from this check by structural identity — it always sets `output_dir == s0ma_project.build_dir` and carries a hidden `_role` namespace attribute that the pre-flight uses to skip the check. The exemption is invariant by construction, not a flag; users running `s0ma test` never see `BUILD_DIR_OVERRIDE_CONFLICT` from the internal build pass.

The new code is registered in `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE` (configuration-shaped: the strictness ladder has no legitimate severity-by-mode reading because the conflict fires before any `.s0ma` parsing happens).

#### 4.17.2 `s0ma test --quiet` (POST-11b)

> **Status:** Behaviour tightened in 0.16.0. `--quiet` now suppresses every driver-side print path on stdout — only pytest's own stream reaches stdout.

`s0ma test --quiet` suppresses every driver-side stdout print path so the only thing on stdout is pytest's own output. Pre-0.16.0 some print paths reached stdout even with `--quiet` set — most notably the build helper's one-line `Built N module(s). 0 errors, W warning(s).` summary (twice, once per build pass — source roots and test roots), and the friendly `s0ma test: no .s0ma test files found …` notice.

Post-POST-11b:

- The `--quiet` build summary is fully suppressed inside the test-runner's internal build pass (signalled by the hidden `_role` namespace attribute the runner sets on its argparse Namespace). The user-facing `s0ma build --quiet` still emits its `Built N module(s). …` one-liner — only the test-runner-invoked path is silenced.
- The `Running: <pytest-cmd>` driver line is gated on `not args.quiet` (was already gated pre-0.16.0; pinned here as a regression target).
- The `s0ma test: no .s0ma test files found …` notice is gated on `not args.quiet`.
- Stderr is unaffected. Pre-flight refusal messages, the conftest staleness diagnostic, and the synthetic-project warning still reach stderr under `--quiet` — the contract is "only pytest's stream to stdout", not "absolute silence on every channel".

| Invocation | Stdout content |
|---|---|
| `s0ma test` | Driver banner (`Running: pytest …`) + per-build summary lines + pytest's own output. |
| `s0ma test --quiet` | Pytest's own output only. (Driver-side prints suppressed.) |

#### 4.17.3 `s0ma build` exit-code semantics (POST-11c)

> **Status:** Verified + regression-pinned in 0.16.0. No behavioural change — POST-11c is a contract pin.

`s0ma build`'s exit code follows a three-tier ladder:

| Outcome | Exit code | When |
|---|---|---|
| Clean | `EXIT_SUCCESS` (0) | Zero `error`-severity diagnostics. May still carry `warning`-severity diagnostics. |
| Validation error | `EXIT_VALIDATION_ERROR` (1) | At least one `error`-severity diagnostic. May be a parse / semantic / resolution / doc-render error, or a warning escalated to `error` by `--mode strict` / `--mode release`. |
| Usage error | `EXIT_USAGE_ERROR` (2) | Pre-flight refusal: missing project, conflicting `--output-dir` without `--force-output-dir`, etc. No `.s0ma` parsing was attempted. |

**Warnings never block the build absent `--mode strict` (or higher).** The strictness ladder is the only knob that flips warning-only findings to blockers; no other CLI input does. A project that builds cleanly under `--mode dev` can be re-run under `--mode strict` to surface every previously-suppressed warning as a hard error.

The contract is exercised by `tests/test_cli_minor_improvements.py::TestPOST11cBuildExitCodeSemantics` (four tests: clean build → 0; dev-mode warning → 0; strict-mode same-warning → non-zero; hard error → non-zero).

### 4.18 Explicit Host Verification (`s0ma verify-host`, 0.14 M2)

`check`, `score`, and ordinary `verify` are static/read-only and never import
application code. Host execution belongs only to `verify-host` (CLI) and
`verify_host` (MCP), whose annotations are `readOnlyHint=false`,
`destructiveHint=true`, `idempotentHint=false`, and `openWorldHint=true`.
Those hints are a trust-boundary statement: imported project code may perform
filesystem, process, or network actions, and s0ma does not sandbox it.

Interpreter resolution is strict: explicit `--python` wins, followed by
project-relative `[tool.s0ma].venv_path`, followed by platform-aware `.venv`
discovery (`.venv/bin/python` or `.venv/Scripts/python.exe`), followed by
refusal. There is no fallback to the interpreter running s0ma. The report's
fingerprint records the selected launcher's absolute path without following its
final venv symlink (following it would discard venv site-packages), plus Python
version, implementation, platform, and installed s0ma distribution versions.

The versioned `s0ma-host-verification@1` report has required keys `schema`,
`ok`, `gate_mode`, `interpreter`, `modules`, `dependencies`, `diagnostics`,
`duration_ms`, and `gate`. It imports every manifest `source`-role module in a
separate isolated subprocess, in deterministic dependency-first manifest order,
using explicit project/build paths and a controlled UTF-8 environment. Each
record carries outcome, duration, owner when known, and bounded stdout/stderr
tails. Per-module and whole-run timeouts apply; one failure does not prevent
later module probes.

Dependency evidence is gathered through that same interpreter. PEP 621
declarations, installed distributions, and imports statically observed in built
Python are compared with diagnostics `DECLARED_DEP_NOT_INSTALLED`,
`HOST_RUNTIME_UNDECLARED`, and `HOST_IMPORT_FAILED`. `transpile` and `build`
also emit the static `HOST_RUNTIME_UNDECLARED` warning when the host omits the
always-emitted `s0ma-core`/`s0ma-dsl` runtime dependencies; that warning is not
installation evidence.

Without `--gate-mode`, host verification is report-only and `gate.passes` is
null. MCP release acceptance is explicitly ordered: caller-pinned static
`check(gate_mode=release)` followed by
`verify_host(gate_mode=release, python=<app-venv>)`. The CLI equivalent is
`s0ma check --mode release`, `s0ma score --gate-mode release --gate`, then
`s0ma verify-host --gate-mode release --python <app-venv>`. Static or host
evidence alone is insufficient.

---

## 5. The Visibility System

| Visibility | Who Can Call It | Who Can Observe/Test It | Description Required? |
|-----------|----------------|------------------------|----------------------|
| `PUBLIC` | Any module (via exports) | Any module (via registry) | Full declaration |
| `INTERNAL` | Same module only | Any module (via registry) | Full declaration |
| `TEST` | Same module + test modules in any project module (via `uses:`) | Any module (via registry) | Full declaration |

The `exports` list governs the cross-module *production* boundary. The evaluator network and test system are not bound by it. `TEST`-visibility components extend the boundary one step further: they are reachable from any module that contains at least one `test` declaration, but never from production modules in another project module.

**Export/visibility consistency invariant:** A component listed in `exports` must declare `visibility: PUBLIC`. A component not listed in `exports` must declare `visibility: INTERNAL` or `visibility: TEST`. Any mismatch is a transpile-time error in all strictness modes. This ensures that the declaration header and the module header agree on the component's cross-module accessibility. `TEST` components are explicitly *not* in the public export surface — they appear neither in `exports:` nor in the emitted Python `__all__`.

**Cross-module access-control matrix.** See §4.10.1 for the full matrix. The load-bearing rule for `TEST`: a production module (zero `test` declarations) that adds a `TEST`-visibility component to its `uses:` produces `TEST_VISIBILITY_VIOLATION` — error in every strictness mode. The check is local (source module declares ≥1 test? yes/no) and does not perform transitive analysis. See ADR-008.

> **▲** INTERNAL does not mean hidden. An internal component is fully visible to the registry, evaluators, and AI agents. Visibility constrains calling, not observability or testability. The same applies to `TEST`: a TEST component is fully observable in the registry; the visibility level just opens cross-module *call* access to test consumers without making the component part of the public production surface.

> **▲** When to choose `TEST` vs `INTERNAL` vs `PUBLIC`. Use `INTERNAL` for helpers that are private implementation detail and tested only via the public surface. Use `TEST` for helpers that production callers do not need but tests need to exercise directly (e.g. an HTML escaper, a prompt formatter, a serialisation primitive). Use `PUBLIC` for components in the module's external API surface. Promoting a true implementation detail to `PUBLIC` purely so tests can reach it is the workaround `TEST` exists to retire.

---

## 6. Evaluator Architecture

| Scope | Biological Analogue | What It Evaluates |
|-------|--------------------|--------------------|
| `FUNCTION_BOUNDARY` | Spinal reflex | Single nerve: latency, contracts, errors. |
| `SUBSYSTEM` | Ganglion cluster | Patterns in a module. Drift, bias, correlated failures. |
| `SYSTEM` | Cerebellum / prefrontal | Cross-subsystem synthesis. Belief updating, self-model revision. |

### 6.1 Evaluator Priors

- **Structural** — from contracts on observed nerves. Available from day one.
- **Statistical** — from signal history. Strengthen with experience.
- **Injected** — human-specified baselines.

---

## 7. Coding Agent Rulebook

**These rules are absolute. Violating any produces invalid s0ma DSL.**

### 7.1 Universal Rules

| Rule | Requirement |
|------|------------|
| **R-01** | Every file must begin with a `module` declaration. |
| **R-02** | Every component must have an `intent` field. |
| **R-03** | No code outside a declaration block. Everything is a `nerve`, `cell`, `ganglion`, `axon`, `test`, or `module`. |
| **R-04** | `INTERNAL` visibility does not reduce description requirements. |
| **R-05** | All authored dependencies must be declared via `depends_on` or standalone `axon`, each with a `relation` field. |
| **R-06** | Every nerve must declare `evaluates_at`. |
| **R-07** | Do not fragment logic to avoid description. |
| **R-08** | When modifying a component, update its declaration fields. |
| **R-09** | No placeholder intents. Every intent must be complete and accurate. |
| **R-10** | Ganglion `priors` must be populated from observed nerve contracts. |
| **R-11** | No bare imports. Dependencies go in module header via `requires` or `uses`. |
| **R-12** | Every cross-module s0ma reference in `uses`, every external in `requires`. `uses` covers all s0ma references: called, raised, constructed, read, configured, or type-annotated. |
| **R-13** | No unused dependencies. Vestigial detection uses relation-specific evidence rules (Section 4.6.3). |
| **R-14** | Intra-module authored dependencies use inline `depends_on`. Cross-module use standalone `axon`. |
| **R-15** | Cross-module authored dependencies must use standalone axon blocks. |
| **R-16** | Cells with validation logic must declare `invariants` (strict mode: enforced). |
| **R-17** | Nerves that raise exceptions must declare them in `raises`. Each type must be a declared cell in the component-reference namespace. |
| **R-18** | Every test must include a `tests` field linking to validated components. |
| **R-19** | Follow semantic versioning. `version` is authored, not auto-generated. |
| **R-20** | Declaration granularity is top-level only. |
| **R-21** | No `exec()`, `eval()`, `__import__()`, `importlib.import_module()`, or monkey-patching. |
| **R-22** | Never author `RAISES` or `TYPE_USES` axons. These are derived. No exceptions. |
| **R-23** | All components in a module must share the module's layer. |
| **R-24** | Nerve bodies must be function definitions (`def`), except SERVICE and ADAPTER nerves which may also use class bodies (`class`). |
| **R-25** | Namespace collisions in the code or component-reference namespaces are transpile-time errors. No silent shadowing. |
| **R-26** | DSL metadata fields (`depends_on`, `raises`, axon targets) resolve against the component-reference namespace, which excludes `requires` names. You cannot reference a Python builtin or third-party name in a DSL field. |
| **R-27** | A component in `exports` must declare `visibility: PUBLIC`. A component not in `exports` must declare `visibility: INTERNAL` or `visibility: TEST`. Mismatches are transpile-time errors in all strictness modes. (TEST is the v0.12.0 addition; see §5 and ADR-008.) |
| **R-28** | No raw code blocks in `doc-guide` prose bodies. Every code block must be an `{{example::X}}` embed referencing a registered `example` declaration. |
| **R-29** | Every factual claim about a named component, cell, module, or edge in a `doc-guide` body must be either a `{{kind::name[.field]}}` reference or captured in `asserts:`. Unwrapped identifier-shaped backtick spans warn (`POSSIBLE_UNRESOLVED_REFERENCE`) and error in `release`. |
| **R-30** | Every `example` declaration must list at least one entity in `demonstrates:`. The list is non-empty by grammar — an example with nothing to demonstrate should not exist. |
| **R-31** | `doc-ref` declarations may not contain prose beyond `intent` and section `title` fields. Prose belongs in `doc-guide`; reference material is rendered, not narrated. |
| **R-32** | When modifying a component, update affected docs and examples in the same change. Affected docs are those returned by `get_docs_for_component(name)`; affected examples are those returned by `get_examples_for_component(name)`. The drift check (§4.12.5) catches forgotten updates at CI; rule R-32 closes the loop at authoring time. |

### 7.2 Decision Tree

```
File-level container?                          → module
Test?                                          → test
Logic serves the system?                       → nerve (FUNCTION, SERVICE, ORCHESTRATOR, ADAPTER)
Evaluator?                                     → ganglion
Data/constant/config/enum/exception/type?      → cell
Explicit dependency?                           → standalone axon
Reference material rendered from registry?     → doc-ref
Narrative documentation with named claims?     → doc-guide (+ embedded examples)
Executable demonstration of components?        → example
Unsure? Data's invariants → cell. System behaviour → nerve.
```

### 7.3 What the AI Must Never Do

- Never write bare Python outside a declaration block.
- Never omit `intent`.
- Never leave authored dependencies undeclared.
- Never generate a nerve without `evaluates_at`.
- Never write a ganglion with empty `priors`.
- Never update code without updating declarations.
- Never use `exec`, `eval`, dynamic imports, or monkey-patching.
- Never author a `RAISES` or `TYPE_USES` axon.
- Never mix layers within a module.
- Never use a class body in a FUNCTION or ORCHESTRATOR nerve (class bodies are allowed for SERVICE and ADAPTER nerves only).
- Never reference a `requires` name in a DSL metadata field.
- Never write a raw fenced code block in a `doc-guide` body — embed an `{{example::X}}` instead.
- Never name a component in `doc-guide` prose without wrapping it in `{{kind::name}}` or capturing the claim in `asserts:`.
- Never declare an `example` with an empty `demonstrates:` list.
- Never modify a registered component without checking which docs and examples reference it (`get_docs_for_component`, `get_examples_for_component`) and updating them in the same change.

---

## 8. Example: Complete Module

Complete, valid, self-consistent. Demonstrates authored relationships (`CALLS`, `READS`), derived relationships (`RAISES`, `TYPE_USES`), the four-namespace model, cross-module standalone axons, the two-level visibility model, and the 0.17.0 batch fields: `metadata:`, `serves_as:`, `covered_by:`, `deferred_requires:`, and a qualified `depends_on:` target. Every guarantee matches the code body.

```s0ma
module signal_processor
    layer: APPLICATION
    version: 1.0.0
    intent: "Receives raw nerve signals, validates them, and routes them
        to the appropriate subsystem evaluator."
    requires: [uuid.UUID, dataclasses.dataclass, time]
    deferred_requires: [json]
    uses: [routing.select_evaluator, errors.SignalValidationError]
    exports: [process_signal, SignalEnvelope]

cell SignalEnvelope :: APPLICATION
    kind: MODEL
    visibility: PUBLIC
    intent: "Wraps a raw nerve signal with metadata for evaluation
        routing: source, timestamp, trace ID."
    schema: "Immutable dataclass. source: str, timestamp: float,
        trace_id: UUID, payload: dict. All fields required."
    ---
    @dataclass(frozen=True)
    class SignalEnvelope:
        source: str
        timestamp: float
        trace_id: UUID
        payload: dict

cell MAX_STALENESS_SECONDS :: APPLICATION
    kind: CONSTANT
    visibility: INTERNAL
    intent: "Maximum age in seconds for a signal envelope before it
        is rejected by validation as stale."
    schema: "int constant. Value: 300 (5 minutes)."
    ---
    MAX_STALENESS_SECONDS: int = 300

nerve validate_envelope :: APPLICATION
    kind: FUNCTION
    visibility: INTERNAL
    intent: "Confirms that a SignalEnvelope contains all required
        fields and that timestamp is within staleness bounds."
    expects: "envelope is not None; all required fields present"
    guarantees: "Returns True if valid"
    forbids: none
    raises: [SignalValidationError]
    latency_ms: 5
    evaluates_at: FUNCTION_BOUNDARY
    depends_on:
        MAX_STALENESS_SECONDS: {relation: READS, carries: "threshold", coupling: TIGHT}
    ---
    def validate_envelope(envelope: SignalEnvelope) -> bool:
        if not envelope.source or not envelope.trace_id:
            raise SignalValidationError("Missing required fields")
        if time.time() - envelope.timestamp > MAX_STALENESS_SECONDS:
            raise SignalValidationError("Envelope is stale")
        return True

nerve process_signal :: APPLICATION
    kind: ORCHESTRATOR
    visibility: PUBLIC
    intent: "Primary entry point for signal processing. Validates
        the incoming envelope, then routes it to the correct
        subsystem evaluator based on source layer."
    expects: "envelope is a valid SignalEnvelope"
    guarantees: "Signal reaches exactly one subsystem evaluator"
    forbids: none
    raises: [SignalValidationError]
    latency_ms: 50
    evaluates_at: SUBSYSTEM
    serves_as: process
    covered_by: ["tests/test_signal_pipeline.py — end-to-end routing suite"]
    metadata:
        team: "signals"
        max_fanout: 1
    depends_on:
        validate_envelope: {relation: CALLS, carries: "SignalEnvelope", coupling: TIGHT}
        routing.select_evaluator: {relation: CALLS, carries: "source layer string", coupling: LOOSE}
    ---
    def process_signal(envelope: SignalEnvelope) -> bool:
        validate_envelope(envelope)
        audit = json.dumps({"trace": str(envelope.trace_id)})
        evaluator = select_evaluator(envelope.source)
        return evaluator.receive(envelope, audit)

# Cross-module authored dependency (R-15)
axon process_signal -> select_evaluator
    relation: CALLS
    intent: "process_signal delegates evaluator selection to the routing
        module. Loose coupling: routing strategy can change without
        modifying signal processing logic."
    carries: "source layer string"
    coupling: LOOSE
```

> **NOTE:** Derived by transpiler (no axon needed):
> 1. `RAISES` edges from `raises` fields: `signal_processor::validate_envelope → errors::SignalValidationError`, `signal_processor::process_signal → errors::SignalValidationError`.
> 2. `TYPE_USES` from signatures: both nerves reference `SignalEnvelope` as parameter/return type.
>
> Only `CALLS` and `READS` are authored. `SignalValidationError` resolves in the component-reference namespace (imported via `uses`). `time`, `uuid.UUID`, `dataclasses.dataclass` resolve in the code namespace only (from `requires`). `validate_envelope` and `MAX_STALENESS_SECONDS` are `INTERNAL` but fully visible to registry for observation and testing.
>
> **0.17.0 batch fields in this example:** `deferred_requires: [json]` emits no module-top import — `import json` lands inside `process_signal`'s body (its only consumer), so a broken `json` environment would fail per call, not at import (§4.5.1/§4.7.4). The qualified `depends_on:` target `routing.select_evaluator` resolves against the project module set and reaches the emitted `dependencies=[...]` as `routing::select_evaluator`, while the bare `validate_envelope` stays a bare name (§4.1.2). `serves_as: process` stamps the emitted callable's `__name__`/`__qualname__` (§4.10) and `covered_by:` satisfies the release gate without an in-language test (§4.1.13/§4.8); `metadata:` appends after the emitter-written registration keys (§4.1.11).

---

## 9. Open Questions & Next Decisions

- Evaluator signal format: Signal object structure? Correlation IDs, payload redaction, retention, sampling, backpressure?
- Prior specification language: Prose + LLM interpretation, or hybrid with structured subfields?
- Ganglion activation model: Push, pull, or event-driven with thresholds?
- Transpiler error message format: Structured for AI. Fields and remediation detail?
- Migration tooling: Path from s0ma Python to `.s0ma` files?
- Source map format: `.s0ma` → `.py` line mapping conventions?
- IR schema: Exact JSON schema for `.s0ma.json`?
- Mutation-oriented relations: `WRITES`, `MUTATES`, `CATCHES` in v1?
- Incremental recompilation: Invalidation strategy for project-wide resolution?

---

## Appendix A — Field Reference

Which lines each declaration must write, and which of them may be `none` or `pending("reason")`, is the table in §4.14.5. That table is generated from the toolchain's own field classification and checked against it, so this appendix points there rather than keeping a second copy.

`depends_on` targets accept the bare local form and, since 0.17.0 (DSL-M2), the qualified in-project form `module.declaration` — exactly one dot; see §4.1.2.

---

## Appendix B — v2 Considerations

Items explicitly deferred from v1.

### Language & Syntax

- `PRIVATE` visibility (block-local scope). Requires nested component syntax.
- Mixed-layer modules.
- Nested component declarations.
- Conditional imports. (Deferred imports shipped in 0.17.0 as `deferred_requires:` — §4.5.1.)

### Type System & Contracts

- Structured contract subfields: thresholds, predicates, expected exception sets, time windows, I/O schemas.
- Runtime contract enforcement (warn vs. error).
- Refinement types or value constraints in a mini-language.

### Dependency Graph & Edge Taxonomy

- Mutation-oriented relations: `WRITES`, `MUTATES`, `CATCHES`.
- Derived `CALLS` from static call graph analysis.
- Weighted edges for prioritised impact analysis.
- Enriched `TYPE_USES` metadata via a separate annotation mechanism (not axons).
- Broader `TYPE_USES` extraction surface. V1 derives `TYPE_USES` from nerve/ganglion function signatures and constructor calls to known cells. V2 could extend to cell field annotations, base class references, Protocol implementations, and type alias bodies.
- Dynamic dispatch modelling. V1 models the decision point; v2 could model the fan-out.
- Selective cycle relaxation. V1 treats all `uses` cycles as fatal. V2 could relax this for type-only or exception-only edges if real-world usage shows the strict rule is too aggressive for complex domain models.

### Identity & Versioning

- Stable UUIDs for rename tracking.
- Cross-project identity (project-scoped prefixes).
- Deprecation markers with transpiler warnings and migration timelines.

### Evaluator System

- Ganglion activation model.
- Signal schema standardisation.
- Evaluator chaining.
- Belief persistence across restarts.

### Tooling & Infrastructure

- Incremental recompilation with dependency-aware caching.
- IDE integration.
- Migration tooling (`s0ma transpile --from-python`).
- IR schema formalisation (versioned JSON Schema).
- Debug tooling (source map integration).
- Golden test CI (spec examples transpile and execute under CI).

### Runtime Evolution

- Registry API expansion.
- Dynamic self-model queries via MCP tool-use interface.
- Hot reload with self-model consistency checks.

### Documentation & Ecosystem

- Sync upstream documents to v1 terminology.
- Academic paper alignment.
- Open source preparation.
