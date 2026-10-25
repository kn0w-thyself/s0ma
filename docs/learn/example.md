# example

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

A short runnable demonstration, registered against the parts it teaches, that has to keep working.

## What it is

An example is a small piece of code written to be read, declared as a part of the system in its own right. It says what it teaches, names the parts it demonstrates, and says where it runs. The build runs it, and an example that has stopped working fails the build exactly the way a broken verification does.

## Why it exists

It closes the gap between sample code and real code. Because the example is registered against the parts it demonstrates, anyone editing one of those parts can ask which examples teach it and fix them in the same change — and because it executes, a demonstration that quietly stopped being true cannot survive.

## When to use it

Write an example when a reader needs to see a part in use, and keep it short: it will be read, and length is what makes a demonstration stop teaching.

## When not to use it

Do not use an example as a substitute for a verification. Verifications exist to catch mistakes and may be as long and as thorough as they need to be; examples exist to be understood, and passing is a side effect of being honest rather than the point of the exercise.

## How it is written

```text
example <name>
    intent: "<what this example teaches>"
    demonstrates: [<entity references>]
    runs_in: <standalone | pytest | integration>
    ---
    <Python body>
```

## Related ideas

- contrasts-with [test](test.md)
- part-of [.s0ma file](s0ma-file.md)
- requires [executable evidence](executable-evidence.md)
- requires [intent](intent.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/example-declaration`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.12.3`

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
- [The documentation subsystem](../documentation-subsystem.md)
- [What s0ma trusts](../trust-model.md)

---

## Identity

- Topic id: `concept:example`
- Release: `0.20.0 (preview)`
- Documentation snapshot: `sha256:d259cef049e9be11`
