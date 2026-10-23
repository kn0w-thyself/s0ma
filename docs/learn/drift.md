# drift

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The gap that opens when a written description and the thing it describes stop agreeing.

## What it is

Drift is what happens when a description and the thing it describes stop agreeing: the written record still says one thing while the code has quietly moved on. s0ma turns that disagreement into something a machine can notice. Every generated document carries a fingerprint of everything it was built from, and recomputing that fingerprint says at once whether the two still match.

## Why it exists

Drift is the failure the whole product exists to prevent. Naming it, fingerprinting it, and rechecking it on every merge is what turns "the documentation is accurate" from a claim somebody makes into a fact the build can prove.

## When to use it

Ask for the drift check whenever you need to know whether the written record still matches the system: before a release, in the merge gate, and after any change to something a document describes.

## When not to use it

Drift is not a word for a document that is badly written, out of date in its judgement, or missing a section. Those are editorial problems and a fingerprint cannot see them. Drift is the narrow, mechanical case where the source a document was built from has changed and the document has not been rebuilt.

## Related ideas

- requires [doc-guide](doc-guide.md)
- requires [doc-ref](doc-ref.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/drift-check`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.12.5`

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
- [Getting started: prove the self-model is useful](../getting-started.md)
- [Releasing s0ma](../RELEASING.md)
- [The documentation subsystem](../documentation-subsystem.md)
- [Troubleshooting s0ma](../troubleshooting.md)
- [What can change, and how you will know](../stability.md)
- [What the build writes, and what each file is for](../guides/what-the-build-writes.md)
- [When s0ma refuses, and how to get back to green](../guides/drift-recovery.md)

---

## Identity

- Topic id: `concept:drift`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:4ebb3236461ceea1`
