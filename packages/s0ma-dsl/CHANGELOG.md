# Changelog

All notable changes to `s0ma-dsl` (formerly `soma-dsl`) are documented in this file. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> From 0.5.0 the canonical changelog is the repo root `CHANGELOG.md`; this file is preserved for ≤ pre-monorepo history.

## [0.16.0] — 2026-05-11

The 0.16.0 release lands the post-Phase-2 second release boundary (M-8 through M-19 of the post-Phase-2 plan) and pairs with `s0ma-core 0.4.0` (which lands POST-1 / M-1 on the core side). Twelve milestones land together: M-8 (POST-14 manifest stubs), M-9 (POST-5 `integration` declaration kind), M-10 (POST-6 test-layer permissive opt-in), M-11 (POST-7 `soma check` multi-path + subdir), M-12 (POST-8 `requires-python` forward-compat check), M-13 (POST-10a/b/c validator round 1), M-14 (POST-10d/e/f/g validator round 2), M-15 (POST-10h/i/j/k strict-mode lints + `soft_requires:` fix), M-16 (POST-11a/b/c CLI minor improvements), M-17 (POST-12a/f `expected_exceptions:` + `deferred:`), M-18 (POST-12b/g `placeholders:` + `fixtures_format`), M-19 (POST-12c/d `dataclass_invariants:` + `consumes_via_dict:`). Every change is additive and backward-compatible — pre-0.16.0 modules parse unchanged, no consumer call site is mandated to change, and the only mandatory rotation is the spec-pointer (the v0.11.0 pointer retires per the deletion-after-0.15.0 policy; the live single pointer is now v0.15.0 → v0.16.0). See `post-phase2_release_0.16.0_summary.md` for the agent-facing surface tour and the per-milestone migration notes in `docs/migration_guide.md` (`# 0.15.0 → 0.16.0`).

### Fixed

- **POST-10j — `soft_requires:` dotted-name codegen.** Pre-0.16.0,
  `soft_requires: [importlib.metadata]` produced the unusable
  `try: import importlib.metadata; except ImportError: importlib =
  None` shape — the except branch silently overwrote the top-level
  `importlib` binding, and the success branch left the `metadata`
  name unbound, so any body using the imported submodule still hit
  `NameError`. The codegen now auto-promotes every dotted-form
  `soft_requires:` entry to the from-import shape that matches the
  canonical author intent: `try: from importlib import metadata;
  except ImportError: metadata = None`. The local-binding name is
  the last dotted segment (or the explicit `alias` if one was
  supplied) so consumers can reference the submodule directly. The
  colon-override form (`soft_requires: [requests:Session]`) was
  already correct pre-POST-10j; POST-10j makes the two forms
  equivalent for dotted names. Single-segment soft_requires entries
  (`soft_requires: [anthropic]`) are unchanged — they emit a plain
  `try: import anthropic` line. See spec §4.5 "`soft_requires`"
  → "Dotted-name codegen" and plan post-Phase-2 M-15 / POST-10j.

- **POST-10a — Vestigial-import detector closure.** The Phase 4
  vestigial check on `uses:` entries now consults a single
  closure that unifies (a) every body identifier found in any
  authored body, (b) every `depends_on:` / `raises:` / `tests:` /
  `mocks:` metadata target, and (c) every standalone axon target.
  A `uses:` entry is vestigial iff its local name is absent from
  every member of that union. The pre-POST-10a behaviour was the
  same union in shape but split across two passes (body
  identifiers vs metadata names) and could drift if a later
  refactor touched one side but not the other; folding both into
  one named `usage_closure` set makes the invariant explicit. The
  closure now also picks up `mocks:` targets from `test`
  declarations (the field shipped in POST-3b but its targets had
  not been threaded into the metadata-name set). No diagnostic
  semantics change for projects that already validated clean —
  this is a hardening pass with regression pins in
  `tests/test_validator_round_1_fixes.py`. See spec §4.5.1
  "Body-evidence scope" + `resolver/dependency.py` docstring on
  `_phase4_usage_verification`, and plan post-Phase-2 M-13 /
  POST-10a.

- **POST-10b — `pytest` in `requires:` false positive on
  fixture-only test bodies.** Test bodies that pull pytest
  fixtures purely through the runner's dependency injection
  (`def test_x(monkeypatch, capsys): ...`) never write
  `pytest.<symbol>` directly, so the Phase 4 vestigial-import
  scan saw no body-side reference and fired
  `VESTIGIAL_IMPORT` against `requires: [pytest]`. The new
  `runtime_only_requires:` module-header field is the explicit
  carve-out: same grammar as `requires:` / `soft_requires:`, same
  emitted import line, but the Phase 4 scan skips it. Project
  authors who hit the false positive on `pytest` (the canonical
  case) — or on any package whose body-level use is via a
  runtime mechanism the static checker cannot see — list the
  entry under `runtime_only_requires:` instead of `requires:` and
  the warning disappears. The legacy `requires: [pytest]`
  semantics are unchanged: a body that references
  `pytest.<symbol>` directly stays in `requires:` and still
  satisfies the existing rule. See spec §4.5.1
  "`runtime_only_requires`", quick reference's Module Header
  Fields, and plan post-Phase-2 M-13 / POST-10b.

- **POST-10c — `HELPER_NAME_COLLISION` D-27 inner-class
  regression pin.** Class methods and inner-function closures in
  test bodies never participated in the collision detector by
  design — the detector restricts itself to module-root `def`
  nodes via the `_extract_top_level_def_names` AST walk over
  `tree.body`. The 0.16.0 pass adds explicit regression pins in
  `tests/test_validator_round_1_fixes.py` covering the three
  scoping shapes that previously slipped through the regex-based
  detector before its M3 rewrite: (i) two test bodies that each
  define `class _Recorder: def _setup(self): ...` no longer fire;
  (ii) a body that mixes a class method `_setup` and a top-level
  `def _setup()` *with* another body's top-level `def _setup()`
  still fires (top-level wins, the class method is invisible);
  (iii) inner-function closure `_setup` defs scoped to their
  parent `def` never collide. The fix itself was the M3
  rewrite; this milestone closes the long-running D-27 ticket
  by pinning the contract so future detector refactors cannot
  regress it. See `_extract_top_level_def_names` docstring
  (POST-10c block) and plan post-Phase-2 M-13 / POST-10c.

- **POST-10f — `BARE_IMPORT` remediation text is context-aware.**
  The pre-0.16.0 remediation said "remove the import; declare in
  `requires:` or `uses:`" — but when the imported name was
  already in `uses:` (the canonical case: a test body that
  bare-imports a nerve already declared on the module header),
  the correct fix is just "remove the bare import; the name is
  already imported automatically." The refinement now consults
  the module-header `uses:` / `requires:` / `soft_requires:` /
  `runtime_only_requires:` sets after the parser builds the
  module and rewrites the diagnostic's remediation per case: (a)
  name already in `uses:` → "This name is already declared in
  `uses: [<qualified>]` and is imported automatically; remove
  the bare ``<stmt>`` from the body."; (b) name already in any
  `requires:` family → analogous "already declared" message; (c)
  name not in any of those → "Did you mean to add `<name>` to
  the module's `requires:` field?" so the next action is
  unambiguous. The runtime contract for `BARE_IMPORT` (warning
  in migration/dev, error in strict/release) is unchanged; only
  the remediation prose is. The post-parse refinement helper
  lives at `parser/soma_parser.py::_refine_bare_imports` and
  runs in both `parse_soma` and `parse_soma_with_warnings`. See
  plan post-Phase-2 M-14 / POST-10f and
  `tests/test_validator_round_2_fixes.py::TestPOST10fBareImportRemediationRefinement`.

### Added

- **POST-12c — `dataclass_invariants:` field on MODEL cells.** A
  MODEL cell may declare a list of machine-readable invariants —
  small Python boolean expressions authored against the dataclass's
  fields — that describe properties the model is expected to
  satisfy. Motivating shapes include bounded-collection contracts
  (`len(latency_samples) <= 100`), ratio / probability ranges
  (`0.0 <= ratio <= 1.0`), and structural invariants on enum-like
  state machines. Each entry is fed through
  `ast.parse(expr, mode="eval")` at `soma check` time; a
  syntactically invalid expression fires
  `INVALID_DATACLASS_INVARIANT` in every strictness mode. The
  invariants are *not* runtime-evaluated by s0ma — they are pure
  metadata for downstream introspection (a future linter, doc
  renderer, or contract-enforcing runtime might pick them up and
  `eval` them, but the 0.16.0 surface is declarative only).
  Declaring `dataclass_invariants:` on a non-MODEL cell is a
  `PARSE_ERROR`. Inline (`dataclass_invariants: ["x <= 10", ...]`)
  and block-list forms parse identically; entries can carry commas
  (the splitter is quote- and paren-aware). The list rides through
  the IR (`components[].fields.dataclass_invariants`) and into the
  emitted `metadata={...}` dict on the `@component` decorator;
  `soma inspect` renders a dedicated "Dataclass invariants" sub-
  section. Legacy MODEL cells without the field carry no new IR
  surface. See spec §4.2.7, quick reference's cell declaration
  block, spec_traceability row for `INVALID_DATACLASS_INVARIANT`,
  and plan post-Phase-2 M-19 / POST-12c.

- **POST-12d — `consumes_via_dict:` field on nerves.** Optional
  structured block-list declaring duck-typed couplings — contract
  relationships where the nerve body reads an injected dependency
  via dict-key access (`config["api_key"]`) rather than attribute
  access (`config.api_key`). Each entry is a structured map with
  two mandatory sub-fields: `contract:` (the named contract) and
  `param:` (the parameter name on the nerve body's outer function).
  `soma check` enforces that the contract resolves to a known cell
  or `uses:` target and the param is a real parameter on the outer
  function (positional / keyword-only / vararg / kwarg); mis-
  resolution fires `CONSUMES_VIA_DICT_INVALID` in every strictness
  mode. The motivating consumer is fr3d's settings / OAuth
  pipeline, where many SERVICEs accept the entire settings map and
  read keys directly to avoid threading a 30-attribute dataclass —
  the type-based coupling reading
  `Attribute(value=Name("config"), attr="api_key")` from the body
  AST collapses to an opaque `Subscript(value=Name("config"),
  slice=Constant("api_key"))` and the registry can no longer trace
  the dependency. `consumes_via_dict:` closes that introspection
  gap. The list rides through the IR
  (`components[].fields.consumes_via_dict`) as records of shape
  `{"contract": ..., "param": ...}` and the emitted `metadata={...}`
  dict carries the same shape; `soma inspect` renders a "Consumes
  via dict" sub-section under each affected nerve row. No codegen
  side effect — the body emits unchanged, no import for the
  contract is added. See spec §4.1.10, quick reference's nerve
  syntax block, spec_traceability row for
  `CONSUMES_VIA_DICT_INVALID`, and plan post-Phase-2 M-19 /
  POST-12d.

- **POST-12b — `placeholders:` field on CONSTANT cells with
  `content: @file("...")`.** A CONSTANT cell whose body comes from
  an embedded file may declare which magic-string markers the file
  is asserted to contain (`placeholders: [__SYSTEM_NAME__,
  __GRAPH_DATA_JSON__]`). The placeholder convention is the dunder-
  uppercase regex `__[A-Z][A-Z0-9_]*__` — Python's `__init__` /
  `__name__` shapes never match. `soma check` enforces a two-way
  contract: every declared placeholder must appear in the embedded
  file (`PLACEHOLDER_NOT_FOUND`, error in every mode), and every
  placeholder-shaped string in the file must be declared
  (`UNDECLARED_PLACEHOLDER`, warning in dev/migration, error in
  strict/release). Declaring `placeholders:` on a CONSTANT cell
  with an inline `---` body is a `PARSE_ERROR` — the field's
  contract is tied to the embed directive. The list rides through
  the IR under `components[].fields.placeholders` so downstream
  template renderers can read the declared marker set without
  re-parsing the source. Inline (`placeholders: [a, b]`) and
  block-list forms parse identically via the PRE-7 re-assembler.
  See spec §4.2.6, quick reference's cell declaration block,
  spec_traceability rows for both new codes, and plan post-Phase-2
  M-18 / POST-12b.

- **POST-12g — `[tool.soma].fixtures_format` for non-`.soma`
  fixture validation.** Projects can declare the expected format of
  non-`.soma` test fixtures under
  `[tool.soma.fixtures_format]` — a TOML sub-table mapping a
  filename glob (`"*.jsonl"`) to one of `"ndjson"` (one JSON
  document per line, blank lines tolerated), `"json"` (one whole-
  document JSON value), or `"yaml"` (one whole-document YAML value
  via `yaml.safe_load`; requires PyYAML at runtime). `soma check`
  walks every configured `test_roots` directory looking for files
  matching each glob and validates them via the format-specific
  parser. Failures fire `FIXTURE_FORMAT_INVALID` with the offending
  path, format, parser-thrown error, and offending line number;
  severity ladders with mode (warning in dev/migration, error in
  strict/release). Files outside every configured glob are ignored
  (fixtures stay opt-in). Unknown format values raise `ValueError`
  at project-discovery time naming the supported set. See spec
  §4.13 "Fixture-format validation", §4.16 "Validation Command",
  quick reference's Project Configuration table, spec_traceability
  row for `FIXTURE_FORMAT_INVALID`, and plan post-Phase-2 M-18 /
  POST-12g.

- **POST-12a — `expected_exceptions:` field on nerves.** Optional
  metadata declaring the Python-namespace exception types a nerve
  catches by design (typically inside `try / except` blocks).
  Distinct from `raises:` which is restricted to s0ma cells in the
  component-reference namespace — `expected_exceptions:` accepts
  dotted Python paths (`json.JSONDecodeError`,
  `urllib.error.HTTPError`) with no namespace check, so the
  canonical place to declare "this body deliberately handles
  `json.JSONDecodeError`" is no longer "nowhere structured." Inline
  (`expected_exceptions: [json.JSONDecodeError, urllib.error.HTTPError]`)
  and block-list forms parse identically. No validation side
  effect today — the field is pure metadata for downstream tooling
  (doc renderers, future linters, the `soma deferred-surface`
  reporter's exception-envelope view). The value rides through the
  IR (`components[].fields.expected_exceptions`) and surfaces in
  the emitted `metadata={"expected_exceptions": [...]}` dict on
  the `@component` decorator. `soma inspect` renders the list in a
  dedicated "Expected exceptions" sub-section. Legacy nerves
  without the field carry no new IR surface — the key is omitted
  entirely. See spec §4.1.8, quick reference's nerve syntax block,
  and plan post-Phase-2 M-17 / POST-12a.

- **POST-12f — `deferred:` annotation on nerves / cells /
  ganglia + `soma deferred-surface` reporter.** Optional
  string-valued annotation that marks a declaration's body as a
  stub awaiting fill. The value is a free-form reason — anything
  from a one-word "TODO" to a paragraph describing the unblocking
  signal — so the project's stub surface is discoverable from the
  registry rather than from inline `# TODO:` comments. Identical
  field on all three executable declaration types: a nerve whose
  body is a `raise NotImplementedError`, a MODEL cell whose body
  is a placeholder `class X: pass`, and a ganglion whose
  `on_anomaly` body is a `pass` can all carry the same
  `deferred: "<reason>"` line. The reason rides through the IR
  (`components[].fields.deferred`) and into the emitted
  `metadata={"deferred": "..."}` dict; `soma inspect` flags the
  declaration with a `deferred` tag in its bracket label and
  renders the reason on its own sub-line. The companion reporter
  ships in two forms: the new `soma deferred-surface` subcommand
  enumerates every deferred-marked declaration in the resolved
  project (with module-qualified name, declaration type, reason,
  and file:line), and `soma check --report-deferred` runs the same
  report after the standard diagnostic block. Both forms emit
  text or JSON via `--format` and **always exit 0** — deferred
  declarations are explicitly *not* a build blocker; the field
  exists to make the stub surface visible, not to gate releases.
  See spec §4.1.9 (the canonical contract; §4.2 and §4.3 cross-
  reference it for cells and ganglia), quick reference's
  Declaration Types block, and plan post-Phase-2 M-17 / POST-12f.

- **POST-11a — `soma build --force-output-dir` flag + `BUILD_DIR_OVERRIDE_CONFLICT`
  pre-flight refusal.** When `soma build --output-dir <path>` is invoked
  against a project with a `[tool.soma].build_dir` and the two paths
  resolve to different absolute paths, the CLI now refuses at pre-flight
  time with the new `BUILD_DIR_OVERRIDE_CONFLICT` code (exit
  `EXIT_USAGE_ERROR`, 2) and a remediation naming both paths plus the
  `--force-output-dir` escape hatch. Pre-0.16.0 the override was applied
  silently — the build landed at the supplied path while the project
  model's `build_dir` stayed unbuilt, scattering build artefacts across
  two locations and producing a subtle drift between
  `[tool.soma].build_dir`-based consumers (`bootstrap_imports`,
  `soma test`'s default path) and the actual build output. The new
  `--force-output-dir` flag is the escape hatch for the ad-hoc
  override case (e.g. a CI script that wants to inspect a build in a
  tmpdir without touching the steady-state path); when set, the
  override applies, the build lands at the supplied path, and a
  one-line stderr notice still announces the override so it stays
  visible in logs. Three pre-flight exemptions: (a) synthetic
  projects (no `[tool.soma]` table) — there is no canonical
  `build_dir` to disagree with; (b) the `_run_build_for_test`
  internal dispatch (`soma test`'s build helper, which always sets
  `output_dir == soma_project.build_dir` and carries the hidden
  `_role` namespace attribute) — exempt by structural identity; (c)
  `--output-dir` paths that resolve to the same absolute path as
  `soma_project.build_dir` (a redundant flag, harmless). The new
  code is registered in `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`
  (configuration-shaped: pre-flight surface; the strictness ladder
  never sees the check). See spec §4.17.1 "`soma build --output-dir`
  vs `[tool.soma].build_dir`", quick reference's CLI Commands row,
  and plan post-Phase-2 M-16 / POST-11a.

- **POST-10h — `MUTABLE_DEFAULT` lint on `dataclasses.field`.** A new
  validator pass flags `dataclasses.field(default=[...])` and
  `dataclasses.field(default={...})` calls in any authored body
  (test, nerve, helper, ganglion, or cell). Python evaluates
  `default` once at class-body time, so every dataclass instance
  ends up sharing the same mutable list/dict/set — the classic
  shared-mutable-default bug. The detector walks every body via
  `ast.parse`, looks for `ast.Call` nodes whose function is `field`
  or `dataclasses.field`, and inspects the `default=` keyword
  argument for `ast.List` / `ast.Dict` / `ast.Set` literals (and
  zero-argument `list()` / `dict()` / `set()` calls). Aliased
  imports (`from dataclasses import field as df; df(default=[])`)
  are intentionally not recognised — the lint is conservative
  there to avoid false positives on unrelated single-name
  `field(...)` calls in unrelated APIs. The diagnostic names the
  correct shape (`default_factory=list` / `=dict` / `=set`) in the
  remediation. Severity ladders with mode: warning in migration/dev
  so authors see the finding while iterating, error in strict and
  release where shipping a known-buggy default is unacceptable.
  See spec §4.7.6 "Body-Shape Lints" (POST-10h block) and plan
  post-Phase-2 M-15 / POST-10h.

- **POST-10i — `DUPLICATE_INNER_FUNCTION` lint.** A new validator
  pass flags two `def` (or `async def`) declarations with the same
  name inside one enclosing function scope. The canonical motivating
  case is a SERVICE nerve's factory body where the author meant the
  second `def` to be a sibling but accidentally re-typed the first
  inner function's name; Python silently shadows the first binding
  and the returned dict from the factory ends up keyed to a
  function the author did not intend. The detector walks every
  authored body and, for each `ast.FunctionDef` /
  `ast.AsyncFunctionDef` node, scans its direct
  `ast.FunctionDef` / `ast.AsyncFunctionDef` children for name
  collisions. Class bodies and methods inside classes are
  intentionally excluded — Python allows `def foo` once per
  method-name in a class body, and the parallel collision detector
  for nerves is `CLASS_BODY_IN_NERVE`. Two sibling outer scopes
  (e.g. `def helper(): def foo(): ...` and `def factory(): def
  foo(): ...`) do NOT collide — the collision is per outer scope,
  not per module. Always an error in every strictness mode: this
  is a structural authoring bug, not a strictness preference (same
  precedent as `DUPLICATE_DECLARATION` at module scope). See spec
  §4.7.6 "Body-Shape Lints" (POST-10i block) and plan post-Phase-2
  M-15 / POST-10i.

- **POST-10k — `CROSS_MODULE_USES_ASYMMETRY` lint.** A new
  validator pass fires when `uses:` imports two or more entries
  from the same parent module (e.g. `uses: [other.A, other.B]`)
  but the module's bodies only reference a subset of those names
  (e.g. only `A`). The asymmetry suggests the author over-imported
  — perhaps copy-pasted the symmetric pair from a sibling module
  that the body never quite caught up to — and that the
  unreferenced entry should be trimmed. The lint groups `uses:`
  entries by their parent-module path (`other.A` and `other.B`
  share parent `other`), collects every bare identifier reference
  across every authored body, and flags any group with both
  referenced and unreferenced siblings. Narrower than
  `VESTIGIAL_IMPORT`: only fires when ≥2 siblings from the same
  parent module are declared together AND at least one IS
  referenced; the all-unused case is left to the broader
  vestigial-import ladder. Single-entry `uses:` ([other.alpha])
  and same-named siblings from different parents
  (`uses: [other.A, third.B]`) do NOT participate. Severity ladders
  with mode: warning in migration/dev so authors see the finding
  while iterating, error in strict and release where the silent
  symmetry-asymmetry pattern signals real drift. See spec §4.5
  "`uses`" → "Cross-module symmetry warning" and plan post-Phase-2
  M-15 / POST-10k.

- **POST-10b — `runtime_only_requires:` module-header field.**
  Companion to `requires:` / `soft_requires:` for external Python
  imports the runtime needs but whose body-level use the static
  checker cannot see (canonically: `pytest` fixtures injected by
  the runner). Same parser path as `requires:` (inline + YAML
  block-list, colon-override and alias forms); same emitted
  import line (no try/except wrapper — these *are* installed by
  assumption); exempt from the Phase 4 `VESTIGIAL_IMPORT` scan.
  Surfaces in the IR under `imports.runtime_only_requires` (same
  shape as `imports.requires`) and in the code namespace
  identically to `requires:` so the namespace collision check
  treats both populations as one. The `ModuleDecl` AST node
  carries the new `runtime_only_requires: tuple[RequiresEntry, ...]`
  field defaulting to `()` for byte-for-byte backward
  compatibility with pre-POST-10b parses. See spec §4.5.1
  "`runtime_only_requires`", quick reference's Module Header
  Fields, and plan post-Phase-2 M-13 / POST-10b.

- **POST-10d — `[tool.soma].test_module_name_prefix_by_dir` opt-in
  for directory-aware `MODULE_NAME_COLLISION` checks.** Pre-0.16.0,
  two `.soma` files declaring the same `module <name>` always
  collided regardless of directory — a project with parallel test
  subdirs (`tests/unit/foo.soma` + `tests/integration/foo.soma`)
  had to hand-rename one of the modules even though the purpose of
  the two `foo` declarations was unambiguous from the directory
  layout. The new boolean flag defaults to `false` (preserving the
  pre-0.16.0 strict behaviour for every existing project). Set to
  `true`, the immediate parent-directory name of each test-context
  `.soma` file becomes an implicit prefix on the declared module
  name when the `MODULE_NAME_COLLISION` check runs — the effective
  names used by the collision check are `unit_foo` and
  `integration_foo`, but cross-module `uses:` references still
  resolve against the AST-declared `foo`. Production modules under
  `source_roots` are unaffected. A non-boolean value at the TOML
  surface raises `ValueError` at project-load time naming the
  supported shape. See spec §4.13 "Test-module dir-prefix opt-in"
  and plan post-Phase-2 M-14 / POST-10d.

- **POST-10g — `REQUIRES_DOTTED_LOWERCASE_HINT` validator warning.**
  When a `requires:` (or `soft_requires:` /
  `runtime_only_requires:`) entry is authored in dotted form
  (`uuid.uuid4`) and the body references the last segment as a
  bare identifier (`uuid4()`), the parser's UPPER_CASE heuristic
  misses the from-import shape because the last segment is
  lowercase. The result is a confusing diagnostic ladder:
  `VESTIGIAL_IMPORT` on `uuid` (the first segment, which the
  heuristic binds), plus a runtime `NameError` when the body
  actually executes. The new warning fires at warning severity in
  every mode (warning even in release because the existing code
  path either already works or fails loudly via a separate
  diagnostic; the hint's value is shortening the discovery loop,
  not gating release) and names the colon-override form
  (`uuid:uuid4`) explicitly in the remediation. The detector
  scans every body in the module for the lowercase last segment
  as a bare identifier and only fires the hint when the heuristic
  confusion is the active author error — qualified calls
  (`uuid.uuid4()` in the body) and bodies with no reference at
  all are silently skipped. See spec §4.5.1 "Common stdlib
  gotchas" → "uuid.uuid4" (POST-10g block) and plan
  post-Phase-2 M-14 / POST-10g.

### Changed

- **POST-11b — `soma test --quiet` suppresses every driver-side
  stdout print.** Pre-0.16.0, `soma test --quiet` left several
  driver-side print paths reaching stdout — most notably the build
  helper's one-line `Built N module(s). 0 errors, W warning(s).`
  summary (twice, once per build pass — source roots and test
  roots), and the friendly `soma test: no .soma test files found
  …` notice. Under POST-11b, the `--quiet` build summary is fully
  suppressed inside the test-runner's internal build pass
  (signalled by the hidden `_role` namespace attribute the runner
  sets on its argparse Namespace); the `soma test: no .soma test
  files found …` notice is also gated on `not args.quiet`. The
  `Running: <pytest-cmd>` driver banner was already gated pre-0.16.0
  and is pinned here as a regression target. Stderr is unaffected
  — pre-flight refusal messages, the conftest staleness diagnostic,
  and the synthetic-project warning still reach stderr under
  `--quiet`. The contract is "only pytest's stream to stdout",
  not "absolute silence on every channel". The user-facing
  `soma build --quiet` is unchanged: its legacy `Built N module(s).
  …` one-liner is preserved for back-compat (only the test-runner-
  invoked path is silenced, via the `_role` discriminator). See
  spec §4.17.2 "`soma test --quiet`", quick reference's CLI
  Commands row, and plan post-Phase-2 M-16 / POST-11b.

- **POST-11c — `soma build` exit-code semantics pinned by regression
  tests.** Verified and regression-pinned the existing exit-code
  contract: clean build (zero `error`-severity diagnostics) →
  `EXIT_SUCCESS` (0); any `error`-severity diagnostic →
  `EXIT_VALIDATION_ERROR` (1); pre-flight refusal (missing
  project, conflicting `--output-dir` without `--force-output-dir`,
  etc.) → `EXIT_USAGE_ERROR` (2). Warnings never block the build
  absent `--mode strict` (or higher) — the strictness ladder is
  the only knob that flips warning-only findings to blockers; no
  other CLI input does. The new tests in
  `tests/test_cli_minor_improvements.py::TestPOST11cBuildExitCodeSemantics`
  pin the four-shape matrix (clean → 0; dev-mode warning → 0;
  strict-mode same-warning → non-zero; hard error → non-zero) so
  future refactors cannot silently flip the contract. No
  behavioural change. See spec §4.17.3 "`soma build` exit-code
  semantics" and plan post-Phase-2 M-16 / POST-11c.

- **POST-7 — `soma check` accepts multiple paths and walks up for
  project context on subdir inputs.** The positional `source`
  argument is now `nargs="*"` — zero or more paths. With no args
  the command walks every configured `source_roots` +
  `test_roots` from the resolved `SomaProject`; with one or more
  paths each is processed in sequence and diagnostics are
  aggregated into a single report (one JSON document under
  `--format json`, never two concatenated documents). Overlapping
  inputs (a directory and a file under it; two directories that
  resolve to the same path) are deduplicated by resolved path so
  `MODULE_NAME_COLLISION` does not fire against a module
  colliding with itself. Subdir inputs (e.g.
  `soma check src/some_subdir/`) now resolve the project context
  by walking upward from the input path for a `pyproject.toml`
  carrying `[tool.soma]` rather than treating the subdir as the
  project boundary; the right `[tool.soma]` (with its
  `attribute_budgets`, `test_layering`, etc.) governs the
  invocation. An explicit `--project-root` still wins over the
  input-path walk-up. Empty configured roots, or roots that do
  not yet exist on disk, yield a friendly one-line no-op message
  on stderr with exit code 0 rather than the pre-0.16.0
  `EXIT_USAGE_ERROR`. The legacy single-positional form
  (`soma check <single-path>`) is byte-for-byte unchanged. See
  spec §4.16 "Validation Command (`soma check`)", quick
  reference's CLI Commands row, and plan post-Phase-2 M-11 /
  POST-7.

- **POST-6 — `[tool.soma].test_layering` opt-in for the cross-module
  layer-reachability check.** Tests routinely span layers as part of
  their job (a PRESENTATION test fixture instantiating an
  INFRASTRUCTURE service for end-to-end coverage; a DOMAIN test
  reaching an APPLICATION nerve) — but pre-0.16.0 the cross-module
  `CROSS_LAYER_DEPENDENCY` check fired on those edges with the same
  severity as a production module's. The result was persistent
  warning noise that the operator had to filter manually on every
  `soma check` run. The new `[tool.soma].test_layering` key opts a
  project into a relaxation: setting `test_layering = "permissive"`
  exempts modules that contain at least one `test` declaration from
  the cross-layer check. Production modules (zero `test`
  declarations) still receive the strict check regardless — the
  opt-in does not relax the rule for shipped code. The default
  `"strict"` preserves the pre-0.16.0 behaviour exactly; existing
  projects are unaffected. The carve-out trigger ("module has ≥1
  `test` declaration") mirrors the M13 helper-access rule
  (`HELPER_PRIVATE_TO_MODULE`) so a mixed module (production code +
  test) qualifies for the carve-out under both rules. Unknown
  values raise `ValueError` at project-load time naming the
  supported set, so a typo cannot silently disable the check. See
  spec §4.13 "Test-layer opt-in" + §4.0.2 footnote, quick
  reference's Project Configuration block, and plan post-Phase-2
  M-10 / POST-6.

- **POST-10d — `MODULE_NAME_COLLISION` diagnostic surfaces a
  descriptive-suffix steering hint.** Pre-0.16.0 the diagnostic's
  remediation was the generic "Rename one of the modules to avoid
  the name collision." The 0.16.0 refinement names a concrete
  descriptive-suffix candidate (e.g. `foo_unit` / `unit_foo` when
  the colliding files live under different `tests/<dir>` subdirs;
  `<name>_lib` / `<name>_test` as a conservative fallback when the
  parent dirs don't supply a useful hint). When at least one of
  the colliding files lives under a configured `test_root` and the
  project hasn't opted in to `test_module_name_prefix_by_dir`, the
  remediation also surfaces the opt-in flag as an alternative to a
  hand-rename. The diagnostic's code, severity (`error` in every
  mode), and message body all stay unchanged; only the remediation
  prose was refined. The helper lives at
  `cli/main.py::_module_collision_suggestion` and is consumed by
  every collision-emit call site (`_cmd_check`, `_cmd_build`,
  `_cmd_topo`, `docs_commands._parse_and_validate_files`). See
  plan post-Phase-2 M-14 / POST-10d.

- **POST-10e — `soma check tests/` surfaces project-level
  invariants alongside per-file findings.** Pre-0.16.0, project-
  level invariants like `MODULE_NAME_COLLISION` surfaced only at
  `soma build` time; `soma check` per-file passes did not run them
  even when the input clearly targeted multiple files (a directory
  walk or the POST-7 multi-path mode). The 0.16.0 behaviour
  closes the discovery-loop gap: a `soma check tests/` (or
  `soma check src/ tests/`) invocation aggregates per-file
  findings and runs the same collision check `soma build` does,
  so a duplicate module name across files surfaces at check time.
  Single-file invocations (`soma check src/foo.soma`) are
  byte-for-byte unchanged — they still parse + intra-module-
  validate only, because the cross-module work has no opposing
  module to compare against. Implementation aligns with the
  pre-existing multi-file aggregation surface added in M-11; the
  POST-10e milestone is the named contract pin and the regression
  test coverage in `tests/test_validator_round_2_fixes.py`. See
  plan post-Phase-2 M-14 / POST-10e.

### Added

- **POST-8 — `requires-python` forward-compat grammar pass.**
  Closes the 3.11 portability gap that previously let a project
  pinned `requires-python = ">=3.11"` ship un-importable code to
  a 3.11 consumer interpreter. The transpiler runs on Python 3.12,
  so a body that authored PEP 701 nested-quote f-strings
  (`f"x {f"y"}"`), walrus inside a comprehension
  (`[(y := x) for x in xs]`), or PEP 695 type-parameter / type-
  alias syntax (`def foo[T]: ...`, `class Foo[T]:`,
  `type Vector = list[T]`) would compile cleanly on the dev box
  and fail at import on a 3.11 operator workstation, several CI
  steps downstream from the actual mistake. The new pass
  (`IntraModuleValidator._check_python_grammar_compat`, gated on
  the captured `SomaProject.requires_python` range) walks every
  authored body — nerve, cell, ganglion, test — and fires
  `PARSE_GRAMMAR_FORWARD_INCOMPAT` (error in every mode) for each
  3.12-only construct it finds. The trigger is conservative: the
  pass fires only when every clause of `[project].requires-python`
  permits Python 3.11 (`>=3.11`, `>=3.11,<3.13`, `==3.11.x`, and
  `~=3.11` all trigger; `>=3.12`, `>=3.13`, `==3.12`, `!=3.11`,
  and `~=3.12` all suppress). Projects with no declared
  `requires-python` field also stay silent under the "no declared
  floor → no check" default. Bodies that fail to parse fall back
  gracefully — the outer `PARSE_ERROR` pass owns the syntax-error
  diagnostic; the compat pass intentionally never double-reports.
  Cells supplied via `content: @file()` are exempt (the embedded
  content is text the codegen writes verbatim into a string literal,
  not Python source). New module
  `src/soma_dsl/semantic/python_compat.py` hosts the detection
  helpers (`flag_python_312_only`, `requires_python_includes_311`,
  `Python312OnlyFinding`) so they are testable in isolation.
  `SomaProject` gains a `requires_python: tuple[str, ...] | None`
  field populated from `[project].requires-python` at discovery
  time. See spec §4.13 "`requires-python` forward-compat pass" +
  §4.16 "Forward-compat grammar pass", quick reference's Project
  Configuration block, traceability matrix
  `PARSE_GRAMMAR_FORWARD_INCOMPAT` row, and plan post-Phase-2 M-12
  / POST-8.

- **POST-5 — First-class `integration` declaration kind.** Promotes
  the D-15 IntegrationManifest pattern to a structural declaration
  the transpiler recognises, validates, and auto-emits boilerplate
  for. The new `integration <Name> :: INFRASTRUCTURE` header carries
  `version` / `intent` / `factory` / `smoke_test_primary` /
  `manifest:` fields; the emitter produces four module-scoped helper
  functions (`get_factory`, `get_manifest`, `smoke_test_primary`,
  `get_smoke_test`) registered with `module_scoped=True` (PRE-10) so
  two integrations declared in different modules can share these
  bare names without registry collision. The integration's name is
  also exposed as a module-level marker symbol bundling the four
  helpers, so cross-module consumers can write
  `uses: [<module>.<Integration>]` and reach the surface through one
  import. Four new error codes register:
  `INTEGRATION_FACTORY_NOT_FOUND`, `INTEGRATION_FACTORY_NOT_SERVICE`,
  `INTEGRATION_SMOKE_TEST_NOT_FOUND`, `INTEGRATION_INVALID_MANIFEST_KEY`
  (all error in every strictness mode); the existing `LAYER_MISMATCH`
  fires when the header is not `:: INFRASTRUCTURE`. The IR carries a
  new `integrations` section parallel to `helpers` (schema bumped to
  1.3.0 — additive; pre-POST-5 IR readers see an empty array). `soma
  inspect` renders an `Integrations` section showing the canonical
  id, intent, factory + smoke-test targets, manifest keys, and the
  four auto-emitted helper names. Critical compatibility: the
  legacy IntegrationManifest pattern (Phase 1 Google Calendar /
  Phase 3 Gmail / Slack) continues to work unchanged — adopting the
  new declaration is opt-in convenience, not a forced migration. See
  spec §4.4b, quick reference's Declaration Types section, patterns
  guide §23, and plan post-Phase-2 M-9 / POST-5.

- **POST-14 — Build manifest emits a companion Python type stub.**
  Every successful `soma build` now writes `<build_dir>/build.soma.pyi`
  alongside `build.soma.json` and `__init__.py`. The stub declares
  each emitted module as `<name>: ModuleType` plus a
  `BootstrapModules` `TypedDict` enumerating every module name, so
  consumer projects pointing their type-checker (mypy / pyright) at
  the build directory get checked `modules["<name>"]` lookups without
  falling back to `getattr` + duck-typing on a plain
  `dict[str, ModuleType]`. The renderer is byte-deterministic — no
  timestamps; two clean builds of the same project at the same
  s0ma-dsl version produce identical stub files. Emission is gated
  on the same `errors_so_far == 0` predicate as the manifest itself,
  so the two files are always consistent; pre-M-8 build directories
  without a stub keep working unchanged because
  `soma_dsl.runtime.bootstrap_imports` does not consult the stub at
  runtime (its return type stays `dict[str, ModuleType]`). The
  filename constant lives at
  `soma_dsl.codegen.build_manifest.MANIFEST_STUB_FILENAME` so tooling
  like `soma migrate-layout` and `soma verify` can reference it
  without importing the emitter module. See spec §4.14.3, quick
  reference's "Bootstrap Pattern" section, and plan post-Phase-2
  M-8 / POST-14.

## [0.15.0] — 2026-05-11

The 0.15.0 release lands the post-Phase-2 grammar-enrichment batch (M-2 through M-7 of the post-Phase-2 plan). Six milestones land together: M-2 (POST-9 a-i, doc + patterns guide additions), M-3 (POST-2 cell `category:` field), M-4 (POST-3a per-method `provides:` triples), M-5 (POST-3b/c test `mocks:` + provides cross-validation), M-6 (POST-3d nerve `internal:` helpers), M-7 (POST-4 a/b/c helper class bodies + `@inline` + `exports_helpers:`). Every change is additive and backward-compatible — pre-0.15.0 modules parse unchanged, no consumer call site is mandated to change, and `s0ma-core` stays at `0.3.0` (no companion bump this cycle). Five new error codes register: `MIXED_PROVIDES_FORMS`, `DUPLICATE_PROVIDES_NAME`, `MOCK_KEY_MISMATCH`, `PROVIDES_KEY_MISMATCH`, `EXPORTED_HELPER_NOT_FOUND`. IR and manifest schemas stay unchanged — every new field rides through the existing schemas additively.

### Added

- **POST-4a — `helper` accepts class bodies.** A `helper` declaration's
  body may now be a `class` definition in addition to the original
  `def` shape. Class-bodied helpers retire the legacy
  `cell kind: MODEL visibility: INTERNAL` workaround that previously
  routed module-private classes through the registry:
  ```
  helper _LocalCache :: APPLICATION
      intent: "Module-private LRU cache for the prompt formatter."
      ---
      class _LocalCache:
          def __init__(self): ...
          def get(self, key): ...
  ```
  The class is **not** registered as a component, carries **no**
  `@component` decorator, and is **not** added to `__all__`. The
  codegen emits a plain top-level `class <Name>:` preceded by the
  same `# Helper: <intent>` comment as a function-bodied helper. The
  IR records the structural shape under
  `IRHelper.body_kind = "class"`; `"function"` (the pre-POST-4a
  default) is unchanged. The access-control rule (§4.4a.3) is
  unchanged: production cross-module consumers still hit
  `HELPER_PRIVATE_TO_MODULE`; test-context consumers continue to
  qualify. Body kinds outside `function` and `class` (assignments,
  type aliases, bare values) are still rejected with `PARSE_ERROR`.
  See spec §4.4a.5 and plan post-Phase-2 M-7 / POST-4a.

- **POST-4b — `helper @inline` shorthand.** A helper may be declared
  inline inside the module header's `helpers:` block, dropping the
  separate `helper <name> :: <layer>` header and `---` separator:
  ```
  module foo
      layer: APPLICATION
      intent: "..."
      helpers:
        - helper _add @inline: "Quick addition" :: def _add(a, b): return a + b
        - helper _mul @inline: "Quick multiplication" :: def _mul(a, b): return a * b
      ---
  ```
  Each entry carries: the literal `helper`, the helper name, the
  `@inline` marker, a quoted intent string, `::`, and a single-line
  Python `def` body. Inline helpers always parse with
  `body_kind="function"` and `inline=True`; the IR records both
  fields. Inline and block-form helpers may coexist freely in the
  same module — the rule is "pick the right shape per helper," not
  "pick one shape per module." Inline helpers obey the same
  access-control rule as block-form helpers; duplicate names within
  a block raise `PARSE_ERROR`. See spec §4.4a.6 and plan
  post-Phase-2 M-7 / POST-4b.

- **POST-4c — `exports_helpers:` module-header field for cross-module
  re-export.** A module may declare which of its helpers are
  intentionally exposed for cross-module reachability:
  ```
  module shared_utils
      layer: APPLICATION
      intent: "..."
      exports_helpers: [_compare, _render_markdown]
      ---
  ```
  Each entry must name an actual `helper` declaration in the same
  module; otherwise the validator fires the new
  `EXPORTED_HELPER_NOT_FOUND` (error in every strictness mode). The
  field accepts both inline (`exports_helpers: [_a, _b]`) and
  block-list (PRE-7 / 0.14.0) forms. Re-exported helpers are
  appended to the emitted `__all__` after the regular `exports:`
  entries (in declaration order) and ride through the IR via
  `IRModule.exports_helpers`. **Reachability vs access control:**
  `exports_helpers:` widens reachability — re-exported helpers
  resolve cleanly when a test-context module names them in
  `uses: [<module>.<helper>]` — but **does not** widen access
  control. Production consumers (no `test` declarations) still
  hit `HELPER_PRIVATE_TO_MODULE` even for re-exported helpers;
  the diagnostic context carries `re_exported: true` so tooling
  can distinguish "production tried to reach a re-exported helper"
  from "production tried to reach a strictly-private helper."
  `exports_helpers:` cannot re-export helpers from other modules —
  every entry must be a `helper` declared in *this* module
  (the validator enforces this through `EXPORTED_HELPER_NOT_FOUND`).
  See spec §4.4a.7 and plan post-Phase-2 M-7 / POST-4c.

- **POST-3d — `internal:` field on `nerve` declarations exposing
  inner helper functions for introspection.** SERVICE nerves
  frequently use a factory-closure pattern where the public
  `provides:` operations share small private helpers (e.g.
  `_normalize_topic`, `_escape_html`) declared as inner `def`
  statements above the factory's `return {...}` dict. Those
  helpers live behind the closure — they are not components,
  not exported, and have no `register_*()` call. The new optional
  `internal:` field lets the author publish the private surface
  as structured metadata:
  ```
  nerve PromptAssembler :: APPLICATION
      kind: SERVICE
      ...
      provides: [assemble, validate]
      internal:
        - _normalize_topic: "Strip whitespace and lowercase the topic"
        - _escape_html: "Escape HTML-special chars"
      ---
      def assembler():
          def _normalize_topic(topic): ...
          def _escape_html(s): ...
          def assemble(topic): ...
          def validate(topic): ...
          return {"assemble": assemble, "validate": validate}
  ```
  Two surface forms parse identically:
  inline (`internal: [_foo, _bar]` — bare names only, no
  intent strings) and block (each entry is either bare `- _foo`
  or `- _foo: "intent"`, with both shapes freely mixable in
  the same block). Each entry name must be a Python identifier;
  duplicates within a block raise `PARSE_ERROR`. The field has
  **no codegen or registry effect** — the Python emitter ignores
  the field entirely, no `register_*()` call is generated for
  any entry, no new key appears in the `@component` `metadata=`
  dict, and the nerve body emits unchanged. The validator does
  not enforce that every named entry actually exists as a `def`
  in the body — the field is descriptive only. When non-empty,
  the value rides through the nerve IR record
  (`components[].fields.internal_helpers` in the `.soma.json`)
  as an ordered list of `{"name": str, "intent"?: str}` dicts,
  and `soma inspect` renders a dedicated `Internal helpers (<n>):`
  sub-section per nerve that has them — a reader can see the
  private surface at a glance without scrolling the body.
  Motivated by fr3d's MS 2 BundleEmitter and MS 16-core
  update-diff nerves, whose deep factory-closure bodies have
  carried several inner helpers each with no way for contributors
  or downstream tooling to discover the private API short of
  reading every body. Spec §4.1.7 carries the canonical
  reference; quick reference nerve-declaration syntax block
  lists the new row.
- **POST-3b — `mocks:` field on `test` declarations + cross-check
  against the target nerve's `provides:` surface.** A test
  declaration may now carry an optional `mocks: [<NerveName>, ...]`
  field naming the SERVICE / ADAPTER nerves whose public surface
  the test mocks:
  ```
  test assembler_test :: APPLICATION
      intent: "Verify the assembler factory exposes the right ops."
      tests: [assembler]
      mocks: [assembler]
      ---
      def assembler_test():
          mock_assembler = {
              "assemble": lambda parts: "".join(parts),
              "validate": lambda topic: True,
          }
          assert mock_assembler["assemble"](["a"]) == "a"
  ```
  Inline (`mocks: [a, b]`) and PRE-7 block forms parse identically.
  The field rides through the IR
  (`components[].fields.mocks` in the `.soma.json`) for downstream
  tooling (fr3d's Phase 2 Frontend track is the motivating
  consumer). The validator cross-checks any dict literal assigned
  to a variable whose lowercased name matches a `mocks:` entry
  (optionally with a `mock_` / `fake_` / `stub_` / `dummy_` /
  `fixture_` prefix) against the target nerve's `provides:` set
  and fires `MOCK_KEY_MISMATCH` (warning in migration/dev, error
  in strict/release) when the literal-string keys diverge.
  Conservative by design — dynamic mock construction (`dict(...)`,
  comprehensions, str-formatted keys) is silently skipped to avoid
  false positives. Cross-module mock targets resolved via `uses:`
  are accepted but the dict-key check runs only for local targets.
  Unknown mock targets raise `DOES_NOT_EXIST`. Spec §4.8.4 carries
  the canonical reference; the quick reference test declaration
  syntax block lists the new row.
- **POST-3a — per-method `returns:` / `expects:` / `guarantees:`
  triples on SERVICE-nerve `provides:` entries.** The flat form
  (`provides: [foo, bar]`) parses unchanged — every existing
  nerve carries no new behaviour. A new structured form lets
  authors declare per-method contracts inline, one entry per
  operation:
  ```
  provides:
    - assemble:
        returns: "str — the assembled prompt"
        expects: "topic: str (non-empty)"
        guarantees: "result is non-empty; topic is escaped"
    - validate:
        returns: "bool — True iff topic is well-formed"
  ```
  Every triple slot is independently optional. The per-method
  triple rides through the IR (`components[].fields.provides_contracts`
  in the `.soma.json`) and the emitted Python's
  `metadata={"provides_contracts": [...]}` dict so introspecting
  agents (fr3d's MS 11 settings, MS 12 budget, MS 17-local
  OAuth nerves are the motivating consumers) read per-method
  contracts at runtime without re-parsing the source or
  recovering them from docstrings + type-hints. When at least
  one entry carries a triple AND the body terminates with a
  `return {...}` literal, the validator additionally checks the
  returned-dict keys against the structured `provides:` names —
  closing the `"asemble"`-vs-`"assemble"` typo class without a
  separate `returns:` declaration. Two new always-error codes
  register the structured form's guard rails:
  `MIXED_PROVIDES_FORMS` (a block mixes flat and structured
  items) and `DUPLICATE_PROVIDES_NAME` (the same operation name
  appears twice in a structured block). Spec §4.1.3 carries the
  canonical reference with both surface forms documented; the
  quick reference declaration-types block lists the structured
  syntax; Patterns Guide §2.1.1 carries the SERVICE-pattern
  recipe.
- **POST-2 — `category: capability | behaviour` field on cell
  declarations.** Cells may now declare an optional high-level
  role via `category: capability` or `category: behaviour`.
  Omitting the field leaves the cell unchanged (legacy source
  parses identically). The value rides through the cell IR
  record (`fields.category` in the `.soma.json`) and is woven
  into the cell's `metadata` dict on every emitted
  `@component` / `register_constant` / `register_type` call, so
  downstream consumers see the role at runtime without re-
  reading the IR. `soma inspect` surfaces the value in the cell
  row's bracket label (`[PUBLIC CONSTANT cell, category=capability]`)
  parallel to how `is_page_composer:` surfaces on nerves. Invalid
  values raise `PARSE_ERROR` with a remediation naming the two
  valid alternatives. Motivated by fr3d's MS 19 ConfigDiff
  classifier, which has historically maintained a static name-
  pattern rule table to derive capability-vs-behaviour from cell
  names — the new field lets the classification come from the
  registry itself. Spec §4.2.5 carries the canonical reference;
  quick reference cell-declaration block lists the field
  alongside the other optional fields.

### Fixed

- **POST-3c — `provides:` ↔ `return {...}` literal-key strict-
  mode pass.** POST-3a / M-4 added a structured-form check that
  fires `MISSING_RETURN_KEY` when a structured `provides:` entry's
  name is missing from the body's terminal `return {...}` literal.
  POST-3c generalises the check to cover (a) the flat form too
  (`provides: [assemble]` with body `return {"asemble": assemble}`
  is now caught — closing the typo class on the flat form), and
  (b) the *extra-key* direction (a return-dict key that is not in
  `provides:` — the structured form's M-4 check did not catch this
  half). The new `PROVIDES_KEY_MISMATCH` code fires warning in
  migration/dev, error in strict/release. For structured nerves,
  POST-3c only fires the extra-key direction so `MISSING_RETURN_KEY`
  and `PROVIDES_KEY_MISMATCH` never duplicate on the same author
  error. Literal-keys-only by design: bodies that build their
  return dict via `dict(...)` or a comprehension are silently
  skipped — false positives on legitimate dynamic returns would
  erode author trust in the check. Spec §4.1.3 documents the
  rule and the documented limitation; the quick reference's
  auto-generated common-errors table now lists both new codes
  (regenerated via `make docs-derived`).

### Documentation

- **POST-9a — Decision-1 pattern** (abstract-down-to-DOMAIN
  remediation for `CROSS_LAYER_DEPENDENCY`). Spec §4.0.2's
  remediation list now names the pattern explicitly and links to
  the patterns guide. Patterns Guide §18 is the new home for the
  full recipe: abstract port in DOMAIN, concrete adapter in
  INFRASTRUCTURE with `depends_on: <Name>: {relation: CONSTRUCTS}`,
  three working instantiations (`LLMAdapter`, `MessageGateway`,
  `EventStore`).
- **POST-9b — Late-bind dependency slot recipe.** Patterns Guide
  §19 documents the `_field: list = [initial]` single-cell
  mutable-list idiom for back-edge late binding (planner ↔
  orchestrator, viz ↔ EventStore, six current fr3d
  instantiations). Covers the why (mutable-default lint, class
  vs instance scope, codebase-wide grep visibility) and when to
  prefer it over plain `__init__` injection.
- **POST-9c — Helper-as-fixture pattern.** Patterns Guide §20
  carries the decision rule: when `_make_X` would appear in two
  test blocks, hoist it to a module-level `helper`. Closes the
  long-running D-27 cross-block helper-name collision. Cross-
  referenced from spec §4.4a and §4.8.3.
- **POST-9d — Patch-via-context-manager + helper pair.** Patterns
  Guide §21 documents the `_patch_run_ok()` / `_patch_run(handler)`
  recipe via `unittest.mock:patch` for tightly-scoped patches.
  Covers when to prefer this over monkeypatch (composability,
  locality, no fixture-parameter plumbing) and the `_patch_X`
  naming convention.
- **POST-9e — Cross-thread `asyncio.Queue` pattern.** Patterns
  Guide §22 documents the `loop.call_soon_threadsafe(_safe_put,
  record)` bridge between sync-side vendor callbacks (Slack RTM,
  Discord WS, threading.Thread workers) and a loop-owned
  `asyncio.Queue`. Will recur for every Phase 4 channel adapter.
- **POST-9f — `requires:` import heuristic stdlib gotchas.** Spec
  §4.5.1 and the quick reference's `requires` Import Heuristic
  section now enumerate the four recurring stdlib patterns
  agents trip on: `urllib.<sub>` collisions, `uuid:uuid4`,
  `dataclasses` / `dataclasses:field`, and `argparse.REMAINDER`
  body-context. Adds the "body-evidence scope" note — the
  vestigial detector recurses into nested closures and inner
  `def`s inside class-bodied SERVICE / ADAPTER nerves.
- **POST-9g — `provides:` ↔ returned-dict-key three-way
  coupling.** Spec §4.1.3 surfaces the three-way coupling
  (`provides:` ↔ inner `def` names ↔ returned dict keys) up
  front with the canonical typo example (`"asemble"` vs
  `"assemble"`) and the validator's catch via
  `MISSING_RETURN_KEY` / `MISSING_PROVIDED_FUNCTION`. Class-
  bodied SERVICE shape carries the two-corner variant
  (`provides:` ↔ `def` names).
- **POST-9h — `abstract: True` vs `abstract: true`
  capitalisation.** Spec §4.1.4 now states that the canonical
  boolean literal form is lowercase (`true` / `false`), matching
  YAML / TOML conventions. The Python-cased `True` / `False` is
  accepted and normalised to lowercase in the IR, so existing
  source continues to parse; new authoring should use the
  lowercase form for visual consistency with other boolean-
  valued fields (`is_page_composer:`, `module_scoped:`).
- **POST-9i — Bootstrap-pattern docs (`argparse.REMAINDER`
  swallows `--`).** The coding-agent handbook gains §1.5
  documenting the thin-CLI dispatch pattern, the
  `argparse.REMAINDER` `--`-swallow gotcha, why `nargs="*"` is
  the wrong shape for this case, and the bootstrap-vs-
  presentation boundary on argparse usage. The quick reference's
  Bootstrap Pattern section carries the consumer-facing version.

## [0.14.0] — 2026-05-10

## [0.14.0] — 2026-05-10

The 0.14.0 release lands the s0ma-dsl half of the pre-Phase-2 improvements identified ahead of fr3d's Phase 2 (Local) milestone work. All changes are additive and backward-compatible — pre-PRE-2 manifests, transpiled artefacts, and consumer call sites continue to work unchanged. Pairs with `s0ma-core 0.3.0`, which adds the registry-side surface (`compute_registry_diff`, `module_scoped` flag, `module_path` parameter on `register_constant` / `register_type`).

### Added

- **PRE-2 — `role` field on `ModuleManifestEntry`** (default
  `"source"`). The build manifest can now carry both source modules
  and test modules in one unified payload. `bootstrap_imports`
  grows a `roles=("source",)` keyword that filters which entries
  to import — default behaviour matches the pre-PRE-2 dict exactly.
  Allowed roles are surfaced via the new `VALID_ROLES` frozenset
  on `soma_dsl.codegen.build_manifest`. Pre-PRE-2 manifests
  without a `role` key load with the back-compat default;
  unknown roles raise `ValueError` (caller bug).
- **PRE-7 — block-style YAML lists** on `uses:`, `requires:`,
  `exports:`, `raises:`. Items are introduced by `-` and must share
  a consistent indent strictly greater than the field column
  (canonical: 6 spaces). The parser reassembles the block into the
  canonical inline `[a, b, c]` form, so downstream field parsers
  (`_parse_name_list`, `_parse_import_list`) consume the result
  unchanged. Inline form is unchanged; mixed inline+block in the
  same field is rejected. Empty blocks raise `EMPTY_BLOCK_LIST`;
  divergent indents raise `INCONSISTENT_BLOCK_LIST_INDENT`.
- **PRE-8 — `module_path` threaded through `register_constant` /
  `register_type`.** The Python emitter passes
  `self.module_name` so the registry can attribute the constant or
  type alias to its owning module the same way `register_module`
  and `@component` registrations do. The runtime-bridge wrapper
  uses `inspect.signature` to forward the kwarg only when the
  installed `s0ma-framework` accepts it — older frameworks lose
  the attribution but do not crash.
- **PRE-9 — raw Python test discovery in `soma test`.** Files
  under `[tool.soma].test_roots` matching pytest's collection
  pattern (`test_*.py` / `*_test.py` / `*_tests.py`) are added to
  the pytest invocation when no `.soma` sibling exists. The
  "no `.soma` sibling" rule plus the flat-layout invariant
  (emitted `.py` lives in `build_dir`, not the test root) keeps
  the two collection sets disjoint. `conftest.py`, `__init__.py`,
  and `.soma.cache` / `__soma_cache__` subtrees are excluded.
  This closes the long-standing need to call `pytest` twice for
  raw integration tests / lint linters that don't fit a `.soma`
  body.

### Changed

- **PRE-3 — `soma test` writes a unified manifest with role
  tags.** `_run_build_for_test` now runs two build passes against
  the same output directory — first with `role="source"` for
  `source_roots`, then with `role="test"` for `test_roots`. The
  second pass merges with the manifest the first pass wrote, so
  the on-disk `build.soma.json` contains both sets. Production
  smoke (`bootstrap_imports(build_dir)` with default
  `roles=("source",)`) no longer requires re-running
  `soma build` after `soma test`. `--clean` skips the merge so a
  clean build always starts from an empty manifest.

### Fixed

- **PRE-6 — `soma build` prunes orphan artefacts.** After every
  successful build, ``.py`` / ``.soma.json`` / ``.soma.map``
  triples whose source no longer appears in the manifest are
  removed. Safety predicate (triple-check guard): a `.py` is
  pruned only when all three sibling artefacts exist — a
  hand-written `.py` without IR/map siblings is never touched.
  `__init__.py` is always skipped; the manifest file is never
  matched. Build with errors skips the prune so partially
  produced work remains recoverable.

### Documentation

- **PRE-4 — `visibility: TEST` is the canonical fix for
  INTERNAL-cell-test-target.** Spec §4.2.4 carries a new
  paragraph + runnable example documenting why INTERNAL blocks
  cross-module test access and how TEST closes the trap. The
  quick reference's visibility bullet gains a pointer at §4.2.4.
  The optional `TEST_REACHABLE_FROM_INTERNAL_HINT` lint rule
  is deferred to POST-10; the doc paragraph is the canonical
  reference until then.
- **Doc cleanup — strip PyPI / public-publish framing.**
  `docs/s0ma_user_guide.md`, `docs/s0ma_user_guide_condensed.md`,
  `docs/s0ma-core-spec-v0.2.0.md`, `docs/release_checklist.md`
  reframe install instructions for the private-repo editable
  workflow (`pip install -e ../s0ma`). CHANGELOG history is
  intact; historical `plans/` and `docs/historical/` content is
  left as-is. Mirrors the corresponding cleanup in `s0ma-core`.

## [0.13.0] — 2026-04-29

Closeout of the feedback 5–6 cycle. Cleanup pass landing five real consumer-bug fixes (Tier A: G1–G5), two doc-drift-prevention refinements (Tier B: G6, G7a/b), the long-pending pre-existing ruff cleanup (G8), and the deferred conftest template fix (G10) that surfaced during cross-project verification (G9). Builds on F1–F4's structural fixes (canonical body storage, `.soma.cache/` exclusion, explicit page-composer declaration). 13 consumer workarounds eliminated cumulatively across the M1–M20 + F1–F4 + G1–G10 work cycle. The minor bump (0.12.0 → 0.13.0) reflects three behaviour-changing surfaces: G3's `build_dir` sanitization changes the default value for hyphenated/dotted/spaced project names; G5's `STALE_GENERATED_CONFTEST` pre-flight is a new loud refusal that consumers must address (or opt past with `--force`); G1's `PACKAGE_MARKER` auto-classification reclassifies `__init__.py` files that previously surfaced as `UNKNOWN`. Every other change is additive.

### Added

- **G7a (feedback 5–6 cleanup): `doc-ref` accepts `covers: { source: error_codes }` to derive a Markdown table from the canonical error-code registry.** Pre-G7a, the doc subsystem's `doc-ref` filter mechanism only handled component-kind targets (`covers: [nerve where ...]` and friends). Every error-code addition required two coordinated edits — register the code in `SEVERITY_MATRIX` *and* hand-author a row in `docs/s0ma-dsl_quick_reference.md`'s Common Errors table — and a forgotten edit produced silent doc drift the meta-tests could only catch as a symptom (a missing traceability row), not as a root cause (the duplicated documentation surface). G7a closes the gap structurally on three surfaces: (1) the `doc-ref` grammar gains a sub-key form `covers: { source: <name> }` (a discriminated union with the historic list-of-filters form — exactly one is set per declaration; the parser rejects shapes that mix `kind:` and `source:` keys with a `PARSE_ERROR` carrying a remediation pointing at the two clean shapes); (2) the renderer's source-registry branch in `codegen/doc_emitter/markdown.py` materialises the named registry into a deterministic Markdown table (Code | Migration | Dev | Strict | Release | Description, sorted alphabetically by code, em-dash for "not applicable" / out-of-matrix cells); (3) `ERROR_CODE_DESCRIPTIONS: dict[str, str]` registered in `soma_dsl.config` next to `SEVERITY_MATRIX` is the canonical code → human-readable description mapping the renderer reads from. The only registered source today is `error_codes` (the union of `SEVERITY_MATRIX` and `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`); adding a future source registry is a one-line grammar change plus a new renderer branch. Schema stays at 1.2.0 — the change is additive (the `covers` field gains a new variant; old IRs still parse). G7a does *not* yet replace the hand-authored quick-reference Common Errors table — that's G7b's cutover, kept separate so the renderer can be parity-tested in isolation. Pinned by 11 tests in `tests/test_doc_ref_error_codes.py` against `tests/fixtures/doc_ref_error_codes/error_codes_doc.soma` (parser discriminator, parse-time rejection of malformed brace forms, renderer determinism, every-code-present invariant, severity-column formatting, and a parity check between the rendered code list and `docs/spec_traceability.md`'s code list — the safety check G7b's cutover depends on); plus a new completeness pin in `tests/test_doc_consistency.py::test_error_code_descriptions_match_severity_registries`. See spec §4.12.1 (`doc-ref` covers shapes) and plan G7a.

- **G6 (feedback 5–6 cleanup): out-of-matrix error code registry audit + AST-walking meta-test pins every code literal in `src/soma_dsl/` to `SEVERITY_MATRIX` or `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`.** Pre-G6, the canonical rule-to-implementation map (`docs/spec_traceability.md`) only had a meta-test pinning codes registered in `SEVERITY_MATRIX`; codes emitted directly by load-time / pre-flight surfaces (`HELPER_NAME_COLLISION`, `CONFLICTING_PACKAGE_DECLARATION`) lived in a test-local tuple inside `tests/test_doc_consistency.py` and any other unregistered code would silently rot — the M19a open question. G6's audit walked every `.py` file under `src/soma_dsl/` with `ast.parse` (not grep) extracting every `code="..."` keyword argument, every positional first-string argument to the four error constructors (`SomaError`, `SomaParseError`, `SomaSemanticError`, `SomaResolutionError`), and every `<CODE>: ...` message-prefix token inside a string or f-string (the convention used by `project.py` and `cli/main.py` for error sites that don't construct `SomaError`). 58 candidate codes surfaced; 49 were already in `SEVERITY_MATRIX` and 2 in the existing out-of-matrix tuple, leaving 6 unregistered codes that the audit triaged: `MODULE_NAME_COLLISION` (six emit sites across `cli/main.py` + `cli/docs_commands.py`; same load-bearing identity invariant as `MODULE_NAME_STEM_MISMATCH`), `DOC_RENDER_ERROR` (renderer-failure wrap; `cli/main.py` + `cli/docs_commands.py`), `INTERFACE_ON_NON_ABSTRACT` (validator structural contradiction), `MISSING_INTERFACE_METHODS` (intra-module + cross-module variants; declared identity ≠ implemented identity), `MISSING_PROVIDED_FUNCTION` (validator `provides:` check), and `MISSING_RETURN_KEY` (validator `returns:` dict-key check). All six were registered in `SEVERITY_MATRIX` as `error` in every strictness mode (each is a structural correctness violation — no mode-graded reading makes sense). `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE: tuple[str, ...]` was promoted from a test-local constant to a public export of `soma_dsl.config`, so the canonical list lives next to `SEVERITY_MATRIX` and the meta-test consumes a single-source-of-truth registry. New meta-test `test_every_error_code_literal_is_registered` walks the source tree at test time and asserts every extracted code is in one of the two registries; the existing `test_error_codes_in_traceability` and `test_out_of_matrix_codes_in_traceability` meta-tests continue to pin the registry-↔-traceability invariant. Six new traceability rows landed in `docs/spec_traceability.md` (one per newly-registered code). The decision rule for future contributors is documented in `docs/coding_agent_handbook.md` §2.3 ("Adding a new error code"): default to `SEVERITY_MATRIX`; only use `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE` when the code is structurally always-one-severity AND fires from a surface that doesn't carry a strictness mode. Closes the M19a open question. See plan G6 for the full audit + triage rationale.

- **G5 (feedback 5–6 cleanup): versioned `soma test-conftest` template + `STALE_GENERATED_CONFTEST` pre-flight detection in `soma test` + `--force` regeneration.** Pre-G5, the `conftest.py` emitted by `soma test-conftest` was a snapshot of the s0ma-dsl runtime contract at generation time; the file landed on disk with no version metadata, no content checksum, and no staleness contract. Months later, an upgrade silently invalidated the contract — kn0wthyself-website-2's M20 finding #7 was a real consumer hitting exactly this: a months-old generated conftest that patched `s0ma.runtime_bridge.registration.register_module`, but `s0ma.runtime_bridge` no longer exists in 0.12.x, so pytest aborted at import time with an opaque `AttributeError` several command invocations downstream from the actual cause. G5 closes the regression structurally on three surfaces: (1) every conftest emitted by `soma test-conftest` now carries a four-line banner — `# Generated by s0ma-dsl <ver>`, `# Content checksum: <sha256-of-body>`, a do-not-hand-edit notice, and a `--force` regeneration pointer (the checksum covers the body **below** the banner, so re-running `soma test-conftest` against the same s0ma-dsl version produces a banner whose checksum line agrees with the body byte-for-byte); (2) `soma test`'s pre-flight check reads the banner via the new pure helper `_classify_conftest(path) -> Literal["absent", "current", "untouched_stale", "customized_stale", "unrecognized"]` before invoking pytest, with the wire-up acting on three of the five states (skip on `absent`, proceed on `current`, auto-regenerate non-destructively with a one-line stderr notice on `untouched_stale`, refuse and surface `STALE_GENERATED_CONFTEST` on `customized_stale` and `unrecognized`); (3) `soma test-conftest` gains a `--force` flag for the "I have customizations and want a clean regeneration after preserving them" flow — without `--force`, the command refuses to overwrite an existing file (mirrors `soma new`'s safety default). The `untouched_stale` branch consults `STALE_GENERATED_CONFTEST_VERSION_CHECKSUMS: dict[str, str]` (mapping prior-version strings to their canonical body checksums); on initial G5 release the registry is **empty** because pre-G5 releases didn't embed banners and their generated bodies depended on project content (kind / layer comments), so retroactive population is not feasible. The fail-safe consequence is that every pre-G5 conftest classifies as `unrecognized` → loud `STALE_GENERATED_CONFTEST` error — by explicit plan choice (silent rewrites of files that may carry hidden customizations are a worse failure mode than a loud one-time error that asks the user to inspect, preserve, and run `--force`). `STALE_GENERATED_CONFTEST` is registered in `SEVERITY_MATRIX` as `error` in every strictness mode (silent runtime `try/except` swallowing was rejected on principles grounds — an opaque pytest-import-time error is exactly the failure mode the "no silent failures" rule exists to prevent). Pinned by 21 tests in `tests/test_conftest_staleness.py` against fixtures under `tests/fixtures/stale_conftest_project/` (current, customized-stale, unrecognized, no-conftest variants — `untouched_stale` is exercised via a runtime-monkeypatched registry since the on-disk shape would require a non-empty registry). Closes M20 finding #7. See spec §4.15 (Test Execution — Generated conftest banner + staleness detection), `docs/coding_agent_handbook.md` §9.4 (`soma test` runner internals — Conftest staleness pre-flight), and `docs/migration_guide.md` ("Workarounds that are now obsolete" #1 — G5 update).

- **G4 (feedback 5–6 cleanup): cross-source-root `uses:` resolution in `soma test`'s per-source-root build pass.** Pre-G4, `_cmd_test` iterated every configured `source_root` and dispatched each per-root build pass with `include_dirs=[]` — each pass saw only its own files. A project with multiple sibling source roots (e.g. `source_roots = ["domain", "application", "presentation"]`) and a `uses: domain.X` reference from `application/foo.soma` could not resolve the cross-root reference; the cross-module resolver raised `DOES_NOT_EXIST` against `order_model` and the build aborted before pytest got invoked. kn0wthyself-website-2 hit this exactly on its first migration attempt with a per-layer fan-out source-roots configuration (M20 finding #6). The hand-rolled workaround was to invoke `soma build -I <prior-layer> ...` per layer in dependency order, then run pytest directly against the resulting build dir. G4 closes the bug structurally: each iteration of the source-root loop now computes `sibling_includes = [r for r in source_roots_present if r != src_root]` (the source roots are already absolute resolved paths so dedup is implicit) and passes the list as `include_dirs` to `_run_build_for_test`. The per-root iteration is preserved — it remains the canonical surface for build-error attribution: a parse / validation failure still names the offending file's actual source-root path because every diagnostic carries the file's own absolute path, regardless of which build pass surfaced it. Single-source-root projects produce an empty sibling list (`include_dirs=[]`) and the post-G4 path reduces exactly to the pre-G4 path — no regression. Each per-root invocation is one-shot, so circular sibling-include patterns (A↔B, A→B→C→A) cannot induce a cycle: `_cmd_build` parses target files plus context (`--include`) files exactly once and does not recursively descend into includes. The test-root build pass continues to see *every* source root via the existing `include_dirs=source_roots_present` (M7 contract); G4 needed no edit there. `_cmd_build` itself is invoked once per `(project_dir, output_dir)` pair and does not iterate roots, so it carries no analogous defect and needs no edit. Pinned by 6 tests in `tests/test_multi_source_root_resolution.py` against the new fixture `tests/fixtures/multi_source_root_project/` (three sibling source roots — `domain/`, `application/`, `presentation/` — plus a tests root reaching into all three; covers the two-root cross-`uses:` case, the three-root cyclic-includes case, the test-root-sees-all-source-roots case, the single-source-root no-regression control, the build-error-attribution preservation case, and a subprocess end-to-end smoke). Closes M20 finding #6. See spec §4.15 (Test Execution — sibling-include behaviour), `docs/coding_agent_handbook.md` §9.4 (`soma test` runner internals — build-error attribution), and `docs/migration_guide.md` (workarounds eliminated #9).

- **G3 (feedback 5–6 cleanup): default `build_dir` sanitizes hyphens / dots / spaces / other non-identifier characters in `[project].name`; `INVALID_PROJECT_NAME_FOR_BUILD_DIR` for irrecoverable shapes.** Pre-G3, the default `build_dir` derivation in `SomaProject._from_tool_soma` was the literal `f"{project_name}_build"`. A consumer with `[project].name = "kn0wthyself-website-2"` got a default of `kn0wthyself-website-2_build/` — a directory whose last path component is not a valid Python identifier, so the M6a runtime-bridge contract `from <build_dir_basename> import <module>` silently failed at runtime. The transpile succeeded, the artifacts landed on disk, and consumers saw `ModuleNotFoundError` only when they wired up the runtime bridge (kn0wthyself-website-2 hit this exact shape on its first migration attempt; M20 finding #5). The pre-G3 workaround was to set `build_dir` explicitly to an underscored form, which conflated "I have a non-default layout preference" with "the default produces a broken build." G3 closes the bug structurally: the new helper `soma_dsl.project._default_build_dir(project_name: str) -> str` sanitizes every non-word character via `re.sub(r"\W", "_", project_name)` before appending `_build`, so hyphens, dots, spaces, and exclamation marks all sanitize to underscores automatically. Recoverable shapes (`foo-bar` → `foo_bar_build`, `foo.bar` → `foo_bar_build`, `foo bar` → `foo_bar_build`, `foo!bar` → `foo_bar_build`) need no explicit configuration. Irrecoverable shapes (project names that start with a digit, or sanitize to the empty string) raise `INVALID_PROJECT_NAME_FOR_BUILD_DIR` at project-load time with a remediation message instructing the author to set `[tool.soma].build_dir` explicitly to a valid Python identifier. Explicit `build_dir` values are validated the same way: `_from_tool_soma` checks `Path(build_dir).name.isidentifier()` so `out/foo_bar` is accepted (the parent path components are not the importable token) and `out/foo-bar` is rejected. The single-underscore edge case (`_`) sanitizes to itself and produces `__build` (valid Python identifier, unusual but accepted — the author can opt out with an explicit override). `INVALID_PROJECT_NAME_FOR_BUILD_DIR` is registered in `SEVERITY_MATRIX` as `error` in every strictness mode (a load-time configuration error is never softer than `error`). Pinned by 21 tests in `tests/test_build_dir_sanitization.py` against the new fixture `tests/fixtures/hyphenated_project_name/` (covers every recoverable / irrecoverable / explicit-validation / end-to-end-importability shape). Closes M20 finding #5. See spec §4.13 (`[tool.soma].build_dir` schema row + sanitization rule + validation rules), `docs/coding_agent_handbook.md` §1.1 (project-discovery internals), and `docs/migration_guide.md` ("Migration-recipe gotchas" + "Workarounds eliminated #8").

- **G2 (feedback 5–6 cleanup): pre-flight `OVERLAPPING_DISCOVERY_ROOTS` error for source/test-root nesting.** Pre-G2, when `[tool.soma].test_roots` was nested inside a `[tool.soma].source_roots` entry (the kn0wthyself-website-2 shape — tests at `src/<proj>/tests`), or vice versa, or when two roots within either list overlapped, `_discover_soma_files` walked the same `.soma` files twice and the cross-module resolver registered each `module <name>` declaration twice; the user saw an opaque `MODULE_NAME_COLLISION` against a file colliding with itself, several command invocations downstream from the actual mistake. M20 finding #4 surfaced this in real consumer migration. G2 closes it structurally: `SomaProject._from_tool_soma` calls a new helper `_detect_overlapping_roots(source_roots, test_roots)` after both lists are resolved to absolute paths, and any non-empty result raises with a message starting `OVERLAPPING_DISCOVERY_ROOTS:` that names every offending pair plus the two clean-config remediation options — (1) move tests outside the source root (`test_roots = ["tests"]`), or (2) narrow `source_roots` to disjoint layer subdirectories. The detector covers source-source overlap, test-test overlap, source-test overlap (in either nesting direction), identity (the same path declared in two roots), and arbitrarily deep nesting; multiple offending pairs at once surface together so the author clears every overlap in a single edit. `OVERLAPPING_DISCOVERY_ROOTS` is registered in `SEVERITY_MATRIX` as `error` in every strictness mode (a load-time configuration ambiguity is never softer than `error`). Silent dedup was rejected on principles grounds — see plan G2 deviations for the rationale. Pinned by 24 tests in `tests/test_overlapping_roots.py` against seven fixtures under `tests/fixtures/overlapping_roots/` (test-under-source, source-under-test, identical, source-source, test-test, deeply nested, multiple, plus the disjoint control). Closes M20 finding #4 / M20 open question (b). See spec §4.13 (`[tool.soma]` schema + disjoint-roots validation rule), `docs/coding_agent_handbook.md` §1.1 (project-discovery internals), and `docs/migration_guide.md` ("Migration-recipe gotchas").

- **G1 (feedback 5–6 cleanup): `PACKAGE_MARKER` is the fourth `soma verify` status, plus a `[tool.soma].package_markers` declarative escape hatch.** Previously, every `__init__.py` package marker in a consumer's source tree fell into `UNKNOWN` because the file had no embedded checksum and was not declared under `[tool.soma].bootstrap_files`. The workaround was to enumerate every layer's `__init__.py` under `bootstrap_files`, conflating "intentional plain-Python entry point" with "Python package marker." G1 retires the workaround structurally: `soma verify` consults a new helper `soma_dsl.project.is_empty_package_marker(path)` that returns `True` iff the file's stem is `__init__`, suffix is `.py`, and its body (after `ast.parse`) is empty or a single module-level docstring. Any executable content (imports, `__all__`, assignments, calls) disqualifies auto-classification — the file falls through to `UNKNOWN` unless explicitly declared. The new `[tool.soma].package_markers` config key mirrors `bootstrap_files` (list of relative paths, resolved to absolute, missing-on-disk produces a warning) and acts as the explicit escape hatch for `__init__.py` files carrying `__all__` re-exports the author wants acknowledged as markers. Explicit declaration wins over auto-classification. `PACKAGE_MARKER` is informational and hidden from default text output (mirroring `BOOTSTRAP`); `--verbose` surfaces the per-file rows and the count. Default summary footer stays `OK / BOOTSTRAP / UNKNOWN`; verbose extends to include the package-marker count. New error code `CONFLICTING_PACKAGE_DECLARATION` (out of `SEVERITY_MATRIX`, error in every mode) fires at project-load time when a file appears in both lists. Closes M20 finding #3 (DSL-side). Pinned by 25 tests in `tests/test_package_markers.py` against the new fixture `tests/fixtures/package_markers_project/`. See spec §4.13 (`[tool.soma]` schema + status taxonomy), `docs/coding_agent_handbook.md` §9.10 (`soma verify` runner internals), and `docs/migration_guide.md` (workarounds eliminated #7).

### Fixed

- **G5 (feedback 5–6 cleanup): stale generated conftests no longer cause opaque pytest-import-time `AttributeError`.** Closes M20 finding #7. Pre-G5, a months-old `conftest.py` emitted by an earlier `soma test-conftest` that referenced internals that have since moved (the kn0wthyself-website-2 case patched `s0ma.runtime_bridge.registration.register_module`; `s0ma.runtime_bridge` does not exist in 0.12.x) produced an opaque `AttributeError` at pytest import time, several command invocations downstream from the actual cause. Post-G5, `soma test` reads the new four-line banner before invoking pytest and surfaces `STALE_GENERATED_CONFTEST` (error in every strictness mode) at pre-flight time with a remediation pointing at `soma test-conftest --force`. See the `### Added` entry above for the surface details.

- **G4 (feedback 5–6 cleanup): cross-source-root `uses:` resolution during `soma test`'s per-source-root build pass.** Closes M20 finding #6. Pre-G4, every per-root build ran with `include_dirs=[]` — sibling source roots were invisible to each other, so a `uses: domain.X` reference from `application/foo.soma` raised `DOES_NOT_EXIST` and aborted the build before pytest ran. The hand-rolled workaround (`soma build -I <prior-layer>` per layer, then run pytest directly) is gone post-G4: `soma test`'s source-root loop threads sibling roots through `--include` automatically. Per-root iteration is preserved so build-error attribution still names the actual offending root, not a sibling. See the `### Added` entry above for the surface details.

- **G3 (feedback 5–6 cleanup): default `build_dir` now sanitizes hyphens (and other non-identifier characters) to underscores so projects with hyphenated package names get importable build outputs without explicit `[tool.soma].build_dir` configuration.** Closes M20 finding #5. Pre-G3, a project with `[project].name = "kn0wthyself-website-2"` got a default `build_dir` of `kn0wthyself-website-2_build/` — the transpile succeeded but the runtime bridge's `from kn0wthyself-website-2_build import <module>` failed silently with `ModuleNotFoundError` because the basename is not a valid Python identifier. Post-G3, the default sanitizes to `kn0wthyself_website_2_build/` and the import works without any consumer-side configuration. Irrecoverable shapes (digit-start names, sanitizes-to-empty) still raise loudly at project-load time via the new `INVALID_PROJECT_NAME_FOR_BUILD_DIR` error code with a remediation message; explicit `build_dir` values are validated against the same identifier rule (the directory's last path component is the importable token). See the `### Added` entry above for the surface details.

- **G2 (feedback 5–6 cleanup): opaque `MODULE_NAME_COLLISION` against a file colliding with itself when `source_roots` and `test_roots` overlap.** Closes M20 finding #4. Pre-G2, the failure mode was silent-walk-then-loud-error several command invocations downstream from the mistake; the diagnostic did not mention the roots, so the author could not connect the collision to the misconfiguration without reading the discovery code. Post-G2, `OVERLAPPING_DISCOVERY_ROOTS` fires at project-load time before any subcommand runs with a message naming both offending paths plus the two clean-config remediation options. See the `### Added` entry above for the surface details. Also closes M20 open question (b) — the source-root/test-root overlap rule is a pre-flight error, not a silent fix.

- **G1 (feedback 5–6 cleanup): empty `__init__.py` files no longer surface as `UNKNOWN` in `soma verify` output.** Closes M20 finding #3. The structural fix retires the M11-era workaround of enumerating every layer's `__init__.py` under `[tool.soma].bootstrap_files`. Auto-classification covers the canonical empty / docstring-only shapes; the new `[tool.soma].package_markers` key handles the unusual `__all__`-bearing case. fr3d's six `__init__.py` files (and kn0wthyself-website-2's count) auto-classify as `PACKAGE_MARKER` without any `[tool.soma]` edit. See the `### Added` entry above for the surface details.

- **F1 (feedback 5–6 follow-up): M17 `CONSTANT_NAME_MISMATCH` false-positive on multi-line CONSTANT bodies.** A CONSTANT cell whose body assigned a triple-quoted string with column-0 lines (e.g. `BIG_TEMPLATE = """\n<html>...`) used to trigger a spurious `CONSTANT_NAME_MISMATCH` because the validator's M17 helper called `textwrap.dedent` on the raw body, that strategy collapses the common leading prefix to the empty string when any line is already at column 0, the still-indented assignment then failed `ast.parse` with `IndentationError`, and the helper swallowed the parse error and reported zero assigned names. Both fr3d and kn0wthyself-website-2 hit the false-positive in the M20 smoke test. F1 closes it structurally: the body-dedenting logic is now consolidated. The parser dedents bodies exactly once at parse time via `parser.body_extractor.extract_body`; every downstream consumer (validator, codegen, IR, derived edges, source map, doc subsystem) reads the canonical dedented body. Duplicate `_dedent_body` and `textwrap.dedent` calls in the codegen, validator, and derived-edges analyzer have been removed. See ADR-009 (`docs/adr/ADR-009-canonical-body-storage.md`) for the architectural rationale and `tests/test_canonical_dedent.py` for the regression pin.

- **F2 (feedback 5–6 follow-up): `soma test` no longer collects test-shaped artefacts from inside `.soma.cache/` or legacy `__soma_cache__/` directories.** Pre-F2, `soma test`'s pytest invocation passed `<build_dir>` as the collection target with no `--ignore` flags. The hidden `.soma.cache/` directory M6a/M6b introduced for incremental-rebuild bookkeeping holds transpiled `.py` artefacts whose names match the `python_files = test_*.py *_tests.py` glob — pytest collected them alongside the real `<build_dir>/*.py` artefacts, double-registering every component and producing `RegistrationError: Component 'X' is already registered` at import time. fr3d's M20 smoke test (`plans/feedback_5-6/feedback_5-6_smoke_results.md` Finding #2) was blocked by exactly this. F2 closes the regression by adding `--ignore=<abs_path>` for every plausible cache location to the pytest invocation: `<build_dir>/.soma.cache/`, `<build_dir>/__soma_cache__/`, `<project.root>/.soma.cache/`, `<project.root>/__soma_cache__/`, plus `__soma_cache__/` under each configured `source_root` and `test_root`. The legacy `__soma_cache__/` exclusions protect mid-migration consumers that have not yet run `soma migrate-layout`. Flag values are absolute paths (no globs — a user directory whose name contains `.soma.cache` as a substring is not wrongly excluded). Pytest accepts non-existent `--ignore` paths harmlessly so the exclusion is unconditional. Pinned by `tests/test_soma_test_cache_exclusion.py` (4 tests) and `tests/fixtures/cache_pollution_project/`. See `docs/s0ma-dsl-spec-v0.12.0.md` §4.15 (Test Execution) and `docs/coding_agent_handbook.md` §9.4 (`soma test` runner internals) for the user-facing contract.

### Changed

- **G7b (feedback 5–6 cleanup): the Common Errors table in `docs/s0ma-dsl_quick_reference.md` is now auto-generated from the canonical error-code registry; hand-edits to the bracketed region are caught by `tests/test_doc_consistency.py::test_common_errors_table_matches_doc_ref_output`.** Pre-G7b, the quick reference carried a hand-authored ~20-row Common Errors table — every error-code addition required two coordinated edits (`config.py` + the quick reference's table); a forgotten edit produced silent drift (the meta-test from G6 caught the symptom — a missing traceability row — but not the root cause: a duplicated documentation surface). G7b closes the structural gap. Three new artefacts ship with the repo: (1) `docs/_generators/common_errors.soma` — the in-repo `doc-ref` declaration that uses G7a's `covers: { source: error_codes }` form to pull from `SEVERITY_MATRIX | OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE` plus `ERROR_CODE_DESCRIPTIONS`; (2) `docs/_generated/common_errors.md` — the rendered artifact, auto-generated from (1) and committed to the tree (the `_generated/` prefix is the human-readable convention marking a directory as machine-output, do-not-hand-edit); (3) `Makefile` target `make docs-derived` — the wrapper that invokes `soma docs render docs/_generators/ --output-dir docs/`. The hand-authored Common Errors block in the quick reference is replaced by a bracketed `<!-- BEGIN auto-generated common-errors-table; do not hand-edit; regenerate with `make docs-derived` -->` ... `<!-- END auto-generated common-errors-table -->` region holding a copy of the rendered table portion (frontmatter is excluded — it carries transpiler-version metadata that is irrelevant for human-facing docs and would couple the quick reference to release cadence). The choice to inline the rendered content (rather than use a markdown include directive) is portability — GitHub's renderer, the agent-system markdown previewers, and the spec/migration-guide rendering paths each handle includes differently or not at all; inlined content renders identically everywhere. Two new meta-tests in `tests/test_doc_consistency.py` pin the cutover: `test_common_errors_table_matches_doc_ref_output` re-renders the `doc-ref` at test time and compares the table portion against the bracketed region in the quick reference (the comparison is against the renderer's CURRENT output, not the committed `_generated/` artifact — so hand-edits to either surface fail the test); `test_common_errors_generated_artifact_matches_doc_ref_output` separately pins the committed `_generated/common_errors.md` to the renderer so a stale artifact does not mask a registry edit. The s0ma-dsl repo is not itself a `[tool.soma]` project (it is the transpiler, not a project that consumes the transpiler); the `make docs-derived` Makefile target is the alternative invocation path the plan permits. Adding a future error code to `SEVERITY_MATRIX` / `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE` / `ERROR_CODE_DESCRIPTIONS` is now a one-edit change followed by `make docs-derived`; the meta-test runs on every CI cycle and surfaces drift loudly. See spec §4.12.1 and `docs/coding_agent_handbook.md` §9.11 for the full pattern. Closes B3 (part 2 of 2).

- **AST declaration nodes' `body` field is now the canonically-dedented form (F1).** `NerveDecl`, `CellDecl`, `GanglionDecl`, `TestDecl`, and `HelperDecl` carry their body in column-0 Python-ready form on `body`. A new `raw_body` field preserves the original .soma indentation for diagnostics (source maps, error-reporting line offsets). `ExampleDecl` follows the same shape with `python_body` (canonical) and `raw_python_body` (raw). The IR's body serialization is unchanged in field name and shape: `body` still spells `body`, but its bytes are now the canonical form, not the raw form. Existing IR readers that just round-trip the `body` field see a Python-ready value and need no changes; tooling that *did* need raw-with-indent (none in this repo) should now read `raw_body`. Doc-subsystem content hashes are recomputed against the canonical body — one fixture (`tests/fixtures/golden/docs/walkthrough.md`) was regenerated as a result.

- **F3 (feedback 5–6 follow-up): M18's `exactly_one_per_page` budget shape now requires nerves to be explicitly marked `is_page_composer: true`.** The previous heuristic ("page = top-level module in the `uses:` graph") was opaque and had documented edge cases — test modules looked like top-level pages, projects with no `uses:` edges had every module flagged, and fully-circular graphs silently no-opped. F3 replaces the heuristic with a first-class `is_page_composer: bool = false` field on `NerveDecl`, parsed from `is_page_composer:` on a nerve declaration, serialised to the IR (additive — schema stays at 1.2.0), and surfaced in `soma inspect` (marked nerves carry a `page_composer` flag in the bracket label). The validator's `exactly_one_per_page` walker now seeds itself from the explicitly-marked nerves only; the heuristic function (`_top_level_modules`) was deleted, not just guarded. A new error code `NO_PAGE_COMPOSER_DECLARED` (error in every mode — including migration) fires loudly when the project configures `exactly_one_per_page` but no nerve carries the marker. Existing fixtures under `tests/fixtures/landmark_budget/` were updated in place; new stress fixtures under `tests/fixtures/page_composer_topologies/` cover two-pages-shared-subcomponent, test-module-not-a-page, no-`uses:`-edges-isolated-nerves, fully-circular `uses:` graph, and zero-marked-nerve topologies. Projects that adopted M18's `exactly_one_per_page` budget must update their nerves; pure `unique_in_project` and `warn_on_duplicate` adopters are unaffected. See spec §4.1.6 (`is_page_composer:`), §4.13 (budget shape), `docs/migration_guide.md` ("M18 attribute_budgets: explicit page composers required"), and `docs/references/dsl_patterns_guide.md` §16 for the full contract.

### Internal

- **G8 (feedback 5–6 cleanup): pre-existing ruff cleanup, 720 → 0 errors across two phases.** The ruff baseline at G1-start was nonzero (a long-standing tech-debt accumulation); the cleanup plan called for closing it before the release-prep milestone so the post-release baseline starts clean. Phase 1 (single commit, `ruff check src/ tests/ --fix --unsafe-fixes`) auto-resolved 512 errors mechanically across F401 unused-import, I001 unsorted-imports, F541 f-string-missing-placeholders, UP037 quoted-annotation, C420 unnecessary-dict-comprehension, TC001/TC003 typing-only-import (auto-moved to TYPE_CHECKING), SIM300 yoda-conditions, SIM114 if-with-same-arms, TC005 empty-type-checking-block, UP017 datetime-timezone-utc, UP032 f-string, F811 redefined-while-unused, and C416 unnecessary-comprehension. Phase 2a (single commit, hand-fix) cleared the small remaining categories (B007, B017, B023, B904, E741, N802, N806, N814, N818, SIM102, SIM105, SIM108) — 23 sites total, each annotated with a same-line reason comment when a `# noqa` was retained for a documented design reason (eight retained, all rationalized in the deviations entry: `N802` for callable-shaped factories; `SIM108`/`SIM102` for explanatory-comment branches that ternary collapse would orphan; `N818` for `SomaProjectNotFound` public API; `N806` for CLRS three-color DFS state names). Phase 2b (single commit, hand-fix) cleared all 244 E501 line-too-long errors via a catalogue of split patterns: `intent="..."` decorator strings (89 sites) split via implicit string concatenation in parenthesised groups with a trailing-space-on-each-non-final-chunk convention (load-bearing — the first auto-fix attempt omitted the trailing space and produced rendered prose with concatenated word boundaries); `add_argument(...)` argparse calls (38 sites); `ERROR_CODE_DESCRIPTIONS` dict entries (43 sites); long error-message strings, `Contract` field strings, `context={...}` dicts, embedded test-body strings, and assert-chain expressions. Tests stayed green at every commit boundary (1826 passed, 1 skipped throughout). No behavioural changes; the post-G8 source tree compiles to byte-identical `.py` output for every fixture. See plan G8 deviations for the full catalogue and the trailing-space convention rationale.

### Fixed

- **G10 (feedback 5–6 cleanup): conftest template's `register_module` patch target corrected to the canonical `soma_dsl.runtime_bridge.registration.register_module`.** Closes G9-1 (the regenerated-conftest-still-fails-at-fixture-setup finding G9's smoke surfaced after G5 closed the *detection* gap). Pre-G10, `_render_conftest_body` in `cli/main.py` emitted `with patch("s0ma.runtime_bridge.registration.register_module", side_effect=mock_register_module):`; the framework's `s0ma` package has never exposed `s0ma.runtime_bridge` as an attribute (the path was a long-standing bug in the template, not a recent framework drift), so the test fixture failed at setup with `AttributeError: module 's0ma' has no attribute 'runtime_bridge'`. The right patch target is the soma-dsl runtime bridge — `soma_dsl.runtime_bridge.registration.register_module` — because Python's `unittest.mock` resolves patch targets where they are *used*, not where they are defined; transpiled modules in a consumer's `<build_dir>/` import `register_module` from `soma_dsl.runtime_bridge.registration` (see `codegen/python_emitter.py`). The G9-1 deviations entry initially recommended `s0ma.register_module`; G10's investigation confirmed that recommendation was misdiagnosed and pinned the correct path. Two new regression tests in `tests/test_conftest_staleness.py` pin the cutover going forward: `test_conftest_patch_targets_resolve_against_live_modules` walks every `unittest.mock.patch(...)` target string-literal through `importlib.import_module` + `hasattr` at test time so any future template edit hitting an unresolvable attribute fails at the s0ma-dsl test boundary (not at consumer pytest collection); `test_conftest_register_module_target_is_soma_dsl_runtime_bridge` pins the canonical name explicitly. The body-shape change recomputes the body checksum, so pre-G10 `0.12.0`-banner conftests classify as `customized_stale` at `soma test` pre-flight (G5's loud-error contract holds — the user is pointed at `soma test-conftest --force`). See plan G10 deviations for the where-it-is-used reasoning and the regression-test design.

### Documentation

- **G9 (feedback 5–6 cleanup): cross-project re-verification + ADR-010 + cleanup-plan rollup.** Re-ran the M20 / F4 smoke recipe (`soma check --mode strict`, `soma build`, `soma test`, `soma verify`) against fr3d and kn0wthyself-website-2 under post-G8. **All five M20 Tier A findings (#3, #4, #5, #6, #7) are closed end-to-end.** fr3d's `soma verify` UNKNOWN count drops from 7 (F4) to 1 (G9) via G1's auto-classification; kn0wthyself-website-2 drops from 2 to 1; both residual UNKNOWNs are `__init__.py` files carrying executable `__version__` assignments, correctly excluded from auto-classification. kn0wthyself-website-2's `[tool.soma]` config no longer needs the F4 explicit `build_dir = "kn0wthyself_site_build"` override (G3 sanitizes the hyphenated name automatically) or the F4 manual per-layer `soma build -I` workaround for cross-source-root resolution (G4 threads sibling roots through `--include` automatically). G5's `STALE_GENERATED_CONFTEST` pre-flight surfaces loudly on the M20-vintage conftest with the right `--force` remediation; the regenerated conftest carries the four-line banner. One new G9 finding (the regenerated conftest body still references `s0ma.runtime_bridge.registration.register_module`, which the current framework no longer exposes) captured in deviations and slated for the next minor cycle — distinct from M20 #7 (G5 closes the *detection* mechanism; G9-1 is the *template content* drift, structurally separable). Workarounds eliminated tally: M20 listed 6, F4 added 2, G9 confirms 5 more = **13 total**. Full smoke results, per-finding closure mapping, per-milestone summary, and PR-strategy recommendation in `plans/5-6_cleanup_smoke_results.md`. Added `docs/adr/ADR-010-derived-doc-targets.md` documenting G7's grammar extension (`doc-ref` `covers:` discriminated-union with the `{ source: <name> }` sub-key form chosen over polymorphic bare-string sentinels) as the canonical shape for future derived-doc registries; "Alternatives Considered" enumerates six options (A–F). `docs/adr/README.md` indexed the ADR-010 row. Two new G9 meta-tests in `tests/test_doc_consistency.py` pin ADR-010's existence and the ADR README's index row.

- **G6 (feedback 5–6 cleanup): meta-test now pins every error code literal in `src/soma_dsl/` to either `SEVERITY_MATRIX` or `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`, preventing silent traceability drift.** See the `### Added` G6 entry above for the audit + triage rationale, the six newly-registered codes, and the decision rule documented in `docs/coding_agent_handbook.md` §2.3.

- **F4 (feedback 5–6 follow-up): cross-project re-verification + ADR-009.** Re-ran the M20 smoke recipe against fr3d and kn0wthyself-website-2 to confirm F1, F2, and F3 closed the three M20-blocking findings end-to-end. Results captured in `plans/5-6_follow-up_smoke_results.md`; per-project verdicts and remaining (deferred) findings tabulated there. Added `docs/adr/ADR-009-canonical-body-storage.md` documenting F1's structural decision: bodies are dedented exactly once at parse time, the canonical dedented form is the single source of truth across validator, codegen, IR, source map, and doc subsystem, and Options A–F (extract dedent helper to shared module, swap to `inspect.cleandoc`, validator parses generated Python, hand-rolled token analysis, smarter dedent strategy, deduplicate by import) were all rejected in favour of Option G (single dedent at parse time). `docs/adr/README.md` updated to index ADR-009; `docs/adr/ADR-008-test-visibility.md` gained a "Related decisions" pointer to F3's heuristic-to-explicit shift in `attribute_budgets.py`.

## [0.12.0] — 2026-04-28

The consumer-feedback release. Six critical fixes, four high-value language additions, comprehensive doc-surface updates. Every change in this release traces back to a real-world consumer-project pain point (the fr3d, kn0wthyself viz, and kn0wthyself-website-2 audits in [`s0ma-dsl-feedback-5.md`](plans/feedback_5-6/s0ma-dsl-feedback-5.md), [`s0ma-dsl-feedback-5.5.md`](plans/feedback_5-6/s0ma-dsl-feedback-5.5.md), and [`s0ma-dsl-feedback-6.md`](plans/feedback_5-6/s0ma-dsl-feedback-6.md)). The headline shape: a declarative project model in `pyproject.toml`, a single flat build layout (no more `__soma_cache__/`), three new language surfaces (`helper`, `visibility: TEST`, `@file()` embeds), project-level structural budgets, and a project-aware `soma test` that retires every consumer-side `PYTHONPATH=...__soma_cache__ pytest ...` wrapper.

### Added

- **Project model.** `[tool.soma]` table in `pyproject.toml` is now the
  canonical configuration entry point. `SomaProject.discover()` walks
  upward from any working directory; recognised keys are
  `source_roots`, `test_roots`, `build_dir`, `bootstrap_files`,
  `test_runner`, and the `[tool.soma.attribute_budgets]` sub-table.
  Every CLI subcommand resolves a `SomaProject` before dispatching;
  a new global `--project-root` flag overrides the discovery start
  path. Projects without `[tool.soma]` run in legacy mode with a
  one-line warning per invocation; legacy mode uses synthetic defaults
  (`SomaProjectNotFound` is the underlying exception). (M1, M11, M15,
  M18; spec §4.13; ADR-005.)
- **`helper` declaration kind.** Module-private functions that live at
  module scope, are not registered as components, but are
  introspectable via `soma inspect`. Test modules in any project
  module may import helpers via `uses:`; production cross-module
  access raises `HELPER_PRIVATE_TO_MODULE` (error in every strictness
  mode). Codegen emits a plain `def` with no `@component` decorator
  and no `register_*()` call. New AST node `HelperDecl`, new
  `DeclarationType.HELPER`, new `SomaModule.helpers` field, new IR
  schema field `IRDocument.helpers`. The `soma inspect` text
  pretty-printer renders a separate `Helpers (N):` section. Resolves
  feedback-5 MS 1 (~160 lines of nested helpers) and feedback-6
  MS 13/16 (D-36 recorder duplication). (M13; spec §4.4a; ADR-008.)
- **`visibility: TEST`.** A third visibility level for nerves and
  cells. TEST components are accessible to test modules in any project
  module (a module qualifies as a test consumer when it contains at
  least one `test` declaration) but hidden from production code in
  other modules. They are exempt from the public export surface — not
  in `module.exports`, exempt from `NOT_EXPORTED`, and never in the
  emitted `__all__`. Cross-module production consumption fires the new
  `TEST_VISIBILITY_VIOLATION` error (error in every strictness mode).
  `soma inspect` renders `[TEST <KIND>]` distinctly. Replaces the
  copy-paste-helper-into-test workaround documented across feedback-5.5
  M02–M07. (M8; spec §4.10.1, §5; ADR-008.)
- **`content: @file("path")` directive on CONSTANT cells.** Embed
  external files (HTML, SQL, prompts, JSON schemas) by reference
  rather than inline as a triple-quoted body. The transpiler reads the
  file at build time, hashes it for cache invalidation, and lists it
  in `build.soma.json` under `external_content_files`. Editing the
  embedded file invalidates the consuming module's cache. Restricted
  to `kind: CONSTANT` in 0.12.0; combining with an inline `---` body
  or applying to other cell kinds is a `PARSE_ERROR`. New error code
  `EMBEDDED_FILE_NOT_FOUND` (error in every mode). New AST fields on
  `CellDecl`, new manifest dataclass `ExternalContentFileEntry`, new
  cache helpers `scan_embed_paths` / `compute_embed_hashes`. Closes
  the kn0wthyself viz-template case (1010-line `.soma` file with
  ~990 lines of embedded HTML/CSS/JS — feedback-5 MS 2/3). (M12;
  spec §4.2.2.)
- **`declares_attributes:` field on nerves + `[tool.soma.attribute_budgets]`
  project configuration.** Domain-agnostic mechanism for cross-component
  structural-uniqueness validation. A nerve declares zero or more
  `<namespace>:<attribute>` strings (`landmark:header`, `route:GET /self`,
  `css_class:btn-primary`); a project opts into enforcement by mapping
  a namespace under `[tool.soma.attribute_budgets]` to one of three
  shapes: `exactly_one_per_page` (one per top-level page composer's
  reachable nerve set), `unique_in_project` (at most one project-wide),
  or `warn_on_duplicate` (warning-severity duplicates). Violations
  surface as the new `ATTRIBUTE_BUDGET_VIOLATION` diagnostic at
  `soma check` / `soma build` time. Generalises the original
  `declares_landmarks:` request from feedback-5.5 (the fr3d two-`<nav>`
  regression that only surfaced at runtime). (M18; spec §4.13 + nerve
  declaration.)
- **Build manifest `build.soma.json`.** Schema `soma-build-manifest@1`,
  emitted alongside transpiled artifacts at the build-dir root. Lists
  every module (absolute source path, output / IR / source-map basenames,
  `sha256:<hex>` source and output hashes), plus top-level `project`,
  `build_dir`, `transpiler_version`, `built_at`, and (M10)
  `topological_import_order`. M12 may add `external_content_files`
  under the same schema. New module
  `soma_dsl.codegen.build_manifest`; new helpers
  `BuildManifest`, `ModuleManifestEntry`, `build_manifest()`,
  `emit_manifest()`, `load_manifest()`, `compute_file_hash()`. New
  runtime-bridge entry point
  `soma_dsl.runtime_bridge.registration.import_modules_from_manifest`
  reads the manifest and imports every listed module — filesystem
  traversal as a fallback is deliberately not supported. The build's
  stdout summary now reads `Build complete: M modules → <build_dir>
  (manifest: build.soma.json)`. (M6b, M10, M12; spec §4.14.)
- **Topological bootstrap.** `build.soma.json` carries
  `topological_import_order` — the dependency-first list of project
  module names computed via Kahn's algorithm with alphabetical
  tie-breaking. New runtime helper
  `soma_dsl.runtime.bootstrap_imports(build_dir)` reads the manifest
  and imports modules in that order, replacing every consumer
  project's hand-maintained `MODULE_IMPORT_ORDER` list. New
  `soma topo <project_dir>` CLI prints the order one module per line
  (or `--format json`). New module `soma_dsl.resolver.topological`
  exposes `compute_topological_order(modules)` and
  `ModuleDependencyCycleError`. New error code
  `MODULE_DEPENDENCY_CYCLE` rejects cyclic `uses:` graphs at build
  time (error in every mode) instead of as a runtime `ImportError`.
  (M10; spec §4.14.)
- **`soma migrate-layout` subcommand.** One-shot legacy-to-flat
  migration: cleans `__soma_cache__/` and per-layer subdirectories
  (`presentation/`, `application/`, `domain/`, `infrastructure/`) from
  the project's build directory, runs a fresh `soma build`, prints a
  one-line summary. Idempotent. Defensive: refuses to operate on a
  build dir lacking recognisable s0ma artifacts. (M6b; ADR-007.)
- **`soma topo <project_dir>` subcommand.** Prints the project's
  topological module import order (one module per line, or
  `--format json`). Build-time `MODULE_DEPENDENCY_CYCLE` if the
  `uses:` graph is cyclic. (M10.)
- **`soma inspect <module_name>` shorthand.** The IR path is now
  resolved automatically by walking the project's build directory —
  the legacy `soma inspect <full_path>/<module>.soma.json` form
  continues to work for ad-hoc external IR inspection. Module-name
  resolution prefers the build manifest (M6b) as the source of
  truth; without a build, the resolver walks `source_roots` /
  `test_roots` for a matching `.soma` source and auto-transpiles to
  a temp dir. Unknown names produce a friendly error with an
  optional "Did you mean ...?" suggestion. (M16; spec §4.15.)
- **`soma inspect --all`.** One-line-per-module project survey
  (module name, layer, per-kind component counts, total component
  count). `--format json` emits the same survey as a list of
  objects for machine consumption. (M16.)
- **`bootstrap_files` recognition in `soma verify`.** Plain-Python
  files declared under `[tool.soma].bootstrap_files` get a distinct
  `BOOTSTRAP` status, hidden from default text output (the noise
  floor goes to zero on every project that declares its plain-Python
  entry points). `--verbose` and `--format json` show per-file rows.
  Undeclared `.py` files without an adjacent `.soma` source produce
  real `UNKNOWN` warnings with a remediation that names both fixes
  (declare under `bootstrap_files`, or transpile a `.soma` source).
  Path matching uses absolute resolved paths. (M11; spec §4.13.)
- **YAML `|` block-scalar form** for all string-valued metadata
  fields (`intent`, `expects`, `guarantees`, `schema`, `invariants`,
  `priors`, `on_anomaly`). Multi-line content is preserved through
  parser, IR, generated Python, and `soma inspect`. The smallest
  interior indent is the de-indenting baseline; relative
  sub-indentation is preserved. The folded form (`>`) and chomping
  indicators (`|+`/`|-`) are out of scope. Empty blocks error with
  a clear `PARSE_ERROR`. The Python emitter no longer collapses
  whitespace inside emitted metadata literals. Resolves
  feedback-5.5 M02/M03/M05. (M14; spec §2.1.1.)
- **New error codes** (all listed in `docs/spec_traceability.md`):
  `MODULE_NAME_STEM_MISMATCH` (M4), `AMBIGUOUS_TEST_TARGET` (M5),
  `TEST_VISIBILITY_VIOLATION` (M8), `CROSS_LAYER_DEPENDENCY` (M9),
  `MODULE_DEPENDENCY_CYCLE` (M10), `EMBEDDED_FILE_NOT_FOUND` (M12),
  `HELPER_PRIVATE_TO_MODULE` (M13), `CONSTANT_NAME_MISMATCH` (M17),
  `ATTRIBUTE_BUDGET_VIOLATION` (M18).
- **`TranspilerInternalError`** raised when emitted Python fails an
  `ast.parse()` round-trip. Wired into both the CLI primary write
  site and the on-disk cache writer; syntactic emission bugs no
  longer silently produce broken output. (M2; spec §2.1.2.)

### Changed

- **breaking-with-migration: single flat build layout.** Build output
  is now a single flat layout at `<project>.build_dir`. The legacy
  `__soma_cache__/` directory and per-layer subdirectories
  (`presentation/`, `application/`, `domain/`, `infrastructure/`) are
  no longer emitted by `soma build` or `soma transpile`. Every
  successful build emits a single `__init__.py` at the build root so
  the directory is a real Python package. The import idiom is
  `from <build_dir_basename> import <module>` and is printed at the
  end of every build. Hash-based incremental-rebuild bookkeeping
  moved to a hidden `.soma.cache/` directory rooted at the build's
  input/output anchor — never on `sys.path`, never importable, may
  be deleted at any time. `soma transpile dir/ -o out/` no longer
  mirrors `dir/`'s subdirectory structure into `out/`; every
  transpiled module lands at `out/<module>.py`. (M6a, M6b; spec
  §4.14; ADR-007.)
- **breaking-with-migration: `soma test` arguments simplified.** The
  `test_dir` positional is optional (defaults to every configured
  `test_root`). The `--source`, `--output-dir`, and
  greedy-positional `pytest_args` flags are removed; pytest args
  pass through after a literal `--` separator instead. Build output
  always lands in `project.build_dir` — `soma test` no longer
  accepts an output-dir override that would write `.py` files into
  the source/test trees. (M7; spec §4.15.)
- **Test modules no longer require `pytest` in `requires:`** unless
  the body references `pytest.<symbol>` directly (e.g. `pytest.raises`,
  `pytest.fixture`, `pytest.mark`). The runner is discovered from
  `[tool.soma].test_runner` in `pyproject.toml` (default `"pytest"`).
  Body-level use of `pytest.<symbol>` still requires `pytest` in
  `requires:` — the existing `VESTIGIAL_IMPORT` semantics are
  preserved. `[tool.soma].test_runner` accepts only `"pytest"` in
  this version; an unsupported value rejected at project-discovery
  time. (M15; spec §4.13.)
- **IR schema 1.1.0 → 1.2.0** (additive). `IRDocument.helpers` array
  added by M13; pre-M13 readers safely ignore the new field. No
  existing IR field semantics change.
- **Module-name as canonical cache key (M4 / `MODULE_NAME_STEM_MISMATCH`).**
  Cache keys, emitted `.py` / `.soma.json` / `.soma.map` filenames,
  and the import paths resolved by `uses:` now derive from
  `module.name` (the canonical IR identity), not the source file's
  stem. The intra-module validator enforces alignment at error
  severity in every strictness mode. New helper
  `soma_dsl.cache.extract_module_name`; the `BuildCache.lookup` /
  `store` / `invalidate` API gains an optional `module_name` keyword.
  (M4; spec §4.5.3; ADR-006.)

### Fixed

- **Metadata-field strings containing `"` no longer corrupt generated
  Python.** All metadata strings (`intent`, `expects`, `guarantees`,
  `schema`, `invariants`, `priors`, `on_anomaly`, axon `carries`,
  doc-* `format` / `output`, example `runs_in`) emit via `repr()`
  through the canonical `_py_str_literal()` helper, guaranteeing
  round-trip through `ast.parse()`. The legacy hand-rolled
  `_escape_string` / `_format_multiline_string` helpers are retired.
  (M2; feedback-5.5 lines 90–176.)
- **`HELPER_NAME_COLLISION` no longer false-positives** on `__init__`,
  `__aenter__`, `__aexit__`, and other class-body methods, or on
  inner functions inside test-block factories. Detection is now
  scope-aware (uses `ast.parse` instead of regex) and considers only
  `def` / `async def` declarations at the **top level** of a test
  body. The legacy regex helper `_extract_def_names` is preserved for
  `provides:` and abstract-interface checks where any matching `def`
  is the correct semantics. (M3; spec §4.8.3; feedback-6 CRIT-1.)
- **Release-mode `MISSING_TEST_COVERAGE` no longer false-positives on
  qualified test targets.** Both sides of the coverage check are now
  canonicalised to `module::component` via the shared
  `resolve_test_target_canonical` helper in
  `soma_dsl.resolver.namespaces` — qualified-vs-bare and
  intra-vs-cross-module behaviour cannot drift between consumers.
  Bare targets resolve intra-module first, then cross-module by
  unique match; ambiguous bare names produce the new
  `AMBIGUOUS_TEST_TARGET` error instead of silently mis-resolving.
  Replays of the fr3d M14 scenario (51 false positives) now pass
  clean. (M5; spec §4.8; feedback-5.5 lines 1099–1136.)
- **`soma test` performs project discovery and resolves cross-module
  references.** The runner discovers the project via `[tool.soma]`,
  builds every `source_root` and `test_root` to `project.build_dir`,
  and invokes pytest as a subprocess with `PYTHONPATH=<build_dir>`
  and `-o python_files=test_*.py *_tests.py`. The 13-milestone
  workaround of `PYTHONPATH=...__soma_cache__ pytest -o python_files=...`
  documented across feedback-6 (CRIT-3) is no longer required. Per-
  project `conftest.py` hacks that mocked the runtime bridge for
  test-time imports are obsolete. (M7; spec §4.15; feedback-6 CRIT-3.)
- **`soma test` correctly passes args after `--` to pytest.** The
  literal `--` separator is now consumed by `SomaCLI.run` before
  argparse runs, with the suffix forwarded to the pytest subprocess
  verbatim. Pre-M7, `soma test ... -- -o python_files='...'`
  greedy-consumed `-o` as the test parser's `--output-dir` short flag
  and produced a directory literally named `python_files=...` (the
  feedback-5.5 M01 foot-gun). (M7; feedback-5.5 M01.)
- **`CROSS_LAYER_DEPENDENCY` validation now applies cross-module.**
  Layer discipline previously held only intra-module — the validator
  did not check that a `uses:` entry's target module was at a layer
  reachable from the consuming module. Three real layer violations
  slipped through 13 milestones in the fr3d audit before this gap
  was closed. The reachability matrix lives in
  `soma_dsl.resolver.dependency._ALLOWED_TARGET_LAYERS`. Severity
  ladders: warning in migration/dev, error in strict and release.
  (M9; spec §4.0.2; feedback-5.5 lines 1157–1177.)
- **`soma verify` bootstrap-noise floor.** Declared bootstrap files
  no longer surface as `UNKNOWN`; they get a distinct `BOOTSTRAP`
  status and are hidden from default text output. (M11; spec §4.13.)

### Migration notes

Consumer projects on 0.11.0 take four actions to land on 0.12.0. See
[`docs/migration_guide.md`](docs/migration_guide.md) §"0.11.0 → 0.12.0"
for the full walkthrough.

1. **Add `[tool.soma]` to `pyproject.toml`.** At minimum `source_roots
   = ["src"]`; declare `bootstrap_files`, `test_runner`, and
   `[tool.soma.attribute_budgets]` if applicable. Without it, the CLI
   prints a one-line legacy-mode warning per invocation.
2. **Run `soma migrate-layout`.** One-shot, idempotent: cleans
   `__soma_cache__/` and per-layer subdirs, then runs a fresh build so
   the flat layout + `build.soma.json` manifest land. Update consumer
   imports from `from <layer>.<module>` to `from <build_dir_basename>
   import <module>`.
3. **Rename any mismatched-stem modules.** Any file whose stem differs
   from its declared `module <name>` errors with
   `MODULE_NAME_STEM_MISMATCH` in every mode. Either rename the source
   file or change the `module <name>` declaration.
4. **(Optional) Drop `pytest` from test `requires:`** when the body
   has no `pytest.<symbol>` reference. The runner is now discovered
   from `[tool.soma].test_runner`; the historic
   `requires: [pytest]`-just-to-silence-the-runner papercut is gone.
   Keep `pytest` in `requires:` when the body uses `pytest.raises`,
   `pytest.fixture`, etc.

### Breaking changes

- **Build output layout (single flat layout).** Pre-0.12 layer-prefixed
  imports (`from presentation.foo import bar`) stop working at the
  0.12 boundary. There is no migration ladder — the legacy
  `__soma_cache__/`-plus-layer-subdirs layout was the source of every
  silent stale-cache bug across feedback-5/5.5/6. **Path forward:**
  `soma migrate-layout` is one shot, idempotent, and safe to run on
  pre-0.12 trees. See [ADR-007](docs/adr/ADR-007-single-build-layout.md)
  for the rationale.
- **`soma test` argument shape.** `--source`, `--output-dir`, and
  greedy-positional `pytest_args` are removed; pytest args pass after
  `--`. Project paths come from `[tool.soma]`. Migration:
  `soma test tests/ --source src/ --output-dir tests/ pytest-args`
  becomes `soma test -- pytest-args`.
- **Module file naming.** Source filenames must equal their declared
  `module <name>`. `MODULE_NAME_STEM_MISMATCH` errors at check time
  in every mode (no migration ladder — the rule fires at error
  severity even in `migration` mode).

Everything else is additive: new declarations (`helper`), new visibility
level (`TEST`), new directives (`@file()`), new fields
(`declares_attributes:`), new commands (`soma topo`, `soma migrate-layout`,
`soma inspect <module>`, `soma inspect --all`), and new error codes.
Pre-0.12 `.soma` modules that pass `soma check --mode strict` on 0.11.0
parse unchanged on 0.12.0 with two adjustments: file-stem alignment
(M4) and dropping `__soma_cache__/`-aware build artifacts.

### Validation against consumer projects

Validated against `fr3d` and `kn0wthyself-website-2` on 2026-04-28
(M20). Every M1–M19c CLI flow ran end-to-end against both projects:
`soma migrate-layout` cleaned the legacy layout and emitted the M6a
flat layout with manifest; `soma build` produced the expected modules
plus `topological_import_order`; `soma topo` matched the manifest;
`soma verify` recognised declared bootstrap files. Six of the
workarounds documented in feedback-5 / feedback-5.5 / feedback-6 were
confirmed-eliminated (legacy-cache `norecursedirs`, per-layer
`__init__.py` shims, hand-maintained `MODULE_IMPORT_ORDER`, conftest
runtime-bridge mocks, post-hoc file-stem renames, manual CONSTANT
name dedup). Seven small DSL-side follow-ups were identified — the
most impactful is a false-positive `CONSTANT_NAME_MISMATCH` on
multi-line string bodies with column-0 lines (the validator's
`textwrap.dedent` mismatches the codegen's `_dedent_body` strategy).
None blocks the 0.12.0 release; all seven are tracked under
`plans/5-6_deviations.md` "M20 — DSL-side follow-up". The full
per-project results table, the workarounds-eliminated audit, and the
consumer-side action gaps now folded into the migration guide live in
[`plans/feedback_5-6/feedback_5-6_smoke_results.md`](plans/feedback_5-6/feedback_5-6_smoke_results.md).

### Deferred

- **Optional `doc-ref`-driven Common Errors table.** The 0.11.0
  documentation subsystem can derive the Common Errors table from the
  registered error codes. Out of scope for 0.12.0; tracked as a
  s0ma-aligned cleanup in `plans/5-6_deviations.md`.
- **Per-namespace "page selector" sub-key under
  `[tool.soma.attribute_budgets]`.** The implicit-from-graph
  interpretation of "what is a page composer?" (a module not
  referenced by any other module's `uses:`) is the simplest viable
  rule that ships. If M20 surfaces a real-world topology this rule
  gets wrong, the right follow-up is an explicit per-namespace
  selector — not baking topology into the validator.
- **Renumbering spec §4.4a (helper) to a clean 4.5.** The letter
  suffix is unusual but inbound references are stable; renumbering
  is deferred to a future cleanup pass that reshuffles §4 entirely.

## [0.11.0] — 2026-04-25

The documentation-subsystem release. Three new declaration types — `doc-ref`, `doc-guide`, and `example` — bring authored documentation under the same grammar-level enforcement as nerves, cells, and ganglia. A new CI gate (`docs check-drift`) makes it structurally impossible for a committed document to drift from the code it describes.

**Highlights:**

- Three new declaration types: `doc-ref` (registry projection), `doc-guide`
  (narrative with `{{...}}` references and `asserts:`), `example`
  (executable demonstration).
- Six-layer validation pipeline (grammar → template parsing → reference
  resolution → assert evaluation → content fingerprinting → example
  execution).
- Deterministic Markdown / HTML / JSON renderers with byte-equal
  reproducibility and an eight-field front-matter contract.
- New CLI subcommands: `docs render`, `docs verify`, `docs check-drift`,
  `examples run`.
- New universal rules R-28 through R-32 in DSL spec §7.1.
- Spec file renamed: `s0ma-dsl-spec-v0.10.1.md` → `s0ma-dsl-spec-v0.11.0.md`.
  The 0.10.1 path remains as a one-line pointer for one release.
- Migration is incremental (Option B per design §14.7) — see
  [`docs/migration_guide.md`](docs/migration_guide.md) for the per-document
  status table.

**Migration notes:** This release is **fully additive**. Every 0.10.1 `.soma` module parses unchanged; the IR schema bump (1.0.0 → 1.1.0) is additive and existing consumers safely ignore the new sections. Projects adopting the new declarations should follow the per-document migration checklist in `docs/migration_guide.md`. The spec rename leaves a one-release pointer at the old path; update inbound links before the 0.12.0 release.

**Breaking changes:** None.

### Added

- DSL spec §4.12 (Documentation Declarations) covering `doc-ref`,
  `doc-guide`, and `example` syntax, the six validation layers, content
  hashing and the drift check, the strictness severity matrix for the
  doc subsystem, and the documentation type taxonomy.
- DSL spec §4.10.1 (Namespace Model) updated to enumerate doc declarations
  as registry-namespace consumers — the same total-observability rule that
  already governs `observes:` and `tests:` now governs `covers:`,
  `asserts:`, `examples:`, `demonstrates:`, and prose `{{...}}` tokens.
- Universal rules R-28 (no raw code blocks in `doc-guide` bodies),
  R-29 (every named-component claim is a `{{...}}` or in `asserts:`),
  R-30 (`example.demonstrates:` is non-empty), R-31 (no prose in `doc-ref`
  beyond `intent` / section `title`), R-32 (update affected docs and
  examples when modifying a component) added to DSL spec §7.1.
- New transitional reference document
  [`docs/references/documentation_subsystem.md`](docs/references/documentation_subsystem.md):
  user-facing guide to the new declaration types, when to use which,
  rendering, drift detection, migration status, and the resolved design
  decisions from design overview §14. Self-hosting is tracked in
  `plans/TODO.md` as a post-v1 follow-up.
- Migration guide gains a "Migrating Hand-Authored Docs to the
  Documentation Subsystem" section with the per-document migration
  status table, the per-document migration checklist, and the
  deprecation policy.
- Spec traceability matrix extended to span R-01 through R-32 and to
  list every documentation-subsystem error code with its implementation
  module and milestone.
- CLI subcommands `docs render`, `docs verify`, `docs check-drift`,
  `examples run` (design §11.10, implementation plan M7).
  - New module `src/soma_dsl/cli/docs_commands.py` houses the `docs`
    handlers; `examples_commands.py` hosts the `examples run`
    dispatcher. Both wire through `SomaCLI.run()` and follow the
    PRD §2.8.2 exit-code contract (0 success, 1 validation error,
    2 usage error, 3 internal error).
  - `docs render` parses, validates, and renders every `doc-ref` /
    `doc-guide` to its declared `output:` path, reusing the M6
    `render_module_docs` pipeline. `docs verify` runs validation
    layers 1–5 without rendering. `docs check-drift` re-renders into
    memory and byte-compares against on-disk files, surfacing
    `DRIFT_DETECTED` diagnostics with unified-diff context.
  - `examples run` discovers every `example` declaration, registers
    them in an isolated `ComponentRegistry`, and delegates to
    `s0ma.examples.ExampleRunner`. When the runner is unavailable
    (environments without s0ma-core M6), the command exits 3 with
    an actionable message rather than faking a result (plan §10).
- Strictness-mode integration for documentation validation layers
  (design §11.11):
  - New error codes: `DRIFT_DETECTED`, `EMPTY_DOC_FILTER`,
    `MISSING_PUBLIC_DOC_REF`, `MISSING_EMBEDDED_EXAMPLE`. Drift and
    empty-filter codes ladder warning → error from migration/dev to
    strict/release; the two coverage codes are release-only.
  - `DocReferenceResolver` materialises every `covers:` filter and
    emits `EMPTY_DOC_FILTER` when the match set is empty (plan M7
    subtask 6, design §8.3). New shared helpers
    `materialize_filter` / `predicate_matches` keep resolver and
    renderer semantics aligned.
  - New `check_release_doc_coverage` pass in
    `soma_dsl.semantic.doc_validator` runs project-wide: every
    PUBLIC nerve must be covered by at least one `doc-ref`, and
    every registered example must be embedded in at least one
    `doc-guide`. Emits `MISSING_PUBLIC_DOC_REF` and
    `MISSING_EMBEDDED_EXAMPLE` (release-only).
  - `DocReferenceResolver`, `DocValidator.validate`, and
    `validate_docs` now thread an optional `mode: StrictnessMode`,
    defaulting to `DEV` so existing callers keep pre-M7 behaviour.
- Cache-aware re-rendering of doc outputs (plan M7 subtask 7,
  deferred from M6):
  - `BuildCache` tracks rendered `.md` / `.html` / `.json` outputs
    alongside `.py` / `.soma.json` / `.soma.map`. New
    `RenderedDocEntry` carries the cached body bytes; the cache key
    combines source content, the doc declaration's transitive
    `DocHashIndex`, and a digest of the project-wide doc-index
    entity set so covered cross-module changes miss the cache.
  - `_transpile_single_file` no longer short-circuits the cache for
    doc-bearing builds — re-running `soma build` against an
    unchanged tree hits the cache for both Python and rendered
    artefacts. Editing a covered nerve's `intent` invalidates every
    doc that references it.
- Retired the dangling `UNSUPPORTED_TEMPLATE_CONSTRUCT` severity-matrix
  entry (plan M7 subtask 5, option b). The grammar already raises
  `TEMPLATE_SYNTAX_ERROR` for every construct §8.2 forbids, so a
  parallel code with no emitter served no purpose.

- Deterministic rendering engine for Markdown / HTML / JSON doc outputs
  with content-hash front-matter (design §§8.5, 11.6, implementation
  plan M6).
  - New subpackage `src/soma_dsl/codegen/doc_emitter/` exposing
    `compute_doc_hashes`, `DocHashIndex`, `render_module_docs`,
    `RenderedOutput`, plus per-format renderers
    (`render_doc_ref_markdown`, `render_doc_guide_markdown`,
    `render_doc_ref_json`, `render_doc_guide_json`,
    `render_doc_ref_html`, `render_doc_guide_html`) and the shared
    `frontmatter` helpers.
  - `compute_doc_hashes()` synthesises a `RegistrySnapshot` from
    parsed AST modules and calls
    `s0ma.hashing.content_hash` for every `doc-ref` /
    `doc-guide` declaration in the project. The transitive digest
    walks `covers:` filters, resolved component metadata, and example
    bodies — exactly the registry state each doc depends on, no more.
  - `PythonEmitter` now accepts a project-wide `doc_hashes` map and
    bakes the transitive content hash into the emitted
    `register_doc_ref` / `register_doc_guide` calls (replacing the
    M5 `content_hash=""` placeholder). `emit_python()` carries the
    same parameter so library callers opt in by passing a hash index.
  - `soma build` and `soma check` now compute hashes once per
    invocation, render every doc declaration to its declared
    `output:` path, and write Markdown / HTML / JSON files alongside
    the existing `.py` / `.soma.json` / `.soma.map` artifacts. The
    runtime registry receives the same content hash the renderers
    committed to disk, so a future `docs check-drift` (M7) can
    compare them without ambiguity.
  - Doc-* registration source spans are normalised to the source
    file's basename (rather than its absolute path) so doc hashes
    are byte-stable across machines, CI runs, and developer
    checkouts. Diagnostics still surface the absolute path —
    only what gets *baked into a stored registration* is
    normalised.
  - Build-cache lookups skip when doc rendering is in play; the
    cache currently only tracks Python / IR / source-map artifacts,
    so a cache hit would silently keep stale rendered docs. M7 will
    extend the cache to cover rendered outputs.
- Hand-rolled deterministic Markdown / HTML / JSON renderers (no
  external `markdown-it-py` dependency for v1) — every renderer is
  a pure function of input AST + project index + content hash, with
  byte-equal reproducibility tests pinning the contract.
- Front-matter contract for rendered docs: YAML for Markdown
  (`---`-delimited), `<meta name="soma:…">` tags for HTML, and a
  top-level `_hash` + `_meta` block for JSON. The same eight fields
  (`soma_kind`, `name`, `module`, `format`, `intent`,
  `transpiler_version`, `schema_version`, `content_hash`) appear in
  every rendered doc in declared order so downstream tools can rely
  on the shape.
- Fixture `tests/fixtures/valid/docs/render_formats/` exercises every
  doc declaration format end-to-end. Golden snapshots checked in
  under `tests/fixtures/golden/docs/`.
- Test coverage: `test_doc_emitter_markdown.py` (11 tests covering
  front-matter, body substitution, byte-equal reproducibility, and
  content-hash stability under unreferenced/referenced changes);
  `test_doc_emitter_json.py` (4 tests on top-level shape, sort-key
  determinism, and reproducibility); `test_doc_emitter_html.py`
  (4 tests on document skeleton, namespaced meta tags, heading
  translation, and reproducibility); `test_doc_emitter_pipeline.py`
  (3 tests on end-to-end build, hash agreement between rendered
  files and emitted register calls, and CLI determinism); plus
  `test_doc_emitter_golden.py` (4 byte-for-byte snapshot tests).

### Deferred

- Cache-aware re-rendering of doc outputs is deferred to **M7** (see
  M6 Handoff Notes in
  [`plans/documentation_subsystem_implementation_plan.md`](plans/documentation_subsystem_implementation_plan.md)
  and M7 subtask 7). The build cache currently bypasses itself when
  doc declarations exist rather than tracking rendered outputs
  alongside `.py` / `.soma.json` / `.soma.map`. M7's `docs check-drift`
  work is the right home for the cache extension because it
  introduces the wider notion of "doc artifact identity".
- `markdown-it-py` opt-in for richer HTML rendering is deferred to a
  future release with no fixed milestone. v1 ships a hand-rolled
  Markdown→HTML translator that covers the narrow subset the doc-*
  renderers emit; richer output (tables, link rewriting, syntax
  highlighting, footnotes) is tracked in
  [`plans/TODO.md`](plans/TODO.md) under "doc-subsystem — richer
  Markdown/HTML rendering (deferred from M6)" and resolves design
  Open Question §14.1 as **hand-rolled for v1**.

### Changed

- `PythonEmitter` now takes an optional `doc_hashes: dict[(kind, name), str]`
  parameter; existing callers see no behavioural change because the
  default `None` preserves the M5 placeholder emission. The CLI build
  pipeline always passes a populated index when doc declarations are
  present.
- Doc-* registration source spans now normalise to source-file
  basenames. This is a behaviour change in the runtime registration
  payload: the runtime registry stores `source_span.file =
  "<basename>.soma"` rather than the transpile-time absolute path.
  Diagnostics on the transpile side are unaffected.

- Emitter, IR, source-map, and runtime-bridge support for doc declarations
  (design §§11.6–11.9, implementation plan M5).
  - `PythonEmitter` now emits `register_doc_ref()`, `register_doc_guide()`,
    and `register_example()` calls for every `doc-ref`, `doc-guide`, and
    `example` declaration in source order.
  - Module-level marker tuples `__soma_doc_ref__`, `__soma_doc_guide__`,
    and `__soma_example__` are emitted alongside the registration calls
    so the s0ma framework's import hook can verify the generated module
    actually registered every name it claims (`s0ma.import_hook`).
  - New `runtime_bridge` adapters `register_doc_ref`, `register_doc_guide`,
    and `register_example` in `soma_dsl.runtime_bridge.registration`
    coerce DSL-side primitive payloads into the framework's typed
    `EntityRef` / `FilterExpr` / `Section` / `AssertExpr` / `SourceSpan`
    records before delegating to the s0ma registry. All three adapters
    are idempotent so re-imports during development do not raise.
  - IR schema gains `IRDocRef`, `IRDocGuide`, `IRExample`, plus the
    structured supporting nodes `IREntityRef`, `IRFilterExpr`,
    `IRComparisonPredicate`, `IRBooleanPredicate`, `IRSection`,
    `IRAssertComparison`, and `IRAssertBoolean`. `IRDocument` adds
    `doc_refs`, `doc_guides`, and `examples` top-level sections.
  - **`SCHEMA_VERSION` bumped to `1.1.0`** — additive, no breaking
    changes for older consumers (extra keys are safely ignored).
  - IR serialisation walks the structured M2/M3 AST fields exclusively;
    the `raw` field is debug-only per the M2 handoff and is excluded
    from the canonical IR so whitespace in source does not change the
    hash later milestones will compute over the IR.
  - Field-value normalisation in IR mirrors `_enum_to_str` from
    `doc_resolver.py` so the IR-derived view of a field agrees with
    what the doc-resolver validated against.
  - Source maps cover doc declarations: `DeclarationMapping.type` adds
    `doc-ref`, `doc-guide`, and `example` discriminators, and the
    generator finds doc declarations via the same comment-marker pattern
    the emitter writes (`# Doc-ref: …`, `# Doc-guide: …`, `# Example: …`).
  - `DocValidator` is now wired into the `soma check` and `soma build`
    CLI pipelines: M4 reference / assert diagnostics block emission
    when any module declares a `doc-ref`, `doc-guide`, or `example`.
  - `ProjectIndex.from_snapshot(snapshot)` builds the resolver's index
    directly from a populated `s0ma.RegistrySnapshot`. The AST-based
    `build_project_index()` path remains the transpiler's primary
    entry point; this companion enables runtime-side integration tests
    to validate doc references against the live registry.
  - `register_doc_*` calls emit `content_hash=""` placeholders for now.
    Real transitive content-hash wiring is deferred to **M6** per the
    plan (s0ma-core M7 must land first).

### Changed

- IR schema version bumped from `1.0.0` to `1.1.0` (additive; consumers
  that read only the existing keys see no behavioural change). Golden
  fixture assertions updated accordingly.

### Deferred

- `covered_<type>` template identifiers (design §6.1 sketch). v1 commits
  to kind-based filters only — `for n in nerves where ...` rather than
  `for n in covered_nerves`. Tracked in `plans/TODO.md`.
- Transitive content-hash computation for `register_doc_*` calls. M5
  emits placeholder `content_hash=""`; M6 (rendering + content hash) wires
  the real hash once s0ma-core M7's content-hash infrastructure lands.

- Reference resolver and assert evaluator for doc declarations
  (design §§8.3, 8.4, implementation plan M4).
  - New module `src/soma_dsl/resolver/doc_resolver.py` exposing
    `ProjectIndex`, `build_project_index(modules)`, and
    `DocReferenceResolver`. The resolver walks every `covers`,
    `sections`, `examples`, `demonstrates`, and `{{...}}` reference
    on `DocRefDecl` / `DocGuideDecl` / `ExampleDecl` and validates
    entity existence, kind correctness, field-path reachability,
    and example registration against a project-level index built
    from parsed `SomaModule` ASTs.
  - New module `src/soma_dsl/resolver/assert_evaluator.py` exposing
    `AssertEvaluator` and `AssertResult`. Walks the narrow
    `AssertComparison | AssertBoolean` AST produced by M2 and
    evaluates each assert against the project index; emits
    `ASSERT_FAILED` diagnostics with expected-vs-actual context
    when an assert contradicts the self-model, and
    `ASSERT_UNEVALUABLE` when a referenced field cannot be read.
    Short-circuits `and` / `or` and handles `not`.
  - New module `src/soma_dsl/semantic/doc_validator.py` exposing
    `DocValidator` + `validate_docs(modules)` — a project-level
    orchestrator that fans out the resolver and evaluator across
    every doc declaration in every module. Returns diagnostics in
    deterministic module-name-then-source-line order.
  - New error codes registered in `SEVERITY_MATRIX`
    (always `error` in every strictness mode, per §8.3's load-bearing
    guarantee): `UNRESOLVED_REFERENCE`, `ENTITY_KIND_MISMATCH`,
    `FIELD_NOT_FOUND`, `UNREGISTERED_EXAMPLE`, `ASSERT_FAILED`,
    `ASSERT_UNEVALUABLE`.
  - Resolver diagnostics include a "did you mean ...?" suggestion
    via a deterministic Levenshtein-based search over the known
    names for the requested kind, so coding agents can fix
    typos without guessing.
  - Test coverage: `tests/test_doc_resolver.py` (21 new tests)
    spans positive end-to-end cases, dangling references, kind
    mismatches, field-not-found in both prose and doc-ref sections,
    filter-predicate field validation, assert truth/falsity/`in`/
    boolean/`not`, unevaluable asserts, and deterministic error
    ordering across modules.

- Prose body parser for `doc-guide` declarations (design §6.2,
  implementation plan M3).
  - New module `src/soma_dsl/parser/prose_parser.py` exposing
    `parse_prose(body, filename, body_start_line, mode)` which returns
    a tuple `(tokens, diagnostics)`.
  - New AST node types `TextChunk`, `ReferenceToken`,
    `ExampleEmbedToken` and the `ProseToken` union. `DocGuideDecl`
    gains a `prose_tokens: tuple[ProseToken, ...]` field populated at
    parse time; the existing byte-exact `prose_body: str` is preserved
    alongside and the round-trip invariant
    `"".join(t.raw for t in prose_tokens) == prose_body` holds for
    every successfully parsed guide.
  - `{{entity::name[.field]}}` tokens inside prose are handed to the
    M2 `_parse_entity_ref` helper — there is no second entity-ref
    parser. The `{{example::X}}` form is distinguished from other
    references by `EntityRefAst.kind == "example"` and wrapped in
    `ExampleEmbedToken` so downstream renderers can inline example
    bodies as fenced code blocks.
  - Raw fenced code blocks (triple-backtick or triple-tilde) are
    detected and emit the new `PROSE_RAW_CODE_BLOCK` diagnostic —
    error in every strictness mode. The fence content stays in the
    token stream so round-trip holds even when the diagnostic fires.
    Nested `{{...}}` and unclosed references raise
    `TEMPLATE_SYNTAX_ERROR` with column-accurate source spans.
  - Heuristic inline-code warning `POSSIBLE_UNRESOLVED_REFERENCE`
    fires for single-backtick spans containing identifier-shaped
    content that is not wrapped in `{{...}}`. Severity is `warning`
    in `migration` / `dev` / `strict` and promotes to `error` in
    `release`.
  - `_build_doc_guide` now returns `(DocGuideDecl, list[diagnostics])`
    and both `parse_soma` and `parse_soma_with_warnings` collect the
    prose diagnostics into the same `body_errors` stream used for
    body-validation findings — hard errors raise and warnings surface
    through the existing channel.
  - Tests: `tests/test_prose_parser.py` (35 cases) covers plain text,
    single / multiple / zero references across all entity kinds,
    example embeds, the round-trip invariant, fenced-code detection
    in every mode, the inline-code heuristic's severity matrix,
    malformed references (unclosed, empty, nested, missing `::`), and
    integration through `parse_soma` on the minimal doc-guide fixture.
  - New error codes registered in `SEVERITY_MATRIX`:
    `PROSE_RAW_CODE_BLOCK` (error in every mode) and
    `POSSIBLE_UNRESOLVED_REFERENCE` (warning → error in release).

- Template-expression and assert-expression sub-grammars for the
  documentation subsystem (design §8.2, implementation plan M2).
  - Template grammar supports entity references
    (`nerve::X`, `cell::Y.field`), filter expressions
    (`nerves where visibility == PUBLIC and kind in [SERVICE, FUNCTION]`),
    ordering (`ordered_by <fields>`), grouping (`group_by <field>`), and
    iteration (`for <var> in <filter_expr>`) in doc-ref `sections:`.
  - Assert grammar is deliberately narrower: entity field access,
    `==` / `!=` / `in`, and boolean composition (`and`, `or`, `not`).
    Iteration, ordering, and grouping are rejected inside `asserts:`.
  - Structured AST nodes replace the M1 placeholders: `EntityRefAst`
    carries `(kind, name, field_path)`; `FilterExprAst` carries
    `(kind, predicate, ordered_by, group_by)`; `SectionAst` is a
    discriminated union of `field_name` and `IterationAst`; asserts are
    `AssertComparison | AssertBoolean` trees. `ComparisonPredicate` and
    `BooleanPredicate` back the template-level predicate trees.
  - Five new element-level parse helpers in `soma_parser.py`
    (`_parse_entity_ref`, `_parse_filter_expr`, `_parse_section_entry`,
    `_parse_assert_pred`, and transformer carriers). The outer
    `[a, b, c]` list shape is still split by `_split_bracketed_list`;
    each element is parsed individually by the matching Lark rule,
    because LALR(1) cannot disambiguate list commas from the
    `ordered_by <a>, <b>` tail inside `filter_expr`.
  - New error codes `TEMPLATE_SYNTAX_ERROR`, `ASSERT_SYNTAX_ERROR`,
    and `UNSUPPORTED_TEMPLATE_CONSTRUCT`, all `error` in every
    strictness mode (structural rules never demote).
  - Tests: `tests/test_template_expressions.py` and
    `tests/test_assert_expressions.py` cover positive cases (all design
    §8.2 constructs), rejection of arbitrary Python / arithmetic /
    string concatenation / unknown kinds / single-`=` typos, and
    diagnostic-field correctness. `test_doc_grammar.py` updated to
    assert on the new structured shapes.
  - Fixture update: `minimal_doc_ref.soma` now uses `==` (per design
    §8.2) rather than the M1-placeholder single `=`.

- Grammar + AST + preprocessor support for `doc-ref`, `doc-guide`, and
  `example` declarations — the three new top-level declaration types
  introduced by the documentation subsystem (design §6, implementation
  plan M1).
  - New AST nodes: `DocRefDecl`, `DocGuideDecl`, `ExampleDecl`, and
    placeholder nodes `EntityRefAst`, `FilterExprAst`, `SectionAst`
    (to be fleshed out by the M2 template- and assert-expression
    grammars).
  - New `DeclarationType` enum members: `DOC_REF`, `DOC_GUIDE`, `EXAMPLE`.
  - `SomaModule` gains `doc_refs`, `doc_guides`, and `examples` tuples;
    its `all_declarations` property now includes them in source order.
  - Preprocessor recognizes `doc-ref NAME`, `doc-guide NAME`, and
    `example NAME` headers, enforces per-declaration mandatory fields at
    parse time, rejects doc-ref declarations that carry a `---` body
    (new error code `PARSE_DOC_REF_BODY_PROHIBITED`), and requires the
    `---` + body pair on doc-guide and example.
  - `validate_example_body` runs the prohibited-construct check
    (`exec`/`eval`/`__import__`/`importlib.import_module`/`setattr`) on
    example bodies without imposing the single-top-level-construct or
    bare-import restrictions that apply to nerves.
  - Fixtures: `tests/fixtures/valid/docs/minimal_doc_ref.soma`,
    `minimal_doc_guide.soma`, `minimal_example.soma`; invalid fixtures
    for missing fields, prohibited doc-ref body, missing doc-guide body,
    and example prohibited constructs.
  - Tests: `tests/test_doc_grammar.py` covers all M1 acceptance criteria.

### Deferred to later milestones

- Prose-body tokenization and `{{...}}` extraction (M3).
- Project-level reference resolution and assert evaluation (M4).
- Emitter, IR, runtime-bridge, rendering, CLI, drift detection,
  strictness integration (M5–M7).
- Documentation, migration path, rulebook rules R-28..R-32 (M8).

### Deferred past 0.11.0

- Self-hosting `docs/references/documentation_subsystem.md` as a
  `doc-guide`. Tracked in `plans/TODO.md` as the canonical post-v1
  follow-up — closes the loop where the documentation system documents
  itself. v1 ships it hand-authored under P7 to avoid a bootstrapping
  cycle.
- Per-document migrations of the existing hand-authored docs
  (`docs/s0ma_user_guide_condensed.md`, `docs/s0ma_user_guide.md`,
  `docs/reference/dsl_patterns_guide.md`, `docs/s0ma-dsl_quick_reference.md`).
  Each migrates on its next substantive update — see
  [`docs/migration_guide.md`](docs/migration_guide.md) for the per-doc
  status table and `plans/TODO.md` for the tracked items.
- Richer Markdown / HTML rendering (GFM tables, syntax highlighting,
  link rewriting, footnotes). v1 ships hand-rolled deterministic
  renderers covering only the subset the doc emitter actually emits.
  Tracked in `plans/TODO.md`.
- `covered_<type>` template identifiers (design overview §6.1 sketch).
  v1 commits to kind-based filters only — `for n in nerves where ...`
  rather than `for n in covered_nerves`. Tracked in `plans/TODO.md`.

### Removed (one-release pointer files)

- `docs/s0ma-dsl-spec-v0.10.1.md` is replaced with a one-line pointer
  to the renamed `docs/s0ma-dsl-spec-v0.11.0.md`. The pointer file is
  scheduled for deletion in the release after 0.11.0 — update inbound
  links before then.
