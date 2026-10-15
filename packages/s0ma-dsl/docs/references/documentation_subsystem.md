# Documentation Subsystem — superseded

**This page has moved into the documentation corpus, where it is cataloged
and gated.** Read
[the documentation subsystem](../../../../docs/documentation-subsystem.md).

It said, for v1, what the three documentation declarations are and when to
reach for each, how a doc-ref and a doc-guide are written, how rendering stays
deterministic, what the front-matter contract is, where a rendered document
lands, how the drift check works and what does and does not trigger it, the
two shapes of `covers:`, the external coverage credit and the wrapper-import
recipe. All of that is on the new page, in one place, with every enumeration
it used to carry by hand deferred to a generated one:

- every report the toolchain can make, with severity per mode and what to do
  about it — [what s0ma can report](../../../../docs/reference/diagnostics.md);
- every command, with its flags — [the s0ma command line](../../../../docs/reference/cli.md);
- what each declaration means — the learning collection's pages for
  [doc-ref](../../../../docs/learn/doc-ref.md),
  [doc-guide](../../../../docs/learn/doc-guide.md) and
  [example](../../../../docs/learn/example.md).

**The normative source is unchanged:**
[DSL Spec §4.12](../s0ma-dsl-spec-v0.17.0.md). When any page and the spec
disagree, the spec wins.

Two things this page carried are not on the new one, deliberately. Its
*migration status* table was a snapshot of which documents had moved as of
v0.11.0; the document catalog now records the standing of every document in
this repository, and [the map of record](../../../../docs/README.md) renders
it. Its *resolved design decisions* table was an implementation log answering
questions from the design overview; the decisions that are still live
invariants — hand-rolled renderers for byte-equality, a content hash scoped to
referenced state only — are stated on the new page as invariants rather than
as a decision log, and the log itself is preserved in this file's git history
and in the archived
[`plans/TODO.md`](../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/TODO.md)
and
[implementation plan](../../../../docs/archive/pre-monorepo/s0ma-dsl/plans/completed/documentation_subsystem_implementation_plan.md).
