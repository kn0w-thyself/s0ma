# Glossary

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

s0ma's vocabulary is 39 ideas. Each row gives the short form; the term links to the whole entry — what it is, why it exists, when to reach for it and when not to.

| Term | Id | In short |
| --- | --- | --- |
| [.s0ma file](s0ma-file.md) | `concept:s0ma-file` | One source file: a module header first, then declarations, each separated from its code by a line of three hyphens. |
| [adoption ladder](adoption-ladder.md) | `concept:adoption-ladder` | The five-rung path a working Python codebase takes to become a s0ma application, one rung at a time. |
| [authored-vs-generated boundary](authored-vs-generated-boundary.md) | `concept:authored-vs-generated-boundary` | The line between what a person writes and what the build works out for itself, with no fact living on both sides of it. |
| [axon](axon.md) | `concept:axon` | A written-down dependency between two parts: which one leans on which, why, and how tightly. |
| [canonical IR](canonical-ir.md) | `concept:canonical-ir` | The normalised record of one file's declarations that the build writes beside the code, for tools to read. |
| [cell](cell.md) | `concept:cell` | A declared piece of structure — a data shape, a fixed value, a setting, a type, or an error kind — rather than a piece of behaviour. |
| [check and build loop](check-and-build-loop.md) | `concept:check-and-build-loop` | The everyday cycle: check the source, build it, run the verifications, then ask the system what it now contains. |
| [contract](contract.md) | `concept:contract` | What a working part needs before it runs, what it promises afterwards, and what it must never do, declared beside the code that has to keep all three. |
| [doc-guide](doc-guide.md) | `concept:doc-guide` | A written guide whose every factual claim about a named part is checked against the system rather than trusted. |
| [doc-ref](doc-ref.md) | `concept:doc-ref` | A reference page assembled entirely from what the system already knows about itself, carrying no prose of its own. |
| [drift](drift.md) | `concept:drift` | The gap that opens when a written description and the thing it describes stop agreeing. |
| [drift-gate](drift-gate.md) | `concept:drift-gate` | The build step that refuses a change when the written record and the system it describes have parted. |
| [embodiment](embodiment.md) | `concept:embodiment` | Bringing the physical parts of a machine inside the boundary of what a system knows about itself, as ordinary declared parts. |
| [example](example.md) | `concept:example` | A short runnable demonstration, registered against the parts it teaches, that has to keep working. |
| [executable evidence](executable-evidence.md) | `concept:executable-evidence` | The rule that every factual claim in a document is printed from the system, checked against it, or demonstrated by code that runs. |
| [feedback](feedback.md) | `concept:feedback` | A report to the people who make s0ma, shown to you in full and sent only after you approve that exact report. |
| [ganglion](ganglion.md) | `concept:ganglion` | A declared watcher: it observes named parts of the system and judges what it sees against what it expected. |
| [helper](helper.md) | `concept:helper` | A small private function inside one file, described but deliberately not registered as a part of the system. |
| [integration](integration.md) | `concept:integration` | A declared adapter to an outside system, naming how to build it, how to check it is alive, and what it needs to run. |
| [intent](intent.md) | `concept:intent` | The declared reason a part exists, required on every part without exception. |
| [interoception](interoception.md) | `concept:interoception` | The runtime-state faculty: a system's sense of how it is behaving against how it said it would. |
| [kind](kind.md) | `concept:kind` | The functional archetype of a part: what sort of working logic it is, or what sort of structure it holds. |
| [layer](layer.md) | `concept:layer` | The architectural band a file and everything in it belongs to, and the rule about which bands may depend on which. |
| [metacognition](metacognition.md) | `concept:metacognition` | The reasoning faculty: answering questions by working over the system's own model rather than over its code. |
| [mirror](mirror.md) | `concept:mirror` | A committed copy of a document, held identical to its one source by a check that fails when they part. |
| [module](module.md) | `concept:module` | The header every s0ma source file opens with, naming the file and declaring everything that enters and leaves it. |
| [nerve](nerve.md) | `concept:nerve` | A piece of working logic that carries its own account of what it does, what it needs, and what it promises. |
| [perimeter](perimeter.md) | `concept:perimeter` | The line a project draws around the code s0ma answers for, and the files it deliberately leaves outside. |
| [proprioception](proprioception.md) | `concept:proprioception` | The structural faculty: a system's sense of what it is made of and how it is wired together. |
| [registry snapshot](registry-snapshot.md) | `concept:registry-snapshot` | The live index of every part in a running system, each held under the full name that joins its file and itself. |
| [release channel](release-channel.md) | `concept:release-channel` | Which build a page came from — a released version, a preview of work in progress, or a record kept for a version that has passed. |
| [requires:](requires.md) | `concept:requires` | The module header's list of code from outside the project — the ordinary Python imports, declared. |
| [s0ma](s0ma.md) | `concept:s0ma` | The platform built on one idea: software should carry an accurate, queryable model of itself. |
| [self-knowledge](self-knowledge.md) | `concept:self-knowledge` | The umbrella faculty: a system's ability to hold an accurate, queryable model of itself. |
| [self-model](self-model.md) | `concept:self-model` | The queryable record of a system's parts, their relationships, and the documentation and examples attached to them. |
| [strictness mode](strictness-mode.md) | `concept:strictness-mode` | How severely the build treats its own findings, from forgiving during adoption to unforgiving before a release. |
| [test](test.md) | `concept:test` | A verification written as a declared part of the system, naming exactly which parts it checks. |
| [uses:](uses.md) | `concept:uses` | The module header's list of parts in other s0ma files that this file is allowed to reach. |
| [visibility](visibility.md) | `concept:visibility` | Who may call a part from another file: everyone, nobody, or verification code only. |

## Other names for the same ideas

21 other names resolve onto one of the terms above. Every one of them can be asked for by name and answers with the entry it points at.

| Also called | See |
| --- | --- |
| `concept:authored-vs-derived-split` | [authored-vs-generated boundary](authored-vs-generated-boundary.md) |
| `concept:check-drift` | [drift-gate](drift-gate.md) |
| `concept:contracts` | [contract](contract.md) |
| `concept:embodied-hardware` | [embodiment](embodiment.md) |
| `concept:evaluator` | [ganglion](ganglion.md) |
| `concept:executable-demonstration` | [example](example.md) |
| `concept:external-system-adapter` | [integration](integration.md) |
| `concept:feedback-report` | [feedback](feedback.md) |
| `concept:file-level-declaration` | [module](module.md) |
| `concept:inter-component-connection` | [axon](axon.md) |
| `concept:ir` | [canonical IR](canonical-ir.md) |
| `concept:module-private-function` | [helper](helper.md) |
| `concept:observable-function` | [nerve](nerve.md) |
| `concept:reasoning-faculty` | [metacognition](metacognition.md) |
| `concept:runtime-state-faculty` | [interoception](interoception.md) |
| `concept:software-self-knowledge` | [self-knowledge](self-knowledge.md) |
| `concept:strictness` | [strictness mode](strictness-mode.md) |
| `concept:structural-component` | [cell](cell.md) |
| `concept:structural-faculty` | [proprioception](proprioception.md) |
| `concept:structural-projection` | [doc-ref](doc-ref.md) |
| `concept:verification-component` | [test](test.md) |

## Where to look next

- [Anatomy of a .s0ma file](anatomy-of-a-s0ma-file.md)
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
- Documentation snapshot: `sha256:8566b7670125c9fa`
