# The s0ma command line

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

Every command `s0ma` serves, read off the command-line parser your shell actually meets rather than from a list somebody kept up to date. This build serves 44 commands with 110 options and 33 arguments between them, and 37 of the 44 reach code the model can point at.

A line here is wrong? The place to fix it is the command — its help text, its flags, or what its handler does — and the next build writes this page again.

Every capability s0ma serves, on every channel, is listed in one place: [what s0ma can do](surfaces-index.md). Every document this repository keeps is on [the documentation map](../README.md).

## How to read this page

**What it does** is the command's own help line, quoted. **Touches** is what running it does to the world, in the vocabulary every capability s0ma serves is described with: `read`, `write`, `network`, `subprocess`, `credential`, `approval`, and `none` for one that genuinely does nothing. A command is listed with every word that is true of it.

Under each command, **Default** is what the value is when you do not give one, and an option that takes no value is a switch that is off unless you write it. **Accepted values** is a closed set: anything else is refused. A dash means the fact is not there — no default, or no closed set — rather than that nobody filled it in.

The sentence under each command's facts says two things the parser cannot: which code the command runs, and what that code does to your project. Both were read by a person and written down, which is why they are one paragraph rather than another table.

Read from `python:s0ma_dsl.cli.main.S0maCLI.build_parser` when the documentation was built.

## Every command

| Command | What it does | Touches |
| --- | --- | --- |
| [`s0ma adopt`](#s0ma-adopt) | Retrofit an existing codebase: `adopt scan` reads a tree and plans the conversion, `adopt init` makes it a s0ma project, `adopt draft` converts one module, `adopt baseline` and `adopt verify-parity` prove the conversion kept its promises, `adopt status` says where you are and what to run next; `adopt file <path>` registers one real (non-generated) file into the self-model | `read` |
| [`s0ma adopt baseline`](#s0ma-adopt-baseline) | Record what a module's Python offers today, before you convert it — and long before you delete it | `read`, `write` |
| [`s0ma adopt draft`](#s0ma-adopt-draft) | Turn one Python module into a .s0ma draft. The Python file is read and never changed | `read`, `write` |
| [`s0ma adopt file`](#s0ma-adopt-file) | Record one pre-existing file as interim migration intake; newly-written code starts from intent with author_module | `read`, `write` |
| [`s0ma adopt init`](#s0ma-adopt-init) | Make an existing codebase a s0ma project. Touches no application file | `read`, `write` |
| [`s0ma adopt scan`](#s0ma-adopt-scan) | Read an existing codebase and say what is in it and what to convert first. Writes nothing | `read` |
| [`s0ma adopt status`](#s0ma-adopt-status) | Where this retrofit stands, and the one command to run next. Writes nothing | `read` |
| [`s0ma adopt verify-parity`](#s0ma-adopt-verify-parity) | Compare a built module with the baseline taken from the Python it replaced, and name every difference | `read` |
| [`s0ma build`](#s0ma-build) | Full project build with cross-module resolution | `read`, `write` |
| [`s0ma check`](#s0ma-check) | Validate .s0ma file(s) without generating output | `read`, `write` |
| [`s0ma deferred-surface`](#s0ma-deferred-surface) | List every deferred:-marked declaration in the project (POST-12f). | `read` |
| [`s0ma docs`](#s0ma-docs) | Learn how s0ma works: run `s0ma docs` for the learning map, or list/show/search one topic. Also renders and gates this project's own documentation (render, verify, check-drift, compose, check) | `read` |
| [`s0ma docs check`](#s0ma-docs-check) | Compose the documentation snapshot and byte-compare it against the committed outputs, writing nothing | `read` |
| [`s0ma docs check-drift`](#s0ma-docs-check-drift) | Re-render every doc and byte-compare against committed output files | `read` |
| [`s0ma docs compose`](#s0ma-docs-compose) | Compose the documentation snapshot and write its declared outputs | `read`, `write` |
| [`s0ma docs list`](#s0ma-docs-list) | List every topic in one part of the documentation, or in all five | `read` |
| [`s0ma docs render`](#s0ma-docs-render) | Render every doc-ref/doc-guide to its declared output: path | `read`, `write` |
| [`s0ma docs search`](#s0ma-docs-search) | Find every topic a word or phrase could mean, strongest match first | `read` |
| [`s0ma docs show`](#s0ma-docs-show) | Show one topic in full, by its id or by a name it goes by | `read` |
| [`s0ma docs verify`](#s0ma-docs-verify) | Run doc-subsystem validation layers without rendering | `read` |
| [`s0ma doctor`](#s0ma-doctor) | Environment and project health report: package versions, project detection, build freshness, MCP registration hint. Diagnoses, does not gate — exit 0 with findings; non-zero only when the environment itself is broken. License/update sections are offline placeholders in this version. | `read` |
| [`s0ma examples`](#s0ma-examples) | Run registered .s0ma example declarations | `read` |
| [`s0ma examples run`](#s0ma-examples-run) | Run every example, or one named example | `read`, `subprocess`, `write` |
| [`s0ma feedback`](#s0ma-feedback) | Send feedback about s0ma, and manage the reports you have sent | `approval`, `network`, `read`, `write` |
| [`s0ma feedback delete`](#s0ma-feedback-delete) | Delete one of your feedback reports, or all of them | `approval`, `network`, `read` |
| [`s0ma feedback drafts`](#s0ma-feedback-drafts) | List the reports written here but not yet sent | `read`, `write` |
| [`s0ma feedback enroll`](#s0ma-feedback-enroll) | Connect this machine to your s0ma account so it can send feedback | `credential`, `network`, `read`, `write` |
| [`s0ma feedback list`](#s0ma-feedback-list) | List the feedback reports you have sent | `network`, `read` |
| [`s0ma feedback submit`](#s0ma-feedback-submit) | Show a saved draft again and send it if you approve | `approval`, `network`, `read`, `write` |
| [`s0ma graph`](#s0ma-graph) | Emit dependency graph data for a module or project | `read` |
| [`s0ma inspect`](#s0ma-inspect) | Query the self-model of a compiled module or project | `read` |
| [`s0ma migrate`](#s0ma-migrate) | Plan or apply a versioned source-grammar migration. | `read` |
| [`s0ma migrate grammar`](#s0ma-migrate-grammar) | Materialise explicit semantic state. Dry-run by default; use --apply for an atomic whole-project rewrite. | `read`, `write` |
| [`s0ma migrate-ext`](#s0ma-migrate-ext) | One-shot migration from the pre-2.0.0 letter-o extension family to .s0ma / .s0ma.json / .s0ma.map (build manifest build.s0ma.json): renames files, rewrites the legacy [tool.*] config table to [tool.s0ma], and removes legacy cache directories. Idempotent; refuses to overwrite existing targets. | `read`, `write` |
| [`s0ma migrate-layout`](#s0ma-migrate-layout) | One-shot migration: clean legacy __s0ma_cache__/ and per-layer subdirs from the project's build directory, then run a fresh `s0ma build`. Idempotent. | `read`, `write` |
| [`s0ma new`](#s0ma-new) | Scaffold a new .s0ma file from a template, or initialize a whole project (`s0ma new project <dir>`) | `read`, `write` |
| [`s0ma score`](#s0ma-score) | Self-knowledge score: a single number + a three-faculty breakdown for a s0ma project (text or --format json). | `read` |
| [`s0ma studi0`](#s0ma-studi0) | Serve the studi0 viewer for a built s0ma project on loopback | `network`, `read`, `subprocess` |
| [`s0ma test`](#s0ma-test) | Discover the project, build source + tests, run pytest (args after `--` pass through to pytest) | `read`, `subprocess`, `write` |
| [`s0ma test-conftest`](#s0ma-test-conftest) | Generate a conftest.py that mocks the s0ma runtime for testing | `read`, `write` |
| [`s0ma topo`](#s0ma-topo) | Print the project's topological module import order, one module per line | `read` |
| [`s0ma transpile`](#s0ma-transpile) | Transpile .s0ma file(s) to .py + .s0ma.json + .s0ma.map | `read`, `write` |
| [`s0ma verify`](#s0ma-verify) | Check transpiled files for drift from .s0ma sources (fast, no transpile needed) | `read` |
| [`s0ma verify-host`](#s0ma-verify-host) | Explicitly import built production modules under the host application's Python (executes trusted project code) | `read`, `subprocess` |

### s0ma adopt

Retrofit an existing codebase: `adopt scan` reads a tree and plans the conversion, `adopt init` makes it a s0ma project, `adopt draft` converts one module, `adopt baseline` and `adopt verify-parity` prove the conversion kept its promises, `adopt status` says where you are and what to run next; `adopt file <path>` registers one real (non-generated) file into the self-model

- **Addressed as** — `cli:s0ma/adopt`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`
- **Has subcommands** — the commands under it are the next headings below.

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_adopt, a method of a registered component; the binding names the class because a method is not separately registered. Bare `s0ma adopt` resolves the project and prints the usage line for its subcommands; the project resolution is the read.

It takes no arguments and no options of its own.

#### s0ma adopt baseline

Record what a module's Python offers today, before you convert it — and long before you delete it

- **Addressed as** — `cli:s0ma/adopt/baseline`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_adopt_baseline, a method of a registered component; the binding names the class because a method is not separately registered. It reads the Python files of the modules it was asked about and writes one file: adopt-baseline.s0ma.json at the project root, which records what each of those modules offers its callers today. The Python files are parsed and never imported, and are not changed; recording a module whose file has not changed rewrites the same bytes.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `modules` | any number, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--all` | no value | `false` | — |

#### s0ma adopt draft

Turn one Python module into a .s0ma draft. The Python file is read and never changed

- **Addressed as** — `cli:s0ma/adopt/draft`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_adopt_draft, a method of a registered component; the binding names the class because a method is not separately registered. It reads the project's Python files to work out which module was asked for and what layer to propose, and writes exactly one new file: the .s0ma draft of that module. The Python file it read is parsed and never imported, and is not modified, moved or deleted; an existing draft is never written over without --force, and --dry-run writes nothing.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `module` | one, required | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--dry-run` | no value | `false` | — |
| `--force` | no value | `false` | — |
| `--layer` | a value | — | — |
| `--out` | a value | — | — |

#### s0ma adopt file

Record one pre-existing file as interim migration intake; newly-written code starts from intent with author_module

- **Addressed as** — `cli:s0ma/adopt/file`
- **Running it touches** — `read`, `write`
- **Implemented by** — nothing the model can address

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.adopt_commands.cmd_adopt_file, which nothing registers, so this command reaches no component the model can address. It reads the named file to hash it and writes the adoption record into adopted.s0ma.json at the project root.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `path` | one, required | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--description` | a value | — | — |
| `--format` | a value | `text` | `text`, `json` |

#### s0ma adopt init

Make an existing codebase a s0ma project. Touches no application file

- **Addressed as** — `cli:s0ma/adopt/init`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_adopt_init, a method of a registered component; the binding names the class because a method is not separately registered. It reads every Python file in the tree it is pointed at and then writes exactly two things: the [tool.s0ma] table appended to pyproject.toml, and one marked block in AGENTS.md. No application file is touched, and --dry-run writes nothing.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `path` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--dry-run` | no value | `false` | — |
| `--source-root` | a value | — | — |

#### s0ma adopt scan

Read an existing codebase and say what is in it and what to convert first. Writes nothing

- **Addressed as** — `cli:s0ma/adopt/scan`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_adopt_scan, a method of a registered component; the binding names the class because a method is not separately registered. It reads every Python file in the tree it is pointed at and prints what it found; it writes nothing at all — no report file, no cache, and nothing beside the sources, because it never imports or runs the code it is reading.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `path` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--detail` | a value | — | — |
| `--format` | a value | `text` | `text`, `json` |
| `--source-root` | a value | — | — |

#### s0ma adopt status

Where this retrofit stands, and the one command to run next. Writes nothing

- **Addressed as** — `cli:s0ma/adopt/status`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_adopt_status, a method of a registered component; the binding names the class because a method is not separately registered. It reads the project's configuration, its Python files, the .s0ma drafts beside them, the committed baselines and whatever the build emitted, and prints where the retrofit stands. It writes nothing at all — no report file, no cache — and neither the Python nor the built modules are ever imported or run.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `path` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |

#### s0ma adopt verify-parity

Compare a built module with the baseline taken from the Python it replaced, and name every difference

- **Addressed as** — `cli:s0ma/adopt/verify-parity`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_adopt_verify_parity, a method of a registered component; the binding names the class because a method is not separately registered. It reads the build manifest, the .py files the build emitted and the committed baselines, compares them, and prints what differs. It writes nothing anywhere, and the built module is parsed rather than imported — importing it would run the code the comparison is there to judge.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `modules` | any number, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--all` | no value | `false` | — |
| `--format` | a value | `text` | `text`, `json` |

### s0ma build

Full project build with cross-module resolution

- **Addressed as** — `cli:s0ma/build`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_build, a method of a registered component; the binding names the class because a method is not separately registered. It reads every source root and test root (or the directory it is given), records each module in the manifest with the role of the root its file lives under, and writes the generated .py, .s0ma.json and .s0ma.map files plus the build cache, which --clean removes first.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `project_dir` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--allow-new-errors` | no value | `false` | — |
| `--check` | no value | `false` | — |
| `--clean` | no value | `false` | — |
| `--force` | no value | `false` | — |
| `--force-output-dir` | no value | `false` | — |
| `--format` | a value | `text` | `text`, `json` |
| `--include`, `-I` | a value | `[]` | — |
| `--mode` | a value | — | `migration`, `dev`, `strict`, `release` |
| `--no-cache` | no value | `false` | — |
| `--output-dir`, `-o` | a value | — | — |
| `--quiet`, `-q` | no value | `false` | — |
| `--without-runtime-packages` | no value | `false` | — |

### s0ma check

Validate .s0ma file(s) without generating output

- **Addressed as** — `cli:s0ma/check`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_check, a method of a registered component; the binding names the class because a method is not separately registered. It parses and validates the configured sources and generates no build output, which is the difference between it and build — but it does keep one bookkeeping note, updating .s0ma/check-baseline.json on every run (the [NEW]-marker baseline), which E3's evidence verified by mtime and content.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `source` | any number, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |
| `--include`, `-I` | a value | `[]` | — |
| `--mode` | a value | — | `migration`, `dev`, `strict`, `release` |
| `--quiet`, `-q` | no value | `false` | — |
| `--report-deferred` | no value | `false` | — |

### s0ma deferred-surface

List every deferred:-marked declaration in the project (POST-12f).

- **Addressed as** — `cli:s0ma/deferred-surface`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_deferred_surface, a method of a registered component; the binding names the class because a method is not separately registered. It scans the project's sources for deferred: markers and prints what it found.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `source` | any number, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |

### s0ma docs

Learn how s0ma works: run `s0ma docs` for the learning map, or list/show/search one topic. Also renders and gates this project's own documentation (render, verify, check-drift, compose, check)

- **Addressed as** — `cli:s0ma/docs`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`
- **Has subcommands** — the commands under it are the next headings below.

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_docs, a method of a registered component; the binding names the class because a method is not separately registered. Bare `s0ma docs` reads the composed documentation snapshot and prints the learning map; the snapshot read is the read.

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |

#### s0ma docs check

Compose the documentation snapshot and byte-compare it against the committed outputs, writing nothing

- **Addressed as** — `cli:s0ma/docs/check`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.docs_commands.cmd_docs_check`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.docs_commands.cmd_docs_check, which is itself a registered component. It composes the documentation snapshot and byte-compares it against the committed outputs, writing nothing — that is the whole difference between it and compose.

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |
| `--head-tag` | a value | — | — |
| `--output-dir`, `-o` | a value | — | — |

#### s0ma docs check-drift

Re-render every doc and byte-compare against committed output files

- **Addressed as** — `cli:s0ma/docs/check-drift`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.docs_commands.cmd_docs_check_drift`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.docs_commands.cmd_docs_check_drift, which is itself a registered component. It re-renders every doc declaration in memory and byte-compares the result against the committed files without touching them.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `source` | one, required | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |
| `--mode` | a value | `strict` | `migration`, `dev`, `strict`, `release` |
| `--output-dir`, `-o` | a value | — | — |

#### s0ma docs compose

Compose the documentation snapshot and write its declared outputs

- **Addressed as** — `cli:s0ma/docs/compose`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.docs_commands.cmd_docs_compose`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.docs_commands.cmd_docs_compose, which is itself a registered component. It composes the documentation snapshot from its providers and writes every declared output under the documentation root.

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |
| `--head-tag` | a value | — | — |
| `--output-dir`, `-o` | a value | — | — |

#### s0ma docs list

List every topic in one part of the documentation, or in all five

- **Addressed as** — `cli:s0ma/docs/list`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.docs_commands.cmd_docs_list`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.docs_commands.cmd_docs_list, which is itself a registered component. It reads the composed documentation snapshot and prints every topic of one part of it. It writes nothing and reaches no network.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `category` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |

#### s0ma docs render

Render every doc-ref/doc-guide to its declared output: path

- **Addressed as** — `cli:s0ma/docs/render`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.docs_commands.cmd_docs_render`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.docs_commands.cmd_docs_render, which is itself a registered component. It renders every doc-ref and doc-guide to its declared output: path.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `source` | one, required | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |
| `--mode` | a value | `dev` | `migration`, `dev`, `strict`, `release` |
| `--output-dir`, `-o` | a value | — | — |

#### s0ma docs search

Find every topic a word or phrase could mean, strongest match first

- **Addressed as** — `cli:s0ma/docs/search`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.docs_commands.cmd_docs_search`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.docs_commands.cmd_docs_search, which is itself a registered component. It reads the composed documentation snapshot and prints the topics a question could have meant. It writes nothing and reaches no network.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `query` | one or more | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |

#### s0ma docs show

Show one topic in full, by its id or by a name it goes by

- **Addressed as** — `cli:s0ma/docs/show`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.docs_commands.cmd_docs_show`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.docs_commands.cmd_docs_show, which is itself a registered component. It reads the composed documentation snapshot and prints one topic in full. It writes nothing and reaches no network.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `topic` | one, required | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |

#### s0ma docs verify

Run doc-subsystem validation layers without rendering

- **Addressed as** — `cli:s0ma/docs/verify`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.docs_commands.cmd_docs_verify`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.docs_commands.cmd_docs_verify, which is itself a registered component. It runs the doc-subsystem validation layers over an in-memory render and writes nothing.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `source` | one, required | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |
| `--mode` | a value | `strict` | `migration`, `dev`, `strict`, `release` |
| `--output-dir`, `-o` | a value | — | — |

### s0ma doctor

Environment and project health report: package versions, project detection, build freshness, MCP registration hint. Diagnoses, does not gate — exit 0 with findings; non-zero only when the environment itself is broken. License/update sections are offline placeholders in this version.

- **Addressed as** — `cli:s0ma/doctor`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_doctor, a method of a registered component; the binding names the class because a method is not separately registered. It reports on the environment and the project — installed versions, project detection, build freshness — and changes neither.

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |

### s0ma examples

Run registered .s0ma example declarations

- **Addressed as** — `cli:s0ma/examples`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`
- **Has subcommands** — the commands under it are the next headings below.

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_examples, a method of a registered component; the binding names the class because a method is not separately registered. Bare `s0ma examples` resolves the project and prints the usage line for its one subcommand; the project resolution is the read.

It takes no arguments and no options of its own.

#### s0ma examples run

Run every example, or one named example

- **Addressed as** — `cli:s0ma/examples/run`
- **Running it touches** — `read`, `subprocess`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.examples_commands.cmd_examples_run`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.examples_commands.cmd_examples_run, which is itself a registered component. It parses the named sources and hands each registered example declaration to the example dispatcher, which writes the body to a throwaway directory and runs it in a child interpreter under the --timeout budget — the same act `s0ma test` and the `run_example` tool declare (G7 corrected the earlier in-this-process claim).

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `source` | one, required | — | — |
| `name` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |
| `--mode` | a value | `dev` | `migration`, `dev`, `strict`, `release` |
| `--timeout` | a value | `30` | — |

### s0ma feedback

Send feedback about s0ma, and manage the reports you have sent

- **Addressed as** — `cli:s0ma/feedback`
- **Running it touches** — `approval`, `network`, `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`
- **Has subcommands** — the commands under it are the next headings below.

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_feedback, a method of a registered component; the binding names the class because a method is not separately registered. Bare `s0ma feedback` is the interactive compose: it reads the machine's stored enrolment, saves the report as a local draft, shows it, and sends it to the s0ma service only after you approve it.

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--category`, `-c` | a value | — | — |
| `--impact`, `-i` | a value | — | — |
| `--message`, `-m` | a value | — | — |

#### s0ma feedback delete

Delete one of your feedback reports, or all of them

- **Addressed as** — `cli:s0ma/feedback/delete`
- **Running it touches** — `approval`, `network`, `read`
- **Implemented by** — nothing the model can address

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.feedback_commands.cmd_feedback_delete, which nothing registers, so this command reaches no component the model can address. It asks the service what you have on file and deletes; a report id is its own confirmation, and --all previews the whole list and asks before deleting any of it.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `report_id` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--all` | no value | `false` | — |

#### s0ma feedback drafts

List the reports written here but not yet sent

- **Addressed as** — `cli:s0ma/feedback/drafts`
- **Running it touches** — `read`, `write`
- **Implemented by** — nothing the model can address

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.feedback_commands.cmd_feedback_drafts, which nothing registers, so this command reaches no component the model can address. It lists the unsent reports stored on this machine and removes the ones older than the draft retention window, which is the write.

It takes no arguments and no options of its own.

#### s0ma feedback enroll

Connect this machine to your s0ma account so it can send feedback

- **Addressed as** — `cli:s0ma/feedback/enroll`
- **Running it touches** — `credential`, `network`, `read`, `write`
- **Implemented by** — nothing the model can address

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.feedback_commands.cmd_feedback_enroll, which nothing registers, so this command reaches no component the model can address. It takes your license key — from --key or from S0MA_LICENSE_KEY — exchanges it with the service for an access code, and stores that code at ~/.s0ma/feedback-token.

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--key` | a value | — | — |

#### s0ma feedback list

List the feedback reports you have sent

- **Addressed as** — `cli:s0ma/feedback/list`
- **Running it touches** — `network`, `read`
- **Implemented by** — nothing the model can address

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.feedback_commands.cmd_feedback_list, which nothing registers, so this command reaches no component the model can address. It reads the machine's stored enrolment and asks the service for the reports you have sent.

It takes no arguments and no options of its own.

#### s0ma feedback submit

Show a saved draft again and send it if you approve

- **Addressed as** — `cli:s0ma/feedback/submit`
- **Running it touches** — `approval`, `network`, `read`, `write`
- **Implemented by** — nothing the model can address

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.feedback_commands.cmd_feedback_submit, which nothing registers, so this command reaches no component the model can address. It loads a saved draft, shows it again, sends it only if you approve, and removes the draft once it has been sent.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `draft_id` | one, required | — | — |

### s0ma graph

Emit dependency graph data for a module or project

- **Addressed as** — `cli:s0ma/graph`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_graph, a method of a registered component; the binding names the class because a method is not separately registered. It reads the project's build artifacts and prints the dependency graph in the requested format.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `target` | one, required | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--detail` | a value | `summary` | `summary`, `full` |
| `--format` | a value | `text` | `text`, `json`, `dot` |

### s0ma inspect

Query the self-model of a compiled module or project

- **Addressed as** — `cli:s0ma/inspect`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_inspect, a method of a registered component; the binding names the class because a method is not separately registered. It reads a compiled module's self-model or the whole project's and prints what it asked for.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `target` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--all` | no value | `false` | — |
| `--format` | a value | `text` | `text`, `json` |

### s0ma migrate

Plan or apply a versioned source-grammar migration.

- **Addressed as** — `cli:s0ma/migrate`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`
- **Has subcommands** — the commands under it are the next headings below.

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_migrate, a method of a registered component; the binding names the class because a method is not separately registered. Bare `s0ma migrate` resolves the project and prints the usage line for its one subcommand; the project resolution is the read.

It takes no arguments and no options of its own.

#### s0ma migrate grammar

Materialise explicit semantic state. Dry-run by default; use --apply for an atomic whole-project rewrite.

- **Addressed as** — `cli:s0ma/migrate/grammar`
- **Running it touches** — `read`, `write`
- **Implemented by** — nothing the model can address

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.migrate_grammar.run_migrate_grammar, which nothing registers, so this command reaches no component the model can address. It plans a whole-project grammar migration and prints the plan; with --apply it rewrites the sources the plan names.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `project_dir` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--apply` | no value | `false` | — |

### s0ma migrate-ext

One-shot migration from the pre-2.0.0 letter-o extension family to .s0ma / .s0ma.json / .s0ma.map (build manifest build.s0ma.json): renames files, rewrites the legacy [tool.*] config table to [tool.s0ma], and removes legacy cache directories. Idempotent; refuses to overwrite existing targets.

- **Addressed as** — `cli:s0ma/migrate-ext`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_migrate_ext, a method of a registered component; the binding names the class because a method is not separately registered. It renames the pre-2.0.0 extension family across the project and rewrites what refers to it, unless --dry-run stops it at the plan.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `project_dir` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--dry-run` | no value | `false` | — |
| `--quiet`, `-q` | no value | `false` | — |

### s0ma migrate-layout

One-shot migration: clean legacy __s0ma_cache__/ and per-layer subdirs from the project's build directory, then run a fresh `s0ma build`. Idempotent.

- **Addressed as** — `cli:s0ma/migrate-layout`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_migrate_layout, a method of a registered component; the binding names the class because a method is not separately registered. It removes the legacy cache and per-layer subdirectories from the build directory and then runs a fresh build into it.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `project_dir` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--mode` | a value | — | `migration`, `dev`, `strict`, `release` |
| `--quiet`, `-q` | no value | `false` | — |

### s0ma new

Scaffold a new .s0ma file from a template, or initialize a whole project (`s0ma new project <dir>`)

- **Addressed as** — `cli:s0ma/new`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_new, a method of a registered component; the binding names the class because a method is not separately registered. It writes a scaffolded declaration file, or for `new project` a whole project tree including its pyproject.toml.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `type` | one, required | — | `module`, `nerve`, `cell`, `test`, `project` |
| `name` | one, required | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--default-off` | no value | `false` | — |
| `--format` | a value | `text` | `text`, `json` |
| `--kind` | a value | — | — |
| `--layer` | a value | `DOMAIN` | `DOMAIN`, `APPLICATION`, `INFRASTRUCTURE`, `PRESENTATION` |
| `--mode` | a value | `dev` | `migration`, `dev`, `strict`, `release` |
| `--name` | a value | — | — |
| `--output-dir`, `-o` | a value | `.` | — |
| `--quiet`, `-q` | no value | `false` | — |
| `--template` | a value | — | `service`, `library`, `cli` |

### s0ma score

Self-knowledge score: a single number + a three-faculty breakdown for a s0ma project (text or --format json).

- **Addressed as** — `cli:s0ma/score`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_score, a method of a registered component; the binding names the class because a method is not separately registered. It reads the project and its policy input and prints the self-knowledge score; the gate flags change only the exit code.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `project` | one, optional | `.` | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--adoption-policy` | a value | — | — |
| `--expected-adoption-policy-hash` | a value | — | — |
| `--format` | a value | `text` | `text`, `json` |
| `--gate` | no value | `false` | — |
| `--gate-mode` | a value | — | `migration`, `dev`, `strict`, `release` |
| `--mode` | a value | — | `migration`, `dev`, `strict`, `release` |

### s0ma studi0

Serve the studi0 viewer for a built s0ma project on loopback

- **Addressed as** — `cli:s0ma/studi0`
- **Running it touches** — `network`, `read`, `subprocess`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_studi0, a method of a registered component; the binding names the class because a method is not separately registered. It serves the viewer over a loopback socket for as long as it runs, reading build artifacts only, and opens a browser process unless --no-open says not to.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `project_root` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--no-open` | no value | `false` | — |
| `--port` | a value | `0` | — |

### s0ma test

Discover the project, build source + tests, run pytest (args after `--` pass through to pytest)

- **Addressed as** — `cli:s0ma/test`
- **Running it touches** — `read`, `subprocess`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_test, a method of a registered component; the binding names the class because a method is not separately registered. It builds every source and test root into the build directory and then runs pytest as a subprocess against it.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `test_dir` | one, optional | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--mode` | a value | — | `migration`, `dev`, `strict`, `release` |
| `--quiet`, `-q` | no value | `false` | — |

### s0ma test-conftest

Generate a conftest.py that mocks the s0ma runtime for testing

- **Addressed as** — `cli:s0ma/test-conftest`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_test_conftest, a method of a registered component; the binding names the class because a method is not separately registered. It inspects the project's declarations and writes a conftest.py, refusing to overwrite an existing one without --force.

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--force` | no value | `false` | — |
| `--output`, `-o` | a value | `conftest.py` | — |
| `--project`, `-p` | a value | `.` | — |

### s0ma topo

Print the project's topological module import order, one module per line

- **Addressed as** — `cli:s0ma/topo`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_topo, a method of a registered component; the binding names the class because a method is not separately registered. It parses each module far enough to read its uses: edges and prints the import order.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `project_dir` | one, required | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |
| `--mode` | a value | — | `migration`, `dev`, `strict`, `release` |

### s0ma transpile

Transpile .s0ma file(s) to .py + .s0ma.json + .s0ma.map

- **Addressed as** — `cli:s0ma/transpile`
- **Running it touches** — `read`, `write`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_transpile, a method of a registered component; the binding names the class because a method is not separately registered. It writes the generated .py, .s0ma.json and .s0ma.map for every source it is given, except under --check, which compares against a temporary directory instead.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `source` | one, required | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--check` | no value | `false` | — |
| `--force` | no value | `false` | — |
| `--format` | a value | `text` | `text`, `json` |
| `--mode` | a value | — | `migration`, `dev`, `strict`, `release` |
| `--no-ir` | no value | `false` | — |
| `--no-source-map` | no value | `false` | — |
| `--output-dir`, `-o` | a value | — | — |
| `--quiet`, `-q` | no value | `false` | — |

### s0ma verify

Check transpiled files for drift from .s0ma sources (fast, no transpile needed)

- **Addressed as** — `cli:s0ma/verify`
- **Running it touches** — `read`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_verify, a method of a registered component; the binding names the class because a method is not separately registered. It hashes the transpiled files and compares them against their sources without transpiling anything.

| Argument | How many | Default | Accepted values |
| --- | --- | --- | --- |
| `target` | one, required | — | — |

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--all` | no value | `false` | — |
| `--format` | a value | `text` | `text`, `json` |
| `--verbose`, `-v` | no value | `false` | — |

### s0ma verify-host

Explicitly import built production modules under the host application's Python (executes trusted project code)

- **Addressed as** — `cli:s0ma/verify-host`
- **Running it touches** — `read`, `subprocess`
- **Implemented by** — `component:s0ma_dsl.cli.main.S0maCLI`

The handler this command reaches was transcribed from the dispatch — argparse records none — and is s0ma_dsl.cli.main.S0maCLI._cmd_verify_host, a method of a registered component; the binding names the class because a method is not separately registered. It runs the host Python as a subprocess and has it import the built production modules, which executes the project's own code.

| Option | Takes | Default | Accepted values |
| --- | --- | --- | --- |
| `--format` | a value | `text` | `text`, `json` |
| `--gate-mode` | a value | — | `migration`, `dev`, `strict`, `release` |
| `--module-timeout` | a value | `10.0` | — |
| `--python` | a value | — | — |
| `--timeout` | a value | `60.0` | — |
