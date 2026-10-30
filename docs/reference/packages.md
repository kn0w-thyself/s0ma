# The distributions s0ma ships

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

s0ma is 4 installable distributions rather than one, so you take the parts you need: the runtime alone if you are shipping an application, the whole toolchain if you are writing s0ma. All 4 are released together at version `0.21.1`, which is what lets one of them declare a floor on another and mean it.

They are all under the same license, `Apache-2.0`. Each row below names the license exactly as the distribution declares it, and the license file that ships beside it is the authority on what the identifier means.

## Contents

- [What ships, and on what terms](#what-ships-and-on-what-terms)
- [s0ma-core](#s0ma-core)
- [s0ma-dsl](#s0ma-dsl)
- [s0ma-mcp](#s0ma-mcp)
- [s0ma-studi0](#s0ma-studi0)

## What ships, and on what terms

**Depends on** lists only the other distributions in this workspace. Third-party requirements are facts about a build environment; what this column shows is the direction s0ma is allowed to point in, and it points one way.

The sentence quoted under each name below is the distribution's own, taken from the packaging metadata every install reads, so it is what the wheel says about itself rather than a second description kept somewhere else.

| Distribution | Version | License | Depends on | Components |
| --- | --- | --- | --- | --- |
| `s0ma-core` | `0.21.1` | `Apache-2.0` | nothing | 63 |
| `s0ma-dsl` | `0.21.1` | `Apache-2.0` | `s0ma-core` | 10 |
| `s0ma-mcp` | `0.21.1` | `Apache-2.0` | `s0ma-core`, `s0ma-dsl` | 40 |
| `s0ma-studi0` | `0.21.1` | `Apache-2.0` | `s0ma-core`, `s0ma-dsl` | 48 |

## s0ma-core

> A Python framework for software self-knowledge — where the self-model is load-bearing.

Version `0.21.1`, licensed `Apache-2.0` — an open license: you may use, change and redistribute it, including commercially, on the terms in the license file. The license text ships as `LICENSE` inside the wheel.

It depends on nothing else in this workspace — it is the bottom of the stack. It registers 63 components, listed with what each is for in the [component index](../architecture/component-index.md).

Declared in [`packages/s0ma-core/pyproject.toml`](../../packages/s0ma-core/pyproject.toml); its front door is [`packages/s0ma-core/README.md`](../../packages/s0ma-core/README.md).

## s0ma-dsl

> The s0ma DSL transpiler — compiles .s0ma source files into self-describing Python for software self-knowledge.

Version `0.21.1`, licensed `Apache-2.0` — an open license: you may use, change and redistribute it, including commercially, on the terms in the license file. The license text ships as `LICENSE` inside the wheel.

It depends on `s0ma-core`, and on nothing else in this workspace. It registers 10 components, listed with what each is for in the [component index](../architecture/component-index.md).

Declared in [`packages/s0ma-dsl/pyproject.toml`](../../packages/s0ma-dsl/pyproject.toml); its front door is [`packages/s0ma-dsl/README.md`](../../packages/s0ma-dsl/README.md).

## s0ma-mcp

> The s0ma authoring MCP server — exposes the s0ma DSL self-knowledge toolchain and agent guides to coding agents over the Model Context Protocol.

Version `0.21.1`, licensed `Apache-2.0` — an open license: you may use, change and redistribute it, including commercially, on the terms in the license file. The license text ships as `LICENSE` inside the wheel.

It depends on `s0ma-core`, `s0ma-dsl`, and on nothing else in this workspace. It registers 40 components, listed with what each is for in the [component index](../architecture/component-index.md).

Declared in [`packages/s0ma-mcp/pyproject.toml`](../../packages/s0ma-mcp/pyproject.toml); its front door is [`packages/s0ma-mcp/README.md`](../../packages/s0ma-mcp/README.md).

## s0ma-studi0

> s0ma studi0 — the local viewer that renders a s0ma project's canonical component graph from its build artifacts, truthfully and read-only.

Version `0.21.1`, licensed `Apache-2.0` — an open license: you may use, change and redistribute it, including commercially, on the terms in the license file. The license text ships as `LICENSE` inside the wheel.

It depends on `s0ma-core`, `s0ma-dsl`, and on nothing else in this workspace. It registers 48 components, listed with what each is for in the [component index](../architecture/component-index.md).

Declared in [`packages/s0ma-studi0/pyproject.toml`](../../packages/s0ma-studi0/pyproject.toml); its front door is [`packages/s0ma-studi0/README.md`](../../packages/s0ma-studi0/README.md).
