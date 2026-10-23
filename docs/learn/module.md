# module

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The header every s0ma source file opens with, naming the file and declaring everything that enters and leaves it.

## What it is

A module declaration is the first thing in a s0ma source file and it speaks for the whole file: it gives the file a name, places it in one architectural band, states what the file is responsible for, and lists both the outside code it draws on and the parts of itself it lets other files use. Nothing enters or leaves the file without appearing in one of those lists.

## Why it exists

It makes a file's dependencies a declared fact instead of a scatter of import lines. Because the header is the only door in and out, a tool can answer what a file needs and what it offers by reading one block, and the build can refuse a file that reaches for something it never declared.

## When to use it

Write one at the top of every s0ma file, before any other declaration. There is no such thing as a s0ma file without one.

## When not to use it

Do not use the header to describe a single function or value; that belongs to the declaration for that part. And do not list a name among the published parts unless the part itself is marked public — the header and the part have to agree about what other files may reach.

## How it is written

```text
module <name>
    layer: <LAYER>
    version: <MAJOR.MINOR.PATCH>
    intent: "<what this module is responsible for>"
    exports: [<public component names>]
```

## Related ideas

- part-of [.s0ma file](s0ma-file.md)
- requires [intent](intent.md)
- requires [layer](layer.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/module-declaration`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.5`

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
- [Authoring through the agent's own tool channel](../guides/mcp-authoring.md)
- [Building an app with s0ma over MCP — walkthrough](../walkthrough.md)
- [Getting started: prove the self-model is useful](../getting-started.md)
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [Seeing your system, and telling the s0ma team what you found](../guides/studi0-feedback.md)
- [The documentation subsystem](../documentation-subsystem.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)
- [Your first project, from install to graph](../getting-started/first-project.md)

---

## Identity

- Topic id: `concept:module`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:402a431f4ac64f0d`
