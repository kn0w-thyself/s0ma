# What s0ma can do

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

s0ma serves 261 capabilities across 9 channels. Each row names one of them: what it is called, the id the model addresses it by, what it does, what calling it touches, and whether the model can point at the code behind it. 92 of the 261 reach a registered component; the rest carry a written reason instead, and both are listed with their reasons in `docs/_generated/inventory-surfaces.json`.

Effects are read from the thing itself wherever the thing declares them: `none`, `read`, `write`, `network`, `subprocess`, `credential`, `approval`. Where a capability declares nothing, the row says so rather than guessing.

## Command line

44 of the 261. Channel: `cli`.

| Name | Id | What it does | Effects | Binding |
| --- | --- | --- | --- | --- |
| s0ma adopt | `cli:s0ma/adopt` | Retrofit an existing codebase: `adopt scan` reads a tree and plans the conversion, `adopt init` makes it a s0ma project, `adopt draft` converts one module, `adopt baseline` and `adopt verify-parity` prove the conversion kept its promises, `adopt status` says where you are and what to run next; `adopt file <path>` registers one real (non-generated) file into the self-model | read | bound |
| s0ma adopt baseline | `cli:s0ma/adopt/baseline` | Record what a module's Python offers today, before you convert it — and long before you delete it | read, write | bound |
| s0ma adopt draft | `cli:s0ma/adopt/draft` | Turn one Python module into a .s0ma draft. The Python file is read and never changed | read, write | bound |
| s0ma adopt file | `cli:s0ma/adopt/file` | Record one pre-existing file as interim migration intake; newly-written code starts from intent with author_module | read, write | exception |
| s0ma adopt init | `cli:s0ma/adopt/init` | Make an existing codebase a s0ma project. Touches no application file | read, write | bound |
| s0ma adopt scan | `cli:s0ma/adopt/scan` | Read an existing codebase and say what is in it and what to convert first. Writes nothing | read | bound |
| s0ma adopt status | `cli:s0ma/adopt/status` | Where this retrofit stands, and the one command to run next. Writes nothing | read | bound |
| s0ma adopt verify-parity | `cli:s0ma/adopt/verify-parity` | Compare a built module with the baseline taken from the Python it replaced, and name every difference | read | bound |
| s0ma build | `cli:s0ma/build` | Full project build with cross-module resolution | read, write | bound |
| s0ma check | `cli:s0ma/check` | Validate .s0ma file(s) without generating output | read, write | bound |
| s0ma deferred-surface | `cli:s0ma/deferred-surface` | List every deferred:-marked declaration in the project (POST-12f). | read | bound |
| s0ma docs | `cli:s0ma/docs` | Learn how s0ma works: run `s0ma docs` for the learning map, or list/show/search one topic. Also renders and gates this project's own documentation (render, verify, check-drift, compose, check) | read | bound |
| s0ma docs check | `cli:s0ma/docs/check` | Compose the documentation snapshot and byte-compare it against the committed outputs, writing nothing | read | bound |
| s0ma docs check-drift | `cli:s0ma/docs/check-drift` | Re-render every doc and byte-compare against committed output files | read | bound |
| s0ma docs compose | `cli:s0ma/docs/compose` | Compose the documentation snapshot and write its declared outputs | read, write | bound |
| s0ma docs list | `cli:s0ma/docs/list` | List every topic in one part of the documentation, or in all five | read | bound |
| s0ma docs render | `cli:s0ma/docs/render` | Render every doc-ref/doc-guide to its declared output: path | read, write | bound |
| s0ma docs search | `cli:s0ma/docs/search` | Find every topic a word or phrase could mean, strongest match first | read | bound |
| s0ma docs show | `cli:s0ma/docs/show` | Show one topic in full, by its id or by a name it goes by | read | bound |
| s0ma docs verify | `cli:s0ma/docs/verify` | Run doc-subsystem validation layers without rendering | read | bound |
| s0ma doctor | `cli:s0ma/doctor` | Environment and project health report: package versions, project detection, build freshness, MCP registration hint. Diagnoses, does not gate — exit 0 with findings; non-zero only when the environment itself is broken. License/update sections are offline placeholders in this version. | read | bound |
| s0ma examples | `cli:s0ma/examples` | Run registered .s0ma example declarations | read | bound |
| s0ma examples run | `cli:s0ma/examples/run` | Run every example, or one named example | read, subprocess, write | bound |
| s0ma feedback | `cli:s0ma/feedback` | Send feedback about s0ma, and manage the reports you have sent | approval, network, read, write | bound |
| s0ma feedback delete | `cli:s0ma/feedback/delete` | Delete one of your feedback reports, or all of them | approval, network, read | exception |
| s0ma feedback drafts | `cli:s0ma/feedback/drafts` | List the reports written here but not yet sent | read, write | exception |
| s0ma feedback enroll | `cli:s0ma/feedback/enroll` | Connect this machine to your s0ma account so it can send feedback | credential, network, read, write | exception |
| s0ma feedback list | `cli:s0ma/feedback/list` | List the feedback reports you have sent | network, read | exception |
| s0ma feedback submit | `cli:s0ma/feedback/submit` | Show a saved draft again and send it if you approve | approval, network, read, write | exception |
| s0ma graph | `cli:s0ma/graph` | Emit dependency graph data for a module or project | read | bound |
| s0ma inspect | `cli:s0ma/inspect` | Query the self-model of a compiled module or project | read | bound |
| s0ma migrate | `cli:s0ma/migrate` | Plan or apply a versioned source-grammar migration. | read | bound |
| s0ma migrate-ext | `cli:s0ma/migrate-ext` | One-shot migration from the pre-2.0.0 letter-o extension family to .s0ma / .s0ma.json / .s0ma.map (build manifest build.s0ma.json): renames files, rewrites the legacy [tool.*] config table to [tool.s0ma], and removes legacy cache directories. Idempotent; refuses to overwrite existing targets. | read, write | bound |
| s0ma migrate-layout | `cli:s0ma/migrate-layout` | One-shot migration: clean legacy __s0ma_cache__/ and per-layer subdirs from the project's build directory, then run a fresh `s0ma build`. Idempotent. | read, write | bound |
| s0ma migrate grammar | `cli:s0ma/migrate/grammar` | Materialise explicit semantic state. Dry-run by default; use --apply for an atomic whole-project rewrite. | read, write | exception |
| s0ma new | `cli:s0ma/new` | Scaffold a new .s0ma file from a template, or initialize a whole project (`s0ma new project <dir>`) | read, write | bound |
| s0ma score | `cli:s0ma/score` | Self-knowledge score: a single number + a three-faculty breakdown for a s0ma project (text or --format json). | read | bound |
| s0ma studi0 | `cli:s0ma/studi0` | Serve the studi0 viewer for a built s0ma project on loopback | network, read, subprocess | bound |
| s0ma test | `cli:s0ma/test` | Discover the project, build source + tests, run pytest (args after `--` pass through to pytest) | read, subprocess, write | bound |
| s0ma test-conftest | `cli:s0ma/test-conftest` | Generate a conftest.py that mocks the s0ma runtime for testing | read, write | bound |
| s0ma topo | `cli:s0ma/topo` | Print the project's topological module import order, one module per line | read | bound |
| s0ma transpile | `cli:s0ma/transpile` | Transpile .s0ma file(s) to .py + .s0ma.json + .s0ma.map | read, write | bound |
| s0ma verify | `cli:s0ma/verify` | Check transpiled files for drift from .s0ma sources (fast, no transpile needed) | read | bound |
| s0ma verify-host | `cli:s0ma/verify-host` | Explicitly import built production modules under the host application's Python (executes trusted project code) | read, subprocess | bound |

## Tools an agent can call

27 of the 261. Channel: `mcp_tool`.

| Name | Id | What it does | Effects | Binding |
| --- | --- | --- | --- | --- |
| adopt_file | `mcp:tool/adopt_file` | When migrating old Python, record it as interim roster debt. | write | bound |
| build_project | `mcp:tool/build_project` | After check is clean, build the complete configured project. | write | bound |
| check | `mcp:tool/check` | After editing intent or code, validate before building. | read | bound |
| check_health | `mcp:tool/check_health` | Get the system's current health status and anomalies. | not declared | exception |
| describe_server | `mcp:tool/describe_server` | When you do not know which s0ma surface fits, ask the server. | read | bound |
| describe_system | `mcp:tool/describe_system` | Get a natural language overview of the system architecture. | not declared | exception |
| explain_dependency | `mcp:tool/explain_dependency` | Explain why component 'source' depends on component 'target'. | not declared | exception |
| find_component | `mcp:tool/find_component` | Get detailed information about a specific component. | not declared | exception |
| get_compliance_checklist | `mcp:tool/get_compliance_checklist` | Get the quick compliance checklist for creating/modifying components. | not declared | exception |
| get_component_example | `mcp:tool/get_component_example` | Get a real component from the registry as a copyable template. | not declared | exception |
| get_examples_for | `mcp:tool/get_examples_for` | List canonical examples demonstrating a component. | not declared | exception |
| get_extension_points | `mcp:tool/get_extension_points` | Find where new components can be added safely. | not declared | exception |
| get_impact | `mcp:tool/get_impact` | Analyze what would be affected if a component changes. | not declared | exception |
| init_project | `mcp:tool/init_project` | When project_status says false, add the canonical project table. | write | bound |
| inspect_module | `mcp:tool/inspect_module` | Before grepping for where X is handled, inspect the self-model. | read | bound |
| learn_about_s0ma | `mcp:tool/learn_about_s0ma` | Learn how to use the s0ma framework. | not declared | exception |
| learn_s0ma | `mcp:tool/learn_s0ma` | Ask s0ma one question about s0ma, and get a short answer back. | read | bound |
| migrate_ext | `mcp:tool/migrate_ext` | When legacy extension names remain, preview and apply their migration. | write | bound |
| prepare_feedback | `mcp:tool/prepare_feedback` | Write up feedback about s0ma for the user to review — read-only. | read | bound |
| project_status | `mcp:tool/project_status` | When landing in a tree or diagnosing it, orient in one call. | read | bound |
| query_system | `mcp:tool/query_system` | Ask a natural language question about the system. | not declared | exception |
| run_example | `mcp:tool/run_example` | When documentation claims behavior, run its executable example. | subprocess, write | bound |
| scaffold_module | `mcp:tool/scaffold_module` | When starting new behavior, create a valid intent-first component. | write | bound |
| submit_feedback | `mcp:tool/submit_feedback` | Ask the user to approve this exact feedback data, then send it. | approval, network, write | bound |
| suggest_fix | `mcp:tool/suggest_fix` | Given an anomaly description, suggest how to fix it. | not declared | exception |
| transpile | `mcp:tool/transpile` | When iterating on one source, emit its Python, IR, and source map. | write | bound |
| verify_host | `mcp:tool/verify_host` | After static checks pass, prove imports in the app's real Python. | approval, subprocess, write | bound |

## Resources an agent can read

24 of the 261. Channel: `mcp_resource`.

| Name | Id | What it does | Effects | Binding |
| --- | --- | --- | --- | --- |
| s0ma://docs/architecture | `mcp:resource/s0ma://docs/architecture` | How s0ma's own architecture is documented, and where to read it. | not declared | exception |
| s0ma://docs/compliance-rules | `mcp:resource/s0ma://docs/compliance-rules` | Compliance rules (Appendix C) — every rule for s0ma-compliant code. | not declared | exception |
| s0ma://docs/concepts | `mcp:resource/s0ma://docs/concepts` | Every s0ma concept, one line each. | read | bound |
| s0ma://docs/index | `mcp:resource/s0ma://docs/index` | What s0ma can be asked about, and how to ask. | read | bound |
| s0ma://docs/journeys | `mcp:resource/s0ma://docs/journeys` | Every worked path through s0ma, step by step. | read | bound |
| s0ma://docs/registered-docs | `mcp:resource/s0ma://docs/registered-docs` | Every registered doc-ref, doc-guide, and example. | not declared | exception |
| s0ma://docs/user-guide | `mcp:resource/s0ma://docs/user-guide` | The complete s0ma user guide — how to build applications with s0ma. | not declared | exception |
| s0ma://guide/errors | `mcp:resource/s0ma://guide/errors` | The s0ma diagnostic error catalog (FR-MCP-10). | read | bound |
| s0ma://guide/getting-started | `mcp:resource/s0ma://guide/getting-started` | What s0ma is, who it fits, and how to prove its value. | read | bound |
| s0ma://guide/patterns | `mcp:resource/s0ma://guide/patterns` | The s0ma DSL patterns guide — idioms for real applications. | read | bound |
| s0ma://guide/quick-reference | `mcp:resource/s0ma://guide/quick-reference` | The s0ma quick reference: every declaration, line by line. | read | bound |
| s0ma://guide/quick-reference.json | `mcp:resource/s0ma://guide/quick-reference.json` | The s0ma quick reference as data (JSON, schema s0ma-quick-reference@1). | read | bound |
| s0ma://guide/self-prompting | `mcp:resource/s0ma://guide/self-prompting` | Runtime self-prompting and verified self_inspect wiring. | read | bound |
| s0ma://guide/survival-card | `mcp:resource/s0ma://guide/survival-card` | The s0ma survival card (under 4 KB) — read this FIRST, hold it in context. | read | bound |
| s0ma://guide/system-prompt | `mcp:resource/s0ma://guide/system-prompt` | The s0ma DSL coding-agent system prompt. | read | bound |
| s0ma://meta/changelog | `mcp:resource/s0ma://meta/changelog` | The s0ma platform changelog — what's new, per version (FR-MCP-10). | read | bound |
| s0ma://meta/version | `mcp:resource/s0ma://meta/version` | The installed s0ma toolchain versions as JSON (FR-MCP-10). | read | bound |
| s0ma://model/component-template | `mcp:resource/s0ma://model/component-template` | A real component from the registry formatted as a copyable template. | not declared | exception |
| s0ma://model/docs-for/{component} | `mcp:resource/s0ma://model/docs-for/{component}` | Doc-refs and doc-guides covering ``component``. | not declared | exception |
| s0ma://model/examples-for/{component} | `mcp:resource/s0ma://model/examples-for/{component}` | Canonical examples demonstrating ``component``. | not declared | exception |
| s0ma://model/registry-summary | `mcp:resource/s0ma://model/registry-summary` | Live system overview from the self-model. | not declared | exception |
| s0ma://project/runbook | `mcp:resource/s0ma://project/runbook` | The project's operational runbook (O1) as markdown. | read | bound |
| s0ma://self/model | `mcp:resource/s0ma://self/model` | The authoring server's live self-model (FR-MCP-7) as JSON. | read | bound |
| s0ma://spec/current | `mcp:resource/s0ma://spec/current` | The current s0ma DSL language specification (normative). | read | bound |

## Prompts an agent can start from

5 of the 261. Channel: `mcp_prompt`.

| Name | Id | What it does | Effects | Binding |
| --- | --- | --- | --- | --- |
| author_module | `mcp:prompt/author_module` | Author a new s0ma module end to end. | none | bound |
| diagnose_fault | `mcp:prompt/diagnose_fault` | Diagnose an observed runtime fault from self-knowledge first. | none | bound |
| feedback | `mcp:prompt/feedback` | Send the user's feedback about s0ma to the s0ma team. | none | bound |
| fix_check_failures | `mcp:prompt/fix_check_failures` | Diagnose and fix s0ma check failures until the project is clean. | none | bound |
| migrate_project | `mcp:prompt/migrate_project` | Migrate a pre-consolidation project to the current s0ma surface. | none | bound |

## The studi0 viewer

5 of the 261. Channel: `studi0`.

| Name | Id | What it does | Effects | Binding |
| --- | --- | --- | --- | --- |
| /api/graph | `studi0:action/api/graph` | The whole component graph of the project being shown, wrapped in the sequence number it belongs to, fetched only when the sequence number says it is worth fetching. | read | bound |
| /api/state | `studi0:action/api/state` | The cheap poll: which reading this is, whether the build still matches the sources it was built from, which modules have moved on, and what an agent has said it is doing. | read | bound |
| /assets/app.css | `studi0:action/assets/app.css` | The sh0w page's stylesheet, served as the build embedded it. | none | bound |
| /assets/app.js | `studi0:action/assets/app.js` | The sh0w page's script, served as the build embedded it — the whole of the viewer's behaviour. | none | bound |
| / | `studi0:action/index` | The sh0w page itself — the one document studi0 hands a browser, which then learns everything it draws from the graph API. | none | bound |

## The self-description interface

14 of the 261. Channel: `rest`.

| Name | Id | What it does | Effects | Binding |
| --- | --- | --- | --- | --- |
| GET /self/anomalies | `rest:GET:/self/anomalies` | Get current verification anomalies (code-model discrepancies). | read | bound |
| GET /self/component/{name} | `rest:GET:/self/component/{name}` | Get detailed information about a specific component. | read | bound |
| GET /self/components | `rest:GET:/self/components` | List all registered components with their metadata. | read | bound |
| GET /self/doc/{name} | `rest:GET:/self/doc/{name}` | Detailed view of a single doc-ref or doc-guide. Looks up ``name`` first in the doc-ref store, then in the doc-guide store. Returns 404 if the name is not registered as either. | read | bound |
| GET /self/docs | `rest:GET:/self/docs` | List every registered doc-ref, doc-guide, and example. Combines the three documentation-subsystem stores into a single natural-language overview plus structured data. | read | bound |
| GET /self/drift | `rest:GET:/self/drift` | Recompute the transitive content hash for every registered doc-ref and doc-guide, compare it against the stored hash, and report divergence as drift. Degrades to a hash-presence report when nothing is hashed yet. | read | bound |
| GET /self/example/{name} | `rest:GET:/self/example/{name}` | Detailed view of a single example registration, including its body and the entities it demonstrates. Returns 404 if the name is not a registered example. | read | bound |
| GET /self/examples | `rest:GET:/self/examples` | List every registered example with its ``runs_in`` mode and the entities it demonstrates. | read | bound |
| GET /self/extensions | `rest:GET:/self/extensions` | Find where new components can be added safely. | read | bound |
| GET /self/graph | `rest:GET:/self/graph` | Get the full dependency graph in both JSON adjacency list and Graphviz DOT format. | read | bound |
| GET /self/health | `rest:GET:/self/health` | Get the system's current health status and verification results. | read | bound |
| GET /self/impact/{name} | `rest:GET:/self/impact/{name}` | Analyze what would be affected if a component changes. | read | bound |
| GET /self/overview | `rest:GET:/self/overview` | Get a natural language overview of the system architecture. | read | bound |
| POST /self/query | `rest:POST:/self/query` | Ask a natural language question about the system. Supports questions about components, dependencies, health, impact, extension points, and more. | read | bound |

## Project settings

19 of the 261. Channel: `config`.

| Name | Id | What it does | Effects | Binding |
| --- | --- | --- | --- | --- |
| [tool.s0ma].adoption_exempt | `config:adoption_exempt` | Project-local adoption classifications. | none | exception |
| [tool.s0ma].attribute_budgets | `config:attribute_budgets` | Project-level budgets for ``declares_attributes:`` namespaces. | none | exception |
| [tool.s0ma].authoring | `config:authoring` | The project's authoring posture, read from ``[tool.s0ma].authoring``. | none | exception |
| [tool.s0ma].bootstrap_files | `config:bootstrap_files` | Absolute paths to plain-Python files that are intentional bootstrap exceptions and should not be flagged by drift / missing-IR checks. | none | exception |
| [tool.s0ma].build_dir | `config:build_dir` | Absolute directory for transpiled build artifacts. | none | exception |
| [tool.s0ma].env | `config:env` | The environment variables the built application reads, keyed by name, each carrying its :class:`RunbookEnvVar` contract (required / fail_fast / default). | none | exception |
| [tool.s0ma].fixtures_format | `config:fixtures_format` | The expected format for non-``.s0ma`` test fixtures. | none | exception |
| [tool.s0ma].health_command | `config:health_command` | The command that checks the running application's health, verbatim as authored under ``[tool.s0ma].health_command`` (e.g. ``"curl -fsS localhost:8080/health"``). | none | exception |
| [tool.s0ma].mode | `config:mode` | The project's declared strictness mode, read from ``[tool.s0ma].mode``. | none | exception |
| [tool.s0ma].package_markers | `config:package_markers` | Absolute paths to ``__init__.py`` files that the author explicitly classifies as package markers. | none | exception |
| [tool.s0ma].run_command | `config:run_command` | The command that runs the built application, verbatim as authored under ``[tool.s0ma].run_command`` (e.g. ``"uv run myapp"``). | none | exception |
| [tool.s0ma].runbook_notes | `config:runbook_notes` | Free-form operational notes authored under ``[tool.s0ma].runbook_notes`` — either a single string (one note) or a list of strings (several). | none | exception |
| [tool.s0ma].source_roots | `config:source_roots` | Absolute directories holding ``.s0ma`` source modules. | none | exception |
| [tool.s0ma].state_paths | `config:state_paths` | Project-relative paths (verbatim as authored under ``[tool.s0ma].state_paths``) that hold **runtime state** — data the running application produces and owns, NOT derivable from source. | none | exception |
| [tool.s0ma].test_layering | `config:test_layering` | Cross-module layer-reachability stance for test-context modules. | none | exception |
| [tool.s0ma].test_module_name_prefix_by_dir | `config:test_module_name_prefix_by_dir` | Whether to auto-prefix test modules by parent directory when checking for ``MODULE_NAME_COLLISION``. | none | exception |
| [tool.s0ma].test_roots | `config:test_roots` | Absolute directories holding ``.s0ma`` test modules. | none | exception |
| [tool.s0ma].test_runner | `config:test_runner` | The test runner this project uses, named once for the whole project. | none | exception |
| [tool.s0ma].venv_path | `config:venv_path` | Project-relative host virtual-environment path for ``verify-host``. | none | exception |

## Reports s0ma can make

114 of the 261. Channel: `diagnostic`.

| Name | Id | What it does | Effects | Binding |
| --- | --- | --- | --- | --- |
| ADOPTED_CHURN | `diagnostic:ADOPTED_CHURN` | A roster file has been re-adopted at least three times; componentize it instead of repeatedly refreshing interim migration telemetry. | none | exception |
| ADOPT_PLACEHOLDER_INTENT | `diagnostic:ADOPT_PLACEHOLDER_INTENT` | A field still carries the `FIXME(adopt):` placeholder `s0ma adopt draft` left for a person to replace; write the sentence in your own words, because a draft derives structure and never invents meaning. | none | exception |
| ADOPT_UNPLACED_CODE | `diagnostic:ADOPT_UNPLACED_CODE` | A module still carries an `adopt: unplaced` quarantine cell holding source text the draft could not place; move the text into the declaration it belongs to, or delete it, and delete the cell. | none | exception |
| AMBIGUOUS_TEST_TARGET | `diagnostic:AMBIGUOUS_TEST_TARGET` | A bare `tests:` entry resolves to components in two or more modules. | none | exception |
| ASSERT_FAILED | `diagnostic:ASSERT_FAILED` | A doc-guide `asserts:` expression evaluated to false. | none | exception |
| ASSERT_SYNTAX_ERROR | `diagnostic:ASSERT_SYNTAX_ERROR` | A doc-guide `asserts:` expression falls outside the narrow assert grammar. | none | exception |
| ASSERT_UNEVALUABLE | `diagnostic:ASSERT_UNEVALUABLE` | A doc-guide `asserts:` expression references a field or entity that cannot be evaluated. | none | exception |
| ATTRIBUTE_BUDGET_VIOLATION | `diagnostic:ATTRIBUTE_BUDGET_VIOLATION` | A nerve's `declares_attributes:` entry violates a project-configured `[tool.s0ma.attribute_budgets]` rule. | none | exception |
| BARE_IMPORT | `diagnostic:BARE_IMPORT` | A nerve or test body contains a bare `import` statement. The fix is one edit with two parts: declare the dependency in the module header — `requires:` for Python imports, `deferred_requires:` for a call-time import, `uses:` for s0ma components — and delete the import line from the body. The transpiler writes the import lines from the declarations. | none | exception |
| BUILD_DIR_OVERRIDE_CONFLICT | `diagnostic:BUILD_DIR_OVERRIDE_CONFLICT` | `s0ma build --output-dir <path>` was invoked with a path that disagrees with the resolved `[tool.s0ma].build_dir`. Drop `--output-dir` to let the project model resolve the build dir, or pass `--force-output-dir` to proceed with the override (a one-line stderr notice is emitted). | none | exception |
| CIRCULAR_DEPENDENCY | `diagnostic:CIRCULAR_DEPENDENCY` | The four-phase resolver's DFS detected a cycle in the declared cross-module architecture edges (`uses:` entries plus qualified `depends_on:` targets). | none | exception |
| CLASS_BODY_IN_NERVE | `diagnostic:CLASS_BODY_IN_NERVE` | A nerve body contains a `class` definition (nerves must be functions). | none | exception |
| CONFLICTING_PACKAGE_DECLARATION | `diagnostic:CONFLICTING_PACKAGE_DECLARATION` | A file path appears in both `[tool.s0ma].bootstrap_files` and `[tool.s0ma].package_markers`. | none | exception |
| CONSTANT_NAME_MISMATCH | `diagnostic:CONSTANT_NAME_MISMATCH` | A `kind: CONSTANT` cell's declaration name does not match the Python identifier its body assigns to. | none | exception |
| CONSUMES_VIA_DICT_INVALID | `diagnostic:CONSUMES_VIA_DICT_INVALID` | A nerve's `consumes_via_dict:` entry names a `contract:` that resolves to no known cell or `uses:` target, or a `param:` that is not a parameter of the nerve body's outer function. The field declares a real dependency, so both halves must exist: declare the contract, or correct the param name. | none | exception |
| COVERED_BY_EMPTY | `diagnostic:COVERED_BY_EMPTY` | A `covered_by:` field is present with an empty list, or an entry is empty/whitespace — the field is the release gate's external test-evidence credit and an empty claim credits coverage with no auditable evidence. | none | exception |
| CROSS_LAYER_DEPENDENCY | `diagnostic:CROSS_LAYER_DEPENDENCY` | A `uses:` entry targets a module at a layer not in the source layer's reachable set. | none | exception |
| CROSS_MODULE_USES_ASYMMETRY | `diagnostic:CROSS_MODULE_USES_ASYMMETRY` | A module's `uses:` declarations import two or more entries from the same parent module but the bodies only reference a subset. Suggests the unreferenced entries be trimmed from `uses:`. Narrower than `VESTIGIAL_IMPORT`: only fires when ≥2 siblings from the same parent module are declared together. | none | exception |
| DEFERRED_IMPORT_MODULE_SCOPE | `diagnostic:DEFERRED_IMPORT_MODULE_SCOPE` | A `deferred_requires:` name is consumed at a module-scope execution position (cell body, class-scope statement, decorator expression, parameter default, or annotation) — those run at import time, before any injected in-body import could; move the entry back to `requires:` or restructure the consumer into a function body. | none | exception |
| DOC_RENDER_ERROR | `diagnostic:DOC_RENDER_ERROR` | The doc renderer raised `DocRenderError` while emitting a `doc-ref` or `doc-guide`. | none | exception |
| DOC_SOURCE_FORMAT_UNSUPPORTED | `diagnostic:DOC_SOURCE_FORMAT_UNSUPPORTED` | A `doc-ref` requests a `format:` its derived `covers: { source: ... }` does not declare; widen the source's registration or change the format. | none | exception |
| DOES_NOT_EXIST | `diagnostic:DOES_NOT_EXIST` | A `uses:` entry, `depends_on:` target, or qualified `depends_on:` target (`module.declaration`) references a component or module that does not exist in the project. | none | exception |
| DRIFT_DETECTED | `diagnostic:DRIFT_DETECTED` | A re-render of a `doc-ref` or `doc-guide` produces bytes that differ from the on-disk doc artifact. | none | exception |
| DUPLICATE_AXON | `diagnostic:DUPLICATE_AXON` | The same axon relationship is declared twice (inline and standalone, or duplicated derived). | none | exception |
| DUPLICATE_DECLARATION | `diagnostic:DUPLICATE_DECLARATION` | Two top-level declarations share the same name in one module. | none | exception |
| DUPLICATE_INNER_FUNCTION | `diagnostic:DUPLICATE_INNER_FUNCTION` | A body contains two `def` declarations with the same name inside one enclosing function scope (e.g. a SERVICE factory body redefines its inner `def foo()` twice). Python silently shadows the first binding; the returned surface ends up keyed to a function the author did not intend. | none | exception |
| DUPLICATE_PROVIDES_NAME | `diagnostic:DUPLICATE_PROVIDES_NAME` | A nerve's structured `provides:` block lists the same operation name twice — each entry must be unique. | none | exception |
| DUPLICATE_REQUIRES_ENTRY | `diagnostic:DUPLICATE_REQUIRES_ENTRY` | The same import target appears in `deferred_requires:` and another requires-family list of the same module header — module-top import and call-time deferral are different failure-time choices; one target, one list. | none | exception |
| EMBEDDED_FILE_NOT_FOUND | `diagnostic:EMBEDDED_FILE_NOT_FOUND` | A `cell ... content: @file("path")` directive references a missing or unreadable file. | none | exception |
| EMPTY_BLOCK_LIST | `diagnostic:EMPTY_BLOCK_LIST` | A YAML-style block list ('- item' per line) on uses/requires/exports/raises has no items — use the inline form ``field: []`` instead. | none | exception |
| EMPTY_DOC_FILTER | `diagnostic:EMPTY_DOC_FILTER` | A `doc-ref`'s `covers:` filter materialises to zero entities. | none | exception |
| EMPTY_OBSERVES | `diagnostic:EMPTY_OBSERVES` | A ganglion's `observes:` glob pattern resolves to zero matching nerves. | none | exception |
| ENTITY_KIND_MISMATCH | `diagnostic:ENTITY_KIND_MISMATCH` | A `{{kind::name}}` token references an entity of a different kind than declared. | none | exception |
| EXPORTED_HELPER_NOT_FOUND | `diagnostic:EXPORTED_HELPER_NOT_FOUND` | A module's `exports_helpers:` entry names an identifier that is not a `helper` declaration in this module. | none | exception |
| FIELD_NOT_FOUND | `diagnostic:FIELD_NOT_FOUND` | A `{{kind::name.field}}` token references a field that does not exist on the entity. | none | exception |
| FIXTURE_FORMAT_INVALID | `diagnostic:FIXTURE_FORMAT_INVALID` | A non-`.s0ma` fixture file under a configured `test_roots` directory matches a glob declared in `[tool.s0ma].fixtures_format` but fails its declared format (e.g. an invalid line in a `.jsonl` file or a malformed `.yaml` document). | none | exception |
| GENERATED_FILE_DRIFT | `diagnostic:GENERATED_FILE_DRIFT` | A generated .py was hand-edited after transpilation (its embedded `# s0ma-output-hash` no longer matches its content). A build will not overwrite it until the .s0ma source says the same thing: move the changes into the source, or pass --force to discard them. `s0ma check` surfaces this as a warning; `s0ma build` refuses, whether or not the source changed since the last build. | none | exception |
| GRAMMAR_MIGRATION_APPLY_FAILED | `diagnostic:GRAMMAR_MIGRATION_APPLY_FAILED` | An atomic grammar-migration replacement failed and prior replacements were restored. | none | exception |
| GRAMMAR_MIGRATION_CONFLICT | `diagnostic:GRAMMAR_MIGRATION_CONFLICT` | A grammar-migration target changed or ceased to be a regular file after planning. | none | exception |
| GRAMMAR_MIGRATION_OUTPUT_INVALID | `diagnostic:GRAMMAR_MIGRATION_OUTPUT_INVALID` | A proposed grammar migration rewrite failed the parser invariant before apply. | none | exception |
| GRAMMAR_MIGRATION_PARSE_ERROR | `diagnostic:GRAMMAR_MIGRATION_PARSE_ERROR` | Whole-project grammar migration preflight could not parse one authored source. | none | exception |
| GRAMMAR_MIGRATION_ROLLBACK_FAILED | `diagnostic:GRAMMAR_MIGRATION_ROLLBACK_FAILED` | The grammar migrator could not restore one or more files after an apply failure. | none | exception |
| HELPER_NAME_COLLISION | `diagnostic:HELPER_NAME_COLLISION` | Two test bodies in one module define a same-named top-level `def` / `async def`. | none | exception |
| HELPER_PRIVATE_TO_MODULE | `diagnostic:HELPER_PRIVATE_TO_MODULE` | A production module attempts to consume a `helper` declaration from another module via `uses:`. | none | exception |
| HOLLOW_MODEL | `diagnostic:HOLLOW_MODEL` | Verification found zero modeled s0ma modules; roster adoption verifies bytes but cannot answer semantic questions about the code. | none | exception |
| HOST_RUNTIME_UNDECLARED | `diagnostic:HOST_RUNTIME_UNDECLARED` | Generated Python imports s0ma-core and s0ma-dsl, but the project does not declare both host runtime distributions. Naming them in [project].dependencies clears the finding; the environment that runs the application must also have them installed, and `s0ma verify-host` is how that is proved. | none | exception |
| INCONSISTENT_BLOCK_LIST_INDENT | `diagnostic:INCONSISTENT_BLOCK_LIST_INDENT` | Items in a YAML-style block list use different indentation columns; all '- item' lines under a field must share the same indent. | none | exception |
| INTEGRATION_FACTORY_NOT_FOUND | `diagnostic:INTEGRATION_FACTORY_NOT_FOUND` | An `integration` declaration's `factory:` field names a nerve that does not exist in the same module. | none | exception |
| INTEGRATION_FACTORY_NOT_SERVICE | `diagnostic:INTEGRATION_FACTORY_NOT_SERVICE` | An `integration` declaration's `factory:` field names a nerve whose `kind:` is not `SERVICE`. | none | exception |
| INTEGRATION_INVALID_MANIFEST_KEY | `diagnostic:INTEGRATION_INVALID_MANIFEST_KEY` | An `integration` declaration's `manifest:` map carries an invalid key or value (keys must be Python identifiers; values must be JSON-serialisable primitives). | none | exception |
| INTEGRATION_SMOKE_TEST_NOT_FOUND | `diagnostic:INTEGRATION_SMOKE_TEST_NOT_FOUND` | An `integration` declaration's `smoke_test_primary:` field names a target that is neither a nerve in the same module nor a reachable `uses:` entry. | none | exception |
| INTERFACE_ON_NON_ABSTRACT | `diagnostic:INTERFACE_ON_NON_ABSTRACT` | A nerve declares `interface:` but is not marked `abstract: true`. | none | exception |
| INVALID_AXON_RELATION | `diagnostic:INVALID_AXON_RELATION` | An axon uses a relation outside the allowed set (CALLS, READS, CONSTRUCTS, CONFIGURES, PRODUCES, CONSUMES). | none | exception |
| INVALID_DATACLASS_INVARIANT | `diagnostic:INVALID_DATACLASS_INVARIANT` | A MODEL cell's `dataclass_invariants:` entry is not a syntactically valid Python boolean expression (fails `ast.parse(expr, mode="eval")`). Invariants are metadata for downstream introspection only and are not runtime-evaluated by s0ma, but the parser syntax-checks each entry so malformed expressions are caught at check time rather than crashing a downstream consumer that tries to evaluate them. | none | exception |
| INVALID_KIND | `diagnostic:INVALID_KIND` | A declaration's `kind:` value is not valid for its declaration type. | none | exception |
| INVALID_PROJECT_NAME_FOR_BUILD_DIR | `diagnostic:INVALID_PROJECT_NAME_FOR_BUILD_DIR` | The project's `[project].name` cannot be turned into a valid Python identifier for the build dir. | none | exception |
| INVALID_RAISES_TARGET | `diagnostic:INVALID_RAISES_TARGET` | A nerve's `raises:` references a `requires:` import (must be a component-ref). | none | exception |
| INVALID_VERSION | `diagnostic:INVALID_VERSION` | A module's `version:` value is not valid semver. | none | exception |
| LAYER_MISMATCH | `diagnostic:LAYER_MISMATCH` | A component's declared layer does not match its module's layer. | none | exception |
| METADATA_INVALID_KEY | `diagnostic:METADATA_INVALID_KEY` | A `metadata:` key is not identifier-shaped, or the same key is authored twice in one map. | none | exception |
| METADATA_INVALID_VALUE | `diagnostic:METADATA_INVALID_VALUE` | A `metadata:` value is outside the shape set (quoted string \| int \| float \| bool \| list of strings) — nested maps, null entries, unquoted bare tokens, and the inline `metadata: {...}` form are rejected. | none | exception |
| METADATA_RESERVED_KEY | `diagnostic:METADATA_RESERVED_KEY` | A `metadata:` key collides with a reserved registration-metadata key the emitter writes (see `RESERVED_COMPONENT_METADATA_KEYS`); set the owning declaration field instead. | none | exception |
| MISSING_EMBEDDED_EXAMPLE | `diagnostic:MISSING_EMBEDDED_EXAMPLE` | A registered `example` is not embedded in any `doc-guide` (release-mode only). | none | exception |
| MISSING_FIELD | `diagnostic:MISSING_FIELD` | A required field on a declaration is absent. | none | exception |
| MISSING_INTERFACE_METHODS | `diagnostic:MISSING_INTERFACE_METHODS` | A concrete nerve `CONSTRUCTS` an abstract but does not define every method in the abstract's `interface:` list. | none | exception |
| MISSING_PACKAGE | `diagnostic:MISSING_PACKAGE` | A `requires:` entry references a Python module that is not importable in the project's environment. | none | exception |
| MISSING_PROVIDED_FUNCTION | `diagnostic:MISSING_PROVIDED_FUNCTION` | A nerve declares `provides:` names but its body does not define every name as a `def`. | none | exception |
| MISSING_PUBLIC_DOC_REF | `diagnostic:MISSING_PUBLIC_DOC_REF` | A PUBLIC nerve is not covered by any `doc-ref` (release-mode only). | none | exception |
| MISSING_RETURN_KEY | `diagnostic:MISSING_RETURN_KEY` | A nerve declares `returns:` keys but its body's terminal `return {...}` literal omits one or more. | none | exception |
| MISSING_TEST_COVERAGE | `diagnostic:MISSING_TEST_COVERAGE` | A PUBLIC nerve has no `test` declaration covering it (release-mode only). | none | exception |
| MIXED_PROVIDES_FORMS | `diagnostic:MIXED_PROVIDES_FORMS` | A nerve's `provides:` block mixes the flat form ('- name') and the structured form ('- name:' with indented returns:/expects:/guarantees: sub-fields). Pick one form per block. | none | exception |
| MOCK_KEY_MISMATCH | `diagnostic:MOCK_KEY_MISMATCH` | A `test` declaration's `mocks: [<NerveName>]` target's mock-shape dict in the body exposes a key set that does not match the target nerve's `provides:` (missing or extra keys). | none | exception |
| MODULE_DEPENDENCY_CYCLE | `diagnostic:MODULE_DEPENDENCY_CYCLE` | Topological sort detected a cycle in the project module `uses:` graph. | none | exception |
| MODULE_NAME_COLLISION | `diagnostic:MODULE_NAME_COLLISION` | Two source files declare the same `module <name>` in one project. Rename one with a descriptive suffix — `<name>_test`, `<name>_lib`, `<dir>_<name>`. For test-context modules under a `test_roots` directory, `[tool.s0ma].test_module_name_prefix_by_dir = true` prefixes them by their parent directory instead of a hand-rename. | none | exception |
| MODULE_NAME_STEM_MISMATCH | `diagnostic:MODULE_NAME_STEM_MISMATCH` | The source filename's stem does not match the declared `module <name>`. | none | exception |
| MODULE_SHADOWS_STDLIB | `diagnostic:MODULE_SHADOWS_STDLIB` | A module's declared name shadows a Python stdlib module (io, json, csv, …). The stdlib module is already loaded, so the built module cannot be imported by its bare name and cross-module `uses:` resolution fails at runtime — rename the module (and its file) to a non-stdlib name. | none | exception |
| MODULE_SUBSCRIPT | `diagnostic:MODULE_SUBSCRIPT` | A body subscripts a bare `uses: [mod]` module object (`mod["key"]`). A bare uses entry imports the whole module, not a component, so the subscript raises `TypeError: 'module' object is not subscriptable` at runtime — import the symbol with `uses: [mod.symbol]` (emits `from mod import symbol`) instead. | none | exception |
| MUTABLE_DEFAULT | `diagnostic:MUTABLE_DEFAULT` | A body calls `dataclasses.field(default=[...])` or `dataclasses.field(default={...})` with a mutable collection literal as the `default=` argument. Python evaluates `default` once at class-body time and shares the same object across instances. Use `default_factory=list` / `default_factory=dict` instead so each instance gets a fresh collection. | none | exception |
| NAMESPACE_COLLISION | `diagnostic:NAMESPACE_COLLISION` | Two names collide in the same namespace within a module. | none | exception |
| NEW_FILE_ROSTER_ONLY | `diagnostic:NEW_FILE_ROSTER_ONLY` | A Python file first seen after the project's s0ma baseline is only roster-adopted; author it as a canonical component with author_module. | none | exception |
| NOT_EXPORTED | `diagnostic:NOT_EXPORTED` | A `uses:` entry or qualified `depends_on:` target references a component that is not in its module's exports list. | none | exception |
| NO_PAGE_COMPOSER_DECLARED | `diagnostic:NO_PAGE_COMPOSER_DECLARED` | The project configures an `exactly_one_per_page` budget but no nerve carries `is_page_composer: true`. | none | exception |
| OVERLAPPING_DISCOVERY_ROOTS | `diagnostic:OVERLAPPING_DISCOVERY_ROOTS` | The project's `[tool.s0ma].source_roots` and `[tool.s0ma].test_roots` overlap structurally. | none | exception |
| PARSE_DOC_REF_BODY_PROHIBITED | `diagnostic:PARSE_DOC_REF_BODY_PROHIBITED` | A `doc-ref` declaration carries a `---` body (its content is renderer-synthesised). | none | exception |
| PARSE_ERROR | `diagnostic:PARSE_ERROR` | Source file failed to parse as a valid .s0ma module. | none | exception |
| PARSE_GRAMMAR_FORWARD_INCOMPAT | `diagnostic:PARSE_GRAMMAR_FORWARD_INCOMPAT` | A body authors Python 3.12-only grammar (PEP 701 nested-quote f-string, walrus-in-comprehension, or PEP 695 type-parameter / type-alias) while `[project].requires-python` still admits 3.11. | none | exception |
| PLACEHOLDER_NOT_FOUND | `diagnostic:PLACEHOLDER_NOT_FOUND` | A CONSTANT cell's `placeholders:` field declares a marker string (e.g. `__SYSTEM_NAME__`) that is absent from the `content: @file(...)` embedded file's content. | none | exception |
| POSSIBLE_UNRESOLVED_REFERENCE | `diagnostic:POSSIBLE_UNRESOLVED_REFERENCE` | A backtick-quoted identifier-shaped span in a `doc-guide` body is outside `{{...}}` and may be an unresolved reference. | none | exception |
| PROHIBITED_CONSTRUCT | `diagnostic:PROHIBITED_CONSTRUCT` | A body uses `exec()`, `eval()`, `__import__()`, or another prohibited dynamic-execution construct. | none | exception |
| PROSE_RAW_CODE_BLOCK | `diagnostic:PROSE_RAW_CODE_BLOCK` | A `doc-guide` body contains a raw fenced code block (use `{{example::X}}` instead). | none | exception |
| PROVIDES_KEY_MISMATCH | `diagnostic:PROVIDES_KEY_MISMATCH` | A nerve declares `provides: [...]` (flat or structured) and its body's terminal `return {...}` literal-string keys do not exactly match the `provides:` set. | none | exception |
| REQUIRES_DOTTED_LOWERCASE_HINT | `diagnostic:REQUIRES_DOTTED_LOWERCASE_HINT` | A `requires:` entry like `uuid.uuid4` is authored in dotted form with a lowercase last segment, while the body uses the last segment as a bare identifier (e.g. `uuid4()`). Suggests the colon-override shape (e.g. `uuid:uuid4`) so the parser emits `from uuid import uuid4` deterministically. | none | exception |
| SEMANTIC_DERIVED_FIELD_AUTHORED | `diagnostic:SEMANTIC_DERIVED_FIELD_AUTHORED` | Authored source attempted to set a field owned by parsing, resolution, or emission. | none | exception |
| SEMANTIC_NONE_NOT_ALLOWED | `diagnostic:SEMANTIC_NONE_NOT_ALLOWED` | A declaration field used none where the normative field matrix requires a value. | none | exception |
| SEMANTIC_PENDING_DEBT | `diagnostic:SEMANTIC_PENDING_DEBT` | A semantic declaration field is explicitly pending with an authored reason; it earns zero completeness credit and blocks strict/release acceptance. | none | exception |
| SEMANTIC_PENDING_INVALID | `diagnostic:SEMANTIC_PENDING_INVALID` | A pending semantic-state value is malformed; use pending with one quoted reason. | none | exception |
| SEMANTIC_PENDING_NOT_ALLOWED | `diagnostic:SEMANTIC_PENDING_NOT_ALLOWED` | A structural or otherwise non-deferrable declaration field used pending. | none | exception |
| SEMANTIC_PENDING_REASON_EMPTY | `diagnostic:SEMANTIC_PENDING_REASON_EMPTY` | A pending semantic-state value has an empty or whitespace-only reason. | none | exception |
| SEMANTIC_REQUIRED_STATE_OMITTED | `diagnostic:SEMANTIC_REQUIRED_STATE_OMITTED` | A semantic-required declaration field was omitted instead of carrying an explicit value, none, or reasoned pending state. | none | exception |
| SERVES_AS_COLLISION | `diagnostic:SERVES_AS_COLLISION` | Two declarations carry the same `serves_as:` value (served names form one flat namespace, validated per module and per project build). | none | exception |
| SERVES_AS_INVALID | `diagnostic:SERVES_AS_INVALID` | A `serves_as:` value is not identifier-shaped — the served name becomes the emitted callable's `__name__`. | none | exception |
| STALE_GENERATED_CONFTEST | `diagnostic:STALE_GENERATED_CONFTEST` | The project's generated `conftest.py` was emitted by an older s0ma-dsl version and may have diverged from the runtime contract. | none | exception |
| TEMPLATE_SYNTAX_ERROR | `diagnostic:TEMPLATE_SYNTAX_ERROR` | A template expression `{{...}}` or `covers:` filter fails the narrow doc-subsystem grammar. | none | exception |
| TEST_NOT_COLLECTED | `diagnostic:TEST_NOT_COLLECTED` | A `test` declaration's code defines no function named `test...`, so the test runner never runs it, while the declaration still counts as coverage for the parts it names. Name the function `test_<something>`. | none | exception |
| TEST_VISIBILITY_VIOLATION | `diagnostic:TEST_VISIBILITY_VIOLATION` | A production module attempts to `uses:` a `visibility: TEST` component cross-module. | none | exception |
| UNDECLARED_PLACEHOLDER | `diagnostic:UNDECLARED_PLACEHOLDER` | A CONSTANT cell's `content: @file(...)` embedded content contains a placeholder-shaped string matching `__[A-Z][A-Z0-9_]*__` that is not listed in the cell's `placeholders:` field. | none | exception |
| UNKNOWN_FIELD | `diagnostic:UNKNOWN_FIELD` | A declaration carries a field that kind of declaration does not have — usually a misspelt name, or a field that belongs to another kind. s0ma does not read the line, so whatever it was meant to say is not said; correct the name or remove the line. | none | exception |
| UNRECOGNIZED_LINE | `diagnostic:UNRECOGNIZED_LINE` | A line inside a declaration's description is not a field, not part of a block, and not a comment — usually a field indented by the wrong number of spaces. s0ma does not read the line; start a field with exactly four spaces, or remove the line. | none | exception |
| UNREGISTERED_EXAMPLE | `diagnostic:UNREGISTERED_EXAMPLE` | An `examples:` entry or `{{example::X}}` token references an unregistered example. | none | exception |
| UNREGISTERED_SURFACE | `diagnostic:UNREGISTERED_SURFACE` | A caller-discovered declaration or source module is absent from the canonical component registry. | none | exception |
| UNRESOLVED_REFERENCE | `diagnostic:UNRESOLVED_REFERENCE` | A `{{kind::name}}` token references an entity that does not exist in the project registry. | none | exception |
| UNSUPPORTED_IR_SCHEMA_MAJOR | `diagnostic:UNSUPPORTED_IR_SCHEMA_MAJOR` | A canonical IR reader received an unsupported schema major and requires migration and rebuild. | none | exception |
| VESTIGIAL_IMPORT | `diagnostic:VESTIGIAL_IMPORT` | A declared `uses:` or `requires:` entry has no evidence of use in the consuming module's bodies. | none | exception |
| VISIBILITY_MISMATCH | `diagnostic:VISIBILITY_MISMATCH` | A component's visibility does not match its module's exports list. | none | exception |

## The Python interface

9 of the 261. Channel: `python`.

| Name | Id | What it does | Effects | Binding |
| --- | --- | --- | --- | --- |
| s0ma.HASH_ALGORITHM_VERSION | `python:s0ma.HASH_ALGORITHM_VERSION` |  | not declared | exception |
| s0ma.__version__ | `python:s0ma.__version__` |  | not declared | exception |
| s0ma.canonicalize | `python:s0ma.canonicalize` | Produce deterministic bytes for ``value``. | not declared | exception |
| s0ma.content_hash | `python:s0ma.content_hash` | Compute the transitive content hash for a doc registration. | not declared | exception |
| s0ma.initialize | `python:s0ma.initialize` | Initialize the s0ma framework. | not declared | exception |
| s0ma.register_doc_guide | `python:s0ma.register_doc_guide` | Register a ``doc-guide`` declaration in the global registry. | not declared | exception |
| s0ma.register_doc_ref | `python:s0ma.register_doc_ref` | Register a ``doc-ref`` declaration in the global registry. | not declared | exception |
| s0ma.register_example | `python:s0ma.register_example` | Register an ``example`` declaration in the global registry. | not declared | exception |
| s0ma.verify | `python:s0ma.verify` | Run the full verification suite. | not declared | exception |
