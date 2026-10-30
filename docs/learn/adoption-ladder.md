# adoption ladder

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The five-rung path a working Python codebase takes to become a s0ma application, one rung at a time.

## What it is

The adoption ladder is the order the work is done in, and every rung is a place a project can honestly sit for weeks. Rung zero is reading: the codebase is scanned as it stands and comes back with the order to convert it in. Rung one sets the perimeter, which makes the tree a s0ma project without changing a line of it. Rung two is optional and marks up the existing Python where it lies, for a codebase too large to convert quickly. Rung three is the loop that converts one module at a time, leaves first, and is repeated until there is nothing left on the list. Rung four tightens the strictness mode as more of the project arrives. A project halfway up is a normal state with a number on it, not an unfinished mess.

## Why it exists

Rewriting a working application in one go is the thing nobody can afford, so the alternative has to be a path with stopping places on it. Naming the rungs gives every stopping place a command that reaches it, a number that says it was reached, and one next step — which is what turns “we will adopt this eventually” into work somebody can pick up on a Tuesday and put down again on the Friday.

## When to use it

Use adoption ladder for the whole ordered path, and rung for one place on it: which rung a project has reached, which rung a command belongs to, what the next rung asks for.

## When not to use it

Do not use it for the strictness modes, which are the ratchet at the top of it rather than the ladder itself, and do not call one conversion a rung — converting a single module is one turn of rung three's loop.

## Related ideas

- part-of [s0ma](s0ma.md)
- requires [strictness mode](strictness-mode.md)

## Worked examples

- none recorded

## What decides this

- `authority:prd/FR-DSL-6`
- `authority:prd/FR-DSL-8`
- `authority:prd/P-8`
- `authority:prd/glossary.adoption-ladder`

## Where to read the decision

- `references/s0ma-prd.md#11. Glossary`
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
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)

---

## Identity

- Topic id: `concept:adoption-ladder`
- Release: `0.21.1 (preview)`
- Documentation snapshot: `sha256:348fe57f8e0d1551`
