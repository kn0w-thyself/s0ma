# s0ma-lang-dsl

The transpiler toolchain for the **s0ma DSL** — a domain-specific language whose grammar enforces, at parse time, what the [s0ma framework](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-core) enforces at runtime: every component is declared, described, dependency-resolved, and registered in the self-model. It also ships the `s0ma` command line, which is how a person drives the whole toolchain.

`.s0ma` source files become plain Python decorated with the framework's `@component` annotations, plus a normalised `.s0ma.json` IR for tooling and agents and a `.s0ma.map` source map for debugging. **Authored documentation is part of the same surface** — `doc-ref`, `doc-guide`, and `example` declarations make documentation a registered, validated, drift-checked artifact rather than a parallel hand-written one.

## Where it sits

Four distributions ship together at one version, and dependencies only ever point down the stack (PRD INV-6):

[`s0ma-lang-mcp`](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-mcp) · [`s0ma-lang-studi0`](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-studi0) → **`s0ma-lang-dsl`** → [`s0ma-lang-core`](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-core)

The two packages above are optional companions: `s0ma-lang-mcp` is the authoring server coding agents drive, and `s0ma-lang-studi0` is the local viewer `s0ma studi0 <project>` opens on a built project's graph. This CLI defers importing each and prints an install hint when it is absent, so neither is required to use the DSL. Below it, `s0ma-lang-core` and `lark` are the only external runtime dependencies.

`s0ma-lang-dsl` is **Apache-2.0**, and so are `s0ma-lang-core`, `s0ma-lang-mcp` and `s0ma-lang-studi0`. What each distribution contains, and the license each one declares, is in [the distributions s0ma ships](https://github.com/kn0w-thyself/s0ma/blob/main/docs/reference/packages.md).

## Install

s0ma is on PyPI:

```bash
pip install s0ma-lang-dsl
```

That brings `s0ma-lang-core` with it and installs the `s0ma` command. In a uv project, `uv add s0ma-lang-core s0ma-lang-dsl` names both in the project's dependencies. The package is named `s0ma-lang-dsl` and imported as `s0ma_dsl`. The other ways in, working inside a checkout or building the wheels yourself, are in the [root README's "Install" section](https://github.com/kn0w-thyself/s0ma/blob/main/README.md#install), and [getting started](https://github.com/kn0w-thyself/s0ma/blob/main/docs/getting-started.md#1-create-a-real-project) is the journey to walk once the `s0ma` command runs.

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

Every command the CLI serves, with what each one touches, is in [the s0ma command line](https://github.com/kn0w-thyself/s0ma/blob/main/docs/reference/cli.md). Every `[tool.s0ma]` setting is in [project settings](https://github.com/kn0w-thyself/s0ma/blob/main/docs/reference/configuration.md), and every diagnostic the toolchain can report is in [reports s0ma can make](https://github.com/kn0w-thyself/s0ma/blob/main/docs/reference/diagnostics.md) — all three generated from the code that serves them.

## The language

The language spec is versioned separately from the distributions; the current one is [`docs/s0ma-dsl-spec-v0.17.0.md`](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md), and it is the authority on what a `.s0ma` file may say. Everything below is a way in, not a second authority:

| Doc | Audience | Purpose |
|-----|----------|---------|
| [Language specification](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md) | Implementers, reviewers | Normative language authority |
| [Survival card](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-dsl/docs/survival_card.md) | Coding agents | Under 4 KB: the bootstrap loop, the body rules, one minimal valid module — read first |
| [Quick reference](https://github.com/kn0w-thyself/s0ma/blob/main/docs/reference/quick-reference-readable.md) | Coding agents, people | Every kind of declaration and every line each may carry, generated from the language itself — look topics up rather than reading it whole |
| [Agent system prompt](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-dsl/docs/agent_system_prompt.md) | LLMs | Copy-paste prompt for `.s0ma` authoring |
| [Patterns guide](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-dsl/docs/references/dsl_patterns_guide.md) | Authors | SERVICE / EXCEPTION / ADAPTER idioms for real applications |
| [Migration guide](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-dsl/docs/migration_guide.md) | Adopters | Convert existing Python to `.s0ma`; migrate hand-written docs into the subsystem |
| [Documentation subsystem](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-dsl/docs/references/documentation_subsystem.md) | Doc authors | `doc-ref` / `doc-guide` / `example` reference |
| [Coding agent handbook](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-dsl/docs/coding_agent_handbook.md) | Transpiler contributors | Architecture and conventions of this package |
| [Spec traceability](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-dsl/docs/spec_traceability.md) | All | Rule-to-implementation matrix |
| [ADRs](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-dsl/docs/adr) | All | The decisions this package holds itself to |

## Documentation

[**The map of record**](https://github.com/kn0w-thyself/s0ma/blob/main/docs/README.md) lists every document this repository keeps, what it is for, and which check keeps it honest. Good places to start:

- [Your first s0ma project](https://github.com/kn0w-thyself/s0ma/blob/main/docs/getting-started/first-project.md) — an empty directory to a built, inspectable project.
- [Your first module](https://github.com/kn0w-thyself/s0ma/blob/main/docs/guides/first-module.md) — the anatomy of a `.s0ma` file, one declaration at a time.
- [When s0ma refuses, and how to get back to green](https://github.com/kn0w-thyself/s0ma/blob/main/docs/guides/drift-recovery.md) — what each refusal means and what to do about it.
- [Concepts index](https://github.com/kn0w-thyself/s0ma/blob/main/docs/reference/concepts-index.md) and the [glossary](https://github.com/kn0w-thyself/s0ma/blob/main/docs/learn/glossary.md) — every term the documentation uses.

In a terminal, `s0ma docs` opens the same map and `s0ma docs show <topic>` answers one question from it.

## Releases

The root [`CHANGELOG.md`](https://github.com/kn0w-thyself/s0ma/blob/main/CHANGELOG.md) names the current release and is canonical for all four packages; this package's own [`CHANGELOG.md`](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-dsl/CHANGELOG.md) holds the pre-monorepo history (last standalone DSL release: v0.16.0, 11 May 2026). All four packages are versioned in lockstep.

## License

Apache License 2.0 — see [`LICENSE`](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-dsl/LICENSE) for details. The rest of the toolchain shares it: `s0ma-lang-core`, `s0ma-lang-mcp` and `s0ma-lang-studi0` are Apache-2.0 too, each with its own `LICENSE`.
