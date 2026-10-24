# The documentation application

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

This is the page s0ma writes about the thing that writes its pages. Everything below is read out of the build that rendered it: the 11 readings it composed the model from, the 21 gates it ran over the result, the 8 declarations its own s0ma module registers, and the 67 files it writes — one of which is this one.

That last sentence is the point of the page. A documentation build that could not describe its own readings would be asking a reader to take on faith exactly the property the product exists to make checkable, so the account is generated from the build rather than written beside it, and it is byte-compared like every other output here.

This page describes the build stamped `sha256:8566b7670125c9fa` at version `0.19.1 (preview)`. What each of those 67 files came out as, with the digest of its exact bytes, is in [`docs/_generated/docs-manifest.json`](../_generated/docs-manifest.json).

## Contents

- [The readings](#the-readings)
- [The gates](#the-gates)
- [What it covers](#what-it-covers)
- [What the application registers about itself](#what-the-application-registers-about-itself)
- [What it writes](#what-it-writes)

## The readings

11 readings, 49 sources between them, 661 records composed. A reading is one adapter over one kind of source: it is handed a checkout, it produces records that each carry the source they came from and the digest of what was read, and it never sees another reading's answer. The merge is the only place they meet, and it sorts every group before the model is built — so the order the readings run in cannot change what the build says.

**Sources** is how many distinct files or in-process readings the adapter drew on, and **Records** is how many records it contributed. **Groups it fills** names which parts of the model those records landed in, with the count in each; an adapter that fills one group is not a lesser reading than one that fills four, it is a narrower question asked completely.

| Reading | Sources | Records | Groups it fills |
| --- | --- | --- | --- |
| `catalog` | 1 | 170 | documents 170 |
| `cli` | 1 | 44 | surfaces 44 |
| `concepts-language` | 1 | 55 | authorities 30, concepts 25 |
| `concepts-product` | 1 | 17 | authorities 3, concepts 14 |
| `config` | 1 | 19 | surfaces 19 |
| `core` | 3 | 43 | surfaces 43 |
| `diagnostics` | 1 | 115 | surfaces 115 |
| `journeys` | 7 | 7 | journeys 7 |
| `mcp` | 1 | 36 | surfaces 36 |
| `repo` | 28 | 144 | authorities 144 |
| `studi0` | 4 | 11 | authorities 6, surfaces 5 |

## The gates

21 gates run over every composition, and all of them run on every build: the report is collected rather than stopped at the first finding, so a build tells an author everything that is wrong in one pass instead of one thing per run. Between them they can report 20 distinct diagnostics.

**What it checks** is the gate's own first line and **What it reports** is the codes that gate names, both quoted rather than rewritten — a gate whose stated purpose and real one had parted company is a defect in the gate, and a description written here would hide it. What each code means for a reader, and what to do about it, is on the [diagnostics page](../reference/diagnostics.md).

| Gate | Where it lives | What it checks | What it reports |
| --- | --- | --- | --- |
| `check_surface_index` | `application` | Every served capability appears in the rendered index of them. | `DOC_SURFACE_UNCOVERED` |
| `check_evidence_voice` | `evidence` | Every authored sentence of a fixture is in the product's voice. | `DOC_VOICE_VIOLATION` |
| `check_canonical_sources` | `providers_catalog` | No file is the canonical source of two documents. | `DOC_CANONICAL_DUPLICATE` |
| `check_completeness` | `providers_catalog` | Every tracked document has a row, or says why it has none. | `DOC_DOCUMENT_UNCATALOGED` |
| `check_document_authorities` | `providers_catalog` | Every `authority` a catalog row claims is an authority that exists. | `DOC_TOPIC_UNRESOLVED` |
| `check_concept_relations` | `providers_concepts` | Every concept-to-concept edge in a composed bundle holds. | `DOC_CONCEPT_UNRESOLVED` |
| `check_voice` | `providers_concepts` | Every authored prose field is written in the product's own voice. | `DOC_VOICE_VIOLATION` |
| `check_journey_voice` | `providers_journeys` | Every authored prose field of a journey is in the product's voice. | `DOC_VOICE_VIOLATION` |
| `check_quick_reference_voice` | `quick_reference` | Every authored sentence of the quick reference is in the product's voice. | `DOC_VOICE_VIOLATION` |
| `check_budget` | `render_agent` | Is this answer small enough for the channel it is served on? | `DOC_TOPIC_OVERSIZED` |
| `check_coverage` | `resolve` | Everything this build knows about can actually be shown. | `DOC_CONCEPT_UNCOVERED`, `DOC_SURFACE_UNCOVERED` |
| `check_journey_coverage` | `resolve` | Every primary capability is taught, and every surface is classified. | `DOC_CAPABILITY_UNCOVERED`, `DOC_GATE_VACUOUS` |
| `check_authority_records` | `validate` | No authority record contradicts itself. | `DOC_AUTHORITY_MISDECLARED` |
| `check_floors` | `validate` | No provider quietly stopped producing (`DOC_GATE_VACUOUS`). | `DOC_GATE_VACUOUS` |
| `check_journeys` | `validate` | The four rules a journey has to satisfy beyond resolving. | `DOC_APPROVAL_UNDECLARED`, `DOC_GATE_VACUOUS`, `DOC_JOURNEY_UNRESOLVED`, `DOC_JOURNEY_UNTESTED`, `DOC_TEACHING_ORDER` |
| `check_manifest` | `validate` | One documentation manifest describes one build of one version. | `DOC_VERSION_MISMATCH` |
| `check_provenance` | `validate` | Every record can be traced to a source, a schema and a digest. | `DOC_PROVENANCE_MISSING` |
| `check_references` | `validate` | Every edge target resolves (architecture plan §6.7). | `DOC_CONCEPT_UNRESOLVED`, `DOC_JOURNEY_UNRESOLVED`, `DOC_SURFACE_UNBOUND`, `DOC_TOPIC_UNRESOLVED` |
| `check_sequences` | `validate` | Every step of every ordered sequence resolves, and none repeats. | `DOC_GATE_VACUOUS`, `DOC_SEQUENCE_REPEATS` |
| `check_side_effects` | `validate` | Every surface says what calling it does, or a named source says why not. | `DOC_GATE_VACUOUS`, `DOC_SIDE_EFFECT_UNDECLARED` |
| `check_surface_binding` | `validate` | Every served capability is bound, or says in writing why it is not. | `DOC_SURFACE_UNBOUND` |

## What it covers

332 of the 502 things this build is required to cover are covered, 204 carry a written exception, and 0 are neither. That last number is the one to read: a gate says nothing when it finds nothing, so a silent build and a build whose gates were never armed look identical from outside. This is the standing positive answer.

**By written exception** counts the members somebody has excused in a reviewable ledger, with a reason, one at a time. Every one of them is named — with the file its permission is written in — in [`docs/_generated/coverage-report.json`](../_generated/coverage-report.json); they are counted here and listed there because a page carrying 204 ids is a page nobody reads. **Not covered** is what no ledger excuses and nothing covers, and it is the number the gates are armed to keep at zero.

| Set | Required | Covered | By written exception | Not covered |
| --- | --- | --- | --- | --- |
| concepts | 39 | 39 | 0 | 0 |
| surfaces | 262 | 92 | 170 | 0 |
| journeys | 17 | 17 | 30 | 0 |
| discovery | 14 | 14 | 0 | 0 |
| catalog | 170 | 170 | 4 | 0 |

Two of those ledgers are bounded, and the bound is a review moment rather than a limit anybody expects to reach: an ordinary addition lands inside the headroom, and a whole new family of exceptions turns the build red before it arrives — which is when the conversation about whether it should have been an exception at all is still worth having.

| Ledger | Set | Entries | Ceiling | Headroom |
| --- | --- | --- | --- | --- |
| `unbound` | surfaces | 170 | 175 | 5 |
| `reference_only_surfaces` | journeys | 25 | 30 | 5 |

**How each set is measured** is stated per set in the report rather than assumed to be the same, because it is not. Four of the five are measured here; discovery is not, and says so. Its routes are properties of the running product — a help text, a server's instructions, a scaffolded file — which no build-time gate has in front of it, so the report names each route, the contract clause it comes from and the suite that runs it, and claims nothing about having checked it during the build.

## What the application registers about itself

The documentation application is itself written in s0ma: `application` at version `1.0.0`, in the application layer. It is a s0ma project the way any application built with s0ma is one, which is why what it registers about itself can be read here at all — the same way every other registered component in this repository is read for the [component index](component-index.md).

What that module says it is for, in its own words:

> The documentation application: the one place that says which sources s0ma's documentation is composed from, which gates it must pass, and what it renders. The machinery is general and ships in the s0ma-dsl wheel; what is here is this repository's own use of it, registered as components so that s0ma knows how it documents itself the same way it knows anything else about itself.

| Declaration | Kind | Visible | What it is for |
| --- | --- | --- | --- |
| `application::COMPOSED_SNAPSHOT` (cell) | constant | public | The composed snapshot's place under the documentation root. It sits in the machine-readable directory because a program reads it and a person does not; reader-facing pages never share a path with it. |
| `application::DOCUMENTATION_ROOT` (cell) | constant | public | Where the documentation application lives, relative to the checkout. Every provider addresses its sources against the checkout, so this name is fixed rather than configurable: renaming it would rename them too. |
| `application::GENERATED_INVENTORIES` (cell) | constant | public | The nineteen files this application decides to render besides the snapshot. Seven are read by a program rather than by a person — three inventories of what s0ma knows about itself, the teaching content s0ma-core carries inside its own wheel, which is generated here and mirrored into that package so that an installed copy can answer a question about s0ma with this repository nowhere in sight, the coverage report, which states how much of what this build is required to cover it does cover and names every standing exception with the ledger that grants it, the quick reference written as data, so that a coding agent can read every line of every kind of declaration without reading a page laid out for a person, and the manifest of what this build is: the version it describes, the sources it read, the digest of the model it composed, and every file it wrote with the hash of what each one says. The other twelve are pages a person opens — an index of the concepts, an index of the capabilities, README.md (the map of every document this repository keeps), a reference for each family of capability the product serves (the command line, the settings a project can declare, the reports s0ma can make, the servers it answers agents on, and the viewer it shows a project through), a page naming the distributions this workspace ships, an index of every registered component behind all of them, the quick reference, which puts every kind of declaration and every line each one may carry on a single page and is rendered from the same value as its data twin so that the two cannot disagree, and architecture/docs-application.md, which turns that same treatment on this application: the readings it composes from, the gates it runs, what this module registers, and every file it writes, so that the account of how s0ma documents itself is generated from the build rather than written beside it and can be compared byte for byte like anything else here. The snapshot is named separately above, because it is the composed model itself rather than a listing taken from it; the two together are everything the composition decides to write, and the learning collection beside them is computed rather than decided, so it is named in its own cell below. One further page leaves this project and is deliberately absent from this list — reference/documentation-application.md, which the documentation emitter renders from the doc-ref declared at the top of this module rather than from the composed snapshot. It is named there, where the declaration that produces it is, because a list of what one command writes should not quietly include what another one does; it is also the reason the composed page above is called docs-application rather than documentation-application, since two pages one letter apart in two directories is a distinction a reader should not have to make. |
| `application::LEARNING_COLLECTION` (cell) | constant | public | Where the learning collection is written, relative to the documentation root: one page for every concept the composition holds, a glossary over all of them, and the anatomy of a .s0ma file. The pages are not listed here, and that is the decision this cell records — which concepts exist is authored in the concept files, so the set is computed from the composed model each build. A list of them here would be a second inventory somebody had to keep, and the day a concept was written it would ship with no page until somebody remembered this file. |
| `application::SOURCES_COMPOSED` (cell) | constant | public | The eleven readings this repository's documentation is composed from, in the order a person would meet them. Five say what s0ma is: what the framework registers about itself, what the repository's governing documents say, the two files of authored teaching vocabulary, and the catalog of every document that exists. Five say what s0ma serves: its command line, the diagnostics it can report, the keys a project can be configured with, the server it answers agents on, and the viewer it shows a project through. The last says how a person gets from one to the other: the authored paths through those capabilities, step by step. |
| `application::compose_documentation` (nerve) | orchestrator | public | Reads every source once and settles them into a single picture of what s0ma knows about itself, which then stays the same for the rest of the build. |
| `application::documentation_artifacts` (nerve) | function | public | What a composition renders to, held in memory rather than written down, so that the command that writes the files and the command that checks them are looking at the same bytes. |
| `application::documentation_findings` (nerve) | function | public | Everything wrong with a composition, all of it at once. A run that stopped at the first problem would make somebody fix the documentation one line per run. |

## What it writes

67 files, and the build writes exactly these: the writer writes this set and the checker compares this set, so neither can grow an output the other has not heard of. 20 of them are decisions — somebody decided this repository should commit that file — and the remaining 47 are computed from what the build composed, because a page per concept and a package per journey are not choices anybody takes one file at a time.

**The document it is** joins the output onto the catalog row whose canonical source is that path. An output with no row is not an uncataloged page: reader-facing pages never live under `_generated/`, so a file that does live there is a machine artifact and its stated absence of a row is the honest answer.

### Decided

| Output | Format | The document it is |
| --- | --- | --- |
| `_generated/s0ma-docs-model.json` | `json` | no catalog row — a machine artifact, not a page |
| `_generated/inventory-concepts.json` | `json` | no catalog row — a machine artifact, not a page |
| `_generated/inventory-surfaces.json` | `json` | no catalog row — a machine artifact, not a page |
| `_generated/inventory-components.json` | `json` | no catalog row — a machine artifact, not a page |
| `reference/concepts-index.md` | `markdown` | Concepts index |
| `reference/surfaces-index.md` | `markdown` | What s0ma can do |
| `README.md` | `markdown` | The s0ma documentation: the map of record |
| `reference/cli.md` | `markdown` | The s0ma command line |
| `reference/configuration.md` | `markdown` | Project settings |
| `reference/diagnostics.md` | `markdown` | Reports s0ma can make |
| `reference/mcp.md` | `markdown` | The MCP servers |
| `reference/studi0.md` | `markdown` | studi0, the viewer |
| `reference/packages.md` | `markdown` | The distributions s0ma ships |
| `architecture/component-index.md` | `markdown` | Component index |
| `architecture/docs-application.md` | `markdown` | The documentation application |
| `_generated/core-teaching-slice.json` | `package_data` | no catalog row — a machine artifact, not a page |
| `_generated/coverage-report.json` | `json` | no catalog row — a machine artifact, not a page |
| `reference/quick-reference-readable.md` | `markdown` | s0ma quick reference |
| `_generated/quick-reference-machine.json` | `json` | s0ma quick reference, as data |
| `_generated/docs-manifest.json` | `json` | no catalog row — a machine artifact, not a page |

### Computed

| Output | Format | The document it is |
| --- | --- | --- |
| `learn/adoption-ladder.md` | `markdown` | adoption ladder, explained |
| `learn/anatomy-of-a-s0ma-file.md` | `markdown` | Anatomy of a .s0ma file |
| `learn/authored-vs-generated-boundary.md` | `markdown` | authored-vs-generated boundary, explained |
| `learn/axon.md` | `markdown` | axon, explained |
| `learn/canonical-ir.md` | `markdown` | canonical IR, explained |
| `learn/cell.md` | `markdown` | cell, explained |
| `learn/check-and-build-loop.md` | `markdown` | check and build loop, explained |
| `learn/contract.md` | `markdown` | contract, explained |
| `learn/doc-guide.md` | `markdown` | doc-guide, explained |
| `learn/doc-ref.md` | `markdown` | doc-ref, explained |
| `learn/drift-gate.md` | `markdown` | drift-gate, explained |
| `learn/drift.md` | `markdown` | drift, explained |
| `learn/embodiment.md` | `markdown` | embodiment, explained |
| `learn/example.md` | `markdown` | example, explained |
| `learn/executable-evidence.md` | `markdown` | executable evidence, explained |
| `learn/feedback.md` | `markdown` | feedback, explained |
| `learn/ganglion.md` | `markdown` | ganglion, explained |
| `learn/glossary.md` | `markdown` | Glossary |
| `learn/helper.md` | `markdown` | helper, explained |
| `learn/integration.md` | `markdown` | integration, explained |
| `learn/intent.md` | `markdown` | intent, explained |
| `learn/interoception.md` | `markdown` | interoception, explained |
| `learn/kind.md` | `markdown` | kind, explained |
| `learn/layer.md` | `markdown` | layer, explained |
| `learn/metacognition.md` | `markdown` | metacognition, explained |
| `learn/mirror.md` | `markdown` | mirror, explained |
| `learn/module.md` | `markdown` | module, explained |
| `learn/nerve.md` | `markdown` | nerve, explained |
| `learn/perimeter.md` | `markdown` | perimeter, explained |
| `learn/proprioception.md` | `markdown` | proprioception, explained |
| `learn/registry-snapshot.md` | `markdown` | registry snapshot, explained |
| `learn/release-channel.md` | `markdown` | release channel, explained |
| `learn/requires.md` | `markdown` | requires:, explained |
| `learn/s0ma-file.md` | `markdown` | .s0ma file, explained |
| `learn/s0ma.md` | `markdown` | s0ma, explained |
| `learn/self-knowledge.md` | `markdown` | self-knowledge, explained |
| `learn/self-model.md` | `markdown` | self-model, explained |
| `learn/strictness-mode.md` | `markdown` | strictness mode, explained |
| `learn/test.md` | `markdown` | test, explained |
| `learn/uses.md` | `markdown` | uses:, explained |
| `learn/visibility.md` | `markdown` | visibility, explained |
| `_generated/media/drift-recovery.json` | `media_manifest` | no catalog row — a machine artifact, not a page |
| `_generated/media/first-module.json` | `media_manifest` | no catalog row — a machine artifact, not a page |
| `_generated/media/first-project.json` | `media_manifest` | no catalog row — a machine artifact, not a page |
| `_generated/media/mcp-authoring-loop.json` | `media_manifest` | no catalog row — a machine artifact, not a page |
| `_generated/media/retrofit-existing-codebase.json` | `media_manifest` | no catalog row — a machine artifact, not a page |
| `_generated/media/studi0-feedback.json` | `media_manifest` | no catalog row — a machine artifact, not a page |
