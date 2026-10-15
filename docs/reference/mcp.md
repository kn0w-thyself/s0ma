# The MCP servers

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

s0ma serves 56 capabilities over the Model Context Protocol, across 2 servers that do different jobs. Each section below says which wheel ships the one it describes. Every row is read from a running server's own listing when this page is built, so it is what the server really answers rather than what somebody remembered it answering.

The complete list of everything s0ma serves — every channel, not just this one — is in [what s0ma can do](surfaces-index.md), and the same rows in a form a program can read are in [`docs/_generated/inventory-surfaces.json`](../_generated/inventory-surfaces.json).

## Contents

- [The authoring server](#the-authoring-server)
- [The runtime's own server](#the-runtimes-own-server)
- [Documents the authoring server ships](#documents-the-authoring-server-ships)

## How to read the tables

**Name** is what a client calls the capability: a tool's name, a resource's URI, a prompt's name. **Id** is what this documentation addresses it by, and it is the stable one — the name is the product's, the id is the model's, and a link to a capability uses the id.

**Effects** are read from the capability itself wherever it declares them: `none`, `read`, `write`, `network`, `subprocess`, `credential`, `approval`. Where nothing declares them, the row says `not declared` rather than guessing — that is an answer about the capability's own description, not about what it does.

**Asks you first** is `yes` where the capability declares the `approval` effect, which means it stops and waits for your decision before the irreversible part happens. `not declared` means the same thing the effects column means by it: nobody has written down what calling it touches.

## The authoring server

What a coding agent talks to while it writes s0ma. It scaffolds modules, runs the check-and-build loop, reads the language guides, and reports what a project currently looks like. This is the server the getting-started journey configures, and every capability below is served by the s0ma-mcp wheel.

36 of the 56 capabilities, shipped in `s0ma-mcp`. Every one of them reaches a registered component, so a reader can follow any row back to the code that answers it.

### Tools

15 of this server's 36.

| Name | Id | What it does | Effects | Asks you first |
| --- | --- | --- | --- | --- |
| `adopt_file` | `mcp:tool/adopt_file` | When migrating old Python, record it as interim roster debt. | write | no |
| `build_project` | `mcp:tool/build_project` | After check is clean, build the complete configured project. | write | no |
| `check` | `mcp:tool/check` | After editing intent or code, validate before building. | read | no |
| `describe_server` | `mcp:tool/describe_server` | When you do not know which s0ma surface fits, ask the server. | read | no |
| `init_project` | `mcp:tool/init_project` | When project_status says false, add the canonical project table. | write | no |
| `inspect_module` | `mcp:tool/inspect_module` | Before grepping for where X is handled, inspect the self-model. | read | no |
| `learn_s0ma` | `mcp:tool/learn_s0ma` | Ask s0ma one question about s0ma, and get a short answer back. | read | no |
| `migrate_ext` | `mcp:tool/migrate_ext` | When legacy extension names remain, preview and apply their migration. | write | no |
| `prepare_feedback` | `mcp:tool/prepare_feedback` | Write up feedback about s0ma for the user to review — read-only. | read | no |
| `project_status` | `mcp:tool/project_status` | When landing in a tree or diagnosing it, orient in one call. | read | no |
| `run_example` | `mcp:tool/run_example` | When documentation claims behavior, run its executable example. | subprocess, write | no |
| `scaffold_module` | `mcp:tool/scaffold_module` | When starting new behavior, create a valid intent-first component. | write | no |
| `submit_feedback` | `mcp:tool/submit_feedback` | Ask the user to approve this exact feedback data, then send it. | approval, network, write | yes |
| `transpile` | `mcp:tool/transpile` | When iterating on one source, emit its Python, IR, and source map. | write | no |
| `verify_host` | `mcp:tool/verify_host` | After static checks pass, prove imports in the app's real Python. | approval, subprocess, write | yes |

### Resources

16 of this server's 36.

| Name | Id | What it does | Effects | Asks you first |
| --- | --- | --- | --- | --- |
| `s0ma://docs/concepts` | `mcp:resource/s0ma://docs/concepts` | Every s0ma concept, one line each. | read | no |
| `s0ma://docs/index` | `mcp:resource/s0ma://docs/index` | What s0ma can be asked about, and how to ask. | read | no |
| `s0ma://docs/journeys` | `mcp:resource/s0ma://docs/journeys` | Every worked path through s0ma, step by step. | read | no |
| `s0ma://guide/errors` | `mcp:resource/s0ma://guide/errors` | The s0ma diagnostic error catalog (FR-MCP-10). | read | no |
| `s0ma://guide/getting-started` | `mcp:resource/s0ma://guide/getting-started` | What s0ma is, who it fits, and how to prove its value. | read | no |
| `s0ma://guide/patterns` | `mcp:resource/s0ma://guide/patterns` | The s0ma DSL patterns guide — idioms for real applications. | read | no |
| `s0ma://guide/quick-reference` | `mcp:resource/s0ma://guide/quick-reference` | The s0ma quick reference: every declaration, line by line. | read | no |
| `s0ma://guide/quick-reference.json` | `mcp:resource/s0ma://guide/quick-reference.json` | The s0ma quick reference as data (JSON, schema s0ma-quick-reference@1). | read | no |
| `s0ma://guide/self-prompting` | `mcp:resource/s0ma://guide/self-prompting` | Runtime self-prompting and verified self_inspect wiring. | read | no |
| `s0ma://guide/survival-card` | `mcp:resource/s0ma://guide/survival-card` | The s0ma survival card (under 4 KB) — read this FIRST, hold it in context. | read | no |
| `s0ma://guide/system-prompt` | `mcp:resource/s0ma://guide/system-prompt` | The s0ma DSL coding-agent system prompt. | read | no |
| `s0ma://meta/changelog` | `mcp:resource/s0ma://meta/changelog` | The s0ma platform changelog — what's new, per version (FR-MCP-10). | read | no |
| `s0ma://meta/version` | `mcp:resource/s0ma://meta/version` | The installed s0ma toolchain versions as JSON (FR-MCP-10). | read | no |
| `s0ma://project/runbook` | `mcp:resource/s0ma://project/runbook` | The project's operational runbook (O1) as markdown. | read | no |
| `s0ma://self/model` | `mcp:resource/s0ma://self/model` | The authoring server's live self-model (FR-MCP-7) as JSON. | read | no |
| `s0ma://spec/current` | `mcp:resource/s0ma://spec/current` | The current s0ma DSL language specification (normative). | read | no |

### Prompts

5 of this server's 36.

| Name | Id | What it does | Effects | Asks you first |
| --- | --- | --- | --- | --- |
| `author_module` | `mcp:prompt/author_module` | Author a new s0ma module end to end. | none | no |
| `diagnose_fault` | `mcp:prompt/diagnose_fault` | Diagnose an observed runtime fault from self-knowledge first. | none | no |
| `feedback` | `mcp:prompt/feedback` | Send the user's feedback about s0ma to the s0ma team. | none | no |
| `fix_check_failures` | `mcp:prompt/fix_check_failures` | Diagnose and fix s0ma check failures until the project is clean. | none | no |
| `migrate_project` | `mcp:prompt/migrate_project` | Migrate a pre-consolidation project to the current s0ma surface. | none | no |

## The runtime's own server

What an application built with s0ma serves about itself. It answers questions from the running self-model — what the system contains, what depends on what, what would be affected by a change — and it ships in the runtime wheel, so an application can offer it without the authoring toolchain being installed.

20 of the 56 capabilities, shipped in `s0ma-core`. None of them reaches a registered component: the protocol's public listing gives a capability its name, its description and its schema, and not the callable behind it. Each carries a written reason saying so.

### Tools

12 of this server's 20.

| Name | Id | What it does | Effects | Asks you first |
| --- | --- | --- | --- | --- |
| `check_health` | `mcp:tool/check_health` | Get the system's current health status and anomalies. | not declared | not declared |
| `describe_system` | `mcp:tool/describe_system` | Get a natural language overview of the system architecture. | not declared | not declared |
| `explain_dependency` | `mcp:tool/explain_dependency` | Explain why component 'source' depends on component 'target'. | not declared | not declared |
| `find_component` | `mcp:tool/find_component` | Get detailed information about a specific component. | not declared | not declared |
| `get_compliance_checklist` | `mcp:tool/get_compliance_checklist` | Get the quick compliance checklist for creating/modifying components. | not declared | not declared |
| `get_component_example` | `mcp:tool/get_component_example` | Get a real component from the registry as a copyable template. | not declared | not declared |
| `get_examples_for` | `mcp:tool/get_examples_for` | List canonical examples demonstrating a component. | not declared | not declared |
| `get_extension_points` | `mcp:tool/get_extension_points` | Find where new components can be added safely. | not declared | not declared |
| `get_impact` | `mcp:tool/get_impact` | Analyze what would be affected if a component changes. | not declared | not declared |
| `learn_about_s0ma` | `mcp:tool/learn_about_s0ma` | Learn how to use the s0ma framework. | not declared | not declared |
| `query_system` | `mcp:tool/query_system` | Ask a natural language question about the system. | not declared | not declared |
| `suggest_fix` | `mcp:tool/suggest_fix` | Given an anomaly description, suggest how to fix it. | not declared | not declared |

### Resources

8 of this server's 20.

| Name | Id | What it does | Effects | Asks you first |
| --- | --- | --- | --- | --- |
| `s0ma://docs/architecture` | `mcp:resource/s0ma://docs/architecture` | How s0ma's own architecture is documented, and where to read it. | not declared | not declared |
| `s0ma://docs/compliance-rules` | `mcp:resource/s0ma://docs/compliance-rules` | Compliance rules (Appendix C) — every rule for s0ma-compliant code. | not declared | not declared |
| `s0ma://docs/registered-docs` | `mcp:resource/s0ma://docs/registered-docs` | Every registered doc-ref, doc-guide, and example. | not declared | not declared |
| `s0ma://docs/user-guide` | `mcp:resource/s0ma://docs/user-guide` | The complete s0ma user guide — how to build applications with s0ma. | not declared | not declared |
| `s0ma://model/component-template` | `mcp:resource/s0ma://model/component-template` | A real component from the registry formatted as a copyable template. | not declared | not declared |
| `s0ma://model/docs-for/{component}` | `mcp:resource/s0ma://model/docs-for/{component}` | Doc-refs and doc-guides covering ``component``. | not declared | not declared |
| `s0ma://model/examples-for/{component}` | `mcp:resource/s0ma://model/examples-for/{component}` | Canonical examples demonstrating ``component``. | not declared | not declared |
| `s0ma://model/registry-summary` | `mcp:resource/s0ma://model/registry-summary` | Live system overview from the self-model. | not declared | not declared |

## Documents the authoring server ships

The authoring server answers 10 of its resources out of documents packaged inside its wheel, so an agent that installed s0ma has them without a checkout. Read the original: the copy is compared to it byte for byte at every build, and an edit made to the copy is lost at the next one.

| Served as | The copy that ships | The original |
| --- | --- | --- |
| `mcp:resource/s0ma://guide/errors` | [`packages/s0ma-mcp/src/s0ma_mcp/_docs/common_errors.md`](../../packages/s0ma-mcp/src/s0ma_mcp/_docs/common_errors.md) | [`packages/s0ma-dsl/docs/_generated/common_errors.md`](../../packages/s0ma-dsl/docs/_generated/common_errors.md) |
| `mcp:resource/s0ma://guide/getting-started` | [`packages/s0ma-mcp/src/s0ma_mcp/_docs/getting-started.md`](../../packages/s0ma-mcp/src/s0ma_mcp/_docs/getting-started.md) | [`docs/getting-started.md`](../getting-started.md) |
| `mcp:resource/s0ma://guide/patterns` | [`packages/s0ma-mcp/src/s0ma_mcp/_docs/dsl_patterns_guide.md`](../../packages/s0ma-mcp/src/s0ma_mcp/_docs/dsl_patterns_guide.md) | [`packages/s0ma-dsl/docs/references/dsl_patterns_guide.md`](../../packages/s0ma-dsl/docs/references/dsl_patterns_guide.md) |
| `mcp:resource/s0ma://guide/quick-reference` | [`packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-readable.md`](../../packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-readable.md) | [`docs/reference/quick-reference-readable.md`](quick-reference-readable.md) |
| `mcp:resource/s0ma://guide/quick-reference.json` | [`packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-machine.json`](../../packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-machine.json) | [`docs/_generated/quick-reference-machine.json`](../_generated/quick-reference-machine.json) |
| `mcp:resource/s0ma://guide/self-prompting` | [`packages/s0ma-mcp/src/s0ma_mcp/_docs/self_prompting.md`](../../packages/s0ma-mcp/src/s0ma_mcp/_docs/self_prompting.md) | [`packages/s0ma-dsl/docs/self_prompting.md`](../../packages/s0ma-dsl/docs/self_prompting.md) |
| `mcp:resource/s0ma://guide/survival-card` | [`packages/s0ma-mcp/src/s0ma_mcp/_docs/survival_card.md`](../../packages/s0ma-mcp/src/s0ma_mcp/_docs/survival_card.md) | [`packages/s0ma-dsl/docs/survival_card.md`](../../packages/s0ma-dsl/docs/survival_card.md) |
| `mcp:resource/s0ma://guide/system-prompt` | [`packages/s0ma-mcp/src/s0ma_mcp/_docs/agent_system_prompt.md`](../../packages/s0ma-mcp/src/s0ma_mcp/_docs/agent_system_prompt.md) | [`packages/s0ma-dsl/docs/agent_system_prompt.md`](../../packages/s0ma-dsl/docs/agent_system_prompt.md) |
| `mcp:resource/s0ma://meta/changelog` | [`packages/s0ma-mcp/src/s0ma_mcp/_docs/CHANGELOG.md`](../../packages/s0ma-mcp/src/s0ma_mcp/_docs/CHANGELOG.md) | [`CHANGELOG.md`](../../CHANGELOG.md) |
| `mcp:resource/s0ma://spec/current` | [`packages/s0ma-mcp/src/s0ma_mcp/_docs/s0ma-dsl-spec-v0.17.0.md`](../../packages/s0ma-mcp/src/s0ma_mcp/_docs/s0ma-dsl-spec-v0.17.0.md) | [`packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`](../../packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md) |
