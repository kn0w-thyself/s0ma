# s0ma-lang

**s0ma-lang** installs all of [s0ma](https://github.com/kn0w-thyself/s0ma), the software self-knowledge platform, under one name. It carries no code of its own. It depends on the four distributions s0ma is made of, each at exactly its own version, so one name and one version give you a toolchain whose parts were released together.

## What it installs

| Distribution | Module | What it is |
|---|---|---|
| [`s0ma-lang-core`](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-core) | `s0ma` | The runtime: the registry every part is declared into, the verifiers, the lifecycle, and the surfaces that answer what exists and why. |
| [`s0ma-lang-dsl`](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-dsl) | `s0ma_dsl` | The `.s0ma` language, its compiler, and the `s0ma` command line. |
| [`s0ma-lang-mcp`](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-mcp) | `s0ma_mcp` | The authoring server a coding agent works through, over the Model Context Protocol. |
| [`s0ma-lang-studi0`](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-studi0) | `s0ma_studi0` | studi0, the local visual environment (`s0ma studi0`), whose sh0w renderer draws a project's component graph from its build artifacts. |

The `s0ma` and `s0ma-mcp` commands arrive with it, because the distributions that provide them are among its dependencies. There is nothing to import from `s0ma-lang` itself: the modules are the four in the table.

## Install

s0ma is on PyPI:

```bash
pip install s0ma-lang
```

That one command installs all four. It also brings pytest, so `s0ma test` runs a project's tests with nothing else to install. In a [uv](https://docs.astral.sh/uv/) project, `uv add s0ma-lang` does the same. The other ways in, taking one part, working inside a checkout or building the wheels yourself, are in the [root README's "Install" section](https://github.com/kn0w-thyself/s0ma/blob/main/README.md#install), and [getting started](https://github.com/kn0w-thyself/s0ma/blob/main/docs/getting-started.md#1-create-a-real-project) is the journey to walk once the `s0ma` command runs.

## One version, exactly

The five distributions are released together at one version. `s0ma-lang` at a given version requires each of the four at exactly that version, not at that version or later. Installing a pinned `s0ma-lang` therefore cannot resolve to a mixed set, and upgrading `s0ma-lang` moves all four together.

## When to take a part instead

Each of the four installs on its own, and dependencies between them point one way: `s0ma-lang-mcp` and `s0ma-lang-studi0` depend on `s0ma-lang-dsl`, which depends on `s0ma-lang-core`.

- An application that runs s0ma components and does not build them needs `s0ma-lang-core` alone. It has zero hard runtime dependencies.
- A project that compiles `.s0ma` sources in its own build needs `s0ma-lang-dsl`, which brings the runtime with it.
- Take `s0ma-lang` when you are writing s0ma and want the language, the authoring server and the viewer together.

## Why the names carry `lang`

The Python package index compares names with a zero read as the letter o, and unrelated projects already hold the letter-o spellings of the shorter names. Only the distribution names carry `lang`. The modules you import, the `s0ma` and `s0ma-mcp` commands, and the `.s0ma` file extension keep the short spelling, with a digit zero.

## Documentation

- [The s0ma README](https://github.com/kn0w-thyself/s0ma/blob/main/README.md): what s0ma is, and the first project.
- [Getting started](https://github.com/kn0w-thyself/s0ma/blob/main/docs/getting-started.md): the journey from an empty directory to a verified build.
- [The distributions s0ma ships](https://github.com/kn0w-thyself/s0ma/blob/main/docs/reference/packages.md): what each distribution contains and declares.
- [The map of record](https://github.com/kn0w-thyself/s0ma/blob/main/docs/README.md): every document the repository keeps.

Once the toolchain is installed, `s0ma docs` opens the same map in a terminal.

## License

Apache License 2.0. See [`LICENSE`](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-lang/LICENSE) for the text. The four distributions this one depends on are Apache-2.0 too, each with its own `LICENSE`.
