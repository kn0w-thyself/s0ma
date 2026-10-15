# studi0, the viewer

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

studi0 shows you the project you just built: every component it contains, how they are wired, and whether what you are looking at is still current. It answers 5 routes and its build declares 6 contracts — promises about what it serves, what those answers look like, and what it touches on your machine.

Every fact on this page is read from studi0's own built source when the documentation is built, so it describes the viewer that ships rather than the one somebody meant to ship.

## Contents

- [The routes it answers](#the-routes-it-answers)
- [The contracts its build declares](#the-contracts-its-build-declares)
- [What the server will and will not do](#what-the-server-will-and-will-not-do)
- [The graph document](#the-graph-document)
- [The state document](#the-state-document)
- [Watching the build](#watching-the-build)
- [What an agent says it is doing](#what-an-agent-says-it-is-doing)
- [The one file studi0 writes](#the-one-file-studi0-writes)

## The routes it answers

5 routes, and nothing else is served. 2 of them answer with the data the page draws itself from; the other 3 are the page. The server listens on `127.0.0.1` and nowhere else. Anything not listed here answers `NOT_FOUND`.

**Effects** are read from the capability itself wherever it declares them: `none`, `read`, `write`, `network`, `subprocess`, `credential`, `approval`. Where nothing declares them, the row says `not declared` rather than guessing — that is an answer about the capability's own description, not about what it does.

| Route | Id | Method | What it is for | Effects | Reports |
| --- | --- | --- | --- | --- | --- |
| `/api/graph` | `studi0:action/api/graph` | `GET` | The whole component graph of the project being shown, wrapped in the sequence number it belongs to, fetched only when the sequence number says it is worth fetching. | read | NOT_BUILT |
| `/api/state` | `studi0:action/api/state` | `GET` | The cheap poll: which reading this is, whether the build still matches the sources it was built from, which modules have moved on, and what an agent has said it is doing. | read | — |
| `/assets/app.css` | `studi0:action/assets/app.css` | `GET` | The sh0w page's stylesheet, served as the build embedded it. | none | — |
| `/assets/app.js` | `studi0:action/assets/app.js` | `GET` | The sh0w page's script, served as the build embedded it — the whole of the viewer's behaviour. | none | — |
| `/` | `studi0:action/index` | `GET` | The sh0w page itself — the one document studi0 hands a browser, which then learns everything it draws from the graph API. | none | — |

## The contracts its build declares

A contract is a promise the build makes and this documentation reads back: each one names the file it is declared in and the declaration inside it, so the promise and the code that keeps it are never two separate things to maintain. 6 of them.

### What the server will and will not do

The shape of the server itself: where it listens, which method it answers, how many routes it has, and what a request for anything else gets back. It listens on the loopback address only, which is the whole of its security model — studi0 shows you your own project on your own machine and is not something to put on a network.

Id `authority:declared/studi0.serving-contract`, declared as `Studi0ServerConfig` in [`packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_server.py`](../../packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_server.py).

| Fact | Value |
| --- | --- |
| `client_poll_ms` | `1000` |
| `host` | `127.0.0.1` |
| `methods` | `GET` |
| `routes` | `5` |
| `shutdown_poll_seconds` | `0.2` |
| `unserved` | `NOT_FOUND` |

### The graph document

What `/api/graph` answers with. The schema name is versioned and carried in the document itself, so a viewer that was written against an older one can say so instead of drawing the wrong picture.

Id `authority:declared/studi0.wire-graph`, declared as `GRAPH_SCHEMA` in [`packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_state.py`](../../packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_state.py).

| Fact | Value |
| --- | --- |
| `carries` | `s0ma-graph@2` |
| `keys` | `graph,schema,seq` |
| `route` | `/api/graph` |
| `schema` | `s0ma-studi0-graph@1` |

### The state document

What `/api/state` answers with. This is the cheap poll: it says which reading you are looking at and whether anything has moved since, so the expensive graph is fetched only when the sequence number says it is worth fetching.

Id `authority:declared/studi0.wire-state`, declared as `STATE_SCHEMA` in [`packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_state.py`](../../packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_state.py).

| Fact | Value |
| --- | --- |
| `keys` | `build_status,narration,schema,seq,stale_modules` |
| `narration_keys` | `entries,invalid,total` |
| `route` | `/api/state` |
| `schema` | `s0ma-studi0-state@2` |

### Watching the build

How studi0 notices that what you are looking at has gone stale. It reads build artifacts on a timer and it never raises: a viewer that crashed because a file was half-written would be a worse tool than one that says the picture is old.

Id `authority:declared/studi0.watch-contract`, declared as `Studi0WatchConfig` in [`packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_watch.py`](../../packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_watch.py).

| Fact | Value |
| --- | --- |
| `join_seconds` | `5.0` |
| `poll_seconds` | `0.75` |
| `raises` | `never` |
| `reads` | `build_artifacts` |
| `reports` | `once_per_failure` |
| `writes` | `none` |

### What an agent says it is doing

The one thing studi0 shows that does not come from the build: a line an agent writes to say which phase of the work it is in. Anything that does not fit the declared shape is counted and never drawn, so a malformed line cannot put text of its own choosing on your screen.

Id `authority:declared/studi0.narration-event`, declared as `NARRATION_TYPE` in [`packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_narration.py`](../../packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_narration.py).

| Fact | Value |
| --- | --- |
| `invalid` | `counted_never_rendered` |
| `log` | `.s0ma/studi0/session.jsonl` |
| `phases` | `orient,author,verify,move_on` |
| `type` | `work.narrated` |
| `window` | `50` |

### The one file studi0 writes

studi0 reads your project and does not change it, with exactly one exception, named here: a marker saying a viewer is currently bound to this project. It is written when the viewer binds and removed when it exits.

Id `authority:declared/studi0.presence-marker`, declared as `PRESENCE_PATH_PARTS` in [`packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_narration.py`](../../packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_narration.py).

| Fact | Value |
| --- | --- |
| `path` | `.s0ma/studi0/active.json` |
| `removed` | `on_exit` |
| `scope` | `the_only_file_studi0_writes` |
| `written` | `on_bind` |
