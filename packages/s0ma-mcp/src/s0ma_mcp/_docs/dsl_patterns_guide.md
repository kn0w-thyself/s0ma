# s0ma DSL Patterns Guide

**Audience:** Coding agents (primary), human developers (secondary)  
**Version:** 1.0 — Milestone 13  
**Last Updated:** 2026-04-01  
**Scope:** Documents patterns, conventions, and heuristics that supplement the quick reference and the specification

> **A complete worked example exists.** The s0ma authoring MCP server is itself authored in `.s0ma` and built at the full `release` gate: three production modules (`packages/s0ma-mcp/s0ma_src/` in the s0ma monorepo) exercising nerves with decorator-stacked bodies, CONSTANT cells with `content: @file()` prompt templates and `placeholders:` contracts, helpers, `declares_attributes` metadata, cross-package `requires:` colon-overrides, `test` declarations, a `doc-ref`, a `doc-guide`, and an embedded `example` — plus a committed build output the package bootstraps from. When a pattern below feels abstract, read how the server applies it.

---

## 1. The `requires` Import Heuristic

The `requires` field on a `module` declaration lists external Python dependencies. The transpiler must convert each entry into a Python import statement — either `import X` or `from X import Y`. Three mechanisms determine which form is used, evaluated in priority order.

### 1.1 Colon Override Syntax (Highest Priority)

Use a colon (`:`) to explicitly force a `from ... import ...` statement:

```
requires: [unittest.mock:patch, unittest.mock:MagicMock]
```

Transpiles to:

```python
from unittest.mock import patch
from unittest.mock import MagicMock
```

**When to use:** When the capitalization heuristic (below) would produce the wrong result. The most common case is lowercase names in submodules: `dataclasses:dataclass`, `functools:wraps`, `contextlib:contextmanager`.

### 1.2 Known-Exceptions List (Second Priority)

The transpiler maintains a hard-coded list of common stdlib dotted paths that are always treated as from-imports, regardless of capitalization:

| Entry | Transpiles to |
|-------|---------------|
| `datetime.datetime` | `from datetime import datetime` |
| `datetime.timezone` | `from datetime import timezone` |
| `datetime.timedelta` | `from datetime import timedelta` |
| `collections.defaultdict` | `from collections import defaultdict` |
| `collections.Counter` | `from collections import Counter` |
| `collections.OrderedDict` | `from collections import OrderedDict` |
| `dataclasses.dataclass` | `from dataclasses import dataclass` |
| `dataclasses.field` | `from dataclasses import field` |
| `functools.wraps` | `from functools import wraps` |
| `functools.lru_cache` | `from functools import lru_cache` |
| `functools.partial` | `from functools import partial` |
| `contextlib.contextmanager` | `from contextlib import contextmanager` |
| `contextlib.asynccontextmanager` | `from contextlib import asynccontextmanager` |
| `typing.Any` | `from typing import Any` |
| `typing.Optional` | `from typing import Optional` |
| `typing.Union` | `from typing import Union` |

**Source:** `_KNOWN_FROM_IMPORTS` in `src/s0ma_dsl/parser/s0ma_parser.py`.

### 1.3 Capitalization Heuristic (Default)

For multi-segment dotted paths not in the known-exceptions list, the transpiler inspects the **final segment**:

- **Uppercase first character** (PascalCase) → `from ... import ...`
- **Lowercase first character** → `import ...`

| `requires` entry | Final segment | Form | Transpiles to |
|------------------|---------------|------|---------------|
| `uuid.UUID` | `UUID` (upper) | from-import | `from uuid import UUID` |
| `pathlib.Path` | `Path` (upper) | from-import | `from pathlib import Path` |
| `os.path` | `path` (lower) | regular import | `import os.path` |
| `json` | `json` (single) | regular import | `import json` |
| `re` | `re` (single) | regular import | `import re` |

**Single-segment names** (no dot) are always regular imports: `import json`, `import re`, `import time`.

### 1.4 Aliases

Any `requires` entry can include an `as` alias:

```
requires: [pathlib.Path as P, json as j]
```

Transpiles to:

```python
from pathlib import Path as P
import json as j
```

### 1.5 Common Pitfalls

**NAMESPACE_COLLISION with `datetime`:** If you need both `datetime.datetime` and `datetime.timezone`, both are in the known-exceptions list and work correctly:

```
requires: [datetime.datetime, datetime.timezone]
```

Transpiles to:

```python
from datetime import datetime
from datetime import timezone
```

However, if you also need the `datetime` module itself (e.g., for `datetime.date`), this creates a namespace collision — the `from datetime import datetime` statement shadows the module name. Solution: use a separate entry with an alias:

```
requires: [datetime.datetime, datetime as dt_mod]
```

**`typing` module is usually unnecessary:** Python 3.11+ supports `X | None` instead of `Optional[X]`, and built-in generics (`list[str]`, `dict[str, int]`) instead of `typing.List`, `typing.Dict`. Only include `typing.Any` or `typing.Optional` if your body code explicitly uses the `Any` annotation or `Optional[X]` form. The transpiler's VESTIGIAL_IMPORT check will flag unused typing imports.

**Lowercase stdlib from-imports:** Entries like `dataclasses.dataclass` have a lowercase final segment but need a from-import. If they're not in the known-exceptions list, use the colon override: `dataclasses:dataclass`.

**Five stdlib spellings that recur in agent-authored code.** Each reads to the heuristic as the wrong form; reach for the colon override:

- `urllib.<sub>` collisions — declare `requires: [urllib.parse:urlencode]` when you want the un-dotted symbol; the body then writes `urlencode(...)` directly.
- `uuid.uuid4` — `uuid4` is lowercase, so the heuristic would emit `import uuid.uuid4` (wrong), and the dotted form draws `REQUIRES_DOTTED_LOWERCASE_HINT`. Use `requires: [uuid:uuid4]`.
- `typing:cast` — lowercase typing symbols (`cast`, `overload`, `final`) read like a submodule to the heuristic. The colon override emits `from typing import cast` and the body writes `cast(...)`.
- `dataclasses` — MODEL cells with `@dataclass`-decorated bodies almost always need `dataclasses` in `requires:`. If the body calls `field(default=...)`, add the colon override too: `requires: [dataclasses, dataclasses:field]`.
- `argparse.REMAINDER` — pick the form that matches your call site: `requires: [argparse]` for `argparse.REMAINDER`, `requires: [argparse:REMAINDER]` for the bare symbol. Mixing the two surfaces as `VESTIGIAL_IMPORT`.

**Body-evidence scope.** The vestigial-import detector counts a `requires:` entry as live when *any* body — including inner closures and nested `def`s inside class-bodied SERVICE / ADAPTER nerves — references the imported name. An import used only inside a method's nested helper still counts as live; the detector recurses.

---

## 2. SERVICE Nerve Patterns

SERVICE nerves represent stateful services with callable interfaces. The DSL supports two body patterns: **function-based** (factory/dict) and **class-based**.

### 2.1 Function-Based Pattern (Factory/Dict)

The original and simplest pattern. The nerve body is a `def` that returns a dict mapping operation names to callables:

```
nerve create_greeting_service :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "Provides greeting messages based on time of day"
    expects: "Valid username string"
    guarantees: "Returns a greeting containing the username"
    forbids: none
    ---
    def create_greeting_service(default_greeting="Hello"):
        def greet(username: str) -> str:
            return f"{default_greeting}, {username}!"

        def greet_formal(username: str) -> str:
            return f"Dear {username}, good day."

        return {
            "greet": greet,
            "greet_formal": greet_formal,
        }
```

**Calling convention:**

```python
service = create_greeting_service(default_greeting="Hi")
result = service["greet"]("Alice")  # "Hi, Alice!"
```

**State management:** Closure variables capture state. The factory function's parameters and local variables persist across method calls via closure:

```
nerve create_counter_service :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "Maintains a counter with increment and read operations"
    expects: "Optional initial value"
    guarantees: "Counter value is always non-negative"
    forbids: none
    ---
    def create_counter_service(initial=0):
        state = {"count": initial}

        def increment(n=1):
            state["count"] += n
            return state["count"]

        def get():
            return state["count"]

        def reset():
            state["count"] = 0

        return {
            "increment": increment,
            "get": get,
            "reset": reset,
        }
```

**When to use:** Simple services with a few operations, no inheritance needs, no complex initialization. This is the standard pattern.

### 2.1.1 Structured `provides:` with per-method contracts (POST-3a, 0.15.0)

The flat form (`provides: [greet, greet_formal]`) declares which operations the SERVICE exposes — the validator checks that each name appears as a `def` in the body, and that's it. For SERVICE nerves whose surface area grows past three or four operations (fr3d's MS 11 settings tools, MS 12 budget tools, and the MS 17-local OAuth nerves are the motivating examples), the flat form leaves the per-method contract scattered between docstrings, type-hints, and the body's prose comments. The structured form lets the author declare the contract inline, one entry per operation:

```
nerve create_greeting_service :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "Provides greeting messages based on time of day"
    expects: "Valid username string"
    guarantees: "Returns a greeting containing the username"
    forbids: none
    provides:
      - greet:
          returns: "str — informal greeting addressed to username"
          expects: "username: str (non-empty)"
          guarantees: "result starts with the configured greeting"
      - greet_formal:
          returns: "str — formal greeting using 'Dear <name>'"
          expects: "username: str (non-empty)"
          guarantees: "result begins with 'Dear '"
    ---
    def create_greeting_service(default_greeting="Hello"):
        def greet(username: str) -> str:
            return f"{default_greeting}, {username}!"

        def greet_formal(username: str) -> str:
            return f"Dear {username}, good day."

        return {
            "greet": greet,
            "greet_formal": greet_formal,
        }
```

**Three things to know.**

1. **The flat form still works.** `provides: [greet, greet_formal]` parses unchanged. Mixing flat and structured items in one block (`- greet:\n    returns: "..."` followed by `- greet_formal`) raises `MIXED_PROVIDES_FORMS` — pick one form per block.
2. **Every triple slot is optional.** Declare just `returns:` (or just `guarantees:`) when that's the only corner that adds clarity. Absent slots are omitted from the IR and the emitted `metadata` dict; readers can tell at a glance which corners the author chose to pin. `forbids:` is not one of the slots. What the service must never do, whichever operation is called, is written once, on the nerve's own `forbids:` line: one sentence that starts with "Never", or `none`, as here, when nothing is ruled out.
3. **The structured form tightens the typo check.** When at least one entry carries a triple AND the body terminates with a `return {...}` literal, the validator additionally compares the returned-dict keys against the structured `provides:` names. That catches the `"asemble"`-vs-`"assemble"` class of bug at `s0ma check` time — the same coverage the standalone `returns:` field offers (see spec §4.1.5), without needing a second declaration.

**Where the metadata lands.** The per-method triple rides through the IR under `components[].fields.provides_contracts` (a list-of-dicts keyed by `name` plus whichever of `returns` / `expects` / `guarantees` was declared) and is woven into the emitted `metadata={...}` dict on the `@component` call under the `"provides_contracts"` key. Introspecting agents read the dict from the registry at runtime — no source re-parse, no docstring archaeology.

**When to use:** SERVICE nerves with three or more operations where the per-method contracts are worth pinning at the declaration site. For two-operation services where the docstring + type-hint already carry the contract clearly, the flat form is still the right default.

### 2.2 Class-Based Pattern (New in MS 8)

For services that benefit from class structure — complex initialization, inheritance, property access, or many methods:

```
nerve HttpClient :: INFRASTRUCTURE
    kind: SERVICE
    visibility: PUBLIC
    intent: "HTTP client with connection pooling and retry logic"
    expects: "Base URL and optional timeout"
    guarantees: "All requests go through the connection pool"
    forbids: none
    ---
    class HttpClient:
        def __init__(self, base_url: str, timeout: int = 30):
            self._base_url = base_url
            self._timeout = timeout
            self._session = None

        def get(self, path: str) -> dict:
            return self._request("GET", path)

        def post(self, path: str, data: dict) -> dict:
            return self._request("POST", path, data)

        def _request(self, method: str, path: str, data=None) -> dict:
            # Implementation details...
            url = f"{self._base_url}/{path}"
            return {"status": 200, "url": url}
```

**What the transpiler emits:** The class is renamed to `_HttpClientImpl` and a factory function `HttpClient(...)` is generated that returns a dict of public methods:

```python
class _HttpClientImpl:
    def __init__(self, base_url: str, timeout: int = 30):
        # ... original body ...

    def get(self, path: str) -> dict: ...
    def post(self, path: str, data: dict) -> dict: ...
    def _request(self, method: str, path: str, data=None) -> dict: ...


@component(
    name="HttpClient",
    kind=ComponentKind.SERVICE,
    layer=Layer.INFRASTRUCTURE,
    intent="HTTP client with connection pooling and retry logic",
)
def HttpClient(base_url: str, timeout: int = 30):
    """Dict-compatible factory for HttpClient."""
    instance = _HttpClientImpl(base_url, timeout)
    return {
        "get": instance.get,
        "post": instance.post,
    }
```

**Key points:**
- Only **public methods** (no leading `_`) are exposed in the returned dict
- The `_Impl` class is not registered — only the factory function gets `@component`
- The calling convention remains dict-based: `client["get"]("/api/data")`
- `__init__` parameters become the factory function's parameters

**When to use:** Complex services with many methods, inheritance hierarchies, private helper methods, or when class structure improves readability.

### 2.3 Testing SERVICE Nerves

Both patterns produce dict-returning callables, so the test pattern is the same:

```
test test_greeting_service :: DOMAIN
    intent: "Verifies greeting service returns correct messages"
    tests: [greeting.create_greeting_service]
    ---
    def test_greeting_service():
        svc = create_greeting_service(default_greeting="Hey")
        assert svc["greet"]("Bob") == "Hey, Bob!"
```

**Mock pattern for service dependencies:** When a nerve depends on a SERVICE, mock it with a plain dict:

```python
def test_something_that_uses_service():
    mock_service = {
        "get": lambda path: {"status": 200},
        "post": lambda path, data: {"status": 201},
    }
    result = my_nerve(http_client=mock_service)
    assert result["status"] == 200
```

This works because both factory/dict and class-based patterns produce dicts at the call site.

---

## 3. `test` Block Scope Behavior

### 3.1 Module-Scoped Emission

All functions defined inside a `test` block are emitted at **module scope** in the transpiled Python file — they are NOT nested inside a class or function wrapper. This means:

- Helper functions defined in one `test` block are accessible from other `test` blocks in the same module
- If two `test` blocks define a helper with the same name, the second silently overwrites the first
- The transpiler emits a `HELPER_NAME_COLLISION` warning when this happens
- The function the runner collects must be named `test...`. A `test` block whose code defines no such function is `TEST_NOT_COLLECTED` — a warning in `dev`, refused in `strict` and `release` — because the block would count as coverage for the parts it names without ever running

**Example:**

```
test test_parsing :: DOMAIN
    intent: "Verifies parser handles valid input"
    tests: [parser.parse]
    ---
    def _make_input(text):
        return {"raw": text}

    def test_parsing():
        inp = _make_input("hello")
        assert parse(inp) is not None

test test_validation :: DOMAIN
    intent: "Verifies validator rejects invalid input"
    tests: [parser.validate]
    ---
    def test_validation():
        inp = _make_input("bad!")  # Uses helper from test_parsing block
        assert validate(inp) == False
```

In the transpiled output, `_make_input` and both test functions all appear at module scope. The second `test` block can use `_make_input` because it's already defined above.

### 3.2 Multi-Function Test Bodies

A `test` block may define multiple functions. All are emitted at module scope:

```
test test_suite :: DOMAIN
    intent: "Comprehensive parser tests"
    tests: [parser.parse]
    ---
    def _setup():
        return create_parser()

    def test_basic():
        p = _setup()
        assert p.parse("x") is not None

    def test_empty():
        p = _setup()
        assert p.parse("") is None
```

Both `test_basic` and `test_empty` are pytest-discoverable (they start with `test_`). The `_setup` helper is also emitted at module scope but is not collected by pytest (leading `_`).

---

## 4. Layer Assignment for Cross-Cutting Tests

**Rule:** Assign the test module's `layer` based on the **primary component under test**, as declared in the `tests` field.

| Scenario | Layer | Reason |
|----------|-------|--------|
| Tests a DOMAIN component | `DOMAIN` | Primary subject is domain logic |
| Tests an INFRASTRUCTURE adapter | `INFRASTRUCTURE` | Primary subject is infrastructure |
| Tests integration across layers | Use the **primary** subject's layer | e.g., testing a DOMAIN service that happens to use an INFRASTRUCTURE adapter — use `DOMAIN` |

**Example:** A test that exercises `self_model.SelfIntrospection` (DOMAIN) but uses `anthropic` (INFRASTRUCTURE) should be assigned `layer: DOMAIN` because the primary subject is the self-model.

---

## 5. Intra-Module Cell and Nerve Reference Rules

### 5.1 No `depends_on` Needed for Same-Module References

Components within the same module can reference each other directly without `depends_on` or `uses` declarations. The transpiler emits all components into the same Python file, so names are naturally in scope.

```
cell MyError :: DOMAIN
    kind: EXCEPTION
    visibility: PUBLIC
    intent: "Error raised when processing fails"
    schema: "message: str"
    ---
    class MyError(Exception):
        def __init__(self, message: str):
            self.message = message
            super().__init__(message)

nerve process :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Processes input, raising MyError on failure"
    expects: "Non-empty input string"
    guarantees: "Returns processed result or raises MyError"
    forbids: none
    raises: [MyError]
    ---
    def process(data: str) -> str:
        if not data:
            raise MyError("Empty input")
        return data.upper()
```

The `raises: [MyError]` generates a derived RAISES edge, but no `depends_on` or `uses` entry is needed because both `process` and `MyError` live in the same module. The emitted Python file has `MyError` defined before `process`, so the name resolves naturally.

### 5.2 When `depends_on` IS Needed

Use inline `depends_on` for intra-module dependencies that represent **deliberate architectural coupling** you want tracked in the IR — specifically for `CALLS`, `READS`, `CONSTRUCTS`, or `CONFIGURES` relationships to other nerves or cells within the module:

```
nerve orchestrate :: DOMAIN
    kind: ORCHESTRATOR
    visibility: PUBLIC
    intent: "Orchestrates the processing pipeline"
    depends_on:
        process: {relation: CALLS, carries: "raw input string", coupling: LOOSE}
    ---
    def orchestrate(data: str) -> str:
        return process(data)
```

**Summary:**
- **Same-module cell/nerve references in code:** No declaration needed
- **`raises` field entries:** Must be s0ma cells in the same module — no declaration needed
- **Explicit architectural dependencies:** Use `depends_on` when you want the edge in the IR
- **Cross-module references:** Use `uses` at the module level and `axon` for standalone edges

---

## 6. EXCEPTION Cell Patterns

EXCEPTION cells define custom exception types. They use `kind: EXCEPTION` and require a `class` body that inherits from `Exception` (or a subclass):

```
cell ValidationError :: DOMAIN
    kind: EXCEPTION
    visibility: PUBLIC
    intent: "Raised when input validation fails"
    schema: "field: str, message: str, code: str"
    ---
    class ValidationError(Exception):
        def __init__(self, field: str, message: str, code: str = "INVALID"):
            self.field = field
            self.message = message
            self.code = code
            super().__init__(f"{field}: {message}")
```

**Key points:**
- The `schema` field documents the exception's attributes (not enforced, but consumed by AI tools via the IR)
- EXCEPTION cells are emitted with `@component(kind=ComponentKind.MODEL, metadata={"kind_detail": "EXCEPTION", ...})`
- The `kind_detail` metadata distinguishes exceptions from other MODEL components in the registry
- Use `raises: [ValidationError]` in nerve declarations to declare which nerves can raise it — this generates a derived RAISES edge
- `raises` is **metadata only** — it does NOT generate an import. The exception cell must be in the same module or imported via `uses`

---

## 7. CONSTANT Cell Patterns

CONSTANT cells define module-level constants. They are simpler than other cells:

```
cell DEFAULT_TIMEOUT :: INFRASTRUCTURE
    kind: CONSTANT
    visibility: INTERNAL
    intent: "Default HTTP timeout in milliseconds"
    schema: "int"
    ---
    DEFAULT_TIMEOUT = 30000
```

**Key points:**
- Body is a bare assignment (not a class)
- **Cell name = Python identifier in the body. Use `UPPER_SNAKE_CASE` for both.** The transpiler emits `from <module> import <cell_name>`, so a mismatch produces a runtime `ImportError` (caught at `s0ma check` time as `CONSTANT_NAME_MISMATCH`).
- No `requires` needed for simple literal constants
- Emitted as the assignment + a `register_constant()` call (not `@component`)
- INTERNAL constants are not exported but are still registered for observability
- The `schema` field documents the constant's type

**Multiple constants in one module:**

```
cell API_VERSION :: INFRASTRUCTURE
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Current API version string"
    schema: "str"
    ---
    API_VERSION = "2.1.0"

cell MAX_RETRIES :: INFRASTRUCTURE
    kind: CONSTANT
    visibility: INTERNAL
    intent: "Maximum retry count for failed requests"
    schema: "int"
    ---
    MAX_RETRIES = 3
```

---

## 8. `raises` and `uses` Relationship

**`raises`** and **`uses`** serve different purposes and do NOT overlap:

| Field | Purpose | Generates import? | Generates edge? |
|-------|---------|-------------------|-----------------|
| `raises: [X]` | Declares which exception cells this nerve may raise | **No** | Yes — derived RAISES edge |
| `uses: [mod.X]` | Declares cross-module component dependencies | **Yes** | Yes — imported in transpiled Python |

**Common mistake:** Assuming `raises: [SomeError]` imports `SomeError`. It doesn't. If `SomeError` is in another module, you also need `uses: [errors.SomeError]` at the module level. If `SomeError` is in the same module, no additional declaration is needed.

**`raises` entries must be s0ma cells**, not Python built-in exceptions. To declare that a nerve raises `ValueError`, simply raise it in the body — no `raises` entry is needed for built-in exceptions.

---

## 9. Abstract Adapter Convention

Abstract nerves define interfaces that concrete nerves must implement. This is the adapter pattern for swappable implementations.

### 9.1 Declaring an Abstract Nerve

```
nerve StorageAdapter :: INFRASTRUCTURE
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Abstract interface for persistent storage backends"
    abstract: true
    interface: [save, load, delete]
    ---
```

**No body needed.** The transpiler generates `NotImplementedError` stubs:

```python
def StorageAdapter():
    def save(*args, **kwargs):
        raise NotImplementedError("save")

    def load(*args, **kwargs):
        raise NotImplementedError("load")

    def delete(*args, **kwargs):
        raise NotImplementedError("delete")
```

### 9.2 Implementing a Concrete Adapter

A concrete nerve in the same or another module implements the interface:

```
nerve FileStorageAdapter :: INFRASTRUCTURE
    kind: ADAPTER
    visibility: PUBLIC
    intent: "File-system implementation of the storage adapter"
    abstract: false
    interface: [save, load, delete]
    ---
    def FileStorageAdapter(base_path: str):
        def save(key: str, data: bytes) -> None:
            path = f"{base_path}/{key}"
            with open(path, "wb") as f:
                f.write(data)

        def load(key: str) -> bytes:
            path = f"{base_path}/{key}"
            with open(path, "rb") as f:
                return f.read()

        def delete(key: str) -> None:
            import os
            os.remove(f"{base_path}/{key}")

        return {
            "save": save,
            "load": load,
            "delete": delete,
        }
```

### 9.3 Cross-Module Abstract Validation

When using `--include` to build with cross-module context, the transpiler validates that concrete nerves implementing abstract interfaces define **all required methods**. Missing methods produce an error:

```
ERROR: FileStorageAdapter implements abstract interface StorageAdapter
       but is missing methods: [delete]
```

### 9.4 When to Use Abstract Nerves

- **Adapter pattern:** Multiple backends (file, S3, database) behind one interface
- **Plugin pattern:** Extensible functionality where implementations vary
- **Testing:** Mock implementations that satisfy the same interface

---

## 10. Bootstrap and Entry Point Patterns

### 10.1 When to Use Plain Python vs `.s0ma`

| Scenario | Use | Reason |
|----------|-----|--------|
| Application entry point (`main.py`, `__main__.py`) | **Plain Python** | Entry points bootstrap the framework; they can't be described by it |
| Framework initialization (`s0ma.initialize()`) | **Plain Python** | Must execute before any `.s0ma` code can be imported |
| CLI scripts | **Plain Python** (with `.s0ma` imports) | CLI parsing is infrastructure plumbing |
| Domain logic, services, adapters | **`.s0ma`** | Core application code benefits from structural self-description |
| Test files | **`.s0ma`** (preferred) or plain pytest | `.s0ma` tests register verification relationships in the self-model |
| Configuration files | **`.s0ma`** (cells) or plain Python | Use `.s0ma` when you want the config tracked in the registry |

### 10.2 Bootstrap Pattern

The bootstrap file initialises s0ma, then loads every transpiled module in topological order. As of 0.12.0 (M10), the order is recorded in `build.s0ma.json` — there is no longer any reason to hand-maintain a `MODULE_IMPORT_ORDER` list.

```python
# bootstrap/startup.py — plain Python, NOT a .s0ma file
from pathlib import Path
import s0ma
from s0ma.bootstrap import bootstrap_imports

def startup() -> dict:
    s0ma.initialize(project_root="./src")
    build_dir = Path(__file__).parent.parent.parent / "myproj_build"
    return bootstrap_imports(build_dir)
```

```python
# main.py — plain Python, NOT a .s0ma file
from my_app.bootstrap.startup import startup

modules = startup()  # idempotent sys.path insert + topological imports

def main():
    storage = modules["infrastructure"].create_storage("/data")
    result = modules["domain"].process_data(storage)
    print(result)

if __name__ == "__main__":
    main()
```

**Rule:** The bootstrap file initialises s0ma, then calls `bootstrap_imports(build_dir)`. It should NOT be a `.s0ma` file because it needs to exist before the s0ma import hook is active.

**Declare every bootstrap file under `[tool.s0ma].bootstrap_files`.** Every plain-Python file in the project (e.g., `main.py`, `bootstrap/startup.py`, framework-init shims) must be listed under `[tool.s0ma].bootstrap_files` in `pyproject.toml` so `s0ma verify` recognises them as status `BOOTSTRAP` (informational) rather than `UNKNOWN` (warning). The declaration is the canonical answer to "which `.py` files are intentional plain-Python exceptions"; without it, every bootstrap file generates noise on every `s0ma verify` run and erodes the value of the check. Example:

```toml
[tool.s0ma]
bootstrap_files = [
    "src/myproj/main.py",
    "src/myproj/bootstrap/startup.py",
]
```

`BOOTSTRAP` rows are hidden from the default `s0ma verify` output; pass `--verbose` (or `--format json`) to see them. The runtime bridge (`bootstrap_imports`, `import_modules_from_manifest`) does not register bootstrap files as components — the build manifest is the registration set, and bootstrap files are by construction outside it. Spec §4.13 carries the full contract, including the status legend.

**`bootstrap_imports(build_dir)` contract:**

- Lives in `s0ma.bootstrap` (s0ma-core, Apache-2.0) since 0.16.x, so a deployed app boots without the authoring packages installed. The old `s0ma_dsl.runtime` import still works and delegates here, with a `DeprecationWarning` naming the new path.
- Reads `build_dir/build.s0ma.json`. A missing or schema-mismatched manifest raises `ManifestSchemaError` with a remediation pointing at `s0ma build` — there is no silent fallback.
- Idempotently inserts `build_dir` at the head of `sys.path`. Re-invoking the helper does not duplicate the entry.
- Imports each module via `importlib.import_module` in the topological order recorded in the manifest's `topological_import_order` field (M10 build) or, when absent, the `modules` list's alphabetical order (pre-M10 build).
- Returns `dict[str, ModuleType]` keyed by canonical module name. Iteration order matches the import order.

**Sidebar — what it replaces.** Before M10, every consumer project carried a hand-maintained constant in `bootstrap/startup.py`:

```python
# Pre-M10 (do not write new code in this shape):
MODULE_IMPORT_ORDER = (
    "domain_constants",
    "domain_types",
    "application_services",
    "presentation_renderers",
    "http_gateway",
)

def startup() -> dict:
    sys.path.insert(0, str(BUILD_DIR))
    return {name: importlib.import_module(name) for name in MODULE_IMPORT_ORDER}
```

The list was append-only by convention — every new module went on the end, regardless of whether the actual `uses:` graph put it there. The IR already carried the topological truth; M10 surfaces it. New code uses `bootstrap_imports`.

For diagnostics or one-off scripts that need the order without going through the runtime helper, `s0ma topo <project_dir>` prints it one module per line.

### 10.3 Thin CLI shim → presentation nerve (`argparse.REMAINDER` and `--`)

When the bootstrap file is a thin CLI shim that hands the remaining arguments to a presentation nerve — the shape `s0ma new project --template cli` scaffolds — the canonical wiring uses `argparse.REMAINDER`:

```python
# bootstrap/cli.py — thin Python shim, not a .s0ma file
import argparse
from pathlib import Path

from s0ma.bootstrap import bootstrap_imports

parser = argparse.ArgumentParser(prog="cli")
parser.add_argument("subcommand")
parser.add_argument("rest", nargs=argparse.REMAINDER)
args = parser.parse_args()

modules = bootstrap_imports(Path(__file__).resolve().parent.parent / "build")
modules["console_presentation"].dispatch(args.subcommand, args.rest)
```

**`argparse.REMAINDER` swallows `--`.** Unlike `nargs="*"`, the `REMAINDER` action captures every remaining argument *including* a literal `--` separator — nothing strips it. If the downstream consumer (the presentation nerve, a wrapped `s0ma test`, a forwarded pytest invocation) expects `--` to have been consumed by the bootstrap layer, strip it explicitly before passing the rest on:

```python
rest = args.rest
if rest and rest[0] == "--":
    rest = rest[1:]
modules["console_presentation"].dispatch(args.subcommand, rest)
```

The downstream consumer's behaviour is the deciding factor: pytest, `s0ma test` and most CLI subcommands tolerate a leading `--` (it terminates option parsing); raw application code typically does not. When in doubt, strip it. The contributor-facing statement of the same contract is in the coding-agent handbook (its section 1.5).

### 10.4 Wiring the `self_inspect` tool, and keeping its answers small

A green build leaves `self_context.json` and `self_prompt_card.md` beside the manifest, and the operation channel is a few lines of plain Python in the bootstrap file. The full treatment, with the trust block the host prompt carries and the measurements behind these rules, is s0ma://guide/self-prompting; this section is the wiring and the economy.

```python
# bootstrap/startup.py: plain Python, not a .s0ma file
import json
from pathlib import Path

from s0ma.runtime import self_context, self_inspect_adapter

build_dir = Path(__file__).resolve().parent.parent / "build"
context = self_context(build_dir)          # verified; context["card"] is the bounded card
adapter = self_inspect_adapter(build_dir)  # pass registry=... only after registration


def self_inspect(query: str) -> str:
    return json.dumps(adapter.handle(query), separators=(",", ":"), sort_keys=True)


agent_host.register_tool(adapter.tool_spec, self_inspect)
```

The companions describe the application's `source` modules; the test modules `s0ma test` builds into the same manifest are left out, and `provenance.roles` records that. The adapter answers five commands, `describe`, `components <layer or module>`, `component <name>`, `dependencies <name>` and `source_ir`, named once in `tool_spec`, and returns a `dict` for each; a registry supplied after registration reaches `describe` as live-health counts and `component <name>` as an `observed` flag. The host's rendering is what the model pays for, on every call, for as long as the answer stays in context. Six rules, with fr3d's build (103 source modules, 441 source components) as the evidence where a number is given:

- **Compact JSON with sorted keys.** `separators=(",", ":"), sort_keys=True`, as above. Indentation cost fr3d about a third of every answer, and sorted keys make equal answers equal bytes, which a prompt cache rewards.
- **Counts first, names second, authored text only on request.** `describe` is counts and module names: 2,264 characters on fr3d, down from 130,808 when it listed every component id and IR record, tests included. `components` is names. Only `component <name>` carries authored text, as quoted project data.
- **Never repeat the tool's description in an answer.** The model already holds the tool list, and `tool_spec` is where the commands are taught.
- **Every authored line is paid for on every answer that carries it.** One sentence added to an intent grew fr3d's full capabilities answer by 235 characters. Intents and contracts are product copy: write them once and keep them short.
- **Budget each default answer and test the budget against a real build.** The adapter's own `describe` is held under 8,000 characters by the adapter itself, which trades module names for module counts past that line, and by two tests: one on 3,000 synthetic components over 200 modules, one on the s0ma-mcp package's own build.
- **Estimate a result by its words or a quarter of its characters, whichever is larger.** A word count reads space-free JSON as one token.

---

## 11. `nerve` vs `ganglion` Decision Tree

| Question | Answer | Declaration |
|----------|--------|-------------|
| Does it **do** something (transform, compute, serve)? | Yes | `nerve` |
| Does it **observe** other components and react? | Yes | `ganglion` |
| Does it orchestrate other nerves? | Yes | `nerve` with `kind: ORCHESTRATOR` |
| Does it evaluate/monitor system behavior? | Yes | `ganglion` |
| Does it have `observes` patterns? | Yes | `ganglion` (only ganglia have `observes`) |
| Does it have `expects`/`guarantees` contracts? | Yes | `nerve` (ganglia don't have these; both write `forbids`) |
| Is it a passive watcher with `priors` and `on_anomaly`? | Yes | `ganglion` |

**Key distinction:** Nerves are **actors** (they do work when called). Ganglia are **observers** (they watch nerves and react to anomalies). If your component is called explicitly by other code, it's a nerve. If it monitors other components and triggers responses, it's a ganglion.

**Orchestrator vs Ganglion:** An orchestrator nerve coordinates a workflow by calling other nerves in sequence. A ganglion passively observes execution patterns and reacts. The orchestrator controls; the ganglion watches.

## 12. Test-only helpers: `visibility: TEST`

Some helpers are genuinely private implementation detail of one or two `PUBLIC` nerves — production callers never need to touch them — yet tests need to exercise them directly to cover edge cases the public surface doesn't expose. The classic shape is a string-rendering primitive: an HTML escaper, a prompt formatter, a serialisation rule. Pre-`TEST`, two workarounds existed; both are wrong.

**The wrong-way-1 workaround: copy-paste into the test module.**

```
# In production: src/text/render.s0ma
nerve _escape_text :: APPLICATION
    visibility: INTERNAL
    ...
    ---
    def _escape_text(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# In tests: tests/test_render.s0ma — no way to import the INTERNAL helper, so:
test test_escape_handles_ampersand :: APPLICATION
    intent: "..."
    tests: [render]
    ---
    def _escape_text(s: str) -> str:  # COPY-PASTED. Drift risk.
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def test_escape_handles_ampersand():
        assert _escape_text("a & b") == "a &amp; b"
```

The two copies drift the moment one changes. The test passes against a stale rendering rule.

**The wrong-way-2 workaround: promote to PUBLIC.**

```
nerve escape_text :: APPLICATION
    visibility: PUBLIC  # Promoted purely so tests can reach it.
    ...

# Module header:
exports: [render_html, escape_text]  # escape_text now in the public API
```

Now `escape_text` is in the IDE auto-complete for every consumer; the API documentation grows by one entry that is structurally a private detail; release-mode `MISSING_PUBLIC_DOC_REF` requires `doc-ref` coverage for it.

**The right-way pattern: `visibility: TEST`.**

```
# Production: src/text/text_helpers.s0ma
module text_helpers
    layer: APPLICATION
    version: 1.0.0
    intent: "Text-rendering primitives."
    exports: [render_html]   # NOTE: escape_text is NOT exported.

nerve escape_text :: APPLICATION
    kind: FUNCTION
    visibility: TEST          # Reachable from test consumers; hidden from production cross-module callers.
    intent: "Escape &, <, > for safe HTML rendering."
    expects: "A string of arbitrary text."
    guarantees: "Returns the input with &, <, > replaced by their HTML entity references."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def escape_text(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

nerve render_html :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Render an HTML span with text properly escaped."
    expects: "A non-empty string."
    guarantees: "Returns a span element with the text HTML-escaped."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def render_html(text: str) -> str:
        escaped = escape_text(text)         # intra-module: TEST is fully callable.
        return "<span>" + escaped + "</span>"
```

The test module reaches the helper directly:

```
# Tests: tests/text_helpers_tests.s0ma
module text_helpers_tests
    layer: APPLICATION
    version: 1.0.0
    intent: "Tests for text_helpers."
    uses: [text_helpers.escape_text, text_helpers.render_html]   # TEST visibility OK — this module declares ≥1 test.
    exports: []

test test_escape_handles_special_characters :: APPLICATION
    intent: "Verifies escape_text replaces &, <, >."
    tests: [text_helpers.escape_text]
    ---
    def test_escape_handles_special_characters():
        assert escape_text("a & b") == "a &amp; b"
        assert escape_text("<x>") == "&lt;x&gt;"
```

A production consumer cannot.

```
# WRONG: this module declares zero `test` declarations.
module production_consumer
    ...
    uses: [text_helpers.escape_text]   # ❌ TEST_VISIBILITY_VIOLATION (error in every mode)
```

The remediation is one of:

- Add a `test` declaration to the consuming module (now it qualifies as a test consumer).
- Change the target's visibility to `PUBLIC` and add it to its module's exports (now it is genuinely public surface).

**When to choose `TEST` vs `INTERNAL` vs `PUBLIC`:**

| Question | Choose |
|---|---|
| Production callers in *other modules* call this? | `PUBLIC` (and add to `exports:`) |
| Only callers in the *same module* call this; tests cover it via the public surface? | `INTERNAL` |
| Only callers in the *same module* call this; tests need to exercise it directly? | `TEST` |

`TEST` is exempt from `NOT_EXPORTED` (it doesn't appear in `exports:` by design) and from `MISSING_PUBLIC_DOC_REF` (it isn't part of the documented public surface). The intra-module `VISIBILITY_MISMATCH` rule is unchanged: a `TEST` component listed in `exports:` is still wrong (you'd be mixing the public and test surfaces). See spec §5 and ADR-008.

## 13. Layer Discipline (cross-module `uses:`)

Every `.s0ma` module declares exactly one architectural `layer:`. The intra-module rule (§4.0.1) is "every component shares the module's layer." The cross-module rule (§4.0.2) is "a module's `uses:` entries cannot reach a higher layer than the consuming module."

The authoritative reachability matrix:

| Source layer (`uses:` written here) | Target layer must be one of |
|---|---|
| `DOMAIN` | `DOMAIN`, `FRAMEWORK` |
| `APPLICATION` | `DOMAIN`, `APPLICATION`, `FRAMEWORK` |
| `PRESENTATION` | `DOMAIN`, `APPLICATION`, `PRESENTATION`, `FRAMEWORK` |
| `INFRASTRUCTURE` | `DOMAIN`, `APPLICATION`, `INFRASTRUCTURE`, `FRAMEWORK` |
| `FRAMEWORK` | `FRAMEWORK` |

Reading the rows: domain models cannot reach up into application services or presentation/infrastructure adapters; application services consume domain plus framework; presentation and infrastructure are sibling boundary layers that consume domain and application but not each other; framework is the floor and sees only itself.

**Violation code.** A `uses:` edge that crosses the matrix produces `CROSS_LAYER_DEPENDENCY`. Severity ladders with strictness mode: warning in migration/dev (so authors see violations as they develop), error in strict and release (so the violations cannot ship). Test modules' `uses:` entries are checked at the layer the test declares — a DOMAIN-layer test importing PRESENTATION is the same architectural smell as a DOMAIN production module doing it.

When the rule fires, two structural fixes apply.

### 13.1 Fix by moving the shared concept down

Symptom: a DOMAIN module needs a constant or type that currently lives in an APPLICATION module.

```
# Wrong — DOMAIN reaches up into APPLICATION.
module order_model
    layer: DOMAIN
    uses: [order_service.MAX_LINE_ITEMS]   # ❌ CROSS_LAYER_DEPENDENCY
    exports: [Order]
```

The shared concept (`MAX_LINE_ITEMS`) is a domain-level invariant: every consumer of `Order` cares about it. Move it down into a DOMAIN module both can reach:

```
# Right — the constant lives at the lowest layer that all consumers can reach.
module order_constants
    layer: DOMAIN
    exports: [MAX_LINE_ITEMS]

cell MAX_LINE_ITEMS :: DOMAIN
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Maximum number of line items per order — domain invariant."
    schema: |
        value: int
    ---
    MAX_LINE_ITEMS = 50

module order_model
    layer: DOMAIN
    uses: [order_constants.MAX_LINE_ITEMS]   # ✓ DOMAIN → DOMAIN
    exports: [Order]

module order_service
    layer: APPLICATION
    uses: [order_constants.MAX_LINE_ITEMS, order_model.Order]   # ✓ APPLICATION → DOMAIN
    exports: [process_order]
```

Both modules now reach `MAX_LINE_ITEMS` cleanly, and the matrix is satisfied.

### 13.2 Fix by inverting the dependency

Symptom: a DOMAIN nerve needs to call an APPLICATION service to do its job. This is usually a sign that the dependency is *wrong-way-round* — the domain shouldn't depend on application logic; application logic should orchestrate the domain.

```
# Wrong — DOMAIN reaches up into APPLICATION.
module order_model
    layer: DOMAIN
    uses: [order_service.process_order]   # ❌ CROSS_LAYER_DEPENDENCY
    exports: [Order]

cell Order :: DOMAIN
    ...
    ---
    class Order:
        def __init__(self, id):
            self.id = id

        def submit(self) -> str:
            return process_order(self.id)
```

Invert the dependency: make `process_order` the consumer and have it call into `Order`:

```
# Right — the lower layer publishes data; the higher layer drives the workflow.
module order_model
    layer: DOMAIN
    exports: [Order]

cell Order :: DOMAIN
    ...
    ---
    class Order:
        def __init__(self, id):
            self.id = id

module order_service
    layer: APPLICATION
    uses: [order_model.Order]   # ✓ APPLICATION → DOMAIN
    exports: [process_order]

nerve process_order :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    ...
    ---
    def process_order(order: Order) -> str:
        if not order.id:
            return "rejected"
        return "queued"
```

If the domain genuinely needs to invoke a higher-layer policy (rare, but not unheard of), introduce an abstract port in the domain layer that the higher layer implements. The dependency edge then runs `APPLICATION → DOMAIN_port` and the domain stays sealed.

```
# Domain publishes a port (abstract interface in DOMAIN layer).
module order_model
    layer: DOMAIN
    exports: [Order, OrderProcessor]

nerve OrderProcessor :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    abstract: true
    interface: [process]
    ...

cell Order :: DOMAIN
    ...
    ---
    class Order:
        def __init__(self, id, processor: OrderProcessor):
            self.id = id
            self._processor = processor

        def submit(self) -> str:
            return self._processor.process(self)

# Application implements the port.
module order_service
    layer: APPLICATION
    uses: [order_model.Order, order_model.OrderProcessor]   # ✓ APPLICATION → DOMAIN
    exports: [DefaultOrderProcessor]

nerve DefaultOrderProcessor :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    depends_on:
        OrderProcessor: {relation: CONSTRUCTS, carries: "abstract port", coupling: TIGHT}
    ...
```

The domain stays self-contained; the application layer wires concrete behaviour in. See §9 (Abstract Adapter Convention) for the full pattern.

**When you cannot fix it locally**, that's a signal the layering itself is wrong — re-evaluate which layer each module belongs to. The matrix is not negotiable per-project; if a real consumer needs to bend it, the redesign is the right answer.

---

## 14. Large Embedded Content (`@file()` directive)

When a `CONSTANT` cell's value is a large block of text — HTML, SQL, prompt templates, JSON schemas — *do not* inline it as a triple-quoted Python string. The wrong-abstraction smell is overwhelming: the author loses editor highlighting and linting for the embedded language, the cell's metadata gets buried under hundreds of lines of unrelated syntax, and the `.s0ma` file's metadata-to-content ratio collapses.

**The canonical motivating case.** The kn0wthyself viz plugin had a `viz_template.s0ma` file that grew to 1010+ lines, of which ~990 were embedded HTML/CSS/JS in a triple-quoted Python string. The metadata-to-content ratio was 1:80. Authors lost HTML/CSS/JS editor support; reviewers had to scroll through hundreds of lines of raw markup to find the cell's intent and schema. That experience is what M12 fixes.

**The pattern.** Replace the inline `--- ... ---` body with a `content: @file("path")` field. The transpiler reads the file at build time, hashes it for cache invalidation, and emits the content into the generated Python verbatim:

```
cell VIZ_TEMPLATE :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Self-contained HTML5 visualization template with embedded D3 force graph."
    schema: "string of valid HTML5 with inline CSS and JS"
    content: @file("templates/viz.html")
```

```html
<!-- templates/viz.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>s0ma component graph</title>
    <style>
        body { font-family: system-ui; }
        .node { stroke: #fff; stroke-width: 1.5px; }
    </style>
</head>
<body>
    <svg id="graph" width="900" height="600"></svg>
    <script>
        const greeting = "Hello, s0ma";
        // ... full HTML/CSS/JS in its native syntax with editor support ...
    </script>
</body>
</html>
```

**Where the content goes.** The transpiler binds `VIZ_TEMPLATE` in the generated module to the file's exact UTF-8 bytes via `r"""..."""` (or `repr()` when the content contains the triple-quote sequence). Consumers `from <package> import VIZ_TEMPLATE` and use it identically to an inline-defined constant — the embed is a transpile-time mechanism, not a runtime one.

**Build artifacts.** The `build.s0ma.json` manifest's `external_content_files` map records the embed under `"<module>::<cell>"` with the path the author wrote and the SHA-256 hash of the file's content. Editing the embedded file changes its hash, invalidates the consuming module's cache, and triggers a re-transpile on the next build — the `.py` is never stale relative to its inputs.

**Source maps.** The `.s0ma.map` records the embedded file as the canonical body source for the cell. Debuggers and error reporters follow this redirect so a runtime error in the embedded literal points at the original `.html` / `.sql` / `.txt` rather than the `.s0ma` line that holds the directive.

**Validation.** A missing or unreadable embedded file produces `EMBEDDED_FILE_NOT_FOUND` at error severity in every strictness mode. The combination of inline body and `@file()` on the same cell is a `PARSE_ERROR` — pick one form. The directive is restricted to `kind: CONSTANT` in v0.12.0; future versions may extend it to other kinds if real consumers need them.

**When to use it.**
- ✓ HTML / CSS / JS templates served by a web SERVICE.
- ✓ SQL DDL or query templates consumed by an ADAPTER.
- ✓ LLM prompt templates — long, structured prose that benefits from a Markdown-aware editor.
- ✓ JSON schemas, OpenAPI specs, or any externally-authored contract.
- ✗ Short literals (an int, a single-line string, a tuple) — keep these inline.
- ✗ Anything generated by code at build time — the `@file()` directive is for hand-authored content with native editor support.

## 15. Helpers vs nerves — module-private functions

> Added in v0.12.0 (feedback 5–6, plan M13).

The `helper` declaration kind exists for one reason: to give module-private functions a first-class home. Before v0.12.0 the only options for a small formatting / parsing / building helper were (a) nest it inside a single nerve body (which produced ~160-line bodies in real consumer projects — feedback-5 MS 1) or (b) promote it to a `nerve` and register it as a component (semantically wrong — it's plumbing, not API). M13 introduces `helper` as the third path.

Use this decision tree when you find yourself writing a small `def` that doesn't quite fit a `nerve`:

### 15.1 Small inline helper inside a single nerve — stays inline

If the helper is used by exactly one nerve and is small (say, fewer than 20 lines), nest it inside that nerve's body. No declaration needed. The nerve owns it; the body validator accepts inner functions.

```
nerve render_event :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Render a calendar event as a single-line summary."
    expects: "A dict with 'summary' and 'attendees' keys."
    guarantees: "Returns a single-line string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def render_event(event: dict) -> str:
        def fmt_attendee(a: dict) -> str:
            return a["name"] + " <" + a["email"] + ">"
        attendees = ", ".join(fmt_attendee(a) for a in event["attendees"])
        return event["summary"] + " — " + attendees
```

### 15.2 Helper used by 2+ nerves in the same module — extract to `helper`

When the same small function would otherwise be duplicated across nerves in the same module, extract it to a `helper` declaration. The helper lives at module scope, is in scope for every other declaration in the module, and is emitted as a plain `def` (no `@component`, no `register_*()`). It does not appear in `__all__`.

```
helper _fmt_attendee :: APPLICATION
    intent: "Format a single attendee dict into a 'Name <email>' string."
    ---
    def _fmt_attendee(a: dict) -> str:
        return a["name"] + " <" + a["email"] + ">"

nerve render_event :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Render a calendar event as a single-line summary."
    expects: "A dict with summary and attendees keys."
    guarantees: "Returns a single-line summary string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def render_event(event: dict) -> str:
        attendees = ", ".join(_fmt_attendee(a) for a in event["attendees"])
        return event["summary"] + " — " + attendees

nerve render_invite :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Render an invite line for a single attendee."
    expects: "An attendee dict."
    guarantees: "Returns a 'Name <email>' string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def render_invite(attendee: dict) -> str:
        return "Invite: " + _fmt_attendee(attendee)
```

By convention, helper names start with an underscore. The parser doesn't enforce it, but the convention makes the intra-module / cross-module asymmetry visually obvious in body code.

### 15.3 Helper that's also useful for tests — extract to `helper`, accessible via test `uses:`

When the same helper is also useful for verifying behaviour from a sibling test module, extract it to a `helper` and add it to the test module's `uses:` list. Test modules (any module that contains ≥1 `test` declaration) may reach a helper across module boundaries; production modules cannot.

This is the canonical fix for the recorder-class duplication that recurred across feedback-6 MS 13/16 (D-36): pull the recorder builder into a single `helper`, then have every relevant test module `uses:` it.

```
# src/sample/event_builder.s0ma
helper _build_recorder :: APPLICATION
    intent: "Build a list-backed call recorder for verifying side effects in tests."
    ---
    def _build_recorder() -> dict:
        calls = []
        return {"record": calls.append, "calls": calls}
```

```
# tests/event_builder_tests.s0ma
module event_builder_tests
    layer: APPLICATION
    version: 1.0.0
    intent: "Tests for event_builder."
    uses: [event_builder._build_recorder, event_builder.publish_event]
    exports: []

test test_publish_records_one_call :: APPLICATION
    intent: "Verify publish_event invokes the side-effect channel exactly once."
    tests: [event_builder.publish_event]
    ---
    def test_publish_records_one_call():
        recorder = _build_recorder()
        publish_event({"summary": "x"}, sink=recorder["record"])
        assert len(recorder["calls"]) == 1
```

If a *production* module tries the same import — adding `event_builder._build_recorder` to its `uses:` without carrying a `test` declaration of its own — the resolver raises `HELPER_PRIVATE_TO_MODULE`. The remediation is one of: (a) promote the helper to a `nerve` if it really is part of the API, (b) add a `test` declaration to the consumer if it's test-only, or (c) inline the helper's behaviour in the consumer.

### 15.4 What helpers are NOT

- Helpers are **not** registered components. They do not appear in `IRDocument.components`, do not get a `@component` decorator, and do not produce a `register_*()` call. They do appear in `IRDocument.helpers` (a separate top-level array) and in `s0ma inspect` under a `[helpers]` section.
- Helpers do **not** carry `kind`, `visibility`, `expects`, `guarantees`, `forbids`, `provides`, `returns`, `raises`, `evaluates_at`, `latency_ms`, or `depends_on`. The parser rejects those fields on a `helper`. If you need any of those, you want a `nerve`.
- Helpers do **not** appear in the module's public surface. They are excluded from `__all__` and from the `exports` list.

### 15.5 Real logic in modules — the multi-function pattern, not the factory-dict trap

> Added in v0.11.0 (batch-01a D3).

A nerve body is exactly one `def` (§ the body rules; a `class` or multiple top-level statements is a `PARSE_ERROR`). Reaching for "I need several functions in this module", agents in benchmark batch-01a invented a workaround that detonates at runtime. Name it so you can avoid it: **the factory-dict module trap.**

**The anti-pattern.** Cram every operation into one nerve that returns a dict, then consume it from another module with a *bare* `uses:` entry and subscript the imported name:

```
# src/registry.s0ma — many operations stuffed into one returned dict
module registry
    layer: DOMAIN
    version: 0.1.0
    intent: "Operation registry."
    exports: [make_registry]

nerve make_registry :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "Build the operation registry."
    expects: "nothing"
    guarantees: "a dict of operations"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def make_registry():
        def get_op(name): ...
        def set_op(name, fn): ...
        return {"get_op": get_op, "set_op": set_op}

# src/cli.s0ma — the consumer that detonates
module cli
    layer: PRESENTATION
    version: 0.1.0
    intent: "CLI entry."
    uses: [registry]          # ❌ bare entry — binds the MODULE OBJECT
    exports: [run]

nerve run :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Run an operation."
    expects: "an op name"
    guarantees: "the op result"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def run(name):
        return registry["get_op"](name)   # ❌ MODULE_SUBSCRIPT
```

A bare `uses: [registry]` emits `import registry`, so inside the body `registry` is the **module object**, not the dict `make_registry()` returns. Bodies are emitted verbatim, so `registry["get_op"]` compiles cleanly and then blows up at runtime. `s0ma check` now stops it at author time (`MODULE_SUBSCRIPT`, error in every mode):

```
'run' subscripts 'registry', but 'registry' is a bare `uses: [registry]`
module object, not a dict — `registry[...]` raises `TypeError: 'module'
object is not subscriptable` at runtime.
```

with the remediation: *import the symbol itself — `uses: [registry.<symbol>]` emits `from registry import <symbol>` — then call it; for a shared factory, declare a module-level `helper`, list it under `exports_helpers:`, and consume it via `uses: [registry.<helper>]`.* This is the run that took bench `P1_P_r02` to 1/24 acceptance — an author-written subscript, not a codegen bug.

**The three real mechanisms.** s0ma already has first-class homes for "several functions"; pick by what the operations *are*.

1. **A `SERVICE` nerve with `provides:` — a factory that returns a dict, consumed correctly.** The factory/dict shape is *right* when the caller subscripts the value the factory **returns**, not a module object. Declare the operations up front (§2.1.1) and call the factory before subscripting:

   ```
   # src/ops.s0ma — producer: one SERVICE nerve, operations in provides:
   module ops
       layer: DOMAIN
       version: 0.1.0
       intent: "Operation registry."
       exports: [op_registry]

   nerve op_registry :: DOMAIN
       kind: SERVICE
       visibility: PUBLIC
       intent: "Operation registry."
       expects: "nothing"
       guarantees: "a dict of operations"
       forbids: none
       evaluates_at: FUNCTION_BOUNDARY
       provides:
         - get_op:
             returns: "the callable registered under a name"
         - set_op:
             returns: "None; registers a callable under a name"
       ---
       def op_registry():
           def get_op(name): ...
           def set_op(name, fn): ...
           return {"get_op": get_op, "set_op": set_op}

   # src/cli.s0ma — consumer: DOTTED uses:, then call the factory and
   # subscript its RETURN value
   module cli
       layer: PRESENTATION
       version: 0.1.0
       intent: "CLI entry."
       uses: [ops.op_registry]   # ✓ from-imports the nerve (a component)
       exports: [run]

   nerve run :: PRESENTATION
       ...
       ---
       def run(name):
           registry = op_registry()          # ✓ call the factory
           return registry["get_op"](name)   # ✓ subscript the RETURNED dict
   ```

   `kind: SERVICE` in `s0ma new module` / `scaffold_module` now scaffolds exactly this skeleton (a `provides:` block plus a factory returning a matching dict) so the correct shape is the starting point.

2. **Independent operations → one exported nerve each, imported with a dotted `uses:`.** When the operations don't share state, they are just several PUBLIC nerves. A dotted `uses: [module.symbol]` emits `from module import symbol` — a *component*, never the module object — so there is nothing to subscript:

   ```
   # src/registry.s0ma
   module registry
       layer: DOMAIN
       version: 0.1.0
       intent: "Operation registry."
       exports: [get_op, set_op]

   nerve get_op :: DOMAIN
       ...
   nerve set_op :: DOMAIN
       ...

   # src/cli.s0ma
   module cli
       layer: PRESENTATION
       version: 0.1.0
       intent: "CLI entry."
       uses: [registry.get_op, registry.set_op]   # ✓ from-imports the nerves
       exports: [run]

   nerve run :: PRESENTATION
       ...
       ---
       def run(name):
           return get_op(name)   # ✓ a plain call, no subscript
   ```

3. **Module-private plumbing shared with tests → `helper` + `exports_helpers:`.** For small `def`s that are implementation detail (formatters, builders) rather than API, extract a module-level `helper` (§15.2). A helper is reachable across modules **only from a test-context consumer** (a module with ≥1 `test`; §15.3) — a production module consuming another module's helper is `HELPER_PRIVATE_TO_MODULE` **even when the helper is listed in `exports_helpers:`**. `exports_helpers:` widens *reachability* (and is validated: a typo is `EXPORTED_HELPER_NOT_FOUND`), not the test-only access rule. So: production API that another production module calls is a `nerve` (mechanism 1 or 2); a helper is for internals your own module and its tests share.

**The rule of thumb.** If another *production* module needs to call it, it is a `nerve` — export it and import it dotted. A returned-dict factory is fine when the *caller* subscripts the *return value*; it is a trap when a *consumer* subscripts an imported *module*. Never write `module_name["key"]`.

## 16. Structural Attribute Budgets (M18)

`declares_attributes:` on a nerve carries a list of `<namespace>:<attribute>` strings — structural claims the nerve makes about its output. Project-level budgets under `[tool.s0ma.attribute_budgets]` enforce uniqueness at `s0ma check` / `s0ma build` time. The mechanism is **domain-agnostic**: it does not bake any HTML, HTTP, or CSS knowledge into the validator. Each project picks the namespaces and budget shapes it cares about.

Three budget shapes are supported:

- `exactly_one_per_page` — exactly one nerve in each page composer's reachable nerve set must declare a given `<namespace>:<attribute>`. Zero or more-than-one fires the violation. **F3 (feedback 5–6 follow-up):** a "page" is the module owning a nerve marked `is_page_composer: true`; the reachable set walks the transitive closure of `module.uses` from that module. The shape requires at least one nerve in the project to be marked, otherwise `NO_PAGE_COMPOSER_DECLARED` fires (error in every mode). F3 replaced M18's heuristic ("top-level module in the `uses:` graph") with explicit declaration to close documented edge cases (test modules looking like pages, projects with no `uses:` edges, fully-circular graphs).
- `unique_in_project` — at most one occurrence of each `<namespace>:<attribute>` string project-wide. Independent of the `uses:` graph.
- `warn_on_duplicate` — same shape as `unique_in_project` but warning-severity in every mode.

Without an `[tool.s0ma.attribute_budgets]` table, `declares_attributes:` is purely descriptive — it appears in the IR JSON and `s0ma inspect`'s text output, but nothing fires.

### 16.1 HTML Landmarks

The original feedback-5.5 motivation: HTML accessibility requires exactly one `<header>`, `<main>`, `<footer>`, and `<nav>` per page. A two-`<nav>` regression that only surfaced at runtime is exactly the kind of structural drift M18 catches at build time.

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

`compose_page` carries `is_page_composer: true` and `uses:` every landmark renderer (omitted for brevity); the validator walks the `uses:` graph from `compose_page`'s module and counts `landmark:header` occurrences in the reachable set. A second nerve declaring `landmark:header` reachable from the same composer trips `ATTRIBUTE_BUDGET_VIOLATION`. If no nerve carries `is_page_composer: true` while the budget is configured, `NO_PAGE_COMPOSER_DECLARED` fires (error in every mode) — the explicit marker is required.

### 16.1.1 Explicit page composers (F3)

F3 (feedback 5–6 follow-up) replaced M18's heuristic page-composer detection with explicit declaration. A page is whatever the project author marks as one — most often the top-level composer that calls every landmark renderer, but the shape generalises to any topology where the validator needs an explicit scope root.

**HTTP analogue (the same pattern, different namespace).** A multi-tenant HTTP router that wants "exactly one health endpoint per tenant" can mark each tenant's app composer as `is_page_composer: true` and configure `health = "exactly_one_per_page"`:

```toml
[tool.s0ma.attribute_budgets]
health = "exactly_one_per_page"
```

```
nerve tenant_a_app :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Tenant A's app entry point."
    expects: "An ASGI scope."
    guarantees: "Returns the routed response."
    forbids: none
    evaluates_at: SUBSYSTEM
    is_page_composer: true
    ---
    def tenant_a_app(scope): ...
```

Each tenant's app composer is a distinct "page"; the budget enforces one health endpoint per tenant rather than one project-wide.

**When to mark.** Mark a nerve `is_page_composer: true` when (a) the project has an `exactly_one_per_page` budget and (b) the nerve is the top of a render / dispatch / orchestration tree the budget should be scoped against. Do **not** mark a nerve just because it is at the top of a `uses:` chain — the marker is intent, not topology. Test harnesses, debugging entry points, and one-off scripts at the top of a `uses:` chain are not pages.

### 16.2 HTTP Routes

Route IDs must be unique across the entire HTTP project. `unique_in_project` is the right shape — the budget is independent of the `uses:` graph because two unrelated modules registering `GET /self` is still a conflict at the runtime router.

```toml
[tool.s0ma.attribute_budgets]
route = "unique_in_project"
```

```
nerve handle_self :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Handle GET /self for the API."
    expects: "No arguments."
    guarantees: "Returns a JSON response."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["route:GET /self"]
    ---
    def handle_self() -> str:
        return "{\"ok\": true}"
```

The double-quoted form (`"route:GET /self"`) is required when the attribute contains spaces, slashes, or commas.

### 16.3 CSS Class Names (Warning Shape)

A CSS-heavy project may want duplicates flagged but not blocked — `warn_on_duplicate` keeps the field useful as an inventory without making the build fail when two components legitimately share a utility class.

```toml
[tool.s0ma.attribute_budgets]
css_class = "warn_on_duplicate"
```

```
nerve render_button :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Render a primary action button."
    expects: "A label string."
    guarantees: "Returns a <button class='btn-primary'>...</button> string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: [css_class:btn-primary]
    ---
    def render_button(label: str) -> str:
        return "<button class='btn-primary'>" + label + "</button>"
```

### 16.4 Picking the Right Shape

- Use `exactly_one_per_page` when the constraint is "this attribute must appear in every page that reaches it, exactly once" — landmarks, primary navigation regions, the page title element.
- Use `unique_in_project` when the attribute is a global identifier — HTTP routes, RPC method names, public IDs, OpenAPI operationIds. Two declarations anywhere in the project is a conflict.
- Use `warn_on_duplicate` when the attribute is a *signal* — a CSS class, a feature flag name, a metric label — and the project wants a heads-up without blocking the build.

### 16.5 The mechanism is open-ended

Nothing in the validator knows about HTML, HTTP, or CSS. The namespaces (`landmark`, `route`, `css_class`) are author-chosen identifiers; the validator only checks the budget shape. Add new namespaces freely as the project grows — `feature_flag`, `metric`, `event_name`, `rpc:projects.list`, anything that needs to be unique at the project or page boundary.

## 17. Documentation subsystem (`doc-ref`, `doc-guide`, `example`)

The full reference for the documentation subsystem lives in [`docs/references/documentation_subsystem.md`](documentation_subsystem.md). One pattern worth surfacing here for parity with the rest of this guide:

### 17.1 `doc-ref` source-registry form (G7a)

Most `doc-ref` declarations point at project entities — "every PUBLIC nerve", "every cell whose `kind:` is in `[MODEL, CONSTANT]`", and so on. As of 0.12 (G7a), `covers:` accepts a second shape that pulls from a derived non-component registry instead. Today the only registered source is `error_codes`, and it's the canonical recipe for any project that wants the s0ma-dsl error catalogue rendered from the registry rather than hand-maintained:

```
doc-ref ErrorCodesTable
    intent: "Generated table of every registered s0ma-dsl error code."
    format: markdown
    output: docs/error_codes.md
    covers: { source: error_codes }
    sections: []
```

The renderer reads `SEVERITY_MATRIX | OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE` from `s0ma_dsl.config`, looks up each code's description in `ERROR_CODE_DESCRIPTIONS`, and emits a Markdown table with one row per code. `sections:` is unused in this form (the renderer emits one self-contained table). Mixing `kind:` and `source:` in the dictionary fires `PARSE_ERROR` — the discriminator is exclusive.

The pattern generalises: when a project wants documentation derived from a registry the framework owns (rather than from author-declared components), the source-registry form keeps the doc-ref declaration small and points at the registry as the single source of truth. New sources can be added with a renderer branch + a description registry.

---

## 18. Decision-1: the abstract-down-to-DOMAIN remediation for `CROSS_LAYER_DEPENDENCY`

The canonical fix for `CROSS_LAYER_DEPENDENCY` when the consumer is in a higher layer (typically `APPLICATION`) and the legitimate concrete lives in a sibling boundary layer (typically `INFRASTRUCTURE`) is to split the dependency in two: an abstract interface in `DOMAIN` and a concrete implementation in `INFRASTRUCTURE`. §13.2 covers the underlying inversion principle; this section is the load-bearing recipe — three working instantiations from real production code — that converts the principle into authored grammar agents can copy.

The pattern's name in fr3d's spec-feedback record is **"Decision-1"**: the structural-fix call you make when the matrix fires. It is structurally a special case of §13.2 (invert the dependency via an abstract port), but the recipe matters enough on its own that the patterns guide carries it as a separate section — agents converge on this shape independently across LLM adapters, message gateways, event stores, and other I/O-side abstractions.

### 18.1 The shape

Three modules, in three layers:

```
# domain/llm_adapter.s0ma — the abstract port, layer DOMAIN
module llm_adapter
    layer: DOMAIN
    version: 1.0.0
    intent: "Abstract LLM adapter port — concrete implementations live in INFRASTRUCTURE."
    exports: [LLMAdapter]

nerve LLMAdapter :: DOMAIN
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Abstract chat adapter — concrete backends implement chat / chat_stream."
    expects: "Concrete subclass implements every method in interface."
    guarantees: "Calls dispatch to the concrete implementation."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    abstract: true
    interface: [chat, chat_stream]
    ---
```

```
# infrastructure/anthropic_adapter.s0ma — the concrete, layer INFRASTRUCTURE
module anthropic_adapter
    layer: INFRASTRUCTURE
    version: 1.0.0
    intent: "Anthropic-backed concrete LLMAdapter."
    uses: [llm_adapter.LLMAdapter]               # INFRASTRUCTURE → DOMAIN: OK
    exports: [AnthropicAdapter]

nerve AnthropicAdapter :: INFRASTRUCTURE
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Anthropic-API implementation of LLMAdapter."
    expects: "An ANTHROPIC_API_KEY env var; well-formed message turns."
    guarantees: "Returns the model's reply text; stream variant yields chunks."
    forbids: none
    evaluates_at: SUBSYSTEM
    abstract: false
    interface: [chat, chat_stream]
    depends_on:
        LLMAdapter: {relation: CONSTRUCTS, carries: "concrete impl of the port", coupling: TIGHT}
    ---
    class AnthropicAdapter:
        def __init__(self, client):
            self._client = client

        def chat(self, messages: list) -> str:
            return self._client.messages.create(messages=messages).content[0].text

        def chat_stream(self, messages: list):
            return self._client.messages.stream(messages=messages)
```

```
# application/orchestrator.s0ma — the consumer, layer APPLICATION
module orchestrator
    layer: APPLICATION
    version: 1.0.0
    intent: "Orchestrates a conversation using whichever LLMAdapter the bootstrap wires in."
    uses: [llm_adapter.LLMAdapter]               # APPLICATION → DOMAIN: OK
    exports: [run_turn]

nerve run_turn :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Send one conversation turn through the configured adapter."
    expects: "An LLMAdapter and a list of messages."
    guarantees: "Returns the assistant's reply text."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def run_turn(adapter: LLMAdapter, messages: list) -> str:
        return adapter.chat(messages)
```

The APPLICATION consumer only knows about the DOMAIN port; the INFRASTRUCTURE concrete is wired in at the bootstrap. The layer matrix is satisfied everywhere: `APPLICATION → DOMAIN` is in the reachable set, and `INFRASTRUCTURE → DOMAIN` is too. `INFRASTRUCTURE → APPLICATION` never appears in any module's `uses:` — the dependency edge structurally cannot land there.

### 18.2 When to reach for Decision-1

The pattern is the right structural fix when *all three* of the following hold:

- The consumer is in `APPLICATION` (or `PRESENTATION`).
- The implementation is genuinely an I/O boundary — talks to the network, the filesystem, a database, a vendor SDK. That work belongs in `INFRASTRUCTURE`.
- The interface (the methods the consumer actually calls) is stable enough to name. If you don't yet know what `chat`, `chat_stream`, `flush`, or `subscribe` look like, the abstract isn't ready to extract; consolidate the consumer first.

The pattern is *not* the right fix when the dependency is purely a data shape (a `MODEL` cell or `CONSTANT`). In that case §13.1 — move the shared concept down to DOMAIN — is structurally simpler and avoids inventing a port for something that has no behaviour.

### 18.3 Three working instantiations in fr3d

The pattern recurs across the fr3d codebase. The three canonical instantiations:

| Port (DOMAIN, `abstract: true`) | Concrete (INFRASTRUCTURE) | Consumer (APPLICATION) |
|---|---|---|
| `LLMAdapter` | `AnthropicAdapter`, `OpenAIAdapter`, `MockAdapter` | `orchestrator.run_turn`, `dialogue.compose_reply` |
| `MessageGateway` | `CLIGateway`, `WebSocketGateway`, `SlackGateway` | `message_dispatch.route_inbound` |
| `EventStore` | `JsonlEventStore`, `SqliteEventStore`, `RingBufferEventStore` | `event_log.record`, `subscription.fan_out` |

Each pair follows the same shape: the port names the interface and lives in DOMAIN; the concrete implements every method, lists `CONSTRUCTS` against the port in `depends_on:`, and lives in INFRASTRUCTURE; the consumer takes the port type and never imports the concrete directly. Bootstrap wires the concrete in at startup (see §9 for the abstract-adapter convention and §10 for bootstrap).

### 18.4 Why this is not just §13.2

§13.2 covers the general inversion principle: "have the lower layer publish an abstract interface and the higher layer implement it." Decision-1 specialises that principle in two ways:

- The abstract always lives in **DOMAIN**, not in the consumer's own layer. The temptation to keep the port in APPLICATION (because the consumer is the one that needs it) re-opens the matrix violation — INFRASTRUCTURE then has to reach into APPLICATION to implement the port. DOMAIN is the only layer every other layer can reach, so the port belongs there.
- The concrete's `depends_on:` block must carry `relation: CONSTRUCTS` against the abstract. The transpiler's cross-module abstract-validation pass (§9.3) reads that edge to verify every interface method has a `def` in the concrete's body.

Without the `CONSTRUCTS` edge, the abstract and concrete are structurally unrelated as far as the validator is concerned — drift between the two surfaces silently when the abstract gains a method the concrete forgets. The edge is the load-bearing link.

### 18.5 Cross-references

- Spec §4.0.2 — the cross-module layer reachability matrix.
- Spec §4.1.4 — the `abstract:` / `interface:` fields.
- Patterns guide §9 — abstract adapter convention (canonical shape, validator behaviour).
- Patterns guide §13.2 — generic inversion remediation (Decision-1 is a specialisation).

---

## 19. Late-bind dependency slot recipe

A SERVICE nerve sometimes needs to receive a dependency *after* its own construction — typically because the dependency itself depends on the SERVICE's instance (a planner consuming an orchestrator that calls back into the planner; an event visualiser subscribing to an EventStore the bootstrap built one line earlier). The dependency can't be passed to the SERVICE's constructor because the dependency doesn't exist yet at that moment.

The canonical recipe is a **single-cell mutable list**:

```
nerve Planner :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Plans a sequence of orchestrator turns; surfaces decision callbacks late-bound by bootstrap."
    expects: "An orchestrator reference, late-bound after construction."
    guarantees: "Returns a plan; emits a decision-callback signal when the orchestrator is wired."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    ---
    class Planner:
        # Single-cell mutable slot: list of length exactly one. None until wired.
        _orchestrator: list = [None]

        def attach_orchestrator(self, orch) -> None:
            self._orchestrator[0] = orch

        def plan(self, goal: str) -> dict:
            orch = self._orchestrator[0]
            if orch is None:
                raise RuntimeError("Planner.attach_orchestrator(...) was never called")
            return {"goal": goal, "first_turn": orch.next_turn(goal)}
```

The bootstrap then wires it:

```python
# bootstrap/startup.py
planner = Planner()
orchestrator = Orchestrator(planner)            # orchestrator's __init__ holds a ref to planner
planner.attach_orchestrator(orchestrator)       # late-bind the back-edge
```

### 19.1 Why a one-element list, not a plain attribute

Three reasons, in priority order:

1. **`dataclass` / `class` body forbids mutable default attributes.** Writing `_orchestrator = None` at class scope makes `_orchestrator` a class attribute, not an instance attribute — every Planner instance would share the same slot. Writing `_orchestrator: ClassVar[Any] = None` is structurally clearer but still shared. The single-element list moves the mutability into the slot's container, so `_orchestrator[0] = orch` rebinds the cell without rebinding the attribute.
2. **The mutable-default lint passes.** Python's `mutable default arguments` warning fires on `def f(x=[]):` because every call to `f` would share the same list. The lint *does not* fire on a class-body `_field: list = [initial]` because the assignment is at class definition time, not at every call. (See spec §4.1 — the class-body convention is intentional and idiomatic in s0ma SERVICE nerves.)
3. **The pattern reads consistently across the codebase.** A grep for `_*: list = \[` finds every late-bind slot in the project in one scan. Plain `None` attributes get lost in the surrounding class body; the one-element list is a syntactic flag.

### 19.2 When to reach for it

The recipe is the right call when *all three* hold:

- The dependency is genuinely a back-edge — A constructs B; B needs a reference to A.
- The back-edge is single-valued (one orchestrator per planner, one event store per subscription).
- The wiring happens in bootstrap, not in production code paths.

For multi-valued late-bind (a fan-out of subscriptions, a registry of callbacks), use a plain list (without the single-cell convention) and append to it. For dependencies that exist at construction time, pass them through `__init__` — late-bind is overkill.

### 19.3 Recurrence in fr3d

Six current instantiations, each following the same shape:

| Owner | Slot | Wired in bootstrap by |
|---|---|---|
| `Planner` | `_orchestrator: list = [None]` | `bootstrap.startup.wire_planner_orchestrator` |
| `Visualiser` | `_event_store: list = [None]` | `bootstrap.startup.wire_viz_subscription` |
| `DialogueRouter` | `_message_gateway: list = [None]` | `bootstrap.startup.wire_dialogue` |
| `CommandHandler` | `_orchestrator: list = [None]` | same as Planner — composed wiring |
| `EvaluatorNetwork` | `_decision_callback: list = [None]` | `bootstrap.startup.wire_evaluator_callbacks` |
| `BackgroundWorker` | `_signal_sink: list = [None]` | `bootstrap.startup.wire_worker_sinks` |

Every recurrence is structurally identical: one slot, one `attach_*` method, one bootstrap line.

### 19.4 Cross-references

- Spec §4.1 — nerve body conventions.
- Patterns guide §2.2 — class-bodied SERVICE pattern (the base shape this recipe extends).
- Patterns guide §10.2 — bootstrap (where the wiring lives).

---

## 20. Helper-as-fixture: hoist `_make_X` to a module-level `helper`

A test body that constructs a system-under-test through a setup function (`_make_planner()`, `_build_request()`, `_fake_event_store()`) shares a recognisable shape: a small `def` that returns a stub, a mock, or a configured instance the test cases drive. When two test functions need the same setup, the temptation is to copy-paste the helper into both bodies — which works once, but the moment a third test function arrives or the setup grows a parameter, the copies drift.

The right structural answer is to **hoist the `_make_X` helper out of the test bodies and declare it as a module-level `helper`**.

```
# Wrong-way — helper copy-pasted inside two test bodies in one module.
test test_planner_emits_decision :: APPLICATION
    intent: "Verifies Planner emits a decision signal."
    tests: [planner.Planner]
    ---
    def _make_planner():
        p = Planner()
        p.attach_orchestrator(StubOrchestrator())
        return p

    def test_planner_emits_decision():
        p = _make_planner()
        assert p.plan("goal-1")["first_turn"] is not None

test test_planner_rejects_empty_goal :: APPLICATION
    intent: "Verifies Planner raises on empty input."
    tests: [planner.Planner]
    ---
    def _make_planner():                          # <-- COPY-PASTED. Drift risk.
        p = Planner()
        p.attach_orchestrator(StubOrchestrator())
        return p

    def test_planner_rejects_empty_goal():
        p = _make_planner()
        with pytest.raises(ValueError):
            p.plan("")
```

Two copies, same name, both at module scope after emit. Phase 4 helper-collision detection (`HELPER_NAME_COLLISION`, see §4.8.3 of the spec) flags the second `_make_planner` because both end up as top-level `def`s in the emitted Python.

The right shape:

```
# Right — _make_planner is a module-level helper, callable from every test body.
helper _make_planner
    intent: "Builds a Planner wired with a stub orchestrator for tests."
    visibility: TEST
    ---
    def _make_planner():
        p = Planner()
        p.attach_orchestrator(StubOrchestrator())
        return p

test test_planner_emits_decision :: APPLICATION
    intent: "Verifies Planner emits a decision signal."
    tests: [planner.Planner]
    ---
    def test_planner_emits_decision():
        p = _make_planner()
        assert p.plan("goal-1")["first_turn"] is not None

test test_planner_rejects_empty_goal :: APPLICATION
    intent: "Verifies Planner raises on empty input."
    tests: [planner.Planner]
    ---
    def test_planner_rejects_empty_goal():
        p = _make_planner()
        with pytest.raises(ValueError):
            p.plan("")
```

Now there is one canonical `_make_planner`, the helper is registered in the module's IR with its intent, and the helper-collision check no longer fires (the test bodies don't declare `def _make_planner` — they just call it).

### 20.1 The decision rule

> **When you'd write `_make_X` as a fixture in two test blocks, hoist it to a module-level `helper`.**

If the helper is genuinely used by one test body — one `def`, one caller — leave it inline. The moment a second caller appears, hoist. There is no third case: helpers in three different test modules are a sign the setup is a fixture for *every* test in the project and should live with the production code as a `visibility: TEST` nerve (see §12).

### 20.2 What this closes

The long-running D-27 cross-block helper-name collision. The collision detector flags the *second* same-named `def` in any pair of test bodies; hoisting the helper removes the duplicate at the source. Spec §4.8.3 (Helper-Collision Detection) lays out the scope-aware detection rule that this remediation maps onto.

### 20.3 Cross-references

- Spec §4.4a — `helper` declaration kind.
- Spec §4.8.3 — Helper-Collision Detection (Scope-Aware).
- Patterns guide §12 — Test-only helpers (`visibility: TEST`) for the cross-module variant.
- Patterns guide §15 — Helpers vs nerves (module-private functions).

---

## 21. Patch-via-context-manager + helper pair

When a test needs to swap a callable's behaviour for the duration of one test body — typically because the callable shells out to the network, the filesystem, or a vendor SDK — `unittest.mock.patch` is the canonical tool. The temptation is to drop a `monkeypatch.setattr(...)` line into every test body that needs the swap; pytest's monkeypatch fixture is the obvious analogue. But monkeypatch carries two costs that the s0ma `helper` + context-manager pair avoids: it requires an injected fixture parameter on every test function, and it cannot be cleanly nested or composed with other context managers without losing the scope.

The recipe pairs a tiny patcher `helper` with a context-manager protocol, then drives it from each test body via `with`.

```
# src/integration/runner.s0ma
nerve run_subprocess :: INFRASTRUCTURE
    kind: SERVICE
    visibility: PUBLIC
    intent: "Run a subprocess and capture its stdout."
    expects: "A list of command arguments."
    guarantees: "Returns (returncode, stdout)."
    forbids: none
    evaluates_at: SUBSYSTEM
    ---
    def run_subprocess(cmd: list) -> tuple:
        import subprocess
        result = subprocess.run(cmd, capture_output=True, text=True)
        return (result.returncode, result.stdout)
```

```
# tests/runner_tests.s0ma
module runner_tests
    layer: INFRASTRUCTURE
    version: 1.0.0
    intent: "Tests for run_subprocess."
    requires: [unittest.mock:patch]
    uses: [runner.run_subprocess]
    exports: []

helper _patch_run_ok
    intent: "Context manager that patches subprocess.run to return (0, 'ok\\n')."
    visibility: TEST
    ---
    def _patch_run_ok():
        return patch(
            "runner.subprocess.run",
            return_value=type("R", (), {"returncode": 0, "stdout": "ok\n"})(),
        )

helper _patch_run
    intent: "Context manager that patches subprocess.run with a caller-supplied handler."
    visibility: TEST
    ---
    def _patch_run(handler):
        return patch("runner.subprocess.run", side_effect=handler)

test test_run_subprocess_happy :: INFRASTRUCTURE
    intent: "Verifies run_subprocess returns (returncode, stdout)."
    tests: [runner.run_subprocess]
    ---
    def test_run_subprocess_happy():
        with _patch_run_ok():
            assert run_subprocess(["echo", "ok"]) == (0, "ok\n")

test test_run_subprocess_failure :: INFRASTRUCTURE
    intent: "Verifies run_subprocess surfaces non-zero exit."
    tests: [runner.run_subprocess]
    ---
    def test_run_subprocess_failure():
        def fail(cmd, **kw):
            return type("R", (), {"returncode": 2, "stdout": ""})()
        with _patch_run(fail):
            rc, out = run_subprocess(["false"])
            assert rc == 2
```

`_patch_run_ok()` returns the default-case context manager directly; `_patch_run(handler)` accepts a per-test handler and returns a parameterised one. Both are scoped to the `with` block, so cleanup is automatic and no fixture parameter has to thread through the test signature.

### 21.1 Why prefer this over monkeypatch

The pair has three properties monkeypatch lacks:

- **Composability.** `with _patch_run_ok(), _patch_clock(fixed=12345):` is a one-liner; monkeypatch fixtures don't compose without per-fixture parameter plumbing.
- **Locality.** The patcher lives in the same `.s0ma` file as the tests, declared as a `helper`. The intent is in the patcher's metadata, not buried in a `conftest.py`. Reviewers see the swap and its scope in one view.
- **No fixture wiring.** Test functions stay parameter-free. The argument-list churn that monkeypatch propagates through every test signature ("now this test needs `monkeypatch`, now this one too...") never starts.

### 21.2 When monkeypatch *is* still the right answer

The pair is overkill for ad-hoc one-off patches in a single test. If the swap is genuinely single-use and the cost of authoring two helpers outweighs the readability win, `monkeypatch.setattr(module, "name", stub)` is fine. The pair pays off when the *same swap* recurs across three or more test functions — at that point, the patcher is itself a fixture, and giving it a name + intent in the patterns-guide shape is the right structural call.

### 21.3 The `_patch_X` naming convention

The leading underscore + `_patch_` prefix is convention: it groups all patcher helpers visually, matches the existing test-only helper convention (`_make_X`, `_build_X`), and surfaces them as "patcher" in the helper IR for `s0ma inspect`. The intent line on each helper carries the natural-language description of *what is being swapped and to what behaviour* — that line is what a reviewer reads when scanning the test module's helpers, so make it specific.

### 21.4 Cross-references

- Spec §4.4a — `helper` declaration kind.
- Patterns guide §20 — Helper-as-fixture (`_make_X` hoist pattern).
- Quick reference — `requires:` colon override for `unittest.mock:patch`.

---

## 22. Cross-thread `asyncio.Queue` pattern (`loop.call_soon_threadsafe`)

When a sync-side handler — typically a Slack RTM event hook, a Discord WebSocket dispatcher, a SDK callback that fires on a vendor thread, a `threading.Thread` worker — needs to push a record into an `asyncio.Queue` owned by the main event loop, the naive `queue.put_nowait(record)` call from the sync thread races against the loop's read side. `asyncio.Queue` is not thread-safe; the right tool is `loop.call_soon_threadsafe`, which schedules a callback on the loop thread and returns immediately to the caller's thread.

The canonical recipe:

```
nerve SlackEventBridge :: INFRASTRUCTURE
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Bridges Slack RTM events (sync callbacks on a vendor thread) into an asyncio.Queue consumed by the orchestrator."
    expects: "The asyncio loop and the queue belong to one thread; the Slack RTM client invokes on_message on a vendor thread."
    guarantees: "Every Slack event arrives on the queue; loop-thread reads see a consistent FIFO."
    forbids: none
    evaluates_at: SUBSYSTEM
    requires: [asyncio]
    ---
    class SlackEventBridge:
        def __init__(self, loop, queue):
            self._loop = loop
            self._queue = queue

        def on_message(self, record) -> None:
            # Called on the Slack RTM thread.
            # Do NOT call self._queue.put_nowait directly — race against loop reads.
            self._loop.call_soon_threadsafe(self._safe_put, record)

        def _safe_put(self, record) -> None:
            # Runs on the loop thread; safe to touch the queue.
            try:
                self._queue.put_nowait(record)
            except asyncio.QueueFull:
                # Caller-policy: drop, log, or raise. The drop path is the
                # most common in event-bridge use; the bridge logs and continues.
                pass
```

The orchestrator-side consumer is a vanilla `async for`-shaped loop:

```
nerve orchestrate_slack_events :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Consumes Slack events from the cross-thread queue."
    expects: "An asyncio.Queue populated by SlackEventBridge."
    guarantees: "Processes every event; exits when the queue is closed."
    forbids: none
    evaluates_at: SUBSYSTEM
    ---
    async def orchestrate_slack_events(queue):
        while True:
            record = await queue.get()
            if record is None:                 # Sentinel: shutdown
                break
            await handle(record)
            queue.task_done()
```

### 22.1 The contract `call_soon_threadsafe` enforces

`loop.call_soon_threadsafe(callable, *args)` schedules `callable(*args)` to run on the loop thread at the next loop iteration. It is the only thread-safe entry point into the loop from foreign threads. Three properties matter:

- **Order is preserved per submitting thread.** If thread A submits records r1, r2, r3 in order, the loop sees them in the same order. (Different submitting threads interleave non-deterministically, but no single thread's stream is reordered.)
- **Submission is non-blocking.** The vendor thread does not wait for the loop to pick up the callback; this matters when the vendor SDK punishes slow handlers (Slack RTM rate-limits handlers >5s).
- **`QueueFull` still has to be caught on the loop thread.** The naive sync-side `put_nowait` would raise on the vendor thread, where the SDK's error path may be different; routing the put through the loop thread means the bridge owns the back-pressure policy in one place.

### 22.2 What happens if you skip `call_soon_threadsafe`

If the bridge calls `self._queue.put_nowait(record)` directly from the vendor thread:

- Most of the time, it works — Python's GIL hides the race.
- Occasionally, the queue's internal pointers are observed mid-update by the loop thread's read side. The reader gets a partially-updated state and crashes with an `AttributeError` deep inside `asyncio.Queue._wakeup_next`. The crash is rare enough that it doesn't reproduce in any reasonable test; rare enough that it ships and surfaces in production once a week. Then the post-mortem is hours.

The threadsafe scheduling is the cheap fix that closes that class entirely.

### 22.3 Per-Phase-4 reach

This pattern will recur for every Phase 4 channel adapter — Slack RTM, Discord WS, Telegram bot, IRC, Matrix, anything with a vendor-thread callback model. The shape stays identical: one bridge nerve per channel, one `_safe_put` helper, one `call_soon_threadsafe` in `on_<event>`, one async consumer on the orchestrator side. The bridge's metadata varies (intent, expects, guarantees, forbids, the channel-specific record shape); the structural recipe does not.

### 22.4 Variants

If the consumer needs to await the put (queue is bounded and the producer must back-pressure), use `asyncio.run_coroutine_threadsafe(self._queue.put(record), self._loop).result()` — this *does* block the vendor thread until the put completes. The blocking variant is right when dropping a record would lose work; the non-blocking variant is right when the channel can tolerate drops under burst load.

### 22.5 Cross-references

- Python stdlib docs — `asyncio.AbstractEventLoop.call_soon_threadsafe`, `asyncio.run_coroutine_threadsafe`.
- Patterns guide §2.2 — class-bodied SERVICE pattern (the base shape this bridge extends).
- Patterns guide §19 — late-bind dependency slots (the loop + queue are typically late-bound).

## 23. IntegrationManifest pattern + `integration` declaration (POST-5, 0.16.0)

External-system adapters (OAuth-backed gateways, third-party API clients, cron-triggered importers) share a recurring shape: a SERVICE factory nerve that constructs the runtime client + a `get_manifest` function returning an `IntegrationManifest` dataclass describing the adapter's surface + a smoke-test nerve verifying the wiring at startup time. The Phase 1 Google Calendar adapter, Phase 3's Gmail / Slack work, and fr3d's Notion integration all instantiate this pattern.

The pre-POST-5 ("manual") shape:

```
module gcal_integration
    layer: INFRASTRUCTURE
    intent: "Google Calendar OAuth adapter."
    requires: [integration_models.IntegrationManifest, integration_models.AuthMethod]
    exports: [GoogleCalendarClient, get_manifest, smoke_calendar_read]
    ---

nerve GoogleCalendarClient :: INFRASTRUCTURE
    kind: SERVICE
    visibility: PUBLIC
    intent: "Construct the calendar client from cached OAuth creds."
    ...
    ---
    def GoogleCalendarClient():
        ...

nerve get_manifest :: INFRASTRUCTURE
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return the integration manifest for the daily scheduler."
    ...
    ---
    def get_manifest():
        return IntegrationManifest(
            name="google_calendar",
            auth_method=AuthMethod.OAUTH2,
            tool_names=["create_event", "list_events", "update_event"],
            scopes=["https://www.googleapis.com/auth/calendar.events"],
            ...
        )

nerve smoke_calendar_read :: INFRASTRUCTURE
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Smoke-test: list one event via the read-only scope."
    ...
    ---
    def smoke_calendar_read():
        ...
```

The first-class `integration` declaration (0.16.0+) collapses the boilerplate by auto-emitting `get_factory`, `get_manifest`, `smoke_test_primary`, and `get_smoke_test`:

```
integration GoogleCalendarIntegration :: INFRASTRUCTURE
    version: 0.1.0
    intent: "Read-only Google Calendar adapter for the daily scheduler."
    factory: GoogleCalendarClient
    smoke_test_primary: smoke_calendar_read
    manifest:
      provides: [list_events, get_event]
      required_env: [GOOGLE_CALENDAR_CREDENTIALS]
      requires_oauth: true
```

The author still declares `GoogleCalendarClient` (the SERVICE factory) and `smoke_calendar_read` (the smoke-test) as separate nerves in the same module. The `integration` block is metadata + codegen affordances — the transpiler auto-emits the four wrapping helpers and registers each under a module-qualified key (`module_scoped=True`), so two integrations in different modules can share helper names without collision.

### 23.1 When to reach for the first-class form

- **Two or more integrations in one project.** The legacy pattern works for one integration; with two, the bare names (`get_manifest`, `get_factory`) collide in the registry unless every helper is module-scoped. The `integration` declaration handles that automatically.
- **You want `s0ma inspect` to show the integration as a single coherent surface.** The legacy pattern surfaces three separate nerves; the new form renders an `Integrations` section that groups them under the declaration's intent + manifest summary.
- **The manifest fits the canonical shape.** When `provides:` / `required_env:` / `requires_oauth:` cover everything you'd put on a dataclass, the `integration` declaration is strictly less code.

### 23.2 When to stay on the legacy pattern

- **Phase 1 / Phase 3 production integrations already shipping.** Migrating requires re-wiring downstream consumers; the legacy pattern keeps working and the new declaration is opt-in, not a forced migration.
- **Your manifest carries a richer Python dataclass than the JSON-primitive map.** If the manifest needs typed enum values, datetime-aware fields, or other custom-class instances, the `manifest:` map's "JSON-serialisable primitives only" rule won't fit. Stay on the legacy form and construct the dataclass directly in `get_manifest`.
- **You need the factory nerve to take constructor parameters.** The auto-emitted `get_factory()` calls the factory with no arguments. If the factory needs a parameterised constructor, stay on the legacy form or wrap the call in a separate nerve.

### 23.3 Cross-references

- Spec §4.4b — full `integration` declaration contract, including all four error codes (`INTEGRATION_FACTORY_NOT_FOUND`, `INTEGRATION_FACTORY_NOT_SERVICE`, `INTEGRATION_SMOKE_TEST_NOT_FOUND`, `INTEGRATION_INVALID_MANIFEST_KEY`).
- Patterns guide §2 — SERVICE nerve patterns (the factory nerve under any integration is always a SERVICE nerve).
- Phased improvements doc — POST-5 (the operator-facing rationale).

---

## 24. Durable-state migrations

Durable state — a database, an on-disk file format, anything the running application persists and reloads across restarts — outlives any single build. When a change alters the **shape** of that state (a new column, a renamed field, a reworked record layout), two code paths touch it: the **creation** path that builds the store from nothing, and the **existing-data** path that every already-running deployment is on. Editing only the creation path is a fresh-state-only fix — it works on a store the new code created and is invisible-then-fatal on one the previous version created.

### 24.1 The `CREATE TABLE IF NOT EXISTS` anti-pattern

The canonical trap adds a schema change only inside the table's creation DDL:

```sql
-- Wrong — the new column is added ONLY to the creation path.
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY,
    action  TEXT NOT NULL,
    actor   TEXT NOT NULL          -- NEW: declared here and nowhere else
);
```

On a fresh database this DDL runs and `actor` exists. On a database the previous version created, the table already exists, so `CREATE TABLE IF NOT EXISTS` is a **no-op** — the `IF NOT EXISTS` guard skips the whole statement — and the column is never added. The next `INSERT ... (action, actor) VALUES (...)` then fails at runtime on every existing deployment, while passing on every fresh one.

This is the shape of the batch-01c CM6 failure: an `actor` column was added to a `CREATE TABLE IF NOT EXISTS audit_log` DDL for a service whose database already held data, so each mutation's `INSERT ... actor` errored and the run cratered — a fresh-database test would have stayed green and hidden it. Cold-start batteries exist to surface exactly this class: fresh agent, existing state.

### 24.2 The fix: migrate the existing store

An existing deployment needs an explicit migration beside the creation-path edit — code that brings a store built by the old version up to the new shape:

```sql
-- Right — the creation path AND a guarded migration for existing databases.
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY,
    action  TEXT NOT NULL,
    actor   TEXT NOT NULL DEFAULT 'unknown'
);

-- Run on load; idempotent, applied only when the column is absent:
ALTER TABLE audit_log ADD COLUMN actor TEXT NOT NULL DEFAULT 'unknown';
```

For a file format the equivalent is **rewrite-on-load**: detect the old shape when reading, transform it to the new one in memory, and write it back. The principle is identical in both cases — the creation path is not the only path, and the data that already exists is the one production runs on.

### 24.3 The one check that catches it

Before shipping any change to durable-state shape, ask a single question:

> **Would this work on a database created by yesterday's version?**

If the change appears only in the creation path (`CREATE TABLE IF NOT EXISTS`, a first-write default, an initial-file template), the answer is no and the change is incomplete until a migration exists. This is the data-shape companion to the runtime-state discipline the survival rules and the `s0ma://project/runbook` resource carry: live state is the deliverable — never reverted, regenerated, or restored from a committed version — and a shape change to it is not done until existing state is migrated. s0ma teaches this discipline rather than enforcing it: no diagnostic yet flags a column reference that appears in no `CREATE`/`ALTER`, so the check is the author's to run.

### 24.4 Cross-references

- Patterns guide §10 — bootstrap and entry points (where a rewrite-on-load or a run-once migration hook is wired into startup).
- `s0ma://project/runbook` — the operational surface carrying `state_paths` and the never-revert-live-state rule.
- `s0ma://guide/survival-card` — the compact ruleset, including the durable-state-migration rule.

---

# Project standards

Sections 25–29 are the blessed conventions for laying out, scoping, and documenting a s0ma project. They are the standards `s0ma new project` scaffolds and `s0ma score` measures against — the shape thousands of agents and humans should converge on. Each one is a *standard*, not a language rule: the grammar does not (yet) enforce most of them, so the discipline is on the author. Where a standard touches something the grammar *does* enforce (the layer matrix, the filename-stem rule, the release-mode doc/test gates) that is called out inline.

## 25. Project layout (feature-first)

A s0ma project's default shape is **feature-first**: top-level directories under the source root name *features* (business capabilities), and within each feature one `.s0ma` module sits per architectural layer. This is the layout `s0ma new project` scaffolds and the one to reach for unless you have a specific reason not to (see §25.3 for the small/library exception).

### 25.1 The shape

```
myproj/
    pyproject.toml            # [tool.s0ma] table: source_roots = ["src"], test_roots = ["tests"]
    src/
        orders/               # a FEATURE directory
            orders_domain.s0ma         # module orders_domain      :: layer DOMAIN
            orders_application.s0ma     # module orders_application :: layer APPLICATION
            orders_presentation.s0ma    # module orders_presentation :: layer PRESENTATION
        billing/              # another feature
            billing_domain.s0ma
            billing_application.s0ma
        app_map.s0ma          # the project-wide app map (see §29)
    tests/
        orders/               # tests mirror features
            orders_domain_tests.s0ma
            orders_application_tests.s0ma
        billing/
            billing_application_tests.s0ma
```

Reading the rule: **one feature per directory; within a feature, one module per layer; `tests/` mirrors the feature tree.** A module is single-layer by construction (every component in a module shares the module's `layer:` — §13), so "one module per layer per feature" falls out naturally: a feature that spans DOMAIN, APPLICATION, and PRESENTATION is three modules in one directory.

### 25.2 Naming the module-per-layer files

> **The filename stem MUST equal the declared module name** (the grammar enforces this — a mismatch is `MODULE_NAME_STEM_MISMATCH`, error in every mode; cache keys and `uses:` import paths derive from the module name). A module name is a single Python-identifier-shaped token, so it **cannot contain a dot**. Join the feature and layer with an **underscore**, not a dot:

```
src/orders/orders_domain.s0ma          ✓  module orders_domain
src/orders/orders_application.s0ma      ✓  module orders_application
src/orders/orders.domain.s0ma          ✗  stem "orders.domain" ≠ module name → MODULE_NAME_STEM_MISMATCH
```

The convention is `<feature>_<layer>` for both the filename stem and the `module` declaration (`orders_domain`, `orders_application`, …). The directory carries the feature; the stem repeats it so the module name is self-describing in a flat `uses:` graph and in `s0ma inspect`. (Hierarchical *dotted module names* — `module orders.domain` — are a deliberately deferred DSL change, not the convention here; the build directory stays flat regardless. See the boundary between layout-as-source-tree and identity-as-flat-name in the bootstrap and manifest docs.)

A feature with a single layer is just one file: `src/notifications/notifications_domain.s0ma`. Don't invent empty layer modules to "fill out" the grid — scaffold the layers the feature actually has.

### 25.3 Layer-first as the documented alternative

For a **small project or a library** — one feature, or a handful of modules whose value is an export surface rather than a multi-feature application — a **layer-first** layout is acceptable: top-level directories name *layers*, and modules sit under the layer they belong to.

```
src/
    domain/
        order.s0ma            # module order :: DOMAIN
    application/
        order_service.s0ma    # module order_service :: APPLICATION
```

Use layer-first only when the project is small enough that a single layer directory holds one or two modules. The moment a second genuine feature appears, prefer feature-first.

### 25.4 Why feature-first is the default (the asymmetry)

The decision turns on a one-way cost (owner decision, binding):

- **Feature → layer is easy.** A feature-first project already groups everything one capability touches in one directory. Reading "all of orders" is one `ls`. If you later want a layer-wide view (every DOMAIN module, say), the layer is still recorded on every module (`layer:` + the manifest's per-module structure) and `s0ma inspect --all` / a `doc-ref` filtered `where layer == DOMAIN` reconstructs it for free.
- **Layer → feature is painful.** A layer-first project scatters one capability across `domain/`, `application/`, `presentation/`, `infrastructure/`. Answering "what does orders consist of, and what breaks if I change it" means grepping four directories and reassembling the feature by hand. There is no cheap reconstruction — the grouping the reader wants was never written down.

Because the translation is cheap in one direction and expensive in the other, the default is the one that keeps the expensive reconstruction off the table. Layer discipline is **not lost** in feature-first: the layer reachability matrix (§13, §26) is enforced identically whichever way the directories are arranged — layers are a property of modules, not of folders.

### 25.5 Archetype starters (`--template`)

`s0ma new project <dir>` without a flag scaffolds the minimal single-feature starter. `--template <service|library|cli>` scaffolds a **complete, compiling worked example** instead — each archetype builds, passes `s0ma check --mode release`, runs its tests, and (where it has one) runs its bootstrap, straight out of the command. The archetype *is* the design-pattern documentation; read the one whose shape matches what you are building, then grow it.

| `--template` | Layout | The pattern it teaches |
|---|---|---|
| `service` | three features, three layers — DOMAIN `catalog` → APPLICATION `ordering` → PRESENTATION `api`, plus `bootstrap/main.py` | **Cross-feature `depends_on:`** in the qualified `module.declaration` form and the **layer reachability matrix** (PRESENTATION → APPLICATION → DOMAIN, never upward). The boundary doctrine: one sanctioned bootstrap, declared in `[tool.s0ma].bootstrap_files`. |
| `library` | one DOMAIN feature — a slug core + a thin public facade | **`exports:`** and **`covered_by:`** (external pytest-suite test credit that satisfies the release gate on a facade with no in-language test). Layer-light is fine for a small library (§25.3). |
| `cli` | DOMAIN/APPLICATION core + a PRESENTATION router, plus `bootstrap/cli.py` | The **`argparse.REMAINDER`** thin-Python bootstrap → PRESENTATION nerve handoff (§10), including the leading-`--` strip. |

All three ship the feature-first layout, AGENTS.md + a thin CLAUDE.md, the load-bearing app map (§29), and starter `test`/`covered_by:` coverage. The `service` archetype is the most representative full application and the recommended starting point for a typical project.

## 26. Placement, not architecture

This is PRD **P-9** expanded into authoring guidance. s0ma is opinionated about **placement** and silent about **architecture** — and the two are different things.

### 26.1 What s0ma fixes (placement)

- **Layers.** Every module declares exactly one `layer:` (DOMAIN, APPLICATION, PRESENTATION, INFRASTRUCTURE, FRAMEWORK), and every component in it shares that layer (§13).
- **Kinds.** Every declaration is a typed kind (`nerve`/`cell`/`ganglion`/`helper`/`integration`/…) with required contract fields — the registry knows what each thing *is*.
- **The blessed layout.** Feature-first (§25): where modules live in the source tree.
- **Reachability — the enforced matrix.** A module's `uses:` edges cannot reach a higher layer than the module itself. This is not advisory: it is computed and gated by the dependency resolver — see **`packages/s0ma-dsl/src/s0ma_dsl/resolver/dependency.py`** — and a violation is `CROSS_LAYER_DEPENDENCY` (warning in migration/dev, error in strict/release). The authoritative matrix:

  | Source layer | May reach |
  |---|---|
  | `DOMAIN` | `DOMAIN`, `FRAMEWORK` |
  | `APPLICATION` | `DOMAIN`, `APPLICATION`, `FRAMEWORK` |
  | `PRESENTATION` | `DOMAIN`, `APPLICATION`, `PRESENTATION`, `FRAMEWORK` |
  | `INFRASTRUCTURE` | `DOMAIN`, `APPLICATION`, `INFRASTRUCTURE`, `FRAMEWORK` |
  | `FRAMEWORK` | `FRAMEWORK` |

### 26.2 What s0ma does NOT prescribe (architecture)

s0ma does **not** dictate an application architecture. It does not require DDD, ports-and-adapters, hexagonal, clean architecture, transaction-script, CQRS, or any other style. You bring your own. s0ma's job is to make whatever structure you choose **self-describing and drift-proof** — an architecture-neutral substrate, not an opinionated framework.

Concretely, the same layered placement hosts many architectures:

- A **ports-and-adapters** app puts the abstract port in DOMAIN and the concrete adapter in INFRASTRUCTURE (the Decision-1 recipe, §18). s0ma enforces that the consumer reaches the port, never the concrete — but it never asked you to use ports in the first place.
- A **transaction-script** app puts each script as an APPLICATION nerve calling DOMAIN models directly. s0ma enforces APPLICATION → DOMAIN — but it never asked you to split into scripts.
- A **DDD** app maps aggregates to DOMAIN cells, application services to APPLICATION nerves, and read models wherever they are consumed. s0ma records the kinds and edges — but the aggregate boundaries are yours.

### 26.3 The practical consequence

When the layer matrix fires (`CROSS_LAYER_DEPENDENCY`), the fix is a **placement** fix — move the shared concept down (§13.1), invert the dependency (§13.2), or introduce an abstract port (§18). It is never "turn off the rule." The matrix is not negotiable per-project; if a real consumer needs to bend it, the architecture is wrong for layered placement, and the redesign is the answer. What s0ma will *not* do is tell you which architecture to adopt — that judgment stays with you.

## 27. Naming conventions

These conventions are **docs-only** (owner decision — build discipline now, lint deferred). The grammar does not enforce them; `s0ma score` and code review do. They codify the rules the flagship MCP server (`packages/s0ma-mcp/s0ma_src/`) follows implicitly, so a reader of one s0ma project can read them all.

### 27.1 Served-name suffixes + `serves_as:` (public name ≠ identifier)

When a nerve is *served* under a public name that differs from its declaration identifier — an MCP tool, an HTTP handler, an RPC method — suffix the **declaration** with its role and put the **public name** in `serves_as:`:

```
nerve check_tool :: PRESENTATION       # declaration identifier: <verb>_<role>
    kind: FUNCTION
    visibility: PUBLIC
    serves_as: check                    # the served (public) name
    ...
```

The suffixes are `_tool` / `_resource` / `_prompt` for the three MCP surfaces; extend the same pattern for other serving layers (`_handler`, `_endpoint`) as needed. The declaration identifier stays the registry/module symbol (greppable, unambiguous: `check_tool` never collides with the built-in verb `check`); `serves_as:` is the one place the public name is authored, and the emitter stamps it onto the callable's `__name__`/`__qualname__`. Served names form one flat namespace per module and per project build — a duplicate is `SERVES_AS_COLLISION`. When the served name and the identifier are the same, omit `serves_as:` (or set it equal — both are allowed).

### 27.2 `_`-prefixed helpers and internal components

A leading underscore marks "not public surface":

- **`helper`** declarations conventionally start with `_` (`_safe`, `_resolve_root`, `_run_cli` in the flagship). Helpers are module-private by construction; the underscore makes the intra-module/cross-module asymmetry visible in body code.
- **`INTERNAL` and `TEST` cells/nerves** that are implementation detail conventionally start with `_` (`_ToolFn`, `_ARTIFACT_SUFFIXES`). The underscore signals "do not reach for this from outside the module" even before the reader checks `visibility:`.
- Public components (`visibility: PUBLIC`, listed in `exports:`) do **not** take a leading underscore.

### 27.3 `SCREAMING_SNAKE` constants

A `kind: CONSTANT` cell's name is the Python identifier its body assigns (the grammar enforces the match — `CONSTANT_NAME_MISMATCH` otherwise). Use `SCREAMING_SNAKE_CASE` for both (`DEFAULT_TIMEOUT`, `MAX_RETRIES`, `API_VERSION`), public or internal. See §7.

### 27.4 Module names: `<feature>_<layer>`

Per §25.2, the module-per-layer-per-feature name is `<feature>_<layer>` (`orders_domain`, `orders_application`) and the filename stem must equal it. Layer-first/library modules name themselves after the concept they own (`order`, `order_service`).

### 27.5 At a glance

| Subject | Convention | Example |
|---|---|---|
| Served nerve (public name ≠ id) | `<verb>_<role>` declaration + `serves_as: <public>` | `check_tool` → `serves_as: check` |
| Helper | leading `_` | `helper _resolve_root` |
| Internal / test component | leading `_` | `cell _ToolFn` |
| CONSTANT cell | `SCREAMING_SNAKE` (= body identifier) | `MAX_RETRIES` |
| Feature module | `<feature>_<layer>` (= filename stem) | `orders_domain` |
| Public component | no leading `_`, in `exports:` | `submit_order` |

## 28. The boundary doctrine

The boundary doctrine answers one question: **what belongs in `.s0ma`, and what is allowed to stay handwritten Python?** The doctrine is three rules — *maximize in-s0ma*, *minimal exempt set*, *external by reference*.

### 28.1 Maximize in-s0ma

Author **as much of the project as possible** as `.s0ma` declarations. Domain logic, services, adapters, config, constants, tests, and the documentation that describes them all belong in `.s0ma` — that is what puts them in the self-model registry, under the layer matrix, in the dependency graph, and reachable by `s0ma inspect` / the app map. Handwritten `.py` is the exception you justify, not the default you fall back to. (See §10.1 for the per-file decision table.)

### 28.2 The exempt set is EXACTLY these four — nothing more

A component may stay handwritten Python only if it is one of the following. This list is closed: anything not on it that is written in `.py` is drift, surfaced by `s0ma verify` as `UNKNOWN` and counted against the project by `s0ma score`.

- **The single handwritten bootstrap module.** The one entry-point/init shim that must exist *before* the s0ma import hook is active so it can call `bootstrap_imports(build_dir)` (e.g. `src/<pkg>/__init__.py` for a self-hosting package, or `bootstrap/startup.py`). It cannot be `.s0ma` because it loads the `.s0ma`-derived modules. Keep it to one module.
- **`[tool.s0ma].bootstrap_files`.** Every *other* intentional plain-Python file (a thin CLI shim, a framework-init helper) declared in this list so `s0ma verify` classifies it `BOOTSTRAP` (informational) rather than `UNKNOWN` (drift). See §10.2.
- **`[tool.s0ma].package_markers`.** `__init__.py` files acknowledged as package markers (the executable-content ones; empty/docstring-only markers are auto-classified, no declaration needed). See the verify status legend in spec §4.13.
- **`@internal`** — components marked internal/out-of-band that are deliberately outside the served surface and registered as such.

That is the whole exempt set: **{ the single bootstrap module, `bootstrap_files`, `package_markers`, `@internal` }**. There is no fifth category. If you find yourself wanting to exempt something else, the answer is almost always to author it as `.s0ma` (rule 1) or to reference it (rule 3) — not to widen the exemption.

### 28.3 External by reference

Code you legitimately do not author in `.s0ma` — a third-party library, a large hand-maintained `.py` integration, an external test suite, a big embedded asset — is brought into the model **by reference**, not by inlining or by leaving it invisible. Pick the reference mechanism that fits:

| You have… | Reference it with | Effect |
|---|---|---|
| An external Python package a body imports | `requires:` (or `soft_requires:` / `runtime_only_requires:`) | Recorded import; `MISSING_PACKAGE` if absent |
| An external dep used only at call time (degrade-don't-crash) | `deferred_requires:` | Import injected per-call; server starts in a broken env |
| A PUBLIC nerve covered by an external pytest suite | `covered_by: ["<suite path>"]` | Satisfies the release-mode `MISSING_TEST_COVERAGE` gate without an in-language `test` |
| A large hand-authored asset (HTML/SQL/prompt/JSON) | `content: @file("path")` on a CONSTANT cell | Content embedded at build, hashed, kept out of the `.s0ma` body (§14) |

The principle: when inlining is inefficient or impossible, the external thing is still *named in the model* — its existence and its contract are recorded, even though its body lives elsewhere. Invisible external code is the failure mode the doctrine exists to prevent.

### 28.4 The worked example: the MCP self-host

`packages/s0ma-mcp` is the doctrine applied at the full release gate. **One** handwritten bootstrap module (`src/s0ma_mcp/__init__.py`) derives the FastMCP surface from the registry; **everything else** — every tool, resource, and prompt — is a `.s0ma` module under `s0ma_src/` (`tools.s0ma`, `resources.s0ma`, `prompts.s0ma`), built to the committed `_built/`. The dsl/core machinery the tools call is brought in by reference (`deferred_requires:` so the server starts degraded), the long prompt templates by reference (`content: @file()`), and the boundary-contract suites by reference (`covered_by:`) alongside in-language `test` declarations. That is max-in / minimal-exempt / external-by-reference in production.

### 28.5 A shadow implementation is never the fifth category — STOP and REPORT

If the s0ma runtime cannot be deployed where the code must run — the environment refuses to install `s0ma-core`, the built output will not import, the platform forbids the dependency — **stop and report the blocker**. Name the failing import and the environment. Do NOT hand-write a plain-Python copy of a modeled component to keep going.

A parallel implementation of something already declared in `.s0ma` is the single worst outcome available:

- **Two definitions, one concept.** The `.s0ma` source and the hand-written twin drift the moment either is touched, and nothing gates them against each other. The self-model then describes a component that is not the one running — which is precisely the failure s0ma exists to abolish.
- **It is invisible where it matters.** The shadow does not register, so `s0ma inspect`, the app map, and the impact analysis keep answering from the model while the process runs the copy. `s0ma verify` can only flag it as `UNKNOWN` drift; `s0ma score` counts it against the project.
- **It is not an exemption.** §28.2's list is closed. "The runtime was not available" is a *deployment* fact, not a fifth category — it does not license a second implementation.

Observed failure mode: an agent under acceptance pressure, unable to import the runtime in its target venv, wrote plain-Python re-implementations of built modules so its demo would pass. The demo passed; the project no longer knew itself.

**The move instead:** report — "cannot deploy the s0ma runtime here: `<import> → <error>`" — and stop. Whether the environment gets the runtime or the component leaves s0ma is an owner decision, not a coping strategy. (Deployment needs `s0ma-core` only: the bootstrap is `s0ma.bootstrap.bootstrap_imports` since 0.16.x — see §10.2.)

## 29. The app-map pattern

The **app map** is a project's load-bearing, self-rendering architecture document — the one place a newcomer (human or agent) reads to learn what the project is, that **cannot rot** because the build refuses to commit it out of sync. It is a pair of declarations in one docs module:

1. a **`doc-ref`** that auto-renders the public API from the registry, and
2. a **`doc-guide`** that narrates the architecture, structured around the three faculties of self-knowledge (structure / runtime state / reasoning).

Both are drift-gated (`DRIFT_DETECTED` — error in strict/release): change a covered component without updating the map and the build fails. This is the pattern `s0ma new project` scaffolds into every starter feature.

### 29.1 Copy-pasteable example

Put this in a `PRESENTATION`-layer docs module (e.g. `src/app_map.s0ma`). It is validated `.s0ma` — it builds and passes `s0ma check --mode strict` and `s0ma docs check-drift` as written (rename the covered nerve to one your project actually exports):

```
module app_map
    layer: PRESENTATION
    version: 0.1.0
    intent: "The project's load-bearing app map: a generated public-API reference plus a three-faculty architecture guide, both drift-gated."
    exports: []

doc-ref public_api_reference
    intent: "Generated reference of every PUBLIC nerve in the project, rendered from the registry so it cannot drift from the served surface."
    format: markdown
    output: docs/public_api_reference.md
    covers: [nerve where visibility == PUBLIC]
    sections: [intent, expects, guarantees]

doc-guide architecture_map
    intent: "How this project is built, narrated around the three faculties of self-knowledge: structure, runtime state, and reasoning over the model."
    format: markdown
    output: docs/architecture_map.md
    covers: [nerve::submit_order]
    asserts: [nerve::submit_order.visibility == PUBLIC, nerve::submit_order.layer == APPLICATION]
    examples: []
    ---
    # Architecture map

    This project keeps an accurate, queryable, machine-readable model of itself. Read it through the three faculties of self-knowledge.

    ## Structure (proprioception)

    What the system is made of and how it is wired: modules, layers, kinds, and the dependency edges between them. The {{nerve::submit_order}} application service is the public entry point; it consumes the order domain model and returns a placement decision. The layer reachability matrix keeps the wiring honest — application code may reach the domain, never the other way round.

    ## Runtime state (interoception)

    How the system behaves versus how it declared it would: declared resource profiles checked against runtime metrics. Declare resource profiles on the nerves that have them and this section grows teeth; until then it states the contract the project intends to hold.

    ## Reasoning over the model (metacognition)

    Reasoning about the project's own model: impact analysis, extension-point guidance, and the drift check that keeps every reference in this map true. Because this guide is registry-bound and drift-gated, a change to a covered component that is not reflected here fails the build.
```

### 29.2 Why this shape

- **The `doc-ref` is maintenance-free.** `covers: [nerve where visibility == PUBLIC]` is a registry projection, not a hand-list: every new PUBLIC nerve appears in the reference on the next build, every removed one disappears, with zero edits to the map. `sections: [intent, expects, guarantees]` renders each nerve's intent and what it expects and guarantees; add `forbids` to the list to render the third part of its contract, what it must never do.
- **The `doc-guide` carries the narrative the registry can't.** Prose about *why* the project is shaped the way it is — but every claim about a named component is a `{{nerve::X}}` token resolved against the registry, and structural facts ride `asserts:` (which fail the build if they stop being true). Organize the prose around the **three faculties** so the reader gets the s0ma frame: **structure** (proprioception) = the wiring; **runtime state** (interoception) = declared-vs-actual behaviour; **reasoning** (metacognition) = impact/extension/drift over the model.
- **Drift is impossible in `main`.** Both declarations carry a transitive `content_hash`; `s0ma docs check-drift` (and the build at strict/release) re-render and byte-compare. The map is a registry projection the build refuses to let rot — that is what "load-bearing" means here.

Note the doc-guide body rules: **no raw fenced code blocks** (use `{{example::X}}` to embed a registered `example` instead — `PROSE_RAW_CODE_BLOCK` otherwise), and **no bare backtick identifiers** that look like references (wrap them as `{{nerve::X}}` or move the claim into `asserts:` — `POSSIBLE_UNRESOLVED_REFERENCE` otherwise). To embed runnable code in the guide, add an `example` declaration and reference it; see §17 and the documentation-subsystem guide.

### 29.3 Project-wide is the v1 default; per-feature is expressible too

The example above is **project-wide**: one `doc-ref` covering the whole project's PUBLIC surface, one architecture guide. This is the v1 default — it needs zero per-feature wiring and stays correct as features come and go. Scaffold this into the starter feature; grow the guide's prose as the project grows.

A **per-feature** app map (one reference per feature) is also expressible today, via the `module` predicate (added in 0.17.0, spec §4.12.1). Because a feature is *several* layer-modules (§25), enumerate the feature's modules in the filter:

```
doc-ref orders_feature_reference
    intent: "Per-feature reference: every PUBLIC nerve owned by the orders feature's modules."
    format: markdown
    output: docs/orders_feature_reference.md
    covers: [nerve where module in [orders_domain, orders_application]]
    sections: [intent]
```

> **Known limitation / future DSL ask.** There is no first-class *feature* dimension in the filter grammar — only `module`. So a per-feature map must hand-enumerate each feature's layer-modules (`module in [orders_domain, orders_application, …]`) and the list must be kept in step as the feature gains layers; there is no `where feature == orders` shorthand, and no way to auto-partition the project into one reference per feature. The clean fix is a first-class feature grouping dimension (a `feature:` field or a `group_by feature` clause) so per-feature maps need no manual module list. Until then, **project-wide is the recommended app map**; reach for the enumerated per-feature form only when a single project-wide reference has grown unwieldy (roughly: many features, dozens of PUBLIC nerves). (Historical note: an earlier friction log recorded that `module`-scoped `covers:` filters were inexpressible — that gap was closed in 0.17.0; the remaining gap is the *feature* grouping above, not `module` itself.)

### 29.4 Cross-references

- Documentation subsystem guide — `doc-ref` / `doc-guide` / `example`, the `covers:` filter forms, the `module` predicate, and the drift check.
- Spec §4.12 — normative doc-subsystem contract (`covers:` shapes §4.12.1, doc-guide body rules §4.12.2, drift §4.12.5).
- Patterns guide §17 — the source-registry `doc-ref` form and the doc subsystem at a glance.
- Patterns guide §25–28 — the layout, placement, naming, and boundary standards the app map documents.

## 30. Measuring self-knowledge (the `s0ma score` command)

`s0ma score [<project>]` turns a project's self-knowledge into **one visible number plus a per-faculty breakdown**, in human text and `--format json` from the same structured data. It is two things at once: the visible *impact* signal ("how much of this project is in the model, and how true is the model?") and a caller-pinned boundary standard. Project-selected `--mode` controls authoring diagnostics; caller-selected `--gate-mode` controls evaluation. `--gate` requires `--gate-mode`.

It introduces **no new analysis engine**: every signal is composed from surfaces the toolchain already computes (the parsed `.s0ma` modules, the dependency resolver's layer matrix, the release-mode doc/test coverage passes, the doc drift validator, the build manifest, and the `s0ma verify` drift classifier). It performs no network I/O.

### 30.1 The formula

The score names its three dimensions from the **three faculties of self-knowledge** (§1.3 of the PRD; structure / runtime state / reasoning). Each faculty is the mean of its measurable sub-metrics; the overall is the mean of the *available* faculties.

**Proprioception — structure ("what am I made of, how is it wired").** Mean of:

- **registration** — the built `.py` surface split into componentized, roster-adopted, and unknown populations. Only `componentized_pct` contributes to the score/gate; `roster_adopted_pct` and `combined_pct` make migration debt visible without rewarding it. Declared/auto-classified exempt files (`BOOTSTRAP`, `PACKAGE_MARKER`) are not counted.
- **layer compliance** — clean (100) iff the dependency resolver reports no `CROSS_LAYER_DEPENDENCY` (the layer reachability matrix, §13/§26).
- **structural-verifier clean** — clean (100) iff resolution surfaces no structural errors (cycles, unresolved `uses:`, undeclared targets, parse/semantic errors).

**Interoception — runtime state ("how am I behaving vs. how I declared").** This faculty is backed by runtime metrics checked against **declared resource profiles** — a `s0ma-core` runtime concept with **no `.s0ma` declaration surface**. A `.s0ma` project therefore has nothing the toolchain can measure here, so the faculty reports **`n/a — no resource profiles declared`** — honestly, never a misleading 0 or 100 — and is **excluded from the overall roll-up**. (This is the same honesty the app-map's interoception section states: declare resource profiles and this faculty grows teeth; until then it is `n/a`.)

**Metacognition — reasoning over the model ("reasoning about my own model").** The reasoning surfaces (impact, extension-point, doc/test queries) are trustworthy only if docs and tests track the code, so this faculty is the mean of:

- **doc-ref coverage** — the share of PUBLIC nerves selected by some `doc-ref`'s `covers:` filter (the release-mode `MISSING_PUBLIC_DOC_REF` contract, as a ratio).
- **declared test evidence** — the share of PUBLIC nerves targeted by an existing, non-empty `test` declaration. A `covered_by:` entry receives credit only when it resolves to such a declaration. This is static declared evidence, not a claim that the test ran.
- **drift-free** — clean (100) iff the doc validator reports no `DRIFT_DETECTED`. `n/a` when the project ships no doc declarations to drift.

**The overall roll-up** is the mean of the available faculty sub-scores only when every required population exists. Missing component, PUBLIC-nerve, documentation, or test-evidence populations create `gate.blocked` entries with `reason: "nothing_to_measure"`; they never disappear and leave a flattering partial score. Interoception remains an explicitly allowed `n/a` until the DSL has a measurable runtime-profile surface. The JSON's `gate.na_faculties` lists abstaining faculties.

### 30.2 The exempt set is LISTED, not just counted

The score enumerates the boundary doctrine's **closed four-category exempt set** (§28.2) with its actual members, so a reviewer sees *exactly* what sits outside s0ma rather than a bare count:

- **bootstrap module** — the single handwritten bootstrap module (the first `[tool.s0ma].bootstrap_files` entry).
- **bootstrap_files** — every other declared `[tool.s0ma].bootstrap_files` entry.
- **package_markers** — declared `[tool.s0ma].package_markers` plus every `.py` the built surface auto-classifies as a `PACKAGE_MARKER` (same classifier as `s0ma verify`).
- **@internal** — `INTERNAL`-visibility components, as `module::name` ids.

Anything in `.py` that is *not* one of these four is drift: `s0ma verify` surfaces it as `UNKNOWN`, and it counts against the project's surface-registration sub-score. The exempt set is the honest "here is what we deliberately did not put in the model" companion to the score.

Adoption exceptions are deliberately separate from that built-surface boundary. A
project may classify narrow inventories with
`[tool.s0ma].adoption_exempt = [{path_glob, category, reason}]`, but this local
authoring declaration never changes a pinned gate. Only a caller-provided
`s0ma-adoption-policy@1` document passed with `--adoption-policy` may waive its
matched adoption debt; the score lists every match and reports the canonical
`sha256:<hex>` policy digest. Release automation should also pass
`--expected-adoption-policy-hash` so a policy edit is an explicit review event.
Root-wide patterns—including a wildcard immediately beneath a configured source
root, test root, or build directory in a pure-legacy project—root escapes, and
matches against canonical `.s0ma` source or hash-bearing generated output are
refused; use an owned subtree such as `src/vendor/acme/**` or `vendor/acme/**`
with a non-empty reason.

### 30.3 Per-mode floors and `--gate`

The gate floor is selected only by the caller's explicit `--gate-mode`:

| Mode | Overall floor |
|---|---|
| `migration` | 50% |
| `dev` | 50% |
| `strict` | 75% |
| `release` | 90% |

Default behaviour is **report-only**: `gate.mode`, `gate.floor`, and `gate.passes` are `null`, with reason `mode not pinned by caller`. `--gate-mode release` computes release policy without changing authoring ergonomics; add `--gate` to make a blocked/below-floor result exit non-zero. `S0MA_VERIFY_CONTRACTS=0` is tolerated for report-only authoring but refused whenever a pinned gate is computed.

### 30.4 The flagship as the worked example

`s0ma score packages/s0ma-mcp --gate-mode release` scores the self-hosted MCP server against caller-pinned release policy: one bootstrap module, everything else componentized, clean layers/structure, and every PUBLIC surface connected to a real non-empty test declaration and documentation. The exempt set lists the bootstrap module, generated package marker, and `@internal` helpers. A fresh `s0ma new project` also scores high because the scaffold ships an app map and a mirrored test (§25, §29).

### 30.5 Cross-references

- Patterns guide §28 — the boundary doctrine whose exempt set the score enumerates.
- Patterns guide §29 — the app map, whose three-faculty structure the score mirrors.
- Patterns guide §13/§26 — the layer reachability matrix the proprioception sub-score reads.
- Quick reference — the `s0ma score` row and the `--mode` resolution rule.

---

## 31. Embodying physical hardware (ADR-003)

Hardware is not modeled from outside — it is **embodied**: brought inside the self-knowing boundary as ordinary components. There is **no new declaration type** — the existing organs carry it, and ADR-003 §1 records the decision (its revisit trigger is a verifier someday needing semantics the opaque metadata map cannot carry):

| Physical thing | Declaration shape |
|---|---|
| The attached device (board, bus peripheral, vehicle) | `integration` — SERVICE factory + `smoke_test_primary` liveness probe + manifest (§23) |
| Reading a sensor / driving an actuator | `nerve` — FUNCTION or SERVICE; the transport driver (serial, I2C) is an ADAPTER, abstracted per §9 |
| Physical value types and reading models | `cell kind: MODEL` — `dataclass_invariants:` carry the physical ranges (`"0.0 <= duty <= 1.0"`) |
| A watched envelope or resting baseline | `ganglion` — `observes:` + `priors:` + `on_anomaly:` (§11) |
| Physical facts (dimensions, power, composition) | `metadata:` under the `hw_*` vocabulary (31.1) |

### 31.1 The `hw_*` physical-facts vocabulary

ADR-003 §2 standardizes names for facts that apply to essentially all hardware. Every key is optional — **author what you know; omit what you don't; never invent**. Units live in the key name (house precedent: `latency_ms`), and the `hw_` prefix marks a key as vocabulary a tool may collect without a schema.

| Key | Type | Meaning |
|---|---|---|
| `hw_part` | str | Canonical part/model identity (e.g. `"LIS3DH"`, `"MG996R"`) |
| `hw_mounted` | str | Where on the body, free prose |
| `hw_length_mm` / `hw_width_mm` / `hw_height_mm` | float | Rough physical envelope |
| `hw_mass_g` | float | Mass |
| `hw_material` | str | Composition (e.g. `"3 mm plywood, PTFE glide tip"`) |
| `hw_range_of_motion_deg` | float | Articulated parts only: usable sweep |
| `hw_supply_voltage_v` | float | Nominal supply rail |
| `hw_current_ma_typical` | float | Typical current draw |
| `hw_current_ma_max` | float | Worst-case current draw (stall/peak) |

```
nerve read_light :: APPLICATION
    # ... required nerve fields elided ...
    metadata:
        hw_part: "ALS-PT19 phototransistor"
        hw_mounted: "top face, beside pad A8"
        hw_supply_voltage_v: 3.3
        hw_current_ma_typical: 0.3
```

Extension is by necessity: a second project needing a key amends ADR-003 §2. Project-specific facts keep using free metadata keys without the prefix.

### 31.2 Sense and actuator roles

Declare physical roles with the existing structural-attribute mechanism — `declares_attributes: [sense:light]`, `[actuator:servo]` — modality slugs under the two conventional namespaces. Where a role must be unique per body, use the ordinary attribute budgets (§16).

### 31.3 Runtime wiring (s0ma-core surfaces)

- **Declared physical bounds** ride `ResourceProfile`: `expected_max_current_ma` and `expected_max_temperature_c` are upper bounds, `expected_min_voltage_v` is a lower bound (supply sag). Breaches are INFLAMMATION, exactly like every other resource-profile deviation.
- **Ingestion is app-driven** — s0ma never reads hardware itself. `get_metrics_collector().record_physical("DoorServo", current_ma=520.0, profile=spec.resource_profile)` stores the latest gauges and immediately returns + publishes any crossing.
- **Push, not poll:** `s0ma.anomaly_stream.subscribe_runtime_anomalies(cb)` delivers NOCICEPTION (a live executable-contract violation, published before the raise) and INFLAMMATION crossings on the detecting call's thread — embodied hosts replace health-poll timers with one subscription.
- **Effect-checking contracts:** `postcondition(validator, "...", pass_args=True)` hands the validator `(result, *args, **kwargs)` — the shape for "the commanded displacement actually happened, per the rangefinder".
- **The self-model channel:** the `self_inspect` adapter wired in §10.4. `component <name>` is where an agent reads a part's `hw_*` facts and, when the host supplied a registry, whether the part is observed live; `describe` and `components <layer or module>` are the counts and names it orients from, and they carry no authored text.

### 31.4 Trust rules

Live sensor readings placed before an agent are **untrusted observational data** — a labeled channel of their own beside the authored self-model, parallel to ADR-002's `AUTHORED_DATA` rule. Readings never enter deterministic build artifacts, and learned baselines (calibration results) reach the model only by explicit re-authoring and rebuild (ADR-003 §6).

---

## 32. Retrofitting a codebase that predates s0ma

Every pattern above assumes a module is being **authored**. A codebase that already exists and already works is **converted** instead, and that path is one document rather than a section here: the repository keeps one home per subject, and a five-rung process copied into a patterns guide is two accounts that start disagreeing on the first change.

**The home** is `docs/guides/retrofit-existing-codebase.md`, served to an agent with no checkout as:

```
s0ma docs show doc:guide/retrofit-existing-codebase
```

**The first command is `s0ma adopt scan`.** It reads a tree of plain Python and reports what is in it, the `[tool.s0ma]` perimeter it would declare, a leaf-first conversion order with a proposed layer for each module, and the one command to run next. It never imports or runs the code it reads, and it writes nothing anywhere — no report file, no cache — so it costs nothing to run before anything has been decided. `s0ma adopt status` answers the same way at any later point, including on a tree that is not a s0ma project yet.

Three facts from that page change how the patterns above are applied mid-conversion:

- **Choose layers against the matrix on the first day, not the tenth** (§13). The build's reachability rules are narrower than the runtime's, so a layering that runs happily as plain Python can turn out to be unbuildable once converted. Discovering that one module at a time is the expensive way to discover it.
- **A draft is unfinished by construction.** `s0ma adopt draft` derives structure and never invents meaning: every field saying what something is *for* arrives as a `FIXME(adopt):` placeholder, and `s0ma check` refuses the module until a person has written them — in every mode, `migration` included.
- **The tests that already exist keep counting.** A converted module credits the suite that already covers it with `covered_by:` (§28), so a conversion does not have to be a test rewrite as well.

---

## 33. Authored lines stand on their own

An authored line — `intent`, `guarantees`, `invariants`, `schema` or `forbids` — stands on its own: in the present tense, it says what the part is for, what it promises, or what it must never do, to a reader who has only this file. It never names a plan, a milestone, a wave, a review item, a date, a person or a ruling: those belong to the changelog and to the planning record, and a reader who has only this file has neither. It may refer only to what ships with the code and is held by a gate — a requirement or an invariant by its id, an accepted architecture decision by its number, a contract revision, a section of the specification, a test through `covered_by:`, another part of the same project by name through `uses:` or `requires:` — and to nothing else.
