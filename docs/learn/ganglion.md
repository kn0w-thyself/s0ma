# ganglion

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

A declared watcher: it observes named parts of the system and judges what it sees against what it expected.

## What it is

A ganglion is a part whose job is to watch other parts. It names which ones it observes — individually, or by a pattern covering a whole file or a whole layer — states what it expects normal behaviour to look like, says what should happen when what it sees does not match, and says what it must never do while it watches. It is the part of a s0ma system that forms judgements about the rest of it.

## Why it exists

It is how a system notices its own trouble instead of waiting to be told about it. Because the watching relationship is declared, anyone can ask which parts of a system are watched, by what, and against which expectation — a question no ordinary monitoring setup can answer from the code.

## When to use it

Use a ganglion when something has to assess behaviour rather than produce it: timing and promise-keeping at a single part, patterns across a file, or judgements that span the whole system.

## When not to use it

Do not use a ganglion to do the work it is watching; a watcher that also acts is two parts wearing one name. Do not use one to confirm a fixed expected result either — that is a verification, which runs on demand and either passes or fails, while a ganglion runs alongside the system and forms an opinion about it.

## How it is written

```text
ganglion <name> :: <LAYER>
    visibility: <PUBLIC | INTERNAL | TEST>
    intent: "<what this evaluator assesses>"
    observes: [<part names or patterns>]
    scope: <FUNCTION_BOUNDARY | SUBSYSTEM | SYSTEM>
    priors: "<what normal is expected to look like>"
    on_anomaly: "<what to do when it is not>"
    forbids: "<what it must never do while it watches>"
    ---
    def <name>(signal: Signal) -> EvaluationResult:
        <body>
```

## Related ideas

- contrasts-with [test](test.md)
- part-of [.s0ma file](s0ma-file.md)
- requires [intent](intent.md)
- requires [layer](layer.md)
- requires [visibility](visibility.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/ganglion-declaration`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.3`

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
- [Building an app with s0ma over MCP — walkthrough](../walkthrough.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)

---

## Identity

- Topic id: `concept:ganglion`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:402a431f4ac64f0d`
