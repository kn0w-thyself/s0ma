# s0ma

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The platform built on one idea: software should carry an accurate, queryable model of itself.

## What it is

s0ma is a Python platform built on one idea — that a system should carry an accurate, queryable, machine-readable model of itself, and that the model should be load-bearing rather than descriptive. Four layers deliver it: a runtime that records and verifies the parts of a running system, a language and compiler that refuse to build undeclared or undescribed code, an interface that lets a coding agent author against the same rules, and a viewer that draws what the model says. One version, one philosophy, four packages.

## Why it exists

It exists because the written account of a system and the system itself part company within weeks, and nobody can tell which half is lying. s0ma removes the parallel account: the description is rendered from declarations the system needs in order to run at all, so a description that has gone wrong is a system that refuses to start.

## When to use it

Use s0ma for the platform as a whole — the four packages, the language, and the idea they serve — and use the specific package name when you mean one of them.

## When not to use it

Do not use s0ma for a single package: the runtime is s0ma-core, the language is s0ma-dsl, the authoring interface is s0ma-mcp, and the viewer is s0ma-studi0. Do not use it for something somebody built on the platform either — that is a s0ma project. And it is always written with a digit zero.

## Related ideas

- requires [self-knowledge](self-knowledge.md)

## Worked examples

- none recorded

## What decides this

- `authority:prd/INV-1`
- `authority:prd/INV-2`
- `authority:prd/section.product-thesis`
- `authority:prd/section.vision`

## Where to read the decision

- `references/s0ma-prd.md#1`
- `references/s0ma-prd.md#3`
- `references/s0ma-prd.md#6. Invariants (INV-#) — never break these`

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
- [Getting started: prove the self-model is useful](../getting-started.md)
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [s0ma in Claude](../guides/claude-integration.md)
- [The documentation subsystem](../documentation-subsystem.md)
- [What can change, and how you will know](../stability.md)
- [Your first project, from install to graph](../getting-started/first-project.md)

---

## Identity

- Topic id: `concept:s0ma`
- Release: `0.21.0 (preview)`
- Documentation snapshot: `sha256:c658fd9bbcbd3969`
