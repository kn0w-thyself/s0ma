# ADR-002: Runtime Expansion & Backwards Compatibility

**Status:** Accepted
**Date:** 2026-03-08
**Context:** Milestone 2 — Architecture Decisions & Spec Traceability
**References:** PRD NFR-07 (backward compatibility), §2.7 (runtime expansion), §2.7.4 (compatibility boundary), DSL Spec §2.2

---

## Decision

1. **The runtime expansion is strictly additive.** No existing s0ma APIs are modified or removed. The existing path (`.py` with manual `@component` decorators → import hook → registry) continues to work unchanged.

2. **Mixed `.s0ma` and `.py` coexistence is supported.** Projects can freely mix transpiled `.s0ma` modules and handwritten `.py` modules with `@component` decorators. Both registration paths feed the same `ComponentRegistry`.

3. **Runtime expansion work is delivered as PRs to the s0ma repo.** The transpiler repo contains a `runtime_bridge/` adapter layer. This two-repo workflow ensures runtime improvements benefit all s0ma consumers (ax0n, st3mcell, etc.).

4. **New registration functions are added alongside existing ones.** `register_module()`, `register_constant()`, `register_type()`, `register_relationship()`, and `register_test()` are new functions that do not alter existing `@component` or `registry.register()` behavior.

## Context

The DSL introduces declaration types that the current s0ma runtime does not fully support: module-level metadata, relationship edges, test registrations, and cell registrations for constants/types. The transpiler's emitted Python must be loadable by the runtime.

The key tension: the DSL needs richer registration capabilities, but existing s0ma users who write plain `@component` Python should not need `s0ma-dsl` or Lark installed. The transpiler is an optional development tool, not a runtime dependency.

## Rationale

### Why additive-only

Breaking existing APIs would force all s0ma consumers (ax0n, st3mcell) to update simultaneously with the transpiler. Since these are independent projects with their own release cycles, backwards compatibility is essential.

The DSL spec §2.2 explicitly states: "The DSL does not replace the s0ma runtime." The runtime's core — registry, import hook, contract system, anomaly detection — remains sound. The expansion adds new capabilities without disturbing existing ones.

### Why mixed coexistence

Real-world adoption requires gradual migration. A project might convert some modules to `.s0ma` while keeping others as `.py`. Both must coexist in the same registry without conflicts.

The registry stores components by canonical ID. A component registered via `@component` decorator and one registered via transpiled code are indistinguishable once registered — they both produce `ComponentSpec` entries.

### Why two-repo workflow

The transpiler is a development tool. The registration functions it targets are framework capabilities. Putting `register_module()` in the transpiler repo would mean ax0n could not use it without depending on `s0ma-dsl`. Putting it in the s0ma repo makes it available to all consumers.

The `runtime_bridge/registration.py` adapter in the transpiler repo handles any translation between the transpiler's internal model and the framework's registration API. This keeps the boundary clean.

### Registry schema expansion

The `ComponentRegistry` needs new storage for:
- Module metadata (layer, version, intent, exports, content_hash)
- Relationship edges (source, target, relation, coupling, carries, intent, origin)
- Test registrations (test ID, validated component IDs)
- Content hashes for change detection

These are new tables/collections, not modifications to existing ones.

### Import hook expansion

The import hook needs three changes:
1. Discover `.s0ma` files alongside `.py` files
2. Trigger on-the-fly transpilation with content-hash caching
3. Recognize `register_constant()` and `register_type()` as valid registrations

When both `.s0ma` and `.py` exist for the same module, `.s0ma` takes precedence (it is the authoritative source).

## Consequences

- Existing s0ma Python code works without any changes (NFR-07 satisfied).
- The transpiler can target stable registration APIs in the framework.
- Runtime expansion can be tested independently of the transpiler.
- Mixed projects require clear documentation about which file is authoritative.

## Alternatives Considered

1. **Transpiler-only registration (no framework changes)** — rejected because it would make the transpiler a runtime dependency and prevent other consumers from using the new capabilities.
2. **Replace existing APIs** — rejected because it would break ax0n, st3mcell, and any existing s0ma project.
3. **Monorepo (transpiler inside s0ma)** — rejected; see ADR-004.
