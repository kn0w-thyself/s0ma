# canonical IR

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The normalised record of one file's declarations that the build writes beside the code, for tools to read.

## What it is

When the build turns a source file into Python it also writes a second file: a normalised record of everything that file declared, with every name in its full form, every shorthand expanded, every pattern resolved, every automatically-derived connection filled in, and a fingerprint of the whole. It says exactly what the source says, with none of the ambiguity, which is why it is the form tools and agents read.

## Why it exists

It is the interface between a s0ma system and anything that wants to reason about it: a tool reading source has to parse a language, while a tool reading this record just reads structured data and every such tool sees the same picture. It also has room for honesty about what is not settled yet — a field can be recorded as deliberately absent, or as pending with a written reason, rather than simply being missing.

## When to use it

Read this record whenever a tool needs the structure of a system rather than its behaviour: building a reference page, answering a question about a part, or working out what a change would touch.

## When not to use it

Do not hand-edit it. The build writes it and rewrites it on every build, so an edit is lost at best and misleading in the meantime; the source file is where a person writes, and this record is what the build made of what they wrote.

## Related ideas

- contrasts-with [registry snapshot](registry-snapshot.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/canonical-ir`
- `authority:spec/intermediate-representation`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.10.5`
- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.14.5`

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
- [The documentation subsystem](../documentation-subsystem.md)
- [What can change, and how you will know](../stability.md)
- [What the build writes, and what each file is for](../guides/what-the-build-writes.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)

---

## Identity

- Topic id: `concept:canonical-ir`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:8566b7670125c9fa`
