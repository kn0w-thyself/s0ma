# test

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

A verification written as a declared part of the system, naming exactly which parts it checks.

## What it is

A test in s0ma is a declaration like any other. It says what behaviour it verifies and, crucially, names the parts it is verifying, so the link between a check and the thing checked is recorded rather than guessed from a file name. The build turns it into an ordinary runnable test, and the system can be asked which of its parts are covered and by what.

## Why it exists

It turns coverage from a number into a structure. Because each test names its targets, a system can list the public parts nobody verifies, and the strictest mode refuses a release while any public working part has neither a test nor a written claim that an outside suite covers it.

## When to use it

Write a test declaration for behaviour you want verified inside the language, where the coverage should become part of the system's own record of itself.

## When not to use it

Do not use a test to show how something is used — a reader learns from an example, which is written to be read, while a test is written to catch mistakes. Do not use one where the real verification lives in an outside suite either; say so in the part's own coverage claim instead.

## How it is written

```text
test test_<name> :: <LAYER>
    intent: "<what behaviour this verifies>"
    tests: [<component names this verifies>]
    ---
    def test_<name>():
        <body>
```

## Related ideas

- contrasts-with [example](example.md)
- contrasts-with [ganglion](ganglion.md)
- part-of [.s0ma file](s0ma-file.md)
- requires [intent](intent.md)
- requires [layer](layer.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/test-declaration`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.8`

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

---

## Identity

- Topic id: `concept:test`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:8566b7670125c9fa`
