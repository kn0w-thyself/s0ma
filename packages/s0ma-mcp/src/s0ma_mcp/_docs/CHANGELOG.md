# Changelog

All notable changes to the s0ma monorepo are documented in this file. It follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

From 0.5.0 every package in this repo shares one lockstep version, one git tag (`v<version>`), and this single changelog (PRD INV-4). Pre-monorepo history lives in each package's own changelog, preserved verbatim:

- [`packages/s0ma-core/CHANGELOG.md`](packages/s0ma-core/CHANGELOG.md) — releases ≤ 0.4.0
- [`packages/s0ma-dsl/CHANGELOG.md`](packages/s0ma-dsl/CHANGELOG.md) — releases ≤ 0.16.0

Historical entries describe artifacts as they were named at the time.

## [Unreleased]

### Added

- **Per-operation contracts reach every describe surface.** A SERVICE nerve's
  `provides:` entries carry per-operation `expects`, `guarantees` and
  `returns`. They reached the IR and the registration metadata and stopped
  there: nothing read `metadata["provides_contracts"]`, so a host asking what
  `pip_install` expects got the nerve's contract and never the operation's.
  `ComponentSpec` gains two typed views over the stored metadata copy, which
  stays as it was: `provides`, the operation names, and `provides_contracts`,
  a tuple of `OperationContract` records. `format_component_detail` prints an
  `Operations (provides):` section with each operation's expects, guarantees
  and returns under it, so `describe_component` and the introspection
  server's `find_component` answer the question. The self-context companion
  carries `provides_contracts` beside `provides`, and the runtime adapter's
  `component <name>` answer returns it.
- **An operation name resolves to the component that provides it.** An agent
  mostly knows a system by the operations it calls, the tool names, and every
  describe surface accepted only component names: `component fetch_url`
  returned nothing and `impact fetch_url` said not found. The registry gains
  `find_providers(operation)` and `resolve_component(name)`, which reads a
  name as a component first and as an operation second; one provider resolves
  to that component and several resolve to nothing with every provider named
  as a candidate. `describe_component`, `get_impact_analysis`,
  `explain_dependency_chain`, the query engine, the introspection server's
  `find_component`, `get_impact` and `explain_dependency`, and the runtime
  adapter all route through it, and each answer opens by saying so:
  "fetch_url is an operation of browser::WebBrowser". `ComponentSpec.display_name`
  is that `module::name` spelling, the one the build artifacts use; the
  runtime adapter puts the same fact under a `resolved` key.
- **A constant carries its value.** A CONSTANT cell whose body assigns a simple
  literal (an int, a finite float, a str, a bool, None, or a flat tuple or
  list of those, at most 1,024 bytes as JSON) now carries it on every surface:
  the canonical IR at `components[].fields.value`, the emitted registration as
  `register_constant(value=...)`, the registry as `metadata["value"]`, the
  snapshot, and the self-context companion. Tuples are carried as JSON arrays
  so the surfaces agree. The key's presence is the signal: `None` is a value,
  and an expression, an embedded `@file` body or an oversized literal is no
  value at all. `describe_component` and the summaries print `Value: 60`.
- **A constant has readers.** The transpiler derives `READS` edges from nerve
  and ganglion bodies to the constants they refer to, in their own module and,
  when `s0ma build` has the whole project parsed, imported through `uses`. The
  derived edge's origin is `constant_reference`. An authored edge between the
  same source and target, with any relation, is the architectural statement
  and wins: no derived edge is emitted for that pair, so a project that
  already authors `READS` to its constants sees no `DUPLICATE_AXON`.
  `s0ma graph` shows the new edges with the other derived ones.
- **The self-context carries the edge graph.** Each component record gains an
  `edges` list, every authored and derived outgoing edge with its `target`,
  `relation`, whether it was `authored`, its IR `origin` and, for an authored
  edge, what it `carries`. `dependencies` keeps carrying the authored targets
  alone. The runtime adapter's `dependencies <name>` answer returns `edges`
  beside `dependencies`, so a reader sees the constants a nerve reads and the
  types it uses next to the dependencies it declared.
- **The runtime self-model answers "what depends on X".** The runtime
  `SelfInspectAdapter` gains `dependents <name>`, the components that depend
  on the named one directly, each with its relation and whether the edge was
  authored or derived, and `impact <name>`, the transitive walk with direct
  and transitive dependents, affected layers, count and depth, the shape the
  dev-time `ImpactReport` has. Both read the companion's authored and derived
  edges, so a constant's readers are its dependents; a generation-1 companion
  is walked over its authored targets. A target an author spelled with the
  declaring module is landed by its unique bare name, and the answer keeps
  the spelling under `declared_as`. The tool description, the error wording,
  the self-prompt card's header line and the self-prompting guide name every
  command.
- **Two `self_inspect` commands reach what `describe` no longer carries.**
  `components <layer or module>` answers the component names in that layer
  or module, grouped by module (an id is `<module>::<name>`), and `source_ir`
  answers the canonical IR records the companion was derived from, path and
  hash, each verified when the companion loaded. An unknown scope answers
  `SCOPE_NOT_FOUND`; `component <name>` and `dependencies <name>` are
  unchanged, except that `component <name>` now says whether the component
  is `observed` live when a registry was supplied, beside the record and
  never inside it. The adapter's `tool_spec` names all seven commands so no
  answer has to repeat them.

### Changed

- **Describe surfaces list the application's components by default.** s0ma
  registers its own framework components beside an application's, flagged
  `is_framework`, and the describe surfaces counted and listed them as the
  application's: a host built its ambient self-description from "516
  components across 5 layers" and named eight of the DSL's own helpers as its
  capabilities, while the build's `self_context.json` said 441 in 103 modules.
  `RegistrySnapshot.visible_components(include_framework=None)` is now the one
  rule: the application's components alone whenever any are registered, the
  framework's only when they are all there is (the framework describing
  itself), `True` for everything, `False` for the application even when that
  is nothing. `RegistrySnapshot.describe`, `SelfModelInterface.describe_system`,
  `get_architecture_context` and the debugging context list and count through
  it and say what they omit; the summary's total, framework and application
  counts stay. The runtime overlay's `registered_component_count` and
  `registered_components` follow the same rule, with a new
  `framework_components_included` flag saying which view it is, so the live
  count agrees with the companion; `self_context()` and
  `self_inspect_adapter()` take `include_framework`, and the adapter's
  `describe` adds `module_count`.
- **The self-context companion is at generation 2.** `self_context.json` keeps
  its schema name, `s0ma-self-context@1`, and every required member;
  `generation_version` moves from `"1"` to `"2"` because the record now
  carries `provides_contracts`, `value` and `edges` where they exist. The
  runtime reads generation 1 and 2 alike, so an older build stays loadable
  with the new fields absent. The three committed builds are regenerated.
- **`value` is a reserved registration-metadata key.** `register_constant`
  stores a constant's literal under it, so an authored `metadata: value:`
  entry on any declaration is now `METADATA_RESERVED_KEY`, like the other
  keys the emitter owns. `RESERVED_COMPONENT_METADATA_KEYS` has 28 members.
- **The bootstrap self-model registers two more framework records.**
  `OperationContract` and `ComponentResolution` join `s0ma.models` and the
  bootstrap registration, so the expected framework component count moves
  from 61 to 63; `ComponentRegistry` declares `ComponentResolution`, which it
  now imports.
- **The self-context companions describe the application, not its tests.**
  `self_context.json` and `self_prompt_card.md` are built from the manifest
  entries with the `source` role; the test modules `s0ma test` builds into
  the same manifest are left out, as `bootstrap_imports` leaves them out of
  the running application. The companion records the roles it was built from
  in `provenance.roles` (additive under `s0ma-self-context@1`; older
  companions still load, and a malformed value is refused), and a build that
  wants its tests described calls
  `emit_self_context_artifacts(..., roles=("source", "test"))` and writes
  the references it returns into the manifest (the self-prompting guide
  shows the three lines). On fr3d's build the companion went from 1,021,910
  bytes and 1,857 components, 1,416 of them from test modules, to 381,824
  bytes and 441; the card's inventory went from 17 lines and 1,780 omitted
  to 20 lines and 354 omitted, inside the unchanged 2,600-byte, 240-word
  budget. The card's header line now names the `self_inspect` tool and
  every command it answers.
- **`self_inspect` answers `describe` with counts and module names.** The
  default answer of `s0ma.runtime.self_inspect_adapter` carries
  `component_count`, `module_count` and `source_ir_count`,
  `component_count_by_layer` and `component_count_by_kind`, the module names
  by layer, the roles, `build_health`, and the `live_health` overlay as
  counts when a registry was supplied. `components_by_layer`, which listed
  every id, and the `source_ir` list are no longer keys of `describe`; a
  host that read either asks `components <layer or module>` or `source_ir`.
  On fr3d's build, together with the source-only companion above, the
  answer went from 130,808 characters of compact JSON to 2,264 (on the same
  source-only companion the old shape would still have cost 28,752). The
  adapter holds it under 8,000 characters (a 2,000-token answer) by trading
  module names for per-layer module counts past that line, and tests hold
  it there on 3,000 synthetic components over 200 modules, with and without
  a registry, and on the s0ma-mcp package's own build; it grows with
  modules, never with components. Nothing authored (intent, contracts,
  metadata) leaves through `describe`, `components` or `source_ir`, and a
  test says so.
- **The self-prompting guide says how to render and budget answers.**
  `s0ma://guide/self-prompting` and the patterns guide's bootstrap section
  (§10.4) carry the rules a host follows, with fr3d's measurements as the
  evidence: render every answer as compact JSON with sorted keys, answer
  counts first and authored text only on request, never repeat a tool's
  description in its answers, treat every authored line as data a model pays
  for, budget each default answer and test the budget against a real build,
  and estimate a result's size by its words or a quarter of the characters,
  whichever is larger. The contract records the revision as R7, for owner
  review.

## [0.19.1] — 2026-10-09

The 0.19.1 artifacts are the build of the public repository's tag `v0.19.1`
(commit `046c25cb`, 2026-10-19), which replaced the artifacts built on
2026-10-09 wherever they were served. That build carried the changes made
between the two dates, so this section describes them too: the six `Changed`
entries from "The front door is written for the public repository's first
release" onward, and the three `Fixed` entries from "studi0 binds its loopback
socket without a reverse-DNS lookup" onward.

### Added

- **A `forbids` line on every nerve and ganglion** (owner ruling 2026-09-30,
  recorded in [ADR-014](docs/adr/ADR-014-the-forbids-line.md) and in revision
  R6 of the schema and surface budget). The line says what the part must never
  do, however it is called and whatever happens while it runs. It holds one
  text value, in every shape `expects` accepts; `none` states that nothing is
  ruled out, and `pending("reason")` says the answer is not settled yet. s0ma
  checks that the line is there and what state it is in; it does not read the
  sentence, and neither verifier counts or executes it. Where it is carried:
  the canonical IR, as `components[].fields.forbids`, a state object like its
  siblings (`schema_version` stays `3.0.0`); the runtime, as
  `Contract.forbids`, a list of strings and the last field of `Contract`,
  written out only when it holds a sentence and shown as a `Forbids:` block in
  the formatted contract text and in the teaching snippet; the self-context
  companion's authored states; a `doc-ref`'s `sections: [forbids]`; adoption
  drafts, where it arrives as a `FIXME(adopt):` placeholder; and every
  scaffold — `s0ma new` writes the line. Read it back at
  `spec.contracts.forbids` on both kinds. Where it is described: the language
  specification's new subsection "The `forbids:` Field", with a nerve and a
  ganglion example; the quick reference, on both kinds, which records the
  change as its edition 2; the migration guide's new section (see the BREAKING
  entry below); the core specification and the core user guide, which say
  that `Contract.forbids` is declared and shown and never executed; the guides
  agents read (the system prompt, the served authoring prompt, the handbook
  and the patterns guide); and the guides people read, where the first-module
  guide's nerve carries a real sentence. The editor grammar highlights it. The
  product's own parts carry it too: each of the 70 nerves of the authoring
  server, studi0 and the documentation application has the line — 41 with a
  sentence that restates a commitment the part already makes in writing, 29
  with `none`.
- **Every authored line stands on its own, and a stage of the repository's
  gate, `authored-lines`, keeps it so.** The lines a `.s0ma` file writes in
  words — `intent`, `guarantees`, `invariants`, `schema` and `forbids` — are
  read by people and agents who have only the code in front of them. Each now
  says, in the present tense, what is true of the part, and names no plan,
  milestone, wave, review item, date, person or ruling behind it. It may
  refer only to what ships with the code and is held by a gate: a requirement
  or an invariant of the product requirements document, an invariant of
  core's specification, an architecture decision record by its number, a
  revision of the schema and surface contract, or a section of the language
  specification. The stage reads every authored line in five trees (the
  authoring server, studi0, the documentation application, the language
  package's document generators and its test fixtures). It refuses a
  milestone or decision id, a run or a round named by its id, a plan or a
  review by its name, a plan's clause written like a section number, a date,
  and a ruling or a person; it looks each allowed reference up in the
  document that defines it, and fails on one that names nothing. A refusal
  prints the file and line, the field and the matched form, and three
  answers: reword the line to stand alone; replace the reference with an
  allowed form that resolves; or, when the matched word is the product's own
  term rather than the planning record's (the dry-run plan a migration shows
  before it applies, the review step of the feedback journey), record it in
  `ALLOWLIST` at the top of `scripts/check_authored_lines.py` with a
  one-line justification. Each allowlist entry is pinned to the line it
  covers, and the stage warns when that line no longer matches; four are
  recorded. Where it is carried: `scripts/check.py`, as its sixteenth stage,
  described in `CONTRIBUTING.md` and listed in the table of stages in
  `docs/operations/docs-maintenance.md`. It checks s0ma's own repository:
  `s0ma check` asks nothing new of a user's project. Where it is described:
  where agents and people learn to write such a line — the quick reference,
  in its explanation of each one; the agent system prompt; the patterns
  guide's closing section, "Authored lines stand on their own"; and the
  retrofit guide's Author step. The product's own 63 lines that leaned were
  rewritten once — 21 in the authoring server, 2 in studi0, and 40 in the
  language package's test fixtures and the source of one of its generated
  documents — and only their words changed: no part does anything different,
  and the authoring server's tools, resources and prompts keep their names,
  descriptions and schemas.
- **The `authored-lines` stage now also reads the authored lines written in
  Python, and the spike fixtures.** The runtime and the language package
  register their own parts in Python rather than in a `.s0ma` file, and the
  `intent`, `guarantees`, `invariants`, `schema` and `forbids` strings they
  pass to `@component`, `ComponentSpec` and `Contract` are authored lines as
  much as a `.s0ma` file's are. The stage reads every such value in the
  tracked `.py` files under each package's `src/`, committed build output
  excepted, with Python's own parser and without importing the code: a
  string, an implicit concatenation of strings, or a list of strings is read
  as one line; a value made somewhere else — a name, a call, an attribute,
  an f-string — is not read, and the summary counts it. The same two tables
  and the same allowlist decide; a refusal prints the line the keyword
  starts on, the field and the registration's name; and a section that a
  line in core's sources cites resolves against the core specification. The
  stage also reads the `.s0ma` fixtures under `scripts/spikes`, its sixth
  tree. A second anti-vacuity floor, for the lines written in Python, sits
  beside the first, so a reader that lost either package cannot report
  PASS. The allowlist gains one product term from a Python line — "audit",
  the registry's audit log that a lifecycle event is recorded for — and now
  holds five entries. The five Python-authored lines that leaned were rewritten
  once — one in core's bootstrap registrations and four in the language
  package's syntax-tree nodes — each losing the planning record's id and the
  release number that rode with it. Four citations in the language package
  were put right: two named a section the product requirements document
  does not have and resolved to nothing, one named such a section and
  passed only because the language specification carries the same number,
  and one gave an architecture decision record's section number, which the
  stage read against the language specification. Two were dropped, one line
  now cites the section of the language specification it means, and the
  decision record is cited by its number alone. Only words changed: no part
  does anything different, and the authoring server's tools, resources and
  prompts keep their names, descriptions and schemas. Where it is described:
  the stage's paragraph in `CONTRIBUTING.md` and its row in the table of
  stages in `docs/operations/docs-maintenance.md`.

### Changed

- **BREAKING — a nerve or a ganglion without a `forbids` line is refused, in
  every mode** (owner ruling 2026-09-30). A project that built before and has
  not written the line is stopped at the parser with
  `SEMANTIC_REQUIRED_STATE_OMITTED` naming `forbids`, exactly as an omitted
  `expects` is; a misspelt `forbid:` gets the existing spelling hint as well.
  The one command: `s0ma migrate grammar --apply` writes `forbids: none` into
  each nerve and ganglion that lacks the line, directly above its `---`;
  without `--apply` it shows what it would change, and a second run changes
  nothing. The `none` it writes is an answer given on the author's behalf,
  matching what those declarations stated until then; replace it with a
  sentence wherever a part has something it must never do — one that starts
  with "Never" and that the part's own body makes true. `s0ma check` may name
  only the first part without the line, while the migration finds them all;
  the migration guide's section "Migrating to the required `forbids` line"
  walks through it.
- **Every documentation content hash moves once, and an application built from
  a real `forbids` sentence needs the matching `s0ma-core`.** `Contract`
  gained a field, and the canonical form walks every field of a dataclass,
  whether or not the line holds a sentence; rendered documents that pin a
  content hash are re-stamped by this release's build. Nothing else about
  hashing changed. For each real sentence, an application's emitted module
  passes `forbids=[…]` to `Contract`, which an older core does not accept, so
  such an application needs the `s0ma-core` of this release or later; `none`
  and `pending` emit nothing, so on this line's account they ask nothing new
  of the installed core. The authoring server and studi0 now carry real
  sentences, so they need it too.
- **The front door is written for the public repository's first release.**
  The root README now opens on what s0ma is — a substrate in which the code
  produces its own live, queryable model — and says who it is for: anyone
  building agents, harnesses, AI-enabled applications or autonomous software
  and hardware systems, with or without an LLM in the loop. It says how a part
  that is not Python is declared from the Python side as a reference, and that
  more languages are on the roadmap. Its install section describes the one
  route that release offers — clone `kn0w-thyself/s0ma` and build from it,
  with PyPI publication pending — and no longer describes accounts, the keyed
  installer, or the Claude plugin and extension. Feedback goes to the
  repository's issues and discussions. The getting-started guide the README
  embeds, which `s0ma://guide/getting-started` serves, says the same, so its
  catalog row no longer claims `s0ma feedback`, and the public-export rules
  expect fewer old repository addresses to rewrite. The guide's host-probe
  step now says what a fresh project needs before `s0ma verify-host` can
  pass — an environment of its own with `s0ma-core` and `s0ma-dsl` installed
  and declared — because walking the guide from a cold install showed that
  step refusing first.
- **The pages the README no longer links say the same thing it does.** The
  tester page, the Claude page, the four package READMEs, the stability
  statement, the security policy and the contributor guide all described a
  route the public repository's first release does not offer — an account, a
  license key, the keyed installer, or the Claude plugin and extension — or
  pointed a reader at one. The tester page and the Claude page keep their
  accounts of those routes and now say, at the top and in their closing
  pointers, that the public repository offers one way in: the source route,
  stated once in the getting-started guide. The package READMEs' Install
  sections state that route alone. The stability statement says beta means
  pre-1.0 and nothing else, and holds a project to a version through its own
  lock file or checkout rather than through an account or Claude. The
  security policy drops the account service from its scope and from the four
  facts it summarises, which now include that nothing checks a licence or an
  entitlement in order to run. The contributor guide clones the public
  repository and sends feedback about s0ma to the repository's discussions
  and bug reports, and the public-export rules expect one fewer old
  repository address to rewrite.
- **The remaining route pages say the same.** The uninstall guide, the MCP
  walkthrough, the core user guide, the first-project journey, the
  troubleshooting page, the trust model and the two issue templates all
  listed the tester route, the Claude route or `s0ma feedback` as ways in,
  or pointed a reader at them. Each now states the source route — clone the
  repository and build from it, stated once in the getting-started guide
  with its commands in the root README — and sends feedback to the
  repository's discussions and bug reports; where a page keeps an account of
  the hosted channel's routes, because a reader may really have installed
  that way or because the code ships here, it says that channel is not what
  the public repository's first release offers. The uninstall guide no
  longer quotes the keyed installer, so the guide-bindings suite's command
  sites are the tester page alone, and its pointer rule asks the walkthrough
  and the user guide to name the getting-started guide and the README and
  not the tester page; the first-project journey test asks the same of its
  page.
- **The requirements document records the rulings behind the first public
  release (v1.15).** Non-goal 1 — languages other than Python — is now a
  statement of the current horizon, with expanding to other languages on the
  development roadmap and the way a part in another language is declared from
  the Python side today written beside it. NFR-8 says the codebase is released
  first, through GitHub alone: the public repository's first release is the
  source tree under its licences, reached by cloning and building, with
  nothing that depends on an account offered or described as a route by it,
  and the paid convenience channel comes after that release; §7.5 says the
  same. The product concepts file pins the amended document's digest.
- **The requirements document distinguishes the two ways an agent meets s0ma,
  and MCP is one channel rather than the way in (v1.16).** §1 separates the
  coding agent building or maintaining a s0ma application — efficiency,
  captured intent, enforcement — from an LLM or agent operating one, which the
  running system hands its own model to through the self-context and the
  runtime query surfaces — autonomy and safety; the end state and persona P1
  no longer say a coding agent connects over MCP, since it works from the
  checkout as well. The trust model says s0ma is an open-source codebase you
  build and run yourself, names the launcher, the keyed installer and the
  feedback function as the hosted channel's clients, and no longer reads as
  the account of a service. The stability statement speaks of no account or
  subscription at all. The retrofit guide starts from the Python in an
  application rather than from a Python application, and says how the parts
  that are not Python are declared as references. The studi0 feedback guide
  says sending feedback from inside s0ma is the hosted channel's function.
- **The front door distinguishes the two ways an agent meets s0ma.** The
  README's "Is s0ma for you?" and the getting-started guide it embeds now
  separate a coding agent building or maintaining a s0ma application — from
  the checkout with the `s0ma` command line, or through the authoring MCP
  server as one channel among others — from an LLM or agent operating one,
  which is handed the system's own model through the self-context and the
  runtime query surfaces; the README's MCP section says the server is one
  channel to the same model.

### Fixed

- **An application that declares a CONSTANT or TYPE cell reports HEALTHY
  again.** `ComponentRegistry.register_constant` and `register_type` in
  s0ma-core accepted the owning `module_path` but never derived the spec's
  `qualified_name` from it, so every such cell registered with an empty name,
  and the phantom-limb check — run by the Structural Verifier and the Coverage
  Auditor alike — reported it as an ERROR twice over. One constant was enough
  to turn `check_health` and `describe_system` to `UNHEALTHY`, which is what a
  four-component demonstration application served. Both helpers now derive
  `"<module_path>.<name>"`, the shape `@component` derives, and leave the name
  empty only when `module_path` is. A registry persisted before this release
  holds the empty name for those cells; the next idempotent re-registration
  from the same source repairs the stored spec in place, so clearing
  `.s0ma/registry.db` is not required. The transpiler's output is unchanged.
  Tests: unit tests for both helpers with and without `module_path`, the
  persisted repair, and a s0ma-dsl end-to-end test that builds a module with
  one CONSTANT and one TYPE cell, imports it through `bootstrap_imports`, and
  requires `verify_all` to pass. The product's own builds were checked the
  same way: before this fix the authoring server, studi0 and the
  documentation application all reported UNHEALTHY on their constants alone.
- **The dependency check charges an import to a part only when that part's
  own definition uses it, and a declared dependency reached without an import
  no longer counts as phantom.** `check_dependency_accuracy` took a module's
  whole import set — function-local and `TYPE_CHECKING` imports included —
  and charged it to every component registered from that module, so each
  nerve of a transpiled module was warned about the registration imports the
  emitter writes for its siblings, and a self-import inside one method in
  `s0ma.models` produced a warning on twenty-four other models. It now finds
  the component's own top-level definition (the class, function or assignment
  its `qualified_name` names) and counts the names that definition references
  in its body, defaults, base classes, nested decorators and annotations,
  quoted annotations included, with the registration decorator itself
  excluded; self-imports are never charged, and a module whose definition
  cannot be found keeps the old module-wide reading. A declared dependency is
  satisfied when the definition imports it, references it as a sibling in the
  same module, or references a name imported from the dependency's module,
  such as a factory function. Parsed modules are cached by modification time.
  The same pass found one false declaration, `LifecycleEvent` on
  `ErosionCoverageReport`, now removed, and forty references the framework's
  own parts make without declaring them, now declared in the bootstrap
  registration. Three stay undeclared on purpose, as warnings: `LifecycleManager`
  on `SelfModelInterface` and on `TransactionContext`, and `ComponentRegistry`
  on `topological_sort_modules`, each a deliberately lazy import whose
  declaration would close a cycle that the cycle check or `import_order()`
  reports as an error. For the four-component demonstration application the
  warnings on its own parts went from fifteen to none.
- **The signature check reads the documented `input_type` form.** The core
  user guide documents `input_type` as a parameter list, `"username: str"`,
  and the check compared that whole string with bare annotation names, so
  every helper of the language's runtime bridge warned. When the declared
  string names parameters, the check now compares those names with the
  signature's; a bare type is compared as before. The bridge's own declarations
  were brought up to date at the same time: `register_constant` and
  `register_type` declare the `module_path` they accept, the documentation
  and example helpers declare the types their code has, and
  `register_integration_helper` declares what it is annotated to take and
  return.
- **The language package's own components count as framework components**
  (owner ruling 2026-10-09). Every `S0maDSL_` component — the runtime bridge's
  registration helpers, the project helpers, and the rest of the transpiler
  — is registered with `is_framework=True`. They are s0ma's toolchain, not
  the application's parts, and the self-model now says so: `describe_system`
  for the four-component demonstration application reads "Framework
  components: 75, User/application components: 4" where it read 61 and 18,
  and the coverage auditor no longer lists the fourteen helpers an application
  runtime loads as parts nothing depends on. The s0ma-dsl self-description
  test that pinned the opposite now pins this.
- **The global registry knows s0ma's own parts from the moment it exists.**
  `get_registry()` created an empty singleton and `s0ma.initialize()`
  registered the framework into it afterwards, so a `@component` that ran
  before `initialize()` — every import-time registration in a toolchain
  process, and any library that never initializes — registered against a
  registry that did not know the framework, and a dependency declared on a
  framework component was logged as "not yet registered". The singleton now
  runs the bootstrap registration as it is created, published before it
  registers so a nested call during that registration receives the same
  instance; `initialize()` keeps its call, which is then a no-op. A repeat
  bootstrap costs well under a millisecond once the framework is imported.
  With that in place the language package's runtime-bridge helpers declare
  the s0ma-core components they construct — `ModuleMetadata`,
  `RelationshipEdge`, `TestRegistration`, `DocRefRegistration`,
  `DocGuideRegistration`, `ExampleRegistration` and `ComponentSpec` — and the
  self-model of an application built with the language reports no warning
  on the toolchain at all: for the four-component demonstration application,
  three warnings remain and all three are the lazy edges inside s0ma-core
  named above.
- **studi0 binds its loopback socket without a reverse-DNS lookup.**
  `HTTPServer.server_bind` resolves the bound host with `socket.getfqdn`, a
  lookup that stalls for tens of seconds on a machine whose resolver answers
  slowly; the public repository's first macOS CI run showed the first studi0
  launch of the test session missing its thirty-second startup window for
  exactly that reason, with every later launch passing once the resolver had
  cached its answer. studi0 only ever binds the loopback literal, so the
  lookup could never say anything the literal does not: the server now binds
  the socket and records the address by value. One test refuses the lookup
  and binds anyway.
- **The `authored-lines` stage no longer fails a checkout that lacks the spike
  tree.** `scripts/spikes` is one of the six trees whose `.s0ma` fixtures the
  stage reads, and a tree with no tracked `.s0ma` file was an error, so that a
  moved tree could not pass by silence. The public export withholds the spike
  directory whole, and inside an exported tree the stage therefore went red
  (and with it two tests that run the stage end to end), which is the one
  thing that made the export rehearsal of 2026-10-15 invalid. The spike tree is
  now the one optional tree: read where present, reported as withheld and
  skipped where absent, with the summary line counting the trees actually
  read. The five core trees keep the loud error, and the floor on the number
  of lines read still guards the scan. One test covers the absent tree.
- **The editor grammar names the `helpers` line and the spec it was
  harvested from, and its README installs into VS Code and Cursor by a route
  that works.** The TextMate grammar's known-field rule lacked `helpers:`, so
  that line took the generic key colour rather than the field colour every
  other authored line gets, and the grammar's contributor note still pointed
  at the previous language spec while the editors README and the drift guard
  point at the current one. The README's full-highlighting route copied an
  unpackaged folder into the editor's extensions directory, which current VS
  Code and Cursor no longer load: they read only the extensions their own
  manifest registers. The route is now a small local package zipped from the
  same two files and installed with the editor's own command line, which
  registers it; the README names Cursor, and says the install was checked
  against Cursor on macOS.

## [0.19.0] — 2026-10-05

0.19.0 is the first s0ma release since 0.18.1 of 28 August 2026, and the first
in which all four packages (s0ma-core, s0ma-dsl, s0ma-mcp and s0ma-studi0) are
offered under the Apache-2.0 license. It adds a guided, step-by-step way to
bring s0ma into a codebase that already exists (the `s0ma adopt` commands), and
a quick reference that gives a person one page and gives an agent the same
facts as data. The documentation now answers from an installed toolchain, not
only from a copy of the source, and every answer says which build it came
from. Two changes can stop something that worked before:

- **The check now reports lines it cannot read, and tests that would never
  run.** A misspelt line name, a line indented by the wrong amount, or a test
  the test runner would never pick up used to be passed over in silence. Each
  is now a warning in `migration` and `dev` and an error in `strict` and
  `release`, so a project that builds at `strict` or `release` may now be
  refused. Run `s0ma check --mode dev` first: it lists every one as a warning
  and refuses nothing. Then fix what it lists. For a test, rename its function
  so that the test runner collects it: the function's name decides what runs.
- **In s0ma-studi0, `compute_payload` is renamed `read_graph`.** Nothing
  studi0 shows in a browser or serves to another program changes. Only code
  that imports `compute_payload` from `s0ma_studi0.studi0_state` needs to
  import `read_graph` instead.

### Added

- **The quick reference: one page for a person, the same facts as data for a
  program (owner decision 2026-09-29)** — two new generated outputs of the
  documentation application, rendered from one value so they cannot disagree.
  `docs/reference/quick-reference-readable.md` is the page: what a `.s0ma`
  file looks like, the eleven kinds of declaration and when to reach for each,
  every line each kind may carry with whether it must be written, whether it
  may be `none` or `pending`, and what it holds, the words a line chooses from,
  a sample of every kind, the everyday commands, the strictness modes, the
  basic rules, and where to ask for more. It is written for somebody who does
  not program. `docs/_generated/quick-reference-machine.json` (schema
  `s0ma-quick-reference@1`) is the same content for a coding agent. Nothing on
  either is typed from memory. The lines come from the table the check itself
  enforces, through the same reading the new `UNKNOWN_FIELD` report uses, so a
  line is on the page exactly when the check accepts it. The words come from
  the language's own closed sets and the layer rule from the matrix the
  resolver enforces. Every command line is parsed against the command line
  s0ma really serves, down to each option and each value an option accepts;
  every report, agent tool, resource, prompt and document the page names is
  resolved against what this build composed. Every sample is cut from one
  small project, which the build parses and validates at release mode before
  it writes anything and the suite then builds, tests and runs for real. The
  explanations are the one authored part, in
  `docs/s0ma_src/quick-reference.json`, held to the language in both
  directions: a line the language has and the file does not describe stops the
  build, and so does a description of a line the language no longer has. The
  page keeps its own list of editions, and the newest edition pins what the
  language accepted when it was written, so a change to the language stops the
  build until somebody has written what changed for a reader. The number of
  reports each mode refuses is counted from the severity registry rather than
  described. The page is on the documentation map and at the head of the
  signposts under every page of the learning collection.
  [The maintenance runbook](docs/operations/docs-maintenance.md) says which
  entry to edit when the language changes.
- **A guide to what the build writes (`docs/guides/what-the-build-writes.md`)**
  — one page that opens a build directory and says what each file in it is
  for, using the survival card's module and the real output of building it:
  the Python module that runs, and registers each part with the runtime as it
  loads; the canonical IR, the module described as data, which `s0ma inspect`,
  `s0ma graph`, studi0 and the self-context files read; the source map from
  each line of that Python back to the line that was written; the manifest,
  whose dependency order `bootstrap_imports` loads in and whose fingerprints
  `s0ma doctor` compares for freshness; the type stub; the package marker; the
  two self-context files; and the cache. It ends with why none of them is
  edited by hand: the `s0ma verify` report a hand-edited file produces, the
  build that refuses to write over it, and the cached build that leaves it as
  it is. The guide joins the documentation catalog and the classification
  ledger, and its six coverage claims are weighed against its prose in the
  guide-bindings suite.
- **Retrofitting an existing codebase — `s0ma adopt scan` and the guide
  (beta-prep-1-retrofit)** — the first rung of a supported path for bringing
  an existing plain-Python codebase into s0ma. `s0ma adopt scan [PATH]
  [--source-root DIR]... [--format text|json] [--detail MODULE]` reads a tree
  without importing or running any of it and without writing anything
  anywhere, and reports what is there and what to convert first: modules and
  public things, the first-party import graph with load-time cycles, a
  leaves-first conversion order, a proposed layer per module with its reasons
  in plain sentences (a suggestion that says how confident it is, checked
  against the language's own layer rules), the perimeter `pyproject.toml`
  would declare, a rough size per module, and the next command to run. A pair
  of modules that avoids a cycle only because one import sits inside a
  function is called out, because it has to stay deferred when converted. On a
  tree that already is a s0ma project the report's `UNKNOWN` count matches
  `s0ma verify`'s. The JSON form is `s0ma-adopt-scan@1`. The new guide,
  `docs/guides/retrofit-existing-codebase.md`, teaches the whole path — assess,
  perimeter, register in place, convert one module at a time with a parity
  check, ratchet — and opens with a card short enough to hand to an agent; it
  is reachable through `s0ma docs show` and the agent read surface with no new
  MCP component. The remaining commands of the family (`draft`, `baseline`,
  `verify-parity`, `status`) land in the entries that follow.
- **`s0ma adopt init` — the perimeter (beta-prep-1-retrofit)** — makes an
  existing Python tree a s0ma project without touching a line of application
  code. `s0ma adopt init [PATH] [--source-root DIR]... [--dry-run]` appends a
  `[tool.s0ma]` table to `pyproject.toml` (the original bytes stay a strict
  prefix; a minimal file is created when there is none) with the source
  roots, entry-point and package-marker exemptions the scan proposes and
  `mode = "migration"`, then appends one marked block to `AGENTS.md` telling
  whoever works there next that the project is being retrofitted, where the
  guide is, and never to edit the build directory. Nothing else is written —
  no starter module, no bulk adoption: the `UNKNOWN` list `s0ma verify` then
  shows is the honest to-convert backlog. The written project is loaded
  before the command reports success, and `pyproject.toml` is restored
  byte-for-byte if it would not load; a flat, un-packaged tree gets
  `test_roots = []` with a comment saying why, because a test root nested in
  a source root is refused. A second run refuses ("already a s0ma project")
  and changes nothing. `adopt scan` and `adopt init` no longer print the
  "operating without project discovery" warning, which contradicted the
  very thing they are for.
- **A draft cannot build or score as though it were finished
  (beta-prep-1-retrofit)** — `s0ma check` now refuses the two kinds of
  unfinished business a retrofit draft carries, and refuses them in every
  strictness mode including `migration`, which is the mode a retrofit runs
  in. `ADOPT_PLACEHOLDER_INTENT` names every field still holding the
  `FIXME(adopt):` marker the draft tool leaves wherever it could not write
  the meaning for you — one finding per field, saying which declaration and
  which field, what a finished one says, and what to do next. Meaning is
  never guessed, so this is the work the tool hands back rather than
  something it failed at. `ADOPT_UNPLACED_CODE` names every quarantine cell:
  source text the draft kept word for word because it belonged in no
  declaration, reported with the line range it came from and the two ways
  out — move it into the declaration it belongs to, most often the module
  header's imports, or delete it if nothing needs it any more. A quarantine
  is recognised two independent ways, by its reserved `ADOPT_UNPLACED_` name
  and by its `adopt: unplaced` marker, so neither renaming the cell nor
  deleting the marker quiets the refusal. Ordinary modules are untouched:
  declaration bodies are never read, so a file whose own Python happens to
  mention the marker is left alone.
- **`s0ma adopt draft` — one Python module becomes a draft
  (beta-prep-1-retrofit)** — the command that opens rung 3, the rung you
  repeat. `s0ma adopt draft MODULE_OR_FILE [--layer LAYER] [--out DIR]
  [--dry-run] [--force]` reads one module — named the way `s0ma adopt scan`
  printed it, or by path; both reach the same file, because both are
  resolved by the same reading — and writes the `.s0ma` draft of it beside
  where the converted module will live. Structure is derived: every
  top-level function becomes a nerve, or a helper when its name starts with
  an underscore; every class and every upper-case constant becomes a cell;
  bodies are carried across exactly as they are. Meaning is not: every field
  that says what something is *for* arrives as a `FIXME(adopt):` line saying
  what belongs there, and `s0ma check` refuses the draft until a person has
  written them. The layer is yours to name with `--layer`, or comes from the
  scan's proposal when the scan was confident, and otherwise the draft asks
  for it and names what the scan thought plausible. The Python file is
  parsed, never imported and never run, and it is not modified, moved or
  deleted — it stays the code that runs until you delete it yourself, and
  the closing message says so, counts the work left in the draft, and names
  the two commands after this one, starting with the baseline you take
  before anything is deleted. `--dry-run` prints the draft and writes
  nothing; a draft already in the way is never replaced without `--force`,
  and neither is a module that has been converted already. Test files,
  package markers, generated files, files outside the project, a name
  nothing matches (the nearest ones are offered) and a name more than one
  file answers to are each refused in one sentence saying what to type
  instead. The retrofit journey now walks all six steps, and its recorded
  transcript is replayed against the fixture application on every build.
- **`s0ma adopt baseline` and `s0ma adopt verify-parity` — the promise that
  makes a conversion safe (beta-prep-1-retrofit)** — before a module is
  converted, `s0ma adopt baseline (MODULE_OR_FILE... | --all)` reads its
  Python and writes down what it offers its callers — every public name, how
  each one is called, the type each one declares, its base classes, its
  decorators and its docstring — into one committed file at the project
  root, `adopt-baseline.s0ma.json`. Recording a module whose file has not
  changed writes the same bytes, so a second run diffs empty; recording one
  that has changed says the old record was replaced and names it. After the
  module is built, `s0ma adopt verify-parity (MODULE... | --all) [--format
  text|json]` compares the emitted `.py` with that record and puts every
  difference on a line of its own: the name it is about, what moved in plain
  words, and the text before and after. Eight kinds of difference are
  reported — a name gone or new, a signature, a declared type, a docstring,
  a base class, a decorator, a constant's value — so a conversion that
  quietly drops `functools.lru_cache`, `staticmethod`, `classmethod` or
  `property`, or turns a field's `str` into an `int`, cannot pass. Four
  things are not differences, because the build adds them and no caller
  could have depended on their absence: the registration decorator above
  each declaration, the generated header and its hash lines, the runtime
  import block and its registration calls, and the order of `__all__` — a
  different *set* of exported names is still reported. Documentation that
  arrives where there was none is not a difference; documentation that
  changes or disappears is. Parity exits 0 when every module compared has
  the surface it had and non-zero on any finding, so it can gate a commit;
  `--format json` is the same verdict as an `s0ma-adopt-parity@1` document,
  and `--all` compares every module that has a baseline and has been built,
  naming the ones that have not rather than passing over them. Neither
  command imports the code it reads, and parity writes nothing anywhere. The
  refusals say which rung is really missing: no project yet, nothing built
  yet, no baseline for that module — and, when its Python file has already
  been deleted, the plain news that the comparison can no longer be made and
  what to do instead. The guide's rung 3 now also spells out the step after
  deleting the old `.py`: a build directory is flat, so a package has to
  point the old module name at the module s0ma built, in six lines at the
  top of its `__init__.py`. The retrofit journey walks all eight steps, and
  its recorded transcript now takes one module the whole way — record,
  draft, author, build, compare — against the fixture application on every
  build.
- **`s0ma adopt status` — where am I on the ladder? (beta-prep-1-retrofit)**
  — the command for coming back. A retrofit is walked over weeks, and the
  hard question after a fortnight away is not how to convert a module but
  which one you were in the middle of. `s0ma adopt status [PATH] [--format
  text|json]` reads the whole project and answers four questions on one
  screen of at most fifteen lines, for somebody who has not read the guide:
  which rung of the ladder this is (nothing set up · the perimeter is set ·
  converting · ratcheting the mode up), what is done, what is left, and the
  one command to run now. It counts the application modules a conversion is
  about, how many are converted, how many are half drafted and how many
  placeholders those drafts still carry, how many files are registered where
  they stand, how many are still plain Python, how many baselines have been
  taken — and, only where something has been built, what comparing the build
  with those baselines says: same surface, differences, built without a
  baseline, recorded but not built. It reports the strictness mode, the
  floor that mode's gate would demand, and the project's score against it.
  The next step is chosen by one written-down table and is always a command
  you can paste; where more than one module is part way through it is the
  step for the one **furthest along**, because finishing what is started
  beats starting another, and the output says so. Nothing is remembered
  between runs: parity is recomputed from the files on disk, so the verdict
  is about the bytes that are there now. It writes nothing anywhere and
  never imports or runs the code it reads, and it answers for a tree that is
  not a s0ma project at all — that is rung 0, and the next command is `s0ma
  adopt scan`. `--format json` is an `s0ma-adopt-status@1` document with
  every count, the state of each module, and the next step as a sentence and
  a command. This completes the `s0ma adopt` family, so the block `s0ma
  adopt init` writes into a project's `AGENTS.md` — which has named this
  command since the perimeter existed — now names only commands that are
  really there, and a test parses that block and offers every command line
  in it to the live CLI parser so it cannot promise an unbuilt one again.
- **The retrofit path is now findable from wherever you are standing
  (beta-prep-1-retrofit)** — the guide existed; the three places a newcomer
  with an existing codebase actually stands did not point at it. Now they do,
  each in one short paragraph that names the guide and `s0ma adopt scan` as
  the first command and keeps no second copy of the ladder: `getting-started`
  says what to do when `s0ma new project` is the wrong shape because the
  folder is not empty; the MCP walkthrough tells an agent that "not a s0ma
  project" means two different things, and to ask `s0ma adopt status` which
  one it is in; and the DSL patterns guide gains a closing section saying
  that a codebase which predates s0ma is converted rather than authored, with
  the three facts from the guide that change how the patterns before it
  apply mid-conversion. The guide itself now names the two refusals a
  conversion really meets — `ADOPT_PLACEHOLDER_INTENT` (a field still carries
  the `FIXME(adopt):` marker; one per unwritten field, not per declaration)
  and `ADOPT_UNPLACED_CODE` (text the draft could not place, kept word for
  word in a quarantine cell named for the lines it came from) — with what
  each means and what to do about it. Every `s0ma adopt` surface now sits
  under the retrofit capability in the coverage policy, `adopt file`
  included: recording a file that will stay plain Python for a while is the
  optional second rung of the same ladder, and the ruling that excused it
  from needing a path was written when no path taught adoption at all.
- **The version-currency gate now covers the drift hotspots (doc-function-1
  A4)** — `LIVING_DOCS` grew from six to twelve files (the four package
  READMEs, `CONTRIBUTING.md`, `editors/README.md`), with a curated allowlist
  for genuinely historical references; a package-map assertion derives the
  expected distribution list from `packages/*/pyproject.toml` and requires
  every package to appear in `CONTRIBUTING.md`'s tree and `AGENTS.md`'s map,
  so a fifth package can never be silently omitted the way studi0 was; the
  release checklist no longer says "check those by hand". The sweep also
  caught and fixed a genuinely stale `"version": "0.17.0"` in the mcp
  README's sample and a root-README language-spec link that had been bumped
  to a spec that does not exist.
- **A complete classification of the documentation corpus (doc-function-1
  A6)** — every tracked Markdown file now carries exactly one disposition
  (`plans/notes/doc-classification-1.json`, 157 rows: 51 historical, 35
  working-plan, 28 living-authored, 20 normative-current, 9 mirrors, 6
  pointers, 5 generated, 3 non-documentation), with a human summary and a
  temporary presence guard so a new document cannot land unclassified. This
  ledger seeds the documentation application's catalog and is the migration
  map for the consolidation phase.
- **An intra-repo link and anchor guard (doc-function-1 A5)** — new
  `check.py` stage `docs-links` (`scripts/check_links.py`): every
  repository-relative Markdown link must resolve to a tracked file or
  directory and every intra-repo `#anchor` to a real heading
  (GitHub-slugged), offline and deterministic, with an empty allowlist at
  introduction. Its first sweep surfaced 22 pre-existing broken links —
  all repaired in the same change: three mis-slugged migration-guide
  anchors, ten completed-plans paths in four dsl ADRs and the 0.14.0
  contract, a literal developer-machine path, the root README's dead spec
  link, and eight links retired by moving the honestly-historical
  `release_walkthrough_5-6.md` under `docs/historical/` with a pointer
  stub (its README row and inbound links now point at the moved file).
- **Tester-facing uninstall and troubleshooting guides (doc-function-1 A7)**
  — `docs/uninstall.md` (complete removal: agent deregistration, both
  documented install layouts, per-project state, what is never touched,
  reinstalling) and `docs/troubleshooting.md` (a human FAQ: `s0ma doctor`
  first, version identification, check-vs-staleness-vs-drift in plain
  language, a humanized common-errors table, MCP and studi0 sections, and
  what makes a feedback report actionable). Both linked from the two
  getting-started guides. The `s0ma studi0` not-installed hint no longer
  recommends `pip install s0ma-studi0` (impossible during the beta, PRD
  NFR-8); it now names the two install routes that work.

- **studi0 declares its own served surface (doc-function-1 D4)** — a new
  `ROUTE_TABLE` cell in the package's authored source declares every HTTP
  route (path, method, purpose, effects, serving nerve), with a structural
  parity test so the table cannot drift from the routing code; the wire-schema
  identities moved from test constants into package data; one registered
  intent dropped the word "payload".
- **Every capability s0ma serves now has a reference page, and every concept
  a page to learn it from (doc-function-1 F3–F5)** — the documentation build
  went from seven generated files to fifty-three. Seven of them are the
  complete reference set, each rendered from what the product really does
  rather than from anybody's notes: every command with its arguments,
  options and defaults; every `[tool.s0ma]` setting a project can declare;
  every report s0ma can make, with how seriously each is taken in all four
  strictness modes; both MCP servers, tool by tool and resource by resource;
  the studi0 viewer's routes and the contracts they are held to; the
  distributions this workspace ships; and a component index that succeeds
  the hand-maintained architecture document the 2026-08-28 audit found had
  stopped naming half of them. The other thirty-nine are the learning
  collection under `docs/learn/` — one page per concept, a public glossary
  that closes the audit's missing-glossary finding, and the anatomy of a
  `.s0ma` file assembled out of the eleven declaration kinds themselves.
  That collection is computed rather than listed: write a new concept and
  its page ships with it, delete one and the page left behind is reported
  as drift instead of going quietly stale. Three rough edges a reader would
  have met went with the wave — two project settings whose descriptions
  stopped mid-sentence at "e.g.", the `s0ma new` help line that swallowed
  its own `<dir>` wherever it was rendered as Markdown, and a row of the
  error catalog whose columns collapsed on an unescaped table separator.
- **Discovery is now a tested contract (doc-function-1 F9)** — all
  fourteen documentation entry points (seven human, seven agent) are
  executable tests against the real CLI and the real in-process server;
  `s0ma new project` and `s0ma doctor` now name the first journey to
  read next; generated project instructions teach both the human and the
  agent route; and the 21 alternate concept names resolve everywhere,
  including on a wheel with no checkout.
- **Three ways to read the documentation, all serving one snapshot
  (doc-function-1 F6/F7/F8)** — `s0ma docs` now opens the learning map
  (with `list`, `show`, and `search` over every topic, each answer naming
  the page that carries the rest); coding agents get the `learn_s0ma`
  tool and the `s0ma://docs/` resources on the authoring server, with the
  one-line pointer riding the tool results that are proven to arrive; and
  a pip-installed s0ma-core finally answers teaching questions — the
  wheel ships a generated slice of the same documentation build, so
  `learn_about_s0ma` returns current content with version and snapshot
  identity instead of "docs unavailable". The same topic through the
  command line, the agent tool, and the installed wheel carries the same
  facts, the same release, and the same snapshot hash.
- **The documentation now has a map of record (doc-function-1 F2)** —
  `docs/README.md` is generated from the document catalog: every current
  document listed with its audience, status, and which gates keep it
  honest; mirrors and the archive behind their own sections; and the ten
  documents the 2026-08-28 audit found outside its own location table are
  all present. The repository gate rebuilds and byte-compares the map on
  every run, so the index that closes the "orphaned docs are the stale
  docs" finding can never itself go stale.
- **Five executable journeys with guides (doc-function-1 E wave)** — every
  primary path through the product is now a validated journey with a
  human guide whose every command and quoted output line is replayed
  against the real toolchain by a transcript fixture: your first project,
  your first module (the anatomy walkthrough), authoring through the
  agent's tool channel, diagnosing and recovering from drift and release
  debt, and inspecting through studi0 plus sending reviewed feedback data.
  The corpus also corrected itself along the way: `s0ma check` now
  honestly declares the one bookkeeping file it writes, and the guide
  pages teach only what their fixtures prove.
- **`doc-ref` derived sources became a registry (doc-function-1 D7, per
  ADR-013)** — source names dispatch through a provider registry with
  declared per-format rendering (a `format: html` derived doc-ref now renders
  a real table instead of silently emitting nothing; an undeclared format
  fails with `DOC_SOURCE_FORMAT_UNSUPPORTED`); `sections:` is optional for
  the source-registry form (an empty list still parses, a non-empty one is
  refused); the spec's hard-coded one-source sentence became the release-bound
  enumeration policy; and derived doc-refs now carry the source registry's
  record hash in their provenance, so a changed error-code table moves the
  rendered document's content hash — before this, the whole table could be
  rewritten under a stable hash.
- **Every answer now says which build it came from, and a release proves its
  wheels carry that build (doc-function-1 H1–H2c)** — documentation is built
  in one of two channels, and a build that nobody told is a release is not
  one, so everything composed from `main` is labelled `preview` wherever a
  version is written. That label had reached the generated pages and the CLI
  read surface; it now reaches the last two places a reader actually meets
  it. `s0ma-core`'s teaching answers say "This answer came from s0ma 0.18.1
  (preview), teaching snapshot …" instead of naming a release the wheel was
  not cut from, and the three `s0ma://docs` index blurbs say the same. Core
  learns the channel from a new `build_channel` field on the teaching slice
  it ships — an additive field, so a slice written before this change still
  reads, as preview. Underneath, `scripts/wheel_smoke.py` gained the check
  that makes those claims true rather than merely consistent: it opens the
  built wheels and requires the embedded teaching slice to name the snapshot
  the release manifest names, the `s0ma_mcp/_docs` payload to be the
  cataloged sources byte for byte, and every rendered identity line to
  describe the version the wheels actually are. The release workflow runs
  the same check on a tagged commit **before** anything is mirrored or
  served, so a release whose documentation and wheels disagree stops instead
  of shipping. That job is present but inactive: it waits on a repository
  variable the owner sets (`docs/RELEASING.md` says what to do first). And a
  release cut can now say which release it is composing — `s0ma docs compose
  --head-tag v0.18.1`, and `docs check --head-tag v0.18.1` to prove the
  committed state already is that release before a wheel is built — which
  drops the `preview` label everywhere; the tag is stated rather than looked
  up, so a tag naming some other version composes a preview and says so on
  the spot instead of quietly shipping one. The repository's own gate now
  follows that claim rather than assuming one: it reads which channel the
  committed documentation says it was built in and checks it as that. For
  anyone not cutting a release this changes nothing — no tag is stated, the
  tree says preview, and the gate runs exactly as it did. A release cut
  states the same tag to the gate (`S0MA_HEAD_TAG=v0.18.1 uv run python
  scripts/check.py`, and the tag push does it automatically), and a
  release-composed tree with no tag stated is refused rather than quietly
  checked as something else — which is what keeps release-labelled
  documentation off `main`.
- **The Claude route is documented (beta-prep-2-claude)** — a new guide,
  `docs/guides/claude-integration.md`, is the one account of installing s0ma
  through Claude: the Claude Code plugin and the Claude Desktop extension, the
  three settings each asks for under the names they show on screen, where a
  license key goes and where it must never go, how the toolchain keeps itself
  current (quietly, in the background, used from the next session, never in the
  middle of one, previous version kept), how a project pins itself and goes
  back, why the plugin updates on a separate schedule from s0ma itself, what
  happens offline, and what ends when access to new versions ends. There are
  now three install routes — through Claude, the keyed installer, from source —
  and `docs/getting-started.md` §1 states all three once, as it already did for
  two. `docs/trust-model.md` gains the exact account of what the launcher
  sends: one host, three requests, a license key in an `Authorization` header
  and nothing else, at most one automatic check a day, four conditions before
  that check happens at all, and how to stop each one.
  `docs/troubleshooting.md` gains a section for that route: what each exit code
  means and what to do about it, and what each of the six lines a session can
  begin with is telling you. `CONTRIBUTING.md` documents the `integrations`
  gate stage and the sync command every launcher change is followed by, and
  `docs/RELEASING.md` the sync step a release cut performs by hand. A draft
  amendment to PRD FR-COM-4 — which still says "no auto-update, ever" — is
  written up for the owner in
  `plans/notes/claude-integration-prd-amendment-draft.md`; nothing in the PRD
  has been changed.
- **The community files a stranger needs (beta-prep-5-front-door)** — five new
  front-door documents, so that somebody arriving at the repository knows where
  to take each kind of message. `SECURITY.md` is the security policy: report
  privately through the repository's Security tab or `security@kn0wthyself.ai`
  and never in a public issue, what to include, what to expect and by when,
  what is in and out of scope, safe harbour for good-faith research, no bounty
  programme, and the four things security-minded people ask about s0ma — each
  one linked to `docs/trust-model.md` rather than restated. `CODE_OF_CONDUCT.md`
  adopts the Contributor Covenant 2.1 by reference, with our own summary, where
  to report (`conduct@kn0wthyself.ai`) and what happens after a report. Under
  `.github/`: two issue forms (a bug report that asks for `s0ma doctor`'s
  output, the operating system, how s0ma was installed, what happened, what was
  expected and the smallest reproduction — and a question form that points at
  Discussions first), a chooser that switches blank issues off and routes
  security reports to private reporting and product feedback to `s0ma
  feedback`, and a pull-request template. The contribution policy for the beta
  is stated in both the template and a new opening section of
  `CONTRIBUTING.md`: issues, bug reports and discussions from anybody, pull
  requests by invitation with a Developer Certificate of Origin sign-off, and
  the reasons why. Nothing is published by this change; the links it carries
  resolve when the repository does.
- **The stability statement (beta-prep-5-front-door)** — `docs/stability.md`
  answers, on one page, the question anybody deciding whether to build on a
  pre-1.0 product asks first: what can change under me, and how will I know? It
  separates what is written down as not-to-be-broken (the import names, the
  file extensions, determinism across the three platforms, and the runtime
  never being gated) from the two frozen contracts and the rule both follow — a
  contract changes by gaining a new version or a recorded revision, never by a
  silent edit — from the documents that carry their own schema string, where a
  reader may assume additive fields within a number and a refusal rather than a
  guess for a number the toolchain does not know. Then the honest half: text
  written for people is reworded and `--format json` is the form to parse,
  report codes are the interface and their sentences are not, a newer toolchain
  can generate different bytes from sources you did not touch, the served agent
  surface gains tools, and studi0 is an early preview that promises least. It
  closes with the two habits that make all of that survivable (pin the version,
  commit the build and check it with `s0ma build --check`), how a change is
  announced — one lockstep version, one changelog, `BREAKING` at the head of an
  entry, and the honest admission that before 1.0 no deprecation period is
  promised — which versions get fixes, and what "beta" means for the software
  and, separately, for the subscription. It names no version number anywhere.

### Changed

- **BREAKING — a line the check cannot read is now reported, and so is a test
  that would never run (owner decision 2026-09-29)** — three new reports, each
  a warning in `migration` and `dev` and an error in `strict` and `release`.
  A project that builds at `strict` or `release` and carries one of these
  mistakes built before and is refused now; `s0ma check --mode dev` lists them
  as warnings without refusing anything. `UNKNOWN_FIELD`: a line whose name
  that kind of declaration does not have. Such a line used to be stored and
  never read, so a misspelt optional line — `tagz:` for `tags:` — silently did
  nothing. The report names the line that was probably meant, or the kind the
  line belongs to. `UNRECOGNIZED_LINE`: a line inside a description that is
  not a field, not part of a block and not a comment — almost always a line
  that starts with the wrong number of spaces. Such a line used to be skipped.
  `TEST_NOT_COLLECTED`: a `test` whose code defines no function the test
  runner would run. The test was emitted, never executed, and still counted as
  coverage for the parts it named; the function's name decides what runs, and
  the declaration's does not. The names the runner collects are read from the
  project's own pytest settings (`pytest.ini`, `pyproject.toml`, `tox.ini`,
  `setup.cfg`, in pytest's order), so a project that has told pytest to
  collect other names is not told its tests will not run. A required line
  that is on the page under the wrong name or at the wrong indentation is
  still an omitted line, reported first and in every mode as before; what
  changes is that `SEMANTIC_REQUIRED_STATE_OMITTED` now names the line it
  found and says what is wrong with it. The known lines are read from the
  field table rather than kept as a second list, and the suite holds that
  reading against every line the parser's builders actually read. No source
  in this repository trips any of the three. Language specification: new
  §4.0.3; §4.4a and §4.8.2 amended; the sample in §4.8.4 now names its
  function the way the runner needs. The error reference and the traceability
  table are regenerated (so was the long quick reference, since retired — see
  the entry below). The documents that describe what the check reports say
  so too: the troubleshooting guide's table of common failures has a row for
  each of the three, the survival card's "if check fails" list names them,
  the agent system prompt states the rule they enforce beside the lines each
  kind of declaration always writes (its required-fields list was the
  pre-0.14 form, and its module header still said `requires:` is written
  only when needed), and the patterns guide's section on `test` blocks
  carries the collection rule.
- **PRD v1.14 — every package's name is published (owner ruling 2026-10-04)** —
  NFR-8 and non-goal 3 now say that all four packages, `s0ma-mcp` and
  `s0ma-studi0` beside `s0ma-core` and `s0ma-dsl`, are published to PyPI from
  the first release cut of the public repository, and that the bare name `s0ma`
  is to be held by a small umbrella distribution built before that release. A
  name on an index is held only by publishing under it: all five were unclaimed
  when checked, and the letter-o spelling already belongs to an unrelated
  project. Nothing changes today: nothing is published while the repository is
  private, and nothing built from the private tree ever is. The release page,
  the publication runbook, the README's install notes and the dormant
  `publish-pypi` job say the same; the job, still commented out, now names four
  packages.
- **The language specification states which lines each declaration must write
  in one place, and that place is generated (owner ruling 2026-09-29)** — the
  field classification existed four times: the toolchain's
  `FIELD_CLASSIFICATIONS`, the 0.14.0 contract's §3, spec §4.14.5, and spec
  Appendix A, and the two copies inside the spec had parted: Appendix A still
  marked as optional most of the lines 0.14 made required, and had no column
  for five of the eleven declaration kinds. The table in §4.14.5 is now
  rendered from `FIELD_CLASSIFICATIONS` by the new
  `scripts/generate_spec_field_table.py` (read-only check by default,
  `--write` to rewrite the spec and its packaged copy), and a test in
  `test_doc_consistency.py` fails whenever the table and the classification
  differ — the way the quick reference's Common Errors table is already kept.
  The rendered table names each line as it is written (`internal`, with the
  IR's `internal_helpers` beside it) and quotes each conditional line's
  applicability from the classification; no line changes class. Appendix A
  keeps its heading and points at §4.14.5. The five declaration sections whose
  field lists had gone stale — nerve, cell, ganglion, module and test — point
  at §4.14.5 instead of repeating it, keeping their cross-references to the
  sections that define shared fields; the five that still agree with the table
  (axon, helper, doc-ref, doc-guide, example) are unchanged. The spec's
  language version is unchanged: no rule moved, only where it is written.
- **The survival card is sized as its gate enforces it — under 4 KB (owner
  ruling 2026-09-29; PRD v1.13; contract revision R4)** — PRD NFR-5 said the first resource an agent is pointed to
  stays "≤ 2 KB, gate-enforced", but the gate has always asserted under 4,096
  bytes served, and the card was over 2 KB from its first release. Its minimal
  module gained the lines 0.14 requires (see Fixed), which took it to 3,378
  bytes; with the three new reports in its "if check fails" list and its
  pointer to the generated quick reference (the entries above and below) it
  is 3,725. The owner accepted that size and ruled that the number follows the
  gate: NFR-5 now says "under 4 KB, gate-enforced" (PRD v1.13), and the 0.14.0
  schema-and-surface-budget contract records the ruling as revision R4. Every
  pointer that gave the card's size now says "under 4 KB", which stays true
  for as long as the gate passes, in place of "~2 KB": the served description
  of `s0ma://guide/survival-card`, the server's instructions, the
  `author_module` prompt, the system prompt, the `AGENTS.md` that
  `s0ma new project` writes, the walkthrough and the `s0ma-dsl` README. The
  client-visible surface changes by the survival card's resource description,
  and the surface snapshot is regenerated for it.
- **The quick reference reaches an installed toolchain (owner ruling
  2026-09-29)** — an agent working in somebody's project must be able to
  reach every reference, with no checkout of this repository in sight. On the
  authoring server, `s0ma://guide/quick-reference` now answers with the
  generated quick reference page, served as Markdown, and a new resource,
  `s0ma://guide/quick-reference.json`, serves the same facts as data (schema
  `s0ma-quick-reference@1`) for a program that would rather look a line up by
  name than read prose. The address keeps its name, so every prompt, card and
  scaffolded `AGENTS.md` that already points at it keeps working and now
  means the generated page. Both forms ship in the `s0ma-mcp` wheel as
  byte-identical copies of what the documentation build wrote, gated the way
  the other packaged documents are and refreshed by the same loop, which
  therefore ends in five copies rather than three; the release check binds
  each copy to the manifest's content hash for that artifact as well. The
  older hand-written "s0ma DSL Quick Reference" is no longer served or
  packaged; it stays in the repository until what it holds that no other
  reference does has been placed, and is then retired. The sentences that
  described the resource as about ninety kilobytes to consult per topic — in
  the survival card, the scaffolded `AGENTS.md`, the `author_module` prompt
  and the walkthrough — now say what the page is. Surface contract revision
  R5: fifteen tools, sixteen resources, five prompts.
- **Retired: the older "s0ma DSL Quick Reference" (owner ruling 2026-09-29)** —
  `packages/s0ma-dsl/docs/s0ma-dsl_quick_reference.md`, about a hundred
  kilobytes written for coding agents, is removed. Two documents were called
  the quick reference, and the owner ruled the older one probably obsolete:
  retire it, and move first whatever it held that nothing else did. Each of
  its nineteen sections was read against the generated quick reference, the
  language specification, the learning pages, the generated references and
  the patterns guide, and five things had no other home. They have one now:
  the five stdlib import spellings that trip the `requires` heuristic and the
  body-evidence rule for vestigial imports (the patterns guide, its section
  1.5); the thin command-line shim that hands off to a presentation nerve with
  `argparse.REMAINDER`, and the `--` that action does not strip (the patterns
  guide, a new section 10.3); the import-sorter reshuffle to expect after a
  module is converted (the retrofit guide); what each exit code means and
  where a command looks for the project when it is run from elsewhere (the
  troubleshooting guide); and the order in which the strictness mode is
  decided, flag, then setting, then the command's own default (the
  strictness-mode page). Everything else on it was already held: the field
  templates and rules by the generated quick reference and the specification,
  the settings by the configuration reference, the commands by the command
  reference, the verify legend and the build's outputs by the specification,
  the layout standards by the patterns guide, the error table by the served
  error catalog it was a copy of. The meta-test that held that copy to the
  renderer is retired with it; the one over the served artifact stays. Every
  pointer to the old document now points at the page that holds the fact, and
  two "see also" pointers in the specification drop the retired name (to be
  reviewed with the rest of that document's edits under review V-7).
- **Every s0ma package is now Apache-2.0 (owner decision 2026-09-18)** —
  `s0ma-mcp` and `s0ma-studi0` join `s0ma-core` and `s0ma-dsl` under the
  Apache License 2.0, so the whole toolchain carries one license. The text
  they replace granted nothing: it forbade any use without written consent,
  which left invited testers unlicensed, and it declared the source
  confidential, which could not have survived a public repository. Releases up
  to and including 0.18.1 remain under the license they shipped with. The
  repository root gains the same `LICENSE` and a `NOTICE` that names the
  copyright holder and states that nothing third-party is bundled inside any
  s0ma distribution; the `NOTICE` stays out of the wheels. Moving together, as
  the agent contract requires: the wheel metadata (`license`, classifier) and
  bundled `LICENSE` of both packages; all four package READMEs and the root
  README's package table and license summary; the getting-started guide and
  its two copies; `AGENTS.md`; `CONTRIBUTING.md`, which now says the workspace
  is under one license and that a contribution inherits it; the generated
  package reference, which says the packages are all under the same license
  instead of describing a split of one; and the wheel-smoke and
  contract-acceptance license checks, which now also refuse a repository root
  without a `LICENSE` or a `NOTICE`. What a subscription buys is unchanged,
  and is now the whole description: the install channel, updates, the agent
  integration and support — never permission to run the code. Two docstrings
  that explain why the build loader moved into the runtime — in
  `s0ma_dsl.runtime` and in the runtime's bootstrap tests — described the
  authoring package as proprietary in the present tense; they now say it was
  proprietary at the time, and give the reason that still stands: a deployed
  application should not need the authoring toolchain installed at all.
- **The release runbook and the publishing job follow the package-index ruling
  (owner ruling O-5, 2026-09-18)** — `docs/RELEASING.md`'s index section no
  longer says "dormant, awaiting an owner decision": it records that
  `s0ma-core` and `s0ma-dsl` are published starting with the public
  repository's first release, that nothing built from the private source tree
  is ever published, and the four owner steps that switch it on. The release
  workflow's `publish-pypi` job is still commented out, but what it would do
  when uncommented now matches the ruling: it publishes those two
  distributions only, and only when it runs in the public repository. The
  publication runbook (kept private) carries the same steps on the day they
  apply, records the rulings made since it was written, and names the identity
  the public history will carry.
- **Three hedges on the stability page become promises (owner ruling
  2026-09-18)** — `docs/stability.md` was honest and said less than a cautious
  adopter needs, so three things that were already how the project behaves are
  now written down as commitments, before 1.0 as well as after it. A report's
  code is never renamed and never reused: once a code has shipped, that
  spelling means that report for good, and a retired code is never given to a
  different report. `--format json` is the interface for programs — it carries
  a schema string and changes only by addition within one schema number —
  while the text a person reads may be reworded in any release. And anything
  the page lists as stable, or versions by a schema string, gets at least one
  release of warning, with the old way still working, before it goes; what is
  not listed can still change in a minor release with a changelog notice
  alone. The generated reports reference says the first of these where a
  reader of codes will look. Criteria for 1.0 are deliberately not promised
  here: that section still says there is no published list and no date.
- **Every MCP tool now carries a human-readable title, and the surface
  contract is true again (owner ruling 2026-09-18, contract revision R3)** —
  directories that list MCP servers require a title a person can read on every
  tool, and none of the fifteen had one. Each tool declaration now authors one
  as `metadata: mcp_tool_title:` — "Check s0ma source", "Build the project",
  "Ask about s0ma" and twelve more, each approved by the owner. The bridge
  validates it as one line of plain text of at most 60 characters and fails
  the package import on a malformed one, exactly as it does for a malformed
  hint; the server serves the one authored value in both places a client may
  look, the tool's own `title` and `annotations.title`, so the two cannot
  disagree. No name, description, schema or hint changed, and no byte budget
  is touched: the serialized tool list grows by 604 bytes. Revision R3 of
  `docs/contracts/0.14.0-schema-and-surface-budget.md` also records what the
  contract had never been amended to say — the surface is 15 tools, 15
  resources and 5 prompts, the tool `learn_s0ma` and the three `s0ma://docs/…`
  resources having been authorized during the documentation initiative without
  a revision row — and states that it authorizes no other name. The surface
  snapshot is regenerated (thirty title fields and nothing else), the contract
  acceptance test pins `verify_host`'s title with its hints, and a new test
  module holds the rule: every served tool has a title, the two places agree,
  and a malformed title is refused.
- **The front door is tidied for publication (owner rulings 2026-09-18)** —
  what the public repository leaves out, and what the published files say
  about who to write to. One contact domain: all four packages' author field
  now reads `kn0wthyself <support@kn0wthyself.ai>` instead of a personal
  address on another domain. `SECURITY.md`'s response times are confirmed —
  acknowledged within 3 working days, assessed within 10, details held for up
  to 90 days — and its scope stays the four packages, the installer, the
  integrations and the account service; `CODE_OF_CONDUCT.md` keeps its short
  form; the three questions to the owner that sat in those two files as hidden
  comments are answered and removed. `docs/hosting-getting-started.md` and
  `docs/RELEASING.md` no longer name the control plane's admin address, its
  sign-in method or a personal smoke-test address — operating the hosted
  service is documented with that service — and the release workflow's
  skipped-verification notice and one link-checker test fixture follow.
  `CONTRIBUTING.md` explains the `plans/` paths that comments and history
  cite: a private planning archive, a record of where a decision came from
  rather than a link to follow. The public-export rules record the rulings:
  `plans/` stays private and the PRD is published, as before; the whole of
  `docs/archive/`, `scripts/spikes/` and `scripts/smoke_hosting.sh` are now
  withheld, and the publication runbook stays withheld; four link-checker
  allowances whose source was an archive tombstone are gone (17 to 13); two
  citation rewrites with nothing left to rewrite are removed and one count is
  corrected (87 to 77 sites) — one of those had been stale since the last
  wording fixes of 2026-09-17, which no rehearsal had covered; no address
  domain is allowed beyond the scanner's own list any more; and the first full
  rehearsal with the spikes withheld found two things a search had missed —
  the discovery surfaces' declared byte budgets, a fixture inside the spikes
  that three test modules read as their authority, now travels through the
  rules' `keep` list, and the map-of-record test expects its three archive
  pages exactly where the archive is in the checkout and none where it is not.
- **PRD v1.12 — one consolidated amendment for the beta (owner rulings
  2026-09-18)** — the requirements document catches up with what was built and
  decided. Retrofit becomes product surface: principle P-8 now covers code
  that has never known s0ma; new requirement FR-DSL-8 states six invariants
  (static only; a read writes nothing; one module at a time; the original is
  never modified; a draft is unfinished by construction; parity is taken first
  and names every difference); metric M-8 measures an unaided agent converting
  one leaf module in at most two check/fix rounds; and the glossary gains
  *adoption ladder*, *perimeter* and *parity baseline*. The update model is
  reversed: FR-COM-4's "no auto-update, ever" becomes automatic by default —
  never mid-session, always reversible, always pinnable, switchable off — and
  NFR-6 gains a narrow exception for the launcher. The commercial model is
  restated as open source plus a paid convenience channel, and three
  requirements that described things nobody built are made honest: FR-COM-1
  names what exists and what does not; FR-COM-2's cached token and offline
  grace window are withdrawn in favor of a standing rule that nothing
  installed ever checks a subscription in order to work; FR-COM-3's
  `LICENSE_EXPIRED` code is withdrawn. NFR-8 records the license change above,
  and that `s0ma-core` and `s0ma-dsl` will also be published to PyPI starting
  with the public repository's first release — nothing built from the private
  source tree is published there — and it corrects an earlier claim that
  setting up a trusted publisher reserves a package name (only publishing
  under it does). The header's owner cell names kn0wthyself alone. The
  documentation model follows: the *adoption ladder* and *perimeter* concepts
  now cite FR-DSL-8 and their glossary entries. The public-export rules follow
  too: they drop the owner-line rewrite the source no longer needs, require
  the root `LICENSE`, `NOTICE`, `SECURITY.md` and `CODE_OF_CONDUCT.md` to
  exist, and stop allowing the `.com` address that lived only in the replaced
  license files; the publication runbook's license step now records the ruling
  instead of offering a choice.
- **The documentation corpus's classification ledger moved to
  `docs/s0ma_src/` (beta-prep-5-front-door)** — the ledger and its human
  summary are now `docs/s0ma_src/doc-classification.json` and
  `docs/s0ma_src/doc-classification.md`, beside the document catalog and every
  other input the documentation gates read. They were under `plans/notes/`,
  which is a directory of working notes the public export withholds — a gate
  input on the wrong side of an exclusion, kept reachable by two special
  rescue rules. [Adding a
  document](docs/operations/docs-maintenance.md#a-document) names the new path
  at step 3; the ledger's own row followed it, and the three test modules that
  read it now read it directly instead of skipping when the working notes are
  absent. Nothing about what the ledger says changed.
- **The trust model, the uninstall page and troubleshooting catch up with the
  second way in (beta-prep-5-front-door B3)** — [what s0ma
  trusts](docs/trust-model.md) gains one complete table of **every** connection
  any part of s0ma can make or accept: the launcher's four requests, uv's
  dependency resolution during an install, the keyed installer, the four
  feedback requests, the loopback viewer, the authoring server that opens no
  socket at all, the optional HTTP view that s0ma binds nowhere, and the
  commands that connect to nothing — each with its host, its exact headers and
  body, when it happens, how often, who starts it, how to stop it, and the test
  that proves the row. Beside it: a "what never happens" list where every "no"
  names the thing that keeps it, and the first written account of the **opt-in
  local agent-tool log** (`S0MA_MCP_TELEMETRY`) — off by default, never leaving
  the machine, and holding each call's arguments **unredacted** with nothing
  pruning it. [Removing s0ma](docs/uninstall.md) now covers every way s0ma can
  be on a machine, in the order to take them off: the Claude Code plugin, the
  Claude Desktop extension, another agent's registration, a project's own
  environment, what s0ma generated, the project's own `[tool.s0ma]` and
  `.s0ma-version` (a change to the project, not to your machine — said plainly),
  and the folder in your home directory item by item, with what deleting each
  one costs; its "holds four things" sentence, true of an earlier release and
  wrong since the launcher arrived, is replaced by the eleven things actually
  there. [Troubleshooting](docs/troubleshooting.md) gains the four things the
  new route makes people ask: "there is nothing newer" when there is (the
  once-a-day record, and `update --check` to ask now), a refused key (where it
  goes, and never into a conversation), `s0ma-launch` not found in your own
  terminal (the plugin puts it on Claude's path, deliberately, not yours), and
  Claude reporting that the s0ma server failed to start (uv invisible to a
  desktop-launched app, and the one setting that fixes it).
- **The version-currency gate now covers the pages people actually read
  (beta-prep-5-front-door B3)** — `docs-version-currency` held twelve documents
  to "no stale s0ma version numbers", which left the trust model, uninstall,
  troubleshooting, stability, all six guides, the first-project journey,
  `SECURITY.md`, `CODE_OF_CONDUCT.md`, the pull-request template, the two
  contributor pages about the documentation machinery, and the plugin's six
  skill files entirely unchecked. All twenty-two are now scanned (thirty-four
  documents, thirty version references). Six references needed recording as
  deliberately historical, each with its reason: a frozen contract's own file
  name, the DSL language spec's file name, a field dated to the release that
  removed it, and the `version:` line of the reader's own module in two worked
  examples. No stale reference was found.
- **The root `README.md` is rewritten for someone who has never heard of s0ma
  (beta-prep-5-front-door B2)** — the hand-written sections are reordered and
  rewritten so a newcomer learns, in order: what s0ma is and who it is for; the
  three ways in, each as one link to the single page that describes it, plus
  the retrofit path for a codebase that already exists; that this is a public
  beta, pre-1.0, with the stability statement one click away; whether s0ma is
  for them, with the honest "probably not, if" moved above the fold from where
  it was buried; how it works, in a paragraph and one complete module copied
  from the first-project journey (the previous example was shorter and did not
  compile — it omitted semantically required fields, and `s0ma transpile`
  refuses it); the four packages with the licenses they carry today and
  studi0's "early preview — more coming" label; what the beta is and that
  feedback, which you read and approve before anything is sent, is the point
  of one; how stable the 0.x series is; and how to contribute, report a
  security problem, and behave. The pre-monorepo migration section moves
  behind a link to the migration guide that already holds all of it, leaving
  one line naming the two frozen repositories. The two generated regions (the
  getting-started journey and the served MCP surface) move as sealed blocks
  and are byte-identical; the `## License` block's pinned wording, the
  `#license` anchor `CONTRIBUTING.md` links to, the "Install" section
  `docs/walkthrough.md` and the core user guide point at, and the
  version-bearing sites `docs/RELEASING.md` step 2 tells a releaser to update
  are all unchanged. `docs/getting-started.md`'s package sentence gains the
  same studi0 label and says that the licenses named are today's.
- **`s0ma verify`'s text output is one line per file, with the explanation said
  once (beta-prep-5 B4)** — on a freshly-adopted codebase every `UNKNOWN` row
  was followed by the same ~190-character remediation, so on the standard
  brownfield fixture one sentence arrived nine times, wrapped mid-word on a
  normal terminal, and pushed the counts that matter off the bottom of the
  screen. An explanation that would otherwise be identical on every row of a
  status is now printed once, as a note between the list and the summary, and
  `UNKNOWN`'s note is written for the reader rather than lifted from the row:
  what the files are, that the backlog is not a fault, and the two ways out.
  Statuses whose rows say genuinely different things are untouched —
  `ADOPTED_DRIFT` names the file in its remediation and `PACKAGE_MARKER` has
  two classification reasons, so each keeps its own. Notes wrap with backticked
  commands and hyphenated words held together, so nothing a reader might retype
  straddles a line break. **`--format json` is unchanged**: every row still
  carries its own `detail`, spelled exactly as before, and the exit codes are
  the same. This is the shape the retrofit journey already promised ("One line
  per file … and the counts underneath") and the screen the retrofit demo
  recording shows.
- **`s0ma-dsl` is now Apache-2.0 (owner decision 2026-09-17)** — the language,
  the compiler, and the `s0ma` CLI join `s0ma-core` under the Apache License
  2.0; releases up to and including 0.18.1 remain under the license they
  shipped with. The wheel metadata (`license`, classifier), the bundled
  `LICENSE`, the package and root READMEs, the getting-started guide and its
  served copy, `AGENTS.md`, `CONTRIBUTING.md`, the generated package
  reference, and the wheel-smoke and contract-acceptance license checks all
  move together, as the agent contract requires. PRD v1.11 records the
  decision: NFR-8 now names each distribution's license separately, and §7.5
  gains a scope note — activation applies to `s0ma-mcp` and the hosted
  convenience channel, not to the language or the CLI. `s0ma-mcp` and
  `s0ma-studi0` are unchanged.
- **The walkthrough is agent-agnostic, and studi0 says "graph document" where
  it used to say the wire word (doc-function-1 G6, owner ruling OP-8)** — two
  halves of one decision about whose words the product speaks in.
  `docs/walkthrough.md` no longer assumes one agent host: the spine is now the
  generic mechanism (a stdio MCP server registered wherever your host keeps
  servers; the standing rules in the project's agent-instructions file, which
  is `AGENTS.md` and which `s0ma new project` already writes for you, with the
  one-line `CLAUDE.md` that imports it named as the pointer it is), and Claude
  Code appears only as the worked example where a concrete command genuinely
  exists there — the `claude mcp add` registration the installer and
  `s0ma doctor` themselves print, `/mcp`, and slash-command prompt surfacing.
  July's DOC-5 finding — the walkthrough teaching a CLAUDE.md standing block
  against the shipped AGENTS.md-canonical scaffold — is closed. In s0ma-studi0,
  the seven declaration intents that called the served graph a "payload" now
  name what it is: the **graph document**, the vocabulary the package already
  used for that object (`graph_document`, `GRAPH_DOCUMENT_KEYS`,
  `CARRIED_GRAPH_SCHEMA`), and the narration window's own block. The word is
  gone from every authored `.s0ma` prose field in the package.
- **BREAKING (s0ma-studi0): the exported nerve `compute_payload` is renamed
  `read_graph`** (owner-accepted API break, OP-8). It computes nothing — it
  reads a project's full `s0ma-graph@2` graph document through
  `s0ma_dsl.graph_export` and answers `None` when nothing is built — and
  `compute` was the only abstract verb in studi0's twenty-nerve public
  surface, beside siblings named `read_snapshot` and `read_narrations`. It is
  a watch-loop read behind `refresh_session`, named by no route-table entry,
  so **no HTTP contract, wire schema, or served document changes**; `/api/graph`
  and `/api/state` are byte-identical. Anything importing
  `s0ma_studi0.studi0_state.compute_payload` must import `read_graph` instead.
- **The self-prompt card's byte ceiling is raised from 1,800 to 2,600
  (doc-function-1 F-3, owner-ratified; ADR-001 amended)** — every build emits a
  bounded `self_prompt_card.md`, and at 1,800 bytes the bound had started
  hiding things rather than merely bounding them. This repo's own `s0ma-mcp`
  package reached 78 components, of which the card rendered 66 plus an exact
  omission count; among the 12 it dropped was the nerve behind `learn_s0ma`,
  the tool an agent reads the documentation with. The renderer was doing its
  job honestly — the budget was simply too small for a real inventory, and a
  too-small budget drops whatever sorts last, not whatever matters least.
  2,600 is sized from the measurement rather than picked for roundness: the
  `s0ma-mcp` card now renders complete at 2,558 bytes, all 78 components
  listed, with its authored-intent samples back. The 240-word ceiling is
  unchanged and was never the binding constraint (that card is 110 words), and
  cards that still cannot fit degrade exactly as before. Your rebuilt projects
  will emit a larger card, and the dogfood suite now asserts completeness
  unconditionally, so a future overflow of this package is a red test and a
  deliberate budget decision instead of a silent truncation.

### Fixed

- **A hand-edited generated file is refused on every build, not only when
  the source changed (owner rulings 2026-09-29)** — `s0ma build` refuses to
  overwrite a hand edit to a generated `.py` (`GENERATED_FILE_DRIFT`), but a
  rebuild of an unchanged source was a cache hit, and a hit reported the
  build directory's files without looking at them: the edit survived, the
  build exited 0 calling the module "unchanged — kept from the last build,
  not rewritten", `s0ma verify` said `EDITED`, and only `--no-cache` or an
  edited source reached the refusal. The answer depended on whether
  `.s0ma.cache/` existed, which the language specification says it never
  may, and three messages promised what no build did: `s0ma check`'s
  warning said "the next `s0ma build` overwrites this file" (without
  `--force`, no path does), `s0ma verify` closed with "Run `s0ma build` to
  re-transpile", and both commands' headline said generated files "are
  overwritten on every build". A cache hit now also needs the published
  `.py`, `.s0ma.json` and `.s0ma.map` to be byte-identical to the cache's
  copies; anything else is a miss, and the build's write-guard decides the
  same way on every path. The guard in turn refuses only when overwriting
  would lose something: an edit moved into the `.s0ma` source reappears in
  the regenerated file, which then differs from the hand-edited one only in
  its two hash lines, so "move the change into the source, then build" — the
  refusal's own first remedy, and the drift-recovery guide's — now works
  without `--force`, where it used to be refused too. `check` and `build`
  now say one sentence ("… was edited by hand; a build will not overwrite it
  until the .s0ma source says the same thing …"), `check`'s remediation names
  `s0ma build --force` as the way to discard, and `verify` names both ways
  out for edited files and keeps "re-transpile" for stale ones. The same
  miss rule mends three smaller faults on the cache path: a deleted
  published `.s0ma.json` crashed the next build; a deleted published `.py`
  was written again but reported as "kept"; and an earlier build's `.py` put
  back over the current one was kept, stale, and classified `CLEAN`. A
  project with no `[tool.s0ma]` now lists the files beside its sources on a
  cache hit, not the cache's internal copies. Behavior change: after a hand
  edit to generated code, a rebuild exits 1 until the edit is moved into the
  source or discarded with `--force`. `docs/guides/drift-recovery.md`, its
  evidence, and the error-code description behind the generated reference
  pages say the same.
- **The public-export tool re-runs the documentation loop with all five
  mirrors** — the loop gained two copies on 2026-09-29 (the quick reference's
  page and its data twin, into the mcp package, which serves them), and the
  tool that rebuilds the exported tree still made only the three older ones.
  Inside an export the snapshot digest moves, because the private planning
  rows are stripped; the quick reference carries that digest; so the two
  stale copies failed the wheel-identity checks in three stages, and the
  rehearsal of 2026-09-30 was NOT VALID although every gate in the checkout
  was green. The tool now names the five pairs once, and its test module
  compares them with the `cp` lines of `docs/operations/docs-maintenance.md`,
  so a mirror the loop gains is a red test rather than a failed rehearsal.
- **The survival card's minimal module passes `s0ma check` again** —
  since 0.14.0 every line the field table marks as required has to be
  written, as a value or as `none`, and leaving one out is
  `SEMANTIC_REQUIRED_STATE_OMITTED`. Two documents agents are pointed at still
  showed the older form, in which such lines were simply left out. The
  survival card (`s0ma://guide/survival-card`, the page an agent is told to
  read first and keep in context) printed a "minimal valid module" that the
  check refused, first on `uses:`; it now carries the five module-header lines
  and the eleven nerve lines it was missing, each as `none`, with one sentence
  saying why, and passes `s0ma check --mode strict` exactly as printed. The
  card grows from 2,829 to 3,378 bytes, inside its 4,096-byte release gate.
  The long quick reference made the same mistake in its declaration
  templates, marking required lines `# optional`; it is retired in this
  release (see Changed), and the generated quick reference now served at
  `s0ma://guide/quick-reference` reads every line from the check's own
  table, so it cannot show the older form.
- **The `# s0ma:` line above each generated body names the line the body
  starts on** — the pointer `s0ma build` writes above each nerve, ganglion,
  helper, test and `@component` cell body (`# s0ma: src/greeter.s0ma:32
  (nerve greet)`) named the line after the `def`: its docstring, or its second
  line. The `.s0ma.map` was wrong by the same amount — its `body_source`
  ranges, and so `resolve_output_line`, which follows a line of generated
  Python back to the line you wrote. Both inherited it from the parser, which
  ended each declaration on the line before the next one began, usually the
  blank line between them, and ended the last declaration of a file one line
  past the end of the file. So the error was one line in the usual layout, but
  in general as many lines as there were blank lines after the declaration,
  and none only for the last declaration of a file with no final newline. A
  declaration now ends on its last line of text — its last body line when it
  has a body. That same number is each declaration's `location` in the IR
  (`.s0ma.json`), each `source` range in the map (the module header's too) and
  the source span a documentation registration records, so the `content_hash`
  stamped on a rendered document moves with it; all of them now name the
  right line, and nothing changes shape. In the three builds this repository
  commits — the two self-hosted packages and the documentation application —
  every pointer was one line late — 129 of 129, counting the quick
  reference's new resource, built the same evening — and the rebuilt
  `_built/` trees differ from the old ones only in these line numbers and the
  fingerprints that cover them. The source-map tests had checked the map against itself —
  a pointer against `body_source`, the resolver against the pointer — which a
  range late by a constant amount passes; the new tests read the lines of the
  `.s0ma` file that the map names, in five layouts. The first build after
  upgrading writes the corrected numbers even where nothing else changed,
  because a cache an earlier version filled is no longer reused (next entry).
- **A build no longer replays what an earlier version of s0ma wrote** — the
  build cache (`.s0ma.cache/`) was keyed on a module's source text and the
  files it embeds, so after an upgrade every unchanged module was a cache hit:
  its `.py`, IR and source map came back exactly as the old transpiler wrote
  them, while `build.s0ma.json` recorded the new version as their
  `transpiler_version`. A fix to what the build writes — the pointer fix above
  is one — stayed invisible until the source changed or someone ran
  `s0ma build --clean`. The key now also holds the version of s0ma-dsl that
  wrote the entry, the same version the manifest records and the one the
  derived-surface cache already keyed on, so the first build after an upgrade
  rebuilds every module once and the cache is reused as before from then on.
  Entries written before this change miss as well. Found by the July codebase
  review (BLD-3) and confirmed here: a cache warmed by 0.18.1 made the fixed
  transpiler write the old, late pointer until the cache was cleared.
- **`s0ma verify` prints forward-slashed paths on Windows, like every other
  command** — the `file` of each row (`CLEAN`, `ADOPTED`, `CONVERTED`,
  `UNKNOWN`, `BOOTSTRAP`, `PACKAGE_MARKER` and the drift rows), in the text
  output and in `--format json` alike, was built with the host's own
  separator, so on Windows it read `src\bookshelf\__init__.py` where every
  other command, and every committed transcript, says
  `src/bookshelf/__init__.py` (NFR-7). All ten sites now go through the same
  display helper `s0ma build` and `s0ma check` use; on macOS and Linux nothing
  changes. Found by the first CI run this branch ever had — CI only runs on
  `main` and on pull requests to it, so ninety-odd commits had been gated on
  one Mac — where the retrofit journey's replay is the first evidence to quote
  a `verify --all` row and failed on it on both Windows cells. The same run
  found two tests that were wrong about Windows rather than the product: the
  launcher's `uv`-discovery test simulated a POSIX host while the host's own
  `which` was deciding (it now spells the file the way the host does), and the
  public-export tool's test module ran on a platform the tool itself refuses
  to start on (the module now skips there, in the tool's own words).
- **Four things the retrofit said that were not quite true
  (beta-prep-1-retrofit)** — found by a second unaided-agent trial, which
  passed. A clean `s0ma adopt verify-parity` verdict said to put the alias
  lines "at the top of" the package's `__init__.py`; most open with a
  docstring and a `from __future__` import, which Python requires to come
  first, so following that sentence to the letter wrote a syntax error into
  the one step where the application is briefly unable to import itself. It
  now says below the docstring and any `from __future__` line, above the
  package's own imports, and the document form carries the same words as a
  field. `ADOPT_PLACEHOLDER_INTENT` fires on every un-authored field but
  always closed with advice written for an `intent:`; the closing clause is
  now the field's own, read from the sentences `s0ma adopt draft` writes into
  the file, so a `schema:` is no longer answered with the wrong question. The
  `s0ma adopt init` note about version control talked about the build
  directory as though it were there, four commands before anything is built,
  and now says it is not yet — the two lines to copy into `.gitignore` are
  unchanged. And `s0ma adopt status` closed by naming
  `journey:retrofit-existing-codebase` while the `AGENTS.md` block the same
  family writes names `doc:guide/retrofit-existing-codebase`, leaving a
  reader with two ids and no way to tell which was "the guide"; both surfaces
  now name the guide, which is the page a person reads.
- **`s0ma docs` now answers from an installed toolchain (beta-prep-5 B6)** —
  `s0ma docs`, `s0ma docs list`, `s0ma docs show …` and `s0ma docs search …`
  have never worked anywhere but inside a clone of the s0ma source tree.
  Installed from the release wheels they all stopped with "no documentation
  snapshot was found", which is every route the product points people down:
  `s0ma --help`, `s0ma adopt init`, `s0ma adopt status`, and the block `adopt
  init` writes into a retrofitted repository all name `s0ma docs show`. The
  composed snapshot was being shipped in the `s0ma-mcp` wheel, where the
  authoring server reads it, and as a teaching slice in `s0ma-core`; the
  `s0ma-dsl` wheel — the one carrying the command line — carried none, and the
  loader that reads it looked in a place nothing ever filled. It is filled now:
  the snapshot ships at `s0ma_dsl/_docs_snapshot/s0ma-docs-model.json` and the
  four commands answer offline, with no clone, from any directory. A checkout
  still wins inside a checkout, so a contributor keeps being answered about the
  tree they are standing in; the first line of every answer says which, ending
  in `(installed)` or `(checkout)`. Three things now keep it that way: the
  documentation loop has a third `cp` and every page that teaches it says so, a
  drift gate holds the new copy byte-identical to the composed artifact and to
  the `s0ma-mcp` wheel's copy of the same snapshot, and the release-integrity
  stage installs the wheels cold, outside any checkout, and runs all four
  commands. The message you get when there really is no documentation was
  rewritten too: it now names the two situations that can still produce it — a
  development install run from outside its own tree, or an incomplete
  installation — and the way out of each. `docs/troubleshooting.md` carries the
  matching entry.
- **Retrofitting a repository that is not one package under `src/`
  (beta-prep-1-retrofit G3a)** — the first pilot against a real codebase found
  that the `s0ma adopt` family assumed the shape of the fixture it was built
  against, and that the first command that writes anything refused the
  perimeter its own scan had proposed. Eight fixes, all under the same command
  lines. **`--source-root` now scopes the scan:** the directories you name are
  the only ones read as your code, and everything else is counted and named by
  directory in one line (`840 other Python files are outside them and not in
  this scan: fixtures/ 632, samples/ 208`) instead of being censused as work
  you never asked for. **`s0ma adopt init` writes the perimeter you asked
  for:** the roots are decided before anything is discovered rather than
  re-derived from where the files turned out to be, so the project directory is
  never added silently beside the packages you named — the pair that made the
  command refuse itself with advice nobody could follow. **A tree with several
  packages side by side is now understood:** when nothing has been declared,
  the scan proposes those packages by name, from evidence the project already
  wrote (the packages its `pyproject.toml` declares, the entry points it names,
  and which of them import each other), says in one sentence why, and falls
  back to reading the whole directory when the evidence is thin. A directory of
  sample applications or reference solutions is input, not source, and is
  counted rather than converted. **`--dry-run` tells the truth:** it renders the
  same table into a temporary directory and loads it there, so it refuses
  wherever the real run would refuse, and still writes nothing inside the
  project. **Test directories are declared:** where a project keeps its tests
  outside the source roots, `test_roots` now names them, so a test suite stops
  counting as code waiting to be converted; the flat-tree `test_roots = []`
  stays, and its comment now says what it costs. **The counts agree:** `s0ma
  adopt status` counts the perimeter, which is what `s0ma score` and `s0ma
  verify` count — on the pilot's repository it said 455 modules where the other
  two said 30 — and the scan's headline is reconciled with its own
  classification block in the text as well as the JSON. **A file declared as an
  entry point is no longer also listed for conversion**, and the screen says in
  one line that it stays plain Python. **The agent-facing JSON is
  proportionate:** on the pilot's repository `--format json` went from 5.8 MB to
  328 KB, and the whole scan from 2.9 s to 0.4 s. A module's dotted name is
  unchanged by any of this — a source root that is itself a package contributes
  its own name, so `harness/runner.py` is `harness.runner` however the
  perimeter is written, and the import graph and conversion order hold.
- **The conversion loop tells the truth about what is left to do
  (beta-prep-1-retrofit G3b)** — an unaided agent converted a module with
  nothing but the guide's card, and a pilot converted one in a real
  four-package repository; between them they found that the dangerous step of
  the ladder — deleting the Python file — was the one step the tooling said
  least about, and that the retrofit's own files could break the toolchain
  around it. **A clean `s0ma adopt verify-parity` verdict now ends with the
  three things that finish a conversion**, computed for the project in front
  of you rather than cited from a document: the exact lines that point the
  module's old dotted name at the built module (the package's `__init__.py`,
  how far the build directory sits above it — a `src/` layout and a flat one
  need different numbers, and the pilot had to work its own out by hand — the
  flat name the build gave the module and the two bindings a caller can reach
  it by), that `s0ma-core` and `s0ma-dsl` have to be declared in
  `[project].dependencies` and installed where the application runs, and that
  the build directory is imported at run time now and has to ship. It teaches
  the order that makes the step safe: alias first, run your tests with the
  original still there and check which file was imported, delete last. `s0ma
  adopt status` carries the same facts at the rung they matter, and both
  `--format json` forms carry them as fields (`before_you_delete`, additive
  under the existing schemas). **`s0ma verify` no longer calls a converted
  source root hollow:** a `.s0ma` source whose build is in the manifest reads
  as `CONVERTED` with the path it was built to, so `s0ma adopt status`,
  `s0ma score` and `s0ma verify` report the same number of converted modules —
  and a reading that covers both the source and the build directory still
  counts each module once. **`s0ma doctor` defers to the ladder:** a project
  mid-retrofit is told "`s0ma adopt status` has the next command" instead of
  being sent to create its first module in a `src` directory it may not have.
  **`s0ma build` runs bare**, building the project you are standing in — every
  source root it declares, the same set `s0ma check` reads — so every refusal
  that names it now prints a command somebody can run. **`s0ma adopt draft`
  writes into the module's own package** rather than the first configured
  source root, which on a multi-package repository put the draft in the wrong
  package and made `adopt status` count one module twice. **The parity
  baseline no longer breaks `s0ma verify`:** `adopt-baseline.s0ma.json` is one
  of the toolchain's own records, and the reader that walks `*.s0ma.json`
  files now knows it (it was refused as canonical IR with a schema error on
  any project whose source root holds the project root). Also: a build that
  reuses an unchanged module lists the file you can import rather than the
  copy in its cache, and says how many were kept; `s0ma adopt init` closes by
  saying which of s0ma's files belong in version control and which two lines
  belong in `.gitignore`, and still writes no `.gitignore` of its own; a
  draft's notes now open with the one rule for writing a field (double quotes,
  no escapes) and its layer placeholder says which way the layer rule points,
  so choosing a layer is a derivation rather than a guess; the
  `HOST_RUNTIME_UNDECLARED` remediation says that declaring the runtime is
  what clears it and that installing it where the application runs is a
  separate matter `s0ma verify-host` exists to prove; and a draft's note about
  comments it could not carry agrees in number.
- **The `AGENTS.md` block `s0ma adopt init` writes can no longer name a command
  that does not exist (beta-prep-1-retrofit)** — for a while its last rule
  ended "when you are not sure what to do next, run `s0ma adopt status`" before
  that command was built. The block is written once into somebody else's
  repository, carries no publication date and is read by agents that simply
  run what they find, so a planned command reaches that reader as a broken
  instruction with nothing to date it against. `adopt status` has since
  landed, so the sentence stays — one command that says which rung the project
  is on and what to run next beats two that leave the reader to work it out —
  and what changed is the guard: a test reads every command back out of the
  rendered block and walks it down the live CLI parser (it fails on the old
  state), alongside the one that parses each command as written, so no future
  edit can put an unbuilt command into a user's repository.
- **Docs corrections (doc-function-1 A1)** — `CONTRIBUTING.md` and `AGENTS.md`
  now describe all four packages (tree, dependency line, four suites, the
  self-host rule for both self-hosted packages, and the license split); the
  studi0, dsl, and core README version/status claims corrected — including the
  studi0 README's failing `0.15.1` install command (now version-agnostic) and
  core's "0.2.0 … Complete" status block; core README gains its stack position,
  root/PRD links, and monorepo-correct install and self-check commands.
- **Docs corrections (doc-function-1 A2)** — the MCP prompts are counted as
  five everywhere (`feedback` was missing from the walkthrough, user guide, and
  the wheel-shipped quick reference + its `_docs` mirror); `RELEASING.md`'s
  owner-runbook link points at the right section with a live anchor;
  `editors/README.md` ground truth moved to the current spec;
  core `architecture.md`'s false "auto-generated" header replaced with an
  honest hand-maintained status line; the mcp README's hand-written self-model
  sample is marked illustrative with its count corrected to the live value.
- **Docs filing and framing (doc-function-1 A3)** — dsl ADR-004 marked
  Superseded (reversed by the 0.5.0 monorepo consolidation); the 0.15
  runtime-free-emission design note carries its dated outcome; both legacy
  package `plans/TODO.md`s wear unmistakable fossil banners; two historical
  feedback logs moved under their packages' `docs/historical/` with pointer
  stubs; the no-PyPI rationale is told one way (PRD NFR-8) across README and
  walkthrough; `getting-started.md` routes testers to the hosting guide
  instead of a private-repo URL.
- **`s0ma docs verify` resolves its base like its siblings, and `runs_in`
  is validated at parse time (doc-function-1 A8)** — `verify` gains
  `--output-dir` and now resolves through the same base-resolution path as
  `render`/`check-drift` (previously a project-form invocation verified
  against a different directory than it rendered to); an example's
  `runs_in` value is checked against the three modes the spec declares
  (`standalone | pytest | integration`) with a source-located parse error,
  instead of surfacing as a runtime failure when the example is executed.

## [0.18.1] — 2026-08-28

### Changed

- **Sending feedback by hand is now two keystrokes, not ten questions**
  (owner follow-up F-1 from the 0.18.0 live-fire): `s0ma feedback -m "..."`
  goes straight to the preview — category and impact default to
  `other`/`minor`, overridable with the new `-c`/`-i` flags — and the full
  interactive compose accepts Enter for both menus and folds the four
  optional prompts behind one "Add more detail? [y/N]" question. The raw
  JSON preview is replaced by a plain-language card that renders the exact
  feedback data completely — every field including the install context and
  what redaction removed, an unexpected field can never hide, and a new
  guard makes it impossible to add an envelope field without card copy —
  ending in the fingerprint computed from the precise bytes that travel.
  The verbatim `Send exactly this feedback data? [y/N]`, the contact
  question, draft-before-send safety, exit codes, and the no-`--yes` rule
  are all unchanged and still pinned by tests.

### Fixed

- **The R2 mirror can no longer mistake a failed manifest read for an empty
  bucket** (follow-up F-2): `r2_get` now dies loudly — naming the real
  stderr — on any read failure that is not R2's own "specified key does not
  exist", so a transient network or auth error can never make the guard
  reason "fresh bucket, nothing to protect" and merge away the served
  version history. Genuine absence still takes the fresh-bucket path, and a
  faked-wrangler test pins both classifications.

- **The installer now survives being run inside someone else's Python
  workspace** (`uv init --no-workspace`): run from within any existing uv
  workspace — a tester's own project, or even a s0ma checkout — `uv init`
  used to JOIN that workspace, and installing the wheels then failed with
  "Workspace dependency `s0ma-core` must refer to local directory, not a
  file" because the wheel's name collides with a workspace member. The
  scaffolded project now always stands alone, wherever the one-liner is
  run. Found live during the 0.18.0 release proof — the feedback loop's
  first catch, before the first tester.

## [0.18.0] — 2026-08-28

### Added

- **The R2 mirror verifies before it trusts (re-run integrity):** on a
  re-run of an already-mirrored version, `scripts/mirror_to_r2.sh` now
  fetches each `dist/<version>/` wheel back from R2 and compares sha256
  against the local wheels — a missing or byte-different object ABORTS
  before the manifest is touched, because the manifest must describe the
  exact bytes R2 serves or install-time verification hard-fails that
  version for every user. A pre-studi0 three-wheel mirror surfaces as a
  missing fourth object instead of a silent skip. Deliberate artifact
  replacement is explicit: `--force-overwrite` rewrites all four wheel
  objects together with the manifest. (Landed from a July hardening
  draft — review INF-2 — adapted to the four-package release; its
  worktree is retired.)

- **Cutting a release is one reviewable command** (`scripts/release_cut.sh`,
  `make release-cut VERSION=X.Y.Z`): dry-run by default and preflighted
  (clean tree, on `main`, strictly-greater lockstep version, non-empty
  `[Unreleased]`, changelog mirror in sync), it bumps the four lockstep
  manifests, carves `[Unreleased]` into a dated heading in this changelog AND
  its served mirror, refreshes the lockfile, and prints — never runs — the
  commit/tag/push commands, because pushing a `v*` tag is the release act
  (owner-authorized only).

- **Living docs can no longer go version-stale silently** — new gate stage
  `docs-version-currency` (`scripts/check_version_refs.py`): every s0ma
  version string in the six living docs must be the current lockstep version
  or carry a justified allowlist entry (unknown `0.N.M` strings are treated
  as s0ma versions unless provably third-party, so nothing slips through on
  missing keywords). The sweep fixed the stragglers it caught — stale
  `0.15.1` wheel-filename examples, the hosting doc naming three wheels
  under "the four released wheels", a five-not-four studi0 module count in
  the release runbook — and made prose version-agnostic where nothing
  load-bearing is lost.

- **The feedback journey is served and scaffolded**: the `feedback` MCP
  prompt joins the server (its fifth prompt — `/mcp__s0ma__feedback` in
  Claude Code) carrying the seven-step journey; the server instructions
  gain the recognition rule — explicit intent only, confirm it is about
  s0ma when the user never named it, never submit without the approval
  interaction, never read frustration as consent; suggest-mode offers are
  served per render only where the project's `[tool.s0ma]` table says
  `feedback = "suggest"` (new projects scaffold exactly that, disclosed in
  the scaffold summary; `"off"` silences offers while every explicit route
  keeps working); and `s0ma new project` also writes the `/s0ma-feedback`
  Claude Code skill (created if absent, listed in both scaffold summaries,
  never part of the atomic-refusal set). The self-prompt card renderer no
  longer emits an empty samples heading when nothing fits, and one
  resources intent was tightened by eight characters so the flagship card
  keeps a rendered authored-intent sample (surface-budget contract R2
  records the ruling).

- **Installing s0ma now sets up feedback in the same breath** (non-fatal
  and skippable): after the doctor step, the keyed installer exchanges the
  license key for this machine's scoped feedback access and stores it at
  `~/.s0ma/feedback-token` (0600; only the 12-character prefix is ever
  printed; `--no-feedback` skips the step; any failure leaves the install
  green with a one-line pointer at `s0ma feedback enroll`). The hosting
  smoke asserts the enrollment end to end — and stashes/restores any real
  token it would displace. Tester docs gain a "Sending feedback" section —
  the four routes in order, the exact-approval promise, pseudonymous-not-
  anonymous language, per-report contact opt-in, deletion by receipt id —
  and every "nothing phones home" claim is reworded to the NFR-6 v1.9
  truth. The control plane's served installer copy is re-synced
  byte-for-byte, drift note preserved.

- **`s0ma feedback` ships** — the universal, agent-independent path:
  interactive compose in plain language, the exact redacted feedback data
  previewed before the verbatim `Send exactly this feedback data? [y/N]`,
  drafts that survive any failure with their idempotency key (`drafts` /
  `submit <draft-id>` resume safely), `list` (server-backed; offline falls
  back to this machine's receipts log, labeled as such), `delete` that
  deletes nothing without an id — and `delete --all` only after a previewed,
  explicit `Delete all N feedback reports? [y/N]`, stopping gracefully at
  the rate ceiling with when-to-retry — plus `enroll` for the one-time
  account connection. Five frozen exit codes; server remediations surfaced
  verbatim; no jargon anywhere in user-facing copy.

- **The agent can now carry your feedback — with you holding the pen**
  (`prepare_feedback` + `submit_feedback`, authored in the DSL like every
  other tool on the server): prepare is pure — build, redact, fingerprint,
  nothing saved or sent; submit shows the exact feedback data in a
  client-rendered approval form (MCP elicitation) with the contact
  question, sends only on accept, saves a local draft on decline/cancel or
  failure, and when the client cannot render an approval it refuses and
  points at `s0ma feedback` — an agent-supplied "approved" can never
  substitute, because the approval plumbing is injected by the server and
  unreachable from tool arguments. Claude Code additionally sees the
  always-ask flag. The served surface grows to exactly the contracted 14
  tools; the release-integrity cold probe now derives its expected surface
  from the snapshot instead of a hardcoded count, so the next deliberate
  surface change carries this gate with it.

- **The feedback transport ships** (`s0ma_dsl.feedback` gains drafts, the
  token store, and the HTTPS client — the engine's first and only
  network-touching module, invoked solely by explicit calls): local drafts
  with per-draft idempotency keys and 30-day expiry, the receipts log that
  makes `s0ma feedback list` work offline, the `~/.s0ma/feedback-token`
  store with env override and expiry-aware reads, one-time license-key →
  feedback-token enrollment (deliberately WITHOUT the installation pseudonym
  — sending it would let the control plane join pseudonym→account), and a
  client that builds the frozen submission wrapper, verifies receipt-hash
  continuity (a mismatched receipt is a failure, never "received"), never
  auto-retries, and surfaces server remediations verbatim.

- **`docs/RELEASING.md` now tells the truth** (rewritten for the activated
  pipeline): cut with `make release-cut`, the owner's tag push is the
  release act, CI builds → GitHub-Release record → forward-only R2 mirror →
  verify-served, control-plane deploys stay manual and only when the
  installer changed, rollback is the documented downgrade-mirror, and the
  two repo secrets are specified once each.

- **Releases now prove what prod actually serves** — `scripts/verify_served.sh`
  plus the `verify-served` CI job (runs after the R2 mirror on every tag once
  the `S0MA_SMOKE_KEY` secret exists): the manifest's resolved `latest` must
  be the tagged version, all four wheels must download and sha256-match both
  the manifest and the just-built artifacts, and the served installer is
  diffed against canon — installer drift is a loud notice (control-plane
  deploys stay manual by R10/R11) while every other mismatch is red. Distinct
  exit classes per failure kind; a fatal failure always outranks the
  non-fatal drift class; the smoke key never appears in any output.

- **The deterministic redactor ships** (`s0ma_dsl.feedback.redact`, profile
  v1): the ten ordered rules with stable placeholders (same value → same
  placeholder, pre-existing placeholders seed the counters), idempotent by
  construction, proven by a 66-record adversarial corpus — cloud keys, JWTs,
  PEM blocks, env-var secrets, emails, URLs and git remotes, paths in three
  OS conventions, stack traces, unicode edge cases — with a zero-residue
  property test; a 32 KB report redacts in ~6 ms. Building it re-froze
  contract rule 3 (r5): a variable named exactly its secret keyword
  (`PASSWORD=…`, `TOKEN=…`) is now caught by both the client redactor and
  the control-plane screen, and FD-1 deletion now blanks the denormalized
  summary at rest on both delete paths.

- **The feedback engine's foundation ships as `s0ma_dsl.feedback`** (FB-M4;
  deliberately no network code — that layer is a later milestone): the
  versioned envelope model with client-side caps and structured plain-voiced
  refusals, canonical serialization + hashing proven byte-identical to the
  control plane's (both sides assert the contract's cross-language test
  vector literally), the allow-listed context collector (typed constructors
  — a non-allow-listed key cannot be expressed), and the `~/.s0ma` state
  layer (0600/0700 best-effort, installation pseudonym create/rotate). The
  matching control-plane intake landed in the CP repo: submit / list-own /
  delete-own endpoints with idempotent receipts, keyed-HMAC reporter
  pseudonyms, entitlement-at-request, and rolling-window rate limits; the
  submission wrapper `s0ma-feedback-submission@1` is pinned in the contract
  (r3/r4) — hash continuity binds exactly the feedback data the user
  approved, never transport metadata.

- **The feedback trust contract is ratified and frozen** (release-pipeline +
  feedback plan, FB-M0): PRD v1.9 adds the FR-FB requirement family, the
  narrow NFR-6 feedback exception (explicitly user-invoked surfaces only,
  never load-bearing), and records the keyed-R2 beta distribution truth in
  NFR-8; `docs/contracts/feedback-v1.md` freezes the wire formats (envelope,
  receipt, a cross-language canonical-JSON hash test vector), the keyed-HMAC
  reporter identity model, redaction profile v1, and the user-facing voice
  rules ("feedback data", never "payload"); ADR-004 records the
  architecture; the 0.14.0 surface-budget contract gains revision R1
  authorizing exactly `prepare_feedback` + `submit_feedback` + the
  `feedback` prompt (12/12/4 → 14/12/5).

### Changed

- **The release workflow pins Wrangler v4** — the mirror script's `--remote`
  flags are v4-only; under v3 the unknown-flag error was swallowed into an
  empty manifest read, which the corrupt-manifest guard correctly refused
  before writing anything (this release's first firing proved the guard).

- **The R2 mirror's `latest` only moves forward** (release-pipeline plan
  RD-5): mirroring a version older than the one prod serves now aborts
  before anything is written — so a historical tag push can no longer
  silently downgrade every keyed install — and `--allow-latest-downgrade` is
  the deliberate, documented rollback path. The served manifest is fetched
  once up front (the guard runs before any wheel upload), a corrupt remote
  manifest aborts instead of dying mid-merge, and `--help` extraction is
  marker-based instead of a rotted hardcoded line range.

- **Four-package truthfulness sweep across the living docs:** the served
  `s0ma://meta/version` resource description now names all four
  distributions and the optional-viewer null semantics (a deliberate
  surface-snapshot regeneration — one line, owner-acked); README,
  AGENTS.md, getting-started (+ served mirror), walkthrough, and
  hosting-getting-started no longer say "three" where the toolchain has
  four packages, four wheels, and four suites. Historical records keep
  their wording.

- **The keyed installer ships all four wheels** (owner decision
  2026-08-17): `install.sh`'s install set gains `s0ma_studi0`, the
  hosting smoke asserts the four-wheel download, and the control-plane's
  served installer copies are synced to canon (deploy is the owner's
  manual step; prod takes effect together with the next R2 mirror push).
  Full local smoke: 32/32 — provision → key check → 4-wheel manifest →
  sha256-verified downloads → 4 wheels installed → `s0ma check` green.
- **PRD v1.7 + v1.8 applied** (owner ack 2026-08-17): FR-CORE-9 (the
  runtime bootstrap is core's, with the emitted-modules boundary named),
  FR-DSL-4 trimmed accordingly, INV-9 relocation note, and FR-STUDI0-10
  (narration re-enters by measurement, D-11-conditional, file transport,
  truth-language display, focus sync).
- **The release workflow's R2 mirror skips gracefully when unkeyed,
  instead of failing red:** `mirror-r2` now probes for the `CF_API_TOKEN`
  secret up front; while it is deliberately unset (today's manual-mirror
  posture) the wrangler install + R2 push are skipped with a loud
  `::notice` — the wheels were NOT mirrored, prod still serves the
  previous latest, and here is how to proceed — instead of failing the
  job on every tag, where a permanently-red job is indistinguishable
  from a genuinely broken mirror. The wheel build and the four-wheel
  assertion still run unconditionally, so a tag never stops proving the
  wheels build at the tag version; setting the secret later flips the
  job to auto-mirror with no further edit. Both call sites
  (`release.yml`, `mirror_to_r2.sh`) now also record the token type that
  actually works: a Cloudflare **User API Token** with `Account ->
  Workers R2 Storage -> Edit` — credentials minted by the R2 dashboard's
  "Manage R2 API Tokens" flow are S3-compatible and fail every
  `wrangler r2` REST call with 403 code 10000 while verifying as valid
  and active. Plan D-8's bucket-only scope is therefore not achievable
  through this code path; accepted (verified 2026-08-18, mirroring
  0.17.0) because `s0ma-dist` is the account's only R2 bucket. The
  `.wrangler/` cache a mirror run drops into the repo is now gitignored.

### Fixed

- **The last "three wheels" drift — in prose and, worse, in the test:**
  `install.sh` still said "three" in five strings (two printed during a
  real install) after the wheel set went to four; all are reworded
  count-agnostically, driven by `$WHEELS`, so the next wheel-set change
  cannot reintroduce the drift. The same sweep found
  `test_install_script.py` still pinning THREE stems — the fourth
  wheel's download and `uv add` presence were untested, so a dropped
  `s0ma_studi0` would have stayed green. The test now pins the four-stem
  set, derives its ordering assertion from that one tuple, and asserts
  exact counts, so an unreviewed addition fails as loudly as a dropped
  stem. Also swept: the walkthrough's Route A prose ("all three"
  directly above a four-wheel command; doctor reports every s0ma
  package), the hosting smoke's seed message (now counts
  `$WHEEL_STEMS`), and this changelog's own preamble (the lockstep
  sentence no longer enumerates a three-package set).

## [0.17.0] — 2026-08-17

### Added

- **Agent narration reaches sh0w — conditioned on studi0 actually watching
  (D-11).** The bench-measured winner (file transport + rules-injection,
  19:1 over an always-visible tool) is now mainline: while a studi0
  session is live on a project, the mcp survival rules gain ONE line
  (the spike's wording, frozen; 100% schema validity in every
  measurement. The mainline re-run narrated in 3/3 first-contact
  sessions; re-analysis showed the spike's 44% was ~61% delivery ×
  ~70% compliance — the delivery ceiling is the client truncating an
  oversized rules-bearing tool result, the documented tuning lever) asking the agent to append main-movement narration to
  `.s0ma/studi0/session.jsonl`; without studi0 the rules are
  byte-identical to before — no studi0, no narration, by owner
  principle. Presence = `.s0ma/studi0/active.json` (port + pid), written
  by `launch()` after bind, pid-guarded on removal, and probed per
  rules render with a stdlib liveness check (POSIX `os.kill(pid, 0)`;
  on Windows a ctypes `OpenProcess` probe — `os.kill` there would
  TERMINATE the probed process, a trap now documented in the helper). A
  dead-pid or malformed file is simply absent — narration is never
  served on stale evidence. The studi0 watcher tails the session log at
  its existing 750 ms cadence (torn trailing lines retried, byte-offset
  resume, shrunken files reset); `/api/state` gains a bounded
  `narration` surface (`s0ma-studi0-state@2`: last 50 entries + total +
  invalid counts) and `seq` advances on new narration. sh0w renders an
  agent-narration pane: newest first, phase chip, provenance sentence
  ("self-reported... not verified against the build"), invalid lines
  counted and named but never rendered, and focus sync (GP-2) — a
  narration whose `subjects` name a canonical id present in the graph
  selects that node through the same path as click-to-inspect; unknown
  ids move nothing and are labelled "not in this graph" (GP-3 silence).
  Keyboard-reachable, reduced-motion-safe, amber untouched (still means
  stale only). The MCP surface is unchanged (12 tools; snapshot
  byte-identical; self-prompt card untouched at 1789 bytes). studi0's
  write-boundary invariant is qualified, not broken: exactly one
  presence file under `.s0ma/studi0/`, never a source or build
  artifact, pinned by test.

## [0.16.2] — 2026-08-17

### Added

- **`s0ma.bootstrap` — the runtime loader lives in `s0ma-core` now.** A
  bench spike proved the blessed one-line bootstrap made deployed apps
  import the proprietary authoring package at runtime: in a venv without
  authoring packages, the documented wiring died with
  `ModuleNotFoundError: No module named 's0ma_dsl'` at app import — in
  tension with INV-9's "nothing a deployed system needs at import time
  or runtime may be gated". The manifest-driven loader
  (`bootstrap_imports`, `ManifestSchemaError`, the manifest schema
  constants) moves to stdlib-only `s0ma.bootstrap` in Apache-licensed
  `s0ma-core`; the blessed line everywhere — new-project templates, the
  emitted stub headers, the mcp and studi0 package bootstraps, every
  guide — is now `from s0ma.bootstrap import bootstrap_imports`. A
  core-only-venv regression test pins the loader's runtime-freedom
  permanently. Honest boundary, recorded in a second test: **emitted
  modules themselves still import `s0ma_dsl.runtime_bridge.
  registration`**, so a full core-only boot of built output arrives with
  the separate runtime-free-emission design round — that test fails
  with promotion instructions the day emission crosses the line.
  Dependency floors now tell the truth about the move: `s0ma-dsl`,
  `s0ma-mcp`, and `s0ma-studi0` all require `s0ma-core >= 0.16.2`.
- **Patterns guide §28.5: a shadow implementation is never the answer.**
  When the s0ma runtime cannot be deployed, the agent's job is to STOP
  and REPORT — never to maintain a parallel plain-Python implementation
  of a modeled component (that is the drift-prone duplication s0ma
  exists to abolish; an agent under acceptance pressure invented exactly
  this coping strategy during the spike).

### Deprecated

- **`s0ma_dsl.runtime.bootstrap_imports`** is a thin re-export of
  `s0ma.bootstrap.bootstrap_imports` and emits a `DeprecationWarning`
  naming the new path (INV-2: no silent rename — existing apps keep
  working with the identical signature). No removal is scheduled before
  the runtime-free-emission round lands.

### Fixed

- The hosting smoke's manifest step still pinned the pre-studi0 wheel
  count (`3`) — the one count its 0.16.1 four-package sweep missed; it
  now expects four manifest wheels. The installed-wheel count deliberately
  stays at the keyed installer's three-stem set, which is a live product
  decision. Caught by running the smoke end-to-end at 0.16.1 (32/32 now).

## [0.16.1] — 2026-08-17

### Added

- **Release integrity covers the fourth package** (cleanup wave, post-v1
  acceptance): the `selfhost-build` gate byte-compares `s0ma-studi0`'s
  committed build alongside `s0ma-mcp`'s (each package rebuilt `--no-cache`
  under its own declared mode — mcp `release`, studi0 `strict`); the wheel
  smoke builds and inspects the `s0ma-studi0` wheel (LicenseRef-Proprietary
  metadata, bundled LICENSE, wheel `_built/` payload equal to the committed
  tree, no `.s0ma.cache`/`s0ma_src`/`tests` inside); `s0ma doctor` lists
  `s0ma-studi0` in its versions block (absent renders as an `info` finding
  with the launch hint — never a warning, exit stays 0); and the root README
  gate/licensing prose now names all four packages.
- **`s0ma://meta/versions` reports the fourth distribution:** the mcp
  version resource's document gains `"s0ma_studi0"`, rendered live from
  `importlib.metadata` like its siblings and `null` when the optional
  leaf package is absent — the honest answer, since `s0ma-studi0` is
  discovered lazily and never required. Resource-list surface unchanged
  (12 tools; the surface snapshot is byte-identical).

### Fixed

- **Reserved ledgers are excluded from IR discovery** (`s0ma verify`
  broke on adopted projects): `adopted.s0ma.json` carries `schema`, not
  the canonical `schema_version`, and discovery fed it to the IR schema
  guard, hard-failing `UNSUPPORTED_IR_SCHEMA_MAJOR` on any project with
  adopted files (green at 0.13.0; broken by the 0.14/0.15 guard
  application; surfaced by a bench adoption ladder). `graph_export.
  discover_ir_files` — the one discovery implementation — now excludes
  both reserved ledgers (`build.s0ma.json`, `adopted.s0ma.json`), with a
  regression test.
- **The release train's own surfaces still assumed three packages** —
  a 0.16.0 release would have silently shipped without the `s0ma-studi0`
  wheel everywhere downstream of the build: the release workflow's INV-4
  tag guard and both built-asserts, the R2 mirror script's wheel stems
  and manifest, and the hosting smoke all enumerate four packages now.
  The hosting smoke also derives its version from the workspace instead
  of a hardcoded `0.9.0` (it could never pass at any newer version), and
  the wheel-license smoke is renamed `scripts/wheel_smoke.py` — it has
  covered all four wheels since the cleanup wave, and `wheel_smoke_mcp`
  under-described it. `docs/RELEASING.md` now records the four-package
  model and the complete verified bump surface (studi0's `.s0ma` module
  version headers and the two self-hosted rebuilds included).

## [0.16.0] — 2026-08-17

### Added

- **`s0ma graph` is now the single graph-export contract: `s0ma-graph@2`.**
  The aggregation logic moved from the CLI into
  `s0ma_dsl.graph_export.collect_graph()`; the JSON payload gains a `schema`
  field, `edges.verification`, and `integrations`, and — at the new
  `--detail full` — per-component records (verbatim `s0ma-ir@3` state
  wrappers), module records, and manifest-based `freshness`
  (`fresh`/`stale`/`missing` with `stale_modules`). The `@1` keys (`nodes`,
  `edges.authored`, `edges.derived`) and the `text`/`dot` formats are
  byte-compatible, and the target may now be a `[tool.s0ma]` project root
  (build dir resolved automatically). One mechanism for every consumer —
  CLI, tooling, and studi0 (FR-STUDI0-3).
- **New `s0ma studi0` subcommand and new `s0ma-studi0` package** (proprietary,
  lockstep-versioned; PRD v1.6 §7.6) — studi0, s0ma's visual development
  environment hosting the sh0w graph renderer. The subcommand discovers the
  package lazily and prints a structured install hint when absent (INV-6:
  `s0ma-dsl` gains no hard dependency). The package is self-hosted from day
  one: `.s0ma` sources, committed deterministic `_built/` output, and a
  single handwritten bootstrap exposing `launch()` — a loopback-only local
  server hosting **sh0w**, the graph renderer: deterministic layer-band /
  module-organ layout with click-to-inspect (state-wrapped fields projected
  honestly — "not declared" / visible "pending: <reason>" authoring debt);
  live refresh from a 750 ms artifact watcher with an honest `seq` and
  truthful `fresh`/`stale`/`missing` semantics; amber-plus-text stale marking
  with a factual banner; a ~4 s materialize/highlight beat on canonical
  deltas (every transition perceivable with reduced motion); spatial
  stability (existing nodes never move when a delta lands); keyboard
  navigation with aria labels; and a fully self-contained page whose
  HTML/CSS/JS ship as s0ma-owned `content: @file` embeds, hash-tracked in
  the build manifest (FR-STUDI0-8). The package is authored at `strict`
  mode; the unified gate grew `mypy-studi0` (the ADR-001 two-invocation
  shape for multi-module committed builds) and `pytest-studi0` stages; the
  studi0 suite is green under the repo's Windows text-mode emulation with a
  byte-identical committed build; and the v1 acceptance gate (A1–A10,
  rendering the s0ma-mcp self-model read-only) passed with recorded
  baselines — 81 KB `/api/graph` payload for s0ma-mcp, ~30 ms warm first
  render, ~1.1 s edit-to-pixel (bounded by the 750 ms watcher plus the
  1000 ms client poll). studi0 renders its own 31-component self-model,
  embedded assets included.

- **Self-context now carries authored component detail** (ADR-003 hardware
  embodiment: physical facts belong on the verified runtime surface). Each
  `self_context.json` component gains — only where authored — the opaque
  `metadata:` map (the ADR-003 `hw_*` physical-facts vocabulary plus any
  project keys) and the state-carrying `expects`, `guarantees`,
  `declares_attributes`, `latency_ms`, and `provides` fields, projected
  verbatim from canonical IR. A `SelfInspectAdapter` `component <name>`
  answer therefore hands an embodied host the component's mounting, units,
  supply/current bounds, self-interference notes, and executable contracts
  without re-reading per-module IR. Additive under `s0ma-self-context@1`:
  documents from older emitters stay valid, `s0ma.runtime` type-checks the
  new fields when present (a present field must keep its authored shape),
  and the bounded self-prompt card is byte-unchanged — authored detail
  never renders into it.

### Fixed

- **Discovery skips hidden subtrees, so a nested checkout can no longer
  collide with the project that contains it.** An agent harness that checks
  a working copy out *inside* the tree being built — Claude Code session
  worktrees at `.claude/worktrees/<name>/`, full copies of the same project
  — made `s0ma build <project_root>` discover every module twice and fail
  with `MODULE_NAME_COLLISION`, once per module per worktree (observed in
  the s0ma-cpx pilot: 8 modules × 2 worktrees = 16 errors, with `s0ma build
  src` the only workaround). Discovery now skips any path whose directory
  components **below the search root** are hidden (dot-prefixed) or
  machine-owned (`__pycache__`), generalising the special cases that were
  previously spelled out one call site at a time — the `.s0ma` working-state
  dir, `.s0ma.cache`, `.git`, `.venv` — so a harness nobody has thought of
  yet is excluded the day it appears. The rule is relative to the anchor,
  never the absolute path: a project may legitimately *live* inside a hidden
  directory (a worktree is itself a working project root), and discovery
  anchored there still finds its own sources. New `s0ma_dsl.discovery` is
  the one implementation, reached by `.s0ma` and raw-`.py` test discovery,
  the inspect fallbacks and module listing, generated-file drift and
  adoption/score `.py` scans, and the MCP transpile tool's artifact walk.
  Two consequences beyond the reported failure: `s0ma migrate-layout` at a
  repository root no longer reaches into a sibling checkout to delete its
  `__s0ma_cache__/`, and adoption reporting no longer counts a copy of the
  tree as unmodeled debt. Naming a file explicitly is still honoured
  verbatim — the guard governs discovery, not instruction.
- **Qualified cross-module dependency claims now resolve against generated
  registrations** — no more false `declares dependency '<module>::<Name>'
  which is not yet registered` warnings when importing generated code. The
  emitter writes cross-module `dependencies=[...]` claims in the DSL-M2
  canonical `module::declaration` form but registers every generated
  component under its bare key (`module_scoped` stays False), and
  `ComponentRegistry._resolve_key` short-circuited any qualified name that
  was not a direct key hit — so every cross-module edge of every generated
  project warned falsely at import (observed live throughout the s0ma-cpx
  pilot under 0.15.1). `_resolve_key` now falls back from
  `"<module>::<name>"` to a stored spec named `<name>` whose recorded
  `module_path` is consistent with the claimed module: equal, or ending
  with `".<module>"` — segment-aware, because `module_path` records the
  Python import path, which may carry a package prefix — with an empty
  `module_path` unable to refute the claim. Ambiguity still resolves to
  nothing rather than guessing; wrong-module and truly-missing claims
  still warn, and still raise under `strict_dependencies=True`. Fixing
  the registry side rather than the emitter repairs already-transpiled
  0.15.1 build artifacts without regeneration. The same fallback serves
  `get`/`contains`/`get_dependencies`, so canonical IDs now address
  bare-keyed generated components uniformly — and every remaining claim
  consumer now shares it: `register_or_update`'s upsert validation,
  `get_dependents` and the `unregister` dependents guard (a component
  claimed as `module::Name` is protected from unregistration like any
  bare-name dependency), the cross-module ordering edges of
  `import_order` and `bootstrap_modules`, the structural verifier's
  completeness check (a resolvable qualified claim is no longer a
  `PHANTOM_LIMB` anomaly), and `get_component_by_canonical_id`, which
  now delegates to the shared resolver — its former loose suffix match
  gains the same segment-aware boundary (`nosignal_processor` no longer
  satisfies `signal_processor::x`) and an ambiguous canonical ID returns
  `None` instead of an arbitrary first match.
- **Windows CI is green again** (NFR-7: Windows is a first-class, CI-enforced
  platform). Five test failures, all Windows-only and all in the tests' own
  I/O discipline — no product behavior changed, and the `selfhost-build`
  byte-equality stage was passing throughout, so emitter determinism (INV-5)
  was never in question:
  - `test_build_refuse.py` read and wrote the generated `.py` without naming
    an encoding. The emitter writes UTF-8 and the output hash is taken over
    UTF-8 bytes, but an encoding-less `read_text()` decodes with the ANSI code
    page on Windows: the emitted header's em-dashes came back as mojibake,
    whose recomputed hash no longer matched the embedded one, so a freshly
    `--force`-regenerated file read as hand-edited.
  - `test_check_baseline.py` took diagnostic basenames with `file.split("/")`.
    `errors[].file` is the diagnostic's absolute, native-separator path — the
    clickable terminal form — so on Windows the split returned the whole
    `C:\…` path. Basenames now come from `PurePath`. The relative,
    platform-stable module identity in `delta[].module` was already correct on
    every OS and is still asserted separately.
  - `test_tools.py` wrote a poisoned `pyproject.toml` in text mode and then
    asserted byte equality; Windows had translated LF to CRLF before the tool
    under test was ever called. The fixture now uses `write_bytes`, so the
    "left the file byte-identical" contract is asserted exactly.

### Changed

- **Terminology: hardware is *embodied*, not modeled.** Per owner direction,
  the living surfaces now speak of *embodying* physical hardware — brought
  inside the self-knowing boundary as ordinary components — rather than
  modeling it (a model is a description prone to drift; embodiment is the
  point). Patterns guide §31 retitled "Embodying physical hardware"; the ADR
  renamed to `docs/adr/ADR-003-hardware-embodiment-foundation.md` (same
  number, one spirit sentence added, decisions unchanged); README, survival
  card, agent system prompt, self-prompting guide, and core user guide
  aligned. Released changelog entries keep their historical wording, per this
  file's own convention.

- **The 0.15 hardware functionality is now discoverable from every entry
  surface:** the root README's model overview and documentation index point
  at ADR-003, the patterns guide §31, and the embodied survival card; the
  authoring survival card and the agent system prompt cite §31; and the
  self-prompting guide gains a "runtime anomalies are push" section covering
  `subscribe_runtime_anomalies`, the physical `ResourceProfile` bounds, and
  `record_physical`. Documentation only — no behavior change.

## [0.15.1] — 2026-08-10

### Changed

- **`s0ma-core` is relicensed from MIT to Apache License 2.0** (owner decision
  2026-08-10; for `s0ma-core` this supersedes the 2026-07-12 MIT ratification).
  Moved together: the bundled LICENSE text, wheel metadata (`Apache-2.0` SPDX
  expression and classifier), the root and package READMEs, `AGENTS.md`, PRD
  INV-9/NFR-8/§9.3, and both license gates (`scripts/wheel_smoke_mcp.py` and
  the 0.14 contract acceptance test, whose LICENSE-heading checks now tolerate
  the canonical whitespace-led Apache title line). `s0ma-dsl` and `s0ma-mcp`
  remain proprietary/commercial (`LicenseRef-Proprietary`), unchanged. One
  historical PRD fact stands: the v0.5.0 `s0ma-core` wheels shipped under MIT
  and that release remains so as distributed to the initial testers.
- The runtime-free-emission design note is retargeted to the 0.16 design cycle
  (`docs/design/0.15-runtime-free-emission.md` status line); nothing about it
  was implemented in 0.15.x.

## [0.15.0] — 2026-08-10

### Added

- **Hardware-readiness foundation, Tier-1 runtime slice
  (`s0ma-new-hw-foundation-1` M1):** project-agnostic runtime surfaces that
  embodied and long-running hosts need, landed in `s0ma-core` only — no DSL,
  IR, or MCP surface change. A new dependency-free **runtime anomaly stream**
  (`s0ma.anomaly_stream`: `subscribe_runtime_anomalies` /
  `emit_runtime_anomaly` / `reset_runtime_anomaly_subscribers`) delivers
  push-based anomaly notification, mirroring the import-hook anomaly channel.
  A new `AnomalyKind.NOCICEPTION` marks live executable-contract violations;
  the `precondition`/`postcondition` decorators publish it on the stream
  immediately before raising `ContractViolationError`, and
  `postcondition(..., pass_args=True)` now hands validators the call's
  arguments after the result so effect-checking contracts can compare a
  commanded action against its measured outcome. `ResourceProfile` gains
  physical bounds — `expected_max_current_ma`, `expected_max_temperature_c`,
  `expected_min_voltage_v` (dict round-trip is backward compatible) — with
  latest-value gauges on `ComponentMetrics`, app-driven ingestion plus
  immediate bound checks via `MetricsCollector.record_physical(...)`,
  full/incremental `InteroceptionVerifier` coverage (gauges-only components
  are now checked rather than flagged as uncalled), and physical lines in
  `format_component_detail`. Conventions (universal `hw_*` physical-facts
  metadata vocabulary, `sense:`/`actuator:` attribute namespaces, the live-
  readings trust rule) are recorded in
  `docs/adr/ADR-003-hardware-modeling-foundation.md` (Proposed) with the plan
  in `plans/s0ma-new-hw-foundation-1.md`.
- **Hardware-readiness foundation, M2 conventions + M3 embodied survival card
  (`s0ma-new-hw-foundation-1`):** ADR-003 is **Accepted** (HW-D-1 ratified;
  HW-D-2 keeps `NOCICEPTION`). The DSL patterns guide gains **§31 "Modeling
  physical hardware"** — the no-new-declaration organ mapping, the `hw_*`
  physical-facts vocabulary, `sense:`/`actuator:` role namespaces, the
  runtime-wiring surfaces, and the live-readings trust rules — with the
  quick reference's `metadata:` entry pointing at it. Both user guides add
  the **Nociception** taxonomy row and integrity rule **S-8** (the DSL
  glossary and condensed taxonomy table updated too), and the core guide
  documents the push channel as **§5.9 "Subscribing to Runtime Anomalies"**.
  New `packages/s0ma-core/docs/embodied_survival_card.md` — the 60-second
  orientation for agents operating a *running* s0ma system (HW-D-3: core
  docs home) — linked from the core README. `_docs` mirrors re-synced.

### Fixed

- **`s0ma-core`'s `mcp` optional extra now bounds the MCP SDK below 2.0**
  (`mcp>=1.0.0,<2`). The SDK's 2.0.0 release removes `mcp.server.fastmcp`,
  which both servers import; unbounded resolution broke the cold
  installed-wheel journey in the release-integrity gate while workspace
  installs stayed locked at 1.27.x. Migrating both MCP servers to SDK 2.x is
  a tracked follow-up (`plans/s0ma-new-hw-foundation-1.md` §6).

## [0.14.0] — 2026-07-21

### Added

- **New users and coding agents now receive one release-gated explanation of
  what s0ma is and how to prove its value (batch-02a 0.14 M7):** the root
  README leads with an outcome-first fit/non-fit and package-role explanation
  before the faculty taxonomy, then runs one executable journey through
  project creation, `project_status`, canonical dependency inspection,
  deliberate generated drift, pending release debt, recovery, and explicit
  host verification. The same canonical Markdown is served as
  `s0ma://guide/getting-started` and linked from CLI/MCP initialization. A root
  `AGENTS.md` pins authority order, dependency direction, generated paths,
  self-host/snapshot rules, the canonical gate, licensing, and a five-minute
  orientation loop. Root and MCP README inventories are now marker-generated
  from the live-surface snapshot (12 tools, 12 resources, 4 prompts), whose
  names, annotations, and schemas remain byte-gated; stale walkthrough lists
  were removed. The 0.9.0 Word guides moved to `docs/archive/0.9.0/` with an
  archive notice. The canonical nine-stage check now builds all three wheels,
  proves their license expressions/classifiers/bundled LICENSE files
  (`s0ma-core`: MIT; DSL/MCP: proprietary), rejects stale current
  authoring-license claims,
  installs the wheels into a cold isolated environment, performs a real MCP
  stdio handshake, and executes the full outcome journey including
  caller-pinned score and trusted host evidence across the supported CI matrix.

- **Applications can ship a verified self-model to their own runtime LLM
  (batch-02a 0.14 M6):** every build now derives deterministic
  `s0ma-self-context@1` JSON from canonical IR and renders a bounded
  `self_prompt_card.md` from that JSON alone (at most 1,800 UTF-8 bytes / 240
  whitespace words). The additive `s0ma-build-manifest@1.self_context` member
  references both build-root sibling artifacts by POSIX path and SHA-256; older
  manifests still load, while the runtime helper refuses them with rebuild
  guidance. `s0ma.runtime.self_context()` stays DSL-free and verifies manifest,
  companion, card, and every source-IR path/hash before returning inventory,
  card, and—only for an explicitly supplied registry—a separately labeled live
  overlay. The app-registerable `self_inspect` adapter answers `describe`,
  `component <name>`, and `dependencies <name>`. ADR-002 freezes authored
  intents as untrusted, provenance-labeled `AUTHORED_DATA`; newline and forged
  delimiter attempts cannot become privileged instructions. New-project and
  MCP guidance teach ContextAssembler-style wiring through
  `s0ma://guide/self-prompting`; the served surface is now 12 tools, 11
  resources, and 4 prompts. The frozen contract's build-root-relative wording
  supersedes M6-T2's stale project-root-relative draft because the companions
  are manifest siblings and need no project-root discovery.

- **The authoring surface now keeps agents inside the value loop instead of
  dropping them at an empty map (batch-02a 0.14 M5):** roster-adopted Python
  modules gain an import-free, provenance-marked `s0ma-derived-surface@1` for
  `inspect_module`; canonical IR always wins, and the deterministic cache binds
  source identity and content, relevant project config, derivation/schema, and
  tool versions while remaining gate-inert and path-contained. `project_status`
  preserves the complete adoption ledger but counts/maps only current existing
  handwritten `.py` files as roster modules. All 12 MCP tool bodies now return
  `s0ma-tool-result@1` with live-tool/schema-validated `next_actions`; invalid
  arguments remain MCP protocol errors, body failures carry correction actions
  plus the live tool map, and `verify_host` keeps exactly one authoritative
  `s0ma-host-verification@1` document under `result.host_verification` (the CLI
  remains native top-level host JSON). Every tool description now states its
  job-to-be-done trigger and a worked example. The look-inward-first operating
  journey ships through initialize instructions, the new `diagnose_fault`
  prompt, runtime-aware `project_status`, and a compact `describe_server`
  situation map whose journeys cover every live tool;
  `check` findings add component owner and intent where resolvable. The served
  surface is now 12 tools, 10 resources, and 4 prompts.

- **New code now starts from intent; adoption is visibly interim migration debt
  (batch-02a 0.14 M4):** `adopt_file` requires a persisted one-line intent and
  returns `s0ma-tool-result@1` with `status: "interim"`, modeled/roster counts,
  and an `author_module` next action. A Python file first seen after the
  first-contact baseline and only roster-adopted emits `NEW_FILE_ROSTER_ONLY`;
  the fourth adoption emits advisory `ADOPTED_CHURN`, while its persisted
  history counter never affects a gate. Project-local `adoption_exempt` entries
  classify and enumerate only. Gate waivers require an explicit caller
  `s0ma-adoption-policy@1`; the score enumerates every match, reports a
  canonical normalized SHA-256, supports expected-hash pinning, and refuses
  catch-alls, whole configured source/test/build roots even in pure-legacy
  projects, root escapes, malformed entries, and modeled-source matches.

- **Semantic state is explicit, typed, and migratable (batch-02a 0.14
  M3A):** every declaration field now has one normative classification;
  semantic fields retain ordinary authored values while additionally accepting
  whole-value `none` and `pending("non-empty reason")`. The AST carries tagged
  `SemanticState` records and canonical output is the breaking `s0ma-ir@3`
  (`schema_version: "3.0.0"`) representation. Unknown majors refuse with a
  migrate-and-rebuild remediation. `s0ma migrate grammar` is a dedicated,
  deterministic dry-run-by-default migration with explicit `--apply`, complete
  project parse/hash preflight, same-directory atomic replacements,
  whole-plan rollback, conflict refusal, and idempotent reruns. Pending debt
  earns zero completeness credit, is a migration/dev warning and strict/release
  error, and is enumerated by `project_status` with owners, fields, reasons,
  sources, and a release-block marker. Caller-pinned release scoring derives
  its structured `pending_semantic_state` gate block directly from tagged AST
  state, so migration/dev warning severity cannot weaken release policy. MCP
  `adopt_file.description` is now
  required because it is authored intent; other paths, modes, and timeouts
  remain ordinary invocation arguments. M3B completed the corpus migration
  and requiredness flip described below.

- **Release evidence now proves the deliverable under the host application's
  actual interpreter (batch-02a 0.14 M2):** the new explicit `s0ma verify-host`
  CLI and twelfth MCP tool, `verify_host`, emit `s0ma-host-verification@1`
  evidence without making static `check`, `score`, or ordinary `verify` execute
  project code. Interpreter resolution is strict—explicit `--python`, then a
  contained project-relative `[tool.s0ma].venv_path`, then platform `.venv`,
  else refusal; there is no fallback to s0ma's interpreter. The report carries
  an absolute venv-preserving interpreter fingerprint, installed s0ma versions,
  declared/installed/runtime-imported dependency states, and one isolated,
  timeout-bounded import record per production module in deterministic
  topological order; bounded UTF-8 output and continued collection keep one
  failure from hiding later modules. Diagnostics distinguish
  `DECLARED_DEP_NOT_INSTALLED`, `HOST_RUNTIME_UNDECLARED`, and
  `HOST_IMPORT_FAILED`. Emitting commands statically warn when the host omits
  the always-emitted `s0ma-core`/`s0ma-dsl` runtime dependencies. Release
  orchestration is explicitly the pair `check(gate_mode=release)` then
  `verify_host(gate_mode=release, python=...)`; neither result alone claims
  readiness, and each MCP result points to the other half through structured
  `next_actions`. The new MCP tool honestly advertises arbitrary trusted
  project-code execution (`readOnlyHint=false`, `destructiveHint=true`,
  `idempotentHint=false`, `openWorldHint=true`); side-effect fixtures prove the
  warning is real, not ceremonial. Runtime-free emission remains a scoped 0.15
  design decision rather than an in-flight semantic fork.

- **0.14 gate-integrity and value-loop contracts are frozen before behavior changes
  (batch-02a M0):** root ADR-001 records the nine owner-approved boundaries for static
  safety, caller-pinned gates, package direction, tagged semantic state, adoption policy,
  derived provenance, canonical self-context, release metadata, and untrusted authored
  prose. A companion contract pins the exact schema migrations, declaration-field state
  matrix, manifest additions, and MCP surface checkpoints. Thirteen strict-XFAIL
  adversarial acceptance cases cover every batch failure shape while keeping the current
  gate green; a live snapshot guard fixes the pre-wave MCP baseline at 11 tools, 10
  resources, and 3 prompts. Later milestones must convert their XPASS into permanent
  acceptance coverage rather than silently changing the contract.

### Changed

- **The 0.14 release candidate is lockstep, auditable, and ready for its local
  tag after independent review (batch-02a 0.14 M8):** all three distributions,
  import-level version surfaces, the workspace lock, current install examples,
  and the served changelog now agree on 0.14.0. The complete release acceptance
  records caller-pinned static score evidence, explicitly approved host-import
  evidence under the trusted project interpreter, verified self-context,
  componentized/no-roster registration, generated knowledge, exact wheel
  licenses and hashes, and the cold installed outcome journey. The bench handoff
  pins the new schemas/exit codes, adoption-policy hash and `gate_mode`
  responsibilities, grammar/cache rebuild, 12/12/4 MCP surface, F1-S runtime
  card wiring, and batch-02b prerequisites. No tag is created or pushed as part
  of candidate construction; the annotated local tag follows independent audit.

- **Semantic requiredness is enforced across current source and generated
  artifacts (batch-02a 0.14 M3B):** normal parse, check, transpile, and build
  paths now reject omitted semantic-required fields, disallowed `none`,
  disallowed `pending(...)`, and authored derived fields with named,
  owner/field-specific diagnostics and remediation. The legacy omission reader
  is isolated to `s0ma migrate grammar`. All monorepo `.s0ma` source, invalid
  fixtures, dynamic test builders, new-project templates, and scaffolds now
  author explicit states; canonical IR and self-host output preserve tagged
  `value` / `none` / `pending` vocabulary. `inspect_module` documents the
  tagged IR contract, `project_status.semantic_debt` documents pending owners,
  reasons, zero credit, and its release block, and the spec, quick reference,
  traceability matrix, and generated errors guide use the same terms. A
  post-migration rerun over each explicitly valid authored corpus reports zero
  changes. Whole-project preflight does not infer source validity from a
  directory name: a user path named `invalid/` is discovered normally and a
  malformed source there aborts with `GRAMMAR_MIGRATION_PARSE_ERROR`.

- **Gates now require evidence instead of hollow arithmetic (batch-02a 0.14
  M1):** `s0ma score` emits the breaking `s0ma-score@2` contract, separates
  project-selected authoring `mode` from caller-pinned `gate_mode`, leaves
  `gate.passes` null for report-only calls, fixes migration's floor at 50,
  and records `nothing_to_measure` as a blocking condition instead of
  silently dropping absent populations. Registration is split into
  componentized, roster-adopted, and unknown counts; only componentized code
  earns gate credit. Metacognition now reports `declared_test_evidence` from
  existing non-empty test declarations rather than name-only claims. The DSL
  owns static discovery and passes a parser-neutral `DiscoveredSurface` into
  core verifiers, which fault the discovered-minus-registry delta as
  `UNREGISTERED_SURFACE` without importing the DSL. Contract coverage at zero
  declarations is now 0.0; performance/error-rate threshold violations retain
  WARNING severity but carry explicit gate-relevant categories, and doc
  selector/validation errors count against the score. A pinned gate refuses to run while
  `S0MA_VERIFY_CONTRACTS=0`. `s0ma verify` emits `HOLLOW_MODEL` and exit 4 for
  adopted-only/zero-modeled trees, with an always-visible modeled / roster /
  unknown coverage triple. MCP `check` adds only the budgeted optional
  `gate_mode` input and returns the same pinned score evidence; `score` remains
  CLI-only and all static checks remain read-only.

### Fixed

- **Package license metadata now matches the ratified open-core posture:**
  `s0ma-core` ships the MIT text, SPDX `MIT` metadata, and MIT classifier;
  `s0ma-dsl` and `s0ma-mcp` ship the proprietary license text,
  `LicenseRef-Proprietary` metadata, and the proprietary classifier. All three wheels
  explicitly include their LICENSE file, and the DSL/MCP package READMEs no longer carry
  stale open-source declarations.

## [0.13.0] — 2026-07-17

**The batch-01c deep-dive wave — closing the cold apprenticeship.** Batch-01c's deep-dive measured *where* the cold-session premium actually goes: a per-session DSL apprenticeship — authoring plus fix loops plus gate re-verification ≈ 73% of the cost delta — with 38/72 cold `check` calls failing on self-inflicted declaration mismatches, `build_project` failing 0/84 times while 18/36 cold sessions ended check-red (agents learned "check red / build green" reads as noise; the CM6 crater shipped through exactly that gap), and teaching landing only in the tool outputs agents already hit (`project_status` 36/36 sessions; `s0ma://guide` 0/36). Every milestone in this wave removes a failure mode the batch measured, on one doctrine: teach in the loaded channel, gate where dismissal was observed, never rely on a new surface agents must discover. The four moves: **self-healing contract diagnostics** (M1 — the checker hands over a ready-to-paste corrected `provides:`/`requires:` block, correct by construction, with an ambiguity guard and a teaching-exposure counter), the **binding build gate** (M2 — `build_project` refuses NEW check-severity errors against a monotone-shrinking inherited-debt anchor that an agent's own red check structurally cannot launder, with a manifest-stamped `allow_new_errors` escape hatch and its override counter; PRE-EXISTING debt alone never blocks, so brownfield stays viable), **source pointers in generated code** (M3 — every generated `.py` carries passive `# s0ma:` origin comments inside the drift hash, and the write-only `*.s0ma.map` finally has its read half: a resolver library plus disk loader), and **teaching in the loaded channel** (M4 — a green build's `health_echo` points at the declared verify command or nudges, not-a-fault, to declare one; the survival rules ride the `project_status` result both branches; and the whole cold arc — init → status → mismatch → suggestion → refusal → paste → green build with echo — is pinned as one MCP integration test). The language and IR schema are unchanged; the served MCP surface changes are the `build_project` `allow_new_errors` input and the `build_project`/`project_status` result-shape descriptions — every other behavior rides result values and rendered text, so bench packs and prompts need no changes.

### Added

- **Teaching consolidation — the health echo on green builds and the survival card in `project_status` (batch-01c 0.13.0 M4, P1):** ship-without-running was the common thread of the batch's worst outcomes (the CM6 crater shipped with zero runtime probes; an ops run left the service down), and the teaching-channel evidence is unambiguous — `project_status` landed in 36/36 sessions while `s0ma://guide` was read 0/36 — so both moves put teaching in the tool outputs agents already hit and neither adds a surface agents must discover. **(a) Health echo:** a green `build_project` result gains ONE trailing `health_echo` line — `verify: <health_command>` when `[tool.s0ma]` declares one (0.11.0 O1; `run_command` is the fallback), else the not-a-fault nudge `no health_command declared — declare one in [tool.s0ma] so builds can point at it` (0.12.0 M1 wording discipline: an absent command is a documentation gap, never a fault). The wording has ONE canonical source — the new `S0maProject.health_echo()` — rendered by both the MCP result and the CLI build summary so the two surfaces cannot drift; the echo rides ONLY the green path (M2's refusal result stays byte-exact as shipped; a legacy-mode build already carries its own init_project warning and gets no echo — the right nudge there is init_project, not health_command; the internal `s0ma test` build helper and synthetic projects are exempt on the CLI side). **(b) Survival card in `project_status`:** the result carries the survival rules under a `rules` key — the same inline `_SURVIVAL_RULES` tuple `init_project` / `scaffold_module` / `describe_server` embed (0.11.0 D1 mechanism; ONE canonical source, no forked wording) — in BOTH branches, because a not-yet-a-project answer is exactly the bootstrap moment that most needs them. Measured payload growth on the representative multi-module fixture: 1,869 B → 3,312 B (+1,443 B for the 7-rule tuple; the plan's 6-rule/~1 KB arbitration figure predates 0.12.0's storage-migration rule 7). The `s0ma://guide` resources stay for reference depth but nothing in the design depends on them any longer. **(c) The fresh-agent walkthrough is now an integration test** (`TestFreshAgentWalkthrough`, MCP tool layer end to end): init (rules) → `project_status` (same rules, one source) → green build (baseline recorded + echo) → an in-place `provides:` mis-declaration → strict `check` labels it `[NEW]` and hands the `suggested_declaration` block (M1) → `build_project` refuses and re-hands the same block (M2), no echo riding the refusal → the suggested block pasted verbatim clears its diagnostic class, and the successor finding (`MISSING_PROVIDED_FUNCTION` — the body-side def/key inconsistency a declaration paste cannot decide for the author) names the remaining rename → green check → green build with the echo. Also covered: declared / fallback / health-beats-run / undeclared echo cases, refusal-carries-no-echo, legacy-carries-no-echo, and `project_status` rules in both branches identical to init's payload. The MCP surface snapshot is regenerated for exactly the two description deltas (`build_project` naming `health_echo`, `project_status` naming `rules`); `_built/` rebuilt byte-clean from the `.s0ma` sources (the M3 `# s0ma:` pointers ride the rebuild) and the `selfhost-build` gate stays green.
- **Source-mapped debugging — generated files now carry source pointers, and a resolver library turns a `build/*.py` line back into its `.s0ma` origin (batch-01c 0.13.0 M3):** the per-module `*.s0ma.map` has shipped on every build since 0.7.0 (declaration + body spans that make a `build/*.py:N` → `src/*.s0ma:M` lookup exact arithmetic), and batch-01c measured that it had **zero consumers** — a write-only artifact read 0 times — while cold agents debugged in raw Bash (465 `python -m …` runs) and opened `build/*.py` at traceback lines 100 times. So this milestone puts the pointer where those reads land, in the cheapest passive form the feasibility packet endorsed (`s0ma-bench/plans/notes/sourcemap-feasibility.md`): **(a)** a pure resolver library, `resolve_output_line(source_map, output_line) -> ResolvedLocation(source_file, source_line, declaration, region)` in `s0ma_dsl.codegen.source_map` — body arithmetic for an authored body (exact), the embedded file (clamped to its recorded span) for a `@file()` cell, and a region label (`decorator` / `declaration` / `module-header` / `imports` / `exports` / `registration` / `between-declarations`) everywhere else — no `.s0ma.map` schema change — plus the read half the write-only artifact never had: `SourceMap.from_dict` / `load_source_map(path)` mirror `to_dict` exactly, so a shipped `.s0ma.map` finally loads from disk and resolves (`resolve_output_line(load_source_map(map_path), py_line)` is the whole traceback-to-source flow, and the exact path the deferred (c) post-processor needs); **(b)** the transpile pipeline now writes one passive `# s0ma: <src>.s0ma:<line> (<kind> <name>)` comment immediately above each authored declaration's body in the generated `.py` (nerve / ganglion / `@component` cell / test / helper — CONSTANT/TYPE data-literal cells are deliberately skipped), plus one module-header `# s0ma: generated from <src>.s0ma — edit the .s0ma source, never this file.` pointer that reinforces the 0.11.0 drift guard in the exact place agents look. So an agent reading a traceback frame in `build/rooms.py` sees `# s0ma: src/rooms.s0ma:43 (nerve RoomsvcApi)` one line above the body and needs neither the `.map` nor a tool. The pointers are **derived from the same body spans as the map** (correct by construction, not string surgery) and inserted **before** `inject_hashes`, so they live inside the drift hash: a freshly regenerated file still classifies as clean (`is_hand_edited` is `False`), a hand edit to a body line still trips `GENERATED_FILE_DRIFT`, and repeated builds are byte-identical (the source map is regenerated from the annotated text — its body finders skip the leading pointer, so `body_output.start` stays anchored to the first authored line and the `body_output.start → body_source.start` arithmetic the resolver relies on stays exact; the direct `emit_python` + `generate_source_map` path is untouched, so the skip is a no-op there). **Optional secondary (spec (c)) deferred to 0.14.0:** appending resolved traceback frames to `run_example`'s captured-stderr result. The measured landing surface is unused — agents run examples in raw Bash (465×) where (b)'s pointers already deliver the origin, not through the `run_example` MCP tool — and shipping it means a `run_example` result-shape change plus a surface-snapshot regen, which is not the "cheap" the gate asks for; the resolver ships as a library so 0.14.0 can add the post-processor in a handful of lines. Explicitly excluded (spec (d)): a standalone resolve/explain MCP tool, a runtime excepthook, and any `.s0ma.map` schema change. Coverage: `test_source_map.py` gains the resolver's exact-body / helper / decorator / module-header / between-declarations / embedded-file (clamped) / frame-formatting cases, the pointer set (one per annotated declaration; CONSTANT skipped; header pointer present; still valid Python; deterministic), the pointer-above-body invariant, the pointer↔resolver round-trip, the drift-guard interaction (regenerate → not hand-edited; edit a body line → drift), lossless `from_dict`/`to_dict`/`load_source_map` round-trips (including resolve-equivalence over every output line of the loaded copy), and a shipped-map fixture battery that loads the 3 committed `_built/*.s0ma.map` files from disk and verifies every `# s0ma:` pointer in the sibling `.py` resolves — through the shipped map — back to exactly the source file/line/declaration it states. Self-host tax (one coherent commit): every generated file re-emits, so the 3 self-hosted `_built` MCP modules (`prompts.py` / `resources.py` / `tools.py`), their `.s0ma.map`s, and the `build.s0ma.json` manifest hashes were regenerated byte-clean and the `selfhost-build` gate stays green; the served MCP surface snapshot is unchanged (no tool description or schema changed — (c) deferred), and the IR (`.s0ma.json`) and type stub are unchanged (comments are not IR).
- **`build_project` hard-fails on NEW check errors — the build gate the CM6 crater shipped through is now binding (batch-01c 0.13.0 M2, P0):** in batch-01c cold sessions `build_project` failed 0/84 times while 18/36 sessions ended check-red, and agents learned that "check red / build green" reads as noise — the P2 CM6 crater (`P2_P_haiku45_r03`) went straight through this gap: the agent read its own `check` failures, dismissed them as *"pre-existing and not related to my changes"* (it was wrong — the edit had just introduced them), built green, and never ran the service. The gap is structural: `check` defaults to **strict** while `build_project` defaults to **dev**, so a code that is a *warning* to the build but an *error* to `check` (`PROVIDES_KEY_MISMATCH`, `MISSING_PACKAGE`, `CROSS_LAYER_DEPENDENCY`, `MODULE_SHADOWS_STDLIB` …) leaves the build green while `check` goes red. 0.12.0 M2 made NEW-vs-PRE-EXISTING computable; this makes it **binding on the build**. `s0ma build` / the MCP `build_project` tool now, before writing any artifact, classify the tree's **check-severity** errors (what `check` — strict — would report, via the strict severity matrix, independent of the build's own laxer mode) against the baseline's inherited-debt **anchor** (below) and **refuse** when the current edit introduced a **NEW** one — no artifacts written, the baseline left untouched (so a re-run refuses again — the override is a one-shot, never a laundering of NEW → PRE-EXISTING). The refusal is a **first-class result, not an exception** (the `GENERATED_FILE_DRIFT` refuse-at-write precedent, 0.11.0 M1): it LEADS with the labelled `[NEW]` error list — each carrying M1's ready-to-paste `suggested_declaration` block when the checker could render one — then the one-line rule *"new check errors block builds; fix them or pass allow_new_errors=true with a reason"* and the escape hatch, in both the text output and the `--format json` document (a top-level `build_refused` block plus the labelled `errors`), so the MCP tool surfaces it verbatim under `result["diagnostics"]` with no MCP-side rendering. The escape hatch is a new `--allow-new-errors` CLI flag / `allow_new_errors: bool` MCP input, kept **separate** from `--force` (spec (d): force discards hand-edits to a generated `.py`; allow-new-errors accepts new contract errors — the two are never conflated): passing it builds anyway, records the waved-through error keys into `build.s0ma.json` (a new additive `overridden_new_errors` field — omitted on every normal build, so the manifest stays byte-identical to its pre-M2 shape), stamps a `build_override` block into the build's JSON output, and — because the gated codes are dev-*warnings* — the build's own dev-mode emission is clean, so the manifest and artifacts stamp normally. Guardrails (spec (c)): **PRE-EXISTING errors alone never block** (a check-recorded prior failure classifies PRE-EXISTING → the build proceeds, so brownfield adoption stays viable), a **missing baseline degrades to today's warn-and-build** (the gate only ever tightens on evidence it can attribute to the current edit), warnings that are warnings even to strict never block, and `build --check` (a drift dry-run that writes no real artifacts) plus the internal `s0ma test` build helper are exempt. A sixth agent-invisible telemetry counter `build_override_new_errors` rides the 0.11.0 counters mechanism (sink-only, byte-invisibility preserved; derived from the `build_override` block in the result) so the bench can count how often agents lean on the escape hatch instead of fixing — batch-02a's guardrail. **The binding half of the gate is a semantic upgrade to the 0.12.0 baseline itself — the monotone-shrinking inherited-debt anchor** (this is what actually closes the measured dismissal path, because the crater agent *ran* `check` before building): under 0.12.0's diff-against-last-run semantics, green baseline → break → red `check` overwrote the baseline with the failure set, and the very next look — the build gate included — would have called the agent's own breakage PRE-EXISTING; an agent's own red check *laundered* NEW into PRE-EXISTING, un-binding the gate through the literal CM6 sequence. The record (`s0ma-check-baseline@1`, `s0ma_dsl.check_baseline`) now carries an additive `anchor` list beside the last-run `diagnostics`: the set of **genuinely inherited debt**, seeded once (no baseline on disk → anchor := the current failure set, so brownfield first contact records its inherited errors; a green first run seeds it empty) and only ever intersected downward (anchor := anchor ∩ current on every recording run; a key leaves when its failure is *observed fixed* and can NEVER re-enter — a once-fixed error re-introduced later is NEW, yours). Classification — the `check` labels AND the build gate — is now PRE-EXISTING iff the key is in the anchor, NEW otherwise, RESOLVED := anchor − current, which changes one observable 0.12.0 behavior **deliberately**: re-checking an unfixed failure keeps saying `[NEW]` (truthful to "NEW since your last green build") instead of flipping to `[PRE-EXISTING]` on the second look; the 0.12.0-pinned baseline byte-shape test is updated for the additive `anchor` field. Attribution safety (spec (c) — a key may only leave the anchor when its module was actually re-analysed and the failure observed absent): **scope-limited runs never record** — a subset `check <path>` classifies read-only against the stored anchor (labels still render) but writes nothing, and only full-project checks, full-project-root builds (not the internal `s0ma test` helper) record, because a partial run must never shrink the anchor on modules it never re-analysed (this also closes a latent 0.12.0 defect where a subset check overwrote the whole-project last-run set); **preempted modules keep their keys** — a module whose analysis was cut short this run (`PARSE_ERROR` and the parse-family codes that suppress a module's downstream checks) keeps its anchor keys and is excluded from RESOLVED, so inherited failure X cannot vanish behind an agent's transient parse error and resurface labelled NEW once the parse error is fixed; and **key severity is check severity** — the record keys on what strict `check` would rank an error (`is_check_severity_error`, the same predicate the gate uses), so a dev-mode build/check observing an inherited strict error as a mere warning does not drop it from the anchor. A legacy 0.12.0 record with no `anchor` field migrates gracefully for one run (anchor := its `diagnostics` set — exactly the old semantics, once). Coverage: DSL `test_build_new_error_gate.py` drives refuse / allow / pre-existing-only / no-baseline, the CM6 refuse→allow arc, the **honest CM6 shape** (green → break → *intervening red `check`* → build STILL refuses → fix → green build) and the parse-error-detour brownfield arc end to end plus the manifest round-trip; `test_check_baseline.py` pins the anchor semantics (second-red-check stays NEW, subset checks neither record nor strip, parse-preemption, legacy migration, never-re-enter); the MCP `test_tools.py` exercises refuse/allow over the `build_project` tool; `test_telemetry_counters.py` pins the new counter's derivation matrix. The MCP surface snapshot is regenerated for exactly the one new `allow_new_errors` input and the `build_project` description text (the anchor upgrade itself is DSL-side classification — no further surface change); `_built/` was rebuilt from the `.s0ma` sources byte-clean and the `selfhost-build` gate stays green.
- **Self-healing contract diagnostics — `check` now hands over a ready-to-paste corrected declaration block (batch-01c 0.13.0 M1, P0):** the cold-session anatomy measured 38 of 72 cold `check` calls failing on self-inflicted declaration mismatches (`PROVIDES_KEY_MISMATCH` / `MISSING_PACKAGE` — the agent's own in-place edits mis-declaring `provides:` / `requires:`), each burning a 2–6-turn guess-and-retry loop (15–17% of cold-mod spend vs baseline's 5–6%). The checker already computed the declared-vs-actual sets it uses to *name* the mismatch; now it hands the answer over. Each such diagnostic gains an additive `suggested_declaration` value carrying the corrected block rendered in the DSL's own inline surface style — for `PROVIDES_KEY_MISMATCH` (flat form) the nerve's `provides:` re-derived from the body's actual literal return-dict keys (`provides: [asemble, validate]`); for `MISSING_PACKAGE` the module's `requires:` (or `deferred_requires:`) with every unresolvable entry dropped, **consolidated one block per module** (multiple bad entries collapse into a single paste, not one block per error). The block is **correct by construction** — derived from the same resolved-actual sets the checker used, never heuristic string surgery — so pasting it over the named declaration and re-checking clears that diagnostic class; a property battery (`test_declaration_suggestions.py`) drives apply-then-green across extra-key / missing-key / renamed-symbol / wrong-module-path / multiple-modules shapes plus a requires-entry renderer round-trip. The suggestion renders **after** the cause and `Remediation:` lines (the lead-with-cause ordering is untouched) and rides `S0maError.to_dict` — present only when set, so pre-M1 consumers are byte-unaffected — into both the CLI `--format json` payload and the CLI text output, and therefore into the MCP `check` result verbatim with **zero MCP-side code** (the 0.12.0 M2 pass-through pattern; it coexists cleanly with the M2 `[NEW]` / `[PRE-EXISTING]` labels). **The ambiguity guard** (spec (e)) is the failure direction: when the checker cannot be certain, it explains rather than fabricates — a structured `provides:` triple (a new key would need a `returns`/`expects`/`guarantees` triple it cannot synthesise) and a `requires:` entry whose import path actually names a s0ma module in the project (the fix is a cross-declaration move to `uses:`, not a silent drop) both emit **no** block and say why. A new agent-invisible telemetry counter `declaration_suggestion_shown` (result-driven, joining the existing four; sink-only, byte-invisibility preserved) lets the bench measure teaching exposure → fix-loop effect. Diagnostic classes covered: `PROVIDES_KEY_MISMATCH`, `MISSING_PACKAGE`. Sibling declared-vs-actual codes swept and consciously deferred to 0.14.0 (their corrected block spans a second declaration, targets a body literal rather than a header block, or already prescribes the exact fix): `NOT_EXPORTED` / `DOES_NOT_EXIST` (block belongs to a *different* module's `exports:`), `VESTIGIAL_IMPORT` / `CROSS_MODULE_USES_ASYMMETRY` (a `uses:` / `requires:` trim of unreferenced entries), `MOCK_KEY_MISMATCH` (fix is a body mock-dict literal, not a header declaration), and `REQUIRES_DOTTED_LOWERCASE_HINT` (its remediation already spells the colon-override form).
- **The patterns-guide section-reference drift gate (`test_patterns_guide_refs.py`):** inserting a numbered section into the patterns guide renumbers every section after it, and the live surfaces that cite those numbers go silently stale — the batch-01c wave's new §24 shifted the project-standards block §24–29 → §25–30 and invalidated the citations in the quick reference's standards row, the agent system prompt, the `new project` AGENTS.md scaffold, and `score.py`, caught only by a one-off manual grep during orchestrator review. A new s0ma-dsl test makes that catch mechanical: it parses the guide's numbered headings (fence-aware) into a number → title map and scans the live repo text — package docs plus the `_docs` mirrors, package `src/**` Python, the MCP `s0ma_src` sources, root docs — for `§N` / `§N.M` / "Patterns Guide §N" citations (ranges like `§24–§28` included), failing with exact `file:line` messages when a cited number no longer exists or a bold/quoted title riding the citation no longer matches the section actually at that number. The repo's other `§` namespaces stay out of scope by construction, favouring few false positives (an immediately preceding document word — "spec §4.13", "walkthrough §5" — or a bare number that resolves only in a shipped spec's heading namespace is never flagged), and historical records are exempt (every `CHANGELOG.md`, `plans/`, `docs/historical/`, generated `_built/`). Reconstructing the batch-01c incident (the renumbered guide plus the pre-fix citations) trips 12 precise violations; the current tree and the batch-01c branch both pass clean. Runs inside the existing `pytest-dsl` stage — the check pipeline stays nine stages.

## [0.12.0] — 2026-07-16

**The batch-01c fix wave.** The second benchmark batch against the pinned 0.11.0 server (ARM-P, batch-01c) confirmed the 0.11.0 wave landed where it aimed — the batch-01a integrity disaster stayed eliminated (no silent revert fired once across the batch) and the modification-cost gap held at parity — so this is not another stop-the-bleeding pass; it targets the failure modes the new batch surfaced. Two P0s from the same warm/cold agent pair: a mid-diagnosis agent read the undeclared-runbook surface and mistook a documentation gap for the live service fault it was hunting, so the undeclared and partial runbook renderings and the `project_status` runtime hint now lead with an explicit not-a-fault disclaimer and a fifth inline survival rule carries it (M1); and an agent dismissed its own build-breaking `check` failures as "pre-existing" when its edit had just introduced them, so `check` now records a per-project working-state baseline at `.s0ma/check-baseline.json` (schema `s0ma-check-baseline@1`, gitignored — the deliberate opposite of adoption's committed record) and attributes every failure as NEW or PRE-EXISTING against your last green build, leading the summary with the NEW count in both CLI text and `--format json`, with a sixth rule making a NEW failure the author's to own (M2 — which also closes a latent `rglob("*.s0ma")` crash on a `.s0ma` working-state directory). One interop-debt fix: every env-gated telemetry record now leads with a `telemetry_schema: "s0ma-telemetry@2"` marker so consumers key on a tag instead of shape-sniffing the `counters` list, with the stable record contract documented in the s0ma-mcp README (M3). And one teaching addition, owner-gated to teaching only (no analyzer): the patterns guide gains a durable-state-migrations section (§24) naming the `CREATE TABLE IF NOT EXISTS` anti-pattern behind the batch's schema-migration crater — a creation-path-only edit is a fresh-state-only fix, fine on a new store and fatal on a lived-in one — with a seventh inline rule; inserting §24 renumbered the guide's project-standards block to §25–30 and a repo-wide sweep moved every live cross-reference in lockstep (M4). The language and IR schema are unchanged, and the served MCP surface is unchanged — this wave's behavior rides result values, rendered text, and served docs, not tool descriptions or schemas, so the surface snapshot is untouched; `_built/` is rebuilt byte-clean for the version bump alone.

### Added

- **`check` attributes every failure as NEW or PRE-EXISTING against your last green build (batch-01c M2, P0):** in bench batch-01c cold CM6 (`P2_P_haiku45_r03`) the agent altered only the `CREATE TABLE IF NOT EXISTS` DDL for an existing database, every mutation's `INSERT … actor` 500'd, `s0ma check` FAILED before commit — and the agent **dismissed it**: *"These errors are pre-existing and not related to my changes"* (verbatim). The dismissal was factually wrong, but nothing in the check output made it checkable — diagnostics carried no notion of "was this failing before your edit?". `check` now keeps a memory of the last run. On every run over a real (`[tool.s0ma]`) project it records a compact failure fingerprint at **`<root>/.s0ma/check-baseline.json`** (schema `s0ma-check-baseline@1`, new module `s0ma_dsl.check_baseline`): a green run writes the empty clean fingerprint, a failing run writes the current failure set, so the *next* run can diff. Storage extends the committed-sidecar pattern of 0.11.0 M3 adoption (`adopted.s0ma.json`) but is its deliberate opposite — **working state, NOT committed**: it lives under the `.s0ma/` directory the repo already gitignores as "s0ma persistence" (the home of `.s0ma/registry.db`), because a green baseline on one machine says nothing about another's uncommitted edits (documented at the schema constant, alongside the load-time contrast — a malformed baseline is treated as *absent* and regenerated, never raised on, unlike adoption's authored record). Each diagnostic keys on `(code, module, symbol)` — the module's project-root-relative POSIX source path and the in-module symbol from `context` — with **no line numbers** (they churn) and no timestamps, so a finding keeps its identity when an edit shifts its line. When a failing run finds a baseline, `check` labels every failure `NEW` (not in the baseline) or `PRE-EXISTING` (in it), summarizes `RESOLVED` (in the baseline, now gone), and **leads the summary with the NEW count** — *"3 failure(s): 2 NEW since your last green build, 1 pre-existing."* — in both the text output (a `[NEW]` / `[PRE-EXISTING]` prefix per line) and the `--format json` document (a `delta_label` on each error plus a `delta` block). No baseline yet → the run renders exactly as before plus one line noting none exists. The MCP `check` tool carries the same labels with **no MCP-side change**: it wraps the DSL's `--format json` result, so the `delta` rides through in `result["diagnostics"]` (spec (e); telemetry unchanged — M3 owns it). A fully-green `build_project` refreshes the same baseline (spec (a) — "check/build_project"); delta *rendering* stays `check`'s surface. Baseline writes are atomic (temp-file + `os.replace`) and deterministically ordered, so two green checks produce byte-identical bytes; the baseline is per-project-root and last-writer-wins (single-agent workflows — noted at the schema constant). The inline survival ruleset (`_SURVIVAL_RULES`) gains a **sixth rule**: a NEW check failure after your edit is yours — fix or explicitly justify it before building; "pre-existing" is only claimable when the output says `PRE-EXISTING`. `check` stays `readOnlyHint=true`: the baseline is gitignored working state (like the telemetry sink and `.s0ma.cache/`), not a mutation of authored state or the tool result — so the served MCP surface snapshot is unchanged (the labels and rule ride result values, not tool descriptions/schemas). `_built/` was rebuilt from the `.s0ma` sources and the `selfhost-build` byte-equality gate stays green.
- **Every improvement-telemetry record is now self-describing — a `telemetry_schema: "s0ma-telemetry@2"` marker on every JSONL record (batch-01c M3, P1, interop debt):** the env-gated telemetry hook (`S0MA_MCP_TELEMETRY`, 0.10.0) appends one JSONL line per served call, and since 0.11.0 M4 each line carries a derived `counters` list — but the records carried no schema/version marker at all (deliberate byte-minimalism at the time), so a consumer had to shape-sniff to recognize one. The counter-evidence: the bench's guardrail-counter table rendered all-n/a for batch-01c because its detector didn't recognize the 0.11.0 `counters` key, and the bench had to fix its detector by keying on `counters`-presence (s0ma-bench `33c535a`). Consumers should not have to shape-sniff. Every record now **leads** with a `telemetry_schema` field carrying the constant `"s0ma-telemetry@2"` — a module-level `_TELEMETRY_SCHEMA` beside `_telemetry_counters` in the one handwritten bootstrap module (`s0ma_mcp/__init__.py`), stamped as the first field on **every** record, including zero-counter events. Discipline: consumers key on the tag; the `@N` suffix bumps ONLY on a breaking record-shape change (a removed/renamed key or changed value semantics — additive fields do not), `@2` is the first MARKED shape (0.11.0's unmarked, counters-bearing shape is the implicit `@1`), and `counters`-presence stays the documented fallback for recognizing a pre-marker `@1` record. The stable record contract — the keys, the four counter names (`runbook_read`, `inline_rule_impression`, `refused_overwrite`, `drift_shown`), and the tag discipline — is documented in a new **`## Telemetry (env-gated, agent-invisible)`** section of the s0ma-mcp README. The 0.11.0 M4 byte-invisibility invariant is untouched: the marker (like the counters) lives ONLY in the JSONL sink and only when the hook is on — the record itself only exists then, the flag-off provider is returned untouched, and the wire responses stay byte-identical with the hook off vs on. `test_telemetry_invisibility.py` is extended (the marker on every record incl. zero-counter events; the flag-off/flag-on byte-identity preserved) and the schema-tag contract value is pinned in `test_telemetry_counters.py`. No `.s0ma` source changed — the hook is handwritten bootstrap-module code — so `_built/` and the served MCP surface snapshot are untouched.
- **The patterns guide teaches durable-state migrations, and a seventh survival rule carries the discipline inline (batch-01c M4, P2 — teaching only, no analyzer):** the batch-01c cold CM6 crater (`P2_P_haiku45_r03`) had two halves — M2 closed the attribution gap (the agent dismissed its own NEW failures as "pre-existing"); this closes the other half, the substance of the crater. A schema change shipped without a migration for existing data: an `actor` column was added only to the `CREATE TABLE IF NOT EXISTS audit_log` creation DDL, which is a no-op on the donor's already-existing database, so every mutation's `INSERT … actor` 500'd — a change that works on a fresh database and is fatal on a lived-in one, exactly the class cold-start batteries exist to surface (fresh agent, existing state). The patterns guide gains a new **§24 Durable-state migrations** (served as `s0ma://guide/patterns`): it names the `CREATE TABLE IF NOT EXISTS` anti-pattern, contrasts the wrong (creation-path-only) shape with the right one (the creation path **plus** a guarded `ALTER TABLE` for a database, or a rewrite-on-load for a file format), cites the CM6 case, and distils the check to one question — *"would this work on a database created by yesterday's version?"*. The inline survival ruleset (`_SURVIVAL_RULES`, carried in the `init_project` / `scaffold_module` / `describe_server` results) gains a **seventh rule**: a change to durable-state shape needs a migration for existing data — a creation-path-only edit (`CREATE TABLE IF NOT EXISTS`, a first-write default) is a fresh-state-only fix, fine on a new store and fatal on a lived-in one. Scope is teaching-only by owner gate: no `check` heuristic (e.g. flagging a column reference that appears in no `CREATE`/`ALTER`) is added — one occurrence (n=1) is not yet evidence for a static analyzer, which stays a 0.13.0 candidate pending a second occurrence. Adding §24 renumbered the guide's Project-standards block §24–29 → §25–30 (headings, sub-sections, and every internal §-cross-reference moved in lockstep), and every **live cross-file reference** to the old numbering moved with it: the quick reference (4 sites — the archetype pointer §24.5→§25.5, the five named standards §24–§28→§25–§29, the `new project` table row, the `score` row §29→§30) and the agent system prompt (§24–§28→§25–§29) among the served docs, plus `cli/new_project.py` (the §refs its scaffold stamps into generated AGENTS.md and the app-map writer docstrings, §28.1→§29.1) and `cli/score.py`/`test_score.py` (the boundary-doctrine §27.2→§28.2 citations) in code. Shipped-release changelog entries and `plans/` documents keep their original numbers — they are historical record, correct as written at their release dates. The drift gates byte-compare the packaged `s0ma_mcp/_docs/` copies against their sources; all three edited served-doc mirrors (patterns guide, quick reference, system prompt) were re-copied byte-identical. The served MCP surface snapshot is unchanged (the rule rides the inline `rules` result value, not any tool description or schema); `_built/` was rebuilt from the `.s0ma` sources and the `selfhost-build` byte-equality gate stays green.

### Changed

- **The runbook surface frames an undeclared runbook as a documentation gap, never a service fault (batch-01c M1, P0):** in bench batch-01c warm O3 (`P2_P_haiku45_r02` — an env-var fault injected, the service misbehaving) the agent read `s0ma://project/runbook`, saw `runbook_declared: false`, and concluded the *absence of a declared runbook was the root cause* — the only `incorrect` detection verdict in its cell. The 0.11.0 runbook resource deliberately serves a teaching variant when nothing is declared (correct — the same run's O5 shows the intended runbook → run-command happy path, so the surface earns its keep), but the wording let a mid-diagnosis agent mistake a documentation gap for a service defect. The undeclared and partially-declared runbook renderings (`resources.s0ma` `_render_runbook`) now **LEAD** with an explicit not-a-fault disclaimer — *"No runbook fields are declared. This is a documentation gap, never a service fault — the absence of a runbook cannot break or degrade a running service. If you are diagnosing a failure, diagnose from observed behavior, configuration, and environment; declare a runbook afterward"* — with a partial-state variant for a half-declared runbook; a fully-declared runbook carries no disclaimer (nothing absent to mistake for a fault). The `project_status` `runtime` section's `hint` beside `runbook_declared: false` (`tools.s0ma` `_runtime_section`) leads with the same not-a-fault semantics. The inline survival ruleset (`_SURVIVAL_RULES` — carried in the `init_project` / `scaffold_module` / `describe_server` results) gains a fifth rule: diagnose runtime faults from observed behavior, configuration, and environment; a missing runbook/doc/config *declaration* is never the root cause of a fault, only follow-up documentation work. A runbook is deliberately NOT auto-scaffolded in `init_project` (it would fabricate run/health commands the author never stated, and the teaching variant already covers discovery). The served MCP surface snapshot is unchanged — the disclaimer rides the rendered runbook text, the runtime `hint`, and the inline `rules`, none of which are client-visible tool/resource descriptions or schemas; `_built/` was rebuilt from the `.s0ma` sources and the `selfhost-build` byte-equality gate stays green.

### Fixed

- **`.s0ma` source discovery no longer chokes on a `.s0ma` working-state directory (batch-01c M2):** `rglob("*.s0ma")` matches a *directory* named `.s0ma` as well as `*.s0ma` files, so once a `.s0ma/` directory exists at or under a source root (the new check baseline, or the long-standing `.s0ma/registry.db` persistence), `s0ma check` / `build` handed the directory to the parser and died with an internal `Is a directory` error. Discovery (`_discover_s0ma_files` and the manifest-less inspect fallback in the DSL, plus the transpile tool's artifact walk in the MCP) now filters to real files. Latent before M2 (nothing wrote `.s0ma/` during a check/build in the same tree); the baseline surfaced it, and the guard closes it for the persistence dir too.

## [0.11.0] — 2026-07-14

**The batch-01a fix wave.** The first benchmark batch against the pinned 0.10.0 server (ARM-P, batch-01a) surfaced a cluster of authoring failures past the bootstrap cliff 0.10.0 closed: agents subscripted imported module objects (a factory-dict workaround that compiled clean and detonated at runtime), the build silently reverted hand-edited generated files, stdlib-named modules could not bootstrap, agents invented multi-function workarounds for the one-def-per-body rule, unregistered plain-Python files grew invisible to every measurement (the hollow-model case), and live application state was git-reverted as if it were source. This release lands the fixes as one batch (per the batch protocol, one version bump before batch-01b): three guards stop the silent detonations — `MODULE_SUBSCRIPT`, the build's refuse-to-clobber `GENERATED_FILE_DRIFT` (with `--force`) plus a `check` drift pass, and `MODULE_SHADOWS_STDLIB` with collision-safe emitted imports (M1); the survival rules and the real multi-function pattern are taught in-band — in the result payloads and the patterns guide/scaffold — where agents broke them (M2); adopted files become first-class — `s0ma adopt file` / MCP `adopt_file`, verified and scored — so hollow-model growth is visible and measurable (M3); and an operational runbook (`s0ma://project/runbook` + `[tool.s0ma]` ops keys), the live-state ops rule, and env-gated improvement-telemetry counters teach the runtime-state discipline and instrument the next batch (M4). The language and IR schema are unchanged; the served MCP surface changes are deliberate and the snapshot is regenerated with them.

### Added

- **`MODULE_SUBSCRIPT` — the module-object subscript guard (batch-01a M1, B1):** a bare `uses: [registry]` entry emits `import registry`, binding a *module object*, not a component. Nerve bodies are emitted verbatim (`parser/body_extractor`), so an author-written `registry["get_op"]` compiles cleanly and detonates at runtime as `TypeError: 'module' object is not subscriptable` — the factory-dict confusion that took bench run `P1_P_r02` to 1/24 acceptance. The intra-module validator now flags a subscript of a bare-`uses:` module object (error in every mode) with remediation pointing at the real fix — import the symbol with `uses: [module.symbol]` (which emits `from module import symbol`), or expose a module-level `helper` via `exports_helpers:`. The guard keys on module-object resolution only: dotted `uses: [module.symbol]` from-imports a component (never flagged), and a body-local rebind of the name (`registry = registry_factory()`) suppresses the finding, so legitimate dict subscripts are never rejected. A dedicated regression fixture (`fixtures/module_subscript_regression/`, shaped after the detonating bench workspace — a factory-dict `registry` plus a `cli` consumer that subscripts the module object) pins the failure.
- **The build refuses to silently overwrite hand-edited generated files + `--force` + a `check` drift pass (batch-01a M1, B2):** a generated `.py` carries `# s0ma-output-hash: sha256:<h>`; if the file is edited by hand the recomputed hash no longer matches, and the next `s0ma build` used to silently revert the edit — the silent revert that detonated bench run `P1_P_r02` (M-INTEG 0/7). The verify hash-compare is factored into shared emitter helpers (`is_hand_edited` / `recompute_output_hash` / `embedded_output_hash`) so `s0ma verify`'s `EDITED` classifier, the build write-guard, and `check`'s new drift pass all detect a hand edit identically. `s0ma build` / `s0ma transpile` now **refuse** (`GENERATED_FILE_DRIFT`, exit non-zero) to overwrite a hand-edited generated file — "`<file>` was edited by hand; generated files are overwritten on every build. Move changes into src/\*.s0ma, or pass --force to discard them." — unless the new `--force` flag is passed (which also bypasses the incremental cache so the file is actually regenerated). `s0ma check` gains a `GENERATED_FILE_DRIFT` **warning** pass over the build dir that surfaces the same hand edit before the next build would clobber it. The MCP `build_project` tool threads a `force: bool` argument through to `s0ma build --force`; the served surface snapshot is regenerated for exactly that one new input property + description. A file with no embedded output-hash (a bootstrap module, a hand-written `.py`) is never generated and never accused. The `selfhost-build` stage rebuilds `_built/` in place every run and stays green: the committed generated files are byte-clean, so `is_hand_edited` returns false and the write-guard is silent (no `--force` needed in the stage).
- **`MODULE_SHADOWS_STDLIB` + collision-safe emitted imports for stdlib-shadowing modules (batch-01a M1, B3):** a s0ma module named after a Python stdlib module (`io`, `json`, `csv`, …) cannot be imported by its bare name — the stdlib module is already resident in `sys.modules` at interpreter start, so `bootstrap_imports` / `importlib.import_module` returns the *stdlib* module and cross-module `uses:` resolution fails at runtime (a module named `io` forced the batch-01a agent into a hand-written `importlib` shim). The validator now flags a stdlib-shadowing module name (`MODULE_SHADOWS_STDLIB`, warning in migration/dev, error in strict/release — the project cannot bootstrap and must not ship), `s0ma new module <stdlibname>` warns at scaffold time (to stdout, so the MCP `scaffold_module` tool surfaces it too), and the emitter emits a **collision-safe sibling-file load** for a `uses:` entry that targets a shadowing module (loading the built sibling `.py` from the consumer's own package directory under a mangled key, bypassing the stdlib cache and leaving the real stdlib module untouched) so a dev build's emitted code runs without a hand shim. The emitted change is byte-identical for every non-shadowing project — including the entire self-host tree, which has no stdlib-named modules — because the sibling-load path only triggers on a `uses:` entry whose module name is in `sys.stdlib_module_names`.
- **The survival rules travel in the result payload, not only behind a URI (batch-01a M2, D1/O2):** pilot-01 read `s0ma://guide/survival-card` in 2 of 6 runs, and the run that needed it most read nothing — a first-pointed resource is only teaching if it is opened. The compact ruleset is now embedded literally (a new `rules` key) in the `init_project` result (both the freshly-initialized and the idempotent already-a-project answers), the `scaffold_module` result, and the `describe_server` result, so the rules arrive in the payload the agent already has. The four rules: (1) only edit `.s0ma` sources — never edit generated files under `build/`; the build now REFUSES to overwrite a hand-edited generated file (`GENERATED_FILE_DRIFT`, M1) and otherwise overwrites it every build; (2) a nerve body is exactly ONE `def`, with imports declared in the module header's `requires:` (the transpiler emits them), never written in the body; (3) after editing a `src/*.s0ma` file, run `check` then `build_project`; (4) the ops rule (O2, landed here on M2's rebuild per the batch plan's sequencing) — live state is the deliverable: demonstrate fixes on the durable instance, and never restore committed versions of runtime data. The `s0ma://guide/survival-card` pointer stays alongside the inline rules (pointer plus payload, not pointer alone).
- **The patterns guide teaches "real logic in modules", and `scaffold_module` scaffolds it (batch-01a M2, D3):** the batch failure mode was agents inventing a factory-dict workaround for the one-`def`-per-body rule — stuff many functions into a returned dict, consume it from another module with a bare `uses:` entry, then subscript the imported *module object* (the `MODULE_SUBSCRIPT` detonation, M1). A new patterns-guide section (`§15.5 Real logic in modules`, served as `s0ma://guide/patterns`) names the anti-pattern (the factory-dict trap), shows the exact `MODULE_SUBSCRIPT` diagnostic it now triggers, and teaches the three real mechanisms keyed by what the operations are: a `SERVICE` nerve with `provides:` (a factory whose *caller* subscripts the returned dict, never a module), independent operations as one exported nerve each imported with a dotted `uses: [module.symbol]`, and module-private plumbing as a `helper` with `exports_helpers:` (reachable only from a test-context consumer — a production module consuming another module's helper is `HELPER_PRIVATE_TO_MODULE` even when re-exported). A one-paragraph version rides the survival card. `s0ma new module` / the MCP `scaffold_module` tool now scaffold the multi-function factory skeleton when `kind: SERVICE` (the default kind): a structured `provides:` block plus a factory returning a matching dict, check-clean in strict mode, with the trap named inline in the body — so the sanctioned shape is the starting point instead of the workaround. The pilot-01 body-rule comment teaching is preserved above the factory.
- **First-class adopted files — `s0ma adopt file` + MCP `adopt_file` (batch-01a M3, D2; owner-decided: adopt, not warning-only):** bench run `P2_P_r02` grew from one to six unregistered `_impl.py` files beside generated code with verify green throughout — the hollow-model case: real files the model knows nothing about, invisible to every measurement. Adoption makes such files first-class: `s0ma adopt file <path>` (and the new MCP `adopt_file` tool — mutating, non-destructive, idempotent) records the file's project-root-relative POSIX path + current content hash in a new committed sidecar at the project root, `adopted.s0ma.json` (schema `s0ma-adopted-files@1`, deterministic bytes — the `build.s0ma.json` JSON-family idiom; chosen over the gitignored `.s0ma/registry.db` (not reviewable), `[tool.s0ma]` keys (machine-rewritten hashes don't belong in hand-authored config the toolchain can't round-trip), and build-dir artifacts (derived output; adoption records are authored state)). `s0ma verify` gains two classifications: `ADOPTED` (content hash matches the record — a *verified* state: counted in the summary/coverage lines, and an adopted-only tree is no longer "nothing verified") and `ADOPTED_DRIFT` (the file changed since adoption — an actionable FAILURE, exit 1, whose message names both ways out: re-adopt via `s0ma adopt file <path>` / MCP `adopt_file`, or convert the file to a `.s0ma` source). `s0ma score`'s registration ratio counts adopted files as registered — before: `hash-bearing / (hash-bearing + unknown)`; after: adopted files move from the `unknown` term into the registered term — so the hollow-model ratio deflates only for genuinely unknown files, and the detail string names the adopted share (`N registered (A by adoption), …`). `s0ma inspect --all` lists adopted files with their recorded hashes (marking records whose file is missing on disk), and the MCP `project_status` result gains an `adopted_files` listing. Adoption refuses (nothing written): paths outside the project root, transpiled artifacts (already registered through their `.s0ma` source), and files declared under `bootstrap_files`/`package_markers` (one classification per file, the `CONFLICTING_PACKAGE_DECLARATION` stance). In `s0ma-core`, a new `AdoptedFile` model + `ComponentRegistry.register_adopted_file()` (idempotent, SQLite-persisted, in `RegistrySnapshot.adopted_files`/`describe()`/`to_dict()`) is the runtime primitive (framework component count 60 → 61). Scope interlock: the brownfield adoption plan owns the conversion ladder and the reserved `adopt scan/draft/baseline/verify-parity` sub-commands — this is only the per-file primitive they build on.
- **The operational runbook — `s0ma://project/runbook` + `[tool.s0ma]` ops keys + `project_status` runtime section (batch-01a M4, O1/O2):** in both batch-01a P2 runs the agent git-reverted the live application database — treating the committed version of runtime state as the deliverable and destroying real data (ARM-P remediation 0.375 vs 0.75). The ops story is now taught in-band. `S0maProject` gains five optional `[tool.s0ma]` keys: `run_command` and `health_command` (strings), `state_paths` (a list of project-relative paths that hold **runtime state — data the app owns and produces, NOT derivable from source, and which must never be reverted, restored from a committed version, or regenerated**), `runbook_notes` (a string or a list of strings), and an `env` mapping (`[tool.s0ma.env.<NAME>]` subtables, each a `required`/`fail_fast`/`default` contract). All optional; every shape error is a load-time `ValueError` in the existing `[tool.s0ma]` style. A new MCP resource `s0ma://project/runbook` (the first `project/*` resource, `text/markdown`) renders those fields plus the module inventory and an **ops-rules section** carrying the O2 rule ("live state is the deliverable … never restore committed versions of runtime data" — the same rule that landed inline as `_SURVIVAL_RULES[3]` on M2) and the `state_paths` semantics; it resolves the project from the server's working directory (the blessed `claude mcp add s0ma --scope project -- uv run s0ma-mcp` runs the server with cwd = the project) and, when no project or no runbook keys are found, still serves — teaching exactly what to declare and where (never an error, never empty). The `project_status` result gains a `runtime` section: `run_command`, `health_command`, the env summary (declared / required / `missing_required_env`, read from the live process environment by variable NAME only — a declared default or a live value is never read into the result), `state_paths`, `runbook_notes`, and `runbook_declared`; an undeclared runbook yields a `hint` pointing at the runbook resource. The served surface snapshot is regenerated for exactly the new resource entry and the one `project_status` description change; no other surface changed.
- **Improvement-telemetry counters for the batch-01a signals (batch-01a M4, P2):** the env-gated, agent-invisible telemetry hook (`S0MA_MCP_TELEMETRY`, 0.10.0) now records a derived `counters` list on each JSONL call record — computed purely from the `(surface, name, result)` the wrapper already sees, so the tags live ONLY in the JSONL and only when the hook is enabled. Four signals the batch-01a verification plan watches: `runbook_read` (a read of the new `s0ma://project/runbook` resource), `inline_rule_impression` (a tool result carrying the inline survival `rules` — `init_project` / `scaffold_module` / `describe_server`), `refused_overwrite` (`build_project` surfacing `GENERATED_FILE_DRIFT` — the B2 refusal to clobber a hand-edited generated file), and `drift_shown` (`check` surfacing it — the M1 warn pass). No tool result gains a counter-specific field, so the agent-facing payloads are unchanged: the invisibility contract holds byte-for-byte when the flag is off, and `test_telemetry_invisibility.py` is extended (a real-stdio read of the runbook resource proves the `runbook_read` counter reaches the sink and nowhere else) alongside a new `test_telemetry_counters.py` pinning the per-tag derivation matrix.

### Changed

- **`describe_server` leads with the survival rules, and failing diagnostics deep-link each code (batch-01a M2, D1/P2):** the `describe_server` result now leads with the compact `rules` ruleset before the surface inventory (the self-model graph), so an agent orienting via the tool reads the rules first. Every failing `check`/`transpile`/`build_project` result's `error_help` now emits a per-code deep anchor into the error catalog — `s0ma://guide/errors#<CODE>` for each diagnostic code returned — so a failure points at each code's own entry (the exact code is findable at that anchor in the served flat-table catalog text), instead of one undifferentiated "look these up" line; the `s0ma://guide/survival-card` pointer stays alongside. A shared `_lead_with_cause` helper generalizes the 0.10.0 lead-with-cause fix (which separated the CLI's advisory "Operating without project discovery" warning from the actual cause on a duplicate scaffold) to every tool that surfaces raw CLI output — `inspect_module` and the diagnostics-result stderr fallback now put any advisory line last so the cause always leads. The served surface snapshot is regenerated for exactly the three tool descriptions touched (`init_project`, `scaffold_module`, `describe_server` — the inline-rules and SERVICE-skeleton notes); no schema, annotation, or name changed. (The batch memo's D4 ask — end-to-end MCP tool annotations — was verified already shipped in the `0.10.0` batch commit and present in the pinned server, so no annotation plumbing changed here.)

## [0.10.0] — 2026-07-06

**The pilot-01 adoption-cliff release.** Six benchmark agent runs against the pinned 0.9.0 server (ARM-P, batch-01) showed one failure shape: adoption has a cliff at bootstrap and nowhere else — once a project existed, the check/build loop ran with zero protocol errors, but 3 of 3 cold-start agents never got a project going, and every bounce point was a specific string in the product. This release lands the pilot's improvement memo as one batch: the bootstrap dead-end is closed with a real tool (`init_project`), the two killer body rules are taught at the exact moments agents broke them (the scaffold template, the tool description, and the PARSE_ERROR remediation), the contradictory BARE_IMPORT remediation pair is sequenced, `s0ma verify` stops passing vacuously on trees with nothing to verify, teaching content gains a genuinely small entry point (`s0ma://guide/survival-card`) that failing tool results now cite, and an env-gated, agent-invisible telemetry hook makes the next batch's analysis largely automatic. Language and IR are unchanged; the served MCP surface changes are deliberate and the snapshot is regenerated with them.

### Added

- **`init_project` MCP tool — the bootstrap step no tool performed (memo P0-1):** pilot-01 reproduced a loop with no exit: `project_status` on a bare directory said "call scaffold_module", but scaffolding never creates the `[tool.s0ma]` table, so `scaffold_module` ok → `build_project` ok (silent legacy mode, no manifest) → `project_status` still `is_project: false` with the same suggestion — the CLI's `s0ma new project` exists but is not reachable over MCP, and headless agents cannot invoke MCP prompts. The new tool writes the canonical `[tool.s0ma]` table (`source_roots = ["src"]`, `test_roots = ["tests"]`, `build_dir = "build"`, the requested `mode`, `authoring = "on"`) into `<project_root>/pyproject.toml` — appended byte-preservingly when the file exists (the original content stays a strict prefix), created minimal when it does not — via the dsl's own `_tool_s0ma_table` writer (one source of truth with `s0ma new project`). Idempotent: an already-initialized project answers `{ok: true, changed: false}` and rewrites nothing; a malformed existing table or non-TOML pyproject is a structured refusal. Annotations: mutating, non-destructive, idempotent, closed-world. The full bootstrap loop (`init_project` → `scaffold_module` → `build_project` → `project_status` reports `is_project: true` with a manifest) is pinned by new round-trip tests.
- **`s0ma://guide/survival-card` — teaching content a small model can actually read (memo P1-5):** pilot-01 recorded ONE successful teaching read across six runs, and it nearly failed: the first-pointed guide was 89 KB (~22k tokens) against an instructions string that called it "one page". The new survival card is a genuinely ~2 KB resource — the bootstrap loop, the three rules that prevent most authoring errors, one minimal valid module, and the recovery move for the top diagnostic codes — served first in the instructions string and cited by `project_status`, `init_project`, and failing diagnostics results. Its context-economy contract is pinned by a release-gate test (under 4096 bytes served). Source: `packages/s0ma-dsl/docs/survival_card.md`, packaged under `s0ma_mcp/_docs/` behind the standing byte-compare drift gate.
- **Failing tool results cite the teaching resources (memo P1-5):** `check`/`transpile`/`build_project` failures now carry an `error_help` key naming the exact diagnostic codes returned and the resources to look them up in (`s0ma://guide/errors`, `s0ma://guide/survival-card`). Pilot-01 counted ~40 failing check/build events and zero reads of the error catalog — no tool response referenced any `s0ma://` URI; now the reference arrives attached to the failure it explains. The DSL's structured diagnostics themselves remain byte-for-byte the CLI's (FR-MCP-2) — the citation is additive alongside them.
- **`S0MA_MCP_TELEMETRY` — env-gated, agent-invisible call telemetry (memo P1-6, test plan §6):** the serving loop in `create_server` now routes every tool, resource, and prompt binding through `_telemetry_wrap` in the bootstrap module. Default off = the provider is returned untouched (identical object, provably zero delta). On, it appends one JSONL record per call ({surface, name, ok, ms, size, sanitized args}) to a file sink — `S0MA_MCP_TELEMETRY_SINK`, defaulting under the user cache dir; never stdout (stdio transport) — with `functools.wraps` applied after `_served_as`/docstring normalization so FastMCP's derived schemas and descriptions are byte-identical, and results/exceptions passing through unmodified (a failed append drops the record, never the call). The hook is deliberately UNREGISTERED in the self-model — a documented FR-MCP-7 exception: a cataloged component would change `describe_server`/`s0ma://self/model` payloads, the exact visibility it must not have. A new smoke test (`test_telemetry_invisibility.py`) spawns the real console script twice over stdio — flag off vs on — through an identical canned session (initialize, the three lists, a succeeding tool call, a structurally-failing tool call, a resource read) and asserts the response BYTES are identical, the sink is well-formed and populated only when on, and the wire tool set equals the committed snapshot. Resource-fetch records give the bench's teaching-signal for free. Honest scope limit: calls FastMCP's schema validation rejects never reach the provider, so malformed-call telemetry would need SDK middleware — deferred.
- **`s0ma verify` exits 4 when there is nothing to verify (memo P1-4):** a tree with zero transpiled s0ma modules — e.g. a plain-Python project — used to print "Verified 0 module(s)… All files are clean." and exit 0, which silently made a headline pilot metric (M-INTEG median 1.00 for the abandoning arm) 100% vacuous. New `EXIT_NOTHING_VERIFIED = 4` fires in both the text and JSON output paths when no file carries s0ma hash headers (BOOTSTRAP/PACKAGE_MARKER-only trees included — deliberate: exit 0 now always means "verified ≥ 1 module, clean"); drift findings still win with exit 1, and the JSON document shape is unchanged for existing consumers. The text path additionally prints an always-on coverage line — verified s0ma modules vs unregistered plain-Python files — so the pilot's *hollow-model* case (a `.s0ma` husk checking green while all logic lives in plain `.py`) is visible at a glance instead of invisible by construction.

### Changed

- **`project_status` non-project answer names the actual bootstrap (memo P0-1 — the single highest-value string in the product):** it is the one s0ma response guaranteed to be in context at the adoption decision moment, and it used to read as permission to skip ("not a s0ma project — call scaffold_module or the author_module prompt" — the first half looped forever, the second half is inert for headless agents). It now states the two-step bootstrap concretely — (1) `init_project` adds `[tool.s0ma]` (minimum `source_roots = ["src"]`), (2) `scaffold_module` creates the first module, then check → build_project — and cites the survival card. Both `project_status` branches also gain a one-line `note` steering agents to verify edits via the MCP `check`/`build_project` tools rather than shelling out to a `s0ma` CLI that is usually not on PATH in agent environments (pilot-01: four distinct sessions tried the CLI, failed, then edited `.s0ma`/generated files without any verification — memo P2-9).
- **`scaffold_module` teaches the two killer body rules and stops swallowing the onboarding warning (memo P0-2, P0-1):** the DSL's module/nerve scaffold templates now carry comment lines above the body's `def` stating the rules the only genuinely-trying pilot agent broke twice and then quit over — the body stays exactly ONE `def`, and imports are declared in the module header's `requires:` (the transpiler emits them), never written in the body. The tool description states the same rule and that scaffolding does not make a directory a project. On success the tool now forwards the CLI's warnings (previously stdout/stderr surfaced only on failure, so the "Operating without project discovery — add `[tool.s0ma]`…" hint was dropped exactly on the happy path that needed it) plus, on a non-project directory, an explicit `{project: false, hint: call init_project}`. Error payloads now lead with the actual cause instead of an advisory warning line (pilot-01's duplicate-scaffold error opened with the project-discovery warning, burying "File already exists").
- **PARSE_ERROR remediation teaches the rule instead of restating the message (memo P0-2/P0-3):** the worst-recovering diagnostic in the pilot catalog (42% next-check resolution; byte-identical twice for the agent that abandoned) used to say only "Wrap the body of nerve 'X' in a 'def X(...)' function". The remediation is now state-aware — when the body contains import statements alongside a `def` (the exact observed failure: pasting a normal Python module into a nerve body) it leads with that diagnosis and the two-part fix — and in all cases includes the single-def rule, the imports-go-in-`requires:` rule, and a compact valid example. Message text, code, severity, and context keys are unchanged (transcript analytics key on the message).
- **The BARE_IMPORT remediation pair reads as one sequenced fix, not a contradiction (memo P0-3):** pilot agents followed "add X to `deferred_requires`" and then received "already declared … remove the bare import" — state-correct but reading as a reversal, driving multi-turn thrash in two sessions. The not-yet-declared variant now states the fix as ONE edit with two parts (declare in the header AND delete the body import); the already-declared variant names the actual list the entry sits in (instead of a four-way parenthetical) and frames the remaining step as step two of the same fix. The `ERROR_CODE_DESCRIPTIONS` entry and the generated error-catalog table are regenerated to match.
- **Instructions string gains a when-to-start trigger and honest reading guidance (memo P2-7, P1-5):** the served instructions now open the loop with a trigger condition ("When the task is to build or extend an application as a s0ma app: call project_status first; if it is not yet a project, call init_project…"), point at the ~2 KB survival card first (the false "one page, kept context-economical" claim about the 89 KB quick reference is gone — its resource description now says plainly it is large and comprehensive), and name `s0ma://guide/errors` as the lookup for diagnostic codes.
- **`build_project` says so when it builds in legacy mode (memo P2-8):** without a `[tool.s0ma]` table the build used to succeed silently with no manifest — three green `ok: true` results for work the self-model machinery cannot see. A successful manifest-less build now carries a warning naming the consequence (project_status/inspect_module will not see it) and the fix (`init_project`), and the tool description states the fallback honestly.
- **Scaffold names with consecutive capitals stop degrading (memo P2-10):** `CLI` scaffolded as `c_l_i.s0ma` (module `c_l_i`), `IO` as `i_o.s0ma`. The snake-casing (one shared `_snake_case` helper in the dsl CLI, reused by the MCP tool so the filename lookup cannot drift) now collapses consecutive capitals: `CLI` → `cli`, `IOHandler` → `io_handler`, `HTTPServer2` → `http_server2`; ordinary PascalCase is unchanged.
- **`serverInfo.version` reports s0ma-mcp's version (memo P2-10):** the MCP initialize response used to carry the MCP SDK's version (e.g. "1.27.2") because FastMCP defaults it — misleading next to `s0ma://meta/version` reporting the real package version. The factory now stamps the installed package version on the underlying server.
- **The served MCP surface snapshot is regenerated** for exactly the deliberate changes above (the new tool + resource, the description edits); the surface-snapshot gate reviewed them as one diff, per its standing contract.
- **PRD v1.5 — NFR-5 amended (owner-ratified, 2026-07-08):** "quick reference stays one page" — falsified empirically by pilot-01 (the reference had grown to ~90 KB and the one agent that trusted the served "one page" claim overflowed its context) — is replaced by the requirement this release actually enforces: *the first-pointed teaching resource stays context-economical (≤ 2 KB, gate-enforced — the survival card)*; comprehensive references may grow but must be honestly sized where they are pointed to and consulted per-topic. The release-gate size test on `s0ma://guide/survival-card` is the enforcement of the amended requirement.

## [0.9.0] — 2026-06-17

**The s0ma standards & usability upgrade.** s0ma is repositioned as a software **self-knowledge** platform — the umbrella spanning three faculties (proprioception / structure, interoception / runtime state, metacognition / reasoning) — and the first hour of building a s0ma application is rebuilt around a consistent, navigable shape. New users get a single-command installer (`sh scripts/install.sh <dir>`), a feature-first `s0ma new project` that ships an AGENTS.md and a drift-gated app map out of the box, three `--template service|library|cli` archetype starters that each build and pass the release gate, an `s0ma score` that turns a project's self-knowledge into one visible number plus a per-faculty breakdown (the flagship `s0ma-mcp` self-host scores **100%**), and a first-class `[tool.s0ma].authoring` on/off switch with an agent confirmation handshake. The build manifest now records each module's logical position in the source tree, and the project standards (feature-first layout, placement-not-architecture, naming conventions, the boundary doctrine, the app-map pattern) are now canon in the served agent corpus. Every change is additive and behaviour-invariant for existing projects; the language and IR schema are unchanged from 0.8.0.

### Added

- **A single-command installer collapses the 5–6-step wheel flow into one command — `sh scripts/install.sh <dir>` (standards/usability plan, M9; D-8 no network in product code / no toolchain coupling):** a new POSIX-`sh` convenience script (`scripts/install.sh`) takes a brand-new user from nothing to a built, MCP-registered, feature-first project in one invocation. It scripts the `docs/walkthrough.md` Route A end to end: create/enter the target dir; `gh release download <tag> -R kn0w-thyself/s0ma -p '*.whl' -D .wheels`; `uv init`; `uv add` the **three wheels explicitly** (their inter-dependencies name PyPI packages that do not exist there yet, so each must be named); `uv run s0ma doctor`; register the authoring MCP server with the verbatim walkthrough invocation `claude mcp add s0ma --scope project -- uv run s0ma-mcp` (skipped with a hint if `claude` is not on PATH); then `uv run s0ma new project .`, chaining into M6's feature-first scaffolder. The **version defaults to the latest published release**, resolved at run time from the GitHub Release (`gh release view --json tagName -q .tagName -R kn0w-thyself/s0ma`) so the script needs no per-release edit; `--version <tag>` pins a specific release and `--default-off` rides through to `new project` (scaffolding `[tool.s0ma].authoring = "off"`). Prerequisites are checked up front and **failures are loud and actionable**: a missing `gh` or `uv`, or an unauthenticated `gh`, each abort with a remediation (the repo is private → `gh auth login`). A **`--dry-run`** prints the exact command sequence it would run (wheel-download → `uv init` → `uv add` → `doctor` → `claude mcp add` → `new project`) and exits **without executing anything or touching the network** — the honest preview, and the basis of the CI-safe test. Per D-8 the installer is a script the *user* runs: nothing in `s0ma-core`/`s0ma-dsl`/`s0ma-mcp` imports or invokes it, and no product or test path performs real network I/O — the test (`packages/s0ma-dsl/tests/test_install_script.py`) only asserts `sh -n` parses the script clean and that `--dry-run` emits the expected sequence, skipping gracefully (`shutil.which("sh")`) where no POSIX `sh` is available. The README "Install" section and `docs/walkthrough.md` §1–2 now **lead with the one-liner** and the chained `install → new project → check` flow, keeping the manual wheel steps as the documented under-the-hood fallback.
- **`s0ma score` makes a project's self-knowledge a single visible number + a per-faculty breakdown — both an impact signal and a gateable boundary standard (standards/usability plan, M8; D-5 two readerships, D-7 compose-don't-rebuild, D-8 no network):** `s0ma score [<project>]` reports a **self-knowledge score** across the three faculties (§1.3) in human text and `--format json` rendered from the same structured data. It introduces **no new analysis engine** and never imports `s0ma-mcp` — every signal is *composed* from surfaces the toolchain already computes: the parsed `.s0ma` modules (the same `_parse_single_file`/`_validate_single_module` pipeline `s0ma check` uses), the dependency resolver's layer matrix, the release-mode doc/test coverage passes (`check_release_doc_coverage` + the `MISSING_TEST_COVERAGE` rule), the doc drift validator, the build manifest, and the `s0ma verify` drift classifier (dependency direction stays `mcp → dsl → core`). **Proprioception** (structure) = surface registration (% of the built `.py` surface that is registered `.s0ma` vs. residual `UNKNOWN` drift, with declared/auto-classified `BOOTSTRAP`/`PACKAGE_MARKER` files excluded — the exact `s0ma verify` classification) + layer compliance (no `CROSS_LAYER_DEPENDENCY`) + structural-verifier clean (no cycles / unresolved `uses:` / parse errors). **Interoception** (runtime state) reports an honest **`n/a — no resource profiles declared`**: declared resource profiles are a `s0ma-core` runtime concept with no `.s0ma` declaration surface, so the faculty is not measurable on a `.s0ma` project and is never fabricated as 0 or 100 (HONESTY rule). **Metacognition** (reasoning) = doc-ref coverage (% PUBLIC nerves a `doc-ref`'s `covers:` selects) + test coverage (% PUBLIC nerves satisfied by `tests:` or `covered_by:`) + drift-free (no `DRIFT_DETECTED`). The **exempt set is LISTED, not just counted** (M3 boundary doctrine §27.2): the closed four categories — the single handwritten bootstrap module, `[tool.s0ma].bootstrap_files`, `[tool.s0ma].package_markers`, and `@internal` components — are enumerated with their actual members so a reviewer sees exactly what sits outside s0ma. The **overall roll-up is the mean of the *available* faculties**; an `n/a` faculty is excluded from the denominator (never silently counted as 0% or 100%), and `gate.na_faculties` names which abstained. **Per-mode floors** (migration 0%, dev 50%, strict 75%, release 90%) are resolved with the standard precedence `--mode` flag > `[tool.s0ma].mode` > `dev`; the command is report-only by default (exit 0) and `--gate` exits non-zero below the floor. The implementation is a separate module `s0ma_dsl/cli/score.py` (the `doctor`/`migrate-ext` precedent); the JSON shape is `s0ma-score@1`. `s0ma score packages/s0ma-mcp` scores the flagship self-host at **100%** (proprioception 100, interoception n/a, metacognition 100). The formula is recorded in the command's `--help` and patterns guide §29 "Measuring self-knowledge". **Hand-off to M10:** the flagship's headline number is a release-notes candidate; the `s0ma-score@1` JSON shape is what the future visual explorer consumes.
- **`s0ma new project --template <service|library|cli>` scaffolds a complete, compiling archetype mini-app — the archetype *is* the design-pattern documentation (standards/usability plan, M7; Decision 4):** without a flag, `new project` still lays down M6's minimal single-feature starter; the three `--template` archetypes are **additive**, each a larger worked example that builds, passes `s0ma check --mode release`, runs its `.s0ma` tests, and (where it has one) runs its bootstrap — straight out of one command. **`service`** is a three-feature, three-layer service — DOMAIN `catalog` (a `Product` model + a pure `price_of` rule) → APPLICATION `ordering` (`submit_order`, which prices through the catalog) → PRESENTATION `api` (`handle_order_request`, the request boundary) — teaching **cross-feature `depends_on:` edges in the qualified `module.declaration` form** and the **layer reachability matrix** (PRESENTATION → APPLICATION → DOMAIN, never upward) in a project that passes the release gate, plus the boundary doctrine made executable: one sanctioned plain-Python `bootstrap/main.py` declared in `[tool.s0ma].bootstrap_files` (so `s0ma verify` classifies it `BOOTSTRAP`, not `UNKNOWN`). **`library`** is a layer-light, export-focused package (one DOMAIN feature: a slug core + a thin public facade) teaching **`exports:`** and **`covered_by:`** — the facade carries external-pytest-suite test credit that satisfies release-mode `MISSING_TEST_COVERAGE` with no in-language test — and notes that layer-first is acceptable for small libraries. **`cli`** is a thin-Python `argparse.REMAINDER` bootstrap shim (`bootstrap/cli.py`, including the leading-`--` strip) dispatching to a PRESENTATION router nerve over a DOMAIN/APPLICATION core, the documented thin-CLI → presentation-nerve handoff. Every archetype ships the feature-first layout, AGENTS.md + a thin CLAUDE.md (`@AGENTS.md`), the load-bearing app map (a registry-projected `doc-ref` + a three-faculty `doc-guide`, drift-gated), and starter `test`/`covered_by:` coverage. The archetypes reuse M6's scaffolding helpers (`scaffold_agent_files`, the `[tool.s0ma]` table writer) and live in a new `s0ma_dsl/cli/templates.py`; the orchestration (atomic refusal, byte-preserving pyproject append with `bootstrap_files`, first build of the whole project, text/`--format json` summary) is in `cli/new_project.py`. `--template` validates its choice (argparse rejects an unknown value); the JSON summary gains `template`/`features`/`bootstrap_files`/`teaches`. **Installer/README hand-off (M9/M10): demo `service`** — it is the most representative full application.
- **`s0ma new project` now scaffolds a feature-first project with an AGENTS.md, a thin CLAUDE.md, and a load-bearing app map — one command, building and `check`-clean (standards/usability plan, M6; Decision 2 feature-first; P-2 one source of truth):** the five-minute first impression now lays down the blessed shape out of the box. The layout is **feature-first** (patterns guide §24): a feature directory `src/<feature>/` (default feature `core`) holds one starter module `<feature>_<layer>.s0ma` — an underscore name because the filename stem must equal the dot-free `module` name (`core_domain.s0ma`, not `core.domain.s0ma`; dotted hierarchical names are the rejected Option A) — exporting one PUBLIC nerve, with a mirrored `tests/<feature>/<feature>_<layer>_tests.s0ma` that covers it. The project ships a project-wide, **load-bearing app map** (`src/app_map.s0ma`, the patterns-guide §28 template wired to the starter feature's real exported nerve): a `doc-ref` that auto-renders every PUBLIC nerve from the registry plus a `doc-guide` narrated around the three faculties of self-knowledge (structure / runtime state / reasoning), both drift-gated so the architecture map cannot rot. It writes **AGENTS.md** — the canonical, agent-agnostic standing rules (author components as `.s0ma` via the `s0ma-authoring` MCP server, never bare Python; the `project_status → scaffold → check → build` loop; the authoring-discipline block; the feature-first layout + naming conventions pointing at `s0ma://guide/patterns`; the STD-M4 confirmation handshake verbatim when authoring is on) — plus a **thin CLAUDE.md** that is exactly `@AGENTS.md` (the officially documented Claude Code import pattern: Claude Code reads CLAUDE.md and expands `@path` imports at session start, so one file is the single source of truth). AGENTS.md and the README quick-start both open with a one-time `@AGENTS.md`-import approval note so a user who would otherwise silently decline keeps the guidance. The `[tool.s0ma]` table is unchanged in shape (`source_roots`/`test_roots`/`build_dir`/`mode`/`authoring`; `--default-off` writes `authoring = "off"` and flips AGENTS.md to document the OFF posture). The first build now builds the whole project (`src` + `tests`), so a fresh project is fully built and `doctor`-clean (build status `fresh`, suggested next action `run s0ma check`) and passes `s0ma check` in every mode including `release`. The atomic-refusal contract is extended: `new project` refuses (changing nothing) if a starter file, the app map, **AGENTS.md, or CLAUDE.md** already exists. The printed and `--format json` summaries gain the new files (`feature`, `test`, `app_map`, `agents_file`, `claude_file`). The reusable scaffolding helpers (`scaffold_feature_layout`, `scaffold_app_map`, `scaffold_agent_files`, `_tool_s0ma_table`) are the foundation M7's `--template` archetypes build on.
- **The build manifest now records each module's logical position in the source tree — `source_root` + `logical_path` per module (standards/usability plan, M5; Decision 3 / Option B; D-3 determinism):** every `ModuleManifestEntry` in `build.s0ma.json` gains two additive, optional fields so tooling (the app map, the future explorer, `s0ma inspect`, and the M8 `s0ma score`) can present the source layout while the build directory stays flat — no hierarchical module-name DSL change, no build-dir nesting. `source_root` is the configured `[tool.s0ma].source_roots` / `test_roots` entry the module was discovered under, recorded as the project-root-relative POSIX string the author wrote (e.g. `"src"`, `"domain"`); `logical_path` is the module's source path relative to that root, POSIX (e.g. `"orders/orders_domain.s0ma"`, or `"order_model.s0ma"` for a top-level module). Both follow the SH-M1 / INV-5 contract for path-typed manifest fields — relative, forward-slash POSIX on every OS, never absolute, never CWD-dependent — so the committed-build equality gate byte-compares rebuilds across machines and operating systems. The **schema string stays `s0ma-build-manifest@1`**: both fields are additive and optional (older manifests omit them and load with the empty-string default; the loader derives nothing), so per the manifest's documented versioning convention `@2` is reserved for a breaking change. `ModuleManifestEntry.to_dict` omits an empty value, so synthetic-fallback builds (no `[tool.s0ma]` table to anchor against) and any module outside every configured root stay byte-identical to a pre-M5 manifest. `s0ma inspect` surfaces the structure in both the text output (a `Logical path:` line plus a `Source root:` line) and the `--format json` output (a `logical_structure` block carrying `source_root` + `logical_path`), read back from the manifest (the per-module IR does not carry it). The portability/byte-identity sweep auto-covers the new fields (both are PATH-classified in the schema-derived enumeration the F-M2-1 fix introduced, so they are swept for absolute prefixes, backslashes, and the project root), with explicit assertions that a nested `logical_path` records as multi-segment POSIX and that neither field carries a backslash or drive-letter/absolute prefix. The s0ma-mcp committed selfhost manifest was regenerated with the new fields (`source_root: "s0ma_src"`, `logical_path: "<name>.s0ma"` for all three modules); the `selfhost-build` byte-equality gate stays green and `_built/` changed only in `build.s0ma.json`.
- **A first-class `[tool.s0ma].authoring` on/off switch with an agent confirmation handshake (standards/usability plan, M4; D-3 selfhost, D-7 dependency direction):** projects can now declare an *authoring posture* that the `s0ma-authoring` MCP server reads to ask the agent to confirm it will build in s0ma before writing code. The dsl project model (`s0ma_dsl.project.S0maProject`) gains an `authoring: Literal["on", "off"]` field parsed from `[tool.s0ma].authoring`; the key defaults to `"on"` when absent (every project — including synthetic fallbacks — carries a definite posture, unlike the optional `mode`), and an unrecognised value is a load-time `ValueError` naming the supported set (the same loud-error style as `mode`/`test_layering`). The self-hosted `project_status` tool (`packages/s0ma-mcp/s0ma_src/tools.s0ma`) now returns the `authoring` posture in its structured result and, for an `"on"` project, leads `suggested_next_action` with the handshake — `"s0ma project; authoring is ON — confirm you will author components as .s0ma via this server before writing code"`; `"off"` projects keep the plain build/check guidance. `s0ma doctor` reports the posture in both the human `project` section and `--format json` (read straight off the dsl's own model — `s0ma-dsl` never imports `s0ma-mcp`, INV-6/D-7). `s0ma new project` accepts `--default-off` and writes the `authoring` key into the `[tool.s0ma]` table (`"on"` by default, `"off"` with the flag) so the key exists from M4 onward (the feature-first scaffolding that builds on it is M6). The selfhost build was regenerated from `s0ma_src/` (the `selfhost-build` byte-equality gate stays green; `_built/` changed only in the tools artifacts + manifest + the two regenerated `_built/docs/` references), and the MCP served-surface snapshot (`tests/snapshots/mcp_surface.json`) was regenerated for the one deliberate `project_status` description change.
- **The s0ma project standards are now canon in the served agent corpus — feature-first layout, placement-not-architecture, naming conventions, the boundary doctrine, and the app-map pattern (standards/usability plan, M3; D-4 `_docs` law):** the five conventions that M5–M8 implement and that coding agents inherit are written where agents actually read them. The patterns guide (`s0ma://guide/patterns`) gains five sections — **§24 Project layout (feature-first)** (top-level dirs are features; one `.s0ma` module per layer within a feature, named `<feature>_<layer>` because the filename stem must equal the dot-free module name — `orders_domain.s0ma`, not `orders.domain.s0ma`; `tests/` mirrors features; layer-first documented as the small/library alternative; the feature→layer-is-cheap / layer→feature-is-painful asymmetry as the rationale), **§25 Placement, not architecture** (PRD P-9 expanded: s0ma fixes placement and enforces the layer reachability matrix — cited to `s0ma_dsl/resolver/dependency.py` — but never prescribes an app architecture; users bring DDD/ports-and-adapters/etc.), **§26 Naming conventions** (docs-only per the owner decision: `_tool`/`_resource`/`_prompt` served suffixes with `serves_as:` for "public name ≠ identifier"; `_`-prefixed helpers/internal; `SCREAMING_SNAKE` constants; `<feature>_<layer>` modules), **§27 The boundary doctrine** (maximize in-s0ma; the exempt handwritten-Python set is EXACTLY {the single bootstrap module, `[tool.s0ma].bootstrap_files`, `[tool.s0ma].package_markers`, `@internal`} and nothing more; external code is brought in by reference via `requires:`/`deferred_requires:`/`covered_by:`/`content: @file()`; the MCP self-host is the worked example), and **§28 The app-map pattern** (a copy-pasteable, build-validated `doc-ref` auto-rendering the public API with `covers: [nerve where visibility == PUBLIC]` plus a `doc-guide` narrating the architecture around the three faculties of self-knowledge — structure / runtime state / reasoning — both drift-gated; the project-wide map is the v1 default, with the per-feature variant expressible today via the 0.17.0 `module` predicate and the remaining gap, a first-class *feature* grouping dimension, logged as a future DSL ask). The quick reference (`s0ma://guide/quick-reference`) gains a compact "Project layout" block with one-line pointers to §24–§28, and the agent system prompt (`s0ma://guide/system-prompt`) gains a standing rule — lay out feature-first, follow the naming conventions, maximize in-s0ma per the boundary doctrine, ship a load-bearing app map. The app-map example was authored and validated in a scratch project (`s0ma build` + `s0ma check --mode strict` + `s0ma docs check-drift` all green). All three served-doc `_docs/` copies were refreshed by byte-copy in the same commit (D-4); no selfhost sources changed, so `_built/` is untouched.

### Changed

- **s0ma is repositioned as a software *self-knowledge* platform — the umbrella framing made canonical (standards/usability plan, M1; PRD v1.4):** the product line is reframed from a "software proprioception platform" to a "software **self-knowledge** platform". Self-knowledge is the umbrella, spanning **three faculties**, each mapped to existing machinery: **proprioception** (structure — registry, structural verifier, dependency graph, layers, IR edges), **interoception** (internal/runtime state — the interoception verifier, runtime metrics vs. declared resource profiles), and **metacognition** (reasoning over the model — QueryEngine, impact analysis, extension-point guidance, drift detection). The PRD (§1 Vision, §3 thesis, §11 glossary) and the core/positioning surfaces (root `README.md`/`CONTRIBUTING.md`, `s0ma-core`'s package `README.md`, `docs/architecture.md`, the core spec, and the `s0ma` package + `SelfModelInterface` strings) now use "self-knowledge" for the umbrella and the specific faculty term where the specific sense is meant; a new PRD principle **P-9 — Placement, not architecture** records that s0ma prescribes *where* components live and enforces reachability, but does not prescribe an application architecture. **Terminology evolution (read this if you hit "proprioception" in older material):** "proprioception" is now the *structural* faculty *within* self-knowledge — it was only ever the structural third, never the whole. Earlier and frozen uses of the term (completed plans under `plans/complete/` and `packages/*/plans/`, already-released changelog sections, and other historical artifacts) remain valid in that structural sense and are **deliberately not retroactively edited** (retroactive rewrites add complexity and risk). This changelog note is the single canonical place that prior usage is explained.
- **The self-knowledge sweep reaches the DSL/MCP corpus, the served agent copies, and the self-hosted MCP surface (standards/usability plan, M2 — extends M1's repositioning above; D-1 semantic editing, D-3 selfhost, D-4 `_docs` law):** the umbrella reframe is now consistent on every live surface a coding agent reads. The DSL language spec (`s0ma-dsl-spec-v0.17.0.md`, served as `s0ma://spec/current`) keeps its "documentation vs. proprioception" contrast in Principle 1 — *Structural Self-Awareness* but annotates the term as the **structural faculty** of self-knowledge (faculty-specific use retained per D-1, not the umbrella); the self-hosted MCP `author_module` prompt copy (`s0ma_src/prompts/author_module.txt`) and the handwritten bootstrap server's `FastMCP` `instructions` (`src/s0ma_mcp/__init__.py`) reframe "software-proprioception platform" → "software **self-knowledge** platform"; and the three package `description` fields plus their `keywords` arrays (`s0ma-core`, `s0ma-dsl`, `s0ma-mcp`) move to the self-knowledge framing (the umbrella `proprioception` keyword → `self-knowledge`). Because the prompt copy is embedded build data, `packages/s0ma-mcp/src/s0ma_mcp/_built/` was rebuilt from `s0ma_src/` (the `selfhost-build` byte-equality gate stays green): only `_built/prompts.py` (the embedded template + its deterministic output-hash comment) and `_built/build.s0ma.json` (the template's content-hash + the prompts output-hash) changed — no `.s0ma.json`/`.map`/stub/docs churn. The drift-gated `_docs/` copy of the edited spec was refreshed by byte-copy (D-4). Frozen history (completed plans, released changelog sections) is untouched per D-2.

## [0.8.0] — 2026-06-11

**DSL improvements driven by real self-hosting evidence.** This release closes the language-improvement backlog the s0ma-mcp self-hosting effort surfaced (the friction log's top ten): declarations gain a first-class `metadata:` channel and a `serves_as:` public-name field, modules gain `deferred_requires:` for per-call deferred imports and a qualified in-project `module.declaration` form for `depends_on:`, the release coverage gate accepts external `covered_by:` evidence, `[tool.s0ma].mode` is now read on every project-resolving command, artifact determinism is derived from the schemas, and the transpiler itself is `mypy --strict`-clean and ships `py.typed`. Every change is additive and behaviour-invariant except the one deliberate emitted-bytes normalization (cleandoc docstrings) and the one removed front-matter field — both flagged below. The s0ma-mcp flagship dogfooded each feature as it landed, retiring its bespoke `mcp_*` namespace convention and shrinking its handwritten bridge.

### Added

- **s0ma-dsl declarations gain a first-class `metadata:` field — the friction log's #1 ask, end to end (DSL plan, M1 — ADR-011 §(a), spec v0.17.0 §4.1.11):** nerve, cell, and ganglion declarations accept an authored block map of opaque facts (`metadata:` with one `key: value` line per entry; values are a quoted string, int, float, `true`/`false`, or a bracketed list of strings — the L-1 shape set; no inline form, no nested maps, no nulls), validated for SHAPE only (P-2: the language never interprets values) and flowing the whole pipeline: parser → AST (ordered pairs; duplicates survive to the validator) → IR (`components[].fields.metadata`, a JSON object in authored key order, omitted when not authored) → the emitted registration `metadata={...}` dict (authored items APPEND after the emitter-written keys, rendered as Python literals) → runtime `ComponentSpec.metadata`. Three new always-error diagnostics guard it: `METADATA_INVALID_KEY` (malformed or duplicate key), `METADATA_INVALID_VALUE` (null / unquoted bare token / nested map / malformed list entry / the unsupported inline `metadata: {...}` form), and `METADATA_RESERVED_KEY` (collision with an emitter-written registration key; the remediation points at the declaration field that owns the fact). The reserved set ships as `s0ma_dsl.ir.schema.RESERVED_COMPONENT_METADATA_KEYS` — the verified 27-key union across all five emission shapes — and an emitter test (`test_every_emitter_written_metadata_key_is_reserved`) pins every key the emitter writes to the constant both behaviourally and lexically, so the set cannot silently drift.
- **s0ma-dsl nerves gain `serves_as:` — the public serving name, authored once instead of re-invented per binding layer (DSL plan, M1 — ADR-011 §(b), spec v0.17.0 §4.1.12/§4.10.7):** an optional bare-identifier field carrying the name a nerve is served under when it differs from the declaration identifier (the MCP tool/prompt evidence: registry disjointness forces `check_tool` serving as `check`, and the suffixed identifier used to leak into client-visible schema titles via the emitted callable's `__name__`). The declaration identifier remains the registry/module symbol; `serves_as` rides the IR (`fields.serves_as`) and the emitted metadata dict (reserved `serves_as` key), and the emitter stamps the emitted callable's `__name__`/`__qualname__` with the served name one blank line after the decorated def — decorate-then-stamp, so `ComponentSpec` identity is untouched and schema-title derivation reads the served name from the artifact itself. Two new always-error diagnostics: `SERVES_AS_INVALID` (non-identifier value) and `SERVES_AS_COLLISION` (served names form one flat namespace, validated per module by the semantic validator AND per project build by the dependency resolver; own-identifier equality permitted).
- **s0ma-dsl language spec v0.17.0 + IR schema 2.1.0 (DSL plan, M1 — ADR-011 §(g)/(h)):** the spec file rotates `s0ma-dsl-spec-v0.16.0.md` → `s0ma-dsl-spec-v0.17.0.md` (fresh one-release breadcrumb at the v0.16.0 path; the v0.15.0 pointer is deleted per its own declared deletion-after-0.16.0 schedule), with the DSL-M1 sections landed (§4.1/§4.2/§4.3 field tables, §4.1.11/§4.1.12 field contracts, §4.10.7 served identity, §4.14.4 IR delta + reserved-key rule + stamp shape, §4.16 new codes, Appendix A rows) — later milestones of the batch extend this same spec version per ADR-011. The IR `schema_version` bumps 2.0.0 → 2.1.0, strictly additive (`fields.metadata`/`fields.serves_as` now, `covered_by` + `deferred_requires` at M2; absent = not authored, 2.0.0 consumers keep parsing) — the one mechanical consequence is the `schema_version` line moving in every committed IR document and rendered doc front matter (dsl doc goldens and the s0ma-mcp committed build are regenerated with exactly that diff; a no-new-fields build is otherwise byte-identical pre/post, emitted `.py`/`.s0ma.map`/stub included). The quick reference and the TextMate grammar gain both fields; the editor grammar's field alternation is now harvested from spec v0.17.0.
- **s0ma-mcp authors its MCP surface as first-class `metadata:`/`serves_as:` fields — the seven-namespace `mcp_*` convention is retired and the bridge's prefix parsers are deleted (DSL plan, M1 dogfood — closes friction items F-M0-7/F-M2-2/F-M3-3/F-M3-4/F-M4-1):** the three `s0ma_src/*.s0ma` modules now author `metadata: mcp_uri:`/`mcp_mime_type:` on resources, `serves_as:` + `metadata: mcp_prompt_title:`/`mcp_dependency:` on prompts, and `serves_as:` + `metadata: mcp_tool_annotations: ["<field>=<bool>", ...]` (plus `mcp_dependency:` where applicable) on tools — zero `declares_attributes` prefixed strings remain in the sources, enforced by a new regression gate. The bootstrap bridge reads runtime `spec.metadata` only: the seven `mcp_*` prefix constants, the `_BuiltMcpFacts` record, and the IR-reading `_built_module_mcp_facts` (176 lines) are deleted outright; annotation entries keep the eager SDK-field-name validation (frozenset + one `=` split); `serves_as` maps to the `mcp_tool`/`mcp_prompt` catalog identity by the owning module's surface family. The two informational metadata blocks SH-M3 had to drop for want of a carrier return as plain authored metadata (`composes` on `project_status`/`run_example`, `wraps` on the CLI bridge). The emitted `__name__`/`__qualname__` stamps now name every built tool/prompt callable at build time — the factory's `_served_as` rename is kept deliberately as an idempotent guard for future handwritten/injected bindings. **The served MCP surface is byte-identical:** the committed surface snapshot passes un-regenerated, and the D-6 derivation suite, annotations parity, cleandoc, stdio, and wheel smokes are all green.
- **s0ma-dsl modules gain `deferred_requires:` — deferred imports with per-call failure semantics, the friction log's #6 ask (DSL plan, M2 — ADR-011 §(c), spec v0.17.0 §4.5.1/§4.7.4):** a fourth requires-family module-header list with the same entry grammar as `requires:` (dotted paths, `pkg:name` colon override, `as` aliases, inline and block-list forms). Entries emit NOTHING at module top; the emitter injects the import at the top of each CONSUMING def body — after the docstring, before the first authored statement, one contiguous block in entry order; injection targets are module-level defs and class-body methods, with nested-def references crediting the outermost enclosing def. On a broken environment the module still imports and each CALL raises `ImportError` inside the body — the "start degraded, fail per-call" resilience idiom (F-M3-1), restored as an authored choice. The static dependency record stays complete: IR `imports.deferred_requires` entries carry `"deferred": true` (no `deferred: false` backfill on the other lists), `MISSING_PACKAGE` applies unchanged, and `VESTIGIAL_IMPORT` uses the same body-evidence rule as `requires:` (deferred entries are not `runtime_only_requires`-exempt). Two new always-error diagnostics: `DUPLICATE_REQUIRES_ENTRY` (the same target in `deferred_requires:` and another requires-family list — one target, one failure-time choice) and `DEFERRED_IMPORT_MODULE_SCOPE` (a deferred name consumed at a module-scope execution position: cell bodies, class-scope statements, decorator expressions, parameter defaults, annotations). The `BARE_IMPORT` remediation now names the deferred option, and the CLI runs dependency resolution even for single-module invocations that author the field so the contracts fire in every mode. A broken-dependency fixture (`tests/fixtures/deferred_imports_project`) proves both arms end-to-end through `s0ma build`.
- **s0ma-dsl `depends_on:` targets gain the qualified in-project form `module.declaration` — the in-scope core of the friction log's #7 ask (DSL plan, M2 — ADR-011 §(d), spec v0.17.0 §4.1.2/§4.6):** the plan's only `grammar.lark` change (`depends_on_entry` now parses through `dep_target: NAME ("." NAME)?` — exactly one dot; deeper dotting is a parse error). Resolution runs against the project's module set: the named module must exist (`DOES_NOT_EXIST` naming the qualified form as authored and listing the project's modules; single-module/synthetic invocations get a remediation saying qualified targets require a `[tool.s0ma]` project build), the declaration must exist in it (`DOES_NOT_EXIST`), and cross-module targets must be exported (`NOT_EXPORTED` — the same public-surface rule as `uses:`); self-module-qualified targets resolve as the local declaration (idempotent, export-exempt). Qualified edges join Phase-1 module-graph construction with the same fatal `CIRCULAR_DEPENDENCY` rule as `uses:` and the cross-layer reachability matrix applies unchanged; Phase-4 evidence rules are target-location-agnostic (checked against the LEAF name). The emitted decorator's `dependencies=[...]` carries the canonical `module::declaration` string for qualified targets while bare local names stay byte-identical, and the IR's authored-edge records canonicalize the same way. Cross-PACKAGE targets remain inexpressible; URI/catalog-shaped referential facts keep `metadata:` as their carrier.
- **s0ma-dsl nerve/cell/ganglion gain `covered_by:` — the release gate's external test-evidence credit, the friction log's #5 ask (DSL plan, M2 — ADR-011 §(e), spec v0.17.0 §4.1.13/§4.8/§2.4):** a bracketed list of non-empty strings naming the out-of-DSL suites (or rationale prose) that cover a declaration, authored-opaque — the language validates SHAPE only (`COVERED_BY_EMPTY`, error in every mode, for an empty list or any empty/whitespace entry) and never resolves the strings. Release-mode `MISSING_TEST_COVERAGE` now passes on EITHER in-language `tests:` coverage OR a non-empty `covered_by:` (the remediation names the third option); the credit injects no synthetic test targets, so "tested in-language" and "externally covered" stay distinguishable in the record. The claim is auditable end to end: it rides the IR (`components[].fields.covered_by`, omitted when absent), the emitted registration metadata (reserved `covered_by` key), and doc-ref renderings (a `Covered by:` line after the intent — the doc index reads it from the AST in pre-import builds and from `spec.metadata` in registry-snapshot builds). The wrapper-import recipe (running DSL-authored tests inside a plain pytest suite, F-M5-3) is documented as the blessed pattern in the documentation-subsystem guide, and the fixture project `covered_by_release_gate` proves the credit through `s0ma check --mode release` (a PUBLIC nerve with `covered_by:` and no `tests:` coverage passes; the negative arm fails).
- **s0ma-mcp dogfoods `deferred_requires:` — the SH-M3 resilience loss (F-M3-1) is reversed (DSL plan, M2):** `tools.s0ma` moves its 15 dsl/core machinery imports (13 `s0ma_dsl.*` entries plus `s0ma.examples:ExampleRunner` and `s0ma.registry:ComponentRegistry`) from `requires:` to `deferred_requires:`, restoring the original tools.py lazy-import design: the committed build's module top sheds the toolchain from-imports, each consuming def body carries its own injected imports, the server starts (and lists tools) even with `s0ma_dsl.cli` broken, and each tool call surfaces the import failure as the `_safe`-shaped structured `{ok: false, error: ...}` result instead of an import-time crash — pinned by three new boundary tests (a static module-top proof on the committed build, a fresh-subprocess degraded-server-start proof, and the per-call structured-failure proof at the tool boundary; mcp suite 154 → 157). The served-surface snapshot is byte-identical and un-regenerated. The `mcp_dependency` metadata entries were each weighed against the new qualified `depends_on:` form and ALL stay metadata per ADR-011 §(d) rule 8: the `s0ma://guide/*` targets are catalog names no DSL identifier can spell, `self_registry` is a cross-boundary edge onto the handwritten bootstrap module, and the prompt→tool journey edges are referential with their evidence in embedded template data — converting those would fail the relation-evidence rule or require a dishonest relation, so the honest carrier stands (the bridge docstrings record the weighing).
- **s0ma-dsl reads `[tool.s0ma].mode` — the declared project mode is now load-bearing, the friction log's #4 ask (DSL plan, M3 — F-M1-2):** `S0maProject` gains a `mode` field parsed from `[tool.s0ma].mode` and validated against the four strictness modes (`migration`/`dev`/`strict`/`release`; an unknown value or wrong type is a load-time error naming the supported set, in the loader's existing style). The CLI resolves the effective mode as `--mode` flag > `[tool.s0ma].mode` > the command's built-in default for the six project-resolving subcommands (`check`/`build`/`transpile`/`topo`/`migrate-layout`/`test`); to make this work the `--mode` flag now defaults to `None` so argparse can tell "flag omitted" from "flag supplied", and the per-command built-in defaults are preserved EXACTLY — `check` stays `strict`, the rest stay `dev` (deliberately NOT unified). Synthetic-fallback invocations (no `[tool.s0ma]` table) and table-less projects keep their command's built-in default, so today's behaviour is unchanged where the key is absent; `s0ma new project --mode M` is the one exception, writing the key for a not-yet-a-project directory. The `dev` → `strict` → `release` ramp is now the one-line `pyproject.toml` change the docs always promised: `scripts/check.py`'s `selfhost-build` stage and the mcp README build snippet drop their `--mode release` flag (the package's pyproject already declares `mode = "release"`), so the gate proves the table-driven path on every run.
- **s0ma-dsl ships a schema-driven artifact portability sweep + a single shared manifest-source resolver — the friction log's #3 ask (DSL plan, M3 — F-M2-1/F-M1-1):** a new determinism test (`test_artifact_portability_sweep.py`) derives its field coverage from the artifact SCHEMAS rather than from whatever a fixture happens to exercise: every string-typed field of the IR component/module schema, the build-manifest schema, and the source-map shape is classified PATH/TIME/OPAQUE in ONE enumeration, and a guard fails the day a new string field appears until it is classified — so a future path-or-time field is caught when it ships, not when it first breaks a cross-machine build (the three-times-paid lesson behind F-M0-8/F-M1-1/F-M2-1). A rich fixture project (multi-module + an `@file()` embed + a helper + rendered doc-ref/doc-guide/example) is built and EVERY artifact byte (recursive, including `docs/`) is swept for the project root, ISO-8601 timestamps, and absolute paths, with a negative proof that an injected absolute path / timestamp / backslash separator is each caught. The manifest-source resolution recipe that lived in three hand-copied places collapses into one dsl helper, `BuildManifest.resolve_source(entry, project_root)` (accepts a parsed entry, a raw mapping, or a string), adopted in `cli/doctor.py` and both `s0ma_mcp` `tools.s0ma` bodies — exactly one authored copy of the recipe now remains.
- **s0ma-dsl source maps record `body_output` for `helper` declarations — the last asymmetric map shape, the friction log's #10 papercut (DSL plan, M3 — F-M0-2):** `helper` was the one declaration kind whose `.s0ma.map` entry carried only the whole-declaration `output` range, forcing the strict-probe categoriser, error reporters, and coverage mappers to special-case it. The `_build_mapping` isinstance ladder gains a `HelperDecl` arm computing `body_output` as `output.start_line + 1 .. output.end_line` (the emitter prefixes a helper with a single `# Helper: <intent>` comment anchor immediately followed by the authored `def`), exactly like the nerve/test arms. The mcp committed build's `_built/tools.s0ma.map` and `_built/resources.s0ma.map` are regenerated with the new ranges (no `.py`/IR/manifest churn — source maps do not feed the output hash).
- **s0ma-dsl doc-ref/doc-guide filters gain a `module` predicate field — per-module references are now expressible, the friction log's #8 doc-subsystem gap (DSL plan, M4 — ADR-011 §(h), F-M5-2, spec v0.17.0 §4.12.1):** `module` (the name of the module that owns an entity) joins the addressable field set on every declaration kind, so a multi-module project can render "the tools reference" and "the resources reference" as separate `doc-ref`s (`covers: [nerve where module == tools]`) instead of one project-wide doc or a hand-curated guide. The value rides every indexed entity as its `module_name` and is exposed in the `fields` dict at index-build time (both the AST-based `build_project_index` and the runtime-snapshot `ProjectIndex.from_snapshot`), so it works in `where` predicates, in field-access (`{{nerve::greet.module}}`), and in `asserts:`. Comparison is by name only — an unrecognised module value matches no entity, surfacing as `EMPTY_DOC_FILTER` exactly like any other empty predicate (warning in dev/migration, error in strict/release); there is no separate unknown-module diagnostic.
- **s0ma-dsl ships `python -m s0ma_dsl` cleanly + a smarter wrong-CWD build warning — the friction log's #10 papercut cluster (DSL plan, M4 — F-M0-3/F-M0-1/F-M2-7/F-M3-2/F-M1-3/F-M4-4):** a new `s0ma_dsl/__main__.py` delegates to `cli.main:main`, so `python -m s0ma_dsl` runs the CLI without the runpy `RuntimeWarning` that `python -m s0ma_dsl.cli.main` triggers (`scripts/check.py`'s selfhost-build stage flips to the clean form). The synthetic-fallback discovery warning is upgraded: when CWD-anchored discovery finds no `[tool.s0ma]` table but the positional `<project_dir>` itself carries one, the warning names that unused `pyproject.toml` and suggests `--project-root <dir>` — the usual cause of a build that "succeeds" into the wrong layout (`s0ma build <dir>` still anchors discovery on the CWD, not the positional argument; the behaviour change is deferred, only the warning improves). The quick reference and spec also close the long-tail doc gaps: `requires:` is documented as omittable for import-free modules (F-M2-7), the `typing:cast` lowercase colon-override gotcha is spelled out (F-M3-2), the global `--project-root` flag is documented (F-M0-1 doc half), the isort-reclassification-after-conversion reshuffle is noted (F-M1-3), and the partially-initialized-bootstrap ordering contract is promoted from a quick-reference note to a spec'd guarantee in the runtime-bridge section (F-M4-4).
- **s0ma-dsl is `mypy --strict`-clean and ships `py.typed` — the repo's oldest open follow-up, tracked since 0.5.0, is closed (DSL plan, M5 — F-M0-4):** the transpiler package now passes `mypy --strict` with zero findings (down from the 221-error / 21-file inventory the milestone re-measured at its start, itself ~40% of the 0.5.0-era ~369), so it advertises inline types via the PEP 561 marker `src/s0ma_dsl/py.typed` (hatchling packages it with no extra config, riding the wheel — the same mechanism s0ma-core uses since 0.7.0). The work was typing-only and behaviour-invariant by construction (annotations, `cast`, narrowing guards, and lexical loop-variable renames; no logic edits, no signature changes that alter runtime behaviour) — the emitted-bytes gate (`selfhost-build`) stayed byte-identical throughout and the served MCP surface snapshot is untouched. `scripts/check.py` gains a `mypy-dsl` stage (strict, run from the package dir like `mypy-core`/`mypy-mcp`), so the gate is now nine stages and the package's strict-cleanliness is enforced on every run. **Dogfood:** s0ma-mcp's `[tool.mypy]` drops its `s0ma_dsl.*` ignore-missing-imports override (deferred at SH-M0 pending exactly this) — `mypy-mcp` now type-checks the bootstrap module's catalog bridge against dsl's real published types and stays green with zero fallout. The milestone added exactly one new `# type: ignore` — `s0ma_dsl/cli/main.py` (the optional unstubbed `yaml` import, with an inline reason) — keeping the tree-wide total at nine, under the plan's ten-ignore budget; the other eight predate this work. Four stale ignores were removed in passing: two bare ignores on the now-typed `s0ma.examples`/`s0ma.registry` imports, and two `union-attr` ignores in the source-map anchor walk that the widened declaration union made redundant.
- **The `mypy-dsl` gate stage now checks BOTH platform views — the native run plus a `--platform win32` re-analysis (DSL plan, M5 repair):** mypy resolves `sys.platform` conditionals for the running platform only, so the CLI entry point's Windows-only stdout/stderr UTF-8 `reconfigure` block was strict-broken in the Windows view alone (typeshed types the streams as `TextIO`, which has no `.reconfigure` — it lives on `io.TextIOWrapper`) while every POSIX run, local and CI, stayed green; the windows CI legs caught it. The block now narrows with `isinstance(..., io.TextIOWrapper)` before each call — a typed guard rather than a `# type: ignore`, which `--strict`'s `warn_unused_ignores` would flag as unused on the POSIX legs where the block is unreachable (on a real Windows console the streams are always `TextIOWrapper`, so runtime behaviour is unchanged; a replaced non-file stream that would previously have crashed the entry point is now skipped) — and the stage's second sub-invocation (separate `.mypy_cache/win32` cache dir, ~1s) makes the Windows view part of every gate run on every machine, closing the platform-conditional blind-spot class for the dsl package.

### Changed

- **s0ma-dsl normalizes emitted body docstrings at emit time — the plan's one deliberate emitted-bytes change to existing projects, the friction log's #9 ask (DSL plan, M3 — F-M3-8, P-7):** the emitter now rewrites every body docstring (module, function, async function, class, and method) to its PEP 257 `inspect.cleandoc` form in the emitted source, so the emitted `__doc__` is interpreter-independent at the ARTIFACT level. CPython 3.13 dedents `__doc__` at compile time ([python/cpython#81283](https://github.com/python/cpython/issues/81283)) while ≤3.12 preserves the source indentation, so byte-identical emitted code otherwise served different `__doc__` bytes per interpreter (the F-M3-8 failure that surfaced on the 3.11/3.12 CI legs only); normalizing in the source collapses both raw forms to one canonical string. The transform touches the docstring's whitespace only — leading common margin and surrounding blank lines are stripped, but escapes and raw-string prefixes survive, and a literal is only rewritten when re-parsing confirms its value equals `cleandoc(original)`. **Consequence for consumers: a `s0ma build` of an existing project will churn docstring bytes once on the next rebuild** (the emitted `.py` and `.s0ma.map` change; IR is unaffected — docstrings do not ride in the IR). The s0ma-mcp served-surface snapshot is byte-UNCHANGED: its descriptions were already `cleandoc`'d at the binding layer, so the emit-time form agreeing with it (the snapshot not moving) is the proof the normalization matches `inspect.cleandoc`; mcp's binding-layer `normalize_docstring` stays as the backstop for handwritten callables.
- **s0ma-dsl drops `transpiler_version` from rendered doc front matter — the friction log's #8 misleading-version-field gap (DSL plan, M4 — ADR-011 §(f), F-M5-5, spec v0.17.0 §4.12.5):** the rendered-doc front matter pinned `transpiler_version: "1.0.0"` (the IR codegen-contract constant `ir.schema.TRANSPILER_VERSION`) under a name that collided with the build manifest's `transpiler_version`, which carries the *distribution* version — "one field name, two semantics" at GA. The field is removed from the front-matter contract (now seven fields: `s0ma_kind | name | module | format | intent | schema_version | content_hash`); `schema_version` remains the contract identity, and the content-hash computation is untouched (it still mixes in `TRANSPILER_VERSION`, so drift detection is unchanged). The distribution version now lives only in the manifest's `transpiler_version` and the `.pyi` header, which preserves the property that a distribution bump churns no rendered docs (only those two files). **Consequence for consumers: any committed rendered doc loses exactly one front-matter line on the next rebuild; `content_hash` values are unchanged** (hash inputs did not change). The four dsl doc goldens, the served `docs/_generated/common_errors.md`, and the s0ma-mcp committed build (`_built/docs/*.md`) are regenerated with exactly that one-line-per-doc diff; the served MCP surface snapshot is byte-frozen (rendered docs are wheel data, not served MCP resources).

### Fixed

- **s0ma-dsl `docs render` / `docs check-drift` now resolve declared `output:` paths against the project's `build_dir`, agreeing with `s0ma build` — the friction log's #8 base-dir gap, found to be a real defect (DSL plan, M4 — F-M5-4, spec v0.17.0 §4.12.5):** for a `[tool.s0ma]` project, `s0ma build` emits docs under `<build_dir>/<output:>` but the `docs` subcommands ignored `build_dir` and resolved against the project root — so a committed-build project wrote docs to `<build_dir>/docs/` while `docs check-drift` looked under `<root>/docs/` and reported spurious `DRIFT_DETECTED` ("missing — never rendered"). The base-dir resolution is now shared and project-aware (a single `_resolve_docs_base_dir`): `--output-dir` wins, else the resolved project's `build_dir`, else (synthetic/no-table invocation) the historic source path or its parent — mirroring the build path's precedence exactly. Synthetic invocations are byte-for-byte unchanged. A render/check-drift/build base-dir AGREEMENT test pins it.

## [0.7.0] — 2026-06-10

**s0ma-mcp is now authored in s0ma.** The headline of this release (FR-MCP-11, the self-hosting plan): every tool, resource, and prompt the authoring MCP server exposes is declared in `.s0ma` sources, built at the DSL's full `release` gate, shipped as the transpiler's committed deterministic build output, and served from the self-model registry the build populates — exactly one handwritten bootstrap module remains, and the registered set and the served surface can no longer drift by construction.

### Added

- **`s0ma-mcp` builds at the DSL's full `release` gate — the D-6 mode ramp is complete, and the package's own production-gate demands are satisfied in its `.s0ma` sources (selfhost plan, M5 — FR-MCP-11/FR-DSL-6):** the package's declared `[tool.s0ma]` mode is now `release` (flipped in lockstep with the `selfhost-build` stage's `--mode` and the README build loop), turning on the DSL's coverage gates — and the sources satisfy them honestly rather than by exemption: five new `test` declarations cover all 22 PUBLIC nerves with boundary-contract verification (prompt rendering substitutes every marker; every packaged document serves its registered text; the version/self-model resources render live JSON; live and invalid tool inputs alike come back as structured `{ok, ...}` answers, never an exception), emitted as pytest functions the package's own suite imports and runs on every CI OS (`tests/test_selfhost_release_gate.py`; suite 146 → 152); a new `doc-ref` (`mcp_public_surface_reference`) renders the public-surface API reference straight from the registry via a `nerve where visibility == PUBLIC` filter, so new surfaces appear in the reference without editing the doc; and a new `doc-guide` (`selfhost_walkthrough`) narrates the self-hosting design around an embedded executable `example` (`describe_the_running_server`) the suite proves live by running it through the server's own `run_example` tool. The rendered documents are committed under `_built/docs/`, ship in the wheel, and are byte-gated by the `selfhost-build` equality stage like every other build artifact. Cross-OS proof recorded on the plan board: two consecutive fully-green CI matrix runs with the equality stage byte-identical on both windows legs. The README now presents the package as the DSL's **flagship worked example** (quoting a real declaration from `s0ma_src/`), and the agent guides point authoring agents at the package as the production reference.
- **`s0ma-mcp` reaches the FR-MCP-11 end state: registry-derived MCP surface, single bootstrap module (selfhost plan, M4 — FR-MCP-11/FR-MCP-7):** `create_server()` no longer contains a registration list — it DERIVES every tool, resource, and prompt binding from the package self-model registry (a component carrying `mcp_tool`/`mcp_uri`/`mcp_prompt` metadata is served *because* it is registered, with its authored FR-MCP-8 `ToolAnnotations`, MIME type, and prompt title bound from the same metadata), making FR-MCP-7's no-drift clause structural: the registered set and the served surface cannot diverge, proven by a negative test that injects a fake MCP-surfaced component and finds it served without any factory change. The handwritten Python collapses to exactly **one bootstrap module** — the package `__init__.py` (bootstrap_imports + module aliasing, the IR-reading catalog bridge, the self-model registry machinery, `normalize_docstring`, and the derived `create_server`/`main`) — `components.py` and `server.py` are retired, and a repurposed drift test enforces the count by reading the filesystem (transpiled modules identified by their emitter hash-comment markers). Two new `declares_attributes` namespaces complete the declaration-level metadata carrier: `mcp_prompt_title:<title>` and `mcp_mime_type:<type>`; the served tool descriptions are now authored on the `_tool` declarations themselves (the old `server.py` wrapper docstrings, moved byte-exactly), and the factory stamps each tool's MCP serving name onto the bound callable so the served JSON schema titles stay byte-identical. The client-visible surface is **unchanged** — the SH-M3 committed schema snapshot passes un-regenerated — and the conversion is API-compatible at runtime: the console script now targets `s0ma_mcp:main`, while `from s0ma_mcp.server import create_server, main` (and any stale installed 0.6.x console-script shim) keeps working through a runtime alias of the bootstrap module; the canonical programmatic import is now `from s0ma_mcp import create_server`. Tool listing order now follows the registry's catalog order (names/schemas/annotations are pinned unchanged; only the order in `list_tools`/`list_resources` responses differs).
- **`s0ma-mcp` tools are authored in the `.s0ma` DSL — the biggest conversion, and the project mode ramps to `strict` (selfhost plan, M3 — FR-MCP-11/FR-MCP-2/FR-MCP-8):** all nine authoring tools (`transpile`, `build_project`, `check`, `inspect_module`, `project_status`, `run_example`, `migrate_ext`, `scaffold_module`, `describe_server`) are now declared in `s0ma_src/tools.s0ma` and served from the committed build; the handwritten `tools.py` is deleted (handwritten package modules: 4 → 3 — `__init__.py`, `components.py`, `server.py`). The shared MCP boundary converts with them: the `_safe` wrapper is a `helper` declaration whose decorator stacks under the emitted `@component` exactly as it did handwritten, the in-process CLI bridge is an INTERNAL `ADAPTER` nerve (declaration `_run_cli`, cataloged under its established `dsl_cli_bridge` identity at PRESENTATION — the documented F-M0-6 re-layering, same as `guide_doc_loader`), and the NFR-6 write fence, diagnostics shaping, and `{ok, ...}` result contracts are unchanged. Tool MCP names are identifier-shaped, so declarations follow the prompts convention: `_tool`-suffixed (`check_tool`) with the served name authored as a `declares_attributes` `mcp_tool:<name>` entry — note the **public Python symbol rename** (`s0ma_mcp.tools.check` → `s0ma_mcp.tools.check_tool`, and likewise for all nine; the served MCP tool names are unchanged). Each tool's FR-MCP-8 `ToolAnnotations` are now **authored on its declaration** as `mcp_tool_annotations:<field>=<bool>` attributes (SDK field names, deliberately-unset hints not authored): the catalog bridge stamps them into `metadata["mcp_tool"]`/`metadata["mcp_tool_annotations"]` (the M4 carrier convention) and `create_server` binds annotations built from that metadata via the new `components.built_tool_annotations()` — the hand-maintained `TOOL_ANNOTATIONS` table is gone, and a new test asserts the served hints equal the authored attributes field by field. The conversion is behavior-invisible at the MCP boundary (D-5), proven two ways: a new **committed schema snapshot** (`tests/snapshots/mcp_surface.json` + `tests/test_mcp_surface_snapshot.py`, captured from the pre-conversion server) pins every tool name, description, input/output JSON schema, and annotation — set and deliberately-unset — plus every resource and prompt, byte-exactly as a standing drift gate; and pre-conversion behavioral baselines (20 tool-result documents through the in-process MCP client on fixed fixture projects) re-captured byte-identical after every conversion group. One documented behavior delta: the DSL rejects function-scoped imports (`BARE_IMPORT`), so the tools' lazy `s0ma_dsl` imports moved to module scope — in a healthy environment nothing changes, but a broken `s0ma_dsl.cli` installation now fails at server import rather than as a per-call structured tool error. The package's declared `[tool.s0ma].mode` ramps `dev` → `strict` (plan D-6) in lockstep with the `selfhost-build` gate's `--mode` and the README build loop; the catalog entries for converted tools also shed two informational metadata blocks (`composes`/`wraps` — the DSL has no authored-metadata channel on declarations yet, logged as friction) while gaining richer `expects:`/`guarantees:` contracts.
- **`s0ma-mcp` prompts are authored in the `.s0ma` DSL — prompt texts as embedded template data (selfhost plan, M2 — FR-MCP-11/FR-MCP-6):** the three authoring-journey prompts (`author_module`, `fix_check_failures`, `migrate_project`) are now declared in `s0ma_src/prompts.s0ma` and served from the committed build; the handwritten `prompts.py` is deleted (handwritten package modules: 5 → 4). The prompt **copy is data**: each journey's text lives as a plain-text template under `s0ma_src/prompts/` and is embedded into a CONSTANT cell via `content: @file(...)` with a check-enforced `placeholders:` contract (POST-12b), so the registry lists the texts as components and `s0ma check` cross-checks every `__MARKER__` between the copy and its rendering nerve before anything builds. Because MCP prompt names are identifier-shaped, the declarations are `_prompt`-suffixed (`author_module_prompt`) and carry their served name as a `declares_attributes` `mcp_prompt:<name>` entry — the catalog bridge registers them under the MCP name (stamped in `metadata["mcp_prompt"]`, the M4 carrier convention) while the global registry keeps the declaration identifier, preserving the self/global registry name-disjointness invariant; the prompts' *referential* dependency edges (the tools and resource URIs the rendered copy instructs an agent to call — inexpressible as in-module `depends_on:`) are authored as `mcp_dependency:<name>` attributes and bridged in declaration order, so the self-model's copy-rot guard survives the conversion intact. The conversion is byte-invisible at the MCP boundary (D-5): rendered prompt texts, names, titles, descriptions (the docstrings transpile verbatim), and argument schemas are identical, verified against captured pre-conversion baselines; the wheel smoke now additionally proves the prompts module serves from the wheel's committed build and renders a journey end to end. A new drift test pins each converted component's served intent to the literal `intent:` text of its `.s0ma` declaration.
- **`s0ma-mcp` is now a self-hosted s0ma application — first converted module + committed-build equality gate (selfhost plan, M1 — FR-MCP-11):** the package is a real `[tool.s0ma]` project (`mode = "dev"`, sources in `s0ma_src/`, build output committed at `src/s0ma_mcp/_built/` — layout decided in the package's new `docs/adr/ADR-001-selfhost-layout.md`), and the **resources surface is the first surface authored in the `.s0ma` DSL**: `s0ma_src/resources.s0ma` replaces the handwritten `resources.py`, the wheel ships the transpiler's committed build output (emitted module + IR + source map + manifest + typed stub), and the package `__init__` bootstraps it with the product's own `bootstrap_imports` pattern (flat canonical module names, manifest-driven order, `s0ma_mcp.resources` aliased so every existing import keeps working). The package self-model absorbs built modules through a new generic bridge (`components.bridge_built_modules`): served resources catalog under their **URIs** read from the IR's authored `declares_attributes` `mcp_uri:` entries (no hand-maintained mapping), plumbing keeps its established catalog identity (`guide_doc_loader`), and the FR-MCP-7 drift gate held at every commit of the transition. A new `selfhost-build` stage in `scripts/check.py` rebuilds the package from its `.s0ma` sources with the cache disabled on every CI run and fails on ANY byte difference vs the committed output, listing the differing files — simultaneously the "you forgot to rebuild+commit" guard and a standing cross-platform determinism regression test (P-4/INV-5). The MCP-served surface is byte-/set-identical through the conversion (D-5); the self-model's plumbing entries change as documented in the ADR (`load_doc` serves as `guide_doc_loader` at PRESENTATION — the friction log's F-M0-6 re-layering — with richer contracts from `expects:`/`guarantees:` and the resource URI stamped in `metadata["mcp_uri"]`). The wheel smoke now additionally proves the converted module is served from the wheel's committed build output. Handwritten package modules: 6 → 5 (per-milestone burn-down tracked in `[tool.s0ma].bootstrap_files`).
- **Selfhost feasibility verified, with re-runnable evidence (selfhost plan, M0 — GO):** two new repo verification scripts prove FR-MCP-11's foundations and stay available to later milestones: `scripts/probe_strict_typing.py` builds a four-fixture corpus (incl. a synthetic mcp-shaped module) with the real `s0ma build` pipeline, runs `mypy --strict` over the emitted Python, and categorizes every error as emitter/authored/dependency via the build's own source maps (result on this tree: zero emitter-class errors); `scripts/spike_selfhost_resources.py` authors the s0ma-mcp resources surface as a real 328-line `.s0ma` module in a scratch project and proves the four GO gates — strict-clean emitted code, byte-identical cold rebuilds (manifest `built_at` is the one documented run-varying field), the existing `test_resources.py` suite green against the built artifact through an import-redirection shim, and registration parity with `components.py` (byte-identical intents). Findings and authoring rules are logged in `plans/notes/mcp-selfhost-friction-log.md`.
- **`s0ma-core` ships `py.typed` (selfhost plan, M0 — the tracked 0.5.0 follow-up):** the installed `s0ma-core` wheel is now PEP 561-typed, so downstream strict mypy gates see the runtime's real types — `@component`, `ComponentSpec`, `ComponentRegistry`, `RegistrySnapshot.describe()` and the rest — instead of `Any`. This is the typing floor for FR-MCP-11 (s0ma-mcp's emitted modules must pass mypy `--strict` against core's real decorator types). `s0ma-mcp` drops its now-inert `s0ma.*` ignore-missing-imports override and one now-redundant `cast`; `s0ma-dsl` deliberately does NOT ship a marker yet (it is not strict-clean as a package — decision recorded on the selfhost plan's status board).
- **Windows is a first-class, CI-enforced platform (Windows-support plan, M4 — completes NFR-7):** the permanent CI matrix now runs the full gate — ruff, mypy `--strict` on s0ma-core and s0ma-mcp, all three test suites, the INV-1 spelling guard — on `windows-latest` (Python 3.11 and 3.13, bracketing the supported range; 3.12 stays Linux-only by design) alongside `ubuntu-latest` (3.11/3.12/3.13), with `fail-fast: false` so one red job cannot hide another. A new transport-level smoke test spawns the real `s0ma-mcp` console-script entry point (`s0ma_mcp.server:main`) as a child interpreter and asserts the stdio server starts and blocks serving — the one product surface no in-process test exercised. The README and CONTRIBUTING now state platform support explicitly (macOS, Linux, Windows; Python ≥ 3.11) and document the make-free Windows dev workflow (`make` is never required — the one make-only convenience, `make docs-derived`, has a documented direct-CLI equivalent).
- **`.gitattributes` — line endings pinned to LF repo-wide (Windows-support plan, M0):** every text file now commits and checks out as LF on every OS, so the byte-compare drift gates, content hashes, and wheel builds see the same bytes on Windows that CI sees on Linux. Verified as a pure no-op for the existing tree: every tracked text file was already stored LF, and `git add --renormalize .` stages nothing.

### Changed

- **`s0ma-mcp`'s self-description catches up with what the package became (selfhost plan, M5 accuracy pass):** the served `s0ma://self/model` resource description now states that every tool, resource, AND prompt is authored as a s0ma component and that the served surface is derived from the same graph the document renders (it previously named only tools and resources — stale since the M2 prompts conversion — and predated the M4 derivation); the `self_registry` and `self_model_resource` catalog intents gain the same corrections at the declaration level. Client-visible: exactly one resource description changed, and the committed surface snapshot is regenerated with exactly that diff.
- **s0ma-dsl source maps record embedded `@file()` template paths portably (selfhost plan, M2 — INV-5):** the `body_source_file` redirect a CONSTANT cell with `content: @file(...)` writes into `.s0ma.map` is now recorded project-root-relative in POSIX form when the build runs against a resolved `[tool.s0ma]` project — it was the one artifact field M1's portable-paths work missed (no `@file()` cell existed in a committed build until the prompts conversion), and it embedded the embed file's resolved absolute machine path, which a committed build must never carry. Synthetic (no-project) invocations keep the legacy resolved-absolute form. Readers resolving the field must now join relative values with the project root (spec §4.2.2 updated); the manifest's `external_content_files` entries were already as-authored relative and are unchanged.
- **s0ma-dsl build artifacts are now fully portable and timestamp-free (selfhost plan, M1 — INV-5):** the `build.s0ma.json` manifest no longer embeds a `built_at` wall-clock timestamp (the field is optional on load; pre-existing manifests still parse, and an explicitly-set value still round-trips for reproducible fixtures), and when the build runs against a resolved `[tool.s0ma]` project the manifest's `source`/`build_dir` fields plus the IR's and source map's `source_file` are recorded relative to the project root in POSIX form instead of as machine-/CWD-/OS-dependent path strings. Two builds of the same input now produce a byte-identical build directory on every machine, working directory, and operating system — the property the committed-build equality gate (FR-MCP-11, `selfhost-build` in `scripts/check.py`) stands on, and the completion of WIN-M3's "no absolute machine paths in artifacts" work for the remaining three writers. `s0ma doctor` / the `project_status` tool now resolve relative manifest sources against the project root (previously CWD — freshness only matched when invoked from the build's own working directory). Synthetic-fallback builds (no `[tool.s0ma]`) keep the legacy as-passed recording. Anything parsing these four fields must expect project-root-relative POSIX values; locally cached artifacts written before this change carry the old forms until the next `s0ma build --clean`.
- **s0ma-core runtime output renders ASCII `->` instead of the Unicode arrow `→` (Windows-support plan, M1):** `RegistrySnapshot.describe()` relationship edges and the documentation drift-status report were the only core runtime output containing U+2192, which is not cp1252-encodable and could crash a redirected Windows console with `UnicodeEncodeError`. This change is visible on every platform — anything parsing those two renderings must now expect `->`.
- **s0ma-dsl `OVERLAPPING_DISCOVERY_ROOTS` diagnostic names roots relative to the project root with POSIX separators (Windows-support plan, M2):** the offending `source_roots`/`test_roots` pairs are now echoed back the way the author wrote them in `[tool.s0ma]` (e.g. `` `src/myproject` ``) instead of as resolved absolute paths, on every OS; a root that resolves outside the project root still renders as a native absolute path. This change is visible on every platform — anything parsing the diagnostic's pair lines must expect relative POSIX paths for in-project roots.
- **s0ma-dsl build artifacts reference their generated `.py` by basename (Windows-support plan, M3):** the `transpiled_file` field in `.s0ma.json` IR and the `output_file` field in `.s0ma.map` now hold just the output file's name (e.g. `signal_processor.py`) instead of the build's full output path. The IR and source map are always emitted into the same directory as the `.py` they describe, so the basename is a complete, directory-independent reference — and embedding the build's own output path made artifact bytes vary per output directory and per machine (INV-5: no absolute machine paths in artifacts). This change is visible on every platform — anything resolving these two fields must now join them with the artifact's own directory. Builds of the same source are now byte-identical across output directories, machines, and OSes; `source_file` (the user's invocation path) is unchanged.
- **s0ma-core runtime-cache artifacts reference their cached `.py` by basename (Windows-support plan, M3 follow-up):** the `transpiled_file` field in the `.s0ma.json` IR the import hook writes into `__s0ma_cache__/` now holds just the cached file's name (e.g. `module.py`) instead of the absolute cache-directory path — the same INV-5 fix the s0ma-dsl build artifacts received in M3 (no absolute machine paths in emitted artifacts), closing the one remaining artifact writer that embedded one. The IR is always written next to the cached `.py` it describes, so the basename is a complete, directory-independent reference; the runtime cache never leaves the machine and nothing in s0ma reads the field back (verified for the core writer as it was for the dsl writers), so the change is visible only in the artifact bytes — anything external resolving the field must now join it with the artifact's own directory. A regression test pins the basename form and asserts the cache directory's path appears nowhere in the IR bytes, raw or JSON-escaped.

### Fixed

- **`s0ma-mcp` serves byte-identical MCP descriptions on every supported interpreter (selfhost plan, M3 repair):** FastMCP renders tool, resource, and prompt descriptions from raw `__doc__`, and CPython 3.13 strips the common leading whitespace from docstrings at compile time (python/cpython gh-81283) while 3.11/3.12 preserve the source indentation — so the same server source served per-interpreter description bytes (a wart the handwritten 0.6.x package had too; the M3 surface snapshot, captured on 3.13, exposed it by failing on the 3.11/3.12 CI legs while `selfhost-build` stayed green everywhere — the committed build bytes were never implicated). `create_server` now routes every callable it binds onto the MCP surface through the new `s0ma_mcp.components.normalize_docstring` (`inspect.cleandoc`, PEP 257 normalization), so all interpreters serve one canonical form. This is a (subtle) client-visible change: on 3.11/3.12 descriptions lose their source indentation and trailing indented blank; on 3.13+ they lose only a trailing newline. The committed surface snapshot is regenerated to the canonical form (mechanical — exactly the 20 served descriptions, each losing its trailing newline; verified `cleandoc(old) == new`), and new regression tests pin interpreter-independence on any single interpreter (the pre-3.13 raw form is simulated by assigning `__doc__` directly) and require every served description to be cleandoc-normalized, so a future factory rewrite that skips the helper fails on every Python version.
- **Repo tooling made Windows-safe (Windows-support plan, M0):** `scripts/check.py` now reconfigures stdout/stderr to UTF-8 with `errors="replace"` so the spelling-guard violation echo and the em-dash summary cannot crash with `UnicodeEncodeError` on a cp1252-redirected Windows console (POSIX output is byte-identical); `scripts/wheel_smoke_mcp.py` now resolves the scratch-venv interpreter portably (`Scripts\` on Windows, `bin/` elsewhere) and runs its probe subprocess with `PYTHONUTF8=1` so the probe's em-dash document output cannot crash under a non-UTF-8 Windows code page.
- **s0ma-core made Windows-correct (Windows-support plan, M1):** the example dispatcher now splits `S0MA_INTEGRATION_CMD` with non-POSIX `shlex` on Windows — POSIX mode ate path backslashes (`C:\Tools\python.exe` became `C:Toolspython.exe`), mangling the runner path into an uncaught `FileNotFoundError` — and strips the surrounding quotes non-POSIX mode preserves on fully-quoted tokens; subprocess launch failures (`OSError`/`FileNotFoundError`) now return the same structured failed result the timeout path produces instead of leaking a raw traceback; example subprocess output is decoded as UTF-8 with `errors="replace"` and child interpreters get `PYTHONIOENCODING=utf-8` so both sides agree regardless of platform locale; the dispatcher's temp dirs use `ignore_cleanup_errors=True` (on Windows a timed-out grandchild can briefly hold the directory open, turning teardown into `PermissionError`); generated sources (`LifecycleManager`) and import-hook cache artifacts (cached `.py`, `.s0ma.json`, `.s0ma.map`) pin `newline="\n"` so artifacts are byte-identical across platforms (INV-5); and the lifecycle temp-file promotion uses `Path.replace` instead of `Path.rename`, which refuses to overwrite an existing target on Windows. POSIX behavior and artifact bytes verified unchanged.
- **s0ma-dsl made Windows-correct (Windows-support plan, M2):** `migrate-ext` plan, refusal, and removal lines render relative paths with `/` on every OS (they rendered `\` on Windows); the Lark grammar load pins `encoding="utf-8"` (the locale default on a DBCS-code-page Windows could not decode it); every artifact, doc, and scaffold writer in the dsl — transpiled `.py`, `.s0ma.json` IR, `.s0ma.map`, `build.s0ma.json` manifest, `build.s0ma.pyi` stub, build `__init__.py`, `.s0ma.cache/` entries, rendered docs, scaffolds, and generated conftests — pins `newline="\n"` so artifacts are byte-identical across platforms (INV-5); `s0ma new project`'s printed `bootstrap_imports(...)` snippet renders the build dir with `as_posix()` (a native Windows path inside the quoted snippet was a `SyntaxError` — `\U` unicode escape); and the `new project` pyproject append plus the `migrate-ext` `[tool.*]` header rewrite now operate in bytes space, making their byte-preservation contracts literally true for CRLF and mixed-line-ending files on every OS (previously such files were silently rewritten wholesale to platform endings — on POSIX too). The dsl performance suite's hard budgets now scale by the optional `S0MA_TEST_PERF_SCALE` float env knob (default `1.0` — strict; not set in CI). POSIX behavior and artifact bytes verified unchanged except the diagnostic rendering called out under Changed.
- **s0ma-dsl Windows artifact nondeterminism (Windows-support plan, M3):** on Windows, builds of the same unchanged source appeared to produce different `.s0ma.json`/`.s0ma.map` bytes per output directory, and `s0ma build --check`/`transpile --check` falsely reported exactly one drifted line in every IR and source map. Root cause: each artifact embedded its build's own absolute output path in `transpiled_file`/`output_file`, and every replace-based path normalisation downstream — the `--check` drift comparator's temp-to-original substitution and the determinism suites' placeholder substitution — searched for the path's native single-backslash form, while `json.dumps` stores backslashes escaped inside JSON strings (`C:\Users\x` is stored as `C:\\Users\\x`), so on Windows the normalisation silently matched nothing and the embedded path surfaced as drift; on POSIX, forward-slash paths need no JSON escaping, which made the same substitutions succeed and masked the embedded paths entirely. Fixed by the basename change called out under Changed, plus an escape-aware `--check` comparator that substitutes both the raw and the JSON-escaped rendering of the temp directory (a harmless repeat on POSIX, where the two renderings coincide). The dsl determinism suites now compare raw artifact bytes with no path normalisation — so a reintroduced machine-dependent value fails on every OS, not only Windows — and print a unified diff of the divergent bytes on failure; a new regression test additionally asserts that neither the raw nor the JSON-escaped rendering of the output directory appears anywhere in IR or map bytes.

## [0.6.0] — 2026-06-10

### Added

- **`s0ma-mcp` eats its own dog food (FR-MCP-7):** every MCP tool, resource, and the `create_server` factory now registers as a s0ma component (kind, layer, intent, dependencies) in a dedicated package self-model (`s0ma_mcp/components.py`), and the server serves its own live component graph over MCP — the new `s0ma://self/model` resource (JSON, rendered via s0ma-core's registry snapshot) and the new read-only `describe_server` tool (same graph plus an LLM-ready text rendering). A drift test asserts the registered component set equals the served MCP surface, so self-model and reality cannot diverge.
- **MCP authoring prompts (FR-MCP-6):** `s0ma-mcp` now serves the three core authoring journeys as MCP prompts — `author_module(project_root, module_name, kind?)`, `fix_check_failures(project_root)`, and `migrate_project(project_root)` — surfaced by clients as first-class commands (in Claude Code: `/mcp__s0ma__<prompt>`). Each renders standalone product copy walking an agent through the journey with the server's own tools and resources, teaching the loop discipline: every diagnostic's `remediation` field is the fix instruction.
- **MCP tool annotations (FR-MCP-8):** every tool now carries honest `ToolAnnotations` so clients can auto-approve the read-only inner loop: `check`, `inspect_module`, and `describe_server` are read-only; `transpile`, `build_project`, `scaffold_module`, and `migrate_ext` are mutating but non-destructive and idempotent; `run_example` executes project code and says so. All tools are closed-world (explicit local project roots only). The full matrix — and the reasoning behind the judgment calls — is in the s0ma-mcp README and `tools.TOOL_ANNOTATIONS`.
- **`project_status` orientation tool (FR-MCP-9):** one read-only `s0ma-mcp` call answering "where am I": resolves the project the way the CLI does (`S0maProject.discover`), then reports `{ok, is_project, project_root, mode, modules, build: {built, status, stale_modules, manifest_path, transpiler_version}, suggested_next_action}`. Per-module freshness is judged by the build manifest's own recorded hashes (`build.s0ma.json` `source_hash` vs the current source through the dsl's `compute_file_hash`) — `fresh` / `stale` / `unbuilt` / `orphaned` — and `suggested_next_action` is a short imperative an agent can act on directly ("run check", "run build_project — 2 modules stale", …). A directory that is not a s0ma project answers `{ok: true, is_project: false}` — orientation, not an error.
- **MCP meta resources (FR-MCP-10):** `s0ma-mcp` now serves the generated diagnostic error catalog as `s0ma://guide/errors` (every error code, severity by mode, canonical fix — the `fix_check_failures` prompt now references it unconditionally), this changelog as `s0ma://meta/changelog`, and the live version surface `s0ma://meta/version` (`{server, s0ma_core, s0ma_dsl, s0ma_mcp, mcp_sdk, python}` rendered from `importlib.metadata` at read time — offline by design). The two document resources are committed copies under `s0ma_mcp/_docs/` resolving from the installed wheel, byte-compare drift-gated against their in-repo sources (`packages/s0ma-dsl/docs/_generated/common_errors.md` and the root `CHANGELOG.md`) like the existing guides.
- **`s0ma new project` — guided initialization (FR-DSL-5 v1.1):** `s0ma new project <dir> [--name N] [--layer L] [--mode M] [--quiet] [--format json]` takes a human from nothing to a built, bootstrap-ready project in one command: writes the `[tool.s0ma]` table (`source_roots = ["src"]`, `test_roots = ["tests"]`, `build_dir = "build"`, and the project's default authoring `mode`, default `"dev"`), scaffolds one starter module through the existing `new module` template, runs the first build through the build pipeline, and prints next steps — the `bootstrap_imports(<build_dir>)` runtime snippet, the check command, and the MCP registration hint (`claude mcp add s0ma -- s0ma-mcp`). An existing `pyproject.toml` is appended to byte-preservingly (the original content remains a strict prefix); a missing one is created minimal. The command refuses atomically — listing every reason, changing nothing — when `[tool.s0ma]` already exists or the starter module file is taken.
- **`s0ma doctor` — environment and project health report (FR-DSL-5 v1.1):** answers "is my environment healthy and what should I do next" in five sections, identical facts as text or `--format json`: `versions` (the three s0ma distributions via `importlib.metadata` — a missing `s0ma-mcp` is tolerated, core+dsl-only installs are supported per INV-6 — plus Python and the `mcp` SDK when present), `project` (resolution plus per-module build freshness judged by the manifest's recorded hashes: `fresh` / `stale` / `unbuilt` / `orphaned`, the same vocabulary as the MCP `project_status` tool; a malformed `[tool.s0ma]` table renders as a finding, never a crash), `mcp` (whether the `s0ma-mcp` server executable is on `PATH`, plus the registration hint), and the two clearly-labeled FR-COM placeholders: `license` (`not required in this version`) and `update_check` (`offline in this version — see PRD §7.5 (FR-COM-4)`). No network I/O anywhere. Doctor diagnoses, it does not gate: findings exit 0; non-zero only when the environment itself is broken (e.g. s0ma-dsl cannot import s0ma-core).
- **`.s0ma` TextMate grammar (`editors/s0ma.tmLanguage.json`):** minimal syntax highlighting for `.s0ma` sources in VS Code and anything TextMate-compatible — the eleven declaration keywords with `:: LAYER` annotations and the axon `->` arrow, the spec v0.16.0 field-key set, strings, comments, enum constants, and the `---` body fence scoped as embedded Python (`include: source.python`) through to the next declaration. Shipped as a standalone grammar file with manual-install instructions (`editors/README.md`); a packaged VS Code extension is phase 2 and an LSP is post-1.0 (PRD §9 non-goal 4). A pure-Python drift test (`packages/s0ma-dsl/tests/test_editor_grammar.py`) keeps the grammar's declaration set equal to the spec's and statically verifies the fence boundary against a multi-declaration fixture.

### Changed

- **Agent corpus updated for the phase-1 surfaces** (these documents ship in the `s0ma-mcp` wheel as live MCP resources): the DSL quick reference gained an "orientation surfaces" note (`project_status`, `s0ma://self/model`, `s0ma://guide/errors`, the three authoring prompts), and the agent system prompt now teaches the `s0ma-mcp` entry points — orient with the read-only `project_status` tool first, use the server's prompts when the client surfaces them, and look up unfamiliar diagnostic `code`s in the error catalog.

### Fixed

- **Docs: corrected stale CLI invocations.** The s0ma-dsl README, the migration guide, and the documentation-subsystem reference invoked subcommands as `s0ma-dsl <command>` (plus one pre-release `compile` spelling); the installed console script is `s0ma` (INV-2). All prose now matches the real CLI: `s0ma docs render` / `s0ma docs verify` / `s0ma docs check-drift` / `s0ma examples run` / `s0ma transpile`.

## [0.5.0] — 2026-06-09

The consolidation release. The two previously separate repositories — `s0ma-core` (distribution `s0ma-framework`) and `s0ma-dsl` — merged into this monorepo as a single uv workspace, with full git history imported, every package renamed to the canonical `s0ma` spelling (INV-1), the `.s0ma` file-extension family adopted, and versions moved to lockstep **0.5.0** (core 0.4.0 → 0.5.0; dsl 0.16.0 → 0.5.0).

### Added

- **NEW: `s0ma-mcp`** — MCP server exposing the s0ma authoring toolchain (transpile/build/check/inspect/scaffold/migrate) and agent guides to coding agents. Stdio transport via FastMCP, server name `s0ma-authoring`, console script `s0ma-mcp`. Seven tools returning structured `{ok, ...}` results with the DSL's JSON diagnostics (`migrate_ext` is dry-run by default), and four guide resources (`s0ma://guide/system-prompt`, `s0ma://guide/quick-reference`, `s0ma://guide/patterns`, `s0ma://spec/current`) packaged so they resolve from an installed wheel. Register with `claude mcp add s0ma -- uv run s0ma-mcp`.
- **`s0ma migrate-ext`** (s0ma-dsl) — one-shot, idempotent migration of user projects from the pre-2.0.0 letter-o extension family to the `.s0ma` family: renames `*.soma` → `*.s0ma`, `*.soma.json` → `*.s0ma.json`, `*.soma.map` → `*.s0ma.map` and `build.soma.json` → `build.s0ma.json` (suffix-anchored), rewrites the legacy `[tool.soma]` table to `[tool.s0ma]` (subtables included) byte-preserving the rest of `pyproject.toml`, and removes the legacy `.soma.cache/` / `__soma_cache__/` (pre-`.s0ma`-era) cache directories, which are regenerable. Plans first and refuses to overwrite existing targets (collisions abort with no changes); `--dry-run` prints the plan; the default run prints every rename. Run `s0ma build` afterwards to re-emit `.py` outputs.
- Monorepo workspace tooling: root `scripts/check.py` (one command for ruff, mypy `--strict` on `s0ma-core` and `s0ma-mcp`, all three test suites, and the INV-1 spelling guard), a root `Makefile` (`make check` / `test` / `lint`), GitHub Actions CI (`.github/workflows/ci.yml`: check matrix on Python 3.11/3.12/3.13 plus a wheel-build job), and a tag-triggered release workflow (`.github/workflows/release.yml`: the same gate, then wheels + sdists for all three packages attached to a GitHub Release whose notes are the matching section of this changelog; PyPI publishing stays a commented-out stub for now).
- Root `README.md` and this root `CHANGELOG.md` as the canonical repo-level documentation surfaces, alongside the product PRD at [`references/s0ma-prd.md`](references/s0ma-prd.md); root `CONTRIBUTING.md` and the release runbook `docs/RELEASING.md` (the pre-monorepo per-package release checklists now point there).

### Changed

- **Lockstep versioning (INV-4):** all packages now share one version, starting at 0.5.0. `s0ma-dsl` now requires `s0ma-core >= 0.5.0`. Each package changelog's unreleased section is folded into this entry and replaced with a pointer to this file.
- **s0ma-core — distribution renamed** `s0ma-framework` → `s0ma-core`. The Python module is unchanged (`import s0ma`).
- **s0ma-core — env vars renamed** `SOMA_INTEGRATION_CMD` → `S0MA_INTEGRATION_CMD`, `SOMA_EXAMPLE_BODY_PATH` → `S0MA_EXAMPLE_BODY_PATH`, and `SOMA_EXAMPLE_NAME` → `S0MA_EXAMPLE_NAME`.
- **s0ma-dsl — distribution renamed** `soma-dsl` → `s0ma-dsl`.
- **s0ma-dsl — Python module renamed** `soma_dsl` → `s0ma_dsl` (parser module file `parser/soma_parser.py` → `parser/s0ma_parser.py`; public functions containing the old spelling follow, e.g. `parse_soma` → `parse_s0ma` and `parse_soma_with_warnings` → `parse_s0ma_with_warnings`). The lazy DSL import paths in s0ma-core's import hook target the renamed module.
- **s0ma-dsl — CLI command renamed** `soma` → `s0ma` (entry point, `prog`, help text, error messages, Makefile).
- **s0ma-dsl — project config table renamed** `[tool.soma]` → `[tool.s0ma]`.
- **Class names renamed** `Soma*` → `S0ma*` (`SomaError` → `S0maError`, `SomaModule` → `S0maModule`, `SomaProject` → `S0maProject`, `SomaCLI` → `S0maCLI`, and every other `Soma`-prefixed class); component registration names follow (`SomaDSL_*` → `S0maDSL_*`).
- **Emitted module markers renamed** `__soma_doc_ref__` → `__s0ma_doc_ref__`, `__soma_doc_guide__` → `__s0ma_doc_guide__`, and `__soma_example__` → `__s0ma_example__` — on both the s0ma-dsl emitter side and the s0ma-core import-hook side (a cross-package contract changed in the same change-set). Stale transpile caches from older versions should be cleared and rebuilt.
- **BREAKING — file extension family renamed**: `.soma` → `.s0ma`, `.soma.json` → `.s0ma.json`, `.soma.map` → `.s0ma.map`, build manifest `build.soma.json` → `build.s0ma.json`. The incremental build-cache directory renamed `.soma.cache/` → `.s0ma.cache/`, the import-hook transpile cache directory renamed `__soma_cache__/` → `__s0ma_cache__/`, and the s0ma-core import hook (`S0maDSLLoader`) now registers for the `.s0ma` suffix and writes `.s0ma.json` / `.s0ma.map` siblings. Stale old-name cache directories are orphaned; `s0ma migrate-ext` removes them.
- **BREAKING — emitted hash markers renamed**: placeholders `__SOMA_SOURCE_HASH__` → `__S0MA_SOURCE_HASH__` and `__SOMA_OUTPUT_HASH__` → `__S0MA_OUTPUT_HASH__`; emitted comment markers `# soma-source-hash:` → `# s0ma-source-hash:` and `# soma-output-hash:` → `# s0ma-output-hash:` (the marker-parsing regexes in the emitter and CLI renamed in lockstep).
- **BREAKING — IR schema 2.0.0**: artifact extensions renamed to the `.s0ma` family and hash placeholder markers renamed to `__S0MA_*`; consumers of 1.x IR must regenerate. Golden doc fixtures and content hashes regenerated accordingly (diffs are spelling/extension/hash-only).
