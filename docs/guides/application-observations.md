# Application observations that reach the consumer

An application must distinguish what it declares, what it observed and what it
actually did. This offline example follows one operation from authored contracts
through the build, isolated boot, public queries, assembled context and effects.
It uses temporary files, a fixture provider and a recording adapter. It has no
fr3d dependency, paid model, real credentials or home-directory data.

## Run and inspect

The agent prompt and patterns guide section 34 ship through the authoring MCP
resources. `s0ma docs show doc:guide/application-observations` returns this guide's
index entry and source locator. The executable fixture and this full guide live
in the matching source checkout; they are not installed as a new MCP resource.

From `packages/s0ma-dsl`, run:

```bash
uv run pytest tests/test_application_observations.py -q
```

The test copies the [fixture project](../../packages/s0ma-dsl/tests/fixtures/application_observations/pyproject.toml)
to a temporary directory and runs its [acceptance harness](../../packages/s0ma-dsl/tests/fixtures/application_observations/acceptance.py)
in a fresh Python process. The harness builds
[observation_app.s0ma](../../packages/s0ma-dsl/tests/fixtures/application_observations/src/observation_app.s0ma)
without a cache, boots the emitted module with the production ComponentRegistry,
and exercises the provider's actual dictionary of bound methods. It repeats the
entire chain after renaming FixtureProvider to ArchiveProvider and retrieve_digest
to collect_brief before compilation. No historical question bank supplies answers.
Generated artifacts stay in the temporary project.

The example lives in the DSL tests because it builds source. Core remains
independently installable. REST and core MCP checks run when their optional extras
are installed; the repository's complete gate installs both. No provider SDK is
required. External socket connections are refused by the harness during boot
and acceptance; loopback remains available for Windows asyncio's control sockets.
The zero network-call count refers to external calls. All file effects use the
temporary fixture directory.

## What is enforced and asserted

| Case | Effective result and evidence |
| --- | --- |
| Memory off | Refused write; no working or disk value; prompt path does not read an existing store. |
| Session memory | Requested persistence becomes working_only; disk stays unchanged; a fresh reader has no session value. |
| Persistent memory | Persisted result, working value, disk bytes and fresh reader agree. |
| Policy unavailable or unknown | Protected reads fail closed, including prompt delivery; diagnostic contains only a safe reason. |
| Missing or empty store | Distinct missing/empty observations; both are known writable starting states. |
| Malformed or unreadable store | Failed observation with null data; read-modify-write refuses and preserves existing bytes/state. |
| Persistence failure | Failed outcome; no working value is promoted as persisted. |
| Registry read/conversion | Known empty, unavailable, failed and partial survive into the actual recorded context. |
| Missing configuration | Readiness and execution use the same validator and name the missing client_id field. |
| Local configuration refresh | Source edits take effect only after explicit refresh; a failed refresh retains its revision. |
| Credential expiry | Presence and locally known expiry are separate; expired relay execution refuses; provider_verified remains false. |
| Alternate route | Direct execution needs no relay client identifier or credential. |
| Optional cache | Cache failure is reported alongside a successful main result; a successful cache callback is also asserted. |
| Context budget | Two memory entries, capped values and action names; operation detail is omitted with a reason if the 6,000-character budget would be exceeded. If detail still exceeds the budget, retain statuses with an explicit omission reason and a bounded follow-up query. |

The recording adapter receives the actual `deliver` call, not a separately
assembled test answer. Tests assert the static system instruction stays constant,
volatile observations stay in its context argument, and fixture-sensitive values
never appear in diagnostics or delivered context. Large memory and inventory
fixtures exercise truncation. Production registry composition passes ComponentSpec
objects to the converter and filters safe versus unsafe actions; it does not use
a stub that conveniently returns names.

The example enforces its own memory/readiness rules in executable bodies. The
`forbids` sentence describes that guard; s0ma does not execute prose. Neither
registration nor a declared smoke test establishes provider health. A host that
needs provider verification must run an explicitly authorized probe and record
its result and time separately.

This is a teaching fixture: single-writer atomic replacement, not a concurrent
storage service; local configuration, not OAuth; a fixed offline result, not
proof of provider reachability. Its status vocabulary belongs to this example,
not a universal s0ma application schema. A TYPE_USES edge or optional cache does
not make every operation dependent on that target. Inspect relation kinds and
the operation's contract before inferring impact or refusing an alternate route.

## Public semantic parity

The built fixture asserts canonical operation identity and contracts through
runtime inspection, library text, query-engine text, HTTP and core MCP. It checks
the emitted constant value, READS relationship, dependents and impact, then tests
register/unregister against retained and reconstructed adapters. Core's
[public observation matrix](../../packages/s0ma-core/tests/test_observation_contracts.py)
adds passed/failed/unavailable verification, alias ambiguity, canonical collisions,
framework filtering and failed snapshot reads without depending on the DSL.

Transport shapes intentionally differ. REST inventories include the full registry;
application-oriented views may exclude framework entries. Compare canonical
identity, evidence basis and outcomes within the same scope. See the
[runtime compatibility guide](../operations/bench-runtime-contracts.md) for the
nullable health/count fields, ambiguity responses and explicit snapshot refresh.

## Continue the authoring loop

After checking and building source, read canonical IR and then test the actual
application consumer. Assert reply, working state, disk and a fresh reader where
applicable. Use recording adapters for agent context, and ordinary callers for
libraries. Keep context bounded and provide targeted dependency/impact queries
instead of injecting the whole registry or maintaining a parallel answer catalog.

The [MCP authoring guide](mcp-authoring.md) retains its five executable authoring
calls. Its journey and transcript were reviewed and remain unchanged: application
acceptance is backed by the test above, not an invented MCP call. These additions
create no primary-surface coverage claim and require no authoring surface snapshot
change. Canonical agent/pattern guidance and packaged documentation carry the same
instructions through the normal documentation maintenance loop.
