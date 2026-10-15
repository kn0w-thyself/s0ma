# ADR-006: `module <name>` is the Canonical Module Identity

**Status:** Accepted
**Date:** 2026-04-28
**Context:** Feedback 5–6 plan, Milestone 4 — Module name as canonical cache key + stem mismatch validation
**References:** feedback-6 CRIT-2 (file-stem vs module-name silent broken imports), feedback-6 MS 11 (renamed `integration.s0ma` to `google_calendar_integration.s0ma` to work around the bug), DSL Spec §4.1 (Module Declaration), `docs/migration_guide.md` ("0.11.0 → 0.12.0: file-stem alignment")

---

## Decision

The `module <name>` declaration is the **canonical identity** of every s0ma module. The transpiler derives the cache key, the emitted `.py` / `.s0ma.json` / `.s0ma.map` filenames, and the import path resolved by `uses:` references from `module.name` — never from the source file's stem. The intra-module validator enforces that the source filename's stem equals `module.name` via the new `MODULE_NAME_STEM_MISMATCH` error code. The check fires at `s0ma check` time at error severity in **every** strictness mode (migration, dev, strict, release) — divergence is a hard correctness invariant, not a stylistic preference.

## Context

The transpiler historically used `source_path.stem` in two places: (a) as the cache key under `__s0ma_cache__/`, and (b) as the basis for the emitted Python filename. The `.s0ma` source independently declared `module <name>`, and that name was the symbol resolved when another module wrote `uses: [<name>.X]`.

When the two diverged — e.g. a file named `integration.s0ma` declaring `module google_calendar_integration` — the build silently produced two artifacts under different names:

- `integration.py` (cache, named after the file stem), and
- `from google_calendar_integration import X` resolved by every `uses:` consumer (named after the module).

There was no error at `s0ma check` or `s0ma build` time. The failure surfaced only at `s0ma test` time, as a cascade of `ModuleNotFoundError` exceptions whose root cause was invisible to the author. Feedback-6 documented one consumer who renamed `integration.s0ma` → `google_calendar_integration.s0ma` to work around the bug; the transpiler never told them what was wrong.

## Rationale

### Why `module <name>` is canonical, not the file stem

The IR is the source of truth for what a module *is*. The `module` declaration carries the layer, version, intent, exports, requires, uses, and tags — the entire identity of the module. The file stem carries one fact: where the bytes live on disk. When the two disagree, the IR is what every other declaration in every other file sees: cross-module `uses:` resolves against `module.name`, every `.s0ma.json` IR document records `module.name` as the module's identity, the registry registers each component under `module.name::Component`. Picking the file stem as the cache key broke the symmetry — the cache and the import resolver disagreed about which fact identified a module.

The fix is to pick *one* canonical identity and propagate it everywhere. We picked `module.name` because every consumer of the IR already does. The cache, the output filenames, and the source filename now all derive from the same fact.

### Why enforce alignment rather than allow divergence

Once the cache key is `module.name`, the source filename becomes free to vary independently. We considered allowing it: a file named `integration.s0ma` with `module google_calendar_integration` would simply emit `google_calendar_integration.py` and the imports would resolve. This is the easy path and it was tempting.

We rejected it. Greppability suffers immediately — searching for `integration.s0ma` from a stack trace would not find the module that owns it; searching for `google_calendar_integration` from an `import` statement would not find the source. Tooling that maps tracebacks to source lines (the source-map subsystem) would have to traverse an extra layer of indirection. Most importantly, the filesystem layout and the IR identity would visibly disagree to any human reading the repo — the kind of low-grade incoherence that erodes trust in the model.

The hard right path is to make the filesystem and the IR mirror each other. Authors get one rule (`<module_name>.s0ma`); readers get one mental model (the file is the module).

### Why error severity in every mode

`MODULE_NAME_STEM_MISMATCH` is a structural correctness invariant, not a stylistic warning. There is no benign case: a divergent stem/name pair always corresponds to either a typo the author wants to catch or a rename the author started but did not finish. Either way, the build should fail loudly at the earliest possible step. Migration mode normally relaxes hygiene rules so authors can adopt s0ma incrementally — but this rule does not protect hygiene, it protects correctness, so migration mode gets the same severity as release.

### Why catch it at `s0ma check` time

The validator runs before emission. By failing the check pass, we ensure no `.py` ever reaches disk under an incoherent name. The previous bug surfaced at `s0ma test` time; the new check fires at `s0ma check` time, which is the earliest authoring step. The fix follows the no-silent-failures principle that runs through the feedback 5–6 plan.

## Consequences

- **Every existing `.s0ma` file in every consumer project** must align its stem with its `module <name>` declaration. The 0.11.0 → 0.12.0 migration guide warns about this; consumers who previously got away with divergence (because the cache key was the stem and tests never exercised cross-module imports) will see the new error on their first `s0ma check` after upgrading. Remediation is mechanical: rename the file, or rename the declaration.
- **The cache key derives from the parsed module name**, via `s0ma_dsl.cache.extract_module_name(source_path)`. The extractor uses a lightweight regex against the source's leading lines so the cache lookup can run before the full parser. When the regex finds no `module` declaration, it falls back to `source_path.stem` so the cache layout stays deterministic for malformed inputs (which the parser will reject on the next pass).
- **Output filenames mirror the module name.** `_transpile_single_file` now writes `<module.name>.py` rather than `<source_path.stem>.py`. Under the new validation invariant the two are equal, but the canonical derivation is from `module.name`.
- **Tests and inline fixture strings must align.** Several existing fixtures and inline `.s0ma` strings in the test suite have been updated to make their stems match their declared module names. None of them were exercising the old behaviour deliberately — they were artifacts of an older convention.

## Alternatives Considered

1. **Make the cache key tolerant of mismatches** — i.e., look up by both stem and module name and fall through. Rejected: this entrenches the bug rather than fixing it. It also leaves `uses:` consumers searching by module name with no recourse if the file is named otherwise.
2. **Allow divergence and document it** — let authors freely pick file stems independently of module names. Rejected for the greppability and mental-model reasons above; also makes source-map tooling materially harder.
3. **Warning in migration/dev, error in strict/release.** Rejected because the rule protects correctness, not style. A warning that consumers can ignore in dev mode invites the same silent-broken-import bug to recur in any project that does not graduate to strict mode before its first release.
4. **Rename the file automatically when a mismatch is detected.** Rejected as too invasive. The author's intent (rename the file vs. rename the declaration) cannot be inferred safely; surfacing both options in the remediation message is the right boundary.
