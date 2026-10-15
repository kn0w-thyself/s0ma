# Building an app with s0ma over MCP — walkthrough

This is the practical, end-to-end guide for using the **s0ma authoring MCP server** (`s0ma-mcp`, server name `s0ma-authoring`) to design, build, and verify a s0ma application with a coding agent. It assumes any MCP-capable agent host — anything that can run a stdio MCP server and read a project instructions file — plus `uv` as the package manager and Python ≥ 3.11 on macOS, Linux, or Windows (all three are CI-enforced platforms). Where a step needs a concrete command only one host has, Claude Code is the worked example and is labelled as such; everything else reads the same wherever you work. Deeper reference: `packages/s0ma-mcp/README.md` (the server's own README — tools, annotations, resources, the self-hosted layout) and the agent guides the server serves as resources.

---

## 1. Install

This page does not describe the install, because the install is written down once elsewhere and a second account of it would only drift. Take what you need from these two pages, then come back:

- **The route** the public repository offers — clone the repository and build from it — is stated once in [`getting-started.md` §1](getting-started.md#1-create-a-real-project).
- **Its commands** — building the wheels from a checkout, or working straight out of the monorepo with `uv sync` — are in the root [`README.md`](../README.md) "Install" section.

One fact from those pages that the rest of this walkthrough leans on: s0ma is **not on PyPI** yet — all four packages are published there from the first release cut of the public repository (the single authority is [PRD](../references/s0ma-prd.md) **NFR-8**) — so there is no `pip install` route to fall back on, and the authoring server you are about to register runs **locally** — what s0ma sends anywhere is the subject of [`trust-model.md`](trust-model.md).

Sanity check whichever route you took:

```bash
uv run s0ma doctor
```

It should report every s0ma package at the same version; they are released as a set. (`s0ma-mcp` itself starts a stdio server and blocks — that is correct behavior, not a hang; don't run it bare to "test" it.)

## 2. Point the agent at the server

The fact your host needs is a small one: `s0ma-mcp` is a **stdio MCP server**, started by running `uv run s0ma-mcp` in the app directory (or plain `s0ma-mcp` when the wheels are installed globally). Every MCP-capable host has somewhere to record that — a project-level `.mcp.json`, a settings file, a configuration UI. Add it there under the name `s0ma`.

Worked example, Claude Code — from the app directory:

```bash
claude mcp add s0ma --scope project -- uv run s0ma-mcp
```

From a monorepo checkout the same command works from the repo root. With a globally installed wheel it is just `claude mcp add s0ma -- s0ma-mcp` — which is what `s0ma doctor` prints as its registration hint and what the installer runs, so the hint you will see quoted by the tooling is this one. `--scope project` writes `.mcp.json` into the repo so every session (and teammate) inherits the server; that file is the portable form, and a host that reads `.mcp.json` needs nothing further. Omit the flag for user-scope.

However you registered it, verify the same way: have your host list its connected servers (`/mcp` in Claude Code) — you should see server `s0ma-authoring` — then compare its served names and schemas with the generated inventory in the [`s0ma-mcp` README](../packages/s0ma-mcp/README.md#served-surface).

Two ergonomics notes worth knowing on day one:

- **Tool annotations are honest** (FR-MCP-8): `project_status`, `check`, `inspect_module`, and `describe_server` are marked read-only/non-destructive, so you can safely auto-approve the agent's inner loop and keep approval prompts for the writers. The explicit `verify_host` exception executes trusted project code and advertises destructive, non-idempotent, open-world risk.
- **Five prompts ship with the server** (`author_module`, `fix_check_failures`, `migrate_project`, `diagnose_fault`, `feedback`) — the first four encode the canonical authoring and operating journeys so you don't have to type the workflow out, and `feedback` walks the tell-the-s0ma-team path ([what s0ma trusts: feedback](trust-model.md#feedback-nothing-leaves-without-you); it needs the feedback access a keyed install gives a machine, where a bug report or a discussion on the repository needs nothing). A host that supports MCP prompts surfaces them as slash commands (that is how they appear in Claude Code); on a host that does not, name the prompt to the agent and it will follow the same journey.

## 3. First contact: orient the agent

Before any work, have the agent do three cheap things (or put them in the project's agent-instructions file per §5, so it always happens):

1. **Read `s0ma://guide/system-prompt`** — the alignment document: what s0ma is, the rules of the DSL, how to behave. This is the single most important context for compliant output.
2. **Hold `s0ma://guide/survival-card` in context** — deliberately under 4 KB (NFR-5): the bootstrap loop, the body rules, and one minimal valid module. `s0ma://guide/quick-reference` lists every kind of declaration and every line each may carry, generated from the language itself — look topics up there rather than reading it whole (the same facts as data: `s0ma://guide/quick-reference.json`).
3. **Call `project_status(project_root)`** — one call answering: is this a s0ma project, which strictness mode, what is built/stale, which modules are mapped versus roster-only, and which validated `next_actions` are available (on a fresh directory it will point you at `init_project`, which writes the `[tool.s0ma]` table). Always pass explicit absolute `project_root` arguments; tools never write outside the given tree (NFR-6).

The other resources, when needed: `s0ma://guide/errors` (every diagnostic code with remediation), `s0ma://spec/current` (the full language spec, for deep questions — it carries its own spec version, deliberately decoupled from the release version), `s0ma://meta/changelog` and `s0ma://meta/version` (what's new / what's running), and `s0ma://self/model` (the server's own live component graph — also proof of what a finished s0ma app looks like, since the server is itself authored in the DSL).

### If the tree already has working Python in it

`project_status` answering "this is not a s0ma project" has two very different meanings, and the rest of this walkthrough only covers one of them. An empty or near-empty directory is a fresh start: call `init_project` and carry on to §4. A tree that already holds a working application is a **retrofit**, and it is a different job — the code cannot be stopped and rewritten, so it is converted a module at a time over weeks, with the application working throughout.

Find out which you are in with one command, from a terminal in that tree:

```bash
uv run s0ma adopt status
```

It answers at every rung, including on a tree that is not a s0ma project at all (that is rung 0), it writes nothing and never imports the code it reads, and it ends in the single next command to run. From there the whole path — the ladder, the six `s0ma adopt` commands, and the rule that a baseline is taken before anything is deleted — is one page, and this walkthrough does not keep a second copy of it:

```bash
uv run s0ma docs show doc:guide/retrofit-existing-codebase
```

The first command that page asks for is `s0ma adopt scan`, which reads the tree and writes nothing, so it is safe to run before agreeing anything with the person you are working for.

## 4. Designing the app (and evolving the design/PRD) through s0ma

The s0ma way to "design" is to make the self-model the design artifact (P-1: the self-model is load-bearing). Concretely:

- **Start the project:** `uv run s0ma new project` (guided: writes `[tool.s0ma]` into pyproject.toml, scaffolds the first module, runs the first build, prints the runtime bootstrap snippet) — or have the agent drive `scaffold_module` per module. Set `mode = "migration"` or `"dev"` in `[tool.s0ma]` to start; since 0.8.0 the toolchain actually reads this table (CLI `--mode` still wins when passed).
- **Design = declarations before bodies.** A design session with the agent produces `.s0ma` modules whose declarations carry the architecture: module `layer:` (DOMAIN/APPLICATION/PRESENTATION/INFRASTRUCTURE/FRAMEWORK — the reachability matrix enforces layering at check time), declaration kinds (`nerve` = functional unit, `cell` = data/constants, `ganglion` = coordinator, `axon` = cross-cutting connector), one-line `intent:` on everything (these are product copy — they become the queryable design rationale and, for served surfaces, user-visible descriptions), `depends_on:` edges (including the 0.8.0 qualified `module.declaration` form for cross-module edges), `expects:`/`guarantees:` contracts, and `metadata:` for app-specific design facts (a flat key→scalar/list map that rides the IR and the runtime registry — first-class as of 0.8.0). A `nerve` or `ganglion` also carries a `forbids:` line: what it must never do, however it is called, with `none` when it rules nothing out.
- **Keep the human PRD as markdown; encode the binding decisions as declarations.** Prose PRDs drift; declarations cannot (P-3). The narrative layer that should *not* drift goes in `doc-guide`/`doc-ref` declarations — rendered, content-hashed, and byte-compare drift-gated, with live references into the registry. A good pattern: PRD.md holds vision and requirements; a `doc-ref` with `covers: [nerve where visibility == PUBLIC]` auto-renders the API reference; `doc-guide`s hold the architecture narrative with `asserts:` that break when the design changes underneath them.
- **Reviewing and adjusting the design:** the agent reads the design back with `inspect_module` and `s0ma://self/model` once built. Built modules return canonical `.s0ma.json` IR; a roster-only Python module instead gets an import-free, explicitly `DERIVED (unverified)` structural sketch that cannot satisfy a score or gate and points toward componentization. Design changes are edits to declarations (intent, contracts, edges, layers) followed by the loop in §5; the check gate tells you immediately if the new design violates layering, namespaces, or coverage rules. For "what breaks if X changes?" questions, structured dependency-neighbor actions answer from the model before grep.

## 5. Making the agent — and every sub-agent — write compliant code

The deep answer is that **compliance is structural, not behavioral**: the DSL refuses to parse undeclared components, `check` refuses non-compliant modules with exact remediations, and the import hook refuses unregistered code at load time (P-7, defense in depth). An agent literally cannot land non-compliant code through the MCP tools — what discipline buys you is *fewer iterations*, not safety. To get one-or-two-attempt authoring (the M-1 success metric):

- **Put a standing block in the app repo's agent-instructions file** so every session and sub-agent inherits it. The cross-tool convention is `AGENTS.md` at the project root, and s0ma writes one: `s0ma new project` scaffolds a canonical, agent-agnostic AGENTS.md carrying these rules in full, so on a scaffolded project the step is already done and that file is the one to grow. (It also writes a one-line `CLAUDE.md` — exactly `@AGENTS.md` — because Claude Code reads `CLAUDE.md` and expands `@` imports; that is a pointer, not a second copy. A host with its own instructions filename wants the same one-line pointer.) For a project that predates the scaffolder, or one you wired up by hand, this is the block, paste-ready:

```markdown
## s0ma rules (all agents, including sub-agents)
- This is a s0ma project. Author components as .s0ma declarations via the s0ma-authoring MCP server — never as bare Python files.
- Before first authoring in a session: read s0ma://guide/system-prompt; keep s0ma://guide/survival-card (under 4 KB) in context; look declarations and their lines up in s0ma://guide/quick-reference per topic (do not read it whole). Orient with project_status; if is_project is false, call init_project first.
- The loop is scaffold_module → edit → check → build_project. Run check after EVERY edit; fix by the diagnostic's `remediation` text, highest severity first (or run the fix_check_failures prompt).
- Authoring discipline: single-line `intent:` on every declaration (it is product copy); parameterize every generic (`dict[str, Any]`, never bare `dict`); `X | None`, never `= None` defaults on typed params; body docstrings are served/registered copy — write them deliberately; imports go in module-header `requires:` (use `deferred_requires:` for fail-per-call resilience); never hand-edit anything under the build directory.
- Pass explicit absolute project_root to every tool call. Do not change `[tool.s0ma].mode` without being asked.
```

- **Sub-agents:** a host that loads the instructions file for its own sub-agents covers them for free; for programmatic sub-agents (an agent SDK, custom orchestration), inline the same block in each sub-agent's prompt and attach the survival-card resource content — deliberately under 4 KB, sized to be held in context whole; sub-agents look details up in the quick reference per-topic. A sub-agent that only edits `.s0ma` through the MCP tools cannot silently de-comply; the gate in §6 catches everything else.
- **Ratchet the strictness mode as the app matures** (`migration` → `dev` → `strict` → `release` in `[tool.s0ma].mode`): adopt incrementally exactly as the platform itself did. `release` mode is the full production gate — public doc-refs, embedded examples, and test coverage become hard requirements (DSL `test` declarations, or `covered_by:` to credit an external pytest suite honestly).

## 6. Verifying compliance after the code is written

Layered verification, cheapest first — this is the app-side equivalent of the monorepo's own `scripts/check.py` gate:

1. **`uv run s0ma check <project-root>`** — the parse/semantic/layering/coverage gate, exit-code-true and CI-ready; add `--format json` for structured findings. Mode comes from `[tool.s0ma].mode` (raise it here first when ratcheting).
2. **`uv run s0ma build <project-root> --check`** — drift gate: rebuilds and byte-compares against the existing build output; nonzero exit means sources and artifacts have drifted (someone edited generated code, or didn't rebuild after a `.s0ma` edit). Builds are deterministic and machine-path-free (INV-5), so if you commit build output this doubles as a committed-build equality gate — the platform's own `selfhost-build` stage is the worked example.
3. **`uv run s0ma docs check-drift <project-root>`** — the documentation byte-gate: rendered doc-guides/doc-refs must match their sources exactly.
4. **`uv run s0ma test <project-root>`** — project-aware pytest invocation (DSL `test` declarations execute via the wrapper-import recipe documented in the doc-subsystem guide).
5. **Runtime backstops:** the example runner (`run_example` / `s0ma examples run`) executes `example` declarations subprocess-isolated; core's import hook in strict mode raises `UnregisteredComponentError` for unregistered public code at import time; the four-verifier engine (`s0ma verify`) compares the declared model against observed reality on the running system.
6. **Optional but now cheap:** `mypy --strict` over your app including emitted code — core and dsl both ship `py.typed` as of 0.8.0, and the emitter's output is strict-clean by construction (the platform gates its own emitted code this way).

For CI, wire 1–4 into a single workflow step per platform; the monorepo's `.github/workflows/ci.yml` + `scripts/check.py` are the reference implementation (ubuntu + windows matrix, one gate command, exit 0 or red).

---

## Appendix: the surfaces at a glance

The current tool, resource, and prompt inventory is generated from the served
surface snapshot in the [`s0ma-mcp` README](../packages/s0ma-mcp/README.md#served-surface).
That gate compares live names, annotations, and input/output schemas before the
inventory is rendered, so this walkthrough does not maintain a second list.

**Language since 0.8.0, in one line:** declarations carry `metadata:` (flat authored map → IR → runtime registry), `serves_as:` (public name ≠ identifier), `covered_by:` (external test credit); modules carry `deferred_requires:` (per-call imports) and qualified `depends_on: module.declaration` edges; `[tool.s0ma].mode` is read for real; builds are deterministic, docstrings interpreter-independent, and the whole transpiler is mypy `--strict`-clean with `py.typed`.
