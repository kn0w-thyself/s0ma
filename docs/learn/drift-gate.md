# drift-gate

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The build step that refuses a change when the written record and the system it describes have parted.

## What it is

The drift gate is where drift stops being a fact and becomes a failure. Every generated document carries a fingerprint of everything it was built from; the gate rebuilds the documents, compares the result with what is committed, and fails when the two differ. It runs in the same pipeline as the tests, so a change that leaves the written record behind cannot be merged, and the remedy is to rebuild rather than to remember.

## Why it exists

Warnings get learned and then ignored. Making the disagreement a build failure — rather than a report somebody reads later, or never — is what turns an accurate written record from an intention into a property of the repository.

## When to use it

Use drift gate for the enforcing step itself: the check that runs in the pipeline, compares what was built against what is committed, and refuses the change.

## When not to use it

Do not use drift gate for the condition it detects — the divergence itself is drift — and do not use it for a check that only warns. A gate that does not refuse is not a gate.

## Related ideas

- part-of [s0ma](s0ma.md)
- requires [authored-vs-generated boundary](authored-vs-generated-boundary.md)
- requires [drift](drift.md)

## Worked examples

- none recorded

## What decides this

- `authority:prd/FR-DSL-5`
- `authority:prd/FR-DSL-7`
- `authority:prd/P-3`
- `authority:prd/P-4`
- `authority:prd/section.problem-statement`

## Where to read the decision

- `references/s0ma-prd.md#2`
- `references/s0ma-prd.md#5. Principles (P-#) — the philosophy, enforced`
- `references/s0ma-prd.md#7.2 `s0ma-dsl` — the language and compiler (FR-DSL)`

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
- [The documentation subsystem](../documentation-subsystem.md)
- [When s0ma refuses, and how to get back to green](../guides/drift-recovery.md)

---

## Identity

- Topic id: `concept:drift-gate`
- Release: `0.20.0 (preview)`
- Documentation snapshot: `sha256:da3d3e6a1c041e5a`
