# release channel

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

Which build a page came from — a released version, a preview of work in progress, or a record kept for a version that has passed.

## What it is

A release channel is the label every rendered page carries saying which build it came from and how far it can be trusted. Release means the page was built from the exact state of a tagged version and describes that version and no other. Preview means it was built from the moving main line, so it may describe work that has not shipped, and every preview page says so where a reader can see it. Historical means the page describes a version that has passed, kept for the people still on it and never presented as current.

## Why it exists

A reader arriving from a search engine cannot tell which version a page describes, and a page that is right about tomorrow is wrong today. Stamping the channel onto the page itself makes that question answerable without anyone having to ask.

## When to use it

Use the channel words whenever a document's currency is at stake: saying which build a page came from, deciding whether unreleased work may appear in it, or marking material that has been superseded.

## When not to use it

Do not call a page a release build when it came from an untagged state, however finished the work feels, and do not use historical as a polite way of keeping a page that is simply wrong. A page that has been superseded points at what replaced it.

## Related ideas

- requires [drift](drift.md)

## Worked examples

- none recorded

## What decides this

- `authority:prd/FR-COM-4`
- `authority:prd/FR-X-3`
- `authority:prd/FR-X-5`
- `authority:prd/NFR-3`
- `authority:prd/glossary.release-channel`

## Where to read the decision

- `references/s0ma-prd.md#11. Glossary`
- `references/s0ma-prd.md#7.4 Cross-cutting (FR-X)`
- `references/s0ma-prd.md#7.5 Commercial access (FR-COM) **[NEW v1.1; restated v1.12]**`
- `references/s0ma-prd.md#8. Non-functional requirements (NFR)`

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
- [The documentation subsystem](../documentation-subsystem.md)

---

## Identity

- Topic id: `concept:release-channel`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:c9da24a3a2762814`
