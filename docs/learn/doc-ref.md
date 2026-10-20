# doc-ref

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

A reference page assembled entirely from what the system already knows about itself, carrying no prose of its own.

## What it is

A doc-ref is a declaration that produces a page of reference material by selecting parts of the system and printing named fields of each. It has no body and almost no writing: you say which parts it covers, which of their declared fields to show, and which file to write. Everything a reader sees comes from the parts themselves.

## Why it exists

It removes the largest single source of stale documentation, the hand-written catalogue. A page assembled from the parts cannot describe a part that no longer exists, cannot miss one that was added, and cannot quote an old promise, because it holds a copy of none of that.

## When to use it

Use a doc-ref for anything that is a list or a table of what the system contains: an interface reference, an error-code table, a catalogue of the parts in one layer.

## When not to use it

Do not use a doc-ref where a reader has to be walked through something. It cannot hold narrative, and forcing one will produce a table where an explanation was needed; that is what a doc-guide is for.

## How it is written

```text
doc-ref <name>
    intent: "<why this reference exists>"
    format: <markdown | html | json>
    output: <relative file path>
    covers: [<filter expression>]
    sections: [<field names to show>]
```

## Related ideas

- contrasts-with [doc-guide](doc-guide.md)
- part-of [.s0ma file](s0ma-file.md)
- requires [executable evidence](executable-evidence.md)
- requires [intent](intent.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/doc-ref-declaration`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.12.1`

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

- Topic id: `concept:doc-ref`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:c157b6f70dabfbd8`
