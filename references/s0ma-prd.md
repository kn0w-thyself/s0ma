# s0ma — Product Requirements Document

| | |
|---|---|
| **Product** | s0ma — software self-knowledge platform |
| **Document** | `references/s0ma-prd.md` |
| **Status** | Living document — canonical alignment reference for developers and coding agents |
| **Version** | 1.16 (2026-10-14) |
| **Owner** | Rob (kn0wthyself) |
| **Applies to** | The consolidated `s0ma` monorepo: `s0ma-core`, `s0ma-dsl`, `s0ma-mcp`, `s0ma-studi0` |
| **Related** | `plans/complete/s0ma-new-consolidation-1.md` (how we get here) · package docs under `packages/*/docs/` |

> **How to use this document.** This PRD defines *what s0ma is for* and *what must remain true*
> of it. Implementation plans, specs, and milestones say *how*; this document is the tiebreaker
> when a change is technically possible but strategically wrong. If a proposed change conflicts
> with a **Principle (P-#)** or an **Invariant (INV-#)** below, the change is wrong — or this
> PRD must be deliberately amended first, by the owner, never implicitly by a patch.

---

## 1. Vision

**Software that cannot exist without understanding itself.**

s0ma is a Python platform for *software self-knowledge*: a system's ability to maintain an accurate, queryable, machine-readable model of itself — its structure (components, their intents, contracts, dependencies, documentation, and examples), its runtime state, and the reasoning over that model.

"Understanding itself" is the umbrella; it spans **three faculties**, each mapped to real machinery in the platform. Use the specific faculty term where the specific sense is meant; use *self-knowledge* for the umbrella:

| Faculty | Sense | Backed by (existing machinery) |
|---|---|---|
| **Proprioception** | structure — "what am I made of, how is it wired" | registry, structural verifier, dependency graph, layers, IR edges |
| **Interoception** | internal/runtime state — "how am I behaving vs. how I declared" | the interoception verifier (runtime metrics vs. declared resource profiles) — one of the four engines |
| **Metacognition** | reasoning over the model — "reasoning about my own model" | QueryEngine, impact analysis, extension-point guidance, drift detection |

Proprioception was only ever the *structural* third; self-knowledge is the whole. (See the glossary, §11, for each faculty's canonical definition.)

The defining idea is that the self-model is **load-bearing**. It is not documentation that
describes the system from the outside and silently rots; it is a structural element the system stands on. Remove a component's registration and the system fails to start. Change a component without updating its declared model and verification fails. Let documentation drift from code and the CI gate refuses the merge.

### Why now

Coding agents are becoming the primary authors, users, and maintainers of software. Agents are only as good as their model of the system they are changing — and today that model is scraped from stale READMEs, partial file reads, and guesswork. s0ma inverts this: the system carries its own always-accurate model, in formats designed for both human and LLM consumption, with enforcement machinery that makes inaccuracy a build failure rather than a discovery during an incident.

**The end state we are building toward:** a coding agent opens a s0ma project — from the checkout itself, reading the `.s0ma` sources and the committed build artifacts and running the `s0ma` command line, or over MCP where its host offers that; MCP is one channel to the same model, never the only one — reads the system's self-description, authors new components in the s0ma DSL, validates them at parse time, and lands changes whose documentation and tests are *structurally guaranteed* to match the code — with no human having to ask "is the documentation up to date?" And the running system hands that same model to whatever operates it: an LLM or agent acting on a s0ma application asks the application what it is made of, what each part promises and what would break, and is answered by the system rather than by a guess.

### Two ways an agent meets s0ma

Agents meet s0ma in two distinct ways, and this document keeps them apart because the benefits
differ:

1. **Building or maintaining a s0ma application** — the coding agent (P1). It reads the
   self-model instead of reconstructing the system from source, authors intent and contracts
   that the compiler then holds the code to, and works inside guardrails that refuse an
   undeclared, undescribed or drifted change before a person sees it. The benefits are
   efficiency, captured intent and enforcement. It works from the checkout with the `s0ma`
   command line and the committed artifacts, or through the authoring MCP server (`s0ma-mcp`,
   §7.3) when its host speaks MCP; MCP is one channel and never a requirement.
2. **Using or operating a s0ma application** — an LLM or agent the running system hands its own
   model to. The self-context the build emits (ADR-002) and the runtime query surfaces of
   `s0ma-core` — the Python API, the optional REST view, the introspection MCP server — let an
   operating agent ask the system what it is made of, what each part promises, what it depends
   on and what would break, and be answered by the system itself. The benefits here are
   autonomy and safety: an agent that acts on a system can first ask the system, and what it is
   told is quoted project data, never an instruction.

s0ma serves both, and neither depends on the other: an application built without any agent
still carries the model an operating agent can read, and an agent that builds with s0ma gets
the guardrails whether or not anything will ever operate the result.

---

## 2. Problem statement

1. **Documentation drifts.** Conventional docs are a parallel, hand-maintained surface with no 
   enforcement link to code. They are wrong within weeks of being written, and nobody can tell
   *which parts* are wrong.
2. **Architecture is tribal knowledge.** Component boundaries, layering rules, dependency
   intent, and contracts live in heads and review comments, not in queryable artifacts. Every
   new contributor — human or agent — re-derives them, imperfectly.
3. **Coding agents lack a trustworthy system model.** Agents waste context reconstructing
   structure from raw source, miss non-local constraints (layering, namespaces, contracts), and
   produce changes that are locally plausible and globally wrong.
4. **Conventions are unenforceable at scale.** "Every public component must be documented,
   tested, and declared" is a wish unless the toolchain makes violations fail loudly — at parse
   time, at import time, and in CI.

## 3. Product thesis

s0ma delivers **software self-knowledge** — the umbrella faculty of §1, spanning proprioception
(structure), interoception (runtime state), and metacognition (reasoning over the model). Today the
platform's centre of gravity is proprioception (the load-bearing structural self-model) with
interoception and metacognition realised by the interoception verifier and the query/impact
surfaces respectively; all three are first-class and grow together. The faculties are a *capability*
axis; the products below are a *packaging* axis — distinct dimensions, not the same three.

s0ma realises this with four layered products in one repo, one version, one philosophy:

| Layer | Package | What it does | Enforcement moment |
|---|---|---|---|
| Runtime | **`s0ma-core`** (module `s0ma`) | Registry, decorators, import-hook enforcement, four-verifier engine, lifecycle management, self-model query surfaces (Python API, REST, introspection MCP) | **Import time & runtime** |
| Language | **`s0ma-dsl`** (module `s0ma_dsl`, CLI `s0ma`) | The `.s0ma` DSL and transpiler: grammar-level enforcement of declaration, description, dependency resolution, and documentation; deterministic compilation to `@component`-decorated Python + IR + source maps | **Parse/build time** |
| Agent interface | **`s0ma-mcp`** (module `s0ma_mcp`) | MCP server exposing the authoring toolchain (transpile, build, check, inspect, scaffold, migrate) and the agent-facing guides to coding agents | **Authoring time** |
| Visualization | **`s0ma-studi0`** (module `s0ma_studi0`, launched by CLI `s0ma studi0`) | studi0, the visual development environment: a local, read-only viewer hosting sh0w, the live canonical-graph renderer, fed exclusively from existing deterministic build artifacts | **Viewing time (read-only; enforces nothing, displays truth)** |

The same rule is enforced three times, earliest possible first: the DSL refuses to *parse* an
undeclared component, the import hook refuses to *load* one, and the verifiers refuse to *pass*
one that has drifted. Defense in depth for truthfulness.

---

## 4. Users and personas

### P1 — The coding agent (primary persona)

An LLM-based agent (Claude Code or similar) building or maintaining a s0ma application — the
first of the two ways an agent meets s0ma (§1). Works from the checkout with the `s0ma` command
line and the committed artifacts, or connects via `s0ma-mcp` where its host speaks MCP; either
way it needs: a one-page survival guide it can hold in context, structured
diagnostics (not prose tracebacks), deterministic tools, an IR it can read instead of re-parsing
source, and a scaffold-check-transpile loop with fast feedback.
**Success looks like:** an agent with no prior exposure to the codebase produces a valid,
fully-declared, documented `.s0ma` module on the first or second attempt.

### P2 — The application developer

A Python developer building a system *on* s0ma. Authors `.s0ma` modules (or decorates plain
Python with `@component`), runs `s0ma build` / `s0ma test`, relies on strictness modes
(`migration` → `dev` → `strict` → `release`) to adopt incrementally.
**Success looks like:** the self-model answers their architecture questions faster than reading
the code would, and CI catches their drift before review does.

### P3 — The platform contributor

A developer (often agent-assisted) working on s0ma itself. Needs: the monorepo's unified check
pipeline, the spec/traceability docs, ADRs, and this PRD to stay aligned.
**Success looks like:** contributions pass `scripts/check.py` and never weaken an invariant.

### P4 — The architecture stakeholder

A tech lead / reviewer / auditor — or an agent operating the system, the second of the two ways
an agent meets s0ma (§1) — querying a running system's self-model (REST, MCP, or natural
language queries) for overviews, impact analysis, dead-code reports, and doc-coverage status.
**Success looks like:** "what would break if X changes?" is a query, not a meeting.

---

## 5. Principles (P-#) — the philosophy, enforced

- **P-1 — The self-model is load-bearing.** Registration is a condition of existence, not an
  annotation. Anything that makes registration optional-by-default in strict contexts is a
  regression of the core idea.
- **P-2 — Truth has one source.** Authored facts (intent, contracts, dependencies) and derived
  facts (e.g. `RAISES`, `TYPE_USES` edges) are disjoint; authoring a derived fact is an error.
  Documentation is rendered *from* registrations, never maintained in parallel. One document may
  be committed at a second path — a **mirror**, most often inside an installed package so the
  guides ship with the wheel — but only where the copy is produced from the one source and a
  gate compares the two byte-for-byte on every build. A second copy nobody compares is a second
  source, and this principle forbids it.
- **P-3 — Drift is a build failure.** Model-vs-reality discrepancies (structural drift, doc
  drift, contract gaps, dead code) are detected mechanically and gate CI. We do not ship
  warnings that everyone learns to ignore — strictness modes exist so that `release` mode can
  be absolute.
- **P-4 — Determinism everywhere.** Same input → byte-identical output: emitted Python, IR,
  rendered docs, source maps. No timestamps, no random IDs in artifacts. Determinism is what
  makes drift *detectable* (byte-compare) and agents *reliable* (reproducible loops).
- **P-5 — Designed for two readerships.** Every surface serves humans *and* LLMs: human-readable
  `describe()` next to `explain_for_llm()`, prose docs next to structured IR, CLI text output
  next to JSON diagnostics. Neither readership is an afterthought.
- **P-6 — No LLM in the loadbearing path.** s0ma *serves* LLMs but never *requires* one: the
  query engine is rule-based, verification is static/runtime analysis, rendering is
  deterministic. A s0ma system builds, verifies, and answers questions offline.
- **P-7 — Earliest enforcement wins.** Push every rule as early as it can live: grammar > parse
  > semantic validation > import hook > runtime verifier. Later layers are backstops, not the
  primary defense.
- **P-8 — Incremental adoption is a feature.** Strictness modes and migration tooling
  (`migrate-layout`, `migrate-ext`, the Python-to-`.s0ma` migration guide) are product surface,
  not afterthoughts. Brownfield users must have a stepwise path. *(v1.12)* That path covers code
  that has never known s0ma, not only projects already inside it: retrofitting a working
  plain-Python codebase is product surface with commands, a documented order, and a measurement at
  every stop (FR-DSL-8) — never a service the project performs by hand for each new user.
- **P-9 — Placement, not architecture.** s0ma prescribes *where* components live — their layers,
  their kinds, and the blessed project layout — and enforces reachability (the layer dependency
  matrix). It does **not** prescribe an application architecture. Users bring their own
  (DDD, ports-and-adapters, hexagonal, clean, transaction-script, …); s0ma fixes placement and
  makes the resulting structure self-describing and drift-proof, without dictating how the app is
  designed. The self-model is an architecture-neutral substrate, not an opinionated framework.

## 6. Invariants (INV-#) — never break these

- **INV-1 — Spelling.** The product is **`s0ma`** — lowercase s, digit **zero**, m, a — in every
  identifier, file extension, config key, document, and user-visible string. The letter-spelling
  "soma" is forbidden except in: git history, pre-consolidation changelog entries, and
  legacy-migration code marked `# legacy-spelling: intentional`. CI enforces this. Case
  variants: `s0ma` / `S0ma` / `S0MA`.
- **INV-2 — Stable import.** The core runtime is `import s0ma`. The DSL module is `s0ma_dsl`.
  The MCP module is `s0ma_mcp`. The studi0 module is `s0ma_studi0` *(v1.6)*. The CLI is `s0ma`.
  Renaming any of these is a major-version event with a migration tool, never a casual refactor.
- **INV-3 — File extensions.** DSL sources are `.s0ma`; compiled IR is `.s0ma.json`; source
  maps are `.s0ma.map`; the build manifest is `build.s0ma.json`.
- **INV-4 — Lockstep versioning.** All packages in the monorepo share one version, one root
  CHANGELOG (Keep-a-Changelog + SemVer), one git tag (`v<version>`). Pre-1.0, minor versions may
  break with a changelog notice; post-1.0, SemVer is binding and breaking changes require a
  major bump plus migration tooling.
- **INV-5 — Deterministic artifacts.** No emitted artifact may embed wall-clock time, randomness,
  absolute machine paths, or environment-dependent ordering. (Hash fields derive from content
  only.)
- **INV-6 — Core stands alone.** `s0ma-core` must remain installable and fully functional with
  zero hard dependencies on `s0ma-dsl` or `s0ma-mcp` (the DSL import stays lazy/optional;
  FastAPI/MCP stay optional extras). Dependency direction: `s0ma-mcp → s0ma-dsl → s0ma-core`
  and `s0ma-studi0 → s0ma-dsl → s0ma-core` *(v1.6)*, never backwards. Nothing depends on
  `s0ma-studi0` (it is a leaf): the `s0ma studi0` CLI subcommand discovers it lazily, and its
  absence yields a structured install hint, never a hard dependency or a traceback.
- **INV-7 — The framework eats its own dog food.** `s0ma-core` registers its own components and
  passes its own verification (`scripts/check.py` runs the bootstrap and self-model tests).
  A change that makes s0ma unable to describe itself is rejected.
- **INV-8 — Quality gates.** mypy `--strict` (core), ruff, and the full test suites are
  non-negotiable CI gates. New public components in the platform itself carry intent,
  contracts, and tests per the same rules we impose on users.
- **INV-9 — The runtime is never gated.** *(v1.1; license amended 2026-08-10)* `s0ma-core` is Apache-2.0-licensed and fully
  functional with no account, license key, subscription, or network access — in perpetuity.
  Applications built on s0ma keep running regardless of any subscription state. Commercial
  gating applies only to authoring-time tooling (`s0ma-dsl`, `s0ma-mcp`) and never to anything
  a deployed system needs at import time or runtime. *(v1.7 note: accordingly the runtime
  bootstrap loader lives in `s0ma.bootstrap` (FR-CORE-9); the remaining authoring-package
  import inside emitted modules is tracked as the runtime-free-emission design round.)*

---

## 7. Functional requirements

Requirements use RFC-2119 keywords (MUST/SHOULD/MAY). Most codify behavior that already exists
and **must be preserved** through the consolidation; items marked **[NEW]** are introduced by it.

### 7.1 `s0ma-core` — the runtime (FR-CORE)

- **FR-CORE-1** MUST provide `@component` (registers name, kind, layer, intent, contracts,
  dependencies; returns the entity unmodified) and `@internal` (explicit exemption), with the
  `ComponentKind` / `Layer` taxonomies.
- **FR-CORE-2** MUST provide a registry with snapshotting, hierarchical queries (by layer,
  kind, dependency relationships), registry diffing, and optional SQLite persistence.
- **FR-CORE-3** MUST provide an import hook that, in strict mode, raises
  `UnregisteredComponentError` for unregistered public code at import time, and that
  transparently loads `.s0ma` modules by invoking the DSL transpiler **when `s0ma-dsl` is
  installed** (lazy import; absence of the DSL MUST NOT break non-DSL usage). Import-time
  anomalies MUST be queryable (`import_hook_anomalies`).
- **FR-CORE-4** MUST provide the four-verifier engine — structural drift, contract coverage,
  interoception (runtime metrics vs declared profiles), dead-code/coverage — producing reports
  with both `describe()` (human) and `explain_for_llm()` (agent) renderings, including fix
  suggestions.
- **FR-CORE-5** MUST provide transactional component lifecycle management (create/update/remove
  with rollback).
- **FR-CORE-6** MUST provide the self-model query surfaces: `SelfModelInterface`
  (system overview, component detail, impact analysis, extension points), the rule-based
  natural-language `QueryEngine` (no LLM dependency — P-6), optional REST API (`/self/*`), and
  the optional **introspection** MCP server (`s0ma-self-model`: resources `s0ma://docs/...`,
  `s0ma://model/...`).
- **FR-CORE-7** MUST provide the documentation subsystem runtime: `doc-ref` / `doc-guide` /
  `example` registrations, transitive content hashing, drift detection, and the
  subprocess-isolated example runner (configurable via `S0MA_INTEGRATION_CMD`,
  `S0MA_EXAMPLE_BODY_PATH`, `S0MA_EXAMPLE_NAME`; pytest integration via the opt-in
  `--s0ma-examples` plugin).
- **FR-CORE-8** MUST self-register its own framework components and verify itself (INV-7).
- **FR-CORE-9** *(v1.7)* MUST provide the runtime bootstrap for built output:
  `s0ma.bootstrap.bootstrap_imports` reads `build.s0ma.json` and imports built modules in
  `topological_import_order`, stdlib-only — so loading a build requires `s0ma-core` alone
  (INV-9). Relocated from FR-DSL-4 (2026-08-17), evidence-driven: a bench spike showed the
  dsl-hosted bootstrap made deployed apps import the proprietary authoring package at runtime.
  Known boundary: emitted modules still import `s0ma_dsl.runtime_bridge.registration`; closing
  that is the runtime-free-emission design round, pinned by a failing-forward boundary test.

### 7.2 `s0ma-dsl` — the language and compiler (FR-DSL)

- **FR-DSL-1** MUST implement the s0ma DSL as specified in the versioned spec under
  `packages/s0ma-dsl/docs/` (the spec is the normative language authority; this PRD does not
  duplicate it). The product invariants are these: the language has a fixed set of declaration
  kinds spanning both code and documentation; every kind enforces its mandatory descriptive
  fields at grammar level; and adding, removing, or renaming a kind is a specification change
  carrying the full grammar, IR, and self-hosting cost, never an implementation detail. Which
  kinds exist, and what each one means, is the spec's to state and this PRD's to defer to.
- **FR-DSL-2** MUST enforce name resolution through the spec's namespace model — separating what
  code may call, what DSL fields may reference, what the registry may observe, and what crosses
  a module boundary — and the authored-vs-derived split (P-2), both at validation time. The
  namespaces are enumerated and defined in the versioned spec (FR-DSL-1).
- **FR-DSL-3** MUST compile `.s0ma` sources — through the staged pipeline the versioned spec
  defines (FR-DSL-1) — into all three of: plain Python decorated with `@component` / doc
  registrations, a normalized `.s0ma.json` IR (schema-versioned; designed for AI tooling), and
  a `.s0ma.map` source map tying every emitted line to its `.s0ma` origin. The three are
  required output of one compilation, not optional products of it. Output MUST be deterministic
  (INV-5), with content hashes embedded via the `# s0ma-source-hash:` /
  `# s0ma-output-hash:` markers.
- **FR-DSL-4** MUST provide project-level builds: `[tool.s0ma]` in `pyproject.toml` as canonical
  project config; cross-module resolution; flat build layout with a `build.s0ma.json` manifest
  recording modules, hashes, transpiler version, and `topological_import_order`; and a
  content-hash-aware build cache with cross-module invalidation. *(v1.7: the one-line runtime
  bootstrap moved to FR-CORE-9 — loading built output is the runtime's job, not the compiler's;
  `s0ma_dsl.runtime.bootstrap_imports` remains as a deprecated delegating re-export, INV-2.)*
- **FR-DSL-5** MUST provide the `s0ma` CLI covering at minimum: `transpile`, `build`, `check`,
  `verify`, `inspect` (single module / `--all`), `topo`, `test` (project-aware pytest
  invocation), `test-conftest`, `docs render`, `docs verify`, `docs check-drift` (the CI gate),
  `examples run`, `deferred-surface`, `migrate-layout`, **[NEW]** `migrate-ext` (legacy
  `.soma`/`[tool.soma]` → `.s0ma`/`[tool.s0ma]`, dry-run by default semantics per the
  consolidation plan), and **[NEW v1.1]** `new project` (guided initialization: `[tool.s0ma]`
  table, first module, first build, printed bootstrap snippet) and `doctor` (environment and
  project health report: package versions, project detection, build freshness, MCP
  registration hint; the future home of license status and update notices per §7.5).
  Diagnostics MUST be available as structured JSON, not only prose.
- **FR-DSL-6** MUST support the four strictness modes (`migration`, `dev`, `strict`, `release`)
  with `release` enforcing the full production gate (public doc-refs, embedded examples, test
  coverage, layering, attribute budgets).
- **FR-DSL-7** MUST keep documentation a compiled, drift-gated artifact: deterministic
  Markdown/HTML/JSON renderers, a front-matter contract whose fields and order the versioned
  spec fixes and carries under its schema version (FR-DSL-1), and byte-compare drift checking
  suitable as a hard CI gate (P-3, P-4).
- **FR-DSL-8 [NEW v1.12]** MUST provide the retrofit surface that makes P-8's stepwise path real
  for code that has never known s0ma: reading a plain-Python tree and reporting what is in it and
  in what order to convert it; declaring the perimeter on an existing tree without touching
  application code; converting one module at a time into a `.s0ma` draft; recording what a module
  offered before it is replaced; and comparing the built module against that record. Which
  commands carry these duties, and what each is called, is the generated command reference's to
  state (`docs/reference/cli.md`, read from the parser itself) and this PRD's to defer to. Six
  product invariants bind, and none may be traded for convenience: (a) *static only* — everything
  reported MUST be derived by reading source; no retrofit surface may import or execute the code it
  is converting, and the behavioral check is the project's own test suite, which the user runs;
  (b) *a read writes nothing* — a surface that only reports MUST leave the tree byte-identical,
  with no report file, no cache and no lockfile, so it is safe on a codebase nobody has decided
  anything about yet; (c) *one module at a time* — conversion MUST be per-module and leaf-first,
  and no surface may adopt a tree wholesale: declaring the perimeter MUST leave the unconverted
  files counted as the honest backlog rather than absorbing them, because a bulk adoption would
  inflate the registration ratio and hide the work; (d) *the original is never modified* — no
  retrofit surface may edit, move or delete the code it reads; deleting the replaced file is the
  user's act, taken after parity is clean; (e) *a draft is unfinished by construction* — structure
  is harvested mechanically and meaning is not derived (P-6), so every un-authored intent MUST be
  emitted as a placeholder that fails `s0ma check` in every strictness mode, `migration` included,
  and source text the harvester cannot place MUST be carried where a check can see it and refuse
  it, never silently dropped; (f) *parity is taken first and names everything* — the record of what
  a module offered MUST be capturable before the original is replaced, and the comparison MUST name
  every difference with what it was and what it became, rather than returning a verdict alone.
  Diagnostics MUST be available as structured JSON, not only prose (FR-DSL-5).

### 7.3 `s0ma-mcp` — the agent authoring interface (FR-MCP) **[NEW]**

- **FR-MCP-1** MUST expose an MCP server (stdio; FastMCP; server name `s0ma-authoring`,
  console script `s0ma-mcp`) installable as a single package that transitively provides the
  full toolchain.
- **FR-MCP-2** MUST provide tools wrapping the authoring loop: `transpile`, `build_project`,
  `check`, `inspect_module`, `run_example`, `migrate_ext`, `scaffold_module`. Every tool MUST
  return structured results (`{ok, ...}` with the DSL's structured diagnostics) and MUST NOT
  leak raw tracebacks across the MCP boundary.
- **FR-MCP-3** MUST serve the agent-alignment corpus as MCP resources — at minimum the agent
  system prompt, the quick reference, the patterns guide, and the current language spec
  (`s0ma://guide/*`, `s0ma://spec/current`) — and these MUST resolve from an installed wheel,
  not only a repo checkout.
- **FR-MCP-4** SHOULD compose with core's introspection server so one MCP connection can serve
  both authoring ("write the system") and introspection ("understand the running system");
  full unification MAY come post-1.0.
- **FR-MCP-5** The scaffold→check→transpile loop MUST be self-sufficient for persona P1: an
  agent holding only the quick-reference resource and using only MCP tools can produce a valid
  module without reading transpiler source.
- **FR-MCP-6 [NEW v1.1]** MUST expose MCP prompts for the core authoring journeys (at minimum:
  author a new module, diagnose-and-fix check failures, migrate a legacy project) so MCP
  clients surface them as first-class commands (e.g. Claude Code slash commands).
- **FR-MCP-7 [NEW v1.1]** MUST eat its own dog food (INV-7 extended to the platform's agent
  layer): the server's tools, resources, prompts, and factory register as s0ma components with
  intent/kind/layer/dependencies, and the server exposes its own live component graph over MCP
  (`s0ma://self/*` resources and/or a capabilities tool) so an agent can ask the authoring
  server what it is and what it can do. The self-model and the served MCP surface MUST NOT be
  able to drift (a test compares them).
- **FR-MCP-8 [NEW v1.1]** Tools MUST carry MCP tool annotations (read-only vs mutating vs
  destructive hints) so clients can apply safe auto-approval policies to the agent inner loop.
- **FR-MCP-9 [NEW v1.1]** MUST provide a `project_status` orientation tool: one call answering
  "is this a s0ma project, which mode, what is built/stale, what is the suggested next action".
- **FR-MCP-10 [NEW v1.1]** MUST serve meta resources resolved from the installed wheel: the
  diagnostic error catalog (`s0ma://guide/errors`) and the changelog/what's-new surface
  (`s0ma://meta/changelog`), drift-gated against their in-repo sources like the existing guides.
- **FR-MCP-11 [NEW v1.3]** SHOULD itself be authored in the `.s0ma` DSL ("level (b)" dogfooding,
  now on the GA path): the server's tools, resources, and prompts are `.s0ma` modules; the
  installed package ships the transpiler's committed, deterministic build output plus exactly
  one handwritten bootstrap module; the FastMCP surface is derived from the self-model registry
  at startup, making FR-MCP-7's no-drift clause structural rather than test-enforced; and the
  package retains mypy `--strict` + `py.typed` (INV-8) — emitted code must meet the same gate
  as handwritten code. The conversion was sequenced strictly after the v1.2 Windows/determinism
  work (the committed-build equality gate binds cross-platform) and gated by an explicit
  go/no-go spike; both conditions were satisfied and the conversion has landed. Execution plan:
  `plans/complete/s0ma-new-mcp-selfhost-1.md`.

### 7.4 Cross-cutting (FR-X)

- **FR-X-1** Migration path: a pre-consolidation project (old spellings, old extensions) MUST be
  convertible by `s0ma migrate-ext` plus documented steps in the migration guide, idempotently
  and without data loss (refuse-don't-clobber on collisions).
- **FR-X-2** Each package MUST remain independently installable from a wheel
  (`pip install s0ma-core` alone is a supported, useful configuration — INV-6).
- **FR-X-3** All user-facing docs (READMEs, spec, guides, agent prompt) MUST use post-
  consolidation naming exclusively (INV-1/2/3), with legacy names appearing only in migration
  documentation, clearly marked as historical.
- **FR-X-4 [NEW v1.10]** Physical parts brought inside a s0ma system MUST be **embodied**, not
  modeled from outside it: declared as ordinary components under the existing declaration kinds,
  with their physical facts recorded as declared metadata under one shared vocabulary, so the
  runtime can hold a machine to its physical declarations the way it holds software to its
  contracts. Hardware gets no declaration kind of its own (FR-DSL-1). The physical-facts
  vocabulary and the runtime surfaces it needs are designed in ADR-003 under `docs/adr/`, which
  this requirement names as its design authority rather than restating. Product language says
  *embodied*; hardware is never "modeled".
- **FR-X-5 [NEW v1.10]** Every published documentation page MUST state the **release channel**
  it was built from: *release* — built from the exact state of a tagged version, describing that
  version and no other; *preview* — built from the moving `main` line, so it may describe work
  that has not shipped, and says so where a reader can see it; or *historical* — describing a
  version that has passed, kept for the people still on it and never presented as current. A
  page built from an untagged state MUST NOT be published as *release*, however finished the
  work feels, and *historical* is never a way to keep a page that is simply wrong.

### 7.5 Commercial access (FR-COM) **[NEW v1.1; restated v1.12]**

> Build timing: this machinery is built as the beta needs it, not ahead of it, and NFR-8 records
> what is actually distributing software today. A requirement below that is not yet built says so
> in its own words; nothing else here may be read as a description of shipped behavior.

The commercial model is **open source plus a paid convenience channel** (NFR-8, amended v1.12). The channel follows the codebase: the public
repository's first release is the source tree on GitHub and offers no subscription, and the
managed subscription opens after that release (NFR-8, amended v1.15).
Every distribution is open source and every one of them runs free of charge and unconditionally:
nothing in the product checks an entitlement in order to run, and no subscription state can switch
installed software off (INV-9). What the subscription sells is the channel and the service around
it — one-step installation into a coding agent, updates through that channel with pinning and
rollback (FR-COM-4), the agent integration, and support. Once the channel is offered, two ways in stand side by side: accounts
the owner provisions by hand for invited testers, who never enter payment details, and a
self-serve paid tier anyone may buy. Prices, billing periods, programme dates and durations are
commercial settings rather than requirements, and this document does not state them.

> **What lapsing costs, and what it does not (v1.12).** Binding, and true of the system as built:
> a subscription that lapses leaves every installed version installed and working, and stops the
> channel serving new downloads to that key. The owner's stated direction — that lapsing should
> keep what you have and lose only the convenience — agrees with that behavior and is recorded
> here as *direction*, not as a requirement. What a lapse should cost beyond losing downloads is
> an open owner decision, and no requirement below answers it.

- **FR-COM-1** *(restated v1.12)* An entitlement service MUST manage access: it issues keys, holds
  each account's status, and is the one place that decides whether a key may download. **Built
  today:** individual keys, hashed at rest and revealed once; statuses covering an invited tester
  and a paying subscriber, with a failed payment keeping access until the provider gives up; an
  optional end date on an invited tester's access; and key delivery to the toolchain through the
  agent host's own secure setting or the `S0MA_LICENSE_KEY` environment variable, with an
  `activate` command that takes a key at a hidden prompt and stores it user-scoped on the machine.
  **Not built, and named rather than left implied:** the browser device-code `login` flow, and
  organization accounts with seats. Both stay requirements; neither blocks the beta.
- **FR-COM-2** *(restated v1.12; the offline-grace design is withdrawn)* The entitlement decision
  MUST be made at the channel and nowhere else. Nothing installed on a user's machine may check an
  entitlement in order to run, author, build, check or import — so there is nothing for an offline
  grace window to protect, and the locally cached signed token with a grace period this
  requirement previously specified is withdrawn rather than left standing as a MUST nothing
  satisfies. A transient network failure MUST at worst delay a download; it MUST never block work
  on software already installed.
- **FR-COM-3** *(restated v1.12)* A refusal from the entitlement service MUST carry a stable
  machine-readable code and a plain-language remediation, and MUST never surface as a traceback or
  as a silent failure. Which codes exist is the entitlement service's own contract and is
  enumerated there, not here; the code `LICENSE_EXPIRED` this requirement previously named is
  withdrawn — it was specified and never issued. What a person reads MUST be a sentence saying
  what happened and what to do next; what a program reads MUST be the code. Guide resources, and
  every open-source surface, remain available in every account state.
- **FR-COM-4** *(amended v1.12; reverses "no auto-update, ever")* The toolchain MUST keep itself
  current by default, and MUST do so without ever interrupting work. Five properties bind together
  and none may be dropped in isolation: (a) *automatic by default* — a newer version MAY be fetched
  without being asked for, in a detached process of its own, so that no request is ever made on the
  path that starts a session and no start ever waits on one; (b) *never mid-session* — a fetched
  version becomes the running version only at the next start, so no session changes toolchain
  underneath itself; (c) *always reversible* — the version that was running before an update MUST
  remain installed, and all released versions MUST remain installable, so going back is one
  command; (d) *always pinnable* — a project MUST be able to hold itself on one version with a file
  in the project, and a pinned project MUST NOT be moved by any automatic path; (e) *switchable
  off* — a user-visible setting MUST offer automatic, notify-only and off, and `off` MUST stop
  every unrequested check. An automatic check MUST be rate-limited (not more than daily), MUST
  require a license key to have something to ask with, MUST NOT move a toolchain s0ma does not own
  (a project's own environment, a pinned project, an explicitly pointed-at checkout), and MUST fail
  silently: a failed update is recorded for `status` to report and never becomes an error in front
  of the user. A newer version MUST be surfaced as a non-blocking notice on a channel the user
  actually sees — today the launcher's `status` report and one session-start line — and the notice
  MUST NOT block, retry or prompt. *(The server startup log, `doctor` output and
  `s0ma://meta/changelog` that v1.1 named as the notice channels remain unbuilt; `doctor`'s license
  and update lines are labeled placeholders that contact nobody.)*
- **FR-COM-5** Nothing in FR-COM may violate INV-9 or P-6: no entitlement check may enter the
  runtime path of a built application.

### 7.6 `s0ma-studi0` — the visual development environment (FR-STUDI0) **[NEW v1.6]**

> v1 scope decided 2026-08-15 (`plans/notes/studi0-v1-scope-and-decisions.md`; execution plan
> `plans/s0ma-new-studi0-v1-1.md`). studi0 is the environment; **sh0w** is the graph renderer
> inside it. v1 shipped as a pure truthful viewer. **Agent narration + focus sync re-entered
> in v1.8 (FR-STUDI0-10), exactly as promised — by PRD amendment after its measured spike**
> (file transport beat an always-visible tool 19:1 on emissions, 8/18 vs 1/18 sessions).
> Proposed-component "ghosts", evidence badges, the pause protocol, and session retention
> remain deferred and re-enter only the same way.

- **FR-STUDI0-1** *(amended v1.12)* MUST ship as a separate distribution `s0ma-studi0` (module
  `s0ma_studi0`) launched by the `s0ma studi0` CLI subcommand. The subcommand discovers the package lazily:
  when it is not installed, the CLI prints a structured install hint — never a traceback — and
  `s0ma-dsl` gains no hard dependency on it (INV-6).
- **FR-STUDI0-2** MUST render the canonical component graph exclusively from existing
  deterministic artifacts — canonical `.s0ma.json` IR, `build.s0ma.json`, self-context — and
  MUST NOT execute the target application, parse ordinary source, infer structure
  heuristically, or make any model call (P-6). Registry-snapshot-backed live introspection is
  a post-v1 opt-in, not a v1 truth source.
- **FR-STUDI0-3** MUST consume the same graph export mechanism as every other consumer: the
  versioned `s0ma graph` payload produced by `s0ma-dsl` is the single graph contract, extended
  in place (never paralleled) when studi0 needs more. A duplicate extraction path is a defect
  (owner directive 2026-08-15: no duplicate mechanisms).
- **FR-STUDI0-4** MUST implement live refresh by observing build artifacts from the studi0
  process (hash/mtime polling). No watcher, daemon, or push channel may be added to
  `s0ma-core`, `s0ma-dsl`, or `s0ma-mcp` for visualization; v1 adds zero MCP surface.
- **FR-STUDI0-5** MUST present truth states honestly per the visual truth language
  (`plans/notes/studi0-visual-truth-language.md`): canonical vs stale distinguished via the
  manifest's recorded source hashes; a stale model is labeled last-known and never presented
  as current; structure implies neither verification nor health; state semantics are never
  color-only.
- **FR-STUDI0-6** MUST provide click-to-inspect for every rendered node and edge: intent,
  kind, layer, declared fields, and typed relationships with authored / derived / verification
  provenance.
- **FR-STUDI0-7** MUST be local-first: loopback-only HTTP, no telemetry, no network access in
  any path, no secret values displayed, and a fully self-contained page (no CDN or external
  asset).
- **FR-STUDI0-8** MUST eat its own dog food (INV-7; FR-MCP-11 pattern): the host is authored
  in the `.s0ma` DSL and ships committed deterministic build output plus a single handwritten
  bootstrap module; web assets (HTML/CSS/JS) are s0ma-owned via `content: @file(...)` embeds
  and hash-tracked in the manifest; studi0 can render its own self-model.
- **FR-STUDI0-9** MUST remain a viewer, not a second brain: no independent reasoning loop, no
  competing chat surface, and no writes to the target project's sources or artifacts.
- **FR-STUDI0-10** *(v1.8)* Agent narration, studi0-scoped by principle (owner 2026-08-16,
  D-11: no studi0, no narration). Transport is the measured winner — a file: while a studi0
  session is live on a project (presence file `.s0ma/studi0/active.json`, port + pid, written
  by `launch()` and withdrawn on clean shutdown; a dead-pid file counts as absent), the mcp
  survival rules carry ONE additional line asking the agent to append main-movement narration
  to `.s0ma/studi0/session.jsonl`; with no live studi0 the rules are byte-identical to the
  narration-free set and zero MCP surface is added (the rule is result content, not a tool).
  studi0 tails the session log on its existing artifact cadence and renders a narration pane
  under truth-language discipline: always attributed as self-reported agent narration, never
  presented as canonical fact; schema-invalid lines are counted and named, never rendered or
  repaired. Focus sync: a narration whose `subjects` name canonical ids present in the graph
  focuses them through the same selection path as click-to-inspect; unknown ids move nothing
  (GP-3 silence). The one qualified exception to FR-STUDI0-9's write ban is the presence file
  itself: exactly one marker under `.s0ma/studi0/`, never a source or build artifact.

### 7.7 Feedback (FR-FB) **[NEW v1.9]**

> Owner-approved 2026-08-27 (`plans/complete/s0ma-release-pipeline-feedback-1.md` §4, decisions
> FD-1..FD-13; product notes `plans/notes/feedback_function_notes.md`). Wire formats, error
> codes, vocabulary, the context allow-list (plan §5.5 = contract §5), redaction profile v1, and
> the local state layout are frozen in `docs/contracts/feedback-v1.md`; the architecture
> rationale is `docs/adr/ADR-004-feedback-architecture.md`. The narrow network/local-state
> exception this family relies on is stated in NFR-6.

- **FR-FB-1** consent modes `off` (default) / `suggest` / `standing` (deferred; per-item
  approval binds in every shipped mode; an agent-supplied approval claim is never trusted).
- **FR-FB-2** local preparation: deterministic redaction (profile v1) + allow-listed context
  only; no transcripts, prompts, source, raw logs, or hardware identifiers by default.
- **FR-FB-3** exact-payload approval with hash continuity (approved = transmitted = stored =
  receipt).
- **FR-FB-4** versioned envelope/receipt contracts; changes re-freeze the contract doc.
- **FR-FB-5** transport auth: scoped, expiring, revocable feedback token exchanged once from
  the license key; hash-at-rest; the license key never accompanies an envelope.
- **FR-FB-6** the `s0ma feedback` CLI family is the universal client-independent path.
- **FR-FB-7** MCP surface: `prepare_feedback` (pure, read-only) + `submit_feedback`
  (elicitation-or-refuse) + `feedback` prompt; honest annotations.
- **FR-FB-8** non-load-bearing: offline/failed submission preserves a local draft and an
  idempotent retry; identical idempotency keys yield one stored report.
- **FR-FB-9** server duties: validation, rate limits, sensitive-content rejection (never silent
  rewrite), atomic write + audit event, structured D-5 errors, definitive receipts.
- **FR-FB-10** operator inbox in the protected admin area; pseudonym-first identity; notes
  append as events; deletion honors FD-1 across D1 and controlled downstream copies.
- **FR-FB-11** product language says *pseudonymous / locally redacted*, never "anonymous".
- **FR-FB-12** the local telemetry sink is never uploaded wholesale; only §5.5-allow-listed
  extracts may enter an envelope, and remote telemetry (if ever) is a separate PRD amendment.

---

## 8. Non-functional requirements (NFR)

- **NFR-1 — Quality gates (binding, amended v1.2).** mypy `--strict` on `s0ma-core`; ruff on
  everything; full test suites green on Python 3.11/3.12/3.13 across the CI platform matrix
  (NFR-7); the spelling guard (INV-1); doc drift gate.
  One command runs it all: `uv run python scripts/check.py`.
- **NFR-2 — Test discipline.** The consolidation baselines (~1,555 core tests; the full DSL
  suite incl. 122+ fixture files and golden tests) are floors, not ceilings. New behavior ships
  with tests; golden/determinism tests are regenerated only via their documented mechanisms
  with diffs reviewed as mechanical-only.
- **NFR-3 — Versioning & releases.** Lockstep SemVer (INV-4); Keep-a-Changelog at the root;
  annotated tags `v<version>`; tag-triggered release workflow building all wheels. The line runs
  from `0.5.0` (consolidation) to `1.0.0` (GA, once the rename has soaked and `s0ma-mcp` is
  proven against real agent workloads). Which version is current is answered by the root
  `CHANGELOG.md` and the package `pyproject.toml` files, never by a number written here.
- **NFR-4 — Performance.** Build performance MUST scale with the content-hash cache: unchanged
  modules are not re-transpiled; doc rendering is content-hash-aware. Interactive commands
  (`check` on a single module) SHOULD complete in low single-digit seconds on a typical
  project — they are an agent's inner loop.
- **NFR-5 — Agent ergonomics as a requirement class (amended v1.5; number amended v1.13).**
  Context economy is a feature: the first-pointed teaching resource stays context-economical
  (under 4 KB, gate-enforced — the survival card, `s0ma://guide/survival-card`); comprehensive
  references may grow but MUST be honestly sized where they are pointed to and consulted
  per-topic rather than read whole; diagnostics are structured and actionable ("what rule,
  where, how to fix"); IR is the canonical machine-readable surface so agents never need to
  parse `.s0ma` or emitted Python themselves. *(v1.5 replaces "quick reference stays one page"
  — falsified empirically in benchmark pilot-01: the quick reference had grown to ~90 KB while
  the served instructions still claimed "one page", and the one agent that trusted the claim
  overflowed its context.)* *(v1.13 states the number the gate has always enforced — under
  4,096 bytes served — in place of "≤ 2 KB", which the card had exceeded since its first
  release.)*
- **NFR-6 — Security & isolation.** Example execution runs subprocess-isolated with
  configurable timeouts. MCP tools operate on explicit project roots passed by the client; no
  tool may write outside the given project tree. No network access in the load-bearing path.
  *Narrow feedback exception (v1.9):* the explicitly user-invoked feedback surfaces —
  `s0ma feedback` (CLI) and the `prepare_feedback`/`submit_feedback` MCP tools — MAY write the
  user-scoped feedback state directory (`~/.s0ma/`, outside every project tree) and MAY transmit
  a user-approved, locally-redacted feedback envelope over HTTPS to the control plane.
  Preparation is always local and network-free; submission always requires the per-item approval
  interaction (or, later, an explicit standing policy per FR-FB-1); feedback failures never alter
  any authoring, build, check, import, or runtime result; `s0ma-core` gains no feedback,
  credential, or network code (INV-9, INV-6). The frozen contract is
  `docs/contracts/feedback-v1.md`.
  *Narrow launcher exception (v1.12):* the launcher that starts s0ma for an agent host
  (`s0ma-launch`) MAY write the user-scoped state directory (`~/.s0ma/`, outside every project
  tree) and MAY make HTTPS requests to the control plane for three things and no others: the
  distribution manifest (which is also how `pin` checks that a version exists), the wheels that
  manifest names, and a one-off license-key check at `activate`. The license key travels only as an
  `Authorization` header and is stripped on any cross-origin redirect; nothing about a project, and
  nothing the user wrote, is ever sent. Installing a version invokes `uv`, which fetches from
  whichever Python package index the machine is configured to use; the launcher MUST hand it an
  environment with the license key removed. No such request may sit on the path that starts a
  session, and none may block, retry or prompt. `s0ma-core` gains no launcher, credential or
  network code (INV-9, INV-6).
- **NFR-7 — Platform (amended v1.2).** Python ≥ 3.11; macOS, Linux, and **Windows** are
  first-class, CI-enforced platforms (Windows added v1.2; native CPython, not WSL). `uv` is
  the development package manager of record; runtime deps stay minimal (`lark` is the DSL's
  only third-party runtime dependency; core has none outside optional extras). Artifact
  determinism (INV-5, P-4) holds **across** platforms: building the same input on any
  supported OS yields byte-identical artifacts.
- **NFR-8 — Licensing (amended v1.1; license amended 2026-08-10; v1.6 adds studi0; v1.11 relicenses `s0ma-dsl`; v1.12 relicenses the remaining two and opens distribution).** **Every distribution the monorepo ships is Apache-2.0**, so the model is open source plus a paid convenience channel (§7.5), not open core. `s0ma-core`: Apache-2.0, in perpetuity (INV-9; relicensed from MIT by owner decision 2026-08-10).
  `s0ma-dsl`: Apache-2.0 (relicensed from the commercial license by owner decision 2026-09-17;
  releases up to and including 0.18.1 remain under the license they shipped with).
  `s0ma-mcp` and `s0ma-studi0`: Apache-2.0 (relicensed from LicenseRef-Proprietary by owner
  decision 2026-09-18, superseding both the commercial split this requirement carried from v1.1
  and the studi0 decision of 2026-08-15). Two historical facts the superseded text carried stand:
  `s0ma-mcp` v0.5.0 as distributed to the initial testers shipped MIT, and `s0ma-studi0` shipped
  proprietary from its first release; releases up to and including 0.18.1 remain under the license
  they shipped with. Distribution (amended v1.9 to record the operating reality; amended v1.12, v1.14 and v1.15):
  **the codebase is released first, through GitHub alone** (owner ruling 2026-10-14). The public
  repository's first release is the source tree under its licences: the way in is to clone the
  repository and build the four packages from it, which is the one route the front door
  describes, and nothing that depends on an account — the entitlement-gated control plane, the
  keyed installer, the Claude plugin and extension, the feedback function's enrolment — is
  offered or described as a route by that release. The paid convenience channel of §7.5 is built
  and stays built, and it comes **after** the codebase release: the control plane and keyed
  installer (`plans/s0ma-hosting-entitlement-1.md`) serve wheels of all four packages from the
  owner's R2 bucket, and that channel — not the software — is what a subscription buys, once it
  is offered. All four packages are additionally published to PyPI
  from the first release cut of the public repository (owner decisions: 2026-09-18 for `s0ma-core`
  and `s0ma-dsl`, 2026-10-04 for `s0ma-mcp` and `s0ma-studi0`), so that a project's runtime and
  authoring dependencies are ordinary Python dependencies rather than machine-specific wheel
  paths, and so that each name is held by the project it belongs to; nothing built from the
  private source tree is ever published there. The bare name `s0ma` is to be held as well, by a
  small umbrella distribution that depends on the others (owner decision 2026-10-04); how it is
  versioned and where it lives is decided when it is built, before that first public release, and
  until then the name stays open. Publishing the software does not change what a subscription
  buys. A name on a public index is held only by publishing under it — configuring a trusted
  publisher reserves nothing. Released artifacts, once published to any public index, are never
  removed.

---

## 9. Non-goals (current horizon)

1. **Languages other than Python** as transpilation targets or host runtimes — for the current
   horizon only. *(Amended v1.15, owner ruling 2026-10-14: expanding to other languages is on the
   development roadmap and will be examined; this line records what the product does not do
   today, not a decision never to. Today a part written in another language is declared from the
   Python side as a reference — an `integration` naming an outside system, an `ADAPTER` nerve
   wrapping a call to it, a `CONSTANT` cell carrying a file verbatim — so it is in the model and
   in the dependency graph even though s0ma does not compile it.)*
2. **An LLM inside s0ma.** No bundled model calls; s0ma is the substrate agents stand on (P-6).
3. **PyPI publication in 0.5.0.** *(Superseded in v1.1; restated in v1.10; resolved in v1.12;
   widened in v1.14 — all four packages publish to PyPI from the first release cut of the public
   repository, by owner decisions 2026-09-18 and 2026-10-04, and the bare name `s0ma` is to be
   held by an umbrella distribution. NFR-8 is the authority on what is distributed and how. The
   earlier claim here that names are reserved by trusted-publisher setup was wrong and is
   withdrawn: a name is held only by publishing under it.)*
4. **An IDE/editor experience** (LSP, completions) — tracked as post-1.0 candidates, not
   required for the agent-first thesis. *(Amended v1.1: a minimal TextMate grammar for `.s0ma`
   syntax highlighting MAY ship pre-1.0 as a UX item; a full LSP remains post-1.0.)*
5. **Backwards compatibility with the letter-spelling era beyond `migrate-ext`.** The frozen
   repos (`s0ma-core`, `s0ma-dsl`) serve legacy users; the monorepo does
   not dual-support old extensions or config tables at runtime.
6. **A general-purpose web framework / ORM / app platform.** s0ma integrates with those; it is
   the self-model layer, not the application kitchen sink.

---

## 10. Success metrics

| # | Metric | Target |
|---|---|---|
| M-1 | Cold-start agent authoring: fresh agent + `s0ma-mcp` only, produce a valid documented module | ≤ 2 check/fix iterations |
| M-2 | Drift escapes: model-vs-reality discrepancies discovered downstream of a green `release`-mode CI run | 0 |
| M-3 | Determinism: repeated builds of an unchanged project | byte-identical artifacts, 100% |
| M-4 | Self-hosting: s0ma's own check pipeline (incl. bootstrap + self-model verification) | green on every commit to `main` |
| M-5 | Spelling guard violations reaching `main` | 0 |
| M-6 | Downstream migration (`ax0n`, `st3mcell`, `s0ma-bot`) onto ≥ 0.5.0 | each migrates via `migrate-ext` + guide with no manual artifact surgery |
| M-7 | Inner-loop latency: single-module `s0ma check` | ≤ ~3 s typical |
| M-8 | Retrofit self-sufficiency: an agent holding only the retrofit guide's opening card and the CLI converts one leaf module of an unfamiliar plain-Python codebase — parity clean, the project's own tests green, unaided (FR-DSL-8) | ≤ 2 check/fix iterations for that module |

---

## 11. Glossary

| Term | Meaning |
|---|---|
| **Self-knowledge** | The umbrella faculty: a system's ability to maintain an accurate, queryable, machine-readable model of itself — its structure, its runtime state, and the reasoning over that model. Spans three faculties (proprioception, interoception, metacognition). The product's organising idea; biological naming runs through the platform |
| **Proprioception** | The *structural* faculty of self-knowledge: the system's sense of its own structure — "what am I made of, how is it wired" — backed by the registry, structural verifier, dependency graph, layers, and IR edges |
| **Interoception** | The *internal/runtime-state* faculty of self-knowledge: the system's sense of how it is behaving versus how it declared it would — "how am I behaving vs. how I declared" — backed by the interoception verifier (runtime metrics vs. declared resource profiles), one of the four engines |
| **Metacognition** | The *reasoning* faculty of self-knowledge: reasoning over the model — "reasoning about my own model" — backed by the QueryEngine, impact analysis, extension-point guidance, and drift detection |
| **Self-model** | The queryable registry of components, edges, docs, and examples; load-bearing (P-1) |
| **Component** | A registered unit with name, kind, layer, intent, contracts, dependencies |
| **Declaration kind** | One of the language's fixed set of declaration forms, spanning code and documentation. The versioned language spec enumerates the set and defines each kind normatively (FR-DSL-1); this glossary names the class, not its members |
| **`nerve` / `cell` / `ganglion` / `axon`** | Four of the code declaration kinds — modules' functional units, data/constants, coordinators, cross-cutting connectors. Indicative, not the complete set; the spec is normative |
| **`doc-ref` / `doc-guide` / `example`** | The documentation declaration kinds — registry projection, narrative guide with live references and asserts, executable demonstration. Normative definitions in the spec |
| **IR** | The `.s0ma.json` intermediate representation — schema-versioned, the canonical machine-readable build artifact |
| **Import hook** | Core's import-time enforcement + transparent `.s0ma` loading |
| **Verifier** | One of four engines (structural, contract, interoception, coverage) checking model vs reality |
| **Drift** | Any divergence between declared model and actual code/docs; always a detectable failure |
| **Strictness modes** | `migration` < `dev` < `strict` < `release` — graduated enforcement |
| **Adoption ladder** | The ordered path a working plain-Python codebase takes to become a s0ma application — assess, set the perimeter, optionally register in place, convert module by module leaves-first, ratchet the strictness mode. Every rung is a place a project can honestly sit for weeks, with a command that reaches it and a number that says it was reached (P-8, FR-DSL-8) |
| **Perimeter** | The line a project declares around the code s0ma answers for, and the files it deliberately leaves outside: where its source lives, which files are plain-Python entry points, which are package markers, and which strictness mode it is held to. Setting one is never a claim that the code inside it has been converted (FR-DSL-8) |
| **Parity baseline** | The record of what a module's original Python offered — its public names, signatures, declared types, documentation and values — captured before that module is replaced, so the built replacement can be compared against it and every difference named (FR-DSL-8) |
| **Derived edge** | A relationship computed from code (`RAISES`, `TYPE_USES`); authoring one is an error (P-2) |
| **Dead-code pathology** | Coverage verifier's biological classification of unused components (phantom limbs, vestigial organs, …) |
| **studi0** | s0ma's visual development environment (`s0ma-studi0`): a local, read-only viewer launched by `s0ma studi0` that makes the self-model legible without reading code. Not a coding agent, not a second brain (§7.6) |
| **sh0w** | The live graph renderer inside studi0: draws the canonical component graph from build artifacts and refreshes as builds land, per the visual truth language |
| **Embodiment** | Physical parts brought inside the self-knowing boundary and declared as ordinary components, so the runtime holds the machine to its physical declarations. Hardware is *embodied*, never "modeled" (FR-X-4) |
| **Release channel** | The label a published documentation page carries saying which build it came from — *release*, *preview*, or *historical* — and therefore how far it can be trusted (FR-X-5) |
| **Mirror** | A committed copy of a document at a second path, produced from the one source and held identical to it by a byte-compare gate; a delivery of a document, never a second one (P-2) |
| **Naming law** | INV-1: always `s0ma`, never "soma" |

---

## 12. Document governance

- This PRD is **canonical for purpose and requirements**; the language spec is canonical for
  DSL semantics; the consolidation plan is canonical for the migration's execution; ADRs record
  point-in-time decisions. On conflict about *what the product should do*, this PRD wins; on
  conflict about *what the language means*, the spec wins.
- Amendments: edit via PR touching this file with the owner's approval; bump the document
  version header and note the change below. Agents MUST NOT amend Principles or Invariants as a
  side effect of implementation work.

### Change log

| Doc version | Date | Change |
|---|---|---|
| 1.0 | 2026-06-09 | Initial PRD for the consolidated monorepo (authored alongside `plans/s0ma-new-consolidation-1.md`) |
| 1.1 | 2026-06-10 | Owner-approved commercial model and UX requirements: INV-9 (runtime never gated); NFR-8 open-core licensing split + Model A PyPI distribution; new §7.5 FR-COM (entitlements, activation, offline grace, revocation diagnostics, update notification); FR-MCP-6..10 (prompts, self-model dogfooding, tool annotations, `project_status`, meta resources); FR-DSL-5 additions (`new project`, `doctor`); non-goals 3/4 amended. Authored alongside `plans/s0ma-new-ux-phase-1.md`. |
| 1.2 | 2026-06-10 | Owner-approved platform expansion: NFR-7 adds **Windows** as a first-class, CI-enforced platform (native CPython; not WSL) and makes artifact determinism explicitly cross-platform; NFR-1 gates now bind across the CI platform matrix. Grounded in the 2026-06-10 empirical compatibility check (full gate on `windows-latest`: mcp/ruff/mypy/spelling green; 15 test failures in 4 root-cause clusters). Authored alongside `plans/s0ma-new-windows-support-1.md`, which carries the evidence and fix milestones. |
| 1.3 | 2026-06-10 | Owner-approved self-hosting commitment: new FR-MCP-11 — `s0ma-mcp` itself authored in the `.s0ma` DSL (sources are `.s0ma` modules; the wheel ships committed deterministic build output + a single handwritten bootstrap module; the MCP surface is derived from the self-model registry; mypy `--strict`/`py.typed` retained). Promoted from post-1.0 exploration to the GA path, feasibility-gated by a go/no-go spike, and sequenced strictly after the v1.2 Windows/determinism work. Authored alongside `plans/s0ma-new-mcp-selfhost-1.md`. |
| 1.4 | 2026-06-17 | Owner-approved self-knowledge repositioning: the product line is reframed from a "software proprioception platform" to a "software **self-knowledge** platform" (umbrella) spanning three faculties — **proprioception** (structure), **interoception** (runtime state), and **metacognition** (reasoning over the model), each mapped to existing machinery (§1, §3). New glossary entries for Self-knowledge, Interoception, and Metacognition; the Proprioception entry rewritten as "the structural faculty" (§11). New principle **P-9 — Placement, not architecture** (s0ma prescribes where components live and enforces reachability, but does not prescribe an application architecture). Proprioception is now the *structural* faculty within self-knowledge; earlier/frozen uses of the term are retained as historical context and are not retroactively edited (the root CHANGELOG documents the terminology evolution). Authored alongside `plans/s0ma_stds_usability_upgrade_plan-1.md` (milestone M1). |
| 1.5 | 2026-07-08 | Owner-approved NFR-5 amendment (pilot-01 evidence): "quick reference stays one page" → "the first-pointed teaching resource stays context-economical (≤ 2 KB, gate-enforced)"; comprehensive references may grow but must be honestly sized and consulted per-topic. Grounded in the pilot-01 benchmark (one successful teaching read across six runs; the 89 KB quick reference overflowed the reading agent's context) and shipped in 0.10.0 as `s0ma://guide/survival-card` with a release-gate size test. Authored alongside the pilot-01 improvement batch (`s0ma-bench` memo, branch `pilot01-improvements`). |
| 1.6 | 2026-08-15 | Owner-approved studi0 introduction: fourth distribution `s0ma-studi0` (module `s0ma_studi0`; launched by `s0ma studi0`) — studi0, the visual development environment hosting the sh0w graph renderer. §3 product table gains the Visualization layer; INV-2 adds the stable module name; INV-6 adds the `s0ma-studi0 → s0ma-dsl → s0ma-core` leaf dependency direction with lazy CLI discovery; new §7.6 FR-STUDI0-1..9 (proprietary distribution, artifact-only truth sources, single graph-export mechanism, artifact-watching live refresh with zero new MCP surface, visual truth language compliance, click-to-inspect, local-first, `.s0ma` self-hosting with `@file`-embedded assets, viewer-not-a-brain); NFR-8 adds `s0ma-studi0` to the commercial side (owner decision 2026-08-15). Glossary adds studi0 and sh0w. v1 scope: pure truthful viewer — narration/ghosts/evidence/pause/retention deferred, re-entering by PRD amendment after measured spikes. Authored alongside `plans/notes/studi0-v1-scope-and-decisions.md` and `plans/s0ma-new-studi0-v1-1.md`. |
| 1.7 | 2026-08-17 | Runtime honesty amendment (M10): FR-CORE-9 added — the manifest-driven runtime bootstrap (`s0ma.bootstrap.bootstrap_imports`, stdlib-only) is `s0ma-core`'s; FR-DSL-4 drops the bootstrap claim (deprecated delegating re-export stays per INV-2); INV-9 note records the relocation and names the emitted-modules boundary (runtime-free emission) as the open design round. Evidence: narration-spike acceptance confound (core-less venv, ModuleNotFoundError s0ma_dsl; agent-invented shadow implementation — now Patterns §28.5 anti-shadow rule). Shipped in 0.16.2. |
| 1.8 | 2026-08-17 | Narration re-enters by measurement (M11): new FR-STUDI0-10 — file-transport agent narration conditioned on a live studi0 session (D-11), served as one survival-rules line (zero MCP surface change), ingested from `.s0ma/studi0/session.jsonl`, displayed under truth language with focus sync; §7.6 preamble updated (narration leaves the deferred set the promised way; ghosts/evidence/pause/retention stay deferred). Spike evidence: V2 file+rules 19 valid emissions across 8/18 sessions vs conditional tool 1/18; mainline re-measure 3/3 first-contact sessions at 100% validity (the spike's 44% decomposed to ~61% delivery × ~70% compliance — delivery ceiling documented as the tuning lever). Shipped in 0.17.0. |
| 1.9 | 2026-08-27 | Owner-approved feedback function + distribution truth: new §7.7 FR-FB-1..12; NFR-6 narrow feedback exception; NFR-8 records keyed-R2 beta distribution (PyPI = future owner decision). Authored alongside plans/s0ma-release-pipeline-feedback-1.md and plans/notes/feedback_function_notes.md; contract: docs/contracts/feedback-v1.md; ADR-004. |
| 1.10 | 2026-08-30 | Owner-approved D-6 amendment (doc-function initiative, milestone G1). **Enumerations deferred to the versioned spec:** FR-DSL-1 (declaration kinds), FR-DSL-2 (namespaces), FR-DSL-3 (pipeline stages), FR-DSL-7 (front-matter fields) and the two glossary declaration rows now state the product invariant and hand the current list to the spec, completing the delegation FR-DSL-1 already declared. **Obsolete concrete claims corrected:** the front-matter field count (eight → the spec's, which is seven since 0.17.0), the four-kind and four-namespace counts (eleven and five today), NFR-3's pinned current line, FR-MCP-11's unmet-precondition wording (the self-hosting conversion has landed), §7.5's build-timing note, non-goal 3's superseded note (realigned to NFR-8), and four plan paths that moved to `plans/complete/`. **Gaps closed:** new FR-X-4 (hardware is *embodied*, design authority ADR-003), new FR-X-5 (release / preview / historical documentation channels, codifying doc-function decision D-8), a mirror sanction sentence in P-2, and glossary entries for all three. Evidence: `plans/notes/doc-function-g1-prd-amendment.md`; audit `plans/notes/docs-audit-28AUG2026.md` §3.2. |
| 1.11 | 2026-09-17 | Owner decision: `s0ma-dsl` relicensed Apache-2.0 (from the commercial license); NFR-8 amended to name the license of each distribution separately, and §7.5 gains a scope note — the language, compiler and `s0ma` CLI are no longer subscription-gated, and activation applies to `s0ma-mcp` and the hosted convenience channel. `s0ma-mcp` and `s0ma-studi0` are unchanged. The owner's stated intent to open-source the whole monorepo before the public repository is created is recorded as pending, not decided. No principle or invariant changes. |
| 1.12 | 2026-09-18 | One consolidated amendment for the beta-release-prep work, on the owner's instructions of 2026-09-17 and rulings of 2026-09-18. **Retrofit becomes product surface:** new FR-DSL-8 states the six invariants of converting a codebase that has never known s0ma — static only, a read writes nothing, one module at a time, the original is never modified, a draft is unfinished by construction, parity is taken first and names every difference — and defers the command enumeration to the generated command reference, as v1.10 deferred the language enumerations to the spec; new metric M-8 (an unaided agent converts one leaf module of an unfamiliar codebase in ≤ 2 check/fix iterations); new glossary entries for *adoption ladder*, *perimeter* and *parity baseline*. **P-8 is strengthened** to say that the stepwise path covers code that has never known s0ma, not only projects already inside it — this is a principle change, made deliberately and not as a side effect. **The update model is reversed:** FR-COM-4's "no auto-update, ever" becomes automatic-by-default under five binding properties (never mid-session, always reversible, always pinnable, switchable off, rate-limited) plus four refusals, and its notification half is corrected to the channel the notice actually reaches; NFR-6 gains a second narrow exception for the launcher's state directory and its three control-plane requests, written in the shape of the v1.9 feedback exception. **The commercial model is restated:** §7.5 becomes open source plus a paid convenience channel — the subscription buys installation, updates, the integration and support, never permission to run the code — with what a lapse truly costs stated as binding and the owner's direction beyond that marked as direction, and with no price, date or duration anywhere. **Three requirements that described unbuilt things are made honest:** FR-COM-1 names what is built and names the device-code login and organization seats as not built; FR-COM-2's locally cached token and offline grace window are withdrawn (nothing on a user's machine checks an entitlement at all, and nothing may); FR-COM-3's `LICENSE_EXPIRED` is withdrawn (it was specified and never issued) and the requirement is restated around a stable code plus a plain-language remediation. **Licensing and distribution:** NFR-8 relicenses `s0ma-mcp` and `s0ma-studi0` Apache-2.0, so every distribution is Apache-2.0 and FR-STUDI0-1 ships a *separate* rather than a *proprietary* distribution; `s0ma-core` and `s0ma-dsl` are additionally published to PyPI from the first release cut of the public repository — nothing built from the private source tree is published there — and non-goal 3 is resolved accordingly, withdrawing its incorrect claim that trusted-publisher setup reserves a name. The header's owner cell drops the separate consultancy name. **P-8 changes; no invariant changes.** Evidence: `plans/notes/beta-prep-prd-amendment-draft.md`; owner actions `plans/notes/beta-prep-owner-actions.md` (O-1, O-4, O-5; rulings R-1…R-5); `plans/s0ma-beta-prep-1-retrofit.md` D-6, `plans/notes/claude-integration-prd-amendment-draft.md`, `plans/notes/apply-apache-everywhere.md`, `plans/notes/front-door-a4-licence-options.md`. |
| 1.13 | 2026-09-29 | Owner ruling: NFR-5's number follows its gate. The survival card is "under 4 KB, gate-enforced" — the release gate has asserted under 4,096 bytes served since the card shipped, while the text said "≤ 2 KB", which the card exceeded from its first release (2,068 bytes). The card is 3,378 bytes after its minimal module gained the lines 0.14 requires. The requirement itself — one context-economical resource pointed to first, comprehensive references honestly sized — is unchanged. Recorded in the 0.14.0 schema-and-surface-budget contract as revision R4. |
| 1.14 | 2026-10-04 | Owner ruling: every package's name is published. NFR-8's distribution paragraph and non-goal 3 now say that all four packages — `s0ma-mcp` and `s0ma-studi0` beside `s0ma-core` and `s0ma-dsl` — are published to PyPI from the first release cut of the public repository, and that the bare name `s0ma` is to be held by a small umbrella distribution built before that release. The reasons: a name is held only by publishing under it (all five were unclaimed when checked on 2026-10-04, and the letter-o spelling already belongs to an unrelated project), and the channel, not the software, is what a subscription buys, so withholding two wheels protected nothing. Unchanged: nothing built from the private source tree is ever published there. No principle and no invariant changes; how the umbrella distribution is versioned is decided when it is built. |
| 1.15 | 2026-10-14 | Owner rulings of 2026-10-14, made while reviewing the documentation for the public repository's first release. **Non-goal 1 is a horizon, not a verdict:** languages other than Python stay outside the current horizon, and the line now says expanding to other languages is on the development roadmap and will be examined, with the way a part in another language is declared from the Python side today recorded beside it. **The codebase is released first, through GitHub alone:** NFR-8's distribution paragraph now says the public repository's first release is the source tree under its licences, reached by cloning and building, with nothing that depends on an account offered or described as a route by it, and that the paid convenience channel of §7.5 comes after that release; §7.5 says the same in one sentence and conditions its two ways in on the channel being offered. PyPI publication from the first release cut, the umbrella name and the never-removed rule are unchanged. No principle and no invariant changes. Evidence: the root README and the pages carried through on branch `pre-release-doc-updates-1`, recorded in the changelog under Unreleased. |
| 1.16 | 2026-10-14 | Owner rulings of 2026-10-14, second set, from the same documentation review. **MCP is one channel, not the way in:** §1's end state no longer says a coding agent "connects to a s0ma project over MCP" — it opens the project from the checkout, with the `.s0ma` sources, the committed artifacts and the `s0ma` command line, or over MCP where its host offers that — and persona P1 says the same; `s0ma-mcp` and its requirements (§7.3) are unchanged. **Two ways an agent meets s0ma, kept distinct:** a new §1 subsection separates the coding agent building or maintaining a s0ma application (efficiency, captured intent, enforcement; P1) from an LLM or agent using or operating one, which the running system hands its own model to through the self-context and the runtime query surfaces (autonomy and safety; P4 now names that agent beside the human stakeholder). No principle and no invariant changes. |
