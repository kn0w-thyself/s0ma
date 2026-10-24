# Documentation corpus classification — human summary

> **This is the public export's copy.** Entries for documents the public
> repository does not carry have been removed from the machine ledger beside
> it, and the disposition counts in §1 have been restated from what is left.
> The narrative after §1 describes the full internal corpus as it grew, so its
> ordinals ("the 229th row") count documents this repository does not have.
> Nothing else about it has been changed.

Companion to [`doc-classification.json`](doc-classification.json) (schema
`doc-classification@1`), produced at milestone **A6** of the doc-function
initiative (`plans/complete/s0ma-doc-function-1.md`, an internal working note).

Both files lived under `plans/notes/` until beta-prep-5-front-door moved them
here. They are a gate input — step 3 of [adding a
document](../operations/docs-maintenance.md#a-document), and three test modules
read them — and a gate input must not sit inside a directory the public export
withholds, which is where every other gate input already is.

The JSON is the machine artifact: one row per tracked Markdown file, exactly one
disposition from the enum frozen in the plan's §5, plus an optional audience and
note. It seeds the C6 document catalog and doubles as the migration map for
Phase G's consolidation. This file is the readable half — the counts, the
mapping back to the audit's eight locations, and the full archive ledger.

**Classified against the tree on branch `doc-function-1` at 2026-08-28**, after
milestones A1–A3 landed their banners, moves, and pointer stubs.

Coverage *was* enforced mechanically by
`packages/s0ma-dsl/tests/test_doc_classification_ledger.py`, the temporary guard
A6 wrote for the purpose. **Milestone F2 retired it**: the document catalog
(`docs/s0ma_src/catalog.json`) is now the live classification, and the
`docs-application` stage refuses a tracked Markdown file the catalog has no row
for — the same rejection, on the same input, proved against one fixture corpus
in `packages/s0ma-dsl/tests/test_docs_map_of_record.py` before the guard was
deleted. What the catalog does not carry, this file still does: the disposition
enum frozen in the plan's §5, the mapping back to the audit's eight locations,
and the archive ledger below. It is the A6 classification record and Phase G's
migration map; the catalog is what the build reads.

---

## 1. The dispositions

| Disposition | Meaning | Count |
|---|---|---|
| `normative-current` | Binding today. The PRD, the current DSL spec, the current core spec, accepted ADRs, frozen contracts, and the repo agent contract. | 25 |
| `living-authored` | Hand-written and actively maintained. Guides, READMEs, runbooks, the changelog. | 47 |
| `generated` | A rendered output of a generator or the s0ma build. Never hand-edited. | 60 |
| `mirror` | A byte-for-byte copy of another file in this repo, kept honest by a gate. | 9 |
| `historical` | A record of the past. Kept for provenance; must not be read as current guidance. | 14 |
| `superseded-pointer` | A short stub whose only content is "this moved — go here". | 11 |
| `working-plan` | Plans, notes, and review records: those under `plans/`, this summary beside the ledger it explains, and the result records of the B-phase spikes under `scripts/spikes/`. | 1 |
| `non-documentation` | A `.md` file that is test data or test scaffolding, not part of the documentation corpus. | 4 |
| **Total** | | **171** |

158 files were tracked at Phase A finalization (the walkthrough pointer stub added at the A5-findings pass is the 156th, and A7's two tester documents — `docs/troubleshooting.md` and `docs/uninstall.md` — are the 157th and 158th); the 159th row was this summary, which the ledger
classifies in advance of its own commit.

Phase B adds one row per ADR it authors, each `normative-current` and each
carrying its Proposed status in the note until the B7 owner gate rules on it:
`docs/adr/ADR-013-derived-source-registry.md` (B2) is the 160th and
`docs/adr/ADR-012-docs-application.md` (B1) the 161st. It also adds one row per
spike that records its results, `working-plan` like the plans they serve:
`scripts/spikes/docs_model/spike_b1_layout/README.md` (B1) is the 162nd and
`scripts/spikes/docs_model/spike_b3_inventory/README.md` (B3) the 163rd. B4
records its results in two files rather than one, so it adds both:
`scripts/spikes/docs_model/spike_b4_schemas/README.md` is the 164th and
`scripts/spikes/docs_model/spike_b4_schemas/DEFERRED.md` — the deferred-field
account the milestone requires — the 165th. B5 records its results in one file,
`scripts/spikes/docs_model/spike_b5_channels/README.md` — the 166th. B6 records
its results in two, so it adds both:
`scripts/spikes/docs_model/spike_b6_discovery/README.md` is the 167th and
`scripts/spikes/docs_model/spike_b6_discovery/VERDICT.md` — the one-page D-4
ergonomics verdict the milestone requires — the 168th. B7 adds its spike record,
`scripts/spikes/docs_model/spike_b7_journeys/README.md` (the 169th), and one row
that is not a spike: `plans/notes/doc-function-b7-report.md` (the 170th), the
Phase B gate document itself, `working-plan` like every other record under
`plans/notes/`. Those
spike rows leave the ledger when their spike does — promoted at C1 or deleted
at the B gate.

Phase E adds the five journey guides — `docs/getting-started/first-project.md`, `docs/guides/first-module.md`, `docs/guides/mcp-authoring.md`, `docs/guides/drift-recovery.md`, and `docs/guides/studi0-feedback.md` — all `living-authored`, each bound to its journey through the catalog and byte-consistent with its transcript evidence.

Phase D adds the first Markdown the documentation application itself renders:
`docs/reference/concepts-index.md` and `docs/reference/surfaces-index.md` (D6),
both `generated` and both byte-gated by `s0ma docs check` rather than by a
person remembering to re-run anything.

Phase F adds `docs/README.md` (F2), the map of record: `generated`, rendered by
the documentation application from the catalog, and the page that closes the
audit's "there is no index" finding. Milestones F3–F5 then add the other
forty-six `generated` rows in one wave — the seven reference pages
(`docs/reference/cli.md`, `configuration.md`, `diagnostics.md`, `mcp.md`,
`studi0.md`, `packages.md`, and `docs/architecture/component-index.md`, which
succeeds the stale hand-maintained architecture document) and the thirty-nine
pages of the learning collection under `docs/learn/`, one per concept plus the
public glossary and the anatomy page — taking `generated` from ten rows to
fifty-six and making it the second-largest disposition in the corpus, which is
the shape a self-documenting repository is supposed to have. It is also two
rows for one page.
`docs/reference/documentation-application.md`
(F1) is `generated`: the `doc-ref` render of the documentation application's own
public surface, which is what let `docs/pyproject.toml` raise its mode to
`release`. `docs/_built/reference/documentation-application.md` is the
byte-identical copy a project build writes into the build directory, and it is
`non-documentation` rather than ruling 8's `mirror` — a mirror is a copy somebody
reads, and ADR-012 §1 addition 2 records this class of copy as a build artifact
that is never linked and never read. Cataloging it would oblige the F-phase map
of record to list a page nobody should open, which is ruling 10's test.

Phase G moves four rows between dispositions, adds six, and relocates
thirty-seven more without reclassifying any of them. The paragraphs below run
in landing order, which is not milestone order — G7 landed before G3 — because
the counts chain. **G2** resolved the user-guide fork
(audit §4, July DOC-2) by merging both full copies into
`packages/s0ma-core/docs/s0ma_user_guide.md`, which therefore stops being a
fossil and becomes `living-authored`; the dsl copy and the condensed
abridgement become `superseded-pointer` stubs naming it. Net:
`living-authored` 35 → 34, `historical` 51 → 50, `superseded-pointer` 6 → 8,
total unchanged. The condensed variant was **retired rather than folded** —
see ruling 6 below for why the fold was the wrong half of the choice.

**G7** added the 229th row and Phase G's only wholly new authored document:
`docs/trust-model.md`, `living-authored`, the consolidated trust note the July
review (GAP-1) and the August audit (§7 item 8) both recorded as missing.
`living-authored` returns to 35. It is the one Phase-G document that could not
be a move, because nothing in the corpus held the content: ADR-002 covers a
single boundary, the feedback contract covers a single path, and the rest of
the trust model existed only as gates nobody had written down for a reader.
Catalog kind `guide` rather than `operations` — it prescribes no procedure, and
`operations` is the kind this corpus reserves for runbooks (`RELEASING.md`,
`troubleshooting.md`, `uninstall.md`). Its `covers` names concepts only, which
puts it in *Understand s0ma* on the map of record under
`map_of_record.category_of` rule 5: a reader deciding whether to trust s0ma is
reading before adopting, which is what that section is for.

**G3** executed the OP-4 rotate+pin ruling on core's documentation posture and
emptied §3.4 below. It adds the 230th row — a current core spec,
`packages/s0ma-core/docs/s0ma-core-spec-v0.18.1.md`, `normative-current`
(`normative-current` 22 → 23) — and retires two documents that had been reading
as current. `architecture.md` becomes a `superseded-pointer`
(`living-authored` 35 → 34, `superseded-pointer` 8 → 9): July DOC-1 is closed
by retirement rather than by generation, because the two surfaces that replace
it are already generated and already gated, and a third hand-maintained
narrative of the same facts was the defect being fixed, not a thing to rebuild.
The v0.2.0 spec and `references/documentation_subsystem.md` keep their
`historical` disposition and gain the banners they never had — the second of
them by withdrawing a promise of regeneration that nothing was going to keep,
which is a smaller act than writing the replacement and a more honest one than
leaving the promise standing. Net: total 229 → 230.

**G5** archived the two pre-monorepo plan trees — the thirty-seven rows of
§3.5, nineteen from `s0ma-core` and eighteen from `s0ma-dsl` — moving them from
`packages/<pkg>/plans/` to `docs/archive/pre-monorepo/<pkg>/plans/`. Every one
keeps its `historical` disposition and its catalog id: a fossil does not change
what it is by being filed correctly, and the ids were derived from filenames
precisely so a move would not churn them. It adds four rows. Two are the
tombstone notes at the archive destinations,
`docs/archive/pre-monorepo/s0ma-core/README.md` and its `s0ma-dsl` twin, both
`living-authored` for the reason `docs/archive/0.9.0/README.md` is: a note that
says "everything beside me is frozen, and here is what replaced it" is a
maintained document about the archive, not a piece of it (`living-authored`
34 → 36). Two are pointer stubs at the retired roots,
`packages/<pkg>/plans/README.md`, `superseded-pointer` like every other stub in
§3.1 (9 → 11). Net: total 230 → 234.

The trees kept their `plans/` directory level inside the archive rather than
being flattened into it, and that is load-bearing rather than cosmetic. Two
gates carve out directories **named** `plans` at any depth — the INV-1 spelling
guard in `scripts/check.py` and the link guard in `scripts/check_links.py` —
because a frozen plan quotes the pre-rename spelling and links the tree as it
was. Flattening would have exposed 1,815 spelling violations across twenty
files and every dead link in the two `TODO.md`s, and the only way back would
have been a tree-sized gate exception. Keeping the directory name kept both
carve-outs, and cost no gate edit at all.

**Phase H** adds one row, and it is the phase's only Markdown: `H4`'s
`plans/notes/doc-function-h4-handoff.md`, the 235th — `working-plan` like every
other record under `plans/notes/`, and `owner` for its audience like the two
other gate documents this initiative wrote (`doc-function-b7-report.md` at the B
gate, `doc-function-g1-prd-amendment.md` at G1). It is the publication handoff the
owner accepts at the H gate. Net: `working-plan` 45 → 46, total 234 → 235.

Phase H's other outputs add no rows at all, and that is the rule rather than an
accident: they are machine artifacts under `docs/_generated/` — the documentation
manifest (H1) and the five media packages (H3) — and the catalog's corpus is
tracked Markdown, so `_generated/` JSON is outside it by ADR-012 §2.3 rule B-2.
They are bound by the manifest and the byte gate instead of by a catalog row; the
handoff's §7.3 records the convention and its pointers.

Phase I adds two rows and moves two, and the four are one migration. I1 adds
`docs/architecture/docs-application.md`, the 236th — `generated`, and the page
architecture M7 asks for: the documentation application's account of its own
readings, gates, registrations and outputs, rendered from the build that
renders it and byte-gated by `s0ma docs check` like its neighbour the component
index. It adds `docs/documentation-subsystem.md`, the 237th —
`living-authored`, the self-hosted guide that ends the two-package split, with
its coverage bound under G6's derivation rule and pinned in
`packages/s0ma-dsl/tests/test_docs_guide_bindings.py`. The two moves are the
pages it supersedes: `packages/s0ma-dsl/docs/references/documentation_subsystem.md`
was `living-authored` and is now `superseded-pointer` (its teaching moved
whole), and `packages/s0ma-core/docs/references/documentation_subsystem.md` was
`historical` and is now `superseded-pointer` — a stub *plus* the roster of core
symbols no generated page carries, which is why it reduces rather than empties.
Net: `generated` 56 → 57, `living-authored` 36 → 37 → 36 (one gained, one
moved out), `historical` 50 → 49, `superseded-pointer` 11 → 13, total 235 →
237.

I3 adds the 238th and last, `docs/operations/docs-maintenance.md` —
`living-authored`, `contributor`: the maintenance runbook, the "what do I do
when" page that I1's subsystem guide deliberately is not. The two sit either
side of one line: the guide explains how the documentation subsystem works, the
runbook says which file you edit and what the refusal you just read is asking
of you. It is the initiative's only new authored page outside the journey
guides, and it is written to point rather than restate — the release cut stays
`docs/RELEASING.md`'s, the build commands stay `AGENTS.md`'s — so it holds no
inventory that can rot out from under it. It also opens `docs/operations/`,
which had no occupant before.

I3 adds the 239th and genuinely last, `plans/notes/doc-function-i3-completion.md`
— `working-plan`, `owner`, the fourth and final gate document of this
initiative after `doc-function-b7-report.md`, `doc-function-g1-prd-amendment.md`
and `doc-function-h4-handoff.md`, and the one the I gate is read against. Net:
`living-authored` 36 → 37, `working-plan` 46 → 47, total 237 → 239.

The beta-release-prep branch (2026-09-17) adds nine rows, all `working-plan`:
the five `plans/s0ma-beta-prep-*.md` documents (four implementation plans for
`contributor` readers and the merchant-of-record decision brief for the
`owner`), and four notes beside them — `beta-prep-owner-actions.md` and
`merchant-of-record-research-17SEP2026.md` (`owner`),
`claude-integration-research-17SEP2026.md` and `retrofit-friction-log.md`
(`contributor`). Net: `working-plan` 47 → 56, total 239 → 248. Later rows
from the same branch are recorded in the ledger itself and counted in the
table above; this summary is not amended per note.

Milestone A2 of `plans/s0ma-beta-prep-5-front-door.md` adds the three community
files a public repository needs, all `living-authored`: `SECURITY.md` (`user`),
`CODE_OF_CONDUCT.md` (`contributor`) and `.github/PULL_REQUEST_TEMPLATE.md`
(`contributor`) — the first tracked Markdown under `.github/`, which the
completeness gate reads like any other path because its corpus is every tracked
`.md` file from the repository root. The three issue forms beside it are YAML,
so they are not documents this ledger classifies. Net: `living-authored`
45 → 48, total 265 → 268.

Milestone B1 of the same plan adds one `living-authored` row: `docs/stability.md`
(`user`), the stability statement — what a pre-1.0 s0ma promises, what it does
not, and how a change is announced. It is a living guide with declared coverage,
so it also joins `LIVING_GUIDES` and `BINDINGS` in
`packages/s0ma-dsl/tests/test_docs_guide_bindings.py`, where its seven claims are
weighed against its prose. Net: `living-authored` 48 → 49, total 268 → 269.

The quick reference (2026-09-29) adds one `generated` row,
`docs/reference/quick-reference-readable.md` (`user`): every kind of
declaration and every line each may carry on one page, rendered by the
documentation application from the language the check enforces and from the
explanations authored in `docs/s0ma_src/quick-reference.json`. Its twin,
`docs/_generated/quick-reference-machine.json`, is the same facts as data and
is not Markdown, so it takes no row. Two `working-plan` notes (`owner`) record
the work: `plans/notes/quick-reference-landing.md` and
`plans/notes/quick-reference-findings.md`. Net: `generated` 59 → 60,
`working-plan` 74 → 76, total 281 → 284.

The quick-reference correction of 2026-09-29 adds one `living-authored` row:
`docs/guides/what-the-build-writes.md` (`user`), the guide to the build's
outputs — what each file `s0ma build` writes is for, who reads it, and why
none of them is edited by hand. It is a living guide with declared coverage,
so it also joins `LIVING_GUIDES` and `BINDINGS` in
`packages/s0ma-dsl/tests/test_docs_guide_bindings.py`, where its six claims are
weighed against its prose. Net: `living-authored` 50 → 51, total 284 → 285.

Serving it (2026-09-29, evening, the owner's ruling that an agent in somebody's
project must be able to reach every reference) swaps one `mirror` row for
another: `packages/s0ma-mcp/src/s0ma_mcp/_docs/s0ma-dsl_quick_reference.md`
leaves, because the older DSL quick reference is no longer served at
`s0ma://guide/quick-reference`, and
`packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-readable.md`, the wheel's
byte-exact copy of the generated page, arrives at that address. The data twin
is served too, as `s0ma://guide/quick-reference.json` from a copy beside it;
both the twin and its copy are JSON and take no row here, though the catalog
holds both (the mirror rule requires a served copy's original to be a cataloged
document), which is why `packages/s0ma-dsl/tests/test_docs_provider_catalog.py`
names them beyond this ledger. The older document's own `living-authored` row
stays until what it holds that no other reference does has been placed. Net:
no count moves — `mirror` 9 → 9, total 285 → 285.

Retiring it (2026-09-29, the same evening, the owner's ruling that the older
document "may now be obsolete") removes that `living-authored` row,
`packages/s0ma-dsl/docs/s0ma-dsl_quick_reference.md`. Each of its nineteen
sections was read against the generated quick reference, the language
specification, the learning pages, the generated references and the patterns
guide; what only it held was placed first (the account, section by section, is
in `plans/notes/quick-reference-landing.md`). Net: `living-authored` 51 → 50,
total 285 → 284.

Cutting core's specification at 0.19.0 (2026-10-05, the owner's ruling "cut
the core spec at 0.19.0": core's specification is pinned to the package's own
version, and the version rolled) adds one row and moves one.
`packages/s0ma-core/docs/s0ma-core-spec-v0.19.0.md` arrives as
`normative-current` and takes over the current-spec row, and
`packages/s0ma-core/docs/s0ma-core-spec-v0.18.1.md`, the cut it restates,
becomes `historical`, kept under its own name with a banner naming its
successor. Net: `historical` 49 → 50, `normative-current` 23 → 23, total
289 → 290.

Cutting core's specification at 0.19.1 (2026-10-09, the bug-fix release that
makes the self-model read HEALTHY for applications with CONSTANT and TYPE
cells) does the same once more: `packages/s0ma-core/docs/s0ma-core-spec-v0.19.1.md`
arrives as `normative-current` and takes over the current-spec row, and
`packages/s0ma-core/docs/s0ma-core-spec-v0.19.0.md` becomes `historical`,
bannered, under its own name. Net: `historical` 50 → 51, `normative-current`
unchanged, total up by one.

The plan for authored lines that stand on their own
(`plans/s0ma-durable-authored-lines-1.md`, commissioned by the owner
2026-10-05 as a required to-do, to run after `forbids-field-1` ships) adds
one `working-plan` row. Net: `working-plan` 81 → 82, total 290 → 291.

The plan for the `forbids` line (`plans/s0ma-forbids-field-1.md`) and its
working notes (`plans/notes/forbids-field-notes.md`, the site map and
hand-offs its milestones share) add two `working-plan` rows. Net:
`working-plan` 82 → 84, total 291 → 293.

The decision on record for the `forbids` line
(`docs/adr/ADR-014-the-forbids-line.md`, accepted by the owner's ruling of
2026-09-30) adds one `normative-current` row. Net: `normative-current`
23 → 24, total 293 → 294.

The working notes of the plan for authored lines that stand on their own
(`plans/notes/durable-authored-lines-notes.md`, the read list, the resolution
inventory and the hand-offs its milestones share) add one `working-plan` row.
Net: `working-plan` 84 → 85, total 294 → 295.

The second round of the plan for authored lines that stand on their own
(`plans/s0ma-durable-authored-lines-2.md`, commissioned by the owner
2026-10-06 as the first round's follow-up card: the authored lines written
in Python, and the spike fixtures) adds one `working-plan` row. Net:
`working-plan` 85 → 86, total 295 → 296.

The build gate and the environment a wheel is built in add two rows. The
packaging guide (`docs/guides/packaging.md`, `user`) is `living-authored`: the
build hook, the isolated build environment and the check baseline, an editable
install against a wheel, the two build directories, and locating the build at
runtime; its two listings are run by `packages/s0ma-dsl/tests/test_docs_packaging_guide.py`,
and it joins `LIVING_GUIDES` and `BINDINGS` in the guide-bindings suite. The
decision on record for the gate (`docs/adr/ADR-015-build-without-runtime-packages.md`,
proposed with the pull request that implements it) is `normative-current`.
Net: `living-authored` 46 → 47, `normative-current` 24 → 25, total 169 → 171.

`audience` is advisory and single-valued (the primary reader): `agent` (coding
agents), `user` (people using or evaluating s0ma), `contributor` (whoever works
in this repo — human or agent), `owner`, `machine` (consumed by code, read by
nobody).

---

## 2. The audit's eight locations, mapped

Locations are from `docs-audit-28AUG2026.md` §2. "Dispositions found" lists what
actually landed there, most-common first.

> **These tables are the Phase A snapshot and are left as one.** They describe
> 158 rows classified on 2026-08-28 and are the record of what the audit's eight
> locations held at that moment; later phases append to §1's narrative rather
> than rewriting them. For what has moved since, read §1 from "Phase B adds"
> onward. G2 in particular moved three rows between locations 3 and 4, and
> **G5 emptied location 6 of its 37 `historical` rows**: the two legacy
> `packages/*/plans/` trees now sit under `docs/archive/pre-monorepo/`, which
> is location 2. Location 6 is `plans/` and its `working-plan` rows alone, plus
> the two pointer stubs G5 left at the retired roots.
>
> **G8 re-derives the two rows the later phases outgrew** — locations 2 and 4,
> both deferred here by G3 and G5, counted from the ledger JSON on 2026-08-30
> (234 rows), not from the snapshot below.
>
> **Location 2 (`docs/`) now holds 113 rows**, against the 16 the table
> records. Outside `docs/archive/`, 73: `generated` ×51 · `living-authored` ×13
> · `normative-current` ×8 · `non-documentation` ×1 (`docs/_built/`'s rendered
> copy of the documentation application's own reference). The generated corpus
> is what grew it — the F phase put the map of record, nine reference pages and
> the learn collection here. Inside `docs/archive/`, 40 more: `historical` ×37,
> G5's two plan trees, and `living-authored` ×3, the tombstone notes that
> describe them.
>
> **Location 4 (`packages/s0ma-dsl/docs/`) now holds 36 rows**, against 35:
> `normative-current` ×11 · `living-authored` ×10 · `historical` ×8 ·
> `superseded-pointer` ×6 · `generated` ×1. The stub count doubled — the spec
> pointer and `release_checklist.md` were always there; A1/A5 added stubs for
> the feedback log and the 5–6 walkthrough as they moved to `historical/`, and
> G2 added the two the user-guide merge retired.

| # | Location | Dispositions found |
|---|---|---|
| 1 | Repo root (`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `AGENTS.md`) | `living-authored` ×3 · `normative-current` ×1 (`AGENTS.md`) |
| 2 | `docs/` | `living-authored` ×8 · `normative-current` ×6 (4 ADRs + 2 frozen contracts) · `generated` ×2 (the D6 reader indexes under `docs/reference/`) |
| 3 | `packages/s0ma-core/docs/` | `historical` ×4 · `superseded-pointer` ×3 · `living-authored` ×2 · `normative-current` ×1 (the current spec cut) |
| 4 | `packages/s0ma-dsl/docs/` | `living-authored` ×12 · `normative-current` ×11 · `historical` ×8 · `superseded-pointer` ×3 · `generated` ×1 |
| 5 | `_docs/` + the `_built/` trees | `mirror` ×9 · `generated` ×4 |
| 6 | `plans/` + the two legacy `packages/*/plans/` trees | `working-plan` ×35 · `historical` ×37 |
| 7 | `references/s0ma-prd.md` | `normative-current` ×1 |
| 8 | `editors/` | `living-authored` ×1 |

The eight locations account for 148 of the 158 rows. **Ten sit outside them**,
and the audit's table does not name them as a location at all:

| Path | Disposition |
|---|---|
| `packages/s0ma-core/README.md` | `living-authored` |
| `packages/s0ma-dsl/README.md` | `living-authored` |
| `packages/s0ma-mcp/README.md` | `living-authored` |
| `packages/s0ma-studi0/README.md` | `living-authored` |
| `packages/s0ma-mcp/docs/adr/ADR-001-selfhost-layout.md` | `normative-current` |
| `packages/s0ma-core/CHANGELOG.md` | `historical` |
| `packages/s0ma-dsl/CHANGELOG.md` | `historical` |
| `packages/s0ma-dsl/tests/fixtures/golden/docs/greetings.md` | `non-documentation` |
| `packages/s0ma-dsl/tests/fixtures/golden/docs/walkthrough.md` | `non-documentation` |
| `packages/s0ma-dsl/tests/fixtures/legacy_layout_project/README.md` | `non-documentation` |

Worth noticing: four of the ten are the package READMEs — the first thing a
reader of any package meets, and the audit's location table has no home for
them. The fifth is an **accepted ADR living outside both ADR directories**, in
`packages/s0ma-mcp/docs/adr/`, which nothing indexes. Whatever F builds as the
map of record has to cover these ten or repeat the audit's own finding.

The mapping makes the audit's central finding legible as a shape. Location 4 is
where the normative material lives (11 of the 20 `normative-current` rows).
Location 6 is where more than half the corpus sits — 72 of 158 files are plans,
and 37 of those are fossils. And the 39 `historical` rows that still wear no
banner concentrate in two places — the core-docs fossils of §3.4 (location 3,
three of them then, two now that G2 merged the user guide) and 35 of the 37
legacy plan files (location 6) — with one straggler in location 4:
`release_walkthrough_5-6.md`, which dates itself honestly but never says it is
superseded.

---

## 3. Archive ledger — every `historical` and `superseded-pointer` entry

### 3.1 `superseded-pointer` (11) — stubs that name their replacement

| Stub | Replacement |
|---|---|
| `packages/s0ma-core/docs/architecture.md` (G3) | `docs/architecture/component-index.md` + `packages/s0ma-core/docs/s0ma-core-spec-v0.19.1.md` |
| `packages/s0ma-core/docs/release_checklist.md` | `docs/RELEASING.md` |
| `packages/s0ma-core/docs/s0ma-framework-feedback-3.1.md` | `packages/s0ma-core/docs/historical/s0ma-framework-feedback-3.1.md` |
| `packages/s0ma-core/plans/README.md` (G5) | `docs/archive/pre-monorepo/s0ma-core/plans/` |
| `packages/s0ma-dsl/docs/release_checklist.md` | `docs/RELEASING.md` |
| `packages/s0ma-dsl/docs/release_walkthrough_5-6.md` | `packages/s0ma-dsl/docs/historical/release_walkthrough_5-6.md` |
| `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.16.0.md` | `packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md` |
| `packages/s0ma-dsl/docs/s0ma_feedback-4.md` | `packages/s0ma-dsl/docs/historical/s0ma_feedback-4.md` |
| `packages/s0ma-dsl/docs/s0ma_user_guide.md` (G2) | `packages/s0ma-core/docs/s0ma_user_guide.md` |
| `packages/s0ma-dsl/docs/s0ma_user_guide_condensed.md` (G2) | `packages/s0ma-core/docs/s0ma_user_guide.md` |
| `packages/s0ma-dsl/plans/README.md` (G5) | `docs/archive/pre-monorepo/s0ma-dsl/plans/` |

**The window, ruled at G5 (OP-6).** A moved-path pointer stub — and any
allowance carried in a gate to keep one passing — is removable at the **first
minor release after the doc-function Phase G merge**. The window is tied to a
release event rather than to a date, because what makes a stub safe to delete
is a version boundary somebody can point at: anyone still following an inbound
link from before Phase G is following it into a release that has shipped, and
the next minor is where that stops being true. The two G5 stubs carry the
sentence in their own text, which is what makes the condition readable at the
file rather than only here.

Five of the older stubs predate the ruling and still carry their own words for
the same idea: the spec stub says "in the release after 0.17.0", and the two
feedback stubs and the two G2 guide stubs say "once inbound links are updated".
OP-6 now supplies the governing condition for all of them; rewriting those five
sentences to match is a text change in five files nobody has made yet, and it
belongs with whoever does the deletion pass.

G3's `architecture.md` stub is the one entry here with **no** deletion trigger,
deliberately. It is still served live to agents as `s0ma://docs/architecture`
(`packages/s0ma-core/src/s0ma/api/teaching.py:795` reads it by filename from a
checkout), so deleting it would turn a served resource into an absence. Either
that read is repointed at the current spec first, or the stub stays.

### 3.2 `historical` — superseded by a live document (6)

| Path | Replacement |
|---|---|
| `packages/s0ma-core/CHANGELOG.md` | `CHANGELOG.md` (root) — this file holds releases ≤ 0.4.0 |
| `packages/s0ma-core/docs/s0ma-core-spec-v0.18.1.md` (0.19.0) | `packages/s0ma-core/docs/s0ma-core-spec-v0.19.1.md` — the current cut; the 0.19.0 cut restated this file and is itself historical since 0.19.1. This file keeps its content and its name and carries a banner naming the current cut |
| `packages/s0ma-core/docs/s0ma-core-spec-v0.19.0.md` (0.19.1) | `packages/s0ma-core/docs/s0ma-core-spec-v0.19.1.md` — the cut that restates it for 0.19.1. This file keeps its content and its name and carries a banner naming its successor |
| `packages/s0ma-core/docs/s0ma-core-spec-v0.2.0.md` (G3) | `packages/s0ma-core/docs/s0ma-core-spec-v0.19.1.md` — the current cut (G3 rotated this file to the 0.18.1 cut, itself historical since 0.19.0; the 0.19.0 cut is historical since 0.19.1). This file keeps its content and its name (historical spec cuts are never renamed) and carries a banner naming its successor, held there by `packages/s0ma-core/tests/test_doc_consistency.py` |
| `packages/s0ma-dsl/CHANGELOG.md` | `CHANGELOG.md` (root) — this file holds the pre-monorepo dsl numbering ≤ 0.16.0 |
| `packages/s0ma-dsl/docs/adr/ADR-004-separate-project.md` | No successor ADR. Current authority: `README.md` + `CONTRIBUTING.md` (workspace layout), `references/s0ma-prd.md` NFR-8/INV-4 (package split, licensing, lockstep) |
| `packages/s0ma-dsl/docs/historical/release_walkthrough_5-6.md` | `packages/s0ma-dsl/docs/migration_guide.md` is the live upgrade reference. Moved to `historical/` with a pointer stub at the old path (A5-findings pass); the dsl README row now points at the moved file |

### 3.3 `historical` — archived in place, no replacement owed (8)

Dated consumer-feedback and enhancement-proposal logs. They are records; nothing
replaces a record. The G3 row is the one that is not a log: it is a symbol
reference whose replacement is owed by a future milestone rather than by any
document that exists, and until that is built, what it says is the best thing
in the tree on its subject.

| Path |
|---|
| `packages/s0ma-core/docs/historical/s0ma-framework-feedback-3.1.md` |
| `packages/s0ma-core/docs/references/documentation_subsystem.md` (G3) |
| `packages/s0ma-dsl/docs/historical/s0ma-feedback-findings-1-2.md` |
| `packages/s0ma-dsl/docs/historical/s0ma-framework-feedback-3.md` |
| `packages/s0ma-dsl/docs/historical/s0ma_build_fix.md` |
| `packages/s0ma-dsl/docs/historical/s0ma_feedback-4.md` |
| `packages/s0ma-dsl/docs/historical/s0ma_feedback.md` |
| `packages/s0ma-dsl/docs/historical/s0ma_py_drift_fix.md` |

### 3.4 `historical` — fossil, no replacement yet and no banner in tree (0) — **closed at G3**

This table held the audit's §3.2-B rows that A1–A3 did not reach: documents
presented as live while the ledger said otherwise. It is empty. All three rows
left during Phase G, each by a different route — which is the finding worth
keeping, because "banner it" was the right answer for exactly one of the three.

| Path | Left at | Route | Now in |
|---|---|---|---|
| `packages/s0ma-core/docs/s0ma_user_guide.md` | G2 | **Merged.** The hard one: it could not be archived because it uniquely held around 155 lines of runtime API documentation. Neither banner nor archive but merge | `living-authored` |
| `packages/s0ma-core/docs/s0ma-core-spec-v0.2.0.md` | G3 | **Rotated.** OP-4 ruled rotate+pin, so the fix was to write the missing successor, not to label the fossil. July DOC-8 closed | §3.2 |
| `packages/s0ma-core/docs/references/documentation_subsystem.md` | G3 | **Banner corrected.** The only one where bannering was the whole answer: its content is accurate (re-verified against the code at 0.18.1, one drift fixed), and only its promise of regeneration was false. Withdrawn rather than reissued with a new date | §3.3 |

The pattern across the three: a document that reads as current because it has
no banner is rarely fixed by adding one. Two of these three needed something
written — a merge and a spec cut — and the banner was the last step, not the
remedy.

### 3.5 `historical` — the two legacy plan trees (37) — **archived at G5**

Untouched since the 2026-06-09 subtree-import commits (`b2f0aab` for
`s0ma-core`, `1c8ce22` for `s0ma-dsl`). Replacement for all 37: **`plans/`** —
the live planning tree. Individually, nothing replaces a closed plan.

**No longer archived in place.** G5 moved both trees out of the packages and
under `docs/archive/pre-monorepo/`, each with a tombstone note at its root
saying what the tree was, when it froze, and where current truth lives, and a
pointer stub left behind at the retired path. The paths below are the
destinations; every row kept its `historical` disposition and its catalog id
through the move.

| Path |
|---|
| `docs/archive/pre-monorepo/s0ma-core/plans/TODO.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/Phase1_progress.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/Phase2_5_progress.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/Phase2_progress.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/Phase3B_teaching_plan.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/Phase3_progress.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/Phase4_test_plan.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/implementation_plan_phase_1.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/implementation_plan_phase_2.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/implementation_plan_phase_2_5.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/implementation_plan_phase_3.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/s0ma-rename-plan.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/s0ma_improvement_1_follow-up.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/s0ma_improvement_plan-16FEB2026.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/completed/s0ma_improvement_spec_16FEB2026.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/documentation_subsystem_implementation_plan.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/prompts.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/s0ma-PRD.md` |
| `docs/archive/pre-monorepo/s0ma-core/plans/s0ma_feedback_3.1_plan.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/TODO.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/documentation_subsystem_implementation_plan.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_cleanup_plan.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_cleanup_smoke_results.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_deviations.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_follow-up_plan.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_follow-up_smoke_results.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/5-6_last_items.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/feedback_5-6_plan.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/feedback_5-6_smoke_results.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/s0ma-dsl-feedback-5.5.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/s0ma-dsl-feedback-5.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/feedback_5-6/s0ma-dsl-feedback-6.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/s0ma-dsl_findings_1-2_plan.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/completed/s0ma-dsl_implementation_plan.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/prompts.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/release_prompt.md` |
| `docs/archive/pre-monorepo/s0ma-dsl/plans/s0ma-dsl_PRD.md` |

Only the two `TODO.md` files carry the "STALE — FROZEN FOSSIL" banner A3 added;
the other 35 wear nothing, and after G5 they do not need to — the tombstone at
each tree's root is what marks the whole tree, which is the point of moving them
somewhere a note can cover them all rather than bannering thirty-seven files one
at a time. Their own contents stay byte-frozen, dead links and all: repairing a
frozen record's links would falsify it.

Two files are worth watching by name. `docs/archive/pre-monorepo/s0ma-core/plans/s0ma-PRD.md`
and `docs/archive/pre-monorepo/s0ma-dsl/plans/s0ma-dsl_PRD.md` are both titled
"Product Requirements Document", both superseded in full by
`references/s0ma-prd.md`, and the most confusable files in the corpus. Both
tombstones name them for that reason.

---

## 4. Judgment calls

Every row where the rules did not decide by themselves.

1. **`AGENTS.md` → `normative-current`, not `living-authored`.** It is the
   binding agent contract and the document that *states* the authority order
   the rest of the corpus defers to. Ruling on the side of "binding today"
   rather than the narrower reading (PRD + spec + ADRs + frozen contracts only).
2. **Both package changelogs → `historical`, not `superseded-pointer`.** They
   carry a supersession line but retain their full content, which the root
   changelog does not duplicate. A pointer stub is a file whose *only* content
   is the redirect.
3. **Both `release_checklist.md` → `superseded-pointer`.** 13 and 18 lines, no
   surviving substance ("preserved in git history"), and they name `RELEASING.md`.
   Stubs, not archives.
4. **`docs/archive/0.9.0/README.md` → `living-authored`.** It sits in an archive
   but is not archived content: it is the live, accurate signpost describing
   what the archive holds and where current guidance is. Classifying it
   `historical` would demand a replacement pointer for the thing that *is* the
   pointer.
5. **`docs/design/0.15-runtime-free-emission.md` → `living-authored`.** The
   filename version and the expired 0.16 retarget both argue "historical", but
   A3's outcome paragraph explicitly keeps the round open and folds the
   emitted-import decision into it. An open design note is live.
6. **`packages/s0ma-dsl/docs/s0ma_user_guide_condensed.md` → `living-authored`.**
   Uncomfortable but honest: it is unmaintained in practice (last touched
   2026-04-24) yet carries no supersession banner and has not been archived, so
   the tree presents it as current. The enum has no "unmaintained but not
   archived" value; `historical` would assert an archive status that does not
   exist. Audit §4 recommends fold-or-retire at G — that decision, not this
   ledger, should change the row.
   **Resolved at G2 → `superseded-pointer`, retired rather than folded.** The
   fold was the wrong half of the choice for a reason the audit could not see
   from the outside: a section-by-section comparison found no fact in it that
   the full guide did not already carry, because every section was a shortened
   copy of the full guide's same-named section. Folding a summary back into its
   own source adds nothing and re-creates exactly the two-documents-one-inventory
   condition the merge exists to end. The short forms that survive are the ones a
   gate keeps honest — the survival card, the quick reference, and the packaged
   teaching slice behind `learn_s0ma`.
7. **The dsl `s0ma_user_guide.md` is `living-authored` while the core one is
   `historical`.** Not symmetric, deliberately: the dsl copy has corrected
   packaging paths and was edited at A2; the core copy carries broken
   pre-monorepo install paths and a 2026-02-17 header, and the audit files it
   under fossils. The fork itself stays open.
   **Closed at G2**, and the asymmetry inverted: the union was homed with core
   because the guide documents the core runtime API, so the core path is now the
   `living-authored` one and the dsl path is the stub. Neither copy had been a
   superset — the dsl side held the packaging and onboarding corrections, the
   core side held §§5.6–5.9 — which is why the resolution had to be a merge in
   both directions rather than a choice between them.
8. **`packages/s0ma-mcp/src/s0ma_mcp/_docs/common_errors.md` → `mirror`, not
   `generated`.** It is a byte-copy of a generated file. The copy relationship
   is what the gate enforces and what a reader needs to know; the generation
   happens one hop upstream, on the source row.
9. **`README.md` → `living-authored`** despite embedding a gate-pinned generated
   region. Mixed files get the disposition of their authored majority, with the
   generated region recorded in the note. `docs/getting-started.md` is the
   source of that region and is itself `living-authored`.
10. **`packages/s0ma-dsl/tests/fixtures/legacy_layout_project/README.md` →
    `non-documentation`.** No test reads it — it is a human explainer — but it
    documents test scaffolding from inside the fixture tree, and putting it in
    the documentation corpus would oblige the F-phase map of record to list it.
    The two golden `.md` fixtures beside it are unambiguous: tests assert their
    bytes.
11. **`plans/progress_review_01JUL2026.md` and everything under `plans/notes/`
    → `working-plan`.** Several are review records or contracts-in-waiting
    rather than plans, but the plan's rule is by location and the value of a
    location rule is that it does not get relitigated per file.
12. **`docs/adr/ADR-002` → `normative-current`** despite its scope-bound status
    line ("Accepted for 0.14.0 M6"). Audit §3.2-C flags the ambiguity; an
    accepted ADR stays binding until something says otherwise.

Nothing in the corpus was unclassifiable.

---

## 5. Notes for the milestones downstream

- **C6** consumes the JSON, not this file. Dispositions map to catalog `status`;
  `audience` seeds `audiences`; `note` is provenance, not content.
- **G** should treat §3.4 as its work list: it began as three fossils with no
  banner and no replacement. **G2 removed one** — the core user guide, the one
  holding content that existed nowhere else — by merging the fork into it rather
  than archiving it. The two that remain are G3's.
- **A7** adds two rows (`docs/uninstall.md`, `docs/troubleshooting.md`,
  both `living-authored`); it owns them, and the guard test will fail until they
  are added.
- **G5** closed §3.5 by moving rather than bannering, and left one thing open
  behind it: the five pre-OP-6 stubs named at the end of §3.1 still carry their
  own deletion wording. The OP-6 window governs them now; the sentences do not
  say so yet. Whoever runs the deletion pass at the first minor release after
  Phase G merges is the one to reconcile the two.
- The guard is a **presence** check only. It cannot tell whether a disposition
  is right — that is what the F2 catalog and its accuracy gates are for.
