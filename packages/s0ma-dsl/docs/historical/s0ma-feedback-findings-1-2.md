# s0ma-dsl Feedback Findings & Recommended Updates

Synthesized from the fr3d rebuild experience (Milestones 0.1 through 7.4, Self-Modification Plan MS 1–11, Verbose/Debug Plan MS V.1–V.5, and LLM Model Consolidation MS 1–8; 2026-03-12 to 2026-03-31). Based on 28+ transpiled modules across 4 layers, 920+ tests, and 30+ milestones of continuous usage.

---

## Executive Summary

s0ma-dsl proved capable of building a full self-aware AI agent from scratch. The module system, cross-module resolution, IR format, and derived edge inference are production-quality. However, five recurring issues accounted for the vast majority of friction across all milestones:

1. **The SERVICE nerve `def`-only body constraint** forces an increasingly verbose factory/dict pattern
2. **VESTIGIAL_IMPORT false positives on `depends_on`** penalize correct architectural documentation
3. **The `requires` import heuristic** is unintuitive and undocumented, with no override mechanism
4. **Transpiler bugs** (missing `Layer` import, `lark[interegular]` dependency) blocked progress repeatedly
5. **Non-deterministic build output paths** (`__s0ma_cache__` vs root) caused stale-import bugs

---

## 1. Bugs (Fix Immediately)

### 1.1 Missing `Layer` Import in Constant-Only Modules

**Severity:** Blocking (requires workaround in every test file and bootstrap code)
**First reported:** MS 2.1 | **Still open at:** MS 7.4
**Occurrences:** Every milestone from MS 2.1 onward

The transpiler generates `register_module(layer=Layer.DOMAIN, ...)` in constant-only modules (like `config.s0ma`) but never emits `from s0ma.types import Layer`. Modules with `@component` decorators get this import implicitly; constant-only modules do not.

**Workaround used:** Inject `Layer` and `ComponentKind` into Python `builtins` before importing transpiled modules.

**Fix:** Add `from s0ma.types import Layer` to any transpiled module that emits `register_module()` with a `layer=` argument, regardless of whether the module has `@component` decorators.

### 1.2 `lark[interegular]` Not Declared in s0ma-dsl Dependencies

**Severity:** Blocking (prevents `s0ma check` and `s0ma transpile` from working at all)
**First reported:** MS 1.1 | **Still open at:** MS 7.4
**Occurrences:** MS 1.1, MS 2.1 (blocked progress twice on fresh environments)

`s0ma-dsl` depends on `lark` but not `lark[interegular]`. Without `interegular`, the parser fails with misleading errors (`PARSE_ERROR: Invalid name list`) that look like syntax errors in the `.s0ma` file rather than a missing dependency.

**Fix:** Change `lark` to `lark[interegular]` in `s0ma-dsl`'s `pyproject.toml` dependencies.

### 1.3 `charmap` Codec Error on Windows

**Severity:** Medium (requires `PYTHONIOENCODING=utf-8` workaround)
**First reported:** MS 1.1 | **Recurred:** MS 2.3

The CLI uses unicode characters (e.g., `\u2192` arrow) in warning messages that fail to encode with the default Windows codec.

**Fix:** Force UTF-8 output encoding in the CLI rather than relying on the system codec.

---

## 2. Recurring Friction Points

### 2.1 SERVICE Nerve `def`-Only Body Constraint

**Impact:** High (affects every SERVICE nerve authored)
**First reported:** MS 1.3 | **Reiterated:** MS 2.2, 2.3, 2.5, 3.1, 3.2, 5.1 (10+ times)

The rule that all nerve bodies must be `def` (never `class`) forces stateful services into a factory/dict pattern:

```python
def MyService(dep1, dep2):
    state = {}
    def operation_a(): ...
    def operation_b(): ...
    return {"operation_a": operation_a, "operation_b": operation_b}
```

This pattern works but becomes increasingly verbose as services grow:
- **CLIGateway:** ~580 lines, 25+ inner functions
- **SessionManager:** ~230 lines, 9 public functions + 2 helpers
- **FileSystemTool:** ~200 lines, 8 operations + 1 helper

Specific costs of the factory/dict pattern at scale:
- No `self` — every operation captures state via closures; repeated boilerplate for shared error handling
- Return dict must be maintained in sync with function definitions
- Helper functions cannot be factored into separate nerves (must live inside the factory)
- IDE navigation (outline, go-to-definition) is degraded vs. class methods
- Consumers call `service["method"](args)` instead of `service.method(args)`

**Recommendation:** Allow `class` bodies for `kind: SERVICE` and `kind: ADAPTER` nerves while keeping `def` required for `kind: FUNCTION`. This would align with Python conventions and eliminate the most persistent ergonomic complaint across the entire rebuild.

**Counterpoint to acknowledge:** The dict-of-functions pattern has one significant advantage — it is excellent for test composability. Creating, composing, and asserting against service instances requires zero boilerplate. This benefit should be preserved even if class bodies are allowed (e.g., by generating a dict-compatible interface from class methods).

### 2.2 VESTIGIAL_IMPORT False Positives on `depends_on`

**Impact:** High (warning noise on every service with injected dependencies)
**First reported:** MS 2.1 | **Occurrences:** 10+ modules affected by MS 7.4

When a nerve receives a dependency as a constructor parameter (`def MyService(dependency)`), the validator cannot match the parameter name to the `depends_on` declaration name (`DependencyComponent`). This triggers a VESTIGIAL_IMPORT warning on every service that uses dependency injection — the standard wiring pattern.

**Affected modules (partial list):** `llm_adapter`, `self_model`, `integrity`, `plugin_loader`, `orchestrator`, `memory_tool`, `cli`

**Recommendations (in order of preference):**
1. **Suppress VESTIGIAL_IMPORT for all `depends_on` targets** — if a component is explicitly declared as a dependency, the warning adds no value
2. **Add `via: PARAMETER` qualifier** — `depends_on: LLMAdapter: {relation: CALLS, param: llm_adapter}` lets the validator check the parameter name instead
3. **Add parameter-to-PascalCase matching** — automatically check if a snake_case parameter corresponds to the PascalCase dependency name

Additionally: **Exempt CONSTRUCTS relations entirely** from body evidence matching. The CONSTRUCTS relation (implementation/inheritance) is inherently structural — the concrete implementation never calls the abstract interface by name. This affects `llm_adapter`, `cli`, and any future concrete adapter implementations.

### 2.3 `requires` Import Heuristic Issues

**Impact:** Medium-High (confusing for new users, no workaround for some patterns)
**First reported:** MS 1.1 | **Reiterated:** MS 1.3, 2.1, 3.2, 7.2

The case-based heuristic for `requires` entries:
- Uppercase last segment → `from X import Y` (e.g., `pathlib.Path`)
- Lowercase last segment → `import X.Y` (e.g., `datetime.datetime`)

Problems:
1. **Unintuitive:** `dataclasses.dataclass` generates `import dataclasses.dataclass`, not `from dataclasses import dataclass`
2. **No override:** Cannot express `from unittest import mock` because `mock` is lowercase
3. **NAMESPACE_COLLISION:** `datetime.datetime` + `datetime.timezone` collide on the local name `datetime`
4. **Undocumented:** The quick reference doesn't explain the heuristic

**Recommendations:**
1. **Document the heuristic** with examples in the quick reference (immediate)
2. **Add import alias/override syntax** (high priority):
   - `requires: [unittest.mock as mock]` or
   - `requires: [{from: unittest, import: mock}]`
3. **Add grouped imports** for same-module names:
   - `requires: [datetime.{datetime, timezone}]`

### 2.4 Plan `requires` Over-Specification

**Impact:** Low (caught by VESTIGIAL_IMPORT check, easily fixed)
**Occurrences:** 9+ milestones needed to drop `typing.Any` and/or `typing.Optional`

Plan templates consistently included `typing.Any` and `typing.Optional` in `requires` lists, but Python 3.11+ union syntax (`X | None`) and the actual code never used them.

**Recommendation:** Default plan templates to exclude `typing.Any` and `typing.Optional`. Only include when the body explicitly uses `Any` as an annotation or `Optional[X]` form.

### 2.5 `s0ma transpile` Flattens Nested Directory Structure

**Impact:** Medium (requires per-subdirectory invocation as workaround)
**First reported:** MS 8 (LLM Consolidation)

Running `s0ma transpile tests/` with the entire directory tree as input places all transpiled output into the `--output-dir` root, discarding subdirectory paths. For test suites organized into subdirectories (by layer, as fr3d does), this requires running `s0ma transpile` once per subdirectory — 6 invocations instead of 1.

**Recommendation:** When `s0ma transpile` processes files in `<input>/subdir/`, the output should go to `<output-dir>/subdir/`, preserving the relative path from the input root.

### 2.6 Large Nerve Bodies Lack Sub-Structure

**Impact:** Medium (affects readability and navigation of large services)
**First reported:** MS V.3 (Verbose CLI Rendering) | **Reiterated:** MS V.5

As nerve bodies grow (CLIGateway reached ~30 inner functions), the DSL provides no sub-structure within the `---` delimited body. There is no way to group related functions (e.g., "event renderers", "slash command handlers", "session lifecycle"). The DSL's structural benefits (declared intent, contracts, visibility) apply only at the nerve level, not within it. IDE navigation tools (outline, go-to-symbol) see only the single nerve, not its internal organization.

**Recommendation:** See feature request 3.14 (`# @section` annotations).

### 2.7 Closure-Based Nerves Make Internal Functions Untestable in Isolation

**Impact:** Medium (affects test granularity for complex services)
**First reported:** MS V.5 (Testing)

Internal functions like `_summarize_tool_result()`, `_handle_event()`, and `_render_turn_summary()` are closures inside the factory function — they cannot be imported or called directly from tests. Testing must go through public entry points (`dispatch_command`, `get_event_log`), meaning some behaviors are only tested indirectly. This is an inherent trade-off of the dict-of-functions pattern: excellent encapsulation, but no way to reach in for unit testing.

**Recommendation:** See feature request 3.17 (`testing_exports` metadata field).

### 2.8 High Ceremony-to-Code Ratio for Test Utilities

**Impact:** Low-Medium (affects test module authoring)
**First reported:** MS 5 (LLM Consolidation)

Modeling test utilities in `.s0ma` requires multiple declaration types. A simple pattern in Python — a module-level helper function, a constant computed from it, and a decorator function — required three separate `.s0ma` declarations (`nerve` + `cell` + `nerve`), each with its own `intent:`, `expects:`, `guarantees:`, etc. This produced ~30 lines of metadata for ~20 lines of implementation. Production code benefits from the metadata (contracts, intents, dependency tracking), but test helpers are ephemeral infrastructure where the ceremony outweighs the value.

**Recommendation:** See feature request 3.19 (lightweight `helper` declaration for test modules).

### 2.9 Duplicated Test Helpers Across Modules

**Impact:** Low-Medium (maintenance burden for shared test utilities)
**First reported:** MS 7 (LLM Consolidation)

Three test modules (`test_llm.s0ma`, `test_llm_live.s0ma`, `test_fresh_llm.s0ma`) contain identical `_load_api_key` nerve and `_API_KEY` cell declarations. The DSL has no mechanism for sharing internal helpers across test modules without creating a dedicated shared module with `exports`/`uses` wiring — which introduces cross-test coupling for a 10-line utility.

**Recommendation:** See feature request 3.20 (test fixtures convention) and consider documenting the trade-off.

### 2.10 Layer Assignment Ambiguity for Cross-Cutting Tests

**Impact:** Low (requires judgment call with no spec guidance)
**First reported:** MS 7 (LLM Consolidation)

Test modules that exercise components from multiple layers have no clear layer assignment rule. For example, `test_fresh_llm.s0ma` tests `self_model.SelfIntrospection` (DOMAIN) but uses `anthropic` (INFRASTRUCTURE). The test was assigned `layer: DOMAIN` because the primary subject is the self-model, but the quick reference provides no decision rule for this case.

**Recommendation:** Document a rule: "assign the test module's layer based on the primary component under test, as declared in `tests:`."

---

## 3. Feature Requests (Prioritized)

### Priority 1 — High Impact, Low Effort

#### 3.1 `provides` Field for SERVICE Nerves

Add a declaration-level field listing the service's public operations:
```
nerve FileSystemTool :: INFRASTRUCTURE
    kind: SERVICE
    provides: [read_file, write_file, edit_file, list_directory, search_files]
```

Benefits:
- Self-documenting service interfaces in the module header
- Appears in `s0ma inspect` output
- Enables validator to check that the body actually returns all declared operations
- Makes the IR richer for tooling consumers

#### 3.2 `soft_requires` / `optional_requires` Field

For dependencies that may not be installed:
```
soft_requires: [anthropic, prompt_toolkit]
```

Transpiles to:
```python
try:
    import anthropic
except ImportError:
    anthropic = None
```

Currently, `import anthropic` at module level causes the entire module to fail if the package isn't installed. This blocks bootstrap from importing optional components.

#### 3.3 Track TYPE_USES Through Constructor Calls

Currently, `s0ma inspect` only derives TYPE_USES edges from type annotations. Constructor calls like `ToolParameter(name="file", ...)` are not tracked. This means ToolParameter — used extensively across 4+ modules — never appears in derived edges.

**Fix:** If `ComponentName(...)` is called in the body, infer a `TYPE_USES → ComponentName` derived edge.

#### 3.4 `s0ma build --check` / Drift Detection

Add a verification mode that compares transpiled output against existing `.py` files:
```bash
s0ma build src/fr3d/ --output-dir src/fr3d_build/ --check
```

Returns exit code 0 if transpiled output matches existing files, exit code 1 if drift is detected. Useful as a CI check or pre-commit hook to prevent `.s0ma` ↔ `.py` divergence. During the LLM Consolidation milestone, 9 drifted test files were discovered — a `--check` command would have caught them immediately. Also useful as `s0ma diff` or `s0ma drift` for ad-hoc verification.

#### 3.5 `s0ma build --quiet` Flag

The full build output on a 26+ module project is verbose. A quiet mode that only shows errors and a summary line would reduce noise during iterative development. Suggested as early as the Self-Modification Plan MS 1 and reiterated across 10+ subsequent milestones.

### Priority 2 — Medium Impact

#### 3.6 `--include-path` for `s0ma build`

Allow specifying additional directories for cross-module resolution:
```bash
s0ma build tests/test_domain/ --include-path src/fr3d/ --output-dir tests/test_domain/
```

Currently, test `.s0ma` files that reference source modules in a different directory cannot use `s0ma build` — they must use per-file `s0ma transpile`, losing cross-module validation. During the LLM Consolidation MS 8, running `s0ma build tests/` produced 97 `DOES_NOT_EXIST` errors because every `uses:` reference to source modules failed resolution.

#### 3.7 `s0ma test` Command

A convenience command combining transpilation and pytest:
```bash
s0ma test tests/test_domain/ --source src/fr3d/ --output-dir tests/test_domain/
```

Handles path setup, transpilation, and test execution in one step.

#### 3.8 `s0ma test-conftest` Generator

Generates a correct s0ma runtime mock `conftest.py` for a project:
```bash
s0ma test-conftest --output tests/conftest.py
```

Inspects the project's `.s0ma` files to determine which `ComponentKind`, `Layer`, and registration functions are needed. Eliminates the manual maintenance burden of the hand-crafted mock that must be updated every time the s0ma runtime evolves.

#### 3.9 Abstract Interface / Protocol Support

A first-class mechanism for abstract adapters instead of the `NotImplementedError` convention:
```
nerve LLMAdapter :: INFRASTRUCTURE
    kind: ADAPTER
    abstract: true
    interface: [chat, chat_stream]
```

Benefits:
- Transpiler can verify concrete implementations provide all required methods
- Build-time enforcement vs. runtime `NotImplementedError`
- Currently used in 2 modules (`LLMAdapter`, `MessageGateway`), likely to grow

#### 3.10 Plugin Declaration Type

A dedicated `plugin` declaration for s0ma-dsl that generates proper registration code:
```
plugin MyPlugin :: DOMAIN
    registers: [NewComponent, NewService]
    requires_core: [ToolRegistry, PermissionManager]
```

Currently, plugins are raw Python files that manipulate registry dicts directly, bypassing all s0ma-dsl conventions and validation.

#### 3.11 `returns:` Metadata Field for Dict-of-Functions Nerves

Since the dict-of-functions pattern is idiomatic in s0ma (every ORCHESTRATOR, SERVICE, and ADAPTER nerve uses it), a structured declaration of the return dict's keys would enable:
```
nerve CLIGateway :: PRESENTATION
    kind: SERVICE
    returns: [receive_message, send_response, start, stop, run, dispatch_command]
```

Benefits:
- Compile-time validation that callers use valid dict keys
- Richer IR documenting the nerve's actual API surface (currently `exports` only names the nerve, not its operations)
- Better `describe()` and `s0ma inspect` output
- Machine-readable contract vs. prose-only `guarantees` field

Related to but distinct from 3.1 (`provides`): `provides` is about declaring the operations, `returns` would make the dict-of-functions return value part of the compile-time contract.

#### 3.12 `s0ma watch` Auto-Rebuild Mode

A file-watching mode that auto-rebuilds on `.s0ma` file changes:
```bash
s0ma watch src/fr3d/ --output-dir src/fr3d_build/ --mode dev
```

The "edit `.s0ma` → forgot to build → tests fail" mistake occurred repeatedly across milestones (first noted MS 4, reiterated across Self-Modification Plan). A watch mode would eliminate this class of error entirely during iterative development.

#### 3.13 `s0ma new` Module Scaffolding Command

Generate a valid `.s0ma` module skeleton with all required fields pre-filled:
```bash
s0ma new module hello_tool --layer APPLICATION
```

During MS 11, a test fixture omitted the required `version:` field — `s0ma check` caught it, but a scaffolding command would have prevented it entirely. Particularly valuable for new developers and LLMs authoring `.s0ma` files for the first time.

#### 3.14 `# @section` Annotations for Large Nerve Bodies

A lightweight annotation for sub-structuring large nerve bodies:
```python
# @section event-rendering
def _render_round_start(event): ...
def _render_tool_call(event): ...

# @section slash-commands
def _handle_replay(args): ...
```

Not a new declaration type — just a comment convention the transpiler recognizes and uses to produce structured sub-sections in the IR. `s0ma inspect` could then show "CLIGateway has 4 sections: event rendering, slash commands, session lifecycle, LLM routing". First requested when CLIGateway reached ~30 inner functions in MS V.3.

#### 3.15 PRODUCES / CONSUMES Axon Relations

For event-driven and pub-sub architectures where component A produces events and component B consumes them, connected by third-party wiring (e.g., `main.py`):
```
axon ConversationOrchestrator -> OrchestratorEvent
    relation: PRODUCES

axon CLIGateway -> OrchestratorEvent
    relation: CONSUMES
```

The current axon relations (CALLS, READS, CONSTRUCTS, CONFIGURES) describe direct dependencies. The event callback pattern (orchestrator produces events, CLI consumes them, connected by a bootstrap wire) is an indirect dependency invisible in the dependency graph. A PRODUCES/CONSUMES pair would make event flow visible and enable tooling to trace data flow paths. Also subsumes the SUPPLIES/FEEDS use case for orchestrator-mediated data flow.

#### 3.16 Preserve Directory Structure in `s0ma transpile`

When `s0ma transpile tests/` processes files in `tests/test_infrastructure/`, the output should go to `<output-dir>/test_infrastructure/`, not `<output-dir>/`. Currently, `s0ma transpile` on a directory tree flattens all output to the root, requiring per-subdirectory invocations as a workaround.

#### 3.17 `s0ma transpile` Output-Dir Mismatch Warning

When `s0ma transpile <file> --output-dir <dir>` places output in a directory that differs from where `s0ma build` would place it, emit a warning. First noted in MS V.1 when `--output-dir src/fr3d_build/domain/` created output in a subdirectory not on the bootstrap import path.

### Priority 3 — Nice to Have

#### 3.18 Intra-Module Helper Nerve Sharing

Allow INTERNAL helper nerves consumed only within the same module's scope. Currently, helpers like `_write_toml` or `_validate_path` must live inside the factory function as closures because there's no way to share code between nerves in the same module without cross-module `uses`.

#### 3.19 Lightweight `helper` Declaration for Test Modules

Test utilities like `_load_api_key` and `requires_api_key` don't benefit from full `nerve` metadata (`expects`, `guarantees`, `evaluates_at`). A `helper` declaration (or a reduced-metadata `nerve` variant for test modules) could reduce boilerplate while keeping code within the `.s0ma` pipeline:
```
helper _load_api_key :: INFRASTRUCTURE
    intent: "Load API key from environment or .env file"
    ---
    def _load_api_key():
        ...
    ---
```

#### 3.20 Test Fixtures / Shared Test Utilities Convention

Document (or provide tooling for) a recommended approach to sharing test helpers across test modules. Options:
1. A dedicated `tests/fixtures/test_utils.s0ma` module with `exports`
2. Allow `uses:` of an INTERNAL component from within the same test directory
3. Accept duplication as a feature (each test module is self-contained)

Currently, three test modules duplicate the identical `_load_api_key` pattern because there's no documented convention.

#### 3.21 `testing_exports` Metadata Field

Allow nerves to optionally export internal closures for test access without polluting the public API:
```
nerve CLIGateway :: PRESENTATION
    kind: SERVICE
    testing_exports: [_summarize_tool_result, _handle_event]
```

Would make closures accessible via `cli["__testing__"]["_summarize_tool_result"]` in test builds only. Addresses the untestability of internal functions in large closure-based nerves (see friction point 2.7).

#### 3.22 `group:` Metadata Field for Related Constants

Group logically related cells:
```
cell DEFAULT_MODEL :: DOMAIN
    kind: CONSTANT
    group: model_tiers
```

`DEFAULT_MODEL`, `TEST_MODEL`, and `ADVANCED_MODEL` are logically a "model tier" group, but this relationship is implicit. A `group:` field would let `s0ma inspect` report them as a cohesive set.

#### 3.23 Intra-Module Data-Flow Annotation

Express "nerve X produces cell Y" relationships within a module, similar to how `raises` declares exception flow. Currently implicit in the code body.

#### 3.24 Runtime IR Access

Provide `s0ma_dsl.runtime_bridge.get_ir()` to return the full `.s0ma.json` data at runtime, bridging the gap between the rich IR metadata and the minimal runtime registry.

#### 3.25 `validates_integration` Field for Test Declarations

Distinguish unit test coverage from integration test coverage in the IR. The current `tests: [module.Component]` field is flat and doesn't capture "integration across these components" semantics.

---

## 4. Documentation Gaps

These items require additions to the s0ma-dsl quick reference or a new "Patterns" guide:

| Gap | Priority | Notes |
|-----|----------|-------|
| `requires` import heuristic (case-based rules, examples) | HIGH | Caused confusion in MS 1.1, 1.3, 3.2, 7.2 |
| SERVICE nerve patterns (factory/dict, state management) | HIGH | The #1 missing pattern for real applications |
| EXCEPTION cell patterns (inheritance, schema field semantics) | MEDIUM | Quick reference only shows generic cell structure |
| CONSTANT cell patterns (minimal example) | MEDIUM | Not obvious that constants need no `requires` |
| `raises` + `uses` relationship | MEDIUM | `raises` is metadata only, does NOT import |
| Cell vs nerve `uses` semantics | MEDIUM | Cells are types; nerves are factory functions |
| Intra-module reference resolution | MEDIUM | Components in same module need no `uses` or `depends_on` |
| Abstract adapter convention (`NotImplementedError` pattern) | MEDIUM | Used in 2+ modules, undocumented |
| Bootstrap & entry point patterns | MEDIUM | When to use plain Python vs `.s0ma` |
| Test mock patterns (dict-based services) | LOW | The dict-mock rule for service dependencies |
| `nerve` vs `ganglion` decision tree for orchestrators | LOW | Ambiguous in current quick reference |
| `s0ma inspect` accepts `.s0ma.json`, not `.s0ma` | LOW | Minor UX issue, confusing error message |
| `test` body multi-function support | LOW | Quick reference shows singular, multi works |
| Integration test convention (plain pytest) | LOW | When to use `.s0ma` tests vs plain pytest |
| `test` block scope behavior (module-scoped) | MEDIUM | Functions in `test` blocks are emitted at module scope, accessible from other blocks — not documented |
| Layer assignment for cross-cutting tests | MEDIUM | No decision rule for tests exercising components across layers (see 2.10) |
| Intra-module cell reference rules | MEDIUM | Whether `depends_on` is needed for nerve-to-cell or test-to-nerve refs within same module — `s0ma check` passes without them but spec is silent |
| `requires` dotted-name convention (case-based) | HIGH | `pathlib.Path` → `from pathlib import Path` vs `unittest.mock` → `import unittest.mock` — transpiler uses capitalization heuristic but quick ref doesn't explain (extends §2.3) |

---

## 5. Tooling Improvements

### 5.1 Deterministic Build Output Paths

**Impact:** Medium (caused stale-import bugs in development and testing)
**First reported:** MS 4.5 | **Reiterated:** MS 5.1, 6.1

`s0ma build` places modules in `__s0ma_cache__/` while `s0ma transpile` places them at the root of the output directory. When both exist for the same module, `sys.path` ordering determines which is imported. Bootstrap and test code must add both paths.

**Fix:** Final outputs should always go to a single deterministic location. If `__s0ma_cache__` is for incremental build optimization, it should be opaque to consumers.

### 5.2 `s0ma inspect` Should Accept `.s0ma` Source Files

Currently, `s0ma inspect src/fr3d/domain/models.s0ma` fails — it only accepts `.s0ma.json` build output. It should auto-locate the corresponding build artifact or suggest running `s0ma transpile` first.

### 5.3 Relax VESTIGIAL_IMPORT for `requires` in `test` Declarations

The checker scans only the outermost scope of the body, missing `pytest` and `pathlib.Path` usage inside nested `def test_*()` functions. Test functions are inherently nested — the checker should scan the full body tree for test declarations.

### 5.4 Helper Name Collision Warning in Test Declarations

When multiple `test` declarations in the same module define helper functions with the same name, the second silently overwrites the first. The transpiler should warn about this.

### 5.5 Axon Evidence Matching for Parameter Injection

The transpiler should check whether a standalone axon target name appears as a parameter (with snake_case-to-PascalCase mapping) in the source nerve's signature, and accept that as evidence of the relationship.

### 5.6 `registry.to_dict()` Public Method

The s0ma `ComponentRegistry` should expose a public method returning the registry in the dict format that `SelfIntrospection` and `AnomalyDetector` expect, eliminating bootstrap code's need to access `_components` and `_modules` private attributes.

### 5.7 `__s0ma_cache__` Staleness on Single-File Transpile

When using `s0ma transpile` on a single file, the `__s0ma_cache__` directory is not updated — only `s0ma build` (full project) populates it. If `conftest.py` adds `__s0ma_cache__` to `sys.path` with higher priority than the main build output, stale cached modules cause import failures (e.g., `ImportError: cannot import name 'TEST_MODEL' from 'config'` because the cache predates the constant's addition).

**Fix:** Either auto-update the cache on single-file transpile, or warn when a dependency's cached output is stale relative to its source `.s0ma` file.

### 5.8 `requires` Import Heuristic Fails for Lowercase Stdlib Attributes

The capitalization-based `requires` heuristic (`Foo` → `from x import Foo`, `foo` → `import x.foo`) breaks for standard library functions like `unittest.mock.patch`, `functools.wraps`, `contextlib.contextmanager`. The transpiler generates `import unittest.mock.patch` (treating `patch` as a submodule) instead of `from unittest.mock import patch`. Workaround: use `requires: [unittest.mock]` and fully-qualified names in bodies.

**Fix:** Allow explicit import form syntax, e.g., `requires: [unittest.mock:patch, unittest.mock:MagicMock]` or `requires: [from unittest.mock import patch]`. This removes all ambiguity for edge cases where the heuristic fails. (Extends §2.3.)

---

## 6. What Works Well (Preserve These)

These are the strengths that made the fr3d rebuild successful. Any refactoring should preserve them:

1. **Cross-module `uses` resolution** — Flawless across 25 modules and 4 layers. Zero `NOT_EXPORTED` or `LAYER_VIOLATION` errors on any module authored since MS 2.1.

2. **`s0ma check` validation** — Catches real issues (NAMESPACE_COLLISION, BARE_IMPORT, DUPLICATE_AXON, DOES_NOT_EXIST) with clear, actionable error messages. VESTIGIAL_IMPORT detection is accurate (the false positives are in the `depends_on` evidence checker, not the import scanner).

3. **`s0ma inspect` and the IR format** — The `.s0ma.json` files are well-structured, complete, and usable as both build artifacts and runtime data sources. `s0ma inspect` output is consistently clear and accurate.

4. **Derived edge inference** — TYPE_USES and RAISES edges are correctly inferred from type annotations and `raise` statements in nerve bodies, including nested inner functions and async generators. (Gap: constructor calls are not tracked — see recommendation 3.3.)

5. **Layer enforcement** — The 4-layer architecture (DOMAIN → INFRASTRUCTURE → APPLICATION → PRESENTATION) is enforced at build time. Cross-layer dependencies in valid directions resolve without friction.

6. **INTERNAL visibility** — Works correctly for module-private data types (e.g., `PlanStep`, `TaskPlan`, `PluginLoadResult`) that nerves need but shouldn't export.

7. **Build performance** — Effectively instant at 25 modules. No observable degradation as the project grew from 1 to 25 modules.

8. **Dict-of-functions test composability** — Creating, composing, and asserting against service instances requires zero boilerplate. This is the single biggest ergonomic advantage of the factory pattern and partially offsets its authoring-time verbosity.

9. **Transpiled output quality** — Clean, readable Python with correct import ordering, proper decorators, and faithful preservation of complex constructs (async generators, nested closures, `nonlocal` state management).

10. **Zero-iteration authoring after ramp-up** — From MS 2.2 onward (7th module), every new `.s0ma` file passed `s0ma check` on the first attempt. The DSL patterns are predictable and learnable.

11. **Advanced Python constructs pass through cleanly** — The transpiler correctly handles `nonlocal` declarations (including multiple functions referencing the same `nonlocal` variable), `@pytest.mark.asyncio` decorators, `async def`/`await`, lambda closures (10+ in a single nerve body), `@staticmethod` in dataclasses, `hashlib`, `shutil.copy2`, f-strings with nested attribute access, `**kwargs`, and `json.loads(json.dumps(...))` patterns. No Python construct used across 12+ milestones required a workaround.

12. **DSL transparency for logic-only changes** — Across the entire Self-Modification Plan (MS 1–11), every milestone was implemented without needing new declaration types, new cell kinds, or new DSL features. When changes are entirely within nerve bodies (Python code between `---` delimiters), s0ma-dsl adds zero overhead. The `cell` + `nerve` vocabulary was sufficient for every change.

13. **`s0ma check` catches missing required fields with clear remediation** — When a test fixture omitted the required `version:` field, `s0ma check` produced a `MISSING_FIELD` error with exact remediation instructions. Error messages consistently point to the fix rather than just the problem.

---

## 7. Summary of Recommended Changes

### Immediate (bug fixes)
- Fix `Layer` import in constant-only modules
- Declare `lark[interegular]` in s0ma-dsl dependencies
- Fix Windows `charmap` encoding
- Fix `__s0ma_cache__` staleness on single-file transpile
- Fix `requires` import heuristic for lowercase stdlib attributes (e.g., `unittest.mock.patch`)

### Short-term (high-impact improvements)
- Suppress VESTIGIAL_IMPORT for `depends_on` targets (or add `via: PARAMETER`)
- Document the `requires` import heuristic with examples (including dotted-name convention)
- Add import alias/override syntax (`requires: [unittest.mock:patch]`)
- Deterministic build output paths
- Add `provides` field for SERVICE nerves
- Add `soft_requires` field
- Add `s0ma build --check` / drift detection command
- Add `s0ma build --quiet` flag
- Preserve directory structure in `s0ma transpile` output

### Medium-term (feature development)
- Allow `class` bodies for SERVICE/ADAPTER nerves
- Track TYPE_USES through constructor calls
- Add `--include-path` to `s0ma build`
- Add `s0ma test` and `s0ma test-conftest` commands
- Abstract interface/protocol support
- Plugin declaration type
- Add `returns:` metadata field for dict-of-functions nerves
- Add `s0ma watch` auto-rebuild mode
- Add `s0ma new` module scaffolding command
- Add `# @section` annotations for large nerve bodies
- Add PRODUCES/CONSUMES axon relations for event-driven patterns
- Add `s0ma transpile` output-dir mismatch warning

### Long-term (ecosystem maturity)
- Intra-module helper nerve sharing
- Lightweight `helper` declaration for test modules
- Test fixtures / shared test utilities convention
- `testing_exports` metadata field for test access to internals
- `group:` metadata field for related constants
- Runtime IR access
- `validates_integration` for test metadata
- `s0ma coverage` and `s0ma graph --include-tests` tooling

### Documentation additions
- `test` block scope behavior (module-scoped, accessible across blocks)
- Layer assignment rules for cross-cutting tests
- Intra-module cell reference rules (nerve-to-cell `depends_on`)
- `requires` dotted-name convention with case-based examples
