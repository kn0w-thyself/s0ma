## Getting started: prove the self-model is useful

This is the canonical cold-start journey for s0ma. It is embedded in the root
README and served to coding agents as `s0ma://guide/getting-started`; if either
copy differs, the repository gate fails.

### s0ma in 30 seconds

**The problem:** code, architecture prose, and an agent's mental model drift
apart, so a green test suite can coexist with an application nobody can
reliably explain or operate.

**Who it is for:** anyone building agents, agent harnesses, AI-enabled
applications, or autonomous software and hardware systems, and any team
maintaining a system where component intent, dependency boundaries, generated
documentation, and runtime evidence need to remain queryable and release-gated
— with or without a coding agent in the loop.

**The concrete outcome:** authored declarations compile to ordinary Python plus
canonical IR, dependency facts, documentation, tests, and a bounded runtime
self-context. Humans and agents can ask what exists and why, while CI rejects
drift, hollow registration, unresolved semantic debt, and unproven host imports.

**Two ways an agent meets s0ma, kept distinct:** a coding agent *building or
maintaining* a s0ma application reads the self-model instead of reconstructing
the system from source, authors intent and contracts the compiler then holds
the code to, and works inside guardrails that refuse an undeclared or drifted
change — from the checkout with the `s0ma` command line, or through the
authoring MCP server when its host speaks MCP; MCP is one channel, never a
requirement. An LLM or agent *using or operating* a s0ma application is handed
the system's own model through the self-context and the runtime query surfaces,
so it can ask what the system is made of, what each part promises and what
would break, and be answered by the system rather than by a guess. The first
gains efficiency, captured intent and enforcement; the second gains autonomy
and safety, and what it is told is quoted project data, never an instruction.

**When not to use it:** do not adopt s0ma for a throwaway script, a project
with no Python in it, a project that cannot accept generated Python, or a team
unwilling to make component intent and boundaries part of its release contract.
s0ma compiles Python today: parts written in other languages are declared from
the Python side as references, and more languages are on the roadmap. s0ma does
not include an LLM — it is as useful without one — and is not a replacement for
application tests or observability.

The toolchain's four packages have distinct jobs: **s0ma-core** is the Apache-2.0
runtime — the registry every part is declared into, the verifiers, and the
surfaces that answer what exists and why; **s0ma-dsl** is the Apache-2.0
authoring language, compiler and `s0ma` command line; **s0ma-mcp** is the
Apache-2.0 authoring server a coding agent works through when its host speaks
MCP; **s0ma-studi0** is the
Apache-2.0 local visual environment (`s0ma studi0`) hosting the sh0w graph
renderer — an early preview, with more coming. Those are the licenses as they
stand today; each package's own `LICENSE` file is the authority.

### 1. Create a real project

<!--
Single-source rule (the G6 rule, narrowed to one route for the public
repository's first release). The route below is stated here and nowhere else:
this section is the canonical route summary, and the root README's generated
getting-started region is its byte-for-byte mirror. The route's mechanics —
the clone, the sync, the wheel build and the install into a project — live on
exactly one page, the root README's "Install" section, and every other page
points there rather than restating them. Do not add a second copy, and do not
restate the mechanics here: the rule is enforced by
packages/s0ma-dsl/tests/test_docs_guide_bindings.py.
-->

If the `s0ma` command is not installed yet, there is one way in today, and it
is written down once — **the source route**: clone this repository and build
from it. The root `README.md` "Install" section has the exact commands, both
for working inside the checkout and for building the wheels and installing them
into a project of your own. s0ma is not on PyPI yet: all four packages are
published there from the first release cut of the public repository (PRD
NFR-8), so until then `pip install s0ma-core` will not work.

Then create a project:

```bash
s0ma new project my-app
cd my-app
```

The command creates a feature-first project, authored `.s0ma` modules, a
load-bearing app map, tests, agent instructions, and a deterministic `build/`
directory. Generated Python is an artifact: edit `.s0ma`, never `build/*.py`.

Every kind of declaration a `.s0ma` file may hold, and every line each one
may carry, is on one page that the documentation build generates from the
language itself — the quick reference: `docs/reference/quick-reference-readable.md`
in a checkout, and `s0ma://guide/quick-reference` to a coding agent (the same
facts as data at `s0ma://guide/quick-reference.json`). Look a line up there
rather than guessing at it.

**Already have a codebase?** `s0ma new project` starts from an empty folder. An
application that already works takes the other way in, and it is written down
once: `docs/guides/retrofit-existing-codebase.md` walks the adoption ladder a
module at a time, over weeks, leaving the code working at every rung. The first
command is `s0ma adopt scan`. It reads the tree, says what is in it and what to
convert first, and writes nothing anywhere — no report file, no cache — so it
is safe to run before anything has been decided.

Run the static release checks. These commands do not import application code:

```bash
s0ma check --mode release
s0ma score --gate-mode release --gate
```

Both commands should exit zero in the fresh project. `--mode` selects authoring
strictness; `--gate-mode` is caller-owned evaluation policy. A project cannot
lower its own release threshold.

### 2. Ask the model what exists

Register the authoring server with your MCP client, then use the served tools:

```text
project_status(project_root="/absolute/path/to/my-app")
inspect_module(project_root="/absolute/path/to/my-app", module="core_domain")
```

`project_status` is the first call in an unfamiliar tree: it reports project
posture, modeled versus roster-only modules, build freshness, semantic debt,
runtime/runbook facts, and validated next actions. `inspect_module` returns the
canonical tagged IR for `core_domain`, including its declared dependencies and
structured dependency-neighbor actions. The starter component has no component
dependency, and that empty edge set is useful evidence rather than an invented
relationship. As the project grows, follow the returned `inspect_module`
actions to inspect `depends_on` and `depended_by` neighbors before grepping.

If no MCP client is connected yet, the equivalent human-oriented survey is:

```bash
s0ma inspect --all
s0ma inspect core_domain
```

### 3. See the guardrail work

Make a harmless temporary edit to the generated file
`build/core_domain.py`—for example, add a comment—then run:

```bash
s0ma build .
```

The build must refuse with `GENERATED_FILE_DRIFT`: s0ma will not silently erase
a hand edit. Recover by discarding that generated-only edit and rebuilding from
the authored source:

```bash
s0ma build . --force
```

Now temporarily change the authored `guarantees:` value in
`src/core/core_domain.s0ma` to
`pending("replace this temporary release debt")`, then run:

```bash
s0ma check --mode release
s0ma score --gate-mode release --gate
```

Release evidence must fail: explicit pending semantic debt earns zero credit and
blocks release. Restore the original guarantee, run `s0ma check --mode release`
and `s0ma build .`, and both return green. The point is not the toy edit; it is
the proof that the self-model participates in what can ship.

### 4. Prove host reality explicitly

Static checks deliberately do not execute project code. The host probe runs
under the application's own Python, and a fresh project does not have one yet:
it has no environment and declares no dependencies. Give it both in one step —
from inside `my-app`, `uv add` the `s0ma-core` and `s0ma-dsl` wheels from the
Install section, which creates `.venv`, installs them, and names them in
`[project].dependencies` (the build's `HOST_RUNTIME_UNDECLARED` warning asks
for exactly that declaration; with pip, install the two wheels into a `.venv`
of your own and add the two names to `[project].dependencies` by hand). Then,
after reviewing and trusting the application, run the separate probe:

```bash
s0ma verify-host --gate-mode release --python .venv/bin/python
```

On Windows use `.venv\\Scripts\\python.exe`, or set a contained
`[tool.s0ma].venv_path`. Host verification imports trusted application modules
without a sandbox and may trigger their filesystem, process, or network side
effects, so it requires explicit approval. Release evidence is the pair: a
caller-pinned static gate and this host-runtime report; neither alone is a
release claim.

### 5. Put self-knowledge in the application

Every build emits a content-addressed `self_context.json` and bounded
`self_prompt_card.md`. An application can load them with
`s0ma.runtime.self_context()`, wire the verified `self_inspect` adapter into its
own toolset, and give the agent that operates it — the second way an agent
meets s0ma — a current component/dependency model.
Read `s0ma://guide/self-prompting` for the complete wiring and trust-boundary
example. Authored intents are quoted project data, never privileged
instructions.

You have now exercised the whole value loop: author intent, build deterministic
artifacts, orient from the model, inspect dependency facts, watch drift and
release debt block, and verify the result in the host environment.

Wondering what s0ma trusts, what it executes, and what it will never send
anywhere? That contract is written down: `docs/trust-model.md`.

See also `docs/troubleshooting.md` when a step here does not behave as
described, `docs/guides/packaging.md` when the project is ready to ship as a
wheel, and `docs/uninstall.md` for removing s0ma completely.

If anything here broke or was harder than it should have been, say so where it
will be seen and answered: open a
[bug report](https://github.com/kn0w-thyself/s0ma/issues/new/choose) for
something that is wrong, or start a
[discussion](https://github.com/kn0w-thyself/s0ma/discussions) for a question or
an idea. `CONTRIBUTING.md` at the repository root says where each kind of
message goes.
