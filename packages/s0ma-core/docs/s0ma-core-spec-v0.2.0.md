# s0ma — Framework Specification & Coding Agent Rulebook (historical: v0.2.0)

**Historical. This is a frozen record, not current guidance.** It is the last
core specification cut before the monorepo consolidation, when `s0ma-core` was
a standalone distribution with its own version line, its own release process,
and a different license. It was last edited on 2026-05-11 and has not been
maintained since. Nothing below is gated, and much of it is no longer true:
every count, component list, module map, and API roster it contains was
accurate on the day it was written and has been drifting ever since.

**The current specification is
[`s0ma-core-spec-v0.21.1.md`](s0ma-core-spec-v0.21.1.md)** — core's invariants
and contracts, stated once, with every inventory deferred to the generated
references. For what core actually contains today, read the
[component index](../../../docs/architecture/component-index.md); for what it
serves, [what s0ma can do](../../../docs/reference/surfaces-index.md). Both are
read out of s0ma itself at build time.

This file is kept, and deliberately not renamed, because it is the honest
record of what core promised at the 0.4.0 boundary. Read it as history.

---

**Version:** 0.2.0 (registry surface additions from 0.3.0 — pre-Phase-2 batch — folded inline in §§4.9–4.11; 0.4.0 import-hook anomaly surface folded into §4.12 and §7.6)
**Last Updated:** 2026-05-11

> The 0.3.0 release adds three additive surfaces — snapshot diffing
> (§4.10), module-scoped registry keys (§4.9), and `module_path` on
> constant / type registration (§4.11). All three are backward-compatible;
> pre-0.3.0 registries, snapshots, and SQLite databases load unchanged.
> The §1–3 and §5+ surface is unchanged. See `CHANGELOG.md ## [0.3.0]`
> for the per-item rationale.
>
> The 0.4.0 release adds the `ImportHookAnomaly` surface (§4.12) —
> every foreign-code violation the import hook detects (§7) is now
> appended to the registry's anomaly buffer and dispatched to any
> registered subscribers. Behaviour is purely additive: strict-mode
> imports still raise and lenient-mode imports still warn; the
> anomaly buffer is the new poll / subscribe surface that downstream
> immune-response detection consumes without scraping log output.

> A Python framework for software self-knowledge — spanning proprioception (structure),
> interoception (runtime state), and metacognition (reasoning over the model).
>
> **Every component. Every piece of code. Fully registered. No exceptions.**

---

## 1. Purpose & Design Principles

s0ma is a Python framework that makes software **know itself**. It enforces a single invariant at the language level: code cannot exist without registering itself. The registry is not documentation — it is a structural dependency. Delete the registry, and the code stops working.

The framework exists to serve five non-negotiable design principles:

### Principle 1 — Registration as Creation

Nothing exists unless it is registered. Every public class or function under the project root must be decorated with `@component` or `@internal`. The `@component` decorator is how code is born into the system. Code that bypasses registration is rejected at import time — the import hook raises `UnregisteredComponentError` before the module can finish loading.

This is not a linting rule. It is not a convention. It is an enforcement mechanism wired into Python's module loading system. The distinction matters: a linting rule can be ignored; an import hook cannot.

The implication: the system's self-model is always complete. If code is running, it is registered. If it is registered, it is queryable. There are no phantom processes, no shadow code, no invisible dependencies.

### Principle 2 — Load-Bearing Self-Model

The self-model is a structural dependency of the running system, not documentation that exists alongside it. This is the distinction between a parts list taped to a machine and the machine's own nervous system.

Concretely: the import hook consults the registry at import time. Components declare dependencies by name, and the registry resolves them. The verification engine compares the registry against source code via AST analysis. If the self-model is deleted, imports fail, dependency resolution fails, and verification becomes impossible.

The self-model is not optional. It is not advisory. It is load-bearing.

### Principle 3 — Zero Runtime Overhead

The `@component` decorator returns the decorated entity **completely unmodified** — no wrapping, no proxying, no descriptor protocol manipulation, no `__call__` interception. A decorated class is identical to the undecorated class at runtime. The only side effect is registration (attaching a `__component__` attribute and inserting a `ComponentSpec` into the registry).

This is a deliberate architectural choice. The self-model must not degrade the system it describes. A framework that slows down every function call to maintain awareness is a framework that creates an incentive to bypass awareness. Zero overhead eliminates that incentive.

The exception: `@instrument` and `monitor_call()` from the interoception verifier add timing overhead, but these are explicitly opt-in and never applied by `@component` itself.

### Principle 4 — AI as Primary Consumer

The self-model's query interfaces (`SelfModelInterface`, REST API, MCP server) produce output designed for LLM consumption first. Every method returns natural language text, not raw data structures. The text is structured enough to be parseable by language models and readable enough for human developers.

This is not a cosmetic choice. The self-model exists to be consumed by agents that reason about the system. If the output requires contextual inference to interpret, it fails its purpose. Every query response must be self-contained, unambiguous, and actionable without prior knowledge of the codebase.

### Principle 5 — Biological Pathology Taxonomy

Code-model discrepancies are classified using biological analogies. This is not metaphor for its own sake — it is a vocabulary designed to be memorable, precise, and immediately communicative of severity and resolution.

A **phantom limb** (registry entry with no code) is different from a **vestigial organ** (code with no callers) is different from an **immune response** (unregistered foreign code). Each has a distinct detection algorithm, a distinct severity, and a distinct resolution path. The taxonomy prevents the common failure mode of verification systems: a flat list of undifferentiated "warnings" that developers learn to ignore.

---

## 2. Architecture

### 2.1 Initialization Pipeline

```
s0ma.initialize(project_root="./src")
       |
       v
1. Create ComponentRegistry (in-memory + optional SQLite at .s0ma/registry.db)
       |
       v
2. Bootstrap self-registration (register s0ma's own framework components;
   get_registry() performs it as it creates the singleton, so this is a no-op then)
       |
       v
3. Install import hook (sys.meta_path finder at highest priority)
       |
       v
Registry is live. Import hook is active. System is self-aware.
```

`initialize()` must be called **before** importing any application modules. This is an ordering constraint, not a suggestion. If application modules are imported first, the import hook is not yet installed, and registration enforcement is bypassed.

### 2.2 The Enforcement Loop

After initialization, every module import under `project_root` passes through the enforcement loop:

```
Module import requested
       |
       v
S0maFinder: Is this module under project_root?
       |
  No --+--> Standard Python import (no enforcement)
       |
  Yes -+--> S0maLoader wraps the standard loader
       |
       v
Module loads normally (all @component decorators fire, registering into registry)
       |
       v
Post-load scan: Are there unregistered public entities?
       |
  No --+--> Import succeeds
       |
  Yes -+--> strict=True:  raise UnregisteredComponentError
            strict=False: emit warning, allow import
```

### 2.3 The Core Loop

Every time a coding agent adds, changes, or removes functionality:

```
1. DECLARE   -> Define the component with @component decorator
2. IMPLEMENT -> Write the logic inside the decorated class/function
3. VERIFY    -> Run s0ma.verify() to check registry <-> code consistency
4. QUERY     -> Use SelfModelInterface or the /self/ API to inspect the result
```

**If you skip step 1, step 2 will not work.** The import hook blocks unregistered code.

### 2.4 Relationship to the s0ma DSL

s0ma-core is the runtime foundation. The s0ma DSL is a transpiler-first language that compiles to Python + s0ma-decorated code. The DSL enforces at the grammar level what s0ma-core enforces at runtime. They are complementary:

| Concern | s0ma-core | s0ma DSL |
|---------|-----------|----------|
| Enforcement point | Runtime (import hook, verification engine) | Compile time (parser, transpiler) |
| Language | Python with decorators | `.s0ma` files with declaration blocks |
| Declaration model | `@component` decorator with keyword arguments | Structured declaration blocks with `---` separator |
| Dependency model | `dependencies` list of component names | `requires`, `uses`, `exports` with namespace separation |
| Relationship model | Implicit (names in `dependencies` list) | Explicit (authored axons with `relation`, `carries`, `coupling`) |
| Evaluation model | Verification engine (post-hoc) | `evaluates_at` + ganglion declarations (built-in) |

The DSL does not replace s0ma-core. It generates code that s0ma-core executes and enforces.

### 2.5 Dependency Architecture

s0ma-core has **zero runtime dependencies** beyond the Python standard library. The core framework — registry, decorators, import hook, types, models, verification engine, self-model interface — uses only `stdlib` modules: `dataclasses`, `threading`, `sqlite3`, `ast`, `inspect`, `importlib`, `pathlib`, `json`, `time`, `collections`, `typing`.

Optional extras add dependencies only when explicitly installed:

| Extra | Dependencies | Purpose |
|-------|-------------|---------|
| `api` | FastAPI, uvicorn | REST API (`/self/` endpoints) |
| `mcp` | MCP SDK | Model Context Protocol server for Claude |
| `all` | Both of the above | Everything |

This is a load-bearing design decision. A framework that requires `requests` or `pydantic` to function creates a dependency surface that the self-model cannot fully describe (those libraries are outside the self-awareness boundary). By using only stdlib, s0ma-core's self-model is complete down to the Python runtime itself.

### 2.6 Thread Safety Model

The `ComponentRegistry` uses `threading.Lock()` for all mutation operations (`register`, `unregister`, `reset`). The `LifecycleManager` uses `threading.RLock()` (reentrant) because lifecycle operations may trigger verification, which reads the registry, which must not deadlock against the lifecycle lock.

Read operations (`get`, `get_all`, `contains`, `query_by_layer`, `query_by_kind`) are lock-free. The registry stores `ComponentSpec` objects, which are frozen dataclasses (immutable after creation). Reads return copies or references to immutable objects, so concurrent reads are safe without locking.

---

## 3. Primitive Vocabulary

| Primitive | Definition |
|-----------|-----------|
| **Component** | Any class or function registered with `@component`. The atom of the self-model. Has a name, kind, layer, intent, and optional contracts, dependencies, resource profile. |
| **Registry** | The central store of all component registrations. In-memory dict backed by optional SQLite persistence. The system's memory of its own structure. |
| **Contract** | A behavioral declaration: what must be true before invocation (preconditions), what is guaranteed after (postconditions), what always holds (invariants), and performance bounds (latency, error rate). |
| **Resource Profile** | Expected runtime characteristics: memory usage, latency percentiles, error rate, call frequency. The basis for interoception monitoring. |
| **Import Hook** | A `sys.meta_path` finder/loader pair that intercepts module imports and enforces registration. The mechanism that makes the self-model load-bearing. |
| **Anomaly** | A detected discrepancy between the self-model and reality. Classified by the biological pathology taxonomy (Section 6.1). |
| **Verification Report** | The aggregated output of all verifiers. Contains anomalies, check counts, durations, and a pass/fail determination. |
| **Self-Model Interface** | The query API for the self-model. Produces natural language text describing the system, its components, dependencies, impact analysis, and extension points. |
| **Lifecycle Manager** | The mutation API for the self-model. Wraps the registry with pre-validation, post-verification, automatic rollback, and audit logging. |
| **Snapshot** | A frozen, serializable view of the registry at a point in time. Includes components, modules, edges, test registrations, IR data, and plugins. Used for self-description, persistence, and comparison. |
| **Plugin** | A first-class extension registered via `register_plugin()`. Declares what it provides (`registers`) and what core components it depends on (`requires_core`), with dependency validation at registration time. |
| **IR Store** | Runtime storage for transpiler intermediate representation data. Modules store their `.s0ma.json` IR via `store_ir()`, making it queryable through the registry without disk access. |
| **Bootstrap** | The process by which s0ma registers its own framework components. Solves the chicken-and-egg problem: `@component` cannot decorate itself. |

### 3.1 Component Kind Taxonomy

| Kind | Meaning | Typical Use |
|------|---------|-------------|
| `SERVICE` | Long-running, stateful process or manager | Database connection pools, cache managers, background workers |
| `FUNCTION` | Stateless transformation or computation | Validators, parsers, formatters, calculators |
| `MODEL` | Data structure with fields and optional invariants | Domain entities, DTOs, value objects |
| `ADAPTER` | Interface to an external system | API clients, file system wrappers, message queue consumers |
| `ORCHESTRATOR` | Coordinates other components | Workflow engines, request routers, pipeline managers |
| `FRAMEWORK` | s0ma's own infrastructure (reserved) | Registry, verifiers, self-model interface |

`FRAMEWORK` is reserved for s0ma's own 44 bootstrap components. Application code must not use it.

### 3.2 Architectural Layer Taxonomy

| Layer | Meaning | Depends On | Never Depends On |
|-------|---------|------------|-----------------|
| `DOMAIN` | Core business logic and rules | Nothing (ideally) | `INFRASTRUCTURE`, `PRESENTATION` |
| `APPLICATION` | Use cases, orchestration, workflows | `DOMAIN` | `PRESENTATION` |
| `INFRASTRUCTURE` | External system adapters, persistence | `DOMAIN`, `APPLICATION` | `PRESENTATION` |
| `PRESENTATION` | UI, API endpoints, CLI handlers | `DOMAIN`, `APPLICATION` | — |
| `FRAMEWORK` | s0ma internals (reserved) | — | — |

Layer constraints are verified by the structural verifier. Cross-layer dependency violations are reported as anomalies.

### 3.3 Anomaly Pathology Taxonomy

| Pathology | Biological Analogue | What It Means | Detection | Severity |
|-----------|-------------------|---------------|-----------|----------|
| `PHANTOM_LIMB` | Amputated limb still "felt" | Registry entry exists, but the code is gone | Registry scan finds name with no matching source | `ERROR` |
| `VESTIGIAL_ORGAN` | Appendix | Code exists but is never called or referenced | Coverage analysis + call graph shows zero references | `WARNING` |
| `IMMUNE_RESPONSE` | Foreign body rejection | Unregistered public code detected under project root | Import hook finds entity without `@component` or `@internal` | `ERROR` |
| `ATROPHIED_MUSCLE` | Disuse atrophy | Deprecated component still receiving traffic | Runtime monitoring shows calls to deprecated endpoints | `WARNING` |
| `INFLAMMATION` | Tissue swelling | Component exceeding its declared resource profile | Interoception verifier compares metrics to `ResourceProfile` | `WARNING` |

### 3.4 Anomaly Severity Levels

| Severity | Meaning | Action Required |
|----------|---------|----------------|
| `ERROR` | System integrity compromised. Self-model is inaccurate. | Must fix before deployment. |
| `WARNING` | Potential drift. Self-model may be degrading. | Should investigate. |
| `INFO` | Cosmetic. No functional impact. | May ignore. |

---

## 4. The Registration System

### 4.1 The `@component` Decorator

Every piece of meaningful code must be wrapped in `@component`. This simultaneously:
- Registers the component in the self-model (inserts `ComponentSpec` into the global registry)
- Attaches introspectable metadata (as `__component__` attribute on the entity)
- Makes the component queryable via the self-model API
- Enables verification against declared contracts and resource profiles

```python
from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer
from s0ma.models import Contract

@component(
    name="SignalProcessor",
    kind=ComponentKind.SERVICE,
    layer=Layer.APPLICATION,
    intent="Receives raw nerve signals, validates them, and routes them to the appropriate subsystem evaluator",
    contracts=Contract(
        input_type="signal: SignalEnvelope",
        output_type="bool",
        preconditions=["signal is not None", "signal.source is non-empty"],
        postconditions=["signal reaches exactly one evaluator"],
        invariants=["processing is idempotent for the same trace_id"],
        max_latency_ms=50,
        error_rate_threshold=0.01,
    ),
    dependencies=["SignalValidator", "EvaluatorRouter"],
    version="1.0.0",
)
class SignalProcessor:
    ...
```

**The decorator returns the entity completely unmodified.** No wrapping, no proxying, no runtime overhead on calls.

### 4.2 Decorator Fields

| Field | Required | Type | Constraint | Purpose |
|-------|----------|------|------------|---------|
| `name` | **Yes** | `str` | PascalCase, globally unique, no whitespace | Unique identifier in the self-model |
| `kind` | **Yes** | `ComponentKind` | Must be enum value, not string | Functional archetype classification |
| `layer` | **Yes** | `Layer` | Must be enum value, not string | Architectural layer classification |
| `intent` | **Yes** | `str` | Minimum 10 characters | Plain-English description of purpose |
| `contracts` | Recommended | `Contract` | See Section 5 | Behavioral expectations |
| `dependencies` | Recommended | `list[str]` | Names must match registered components | Declared dependency relationships |
| `resource_profile` | Optional | `ResourceProfile` | See Section 5.3 | Expected runtime resource usage |
| `version` | Optional | `str` | Semantic versioning | Defaults to `"0.1.0"` |
| `metadata` | Optional | `dict[str, Any]` | Free-form | Extensible key-value store |
| `idempotent` | Optional | `bool` | — | Allow re-registration from same source file |

### 4.3 The `@internal` Decorator

For private helpers that should NOT be registered as components but live alongside component code:

```python
from s0ma.decorators import internal

@internal
def _parse_config(raw: str) -> dict:
    """Private helper — intentionally unregistered."""
    return json.loads(raw)

@internal(reason="Legacy helper, will be removed in v2")
def _old_parser(raw: str) -> dict:
    ...
```

`@internal` tells the import hook to exempt the entity from registration requirements. It attaches a `__s0ma_internal__ = True` attribute. Internal entities are never registered in the self-model, never appear in queries, and never participate in verification.

### 4.4 The Decision: `@component` vs `@internal` vs `_` Prefix

| Entity Type | Decorator | Rationale |
|-------------|-----------|-----------|
| Independent functionality (services, processors, validators) | `@component` | Self-model must know about it |
| Private helper used by a component | `@internal` | Import hook must allow it, but self-model should not track it |
| Truly private implementation detail | `_` prefix (no decorator needed) | Python convention; import hook ignores non-public names |
| Abstract base class | `@internal` (default) or `@component` (if architecturally significant) | ABCs are interface definitions, not deployable components |
| Shared types, enums, dataclasses | `@internal` | Supporting types, not independent components |

### 4.5 Component Name Uniqueness

Component `name` is globally unique across **all** registered components — both application components and s0ma's own 44 framework components. The namespace is flat and global.

**Framework-reserved names include:** `ComponentRegistry`, `SelfModelInterface`, `Contract`, `LifecycleManager`, `TransactionContext`, `StructuralVerifier`, `ContractVerifier`, `InteroceptionVerifier`, `CoverageAuditor`, `MetricsCollector`, `ComponentSpec`, `ResourceProfile`, `RegistrySnapshot`, `VerificationReport`, `VerificationResult`, `Anomaly`, `LifecycleEvent`, `ImpactReport`, `ExtensionPoint`, `ReflexionAnalysis`, `QueryEngine`, and others.

**To avoid collisions, adopt a project-level naming convention:**

| Risky | Safer |
|-------|-------|
| `"QueryEngine"` | `"MyApp_QueryEngine"` |
| `"MetricsCollector"` | `"MyApp_MetricsCollector"` |
| `"LifecycleManager"` | `"MyApp_LifecycleManager"` |

Discover all reserved names:
```python
reserved = [spec.name for spec in registry.get_all().values() if spec.is_framework]
```

### 4.6 Idempotent Registration

By default, duplicate registration raises `RegistrationError`. Two legitimate scenarios require re-registration:

1. **Hot-reload:** `importlib.reload(module)` re-executes `@component` decorators
2. **Post-reset module reuse:** After `reset_registry()`, re-importing a cached module re-fires its decorators

**`idempotent=True`** opts into graceful re-registration:

| Condition | `idempotent=False` (default) | `idempotent=True` |
|-----------|------|------|
| Same name, same source file | `RegistrationError` | Silent success (no-op) |
| Same name, different source file | `RegistrationError` | `RegistrationError` |
| New name | Registers normally | Registers normally |

**`register_or_update(spec)`** provides upsert semantics for programmatic scenarios:

| Condition | Behavior |
|-----------|----------|
| Name is new | Register and return new spec |
| Name exists, same source file | Replace with new spec and return it |
| Name exists, different source file | Raise `RegistrationError` |

### 4.7 Abstract Base Classes

`@internal` on the ABC, `@component` on each concrete subclass. This is the default pattern because the self-model tracks concrete, deployable implementations — not abstract contracts.

`@component` on both parent and child is permitted. Each class establishes independent registration. But applying `@component` twice to the *same* class raises `RegistrationError`.

### 4.8 What Happens Without `@component`

```python
# This file is under project_root but has no decorator
class SneakyHelper:
    def do_something(self):
        return "I'm unregistered!"

# When another module tries to import this:
# >>> from my_app.helpers import SneakyHelper
# UnregisteredComponentError: 'SneakyHelper' in 'my_app/helpers.py'
#   is not registered in the s0ma self-model.
#   All public code under the project root must use @component or @internal.
```

The system literally cannot use code it does not know about. There are no phantom limbs at import time.

### 4.9 Module-Scoped Registry Keys (0.3.0)

The default registry stores every component under its bare `name`, which is why §4.5 demands global uniqueness across all registered components. The `ComponentSpec.module_scoped: bool` field (default `False`) opts a spec into module-qualified registry keying without changing default behaviour. When both `module_scoped=True` and `module_path` is non-empty, the registry stores the spec under `"<module_path>::<name>"` instead of the bare `name`, letting two specs with identical bare names but distinct modules coexist.

Key facts:

- The spec's own `name` field remains the bare name regardless of `module_scoped`. Only the registry's lookup key changes — `ComponentSpec` does not lie about its own identity.
- `ComponentRegistry.get(name)` and `contains(name)` accept either form. A direct match (qualified or bare) resolves in O(1). A bare lookup against a uniquely-scoped spec succeeds. A bare lookup that resolves to two or more module-scoped specs returns `None` — the registry never guesses across modules; callers must use the qualified form to disambiguate.
- `unregister(name)` and `_replace_internal` accept either form via the same resolution rule.
- `RegistrySnapshot.components` carries qualified keys for scoped entries and bare keys for unscoped. `to_dict`/`from_dict` round-trip cleanly.
- SQLite persistence: the `components` table gained an additive `module_scoped INTEGER DEFAULT 0` column. Module-scoped rows are stored under their qualified key in the existing `name` column; bare rows are stored unchanged. Pre-0.3.0 databases migrate via `ALTER TABLE` on first load.
- `to_dict()` emits `"module_scoped": true` only when set; legacy specs serialise byte-identical.

The DSL emitter passes `module_path` through `register_constant` / `register_type` automatically. When the corresponding cell carries `module_scoped: true` in its `.s0ma` declaration, the resulting `ComponentSpec` opts into qualified keying with no additional consumer-side work. Use this when two modules legitimately need a cell of the same bare name — abstract/concrete pairs, plugin-shaped sibling integrations, or any other case where renaming around the global namespace would obscure intent.

### 4.10 Snapshot Diffing — `s0ma.self_model.diff` (0.3.0)

Two registry snapshots compare into a structured difference via:

```python
from s0ma.self_model.diff import compute_registry_diff, StructuredDiff, ComponentChange

result: StructuredDiff = compute_registry_diff(prior=snap_a, current=snap_b)
# result.added / .removed / .modified : list[ComponentChange]
# ComponentChange.field_changes : dict[field_name, (before, after)]
```

Behaviour pins:

- Inputs are two `RegistrySnapshot` instances (typically produced via `registry.snapshot()`).
- Component matching is by snapshot dict key — bare names for unscoped components, qualified `"<module_path>::<name>"` for `module_scoped=True` components.
- Field comparison delegates to `s0ma.hashing.canonical.canonicalize`, so dict and set ordering inside `metadata` / `dependencies` never produces false positives. The diff agrees with the content-hash subsystem about deeper equality.
- The `registered_at` timestamp is excluded from comparison (always differs across registrations).
- All three lists (`added`, `removed`, `modified`) are sorted by component name for deterministic output.
- `StructuredDiff.is_empty()` returns `True` for a no-change comparison; `StructuredDiff(snap, snap).is_empty() == True` is the round-trip invariant.
- `StructuredDiff.to_dict()` and `ComponentChange.to_dict()` produce JSON-serialisable output for cross-process / HTTP transport.

`compute_registry_diff` is the canonical implementation for snapshot-vs-snapshot diffing. Downstream consumers should depend on this API rather than maintaining parallel implementations.

### 4.11 `module_path` on Constant / Type Registration (0.3.0)

`ComponentRegistry.register_constant()` and `register_constant_type()` accept a `module_path: str = ""` keyword that flows through to `ComponentSpec.module_path` on the resulting spec. The DSL emitter passes the owning module's canonical name automatically, achieving parity with `register_module` and `@component` — every registered component now carries its owning module on the spec without consumer fallbacks. Empty string remains the back-compat default for direct (non-emitter) call sites.

### 4.12 Import-Hook Anomaly Surface (0.4.0)

The import hook (§7) detects foreign-code violations every time a project module loads — unregistered public entities (§4.8) and stale documentation markers (§10). Pre-0.4.0 the hook surfaced these only via `UnregisteredComponentError` (strict mode) and Python warnings (lenient mode). 0.4.0 adds a structured, observable surface backed by the registry so downstream consumers — notably the B1 IMMUNE_RESPONSE detection layer in fr3d's Phase 2 — can poll or subscribe to detections without scraping log output.

**Dataclass.** `ImportHookAnomaly` is a frozen dataclass exported from `s0ma`:

```python
from s0ma import ImportHookAnomaly
from s0ma.types import AnomalySeverity, Layer

ImportHookAnomaly(
    name: str,                  # fully qualified module name
    description: str,           # human-readable finding
    severity: AnomalySeverity,  # ERROR (strict) / WARNING (lenient)
    layer: Layer | None = None, # registry-known layer if available
    detected_at: datetime = <utc now>,
)
```

`to_dict()` returns a JSON-shape with the enum names serialised as strings (`severity="ERROR"`, `layer="DOMAIN"` or `None`).

**Registry API.** Three new entry points on `ComponentRegistry`:

```python
registry.import_hook_anomalies         # property — list[ImportHookAnomaly]
registry.clear_import_hook_anomalies() # empty the buffer
registry.subscribe_import_hook_anomalies(callback) -> Callable[[], None]
```

- `import_hook_anomalies` returns a **defensive copy** of the buffer in detection order. Mutating the returned list does not affect future polls.
- `clear_import_hook_anomalies()` empties the buffer without touching subscriber bindings.
- `subscribe_import_hook_anomalies(callback)` registers a `Callable[[ImportHookAnomaly], None]` invoked **synchronously, under the registry lock**, for every new detection. The return value is a zero-argument unsubscribe function; calling it twice is a no-op. Subscriber exceptions are logged and swallowed so one bad callback cannot blackhole the rest.

**Hook integration.** Every existing detection path inside `S0maLoader.exec_module` and `S0maDSLLoader.exec_module` now records one anomaly per detected entity (one per missing doc declaration, one per unregistered class/function). Strict-mode detections carry `severity=ERROR` (the import is about to raise); lenient-mode detections carry `severity=WARNING` (the import proceeds with a warning). The pre-0.4.0 warning / exception behaviour is preserved unchanged — the anomaly surface is additive observability.

**Layer attribution.** `layer` is populated from `registry._modules[name].layer` when the offending module has previously registered module metadata. Most anomalies fire before any registration completes for the module, so `None` is the common case; downstream code should not depend on `layer` being set.

**Buffer growth.** The buffer is unbounded — it is sized only by the number of detections, not by registered components. Long-running processes that never poll should subscribe instead, or call `clear_import_hook_anomalies()` after each drain.

**Thread safety.** Append, snapshot, clear, subscribe, and dispatch all run under the same `ComponentRegistry._lock` that protects registrations. Concurrent registration + anomaly recording from multiple threads cannot lose records or interleave a subscriber dispatch with another thread's append.

---

## 5. The Contract System

### 5.1 The `Contract` Dataclass

Contracts declare behavioral expectations. They are the system's promises about what a component does, what it requires, and how it performs.

```python
from s0ma.models import Contract, ConfigurableProperty, ProtocolContract

Contract(
    preconditions=["input is not None", "input.id is a valid UUID"],
    postconditions=["return value contains the input's ID"],
    invariants=["output is always a valid JSON string"],
    max_latency_ms=100,
    error_rate_threshold=0.01,
    input_type="request: ProcessingRequest",
    output_type="ProcessingResult",
    configurable_properties={
        "max_batch_size": ConfigurableProperty(
            type="int",
            default=10,
            constraints={"min": 1, "max": 1000},
            description="Maximum items per processing batch",
        ),
    },
    protocol=ProtocolContract(
        protocol_type="websocket",
        message_types={
            "request": {"id": "str", "payload": "dict"},
            "response": {"id": "str", "result": "dict", "status": "str"},
        },
        description="Real-time processing protocol",
    ),
)
```

### 5.2 Contract Fields

| Field | Type | Purpose | Validation |
|-------|------|---------|------------|
| `preconditions` | `list[str]` | What must be true before invocation | — |
| `postconditions` | `list[str]` | What the component guarantees after execution | — |
| `invariants` | `list[str]` | Properties that must always hold | — |
| `max_latency_ms` | `float \| None` | Performance ceiling | Must be positive |
| `error_rate_threshold` | `float \| None` | Maximum acceptable error rate | Must be 0.0–1.0 |
| `input_type` | `str \| None` | Description of expected input | — |
| `output_type` | `str \| None` | Description of expected output | — |
| `configurable_properties` | `dict[str, ConfigurableProperty] \| None` | Runtime-adjustable settings | See Section 5.2.1 |
| `protocol` | `ProtocolContract \| None` | Cross-boundary interface contract | See Section 5.2.2 |

All fields are optional. An empty `Contract()` is valid but provides no verification value.

#### 5.2.1 Configurable Properties

Runtime-changeable aspects of a component: theme colors, labels, layout options, batch sizes. Distinct from structural properties that require code changes.

```python
ConfigurableProperty(
    type="int",              # "str", "int", "float", "bool", or "enum"
    default=10,              # Must match declared type
    description="Maximum items to display",
    constraints={"min": 1, "max": 100},  # Optional
    category="Display",      # Optional: UI grouping hint
)
```

**Supported types and constraints:**

| Type | Default Must Be | Constraints |
|------|----------------|-------------|
| `"str"` | `str` | — |
| `"int"` | `int` | `min`, `max` (min < max) |
| `"float"` | `int` or `float` | `min`, `max` (min < max) |
| `"bool"` | `bool` | — |
| `"enum"` | One of `allowed_values` | `allowed_values` (non-empty list) |

Validation occurs at construction time. Invalid properties raise `RegistrationError` immediately — fail-fast at decoration time, not at runtime.

#### 5.2.2 Protocol Contracts

Cross-boundary interface specifications for WebSocket, REST, gRPC, IPC — interfaces that span the Python/non-Python boundary.

```python
ProtocolContract(
    protocol_type="websocket",   # "websocket", "rest", "grpc", "ipc", etc.
    message_types={              # Maps message names to field schemas
        "chat_message": {"role": "str", "content": "str"},
        "error": {"code": "int", "message": "str"},
    },
    description="Real-time chat protocol",
)
```

Protocol contracts are **declarative metadata only** in the current phase. Runtime verification of protocol conformance is deferred. The value now is in *capturing* the contract in the self-model so the system knows the interface exists.

### 5.3 The `ResourceProfile` Dataclass

Expected resource usage for interoception monitoring:

```python
ResourceProfile(
    expected_memory_mb=256.0,
    expected_latency_p50_ms=10.0,
    expected_latency_p99_ms=100.0,
    expected_error_rate=0.001,
    expected_call_frequency_per_min=1000.0,
)
```

| Field | Type | Purpose |
|-------|------|---------|
| `expected_memory_mb` | `float \| None` | Expected memory consumption |
| `expected_latency_p50_ms` | `float \| None` | Expected median latency |
| `expected_latency_p99_ms` | `float \| None` | Expected tail latency |
| `expected_error_rate` | `float \| None` | Expected error frequency (0.0–1.0) |
| `expected_call_frequency_per_min` | `float \| None` | Expected invocation rate |

The interoception verifier compares runtime metrics against these expectations. Components without a `ResourceProfile` are skipped by interoception verification.

### 5.4 Serialization

All core data models support full round-trip serialization:

```python
# Serialize
contract_dict = contract.to_dict()
spec_dict = component_spec.to_dict()
profile_dict = resource_profile.to_dict()

# Deserialize (with validation and enum conversion)
contract = Contract.from_dict(contract_dict)
spec = ComponentSpec.from_dict(spec_dict)        # Converts "SERVICE" -> ComponentKind.SERVICE
profile = ResourceProfile.from_dict(profile_dict)
```

`from_dict()` methods validate the reconstructed objects and convert string enum names to enum values. This enables LLM-driven workflows where component specifications arrive as JSON.

### 5.5 Helpful Error Messages

Invalid keyword arguments to `Contract`, `ComponentSpec`, `ResourceProfile`, or `ConfigurableProperty` raise `RegistrationError` with a message listing all valid fields:

```
RegistrationError: Contract() received unexpected keyword argument.
Valid fields are: preconditions, postconditions, invariants,
max_latency_ms, error_rate_threshold, input_type, output_type,
configurable_properties, protocol.
```

This is specifically designed for LLM-generated code, which may use outdated examples or incorrect field names.

---

## 6. The Verification Engine

### 6.1 Architecture

The verification engine answers one question: **does the self-model match reality?**

Four independent verifiers run in sequence, each checking a different dimension:

```
s0ma.verify(registry)
       |
       v
  StructuralVerifier    -> Code structure matches registry declarations?
       |
       v
  ContractVerifier      -> Runtime behavior matches declared contracts?
       |
       v
  InteroceptionVerifier -> Resource usage matches declared profiles?
       |
       v
  CoverageAuditor       -> Is all code reachable and used?
       |
       v
  VerificationReport (aggregated anomalies, pass/fail, LLM-readable explanation)
```

### 6.2 Verification Scopes

| Scope | Verifier | What It Checks |
|-------|----------|----------------|
| `STRUCTURAL` | `StructuralVerifier` | Code structure matches registry declarations |
| `CONTRACT` | `ContractVerifier` | Runtime behavior matches declared contracts |
| `INTEROCEPTION` | `InteroceptionVerifier` | Resource usage matches declared `ResourceProfile` |
| `COVERAGE` | `CoverageAuditor` | Code reachability and usage analysis |

### 6.3 The Structural Verifier

AST-based comparison of registry against source code. The most critical verifier — it detects when the self-model has drifted from the code it describes.

**Checks performed:**

| Check | Detects | Anomaly Kind |
|-------|---------|-------------|
| Phantom limb detection | Registry entry with no corresponding source code | `PHANTOM_LIMB` |
| Signature verification | Function/class signature differs from declared contracts | `WARNING` |
| Dependency accuracy | Declared `dependencies` do not match actual imports | `WARNING` |
| Metadata accuracy | Module path, source file, qualified name are wrong | `WARNING` |
| Layer conformance | Cross-layer dependency violations | `WARNING` |
| Component completeness | Missing intent, version, or dependencies | `INFO` |
| Dependency cycle detection | Circular dependency chains | `ERROR` |

**Advanced analysis models:**

- **Murphy's Reflexion Model:** Classifies findings into convergences (model and code agree), divergences (model and code conflict), and absences (expected elements missing).
- **de Silva Erosion Coverage:** Measures what percentage of the self-model is automatically verifiable.

### 6.4 The Contract Verifier

Checks whether runtime behavior matches declared contracts:

- Contract coverage analysis: what percentage of declared contracts have callable backing
- Performance threshold verification: actual latency vs declared `max_latency_ms`
- Error rate verification: actual error rate vs declared `error_rate_threshold`
- Controlled via `S0MA_VERIFY_CONTRACTS` for ordinary runtime/development
  use. As of 0.14, a caller-pinned score/check gate refuses to compute while
  `S0MA_VERIFY_CONTRACTS=0`; disabled verification cannot be gate evidence.

### 6.5 The Interoception Verifier

Runtime performance monitoring — the system's awareness of its own physiological state.

**MetricsCollector** (thread-safe):
- Tracks per-component: `call_count`, `error_count`, `latencies_ns` (ring buffer)
- Computes: `error_rate`, `latency_p50_ms`, `latency_p99_ms`, `call_frequency_per_min`
- Nanosecond precision via `time.perf_counter_ns()`
- Windowed aggregation (default 60 seconds)

**Instrumentation (opt-in):**

```python
from s0ma.verifiers.interoception import instrument, monitor_call

# Decorator form
@instrument
def my_function():
    ...

# Context manager form
with monitor_call("MyComponent"):
    ...
```

**Verification:** Compares collected metrics against declared `ResourceProfile`. Components without a profile are skipped. Exceedances produce `INFLAMMATION` anomalies.

### 6.6 The Coverage Auditor

Dead code detection using multiple data sources:

1. **Registry data** — what is declared
2. **AST analysis** — what exists in source files
3. **Import analysis** — what is actually imported
4. **Runtime metrics** — what is actually called (from `MetricsCollector`)
5. **Test coverage data** — what is tested (from pytest-cov)

Detected pathologies: `PHANTOM_LIMB`, `VESTIGIAL_ORGAN`, `IMMUNE_RESPONSE`, `ATROPHIED_MUSCLE`, `INFLAMMATION`.

**Automation metric** (Kounev & Spinner 2015): percentage of the self-model that is automatically verifiable without human intervention.

### 6.7 The Verification Report

```python
report = s0ma.verify(registry)

if not report.passed:
    # LLM-readable explanation of all anomalies
    print(report.explain_for_llm())

# Detailed human-readable report
print(report.describe())
```

**Report structure:**

```
=== s0ma Verification Report ===

SYSTEM: s0ma-core v0.1.0
COMPONENTS: 12 registered
SCAN TIME: 2026-03-22T14:30:00Z

+ Structural Integrity: 11/12 components match
+ Contract Compliance: 10/12 contracts valid
+ Dependency Graph: All declared dependencies exist
x Coverage Audit: 1 anomaly detected

ANOMALIES:
  [VESTIGIAL_ORGAN] components/plugins/old_weather.py
    - OldWeatherPlugin is registered but has 0 callers
    - Recommendation: Remove or mark as deprecated

  [INFLAMMATION] components/router.py
    - ChatRouter declares max_latency_ms: 50
    - Actual measured latency: 120ms (p95)
    - Recommendation: Update contract or optimize implementation

HEALTH: 2 anomalies -- resolve before deployment
```

### 6.8 Incremental Verification

For single-component checks after modifications:

```python
from s0ma.verifiers import verify_incremental

result = verify_incremental(registry, "MyComponent")
```

Runs only the structural verifier against the named component. Faster than full verification for iterative development.

---

## 7. The Import Hook

### 7.1 Mechanism

The import hook is a `sys.meta_path` finder/loader pair installed at the highest priority position. It consists of two classes:

| Class | Role |
|-------|------|
| `S0maFinder` | Determines whether a module is under `project_root` and should be subject to enforcement |
| `S0maLoader` | Wraps the standard Python loader, adding a post-load verification step |

### 7.2 What the Hook Enforces

After a module under `project_root` finishes loading, the hook scans all module-level attributes:

- **Public names** (not starting with `_`): Must have `@component` or `@internal`
- **Private names** (starting with `_`): Exempt — Python convention is sufficient
- **Framework allowlist**: s0ma's own modules are automatically exempt
- **Documentation markers** (§18): Modules that advertise `__s0ma_doc_ref__`, `__s0ma_doc_guide__`, or `__s0ma_example__` must have each advertised name registered in the corresponding store (`_doc_refs`, `_doc_guides`, `_examples`) by the time the module body finishes executing. Unresolved markers produce a doc-specific diagnostic distinct from the unregistered-component diagnostic.

### 7.3 Strictness Modes

| Mode | Behavior |
|------|----------|
| `strict=True` (default) | Unregistered public code raises `UnregisteredComponentError` |
| `strict=False` | Unregistered public code emits a warning but allows the import |

### 7.4 Hook Lifecycle

```python
from s0ma.import_hook import install_import_hook, uninstall_import_hook, is_hook_installed

# Install (normally done by s0ma.initialize())
install_import_hook(project_root="./src", allowlist=[], strict=True)

# Check status
assert is_hook_installed()

# Uninstall (rare — mainly for testing)
uninstall_import_hook()
```

### 7.5 What the Hook Does NOT Do

- It does not intercept imports outside `project_root`
- It does not wrap or proxy imported objects
- It does not modify the imported module's code
- It does not add runtime overhead to function/method calls
- It does not enforce dependencies (that is the structural verifier's job)

The hook's sole purpose is to ensure the self-model is complete at the point of import.

### 7.6 Anomaly Observability (0.4.0)

Every detection the hook performs is also recorded on the registry as an `ImportHookAnomaly` (see §4.12). Strict-mode detections still raise `UnregisteredComponentError` and lenient-mode detections still emit warnings; the anomaly buffer is an additional, structured channel that downstream consumers (the B1 IMMUNE_RESPONSE detection layer in particular) can poll via `registry.import_hook_anomalies` or subscribe to via `registry.subscribe_import_hook_anomalies(callback)`. See §4.12 for the full surface — the hook itself is unchanged from §7.1–7.5 behaviour.

---

## 8. The Self-Model Interface

### 8.1 Purpose

`SelfModelInterface` is the query API for the self-model. It transforms raw registry data into natural language text optimized for LLM consumption and human readability.

### 8.2 Core Methods

```python
from s0ma import SelfModelInterface

smi = SelfModelInterface(registry)
```

| Method | Returns | Use Case |
|--------|---------|----------|
| `describe_system()` | Full system overview | LLM system prompt context |
| `describe_component(name)` | Single component detail | Understanding a specific component |
| `get_architecture_context()` | Complete architectural overview | Planning changes |
| `get_impact_analysis(name)` | What breaks if this changes | Pre-modification risk assessment |
| `get_available_extension_points()` | Where new components can be added | Finding safe insertion points |
| `validate_proposed_component(spec)` | Pre-creation validation | Checking before registering |
| `get_recent_changes(limit=10)` | Lifecycle event history | Understanding recent modifications |

### 8.3 Audience-Aware Output

Standard methods (`describe_system()`, `get_architecture_context()`) are designed for dual consumption: readable by developers, parseable by LLMs answering architectural questions.

But for LLMs *generating code*, this same output can **actively mislead**: LLMs see layer names like `DOMAIN` and infer they are Python packages. They see framework module paths and try to import from them.

Two audience-specific methods solve this:

#### `describe_for_code_generation(target_package)`

Output optimized for LLM code generation prompts:

1. **Explicit import guidance** — States where generated code should import from
2. **Layer annotation** — Explains that layer names are classification labels, not packages
3. **Framework components annotated as non-importable** — Prevents LLMs from inferring they are import roots
4. **`@component` decorator template** — Concrete anchor using `target_package` naming
5. **Configurable property schemas** — Runtime configuration context

```python
context = smi.describe_for_code_generation("myapp.services")
```

#### `describe_for_agent(context, *, target_package=None)`

Dispatch method routing to the most appropriate output:

| Context | Delegates To | Use When |
|---------|-------------|----------|
| `"code_generation"` | `describe_for_code_generation()` | Generating new code. Requires `target_package`. |
| `"architectural_review"` | `get_architecture_context()` | Planning changes. |
| `"debugging"` | Internal method | Diagnosing problems (anomalies + dependency graph). |

---

## 9. The Lifecycle System

### 9.1 Purpose

The `LifecycleManager` wraps `ComponentRegistry` with safety guarantees for runtime mutations:

- **Pre-validation** before any mutation
- **Post-verification** (structural verifier) after mutation
- **Automatic rollback** if verification fails
- **Audit logging** of all lifecycle events

### 9.2 Operations

```python
from s0ma import LifecycleManager

lm = LifecycleManager(registry)

# Create a component at runtime
lm.create_component_at_runtime(
    name="DynamicProcessor",
    kind=ComponentKind.SERVICE,
    layer=Layer.APPLICATION,
    intent="Dynamically created processor for incoming data streams",
)

# Update a component's metadata
lm.update_component("DynamicProcessor",
    intent="Updated: Processes and validates incoming data streams",
    contracts=Contract(max_latency_ms=200),
)

# Remove a component (checks dependents first)
lm.remove_component("DynamicProcessor")
```

### 9.3 Transactions

Atomic multi-step operations with automatic rollback:

```python
with lm.transaction() as txn:
    txn.create_component(name="ServiceA", kind=..., layer=..., intent=...)
    txn.create_component(name="ServiceB", kind=..., layer=..., intent=...,
                         dependencies=["ServiceA"])
    # If any step fails, all previous steps are rolled back
    # commit() is called automatically on successful exit
```

### 9.4 Event Audit Trail

Every lifecycle operation is recorded as a `LifecycleEvent`:

```python
for event in lm.events:
    print(f"{event.action} {event.component_name} at {event.timestamp}: "
          f"{'success' if event.success else event.error_message}")
```

---

## 10. The External API Surface

### 10.1 REST API

Requires: `pip install -e "../s0ma[api]"` (s0ma is a private repo; PyPI publication is deferred — install editable from a sibling clone).

```python
from s0ma.api.rest import create_app

app = create_app(registry)
# Run with: uvicorn module:app --reload
```

**Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/self/overview` | System purpose, layers, component count |
| `GET` | `/self/components` | All registered components with summaries |
| `GET` | `/self/component/{name}` | Full detail on one component |
| `GET` | `/self/health` | Verification status and anomaly count |
| `GET` | `/self/anomalies` | Current model-reality discrepancies |
| `GET` | `/self/graph` | Dependency graph (JSON adjacency list + Graphviz DOT) |
| `GET` | `/self/impact/{name}` | What breaks if this component changes |
| `GET` | `/self/extensions` | Where new components can be added safely |
| `POST` | `/self/query` | Natural language query |
| `GET` | `/self/docs` | Registry-wide documentation overview (doc-refs + doc-guides + examples) — see §18 |
| `GET` | `/self/doc/{name}` | Doc-ref or doc-guide detail; 404 on miss (response carries `kind` to disambiguate) |
| `GET` | `/self/examples` | All registered examples |
| `GET` | `/self/example/{name}` | Single example detail (body + source span) |
| `GET` | `/self/drift` | Transitive content-hash drift status; optional `?transpiler_version=` |

All responses include both a `text` field (natural language for LLM consumption) and structured data fields (for programmatic access).

### 10.2 MCP Server

Requires: `pip install -e "../s0ma[mcp]"` (s0ma is a private repo; PyPI publication is deferred — install editable from a sibling clone).

```python
from s0ma.api.mcp_server import create_mcp_server

server = create_mcp_server(registry)
```

**Resources** (read-only data):

| URI | Returns |
|-----|---------|
| `s0ma://docs/user-guide` | Complete user guide |
| `s0ma://docs/compliance-rules` | Appendix C compliance rules |
| `s0ma://docs/architecture` | Architecture document |
| `s0ma://model/component-template` | Real registered component as a copyable template |
| `s0ma://model/registry-summary` | Live system overview from the self-model |
| `s0ma://docs/registered-docs` | Registry-wide documentation overview (live; §18) |
| `s0ma://model/examples-for/{component}` | Examples demonstrating a given component |
| `s0ma://model/docs-for/{component}` | Doc-refs and doc-guides covering a given component |

**Teaching Tools** (callable functions):

| Tool | Purpose |
|------|---------|
| `learn_about_s0ma(topic)` | Topic-based documentation lookup with live examples |
| `get_component_example(kind?)` | Real component formatted as a copyable template |
| `get_compliance_checklist()` | Quick pre-flight checklist |
| `get_examples_for(component)` | Examples demonstrating a given component (§18) — explicit tool mirror of the templated `examples-for` resource for clients that do not expose templated-resource reads |

All content is served from actual source files, not duplicated documentation.

### 10.3 Natural Language Query Engine

The `POST /self/query` endpoint accepts natural language questions:

```json
{"question": "What component handles user authentication?"}
{"question": "What are the dependencies of the ChatRouter?"}
{"question": "Which components have the highest complexity?"}
{"question": "What would break if I removed the TimezoneResolver?"}
```

The query engine is **rule-based** — it categorizes questions and dispatches to appropriate `SelfModelInterface` methods. No LLM dependency at query time. The self-model answers questions about itself without external AI assistance.

---

## 11. The Registry

### 11.1 Storage Model

The `ComponentRegistry` maintains nine primary stores:

| Store | Type | Purpose |
|-------|------|---------|
| `_components` | `dict[str, ComponentSpec]` | Component registrations by name |
| `_modules` | `dict[str, ModuleMetadata]` | Module-level metadata |
| `_edges` | `list[RelationshipEdge]` | Explicit relationship edges |
| `_test_registrations` | `dict[str, TestRegistration]` | Test component registrations |
| `_ir_store` | `dict[str, dict[str, object]]` | Transpiler IR data keyed by module name |
| `_plugins` | `dict[str, PluginRegistration]` | Registered plugin metadata with dependency validation |
| `_doc_refs` | `dict[str, DocRefRegistration]` | Generated reference artifacts (§18) |
| `_doc_guides` | `dict[str, DocGuideRegistration]` | Hand-authored guides (§18) |
| `_examples` | `dict[str, ExampleRegistration]` | Executable code samples (§18) |

Optional SQLite persistence at `.s0ma/registry.db` survives process restarts.

### 11.2 Core Operations

**Registration:**
```python
registry.register(spec)                    # Register (raises on duplicate)
registry.register(spec, idempotent=True)  # Idempotent registration
registry.register_or_update(spec)         # Upsert semantics
registry.register_from_module(module)     # Scan module, register @component entities
```

**Retrieval:**
```python
registry.get("name")                      # ComponentSpec or None
registry.get_all()                        # dict[str, ComponentSpec] copy
registry.query_by_layer(Layer.DOMAIN)     # list[ComponentSpec]
registry.query_by_kind(ComponentKind.SERVICE)  # list[ComponentSpec]
registry.contains("name")                # bool
len(registry)                             # Component count
"name" in registry                        # Containment check
```

**Dependency Graph:**
```python
registry.get_dependencies("name")         # Resolved deps as list[ComponentSpec]
registry.get_dependents("name")           # Reverse lookup: who depends on this
registry.get_dependency_graph()           # Full graph as dict[str, list[str]]
registry.import_order()                   # Topologically sorted module paths
```

**IR Storage:**
```python
registry.store_ir("module_name", ir_data) # Store transpiler IR data for a module
registry.get_ir("module_name")            # Retrieve IR data (or None)
registry.get_all_ir()                     # All stored IR data
```

**Plugin Registration:**
```python
registry.register_plugin(                 # Register a plugin with dep validation
    name="...", version="...", intent="...",
    registers=["..."], requires_core=["..."],
)
registry.get_plugin("name")              # PluginRegistration or None
registry.get_all_plugins()               # All registered plugins
```

**Serialization:**
```python
registry.to_dict()                        # Complete state as JSON-serializable dict
registry.snapshot()                       # Frozen RegistrySnapshot
```

**Lifecycle:**
```python
registry.unregister("name")              # Remove by name
registry.reset()                          # Clear all (memory + persistence)
registry.close()                          # Close SQLite connection
```

**Global Singleton:**
```python
from s0ma.registry import get_registry, set_registry, reset_registry

get_registry(persist=True)               # Get or create global singleton
set_registry(registry)                   # Replace global singleton
reset_registry()                          # Clear and remove global singleton
```

### 11.3 The Snapshot

`registry.snapshot()` returns a `RegistrySnapshot` — a frozen, serializable view of the registry:

```python
snap = registry.snapshot()
snap.components          # dict of all component specs
snap.component_count     # Total components
snap.framework_component_count  # Framework components
snap.layers              # Layer distribution
snap.dependency_graph    # Full graph
snap.modules             # dict of ModuleMetadata
snap.edges               # list of RelationshipEdge
snap.test_registrations  # dict of TestRegistration
snap.ir                  # dict of transpiler IR data
snap.plugins             # dict of PluginRegistration
snap.snapshot_at         # Timestamp

# Serialization
snap.to_dict()           # dict (includes all stores)
snap.to_json()           # JSON string
snap.describe()          # Human-readable text (includes modules,
                         # relationships, test coverage, plugins
                         # sections when data is present)
```

---

## 12. The Bootstrap Problem & Solution

### 12.1 The Problem

The `@component` decorator registers entities into the `ComponentRegistry`. But the `ComponentRegistry` class itself should be registered as a framework component. `@component` cannot decorate `ComponentRegistry` because `@component` depends on `ComponentRegistry` to exist first.

This is the chicken-and-egg problem of a self-aware system.

### 12.2 The Solution

Two-phase bootstrap:

**Phase 1:** Load all framework modules normally (no `@component` decorators on framework classes).

**Phase 2:** `bootstrap_register(registry)` manually constructs `ComponentSpec` objects for all 44 framework components and registers them directly — bypassing the `@component` decorator entirely.

```python
from s0ma._bootstrap import bootstrap_register, EXPECTED_FRAMEWORK_COMPONENT_COUNT

# Phase 2: Register s0ma's own components
bootstrap_register(registry)
assert len(registry) >= EXPECTED_FRAMEWORK_COMPONENT_COUNT
```

**Validation:** The bootstrap test verifies that manually-constructed specs produce results identical to what `@component` would produce. If the bootstrap specs drift from the actual classes, the test fails. The bootstrap is the canary.

---

## 13. Testing Infrastructure

### 13.1 The Core Problem

The `@component` decorator fires exactly **once** at import time. Python caches imported modules in `sys.modules`. When you call `reset_registry()` for test isolation, already-imported modules retain their cached state — `@component` decorators do **not** re-fire.

**Symptom:** After `reset_registry()` + `import_module("myapp.mymodule")`, components are missing from the fresh registry.

### 13.2 `fresh_registry()` — Context Manager

The primary isolation primitive:

```python
from s0ma.testing import fresh_registry

def test_my_component():
    with fresh_registry(".", ["myapp.components", "myapp.services"]) as registry:
        spec = registry.get("MyService")
        assert spec is not None
    # Original global registry is restored here
```

**What it does:**
1. Creates a fresh in-memory registry and sets it as the global singleton
2. Evicts all modules matching prefixes from `sys.modules`
3. Re-imports evicted modules (parents before children), triggering `@component` decorators
4. Yields the populated registry
5. Restores the original global registry on exit

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `project_root` | required | Root directory of the project |
| `module_prefixes` | required | Module name prefixes to evict and re-import |
| `persist` | `False` | SQLite persistence for the fresh registry |
| `strict_dependencies` | `False` | Raise on unresolved dependencies |

### 13.3 `isolate_registry()` — Isolated Scope

For tests that need synthetic components without module re-imports:

```python
from s0ma.testing import isolate_registry

def test_registry_logic():
    with isolate_registry() as registry:
        registry.register(ComponentSpec(
            name="SyntheticService",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A synthetic component used only in this test",
            module_path="tests.synthetic",
            qualified_name="tests.synthetic.SyntheticService",
        ))
        assert registry.contains("SyntheticService")
    # Original global registry restored; SyntheticService is gone
```

### 13.4 `reinitialize_for_test()` — Imperative Variant

Non-context-manager version for `unittest.TestCase`:

```python
from s0ma.testing import reinitialize_for_test

class MyTestCase(unittest.TestCase):
    def setUp(self):
        self.registry = reinitialize_for_test(".", ["myapp.components"])
```

Caller is responsible for cleanup.

### 13.5 When to Use Each

| Scenario | Utility |
|----------|---------|
| Need real application components re-imported | `fresh_registry` |
| Need empty sandbox for synthetic specs | `isolate_registry` |
| `unittest.TestCase` setup (no context manager) | `reinitialize_for_test` |
| Module hot-reload in production | `register_from_module(module)` |

---

## 14. Import-Ordering Utilities

### 14.1 The Problem

Modules with dependencies must be imported after their dependencies. A manually-maintained import order list is fragile and error-prone.

### 14.2 `topological_sort_modules()`

Pure algorithm — Kahn's algorithm for dependency-safe ordering:

```python
from s0ma.utils import topological_sort_modules

sorted_order = topological_sort_modules([
    ("myapp.api", ["myapp.services"]),
    ("myapp.services", ["myapp.models"]),
    ("myapp.models", []),
])
# Returns: ["myapp.models", "myapp.services", "myapp.api"]
```

Circular dependencies raise `RegistrationError` with cycle path.

### 14.3 `bootstrap_modules()`

Highest-level utility — imports and registers in dependency-safe order:

```python
from s0ma.utils import bootstrap_modules

registered = bootstrap_modules([
    "myapp.api",       # depends on myapp.services
    "myapp.models",    # no dependencies
    "myapp.services",  # depends on myapp.models
])
# Imports in order: myapp.models, myapp.services, myapp.api
# Returns: list[ComponentSpec]
```

### 14.4 `registry.import_order()`

Returns topologically sorted module paths from the live registry:

```python
order = registry.import_order()
```

---

## 15. Exception Hierarchy

```
S0maError (base)
  |
  +-- RegistrationError
  |     Component registration failure: missing fields, duplicate name,
  |     invalid metadata, self-dependency, invalid keyword arguments.
  |
  +-- UnregisteredComponentError
  |     Import hook detected unregistered public code under project root.
  |
  +-- ContractViolationError
  |     Runtime behavior does not match declared contracts.
  |
  +-- RegistryIntegrityError
  |     Registry internal state inconsistent: orphaned dependencies,
  |     phantom limbs, SQLite corruption.
  |
  +-- BootstrapError
  |     s0ma's own framework components cannot describe themselves.
  |     Indicates a framework-level issue.
  |
  +-- LifecycleError
  |     Lifecycle operation failed: pre-validation rejected,
  |     post-verification failed, dependency check blocked removal.
  |
  +-- TransactionError
        Transaction commit or rollback failed.
```

---

## 16. Coding Agent Rulebook

**These rules are absolute. Violating any produces an invalid s0ma application.**

### 16.1 Universal Rules

| Rule | Requirement | Enforcement |
|------|------------|-------------|
| **R-01** | `s0ma.initialize()` must be called before importing any application modules. | ENFORCED (import hook) |
| **R-02** | Every public class or function under the project root must use `@component` or `@internal`. | ENFORCED (import hook) |
| **R-03** | Every `@component` must specify all four required fields: `name`, `kind`, `layer`, `intent`. | ENFORCED (decorator validation) |
| **R-04** | `name` must be globally unique across all registered components, including framework components. | ENFORCED (registry) |
| **R-05** | `kind` must be a `ComponentKind` enum value, not a string. | ENFORCED (decorator validation) |
| **R-06** | `layer` must be a `Layer` enum value, not a string. | ENFORCED (decorator validation) |
| **R-07** | `intent` must be at least 10 characters and describe what the component does in plain English. | ENFORCED (decorator validation) |
| **R-08** | `dependencies` must list the names of other registered components this component depends on. Names must exactly match. | VERIFIED (structural verifier) |
| **R-09** | A component must not list itself in its own `dependencies`. | ENFORCED (decorator validation) |
| **R-10** | When modifying a component, update `intent`, `contracts`, and `dependencies` if they no longer accurately describe the component. | VERIFIED (structural verifier) |
| **R-11** | Run `s0ma.verify()` after every change. Verify incrementally, not in batches. | CONVENTION |
| **R-12** | Before writing any code, query the self-model to understand the system. | CONVENTION |
| **R-13** | Before removing a component, check what depends on it via impact analysis. | CONVENTION |
| **R-14** | All dependent components must be updated before removing a dependency. | VERIFIED (structural verifier) |
| **R-15** | Use `@internal` for private helpers. Never leave public helpers undecorated. | ENFORCED (import hook) |
| **R-16** | Write `intent` descriptions for other agents: clear enough that a different agent, with no context, can understand the component. | CONVENTION |
| **R-17** | `contracts` should accurately reflect actual inputs, outputs, invariants, and performance bounds. Mismatches erode trust. | VERIFIED (contract verifier) |
| **R-18** | Use project-name prefixes for component names to avoid collision with framework-reserved names. | CONVENTION |
| **R-19** | Place shared enums and dataclasses in a `models.py` with `@internal`. Do not scatter shared types. | CONVENTION |
| **R-20** | Do not register non-Python files. Register the Python component that owns them. | CONVENTION |
| **R-21** | When a module grows beyond 200-300 lines, split helpers into `_`-prefixed companion modules with `@internal`. | CONVENTION |
| **R-22** | Documentation artifacts (`doc-ref`, `doc-guide`, `example` — see §18) must be registered via `register_doc_ref` / `register_doc_guide` / `register_example`. The same registration-as-creation rule that governs components governs documentation. | ENFORCED (import hook) |
| **R-23** | An `example` registration must carry a non-empty `demonstrates` list of `EntityRef`s identifying the components it exercises. An example that demonstrates nothing has no reason to exist in the self-model. | ENFORCED (boundary validation) |
| **R-24** | When modifying a component, query `get_docs_for_component(name)` and `get_examples_for_component(name)`. Update affected docs and examples atomically in the same change. | VERIFIED (drift check) |
| **R-25** | Never embed a raw code sample in a doc-guide body. Reference a registered example via `{{example::<name>}}`. This preserves the invariant that every code sample in the system is executable and discoverable. | ENFORCED (DSL validation) |
| **R-26** | Never alter a stored `content_hash` by hand. Hashes are produced by `s0ma.hashing.content_hash(...)` at emission time; drift detection compares stored vs. recomputed. Editing the stored value defeats detection. | CONVENTION |

### 16.2 Enforcement Levels

| Level | Meaning |
|-------|---------|
| **ENFORCED** | Violation is caught automatically by the import hook, decorator validation, or registry at runtime. The system will not function if this rule is broken. |
| **VERIFIED** | Violation is detected by `s0ma.verify()` and reported as an anomaly. The system may still run, but the self-model is degraded. |
| **CONVENTION** | Not automatically enforced. Following this rule is expected for a well-formed s0ma application. |

### 16.3 Decision Tree

```
New functionality?
  Does it serve the system independently?    -> @component (SERVICE, FUNCTION, ORCHESTRATOR, ADAPTER)
  Is it a data structure / type / enum?      -> @internal (put in models.py)
  Is it a private helper for a component?    -> @internal or _ prefix
  Is it an abstract base class?              -> @internal (default) or @component (if architecturally significant)

Modifying a component?
  Did the purpose change?                    -> Update intent
  Did the inputs/outputs change?             -> Update contracts
  Did you add/remove imports of components?  -> Update dependencies
  Done?                                      -> Run s0ma.verify()

Removing a component?
  Check impact analysis first                -> SelfModelInterface.get_impact_analysis()
  Update all dependents                      -> Remove from their dependencies lists
  Delete the code                            -> Remove @component-decorated entity
  Verify                                     -> Run s0ma.verify()
```

### 16.4 What the Agent Must Never Do

- Never import application modules before calling `s0ma.initialize()`
- Never leave public code undecorated under the project root
- Never use strings where enum values are required (`kind`, `layer`)
- Never write an `intent` shorter than 10 characters or use placeholder text
- Never delete a component without checking impact analysis first
- Never batch changes and verify later — verify incrementally
- Never skip updating `intent`, `contracts`, or `dependencies` when modifying behavior
- Never use `ComponentKind.FRAMEWORK` for application code
- Never use `Layer.FRAMEWORK` for application code
- Never assume the self-model is optional or advisory — it is load-bearing
- Never register a `doc-ref`, `doc-guide`, or `example` with invalid `format`, `output`, `runs_in`, or empty `demonstrates` — validation is deliberate and its errors are actionable
- Never hand-edit a stored `content_hash` — recompute via `s0ma.hashing.content_hash(...)`
- Never embed a raw code sample in a doc-guide body — reference a registered `example` instead

---

## 17. Complete Example

A fully compliant s0ma application demonstrating: initialization, registration, contracts, dependencies, verification, self-model queries, and the `@internal` decorator.

```python
# main.py — Application entry point
import s0ma

# Step 1: Initialize BEFORE any application imports
registry = s0ma.initialize(project_root="./src")

# Step 2: Now import application modules (import hook is active)
from myapp.models import TaskData, Priority
from myapp.task_service import TaskService
from myapp.task_validator import TaskValidator

# Step 3: Verify
report = s0ma.verify(registry)
assert report.passed, report.explain_for_llm()

# Step 4: Query the self-model
smi = s0ma.SelfModelInterface(registry)
print(smi.describe_system())
print(smi.get_impact_analysis("TaskService"))
```

```python
# src/myapp/models.py — Shared types (all @internal)
from s0ma.decorators import internal
from enum import Enum
from dataclasses import dataclass

@internal
class Priority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@internal
@dataclass
class TaskData:
    title: str
    priority: Priority
    assignee: str | None = None
    completed: bool = False
```

```python
# src/myapp/task_validator.py — Validation component
from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer
from s0ma.models import Contract

from myapp.models import TaskData

@component(
    name="TaskValidator",
    kind=ComponentKind.FUNCTION,
    layer=Layer.DOMAIN,
    intent="Validates task data integrity: ensures title is non-empty, "
           "priority is valid, and assignee format is correct when present",
    contracts=Contract(
        input_type="task: TaskData",
        output_type="bool",
        preconditions=["task is not None"],
        postconditions=["returns True if all validations pass"],
        invariants=["never modifies the input task"],
        max_latency_ms=5,
    ),
    dependencies=[],
)
class TaskValidator:
    def validate(self, task: TaskData) -> bool:
        if not task.title or not task.title.strip():
            return False
        if task.assignee is not None and "@" not in task.assignee:
            return False
        return True
```

```python
# src/myapp/task_service.py — Service component
from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer
from s0ma.models import Contract

from myapp.models import TaskData, Priority
from myapp.task_validator import TaskValidator

@component(
    name="TaskService",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="Creates and manages tasks: validates input via TaskValidator, "
           "assigns default priority, and tracks task lifecycle",
    contracts=Contract(
        input_type="title: str, assignee: str | None",
        output_type="TaskData",
        preconditions=["title is a non-empty string"],
        postconditions=["returned TaskData has a valid priority"],
        max_latency_ms=50,
    ),
    dependencies=["TaskValidator"],
    version="1.0.0",
)
class TaskService:
    def __init__(self):
        self._validator = TaskValidator()

    def create(self, title: str, assignee: str | None = None) -> TaskData:
        task = TaskData(title=title, priority=Priority.MEDIUM, assignee=assignee)
        if not self._validator.validate(task):
            raise ValueError(f"Invalid task: {title}")
        return task

    def complete(self, task: TaskData) -> TaskData:
        return TaskData(
            title=task.title,
            priority=task.priority,
            assignee=task.assignee,
            completed=True,
        )
```

**What the self-model knows after initialization:**

```
System: myapp v1.0.0
Components: 2 application + 44 framework = 46 total

Application Components:
  TaskValidator (function, DOMAIN)
    Intent: Validates task data integrity...
    Dependencies: none
    Contracts: input=TaskData, output=bool, max_latency=5ms

  TaskService (service, DOMAIN)
    Intent: Creates and manages tasks...
    Dependencies: [TaskValidator]
    Contracts: input=title+assignee, output=TaskData, max_latency=50ms

Impact Analysis for TaskService:
  Direct dependents: none
  If TaskService changes: 0 components affected
  If TaskValidator changes: TaskService is affected (dependency)
```

---

## 18. The Documentation Subsystem

Registration-as-creation extends from code to documentation. A piece of generated reference material, a hand-authored guide, or an executable code sample cannot exist without a runtime registration that the rest of the system can query. The self-model thereby becomes the single source of truth for both *what the system is* and *what we say about it*.

### 18.1 The Three Registration Kinds

| Kind | Registry store | Purpose |
|------|----------------|---------|
| `doc-ref` | `_doc_refs` | A generated reference artifact (e.g. a Markdown API reference) that iterates over registry state. |
| `doc-guide` | `_doc_guides` | A hand-authored guide whose body may embed executable examples by reference and may carry assertions that the self-model verifies. |
| `example` | `_examples` | An executable code sample that demonstrates one or more components and runs in a subprocess as part of the test pipeline. |

All three are first-class registrations with stable names, SQLite persistence, snapshot serialization, and full reachability through `SelfModelInterface`, the REST API, and the MCP server. No documentation artifact is ever a second-class citizen of the self-model.

### 18.2 Dataclasses (public, frozen)

| Type | Fields |
|------|--------|
| `SourceSpan` | `file: str`, `start_line: int`, `end_line: int` |
| `EntityRef` | `kind: str`, `name: str`, `module: str \| None` |
| `FilterExpr` | `target_kind: str`, `predicate: str \| None`, `raw: str` |
| `Section` | `title: str`, `iterate: str \| None`, `group_by: str \| None`, `render: dict[str, Any]` |
| `AssertExpr` | `expression: str`, `source_span: SourceSpan` |
| `DocRefRegistration` | `name`, `module`, `intent`, `format`, `output`, `covers: list[FilterExpr]`, `sections: list[Section]`, `content_hash: str`, `source_span: SourceSpan` |
| `DocGuideRegistration` | `name`, `module`, `intent`, `format`, `output`, `covers: list[EntityRef]`, `asserts: list[AssertExpr]`, `examples: list[EntityRef]`, `body: str`, `content_hash: str`, `source_span: SourceSpan` |
| `ExampleRegistration` | `name`, `module`, `intent`, `demonstrates: list[EntityRef]`, `runs_in: Literal["standalone","pytest","integration"]`, `body: str`, `source_span: SourceSpan` |

All are frozen dataclasses. All are re-exported from the top-level `s0ma` package.

### 18.3 Public Registration Functions

```python
from s0ma import register_doc_ref, register_doc_guide, register_example
```

All three functions accept keyword-only arguments and return the stored registration. Each raises `RegistrationError` on duplicate `name` (unless `idempotent=True`) and `ValueError` on invalid input. Validation at the boundary:

| Field | Rule |
|-------|------|
| `format` | One of `{markdown, html, json}` |
| `output` | Non-empty relative path; no leading `/`, no `..` segments |
| `demonstrates` | Required and non-empty for examples |
| `runs_in` | One of `{standalone, pytest, integration}` |
| `name` | Globally unique within its store (module is stored but is not part of the key — matches `register_test`) |

Idempotent mode mirrors `register_test`: `idempotent=True` silently upserts, `idempotent=False` (default) raises on any collision.

### 18.4 Import-Hook Marker Attributes

Code generators (notably `s0ma-dsl`) emit three module-level marker attributes on generated `.py` output. Each marker advertises the names of the registrations the module is expected to install by the time its body finishes executing:

| Attribute | Registration | Public constant |
|-----------|-------------|-----------------|
| `__s0ma_doc_ref__` | `doc-ref` | `s0ma.import_hook.DOC_REF_MARKER_ATTR` |
| `__s0ma_doc_guide__` | `doc-guide` | `s0ma.import_hook.DOC_GUIDE_MARKER_ATTR` |
| `__s0ma_example__` | `example` | `s0ma.import_hook.EXAMPLE_MARKER_ATTR` |

The value is an iterable of `str` names, or a bare `str` as a single-name shorthand. If a marker entry does not resolve against the global registry at import completion, the hook raises `UnregisteredComponentError` in strict mode (warns in lenient mode). The diagnostic is distinct from the unregistered-component diagnostic because the remediation differs: regenerate the `.s0ma` source, not "add `@component`."

### 18.5 `RegistrySnapshot` Extensions

`RegistrySnapshot` carries the three stores and two reverse-index methods:

```python
snap = registry.snapshot()

snap.doc_refs      # dict[str, DocRefRegistration]
snap.doc_guides    # dict[str, DocGuideRegistration]
snap.examples      # dict[str, ExampleRegistration]

snap.examples_for(ref)    # → list[ExampleRegistration]
snap.docs_for(ref)        # → DocsForResult(refs, guides)
```

Both reverse-index methods accept either an `EntityRef` or a `"module::name"` / bare `"name"` string shortcut. The returned `DocsForResult` carries `.refs`, `.guides`, `is_empty()`, and `to_dict()`.

`snap.to_dict()` / `.to_json()` / `.describe()` emit the new `doc_refs` / `doc_guides` / `examples` keys only when their stores are non-empty, so existing snapshot consumers see no schema churn until the subsystem is in use.

### 18.6 `SelfModelInterface` Extensions

```python
smi.describe_docs()                              # registry-wide overview
smi.describe_doc(name)                           # doc detail by registry key
smi.get_docs_for_component(name)                 # reverse index (NL)
smi.get_examples_for_component(name)             # reverse index (NL)
smi.get_drift_status(transpiler_version="...")   # transitive hash drift
```

The five new methods are informational — they return a string and never raise on unknown names. `compute_impact_analysis(...)` / `format_impact_report(...)` now surface `affected_docs` and `affected_examples` sections when the reverse indices produce matches; rule R-24 depends on this.

### 18.7 Example Execution (`s0ma.examples`)

```python
from s0ma.examples import ExampleRunner

runner = ExampleRunner(registry, timeout_seconds=30)
for result in runner.run_all():
    print(result.summary())
```

**Execution model.** Every example runs in a child process — unconditionally, across all three `runs_in` modes. Reasons:

1. Timeouts require it. `subprocess.run(..., timeout=...)` is the only reliable cross-platform mechanism; there is no portable in-process thread-cancellation primitive.
2. In-body `@component` registrations must not contaminate the parent registry. Examples frequently register throwaway components to demonstrate a pattern; leaking those into the caller's registry would violate registration-as-creation for the system under observation.
3. A failing or hung example must not take the caller down.

**Dispatch modes:**

| Mode | Behavior |
|------|----------|
| `standalone` | Writes the body to a temp script; runs `python <script>`. |
| `pytest` | Writes the body to `test_<name>.py`; runs `python -m pytest`. |
| `integration` | Honors `S0MA_INTEGRATION_CMD` (with `{body}` substitution); falls back to `standalone` when the env var is unset. |

**Result model.** `ExampleResult` is frozen and carries `passed`, `duration_ms`, `stdout`, `stderr`, `returncode`, `timed_out`, `error`, plus a `summary()` one-liner. The runner never raises on per-example failure — every outcome surfaces as a result so `run_all` can aggregate full pipelines. `ExampleTimeoutError` is defined for consumers that want to introspect by exception type, but it is stringified onto `ExampleResult.error`; it is never propagated.

**Pytest plugin (opt-in).** `pytest --s0ma-examples` collects every registered example as a pytest item named `s0ma-example::<name>`. The `s0ma_example_timeout` `pytest.ini` key overrides the default 30-second timeout. The plugin entry point is registered unconditionally (so `pytest --help` documents the flag) but is a no-op when the flag is not passed; existing test suites are unaffected.

### 18.8 Content Hashing (`s0ma.hashing`)

```python
from s0ma import canonicalize, content_hash, HASH_ALGORITHM_VERSION

digest = content_hash(doc_registration, snap, transpiler_version="0.2.0")
# → "1:4f1acd..."
```

`canonicalize(value) -> bytes` is a deterministic byte serializer over primitives, collections, enums, and dataclasses. Invariants:

- Dict keys are sorted; set elements are sorted by their elements' own canonical form (never by `sorted()` directly — mixed-type sets must hash reliably).
- Strings are NFC-normalized before UTF-8 encoding.
- Floats are emitted via `repr` (round-trip stable).
- Every value carries a one-byte type tag and an explicit length prefix to prevent concatenation smearing.
- Unsupported types raise `TypeError`. Silent fallback to `repr` would break determinism.

`content_hash(doc_registration, snapshot, *, transpiler_version) -> str` returns a lowercase hex SHA-256 digest prefixed with `HASH_ALGORITHM_VERSION` (currently `"1"`), so stored hashes self-identify when the algorithm is bumped. The hash covers:

1. A version prefix.
2. The registration itself, with its own stored `content_hash` zeroed (otherwise the hash would be a fixed point of itself).
3. The transitive closure of the registry state it references: doc-refs walk their `covers` filter matches; doc-guides walk `covers` EntityRefs and `examples` EntityRefs; referenced examples are included verbatim.

**Operational metadata is excluded from the transitive walk.** `ComponentSpec.registered_at` (wall-clock timestamp) and `source_file` (absolute path) are projected out via `_canon_component_spec` so two developers' checkouts of the same commit produce identical digests. Bumping `HASH_ALGORITHM_VERSION` invalidates every previously-stored hash; it is not a casual operation.

### 18.9 Observability: REST and MCP

The REST and MCP surfaces in §10 are extended one-for-one:

| Surface | Path / URI / Name |
|---------|-------------------|
| REST | `GET /self/docs`, `/self/doc/{name}`, `/self/examples`, `/self/example/{name}`, `/self/drift` |
| MCP resources | `s0ma://docs/registered-docs` (static), `s0ma://model/examples-for/{component}` (templated), `s0ma://model/docs-for/{component}` (templated) |
| MCP tool | `get_examples_for(component)` — explicit mirror of the `examples-for` templated resource for clients that do not expose templated-resource reads |

The drift endpoint recomputes every stored content hash transitively via `s0ma.hashing.content_hash` (no placeholder). It accepts an optional `?transpiler_version=` query parameter because `GET` is idempotent and cacheable.

### 18.10 Rule Summary

The rules that govern this subsystem are part of §16 (R-22 through R-26). In condensed form:

- Register every doc artifact via the public `register_*` functions (R-22).
- Every `example` must `demonstrates` something (R-23).
- Modifying a component is incomplete until its docs and examples are updated atomically (R-24).
- Doc-guides reference examples; they never inline raw code (R-25).
- Content hashes are recomputed, never hand-edited (R-26).

---

## Appendix A: `ComponentSpec` Field Reference

| Field | Type | Required | Default | Set By |
|-------|------|----------|---------|--------|
| `name` | `str` | Yes | — | Author |
| `kind` | `ComponentKind` | Yes | — | Author |
| `layer` | `Layer` | Yes | — | Author |
| `intent` | `str` | Yes (>= 10 chars) | — | Author |
| `contracts` | `Contract \| None` | No | `None` | Author |
| `dependencies` | `list[str]` | No | `[]` | Author |
| `resource_profile` | `ResourceProfile \| None` | No | `None` | Author |
| `version` | `str` | No | `"0.1.0"` | Author |
| `metadata` | `dict[str, Any]` | No | `{}` | Author |
| `idempotent` | `bool` | No | `False` | Author |
| `module_path` | `str` | No | — | Auto-derived from `__module__` |
| `qualified_name` | `str` | No | — | Auto-derived from `__qualname__` |
| `source_file` | `str \| None` | No | — | Auto-derived from `inspect.getfile()` |
| `registered_at` | `str` | No | — | Auto-derived (ISO timestamp) |
| `is_framework` | `bool` | No | `False` | Bootstrap only |

---

## Appendix B: Compliance Checklist

Use this before every commit:

```
 [ ] s0ma.initialize() is called before any application imports
 [ ] @component decorator is present with all four required fields (name, kind, layer, intent)
 [ ] name is PascalCase, globally unique, no whitespace, no collision with framework names
 [ ] kind uses ComponentKind enum, not a string
 [ ] layer uses Layer enum, not a string
 [ ] intent is >= 10 characters, describes purpose clearly for agents with no context
 [ ] dependencies lists all components this one imports or uses
 [ ] contracts reflect actual inputs, outputs, invariants, and performance bounds
 [ ] configurable_properties declared for runtime-adjustable settings (if any)
 [ ] protocol declared for cross-boundary interfaces (WebSocket, REST, etc.) if any
 [ ] All private helpers use @internal or _ prefix
 [ ] Shared types are in models.py with @internal
 [ ] s0ma.verify() passes with no ERROR-level anomalies
```

---

## Appendix C: Glossary

| Term | Definition |
|------|-----------|
| **Registration-as-creation** | The principle that code cannot exist without being registered. `@component` is how code is born. |
| **Load-bearing** | The self-model is required for the system to function. Not optional documentation. |
| **Phantom limb** | A registry entry with no corresponding code. Code was deleted, registry was not updated. |
| **Vestigial organ** | Code that exists but serves no purpose. Never called, no references. |
| **Immune response** | The system's reaction to unregistered or non-conforming code. |
| **Inflammation** | A component exceeding its declared resource profile. |
| **Atrophied muscle** | A deprecated component still receiving traffic. |
| **Interoception** | Runtime monitoring of internal state: latency, error rates, resource usage. |
| **Homunculus weight** | How important a component is. Determines verification frequency and detail. |
| **Bootstrap** | The process by which s0ma registers its own framework components. Solves the self-reference problem. |
| **Bootstrap test** | The foundational test: can the system accurately describe itself? |
| **Configurable property** | A runtime-changeable aspect of a component declared in its Contract. |
| **Protocol contract** | A declarative specification of a cross-boundary interface captured in the self-model. |
| **Idempotent registration** | Re-registering the same component from the same source silently succeeds. |
| **Topological sort** | Dependency-aware ordering of modules for safe import sequencing. |
| **Snapshot** | A frozen, serializable view of the registry at a point in time. Includes components, modules, edges, test registrations, IR data, plugins, doc-refs, doc-guides, and examples. |
| **doc-ref** | A registered generated reference artifact. Body is derived from registry state (§18). |
| **doc-guide** | A registered hand-authored guide whose body may reference examples and carry self-model assertions (§18). |
| **example** | A registered executable code sample that demonstrates one or more components and runs in a child process as part of the test pipeline (§18). |
| **Content hash** | A deterministic SHA-256 digest over a doc registration plus the transitive closure of the registry state it references. Prefixed with `HASH_ALGORITHM_VERSION` so stored hashes self-identify across algorithm bumps (§18.8). |
| **Documentation subsystem** | The registration, storage, query, execution, and drift-detection machinery described in §18. Extends registration-as-creation from code to documentation. |
| **Plugin** | A first-class extension registered via `register_plugin()`. Declares what it provides and what core components it depends on, with validation at registration time. |
| **IR store** | Runtime storage for transpiler intermediate representation data, queryable via `store_ir()` / `get_ir()`. |
| **Known relation types** | The recognized set of relationship edge types: CALLS, READS, CONSTRUCTS, CONFIGURES, RAISES, TYPE_USES, OBSERVES, PRODUCES, CONSUMES. Defined in `KNOWN_RELATION_TYPES`. |
| **Reflexion model** | Murphy's model classifying findings as convergences, divergences, or absences. |
| **Erosion coverage** | de Silva metric: percentage of the self-model that is automatically verifiable. |
| **Automation metric** | Kounev & Spinner metric: percentage of self-knowledge maintained without human intervention. |

---

## Appendix D: Future Considerations

Items under consideration for future phases:

### Registration & Enforcement

- Module-level registration (metadata per `.py` file, not just per class/function) — **implemented** (`register_module()`, `ModuleMetadata`)
- Relationship registration (typed edges: CALLS, CONSTRUCTS, READS, CONFIGURES, PRODUCES, CONSUMES) — **implemented** (`register_relationship()`, `RelationshipEdge`, `KNOWN_RELATION_TYPES`)
- Test registration (tests as first-class self-model entities) — **implemented** (`register_test()`, `TestRegistration`)
- Plugin registration (first-class plugin metadata with dependency validation) — **implemented** (`register_plugin()`, `PluginRegistration`)
- Cell registration for constants, enums, type aliases, and config objects
- Visibility system (PUBLIC, INTERNAL with cross-module access control)

### Verification & Monitoring

- Runtime contract enforcement (warn vs error modes)
- Protocol contract runtime verification (WebSocket/REST/gRPC conformance)
- Evaluator/ganglion architecture (convergence points, signal routing)
- Belief persistence across restarts
- Adaptive monitoring thresholds

### Dependency Graph

- Typed relationships (CALLS, CONSTRUCTS, READS, CONFIGURES, PRODUCES, CONSUMES, etc.) — **implemented** (`RelationshipEdge.relation`, `KNOWN_RELATION_TYPES` constant in `types.py`)
- Authored vs derived relationship separation — **implemented** (`RelationshipEdge.authored` flag)
- Dynamic dispatch modelling
- Weighted edges for prioritized impact analysis
- Cycle relaxation for type-only edges

### Language & Tooling

- s0ma DSL integration (`.s0ma` file compilation to `@component`-decorated Python)
- IDE integration (autocomplete, inline verification, navigation)
- Migration tooling (existing Python to s0ma-compliant Python)
- Incremental verification (dependency-aware caching)
- Source map support (DSL line to Python line mapping)

### Identity & Versioning

- Stable UUIDs for rename tracking across versions
- Cross-project identity (project-scoped namespaces)
- Deprecation markers with migration timelines
- Version compatibility checking between dependent components

---

*This specification is itself described by the system it specifies. The bootstrap test verifies that claim.*
