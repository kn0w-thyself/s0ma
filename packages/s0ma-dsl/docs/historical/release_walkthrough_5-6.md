# s0ma-dsl 0.13.0 — Consumer Walkthrough

**Audience:** maintainers of consumer projects already on s0ma-dsl 0.10.x or
0.11.x who need to land on 0.13.0 cleanly.

**Status:** v0.13.0 (closeout of the feedback 5–6 cycle, 2026-04-29).

## Why this document exists

The 0.11.x → 0.13.0 progression is the cumulative result of the feedback 5–6
work cycle: M1–M20 (the original 24-milestone bulk delivery — see
[`plans/completed/feedback_5-6/feedback_5-6_plan.md`](../plans/completed/feedback_5-6/feedback_5-6_plan.md)),
F1–F4 (post-M20 structural fixes — see
[`plans/completed/feedback_5-6/5-6_follow-up_plan.md`](../plans/completed/feedback_5-6/5-6_follow-up_plan.md)),
and G1–G12 (cleanup pass closing the remaining inventory — see
[`plans/5-6_cleanup_plan.md`](../plans/5-6_cleanup_plan.md)). Three
cross-project verification passes ran against `fr3d` and
`kn0wthyself-website-2` over the cycle: M20 (the original smoke;
[`plans/completed/feedback_5-6/feedback_5-6_smoke_results.md`](../plans/completed/feedback_5-6/feedback_5-6_smoke_results.md)),
F4 ([`plans/5-6_follow-up_smoke_results.md`](../plans/5-6_follow-up_smoke_results.md)),
and G9 ([`plans/5-6_cleanup_smoke_results.md`](../plans/5-6_cleanup_smoke_results.md)).
**Thirteen consumer-side workarounds were eliminated** across the cycle.

This walkthrough is the maintainer's scannable adoption guide. The canonical
"what changed" reference is [`docs/migration_guide.md`](migration_guide.md);
the canonical normative authority is
[`docs/s0ma-dsl-spec-v0.13.0.md`](s0ma-dsl-spec-v0.13.0.md); the per-version
narrative is in [`CHANGELOG.md`](../CHANGELOG.md). This doc is the **what you
should DO about it** overlay — read it first; cross-link out to the canonical
sources for full contracts.

---

## TL;DR

- **Add `[tool.s0ma]` to your `pyproject.toml`** (M1; ADR-005). At minimum
  `source_roots = ["src"]`. Without it the CLI runs in legacy mode with a
  one-line warning per invocation.
- **`s0ma migrate-layout`** (M6a + M6b; ADR-007) brings pre-0.12 build trees
  forward in one idempotent step. Legacy `__s0ma_cache__/` and per-layer
  subdirs are gone; output is now a flat layout with a `build.s0ma.json`
  manifest.
- **Replace `from <layer>.<module>` imports** with
  `from <build_dir_basename>.<module>` everywhere. The build's stdout summary
  prints the right import idiom for your project.
- **Stop hand-setting `[tool.s0ma].build_dir`** for hyphenated / dotted /
  spaced project names — G3 sanitizes them automatically. A pre-G3 explicit
  override that exists *only* to dodge the hyphen bug can be deleted.
- **Disjoint `source_roots` and `test_roots`** (G2). Overlap is now a
  pre-flight `OVERLAPPING_DISCOVERY_ROOTS` error.
- **Stop enumerating empty `__init__.py` files** under
  `[tool.s0ma].bootstrap_files` (G1). They auto-classify as `PACKAGE_MARKER`.
- **Regenerate any `s0ma test-conftest`-emitted `conftest.py`** with
  `s0ma test-conftest --force` (G5). Pre-G5 conftests classify as
  `unrecognized` and surface `STALE_GENERATED_CONFTEST` loudly at pre-flight.
- **Replace any hand-maintained `MODULE_IMPORT_ORDER` list** with
  `bootstrap_imports(build_dir)` (M10). The build records the topological
  order in the manifest; the helper reads it.
- **`s0ma test` is now project-aware.** Delete any
  `PYTHONPATH=...__s0ma_cache__ pytest -o python_files=...` wrapper script
  (M7).
- **Opt into new language surfaces where they help:** `helper` declarations
  (M13), `visibility: TEST` (M8 + ADR-008), `@file()` content embeds (M12),
  `declares_attributes:` + `[tool.s0ma.attribute_budgets]` (M18 + F3),
  `is_page_composer:` (F3), block-scalar metadata (M14).
- **`s0ma inspect <module-name>` and `s0ma topo`** are new diagnostic
  surfaces (M16, M10).

---

## Quick adoption checklist

Walk these in order. Each step calls out what fires loudly if you skip it.

1. **Upgrade s0ma-dsl to 0.13.0.** `pip install -e ../s0ma-dsl` from your
   worktree.

2. **Add a `[tool.s0ma]` table.** Minimum:
   ```toml
   [tool.s0ma]
   source_roots = ["src"]
   ```
   Skip → every CLI invocation prints a one-line legacy-mode warning.

3. **Run `s0ma migrate-layout`** from your project root. Idempotent — safe
   to run twice.
   Skip → pre-0.12 build artifacts shadow new ones; layer-prefixed imports
   silently break.

4. **Update Python imports.** Replace `from <layer>.<module>` (or
   `from <layer> import <module>`) with `from <build_dir_basename>.<module>`.
   The build's stdout summary prints the right idiom.
   Skip → `ModuleNotFoundError` at runtime.

5. **Rename any mismatched-stem modules** so each `.s0ma` file's stem equals
   its declared `module <name>` (M4; ADR-006). Run `s0ma check src/ --mode dev`
   to find them.
   Skip → `MODULE_NAME_STEM_MISMATCH` (error in every mode — no migration
   ladder).

6. **Make `source_roots` and `test_roots` disjoint** (G2). Prefer
   `source_roots = ["src"]` + `test_roots = ["tests"]` at the project top
   level.
   Skip → `OVERLAPPING_DISCOVERY_ROOTS` at project-load time.

7. **Drop pre-G3 `build_dir` overrides** that exist only to dodge hyphens /
   dots / spaces in `[project].name`. The G3 default sanitizer produces the
   same string.
   Skip nothing — works either way; the override is just redundant.

8. **Strip empty `__init__.py` enumerations from `bootstrap_files`** (G1).
   Auto-classification handles them.
   Skip nothing — the entries are merely redundant; `s0ma verify` still
   classifies them as `PACKAGE_MARKER` either way.

9. **Regenerate any `s0ma test-conftest`-emitted `conftest.py`.** Run
   `s0ma test-conftest --force` (G5). The new file carries a four-line banner
   plus body checksum.
   Skip → `STALE_GENERATED_CONFTEST` at the next `s0ma test` invocation.

10. **Replace `MODULE_IMPORT_ORDER` with `bootstrap_imports`** (M10).
    Skip nothing — the hand-maintained list still works, but the build's
    `topological_import_order` is now correct by construction; trust it.

11. **Delete any `PYTHONPATH=...pytest -o python_files=...` wrapper script**
    (M7).
    Skip nothing — works either way; the wrapper is just unnecessary.

12. **(If you adopted M18's `exactly_one_per_page` budget):** mark your page
    composer with `is_page_composer: true` (F3).
    Skip → `NO_PAGE_COMPOSER_DECLARED` (error in every mode).

13. **Run the smoke recipe end-to-end:**
    ```bash
    s0ma check src/ --mode strict
    s0ma build
    s0ma test
    s0ma verify
    ```
    Skip → you're flying blind.

---

## What you must change

The breaking-or-near-breaking changes. Each entry: one paragraph,
before/after where mechanical, and a pointer to the canonical contract.

### 1. Add `[tool.s0ma]` to your `pyproject.toml`

**First appeared:** M1 (0.12.0). **ADR:** ADR-005. **Spec:** §4.13.

Every CLI subcommand resolves a `S0maProject` before dispatching.
`S0maProject.discover()` walks upward from any working directory looking for
the table. Without it, the CLI runs in legacy mode and prints a one-line
warning per invocation.

```toml
# Minimum
[tool.s0ma]
source_roots = ["src"]
```

Full schema (all keys optional; defaults shown):

```toml
[tool.s0ma]
source_roots = ["src"]                # default
test_roots = ["tests"]                # default
build_dir = "myproj_build"            # default: <sanitized [project].name>_build
test_runner = "pytest"                # default; only "pytest" supported today
bootstrap_files = []                  # plain-Python entry points
package_markers = []                  # __init__.py with executable __all__ etc.

[tool.s0ma.attribute_budgets]
# landmark = "exactly_one_per_page"
# route    = "unique_in_project"
```

See [`docs/migration_guide.md` § Action 1](migration_guide.md#action-1--add-tools0ma-to-pyprojecttoml)
for the full key-by-key contract and
[`docs/s0ma-dsl-spec-v0.13.0.md` §4.13](s0ma-dsl-spec-v0.13.0.md) for the
normative authority.

### 2. Disjoint discovery roots

**First appeared:** G2 (0.13.0). **Spec:** §4.13.

`source_roots` and `test_roots` must not overlap. Pre-G2, when the test
directory lived inside a source root, `.s0ma` files under it were discovered
twice and the user saw an opaque `MODULE_NAME_COLLISION` against a file
colliding with itself. Post-G2, the same misconfiguration raises
`OVERLAPPING_DISCOVERY_ROOTS` at project-load time before any subcommand
runs.

**Bad shape (now rejected):**
```toml
[tool.s0ma]
source_roots = ["src"]
test_roots = ["src/myproj/tests"]   # nested inside source root
```

**Two clean shapes:**
```toml
# Option A — top-level peer directories (preferred)
[tool.s0ma]
source_roots = ["src"]
test_roots = ["tests"]
```
```toml
# Option B — narrow source_roots to layer subdirectories
[tool.s0ma]
source_roots = [
    "src/myproj/application",
    "src/myproj/domain",
    "src/myproj/presentation",
]
test_roots = ["src/myproj/tests"]
```

The same disjoint rule applies *within* each list (two `source_roots` where
one is a subpath of the other), and to identity (the same path declared in
both lists).

**If you skip:** `OVERLAPPING_DISCOVERY_ROOTS` at project-load time, before
any subcommand runs. The diagnostic names every offending pair plus the two
clean-config remediation options.

### 3. Single flat build layout

**First appeared:** M6a + M6b (0.12.0). **ADR:** ADR-007. **Spec:** §4.14.

Build output is now a single flat layout at `<build_dir>/`. The pre-0.12
`__s0ma_cache__/` directory and per-layer subdirectories
(`presentation/`, `application/`, `domain/`, `infrastructure/`) are no longer
emitted. Every successful build emits a single `__init__.py` at the build
root (so the directory is a real Python package), every transpiled module
lands directly at `<build_dir>/<module>.py`, and a single `build.s0ma.json`
manifest names everything.

**Pre-0.12 layout:**
```
<build_dir>/
    __s0ma_cache__/
        presentation/foo.py
        application/bar.py
        domain/baz.py
```

**Post-0.12 layout:**
```
<build_dir>/
    __init__.py                # auto-emitted
    build.s0ma.json            # manifest
    foo.py                     # every module flat
    foo.s0ma.json
    foo.s0ma.map
    bar.py
    bar.s0ma.json
    ...
```

Hash-based incremental-rebuild bookkeeping moved to a hidden `.s0ma.cache/`
directory rooted at the build's input/output anchor — never on `sys.path`,
never importable, may be deleted at any time.

**Migration:** run `s0ma migrate-layout` from your project root. It cleans
legacy artifacts and runs a fresh `s0ma build`. Idempotent. Then update
imports from `from <layer>.<module>` to `from <build_dir_basename>.<module>`.
The new build's stdout summary prints the import idiom.

**If you skip migrate-layout:** layer-prefixed imports silently break;
pre-0.12 build artifacts may shadow new ones until manually deleted.

### 4. Bootstrap files declared, not inferred

**First appeared:** M11 (0.12.0). **Spec:** §4.13.

List every plain-Python entry point under `[tool.s0ma].bootstrap_files`.
`s0ma verify` classifies declared entries as `BOOTSTRAP` (informational,
hidden by default) instead of the noisy `UNKNOWN`. The runtime bridge does
not register them as components.

```toml
[tool.s0ma]
bootstrap_files = [
    "src/myproj/main.py",
    "src/myproj/__main__.py",
    "src/myproj/bootstrap/startup.py",
]
```

Bootstrap files that do not exist on disk yet produce a warning, not an
error.

**If you skip:** every plain-Python entry point surfaces as `UNKNOWN` in
`s0ma verify` output, drowning real warnings.

### 5. Don't enumerate empty `__init__.py` (G1)

**First appeared:** G1 (0.13.0). **Spec:** §4.13.

`s0ma verify` auto-classifies any `__init__.py` whose body is empty,
whitespace only, or a single module-level docstring as `PACKAGE_MARKER` —
informational, hidden from default text output, no configuration required.
The pre-G1 workaround (listing every layer's `__init__.py` under
`[tool.s0ma].bootstrap_files`) is retired.

**Action:** strip empty `__init__.py` entries from `bootstrap_files`. Keep
only real plain-Python entry points (e.g. `src/myproj/main.py`).

For unusual cases — an `__init__.py` carrying `__all__` re-exports or other
executable content the author wants acknowledged as a marker rather than
reported as `UNKNOWN` — declare it under the new `[tool.s0ma].package_markers`
key:

```toml
[tool.s0ma]
package_markers = ["src/myproj/exports/__init__.py"]
```

A file appearing in both `bootstrap_files` and `package_markers` raises
`CONFLICTING_PACKAGE_DECLARATION` at project-load time.

**Note:** an `__init__.py` carrying executable content like
`__version__ = "0.1.0"` does **not** auto-classify — the auto-classifier
deliberately only handles structurally-empty bodies. Add such files to
`bootstrap_files` (acknowledged plain-Python entry point) or
`package_markers` (acknowledged package marker with executable content)
based on intent.

**If you skip:** harmless — `s0ma verify` will still classify empty
`__init__.py` entries as `PACKAGE_MARKER` whether or not they're listed
under `bootstrap_files`. The redundant entries are just noise in your
config.

### 6. Build dir derives from project name (G3)

**First appeared:** G3 (0.13.0). **Spec:** §4.13.

The default `build_dir` derivation now sanitizes every non-word character
(`\W`) in `[project].name` to `_` before appending `_build`. So
`[project].name = "kn0wthyself-website-2"` produces
`kn0wthyself_website_2_build/` — a valid Python identifier the runtime
bridge can import via `from kn0wthyself_website_2_build import <module>`.

Pre-G3, the default was the literal `f"{project_name}_build"` and consumers
with hyphenated names had to set `build_dir` explicitly to avoid a silent
`ModuleNotFoundError` at runtime.

**Action:** if your `[tool.s0ma]` carries a `build_dir = "<sanitized>_build"`
line that exists only because of the pre-G3 silent-broken-import bug,
**delete the line.** The G3 default produces the same string.

**Don't delete** if you genuinely want a custom build dir (e.g. `_build/`,
`dist_s0ma/`).

**Two cases still need explicit `build_dir`:**

1. `[project].name` starts with a digit (`123foo`) — Python identifiers
   can't start with a digit.
2. `[project].name` sanitizes to the empty string (defensive — PEP 621
   requires non-empty names so this is rare).

Both raise `INVALID_PROJECT_NAME_FOR_BUILD_DIR` at project-load time.
Explicit `build_dir` values are validated the same way: the directory's
last path component must be a valid Python identifier.

**If you skip:** harmless — your existing override still works (it's just
redundant).

### 7. Conftest staleness — regenerate after upgrading

**First appeared:** G5 (0.13.0). **Spec:** §4.15.

Every `conftest.py` emitted by `s0ma test-conftest` now carries a four-line
banner identifying the s0ma-dsl version that produced it plus a SHA256
content checksum of the body:

```python
# Generated by s0ma-dsl 0.13.0
# Content checksum: 88fe08...d3cc
# Do not hand-edit unless you know what you're doing.
# Run `s0ma test-conftest --force` to regenerate after upgrading s0ma-dsl.
```

`s0ma test` reads the banner via the new `_classify_conftest` helper before
invoking pytest. Five states surface:

| State | Outcome |
|---|---|
| `absent` | `s0ma test` proceeds (no conftest needed). |
| `current` | `s0ma test` proceeds (banner version + checksum match). |
| `untouched_stale` | Auto-regenerated with a one-line stderr notice (registry-driven; empty in 0.13.0 — see fail-safe note below). |
| `customized_stale` | Refused; `STALE_GENERATED_CONFTEST` surfaces. |
| `unrecognized` | Refused; `STALE_GENERATED_CONFTEST` surfaces. |

Pre-G5 conftests have no banner, so they classify as `unrecognized` →
`STALE_GENERATED_CONFTEST`. The fail-safe choice is deliberate: silent
rewrites of files that may carry hidden customizations are a worse failure
mode than a loud one-time error that asks the user to inspect, preserve,
and regenerate.

**Action:**

```bash
s0ma test-conftest --force
```

`--force` regenerates unconditionally for the "I customized intentionally
and want a clean regeneration after preserving the customization" flow.
The default `s0ma test-conftest` (no flag) refuses to overwrite — mirrors
`s0ma new`'s safety default.

**If you skip:** the next `s0ma test` invocation surfaces
`STALE_GENERATED_CONFTEST` (error in every mode) at pre-flight time with
the exact remediation message. The pre-G5 failure mode (opaque
`AttributeError` at pytest import time, several command invocations
downstream from the cause) is gone — G5 closed the detection mechanism
loudly.

### 8. The conftest patches `s0ma_dsl.runtime_bridge.*` now (G10)

**First appeared:** G10 (0.13.0).

The `s0ma test-conftest`-emitted body patches
`s0ma_dsl.runtime_bridge.registration.register_module` (the s0ma-dsl
runtime bridge), not `s0ma.runtime_bridge.registration.register_module`
(the framework path that has never been correct). Python's `unittest.mock`
resolves patch targets where they are *used*, not where they are defined;
transpiled modules in your `<build_dir>/` import `register_module` from
`s0ma_dsl.runtime_bridge.registration`.

**Action:** if you regenerate via `s0ma test-conftest --force` (G5 step
above), the right patch path lands automatically. If you've hand-edited
your conftest, change every
`patch("s0ma.runtime_bridge.registration.register_module", ...)` to
`patch("s0ma_dsl.runtime_bridge.registration.register_module", ...)`.

**If you skip and you hand-edit:** every test using the
`mock_s0ma_runtime` fixture fails at setup with
`AttributeError: module 's0ma' has no attribute 'runtime_bridge'`. The G5
classifier will catch it on the next `s0ma test` because the body checksum
will mismatch — the failure mode is loud, not silent.

### 9. Sanitize cross-source-root tests (G4)

**First appeared:** G4 (0.13.0). **Spec:** §4.15.

For projects with multiple sibling source roots (e.g.
`source_roots = ["src/myproj/application", "src/myproj/domain",
"src/myproj/presentation"]`), `s0ma test`'s per-source-root build pass now
threads sibling roots through `--include` automatically. A `uses: domain.X`
reference from `application/foo.s0ma` resolves cleanly without any
hand-rolled `-I`-chained build script.

Pre-G4, the per-root build invoked with `include_dirs=[]` and the
cross-module resolver raised `DOES_NOT_EXIST` against the sibling-root
target. The workaround was to hand-run each layer's
`s0ma build -I <prior-layer> ...` invocations in dependency order, then
invoke pytest directly against the resulting build dir.

**Action:** if you have a hand-rolled per-layer build script that exists
only because of this bug, delete it. `s0ma test` now does the right thing
unmodified.

**If you skip:** your hand-rolled script still works (it's just
unnecessary).

### 10. Module-stem alignment (M4)

**First appeared:** M4 (0.12.0). **ADR:** ADR-006. **Spec:** §4.5.3.

Every `.s0ma` source file's filename stem must equal the declared
`module <name>`. The cache key, emitted Python filename, and `uses:`
import paths all derive from `module.name` — the canonical IR identity, not
the source file's stem.

**Action:** run `s0ma check src/ --mode dev` to find any mismatches. Each
report names the file. Pick whichever rename surfaces the canonical name
better (rename the file to match the declaration, or rename the declaration
to match the file) — both are mechanically safe.

**If you skip:** `MODULE_NAME_STEM_MISMATCH` at error severity in **every**
strictness mode — no migration ladder. The fix is one-time per project.

### 11. `s0ma test` argument shape (M7)

**First appeared:** M7 (0.12.0). **Spec:** §4.15.

`s0ma test`'s positional `test_dir` is optional (defaults to every
configured `test_root`). `--source`, `--output-dir`, and the
greedy-positional `pytest_args` flag are removed; pytest args pass after a
literal `--` separator instead.

**Pre-0.12:**
```bash
s0ma test tests/ --source src/ --output-dir tests/ -- -v
```

**Post-0.12:**
```bash
s0ma test -- -v
```

**Action:** update any CI scripts / Makefiles invoking `s0ma test`. The
new form is shorter and the `--`-passthrough is reliable.

**If you skip:** invocations with the old flag shape error out cleanly with
an argparse usage message.

---

## What you can opt into

These are additive — no existing `.s0ma` source needs modification to keep
working. Adopt them where they improve your project's self-model.

### `helper` declaration kind (M13)

**First appeared:** M13 (0.12.0). **ADR:** ADR-008. **Spec:** §4.4a.

Module-private functions that live at module scope, are not registered as
components, but are introspectable via `s0ma inspect`. By convention,
helper names start with an underscore.

```
helper _normalize_error :: APPLICATION
    intent: |
        Normalise an upstream API error into the project's canonical
        ErrorEnvelope shape.
    ---
    def _normalize_error(raw: dict) -> ErrorEnvelope:
        return ErrorEnvelope(
            code=raw.get("code", "UNKNOWN"),
            message=raw.get("message", ""),
        )
```

**Scoping rules:**

- Intra-module access is unconstrained.
- Cross-module access is allowed only from modules that contain at least
  one `test` declaration (so test modules can reach helpers in any module
  for unit-testing).
- Production cross-module access raises `HELPER_PRIVATE_TO_MODULE` (error
  in every strictness mode).

**When to use:** when feedback-5's MS 1 surfaced ~160 lines of nested
helpers, and feedback-6's MS 13/16 surfaced D-36's recorder-duplication
pattern, the right answer was a fourth declaration kind. Helpers replace
copy-pasted private functions across test modules and production-side
recorder duplication.

### `visibility: TEST` (M8)

**First appeared:** M8 (0.12.0). **ADR:** ADR-008. **Spec:** §4.10.1, §5.

A third visibility level for nerves and cells. TEST components are
accessible to test modules in any project module (a module qualifies as a
test consumer when it contains at least one `test` declaration) but hidden
from production code in other modules. They are exempt from the public
export surface — not in `module.exports`, exempt from `NOT_EXPORTED`, and
never in the emitted `__all__`.

```
nerve escape_html :: PRESENTATION
    kind: FUNCTION
    visibility: TEST
    intent: "Escape HTML special characters."
    expects: "string input"
    guarantees: "returns escaped string"
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def escape_html(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;")
```

**When to use:** for helpers production callers shouldn't see but tests
need to exercise directly (HTML escaping, prompt formatters, raw JSON
serializers). Replaces the copy-paste-helper-into-test workaround
documented across feedback-5.5 M02–M07. Cross-module production consumption
fires `TEST_VISIBILITY_VIOLATION` (error in every strictness mode).

### `@file()` content embeds (M12)

**First appeared:** M12 (0.12.0). **Spec:** §4.2.2.

Embed external files (HTML, SQL, prompts, JSON schemas) by reference
rather than inline as a triple-quoted body. The transpiler reads the file
at build time, hashes it for cache invalidation, and lists it in
`build.s0ma.json` under `external_content_files`.

```
cell VIZ_TEMPLATE :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Self-contained HTML5 viz template."
    schema: "string of valid HTML5"
    content: @file("templates/viz.html")
```

Restricted to `kind: CONSTANT` in 0.13.0; combining with an inline `---`
body or applying to other cell kinds is a `PARSE_ERROR`.
`EMBEDDED_FILE_NOT_FOUND` (error in every mode) fires when the path does
not resolve.

**When to use:** when you have large CONSTANT cells with HTML / SQL /
prompt templates / JSON schemas. Closes the kn0wthyself viz-template case
(the original 1010-line `.s0ma` file with ~990 lines of embedded
HTML/CSS/JS).

### `is_page_composer:` and attribute budgets (M18 + F3)

**First appeared:** M18 (0.12.0); F3 (0.12.0 follow-up). **Spec:** §4.1.6,
§4.13.

Domain-agnostic mechanism for cross-component structural-uniqueness
validation. A nerve declares zero or more `<namespace>:<attribute>` strings;
a project opts into enforcement by mapping a namespace under
`[tool.s0ma.attribute_budgets]`.

```
nerve compose_self_page :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Top-level page composer for /self."
    expects: "Body content."
    guarantees: "Returns a full HTML page."
    evaluates_at: FUNCTION_BOUNDARY
    is_page_composer: true
    declares_attributes: ["route:GET /self"]
    ---
    def compose_self_page(body: str) -> str:
        return render_header() + render_main(body) + render_footer()


nerve render_self_header :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Render the self-page header."
    expects: "no input"
    guarantees: "returns header HTML"
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["landmark:header"]
    ---
    def render_self_header() -> str:
        return "<header>...</header>"
```

```toml
[tool.s0ma.attribute_budgets]
landmark = "exactly_one_per_page"
route    = "unique_in_project"
css_class = "warn_on_duplicate"
```

Three budget shapes:

- `exactly_one_per_page`: one occurrence per page composer's reachable
  nerve set. **Requires** at least one nerve marked
  `is_page_composer: true` (F3) — otherwise `NO_PAGE_COMPOSER_DECLARED`
  fires in every mode.
- `unique_in_project`: at most one project-wide.
- `warn_on_duplicate`: warning-severity duplicates.

Violations surface as `ATTRIBUTE_BUDGET_VIOLATION`.

**When to use:** when you have a cross-component invariant the type system
can't express (one `<header>` per page, one `route:GET /foo` project-wide,
unique CSS class names). Generalises the original `declares_landmarks:`
request from feedback-5.5 (the fr3d two-`<nav>` regression that only
surfaced at runtime).

**F3 migration note:** if you adopted M18's `exactly_one_per_page` shape
before F3 landed, you must now mark your page composer with
`is_page_composer: true`. M18's previous heuristic ("a page is a top-level
module in the `uses:` graph") was opaque and had documented edge cases —
test modules looked like top-level pages, projects with no `uses:` edges
had every module flagged, and fully-circular graphs silently no-opped. F3
replaces the heuristic with explicit declaration. See
[`docs/migration_guide.md` § M18 attribute_budgets: explicit page composers
required (F3)](migration_guide.md#m18-attribute_budgets-explicit-page-composers-required-f3)
for the full recipe.

### Block-scalar metadata (M14)

**First appeared:** M14 (0.12.0). **Spec:** §2.1.1.

Every string-valued metadata field — `intent`, `expects`, `guarantees`,
`schema`, `invariants`, `priors`, `on_anomaly` — accepts YAML's literal-
block-scalar form (`|` followed by indented content). Multi-line content
is preserved exactly through the IR, the generated Python, and
`s0ma inspect`.

```
nerve render :: PRESENTATION
    intent: |
        Render a value into a presentation-safe string.

        Multi-line content is preserved exactly through the IR, the
        generated Python, and `s0ma inspect`.
    expects: |
        Preconditions on input:
          - value is non-null
          - value is a str-coercible scalar
    guarantees: |
        Postconditions on output:
          - returns a str
          - HTML-special characters are escaped
```

The smallest interior indent is the de-indenting baseline; relative
sub-indentation is preserved. The folded form (`>`) and chomping
indicators (`|+`/`|-`) are out of scope. Empty blocks error with a clear
`PARSE_ERROR`.

**When to use:** when your `intent:` / `expects:` / `guarantees:` is
multi-sentence prose, has bulleted lists, or carries sub-indented
examples. Resolves feedback-5.5 M02/M03/M05.

### `s0ma inspect` by module name + `--all` (M16)

**First appeared:** M16 (0.12.0). **Spec:** §4.15.

Drop the `.s0ma.json` path; just pass the module name. The IR path is
resolved automatically via `[tool.s0ma].build_dir`.

```bash
s0ma inspect signals_models       # by module name
s0ma inspect --all                # one-line-per-module project survey
s0ma inspect --all --format json  # machine-consumable
```

The legacy `s0ma inspect <full_path>/<module>.s0ma.json` form continues to
work for ad-hoc external IR inspection.

### `s0ma topo` (M10)

**First appeared:** M10 (0.12.0). **Spec:** §4.14.

Print the project's topological module import order, one module per line,
or as JSON.

```bash
s0ma topo                         # one module per line
s0ma topo --format json           # array of strings
```

Useful for diagnostics or scripts. The same order is recorded in
`build.s0ma.json` under `topological_import_order` and consumed by
`bootstrap_imports(build_dir)`.

Cyclic `uses:` graphs raise `MODULE_DEPENDENCY_CYCLE` at build time
(error in every mode), not as a runtime `ImportError`.

### Bootstrap pattern (M10)

**First appeared:** M10 (0.12.0).

Replace any hand-maintained `MODULE_IMPORT_ORDER` tuple in
`bootstrap/startup.py` with a one-line call:

**Pre-0.12:**
```python
MODULE_IMPORT_ORDER = (
    "domain_constants",
    "domain_types",
    "application_services",
    "presentation_renderers",
)

def startup() -> dict:
    build_dir = Path(__file__).parent.parent.parent / "myproj_build"
    sys.path.insert(0, str(build_dir))
    imported = {}
    for name in MODULE_IMPORT_ORDER:
        imported[name] = importlib.import_module(name)
    return imported
```

**Post-0.12:**
```python
from pathlib import Path
from s0ma_dsl.runtime import bootstrap_imports

def startup() -> dict:
    build_dir = Path(__file__).parent.parent.parent / "myproj_build"
    return bootstrap_imports(build_dir)
```

`bootstrap_imports(build_dir)` reads `build.s0ma.json`, idempotently
inserts `build_dir` at the head of `sys.path`, imports each module via
`importlib.import_module` in topological order, and returns the resulting
`dict[str, ModuleType]`. The order is computed via Kahn's algorithm with
alphabetical tie-breaking — deterministic across runs.

### Documentation subsystem (0.11.x + G7a/b)

**First appeared:** 0.11.0; refined by G7a/b (0.13.0). **ADR:** ADR-010.
**Spec:** §4.12.

Three declaration types — `doc-ref` (registry projection), `doc-guide`
(narrative with `{{...}}` references and `asserts:`), and `example`
(executable demonstration) — bring documentation under the same
grammar-level enforcement as code.

**G7a:** `doc-ref` accepts `covers: { source: error_codes }` to derive a
Markdown table from the canonical error-code registry
(`SEVERITY_MATRIX | OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE` plus
`ERROR_CODE_DESCRIPTIONS`). The brace form is the structural
discriminator, distinct from the historic
`covers: [nerve where ...]` list-of-filters form.

**G7b:** the s0ma-dsl repo's own Common Errors table in
`docs/s0ma-dsl_quick_reference.md` is now derived from the registry — see
`docs/_generators/common_errors.s0ma` and `docs/_generated/common_errors.md`
for the in-repo precedent.

**When to use:** any consumer-side doc-ref that derives a registry table
from a non-component source. Adding a new derived source is a one-line
grammar change plus a renderer branch — see ADR-010.

### Inspect-able introspection

The runtime is queryable. Several surfaces are now stable:

- **`build.s0ma.json`**: the canonical "what was built and how to import
  it" manifest. Schema `s0ma-build-manifest@1`. Lists every module
  (absolute source path, output / IR / source-map basenames,
  `sha256:<hex>` source and output hashes), plus top-level `project`,
  `build_dir`, `transpiler_version`, `built_at`,
  `topological_import_order`, and (M12) `external_content_files`.
- **`bootstrap_imports(build_dir)`**: reads the manifest, returns
  `dict[str, ModuleType]`. The library entry point for runtime
  introspection.
- **`s0ma inspect <module>`** + `--all`: print component counts, layer,
  visibility per module.
- **`s0ma topo`**: print the import order.

Spec §4.14 carries the full manifest schema reference.

---

## What you no longer need

The cumulative tally across M20 + F4 + G9 — **13 consumer-side workarounds
eliminated**:

1. **Custom `conftest.py` mocking the runtime bridge** so pytest can import
   transpiled modules. Eliminated by M7.
2. **Hand-rolled `pytest` wrapper scripts** with
   `PYTHONPATH=...__s0ma_cache__ pytest -o python_files=...`. Eliminated by
   M7.
3. **`python_files = test_*.py *_tests.py` overrides** in `pyproject.toml`
   or `pytest.ini`. Eliminated by M7.
4. **`--output-dir <test_dir>` invocations** that emitted `.py` next to
   `.s0ma` to dodge pytest discovery. Eliminated by M7.
5. **`-o`-after-`--` foot-gun workarounds.** Eliminated by M7.
6. **`requires: [pytest]` lines** added only to silence the runner.
   Eliminated by M15.
7. **Hand-maintained `MODULE_IMPORT_ORDER` lists.** Eliminated by M10.
8. **Per-layer `__init__.py` shims** for the legacy layout. Eliminated by
   M6a/b.
9. **`pyproject.toml` `[tool.pytest.ini_options].norecursedirs = ["__s0ma_cache__", ...]`**
   defending against `.s0ma.cache/` collection. Eliminated by F2.
10. **Moving `.s0ma` files aside** to skirt M17's `CONSTANT_NAME_MISMATCH`
    false-positive on multi-line CONSTANT bodies. Eliminated by F1.
11. **Enumerating every layer's `__init__.py`** under
    `[tool.s0ma].bootstrap_files` to silence `UNKNOWN` noise. Eliminated by
    G1.
12. **Setting `[tool.s0ma].build_dir` explicitly** to dodge hyphenated
    default. Eliminated by G3.
13. **Hand-running per-layer `s0ma build -I <prior-layer>`** then invoking
    pytest directly, when using multiple sibling source roots. Eliminated
    by G4.

See the smoke-results docs (M20 / F4 / G9) for the per-pass attribution.

---

## Per-project notes

### fr3d

**Path:** `/Users/main/Projects/kn0wthyself/fr3d`. **Verified at:** G9
(2026-04-29).

`[tool.s0ma]` config that works on G9-vintage 0.13.0:

```toml
[tool.s0ma]
source_roots = ["src"]
test_roots = ["tests"]
bootstrap_files = [
    "src/fr3d/main.py",
    "src/fr3d/__main__.py",
    "src/fr3d/bootstrap/startup.py",
]
```

**State post-G9:**

- `s0ma check src/ --mode strict`: 12 errors (all real fr3d-side findings;
  see "Remaining consumer-side issues" below). Build aborts on the same
  PARSE_ERROR.
- `s0ma verify`: 1 UNKNOWN — down from 7 in F4 (G1 auto-classifies the 6
  empty package-marker `__init__.py` files automatically). The remaining
  UNKNOWN is `src/fr3d/__init__.py`, which carries
  `__version__ = "0.1.0"` plus a docstring; the executable assignment
  correctly disqualifies auto-classification. Resolve by adding the file
  to `[tool.s0ma].bootstrap_files` (acknowledged plain-Python entry point)
  or `package_markers` (acknowledged package marker with `__version__`)
  based on intent.

**Remaining consumer-side issues** (DSL-side correctly surfaces them; not
DSL bugs):

1. **`cli.s0ma:441` PARSE_ERROR.** A nested-quote f-string syntax that
   only parses on Python 3.12+. Real fr3d-side bug — fix the body to use
   triple-quoted strings or escape the inner quotes properly. The DSL
   correctly refuses to emit Python that won't parse on the project's
   declared `requires-python`.
2. **`_normalize_error` cross-module collision.** Two production modules
   (`google_calendar_integration` and `notion_integration`) define a
   top-level helper named `_normalize_error`. Both transpile to the same
   registered name; the runtime bridge raises `RegistrationError`. Real
   fr3d-side architectural collision. Fix by either (a) renaming one (or
   both) helpers to module-distinct names, or (b) promoting both to a
   `helper` declaration in a shared lower-layer module if the
   functionality is genuinely shared. F2's `.s0ma.cache/` exclusion
   exposed the underlying issue; pre-F2 it was masked by double-collection
   of the same helper.
3. **`MISSING_PACKAGE` × 2 (croniter, bs4).** The project's environment
   doesn't have these installed. Real environment gap. Fix by adding the
   packages to your dev environment, or by stripping the `requires:`
   entries if the body never imports them.
4. **`CROSS_LAYER_DEPENDENCY` × 1 (orchestrator → llm_adapter).** A
   `uses:` reference targets a higher-layer module than the consuming
   module's layer permits. Real layer-discipline violation. Fix by either
   moving the consuming module to a lower layer or restructuring the
   dependency to invert the direction.
5. **`VESTIGIAL_IMPORT` × 8.** Across `viz_cli.s0ma`, `plugin_loader.s0ma`,
   `self_model.s0ma`, `viz_graph_builder.s0ma`, `context.s0ma`,
   `orchestrator.s0ma`. Each declares a `requires:` or `uses:` entry that
   has no body-level evidence of use. Fix by removing the unused entries.

The DSL-side smoke through `s0ma test` is single-source-root (so G4's
cross-source-root resolution is not exercised against fr3d) and there's
no `conftest.py` in fr3d's project root (so G5's staleness pre-flight is
not exercised either). Both are verified end-to-end against
kn0wthyself-website-2 below.

### kn0wthyself-website-2

**Path:** `/Users/main/Projects/kn0wthyself/kn0wthyself-website-2`.
**Verified at:** G9 (2026-04-29).

`[tool.s0ma]` config that works on G9-vintage 0.13.0 (note: explicit
`build_dir` override is **no longer required** post-G3 — sanitization
produces the same string automatically):

```toml
[tool.s0ma]
source_roots = [
    "src/kn0wthyself_site/application",
    "src/kn0wthyself_site/domain",
    "src/kn0wthyself_site/presentation",
]
test_roots = ["src/kn0wthyself_site/tests"]
bootstrap_files = [
    "src/kn0wthyself_site/main.py",
    "src/kn0wthyself_site/bootstrap/startup.py",
]
```

**State post-G9:**

- `s0ma check src/kn0wthyself_site/ --mode strict`: 0 errors (clean, 32
  files checked).
- `s0ma build src/kn0wthyself_site/`: PASS — 32 modules emitted to
  `kn0wthyself_site_build/`. G3's sanitization handles the hyphenated
  `[project].name = "kn0wthyself-site"` automatically.
- `s0ma verify`: 1 UNKNOWN — down from 2 in F4. The remaining UNKNOWN is
  `src/kn0wthyself_site/__init__.py` (carries `__version__`); same shape
  as fr3d.
- `s0ma test`: G5 fires `STALE_GENERATED_CONFTEST` on the M20-vintage
  conftest with the right `--force` remediation. Post-`s0ma test-conftest
  --force`, the build steps run cleanly through G4's cross-source-root
  resolution. Pytest collection then fails on a real consumer-side issue
  — the `fastapi` env gap (see below).

**G3 closure verified end-to-end** with the F4 explicit `build_dir = "kn0wthyself_site_build"`
override **removed** from the project's `pyproject.toml`. The default
sanitization produces the same string the explicit override did.

**Remaining consumer-side issues** (DSL-side correctly surfaces them; not
DSL bugs):

1. **`fastapi` env gap during `s0ma test`.** Pytest collection fails on
   `fastapi` import errors. Real environment gap. Fix by adding `fastapi`
   to your dev environment.
2. **The same `__version__`-bearing `__init__.py` UNKNOWN** described
   above. Resolve by acknowledging the file under `bootstrap_files` or
   `package_markers` based on intent.

**G4 closure verified end-to-end** by the per-source-root build pass for
`application/`, `domain/`, `presentation/` running cleanly (pre-G4, the
missing sibling-include threading produced `DOES_NOT_EXIST` against
`application/builders_composer.s0ma`'s `uses: domain.metadata_content.PageMetadata`
reference). **G5 closure verified end-to-end** by the M20-vintage
conftest classifying as `unrecognized` and the regenerated body carrying
the four-line banner.

---

## What's not in this document

- **Tier B/C/D deferred items** from the cleanup plan triage (B1 the
  `is_page_composer:` IR shape question; C1 framework
  `s0ma.import_hook` consolidation; D1–D7 smaller historical open
  questions). See [`plans/5-6_last_items.md`](../plans/5-6_last_items.md)
  for the full triage.
- **Release-prep details** (the version bump, changelog consolidation,
  spec rename). See [`docs/release_checklist.md`](release_checklist.md) and
  the G11 deviations entry.
- **The s0ma framework's runtime-bridge consolidation** — that's
  cross-repo work tracked under C1.
- **v2 work** — see Appendix B of the spec.
- **Implementation specifics** beyond what the migration guide covers.
  This walkthrough is the consumer's adoption overlay; the migration
  guide is the canonical "what changed" reference.

---

## Where to go next

- [Quick reference](s0ma-dsl_quick_reference.md) — one-page survival guide
  with the schema tables and common-errors table.
- [Migration guide](migration_guide.md) — full per-version walkthrough
  (canonical "what changed").
- [Spec v0.13.0](s0ma-dsl-spec-v0.13.0.md) — normative language authority.
- [CHANGELOG.md](../CHANGELOG.md) — per-version narrative (0.13.0 +
  0.12.0 cover the feedback 5–6 cycle).
- [ADRs](adr/) — especially:
  - [ADR-005](adr/ADR-005-project-discovery.md) (M1: declarative project
    model)
  - [ADR-006](adr/ADR-006-canonical-module-identity.md) (M4: canonical
    module identity)
  - [ADR-007](adr/ADR-007-single-build-layout.md) (M6a/b: single flat
    build layout)
  - [ADR-008](adr/ADR-008-test-visibility.md) (M8: `visibility: TEST`)
  - [ADR-009](adr/ADR-009-canonical-body-storage.md) (F1: canonical body
    storage)
  - [ADR-010](adr/ADR-010-derived-doc-targets.md) (G7a/b: derived doc
    targets)
- [Patterns guide](references/dsl_patterns_guide.md) — SERVICE patterns,
  EXCEPTION/CONSTANT cells, abstract adapters, bootstrap conventions.
- [Coding agent handbook](coding_agent_handbook.md) — handbook for agents
  working on the transpiler itself.
- [Smoke results](../plans/5-6_cleanup_smoke_results.md) — G9's
  per-project verdict snapshot (the empirical basis for the per-project
  notes above).
