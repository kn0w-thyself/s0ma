# check and build loop

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The everyday cycle: check the source, build it, run the verifications, then ask the system what it now contains.

## What it is

Working in this language is a short loop. You check the source, which validates everything and generates none of the build output — it keeps only one bookkeeping note of what it has already told you about — so it is cheap enough to run constantly. You build, which turns the source into ordinary Python together with the record of the system's own structure. You run the verifications. Then you ask the built system what it contains, which is how you confirm that the parts you meant to declare really are declared.

## Why it exists

The loop is what keeps the description and the code in step. Because checking writes nothing it costs almost nothing to run, and because building produces the code and the record together the two cannot fall out of date with respect to each other.

## When to use it

Check constantly while writing, build when you want the output, verify before you share the change, and look at what the system now contains whenever you want to see what it believes about itself.

## When not to use it

Do not skip the check and go straight to a build hoping to save time. The check exists so that mistakes are found before anything is written, and the build runs the same validation anyway — so skipping it buys nothing and costs you the earlier, cheaper failure.

## Related ideas

- requires [strictness mode](strictness-mode.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/build-pipeline`
- `authority:spec/test-execution`
- `authority:spec/validation-command`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#2.1`
- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.15`
- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.16`

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
- [When s0ma refuses, and how to get back to green](../guides/drift-recovery.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)
- [Your first project, from install to graph](../getting-started/first-project.md)

---

## Identity

- Topic id: `concept:check-and-build-loop`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:ec62ca0343ef8be5`
