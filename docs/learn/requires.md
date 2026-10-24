# requires:

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

The module header's list of code from outside the project — the ordinary Python imports, declared.

## What it is

The requires list names the outside code a file needs: standard library modules, installed packages, and specific names from either. The build turns each entry into the right import line. Sibling lists cover the variations — one for packages that may not be installed, one for imports a running system supplies in a way no checker can see, and one for imports deferred until the moment they are first used.

## Why it exists

It puts outside dependencies in the same declared place as everything else, so a file's needs can be read in one block instead of searched for. It also lets the build confirm that what a file claims to need is really installed, and say so when a file claims something it never uses.

## When to use it

List an entry for every outside module or name the file's code refers to, and choose the sibling list that matches how the dependency should fail: quietly absent, invisible to the checker, or deferred to the first call.

## When not to use it

Do not use it for parts of your own project written in this language; those belong in the uses list. And do not expect these names in the declaration fields themselves — those fields may only name things the system is able to describe.

## How it is written

```text
module <name>
    requires: [<module>, <package.Name>, <package:name>]
    soft_requires: [<packages that may not be installed>]
```

## Related ideas

- contrasts-with [uses:](uses.md)
- part-of [module](module.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/dependency-categories`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#4.5.1`

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
- [Building an app with s0ma over MCP — walkthrough](../walkthrough.md)
- [Packaging a s0ma project as a wheel](../guides/packaging.md)
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)

---

## Identity

- Topic id: `concept:requires`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:f3b5e3182c59c01d`
