# registry snapshot

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The live index of every part in a running system, each held under the full name that joins its file and itself.

## What it is

When a s0ma system starts, every declared part registers itself in one index under a full name that joins the file's name and the part's own. Because the name is qualified, two files may each contain a part called the same thing without either shadowing the other. The index is what the system consults when anything asks what it contains, and it is complete — it includes the parts no other file is allowed to call.

## Why it exists

It makes self-knowledge a running fact rather than only a build-time one. The watchers, the verifications and the documentation machinery all resolve names against this index rather than against the shorter list of what a file publishes, which is how a system can describe every part of itself while keeping most of them private to call.

## When to use it

Reach for the index when you want to know what a running system actually contains, as opposed to what one file publishes to its neighbours.

## When not to use it

Do not read presence in the index as permission to call something. The index answers what exists and what may be observed; what may be called across files is the separate question the publish list and the visibility setting answer.

## Related ideas

- contrasts-with [canonical IR](canonical-ir.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/namespace-model`
- `authority:spec/registry-storage`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.10.1`
- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.10.4`

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
- [Seeing your system, and telling the s0ma team what you found](../guides/studi0-feedback.md)
- [The documentation subsystem](../documentation-subsystem.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)
- [Your first project, from install to graph](../getting-started/first-project.md)

---

## Identity

- Topic id: `concept:registry-snapshot`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:f3b5e3182c59c01d`
