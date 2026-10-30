# embodiment

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

Bringing the physical parts of a machine inside the boundary of what a system knows about itself, as ordinary declared parts.

## What it is

Embodiment is what happens when the physical parts of a machine are declared as ordinary parts of the system that drives them, rather than described from outside it. A sensor or a motor is embodied when it is declared like everything else: an attached device is an integration, reading it or driving it is a nerve, its readings and physical value types are cells, and its physical facts — part identity, where it is mounted, size, mass, material, sweep, supply voltage, current draw — are recorded as declared metadata under one shared vocabulary. The language gains nothing new to make this possible.

## Why it exists

Physical parts inside the boundary can be held to their declarations the way software is: a current ceiling the running machine exceeds becomes an anomaly the system raises about itself, and a physical fact that has changed becomes a discrepancy a build can find. Physical parts described from outside the boundary are a document, and documents drift.

## When to use it

Use embodiment — and the word embodied — whenever physical parts are brought inside the self-knowing boundary as declared parts of the system, whether that is a sensor board, a drive train, or a door.

## When not to use it

Do not use embodiment for a system that merely talks to a device over a wire and declares nothing about it; that is an integration with no physical facts recorded. Never say the hardware is represented from outside the system: the whole point of the word is that the hardware is inside the boundary, declared like every other part.

## Related ideas

- requires [cell](cell.md)
- requires [integration](integration.md)
- requires [nerve](nerve.md)
- requires [self-model](self-model.md)

## Worked examples

- none recorded

## What decides this

- `authority:adr/repo.ADR-003`
- `authority:prd/FR-CORE-1`
- `authority:prd/FR-X-4`
- `authority:prd/P-1`
- `authority:prd/glossary.component`
- `authority:prd/glossary.embodiment`

## Where to read the decision

- `docs/adr/ADR-003-hardware-embodiment-foundation.md#ADR-003: Hardware embodiment foundation — physical-facts vocabulary and runtime surfaces`
- `references/s0ma-prd.md#11. Glossary`
- `references/s0ma-prd.md#5. Principles (P-#) — the philosophy, enforced`
- `references/s0ma-prd.md#7.1 `s0ma-core` — the runtime (FR-CORE)`
- `references/s0ma-prd.md#7.4 Cross-cutting (FR-X)`

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

- Topic id: `concept:embodiment`
- Release: `0.21.1`
- Documentation snapshot: `sha256:348fe57f8e0d1551`
