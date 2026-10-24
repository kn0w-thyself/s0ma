---
s0ma_kind: "doc-ref"
name: "CommonErrorsTable"
module: "common_errors"
format: "markdown"
intent: "Derived table of every s0ma-dsl error code, severity by mode, and a one-sentence description. Auto-generated from the canonical error-code registry (`SEVERITY_MATRIX` + `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE` + `ERROR_CODE_DESCRIPTIONS` in `s0ma_dsl.config`)."
schema_version: "3.0.0"
content_hash: "1:529d1e7ccde8654324e334951bbb926d5b264165d3337bbd14746e6c46fa1e19"
---

# CommonErrorsTable

Derived table of every s0ma-dsl error code, severity by mode, and a one-sentence description. Auto-generated from the canonical error-code registry (`SEVERITY_MATRIX` + `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE` + `ERROR_CODE_DESCRIPTIONS` in `s0ma_dsl.config`).

| Code | Migration | Dev | Strict | Release | Description |
|---|---|---|---|---|---|
| `ADOPTED_CHURN` | — | — | — | — | A roster file has been re-adopted at least three times; componentize it instead of repeatedly refreshing interim migration telemetry. |
| `ADOPT_PLACEHOLDER_INTENT` | error | error | error | error | A field still carries the `FIXME(adopt):` placeholder `s0ma adopt draft` left for a person to replace; write the sentence in your own words, because a draft derives structure and never invents meaning. |
| `ADOPT_UNPLACED_CODE` | error | error | error | error | A module still carries an `adopt: unplaced` quarantine cell holding source text the draft could not place; move the text into the declaration it belongs to, or delete it, and delete the cell. |
| `AMBIGUOUS_TEST_TARGET` | error | error | error | error | A bare `tests:` entry resolves to components in two or more modules. |
| `ASSERT_FAILED` | error | error | error | error | A doc-guide `asserts:` expression evaluated to false. |
| `ASSERT_SYNTAX_ERROR` | error | error | error | error | A doc-guide `asserts:` expression falls outside the narrow assert grammar. |
| `ASSERT_UNEVALUABLE` | error | error | error | error | A doc-guide `asserts:` expression references a field or entity that cannot be evaluated. |
| `ATTRIBUTE_BUDGET_VIOLATION` | warning | error | error | error | A nerve's `declares_attributes:` entry violates a project-configured `[tool.s0ma.attribute_budgets]` rule. |
| `BARE_IMPORT` | warning | warning | error | error | A nerve or test body contains a bare `import` statement. The fix is one edit with two parts: declare the dependency in the module header — `requires:` for Python imports, `deferred_requires:` for a call-time import, `uses:` for s0ma components — and delete the import line from the body. The transpiler writes the import lines from the declarations. |
| `BUILD_DIR_OVERRIDE_CONFLICT` | — | — | — | — | `s0ma build --output-dir <path>` was invoked with a path that disagrees with the resolved `[tool.s0ma].build_dir`. Drop `--output-dir` to let the project model resolve the build dir, or pass `--force-output-dir` to proceed with the override (a one-line stderr notice is emitted). |
| `CIRCULAR_DEPENDENCY` | error | error | error | error | The four-phase resolver's DFS detected a cycle in the declared cross-module architecture edges (`uses:` entries plus qualified `depends_on:` targets). |
| `CLASS_BODY_IN_NERVE` | error | error | error | error | A nerve body contains a `class` definition (nerves must be functions). |
| `CONFLICTING_PACKAGE_DECLARATION` | — | — | — | — | A file path appears in both `[tool.s0ma].bootstrap_files` and `[tool.s0ma].package_markers`. |
| `CONSTANT_NAME_MISMATCH` | error | error | error | error | A `kind: CONSTANT` cell's declaration name does not match the Python identifier its body assigns to. |
| `CONSUMES_VIA_DICT_INVALID` | error | error | error | error | A nerve's `consumes_via_dict:` entry names a `contract:` that resolves to no known cell or `uses:` target, or a `param:` that is not a parameter of the nerve body's outer function. The field declares a real dependency, so both halves must exist: declare the contract, or correct the param name. |
| `COVERED_BY_EMPTY` | error | error | error | error | A `covered_by:` field is present with an empty list, or an entry is empty/whitespace — the field is the release gate's external test-evidence credit and an empty claim credits coverage with no auditable evidence. |
| `CROSS_LAYER_DEPENDENCY` | warning | warning | error | error | A `uses:` entry targets a module at a layer not in the source layer's reachable set. |
| `CROSS_MODULE_USES_ASYMMETRY` | warning | warning | error | error | A module's `uses:` declarations import two or more entries from the same parent module but the bodies only reference a subset. Suggests the unreferenced entries be trimmed from `uses:`. Narrower than `VESTIGIAL_IMPORT`: only fires when ≥2 siblings from the same parent module are declared together. |
| `DEFERRED_IMPORT_MODULE_SCOPE` | error | error | error | error | A `deferred_requires:` name is consumed at a module-scope execution position (cell body, class-scope statement, decorator expression, parameter default, or annotation) — those run at import time, before any injected in-body import could; move the entry back to `requires:` or restructure the consumer into a function body. |
| `DOC_RENDER_ERROR` | error | error | error | error | The doc renderer raised `DocRenderError` while emitting a `doc-ref` or `doc-guide`. |
| `DOC_SOURCE_FORMAT_UNSUPPORTED` | error | error | error | error | A `doc-ref` requests a `format:` its derived `covers: { source: ... }` does not declare; widen the source's registration or change the format. |
| `DOES_NOT_EXIST` | error | error | error | error | A `uses:` entry, `depends_on:` target, or qualified `depends_on:` target (`module.declaration`) references a component or module that does not exist in the project. |
| `DRIFT_DETECTED` | warning | warning | error | error | A re-render of a `doc-ref` or `doc-guide` produces bytes that differ from the on-disk doc artifact. |
| `DUPLICATE_AXON` | warning | warning | error | error | The same axon relationship is declared twice (inline and standalone, or duplicated derived). |
| `DUPLICATE_DECLARATION` | error | error | error | error | Two top-level declarations share the same name in one module. |
| `DUPLICATE_INNER_FUNCTION` | error | error | error | error | A body contains two `def` declarations with the same name inside one enclosing function scope (e.g. a SERVICE factory body redefines its inner `def foo()` twice). Python silently shadows the first binding; the returned surface ends up keyed to a function the author did not intend. |
| `DUPLICATE_PROVIDES_NAME` | error | error | error | error | A nerve's structured `provides:` block lists the same operation name twice — each entry must be unique. |
| `DUPLICATE_REQUIRES_ENTRY` | error | error | error | error | The same import target appears in `deferred_requires:` and another requires-family list of the same module header — module-top import and call-time deferral are different failure-time choices; one target, one list. |
| `EMBEDDED_FILE_NOT_FOUND` | error | error | error | error | A `cell ... content: @file("path")` directive references a missing or unreadable file. |
| `EMPTY_BLOCK_LIST` | error | error | error | error | A YAML-style block list ('- item' per line) on uses/requires/exports/raises has no items — use the inline form ``field: []`` instead. |
| `EMPTY_DOC_FILTER` | warning | warning | error | error | A `doc-ref`'s `covers:` filter materialises to zero entities. |
| `EMPTY_OBSERVES` | warning | warning | error | error | A ganglion's `observes:` glob pattern resolves to zero matching nerves. |
| `ENTITY_KIND_MISMATCH` | error | error | error | error | A `{{kind::name}}` token references an entity of a different kind than declared. |
| `EXPORTED_HELPER_NOT_FOUND` | error | error | error | error | A module's `exports_helpers:` entry names an identifier that is not a `helper` declaration in this module. |
| `FIELD_NOT_FOUND` | error | error | error | error | A `{{kind::name.field}}` token references a field that does not exist on the entity. |
| `FIXTURE_FORMAT_INVALID` | warning | warning | error | error | A non-`.s0ma` fixture file under a configured `test_roots` directory matches a glob declared in `[tool.s0ma].fixtures_format` but fails its declared format (e.g. an invalid line in a `.jsonl` file or a malformed `.yaml` document). |
| `GENERATED_FILE_DRIFT` | — | — | — | — | A generated .py was hand-edited after transpilation (its embedded `# s0ma-output-hash` no longer matches its content). A build will not overwrite it until the .s0ma source says the same thing: move the changes into the source, or pass --force to discard them. `s0ma check` surfaces this as a warning; `s0ma build` refuses, whether or not the source changed since the last build. |
| `GRAMMAR_MIGRATION_APPLY_FAILED` | — | — | — | — | An atomic grammar-migration replacement failed and prior replacements were restored. |
| `GRAMMAR_MIGRATION_CONFLICT` | — | — | — | — | A grammar-migration target changed or ceased to be a regular file after planning. |
| `GRAMMAR_MIGRATION_OUTPUT_INVALID` | — | — | — | — | A proposed grammar migration rewrite failed the parser invariant before apply. |
| `GRAMMAR_MIGRATION_PARSE_ERROR` | — | — | — | — | Whole-project grammar migration preflight could not parse one authored source. |
| `GRAMMAR_MIGRATION_ROLLBACK_FAILED` | — | — | — | — | The grammar migrator could not restore one or more files after an apply failure. |
| `HELPER_NAME_COLLISION` | — | — | — | — | Two test bodies in one module define a same-named top-level `def` / `async def`. |
| `HELPER_PRIVATE_TO_MODULE` | error | error | error | error | A production module attempts to consume a `helper` declaration from another module via `uses:`. |
| `HOLLOW_MODEL` | — | — | — | — | Verification found zero modeled s0ma modules; roster adoption verifies bytes but cannot answer semantic questions about the code. |
| `HOST_RUNTIME_UNDECLARED` | warning | warning | warning | warning | Generated Python imports s0ma-core and s0ma-dsl, but the project does not declare both host runtime distributions. Naming them in [project].dependencies clears the finding; the environment that runs the application must also have them installed, and `s0ma verify-host` is how that is proved. |
| `INCONSISTENT_BLOCK_LIST_INDENT` | error | error | error | error | Items in a YAML-style block list use different indentation columns; all '- item' lines under a field must share the same indent. |
| `INTEGRATION_FACTORY_NOT_FOUND` | error | error | error | error | An `integration` declaration's `factory:` field names a nerve that does not exist in the same module. |
| `INTEGRATION_FACTORY_NOT_SERVICE` | error | error | error | error | An `integration` declaration's `factory:` field names a nerve whose `kind:` is not `SERVICE`. |
| `INTEGRATION_INVALID_MANIFEST_KEY` | error | error | error | error | An `integration` declaration's `manifest:` map carries an invalid key or value (keys must be Python identifiers; values must be JSON-serialisable primitives). |
| `INTEGRATION_SMOKE_TEST_NOT_FOUND` | error | error | error | error | An `integration` declaration's `smoke_test_primary:` field names a target that is neither a nerve in the same module nor a reachable `uses:` entry. |
| `INTERFACE_ON_NON_ABSTRACT` | error | error | error | error | A nerve declares `interface:` but is not marked `abstract: true`. |
| `INVALID_AXON_RELATION` | error | error | error | error | An axon uses a relation outside the allowed set (CALLS, READS, CONSTRUCTS, CONFIGURES, PRODUCES, CONSUMES). |
| `INVALID_DATACLASS_INVARIANT` | error | error | error | error | A MODEL cell's `dataclass_invariants:` entry is not a syntactically valid Python boolean expression (fails `ast.parse(expr, mode="eval")`). Invariants are metadata for downstream introspection only and are not runtime-evaluated by s0ma, but the parser syntax-checks each entry so malformed expressions are caught at check time rather than crashing a downstream consumer that tries to evaluate them. |
| `INVALID_KIND` | error | error | error | error | A declaration's `kind:` value is not valid for its declaration type. |
| `INVALID_PROJECT_NAME_FOR_BUILD_DIR` | error | error | error | error | The project's `[project].name` cannot be turned into a valid Python identifier for the build dir. |
| `INVALID_RAISES_TARGET` | error | error | error | error | A nerve's `raises:` references a `requires:` import (must be a component-ref). |
| `INVALID_VERSION` | error | error | error | error | A module's `version:` value is not valid semver. |
| `LAYER_MISMATCH` | error | error | error | error | A component's declared layer does not match its module's layer. |
| `METADATA_INVALID_KEY` | error | error | error | error | A `metadata:` key is not identifier-shaped, or the same key is authored twice in one map. |
| `METADATA_INVALID_VALUE` | error | error | error | error | A `metadata:` value is outside the shape set (quoted string \| int \| float \| bool \| list of strings) — nested maps, null entries, unquoted bare tokens, and the inline `metadata: {...}` form are rejected. |
| `METADATA_RESERVED_KEY` | error | error | error | error | A `metadata:` key collides with a reserved registration-metadata key the emitter writes (see `RESERVED_COMPONENT_METADATA_KEYS`); set the owning declaration field instead. |
| `MISSING_EMBEDDED_EXAMPLE` | — | — | — | error | A registered `example` is not embedded in any `doc-guide` (release-mode only). |
| `MISSING_FIELD` | error | error | error | error | A required field on a declaration is absent. |
| `MISSING_INTERFACE_METHODS` | error | error | error | error | A concrete nerve `CONSTRUCTS` an abstract but does not define every method in the abstract's `interface:` list. |
| `MISSING_PACKAGE` | warning | warning | error | error | A `requires:` entry references a Python module that is not importable in the project's environment. |
| `MISSING_PROVIDED_FUNCTION` | error | error | error | error | A nerve declares `provides:` names but its body does not define every name as a `def`. |
| `MISSING_PUBLIC_DOC_REF` | — | — | — | error | A PUBLIC nerve is not covered by any `doc-ref` (release-mode only). |
| `MISSING_RETURN_KEY` | error | error | error | error | A nerve declares `returns:` keys but its body's terminal `return {...}` literal omits one or more. |
| `MISSING_TEST_COVERAGE` | — | — | — | error | A PUBLIC nerve has no `test` declaration covering it (release-mode only). |
| `MIXED_PROVIDES_FORMS` | error | error | error | error | A nerve's `provides:` block mixes the flat form ('- name') and the structured form ('- name:' with indented returns:/expects:/guarantees: sub-fields). Pick one form per block. |
| `MOCK_KEY_MISMATCH` | warning | warning | error | error | A `test` declaration's `mocks: [<NerveName>]` target's mock-shape dict in the body exposes a key set that does not match the target nerve's `provides:` (missing or extra keys). |
| `MODULE_DEPENDENCY_CYCLE` | error | error | error | error | Topological sort detected a cycle in the project module `uses:` graph. |
| `MODULE_NAME_COLLISION` | error | error | error | error | Two source files declare the same `module <name>` in one project. Rename one with a descriptive suffix — `<name>_test`, `<name>_lib`, `<dir>_<name>`. For test-context modules under a `test_roots` directory, `[tool.s0ma].test_module_name_prefix_by_dir = true` prefixes them by their parent directory instead of a hand-rename. |
| `MODULE_NAME_STEM_MISMATCH` | error | error | error | error | The source filename's stem does not match the declared `module <name>`. |
| `MODULE_OUTSIDE_PROJECT_ROOTS` | warning | warning | warning | warning | A built module's file lives under none of the project's `[tool.s0ma].source_roots` or `test_roots`, so the build recorded it with role `source` by default. Add its directory to one of the two lists so the build can record which it is, or move the file under a configured root. |
| `MODULE_SHADOWS_STDLIB` | warning | warning | error | error | A module's declared name shadows a Python stdlib module (io, json, csv, …). The stdlib module is already loaded, so the built module cannot be imported by its bare name and cross-module `uses:` resolution fails at runtime — rename the module (and its file) to a non-stdlib name. |
| `MODULE_SUBSCRIPT` | error | error | error | error | A body subscripts a bare `uses: [mod]` module object (`mod["key"]`). A bare uses entry imports the whole module, not a component, so the subscript raises `TypeError: 'module' object is not subscriptable` at runtime — import the symbol with `uses: [mod.symbol]` (emits `from mod import symbol`) instead. |
| `MUTABLE_DEFAULT` | warning | warning | error | error | A body calls `dataclasses.field(default=[...])` or `dataclasses.field(default={...})` with a mutable collection literal as the `default=` argument. Python evaluates `default` once at class-body time and shares the same object across instances. Use `default_factory=list` / `default_factory=dict` instead so each instance gets a fresh collection. |
| `NAMESPACE_COLLISION` | error | error | error | error | Two names collide in the same namespace within a module. |
| `NEW_FILE_ROSTER_ONLY` | warning | warning | warning | warning | A Python file first seen after the project's s0ma baseline is only roster-adopted; author it as a canonical component with author_module. |
| `NOT_EXPORTED` | error | error | error | error | A `uses:` entry or qualified `depends_on:` target references a component that is not in its module's exports list. |
| `NO_PAGE_COMPOSER_DECLARED` | error | error | error | error | The project configures an `exactly_one_per_page` budget but no nerve carries `is_page_composer: true`. |
| `OVERLAPPING_DISCOVERY_ROOTS` | error | error | error | error | The project's `[tool.s0ma].source_roots` and `[tool.s0ma].test_roots` overlap structurally. |
| `PARSE_DOC_REF_BODY_PROHIBITED` | error | error | error | error | A `doc-ref` declaration carries a `---` body (its content is renderer-synthesised). |
| `PARSE_ERROR` | error | error | error | error | Source file failed to parse as a valid .s0ma module. |
| `PARSE_GRAMMAR_FORWARD_INCOMPAT` | error | error | error | error | A body authors Python 3.12-only grammar (PEP 701 nested-quote f-string, walrus-in-comprehension, or PEP 695 type-parameter / type-alias) while `[project].requires-python` still admits 3.11. |
| `PLACEHOLDER_NOT_FOUND` | error | error | error | error | A CONSTANT cell's `placeholders:` field declares a marker string (e.g. `__SYSTEM_NAME__`) that is absent from the `content: @file(...)` embedded file's content. |
| `POSSIBLE_UNRESOLVED_REFERENCE` | warning | warning | warning | error | A backtick-quoted identifier-shaped span in a `doc-guide` body is outside `{{...}}` and may be an unresolved reference. |
| `PROHIBITED_CONSTRUCT` | warning | warning | error | error | A body uses `exec()`, `eval()`, `__import__()`, or another prohibited dynamic-execution construct. |
| `PROSE_RAW_CODE_BLOCK` | error | error | error | error | A `doc-guide` body contains a raw fenced code block (use `{{example::X}}` instead). |
| `PROVIDES_KEY_MISMATCH` | warning | warning | error | error | A nerve declares `provides: [...]` (flat or structured) and its body's terminal `return {...}` literal-string keys do not exactly match the `provides:` set. |
| `REQUIRES_DOTTED_LOWERCASE_HINT` | warning | warning | warning | warning | A `requires:` entry like `uuid.uuid4` is authored in dotted form with a lowercase last segment, while the body uses the last segment as a bare identifier (e.g. `uuid4()`). Suggests the colon-override shape (e.g. `uuid:uuid4`) so the parser emits `from uuid import uuid4` deterministically. |
| `SEMANTIC_DERIVED_FIELD_AUTHORED` | error | error | error | error | Authored source attempted to set a field owned by parsing, resolution, or emission. |
| `SEMANTIC_NONE_NOT_ALLOWED` | error | error | error | error | A declaration field used none where the normative field matrix requires a value. |
| `SEMANTIC_PENDING_DEBT` | warning | warning | error | error | A semantic declaration field is explicitly pending with an authored reason; it earns zero completeness credit and blocks strict/release acceptance. |
| `SEMANTIC_PENDING_INVALID` | error | error | error | error | A pending semantic-state value is malformed; use pending with one quoted reason. |
| `SEMANTIC_PENDING_NOT_ALLOWED` | error | error | error | error | A structural or otherwise non-deferrable declaration field used pending. |
| `SEMANTIC_PENDING_REASON_EMPTY` | error | error | error | error | A pending semantic-state value has an empty or whitespace-only reason. |
| `SEMANTIC_REQUIRED_STATE_OMITTED` | error | error | error | error | A semantic-required declaration field was omitted instead of carrying an explicit value, none, or reasoned pending state. |
| `SERVES_AS_COLLISION` | error | error | error | error | Two declarations carry the same `serves_as:` value (served names form one flat namespace, validated per module and per project build). |
| `SERVES_AS_INVALID` | error | error | error | error | A `serves_as:` value is not identifier-shaped — the served name becomes the emitted callable's `__name__`. |
| `STALE_GENERATED_CONFTEST` | error | error | error | error | The project's generated `conftest.py` was emitted by an older s0ma-dsl version and may have diverged from the runtime contract. |
| `TEMPLATE_SYNTAX_ERROR` | error | error | error | error | A template expression `{{...}}` or `covers:` filter fails the narrow doc-subsystem grammar. |
| `TEST_NOT_COLLECTED` | warning | warning | error | error | A `test` declaration's code defines no function named `test...`, so the test runner never runs it, while the declaration still counts as coverage for the parts it names. Name the function `test_<something>`. |
| `TEST_VISIBILITY_VIOLATION` | error | error | error | error | A production module attempts to `uses:` a `visibility: TEST` component cross-module. |
| `UNDECLARED_PLACEHOLDER` | warning | warning | error | error | A CONSTANT cell's `content: @file(...)` embedded content contains a placeholder-shaped string matching `__[A-Z][A-Z0-9_]*__` that is not listed in the cell's `placeholders:` field. |
| `UNKNOWN_FIELD` | warning | warning | error | error | A declaration carries a field that kind of declaration does not have — usually a misspelt name, or a field that belongs to another kind. s0ma does not read the line, so whatever it was meant to say is not said; correct the name or remove the line. |
| `UNRECOGNIZED_LINE` | warning | warning | error | error | A line inside a declaration's description is not a field, not part of a block, and not a comment — usually a field indented by the wrong number of spaces. s0ma does not read the line; start a field with exactly four spaces, or remove the line. |
| `UNREGISTERED_EXAMPLE` | error | error | error | error | An `examples:` entry or `{{example::X}}` token references an unregistered example. |
| `UNREGISTERED_SURFACE` | — | — | — | — | A caller-discovered declaration or source module is absent from the canonical component registry. |
| `UNRESOLVED_REFERENCE` | error | error | error | error | A `{{kind::name}}` token references an entity that does not exist in the project registry. |
| `UNSUPPORTED_IR_SCHEMA_MAJOR` | — | — | — | — | A canonical IR reader received an unsupported schema major and requires migration and rebuild. |
| `VESTIGIAL_IMPORT` | warning | warning | error | error | A declared `uses:` or `requires:` entry has no evidence of use in the consuming module's bodies. |
| `VISIBILITY_MISMATCH` | error | error | error | error | A component's visibility does not match its module's exports list. |
