# ADR-007: Single Flat Build-Output Layout

**Status:** Accepted (Part 1: layout, M6a; Part 2: manifest + runtime-bridge integration + `s0ma migrate-layout`, M6b).
**Date:** 2026-04-28
**Context:** Feedback 5–6 plan, Milestone 6a — Single flat output layout + emitted `__init__.py` (drop legacy emission)
**References:** [feedback-5.5 lines 7–56](../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/s0ma-dsl-feedback-5.5.md) ("Output Layout / Runtime Import Contract Is Incoherent"), [feedback-5 MS 3–5](../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/s0ma-dsl-feedback-5.md), [feedback-6 CRIT-3](../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/s0ma-dsl-feedback-6.md), [ADR-005](ADR-005-project-discovery.md), [ADR-006](ADR-006-canonical-module-identity.md), `docs/s0ma-dsl-spec-v0.13.0.md` §4.14, `docs/migration_guide.md`.

---

## Decision

`s0ma build` emits a **single flat layout** rooted at the resolved project's `build_dir` (per ADR-005). The build directory contains exactly:

```
<build_dir>/
    __init__.py            # auto-emitted, marks the directory as a package
    <module>.py            # one per .s0ma module, named by canonical module identity (ADR-006)
    <module>.s0ma.json     # IR document
    <module>.s0ma.map      # source map
    # (M6b adds build.s0ma.json — see below)
```

Internal hash-based incremental cache state lives under a hidden `.s0ma.cache/` directory rooted at the build's input/output anchor. The cache is implementation detail — it is not on `sys.path`, not a Python package, and never appears under the build directory.

The legacy `__s0ma_cache__/` directory and the per-layer subdirectories (`presentation/`, `application/`, `domain/`, `infrastructure/`) are no longer emitted. A migration command (`s0ma migrate-layout`) lands in M6b to bring legacy consumer trees forward in one step.

**Stdout contract.** Every successful build prints exactly one import-idiom line:

```
Build complete. Import via: from <build_dir_basename> import <module>
```

The pre-M6a "import from the output directory, not from `__s0ma_cache__/`" note — which contradicted the runtime's actual behaviour — is gone.

## Context

Across **every milestone** of the feedback-5.5 consumer project (MS00–M14) the same class of bug recurred: stale shadows under `__s0ma_cache__/` silently overrode hand-imported modules under layer subdirs, or vice versa. Three properties of the legacy layout produced the bug pattern:

1. **Two-headed emission.** `s0ma build` wrote the same `.py` to *two* places — the layer subdir (so consumers could import `from presentation.foo import bar`) and `__s0ma_cache__/` (so the runtime import hook could find pre-built bytecode). Either head could go stale relative to the other.
2. **No canonical importable surface.** The layer subdirs had no `__init__.py`, so cross-module imports needed `__s0ma_cache__/` to be on `sys.path` — but the stdout note told users to import from the layer subdirs. The two halves of the contract disagreed in print.
3. **No manifest.** Nothing in the build output answered "what was emitted, in what order, with what hashes?" — the runtime had to walk the filesystem and guess.

Three options were enumerated in feedback-5.5:

- **Option A — Single flat layout + manifest.** Stop emitting two heads; emit one flat directory with an `__init__.py` and a `build.s0ma.json` manifest.
- **Option B — Keep layer subdirs as the canonical layout; emit `__init__.py` in each.** Preserves the "the build mirrors the architecture" framing but inherits two-headed-emission complexity and adds a sub-package per layer.
- **Option C — Drop file-based emission entirely; serve transpiled Python out of an in-memory cache.** Theoretically cleanest, but breaks `python -m`, `pytest`, IDEs, and every other tool that expects modules on disk.

## Rationale

### Why Option A wins

**A) The unite-code-and-information principle (Guiding Principle #1).** A single flat directory whose every file is a transpiled module is *itself* the description of what was built. Adding the manifest (M6b) makes the description machine-queryable. Option B still leaves layer subdirs that carry no information beyond what the IR already encodes; Option C deletes the disk presence the IDE / pytest world depends on.

**B) No silent failures (Guiding Principle #5).** Two-headed emission is the *original* silent failure: build A writes both heads, build B only updates one, runtime picks the stale one, tests pass locally and fail in CI. Option A removes the second head by construction. There is no `__s0ma_cache__/` to go stale.

**C) Hard-right-not-easy-wrong (Guiding Principle #4).** Option B was the easy-wrong path: it preserves consumer scripts that already say `from presentation.foo import bar`. We chose to break those at one specific upgrade boundary (with `s0ma migrate-layout` doing the legwork in M6b) rather than carry the two-headed contract forward indefinitely.

**D) Module identity and disk identity now agree (ADR-006).** ADR-006 made the canonical module identity the declared `module <name>`. The flat layout makes the on-disk filename equal that name unconditionally. There is no longer a layer-subdir step that introduces ambiguity between `application/foo.py` and `domain/foo.py` when both modules declare the same `module foo`.

### Why the cache moves to `.s0ma.cache/`

The pre-M6a `__s0ma_cache__/` did double duty: it was both the incremental-rebuild bookkeeping store *and* a runtime-importable shadow of the build output. M6a separates the two concerns:

- **Build output:** `<build_dir>/<module>.py` — importable, on `sys.path`, fully described by the upcoming `build.s0ma.json` manifest (M6b).
- **Internal cache:** `<anchor>/.s0ma.cache/` — hidden (leading dot keeps Python's importer from ever picking it up), holds source/IR/map/hash files for incremental rebuilds, never imported.

The leading-dot prefix is a deliberate choice over the legacy double-underscore: `__s0ma_cache__` *looks* like a Python dunder package and Python tooling will gladly walk into it. `.s0ma.cache` is unambiguously hidden state, the same way `.git` and `.mypy_cache` are.

### Why M6a defers the manifest to M6b

The manifest is load-bearing for the runtime bridge integration (M6b) but is independent of the layout decision. Splitting the work this way keeps each sub-agent's working set focused: M6a is "stop emitting two heads, start emitting one"; M6b is "the manifest becomes the new contract." The `__init__.py` already establishes the directory as a real Python package, so cross-module imports work in M6a — the manifest in M6b adds machine-queryable structure on top of an already-correct base.

### Why we keep the runtime bridge minimally compatible in M6a

M6a explicitly *does not* rewrite the runtime bridge — that lands in M6b. For M6a's window, transpiled modules remain importable through whatever path the consumer was already using (typically `sys.path.insert(0, build_dir)` or an equivalent in their bootstrap). The plan's scope statement is: "M6a's job is to keep imports working — even if minimally." We met that bar by emitting `__init__.py` so `sys.path.insert(0, build_dir); import <module>` works without further surgery.

### Why a manifest, not filesystem inspection (M6b)

The manifest is the canonical "what's in this build" answer. Three properties of the alternative — filesystem inspection — make it strictly worse:

1. **No first-class identity.** Filesystem inspection needs a heuristic for "is this file part of the build?" (file extension? naming convention? magic comment?). Every heuristic has edge cases — IDE temp files, partial writes, leftover artifacts from a previous build. The manifest names exactly what the build emitted; nothing else qualifies.
2. **No version stamping.** A `.py` on disk has no built-in record of which transpiler version produced it. Manifest's `transpiler_version` lets downstream tooling (verify, runtime bridge, future code-generation cousins) branch on capability without re-deriving from the file's content.
3. **No ordering.** M10 needs a topological import order so `register_*` calls fire in the right sequence. Filesystem inspection cannot derive ordering — it gets `dict_keys` and a heuristic. The manifest reserves a `topological_import_order` field (not yet populated; M10 lands it) so the ordering claim is durable, not regenerated each load.

The manifest also unites code and information about code (Guiding Principle #1 of the feedback 5–6 plan): the build directory is descriptive of what was emitted, *and* the description is machine-queryable in one canonical artifact.

### Why `s0ma-build-manifest@1` is intentional (M6b)

The schema string is a contract between the manifest writer and every downstream reader. Three properties of `@1` are deliberate:

- **Versioned.** A reader that only knows how to parse `@1` must reject `@2` rather than guess. The version string makes that contract explicit at the top of the file.
- **Additive over time.** M10 extends the schema with `topological_import_order`; M12 may add `external_content_files`. Both extensions live under `@1` because readers can branch on optional fields without breaking. The version increments only for *breaking* changes — renames, removals, semantic shifts.
- **Self-describing.** The string `s0ma-build-manifest@1` carries enough context that a foreign tool (e.g., a CI artifact validator) can recognise the manifest by string match alone. Compared to a bare integer version, the prefix is load-bearing — it disambiguates from any other `@1` schema in the ecosystem.

### Why `s0ma migrate-layout` exists (M6b)

The 0.11 → 0.12 layout change is breaking by design — preserving layer-prefixed imports forward would carry the legacy stale-cache failure mode indefinitely. `s0ma migrate-layout` exists so that "breaking" is a one-shot inconvenience, not a per-project surgical exercise:

- It encapsulates the legacy-layout recogniser (the four well-known layer subdirs, `__s0ma_cache__/` at any depth) in one place. Future cleanups can extend the recogniser without consumers needing to know.
- It is idempotent — safe to run unconditionally in CI before each build. A no-op invocation reports "nothing to clean" and still re-runs the build, which is harmless on an already-correct tree.
- It is defensive: the `_looks_like_s0ma_build` guard refuses to delete a directory that does not look like a s0ma build. Pointing the command at the wrong path produces a remediation message, not data loss.

## Consequences

- **Breaking change for consumer projects.** Any consumer that imported `from presentation.foo import bar` (or any other layer-prefixed path) breaks at upgrade. `s0ma migrate-layout` (M6b) ships as the one-shot cleanup; `docs/migration_guide.md` ("0.11.0 → 0.12.0: Output layout migration") carries the full recipe.
- **CI scripts that grepped `__s0ma_cache__/` paths in build logs need updating.** The directory is gone. The replacement is the `Build complete. Import via: …` line, which is parseable as well.
- **`s0ma inspect` reads the new cache location.** Inspecting a `.s0ma` source falls back to `.s0ma.cache/<module>.s0ma.json` first, then legacy `__s0ma_cache__/<module>.s0ma.json` for backwards-compat reads (so inspecting a pre-M6a tree still works during migration). It never *writes* to the legacy path.
- **`s0ma transpile`'s subdirectory-preservation behaviour is gone.** Pre-M6a, `s0ma transpile dir/ -o out/` mirrored `dir/`'s subtree into `out/`. M6a flattens: every transpiled module lands at `out/<module>.py`. The subdirectory mirror was a holdover from the layer-subdir era and never matched the canonical-module-identity model.
- **The build directory must not collide with consumer source.** Default project layout (per ADR-005) is `<project_name>_build/`, sibling to `src/`. Consumers who previously built into `src/` itself need to retarget — `s0ma migrate-layout` (M6b) does this automatically.
- **The flat layout enables M10 (topological import order) cleanly.** With a single namespace and a single emit pass, M10's manifest extension can record exactly one ordered list — no per-layer interleaving to reason about.

## Alternatives Considered

1. **Option B — Layer subdirs with `__init__.py` per layer.** Rejected: preserves two-headed-emission complexity (still need `__s0ma_cache__/` for the runtime hook), forces consumer code to know about layer-prefixed import paths, and makes the on-disk layout disagree with the canonical module identity from ADR-006.
2. **Option C — In-memory module serving only.** Rejected: breaks every disk-based tool in the Python ecosystem (pytest, IDEs, `python -m`, `python -c "import …"`). The cost of disk emission is one `__init__.py` and a directory walk; the cost of *not* emitting is the entire IDE / pytest contract.
3. **Keep `__s0ma_cache__/` as a build-output mirror "for backwards compatibility".** Rejected: the legacy stale-cache failure mode lives precisely in this mirror. The hard-right path is to delete the second head, not to preserve the source of every silent failure across feedback 5–6.
4. **Use `__build__/` instead of `<project_name>_build/`.** Rejected: collides with PEP 517 build backends' conventional `_build/` directory; ADR-005 already standardised the `<project_name>_build/` form via `[tool.s0ma].build_dir`.
5. **Defer all of M6 to a single milestone.** Rejected: working-set size for one sub-agent. M6a (layout) and M6b (manifest + runtime bridge + migrate-layout) each fit a focused agent context; together they would exceed it.

## Forward pointers

- **M6b** (now landed) finalised this ADR's status to **Accepted** by adding the `build.s0ma.json` manifest, the runtime-bridge integration that reads it (`import_modules_from_manifest`), and the `s0ma migrate-layout` subcommand. The build directory is now descriptive of itself both structurally (M6a) and via metadata (M6b).
- **M10** extends the M6b manifest with `topological_import_order`. The flat layout makes that list a single sequence rather than a per-layer interleaving. Additive under `s0ma-build-manifest@1`.
- **M12** may extend the manifest with `external_content_files` for embedded-content modules. Additive under `s0ma-build-manifest@1`.
