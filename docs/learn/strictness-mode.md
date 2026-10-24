# strictness mode

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

How severely the build treats its own findings, from forgiving during adoption to unforgiving before a release.

## What it is

A strictness mode decides whether a finding is a warning or a refusal. The most forgiving mode exists for bringing an existing codebase across, where nearly everything is a warning. The everyday mode is balanced. The strict mode makes nearly everything a refusal and is meant for automated checks before a merge. The release mode adds requirements of its own: every public working part verified or explicitly claimed as covered elsewhere, every file carrying a real version, and every cross-file connection explained in a person's own words.

## Why it exists

It lets one set of rules serve a codebase at every stage of its life. Silence would be the wrong default in a system built on explicitness, so nothing is ever ignored; what changes is whether a finding stops you now or is recorded for later.

## When to use it

Use the forgiving mode while adopting the language, the balanced one day to day, the strict one in the automated checks before merging, and the release one when shipping. Which mode applies is decided in this order: the `--mode` flag on the command, else the project's `mode` setting in `pyproject.toml`, else the command's own default, which is `strict` for `s0ma check` and `dev` for the rest.

## When not to use it

Do not reach for a forgiving mode to get a release out. The extra release requirements are the ones that keep a published system honest, and turning them off does not make the problems they name go away.

## Related ideas

- part-of [check and build loop](check-and-build-loop.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/strictness-modes`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#2.4`

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
- [Packaging a s0ma project as a wheel](../guides/packaging.md)
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [The documentation subsystem](../documentation-subsystem.md)
- [When s0ma refuses, and how to get back to green](../guides/drift-recovery.md)
- [Your first project, from install to graph](../getting-started/first-project.md)

---

## Identity

- Topic id: `concept:strictness-mode`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:73ec358e89ebaace`
