# helper

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

A small private function inside one file, described but deliberately not registered as a part of the system.

## What it is

A helper is a function that exists to keep other declarations readable and never leaves the file it is written in. It declares why it exists and nothing else: no promises, no visibility setting, no dependency list, because the parts it serves are the ones that carry those. Other files cannot reach it and the system's list of components does not include it — though the file's own record still shows it, so nothing in a file is invisible.

## Why it exists

It gives ordinary scaffolding a home. Without it a private twenty-line routine has to be either buried inside a larger part, where nobody can see it, or promoted to a full component with promises it does not deserve. The helper is the honest third answer, and it keeps the component list meaningful by keeping scaffolding out of it.

## When to use it

Use a helper for a routine only this file calls and that carries no promise of its own: formatting, small shared setup, a recorder class several verifications reuse.

## When not to use it

Do not use a helper for anything another file needs; nothing outside the file can reach it and the build refuses the attempt. Do not use one for something with a real promise to keep either — the moment you want to say what it expects and guarantees, it is a nerve.

## How it is written

```text
helper _<name> :: <LAYER>
    intent: "<why this helper exists>"
    ---
    def _<name>(...) -> ...:
        <body>
```

## Related ideas

- contrasts-with [nerve](nerve.md)
- part-of [.s0ma file](s0ma-file.md)
- requires [intent](intent.md)
- requires [layer](layer.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/helper-declaration`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.4a`

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
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)

---

## Identity

- Topic id: `concept:helper`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:4ebb3236461ceea1`
