# axon

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

A written-down dependency between two parts: which one leans on which, why, and how tightly.

## What it is

An axon is a declared connection from one part of a system to another. It names the two ends, says what kind of dependence it is — one part calls another, builds it, reads settings from it, configures it, produces it, or consumes it — explains why the connection exists, says what travels along it, and records whether the two are tightly or loosely bound. A person writes it because it is a decision, not something a reader of the code could reliably work out.

## Why it exists

It captures the architecture a codebase would otherwise only imply. Connections a machine can work out for itself — which errors a part may raise, which types it mentions — are worked out automatically and may never be written by hand, so an axon is reserved for the choices somebody made and the recorded graph is a record of decisions rather than a transcript of syntax.

## When to use it

Write an axon for a dependency that crosses a file boundary, where the build requires one, and for any dependency inside a single file that is architecturally significant enough that a reader should be told why it is there.

## When not to use it

Do not write an axon for something the build already works out for itself, such as which errors a part raises or which types it mentions; the language refuses those outright. Do not write two for one relationship either — one connection, one declaration.

## How it is written

```text
axon <source> -> <target>
    relation: <CALLS | CONSTRUCTS | READS | CONFIGURES | PRODUCES | CONSUMES>
    intent: "<why this connection exists>"
    carries: "<what travels along it>"
    coupling: <TIGHT | LOOSE>
```

## Related ideas

- contrasts-with [uses:](uses.md)
- part-of [.s0ma file](s0ma-file.md)
- requires [intent](intent.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/axon-declaration`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.4`

## Where to look next

- [Glossary](glossary.md)
- [Anatomy of a .s0ma file](anatomy-of-a-s0ma-file.md)
- [Every kind of declaration, line by line](../reference/quick-reference-readable.md)
- [Every concept, in one table](../reference/concepts-index.md)
- [Everything s0ma can do](../reference/surfaces-index.md)
- [Every command, and what it takes](../reference/cli.md)
- [Every setting a project can declare](../reference/configuration.md)
- [Every report s0ma can make](../reference/diagnostics.md)
- [What s0ma answers an agent with](../reference/mcp.md)
- [What the viewer shows you](../reference/studi0.md)
- [Building an app with s0ma over MCP — walkthrough](../walkthrough.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)

---

## Identity

- Topic id: `concept:axon`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:402a431f4ac64f0d`
