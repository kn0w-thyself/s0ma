# Coding Agent Handbook — s0ma DSL Transpiler

**Audience:** Coding agents working on the s0ma DSL transpiler
**References:** PRD §1.13 (implementation guardrails), DSL Spec §7 (coding agent rulebook)

---

## 1. Orientation

You are working on the **s0ma DSL transpiler** — a tool that compiles `.s0ma` files into Python + IR + source maps. The transpiler is itself a s0ma project: every module uses `@component` or `@internal` decorators.

**Authority hierarchy:** DSL Spec > PRD > Implementation Plan > This handbook. When documents disagree, the higher-authority source wins (PRD §1.13, guardrail #1).

### 1.1 Architecture: project discovery first

As of 0.12.0 (Milestone 1, feedback 5–6 plan), every CLI subcommand resolves a `S0maProject` before dispatching. The project is rooted at the consumer's `pyproject.toml`, configured via a `[tool.s0ma]` table, and produced by `S0maProject.discover(start)` (which walks upward from `--project-root` or `Path.cwd()`). The resolved project carries `source_roots`, `test_roots`, `build_dir`, and `bootstrap_files`, all as absolute `pathlib.Path` values. When discovery fails, the CLI falls back to a synthetic project (`S0maProject.synthetic_fallback`) and emits a one-line warning; the synthetic project is flagged with `synthetic=True` so feature code can short-circuit project-aware behaviour.

**Disjoint discovery roots (G2, feedback 5–6 cleanup).** `_from_tool_s0ma` calls `_detect_overlapping_roots(source_roots, test_roots)` after both lists are resolved to absolute paths. The detector returns `(root_a, root_b, kind)` triples for every pair where one root is a subpath of the other or both resolve to the same path; `kind` is `source-source`, `test-test`, or `source-test`. Any non-empty result raises `ValueError` with a message starting `OVERLAPPING_DISCOVERY_ROOTS:` that names every offending pair plus the two clean-config remediation options (move tests outside the source root, or narrow `source_roots` to disjoint layer subdirectories). The error is registered in `SEVERITY_MATRIX` as `error` in every strictness mode — load-time configuration ambiguity is never softened. Implication for transpiler contributors: anything that synthesises a `S0maProject` from raw `[tool.s0ma]` data (e.g. test fixtures) must keep the lists disjoint or supply pre-resolved overlap-free tuples; reaching for `S0maProject(...)` directly bypasses the detector by design (only synthesised-from-disk projects route through `_from_tool_s0ma`).

**Importable build_dir basename (G3, feedback 5–6 cleanup).** `_from_tool_s0ma` derives the default `build_dir` value via `_default_build_dir(project_name)`, which sanitizes every non-word character (`re.sub(r"\W", "_", project_name)`) before appending `_build`. The contract is M6a-mandated: `s0ma build` writes `<build_dir>/<module>.py` and the runtime bridge imports via `from <build_dir_basename> import <module>`, so the basename must be a valid Python identifier. Recoverable shapes (hyphens, dots, spaces, exclamation marks — anything `\W` matches) sanitize automatically; irrecoverable shapes (project names that start with a digit, or sanitize to the empty string) raise `ValueError` with a message starting `INVALID_PROJECT_NAME_FOR_BUILD_DIR:` instructing the author to set `[tool.s0ma].build_dir` explicitly. Explicit `build_dir` values are validated the same way: the directory's last path component (`Path(build_dir).name`) must be a valid Python identifier — `out/foo_bar` is fine; `out/foo-bar` is rejected because `foo-bar` is not an identifier. The error is registered in `SEVERITY_MATRIX` as `error` in every strictness mode. Implication for transpiler contributors: anything that constructs a `S0maProject` from a raw project-name (e.g. `synthetic_fallback`) bypasses the sanitizer by design — only the `[tool.s0ma]`-routed path gets G3 validation. New CLI features that read `project.build_dir.name` for import-statement codegen can rely on the basename being a valid identifier; defensive checks at the use-site are redundant.

**Implication for transpiler contributors:** new CLI features that need to know *where source lives* or *where build output goes* must read those values from `args.s0ma_project`, not from per-command flags reconstructed from arguments. Per-command flags remain valid as overrides for one-off invocations, but the project model is the canonical source of truth. See `src/s0ma_dsl/project.py` for the dataclass and ADR-005 for the rationale.

### 1.2 Output artifacts

As of 0.12.0 (Milestone 6a, feedback 5–6 plan), `s0ma build` emits a **single flat layout** at `<project>.build_dir`. The build directory contains:

- one auto-emitted `__init__.py` (idempotent; one-line generated-marker docstring) so the directory is a real Python package and cross-module imports work via `sys.path` insertion alone;
- one `<module>.py` / `<module>.s0ma.json` / `<module>.s0ma.map` triple per `.s0ma` source, named by the canonical module identity (ADR-006);
- *nothing else.* No layer subdirectories. No `__s0ma_cache__/`.

Hash-based incremental-rebuild bookkeeping lives under `<anchor>/.s0ma.cache/` (hidden, leading dot keeps Python's importer out of it; `<anchor>` is the build's input/output dir). The cache is implementation detail and may be deleted at any time. **Do not** import from it; it is never on `sys.path` by design.

**Implication for transpiler contributors:** when adding a code path that writes a transpiled artifact, write it to `output_dir / f"{module.name}.py"` (or the matching `.s0ma.json` / `.s0ma.map`). When adding a code path that needs to *find* an artifact for inspection, prefer the build directory; fall back to `.s0ma.cache/` only for IR/source-map lookup. Never reintroduce `__s0ma_cache__/`. Never reintroduce per-layer subdirectory writes. The `_emit_build_init` helper in `src/s0ma_dsl/cli/main.py` is the single home for the auto-emitted `__init__.py`; reuse it. See ADR-007 for the full rationale and the §4.14 "Build Output" section of the spec for the user-facing contract.

**Build manifest (M6b, extended in M10).** Every successful build emits a `build.s0ma.json` manifest at the build root. The manifest is the canonical "what's in this build" answer — the runtime helpers read it (`s0ma.bootstrap.bootstrap_imports` for M10's topological-order-aware path — it lives in s0ma-core since 0.16.x so deployed apps need no authoring package at runtime; `s0ma_dsl.runtime_bridge.registration.import_modules_from_manifest` for the M6b alphabetical path retained for back-compat) instead of walking the filesystem, and `s0ma migrate-layout` consults it when reporting how many modules were emitted post-migration. Filesystem traversal as a fallback is deliberately not supported: a missing or schema-mismatched manifest raises `ManifestSchemaError` with a remediation pointing at `s0ma build` or `s0ma migrate-layout`.

The manifest-emission codepath:

1. The build pipeline transpiles every target file under `_transpile_single_file` (which writes `.py`, `.s0ma.json`, `.s0ma.map` to disk).
2. After every successful build, `_cmd_build` walks the just-emitted `(source_path, module)` pairs and constructs one `ModuleManifestEntry` per module via `_collect_manifest_entry`. Hashes are computed by reading the freshly-written `.py` and the `.s0ma` source from disk; this keeps the per-file pipeline decoupled from manifest construction (no signature change to `_transpile_single_file`).
3. `_cmd_build` also calls `s0ma_dsl.resolver.compute_topological_order(target_modules_dict)` over the parsed `S0maModule` map to compute the dependency-first import order from every module's `uses:` edges. A cycle raises `ModuleDependencyCycleError`, which `_cmd_build` surfaces as the `MODULE_DEPENDENCY_CYCLE` diagnostic and exits non-zero before any manifest is written.
4. `_emit_build_manifest` constructs the top-level `BuildManifest` (filling `transpiler_version` from `s0ma_dsl.__version__`, `built_at` from a UTC ISO 8601 timestamp, `topological_import_order` from the M10 step above) and writes it to `<build_dir>/build.s0ma.json` via `s0ma_dsl.codegen.build_manifest.emit_manifest`.
5. The manifest's `modules` list is sorted by name (the inventory). The `topological_import_order` field is the import-time directive (M10). M12 may add `external_content_files`. All extensions are *additive* under the same `s0ma-build-manifest@1` schema string — readers branch on optional fields, not on the version.

**Topological sort algorithm (M10).** `src/s0ma_dsl/resolver/topological.py:compute_topological_order` runs Kahn's algorithm with deterministic alphabetical tie-breaking over the project's `uses:` graph. Edges are oriented so that `in_degree[X]` counts how many modules `X` depends on; leaf-dependency modules (in-degree 0) emit first, satisfying `importlib`'s requirement to import dependencies before consumers. When the queue is sorted alphabetically on each iteration, the output is reproducible across runs of the same source. A cycle is detected by checking that the result list has the same length as the input map; surviving non-zero-in-degree nodes name the cycle in the raised `ModuleDependencyCycleError`. The four-phase resolver (`resolver/dependency.py`) also runs DFS-based cycle detection during Phase 1 (`CIRCULAR_DEPENDENCY`); both surfaces are intentional — the resolver's catches cycles in normal `s0ma build` flow, while `MODULE_DEPENDENCY_CYCLE` is the topological-sort-path's defensive backstop and the only signal `s0ma topo` raises when invoked standalone.

**Implication for transpiler contributors:** when adding a new artifact to the build output, extend the manifest schema additively under `@1` (add an optional field; readers can branch on its presence). Bump to `@2` only for *breaking* schema changes (renamed/removed fields). When adding a new build CLI subcommand, plug into the existing manifest-emission point rather than re-implementing it; the manifest module (`s0ma_dsl.codegen.build_manifest`) exposes `build_manifest()`, `emit_manifest()`, `load_manifest()`, and `compute_file_hash()` for reuse. When adding a code path that needs the topological order at *runtime*, prefer `s0ma.bootstrap.bootstrap_imports` (s0ma-core; the `s0ma_dsl.runtime` re-export is deprecated); do not re-derive the order by walking the filesystem or re-parsing `.s0ma` sources.

**`s0ma migrate-layout` (M6b).** The migration command lives in `src/s0ma_dsl/cli/main.py:_cmd_migrate_layout`. It is the canonical mechanism for bringing legacy consumer projects forward; it is idempotent and refuses to operate on a build dir that has no recognisable s0ma artifacts (defensive guard via `_looks_like_s0ma_build`). When adding new legacy artifacts to the cleanup recogniser, edit `_discover_legacy_layout_paths` — the recogniser's strict whitelist of layer-subdir names means the cleanup is targeted, not destructive.

### 1.3 Parse-time body dedenting (F1, feedback 5–6 follow-up)

Bodies are dedented exactly once, at parse time, in `parser/body_extractor.extract_body`. All downstream consumers (validator, codegen, IR, source map, doc subsystem) read `decl.body` (the dedented form). Any code calling `textwrap.dedent`, `inspect.cleandoc`, or a hand-rolled dedent on a body should be considered a bug.

The single source of truth is `body_extractor._dedent_body`. Its strategy — strip the indent of the first non-blank, non-comment line from every line that starts with that prefix; pass column-0 lines through unchanged — is the only correct one for `.s0ma` bodies, because the body splitter may capture column-0 trailing comments and CONSTANT bodies routinely contain multi-line strings whose interior is at column 0. `textwrap.dedent` collapses to a no-op on those inputs and used to leave the still-indented assignment line for `ast.parse` to reject as `IndentationError` — a swallowed silent failure that produced an M17 false-positive (closed by F1; see ADR-009).

The AST also exposes a `raw_body` (`raw_python_body` for examples) that retains the original .s0ma indentation. It is **diagnostics-only** — source maps, error-reporting line offsets, and tooling that needs to project a body byte back to the .s0ma column are valid uses. Production analysis (validator helpers, codegen literals, IR serialization, content hashes) uses `body`. If you find yourself reaching for `raw_body` from a non-diagnostic path, you have probably picked the wrong field.

### 1.4 0.14.0 — Manifest role, orphan prune, raw `.py` discovery

Three behavioural shifts in `_cmd_build` / `_cmd_test` that contributors should keep in mind when extending those paths:

**Manifest `role` field + merge.** Every `ModuleManifestEntry` carries a `role: "source" | "test"` field (default `"source"`). The build decides it per module: `_cmd_build` records each module with the role of the configured root its file lives under (`_root_role` in `cli/main.py`: `"test"` under a `[tool.s0ma].test_roots` entry, `"source"` under a `source_roots` entry), whichever path the caller named, so a bare `s0ma build`, `s0ma build .` and `s0ma build tests` tag a test module as a test and `bootstrap_imports` with its default roles loads the application alone. The hidden `_role` argparse attribute that `_run_build_for_test` sets for each of `s0ma test`'s passes (never exposed on the public CLI) is an explicit statement for the whole pass and wins when it is set; the roots are disjoint by construction (`OVERLAPPING_DISCOVERY_ROOTS`), so the two never disagree in practice. A module under no configured root is recorded as `source` and the build raises `MODULE_OUTSIDE_PROJECT_ROOTS` (a warning in every mode, so the build gate never counts it); a synthetic project has no roots and records `source` silently. Before writing the manifest, `_cmd_build` checks for an existing `build.s0ma.json` and merges with it (per-name overwrite of just this pass's modules; survivors of the prior pass keep their role tag). `--clean` skips the merge so a clean build always starts from an empty manifest. The build is the one place a role is derived from the file system: when adding build-time pipeline stages or readers, pull the role from the manifest entry, which is the canonical record. `VALID_ROLES` is the frozenset on `s0ma_dsl.codegen.build_manifest`; future roles (e.g. `"tool"`) require expanding that constant plus a schema-level review of the run/filter contracts that depend on it (`bootstrap_imports`, the merge logic, the test pipeline).

**Orphan artefact pruning.** After a clean build (`errors_so_far == 0`), `_prune_orphan_artefacts(output_dir, known_module_names)` removes `.py` / `.s0ma.json` / `.s0ma.map` triples whose `<stem>` is not in `known_module_names`. The triple-check safety predicate (all three sibling artefacts must exist before any one is removed) protects hand-written `.py` files. When you add a new build artefact whose lifecycle is tied to a `.s0ma` source, follow the same convention — emit alongside the existing triple, and extend the pruner's safety predicate symmetrically if the new artefact should also be pruned. **Never** prune artefacts that were emitted with errors in the build (the existing `errors_so_far` guard captures this).

**Raw `.py` test discovery.** `_discover_raw_python_tests(test_roots)` returns `.py` files under `[tool.s0ma].test_roots` that match pytest's collection patterns and have **no same-stem `.s0ma` sibling**. The "no `.s0ma` sibling" rule plus the flat-layout invariant (emitted `.py` lives in `build_dir`, not the test root) guarantees the discovered raw set and the build-dir collection set are structurally disjoint. The `_cmd_test` integration appends the discovered paths to `pytest_args` after the `build_dir` target. When extending `_cmd_test`'s pytest argument construction, preserve the disjoint-sets invariant — anything that adds a path twice will surface as `RegistrationError: Component 'X' is already registered` at pytest import time, which is the same failure mode the `--ignore` flags for `.s0ma.cache` were originally added to prevent.

**Cross-repo dependency note.** The DSL emitter's `register_constant(module_path=…)` / `register_type(module_path=…)` calls flow through the runtime bridge with an `inspect.signature` introspection guard, so the bridge is safe against pre-0.3.0 `s0ma-framework` installations. When extending the runtime bridge's other registration adapters, follow the same pattern: forward new kwargs only when the framework registry's signature accepts them, so partial-upgrade environments do not crash.

### 1.5 Bootstrap-pattern contract — thin CLI dispatch and `argparse.REMAINDER`

Downstream s0ma projects commonly ship a thin Python CLI shim that parses a subcommand, builds the modules dict via `bootstrap_imports`, and dispatches the rest to a presentation-layer nerve. The three-step pattern recurs in fr3d, in the kn0wthyself viz plugin, and in every other consumer that exposes a `python -m <app> <subcommand> [...args]` surface:

```python
# bootstrap/cli.py — plain Python, NOT a .s0ma file
import argparse
import sys
from my_app.bootstrap.startup import startup

def main() -> int:
    parser = argparse.ArgumentParser(prog="my_app")
    parser.add_argument("subcommand")
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    modules = startup()
    router = modules["presentation.cli_router"]
    return router.dispatch(args.subcommand, args.rest)

if __name__ == "__main__":
    sys.exit(main())
```

Three contributor-facing gotchas worth surfacing here so the next agent does not burn a discovery cycle:

**`argparse.REMAINDER` swallows the `--` separator.** Unlike `nargs="*"`, the `REMAINDER` action does *not* strip a literal `--` from the captured argument list. `python -m my_app run -- --flag x` produces `args.rest == ["--", "--flag", "x"]`, not `["--flag", "x"]`. The presentation nerve receives the `--`. Strip it explicitly at the dispatch site (`if rest and rest[0] == "--": rest = rest[1:]`) when the downstream consumer treats `--` as raw input rather than an option-parsing terminator. The detection is verbatim string equality — `--=` and other `--`-prefixed tokens are preserved.

**`nargs="*"` is the wrong tool here.** `nargs="*"` greedily consumes positionals — it cannot coexist with a preceding positional argument (`subcommand`) without `argparse` getting confused about which side of the boundary each token belongs on. `REMAINDER` is the canonical fix; it tells `argparse` "stop parsing after `subcommand`, capture everything remaining verbatim." This is also why `subparsers` is not the right shape for the thin-CLI case: subparsers re-enter the parser on every subcommand and require each subcommand to declare its option grammar in the bootstrap, which leaks presentation-layer behaviour into the bootstrap layer.

**The bootstrap is allowed to know about argparse — the presentation layer is not.** The presentation nerve receives a `list[str]` of remaining args and is responsible for its own parsing (typically by calling into `argparse.ArgumentParser` itself, or by accepting a fully-parsed `argparse.Namespace` from the bootstrap if the subcommands share enough grammar). The architectural boundary is "bootstrap owns process-level argv shape; presentation owns subcommand-level grammar."

The quick reference "Bootstrap Pattern" section carries the consumer-facing version of the same contract; this handbook section is the contributor-facing detail (what to watch when extending the runtime bridge or the build-pipeline integration with the bootstrap helpers).

### 1.6 0.6.0 onboarding CLI + the docs drift gate

Two facts contributors need from the UX phase-1 work (0.6.0, FR-DSL-5 v1.1):

**`s0ma new project` and `s0ma doctor` follow the separate-module precedent.** Each lives in its own CLI module (`src/s0ma_dsl/cli/new_project.py` / `src/s0ma_dsl/cli/doctor.py`, module-level `EXIT_*` constants, thin `_cmd_*` dispatch shims in `main.py`) — the same shape as `cli/migrate_ext.py`. One behavioural wrinkle in `run()`: both commands **bypass the pre-dispatch `_resolve_project` call** (`args.s0ma_project = None`), because `S0maProject.discover`'s `ValueError` on a malformed `[tool.s0ma]` table fires *before* the dispatch try-block — `doctor` must render it as a finding, and `new project` must not print the synthetic-fallback warning on its own success path. Every other subcommand still resolves the project pre-dispatch; new subcommands should too, unless they have the same render-config-errors-as-findings requirement.

**Several docs in this tree are drift-gated against byte-copies in `s0ma-mcp`.** The MCP server ships committed copies of the agent corpus as package data (`packages/s0ma-mcp/src/s0ma_mcp/_docs/`), and `s0ma-mcp`'s test suite byte-compares every copy against its in-repo source on every CI run (`tests/test_resources.py::TestDocDrift`). If you edit `docs/s0ma-dsl_quick_reference.md`, `docs/agent_system_prompt.md`, `docs/references/dsl_patterns_guide.md`, the current spec, the generated `docs/_generated/common_errors.md`, or the root `CHANGELOG.md`, you MUST refresh the matching copy in the same commit (`cp` the file over the `_docs/` copy) or `scripts/check.py` fails — that is the mechanism working, not a flake. The error catalog's source is itself generated: after grammar/diagnostic changes run `make -C packages/s0ma-dsl docs-derived S0MA="uv run s0ma"` first, then refresh the copy.

---

## 2. Naming Conventions

### 2.1 Component Names

All transpiler components use the `S0maDSL_` prefix to avoid collisions with s0ma framework components and other sister projects.

```python
@component(
    name="S0maDSL_S0maParser",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent="...",
    idempotent=True,
)
```

### 2.2 File Names

| Artifact | Convention | Example |
|----------|-----------|---------|
| Source modules | `snake_case.py` | `s0ma_parser.py` |
| Test modules | `test_<subject>.py` | `test_parser.py` |
| Valid fixtures | `tests/fixtures/valid/<name>.s0ma` | `signal_processor.s0ma` |
| Invalid fixtures | `tests/fixtures/invalid/<error_code>_<desc>.s0ma` | `missing_field_nerve.s0ma` |
| Golden outputs | `tests/fixtures/golden/<name>.<ext>` | `signal_processor.py`, `signal_processor.s0ma.json` |
| ADRs | `ADR-NNN-<slug>.md` | `ADR-001-build-pipeline.md` |

### 2.3 Error Codes

Error codes are SCREAMING_SNAKE_CASE, unique, and searchable. Use the error code registry in PRD §2.4.2. Do not invent new codes without adding them to the registry.

#### Adding a new error code (G6 decision rule)

Every error code literal that appears in `src/s0ma_dsl/` is pinned by the meta-test `tests/test_doc_consistency.py::test_every_error_code_literal_is_registered`. The audit walks every `.py` file under `src/s0ma_dsl/` with `ast.parse` and extracts:

- Every `code="<CODE>"` keyword argument to any call.
- The first positional string argument to calls that target the four error constructors (`S0maError`, `S0maParseError`, `S0maSemanticError`, `S0maResolutionError`).
- Every `<CODE>: ...` message-prefix token inside a string literal or f-string (the convention used by load-time error sites that don't go through `S0maError`, e.g. `project.py` raising `ValueError("OVERLAPPING_DISCOVERY_ROOTS: ...")`).

Each extracted code MUST appear in either `s0ma_dsl.config.SEVERITY_MATRIX` or `s0ma_dsl.config.OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`. The meta-test fires loudly with a remediation message if a future contributor adds an unregistered code.

When you add a new error code:

1. **Default: register it in `SEVERITY_MATRIX`.** Pick the appropriate severity-by-mode mapping. Most codes are `error` in every mode (structural correctness violations); some are mode-graded (warning in migration/dev → error in strict/release for hygiene-shaped rules); release-only codes are `None` in migration/dev/strict and `error` in release.
2. **Only use `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE` when both conditions hold:**
   - The code is structurally always-one-severity (no mode variation makes sense). Examples: a project-load configuration error cannot be softer than `error` because the project model cannot be constructed at all; a hygiene smell with no correctness cost cannot be more than a `warning`.
   - The code fires from a surface that does not carry a strictness mode. Examples: project load (`S0maProject._from_tool_s0ma`), file discovery, pre-flight check (`s0ma test` conftest classification).
3. **Add a one-line comment per entry** in either registry explaining the rationale (severity-by-mode for `SEVERITY_MATRIX`; "always-one-severity, no mode variation" structural reason for the out-of-matrix list).
4. **Add a row to `docs/spec_traceability.md`** describing the rule, its trigger, the implementation site, and the test module that pins it. The traceability matrix is the canonical rule-to-implementation map; without a row, future contributors cannot trace the rule.

The single-source-of-truth invariant is enforced by three meta-tests: `test_every_error_code_literal_is_registered` (audit ↔ registries), `test_error_codes_in_traceability` (`SEVERITY_MATRIX` ↔ traceability), and `test_out_of_matrix_codes_in_traceability` (out-of-matrix list ↔ traceability). Drift in any direction surfaces immediately.

### 2.4 Test Names

```python
def test_<subject>_<scenario>_<expected_outcome>():
    """Example: test_nerve_missing_intent_raises_parse_error"""
```

---

## 3. Dogfooding Rules (CC-1)

Every Python module in the transpiler that defines public classes or functions MUST use s0ma decorators.

```python
from s0ma.decorators import component, internal
from s0ma.types import ComponentKind, Layer
from s0ma.models import Contract

# Public class or function
@component(
    name="S0maDSL_<Name>",
    kind=ComponentKind.<KIND>,
    layer=Layer.FRAMEWORK,
    intent="<10+ chars describing purpose>",
    idempotent=True,
)
class MyPublicClass:
    ...

# Private helper
@internal
def _my_helper():
    ...
```

**Key rules:**
- Use `Layer.FRAMEWORK` for all transpiler components
- Use `idempotent=True` to prevent `RegistrationError` during test imports
- If `@component` causes issues, document in `docs/s0ma_feedback.md` and use `@internal` temporarily
- The import hook is NOT activated for the transpiler (decorators-only, no hook enforcement)

---

## 4. Testing Expectations

### 4.1 Every Milestone Has Tests

Do not consider a milestone complete until its validation checklist passes. Tests are not optional.

### 4.2 Fixture-Driven Testing

- **Valid fixtures** (`tests/fixtures/valid/`) — `.s0ma` files that MUST parse, validate, and transpile successfully
- **Invalid fixtures** (`tests/fixtures/invalid/`) — `.s0ma` files that MUST fail with specific error codes
- **Golden fixtures** (`tests/fixtures/golden/`) — expected output for deterministic comparison

### 4.3 Test Categories

| Category | What It Tests | When to Write |
|----------|--------------|---------------|
| Unit | Individual functions/classes | Every milestone |
| Snapshot | Deterministic output comparison | IR and codegen milestones |
| Integration | Multi-stage pipeline | Phase 7+ |
| Golden | End-to-end against spec §8 example | Phase 7+ |

### 4.4 Determinism in Tests

All outputs must be deterministic (NFR-01). Avoid:
- Set iteration (use sorted lists)
- Random IDs or UUIDs in output
- Timestamps in generated code
- Non-deterministic dict ordering (use `sorted()` on keys)

---

## 5. Guardrails (PRD §1.13)

These are binding on all implementation work:

1. **Spec is authoritative.** When the PRD is less precise, defer to the DSL spec.
2. **No unauthorized semantics.** Do not add behavior the spec does not authorize.
3. **Authored vs. derived boundaries are strict.** Per PRD §1.12 and spec §4.11.
4. **No namespace blurring.** The four namespaces (code, component-ref, registry, public API) are distinct.
5. **No escape hatches.** Do not allow runtime bypass because a test is easier that way.
6. **Update tests when behavior changes.** Traceability must stay current.
7. **Deterministic explicitness over clever inference.** When in doubt, be explicit.
8. **Check deferrals before implementing.** PRD §1.6 lists what is NOT in scope for v1.
9. **Dogfood all modules.** No module is exempt from `@component`/`@internal`.
10. **Milestone boundaries are hard stops.** Do not implement beyond the active milestone.

---

## 6. Merge Checklist

Before considering any milestone complete:

- [ ] All milestone tasks implemented
- [ ] All validation checklist items pass
- [ ] `pytest` passes with no failures
- [ ] No new files without `@component` or `@internal` on public entities
- [ ] Spec traceability matrix updated for any rules touched
- [ ] `docs/s0ma_feedback.md` has a milestone entry
- [ ] No v2 features implemented (check PRD §1.6)
- [ ] No non-deterministic output patterns introduced
- [ ] Drift-gated docs edited (quick reference, agent system prompt, patterns guide, spec, generated error catalog, root `CHANGELOG.md`)? Refresh the byte-copies under `packages/s0ma-mcp/src/s0ma_mcp/_docs/` in the same commit (see §1.6)

---

## 7. Deferrals Reference

The following are explicitly out of scope for v1 (PRD §1.6). Do NOT implement:

- PRIVATE visibility / nested components
- Mixed-layer modules
- Conditional or deferred imports
- Class-bodied nerves
- Structured contract subfields
- Runtime contract enforcement
- Mutation relations (WRITES, MUTATES, CATCHES)
- Derived CALLS via static analysis
- Expanded TYPE_USES beyond nerve/ganglion signatures
- Selective cycle relaxation
- Full incremental recompilation
- Full migration tooling
- Richer prior mini-language
- Finalized evaluator activation model
- Stable UUIDs for rename tracking
- Deprecation markers
- Evaluator chaining
- Hot reload
- IDE integration
- Automated Python-to-s0ma migration

---

## 8. Common Pitfalls

1. **Confusing `uses` and `requires`.** `uses` = s0ma components (self-describable). `requires` = external Python (opaque). Never mix them.
2. **Putting `requires` names in DSL fields.** The component-reference namespace excludes `requires`. You cannot write `raises: [ValueError]`.
3. **Authoring derived edges.** RAISES and TYPE_USES are ALWAYS derived. Authored axons with these relations must be rejected.
4. **Emitting privileged imports in normal modules.** Privileged imports are ONLY for test and ganglion files. Regression tests must prove this.
5. **Non-deterministic ordering.** Use declaration order for components, deterministic sort for edges. Never iterate sets directly.

---

## 9. Codegen Conventions

### 9.1 Metadata-string interpolation: `_py_str_literal()` is the canonical path

Every string interpolated into emitted Python — `intent`, `expects`,
`guarantees`, `forbids`, `schema`, `invariants`, `priors`, `on_anomaly`,
axon `carries`, doc-* `format`/`output`, example `runs_in`, and any other
metadata field — must go through `_py_str_literal()` in
`s0ma_dsl.codegen.python_emitter`. The helper is a thin wrapper over
Python's `repr()` (with a double-quote-preference layer for readability)
and the result is guaranteed to round-trip through `ast.parse()`.

Direct `f'"{value}"'` patterns are forbidden. They produce unsafe
output for any input containing `"`, `'`, or backslashes — see CHANGELOG
0.12.0 → Fixed for the historical `\"` corruption bug. If you find
yourself writing manual escape logic, stop and use `_py_str_literal()`
instead. The legacy `_escape_string` / `_format_multiline_string`
helpers were retired in M2 of the feedback 5–6 plan.

### 9.2 Output validation invariant

Every emitted `.py` payload is validated with `ast.parse()` before
being written (see `s0ma_dsl.codegen.validate_emitted_python`). The
check is wired into both the CLI primary write site
(`s0ma_dsl.cli.main._transpile_file`) and the on-disk cache writer
(`s0ma_dsl.cache.TranspilerCache.store`). When the invariant is
violated, the writer raises `TranspilerInternalError` and the file is
not written. New emission paths must call `validate_emitted_python`
before their `write_text`.

### 9.3 Canonical test-target resolution: a single helper, two callers

`s0ma_dsl.resolver.namespaces.resolve_test_target_canonical` is the
**single source of truth** for `tests:` resolution. Both the IR builder
(when emitting verification edges in
`ir/builder.py:_build_verification_edges`) and the dependency resolver
(when checking release-mode coverage in
`resolver/dependency.py:_check_release_test_coverage`) must call
through it. The IR builder's `_resolve_target_canonical` delegates to
`canonicalize_qualified_target` (the syntactic sibling that handles
the bare-vs-qualified split without needing a registry view), and the
dependency resolver layers registry-aware ambiguity detection on top.
Both helpers live in one module so the canonicalisation rule is
defined exactly once.

Do not reimplement the bare-vs-qualified split anywhere else, do not
last-segment-split-and-pray, and do not special-case bare-name
comparison. If a new pass needs to consume `tests:` entries, it
imports from `resolver.namespaces` and shares the helper. A bare
target that matches multiple modules surfaces as the
`AmbiguousTestTarget` sentinel — callers must emit
`AMBIGUOUS_TEST_TARGET` rather than silently mis-resolving.

### 9.4 `s0ma test` runner internals (M7)

`S0maCLI._cmd_test` is the transpiler's project-aware pytest runner.
It is a thin wrapper whose every behavioural input is computed from
the resolved `S0maProject` — no per-project conftest plumbing
required to make cross-module imports resolve. The runner has four
moving parts; understanding the contract between them is essential
before changing any of them.

**1. Argument parsing — `--`-split before argparse.**

The literal `--` separator is consumed by `S0maCLI.run` *before*
the argparse parser is built. Everything to the left of `--` is
parsed normally; everything to the right is stored verbatim on
`args.passthrough_args` and forwarded to pytest. This is why the
test parser declares only the args `s0ma test` itself reads
(`test_dir`, `--mode`, `--quiet`) — argparse never sees pytest's
flags, so it cannot consume them. Pre-M7, a `pytest_args=nargs="*"`
arg greedy-consumed `-o`, `--maxfail`, etc., producing the bug
documented under feedback-5.5 M01. The split-before-parse approach
is structural (not a heuristic): no flag name overlap between
`s0ma test` and pytest can ever recur.

If you add a new top-level CLI flag, the split happens against the
pre-`--` argv only, so your flag is parsed normally even when the
user invokes `s0ma --new-flag test -- -k ...`.

**2. Project discovery and preflight.**

`_cmd_test` reads the resolved `S0maProject` off `args.s0ma_project`
(set by `_resolve_project` during dispatch). Two preflight checks
fire before any build work:

- `importlib.util.find_spec("pytest")` returns `None` ⇒ exit 2 with
  remediation pointing at `pip install pytest`. This catches the
  common "pytest is in dev-deps but the user's active venv doesn't
  have it installed" case loudly rather than silently producing
  cryptic subprocess errors.
- `s0ma_project.test_roots` is the empty tuple ⇒ exit 2 with
  remediation pointing at `[tool.s0ma].test_roots`. Distinct from
  the "test_roots configured but no .s0ma files yet" path, which
  exits 0 with a friendly notice.

**3. Build pass — reuses `_cmd_build`.**

`_run_build_for_test` constructs an `argparse.Namespace` shaped like
the build subcommand's parsed args and dispatches to
`_cmd_build`. Two passes:

- Source roots first (so test modules can `uses:` source modules
  cross-module without context warnings). Each per-source-root
  invocation threads the *other* configured source roots through
  `--include` (G4) so cross-source-root `uses:` references in source
  modules resolve as context. The per-root structure is preserved —
  it is the canonical surface for build-error attribution. Single-
  source-root projects pass an empty sibling list (no regression).
  Each invocation is one-shot, so a complete sibling-include graph
  (A↔B↔C) does not induce a cycle.
- Test roots second, with *every* source root threaded through as
  `--include` so the resolver sees the full project as context.

Both passes write to the same `<build_dir>` (M6a flat layout). The
build is run with `--no-cache` — the test command is not the place
to debug stale-cache surprises, and a fresh build is fast.

Consequence: `_cmd_build` is the single source of truth for
transpile + manifest emission. If you change build behaviour, the
test runner picks it up automatically. Do *not* duplicate transpile
logic in `_cmd_test`; that path was the source of pre-M6a's
two-headed-build problem.

**Build-error attribution.** A parse / validation failure inside a
source root carries that file's actual source-root path (the
diagnostic's `file=` is the on-disk path, not the build target). G4
preserves this: only the resolution context expanded; the per-root
iteration that surfaces "this root's build failed" still fires
against the offending root. A deliberately broken file under
`domain/` produces a diagnostic naming the `domain/` path, even when
the build pass that surfaced it was iterating `application/` with
`domain/` threaded as a sibling include. The attribution test in
`tests/test_multi_source_root_resolution.py` pins this contract.

**4. Pytest invocation — env + args + subprocess.**

After the build:

```python
env = dict(os.environ)
env["PYTHONPATH"] = (
    str(build_dir) + os.pathsep + env.get("PYTHONPATH", "")
)
pytest_args = [
    "-o", "python_files=test_*.py *_tests.py",
    # F2: cache exclusion — `--ignore=<abs_path>` for every plausible
    # cache location (build_dir, project root, source roots, test roots).
    "--ignore", str(build_dir / ".s0ma.cache"),
    "--ignore", str(build_dir / "__s0ma_cache__"),
    "--ignore", str(s0ma_project.root / ".s0ma.cache"),
    "--ignore", str(s0ma_project.root / "__s0ma_cache__"),
    # ...plus __s0ma_cache__/ under each source_root and test_root...
    str(build_dir),
    *args.passthrough_args,
]
subprocess.run(
    [sys.executable, "-m", "pytest", *pytest_args],
    env=env, check=False,
)
```

`PYTHONPATH` leads with `<build_dir>` so a build's transpiled module
always wins over a stale install of the same name. The
`python_files` glob extension is set on the pytest command line
(not in the consumer's pyproject.toml) so it is uniform across
every consumer. The subprocess is invoked with `check=False` —
pytest's exit code is the runner's exit code; non-zero is a test
failure, not an exception.

**Cache exclusion (F2).** The `--ignore` flags are unconditional:
pytest accepts non-existent paths harmlessly, so we don't preflight
the directories. Both `.s0ma.cache/` (current name) and
`__s0ma_cache__/` (legacy pre-M6a name) are excluded — the legacy
entries protect mid-migration consumers that have not yet run
`s0ma migrate-layout`. Paths are absolute, never globs, so a user
test directory whose name happens to contain `.s0ma.cache` as a
substring is not wrongly excluded. Pytest's default
`norecursedirs = .* …` already skips dot-prefixed directories on a
default config, but consumer projects with custom
`[tool.pytest.ini_options]` can disable that — F2's `--ignore` flag
is a structural defense that does not depend on pytest's defaults.
fr3d's M20 smoke test was blocked by exactly this: a custom pytest
config let the cache dir into collection, every component
double-registered, and `s0ma test` failed on `RegistrationError`.

`subprocess.run` is the right primitive (not `pytest.main()`):
in-process invocation would couple `s0ma`'s test command to the
consumer's pytest version, and would risk cross-test-suite state
leakage if anything pytest does at startup mutates global state.

**Test infrastructure.** The runner has its own test file
(`tests/test_s0ma_test_runner.py`) and fixture
(`tests/fixtures/cross_module_test_project/`). The fixture exercises
both naming conventions (`test_*.s0ma` and `*_tests.s0ma`) and the
cross-module-import path that CRIT-3 documented. If you change the
runner's contract, update both.

**5. Conftest staleness pre-flight (G5 — feedback 5–6 cleanup).**

After the explicit-test-dir guard and before the build pass, `_cmd_test`
calls `_classify_conftest(s0ma_project.root / "conftest.py")`. The
classifier is pure (modulo a single `Path.is_file` + `Path.read_text`)
and returns one of five state strings:

```
absent | current | untouched_stale | customized_stale | unrecognized
```

The wire-up reacts as follows:

- `absent`: skip the pre-flight entirely. The project does not use a
  generated conftest; pytest runs without one. The M11+ runner
  initialises the runtime bridge from imported modules, so this is the
  expected steady-state for most projects.
- `current`: proceed. The banner version matches `s0ma_dsl.__version__`;
  the body checksum is *not* consulted — a current-version conftest the
  user hand-edited is still valid against the current runtime contract.
- `untouched_stale`: regenerate non-destructively, then proceed. Calls
  `_collect_kinds_and_layers(project.root)` (shared with `_cmd_test_conftest`'s
  write side, so byte-exact regeneration is guaranteed) and writes the
  fresh content. Emits `s0ma-dsl: regenerated stale conftest at <path>
  from 0.X.Y -> 0.13.0` to stderr. Only fires for entries explicitly
  registered in `STALE_GENERATED_CONFTEST_VERSION_CHECKSUMS`; on initial
  G5 release the registry is empty so this branch never fires.
- `customized_stale` / `unrecognized`: refuse to invoke pytest. Print a
  `STALE_GENERATED_CONFTEST: <path> ...` diagnostic with a remediation
  pointing at `s0ma test-conftest --force` (preserve customizations) or
  delete-and-`s0ma test-conftest` (clean regeneration). Returns
  `EXIT_VALIDATION_ERROR` so CI surfaces a non-zero exit before pytest
  starts.

**Banner format.** Four comment lines: `# Generated by s0ma-dsl <ver>`,
`# Content checksum: <sha256-of-body>`, do-not-hand-edit notice,
`--force` pointer. The body checksum covers everything *below* the
banner; the banner is excluded so re-running `s0ma test-conftest` against
the same s0ma-dsl version produces a banner whose checksum line agrees
with the body byte-for-byte. The banner-parser (`_parse_conftest_banner`)
walks the leading comment block until the first non-comment, non-blank
line, returning `(version, checksum)` or `(None, None)`. Robust against
banner-stripping, banner-only-half-present, and hand-rolled conftests.

**Version-checksum registry.** `STALE_GENERATED_CONFTEST_VERSION_CHECKSUMS:
dict[str, str]` (in `cli/main.py`) maps a prior version string to the
SHA256 hex digest of the body that prior version would have produced.
Populating it lets the `untouched_stale` branch fire for that version
(non-destructive auto-regeneration). **Initial state: empty.** Pre-G5
releases didn't embed banners and their generated bodies depended on
project content (kind / layer comments), so retroactive population is
not feasible. The fail-safe `customized_stale` classification of every
pre-G5 conftest is by explicit plan choice — silent rewrites of files
that may carry hidden customizations are a worse failure mode than a
loud one-time error.

### 9.5 `s0ma inspect` resolution algorithm (M16)

`S0maCLI._cmd_inspect` resolves its positional `<target>` argument
through a four-step chain. The chain is structural, not heuristic —
each step has a precondition, and falls through cleanly to the next
step when its precondition does not hold.

**1. Existing filesystem path (legacy).** When `Path(target).exists()`
is true, the resolver uses the path directly:

- A `.s0ma.json` file → loaded as IR.
- A `.s0ma` source file → resolved through `_resolve_s0ma_to_ir`
  (same-dir, `.s0ma.cache/`, legacy `__s0ma_cache__/` for read-only
  back-compat, then auto-transpile to a temp dir).
- A directory → walked for `*.s0ma.json` via `_discover_ir_files`.

This step preserves the pre-M16 behaviour byte-for-byte; existing
scripts and tests that pass paths continue to work unchanged.

**2. Module name → `project.build_dir/<name>.s0ma.json`.** When
the target string contains no path separator and does not end in
a recognised file suffix, and the resolved `S0maProject` is not
synthetic, the resolver checks
`s0ma_project.build_dir / f"{target}.s0ma.json"`. Found ⇒ render.
Not found ⇒ jump to the friendly-error step below — we do *not*
fall through to step 3 with the assumption that the typo might
match a `.s0ma` source instead, because that would mask the much
more common "module name typo against a built project" case.

**3. `.s0ma` source basename via project roots.** When the target
looks like a module name *and* step 2's manifest lookup did not
fire (e.g., the project was discovered but never built), the
resolver walks every `source_root` and `test_root`, looking for
a file whose stem matches the target. The first hit is fed to
`_resolve_s0ma_to_ir`, which auto-transpiles to a temp dir.

**4. Friendly "module not found" error.** When steps 2 falls
through with no match, `_inspect_module_not_found` reads the
build manifest (M6b) — the source of truth for "what's in this
build" — and prints `Module '<target>' not found. Available
modules: ...`. When the manifest is absent (the project was
discovered but never built), the resolver falls back to a
filesystem walk of the declared source/test roots so the
available-modules listing is still useful. A "Did you mean ...?"
hint is appended when `difflib.get_close_matches` returns a single
candidate above the 0.6 similarity threshold; below that, the
suggestion adds noise rather than signal.

**`--all` flag.** Short-circuits the resolution chain. Reads the
manifest, loads each module's IR, and prints one line per module
with the module name, layer, per-kind component counts, and total
component count. JSON output (`--format json`) emits a list of
objects with the same fields. Without a non-synthetic project,
`--all` exits 2 with a remediation pointing at `[tool.s0ma]` —
the manifest is the contract, and synthesizing one from the
filesystem would defeat M16's "no silent fallback" guarantee.

**Why the manifest is the source of truth.** Step 2 and step 4
both prefer the build manifest over filesystem walking. The
manifest is the canonical "what's in this build" answer (see
M6b / `codegen/build_manifest.py`); walking the build directory
would produce the same answer most of the time but would silently
re-discover stale `.s0ma.json` files left behind by an aborted
build, or miss modules the manifest knows about but were emitted
to a non-default location. The manifest is cheap to load
(one JSON file, one schema check) and unambiguous.

**Test infrastructure.** The resolution chain has its own test
file (`tests/test_inspect_by_name.py`) and reuses the
`multi_module_project` fixture, staged into a tmp directory with
a synthesized `pyproject.toml` so the project-discovery path is
exercised end-to-end. Existing path-based inspect tests in
`tests/test_cli.py` continue to assert the legacy form.

### 9.6 Cache key is the declared module name (M4)

`s0ma_dsl.cache.BuildCache` keys every cache entry by the **declared
module name**, not by the source filename's stem. The key is derived
once via `extract_module_name(source_path)` (a regex over the
top-of-file `module <name> :: <layer>` line) and threaded through every
cache method as the optional `module_name` argument; callers that
already have a parsed `S0maModule` should pass the canonical name
explicitly to avoid re-reading the source.

This lets the IR's canonical identity (`module.name`) be the single
source of truth across three previously-divergent surfaces: the cache
key, the `<module>.py` / `<module>.s0ma.json` / `<module>.s0ma.map`
output filenames, and the `uses:` import paths the resolver follows.
Pre-M4 the cache keyed on `Path.stem`, which silently broke as soon as
a file's stem disagreed with its declared module name (e.g.,
`integration.s0ma` declaring `module google_calendar_integration`):
the cache would write outputs that no consumer could find by `uses:`.

The `MODULE_NAME_STEM_MISMATCH` validator
(`semantic/validator.py:_check_module_name_stem_match`) is the matching
build-time invariant: every `.s0ma` source whose filename stem differs
from its declared module name fails strict-mode `s0ma check` with
remediation pointing to either the rename of the file or the rename
of the module. Validator severity is "error" in dev/strict/release
(plus warning in migration to ease adoption); this is enforced via the
`SEVERITY_MATRIX` row in `config.py`. Together the cache key and the
stem-match validator close the silent-failure loop — the cache derives
from `module.name` and the validator guarantees the file shipped on
disk agrees.

**Implication for transpiler contributors:** new cache callers should
pass `module_name=` explicitly when they already have a parsed
`S0maModule`; the fallback regex extraction is for the rare path
where only a file path is available. Never reintroduce a code path
that derives a cache key (or output file name) from `Path.stem`.

### 9.7 Scope-aware HELPER_NAME_COLLISION (M3)

`semantic/validator.py:_check_test_helper_collisions` warns when two
or more `test` declarations in the same module define a top-level
`def <name>` with the same name. M3 is a scope-aware sweep: the check
only fires when the colliding helpers are *both* at top-level (i.e.,
they would silently overwrite each other when the test bodies are
emitted into one module file). Inner functions, methods on a `class`,
and helpers under different names are not flagged.

The collision is surfaced as `HELPER_NAME_COLLISION` at warning
severity (informational across modes). It is one of two error codes
that bypass the matrix-driven severity system (the other being the
documentation-subsystem warning codes); the `test_doc_consistency.py`
meta-test `test_out_of_matrix_codes_still_in_traceability` pins the
small list of codes that bypass the matrix yet still appear in
`docs/spec_traceability.md`. **Implication for transpiler
contributors:** if a future M-N also goes the hand-emitted-warning
route, add its code to `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`
in `tests/test_doc_consistency.py` so the traceability surface stays
honest.

### 9.8 `helper` declaration kind (M13)

The `helper` kind is the third path between "nest a function inside a
single nerve body" (used by exactly one nerve, ≤20 lines) and "promote
to a `nerve` and register it as a component" (semantically wrong for
plumbing). Helpers live in `src/s0ma_dsl/ast_nodes/nodes.py` as
`HelperDecl`, parse out of the Lark grammar via the `helper_decl` rule,
and emit a plain top-level `def` in the generated module (no
`@component`, no `register_*()` call, never in `__all__`).

Helpers are first-class IR citizens despite not being registered
components: they appear under `IRDocument.helpers` (a separate
top-level array, parallel to `components`), surface in `s0ma inspect`
under a `[helpers]` section, and participate in the `uses:` resolution
machinery just like nerves so the test-cross-module-import path
(`HELPER_PRIVATE_TO_MODULE`) can fire when a production module tries
to reach a helper. The cross-module rule: a module may `uses:` a
helper from another module *only if* the consuming module declares
≥1 `test` declaration. Production modules cannot.

**Implication for transpiler contributors:** when adding a code path
that walks "every named function in a module", iterate
`module.cells + module.nerves + module.ganglia + module.helpers + module.tests`.
Forgetting `module.helpers` is a recurring drift surface (helpers were
late additions to multiple analyzers); the inspector / IR builder /
verifier all carry a comment marking the iteration loop. The
`test_helper_*.py` test suite asserts the surface remains complete.

### 9.9 Structural attribute budgets (M18)

`S0maProject.attribute_budgets` is a `dict[str, str]` mapping each
namespace (`landmark`, `route`, `css_class`, `rpc`, ...) to a budget
shape (`exactly_one_per_page`, `unique_in_project`, `warn_on_duplicate`).
Authored under `[tool.s0ma.attribute_budgets]` in `pyproject.toml`,
parsed by `S0maProject.discover()` from the same TOML pass that reads
`source_roots` and `bootstrap_files`. Without a budget table the field
is purely descriptive; nerves' `declares_attributes:` entries appear
in the IR but no validation fires.

The validator runs in `resolver/dependency.py:_check_attribute_budgets`
across the project graph. Three shapes:

- `exactly_one_per_page` — Phase 1 of the four-phase resolver builds
  the `uses:` graph; "page" = a top-level module (not the target of any
  other module's `uses:`); the reachable nerve set is the transitive
  closure of `module.uses` from each top-level module. For each
  `<namespace>:<attribute>` pair declared by any nerve in that set,
  the count must be exactly 1 — zero or more-than-one fires
  `ATTRIBUTE_BUDGET_VIOLATION` at error severity (warning in
  migration; error in dev/strict/release).
- `unique_in_project` — flat project-wide pass: at most one occurrence
  of each `<namespace>:<attribute>` string. Independent of the `uses:`
  graph. Same severity ladder as `exactly_one_per_page`.
- `warn_on_duplicate` — same shape as `unique_in_project` but warning
  severity in every mode.

**Why "page" is implicit-from-graph rather than an explicit
`kind: PAGE_COMPOSER` enum.** See the M18 deviation entry in
`plans/5-6_deviations.md` ("what is a page composer?") — the explicit-
enum alternative was rejected because forgetting the marker silently
disables the budget. Implicit-from-graph reuses the `uses:` edges the
author already wrote.

**Parsing the field.** `declares_attributes:` is parsed by a
dedicated `_parse_attribute_list` Python helper, not the Lark
`name_list` rule. Each entry is a `<namespace>:<attribute>` string
where the attribute portion may contain spaces, slashes, hyphens and
other non-identifier characters (`route:GET /self`,
`css_class:btn-primary`). Double-quoted form is required when the
attribute contains commas or other ambiguous characters. See the
M18 deviation entry "`declares_attributes:` parsed via a custom
helper" for the rationale and the unit-test references.

**Implication for transpiler contributors:** the field exists on
`NerveDecl` only — not `CellDecl`, `GanglionDecl`, or `HelperDecl`.
The reasoning is in the M18 deviation tracker; the short version is
"attribute claims are about behaviour the nerve executes; cells are
structural artifacts and don't produce structural attributes
themselves." If a future namespace genuinely needs cell-level claims
(e.g., a SQL-schema budget), add the field then; do not pre-emptively
extend the surface.

### 9.10 `s0ma verify` status taxonomy (M11 + G1)

`S0maCLI._cmd_verify` classifies every `.py` file under inspection
into one of four authoritative statuses (plus the three drift
statuses for hash-bearing artifacts that have changed since
emission). The classification logic is a per-file ladder consulted
once per scanned `.py`; understanding the precedence order is
essential before extending it.

**Status ladder (top match wins):**

1. **Hash-bearing artifact** — the file carries embedded
   `# s0ma-source-hash:` and `# s0ma-output-hash:` comments. Both
   match → `CLEAN`; one mismatches → `EDITED` / `STALE` /
   `CONFLICT` per the existing M5b drift detector.
2. **`BOOTSTRAP`** — no checksum comments and the file's resolved
   absolute path matches a declared `[tool.s0ma].bootstrap_files`
   entry. Informational; hidden from the default text output;
   surfaces under `--verbose` and in `--format json`.
3. **`PACKAGE_MARKER` (declared)** — no checksum comments and the
   file's resolved absolute path matches a declared
   `[tool.s0ma].package_markers` entry. Explicit declaration wins
   over auto-classification (a non-empty `__init__.py` with
   `__all__` re-exports listed under `package_markers` lands here,
   not in step 4 or step 5).
4. **`PACKAGE_MARKER` (auto-classified)** — no checksum comments,
   no declaration, and `s0ma_dsl.project.is_empty_package_marker`
   returns `True`. The structural rule: stem `__init__`, suffix
   `.py`, body (after `ast.parse`) is either empty (whitespace-only
   files take this branch) or a single module-level
   `ast.Expr(value=ast.Constant(value=str))` (docstring). Any
   executable content disqualifies the file. Failures from
   `ast.parse` (`SyntaxError`) and `read_text` (`OSError`,
   `UnicodeDecodeError`) return `False` — the conservative default
   keeps broken `__init__.py` files surfacing as `UNKNOWN` rather
   than being silently classified as harmless.
5. **`UNKNOWN`** — none of the above. Always loud at every
   verbosity; surfaces with a remediation that names both available
   declarative fixes (`bootstrap_files` for runtime entry points,
   `package_markers` for re-export-bearing `__init__.py`) and the
   transpile alternative.

**Default-vs-`--verbose` rendering.** `BOOTSTRAP` and
`PACKAGE_MARKER` are both informational and follow the same
hidden-by-default policy: per-file rows are suppressed at default
verbosity, surfaced under `--verbose`, and always present in
`--format json`. `UNKNOWN` rows are loud at every verbosity. The
default summary line is `Verified N module(s). M bootstrap file(s)
recognized. K unknown.` — the package-marker count is omitted.
Under `--verbose` the line extends to `Verified N module(s). M
bootstrap file(s) recognized. P package marker(s). K unknown.` so
the consumer can audit the project's full marker surface when they
ask for it.

**One line per file (B4, beta-prep-5).** The text output prints one
row per file and says a repeated explanation once, under the list,
instead of after every row. A status qualifies for that hoisting
when every shown row of it carries the *same* `detail` and either
there is more than one such row, or the status is listed in
`_VERIFY_ALWAYS_NOTED_STATUSES` (`UNKNOWN` — the one a
freshly-adopted codebase meets on nearly every file, so its shape
should not change between a one-file project and a fifty-file one).
Statuses whose rows say genuinely different things keep their
explanation on the row: `ADOPTED_DRIFT` names the file in its
remediation, and `PACKAGE_MARKER` has two classification reasons a
reader cannot tell apart from the file name. `UNKNOWN`'s note is
the one written for the reader rather than lifted from the row
(`_VERIFY_UNKNOWN_NOTE`); the row's `detail` is the machine-readable
surface and `--format json` still carries it unchanged, per file.
Notes wrap at `_VERIFY_NOTE_WIDTH` with backticked commands and
hyphenated words held together, so nothing a reader might retype
straddles a line break.

**`CONFLICTING_PACKAGE_DECLARATION`.** A file that appears in BOTH
`bootstrap_files` and `package_markers` is a misconfiguration that
fires at `S0maProject._from_tool_s0ma` time — before any subcommand
runs. The diagnostic names every conflicting file and instructs the
author to declare each in exactly one list. The error code is
out-of-`SEVERITY_MATRIX` (configuration-shaped, never reaches the
strictness ladder) but tracked in
`tests/test_doc_consistency.py::OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`
and pinned to the spec traceability matrix.

**Why hidden-by-default for `PACKAGE_MARKER`?** Same rationale as
M11's `BOOTSTRAP` policy. Package markers are noise floor on a
project that organises its source tree as a Python package — the
typical 4-layer project carries 5–10 `__init__.py` files, most of
them empty. Surfacing every one as a per-file row at default
verbosity drowns the actionable `UNKNOWN` rows in informational
chatter. Hiding them keeps the noise floor at zero (M11's promise)
and makes the auto-classification path observably equivalent to
"the consumer doesn't have to think about it."

**Why structural inspection rather than a size threshold or a
filename pattern?** Both alternatives have known false-positive
modes. A 1-byte file might be a forgotten assignment that lost its
right-hand side; a long docstring is still a marker. A filename
pattern (`__init__.py` always = marker) misclassifies real
re-export surfaces as harmless. The AST-shape rule —
"parse succeeds AND body is empty or a single docstring" — is the
narrow Python-convention-honouring shape; any executable content
falls through to `UNKNOWN` so the author still gets the diagnostic.

**Test infrastructure.** The runner has its own test file
(`tests/test_package_markers.py`) and fixture
(`tests/fixtures/package_markers_project/`). The fixture exercises
every branch of the ladder: a top-level empty `__init__.py`, a
docstring-only `__init__.py` under one layer, an `__all__`-bearing
`__init__.py` declared under `package_markers` (status: declared
override), and an `__all__`-bearing `__init__.py` left undeclared
(status: `UNKNOWN`). If you change the classifier or the rendering
contract, update both.

### 9.11 Derived docs (G7a + G7b, feedback 5–6 cleanup)

s0ma-dsl's own documentation is partly derived from registry data, not hand-authored. The Common Errors table — `docs/_generated/common_errors.md`, served to agents as `s0ma://guide/errors` — is the first instance of this pattern; future tables (the spec traceability matrix, CLI command listings) are candidates for the same shape when they next get attention.

**Where the source lives.** `docs/_generators/` holds the in-repo `doc-ref` declarations. Today there is one: `docs/_generators/common_errors.s0ma` declares a single `doc-ref CommonErrorsTable` whose `covers: { source: error_codes }` form pulls from the canonical error-code registry (G7a's grammar extension). The directory is committed; both the generator source and the rendered artifacts ship with the repo.

**Where the rendered output lands.** `docs/_generated/` holds the derived artifacts. The `_generated/` prefix is the human-readable convention marking the directory as machine-output (do not hand-edit). Every file under `docs/_generated/` is committed but is overwritten on `make docs-derived`; CI surfaces drift via the meta-tests in `tests/test_doc_consistency.py`.

**How to render.** The s0ma-dsl repo is not itself a `[tool.s0ma]` project (it is the transpiler, not a project that consumes the transpiler). The `Makefile` target `make docs-derived` invokes `s0ma docs render docs/_generators/ --output-dir docs/` directly — passing the generator directory as the source and the parent `docs/` directory as the base for `output:` resolution so each `doc-ref`'s declared `output: _generated/<name>.md` lands at `docs/_generated/<name>.md` rather than `docs/_generators/_generated/<name>.md` (the default base-dir is the source directory). If you add a future generator, follow the same `output: _generated/<name>.md` convention so the same Make target picks it up without further configuration.

**The bracketed-region convention (retired 2026-09-29).** Until the quick reference became a generated page of the documentation application, the rendered table was also COPIED into an HTML-comment-bracketed region of the hand-authored quick reference, and a meta-test held that copy to the renderer's current output. That host document is retired — the generated quick reference and the served error catalog cover what it held — so today no derived artifact lives inline in a hand-authored document. Should one need to again, the shape was `<!-- BEGIN auto-generated <name>; do not hand-edit; regenerate with \`make docs-derived\` -->` … `<!-- END auto-generated <name> -->`, inlined rather than included because GitHub's markdown renderer, the agent-side previewers and the spec rendering paths each handle includes differently or not at all, with a meta-test comparing the region to the renderer.

**The meta-test.** `tests/test_doc_consistency.py::test_common_errors_generated_artifact_matches_doc_ref_output` re-renders the `doc-ref` at test time, extracts the table portion (the rendered output's `| Code | ...` table, stripping frontmatter / heading / intent), and compares it against the committed `docs/_generated/common_errors.md`. A mismatch fails with a "regenerate via `make docs-derived` (or `s0ma docs render docs/_generators/ --output-dir docs/`)" message. This catches:

- Hand-edits to `docs/_generated/common_errors.md` (the comparison is against the renderer's CURRENT output, not against the committed file).
- A new error code registered in `SEVERITY_MATRIX` / `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE` / `ERROR_CODE_DESCRIPTIONS` without re-running `make docs-derived`.

**When to add a new derived doc.** When you author a new hand-authored documentation surface that mirrors registry data (a CLI command listing, a spec rule index, a migration-recipe summary), prefer to author a `doc-ref` declaration under `docs/_generators/` and copy the rendered output into a bracketed region. The source-registry form (`covers: { source: <name> }`) resolves through the derived-source registry (ADR-013) in `codegen/doc_emitter/derived_sources.py`, which is the one place a source name exists — the parser's allow-list and all three renderers read from it. Adding a source is a provider component plus a registry row plus the spec's enumeration sentence; it touches no renderer. The registered names are `error_codes`, `cli_commands`, `document_catalog`, and `package_inventory`.

---

*Created: Milestone 2; expanded through feedback 5–6 (M19c, G1, G7b)*
*Reference: PRD §1.13, DSL Spec §7, plans/feedback_5-6/feedback_5-6_plan.md*
