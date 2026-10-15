# ADR-013: Derived-source provider registry — generalizing `doc-ref covers: { source: <name> }`

**Status:** Accepted — owner-ratified 2026-08-29 at the Phase B gate of
the docs-function initiative (internal plan, not published)
(gate record: `plans/notes/doc-function-b7-report.md` §5 A-1; the §3b scope
escalation — the fix reaches s0ma-core's `DocRefRegistration` and re-stamps
four committed doc-ref artifacts including the MCP self-host set — was
accepted at the same gate)
**Date:** 2026-08-28
**Governing input:** owner decision **D-11** of 2026-08-28 ("derived-source
provider registry: yes, behind an ADR freezing provider purity, provenance,
schema boundaries") and owner decision **D-4** as amended (§2.2 of the same
plan)
**Generalizes:**
[`ADR-010`](../../packages/s0ma-dsl/docs/adr/ADR-010-derived-doc-targets.md)
— the brace form this ADR extends the value space of
**Sibling (also Proposed at the same gate):**
[ADR-012](ADR-012-docs-application.md) — placement, build/output boundaries,
and snapshot semantics of the documentation application. Referenced by path
rather than by link because it is authored in the same wave as this ADR; the
reference becomes a link once both are committed.
**Architecture authority:**
the self-documenting-application architecture plan (internal, not published)
§7.1 (adapter contract), §7.7 (derived-source extension point), §11 (validation
rules)
**Implements no code.** This ADR is text. The code and data changes it
authorizes land at milestone **D7**, and nowhere else.

---

## Context

`doc-ref` has had two `covers:` shapes since 0.12: a bracketed list of filter
expressions over project entities, and the brace form `covers: { source: <name> }`
naming a derived, non-component registry. ADR-010 chose the brace form and said
what it was for. It also said, in its forward pointers, exactly how it expected
to grow: *"Future `covers: { source: <name> }` registrations add to
`_DOC_REF_COVERS_SOURCES` plus a renderer branch"*.

That growth path is the thing this ADR replaces. Verified against the tree at
`b2722b7` (v0.18.1):

1. **One source exists.** `_DOC_REF_COVERS_SOURCES` is a one-element frozenset
   containing `error_codes`
   (`packages/s0ma-dsl/src/s0ma_dsl/parser/s0ma_parser.py:5509`).
2. **Dispatch is a literal string compare in one renderer.**
   `if decl.covers_source == "error_codes":`
   (`codegen/doc_emitter/markdown.py:326`). The `else` branch renders
   `sections:`.
3. **Two renderers have no derived-source handling at all.** `html.py` does not
   mention `covers_source`. `json_format.py` copies the *name* into its payload
   (`json_format.py:177-178`) and then renders `sections:` — which the brace
   form leaves empty. So a `doc-ref` with `format: html` or `format: json` over
   a derived source emits a document as if `covers:` were empty, silently, in
   every strictness mode. Nothing fails; the reader gets a heading, an intent,
   and no content.
4. **`sections:` is required-but-dead for the brace form.** The parser requires
   the field (`s0ma_parser.py:5445`); the derived path never reads it. The one
   in-tree generator authors `sections: []` to satisfy a validator that will
   discard it (`packages/s0ma-dsl/docs/_generators/common_errors.s0ma`).
5. **The derived form contributes nothing to the transitive content hash.**
   `build_doc_ref_registration` does not carry `covers_source`
   (`codegen/doc_emitter/registrations.py:226-240`), and the brace form leaves
   `covers` empty, so the hashed registry snapshot is empty too. The
   consequence is visible in the committed artifact: `common_errors.md`'s
   frontmatter `content_hash` moves when `TRANSPILER_VERSION` moves and **not**
   when the error-code registry it renders changes. The table can be rewritten
   from top to bottom under a stable hash.
6. **Brace-form doc-refs discharge no release-gate coverage.**
   `_doc_ref_covers_nerves` iterates `decl.covers` only
   (`semantic/doc_validator.py:173-183`), so a derived doc-ref contributes zero
   toward `MISSING_PUBLIC_DOC_REF`.

Facts 1–3 are the cost of the per-source renderer branch: each new source is
three edits in three files, and forgetting two of them produces silence rather
than a diagnostic. Facts 4–6 are unfinished edges of the original decision that
a second source would inherit and a ninth would entrench.

The documentation application (ADR-012) needs eight more sources than
`error_codes` — the architecture plan §7.7 names them — and each is backed by a
provider the application already has to build for its own purposes. Nine
copies of a three-file edit, with a silent-failure mode in two of the three
files, is not a growth path. This ADR freezes the registry that replaces it.

---

## Decision

### 1. The registry

A **derived-source registry** maps a source name to exactly one registered
**provider component**. The registry is the single place a source name exists;
the parser's allow-list, the three renderers, and the spec's enumeration all
read from it rather than each maintaining a copy.

```text
name        lowercase snake_case, stable, unique
provider    one registered component satisfying §2 below
formats     the doc-ref formats this source renders in (§4)
schema      the source's own record-schema version (§3)
```

A name means one thing forever. Renaming a source, or reusing a retired name
for different records, is a breaking change: it needs the spec sentence edited
(§5), an amendment to this ADR, and the usual deprecation courtesy to any
consumer project whose `.s0ma` sources name it.

Registration is data plus a component, not a renderer branch. Adding a source
does not touch `markdown.py`, `html.py`, or `json_format.py`.

### 2. Provider purity — the contract, frozen

Every provider is a registered component of the documentation application (or,
for sources derived from the transpiler's own configuration, of `s0ma-dsl`) and
implements the architecture plan's §7.1 adapter contract without exception.
(**Terminology:** the architecture plan says "adapter" in §7.1 and "provider"
in §7.7 for the same thing. This ADR says *provider* throughout, and
`provider_id` below is §7.1's "adapter id". There is one concept, not two.)

```text
input              immutable — the transpiler's own configuration, or an
                   already-composed snapshot handed to the provider by its
                   caller. A provider never goes looking for its input.
output             a tuple of normalized records, sorted by a declared key
records            renderer-independent data. A provider never returns markup,
                   never returns a table, never knows what Markdown is.
provenance         provider id + source identity + schema version + content
                   hash, on every record set (§3)
side effects       none
network            forbidden
filesystem writes  forbidden
filesystem reads   only the immutable input it is handed — never a path it
                   discovers, and never the documentation surface itself
                   (ADR-010's "no docs-on-disk dependency", unchanged)
determinism        two calls, in one process and across processes and across
                   operating systems, produce equal records and equal hashes
errors             structured and source-located; never a partial record set,
                   never an empty one standing in for a failure
```

Two clauses deserve their emphasis because they are the ones a hurried
implementation breaks first:

- **Records, not markup.** The renderer-independence in §4 is only real if the
  provider cannot express presentation. A provider that returns a
  Markdown-shaped string has silently made itself a Markdown-only source, and
  the format declaration becomes a lie the gates cannot detect.
- **Emptiness is a failure, not a result.** A provider whose records resolve
  empty reports it as an error. This is the `DOC_GATE_VACUOUS` class of the
  architecture plan §11 arriving one layer earlier: an empty derived table is
  indistinguishable, in the rendered output, from a source nobody wired up.
  ADR-010 already reasoned this way for the one source that exists — the spec
  records that the source-registry form does not emit `EMPTY_DOC_FILTER`
  because "a 'zero matches' outcome would indicate a structural transpiler bug
  rather than authoring drift". The registry generalizes that judgment and
  gives it a diagnostic instead of a silence.

### 3. Provenance

Every record set carries four fields, and a provider that cannot produce all
four cannot be registered:

| Field | Meaning |
|---|---|
| `provider_id` | The registered component identity of the provider. |
| `source_identity` | What was read — the configuration constant, catalog file, or snapshot id the records came from, precise enough to re-derive them. |
| `schema_version` | The **source's** record-schema version, versioned per source and additive-only within a major. |
| `content_hash` | A hash over the normalized records, not over any rendering of them. |

Three rulings follow.

**3a. `schema_version` here is not the frontmatter's `schema_version`.** The
doc frontmatter field of that name is the IR schema version
(`ir.schema.SCHEMA_VERSION`, `3.0.0` today) and stays exactly what it is. A
source's record schema versions independently. The two must never be conflated
in code, in the spec, or in a rendered artifact.

**3b. The provider's `content_hash` contributes to the doc-ref's transitive
content hash.** This closes the defect recorded as Context fact 5. A derived
`doc-ref`'s hash must move when the records it renders move, or the hash is
decoration. Implementation: `covers_source` and the provider's record hash
reach `build_doc_ref_registration`, and from there the existing
`compute_doc_hashes` path
(`codegen/doc_emitter/content_hashes.py:125-190`). This is authorized at D7.

**3c. Correcting the hash is visibly separate from migrating the source.** D7's
acceptance requires `error_codes` to render byte-identically after migration.
Byte-identical includes the frontmatter, so the migration proof and the
provenance correction cannot both be true of the same diff. They are therefore
two steps in D7, in this order: migrate onto the registry and prove
`docs/_generated/common_errors.md` byte-identical (the records are the same
records); then land 3b, whose entire diff to the committed artifact is the
`content_hash` line. Either step alone is reviewable; combined they would mask
each other. **This refines D7's acceptance wording and belongs on B7's
amendment list.**

### 4. Renderer-format completeness is a registry obligation

A registered source declares which `doc-ref` formats it renders in — a subset
of `{markdown, html, json}`.

- A `doc-ref` whose `format:` is not in its source's declared set is a
  **check-time error in every strictness mode**, reported as
  `DOC_SOURCE_FORMAT_UNSUPPORTED`, naming the source, the requested format, and
  the formats the source does declare. It is never a warning and never a
  degraded rendering, for the reason `DOC_RENDER_ERROR` is already unconditional
  (`s0ma_dsl/config.py:230-235`): a doc that cannot produce its declared output
  is structurally broken, and silently dropping it is precisely the failure mode
  the no-silent-failures rule exists to prevent.
- **Silent-empty output stops being reachable.** All three renderers dispatch
  through the registry. There is no fall-through to the `sections:` path for a
  brace-form doc-ref, so the shape that produces today's empty HTML and JSON
  documents no longer exists. A missing format is a named error; a missing
  source is a parse error, as it is today.
- **The expectation is all three.** Records are renderer-independent by §2, so
  a source that renders in Markdown can render in HTML and JSON by
  construction. A narrower declaration is permitted but is a recorded decision
  with a stated reason in the source's registration, not a default and not an
  oversight. `error_codes` declares all three at migration: closing the
  existing HTML/JSON hole is the point, and grandfathering it as "markdown
  only" would preserve the defect behind a diagnostic.

**Naming boundary.** `DOC_SOURCE_FORMAT_UNSUPPORTED` is a `s0ma-dsl` diagnostic
and follows the DSL's severity-registry conventions, alongside the existing
`DOC_RENDER_ERROR`, `EMPTY_DOC_FILTER`, and `MISSING_PUBLIC_DOC_REF`. The
`DOC_*` codes frozen in the implementation plan §5 for the documentation
application (architecture plan §11) are a **separate set in a shared prefix**.
Neither side may take a name the other has. D7 checks the DSL registry and the
architecture plan §11 table before minting the code.

### 5. Source names are enumerated in the spec — value space only, no syntax

The spec lists the valid source names for the release it describes. This is an
**additive sentence**, and it is the whole of the language surface this
initiative touches for D-11. No grammar, no new field, no new declaration kind,
no new reference namespace — the brace form is already in the language, and the
registry only says which names may appear inside it. This is what owner decision
D-4 (strict, §2.2.4 of the implementation plan) permits and its exact limit.

For the D7 diff to be precise, here is what the spec says **today**
(`packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md` §4.12.1, the current highest
version), verbatim — soft-wrapped here, one line in the source:

> 2. **Source-registry form (added in 0.12, G7a).** A single-key dictionary
>    naming a derived non-component registry the renderer materialises
>    directly. The only registered source today is `error_codes` (the canonical
>    union of `SEVERITY_MATRIX` and
>    `OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`):

There is no standalone enumeration sentence to edit. The value space is stated
in passing, inside the shape's description, in a clause that hard-codes both
the count ("The only registered source today") and the identity of the one
source. D7 replaces that clause with a sentence that names the registry as the
authority and enumerates the names valid for the release, so a future addition
edits a list rather than rewriting a paragraph.

The registered set is release-bound: a `.s0ma` source naming a source that a
given release does not register is a parse error at that release, which is
today's behavior (`s0ma_parser.py:5717`) and stays.

### 6. `sections:` becomes optional for the brace form

`sections:` is required today and dead for derived sources (Context fact 4).
The requirement should end, for the brace form only:

- **Filter form:** `sections:` stays required. Nothing changes.
- **Brace form:** `sections:` becomes optional.
- **An empty `sections: []` on a brace-form doc-ref keeps parsing.** It is the
  exact shape today's rule forces every brace-form author to write — including
  any consumer project that took up ADR-010's forward-pointer invitation to
  render the s0ma error catalogue in its own documentation. Rejecting it would
  break working `.s0ma` sources to tidy a field, which is not a trade this
  initiative is entitled to make.
- **A non-empty `sections:` on a brace-form doc-ref is rejected** with
  `PARSE_ERROR`, in the same exclusivity spirit as the existing rejection of
  mixed `kind:`/`source:` keys. Nobody is forced to write one, and an author
  who does is expecting a rendering that will never happen. Accepting it
  silently is how the dead field became dead in the first place.

The spec already owns the vocabulary for this, so the change needs no new
concept. §4.14.5 classifies `sections` for `doc-ref` as **SR / V,P**
(semantic-required-state). The brace form makes it **SC**
(semantic-conditional-state — "required only when its declaration shape makes
the concept applicable"), which is the spec's own name for exactly this
situation. Three coordinated edits, all in the current spec: the §4.12.1
mandatory-field list, the §4.12.1 sentence that today says "In the
source-registry form `sections:` is unused", and the §4.14.5 declaration-field
table row for `doc-ref`.

**This one touches parser validation** (`s0ma_parser.py:5445`), which the D-4
guard otherwise forbids. It is authorized at **milestone D7 and only there**,
it is a relaxation of a required-field check rather than a grammar change (the
field, its syntax, and its meaning in the filter form are all untouched), and
the existing generator drops its dead `sections: []` in the same commit. Any
other milestone that finds itself editing parser validation for documentation
reasons has left its authorization and stops.

### 7. Release-gate boundary — derived sources are not component coverage

**A brace-form `doc-ref` does not discharge `MISSING_PUBLIC_DOC_REF`, and this
is correct.** Today it happens to be true by implementation accident
(`doc_validator.py:173-183` counts filter-form nerve matches, and the brace form
leaves `covers` empty). From here it is a ruling.

The trap is specific and worth naming, because the registry makes it inviting.
Sources like `cli_commands`, `mcp_surface`, and `rest_surface` will render
tables that *mention* the very components `MISSING_PUBLIC_DOC_REF` asks about.
Someone will notice a release-mode failure, notice that the derived table
already lists the nerve, and wire the derived source in as coverage. Three
reasons that is prohibited:

1. **It answers a different question.** The gate asks whether a PUBLIC nerve
   has documentation that resolves *to that nerve* through the registry. A
   derived table's incidental mention of a name is not that resolution.
2. **It makes the gate vacuous.** Coverage would become satisfiable by pointing
   one doc-ref at an opaque provider. Every PUBLIC nerve in the project passes
   forever, including the ones added tomorrow. That is `DOC_GATE_VACUOUS`
   (architecture plan §11) written as a feature.
3. **The class already has an owner.** Coverage of *surfaces* — CLI commands,
   MCP tools, REST routes, studi0 actions — belongs to the documentation
   application's own gates: `DOC_SURFACE_UNCOVERED` (first version at milestone
   D6), with `DOC_SURFACE_UNBOUND`, `DOC_CONCEPT_UNCOVERED`, and
   `DOC_JOURNEY_UNRESOLVED` beside it. They run over the composed model, which
   knows what a surface is; `MISSING_PUBLIC_DOC_REF` runs over one project's
   registry and knows what a nerve is. Two gates, two questions, no overlap.

The consequence is deliberate and must not be "fixed": a project whose only
`doc-ref` declarations are brace-form still fails release mode until its PUBLIC
nerves are covered by filter-form doc-refs.

### 8. Initial population

`error_codes` migrates first and proves the registry against a source that
already ships. The other eight are the architecture plan §7.7 candidate list.
**None of them exists today.** Each lands with the provider that produces its
records — never earlier, and never before D7 registers the registry itself.

| Source | Records | Provider from | Registers at |
|---|---|---|---|
| `error_codes` | Registered diagnostics: code, per-mode severity, one-sentence description | `s0ma_dsl.config` today; the D2 diagnostics provider later | **D7** (migration; byte-identical body) |
| `document_catalog` | Cataloged documents: id, path, status, authority, audience | C6 | D7 |
| `cli_commands` | `s0ma` commands, options, arguments, side-effect class | D1 | D7 |
| `configuration_fields` | `[tool.s0ma]` fields, types, defaults, validation | D2 | after D2 |
| `package_inventory` | The four distributions: identity, version, dependency direction | C4 | after C4 |
| `mcp_surface` | Tools, resources, prompts, schemas, annotations, approval boundaries | D3 | after D3 |
| `rest_surface` | Core `/self/*` routes: method, path, schema, side-effect class | C3 | after C3 |
| `studi0_surface` | studi0 actions, HTTP surfaces, read/write boundaries | D4 | after D4 |
| `authority_index` | Authority records: class, id, version, status, content hash | C4 | after C4 |

Each addition is still an architectural judgment, exactly as ADR-010 required
of its allow-list: is the source's shape stable enough that derived docs make
sense, and are its records genuinely renderer-independent? What the registry
removes is the *mechanical* cost — three files, two of them able to fail
silently — not the review.

**One sequencing constraint this table imposes.** The implementation plan
schedules D7 as independent after the B gate and parallel with D1–D5, but D7's
own tasks register `document_catalog` and `cli_commands`, whose providers come
from C6 and D1. A registry row cannot precede its provider. Either those two
rows move to a milestone after D1 and C6, or D7 lands the registry plus the
`error_codes` migration alone and the two rows follow. Which of the two is a
scheduling call for the orchestrator, not a decision this ADR makes — but the
constraint is not optional, and it belongs on B7's amendment list beside §3c.

---

## What this ADR does not decide

- **Grammar.** Nothing. Per D-4 there is no new declaration kind, no new field,
  no new reference namespace, and no syntax change. The brace form is
  unchanged; only the set of names valid inside it grows, and only through §5's
  additive spec sentence.
- **Renderer implementation.** Column layouts, HTML structure, JSON key names,
  and how each source's records become each format are D7's business and each
  source's registration, not this ADR's.
- **Where the documentation application lives, what it builds, and what a
  snapshot is.** That is [ADR-012](ADR-012-docs-application.md),
  Proposed at the same gate. This ADR assumes only that providers exist and are
  registered components; ADR-012 says where they live and how they compose.
- **The application-level `DOC_*` names** of architecture plan §11. They are
  proposed there and frozen at their own milestones; §4 above only rules that
  the DSL-side code must not collide with them.
- **Whether `_generators/` survives.** The one in-tree generator is migrated,
  not relocated. If the documentation application later subsumes
  `docs/_generators/`, that is a G- or F-phase decision with its own
  equivalence proof.
- **`ERROR_CODE_DESCRIPTIONS`' home.** ADR-010 decided it is hand-authored in
  `s0ma_dsl.config` and gave three reasons; none of them changes here. A future
  move to the D2 diagnostics provider is a provider-input question, not a
  registry question.

---

## Consequences

- **Adding a derived source becomes a registration, not a renderer edit.** One
  provider component plus one registry row plus one spec name. `markdown.py`,
  `html.py`, and `json_format.py` stop growing a branch per source.
- **Two silent failure modes end.** `format: html` and `format: json` over a
  derived source stop emitting empty documents (§4); a derived doc-ref's
  content hash stops being blind to the records it renders (§3b).
- **One dead field requirement ends** (§6), at the cost of the only parser
  validation change this initiative makes — narrow, named, and confined to D7.
- **The release gate keeps its meaning** (§7). Derived doc-refs never satisfy
  component coverage; the documentation application's own gates cover surfaces.
- **Nine sources become one review each instead of one review plus three
  edits.** The architectural question ADR-010 attached to each new source
  survives intact; only the mechanical tax is removed.
- **D7's acceptance wording gains a step** (§3c): byte-identical migration
  first, provenance correction second, each visible on its own.

---

## Alternatives considered

**A — Keep ADR-010's growth path (allow-list entry + renderer branch per
source).** Rejected on arithmetic and on failure mode. Nine sources is
twenty-seven edits across three files, two of which fail silently when missed —
which is not hypothetical: the HTML and JSON renderers were missed for the
*first* source, in 0.12, and nothing has said so in the six minor releases
since.

**B — One provider, many sources (a single "derived docs" adapter that switches
internally).** Rejected: it moves the string compare from the renderer into the
adapter and gives up per-source provenance, per-source schema versioning, and
per-source format declarations — the three things D-11 gated the ADR on.

**C — Let the documentation application own rendering entirely and leave
`doc-ref` with `error_codes` forever.** Rejected as a duplication of the
mechanism the DSL already has. `doc-ref` is how a s0ma project asks for derived
reference material; a consumer project wanting the s0ma error catalogue in its
own documentation uses the brace form today (ADR-010's forward pointer), and
that capability should widen with the registry rather than fork into an
application-only path a consumer project cannot reach.

**D — Make `sections:` meaningful for derived sources instead of optional** (a
section-per-record or column-selection semantics). Rejected as speculation: no
source in §8 wants it, the shape it would need differs per source, and ADR-010
already parked the "long-form section-per-row renderer" idea as a future
generalisation. If a source ever needs record selection, the brace form takes
additive keys — which is precisely why ADR-010 chose a structural discriminator
over a bare-string sentinel.
