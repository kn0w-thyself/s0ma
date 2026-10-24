# contract

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

What a working part needs before it runs, what it promises afterwards, and what it must never do, declared beside the code that has to keep all three.

## What it is

A contract is the three-part agreement a working part carries: what must be true before it is called, what it guarantees once it has finished, and what it must never do, however it is called and whatever happens while it runs. All three are fields of the declaration, sitting alongside the reason the part exists, and a working part cannot be declared without them; when there is nothing to rule out, the third says so with the word none rather than being left off. Two related fields sit beside them — which errors the part may raise, and how long it may acceptably take. A watcher carries the third part as well: what it must never do while it watches.

## Why it exists

It makes the agreement between caller and called a fact the system holds rather than something each reader reconstructs. A watcher can compare what actually happened against the promise, an agent can decide whether a part fits the situation in front of it — including what the part will never do — and a reviewer can see a promise or a prohibition change in a diff.

## When to use it

State all three parts on every working part: the condition a caller has to satisfy, the outcome the part will produce if that condition holds, and what it must never do, however it is called. When there is genuinely nothing to rule out, write none as the third part's answer.

## When not to use it

Do not put a contract on a structural part; a data shape says what it represents and what must always be true of it instead. Do not put one on a private helper either — helpers are scaffolding for the parts that carry contracts, and the check reports the fields when a helper carries them. And do not word a promise as a prohibition: what the part delivers belongs with what it guarantees, and only what it must never do, on any path, belongs in the third part.

## How it is written

```text
nerve <name> :: <LAYER>
    expects: "<what must be true before it runs>"
    guarantees: "<what is true once it has run>"
    forbids: "<what it must never do>"
    raises: [<error types it may raise>]
```

## Related ideas

- contrasts-with [intent](intent.md)
- part-of [nerve](nerve.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/nerve-declaration`
- `authority:spec/primitive-vocabulary`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#3`
- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.1`

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
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)

---

## Identity

- Topic id: `concept:contract`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:ec62ca0343ef8be5`
