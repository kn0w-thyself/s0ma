"""The s0ma feedback engine — envelope, context, local state, transport.

Implements the client half of the frozen feedback contract at
``docs/contracts/feedback-v1.md``:

* :mod:`s0ma_dsl.feedback.model` — the ``s0ma-feedback@1`` envelope, the
  §4 vocabulary, the §3.1 caps, the §3.2 canonical hash, and the
  pre-flight validator;
* :mod:`s0ma_dsl.feedback.context` — the §5 allow-list collector;
* :mod:`s0ma_dsl.feedback.redact` — redaction profile v1, the ten ordered
  §7 rules every free-text field passes through before anything is shown
  back, hashed, or sent;
* :mod:`s0ma_dsl.feedback.state` — ``~/.s0ma/`` and the installation
  pseudonym (§8);
* :mod:`s0ma_dsl.feedback.drafts` — unsent reports and the receipts log (§8);
* :mod:`s0ma_dsl.feedback.tokens` — the feedback token store and the
  one-time license-key exchange (§2.2/§8);
* :mod:`s0ma_dsl.feedback.client` — the ``s0ma-feedback-submission@1``
  transport: submit, list, delete (§2, §13 r3).

**Only :mod:`~s0ma_dsl.feedback.client` opens a socket, and only when it
is called.** Composing, redacting, hashing, previewing, drafting, and
reading the token store are entirely local and offline — importing this
package touches no network at all. ``tests/test_feedback_context.py`` and
``tests/test_feedback_client.py`` hold that boundary as an executable rule.

Zero third-party dependencies (INV-6/NFR-7): stdlib only, everywhere in
this package.
"""

from __future__ import annotations

from s0ma_dsl.feedback.client import (
    APPROVAL_METHODS,
    DEFAULT_TIMEOUT_SECONDS,
    SUBMISSION_SCHEMA,
    SUBMIT_CHANNELS,
    FeedbackReceipt,
    FeedbackReportRow,
    FeedbackResult,
    build_submission,
    delete_report,
    list_reports,
    submit,
    user_agent,
)
from s0ma_dsl.feedback.context import (
    COHORT,
    ClientInfo,
    ContextAllowListError,
    SurfaceInfo,
    build_context,
    duration_bucket,
    enforce_allow_list,
)
from s0ma_dsl.feedback.drafts import (
    DRAFT_TTL_DAYS,
    FeedbackDraft,
    ReceiptLogEntry,
    append_receipt,
    delete_draft,
    drafts_dir,
    list_drafts,
    load_draft,
    new_idempotency_key,
    purge_expired_drafts,
    read_receipts,
    receipts_path,
    save_draft,
)
from s0ma_dsl.feedback.model import (
    BODY_MAX_BYTES,
    CATEGORIES,
    CHANNELS,
    CONTEXT_ALLOWED_KEYS,
    CONTEXT_MAX_BYTES,
    ENVELOPE_FIELDS,
    FEEDBACK_SCHEMA,
    IMPACTS,
    PRIVACY_PROFILE,
    RECEIPT_SCHEMA,
    STATUSES,
    FeedbackEnvelope,
    FeedbackPrivacy,
    FeedbackProblem,
    FeedbackValidation,
    build_envelope,
    canonical_bytes,
    payload_sha256,
    validate_envelope,
    validate_payload,
)
from s0ma_dsl.feedback.redact import (
    REDACTION_PROFILE,
    redact,
    redact_envelope,
)
from s0ma_dsl.feedback.state import (
    installation_id,
    read_installation_id,
    rotate_installation_id,
    state_dir,
)
from s0ma_dsl.feedback.tokens import (
    DEFAULT_CP_HOST,
    TOKEN_ENV_VAR,
    StoredToken,
    TokenLookup,
    base_url,
    clear_token,
    exchange,
    read_token,
    token_path,
    write_token,
)

__all__ = [
    "APPROVAL_METHODS",
    "BODY_MAX_BYTES",
    "CATEGORIES",
    "CHANNELS",
    "COHORT",
    "CONTEXT_ALLOWED_KEYS",
    "CONTEXT_MAX_BYTES",
    "DEFAULT_CP_HOST",
    "DEFAULT_TIMEOUT_SECONDS",
    "DRAFT_TTL_DAYS",
    "ENVELOPE_FIELDS",
    "FEEDBACK_SCHEMA",
    "IMPACTS",
    "PRIVACY_PROFILE",
    "RECEIPT_SCHEMA",
    "REDACTION_PROFILE",
    "STATUSES",
    "SUBMISSION_SCHEMA",
    "SUBMIT_CHANNELS",
    "TOKEN_ENV_VAR",
    "ClientInfo",
    "ContextAllowListError",
    "FeedbackDraft",
    "FeedbackEnvelope",
    "FeedbackPrivacy",
    "FeedbackProblem",
    "FeedbackReceipt",
    "FeedbackReportRow",
    "FeedbackResult",
    "FeedbackValidation",
    "ReceiptLogEntry",
    "StoredToken",
    "SurfaceInfo",
    "TokenLookup",
    "append_receipt",
    "base_url",
    "build_context",
    "build_envelope",
    "build_submission",
    "canonical_bytes",
    "clear_token",
    "delete_draft",
    "delete_report",
    "drafts_dir",
    "duration_bucket",
    "enforce_allow_list",
    "exchange",
    "installation_id",
    "list_drafts",
    "list_reports",
    "load_draft",
    "new_idempotency_key",
    "payload_sha256",
    "purge_expired_drafts",
    "read_installation_id",
    "read_receipts",
    "read_token",
    "receipts_path",
    "redact",
    "redact_envelope",
    "rotate_installation_id",
    "save_draft",
    "state_dir",
    "submit",
    "token_path",
    "user_agent",
    "validate_envelope",
    "validate_payload",
    "write_token",
]
