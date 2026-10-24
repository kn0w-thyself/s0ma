# executable evidence

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The rule that every factual claim in a document is printed from the system, checked against it, or demonstrated by code that runs.

## What it is

Executable evidence is the standard the documentation machinery holds every claim to. A statement about a named part of the system may exist in exactly three forms: printed from what that part declares, written as a claim the build evaluates against the system, or demonstrated by a registered example that is actually run. There is no fourth form, and a claim in none of the three is refused.

## Why it exists

It makes documentation a projection of the system rather than a second description competing with it. A printed claim cannot be wrong, a checked claim fails loudly the moment it becomes wrong, and a demonstration that runs cannot quietly stop being true — so nothing survives on the strength of having once been correct.

## When to use it

Apply the standard whenever a document names a real part of the system: reach for a printed field first, a checked claim where a field alone will not say it, and a running demonstration where a reader needs to see the part in use.

## When not to use it

The standard does not reach writing that names no part of the system. Conceptual and teaching material — the language specification among it — is hand-written and deliberately outside this machinery, because there is nothing in it for the build to check.

## Related ideas

- requires [registry snapshot](registry-snapshot.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/doc-validation-layers`
- `authority:spec/documentation-declarations`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.12`
- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.12.4`

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
- [What s0ma trusts](../trust-model.md)

---

## Identity

- Topic id: `concept:executable-evidence`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:8566b7670125c9fa`
