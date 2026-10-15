# ADR-005: Declarative Project Discovery via `[tool.s0ma]`

**Status:** Accepted
**Date:** 2026-04-28
**Context:** Feedback 5–6 plan, Milestone 1 — Project discovery: `[tool.s0ma]` in `pyproject.toml`
**References:** feedback-5.5 (output-layout incoherence), feedback-6 CRIT-3 (`s0ma test` cannot find `src/`), DSL Spec §4.13 (Project Configuration), `docs/migration_guide.md` ("0.11.0 → 0.12.0: Adding `[tool.s0ma]`")

---

## Decision

Every s0ma DSL CLI subcommand resolves a **declarative project model** before dispatching. The project is rooted at the consumer's `pyproject.toml`, configured via a `[tool.s0ma]` table, and produced by `S0maProject.discover(start)`, which walks upward from a start directory (default: `Path.cwd()`, overridable with the global `--project-root` flag) until it finds a `pyproject.toml` containing the `[tool.s0ma]` table.

The recognised schema is:

```toml
[tool.s0ma]
source_roots = ["src"]                # default: ["src"]
test_roots = ["tests"]                # default: ["tests"]
build_dir = "<project_name>_build"    # default: derived from [project].name
bootstrap_files = []                  # default: []
```

When no `[tool.s0ma]` table is reachable, the CLI falls back to a synthetic project rooted at the working directory and emits a one-line warning. Synthetic projects carry `synthetic=True` so feature code can short-circuit project-aware behaviour.

## Context

Across feedback 5.5 and feedback 6, two related classes of pain recurred at every consumer-project handoff:

1. **Output-layout incoherence (feedback-5.5).** Every consumer reinvented conventions for "where does the source live, where does the build go, which `.py` files are the bootstrap exception?" Each `s0ma transpile` and `s0ma build` invocation passed a different combination of `--output-dir`, `--source`, and ad-hoc include paths.
2. **`s0ma test` cannot find `src/` (feedback-6 CRIT-3).** The test runner had no project model and had to be told the source root on every invocation, which authors forgot — leading to silent test-collection misses.

Both problems shared a root cause: there was no canonical answer to "what is *this* project's layout?" The CLI flags were each consistent in isolation, but together they re-derived the same facts on every command.

## Rationale

### Why a declarative project model rather than per-command flags

Per-command flags are a workaround for the absence of a project model. They shift the burden onto the author to remember (and onto every script and CI job to repeat) the same facts: where source lives, where build artifacts go, which files are exceptions. A declarative model collapses that knowledge into a single source of truth.

This is also the kind of fact that *belongs in the project*, not in the invocation. The build directory is a property of the project, not a property of any one `s0ma build` call. Encoding the property in the project itself makes the project queryable — `S0maProject` is now a registered component (`S0maDSL_S0maProject`) and can be inspected by the same machinery that inspects `.s0ma` declarations.

### Why `pyproject.toml`, not a separate `s0ma.toml`

PEP 518 explicitly carves out the `[tool.<name>]` namespace for project-tool configuration. Asking authors to maintain a parallel `s0ma.toml` would split a single coherent fact (project layout) across two files. The python ecosystem has converged on `pyproject.toml` as the home for hatch / setuptools / poetry / black / ruff / pytest / mypy configuration; `[tool.s0ma]` joins the same precedent.

A separate file would also produce a worse failure mode: if a consumer creates `pyproject.toml` but forgets `s0ma.toml`, our discovery would silently use defaults that disagree with the rest of the project's tooling. By living in the same file, `[tool.s0ma]` follows the same lifecycle as `[tool.ruff]` and is harder to forget.

### Why upward-walking discovery

The convention in modern Python tooling (poetry, ruff, black, pytest) is to walk upward from the working directory until a configuration file is found. This matches author expectations: running `s0ma check src/foo/bar.s0ma` from a deeply nested working directory should find the same project as running it from the repo root.

Walking upward also handles monorepos cleanly: a sub-project with its own `pyproject.toml` will short-circuit the walk, while a leaf directory with no `pyproject.toml` will continue upward to the parent.

### Why a synthetic fallback rather than a hard error

Hard-erroring on missing `[tool.s0ma]` would break every existing consumer's CI on the day this milestone shipped. The synthetic fallback gives consumers a strict deprecation window: legacy invocations continue to work but every command prints a warning. The warning is loud enough that authors will fix it; soft enough that it does not block work.

The fallback project is flagged with `synthetic=True` so future milestones can short-circuit features that genuinely require declared metadata (e.g., a future `s0ma project doctor` that audits `[tool.s0ma]` keys against the actual filesystem).

### Defaults chosen for backwards compatibility

The defaults (`source_roots = ["src"]`, `test_roots = ["tests"]`, `build_dir = "<project_name>_build"`, `bootstrap_files = []`) match the conventions already used in the s0ma framework, sister projects, and feedback-5/6 reference projects. Empty `[tool.s0ma]` tables work for the common case without further configuration.

## Consequences

- Every CLI subcommand entry point reads `args.s0ma_project` and operates against the resolved project. Per-command path arguments remain valid as one-off overrides.
- `S0maProject` is a frozen `@dataclass`, registered via `@component(name="S0maDSL_S0maProject", kind=ComponentKind.MODEL, ...)`. It is queryable through the same registry surface as the rest of the transpiler.
- Consumer projects must add `[tool.s0ma]` (one line minimum) to suppress the legacy-mode warning. This is documented in `docs/migration_guide.md`.
- Subsequent feedback 5–6 milestones (M4, M6, M7, M11, M16) build on this model — for example, M16's coherent build-output layout reads `build_dir` directly from the project rather than reconstructing it from CLI flags.
- The `--project-root` global flag is the single supported override for the discovery start path. CI jobs that invoke `s0ma` from outside the project tree should pass it.

## Alternatives Considered

1. **Per-command flags only (no project model).** Rejected: this is the status quo that produced feedback-5.5 and feedback-6 CRIT-3.
2. **Separate `s0ma.toml` file.** Rejected: splits configuration across files, contradicts PEP 518, worsens the "I forgot to add it" failure mode.
3. **Configuration via environment variables (`S0MA_SOURCE_ROOT`, etc.).** Rejected: env vars are imperative, not declarative; they don't survive `git clone`; they make the project's layout invisible to anyone reading the repo.
4. **Hard-error when `[tool.s0ma]` is missing.** Rejected for the deprecation window; will be reconsidered in a 1.0.0 release.
5. **Discover via `.s0ma-project` marker file.** Rejected: dotfile proliferation; offers no advantage over the `[tool.s0ma]` table that lives in a file every Python project already has.
