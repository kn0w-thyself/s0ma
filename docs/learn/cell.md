# cell

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

A declared piece of structure — a data shape, a fixed value, a setting, a type, or an error kind — rather than a piece of behaviour.

## What it is

A cell is a part of a system that holds a shape or a value rather than doing work. Data models, configuration objects, fixed constants, enumerations, type names and error types are all cells. Like every other part it declares why it exists and what it represents, so a system can describe its own vocabulary and not only its own actions.

## Why it exists

It draws the line between what a system is made of and what a system does. A tool asking what data a program handles reads the cells; a tool asking what a program does reads the nerves. Keeping structure out of the behaviour declarations is what makes both questions answerable at all.

## When to use it

Use a cell for a data structure, a fixed value, a configuration object, an enumeration, a type name, or an error type. The test is whether the logic inside serves the data's own rules rather than the wider system's work.

## When not to use it

Do not use a cell for anything that computes, decides, fetches, or serves — that is a nerve, even when it is three lines long. A method that keeps a data structure internally consistent belongs on a cell; a method that acts on the system around it does not.

## How it is written

```text
cell <Name> :: <LAYER>
    kind: <KIND>
    visibility: <PUBLIC | INTERNAL | TEST>
    intent: "<why this component exists>"
    schema: "<what data this represents>"
    ---
    <Python class, constant, or type definition>
```

## Related ideas

- contrasts-with [nerve](nerve.md)
- part-of [.s0ma file](s0ma-file.md)
- requires [intent](intent.md)
- requires [kind](kind.md)
- requires [layer](layer.md)
- requires [visibility](visibility.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/cell-declaration`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.2`

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
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)

---

## Identity

- Topic id: `concept:cell`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:f3b5e3182c59c01d`
