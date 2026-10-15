# s0ma-mcp

The **s0ma authoring MCP server** — exposes the s0ma DSL toolchain and the agent-alignment guides to coding agents over the [Model Context Protocol](https://modelcontextprotocol.io) (stdio transport, FastMCP). This is the agent-interface layer of the s0ma platform (PRD §7.3): an agent connects, reads the system's guides, then drives the scaffold → check → transpile/build loop entirely through tools.

It is also the **flagship `.s0ma` application** (FR-MCP-11): every tool, resource, and prompt this server exposes is authored in the s0ma DSL itself, built at the DSL's full `release` gate, and served from the self-model registry that build populates. When you want to see what a production s0ma project looks like, read this package's `s0ma_src/`.

## Where it sits

Four distributions ship together at one version, and dependencies only ever point down the stack (PRD INV-6):

**`s0ma-mcp`** · [`s0ma-studi0`](../s0ma-studi0) → [`s0ma-dsl`](../s0ma-dsl) → [`s0ma-core`](../s0ma-core)

Installing this one package transitively provides the full toolchain (`s0ma-dsl` and `s0ma-core[mcp]`). `s0ma-mcp` is **Apache-2.0**, and so are `s0ma-core`, `s0ma-dsl` and `s0ma-studi0`. What each distribution contains, and the license each one declares, is in [the distributions s0ma ships](../../docs/reference/packages.md).

## Install and register

s0ma is not on PyPI yet: all four packages are published there from the first release cut of the public repository, and until that lands the way in is the repository itself. That route is written down once, in the [root README's "Install" section](../../README.md#install) — working inside a checkout, or building the wheels and installing them into a project of your own — and [getting started](../../docs/getting-started.md#1-create-a-real-project) is the journey to walk once the `s0ma` command runs.

To register the server with Claude Code — `claude mcp add s0ma -- s0ma-mcp` where the wheel is installed, or `claude mcp add s0ma -- uv run s0ma-mcp` from a checkout of this repository. Any other client takes the same command as JSON:

```json
{
  "mcpServers": {
    "s0ma": {
      "command": "s0ma-mcp",
      "args": []
    }
  }
}
```

The server name is `s0ma-authoring`. [Authoring through the agent's own tool channel](../../docs/guides/mcp-authoring.md) walks the loop an agent then follows, call by call.

## Served surface

Every tool body returns `s0ma-tool-result@1`: required `schema`, `ok`, and `next_actions` fields plus tool-specific data. Every action names a live served tool and carries arguments validated against that tool's input schema. Schema-invalid calls remain honest MCP protocol validation errors; failures reached inside a tool body return structured correction actions and the compact live `tool_map`, never a raw traceback. Tools operate on explicit `project_root` arguments passed by the client and never write outside the given project tree.

<!-- BEGIN GENERATED MCP SURFACE -->
The tables below are generated from the served-surface snapshot. Do not edit them by hand.

### Tools

| Tool | Inputs | Job to be done |
|---|---|---|
| `adopt_file` | `description` (required), `path` (required), `project_root` (required) | When migrating old Python, record it as interim roster debt. |
| `build_project` | `allow_new_errors`, `clean`, `force`, `mode`, `project_root` (required) | After check is clean, build the complete configured project. |
| `check` | `adoption_policy`, `expected_adoption_policy_hash`, `gate_mode`, `mode`, `path`, `project_root` | After editing intent or code, validate before building. |
| `describe_server` | None | When you do not know which s0ma surface fits, ask the server. |
| `init_project` | `mode`, `project_root` (required) | When project_status says false, add the canonical project table. |
| `inspect_module` | `module`, `project_root` (required) | Before grepping for where X is handled, inspect the self-model. |
| `learn_s0ma` | `topic` (required) | Ask s0ma one question about s0ma, and get a short answer back. |
| `migrate_ext` | `dry_run`, `project_root` (required) | When legacy extension names remain, preview and apply their migration. |
| `prepare_feedback` | `actual`, `category` (required), `details`, `diagnostic_codes`, `expected`, `impact` (required), `reproduction`, `summary` (required), `surface_kind`, `surface_name` | Write up feedback about s0ma for the user to review — read-only. |
| `project_status` | `project_root` (required) | When landing in a tree or diagnosing it, orient in one call. |
| `run_example` | `example_name`, `project_root` (required), `source_path`, `timeout_seconds` | When documentation claims behavior, run its executable example. |
| `scaffold_module` | `kind`, `layer`, `module_name` (required), `output_dir`, `project_root` (required) | When starting new behavior, create a valid intent-first component. |
| `submit_feedback` | `contact_ok`, `envelope` (required), `payload_sha256` (required) | Ask the user to approve this exact feedback data, then send it. |
| `transpile` | `mode`, `output_dir`, `project_root`, `source_path` (required) | When iterating on one source, emit its Python, IR, and source map. |
| `verify_host` | `gate_mode`, `module_timeout_seconds`, `project_root` (required), `python`, `timeout_seconds` | After static checks pass, prove imports in the app's real Python. |

### Tool annotations

| Tool | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` |
|---|---:|---:|---:|---:|
| `adopt_file` | false | false | false | false |
| `build_project` | false | false | true | false |
| `check` | true | — | — | false |
| `describe_server` | true | — | — | false |
| `init_project` | false | false | true | false |
| `inspect_module` | true | — | — | false |
| `learn_s0ma` | true | — | true | false |
| `migrate_ext` | false | false | true | false |
| `prepare_feedback` | true | — | — | false |
| `project_status` | true | — | — | false |
| `run_example` | false | true | false | false |
| `scaffold_module` | false | false | true | false |
| `submit_feedback` | false | false | true | true |
| `transpile` | false | false | true | false |
| `verify_host` | false | true | false | true |

### Resources

| URI | MIME type | Content |
|---|---|---|
| `s0ma://docs/concepts` | `text/markdown` | Every s0ma concept, one line each. |
| `s0ma://docs/index` | `text/markdown` | What s0ma can be asked about, and how to ask. |
| `s0ma://docs/journeys` | `text/markdown` | Every worked path through s0ma, step by step. |
| `s0ma://guide/errors` | `text/plain` | The s0ma diagnostic error catalog (FR-MCP-10). |
| `s0ma://guide/getting-started` | `text/plain` | What s0ma is, who it fits, and how to prove its value. |
| `s0ma://guide/patterns` | `text/plain` | The s0ma DSL patterns guide — idioms for real applications. |
| `s0ma://guide/quick-reference` | `text/markdown` | The s0ma quick reference: every declaration, line by line. |
| `s0ma://guide/quick-reference.json` | `application/json` | The s0ma quick reference as data (JSON, schema s0ma-quick-reference@1). |
| `s0ma://guide/self-prompting` | `text/plain` | Runtime self-prompting and verified self_inspect wiring. |
| `s0ma://guide/survival-card` | `text/plain` | The s0ma survival card (under 4 KB) — read this FIRST, hold it in context. |
| `s0ma://guide/system-prompt` | `text/plain` | The s0ma DSL coding-agent system prompt. |
| `s0ma://meta/changelog` | `text/plain` | The s0ma platform changelog — what's new, per version (FR-MCP-10). |
| `s0ma://meta/version` | `application/json` | The installed s0ma toolchain versions as JSON (FR-MCP-10). |
| `s0ma://project/runbook` | `text/markdown` | The project's operational runbook (O1) as markdown. |
| `s0ma://self/model` | `application/json` | The authoring server's live self-model (FR-MCP-7) as JSON. |
| `s0ma://spec/current` | `text/plain` | The current s0ma DSL language specification (normative). |

### Prompts

| Prompt | Arguments | Journey |
|---|---|---|
| `author_module` | `project_root` (required), `module_name` (required), `kind` | Author a new s0ma module end to end. |
| `diagnose_fault` | `project_root` (required), `fault` (required) | Diagnose an observed runtime fault from self-knowledge first. |
| `feedback` | `message` | Send the user's feedback about s0ma to the s0ma team. |
| `fix_check_failures` | `project_root` (required) | Diagnose and fix s0ma check failures until the project is clean. |
| `migrate_project` | `project_root` (required) | Migrate a pre-consolidation project to the current s0ma surface. |
<!-- END GENERATED MCP SURFACE -->

Implementation note: tools invoke the `s0ma` CLI's own command surface (`s0ma_dsl.cli.main.S0maCLI`) **in-process** with `--format json` — no re-implemented pipeline, diagnostics byte-identical to the CLI's. `run_example` and the explicitly dangerous `verify_host` surface launch their documented isolated subprocesses for project-code execution. The same capabilities with their ids, effects, and approval behaviour — beside the runtime's own separate introspection server — are in [the MCP servers](../../docs/reference/mcp.md).

## The surface is derived, not enumerated (FR-MCP-7)

`s0ma-mcp` is itself a s0ma application: every tool, resource, prompt, and the `create_server` factory is a registered s0ma component — name, kind, layer, one-sentence intent, dependencies — in a dedicated package self-model, and `create_server` derives the entire FastMCP surface from it. There is no hand-maintained registration list, so a component carrying MCP metadata is served *because* it is in the registry, and a served surface without a registered component cannot exist. Ask the running server what it is: `describe_server()`, or read `s0ma://self/model`.

Adding a surface is therefore one move: author the `.s0ma` declaration with the matching `declares_attributes` namespace — `mcp_uri:<uri>` (plus `mcp_mime_type:<type>` where not text/plain) for resources, `mcp_prompt:<name>` plus `mcp_prompt_title:<title>` for prompts, `mcp_tool:<name>` plus `mcp_tool_annotations:<field>=<bool>` for tools — and the bridge catalogs it, the factory serves it. Two gates hold that line: `tests/test_components.py::TestDerivedSurface` asserts that every MCP-surfaced component carries complete serving metadata, that the catalog partitions exactly into served surfaces and a documented internal-plumbing allowlist (`UNSERVED_COMPONENTS`), and that an injected fake component with MCP metadata is served *without* touching the factory — derivation, not enumeration; and the committed schema snapshot (`tests/snapshots/mcp_surface.json`) pins the whole client-visible surface byte-exactly.

## How this package builds (FR-MCP-11)

The sources are `s0ma_src/*.s0ma` — the files humans and agents edit. Prompt copy is **data, not code**: each journey's text lives as a plain-text template under `s0ma_src/prompts/` and is embedded into a CONSTANT cell with the DSL's `content: @file(...)` directive under a check-enforced `placeholders:` contract, so `s0ma check` cross-checks the copy against the rendering nerves before anything builds. The package builds at the DSL's full `release` gate, which demands documentation and test coverage for every PUBLIC nerve, and the `.s0ma` sources satisfy it honestly: `test` declarations verify the rendering, serving, and boundary contracts of every public nerve, a `doc-ref` renders the public-surface reference straight from the registry, and a `doc-guide` narrates the self-hosting story around an embedded, executable `example` that the suite runs through the server's own `run_example` tool.

The build output is `src/s0ma_mcp/_built/` — committed, shipped in the wheel exactly as committed, held to the same `mypy --strict` gate as handwritten code, and never hand-edited. At runtime the package `__init__` — the single handwritten Python module, enforced by a test that counts them on disk — bootstraps those built modules under their canonical flat names, bridges their components into the package self-model, and lets `create_server` derive the surface from that catalog. The legacy `s0ma_mcp.server` import path stays available as an alias of it. `scripts/check.py`'s `selfhost-build` stage rebuilds from `s0ma_src/` with the cache disabled and **byte-compares** against the committed output on every OS, which makes it a standing cross-platform determinism regression test (PRD P-4/INV-5) on top of the "did you commit what you built" check.

Changing a surface is four steps, and skipping the last two turns the gate red:

```bash
$EDITOR packages/s0ma-mcp/s0ma_src/resources.s0ma
# --project-root is required (discovery anchors on the CWD); no --mode flag needed,
# because the package's own pyproject declares its [tool.s0ma].mode.
uv run s0ma --project-root packages/s0ma-mcp build packages/s0ma-mcp
uv run python scripts/check.py
git add packages/s0ma-mcp/s0ma_src packages/s0ma-mcp/src/s0ma_mcp/_built   # one commit
```

A red `selfhost-build` stage means exactly one of two things, and both are real failures: you forgot to rebuild and commit, or the transpiler stopped being deterministic for the same input (a s0ma-dsl bug to fix, never to paper over).

## The documents it ships

The file-backed document resources — the agent guides, the error catalog, the changelog, and the quick reference in both its forms (the page at `s0ma://guide/quick-reference` and the same facts as data at `s0ma://guide/quick-reference.json`) — are **committed copies** of their in-repo sources, shipped as package data in `s0ma_mcp/_docs/` and resolved with `importlib.resources`, so they work from an installed wheel and not only from a checkout (PRD FR-MCP-3/FR-MCP-10). `s0ma://meta/version` is the exception: no file — it renders live from `importlib.metadata` at read time.

The copies exist because the `s0ma-dsl` wheel packages only `src/s0ma_dsl` (its `docs/` tree is repo-only, the root `CHANGELOG.md` belongs to no wheel at all, and the quick reference is written by the documentation build under the repository's `docs/`), so cross-package resolution from installed distributions is impossible without changing those packages. They cannot drift silently: `tests/test_resources.py::TestDocDrift` byte-compares every file in `_docs/` against its in-repo source on every CI run, and CI stays red until the copy here is refreshed (`cp` the file and commit). Each copy and its original are listed in [the MCP servers](../../docs/reference/mcp.md). The error catalog's source is itself generated from the DSL's error-code registry: after grammar or diagnostic changes, regenerate it first (`make -C packages/s0ma-dsl docs-derived S0MA="uv run s0ma"`), then refresh the copy here.

## Telemetry (off by default, invisible to agents)

The server carries an optional call-telemetry hook for the s0ma benchmark and other improvement analysis. It is gated by the `S0MA_MCP_TELEMETRY` environment variable (unset or `0`/`false`/`off`/`no` = off), it appends one JSON line per served call to a **file sink** (`S0MA_MCP_TELEMETRY_SINK`, defaulting under the user cache directory — **never stdout**, which is the stdio transport's protocol channel), and it adds no field to any tool, resource, or prompt result: the wire responses are byte-identical with the flag off and on, pinned by `tests/test_telemetry_invisibility.py`.

Every record is self-describing. It leads with a `telemetry_schema` tag — `s0ma-telemetry@2` today — which is what a consumer keys on rather than sniffing the record's shape, then `ts`, `surface` (`tool`/`resource`/`prompt`), `name`, `ok`, `ms`, `size`, `counters`, and sanitized `args`. The `@N` suffix bumps only on a breaking change to the record shape; added fields and added counters do not bump it. Records written before the tag existed carry no marker at all and are recognized by `counters`-presence.

`counters` is derived purely from the `(surface, name, result)` the wrapper already sees. The tags the benchmark watches:

| Counter | Fires when |
|---|---|
| `runbook_read` | a read of the `s0ma://project/runbook` resource |
| `inline_rule_impression` | a tool result carrying the inline survival `rules` (`init_project` / `scaffold_module` / `describe_server`) |
| `refused_overwrite` | `build_project` surfaced `GENERATED_FILE_DRIFT` — the build refusing to clobber a hand-edited generated file |
| `drift_shown` | `check` surfaced `GENERATED_FILE_DRIFT` in its warn pass |
| `declaration_suggestion_shown` | a tool result carried a `suggested_declaration` block: a ready-to-paste corrected declaration |
| `build_override_new_errors` | a `build_project` result carried a `build_override` block — how often the escape hatch is used instead of fixing |

## Documentation

[**The map of record**](../../docs/README.md) lists every document this repository keeps, what it is for, and which check keeps it honest. The paths through this server:

- [Authoring through the agent's own tool channel](../../docs/guides/mcp-authoring.md) — the five-call loop an agent walks in a s0ma project.
- [The MCP servers](../../docs/reference/mcp.md) — the generated reference for both servers and the documents this one ships.
- [What s0ma can do](../../docs/reference/surfaces-index.md) — every capability s0ma serves, on every channel.
- [ADR-001](docs/adr/ADR-001-selfhost-layout.md) — why this package is laid out the way it is.

In a terminal, `s0ma docs` opens the same map and `s0ma docs show <topic>` answers one question from it. [CONTRIBUTING.md](../../CONTRIBUTING.md) has the workspace setup and the one command that runs the whole gate.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) for details. The rest of the toolchain shares it: `s0ma-core`, `s0ma-dsl` and `s0ma-studi0` are Apache-2.0 too, each with its own `LICENSE`.
