# Changelog

All notable changes to s0ma-core are tracked here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

The `0.2.0-alpha.*` series covers incremental delivery of the documentation subsystem described in `plans/documentation_subsystem_implementation_plan.md`. Those per-milestone entries are preserved below under *Milestone history* for provenance; the consolidated `[0.2.0]` section is the release-facing summary.

> From 0.5.0 the canonical changelog is the repo root `CHANGELOG.md`; this file is preserved for ≤ pre-monorepo history.

## [0.4.0] — 2026-05-11

The 0.4.0 release lands the s0ma-core half of the post-Phase-2 batch. It pairs with `s0ma-dsl 0.16.0` (cut concurrently). Only one behaviour-bearing item lands on the core side — the import-hook anomaly surface — so re-pinning is mandatory only for consumers that intend to subscribe to the new observability surface; otherwise the 0.3.0 contract is preserved unchanged.

### Added

- **`ComponentRegistry.import_hook_anomalies` surface (POST-1).** Every
  foreign-code violation the s0ma import hook detects — unregistered
  public entities and stale documentation markers, in both strict and
  lenient modes — is now appended to a registry-side anomaly buffer
  and dispatched to every callback registered via
  `subscribe_import_hook_anomalies(callback) -> Callable[[], None]`.
  The buffer is consumed via the `import_hook_anomalies` property
  (returns a defensive copy in detection order) and emptied via
  `clear_import_hook_anomalies()`. The pre-existing
  `UnregisteredComponentError` (strict) and warning (lenient)
  behaviour is preserved unchanged — the anomaly surface is additive
  observability. Append, snapshot, clear, subscribe, and subscriber
  dispatch all run under `ComponentRegistry._lock`, so concurrent
  registration + anomaly recording from multiple threads cannot lose
  records or interleave dispatches.
- **`ImportHookAnomaly` frozen dataclass** — re-exported from `s0ma`.
  Fields: `name` (fully qualified module name), `description`
  (human-readable finding), `severity` (`AnomalySeverity.ERROR` for
  strict-mode detections, `WARNING` for lenient-mode detections),
  `layer` (`Layer | None` populated from registry module metadata
  when available; `None` is the common case since most detections
  fire before module registration completes), `detected_at`
  (UTC timestamp, populated automatically). `to_dict()` produces a
  JSON-shape with enum names serialised. Records are frozen and
  hashable — safe to keep in sets or use as dict keys.

## [0.3.0] — 2026-05-10

The 0.3.0 release lands the s0ma-core half of the pre-Phase-2 improvements identified ahead of fr3d's Phase 2 (Local) milestone work. All changes are additive and backward-compatible — pre-existing registries, snapshots, and SQLite databases load unchanged.

### Added

- **`s0ma.self_model.diff`** — new module exposing
  `compute_registry_diff(prior, current) -> StructuredDiff`. Two
  registry snapshots compare into `added` / `removed` / `modified`
  lists of `ComponentChange` records; each change carries the
  before/after specs plus a `field_changes` dict keyed by spec field
  with `(before_value, after_value)` pairs. Comparison delegates to
  `s0ma.hashing.canonical.canonicalize` so dict / set ordering does
  not produce false positives, and so the diff agrees with the
  content-hash subsystem about deeper equality. The
  `registered_at` timestamp is excluded from comparison. Output is
  deterministically sorted by component name.
- **`module_scoped: bool` field on `ComponentSpec`** (default
  `False`) — opt-in flag that asks the registry to store this spec
  under a module-qualified `"<module_path>::<name>"` key rather than
  the bare `name`. Two specs sharing a bare name across different
  modules can coexist when both opt in. The spec's own `name` field
  remains the bare name regardless of keying.
- **`module_path` keyword on `register_constant` /
  `register_type`** — the s0ma-DSL emitter now passes the owning
  module's canonical name through these helpers so the resulting
  `ComponentSpec.module_path` is populated, parity with
  `register_module` and `@component` registrations. Empty string is
  the back-compat default.

### Changed

- **`ComponentRegistry.get` / `contains` / `__contains__`** accept
  either bare or qualified identifiers. Direct hits resolve in O(1);
  bare lookups for module-scoped specs succeed when the bare name
  resolves uniquely and return `None` otherwise (deliberate explicit
  failure — never guess across modules).
- **SQLite persistence** — the `components` table gains a
  `module_scoped INTEGER DEFAULT 0` column. Module-scoped specs
  persist under their qualified key; bare-keyed specs (the default)
  are persisted unchanged. Legacy databases are migrated additively
  via `ALTER TABLE` on first load.
- **`ComponentSpec.to_dict`** — emits `"module_scoped": True` only
  when set; legacy specs serialise byte-identically.

## [0.2.0] — 2026-04-24

The 0.2.0 release delivers the runtime half of the s0ma documentation subsystem. A transpiled `.soma` file that declares a `doc-ref`, `doc-guide`, or `example` now imports cleanly under s0ma-core's import hook, registers to the correct registry store, persists through SQLite, serializes through `RegistrySnapshot`, is queryable through `SelfModelInterface` / REST / MCP, and — for `example` — executes in a subprocess-isolated test pipeline. Transitive content hashes power drift detection end-to-end.

### Added

- **Documentation registration dataclasses** (design §§6, 10.1):
  `SourceSpan`, `EntityRef`, `FilterExpr`, `Section`, `AssertExpr`,
  `DocRefRegistration`, `DocGuideRegistration`, `ExampleRegistration`.
  All frozen; re-exported from `s0ma`.
- **Registry stores** `_doc_refs`, `_doc_guides`, `_examples` with
  matching SQLite tables (payload-JSON layout).
- **Public registration API** (design §10.2):
  `register_doc_ref`, `register_doc_guide`, `register_example` —
  both as methods on `ComponentRegistry` and as top-level wrappers on
  `s0ma`. Validation enforced at the boundary (`format` in
  `{markdown, html, json}`, `output` a non-empty relative path,
  `demonstrates` required and non-empty for examples, `runs_in` in
  `{standalone, pytest, integration}`).
- **Import-hook marker attributes** (design §10.3):
  `__soma_doc_ref__`, `__soma_doc_guide__`, `__soma_example__`
  — iterable-of-names (or single-name `str` shorthand) advertised by
  generated modules. Unresolved markers raise
  `UnregisteredComponentError` in strict mode. Attribute names are
  exposed as public constants (`DOC_REF_MARKER_ATTR`,
  `DOC_GUIDE_MARKER_ATTR`, `EXAMPLE_MARKER_ATTR`) so the DSL emitter
  does not hard-code strings.
- **`RegistrySnapshot` fields + reverse indices** (design §10.4):
  `doc_refs`, `doc_guides`, `examples` populated by `snapshot()`;
  `examples_for(entity_ref)` / `docs_for(entity_ref)` accepting
  either an `EntityRef` or a `"module::name"` / bare-name shortcut;
  new `DocsForResult` wrapper with separate `.refs` / `.guides` lists,
  `to_dict()`, and `is_empty()`.
- **`SelfModelInterface` extensions** (design §10.5):
  `describe_docs()`, `describe_doc(name)`,
  `get_docs_for_component(name)`, `get_examples_for_component(name)`,
  and `get_drift_status(*, transpiler_version)`. Seven new formatters
  in `s0ma.self_model.formatters`. `ImpactReport` carries
  `affected_docs` / `affected_examples`, surfaced by
  `format_impact_report`.
- **Example execution subsystem** `s0ma.examples` (design §10.8):
  `ExampleRunner`, `ExampleResult`, `ExampleDispatcher`,
  `DispatchOutcome`, `TimeoutResult`, `run_subprocess_with_timeout`,
  `run_all_examples`, `DEFAULT_TIMEOUT_SECONDS = 30`,
  `INTEGRATION_CMD_ENV_VAR = "SOMA_INTEGRATION_CMD"`,
  `ExampleTimeoutError`. Every example runs in a child process so
  timeouts can be enforced cross-platform and in-body `@component`
  registrations cannot contaminate the parent registry. Opt-in pytest
  plugin via `pytest --s0ma-examples` + `s0ma_example_timeout` ini key
  (entry point `s0ma_examples` on `pytest11`).
- **Content-hash subsystem** `s0ma.hashing` (design §10.9):
  `canonicalize(value) -> bytes` (deterministic byte serializer with
  sorted dict keys, canonical-bytes-sorted sets, NFC string
  normalization, and explicit length prefixes to prevent concatenation
  smearing); `content_hash(doc_registration, snapshot, *,
  transpiler_version) -> str` (transitive SHA-256 returning
  `"<HASH_ALGORITHM_VERSION>:<hex>"`); `HASH_ALGORITHM_VERSION = "1"`.
  Operational metadata (`registered_at`, `source_file`) is excluded
  from the transitive walk so cross-machine checkouts hash
  identically.
- **REST endpoints** (design §10.6; requires `[api]` extra):
  `GET /self/docs`, `GET /self/doc/{name}`, `GET /self/examples`,
  `GET /self/example/{name}`, `GET /self/drift` (with optional
  `?transpiler_version=` parameter feeding a real transitive
  re-hash). Pydantic response models: `DocListResponse`,
  `DocDetailResponse`, `ExampleListResponse`, `ExampleDetailResponse`,
  `DriftResponse`, `DriftEntry`.
- **MCP surface** (design §10.7; requires `[mcp]` extra): resources
  `s0ma://docs/registered-docs`, `s0ma://model/examples-for/{component}`,
  `s0ma://model/docs-for/{component}`; tool `get_examples_for`.
- **Agent rules A-8 and A-9** in `docs/s0ma_user_guide.md` §C.10
  (design §10.10):
  - A-8 (VERIFIED) — check `get_docs_for_component` /
    `get_examples_for_component` and update affected docs / examples
    atomically.
  - A-9 (ENFORCED) — never embed a raw code sample in a doc-guide
    body; always reference a registered example via
    `{{example::<name>}}`.
- **User-guide Section 10** — *Documentation Subsystem (Runtime
  Surface)* — covering the three registration kinds, marker
  attributes, query API, snapshot extensions, example runner,
  content-hash subsystem, REST / MCP surfaces, and transition notes.
- **`docs/references/documentation_subsystem.md`** — stable symbol /
  endpoint / resource inventory. Transitional (hand-authored, marked
  for regeneration once the DSL's `doc-ref` emitter lands on it).
- **Top-level re-exports on `s0ma`:** `DocsForResult`,
  `HASH_ALGORITHM_VERSION`, `canonicalize`, `content_hash`.

### Changed

- `RegistrySnapshot.to_dict()` / `.to_json()` / `.describe()` emit
  `doc_refs` / `doc_guides` / `examples` only when the corresponding
  stores are non-empty, so legacy snapshot consumers see no schema
  churn until the subsystem is in use. `snapshot_at` remains the
  trailing key.
- `SelfModelInterface.get_drift_status(*, transpiler_version)` now
  recomputes every stored content hash via `s0ma.hashing.content_hash`
  and reports stored-vs-recomputed divergence.
  `format_drift_status(snapshot, *, recomputed_hashes=None)` gained an
  optional `recomputed_hashes` kwarg with graceful degradation to the
  v1 hash-presence report.
- `compute_impact_analysis(...)` and `format_impact_report(...)`
  surface "Affected documentation" and "Affected examples" sections
  when the M4 reverse indices produce matches.
- Bootstrap framework-component count raised from 52 → 59 across this
  release: `S0maDSLLoader` (+1, pre-existing blind-spot fix in M3B),
  `DocsForResult` (+1, M4), and the five new `s0ma.examples`
  framework components `ExampleRunner` / `ExampleResult` /
  `ExampleDispatcher` / `DispatchOutcome` / `TimeoutResult` (+5, M6).
- `tests/test_phase3_capstone.py::test_bootstrap_component_count_is_final`
  and `tests/test_mcp_server.py::TestCreateMcpServer::test_server_lists_all_tools`
  updated to track the new bootstrap count and the new
  `get_examples_for` MCP tool respectively. These are the only
  existing tests modified under this release; both are enumeration
  tests whose expected sets must track new registrations.
- README promoted to "0.2.0: Documentation Subsystem runtime — Complete"
  with a feature-list bullet for the new surface.

### Fixed

- Registered `S0maDSLLoader` in `_bootstrap.py` alongside `S0maFinder`
  / `S0maLoader`, resolving 5 pre-existing bootstrap-verifier blind-
  spot failures in `tests/test_bootstrap.py`, `tests/test_integration.py`,
  and `tests/test_self_model.py`.
- 13 `mypy --strict` errors in `src/s0ma/api/` cleared via scoped
  optional-import overrides for `fastapi.*`, `pydantic.*`, `mcp.*`
  and `disallow_subclassing_any = false` on the two API modules.
- 104 `ruff check` errors across `src/` (5) and `tests/` (99) resolved
  without adding any `# noqa` to new code. Included SIM117
  nested-`with` collapses, F401 side-effect-import refactors to
  `importlib.import_module`, E501 long-line wraps, E741 ambiguous
  name renames, and one F811 collision (`TestRegistration` import
  from `s0ma.models` removed from `test_registry.py`).

### Migration notes

- Nothing will call the new `register_doc_*` functions in practice
  until `s0ma-dsl` M6 (emitter) lands. All of 0.2.0 is validated via
  direct Python registration in tests. See
  `plans/documentation_subsystem_implementation_plan.md` §8 for the
  bootstrap / chicken-and-egg analysis and the s0ma-dsl plan for the
  cross-repo milestone ordering.
- `docs/references/documentation_subsystem.md` is the one deliberate
  transitional hand-authored artifact this release leaves in the
  tree. It will be regenerated from a `doc-ref` declaration once the
  DSL's `doc-ref` emitter lands. Do not migrate it piecemeal — the
  migration is owned by s0ma-dsl M8.
- Existing JSON consumers of `RegistrySnapshot.to_dict()` /
  `.to_json()` see no schema churn: the new `doc_refs` / `doc_guides`
  / `examples` keys are omitted when their stores are empty. Consumers
  that want to opt in should check for the keys rather than assume
  them.
- The drift-check API gained a `transpiler_version=` kwarg. Callers
  that invoke `SelfModelInterface.get_drift_status()` without an
  argument default to `"unknown"` and continue to work; CI drift
  checks should feed the actual transpiler version that produced the
  stored hashes.
- Bumping `HASH_ALGORITHM_VERSION` invalidates every previously-
  stored hash. Do not bump it casually — the next CI drift check
  will flag every doc in the tree.

### Design decisions (release-level summary)

- **Registry key is the bare `name`** (matching `register_test`), not
  `<module>::<name>`. Module is stored but not part of the key.
  Evolvable to canonical keying if real collisions emerge.
- **`docs_for` returns a structured `DocsForResult`** rather than a
  `list[DocRef | DocGuide]` union. Callers iterate `.refs` / `.guides`
  without runtime `isinstance` dispatch. Resolves plan §11 open
  question.
- **Pytest example plugin is opt-in** (`--s0ma-examples`), not
  opt-out. The `pytest11` entry point is registered unconditionally
  so `pytest --help` documents the flag; the plugin is a no-op when
  the flag is unset. Resolves plan §11 open question.
- **Subprocess isolation for every example dispatch mode.** Timeouts
  require it; in-body `@component` registrations must not
  contaminate the parent registry; the plan's subtask mandates it.
- **Timeout as a result field, not an exception.** `run_subprocess_with_timeout`
  never raises `subprocess.TimeoutExpired`; `ExampleTimeoutError` is
  stringified onto `ExampleResult.error`. Otherwise `run_all` would
  short-circuit on the first hang.
- **Operational metadata excluded from the transitive content hash.**
  `ComponentSpec.registered_at` and `source_file` are projected out
  so two developers' checkouts hash identically.
- **Formatters and the two `s0ma.hashing` public functions live on
  `_KNOWN_UNREGISTERED_UTILITIES`, not in the registry.** They are
  module-level pure functions; registering ~20 trivial helpers
  would dilute the registry without adding verification value.
  Class-level surfaces (`SelfModelInterface`, `ExampleRunner`, etc.)
  remain the registered entities.

### Test suite

Grew from the pre-0.2.0 baseline (1007 tests, Phase 3 Capstone) to
1523 passing + 1 skipped at the M8 boundary (0.2.0-alpha.11). M9 adds
no new tests — it is documentation-only.

---

### Milestone history

The per-milestone `0.2.0-alpha.*` entries below are preserved for
provenance. They are not part of the release-facing changelog and may
be elided by downstream packagers.

## [0.2.0-alpha.11] — 2026-04-24

Documentation subsystem Milestone 8 — REST + MCP surfaces for the
documentation stores.

### Added
- REST endpoints (wrappers over `SelfModelInterface` / `RegistrySnapshot`):
  - `GET /self/docs` — registry-wide overview returning both
    `text` (via `describe_docs()`) and structured `doc_refs` /
    `doc_guides` / `examples` lists with counts.
  - `GET /self/doc/{name}` — doc-ref or doc-guide detail. 404 when
    the name is not registered as either. Returns `kind` so clients
    can distinguish a ref from a guide without guessing.
  - `GET /self/examples` — all registered examples (name, `runs_in`,
    `demonstrates`).
  - `GET /self/example/{name}` — single example detail including
    body and source span. Uses `format_example_detail` for the
    natural-language text.
  - `GET /self/drift` — transitive drift status. Accepts optional
    `?transpiler_version=` query param (mirrors
    `SelfModelInterface.get_drift_status`). Returns counts plus a
    structured `drifted` list (kind / name / stored_hash /
    recomputed_hash) and `missing_hashes` list. Recomputes every
    stored hash via `s0ma.hashing.content_hash` — full M7 transitive
    walk, not a placeholder.
- Five Pydantic response models next to the existing `*Response`
  block: `DocListResponse`, `DocDetailResponse`, `ExampleListResponse`,
  `ExampleDetailResponse`, `DriftResponse` (plus `DriftEntry`).
- MCP resources:
  - `s0ma://docs/registered-docs` (static) — serves
    `SelfModelInterface.describe_docs()` as the live registry-wide
    documentation overview.
  - `s0ma://model/examples-for/{component}` (templated) — examples
    whose `demonstrates` list covers the named component.
  - `s0ma://model/docs-for/{component}` (templated) — doc-refs +
    doc-guides covering the named component.
- MCP tool `get_examples_for(component)` — explicit mirror of the
  `examples-for` templated resource. Rationale: not every MCP client
  exposes templated-resource reads directly; a tool round-trip keeps
  the surface usable from plain tool-call clients (the primary
  consumer agents that drive rule A-8).

### Changed
- `tests/test_mcp_server.py::TestCreateMcpServer::test_server_lists_all_tools`
  expected-set extended with `get_examples_for`. Deliberate test
  change — it is an enumeration test, so adding a tool requires
  updating the enumeration; no semantic change to existing behavior.

### Notes
- REST `GET /self/doc/{name}` returns 404 on miss instead of the
  informational string that `SelfModelInterface.describe_doc`
  returns. The M5 interface contract (text, never raises) is
  preserved inside `describe_doc`; the REST layer translates missing
  to 404 so HTTP clients get canonical status semantics, matching
  the existing `GET /self/component/{name}` behavior.
- Drift endpoint carries a `transpiler_version` query param rather
  than a request body because `GET` is idempotent / cacheable and
  the parameter is purely an input to the hash recompute, not a
  mutation.
- M8 adds no new registered components. The new REST endpoint
  functions and MCP resources/tools are closures defined inside
  `create_app()` / `create_mcp_server()`; they are not public
  module-level names that would need to register as components. The
  existing `s0ma.api.create_app` / `s0ma.api.create_mcp_server`
  entries in `_KNOWN_UNREGISTERED_UTILITIES` continue to cover them.

## [0.2.0-alpha.10] — 2026-04-24

Documentation subsystem Milestone 7 — deterministic transitive
content-hash subsystem.

### Added
- `s0ma.hashing` subpackage implementing plan M7. Single source of
  truth for fingerprinting documentation registrations and their
  transitive registry dependencies.
- `canonicalize(value) -> bytes` — deterministic byte serializer for
  `None`, `bool`, `int`, `float`, `str`, `bytes`, `list`, `tuple`,
  `dict`, `set`/`frozenset`, any `Enum` subclass, and any `@dataclass`
  instance. Dict keys are sorted; sets are sorted by their elements'
  own canonical form; strings are NFC-normalized before UTF-8
  encoding; floats are emitted via `repr` (round-trip stable); every
  value carries a one-byte type tag plus an explicit length prefix to
  prevent smearing / collision across concatenation. Unsupported
  types raise `TypeError` — silent fallback to `repr` would break
  determinism.
- `content_hash(doc_registration, snapshot, *, transpiler_version) ->
  str` — transitive SHA-256 over (a) a version prefix, (b) the
  registration itself with its own `content_hash` field zeroed, and
  (c) the transitive closure of the registry state it references.
  Returns a lowercase hex digest prefixed with the algorithm version
  (e.g. `"1:4f1ac..."`), so stored hashes are self-identifying when
  the algorithm version is bumped. DocRefs resolve `covers` filter
  expressions against the current snapshot; DocGuides resolve
  `covers` EntityRefs and `examples` EntityRefs and include each
  referenced example verbatim.
- `HASH_ALGORITHM_VERSION` constant (currently `"1"`) — bump whenever
  the canonicalization scheme or transitive-walk rules change, which
  invalidates every previously-stored hash and forces a
  CI-visible re-hash on the next drift check.
- Top-level re-exports on `s0ma`: `HASH_ALGORITHM_VERSION`,
  `canonicalize`, `content_hash`.

### Changed
- `SelfModelInterface.get_drift_status(*, transpiler_version="unknown")`
  now recomputes the transitive content hash for every registered
  doc-ref and doc-guide that carries a stored hash and reports drift
  — stored vs. recomputed — in the output. The M5-era v1 placeholder
  (hash-presence only, plus a forward-reference to "the M7
  content-hash subsystem") is replaced with a real divergence report.
  Method signature gained a kw-only `transpiler_version` so CI drift
  checks can feed the transpiler version that produced the stored
  hashes.
- `format_drift_status(snapshot, *, recomputed_hashes=None)` carries
  an optional `recomputed_hashes` dict keyed by
  `"<kind>:<name>"`. When provided, the formatter adds a drift-check
  section listing every divergence and the stored/recomputed values.
  When omitted, it degrades to the v1 hash-presence report so any
  caller that has not yet wired the content-hash utility keeps
  working.
- `_verifier._S0MA_PUBLIC_MODULES` extended with the three new
  `s0ma.hashing.*` modules.
- `_verifier._KNOWN_UNREGISTERED_UTILITIES` extended with
  `s0ma.hashing.canonical.canonicalize` and
  `s0ma.hashing.content_hash.content_hash`. Both are module-level
  pure functions; registering them as components would introduce a
  cycle through `models.py` without adding verification value.
  Follows the same pattern as the `self_model.formatters.*` entries
  and `examples.runner.run_all_examples`.
- `tests/test_self_model_docs.py::TestDriftStatus::`
  `test_populated_registry_reports_hash_presence` updated: the M5
  placeholder assertion on the literal `"M7 content-hash subsystem"`
  is replaced with real drift-check expectations. This is a
  deliberate M5→M7 transition — the old assertion was explicitly
  placed as a forward reference to be replaced when M7 landed.

### Tests
- New file `tests/test_content_hash.py` with 22 cases covering:
  `canonicalize` primitives / dict-key insensitivity / list-order
  sensitivity / NFC normalization / length-prefix anti-smearing /
  set determinism / dataclass declaration-order semantics / typed
  rejection of unsupported types; `content_hash` digest shape and
  version prefix; rejection of `ExampleRegistration` inputs; in-
  process determinism; cross-interpreter determinism via a
  subprocess with `PYTHONHASHSEED=random`; platform-determinism
  self-check; the two invariance properties from plan §M7 tests
  (changing a referenced component intent changes the hash; adding
  an unreferenced component does not); referenced-example-body
  invalidation; `transpiler_version` sensitivity; and the
  `stored-content_hash-on-input is ignored` fixed-point guarantee.
- Full test suite: 1406 passed, 18 skipped (baseline 1384 → +22 new
  tests). `mypy --strict src/s0ma/` clean across 40 source files.
  `ruff check src/ tests/` clean.

### Design decisions recorded during M7 (2026-04-24)
- **Bootstrap registration skipped for the M7 public functions.**
  `canonicalize` and `content_hash` are module-level pure functions
  over immutable inputs — the same category as the
  `self_model.formatters.*` family and `examples.runner`'s
  module-level convenience wrappers. The existing pattern for
  that category is allowlist entries in
  `_KNOWN_UNREGISTERED_UTILITIES`, not bootstrap `ComponentSpec`
  entries. Adding components would introduce a bootstrap cycle
  (`hashing` imports `models`, and bootstrap specs for `hashing`
  would live in `_bootstrap.py` which imports `models`); the
  allowlist path is the settled carve-out for this case.
  Framework count stays at 59.
- **`ComponentSpec.registered_at` and `source_file` are excluded
  from the transitive hash.** Both are operational metadata:
  `registered_at` is a wall-clock timestamp captured at
  registration time (would make two runs of the same code produce
  different hashes), and `source_file` is an absolute filesystem
  path (would make two developers' checkouts disagree). The
  transitive walk projects each `ComponentSpec` through
  `_canon_component_spec`, which includes only the semantic fields
  (`name`, `kind`, `layer`, `intent`, `contracts`, `dependencies`,
  `resource_profile`, `version`, `metadata`, `module_path`,
  `qualified_name`, `is_framework`). Other dataclasses
  (`DocRefRegistration`, `DocGuideRegistration`,
  `ExampleRegistration`, `FilterExpr`, `EntityRef`, `Section`,
  `AssertExpr`, `SourceSpan`) have no timestamp fields, so the
  generic dataclass canonicalization handles them directly.
- **FilterExpr resolution is kind-only in v1.** A doc-ref's
  `covers` list contains `FilterExpr(target_kind, predicate,
  raw)`. The v1 resolver matches by `target_kind` only — the
  predicate is already in the doc's own canonicalization (step
  2), but is not interpreted by `_resolve_filter`. An s0ma-dsl
  upgrade can replace this helper with a real predicate
  interpreter without touching the rest of the algorithm.
- **The `content_hash` field on the input is zeroed before
  hashing.** Otherwise the hash would be a fixed point of its own
  input — feeding the stored hash back in would change the output,
  making "recompute and compare" impossible.
- **Dataclass field order is declaration order, not sorted.** Two
  dataclasses with the same field names in different order are
  semantically distinct and must hash differently. Sorting would
  mask field-reordering regressions.
- **Sets sort by element's canonical form, not by the element
  itself.** `sorted({1, "a"})` raises `TypeError`; sorting by
  canonical bytes is always defined, so mixed-type sets hash
  reliably.

## [0.2.0-alpha.9] — 2026-04-24

Documentation subsystem Milestone 6 — example execution subsystem.

### Added
- `s0ma.examples` subpackage implementing plan M6. Discovers registered
  `ExampleRegistration` entries from the current registry snapshot and
  executes each body in an isolated subprocess with per-example timeout
  enforcement and structured result reporting.
- `ExampleRunner(registry, *, timeout_seconds, dispatcher)` — reads
  examples from `RegistrySnapshot.examples` at call time, returns
  `ExampleResult` objects, and never raises on per-example failure or
  timeout. `run_all()` aggregates results; `run()` executes a single
  example; `discover()` returns the current list.
- `ExampleResult(frozen)` — `example_name`, `runs_in`, `passed`,
  `duration_ms`, captured `stdout` / `stderr`, `returncode`, `timed_out`,
  optional `error` summary, and a `summary()` one-liner.
- `ExampleDispatcher(*, timeout_seconds, python_executable,
  integration_cmd)` — routes by `runs_in` to three subprocess handlers:
  `standalone` (runs the body as a script), `pytest` (writes the body
  to a `test_<name>.py` and invokes `python -m pytest`), and
  `integration` (honors `SOMA_INTEGRATION_CMD` env var with `{body}`
  substitution; falls back to `standalone` when unset).
- `DispatchOutcome` — thin value object pairing a `TimeoutResult` with
  the effective `runs_in` mode.
- `TimeoutResult(frozen)` + `run_subprocess_with_timeout(...)` —
  cross-platform subprocess runner that represents a timeout as a
  first-class result field (`timed_out=True`, `returncode=-1`) rather
  than propagating `subprocess.TimeoutExpired`.
- `DEFAULT_TIMEOUT_SECONDS = 30` and `INTEGRATION_CMD_ENV_VAR =
  "SOMA_INTEGRATION_CMD"` constants.
- `run_all_examples(registry, *, timeout_seconds)` — module-level
  convenience wrapper over `ExampleRunner.run_all()`.
- `ExampleTimeoutError(S0maError)` — structured marker exposed on
  `s0ma.exceptions` with `example_name` / `timeout_seconds` attributes.
  Carried on the `ExampleResult.error` string; not propagated to
  callers, by design.
- Opt-in pytest plugin `s0ma.examples.plugin` wired to the
  `pytest11` entry-point group in `pyproject.toml`. Adds
  `--s0ma-examples` (default off) plus `s0ma_example_timeout` ini key.
  When enabled, registered examples surface as `pytest` items named
  `s0ma-example::<example-name>` and fail via `pytest.fail` with
  stdout / stderr / error captured.

### Changed
- Bootstrap component count raised from 54 → 59. The five new
  `FRAMEWORK` registrations are `ExampleRunner`, `ExampleResult`,
  `ExampleDispatcher`, `DispatchOutcome`, and `TimeoutResult`. Registered
  in dependency-safe order (`TimeoutResult` → `DispatchOutcome` /
  `ExampleDispatcher` → `ExampleResult` / `ExampleRunner`) to keep the
  registry's strict-dependency warnings quiet.
- `tests/test_phase3_capstone.py::test_bootstrap_component_count_is_final`
  expectation updated from 54 → 59 and docstring extended with the M6
  rationale. This is the only existing test modified in this milestone,
  per the plan's non-negotiable invariants.
- `_S0MA_PUBLIC_MODULES` extended with the four new
  `s0ma.examples.*` modules so the bootstrap-verifier blind-spot scan
  covers them.
- `_KNOWN_UNREGISTERED_UTILITIES` extended with
  `run_all_examples`, `run_subprocess_with_timeout`, and the two
  pytest hook-protocol functions (`pytest_addoption`,
  `pytest_collection_modifyitems`). Hook names are mandated by pytest
  and cannot be registered as components.
- `pyproject.toml` gains a `[project.entry-points."pytest11"]` block
  registering `s0ma_examples = "s0ma.examples.plugin"`.

### Tests
- New file `tests/test_example_runner.py` with 20 cases spanning:
  the `run_subprocess_with_timeout` primitive (success, non-zero exit,
  timeout, stderr capture), `ExampleTimeoutError` structure, the three
  dispatcher modes (standalone pass/fail, pytest pass/fail,
  integration fallback + `SOMA_INTEGRATION_CMD` honor), an invalid
  `runs_in` rejection, the runner's default timeout / empty-registry /
  run / run_all behaviors including mixed-outcome aggregation, the
  timeout pathway (`timed_out=True`, `[TIMEOUT]` summary), and a
  public-API-surface assertion for every re-exported symbol.
- Full test suite: 1384 passed, 18 skipped. `mypy --strict src/s0ma/`
  clean across 37 source files. `ruff check src/ tests/` clean.

### Design decisions recorded during M6 (2026-04-24)
- **Subprocess-level isolation is non-negotiable.** Every example runs
  in a child process even when the dispatch mode could in principle
  execute in-process. Reasons: (a) timeout enforcement via
  `subprocess.run(..., timeout=...)` is the only reliable
  cross-platform mechanism; (b) example bodies frequently perform
  `@component` registrations of their own, which would corrupt the
  parent registry; (c) the plan's subtask 4 explicitly mandates
  `subprocess.run` wrapping.
- **Timeout as a result field, not an exception.** `run_subprocess_with_timeout`
  never raises `subprocess.TimeoutExpired` to its caller. The design
  preference is that bulk runs must surface all failures — a raised
  exception would short-circuit `run_all`. `ExampleTimeoutError` is
  still defined for consumers that want to introspect results by
  exception type; it is stringified onto `ExampleResult.error`.
- **Pytest plugin is opt-in, resolving §11 open question.** The plan
  flagged the opt-in vs. opt-out choice as deferrable to M6. Chose
  opt-in (`--s0ma-examples`) matching the plan's stated lean. Entry
  point is registered unconditionally so `pytest --help` documents the
  flag; the plugin is a no-op when the flag is unset.
- **Plugin item class is underscore-prefixed.** `_S0maExampleItem`
  lives inside `s0ma.examples.plugin` as an internal helper.
  Registering it as a `FRAMEWORK` component would couple the bootstrap
  to pytest as a runtime dependency, which it isn't. The underscore
  prefix is the existing mechanism for "private class in a public
  module"; the bootstrap verifier's AST scanner skips it.
- **Integration dispatcher fallback.** When `SOMA_INTEGRATION_CMD` is
  unset, the integration mode falls through to the standalone
  dispatcher with `mode="integration"` preserved on the outcome. The
  plan's subtask 3 explicitly allows this: "honors `SOMA_INTEGRATION_CMD`
  env var; default: same as standalone."

## [0.2.0-alpha.8] — 2026-04-23

Documentation subsystem Milestone 5 — SelfModelInterface extensions
and impact-analysis doc/example surfacing.

### Added
- `SelfModelInterface.describe_docs()` — registry-wide natural-language
  overview of all registered doc-refs, doc-guides, and examples
  (design §10.5). Returns an informative message when nothing is
  registered.
- `SelfModelInterface.describe_doc(name)` — doc-ref / doc-guide detail
  lookup. Dispatches on registry key (bare name, matching the M2 key
  convention). Returns a helpful not-found string listing known docs
  — does not raise.
- `SelfModelInterface.get_docs_for_component(name)` — reverse-index
  surface over M4's `RegistrySnapshot.docs_for(...)`, rendering the
  matched doc-refs and doc-guides as natural-language text. Accepts
  the same bare-name / `"module::name"` shortcut inputs as the M4
  reverse index.
- `SelfModelInterface.get_examples_for_component(name)` — reverse-index
  surface over M4's `RegistrySnapshot.examples_for(...)`.
- `SelfModelInterface.get_drift_status()` — v1 per-doc content-hash
  presence report. Signature is stable; full transitive drift
  computation lands with M7's content-hash subsystem and will replace
  this method's body without breaking callers.
- `ImpactReport.affected_docs` / `affected_examples` fields —
  populated by `compute_impact_analysis(...)` from M4's reverse
  indices.
- `format_doc_refs_overview`, `format_doc_ref_detail`,
  `format_doc_guide_detail`, `format_example_detail`,
  `format_docs_for_component`, `format_examples_for_component`,
  `format_drift_status` — seven new text formatters in
  `s0ma.self_model.formatters`. Added to
  `_KNOWN_UNREGISTERED_UTILITIES` to preserve the existing pattern
  used for the rest of that module.

### Changed
- `format_impact_report` now renders "Affected documentation" and
  "Affected examples" sections when the impact analysis surfaces
  matching M4 reverse-index entries. Sections are omitted when empty.
- `SelfModelInterface` bootstrap postconditions extended to describe
  the five new methods and the informational not-found contract on
  `describe_doc`.
- `ImpactReport` bootstrap intent expanded to mention the new
  affected-docs / affected-examples fields.

### Tests
- New file `tests/test_self_model_docs.py` with 17 cases covering
  every new method, the empty-registry path on each, the no-match
  path on both reverse-index surfaces, string-shortcut input, the
  "missing content hash" branch of drift status, and the two new
  sections in `format_impact_report` (present vs. omitted).
- Suite size: 1347 → 1364 passing, 18 skipped. mypy/ruff clean
  across `src/s0ma` and `tests/test_self_model_docs.py`.

### Design decisions recorded during M5 (2026-04-23)
- **Informational "not found" on new M5 surface**: the plan's test
  guidance ("Missing-name case returns informative 'not found'
  message (no exception)") is followed for every new M5 method.
  `describe_component` still raises `RegistryIntegrityError` on
  unknown names because its public contract has been stable since
  Phase 3A — changing it would be a regression for existing callers.
  The new M5 surface is informational by construction.
- **`get_drift_status()` is v1-only**: M5 delivers the method's shape
  and a useful hash-presence report, but the transitive-hash
  comparison lives in M7. The formatter text explicitly names M7 so
  readers know the bound. This matches M7 subtask 4 ("Wire
  `get_drift_status` (from M5) to use this utility").
- **Formatters join the utilities allowlist, not the component
  registry**: every existing formatter in
  `s0ma.self_model.formatters` is listed in
  `_KNOWN_UNREGISTERED_UTILITIES`. The new M5 formatters follow the
  same rule — they are pure text-producing helpers, not load-bearing
  components, and registering ~20 trivial utility functions as
  components would dilute the registry. Class-level
  `SelfModelInterface` remains the registered surface; its
  postconditions describe the M5 methods.
- **Key lookup in `describe_doc`**: bare name (matches the M2
  registry key), not `<module>::<name>`. Module disambiguation can
  layer in later if real collisions emerge.

## [0.2.0-alpha.7] — 2026-04-23

Documentation subsystem Milestone 4 — RegistrySnapshot extensions
and reverse indices.

### Added
- `RegistrySnapshot.doc_refs`, `.doc_guides`, `.examples` fields,
  populated by `ComponentRegistry.snapshot()` from the M1 stores
  (design §10.4).
- `RegistrySnapshot.examples_for(entity_ref)` — coarse-match reverse
  index returning `ExampleRegistration`s whose `demonstrates` includes
  the given target.
- `RegistrySnapshot.docs_for(entity_ref)` returning the new
  `DocsForResult` wrapper with separate `refs` and `guides` lists.
  Doc-guide matches use the same name+module rule as `examples_for`;
  doc-ref matches fall back to coarse textual containment on each
  filter's `raw` source — full filter-expression evaluation lands in
  s0ma-dsl (plan §11 open question resolved in favor of textual v1).
- Both reverse-index methods accept either an `EntityRef` or a string
  shortcut (`"module::name"` or bare `"name"`). The string form
  ignores `kind` and treats `module` as optional.
- `DocsForResult` dataclass exported from `s0ma`. Bootstrap-registered
  as a framework component, bringing the framework count from 53 → 54.

### Changed
- `RegistrySnapshot.to_dict()` / `.to_json()` emit the new `doc_refs`,
  `doc_guides`, `examples` keys only when the corresponding stores
  are non-empty, preserving the existing key order so legacy snapshot
  consumers see no schema churn until the documentation subsystem is
  in use. `snapshot_at` remains the trailing key.
- `RegistrySnapshot.describe()` renders new `DOCUMENTATION` and
  `EXAMPLES` sections when doc registrations are present and omits
  them otherwise.
- `RegistrySnapshot` bootstrap registration's postconditions extended
  to mention `doc_refs`/`doc_guides`/`examples` emission and the two
  reverse-index methods.

### Tests
- New file `tests/test_registry_snapshot_docs.py` with 18 cases
  covering snapshot population, conditional serialization,
  describe-section emission, EntityRef and string-shortcut reverse
  lookups, module disambiguation, `DocsForResult.is_empty()` /
  `.to_dict()`, and direct `RegistrySnapshot(...)` construction.
- Suite size: 1329 → 1347 passing, 18 skipped.

### Design decisions recorded during M4 (2026-04-23)
- **`docs_for` return type** (plan §11 open question): structured
  `DocsForResult` wrapper, not a `list[DocRef | DocGuide]` union.
  Callers iterate `.refs` and `.guides` independently and never need
  runtime `isinstance` dispatch; the wrapper carries `to_dict()` and
  `is_empty()` for serialization and quick checks.
- **Empty-vs-omit serialization**: M4 follows the plan's explicit
  wording — emit doc-subsystem keys only when non-empty — diverging
  from the existing convention of always-include for legacy fields.
  Rationale: existing JSON consumers and the OpenAPI/MCP schema layer
  remain stable until they opt in to the new keys. Adding a new key
  is far less disruptive than changing the meaning of an existing
  empty-dict value.
- **Coarse v1 matching**: `_entity_refs_match` requires `name`
  equality and module agreement-when-both-supply-one; `kind` is
  ignored because callers using string shortcuts never know it.
  Doc-ref filter matches use raw-text containment for the same
  reason — full predicate evaluation belongs to s0ma-dsl, not the
  runtime snapshot.

## [0.2.0-alpha.6] — 2026-04-23

### Fixed
- Cleared the 99 remaining ruff errors across `tests/` (plan M3D).
  65 auto-fixed by `ruff check --fix` (unused imports, empty
  f-strings, import-sort, `TC005` empty type-checking blocks,
  `B010` setattr-constant, `SIM300` yoda), 34 manually resolved:
  - **9× SIM117** in `test_lifecycle_transaction.py`: nested
    `with pytest.raises(...)` / `with lifecycle_manager.transaction()`
    pairs collapsed into parenthesised multi-context `with` blocks.
  - **8× F401 false-positive** restored in `test_integration.py`:
    side-effect imports of `tests.sample_project.mini_app.*`
    (required to trigger `@component` on re-import after
    `_clear_mini_app_modules`) converted to
    `importlib.import_module(...)` calls — preserves semantics
    without tripping F401.
  - **7× F841** unused locals removed (`original_id`, `t2`, 4×
    `props = {…}` inside `pytest.raises` blocks in
    `test_models.py`, `desc_before` in
    `test_phase3_capstone.py`).
  - **3× TC003** (`pathlib.Path`) moved into `TYPE_CHECKING`
    blocks in `test_phase3_capstone.py`, `test_self_model.py`,
    `test_self_model_integration.py`.
  - **1× TC001** (`ComponentRegistry`) moved into
    `TYPE_CHECKING` in `test_lifecycle_create.py`.
  - **2× E741** `l`-named comprehension variables renamed to
    `layer` in `test_phase3_capstone.py`.
  - **1× B024** `ParentComponent(abc.ABC)` in
    `test_decorators.py` given a real `@abstractmethod` and a
    `ChildComponent` implementation so the ABC declaration is
    semantically meaningful.
  - **1× F811** `TestRegistration` import from `s0ma.models`
    deleted from `test_registry.py` — it was dead and collided
    with a local test class.
  - **1× N807** `__special__` dunder-named helper in
    `test_import_hook.py:108` renamed to `_dunder_stub`. The
    test's assertion passes the dunder name as a *string*, which
    is what `_is_public_entity` actually inspects — the helper's
    `__name__` was never load-bearing.
  - **13× E501** long lines wrapped via paren-continuation or
    split across multiple arguments.

### Changed
- `TestABCInheritanceHandling.test_component_on_subclass_has_own_spec`
  in `tests/test_decorators.py` now exercises an ABC with an actual
  abstract method (rather than a bare `abc.ABC` subclass with no
  abstract content). Same semantic coverage, cleaner lint.

### Design decisions

- **No `# noqa` anywhere.** Every lint violation was resolved by
  semantic fix or refactor. The N807 judgment call contemplated in
  the M3D plan text went to "rename" because the dunder string is
  what the test actually cares about; the helper's own `__name__`
  carried no meaning.
- **Side-effect imports via `importlib.import_module`.** Ruff's F401
  cannot distinguish intentional side-effect imports from dead code
  at function scope. Using the function-call form both documents the
  intent (there's a comment on every site) and is invisible to F401.
- **SIM117 collapsed with paren-continuation, not `contextlib.ExitStack`.**
  The nested-with pattern paired exactly two contexts per site; the
  Python 3.10+ parenthesised form reads cleaner than `ExitStack` and
  doesn't require an import.
- **`props = {…}` dict assignments inside `pytest.raises` blocks
  deleted, not renamed to `_`.** The dict construction existed only
  to wrap a single `ConfigurableProperty(...)` whose construction is
  what actually raises. Inlining the construct removes the F841 and
  makes the test's intent obvious.

## [0.2.0-alpha.5] — 2026-04-23

### Fixed
- Resolved the 13 remaining `mypy --strict` errors in `src/s0ma/api/`:
  - Declared `fastapi.*`, `pydantic.*`, `mcp.*` as optional-import
    overrides in `pyproject.toml` (matching the `soma_dsl.*` pattern
    from M3B — these are all declared `[project.optional-dependencies]`
    extras, so their stubs are not guaranteed to be present in the
    type-check environment).
  - Added `disallow_subclassing_any = false` to the existing
    `s0ma.api.rest` and `s0ma.api.mcp_server` override blocks. When
    pydantic is absent, `BaseModel` resolves to `Any`; our REST
    response models intentionally subclass it, so the strict-mode
    diagnostic was noise.
- Cleaned the 5 ruff errors in `src/s0ma/registry.py`:
  - Two `I001` import-sort violations auto-fixed.
  - `SIM102` nested `if` at `get_by_canonical_id` collapsed into a
    single `and`-chained conditional (no `# noqa`).
  - Two `E501` long lines (SQLite row-load dict comprehensions) wrapped
    via paren-continuation.

### Design decisions

- **`disallow_subclassing_any = false` scoped to the two API modules,
  not globally.** Keeps the strict-mode discipline everywhere else.
  When the `api` extras are installed locally, those modules type-check
  against real pydantic stubs; the override only relaxes the rule when
  stubs are missing.
- **`SIM102` fixed by restructure, not suppression.** The nested `if`
  carried no independent semantics beyond its outer — folding the
  conditions is a strict improvement in readability.

## [0.2.0-alpha.4] — 2026-04-23

### Fixed
- Registered `S0maDSLLoader` in `_bootstrap.py` alongside `S0maFinder`
  / `S0maLoader`, resolving the 5 pre-existing bootstrap-verifier
  blind-spot failures in `tests/test_bootstrap.py`,
  `tests/test_integration.py`, and `tests/test_self_model.py` that had
  been deferred through M1–M3 (plan M3B).
- Resolved `mypy --strict` `import-not-found` errors on the lazy
  `soma_dsl.*` imports inside `S0maDSLLoader._transpile` and
  `_write_ir_and_map` via a scoped `[[tool.mypy.overrides]]` block in
  `pyproject.toml`. `soma_dsl` is a sibling package, not a declared
  runtime dependency — the override tells mypy the optional import is
  intentional.
- Resolved the `no-any-return` on `emit_python(ast_module)` by
  annotating the local `python_source: str` rather than suppressing.
- Fixed the two ruff import-sort violations inside
  `S0maDSLLoader._transpile` / `_write_ir_and_map` (auto-sorted by
  `ruff check --fix`).

### Changed
- `EXPECTED_FRAMEWORK_COMPONENT_COUNT` bumped 52 → 53 to reflect the
  new `S0maDSLLoader` registration. Updated pinned-count tests in
  `tests/test_phase3_capstone.py` and the docstring noting the jump.
  This is the sole test-change category permitted by the plan's
  non-negotiable invariants: pinned counts that tracked the prior
  under-registered baseline.

### Design decisions

- **No `@internal` band-aid.** `S0maDSLLoader` is a load-bearing public
  loader class (parallel to `S0maFinder` / `S0maLoader`), so it gets a
  full `@component`-equivalent bootstrap registration. Marking it
  `@internal` would misrepresent its role and re-open the P1
  registration-as-creation invariant.
- **Mypy override, not inline `# type: ignore`.** The plan's
  non-negotiables forbid `# type: ignore` in new code; the correct
  tool for an optional sibling-package import is the module-scoped
  override block.
- **Out-of-scope debt left in place.** 13 other mypy errors and 104
  other ruff errors exist across `src/s0ma/api/*` and elsewhere.
  M3B narrowly targets the debt on the import-hook / bootstrap path
  that M1–M3 inherited. The remainder is not on the doc-subsystem
  critical path and will be addressed separately.

## [0.2.0-alpha.3] — 2026-04-23

### Added
- Import-hook recognition of the three documentation-subsystem marker
  attributes: `__soma_doc_ref__`, `__soma_doc_guide__`, `__soma_example__`
  (plan M3 / design §10.3). Modules that advertise a marker whose
  declaration is not registered in the global registry by the time the
  module body finishes executing raise `UnregisteredComponentError` in
  strict mode (warn in lenient mode).
- Public constants `DOC_REF_MARKER_ATTR`, `DOC_GUIDE_MARKER_ATTR`,
  `EXAMPLE_MARKER_ATTR` on `s0ma.import_hook` so the s0ma-dsl emitter
  can reference the attribute names without hard-coding strings.
- `docs/references/documentation_subsystem.md` — transitional reference
  anchor documenting the new runtime surface and the marker-attribute
  contract with s0ma-dsl. Marked for regeneration from a `doc-ref`
  once the DSL emitter lands.
- `tests/test_fixtures/docs/` — fixture package with registered and
  intentionally-dangling doc/example modules used by import-hook tests.

### Changed
- `S0maLoader.exec_module` and `S0maDSLLoader.exec_module` now run a
  second post-import scan for missing documentation registrations on
  top of the existing unregistered-entity scan.

### Design decisions

- **Marker names are singular** (`__soma_doc_ref__`, not
  `__soma_doc_refs__`), matching the wording in the M3 plan. The
  attribute value is an iterable of names; a bare `str` is accepted as
  a one-name shorthand.
- **Verification runs against the global registry singleton**, not a
  locally scoped one. Consistent with how `@component` registrations are
  verified and keeps the check side-effect-free relative to the import
  system itself.
- **Separate error path from component enforcement.** Missing doc
  declarations produce their own diagnostic message (`_format_doc_\
violation_message`) rather than piggy-backing on the
  unregistered-public-entity message — the remediation differs
  (regenerate the `.soma` source) and the two scans are logically
  independent.

## [0.2.0-alpha.2] — 2026-04-23

### Added
- Public registration functions `register_doc_ref`, `register_doc_guide`,
  `register_example` — both as methods on `ComponentRegistry` and as
  module-level wrappers exported from `s0ma` (design §10.2 / plan M2).
- Persistence of doc-ref, doc-guide, and example registrations to the
  SQLite store introduced in M1 (payload-as-JSON), with round-trip
  loading on registry reopen.
- `ComponentRegistry.get_doc_ref`, `.get_doc_guide`, `.get_example`
  accessors to mirror existing `get_*` patterns.
- Validation at the registration boundary: `format` restricted to
  `{markdown, html, json}`, `output` must be a non-empty relative path
  (no leading `/`, no `..`), `demonstrates` required and non-empty for
  examples, `runs_in` restricted to `{standalone, pytest, integration}`.
- Allowlist entries in `_verifier._KNOWN_UNREGISTERED_UTILITIES` for
  the three new top-level wrappers, matching the pattern already used
  by `s0ma.initialize` / `s0ma.verify`.

### Design decisions

- Registry key is the bare `name` (matching `register_test`), not
  `<module>::<name>`. Module is stored on the registration but is not
  part of the key. Can evolve to canonical keying later if real
  collisions emerge.
- `idempotent=True` silently replaces (upsert); default raises
  `RegistrationError` on duplicate. Satisfies the plan's "mirrors
  `register_test`" hint.
- Duplicate collisions raise the existing `RegistrationError` rather
  than a new `DuplicateRegistrationError` subclass. The plan's
  parenthetical class name was read as illustrative.
- The three `s0ma.*` module-level wrappers are registered in
  `_verifier._KNOWN_UNREGISTERED_UTILITIES`, matching `s0ma.initialize`
  / `s0ma.verify`. The registration-as-creation invariant (P1) is
  upheld by the underlying `ComponentRegistry` methods themselves.

### Known pre-existing issues (not introduced by this milestone)

- 5 bootstrap tests in `tests/test_bootstrap.py`,
  `tests/test_integration.py`, and `tests/test_self_model.py` fail with
  a blind-spot anomaly for `S0maDSLLoader`. This predates M2 (confirmed
  on commit `3aa64af`). To be resolved in a separate cleanup pass.

## [0.2.0-alpha.1] — 2026-04-22

_Backfilled entry for M1, which landed on commit 3aa64af without a
changelog update._

### Added
- Documentation registration dataclasses (`SourceSpan`, `EntityRef`,
  `FilterExpr`, `Section`, `AssertExpr`, `DocRefRegistration`,
  `DocGuideRegistration`, `ExampleRegistration`) — design §§6, 10.1.
- `ComponentRegistry._doc_refs`, `._doc_guides`, `._examples` stores
  with SQLite schema tables `doc_refs`, `doc_guides`, `examples`
  (payload-JSON layout).
- Re-exports of the new dataclasses from `s0ma`.
