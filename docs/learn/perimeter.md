# perimeter

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The line a project draws around the code s0ma answers for, and the files it deliberately leaves outside.

## What it is

The perimeter is four settings a project keeps in its own pyproject.toml: where its source lives, which files are the plain-Python entry points, which files are package markers that only re-export, and which strictness mode it is held to. Together they say what s0ma is answerable for here. Anything inside the perimeter that has not been converted yet is reported as unknown, which is the honest list of what is left to do; anything named as an entry point or a package marker is reported as exempt, by name, so what sits outside is something a reader can check rather than something they have to trust.

## Why it exists

A project that adopts s0ma a piece at a time needs a way of saying “this much, so far” that is exact enough to check. Without a declared perimeter the toolchain would have to guess which plain Python was left over and which was meant to stay plain, and a guess is the one thing an account of a system may not rest on.

## When to use it

Use perimeter for the declared boundary itself: setting it on an existing tree, widening it as more is converted, or reading what it leaves outside.

## When not to use it

Do not use it for the conversion work inside it: a file joins the self-model by being converted, not by the perimeter moving. A file named as an entry point or a package marker sits outside the account rather than inside it, so setting a perimeter is never a claim that the code within it has been converted.

## Related ideas

- part-of [adoption ladder](adoption-ladder.md)
- requires [strictness mode](strictness-mode.md)

## Worked examples

- none recorded

## What decides this

- `authority:prd/FR-DSL-5`
- `authority:prd/FR-DSL-8`
- `authority:prd/P-8`
- `authority:prd/glossary.perimeter`

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

- Topic id: `concept:perimeter`
- Release: `0.21.1 (preview)`
- Documentation snapshot: `sha256:348fe57f8e0d1551`
