# Reports s0ma can make

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

Every report s0ma can make about a project, with what it means and how seriously it is taken. This build registers 114 of them: 101 get more serious as a project tightens its strictness, and 13 are the same whatever mode the project is in.

Each report has an entry of its own further down, so a build that stopped on one can send you straight to it.

A report's code is its permanent name: once a code has shipped it is never renamed and never given to a different report, so a script or an agent can match on it safely. The sentence beside it is written for a person and is improved between releases. [What can change, and how you will know](../stability.md) says so in full.

Every capability s0ma serves, on every channel, is listed in one place: [what s0ma can do](surfaces-index.md). Every document this repository keeps is on [the documentation map](../README.md).

## How to read this page

s0ma reads a project in one of four **modes**, each stricter than the last, and a project chooses which. The same finding can be worth mentioning in the first and worth stopping for in the fourth, so most reports have a severity per mode rather than one severity.

A mode column says `warning` when the report is made and the work goes on, `error` when the work stops, and *not checked* when the report is not made at all in that mode. A dash means the report does not pass through the modes: it is raised the same way in all of them.

Read from `packages/s0ma-dsl/src/s0ma_dsl/config.py` when the documentation was built.

## Severity by mode

| Report | migration | dev | strict | release |
| --- | --- | --- | --- | --- |
| [`ADOPTED_CHURN`](#adopted_churn) | — | — | — | — |
| [`ADOPT_PLACEHOLDER_INTENT`](#adopt_placeholder_intent) | `error` | `error` | `error` | `error` |
| [`ADOPT_UNPLACED_CODE`](#adopt_unplaced_code) | `error` | `error` | `error` | `error` |
| [`AMBIGUOUS_TEST_TARGET`](#ambiguous_test_target) | `error` | `error` | `error` | `error` |
| [`ASSERT_FAILED`](#assert_failed) | `error` | `error` | `error` | `error` |
| [`ASSERT_SYNTAX_ERROR`](#assert_syntax_error) | `error` | `error` | `error` | `error` |
| [`ASSERT_UNEVALUABLE`](#assert_unevaluable) | `error` | `error` | `error` | `error` |
| [`ATTRIBUTE_BUDGET_VIOLATION`](#attribute_budget_violation) | `warning` | `error` | `error` | `error` |
| [`BARE_IMPORT`](#bare_import) | `warning` | `warning` | `error` | `error` |
| [`BUILD_DIR_OVERRIDE_CONFLICT`](#build_dir_override_conflict) | — | — | — | — |
| [`CIRCULAR_DEPENDENCY`](#circular_dependency) | `error` | `error` | `error` | `error` |
| [`CLASS_BODY_IN_NERVE`](#class_body_in_nerve) | `error` | `error` | `error` | `error` |
| [`CONFLICTING_PACKAGE_DECLARATION`](#conflicting_package_declaration) | — | — | — | — |
| [`CONSTANT_NAME_MISMATCH`](#constant_name_mismatch) | `error` | `error` | `error` | `error` |
| [`CONSUMES_VIA_DICT_INVALID`](#consumes_via_dict_invalid) | `error` | `error` | `error` | `error` |
| [`COVERED_BY_EMPTY`](#covered_by_empty) | `error` | `error` | `error` | `error` |
| [`CROSS_LAYER_DEPENDENCY`](#cross_layer_dependency) | `warning` | `warning` | `error` | `error` |
| [`CROSS_MODULE_USES_ASYMMETRY`](#cross_module_uses_asymmetry) | `warning` | `warning` | `error` | `error` |
| [`DEFERRED_IMPORT_MODULE_SCOPE`](#deferred_import_module_scope) | `error` | `error` | `error` | `error` |
| [`DOC_RENDER_ERROR`](#doc_render_error) | `error` | `error` | `error` | `error` |
| [`DOC_SOURCE_FORMAT_UNSUPPORTED`](#doc_source_format_unsupported) | `error` | `error` | `error` | `error` |
| [`DOES_NOT_EXIST`](#does_not_exist) | `error` | `error` | `error` | `error` |
| [`DRIFT_DETECTED`](#drift_detected) | `warning` | `warning` | `error` | `error` |
| [`DUPLICATE_AXON`](#duplicate_axon) | `warning` | `warning` | `error` | `error` |
| [`DUPLICATE_DECLARATION`](#duplicate_declaration) | `error` | `error` | `error` | `error` |
| [`DUPLICATE_INNER_FUNCTION`](#duplicate_inner_function) | `error` | `error` | `error` | `error` |
| [`DUPLICATE_PROVIDES_NAME`](#duplicate_provides_name) | `error` | `error` | `error` | `error` |
| [`DUPLICATE_REQUIRES_ENTRY`](#duplicate_requires_entry) | `error` | `error` | `error` | `error` |
| [`EMBEDDED_FILE_NOT_FOUND`](#embedded_file_not_found) | `error` | `error` | `error` | `error` |
| [`EMPTY_BLOCK_LIST`](#empty_block_list) | `error` | `error` | `error` | `error` |
| [`EMPTY_DOC_FILTER`](#empty_doc_filter) | `warning` | `warning` | `error` | `error` |
| [`EMPTY_OBSERVES`](#empty_observes) | `warning` | `warning` | `error` | `error` |
| [`ENTITY_KIND_MISMATCH`](#entity_kind_mismatch) | `error` | `error` | `error` | `error` |
| [`EXPORTED_HELPER_NOT_FOUND`](#exported_helper_not_found) | `error` | `error` | `error` | `error` |
| [`FIELD_NOT_FOUND`](#field_not_found) | `error` | `error` | `error` | `error` |
| [`FIXTURE_FORMAT_INVALID`](#fixture_format_invalid) | `warning` | `warning` | `error` | `error` |
| [`GENERATED_FILE_DRIFT`](#generated_file_drift) | — | — | — | — |
| [`GRAMMAR_MIGRATION_APPLY_FAILED`](#grammar_migration_apply_failed) | — | — | — | — |
| [`GRAMMAR_MIGRATION_CONFLICT`](#grammar_migration_conflict) | — | — | — | — |
| [`GRAMMAR_MIGRATION_OUTPUT_INVALID`](#grammar_migration_output_invalid) | — | — | — | — |
| [`GRAMMAR_MIGRATION_PARSE_ERROR`](#grammar_migration_parse_error) | — | — | — | — |
| [`GRAMMAR_MIGRATION_ROLLBACK_FAILED`](#grammar_migration_rollback_failed) | — | — | — | — |
| [`HELPER_NAME_COLLISION`](#helper_name_collision) | — | — | — | — |
| [`HELPER_PRIVATE_TO_MODULE`](#helper_private_to_module) | `error` | `error` | `error` | `error` |
| [`HOLLOW_MODEL`](#hollow_model) | — | — | — | — |
| [`HOST_RUNTIME_UNDECLARED`](#host_runtime_undeclared) | `warning` | `warning` | `warning` | `warning` |
| [`INCONSISTENT_BLOCK_LIST_INDENT`](#inconsistent_block_list_indent) | `error` | `error` | `error` | `error` |
| [`INTEGRATION_FACTORY_NOT_FOUND`](#integration_factory_not_found) | `error` | `error` | `error` | `error` |
| [`INTEGRATION_FACTORY_NOT_SERVICE`](#integration_factory_not_service) | `error` | `error` | `error` | `error` |
| [`INTEGRATION_INVALID_MANIFEST_KEY`](#integration_invalid_manifest_key) | `error` | `error` | `error` | `error` |
| [`INTEGRATION_SMOKE_TEST_NOT_FOUND`](#integration_smoke_test_not_found) | `error` | `error` | `error` | `error` |
| [`INTERFACE_ON_NON_ABSTRACT`](#interface_on_non_abstract) | `error` | `error` | `error` | `error` |
| [`INVALID_AXON_RELATION`](#invalid_axon_relation) | `error` | `error` | `error` | `error` |
| [`INVALID_DATACLASS_INVARIANT`](#invalid_dataclass_invariant) | `error` | `error` | `error` | `error` |
| [`INVALID_KIND`](#invalid_kind) | `error` | `error` | `error` | `error` |
| [`INVALID_PROJECT_NAME_FOR_BUILD_DIR`](#invalid_project_name_for_build_dir) | `error` | `error` | `error` | `error` |
| [`INVALID_RAISES_TARGET`](#invalid_raises_target) | `error` | `error` | `error` | `error` |
| [`INVALID_VERSION`](#invalid_version) | `error` | `error` | `error` | `error` |
| [`LAYER_MISMATCH`](#layer_mismatch) | `error` | `error` | `error` | `error` |
| [`METADATA_INVALID_KEY`](#metadata_invalid_key) | `error` | `error` | `error` | `error` |
| [`METADATA_INVALID_VALUE`](#metadata_invalid_value) | `error` | `error` | `error` | `error` |
| [`METADATA_RESERVED_KEY`](#metadata_reserved_key) | `error` | `error` | `error` | `error` |
| [`MISSING_EMBEDDED_EXAMPLE`](#missing_embedded_example) | not checked | not checked | not checked | `error` |
| [`MISSING_FIELD`](#missing_field) | `error` | `error` | `error` | `error` |
| [`MISSING_INTERFACE_METHODS`](#missing_interface_methods) | `error` | `error` | `error` | `error` |
| [`MISSING_PACKAGE`](#missing_package) | `warning` | `warning` | `error` | `error` |
| [`MISSING_PROVIDED_FUNCTION`](#missing_provided_function) | `error` | `error` | `error` | `error` |
| [`MISSING_PUBLIC_DOC_REF`](#missing_public_doc_ref) | not checked | not checked | not checked | `error` |
| [`MISSING_RETURN_KEY`](#missing_return_key) | `error` | `error` | `error` | `error` |
| [`MISSING_TEST_COVERAGE`](#missing_test_coverage) | not checked | not checked | not checked | `error` |
| [`MIXED_PROVIDES_FORMS`](#mixed_provides_forms) | `error` | `error` | `error` | `error` |
| [`MOCK_KEY_MISMATCH`](#mock_key_mismatch) | `warning` | `warning` | `error` | `error` |
| [`MODULE_DEPENDENCY_CYCLE`](#module_dependency_cycle) | `error` | `error` | `error` | `error` |
| [`MODULE_NAME_COLLISION`](#module_name_collision) | `error` | `error` | `error` | `error` |
| [`MODULE_NAME_STEM_MISMATCH`](#module_name_stem_mismatch) | `error` | `error` | `error` | `error` |
| [`MODULE_SHADOWS_STDLIB`](#module_shadows_stdlib) | `warning` | `warning` | `error` | `error` |
| [`MODULE_SUBSCRIPT`](#module_subscript) | `error` | `error` | `error` | `error` |
| [`MUTABLE_DEFAULT`](#mutable_default) | `warning` | `warning` | `error` | `error` |
| [`NAMESPACE_COLLISION`](#namespace_collision) | `error` | `error` | `error` | `error` |
| [`NEW_FILE_ROSTER_ONLY`](#new_file_roster_only) | `warning` | `warning` | `warning` | `warning` |
| [`NOT_EXPORTED`](#not_exported) | `error` | `error` | `error` | `error` |
| [`NO_PAGE_COMPOSER_DECLARED`](#no_page_composer_declared) | `error` | `error` | `error` | `error` |
| [`OVERLAPPING_DISCOVERY_ROOTS`](#overlapping_discovery_roots) | `error` | `error` | `error` | `error` |
| [`PARSE_DOC_REF_BODY_PROHIBITED`](#parse_doc_ref_body_prohibited) | `error` | `error` | `error` | `error` |
| [`PARSE_ERROR`](#parse_error) | `error` | `error` | `error` | `error` |
| [`PARSE_GRAMMAR_FORWARD_INCOMPAT`](#parse_grammar_forward_incompat) | `error` | `error` | `error` | `error` |
| [`PLACEHOLDER_NOT_FOUND`](#placeholder_not_found) | `error` | `error` | `error` | `error` |
| [`POSSIBLE_UNRESOLVED_REFERENCE`](#possible_unresolved_reference) | `warning` | `warning` | `warning` | `error` |
| [`PROHIBITED_CONSTRUCT`](#prohibited_construct) | `warning` | `warning` | `error` | `error` |
| [`PROSE_RAW_CODE_BLOCK`](#prose_raw_code_block) | `error` | `error` | `error` | `error` |
| [`PROVIDES_KEY_MISMATCH`](#provides_key_mismatch) | `warning` | `warning` | `error` | `error` |
| [`REQUIRES_DOTTED_LOWERCASE_HINT`](#requires_dotted_lowercase_hint) | `warning` | `warning` | `warning` | `warning` |
| [`SEMANTIC_DERIVED_FIELD_AUTHORED`](#semantic_derived_field_authored) | `error` | `error` | `error` | `error` |
| [`SEMANTIC_NONE_NOT_ALLOWED`](#semantic_none_not_allowed) | `error` | `error` | `error` | `error` |
| [`SEMANTIC_PENDING_DEBT`](#semantic_pending_debt) | `warning` | `warning` | `error` | `error` |
| [`SEMANTIC_PENDING_INVALID`](#semantic_pending_invalid) | `error` | `error` | `error` | `error` |
| [`SEMANTIC_PENDING_NOT_ALLOWED`](#semantic_pending_not_allowed) | `error` | `error` | `error` | `error` |
| [`SEMANTIC_PENDING_REASON_EMPTY`](#semantic_pending_reason_empty) | `error` | `error` | `error` | `error` |
| [`SEMANTIC_REQUIRED_STATE_OMITTED`](#semantic_required_state_omitted) | `error` | `error` | `error` | `error` |
| [`SERVES_AS_COLLISION`](#serves_as_collision) | `error` | `error` | `error` | `error` |
| [`SERVES_AS_INVALID`](#serves_as_invalid) | `error` | `error` | `error` | `error` |
| [`STALE_GENERATED_CONFTEST`](#stale_generated_conftest) | `error` | `error` | `error` | `error` |
| [`TEMPLATE_SYNTAX_ERROR`](#template_syntax_error) | `error` | `error` | `error` | `error` |
| [`TEST_NOT_COLLECTED`](#test_not_collected) | `warning` | `warning` | `error` | `error` |
| [`TEST_VISIBILITY_VIOLATION`](#test_visibility_violation) | `error` | `error` | `error` | `error` |
| [`UNDECLARED_PLACEHOLDER`](#undeclared_placeholder) | `warning` | `warning` | `error` | `error` |
| [`UNKNOWN_FIELD`](#unknown_field) | `warning` | `warning` | `error` | `error` |
| [`UNRECOGNIZED_LINE`](#unrecognized_line) | `warning` | `warning` | `error` | `error` |
| [`UNREGISTERED_EXAMPLE`](#unregistered_example) | `error` | `error` | `error` | `error` |
| [`UNREGISTERED_SURFACE`](#unregistered_surface) | — | — | — | — |
| [`UNRESOLVED_REFERENCE`](#unresolved_reference) | `error` | `error` | `error` | `error` |
| [`UNSUPPORTED_IR_SCHEMA_MAJOR`](#unsupported_ir_schema_major) | — | — | — | — |
| [`VESTIGIAL_IMPORT`](#vestigial_import) | `warning` | `warning` | `error` | `error` |
| [`VISIBILITY_MISMATCH`](#visibility_mismatch) | `error` | `error` | `error` | `error` |

## Every report

### ADOPTED_CHURN

A roster file has been re-adopted at least three times; componentize it instead of repeatedly refreshing interim migration telemetry.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:ADOPTED_CHURN`

### ADOPT_PLACEHOLDER_INTENT

A field still carries the `FIXME(adopt):` placeholder `s0ma adopt draft` left for a person to replace; write the sentence in your own words, because a draft derives structure and never invents meaning.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:ADOPT_PLACEHOLDER_INTENT`

### ADOPT_UNPLACED_CODE

A module still carries an `adopt: unplaced` quarantine cell holding source text the draft could not place; move the text into the declaration it belongs to, or delete it, and delete the cell.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:ADOPT_UNPLACED_CODE`

### AMBIGUOUS_TEST_TARGET

A bare `tests:` entry resolves to components in two or more modules.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:AMBIGUOUS_TEST_TARGET`

### ASSERT_FAILED

A doc-guide `asserts:` expression evaluated to false.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:ASSERT_FAILED`

### ASSERT_SYNTAX_ERROR

A doc-guide `asserts:` expression falls outside the narrow assert grammar.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:ASSERT_SYNTAX_ERROR`

### ASSERT_UNEVALUABLE

A doc-guide `asserts:` expression references a field or entity that cannot be evaluated.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:ASSERT_UNEVALUABLE`

### ATTRIBUTE_BUDGET_VIOLATION

A nerve's `declares_attributes:` entry violates a project-configured `[tool.s0ma.attribute_budgets]` rule.

- **Severity by mode** — migration `warning`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:ATTRIBUTE_BUDGET_VIOLATION`

### BARE_IMPORT

A nerve or test body contains a bare `import` statement. The fix is one edit with two parts: declare the dependency in the module header — `requires:` for Python imports, `deferred_requires:` for a call-time import, `uses:` for s0ma components — and delete the import line from the body. The transpiler writes the import lines from the declarations.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:BARE_IMPORT`

### BUILD_DIR_OVERRIDE_CONFLICT

`s0ma build --output-dir <path>` was invoked with a path that disagrees with the resolved `[tool.s0ma].build_dir`. Drop `--output-dir` to let the project model resolve the build dir, or pass `--force-output-dir` to proceed with the override (a one-line stderr notice is emitted).

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:BUILD_DIR_OVERRIDE_CONFLICT`

### CIRCULAR_DEPENDENCY

The four-phase resolver's DFS detected a cycle in the declared cross-module architecture edges (`uses:` entries plus qualified `depends_on:` targets).

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:CIRCULAR_DEPENDENCY`

### CLASS_BODY_IN_NERVE

A nerve body contains a `class` definition (nerves must be functions).

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:CLASS_BODY_IN_NERVE`

### CONFLICTING_PACKAGE_DECLARATION

A file path appears in both `[tool.s0ma].bootstrap_files` and `[tool.s0ma].package_markers`.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:CONFLICTING_PACKAGE_DECLARATION`

### CONSTANT_NAME_MISMATCH

A `kind: CONSTANT` cell's declaration name does not match the Python identifier its body assigns to.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:CONSTANT_NAME_MISMATCH`

### CONSUMES_VIA_DICT_INVALID

A nerve's `consumes_via_dict:` entry names a `contract:` that resolves to no known cell or `uses:` target, or a `param:` that is not a parameter of the nerve body's outer function. The field declares a real dependency, so both halves must exist: declare the contract, or correct the param name.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:CONSUMES_VIA_DICT_INVALID`

### COVERED_BY_EMPTY

A `covered_by:` field is present with an empty list, or an entry is empty/whitespace — the field is the release gate's external test-evidence credit and an empty claim credits coverage with no auditable evidence.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:COVERED_BY_EMPTY`

### CROSS_LAYER_DEPENDENCY

A `uses:` entry targets a module at a layer not in the source layer's reachable set.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:CROSS_LAYER_DEPENDENCY`

### CROSS_MODULE_USES_ASYMMETRY

A module's `uses:` declarations import two or more entries from the same parent module but the bodies only reference a subset. Suggests the unreferenced entries be trimmed from `uses:`. Narrower than `VESTIGIAL_IMPORT`: only fires when ≥2 siblings from the same parent module are declared together.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:CROSS_MODULE_USES_ASYMMETRY`

### DEFERRED_IMPORT_MODULE_SCOPE

A `deferred_requires:` name is consumed at a module-scope execution position (cell body, class-scope statement, decorator expression, parameter default, or annotation) — those run at import time, before any injected in-body import could; move the entry back to `requires:` or restructure the consumer into a function body.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:DEFERRED_IMPORT_MODULE_SCOPE`

### DOC_RENDER_ERROR

The doc renderer raised `DocRenderError` while emitting a `doc-ref` or `doc-guide`.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:DOC_RENDER_ERROR`

### DOC_SOURCE_FORMAT_UNSUPPORTED

A `doc-ref` requests a `format:` its derived `covers: { source: ... }` does not declare; widen the source's registration or change the format.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:DOC_SOURCE_FORMAT_UNSUPPORTED`

### DOES_NOT_EXIST

A `uses:` entry, `depends_on:` target, or qualified `depends_on:` target (`module.declaration`) references a component or module that does not exist in the project.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:DOES_NOT_EXIST`

### DRIFT_DETECTED

A re-render of a `doc-ref` or `doc-guide` produces bytes that differ from the on-disk doc artifact.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:DRIFT_DETECTED`

### DUPLICATE_AXON

The same axon relationship is declared twice (inline and standalone, or duplicated derived).

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:DUPLICATE_AXON`

### DUPLICATE_DECLARATION

Two top-level declarations share the same name in one module.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:DUPLICATE_DECLARATION`

### DUPLICATE_INNER_FUNCTION

A body contains two `def` declarations with the same name inside one enclosing function scope (e.g. a SERVICE factory body redefines its inner `def foo()` twice). Python silently shadows the first binding; the returned surface ends up keyed to a function the author did not intend.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:DUPLICATE_INNER_FUNCTION`

### DUPLICATE_PROVIDES_NAME

A nerve's structured `provides:` block lists the same operation name twice — each entry must be unique.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:DUPLICATE_PROVIDES_NAME`

### DUPLICATE_REQUIRES_ENTRY

The same import target appears in `deferred_requires:` and another requires-family list of the same module header — module-top import and call-time deferral are different failure-time choices; one target, one list.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:DUPLICATE_REQUIRES_ENTRY`

### EMBEDDED_FILE_NOT_FOUND

A `cell ... content: @file("path")` directive references a missing or unreadable file.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:EMBEDDED_FILE_NOT_FOUND`

### EMPTY_BLOCK_LIST

A YAML-style block list ('- item' per line) on uses/requires/exports/raises has no items — use the inline form ``field: []`` instead.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:EMPTY_BLOCK_LIST`

### EMPTY_DOC_FILTER

A `doc-ref`'s `covers:` filter materialises to zero entities.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:EMPTY_DOC_FILTER`

### EMPTY_OBSERVES

A ganglion's `observes:` glob pattern resolves to zero matching nerves.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:EMPTY_OBSERVES`

### ENTITY_KIND_MISMATCH

A `{{kind::name}}` token references an entity of a different kind than declared.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:ENTITY_KIND_MISMATCH`

### EXPORTED_HELPER_NOT_FOUND

A module's `exports_helpers:` entry names an identifier that is not a `helper` declaration in this module.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:EXPORTED_HELPER_NOT_FOUND`

### FIELD_NOT_FOUND

A `{{kind::name.field}}` token references a field that does not exist on the entity.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:FIELD_NOT_FOUND`

### FIXTURE_FORMAT_INVALID

A non-`.s0ma` fixture file under a configured `test_roots` directory matches a glob declared in `[tool.s0ma].fixtures_format` but fails its declared format (e.g. an invalid line in a `.jsonl` file or a malformed `.yaml` document).

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:FIXTURE_FORMAT_INVALID`

### GENERATED_FILE_DRIFT

A generated .py was hand-edited after transpilation (its embedded `# s0ma-output-hash` no longer matches its content). A build will not overwrite it until the .s0ma source says the same thing: move the changes into the source, or pass --force to discard them. `s0ma check` surfaces this as a warning; `s0ma build` refuses, whether or not the source changed since the last build.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:GENERATED_FILE_DRIFT`

### GRAMMAR_MIGRATION_APPLY_FAILED

An atomic grammar-migration replacement failed and prior replacements were restored.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:GRAMMAR_MIGRATION_APPLY_FAILED`

### GRAMMAR_MIGRATION_CONFLICT

A grammar-migration target changed or ceased to be a regular file after planning.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:GRAMMAR_MIGRATION_CONFLICT`

### GRAMMAR_MIGRATION_OUTPUT_INVALID

A proposed grammar migration rewrite failed the parser invariant before apply.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:GRAMMAR_MIGRATION_OUTPUT_INVALID`

### GRAMMAR_MIGRATION_PARSE_ERROR

Whole-project grammar migration preflight could not parse one authored source.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:GRAMMAR_MIGRATION_PARSE_ERROR`

### GRAMMAR_MIGRATION_ROLLBACK_FAILED

The grammar migrator could not restore one or more files after an apply failure.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:GRAMMAR_MIGRATION_ROLLBACK_FAILED`

### HELPER_NAME_COLLISION

Two test bodies in one module define a same-named top-level `def` / `async def`.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:HELPER_NAME_COLLISION`

### HELPER_PRIVATE_TO_MODULE

A production module attempts to consume a `helper` declaration from another module via `uses:`.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:HELPER_PRIVATE_TO_MODULE`

### HOLLOW_MODEL

Verification found zero modeled s0ma modules; roster adoption verifies bytes but cannot answer semantic questions about the code.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:HOLLOW_MODEL`

### HOST_RUNTIME_UNDECLARED

Generated Python imports s0ma-core and s0ma-dsl, but the project does not declare both host runtime distributions. Naming them in [project].dependencies clears the finding; the environment that runs the application must also have them installed, and `s0ma verify-host` is how that is proved.

- **Severity by mode** — migration `warning`, dev `warning`, strict `warning`, release `warning`
- **Addressed as** — `diagnostic:HOST_RUNTIME_UNDECLARED`

### INCONSISTENT_BLOCK_LIST_INDENT

Items in a YAML-style block list use different indentation columns; all '- item' lines under a field must share the same indent.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INCONSISTENT_BLOCK_LIST_INDENT`

### INTEGRATION_FACTORY_NOT_FOUND

An `integration` declaration's `factory:` field names a nerve that does not exist in the same module.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INTEGRATION_FACTORY_NOT_FOUND`

### INTEGRATION_FACTORY_NOT_SERVICE

An `integration` declaration's `factory:` field names a nerve whose `kind:` is not `SERVICE`.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INTEGRATION_FACTORY_NOT_SERVICE`

### INTEGRATION_INVALID_MANIFEST_KEY

An `integration` declaration's `manifest:` map carries an invalid key or value (keys must be Python identifiers; values must be JSON-serialisable primitives).

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INTEGRATION_INVALID_MANIFEST_KEY`

### INTEGRATION_SMOKE_TEST_NOT_FOUND

An `integration` declaration's `smoke_test_primary:` field names a target that is neither a nerve in the same module nor a reachable `uses:` entry.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INTEGRATION_SMOKE_TEST_NOT_FOUND`

### INTERFACE_ON_NON_ABSTRACT

A nerve declares `interface:` but is not marked `abstract: true`.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INTERFACE_ON_NON_ABSTRACT`

### INVALID_AXON_RELATION

An axon uses a relation outside the allowed set (CALLS, READS, CONSTRUCTS, CONFIGURES, PRODUCES, CONSUMES).

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INVALID_AXON_RELATION`

### INVALID_DATACLASS_INVARIANT

A MODEL cell's `dataclass_invariants:` entry is not a syntactically valid Python boolean expression (fails `ast.parse(expr, mode="eval")`). Invariants are metadata for downstream introspection only and are not runtime-evaluated by s0ma, but the parser syntax-checks each entry so malformed expressions are caught at check time rather than crashing a downstream consumer that tries to evaluate them.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INVALID_DATACLASS_INVARIANT`

### INVALID_KIND

A declaration's `kind:` value is not valid for its declaration type.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INVALID_KIND`

### INVALID_PROJECT_NAME_FOR_BUILD_DIR

The project's `[project].name` cannot be turned into a valid Python identifier for the build dir.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INVALID_PROJECT_NAME_FOR_BUILD_DIR`

### INVALID_RAISES_TARGET

A nerve's `raises:` references a `requires:` import (must be a component-ref).

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INVALID_RAISES_TARGET`

### INVALID_VERSION

A module's `version:` value is not valid semver.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:INVALID_VERSION`

### LAYER_MISMATCH

A component's declared layer does not match its module's layer.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:LAYER_MISMATCH`

### METADATA_INVALID_KEY

A `metadata:` key is not identifier-shaped, or the same key is authored twice in one map.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:METADATA_INVALID_KEY`

### METADATA_INVALID_VALUE

A `metadata:` value is outside the shape set (quoted string | int | float | bool | list of strings) — nested maps, null entries, unquoted bare tokens, and the inline `metadata: {...}` form are rejected.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:METADATA_INVALID_VALUE`

### METADATA_RESERVED_KEY

A `metadata:` key collides with a reserved registration-metadata key the emitter writes (see `RESERVED_COMPONENT_METADATA_KEYS`); set the owning declaration field instead.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:METADATA_RESERVED_KEY`

### MISSING_EMBEDDED_EXAMPLE

A registered `example` is not embedded in any `doc-guide` (release-mode only).

- **Severity by mode** — migration not checked, dev not checked, strict not checked, release `error`
- **Addressed as** — `diagnostic:MISSING_EMBEDDED_EXAMPLE`

### MISSING_FIELD

A required field on a declaration is absent.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MISSING_FIELD`

### MISSING_INTERFACE_METHODS

A concrete nerve `CONSTRUCTS` an abstract but does not define every method in the abstract's `interface:` list.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MISSING_INTERFACE_METHODS`

### MISSING_PACKAGE

A `requires:` entry references a Python module that is not importable in the project's environment.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MISSING_PACKAGE`

### MISSING_PROVIDED_FUNCTION

A nerve declares `provides:` names but its body does not define every name as a `def`.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MISSING_PROVIDED_FUNCTION`

### MISSING_PUBLIC_DOC_REF

A PUBLIC nerve is not covered by any `doc-ref` (release-mode only).

- **Severity by mode** — migration not checked, dev not checked, strict not checked, release `error`
- **Addressed as** — `diagnostic:MISSING_PUBLIC_DOC_REF`

### MISSING_RETURN_KEY

A nerve declares `returns:` keys but its body's terminal `return {...}` literal omits one or more.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MISSING_RETURN_KEY`

### MISSING_TEST_COVERAGE

A PUBLIC nerve has no `test` declaration covering it (release-mode only).

- **Severity by mode** — migration not checked, dev not checked, strict not checked, release `error`
- **Addressed as** — `diagnostic:MISSING_TEST_COVERAGE`

### MIXED_PROVIDES_FORMS

A nerve's `provides:` block mixes the flat form ('- name') and the structured form ('- name:' with indented returns:/expects:/guarantees: sub-fields). Pick one form per block.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MIXED_PROVIDES_FORMS`

### MOCK_KEY_MISMATCH

A `test` declaration's `mocks: [<NerveName>]` target's mock-shape dict in the body exposes a key set that does not match the target nerve's `provides:` (missing or extra keys).

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MOCK_KEY_MISMATCH`

### MODULE_DEPENDENCY_CYCLE

Topological sort detected a cycle in the project module `uses:` graph.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MODULE_DEPENDENCY_CYCLE`

### MODULE_NAME_COLLISION

Two source files declare the same `module <name>` in one project. Rename one with a descriptive suffix — `<name>_test`, `<name>_lib`, `<dir>_<name>`. For test-context modules under a `test_roots` directory, `[tool.s0ma].test_module_name_prefix_by_dir = true` prefixes them by their parent directory instead of a hand-rename.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MODULE_NAME_COLLISION`

### MODULE_NAME_STEM_MISMATCH

The source filename's stem does not match the declared `module <name>`.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MODULE_NAME_STEM_MISMATCH`

### MODULE_SHADOWS_STDLIB

A module's declared name shadows a Python stdlib module (io, json, csv, …). The stdlib module is already loaded, so the built module cannot be imported by its bare name and cross-module `uses:` resolution fails at runtime — rename the module (and its file) to a non-stdlib name.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MODULE_SHADOWS_STDLIB`

### MODULE_SUBSCRIPT

A body subscripts a bare `uses: [mod]` module object (`mod["key"]`). A bare uses entry imports the whole module, not a component, so the subscript raises `TypeError: 'module' object is not subscriptable` at runtime — import the symbol with `uses: [mod.symbol]` (emits `from mod import symbol`) instead.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MODULE_SUBSCRIPT`

### MUTABLE_DEFAULT

A body calls `dataclasses.field(default=[...])` or `dataclasses.field(default={...})` with a mutable collection literal as the `default=` argument. Python evaluates `default` once at class-body time and shares the same object across instances. Use `default_factory=list` / `default_factory=dict` instead so each instance gets a fresh collection.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:MUTABLE_DEFAULT`

### NAMESPACE_COLLISION

Two names collide in the same namespace within a module.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:NAMESPACE_COLLISION`

### NEW_FILE_ROSTER_ONLY

A Python file first seen after the project's s0ma baseline is only roster-adopted; author it as a canonical component with author_module.

- **Severity by mode** — migration `warning`, dev `warning`, strict `warning`, release `warning`
- **Addressed as** — `diagnostic:NEW_FILE_ROSTER_ONLY`

### NOT_EXPORTED

A `uses:` entry or qualified `depends_on:` target references a component that is not in its module's exports list.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:NOT_EXPORTED`

### NO_PAGE_COMPOSER_DECLARED

The project configures an `exactly_one_per_page` budget but no nerve carries `is_page_composer: true`.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:NO_PAGE_COMPOSER_DECLARED`

### OVERLAPPING_DISCOVERY_ROOTS

The project's `[tool.s0ma].source_roots` and `[tool.s0ma].test_roots` overlap structurally.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:OVERLAPPING_DISCOVERY_ROOTS`

### PARSE_DOC_REF_BODY_PROHIBITED

A `doc-ref` declaration carries a `---` body (its content is renderer-synthesised).

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:PARSE_DOC_REF_BODY_PROHIBITED`

### PARSE_ERROR

Source file failed to parse as a valid .s0ma module.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:PARSE_ERROR`

### PARSE_GRAMMAR_FORWARD_INCOMPAT

A body authors Python 3.12-only grammar (PEP 701 nested-quote f-string, walrus-in-comprehension, or PEP 695 type-parameter / type-alias) while `[project].requires-python` still admits 3.11.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:PARSE_GRAMMAR_FORWARD_INCOMPAT`

### PLACEHOLDER_NOT_FOUND

A CONSTANT cell's `placeholders:` field declares a marker string (e.g. `__SYSTEM_NAME__`) that is absent from the `content: @file(...)` embedded file's content.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:PLACEHOLDER_NOT_FOUND`

### POSSIBLE_UNRESOLVED_REFERENCE

A backtick-quoted identifier-shaped span in a `doc-guide` body is outside `{{...}}` and may be an unresolved reference.

- **Severity by mode** — migration `warning`, dev `warning`, strict `warning`, release `error`
- **Addressed as** — `diagnostic:POSSIBLE_UNRESOLVED_REFERENCE`

### PROHIBITED_CONSTRUCT

A body uses `exec()`, `eval()`, `__import__()`, or another prohibited dynamic-execution construct.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:PROHIBITED_CONSTRUCT`

### PROSE_RAW_CODE_BLOCK

A `doc-guide` body contains a raw fenced code block (use `{{example::X}}` instead).

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:PROSE_RAW_CODE_BLOCK`

### PROVIDES_KEY_MISMATCH

A nerve declares `provides: [...]` (flat or structured) and its body's terminal `return {...}` literal-string keys do not exactly match the `provides:` set.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:PROVIDES_KEY_MISMATCH`

### REQUIRES_DOTTED_LOWERCASE_HINT

A `requires:` entry like `uuid.uuid4` is authored in dotted form with a lowercase last segment, while the body uses the last segment as a bare identifier (e.g. `uuid4()`). Suggests the colon-override shape (e.g. `uuid:uuid4`) so the parser emits `from uuid import uuid4` deterministically.

- **Severity by mode** — migration `warning`, dev `warning`, strict `warning`, release `warning`
- **Addressed as** — `diagnostic:REQUIRES_DOTTED_LOWERCASE_HINT`

### SEMANTIC_DERIVED_FIELD_AUTHORED

Authored source attempted to set a field owned by parsing, resolution, or emission.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:SEMANTIC_DERIVED_FIELD_AUTHORED`

### SEMANTIC_NONE_NOT_ALLOWED

A declaration field used none where the normative field matrix requires a value.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:SEMANTIC_NONE_NOT_ALLOWED`

### SEMANTIC_PENDING_DEBT

A semantic declaration field is explicitly pending with an authored reason; it earns zero completeness credit and blocks strict/release acceptance.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:SEMANTIC_PENDING_DEBT`

### SEMANTIC_PENDING_INVALID

A pending semantic-state value is malformed; use pending with one quoted reason.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:SEMANTIC_PENDING_INVALID`

### SEMANTIC_PENDING_NOT_ALLOWED

A structural or otherwise non-deferrable declaration field used pending.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:SEMANTIC_PENDING_NOT_ALLOWED`

### SEMANTIC_PENDING_REASON_EMPTY

A pending semantic-state value has an empty or whitespace-only reason.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:SEMANTIC_PENDING_REASON_EMPTY`

### SEMANTIC_REQUIRED_STATE_OMITTED

A semantic-required declaration field was omitted instead of carrying an explicit value, none, or reasoned pending state.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:SEMANTIC_REQUIRED_STATE_OMITTED`

### SERVES_AS_COLLISION

Two declarations carry the same `serves_as:` value (served names form one flat namespace, validated per module and per project build).

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:SERVES_AS_COLLISION`

### SERVES_AS_INVALID

A `serves_as:` value is not identifier-shaped — the served name becomes the emitted callable's `__name__`.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:SERVES_AS_INVALID`

### STALE_GENERATED_CONFTEST

The project's generated `conftest.py` was emitted by an older s0ma-dsl version and may have diverged from the runtime contract.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:STALE_GENERATED_CONFTEST`

### TEMPLATE_SYNTAX_ERROR

A template expression `{{...}}` or `covers:` filter fails the narrow doc-subsystem grammar.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:TEMPLATE_SYNTAX_ERROR`

### TEST_NOT_COLLECTED

A `test` declaration's code defines no function named `test...`, so the test runner never runs it, while the declaration still counts as coverage for the parts it names. Name the function `test_<something>`.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:TEST_NOT_COLLECTED`

### TEST_VISIBILITY_VIOLATION

A production module attempts to `uses:` a `visibility: TEST` component cross-module.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:TEST_VISIBILITY_VIOLATION`

### UNDECLARED_PLACEHOLDER

A CONSTANT cell's `content: @file(...)` embedded content contains a placeholder-shaped string matching `__[A-Z][A-Z0-9_]*__` that is not listed in the cell's `placeholders:` field.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:UNDECLARED_PLACEHOLDER`

### UNKNOWN_FIELD

A declaration carries a field that kind of declaration does not have — usually a misspelt name, or a field that belongs to another kind. s0ma does not read the line, so whatever it was meant to say is not said; correct the name or remove the line.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:UNKNOWN_FIELD`

### UNRECOGNIZED_LINE

A line inside a declaration's description is not a field, not part of a block, and not a comment — usually a field indented by the wrong number of spaces. s0ma does not read the line; start a field with exactly four spaces, or remove the line.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:UNRECOGNIZED_LINE`

### UNREGISTERED_EXAMPLE

An `examples:` entry or `{{example::X}}` token references an unregistered example.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:UNREGISTERED_EXAMPLE`

### UNREGISTERED_SURFACE

A caller-discovered declaration or source module is absent from the canonical component registry.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:UNREGISTERED_SURFACE`

### UNRESOLVED_REFERENCE

A `{{kind::name}}` token references an entity that does not exist in the project registry.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:UNRESOLVED_REFERENCE`

### UNSUPPORTED_IR_SCHEMA_MAJOR

A canonical IR reader received an unsupported schema major and requires migration and rebuild.

- **Severity by mode** — not in the table. The strictness mode a project is in does not change how this one is reported.
- **Addressed as** — `diagnostic:UNSUPPORTED_IR_SCHEMA_MAJOR`

### VESTIGIAL_IMPORT

A declared `uses:` or `requires:` entry has no evidence of use in the consuming module's bodies.

- **Severity by mode** — migration `warning`, dev `warning`, strict `error`, release `error`
- **Addressed as** — `diagnostic:VESTIGIAL_IMPORT`

### VISIBILITY_MISMATCH

A component's visibility does not match its module's exports list.

- **Severity by mode** — migration `error`, dev `error`, strict `error`, release `error`
- **Addressed as** — `diagnostic:VISIBILITY_MISMATCH`
