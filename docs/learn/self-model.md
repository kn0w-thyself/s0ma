# self-model

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The queryable record of a system's parts, their relationships, and the documentation and examples attached to them.

## What it is

The self-model is the system's record of itself: every declared part with its purpose, its kind, its layer, what it promises and what it depends on, together with the relationships between the parts and the documentation and examples attached to each. It is load-bearing rather than descriptive — being declared is a condition of a part existing at all, so the record cannot be skipped without the system failing to start.

## Why it exists

Making the record load-bearing is what stops it rotting. A description kept beside the code is optional, and optional records go stale; a record the system needs in order to run is maintained by everyone who touches the code, whether or not they were thinking about documentation at the time.

## When to use it

Use self-model for the recorded artifact itself — the thing that is queried, rendered, verified, and compared against reality.

## When not to use it

Do not use self-model for the capability of having one; that is self-knowledge. Do not use it for a diagram or a written page produced from it either — those are views of the model, and the model is what they are views of.

## Related ideas

- requires [intent](intent.md)
- requires [registry snapshot](registry-snapshot.md)

## Worked examples

- none recorded

## What decides this

- `authority:prd/P-1`
- `authority:prd/glossary.self-model`
- `authority:prd/section.vision`

## Where to read the decision

- `references/s0ma-prd.md#1`
- `references/s0ma-prd.md#11. Glossary`
- `references/s0ma-prd.md#5. Principles (P-#) — the philosophy, enforced`

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
- [Getting started: prove the self-model is useful](../getting-started.md)
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [s0ma in Claude](../guides/claude-integration.md)
- [Seeing your system, and telling the s0ma team what you found](../guides/studi0-feedback.md)
- [The documentation subsystem](../documentation-subsystem.md)
- [What the build writes, and what each file is for](../guides/what-the-build-writes.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)
- [Your first project, from install to graph](../getting-started/first-project.md)

---

## Identity

- Topic id: `concept:self-model`
- Release: `0.20.0 (preview)`
- Documentation snapshot: `sha256:51ba36aa8c843a19`
