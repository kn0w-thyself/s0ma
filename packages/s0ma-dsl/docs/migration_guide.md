# Migrating from s0ma Python to .s0ma DSL

This guide explains how to convert existing `@component`-decorated Python modules into `.s0ma` source files.

> **Looking for a scannable adoption overview for the 0.11.x → 0.13.0
> upgrade?** See
> [`docs/release_walkthrough_5-6.md`](historical/release_walkthrough_5-6.md) — the
> consumer-facing walkthrough for the feedback 5–6 work cycle (M1–M20 +
> F1–F4 + G1–G12). It's the "what you should DO about it" overlay; this
> guide is the canonical "what changed" reference.

---

## Migrating to the required `forbids` line (`s0ma migrate grammar`)

From the release that carries this change, every `nerve` and every `ganglion`
carries a `forbids:` line: what that part must never do, however it is called
and whatever happens while it runs. The line is required, like `expects:` and
`guarantees:`. When a part has nothing to rule out, the line says so with
`none`, which is an answer, not a way to skip the line. s0ma checks that the
line is there and what state it is in; it does not read the sentence.

**Who is affected:** every project with at least one nerve or ganglion. A
project that built cleanly before is refused until each of those parts carries
the line, in every strictness mode, `migration` included. `s0ma check` and
`s0ma build` report the gap as `SEMANTIC_REQUIRED_STATE_OMITTED`, naming the
field and the part, and the report points at the one command that fixes it:

```bash
s0ma migrate grammar path/to/project_root           # dry run: shows what it would write
s0ma migrate grammar path/to/project_root --apply   # writes it
s0ma build path/to/project_root                     # rebuild
```

`migrate grammar` does three things, and is idempotent (a second run finds
nothing to add and changes nothing):

1. **Reads the whole project first.** It parses every authored `.s0ma` file
   before it plans a single write, and without `--apply` it writes nothing.
2. **Writes `forbids: none`** into every nerve and ganglion that lacks the
   line, directly above that part's `---`. A part that already carries a
   `forbids:` line is left exactly as it is.
3. **Reports each insertion.** It prints a manifest naming every file it
   changes and every line it adds, as `nerve:<name>.forbids` or
   `ganglion:<name>.forbids`. With `--apply` it writes the whole plan, or
   none of it if any file cannot be written.

**What `none` means on migrated code.** On a part you wrote yourself,
`forbids: none` is your answer: you looked, and there is nothing this part
must never do. On migrated code it is an answer the command gave on your
behalf. Nobody has looked yet, and the build cannot tell the difference, so
nothing will remind you. Keep the manifest, read each part it names, and
wherever a part has something it must never do, replace `none` with one plain
sentence in double quotes that says what it is, specific enough that a reader
could tell when the code breaks it. Leave `none` only where you have looked
and found nothing to rule out.

**What a built application needs.** `none` adds nothing to the built Python,
but a sentence does: the build passes it to the part's `Contract` as
`forbids=[...]`, and only the `s0ma-core` of the release that carries this
change accepts that field. An older `s0ma-core` refuses it with a registration
error when the module loads. Install the matching `s0ma-core` alongside
`s0ma-dsl` wherever the application runs, and rebuild. s0ma then shows the
sentence with the part's contract, under `Forbids:`, and never executes it.

---

## Migrating a pre-consolidation project (`s0ma migrate-ext`)

If your project was authored against the pre-consolidation repos — when the
product name and extension family were spelled with a letter o instead of
the digit 0 — migrate it **before** anything else in this guide:

```bash
s0ma migrate-ext path/to/project_root --dry-run   # inspect the plan
s0ma migrate-ext path/to/project_root             # apply it
s0ma build path/to/project_root                   # re-emit .py outputs + manifest
```

`migrate-ext` does three things, prints each one as it happens, and is
idempotent (a second run is a no-op):

1. **Renames the extension family** to `.s0ma` / `.s0ma.json` / `.s0ma.map`
   (and the build manifest to `build.s0ma.json`). The rename anchors at the
   end of the filename, so only real artifact extensions are touched. If a
   rename target already exists, the command lists every collision and exits
   **without changing anything** — resolve the conflicts and re-run.
2. **Rewrites the legacy `[tool.*]` table** in the project root's
   `pyproject.toml` to `[tool.s0ma]` (subtables included), preserving every
   other byte of the file. Project discovery (ADR-005) works again
   immediately afterwards.
3. **Removes legacy cache directories** (both the pre-consolidation
   incremental build cache and the older import-hook cache generation).
   Caches are regenerable; the next `s0ma build` or import repopulates them
   under the current names.

The final `s0ma build` matters: `.py` files emitted by a pre-2.0.0
transpiler embed the old hash-comment markers, so `s0ma verify` reports
them as unverifiable until the build re-emits them with current markers
(IR schema 2.0.0).

After migrating, run `s0ma doctor` (0.6.0): it confirms the project
resolves under the current `[tool.s0ma]` spelling and reports per-module
build freshness, so a missed rebuild shows up as a `stale` finding
instead of a surprise at import time. See the quick reference's CLI
table for the full section list.

---

## Strategy: Leaf-First, Gradual Strictness

1. **Start with leaf modules** — modules with no `uses` dependencies (only `requires`). These can be converted and validated independently.
2. **Begin in migration mode** — `s0ma check --mode migration` is lenient on vestigial imports and missing packages.
3. **Increase strictness gradually** — move to `dev`, then `strict`, then `release` as you fix warnings.
4. **Mixed projects work** — `.s0ma` and `.py` files coexist in the same project and share the registry.

---

## Step-by-Step Conversion

### 1. Identify the module

Start with a Python file that uses `@component` decorators. Example:

```python
# signals/models.py
from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer
from s0ma.models import Contract

@component(
    name="SignalEnvelope",
    kind=ComponentKind.MODEL,
    layer=Layer.APPLICATION,
    intent="Wraps a raw nerve signal with metadata for routing",
)
@dataclass(frozen=True)
class SignalEnvelope:
    source: str
    timestamp: float
    payload: dict

MAX_STALENESS = 300
```

### 2. Create the module header

Map the Python metadata to a `.s0ma` module declaration:

```
module models
    layer: APPLICATION
    version: 1.0.0
    intent: "Data models and constants for the signal processing system"
    requires: [dataclasses.dataclass]
    exports: [SignalEnvelope]
```

**Mapping rules:**
- `layer` comes from the `Layer` enum used in `@component`
- `version` — assign a semver version (start with `1.0.0` for stable code)
- `requires` — list external Python imports used in bodies
- `uses` — list s0ma components from other modules (qualified: `module.Component`)
- `exports` — list all PUBLIC components (the module's external API)

### 3. Convert each @component to a declaration

**@component class → cell:**

```
cell SignalEnvelope :: APPLICATION
    kind: MODEL
    visibility: PUBLIC
    intent: "Wraps a raw nerve signal with metadata for routing"
    schema: "Frozen dataclass with source: str, timestamp: float, payload: dict"
    ---
    @dataclass(frozen=True)
    class SignalEnvelope:
        source: str
        timestamp: float
        payload: dict
```

**@component function → nerve:**

```python
# Before
@component(
    name="validate_signal",
    kind=ComponentKind.FUNCTION,
    layer=Layer.APPLICATION,
    intent="Validates signal envelope fields",
    contracts=Contract(
        input_type="envelope: SignalEnvelope",
        output_type="bool",
        max_latency_ms=5,
    ),
)
def validate_signal(envelope: SignalEnvelope) -> bool:
    ...
```

```
# After
nerve validate_signal :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Validates signal envelope fields"
    expects: "envelope is a valid SignalEnvelope"
    guarantees: "Returns True if valid, raises on invalid"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    latency_ms: 5
    ---
    def validate_signal(envelope: SignalEnvelope) -> bool:
        ...
```

**Bare constants → cell (CONSTANT kind):**

```
cell MAX_STALENESS :: APPLICATION
    kind: CONSTANT
    visibility: INTERNAL
    intent: "Maximum age in seconds before a signal is rejected as stale"
    schema: "int constant = 300"
    ---
    MAX_STALENESS = 300
```

### 4. Map dependencies

| Python Pattern | .s0ma Equivalent |
|----------------|------------------|
| `import os` | `requires: [os]` |
| `from uuid import UUID` | `requires: [uuid.UUID]` |
| `from mymod import Foo` (s0ma component) | `uses: [mymod.Foo]` |
| `dependencies=["OtherComponent"]` (same module) | `depends_on:` block on the nerve/ganglion |
| Cross-module dependency | Standalone `axon` declaration |

### 5. Map visibility

| Python | .s0ma |
|--------|-------|
| Listed in `__all__` or intended as public API | `visibility: PUBLIC` + add to `exports` |
| Internal helper, `@internal` | `visibility: INTERNAL` + omit from `exports` |

### 6. Map contracts to fields

| `Contract` field | .s0ma field |
|------------------|-------------|
| `preconditions` or `input_type` | `expects` |
| `postconditions` or `output_type` | `guarantees` |
| `max_latency_ms` | `latency_ms` |
| `invariants` | `invariants` (on cells) |

### 7. Handle special cases

**Enums:**
```
cell Priority :: DOMAIN
    kind: ENUM
    visibility: PUBLIC
    intent: "Valid priority levels for tasks"
    schema: "Enum with LOW, MEDIUM, HIGH values"
    ---
    class Priority:
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"
```

**Exceptions:**
```
cell TaskError :: DOMAIN
    kind: EXCEPTION
    visibility: PUBLIC
    intent: "Raised when a task operation fails"
    schema: "Exception with message and task_id"
    ---
    class TaskError(Exception):
        def __init__(self, message: str, task_id: str = ""):
            self.task_id = task_id
            super().__init__(message)
```

**Tests:**
```
module task_tests
    layer: APPLICATION
    version: 1.0.0
    intent: "Tests for the task processing pipeline"
    uses: [task_service.validate_task]
    exports: []

test test_validate_task :: APPLICATION
    intent: "Verifies validate_task rejects empty titles"
    tests: [task_service.validate_task]
    ---
    def test_validate_task():
        assert validate_task(make_task(title="hello")) is True
```

### 8. Validate

```bash
# Start lenient
s0ma check my_module.s0ma --mode migration

# Fix warnings, then tighten
s0ma check my_module.s0ma --mode dev
s0ma check my_module.s0ma --mode strict

# Before release
s0ma check my_module.s0ma --mode release
```

---

## Strictness Progression

| Mode | What it catches |
|------|----------------|
| `migration` | Structural errors only. Vestigial imports and missing packages are warnings. |
| `dev` | Same as migration. Recommended for active development. |
| `strict` | Vestigial imports, missing packages, empty observes, prohibited constructs are errors. |
| `release` | All of strict, plus: untested PUBLIC nerves, zero-version modules. |

---

## Checklist

- [ ] Module header has layer, version, intent, exports
- [ ] Every `@component` class/function has a corresponding declaration
- [ ] `requires` lists all external Python imports used in bodies
- [ ] `uses` lists all cross-module s0ma references
- [ ] Visibility matches exports (PUBLIC ↔ exported, INTERNAL ↔ not exported)
- [ ] All components share the module's layer
- [ ] Nerve bodies are `def`, not `class`
- [ ] No bare `import` statements in bodies
- [ ] `raises` entries are s0ma exception cells, not Python builtins
- [ ] `s0ma check --mode strict` passes

---

# 0.15.0 → 0.16.0: Migration walkthrough

The 0.16.0 release lands the post-Phase-2 second release boundary (M-8 through M-19 of the post-Phase-2 plan; 11 May 2026) and pairs with `s0ma-core 0.4.0` (which lands POST-1 / M-1 on the core side). The DSL batch is **wider than 0.15.0**: it covers grammar enrichment round 2, build / CLI maturity, the bulk of the validator round, permissive test-layer routing, and the `requires-python` forward-incompat check. Every change is **additive and backward-compatible** — pre-0.16.0 modules parse unchanged, no consumer call site is mandated to change, and the only mandatory rotation is the spec-pointer (the v0.11.0 pointer retires, the live single pointer is now v0.15.0 → v0.16.0).

**No required consumer action.** Re-pin the toolchain to the new release — from a monorepo checkout, `uv sync --all-packages` — and re-run `s0ma build`; everything continues to work. Every milestone below is either an opt-in adoption surface OR a no-action-needed behavioural improvement.

**Behaviour-changing surfaces consumers should be aware of.**

1. **`integration` declaration kind (M-9 / POST-5).** D-15 is promoted to a first-class declaration. An integration declares `intent:`, `version:`, `smoke_test_primary:`, and the codegen auto-emits four helpers (`get_factory`, `get_manifest`, `smoke_test_primary`, `get_smoke_test`) without IntegrationManifest constructor verbosity. The existing IntegrationManifest pattern continues to work — no breaking change. **Use this for** Phase 3 §4.3 P-11.x integrations (Gmail, Slack) and any sibling integrations sharing helper names that previously needed `module_scoped: True` to coexist. Spec §4.7 carries the canonical reference.

2. **`test_layering` permissive opt-in (M-10 / POST-6).** A new project-config flag in `pyproject.toml`:

   ```toml
   [tool.s0ma]
   test_layering = "permissive"   # default: "strict"
   ```

   When set to `"permissive"`, the validator skips `CROSS_LAYER_DEPENDENCY` checks for `test` declarations only; production `uses:` is still checked strictly. The default is preserved as `"strict"`, so opting in is explicit. **Use this for** Phase 2 MS 4 / MS 7 / MS 18 tests that routinely import across layers (a common pattern: an APPLICATION test referencing INFRASTRUCTURE).

3. **`s0ma check` multi-path + subdir scope (M-11 / POST-7).** `s0ma check src/ tests/` runs against both paths as a single invocation. `s0ma check` with no positional args runs against every configured root. A subdir input resolves the project context by walking up to find `pyproject.toml`. Existing `s0ma check src/specific_module.s0ma` continues to work. **Use this for** Phase 2 MS 22 acceptance sweeps.

4. **`--force-output-dir` refusal semantics (M-16 / POST-11a).** `s0ma build --output-dir <path>` warns when `<path>` contradicts `[tool.s0ma].build_dir`, and **refuses without `--force-output-dir`**. The new flag is the explicit override. Pre-0.16.0 invocations that previously silently overrode the project's `build_dir` now require the explicit flag to opt back into the override. **Use this for** any agent or CI step that intentionally builds into a transient directory.

5. **`runtime_only_requires:` field (M-13 / POST-10b).** A new module-header field carves out imports that are needed only at test runtime (the canonical case is `pytest`) so the vestigial-import detector no longer flags them. Inline (`runtime_only_requires: [pytest]`) and block forms parse identically.

6. **Validator closure improvement (M-13 / POST-10a).** The vestigial-import detector now computes the closure across `uses:` ↔ `depends_on:` ↔ body references in a single pass instead of multiple separate passes. Some imports that were previously flagged as vestigial may now resolve cleanly; no false-negatives are introduced (the closure is a strict superset of the previous detection set).

**New opt-in surfaces (no behaviour change for legacy modules).**

7. **Manifest emits Python stubs (M-8 / POST-14).** `s0ma build` writes `<build_dir>/build.s0ma.pyi` alongside `build.s0ma.json` so `bootstrap_imports` consumers see typed `dict[str, ModuleType]` keyed by module name under mypy / pyright. Pre-0.16.0 consumers continue to work — the stub is additive. **Use this for** dropping the consumer-side `getattr` + duck-typing fallback (`bootstrap = bootstrap_imports(build_dir); bootstrap["module_name"]` typechecks cleanly).

8. **`expected_exceptions:` on nerves (M-17 / POST-12a).** Nerves may declare Python-side exceptions caught by design — distinct from `raises:` which is restricted to s0ma cells:

   ```
   nerve OAuthCallback :: INFRASTRUCTURE
       kind: ADAPTER
       expected_exceptions: [TokenExpiredError, NetworkError]
       ...
   ```

   The field rides through the nerve IR as `components[].fields.expected_exceptions` and into the emitted `metadata={}` dict. Codegen wraps the body with the same `try` / `except` topology it does for `raises:`-mediated cells. **Use this for** nerves whose contract includes catching specific Python exceptions (the typical OAuth, HTTP, vendor-SDK case).

9. **`deferred:` annotation on stubs (M-17 / POST-12f).** A `deferred: "<reason>"` annotation marks a stub body as awaiting fill. The new `s0ma check --report-deferred` CLI reporter enumerates every deferred surface across the project for milestone planning.

10. **`placeholders:` on CONSTANT cells with `@file()` content (M-18 / POST-12b).** Magic-string slots like `__SYSTEM_NAME__` inside an `@file()` body may be declared in a `placeholders:` list; the validator checks each declared slot exists in the file at check time and fires an error if any is missing.

11. **`[tool.s0ma].fixtures_format` (M-18 / POST-12g).** Project-config map for non-`.s0ma` test-fixture validation:

    ```toml
    [tool.s0ma.fixtures_format]
    "*.jsonl" = "ndjson"
    "*.toml" = "toml"
    ```

    `s0ma check` validates each matched fixture file against the declared format.

12. **`dataclass_invariants:` on MODEL cells (M-19 / POST-12c).** MODEL cells may declare machine-readable invariants:

    ```
    cell LatencyProfile :: APPLICATION
        kind: MODEL
        dataclass_invariants:
          - "len(latency_samples) <= 100"
          - "min(latency_samples) >= 0"
        ---
        @dataclass
        class LatencyProfile:
            latency_samples: list[float]
    ```

    The invariants ride through the cell IR as `components[].fields.dataclass_invariants`. Validator parses each invariant string; runtime-side enforcement is left to the consumer.

13. **`consumes_via_dict:` on depends_on entries (M-19 / POST-12d).** A new optional sub-field on `depends_on:` entries declares duck-typed coupling explicitly:

    ```
    depends_on:
      - PromptAssembler:
          consumes_via_dict: [AssembledPrompt: payload]
    ```

    Surfaces dict-access coupling that was previously invisible to the validator's reach analysis. The IR records the pairing under `components[].fields.depends_on_via_dict`.

14. **`MUTABLE_DEFAULT` strict-mode lint (M-15 / POST-10h).** `s0ma check --mode strict` flags `dataclasses.field(default=[...])` (and analogous mutable defaults on plain `def` arguments) with a remediation pointing at `default_factory=`.

15. **`DUPLICATE_INNER_FUNCTION` lint (M-15 / POST-10i).** SERVICE-nerve bodies that declare the same inner `def` name twice now fire a strict-mode error.

16. **`CROSS_MODULE_USES_ASYMMETRY` warning (M-15 / POST-10k).** Two modules in the same project that share a bare `<CellName>` via `uses: [other_module.<CellName>]` from one side but not the other fire a strict-mode warning. Closes the silent-drift class where module-qualified imports go one way but a sibling module's import of the same cell goes another.

17. **`PARSE_GRAMMAR_FORWARD_INCOMPAT` (M-12 / POST-8).** `s0ma check` walks each emitted body's AST against the project's `[project].requires-python` floor. 3.12-only constructs (nested-quote f-strings, walrus-in-comprehension, etc.) when `requires-python` includes 3.11 fire `PARSE_GRAMMAR_FORWARD_INCOMPAT` at check time rather than failing at import on 3.11.

**Validator surface polish (M-14 / POST-10d/e/f/g).**

- `MODULE_NAME_COLLISION` remediation now suggests a descriptive suffix (plus an opt-in `[tool.s0ma].test_module_name_prefix_by_dir = true` config for the directory-prefix auto-rename strategy).
- `s0ma check tests/` now surfaces project-level invariants (previously only `s0ma build` did).
- `BARE_IMPORT` remediation reworded per the spec: "this name is already declared in `uses:` and is imported automatically; remove the bare import."
- `uuid.uuid4` warning now suggests the `uuid:uuid4` colon-override.

**CLI quality of life (M-16 / POST-11).**

- `s0ma test --quiet` mode suppresses the driver banner; forwards only pytest's stream. Useful in CI logs.
- `s0ma build` exit-code semantics are pinned: warnings never block build absent `--strict`. New regression tests guard against drift.
- `BUILD_DIR_OVERRIDE_CONFLICT` info-severity finding surfaces the `--output-dir` ↔ `build_dir` mismatch in a structured way.

**New error codes (with severity-by-mode).**

| Code | Migration | Dev | Strict | Release | Trigger | Fix |
|---|---|---|---|---|---|---|
| `PARSE_GRAMMAR_FORWARD_INCOMPAT` | warning | error | error | error | A construct in the emitted body requires a Python version above the project's `[project].requires-python` floor | Either restrict the construct or raise `requires-python` |
| `MUTABLE_DEFAULT` | — | — | error | error | A mutable default (`default=[...]`, `default={...}`) on a dataclass field or function parameter | Use `default_factory=list` (or analogous) |
| `DUPLICATE_INNER_FUNCTION` | — | — | error | error | The same inner `def` name appears twice inside a SERVICE-nerve body | Rename one of the duplicates |
| `CROSS_MODULE_USES_ASYMMETRY` | — | warning | warning | warning | Two modules share a cell via asymmetric `uses:` references | Pick one convention per cell — either both qualify or neither does |
| `EXPORTED_HELPER_NOT_FOUND` (already in 0.15.0; behaviour unchanged) | error | error | error | error | An `exports_helpers:` entry does not name a `helper` in the same module | Declare the helper or remove the entry |
| `BUILD_DIR_OVERRIDE_CONFLICT` | info | info | info | info | `--output-dir` contradicts `[tool.s0ma].build_dir` and `--force-output-dir` was not set | Add `--force-output-dir`, or remove `--output-dir` and let `build_dir` apply |
| `INTEGRATION_*` (M-9; reserved error-code family) | error | error | error | error | Various integration-declaration shape violations | See spec §4.7 for the per-code remediation |
| `PROVIDES_VIA_DICT_UNKNOWN_CONTRACT` (M-19) | error | error | error | error | A `consumes_via_dict:` entry names a contract not declared in `provides_contracts:` of the target | Add the contract to the target's `provides_contracts:` or remove the entry |
| `PLACEHOLDER_NOT_IN_FILE` (M-18) | error | error | error | error | A declared `placeholders:` slot is missing from the `@file()` body | Add the slot to the file or remove the entry |
| `INVARIANT_PARSE_ERROR` (M-19) | error | error | error | error | A `dataclass_invariants:` string does not parse as a Python expression | Fix the expression syntax |

All codes appear in the auto-generated common-errors table in the quick reference (regenerated via `make docs-derived`) and in `docs/spec_traceability.md`.

**Spec file rename.** `docs/s0ma-dsl-spec-v0.15.0.md` → `docs/s0ma-dsl-spec-v0.16.0.md` via `git mv`. **One-release-pointer rotation:** the v0.11.0 pointer (which previously redirected to v0.15.0) is deleted in this release per the deletion-after-0.15.0 policy the MR-1 pointer body declared. A new v0.15.0 pointer file takes its place and redirects to v0.16.0 (declaring deletion-after-0.16.0). The README's spec link and the docs-table row update in lockstep.

**IR / manifest schema versions.** The IR stays at the prior shape; the manifest schema stays at `s0ma-build-manifest@1`. Every new field (`expected_exceptions`, `deferred`, `placeholders`, `dataclass_invariants`, `depends_on_via_dict`, plus the integration-decl IR additions) is additive under the existing schema.

**Cross-repo dependency.** Pairs with `s0ma-core 0.4.0` (which adds the `ImportHookAnomaly` observability surface — see `post-phase2_release_0.4.0_summary.md`, a pre-monorepo summary not carried in this repository). The two bumps are companion releases — either side can be re-pinned independently because the DSL changes ride through the registry as opaque metadata.

**Consumer action checklist.**

- [ ] Re-pin `s0ma-dsl` to the new branch. (`s0ma-core 0.4.0` is the companion bump; re-pin independently when you want the observability surface.)
- [ ] Re-run `s0ma build`. Every existing module continues to parse and emit unchanged — no required edits.
- [ ] (Recommended) If your project has `s0ma build --output-dir <path>` invocations that previously contradicted `[tool.s0ma].build_dir`, add `--force-output-dir` to keep the override behaviour.
- [ ] (Optional) Add `[tool.s0ma] test_layering = "permissive"` to retire the documented `CROSS_LAYER_DEPENDENCY` workarounds on test modules.
- [ ] (Optional) Promote existing IntegrationManifest call sites to the `integration` declaration kind for the four-helper auto-emit.
- [ ] (Optional) Adopt `expected_exceptions:` on ADAPTER nerves whose contract catches specific Python exceptions.
- [ ] (Optional) Add `deferred: "<reason>"` to stub bodies; track via `s0ma check --report-deferred`.
- [ ] (Optional) Adopt `placeholders:` on `@file()`-backed CONSTANTs.
- [ ] (Optional) Adopt `dataclass_invariants:` on MODEL cells with non-trivial shape constraints.
- [ ] (Optional) Adopt `consumes_via_dict:` on `depends_on:` entries that today route through dict-key access.
- [ ] (Optional) Adopt `runtime_only_requires: [pytest]` to retire vestigial-import false-positive carveouts on pytest.
- [ ] (Optional, recommended for typed consumers) Pick up the new `build.s0ma.pyi` stub by re-running `s0ma build`; consumers using `bootstrap_imports` now typecheck cleanly under mypy / pyright.

---

# 0.14.0 → 0.15.0: Migration walkthrough

The 0.15.0 release lands the post-Phase-2 grammar-enrichment batch (M-2 through M-7 of the post-Phase-2 plan; 11 May 2026). Every change is **additive and backward-compatible** — pre-0.15.0 modules parse unchanged, no consumer call site is mandated to change, and `s0ma-core` stays pinned at `0.3.0` (no companion bump this cycle). The six milestones each retire a documented workaround or close a recurring friction surface fr3d's Phase 2 work bumped into.

**No required consumer action.** Re-pin the toolchain to the new release — from a monorepo checkout, `uv sync --all-packages` — and re-run `s0ma build`; everything continues to work. Every milestone below is an **opt-in** surface — adopt the new field on a cell or nerve when you want the behaviour; ignore it otherwise.

**Behaviour-changing surfaces consumers should be aware of (all opt-in).**

1. **`category: capability | behaviour` on cells** (M-3 / POST-2). Cells gain an optional high-level role field. Omitting the field leaves the cell unchanged (legacy source parses identically). The value rides through the cell IR record (`fields.category` in the `.s0ma.json`) and is woven into the cell's `metadata` dict on every emitted `@component` / `register_constant` / `register_type` call, so downstream consumers see the role at runtime without re-reading the IR. `s0ma inspect` surfaces the value in the cell row's bracket label (`[PUBLIC CONSTANT cell, category=capability]`). Invalid values raise `PARSE_ERROR` with a remediation naming the two valid alternatives. **Use this for** registry-driven capability/behaviour classification (fr3d's MS 19 ConfigDiff classifier is the motivating consumer). The static name-pattern rule table previously maintained in `docs/config_change_format.md` can be retired in favour of querying `metadata["category"]` at runtime.

2. **Structured `provides:` triples on SERVICE nerves** (M-4 / POST-3a). The flat form (`provides: [foo, bar]`) parses unchanged. A new structured form lets authors declare per-method `returns:` / `expects:` / `guarantees:` inline, one entry per operation:

   ```
   provides:
     - assemble:
         returns: "str — the assembled prompt"
         expects: "topic: str (non-empty)"
         guarantees: "result is non-empty; topic is escaped"
     - validate:
         returns: "bool — True iff topic is well-formed"
   ```

   Every triple slot is independently optional. The per-method triple rides through the IR (`components[].fields.provides_contracts` in `.s0ma.json`) and the emitted Python's `metadata={"provides_contracts": [...]}` dict so introspecting agents (fr3d's MS 11 settings, MS 12 budget, MS 17-local OAuth nerves) read per-method contracts at runtime without re-parsing the source or recovering them from docstrings + type hints. When at least one entry carries a triple AND the body terminates with a `return {...}` literal, the validator additionally checks the returned-dict keys against the structured `provides:` names — closing the `"asemble"`-vs-`"assemble"` typo class without a separate `returns:` declaration. Two new always-error codes guard the structured form's shape: `MIXED_PROVIDES_FORMS` (a block mixes flat and structured items) and `DUPLICATE_PROVIDES_NAME` (the same operation name appears twice). Spec §4.1.3 carries the canonical reference.

3. **`mocks:` on test declarations + cross-validation** (M-5 / POST-3b). Test declarations may now carry an optional `mocks: [<NerveName>, ...]` field naming the SERVICE / ADAPTER nerves whose public surface the test mocks. Inline and PRE-7 block forms parse identically. The field rides through the IR (`components[].fields.mocks` in `.s0ma.json`) for downstream tooling (fr3d's Phase 2 Frontend track is the motivating consumer). The validator cross-checks any dict literal assigned to a variable whose lowercased name matches a `mocks:` entry (optionally with a `mock_` / `fake_` / `stub_` / `dummy_` / `fixture_` prefix) against the target nerve's `provides:` set and fires `MOCK_KEY_MISMATCH` on key mismatch. Conservative by design — dynamic mock construction (`dict(...)`, comprehensions, str-formatted keys) is silently skipped to avoid false positives. Cross-module mock targets resolved via `uses:` are accepted but the dict-key check runs only for local targets. Unknown mock targets raise `DOES_NOT_EXIST`. **Use this for** silent-drift prevention where a mock dict's keys would otherwise diverge from the production SERVICE's `provides:` set without any test failing.

4. **`provides:` ↔ `return {...}` literal-key strict-mode pass** (M-5 / POST-3c). M-4 added a structured-form check that fires `MISSING_RETURN_KEY` when a structured `provides:` entry's name is missing from the body's terminal `return {...}` literal. POST-3c generalises the check to cover (a) the flat form too (`provides: [assemble]` with body `return {"asemble": assemble}` is now caught — closing the typo class on the flat form), and (b) the extra-key direction (a return-dict key that is not in `provides:` — the structured form's M-4 check did not catch this half). The new `PROVIDES_KEY_MISMATCH` code fires warning in migration/dev, error in strict/release. For structured nerves, POST-3c only fires the extra-key direction so `MISSING_RETURN_KEY` and `PROVIDES_KEY_MISMATCH` never duplicate on the same author error. Literal-keys-only by design: bodies that build their return dict via `dict(...)` or a comprehension are silently skipped — false positives on legitimate dynamic returns would erode author trust in the check.

**New opt-in surfaces (no behaviour change for legacy modules).**

5. **`internal: [name: "<intent>"]` on nerves** (M-6 / POST-3d). Nerve declarations gain an optional structured list of inner helper functions:

   ```
   nerve PromptAssembler :: APPLICATION
       kind: SERVICE
       provides: [assemble, validate]
       internal:
         - _normalize_topic: "Strip whitespace and lowercase the topic"
         - _escape_html: "Escape HTML-special chars"
       ---
       def assembler():
           def _normalize_topic(topic): ...
           def _escape_html(s): ...
           ...
   ```

   Two surface forms parse identically: inline (`internal: [_foo, _bar]` — bare names only, no intent strings) and block (each entry is either bare `- _foo` or `- _foo: "intent"`, with both shapes freely mixable in the same block). Each entry name must be a Python identifier; duplicates within a block raise `PARSE_ERROR`. The field has **no codegen or registry effect** — the Python emitter ignores the field entirely, no `register_*()` call is generated for any entry, no new key appears in the `@component` `metadata=` dict, and the nerve body emits unchanged. The validator does not enforce that every named entry actually exists as a `def` in the body — the field is descriptive only. When non-empty, the value rides through the nerve IR record (`components[].fields.internal_helpers` in the `.s0ma.json`) as an ordered list of `{"name": str, "intent"?: str}` dicts, and `s0ma inspect` renders a dedicated `Internal helpers (<n>):` sub-section per nerve that has them. **Use this for** factory-closure nerves whose deep bodies have carried several inner helpers each with no way for contributors or downstream tooling to discover the private API short of reading every body (fr3d's MS 2 BundleEmitter and MS 16-core update-diff are the motivating consumers).

6. **`helper` accepts `class` bodies** (M-7 / POST-4a). A `helper` declaration's body may now be a `class` definition in addition to the original `def` shape:

   ```
   helper _LocalCache :: APPLICATION
       intent: "Module-private LRU cache for the prompt formatter."
       ---
       class _LocalCache:
           def __init__(self): ...
           def get(self, key): ...
   ```

   The class is **not** registered as a component, carries **no** `@component` decorator, and is **not** added to `__all__`. The codegen emits a plain top-level `class <Name>:` preceded by the same `# Helper: <intent>` comment as a function-bodied helper. The IR records the structural shape under `IRHelper.body_kind = "class"`; `"function"` (the pre-POST-4a default) is unchanged. The access-control rule (§4.4a.3) is unchanged: production cross-module consumers still hit `HELPER_PRIVATE_TO_MODULE`; test-context consumers continue to qualify. Body kinds outside `function` and `class` (assignments, type aliases, bare values) are still rejected with `PARSE_ERROR`. **Use this for** module-private classes that previously routed through `cell kind: MODEL visibility: INTERNAL` to stay out of the public registry — the helper form retires that workaround without registry side-effects.

7. **`helper @inline` shorthand** (M-7 / POST-4b). A helper may be declared inline inside the module header's `helpers:` block, dropping the separate `helper <name> :: <layer>` header and `---` separator:

   ```
   module foo
       layer: APPLICATION
       intent: "..."
       helpers:
         - helper _add @inline: "Quick addition" :: def _add(a, b): return a + b
         - helper _mul @inline: "Quick multiplication" :: def _mul(a, b): return a * b
       ---
   ```

   Each entry carries: the literal `helper`, the helper name, the `@inline` marker, a quoted intent string, `::`, and a single-line Python `def` body. Inline helpers always parse with `body_kind="function"` and `inline=True`; the IR records both fields. Inline and block-form helpers may coexist freely in the same module — the rule is "pick the right shape per helper," not "pick one shape per module." Inline helpers obey the same access-control rule as block-form helpers; duplicate names within a block raise `PARSE_ERROR`. **Use this for** one-line helpers (small predicates, format helpers) that previously incurred a five-line `helper ... --- def ...` block per declaration.

8. **`exports_helpers:` module-header field for cross-module re-export** (M-7 / POST-4c). A module may declare which of its helpers are intentionally exposed for cross-module reachability:

   ```
   module shared_utils
       layer: APPLICATION
       intent: "..."
       exports_helpers: [_compare, _render_markdown]
       ---
   ```

   Each entry must name an actual `helper` declaration in the same module; otherwise the validator fires the new `EXPORTED_HELPER_NOT_FOUND` (error in every strictness mode). The field accepts both inline (`exports_helpers: [_a, _b]`) and PRE-7 block-list (0.14.0) forms. Re-exported helpers are appended to the emitted `__all__` after the regular `exports:` entries (in declaration order) and ride through the IR via `IRModule.exports_helpers`. **Reachability vs access control:** `exports_helpers:` widens reachability — re-exported helpers resolve cleanly when a test-context module names them in `uses: [<module>.<helper>]` — but **does not** widen access control. Production consumers (no `test` declarations) still hit `HELPER_PRIVATE_TO_MODULE` even for re-exported helpers; the diagnostic context carries `re_exported: true` so tooling can distinguish "production tried to reach a re-exported helper" from "production tried to reach a strictly-private helper." `exports_helpers:` cannot re-export helpers from other modules — every entry must be a `helper` declared in *this* module. **Use this for** sharing test fixtures or contract-witness helpers across sibling test modules without resorting to a duplicated `cell kind: MODEL visibility: TEST` per consumer.

**Documentation additions (POST-9 a-i) — no code change required.**

The patterns guide grows §18–§22 with five recipes that previously lived as tribal knowledge in PR review comments: Decision-1 abstract-down-to-DOMAIN (§18, the canonical remediation for `CROSS_LAYER_DEPENDENCY`); late-bind dependency slot via `_field: list = [initial]` (§19, the planner ↔ orchestrator / viz ↔ EventStore pattern); helper-as-fixture hoist for D-27 cross-block helper-name collision (§20); patch-via-context-manager + helper pair (`_patch_run_ok()` / `_patch_run(handler)`, §21, the `unittest.mock:patch` recipe for tightly-scoped patches); cross-thread `asyncio.Queue` bridge for sync-side vendor callbacks (§22, the Phase 4 channel-adapter foundation). The spec's §4.5.1 requires-import heuristic gains the four recurring stdlib gotchas (`urllib.<sub>` collisions, `uuid:uuid4`, `dataclasses` / `dataclasses:field`, `argparse.REMAINDER`); §4.1.3 surfaces the `provides:` ↔ inner-`def`-names ↔ returned-dict-keys three-way coupling up front with the canonical `"asemble"` typo example; §4.1.4 normalises `abstract: true` lowercase as the canonical boolean literal form (Python-cased `True` / `False` accepted and normalised); the coding-agent handbook gains §1.5 documenting the thin-CLI dispatch pattern and the `argparse.REMAINDER` `--`-swallow gotcha; the quick reference's Bootstrap Pattern section carries the consumer-facing version.

**New error codes (with severity-by-mode).**

| Code | Migration | Dev | Strict | Release | Trigger | Fix |
|---|---|---|---|---|---|---|
| `MIXED_PROVIDES_FORMS` | error | error | error | error | A `provides:` block mixes flat (`- foo`) and structured (`- foo: { returns: ... }`) items | Pick one form per nerve — flat or structured, not both |
| `DUPLICATE_PROVIDES_NAME` | error | error | error | error | The same operation name appears twice in a structured `provides:` block | Rename one of the duplicates |
| `MOCK_KEY_MISMATCH` | warning | warning | error | error | A mock dict literal in a test body has keys diverging from the target nerve's `provides:` set | Align the mock dict's keys with the target's `provides:` |
| `PROVIDES_KEY_MISMATCH` | warning | warning | error | error | A SERVICE-nerve body's terminal `return {...}` literal has a key not in `provides:` (extra-key direction) | Either add the operation to `provides:` or rename the dict key |
| `EXPORTED_HELPER_NOT_FOUND` | error | error | error | error | An `exports_helpers:` entry does not name a `helper` declared in the same module | Either declare the helper in the module or remove the entry from `exports_helpers:` |

All five codes appear in the auto-generated common-errors table in the quick reference (regenerated via `make docs-derived`) and in `docs/spec_traceability.md`.

**Spec file rename.** `docs/s0ma-dsl-spec-v0.14.0.md` → `docs/s0ma-dsl-spec-v0.15.0.md` via `git mv`. The v0.11.0 pointer file now redirects to v0.15.0 (per the one-release-pointer policy). The README's spec link and the docs-table row update in lockstep. Per the one-release-pointer policy, `v0.11.0` stays the single pointer file until the release **after** 0.15.0 — at the next MR boundary, the pointer rotation deletes v0.11.0 and rotates v0.14.0 into the pointer slot.

**IR / manifest schema versions.** Unchanged. The IR stays at the prior `1.2.0`-equivalent shape; the manifest schema stays at `s0ma-build-manifest@1`. Every new field (`category`, `provides_contracts`, `internal_helpers`, `mocks`, `body_kind`, `inline`, `exports_helpers`) is additive under the existing schema.

**Cross-repo dependency.** No companion bump. `s0ma-core` stays at `0.3.0`. The new fields are all DSL-level — they ride through the IR and into the emitted `metadata={}` dict, and the runtime bridge passes them through as opaque dict values. **The full benefit of 0.15.0 is available without re-pinning `s0ma-core`.**

**Consumer action checklist.**

- [ ] Re-pin `s0ma-dsl` to the new branch.
- [ ] Re-run `s0ma build`. Every existing module continues to parse and emit unchanged — no required edits.
- [ ] (Optional) Annotate cells with `category: capability` / `category: behaviour` where the high-level role is meaningful (consumer of `metadata["category"]` is fr3d's MS 19 ConfigDiff classifier).
- [ ] (Optional) Convert SERVICE-nerve `provides:` flat lists to the structured form where per-method contracts would be useful — agents reading `metadata["provides_contracts"]` at runtime no longer need to recover the triples from docstrings or type hints.
- [ ] (Optional) Add `mocks: [<NerveName>]` to test declarations whose bodies build mock dicts; the validator's `MOCK_KEY_MISMATCH` check is the silent-drift backstop.
- [ ] (Optional) Add `internal:` to factory-closure SERVICE nerves so `s0ma inspect` surfaces the private surface alongside the public `provides:` set.
- [ ] (Optional) Convert `cell kind: MODEL visibility: INTERNAL` workarounds for module-private classes to `helper` declarations with a `class` body (no registry side-effect, same access-control rule).
- [ ] (Optional) Convert one-line block helpers to the `helper @inline` shorthand inside the module header's `helpers:` block.
- [ ] (Optional) Add `exports_helpers:` to modules that intentionally expose helpers for sibling test consumption.

---

# 0.13.0 → 0.14.0: Migration walkthrough

The 0.14.0 release lands the s0ma-dsl half of the pre-Phase-2 batch identified ahead of fr3d's Phase 2 (Local) milestone work (10 May 2026). Every change is **additive and backward-compatible** — pre-0.14.0 manifests, transpiled artefacts, and consumer call sites continue to work unchanged. Pairs with `s0ma-core 0.3.0`, which adds the matching registry surface.

**No required consumer action.** Re-pin the toolchain to the new release — from a monorepo checkout, `uv sync --all-packages` — and re-run `s0ma build`; everything continues to work. The points below are *opt-in* surfaces consumers can take advantage of, plus one behavioural ergonomics improvement (unified `s0ma test` manifest) that is invisible to existing call patterns.

**Behaviour-changing surfaces that consumers should be aware of.**

1. **`s0ma test` writes a unified manifest** (PRE-3). Before 0.14.0, `s0ma test` overwrote `build.s0ma.json` with a test-only manifest — production smoke (`docker compose up` reading the manifest via `bootstrap_imports`) then failed with `KeyError: 'workspace'` until `s0ma build .` was re-run. After 0.14.0, the source-roots pass writes `role="source"` entries; the test-roots pass merges with the existing manifest and adds `role="test"` entries. **`bootstrap_imports(build_dir)` with the default `roles=("source",)` returns the same dict whether the last command was `s0ma build` or `s0ma test`.** If your `Makefile` or CI workflow re-runs `s0ma build` between `s0ma test` and a production smoke step, that intermediate step is no longer necessary (and can be removed in a follow-up commit). `--clean` skips the merge, so a clean build always starts from an empty manifest.

2. **`s0ma build` prunes orphan artefacts** (PRE-6). After every successful build (`errors_so_far == 0`), `.py` / `.s0ma.json` / `.s0ma.map` triples whose `<stem>` is no longer in the manifest are removed. **Safety predicate (triple-check guard):** a `.py` is only pruned when all three sibling artefacts exist; hand-written `.py` files without IR/map siblings are never touched. `__init__.py` and `build.s0ma.json` are always preserved. Builds with errors skip the prune. A single info-level line summarises: `Pruned <N> orphan artefact(s): <names>`. If your project carries stale artefacts from a prior build (renamed `.s0ma` files, removed modules), they will be cleaned up on the next successful `s0ma build`. Spec §4.14.2 carries the full contract.

3. **`s0ma test` discovers raw `.py` test files** (PRE-9). Files under `[tool.s0ma].test_roots` that match pytest's collection patterns (`test_*.py` / `*_test.py` / `*_tests.py`) and have **no same-stem `.s0ma` sibling** are added to the pytest invocation alongside `<build_dir>`. `conftest.py`, `__init__.py`, and `.s0ma.cache` / `__s0ma_cache__` subtrees are excluded. **Consumer impact:** if you previously invoked `pytest tests/integration/test_local_smoke.py` separately from `s0ma test` (typical for integration tests that shell out to `docker compose`), drop the extra invocation — `s0ma test` now picks those up. The "no `.s0ma` sibling" rule plus the flat-layout invariant guarantees the discovered raw files and the build-dir collection set are structurally disjoint, so there is no double-collection risk.

**New opt-in surfaces.**

4. **Block-form lists on `uses` / `requires` / `exports` / `raises`** (PRE-7). Long inline `[a, b, c, ...]` lists can now be rewritten in YAML block form (`- entry` per line). The two forms are exactly equivalent (the parser reassembles block into inline before any downstream pass sees it). Use the block form when the list grows past ~5 entries — typical for Phase 2 web-view modules where `uses:` runs 8–15 entries. See spec §4.5.4. **Inline form continues to work without change.**

   ```
   # Inline (still valid)
   uses: [routing.select_evaluator, errors.SignalValidationError]

   # Block (new in 0.14.0)
   uses:
     - routing.select_evaluator
     - errors.SignalValidationError
   ```

5. **`bootstrap_imports(roles=…)` keyword** (PRE-2). Default is `("source",)` — same dict as before. Pass `roles=("source", "test")` to import everything (typical inside a test runner harness); `roles=("test",)` for test-only. Unknown roles raise `ValueError` (caller bug). **Existing call sites need no change.**

6. **`module_path` on `register_constant` / `register_type`** (PRE-8 + s0ma-core 0.3.0 PRE-8). The DSL emitter now passes `self.module_name` automatically into the registration calls, so CONSTANT and TYPE cells get `module_path` populated on their `ComponentSpec` (parity with `register_module` and `@component`). The runtime bridge uses `inspect.signature` to forward only when the framework's registry accepts the kwarg — older `s0ma-core` builds gracefully degrade (no attribution, but no crash). **Consumer-side action:** if your project carries an `_extract_modules` fallback that re-derives `module_path` from `source_file`, that fallback is now redundant and can be removed.

**Documentation: `visibility: TEST` (PRE-4).** Spec §4.2.4 is new: it documents why `visibility: INTERNAL` is wrong for cells consumed only by tests (it blocks cross-module `uses:` from sibling test modules, surfacing `NOT_EXPORTED`) and how `visibility: TEST` closes the trap. Quick-reference visibility section gains a one-line pointer at §4.2.4. **No code change required;** the doc clarifies long-standing behaviour. If your project carries `SimpleNamespace`-based test helpers as a workaround for INTERNAL cells, you can now change those cells' `visibility:` to `TEST` and drop the helpers.

**New parse-time error codes (PRE-7).**

| Code | All modes | Trigger | Fix |
|---|---|---|---|
| `EMPTY_BLOCK_LIST` | error | A block list on `uses`/`requires`/`exports`/`raises` has zero items | Use the inline form `field: []` |
| `INCONSISTENT_BLOCK_LIST_INDENT` | error | Items in one block use different indent columns | Align every `- item` line under the field key to the same column |

Both behave like `PARSE_ERROR` semantically — the malformed module cannot proceed through later passes.

**Spec file rename.** `docs/s0ma-dsl-spec-v0.13.0.md` → `docs/s0ma-dsl-spec-v0.14.0.md` via `git mv`. The v0.11.0 pointer file now redirects to v0.14.0 (per the one-release-pointer policy). The README's spec link and the docs-table row update in lockstep.

**IR / manifest schema versions.** Unchanged. The IR stays at the prior `1.2.0`-equivalent shape. The manifest schema stays at `s0ma-build-manifest@1`; the `role` field is additive under that schema, following the M10 / M12 precedent.

**Cross-repo dependency.** Pair this with `s0ma-core 0.3.0`. The PRE-8 module-path threading and the PRE-10 `module_scoped` opt-in both require the matching registry surface to take effect — the runtime bridge's `inspect.signature` guard means **the s0ma-dsl side is safe to pin independently**, but the full benefit only lands when both versions are installed together.

**Consumer action checklist.**

- [ ] Re-pin `s0ma-dsl` to the new branch.
- [ ] Re-run `s0ma build` to pick up the new emitter output. (Optional — only matters when you want CONSTANT / TYPE cells to carry `module_path` on the spec.)
- [ ] If your CI / `Makefile` runs `s0ma build` between `s0ma test` and a production smoke step, drop that intermediate `s0ma build` invocation.
- [ ] If you invoke `pytest` separately for raw `.py` integration tests under `test_roots`, drop the extra invocation.
- [ ] If you carry `SimpleNamespace`-based test helpers as a workaround for INTERNAL cells, change those cells' `visibility:` to `TEST` and drop the helpers.
- [ ] If your project's `__s0ma_cache__` directories or stale `.py` / `.s0ma.json` / `.s0ma.map` triples have accumulated, they will be pruned on the next successful `s0ma build`. Inspect once and confirm nothing important is at risk; the triple-check safety predicate protects hand-written `.py` files.
- [ ] (Optional) Rewrite long `uses:` lists in block form for readability — purely cosmetic; the inline form remains valid.

---

# 0.12.0 → 0.13.0: Migration walkthrough

The 0.13.0 release closes out the feedback 5–6 cycle. It is a cleanup
pass — every change either fixes a real consumer bug surfaced by the
M20 / F4 smoke recipes or refines a doc-drift-prevention surface. There
is no breaking language change; the IR schema stays at 1.2.0; every
0.12.0 module parses unchanged.

**Three behaviour-changing surfaces that consumers must be aware of.**
Every other change is additive and requires no consumer action.

1. **Default `build_dir` now sanitizes non-identifier characters in
   `[project].name`** (G1 → G3 chain; M20 finding #5 closure). Pre-
   0.13.0, the default `build_dir` was the literal `f"{project_name}_build"`,
   so a project with `[project].name = "kn0wthyself-website-2"` got
   `kn0wthyself-website-2_build/` — a directory whose last path
   component is not a valid Python identifier, breaking the runtime
   bridge's `from <build_dir_basename> import <module>`. Post-0.13.0,
   `re.sub(r"\W", "_", project_name) + "_build"` runs first, so
   hyphens, dots, spaces, and exclamation marks all sanitize to
   underscores automatically. **If your project's `pyproject.toml`
   carries an explicit `[tool.s0ma].build_dir = "<sanitized>_build"`
   line that exists only because of the pre-0.13.0 silent-broken-
   import bug**, you can delete the override — the new default
   produces the same string. Two cases still need explicit
   `build_dir`: `[project].name` starts with a digit, or sanitizes to
   the empty string. Both raise `INVALID_PROJECT_NAME_FOR_BUILD_DIR`
   at project-load time with a remediation.

2. **`s0ma test` now refuses to run against a stale generated
   conftest** (G5; M20 finding #7 closure — detection mechanism).
   Every conftest emitted by `s0ma test-conftest` carries a four-line
   banner (s0ma-dsl version + SHA256 body checksum + a
   do-not-hand-edit notice + a `--force` regeneration pointer). On
   `s0ma test`, the runner reads the banner before invoking pytest
   and refuses to proceed if (a) the banner is unparseable
   (pre-G5 file), or (b) the banner version mismatches *and* the
   recomputed body checksum does not match a registered
   prior-version checksum. **Every pre-0.13.0 generated conftest
   classifies as `unrecognized` and surfaces `STALE_GENERATED_CONFTEST`
   loudly at pre-flight time** — by explicit fail-safe choice (silent
   rewrites of files that may carry hidden customizations are a worse
   failure mode than the loud one-time error). Remediation is one of
   two paths:
   - Delete the existing `conftest.py` and run `s0ma test-conftest`
     again to regenerate cleanly.
   - Run `s0ma test-conftest --force` to regenerate unconditionally
     (recommended when you have customizations to preserve — copy
     them into the new file after regeneration).

   The 0.13.0 G10 update also fixes a long-standing template-content
   bug: the regenerated `conftest.py` patches
   `s0ma_dsl.runtime_bridge.registration.register_module` (the
   canonical surface — Python's `unittest.mock` resolves patch
   targets where they are *used*), not the previous incorrect
   `s0ma.runtime_bridge.registration.register_module` (an attribute
   that has never existed on the framework's `s0ma` package). If your
   pre-0.13.0 generated conftest collected at pytest time but failed
   at fixture setup with `AttributeError: module 's0ma' has no
   attribute 'runtime_bridge'`, regeneration via `s0ma test-conftest`
   (or `--force`) is the fix.

3. **Empty / docstring-only `__init__.py` files now auto-classify as
   `PACKAGE_MARKER` instead of `UNKNOWN`** (G1; M20 finding #3
   closure). `s0ma verify` consults a new
   `is_empty_package_marker(path)` helper that returns `True` iff
   the file's stem is `__init__`, suffix is `.py`, and its body
   (after `ast.parse`) is empty or a single module-level docstring.
   The new `PACKAGE_MARKER` status is informational and hidden from
   default text output (`--verbose` surfaces it). **If your project
   carries `[tool.s0ma].bootstrap_files` entries that exist only to
   silence `UNKNOWN` noise from package markers**, you can strip
   them — keep only real plain-Python entry points (e.g.
   `src/myproj/main.py`) under `bootstrap_files`. For the unusual
   case of an `__init__.py` carrying `__all__` re-exports the author
   wants acknowledged as a marker rather than reported as `UNKNOWN`,
   declare it under the new `[tool.s0ma].package_markers` key. A
   file appearing in both lists raises
   `CONFLICTING_PACKAGE_DECLARATION` at project-load time.

**Three pre-flight errors a misconfigured project may now hit.** Each
fires at project-load time before any subcommand runs (so the failure
mode is immediate and the diagnostic carries the misconfiguration
shape, not a downstream symptom):

- `OVERLAPPING_DISCOVERY_ROOTS` (G2; M20 finding #4 closure) — fires
  when `[tool.s0ma].source_roots` and `test_roots` overlap (in either
  nesting direction), when two roots within either list overlap, or
  when the same path appears in both lists. Pre-0.13.0 this
  misconfiguration silently double-walked the offending `.s0ma` files
  and produced opaque `MODULE_NAME_COLLISION` errors against files
  colliding with themselves. Remediation: either move tests outside
  the source root (`test_roots = ["tests"]`) or narrow `source_roots`
  to disjoint layer subdirectories.
- `INVALID_PROJECT_NAME_FOR_BUILD_DIR` (G3) — fires when `[project].name`
  starts with a digit, sanitizes to the empty string, or when an
  explicit `[tool.s0ma].build_dir` value's basename is not a valid
  Python identifier. Remediation: set `[tool.s0ma].build_dir`
  explicitly to a valid Python identifier.
- `CONFLICTING_PACKAGE_DECLARATION` (G1) — fires when a file appears
  in both `[tool.s0ma].bootstrap_files` and `[tool.s0ma].package_markers`.
  Remediation: declare each file in exactly one list.

**One language-surface refinement that affects multi-source-root
projects** (G4; M20 finding #6 closure). Pre-0.13.0, `s0ma test`'s
per-source-root build pass dispatched each pass with `include_dirs=[]`
— each pass saw only its own files. A project with multiple sibling
source roots (e.g. `source_roots = ["domain", "application",
"presentation"]`) and a `uses: domain.X` reference from
`application/foo.s0ma` could not resolve the cross-root reference;
the build aborted with `DOES_NOT_EXIST` before pytest got invoked.
Post-G4, each per-root pass threads its sibling roots through
`--include` automatically; the per-root iteration is preserved (so
build-error attribution still names the actual offending root).
**If your `[tool.s0ma].source_roots` fans out across multiple layer
directories** and you maintained a hand-rolled
`s0ma build -I <prior-layer> ...`-chained shell wrapper to work
around the resolution gap, you can drop the wrapper — `s0ma test`
now does the right thing unmodified. Single-source-root projects are
unaffected.

**One doc-surface change consumers may notice.** The Common Errors
table in `docs/s0ma-dsl_quick_reference.md` is now derived from the
canonical error-code registry via the new G7a `doc-ref`
`covers: { source: error_codes }` grammar (G7b). The post-G7b table
has 58 rows (one per registered code) with severity-by-mode columns
plus a one-sentence description sourced from `ERROR_CODE_DESCRIPTIONS`
— a structural improvement over the pre-G7b ~20-row hand-authored
table. The bracketed region is auto-generated and surrounded by
HTML comments naming the regenerator (`make docs-derived`). **If
your consumer-side documentation linked to a specific row count or
column header in the pre-G7b table**, update the references to the
new five-column form.

**Verify:**

```bash
cd /path/to/your/project
s0ma check --mode strict
s0ma build
s0ma test
s0ma verify
```

Every step should pass cleanly. If `s0ma test` surfaces
`STALE_GENERATED_CONFTEST`, follow the remediation above. If
`s0ma verify` still surfaces `UNKNOWN` rows for `__init__.py` files,
they carry executable content (commonly a `__version__` assignment) —
either declare them under `[tool.s0ma].package_markers` (acknowledge
as marker) or under `[tool.s0ma].bootstrap_files` (acknowledge as
intentional plain-Python entry point). The two declarative escape
hatches are mutually exclusive — pick the one that matches authorial
intent.

---

# 0.11.0 → 0.12.0: Migration walkthrough

The 0.12.0 release lands a declarative project model, a single flat build
layout, and a project-aware test runner. The four required actions below
take any 0.11.0 consumer project to 0.12.0; the deep-dive sections that
follow document the rationale, edge cases, and optional cleanups for
each. Work top to bottom — the actions are sequenced so each step
unblocks the next.

**Quick checklist:**

1. [Action 1](#action-1--add-tools0ma-to-pyprojecttoml) — Add `[tool.s0ma]` to `pyproject.toml`.
2. [Action 2](#action-2--run-s0ma-migrate-layout) — Run `s0ma migrate-layout`.
3. [Action 3](#action-3--rename-mismatched-stem-modules) — Rename any mismatched-stem modules.
4. [Action 4](#action-4--optional-drop-pytest-from-test-requires) — *(Optional)* Drop `pytest` from test `requires:` and adopt the new language features.

After the four actions, your project is on 0.12.0. The deep-dive
sections (project model details, build-output details, test-runner
details, bootstrap pattern) are reference material — you do not need
to read them linearly.

---

## Action 1 — Add `[tool.s0ma]` to `pyproject.toml`

**Why.** 0.12.0 introduces a declarative project model. Every CLI
subcommand (`s0ma test`, `s0ma build`, `s0ma check`, `s0ma inspect`,
`s0ma verify`, `s0ma transpile`, `s0ma docs ...`, `s0ma examples run`,
`s0ma topo`, `s0ma migrate-layout`) resolves a `S0maProject` first.
The project tells the CLI where source lives, where build artifacts
go, which test directories to walk, and which plain-Python files are
intentional bootstrap exceptions. Without `[tool.s0ma]`, the CLI runs
in legacy mode with a one-line warning per invocation.

**Command:**

```bash
# Edit pyproject.toml; add at minimum:
cat >> pyproject.toml <<'EOF'

[tool.s0ma]
source_roots = ["src"]
EOF
```

That single line is enough to silence the legacy-mode warning. Override
only what differs from the defaults — the full schema lives in
[the configuration reference](../../../docs/reference/configuration.md);
deep-dive details are in the [Project model details](#project-model-details)
section below.

**Migration-recipe gotchas (M20-validated against real consumer projects):**

- **Hyphenated / dotted / spaced `[project].name`? (G3, feedback 5–6
  cleanup).** The default `build_dir` derivation now sanitizes every
  non-word character (`\W`) in the project name to `_` before
  appending `_build`, so a project name like `kn0wthyself-website-2`
  produces `kn0wthyself_website_2_build/` — a valid Python identifier
  the runtime bridge can import via
  `from kn0wthyself_website_2_build import <module>`. Pre-G3 the
  default was the literal `f"{project_name}_build"` and consumers
  with hyphenated names had to set `build_dir` explicitly to avoid a
  silent `ModuleNotFoundError`. Post-G3 the explicit override is no
  longer required for the recoverable shape (hyphens, dots, spaces,
  exclamation marks — anything `\W` matches).

  Two cases still need explicit `build_dir`: (1) `[project].name`
  starts with a digit (e.g. `123foo`) — sanitization can't help
  because Python identifiers can't start with a digit; (2)
  `[project].name` sanitizes to the empty string (defensive — PEP 621
  requires non-empty names so this is rare). Both cases raise
  `INVALID_PROJECT_NAME_FOR_BUILD_DIR` at project-load time with a
  remediation message instructing the author to set `build_dir`
  explicitly to a valid Python identifier.

  Explicit `build_dir` values are validated the same way: `build_dir
  = "out/foo_bar"` is accepted; `build_dir = "out/foo-bar"` raises
  `INVALID_PROJECT_NAME_FOR_BUILD_DIR` because `foo-bar` (the
  importable basename) is not a valid Python identifier.
- **`source_roots` and `test_roots` must be disjoint (G2, feedback 5–6
  cleanup).** Prefer top-level peer directories (`source_roots = ["src"]`
  + `test_roots = ["tests"]`) over nested layouts
  (`source_roots = ["src/<proj>"]` + `test_roots = ["src/<proj>/tests"]`).
  Pre-G2, when the test directory lived inside a source root, `.s0ma`
  files under it were discovered twice — once during the source-root
  walk, once during the test-root walk — producing opaque false-
  positive `MODULE_NAME_COLLISION` errors against files colliding
  with themselves. **Post-G2** the same misconfiguration raises
  `OVERLAPPING_DISCOVERY_ROOTS` at project-load time before any
  subcommand runs; the diagnostic names every offending pair plus the
  two clean-config remediation options:
  1. Move tests outside the source root: `test_roots = ["tests"]` (top
     level).
  2. Narrow `source_roots` to disjoint layer subdirectories:
     `source_roots = ["src/<proj>/application", "src/<proj>/domain", "src/<proj>/presentation"]`.

  The same disjoint-roots rule applies *within* each list (two
  `source_roots` where one is a subpath of the other, or two
  `test_roots` where one is a subpath of the other) and to identity
  (the same path declared in both lists). Multiple offending pairs
  surface together — fix every overlap in one edit, re-run, project
  loads cleanly.
- **Empty / docstring-only `__init__.py` files no longer need
  declaring (G1, feedback 5–6 cleanup).** `s0ma verify` auto
  classifies any `__init__.py` whose body is empty, whitespace only,
  or a single module-level docstring as `PACKAGE_MARKER` —
  informational, hidden from the default text output, no
  configuration required. The previous workaround of enumerating
  every package layer's `__init__.py` under `bootstrap_files` is
  retired.

  For unusual cases — an `__init__.py` carrying `__all__` re-exports
  or other executable content the author wants acknowledged as a
  marker rather than reported as `UNKNOWN` — declare it explicitly
  under the new `[tool.s0ma].package_markers` key:
  ```toml
  package_markers = ["src/myproj/exports/__init__.py"]
  ```
  A file appearing in both `bootstrap_files` and `package_markers`
  raises `CONFLICTING_PACKAGE_DECLARATION` at project-load time —
  declare each in exactly one list.

**Verify:**

```bash
cd /path/to/your/project
s0ma check src/ --mode dev
# Should NOT print: "warning: Operating without project discovery..."
```

---

## Action 2 — Run `s0ma migrate-layout`

**Why.** 0.12.0 emits a single flat layout under `<project>.build_dir`
(no per-layer subdirectories, no implicit dual-headed import paths).
Pre-0.12 consumer projects need their build trees brought forward
once. The migration command is idempotent — safe to run twice in a
row, safe to run on a project that's already migrated.

**Command:**

```bash
# From inside your project root:
s0ma migrate-layout

# Or pointed at a project directory:
s0ma migrate-layout path/to/project_root
```

What it does (5-step recipe — see [Build-output details](#build-output-details) for the rationale):

1. Resolves your project (per `[tool.s0ma]` discovery; falls back to a synthetic project if you have not yet adopted `[tool.s0ma]`).
2. Walks the build directory for any pre-0.12 incremental-cache directory or per-layer subdirs (`presentation/`, `application/`, `domain/`, `infrastructure/`). Deletes them.
3. Walks the project tree for any stray pre-0.12 cache directories (pre-0.12 sometimes anchored to the source dir). Deletes them.
4. Runs a fresh `s0ma build`. The new layout (flat, with `__init__.py` and `build.s0ma.json`) lands.
5. Prints a one-line summary: `Migrated <project>: removed N legacy path(s), emitted M module(s) to <build_dir>.` On a no-op rerun: `Migrated <project>: nothing to clean, emitted M module(s) to <build_dir>.`

**Defensive guard.** If the build directory exists but contains no
recognisable s0ma artifacts (no auto-emitted `__init__.py` marker, no
`.s0ma.json` IR, no recognisable pre-0.12 build artifacts), the
command refuses to delete and surfaces a remediation pointing at your
`[tool.s0ma].build_dir` setting.

**After running:**

1. **Imports.** Replace `from <layer>.<module> import …` with
   `from <build_dir_basename>.<module> import …`. Layer-prefixed
   import paths no longer work — the layout is flat.
2. **`sys.path`.** Ensure your test harness / runtime bootstrap puts
   `<build_dir>` on `sys.path` (or installs it as a Python package).
   The auto-emitted `__init__.py` makes that work without further
   surgery. The recommended pattern is `bootstrap_imports(build_dir)`
   from the [Bootstrap pattern](#bootstrap-pattern-replacing-hand-maintained-module_import_order)
   section below.
3. **CI grep.** Any CI scripts that grepped pre-0.12 cache-directory
   paths in build logs need updating — those strings are gone. The
   build's stdout summary (`Build complete: M modules → <build_dir>
   (manifest: build.s0ma.json)`) is the new parseable surface.

---

## Action 3 — Rename mismatched-stem modules

**Why.** Every `.s0ma` source file's filename stem must equal the
declared `module <name>`. Pre-0.12, the cache key and emitted Python
filename were derived from the source file's stem while `uses:`
consumers resolved imports against the declared `module <name>`. When
the two diverged the build silently produced two artifacts under
different names and imports failed at runtime with no signal at
`s0ma check` or `s0ma build` time. The 0.12.0 transpiler treats
divergence as `MODULE_NAME_STEM_MISMATCH` — error in every strictness
mode (migration, dev, strict, release). See
[ADR-006](adr/ADR-006-canonical-module-identity.md) for rationale.

**Command:**

```bash
s0ma check src/ --mode dev
```

Any file whose stem differs from its `module <name>` will report:

```
ERROR [MODULE_NAME_STEM_MISMATCH]
  Module is declared as 'X' but the source file is named 'Y.s0ma'.
  Remediation: Rename the source file to 'X.s0ma', or change the
  module declaration to 'module Y :: ...'.
```

Pick whichever rename surfaces the canonical name better — both are
mechanically safe. If the module name conveys the public identity
(typical when it appears in cross-module `uses:` references), rename
the file. If the file path carries information the module name does
not, rename the declaration.

**One-time fix per project.** Once every file's stem matches its
declared module name, the rule is stable for the lifetime of the
project. The check fires at error severity in migration mode too — a
migration ladder would invite the same silent-broken-imports bug to
recur. Cache keys are now derived from `module.name`, so the first
0.12.0 build will miss every cached entry; expect a one-time slow
build, then subsequent runs hit normally.

---

## Action 4 — *(Optional)* Drop `pytest` from test `requires:`

**Why.** Pre-0.12 every test module the runner had to discover
carried a `requires: [pytest]` entry — even when the body had no
`pytest.<symbol>` reference — because the dependency model didn't
distinguish runner identity from body-level imports. Stripping
`pytest` from `requires:` to silence `VESTIGIAL_IMPORT` was the
recurring fr3d MS 16/18 papercut. M15 makes runner discovery
first-class via `[tool.s0ma].test_runner` (default `"pytest"`).

**Command:**

For each test module whose body has no `pytest.<symbol>` reference
(no `pytest.raises`, `pytest.fixture`, `pytest.mark`, `pytest.skip`,
etc.), remove the `pytest` entry from `requires:`. Keep `pytest` in
`requires:` when the body uses `pytest.<symbol>` — the existing
`VESTIGIAL_IMPORT` semantics are preserved.

**While you're here**, consider adopting the new 0.12.0 language
surfaces where applicable:

- **`helper` declaration kind** for module-private functions that do
  not warrant a registered component (M13; spec §4.4a). Replaces
  copy-pasted helpers across test modules.
- **`visibility: TEST`** for nerves and cells that production callers
  shouldn't see but tests should reach (M8; spec §4.10.1, §5).
  Replaces the copy-paste-helper-into-test workaround.
- **`content: @file("path")`** on CONSTANT cells for embedding large
  external files (HTML, SQL, prompts) by reference rather than
  inline as a triple-quoted body (M12; spec §4.2.2). Closes the
  kn0wthyself viz-template case.
- **`declares_attributes:` + `[tool.s0ma.attribute_budgets]`** for
  cross-component structural-uniqueness validation (M18; spec §4.13
  + nerve declaration). Closes the fr3d two-`<nav>` regression.
- **`is_page_composer: true`** on nerves to scope the
  `exactly_one_per_page` attribute-budget shape (F3, feedback 5–6
  follow-up; spec §4.1.6). Replaces M18's heuristic page-composer
  detection.

These are additive — no existing `.s0ma` source needs modification to
keep working.

### M18 attribute_budgets: explicit page composers required (F3)

If your project adopted M18's `[tool.s0ma.attribute_budgets]` with the
`exactly_one_per_page` shape, F3 (feedback 5–6 follow-up) introduces a
**required migration step**: the nerve that scopes a "page" must now
carry `is_page_composer: true`. M18's previous heuristic ("a page is a
top-level module in the `uses:` graph") was opaque and had documented
edge cases — test modules looked like top-level pages, projects with
no `uses:` edges had every module flagged, and fully-circular graphs
silently no-opped. F3 replaces the heuristic with explicit declaration.

To migrate: find the nerve that is the top of your render / dispatch
tree (typically the page composer that `uses:` every landmark
renderer) and add `is_page_composer: true` to its declaration. The
validator walks the `uses:` graph from that nerve's owning module to
scope the per-page reachable nerve set. If no nerve carries the
marker while an `exactly_one_per_page` budget is configured,
`NO_PAGE_COMPOSER_DECLARED` fires in every mode — silent no-op is
forbidden. Projects that only use `unique_in_project` or
`warn_on_duplicate` shapes are unaffected.

**Verify:**

```bash
s0ma test
# Build + run all tests via the new project-aware runner.
```

---

## Project model details

`[tool.s0ma]` carries the following keys (all optional; defaults
shown):

```toml
[project]
name = "myproj"  # used to derive build_dir's default

[tool.s0ma]
source_roots = ["src"]                # default: ["src"]
test_roots = ["tests"]                # default: ["tests"]
build_dir = "myproj_build"            # default: "<sanitized_project.name>_build" (G3)
test_runner = "pytest"                # default: "pytest" (only "pytest" supported)
bootstrap_files = [                   # default: []
    "src/myproj/main.py",
    "src/myproj/bootstrap/startup.py",
]

[tool.s0ma.attribute_budgets]         # default: empty (no enforcement)
landmark = "exactly_one_per_page"
route    = "unique_in_project"
```

**Key-by-key notes:**

- `source_roots` — list of directories (relative to project root) holding `.s0ma` source modules. If your repo uses `src/<package>/` layout, the default is correct; if you keep `.s0ma` files at the repo root or in a non-standard subdirectory, list each here.
- `test_roots` — list of directories holding `.s0ma` test modules. Distinct from `source_roots` because test discovery, contract semantics, and visibility rules differ between the two.
- `build_dir` — single directory for transpiled `.py` + `.s0ma.json` + `.s0ma.map` artifacts. Default is derived from `[project].name` via `re.sub(r"\W", "_", name) + "_build"` (G3, feedback 5–6 cleanup) so hyphens, dots, and spaces in the project name sanitize to underscores automatically. Set this explicitly if you want a custom build directory name (e.g. `_build/` or `dist_s0ma/`); the directory's last path component must be a valid Python identifier because the runtime bridge imports via `from <build_dir_basename> import <module>`. Names that cannot be sanitized (digit-start, sanitizes-to-empty) and explicit values whose basename is not an identifier raise `INVALID_PROJECT_NAME_FOR_BUILD_DIR` at project-load time.
- `test_runner` — the test-runner identity. Default `"pytest"`. Today only `"pytest"` is supported; an unsupported value (e.g. `"nose"`) errors at discovery time naming the supported set.
- `bootstrap_files` — list of plain-Python files that are intentional bootstrap exceptions (e.g., `src/myproj/main.py` for an entry-point that must remain pure Python). `s0ma verify` recognises every entry as status `BOOTSTRAP` (informational, hidden by default) instead of `UNKNOWN`; the runtime bridge does not register them as components. Bootstrap files that do not exist on disk yet produce a warning, not an error.
- `package_markers` (G1, feedback 5–6 cleanup) — list of `__init__.py` files explicitly acknowledged as Python package markers. Most package markers do not need declaring: `s0ma verify` auto-classifies any `__init__.py` whose body is empty, whitespace only, or a single module-level docstring as status `PACKAGE_MARKER`. List entries here only for `__init__.py` files carrying `__all__` re-exports or other executable content the author wants acknowledged as a marker rather than reported as `UNKNOWN`. A file appearing in both `bootstrap_files` and `package_markers` raises `CONFLICTING_PACKAGE_DECLARATION` at project-load time.
- `[tool.s0ma.attribute_budgets]` — sub-table mapping `<namespace>` to one of `"exactly_one_per_page"`, `"unique_in_project"`, `"warn_on_duplicate"`. Enforces uniqueness of nerve `declares_attributes:` entries at `s0ma check` / `s0ma build` time. Without an entry, `declares_attributes:` is purely descriptive.

**Compatibility notes:**

- **Additive change.** No `.s0ma` source files require modification to add `[tool.s0ma]`.
- **Legacy mode is preserved.** Existing scripts that invoked `s0ma` without a project model continue to work, with one extra warning line per invocation. The tools still operate on the explicit path / output args you pass.
- **`--project-root`.** A new global flag overrides the discovery start path. Default: current working directory. Use this when invoking `s0ma` from outside the project tree.
- **CI integration.** If your CI runs `s0ma` from a custom working directory, either `cd` into the project root first or pass `--project-root <path>`. Either approach silences the legacy warning.

---

## Build-output details

The 0.12.0 release replaces the legacy two-headed build output (a
pre-0.12 incremental-cache directory plus per-layer subdirectories)
with a **single flat layout** rooted at `<project>.build_dir`. The
new layout fixes the stale-cache shadowing and broken-import-contract
bugs flagged across feedback-5 MS 3–5 and every milestone of
feedback-5.5 (MS00–M14). See
[ADR-007](adr/ADR-007-single-build-layout.md) for the full rationale.

**What changes for adopters:**

- **Imports.** Pre-0.12: `from presentation.scheduler_service import schedule`. Post-0.12: `from <build_dir_basename>.scheduler_service import schedule`. The `<build_dir_basename>` is whatever `[tool.s0ma].build_dir` resolves to (default: `<project_name>_build`).
- **Build artifacts.** Pre-0.12: layer subdirs (`presentation/`, `application/`, `domain/`, `infrastructure/`) under the build dir, plus a pre-0.12 cache directory. Post-0.12: every transpiled module lands at `<build_dir>/<module>.py`, alongside its `.s0ma.json` IR and `.s0ma.map` source map. There are no layer subdirs.
- **Cache location.** Post-0.12 incremental-cache state lives under a hidden `<anchor>/.s0ma.cache/` directory — never on `sys.path`, never importable. The build-output and cache surfaces are deliberately disjoint.
- **Build manifest.** Every successful build emits `build.s0ma.json` at the build root. Schema `s0ma-build-manifest@1`. Names every emitted module with absolute source path, output basename, IR/source-map basenames, and source/output hashes; carries top-level `project`, `build_dir`, `transpiler_version`, `built_at`, and `topological_import_order`. Spec §4.14 has the full schema.

**Compatibility notes:**

- **Breaking change.** Layer-prefixed imports stop working at the 0.12 boundary. There is no migration ladder — the legacy layout was the source of every silent stale-cache bug across feedback-5/5.5/6.
- **Idempotent migration.** `s0ma migrate-layout` is safe to script in CI: run it unconditionally before each build. Once migrated, repeat invocations are no-ops.
- **`s0ma inspect` falls back to legacy paths for *reads*.** During the migration window, `s0ma inspect <pre-0.12-tree>/foo.s0ma` still works against pre-0.12 IR — read-only fallback only. The transpiler never *writes* to the legacy path.

---

## Test-runner details

The 0.12.0 release rewrites `s0ma test` as a project-aware pytest
runner. Pre-0.12, every consumer project running `.s0ma`-authored
tests had to carry one or more workarounds. Each becomes
unnecessary at the 0.12.0 boundary — and several actively interfere
with the new runner. Audit your project for each.

### Workarounds that are now obsolete

#### 1. Custom `conftest.py` mocking the runtime bridge

If your `tests/conftest.py` exists solely to mock `register_module` /
`register_test` / `register_doc_ref` so that pytest can import
transpiled modules without the framework being initialised, you can
delete it. The 0.12.0 runner builds source + tests into the project's
`build_dir`, puts that directory on `PYTHONPATH`, and pytest imports
the result as a real Python package. The runtime bridge is
initialised by the imported modules themselves — no per-project
plumbing required.

If your `conftest.py` does *more* than mock the runtime (e.g.
session-scoped fixtures), keep it — but remove only the
runtime-mocking parts.

**Regenerate generated conftests.** If your project carries a
`conftest.py` previously emitted by `s0ma test-conftest`, regenerate
it after upgrading s0ma versions: the generated file references
specific attributes on the `s0ma` package, and stale conftests can
break test collection (M20 found a real consumer with a months-old
generated conftest that referenced a pre-0.11 `s0ma.runtime_bridge.*`
path). The simplest path: delete the generated file and run
`s0ma test-conftest` again, or just use `s0ma test` (which sets up
the runtime correctly without a conftest at all).

**G5 update (feedback 5–6 cleanup): `s0ma test` now refuses to run
against a stale generated conftest at the canonical location.**
Pre-G5, the failure mode for the kn0wthyself-website-2 case was an
opaque `AttributeError: module 's0ma' has no attribute 'runtime_bridge'`
at pytest import time, several command invocations downstream from
the actual cause (a months-old generated conftest). G5 closes the
loop: every conftest emitted by `s0ma test-conftest` now carries a
four-line banner (s0ma-dsl version + SHA256 content checksum + a
do-not-hand-edit notice + a `--force` regeneration pointer); `s0ma
test` reads the banner before invoking pytest and refuses to proceed
if the banner is missing or the version mismatches *and* the body
has been customized (or the banner version's canonical checksum is
not in the registry — see spec §4.15). The remediation message
surfaces the new `s0ma test-conftest --force` flag, which regenerates
unconditionally for the "I customized intentionally and want a clean
regeneration after preserving the customization" flow. The default
`s0ma test-conftest` (no flag) still refuses to overwrite — mirrors
`s0ma new`'s safety default. Pre-G5 generated conftests have no
banner and are treated as `unrecognized` → loud `STALE_GENERATED_CONFTEST`
error, by explicit fail-safe choice (silent rewrites of files that
may carry hidden customizations are a worse failure mode than the
loud one-time error). See spec §4.15 for the full classifier
contract.

#### 2. Hand-rolled `pytest` wrapper scripts

Pre-0.12 the canonical incantation for running a `.s0ma` test suite
required pointing pytest at the pre-0.12 cache directory and setting
the `python_files` glob. Every consumer project shipped a Makefile /
justfile / shell-script wrapping it — feedback-6 CRIT-3 documented
13 milestones of this workaround in the fr3d project alone. At
0.12.0, the equivalent is just:

```bash
s0ma test
```

The runner discovers the project, builds source + tests to
`<build_dir>`, sets `PYTHONPATH=<build_dir>`, and invokes pytest
with the right `python_files` glob. Delete the wrapper script.

#### 3. `python_files` overrides in `pyproject.toml` or `pytest.ini`

If your project's pytest config carries `python_files = test_*.py
*_tests.py` (or similar) only because the s0ma transpiler emits
files under `*_tests.py` and pytest's default `test_*.py` glob
doesn't match them, you can remove the override. The 0.12.0 runner
sets the glob via `-o python_files='test_*.py *_tests.py'` on the
pytest command line.

If your project genuinely uses both naming conventions (some
hand-written `*_tests.py` files plus `.s0ma`-emitted ones), keep
the override — the runner's `-o` is additive and does not conflict.

#### 4. `--output-dir <test_dir>` invocations that emit `.py` next to `.s0ma`

Pre-0.12, some projects called `s0ma test <test_dir> --output-dir
<test_dir>` so that the transpiled `.py` files landed alongside the
`.s0ma` sources, simplifying pytest's discovery. This pattern is
gone at 0.12.0 — `s0ma test` no longer accepts `--output-dir` and
the build dir is the only output. Source-tree pollution
(committing transpiled `.py` files into the same directory as
authored `.s0ma` files) is now prevented by construction.

If your CI relied on the legacy in-tree `.py` files, switch to
importing from `<build_dir>` instead.

#### 5. `-o`-after-`--` foot-gun workarounds

Pre-0.12 a `s0ma test ... -- -o python_files='*.py'` invocation
greedy-consumed `-o` as `s0ma test`'s own `--output-dir` short flag
and produced a directory literally named `python_files=*.py`.
Workaround scripts that avoided `-o` after `--` (e.g.
`s0ma test ... -- --override-ini python_files='*.py'`) can switch
back to the natural form — at 0.12.0, args after `--` reach pytest
verbatim.

#### 6. `requires: [pytest]` lines added only to satisfy the runner

Per [Action 4](#action-4--optional-drop-pytest-from-test-requires)
above. Strip `pytest` from `requires:` when the body has no
`pytest.<symbol>` reference; keep it when the body uses
`pytest.raises`, `pytest.fixture`, `pytest.mark`, etc.

#### 7. Enumerating every `__init__.py` under `[tool.s0ma].bootstrap_files` to silence `UNKNOWN` noise (G1)

Pre-G1, an `__init__.py` package marker — typically empty or a
single docstring — had no checksum and surfaced as `UNKNOWN` under
`s0ma verify`. The workaround was to list every layer's
`__init__.py` under `[tool.s0ma].bootstrap_files` to silence the
diagnostic, which conflated "this is an intentional plain-Python
entry point" with "this is a Python package marker."

**G1 (feedback 5–6 cleanup)** retires the workaround. `s0ma verify`
auto-classifies any `__init__.py` whose body is empty, whitespace
only, or a single module-level docstring as `PACKAGE_MARKER` via
AST inspection — informational, hidden from the default text
output, no configuration required. Strip the package-marker
entries from `bootstrap_files`; keep only real plain-Python entry
points there. For the unusual case of an `__init__.py` carrying
`__all__` re-exports the author wants acknowledged as a marker,
declare it under the new `[tool.s0ma].package_markers` key
(declarative escape hatch — wins over the auto-classifier's
structural rule).

#### 8. Setting `[tool.s0ma].build_dir` explicitly to dodge hyphenated default (G3)

Pre-G3, the default `build_dir` derivation was the literal
`f"{project_name}_build"`. A consumer with `[project].name =
"kn0wthyself-website-2"` got a default of
`kn0wthyself-website-2_build/` — a directory whose last component is
not a valid Python identifier, so the M6a runtime bridge's
`from <build_dir_basename> import <module>` import silently failed
at runtime. The transpile succeeded, the artifacts landed on disk,
and consumers saw `ModuleNotFoundError` only when they wired up the
runtime bridge (kn0wthyself-website-2 hit this exact shape on its
first migration attempt; M20 finding #5). The workaround was to set
`build_dir` explicitly to an underscored form (e.g. `build_dir =
"kn0wthyself_site_build"`).

**G3 (feedback 5–6 cleanup)** retires the workaround. The default
derivation now sanitizes every non-word character (`\W`) in the
project name to `_` before appending `_build`, so
`kn0wthyself-website-2` produces `kn0wthyself_website_2_build`
without any explicit configuration. Hyphens, dots, spaces,
exclamation marks — every recoverable shape sanitizes
automatically. Two cases still need explicit `build_dir` (digit-
start project names, sanitizes-to-empty); both raise
`INVALID_PROJECT_NAME_FOR_BUILD_DIR` at project-load time with a
remediation message instructing the author to set the override.
Explicit `build_dir` values are validated the same way: the
directory's last path component must be a valid Python identifier.

If your project carries a `build_dir = "<sanitized>_build"` line
that exists only because of the pre-G3 silent-broken-import bug,
delete the line — the sanitized default is the same string.

#### 9. Hand-running per-layer builds with explicit `-I` flags before invoking pytest, when using multiple sibling source roots (G4)

Pre-G4, the per-source-root build pass inside `s0ma test` ran every
configured source root with `include_dirs=[]` — each root's build
saw only its own files. A project with multiple sibling source
roots (e.g. `source_roots = ["domain", "application",
"presentation"]`) and a `uses: domain.X` reference from
`application/foo.s0ma` could not resolve the cross-root reference;
the resolver raised `DOES_NOT_EXIST` and the build aborted before
pytest got invoked. kn0wthyself-website-2 hit this on its first
migration attempt with a per-layer fan-out source-roots
configuration (M20 finding #6). The workaround was to hand-run each
layer's `s0ma build -I <prior-layer> ...` invocations in dependency
order, then invoke pytest directly against the resulting build dir.

**G4 (feedback 5–6 cleanup)** retires the workaround. `s0ma test`'s
source-root loop now threads each pass's *sibling* roots through
`--include` automatically; the per-root structure is preserved (so
build-error attribution still names the actual offending root, not
a sibling). Single-source-root projects produce an empty sibling
list and behaviour is identical to pre-G4. Each per-root invocation
is one-shot, so circular sibling-include patterns (A↔B, A→B→C→A)
cannot induce a cycle. If your project's `[tool.s0ma].source_roots`
fans out across multiple layer directories, drop the hand-rolled
`-I`-chained build script — `s0ma test` now does the right thing
unmodified.

### Compatibility notes

- **Build dir is the only output.** Tests transpile to `<build_dir>` alongside source modules. Both end up in the same flat layout — pytest collects only files matching `python_files`, so the source-module `.py` files are skipped automatically.
- **`--no-cache` is enforced.** The test runner always builds with `--no-cache`. Stale-cache surprises are not tolerated in the test path; the cost is a fresh build every invocation, but fresh builds are fast and the correctness gain is non-negotiable.
- **Pytest version.** The runner invokes `python -m pytest` via subprocess, so it picks up whatever pytest is installed in the active environment. The runner does not import pytest in-process — that would couple `s0ma`'s test command to the consumer's pytest version.

---

## Bootstrap pattern: replacing hand-maintained `MODULE_IMPORT_ORDER`

Pre-0.12.0 every consumer project carried a hand-maintained
`MODULE_IMPORT_ORDER` tuple in `bootstrap/startup.py`, listing
modules in append-only order — a convention that violates topological
sense the moment any new module imports an existing one. M10 retires
that pattern: the build records the dependency-first order in
`build.s0ma.json`; the runtime helper reads it.

**What changes for adopters:**

- `build.s0ma.json` carries `topological_import_order` (computed via Kahn's algorithm with alphabetical tie-breaking — deterministic across runs).
- `s0ma.bootstrap.bootstrap_imports(build_dir)` is the public helper that reads it (it shipped from `s0ma_dsl.runtime` before 0.16.x; that import still works and delegates, with a `DeprecationWarning`). It idempotently inserts `build_dir` at the head of `sys.path`, imports each module via `importlib.import_module`, and returns the resulting `dict[str, ModuleType]`.
- `s0ma topo <project_dir>` prints the order one module per line for debugging.
- Cyclic `uses:` graphs surface `MODULE_DEPENDENCY_CYCLE` at build time (severity `error` in every mode), not as a runtime `ImportError`.

**Step-by-step:**

1. **Locate the hand-maintained list.** It typically lives at the top of `bootstrap/startup.py` (or wherever the project boots its registry):

   ```python
   MODULE_IMPORT_ORDER = (
       "domain_constants",
       "domain_types",
       "application_services",
       "presentation_renderers",
       "http_gateway",
   )

   def startup() -> dict:
       build_dir = Path(__file__).parent.parent.parent / "myproj_build"
       sys.path.insert(0, str(build_dir))
       imported = {}
       for name in MODULE_IMPORT_ORDER:
           imported[name] = importlib.import_module(name)
       return imported
   ```

2. **Replace it with `bootstrap_imports`.** The whole ceremony collapses to one call:

   ```python
   from pathlib import Path
   from s0ma.bootstrap import bootstrap_imports

   def startup() -> dict:
       build_dir = Path(__file__).parent.parent.parent / "myproj_build"
       return bootstrap_imports(build_dir)
   ```

3. **Verify the order is correct.** Run `s0ma topo <project_dir>` and compare against the (now-retired) `MODULE_IMPORT_ORDER`. They should differ only where the hand-maintained list was wrong (a real correctness improvement). Run the project's smoke test or `python -c "from <project>.bootstrap import startup; startup()"` to confirm every module imports cleanly.

4. **Delete the constant.** Once the helper-driven path is exercised by tests, remove `MODULE_IMPORT_ORDER` and the surrounding boilerplate.

**Compatibility notes:**

- **The helper moved to s0ma-core (0.16.x).** `bootstrap_imports` now lives at `s0ma.bootstrap.bootstrap_imports` so a deployed application boots with `s0ma-core` alone — no authoring package on the runtime path (INV-9). `from s0ma_dsl.runtime import bootstrap_imports` keeps working and delegates to it, emitting a `DeprecationWarning` that names the new import. Migration is a one-line edit in the bootstrap file.
- **Older manifests round-trip.** Manifests written before M10 omit `topological_import_order`; the helper falls back to the manifest's `modules` list (alphabetical) so a project rebuilt with 0.12.0 picks up the topological field automatically without a one-shot migration.
- **Cycle detection is loud.** A `uses:` cycle that previously produced silent late-binding behaviour at runtime now fails the build with `MODULE_DEPENDENCY_CYCLE` and names every module in the cycle. Break the cycle by removing one of the `uses:` entries or by introducing a shared lower-layer module.
- **`runtime_bridge` still works.** `s0ma_dsl.runtime_bridge.registration.import_modules_from_manifest` is retained for back-compat with M6b adopters. New code should prefer `s0ma.bootstrap.bootstrap_imports`, which honours the topological order field.

---

# Migrating Hand-Authored Docs to the Documentation Subsystem

The 0.11.0 release introduces three new declaration types — `doc-ref`, `doc-guide`, and `example` — that bring documentation under the same grammar-level enforcement as code. See spec §4.12 and the [Documentation Subsystem](references/documentation_subsystem.md) reference for the language details.

This section explains how to move existing hand-authored Markdown files into the new system without disrupting in-flight work.

## Strategy: Incremental Migration (Option B)

The design overview (§14.7) considered three sequencing options:

- **Option A — Big-bang migration.** Convert every existing `.md` in one release. High risk; long-lived branches; impossible to ship partial value.
- **Option B — Incremental, doc-by-doc.** Migrate one document at a time, keeping both systems in parallel during transition. Each migration ships standalone.
- **Option C — Freeze and start over.** Stop authoring hand-written docs; new docs go through the subsystem only. Old docs eventually rot.

**The committed v1 path is Option B.** Each document is migrated when it next needs a substantive update, with a deprecation marker placed in the hand-authored file as soon as a `doc-ref` or `doc-guide` covers the same surface.

## When to Migrate, When to Leave Alone

Not every Markdown file should become a `.s0ma` declaration. Apply this decision tree per document:

```
Does the doc name registered components (nerves, cells, modules)?
├── No → Leave hand-authored. Conceptual / framework teaching is exempt under P7.
└── Yes → Migrate.
    ├── Doc is pure projection (API reference, registry catalogue)?     → doc-ref
    ├── Doc is narrative (user guide, walkthrough, migration guide)?    → doc-guide + embedded examples
    └── Doc shows how to call something?                                 → example (likely embedded by a doc-guide)
```

If the document mixes conceptual teaching with named-component claims, **split it.** Move the named-component sections into `doc-guide` declarations; leave the conceptual prose hand-authored. The split is almost always clearer than the original mixed file.

## Per-Document Migration Status

The current repo has the following hand-authored documents. This table is the authoritative migration tracker — update it as you migrate each doc.

> **Stale as of 2026-08-30, kept as the record of what was planned.** The paths
> below are pre-monorepo: the spec has rotated several times since v0.11.0, both
> user guides were merged into one canonical guide homed with `s0ma-core`, and
> `plans/TODO.md` now sits under `docs/archive/pre-monorepo/`. For what each
> document is today and which check keeps it honest, read
> [the map of record](../../../docs/README.md). Re-deriving this table belongs
> with the wider self-hosting work July's review filed as DOC-7.

| Document | Type | Migration plan |
|----------|------|----------------|
| `docs/s0ma-dsl-spec-v0.11.0.md` | Conceptual / framework teaching | **Stays hand-authored — exception under P7.** This is the language definition itself; meta-circularity makes self-hosting it pointless until the subsystem is fully bootstrapped (post-v1). |
| `docs/s0ma_user_guide_condensed.md` | Mixed | Split per section. Sections that name framework components (`@component`, `Contract`, `register_doc_ref`, `SelfModelInterface`, etc.) become `doc-guide` declarations under `s0ma-core`. Generic "what is a component" teaching stays hand-authored. |
| `docs/s0ma_user_guide.md` | Mixed | Same treatment as the condensed version. Migrate together so the two stay aligned, or deprecate one in favour of the other. |
| `docs/reference/dsl_patterns_guide.md` | Narrative + named components | `doc-guide` declarations per pattern (SERVICE, EXCEPTION cell, abstract adapter, etc.) with embedded `example` declarations demonstrating each. |
| `docs/migration_guide.md` (this file) | Mixed | Conceptual sections (Strategy, Step-by-Step, Strictness Progression) stay hand-authored. Per-document migration status (this table) becomes a `doc-ref` once the registry exposes it cleanly. |
| `docs/s0ma-dsl_quick_reference.md` | Reference + examples | Migrate to a `doc-ref` driven by the actual grammar / declaration registry, with `example` declarations replacing the inline code blocks. |
| `docs/agent_system_prompt.md` | Conceptual / instructional | Stays hand-authored — instructions for an LLM, not factual claims about components. |
| `docs/coding_agent_handbook.md` | Mixed | Sections describing the transpiler's own architecture become `doc-guide`s; the prescriptive workflow guidance stays hand-authored. |
| `docs/release_checklist.md` | Process | Stays hand-authored. |
| `docs/adr/*.md` (ADRs 001–004) | Historical rationale | Stay hand-authored — ADRs are immutable historical records, not facts about the current system. |
| `docs/historical/*` | Archive | Stays hand-authored. |
| `docs/s0ma-core-spec-v0.2.0.md` | External spec | Stays hand-authored. The canonical copy lives at `packages/s0ma-core/docs/s0ma-core-spec-v0.2.0.md`; the dsl-side duplicate (a stale 2026-04-24 snapshot) was removed 2026-06-11. |
| `docs/references/documentation_subsystem.md` | Conceptual / framework teaching | Stays hand-authored for v1. **Self-hosting target post-v1** — once the subsystem stabilises, this document migrates to a `doc-ref` so the documentation system documents itself. Tracked in `plans/TODO.md`. |

## Per-Document Migration Checklist

When migrating a hand-authored document, follow this checklist:

```
1. IDENTIFY surface
   [ ] Read the doc end-to-end. Annotate every component name (nerve::X,
       cell::Y, module::Z) and every code example.
   [ ] Mark sections as one of: doc-ref candidate, doc-guide candidate,
       example candidate, hand-authored (P7 exception).

2. CARVE OUT examples first
   [ ] For each code block, write an `example` declaration in a docs
       module (e.g., `docs.user_guide_examples`). Set `demonstrates:` to
       the components shown. Pick a `runs_in:` value the test pipeline
       can execute.
   [ ] Run `s0ma examples run` — every example must pass.

3. WRITE the doc-guide
   [ ] Create the `doc-guide` declaration. Set `output:` to the same
       path as the hand-authored file (or a sibling under
       `docs/generated/`).
   [ ] Replace every named-component reference with `{{kind::name}}`.
   [ ] Replace every code block with `{{example::name}}`.
   [ ] Move every factual claim that isn't a `{{...}}` reference into
       `asserts:`.
   [ ] Run `s0ma docs verify` — zero diagnostics required.

4. RENDER and compare
   [ ] Run `s0ma docs render`. Compare generated output to the
       hand-authored original. Differences are either improvements
       (factually accurate where prose was vague) or regressions
       (lost narrative). Address regressions in the doc-guide body.

5. DEPRECATE the hand-authored file
   [ ] Replace the hand-authored content with a one-line pointer to
       the generated output. Keep the file for one release cycle so
       external links don't 404, then remove.

6. WIRE into CI
   [ ] Add `s0ma docs check-drift` to the CI pipeline. From this
       point, drift between the .s0ma source and the rendered output
       fails the build.
```

## Deprecation Policy

When a hand-authored file is replaced by a generated `doc-ref` or `doc-guide`:

1. Replace the file's body with a one-line pointer (`This document moved to docs/generated/<name>.md.`) plus a removal-after marker (`Will be removed after release X.Y.0.`).
2. Update any links in the rest of the repo to point at the new location.
3. After one release cycle, delete the pointer file. The migration is complete.

This mirrors the policy used for the spec rename (`s0ma-dsl-spec-v0.10.1.md` → `s0ma-dsl-spec-v0.11.0.md`): the old name stays as a one-line pointer for one release, then disappears.

## What Not to Do

- **Don't migrate ADRs.** They're historical records. Their value is that they captured a decision at a specific moment.
- **Don't migrate the spec.** `docs/s0ma-dsl-spec-v0.11.0.md` is the language definition; documenting it through itself is meta-circular and brittle.
- **Don't migrate instructional prose for LLMs.** `agent_system_prompt.md` exists to instruct an LLM, not to describe components. Migrating it would force every prompt sentence into the `{{...}}` / `asserts:` straitjacket — net negative.
- **Don't half-migrate.** A doc that mixes generated and hand-authored sections in the same file fails the deterministic-rendering contract. Split, don't blend.

