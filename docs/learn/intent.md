# intent

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The declared reason a part exists, required on every part without exception.

## What it is

Intent is the sentence that says why a part exists. Every declared part carries one; no kind of code is exempt. It is not a comment and not a docstring bolted on afterwards — it is a field of the declaration, so it cannot be left out, cannot drift away from the code it belongs to, and travels with that code wherever the description is read.

## Why it exists

It is the smallest unit of a system's self-knowledge and the one the rest depends on. Reference pages assembled from the parts, searches across a system, and an agent asking what something is for all read this field, which is why a system where every part states its reason can answer questions an ordinary codebase cannot.

## When to use it

Write an intent on every declaration, and write the reason rather than the mechanics — what the part is for, not a restatement of what its code does.

## When not to use it

Do not leave it to be inferred from a name, and do not use it to record how something works. The how belongs in the code and, where a promise is involved, in the contract fields beside it.

## How it is written

```text
nerve <name> :: <LAYER>
    intent: "<why this component exists>"
```

## Related ideas

- contrasts-with [contract](contract.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/primitive-vocabulary`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#3`

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
- [Authoring through the agent's own tool channel](../guides/mcp-authoring.md)
- [Building an app with s0ma over MCP — walkthrough](../walkthrough.md)
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [Seeing your system, and telling the s0ma team what you found](../guides/studi0-feedback.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)
- [Your first project, from install to graph](../getting-started/first-project.md)

---

## Identity

- Topic id: `concept:intent`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:2607b8d0896aa97d`
