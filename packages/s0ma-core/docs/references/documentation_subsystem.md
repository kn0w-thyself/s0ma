# Documentation Subsystem — core's runtime symbols

**The teaching moved.** How the documentation subsystem works — the three
declarations, the deterministic render, the drift gate, what the runtime lets
you ask and where each answer is served — is now one page, in the corpus that
is generated and gated:
[the documentation subsystem](../../../../docs/documentation-subsystem.md).
Read that first. This file is what is left after that move: the core symbols
that no generated page names, kept here because dropping them would lose them
and writing them there would put them in two places.

This page was for most of its life a transitional anchor whose banner promised
it would be regenerated once the emitter landed. The emitter landed and the
regeneration did not, and G3 withdrew the promise rather than keep making it.
The roster below was verified against the code at 0.18.1 at that time. It is
hand-maintained, nothing gates it, and it is the last of this file that is:
every symbol a generated surface *does* carry has been removed from it and is
listed at the bottom with where it now lives.

The implementation plan this subsystem was built from is archived at
[`documentation_subsystem_implementation_plan.md`](../../../../docs/archive/pre-monorepo/s0ma-core/plans/documentation_subsystem_implementation_plan.md).

---

## Import-hook marker attributes

The s0ma-dsl transpiler emits three module-level marker attributes on
generated `.py` output. Each is a contract between the transpiler and the
s0ma-core import hook: the marker advertises the names of the
documentation-subsystem registrations that the module is *expected* to install
into the registry by the time its module body finishes executing.

| Attribute | Registration kind | Value |
|---|---|---|
| `__s0ma_doc_ref__` | `doc-ref` | Iterable of `str` names (a bare `str` is treated as a single name) |
| `__s0ma_doc_guide__` | `doc-guide` | Iterable of `str` names |
| `__s0ma_example__` | `example` | Iterable of `str` names |

The names are the same keys passed to `s0ma.register_doc_ref` /
`s0ma.register_doc_guide` / `s0ma.register_example`. After the module body
runs, the import hook looks each name up via `ComponentRegistry.get_doc_ref` /
`get_doc_guide` / `get_example`. Any marker entry that does not resolve to a
registration raises `UnregisteredComponentError` in strict mode and warns in
lenient mode.

The attribute *names* are exposed as public constants on `s0ma.import_hook`
for the DSL emitter to reference directly rather than hard-coding strings:

- `s0ma.import_hook.DOC_REF_MARKER_ATTR`
- `s0ma.import_hook.DOC_GUIDE_MARKER_ATTR`
- `s0ma.import_hook.EXAMPLE_MARKER_ATTR`

*Why advertise names alongside the registration call* is answered in the
[documentation subsystem](../../../../docs/documentation-subsystem.md) page,
under what the runtime holds.

---

## Registration-function signatures

The three calls are served capabilities and appear in
[what s0ma can do](../../../../docs/reference/surfaces-index.md); their
keyword sets are not, and are here. All accept keyword-only arguments and
return the stored registration. Each raises
`s0ma.exceptions.RegistrationError` on a duplicate name unless
`idempotent=True`, and `ValueError` on invalid input.

- `s0ma.register_doc_ref(name, module, intent, format, output, covers, sections, content_hash, source_span, idempotent)`
- `s0ma.register_doc_guide(name, module, intent, format, output, covers, asserts, examples, body, content_hash, source_span, idempotent)`
- `s0ma.register_example(name, module, intent, demonstrates, runs_in, body, source_span, idempotent)`

---

## `RegistrySnapshot` extensions

| Symbol | Purpose |
|---|---|
| `RegistrySnapshot.doc_refs` | `dict[str, DocRefRegistration]` populated from the registration store. |
| `RegistrySnapshot.doc_guides` | `dict[str, DocGuideRegistration]`. |
| `RegistrySnapshot.examples` | `dict[str, ExampleRegistration]`. |
| `RegistrySnapshot.examples_for(ref)` | Returns the `ExampleRegistration`s whose `demonstrates` matches the target. Accepts either an `EntityRef` or a `"module::name"` / bare `"name"` string shortcut. |
| `RegistrySnapshot.docs_for(ref)` | Returns a `DocsForResult` with separate `.refs` / `.guides` lists. Doc-guide matches use name+module; doc-ref matches use textual containment against each filter's `raw` source (full predicate evaluation is `s0ma-dsl`-side). |
| `DocsForResult` | Structured wrapper around `refs` / `guides` lists. Carries `to_dict()` and `is_empty()`. |

`to_dict()` / `to_json()` emit the `doc_refs` / `doc_guides` / `examples` keys
only when the corresponding stores are non-empty, preserving existing snapshot
consumers' schema until the subsystem is in use.

---

## `SelfModelInterface` extensions

| Method | Purpose |
|---|---|
| `describe_docs()` | Registry-wide natural-language overview of every registered doc-ref, doc-guide, and example. |
| `describe_doc(name)` | Doc-ref / doc-guide detail lookup by registry key. Returns an informational "not found" string rather than raising. |
| `get_docs_for_component(name)` | Reverse-index surface over `RegistrySnapshot.docs_for(...)`. |
| `get_examples_for_component(name)` | Reverse-index surface over `RegistrySnapshot.examples_for(...)`. |
| `get_drift_status(*, transpiler_version="unknown")` | Transitive drift report. Recomputes every stored content hash via `s0ma.hashing.content_hash` and lists divergences. |

Impact analysis surfaces `affected_docs` and `affected_examples` when the
reverse indices return matches. These two are module-level functions rather
than methods on the interface — `s0ma.self_model.analyzers`
`compute_impact_analysis(...)` computes the `ImpactReport` (both fields are
`list[str]` on it) and `s0ma.self_model.formatters` `format_impact_report(...)`
renders the sections. An earlier version of this page listed them directly
under the interface's methods, where a reader would reasonably have looked for
them on `SelfModelInterface` and not found them.

---

## Example execution (`s0ma.examples`)

The five classes below are registered components and appear in
[the component index](../../../../docs/architecture/component-index.md); what
is here is the rest of the module — the functions, the constants and the
pytest plugin, none of which any generated page names.

| Symbol | Purpose |
|---|---|
| `run_subprocess_with_timeout(...)` | Cross-platform subprocess runner that represents a timeout as a first-class field rather than an exception. Returns a `TimeoutResult`. |
| `run_all_examples(registry, *, timeout_seconds)` | Module-level convenience wrapper over `ExampleRunner`. |
| `DEFAULT_TIMEOUT_SECONDS = 30` | Per-example default timeout. |
| `INTEGRATION_CMD_ENV_VAR = "S0MA_INTEGRATION_CMD"` | Env var consulted by the `integration` dispatcher. |
| `ExampleTimeoutError` | Stringified onto `ExampleResult.error`; never propagated to callers. |
| Pytest plugin | Entry-point `s0ma_examples` on `pytest11`. Opt-in via `pytest --s0ma-examples`; `s0ma_example_timeout` ini key. Items surface as `s0ma-example::<name>`. |

`ExampleRunner` exposes `run()` / `run_all()` / `discover()` and takes
`(registry, *, timeout_seconds, dispatcher)`. `ExampleResult` is frozen and
carries `passed`, `duration_ms`, `stdout`, `stderr`, `returncode`,
`timed_out`, `error` and `summary()`. `ExampleDispatcher` routes by `runs_in`
to the `standalone` / `pytest` / `integration` handlers, and `DispatchOutcome`
pairs a `TimeoutResult` with the effective mode.

---

## REST response models

The five endpoints themselves are served capabilities and are listed in
[what s0ma can do](../../../../docs/reference/surfaces-index.md). Their
Pydantic response models are not, and are here: `DocListResponse`,
`DocDetailResponse`, `ExampleListResponse`, `ExampleDetailResponse`,
`DriftResponse`, `DriftEntry`. `GET /self/doc/{name}` returns 404 on a miss
and its response carries `kind` to disambiguate a doc-ref from a doc-guide;
`GET /self/drift` accepts an optional `?transpiler_version=` query parameter.
The whole family requires the `[api]` extra, as core's own MCP resources —
listed in [the servers s0ma answers agents on](../../../../docs/reference/mcp.md)
— require the `[mcp]` one.

---

## Agent rules

Added to [the user guide](../s0ma_user_guide.md) Appendix C.10:

- **A-8 (VERIFIED)** — When modifying a component, check
  `SelfModelInterface.get_docs_for_component(name)` and
  `get_examples_for_component(name)`. Update affected docs and examples
  atomically in the same change.
- **A-9 (ENFORCED)** — Never embed a raw code sample in a doc-guide body.
  Always reference a registered example via `{{example::<name>}}`.

---

## What left this page, and where it went

| Fact | Now written down at |
|---|---|
| What `doc-ref`, `doc-guide` and `example` are, and when to reach for each | [the learning collection](../../../../docs/learn/glossary.md) |
| The three registration calls as served capabilities | [what s0ma can do](../../../../docs/reference/surfaces-index.md) |
| The five REST endpoints | [what s0ma can do](../../../../docs/reference/surfaces-index.md) |
| The MCP resources and the `get_examples_for` tool | [the servers s0ma answers agents on](../../../../docs/reference/mcp.md) |
| `content_hash`, `canonicalize`, `HASH_ALGORITHM_VERSION` | [what s0ma can do](../../../../docs/reference/surfaces-index.md) |
| `ExampleRunner`, `ExampleResult`, `ExampleDispatcher`, `DispatchOutcome`, `TimeoutResult` | [the component index](../../../../docs/architecture/component-index.md) |
| What the transitive hash covers and why | [the documentation subsystem](../../../../docs/documentation-subsystem.md) |
| Why the markers are load-bearing | [the documentation subsystem](../../../../docs/documentation-subsystem.md) |
| The contract core's registrations have to hold | [`s0ma-core-spec-v0.19.1.md`](../s0ma-core-spec-v0.19.1.md) §7 |
