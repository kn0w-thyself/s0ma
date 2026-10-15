# Maintaining the documentation

This is the "what do I do when" page for s0ma's documentation. It answers two
questions and only two: *which file do I edit to add this?* and *this gate just
refused me — what is it asking for?*

It deliberately explains nothing about how the subsystem works. Three other
pages own that, and this page points at them rather than keeping a second copy
that could drift:

| For | Read |
|---|---|
| How the documentation subsystem works — the declarations, rendering, drift, the runtime | [The documentation subsystem](../documentation-subsystem.md) |
| What the application registers, reads, gates and writes, rendered from itself | [The documentation application](../architecture/docs-application.md) |
| Cutting a release, and where documentation sits in it | [Releasing s0ma](../RELEASING.md) |
| The build and verification commands, and which paths are authored | [The repository agent contract](../../AGENTS.md) |
| Setting up, and the check pipeline as a whole | [Contributing to s0ma](../../CONTRIBUTING.md) |

If you arrived here from a red gate, go straight to
[When a gate refuses](#when-a-gate-refuses).

## Contents

- [The loop](#the-loop)
- [What each step is for](#what-each-step-is-for)
- [Adding something](#adding-something)
- [When a gate refuses](#when-a-gate-refuses)
- [Three refusals that mean something other than what they say](#three-refusals-that-mean-something-other-than-what-they-say)

## The loop

Every documentation change runs the same five steps, from the repository root
unless a step says otherwise. Steps 1 and 5 are always needed. Steps 2, 3 and 4
are needed only in the cases the next section names.

```bash
# 1. Compose: rebuild every generated artifact from the sources.
uv run s0ma --project-root docs docs compose --output-dir docs

# 2. Check: byte-compare what you just built against what is committed.
uv run s0ma --project-root docs docs check --output-dir docs

# 3. Mirrors: three wheels carry copies of what compose produced. Refresh
#    all five. The third is what `s0ma docs` reads with no checkout; the
#    last two are the quick reference the authoring server serves.
cp docs/_generated/s0ma-docs-model.json \
   packages/s0ma-mcp/src/s0ma_mcp/_docs/s0ma-docs-model.json
cp docs/_generated/core-teaching-slice.json \
   packages/s0ma-core/src/s0ma/_teaching/slice.json
cp docs/_generated/s0ma-docs-model.json \
   packages/s0ma-dsl/src/s0ma_dsl/_docs_snapshot/s0ma-docs-model.json
cp docs/reference/quick-reference-readable.md \
   packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-readable.md
cp docs/_generated/quick-reference-machine.json \
   packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-machine.json

# 4. Goldens: re-stamp the rendered fixtures. From packages/s0ma-dsl.
uv run python - <<'EOF'
import sys
sys.path.insert(0, "tests")
import test_docs_resolve_render as t
for name, text in t.golden_texts().items():
    (t.GOLDEN_DIR / name).write_bytes(text.encode())
EOF

# 5. The gate.
uv run python scripts/check.py
```

Before step 5, run `git add -A -N` if you created files. Several gates ask git
what the corpus is, and a file that exists only in your working tree is a file
they cannot see — which is also true of everyone who clones the repository
after you.

## What each step is for

| Step | Run it when | Skip it when |
|---|---|---|
| 1. Compose | Always. Anything that changes what the build composes changes the snapshot digest, and every generated page carries that digest. | Never. |
| 2. Check | You want the answer before the full gate does. It is the same comparison the `docs-application` stage makes, in about a second. | Never harmful; it is the cheapest check you have. |
| 3. Mirrors | Compose changed `docs/_generated/s0ma-docs-model.json`, `docs/_generated/core-teaching-slice.json`, or the quick reference in either form. In practice: almost any change at all, because the snapshot digest moves and the quick reference carries it. Four artifacts, five copies: the snapshot is mirrored into both the mcp and the dsl package, and the quick reference's page and data twin into the mcp package, which serves them. | Only when compose left all four artifacts byte-identical. `git status` tells you. |
| 4. Goldens | You changed a renderer, a resolver, or the prose of a topic a golden fixture captures. | You only added or edited a document, a catalog row or a ledger row. |
| 5. The gate | Always, before you hand the work on. | Never. |

The order is not decorative. Mirrors are copies of what compose produces, so
copying before composing copies the previous answer; goldens are stamped from
the renderers, so stamping before composing stamps the old render.

## Adding something

Six acts, six recipes. Each one names the files you edit; the loop above is
what you run afterwards.

### A document

Two files, both hand-maintained, and the gates check them against each other.

1. Write the page. Anywhere under `docs/`, with `#`-style headings — the link
   checker reads those and nothing else, so an underlined heading gets no
   anchor and every link to it is reported dead.
2. Add a row to `docs/s0ma_src/catalog.json`, in the `documents` list, sorted
   by `id`. The `id` category and the `status` must agree with each other; the
   loader names both halves when they do not. Copy the shape of a neighbouring
   row rather than composing one from the field list.
3. Add a row to `docs/s0ma_src/doc-classification.json`, sorted by `path`, and
   record it in the human summary beside it. Its `audience` must be one of the
   audiences the catalog row lists.
4. `git add` the page. Until you do, the completeness gate cannot see it, and
   the ledger gate cannot either.

The catalog row is what makes the page a document; the ledger row is what
records the judgment about it. Every tracked Markdown file needs both, and the
two gates below check the set both ways, so adding one without the other fails.

### A concept

Concepts are declared as data, not prose, and their pages are rendered from
that data. You edit one of two files under `docs/s0ma_src/concepts/`, chosen by
domain: the language file for words the DSL defines, the product file for words
the product defines. Each is pinned to the document that governs it, so a
concept's authority is a citation rather than an assertion.

Adding one adds a page to the learning collection. You do not write that page,
and editing it by hand loses the edit at the next compose — it is one of the
generated artifacts, so the count the check reports goes up by one and the new
page is committed alongside the declaration that produced it.

Two fields carry more weight than they look. `term` is the word a reader
meets, and it is what a guide's coverage claim is matched against, so it is
load-bearing beyond its own page. `related_concepts` edges must resolve, and a
symmetric relation declared from one end only is reported as one-sided rather
than quietly accepted.

The [subsystem guide's declaration section](../documentation-subsystem.md#level-one-the-three-declarations)
is where the shapes are written down.

### A surface

You do not add surfaces. A surface is what the build finds when it reads the
command tree, the served tools and resources, and the registered components —
so a new command or a new tool becomes a documented surface by existing, and
the reference pages that list them are rendered from that reading.

What you have to do is rule on it, in two places, and the gate will ask you for
both:

- **Binding.** Name the components that implement it, or write the exception
  saying why its facts were transcribed by hand. An unbound surface with no
  written exception is refused.
- **Coverage.** Classify it in `docs/s0ma_src/coverage-policy.json` — either
  into the surfaces of the primary capability it belongs to, or into the
  reference-only ledger with the reason it is not a capability any journey has
  to teach. The refusal here asks for a decision, not a page.

Both ledgers are printed on every run, with their ceilings, so the cost of an
exception is visible rather than absorbed. The
[drift section](../documentation-subsystem.md#how-drift-is-caught) explains
which ledger is which.

### A journey

A journey is a capability taught as an executable sequence, and its evidence is
replayed rather than described. Two files: the journey under
`docs/s0ma_src/journeys/`, and the transcript its steps are checked against
under `docs/s0ma_src/evidence/`. A journey with no evidence is reported as
untested, so the second file is not optional.

Order matters inside the declaration. The concepts a journey teaches are an
ordered list, and teaching one before the concept it rests on is refused —
either move it later or declare it as required rather than taught. A step that
walks into an approval also has to say what the person is approving.

Approval is a rule, not a list: a journey is approved for a package when a
catalog document covers it. This is why a journey can be complete and correct
and still emit no package — covering it would produce a package with nothing to
edit.

### A coverage claim on a guide

A `covers:` entry is a claim that a document teaches a topic, and every entry
must resolve to something the build actually composes. There are two shapes,
and the [subsystem guide separates them](../documentation-subsystem.md#the-two-shapes-of-covers).

Claims made by a living guide are bound by a derivation rule rather than by a
hand-kept list: the claim has to be **earned by the prose**. A concept claim is
legal when the page uses that concept's own `term`; a surface claim is legal
when the page names the surface as it is really called. Teaching the idea
beautifully without ever using the word is an illegal claim, and it is caught.

So a claim on a living guide is two edits, and the gate compares them in both
directions — a catalog row without a binding is a claim nobody weighed, and a
binding without a row is a gate about nothing:

1. Add the id to the row's `covers` in `docs/s0ma_src/catalog.json`.
2. Add it to that guide's entry in
   `packages/s0ma-dsl/tests/test_docs_guide_bindings.py`, sorted, under a
   comment saying why the group belongs.

If the teaching lives in a test rather than in the page,
[coverage credit for tests that live elsewhere](../documentation-subsystem.md#coverage-credit-for-tests-that-live-elsewhere)
is the mechanism for saying so.

### A change to the language

[The quick reference](../reference/quick-reference-readable.md) lists every
line of every kind of declaration, and it is generated: the lines, whether each
must be written, and the words a line chooses from are read from the language
itself. What a person writes is the explanation beside each one, and all of it
is in one file, `docs/s0ma_src/quick-reference.json`. You never edit the page,
and you never edit its twin for programs,
`docs/_generated/quick-reference-machine.json`.

The build holds that file to the language in both directions, so after a
change to the language it tells you what it is missing. Each refusal names the
entry:

| The language gained or lost | Edit, in `quick-reference.json` |
|---|---|
| A line on a kind of declaration | That kind's `lines`: one entry per line, in the order a person would write them. `type` is one of the words under `types`. |
| A word a line chooses from | That set's `values`, under `choices`. |
| A kind of declaration | `kinds`, and the concept that says what the kind is for — see [a concept](#a-concept). |
| A strictness mode | `modes`. |
| A command the page names, or one of its options | `commands`. The command line is checked against the real one, option by option. |

Then say what changed. The newest entry under `editions` pins what the
language accepted when it was written, so once the language moves the build
refuses until there is a new edition: a date, a sentence or two for the
reader, and the `facts` the refusal prints for you to paste. That list is the
page's own changelog, which is why it cannot be skipped.

The samples on the page are cut from one small project kept in the same file,
under `sample`, one list entry per line of each file. The build parses and
validates every one of those files at release mode before it writes the page;
`packages/s0ma-dsl/tests/test_docs_quick_reference.py` then writes the project
out, builds it, and runs its tests and its example. A line added to the
language as one that must always be written has to be added to every sample
declaration of that kind, exactly as it would to any other source.

## When a gate refuses

Two different things can refuse you, and they read differently.

**The composition gates** report a `DOC_`-prefixed code. They run inside
compose and check, all of them on every build, and the report is collected
rather than stopped at the first finding — so one run tells you everything that
is wrong instead of one thing per run. Every finding names the source location
that caused it and states its own remediation; the message is the instruction,
and it is written to be sufficient without this page.

Which gate reports which code is
[a table on the application's own page](../architecture/docs-application.md#the-gates),
rendered from the gates themselves. That table is the map of record and this
page does not copy it — a second copy is exactly the drift this subsystem
exists to prevent. What is worth knowing here is which of your edits a refusal
is pointing at:

| You were | A refusal here is about |
|---|---|
| Adding or moving a page | Its catalog row, or the ledger row that must match it. Also: a page can be tracked and uncataloged, which is a different failure from a row whose file does not exist. |
| Adding a concept | Its relations — an edge to a concept the build does not compose, or a one-sided relation — and its prose fields, which are voice-checked. |
| Adding a command, tool or resource | Coverage and binding: a served capability must be covered by something, or carry a written exception. The refusal asks for a decision, not a page. |
| Adding a journey | The four rules a journey satisfies beyond resolving, including whether it is taught in an order that works and whether its steps are tested. |
| Claiming coverage | Whether the claimed id resolves to something this build composes. |
| Changing the language | The quick reference. Its two outputs are refused together, and the refusal names the entry of `docs/s0ma_src/quick-reference.json` that no longer matches the language — see [a change to the language](#a-change-to-the-language). |
| Editing served prose | The voice rules, and the size budget for the channel the answer is served on. |

**The pipeline stages** report no code at all — they are separate scripts, and
they fail in their own words. These are the ones a documentation change meets
most often:

| Stage | What it refuses |
|---|---|
| `docs-application` | The committed artifacts are not what the sources compose. Almost always compose step 1, not run. |
| `docs-links` | A relative link naming an untracked path, or an anchor naming no heading. It prints the nearest real headings for a miss. |
| `docs-version-currency` | A stale version in a page that describes the current release, or the four distributions out of step with each other. |
| `authored-lines` | An `intent`, `guarantees`, `invariants`, `schema` or `forbids` line in a `.s0ma` source, fixture or spike fixture, or in a registration written in Python (`@component`, `ComponentSpec` or `Contract` under `packages/*/src`), that names a milestone, a run, a plan, a date or a ruling, or that cites a requirement, an invariant, an ADR, a revision or a section that does not resolve. It prints the line and the three answers. |
| `spelling` | The letter-o spelling of the product name, anywhere in the tree. |
| `selfhost-build` | The packaged copies inside the wheels are not the artifacts they mirror — or a cold install cannot answer `s0ma docs`. Usually mirror step 3, skipped. |

Run one on its own with `uv run python scripts/check.py --only <stage>`, and
`--list` to see them all. [The check pipeline](../../CONTRIBUTING.md#the-check-pipeline)
covers the stages that are not about documentation.

## Three refusals that mean something other than what they say

**"This generated page has drifted" — on a page you never touched.** Every
generated page carries the snapshot digest, so any change to what the build
composes rewrites all of them. This is compose step 1 not having been run, or
having been run before the last edit. Re-run it and commit what moves.

**"The packaged model has drifted from the composed one."** This is mirror step
3, skipped. The five `cp` commands are the whole fix, and each refusal names
the one it needs — the two quick-reference copies are refused by the same
drift gate as the other packaged documents, and by the release check. It is worth knowing why the copies exist rather than being
generated in place: the wheels have to carry their documentation without the
repository, and the
[teaching-slice build order](../RELEASING.md#the-teaching-slice-build-order)
explains the circularity that ordering avoids.

The third copy is the newest, and it is there because its absence was invisible
for four milestones. The snapshot went into the `s0ma-mcp` wheel, where the MCP
resources read it, and a teaching slice into `s0ma-core`; the `s0ma-dsl` wheel —
the one carrying the command line — got nothing, so `s0ma docs`, `docs list`,
`docs show` and `docs search` answered every installed person "no documentation
snapshot was found" while answering a contributor perfectly. Every gate in this
repository ran inside a checkout, and a checkout was the one place the gap did
not show. Two things now close that: the dsl mirror gate, which fails the way
the other two do, and `selfhost-build`, which runs `s0ma docs` from a cold
install outside any checkout.

**"A version reference is stale" — in a page you did not edit.** The living
docs are checked against one lockstep version, so a release bump makes every
page that names the old version fail at once. Each hit has exactly three
legitimate answers and the failure prints all three: update it, reword it so it
names no version at all, or record it as deliberately historical with a written
justification. Prefer the second wherever the sentence allows — a page that
names no version can never go stale.
