# ADR-012: The documentation application — placement, build and output boundaries, snapshot semantics

**Status:** Accepted — owner-ratified 2026-08-29 at the Phase B gate of
the docs-function initiative (internal plan, not published)
(gate record: `plans/notes/doc-function-b7-report.md` §5 A-1)
**Date:** 2026-08-28
**Governing input:** owner decisions of 2026-08-28 — **D-3** (`docs/` is a s0ma
project, "docs is integral to all that is s0ma", *subject to B1's path/build
safety proof*), **D-4** strict (nothing new to the DSL for documentation), and
**D-5** (composed immutable snapshots)
**Architecture authority:**
the self-documenting-application architecture plan (internal, not published)
§5.2 (repository placement), §5.3 (package roles), §5.4 (build-time
composition), §10.2 (commands), §10.3 (repository gate)
**Evidence:** the B1 micro-spike at
`scripts/spikes/docs_model/spike_b1_layout/` — eleven proofs against a
throwaway `docs/`-shaped trial project, run offline, touching the real `docs/`
tree not at all. Its `README.md` records the findings cited by number below.
**Sibling (accepted at the same gate):**
[ADR-013](ADR-013-derived-source-registry.md) — the derived-source provider
registry. Referenced by path rather than by link because it is authored in the
same wave as this ADR; the reference becomes a link once both are committed.
**Implements no code.** This ADR is text. The machinery it describes lands in
Phases C–F, and nowhere else.

---

## Context

Owner decision D-3 made `docs/` a s0ma project and attached one condition to it:
prove first that a `docs/` project root can use an isolated build directory,
render safe relative outputs into the documentation tree, and pass a drift check
without risking unrelated files. That condition exists because three facts in
the current toolchain pull against each other.

1. The architecture's §5.2 layout wants rendered pages in **sibling** directories
   of the build — `docs/learn/`, `docs/reference/` — beside a committed
   `docs/_built/` and an authored `docs/s0ma_src/`.
2. Every rendered document is **hard-confined to a base directory**: an absolute
   `output:` or one containing `..` is refused
   (`codegen/doc_emitter/renderer.py::_resolve_output_path`).
3. For a resolved project, that base **is** the project's `build_dir`
   (`cli/docs_commands.py::_resolve_docs_base_dir`, precedence rule 2).

Taken together, those say a documentation project renders into its own build
directory and cannot reach a sibling of it. Either the §5.2 layout was wrong, or
the invocation form was. The existing counter-example said the second: the DSL's
own `docs-derived` target in
[`packages/s0ma-dsl/Makefile`](../../packages/s0ma-dsl/Makefile) has been
rendering an in-repo `doc-ref` into a documentation tree since G7b, using an
explicit `--output-dir`. The spike settled which form the documentation
application should use by exercising both against a faithful trial layout.

What the spike found, in one paragraph. Project form pins every output inside
`build_dir`, so the §5.2 sibling directories are not merely awkward to reach but
structurally unreachable (finding 1) — the `../learn/…` that would reach them is
refused under both invocation forms (finding 4), and the configuration trick
that would have avoided the problem, `build_dir = "."`, is refused by the project
loader outright (finding 5). The `--output-dir` form produces the §5.2 layout
exactly, with no code change, no override flag, and no `BUILD_DIR_OVERRIDE_CONFLICT`
refusal, because that guard lives on `s0ma build` alone (finding 2). The
write/check loop is clean and byte-stable: `check-drift` exits 0 twice in a row
and changes nothing, a second render reproduces the bytes, and two copies of the
same project rendered at different absolute paths produce identical content
hashes (finding 3). Two consequences follow the choice: a project build renders
every document a second time into `build_dir`, byte-identically (finding 6), and
project discovery anchors on the working directory rather than the positional
source path, so `--project-root` is mandatory (finding 7).

D-3's condition is met. The rulings below follow from that evidence.

---

## Decision

### 1. Placement — four homes, confirmed

The architecture's forecast stands. Each home has one job.

| Home | Holds | Must not hold |
|---|---|---|
| `packages/s0ma-dsl/src/s0ma_dsl/docs_model/` | The reusable machinery: the `s0ma-docs-model@1` schema module, the provider interface, the composition engine, the resolvers and renderers | Anything specific to this repository's documentation — no catalog, no concept records, no repository paths |
| `docs/s0ma_src/` | The application: composition, the document catalog, and the authored records (concepts, journeys, surfaces) as schema-validated data files | Rendering, source-adapter, or coverage logic that belongs in the reusable machinery |
| `docs/_built/` | The committed deterministic application build, byte-gated the way the s0ma-mcp and s0ma-studi0 builds are | Hand edits, ever |
| `docs/_generated/` | Structured outputs — manifests, structured projections of the model, machine-readable inventories | Reader-facing pages |

Rendered reader-facing pages land in the documentation tree's own directories
(`docs/learn/`, `docs/reference/`, and the rest of §5.2's list), never inside
`_built/` or `_generated/`.

**Why the machinery goes in s0ma-dsl and not s0ma-core.** SDA-INV-5 fixes the
dependency direction: core may not import the DSL, and core may not know
repository layout. s0ma-dsl already parses, validates, indexes, hashes, renders,
and drift-checks documentation (§5.3), so the model and provider framework sit
with the layer that already owns those verbs. Shipping them in the s0ma-dsl
wheel also makes them available to any consumer project, not only to this
repository — the documentation application is the first consumer of the
machinery, not its owner.

**The documentation project is not a distribution.** It is never a dependency of
any wheel (§5.3), and it is never added to the uv workspace member set.

**Two additions the spike forces**, neither of which changes the four homes:

1. `docs/pyproject.toml` carries `[tool.s0ma]` with `source_roots = ["s0ma_src"]`,
   `build_dir = "_built"`, and `mode = "release"`. `build_dir` may not be `"."`
   (finding 5), and the table's `mode` is honoured by the project build without
   a `--mode` flag — verified. The project declares `s0ma-core` and `s0ma-dsl` in
   `[project].dependencies` so the build is warning-free rather than carrying a
   standing `HOST_RUNTIME_UNDECLARED`.
2. Until the enabling change in §2.4 lands, `docs/_built/` will also hold a
   byte-identical second copy of every rendered page (finding 6). Those copies
   are build artifacts: committed with the rest of the build, never linked, never
   read, never hand-edited. The repository's existing ignore rules already keep
   the machine-local state out of the tree — `.s0ma/` and `.s0ma.cache/` are
   ignored at the root, so `docs/.s0ma/` and `docs/_built/.s0ma.cache/` need no
   new rule.

**Package-owned material stays where packaging or authority requires** (§5.2).
"One location" means one governed map and one canonical source per artifact, not
one physical directory. Package READMEs, wheel payloads, generated package
builds, and package-owned normative specifications remain outside `docs/` and
become cataloged landing pages or gated mirrors — the pattern
[`packages/s0ma-mcp/docs/adr/ADR-001-selfhost-layout.md`](../../packages/s0ma-mcp/docs/adr/ADR-001-selfhost-layout.md)
already established for the s0ma-mcp `_docs` mirror.

### 2. Build and output boundary

#### 2.1 Three commands, all through the existing `s0ma` surface

Per §10.2, no repository-only generator with different semantics is introduced.
The operator loop is one write command and one check command; the application
build is the ordinary project build.

```text
# build the application itself into the committed build directory
uv run s0ma --project-root docs build docs

# write: render every declared output into the documentation tree
uv run s0ma --project-root docs docs render docs/s0ma_src --output-dir docs --mode release

# check: re-render in memory and byte-compare against what is committed
uv run s0ma --project-root docs docs check-drift docs/s0ma_src --output-dir docs --mode release
```

`--project-root docs` is **mandatory in every invocation** (finding 7): project
discovery anchors on the working directory, not on the positional source path, so
a run from the checkout root would otherwise fall back to a synthetic project and
scatter rendered pages into `docs/s0ma_src/`. `docs verify` accepts the same
`--output-dir` and resolves it through the same function as `render` and
`check-drift` — that parity is milestone A8's fix, and the application depends on
all three subcommands agreeing about where declared outputs land.

A thin repository wrapper over these commands remains acceptable under §10.2 only
if it calls the public documentation-application API and contains no rendering,
source, or coverage logic of its own.

#### 2.2 The invocation form is the `--output-dir` form, and the reason is evidence

The two forms were exercised against the same trial layout. The `--output-dir`
form is chosen because it is the only one that can express the target layout, and
because expressing it costs nothing:

| Form | Result against the §5.2 layout |
|---|---|
| Project form (base = `build_dir`) | Every output lands under `_built/`. The reader-facing directories are unreachable: reaching them needs `../learn/…`, which the renderer refuses (findings 1, 4) |
| Project form with `build_dir = "."` | Refused by the project loader — `INVALID_PROJECT_NAME_FOR_BUILD_DIR`; the build directory's last path component is the import token the runtime bridge uses (finding 5) |
| **`--output-dir <docs root>`** | **Produces §5.2 exactly. No code change, no override flag, no configuration change. Same shape as the DSL's own `docs-derived` target (finding 2)** |

The rejection of project form is therefore mechanical, not aesthetic. It is not
the harder path to the layout; it is not a path to the layout.

#### 2.3 How outputs into `docs/learn/`, `docs/reference/` stay contained

Pinning the base to the documentation root makes the renderer's existing
confinement rule do exactly the work the architecture wants: **every declared
output resolves inside `docs/` and nothing resolves outside it.** A doc
declaration cannot write into `packages/`, into `plans/`, or into the repository
root, however it is authored — verified by the escape proof under this form
(finding 4).

Because the base is the documentation root rather than the build directory, three
rules that the mechanism cannot enforce become the application's own, checked by
the gate stage in §4:

* **B-1.** No doc declaration may declare an `output:` under `_built/`. That tree
  belongs to the transpiler; a declaration writing into it would put authored
  intent inside machine output.
* **B-2.** `_generated/` holds machine-readable outputs only. Reader-facing pages
  go in the reader-facing directories, so that "what a person reads" and "what a
  program reads" never share a path.
* **B-3.** Declared `output:` paths are relative and forward-slashed, and the
  rendered bytes are UTF-8 with LF endings on every platform.

#### 2.4 The one enabling change, and it is D-4-clean

A project build resolves its documentation base to `build_dir`, so
`s0ma build` renders every declared output a second time under `_built/`
(finding 6). The copies are byte-identical; the duplication is the cost.

The spike identified one small change that removes it: an **optional
`[tool.s0ma]` key** — working name `docs_output_dir` — naming the base that
declared `output:` paths resolve against, defaulting to `build_dir` so every
existing project is unaffected. Three touch points: the loader in `project.py`,
precedence rule 2 in `cli/docs_commands.py::_resolve_docs_base_dir`, and the
project-build `docs_base` line in `cli/main.py`.

This ADR records it as the only enabling change the C phase needs and rules that
it is **outside the D-4 guard**: it is a project-configuration key in TOML — no
grammar, no declaration kind, no entity namespace, no parser surface. Whether to
adopt it is a C-phase call (C8's business), not a precondition: without it the
duplication is harmless and the drift gate keeps both copies honest; with it,
`s0ma build` and `s0ma docs check-drift` agree on one location.

### 3. Composed-snapshot semantics

**One snapshot per build, immutable for the duration of that build** (D-5). The
application composes the four package snapshots, the catalog, the surfaces, and
the journeys into one `s0ma-docs-model@1` value, and every renderer, coverage
gate, and manifest reads that one value. Nothing re-composes mid-build; nothing
mutates a record after composition.

**No persisted registry.** Every build boots its own registry and composes from
scratch. A `.s0ma/registry.db` written by an earlier run is never an input, and
the composed snapshot is never written down to be read back by a later build.
`docs/_generated/` is an *output* of a snapshot, never an input to one.

**The §5.4 prohibition list, restated.** The application must not depend on:

- a persisted `.s0ma/registry.db` from an earlier run;
- import order that changes record identity;
- local network services;
- Cloudflare, GitHub, R2, or MCP client availability;
- a production studi0 process;
- filesystem paths outside the checkout;
- uncommitted generated outputs as input truth.

**Identity and provenance.** Stable id forms are frozen in the implementation
plan's §5; two providers emitting one id with different facts is a build error,
not a merge. Every record carries the provenance its provider stamped on it
(adapter id, source identity, schema version, content hash), and provenance
survives every projection (SDA-INV-10). Authority order — owner > prd > spec >
adr > frozen_contract > declared > derived > observed > editorial — is applied,
never silently resolved: a conflict is reported.

**Byte determinism is a stated invariant**, not an aspiration: UTF-8 and LF
everywhere, sorted outputs, no wall clock, no randomness, no machine paths in
rendered content. The spike's cross-path proof — two copies of one project at
different absolute paths rendering to identical hashes — is the shape the
application's own gate must keep, because Windows CI is real and a path leaking
into a rendered page is exactly the defect that survives a same-directory
re-run.

**The trust boundary is unchanged.** Live or observed data never enters a build
artifact; that rule is ADR-002's and
[ADR-002](ADR-002-self-context-authored-data-boundary.md) continues to govern it.
The documentation snapshot is composed from authored records and registered
component facts only.

### 4. The `docs-application` gate stage

**Slot.** `scripts/check.py` gains one stage named `docs-application`, placed
**after `pytest-studi0` and before `selfhost-build`**. The reason for that exact
position: the four package suites must be green before anything composes their
registries, and `selfhost-build` rebuilds committed `_built/` trees *in place*, so
a documentation failure should be reported while the tree is still the tree that
was committed. The stage is added by the existing extension convention in
[`scripts/check.py`](../../scripts/check.py) and appears in `--list` and `--only`
like every other stage.

**Charter** (§10.3, binding on the implementation):

1. Build the documentation snapshot **from scratch** — no cached registry, no
   reuse of a previous run's outputs.
2. Run coverage, authority, link, version, mirror, and drift validation.
3. Render every artifact to **temporary storage**, then byte-compare against the
   committed outputs and report precise diffs.
4. Prove the document catalog is **complete and non-vacuous** — an anti-vacuity
   floor, the house pattern already used by the link guard.
5. Run with **no network access and no repository writes**. The stage is a check
   path only; it never runs the write command.
6. Print **source-located remediation** for every failure.
7. **Continue collecting independent failures** rather than stopping at the
   first.

**Subsumption bookkeeping.** The existing focused checks remain unless the new
stage demonstrably subsumes them, and removing a proven gate requires an explicit
equivalence test and review (§10.3). Two live cases this ADR names so they are
not lost: the nine-file `_docs` mirror byte-gate is a pytest test rather than a
stage, so its bookkeeping belongs with that test; and the temporary
classification-ledger guard is scheduled for subsumption by the F2 catalog gate
under the same equivalence rule.

---

## What this ADR does not decide

Stated explicitly, because each of these is a live question that this document
would otherwise appear to have settled.

* **Anything about the DSL grammar.** D-4 strict governs: no new declaration
  kind, no new grammar, no entity-namespace addition, no parser surface. The
  documentation application is composed from the existing declaration kinds plus
  schema-validated data files loaded by registered provider components. Any
  conclusion that the application *needs* grammar is a full stop and an owner
  escalation, never a workaround.
* **The catalog file format.** Whether the catalog, concepts, and journeys are
  represented as data files or in a cells-based form is B6's spike and the B7
  owner gate's ruling. This ADR rules only on *where* the catalog lives
  (`docs/s0ma_src/`), not on what it looks like.
* **The derived-source provider registry.** ADR-013 owns it, at the same gate.
* **Physical moves of governance material.** D-7 deferred the PRD and spec moves;
  catalog first. Which documents move, and when, is Phase G's business, and
  `docs/governance/` exists in §5.2 as a target, not as an approved move list.
* **Whether `docs_output_dir` is adopted.** §2.4 records the change and rules it
  D-4-clean; adopting it is a C-phase call, and the layout works either way.
* **The reserved read-surface names.** `s0ma docs list|show|search`,
  `learn_s0ma`, and the `s0ma://docs/*` resource family are frozen at their own
  milestones (F6, F7), not here.

---

## Consequences

- D-3's condition is discharged: the `docs/` project uses an isolated build
  directory, renders safe relative outputs into the documentation tree, and
  passes a drift check twice over without touching an unrelated file.
- The documentation application costs the toolchain **no code change to exist**.
  Every mechanism it needs — project resolution, the output base override, output
  confinement, transitive content hashes, drift comparison — already ships and is
  already gated.
- The `--output-dir` form becomes load-bearing for a second consumer, so its
  behaviour is now covered by the spike's proofs as well as the DSL's
  `docs-derived` target. A future change to base resolution shows up as a failing
  proof rather than as scattered pages.
- `docs/_built/` carries duplicate copies of every rendered page until, and unless,
  §2.4's key is adopted. That is a known, byte-gated cost recorded here so it is
  not rediscovered as a defect.
- Every declared output is confined to `docs/`. The blast radius of a bad
  `output:` path is one directory tree, and the failure is a refusal, not a
  stray file.
- The gate stage inherits an explicit charter, so "the docs stage passed" means
  built-from-scratch, compared byte-for-byte, offline, and reporting every
  failure rather than the first.

---

## Amendment (2026-08-29, milestone C8)

§1 names `mode = "release"` for the docs application's `[tool.s0ma]`. C8
shipped `mode = "strict"` instead, for a recorded reason: release mode adds
`MISSING_PUBLIC_DOC_REF` (one doc-ref per PUBLIC nerve), satisfiable before
the F phase only by declaring an output no reader consumes, in a directory
the F phase has not laid out — and a Markdown output would cascade into a
catalog row prematurely. This is the same call `s0ma-studi0` made at its own
introduction, for its own recorded reason. The reason is written at the key
in `docs/pyproject.toml`, a test pins both the value and the reason, and F1
raises the mode to `release` when the reader-facing pages are real.
Surfaced for owner visibility at the Phase C close-out.
