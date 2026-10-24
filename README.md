# s0ma

**Software that knows what it is. s0ma is a substrate in which the code
produces its own model — live, queryable and load-bearing — so that what a
system says about itself, to a person or to a coding agent, comes from the
system rather than from a guess.**

s0ma is built on one idea: a system should carry an accurate, machine-readable
model of itself, and that model should be load-bearing rather than descriptive.
The model is not written about the code; it is made by the code. Being declared
is how a part exists at all, so the account of the system is maintained by
everyone who touches it, whether or not they were thinking about documentation
at the time, and it is never older than the code. s0ma starts in Python, and it
is for anyone building agents, harnesses, AI-enabled applications, or
autonomous software and hardware systems — and for anyone maintaining a system
whose account of itself has to stay true. It needs no LLM to be useful: the
model that orients a coding agent is the same one that explains the system to a
person, and building with s0ma is building with Python.

**Why the biology.** The human nervous system was the design model for s0ma,
and the vocabulary follows it: a working part is a `nerve`, data lives in a
`cell`, a `ganglion` watches and responds, and a declared dependency between
parts is an `axon`. The purpose follows it too. A nervous system connects a
brain to the body it controls, and s0ma was built to connect an LLM, the brain
of a system, to the software, the body it acts on — so that the brain can know
what the body is made of, sense what it is doing, and act on it through
contracts it can read. The connection is the point, not the brain: a body built
this way knows itself whether or not a brain is attached.

**Getting in:** [from source](#install) — clone this repository and build the
wheels. s0ma is not on PyPI yet; publication there is pending the first release
from this repository.

**Already have a codebase?** [Retrofitting an existing codebase](docs/guides/retrofit-existing-codebase.md) is the way in: five rungs you can stop on and walk over weeks, not a rewrite.

**Status: public beta, pre-1.0.** [What can change, and how you will know](docs/stability.md).

<!-- DEMO: the terminal recordings rendered from docs/media/tapes/ by
     scripts/record_demos.sh are embedded here at publication. -->

## Is s0ma for you?

**Probably, if** you are building or maintaining a system and you need what it
says about itself to be true — because a coding agent works on it, because
people join and leave, or because *what does this do, and what breaks if I
change it?* is a question you keep answering by reading code. That is most
agents, agent harnesses and AI-enabled applications, and any autonomous
software or hardware system whose operator has to be able to ask it what it is;
s0ma is for the people building those, and for anyone whose system has to keep
an honest account of itself. s0ma makes the answer something the project holds:
every part carries its purpose, what it promises and what it depends on; the
compiler refuses code that is undeclared or undescribed; and the release gate
refuses a build whose account of itself has drifted from what it does. The
written description and the system cannot part company quietly, because a
description that has gone wrong is a system that refuses to start.

**With or without an LLM, and for two kinds of agent.** s0ma contains no model
of its own and calls none, and it does not need one to be useful: the
self-model is as readable by a person as by an agent — `s0ma inspect` and
studi0 answer the same questions a coding agent asks — and authoring in s0ma
is authoring in Python, a declaration and then ordinary code. Agents meet s0ma
in two distinct ways. A coding agent *building or maintaining* a s0ma
application works from the checkout with the `s0ma` command line, or through
the authoring MCP server where its host speaks MCP — one channel, never a
requirement — and gains efficiency, captured intent and guardrails that refuse
an undeclared, undescribed or drifted change before a person sees it. An LLM or
agent *operating* a s0ma application is handed the system's own model, through
the self-context the build emits and the runtime query surfaces, and gains
autonomy and safety: it asks the system what it is made of, what each part
promises and what would break, and is answered by the system rather than by a
guess — what it is told is quoted project data, never an instruction. A team
with no AI in the loop gets a system that explains itself; a team with agents
gets agents whose answers come from the project.

**Not everything has to be Python.** s0ma compiles Python, and what it declares
reaches further than what it compiles. A part written in another language, a
service you do not control, or a file that is not Python is declared from the
Python side as a reference — a pointer to the thing, or a wrapper around it: an
`integration` names an outside system, how to reach it and how to check it is
alive; an `ADAPTER` nerve wraps a call to something outside the program; a
`CONSTANT` cell carries a file verbatim with `content: @file(...)`; and hardware
is embodied as ordinary components. The non-Python parts are in the model and
in the dependency graph rather than left out of them. Support for more
languages is on the development roadmap.

**s0ma might not be for you, if** the work is a throwaway script, or has no Python in it to
declare the rest from, or is a codebase that cannot accept generated Python
files alongside the sources you write. And not if a team is unwilling to make
each part's purpose and boundaries something a release is allowed to fail on —
that is the whole mechanism, and without it s0ma is overhead. One thing s0ma is
not: a replacement for your tests or your production monitoring. It tells you
what the system is; it does not tell you it is working.

## How it works

You author `.s0ma` files. Each opens with a header that speaks for the whole
file — what it is for, which architectural band it belongs to, what it draws on
from outside and what it lets other files use — and then carries one or more
declarations. A declaration says what a part is for, what it expects and what it
guarantees, then a line of three hyphens, then perfectly ordinary Python. Its
`forbids:` line says what the part must never do, however it is called, and
`none` there means it rules nothing out.
`s0ma build` turns that into plain `.py` beside a machine-readable record of
everything declared; `s0ma check` reads the sources, writes nothing, and is
cheap enough to run constantly. Generated Python is an artifact: you edit the
`.s0ma` file, and the build refuses rather than silently erase a hand edit to
what it emitted. Because a part has to be declared to exist, the record cannot
drift away from the code without something refusing to build.

One declaration, copied from the module you write in [your first
project](docs/getting-started/first-project.md):

```s0ma
nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return a greeting for the name it is given."
    expects: "A name, as text."
    guarantees: "Returns a greeting that contains the name."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def greet(name: str) -> str:
        """Return a greeting for the name it is given."""
        return f"Hello, {name}!"
```

The long list of `none` entries is the file answering questions rather than
ignoring them — each is a thing this part could have declared and does not, said
out loud, so that an unanswered question and an answer of nothing never look the
same. Above it sits the file's header, which names what the whole file is for,
which band it belongs to, what it draws on from outside and what it lets other
files use: [your first module](docs/guides/first-module.md) walks a file's
anatomy field by field, and every line of every declaration is in [the quick
reference](docs/reference/quick-reference-readable.md). Plain-Python
adoption works too: decorate with `@component` from `s0ma-core` and the same
registry, verifiers and query surfaces apply, with no `.s0ma` file anywhere.

The system's own account of itself is what the documentation is rendered from,
which is why it can be checked rather than believed: pages are generated from
the model and compared byte for byte against what is committed, and the worked
journeys are replayed as real commands, with every line a page claims compared
against a line a real run produced.

Since 0.15.0 self-knowledge reaches physical hardware too — not as a model of a
device, but as embodiment: sensors, actuators and devices are brought inside the
self-knowing boundary as ordinary components, with a physical-facts vocabulary
carrying what a spec sheet cannot verify, resource bounds checked at ingestion,
and a live contract violation delivered to a running agent as it happens. Start
at [the patterns guide §31](packages/s0ma-dsl/docs/references/dsl_patterns_guide.md#31-embodying-physical-hardware-adr-003).

## Packages

One repository, one lockstep version (**0.19.1**), four independently
installable packages:

| Distribution | Module | What it is | License |
|---|---|---|---|
| [`s0ma-core`](packages/s0ma-core) | `s0ma` | The runtime: the registry every part is declared into, the verifiers, the lifecycle, and the surfaces that answer what exists and why. | Apache-2.0 |
| [`s0ma-dsl`](packages/s0ma-dsl) | `s0ma_dsl` | The `.s0ma` language, its compiler, and the `s0ma` command line. | Apache-2.0 |
| [`s0ma-mcp`](packages/s0ma-mcp) | `s0ma_mcp` | The authoring server a coding agent works through, over the Model Context Protocol. | Apache-2.0 |
| [`s0ma-studi0`](packages/s0ma-studi0) | `s0ma_studi0` | studi0, the local visual environment (`s0ma studi0`), whose sh0w renderer draws a project's component graph from its build artifacts. **Early preview — more coming.** | Apache-2.0 |

Those are the licenses as they stand today; each package's own `LICENSE` file is
the authority and the [summary at the end of this page](#license) is the short
form. Dependency direction is strictly `s0ma-mcp` / `s0ma-studi0` →
`s0ma-dsl` → `s0ma-core`, and `s0ma-core` stands alone with zero hard runtime
dependencies — an application can take the runtime and nothing else.

**The spelling.** The product is `s0ma` — lowercase s, digit **zero**, m, a — in
every identifier, file extension, configuration key, document and user-visible
string; `studi0`, `sh0w` and `kn0wthyself` likewise. Case variants are `s0ma` /
`S0ma` / `S0MA`. The letter-o spelling is a build failure rather than a
preference ([PRD](references/s0ma-prd.md) INV-1).

## The beta

s0ma is in public beta, which here means one thing: the software is pre-1.0,
and [the next section](#stability) says what that does and does not let change.

Nothing built from this repository contacts a service unless you ask it to, and
nothing in s0ma checks a licence or an entitlement in order to run. [What s0ma
trusts](docs/trust-model.md) lists every request any part of s0ma can make, what
it carries, and how to stop each one.

**Feedback is the point of a beta.** If something broke, confused you, or was
harder than it should have been, say so where it will be seen and answered: a
[bug report](https://github.com/kn0w-thyself/s0ma/issues/new/choose) for
something that is wrong, or a
[discussion](https://github.com/kn0w-thyself/s0ma/discussions) for a question,
an idea, or an account of how it went. [CONTRIBUTING.md](CONTRIBUTING.md) says
where each kind of message goes.

## Stability

While the first digit is a zero, a minor release may break something, and what
announces it is a changelog entry rather than a bigger version number. Three
things hold anyway: what you have installed keeps working; anything s0ma writes
for another program to read says what shape it is, so a reader that meets a
number it does not know is refused rather than misled; and every change is
written down once, in [one changelog](CHANGELOG.md), for one version all four
distributions share. One habit covers most of the rest — **pin the version, and
commit the build.**

The full answer, with the gate or the command that proves each promise, is [what
can change, and how you will know](docs/stability.md).

## Install

s0ma runs on macOS, Linux and Windows (native CPython, Python ≥ 3.11); CI
enforces the full gate on Linux (3.11/3.12/3.13) and Windows (3.11/3.13). The
commands below use [uv](https://docs.astral.sh/uv/).

s0ma is **not on PyPI yet**. All four packages are published there from the
first release cut of this repository ([PRD](references/s0ma-prd.md) NFR-8);
until that lands, `pip install s0ma-core` does not work, because a name on the
index is held only once something is published under it. Today the way in is
this repository, and this section is the one place that route is written down.

**Work from a clone.** Everything on this page runs from a checkout:

```bash
git clone https://github.com/kn0w-thyself/s0ma.git && cd s0ma
uv sync --all-packages --all-extras   # one environment; `uv run s0ma` and `uv run s0ma-mcp` now work
uv run s0ma doctor                     # what is installed here, and whether it is healthy
```

Working this way, every bare `s0ma` command on this page is `uv run s0ma …` —
or activate the checkout's `.venv` once and type them as written.

**Or build the wheels and install them into a project of your own.** From the
checkout:

```bash
uv build --package s0ma-core && uv build --package s0ma-dsl   # add --package s0ma-mcp / --package s0ma-studi0 as needed
```

Then, in your own project, add each wheel by path. Their inter-dependencies
name PyPI packages that do not exist there yet, so a resolver cannot find them
on its own:

```bash
uv add /path/to/s0ma/dist/s0ma_core-*.whl /path/to/s0ma/dist/s0ma_dsl-*.whl
```

or `pip install` the same wheels into any virtual environment, `s0ma-core`
first. `s0ma-core` on its own is fully supported — the runtime, with zero hard
dependencies; `s0ma-dsl` adds the `.s0ma` compiler and the `s0ma` command;
`s0ma-mcp` adds the authoring server; `s0ma-studi0` adds studi0, the local
visual environment. `s0ma-core`'s optional extras are `[api]` (REST), `[mcp]`
(introspection MCP server) and `[all]`. The globs assume a clean `dist/` — one
wheel per package, at the version you just built.

However you got in, the journey below is the one to walk next.

<!-- BEGIN GENERATED GETTING STARTED -->
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
<!-- END GENERATED GETTING STARTED -->

## For coding agents: the authoring MCP server

`s0ma-mcp` exposes the whole authoring loop over the Model Context Protocol (stdio) — one channel to the same model the `s0ma` command line gives an agent working in a checkout, for hosts that speak MCP. Register it with your MCP client — with Claude Code, `claude mcp add s0ma -- s0ma-mcp` — and an agent gets:

<!-- BEGIN GENERATED MCP SURFACE -->
The served surface is generated from the committed MCP snapshot; its live names, annotations, and input/output schemas are checked in CI.

- **Tools:** `adopt_file`, `build_project`, `check`, `describe_server`, `init_project`, `inspect_module`, `learn_s0ma`, `migrate_ext`, `prepare_feedback`, `project_status`, `run_example`, `scaffold_module`, `submit_feedback`, `transpile`, `verify_host`.
- **Resources:** `s0ma://docs/concepts`, `s0ma://docs/index`, `s0ma://docs/journeys`, `s0ma://guide/errors`, `s0ma://guide/getting-started`, `s0ma://guide/patterns`, `s0ma://guide/quick-reference`, `s0ma://guide/quick-reference.json`, `s0ma://guide/self-prompting`, `s0ma://guide/survival-card`, `s0ma://guide/system-prompt`, `s0ma://meta/changelog`, `s0ma://meta/version`, `s0ma://project/runbook`, `s0ma://self/model`, `s0ma://spec/current`.
- **Prompts:** `author_module`, `diagnose_fault`, `feedback`, `fix_check_failures`, `migrate_project`.
<!-- END GENERATED MCP SURFACE -->

The platform **self-hosts its agent layer** (FR-MCP-11): `s0ma-mcp` is itself a
s0ma application, authored as `.s0ma` modules under
`packages/s0ma-mcp/s0ma_src/`, built at the language's full release gate, and
served from its own self-model — which makes it the worked example of a
production s0ma project as well as the server. Details: the
[`s0ma-mcp` README](packages/s0ma-mcp/README.md).

## Documentation

**Start here: [the map of record](docs/README.md).** It is the one index. Every
document this repository keeps is on it — the guides, the language spec, the
generated references, the decision records, the package front doors, the wheel
copies, the archive — with what each one is, who it is written for, and which
automatic check keeps it honest. The page is generated from the same document
catalog the documentation build reads, so a document cannot be on it and unknown
to the build, or known to the build and missing from it. There is no second list
to keep in step with this one.

The same map is reachable without leaving your terminal: `s0ma docs` opens it,
`s0ma docs list` walks it by category, and `s0ma docs show <topic>` answers one
question from it. A coding agent reads it as `s0ma://docs/index`.

## Contributing, security, and conduct

Questions, bug reports and discussions are open to everybody and are the
contribution we most want — [CONTRIBUTING.md](CONTRIBUTING.md) says where each
kind of message goes. **Pull requests are by invitation during the beta:** raise
the idea in an issue or a discussion first, so that nobody writes something we
may not be able to take. It is a beta posture, not a permanent one, and the
reasons are written down rather than implied.

Found a security problem? Please report it privately, never in an issue —
[SECURITY.md](SECURITY.md) has the two routes and what to expect back.

Everyone taking part is asked to follow the [code of conduct](CODE_OF_CONDUCT.md).

## Development

```bash
uv sync --all-packages --all-extras   # one env for the whole workspace
uv run python scripts/check.py        # the full gate: ruff, mypy, all four suites, spelling guard
make check / make test / make lint    # the same, via the root Makefile
```

`scripts/check.py` is the single command CI runs (`ubuntu-latest` on Python 3.11/3.12/3.13 plus `windows-latest` on 3.11/3.13; see `.github/workflows/ci.yml`). Its stages are ruff over `packages/`, `mypy --strict` over all four packages, the four test suites, the documentation stages, release integrity under `selfhost-build` (committed-build byte equality for both self-hosted packages, generated inventories, all four wheels' license metadata, and a cold isolated installed-wheel journey), and the INV-1 spelling guard. Run a subset with `uv run python scripts/check.py --only <stage> [...]` (stage names are listed in `--help`). All four packages are `mypy --strict`-clean and ship `py.typed`, so downstream strict gates see every package's real types.

The product's purpose, principles and binding invariants live in the [PRD](references/s0ma-prd.md) — read it before changing what s0ma *is*. Contributor conventions are in [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## License

s0ma-core: Apache-2.0
s0ma-dsl: Apache-2.0
s0ma-mcp: Apache-2.0
s0ma-studi0: Apache-2.0
