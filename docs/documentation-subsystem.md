# The documentation subsystem

s0ma's premise is that a system should be able to describe itself without the
description drifting from the thing described. The documentation subsystem is
where that premise is cashed in for documentation: it is the machinery that
lets a page be a projection of the registry rather than a file somebody
remembered to update.

It has two levels, and they are often confused because they share a name.

**The language level** is three declarations — `doc-ref`, `doc-guide` and
`example` — plus a gate that refuses a committed page which no longer matches
the code it describes. Any project written in s0ma gets these. This is the
level the DSL spec calls the documentation declarations.

**The application level** is one particular use of that idea, at a size the
declarations were never meant to carry: the composition that reads eleven
sources, settles them into a single model of what s0ma knows about itself, runs
a battery of gates over it, and renders every generated page in this
repository. That composition is the *documentation application*, and it lives
in `docs/`.

This page teaches both. It is for the contributor or agent who has to change
something and needs to know which level they are standing on, what will refuse
them, and where the fact they are about to write down already lives.

Everything below is prose about how the machinery behaves. Every enumeration —
which diagnostics exist, which readings run, which files get written, which
components are registered — is on a generated page instead, named where it is
relevant. That split is deliberate: an invariant stated in prose stays true
while the counts move underneath it, and a count written in prose is a count
that goes stale the first time somebody adds a twelfth of something.

*Held by:* [ADR-012](adr/ADR-012-docs-application.md) for the application,
[DSL spec §4.12](../packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md) for the
declarations. Where this page and either of those disagree, they are right and
this page is the defect.

## Contents

- [Level one: the three declarations](#level-one-the-three-declarations)
- [How rendering works](#how-rendering-works)
- [How drift is caught](#how-drift-is-caught)
- [What the runtime holds](#what-the-runtime-holds)
- [Level two: the documentation application](#level-two-the-documentation-application)
- [The gates](#the-gates)
- [How a topic is read](#how-a-topic-is-read)
- [Where each fact lives](#where-each-fact-lives)

## Level one: the three declarations

The subsystem brings authored documentation under the same grammar-level
enforcement as code. Three declaration kinds do the work.

| Declaration | Reach for it when you want to |
| --- | --- |
| `doc-ref` | Render reference material — an API listing, a registry catalogue, a contract index — entirely from the registry. No prose, no narrative. |
| `doc-guide` | Write a narrative document that names registered components. Every claim it makes is verified against the registry before it renders. |
| `example` | Capture a reusable, executable demonstration. An example is a registered, testable, embeddable artifact rather than a code block. |

Each has its own page in the learning collection —
[doc-ref](learn/doc-ref.md), [doc-guide](learn/doc-guide.md) and
[example](learn/example.md) — with the authored definition, when to reach for
it, and when not to.

All three use the **registry namespace**: they can reach INTERNAL components
and components in other modules, exactly as `observes:` and `tests:` already
do. That is total observability, and it is the point. Drift would be
impossible to catch if documentation could only see what a module exports.

The rule of thumb: **if a document names a registered component, it should be
a `doc-ref` or a `doc-guide`.** Conceptual teaching that names no registered
component — what a nerve *is*, why a layer exists — stays hand-authored, and
this page is itself an instance of that exemption.

### The shapes

A `doc-ref` says what to render and from where. `covers:` selects and
`sections:` says which fields of each selected entity to emit:

```
doc-ref tools_reference
    intent: "Generated reference for the tools module's public nerves."
    format: markdown
    output: docs/tools_reference.md
    covers: [nerve where module == tools]
    sections: [intent, expects, guarantees]
```

The fields `sections:` can name are the selected kind's own — for a nerve,
among others, `intent`, `expects`, `guarantees` and `forbids` (what it must
never do); for a ganglion, among others, `observes`, `on_anomaly` and
`forbids`.

A `doc-guide` is prose with holes in it. `{{...}}` tokens resolve against the
registry, `asserts:` are evaluated before the render is allowed, and
`examples:` names the demonstrations the body embeds:

```
doc-guide greetings_walkthrough
    intent: "New-developer walkthrough for the greetings nerve."
    format: markdown
    output: docs/greetings_walkthrough.md
    covers: [nerve::greet]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: [example::greet_example]
    ---
    The {{nerve::greet}} nerve produces a greeting from a username.

    {{example::greet_example}}
```

An `example` is a body that runs:

```
example greet_example
    intent: "Demonstrates calling greet with a sample username."
    demonstrates: [nerve::greet]
    runs_in: standalone
    ---
    from greetings import greet

    print(greet("Ada"))
```

Transpiling that pair parses both modules, resolves `{{nerve::greet}}` against
the registry, evaluates the assert and confirms it holds, verifies the example
is registered, renders the page with the example body inlined, and computes a
transitive content hash over the document and the registry slice it touched —
baking that hash into both the rendered file's front matter and the emitted
registration.

Which is to say: if `greet` later flips to INTERNAL, the assert fails before
the guide can be regenerated. If the example body breaks, the test run catches
it. If someone edits `greet`'s intent without re-rendering, the gate fails.

### The two shapes of `covers:`

`covers:` accepts exactly one of two shapes per declaration.

**Component filter form** — a bracketed list of filter expressions over
registry entity types, shown above. Each selected entity is rendered through
every `sections:` entry. A `where` predicate compares an entity's addressable
fields; the field set is per kind, plus one field every kind shares: `module`,
the name of the module that owns the entity. That shared field is what makes
per-module references expressible in a multi-module project — one reference
per module instead of one project-wide document. The comparison is by name
only, so an unrecognised module name matches nothing and surfaces as
`EMPTY_DOC_FILTER` like any other predicate that selects nothing. There is no
distinct "unknown module" report.

**Source-registry form** — a single-key dictionary naming a derived,
non-component registry the renderer materialises directly:

```
doc-ref ErrorCodesTable
    intent: "Generated table of every registered error code."
    format: markdown
    output: docs/error_codes.md
    covers: { source: error_codes }
    sections: []
```

In this form `sections:` is unused: the renderer emits one self-contained
table per declaration. Mixing a `kind:` key and a `source:` key in the
dictionary is refused at parse time — the discriminator is exclusive.

*Held by:* [ADR-013](adr/ADR-013-derived-source-registry.md), which is where
the source registry was decided and which names the registries that exist.

### Coverage credit for tests that live elsewhere

Release mode demands test coverage for every PUBLIC nerve
(`MISSING_TEST_COVERAGE`). The gate is satisfied by *either* an in-language
`test` declaration whose `tests:` names the nerve, *or* a `covered_by:` field
on the nerve naming the external evidence:

```
nerve check_tool :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Validates .s0ma source and returns structured diagnostics."
    covered_by: ["packages/s0ma-mcp/tests/test_tools.py — boundary-contract suite"]
```

`covered_by:` is authored-opaque: a non-empty list of non-empty strings, which
may be suite paths or rationale prose. The language validates shape only —
`COVERED_BY_EMPTY` otherwise — and never resolves the strings. Honesty is the
author's burden, and the claim is auditable because it rides the canonical IR,
the emitted registration metadata, and the rendered reference, where it
appears as a `Covered by:` line after the intent. The credit does not inject
synthetic test targets, so "tested in-language" and "externally covered" stay
distinguishable in the record.

**When you author `test` declarations instead**, mind where the emitted test
functions land. In a committed-build package they live in the built modules,
where a plain `testpaths = ["tests"]` never collects them — and a release gate
satisfied by tests that never execute is worse than no gate. The blessed
pattern is the wrapper-import recipe: one file in the collected `tests/`
directory that imports the emitted test functions into a module the runner
does collect. Imported test names are collected like any other, so
DSL-authored tests run in the existing suite on every platform with no extra
configuration.

Rule of thumb: use `covered_by:` when the real coverage lives in an external
plain-pytest suite, and name the suite path so the claim is checkable; use
`test` declarations plus the wrapper-import recipe when you want the coverage
expressed in-language and still executed by one run.

## How rendering works

Every doc declaration renders as a pure function of its declaration, the
project index, the content hash, the transpiler version and the schema
version. The renderer never touches the filesystem while rendering, never
reads the wall clock, never generates a unique identifier. Re-running it on
identical input produces byte-equal output. That is the deterministic-render
contract, and it is what makes a drift check possible at all: without it,
"the file differs from a fresh render" would mean nothing.

**Formats.** `format:` chooses one of three, and the choice decides where the
document's identity block goes: `markdown` carries it as YAML front matter
between `---` delimiters, `html` as `<meta>` tags, `json` as a top-level
`_meta` block. Markdown is the default and is what a repository commits;
`json` exists for machine consumption.

**The front-matter contract** is seven fields in a declared order —
`s0ma_kind`, `name`, `module`, `format`, `intent`, `schema_version`,
`content_hash`. Downstream tools parse that contract, so adding, removing or
reordering a field is carried by the schema version rather than done quietly.
A `transpiler_version` field was dropped in 0.8.0: it collided in name with
the build manifest's distribution-version field while carrying only the
codegen-contract constant, and its presence made every rendered document churn
on a distribution bump. The schema version remains the contract identity, and
the content hash still mixes in the transpiler version — it is simply no
longer a rendered field of its own.

**Markdown flavour.** The renderers emit a hand-rolled subset of
GitHub-flavoured Markdown: headings, paragraphs, fenced code blocks and bullet
lists. No tables, no link rewriting, no syntax highlighting, no footnotes.
This is deliberate rather than unfinished — every external Markdown library
introduces version-dependent variability, and version-dependent variability
breaks byte-equal reproducibility, which is the property the whole subsystem
rests on. Richer output is tracked in the
[archived TODO](archive/pre-monorepo/s0ma-dsl/plans/TODO.md) for a post-v1
release; the trigger is a real consumer asking, not a preference.

**Where rendered documents land.** A declaration's `output:` is a relative
path, resolved against a base directory chosen by this precedence, identical
for `s0ma build`, `s0ma docs render` and `s0ma docs check-drift` so the gate
always checks the directory the build actually writes to:

1. An explicit `--output-dir`, if passed. It always wins.
2. Otherwise the resolved project's `[tool.s0ma].build_dir` — for a configured
   project the build emits everything, documents included, under the build
   directory. This is the right behaviour for a committed-build package: the
   rendered documents ride the committed build, the byte-equality gate and the
   wheel with no extra wiring.
3. Otherwise — a synthetic invocation with no `[tool.s0ma]` table — the source
   path if it is a directory, else its parent.

Because all three commands share the rule, `s0ma docs check-drift` for a
configured project re-renders into the build directory and byte-compares
against exactly what `s0ma build` committed there. The selfhost byte gate and
the drift check converge on the same files. A fourth command,
`s0ma docs verify`, validates the declarations without rendering anything,
which is what you want while a document is still being written.

## How drift is caught

The drift check is what makes the subsystem load-bearing rather than advisory.
Without it the rendered documents in a repository are just files; with it they
are registry projections the build refuses to commit out of sync.

Run it locally before pushing, and in continuous integration where a
difference should be an error:

```bash
s0ma docs check-drift
s0ma docs check-drift --mode strict
```

Internally the command computes the transitive content hash for every
`doc-ref` and `doc-guide` in the project using the same machinery the renderer
uses, re-renders each document into memory, byte-compares that against the
file on disk, and emits `DRIFT_DETECTED` with a diff summary for anything that
differs. Severity follows the [strictness mode](learn/strictness-mode.md):
a warning in `migration` and `dev`, an error in `strict` and `release`.

**What triggers drift:** a covered nerve, cell or module changed — even a
one-character intent tweak flips the hash; an embedded example's body changed;
a `covers:` filter started matching a different set of entities; the
transpiler version changed, in which case you regenerate and the hash changes
by design.

**What does not:** changes to components the document never touches, because
the transitive hash walks only referenced state; and whitespace inside a
`.s0ma` source that does not affect the structured tree, because the hash is
computed over the [canonical IR](learn/canonical-ir.md) rather than the raw
source.

The [drift](learn/drift.md) and [drift-gate](learn/drift-gate.md) pages carry
the concepts; [what s0ma can report](reference/diagnostics.md) carries every
code, its severity per mode, and what to do about it — including the ones an
author meets most while writing documentation: `UNRESOLVED_REFERENCE`,
`ENTITY_KIND_MISMATCH`, `FIELD_NOT_FOUND`, `ASSERT_FAILED`,
`PROSE_RAW_CODE_BLOCK`, `EMPTY_DOC_FILTER` and `DRIFT_DETECTED`, plus the two
release-mode gates a documentation change trips first,
`MISSING_PUBLIC_DOC_REF` and `MISSING_EMBEDDED_EXAMPLE`.

## What the runtime holds

The declarations are a language feature; what a running program can *ask*
about them is a runtime one. Three registration calls put a document or an
example into the registry — `s0ma.register_doc_ref`, `s0ma.register_doc_guide`
and `s0ma.register_example` — and the transpiler emits them from the
declarations rather than expecting anyone to write them by hand.

**The emitted module advertises what it will register.** Each generated `.py`
carries module-level marker attributes naming the registrations its body is
expected to install by the time it finishes executing. After the body runs,
the import hook looks each name up; a marker entry that resolves to nothing
raises in strict mode and warns in lenient mode. The marker is redundant while
generation and registration are in sync — and load-bearing when they are not.
A stale transpiled file that outlives the source which produced it is caught
immediately, rather than at whatever later moment somebody queries for a
document that is not there. It is the same structural argument that makes
`@component` load-bearing: the metadata sits at the site of the entity, not
only in a remote registry.

**What you can ask, and where.** The registry snapshot carries the registered
documents and examples and answers the two reverse questions — which documents
cover this component, which examples demonstrate it. The self-model interface
wraps those for a caller who wants prose rather than records, and adds a drift
report that recomputes every stored content hash and lists the divergences.
The same answers are served over the optional REST surface at
`GET /self/docs`, `GET /self/doc/{name}`, `GET /self/examples`,
`GET /self/example/{name}` and `GET /self/drift`, and over the optional MCP
surface as `s0ma://docs/registered-docs`,
`s0ma://model/docs-for/{component}`, `s0ma://model/examples-for/{component}`
and the `get_examples_for` tool for clients that only make tool calls.

**Hashing.** `s0ma.content_hash` computes the transitive digest a document
carries: a version prefix, the registration with its own hash zeroed, and the
transitive closure of the registry state it references.
`s0ma.canonicalize` is the deterministic byte serializer underneath it, which
sorts keys, normalizes strings and length-prefixes every value so that two
different structures cannot serialize to the same bytes.
`s0ma.HASH_ALGORITHM_VERSION` is bumped whenever the canonicalization scheme
or the transitive-walk rules change, which invalidates every previously stored
hash by design. A component's registration timestamp and source file are
deliberately excluded from the transitive hash, so two checkouts of the same
commit hash identically.

**Executing examples.** `s0ma examples run` discovers registered examples from
the snapshot and executes each body in an isolated subprocess with a per-example
timeout, routed by `runs_in` to a standalone, pytest or integration handler.
Subprocess isolation is not incidental: an in-body registration would
otherwise contaminate the parent registry. A timeout is represented as a
field of the result rather than as an exception, so a run reports every
example's outcome instead of stopping at the first one that hangs.

The exact symbols, their signatures and the response models behind the REST
endpoints are on
[core's runtime reference](../packages/s0ma-core/docs/references/documentation_subsystem.md),
which is the only place they are written down. What each served capability
*is*, across every channel, is in
[what s0ma can do](reference/surfaces-index.md).

## Level two: the documentation application

Everything above scales to a project's own documents. This repository has a
harder problem: the documentation is *about* four distributions, a command
line, a viewer, two servers and a vocabulary, and no single registry holds all
of that. So the same idea is applied one level up.

`docs/` is a s0ma project. It has a `[tool.s0ma]` table, a
`[tool.s0ma].source_roots` directory holding its authored sources, and a
`[tool.s0ma].build_dir` holding its
committed build — the same shape any other s0ma project has. What makes it the
documentation application is one module, `application`, whose declarations are
the whole of this repository's decisions about its own documentation: which
sources are read, where the composed model goes, and which files get written.
That module is registered, so s0ma knows how it documents itself the same way
it knows anything else about itself.

The composition runs in phases, and the shape matters more than the count:

1. **Read.** Each reading is one adapter over one kind of source. It is handed
   a checkout, it produces records, and every record carries the source it
   came from and the digest of what was read. No reading sees another's
   answer.
2. **Merge.** The readings meet exactly once, in a merge that sorts every
   group before the model is built — so the order the readings ran in cannot
   change what the build says. Compose the same checkout twice and you get the
   same model, byte for byte.
3. **Validate.** The gates run over the merged model. All of them run, on
   every build, collecting rather than stopping at the first finding.
4. **Render.** Every declared output is rendered in memory. Nothing is written
   yet, which is what lets the command that writes files and the command that
   checks them look at the same bytes.
5. **Write, or compare.** `s0ma docs compose` writes what was rendered.
   `s0ma docs check` compares it against what is committed and writes nothing
   at all — there is no path through the checking command on which it opens a
   file for writing.

**Determinism, stated as a rule rather than a hope.** No wall clock, no
network, no randomness, no machine path reaches a rendered byte. Every
artifact is UTF-8 with LF endings and one trailing newline, and every
collection that reaches an artifact is sorted before it gets there. The one
process the build runs is a read of the local checkout's file list.

**Which readings run, which gates run, what the application registers about
itself, and every file it writes** are on
[the documentation application](architecture/docs-application.md) — a page
generated from the build that renders it, so it cannot describe a composition
nobody ran. That page is the reason this one carries no such lists.

*Held by:* `scripts/check_docs_application.py`, the `docs-application` stage
of the repository gate. It composes from scratch in a temporary directory,
byte-compares every rendered artifact against what is committed, composes a
second time to prove the result is stable, rebuilds the committed build from
its sources to prove that tree is what those sources produce, and runs the
whole thing with an offline guard armed so a reading that tried to open a
socket would fail rather than succeed quietly.

## The gates

A gate is a function that takes some part of the composed model and returns
findings. They share three properties worth knowing before you write one.

**They collect; they do not stop.** A build that halted at the first problem
would make somebody fix their documentation one line per run. Every gate runs
on every build and the findings are reported together, sorted, with exact
repeats dropped — two gates asking the same question of one mistake should
produce one finding, not two.

**They take their policy from the caller.** How much a reading should produce,
which source may stay silent about its effects, whether a path's evidence
actually ran, which capabilities the product is *for* — none of those are
facts the machinery can know. They are claims about one repository and one
release policy, so the application passes them in. A gate that supplied its
own policy would be a gate that could never be wrong.

**They never produce the thing they check.** The index gate is handed the
rendered index as text rather than rendering it; the floors are handed to the
floor gate rather than derived by it. A gate that made its own subject passes
by construction and proves nothing, which is the failure mode the whole
initiative exists to eliminate.

Two anti-vacuity ideas run through all of them. A **floor** is an honest
minimum under the live count — a reading that quietly stopped producing is the
failure that matters, and a floor set *at* the count fails the day somebody
writes one more of something. A **refusal** is a renderer declining to render
rather than emitting an empty page: a page of empty tables reads as a product
that has stopped serving something, so the renderer says which reading came
back empty and the build reports being short of its declared set.

Every gate, what it checks, and which reports it can raise are on
[the documentation application](architecture/docs-application.md), read off
the gate functions themselves.

## How a topic is read

One topic reaches a reader through several channels, and the rule is that they
are projections of one composed model rather than four documents that agree by
discipline.

A person opens Markdown in this repository, or asks the command line —
`s0ma docs` for the map, `s0ma docs list`, `s0ma docs show` for one topic, and
`s0ma docs search` for a deterministic search that does not guess. An agent
asks the authoring server, which serves the same topics as resources and tools
over MCP. An installed copy of s0ma-core with no repository in sight answers
from a teaching slice generated here and carried inside its own wheel.

Every one of those channels is offline and deterministic, and every one of
them carries the same identity: the version the answer describes, labelled
with its [release channel](learn/release-channel.md) unless it is a release,
and the digest of the model snapshot it was projected from. A preview build
says so on every surface, which is what stops preview documentation being read
as a released version's.

The copies that leave this project — the served model inside the MCP
distribution, the teaching slice inside core's wheel — are
[mirrors](learn/mirror.md): byte-identical by gate rather than by convention.
A mirror that has drifted from its source is a build failure, not a stale
file somebody notices later.

## Where each fact lives

The one rule this page enforces on itself: a fact is written down once.

| The question | Where it is answered |
| --- | --- |
| What a declaration means, and when to reach for it | [the learning collection](learn/glossary.md) |
| What the language requires of one | [DSL spec §4.12](../packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md) |
| Every line a declaration may carry, and whether it must be written | [the quick reference](reference/quick-reference-readable.md) |
| Every report the toolchain can make, and what to do | [what s0ma can report](reference/diagnostics.md) |
| Every capability s0ma serves, on every channel | [what s0ma can do](reference/surfaces-index.md) |
| The runtime symbols behind the registrations | [core's runtime reference](../packages/s0ma-core/docs/references/documentation_subsystem.md) |
| The readings, gates, registrations and outputs of the application | [the documentation application](architecture/docs-application.md) |
| Every component every distribution registers | [the component index](architecture/component-index.md) |
| What this build was, with a digest per file | `docs/_generated/docs-manifest.json` |
| Every document this repository keeps | [the map of record](README.md) |

This page superseded two others that had been saying parts of the same thing
in two package trees since before the monorepo. Both now point here.
