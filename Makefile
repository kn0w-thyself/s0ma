# s0ma monorepo root Makefile — thin delegation to the unified check
# pipeline. `scripts/check.py` is the single source of truth for what
# constitutes a passing tree (it is exactly what CI runs); these targets
# are typing-savers, not alternative pipelines.
#
# The s0ma-dsl package keeps its own Makefile for package-local
# conveniences — notably `docs-derived`, which renders the in-repo
# doc-ref generators; the root `docs-derived` target forwards to it with
# the workspace CLI.

.PHONY: check test lint docs-derived release-cut

check:
	uv run python scripts/check.py

test:
	uv run python scripts/check.py --only pytest-core pytest-dsl

lint:
	uv run python scripts/check.py --only ruff mypy-core spelling

docs-derived:
	$(MAKE) -C packages/s0ma-dsl docs-derived S0MA="uv run s0ma"

# The mechanical half of docs/RELEASING.md: bump the four pyproject
# versions, carve the changelog (+ its served mirror), refresh the lockfile,
# and PRINT the commit/tag/push commands. Dry run unless ARGS=--write.
#   make release-cut VERSION=0.18.0
#   make release-cut VERSION=0.18.0 ARGS=--write
release-cut:
	@[ -n "$(VERSION)" ] || { \
	  echo "usage: make release-cut VERSION=X.Y.Z [ARGS='--write --allow-branch']"; \
	  exit 1; }
	bash scripts/release_cut.sh --version $(VERSION) $(ARGS)
