# fr3d adoption after the upstream observation fixes

Updated 2026-10-25. This is a handoff for a separate session. Rob reviewed and
merged the upstream fixes and release preparation, then authorized publication.
The annotated tag `v0.21.0` names release commit
`62bbf1caa5341b5f3047e8e08c1b3cdebd7506b8`. Publication and served-artifact
verification passed. fr3d adoption can now use this immutable release in its
separate implementation session; it has not begun here.

## Upstream identity and evidence

| Record | Value |
| --- | --- |
| s0ma implementation base | fd62a067b292f575c6845620a633af1d6b7e763f |
| Runtime head | 35f34ec19d9b759818c7ac46b9af984ae760319f |
| Runtime PR | [s0ma #11](https://github.com/kn0w-thyself/s0ma/pull/11) |
| Runtime merge on main | 5c5793abdcd718f1b6f9b919612afdce62f3a3a3 |
| Guidance implementation head | 348b8c90fa7898259c634e206f52caded1113a02 |
| Guidance PR | [s0ma #12](https://github.com/kn0w-thyself/s0ma/pull/12) |
| Guidance merge on main | 5888b8b2c085013c0bbfd32a53da87fb2b9acb71 |
| fr3d main inspected read-only | cbe17141f721f315e53c7bb799224f53edee9579 |
| Release version / tag | 0.21.0 / [v0.21.0](https://github.com/kn0w-thyself/s0ma/releases/tag/v0.21.0) |
| Release commit R | 62bbf1caa5341b5f3047e8e08c1b3cdebd7506b8 |
| Annotated tag object | 1c22eb8ec69a4ef5c31fce1ab7db66477df027e4 |
| Release PR | [s0ma #13](https://github.com/kn0w-thyself/s0ma/pull/13), reviewed and merged by Rob |
| Owner merge on main | d8016df2e45bcb68afbf9b2844571017010257a7 |
| Publication verification | [Release run 40245019756](https://github.com/kn0w-thyself/s0ma/actions/runs/40245019756), all jobs and critical verification steps passed |
| fr3d adoption | Not performed; separate implementation session |

Both implementation PRs are merged. The guidance SHA above identifies the
implementation before the handoff and Windows portability commits; its final
head was `2c302a69f3424dfc0872f64fffd04c6d536cdb3a`. A PR head is not a
release tag; downstream adoption must use the verified release identity.

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
adds two build/boot/consumer runs, original and renamed, with zero model calls
and zero external network calls. The guidance gate passed with DSL 7,992 and the
same other suite counts; the final combined gate is recorded in the adjacent
evidence JSON. Both use
the canonical `uv run python scripts/check.py`,
including type/lint checks, three-build equality, packaged guide equality,
cold installed-wheel checks and documentation gates. `git diff --check` passes.
Runtime CI passed all six OS/Python jobs and wheel building. Guidance CI began
after retargeting to main and reopening the PR. It exposed Windows subprocess
encoding in the new acceptance harness; local investigation also reproduced
Windows asyncio's need for a loopback control socket. The harness now uses
explicit UTF-8 and permits loopback while refusing external connections. The
adjacent evidence JSON records both regressions and their local checks. All six
jobs and wheel building passed on the final guidance head in
[CI run 40237011697](https://github.com/kn0w-thyself/s0ma/actions/runs/40237011697).
No authoring MCP surface snapshot, DSL grammar, IR schema or dependency direction
changed. Frozen audit results and probe attempts remain untouched.

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

## Release record and downstream boundary

The cut followed [docs/RELEASING.md](../RELEASING.md):

| Commit | SHA | Local canonical gate |
| --- | --- | --- |
| A, prepare as preview | da8a3f211079a930dcda100cd3f435677a33d9e0 | 11,158 passed, 30 skipped |
| R, compose for v0.21.0 | 62bbf1caa5341b5f3047e8e08c1b3cdebd7506b8 | 11,145 passed, 43 skipped |
| P, restore preview | 1fb42af9b068b58158ee21b1ee121c157828b966 | 11,158 passed, 30 skipped |

R's additional 13 skips are tests explicitly marked `preview_tree_only`; all
run on A and P. A and P have the identical tree
`742a9101b50e34133dfc78ef583125d4c6acb1e1`. Both A and P passed all six
OS/Python CI jobs and wheel building. Rob merged PR #13 with a merge commit
rather than a fast-forward; that merge preserves R and P and has exactly the
same tested preview tree. No history was rewritten. The annotated tag names R,
whose documentation identifies the release channel.

The [release workflow](https://github.com/kn0w-thyself/s0ma/actions/runs/40245019756)
passed on R: Python 3.11, 3.12 and 3.13 gates, exact wheel documentation
identity, GitHub publication, R2 mirroring and served-release verification.
The documentation-identity gate was armed before publication; its check, the
mirror step and the served check all ran successfully. The GitHub Release was
published at `2026-10-25T23:38:48Z` with four wheels and four source archives.
The served verifier confirmed that `latest` is 0.21.0, all four wheel hashes
match both the manifest and fresh builds, and the installer matches the
canonical script. No control-plane deployment or PyPI publication occurred.
Artifact digests and workflow evidence are in the adjacent evidence JSON.
This post-release handoff supersedes the preparation status captured inside the
tagged source. Install the immutable tag; use this updated record for publication
status and the downstream implementation prompt.

The runtime floors between sibling s0ma packages remain at 0.20.0 because this
cut introduces no new sibling API dependency. That does not make an older core
sufficient for fr3d's new observation contracts: adopt 0.21.0 for the existing
core, DSL and authoring MCP dependencies. Do not add studi0 to fr3d merely
because upstream releases four packages together.

Do not move this release tag or replace its immutable wheels. Any production
rollback uses the runbook's manifest-pointer procedure only with owner
approval. The next work is fr3d adoption and application fixes in its separate
session, followed by benchmark preparation. No fr3d changes or benchmark runs
were performed during this release.

## Copy/paste prompt for the separate fr3d session

The release is verified. Copy the following block into the separate fr3d
session; it includes the exact release identity and actual API changes.

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
4. This post-release s0ma docs/operations/fr3d-adoption-handoff.md, plus
   docs/operations/bench-runtime-contracts.md and
   docs/guides/application-observations.md at v0.21.0, including the executable
   fixture. The handoff inside the immutable tag records preparation status;
   this updated handoff records verified publication. Install from the tag.

Adopt s0ma 0.21.0, annotated tag v0.21.0, from kn0w-thyself/s0ma.
The tag must resolve to release commit
62bbf1caa5341b5f3047e8e08c1b3cdebd7506b8, which includes merged fixes #11
and #12 and release preparation #13. The tag object is
1c22eb8ec69a4ef5c31fce1ab7db66477df027e4. Verify those identities and the
successful release workflow 40245019756 before adopting. Do not substitute
moving main, a preview commit or another editable checkout. Record package
provenance, installed versions and import paths, and retain the upstream
compatibility requirements below. An unavailable or mismatched release is a
stop condition; it is not permission to invent a replacement pin.

At inspected fr3d main cbe17141f721f315e53c7bb799224f53edee9579, build-system
core/dsl pins and dev mcp pin in pyproject.toml used v0.20.0, runtime floors
were >=0.19.1, and Dockerfile plus boundary-check.yml, ci-windows.yml and
install_smoke.yml pinned v0.20.0. Re-inventory current main, update all existing
active pins/floors, lockfile if present, CI/build references and living docs to
0.21.0: existing Git pins use v0.21.0, and runtime floors requiring these fixes
must require >=0.21.0. No dependency lockfile was tracked in the inspected
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
