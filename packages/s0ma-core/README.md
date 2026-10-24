# s0ma-core

**Software that cannot exist without understanding itself.**

s0ma is a Python framework for *software self-knowledge* — the ability of a software system to maintain an accurate, queryable model of itself: its structure, its runtime state, and the reasoning over that model. Self-knowledge spans three faculties — **proprioception** (structure), **interoception** (runtime state), and **metacognition** (reasoning over the model). Unlike conventional documentation, the self-model is **load-bearing**: remove it and the system fails to start. Every component must register itself as a condition of existing.

`s0ma-core` is the runtime foundation the rest of the toolchain stands on: the registry every component registers into, the verification engine that compares that model against the real code, and the surfaces that answer questions from it — Python, an optional REST API, and an optional MCP server an application can offer about itself. It needs none of the other three packages.

## Where it sits

Four distributions ship together at one version, and dependencies only ever point down the stack (PRD INV-6):

[`s0ma-mcp`](../s0ma-mcp) · [`s0ma-studi0`](../s0ma-studi0) → [`s0ma-dsl`](../s0ma-dsl) → **`s0ma-core`**

Core sits at the bottom with no hard runtime dependency on any of them, and it is open: **`s0ma-core` is Apache-2.0**, as are `s0ma-dsl`, `s0ma-mcp` and `s0ma-studi0`. What each distribution contains, and the license each one declares, is in [the distributions s0ma ships](../../docs/reference/packages.md).

## Install

s0ma is not on PyPI yet, so `pip install s0ma-core` will not work: all four packages are published there from the first release cut of the public repository, and until that lands the way in is the repository itself. That route is written down once, in the [root README's "Install" section](../../README.md#install) — working inside a checkout, or building the wheels and installing them into a project of your own, with this package's optional extras (`[api]`, `[mcp]`, `[all]`) — and [getting started](../../docs/getting-started.md#1-create-a-real-project) is the journey to walk once the `s0ma` command runs.

## What it feels like

Every component says what it is as a condition of being registered, and the framework can then be asked what exists and whether it is still true:

```python
from s0ma import initialize, verify
from s0ma.decorators import component, internal
from s0ma.types import ComponentKind, Layer

registry = initialize(project_root="./my_project")

@component(
    name="TaskService",
    kind=ComponentKind.SERVICE,
    layer=Layer.APPLICATION,
    intent="Manages task lifecycle: creation, assignment, and completion",
    dependencies=["StorageAdapter"],
)
class TaskService:
    def create_task(self, title: str) -> dict:
        return {"title": title, "status": "pending"}

@internal                      # a private helper, deliberately unregistered
def _validate_title(title: str) -> bool:
    return len(title) > 0

print(registry.snapshot().describe())   # what the system says it is
report = verify(registry)               # does that match the code?
assert report.passed, report.describe()
```

`verify` runs four verifiers and reports structural drift between declarations and source, how much of each declared contract is executable, runtime metrics against declared resource profiles, and dead code. `report.explain_for_llm()` renders the same findings with fix suggestions.

An application can also carry its own self-knowledge at runtime. After a build, core verifies and loads the emitted self-context without needing the DSL package:

```python
from s0ma.runtime import self_context, self_inspect_adapter

context = self_context("build/build.s0ma.json")     # context["card"] is bounded prompt text
adapter = self_inspect_adapter("build/build.s0ma.json")
agent_host.register_tool(adapter.tool_spec, adapter.handle)
```

The adapter answers `describe`, `component <name>`, `dependencies <name>`, `dependents <name>` and `impact <name>`; a name may be a component id, a bare name, or an operation the component provides. Authored intent lines are quoted project data, never host instructions (see [ADR-002](../../docs/adr/ADR-002-self-context-authored-data-boundary.md)).

## Documentation

[**The map of record**](../../docs/README.md) lists every document this repository keeps, what it is for, and which check keeps it honest. The pages that describe this package:

- [Component index](../../docs/architecture/component-index.md) — every component s0ma registers about itself, read out of the registry at build time.
- [What s0ma can do](../../docs/reference/surfaces-index.md) — every capability on every channel, including core's `/self/*` REST routes and its Python interface.
- [The MCP servers](../../docs/reference/mcp.md) — what the optional read-only introspection server serves, beside the authoring server it is often confused with.
- [Concepts index](../../docs/reference/concepts-index.md) and the [glossary](../../docs/learn/glossary.md) — the vocabulary the rest of the documentation leans on.
- [s0ma User Guide](docs/s0ma_user_guide.md) — the long-form guide to using the toolchain.
- [Embodied survival card](docs/embodied_survival_card.md) — for an agent operating a *running* s0ma system: a body, a service.
- [PRD](../../references/s0ma-prd.md) — purpose, principles, and binding invariants. Read it before changing what s0ma *is*.

In a terminal, `s0ma docs` opens the same map and `s0ma docs show <topic>` answers one question from it.

## Releases

The root [`CHANGELOG.md`](../../CHANGELOG.md) is the single record of what each release contains, canonical from 0.5.0 onward; this package's own [`CHANGELOG.md`](CHANGELOG.md) holds the pre-monorepo history through 0.4.0. All four packages are versioned in lockstep.

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details. The rest of the toolchain shares it: `s0ma-dsl`, `s0ma-mcp` and `s0ma-studi0` are Apache-2.0 too, each with its own `LICENSE`.

---

*Project s0ma — Know Thyself (kn0wthyself)*
*Software Self-Knowledge Research Program*
