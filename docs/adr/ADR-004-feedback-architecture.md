# ADR-004: Feedback architecture — placement, consent authority, identity, and the data boundary

**Status:** Accepted — owner-ratified 2026-08-27 (FD-1..FD-13, and the
walkthrough adjustments A-1..A-3)
**Date:** 2026-08-27
**Context:** `plans/s0ma-release-pipeline-feedback-1.md` (workstream FB),
`plans/notes/feedback_function_notes.md` (the owner's product notes)
**Frozen wire formats:**
[`../contracts/feedback-v1.md`](../contracts/feedback-v1.md)
**PRD authority:** `references/s0ma-prd.md` v1.9 — §7.7 FR-FB-1..12, the NFR-6
narrow feedback exception, NFR-8, INV-5, INV-6, INV-9

---

## Context

s0ma is entering a keyed beta. Testers are coding-agent users: the moment they
hit a confusing diagnostic, a missing capability, or a workaround they have to
repeat, they are inside an agent conversation — not in a browser, not in an
issue tracker. A feedback path that makes them leave that workflow collects
almost nothing. A feedback path that makes it *easy* for an agent to send
things on their behalf collects the wrong thing, because an agent has the whole
conversation, the source tree, and the environment in reach, and no reliable
sense of which parts are the user's secrets.

So the design problem is not "add an endpoint". It is: how does a product whose
entire thesis is *the system tells the truth about itself* collect feedback
through an agent without becoming the kind of software that quietly uploads
things. Every decision below is downstream of that.

Three existing constraints bound the answer. INV-9 says the runtime is never
gated and `s0ma-core` needs no account or network. NFR-6 (pre-v1.9) said MCP
tools may not write outside the given project tree and there is no network
access in the load-bearing path. INV-5 says emitted artifacts are
deterministic. A feedback function touches all three, which is why the PRD
amendment (v1.9) is part of this decision and not a follow-up.

---

## Decision

### 1. Package placement: engine in `s0ma-dsl`, wrapper in `s0ma-mcp`, nothing in core

The shared engine — envelope model, deterministic redaction, context
allow-listing, hashing, drafts, token store, HTTPS client — lives in
`s0ma-dsl` as `s0ma_dsl.feedback.*`, because `s0ma-dsl` owns the `s0ma` CLI and
the CLI is the universal, client-independent path (FR-FB-6). `s0ma-mcp`
authors two tools and one prompt that wrap that engine and add exactly one
thing the CLI does not need: the approval interaction. `s0ma-core` gains no
feedback, credential, account, or network code.

The dependency direction is unchanged:

```text
s0ma-mcp -> s0ma-dsl -> s0ma-core
```

A fifth distribution (`s0ma-feedback`) was considered and rejected: it would
add a wheel to every installer, mirror, manifest, and release gate in the
pipeline for a component with no independent product identity. Feedback is a
feature of the authoring toolchain, and the authoring toolchain is already two
packages.

Core staying out is not tidiness, it is INV-9. A deployed application that
imports `s0ma` must not acquire a transitive path to an HTTP client, a token
file, or an account concept. The boundary is testable: the feedback package
introduces no new third-party dependency (INV-6) and uses only
`urllib.request` from the standard library.

### 2. Consent authority: the approval boundary is client-side, and we say so

`submit_feedback` MUST NOT treat a model-authored `approved: true` argument as
proof of consent. An argument like that is written by the same process that
wants to submit; it evidences nothing. Approval must come from an interaction
the model cannot forge — MCP elicitation where the client declares the
capability, or a TTY prompt in the CLI.

Where a client cannot offer elicitation, the MCP path **refuses**:
`{ok:false, code:"APPROVAL_UNAVAILABLE", remediation:"run: s0ma feedback"}`,
with a draft preserved locally. There is deliberately no trust-the-agent
fallback (FD-6). A refusal that points at a working alternative costs a user
thirty seconds; a fallback that trusts an unverifiable claim costs the product
the one promise it is selling.

The honest part is what the server can and cannot know. The control plane
records `approval_method` ∈ `{'mcp_elicitation','cli_tty'}` on the consent row,
and it **cannot verify that value**. It is a client self-report: a compromised
or hostile client could send either string. We record it anyway because it is
operationally useful (which surface produced this consent) and we document the
limit here so that no later reader mistakes a stored string for a proof. The
real enforcement lives where the interaction happens, on the user's machine,
and the mechanism that keeps it honest is the exact-payload approval plus hash
continuity (§5), not a server-side assertion.

The same honesty rule governs the annotations. `prepare_feedback` is pure — no
draft write, no network — so `readOnlyHint=true` is *true*. The notes flagged
the temptation to have prepare quietly persist a draft; that would have made
the annotation a lie, so drafts are written by `submit_feedback` and by the CLI
instead.

### 3. Authentication: a scoped token exchanged once from the license key

The beta license key already exists and already authorizes wheel downloads and
entitlement checks. Sending it alongside feedback would put a
distribution-grade credential into the same code path as user-authored prose,
on every submission, from every device.

Instead the key is exchanged **once** for a narrowly scoped feedback token
(`POST /api/feedback/token`), which is random, opaque, hash-at-rest, expiring
(180 days, FD-3), revocable, per-device, and authorized for nothing but
`feedback:write` and `feedback:delete-own`. It cannot download a wheel, read an
account, or change a subscription. The installer performs the exchange
non-fatally after the doctor step; `s0ma feedback enroll` performs it later.
After the exchange the s0ma MCP process never needs the license key again
(FR-FB-5).

Revocation composes: revoking an account's license keys revokes its feedback
tokens in the same operation.

### 4. Identity at rest: keyed pseudonymization (FD-9)

Feedback content rows carry `reporter_id` — the first 16 hex characters of
`HMAC-SHA256(FEEDBACK_REPORTER_SECRET, account_id)` — and carry `account_id`
itself **only** when the reporter answered yes to the contact question.

Two simpler designs were rejected for the same reason:

- **Bare `account_id` on content rows** links every report to an identifiable
  account by construction, which makes pseudonym-first operator display a UI
  convention rather than a property of the data.
- **An unkeyed hash of `account_id`** does not fix that. Account ids are small
  integers; anyone with read access to the table can hash `1..100000` and
  invert the whole column in under a second. An unkeyed digest of a small
  domain is an obfuscation, not a pseudonym.

The keyed HMAC makes inversion require the secret, which lives as a Wrangler
secret (`.dev.vars` locally) and is not in the database, not in the repo, and
not in a backup of the database. The operator sees a stable 16-hex reporter and
can group a reporter's history without seeing who they are; the email exists
only where the reporter granted contact permission, and even there the admin
view reaches it through an explicit reveal control joining `accounts`.

Ownership checks for `GET /api/feedback` and `DELETE /api/feedback/<id>`
recompute the HMAC from the authenticated token's account and compare. They
never read `account_id` off a content row — which is what lets self-serve
listing and deletion work for reports that carry no account linkage at all.

**Rotation caveat (accepted).** Reporter continuity is a function of the
secret. Rotating `FEEDBACK_REPORTER_SECRET` changes every future
`reporter_id`, so reports written before a rotation stop grouping with reports
written after it, and pre-rotation reports become unreachable through
self-serve list/delete. This is deliberate — it is the same property that makes
the column non-invertible — and it means rotation is an operational decision
with a data consequence, not a routine hygiene task. If continuity across a
rotation is ever required, it needs a designed migration (re-key the column
under the old and new secrets in one pass), not an ad-hoc rotation.

FD-9 unlinks **content**, not **authentication**: `feedback_tokens` keeps its
`account_id` foreign key, because it *is* the auth layer. Splitting that would
make revocation impossible.

### 5. Data flow and hash continuity

```text
compose (local)  ->  redact v1 (local, deterministic)  ->  canonical JSON
      -> sha256  ->  EXACT-PAYLOAD APPROVAL (elicitation | TTY)
      -> HTTPS POST + Idempotency-Key  ->  server re-validates + re-hashes
      -> D1 write (submission + consent + event, one batch)  ->  receipt
```

The invariant across that pipeline is one line:

```text
approved hash = transmitted hash = stored hash = receipt hash
```

Everything else is arranged to protect it. The user approves the actual bytes,
not a summary of different hidden bytes. An edit during the approval round does
not mutate an approved payload in place — it returns to a fresh
`prepare_feedback` round that recomputes the hash, so "approved" always refers
to something that exists. The server **rejects** a payload whose sensitive
screen matches (`SENSITIVE_CONTENT`, naming the type and never the value)
rather than sanitizing it, because a server-side rewrite would store bytes the
user never approved and silently break the chain (notes §7.4). And no surface
tells a user their feedback was received without a receipt carrying the
matching hash.

Idempotency is part of the same promise: the client mints one key per draft and
reuses it on retry, so a timeout after server acceptance is recoverable without
creating a second report. There are no automatic retries — a network failure
returns a structured result, keeps the draft, and prints the retry command
(FR-FB-8).

Feedback is never load-bearing. A failure anywhere in that pipeline cannot
change an authoring, build, check, import, or runtime result.

### 6. D1 is the system of record; R2 is not, and attachments stay out

Structured feedback goes to the existing control-plane D1 database. The
workflow needs querying, filtering, status transitions, deduplication by
idempotency key, relational consent rows, and an append-only event trail —
every one of which object storage would force us to reimplement badly. The
receipt means "the system of record accepted this", which requires a
synchronous write to that system of record; a Queue is therefore not the
canonical write path (it stays deferred for notifications and enrichment).

Reusing the existing D1 database rather than provisioning a second one buys
direct reuse of the account/key model, one protected admin area, one migration
lane, and one backup story. A separate database can be reconsidered if scale,
residency, or isolation requirements ever justify the operational split.

Attachments are out of the MVP (FD-11), and the boundary is recorded now so it
cannot be crossed casually later: if attachments ever land, they go in a
**separate private bucket** (`s0ma-feedback-attachments`) with lifecycle
deletion and a D1 metadata row per object — **never** the `s0ma-dist`
wheel-distribution bucket. Wheels and user-supplied content have different
trust, access, retention, backup, and deletion requirements; sharing a bucket
would mean the deletion path for a tester's report runs through the bucket that
serves releases. `feedback_attachments` is deliberately not created.

### 7. INV-5 governs artifacts, not runtime state

Draft ids, idempotency keys, and the installation pseudonym are random by
design. Timestamps appear in receipts and events. None of that violates INV-5,
because INV-5 governs **emitted artifacts** — the deterministic outputs of the
compiler, whose byte-equality is what makes drift detectable (P-4).

The boundary is recorded here explicitly so no executor over-applies the
invariant and tries to make a draft id deterministic:

| Governed by INV-5 (deterministic) | Feedback runtime state (randomness required) |
|---|---|
| Emitted Python, `.s0ma.json` IR, `.s0ma.map`, `build.s0ma.json`, rendered docs, self-context | `~/.s0ma/feedback-drafts/fbd_<8-hex>.json`, `installation_id`, `feedback-token`, `feedback-receipts.jsonl` |
| Inside the project tree, committed, drift-gated | Outside every project tree, never committed, never drift-gated |

The feedback state directory is user-scoped and lives at `~/.s0ma/`
(Windows `%USERPROFILE%\.s0ma`), permissions 0700/0600 where the platform
supports them and best-effort where it does not. It is the only write the NFR-6
narrow feedback exception permits, and it is deliberately outside every project
tree so that "no MCP tool writes outside the given project root" remains true
of the project tree itself.

The installation pseudonym is a locally generated random identifier, never a
hardware fingerprint, and rotating it is deleting one file.

### 8. Suggest mode is served conditionally, per render (FD-13)

Consent modes are `off` (default), `suggest` (beta), and `standing`
(deferred). Per-item approval binds in every shipped mode.

The beta scaffold writes `feedback = "suggest"` into a project's `[tool.s0ma]`
table and discloses that in the scaffold summary. The MCP server serves the
*suggest-offer* line — "you may offer to draft s0ma feedback when you hit
s0ma-specific friction; non-blocking, specific, only prepare after the user
agrees" — conditionally per render, reading the project's table through the
same narration-rule mechanism D-11 established for studi0 (`"suggest"` →
present; `"off"` or an absent table → absent). Setting `"off"` silences
agent-initiated *offers* only: every explicit route — the prompt, the skill, the
CLI, a direct request — keeps working, because a user asking to send feedback
is not something a config key should be able to veto.

The explicit-intent **recognition** line is unconditional for the same reason.

Serving the offer conditionally rather than always costs nothing at render time
and keeps a project that opted out from carrying instructions it declined.

### 9. Recognition is taught, not inferred (A-1)

The MCP server cannot observe a conversation that has not invoked it, so
recognition has to be taught to the agent — through concise server
instructions, tool descriptions, the `feedback` prompt, and the optional
client-side skill. Two rules bound it.

The agent reacts to **explicit** feedback intent and never infers consent from
frustration. A user who is annoyed has not asked to file a report.

And when a user expresses feedback intent without naming s0ma or kn0wthyself
("I have some feedback"), the agent confirms the feedback is about s0ma before
starting the journey. Testers use other tools that also collect feedback;
hijacking an ambiguous sentence would be a small betrayal of exactly the trust
this whole design is built to earn. Mentions that name s0ma, the
`/s0ma-feedback` skill, and the MCP prompt are unambiguous and need no
confirmation.

### 10. The deferred set

Not built, not scaffolded, not partially wired (notes §13.2): standing
automatic consent; automatic background submission; source, transcript, or
raw-log inclusion; R2 attachments; Queue-based enrichment and notifications;
automatic issue-tracker creation; public feature-request boards; remote product
telemetry; AI-only redaction; semantic clustering or automated prioritization;
and contact automation.

Two of these have schema affordances so they can land later without migration
churn, and that is the full extent of the anticipation: `feedback_consents`
carries `mode`/`scopes_json`/`expires_ts`/`revoked_ts` for standing consent
(FD-10), and `channel` accepts a reserved `web` value. Neither has code.

The existing local telemetry sink stays local. Its `sanitize` behavior is
bounded `repr(...)` truncation, not secret or PII redaction, so telemetry
records are never uploaded wholesale; only the §5-allow-listed extracts may
enter an envelope, and remote telemetry — if it is ever wanted — is a separate
PRD amendment with its own schema and consent policy, not something smuggled
through a free-form feedback field (FR-FB-12).

---

## Consequences

- The PRD needed a real amendment, not a reinterpretation: v1.9 adds §7.7
  (FR-FB-1..12) and a narrow, named exception to NFR-6 covering exactly one
  directory (`~/.s0ma/`) and exactly one network call (a user-approved,
  locally-redacted envelope over HTTPS). The pre-existing guarantees stand
  otherwise, and the amendment states them: preparation is always local and
  network-free, submission always requires the approval interaction, feedback
  failures never alter an authoring/build/check/import/runtime result, and
  `s0ma-core` gains no feedback, credential, or network code.
- The MCP surface grows by exactly two tools and one prompt (FD-5), recorded as
  a versioned revision of the 0.14.0 surface-budget contract. Descriptions are
  written under the context-economy rule (NFR-5): the long privacy story lives
  in the contract document, not in every tool description.
- A client that cannot do elicitation has a working path — the CLI — and gets
  told so. That is the whole fallback, by design.
- The redaction profile is versioned (`REDACTION_PROFILE = "v1"`) and its
  adversarial corpus is the executable definition. Changing a rule is a
  contract re-freeze, which means redaction cannot drift quietly the way a
  helper function would.
- Deletion is a real product feature, not a support request: a user can list
  and delete their own reports by receipt id, and `delete --all` requires an
  explicit counted confirmation (A-3). Deletion nulls the envelope, sets the
  tombstone, and keeps a minimal audit skeleton (FD-1).
- Rotating the reporter secret is now a documented operational decision with a
  data consequence (§4), which is a cost the alternative designs did not have —
  and is the price of a column that cannot be inverted from the database alone.
- Everything above is falsifiable at the gate: hash continuity is asserted
  end-to-end in tests and once against production, the no-network property of
  the prepare path is proven with a socket guard, and the surface delta is
  reviewed as an exact diff.
