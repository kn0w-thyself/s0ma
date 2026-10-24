# visibility

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

Who may call a part from another file: everyone, nobody, or verification code only.

## What it is

Every working and structural part declares a visibility. Public means other files may use it, provided the module header lists it too. Internal means only the file it lives in may call it. The third setting opens a part to verification code anywhere in the project without putting it on the public surface. Visibility governs calling and nothing else: watchers, verifications and the documentation machinery reach every part regardless, because a system that cannot see all of itself cannot describe itself.

## Why it exists

It separates two questions that are usually tangled: who may depend on this, and who may look at it. Making the first restrictive and the second total is what lets a s0ma system keep a small public surface and a complete self-description at the same time.

## When to use it

Mark a part public when other files are meant to use it, internal when it is an implementation detail, and use the third setting for a detail that verification code genuinely has to exercise directly.

## When not to use it

Do not mark something public purely so a verification can reach it; that is exactly the workaround the third setting exists to retire. And do not read internal as hidden — an internal part is fully visible to watchers, verifications, and anything asking the system what it contains.

## How it is written

```text
nerve <name> :: <LAYER>
    visibility: <PUBLIC | INTERNAL | TEST>
```

## Related ideas

- contrasts-with [kind](kind.md)
- contrasts-with [layer](layer.md)
- requires [module](module.md)

## Worked examples

- none recorded

## What decides this

- `authority:spec/visibility-system`

## Where to read the decision

- `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md#5`

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
- [Retrofitting an existing codebase](../guides/retrofit-existing-codebase.md)
- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)

---

## Identity

- Topic id: `concept:visibility`
- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:ec62ca0343ef8be5`
