# s0ma Framework Feedback — Report 3

Sourced from the s0ma-dsl findings synthesis (`docs/s0ma-feedback-findings-1-2.md`), which covers the fr3d rebuild experience across 28+ transpiled modules, 920+ tests, and 30+ milestones of continuous usage. This report extracts the items that require changes to the **s0ma framework** (`s0ma-framework` package, `kn0wthyself/s0ma/`) rather than to the s0ma-dsl transpiler.

**Date:** March 31, 2026

---

## 1. `ComponentRegistry` Lacks a Complete `to_dict()` Method

**Findings ref:** 5.6  
**Severity:** Medium (requires workaround in every consuming project)  
**Affected consumers:** fr3d `SelfIntrospection`, fr3d `AnomalyDetector`, any project needing runtime self-model access

### Background

The fr3d agent's self-introspection components (`SelfIntrospection`, `AnomalyDetector`) need the registry's full state as a serializable dict — components, modules, edges, and test registrations — to power runtime self-awareness. Currently, there is no single public method on `ComponentRegistry` that returns this.

The closest approximation is:

```python
registry = get_registry()
snapshot = registry.snapshot()
data = snapshot.to_dict()
```

However, `RegistrySnapshot` (defined in `s0ma/models.py`, line 743) only captures:
- `components`: `dict[str, ComponentSpec]`
- `component_count` / `framework_component_count`
- `layers`: `dict[str, list[str]]`
- `dependency_graph`: `dict[str, list[str]]`

It **omits**:
- **Module metadata** (`_modules: dict[str, ModuleMetadata]`) — module-level identity registered by transpiled `.s0ma` modules via `register_module()`
- **Relationship edges** (`_edges: list[RelationshipEdge]`) — authored and derived dependency edges with relation types, carries, and coupling
- **Test registrations** (`_test_registrations: dict[str, TestRegistration]`) — test metadata linking tests to the components they validate

These are stored in private attributes on the registry (`_modules`, `_edges`, `_test_registrations`), forcing consuming code to either:
1. Access private attributes directly (fragile, undocumented)
2. Call individual accessor methods (`get_all_modules()`, `get_edges()`, `get_all_tests()`) and assemble the dict manually (verbose, easy to get wrong)

During the fr3d rebuild, the bootstrap code used option 2 — hand-assembling a registry dict from 4 separate API calls. This was duplicated in at least two components and diverged slightly between them.

### Proposed Solution

Add a `to_dict()` method directly to `ComponentRegistry` that returns the **complete** registry state:

```python
# In s0ma/registry.py, on ComponentRegistry class

def to_dict(self) -> dict[str, Any]:
    """Return the complete registry state as a JSON-serializable dict.

    Includes components, modules, edges, and test registrations —
    everything needed for runtime self-introspection.
    """
    return {
        "components": {
            name: spec.to_dict()
            for name, spec in self._components.items()
        },
        "modules": {
            name: meta.to_dict()
            for name, meta in self._modules.items()
        },
        "edges": [edge.to_dict() for edge in self._edges],
        "test_registrations": {
            name: reg.to_dict()
            for name, reg in self._test_registrations.items()
        },
        "summary": {
            "component_count": len(self._components),
            "module_count": len(self._modules),
            "edge_count": len(self._edges),
            "test_count": len(self._test_registrations),
        },
    }
```

Alternatively, expand `RegistrySnapshot` to include the missing data and keep `to_dict()` on the snapshot:

```python
@dataclass(frozen=True)
class RegistrySnapshot:
    components: dict[str, ComponentSpec]
    modules: dict[str, ModuleMetadata]           # NEW
    edges: list[RelationshipEdge]                 # NEW
    test_registrations: dict[str, TestRegistration]  # NEW
    component_count: int
    framework_component_count: int
    layers: dict[str, list[str]]
    dependency_graph: dict[str, list[str]]
    snapshot_at: datetime = field(default_factory=_now)
```

The first approach (method on `ComponentRegistry`) is simpler and avoids expanding the frozen snapshot dataclass. The second is more consistent with the existing `snapshot()` pattern.

### Impact on s0ma-dsl

The s0ma-dsl `runtime_bridge/registration.py` delegates to `ComponentRegistry` public methods and would not need changes — it already uses `registry.register_module()`, `registry.register_constant()`, etc. The improvement benefits downstream consumers of transpiled modules (like fr3d), not the transpiler itself.

---

## 2. `RegistrySnapshot` Should Include Module Metadata, Edges, and Tests

**Findings ref:** 5.6 (related)  
**Severity:** Low-Medium  
**Affected consumers:** Any tooling that uses `registry.snapshot()` for serialization

### Background

`RegistrySnapshot.to_dict()` (in `s0ma/models.py`, line 759) currently serializes:
```python
{
    "components": { ... },
    "component_count": N,
    "framework_component_count": N,
    "layers": { ... },
    "dependency_graph": { ... },
    "snapshot_at": "..."
}
```

This was sufficient before the DSL's expanded registration API (`register_module`, `register_relationship`, `register_test`), which added three new data stores. Now, a snapshot omits most of the data that makes transpiled-module registries richer than manually-decorated ones.

### Proposed Solution

Expand `RegistrySnapshot` to include the new stores (as described in the alternative above). Update `ComponentRegistry.snapshot()` to populate them:

```python
def snapshot(self) -> RegistrySnapshot:
    return RegistrySnapshot(
        components=dict(self._components),
        modules=dict(self._modules),               # NEW
        edges=list(self._edges),                    # NEW
        test_registrations=dict(self._test_registrations),  # NEW
        component_count=len(self._components),
        framework_component_count=...,
        layers=...,
        dependency_graph=...,
    )
```

And update `RegistrySnapshot.to_dict()` and `RegistrySnapshot.describe()` to include the new fields.

**Backward compatibility:** The expanded `RegistrySnapshot` adds new fields with defaults (`modules={}`, `edges=[]`, `test_registrations={}`), so existing `snapshot()` callers that don't use the new fields are unaffected. The `to_dict()` output adds new keys but doesn't remove any.

---

## 3. Runtime IR Access Mechanism

**Findings ref:** 3.24  
**Severity:** Low  
**Affected consumers:** Projects wanting to access `.s0ma.json` IR data at runtime

### Background

The s0ma-dsl transpiler generates rich `.s0ma.json` IR files alongside `.py` files. These contain the full module declaration graph — components, authored edges, derived edges, imports, contracts, and metadata — in a machine-readable format. However, at runtime, only the subset registered via `@component` decorators and `register_*()` calls is available through the `ComponentRegistry`.

The IR contains information the registry does not:
- **Derived edges** (TYPE_USES, RAISES) inferred from code analysis
- **Import metadata** (requires, uses, soft_requires)
- **Source location mappings** (line numbers, source map references)
- **Transpiler version** and schema version
- **Full contract text** (expects/guarantees as prose, vs. Contract's structured fields)

During the fr3d rebuild, `SelfIntrospection.describe()` needed the full declaration graph (not just the component list) to produce accurate self-descriptions. It had to load `.s0ma.json` files from disk at runtime, duplicating path resolution logic.

### Proposed Solution

This is a two-part change spanning both repositories:

**Part 1 (s0ma framework):** Add an optional IR storage mechanism to the registry:

```python
# In ComponentRegistry

def store_ir(self, module_name: str, ir_data: dict[str, Any]) -> None:
    """Store IR data for a module, making it available at runtime."""
    self._ir_store[module_name] = ir_data

def get_ir(self, module_name: str) -> dict[str, Any] | None:
    """Retrieve stored IR data for a module."""
    return self._ir_store.get(module_name)

def get_all_ir(self) -> dict[str, dict[str, Any]]:
    """Return all stored IR data."""
    return dict(self._ir_store)
```

**Part 2 (s0ma-dsl):** In the transpiled Python output, after `register_module()`, emit a `store_ir()` call that loads the co-located `.s0ma.json`:

```python
# In transpiled output (emitted by PythonEmitter)
import json
from pathlib import Path

_ir_path = Path(__file__).with_suffix("") 
_ir_file = _ir_path.parent / (_ir_path.name + ".s0ma.json")
if _ir_file.exists():
    _get_registry().store_ir("module_name", json.loads(_ir_file.read_text()))
```

**Note:** This is a nice-to-have. The current pattern (loading `.s0ma.json` from disk) works. The improvement is convenience and discoverability — runtime code doesn't need to know where IR files live.

### Impact

- Adds `_ir_store: dict[str, dict]` to `ComponentRegistry.__init__`
- Adds 3 public methods to `ComponentRegistry`
- `RegistrySnapshot` / `to_dict()` should include IR if stored
- `reset()` should clear `_ir_store`

---

## 4. Plugin Registration API

**Findings ref:** 3.10 (partial — the DSL declaration type is s0ma-dsl work, but framework support is needed)  
**Severity:** Low  
**Affected consumers:** Projects using plugin-based extensibility

### Background

The fr3d agent has a plugin system where plugins register new components, tools, and services at runtime. Currently, plugins are raw Python files that manipulate the registry directly — calling `registry.register()` with hand-constructed `ComponentSpec` objects, bypassing all DSL conventions and validation.

The s0ma-dsl side of this (a `plugin` declaration type) is tracked in the DSL findings plan. However, the framework also needs a public plugin API to make plugin registration first-class.

### Proposed Solution

Add a `PluginRegistration` model and registry support:

```python
# In s0ma/models.py

@dataclass
class PluginRegistration:
    """Metadata for a registered plugin."""
    name: str
    version: str
    intent: str
    registers: list[str] = field(default_factory=list)   # Component names this plugin adds
    requires_core: list[str] = field(default_factory=list)  # Core components it depends on
    source_file: str | None = None

    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    def from_dict(cls, data: dict) -> PluginRegistration: ...
```

```python
# In ComponentRegistry

def register_plugin(
    self,
    *,
    name: str,
    version: str,
    intent: str,
    registers: list[str] | None = None,
    requires_core: list[str] | None = None,
) -> PluginRegistration:
    """Register a plugin and validate its core dependencies exist."""
    # Validate requires_core components are registered
    for dep in (requires_core or []):
        if dep not in self._components:
            raise RegistryIntegrityError(
                f"Plugin '{name}' requires core component '{dep}' which is not registered."
            )
    ...
```

This gives plugins a structured registration path that the framework can validate (are dependencies met?) and introspect (what did this plugin add?).

### Impact

- New `PluginRegistration` dataclass in `models.py`
- New `_plugins: dict[str, PluginRegistration]` store in `ComponentRegistry`
- New `register_plugin()`, `get_plugin()`, `get_all_plugins()` methods
- `RegistrySnapshot` / `to_dict()` should include plugins

---

## 5. PRODUCES / CONSUMES Relation Types

**Findings ref:** 3.15 (partial — grammar and validation are s0ma-dsl work, but framework models need the new values)  
**Severity:** Low  
**Affected consumers:** Event-driven architectures using s0ma relationship tracking

### Background

The `RelationshipEdge` model stores `relation` as a string, so the framework technically accepts any value. However, the framework's documentation, query methods, and verification logic only recognize: `CALLS`, `READS`, `CONSTRUCTS`, `CONFIGURES`, `RAISES`, `TYPE_USES`.

The fr3d rebuild identified a gap: event-driven patterns (producer creates events, consumer handles them, connected by bootstrap wiring) are invisible in the dependency graph. Adding `PRODUCES` and `CONSUMES` as recognized relation types would make event flow visible to the self-model.

### Proposed Solution

1. **Document** `PRODUCES` and `CONSUMES` as valid relation types alongside the existing six.

2. **Update verification logic** in `s0ma/verifiers/structural.py` (if any) to recognize the new types without flagging them as anomalies.

3. **Update `SelfModelInterface`** query formatting to display event flow when PRODUCES/CONSUMES edges exist.

4. **No model changes needed** — `RelationshipEdge.relation` is already a `str` field, so `"PRODUCES"` and `"CONSUMES"` values work today. This is purely about recognition in tooling and documentation.

---

## 6. `RegistrySnapshot.describe()` Should Reflect DSL-Expanded Data

**Findings ref:** Implicit (derived from 5.6 and runtime usage patterns)  
**Severity:** Low  
**Affected consumers:** Any project using `snapshot.describe()` for LLM self-descriptions

### Background

`RegistrySnapshot.describe()` produces a human-readable self-description used by LLMs for self-awareness. Currently it describes components and their layers, but omits:
- Module structure (which modules exist, what they export)
- Relationship graph with relation types (not just "depends on" but "CALLS", "READS", etc.)
- Test coverage summary (which components are tested)

For projects built with s0ma-dsl, this information is registered at load time but invisible in `describe()`.

### Proposed Solution

After expanding `RegistrySnapshot` (per item 2), update `describe()` to include:

```
Modules:
  config (DOMAIN, v0.1.0) — exports: [DEFAULT_MODEL, TEST_MODEL, ...]
  models (DOMAIN, v0.1.0) — exports: [ToolParameter, ToolResult, ...]
  ...

Relationships:
  Orchestrator → LLMAdapter (CALLS, carries: ChatMessage)
  Orchestrator → OrchestratorEvent (PRODUCES)
  CLIGateway → OrchestratorEvent (CONSUMES)
  ...

Test Coverage:
  12/15 public nerves have tests (80%)
  Untested: [PluginLoader, PermissionManager, ...]
```

This makes the `describe()` output substantially more useful for runtime self-introspection, especially for LLM agents that need to understand their own architecture.

---

## Summary of Proposed Changes

| # | Change | Files Affected | Priority |
|---|--------|---------------|----------|
| 1 | `ComponentRegistry.to_dict()` method | `registry.py` | Medium |
| 2 | Expand `RegistrySnapshot` with modules, edges, tests | `models.py`, `registry.py` | Medium |
| 3 | Runtime IR storage (`store_ir` / `get_ir`) | `registry.py`, `models.py` | Low |
| 4 | Plugin registration API | `models.py`, `registry.py` | Low |
| 5 | Recognize PRODUCES/CONSUMES relations | Documentation, `verifiers/` | Low |
| 6 | Expand `RegistrySnapshot.describe()` | `models.py` | Low |

Items 1 and 2 should be addressed together as they both concern the completeness of registry serialization. Items 3–6 are independent and can be tackled in any order.
