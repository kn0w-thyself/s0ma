# uses:

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The module header's list of parts in other s0ma files that this file is allowed to reach.

## What it is

The uses list names every part in another s0ma file that this file refers to — whether it calls it, builds it, raises it, or merely names it in a type. Each entry has to be something the other file has published, and each has to satisfy the layer rule, so a file's reach across the project is a declared and checked list rather than a set of import lines nobody audits.

## Why it exists

It turns the dependency graph between files into a declared fact. Because it covers every kind of reference and not only calls, the recorded graph is complete — which is what makes it safe to ask what a change to one file would affect.

## When to use it

Add an entry whenever this file refers to something in another s0ma file, by any means at all.

## When not to use it

Do not use it for code from outside the project; that is the requires list. And do not leave an entry in place once nothing in the file refers to it — an unused entry is reported, because a declared dependency nobody exercises is a claim that is no longer true.

## How it is written

```text
module <name>
    uses: [<other_module.component>, <other_module.component as alias>]
```

## Related ideas

- contrasts-with [axon](axon.md)
- contrasts-with [requires:](requires.md)
- part-of [module](module.md)
- requires [layer](layer.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/dependency-categories`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.5.1`

## Where to look next

- [Glossary](glossary.md)
- [Every kind of declaration, line by line](../reference/quick-reference-readable.md)
- [Every concept, in one table](../reference/concepts-index.md)
- [Everything s0ma can do](../reference/surfaces-index.md)
- [Every command, and what it takes](../reference/cli.md)
- [Every setting a project can declare](../reference/configuration.md)
- [Every report s0ma can make](../reference/diagnostics.md)
- [What s0ma answers an agent with](../reference/mcp.md)
- [What the viewer shows you](../reference/studi0.md)
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)

---

## Identity

- Topic id: `concept:uses`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:4ebb3236461ceea1`
