# s0ma Framework Enhancement: Cross-Project Build and Output Structure

**Date:** March 31, 2026
**Source project:** fr3d (28-module s0ma-dsl agent, 21 test modules)
**Applies to:** s0ma-dsl CLI (`s0ma build`, `s0ma transpile`, `s0ma check`)
**Status:** Proposed
**Related:** `docs/s0ma_py_drift_fix.md` (drift detection — complementary proposal)

---

## 1. Problem Statement

### 1.1 The Build Model Today

`s0ma build` takes a single `project_dir` argument. Its module discovery and cross-module resolution are both scoped to that directory:

```
s0ma build <project_dir> --output-dir <output_dir> --mode <mode>
```

Internally, the pipeline works as follows:

1. **Discovery** — `_discover_s0ma_files(project_dir)` calls `Path(project_dir).rglob("*.s0ma")` to find every `.s0ma` file in the directory tree.
2. **Parse** — Each discovered `.s0ma` file is parsed into a `S0maModule` and added to `module_dict`, keyed by module name.
3. **Resolution** — If `len(module_dict) > 1` or `mode == release`, the `DependencyResolver` runs four phases:
   - Phase 1: Module graph construction and cycle detection.
   - Phase 2: **Export validation** — for each `uses:` entry (e.g., `config.DEFAULT_MODEL`), checks that the target module exists in `module_dict` and exports the referenced component. If the module is missing, emits `DOES_NOT_EXIST`.
   - Phase 3: External validation (`requires:` entries are importable).
   - Phase 4: Usage verification (vestigial imports, evidence rules).
4. **Transpile** — Each module is transpiled to `.py` + `.s0ma.json` + `.s0ma.map`. All output goes to `--output-dir` as a **flat list** (no subdirectory structure preserved).

### 1.2 The Problem: Tests Can't Reference Source Modules

fr3d (and any non-trivial s0ma project) follows the standard Python project layout:

```
fr3d/
├── src/fr3d/               ← source .s0ma files (28 modules)
│   ├── domain/
│   │   ├── config.s0ma
│   │   ├── models.s0ma
│   │   └── ...
│   ├── infrastructure/
│   │   ├── llm_adapter.s0ma
│   │   └── ...
│   ├── application/
│   └── presentation/
├── tests/                   ← test .s0ma files (21 modules)
│   ├── test_domain/
│   │   ├── test_config.s0ma     ← uses: [config.DEFAULT_MODEL, config.TEST_MODEL]
│   │   └── ...
│   ├── test_infrastructure/
│   │   ├── test_llm.s0ma        ← uses: [llm_adapter.AnthropicAdapter, config.TEST_MODEL]
│   │   └── ...
│   └── ...
└── src/fr3d_build/          ← transpiled source output
```

Test modules reference source modules via `uses:`:

```
module test_config
    layer: DOMAIN
    uses: [config.AGENT_NAME, config.DEFAULT_MODEL, config.TEST_MODEL, ...]
```

Running `s0ma build tests/` fails with **97 `DOES_NOT_EXIST` errors** because the resolver's `module_dict` only contains the 21 test modules — it has no knowledge of the 28 source modules in `src/fr3d/`.

Running `s0ma build src/fr3d/` works perfectly (0 errors, 28 modules) because source modules only reference each other.

### 1.3 The Workaround: `s0ma build .` from the Project Root

Running `s0ma build .` from the project root discovers all 49 `.s0ma` files (28 source + 21 test), builds a complete `module_dict`, and resolves all cross-module references successfully — **0 errors**.

But this workaround is unusable in practice because of a second problem:

### 1.4 The Second Problem: Output Flattening

`s0ma build` (and `s0ma transpile`) writes all output files to the `--output-dir` root as a flat list. Directory structure is discarded:

```bash
s0ma build . --output-dir /tmp/build
# Produces:
#   /tmp/build/config.py           ← from src/fr3d/domain/config.s0ma
#   /tmp/build/test_config.py      ← from tests/test_domain/test_config.s0ma
#   /tmp/build/models.py           ← from src/fr3d/domain/models.s0ma
#   /tmp/build/test_llm.py         ← from tests/test_infrastructure/test_llm.s0ma
#   ... all 49 .py files in one flat directory
```

This makes `s0ma build .` unusable for a project where:
- Source modules must go to `src/fr3d_build/` (imported at runtime by `main.py`)
- Test modules must go to their respective `tests/<subdir>/` directories (discovered by pytest)

You can't specify two output directories, and you can't tell the transpiler "source modules go here, test modules go there."

### 1.5 The Double Bind

| Command | Cross-Module Resolution | Output Location | Usable? |
|---------|------------------------|-----------------|---------|
| `s0ma build src/fr3d/ --output-dir src/fr3d_build/` | Source-only (works) | Correct | Yes, for source only |
| `s0ma build tests/ --output-dir tests/` | Test-only (fails: `DOES_NOT_EXIST`) | Correct | No |
| `s0ma build . --output-dir ???` | Full project (works) | Wrong (flat, single dir) | No |

There is no invocation that provides both correct resolution **and** correct output placement for test modules.

### 1.6 Current Workaround

During the fr3d MS 8 full re-transpile, we used:

1. `s0ma build src/fr3d/ --output-dir src/fr3d_build/ --mode dev` — builds source modules with full cross-module resolution.
2. `s0ma transpile tests/<subdir>/ --output-dir tests/<subdir>/ --mode dev` — transpiles test modules per-directory without cross-module resolution.

This produces correct output in the correct locations, but `s0ma transpile` **skips Phase 2-4 entirely** — it doesn't validate `uses:` references. A test module could declare `uses: [nonexistent_module.FakeComponent]` and `s0ma transpile` would happily emit a `.py` file with a dangling import that only fails at runtime.

---

## 2. Root Cause Analysis

The root cause is two assumptions baked into `s0ma build`:

1. **Single-tree assumption:** The entire project lives under one directory tree. Module discovery (`rglob`) and resolution (`module_dict`) are both scoped to that tree. There is no concept of "context modules" — modules that participate in resolution but don't produce output.

2. **Flat-output assumption:** All transpiled output goes to a single flat directory. The relative path of each `.s0ma` file within the project tree is discarded during output generation.

Both assumptions were reasonable for small, single-directory projects. They break for projects with the standard Python layout (`src/` + `tests/` as separate trees) and for projects with nested directory structures.

### 2.1 Where in the Code

Based on analysis of the s0ma-dsl source:

- **Discovery** — `_discover_s0ma_files()` in `cli/main.py` (line ~173): `Path(project_dir).rglob("*.s0ma")`. Scoped to a single directory.
- **Module registry** — `module_dict` built at lines ~641-642: only populated from discovered files.
- **Resolution trigger** — lines ~645-649: `resolve_dependencies(module_dict, ...)` runs against `module_dict` only.
- **Phase 2 check** — `_phase2_export_validation()` in `resolver/dependency.py` (lines ~348-372): `if target_mod not in modules: → DOES_NOT_EXIST`.
- **Output path** — transpiler writes to `output_dir / <module_name>.py` with no subdirectory component.

---

## 3. Proposed Fix 1: `--include` Flag for Context Modules

### 3.1 Summary

Add a repeatable `--include` flag to `s0ma build` and `s0ma check` that specifies additional directory trees to discover modules from. Included modules participate in cross-module resolution (Phase 2-4) but are **not transpiled** — they are read-only context.

### 3.2 User Interface

```bash
# Build tests with source modules as resolution context
s0ma build tests/ --output-dir tests/ --include src/fr3d/ --mode dev

# Check tests against source modules
s0ma check tests/ --include src/fr3d/ --mode dev

# Multiple include paths
s0ma build tests/ --output-dir tests/ --include src/fr3d/ --include lib/shared/ --mode dev
```

### 3.3 Behavior

1. Discover `.s0ma` files in `project_dir` as today — these are the **build targets**.
2. For each `--include` path, also discover `.s0ma` files — these are **context modules**.
3. Parse all discovered files (targets + context) and add to `module_dict`.
4. Run `resolve_dependencies(module_dict)` as today — resolution now sees the full module graph.
5. **Transpile only the build targets.** Context modules are not transpiled and produce no output.

### 3.4 Implementation Sketch

In `cli/main.py`, the build command handler:

```python
# Current:
s0ma_files = _discover_s0ma_files(str(project_dir))

# Proposed:
target_files = _discover_s0ma_files(str(project_dir))
context_files = []
for include_path in args.include or []:
    context_files.extend(_discover_s0ma_files(str(include_path)))

# Parse all into module_dict for resolution
all_files = target_files + context_files
for source_path in all_files:
    module = parse(source_path)
    module_dict[module.module.name] = module
    module_filenames[module.module.name] = str(source_path)

# Resolution sees everything
resolve_dependencies(module_dict, mode=mode, filenames=module_filenames)

# Transpile only targets
target_names = {parse(f).module.name for f in target_files}
for name, module in module_dict.items():
    if name in target_names:
        transpile(module, output_dir)
```

### 3.5 CLI Argument Addition

```python
build_parser.add_argument(
    "--include", "-I",
    action="append",
    default=[],
    help="Additional directory to include for cross-module resolution (not transpiled). Repeatable.",
)
```

### 3.6 Edge Cases

- **Module name collision:** If a context module and a target module have the same name, emit an error: `"Module '<name>' found in both <target_path> and <include_path>."` This catches accidental module name reuse.
- **Circular context:** If context modules reference each other, that's fine — resolution handles cycles already (Phase 1). If context modules reference target modules, that's also valid (the full graph is available).
- **`s0ma check` parity:** The `--include` flag should also work with `s0ma check` so you can validate test modules against source modules without transpiling.

---

## 4. Proposed Fix 2: Preserve Directory Structure in Output

### 4.1 Summary

When transpiling files from a directory tree, preserve the relative path of each `.s0ma` file in the output directory structure. A file at `tests/test_infrastructure/test_llm.s0ma` should produce output at `<output_dir>/test_infrastructure/test_llm.py`, not `<output_dir>/test_llm.py`.

### 4.2 Current Behavior

```bash
s0ma transpile tests/ --output-dir tests/
# Input:  tests/test_infrastructure/test_llm.s0ma
# Output: tests/test_llm.py                          ← WRONG (flattened)
```

### 4.3 Proposed Behavior

```bash
s0ma transpile tests/ --output-dir tests/
# Input:  tests/test_infrastructure/test_llm.s0ma
# Output: tests/test_infrastructure/test_llm.py      ← CORRECT (structure preserved)
```

### 4.4 Implementation Sketch

In the output path computation:

```python
# Current:
output_path = output_dir / f"{module_name}.py"

# Proposed:
relative_path = source_path.relative_to(project_dir)
output_path = output_dir / relative_path.with_suffix(".py")

# Example:
#   project_dir = Path("tests/")
#   source_path = Path("tests/test_infrastructure/test_llm.s0ma")
#   relative_path = Path("test_infrastructure/test_llm.s0ma")
#   output_path = Path("tests/test_infrastructure/test_llm.py")
```

Create parent directories as needed:

```python
output_path.parent.mkdir(parents=True, exist_ok=True)
```

### 4.5 Applies to `s0ma build` and `s0ma transpile`

Both commands should preserve directory structure. The same logic applies to `.s0ma.json` and `.s0ma.map` output files.

### 4.6 Backward Compatibility

- **Single-file transpile** (`s0ma transpile foo.s0ma --output-dir bar/`): No change — the file is at the root, so the relative path is just the filename.
- **Flat directory** (`s0ma build src/fr3d/domain/ --output-dir build/`): No change — all `.s0ma` files are direct children of the source directory.
- **Nested directory** (`s0ma build tests/ --output-dir tests/`): Behavior changes — output now preserves subdirectory structure instead of flattening.

The behavior change only affects projects with nested subdirectory structures under the source root, and in those cases the current behavior (flattening) is almost certainly wrong.

### 4.7 Opt-Out Flag (Optional)

If backward compatibility is a concern, add a `--flat` flag to force the old behavior:

```bash
s0ma build tests/ --output-dir tests/ --flat    # old behavior: flatten
s0ma build tests/ --output-dir tests/            # new default: preserve structure
```

This is likely unnecessary — flattening is a bug, not a feature — but it provides an escape hatch.

---

## 5. Proposed Fix 3: `s0ma build --check` (Drift Detection Mode)

This proposal is detailed in `docs/s0ma_py_drift_fix.md` (Solution A). With Fixes 1 and 2 in place, `--check` becomes significantly more useful because it can operate on the test tree with full cross-module resolution:

```bash
# Verify source modules — no drift?
s0ma build src/fr3d/ --output-dir src/fr3d_build/ --check

# Verify test modules against source context — no drift?
s0ma build tests/ --output-dir tests/ --include src/fr3d/ --check
```

Without Fix 1, `--check` on tests would fail with `DOES_NOT_EXIST` before it could even compare output, making it useless for test modules.

---

## 6. Combined Effect

With all three fixes, the full re-transpile workflow (fr3d MS 8) reduces from a multi-step workaround to two commands with full validation:

### Before (Current Workaround)

```bash
# 1. Build source modules (with cross-module resolution)
s0ma build src/fr3d/ --output-dir src/fr3d_build/ --mode dev

# 2. Transpile tests per-directory (NO cross-module resolution)
s0ma transpile tests/acid_tests/ --output-dir tests/acid_tests/ --mode dev
s0ma transpile tests/test_application/ --output-dir tests/test_application/ --mode dev
s0ma transpile tests/test_domain/ --output-dir tests/test_domain/ --mode dev
s0ma transpile tests/test_infrastructure/ --output-dir tests/test_infrastructure/ --mode dev
s0ma transpile tests/test_presentation/ --output-dir tests/test_presentation/ --mode dev
s0ma transpile tests/fixtures/hello_tool.s0ma --output-dir tests/fixtures/ --mode dev

# 3. Manually verify no drift
git diff
```

**8 commands, no cross-module validation on tests.**

### After (With Fixes 1-3)

```bash
# 1. Build source modules (with cross-module resolution + drift check)
s0ma build src/fr3d/ --output-dir src/fr3d_build/ --mode dev --check

# 2. Build tests with source context (with cross-module resolution + drift check)
s0ma build tests/ --output-dir tests/ --include src/fr3d/ --mode dev --check
```

**2 commands, full cross-module validation on everything, drift detection built in.**

---

## 7. Implementation Priority

| Fix | Effort | Impact | Priority |
|-----|--------|--------|----------|
| **Fix 1: `--include`** | Medium — new CLI arg, modify discovery and resolution, gate transpile output | High — enables test validation against source modules | **P0** |
| **Fix 2: Preserve directory structure** | Low — change output path computation | Medium — eliminates per-directory workaround | **P1** |
| **Fix 3: `--check`** | Medium — transpile to temp, compare, report | Medium — enables CI/CD drift detection | **P2** (see `s0ma_py_drift_fix.md`) |

Fix 1 is the critical path. Without it, `s0ma build` cannot validate test modules — the most common cross-tree reference pattern. Fix 2 is a quality-of-life improvement that becomes essential once Fix 1 is in place (otherwise `s0ma build tests/` with `--include` would produce correct validation but broken output locations). Fix 3 builds on both.

---

## 8. References

- **fr3d MS 8 experience:** `plans/llm_model_consolidation_plan.md` Section 5, MS 8 — full re-transpile where these issues were encountered.
- **Drift detection proposal:** `docs/s0ma_py_drift_fix.md` — complementary `--check` and checksum proposals.
- **s0ma-dsl feedback:** `docs/s0ma-dsl-feedback-2.md` — MS 8 section documents these findings.
- **s0ma-dsl CLI source:** `s0ma-dsl/src/s0ma_dsl/cli/main.py` — `_discover_s0ma_files()`, build handler, check handler.
- **Resolver source:** `s0ma-dsl/src/s0ma_dsl/resolver/dependency.py` — `_phase2_export_validation()` where `DOES_NOT_EXIST` is emitted.

---

*Report v1.0 — March 31, 2026*
*Authored during fr3d LLM Model Consolidation MS 8*
