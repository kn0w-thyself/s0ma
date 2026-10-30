# s0ma Architecture — superseded

**This document has been replaced by two that cannot drift.** It was a
hand-maintained narrative of core's design that carried its own component
inventory, module map, and counts — and for most of its life it claimed at the
top to be generated from `registry.snapshot().describe()` and gated by a test.
Neither was ever true: no generator produced it and no test read it. That is
the worst possible document to hand an agent in a framework whose premise is
that a self-model cannot drift from the code, so the claim was withdrawn and
the document is now retired in favour of the two surfaces that make it true.

**What s0ma contains** is the
[component index](../../../docs/architecture/component-index.md): every
component every distribution registers, with what each one is for, read out of
a booted registry and the committed build artifacts when this repository's
documentation is composed. It is regenerated on every build and byte-compared
by a gate, which is exactly the property this file asserted and never had.

**What s0ma promises** is
[`s0ma-core-spec-v0.21.1.md`](s0ma-core-spec-v0.21.1.md): core's invariants and
contracts — the registration rule, the import hook, verification, the trust
boundary, the stability promises — stated once, with every inventory deferred
to the generated pages.

For the rest of the map: [what s0ma can do](../../../docs/reference/surfaces-index.md)
lists the served capabilities, [the distributions s0ma ships](../../../docs/reference/packages.md)
lists the packages, [the user guide](s0ma_user_guide.md) teaches the runtime
API, and [`docs/README.md`](../../../docs/README.md) is the map of the whole
corpus.

The retired narrative — its design-decision log, module map, and the research
program framing — is preserved in this file's git history.
