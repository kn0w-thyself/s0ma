# mirror

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

A committed copy of a document, held identical to its one source by a check that fails when they part.

## What it is

A mirror is a second copy of a document, committed at another path because something genuinely needs it there — most often inside an installed package, so an agent working on a project can read the guides without a copy of the repository. A mirror is never edited in place: it is copied from the one source, and a check compares the two character for character and fails the build when they have parted. The source is the document; the mirror is a delivery of it.

## Why it exists

Some documents really do have to exist in two places, and the honest way to allow that is to make the second copy mechanically dependent on the first. A copy nobody compares becomes a second source of truth within a week; a copy compared on every build stays a delivery mechanism.

## When to use it

Use mirror for a committed copy whose whole job is to be identical to a source elsewhere in the repository, and name the source whenever you name a mirror.

## When not to use it

Do not call a document a mirror when it is edited in its own right, or when it merely covers the same ground as another. That is a second document, and two documents describing one thing are how a contradiction gets shipped.

## Related ideas

- requires [authored-vs-generated boundary](authored-vs-generated-boundary.md)
- requires [drift-gate](drift-gate.md)

## Worked examples

- none recorded

## What decides this

- `authority:prd/FR-MCP-10`
- `authority:prd/FR-MCP-3`
- `authority:prd/P-2`
- `authority:prd/glossary.mirror`

## Where to read the decision

- `references/s0ma-prd.md#11. Glossary`
- `references/s0ma-prd.md#5. Principles (P-#) — the philosophy, enforced`
- `references/s0ma-prd.md#7.3 `s0ma-mcp` — the agent authoring interface (FR-MCP) **[NEW]**`

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
- [Releasing s0ma](../RELEASING.md)
- [The documentation subsystem](../documentation-subsystem.md)

---

## Identity

- Topic id: `concept:mirror`
- Release: `0.20.0 (preview)`
- Documentation snapshot: `sha256:d259cef049e9be11`
