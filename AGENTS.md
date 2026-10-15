# s0ma repository agent contract

Be concise: prefer concrete evidence, decisions, and artifacts over long narration. These rules apply to every coding agent and sub-agent working in this repository.

## Authority order

When sources disagree, stop and resolve them in this order:

1. The owner's current instruction and an owner-approved implementation plan.
2. `references/s0ma-prd.md` for product purpose, principles, and invariants.
3. The current versioned DSL spec under `packages/s0ma-dsl/docs/` for language
   grammar and semantics.
4. Accepted ADRs and frozen contracts under `docs/adr/` and `docs/contracts/`.
5. Executable tests and current implementation behavior.
6. READMEs and explanatory guides.

Do not amend the PRD, a frozen contract, or an accepted ADR as an incidental
implementation fix. Escalate a real conflict to the owner.

## Package and dependency map

The distributions version in lockstep, but remain independently installable:

```text
s0ma-mcp (agent authoring server)
s0ma-studi0 (local visual environment: studi0 and its sh0w graph renderer)
    -> s0ma-dsl (language, compiler, CLI)
        -> s0ma-core (Apache-2.0 runtime, registry, verification, introspection)
```

Dependencies never point upward. In particular, `s0ma-core` stays fully useful
with zero hard dependency on the DSL, MCP, or studi0 packages. Optional API/MCP
extras in core remain optional.

## Authored and generated paths

- Two packages are self-hosted — `s0ma-mcp` and `s0ma-studi0` — and both use the
  same layout: authored `.s0ma` sources under `s0ma_src/`, the transpiler's
  committed build output under `src/<module>/_built/` (the shape
  `packages/s0ma-mcp/docs/adr/ADR-001-selfhost-layout.md` set for MCP, which
  studi0 later adopted). Both ship that output in their wheel, so a stale commit
  of it is a release defect. Never hand-edit anything under either `_built/`
  tree; edit the `.s0ma` source and rebuild.
- Author MCP behavior in `packages/s0ma-mcp/s0ma_src/*.s0ma` and its embedded
  data files. Regenerate the committed build with:
  `uv run s0ma --project-root packages/s0ma-mcp build packages/s0ma-mcp --mode release --no-cache`.
- Author studi0 behavior in `packages/s0ma-studi0/s0ma_src/*.s0ma`, and the sh0w
  front end in `packages/s0ma-studi0/s0ma_src/assets/` (embedded into CONSTANT
  cells with `content: @file(...)`). Regenerate the committed build with:
  `uv run s0ma --project-root packages/s0ma-studi0 build packages/s0ma-studi0`
  — no `--mode` flag, because that package's pyproject declares
  `[tool.s0ma].mode = "strict"` and the CLI reads it.
- The documentation application is a third committed build, though not a
  package: `docs/s0ma_src/application.s0ma` builds into `docs/_built/` and
  renders `docs/reference/documentation-application.md`
  ([`docs/adr/ADR-012-docs-application.md`](docs/adr/ADR-012-docs-application.md)
  §2.1). Regenerate both with `uv run s0ma --project-root docs build docs` and
  `uv run s0ma --project-root docs docs render docs/s0ma_src --output-dir docs --mode release`
  (`--project-root docs` in every invocation), then run the documentation loop
  below, because the rendered page is part of what compose reads. Never
  hand-edit `docs/_built/`.
- For any of the three builds, commit authored source and regenerated output
  together.
- `packages/s0ma-mcp/tests/snapshots/mcp_surface.json` is the client-visible
  surface contract. Regenerate it only for an approved surface change, review
  the exact names/descriptions/schemas/annotations diff, then run the ordinary
  snapshot test.
- README inventory blocks and the packaged getting-started guide are generated
  by `python scripts/generate_mcp_readme_surfaces.py --write`. Edit
  `docs/getting-started.md` or the served surface snapshot, not those blocks.
- Other committed mirrors under `s0ma_mcp/_docs/` must remain byte-identical to
  the source recorded in `resources.GUIDE_DOCS`.
- The documentation loop ends in **five** mirror copies, and a change to what
  the build composes needs all five or a wheel ships stale documentation:
  `docs/_generated/s0ma-docs-model.json` into `s0ma_mcp/_docs/` and into
  `s0ma_dsl/_docs_snapshot/`, `docs/_generated/core-teaching-slice.json`
  into `s0ma/_teaching/slice.json`, and the quick reference in both its
  forms, `docs/reference/quick-reference-readable.md` and
  `docs/_generated/quick-reference-machine.json`, into `s0ma_mcp/_docs/`.
  They are `cp` outputs, never edited. The loop is written once, in
  [`docs/operations/docs-maintenance.md`](docs/operations/docs-maintenance.md).
- Generated DSL docs identify their generator in the file or nearby tests. Use
  that generator; do not patch rendered tables by hand.

## Five-minute orientation loop

Before editing:

1. Read the relevant approved plan milestone and `git status --short --branch`.
2. Read this file, the PRD sections in scope, and the applicable spec/ADR.
3. Locate the authored source, generated consumers, tests, and changelog entry
   with `rg`; do not infer ownership from filenames alone.
4. Run the narrowest existing test or gate that describes the current behavior.
5. State the intended contract and expected artifact/snapshot delta before a
   broad edit. Preserve unrelated user changes in a dirty worktree.

## Verification and release rules

- `uv run python scripts/check.py` is the canonical repository gate. It runs
  every stage (`--list` names them) and does not stop after the first failure.
  Do not substitute an ad-hoc set of commands for the final run.
- While iterating, run focused package tests from that package's directory.
  Before handoff, run all relevant focused tests, the full gate, and
  `git diff --check`.
- Any `.s0ma`, parser, grammar, IR, or emitter change pays the self-host tax in
  all THREE committed builds — both self-hosted packages and the documentation
  application: rebuild each affected `_built/`, run the byte-equality stages
  (`--only selfhost-build` covers the two packages, `--only docs-application`
  the documentation application), and regenerate the MCP surface snapshot only
  when the client-visible surface deliberately changed. A parser, grammar, IR,
  or emitter change reaches all three alike, even when you only edited one of
  them; the documentation application is the one that is easy to miss. Add
  `--no-cache` to those rebuilds: the build cache is keyed on the s0ma-dsl
  version, which does not move between unreleased commits.
- A version is released in lockstep across all four packages. Follow
  `docs/RELEASING.md`; update the root `CHANGELOG.md`, keep package changelogs as
  historical pre-monorepo records, and never leave an empty release heading.
- All four packages are Apache-2.0, and the repository root carries the same
  `LICENSE` plus a `NOTICE`. Wheel metadata, classifiers, bundled LICENSE
  files, PRD, and current package docs must agree.
- Never push a `v*` tag merely to test a release: the release workflow fires on
  pushed tags. Create/push only when the owner explicitly authorizes it.

Prefer small, reviewable commits. A green gate is evidence, not permission to
change a frozen contract or broaden scope.
