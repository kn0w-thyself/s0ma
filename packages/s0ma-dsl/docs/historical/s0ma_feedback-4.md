# s0ma Framework Feedback

Logged during ax0n development as issues, observations, or suggestions arise.

Please annotate the current milestone, a number/title, issue, resolution, and suggestion about how to improve s0ma (if appropriate). Please refer to the SAMPLE FEEDBACK below.

---
## SAMPLE FEEDBACK

### 2026-02-15 — Milestone 1 (Project Scaffolding)

#### 1. Package name mismatch in documentation

**Issue:** The PRD (Section 4.2) documents the s0ma dependency as `"s0ma"` in `pyproject.toml`, but the actual published package name is `s0ma-framework`. This caused the initial `pip install -e ".[dev]"` to fail with `ERROR: No matching distribution found for s0ma`.

**Resolution:** Changed the dependency to `"s0ma-framework"` in st3mcell's `pyproject.toml`.

**Suggestion:** The s0ma user guide (Section 1.1) correctly shows `pip install s0ma-framework`, but downstream documentation (like the PRD) should consistently use the pip package name `s0ma-framework` rather than the import name `s0ma`. Alternatively, consider adding a note in the user guide about this distinction.

---

## Milestone 1 — Repository Scaffolding & Toolchain Setup — 2026-03-08

### What Worked Well

- `@component` decorator applied cleanly to frozen dataclasses (`S0maError`, etc.) and enums (`StrictnessMode`). Registration was seamless.
- `idempotent=True` on all transpiler components prevented `RegistrationError` during repeated test imports — good design for library code that gets imported in multiple test modules.
- The decorator's zero-overhead, no-wrapping design means frozen dataclasses remain truly frozen after decoration. No surprises.
- `from s0ma.decorators import component, internal` and `from s0ma.types import ComponentKind, Layer` — the import API is clean and discoverable.

### Pain Points

1. **`Layer.FRAMEWORK` not documented in user guide.** The user guide §2.2 lists only `DOMAIN`, `APPLICATION`, `INFRASTRUCTURE`, `PRESENTATION` as `Layer` enum values. However, s0ma's own framework components use `Layer.FRAMEWORK`, and the DSL transpiler PRD (CC-1) instructs us to use `Layer.FRAMEWORK` for transpiler components. The value exists in the code but isn't in the user-facing docs. An agent following only the user guide would not know `FRAMEWORK` is available.

2. **No guidance on `@component` with enum classes.** The user guide covers classes and functions but doesn't mention applying `@component` to `Enum` subclasses. It works fine, but an agent might hesitate. A brief note would help.

3. **Component name uniqueness with sister projects.** The user guide warns about collisions with framework-reserved names and suggests project prefixes (e.g., `MyApp_QueryEngine`). For sister projects like s0ma-dsl, ax0n, st3mcell, we adopted `S0maDSL_` as a prefix. Documenting this convention for the kn0wthyself ecosystem would be helpful.

### Suggestions

- Add `Layer.FRAMEWORK` to the user guide's `Layer` enum documentation (§2.2), with a note that it's intended for framework-level tooling and infrastructure projects.
- Add a brief example of `@component` on an `Enum` class in the user guide.
- Consider a "sister project conventions" section in the user guide for projects in the kn0wthyself ecosystem (prefixing strategy, editable install pattern, lenient mode usage).

### Questions / Open Issues

- **Lenient mode activation:** The transpiler PRD says "the import hook runs in lenient mode during development," but we haven't activated the import hook at all for `s0ma_dsl` yet (no `s0ma.initialize(project_root=...)` call). This works because we only use `@component` decorators directly — we never import modules under hook enforcement. Should we add an explicit `s0ma.initialize(strict=False)` somewhere, or is the current approach (decorators-only, no hook) the intended pattern for library/tool projects?

---

## Milestone 2 — Architecture Decisions & Spec Traceability — 2026-03-08

### What Worked Well

- The s0ma decorator model is well-suited to the separate-project architecture. The transpiler can use `@component` from `s0ma.decorators` as a pure client — no special bootstrapping, no circular dependencies. ADR-004 confirms this pattern works cleanly.
- The four-namespace model (spec §4.10.1) is architecturally sound and maps well to implementation modules. The separation of concerns (code vs. component-ref vs. registry vs. public API) is clear enough to plan enforcement locations in the traceability matrix without ambiguity.
- The additive runtime expansion strategy (ADR-002) means existing s0ma code is unaffected. This is a significant advantage for ecosystem adoption — sister projects don't need to coordinate releases.

### Pain Points

1. **Runtime expansion scope unclear from user guide alone.** The user guide documents the current `@component` → registry path well, but doesn't hint at the registration functions the DSL will need (`register_module()`, `register_constant()`, `register_type()`, `register_relationship()`, `register_test()`). While these are new additions, having a "framework extension points" section in the user guide would help agents working on runtime expansion milestones (M14-M15) understand what's available vs. what needs to be built.

2. **No documentation on registry schema internals.** The traceability matrix needs to map to concrete registry storage (tables for modules, edges, tests). The user guide documents the query API well (`registry.get()`, `registry.get_dependencies()`, etc.) but doesn't describe the internal schema. For the runtime expansion ADR, we had to infer storage needs from the query API surface. A brief "registry internals" appendix (even just table names and primary keys) would help agents planning schema expansion.

### Suggestions

- Add a "Framework Extension Points" section to the user guide documenting how sister projects can extend registration capabilities (new `register_*` functions, schema additions).
- Consider documenting the registry's internal schema (even briefly) for agents who need to extend it.

### Questions / Open Issues

- **Mixed `.s0ma`/`.py` registry behavior.** ADR-002 decides that mixed projects are supported, but the exact semantics when both `foo.s0ma` and `foo.py` exist for the same module need to be resolved during M15 (import hook expansion). The ADR records `.s0ma` takes precedence, but edge cases (e.g., `.py` exists without corresponding `.s0ma`, partial conversion) should be explicitly tested.

---

## Milestone 3 — AST Node Definitions & Enums — 2026-03-08

### What Worked Well

- `@component` applied cleanly to all 18 AST node types (7 enums + 11 dataclasses). The decorator continues to work flawlessly with `@dataclass(frozen=True)` — frozen semantics are preserved after decoration, which is exactly what we need for immutable AST nodes.
- `idempotent=True` remains essential. With 18 components registered across `enums.py` and `nodes.py`, and tests importing from both the submodules and the `__init__.py` re-exports, the same decorator fires multiple times in a test session. Without idempotent mode, this would cause `RegistrationError` on every test run.
- The `@unique` decorator on enums combined with `@component` works without issues — no decorator ordering conflicts.
- Registering frozen dataclass enum types (like `Layer`, `Kind`) as `ComponentKind.MODEL` feels appropriate and consistent with the s0ma ontology.

### Pain Points

1. **Pytest `TestDecl` collection warning.** Naming our AST node `TestDecl` causes a `PytestCollectionWarning` because pytest's default collection convention treats any class starting with `Test` as a test class. The `@dataclass` `__init__` prevents actual collection, so the warning is harmless, but it adds noise. This is a Python ecosystem friction, not a s0ma issue, but worth noting: s0ma projects that model "test" as a first-class concept will encounter this naming tension with pytest.

2. **No `ComponentKind` value maps directly to "enum" or "type alias".** When registering our DSL's `Kind` enum (which enumerates component kinds like SERVICE, FUNCTION, MODEL, etc.) with s0ma's `@component`, we use `ComponentKind.MODEL` — but the thing being registered is itself an enum, not a data model. This works fine but highlights a minor ontological gap: s0ma's `ComponentKind` enum (SERVICE, FUNCTION, MODEL, ADAPTER, ORCHESTRATOR) doesn't have an ENUM or TYPE_DEFINITION variant. For the transpiler, where we're modelling these concepts explicitly in our DSL's `Kind` enum, the mismatch is noticeable but not blocking.

### Suggestions

- Consider adding a note to the user guide about the pytest `Test*` naming collision when components model testing concepts.
- Consider whether `ComponentKind` should eventually include an `ENUM` or `TYPE` variant for registering enum classes and type aliases, or whether `MODEL` is the intended catch-all for structural artifacts.

### Questions / Open Issues

- None blocking. The AST node types align well with the spec's Appendix A field reference table.

---

## Milestone 4 — Lark Grammar & Outer Structure — 2026-03-08

### What Worked Well

- `@component` applied cleanly to the `S0maParser` class. The decorator works well on service-oriented classes that expose a `parse()` method.
- `idempotent=True` continues to be essential — the parser module gets imported by multiple test files in the same pytest session.
- The `S0maError` → `Exception` upgrade (making `S0maError` extend both `dataclass` and `Exception`) worked seamlessly. The frozen dataclass fields are preserved, and the error can now be raised/caught naturally. This is a good pattern for structured errors that need to be both data objects and exceptions.

### Pain Points

1. **`S0maError` was not raiseable as originally implemented.** The M1 implementation created `S0maError` as a frozen dataclass without `Exception` in the MRO. This meant errors could only be collected into lists, not raised. The parser needs to raise errors to stop processing on fatal syntax issues. M4 upgraded `S0maError` to extend `Exception` — this was a one-line change (`class S0maError(Exception):`) but required re-running existing tests to verify no regressions. Suggestion: the PRD §2.4.1 should note that `S0maError` must be raiseable.

2. **`strict=True` in Lark requires `interegular` package.** The PRD specifies "Lark with LALR(1) and `strict=True`" but `strict=True` requires the `interegular` package for regex conflict detection. This is not listed in the PRD §2.1.4 dependency table. It should be added as a development dependency: `lark[interegular]`.

3. **Golden fixture uses 4-space-indented separators, not column-0.** The DSL spec §4.9 states separators must be at "Column 0 (no leading whitespace)", but the spec's own §8 golden example has `    ---` (4-space indent). The parser was updated to accept indented separators to match the actual golden fixture. The spec should be clarified: is the separator at column 0, or is it at the same indentation level as field lines?

4. **Lark LALR(1) is not well-suited for the full .s0ma file structure.** The indentation-sensitive format with embedded Python bodies doesn't map cleanly to a single LALR(1) grammar. The implementation uses a hybrid approach: line-based declaration splitting for the outer structure, with Lark LALR(1) for structured field values (lists, depends_on entries, import entries with aliases). This satisfies the spirit of the PRD requirement while being practically implementable. A pure Lark grammar would require a custom postlexer/indenter and would struggle with body extraction.

### Suggestions

- Add `interegular` to the dependency list (or change to `lark[interegular]` in pyproject.toml).
- Clarify the separator indentation rule in the spec — the golden example contradicts the specification text.
- Consider documenting the "structured errors that extend Exception" pattern in the user guide, as it's useful for any s0ma project that needs raiseable structured errors.
- The from-import heuristic (`uuid.UUID` → `from uuid import UUID` vs. `os.path` → `import os.path`) based on capitalization of the last path segment is a rough approximation. Consider making the `is_from_import` field explicitly authorable in the DSL syntax for v2.

### Questions / Open Issues

- **Separator indentation:** Should the `---` be at column 0 or at field indentation level (4 spaces)? The golden fixture uses 4-space indent. The parser currently accepts both. This should be resolved in the spec.
- **`requires` from-import detection:** The heuristic of "last segment capitalized = from import" works for `uuid.UUID` but not for `dataclasses.dataclass`. This could be refined with an explicit syntax like `from dataclasses import dataclass` vs. `import time`, but that's a DSL syntax change for v2.

---

## Milestone 5 — Body Extraction & Validation — 2026-03-09

### What Worked Well

- `@component` applied cleanly to the new `BodyType` enum, `BodyInfo` dataclass, and the `extract_body` / `validate_body` functions. The decorator continues to work seamlessly with all Python constructs — enums, frozen dataclasses, and module-level functions alike.
- `idempotent=True` remains essential. The body extractor module is imported by both the parser and the new test file; without idempotent registration, test runs would fail with `RegistrationError`.
- The `ComponentKind.FUNCTION` mapping works well for standalone utility functions (`extract_body`, `validate_body`). It feels natural and appropriate in the s0ma ontology.
- The severity matrix integration (`config.py`'s `StrictnessMode` + `get_severity`) works cleanly for modulating prohibited construct and bare import violations between warnings and errors depending on the active strictness mode.

### Pain Points

1. **`@dataclass(frozen=True)` + `Exception` is fundamentally incompatible in Python 3.11+.** The M4 feedback noted that making `S0maError` extend `Exception` "worked seamlessly" — but this was only true for collecting errors. When M5 actually *raises* `S0maError` instances (as the parser now does for fatal body validation failures), Python's exception machinery tries to set `__traceback__`, `__cause__`, `__context__`, and `__suppress_context__` on the exception object. With `frozen=True`, this raises `FrozenInstanceError`. Worse, Python 3.11 forbids overriding `__setattr__` in frozen dataclasses (`TypeError: Cannot overwrite attribute __setattr__ in class S0maError`), so you can't simply whitelist those attributes.

   **Resolution:** Changed all error dataclasses (`S0maError`, `S0maParseError`, `S0maSemanticError`, `S0maResolutionError`) from `@dataclass(frozen=True)` to `@dataclass(eq=True, unsafe_hash=True)` and implemented manual freezing via a custom `__setattr__`/`__delattr__` pair with a `_sealed` flag set in `__post_init__`. Exception-protocol attributes (`__traceback__`, `__cause__`, `__context__`, `__suppress_context__`, `args`) are whitelisted for mutation.

   **Suggestion:** This is a significant pattern that any s0ma project using structured raiseable errors will encounter. The user guide should document a "Frozen Exception Dataclass" recipe, since the naive `@dataclass(frozen=True) + Exception` combination silently works until you actually raise the exception in a context manager or try/except chain.

2. **`textwrap.dedent` fails on body text containing column-0 comments.** The golden fixture's `process_signal` nerve body includes a trailing comment `# Cross-module authored dependency (R-15)` at column 0 (captured by the parser's body extraction loop). `textwrap.dedent` computes common leading whitespace across ALL non-blank lines, so a single column-0 line (even a comment) makes the common prefix empty, preventing any dedenting. The entire body then fails to parse with `IndentationError`.

   **Resolution:** Replaced `textwrap.dedent` with a custom `_dedent_body` function that determines base indent from the first non-blank, non-comment line and strips that prefix from lines that have it (tolerating lines with less indentation, like column-0 comments).

   **Suggestion:** This is a general issue for any DSL that embeds indentation-sensitive code blocks. Consider documenting the `textwrap.dedent` limitation in the spec's body extraction section, or defining body capture boundaries more precisely so trailing comments at column 0 are excluded.

3. **Pre-existing test assumed all cell kinds accept assignment bodies.** The M4 `test_all_cell_kinds` test used `c = None` as the body for every cell kind, but M5's body validation correctly rejects assignments for kinds that require class definitions (MODEL, ENUM, EXCEPTION, CONFIG). The test needed updating with kind-appropriate bodies.

### Suggestions

- Document the "Frozen Exception Dataclass" pattern in the user guide — `@dataclass(frozen=True)` + `Exception` is a trap that only manifests at raise time, not at construction time.
- Consider whether s0ma should provide a `FrozenError` base class that handles the `__setattr__` whitelisting automatically, so downstream projects don't each need to implement the same boilerplate.
- The body extraction spec (§4.6-4.8) could benefit from explicit examples of edge cases: trailing comments at column 0, empty bodies, bodies with only docstrings.

### Questions / Open Issues

- **Body capture boundary:** The parser captures all indented lines after `---` as body text, but trailing comments at column 0 (within the declaration block) also get captured. Should the spec define a more precise body termination rule (e.g., body ends at the first line with indentation ≤ the field indentation level)?
- **Empty body handling:** The spec doesn't address whether an empty body (just `---` with no code after it) is valid. The current implementation treats it as `BodyType.EMPTY`. Should this be an error for declaration types that require bodies (nerves, ganglia, tests)?

---

## Milestone 6 — Namespace Services — 2026-03-09

### What Worked Well

- `@component` applied cleanly to the `NamespaceEntry` frozen dataclass, the `NamespaceService` mutable dataclass, and the `build_namespaces` module-level function. All three patterns (frozen model, mutable service, standalone function) registered without friction.
- `idempotent=True` continues to be essential — the resolver module is imported by both the test file and will be imported by the future validator and dependency resolver modules.
- `ComponentKind.SERVICE` is a natural fit for `NamespaceService` — it's a stateful service that holds and queries namespace data for a module.
- `ComponentKind.FUNCTION` works well for the `build_namespaces` factory function.
- The decorator's zero-overhead design means the `NamespaceService` dataclass remains fully mutable (no frozen constraint), which is necessary since it accumulates namespace entries during construction.

### Pain Points

1. **`ComponentKind` still lacks a good match for "data container with methods".** `NamespaceService` is registered as `ComponentKind.SERVICE`, but it's really a data-oriented container with lookup methods — not a service in the traditional sense (it doesn't manage lifecycle, handle requests, or orchestrate). There's no `ComponentKind.CONTAINER` or `ComponentKind.REPOSITORY`. `MODEL` feels wrong because it's mutable and has behavior. This is the same ontological gap noted in M3 feedback — the kind taxonomy doesn't perfectly capture "stateful data structure with query methods."

2. **No guidance on `@component` for factory functions that return other components.** `build_namespaces()` is a factory function that creates a `NamespaceService` instance. Both the function and the class it produces are `@component`-decorated. The user guide doesn't address this pattern — should factory functions be registered? The answer is yes (they're meaningful, independently usable units of functionality), but explicit guidance would help agents make this decision faster.

### Suggestions

- Consider adding a `ComponentKind.REPOSITORY` or `ComponentKind.CONTAINER` for stateful data structures that provide query interfaces but don't manage lifecycle. This would better classify namespace services, registry wrappers, and similar "data + lookup" components.
- Add a brief note to the user guide about the factory function pattern: when a function creates and returns a `@component`-decorated object, both the factory and the product should be registered independently.

### Questions / Open Issues

- None blocking. The four-namespace model maps cleanly to the spec §4.10.1 definitions. The registry namespace is correctly left as a stub — it will be populated at project level by the cross-module dependency resolver (M8).

---

## Milestone 7 — Intra-Module Semantic Validation — 2026-03-09

### What Worked Well

- `@component` applied cleanly to the `IntraModuleValidator` dataclass (registered as `ComponentKind.SERVICE`) and the `validate_module` convenience function (registered as `ComponentKind.FUNCTION`). The pattern of SERVICE for stateful orchestrators and FUNCTION for standalone entry points continues to feel natural.
- `idempotent=True` remains essential. The validator module is imported by both the test file and will be imported by future pipeline orchestration modules. Without idempotent registration, test collection would fail.
- The decorator's zero-overhead design means the validator's `@dataclass` fields (`mode`, `filename`) work exactly as expected — no interference from decoration.
- Composing the validator with the `NamespaceService` from M6 was clean. The four-namespace model provides a solid foundation: checking inline axon targets against `is_in_component_ref_namespace()` and detecting requires-name misuse with `is_requires_name()` required zero namespace infrastructure changes.
- The `Relation.is_authored()` / `is_derived()` helper methods (defined in M3's `enums.py`) made the R-22 validation implementation trivially clean — a single method call instead of set membership checks.

### Pain Points

1. **No `ComponentKind` value maps cleanly to "validator" or "checker".** `IntraModuleValidator` is registered as `ComponentKind.SERVICE`, but it doesn't manage lifecycle, handle requests, or persist state between calls — it's a stateless validation pass. The `SERVICE` kind feels slightly overloaded. This is the same ontological gap noted in M6 feedback: the kind taxonomy doesn't perfectly capture "stateless analysis engine" vs. "stateful service that manages lifecycle." Not blocking, but worth tracking as `ComponentKind` adoption grows.

2. **`TestDecl` naming collision with pytest continues.** The `PytestCollectionWarning` for `TestDecl` appears in every test file that imports from `ast_nodes.nodes`. While functionally harmless, it adds visual noise to test output (4 warnings across 4 test files). This is unchanged from M3 feedback — worth noting that the problem scales linearly with the number of test files.

### Suggestions

- Consider adding `ComponentKind.ANALYZER` or `ComponentKind.VALIDATOR` for components that perform stateless analysis passes. This would better classify the semantic validator, the future dependency resolver, and similar "check and report" components.
- Consider adding a `collect_ignore_glob` or pytest configuration to suppress the `TestDecl` collection warning project-wide.

### Questions / Open Issues

- **R-09 (placeholder intents) and R-10 (ganglion priors) are deferred.** R-09 requires semantic quality assessment of intent text — the transpiler can enforce non-empty strings (done by the parser) but cannot judge whether an intent is meaningful. This is fundamentally an agent responsibility. R-10 requires validating that ganglion `priors` relate semantically to observed nerve contracts — this needs the richer priors mini-language planned for v2. Both rules are documented as deferred in the traceability matrix.
- **R-16 (cells with validation logic must declare `invariants`) is deferred.** Detecting whether a cell body contains "validation logic" would require heuristic code analysis that is beyond the scope of v1's static checks. The `invariants` field exists in the AST and will be validated when present, but requiring it based on body content analysis is not implementable without false positives.
- **`DOES_NOT_EXIST` error code is shared between inline axon target validation (M7) and cross-module resolution (M8).** The validator currently emits `DOES_NOT_EXIST` for inline axon targets that don't exist in the component-reference namespace. M8 will also emit `DOES_NOT_EXIST` for `uses` references to unknown components. The error code is the same but the context differs. This is intentional per the PRD §2.4.2 error code registry, but the `context` dict on each error provides disambiguation.

---

## Milestone 8 — Cross-Module Dependency Resolution — 2026-03-09

### What Worked Well

- `@component` applied cleanly to the `DependencyResolver` dataclass (registered as `ComponentKind.SERVICE`) and the `resolve_dependencies` convenience function (registered as `ComponentKind.FUNCTION`). The SERVICE + FUNCTION convenience wrapper pattern established in M7 continues to work well.
- `idempotent=True` remains essential — the resolver module is imported by the test file and re-exports through the `resolver/__init__.py` barrel, triggering multiple decorator evaluations in a test session.
- The four-namespace model from M6 (`build_namespaces`, `NamespaceService`) composed seamlessly into the cross-module resolver. Standalone axon validation uses `lookup_component_ref()` and checks `entry.origin == "local"` to enforce the cross-module-only constraint. Zero changes needed to the namespace infrastructure.
- The `StrictnessMode` + `get_severity()` integration from `config.py` works cleanly for modulating `VESTIGIAL_IMPORT`, `MISSING_PACKAGE`, and `DUPLICATE_AXON` severity between modes. The severity matrix design (M1) pays dividends here — adding new error codes to the matrix is trivial.
- AST-based body analysis (`ast.parse` + `ast.walk`) for evidence rules proved reliable. Extracting identifiers and call targets from Python bodies is straightforward with the standard library `ast` module, and the regex fallback on `SyntaxError` provides graceful degradation.
- The `importlib.util.find_spec()` approach for Phase 3 (external validation) is elegant — it checks package availability without side effects (no `importlib.import_module()` execution). The `check_imports=False` parameter for test environments was a practical necessity.

### Pain Points

1. **Private function duplication across resolver modules.** `_uses_local_name()` and `_requires_local_name()` are defined in both `resolver/namespaces.py` and `resolver/dependency.py` with identical logic. They're private (`_`-prefixed) in `namespaces.py`, so importing them would be fragile. The duplication is intentional to avoid coupling to private APIs, but it means any change to alias resolution logic must be updated in two places. This is a minor DRY violation that could be resolved by promoting these functions to the public API of `namespaces.py`, but the current approach is defensible.

2. **`DOES_NOT_EXIST` code overloaded for two distinct scenarios.** The standalone axon validation reuses `DOES_NOT_EXIST` when a standalone axon targets a local declaration (indicating it should be inline `depends_on` instead). This overlaps with Phase 2's `DOES_NOT_EXIST` for missing modules. The `context` dict disambiguates, but a dedicated error code like `LOCAL_AXON_TARGET` or `INVALID_AXON_SCOPE` would be more precise. The PRD error code registry doesn't define such a code, so we used the closest match.

3. **Evidence rules for derived relations are vacuously true.** The `_has_relation_evidence()` function returns `True` for derived relations (`RAISES`, `TYPE_USES`) since they don't have authored evidence in bodies — the transpiler derives them automatically. This is correct behavior but slightly surprising when reading the code. A comment explains it, but the spec §4.6.3 could be more explicit about which relations have evidence rules and which don't.

### Suggestions

- Consider promoting `_uses_local_name()` and `_requires_local_name()` to the public API of `resolver/namespaces.py` to avoid duplication. They're stable, well-defined utility functions that multiple resolver modules need.
- Consider adding a dedicated error code (e.g., `INVALID_AXON_SCOPE` or `LOCAL_AXON_TARGET`) for standalone axons that target local declarations. This is distinct from a "component doesn't exist" error and would produce clearer diagnostics.
- The spec §4.6.3 (evidence rules) could explicitly state: "Evidence rules apply only to authored relations (CALLS, READS, CONSTRUCTS, CONFIGURES). Derived relations (RAISES, TYPE_USES) are not subject to evidence checking since they are automatically inferred."
- Consider adding `ComponentKind.ANALYZER` for stateless analysis engines like `DependencyResolver` — it doesn't manage lifecycle or persist state between calls, making `SERVICE` a slightly overloaded classification (same feedback as M6/M7).

### Questions / Open Issues

- **Registry namespace population.** The M6 namespace model leaves the registry namespace as a stub ("populated at project level by resolver"). The M8 dependency resolver does NOT currently populate it — it validates cross-module consistency but doesn't merge all module namespaces into a unified registry. Full registry population is deferred to a future milestone (likely M9 or M10) when the IR builder needs global name resolution for derived edge inference and code generation.
- **Glob-pattern observes resolution.** Ganglia use `observes` patterns (e.g., `*_signal`) that resolve against the registry namespace. The M8 resolver does not implement glob-pattern resolution — this is an M12 concern per the implementation plan. The `EMPTY_OBSERVES` error code exists in the severity matrix but is not yet emitted.
- **Self-referencing modules.** A module that uses itself (e.g., `uses: [self.component]`) is correctly detected as a cycle by the DFS algorithm. The spec doesn't explicitly address self-referencing modules, but treating them as cycles is the conservative correct behavior — intra-module dependencies should use inline `depends_on`, not `uses`.

---

## Milestone 9 — Derived Edge Analysis — 2026-03-09

### What Worked Well

- `@component` applied cleanly to the new `DerivedEdge` frozen dataclass (registered as `ComponentKind.MODEL`), the `DerivedEdgeAnalyzer` mutable dataclass (registered as `ComponentKind.SERVICE`), and the `analyze_derived_edges` convenience function (registered as `ComponentKind.FUNCTION`). The M7/M8 pattern of SERVICE + FUNCTION convenience wrapper continues to work well.
- `idempotent=True` remains essential. The `derived_edges.py` module is imported by both the test file and re-exported through the `semantic/__init__.py` barrel.
- The existing infrastructure composed cleanly: `NamespaceService.lookup_component_ref()` provides exactly the right namespace for resolving both `raises` targets (must be s0ma components, not requires names) and TYPE_USES annotation targets (external Python types like `UUID` are correctly excluded). Zero namespace infrastructure changes needed.
- The `Relation.is_authored()` / `is_derived()` helper methods from M3 make the single-source authority enforcement trivially clear in the conflict detection code.
- The `StrictnessMode` + `get_severity()` integration from `config.py` works cleanly for modulating `DUPLICATE_AXON` severity on authored/derived conflicts. The severity matrix design pays dividends again.
- 43 new tests all pass, covering RAISES derivation, TYPE_USES derivation, annotation extraction helpers, conflict detection with strictness mode variations, and golden fixture validation.

### Pain Points

1. **Body text preservation includes leading indentation.** The parser preserves body text with original indentation (e.g., 4-space prefix from .s0ma file nesting). This means `ast.parse(body)` fails with `IndentationError` unless the body is first dedented. Furthermore, `textwrap.dedent` fails when bodies contain column-0 comments (like `# Cross-module authored dependency (R-15)` captured as part of `process_signal`'s body in the golden fixture). This is the same issue documented in M5 feedback. A custom `_dedent_body` function was needed that determines base indent from the first non-blank, non-comment line and strips that prefix, tolerating lines with less indentation. **This is a recurring pattern** — any module that needs to `ast.parse` stored body text will need this same dedent logic.

2. **`ComponentKind.SERVICE` continues to feel overloaded.** `DerivedEdgeAnalyzer` is registered as `ComponentKind.SERVICE` but it's a stateless analysis engine — it doesn't manage lifecycle, handle requests, or persist state. This is the same ontological gap noted in M6, M7, and M8 feedback. The kind taxonomy would benefit from an `ANALYZER` or `VALIDATOR` kind for stateless analysis passes.

### Suggestions

- **Centralize the `_dedent_body` helper.** The same logic exists in `body_extractor.py` (M5), `dependency.py` (M8's `_extract_identifiers` handles it via fallback), and now `derived_edges.py`. This should be promoted to a shared utility (e.g., `s0ma_dsl.utils.dedent_body`) that all body-analyzing modules import. The current duplication means any fix to the dedent algorithm must be applied in multiple places.
- Consider adding `ComponentKind.ANALYZER` for the growing number of stateless analysis components (validator, resolver, derived edge analyzer). Four milestones of feedback have flagged this ontological gap.

### Questions / Open Issues

- **Registry namespace population for TYPE_USES.** The TYPE_USES derivation currently only finds types in the component-reference namespace (local + uses). If a type annotation references a component from a module not listed in `uses`, the TYPE_USES edge won't be derived. This is correct behavior per the spec (you must declare `uses` for cross-module references), but it means TYPE_USES edges are limited to the same scope as authored dependencies. Full project-level TYPE_USES inference would require the registry namespace, which is deferred to M10/M12.
- **`_dedent_body` vs. body extractor dedent.** The body extractor in M5 already has a custom `_dedent_body` function, but it lives in `parser/body_extractor.py` as a private function. Both implementations use the same algorithm (find first code line's indent, strip it). This should be unified in a future milestone.

---

## Milestone 10 — IR Generation (.s0ma.json) — 2026-03-09

### What Worked Well

- `@component` applied cleanly to all 16 new IR schema dataclasses (`IRModule`, `IRComponent`, `IRAuthoredEdge`, `IRDerivedEdge`, `IRVerificationEdge`, `IREdges`, `IRRequiresImport`, `IRUsesImport`, `IRPrivilegedImport`, `IRImports`, `IRComponentLocation`, `IRDocument`) and the `IRBuilder` service class plus `build_ir` convenience function. The frozen dataclass + `@component` pattern established in earlier milestones continues to work flawlessly.
- `idempotent=True` remains essential. The `ir/schema.py` module alone registers 14 components, and `ir/builder.py` adds 2 more. Without idempotent mode, the test suite would fail immediately due to duplicate registration across test module imports.
- The `ComponentKind.MODEL` classification for the IR schema types feels natural — they are pure data containers with `to_dict()` serialization. `ComponentKind.SERVICE` for `IRBuilder` (which orchestrates building from multiple inputs) also fits well.
- The IR-first architecture decision (PRD §2.1.5) pays dividends: having the IR builder consume the semantic model directly means downstream consumers (Python emitter, runtime bridge) can share this same normalized representation rather than each re-deriving semantics independently.
- The `to_dict()` method pattern on every IR type provides a clean, composable serialization path: `IRDocument.to_dict()` recursively calls `to_dict()` on all nested types. JSON output with `sort_keys=True` ensures deterministic key ordering at all levels.
- 74 new tests all pass, covering schema types, content hash generation, IR builder with all declaration types, derived edge integration, verification edges, determinism verification, golden fixture end-to-end, and edge cases (aliases, empty modules).

### Pain Points

1. **Standalone axon target resolution requires uses lookup.** The standalone axon declaration `axon process_signal -> select_evaluator` stores the target as `select_evaluator` (a bare name). The IR builder initially treated this as a local reference (`signal_processor::select_evaluator`), but the correct canonical ID is `routing::select_evaluator` — resolved via the module's `uses` list. This required adding a `_build_uses_lookup` method and a `_resolve_axon_target` method that checks the uses entries before falling back to local resolution. The spec and PRD don't explicitly document this resolution rule for standalone axon targets in the IR, though it follows logically from the namespace model (targets in the component-reference namespace include `uses` entries).

2. **`ComponentKind.SERVICE` continues to feel overloaded for `IRBuilder`.** `IRBuilder` is stateful (carries `source_file`, `source_text`, `transpiled_file`) but doesn't manage lifecycle or handle requests — it's a builder/factory pattern. This is the same ontological gap noted in M6-M9 feedback. Five milestones of feedback have now flagged the lack of a `BUILDER` or `FACTORY` kind.

3. **Privileged imports are stubbed.** The `IRImports.privileged` field is always empty in this milestone because privileged import resolution requires project-level registry access (M12). The IR schema includes the field per PRD §2.5.2, but population is deferred. Tests verify the structure is present but don't test populated values.

### Suggestions

- Document the standalone axon target resolution rule explicitly: "Standalone axon targets that are bare names (not dot-qualified) must be resolved against the module's `uses` list before falling back to local namespace lookup."
- Consider adding `ComponentKind.BUILDER` or `ComponentKind.FACTORY` for components that construct other data structures. Five milestones have flagged this ontological gap — the current workaround of using `SERVICE` for stateless/short-lived builders obscures the component's true archetype.

### Questions / Open Issues

- **Privileged imports deferred to M12.** The `IRImports.privileged` field is structurally present in the schema but always empty. M12 (Ganglion, Test, & Privileged Import Emission) will populate this when project-level registry access is available. This is documented in the builder code.
- **Content hash scope.** The content hash is computed over the raw `.s0ma` source text (not the canonical JSON). This means any whitespace change in the source produces a different hash, even if the semantic content is identical. The PRD §2.5.3 says "computed over a canonical JSON serialization (sorted keys, no extra whitespace)" — but this refers to the IR output determinism, not the content hash input. The current approach (hashing raw source) is more useful for change detection (PRD §2.7.5) since it detects any source modification. This should be clarified in the spec.
- **`_resolve_target_canonical` method is now unused** after the addition of `_resolve_axon_target` for standalone axons. The method remains as it may be useful for future milestones (e.g., verification edge targets that reference cross-module components). It could be removed in a cleanup pass if it stays unused.

---

## Milestone 11 — Python Emitter — Core Declarations — 2026-03-09

### What Worked Well

- `@component` applied cleanly to the `PythonEmitter` dataclass (registered as `ComponentKind.SERVICE`) and the `emit_python` convenience function (registered as `ComponentKind.FUNCTION`). The SERVICE + FUNCTION convenience wrapper pattern established in M7-M10 continues to work well.
- `idempotent=True` remains essential. The codegen module is imported by the test file and re-exported through the `codegen/__init__.py` barrel.
- The existing AST node types and enum definitions from M3 provided exactly the right foundation for the emitter. Every field needed for code generation was already captured in the AST nodes.
- The `S0maModule.all_declarations` property (which returns declarations sorted by source line) made declaration-order emission trivial — a single loop emits components in the correct order.
- The body text stored in AST nodes is faithfully preserved through the emission pipeline. The custom `_dedent_body` function handles indented bodies and column-0 comments correctly.
- 45 tests pass covering unit tests (dedent, stdlib detection, import lines), integration tests (minimal modules, imports, nerves, cells, axons), golden fixture tests, multi-module tests, and determinism verification.

### Pain Points

1. **`@component` parameter set doesn't cover DSL-specific fields.** The PRD §2.2.2 maps DSL fields like `visibility`, `evaluates_at`, and `raises` to `@component` parameters (e.g., `visibility=Visibility.<VIS>`), but the current `@component` decorator doesn't accept these parameters. The emitter stores these in the `metadata` dict as a pragmatic workaround. This means emitted code works with the current s0ma framework, but the DSL-specific fields aren't first-class `@component` parameters. M14 (Runtime Registry Expansion) should either: (a) extend `@component` to accept `visibility`, `evaluates_at`, `raises`, etc., or (b) formally define `metadata` as the standard location for DSL-extended fields.

2. **`ComponentKind` taxonomy doesn't cover all DSL cell kinds.** Cell kinds ENUM, EXCEPTION, and CONFIG all map to `ComponentKind.MODEL` in emitted code because s0ma's `ComponentKind` only has `SERVICE`, `FUNCTION`, `MODEL`, `ADAPTER`, `ORCHESTRATOR`. The emitter stores the original kind in `metadata["kind_detail"]` for precision, but this means the s0ma registry loses kind granularity. This is the same ontological gap noted in M3, M6-M10 feedback — now it directly affects emitted code.

3. **Registration functions don't exist yet.** The emitter generates calls to `register_module()`, `register_constant()`, `register_type()`, and `register_relationship()` from `s0ma_dsl.runtime_bridge.registration`, but this module doesn't exist yet (M14). Emitted Python passes `compile()` (syntax check) but won't be importable until M14 provides the registration functions. This is expected per the milestone ordering but means golden fixture output can't be end-to-end tested until M14.

4. **Parser `is_from_import` heuristic produces invalid imports.** The parser's heuristic for `requires` entries (`is_from_import=True` if last path segment is capitalized) causes `dataclasses.dataclass` to be emitted as `import dataclasses.dataclass` instead of `from dataclasses import dataclass`. The emitter faithfully translates the parser's `RequiresEntry`, so the bug is in the parser's heuristic, not the emitter. This was already noted in M4 feedback but now directly produces incorrect emitted Python.

5. **`ComponentKind.SERVICE` continues to feel overloaded.** `PythonEmitter` is registered as `ComponentKind.SERVICE` but it's a stateless code generator — it doesn't manage lifecycle or persist state. This is the same feedback from M6-M10.

### Suggestions

- Extend `@component` to accept `visibility`, `evaluates_at`, and `raises` parameters natively, or formally document `metadata` as the extensibility mechanism for DSL-specific fields. Either approach is fine, but the current state (PRD specifies native parameters that don't exist) creates confusion.
- Consider extending `ComponentKind` with `ENUM`, `EXCEPTION`, `CONFIG`, `CONSTANT`, `TYPE` to match the DSL's finer-grained kind taxonomy. Alternatively, document `metadata["kind_detail"]` as the standard way to preserve kind granularity.
- Fix the parser's `is_from_import` heuristic for `requires` entries. A simple fix: treat dotted paths where the last segment starts lowercase as from-imports when the module portion is a known stdlib package. Or allow explicit `from X import Y` syntax in `.s0ma` requires lists.

### Questions / Open Issues

- **Ganglion and test emission deferred to M12.** The emitter produces basic stubs for ganglion declarations (plain `@component` without observes resolution or privileged imports) and test declarations (plain pytest functions without `register_test()`). Full emission requires project-level registry access for observes pattern resolution and privileged import handling.
- **Registration function import path.** The emitter imports registration functions from `s0ma_dsl.runtime_bridge.registration`. When M14 implements these, the import path should be confirmed — it may end up in `s0ma.registration` (the framework) rather than the transpiler's runtime bridge, depending on the two-repo design.

---

## Milestone 12 — Ganglion, Test, & Privileged Import Emission — 2026-03-09

### What Worked Well

- `@component` applied cleanly to all 6 new public types in `observes_resolver.py`: `ProjectContext` (MODEL), `ResolvedObserves` (MODEL, frozen), `PrivilegedImportInfo` (MODEL, frozen), `ObservesResolver` (SERVICE), `determine_privileged_imports` (FUNCTION), and `resolve_observes` (FUNCTION). The decorator continues to handle frozen dataclasses, mutable dataclasses, and standalone functions without friction.
- `idempotent=True` remains essential. The `observes_resolver.py` module is imported by both the emitter and the test file, and re-exported through the `codegen/__init__.py` barrel — three decorator evaluation paths in a single test run.
- The `ProjectContext` design (optional parameter on `PythonEmitter`) preserves full backward compatibility with M11's single-module emission while enabling M12's cross-module features. The emitter degrades gracefully: without context, ganglia emit raw `observes` lists; with context, they emit `resolved_observes` canonical IDs. No existing callers break.
- The `StrictnessMode` + `get_severity()` integration from `config.py` works cleanly for `EMPTY_OBSERVES`. The severity matrix already had the rule (defined in M1), and the resolver simply calls `get_severity("EMPTY_OBSERVES", self.mode)` — zero config changes needed.
- The three pattern forms (exact, module glob, layer glob) compose orthogonally. Each has a single static method in `ObservesResolver` and a single test class. The classification function `_classify_pattern` is a clean three-line dispatch.
- The privileged import deduplication in `_resolve_all_tests()` handles the case where the same cross-module INTERNAL component is referenced by multiple tests or by both ganglia and tests — deduplicated by canonical_id before emission.
- 46 new tests (14 test classes) all pass on first run. The test helpers (`_make_module`, `_make_nerve`, `_make_ganglion`, `_make_test`, `_build_project_context`) compose cleanly for building arbitrary multi-module project contexts.
- All 518 existing tests continue to pass with zero regressions, including the codegen and IR tests that depend on modified code.

### Pain Points

1. **`ComponentKind.SERVICE` for `ObservesResolver`.** `ObservesResolver` is a stateless resolver with no lifecycle management — it takes patterns and a context, returns results. This is the same ontological gap flagged in M6-M11: `SERVICE` is overloaded for stateless analysis/resolution components. Six consecutive milestones have now noted this. The framework would benefit from a `ComponentKind.RESOLVER` or `ComponentKind.ANALYZER` kind.

2. **`ProjectContext.all_nerves()` recomputed on every call.** The method iterates all modules and all nerves every time it's called. For `resolve_patterns()` with N patterns, this means N × M nerve iterations (where M is total nerves across modules). For the current scale this is trivial, but a caching layer or pre-built index would be needed for large projects. This is a scalability observation, not a current blocker.

3. **Privileged import population requires threading through three layers.** The `PythonEmitter` resolves privileged imports, but the `IRBuilder` needs them too (to populate `IRImports.privileged`). The current design passes them from emitter output to IR builder via the `privileged_imports` parameter on `build()` / `build_ir()`. This creates an implicit coupling: the IR builder can't determine privileged imports independently; it depends on the emitter having already resolved them. A future refactor could have both the emitter and IR builder share a common `ProjectContext`-aware resolution step.

### Suggestions

- Seriously consider adding `ComponentKind.RESOLVER` or `ComponentKind.ANALYZER` to the kind taxonomy. Six milestones of consistent feedback indicate this is a real gap, not a one-off edge case. Components that resolve patterns, analyze dependencies, or validate constraints are a distinct archetype from lifecycle-managing services.
- Consider making `ProjectContext.all_nerves()` lazily cached (computed once, invalidated if `modules` changes). The `@cached_property` pattern would work if `ProjectContext` were made effectively immutable after construction.
- Consider having the `IRBuilder` accept a `ProjectContext` directly and perform its own privileged import resolution, rather than requiring the emitter to pre-compute and pass them in. This would make the IR builder self-contained for project-level concerns.

### Questions / Open Issues

- **Test `register_test()` call format.** The emitter generates `register_test(name="module::test_name", intent="...", validates=[...])` calls, but the `register_test` function doesn't exist yet (M14). The exact parameter signature should be confirmed when M14 implements the registration API. The current format follows the pattern established in ADR-002 and the PRD §2.3.3.
- **Privileged import comment format.** Privileged imports are emitted with a trailing `# privileged_observation` or `# privileged_verification` comment. This is a convention for human readability. If the s0ma framework eventually enforces privileged import rules at runtime, the comment format may need to become a structured annotation (e.g., a `@privileged_import` decorator or a registration call).
- **`EMPTY_OBSERVES` in strict mode blocks emission.** When `StrictnessMode.STRICT` and an observes pattern resolves to no nerves, the error has severity "error". However, the emitter currently collects but does not halt on errors — it continues emitting. Should the emitter abort on error-severity issues, or is collection-and-report the right behavior? The current approach (collect all, let the caller decide) is more flexible but means the emitter can produce Python code that references zero-match observes patterns.

---

## Milestone 13 — Source Map Generation (.s0ma.map) — 2026-03-09

### What Worked Well

- `@component` applied cleanly to all source map data types (`LineRange`, `DeclarationMapping`, `ModuleHeaderMapping`, `SourceMap`) as frozen dataclasses with `ComponentKind.DATA_OBJECT`. The decorator continues to work seamlessly with `@dataclass(frozen=True)`.
- `@component(kind=ComponentKind.SERVICE)` fit naturally for `SourceMapGenerator` — it is a stateless service that takes inputs and produces a `SourceMap`. This is one of the few milestones where `SERVICE` felt like the right fit rather than a compromise.
- `@component(kind=ComponentKind.FUNCTION)` on `generate_source_map()` as a convenience wrapper worked well. The decorator's `idempotent=True` flag prevented re-registration errors during test collection.
- The `idempotent=True` pattern remains essential — tests import from both the module directly and the `codegen` package `__init__.py`, causing duplicate registration without it. This has been consistent feedback across all 13 milestones.

### Pain Points

- **No pain points specific to the s0ma framework in this milestone.** The decorator application was straightforward and the component taxonomy fit well. The `ComponentKind.SERVICE` vs. `ANALYZER` question from previous milestones did not arise here because `SourceMapGenerator` genuinely is a service (it generates an output artifact from inputs).

### Suggestions

- Consider documenting the `idempotent=True` pattern as the default recommendation in the s0ma user guide. After 13 milestones of consistently needing it for every component in library/framework code, it's clear that `idempotent=False` (the default) is only appropriate for application-level singletons. Library authors will always need `idempotent=True`.
- The `ComponentKind` taxonomy worked well this milestone because the source map module has a clear service/data split. Previous milestones' feedback about needing `ANALYZER`/`RESOLVER` kinds remains valid for the analysis-heavy modules (semantic analyzer, observes resolver, etc.).

### Questions / Open Issues

- **Source map integration with emitter.** Currently `SourceMapGenerator` is a standalone class that takes emitted Python output and the AST, then reconstructs line mappings by pattern-matching the output. An alternative design would have the `PythonEmitter` track line numbers as it emits and produce mappings directly. The current approach is simpler and decoupled, but the pattern-matching is somewhat fragile — if the emitter's output format changes, the source map generator must be updated in lockstep. This is an acceptable trade-off for now, but worth revisiting if the emitter undergoes significant changes.
- **Body source range estimation.** The source map estimates `body_source.start_line` as `decl.location.end_line - body_line_count + 1`, since the AST's `SourceLocation` doesn't store a separate body start line. This is accurate for current `.s0ma` syntax but would break if body formatting changes (e.g., if blank lines within bodies become common). A more robust solution would be to have the parser record the body start line in `SourceLocation` or as a separate AST field.

---

## Milestone 14 — Runtime Registry Expansion — 2026-03-09

### What Worked Well

- **The `ComponentRegistry` was easy to extend.** Adding `_modules`, `_edges`, and `_test_registrations` alongside `_components` followed the existing patterns naturally. The SQLite persistence layer's pattern of `_persist_*` / `_load_all` / `_clear_persistence` was straightforward to replicate for new tables. The design is clean and predictable.
- **Bootstrap self-registration worked as documented.** Adding 3 new model classes (`ModuleMetadata`, `RelationshipEdge`, `TestRegistration`) required adding them to `_bootstrap.py` and bumping `EXPECTED_FRAMEWORK_COMPONENT_COUNT` — the blind-spot verifier immediately caught the omission, exactly as designed. This is the self-model doing its job.
- **`@component(idempotent=True)` on the runtime bridge functions** worked perfectly for the adapter layer. The bridge functions are imported by every transpiled module, so idempotency is essential.
- **The two-repo milestone structure** (s0ma framework changes + s0ma-dsl adapter) was well-scoped. The framework provides the storage and API, the transpiler provides the thin adapter — clean separation of concerns.

### Pain Points

- **Pre-M14 database compatibility.** When loading from a pre-M14 SQLite database that doesn't have the `modules`, `edges`, or `test_registrations` tables, `_load_all()` would crash with `sqlite3.OperationalError`. I had to add `try/except OperationalError: pass` guards around each new table load. This is a one-time migration concern, but it suggests that s0ma should have a schema version mechanism or use `CREATE TABLE IF NOT EXISTS` at load time rather than only at init time. Currently the schema is implicitly versioned by which tables exist.
- **`EXPECTED_FRAMEWORK_COMPONENT_COUNT` as a hardcoded constant** in both `_bootstrap.py` and `test_phase3_capstone.py` requires updating in two places. The capstone test duplicates the assertion (`== 40`) instead of referencing the constant. This is minor but creates a maintenance burden when adding framework models.

### Suggestions

- **Schema versioning for SQLite.** Consider adding a `schema_version` table or PRAGMA to the registry database. When the registry opens an existing database, it can compare the stored version against the expected version and run migrations (e.g., `CREATE TABLE IF NOT EXISTS modules`). This would replace the `try/except OperationalError` pattern with explicit migration logic.
- **Remove the hardcoded count in capstone.** `test_phase3_capstone.py` line 730 asserts `EXPECTED_FRAMEWORK_COMPONENT_COUNT == 40` (now 43). This should just assert that the count matches the constant, not that the constant equals a specific number — the constant in `_bootstrap.py` is already the single source of truth.
- **Consider a `Layer` coercion helper.** The runtime bridge has to convert `Layer.DOMAIN` (enum) to `"DOMAIN"` (string) when calling `register_module()`. The registry's `register_constant()`/`register_type()` accept a string `layer` and do `FrameworkLayer[layer]` internally. A coercion function that accepts both `Layer` enum values and strings would simplify this conversion and make the API more flexible.

### Questions / Open Issues

- **Should `register_constant`/`register_type` create `ComponentSpec` entries?** Currently they do, which means constants and types appear in `registry.get_all()` alongside nerves and classes. This is useful for completeness (the self-model knows about everything), but it means the component graph contains entities that don't have decorators and can't be verified structurally. This may need revisiting when the structural verifier encounters these entries.
- **Edge origin taxonomy.** Currently edges have `origin="authored"` or `origin="derived"`. The derived edges (from `raises`/type annotations) aren't registered yet — that's a downstream milestone concern. When they are, should the origin value be more granular (e.g., `"derived_raises"`, `"derived_type_uses"`) to support filtering by inference source?

---

## Milestone 15 — Runtime Query APIs & Import Hook — 2026-03-09

### What Worked Well

- **The `ComponentRegistry` was straightforward to extend with query APIs.** Adding `get_component_by_canonical_id()`, `get_incoming_edges()`, `get_outgoing_edges()`, `get_observers()`, `get_verifiers()`, `get_public_nerve_coverage()`, and `get_untested_public_nerves()` followed the existing patterns naturally. All are thin convenience wrappers over existing storage — no new storage or persistence needed.
- **The import hook architecture was clean to extend.** Adding `S0maDSLLoader` alongside the existing `S0maLoader` was straightforward. The `S0maFinder._find_s0ma_spec()` method integrates cleanly with the existing `find_spec()` flow: check for `.s0ma` first, fall back to `.py`. The precedence rule (`.s0ma` wins over `.py`) is handled by the method call order in `find_spec()`.
- **Content-hash-based caching is simple and effective.** SHA-256 hash of the raw `.s0ma` source stored in a `.hash` file alongside the cached `.py` is a minimal, reliable invalidation strategy. Cache hits avoid all transpiler imports entirely.
- **Mixed .s0ma/.py backwards compatibility just works.** No special handling was needed for mixed projects — the registry doesn't care whether a `ComponentSpec` came from a `@component` decorator (`.py` path) or from transpiled output (`.s0ma` path). Module metadata (`register_module`) is simply absent for `.py` modules, and all query APIs handle this gracefully.
- **`reset_registry()` is essential for integration testing.** Transpiled `.s0ma` modules call `@component()` and `register_module()` during import, which register into the global singleton. Without `reset_registry()` between tests, components persist and cause `RegistrationError` on re-import. The `autouse` fixture pattern with `reset_registry()` before AND after each test resolved cross-test pollution cleanly.

### Pain Points

1. **`@component()` in emitted Python does not use `idempotent=True`.** The Python emitter (M11) generates `@component(name="...", ...)` without `idempotent=True`, which means re-importing a transpiled module after a `sys.modules` eviction fails with `RegistrationError` if the component is already in the global registry. This is a real problem for development workflows (hot-reload, test re-runs) and for the import hook's retranspile-on-change feature. The workaround is calling `reset_registry()` before re-import, but this is heavy-handed — it clears the entire registry. The emitter should either: (a) always emit `idempotent=True` for transpiled code, or (b) emit `register_or_update()` instead of plain `register()`. This is a change for the emitter (M11), not the registry.

2. **`S0maDSLLoader` depends on `s0ma_dsl` being installed.** The import hook lives in the s0ma framework, but `_transpile()` imports `s0ma_dsl.parser.s0ma_parser` and `s0ma_dsl.codegen.python_emitter`. This creates a soft circular dependency: `s0ma-framework` → (at transpile time) → `s0ma-dsl` → (as a dependency) → `s0ma-framework`. The lazy import (`try/except ImportError`) handles the case where `s0ma-dsl` isn't installed, but the error message guidance ("install with `pip install -e ../s0ma-dsl`") is somewhat awkward for production scenarios. For production use, `.s0ma` files should be pre-transpiled during build/CI — the import hook's on-the-fly transpilation is a development convenience.

3. **No `ComponentKind.QUERY_SERVICE` or similar for the query API methods.** The query API methods are added directly to `ComponentRegistry` (the god object). They don't have their own `@component` registration because they're methods on an existing class, not standalone components. The PRD mentions query APIs as a first-class feature (FR-27), but the implementation is procedural methods rather than a queryable service. This is fine for v1 but may warrant extraction into a dedicated `QueryService` class in v2 if the query surface grows.

### Suggestions

- **Emit `idempotent=True` on `@component()` in transpiled Python.** This is the single most impactful change for developer experience with the import hook. Without it, every re-import of a transpiled module requires a full `reset_registry()`.
- **Consider a `register_or_update` mode for `@component`.** An alternative to `idempotent=True` that replaces the existing registration rather than silently skipping. This would handle the retranspile-on-change case where the component's metadata has actually changed.
- **Document the import hook's `s0ma-dsl` dependency clearly.** The s0ma user guide should note that `.s0ma` file support in the import hook requires `s0ma-dsl` to be installed, and that production deployments should pre-transpile rather than relying on on-the-fly transpilation.
- **Add `__s0ma_cache__/` to `.gitignore` templates.** The cache directory created by the import hook should not be committed. Document this in the user guide.

### Questions / Open Issues

- **Should the emitter always use `idempotent=True`?** The current emitter generates `@component(name=..., kind=..., ...)` without `idempotent=True`. For transpiled code, idempotency is always the right behavior — the transpiler is the source of truth, and re-registration should be safe. This should be changed in the emitter (affects M11 code).
- **IR/source map generation in the import hook is best-effort.** `_write_ir_and_map()` wraps the IR builder and source map generator in a try/except and logs failures. This means `.s0ma.json` and `.s0ma.map` may not always be generated in the cache directory. Should the import hook guarantee these artifacts, or is best-effort acceptable? For v1, best-effort is fine — the primary use case for the import hook is development, not artifact generation.
- **Cache location.** The cache is at `__s0ma_cache__/` alongside the `.s0ma` file. This means it's in the source tree, which could cause issues with version control, CI, and Docker builds. An alternative is `~/.cache/s0ma-dsl/` or a configurable location. Deferring this to M20 (performance/caching milestone).

---

## Milestone 16 — CLI Entry Point & Commands — 2026-03-09

### What Worked Well

- `@component` applied cleanly to the `S0maCLI` class (registered as `ComponentKind.SERVICE`) and the `main()` entry point function (registered as `ComponentKind.FUNCTION`). The SERVICE + FUNCTION convenience wrapper pattern from M7-M15 continues to work well. `S0maCLI` is one of the few components where `ComponentKind.SERVICE` genuinely fits — it manages a lifecycle (parse args → dispatch → return exit code) and orchestrates multiple subsystems.
- `idempotent=True` remains essential. The CLI module is imported by both the test file and the `cli/__init__.py` barrel, triggering duplicate decorator evaluation during test collection.
- The entire six-stage pipeline (parse → validate → derive edges → emit Python → build IR → generate source map) composed cleanly into a single `_transpile_single_file()` orchestrator. Every stage exposes a clean functional API that takes inputs and returns outputs + errors — no global state, no side effects beyond file writes. This composability is a direct benefit of the `@component` discipline enforced across M4-M15.
- The `ProjectContext` from M12 integrated cleanly into the `build` command for cross-module features (observes resolution, privileged imports). The `determine_privileged_imports()` function accepts a `ProjectContext` and returns everything needed for the IR builder and emitter — no additional plumbing required.
- The `StrictnessMode` + `get_severity()` pattern from `config.py` works cleanly in the CLI: the `--mode` flag maps directly to a `StrictnessMode` enum value that threads through every pipeline stage. Zero adapter code needed.
- The `.s0ma.json` IR files (from M10) serve as the data source for both `inspect` and `graph` commands. The IR-first architecture decision (PRD §2.1.5) pays dividends — these commands consume pre-built artifacts rather than re-parsing source, making them fast and decoupled from the transpiler pipeline.
- 55 new tests all pass covering parser construction, file discovery, diagnostic formatting, all five commands (transpile, check, build, inspect, graph), exit codes, golden fixture validation, and strictness mode integration. All 734 tests in the full suite pass with zero regressions.

### Pain Points

1. **`ComponentKind.SERVICE` for `S0maCLI` is a reasonable fit**, unlike previous milestones where SERVICE felt overloaded. The CLI genuinely orchestrates a lifecycle (argument parsing → command dispatch → exit code). No pain point here — just noting that this is one case where the taxonomy works well.

2. **Exit code constants are not provided by the framework.** The PRD §2.8.2 defines exit codes (0=success, 1=validation error, 2=usage error, 3=internal error), but these aren't available as constants from the s0ma framework. The CLI defines them as module-level constants (`EXIT_SUCCESS`, `EXIT_VALIDATION_ERROR`, `EXIT_USAGE_ERROR`, `EXIT_INTERNAL_ERROR`). If other tools in the s0ma ecosystem need the same exit codes, they'll duplicate these definitions.

3. **No `ComponentKind.CLI` or `ComponentKind.COMMAND`.** The `S0maCLI` class is a command-line interface — a distinct archetype from a background service or a library service. It has a lifecycle (parse → dispatch → exit), it interacts with the filesystem and stdout, and it returns exit codes. `ComponentKind.SERVICE` works but doesn't capture the command-oriented nature of the component. This is a minor observation, not a blocking issue.

### Suggestions

- Consider providing standard exit code constants in the s0ma framework (e.g., `s0ma.types.ExitCode.SUCCESS`, `ExitCode.VALIDATION_ERROR`, etc.) for tools in the ecosystem. The PRD defines these values, so they should be first-class framework types rather than ad-hoc constants in each tool.
- The `idempotent=True` recommendation from M13 feedback is reinforced yet again — every single milestone has needed it. This should be the default for `@component` or at least prominently documented as the standard for library/framework code.
- The six-stage pipeline's clean composability is a testament to the `@component` discipline. Consider documenting this as a case study in the s0ma user guide: "How functional API design enables pipeline composition."

### Questions / Open Issues

- **`pyproject.toml` entry point was already configured.** The M1 scaffolding milestone pre-registered `s0ma = "s0ma_dsl.cli.main:main"` in `pyproject.toml` line 39. No changes were needed in M16. This is good forward planning — the entry point was a placeholder awaiting the real implementation.
- **`inspect` and `graph` commands require pre-transpiled IR.** These commands read `.s0ma.json` files from the output directory, meaning the user must run `s0ma transpile` or `s0ma build` first. An alternative would be to parse `.s0ma` source on-the-fly and build a transient IR for inspection. The current design (IR-first) is consistent with the PRD's architecture but requires a two-step workflow for first-time users. A `--from-source` flag could be added in a future milestone.
- **`build --clean` removes the entire output directory.** This is a destructive operation that deletes all files in `--output-dir`, not just transpiler-generated ones. If the user sets `--output-dir` to a directory containing non-transpiled files, those will be lost. Consider only deleting files with `.s0ma.py`, `.s0ma.json`, and `.s0ma.map` extensions, or maintaining a manifest of generated files.

---

## Milestone 17 — Golden Test Suite — 2026-03-09

### What Worked Well

- **The full pipeline composes cleanly for golden testing.** Every stage (`parse_s0ma` → `validate_module` → `analyze_derived_edges` → `emit_python` → `build_ir` → `generate_source_map`) has a clean functional API that takes inputs and returns outputs + errors. Building a golden test runner was straightforward — just chain the functions. This is a direct benefit of the `@component` discipline enforced across M4-M16.
- **No `@component` registration needed for the golden test module itself.** `test_golden.py` is a pytest test module, not transpiler infrastructure, so it doesn't need `@component` decorators. The framework's distinction between "test infrastructure" and "component infrastructure" works well here.
- **The IR-first architecture (PRD §2.1.5) enables robust roundtrip testing.** The roundtrip test (IR ↔ AST consistency) was easy to implement because the IR builder consumes the semantic model directly. Every component in the source has a corresponding IR entry; every edge has proper origin tags. The canonical model is trustworthy.
- **Determinism testing is trivially reliable.** Running the pipeline twice on the same input produces byte-identical IR, Python, and source maps. No non-deterministic ordering, no timestamps, no random IDs. PRD P6 is fully satisfied.
- **The negative fixture pattern is powerful.** Each invalid `.s0ma` file targets a single error code, making error detection tests precise and debuggable. The error quality tests (remediation non-empty, source location present) caught no gaps — every error has the required fields per PRD §2.4.1.

### Pain Points

1. **Parser's `_parse_name_list` doesn't support glob patterns for `observes`.** The Lark grammar's `name_list` rule only accepts `NAME` and `QUALIFIED_NAME` terminals. Ganglion `observes` patterns like `task_service.*` and `APPLICATION::*` (module-glob and layer-glob per PRD §2.2.4) fail at parse time. The `ObservesResolver` (M12) supports these patterns when given pre-built AST nodes, but the parser can't produce them from `.s0ma` source. This means the golden project's ganglia fixture had to use only exact-name observes patterns instead of exercising all three pattern forms. **This is a gap between the parser and the observes resolver that should be fixed** — the grammar needs `GLOB_NAME` and `LAYER_GLOB` terminals.

2. **Body validation warnings are suppressed in DEV/MIGRATION mode, not collected.** The severity matrix (PRD §2.4.3) says `PROHIBITED_CONSTRUCT` and `BARE_IMPORT` should be _warnings_ in DEV/MIGRATION mode. However, the parser's body validation either raises the error (STRICT/RELEASE) or silently suppresses it (DEV/MIGRATION). The warnings are not collected into any list — they simply disappear. This means coding agents in DEV mode get no signal about prohibited constructs in their code. The body validator should collect warnings and return them alongside the parsed module, rather than swallowing them.

3. **`ComponentKind.SERVICE` continues to be used for all non-trivial test infrastructure.** This is the same feedback from M6-M16. No action needed for M17 specifically, but the pattern persists.

### Suggestions

- **Extend the Lark grammar to support glob patterns in `observes` lists.** Add `GLOB_NAME: /[a-zA-Z_][a-zA-Z0-9_]*\.\*/` and `LAYER_GLOB: /[A-Z]+::\*/` terminals to the grammar, and make `name_list_item` accept them. This would allow ganglion declarations to use all three observes pattern forms directly in `.s0ma` source.
- **Refactor body validation to collect warnings instead of raising/suppressing.** The body extractor's `validate_body()` should return a list of `S0maError` objects (with severity determined by strictness mode) rather than raising on error and silently discarding on warning. This would fix the "swallowed warnings" gap and make the severity matrix work correctly for body-related codes.
- **Consider a `RegistryRoundtripValidator` service** that takes an `IRDocument` and a populated `ComponentRegistry` and verifies structural consistency. This would formalize the roundtrip test pattern into a reusable tool for downstream projects.

### Questions / Open Issues

- **Glob observes parsing gap.** The parser doesn't support glob patterns in `observes`, which means the golden project can't exercise module-glob (`task_service.*`) or layer-glob (`APPLICATION::*`) patterns from `.s0ma` source. All three forms work when AST nodes are constructed programmatically (confirmed by M12 tests), but the parse-to-AST path is broken for globs. This should be addressed in a follow-up to M4 (parser) or M12 (observes resolver).
- **Body validation warning collection.** Should this be fixed in M18 (Error UX Polish) or as a standalone fix? It affects the severity matrix correctness for 4 error codes (PROHIBITED_CONSTRUCT, BARE_IMPORT in DEV/MIGRATION modes).
- **Runtime import test deferred.** The golden test runner validates transpiled Python _compiles_ (`compile()` succeeds) but doesn't _import_ it (which would trigger `@component` registration). Full import-and-register testing requires a clean registry setup and teardown per test, which is better suited to M18-M19 or the integration test infrastructure. The roundtrip test validates IR↔AST consistency as a proxy for correctness.

---

## Milestone 18 — Error UX Polish — 2026-03-09

### What Worked Well

- **The error system was already well-structured before M18.** The audit of all 73 error creation sites across 7 source modules found that 72 out of 73 had specific remediation, 70 out of 73 had populated context dicts, and 71 out of 73 had meaningful line values. The `S0maError` dataclass design (PRD §2.4.1) enforced good practices from M1 onward — requiring `remediation` as a mandatory field meant developers couldn't skip it. This is a vindication of the "structured errors as a product feature" principle.
- **`@component(idempotent=True)` was NOT needed for M18.** The test file (`test_error_ux.py`) doesn't define any `@component`-decorated classes — it only imports existing transpiler modules. This is the correct pattern for pure test modules: they consume components, they don't register new ones.
- **The `S0maError.to_dict()` → JSON serialization path is clean and reliable.** Round-tripping errors through `to_dict()` → `json.dumps()` → `json.loads()` produces identical structures. The context dict supports arbitrary JSON-serializable types (int, list, bool, str, nested dicts). This makes the JSON error output trivially correct once the base `to_dict()` method works.
- **The `S0maError.format_text()` method provides a consistent format.** All 73 error creation sites produce identically structured text output (file:line: SEVERITY [CODE] / message / Remediation:) without any per-site formatting logic. This consistency is a direct benefit of centralizing formatting on the error class itself rather than in consumers.

### Pain Points

1. **No pain points with the s0ma framework in this milestone.** M18 was purely about polishing the transpiler's own error system, which doesn't directly interact with the s0ma decorator API. The `@component` and `@internal` decorators were not involved in this milestone's implementation work.

2. **The catch-all exception handler in `_parse_single_file()` had a generic remediation.** The original handler (from M16) created a `S0maParseError` with `remediation="Check the .s0ma file syntax and try again."` and `line=0` and empty context. This violated the PRD §2.4.1 requirement that remediation be "specific and actionable." Fixed by providing a more informative remediation that includes the filename, the nature of the error, and guidance on whether it might be a transpiler bug. Also added `context={"exception_type": ..., "exception_message": ...}` for structured debugging.

3. **Two error creation sites in `s0ma_parser.py` and `body_extractor.py` had empty `context` dicts.** These were edge cases (unexpected top-level content, empty body after separator) where the context seemed "obvious" from the message. Fixed by adding minimal context keys (`{"content": ...}` and `{"reason": "empty_body"}`) to maintain the invariant that every error has a non-empty context.

### Suggestions

- **Consider making `context` a required keyword argument (not default-factory empty dict).** The current `field(default_factory=dict)` on `S0maError.context` makes it easy to forget populating it. If context were required at construction time (or at least a `# noqa: empty-context` convention for intentional empties), the 3 missing-context errors found in M18's audit would have been caught at development time. This is a minor suggestion — 70/73 (95.9%) already had context populated without enforcement.
- The `idempotent=True` recommendation from previous milestones (M1-M16) was not relevant to M18 since no new components were registered. However, the consistent recommendation stands for all future milestones that add `@component`-decorated classes.

### Questions / Open Issues

- **Body validation warning collection remains deferred.** M17 noted that body validation warnings (PROHIBITED_CONSTRUCT, BARE_IMPORT in DEV/MIGRATION modes) are suppressed rather than collected. M18 audited this and confirms it's still the case. The body validator either raises (STRICT/RELEASE) or silently suppresses (DEV/MIGRATION). This should be addressed in a future milestone — either M19 (Strictness Mode Complete Implementation) or a standalone fix. The severity matrix is correctly defined; it's the body validator's collection behavior that's incomplete.
- **The `authored_raises_axon.s0ma` fixture fails at parse time (PARSE_ERROR), not semantic time (INVALID_AXON_RELATION).** The parser rejects `RAISES` as an inline `depends_on` relation before the semantic validator can check it. This is correct behavior (parser catches it earlier, which is preferred per PRD P2), but means the `INVALID_AXON_RELATION` error code from the semantic validator is unreachable for inline axons parsed from `.s0ma` source. It's still testable via programmatically constructed AST nodes (confirmed in M7 tests). The golden test was updated to expect `PARSE_ERROR` for this fixture.

---

## Milestone 19 — Strictness Mode Complete Implementation — 2026-03-09

### What Worked Well

- **The `SEVERITY_MATRIX` design from M1/M2 paid off handsomely.** All 21 error codes × 4 modes were already correctly defined in `config.py`. The matrix-driven `get_severity()` function made it trivial to add mode-dependent checks in the resolver and validator — just call `get_severity(code, mode)` and skip if `None`. Zero modifications needed to the matrix itself.
- **`@component(idempotent=True)` continues to work flawlessly.** No new `@component`-decorated classes were added in M19, but the existing ones (`DependencyResolver`, `IntraModuleValidator`) were extended with new methods. The decorator's non-wrapping design means adding methods to a `@dataclass` class works exactly like adding methods to an undecorated class — no special considerations needed.
- **The `S0maResolutionError` hierarchy made it natural to emit cross-module errors.** The new `_check_release_test_coverage()` method produces `S0maResolutionError` instances identical in structure to all other resolver errors. The error system's uniform interface (code, message, file, line, column, severity, remediation, context) meant no new patterns were needed.
- **`ComponentKind.SERVICE` and `ComponentKind.FUNCTION` accurately describe the extended components.** `DependencyResolver` (SERVICE) gained a new private method — the component kind correctly reflects that it's a stateful service instance. `resolve_dependencies` (FUNCTION) is a pure convenience wrapper. The kind taxonomy remains clean.

### Pain Points

1. **The parser drops body-validation warnings — still not fixed.** M17 and M18 both flagged this: `parse_s0ma()` collects body errors in a list, raises the first hard error, but silently discards warnings when returning a `S0maModule`. This means PROHIBITED_CONSTRUCT and BARE_IMPORT warnings in MIGRATION/DEV mode are produced by the body extractor but never reach callers. The M19 strictness tests had to test these at the body-extractor level rather than through the full pipeline. This is the most significant remaining gap in strictness mode completeness. The fix is to change `parse_s0ma()` to return `(S0maModule, list[S0maError])` instead of just `S0maModule`, but this is a breaking API change that ripples through the CLI, tests, and import hook.

2. **Pre-existing bug in CLI `_cmd_check` and `_cmd_build`.** Both methods called `resolve_dependencies(modules, mode=mode)` where `modules` was a `list[S0maModule]` but the function expects `dict[str, S0maModule]`. Additionally, the return value was unpacked as a tuple (`resolution_errors, _ = ...`) but the function returns a `list`. This would crash at runtime for any multi-file check or build. Fixed as part of M19 by converting to proper dict-based module tracking and removing the erroneous tuple unpacking.

3. **"Hand-written axon intents" release check deferred.** PRD §2.4.3 mentions "all cross-module axon intents are hand-written" as a release-mode check, but no error code is defined in §2.4.2 for this check. Without a defined error code and clear acceptance criteria (what distinguishes "hand-written" from "auto-generated"?), implementing this check would be speculative. Deferred until the PRD clarifies the requirement.

### Suggestions

- **Add a `parse_s0ma_with_warnings()` function or change the return type.** The current `parse_s0ma() -> S0maModule` API structurally prevents surfacing body warnings. A companion function returning `tuple[S0maModule, list[S0maError]]` (or a `ParseResult` dataclass) would allow the CLI and import hook to collect warnings without breaking existing callers. This is the single most impactful improvement for strictness mode correctness.
- **Define an error code for the "hand-written axon intents" release check.** If this check is desired, it needs a clear definition: an error code (e.g., `GENERIC_INTENT`), detection heuristic (minimum length? no template phrases?), and severity mapping in the matrix. Without these, it's unimplementable.

### Questions / Open Issues

- **Body validation warning surfacing** is now flagged in three consecutive milestones (M17, M18, M19). Should this be escalated to a standalone fix milestone or rolled into M20?
- **Non-zero version check scope:** M19 implemented the check only for version `0.0.0`. Should it also reject `0.x.y` versions (any zero-major) in release mode? The current interpretation ("non-zero" = not `0.0.0`) is conservative. Semver convention treats `0.x.y` as pre-release, which arguably shouldn't pass release-mode validation.

---

## Post-M19 Fix — Parser Warning Surfacing — 2026-03-09

### Resolution

The body-validation warning surfacing gap flagged in M17, M18, and M19 is now **fixed**.

#### What was done:

1. **Added `parse_s0ma_with_warnings()` to `s0ma_parser.py`.** Returns `tuple[S0maModule, list[S0maError]]` — the module plus any non-error body-validation diagnostics (PROHIBITED_CONSTRUCT, BARE_IMPORT warnings in MIGRATION/DEV mode). The original `parse_s0ma()` is preserved for backward compatibility.

2. **Updated CLI `_parse_single_file()`.** Now calls `parse_s0ma_with_warnings()` instead of `parse_s0ma()`, so body warnings flow through to `_cmd_check`, `_cmd_build`, and `_cmd_transpile` diagnostic output. Users will now see warnings in the terminal when running `s0ma check` or `s0ma build` in MIGRATION/DEV mode.

3. **Updated the s0ma import hook.** Both `_transpile()` and `_write_ir_and_map()` now use `parse_s0ma_with_warnings()`. Warnings are emitted via `logger.warning()` so they appear in Python's logging output during import-time transpilation.

4. **Upgraded strictness tests.** `TestProhibitedConstructByMode` and `TestBareImportByMode` migration/dev tests now exercise the full parse pipeline (via `_parse_and_validate` → `parse_s0ma_with_warnings`) instead of testing the body extractor in isolation. All 126 strictness tests pass, all 1012 project tests pass.

### Impact

- **Three-milestone gap closed.** Body-validation warnings are no longer silently discarded. The strictness mode pipeline is now fully end-to-end for all 21 error codes across all 4 modes.
- **Backward-compatible.** `parse_s0ma()` signature unchanged. Only callers that opt in to `parse_s0ma_with_warnings()` get the new behavior.
- **Zero test regressions.** 1012/1012 tests pass.

---

## Milestone 20 — Performance Testing & Optimization — 2026-03-09

### What Worked Well

- **`@component` applied cleanly to both new types** in `cache.py`: `CacheResult` (frozen dataclass, registered as `ComponentKind.MODEL`) and `BuildCache` (mutable dataclass, registered as `ComponentKind.SERVICE`). The decorator's zero-overhead design means the frozen `CacheResult` remains truly frozen and the mutable `BuildCache` accumulates state normally. `idempotent=True` continues to be essential for library code.
- **The transpiler is extremely fast.** Pipeline profiling reveals the full six-stage pipeline completes in ~1ms per file on the golden fixture. The 55-module stress project builds in under 1 second. All PRD NFR-04 targets are exceeded by large margins:
  - Single file parse + validate: ~0.6ms (target: < 100ms)
  - Single file transpile (all outputs): ~1.1ms (target: < 500ms)
  - 55-module project build: ~0.5s (target: < 30s)
  - Cached retranspile: < 1ms (target: < 1s)
  - Peak memory (55 modules): < 5MB (target: < 500MB)
- **Determinism is fully verified.** Triple-run tests confirm byte-identical output for Python, IR, and source maps (after normalising embedded absolute paths). Content hashes are deterministic across runs. Diagnostic ordering is stable.
- **`ComponentKind.SERVICE` is a natural fit for `BuildCache`.** Unlike the analysis/validator components flagged in M6-M12, the build cache genuinely manages state (hit/miss counters, file I/O, cache directory lifecycle) and has a clear service interface (lookup, store, invalidate, clear).

### Pain Points

1. **IR and source map embed absolute paths, breaking naive byte-for-byte comparison.** The `.s0ma.json` contains `source_file` and `transpiled_file` as absolute paths, and `.s0ma.map` contains `output_file` and `source_file`. When comparing outputs across different output directories (e.g., determinism tests with `run_a/` vs `run_b/`), these embedded paths differ. The determinism tests normalise paths before comparison, which correctly tests that all *semantic* content is identical. However, this means PRD P6's "identical byte-for-byte" guarantee holds only when the same output directory is used — which is the production scenario. Consider whether IR/source map paths should be relative rather than absolute, which would make byte-for-byte comparison trivially correct regardless of output location.

2. **No `ComponentKind` for "cache" or "store".** `BuildCache` is registered as `ComponentKind.SERVICE`, which is accurate but generic. A `ComponentKind.CACHE` or `ComponentKind.STORE` kind would better capture the caching archetype. This is a minor observation — `SERVICE` is appropriate and functional.

### Suggestions

- **Consider making IR/source map paths relative to the project root** rather than absolute. This would simplify determinism verification and make artifacts more portable (e.g., for CI, containerised builds, or sharing `.s0ma.json` across machines).
- The `idempotent=True` recommendation continues to apply to every new component. After 20 milestones of consistent need, this should be the documented default for library/framework code.
- **Cache location strategy.** The current cache lives at `__s0ma_cache__/` under the output directory (or project directory if no output dir). For CI/production, consider supporting `~/.cache/s0ma-dsl/` or a configurable cache root via environment variable or config file. The current approach works well for development but creates artifacts in the source tree.

### Questions / Open Issues

- **Cross-module dependency cache invalidation.** The current cache invalidates per-file based on source content hash. It does NOT invalidate when a *dependency* changes (e.g., if module A uses module B, and B's exports change, A's cached output is stale). Full incremental recompilation with dependency-aware invalidation is explicitly deferred to v2 (PRD §1.6). The current implementation is correct for the v1 scope — individual file caching with content-hash invalidation.
- **Cache integration with `s0ma transpile` command.** The cache is currently integrated only with `s0ma build`. The `s0ma transpile` command does not use caching because it targets individual files without a project context. Should `s0ma transpile` support an optional `--cache-dir` flag? This is a minor UX question for a future milestone.

---

## Milestone 21 — Determinism Hardening — 2026-03-10

### What Worked Well

- **The codebase was already well-hardened for determinism before M21.** The systematic audit of all source modules found zero non-deterministic ordering issues. Every set used for output is sorted before emission (e.g., `sorted(set(types_needed))` in `python_emitter.py:405`). Every dict iteration that affects output uses deterministic insertion order. All JSON serialization uses `sort_keys=True`. This is a testament to the discipline enforced across M1-M20 — determinism was treated as a correctness requirement from day one, not a retrofit.
- **No `@component`-decorated classes were added in M21.** The test file (`test_determinism.py`) is a pure pytest module that consumes existing transpiler modules. The framework's distinction between test infrastructure and component infrastructure continues to work cleanly.
- **The triple-run test pattern is simple and effective.** Running the pipeline 3 times on the same input and asserting byte-identical output across all artifacts (Python, IR, source map, diagnostics) is a powerful regression test. The existing pipeline's functional API (each stage takes inputs and returns outputs) makes this trivially composable.
- **Parametrized tests over fixture directories (`pytest.fixture(params=sorted(...))`) provide comprehensive coverage.** Every valid fixture and every invalid fixture is automatically tested for determinism without maintaining a manual list. New fixtures added in future milestones will be automatically included.

### Pain Points

1. **No pain points with the s0ma framework in this milestone.** M21 was purely about auditing and testing the transpiler's own determinism guarantees. The `@component` and `@internal` decorators were not involved in this milestone's implementation work.

2. **The `PytestCollectionWarning` for `TestDecl` continues to appear (now across 11 test files).** This is unchanged from M3 feedback — the warning scales linearly with the number of test files importing AST nodes. It's harmless but adds visual noise. A project-wide `collect_ignore` configuration would suppress it cleanly.

### Suggestions

- The `idempotent=True` recommendation from M1-M20 was not relevant to M21 since no new components were registered. The consistent recommendation stands for all future milestones that add `@component`-decorated classes.
- Consider adding a `conftest.py`-level `collect_ignore_glob` to suppress the `TestDecl` collection warning project-wide, since it now appears in 11+ test files.

### Questions / Open Issues

- **IR/source map paths are absolute.** Determinism tests that compare outputs across different output directories must normalize embedded paths before comparison (replacing absolute paths with `<DIR>` placeholders). This is correct for production use (same output dir = byte-identical), but makes CI determinism testing slightly more complex. The M20 feedback suggested making paths relative to project root — this remains a valid improvement for a future milestone.
- **Verification edge ordering test skipped for golden fixture.** The `test_verification_edges_sorted` test requires 2+ verification edges, but the golden fixture (`signal_processor.s0ma`) has only one test declaration. The golden project exercises this through its multi-module test suite. Future fixtures with multiple test declarations will activate this test automatically via the parametrized valid-fixture tests.

---

## Milestone 22 — Transpiler Self-Description Audit — 2026-03-10

### What Worked Well

- **The transpiler is a fully queryable s0ma project.** After M22, the transpiler registers **80 components** across 18 source modules. Every public class, enum, and function has a `@component` decorator with `idempotent=True` and `Layer.FRAMEWORK`. The `SelfModelInterface.describe_system()` output includes all transpiler components alongside the 43 framework components. The system can truly describe the system that describes systems.
- **`register_from_module()` is essential for testing self-description.** Since `@component` decorators fire at import time into whatever global registry is active, and test setups need fresh registries, `register_from_module()` is the correct pattern for re-registering already-imported modules into a clean registry. This worked flawlessly — scanning 18 modules and registering 80 components into a fresh registry takes less than 10ms.
- **`idempotent=True` across the entire codebase proved its value.** All 80 components use `idempotent=True`, which means the transpiler can be imported in any order, from any number of test files, without `RegistrationError`. This is the pattern that 21 previous milestones recommended as the default for library code.
- **The `S0maDSL_` prefix convention works well.** All 80 transpiler components use the `S0maDSL_` prefix, which prevents collisions with the 43 framework components and any future sister project components (ax0n, st3mcell). The prefix also makes it trivial to filter for transpiler-specific components in registry queries.
- **Component kind distribution is healthy.** The 80 components break down as: ~49 MODEL (enums, AST nodes, IR schema types, error types), ~11 SERVICE (parser, validator, resolver, emitter, etc.), ~20 FUNCTION (convenience wrappers, utilities). This distribution accurately reflects the transpiler's architecture: predominantly data types with service orchestrators and utility functions.

### Pain Points

1. **`register_from_module()` is required for dogfooding tests, but the pattern is not documented.** The user guide documents `register_from_module()` in the troubleshooting section (§9) for "Components Not Re-Registering After Reset", but the self-description audit pattern — `reset_registry()` → `initialize(persist=False)` → scan all modules with `register_from_module()` — is not documented as a first-class testing pattern. Any s0ma project that wants to test its own self-model will need this exact workflow. It should be promoted from a troubleshooting workaround to a documented testing pattern.

2. **Four public convenience functions were missing `@component` after 21 milestones.** Despite CC-1 requiring `@component` on every public function, `get_severity()`, `parse_s0ma()`, `parse_s0ma_with_warnings()`, and `compute_content_hash()` had been overlooked across M1–M21. All other convenience functions (e.g., `emit_python()`, `build_ir()`, `validate_module()`) were properly decorated. The gap was not caught earlier because no automated check enforced `@component` coverage — the rule relied on manual discipline per milestone. An automated lint or CI check would prevent this drift.

3. **`ComponentKind` taxonomy still has the ontological gap flagged in M6–M16.** The transpiler has 11 SERVICE components, but several are stateless analysis passes (`IntraModuleValidator`, `DerivedEdgeAnalyzer`, `DependencyResolver`) rather than lifecycle-managing services. The `SERVICE` kind remains overloaded. This is the 17th milestone to note this gap. While not blocking, the lack of `ANALYZER`/`VALIDATOR`/`RESOLVER` kinds means the self-model loses archetype precision for analysis-oriented components.

### Suggestions

- **Document the self-description testing pattern in the user guide.** Add a "Testing Your Project's Self-Model" section alongside the existing `fresh_registry()` and `isolate_registry()` patterns. The pattern is: create a fresh registry, scan all project modules with `register_from_module()`, then query the registry to verify component coverage. This is useful for any s0ma project that wants to audit its own dogfooding compliance.
- **Consider adding a `s0ma verify --self-model` command** (or equivalent) that checks `@component`/`@internal` coverage across all Python modules in a project. This would automate what M22 does manually: import every module, check that every public class and function has a `__component__` attribute, and report gaps.
- **The `idempotent=True` recommendation is now proven across 22 milestones.** Consider making `idempotent=True` the default for `@component`, or at minimum, document it as the standard for library/framework/tool code. The only scenario where `idempotent=False` is appropriate is application-level singletons where duplicate registration genuinely indicates a bug. For library code (which is the majority of s0ma projects), `idempotent=True` should be the default.

### Questions / Open Issues

- **No `@component` coverage for `__init__.py` re-export modules.** The 10 `__init__.py` files in the transpiler only contain re-exports (`from .foo import Bar; __all__ = [...]`). They don't define public classes or functions, so they don't need `@component`. This is the correct behavior — re-export modules are structural glue, not independent components. No action needed, but worth documenting as an explicit convention.
- **Component dependency declarations are empty.** All 80 transpiler components register with `dependencies=[]` because the `@component` decorator's `dependencies` field requires listing component names, which would need to be maintained manually alongside Python imports. This means the registry's dependency graph for the transpiler is flat (no edges). The DSL itself solves this problem (via `uses`, `depends_on`, and derived edges), but the transpiler's own code uses plain `@component` decorators, not `.s0ma` files. For v2, converting the transpiler's modules to `.s0ma` (eating our own dog food at the DSL level) would make the dependency graph complete.

---

## Milestone 23 — Documentation & Coding Agent Prompt — 2026-03-10

### What Worked Well

- **The DSL syntax is agent-friendly.** Writing the quick reference and system prompt was straightforward because the DSL has a consistent, predictable structure across all declaration types. The field-per-line format with explicit keywords (kind, visibility, intent, etc.) maps cleanly to a concise reference table. An LLM reading the quick reference has enough information to produce valid `.s0ma` files.
- **The fresh agent test validated the docs end-to-end.** A new `.s0ma` fixture (`fresh_agent_test.s0ma`) was written using only the quick reference as a guide, and it passed `s0ma check --mode strict` after one fix. The one error (`DUPLICATE_AXON` for an inline `depends_on` that overlapped with a derived TYPE_USES edge from a type annotation) produced an excellent, actionable remediation message — exactly what PRD P3 demands.
- **Error remediations drive documentation improvements.** The `DUPLICATE_AXON` error remediation ("Remove the inline depends_on entry for 'AuthToken' — the TYPE_USES edge is already derived from the 'function signature'") was clear enough to fix the issue in one step. This confirmed that the error system is doing its job as a teaching tool for agents. The finding was fed back into the quick reference and system prompt as a new rule.
- **`s0ma check --mode strict` is the right validation target for agent-authored code.** It catches everything except release-mode concerns (test coverage, non-zero versions) which are project-level, not file-level. This is the correct default for the system prompt to recommend.

### Pain Points

1. **No `@component` involvement in M23.** This milestone created documentation files (`.md`) and a test fixture (`.s0ma`), neither of which are Python modules requiring `@component` decorators. The framework's decorator model is not relevant to documentation tasks. No friction, but also no validation of the framework itself.

2. **The DUPLICATE_AXON overlap between authored `depends_on` and derived TYPE_USES is a common agent trap.** When a nerve's body constructs or calls a component that also appears in the function's type annotation, an agent will naturally write both a `depends_on` entry (for the authored CONSTRUCTS/CALLS relationship) and a return type annotation (which triggers derived TYPE_USES). The transpiler correctly rejects this overlap, but it requires the agent to understand that TYPE_USES is derived from annotations and must not be duplicated by authored edges targeting the same component. This is subtle and not obvious from the DSL syntax alone. The quick reference now documents this, but it may be the most common error agents encounter.

3. **The `s0ma check` exit code 1 output goes to stderr.** When validation fails, the error output is on stderr and the exit code is 1. This is correct per PRD §2.8.2, but it means shell pipelines need `2>&1` to capture errors. For agent workflows, `--format json` sending everything to stdout would be more convenient. This works today, but it's worth noting that the default text format splits output across stdout (success message) and stderr (errors).

### Suggestions

- **Consider adding a `DUPLICATE_AXON` guidance section to the spec.** The overlap between authored `depends_on` and derived TYPE_USES is the most common error for agents writing new `.s0ma` files. The spec's §4.11 (relationship derivation) mentions single-source authority, but a concrete example showing the conflict would prevent this error proactively.
- **Consider a `s0ma init` command** that generates a skeleton `.s0ma` file from a template. This would bootstrap new modules faster than writing from scratch, and the template could encode the mandatory fields and correct structure. Not blocking for v1, but useful for adoption.
- The `idempotent=True` recommendation from M1-M22 was not relevant to M23 since no new components were registered.

### Questions / Open Issues

- **Fresh agent test fixture location.** The `fresh_agent_test.s0ma` fixture was placed in `tests/fixtures/valid/` so it participates in the existing parametrized valid-fixture tests (parser, determinism, etc.). This is intentional — it doubles as both documentation validation and regression test coverage. If this causes issues with golden tests that expect a fixed fixture set, it may need to move to a separate `tests/fixtures/docs/` directory.
- **Migration guide validation.** The migration guide documents the conversion process with examples, but it was not tested by actually converting an existing `@component` Python module to `.s0ma`. That validation is the purpose of M24 (ax0n conversion). The guide's correctness will be confirmed when M24 exercises the documented workflow.

---

## Findings 1-2 Implementation — Milestone 1 (Layer Import & Dependency Declaration) — 2026-04-01

### What Worked Well

1. **The `@component` decorator model continues to be zero-friction for existing code.** The codegen fix (moving `Layer` from the `has_decorated` conditional to unconditional) required changing only 3 lines in `_determine_s0ma_imports()`. The decorator's non-wrapping, non-proxying design meant no behavioral side effects — frozen dataclass cells, registration functions, and the emitter all continued working identically after the change. The s0ma contract (decorator returns entity unmodified) makes changes like this safe and local.

2. **The test infrastructure is well-designed for regression testing.** The existing `_minimal_module()` helper, `_compile_check()` validator, and `S0maModule` AST construction patterns in `test_codegen.py` made it trivial to write targeted tests for the constant-only module case. Building a new `S0maModule` with only `CellDecl(kind=Kind.CONSTANT)` and asserting on the emitted output took minimal code. The AST node design — frozen dataclasses with sensible defaults — is highly composable for test construction.

3. **The findings document accurately pinpointed root causes.** Finding 1.1 identified the exact method (`_determine_s0ma_imports()`), the exact conditional (`has_decorated`), and the exact interaction (every module emits `register_module()` which requires `Layer`). This made the fix a direct application rather than an investigation. Well-structured findings documents dramatically reduce agent ramp-up time.

### Pain Points

1. **`Layer` import in s0ma.types vs. s0ma_dsl.ast_nodes.enums ambiguity.** The transpiler defines its own `s0ma_dsl.ast_nodes.enums.Layer` enum (used internally for AST representation), while the emitted code imports `s0ma.types.Layer` (the runtime enum). Both have the same member names but are distinct types. In `test_codegen.py`, the test file imports `Layer` from `s0ma_dsl.ast_nodes.enums`, which is correct for constructing AST nodes — but it requires understanding that emitted code references a different `Layer`. This dual-Layer situation isn't confusing once understood, but an agent encountering it for the first time might import from the wrong module. The s0ma framework could benefit from a note in the user guide clarifying that sister projects may shadow framework types internally.

2. **The `pyproject.toml` dependency on `lark` missing the `[interegular]` extra is a class of bug that framework documentation could help prevent.** The s0ma user guide's Section 1.1 lists extras like `[api]`, `[mcp]`, `[all]` — this is a good pattern. When s0ma-dsl or other sister projects have dependencies with required extras, there's no standard place to document "you need the extra, not just the base package." This is more of a general Python packaging issue than a s0ma issue, but the pattern of documenting required extras prominently (as s0ma does for its own extras) is worth recommending to downstream projects.

### Suggestions

- Consider adding a "Type Shadowing" note to the user guide for sister projects that define internal types mirroring s0ma types (e.g., a project-local `Layer` enum for AST representation vs. `s0ma.types.Layer` for runtime). This is an inherent design choice (not a bug), but documenting the pattern helps agents navigate it.
- The `@component(idempotent=True)` pattern continues to work well for all transpiler components. No issues encountered in this milestone.

### Questions / Open Issues

- None for this milestone. Both tasks were self-contained bug fixes with clear root causes and straightforward resolutions.

---

## Milestone 2 — Windows Encoding & Cache Staleness Fixes — 2026-04-01

### What Worked Well

1. **The `BuildCache` class was already well-designed for the staleness fix.** The plan called for adding an `invalidate(source_path)` method to `BuildCache`, but it already existed (line 174 of `cache.py`) with exactly the right semantics — removing `.hash`, `.py`, `.s0ma.json`, and `.s0ma.map` artifacts by stem. This meant the fix in `_cmd_transpile()` only needed to instantiate `BuildCache` and call the existing method. The s0ma component model's emphasis on clear, single-responsibility design made this method easy to discover and trust without additional verification.

2. **The `@component` decorator on `main()` (a standalone function) and `S0maCLI` (a class) both worked cleanly with the UTF-8 fix.** Adding `sys.stdout.reconfigure()` at the top of `main()` required no interaction with the decorator — the decorator's non-wrapping guarantee meant the function body is exactly what runs. No need to reason about decoration ordering or wrapper behavior.

3. **`idempotent=True` continues to prevent test-time registration collisions.** Both `BuildCache` and `S0maCLI` are imported into multiple test modules; the `idempotent=True` flag on all transpiler components avoids `RegistrationError` during parallel test collection. This pattern is validated again this milestone.

### Pain Points

1. **No s0ma-level pattern for cross-command cache coordination.** The staleness bug arose because `_cmd_transpile()` and `_cmd_build()` have different cache awareness: `_cmd_build()` creates and uses a `BuildCache`, while `_cmd_transpile()` was entirely cache-unaware. The s0ma `@component` model describes individual components well, but doesn't provide a mechanism to express "these two commands share state through this artifact" at the architectural level. The `dependencies` field in `@component` tracks component-to-component dependencies, but shared filesystem artifacts like `__s0ma_cache__/` are invisible to the self-model. This is arguably outside s0ma's scope (it's a build-tool concern, not a component-registration concern), but it's worth noting that shared-state coordination between commands is a class of bug that the current self-model can't surface.

2. **Testing `sys.platform`-gated behavior requires careful mocking.** The Windows UTF-8 fix is guarded by `sys.platform == "win32"`, which means testing on macOS/Linux requires monkeypatching `sys.platform` and providing mock streams with `reconfigure()` methods. This is standard Python testing, not a s0ma issue — but it's worth noting that the s0ma testing patterns documented in the user guide (Section 8) focus on registry isolation (`fresh_registry()`, `isolate_registry()`) and don't cover platform-specific behavior testing. A brief mention of monkeypatching strategies alongside s0ma test isolation patterns could help agents writing cross-platform code.

### Suggestions

- Consider whether the s0ma self-model could represent shared filesystem artifacts (like cache directories) as a dependency type. Currently, `dependencies` is a list of component names. A "resource dependency" concept (e.g., `resources=["__s0ma_cache__"]`) could make cross-command shared-state visible to architectural queries. This is a speculative suggestion — it may be out of scope for v1.
- The `@component(idempotent=True)` pattern is now well-validated across 2 milestones. Consider documenting it as the recommended default for library/tool projects (where components are imported from multiple entry points) in the user guide.

### Questions / Open Issues

- None for this milestone. Both fixes were straightforward applications of the plan.

---

## Milestone 3 — `requires` Import Heuristic Fixes — 2026-04-01

### What Worked Well

1. **The Lark grammar extension was clean and composable.** Adding the `COLON_IMPORT` terminal and corresponding `colon_import` / `aliased_colon_import` rules to the existing `import_list` production was straightforward. The grammar's modular structure (separate entry points per field type) meant the change was isolated to the import list parsing — no risk of interfering with `name_list` or `depends_on_entry` parsing. The LALR(1) parser accepted the new rules without ambiguity conflicts.

2. **The `_FieldValueTransformer` (Lark Transformer) pattern is easy to extend.** Adding two new handler methods (`colon_import`, `aliased_colon_import`) that normalize the colon syntax into the same `{"path": ..., "alias": ..., "colon_form": True}` dict format meant no downstream changes were needed in `_parse_import_list()`. The transformer absorbs syntax variation and produces uniform output — a clean design.

3. **The emitter required zero changes.** `_requires_to_import_line()` already handles `is_from_import=True` correctly by splitting on the last dot. Both the colon syntax (`unittest.mock:patch` → `RequiresEntry(module_path="unittest.mock.patch", is_from_import=True)`) and the known-exceptions fix (`datetime.datetime` → `is_from_import=True`) flow through the emitter unchanged. This validates the separation between parsing (determines `is_from_import`) and emission (consumes it).

4. **The resolver's `_requires_local_name()` required zero changes.** Both resolver copies (in `namespaces.py` and `dependency.py`) correctly handle the new forms because the normalized `module_path` is still a dotted path. `rsplit(".", 1)[-1]` correctly extracts `"patch"` from `"unittest.mock.patch"` and `"datetime"` from `"datetime.datetime"`. VESTIGIAL_IMPORT detection works correctly with the new import forms.

5. **`idempotent=True` continues to be essential.** The parser module is imported by multiple test files; without it, `RegistrationError` would fire during test collection.

### Pain Points

1. **The `_KNOWN_FROM_IMPORTS` list is a maintenance burden.** The known-exceptions frozenset (`datetime.datetime`, `functools.wraps`, `dataclasses.dataclass`, etc.) is a hardcoded list that will need manual extension as users encounter more stdlib modules where the lowercase-last-segment heuristic fails. Examples not yet covered: `copy.copy`, `copy.deepcopy`, `json.decoder`, `logging.handlers`. The colon syntax provides an escape hatch for any case not in the list, but the heuristic should "just work" for common stdlib patterns. The list's existence is a workaround for the fundamental limitation of the capitalization heuristic — it can't distinguish "lowercase module name" (`os.path` → `import os.path`) from "lowercase function/class name" (`datetime.datetime` → `from datetime import datetime`).

2. **No `@component` kind captures "grammar extension" as an archetype.** The grammar file (`grammar.lark`) is a critical artifact but isn't registered in the s0ma self-model — it's a static file consumed by the Lark parser library. The `@component` model covers Python classes, functions, and enums, but not non-Python configuration artifacts like grammars, schemas, or templates. This is arguably out of scope for s0ma (it's a Python framework), but it means the transpiler's grammar — one of its most important architectural artifacts — is invisible to self-model queries.

### Suggestions

- **Consider a community-maintained or auto-derived `_KNOWN_FROM_IMPORTS` list.** The stdlib's `importlib.metadata` or a static analysis of `sys.stdlib_module_names` + module contents could be used to auto-generate the known-exceptions list at build time. Alternatively, document the colon syntax prominently as the recommended approach for any ambiguous import, and keep the hardcoded list minimal (only the most common stdlib patterns).
- The `idempotent=True` recommendation from all prior milestones applies again. This is milestone 3 (of the findings plan) that has needed it.

### Questions / Open Issues

- **Should `_KNOWN_FROM_IMPORTS` be user-extensible?** A project-level configuration (e.g., in `pyproject.toml` under `[tool.s0ma-dsl]`) could allow projects to add their own known from-import patterns. This would reduce reliance on the hardcoded list and the colon syntax for project-specific stdlib usage patterns. Deferring this to a future milestone as the colon syntax provides a sufficient workaround.

---

## Milestone 4 — VESTIGIAL_IMPORT False Positive Suppression — 2026-04-01

### What Worked Well

1. **The evidence-checking architecture is well-factored for extension.** The `_has_relation_evidence()` function in `dependency.py` is the single point of control for all body-evidence matching — both inline `depends_on` (Phase 4c) and standalone axon validation call the same function. This meant the CONSTRUCTS exemption and parameter-injection check each required a change in exactly one place, and both inline and standalone axon paths benefited automatically. Good separation of concerns.

2. **`ast.walk()` already traverses nested scopes correctly.** The plan asked us to verify whether `_extract_identifiers()` walked nested function bodies (e.g., `def test_*()` inside a test declaration body). It does — `ast.walk()` is a full recursive tree traversal. The existing code was already correct for this case; we added root-name extraction from attribute chains (e.g., extracting `pytest` from `pytest.mark.asyncio`) as a belt-and-suspenders safeguard, plus explicit tests confirming the behavior.

3. **`idempotent=True` continues to be essential.** Same observation as all prior milestones — the resolver module is imported by multiple test files. Without `idempotent=True`, test collection would fail with `RegistrationError`.

4. **The test helper infrastructure (`_make_nerve_with_body`, `_simple_s0ma_module`) is comprehensive.** Writing 10 new tests for three tasks required zero new helper functions — the existing test infrastructure supported every scenario (inline axons, standalone axons, test declarations with bodies, requires entries). This is a sign of good test architecture from the original Milestone 8 implementation.

### Pain Points

1. **Evidence rules conflate "structural relation" with "body-inspectable relation."** The CONSTRUCTS relation is fundamentally structural — the concrete implementation never references the abstract interface by name (this is the whole point of dependency injection). But the evidence rules in spec §4.6.3 originally treated CONSTRUCTS the same as CALLS (both require call-target evidence). We had to exempt CONSTRUCTS entirely from evidence checking, which works but feels like a spec gap rather than a transpiler design choice. The spec should acknowledge that some relation types are inherently structural and don't require body evidence.

2. **The PascalCase-to-snake_case heuristic has edge cases.** The `_pascal_to_snake()` helper handles common patterns well (`LLMAdapter` → `llm_adapter`, `HTTPClient` → `http_client`), but some naming conventions in real codebases could produce unexpected results (e.g., `OAuth2Client` → `o_auth2_client`). The colon-import syntax (MS 3) already handles import-level edge cases; the parameter-injection heuristic could benefit from a similar escape hatch if users have non-standard naming conventions. For now, the common case works and genuine edge cases will surface as user feedback.

3. **No `@component` kind for "analysis helper" functions.** The `_pascal_to_snake()`, `_extract_parameters()`, and `_extract_identifiers()` helpers are critical to the resolver's correctness but are module-private and not registered in the self-model. They're decorated with neither `@component` nor `@internal` — they're just regular private functions. The s0ma user guide recommends `@internal` for private helpers that support registered components, but applying `@internal` to every small utility function feels excessive. There's a gap between "unregistered private helper" and "intentionally unregistered with `@internal`." For library code without the import hook, this distinction is academic — but if the import hook were ever applied to s0ma-dsl, these functions would need `@internal`.

### Suggestions

- **Spec §4.6.3 should distinguish structural vs. inspectable relations.** Add a category note: CONSTRUCTS and potentially future structural relations (e.g., IMPLEMENTS, EXTENDS) are inherently exempt from body-evidence matching. The evidence rules should apply only to operational relations (CALLS, READS, CONFIGURES).
- **Consider documenting the parameter-injection pattern in the DSL spec or user guide.** The pattern where `depends_on: FooService: {relation: CALLS}` is satisfied by a constructor parameter `foo_service` is common in dependency-injection architectures. Documenting this as a recognized evidence pattern would help both human developers and coding agents understand why no VESTIGIAL_IMPORT warning is raised.

### Questions / Open Issues

- **Should `_pascal_to_snake()` matching apply to READS and CONFIGURES relations too?** Currently, parameter injection only suppresses VESTIGIAL_IMPORT for CALLS. In some architectures, dependencies are read or configured via injected parameters too (e.g., `def handler(config_store): config_store.get("key")`). The current scope is intentionally conservative, but this could be expanded if real-world usage shows false positives for READS/CONFIGURES with parameter injection.

---

## Milestone 5 — Deterministic Build Output & CLI Flags — 2026-04-01

### What Worked Well

1. **The `@component`-decorated `S0maCLI` class accommodated new CLI flags without any framework friction.** Adding `--no-cache`, `--quiet`, `--check` to the argparse subparsers required zero changes to s0ma registration. The decorator continues to be invisible at runtime, which is exactly what we want for a CLI controller that's frequently extended.

2. **`_print_diagnostics()` was already well-factored for extension.** Adding a `quiet` parameter required only a new branch in the existing function — the error/warning split and format dispatch were already cleanly separated. This is a sign that the original CLI architecture (Milestone 16 of the original plan) was designed with extensibility in mind.

3. **`idempotent=True` continues to be essential.** With 20 new test methods added across 4 new test classes, the same `@component`-decorated modules are imported repeatedly. Without `idempotent=True`, test collection would fail with `RegistrationError`. This is now confirmed across every milestone.

4. **The `BuildCache` dataclass was cleanly composable with the `--no-cache` flag.** Because `_transpile_single_file()` already accepted `cache=None` as a no-op, the `--no-cache` implementation required only a conditional in `_cmd_build()` — no changes to the cache module itself. Good API design from the original milestone.

### Pain Points

1. **IR and source map files embed absolute output paths, causing false drift positives.** The `--check` drift detection transpiles to a temporary directory and compares against existing files. However, `.s0ma.json` embeds a `"transpiled_file"` field and `.s0ma.map` embeds `"output_file"` — both containing absolute paths that naturally differ between the temp dir and the original output dir. This required path-normalization logic in `_compare_outputs()` to replace temp-dir paths with original-dir paths before comparison. This isn't a s0ma framework issue per se, but it's a design consideration for any build tool that embeds absolute paths in its artifacts: such paths make byte-for-byte comparison fragile across different output directories. A relative-path option in the IR builder would eliminate this class of comparison issues.

2. **macOS symlink indirection (`/var` -> `/private/var`) adds complexity.** Python's `tempfile.TemporaryDirectory()` returns paths under `/var/folders/...`, but `Path.resolve()` returns `/private/var/folders/...`. The drift comparison needed to handle both forms to avoid false positives. This is a platform concern, not a s0ma concern, but it's worth documenting for agents building build-tools on macOS.

3. **No `ComponentKind` value maps naturally to "CLI subcommand handler" or "pipeline stage."** The `_cmd_transpile`, `_cmd_check`, `_cmd_build` methods on `S0maCLI` are not individually registered — they're private methods of a registered SERVICE. This is correct under s0ma conventions, but it means the self-model doesn't capture the individual subcommand structure. For the transpiler, where each subcommand is a distinct pipeline with its own semantics, a finer-grained model would be useful for downstream AI tooling. This is a minor observation, not a blocking issue.

### Suggestions

- **Consider supporting relative paths in IR `"transpiled_file"` / `"source_file"` fields.** If the IR builder could emit paths relative to a project root, it would make IR files portable across output directories and simplify drift detection, CI artifact comparison, and cross-environment build reproducibility.
- **Document the macOS `/var`/`/private/var` symlink issue in the build tooling section of the PRD or user guide**, as it affects any tool doing temp-directory comparisons or path normalization.

### Questions / Open Issues

- **Should `--check` normalize the transpiler version comment by default?** Currently, `_normalize_for_comparison()` strips the version line (`Auto-generated by s0ma DSL transpiler v...`) so that upgrading the transpiler alone doesn't flag drift. This seems correct for most use cases, but some CI pipelines might want strict byte-for-byte comparison. A `--strict-check` flag could provide this, but adding it now would be speculative. Deferring until real-world usage clarifies the need.

---

## Findings 1-2, Milestone 6 — `provides` and `soft_requires` Fields — 2026-04-01

### What Worked Well

1. **Frozen dataclass field addition was seamless.** Adding `provides: tuple[str, ...] = ()` to `NerveDecl` and `soft_requires: tuple[RequiresEntry, ...] = ()` to `ModuleDecl` required no changes to existing code — the default empty tuple means every existing `NerveDecl` and `ModuleDecl` construction site remains valid. The `@dataclass(frozen=True)` + `@component` stack continues to handle incremental field additions gracefully.

2. **The `_build_requires()` parser helper was reusable for `soft_requires`.** Because `soft_requires` has the same syntax as `requires` (an import list with optional aliases and colon syntax), we could reuse the existing `_build_requires()` function directly — no new parsing logic needed. This validates the decision to factor import list parsing into a reusable helper back in Milestone 5.

3. **The four-phase resolver architecture made `soft_requires` scoping clean.** Phase 3 (external validation) only iterates `mod.module.requires`, so `soft_requires` entries are automatically excluded from package existence checks — exactly the desired semantics. Phase 4 (vestigial checking) needed explicit addition, but the pattern was a straightforward parallel to existing requires checking. The phase separation makes it easy to reason about which rules apply to which import categories.

4. **The `@component` metadata dict on nerves was trivially extensible.** Adding `provides` to the emitter's `_build_nerve_metadata()` method was a three-line addition. The existing pattern of conditionally appending fields to a dict literal is clean and predictable. No refactoring needed.

5. **`idempotent=True` continues to be essential.** With 25 new tests across 8 test classes, the same `@component`-decorated modules are imported repeatedly. Without `idempotent=True`, test collection would fail with `RegistrationError`.

### Pain Points

1. **No built-in s0ma concept for "optional dependency" or "soft import."** The `soft_requires` feature introduces a new category of import that doesn't quite fit any existing s0ma pattern. The `@component` decorator has `dependencies: list[str]` for required dependencies, but there's no `optional_dependencies` or similar field. This means the self-model can't distinguish between hard and soft dependencies at the component level — the distinction only exists at the module level via the DSL's `soft_requires` field. For downstream AI tooling that reasons about deployment requirements (e.g., "what packages do I need to run this component?"), this distinction matters.

2. **Validator body-level checks use regex, not AST parsing.** The `_extract_def_names()` helper for `provides` validation uses `re.finditer(r"\bdef\s+(\w+)\s*\(", body)` rather than `ast.parse()`. This works for well-formed bodies but could produce false positives for function names in comments or strings. The same limitation exists in the resolver's `_extract_identifiers()` and `_extract_call_targets()`. A unified AST-based body analysis pass would be more robust, but would require careful handling of partial/invalid Python in body text. The regex approach is pragmatic for v1 but worth revisiting if false positive reports surface.

3. **The `metadata` dict on `@component` is a free-form grab bag.** The emitter now puts `visibility`, `evaluates_at`, `provides`, and `raises` into a single `metadata={...}` dict. This is convenient for extensibility but means downstream consumers need to know the schema of this dict out-of-band. The s0ma framework doesn't validate or document the structure of `metadata`. For the transpiler's own needs this works, but if `provides` becomes a first-class concept in the s0ma framework (as it arguably should for SERVICE components), it should be a top-level `@component` parameter rather than a metadata field.

### Suggestions

- **Consider adding `optional_dependencies` to the `@component` decorator** for components that have soft/optional requirements. This would make the dependency graph more precise for deployment analysis and change impact assessment.
- **Consider promoting `provides` to a first-class `@component` parameter** for SERVICE-kind components. The operations a service provides are a fundamental part of its contract, not arbitrary metadata. This would enable the registry to answer questions like "which component provides the `read_file` operation?" without parsing metadata dicts.
- **Document the `metadata` dict schema conventions** in the user guide, since the transpiler now relies on specific keys (`visibility`, `evaluates_at`, `provides`, `raises`) being present. Even if the framework treats `metadata` as free-form, documenting the conventions helps downstream tooling.

### Questions / Open Issues

- **Should `soft_requires` entries be tracked in the runtime registry?** Currently, `soft_requires` entries appear in the `.s0ma.json` IR but are not registered in the s0ma runtime registry (no `register_module()` parameter for soft dependencies). If the runtime registry needs to support queries like "which modules have optional dependencies on `anthropic`?", a schema addition would be needed. Deferring until the runtime expansion milestones clarify the scope.

---

## Milestone 7 — Preserve Directory Structure in `s0ma transpile` — 2026-04-01

### What Worked Well

1. **The `_transpile_single_file()` API was cleanly decoupled from path logic.** The function accepts an `output_dir` parameter and handles all file-writing internally, which meant the fix could be applied entirely in the caller (`_cmd_transpile()` and `_cmd_build()`) without touching the core transpilation pipeline. This separation of concerns made the fix small and low-risk.

2. **The existing `_compare_outputs()` drift-detection logic already handled subdirectories correctly.** It uses `relative_to(temp_dir)` to compute relative paths, so once the temp output directory preserved subdirectory structure, the comparison logic worked without modification. This is good design — the drift checker was written against relative paths from the start, rather than assuming a flat output directory.

3. **The `_discover_s0ma_files()` helper already recursed into subdirectories.** It uses `p.rglob("*.s0ma")`, so nested `.s0ma` files were already being discovered. The bug was only in how output paths were computed, not in file discovery. This meant the fix was purely in path arithmetic, not in traversal logic.

4. **`@component` with `idempotent=True` continues to work reliably.** No registration issues despite adding new test modules with unique names. The pattern of unique module names per test is well-established and works cleanly.

### Pain Points

1. **The bug affected both `s0ma transpile` and `s0ma build` identically, but the plan only mentioned `_cmd_transpile()`.** Because `_cmd_build()` has its own loop calling `_transpile_single_file()` with the same flat `output_dir`, the same directory-flattening bug existed there. The findings document and implementation plan only referenced `_cmd_transpile()`, which could have led an agent to fix one path and miss the other. Both commands needed identical fixes. This is a documentation gap in the findings, not in s0ma itself, but it highlights a risk: when the same pattern is duplicated across commands, findings should explicitly enumerate all affected call sites.

2. **The `--check` mode's `original_dir` fallback was fragile for nested inputs.** When no `--output-dir` was specified, check mode fell back to `s0ma_files[0].parent` — the parent directory of the first discovered file. For nested structures (e.g., `src/domain/models.s0ma`), this would point to `src/domain/` rather than `src/`, breaking the relative path comparison for files in other subdirectories. The fix required changing the fallback to use the input root when it's a directory.

### Suggestions

- **Consider centralizing the "per-file output directory" computation.** Currently, both `_cmd_transpile()` and `_cmd_build()` need to call `_resolve_output_dir()` in their loops. If a third command (e.g., a future `s0ma watch`) also transpiles files, it would need the same logic. A higher-level helper like `_transpile_directory()` that wraps the file loop and output-dir resolution could reduce duplication.
- **The `_compare_outputs()` function's robustness with relative paths is worth documenting** as a pattern. Its approach of resolving symlinks and normalizing temp-dir references is non-obvious but essential for macOS (where `/var` is a symlink to `/private/var`). Other s0ma tooling that compares file outputs across directories should follow the same pattern.

### Questions / Open Issues

- **Should `s0ma build` output a `__init__.py` in created subdirectories?** When the fix creates subdirectories like `out/domain/` and `out/infra/`, Python won't treat them as packages unless `__init__.py` files are present. The transpiler currently doesn't emit these. Whether it should depends on whether the output directory is meant to be a Python package hierarchy or just a file mirror. This is a broader design question for the output model, not specific to this milestone's fix.

---

## Milestone 8 — CLASS Bodies for SERVICE/ADAPTER Nerves — 2026-04-01

### What Worked Well

1. **The body validation architecture was cleanly extensible.** The `_validate_nerve_body()` function in `body_extractor.py` already received `kind` as a parameter in the parent `validate_body()` call — it just wasn't being passed through. The fix was a single parameter addition to the inner function and one line change at the call site. The separation between body extraction (`extract_body`) and body validation (`validate_body`) meant the extraction logic needed zero changes — only the validation rules changed.

2. **The `BodyType` enum and `BodyInfo` dataclass were already complete.** The body extractor already classified class bodies as `BodyType.CLASS` and populated the `class_name` field on `BodyInfo`. This meant the emitter could detect class bodies reliably without any parser changes. The existing AST-based classification (`_classify_body`) was robust and required no modifications.

3. **The `_emit_nerve()` refactoring into `_emit_function_nerve()` and `_emit_class_nerve()` was clean.** The original `_emit_nerve()` was a single method that mixed decorator construction with body emission. Extracting the decorator parameter construction into `_build_nerve_decorator_params()` eliminated duplication between the function and class paths. Both code paths now share the same decorator logic, differing only in how the body is wrapped.

4. **The dict-compatible factory wrapper preserves backward compatibility.** The emitted code pattern — implementation class renamed to `_<Name>Impl`, factory function with `@component` decorator returning a dict of bound methods — maintains the existing `service["method"](args)` calling convention. Tests that use this pattern will continue to work unchanged. The `provides` field (from MS 6) integrates naturally: if declared, the dict uses those specific methods; otherwise, public methods are auto-detected from the class AST.

5. **The `provides` field validation (from MS 6) works seamlessly with class bodies.** Since `_extract_def_names()` already uses regex to find `def` names in body text, and class methods are `def` statements, the existing `_check_provides_fields()` validation correctly checks class method names against the `provides` list without modification.

### Pain Points

1. **The `class_in_nerve.s0ma` invalid fixture needed updating.** The existing negative test fixture used `kind: SERVICE` with a class body, which was exactly the case we were now legalizing. The fixture needed to be changed to `kind: FUNCTION` to remain a valid negative test. This was easy to miss — the full test suite caught it, but an agent working only with the body extractor and codegen tests would have seen all-green and missed the 5 failures in `test_golden.py` and `test_error_ux.py`. This highlights that **invalid fixtures are as important as valid ones** and should be listed in the milestone's "Files to Load" section.

2. **The emitter has no access to `BodyInfo` — only raw body text.** The `NerveDecl` stores the body as a raw string, not as a `BodyInfo`. This means the emitter must re-detect the body type by inspecting the text. I used a simple `_is_class_body()` helper that checks whether the first non-blank, non-comment line starts with `class `, which is reliable because the body has already been validated by the parser. However, a cleaner architecture would store `BodyType` on the AST node so downstream consumers don't need to re-classify. This is a minor structural debt — the current approach works, but if more body-type-dependent emission logic is added in the future, it would be worth adding `body_type: BodyType` to `NerveDecl`.

3. **Extracting `__init__` parameters for the factory function requires AST parsing.** The factory function needs to forward `__init__` parameters (e.g., `def MyService(db, cache):` → `_MyServiceImpl(db, cache)`). This required writing `_extract_init_params()`, a non-trivial helper that handles positional args, defaults, type annotations, `*args`, and `**kwargs`. The Python `ast` module made this tractable, but the function is ~40 lines and handles multiple edge cases. If the `__init__` has no parameters, the factory falls back to `*args, **kwargs`.

4. **The error message for `CLASS_BODY_IN_NERVE` needed updating.** The old message said "nerve bodies must be function definitions" unconditionally. The new message needs to be kind-aware: "only SERVICE and ADAPTER nerves may use class bodies." The `context` dict in the error also now includes `class_allowed_kinds` so coding agents can see exactly which kinds permit class bodies.

### Suggestions

- **Consider adding `body_type: BodyType | None` to `NerveDecl`** (and other declaration nodes). This would eliminate the need for the emitter and other downstream consumers to re-detect the body type from raw text. The parser already knows the body type at extraction time — it's discarded after validation.
- **Consider a valid fixture for class-body SERVICE nerves.** The existing fixture corpus tests class bodies only in the negative case (rejection for FUNCTION nerves). A positive fixture showing a SERVICE nerve with a class body, `provides` field, and the generated factory wrapper would serve as executable documentation for this pattern.
- **The plan's suggestion of a `class_style: "dict" | "object"` metadata field** is worth implementing in a future milestone. The current implementation always generates the dict wrapper. An `"object"` style that skips the wrapper and lets class-based nerves use `service.method(args)` calling convention would be useful for projects that don't need backward compatibility with the dict pattern.

### Questions / Open Issues

- **Should the `@component` decorator go on the implementation class or the factory function?** The current implementation puts `@component` on the factory function, since the factory is the public-facing entity with the component's name. The implementation class is prefixed with `_` and is not registered. An alternative would be to register the implementation class and have the factory be unregistered. The current approach is more consistent with function-based nerves (where the function IS the component), but the alternative would give the registry access to the actual class structure.
- **How should class-body nerves interact with derived edge analysis?** `TYPE_USES` edges are derived from function signature annotations. For class bodies, should the transpiler also analyze `__init__` parameter annotations and method return types? This is deferred to MS 9's derived edge improvements but should be tracked.

---

## Milestone 9 — Derived Edge & Axon Improvements — 2026-04-01

### What Worked Well

1. **The `_derive_type_uses_edges()` method was cleanly extensible for constructor calls.** The existing architecture — collecting candidate names, resolving them against the namespace, and deduplicating — accommodated the new `_extract_constructor_type_uses()` source with minimal changes. The new source simply feeds additional names into the same deduplication/resolution pipeline. No new data structures or control flow were needed.

2. **The `_collect_cell_names()` approach (constructable kinds only) avoids false positives.** By restricting constructor-based TYPE_USES to MODEL, EXCEPTION, ENUM, and CONFIG cell kinds, CONSTANT and TYPE cells (which are not constructable) are excluded. This matches real-world usage: `ToolParameter(name="file")` is a legitimate constructor call, but `MAX_SIZE()` on a CONSTANT cell is not.

3. **Adding PRODUCES and CONSUMES to the `Relation` enum was low-friction.** The enum's `is_authored()` / `is_derived()` classification, the grammar's `RELATION` terminal, the validator's relation-type checks, and the resolver's evidence rules all use the same enum. Adding two new values required touching each exactly once. The architecture of a single enum with `_AUTHORED_RELATIONS` / `_DERIVED_RELATIONS` frozensets makes extension straightforward.

4. **The evidence rules for PRODUCES and CONSUMES are well-aligned with existing patterns.** PRODUCES uses the same `_extract_call_targets()` + `_extract_identifiers()` helpers that CALLS already uses (producing an event is typically a constructor call or return). CONSUMES uses `_extract_identifiers()` like READS/CONFIGURES (consuming an event typically means receiving it as a parameter or checking it with `isinstance`). No new AST extraction helpers were needed.

5. **The golden test infrastructure caught the `constructor_call` origin immediately.** The `test_ir_edge_origin_tags` test in `test_golden.py` validates that all derived edge origin strings belong to an expected set. When the new `constructor_call` origin appeared, the test failed with a clear message. This is excellent design — origin tags are a semantic contract, and the golden test enforces it. One line addition to the valid set fixed it.

### Pain Points

1. **The `origin` field on `DerivedEdge` creates a branching concern for consumers.** The existing origins were `raises_field` and `function_signature`. Adding `constructor_call` means any downstream consumer that switches on origin (IR builder, graph emitter, etc.) must be updated. In this case the IR builder serializes origin as a string so no changes were needed there, but the golden test's allowlist broke. As more derivation sources are added (e.g., class body analysis from MS 8's question), the origin set will grow. Consider whether origins should be an enum rather than free-form strings to make exhaustiveness checking automatic.

2. **The deduplication strategy for overlapping annotation and constructor sources is subtle.** When a cell appears in both a function annotation (`def f(x: Foo)`) and a constructor call (`Foo()`), only one TYPE_USES edge is emitted. The origin is set to `function_signature` when the name comes from both sources (annotations take precedence). This precedence rule is implicit in the code ordering and could be surprising to consumers who expect `constructor_call` origin for something they only see as a constructor call. The current behavior is correct but the precedence rule should be documented.

3. **The plan's evidence rules for PRODUCES were slightly ambiguous.** The plan says "target name appears in a constructor call or return value (creating the event)." The return-value check is tricky — you'd need to trace what the function returns and match it against the target type. The simpler approach implemented here (target appears as any identifier, which covers both constructor calls and variable references to the produced type) is sufficient and avoids fragile return-value analysis.

### Suggestions

- **Consider making `DerivedEdge.origin` an enum** rather than a free-form string. As more derivation sources are added across milestones, the string-based approach risks inconsistency. An enum would provide exhaustiveness checking in tests and downstream consumers.
- **The MS 8 open issue about class-body derived edges is now partially addressed.** Constructor calls in class-body nerves will produce TYPE_USES edges (since the body scanning walks all nested scopes). However, `__init__` parameter annotations and method return types are still only captured if the methods have function signatures. A future enhancement could explicitly analyze class body method signatures for annotation-based TYPE_USES.
- **The PRODUCES/CONSUMES evidence rules could benefit from a dedicated test fixture.** A `.s0ma` fixture demonstrating an event-driven pattern (producer → event cell → consumer) would serve as executable documentation for the new relation types and validate the full pipeline (parse → validate → resolve → emit IR).

### Questions / Open Issues

- **Should PRODUCES evidence also check return type annotations?** Currently, `PRODUCES` looks for the target in identifiers and call targets. A stronger check would inspect the function's return annotation for the target type (e.g., `-> DomainEvent`). This would catch cases where the event is produced but the body only references it implicitly via the return type. The current approach is intentionally permissive.
- **Should CONSUMES be exempt from evidence like CONSTRUCTS?** The plan's evidence rules say CONSUMES needs a name reference. But in some dependency-injection patterns, the consumer receives the event as a parameter whose name doesn't match the cell name (e.g., `event: DomainEvent` vs `event_data`). The parameter injection pattern (snake_case conversion) from MS 4 doesn't apply here since CONSUMES isn't CALLS. This could produce false VESTIGIAL_IMPORT warnings in some patterns.

---

## Milestone 10 — `--include` Flag and Cross-Module Build Improvements — 2026-04-01

### What Worked Well

1. **The existing architecture made `--include` straightforward to implement.** The `_discover_s0ma_files()` helper, the `module_dict` / `module_filenames` pattern, and the `resolve_dependencies()` interface all support the context-module concept without API changes. Context modules are simply additional entries in `module_dict` that participate in resolution but are excluded from transpilation. The separation of discovery → parse → resolve → transpile is clean enough that inserting context modules between discovery and resolution required no refactoring.

2. **The `_extract_def_names()` helper (from MS 9's `provides` validation) was directly reusable for HELPER_NAME_COLLISION.** The function-name extraction regex was already factored out as a module-level utility. Adding the test-body collision check was a ~50-line method that delegates to the same helper. This is a good example of the validator's composable design paying off.

3. **The `@component` decorator continued to be zero-friction.** No new components were added in this milestone (changes were to existing CLI and validator components), but the existing `@component`-decorated `S0maCLI` and `IntraModuleValidator` classes accepted the new methods without any decorator-related issues. The `idempotent=True` flag continued to prevent test-import conflicts.

4. **The diagnostic infrastructure (S0maError, severity-based filtering, structured output) handled the new MODULE_NAME_COLLISION error and HELPER_NAME_COLLISION warning without modification.** Creating a new error code is as simple as constructing a `S0maError` or `S0maSemanticError` with the new code string — no registration, no enum extension needed. The severity-based filtering (`error` vs `warning`) automatically routes them correctly through `_print_diagnostics()`, `_split_diagnostics()`, and JSON output.

### Pain Points

1. **Single-module dev-mode builds skip cross-module resolution.** The `_cmd_build()` and `_cmd_check()` methods gate resolution on `len(modules) > 1 or mode == StrictnessMode.RELEASE`. This means `s0ma build tests/` with a single test module that has `uses:` references will succeed silently in dev mode — the dangling reference is never checked. While this is by design (dev mode is lenient), it creates a confusing experience when the user expects `--include` to solve their DOES_NOT_EXIST errors but doesn't see errors without it either. The fix is to run resolution when any module has `uses:` entries, regardless of module count. This could be a future enhancement.

2. **`module_dict` is overloaded for both resolution scope and transpilation scope.** Before `--include`, these were identical. Now they diverge: `module_dict` includes context modules, but only `target_names` should be transpiled. The current approach uses a parallel `target_names` set to track which modules are targets. This works but means the "which modules get transpiled" logic is distributed across two data structures. A clearer approach would be a tagged data structure (e.g., each module has a `is_target: bool` flag), but the current approach is sufficient for v1.

3. **The output-dir mismatch info message needed careful interaction with `--quiet` mode.** The initial implementation printed the info message unconditionally, breaking the `test_quiet_transpile_shows_summary` test because it asserted the output dir path wouldn't appear in quiet output. This is a minor example of feature interaction — new informational output must respect all existing output-control flags. The fix was a single `not quiet` guard, but it's a reminder to check all output modes when adding new messages.

### Suggestions

- **Consider adding a `--include` flag to `s0ma transpile` as well.** Currently `s0ma transpile` has no cross-module resolution, but for consistency and to avoid the "must use `s0ma build` for validated transpilation" friction, it would be natural to add `--include` there too. The transpile command would still skip Phases 2-4, but the include modules could at least populate the module dict for any future per-file resolution.
- **Document the `--include` pattern in the s0ma user guide or DSL spec.** The "double bind" problem (tests can't reference source modules during build) will affect every non-trivial s0ma project. A standard workflow section showing `s0ma build src/ && s0ma build tests/ --include src/` would help new adopters.
- **Consider a project-level config file (e.g., `s0ma.toml`) that specifies default include paths.** Repeatedly typing `--include src/fr3d/` is error-prone and doesn't compose well with CI scripts. A `[build] include = ["src/fr3d/"]` config would eliminate this boilerplate.

### Questions / Open Issues

- **Should context module validation errors block target transpilation?** Currently, errors in context modules (from `--include`) are reported and block transpilation (they go into `all_diagnostics` alongside target errors). The plan says context validation errors should be reported but "do NOT block transpilation of targets for *warnings* in context modules." The current implementation is more conservative — all errors in all modules block. This seems correct for errors (a broken context module means broken resolution), but warnings in context modules arguably shouldn't block target transpilation. This distinction is not yet implemented.
- **Should `MODULE_NAME_COLLISION` be a warning in dev mode instead of an error?** Some workflows might intentionally override a source module name in tests (e.g., a mock module). The current implementation always errors on collision, which is the safer default.

---

## Milestone 11 — Abstract Interface & `returns` Metadata — 2026-04-01

### What Worked Well

1. **The parser's field-based architecture made adding new nerve fields trivial.** Adding `abstract`, `interface`, and `returns` required no grammar changes — all three use the existing `_RawDeclaration.fields` dict and the existing `_parse_name_list()` / new `_parse_bool_field()` helpers. The parser's Phase 1 (line-based declaration splitter) treats all `key: value` lines uniformly, so new fields are parsed automatically; only Phase 2 (typed AST construction in `_build_nerve()`) needs explicit handling. This is an elegant extension point.

2. **The validator's composable design continued to pay off.** Adding two new validation methods (`_check_abstract_fields`, `_check_returns_fields`) was straightforward — each is a self-contained method that's added to the `validate()` orchestrator with a single line. The existing `_extract_def_names()` helper was directly reusable for the abstract interface check. The new `_extract_return_dict_keys()` helper follows the same module-level function pattern.

3. **The `@component` decorator remained invisible.** No decorator-related issues at all. The `idempotent=True` flag continues to prevent test-import conflicts across all 1253 tests. Adding new fields to frozen dataclasses (`NerveDecl`) didn't require any decorator adjustments — the decorator correctly handles the updated `__init__` signatures without intervention.

4. **The metadata dict pattern in `_build_nerve_metadata()` is a clean extension point.** Adding new fields to the `metadata` dict emitted in `@component(metadata={...})` is as simple as appending conditional items to a list. The pattern `if nerve.field: items.append(...)` makes it easy to add optional fields without affecting nerves that don't use them.

5. **The IR builder's `fields` dict pattern is equally extensible.** The `IRComponent.fields` dict is an untyped `dict` that accepts any JSON-serializable value. This means new nerve-level metadata (`abstract`, `interface`, `returns`) can be added without changing the `IRComponent` dataclass or its `to_dict()` method. The trade-off is loss of type safety, but the flexibility is appropriate for an evolving schema.

### Pain Points

1. **No `_parse_bool_field()` existed before this milestone.** The parser had `_parse_int_field()` and `_parse_string_field()` but no boolean parser. This is a minor gap — boolean fields are common enough in DSLs that a built-in parser helper should have been scaffolded earlier. The addition was trivial (~12 lines), but the gap suggests that the parser's helper suite was grown reactively rather than being designed upfront for the full range of field types the DSL might need.

2. **Body-delimiter conventions in tests are easy to get wrong.** The `.s0ma` body syntax uses a single opening `---` separator, and the body runs until the next declaration header or EOF. There is no closing `---`. This tripped up test authoring initially (closing `---` gets captured as body content and causes Python syntax errors). A quick reference card or explicit "body capture rules" section in the DSL documentation would prevent this recurring confusion for agent authors.

3. **The `returns` validation relies on regex-based return-dict key extraction.** The `_extract_return_dict_keys()` helper uses `re.search(r'\breturn\s*\{', body)` to find return-dict patterns and then extracts quoted keys. This works for the idiomatic dict-of-functions pattern (`return {"key": fn, ...}`) but cannot handle computed keys, variable-based dicts, or multi-return-statement bodies. A proper AST-based analysis (using Python's `ast` module to walk `ast.Return` → `ast.Dict` → `ast.Constant` keys) would be more robust, but the regex approach is pragmatic for v1 since the dict-of-functions pattern is highly uniform across s0ma projects.

4. **Cross-module abstract interface validation is not yet implemented.** The plan mentions validating that a concrete nerve with `depends_on: {relation: CONSTRUCTS}` targeting an abstract nerve implements all interface methods. The current implementation only checks this for abstract nerves *within the same module*. Cross-module validation (where the abstract nerve is in a different `.s0ma` file) would require the dependency resolver to carry `interface` metadata from context modules. This is deferred and should be addressed when cross-module resolution is enhanced.

### Suggestions

- **Add a `_parse_bool_field()` alongside `_parse_int_field()` during initial parser scaffolding.** Boolean fields are inevitable in DSL design; having the helper ready from the start saves time and prevents inconsistent parsing approaches.
- **Document the body-delimiter convention explicitly.** A sentence in the DSL quick reference: "Bodies begin after a `---` line and end at the next declaration header or end of file. There is no closing `---` delimiter." would prevent repeated confusion.
- **Consider AST-based return-dict key extraction as a v2 improvement.** The regex approach works for the current idiomatic patterns, but as the DSL matures and users write more complex bodies, AST-based analysis would catch a broader range of patterns.
- **The `metadata` dict in `@component()` is growing.** With `visibility`, `evaluates_at`, `provides`, `returns`, `raises`, `abstract`, and `interface` all packed into a flat dict, the metadata is becoming a significant part of the decorator call. Consider whether s0ma should support structured metadata (e.g., `metadata=NerveMetadata(abstract=True, interface=[...])`) or at least document which metadata keys are "well-known" and used by framework tooling vs. user-defined.

### Questions / Open Issues

- **Should `abstract: true` be restricted to specific nerve kinds?** Currently, any nerve kind can be marked abstract. In practice, abstract nerves are ADAPTER or SERVICE nerves (like `LLMAdapter`, `MessageGateway`). Should the validator enforce that only ADAPTER/SERVICE nerves can be abstract? The current implementation is permissive.
- **Should `returns` validation be mandatory in release mode?** Currently, `returns` validation is best-effort (only checks if a return-dict pattern is found). In release mode, it might be appropriate to require that every nerve declaring `returns` must have a body with a verifiable return-dict pattern.

---

## Milestone 5b — Checksum Embedding for Drift Detection — 2026-04-01

### What Worked Well

- **`@component` decorator on the `inject_hashes()` utility was not needed.** The function is a pure module-level utility (stateless, no registration concerns) and lives alongside the emitter. The decorator pattern works best on components with identity and intent; pure helper functions don't need registration overhead. This is a good boundary — s0ma's model doesn't force registration on everything, just on architecturally meaningful components.
- **The existing `compute_content_hash()` function (already `@component`-decorated) provided the right pattern to follow.** Having an existing hash utility in `ir/builder.py` made it easy to understand the project convention (SHA-256, `sha256:` prefix format). The new hash embedding uses truncated hashes (16 hex chars) since this is drift detection, not security, but the prefix convention carries over.
- **The `IRDocument` frozen dataclass extended cleanly.** Adding `source_hash` as a new field to `IRDocument` (a `@dataclass(frozen=True)` with `@component`) was straightforward. The frozen constraint didn't cause any issues with the new field since the dataclass constructor handles it. The `to_dict()` method's sorted-keys pattern made adding the new field deterministic.

### Pain Points

1. **No `hashlib` import in `python_emitter.py` by default.** The emitter module didn't import `hashlib`, which is needed for the hash computation. This is expected (the module had no hashing responsibility before), but it's a reminder that new cross-cutting features (like drift detection) often require touching import sections across multiple files. s0ma's import model (`requires` in `.s0ma` files) would make this explicit at the DSL level — a good validation that the DSL approach catches what Python silently allows.

2. **The `_normalize_for_comparison()` function in `cli/main.py` needed updating to exclude hash lines.** This is a coupling issue: the `--check` drift detection (MS 5) and the checksum-based drift detection (MS 5b) use different mechanisms but must agree on what counts as "meaningful" content. Adding the hash exclusion regex is simple, but it's a case where two related features need coordinated normalization rules. A single "transpiler-generated metadata" exclusion list would be more maintainable than separate regexes.

3. **Frozen `IRDocument` required updating all call sites.** Adding `source_hash` to `IRDocument` (a positional field in a frozen dataclass) broke one existing test that constructed `IRDocument` directly. Since `source_hash` has no sensible default (empty string would be misleading), making it required is correct, but it highlights the trade-off of frozen dataclasses: they're safe but every field addition is a breaking change for constructors.

### Suggestions

- **Consider a `TranspilerMetadataLines` constant** that lists all regex patterns for lines that should be excluded from drift comparison. Both `_normalize_for_comparison()` and `inject_hashes()` use similar patterns; centralizing would prevent drift between the two normalization approaches.
- **The `s0ma verify` command could be integrated into CI pipelines.** A `pre-commit` hook or CI step running `s0ma verify` would catch `.py` drift before it accumulates. Consider documenting this workflow pattern in the user guide.
- **The truncated hash (16 hex chars / 64 bits) is appropriate for drift detection** but should be documented as non-cryptographic. If future s0ma features need integrity guarantees (e.g., supply chain verification), the full hash from `content_hash` in the IR module block would be the right choice.

### Questions / Open Issues

- **Should `s0ma verify` also check `.s0ma.map` files?** Currently it checks `.py` (source + output hashes) and `.s0ma.json` (source hash). Source maps could also go stale, but they're less commonly consumed directly. Deferring this for now.

---

## Milestone 11b — Cross-Module Abstract Interface Validation — 2026-04-01

### What Worked Well

- **Importing `_extract_def_names()` from `validator.py` into `resolver/dependency.py` caused no circular import.** The dependency graph is `resolver` -> `validator` (via a lazy import inside the method), and `validator` does not import from `resolver`. This is a clean cross-module utility reuse pattern that s0ma's architecture supports well — the function is a pure utility with no registration side effects.
- **The existing `_validate_standalone_axons_cross_module()` method provided an excellent template.** The pattern of iterating over modules, checking standalone axons, resolving targets, and building error diagnostics with context dicts was directly reusable. The new method follows the same structure, making the codebase consistent.
- **The `resolve()` method's phased architecture made insertion clean.** Adding the cross-module abstract validation as a new phase (after standalone axon validation, before release-mode checks) was a single `errors.extend()` call. The phase-based architecture is well-designed for additive feature work.

### Pain Points

1. **Target resolution for standalone axons requires multi-step lookup.** A standalone axon's target can be a bare name (from a `uses` alias), a qualified name (`adapters.LLMAdapter`), or a module-scoped name. The validation method needed to try multiple resolution strategies: direct nerve index lookup, uses-alias resolution, and qualified-name decomposition. This logic partially duplicates what `NamespaceService` already does for the semantic validator. A shared "resolve cross-module target to NerveDecl" utility would reduce duplication.

2. **The intra-module vs. cross-module validation split requires coordination.** The semantic validator handles intra-module CONSTRUCTS abstract validation, and the resolver handles cross-module. Both use the same error code (`MISSING_INTERFACE_METHODS`) and similar diagnostic structure, but they run at different pipeline stages. If a user moves an abstract nerve from intra-module to cross-module (or vice versa), the validation source changes silently. This split is architecturally correct (single-module vs. multi-module contexts) but could confuse users debugging validation failures.

3. **The `metadata` dict in `@component()` continues to grow.** With MS 11's `abstract` and `interface` fields, and MS 11b's cross-module validation of those fields, the metadata dictionary passed to `@component()` now contains: `visibility`, `evaluates_at`, `provides`, `returns`, `raises`, `abstract`, `interface`, and potentially more. This is becoming a substantial metadata surface area. The s0ma framework treats `metadata` as an opaque `dict[str, Any]`, which is flexible but means framework tooling can't validate metadata keys at registration time.

### Suggestions

- **Consider a `resolve_nerve_reference()` utility** that encapsulates the multi-step target resolution logic (bare name, alias, qualified name) for both the standalone axon validator and the abstract interface validator. This would live in `resolver/namespaces.py` or a new `resolver/utils.py`.
- **Document the validation responsibility split.** A brief note in the resolver module docstring: "Intra-module abstract interface validation is handled by `IntraModuleValidator._check_abstract_fields()`. Cross-module validation is handled here." This prevents future developers from adding duplicate checks.
- **Consider structured metadata for well-known keys.** As the `metadata` dict grows, s0ma could define a `NerveMetadata` dataclass (or similar) that validates well-known keys (`abstract`, `interface`, `provides`, `returns`) at registration time, while still allowing arbitrary `extra` keys for user-defined metadata. This would catch typos (e.g., `abstact: true`) that the current opaque dict silently accepts.

### Questions / Open Issues

- **Should cross-module abstract validation also check inline `depends_on` with qualified targets?** The plan mentions this case (e.g., `depends_on: {target: "adapters.LLMAdapter", relation: CONSTRUCTS}`), but inline `depends_on` targets are typically unqualified (intra-module). If qualified targets in inline depends_on are a valid pattern, the resolver should handle them too. Currently deferred since the grammar enforces that inline targets are bare names.
- **Should the resolver skip validation if Phase 2 already reported DOES_NOT_EXIST for the target module?** Currently, the abstract validation will simply fail to find the target in `nerve_index` and skip silently. This is correct behavior but might mask cases where the abstract nerve was removed. The existing Phase 2 error is sufficient for diagnostics.

---

## Milestone 12 — New CLI Commands — 2026-04-01

### What Worked Well

- **The existing CLI architecture extended cleanly.** Adding three new subcommands (`new`, `test`, `test-conftest`) to `S0maCLI` required only: (1) adding parser entries in `build_parser()`, (2) adding dispatch entries in `run()`, and (3) implementing the handler methods. The dispatch-table pattern (`dict[str, handler]`) in `run()` scales well. s0ma's `@component` decorator on `S0maCLI` didn't interfere with any of this.
- **The `_parse_single_file()` utility was reusable for validation.** The `s0ma new` command validates its generated output by calling `_parse_single_file()` — the same function used by `check`, `build`, and `transpile`. This is a good example of internal reuse without needing new abstractions.
- **The `_discover_s0ma_files()` utility worked as-is for all three commands.** File discovery for `test` and `test-conftest` used the same utility that `build` and `check` already use.
- **Composing `s0ma test` on top of `s0ma build` via `self.run()` was straightforward.** Rather than re-implementing the transpilation pipeline, `_cmd_test` delegates to the existing `build` command with `--no-cache`, then runs pytest. This avoids duplication and keeps the test command behavior consistent with the build command.

### Pain Points

1. **Enum values from AST nodes need string conversion for display.** The `_cmd_test_conftest` method collects `kind` and `layer` values from parsed modules. These are enum instances (e.g., `Kind.SERVICE`, `Layer.DOMAIN`), which don't sort with `<` and don't display cleanly as strings without using `.name`. Python enums that define `__str__` as the repr (e.g., `Kind.SERVICE`) rather than just the name value create a small friction point. For s0ma's types (`ComponentKind`, `Layer`), the string representation is well-designed (just the value), but the DSL's internal `Kind` and `Layer` enums use the default Python repr. This is a minor inconsistency between framework and DSL enum conventions.

2. **The `build` command creates `__s0ma_cache__/` by default, which conflicts with pytest collection.** When `s0ma test` delegates to `s0ma build`, the cache directory creates duplicate `.py` files that confuse pytest's module collection (`import file mismatch` error). The fix is `--no-cache`, but this is a sharp edge: any user who manually runs `s0ma build` followed by `pytest` on the same directory will hit this. Consider adding `__s0ma_cache__/` to a default `.gitignore` pattern and/or documenting this interaction.

3. **Scaffolding templates are string-based, not grammar-aware.** The `_scaffold_template()` function generates `.s0ma` text by concatenating f-strings. This works but means the template structure is maintained separately from the grammar. If the grammar changes (e.g., a new required field), the templates will silently generate invalid files until someone updates them. The validation step (`_parse_single_file` on the output) catches this at generation time, which is the right safety net, but the templates could still produce confusing error messages if the grammar evolves.

### Suggestions

- **Consider using the grammar's own validation to define "minimum viable" templates.** Rather than hard-coding template strings, a template could be a minimal valid `.s0ma` fixture that the scaffolder reads, performs name/layer substitution on, and writes out. This would make template maintenance grammar-aware.
- **Document the `s0ma test` workflow end-to-end.** Users will want to know: (1) create test `.s0ma` files, (2) run `s0ma test tests/ --source src/myproject/`, (3) transpiled `.py` files appear in the test directory, (4) pytest runs on those `.py` files. The `--source` flag for cross-module resolution is important but not obvious from the help text alone.
- **The conftest generator currently mocks `component` and `register_module`.** If s0ma adds more registration entry points (e.g., for ganglia or specialized decorators), the conftest will need updating. Consider having the conftest mock at a higher level (e.g., a single `s0ma.initialize()` mock that sets up lenient mode) to be more resilient to framework changes.

### Questions / Open Issues

- **Should `s0ma new` support `ganglion` and `axon` types?** The plan specifies `module`, `nerve`, `cell`, and `test`. Ganglia and standalone axons are less commonly scaffolded, but completeness might justify adding them later.
- **Should `s0ma test` generate a conftest automatically if none exists?** Currently, `s0ma test` and `s0ma test-conftest` are separate commands. An `--auto-conftest` flag on `s0ma test` could detect whether a conftest is needed and generate one, reducing the number of steps for new users.

---

## Milestone 13 — Documentation Additions — 2026-04-01

### What Worked Well

- **The codebase is well-structured for documentation extraction.** Documenting the `requires` heuristic was straightforward because the three-tier logic (colon override → known-exceptions → capitalization) is cleanly separated in `_build_requires()` and `_KNOWN_FROM_IMPORTS`. The code is self-documenting enough that the patterns guide could be written directly from the source without ambiguity.
- **The emitter's class-nerve and function-nerve split (MS 8) maps cleanly to a two-pattern documentation structure.** The `_emit_class_nerve` / `_emit_function_nerve` distinction in the emitter corresponds exactly to the two SERVICE patterns users need to learn. The transpiler's internal architecture mirrors the mental model users should have.
- **The test emission pattern (module-scoped) and the `HELPER_NAME_COLLISION` warning (validator) form a coherent story.** The behavior (module scope) and the safety net (collision warning) were both already implemented — the documentation just needed to explain what was already enforced.
- **The abstract nerve pattern (MS 11) with `NotImplementedError` stubs is elegant and easy to document.** The `_generate_abstract_stub` function is only 8 lines, yet it covers the full abstract adapter convention. The simplicity of the implementation made for clear documentation.

### Pain Points

1. **Several patterns required cross-referencing 3+ source files to document accurately.** For example, documenting the `raises` + `uses` relationship required reading: (a) the parser's `_build_requires` to confirm `raises` doesn't generate imports, (b) the derived edge analyzer to confirm it generates RAISES edges, (c) the emitter to confirm the edge appears in IR but not in import statements, and (d) the validator to confirm `raises` entries must be s0ma cells. No single file tells the complete story. This is architecturally sound (separation of concerns), but it means documentation must be maintained separately from the implementation — exactly the kind of drift s0ma is designed to prevent.

2. **The quick reference had a stale constraint: "body must be `def`, never `class`" for nerves.** This was accurate before MS 8 added class body support for SERVICE/ADAPTER nerves. Documentation-as-code would have caught this drift — the quick reference is a plain markdown file with no validation against the actual grammar or emitter capabilities. This is a concrete example of documentation drift that s0ma's philosophy is meant to prevent, but the quick reference itself sits outside the s0ma-described system.

3. **The `raises` field's "metadata only, does NOT import" semantics are a frequent source of confusion (findings 1.1, 1.3, 3.2, 7.2) but there was no single place documenting this.** The information was scattered across feedback entries and code comments. Centralizing it in the patterns guide should help, but the repeated confusion across multiple milestones suggests the semantics may be counterintuitive enough to warrant a compile-time hint when `raises` references a cell from another module without a corresponding `uses` entry.

### Suggestions

- **Consider a compile-time note when `raises` references a cross-module cell without a `uses` entry.** Something like: `NOTE: raises: [errors.MyError] is metadata only — add errors.MyError to module uses if you need the import.` This would reduce the most common confusion point without changing semantics.
- **Consider adding a `--validate-docs` command or hook that checks quick reference examples against the actual grammar.** The stale "never `class`" constraint could have been caught automatically if the quick reference examples were parsed as part of the test suite.
- **The known-exceptions list (`_KNOWN_FROM_IMPORTS`) should be documented as extensible via configuration.** Currently it's hard-coded. If a project uses a third-party library where the capitalization heuristic fails (e.g., `sqlalchemy.orm:Session`), the only workaround is the colon override syntax. This is fine, but worth calling out explicitly so users don't wonder why some stdlib imports "just work" while third-party ones need the colon.
- **The patterns guide would benefit from being generated or validated from source.** For a framework whose core premise is "code and description are inseparable" (P9), having a hand-written patterns guide that can drift from the implementation is an ironic gap. Consider generating at least the known-exceptions table and the kind-mapping table from the actual source constants.

### Questions / Open Issues

- **Should the patterns guide live in `docs/reference/` or at the top level of `docs/`?** The `reference/` subdirectory was empty before this milestone. Using it establishes a convention for reference material, but it's one level deeper than other documentation. The choice is consistent (reference material goes in `reference/`), but worth confirming.
- **Integration test coverage for documentation examples.** The patterns guide contains ~20 `.s0ma` code examples. Should these be extracted and validated as part of the test suite? This would prevent documentation drift but adds maintenance overhead for a documentation-only artifact.
