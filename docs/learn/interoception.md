# interoception

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The runtime-state faculty: a system's sense of how it is behaving against how it said it would.

## What it is

Interoception is the internal-state faculty of self-knowledge: the system's sense of how it is actually behaving compared with the behaviour it declared. A part can state what it expects of itself — how long a call should take, how often it may fail, how much memory or current it may draw — and the interoception verifier compares live measurements against those statements, so a part quietly running outside its own declared envelope becomes a reported fact instead of a surprise.

## Why it exists

It gives the platform a second kind of truth to check. Structure can be verified from the code alone; behaviour can only be verified while the system runs, and without a name for that sense the runtime half of self-knowledge has nowhere to live.

## When to use it

Use interoception when the sentence is about a running system measured against its own declarations: how fast, how often it fails, what it draws, and the anomalies raised when a reading crosses a declared bound.

## When not to use it

Do not use interoception for structural facts, which hold whether or not anything is running, and do not use it as another word for monitoring: what distinguishes it is the comparison against what the part itself declared.

## Related ideas

- contrasts-with [metacognition](metacognition.md)
- contrasts-with [proprioception](proprioception.md)
- part-of [self-knowledge](self-knowledge.md)

## Worked examples

- none recorded

## What decides this

- `authority:prd/FR-CORE-4`
- `authority:prd/glossary.interoception`
- `authority:prd/section.vision`

## Where to read the decision

- `references/s0ma-prd.md#1`
- `references/s0ma-prd.md#11. Glossary`
- `references/s0ma-prd.md#7.1 `s0ma-core` — the runtime (FR-CORE)`

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

---

## Identity

- Topic id: `concept:interoception`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:2607b8d0896aa97d`
