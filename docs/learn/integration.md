# integration

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

A declared adapter to an outside system, naming how to build it, how to check it is alive, and what it needs to run.

## What it is

An integration is the declaration that describes a connection to something outside the program — a calendar service, a payment provider, a message queue. It names the part that builds the connection, the part that checks the connection is alive, and a short record of what the integration offers and what the environment has to supply, such as which settings must be present. From that declaration the build writes the routine wiring for you.

## Why it exists

Every outside connection used to be assembled by hand in roughly the same shape, and hand-assembled shapes drift apart. Making it a declaration lets the build check the named pieces really exist, produce the same access points every time, and lets anyone ask what a system depends on beyond itself.

## When to use it

Use an integration when your program talks to a service you do not control, and you want that fact, its readiness check and its requirements declared in one place.

## When not to use it

Do not use an integration for a dependency inside your own program, and do not place one outside the infrastructure layer — talking to the outside world is an infrastructure job by definition, and the build refuses any other layer.

## How it is written

```text
integration <Name> :: INFRASTRUCTURE
    version: <MAJOR.MINOR.PATCH>
    intent: "<why this integration exists>"
    factory: <FactoryNerveName>
    smoke_test_primary: <SmokeTestNerveName>
    manifest:
      provides: [<operation names>]
      required_env: [<setting names>]
```

## Related ideas

- part-of [.s0ma file](s0ma-file.md)
- requires [intent](intent.md)
- requires [layer](layer.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/integration-declaration`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.4b`

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

- Topic id: `concept:integration`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:ec62ca0343ef8be5`
