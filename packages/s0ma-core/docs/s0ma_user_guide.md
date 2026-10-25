# s0ma User Guide
## How to Build and Modify Applications with s0ma

**Audience:** Coding agents (primary), human developers (secondary)
**Subject:** the s0ma-core Python runtime — registration, verification, and the self-model API
**Status:** the one canonical user guide. Merged 2026-08-30 from the two copies that had drifted apart (one here, one under `s0ma-dsl`) plus the condensed abridgement of both; those paths are now pointers to this file. Maintained by hand and checked by the documentation build's link, catalog, and mirror gates.

> **What this guide is not.** It teaches the **Python** way of using s0ma-core:
> you write classes and functions and decorate them. If you are authoring in the
> **`.s0ma` language** instead — the usual route today — the language is
> specified in
> [the current DSL spec](../../s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md) and
> taught by
> [the quick reference](../../../docs/reference/quick-reference-readable.md).
> The runtime described here is what the DSL compiles down to, so everything
> below still holds underneath; you just declare it in `.s0ma` rather than in
> decorators. Start at [`docs/getting-started.md`](../../../docs/getting-started.md)
> if you are new, and use [`docs/README.md`](../../../docs/README.md) to find
> anything else.

---

## What s0ma Is (30-Second Version)

s0ma is a Python framework that makes software **know itself**. Every piece of code must **register** itself before it can exist. The registry is not documentation — it's a structural dependency. Delete the registry, and the code stops working.

**Nothing exists unless it's registered. Registration IS creation.**

---

## Quick Reference: The Core Loop

Every time you add, change, or remove functionality, follow this loop:

```
1. DECLARE  → Define the component with @component decorator
2. IMPLEMENT → Write the logic inside the decorated class/function
3. VERIFY   → Run s0ma.verify() to check registry ↔ code consistency
4. QUERY    → Use SelfModelInterface or the /self/ API to see the system's self-description
```

**If you skip step 1, step 2 won't work.** The import hook blocks unregistered code.

---

## Section 1: Project Setup

### 1.1 Install s0ma

s0ma is not on PyPI yet, so `pip install s0ma-core` will not work: all four packages are published there from the first release cut of the public repository. Until then the way in is the repository itself, and it is written down once, outside this guide:
[`docs/getting-started.md` §1](../../../docs/getting-started.md#1-create-a-real-project)
states the route, and the
[root `README.md`](../../../README.md) "Install" section has its commands —
working inside a checkout, or building the wheels and installing them into a
project of your own. Install that way, then come back here for the runtime.

From a checkout you may install `s0ma-core` alone — the runtime framework on its own is fully supported — and then the optional extras matter:

| Extra | What it adds |
|---|---|
| *(none)* | The runtime: registry, decorators, verification, self-model. |
| `api` | The `/self/` REST application (FastAPI + uvicorn) — see §5.2. |
| `mcp` | The core introspection MCP server — see §5.3. |
| `all` | Both of the above. |

```python
# However it was installed, the import name is 's0ma':
import s0ma
```

> **Distribution name vs. import name.** The distribution is `s0ma-core`; the
> import name is `s0ma`. They differ because Python packaging conventions do not
> allow a leading digit in a distribution name — the import name is the one that
> matches the framework's identity.

Requires Python 3.11+.

> **Starting a `.s0ma` project instead?** One command takes you from nothing to a
> built, bootstrap-ready project: `s0ma new project <dir>` writes the
> `[tool.s0ma]` table, scaffolds a starter module, runs the first build, and
> prints your next steps. `s0ma doctor` health-checks the environment and the
> project at any time. Everything from §1.2 onward describes the runtime those
> commands set up for you, so it is worth reading either way.

### 1.2 Initialize s0ma in Your Project

s0ma is initialized programmatically via `s0ma.initialize()`. This is typically done in your project's entry point:

```python
import s0ma

# Full initialization with import hook enforcement
registry = s0ma.initialize(project_root="./src")

# Library-only mode (no hook, no persistence)
registry = s0ma.initialize(persist=False)
```

`s0ma.initialize()` performs three steps:
1. Creates or connects to the component registry (SQLite-backed by default at `.s0ma/registry.db`)
2. Performs bootstrap self-registration (registers s0ma's own framework components — `s0ma.verify()` and the self-model API report how many, and the count grows with the framework). The global registry does this for itself the moment `get_registry()` creates it, so a component registered before `initialize()` runs — at import time, say — already finds the framework there; this step then changes nothing.
3. Optionally installs the import hook if `project_root` is provided

**Parameters:**

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `project_root` | `None` | Directory to enforce registration for. If `None`, no import hook is installed. |
| `persist` | `True` | Enable SQLite persistence so the registry survives process restarts. |
| `strict` | `True` | If `True`, the import hook raises `UnregisteredComponentError`. If `False`, it issues warnings only. |

**Returns:** The initialized `ComponentRegistry` with all framework components registered.

> **Agent instruction:** Always call `s0ma.initialize()` before importing any application components. This activates the import hook that enforces registration.

### 1.3 How the Import Hook Works

After `initialize(project_root=...)` is called, the import hook intercepts all module loading for files under `project_root`:

- Any Python module that contains **public** classes or functions (names not starting with `_`) that are NOT decorated with `@component` or `@internal` will raise `UnregisteredComponentError` on import.
- The hook is installed as a `sys.meta_path` finder at the highest priority.
- s0ma's own modules are automatically allowlisted.

---

## Section 2: Creating Components

### 2.1 The @component Decorator

Every piece of meaningful code must be wrapped in `@component`. This simultaneously:
- Registers the component in the self-model
- Attaches introspectable metadata (as `__component__` attribute)
- Makes the component queryable via the self-model API
- Enables verification against declared contracts and resource profiles

```python
from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer
from s0ma.models import Contract

@component(
    name="GreetingPlugin",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="Generates greeting messages for users based on time of day",
    contracts=Contract(
        input_type="username: str",
        output_type="str",
        invariants=["output always contains the username"],
        max_latency_ms=100,
    ),
    dependencies=[],
)
class GreetingPlugin:
    """Generates greeting messages for users based on time of day."""

    def execute(self, username: str) -> str:
        from datetime import datetime
        hour = datetime.now().hour
        if hour < 12:
            return f"Good morning, {username}!"
        elif hour < 17:
            return f"Good afternoon, {username}!"
        else:
            return f"Good evening, {username}!"
```

> **Important:** The decorator returns the entity **completely unmodified** — no wrapping, no proxying. Zero runtime overhead on calls.

### 2.2 Decorator Fields Explained

| Field | Required? | Type | Purpose | Agent Guidance |
|-------|-----------|------|---------|----------------|
| `name` | **Yes** | `str` | Unique identifier for this component | Use PascalCase. Must be globally unique. |
| `kind` | **Yes** | `ComponentKind` | What archetype this component follows | One of: `SERVICE`, `FUNCTION`, `MODEL`, `ADAPTER`, `ORCHESTRATOR` |
| `layer` | **Yes** | `Layer` | Which architectural layer this belongs to | One of: `DOMAIN`, `APPLICATION`, `INFRASTRUCTURE`, `PRESENTATION` |
| `intent` | **Yes** | `str` | Plain-English description of what this component does and why | Write 1-2 sentences (min 10 chars). This is what agents and humans read first. |
| `contracts` | Recommended | `Contract` | Behavioral expectations (pre/postconditions, invariants, what it must never do, performance) | Use the `Contract` dataclass (see below). |
| `dependencies` | Recommended | `list[str]` | List of other component names this depends on | Names must match registered components. s0ma validates these exist. |
| `resource_profile` | Optional | `ResourceProfile` | Expected resource usage for interoception monitoring | Used by the interoception verifier. |
| `version` | Optional | `str` | Semantic version string | Defaults to `"0.1.0"`. |
| `metadata` | Optional | `dict[str, Any]` | Extensible key-value store | Free-form metadata for custom use. |
| `idempotent` | Optional | `bool` | Allow re-registration from the same source file | Defaults to `False`. Set to `True` for hot-reload and dynamic loading scenarios (see Section 2.7). |

### Component Name Uniqueness and Reserved Names

Component `name` is globally unique across **all** registered components, including s0ma's own framework components. When you register a component, its name competes in the same namespace as framework internals like `ComponentRegistry`, `SelfModelInterface`, `Contract`, `LifecycleManager`, and others.

**To avoid collisions, adopt a project-level naming convention.** For example, prefix service names with the project name:

| Risky | Safer |
|-------|-------|
| `"QueryEngine"` | `"MyApp_QueryEngine"` |
| `"MetricsCollector"` | `"MyApp_MetricsCollector"` |
| `"LifecycleManager"` | `"MyApp_LifecycleManager"` |

You can discover all framework-reserved names by querying the registry for components where `is_framework=True`:

```python
framework_names = [
    spec.name for spec in registry.get_all().values() if spec.is_framework
]
```

> **Agent instruction:** Before choosing a component name, verify it doesn't collide with framework components. If building a multi-project system, use project-name prefixes to keep namespaces clean.

### 2.3 The Contract Dataclass

Contracts declare behavioral expectations. They are defined using the `Contract` dataclass:

```python
from s0ma.models import Contract, ConfigurableProperty, ProtocolContract

Contract(
    preconditions=["username must be non-empty"],
    postconditions=["return value contains the username"],
    invariants=["output is always a string"],
    max_latency_ms=100,
    error_rate_threshold=0.01,
    input_type="username: str",
    output_type="str",
    configurable_properties={
        "theme_color": ConfigurableProperty(
            type="str",
            default="blue",
            description="Primary theme color for UI components",
        ),
        "max_items": ConfigurableProperty(
            type="int",
            default=10,
            constraints={"min": 1, "max": 100},
        ),
    },
)
```

| Field | Type | Purpose |
|-------|------|---------|
| `preconditions` | `list[str]` | What must be true before invocation |
| `postconditions` | `list[str]` | What the component guarantees after execution |
| `invariants` | `list[str]` | Properties that must always hold |
| `forbids` | `list[str]` | What the component must never do — declared and shown, never executed |
| `max_latency_ms` | `float \| None` | Performance ceiling (must be positive) |
| `error_rate_threshold` | `float \| None` | Maximum acceptable error rate (0.0–1.0) |
| `input_type` | `str \| None` | Description of expected input |
| `output_type` | `str \| None` | Description of expected output |
| `configurable_properties` | `dict[str, ConfigurableProperty] \| None` | Runtime-configurable properties (theme, layout, etc.) |
| `protocol` | `ProtocolContract \| None` | Cross-boundary interface contract (WebSocket, REST, gRPC, IPC) |

`forbids` holds what the component must never do, however it is called and whatever happens while it runs, one plain sentence per item. It is declared and shown, never executed: s0ma keeps it with the component (`to_dict()` writes it only when the list is not empty), the self-model's formatted contract text lists it under `Forbids:` after `Invariants:`, and the teaching output includes it. No verifier counts it and nothing checks it at runtime; it is there for the people and agents who change the code.

#### Configurable Properties

Configurable properties represent aspects of a component that can be changed at runtime without code regeneration—theme colors, labels, layout options, maximum item counts, and similar runtime-adjustable settings. Unlike structural properties that require code changes, configurable properties are part of the component's runtime configuration interface.

Each configurable property is described using the `ConfigurableProperty` dataclass:

```python
from s0ma.models import ConfigurableProperty

ConfigurableProperty(
    type="int",              # "str", "int", "float", "bool", or "enum"
    default=10,              # Default value (must match declared type)
    description="The maximum number of items to display",  # Optional
    constraints={"min": 1, "max": 100},  # Optional: min/max for numbers, allowed_values for enums
    category="Display",      # Optional: UI grouping hint
)
```

**Supported types:**
- `"str"` — string values
- `"int"` — integer values
- `"float"` — floating-point values (also accepts int defaults)
- `"bool"` — boolean values (True/False)
- `"enum"` — enumerated values (requires `allowed_values` list in `constraints`)

**Example with enum:**

```python
ConfigurableProperty(
    type="enum",
    default="light",
    constraints={"allowed_values": ["light", "dark", "auto"]},
    description="Theme mode selection",
)
```

**Validation:**

Configurable properties are validated at construction time. Invalid properties raise `RegistrationError` immediately when the `ConfigurableProperty` is created:

- `type` must be one of: `"str"`, `"int"`, `"float"`, `"bool"`, `"enum"`
- `default` value must match the declared `type`
- For numeric types (`"int"`, `"float"`): if both `min` and `max` are specified in `constraints`, `min` must be less than `max`
- For `"enum"` type: `constraints` must include a non-empty `allowed_values` list, and `default` must be one of the allowed values

This validation happens at `@component` decoration time (fail-fast), ensuring that invalid configurable properties are caught before the component is registered.

**Helpful error messages:** If you pass an invalid field name to `Contract()`, `ConfigurableProperty()`, `ComponentSpec()`, or `ResourceProfile()`, you'll receive a `RegistrationError` that lists all valid fields. This is especially helpful when working with LLM-generated code that might use outdated examples or incorrect field names.

```python
# Example of helpful error message:
try:
    Contract(invalid_field="value")
except RegistrationError as e:
    print(e)
    # Output: "Contract() received unexpected keyword argument.
    #          Valid fields are: preconditions, postconditions, invariants,
    #          max_latency_ms, error_rate_threshold, input_type, output_type,
    #          configurable_properties, protocol, forbids."
```

**Serialization and deserialization:** All core data models support full round-trip serialization via `to_dict()` and `from_dict()` methods. This enables LLM-driven workflows where component specifications arrive as JSON:

```python
# Serialize a contract to dictionary
contract = Contract(max_latency_ms=50.0, configurable_properties={...})
contract_dict = contract.to_dict()

# Deserialize from dictionary (with validation)
reconstructed = Contract.from_dict(contract_dict)

# Same pattern for ComponentSpec, ResourceProfile, ConfigurableProperty
spec_dict = component_spec.to_dict()
spec = ComponentSpec.from_dict(spec_dict)  # Converts enum strings to enum values
```

The `from_dict()` methods automatically validate the reconstructed objects and convert string enum names (like `"SERVICE"`, `"DOMAIN"`) to their enum values. This is particularly useful when receiving component specifications from LLM planning steps or external configuration files.

#### Cross-Boundary Protocols

Protocol contracts capture cross-boundary interface specifications — WebSocket messages, REST endpoints, gRPC services, IPC channels — so the self-model is aware of interfaces that span the Python/non-Python boundary. Without protocol contracts, these interfaces are invisible to `s0ma.verify()`, and drift between server and client implementations can only be caught by integration testing.

In the current phase, protocol contracts are **declarative metadata only**. Runtime verification of protocol conformance is deferred to a future phase. The value now is in *capturing* the contract in the self-model so the system knows the interface exists and what it promises.

```python
from s0ma.models import Contract, ProtocolContract

Contract(
    protocol=ProtocolContract(
        protocol_type="websocket",
        message_types={
            "message": {"role": "str", "content": "str"},
            "plan": {"steps": "list[str]", "status": "str"},
            "progress": {"step_index": "int", "detail": "str"},
            "error": {"code": "int", "message": "str"},
        },
        description="Real-time chat protocol with planning support",
    ),
)
```

**`ProtocolContract` fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `protocol_type` | `str` | Protocol kind: `"websocket"`, `"rest"`, `"grpc"`, `"ipc"`, etc. |
| `message_types` | `dict[str, dict]` | Maps message names to their schema (field names and types). |
| `description` | `str \| None` | Optional description of the protocol's purpose. |

**How protocol contracts appear in the self-model:**

When a component declares a protocol contract, it appears in `describe()` output:

```
ChatServer (service)
  Intent: WebSocket server handling real-time chat communication
  Protocol: websocket with message types: error, message, plan, progress
```

It also appears in `describe_for_code_generation()` output, providing LLMs generating client code with the authoritative schema for what message types and payloads are valid.

> **Agent instruction:** Use `configurable_properties` to declare component aspects that users can adjust at runtime. Use `protocol` to declare cross-boundary interface contracts (WebSocket, REST, gRPC) so the self-model captures the full system surface, not just the Python side. Use `from_dict()` / `to_dict()` for persisting component specifications or exchanging them with LLMs.

### 2.4 The @internal Decorator

For private helpers that should NOT be registered as components but live alongside component code, use `@internal` to tell the import hook to exempt them:

```python
from s0ma.decorators import component, internal
from s0ma.types import ComponentKind, Layer

@internal
def _parse_config(raw: str) -> dict:
    """Private helper — intentionally unregistered."""
    return json.loads(raw)

@internal(reason="Legacy helper, will be removed in v2")
def _old_parser(raw: str) -> dict:
    ...

@component(
    name="ConfigLoader",
    kind=ComponentKind.SERVICE,
    layer=Layer.INFRASTRUCTURE,
    intent="Loads and validates configuration files",
)
class ConfigLoader:
    def load(self, path: str) -> dict:
        raw = open(path).read()
        return _parse_config(raw)
```

> **Agent instruction:** Use `@internal` for private helpers that support registered components. Use `@component` for anything that represents meaningful, independent functionality.

### 2.5 What Happens If You Forget @component

```python
# This file is under project_root but has no @component or @internal decorator

class SneakyHelper:
    def do_something(self):
        return "I'm unregistered!"

# When another module tries to import this:
# >>> from my_app.helpers import SneakyHelper
# UnregisteredComponentError: 'SneakyHelper' in 'my_app/helpers.py'
#   is not registered in the s0ma self-model.
#   All public code under the project root must use @component or @internal.
```

> **This is the core enforcement mechanism.** The system literally cannot use code it doesn't know about. There are no phantom limbs.

### 2.6 Abstract Base Classes

When using Python's Abstract Base Classes (ABCs), apply `@internal` to the ABC and `@component` to each concrete subclass. This is the recommended pattern because the self-model is meant to track concrete, deployable implementations — not abstract contracts.

```python
import abc
from s0ma.decorators import component, internal
from s0ma.types import ComponentKind, Layer

@internal
class BaseProcessor(abc.ABC):
    """Abstract base — intentionally unregistered."""

    @abc.abstractmethod
    def process(self, data: str) -> str: ...

@component(
    name="JsonProcessor",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="Processes input data as JSON, returning a normalized dict string",
)
class JsonProcessor(BaseProcessor):
    def process(self, data: str) -> str:
        import json
        return str(json.loads(data))

@component(
    name="XmlProcessor",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="Processes input data as XML, returning a normalized dict string",
)
class XmlProcessor(BaseProcessor):
    def process(self, data: str) -> str:
        # ... XML parsing logic
        return str(data)
```

**Why `@internal` on the ABC, not `@component`?**

Abstract classes are interface definitions — they cannot be instantiated and represent a design contract, not a deployable component. Registering the ABC would add a phantom entry to the self-model for something that can never actually run.

**What if you also need to `@component`-decorate the ABC itself?**

This is now supported. `@component` on a parent class does not block `@component` on a subclass. Each class establishes its own independent registration:

```python
@component(
    name="AbstractRegistry",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="Abstract component defining the registry interface contract",
)
class AbstractRegistry(abc.ABC):
    @abc.abstractmethod
    def register(self, key: str, value: object) -> None: ...

@component(
    name="InMemoryRegistry",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="In-memory implementation of the registry interface for testing",
)
class InMemoryRegistry(AbstractRegistry):
    def register(self, key: str, value: object) -> None:
        ...
```

Both `AbstractRegistry` and `InMemoryRegistry` appear in the self-model with their own specs, registered under their own names.

**Error message guidance:**

If you accidentally apply `@component` twice to the *same* class, you'll see:

```
RegistrationError: Entity 'MyClass' already has a @component decorator
(registered as 'OriginalName'). If this was inherited from a parent class,
use @internal on the abstract base class and @component only on concrete
implementations.
```

If the error occurs on a subclass when you intended independent registration, verify the parent class doesn't already have `@component` directly applied — or switch the parent to `@internal`.

> **Agent instruction:** Default to `@internal` on ABCs and `@component` on concrete implementations. Only register an ABC with `@component` if it represents a genuine, independent component in the architecture that you want tracked in the self-model. In all cases, each concrete subclass that you want discoverable must have its own `@component` decoration.

### 2.7 Idempotent Registration

By default, attempting to register a component whose name is already in the registry raises `RegistrationError`. This protects against accidental name collisions. However, two legitimate scenarios require re-registration:

1. **Hot-reload / dynamic reloading:** `importlib.reload(module)` re-executes `@component` decorators, which would attempt to re-register components that already exist.
2. **Post-reset module reuse:** After `reset_registry()`, re-importing a cached module re-fires its `@component` decorators.

**`@component(..., idempotent=True)`** opts a component into graceful re-registration:

```python
@component(
    name="HotReloadableProcessor",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="Processor that supports live reloading during development",
    idempotent=True,  # silently succeeds if re-registered from the same source file
)
class HotReloadableProcessor:
    ...
```

**Semantics:**
- `idempotent=True` + same `source_file` → silently succeeds (the registration is a no-op)
- `idempotent=True` + different `source_file` → raises `RegistrationError` (this is a genuine name collision, not a redundant declaration)
- `idempotent=False` (default) → raises on any duplicate name (unchanged behavior)

**`register_or_update(spec)`** provides upsert semantics for dynamic loading scenarios where you want the registry to reflect the latest version of a component:

```python
from s0ma.registry import get_registry
from s0ma.models import ComponentSpec

registry = get_registry(persist=False)

# Register if new, update (replace) if already registered from the same source
spec = ComponentSpec(
    name="DynamicComponent",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="A dynamically loaded component that may be reloaded with updates",
    module_path="my_project.dynamic",
    qualified_name="my_project.dynamic.DynamicComponent",
    source_file="/path/to/dynamic.py",
    version="0.2.0",
)
registered_spec = registry.register_or_update(spec)
```

`register_or_update()` semantics:
- Name is new → register and return the new spec
- Name exists and `source_file` matches → replace with new spec and return it
- Name exists but `source_file` differs → raise `RegistrationError` (name collision)

**When to use each:**

| Scenario | Recommended approach |
|----------|---------------------|
| Normal component registration | `@component(...)` — default behavior |
| Module hot-reload in development | `@component(..., idempotent=True)` |
| Dynamic code generation with possible re-import | `@component(..., idempotent=True)` |
| Updating a spec programmatically after reload | `registry.register_or_update(spec)` |
| Test isolation with `reset_registry()` + module reuse | `fresh_registry()` or `register_from_module(module)` (see Section 8) |

> **Agent instruction:** Use `idempotent=True` when a component's module may be reloaded at runtime (hot-reload, dynamic generation, or test setup patterns). Use `register_or_update()` when you're constructing `ComponentSpec` objects programmatically and want upsert semantics. Leave the default (`idempotent=False`) for all standard application components to preserve name-collision safety.

---

## Section 3: Modifying Components

### 3.1 Changing a Component's Behavior

When you modify what a component does:

```
1. Update the implementation (the code inside the class/function)
2. Update the `intent` field if the purpose has changed
3. Update `contracts` if inputs, outputs, or invariants changed
4. Update `dependencies` if you added/removed imports of other components
5. Run s0ma.verify()
```

**Example: Adding time zone support to GreetingPlugin**

```python
@component(
    name="GreetingPlugin",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="Generates greeting messages based on user's local time zone",  # ← UPDATED
    contracts=Contract(
        input_type="username: str, timezone: str",  # ← UPDATED
        output_type="str",
        invariants=["output always contains the username"],
        max_latency_ms=100,
    ),
    dependencies=["TimezoneResolver"],  # ← NEW DEPENDENCY
)
class GreetingPlugin:
    def execute(self, username: str, timezone: str = "UTC") -> str:
        from my_app.utils import TimezoneResolver
        resolver = TimezoneResolver()
        hour = resolver.get_local_hour(timezone)
        # ... rest of implementation
```

> **Agent instruction:** When modifying a component, ALWAYS check whether the `intent`, `contracts`, and `dependencies` fields still accurately describe the component. If the code does something the decorator doesn't declare, `s0ma.verify()` will flag it.

### 3.2 Renaming a Component

```
1. Change the `name` field in the @component decorator
2. Update ALL other components that list this in their `dependencies`
3. Run s0ma.verify() — it will catch any missed references
```

### 3.3 Moving a Component to a Different Layer

```
1. Change the `layer` field in the @component decorator (use the Layer enum)
2. Verify the new layer is appropriate for the component's purpose
3. Run s0ma.verify() — it will flag layer constraint violations
```

---

## Section 4: Removing Components

### 4.1 Safe Removal Process

```
1. Use the /self/impact/{name} endpoint or SelfModelInterface to see what depends on this
2. Remove or update all dependent components first
3. Delete the component file (or remove the @component-decorated class)
4. Run s0ma.verify()
```

**What `s0ma.verify()` catches after deletion:**

- **Phantom limb detected:** Other components still list the deleted component in their `dependencies`
- **Import failure:** Code that tries to import the deleted component will fail at the import hook level

> **Agent instruction:** NEVER just delete a file. Always check dependencies first. The system will catch you, but it's faster to check proactively.

### 4.2 What Phantom Limbs Look Like

If you delete `GreetingPlugin` but `ChatRouter` still declares it as a dependency, `s0ma.verify()` will return an anomaly:

```
ANOMALY DETECTED: PHANTOM_LIMB (severity: ERROR)
  Component 'ChatRouter' declares dependency on 'GreetingPlugin'
  but 'GreetingPlugin' is not registered in the self-model.

  Resolution: Either restore GreetingPlugin or update ChatRouter's
  dependencies list to remove the reference.
```

---

## Section 5: Querying the Self-Model

### 5.1 Python API

s0ma is a Python library. Use the Python API directly to query the system:

```python
import s0ma
from s0ma import SelfModelInterface

# Initialize
registry = s0ma.initialize(project_root="./src")

# Create the query interface
smi = SelfModelInterface(registry)

# Get a natural language system overview
print(smi.describe_system())

# Get details on a specific component
print(smi.describe_component("GreetingPlugin"))

# Get impact analysis (what breaks if this changes)
print(smi.get_impact_analysis("GreetingPlugin"))

# Get extension points (where new components can be added)
print(smi.get_available_extension_points())

# Run full verification
report = s0ma.verify(registry)
print(report.describe())
assert report.passed, report.explain_for_llm()
```

### 5.2 The /self/ REST API (for programmatic access)

With the `api` extra installed (see §1.1), s0ma exposes a FastAPI application:

```python
from s0ma import initialize
from s0ma.api.rest import create_app

registry = initialize(persist=False)
app = create_app(registry)
# Run with: uvicorn s0ma.api.rest:app --reload
```

**Endpoints:**

```
GET  /self/overview              → System purpose, layers, component count
GET  /self/components            → All registered components with summaries
GET  /self/component/{name}      → Full detail on one component
GET  /self/health                → Verification status and anomaly count
GET  /self/anomalies             → Current model ↔ reality discrepancies
GET  /self/graph                 → Dependency graph (JSON adjacency list + Graphviz DOT)
GET  /self/impact/{name}         → Impact analysis: what breaks if this component changes
GET  /self/extensions            → Extension points: where new components can be added safely
POST /self/query                 → Natural language query (body: {"question": "..."})
```

All responses include both a `text` field (natural language for LLM consumption) and structured data fields (for programmatic access).

The health endpoint reports verification, not provider or global application health.
Check `status` (`passed`, `failed`, or `unavailable`) before interpreting `passed`
or `anomaly_count`; both are null when verification is unavailable. Component
aliases share the library resolver, ambiguity returns 409 with canonical
candidates, and unknown names retain 404. See the
[runtime compatibility guide](../../../docs/operations/bench-runtime-contracts.md)
for exact response examples and the runtime adapter's snapshot refresh contract.

### 5.3 MCP Server

s0ma also provides an MCP (Model Context Protocol) server for direct integration with AI tools:

```python
from s0ma.api.mcp_server import create_mcp_server

server = create_mcp_server(registry)
```

Requires the `mcp` extra (see §1.1).

> **Two MCP servers, two jobs.** The server in this section is s0ma-core's
> *introspection* server — it answers questions about a running system's
> self-model. The separate [`s0ma-mcp`](../../s0ma-mcp/README.md) package is the
> *authoring* server: it drives the `.s0ma` toolchain (scaffold → check →
> transpile/build) through a set of honestly annotated tools including read-only
> `project_status` orientation, derived roster inspection, and explicit host
> verification. Every tool-body result carries validated `next_actions`. It serves
> the agent guides plus the diagnostic error catalog (`s0ma://guide/errors`),
> exposes its core authoring and operating journeys as MCP prompts (among them
> `author_module`, `fix_check_failures`, `migrate_project`, `diagnose_fault`),
> and — eating its own dog food — publishes its own live component graph at
> `s0ma://self/model`. Register it with `claude mcp add s0ma -- s0ma-mcp`.
>
> If you are an agent looking for the s0ma **concepts** rather than a running
> system's shape, the authoring server's `learn_s0ma` tool is the front door.

#### 5.3.1 Teaching Resources and Tools

The MCP server includes teaching capabilities that help coding agents learn the s0ma framework at runtime — no pre-loaded documentation required.

**Where the answers come from.** The teaching content ships *inside* the
`s0ma-core` package as a generated data file, so an agent gets the same answers
from an installed wheel as from a source checkout. Reading this guide off disk
is the **fallback** and only fires in a checkout that has it, which is why the
section headings in this guide are load-bearing: the fallback addresses them by
name. Either way the answer is stamped with the release version and the
documentation snapshot it came from, so an agent can tell the two apart.

**MCP Resources** (read-only data an agent can request):

| URI | What It Returns |
|-----|-----------------|
| `s0ma://docs/user-guide` | Complete user guide (this document) |
| `s0ma://docs/compliance-rules` | Appendix C only |
| `s0ma://docs/architecture` | Architecture document |
| `s0ma://model/component-template` | A real registered component as a copyable `@component` template |
| `s0ma://model/registry-summary` | Live system overview from the self-model |

**MCP Teaching Tools** (callable functions):

| Tool | Purpose |
|------|---------|
| `learn_about_s0ma(topic)` | Topic-based documentation lookup with live examples |
| `get_component_example(kind?)` | Real component from the registry formatted as a copyable template |
| `get_compliance_checklist()` | Quick pre-flight checklist from Appendix C |

**Example usage from an MCP client:**
```
# "How do I create a component?"
→ call learn_about_s0ma(topic="creating components")
→ Returns Section 2 content + a live @component template from the registry

# "What are the rules?"
→ call learn_about_s0ma(topic="compliance")
→ Returns Appendix C directly from this user guide
```

> **Agent instruction:** When building an application with s0ma, call `learn_about_s0ma` with relevant topics before writing code. Every answer names where it came from, so you can tell a packaged answer from a checkout fallback.

### 5.4 Natural Language Queries

The `POST /self/query` endpoint accepts natural language questions about the system:

```python
# Via the REST API (POST /self/query):
{"question": "What component handles user authentication?"}
{"question": "What are the dependencies of the ChatRouter?"}
{"question": "Which components have the highest complexity?"}
{"question": "What would break if I removed the TimezoneResolver?"}
```

> **Agent instruction:** When you're unsure about the system's architecture, query the self-model BEFORE making changes. It is the authoritative source of truth.

### 5.5 Self-Model for LLM Consumers

The standard `describe_system()` and `get_architecture_context()` outputs are designed for dual consumption: readable by developers, parseable by LLMs answering architectural questions. They work well for this. But there is a category of issues where that same output **actively misleads** LLMs that are *generating code* rather than reading about the system.

The specific problem: when `get_architecture_context()` output is injected into a code generation prompt, LLMs see platform module paths (e.g., `st3mcell.desktop.server`) alongside layer names (`PRESENTATION`). They correctly infer a pattern — layer X lives in package Y — and apply it to generated code. Since `Layer` enum names look like plausible Python package directories, generated code ends up with `from DOMAIN.something import ...` or using framework internal paths as import roots. This is wrong, but it's the rational inference from the output.

s0ma provides two audience-aware methods that produce output optimized for different agent contexts.

#### `describe_for_code_generation(target_package)`

Produces self-model output specifically formatted for LLM code generation prompts.

**Key differences from `describe_system()` / `get_architecture_context()`:**

1. **Explicit import guidance** — States clearly where generated code should import from, and where it should *not*.
2. **Layer annotation** — Explains that layer names are classification labels, not Python packages or directories.
3. **Framework components annotated as non-importable** — Platform internals are grouped and labeled `(platform internal — not for import)`, preventing LLMs from inferring they are valid import roots.
4. **`@component` decorator template** — A filled-in template using `target_package` naming, giving the LLM a concrete anchor.
5. **Configurable property schemas** — When components declare `configurable_properties`, they are shown for runtime-configuration context.

```python
from s0ma import SelfModelInterface

smi = SelfModelInterface(registry)

# In your code generation prompt:
context = smi.describe_for_code_generation("myapp.services")
prompt = f"""
{context}

Generate a new service component called OrderValidator in myapp.services.
"""
```

The output will include sections like:

```
## Import Guidance
Generated code should import from: `myapp.services.*`. Do not import from
`s0ma.*` or other framework packages — these are platform internals not
available in generated code.

## Architectural Layers
Layer values (DOMAIN, APPLICATION, INFRASTRUCTURE, PRESENTATION) are
architectural classification labels, not Python packages or directories.
Do not use layer names as package paths in import statements.

## System Components

### Platform Components (platform internal — not for import)
- ComponentRegistry (framework): ...
- SelfModelInterface (framework): ...

### Application Components
- OrderProcessor (service, DOMAIN): ...

## @component Decorator Template
Use this template when defining new components in `myapp.services`:

@component(
    name="YourComponentName",
    kind=ComponentKind.SERVICE,  # classification label, not a directory
    layer=Layer.DOMAIN,  # label only — not a package path
    ...
)
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `target_package` | required | The Python package where generated code will live (e.g., `"myapp.services"`). |
| `include_contracts` | `True` | Whether to include contract details (pre/postconditions) per component. |
| `include_configurable_properties` | `True` | Whether to include configurable property schemas. |

#### `describe_for_agent(context, *, target_package=None)`

A general-purpose dispatch method that routes to the most appropriate self-model output based on the agent's current activity.

```python
# Code generation: LLM-optimized output with import guidance and templates
context = smi.describe_for_agent("code_generation", target_package="myapp.services")

# Architectural review: full dependency graph and component details
context = smi.describe_for_agent("architectural_review")

# Debugging: verification status, active anomalies, dependency graph
context = smi.describe_for_agent("debugging")
```

**Valid context values:**

| Context | Delegates To | Use When |
|---------|-------------|----------|
| `"code_generation"` | `describe_for_code_generation()` | Generating new component code. Requires `target_package`. |
| `"architectural_review"` | `get_architecture_context()` | Planning changes, reviewing the full architecture. |
| `"debugging"` | Internal method | Diagnosing problems — shows anomalies and the dependency graph. |

> **LLM pitfalls this solves:**
>
> - **Layer-as-package confusion.** LLMs trained on Spring, Django, and Clean Architecture patterns have strong priors that `DOMAIN`, `APPLICATION`, `INFRASTRUCTURE`, `PRESENTATION` correspond to directory structure. `describe_for_code_generation()` breaks this assumption explicitly.
> - **Framework internal path leakage.** When the output lists `module: s0ma.registry` next to framework components, LLMs may infer this is a valid import root for user code. The annotated Platform Components section prevents this.
> - **Missing decorator template.** Without a concrete `@component` example using the target package, LLMs must synthesize one from partial context. The template gives an unambiguous reference.

### 5.6 Comparing Snapshots — `compute_registry_diff` (0.3.0)

`registry.snapshot()` already gives you a frozen view of the registry state. `s0ma.self_model.diff.compute_registry_diff` compares two snapshots and returns the structured difference — useful for configuration drift detection, update-cycle audits, change-impact reporting, or any flow that needs to know exactly what shifted between two registry states.

```python
from s0ma.self_model.diff import compute_registry_diff

snap_before = registry.snapshot()
# ... apply some changes (register / unregister / replace) ...
snap_after = registry.snapshot()

diff = compute_registry_diff(prior=snap_before, current=snap_after)

for change in diff.added:
    print(f"+ {change.name} (layer={change.after.layer.name})")
for change in diff.removed:
    print(f"- {change.name}")
for change in diff.modified:
    fields = ", ".join(change.field_changes.keys())
    print(f"~ {change.name} (changed: {fields})")

if diff.is_empty():
    print("No change.")
```

Behaviour pins:

- `diff.added`, `diff.removed`, `diff.modified` are deterministically sorted by component name.
- Each `ComponentChange` carries `before`, `after`, and a `field_changes: dict[field_name, (before_value, after_value)]` for modified components only.
- Field comparison goes through `s0ma.hashing.canonical.canonicalize`, so dict / set ordering in `metadata` or `dependencies` never produces a false positive.
- The `registered_at` timestamp is excluded from comparison (would otherwise differ on every re-registration).
- `diff.to_dict()` and each `change.to_dict()` produce JSON-serialisable output for HTTP / cross-process transport.

### 5.7 Module-Scoped Components — `module_scoped: True` (0.3.0)

By default, every component's `name` must be globally unique (see §2.2 and the framework spec §4.5). For most projects this is the right invariant — it keeps the registry a flat queryable namespace. But two legitimate patterns benefit from a per-module namespace:

1. **Abstract ↔ concrete pairs.** A DOMAIN-layer `EventStore` abstract and an INFRASTRUCTURE-layer `EventStore` concrete naturally share a name. Renaming one of them to dodge the collision (`JsonlEventStore`, `AbstractEventStore`) obscures intent.
2. **Plugin-shaped sibling integrations.** Multiple integration modules each exposing `get_factory`, `get_manifest`, `smoke_test_primary` are clearer with the bare name preserved in each module.

Set `module_scoped=True` on the `ComponentSpec` (or carry `module_scoped: true` in the originating `.s0ma` cell declaration) to opt that spec into qualified keying:

```python
spec = ComponentSpec(
    name="EventStore",                            # bare name stays the bare name
    kind=ComponentKind.SERVICE,
    layer=Layer.INFRASTRUCTURE,
    intent="JSONL-backed event store for local operation",
    module_path="infrastructure.event_store_jsonl",
    module_scoped=True,                           # opt in
)
registry.register(spec)
```

The registry then stores this under the qualified key `"infrastructure.event_store_jsonl::EventStore"`. A different module can register its own `EventStore` (also `module_scoped=True`) with a different `module_path` and both coexist.

**Lookup rules:**

- `registry.get("infrastructure.event_store_jsonl::EventStore")` — direct O(1) hit.
- `registry.get("EventStore")` — succeeds **only when** there is exactly one scoped `EventStore` across all modules. When two or more scoped specs share the bare name, returns `None`. The registry never guesses; callers must use the qualified form to disambiguate.
- `registry.contains(name)` and `name in registry` follow the same rule.
- `registry.unregister(name)` accepts either form.

**Persistence:** module-scoped specs round-trip cleanly through `RegistrySnapshot.to_dict` / `from_dict` and through the SQLite persistence layer. Pre-0.3.0 databases migrate transparently via an additive `module_scoped INTEGER DEFAULT 0` column.

**When NOT to use it:** if you can give the component a clearer non-colliding name (`OrderEventStore` vs `BillingEventStore`), do that — the global namespace is the simpler default. Reach for `module_scoped` when renaming around the collision would itself be lossy.

### 5.8 Polling Import-Hook Anomalies — `import_hook_anomalies` (0.4.0)

The import hook (§1.3, §6.1 "Immune Response") detects unregistered public entities and stale documentation markers every time a project module loads. Pre-0.4.0 these were observable only via `UnregisteredComponentError` (strict mode) or Python warnings (lenient mode). 0.4.0 adds a structured observability surface so downstream consumers — runtime self-defence layers, dashboards, monitoring loops — can react to surveillance findings without scraping log output.

**Quick poll loop.** Once the framework is initialised, every detection is appended to a registry-side buffer that you can drain at any time:

```python
from s0ma import initialize

registry = initialize(project_root="./src")
# ... your application loads modules, some of which may trip the hook ...

for anomaly in registry.import_hook_anomalies:
    print(f"[{anomaly.severity.name}] {anomaly.name}: {anomaly.description}")
registry.clear_import_hook_anomalies()  # drain after consuming
```

**Subscribe pattern.** For long-running processes that want incremental notification rather than polling:

```python
from s0ma import initialize, ImportHookAnomaly

registry = initialize(project_root="./src")

def on_import_hook_anomaly(anomaly: ImportHookAnomaly) -> None:
    # Keep the body short — this runs synchronously under the registry lock.
    # For heavier work, push the record onto a queue and process it elsewhere.
    log.warning(
        "import-hook %s in %s: %s",
        anomaly.severity.name, anomaly.name, anomaly.description,
    )

unsubscribe = registry.subscribe_import_hook_anomalies(on_import_hook_anomaly)
# ... later, when you want to stop receiving:
unsubscribe()
```

**Behaviour pins:**

- One `ImportHookAnomaly` per detected entity: one per unregistered public class/function, one per missing documentation registration. The hook's existing exception / warning behaviour is preserved unchanged.
- `severity=AnomalySeverity.ERROR` for strict-mode detections (the import is about to raise); `severity=AnomalySeverity.WARNING` for lenient-mode detections (the import proceeds).
- `layer` is set from `registry._modules[name].layer` when the offending module previously registered module metadata; `None` otherwise (the common case — most detections fire before any registration completes for the module).
- `import_hook_anomalies` returns a defensive copy of the buffer in detection order. Mutating the returned list does not affect the buffer. Long-running processes should subscribe instead of polling, or call `clear_import_hook_anomalies()` after each drain to keep the buffer bounded.
- Append, snapshot, clear, subscribe, and subscriber dispatch all run under `ComponentRegistry._lock`, so concurrent registration + anomaly recording from multiple threads cannot lose records or interleave a subscriber dispatch with another thread's append.
- Subscriber exceptions are logged and swallowed so one bad callback cannot blackhole the rest.

**Use case.** fr3d's Phase 2 B1 IMMUNE_RESPONSE detection layer subscribes to this surface to react to foreign-code surveillance findings in real time.

### 5.9 Subscribing to Runtime Anomalies — `s0ma.anomaly_stream` (hw-foundation M1)

§5.8's channel covers import-time surveillance. Runtime detectors have their own process-wide push channel: executable-contract violations (`NOCICEPTION`, §6.1) and physical resource-bound crossings (`INFLAMMATION`) are published the moment they are detected, so long-running and embodied hosts replace health-poll timers with a subscription.

```python
from s0ma.anomaly_stream import subscribe_runtime_anomalies
from s0ma.models import Anomaly

def on_runtime_anomaly(anomaly: Anomaly) -> None:
    # Runs synchronously on the detecting call's thread — keep it short;
    # hand heavy work to a queue or executor.
    log.warning(
        "%s in %s: %s",
        anomaly.kind.name, anomaly.component_name, anomaly.message,
    )

unsubscribe = subscribe_runtime_anomalies(on_runtime_anomaly)
# ... later, when you want to stop receiving:
unsubscribe()
```

**Publishers today:**

- The `precondition` / `postcondition` decorators publish a `NOCICEPTION` anomaly immediately *before* raising `ContractViolationError`, so subscribers hear the pain signal even when the caller swallows the exception. (`postcondition(..., pass_args=True)` hands the validator `(result, *args, **kwargs)` so an effect-checking contract can compare a commanded action against its measured outcome.)
- `MetricsCollector.record_physical(name, current_ma=..., temperature_c=..., voltage_v=..., profile=...)` stores the latest physical gauges and, when the component's `ResourceProfile` declares physical bounds (`expected_max_current_ma`, `expected_max_temperature_c`, `expected_min_voltage_v`), publishes an `INFLAMMATION` anomaly per crossing at ingestion time. The interoception verifier also checks stored gauges on every poll, and components that only report gauges are checked rather than flagged as uncalled.

**Behaviour pins:**

- Dispatch is synchronous, in registration order; the subscriber list is snapshotted and dispatch happens *outside* the internal lock, so a subscriber may unsubscribe itself (or subscribe others) during dispatch.
- Subscriber exceptions are logged and swallowed so one bad callback cannot blackhole the rest.
- `emit_runtime_anomaly` is public — applications may publish their own anomalies through the same channel.
- `reset_runtime_anomaly_subscribers()` exists for test isolation.
- Conventions for embodying the hardware itself (the `hw_*` metadata vocabulary, sense/actuator roles, trust rules): ADR-003 and the patterns guide §31.

---

## Section 6: Understanding Anomaly Reports

### 6.1 The Biological Pathology Taxonomy

s0ma categorizes problems using biological analogies. Each maps to a specific detection algorithm and resolution:

| Pathology | What It Means | How It's Detected | Resolution |
|-----------|---------------|-------------------|------------|
| **Phantom Limb** | Registry entry exists, but the code is gone | Registry scan finds name with no matching module | Delete the registry entry OR restore the code |
| **Vestigial Organ** | Code exists but is never called/used | Coverage analysis + call graph shows zero references | Remove the dead code OR document why it's kept |
| **Immune Response** | Unregistered public code detected (foreign body) | Import hook finds entities without `@component` or `@internal` | Add `@component` decorator or `@internal` marker |
| **Atrophied Muscle** | Deprecated component still receiving traffic | Runtime monitoring shows calls to deprecated endpoints | Migrate callers to the replacement component |
| **Inflammation** | Component exceeding its declared resource profile | Interoception verifier compares actual metrics to `ResourceProfile` | Optimize the implementation OR update the resource profile |
| **Nociception** | A live call violated an executable contract | `precondition`/`postcondition` decorators check at call time; published on the runtime anomaly stream (§5.9) before `ContractViolationError` raises | Fix the implementation or caller OR correct an over-strict validator |

**Anomaly Severities:**

| Severity | Meaning |
|----------|---------|
| `ERROR` | Must fix — system integrity compromised |
| `WARNING` | Should investigate — potential drift |
| `INFO` | Cosmetic — no functional impact |

### 6.2 Reading a Verification Report

```python
import s0ma

registry = s0ma.initialize(project_root="./src")
report = s0ma.verify(registry)

if not report.passed:
    # Get LLM-readable explanation of all anomalies
    print(report.explain_for_llm())
```

A report, in the shape a reader should expect (illustrative — the exact wording is the report object's, not this guide's):

```
═══ s0ma Verification Report ═══

COMPONENTS: 12 registered

✓ Structural Integrity: 11/12 components match
✓ Contract Compliance: 10/12 contracts valid
✓ Dependency Graph: All declared dependencies exist
✗ Coverage Audit: 1 anomaly detected

ANOMALIES:
  [VESTIGIAL_ORGAN] components/plugins/old_weather.py
    - OldWeatherPlugin is registered but has 0 callers
    - Recommendation: Remove or mark as deprecated

  [INFLAMMATION] components/router.py
    - ChatRouter declares max_latency_ms: 50
    - Actual measured latency: 120ms (p95)
    - Recommendation: Update contract or optimize implementation

HEALTH: 2 anomalies — resolve before deployment
```

### 6.3 Verification Scopes

The verification engine runs four verifiers, each in its own scope:

| Scope | Verifier | What It Checks |
|-------|----------|----------------|
| `STRUCTURAL` | `StructuralVerifier` | Code structure matches registry declarations (phantom limbs, blind spots) |
| `CONTRACT` | `ContractVerifier` | Runtime behavior matches declared pre/postconditions and invariants |
| `INTEROCEPTION` | `InteroceptionVerifier` | Resource usage matches declared `ResourceProfile` |
| `COVERAGE` | `CoverageAuditor` | Code reachability and usage analysis (vestigial organs) |

---

## Section 7: Best Practices

### For Coding Agents

1. **Always read the self-model first.** Before writing any code, use `SelfModelInterface.describe_system()` or query `GET /self/overview` to understand the system.
2. **Follow the core loop.** Declare → Implement → Verify → Query. Every time.
3. **Write intent descriptions for other agents.** Your `intent` field should be clear enough that a different agent, with no context, can understand what this component does.
4. **Always specify `kind` and `layer` using the enum types.** Use `ComponentKind.SERVICE` and `Layer.DOMAIN`, not strings.
5. **Declare dependencies explicitly.** Even if Python imports work without it, the `dependencies` field is what the self-model uses for architectural reasoning.
6. **Run `s0ma.verify()` after every change.** Don't batch changes and verify later — verify incrementally.
7. **Use `POST /self/query` or `SelfModelInterface` when uncertain.** The self-model knows more about the system than any single file does.
8. **Use `@internal` for private helpers.** Don't leave public helpers undecorated — the import hook will block them.

### For Human Developers

1. **Think of @component as a commit message for architecture.** Every component declares its purpose, contracts, and relationships.
2. **The intent field is the most important field.** Contracts can be auto-checked. Intent can only be human-authored. Write it well.
3. **Trust the anomaly reports.** If s0ma says there's a phantom limb, there is one. The system doesn't have false positives on structural checks.
4. **Use the /self/query endpoint for onboarding.** New team members can ask the system about itself instead of reading stale documentation.

### Where to Put Shared Types

When multiple components share the same enums, dataclasses, or type aliases, collect them in a dedicated `models.py` (or `types.py`) module and mark them with `@internal`. This keeps them visible to the import hook while signaling that they are supporting types, not independent components.

```python
# myapp/models.py
from s0ma.decorators import internal
from enum import Enum
from dataclasses import dataclass

@internal
class Priority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

@internal
@dataclass
class TaskData:
    title: str
    priority: Priority
    assignee: str | None = None
```

```python
# myapp/task_service.py
from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer
from myapp.models import TaskData, Priority  # shared types

@component(
    name="TaskService",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="Creates and manages tasks using shared TaskData model",
    dependencies=[],
)
class TaskService:
    def create(self, title: str) -> TaskData:
        return TaskData(title=title, priority=Priority.MEDIUM)
```

> **Agent instruction:** Place shared enums and dataclasses in a `models.py` with `@internal`. Import them into `@component` modules. Do not scatter shared types across component files — centralize them.

### Non-Python Assets

Non-Python assets — HTML templates, CSS stylesheets, JavaScript files, images, configuration files — are **outside s0ma's enforcement scope**. The import hook only intercepts Python module loading; it has no opinion about static files.

These assets should be **served or managed by registered Python components**. The self-model tracks the Python component responsible for the assets, not the assets themselves. For example, a `DesktopServer` component might serve a `chat.html` file, but only the server is registered; the HTML file is not.

> **Agent instruction:** Do not attempt to register non-Python files with `@component`. Instead, register the Python component that owns, serves, or manages those files, and mention the assets in its `intent` or `metadata` fields if they are architecturally significant.

### Module Splitting Conventions

When a `@component` module grows too large (over 200–300 lines), split it by extracting helper logic into a companion module prefixed with `_` and decorated with `@internal`:

```
myapp/
  executor.py              ← @component class lives here (~150 lines)
  _executor_helpers.py     ← @internal helper functions (~200 lines)
```

```python
# myapp/_executor_helpers.py
from s0ma.decorators import internal

@internal
def parse_plan_steps(raw: str) -> list[dict]:
    """Extract structured steps from an LLM plan response."""
    ...

@internal
def validate_step_dependencies(steps: list[dict]) -> bool:
    """Check that step dependencies form a valid DAG."""
    ...
```

```python
# myapp/executor.py
from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer
from myapp._executor_helpers import parse_plan_steps, validate_step_dependencies

@component(
    name="PlanExecutor",
    kind=ComponentKind.ORCHESTRATOR,
    layer=Layer.APPLICATION,
    intent="Executes multi-step plans by parsing, validating, and running each step",
)
class PlanExecutor:
    def execute(self, raw_plan: str) -> list[dict]:
        steps = parse_plan_steps(raw_plan)
        if not validate_step_dependencies(steps):
            raise ValueError("Circular step dependencies detected")
        # ... execute steps
```

**Rules of thumb:**
- The `@component` class stays in the primary module — this is what the self-model tracks.
- Helper functions go into `_`-prefixed companion modules with `@internal`.
- The self-model sees the `@component` module; helpers are internal implementation details.

---

## Section 8: Testing s0ma Applications

The `s0ma.testing` module provides canonical test isolation utilities that handle the interaction between Python's module caching and s0ma's one-shot registration model. These utilities are the recommended way to write tests for any s0ma-based project.

### The Core Problem: sys.modules and One-Shot Registration

The `@component` decorator fires exactly **once** at import time. Python caches imported modules in `sys.modules`. When you call `reset_registry()` to get a clean slate for a test, already-imported modules retain their cached state — `importlib.import_module()` is a no-op for cached modules, so `@component` decorators do **not** re-fire.

**Symptom:** After `reset_registry()` + `importlib.import_module("myapp.mymodule")`, the module's components are missing from the fresh registry even though the import succeeded.

**Solution:** `s0ma.testing` handles the full eviction-and-reimport cycle automatically.

### 8.1 `fresh_registry()` — Context Manager

The primary isolation primitive. Provides a clean registry with freshly-imported modules, then restores the original global state on exit.

```python
from s0ma.testing import fresh_registry

def test_my_component():
    with fresh_registry(".", ["myapp.components", "myapp.services"]) as registry:
        # registry is fresh and empty except for re-imported components
        spec = registry.get("MyService")
        assert spec is not None
        assert spec.kind == ComponentKind.SERVICE
    # Original global registry is restored here
```

**What it does:**
1. Creates a fresh in-memory registry and sets it as the global singleton
2. Evicts all modules matching the given prefixes from `sys.modules` (e.g., `"myapp"` evicts `myapp`, `myapp.components`, `myapp.services.user`, etc.)
3. Re-imports the evicted modules in sorted order (parents before children), triggering `@component` decorators into the fresh registry
4. Yields the populated registry
5. Restores the original global registry on exit (including on exception)

**Parameters:**

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `project_root` | required | Root directory of the project (accepted for context; does not affect current behavior) |
| `module_prefixes` | required | List of module name prefixes to evict and re-import |
| `persist` | `False` | If `True`, the fresh registry uses SQLite persistence |
| `strict_dependencies` | `False` | If `True`, raises on unresolved dependencies during registration |

**Pytest fixture pattern:**

```python
import pytest
from s0ma.testing import fresh_registry
from s0ma._bootstrap import bootstrap_register

@pytest.fixture()
def app_registry():
    """Fresh registry with all application components re-registered."""
    with fresh_registry(".", ["myapp"]) as registry:
        bootstrap_register(registry)  # Register framework components too
        yield registry
```

### 8.2 `isolate_registry()` — Isolated Scope for Synthetic Components

Creates a temporary registry scope for tests that need to register synthetic (manually constructed) components without affecting the global registry or triggering any module re-imports.

```python
from s0ma.testing import isolate_registry
from s0ma.models import ComponentSpec
from s0ma.types import ComponentKind, Layer

def test_registry_query_logic():
    with isolate_registry() as registry:
        # Register synthetic components for testing
        registry.register(ComponentSpec(
            name="SyntheticService",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="A synthetic component used only in this test",
            module_path="tests.synthetic",
            qualified_name="tests.synthetic.SyntheticService",
        ))
        assert registry.contains("SyntheticService")
    # Original global registry is restored here; SyntheticService is gone
```

**When to use `isolate_registry` vs `fresh_registry`:**
- Use `fresh_registry` when you need real application modules re-imported with their actual `@component` registrations
- Use `isolate_registry` when you just need an empty sandbox to register synthetic specs for testing registry logic itself

### 8.3 `reinitialize_for_test()` — Imperative Equivalent

The non-context-manager version of `fresh_registry`. Useful in `unittest.TestCase` setups or anywhere a context manager is inconvenient:

```python
from s0ma.testing import reinitialize_for_test

class MyTestCase(unittest.TestCase):
    def setUp(self):
        # Evict and re-import myapp modules into a fresh registry
        self.registry = reinitialize_for_test(".", ["myapp.components"])

    def test_something(self):
        spec = self.registry.get("MyComponent")
        self.assertIsNotNone(spec)
```

The caller is responsible for cleanup. In `pytest` environments, the `conftest.py` autouse fixture (`reset_registry()` after each test) handles cleanup automatically.

### 8.4 `register_from_module()` — Dynamic Code Loading

For scenarios where you have an already-imported module object and need to register its components into a specific registry, use `registry.register_from_module(module)` directly:

```python
import importlib
from s0ma.registry import get_registry, reset_registry

# Reset and get a fresh registry
reset_registry()
registry = get_registry(persist=False)

# Module is already cached — importlib.import_module() returns the cache
import myapp.mymodule
mod = importlib.import_module("myapp.mymodule")  # returns cached module

# register_from_module scans the cached module and registers its components
newly_registered = registry.register_from_module(mod)
print(f"Re-registered: {[s.name for s in newly_registered]}")
```

This is most useful in production scenarios (e.g., after dynamically generating and importing a module) rather than in test code. For tests, prefer `fresh_registry` or `isolate_registry`.

### 8.5 Idempotent Registration in Tests

If your code uses `importlib.reload(module)` for hot-reloading, the `@component` decorator will fire again on reload. Use `idempotent=True` to allow this:

```python
@component(
    name="HotReloadableService",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="A service that supports hot-reload during development",
    idempotent=True,  # Allow re-registration from the same source file
)
class HotReloadableService:
    ...
```

See Section 2.7 for full documentation on idempotent registration.

### 8.6 Bootstrap Module Ordering

Projects with many components often maintain a list of modules that need to be imported at startup. When modules are imported in the wrong order, `@component` decorators may fire before their declared dependencies are registered — causing warnings in lenient mode or errors in strict mode.

s0ma provides utilities that compute the correct import order automatically from the dependency graph, replacing manually-maintained ordered module lists.

#### `topological_sort_modules()` — Pure Algorithm

A standalone function that takes a list of `(module_path, dependency_module_paths)` tuples and returns them in dependency-safe order using Kahn's algorithm. Circular dependencies are detected and reported with the cycle path.

```python
from s0ma.utils import topological_sort_modules

sorted_order = topological_sort_modules([
    ("myapp.api", ["myapp.services"]),
    ("myapp.services", ["myapp.models"]),
    ("myapp.models", []),
])
# Returns: ["myapp.models", "myapp.services", "myapp.api"]
```

If a circular dependency exists, `RegistrationError` is raised with a message describing the cycle:

```python
# Circular: api -> services -> api
topological_sort_modules([
    ("myapp.api", ["myapp.services"]),
    ("myapp.services", ["myapp.api"]),
])
# Raises: RegistrationError("Circular dependency detected among modules. ...")
```

#### `registry.import_order()` — From the Live Registry

Returns the topologically sorted module paths based on the current registry's dependency graph. Each registered component's `module_path` becomes a node, and cross-module component dependencies become edges.

```python
import s0ma

registry = s0ma.initialize(persist=False)
order = registry.import_order()
# Returns all s0ma module paths in dependency-safe order
```

This is useful for inspecting the current dependency structure or for debugging import ordering issues.

#### `bootstrap_modules()` — Convenience Function

The highest-level utility: given a list of module paths **in any order**, it imports them, discovers their `@component`-decorated entities, determines the correct module import order from the dependency graph, and registers components in dependency-safe order.

```python
from s0ma.utils import bootstrap_modules

# Order doesn't matter — bootstrap_modules figures it out
registered = bootstrap_modules([
    "myapp.api",          # depends on myapp.services
    "myapp.models",       # no dependencies
    "myapp.services",     # depends on myapp.models
])
# Imports in order: myapp.models, myapp.services, myapp.api
# Returns list of all newly registered ComponentSpec objects
```

**When to use each:**

| Scenario | Recommended utility |
|----------|-------------------|
| Need the sorted order for a known dependency graph | `topological_sort_modules()` |
| Inspecting import order of an already-populated registry | `registry.import_order()` |
| Replacing a manually-ordered `_PLATFORM_MODULES` list | `bootstrap_modules()` |
| Checking for circular module-level dependencies | `topological_sort_modules()` or `bootstrap_modules()` (both detect cycles) |

> **Agent instruction:** Use `bootstrap_modules()` when setting up application module imports during startup. It replaces the error-prone pattern of manually ordering module lists. Use `topological_sort_modules()` directly when you need ordering control without automatic import/registration.

---

## Section 9: Troubleshooting

### UnregisteredComponentError

**Cause:** You have a public class or function under the project root without `@component` or `@internal`.
**Fix:** Add the `@component` decorator if it's a meaningful component, or `@internal` if it's a private helper. Alternatively, prefix the name with `_` to make it non-public.

### RegistrationError

**Cause:** Component registration failed — missing required fields, duplicate name, invalid metadata, self-dependency, or invalid keyword arguments to dataclasses.
**Fix:** Check the `name` is unique, `kind` and `layer` are valid enum values, `intent` is at least 10 characters, and `dependencies` don't include the component's own name.

**Common variant:** If the error message says "received unexpected keyword argument" and lists valid fields, you've passed an invalid field name to `Contract`, `ComponentSpec`, `ResourceProfile`, or `ConfigurableProperty`. The error message will list all valid fields — check your code against this list to find the typo or outdated field name.

### ContractViolationError

**Cause:** Runtime behavior doesn't match declared contracts (e.g., latency exceeded, precondition failed).
**Fix:** Either fix the code to meet the contract, or update the contract to reflect reality. Don't leave mismatches — they erode trust in the self-model.

### RegistryIntegrityError

**Cause:** The registry's internal state is inconsistent — orphaned dependencies, phantom limbs, or corruption in SQLite persistence.
**Fix:** Run `s0ma.verify()` to identify the specific discrepancies. Resolve them by updating or removing the affected components.

### BootstrapError

**Cause:** s0ma's own components can't describe themselves accurately.
**Fix:** This indicates a framework-level issue. Report it. The bootstrap test is the canary — if it fails, the framework itself has a problem.

### Dynamic Code Loading: Components Not Re-Registering After Reset

**Cause:** Python caches imported modules in `sys.modules`. When `reset_registry()` is called to clear the registry (for test isolation or re-initialization), already-imported modules are not re-executed — their `@component` decorators have already fired and won't fire again on a second `importlib.import_module()` call.

**Symptom:** After `reset_registry()` and `importlib.import_module("myapp.mymodule")`, the module's components are missing from the registry even though the module imported without error.

**Fix: Use `register_from_module()`**

`registry.register_from_module(module)` scans a module object for all `@component`-decorated entities and registers any that aren't already in the registry. Since it works on an already-imported module object (not the import process itself), module caching is irrelevant:

```python
import importlib
from s0ma.registry import get_registry, reset_registry

# Reset the registry
reset_registry()
registry = get_registry(persist=False)

# The module is already in sys.modules — importlib.import_module() returns it cached
import myapp.mymodule
mod = importlib.import_module("myapp.mymodule")  # returns the cached module

# register_from_module() scans the cached module and re-registers its components
newly_registered = registry.register_from_module(mod)
print(f"Re-registered: {[s.name for s in newly_registered]}")
```

**For dynamic code generation scenarios** (where a module was just created and dynamically imported):

```python
import importlib
import importlib.util

# Dynamically import a generated module
spec = importlib.util.spec_from_file_location("generated.widget", "/path/to/widget.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # this executes @component decorators

# The @component decorators registered into the *current* global registry
# If you need to register into a *specific* registry:
my_registry.register_from_module(mod)
```

**`register_from_module()` return value:** The method returns `list[ComponentSpec]` containing only the specs that were *newly* registered in this call. Components already present in the registry are silently skipped. This makes the method idempotent and safe to call multiple times.

---

## Section 10: Documentation Subsystem (Runtime Surface)

The documentation subsystem extends registration-as-creation to documentation artifacts. In the same way that a public class or function cannot exist without a `@component` registration, a piece of generated documentation, a doc-guide, or an executable example cannot exist without a runtime registration that the rest of the system can query.

This section describes the s0ma-core **runtime** surface — the registration functions and queries that exist in Python. The **authoring** surface that emits calls into it (the `.s0ma` grammar and its transpiler) lives in the `s0ma-dsl` package of this repository and is specified by [the current DSL spec](../../s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md). Everything below is usable from plain Python without the DSL.

### 10.1 The Three Registration Kinds

| Kind | Purpose | Registry store |
|------|---------|----------------|
| `doc-ref` | A generated reference artifact (e.g. a Markdown API reference) that iterates over registry state. | `_doc_refs` |
| `doc-guide` | A hand-authored guide whose body may embed examples by reference and may carry assertions that the self-model verifies. | `_doc_guides` |
| `example` | An executable code sample that demonstrates one or more components and can be run as part of the test pipeline. | `_examples` |

All three are full first-class registrations. Each has a stable key (the `name`), persists to SQLite, serializes through `RegistrySnapshot`, and is queryable through `SelfModelInterface`, the REST API, and the MCP server.

### 10.2 Public Registration Functions

All three functions accept keyword-only arguments and return the stored registration. Each raises `RegistrationError` on duplicate name (unless `idempotent=True`) and `ValueError` on invalid input.

```python
from s0ma import register_doc_ref, register_doc_guide, register_example
from s0ma.models import EntityRef, FilterExpr, Section, SourceSpan

register_doc_ref(
    name="api_reference",
    module="myapp::api",
    intent="Reference for all public nerves",
    format="markdown",
    output="docs/api.md",
    covers=[FilterExpr(target_kind="nerve", predicate=None, raw="kind:nerve")],
    sections=[Section(title="Nerves", iterate="covers", group_by=None, render={})],
    content_hash="",
    source_span=SourceSpan(file="myapp/api.s0ma", start_line=1, end_line=20),
)

register_example(
    name="chat_router_smoke",
    module="myapp::nerves",
    intent="Smoke-test the ChatRouter nerve end-to-end",
    demonstrates=[EntityRef(kind="nerve", name="ChatRouter", module="myapp::nerves")],
    runs_in="pytest",
    body="def test_chat_router(): ...",
    source_span=SourceSpan(file="myapp/examples.s0ma", start_line=12, end_line=40),
)
```

**Validation at the boundary:**

| Field | Rule |
|-------|------|
| `format` | One of `{markdown, html, json}` |
| `output` | Non-empty relative path; no leading `/`, no `..` segments |
| `demonstrates` | Required and non-empty for examples |
| `runs_in` | One of `{standalone, pytest, integration}` |
| `name` | Globally unique within its store (module is stored but is not part of the key) |

### 10.3 Import-Hook Marker Attributes

Generated `.py` files emitted by `s0ma-dsl` carry three module-level marker attributes. Each marker advertises the names of the registrations the module is expected to install by the time its body finishes executing:

| Attribute | Registration | Import-hook constant |
|-----------|-------------|-----------------------|
| `__s0ma_doc_ref__` | `doc-ref` | `s0ma.import_hook.DOC_REF_MARKER_ATTR` |
| `__s0ma_doc_guide__` | `doc-guide` | `s0ma.import_hook.DOC_GUIDE_MARKER_ATTR` |
| `__s0ma_example__` | `example` | `s0ma.import_hook.EXAMPLE_MARKER_ATTR` |

The value is an iterable of `str` names, or a bare `str` as a single-name shorthand. If a marker entry does not resolve against the global registry at import completion, the hook raises `UnregisteredComponentError` in strict mode (warns in lenient mode). This catches stale transpiled `.py` files whose source has drifted out from under them.

Hand-authored modules generally do not need these markers — calling `register_doc_ref` / `register_doc_guide` / `register_example` directly is sufficient. The markers matter when code is generated ahead-of-time and loaded later.

### 10.4 Querying the Subsystem

The self-model surface mirrors the component-query surface one-for-one.

```python
from s0ma import initialize, SelfModelInterface

registry = initialize(persist=False)
smi = SelfModelInterface(registry)

# Registry-wide natural-language overview of every registered doc/example.
print(smi.describe_docs())

# Detail on one doc-ref or doc-guide (dispatches on the registry key).
print(smi.describe_doc("api_reference"))

# Reverse indices: what docs / examples reference a given component.
print(smi.get_docs_for_component("ChatRouter"))
print(smi.get_examples_for_component("ChatRouter"))

# Drift status — compares every stored content_hash against a fresh
# transitive recompute from the current registry state.
print(smi.get_drift_status(transpiler_version="0.2.0"))
```

`get_impact_analysis(name)` now surfaces `affected_docs` and `affected_examples` alongside the existing component-impact data, so agents running rule A-8 (see §C.10) see the full blast radius of a change in one call.

### 10.5 `RegistrySnapshot` Fields and Reverse Indices

```python
snap = registry.snapshot()

snap.doc_refs     # dict[str, DocRefRegistration]
snap.doc_guides   # dict[str, DocGuideRegistration]
snap.examples     # dict[str, ExampleRegistration]

# Reverse indices accept either an EntityRef or a "module::name" string shortcut.
snap.examples_for("myapp::nerves::ChatRouter")
result = snap.docs_for("ChatRouter")
result.refs        # list[DocRefRegistration]
result.guides      # list[DocGuideRegistration]
result.is_empty()
```

`snap.to_dict()` and `snap.to_json()` emit the new `doc_refs` / `doc_guides` / `examples` keys only when the corresponding stores are non-empty, so existing snapshot consumers see no schema churn until the documentation subsystem is in use.

### 10.6 Executable Examples

```python
from s0ma.examples import ExampleRunner

runner = ExampleRunner(registry, timeout_seconds=30)
for result in runner.run_all():
    print(result.summary())
```

Each example runs in a child process so that (a) timeouts can be enforced cross-platform via `subprocess.run(..., timeout=...)`, (b) `@component` registrations performed inside an example do not contaminate the parent registry, and (c) a failing or hung example cannot take down the caller.

`ExampleResult` is frozen and carries `passed`, `duration_ms`, `stdout`, `stderr`, `returncode`, `timed_out`, and a `summary()` one-liner. The runner never raises on per-example failure — every outcome surfaces as a result so `run_all` can aggregate full pipelines.

The `runs_in` field dispatches to three handlers:

| Mode | Behavior |
|------|----------|
| `standalone` | Writes the body to a temp script and runs `python <script>`. |
| `pytest` | Writes the body to `test_<name>.py` and runs `python -m pytest` against it. |
| `integration` | Honors `S0MA_INTEGRATION_CMD` (with `{body}` substitution); falls back to `standalone` when unset. |

**Pytest plugin (opt-in):** `pytest --s0ma-examples` collects every registered example as a pytest item named `s0ma-example::<name>`. The `s0ma_example_timeout` `pytest.ini` key overrides the default 30-second timeout. The plugin is a no-op when the flag is not passed — existing test suites are unaffected.

### 10.7 Content-Hash Subsystem

`s0ma.hashing` provides a deterministic transitive content hash used by drift detection and by the DSL's front-matter emission.

```python
from s0ma import content_hash, HASH_ALGORITHM_VERSION

digest = content_hash(doc_registration, snap, transpiler_version="0.2.0")
# e.g. "1:4f1acd..." — version-prefixed so stored hashes self-identify.
```

The hash covers the registration itself (with its own stored `content_hash` zeroed so it cannot be a fixed point of itself) plus the transitive closure of the registry state it references: doc-refs walk their `covers` filter matches, doc-guides walk `covers` EntityRefs and `examples` EntityRefs, and referenced examples are included verbatim.

Operational metadata — `registered_at` wall-clock timestamps and absolute `source_file` paths — is deliberately excluded from the hash so that two developers' checkouts of the same commit produce identical digests. `HASH_ALGORITHM_VERSION` prefixes every digest; bumping it invalidates every previously-stored hash, which forces a CI-visible re-hash on the next drift check.

### 10.8 REST and MCP Surfaces

**REST endpoints** (thin wrappers over `SelfModelInterface` / `RegistrySnapshot`; available when the `[api]` extra is installed):

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/self/docs` | Registry-wide overview (text + structured lists). |
| `GET` | `/self/doc/{name}` | Doc-ref or doc-guide detail; 404 when unknown. Returns `kind` so clients can distinguish. |
| `GET` | `/self/examples` | All registered examples. |
| `GET` | `/self/example/{name}` | Single example detail including body and source span. |
| `GET` | `/self/drift` | Transitive drift status; optional `?transpiler_version=` query parameter. |

**MCP resources and tool** (available when the `[mcp]` extra is installed):

| Surface | URI / Name |
|---------|------------|
| Resource (static) | `s0ma://docs/registered-docs` |
| Resource (templated) | `s0ma://model/examples-for/{component}` |
| Resource (templated) | `s0ma://model/docs-for/{component}` |
| Tool | `get_examples_for(component)` |

The tool mirrors the templated resource because not every MCP client exposes templated-resource reads directly; a tool round-trip keeps the surface usable from plain tool-call clients — which is the primary agent path for rule A-8.

### 10.9 What This Guide Is Authoritative About

This guide is hand-written, and hand-written prose is the weakest kind of
documentation s0ma keeps. Where it explains a *rule* or a *shape* — what
registration means, what a contract is for, how the import hook behaves — it is
the intended reading. Where it would name a *specific* registered thing — this
component, that endpoint, this many of something — the code and its runtime
self-model are the truth, and the generated references are the place to read
them, because those are rebuilt from the registry and compared byte-for-byte on
every CI run while this file is not.

That is why counts and inventories have been taken out of this guide rather than
updated in it. When you need one, ask the system: `SelfModelInterface`
(§5.1), the `/self/` endpoints (§5.2), or the generated reference pages listed in
[`docs/README.md`](../../../docs/README.md), which is itself rendered from the
documentation catalog and cannot silently disagree with what the build knows.

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| **Component** | Any class or function registered with `@component`. The atomic unit of the self-model. |
| **Self-model** | The complete hierarchical description of the system — all components, their relationships, contracts, and intent. |
| **Load-bearing** | The self-model is required for the system to function. It's not optional documentation. |
| **Registration-as-creation** | The principle that code cannot exist without being registered. The `@component` decorator is how code is born. |
| **Configurable property** | A runtime-changeable aspect of a component declared in its Contract (theme colors, layout options, etc.) — distinct from structural properties that require code changes. |
| **Idempotent registration** | A registration mode (`idempotent=True`) where re-registering the same component from the same source file silently succeeds instead of raising an error. Enables hot-reload and dynamic loading patterns. |
| **Protocol contract** | A declarative specification of a cross-boundary interface (WebSocket, REST, gRPC, IPC) captured in the self-model via `ProtocolContract`. Currently declarative only; runtime verification deferred to a future phase. |
| **Topological sort** | Dependency-aware ordering of modules for safe import sequencing — ensures each module is imported after all its dependencies. |
| **Phantom limb** | A registry entry with no corresponding code (code was deleted, registry wasn't updated). |
| **Vestigial organ** | Code that exists but serves no purpose (never called, no references). |
| **Immune response** | The system's reaction to unregistered or non-conforming code. |
| **Inflammation** | A component exceeding its declared resource profile (latency, memory, error rate, physical bounds). |
| **Nociception** | A live call violating an executable contract — the pain signal published on the runtime anomaly stream before the `ContractViolationError` raises. |
| **Interoception** | Runtime monitoring of internal state (latency, error rates, resource usage). |
| **Homunculus weight** | How important a component is — determines verification frequency and detail level. |
| **Plugin** | A first-class extension registered via `register_plugin()`. Declares what it provides and what core components it depends on, with validation at registration time. |
| **IR store** | Runtime storage for transpiler intermediate representation data, queryable through the registry via `store_ir()` / `get_ir()`. |
| **Bootstrap test** | The foundational test: can the system accurately describe itself? |

---

## Appendix B: Python API Reference

### Core Functions (s0ma)

```python
import s0ma

# Initialize the framework and install import hook
registry = s0ma.initialize(
    project_root="./src",  # None = no import hook
    persist=True,           # SQLite persistence
    strict=True,            # Raise vs warn on violations
)

# Run full verification suite
report = s0ma.verify(registry)
```

### Decorators (s0ma.decorators)

```python
from s0ma.decorators import component, internal

@component(name, kind, layer, intent, *, contracts, dependencies, resource_profile,
           version, metadata, idempotent=False)
# idempotent=True: silently succeed on re-registration from the same source file.
# Useful for hot-reload and dynamic loading. Still raises on name collision from
# a different source file.

@internal                       # Bare: marks helper as intentionally unregistered
@internal(reason="...")         # With reason: same, but documents why
```

### Types (s0ma.types)

```python
from s0ma.types import ComponentKind, Layer

# ComponentKind: SERVICE | FUNCTION | MODEL | ADAPTER | ORCHESTRATOR
# Layer: DOMAIN | APPLICATION | INFRASTRUCTURE | PRESENTATION
```

### Models (s0ma.models)

```python
from s0ma.models import (
    Contract, ConfigurableProperty, ProtocolContract,
    ResourceProfile, ComponentSpec, PluginRegistration,
)

# ConfigurableProperty: descriptor for runtime-configurable component properties
ConfigurableProperty(type, default, description=None, constraints=None, category=None)
ConfigurableProperty.from_dict(data)  # Deserialize from dictionary
property.to_dict()                     # Serialize to dictionary

# ProtocolContract: cross-boundary interface contract (WebSocket, REST, gRPC, IPC)
ProtocolContract(protocol_type, message_types, description=None)
ProtocolContract.from_dict(data)      # Deserialize from dictionary
protocol.to_dict()                     # Serialize to dictionary

# Contract: behavioral contract with serialization
Contract(preconditions, postconditions, invariants, max_latency_ms, error_rate_threshold,
         input_type, output_type, configurable_properties, protocol, forbids)
Contract.from_dict(data)              # Deserialize from dictionary (with validation)
contract.to_dict()                     # Serialize to dictionary

# ResourceProfile: expected resource usage with serialization
ResourceProfile(expected_memory_mb, expected_latency_p50_ms, expected_latency_p99_ms,
                expected_error_rate, expected_call_frequency_per_min)
ResourceProfile.from_dict(data)       # Deserialize from dictionary (with validation)
profile.to_dict()                      # Serialize to dictionary

# ComponentSpec: registration metadata with serialization
ComponentSpec(name, kind, layer, intent, contracts, dependencies, resource_profile,
              version, metadata, module_path, qualified_name, source_file,
              registered_at, is_framework)
ComponentSpec.from_dict(data)         # Deserialize from dictionary (converts enum strings)
spec.to_dict()                         # Serialize to dictionary (enum names as strings)
```

### Registry (s0ma.registry)

```python
from s0ma.registry import ComponentRegistry, get_registry, reset_registry, set_registry

# Core registration
registry.register(spec)                    # Register a ComponentSpec (raises on duplicate)
registry.register(spec, idempotent=True)  # Silently succeed if same name + same source_file;
                                          # still raises if name exists from a different source
registry.unregister("name")               # Remove a component by name
registry.register_from_module(module)     # Scan module, register any new @component entities
                                          # Returns list[ComponentSpec] of newly registered specs
registry.register_or_update(spec)         # Upsert: register if new, update if same source_file,
                                          # raise if name collision from different source
                                          # Returns the registered ComponentSpec

# Retrieval and queries
registry.get("name")                      # Returns ComponentSpec or None
registry.get_all()                        # Returns dict[str, ComponentSpec] copy
registry.query_by_layer(layer)            # Returns list[ComponentSpec]
registry.query_by_kind(kind)              # Returns list[ComponentSpec]
registry.contains("name")                # Returns bool
len(registry)                             # Component count
"name" in registry                        # Containment check

# Dependency graph
registry.get_dependencies("name")         # Resolved deps as list[ComponentSpec]
registry.get_dependents("name")           # Reverse lookup: who depends on this
registry.get_dependency_graph()           # Full graph as dict[str, list[str]]

# Import ordering
registry.import_order()                   # Topologically sorted module paths based on
                                          # the current dependency graph

# Snapshot and serialization
registry.snapshot()                       # Returns RegistrySnapshot (frozen view)
registry.to_dict()                        # Complete state as JSON-serializable dict

# IR storage (transpiler intermediate representation)
registry.store_ir("module", ir_data)      # Store IR data for a module
registry.get_ir("module")                 # Retrieve IR data (or None)
registry.get_all_ir()                     # All stored IR data

# Plugin registration
registry.register_plugin(                 # Register plugin with dep validation
    name="...", version="...", intent="...",
    registers=["..."], requires_core=["..."],
)
registry.get_plugin("name")              # PluginRegistration or None
registry.get_all_plugins()               # All registered plugins

# Reset and teardown
registry.reset()                          # Clear all components (memory + persistence)
registry.close()                          # Close SQLite connection

# Global singleton management
get_registry(persist=True)               # Get or create global singleton
set_registry(registry)                   # Replace global singleton
reset_registry()                          # Clear and remove global singleton
```

### Self-Model Interface (s0ma.self_model)

```python
from s0ma import SelfModelInterface

smi = SelfModelInterface(registry)
smi.describe_system()                            # Full system overview
smi.describe_component("name")                  # Component detail
smi.get_architecture_context()                  # Full context for LLM planning
smi.get_impact_analysis("name")                 # What breaks if this changes
smi.get_available_extension_points()            # Where to add new components
smi.get_recent_changes(limit=10)                # Recent lifecycle events

# LLM-aware audience-specific output:
smi.describe_for_code_generation("myapp")       # Code-gen optimized output
smi.describe_for_agent("code_generation",       # Context dispatch
    target_package="myapp")
smi.describe_for_agent("architectural_review")  # → get_architecture_context()
smi.describe_for_agent("debugging")             # Anomalies + dependency graph
```

### REST API (s0ma.api)

```python
from s0ma.api.rest import create_app

app = create_app(registry, metrics_collector=None, lifecycle_manager=None)
# Run with: uvicorn module:app --reload
```

### Lifecycle Management (s0ma.lifecycle)

```python
from s0ma import LifecycleManager
from s0ma.lifecycle import TransactionContext

lm = LifecycleManager(registry)
# Runtime create, update, remove components with rollback support
```

### Testing Utilities (s0ma.testing)

```python
from s0ma.testing import fresh_registry, reinitialize_for_test, isolate_registry

# Context manager: clean registry with freshly-imported modules
with fresh_registry(
    project_root=".",               # Project root (for context)
    module_prefixes=["myapp"],      # Prefixes to evict and re-import
    persist=False,                  # In-memory (default)
    strict_dependencies=False,      # Lenient dependency checking (default)
) as registry:
    spec = registry.get("MyComponent")

# Context manager: isolated scope for synthetic components (no module eviction)
with isolate_registry(persist=False) as registry:
    registry.register(synthetic_spec)
    # registry is fresh and isolated; original restored on exit

# Imperative equivalent of fresh_registry (caller responsible for cleanup)
registry = reinitialize_for_test(
    project_root=".",
    module_prefixes=["myapp"],
    persist=False,
)
```

### Bootstrap and Import-Ordering Utilities (s0ma.utils)

```python
from s0ma.utils import topological_sort_modules, bootstrap_modules

# Topological sort: pure algorithm for module dependency ordering
sorted_order = topological_sort_modules([
    ("myapp.api", ["myapp.services"]),       # api depends on services
    ("myapp.services", ["myapp.models"]),     # services depends on models
    ("myapp.models", []),                      # models has no deps
])
# Returns: ["myapp.models", "myapp.services", "myapp.api"]
# Raises RegistrationError on circular dependencies with cycle info

# Bootstrap modules: import and register in dependency-safe order
registered = bootstrap_modules(
    module_paths=["myapp.api", "myapp.models", "myapp.services"],
    project_root=".",            # Optional: project root for context
)
# Returns: list[ComponentSpec] of all newly registered components
# Raises RegistrationError on circular module-level dependencies
```

---

## Appendix C: Compliance Rules

This appendix consolidates every rule that must be adhered to when building or modifying a s0ma-compliant application. Rules are organized by category and marked by enforcement level.

**Enforcement Levels:**

| Level | Meaning |
|-------|---------|
| **ENFORCED** | Violation is caught automatically by the import hook or verifier at runtime. The system will not function if this rule is broken. |
| **VERIFIED** | Violation is detected by `s0ma.verify()` and reported as an anomaly. The system may still run, but the self-model is degraded. |
| **CONVENTION** | Not automatically enforced, but following this rule is expected for a well-formed s0ma application. |

---

### C.1 The Foundational Rule

| # | Rule | Level |
|---|------|-------|
| **F-1** | **Nothing exists unless it is registered.** Every public class or function under the project root must be decorated with `@component` or `@internal`. Registration is creation. | ENFORCED |

---

### C.2 Initialization Rules

| # | Rule | Level |
|---|------|-------|
| **I-1** | `s0ma.initialize()` must be called **before** importing any application modules. This activates the import hook that enforces registration. | ENFORCED |
| **I-2** | `project_root` must be provided to `s0ma.initialize()` for the import hook to be installed. Without it, no enforcement occurs. | CONVENTION |
| **I-3** | Python 3.11 or higher is required. | ENFORCED |

---

### C.3 Registration Rules (the `@component` decorator)

| # | Rule | Level |
|---|------|-------|
| **R-1** | Every `@component` must specify all four required fields: `name`, `kind`, `layer`, and `intent`. | ENFORCED |
| **R-2** | `name` must be globally unique across all registered components. | ENFORCED |
| **R-3** | `name` must use PascalCase and contain no whitespace. | CONVENTION |
| **R-4** | `kind` must be a `ComponentKind` enum value (`SERVICE`, `FUNCTION`, `MODEL`, `ADAPTER`, or `ORCHESTRATOR`), not a string. | ENFORCED |
| **R-5** | `layer` must be a `Layer` enum value (`DOMAIN`, `APPLICATION`, `INFRASTRUCTURE`, or `PRESENTATION`), not a string. | ENFORCED |
| **R-6** | `intent` must be at least 10 characters and describe what the component does in plain English (1-2 sentences). | ENFORCED |
| **R-7** | `dependencies` must list the names of other registered components this component depends on. Names must exactly match registered component names. | VERIFIED |
| **R-8** | A component must not list itself in its own `dependencies`. | ENFORCED |
| **R-9** | `contracts` should be specified using the `Contract` dataclass. | CONVENTION |
| **R-10** | If `max_latency_ms` is specified in a contract, it must be a positive number. | ENFORCED |
| **R-11** | If `error_rate_threshold` is specified in a contract, it must be between 0.0 and 1.0. | ENFORCED |
| **R-12** | If `configurable_properties` is specified, each entry must have a valid `type` (str, int, float, bool, or enum) and a `default` value that matches the declared type. For enum types, `allowed_values` must be a non-empty list containing the default value. For numeric types with constraints, `min` must be less than `max`. | ENFORCED |
| **R-13** | Invalid keyword arguments to `Contract`, `ComponentSpec`, `ResourceProfile`, or `ConfigurableProperty` raise `RegistrationError` with a message listing all valid fields. This helps catch typos and outdated field names in LLM-generated code. | ENFORCED |
| **R-14** | `idempotent=True` silently accepts re-registration only when `source_file` matches the existing registration. A name collision from a different source file always raises `RegistrationError`, regardless of the `idempotent` flag. | ENFORCED |
| **R-15** | If `protocol` is specified, it must use the `ProtocolContract` dataclass with a non-empty `protocol_type` and `message_types` dict. Protocol contracts are currently declarative only; runtime verification is deferred to a future phase. | ENFORCED |
| **R-16** | Component `name` must not collide with s0ma framework component names (names where `is_framework=True`). Every bootstrap component is reserved (e.g., `ComponentRegistry`, `SelfModelInterface`, `Contract`, `LifecycleManager`); query the registry rather than working from a remembered list. Use project-name prefixes to avoid collisions (see Section 2, "Component Name Uniqueness and Reserved Names"). | ENFORCED |

---

### C.4 Internal Marker Rules (the `@internal` decorator)

| # | Rule | Level |
|---|------|-------|
| **N-1** | Private helper functions or classes that are not independent components but live alongside component code must be decorated with `@internal`. | ENFORCED |
| **N-2** | `@internal` entities are exempt from the import hook and are never registered in the self-model. | ENFORCED |
| **N-3** | Alternatively, prefixing a name with `_` makes it non-public and therefore exempt from enforcement. | ENFORCED |
| **N-4** | `@internal` may optionally include a `reason` string documenting why the entity is unregistered. | CONVENTION |

---

### C.5 Modification Rules

| # | Rule | Level |
|---|------|-------|
| **M-1** | When a component's behavior changes, the `intent` field must be updated if the purpose has changed. | VERIFIED |
| **M-2** | When a component's inputs, outputs, or invariants change, the `contracts` field must be updated. | VERIFIED |
| **M-3** | When a component adds or removes imports of other components, the `dependencies` field must be updated. | VERIFIED |
| **M-4** | `s0ma.verify()` must be run after every modification. | CONVENTION |
| **M-5** | When renaming a component, all other components that list the old name in their `dependencies` must be updated. | VERIFIED |
| **M-6** | When moving a component to a different layer, the new `Layer` enum value must be appropriate for the component's purpose. | VERIFIED |

---

### C.6 Removal Rules

| # | Rule | Level |
|---|------|-------|
| **D-1** | Before removing a component, check what depends on it using `SelfModelInterface.get_impact_analysis()` or the `/self/impact/{name}` endpoint. | CONVENTION |
| **D-2** | All dependent components must be updated or removed before deleting a component. | VERIFIED |
| **D-3** | After removing a component, `s0ma.verify()` must be run to detect phantom limbs. | CONVENTION |
| **D-4** | A dangling dependency reference (component A declares dependency on deleted component B) is a `PHANTOM_LIMB` anomaly with severity `ERROR`. | VERIFIED |

---

### C.7 Self-Model Integrity Rules

| # | Rule | Level |
|---|------|-------|
| **S-1** | The self-model is **load-bearing** — it is a structural dependency, not optional documentation. Deleting the registry breaks the system. | ENFORCED |
| **S-2** | The self-model is the authoritative source of truth about the system's architecture. Query it before making changes. | CONVENTION |
| **S-3** | Every registered component must have corresponding code. A registry entry without code is a `PHANTOM_LIMB`. | VERIFIED |
| **S-4** | Every piece of public code must have a corresponding registry entry. Code without registration triggers an `IMMUNE_RESPONSE`. | ENFORCED |
| **S-5** | Code that exists but is never called or referenced is a `VESTIGIAL_ORGAN`. | VERIFIED |
| **S-6** | A component exceeding its declared `ResourceProfile` is an `INFLAMMATION`. | VERIFIED |
| **S-7** | A deprecated component still receiving traffic is an `ATROPHIED_MUSCLE`. | VERIFIED |
| **S-8** | A live call that violates an executable contract is a `NOCICEPTION` — published on the runtime anomaly stream, then raised as `ContractViolationError`. | ENFORCED |

---

### C.8 Contract Rules

| # | Rule | Level |
|---|------|-------|
| **C-1** | If a contract declares `preconditions`, they must be true before the component is invoked. | VERIFIED |
| **C-2** | If a contract declares `postconditions`, the component must guarantee them after execution. | VERIFIED |
| **C-3** | If a contract declares `invariants`, those properties must always hold. | VERIFIED |
| **C-4** | If runtime behavior does not match declared contracts, either fix the code or update the contract. Mismatches erode trust in the self-model. | VERIFIED |
| **C-5** | If a contract declares `forbids`, the component must never do what they name. No verifier checks this: the people and agents who change the code hold it to them. | CONVENTION |

---

### C.9 Verification Rules

| # | Rule | Level |
|---|------|-------|
| **V-1** | `s0ma.verify()` must be run after every change. Verify incrementally, not in batches. | CONVENTION |
| **V-2** | Anomalies with severity `ERROR` must be fixed before deployment. | CONVENTION |
| **V-3** | Anomalies with severity `WARNING` should be investigated. | CONVENTION |
| **V-4** | Four verification scopes are always run: `STRUCTURAL`, `CONTRACT`, `INTEROCEPTION`, and `COVERAGE`. | ENFORCED |

---

### C.10 Agent-Specific Rules

These rules apply specifically to coding agents working within a s0ma project:

| # | Rule | Level |
|---|------|-------|
| **A-1** | Always read the self-model first. Before writing any code, use `SelfModelInterface.describe_system()` or `GET /self/overview`. | CONVENTION |
| **A-2** | Follow the core loop: Declare, Implement, Verify, Query. Every time. | CONVENTION |
| **A-3** | Write `intent` descriptions for other agents. The field must be clear enough that a different agent, with no prior context, can understand the component. | CONVENTION |
| **A-4** | Use `@internal` for private helpers. Never leave public helpers undecorated. | ENFORCED |
| **A-5** | When modifying a component, always check whether `intent`, `contracts`, and `dependencies` still accurately describe it. | VERIFIED |
| **A-6** | Never just delete a file. Always check dependencies first via impact analysis. | CONVENTION |
| **A-7** | When uncertain about architecture, query the self-model before making changes. It is the authoritative source. | CONVENTION |
| **A-8** | When modifying a component, check `SelfModelInterface.get_docs_for_component(name)` and `get_examples_for_component(name)`. Update affected docs and examples atomically in the same change. | VERIFIED |
| **A-9** | Never embed a raw code sample in a doc-guide body. Always reference a registered example via `{{example::<name>}}`. | ENFORCED |

---

### C.11 Summary: Quick Compliance Checklist

Use this checklist when creating or modifying a component:

```
 [ ] s0ma.initialize() is called before any application imports
 [ ] @component decorator is present with all four required fields (name, kind, layer, intent)
 [ ] name is PascalCase, globally unique, no whitespace
 [ ] kind uses ComponentKind enum, not a string
 [ ] layer uses Layer enum, not a string
 [ ] intent is >= 10 characters, describes purpose clearly
 [ ] dependencies lists all components this one imports/uses
 [ ] contracts reflect actual inputs, outputs, invariants, and performance
 [ ] configurable_properties declared for runtime-adjustable settings (if any)
 [ ] protocol declared for cross-boundary interfaces (WebSocket, REST, etc.) if any
 [ ] All private helpers use @internal or _ prefix
 [ ] s0ma.verify() passes with no ERROR-level anomalies
```

---

*This guide is itself a component of the s0ma framework. It describes the system and is described by the system.*
