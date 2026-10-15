# s0ma feedback contract — `s0ma-feedback@1` (feedback-v1)

**Status:** Frozen contract — owner-ratified 2026-08-27
**Date:** 2026-08-27
**Applies to:** the beta feedback function shipping in 0.19.0 across
`s0ma-dsl` (engine + CLI), `s0ma-mcp` (tools + prompt), and the kn0wthyself
control plane (`account.kn0wthyself.ai`). `s0ma-core` is untouched.
**Governing ADR:**
[`ADR-004`](../adr/ADR-004-feedback-architecture.md)
**Governing PRD clauses:** `references/s0ma-prd.md` v1.9 — §7.7 (FR-FB-1..12),
NFR-6 narrow feedback exception, NFR-8, INV-6, INV-9
**Owner decisions frozen here:** FD-1, FD-2, FD-3, FD-8, FD-9, FD-11, and the
owner walkthrough adjustments A-1, A-2, A-3
**Source of record:** `plans/s0ma-release-pipeline-feedback-1.md` §5.1–§5.8 and
§5.12, and `plans/notes/feedback_function_notes.md` (the owner's product notes)

## 0. Authority and scope

Per the AGENTS.md authority order this document is a **frozen contract**
(authority level 4): it sits below the owner's current instruction and an
owner-approved plan (1), the PRD (2), and the versioned DSL spec (3), and above
executable tests, implementations, READMEs, and guides. It is authoritative
over the plan section it was copied from: once this file exists,
`plans/s0ma-release-pipeline-feedback-1.md` §5 is that plan's *draft* of this
contract, and this file governs.

No milestone may rename a surface, change a wire format, add a persisted field,
loosen a cap, or alter a redaction rule below without owner review and a
versioned re-freeze recorded in §13. A green gate is evidence, not permission.

**Section numbering mirrors the source plan:** contract §N freezes plan §5.N.
Frozen text is reproduced with its original cross-references intact, so a
"§5.N" appearing inside it resolves to §N of this document (`§5.5` → §5,
`§5.3` → §3, `§5.1.4` → §1.4). §9, §10, and §11 are deliberately *not* frozen
here and say so. References written as plain "§N" are this document's own.

**Spelling (INV-1):** the product is `s0ma` — lowercase s, digit zero, m, a — in
every identifier, config key, document, and user-visible string in this
contract's scope.

---

## 1. Recorded refinements of the owner's notes (plan §5.1)

These are deliberate, recorded refinements of
`plans/notes/feedback_function_notes.md`; the notes remain binding wherever
this contract does not refine them.

1. The envelope gains one optional free-prose field `details` (≤ 8000 chars)
   — the CLI's interactive compose needs a place for prose that is not
   expected/actual/reproduction.
2. `prepare_feedback` is **pure** (no draft write, no network) so its
   `readOnlyHint=true` is honest (the notes flagged this exact honesty risk).
   Drafts are written by `submit_feedback` on decline/failure and by the CLI.
3. No `--anonymous` flag anywhere: submissions are pseudonymous by design
   (notes trust rule 6 — never claim anonymity the system cannot prove).
   Operator-side pseudonym-first display (FD-9) is the privacy mechanism.
4. INV-5 determinism governs **emitted artifacts**; feedback runtime state
   (draft ids, idempotency keys, pseudonyms) requires randomness by design.
   ADR-004 records this boundary so executors do not over-apply INV-5.
5. Consent rows: MVP writes one `feedback_consents` row per submission
   (`mode='per_submission'`, `approval_method` ∈
   `{'mcp_elicitation','cli_tty'}`) in the same transaction — satisfying the
   notes' `consent_id NOT NULL` without building standing-consent machinery.
6. The server **rejects** on detected sensitive content
   (`SENSITIVE_CONTENT`), never rewrites — preserving hash continuity
   (notes §7.4).

---

## 2. Endpoints (plan §5.2)

All endpoints live on the existing Cloudflare control plane and sit behind the
established D-5 structured-error contract.

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /api/feedback/token` | `Bearer <license-key>` (entitled: `free_tester`/`active`) | Exchange for a scoped feedback token. Body `{"pseudonym": "<opaque-id>"}` optional. 200: `{ok, token, token_prefix, expires_ts, scopes}` — plaintext shown once; hash-at-rest. Rate: 5/hr/key. Logs `feedback_token` event. |
| `POST /api/feedback` | `Bearer <feedback-token>` (scope `feedback:write`) | Submit one envelope. Headers: `Idempotency-Key: <client-uuid>` (required), `Content-Type: application/json`. Body: `s0ma-feedback@1` envelope. 200: receipt (§5.3). Same key replays the original receipt with `"replayed": true`. Rate: 10/hr/token, 30/day/account (+ existing IP limits). |
| `GET /api/feedback` | `Bearer <feedback-token>` (scope `feedback:write`) | List the caller's own reports (matched by recomputing `reporter_id` from the token's account): newest-first, ≤ 100 rows of `{feedback_id, received_ts, category, impact, summary, status}`. Rate: 30/hr/token. |
| `DELETE /api/feedback/<id>` | `Bearer <feedback-token>` (scope `feedback:delete-own`) | Deletes exactly ONE own report (ownership = `reporter_id` recompute match; 404 otherwise, non-enumerating) per FD-1 semantics. 200 `{ok, feedback_id, status:"deleted"}`. Rate: 30/hr/token. |
| `GET /admin/feedback` (+ `POST /admin/feedback/update`) | Cloudflare Access (like `/admin/`) | Inbox: list/filter/detail/status transitions/notes-as-events/deletion honoring. |

### 2.1 Error codes

Error codes (all `{ok:false, code, remediation}` + correct HTTP status):
`INVALID_TOKEN` 401 · `NOT_ENTITLED` 403 · `SCHEMA_INVALID` 400 ·
`PAYLOAD_TOO_LARGE` 413 · `SENSITIVE_CONTENT` 422 · `RATE_LIMITED` 429
(+ `Retry-After`) · `NOT_FOUND` 404 · `BAD_REQUEST` 400. New codes join the
D-5 matrix; the installer/docs troubleshooting tables gain rows at FB-M10.

Tabulated for implementers:

| Code | HTTP | Raised when |
|---|---:|---|
| `INVALID_TOKEN` | 401 | Missing/malformed/unknown/expired/revoked bearer token, or a token lacking the required scope |
| `NOT_ENTITLED` | 403 | Token-exchange caller's account is not `free_tester`/`active` |
| `SCHEMA_INVALID` | 400 | Envelope fails schema tag, enum, cap, or context-allow-list validation |
| `PAYLOAD_TOO_LARGE` | 413 | Serialized body exceeds 32 KB |
| `SENSITIVE_CONTENT` | 422 | Server-side sensitive screen matched; response names the offending **type**, never the value |
| `RATE_LIMITED` | 429 | Any limit in the table above; response carries `Retry-After` |
| `NOT_FOUND` | 404 | Unknown feedback id, or an id owned by another reporter (non-enumerating) |
| `BAD_REQUEST` | 400 | Missing `Idempotency-Key`, wrong content type, malformed JSON |

Deletion never returns 403 for a wrong owner: ownership failure and
non-existence are indistinguishable by design.

### 2.2 Feedback token format

Feedback token format: `s0ma_fb_` + base64url(32 B), display prefix = first
12 chars. Hash-at-rest identical to the license-key discipline (H2/D-3).
Multiple live tokens per account allowed (per-device); revocation:
account-level revocation revokes its feedback tokens too.

Expiry is 180 days (FD-3). The license key is exchanged for this token once and
**never** accompanies an envelope (FD-4, FR-FB-5).

### 2.3 Identity at rest (FD-9)

Identity at rest (FD-9): the CP holds a Wrangler secret
`FEEDBACK_REPORTER_SECRET` (local dev: `.dev.vars`); `reporter_id` = first
16 hex chars of HMAC-SHA256(secret, account_id). Feedback content rows carry
`reporter_id` always and `account_id` only when `contact_ok=1`; the tokens
table keeps its account linkage (it IS the auth layer — FD-9 unlinks
content, not authentication).

Binding implementation notes:

- The HMAC key is the secret's raw UTF-8 bytes; the message is the decimal
  ASCII rendering of `account_id` with no padding, prefix, or separator
  (e.g. account `41` → message bytes `b"41"`).
- `reporter_id` is the first 16 characters of the lowercase hex digest
  (64 bits of the 256-bit MAC).
- Bare account numbers and unkeyed hashes of account numbers are **rejected**:
  small integers enumerate trivially under an unkeyed digest.
- Ownership checks (`GET /api/feedback`, `DELETE /api/feedback/<id>`) recompute
  `reporter_id` from the authenticated token's account and compare; they never
  read `account_id` off a content row.
- Rotating `FEEDBACK_REPORTER_SECRET` resets reporter continuity: reports
  written before the rotation stop matching the same reporter afterwards. That
  is an accepted, documented consequence (ADR-004).

---

## 3. Envelope, canonical serialization, and receipt (plan §5.3)

### 3.1 Envelope `s0ma-feedback@1`

Envelope `s0ma-feedback@1` — the notes §8 shape plus `details`:
required `schema`, `category`, `impact`, `summary` (≤ 400 chars);
optional `expected` (≤ 2000), `actual` (≤ 2000), `details` (≤ 8000),
`reproduction` (≤ 10 steps × 500 chars), `context` (≤ 4 KB JSON: the §5.5
allow-list only), `privacy` `{profile:"metadata_only", includes_source:false,
includes_transcript:false, redacted:{<type>:<count>...}}`. Total serialized
body ≤ 32 KB. **Canonical serialization for hashing:** UTF-8 JSON,
`sort_keys=True`, separators `(",", ":")`; hash = `"sha256:" + hex`. The
envelope carries **no** account identity, email, license key, or trusted
approval flag (server-side facts only). Client `User-Agent`:
`s0ma-feedback/<version>`.

| Field | Required | Type | Cap |
|---|:--:|---|---|
| `schema` | yes | string | exactly `s0ma-feedback@1` |
| `category` | yes | string | one of §8 `category` |
| `impact` | yes | string | one of §8 `impact` |
| `summary` | yes | string | ≤ 400 chars |
| `expected` | no | string | ≤ 2000 chars |
| `actual` | no | string | ≤ 2000 chars |
| `details` | no | string | ≤ 8000 chars |
| `reproduction` | no | string[] | ≤ 10 entries, each ≤ 500 chars |
| `context` | no | object | ≤ 4 KB serialized; keys ⊆ §5 allow-list |
| `privacy` | no | object | `{profile, includes_source, includes_transcript, redacted}` |

Character caps count Unicode code points. The 32 KB body cap is measured on the
UTF-8 bytes of the transmitted body and is checked **before** JSON parsing on
the server. An unknown top-level key is `SCHEMA_INVALID`, not an ignored field.

### 3.2 Canonical serialization and hashing — binding implementation notes

The frozen sentence in §3.1 is the rule. These notes pin the details that make
a Python and a TypeScript implementation byte-identical; they add precision and
change nothing:

1. Keys are sorted at **every** object depth, ascending by Unicode code point.
   Every key in this contract is ASCII, so a JavaScript `Array.prototype.sort()`
   (UTF-16 code-unit order) and Python's `sort_keys=True` (code-point order)
   agree; a non-ASCII key is `SCHEMA_INVALID` and can never arise.
2. Separators are exactly `,` and `:` — no whitespace anywhere, no trailing
   newline.
3. Non-ASCII characters are emitted **literally as UTF-8**, never as `\uXXXX`
   escapes. In Python that means `ensure_ascii=False`; JavaScript's
   `JSON.stringify` already does this. Getting this wrong is the single most
   likely cause of a cross-language hash mismatch — §3.3 gives the fingerprint.
4. Array order is authored order and is never sorted.
5. `payload_sha256` is `"sha256:"` + the lowercase hex SHA-256 of those UTF-8
   bytes.
6. The hash covers the envelope alone. Transport headers (`Idempotency-Key`,
   `Authorization`), the `approval_method` request field, and every
   server-derived fact are outside it.

Reference implementations (both MUST reproduce §3.3):

```python
import hashlib, json

def canonical_bytes(envelope: dict) -> bytes:
    return json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

def payload_sha256(envelope: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(envelope)).hexdigest()
```

```ts
function canonicalize(v: unknown): unknown {
  if (v === null || typeof v !== "object") return v;
  if (Array.isArray(v)) return v.map(canonicalize);
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(v as object).sort()) {
    out[k] = canonicalize((v as Record<string, unknown>)[k]);
  }
  return out;
}

export function canonicalJson(v: unknown): string {
  return JSON.stringify(canonicalize(v));
}

export async function payloadSha256(v: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson(v));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return "sha256:" + hex;
}
```

### 3.3 Cross-language test vector (normative)

Both the `s0ma-dsl` implementation (FB-M4) and the control-plane implementation
(FB-M2) MUST reproduce this vector exactly. It carries an em dash (U+2014) so
that a wrong `ensure_ascii` setting fails the test rather than passing silently.

Input envelope (authored key order deliberately unsorted):

```json
{
  "schema": "s0ma-feedback@1",
  "category": "friction",
  "impact": "minor",
  "summary": "check named the rule but not the declaration to edit.",
  "expected": "A declaration-level remediation — name the field to edit.",
  "context": {
    "s0ma_version": "0.19.0",
    "os": "macos",
    "python": "3.13",
    "cohort": "beta"
  },
  "privacy": {
    "profile": "metadata_only",
    "includes_source": false,
    "includes_transcript": false,
    "redacted": {"paths": 1}
  }
}
```

Canonical serialization (one line, no trailing newline):

```text
{"category":"friction","context":{"cohort":"beta","os":"macos","python":"3.13","s0ma_version":"0.19.0"},"expected":"A declaration-level remediation — name the field to edit.","impact":"minor","privacy":{"includes_source":false,"includes_transcript":false,"profile":"metadata_only","redacted":{"paths":1}},"schema":"s0ma-feedback@1","summary":"check named the rule but not the declaration to edit."}
```

| Property | Value |
|---|---|
| Canonical byte length (UTF-8) | `400` |
| Em dash byte sequence | `e2 80 94` (present literally; never `—`) |
| `payload_sha256` | `sha256:70265543186546875ad5b349b0ef581023add017b13c161fbac4d43597169d46` |

Negative control — the same envelope serialized with ASCII escaping
(`ensure_ascii=True`, the Python default) produces
`sha256:72e528051e50ba44a03d3609982215b808ce4371688b0096c1611500dec4d287`.
An implementation reporting that digest has bug (3) above, not a content
difference.

### 3.4 Receipt `s0ma-feedback-receipt@1`

Receipt `s0ma-feedback-receipt@1`:
`{schema, ok:true, feedback_id:"fb_<opaque>", received_ts:<epoch-ms>,
payload_sha256:"sha256:<hex>", status:"received"}` (+ `replayed:true` on
idempotent replay). Hash continuity invariant: approved = transmitted =
stored = receipt (notes trust rule 4).

```json
{
  "schema": "s0ma-feedback-receipt@1",
  "ok": true,
  "feedback_id": "fb_9f3c1e0a7b5d2648c1a0f4e7b9d3a250",
  "received_ts": 1787850000000,
  "payload_sha256": "sha256:70265543186546875ad5b349b0ef581023add017b13c161fbac4d43597169d46",
  "status": "received"
}
```

A client MUST NOT tell the user that feedback was received without a receipt
carrying a matching `payload_sha256` (notes §3.5).

---

## 4. Vocabulary (plan §5.4, FD-8)

- `category`: `bug` · `friction` · `idea` · `documentation` ·
  `diagnostic_quality` · `agent_behavior` · `performance` ·
  `privacy_or_trust` · `other`
- `impact`: `blocked` · `degraded` · `minor` · `idea`
- `status`: `received` · `triaged` · `needs_information` · `planned` ·
  `resolved` · `closed` · `duplicate` · `deleted`
- `channel`: `mcp` · `cli` (`web` reserved)

These lists are closed. Adding or renaming a member is a contract re-freeze
(§13) plus a D1 `CHECK`-constraint migration, never an incidental change.

---

## 5. Context allow-list (plan §5.5) — nothing else enters `context`

`s0ma_version` + per-distribution versions (absent → null) ·
client `{name, version}` when the host exposes them (MCP `clientInfo`;
CLI: null) · MCP protocol version (mcp channel only) · `python` (major.minor)
· `os` family (`macos`/`linux`/`windows`) · `architecture` ·
`surface` `{kind, name}` · `diagnostic_codes[]` · outcome (`success`/
`failure`) · duration **bucket** · cohort (`beta`) · `pseudonym` (the random
installation id — never a hardware fingerprint; stored at
`~/.s0ma/installation_id`, rotatable by deleting the file).

The allow-list is enforced twice: the client builds `context` from this list
only (it never copies a caller-supplied map through), and the server rejects an
envelope whose `context` keys are not a subset of it (`SCHEMA_INVALID`).
Excluded by construction, and never addable without a PRD amendment: source
code, file contents, prompts, conversation transcripts, raw stdout/stderr,
stack traces, git remotes, repository or organization names, account email,
license keys, and hardware identifiers.

---

## 6. D1 schema (plan §5.6) — `kts-website-3/migrations/0005_feedback.sql`

```sql
CREATE TABLE feedback_submissions (
  id                   TEXT PRIMARY KEY,            -- "fb_" + hex(16 random bytes)
  schema_version       TEXT NOT NULL,               -- "s0ma-feedback@1"
  reporter_id          TEXT NOT NULL,               -- FD-9: 16-hex keyed HMAC of account_id; never the raw id
  account_id           INTEGER REFERENCES accounts(id),  -- NULL unless contact_ok=1 (FD-9)
  created_ts           INTEGER NOT NULL,            -- client-declared, bounded ±48h of received_ts
  received_ts          INTEGER NOT NULL,            -- server epoch-ms
  channel              TEXT NOT NULL CHECK (channel IN ('mcp','cli','web')),
  category             TEXT NOT NULL CHECK (category IN ('bug','friction','idea','documentation','diagnostic_quality','agent_behavior','performance','privacy_or_trust','other')),
  impact               TEXT NOT NULL CHECK (impact IN ('blocked','degraded','minor','idea')),
  summary              TEXT NOT NULL,
  payload_json         TEXT,                        -- exact approved envelope; NULL after deletion (FD-1)
  payload_sha256       TEXT NOT NULL,
  consent_id           TEXT NOT NULL REFERENCES feedback_consents(id),
  idempotency_key      TEXT NOT NULL UNIQUE,
  contact_ok           INTEGER NOT NULL DEFAULT 0,
  status               TEXT NOT NULL DEFAULT 'received',
  retention_expires_ts INTEGER,
  deleted_ts           INTEGER
);
CREATE INDEX idx_feedback_status   ON feedback_submissions(status, received_ts);
CREATE INDEX idx_feedback_reporter ON feedback_submissions(reporter_id, received_ts);
CREATE INDEX idx_feedback_category ON feedback_submissions(category, received_ts);

CREATE TABLE feedback_consents (
  id              TEXT PRIMARY KEY,                 -- "fc_" + hex(16 random bytes)
  reporter_id     TEXT NOT NULL,                    -- FD-9: no account linkage on consent rows
  policy_version  TEXT NOT NULL,                    -- privacy/consent copy version, e.g. "beta-1"
  mode            TEXT NOT NULL CHECK (mode IN ('per_submission','standing')),
  scopes_json     TEXT,                             -- NULL for per_submission (MVP)
  approval_method TEXT NOT NULL CHECK (approval_method IN ('mcp_elicitation','cli_tty')),
  granted_ts      INTEGER NOT NULL,
  expires_ts      INTEGER,
  revoked_ts      INTEGER,
  install_pseudonym TEXT
);

CREATE TABLE feedback_events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts            INTEGER NOT NULL,
  feedback_id   TEXT NOT NULL,
  event         TEXT NOT NULL,                      -- received|triaged|status_changed|note|duplicate|contact_requested|deletion_requested|deleted
  detail        TEXT                                -- operator notes ride here; the envelope is never mutated
);
CREATE INDEX idx_feedback_events ON feedback_events(feedback_id, ts);

CREATE TABLE feedback_tokens (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id   INTEGER NOT NULL REFERENCES accounts(id),
  token_hash   TEXT NOT NULL UNIQUE,
  token_prefix TEXT NOT NULL,                       -- first 12 chars, display-safe
  scopes       TEXT NOT NULL,                       -- CSV: "feedback:write,feedback:delete-own"
  created_ts   INTEGER NOT NULL,
  expires_ts   INTEGER NOT NULL,
  revoked_ts   INTEGER,
  last_used_ts INTEGER,
  install_pseudonym TEXT
);
CREATE INDEX idx_feedback_tokens_account ON feedback_tokens(account_id);
```

`feedback_attachments` is deliberately **not** created (FD-11).

### 6.1 Retention and deletion semantics (FD-1)

- Submissions are retained 24 months, then purged; `retention_expires_ts` is
  written at insert and is the enforced boundary.
- Local drafts expire after 30 days (§8).
- Deletion — self-serve or operator — sets `payload_json = NULL`,
  `status = 'deleted'`, and `deleted_ts`, and appends a `deleted` event. The
  minimal audit skeleton retained is the row's `id`, its timestamps, and
  `payload_sha256`. The envelope is never mutated in place; deletion is the only
  operation that removes it.
- `feedback_consents` carries standing-consent columns (`mode`, `scopes_json`,
  `expires_ts`, `revoked_ts`) so FD-10 lands post-MVP without migration churn.
  MVP writes only `mode='per_submission'`.

---

## 7. Redaction profile v1 (plan §5.7) — deterministic, ordered, idempotent

Applied by `s0ma_dsl.feedback.redact` to every free-text field
(`summary`/`expected`/`actual`/`details`/`reproduction[*]`), in this order,
with stable per-type numbering (`<PATH_1>`, `<PATH_2>`, …) and a counts map
for the `privacy.redacted` report; re-running on redacted output is a no-op:

1. s0ma keys/tokens: `s0ma_test_[A-Za-z0-9_-]+`, `s0ma_fb_[A-Za-z0-9_-]+`
   → `<SECRET_REDACTED>`
2. Known secret formats: `AKIA[0-9A-Z]{16}`, `ghp_[A-Za-z0-9]{36,}`,
   `github_pat_\w+`, `sk-[A-Za-z0-9_-]{20,}`, `xox[baprs]-[A-Za-z0-9-]+`,
   `Bearer\s+\S{16,}`, PEM blocks (`-----BEGIN … KEY-----`),
   `eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}` (JWT) → `<SECRET_REDACTED>`
3. Env-var secret assignments *(re-frozen r5 — the keyword prefix is
   optional, so a variable named exactly the keyword is caught)*:
   `\b(?:[A-Z][A-Z0-9_]*)?(KEY|TOKEN|SECRET|PASSWORD|
   CREDENTIAL)[A-Z0-9_]*\s*=\s*\S+` → name kept, value `<SECRET_REDACTED>`
4. Emails → `<EMAIL_n>`
5. URLs and git remotes (http/https/ssh/git@) → `<URL_n>`
6. Absolute paths, POSIX and Windows (`/Users/...`, `/home/...`, `/private/...`,
   `[A-Za-z]:\\...`, `\\\\server\...`) → `<PATH_n>`; a path whose final
   segment is load-bearing may keep the basename as `<PATH_n:basename>`
7. Home-dir username leakage outside paths (the literal current username as a
   standalone token) → `<USER>`
8. Hardware/host identifiers: UUIDs, MAC addresses, hostnames matching the
   local hostname → `<HOST_ID_n>`
9. High-entropy strings: length ≥ 20, Shannon entropy ≥ 4.5 bits/char, not
   already a placeholder → `<SECRET_REDACTED>`
10. Stack-trace shapes (`File "...", line N` / `at ... (...:N:N)`) → the
    frame is collapsed to `<TRACE_FRAME>` (raw traces are excluded-by-default
    content, not context)

The adversarial corpus (FB-M5) is the executable definition; rules are
versioned as `redaction_profile: "v1"` inside ADR-004 and the contract doc.

### 7.1 Notes for implementers

- Rule 3's pattern is line-wrapped above for page width only. The wrap is **not**
  part of the pattern; the pattern (as re-frozen by r5) is:
  `\b(?:[A-Z][A-Z0-9_]*)?(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*\s*=\s*\S+`
- Numbering is per type and per redaction pass, assigned in first-appearance
  order across the envelope's fields in the §3.1 field order, with
  `reproduction[*]` walked in index order. The same value appearing twice keeps
  the same placeholder number.
- Idempotency is a property test, not a comment: re-running `redact` over its
  own output must be a fixed point, and no rule's regex may match anywhere in
  any output.
- Rule 9's false-positive bound is documented with the implementation:
  identifiers of ≤ 19 characters are never touched by the entropy rule.
- The module declares `REDACTION_PROFILE = "v1"`. Changing, adding, reordering,
  or removing a rule requires a re-freeze under §13 — the profile string is the
  version handle.
- The server runs a **detection-only** port of rules 1–5 and rejects with
  `SENSITIVE_CONTENT` naming the matched type. It never rewrites an approved
  envelope (§1.6, notes §7.4): rewriting would break hash continuity.

---

## 8. Local state layout (plan §5.8) — client machines

`~/.s0ma/` (0700, created on demand; Windows `%USERPROFILE%\.s0ma`,
permissions best-effort and documented):
`feedback-token` (0600 JSON: `{token, token_prefix, expires_ts, cp_host}`) ·
`installation_id` (0600, random 16-byte hex pseudonym) ·
`feedback-drafts/fbd_<8-hex>.json` (0600; envelope + idempotency key +
created ts; 30-day expiry purged on any drafts-listing access) ·
`feedback-receipts.jsonl` (0600; append-only log of successful submissions
from this machine — `{feedback_id, ts, category, summary60, payload_sha256}`
— the offline source for `s0ma feedback list`, labeled "recorded on this
machine"). Never inside a project tree; never committed; not governed by
INV-5 (§5.1.4).

`S0MA_FEEDBACK_TOKEN` overrides the token file (FD-3). An OS keychain is
deferred. This directory is user-scoped runtime state, deliberately outside
every project tree — it is the only write the NFR-6 narrow feedback exception
permits.

---

## 9. CLI surface — NOT frozen here

The `s0ma feedback …` command family is specified in
`plans/s0ma-release-pipeline-feedback-1.md` §5.9 and implemented by FB-M7. It
is a consumer of this contract, not part of it; its user-facing copy is bound by
§12.

## 10. MCP surface — NOT frozen here

`prepare_feedback`, `submit_feedback`, and the `feedback` prompt are specified
in `plans/s0ma-release-pipeline-feedback-1.md` §5.10 and implemented by
FB-M8/FB-M9. Their count budget is governed by the FD-5 revision in
[`0.14.0-schema-and-surface-budget.md`](0.14.0-schema-and-surface-budget.md)
§10. Their user-facing copy is bound by §12.

## 11. Claude Code skill — NOT frozen here

The `/s0ma-feedback` skill is specified in
`plans/s0ma-release-pipeline-feedback-1.md` §5.11 (FD-7) and implemented by
FB-M9/FB-M10. It is a thin alias route into the same mechanics: no new
transport and no new consent path.

---

## 12. User-facing voice and recognition rules (plan §5.12; owner adjustments A-1..A-3, 2026-08-27)

- **A-2 — Voice.** Every user-facing string — CLI output, elicitation
  labels, agent-relayed copy, prompt copy, docs — is written for
  intelligent non-programmers. The word "payload" never appears in
  user-facing text: say **"feedback data"** or **"feedback report"**.
  (Technical identifiers — schema field names like `payload_sha256`, code,
  logs, this plan — are exempt.) The canonical confirmation line is
  `Send exactly this feedback data? [y/N]`.
- **A-1 — Recognition disambiguation.** When a user expresses feedback
  intent WITHOUT naming s0ma or kn0wthyself ("I have some feedback", "send
  feedback about this"), the agent must first confirm the feedback is about
  s0ma before starting the journey — users may have other tools that also
  collect feedback. Mentions that name s0ma/kn0wthyself, the
  `/s0ma-feedback` skill, and the MCP prompt are unambiguous and need no
  confirmation. This rule lives in the recognition instruction (FB-M9.T2),
  the `feedback` prompt copy, and the scaffolded AGENTS.md rule.
- **A-3 — Multi-report management.** Users may accumulate many reports, so
  the report functions handle plurality explicitly: `s0ma feedback list`
  (server-backed own-report listing; offline falls back to the local
  receipts log), bare `delete` deletes nothing, `delete <receipt-id>`
  deletes exactly one, and `delete --all` is the only bulk path — preview
  list + explicit `Delete all N feedback reports? [y/N]` confirmation, then
  per-id deletion. Receipts are appended to `feedback-receipts.jsonl` so
  ids remain findable after the conversation scrolls away.

Two further product rules bind every surface that renders copy:

- **Contact permission (FD-2).** `contact_ok` defaults to `false` and is asked
  during approval with exactly:
  `May kn0wthyself contact you about this report? [y/N]`
- **Pseudonymous, never anonymous (FR-FB-11).** Product language says
  *pseudonymous*, *locally redacted*, or *content-minimized*. No surface claims
  anonymity, and no `--anonymous` flag exists (§1.3).

---

## 13. Change control

- This contract is versioned by its filename and its `s0ma-feedback@1` /
  `s0ma-feedback-receipt@1` schema tags. A wire-format change bumps the schema
  tag and re-freezes this document; the old tag stays readable for as long as
  stored rows carry it.
- A change to §4 vocabulary, §5 allow-list, §6 DDL, §7 redaction rules, or the
  §3.3 test vector requires owner review, an ADR-004 amendment where the
  rationale moves, and a new revision row below.
- The redaction profile's version handle is `REDACTION_PROFILE = "v1"`. Rule
  edits change it.
- Nothing in the deferred set may be built without a new owner decision:
  standing automatic consent, background submission, source/transcript/log
  inclusion, R2 attachments, Queues, issue-tracker automation, public boards,
  remote telemetry, AI-only redaction, clustering, contact automation
  (notes §13.2).

| Revision | Date | Change |
|---|---|---|
| feedback-v1 | 2026-08-27 | Initial freeze. Copies `plans/s0ma-release-pipeline-feedback-1.md` §5.1–§5.8 and §5.12 verbatim; adds the §3.2 cross-language serialization notes, the §3.3 normative test vector, the §2.1/§2.3/§6.1/§7.1 implementer tables and notes, and §9–§11 not-frozen-here markers. Owner-ratified with FD-1..FD-13 and PRD v1.9. |
| feedback-v1 r6 | 2026-08-28 | Wave-4 gate clarifications (both sides verified in agreement; no wire change): (1) every `*_ts` in this contract is **epoch-milliseconds** — `expires_ts` included (CP emits `Date.now()+180d·ms`; the client reads ms). (2) Enrollment sends an empty body by default — the installation pseudonym is NOT sent at token exchange (sending it would let the CP join pseudonym→account, weakening exactly what FD-9 protects); the pseudonym travels only inside approved envelopes. (3) Client duty on receipt-hash mismatch: a 200 receipt whose `payload_sha256` differs from the approved envelope's is reported as a failure (`HASH_MISMATCH`), never as "received" (§3.4's MUST). (4) Client-side transport codes (`TIMEOUT`, `NETWORK_UNREACHABLE`, `INVALID_RESPONSE`, `SERVER_ERROR`, `HASH_MISMATCH`) are client-local and never originate from the server. |
| feedback-v1 r5 | 2026-08-28 | Wave-3 gate (defect re-freezes + admin rulings): (1) **§7 rule 3 is re-frozen** — the original pattern's leading `[A-Z]` consumed the keyword's first letter, so a variable named exactly the keyword (`PASSWORD=hunter2`, `TOKEN=abc`) was never caught. Rule 3 is now `\b(?:[A-Z][A-Z0-9_]*)?(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*\s*=\s*\S+` (name kept, value → `<SECRET_REDACTED>`), binding on the dsl redactor AND the CP sensitive screen. (2) **FD-1 deletion also blanks the denormalized `summary` to `''`** on both delete paths (the DDL's NOT NULL survives; free text does not) — deletion now leaves id/timestamps/hash/status/events only. (3) The CP screen's placeholder neutralization must SUBSTITUTE (never delete) placeholders — deleting `<SECRET_REDACTED>` would let rule 3's `\S+` bind the next word and refuse correctly-redacted text — and must recognize the `<PATH_n:basename>` form. (4) Admin triage is `POST /admin/feedback` (Pages one-file-one-path routing); `functions/admin/feedback/update.ts` re-exports it so the §2 path also answers. (5) An admin identity reveal appends a `contact_requested` audit event. (6) Redaction numbering policy pinned as implemented: per-type first-appearance order, same value → same placeholder, pre-existing placeholders seed the counters; counts are occurrences by type. |
| feedback-v1 r4 | 2026-08-27 | Wave-2 gate close-out (FB-M2 rulings ratified): (1) `s0ma_version` STAYS in the context allow-list (r3's spelling list accidentally omitted it; §5 prose and the §3.3 vector carry it; it resolves to the s0ma-dsl lockstep version). (2) `contact_ok` is the only optional wrapper key (absent → `false`, FD-2); the other five are required. (3) `GET /api/feedback` responds `{ok, count, reports:[…]}` and omits `status='deleted'` rows — deletion is visible as absence; clients (FB-M6/M7) must match. (4) An idempotent replay reports the row's CURRENT status (a deleted report is never re-announced as "received"). (5) A cross-reporter `Idempotency-Key` is 400, never another reporter's receipt. (6) Correctly redacted text can never be refused: the server's sensitive screen neutralizes the §7 placeholders. (7) The 30/hr delete ceiling stands; a bulk `delete --all` beyond it must degrade gracefully (report progress + when to retry), never bypass. (8) Prod prerequisite: `FEEDBACK_REPORTER_SECRET` must be set (Wrangler secret) before the endpoints go live; a missing secret is a hard 500, never an unkeyed-digest fallback. |
| feedback-v1 r3 | 2026-08-27 | Wave-2 gate: the **submission wrapper** is pinned (FB-M4 found the gap: the envelope is a closed schema, yet the server needs per-request facts that are not feedback content). The `POST /api/feedback` body is `{"schema":"s0ma-feedback-submission@1","envelope":{…s0ma-feedback@1…},"channel":"mcp"\|"cli","created_ts":<epoch-ms client clock>,"approval_method":"mcp_elicitation"\|"cli_tty","contact_ok":<bool>}` — unknown wrapper keys are `SCHEMA_INVALID`; the envelope stays closed; the ≤ 32 KB cap applies to the whole body; **`payload_sha256` is computed over the canonical ENVELOPE only** (hash continuity binds exactly what the user approved — the feedback data — never the transport metadata). Also pinned, matching the dsl engine (FB-M4): context allow-list key spellings `s0ma_core`/`s0ma_dsl`/`s0ma_mcp`/`s0ma_studi0`/`client`/`surface`/`mcp_protocol_version`/`python`/`os`/`architecture`/`diagnostic_codes`/`outcome`/`duration_bucket`/`cohort`/`pseudonym`; `os` family adds `other`; `duration_bucket` values `<1s`/`1-5s`/`5-30s`/`30s-2m`/`>2m`. |
| feedback-v1 r2 | 2026-08-27 | Wave-1 gate clarifications (orchestrator, filling gaps the freeze left unpinned; no wire-format tag change): (1) `scopes` is a JSON **array** everywhere on the wire (exchange response and any future surface); the CSV form is the D1 at-rest encoding only. (2) Token validity additionally requires the token's **account to be entitled at request time** (`free_tester`/`active`) on every feedback endpoint — `NOT_ENTITLED` 403 otherwise — so account-level revocation stops existing feedback tokens immediately; license-key *rotation* deliberately does NOT revoke feedback tokens (they are account-scoped, not key-scoped). (3) The hourly/daily rate ceilings are enforced against rolling windows; the shared limiter gains an optional `windowMs` (FB-M2) rather than per-endpoint counters. |
