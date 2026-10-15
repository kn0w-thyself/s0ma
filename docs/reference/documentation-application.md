---
s0ma_kind: "doc-ref"
name: "documentation_application_reference"
module: "application"
format: "markdown"
intent: "Generated reference to the documentation application's own public surface: the three calls that compose a snapshot, ask it what is wrong, and ask it what it renders to. Rendered from the registry rather than written, so the page a contributor reads and the code the gate runs cannot say different things."
schema_version: "3.0.0"
content_hash: "1:ed408a09fed62fc1f34ac52030046bef802e34fd67120c4085c184d1fc337cd0"
---

# documentation_application_reference

Generated reference to the documentation application's own public surface: the three calls that compose a snapshot, ask it what is wrong, and ask it what it renders to. Rendered from the registry rather than written, so the page a contributor reads and the code the gate runs cannot say different things.

## intent

### nerve::compose_documentation

Reads every source once and settles them into a single picture of what s0ma knows about itself, which then stays the same for the rest of the build.

### nerve::documentation_artifacts

What a composition renders to, held in memory rather than written down, so that the command that writes the files and the command that checks them are looking at the same bytes.

### nerve::documentation_findings

Everything wrong with a composition, all of it at once. A run that stopped at the first problem would make somebody fix the documentation one line per run.

## expects

### nerve::compose_documentation

the path of a s0ma checkout, holding the catalog and the authored concept files the composition reads

### nerve::documentation_artifacts

a settled composition

### nerve::documentation_findings

a settled composition

## guarantees

### nerve::compose_documentation

returns one settled composition. The same checkout always produces the same one: nothing is read from an earlier run, no clock or network is consulted, and the order the sources are read in cannot change the answer.

### nerve::documentation_artifacts

returns every rendered artifact with its place under the documentation root and its whole content. Nothing is read from or written to the filesystem to produce them.

### nerve::documentation_findings

returns every finding the gates produced, in reporting order, with an empty result meaning nothing is wrong. Each finding says where to go and what to write instead.

## forbids

### nerve::compose_documentation

Never reads anything from an earlier run, and never consults a clock or the network.

### nerve::documentation_artifacts

Never reads from or writes to the filesystem, and never alters or rebuilds the composition it is given.

### nerve::documentation_findings

Never alters or rebuilds the composition it is given.
