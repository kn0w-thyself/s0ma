# Concepts index

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

s0ma teaches 39 concepts. Each one has a short definition here and a full entry — what it is for, when to reach for it, when not to — in the composed model at `docs/_generated/inventory-concepts.json`.

| Concept | Id | In short |
| --- | --- | --- |
| .s0ma file | `concept:s0ma-file` | One source file: a module header first, then declarations, each separated from its code by a line of three hyphens. |
| adoption ladder | `concept:adoption-ladder` | The five-rung path a working Python codebase takes to become a s0ma application, one rung at a time. |
| authored-vs-generated boundary | `concept:authored-vs-generated-boundary` | The line between what a person writes and what the build works out for itself, with no fact living on both sides of it. |
| axon | `concept:axon` | A written-down dependency between two parts: which one leans on which, why, and how tightly. |
| canonical IR | `concept:canonical-ir` | The normalised record of one file's declarations that the build writes beside the code, for tools to read. |
| cell | `concept:cell` | A declared piece of structure — a data shape, a fixed value, a setting, a type, or an error kind — rather than a piece of behaviour. |
| check and build loop | `concept:check-and-build-loop` | The everyday cycle: check the source, build it, run the verifications, then ask the system what it now contains. |
| contract | `concept:contract` | What a working part needs before it runs, what it promises afterwards, and what it must never do, declared beside the code that has to keep all three. |
| doc-guide | `concept:doc-guide` | A written guide whose every factual claim about a named part is checked against the system rather than trusted. |
| doc-ref | `concept:doc-ref` | A reference page assembled entirely from what the system already knows about itself, carrying no prose of its own. |
| drift | `concept:drift` | The gap that opens when a written description and the thing it describes stop agreeing. |
| drift-gate | `concept:drift-gate` | The build step that refuses a change when the written record and the system it describes have parted. |
| embodiment | `concept:embodiment` | Bringing the physical parts of a machine inside the boundary of what a system knows about itself, as ordinary declared parts. |
| example | `concept:example` | A short runnable demonstration, registered against the parts it teaches, that has to keep working. |
| executable evidence | `concept:executable-evidence` | The rule that every factual claim in a document is printed from the system, checked against it, or demonstrated by code that runs. |
| feedback | `concept:feedback` | A report to the people who make s0ma, shown to you in full and sent only after you approve that exact report. |
| ganglion | `concept:ganglion` | A declared watcher: it observes named parts of the system and judges what it sees against what it expected. |
| helper | `concept:helper` | A small private function inside one file, described but deliberately not registered as a part of the system. |
| integration | `concept:integration` | A declared adapter to an outside system, naming how to build it, how to check it is alive, and what it needs to run. |
| intent | `concept:intent` | The declared reason a part exists, required on every part without exception. |
| interoception | `concept:interoception` | The runtime-state faculty: a system's sense of how it is behaving against how it said it would. |
| kind | `concept:kind` | The functional archetype of a part: what sort of working logic it is, or what sort of structure it holds. |
| layer | `concept:layer` | The architectural band a file and everything in it belongs to, and the rule about which bands may depend on which. |
| metacognition | `concept:metacognition` | The reasoning faculty: answering questions by working over the system's own model rather than over its code. |
| mirror | `concept:mirror` | A committed copy of a document, held identical to its one source by a check that fails when they part. |
| module | `concept:module` | The header every s0ma source file opens with, naming the file and declaring everything that enters and leaves it. |
| nerve | `concept:nerve` | A piece of working logic that carries its own account of what it does, what it needs, and what it promises. |
| perimeter | `concept:perimeter` | The line a project draws around the code s0ma answers for, and the files it deliberately leaves outside. |
| proprioception | `concept:proprioception` | The structural faculty: a system's sense of what it is made of and how it is wired together. |
| registry snapshot | `concept:registry-snapshot` | The live index of every part in a running system, each held under the full name that joins its file and itself. |
| release channel | `concept:release-channel` | Which build a page came from — a released version, a preview of work in progress, or a record kept for a version that has passed. |
| requires: | `concept:requires` | The module header's list of code from outside the project — the ordinary Python imports, declared. |
| s0ma | `concept:s0ma` | The platform built on one idea: software should carry an accurate, queryable model of itself. |
| self-knowledge | `concept:self-knowledge` | The umbrella faculty: a system's ability to hold an accurate, queryable model of itself. |
| self-model | `concept:self-model` | The queryable record of a system's parts, their relationships, and the documentation and examples attached to them. |
| strictness mode | `concept:strictness-mode` | How severely the build treats its own findings, from forgiving during adoption to unforgiving before a release. |
| test | `concept:test` | A verification written as a declared part of the system, naming exactly which parts it checks. |
| uses: | `concept:uses` | The module header's list of parts in other s0ma files that this file is allowed to reach. |
| visibility | `concept:visibility` | Who may call a part from another file: everyone, nobody, or verification code only. |
