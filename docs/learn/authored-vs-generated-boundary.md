# authored-vs-generated boundary

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The line between what a person writes and what the build works out for itself, with no fact living on both sides of it.

## What it is

The authored-vs-generated boundary is the rule that every fact about the system has exactly one home. Facts a person states — what a part is for, what it promises, what it depends on — are authored, and are written once, in the source. Facts the build can work out for itself — which errors a piece of logic raises, which types it touches, what a finished documentation page says — are generated, and writing one of them by hand is refused rather than accepted as a shortcut. Documentation is rendered from the declarations; it is never maintained alongside them.

## Why it exists

One home per fact is what makes disagreement impossible rather than merely unlikely. Where a fact is written in two places, one of them is eventually wrong and nothing can say which; where the generated half is rebuilt from the authored half every time, the two cannot part without the build seeing it.

## When to use it

Use this idea when deciding where a fact belongs: if a person has to state it, author it once; if the build can derive it, let the build derive it and never copy the answer anywhere.

## When not to use it

Do not use it to argue that hand-written explanation is unwelcome. Guides are authored on purpose; the boundary governs only the factual claims inside them, which are checked against the system rather than trusted.

## Related ideas

- requires [self-model](self-model.md)

## Worked examples

- none recorded

## What decides this

- `authority:prd/FR-DSL-2`
- `authority:prd/P-2`
- `authority:prd/glossary.derived-edge`

## Where to read the decision

- `references/s0ma-prd.md#11. Glossary`
- `references/s0ma-prd.md#5. Principles (P-#) — the philosophy, enforced`
- `references/s0ma-prd.md#7.2 `s0ma-dsl` — the language and compiler (FR-DSL)`

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
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [What can change, and how you will know](../stability.md)
- [What s0ma trusts](../trust-model.md)
- [When s0ma refuses, and how to get back to green](../guides/drift-recovery.md)
- [Your first project, from install to graph](../getting-started/first-project.md)

---

## Identity

- Topic id: `concept:authored-vs-generated-boundary`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:f0638b89b84dfd6c`
