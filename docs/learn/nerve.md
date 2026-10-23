# nerve

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

A piece of working logic that carries its own account of what it does, what it needs, and what it promises.

## What it is

A nerve is a piece of working logic that carries a description of itself. You write the function — or, for a long-running service, the class — as you normally would, and above it you state what it is for, what it needs from its caller, what it promises in return, and what it must never do. Those statements are part of the declaration rather than a comment beside it, so they travel with the code from then on.

## Why it exists

Nerves are how a s0ma system knows what its own moving parts do. Because the description is declared rather than remembered, the system can be asked what it contains and answer from the code itself, instead of from a document somebody hopefully kept up to date.

## When to use it

Use a nerve for anything that acts: a step that computes, decides, fetches, or serves. If you would reach for a function or a service class, reach for a nerve.

## When not to use it

Do not use a nerve for something that only holds a shape or a value — a fixed value, a data structure, or a type belongs in a cell. Do not use one for the part that watches other parts and draws conclusions about them; that is a ganglion. And do not use one for a small private routine nobody outside the file calls; that is a helper.

## How it is written

```text
nerve <name> :: <LAYER>
    kind: <KIND>
    visibility: <PUBLIC | INTERNAL | TEST>
    intent: "<why this component exists>"
    expects: "<preconditions>"
    guarantees: "<postconditions>"
    forbids: "<what it must never do>"
    evaluates_at: <FUNCTION_BOUNDARY | SUBSYSTEM | SYSTEM>
    ---
    def <name>(<args>) -> <return type>:
        <body>
```

## Related ideas

- contrasts-with [cell](cell.md)
- contrasts-with [helper](helper.md)
- part-of [.s0ma file](s0ma-file.md)
- requires [contract](contract.md)
- requires [intent](intent.md)
- requires [kind](kind.md)
- requires [layer](layer.md)
- requires [visibility](visibility.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/nerve-declaration`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.1`

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
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)

---

## Identity

- Topic id: `concept:nerve`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:4637874a4bcdaece`
