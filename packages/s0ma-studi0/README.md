# s0ma-studi0

**studi0** is s0ma's local visual development environment, and **sh0w** is the graph renderer it hosts. `s0ma studi0 <project>` starts a loopback web server and opens one page: the project's own component graph — modules, components, and the authored, derived, and verification edges between them — drawn from the artifacts that project's last build produced (PRD §7.6, FR-STUDI0-1..9).

Every fact on the page comes from `s0ma-dsl`'s single graph-export contract (`s0ma_dsl.graph_export.collect_graph`, the same data `s0ma graph --format json --detail full` prints). studi0 has no second extraction path, so it cannot show you something the project did not declare. What it has no declaration for, it says so about: **nothing on the page is inferred, completed, or invented.**

studi0 is a **viewer**. It never executes or imports the application it is showing, never calls a model, and never opens a socket beyond `127.0.0.1` — it opens the project read-only and re-reads it as builds land. It writes exactly one file into the target tree: `.s0ma/studi0/active.json`, the marker that says a viewer is bound to this project, removed again when studi0 exits.

## Where it sits

Four distributions ship together at one version, and dependencies only ever point down the stack (PRD INV-6):

**`s0ma-studi0`** · [`s0ma-mcp`](../s0ma-mcp) → [`s0ma-dsl`](../s0ma-dsl) → [`s0ma-core`](../s0ma-core)

`s0ma-studi0` is **Apache-2.0**, and so are `s0ma-core`, `s0ma-dsl` and `s0ma-mcp`. What each distribution contains, and the license each one declares, is in [the distributions s0ma ships](../../docs/reference/packages.md).

## Install

s0ma is not on PyPI yet: all four packages are published there from the first release cut of the public repository, and until that lands the way in is the repository itself. That route is written down once, in the [root README's "Install" section](../../README.md#install) — working inside a checkout, or building the wheels and installing them into a project of your own — and [getting started](../../docs/getting-started.md#1-create-a-real-project) is the journey to walk once the `s0ma` command runs.

studi0 ships no console script of its own on purpose: the door is the `s0ma` CLI, which discovers this package lazily and prints an install hint if it is absent.

```bash
s0ma studi0                     # view the project in the current directory
s0ma studi0 path/to/project     # view a project elsewhere
s0ma studi0 --port 8731         # pin the port (default: an OS-assigned ephemeral one)
s0ma studi0 --no-open           # serve and print the URL without opening a browser
```

The server binds the loopback interface only, prints exactly one line naming the project and the URL it really bound, opens your browser there, and serves until you interrupt it:

```text
studi0 serving my-project at http://127.0.0.1:52544/
```

Programmatic use is the same call the subcommand makes: `launch(Path("path/to/project"), port=0, open_browser=False)` from `s0ma_studi0`.

## What the page shows

The canvas is organized the way the project's own declarations are. **Layer bands** run top to bottom — `PRESENTATION`, `APPLICATION`, `DOMAIN`, `INFRASTRUCTURE` — with `FRAMEWORK` appearing only when you ask for it. **Organs** are modules, placed in the band each one declares. **Nodes** are components, on a grid inside their organ, with shape and a type letter carrying the declaration type, so color is never the only carrier of meaning. **Edges** are authored solid, derived dashed, verification dotted.

Defaults hide the noise rather than the truth: `test`, `helper`, `doc_ref`, `doc_guide`, and `example` declarations and `FRAMEWORK`-layer modules sit behind two toolbar toggles, and everything hidden stays reachable — the inspector lists a component's verification edges whether or not they are drawn. Click any node or edge for intent first, then kind, layer, visibility and declaration type, the declared fields, the relationships with their provenance, and the source location. The whole view is keyboard-drivable, every glyph carries an `aria-label`, and under `prefers-reduced-motion` nothing animates. The page is fully self-contained (FR-STUDI0-7): no CDN, no web font, no remote asset, no telemetry.

## Being honest about how current it is

studi0's whole job is to be honest about what a project did and did not declare, and about how fresh the picture is.

- **Build freshness** is read from the build manifest and shown as one of three states: `fresh` (the graph, unmarked), `stale` (amber markers on the affected organs and nodes, plus a banner naming the stale modules), or `missing` (a full-page empty state carrying the command to run). What you see while a module is stale is the *last canonical build* — the declarations that were really compiled — never a guess at what the edited source now says.
- **Declared versus not declared.** A value renders as itself; an absent field renders as a muted *not declared*; a field the author explicitly deferred renders as *pending: &lt;reason&gt;*, surfaced as authoring debt rather than hidden as an empty slot.
- **Narration is separated from truth.** While studi0 is running, the authoring server may ask the agent to say which movement of the work it is in, and studi0 tails that log in a pane beside the graph. The pane says in words that it is self-reported and unverified, it never gains a checkmark or a badge, a line that does not parse is counted and dropped rather than guessed at, and a narrated name the graph does not carry is labelled *not in this graph* and moves nothing.

The routes studi0 serves, the contracts its build declares, the shape of a narration line, and the one file it writes are all in [studi0, the viewer](../../docs/reference/studi0.md) — generated from studi0's own built source, so it describes the viewer that ships.

## v1 limits

v1 is deliberately a pure viewer, and the honest list of what it is not is short:

- **Viewer only.** studi0 shows; it does not edit, scaffold, refactor, or run anything. Authoring stays in your editor and in `s0ma-mcp`.
- **Deferred, not stubbed:** proposal "ghosts", evidence badges, the pause protocol, session summary and retention, multi-agent views, host theme matching, replay, and 3D. None of them are half-present in the UI.
- **One project per process.** `launch()` serves one project root and blocks until interrupted.
- **The page needs JavaScript.** With scripting off it says so and points at `s0ma graph --format json --detail full`, which is the same data.
- **Local only.** The server is loopback-bound by construction; there is no flag to offer it to another machine.

## How this package builds

Like `s0ma-mcp`, this package is itself a s0ma project — a viewer for s0ma models that is a s0ma model. Its behavior is authored in the DSL under `s0ma_src/*.s0ma` and shipped as the transpiler's committed, deterministic build output under `src/s0ma_studi0/_built/`; `src/s0ma_studi0/__init__.py` is the **single** handwritten Python module, which bootstraps the built modules and exposes `launch()`. sh0w's front end rides the same rule (FR-STUDI0-8): `index.html`, `app.css`, and `app.js` are plain files under `s0ma_src/assets/`, embedded into PUBLIC CONSTANT cells with the DSL's `content: @file(...)` directive, so the served page is s0ma-owned content with its bytes hash-tracked in the build manifest.

Never hand-edit anything under `_built/` — a CI stage rebuilds it and byte-compares. Edit the `.s0ma` source, rebuild, and commit both together in one commit:

```bash
# --project-root is required: discovery anchors on the CWD, not the path argument.
# No --mode flag needed — the package's pyproject declares its own [tool.s0ma].mode.
uv run s0ma --project-root packages/s0ma-studi0 build packages/s0ma-studi0
```

Point studi0 at itself to see the arrangement: `uv run s0ma studi0 packages/s0ma-studi0` draws five organs — the server, the state service, the watch loop, the narration side channel, and the embedded sh0w assets. [CONTRIBUTING.md](../../CONTRIBUTING.md) has the workspace setup and the one command that runs the whole gate.

## Documentation

[**The map of record**](../../docs/README.md) lists every document this repository keeps, what it is for, and which check keeps it honest. The paths through studi0:

- [studi0, the viewer](../../docs/reference/studi0.md) — the generated reference: routes, contracts, wire documents.
- [Look at what you built, then tell us what is wrong with it](../../docs/guides/studi0-feedback.md) — the viewer and the feedback route, end to end.
- [What s0ma can do](../../docs/reference/surfaces-index.md) — every capability s0ma serves, on every channel.

In a terminal, `s0ma docs` opens the same map and `s0ma docs show <topic>` answers one question from it.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) for details. The rest of the toolchain shares it: `s0ma-core`, `s0ma-dsl` and `s0ma-mcp` are Apache-2.0 too, each with its own `LICENSE`.
