# s0ma-lang-studi0

**studi0** is s0ma's local visual development environment, and **sh0w** is the graph renderer it hosts. `s0ma studi0 <project>` starts a loopback web server and opens one page: the project's own component graph — modules, components, and the authored, derived, and verification edges between them — drawn from the artifacts that project's last build produced (PRD §7.6, FR-STUDI0-1..9).

Every fact on the page comes from `s0ma-lang-dsl`'s single graph-export contract (`s0ma_dsl.graph_export.collect_graph`, the same data `s0ma graph --format json --detail full` prints). studi0 has no second extraction path, so it cannot show you something the project did not declare. What it has no declaration for, it says so about: **nothing on the page is inferred, completed, or invented.** The one thing on the page that is not about your project is s0ma's own definition of the words it is written in, and that comes from s0ma too: the teaching slice `s0ma-lang-core` ships, the same entries `s0ma docs show` prints.

studi0 is a **viewer**. It never executes or imports the application it is showing, never calls a model, and never opens a socket beyond `127.0.0.1` — it opens the project read-only and re-reads it as builds land. It writes exactly one file into the target tree: `.s0ma/studi0/active.json`, the marker that says a viewer is bound to this project, removed again when studi0 exits.

## Where it sits

Five distributions ship together at one version: the four below, and the umbrella [`s0ma-lang`](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-lang), which carries no code and requires each of the four at exactly its own version. Dependencies only ever point down the stack (PRD INV-6):

**`s0ma-lang-studi0`** · [`s0ma-lang-mcp`](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-mcp) → [`s0ma-lang-dsl`](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-dsl) → [`s0ma-lang-core`](https://github.com/kn0w-thyself/s0ma/tree/main/packages/s0ma-core)

`s0ma-lang-studi0` is **Apache-2.0**, and so are `s0ma-lang-core`, `s0ma-lang-dsl` and `s0ma-lang-mcp`. What each distribution contains, and the license each one declares, is in [the distributions s0ma ships](https://github.com/kn0w-thyself/s0ma/blob/main/docs/reference/packages.md).

## Install

s0ma is on PyPI:

```bash
pip install s0ma-lang-studi0
```

That brings `s0ma-lang-dsl` and `s0ma-lang-core` with it. The package is named `s0ma-lang-studi0` and imported as `s0ma_studi0`. The other ways in, working inside a checkout or building the wheels yourself, are in the [root README's "Install" section](https://github.com/kn0w-thyself/s0ma/blob/main/README.md#install), and [getting started](https://github.com/kn0w-thyself/s0ma/blob/main/docs/getting-started.md#1-create-a-real-project) is the journey to walk once the `s0ma` command runs.

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

A project with nothing built yet is not a lost connection, and the page does not say it is. Once the server has answered that nothing is built, the canvas draws the same layer bands, empty, with one sentence in the middle, "Nothing is built yet. Parts appear here when the first build lands.", the command to run under it, and the status line saying nothing is built yet. Until the server has answered, the canvas stays blank rather than guess. When the first build lands, its parts arrive the way an added part arrives on any later build, and no reload is needed. Until then there is no `terms` button either, because s0ma's definitions arrive with the graph.

Defaults hide the noise rather than the truth: `test`, `helper`, `doc_ref`, `doc_guide`, and `example` declarations and `FRAMEWORK`-layer modules sit behind two toolbar toggles, and everything hidden stays reachable. The inspector lists a component's verification edges whether or not they are drawn.

Click a component and the inspector opens on its short name, its declaration type, and its `module` and `layer`. Each label puts the DSL term first and a plain phrase after it, as in `intent` · what it is for. Then comes `intent`, followed, for a nerve or a ganglion, by `guarantees`, `forbids`, and `expects`, and for a cell by `schema`, `invariants`, and `value`. A row appears only when the part carries that field, so a ganglion, which has no `guarantees` or `expects` line, shows neither. Every value is the author's text exactly as written. A field with nothing declared says "not declared", a deferred one says "pending:" and its reason, and a written `forbids: none` shows `none`. Next come its dependencies, the relationships that leave it, and its dependents, the relationships that arrive at it. Each row names the relation, the part at the other end as a button that selects it, and whether the relationship is authored or derived, with an authored one's `carries` text. Everything else sits under one disclosure, "More about this part": `kind` and `visibility`, `covered_by` with the verification relationships, every other declared field, a counted line of the fields not declared, the file and lines it was written in, and its canonical id. A pending field is never folded away.

Click a module's name in its header and the inspector opens on the module: its name, a `module` tag, its `layer` and how many components it holds, and the stale note when it is stale. The arrow and the rest of the header still collapse and expand it. Then come `intent` · what it is for, `uses` · parts of other files it may reach, grouped under "from" and the other module's name, `requires` · code from outside the project, `exports` · what it offers to other files, and used by · files that reach into it. A part name in `uses` or `exports` is a button that selects that part when the graph carries it, and is shown as written when it does not. `requires` names are shown as written, since they are not in the graph. "used by" lists the modules whose declared `uses` name a part of this one, each a button that selects it, or says "none in this project". A row appears only when the module record carries it, so a graph from an older build shows the header and `intent` alone. Everything else sits under "More about this module": `version`, `tags`, a counted line for the import lists not declared, and the file it was written in.

Click an edge or an integration for its own panel.

When a build lands while the page is open, the parts it added, changed, or removed are marked for a few seconds. A part counts as changed only when something it declares differs: its `intent`, a field, its `kind`, `visibility`, or `layer`, or the set of things it leans on. Where it sits in its file is not a change, so a part pushed down by one written above it is not marked. After the marks fade, the parts the newest build added keep a steady outline, two thin rules just outside the part, unlike the single heavier line inside a selected part, until the next build that adds, changes, or removes something, and the status line says "Outlined parts arrived in the newest build." A page opened on a project that is already built outlines nothing.

A build that adds more than 4 parts in view, in more than one module, is shown one module at a time rather than all at once. A module comes after the modules it leans on, those it has a dependency on; otherwise the band nearer the bottom of the page goes first, then the module name. Each module's new parts arrive together with the usual mark, and the next module follows two seconds later. The build's changed and removed parts show at once. Every part already has its place, so nothing moves as the rest arrive, and an edge is drawn once both its ends are. While it runs, the status line says how many parts landed and how many are showing, for example "This build added 6 parts. Showing 3 of 6, module by module.", beside a "Show the rest" button that shows everything left at once. A newer build that adds, changes, or removes something, the `tests and docs`, `framework layer`, `expand all`, and `collapse all` buttons, selecting something not yet shown, or the project becoming unbuilt does the same. Under `prefers-reduced-motion` there is no reveal: everything appears at once.

A module that arrives with a build is placed after the modules already drawn in its band, and keeps that place while the page is open, so nothing already drawn moves sideways to make room for it. A reload sorts each band again. A module that grows, or a new band, may still push what is below it down.

The view follows the build. The page starts out keeping the whole graph in frame. When a build needs a different frame, the view eases to it first, in about half a second, while the page still shows what it had, and then the build lands: its parts, their marks, the reveal, and its entry in the list of changes together. The part nearest the middle of the view keeps its place on screen as it lands. The `tests and docs`, `framework layer`, `expand all`, and `collapse all` buttons, and a module's own collapse control, act at once and then ease to the new fit. Dragging the canvas, the wheel, `+` and `-`, and the arrow keys stop the following, and `fit` or the `f` key eases to the whole graph and starts it again. While the view is not following, a build that lands keeps the part nearest the middle where it was and moves nothing else, and if parts it added are out of view, a button at that edge of the canvas says so, for example "3 new parts below · show them", and pressing it does what `fit` does. Under `prefers-reduced-motion` the view jumps instead of easing. Nothing is stored, so a reload starts out following.

The left column holds "What changed since you opened this page": one entry for each build that added, changed, or removed something since the page opened, newest first. An entry reads, for example, "Build 2 · added 2 parts, changed 1", then the added parts by name, each a button that selects the part, one line per changed part naming the declared lines that differ, and the parts that were removed. The first build after "nothing is built" says so: "Build 1 · the first build, added 4 parts". While a build is being shown module by module, its entry adds how many are showing, as in "Build 3 · added 6 parts · showing 3 of 6", and names only the parts shown so far; when the last arrives it reads in full again. The entry follows the view toggles as the canvas does, and counts in one line the parts they hide. A build that only moved lines makes no entry. The list lives only in the page: nothing is stored anywhere, a reload clears it, and it keeps the newest 30 builds and says how many earlier ones are not listed. The `changes` button in the toolbar hides and shows it. Narration, when there is any, sits under it in the same column.

The page explains its own words. Where it prints a s0ma word, such as the declaration type in a panel's header, `module` and `layer` and the layer's name under it, the term of a field label (`intent`, `forbids`, `uses`), a field name under a fold (`kind`, `visibility`), the relation word in a relationship row, or a glyph's name in the legend, that word is a button when s0ma has an entry for it. Click it and a card opens under the row with the entry's one-sentence summary, its fuller definition behind "Read more", and the command that prints the whole entry, such as `s0ma docs show concept:contract`. A word explained under another entry says so first: `forbids` is explained under `contract`, a layer name under `layer`, and a relation word under `axon`. Every sentence is s0ma's, unchanged. The `terms` button in the toolbar opens the same entries as a dictionary in the right panel: first the words this page can show, then the rest of s0ma's concepts behind one disclosure. Pressing `terms` again goes back to the part you had open, or closes the panel if there was none. A word with no entry is drawn as it always was, and if the server sends no definitions at all, no word is a button and there is no `terms` button.

The whole view is keyboard-drivable, every glyph carries an `aria-label`, and under `prefers-reduced-motion` nothing animates. The page is fully self-contained (FR-STUDI0-7): no CDN, no web font, no remote asset, no telemetry.

## Being honest about how current it is

studi0's whole job is to be honest about what a project did and did not declare, and about how fresh the picture is.

- **Build freshness** is read from the build manifest and shown as one of three states: `fresh` (the graph, unmarked), `stale` (amber markers on the affected organs and nodes, plus a banner naming the stale modules), or `missing` (the empty layer bands, with a sentence saying nothing is built yet and the command to run). What you see while a module is stale is the *last canonical build* — the declarations that were really compiled — never a guess at what the edited source now says.
- **Declared versus not declared.** A value renders as itself; an absent field renders as a muted *not declared*; a field the author explicitly deferred renders as *pending: &lt;reason&gt;*, surfaced as authoring debt rather than hidden as an empty slot.
- **Narration is separated from truth.** While studi0 is running, the authoring server may ask the agent to say which movement of the work it is in, and studi0 tails that log in a pane beside the graph. The pane says in words that it is self-reported and unverified, it never gains a checkmark or a badge, a line that does not parse is counted and dropped rather than guessed at, and a narrated name the graph does not carry is labelled *not in this graph* and moves nothing.

`GET /api/graph` answers with four keys: `schema` (`s0ma-studi0-graph@1`), `seq`, `graph` (the graph export, passed through whole), and `terms`, which holds `source` (the slice's `release_version` and `snapshot_hash`, or `null` when the slice cannot be read) and `entries` (one per concept: `id`, `name`, `names`, `summary`, and `definition` when there is one, all copied verbatim). The terms are read once per server process. The routes studi0 serves, the contracts its build declares, the shape of a narration line, and the one file it writes are all in [studi0, the viewer](https://github.com/kn0w-thyself/s0ma/blob/main/docs/reference/studi0.md) — generated from studi0's own built source, so it describes the viewer that ships.

## v1 limits

v1 is deliberately a pure viewer, and the honest list of what it is not is short:

- **Viewer only.** studi0 shows; it does not edit, scaffold, refactor, or run anything. Authoring stays in your editor and in `s0ma-lang-mcp`.
- **Deferred, not stubbed:** proposal "ghosts", evidence badges, the pause protocol, session summary and retention, multi-agent views, host theme matching, replay, and 3D. None of them are half-present in the UI.
- **One project per process.** `launch()` serves one project root and blocks until interrupted.
- **The page needs JavaScript.** With scripting off it says so and points at `s0ma graph --format json --detail full`, which is the same data.
- **Local only.** The server is loopback-bound by construction; there is no flag to offer it to another machine.

## How this package builds

Like `s0ma-lang-mcp`, this package is itself a s0ma project — a viewer for s0ma models that is a s0ma model. Its behavior is authored in the DSL under `s0ma_src/*.s0ma` and shipped as the transpiler's committed, deterministic build output under `src/s0ma_studi0/_built/`; `src/s0ma_studi0/__init__.py` is the **single** handwritten Python module, which bootstraps the built modules and exposes `launch()`. sh0w's front end rides the same rule (FR-STUDI0-8): `index.html`, `app.css`, and `app.js` are plain files under `s0ma_src/assets/`, embedded into PUBLIC CONSTANT cells with the DSL's `content: @file(...)` directive, so the served page is s0ma-owned content with its bytes hash-tracked in the build manifest.

Never hand-edit anything under `_built/` — a CI stage rebuilds it and byte-compares. Edit the `.s0ma` source, rebuild, and commit both together in one commit:

```bash
# --project-root is required: discovery anchors on the CWD, not the path argument.
# No --mode flag needed — the package's pyproject declares its own [tool.s0ma].mode.
uv run s0ma --project-root packages/s0ma-studi0 build packages/s0ma-studi0
```

Point studi0 at itself to see the arrangement: `uv run s0ma studi0 packages/s0ma-studi0` draws five organs — the server, the state service, the watch loop, the narration side channel, and the embedded sh0w assets. [CONTRIBUTING.md](https://github.com/kn0w-thyself/s0ma/blob/main/CONTRIBUTING.md) has the workspace setup and the one command that runs the whole gate.

## Documentation

[**The map of record**](https://github.com/kn0w-thyself/s0ma/blob/main/docs/README.md) lists every document this repository keeps, what it is for, and which check keeps it honest. The paths through studi0:

- [studi0, the viewer](https://github.com/kn0w-thyself/s0ma/blob/main/docs/reference/studi0.md) — the generated reference: routes, contracts, wire documents.
- [Look at what you built, then tell us what is wrong with it](https://github.com/kn0w-thyself/s0ma/blob/main/docs/guides/studi0-feedback.md) — the viewer and the feedback route, end to end.
- [Watch an app being built](https://github.com/kn0w-thyself/s0ma/blob/main/docs/guides/watch-an-app-being-built.md): a finished example in studi0 first, then your own agent building one like it in three requests.
- [What s0ma can do](https://github.com/kn0w-thyself/s0ma/blob/main/docs/reference/surfaces-index.md) — every capability s0ma serves, on every channel.

In a terminal, `s0ma docs` opens the same map and `s0ma docs show <topic>` answers one question from it.

## License

Apache License 2.0 — see [`LICENSE`](https://github.com/kn0w-thyself/s0ma/blob/main/packages/s0ma-studi0/LICENSE) for details. The rest of the toolchain shares it: `s0ma-lang-core`, `s0ma-lang-dsl` and `s0ma-lang-mcp` are Apache-2.0 too, each with its own `LICENSE`.
