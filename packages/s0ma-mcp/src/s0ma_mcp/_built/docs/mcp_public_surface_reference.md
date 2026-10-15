---
s0ma_kind: "doc-ref"
name: "mcp_public_surface_reference"
module: "tools"
format: "markdown"
intent: "Generated reference of every PUBLIC nerve the s0ma authoring MCP server registers — served tools, resource providers, and prompt renderers with their contracts — rendered from the registry so it cannot drift from the served surface."
schema_version: "3.0.0"
content_hash: "1:a0f4b4294c9049b6a660980ae1766bebbdabb7c76319e288e2dc27dcb49b5984"
---

# mcp_public_surface_reference

Generated reference of every PUBLIC nerve the s0ma authoring MCP server registers — served tools, resource providers, and prompt renderers with their contracts — rendered from the registry so it cannot drift from the served surface.

## intent

### nerve::adopt_file_tool

Records a pre-existing non-generated file as interim migration intake with mandatory authored intent, then points to author_module because roster adoption is not a semantic component model

### nerve::author_module_prompt

Walks an agent through authoring one new module end to end, rendering the steps of journey:mcp-authoring-loop from the record rather than from a copy in the prompt text, wrapped in the framing the record does not carry: the golden rule, the survival card, the argument shapes, and the editing that happens between steps

### nerve::build_project_tool

Runs a full cross-module s0ma build into the project's build dir and reports the build.s0ma.json manifest summary

### nerve::changelog_resource

Serves the monorepo's canonical changelog so agents and humans can read what changed in the installed toolchain version

### nerve::check_tool

Validates .s0ma source without emitting artifacts and returns structured diagnostics with per-finding remediation — the agent's inner loop

### nerve::describe_server_tool

Answers 'what is this server and what can it do' from the live self-model: the registered component graph plus an LLM-ready text rendering

### nerve::diagnose_fault_prompt

Guides an agent from an observed runtime fault through project_status, declared runtime/runbook context, suspect and dependency-neighbor inspection, host evidence when needed, and a state-preserving live behavior probe.

### nerve::docs_bundle

Hands out the packaged documentation snapshot as records — the one reading every documentation surface of this server answers from

### nerve::docs_concepts_resource

Serves the whole concept vocabulary in one read: every concept this build records, its id, its term and its authored one-sentence summary, in id order

### nerve::docs_index_resource

Serves the documentation index: which build this is, every category of topic it addresses with a count and an example id, how to ask for one, how many earlier names still answer, where the full pages are, and which s0ma://docs addresses belong to the other server

### nerve::docs_journey_recovery

Reads one journey's recovery paths out of the packaged snapshot: the named thing that can go wrong, what to do about it, and the surface that does it — so a prompt that teaches a journey teaches its recoveries from the same record rather than from a second account of them

### nerve::docs_journey_steps

Reads one journey's steps out of the packaged snapshot in the order they are walked, so a prompt that teaches a journey renders the steps the model records rather than a second copy somebody has to keep in step with them

### nerve::docs_journeys_resource

Serves every worked path this build records, step by step: what the path is for, each step's surface, why it is taken, what a good result looks like, any approval it needs, and what to do when a named thing goes wrong

### nerve::docs_page_for

Answers 'where is this written down in full' for one topic id, as a path in the s0ma repository — the reference pages' anchored deep link where the id class has one, the concept's own learning page, the page whose declared coverage names the topic, a document's or an authority clause's own source, and failing all of those the index that does list it

### nerve::docs_snapshot_identity

States which build of the documentation an answer came from: the release it describes, that release as a reader meets it (labelled when the build is not a release), and the snapshot digest of the records it was read out of

### nerve::docs_topic_index

Hands out the resolver's index over the packaged snapshot: everything this build can be asked about, and the ways of asking

### nerve::errors_resource

Serves the generated diagnostic error catalog — every s0ma-dsl error code with its severity by mode and canonical fix

### nerve::feedback_prompt

Walks an agent through carrying one piece of the user's own feedback to the s0ma team: identify it, confirm it is about s0ma when the user never said so, draft from evidence, prepare, show the exact feedback data and what redaction removed, submit only through the client's approval form, and relay the receipt or the saved draft

### nerve::fix_check_failures_prompt

Walks an agent through diagnosing and clearing check failures: group structured diagnostics by code, fix highest severity first via each remediation, re-check until clean

### nerve::getting_started_resource

Serves the canonical outcome-first cold-start journey: product fit, project creation, model orientation, dependency inspection, drift and release-gate proof, and explicit host verification.

### nerve::init_project_tool

Makes a directory a s0ma project by writing the [tool.s0ma] table into its pyproject.toml (creating a minimal pyproject when none exists) — the bootstrap step no other tool performs, so an agent is never left scaffolding modules into a directory that is not a project

### nerve::inspect_module_tool

Surfaces a built module's tagged .s0ma.json IR self-model (value/none/pending states preserved), or a per-module survey of the whole project when no module is named

### nerve::journey_ladder

Renders one recorded journey as the numbered ladder a prompt teaches: each step's call, why it is taken and what a good result looks like, any approval it needs, then the named things that can go wrong and what to do about each

### nerve::learn_s0ma_tool

Answers one question about s0ma itself from the documentation snapshot packaged with this release: resolves the asked-for topic by exact id, then by name, then by category, renders the bounded answer with its own build identity, and names both the committed page and the resource carrying the rest

### nerve::load_doc

Resolves the packaged agent-guide documents from s0ma_mcp/_docs package data via importlib.resources so they load from an installed wheel

### nerve::load_docs_model

Reads the packaged documentation snapshot out of s0ma_mcp/_docs package data, so the documentation read surfaces answer identically from a wheel and from a checkout

### nerve::migrate_ext_tool

Migrates a pre-consolidation project to the .s0ma extension family and [tool.s0ma] config — dry-run by default, refuse-don't-clobber

### nerve::migrate_project_prompt

Walks an agent through migrating a pre-consolidation project: migrate_ext dry-run, present the plan, apply, rebuild, and check until clean

### nerve::patterns_resource

Serves the DSL patterns guide of worked idioms and recipes for structuring non-trivial s0ma applications

### nerve::prepare_feedback_tool

Composes and locally redacts one s0ma-feedback@1 report from the user's own words and returns the exact data plus its fingerprint — the review step of the feedback journey, and deliberately the only one that is pure: it saves nothing and contacts nothing

### nerve::project_status_tool

Answers one-call orientation: is this a s0ma project, which mode and authoring posture, what is built or stale, which tagged pending semantic states block release, and the suggested next action

### nerve::quick_reference_machine_resource

Serves the generated s0ma quick reference as data (schema s0ma-quick-reference@1): the same facts as the page, rendered from the same value, so that a coding agent can read every line of every kind of declaration without reading a page laid out for a person

### nerve::quick_reference_resource

Serves the generated s0ma quick reference, the page written for a reader: every kind of declaration, every line each may carry with whether it must be written, the words a line chooses from, a checked sample of each kind, the everyday commands, the strictness modes and the basic rules, rendered by the documentation build from the language the check enforces

### nerve::run_example_tool

Discovers example declarations and executes each in its own timeout-guarded subprocess via core's isolated example runner

### nerve::runbook_resource

Serves the per-project operational runbook: run/health commands, env contracts, runtime state_paths that must never be reverted, module inventory, and the ops rules — rendered from the project's [tool.s0ma] keys, or a teaching variant naming what to declare when they are absent

### nerve::scaffold_module_tool

Emits a minimal known-valid .s0ma module skeleton from the DSL's own template and validates it with check before returning

### nerve::self_model_resource

Serves this server's own live component graph as JSON — every tool, resource, prompt, and factory with kind, layer, intent, and dependencies, the same registry the served surface is derived from (FR-MCP-7)

### nerve::self_prompting_resource

Serves the runtime self-prompting guide: verified companion loading, self_inspect adapter wiring, a ContextAssembler concierge-shaped example, and the recommended host prompt trust block.

### nerve::spec_resource

Serves the current normative s0ma DSL language specification — the authority when the guides are not enough

### nerve::submit_feedback_tool

Proves the report it was handed is the one prepare_feedback produced, obtains the user's own approval through the client's approval interaction, and only then sends it — saving a local draft on every other outcome so nothing a user wrote is ever lost and nothing they did not approve is ever sent

### nerve::survival_card_resource

Serves the survival card (under 4 KB): the bootstrap loop, the three body rules, one minimal valid module, and the recovery moves for the top diagnostic codes — deliberately small enough to hold in context

### nerve::system_prompt_resource

Serves the drop-in coding-agent system prompt that teaches an LLM how to author .s0ma files

### nerve::transpile_tool

Compiles .s0ma source (one file or directory) into .py plus .s0ma.json IR plus .s0ma.map artifacts via the DSL pipeline

### nerve::verify_host_tool

Explicitly executes each built production module under the host application's selected Python and reports interpreter, dependency, and isolated import evidence without pretending project code is sandboxed

### nerve::version_document

Builds the version surface as a JSON-compatible dict, rendered live from importlib.metadata with no file reads and no network (FR-MCP-10, P-6)

### nerve::version_resource

Serves the installed toolchain versions (server, the four s0ma distributions, MCP SDK, Python) live from importlib.metadata — offline by design

## expects

### nerve::adopt_file_tool

project_root is a directory

### nerve::author_module_prompt

project_root and module_name are non-empty; kind, when given, is a scaffold-recognized nerve kind

### nerve::build_project_tool

project_root is a directory

### nerve::changelog_resource

the changelog copy is packaged under s0ma_mcp/_docs

### nerve::check_tool

path (file or directory) or project_root or both are provided

### nerve::describe_server_tool

the s0ma_mcp self-model registry is importable

### nerve::diagnose_fault_prompt

project_root and fault are non-empty

### nerve::docs_bundle

the packaged snapshot is present and carries a schema version this build of the model reads

### nerve::docs_concepts_resource

the packaged snapshot is present and readable

### nerve::docs_index_resource

the packaged snapshot is present and readable

### nerve::docs_journey_recovery

journey_id names a journey this build records

### nerve::docs_journey_steps

journey_id names a journey this build records

### nerve::docs_journeys_resource

the packaged snapshot is present and readable

### nerve::docs_page_for

topic_id is an id this build addresses

### nerve::docs_snapshot_identity

the packaged snapshot is present and carries a build stamp

### nerve::docs_topic_index

the packaged snapshot is present and readable

### nerve::errors_resource

the generated error catalog is packaged under s0ma_mcp/_docs

### nerve::feedback_prompt

message, when given, is the user's own account of what they want reported; an absent message means the journey opens by asking for it

### nerve::fix_check_failures_prompt

project_root is non-empty

### nerve::getting_started_resource

the canonical getting-started guide is packaged under s0ma_mcp/_docs

### nerve::init_project_tool

project_root is a directory; any existing pyproject.toml is valid TOML

### nerve::inspect_module_tool

project_root is a directory; module, when given, names a built module

### nerve::journey_ladder

journey_id names a journey the packaged documentation snapshot records

### nerve::learn_s0ma_tool

topic is a non-empty question — a topic id, a term, or a category word

### nerve::load_doc

key is one of the GUIDE_DOCS loader keys

### nerve::load_docs_model

the snapshot is packaged under s0ma_mcp/_docs

### nerve::migrate_ext_tool

project_root is a directory

### nerve::migrate_project_prompt

project_root is non-empty

### nerve::patterns_resource

the patterns guide is packaged under s0ma_mcp/_docs

### nerve::prepare_feedback_tool

summary, category and impact carry the user's own account of the problem; mcp_client is supplied by the bootstrap binding layer, never by the caller

### nerve::project_status_tool

project_root is a directory

### nerve::quick_reference_machine_resource

the quick reference data twin is packaged under s0ma_mcp/_docs as a byte-identical copy of docs/_generated/quick-reference-machine.json

### nerve::quick_reference_resource

the quick reference page is packaged under s0ma_mcp/_docs as a byte-identical copy of docs/reference/quick-reference-readable.md

### nerve::run_example_tool

project_root is a directory; source_path, when given, exists

### nerve::runbook_resource

the server's working directory is at or under the target project (the blessed per-project `uv run s0ma-mcp` registration); absent that, the teaching variant renders

### nerve::scaffold_module_tool

project_root is a directory; module_name is non-empty; any output_dir lies inside the project tree

### nerve::self_model_resource

the s0ma_mcp self-model registry is importable

### nerve::self_prompting_resource

the runtime self-prompting guide is packaged under s0ma_mcp/_docs

### nerve::spec_resource

the language spec is packaged under s0ma_mcp/_docs

### nerve::submit_feedback_tool

envelope and payload_sha256 are the unmodified pair prepare_feedback returned; mcp_approval carries the user's decision and is supplied by the bootstrap binding layer, never by the caller

### nerve::survival_card_resource

the survival card is packaged under s0ma_mcp/_docs

### nerve::system_prompt_resource

the agent system prompt is packaged under s0ma_mcp/_docs

### nerve::transpile_tool

source_path exists; source_path and any output_dir lie inside the project tree

### nerve::verify_host_tool

project_root is a real built s0ma project; python, when supplied, identifies an executable host interpreter

### nerve::version_document

importlib.metadata can see the installed distributions

### nerve::version_resource

version_document renders the installed distributions

## guarantees

### nerve::adopt_file_tool

Returns a JSON-compatible dict with an ok bool key; never raises across the MCP boundary

### nerve::author_module_prompt

Returns the rendered journey text with every placeholder marker substituted, its numbered steps identical to the ones journey:mcp-authoring-loop records

### nerve::build_project_tool

Returns a JSON-compatible dict with an ok bool key; never raises across the MCP boundary

### nerve::changelog_resource

Returns the full changelog text

### nerve::check_tool

Returns a JSON-compatible dict with an ok bool key; never raises across the MCP boundary

### nerve::describe_server_tool

Returns a JSON-compatible dict with an ok bool key; never raises across the MCP boundary

### nerve::diagnose_fault_prompt

Returns the look-inward-first diagnostic journey with the project root and observed fault substituted

### nerve::docs_bundle

Returns the same DocsBundle object on every call in a process; offline, and it consults nothing but package data

### nerve::docs_concepts_resource

Returns one line per recorded concept, each carrying the summary the concept itself declares, word for word

### nerve::docs_index_resource

Returns the index text, every count and category read from the snapshot rather than written down

### nerve::docs_journey_recovery

Returns one entry per recorded recovery path, in the order the journey records them; an unknown id returns nothing rather than raising

### nerve::docs_journey_steps

Returns one entry per recorded step, in walking order, each carrying the surface it calls, why, what a good result looks like, and any approval the step needs; an unknown id returns nothing rather than raising

### nerve::docs_journeys_resource

Returns one section per recorded journey with its steps in walking order, read from the same records the journey-shaped prompts render

### nerve::docs_page_for

Returns a non-empty repository-relative page path, never a machine path and never an invented one

### nerve::docs_snapshot_identity

Returns exactly the three identity keys, all non-empty

### nerve::docs_topic_index

Returns the same TopicIndex object on every call in a process

### nerve::errors_resource

Returns the full error-catalog text

### nerve::feedback_prompt

Returns the rendered journey text with no placeholder marker left behind, whether or not a message was supplied

### nerve::fix_check_failures_prompt

Returns the rendered journey text with the project root substituted

### nerve::getting_started_resource

Returns the same getting-started Markdown embedded in the root README

### nerve::init_project_tool

Returns a JSON-compatible dict with an ok bool key; never raises across the MCP boundary; idempotent — an already-initialized project is an ok answer with changed: false and nothing is rewritten

### nerve::inspect_module_tool

Returns a JSON-compatible dict with an ok bool key and preserves canonical semantic-state tags; never raises across the MCP boundary

### nerve::journey_ladder

Returns the steps in walking order, every word of them read from the record; a journey this build does not record renders as nothing rather than as an invented path

### nerve::learn_s0ma_tool

Returns a JSON-compatible dict with an ok bool key; never raises across the MCP boundary; offline and deterministic — the same question returns the same answer from the same build, with no model and no network in the path

### nerve::load_doc

Returns the packaged document's full UTF-8 text

### nerve::load_docs_model

Returns the snapshot's full UTF-8 text, byte-identical to the in-repo snapshot it was copied from

### nerve::migrate_ext_tool

Returns a JSON-compatible dict with an ok bool key; never raises across the MCP boundary

### nerve::migrate_project_prompt

Returns the rendered journey text with the project root substituted

### nerve::patterns_resource

Returns the full patterns-guide text

### nerve::prepare_feedback_tool

Never writes to disk — the installation pseudonym is read, never minted, so the read-only claim is literal — never opens a socket, and returns the redacted report byte-identical to what submit_feedback will hash, show, and send

### nerve::project_status_tool

Returns a JSON-compatible dict with an ok bool key and semantic_debt inventory; never raises across the MCP boundary; a non-project directory is a valid ok answer, not an error

### nerve::quick_reference_machine_resource

Returns the full quick-reference document as JSON text

### nerve::quick_reference_resource

Returns the full quick-reference page as Markdown

### nerve::run_example_tool

Returns a JSON-compatible dict with an ok bool key; never raises across the MCP boundary

### nerve::runbook_resource

Returns the runbook markdown text; never raises and never empty — an unresolved project yields the teaching variant

### nerve::scaffold_module_tool

Returns a JSON-compatible dict with an ok bool key; never raises across the MCP boundary

### nerve::self_model_resource

Returns the live component graph as pretty-printed JSON text

### nerve::self_prompting_resource

Returns the full runtime self-prompting guide text

### nerve::spec_resource

Returns the full specification text

### nerve::submit_feedback_tool

Sends only on an explicit accept, reports a receipt only when its payload_sha256 matches what was approved, and saves a draft on refusal, cancellation, absent approval, and transport failure alike

### nerve::survival_card_resource

Returns the full survival-card text (deliberately under a few KB)

### nerve::system_prompt_resource

Returns the full prompt text

### nerve::transpile_tool

Returns a JSON-compatible dict with an ok bool key; never raises across the MCP boundary

### nerve::verify_host_tool

Returns s0ma-host-verification@1 evidence and never raises across the MCP boundary; imported trusted project code may perform arbitrary side effects

### nerve::version_document

Returns a dict with server, s0ma_core, s0ma_dsl, s0ma_mcp, s0ma_studi0, mcp_sdk, and python keys; None marks a distribution that is not installed

### nerve::version_resource

Returns the version document as pretty-printed JSON text

## forbids

### nerve::adopt_file_tool

Never records a file without a non-empty, one-line authored intent, and never raises across the MCP boundary.

### nerve::author_module_prompt

Never renders the authoring steps from a copy in its own text instead of the journey:mcp-authoring-loop record.

### nerve::build_project_tool

Never raises across the MCP boundary.

### nerve::changelog_resource



### nerve::check_tool

Never emits artifacts while it validates source, and never raises across the MCP boundary.

### nerve::describe_server_tool

Never describes a component graph that can drift from the MCP surface this server serves, and never raises across the MCP boundary.

### nerve::diagnose_fault_prompt



### nerve::docs_bundle

Never reaches the network or consults anything but package data.

### nerve::docs_concepts_resource



### nerve::docs_index_resource

Never states a count or a category that is written down rather than read from the packaged snapshot.

### nerve::docs_journey_recovery



### nerve::docs_journey_steps



### nerve::docs_journeys_resource



### nerve::docs_page_for

Never answers with a machine path or an invented page path.

### nerve::docs_snapshot_identity

Never gives the version a reader meets without its channel label when the build is not a release.

### nerve::docs_topic_index



### nerve::errors_resource



### nerve::feedback_prompt



### nerve::fix_check_failures_prompt



### nerve::getting_started_resource



### nerve::init_project_tool

Never rewrites a project that is already initialized, and never raises across the MCP boundary.

### nerve::inspect_module_tool

Never raises across the MCP boundary.

### nerve::journey_ladder

Never invents a step, or a path for a journey the packaged documentation snapshot does not record.

### nerve::learn_s0ma_tool

Never calls a model or reaches the network to answer, and never raises across the MCP boundary.

### nerve::load_doc



### nerve::load_docs_model



### nerve::migrate_ext_tool

Never changes the project unless the caller turns the default dry run off, never clobbers an existing file, and never raises across the MCP boundary.

### nerve::migrate_project_prompt



### nerve::patterns_resource



### nerve::prepare_feedback_tool

Never writes to disk, mints the installation pseudonym or opens a socket.

### nerve::project_status_tool

Never raises across the MCP boundary.

### nerve::quick_reference_machine_resource



### nerve::quick_reference_resource



### nerve::run_example_tool

Never runs an example in the server's own process or without a timeout, and never raises across the MCP boundary.

### nerve::runbook_resource



### nerve::scaffold_module_tool

Never raises across the MCP boundary.

### nerve::self_model_resource

Never serves a component graph that can drift from the MCP surface this server serves.

### nerve::self_prompting_resource



### nerve::spec_resource



### nerve::submit_feedback_tool

Never sends a report the user has not explicitly accepted, or one it has not proved is the report prepare_feedback produced.

### nerve::survival_card_resource



### nerve::system_prompt_resource



### nerve::transpile_tool

Never raises across the MCP boundary.

### nerve::verify_host_tool

Never presents the project code it imports as sandboxed, and never raises across the MCP boundary.

### nerve::version_document

Never reads a version from a packaged file or reaches the network; each one comes live from the running environment.

### nerve::version_resource

Never reaches the network to report the installed versions.
