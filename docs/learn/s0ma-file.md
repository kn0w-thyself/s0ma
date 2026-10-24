# .s0ma file

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

One source file: a module header first, then declarations, each separated from its code by a line of three hyphens.

## What it is

A s0ma source file has a fixed anatomy. It opens with the module header that speaks for the whole file, then carries one or more declarations, and every piece of code in it belongs to exactly one of them — the language refuses a block that belongs to none. Inside a declaration the description comes first and the code comes after, with a line of exactly three hyphens at the left margin between them.

## Why it exists

The fixed shape is what lets both people and machines read a file with no guesswork: the header always says what the file is, the description always comes before the code it describes, and the separator always marks where one stops and the other starts. Nothing about a file's meaning depends on convention or on where a reader happens to look.

## When to use it

Every file you write in this language has this shape; there is no other arrangement to choose between.

## When not to use it

Do not leave code in a file outside a declaration, and do not use the three-hyphen line anywhere but between a declaration's description and its code. The two declarations that carry no code — a connection between parts and the module header — leave the separator out entirely.

## How it is written

```text
module <name>
    layer: <LAYER>
    version: <MAJOR.MINOR.PATCH>
    intent: "<what this module is responsible for>"
    exports: [<public component names>]
# then one or more declarations, in any order:
<declaration header>
    <description fields>
    ---
    <code>
```

## Related ideas

- requires [module](module.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/body-separator`
- `authority:spec/declaration-types`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4`
- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.9`

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
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)
- [Your first project, from install to graph](../getting-started/first-project.md)

---

## Identity

- Topic id: `concept:s0ma-file`
- Release: `0.20.0 (preview)`
- Documentation snapshot: `sha256:51ba36aa8c843a19`
