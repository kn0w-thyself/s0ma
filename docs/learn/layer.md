# layer

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The architectural band a file and everything in it belongs to, and the rule about which bands may depend on which.

## What it is

Every s0ma file declares one layer and every part inside the file shares it. The five bands are the subject matter itself, the work that coordinates it, the two edges where a program meets people and meets other systems, and the band s0ma keeps for its own machinery. A fixed table says which band may reach which: the subject matter reaches only itself and the framework, the two edges reach inward but never each other, and nothing reaches outward.

## Why it exists

It stops a codebase turning into a web where anything may call anything. Because the band is declared and the reachable pairs are fixed, an accidental dependency from the subject matter out to a screen or a database is refused at build time rather than discovered years later.

## When to use it

Choose the layer when you create a file, and choose it for the file rather than for one part — the layer applies to everything the file contains.

## When not to use it

Do not mix layers within one file; the language requires them to match exactly. And when two files in different bands need to share something, do not reach across: move the shared thing down into a band both can reach, or have the lower band publish an interface the higher one fills in.

## How it is written

```text
module <name>
    layer: <DOMAIN | APPLICATION | INFRASTRUCTURE | PRESENTATION | FRAMEWORK>
```

## Related ideas

- contrasts-with [kind](kind.md)
- contrasts-with [visibility](visibility.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/layer-consistency`
- `authority:spec/layer-reachability`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.0.1`
- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.0.2`

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
- [Authoring through the agent's own tool channel](../guides/mcp-authoring.md)
- [Building an app with s0ma over MCP — walkthrough](../walkthrough.md)
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)
- [Your first project, from install to graph](../getting-started/first-project.md)

---

## Identity

- Topic id: `concept:layer`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:4ebb3236461ceea1`
