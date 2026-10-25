# doc-guide

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

A written guide whose every factual claim about a named part is checked against the system rather than trusted.

## What it is

A doc-guide is a hand-written explanation — a walkthrough, a conceptual piece, a migration note — with one rule attached: wherever it names a part of the system it must do so through a marker the build resolves, embed a registered example, or state a claim the build can evaluate against what the system says about itself. Ordinary prose stays ordinary prose; it is the factual claims that are held to the system.

## Why it exists

It is the concession that some things genuinely need explaining, made safe. Narrative usually rots because nothing checks it; here a guide that names a part which has since been renamed or removed fails the build, so the only claims that survive a merge are the true ones.

## When to use it

Use a doc-guide for task-oriented walkthroughs, conceptual explanations and migration notes that name real parts of the system.

## When not to use it

Do not use a doc-guide for material that is purely a listing — a page assembled from the parts needs no author and is a doc-ref. Do not use one for conceptual writing that names no part of the system either; that is ordinary hand-written material, and this machinery would have nothing to check.

## How it is written

```text
doc-guide <name>
    intent: "<why this guide exists>"
    format: <markdown | html | json>
    output: <relative file path>
    covers: [<entity references>]
    asserts: [<claims the build can check>]
    examples: [example::<name>]
    ---
    <prose, naming parts through {{nerve::X}} style references>
```

## Related ideas

- contrasts-with [doc-ref](doc-ref.md)
- part-of [.s0ma file](s0ma-file.md)
- requires [executable evidence](executable-evidence.md)
- requires [intent](intent.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/doc-guide-declaration`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.12.2`

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
- [The documentation subsystem](../documentation-subsystem.md)
- [When s0ma refuses, and how to get back to green](../guides/drift-recovery.md)

---

## Identity

- Topic id: `concept:doc-guide`
- Release: `0.20.0 (preview)`
- Documentation snapshot: `sha256:da3d3e6a1c041e5a`
