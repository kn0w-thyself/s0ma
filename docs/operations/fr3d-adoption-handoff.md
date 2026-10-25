# fr3d adoption after the upstream observation fixes

Prepared 2026-10-25. This is a handoff for a separate session. Upstream work is
prepared for review; it is not merged, released or adopted. The next release
version is unresolved. Rob must merge both s0ma PRs, then explicitly authorize
the normal four-package release before fr3d adoption begins.

## Upstream identity and evidence

| Record | Value |
| --- | --- |
| s0ma implementation base | fd62a067b292f575c6845620a633af1d6b7e763f |
| Runtime head | 35f34ec19d9b759818c7ac46b9af984ae760319f |
| Runtime PR | [s0ma #11](https://github.com/kn0w-thyself/s0ma/pull/11) |
| Guidance implementation head | 348b8c90fa7898259c634e206f52caded1113a02 |
| Guidance PR | [s0ma #12](https://github.com/kn0w-thyself/s0ma/pull/12) |
| fr3d main inspected read-only | cbe17141f721f315e53c7bb799224f53edee9579 |
| Release / fr3d adoption | Neither performed; owner merge and authorized release pending |

The guidance PR is stacked on the runtime branch. Merge runtime first, retarget
the guidance PR to main and verify its diff and checks before merging it. The
guidance SHA above identifies the implementation before this handoff's final
documentation commit; get each PR's current head with `gh pr view --json
headRefOid,state,statusCheckRollup`. A PR head is not a release tag.

S01-S04 are fixed. S05 now has a public adapter matrix and real build composition;
operation contracts, constants, READS edges, reverse dependencies and application
views were already supported and are verified, not reimplemented. S06-S08 are
implemented as executable application examples and canonical served guidance.
No S item is deferred. The
[requirement ledger and compatibility guide](bench-runtime-contracts.md) maps
each item to tests; [saved evidence](bench-runtime-evidence.json) records the
original 87-test baseline, corrected 16 failing regression cases against unchanged
base source, and 307 focused passes before two further tests were added.

The full runtime gate passed: core 2,034, DSL 7,990, MCP 476, studi0 124 and
integration 532 tests, with 30 documented skips across those suites. The guidance
adds two build/boot/consumer runs, original and renamed, with zero model/network
calls. The guidance gate passed with DSL 7,992 and the same other suite counts;
the final combined gate is recorded in the adjacent evidence JSON. Both use
the canonical `uv run python scripts/check.py`,
including type/lint checks, three-build equality, packaged guide equality,
cold installed-wheel checks and documentation gates. `git diff --check` passes.
Runtime CI passed all six OS/Python jobs and wheel building. CI is filtered
to PRs targeting main, so the stacked guidance PR has no remote checks yet.
After retargeting it to main, verify a new CI run completes before merging;
if retargeting alone does not trigger the workflow, reopen the PR or push the
next reviewed change. Do not treat absent checks as a pass. No authoring MCP
surface snapshot, DSL grammar, IR schema or dependency direction changed. Frozen audit results and probe attempts remain untouched.

## Consumer compatibility, with before and after examples

These are inspection contracts, not proof of provider or whole-application health.
The exact response table and full examples are in the compatibility guide above.

| Request | Before | After | fr3d adjustment or verification |
| --- | --- | --- | --- |
| GET /self/health when verification raises | HTTP 200, passed=true, anomaly_count=0, text says unavailable | HTTP 200, status=unavailable, passed=null, anomaly_count=null, reason=VERIFICATION_ERROR, checked_at=null | Branch on status; do not coerce null to false/failure or zero/absence. Keep request success separate from check outcome. |
| GET /self/anomalies when checks are unavailable | anomalies=[], total=0 | anomalies=[], total=null, status=unavailable, safe reason | Carry availability and coverage through HTTP/UI/prompt projections. An empty list is not an observed zero here. |
| GET /self/component/fixture_read, unique provider | 404 after successful text resolution | 200 with resolved={query:fixture_read,component:alpha::FixtureProvider,operation:fixture_read} and matching spec/text | Consume canonical resolved identity; verify the real endpoint and assembled context. |
| Same request, two providers | Generic 404 | 409, detail.code=AMBIGUOUS_COMPONENT, candidates=[alpha::FixtureProvider,beta::FixtureProvider] | Preserve ambiguity and ask for a canonical candidate; never choose silently. Unknown names retain 404 and string detail. |
| component Shared with one alpha registration and alpha/beta in build | Both canonical components observed=true | alpha=true, beta=false for coherent metadata; unresolved/conflicting identity yields null for affected components | Retain canonical IDs and null; do not merge same-name records or turn uncertainty into absence. |
| component X after unregister, reused adapter | Earlier observed=true without lifetime metadata | Earlier true with original captured_at and lifetime=snapshot; new adapter false | Reconstruct deliberately, and publish handler/context as one update. Inspection itself does not refresh. |
| Registry read fails during reconstruction | Exception escaped | live_health.status=unavailable, captured_at=null, reason=REGISTRY_SNAPSHOT_FAILED; component observed=null | Publish unavailable evidence; do not present retained old context as newly observed. Invalid build hashes still raise SelfContextError. |

Library, query-engine and core MCP verification text now says PASSED, FAILED or
UNAVAILABLE and names registered verification as its scope. REST completed reports
include the actual report time. Missing imports use VERIFIER_UNAVAILABLE; absent
reports/results use NO_VERIFICATION_RESULTS. Raw exception messages are omitted.
ComponentResolution retains the operation on ambiguous aliases. Runtime ambiguity
adds an error.candidates list. Text adapters retain their diagnostic-text shapes.

REST list/graph/numeric inventory remains full-registry. Application-focused text
and runtime views may filter framework components; compare the same population.
Snapshot metadata is volatile and remains outside deterministic build identity.
Do not infer provider reachability from registered components or build verification.

For a long-running host that explicitly opts into registry observations:

```python
from s0ma.runtime import self_inspect_adapter

replacement = self_inspect_adapter(build_root, registry=registry)
# Publish replacement.context and replacement.handle as one host-owned update.
# Publish unavailable if the registry read failed. Retaining a previous adapter
# retains its original capture time; record a failed refresh separately.
adapter = replacement
```

At the inspected fr3d main, `src/fr3d/domain/self_model.s0ma` calls
`self_context(root)` without a registry. Adding a registry is an explicit host
decision, not something this upstream change does. Keep source-mode gates around
every new prompt/inspection path. `frozen_docs` and `manifest_only` must not gain
live facts, tools or ambient context through the upgrade.

## Owner release boundary

Rob merges the reviewable changes; the author cannot supply the required review.
Then Rob chooses a version and authorizes release. Follow
[docs/RELEASING.md](../RELEASING.md), including its prepare A, tagged R and reopened
P sequence, not an improvised tag on either implementation branch:

1. From clean updated main, create the release branch. Dry-run the release-cut
   script before its authorized write. Bump all four packages together and carve
   the root changelog; cut the new core spec and refresh documented version refs.
2. Rebuild all three outputs without cache, render the documentation application,
   compose preview, refresh all GUIDE_DOCS and five generated mirrors, then run
   the full gate. Commit A and review it through the release PR.
3. For R, compose with the chosen tag value and run the full gate with the same
   S0MA_HEAD_TAG. Recompose preview for P, run the full gate again, and verify P's
   tree equals A's. The annotated release tag names R; main ends at P.
4. Only the owner-authorized tag push triggers publication. Verify wheel identity,
   release artifacts and served distribution checks. A skipped deployment or
   served check is not evidence of delivery. No control-plane change is part of
   these library fixes. Do not enable index publishing as an incidental step.

Stop on failed gates, mismatched artifacts or missing authorization. Before
publication, retain the prior release and correct the candidate. After publication,
use the runbook's manifest-pointer rollback if authorized; do not move a released
tag or replace immutable wheels. Record the approved tag, commit and package
version in the downstream PR before changing fr3d pins.

## Copy/paste prompt for the separate fr3d session

Copy the following block after the upstream release has been authorized and
verified. It supplements the older detailed prompt with the actual API changes.

```text
You are CLU. Implement fr3d's adoption and application fixes in a fresh codex/
branch from fetched current rob-kts/fr3d main, in an isolated worktree. Leave
historical benchmark artifacts and drift branches untouched. Do not implement
website or benchmark changes. Use uv run for Python and s0ma commands.

Read in order:
1. Current fr3d CLAUDE.md, docs/CONTRIBUTING.md and applicable AGENTS.md, the
   current approved plans and syntax reference they require.
2. /Users/main/Projects/kn0wthyself/s0ma-bench/docs/scenarios/pre-next-bench-2026-10-24/report.md,
   evidence.md and upstream-first-handoff.md in full.
3. /Users/main/Projects/kn0wthyself/s0ma-bench/docs/scenarios/s2-phase1-v1/investigation/fr3d-fixes-prompt.md
   in full. The newer report governs F01-F11 when the earlier prompt is stale.
4. The merged s0ma docs/operations/fr3d-adoption-handoff.md,
   docs/operations/bench-runtime-contracts.md and
   docs/guides/application-observations.md, including the executable fixture.

First verify that Rob merged s0ma #11 and #12, authorized a release,
and that its immutable tag/commit includes both implementations. Record the
actual version, tag, SHA, package provenance and installed import paths. Do not
substitute a pending branch, assume a future version, or claim adoption while
that release is missing. Complete independent investigation while a required
owner decision is pending; keep dependent changes behind that boundary.

At inspected fr3d main cbe17141f721f315e53c7bb799224f53edee9579, build-system
core/dsl pins and dev mcp pin in pyproject.toml used v0.20.0, runtime floors
were >=0.19.1, and Dockerfile plus boundary-check.yml, ci-windows.yml and
install_smoke.yml pinned v0.20.0. Re-inventory current main, update all existing
active pins/floors, lockfile if present, CI/build references and living docs to
the approved release. No dependency lockfile was tracked in the inspected
main; recheck instead of assuming one exists or inventing a lock mechanism.
fr3d uses core, dsl and authoring mcp; do not add studi0 because upstream releases
four packages. Preserve valid alternative installation routes.

Build with uv run s0ma build src --mode dev, never a bare s0ma build. Edit
authored .s0ma sources and registered tests; rebuild generated code under fr3d's
rules. Verify imports use the chosen project build, not another editable install
or the wheel's separate fr3d_build copy. Use the supported bootstrap/import helper.

Adopt these concrete contracts: REST health has status passed/failed/unavailable,
nullable passed/anomaly_count and safe reason codes; unavailable anomalies have
total=null. HTTP 200 is request success only. Unique operation lookup returns
the resolved canonical identity; ambiguous names return 409 and candidates;
unknown names retain 404. Text adapters retain explicit unknown/ambiguity meaning.
Component observation can be null when identity/read is unknown. Snapshot
adapters retain captured_at and never refresh on query. Reconstruct on the
host's explicit lifecycle event, publish handler/context together, and distinguish
failed refresh from retained old evidence. Invalid build hashes still refuse.
The current fr3d loader supplies no registry to self_context; opt into live
observations only through the allowed host path, never through frozen source arms.

Implement F01-F03 first: fail closed on memory-policy read failure throughout
prompt construction/background reads; report actual refused/working-only/
persisted/failed effects; preserve malformed/unreadable categories on failed
read-modify-write. Assert response, memory, disk, fresh-reader and actual prompt
delivery agree. Use temporary data, atomic persistence and an explicit recovery
path; assess concurrency separately.

Then implement F04-F11: shared readiness and next actions for Gmail/Calendar/
Notion/Slack using the same effective configuration and validator as execution;
deliberate refresh and expiry/removal semantics; registration, credential presence
and provider verification as distinct facts; unavailable/failed/partial inspection,
scoped health and session parse coverage; scheduler discovery against the real
ToolSpec return contract with safe/unsafe/read/conversion cases; bounded effects,
settings and limitations queries sourced from actual owners; evidence-aware
unknown-name and ambiguous-name recovery. Keep the lightweight boot probe.

F09 is an owner policy decision: the written frequency safeguard covers INTERVAL.
Ask whether it should remain interval-specific or cover firing frequency across
cron and other triggers. Do not call existing cron behavior a contract violation.
Finish independent fixes while that decision is pending; implement any expansion
only after the policy is explicit.

Test real registry, self-inspection queries, HTTP projections and the context
actually sent to a recording adapter. Keep authored facts through build/IR/boot,
operation contracts, constants/READS, dependents/impact and application filtering.
Preserve static system instructions versus volatile turn context and the
data/instruction fence. Test all source modes; frozen_docs and manifest_only
must not acquire live facts through any new query, tool or ambient prompt path.
Use renamed providers/new operations absent from the old bank. Inspect relation
kinds and operation scope; optional cache failure need not fail the main action.

Preserve expired initial reattachment rejection, dispatch refusal on policy-read
failure, permissions/capabilities, unattended consent, and no workaround after
denial. Do not merge benchmark drift commits or remove a valid alternate route
to satisfy an old key. No paid calls, OAuth flows or real user data are needed.

Run focused registered tests, then the current complete documented gates. At
inspection these include uv run make discipline-check, uv run s0ma check --mode
strict, uv run s0ma verify fr3d_build/, uv run s0ma test --mode dev --quiet,
the documented score/report and applicable install/CI checks. Keep live,
live_api and acid excluded. Record exact commands, counts, effect/prompt assertions,
tree deviations and existing baseline failures. Update the canonical docs and
feedback log, commit explicit file lists, push focused PRs, attach them and verify
remote heads/CI. Rob must review/merge; do not bypass the author-review rule.

Finish with a benchmark-preparation handoff, not a benchmark run. Preserve all
frozen inputs, keys, grades, reports and tags, including unrelated working files.
```

## Benchmark restart prerequisites

After upstream release and fr3d adoption/fixes, begin a separate bench preparation
session. Repair B01's key-writing test before running the full bench suite and
hash-check frozen paths before/after. B02 requires immutable source/build/env
fixtures, independent of mutable working checkouts. B03-B10 require strict parser
counterexamples; separate correctness, self-report consistency and confidence;
questions that cover permitted routes/triggers; direct effect observations;
projection invalidation on declaration/schema revision; per-invocation timing;
pre-call cost reservations; and held-out cases with human audit.

Create new pre-registrations only after product adoption. The old bank is now
development material. Preserve historical scores. Run a zero-spend pipeline
check before any separately authorized paid pilot; the earlier exploratory
allowance is not permission for another study. Scenario 5 is next in the approved
order, but its runner is still a placeholder. Deterministic regression passes do
not establish an accuracy improvement.
