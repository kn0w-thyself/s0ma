# ADR-004: Transpiler as Separate Sister Project

**Status:** **Superseded (2026-08-28)** — reversed by the 0.5.0 monorepo consolidation
(`CHANGELOG.md`, `[0.5.0] — 2026-06-09`, "the consolidation release"). The two repositories
merged into one uv workspace; there is no `kn0wthyself/s0ma-dsl` repo and no
`pip install -e ../s0ma` step. Nothing below is operative — it is retained for the
rationale, which is the reason ADRs are append-only. **Current truth:** root `README.md`
and `CONTRIBUTING.md` for the workspace layout and dev setup;
`references/s0ma-prd.md` NFR-8 / INV-4 for the package split, licensing, and lockstep
versioning. No successor ADR was written: the consolidation was a repository decision taken
outside this ADR series and is recorded in the changelog.
**Date:** 2026-03-08
**Context:** Milestone 2 — Architecture Decisions & Spec Traceability
**References:** PRD §2.1.2 (component map), §2.1.3 (relationship to s0ma framework), §2.1.4 (dependency stack)

---

## Decision

The s0ma DSL transpiler is a **separate sister project** (`kn0wthyself/s0ma-dsl/`) alongside the s0ma framework (`kn0wthyself/s0ma/`), not a subpackage within it. It depends on `s0ma-framework` via editable install (`pip install -e ../s0ma`).

## Context

The transpiler needs to:
- Import from `s0ma.decorators`, `s0ma.models`, `s0ma.registry`, and `s0ma.hook`
- Use `@component` decorators on its own modules (dogfooding)
- Add `lark` as a dependency for parser generation
- Be independently versioned and releasable
- Not impose its dependencies on plain s0ma users

## Rationale

### The transpiler targets s0ma, not extends it

The relationship is analogous to TypeScript targeting JavaScript: the transpiler produces artifacts that the runtime consumes, but the runtime does not need the transpiler to function. Users who write plain `@component` Python should not need `s0ma-dsl` or Lark installed.

### Lark should not be a core s0ma dependency

Lark is a parser generator needed only for DSL compilation. Adding it to `s0ma-framework`'s dependencies would increase the install footprint for all users — including those who never write `.s0ma` files. Keeping it in the transpiler's own `pyproject.toml` isolates this cost.

### Independent versioning

The transpiler and framework have different release cadences. The framework might release a patch for a registry bug while the transpiler is mid-milestone. Independent `pyproject.toml` files enable independent versioning.

### Follows the kn0wthyself ecosystem pattern

ax0n and st3mcell are already sister projects that depend on `s0ma-framework`. The transpiler follows the same pattern:

```
kn0wthyself/
├── s0ma/          # Framework
├── s0ma-dsl/      # Transpiler (THIS project)
├── ax0n/          # Agent
└── st3mcell/      # Platform
```

All are clients of the s0ma framework, not extensions of its internal package structure.

### Editable install for development

During development, `pip install -e ../s0ma` ensures the transpiler always picks up the latest framework changes, including runtime expansion work delivered as PRs to the s0ma repo. This is the standard workflow for co-developing sister packages.

### Dogfooding is not self-compilation

The transpiler uses `@component` decorators from the s0ma runtime to describe itself. It does not need to compile itself with the DSL — it needs to describe itself using the same registration primitives it generates for other projects. The bootstrap paradox (the transpiler cannot transpile itself during its own loading) is a non-issue because dogfooding operates at the decorator level, not the DSL level.

## Consequences

- `s0ma-dsl` has its own `pyproject.toml` with `s0ma-framework` and `lark` as dependencies
- Runtime expansion work (new registration functions, registry schema changes, import hook modifications) is delivered as PRs to the s0ma repo
- The transpiler repo contains a `runtime_bridge/` adapter for framework integration
- Development setup requires two editable installs: `pip install -e ../s0ma && pip install -e .`
- The transpiler package is `s0ma-dsl` (import as `s0ma_dsl`)

## Alternatives Considered

1. **Subpackage of s0ma (`s0ma.dsl.*`)** — rejected because it would make Lark a transitive dependency for all s0ma users and would complicate independent versioning.
2. **Fully independent project (no sister relationship)** — rejected because the tight co-development workflow (runtime expansion PRs, editable installs) benefits from repository proximity.
3. **Monorepo with workspace** — considered but rejected for simplicity; the sister project pattern is already established in the kn0wthyself ecosystem.
