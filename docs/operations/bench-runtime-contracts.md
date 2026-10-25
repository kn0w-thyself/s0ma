# Runtime observation compatibility and regression record

These changes are included in s0ma 0.21.0 and follow the October 24 offline audit. The implementation
base is `fd62a067b292f575c6845620a633af1d6b7e763f`. They change inspection
answers, not the DSL grammar, deterministic companion schema, or provider execution.
No new benchmark result or application adoption is claimed.

## Requirement ledger

| Audit ID | Reproduction and contract | Surface and regression evidence | Compatibility |
| --- | --- | --- | --- |
| S01 | REST claimed a pass when verification was unavailable. Missing verifier, thrown verification, and no results now mean unavailable. A completed report retains its actual pass/fail result. | `test_verification_meaning_through_public_adapters` covers HTTP, library, query engine and core MCP. | Nullable booleans/counts and explicit status; text says verification, not global health. |
| S02 | REST resolved an operation in prose and then rejected its literal name. Resolve once for both representations; preserve ambiguity including bare-name collisions. | `test_component_resolution_through_public_adapters`, `test_ambiguity_and_unknown_are_distinct`, `test_rest_resolves_once_and_accepts_package_qualified_names`. | Unique aliases now return 200; ambiguity returns 409 with candidates; unknown names retain their 404 text detail. |
| S03 | A bare Shared registration for alpha observed both alpha and beta. Coherent canonical/module/qualified identity now observes at most one component; only an unambiguous bare fallback is allowed. | `test_canonical_observation_identity`, `test_observation_filtering_and_supplied_snapshot_time`; test_application_observations adds build-backed acceptance. | `observed` may be null for unresolved identity; false means absence from the supplied registry scope. |
| S04 | Reusing an adapter after unregister retained its earlier observation. Snapshot semantics remain; reconstruct explicitly and replace the host's handler/context together. | `test_explicit_refresh_and_failed_refresh_preserve_snapshots`. | Additive capture metadata. Failed registry reads produce unavailable observations; invalid build artifacts still raise. |
| S05 | Adapter parity was not executable for these failures. A common fixture now exercises the applicable public paths; existing operation-contract, constant and reverse-edge tests remain. | `packages/s0ma-core/tests/test_observation_contracts.py`; build/IR composition lives in the DSL layer. | Transport and registry scopes differ deliberately, as described below. |
| S06 | Application results and failed observations need actual-effect tests. | [Executable application example](../guides/application-observations.md), replayed by test_application_observations for original and renamed providers. | No universal application result schema or automatic enforcement. |
| S07 | Declaration, readiness, observation and enforcement need separate evidence. | [Executable application example](../guides/application-observations.md), replayed by test_application_observations for original and renamed providers. | Existing integration declarations and manual manifests remain supported. |
| S08 | Optional dependencies and real provider types need composition tests. | [Executable application example](../guides/application-observations.md), replayed by test_application_observations for original and renamed providers. | No graph or grammar redesign. |

## Verification response table

`GET /self/health` continues to return HTTP 200 when the inspection request
completes. Its body says whether verification completed. HTTP success alone is
not a health verdict. The optional FastAPI and MCP dependencies stay optional.

| Evidence | status | passed | anomaly_count | reason |
| --- | --- | --- | --- | --- |
| Completed passing report | passed | true | measured count | null |
| Completed failing report | failed | false | measured count | null |
| Import of verifier unavailable | unavailable | null | null | VERIFIER_UNAVAILABLE |
| Verification raised an exception | unavailable | null | null | VERIFICATION_ERROR |
| No report or no verifier results | unavailable | null | null | NO_VERIFICATION_RESULTS |

Before, unavailable verification returned:

```json
{"text":"Health status: No verification data available.","passed":true,"anomaly_count":0,"erosion_coverage":null}
```

Now that request returns, for a verification exception:

```json
{"text":"Verification status: UNAVAILABLE. No verification data available.","status":"unavailable","passed":null,"anomaly_count":null,"reason":"VERIFICATION_ERROR","basis":"registered_verification_checks","checked_at":null,"erosion_coverage":null}
```

Completed reports include their actual `report_at` value as `checked_at`.
The basis is the registered verification checks. This does not establish
provider reachability, authorization, or whole-application correctness. Exception
messages are omitted because they can contain credentials; the stable reason code
is safe to retain. `/self/anomalies` also carries status and reason, and its total
is null when no observation exists. Its empty array then means no available
findings, not an observed zero. Existing boolean-only/count-only clients must
handle null and check status before claiming a pass or absence.

Library, query-engine and core MCP answers retain their text transports and
use `Verification status: PASSED`, `FAILED`, or `UNAVAILABLE`. The runtime build
adapter does not run these verifiers: `build_health` describes the artifact's
basis and `live_health` describes only registration evidence.

## Names and transport differences

For `GET /self/component/fixture_read`, a unique operation previously produced
404 after a successful library description. Now it produces 200:

```json
{"text":"fixture_read is an operation of alpha::FixtureProvider; this describes that component. ...","spec":{"name":"FixtureProvider","module_path":"alpha"},"resolved":{"query":"fixture_read","component":"alpha::FixtureProvider","operation":"fixture_read"}}
```

The abbreviated `spec` above retains the full existing ComponentSpec payload.
Canonical `alpha::FixtureProvider`, unique bare `FixtureProvider`, and supported
package-qualified `pkg.alpha::FixtureProvider` names resolve through the same
registry resolver. A component name takes precedence over an operation alias.

Multiple providers return HTTP 409 instead of the old generic 404:

```json
{"detail":{"code":"AMBIGUOUS_COMPONENT","query":"fixture_read","candidates":["alpha::FixtureProvider","beta::FixtureProvider"],"message":"Use a canonical component name from candidates."}}
```

Unknown names retain HTTP 404 and the existing string `detail`. The library
raises RegistryIntegrityError with candidates; core MCP and the query engine
return diagnostic text; the runtime adapter returns `ok: false` with
`AMBIGUOUS_COMPONENT` and candidates. Hosts must ask for a canonical candidate,
not select one silently. `ComponentResolution.operation` also retains an
ambiguous operation's name. Candidate order remains registration order for
operations, as before.

REST `/self/components`, graph and overview numeric inventory remain full-registry
projections. Library overview prose and the runtime overlay default to application
components when any exist, with framework counts retained. A framework-only
registry can describe itself. This scope difference is intentional; compare the
same selected population rather than equating every transport's counts.

## Observation identity and lifetime

One bare Shared registration with coherent `module_path: alpha` and
`qualified_name: alpha.Shared` now observes only `alpha::Shared`. A module-scoped
registration with package prefix `pkg.alpha` has the same canonical identity.
Conflicting metadata or a same-name collision without enough identity produces
`observed: null` for affected components. An unrelated coherent registration
establishes no observation of this build. Filtering applies before matching.

`live_health` now includes `lifetime: snapshot` and `captured_at`, taken from
RegistrySnapshot.snapshot_at, including when the host supplies an older snapshot.
No timestamp is added to a deterministic build artifact or hash. `partial` means
some canonical identities are unresolved; the overlay lists those in
`canonical_components_unknown` and the registrations in `unresolved_registrations`.
The bounded describe answer includes their counts, not their full lists.

After register/unregister or a host configuration event, reconstruct:

```python
from s0ma.runtime import self_inspect_adapter

replacement = self_inspect_adapter(manifest, registry=registry)
# Publish replacement.context and replacement.handle as one host-owned update.
# If replacement.context["live_health"]["status"] == "unavailable", publish
# that unavailable state. Do not relabel an older adapter as freshly observed.
adapter = replacement
```

No query refreshes tokens, authorizes, writes, or probes a provider. Reusing an
adapter reuses its original observation. It may be stale relative to a later
registry change; the capture time alone is not a freshness guarantee. A failed
registry read creates an unavailable overlay with null capture time and
`REGISTRY_SNAPSHOT_FAILED`. An invalid/tampered build raises SelfContextError;
if a host retains its last valid adapter, it must label that retained evidence as
stale and expose the failed refresh separately. A new adapter revalidates all
build hashes before reading the registry.

## Verification record

The original 87-test REST/runtime baseline passed on the implementation base.
The new 16-case public regression matrix failed against that unchanged source,
then passed against the implementation. The original audit outputs remain intact.
Early local test attempts exposed fixture setup errors (a test-module import,
a VerificationResult constructor argument, and a missing QueryEngine argument);
those attempts were retained separately and are not evidence of product defects.
The corrected baseline explicitly loaded the base checkout's core source in the
isolated worktree environment. See `bench-runtime-evidence.json` alongside this
page for exact commands, source identity and subsequent gate results.

The focused adapter suites passed 307 tests before two additional identity and
single-resolution cases were added. The final gate result is recorded with the
[review and adoption handoff](fr3d-adoption-handoff.md); a focused pass alone is
not a release gate. Both implementation PRs are merged and Rob has authorized
the four-package 0.21.0 release through [the release runbook](../RELEASING.md).
Check the handoff for verified publication identity before downstream adoption.
