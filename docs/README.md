# The s0ma documentation

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

This is the map of record: every document this repository keeps, what it is, who it is written for, and which automatic check keeps it honest. It is built from the same document catalog the documentation build reads, so a document cannot be on this page and unknown to the build, or known to the build and missing here.

A row here is wrong, or a document is missing? The place to fix it is the catalog this page is rendered from — [`docs/s0ma_src/catalog.json`](s0ma_src/catalog.json) — and the next build writes the page again.

There are 176 documents. 139 of them describe s0ma as it is now and are grouped below by what you would be trying to do; the rest are copies that ship inside the wheels, records of the past, and working notes, each behind its own heading further down. 4 more tracked files are listed at the end as what they are: test data rather than documentation.

## Contents

- [Understand s0ma](#understand-s0ma)
- [Build with s0ma](#build-with-s0ma)
- [Use the toolchain](#use-the-toolchain)
- [Reference](#reference)
- [Operate and contribute](#operate-and-contribute)
- [Copies inside the wheels](#copies-inside-the-wheels)
- [The archive](#the-archive)
- [Working notes and plans](#working-notes-and-plans)
- [Files this map does not carry](#files-this-map-does-not-carry)

## How to read the tables

Every table below has the same five columns. **Where** is the file's path from the top of the repository. **For** says who it is written for: `users` are people using or evaluating s0ma, `agents` are coding agents working through the command line or the MCP server, `contributors` are whoever works in this repository, and `owner` is whoever decides what s0ma is.

**Standing** says what the document is. `binding` is a written authority the rest of the documentation defers to. `maintained` is hand-written and kept current. `generated` is written by the build from something else, so an edit to it is lost at the next build. `copy`, `historical`, `moved` and `working note` are the four kinds of document that are real and are not current guidance.

**Kept true by** names the automatic checks that run on that file in this repository, and it is deliberately blunt about how few reach some of them:

- `rebuilt and compared` — the build renders the file again and refuses any difference, so it cannot quietly stop describing what it describes.
- `links checked` — every link and heading it points at has to resolve to something that is really there.
- `version checked` — every version number in it has to be the version this repository ships.
- `listed only` — none of the above. The one automatic check on this document is the one that put it on this page: the build refuses a tracked document the catalog has no row for.

## Understand s0ma

What s0ma is, the words it uses, and how its four packages fit together. Start here if you have not met s0ma before: the front doors say what each part is for, and the two vocabulary files define every term the rest of the documentation leans on.

| Document | Where | For | Standing | Kept true by |
| --- | --- | --- | --- | --- |
| [.s0ma file, explained](learn/s0ma-file.md) | `docs/learn/s0ma-file.md` | agents, users | generated | rebuilt and compared, links checked |
| [adoption ladder, explained](learn/adoption-ladder.md) | `docs/learn/adoption-ladder.md` | agents, users | generated | rebuilt and compared, links checked |
| [Anatomy of a .s0ma file](learn/anatomy-of-a-s0ma-file.md) | `docs/learn/anatomy-of-a-s0ma-file.md` | agents, users | generated | rebuilt and compared, links checked |
| [authored-vs-generated boundary, explained](learn/authored-vs-generated-boundary.md) | `docs/learn/authored-vs-generated-boundary.md` | agents, users | generated | rebuilt and compared, links checked |
| [axon, explained](learn/axon.md) | `docs/learn/axon.md` | agents, users | generated | rebuilt and compared, links checked |
| [canonical IR, explained](learn/canonical-ir.md) | `docs/learn/canonical-ir.md` | agents, users | generated | rebuilt and compared, links checked |
| [cell, explained](learn/cell.md) | `docs/learn/cell.md` | agents, users | generated | rebuilt and compared, links checked |
| [check and build loop, explained](learn/check-and-build-loop.md) | `docs/learn/check-and-build-loop.md` | agents, users | generated | rebuilt and compared, links checked |
| [contract, explained](learn/contract.md) | `docs/learn/contract.md` | agents, users | generated | rebuilt and compared, links checked |
| [doc-guide, explained](learn/doc-guide.md) | `docs/learn/doc-guide.md` | agents, users | generated | rebuilt and compared, links checked |
| [doc-ref, explained](learn/doc-ref.md) | `docs/learn/doc-ref.md` | agents, users | generated | rebuilt and compared, links checked |
| [drift, explained](learn/drift.md) | `docs/learn/drift.md` | agents, users | generated | rebuilt and compared, links checked |
| [drift-gate, explained](learn/drift-gate.md) | `docs/learn/drift-gate.md` | agents, users | generated | rebuilt and compared, links checked |
| [embodiment, explained](learn/embodiment.md) | `docs/learn/embodiment.md` | agents, users | generated | rebuilt and compared, links checked |
| [example, explained](learn/example.md) | `docs/learn/example.md` | agents, users | generated | rebuilt and compared, links checked |
| [executable evidence, explained](learn/executable-evidence.md) | `docs/learn/executable-evidence.md` | agents, users | generated | rebuilt and compared, links checked |
| [feedback, explained](learn/feedback.md) | `docs/learn/feedback.md` | agents, users | generated | rebuilt and compared, links checked |
| [ganglion, explained](learn/ganglion.md) | `docs/learn/ganglion.md` | agents, users | generated | rebuilt and compared, links checked |
| [Glossary](learn/glossary.md) | `docs/learn/glossary.md` | agents, users | generated | rebuilt and compared, links checked |
| [helper, explained](learn/helper.md) | `docs/learn/helper.md` | agents, users | generated | rebuilt and compared, links checked |
| [integration, explained](learn/integration.md) | `docs/learn/integration.md` | agents, users | generated | rebuilt and compared, links checked |
| [intent, explained](learn/intent.md) | `docs/learn/intent.md` | agents, users | generated | rebuilt and compared, links checked |
| [interoception, explained](learn/interoception.md) | `docs/learn/interoception.md` | agents, users | generated | rebuilt and compared, links checked |
| [kind, explained](learn/kind.md) | `docs/learn/kind.md` | agents, users | generated | rebuilt and compared, links checked |
| [Language concepts](s0ma_src/concepts/language.json) | `docs/s0ma_src/concepts/language.json` | agents, contributors | maintained | listed only |
| [layer, explained](learn/layer.md) | `docs/learn/layer.md` | agents, users | generated | rebuilt and compared, links checked |
| [metacognition, explained](learn/metacognition.md) | `docs/learn/metacognition.md` | agents, users | generated | rebuilt and compared, links checked |
| [mirror, explained](learn/mirror.md) | `docs/learn/mirror.md` | agents, users | generated | rebuilt and compared, links checked |
| [module, explained](learn/module.md) | `docs/learn/module.md` | agents, users | generated | rebuilt and compared, links checked |
| [nerve, explained](learn/nerve.md) | `docs/learn/nerve.md` | agents, users | generated | rebuilt and compared, links checked |
| [perimeter, explained](learn/perimeter.md) | `docs/learn/perimeter.md` | agents, users | generated | rebuilt and compared, links checked |
| [Product concepts](s0ma_src/concepts/product.json) | `docs/s0ma_src/concepts/product.json` | agents, contributors | maintained | listed only |
| [proprioception, explained](learn/proprioception.md) | `docs/learn/proprioception.md` | agents, users | generated | rebuilt and compared, links checked |
| [registry snapshot, explained](learn/registry-snapshot.md) | `docs/learn/registry-snapshot.md` | agents, users | generated | rebuilt and compared, links checked |
| [release channel, explained](learn/release-channel.md) | `docs/learn/release-channel.md` | agents, users | generated | rebuilt and compared, links checked |
| [requires:, explained](learn/requires.md) | `docs/learn/requires.md` | agents, users | generated | rebuilt and compared, links checked |
| [s0ma](../README.md) | `README.md` | users | maintained | links checked, version checked |
| [s0ma — Product Requirements Document](../references/s0ma-prd.md) | `references/s0ma-prd.md` | owner | binding | listed only |
| [s0ma, explained](learn/s0ma.md) | `docs/learn/s0ma.md` | agents, users | generated | rebuilt and compared, links checked |
| [s0ma-core](../packages/s0ma-core/README.md) | `packages/s0ma-core/README.md` | users | maintained | links checked, version checked |
| [s0ma-dsl](../packages/s0ma-dsl/README.md) | `packages/s0ma-dsl/README.md` | users | maintained | links checked, version checked |
| [s0ma-mcp](../packages/s0ma-mcp/README.md) | `packages/s0ma-mcp/README.md` | users | maintained | links checked, version checked |
| [s0ma-studi0](../packages/s0ma-studi0/README.md) | `packages/s0ma-studi0/README.md` | users | maintained | links checked, version checked |
| [self-knowledge, explained](learn/self-knowledge.md) | `docs/learn/self-knowledge.md` | agents, users | generated | rebuilt and compared, links checked |
| [self-model, explained](learn/self-model.md) | `docs/learn/self-model.md` | agents, users | generated | rebuilt and compared, links checked |
| [strictness mode, explained](learn/strictness-mode.md) | `docs/learn/strictness-mode.md` | agents, users | generated | rebuilt and compared, links checked |
| [test, explained](learn/test.md) | `docs/learn/test.md` | agents, users | generated | rebuilt and compared, links checked |
| [uses:, explained](learn/uses.md) | `docs/learn/uses.md` | agents, users | generated | rebuilt and compared, links checked |
| [visibility, explained](learn/visibility.md) | `docs/learn/visibility.md` | agents, users | generated | rebuilt and compared, links checked |
| [What s0ma trusts](trust-model.md) | `docs/trust-model.md` | contributors, users | maintained | links checked, version checked |

## Build with s0ma

Getting a project running and writing your first declarations, then checking, building and testing them. The tutorials go from an empty directory to a working module; the guides beside them are the same ground written for a coding agent doing the work.

| Document | Where | For | Standing | Kept true by |
| --- | --- | --- | --- | --- |
| [Building an app with s0ma over MCP — walkthrough](walkthrough.md) | `docs/walkthrough.md` | users | maintained | links checked, version checked |
| [Coding Agent Handbook — s0ma DSL Transpiler](../packages/s0ma-dsl/docs/coding_agent_handbook.md) | `packages/s0ma-dsl/docs/coding_agent_handbook.md` | agents | maintained | links checked |
| [Getting started: prove the self-model is useful](getting-started.md) | `docs/getting-started.md` | users | maintained | links checked, version checked |
| [Migrating from s0ma Python to .s0ma DSL](../packages/s0ma-dsl/docs/migration_guide.md) | `packages/s0ma-dsl/docs/migration_guide.md` | agents | maintained | links checked |
| [s0ma User Guide](../packages/s0ma-core/docs/s0ma_user_guide.md) | `packages/s0ma-core/docs/s0ma_user_guide.md` | agents | maintained | links checked |
| [s0ma — getting started as a free tester](hosting-getting-started.md) | `docs/hosting-getting-started.md` | users | maintained | links checked, version checked |
| [The /s0ma:doctor skill — diagnose s0ma](../integrations/claude/plugin/skills/doctor/SKILL.md) | `integrations/claude/plugin/skills/doctor/SKILL.md` | agents | maintained | version checked |
| [The /s0ma:feedback skill — send feedback about s0ma](../integrations/claude/plugin/skills/feedback/SKILL.md) | `integrations/claude/plugin/skills/feedback/SKILL.md` | agents | maintained | version checked |
| [The /s0ma:new skill — start a new s0ma project](../integrations/claude/plugin/skills/new/SKILL.md) | `integrations/claude/plugin/skills/new/SKILL.md` | agents | maintained | version checked |
| [The /s0ma:retrofit skill — the adoption ladder](../integrations/claude/plugin/skills/retrofit/SKILL.md) | `integrations/claude/plugin/skills/retrofit/SKILL.md` | agents | maintained | version checked |
| [The /s0ma:setup skill — set s0ma up in Claude](../integrations/claude/plugin/skills/setup/SKILL.md) | `integrations/claude/plugin/skills/setup/SKILL.md` | agents | maintained | version checked |
| [The /s0ma:update skill — update or pin s0ma](../integrations/claude/plugin/skills/update/SKILL.md) | `integrations/claude/plugin/skills/update/SKILL.md` | agents | maintained | version checked |
| [The server that describes itself](../packages/s0ma-mcp/src/s0ma_mcp/_built/docs/selfhost_walkthrough.md) | `packages/s0ma-mcp/src/s0ma_mcp/_built/docs/selfhost_walkthrough.md` | agents | generated | rebuilt and compared |
| [Your first module: the anatomy of a .s0ma file](guides/first-module.md) | `docs/guides/first-module.md` | users | maintained | links checked, version checked |
| [Your first project, from install to graph](getting-started/first-project.md) | `docs/getting-started/first-project.md` | users | maintained | links checked, version checked |

## Use the toolchain

The parts you work through day to day: your editor, the server a coding agent talks to, and the viewer that shows you what you built. What each command and served capability does is in Reference below.

| Document | Where | For | Standing | Kept true by |
| --- | --- | --- | --- | --- |
| [Application observations that reach the consumer](guides/application-observations.md) | `docs/guides/application-observations.md` | agents, contributors, users | maintained | links checked |
| [Authoring through the agent's own tool channel](guides/mcp-authoring.md) | `docs/guides/mcp-authoring.md` | agents, users | maintained | links checked, version checked |
| [Editor support for `.s0ma` files](../editors/README.md) | `editors/README.md` | contributors | maintained | version checked |
| [Packaging a s0ma project as a wheel](guides/packaging.md) | `docs/guides/packaging.md` | agents, users | maintained | links checked |
| [Retrofitting an existing codebase](guides/retrofit-existing-codebase.md) | `docs/guides/retrofit-existing-codebase.md` | agents, users | maintained | links checked, version checked |
| [s0ma in Claude](guides/claude-integration.md) | `docs/guides/claude-integration.md` | users | maintained | links checked, version checked |
| [Seeing your system, and telling the s0ma team what you found](guides/studi0-feedback.md) | `docs/guides/studi0-feedback.md` | users | maintained | links checked, version checked |
| [The documentation subsystem](documentation-subsystem.md) | `docs/documentation-subsystem.md` | agents, contributors | maintained | links checked, version checked |
| [What can change, and how you will know](stability.md) | `docs/stability.md` | contributors, users | maintained | links checked, version checked |
| [What the build writes, and what each file is for](guides/what-the-build-writes.md) | `docs/guides/what-the-build-writes.md` | agents, users | maintained | links checked |

## Reference

Look-up material. The language specification is the authority on what a .s0ma file may say; the generated indexes are the complete lists of what s0ma knows and what it can do; the cards are short forms a coding agent reads before it starts.

| Document | Where | For | Standing | Kept true by |
| --- | --- | --- | --- | --- |
| [Changelog](../CHANGELOG.md) | `CHANGELOG.md` | contributors | maintained | listed only |
| [Common s0ma-dsl errors](../packages/s0ma-dsl/docs/_generated/common_errors.md) | `packages/s0ma-dsl/docs/_generated/common_errors.md` | agents | generated | rebuilt and compared |
| [Component index](architecture/component-index.md) | `docs/architecture/component-index.md` | agents, contributors, users | generated | rebuilt and compared, links checked |
| [Concepts index](reference/concepts-index.md) | `docs/reference/concepts-index.md` | agents, users | generated | rebuilt and compared, links checked |
| [docs application self-prompt card](_built/self_prompt_card.md) | `docs/_built/self_prompt_card.md` | agents | generated | rebuilt and compared |
| [Project settings](reference/configuration.md) | `docs/reference/configuration.md` | agents, users | generated | rebuilt and compared, links checked |
| [Reports s0ma can make](reference/diagnostics.md) | `docs/reference/diagnostics.md` | agents, users | generated | rebuilt and compared, links checked |
| [Runtime self-prompting with s0ma](../packages/s0ma-dsl/docs/self_prompting.md) | `packages/s0ma-dsl/docs/self_prompting.md` | agents | maintained | links checked |
| [s0ma DSL Patterns Guide](../packages/s0ma-dsl/docs/references/dsl_patterns_guide.md) | `packages/s0ma-dsl/docs/references/dsl_patterns_guide.md` | agents | maintained | links checked |
| [s0ma DSL — Coding Agent System Prompt](../packages/s0ma-dsl/docs/agent_system_prompt.md) | `packages/s0ma-dsl/docs/agent_system_prompt.md` | agents | maintained | links checked |
| [s0ma DSL — Language Specification & Coding Agent Rulebook](../packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md) | `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md` | agents | binding | links checked |
| [s0ma embodied survival card](../packages/s0ma-core/docs/embodied_survival_card.md) | `packages/s0ma-core/docs/embodied_survival_card.md` | agents | maintained | links checked |
| [s0ma quick reference](reference/quick-reference-readable.md) | `docs/reference/quick-reference-readable.md` | agents, users | generated | rebuilt and compared, links checked |
| [s0ma quick reference, as data](_generated/quick-reference-machine.json) | `docs/_generated/quick-reference-machine.json` | agents | generated | rebuilt and compared |
| [s0ma self-prompt card](../packages/s0ma-mcp/src/s0ma_mcp/_built/self_prompt_card.md) | `packages/s0ma-mcp/src/s0ma_mcp/_built/self_prompt_card.md` | agents | generated | rebuilt and compared |
| [s0ma self-prompt card](../packages/s0ma-studi0/src/s0ma_studi0/_built/self_prompt_card.md) | `packages/s0ma-studi0/src/s0ma_studi0/_built/self_prompt_card.md` | agents | generated | rebuilt and compared |
| [s0ma survival card](../packages/s0ma-dsl/docs/survival_card.md) | `packages/s0ma-dsl/docs/survival_card.md` | agents | maintained | links checked |
| [studi0, the viewer](reference/studi0.md) | `docs/reference/studi0.md` | agents, users | generated | rebuilt and compared, links checked |
| [The distributions s0ma ships](reference/packages.md) | `docs/reference/packages.md` | contributors, users | generated | rebuilt and compared, links checked |
| [The document catalog](s0ma_src/catalog.json) | `docs/s0ma_src/catalog.json` | agents, contributors | maintained | listed only |
| [The documentation application](architecture/docs-application.md) | `docs/architecture/docs-application.md` | agents, contributors | generated | rebuilt and compared, links checked |
| [The documentation application's public surface](reference/documentation-application.md) | `docs/reference/documentation-application.md` | agents, contributors | generated | rebuilt and compared, links checked |
| [The MCP servers](reference/mcp.md) | `docs/reference/mcp.md` | agents, users | generated | rebuilt and compared, links checked |
| [The s0ma authoring MCP surface](../packages/s0ma-mcp/src/s0ma_mcp/_built/docs/mcp_public_surface_reference.md) | `packages/s0ma-mcp/src/s0ma_mcp/_built/docs/mcp_public_surface_reference.md` | agents | generated | rebuilt and compared |
| [The s0ma command line](reference/cli.md) | `docs/reference/cli.md` | agents, users | generated | rebuilt and compared, links checked |
| [The s0ma documentation: the map of record](README.md) | `docs/README.md` | agents, contributors, users | generated | rebuilt and compared, links checked |
| [What s0ma can do](reference/surfaces-index.md) | `docs/reference/surfaces-index.md` | agents, users | generated | rebuilt and compared, links checked |

## Operate and contribute

Running s0ma when something has gone wrong, releasing it, and working on s0ma itself. The decision records and frozen contracts are here because they are what this repository holds itself to, and reading them is how a change gets proposed without re-opening a settled question.

| Document | Where | For | Standing | Kept true by |
| --- | --- | --- | --- | --- |
| [0.15 Design Note: Runtime-Free Emission](design/0.15-runtime-free-emission.md) | `docs/design/0.15-runtime-free-emission.md` | contributors | maintained | links checked |
| [ADR-001: 0.14 Gate Integrity and Value-Loop Boundaries](adr/ADR-001-0.14-gate-integrity-and-value-loop.md) | `docs/adr/ADR-001-0.14-gate-integrity-and-value-loop.md` | contributors | binding | links checked |
| [ADR-001: Self-hosting layout for `packages/s0ma-mcp` (FR-MCP-11)](../packages/s0ma-mcp/docs/adr/ADR-001-selfhost-layout.md) | `packages/s0ma-mcp/docs/adr/ADR-001-selfhost-layout.md` | contributors | binding | links checked |
| [ADR-001: Six-Stage Build Pipeline](../packages/s0ma-dsl/docs/adr/ADR-001-build-pipeline.md) | `packages/s0ma-dsl/docs/adr/ADR-001-build-pipeline.md` | contributors | binding | links checked |
| [ADR-002: Runtime Expansion & Backwards Compatibility](../packages/s0ma-dsl/docs/adr/ADR-002-runtime-expansion.md) | `packages/s0ma-dsl/docs/adr/ADR-002-runtime-expansion.md` | contributors | binding | links checked |
| [ADR-002: Self-context treats authored prose as untrusted data](adr/ADR-002-self-context-authored-data-boundary.md) | `docs/adr/ADR-002-self-context-authored-data-boundary.md` | contributors | binding | links checked |
| [ADR-003: Custom .s0ma.map Source Map Format](../packages/s0ma-dsl/docs/adr/ADR-003-source-map-format.md) | `packages/s0ma-dsl/docs/adr/ADR-003-source-map-format.md` | contributors | binding | links checked |
| [ADR-003: Hardware embodiment foundation — physical-facts vocabulary and runtime surfaces](adr/ADR-003-hardware-embodiment-foundation.md) | `docs/adr/ADR-003-hardware-embodiment-foundation.md` | contributors | binding | links checked |
| [ADR-004: Feedback architecture — placement, consent authority, identity, and the data boundary](adr/ADR-004-feedback-architecture.md) | `docs/adr/ADR-004-feedback-architecture.md` | contributors | binding | links checked |
| [ADR-005: Declarative Project Discovery via `[tool.s0ma]`](../packages/s0ma-dsl/docs/adr/ADR-005-project-discovery.md) | `packages/s0ma-dsl/docs/adr/ADR-005-project-discovery.md` | contributors | binding | links checked |
| [ADR-006: `module <name>` is the Canonical Module Identity](../packages/s0ma-dsl/docs/adr/ADR-006-canonical-module-identity.md) | `packages/s0ma-dsl/docs/adr/ADR-006-canonical-module-identity.md` | contributors | binding | links checked |
| [ADR-007: Single Flat Build-Output Layout](../packages/s0ma-dsl/docs/adr/ADR-007-single-build-layout.md) | `packages/s0ma-dsl/docs/adr/ADR-007-single-build-layout.md` | contributors | binding | links checked |
| [ADR-008: `visibility: TEST` — A Third Declarative Visibility Level](../packages/s0ma-dsl/docs/adr/ADR-008-test-visibility.md) | `packages/s0ma-dsl/docs/adr/ADR-008-test-visibility.md` | contributors | binding | links checked |
| [ADR-009: Canonical Body Storage — Dedent Once, At Parse Time](../packages/s0ma-dsl/docs/adr/ADR-009-canonical-body-storage.md) | `packages/s0ma-dsl/docs/adr/ADR-009-canonical-body-storage.md` | contributors | binding | links checked |
| [ADR-010: Derived Doc Targets — `doc-ref covers: { source: <name> }` Sub-Key Form](../packages/s0ma-dsl/docs/adr/ADR-010-derived-doc-targets.md) | `packages/s0ma-dsl/docs/adr/ADR-010-derived-doc-targets.md` | contributors | binding | links checked |
| [ADR-011: First-Class Declaration Metadata & the 0.8.0 Language-Surface Batch (`metadata:`, `serves_as:`, `deferred_requires:`, qualified `depends_on:`, `covered_by:`)](../packages/s0ma-dsl/docs/adr/ADR-011-declaration-metadata-and-language-surface-batch.md) | `packages/s0ma-dsl/docs/adr/ADR-011-declaration-metadata-and-language-surface-batch.md` | contributors | binding | links checked |
| [ADR-012: The documentation application — placement, build and output boundaries, snapshot semantics](adr/ADR-012-docs-application.md) | `docs/adr/ADR-012-docs-application.md` | contributors | binding | links checked |
| [ADR-013: Derived-source provider registry — generalizing `doc-ref covers: { source: <name> }`](adr/ADR-013-derived-source-registry.md) | `docs/adr/ADR-013-derived-source-registry.md` | contributors | binding | links checked |
| [ADR-014: The `forbids` line — what a nerve or a ganglion must never do](adr/ADR-014-the-forbids-line.md) | `docs/adr/ADR-014-the-forbids-line.md` | contributors | binding | links checked |
| [ADR-015: A build without the runtime packages records what it could not verify](adr/ADR-015-build-without-runtime-packages.md) | `docs/adr/ADR-015-build-without-runtime-packages.md` | contributors | binding | links checked |
| [Architecture Decision Records](../packages/s0ma-dsl/docs/adr/README.md) | `packages/s0ma-dsl/docs/adr/README.md` | contributors | maintained | links checked |
| [Code of conduct](../CODE_OF_CONDUCT.md) | `CODE_OF_CONDUCT.md` | contributors | maintained | version checked |
| [Contributing to s0ma](../CONTRIBUTING.md) | `CONTRIBUTING.md` | contributors | maintained | links checked, version checked |
| [fr3d adoption after the upstream observation fixes](operations/fr3d-adoption-handoff.md) | `docs/operations/fr3d-adoption-handoff.md` | agents, contributors | maintained | links checked |
| [Maintaining the documentation](operations/docs-maintenance.md) | `docs/operations/docs-maintenance.md` | contributors | maintained | links checked, version checked |
| [Offering a change during the beta](../.github/PULL_REQUEST_TEMPLATE.md) | `.github/PULL_REQUEST_TEMPLATE.md` | contributors | maintained | version checked |
| [Releasing s0ma](RELEASING.md) | `docs/RELEASING.md` | owner | maintained | links checked, version checked |
| [Removing s0ma](uninstall.md) | `docs/uninstall.md` | users | maintained | links checked, version checked |
| [Reporting a security problem](../SECURITY.md) | `SECURITY.md` | contributors, users | maintained | version checked |
| [Runtime observation compatibility and regression record](operations/bench-runtime-contracts.md) | `docs/operations/bench-runtime-contracts.md` | agents, contributors | maintained | links checked |
| [s0ma 0.14.0 Schema and Surface Budget](contracts/0.14.0-schema-and-surface-budget.md) | `docs/contracts/0.14.0-schema-and-surface-budget.md` | contributors | binding | links checked |
| [s0ma feedback contract — `s0ma-feedback@1` (feedback-v1)](contracts/feedback-v1.md) | `docs/contracts/feedback-v1.md` | contributors | binding | links checked |
| [s0ma repository agent contract](../AGENTS.md) | `AGENTS.md` | agents | binding | links checked, version checked |
| [s0ma-core — Runtime Specification & Coding Agent Rulebook](../packages/s0ma-core/docs/s0ma-core-spec-v0.20.0.md) | `packages/s0ma-core/docs/s0ma-core-spec-v0.20.0.md` | agents | binding | links checked |
| [Spec Traceability Matrix](../packages/s0ma-dsl/docs/spec_traceability.md) | `packages/s0ma-dsl/docs/spec_traceability.md` | contributors | maintained | links checked |
| [Troubleshooting s0ma](troubleshooting.md) | `docs/troubleshooting.md` | users | maintained | links checked, version checked |
| [When s0ma refuses, and how to get back to green](guides/drift-recovery.md) | `docs/guides/drift-recovery.md` | users | maintained | links checked, version checked |

## Copies inside the wheels

Byte-for-byte copies of documents listed above, packaged so a coding agent that installed s0ma has them without a checkout. Read the original: a copy that drifts from its source fails the build, and an edit made here is lost at the next one.

| Document | Where | For | Standing | Kept true by |
| --- | --- | --- | --- | --- |
| [Changelog](../packages/s0ma-mcp/src/s0ma_mcp/_docs/CHANGELOG.md) | `packages/s0ma-mcp/src/s0ma_mcp/_docs/CHANGELOG.md` | agents | copy | rebuilt and compared |
| [s0ma DSL — Coding Agent System Prompt](../packages/s0ma-mcp/src/s0ma_mcp/_docs/agent_system_prompt.md) | `packages/s0ma-mcp/src/s0ma_mcp/_docs/agent_system_prompt.md` | agents | copy | rebuilt and compared |
| [Common s0ma-dsl errors](../packages/s0ma-mcp/src/s0ma_mcp/_docs/common_errors.md) | `packages/s0ma-mcp/src/s0ma_mcp/_docs/common_errors.md` | agents | copy | rebuilt and compared |
| [s0ma DSL Patterns Guide](../packages/s0ma-mcp/src/s0ma_mcp/_docs/dsl_patterns_guide.md) | `packages/s0ma-mcp/src/s0ma_mcp/_docs/dsl_patterns_guide.md` | agents | copy | rebuilt and compared |
| [Getting started: prove the self-model is useful](../packages/s0ma-mcp/src/s0ma_mcp/_docs/getting-started.md) | `packages/s0ma-mcp/src/s0ma_mcp/_docs/getting-started.md` | agents | copy | rebuilt and compared |
| [s0ma quick reference, as data](../packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-machine.json) | `packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-machine.json` | agents | copy | rebuilt and compared |
| [s0ma quick reference](../packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-readable.md) | `packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-readable.md` | agents | copy | rebuilt and compared |
| [s0ma DSL — Language Specification & Coding Agent Rulebook](../packages/s0ma-mcp/src/s0ma_mcp/_docs/s0ma-dsl-spec-v0.17.0.md) | `packages/s0ma-mcp/src/s0ma_mcp/_docs/s0ma-dsl-spec-v0.17.0.md` | agents | copy | rebuilt and compared |
| [Runtime self-prompting with s0ma](../packages/s0ma-mcp/src/s0ma_mcp/_docs/self_prompting.md) | `packages/s0ma-mcp/src/s0ma_mcp/_docs/self_prompting.md` | agents | copy | rebuilt and compared |
| [s0ma survival card](../packages/s0ma-mcp/src/s0ma_mcp/_docs/survival_card.md) | `packages/s0ma-mcp/src/s0ma_mcp/_docs/survival_card.md` | agents | copy | rebuilt and compared |

## The archive

Records of how s0ma used to work, short stubs left behind where a document moved, and the maintained notes that describe the archive itself. They are kept so a decision can be traced back to what was true when it was taken. Do not read them as current guidance.

| Document | Where | For | Standing | Kept true by |
| --- | --- | --- | --- | --- |
| [Changelog](../packages/s0ma-core/CHANGELOG.md) | `packages/s0ma-core/CHANGELOG.md` | contributors | historical | listed only |
| [s0ma Architecture — superseded](../packages/s0ma-core/docs/architecture.md) | `packages/s0ma-core/docs/architecture.md` | contributors | moved | links checked |
| [s0ma Framework Feedback — Report 3](../packages/s0ma-core/docs/historical/s0ma-framework-feedback-3.1.md) | `packages/s0ma-core/docs/historical/s0ma-framework-feedback-3.1.md` | contributors | historical | listed only |
| [Documentation Subsystem — core's runtime symbols](../packages/s0ma-core/docs/references/documentation_subsystem.md) | `packages/s0ma-core/docs/references/documentation_subsystem.md` | agents, contributors | moved | links checked |
| [Release Checklist — superseded](../packages/s0ma-core/docs/release_checklist.md) | `packages/s0ma-core/docs/release_checklist.md` | owner | moved | links checked |
| [s0ma-core — Runtime Specification & Coding Agent Rulebook (historical: v0.18.1)](../packages/s0ma-core/docs/s0ma-core-spec-v0.18.1.md) | `packages/s0ma-core/docs/s0ma-core-spec-v0.18.1.md` | agents | historical | links checked |
| [s0ma-core — Runtime Specification & Coding Agent Rulebook (historical: v0.19.0)](../packages/s0ma-core/docs/s0ma-core-spec-v0.19.0.md) | `packages/s0ma-core/docs/s0ma-core-spec-v0.19.0.md` | agents | historical | links checked |
| [s0ma-core — Runtime Specification & Coding Agent Rulebook (historical: v0.19.1)](../packages/s0ma-core/docs/s0ma-core-spec-v0.19.1.md) | `packages/s0ma-core/docs/s0ma-core-spec-v0.19.1.md` | agents | historical | links checked |
| [s0ma — Framework Specification & Coding Agent Rulebook (historical: v0.2.0)](../packages/s0ma-core/docs/s0ma-core-spec-v0.2.0.md) | `packages/s0ma-core/docs/s0ma-core-spec-v0.2.0.md` | agents | historical | links checked |
| [Moved: s0ma-framework-feedback-3.1.md](../packages/s0ma-core/docs/s0ma-framework-feedback-3.1.md) | `packages/s0ma-core/docs/s0ma-framework-feedback-3.1.md` | contributors | moved | links checked |
| [Changelog](../packages/s0ma-dsl/CHANGELOG.md) | `packages/s0ma-dsl/CHANGELOG.md` | contributors | historical | listed only |
| [ADR-004: Transpiler as Separate Sister Project](../packages/s0ma-dsl/docs/adr/ADR-004-separate-project.md) | `packages/s0ma-dsl/docs/adr/ADR-004-separate-project.md` | contributors | historical | links checked |
| [s0ma-dsl 0.13.0 — Consumer Walkthrough](../packages/s0ma-dsl/docs/historical/release_walkthrough_5-6.md) | `packages/s0ma-dsl/docs/historical/release_walkthrough_5-6.md` | users | historical | listed only |
| [s0ma-dsl Feedback Findings & Recommended Updates](../packages/s0ma-dsl/docs/historical/s0ma-feedback-findings-1-2.md) | `packages/s0ma-dsl/docs/historical/s0ma-feedback-findings-1-2.md` | contributors | historical | listed only |
| [s0ma Framework Feedback — Report 3](../packages/s0ma-dsl/docs/historical/s0ma-framework-feedback-3.md) | `packages/s0ma-dsl/docs/historical/s0ma-framework-feedback-3.md` | contributors | historical | listed only |
| [s0ma Framework Enhancement: Cross-Project Build and Output Structure](../packages/s0ma-dsl/docs/historical/s0ma_build_fix.md) | `packages/s0ma-dsl/docs/historical/s0ma_build_fix.md` | contributors | historical | listed only |
| [s0ma Framework Feedback](../packages/s0ma-dsl/docs/historical/s0ma_feedback-4.md) | `packages/s0ma-dsl/docs/historical/s0ma_feedback-4.md` | contributors | historical | listed only |
| [s0ma Framework Feedback](../packages/s0ma-dsl/docs/historical/s0ma_feedback.md) | `packages/s0ma-dsl/docs/historical/s0ma_feedback.md` | contributors | historical | listed only |
| [s0ma Framework Enhancement: Transpiled `.py` Drift Detection](../packages/s0ma-dsl/docs/historical/s0ma_py_drift_fix.md) | `packages/s0ma-dsl/docs/historical/s0ma_py_drift_fix.md` | contributors | historical | listed only |
| [Documentation Subsystem — superseded](../packages/s0ma-dsl/docs/references/documentation_subsystem.md) | `packages/s0ma-dsl/docs/references/documentation_subsystem.md` | agents, contributors | moved | links checked |
| [Release Checklist — superseded](../packages/s0ma-dsl/docs/release_checklist.md) | `packages/s0ma-dsl/docs/release_checklist.md` | owner | moved | links checked |
| [Moved: release_walkthrough_5-6.md](../packages/s0ma-dsl/docs/release_walkthrough_5-6.md) | `packages/s0ma-dsl/docs/release_walkthrough_5-6.md` | users | moved | links checked |
| [Superseded: s0ma DSL specification v0.16.0](../packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.16.0.md) | `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.16.0.md` | agents | moved | links checked |
| [Moved: s0ma_feedback-4.md](../packages/s0ma-dsl/docs/s0ma_feedback-4.md) | `packages/s0ma-dsl/docs/s0ma_feedback-4.md` | contributors | moved | links checked |
| [Moved: s0ma_user_guide.md](../packages/s0ma-dsl/docs/s0ma_user_guide.md) | `packages/s0ma-dsl/docs/s0ma_user_guide.md` | agents | moved | links checked |
| [Retired: s0ma_user_guide_condensed.md](../packages/s0ma-dsl/docs/s0ma_user_guide_condensed.md) | `packages/s0ma-dsl/docs/s0ma_user_guide_condensed.md` | agents | moved | links checked |

## Working notes and plans

The plans, review notes and experiment records behind the documents above. They are internal, they are written to be worked through rather than read, and each one stops being true the day its work lands.

| Document | Where | For | Standing | Kept true by |
| --- | --- | --- | --- | --- |
| [Documentation corpus classification — human summary](s0ma_src/doc-classification.md) | `docs/s0ma_src/doc-classification.md` | contributors | working note | links checked |

## Files this map does not carry

Tracked Markdown files that are not documentation. Each one says why, because a file left off a map of record silently and a file left off it for a written reason look the same from outside, and only one of them is reviewable.

| File | Why it is not a document |
| --- | --- |
| [`docs/_built/reference/documentation-application.md`](_built/reference/documentation-application.md) | A build artifact, not a second document: the byte-identical copy of docs/reference/documentation-application.md that a project build writes into the build directory because declared outputs resolve against it (ADR-012 §1 addition 2, from the B1 spike's finding 6). ADR-012 records those copies as committed with the build and never linked, never read and never hand-edited, so cataloging it would put a duplicate into every reader-facing map of the corpus. It stops existing if the docs_output_dir key of ADR-012 §2.4 is ever adopted. |
| [`packages/s0ma-dsl/tests/fixtures/golden/docs/greetings.md`](../packages/s0ma-dsl/tests/fixtures/golden/docs/greetings.md) | Test data, not documentation: a golden file whose exact bytes the documentation emitter's tests assert against. Nobody reads it, and editing it for a reader would break the test that owns it. |
| [`packages/s0ma-dsl/tests/fixtures/golden/docs/walkthrough.md`](../packages/s0ma-dsl/tests/fixtures/golden/docs/walkthrough.md) | Test data, not documentation: a golden file whose exact bytes the documentation emitter's tests assert against. Nobody reads it, and editing it for a reader would break the test that owns it. |
| [`packages/s0ma-dsl/tests/fixtures/legacy_layout_project/README.md`](../packages/s0ma-dsl/tests/fixtures/legacy_layout_project/README.md) | Test data, not documentation: the explanatory file inside a fixture project the layout-migration tests build on. It describes the fixture to whoever maintains the test, and it ships to nobody. |
