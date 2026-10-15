# Moved: s0ma_user_guide.md

The s0ma User Guide is now one document, and it lives with the runtime it
describes:
[`packages/s0ma-core/docs/s0ma_user_guide.md`](../../s0ma-core/docs/s0ma_user_guide.md).

Until 2026-08-30 there were three overlapping copies — this one, one under
`s0ma-core`, and a condensed abridgement beside this file. They began as one
pre-monorepo document and drifted apart in both directions: this copy had the
corrected packaging paths and the DSL onboarding notes, the core copy uniquely
held around 155 lines of runtime API documentation, and neither was a superset of
the other. The merged guide carries all of it, and its first section describes
how s0ma is actually installed today.

It is homed with `s0ma-core` because that is what it documents: the Python
registration, verification, and self-model API. For the `.s0ma` **language**,
read [the current spec](s0ma-dsl-spec-v0.17.0.md), this package's own document
and unaffected, and [the quick reference](../../../docs/reference/quick-reference-readable.md),
which the documentation build generates from the language itself.

This pointer file is scheduled for deletion once inbound links are updated.
