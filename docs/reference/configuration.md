# Project settings

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

Everything a project can say about itself in its `pyproject.toml`, under the `[tool.s0ma]` table. This build reads 19 keys; 6 of them accept a closed set of values and nothing else, and 6 carry a structural rule the loader enforces when your project is opened.

The keys are what the project loader actually reads, so this page cannot describe a setting the product has stopped honouring, and a setting it starts honouring appears here at the next build.

Every capability s0ma serves, on every channel, is listed in one place: [what s0ma can do](surfaces-index.md). Every document this repository keeps is on [the documentation map](../README.md).

## How to read this page

**Type** is the type you write in TOML — a string, a list of strings, a table — taken from the words the loader itself uses when it refuses the wrong one. Three keys are validated through helpers that name no type, and those say so rather than carrying a type somebody guessed.

**Default** is what you get when you leave the key out. `None` means the key is simply unset and nothing stands in for it; one key's default is worked out from the project's own name and says so.

**Accepted values** is the closed set the loader validates against: writing anything else is refused when the project is opened. **Checked by** names the rule in the loader that governs the key, and the paragraph under a key with one says what that rule is.

Read from `packages/s0ma-dsl/src/s0ma_dsl/project.py` when the documentation was built.

## Every setting

| Setting | What it is for | Type | Default |
| --- | --- | --- | --- |
| [`adoption_exempt`](#adoption_exempt) | Project-local adoption classifications. | not stated by the loader | `[]` |
| [`attribute_budgets`](#attribute_budgets) | Project-level budgets for ``declares_attributes:`` namespaces. | `table (mapping)` | `{}` |
| [`authoring`](#authoring) | The project's authoring posture, read from ``[tool.s0ma].authoring``. | `string` | `'on'` |
| [`bootstrap_files`](#bootstrap_files) | Absolute paths to plain-Python files that are intentional bootstrap exceptions and should not be flagged by drift / missing-IR checks. | `list of strings` | `[]` |
| [`build_dir`](#build_dir) | Absolute directory for transpiled build artifacts. | `string` | worked out from the project |
| [`env`](#env) | The environment variables the built application reads, keyed by name, each carrying its :class:`RunbookEnvVar` contract (required / fail_fast / default). | not stated by the loader | `{}` |
| [`fixtures_format`](#fixtures_format) | The expected format for non-``.s0ma`` test fixtures. | `table (mapping)` | `None` |
| [`health_command`](#health_command) | The command that checks the running application's health, verbatim as authored under ``[tool.s0ma].health_command`` (e.g. ``"curl -fsS localhost:8080/health"``). | `string` | `None` |
| [`mode`](#mode) | The project's declared strictness mode, read from ``[tool.s0ma].mode``. | `string` | `None` |
| [`package_markers`](#package_markers) | Absolute paths to ``__init__.py`` files that the author explicitly classifies as package markers. | `list of strings` | `[]` |
| [`run_command`](#run_command) | The command that runs the built application, verbatim as authored under ``[tool.s0ma].run_command`` (e.g. ``"uv run myapp"``). | `string` | `None` |
| [`runbook_notes`](#runbook_notes) | Free-form operational notes authored under ``[tool.s0ma].runbook_notes`` — either a single string (one note) or a list of strings (several). | not stated by the loader | `()` |
| [`source_roots`](#source_roots) | Absolute directories holding ``.s0ma`` source modules. | `list of strings` | `['src']` |
| [`state_paths`](#state_paths) | Project-relative paths (verbatim as authored under ``[tool.s0ma].state_paths``) that hold **runtime state** — data the running application produces and owns, NOT derivable from source. | `list of strings` | `[]` |
| [`test_layering`](#test_layering) | Cross-module layer-reachability stance for test-context modules. | `string` | `'strict'` |
| [`test_module_name_prefix_by_dir`](#test_module_name_prefix_by_dir) | Whether to auto-prefix test modules by parent directory when checking for ``MODULE_NAME_COLLISION``. | `bool` | `False` |
| [`test_roots`](#test_roots) | Absolute directories holding ``.s0ma`` test modules. | `list of strings` | `['tests']` |
| [`test_runner`](#test_runner) | The test runner this project uses, named once for the whole project. | `string` | `'pytest'` |
| [`venv_path`](#venv_path) | Project-relative host virtual-environment path for ``verify-host``. | `string` | `None` |

### adoption_exempt

Project-local adoption classifications.

- **Written as** — `[tool.s0ma].adoption_exempt`
- **Type** — not stated by the loader
- **Default** — `[]`
- **Addressed as** — `config:adoption_exempt`

### attribute_budgets

Project-level budgets for ``declares_attributes:`` namespaces.

- **Written as** — `[tool.s0ma].attribute_budgets`
- **Type** — `table (mapping)`
- **Default** — `{}`
- **Accepted values** — `exactly_one_per_page`, `unique_in_project`, `warn_on_duplicate`
- **Addressed as** — `config:attribute_budgets`

### authoring

The project's authoring posture, read from ``[tool.s0ma].authoring``.

- **Written as** — `[tool.s0ma].authoring`
- **Type** — `string`
- **Default** — `'on'`
- **Accepted values** — `off`, `on`
- **Addressed as** — `config:authoring`

### bootstrap_files

Absolute paths to plain-Python files that are intentional bootstrap exceptions and should not be flagged by drift / missing-IR checks.

- **Written as** — `[tool.s0ma].bootstrap_files`
- **Type** — `list of strings`
- **Default** — `[]`
- **Checked by** — `CONFLICTING_PACKAGE_DECLARATION`
- **Addressed as** — `config:bootstrap_files`

A file listed here and under package_markers is refused at load time. The two lists answer different questions and one file cannot answer both.

### build_dir

Absolute directory for transpiled build artifacts.

- **Written as** — `[tool.s0ma].build_dir`
- **Type** — `string`
- **Default** — worked out from the project
- **Checked by** — `INVALID_PROJECT_NAME_FOR_BUILD_DIR`
- **Addressed as** — `config:build_dir`

The last path component has to be a valid Python identifier. It is the import token the built modules are reached through, so a hyphen or a leading digit there produces code that transpiles cleanly and cannot be imported. Left unset, the default is the project name with every non-word character turned into an underscore and _build appended; a name that cannot be repaired that way is refused by name.

### env

The environment variables the built application reads, keyed by name, each carrying its :class:`RunbookEnvVar` contract (required / fail_fast / default).

- **Written as** — `[tool.s0ma].env`
- **Type** — not stated by the loader
- **Default** — `{}`
- **Checked by** — `_RUNBOOK_ENV_FIELDS`
- **Addressed as** — `config:env`

Each variable is its own subtable and may declare only the sub-keys the loader recognises; an unrecognised one is refused so a typo cannot silently drop the contract. The table carries contracts, never live values.

### fixtures_format

The expected format for non-``.s0ma`` test fixtures.

- **Written as** — `[tool.s0ma].fixtures_format`
- **Type** — `table (mapping)`
- **Default** — `None`
- **Accepted values** — `json`, `ndjson`, `yaml`
- **Addressed as** — `config:fixtures_format`

### health_command

The command that checks the running application's health, verbatim as authored under ``[tool.s0ma].health_command`` (e.g. ``"curl -fsS localhost:8080/health"``).

- **Written as** — `[tool.s0ma].health_command`
- **Type** — `string`
- **Default** — `None`
- **Addressed as** — `config:health_command`

### mode

The project's declared strictness mode, read from ``[tool.s0ma].mode``.

- **Written as** — `[tool.s0ma].mode`
- **Type** — `string`
- **Default** — `None`
- **Accepted values** — `dev`, `migration`, `release`, `strict`
- **Addressed as** — `config:mode`

### package_markers

Absolute paths to ``__init__.py`` files that the author explicitly classifies as package markers.

- **Written as** — `[tool.s0ma].package_markers`
- **Type** — `list of strings`
- **Default** — `[]`
- **Checked by** — `CONFLICTING_PACKAGE_DECLARATION`
- **Addressed as** — `config:package_markers`

A file listed here and under bootstrap_files is refused at load time. The two lists answer different questions and one file cannot answer both.

### run_command

The command that runs the built application, verbatim as authored under ``[tool.s0ma].run_command`` (e.g. ``"uv run myapp"``).

- **Written as** — `[tool.s0ma].run_command`
- **Type** — `string`
- **Default** — `None`
- **Addressed as** — `config:run_command`

### runbook_notes

Free-form operational notes authored under ``[tool.s0ma].runbook_notes`` — either a single string (one note) or a list of strings (several).

- **Written as** — `[tool.s0ma].runbook_notes`
- **Type** — not stated by the loader
- **Default** — `()`
- **Addressed as** — `config:runbook_notes`

### source_roots

Absolute directories holding ``.s0ma`` source modules.

- **Written as** — `[tool.s0ma].source_roots`
- **Type** — `list of strings`
- **Default** — `['src']`
- **Checked by** — `_detect_overlapping_roots`
- **Addressed as** — `config:source_roots`

No declared root may contain another, and no two may resolve to one path. Overlapping roots make the same file discovered twice, which surfaces much later as a module colliding with itself.

### state_paths

Project-relative paths (verbatim as authored under ``[tool.s0ma].state_paths``) that hold **runtime state** — data the running application produces and owns, NOT derivable from source.

- **Written as** — `[tool.s0ma].state_paths`
- **Type** — `list of strings`
- **Default** — `[]`
- **Addressed as** — `config:state_paths`

### test_layering

Cross-module layer-reachability stance for test-context modules.

- **Written as** — `[tool.s0ma].test_layering`
- **Type** — `string`
- **Default** — `'strict'`
- **Accepted values** — `permissive`, `strict`
- **Addressed as** — `config:test_layering`

### test_module_name_prefix_by_dir

Whether to auto-prefix test modules by parent directory when checking for ``MODULE_NAME_COLLISION``.

- **Written as** — `[tool.s0ma].test_module_name_prefix_by_dir`
- **Type** — `bool`
- **Default** — `False`
- **Addressed as** — `config:test_module_name_prefix_by_dir`

### test_roots

Absolute directories holding ``.s0ma`` test modules.

- **Written as** — `[tool.s0ma].test_roots`
- **Type** — `list of strings`
- **Default** — `['tests']`
- **Checked by** — `_detect_overlapping_roots`
- **Addressed as** — `config:test_roots`

No declared root may contain another, and no two may resolve to one path. Overlapping roots make the same file discovered twice, which surfaces much later as a module colliding with itself.

### test_runner

The test runner this project uses, named once for the whole project.

- **Written as** — `[tool.s0ma].test_runner`
- **Type** — `string`
- **Default** — `'pytest'`
- **Accepted values** — `pytest`
- **Addressed as** — `config:test_runner`

### venv_path

Project-relative host virtual-environment path for ``verify-host``.

- **Written as** — `[tool.s0ma].venv_path`
- **Type** — `string`
- **Default** — `None`
- **Addressed as** — `config:venv_path`
