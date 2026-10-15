# s0ma-dsl Makefile.
#
# This repo is not itself a `[tool.s0ma]` project (intentional — s0ma-dsl is
# the transpiler, not a project that consumes the transpiler). Targets here
# stand in for the conveniences a fully-dogfooded project would get from
# `[tool.s0ma]` discovery — today, that is one target: `make docs-derived`,
# which renders the in-repo `doc-ref` declarations under `docs/_generators/`
# to their declared output paths under `docs/_generated/`.
#
# G7b (feedback 5–6 cleanup) introduced this target. Running it updates
# `docs/_generated/common_errors.md`, the rendered Common Errors table, which
# `s0ma-mcp` serves to agents as `s0ma://guide/errors` from a byte-identical
# copy. The meta-test
# `tests/test_doc_consistency.py::test_common_errors_generated_artifact_matches_doc_ref_output`
# fails loudly if the generated artifact drifts from the renderer's current
# output. (Until 2026-09-29 the table was also copied into a bracketed region
# of the hand-authored quick reference; that document is retired.)

S0MA ?= s0ma

.PHONY: docs-derived
docs-derived:
	$(S0MA) docs render docs/_generators/ --output-dir docs/

.PHONY: test
test:
	pytest tests/ -q

.PHONY: lint
lint:
	ruff check src/ tests/
