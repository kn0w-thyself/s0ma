# ADR-008: `visibility: TEST` — A Third Declarative Visibility Level

**Status:** Accepted (M8, feedback 5–6).
**Date:** 2026-04-28
**Context:** Feedback 5–6 plan, Milestone 8 — `visibility: TEST` level.
**References:** [feedback-5.5 lines 984–1019](../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/s0ma-dsl-feedback-5.5.md) ("HIGH PRIORITY M13"), [ADR-007](ADR-007-single-build-layout.md), `docs/s0ma-dsl-spec-v0.13.0.md` §4.10.1 and §5, `docs/spec_traceability.md` (`TEST_VISIBILITY_VIOLATION`).

---

## Decision

Add a third value to the `Visibility` enum: `TEST`. Components declared with `visibility: TEST` are reachable cross-module *only* from modules that contain at least one `test` declaration. Production modules that try to `uses:` a `TEST`-visibility component produce the new `TEST_VISIBILITY_VIOLATION` error (error severity in every strictness mode — migration, dev, strict, release).

`TEST` is a **declarative** third level — not a friend annotation, not an exception list, not a `# noqa: VISIBILITY` marker. The IR records the test-visibility relationship; `s0ma inspect` renders `[TEST <KIND> nerve]` distinctly from `[PUBLIC ...]` and `[INTERNAL ...]`; the access-control rules are explicit and machine-checkable.

**The access-control matrix.**

| Target visibility | Source: production module (no tests) | Source: test consumer (≥1 test) |
|---|---|---|
| `PUBLIC`, in `exports:` | OK | OK |
| `PUBLIC`, omitted from `exports:` | `VISIBILITY_MISMATCH` (intra-module) | `VISIBILITY_MISMATCH` (intra-module) |
| `INTERNAL` | `NOT_EXPORTED` | `NOT_EXPORTED` |
| `TEST` | **`TEST_VISIBILITY_VIOLATION`** | OK (and exempt from `NOT_EXPORTED`) |

**Interaction with `exports:`.** `TEST` components are explicitly *not* in the public export surface. They do not appear in `module.exports`, are exempt from the cross-module `NOT_EXPORTED` check (per the matrix above), and never appear in the emitted Python `__all__`. The intra-module `VISIBILITY_MISMATCH` check accepts a non-exported `TEST` cell or nerve as a correct authoring; an exported `TEST` component (i.e. listed in `exports:` and declared `TEST`) errors as before — `exports:` lists the *public* surface, and `TEST` is not public.

**The check is local, not transitive.** If a module declares ≥1 `test`, it qualifies as a test consumer and may add `TEST`-visibility targets to its `uses:`. The dependency resolver does not reason about whether a function inside a test module is *really* being called transitively from a production helper — that path of analysis lives outside the visibility model. Authors who need stronger guarantees use `INTERNAL` and reach for the registry namespace's privileged-imports mechanism (§4.10.6) instead.

## Context

The s0ma DSL has shipped two visibility levels for thirteen milestones: `PUBLIC` (cross-module via `exports:`) and `INTERNAL` (same module only). The model is tidy in the abstract but produced one specific failure pattern across three feedback-5.5 milestones (M01, M07, M13):

- A production module declares an `INTERNAL` helper (e.g. `_escape_text`, `_format_prompt`, `_render_attribute`) that is genuinely a private implementation detail of one or two PUBLIC nerves.
- A snapshot test wants to exercise the helper directly — input/output round-trips, edge-case coverage, characterisation tests of the rendering rules.
- The test cannot reach `INTERNAL` cross-module. It is forced to one of two workarounds:
  - **Workaround A: copy-paste.** Duplicate the helper into the test module verbatim. The two copies drift the moment the production helper changes; the test passes against a stale copy of the rendering rules.
  - **Workaround B: promote to `PUBLIC`.** Add the helper to `exports:`. The module's external surface now includes a function no production caller ever needed; downstream consumers see it in IDE auto-complete and may mistakenly call it; the API documentation grows by one entry that is structurally a private detail.

In feedback-5.5's M13 audit, `_escape_text` appeared **six times** across three test modules — one production definition, six near-identical copies. The drift risk was real (the production helper had changed once during the audit window without the tests updating), and the cure (Workaround A) was worse than the disease (Workaround B). Neither option is right.

The fix has been latent in the language design since v0: tests have a different access boundary than production code. Spec §4.10.1's registry namespace already grants tests *full observability* of every component regardless of visibility; what it does not grant is *callable access* in the generated Python. ADR-008 closes that gap.

## Rationale

### Why `TEST` is a first-class language level

**A) Unite code and information about code (Guiding Principle #1).** A friend-annotation approach (e.g. `# friend: my_test_module`) would scatter access-control facts across both ends of every test/production pair, with no IR record. `TEST` lives on the declaration where the rule applies; the IR records `"visibility": "TEST"`; `s0ma inspect` shows `[TEST <KIND> nerve]`. The fact that "this helper is reachable only from test consumers" is now a machine-queryable property of the component, not a comment.

**B) Eliminate manual documentation (Guiding Principle #2).** Both workarounds A and B require the author to write prose: "this is duplicated for test reasons; keep in sync" (Workaround A) or "this is `PUBLIC` only because tests need it; do not call from production" (Workaround B). With `TEST`, the visibility itself is the documentation. No comment is needed.

**C) The hard right path (Guiding Principle #4).** A friend annotation is a per-pair exception list — easier to ship, harder to reason about as the project grows. `TEST` is the third declarative level; once shipped, every test/production pair uses the same primitive. No exception list. No annotation grammar to maintain. The cost is a small enum change and one new error code.

**D) No silent failures (Guiding Principle #5).** Workaround A's drift is silent at build time and visible only when the test passes against a stale copy of the helper. `TEST_VISIBILITY_VIOLATION` is loud at build time in every strictness mode. The wrong path errors; the right path validates clean. There is no in-between.

### Why the check is local, not transitive

A natural worry: "what if a test file imports the `TEST` nerve into a private helper that's later called from production code transitively?" The honest answer is: the test consumer *is* itself a project module whose code is generated and importable, so in theory a production module elsewhere could `from <test_consumer> import <helper>` at the Python layer.

Three reasons we do not bake transitive analysis into the visibility check:

1. **The transitive call graph is not available at parse-time.** The visibility check runs in the dependency resolver — Phase 2 — well before any body-level evidence pass. Reasoning about transitive call-paths requires the full project AST and a CALLS edge derivation; baking that dependency into the visibility check inverts the pipeline.
2. **The pathology is contrived.** A test consumer that exposes a `TEST`-visibility helper for *production* use is itself a code-smell (test modules don't carry production code by convention, and `s0ma test` builds them into a separate output anyway). If a consumer reaches that shape, the right intervention is at code review, not at parse-time.
3. **Stronger guarantees already exist via `INTERNAL`.** A team that needs hard transitive isolation declares the helper `INTERNAL` and exercises it via the registry namespace's privileged-imports mechanism (§4.10.6). The privileged-import path is implementation-internal to the test runner and is not callable from production code by construction.

The visibility level chooses the access-control surface; the test runner enforces the boundary at the runtime layer. They are complementary, not substitutable.

### Why `TEST_VISIBILITY_VIOLATION` is `error` in every strictness mode

Same precedent as `MODULE_NAME_STEM_MISMATCH` (M4) and `AMBIGUOUS_TEST_TARGET` (M5): the rule is correctness, not preference. A production module that reaches for a `TEST`-visibility helper is bypassing the visibility model entirely; the cure is one of two remediations the diagnostic spells out. Demoting it to a warning in migration mode would normalise the workaround the level exists to retire.

The severity matrix entry reads:

```python
"TEST_VISIBILITY_VIOLATION": {m: "error" for m in StrictnessMode},
```

mirroring the `MODULE_NAME_STEM_MISMATCH` and `AMBIGUOUS_TEST_TARGET` entries.

### Why `TEST` is exempt from `NOT_EXPORTED`

A `uses:` entry that targets a `TEST`-visibility component bypasses the standard `NOT_EXPORTED` check by design — `TEST` components are not in `exports:` (and authoring them so produces `VISIBILITY_MISMATCH`), so the export check would fire on every legitimate test-consumer reference. The Phase 2 path:

1. If target visibility is `TEST`:
   - Source has ≥1 `test` declaration → OK.
   - Source has zero `test` declarations → `TEST_VISIBILITY_VIOLATION`.
   - In either branch, the export check is skipped — TEST is not in the export surface.
2. Otherwise: existing `NOT_EXPORTED` check applies.

Codegen treats `TEST` exactly like `INTERNAL`: emitted as a regular module-level name, not added to `__all__`. The visibility difference is purely about *which other modules* can import it, not about Python emission semantics.

## Alternatives Considered

### Option A — `friend:` annotations (rejected)

A `friend: [<test_module_names>]` field on the production declaration that names the specific test modules permitted to import an `INTERNAL` component:

```
nerve escape_text :: APPLICATION
    visibility: INTERNAL
    friend: [text_helpers_tests]
    ...
```

**Why rejected:**

- **Per-pair exception list.** Every new test consumer requires editing the production declaration. The list grows; the production module accumulates knowledge of its testers; the relationship is symmetric in code but asymmetric in maintenance.
- **No IR shape.** The `friend:` field does not generalise: it carries module names that may be added or removed without producing an IR-level record of the intent. `s0ma inspect` cannot render "this nerve is friend-accessible from <these specific modules>" without serialising the list verbatim, which is the same drift surface as the original prose comment.
- **Doesn't compose.** What if a test consumer wants to import a `TEST`-visibility helper from *another* test consumer? The friend list grammar would need to special-case test-to-test references, expanding the surface area of the rule.
- **The hard right path is structural, not annotational.** `TEST` is a property of the declaration; `friend:` is a property of the relationship between two declarations. Properties of the declaration are simpler.

### Option B — `# noqa: VISIBILITY` markers (rejected)

A comment-driven escape hatch on the consuming `uses:` line:

```
uses: [text_helpers.escape_text]  # noqa: VISIBILITY
```

**Why rejected:**

- **The original silent failure.** A `# noqa` is invisible to the IR; `s0ma inspect` cannot show that a particular `uses:` was permitted via a per-line override. Future authors copying the line carry the marker forward; future readers see the marker without context.
- **Comments are not declarations.** s0ma's working hypothesis is that every load-bearing fact lives in a declaration the system can self-describe. A `# noqa` marker delegates the description to prose; the system has no record of *why* this particular import was permitted.
- **Re-introduces the workaround the level retires.** `# noqa: VISIBILITY` is the workaround written in a different syntax. The hard right path is to make the legitimate use case a first-class declaration and the illegitimate use case a hard error.

### Option C — Promote helpers to `PUBLIC` and accept the API pollution (status quo)

The existing pre-M8 path: declare the helper `PUBLIC`, list it in `exports:`, and trust convention to keep production callers from reaching for it.

**Why rejected:**

- **API pollution is a real cost.** The module's external surface — what IDEs autocomplete, what cross-module consumers can `from <module> import`, what release-mode `MISSING_PUBLIC_DOC_REF` requires `doc-ref` coverage for — grows by every test-only helper. Fr3d's M07 audit found 14 such promotions; the public surface was 23% larger than the actual public API.
- **Convention is not enforcement.** A `PUBLIC` helper that is "really only for tests" is one off-by-one ticket away from being called from production code; the visibility level is the only structural defence.
- **Release-mode requirements escalate.** `MISSING_PUBLIC_DOC_REF` (release-only, doc-M7) requires every `PUBLIC` nerve to be covered by a `doc-ref`. Promoting test-only helpers to `PUBLIC` forces them into the documented public surface, where they have no business living.

`TEST` removes the cost without re-introducing convention-as-enforcement.

## Consequences

- **New error code:** `TEST_VISIBILITY_VIOLATION`. Severity `error` in every strictness mode. Registered in `SEVERITY_MATRIX` and `docs/spec_traceability.md`.
- **Validator and resolver are now visibility-aware on the cross-module path.** `_phase2_export_validation` calls a new helper `_lookup_component_visibility(module, name)` that returns the visibility of a named nerve or cell (or `None` if neither matches). The TEST branch fires before the existing NOT_EXPORTED branch.
- **Codegen is unchanged for `TEST`.** Visibility metadata flows through the existing emission path (`"visibility": "TEST"` in the registry metadata dict). `__all__` derives from `exports:` only — `TEST` components are not exported, so they do not appear in `__all__`. No special-casing.
- **`s0ma inspect` renders `[TEST <KIND> <decl_type>]`.** The pretty-printer concatenates `visibility kind decl_type` already; the addition is purely the new enum value flowing through.
- **Backwards-compatible for existing consumers.** Pre-M8 modules use only `PUBLIC` and `INTERNAL`; they parse and validate identically post-M8. The TEST level is purely additive.
- **Migration path:** `_escape_text` and analogous test-accessible helpers across feedback-5.5 audit milestones can now declare `visibility: TEST` and the consuming test module imports them directly — six copy-paste sites collapse to one declaration. No grammar migration is required for projects that don't adopt the new level.

## Forward pointers

- **M9 (Cross-layer dependency)** lands `CROSS_LAYER_DEPENDENCY` checking on `uses:` — including `uses:` of `TEST`-visibility components. A test module can `uses:` a `TEST` helper only if the cross-layer rule also permits the layer pair, regardless of visibility. The two checks compose: `TEST` answers "may this caller reach this kind of target?", layer rules answer "may this layer reach that layer?".
- **M19a (spec finalisation)** anchors §4.10.1's access-control matrix as the normative description of the visibility model. ADR-008 is the rationale; the spec is the contract.
- **A future "private nested component" extension** (referenced in the v1 visibility note in §3) would introduce a fourth level for in-declaration helpers. `TEST` does not occupy that slot — `TEST` is about cross-module access for test consumers, while `PRIVATE` would be about intra-declaration encapsulation.

## Related decisions

**F3 (feedback 5–6 follow-up): explicit `is_page_composer:` field replaces M18's heuristic.** ADR-008 established the architectural pattern that load-bearing access-control facts live as explicit, declarative metadata on the declaration where the rule applies — not as comments, friend lists, or runtime heuristics. F3 applies the same pattern to a different surface: M18's `exactly_one_per_page` attribute-budget shape originally inferred page-composer identity from `uses:`-graph topology ("a page is any module that no other module's `uses:` references"). The heuristic had documented edge cases — test modules looked like pages, projects without `uses:` edges had every module flagged, fully-circular graphs silently no-opped. F3 replaces the heuristic with a first-class `is_page_composer: bool = false` field on `NerveDecl`, parsed from `is_page_composer:` on a nerve declaration, serialised to the IR, and surfaced in `s0ma inspect`. The new error code `NO_PAGE_COMPOSER_DECLARED` (error in every mode) fires loudly when the budget shape is configured but no nerve carries the marker. Same architectural argument as ADR-008's `TEST` level: the property of "this nerve scopes a page" should be explicit metadata on the declaration the rule applies to, not a heuristic the resolver re-derives from topology. See `semantic/attribute_budgets.py` (`_page_composer_nerves`), `docs/migration_guide.md` ("M18 attribute_budgets: explicit page composers required"), and the F3 entry in [plans/5-6_deviations.md](../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_deviations.md).
