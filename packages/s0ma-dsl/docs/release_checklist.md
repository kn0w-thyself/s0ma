# Release Checklist — superseded

**This checklist is superseded.** It described the release process for the
pre-consolidation, multi-repo era (separate versions and tags per repo).
Since the monorepo consolidation (0.5.0), all packages — `s0ma-core`,
`s0ma-dsl`, `s0ma-mcp` — release together: one lockstep version, one root
`CHANGELOG.md`, one annotated `v<version>` tag (PRD INV-4).

**The canonical release runbook is
[`docs/RELEASING.md`](../../../docs/RELEASING.md) at the repo root.**

The dsl-specific manual items the old checklist carried are now enforced
mechanically by the unified gate (`scripts/check.py`): derived-doc drift
via `tests/test_doc_consistency.py`, golden/determinism suites, and the
INV-1 spelling guard.

The historical checklist text is preserved in git history (this file,
pre-0.5.0).
