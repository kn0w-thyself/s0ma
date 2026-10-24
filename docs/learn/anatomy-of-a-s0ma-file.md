# Anatomy of a .s0ma file

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

## In short

One source file: a module header first, then declarations, each separated from its code by a line of three hyphens.

## What it is

A s0ma source file has a fixed anatomy. It opens with the module header that speaks for the whole file, then carries one or more declarations, and every piece of code in it belongs to exactly one of them — the language refuses a block that belongs to none. Inside a declaration the description comes first and the code comes after, with a line of exactly three hyphens at the left margin between them.

## Why it exists

The fixed shape is what lets both people and machines read a file with no guesswork: the header always says what the file is, the description always comes before the code it describes, and the separator always marks where one stops and the other starts. Nothing about a file's meaning depends on convention or on where a reader happens to look.

## The shape of the file

```text
module <name>
    layer: <LAYER>
    version: <MAJOR.MINOR.PATCH>
    intent: "<what this module is responsible for>"
    exports: [<public component names>]
# then one or more declarations, in any order:
<declaration header>
    <description fields>
    ---
    <code>
```

## The parts a file is made of

A file may contain 11 kinds of declaration. They are listed here in the order the specification defines them, each with the section that defines it and a link to its whole entry.

### nerve

A piece of working logic that carries its own account of what it does, what it needs, and what it promises.

- Whole entry: [nerve](nerve.md)
- Defined in: `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, section `4.1`

```text
nerve <name> :: <LAYER>
    kind: <KIND>
    visibility: <PUBLIC | INTERNAL | TEST>
    intent: "<why this component exists>"
    expects: "<preconditions>"
    guarantees: "<postconditions>"
    forbids: "<what it must never do>"
    evaluates_at: <FUNCTION_BOUNDARY | SUBSYSTEM | SYSTEM>
    ---
    def <name>(<args>) -> <return type>:
        <body>
```

### cell

A declared piece of structure — a data shape, a fixed value, a setting, a type, or an error kind — rather than a piece of behaviour.

- Whole entry: [cell](cell.md)
- Defined in: `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, section `4.2`

```text
cell <Name> :: <LAYER>
    kind: <KIND>
    visibility: <PUBLIC | INTERNAL | TEST>
    intent: "<why this component exists>"
    schema: "<what data this represents>"
    ---
    <Python class, constant, or type definition>
```

### ganglion

A declared watcher: it observes named parts of the system and judges what it sees against what it expected.

- Whole entry: [ganglion](ganglion.md)
- Defined in: `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, section `4.3`

```text
ganglion <name> :: <LAYER>
    visibility: <PUBLIC | INTERNAL | TEST>
    intent: "<what this evaluator assesses>"
    observes: [<part names or patterns>]
    scope: <FUNCTION_BOUNDARY | SUBSYSTEM | SYSTEM>
    priors: "<what normal is expected to look like>"
    on_anomaly: "<what to do when it is not>"
    forbids: "<what it must never do while it watches>"
    ---
    def <name>(signal: Signal) -> EvaluationResult:
        <body>
```

### axon

A written-down dependency between two parts: which one leans on which, why, and how tightly.

- Whole entry: [axon](axon.md)
- Defined in: `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, section `4.4`

```text
axon <source> -> <target>
    relation: <CALLS | CONSTRUCTS | READS | CONFIGURES | PRODUCES | CONSUMES>
    intent: "<why this connection exists>"
    carries: "<what travels along it>"
    coupling: <TIGHT | LOOSE>
```

### helper

A small private function inside one file, described but deliberately not registered as a part of the system.

- Whole entry: [helper](helper.md)
- Defined in: `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, section `4.4a`

```text
helper _<name> :: <LAYER>
    intent: "<why this helper exists>"
    ---
    def _<name>(...) -> ...:
        <body>
```

### integration

A declared adapter to an outside system, naming how to build it, how to check it is alive, and what it needs to run.

- Whole entry: [integration](integration.md)
- Defined in: `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, section `4.4b`

```text
integration <Name> :: INFRASTRUCTURE
    version: <MAJOR.MINOR.PATCH>
    intent: "<why this integration exists>"
    factory: <FactoryNerveName>
    smoke_test_primary: <SmokeTestNerveName>
    manifest:
      provides: [<operation names>]
      required_env: [<setting names>]
```

### module

The header every s0ma source file opens with, naming the file and declaring everything that enters and leaves it.

- Whole entry: [module](module.md)
- Defined in: `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, section `4.5`

```text
module <name>
    layer: <LAYER>
    version: <MAJOR.MINOR.PATCH>
    intent: "<what this module is responsible for>"
    exports: [<public component names>]
```

### test

A verification written as a declared part of the system, naming exactly which parts it checks.

- Whole entry: [test](test.md)
- Defined in: `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, section `4.8`

```text
test test_<name> :: <LAYER>
    intent: "<what behaviour this verifies>"
    tests: [<component names this verifies>]
    ---
    def test_<name>():
        <body>
```

### doc-ref

A reference page assembled entirely from what the system already knows about itself, carrying no prose of its own.

- Whole entry: [doc-ref](doc-ref.md)
- Defined in: `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, section `4.12.1`

```text
doc-ref <name>
    intent: "<why this reference exists>"
    format: <markdown | html | json>
    output: <relative file path>
    covers: [<filter expression>]
    sections: [<field names to show>]
```

### doc-guide

A written guide whose every factual claim about a named part is checked against the system rather than trusted.

- Whole entry: [doc-guide](doc-guide.md)
- Defined in: `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, section `4.12.2`

```text
doc-guide <name>
    intent: "<why this guide exists>"
    format: <markdown | html | json>
    output: <relative file path>
    covers: [<entity references>]
    asserts: [<claims the build can check>]
    examples: [example::<name>]
    ---
    <prose, naming parts through {{nerve::X}} style references>
```

### example

A short runnable demonstration, registered against the parts it teaches, that has to keep working.

- Whole entry: [example](example.md)
- Defined in: `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, section `4.12.3`

```text
example <name>
    intent: "<what this example teaches>"
    demonstrates: [<entity references>]
    runs_in: <standalone | pytest | integration>
    ---
    <Python body>
```

## The smallest complete file

A header and one declaration. Both written forms below are the ones module and nerve carry above, unedited.

```text
module <name>
    layer: <LAYER>
    version: <MAJOR.MINOR.PATCH>
    intent: "<what this module is responsible for>"
    exports: [<public component names>]

nerve <name> :: <LAYER>
    kind: <KIND>
    visibility: <PUBLIC | INTERNAL | TEST>
    intent: "<why this component exists>"
    expects: "<preconditions>"
    guarantees: "<postconditions>"
    forbids: "<what it must never do>"
    evaluates_at: <FUNCTION_BOUNDARY | SUBSYSTEM | SYSTEM>
    ---
    def <name>(<args>) -> <return type>:
        <body>
```

## Where to look next

- [Your first module: the anatomy of a .s0ma file](../guides/first-module.md)
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

- Release: `0.19.1 (preview)`
- Documentation snapshot: `sha256:f0638b89b84dfd6c`
