# ADR-014: The `forbids` line — what a nerve or a ganglion must never do

**Status:** Accepted by the owner's ruling of 2026-09-30
**Date:** 2026-09-30 (the owner's ruling; this record was written 2026-10-05)
**Governing input:** the owner's rulings of 2026-09-30, **D-1** to **D-6** in
§2.1 of the forbids-line plan (internal, not published):
the line is called `forbids`; it belongs to `nerve` and `ganglion`; it must
always be written, and it may be `none` or `pending("reason")`; it holds one
text value; its home in the runtime is `Contract.forbids`; it goes out in a
release whose number is not named yet
**Recorded with them:** the rulings **P-1** to **P-12** in §2.2 of the same
plan, which work the owner's rulings out in the language, the IR and the
runtime. Each is reversible and is put to the owner with this record. Every
rule below names the ruling it comes from.
**Contract revision:** Revision R6 (§14) of
[`docs/contracts/0.14.0-schema-and-surface-budget.md`](../contracts/0.14.0-schema-and-surface-budget.md),
which adds the line to the field tables of its §3

---

## Decision

A nerve and a ganglion each carry a line called `forbids`. It says what the
part must never do. Its meaning is normative, in these words:

> What the part must never do, however it is called and whatever happens while
> it runs. s0ma checks that the line is there and what state it is in; it does
> not read the sentence. `none` states that nothing is ruled out. It is an
> answer, not a way to skip the line.

It goes out in a release whose number is not named yet, and this record names
none (D-6).

### 1. The line

The line is called `forbids` (D-1), and that one spelling is used everywhere:
the authored line, the attribute of the parsed declaration, the key in the
canonical IR, the key in the self-context and the field in the runtime.

### 2. Its two kinds

`nerve` and `ganglion`: the working part and the watcher (D-2). Not cells,
helpers, tests, integrations, modules, axons or the documentation kinds.
Written on any other kind, the line is an unknown field, and the existing
`UNKNOWN_FIELD` report says where it belongs. In the contract's field tables it
sits directly after `guarantees` for a nerve and directly after `on_anomaly`
for a ganglion. It is not a sub-field of a `provides:` entry, whose three
sub-fields stay three (P-7).

### 3. Its class

Semantic-required-state, **SR / V,N,P** in the contract's legend (D-3). The
line must always be written. It may hold a sentence, `none`, or
`pending("reason")` with a reason that is not empty. Leaving it out is an
error, as it is for every required line. As on every state-carrying line, the
whole-value forms `none` and `pending(…)` are states, while a quoted `"none"`
is a sentence. There is no new diagnostic code and no new severity row: the
reports that already cover a required line cover this one (P-5).

### 4. Its shape

One text value, like `expects` and `guarantees` (D-4), in every shape `expects`
accepts: inline quoted, multi-line quoted, and the `|` block. Every shape, the
empty quoted string included, is handled exactly as `expects` handles it. In
the canonical IR the line is `components[].fields.forbids` on nerve and
ganglion records, in the tagged representation the contract gives every
state-carrying line: `{"state": "value", …}`, `{"state": "none"}` or
`{"state": "pending", …}`. The IR `schema_version` stays `"3.0.0"` (P-1).

### 5. Its home

In the runtime the line lives in `Contract.forbids` (D-5), a list of strings:
the last field of `Contract`, empty by default, and written out by `to_dict`
only when it is not empty (P-3). A nerve's sentence goes into the nerve's
`Contract`, beside what `expects` and `guarantees` put there. A ganglion's goes
into `contracts=Contract(forbids=[…])` on its emitted `@component(…)`, so the
prohibition of either kind is read back at `spec.contracts.forbids` (P-4).
`none` and `pending` emit nothing.

### 6. What s0ma does with it

s0ma checks that the line is there and what state it is in, and carries it to
the places a part's contract is shown: the self-context, the documentation's
field lists for a nerve and a ganglion, studi0, the contract text the runtime
formats (a `Forbids:` block after `Invariants:`) and the teaching snippet. It
does not read the sentence, and neither verifier counts it or executes it: the
arithmetic of both stays as it is (P-6). The MCP surface does not change
(P-10).

## Context

The contract's field tables (its §3) list what a declaration must answer. A
nerve says what it is for (`intent`), what must hold before it runs
(`expects`) and what it promises (`guarantees`). A ganglion says what it is
for, what it observes and how it responds (`intent`, `observes`,
`on_anomaly`). Until this decision, neither had a line for what the part must
never do.

An author who knew of such a rule had nowhere of its own to put it. It could
go into the prose of another line, such as `guarantees:`, where nothing tells a
prohibition apart from a promise, or into `metadata`, which is
presentation-optional: it may be left out and has no state to answer with. No
line asked the question, so a part with nothing to rule out and a part whose
author never considered the question looked the same.

The owner ruled on 2026-09-30 (D-1 to D-6 above).

## Rationale

**A line of its own.** A promise and a prohibition answer different questions.
`guarantees` says what the part achieves; `forbids` says what it must never do
on the way, whoever calls it and whatever goes wrong. An agent changing the
part needs both: the promise tells it what the change must keep achieving, the
prohibition what no change may make the part do. Kept apart, the prohibition
is shown under its own label and asked for on its own.

**Required, with `none` as an answer.** An optional line cannot tell "nothing
is ruled out" from "nobody asked". The contract already settles this for lines
whose absence must be a conscious choice — `expects`, the dependency lines,
`covered_by` — by requiring them and accepting `none` as the answer. `none`
costs one word. `pending("reason")` lets an author say that the answer is not
settled yet, and why.

**A nerve and a ganglion, and nothing else.** A prohibition is about what a
part does. The working part does the work it is called for; the watcher
assesses what it observes and responds. Of the kinds left out, two come
closest. A helper works for the nerves that call it, and a nerve's line covers
whatever happens while it runs, its helpers included. A cell holds data, and
what must never happen to that data is the other face of what must always hold
of it, which the cell's `invariants` line already states.

**One text value.** Beside `expects` and `guarantees`, in the same shapes, the
line is handled by the parser, the IR builder and every reader exactly as those
two are. No new value shape is needed, and so no new report.

**`Contract.forbids`.** A prohibition is a term of the part's contract, and it
belongs where a contract is already read: the registry, the formatted contract
text, the teaching snippet. Placed last in the dataclass and written out only
when set, the field changes nothing for a component that has none: building a
`Contract` positionally still works, and no stored snapshot, API reply or test
expectation moves (P-3). One home for both kinds (P-4) means one place to read
it back.

**Declared and shown, not counted.** s0ma does not read the sentence, so it
cannot check it. Counting it in a verifier would lower a component's
auto-verifiable share for having written one, and would move the score report
the contract freezes (P-6). A new diagnostic code would add a severity row, an
error-reference row, a fixture and a ledger move for no new behaviour (P-5).

## Consequences

- **Breaking, in the release that carries it.** Once the line is required, a
  nerve or a ganglion without it is refused, in every mode, where it built
  before.
- **One command migrates a project.** `s0ma migrate grammar --apply` writes
  `forbids: none` into each nerve and ganglion that lacks the line, as one
  whole-project rewrite; without `--apply` it only shows what it would change.
  The `none` it writes is an answer given on the author's behalf, matching what
  those declarations stated until then. Wherever a part does have something it
  must never do, the author replaces that `none` with the sentence.
- **Every doc content hash moves, once.** The canonical form walks every
  declared field of a dataclass (`hashing/canonical.py` in `s0ma-core`), so a
  new field on `Contract` changes the canonical form of every component, and
  with it every doc content hash, whether or not the line holds a sentence.
  This is accepted and recorded here (P-12). The rendered fixtures in this
  repository that pin those hashes are re-stamped once.
- **A real prohibition needs the matching `s0ma-core`.** An application built
  from a `forbids` sentence passes `forbids=[…]` to `Contract`, which an older
  `s0ma-core` does not accept, so it needs the `s0ma-core` of the release that
  carries this change. `none` and `pending` emit nothing, so on this line's
  account they ask nothing new of the installed core.
- **The IR version does not move.** `forbids` is one more state-carrying key on
  nerve and ganglion records, and `schema_version` stays `"3.0.0"` (P-1).
  [ADR-013](ADR-013-derived-source-registry.md) (§3a) likewise added content
  and left the IR schema version exactly what it was.
- **The verifiers do not change.** Both compute exactly what they computed
  before (P-6).
- **No MCP surface moves.** No tool, prompt, resource, description or schema
  names the line, and the committed surface snapshot does not change (P-10).
  The self-prompt card does not change by a byte.
- **The PRD does not change** (P-11).
- **It arrives in three steps** (P-2). The language accepts the line; the
  repository's own sources gain it; then the language requires it. The
  repository's own sources get `none` mechanically first, and real sentences
  only where a commitment already exists in writing, ratified by the owner as
  one table (P-8). Until the last step, a left-out line reads as `none`, and
  the migration does not write it. No `guarantees:` text is edited to move a
  prohibition out of it (P-9).

## What this ADR does not decide

- The number of the release that carries the line, and the language
  specification's next number. Both are chosen when that release is cut.
- Which of the product's own parts carry a real sentence, and its words. The
  owner rules those as one table; each sentence restates a commitment already
  in writing and cites it.
- Counting a prohibition in either verifier (P-6), the line inside a
  `provides:` entry (P-7), moving prohibitions already written into
  `guarantees:` text (P-9), and a canonical form that keeps the hashes still
  when the line is empty (P-12). Each is deferred to a decision of its own.
- Whether editing contract text should mark a document as drifted. The
  build-time doc-hash snapshot gives every component an empty `Contract()`, so
  a change to a `forbids` sentence, like a change to `expects` or `guarantees`
  text, does not by itself mark a document as drifted. This record notes that
  and changes nothing about it.

## Alternatives considered

- **Optional, checked only when written.** Rejected by the owner (D-3). A line
  that may be left out cannot be told apart from one nobody considered, and
  the question would reach only the authors who had already thought of it.
- **A list of strings.** Rejected by the owner (D-4). Its siblings hold one text
  value, and the multi-line shapes already hold as many sentences as an author
  needs; a list would need a new value shape and new reports for its empty and
  malformed forms. The runtime field is a list, so code that builds a
  `Contract` itself can still give more than one.
- **A `metadata` key.** Rejected. `metadata` is presentation-optional: it may be
  left out and has no state, so it cannot carry a required answer. It is
  metadata, not a term of the part's contract, so nothing that shows the
  contract would show it.
- **A schema-version bump.** Rejected (P-1). The contract freezes the number
  and a reader requires it exactly, so a bump would make every existing reader
  refuse every new build, for one added key on records that already carry
  state-carrying keys.
- **A hash-stable canonical form.** Rejected here (P-12). A rule that leaves an
  empty field out of the canonical form would keep every doc content hash
  still, but it would change the hashing contract, a larger decision than this
  feature. Deferred.
- **Cells as well.** Rejected by the owner (D-2). A cell's `invariants` already
  say what must always hold of its data, and a second line saying it in the
  negative would split one answer across two lines.
