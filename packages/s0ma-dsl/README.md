# s0ma-dsl

The transpiler toolchain for the **s0ma DSL** — a domain-specific language whose grammar enforces, at parse time, what the [s0ma framework](../s0ma-core) enforces at runtime: every component is declared, described, dependency-resolved, and registered in the self-model. It also ships the `s0ma` command line, which is how a person drives the whole toolchain.

`.s0ma` source files become plain Python decorated with the framework's `@component` annotations, plus a normalised `.s0ma.json` IR for tooling and agents and a `.s0ma.map` source map for debugging. **Authored documentation is part of the same surface** — `doc-ref`, `doc-guide`, and `example` declarations make documentation a registered, validated, drift-checked artifact rather than a parallel hand-written one.

## Where it sits

Four distributions ship together at one version, and dependencies only ever point down the stack (PRD INV-6):

[`s0ma-mcp`](../s0ma-mcp) · [`s0ma-studi0`](../s0ma-studi0) → **`s0ma-dsl`** → [`s0ma-core`](../s0ma-core)

The two packages above are optional companions: `s0ma-mcp` is the authoring server coding agents drive, and `s0ma-studi0` is the local viewer `s0ma studi0 <project>` opens on a built project's graph. This CLI defers importing each and prints an install hint when it is absent, so neither is required to use the DSL. Below it, `s0ma-core` and `lark` are the only external runtime dependencies.

`s0ma-dsl` is **Apache-2.0**, and so are `s0ma-core`, `s0ma-mcp` and `s0ma-studi0`. What each distribution contains, and the license each one declares, is in [the distributions s0ma ships](../../docs/reference/packages.md).

## Install

s0ma is not on PyPI yet: all four packages are published there from the first release cut of the public repository, and until that lands the way in is the repository itself. That route is written down once, in the [root README's "Install" section](../../README.md#install) — working inside a checkout, or building the wheels and installing them into a project of your own — and [getting started](../../docs/getting-started.md#1-create-a-real-project) is the journey to walk once the `s0ma` command runs.

Then give your project a `[tool.s0ma]` table in its `pyproject.toml` — or start fresh with `s0ma new project <dir>`, which writes it for you. Without the table the CLI runs in legacy mode with a one-line warning per invocation.

## What it feels like

```bash
s0ma new project my-app   # writes [tool.s0ma], scaffolds a module, runs the first build
s0ma check --mode release # validate without emitting; `--mode` selects authoring strictness
s0ma build .              # emit Python, IR, source maps, docs, and the build manifest
s0ma inspect --all        # one row per module, straight out of the self-model
s0ma doctor               # environment and project health; diagnoses, does not gate
```

Release evidence is a pair, and neither half alone is a release claim: `s0ma score --gate-mode release --gate` is the caller-pinned static gate, and `s0ma verify-host --gate-mode release --python .venv/bin/python` proves the imports in the application's own Python. Host verification imports trusted application code without a sandbox, so it is a separate, explicit step.

Every command the CLI serves, with what each one touches, is in [the s0ma command line](../../docs/reference/cli.md). Every `[tool.s0ma]` setting is in [project settings](../../docs/reference/configuration.md), and every diagnostic the toolchain can report is in [reports s0ma can make](../../docs/reference/diagnostics.md) — all three generated from the code that serves them.

## The language

The language spec is versioned separately from the distributions; the current one is [`docs/s0ma-dsl-spec-v0.17.0.md`](docs/s0ma-dsl-spec-v0.17.0.md), and it is the authority on what a `.s0ma` file may say. Everything below is a way in, not a second authority:

| Doc | Audience | Purpose |
|-----|----------|---------|
| [Language specification](docs/s0ma-dsl-spec-v0.17.0.md) | Implementers, reviewers | Normative language authority |
| [Survival card](docs/survival_card.md) | Coding agents | Under 4 KB: the bootstrap loop, the body rules, one minimal valid module — read first |
| [Quick reference](../../docs/reference/quick-reference-readable.md) | Coding agents, people | Every kind of declaration and every line each may carry, generated from the language itself — look topics up rather than reading it whole |
| [Agent system prompt](docs/agent_system_prompt.md) | LLMs | Copy-paste prompt for `.s0ma` authoring |
| [Patterns guide](docs/references/dsl_patterns_guide.md) | Authors | SERVICE / EXCEPTION / ADAPTER idioms for real applications |
| [Migration guide](docs/migration_guide.md) | Adopters | Convert existing Python to `.s0ma`; migrate hand-written docs into the subsystem |
| [Documentation subsystem](docs/references/documentation_subsystem.md) | Doc authors | `doc-ref` / `doc-guide` / `example` reference |
| [Coding agent handbook](docs/coding_agent_handbook.md) | Transpiler contributors | Architecture and conventions of this package |
| [Spec traceability](docs/spec_traceability.md) | All | Rule-to-implementation matrix |
| [ADRs](docs/adr) | All | The decisions this package holds itself to |

## Documentation

[**The map of record**](../../docs/README.md) lists every document this repository keeps, what it is for, and which check keeps it honest. Good places to start:

- [Your first s0ma project](../../docs/getting-started/first-project.md) — an empty directory to a built, inspectable project.
- [Your first module](../../docs/guides/first-module.md) — the anatomy of a `.s0ma` file, one declaration at a time.
- [When s0ma refuses, and how to get back to green](../../docs/guides/drift-recovery.md) — what each refusal means and what to do about it.
- [Concepts index](../../docs/reference/concepts-index.md) and the [glossary](../../docs/learn/glossary.md) — every term the documentation uses.

In a terminal, `s0ma docs` opens the same map and `s0ma docs show <topic>` answers one question from it.

## Releases

The root [`CHANGELOG.md`](../../CHANGELOG.md) names the current release and is canonical for all four packages; this package's own [`CHANGELOG.md`](CHANGELOG.md) holds the pre-monorepo history (last standalone DSL release: v0.16.0, 11 May 2026). All four packages are versioned in lockstep.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) for details. The rest of the toolchain shares it: `s0ma-core`, `s0ma-mcp` and `s0ma-studi0` are Apache-2.0 too, each with its own `LICENSE`.
