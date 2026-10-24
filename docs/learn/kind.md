# kind

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The functional archetype of a part: what sort of working logic it is, or what sort of structure it holds.

## What it is

Every working part and every structural part declares a kind, which says which archetype it belongs to. A working part is a plain computation, a coordinator of other parts, an adapter to something outside, or a long-running service. A structural part is a data shape, a fixed value, a settings object, an enumeration, a type name, or an error type. Which kinds are available depends on what sort of declaration you are writing, and the build refuses a mismatch.

## Why it exists

It lets a system group its own parts by role rather than by name. Asking for every adapter, or every fixed value, or every long-running service is a question the system answers directly — which is what makes a reference page assembled from the parts possible at all.

## When to use it

Choose a kind for every working part and every structural part, picking the archetype that describes what it is rather than what it happens to be called.

## When not to use it

Do not expect a kind on the declarations that have only one role. A verification, a private helper, a connection between parts and the three documentation declarations carry none, because there is nothing to choose between.

## How it is written

```text
nerve <name> :: <LAYER>
    kind: <SERVICE | FUNCTION | ADAPTER | ORCHESTRATOR>
cell <Name> :: <LAYER>
    kind: <MODEL | CONSTANT | CONFIG | ENUM | EXCEPTION | TYPE>
```

## Related ideas

- contrasts-with [layer](layer.md)
- contrasts-with [visibility](visibility.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/kind-taxonomy`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#3.1`

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
- [Building an app with s0ma over MCP — walkthrough](../walkthrough.md)
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)

---

## Identity

- Topic id: `concept:kind`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:8566b7670125c9fa`
