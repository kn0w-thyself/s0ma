"""The feedback transport: submit, list, delete (contract §2, §3, r3).

This is the one module in :mod:`s0ma_dsl.feedback` that opens a socket.
Everything else — composing, redacting, hashing, previewing, drafting,
reading the token store — is local and offline, and
``tests/test_feedback_context.py`` holds that boundary as an executable
rule. The transport is :mod:`urllib.request` from the standard library:
zero third-party dependencies, here as everywhere in this package (INV-6).

What goes on the wire (contract §13 r3): the request body is the
**submission wrapper** ``s0ma-feedback-submission@1`` —
``{schema, envelope, channel, created_ts, approval_method, contact_ok}`` —
carrying the closed ``s0ma-feedback@1`` envelope plus the per-request facts
the server needs and the envelope deliberately does not hold. Both layers
are closed schemas, the whole body is capped at 32 KB, and
``payload_sha256`` covers **the canonical envelope alone**: hash continuity
binds exactly what the user approved, never the transport metadata.

What does not happen here: **retries**. A failed submission returns a
structured result and the caller keeps its draft. That is not timidity —
after a timeout the client cannot know whether the server filed the report,
so retrying is the *caller's* decision, made explicitly, reusing the
draft's original ``Idempotency-Key`` so the server replays the first
receipt instead of filing a second report.

Every call returns a :class:`FeedbackResult`. On failure the server's own
``code`` and ``remediation`` are surfaced verbatim (contract §2.1, the D-5
error shape) so a refusal reads the same wherever it is shown; failures
that never reached the server — timeout, unreachable host, unreadable
reply — carry client-side codes and copy written to contract §12's voice.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from importlib import metadata
from typing import TYPE_CHECKING, Any

from s0ma_dsl.feedback import tokens
from s0ma_dsl.feedback.context import S0MA_VERSION_DISTRIBUTION
from s0ma_dsl.feedback.model import (
    BODY_MAX_BYTES,
    RECEIPT_SCHEMA,
    FeedbackEnvelope,
    canonical_bytes,
    payload_sha256,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from email.message import Message
    from pathlib import Path

__all__ = [
    "APPROVAL_METHODS",
    "CLIENT_CODES",
    "CODE_BAD_REQUEST",
    "CODE_HASH_MISMATCH",
    "CODE_INVALID_RESPONSE",
    "CODE_INVALID_TOKEN",
    "CODE_SERVER_ERROR",
    "CODE_TIMEOUT",
    "CODE_TOO_LARGE",
    "CODE_UNREACHABLE",
    "DEFAULT_TIMEOUT_SECONDS",
    "FEEDBACK_PATH",
    "SUBMISSION_SCHEMA",
    "SUBMIT_CHANNELS",
    "WRAPPER_FIELDS",
    "FeedbackReceipt",
    "FeedbackReportRow",
    "FeedbackResult",
    "build_submission",
    "delete_report",
    "list_reports",
    "request_json",
    "submit",
    "user_agent",
]

#: The submission wrapper's schema tag (contract §13 r3).
SUBMISSION_SCHEMA = "s0ma-feedback-submission@1"

#: The wrapper's closed key set. An unknown key is ``SCHEMA_INVALID``.
WRAPPER_FIELDS: tuple[str, ...] = (
    "schema",
    "envelope",
    "channel",
    "created_ts",
    "approval_method",
    "contact_ok",
)

#: Channels a client may submit under. ``web`` is reserved in the §4
#: vocabulary but has no client, so it cannot be submitted from here.
SUBMIT_CHANNELS: tuple[str, ...] = ("mcp", "cli")

#: How the user approved this report (contract §1.5). One consent row is
#: written per submission, and this says which interaction produced it.
APPROVAL_METHODS: tuple[str, ...] = ("mcp_elicitation", "cli_tty")

#: The submit/list endpoint; deletion appends ``/<feedback-id>``.
FEEDBACK_PATH = "/api/feedback"

#: Seconds before a request is abandoned. One coherent wait, then a
#: structured answer — never a silent hang in front of a user.
DEFAULT_TIMEOUT_SECONDS = 10.0

# --- client-side codes -----------------------------------------------------
# These name failures that never reached the server, so they can never
# collide with the §2.1 server codes a response carries.

#: The service did not answer within the timeout.
CODE_TIMEOUT = "TIMEOUT"

#: The service could not be reached at all (DNS, refused, offline).
CODE_UNREACHABLE = "NETWORK_UNREACHABLE"

#: A reply arrived but this version could not read it.
CODE_INVALID_RESPONSE = "INVALID_RESPONSE"

#: The service answered 5xx without a usable error body.
CODE_SERVER_ERROR = "SERVER_ERROR"

#: The receipt's hash is not the hash of the report the user approved.
CODE_HASH_MISMATCH = "HASH_MISMATCH"

CLIENT_CODES: tuple[str, ...] = (
    CODE_TIMEOUT,
    CODE_UNREACHABLE,
    CODE_INVALID_RESPONSE,
    CODE_SERVER_ERROR,
    CODE_HASH_MISMATCH,
)

# --- §2.1 codes this client also raises on its own -------------------------
# A pre-flight refusal predicts the exact code the server would have given,
# so "the request never left" and "the service said no" read alike. Only the
# three the client raises are named; the tables below stay keyed by the wire
# string, because that is what they are — a lookup on whatever a response
# said, including codes this client never raises.

#: A request this client will not make as asked.
CODE_BAD_REQUEST = "BAD_REQUEST"

#: No usable token on this machine, or one the service rejected.
CODE_INVALID_TOKEN = "INVALID_TOKEN"

#: The whole body exceeds the 32 KB cap (contract §3.1, r3).
CODE_TOO_LARGE = "PAYLOAD_TOO_LARGE"

# Contract §12 A-2 voice: "feedback report" / "feedback data", never the
# word this codebase uses for the same thing in field names.
_MESSAGES = {
    CODE_TIMEOUT: "The s0ma feedback service did not answer in time, so nothing was sent.",
    CODE_UNREACHABLE: "The s0ma feedback service could not be reached, so nothing was sent.",
    CODE_INVALID_RESPONSE: "The s0ma feedback service sent a reply s0ma could not read.",
    CODE_SERVER_ERROR: "The s0ma feedback service had a problem at its end, so nothing was sent.",
    CODE_HASH_MISMATCH: (
        "The s0ma feedback service confirmed something other than the feedback report "
        "you approved, so this is not counted as sent."
    ),
    "INVALID_TOKEN": "The s0ma feedback service did not accept this machine's access.",
    "NOT_ENTITLED": "This s0ma account cannot send feedback at the moment.",
    "SCHEMA_INVALID": "The s0ma feedback service could not accept this feedback report as written.",
    "PAYLOAD_TOO_LARGE": "This feedback report is too large to send.",
    "SENSITIVE_CONTENT": (
        "The s0ma feedback service found something sensitive in this feedback report "
        "and did not store it."
    ),
    "RATE_LIMITED": "This account has sent as much feedback as it can for now.",
    "NOT_FOUND": "No feedback report with that id belongs to this account.",
    "BAD_REQUEST": "The s0ma feedback service could not accept this request.",
}

_GENERIC_MESSAGE = "The s0ma feedback service could not complete this request."

# Used only when a response omits its own remediation — the server's copy
# always wins (contract §2.1).
_RETRY_SAFELY = (
    "Your feedback report is kept as a draft. Sending the same draft again is safe: "
    "the service files it only once."
)
_FALLBACK_REMEDIATION = {
    CODE_TIMEOUT: f"Check your connection and try again. {_RETRY_SAFELY}",
    CODE_UNREACHABLE: f"Check your connection and try again. {_RETRY_SAFELY}",
    CODE_INVALID_RESPONSE: (
        "Try again in a few minutes. If it keeps happening, update s0ma to the latest version."
    ),
    CODE_SERVER_ERROR: f"Try again in a few minutes. {_RETRY_SAFELY}",
    CODE_HASH_MISMATCH: (
        "Nothing you wrote was lost. Try sending the report again, and tell the s0ma "
        "team if it happens a second time."
    ),
    "INVALID_TOKEN": "Run `s0ma feedback enroll` to set this machine up again.",
    "NOT_ENTITLED": "Check your s0ma subscription at https://account.kn0wthyself.ai",
    "PAYLOAD_TOO_LARGE": (
        "Shorten the description, or remove a few reproduction steps, then try again."
    ),
    "RATE_LIMITED": "Wait until the limit resets, then try again.",
}
_GENERIC_REMEDIATION = "Try again in a few minutes."

# A response with no readable body still has a status. These are the §2.1
# rows a bare status determines on its own.
_CODE_BY_STATUS = {
    400: "BAD_REQUEST",
    401: "INVALID_TOKEN",
    403: "NOT_ENTITLED",
    404: "NOT_FOUND",
    413: "PAYLOAD_TOO_LARGE",
    422: "SENSITIVE_CONTENT",
    429: "RATE_LIMITED",
}


def user_agent() -> str:
    """Return the ``s0ma-feedback/<version>`` User-Agent (contract §3.1)."""
    try:
        version = metadata.version(S0MA_VERSION_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        version = "unknown"
    return f"s0ma-feedback/{version}"


# ---------------------------------------------------------------------------
# Typed responses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackReceipt:
    """A ``s0ma-feedback-receipt@1`` receipt (contract §3.4)."""

    feedback_id: str
    received_ts: int
    payload_sha256: str
    status: str = "received"
    """The row's status. On a replay this is its **current** status
    (contract r4 item 4) — a deleted report is never announced as newly
    received."""

    replayed: bool = False
    """True when this receipt is the original one, replayed for a repeated
    ``Idempotency-Key``. Nothing new was filed."""

    schema: str = RECEIPT_SCHEMA

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> FeedbackReceipt:
        """Build a receipt from a response body, or raise :class:`ValueError`."""
        feedback_id = document.get("feedback_id")
        digest = document.get("payload_sha256")
        received_ts = document.get("received_ts")
        if not isinstance(feedback_id, str) or not feedback_id:
            raise ValueError("the receipt carries no feedback id")
        if not isinstance(digest, str) or not digest:
            raise ValueError("the receipt carries no payload_sha256")
        if not isinstance(received_ts, int) or isinstance(received_ts, bool):
            raise ValueError("the receipt carries no received timestamp")
        status = document.get("status")
        return cls(
            feedback_id=feedback_id,
            received_ts=received_ts,
            payload_sha256=digest,
            status=status if isinstance(status, str) and status else "received",
            replayed=bool(document.get("replayed", False)),
            schema=str(document.get("schema", RECEIPT_SCHEMA)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "schema": self.schema,
            "feedback_id": self.feedback_id,
            "received_ts": self.received_ts,
            "payload_sha256": self.payload_sha256,
            "status": self.status,
            "replayed": self.replayed,
        }


@dataclass(frozen=True)
class FeedbackReportRow:
    """One row of the caller's own reports (contract §2, ``GET /api/feedback``).

    Deleted reports are simply absent from the listing (r4 item 3):
    deletion is visible as absence, never as a tombstone row.
    """

    feedback_id: str
    received_ts: int = 0
    category: str = ""
    impact: str = ""
    summary: str = ""
    status: str = ""

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> FeedbackReportRow:
        """Build a row from a response entry, or raise :class:`ValueError`."""
        feedback_id = document.get("feedback_id")
        if not isinstance(feedback_id, str) or not feedback_id:
            raise ValueError("a listed report carries no feedback id")
        received_ts = document.get("received_ts")
        return cls(
            feedback_id=feedback_id,
            received_ts=(
                received_ts
                if isinstance(received_ts, int) and not isinstance(received_ts, bool)
                else 0
            ),
            category=str(document.get("category", "")),
            impact=str(document.get("impact", "")),
            summary=str(document.get("summary", "")),
            status=str(document.get("status", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "feedback_id": self.feedback_id,
            "received_ts": self.received_ts,
            "category": self.category,
            "impact": self.impact,
            "summary": self.summary,
            "status": self.status,
        }


@dataclass(frozen=True)
class FeedbackResult:
    """The outcome of one call to the feedback service.

    One type for every call, so callers have one shape to handle:
    ``ok`` with the typed payload for that call (``receipt`` for a
    submission, ``reports`` for a listing, ``feedback_id`` for a deletion,
    ``token`` for an enrollment), or ``ok=False`` with ``code`` +
    ``remediation`` — the server's own words when the server spoke, and
    contract §12 voice when the failure never reached it.
    """

    ok: bool
    code: str | None = None
    message: str = ""
    remediation: str | None = None
    status_code: int | None = None
    """HTTP status, or ``None`` when no response arrived."""

    retry_after: int | None = None
    """Seconds from a ``Retry-After`` header, when the service sent one."""

    receipt: FeedbackReceipt | None = None
    reports: tuple[FeedbackReportRow, ...] = ()
    feedback_id: str | None = None
    token: tokens.StoredToken | None = None
    data: dict[str, Any] | None = field(default=None, repr=False)
    """The decoded response body, for diagnosis. Never carries a token: the
    one response that holds a plaintext token does not keep its body."""

    @property
    def replayed(self) -> bool:
        """Whether this submission replayed an already-filed report."""
        return self.receipt is not None and self.receipt.replayed

    def to_dict(self) -> dict[str, Any]:
        """Serialize for a JSON surface (an MCP tool result, a log line).

        ``token`` and ``data`` are deliberately excluded: one is a secret,
        the other is raw transport detail no surface should relay.
        """
        document: dict[str, Any] = {"ok": self.ok}
        if self.code is not None:
            document["code"] = self.code
        if self.message:
            document["message"] = self.message
        if self.remediation is not None:
            document["remediation"] = self.remediation
        if self.status_code is not None:
            document["status_code"] = self.status_code
        if self.retry_after is not None:
            document["retry_after"] = self.retry_after
        if self.receipt is not None:
            document["receipt"] = self.receipt.to_dict()
        if self.reports:
            document["reports"] = [row.to_dict() for row in self.reports]
        if self.feedback_id is not None:
            document["feedback_id"] = self.feedback_id
        return document


def _failure(
    code: str,
    *,
    remediation: str | None = None,
    message: str | None = None,
    status_code: int | None = None,
    retry_after: int | None = None,
    data: dict[str, Any] | None = None,
    receipt: FeedbackReceipt | None = None,
) -> FeedbackResult:
    """Build a failure result, filling message/remediation from the tables."""
    return FeedbackResult(
        ok=False,
        code=code,
        message=message if message is not None else _MESSAGES.get(code, _GENERIC_MESSAGE),
        remediation=(
            remediation
            if remediation is not None
            else _FALLBACK_REMEDIATION.get(code, _GENERIC_REMEDIATION)
        ),
        status_code=status_code,
        retry_after=retry_after,
        data=data,
        receipt=receipt,
    )


# ---------------------------------------------------------------------------
# The submission wrapper (contract §13 r3)
# ---------------------------------------------------------------------------


def build_submission(
    envelope: FeedbackEnvelope | Mapping[str, Any],
    *,
    channel: str,
    approval_method: str,
    contact_ok: bool = False,
    created_ts: int | None = None,
) -> dict[str, Any]:
    """Build the ``s0ma-feedback-submission@1`` body around *envelope*.

    The envelope goes in untouched — it is a closed schema and its bytes are
    what the hash covers. The four other keys are the per-request facts the
    server needs and the envelope deliberately does not carry.

    Raises :class:`ValueError` for a channel or approval method outside the
    frozen vocabulary. Those values come from s0ma's own surfaces, never
    from user text, so a wrong one is a bug to fix here rather than
    something to report to a user.
    """
    if channel not in SUBMIT_CHANNELS:
        raise ValueError(f"channel must be one of {SUBMIT_CHANNELS}; got {channel!r}")
    if approval_method not in APPROVAL_METHODS:
        raise ValueError(
            f"approval_method must be one of {APPROVAL_METHODS}; got {approval_method!r}"
        )
    payload = (
        envelope.to_payload() if isinstance(envelope, FeedbackEnvelope) else dict(envelope)
    )
    return {
        "schema": SUBMISSION_SCHEMA,
        "envelope": payload,
        "channel": channel,
        "created_ts": _now_ms() if created_ts is None else created_ts,
        "approval_method": approval_method,
        "contact_ok": bool(contact_ok),
    }


def _now_ms() -> int:
    """Epoch milliseconds from the client clock (the contract's ts unit)."""
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _retry_after(headers: Message) -> int | None:
    """Seconds from a ``Retry-After`` header, when it is a plain count.

    The control plane's limiter emits seconds; an HTTP-date form is read as
    "no usable number" rather than guessed at.
    """
    raw = headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = int(str(raw).strip())
    except ValueError:
        return None
    return max(seconds, 0)


def _transport_failure(error: Exception) -> FeedbackResult:
    """Classify an exception that stopped a request from being answered."""
    reason: Any = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(error, TimeoutError) or isinstance(reason, TimeoutError):
        code = CODE_TIMEOUT
    elif isinstance(error, http.client.HTTPException):
        code = CODE_INVALID_RESPONSE
    else:
        code = CODE_UNREACHABLE
    return _failure(code, data={"reason": str(reason)})


def _server_failure(
    document: dict[str, Any], status: int, retry_after: int | None
) -> FeedbackResult:
    """Turn a D-5 error body into a result, surfacing its words verbatim."""
    code = document.get("code")
    if not isinstance(code, str) or not code:
        code = _CODE_BY_STATUS.get(status)
        if code is None:
            code = CODE_SERVER_ERROR if status >= 500 else CODE_INVALID_RESPONSE
    remediation = document.get("remediation")
    return _failure(
        code,
        remediation=remediation if isinstance(remediation, str) and remediation else None,
        status_code=status,
        retry_after=retry_after,
        data=document,
    )


def request_json(
    method: str,
    url: str,
    *,
    bearer: str,
    body: Mapping[str, Any] | None = None,
    extra_headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> FeedbackResult:
    """Make one JSON request and return it as a :class:`FeedbackResult`.

    Success is ``ok`` with the decoded body in ``data``; everything else —
    an HTTP error, an unreadable reply, a dead connection — comes back as a
    structured failure. There are no retries at any level: see the module
    docstring.

    *bearer* is a secret (a feedback token, or a license key at enrollment).
    It is placed in the ``Authorization`` header and nowhere else; no
    message, result, or exception built here contains it.
    """
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Authorization": f"Bearer {bearer}",
        "User-Agent": user_agent(),
    }
    data: bytes | None = None
    if body is not None:
        data = canonical_bytes(body)
        headers["Content-Type"] = "application/json"
    headers.update(extra_headers or {})
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            raw = bytes(response.read())
            retry_after = _retry_after(response.headers)
    except urllib.error.HTTPError as error:
        # An error status is an answer, not a transport failure: the D-5
        # body is exactly what the user needs to see.
        status = int(error.code)
        raw = bytes(error.read())
        retry_after = _retry_after(error.headers)
        error.close()
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as error:
        return _transport_failure(error)

    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        if status >= 400:
            return _server_failure({}, status, retry_after)
        return _failure(CODE_INVALID_RESPONSE, status_code=status, retry_after=retry_after)
    if not isinstance(document, dict):
        return _failure(CODE_INVALID_RESPONSE, status_code=status, retry_after=retry_after)
    if status >= 400 or document.get("ok") is False:
        return _server_failure(document, status, retry_after)
    return FeedbackResult(
        ok=True, status_code=status, retry_after=retry_after, data=document
    )


def _authorize(
    cp_host: str | None, home: Path | None
) -> tuple[tokens.StoredToken, str] | FeedbackResult:
    """Resolve the token and base URL, or the failure to report instead.

    A missing local token is reported with the server's own
    ``INVALID_TOKEN`` code, so "this machine is not set up" and "the service
    refused this token" reach the caller as one case to handle, each with
    its own remediation.
    """
    lookup = tokens.read_token(home=home)
    if lookup.token is None:
        return _failure(CODE_INVALID_TOKEN, remediation=lookup.remediation)
    return lookup.token, tokens.base_url(cp_host or lookup.token.cp_host)


# ---------------------------------------------------------------------------
# The three calls
# ---------------------------------------------------------------------------


def submit(
    envelope: FeedbackEnvelope,
    *,
    idempotency_key: str,
    channel: str,
    approval_method: str,
    contact_ok: bool = False,
    created_ts: int | None = None,
    cp_host: str | None = None,
    home: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> FeedbackResult:
    """Send one approved feedback report and return its receipt.

    *idempotency_key* is the draft's key, reused by every retry of this
    report: the server replays the original receipt rather than filing a
    second report (contract §2). This function never retries by itself.

    The returned receipt is checked against the hash of the report that was
    sent. A receipt that confirms a different hash is a failure, not a
    success — contract §3.4 forbids telling a user their feedback was
    received on a receipt that does not match.
    """
    authorized = _authorize(cp_host, home)
    if isinstance(authorized, FeedbackResult):
        return authorized
    token, base = authorized

    wrapper = build_submission(
        envelope,
        channel=channel,
        approval_method=approval_method,
        contact_ok=contact_ok,
        created_ts=created_ts,
    )
    size = len(canonical_bytes(wrapper))
    if size > BODY_MAX_BYTES:
        return _failure(
            CODE_TOO_LARGE,
            message=(
                f"This feedback report is too large to send: {size:,} bytes, "
                f"and the limit is {BODY_MAX_BYTES:,}."
            ),
        )
    expected = payload_sha256(wrapper["envelope"])

    result = request_json(
        "POST",
        f"{base}{FEEDBACK_PATH}",
        bearer=token.token,
        body=wrapper,
        extra_headers={"Idempotency-Key": idempotency_key},
        timeout=timeout,
    )
    if not result.ok:
        return result
    try:
        receipt = FeedbackReceipt.from_dict(result.data or {})
    except ValueError:
        return _failure(
            CODE_INVALID_RESPONSE, status_code=result.status_code, data=result.data
        )
    if receipt.payload_sha256 != expected:
        return _failure(
            CODE_HASH_MISMATCH,
            status_code=result.status_code,
            data=result.data,
            receipt=receipt,
        )
    return FeedbackResult(
        ok=True,
        status_code=result.status_code,
        receipt=receipt,
        feedback_id=receipt.feedback_id,
        data=result.data,
    )


def list_reports(
    *,
    cp_host: str | None = None,
    home: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> FeedbackResult:
    """List this account's own feedback reports, newest first.

    The service answers ``{ok, count, reports}`` and omits deleted reports
    entirely (contract r4 item 3), so an absent report is a deleted one.
    """
    authorized = _authorize(cp_host, home)
    if isinstance(authorized, FeedbackResult):
        return authorized
    token, base = authorized

    result = request_json(
        "GET", f"{base}{FEEDBACK_PATH}", bearer=token.token, timeout=timeout
    )
    if not result.ok:
        return result
    listed = (result.data or {}).get("reports")
    if not isinstance(listed, list):
        return _failure(
            CODE_INVALID_RESPONSE, status_code=result.status_code, data=result.data
        )
    rows: list[FeedbackReportRow] = []
    for entry in listed:
        if not isinstance(entry, dict):
            return _failure(
                CODE_INVALID_RESPONSE, status_code=result.status_code, data=result.data
            )
        try:
            rows.append(FeedbackReportRow.from_dict(entry))
        except ValueError:
            return _failure(
                CODE_INVALID_RESPONSE, status_code=result.status_code, data=result.data
            )
    return FeedbackResult(
        ok=True, status_code=result.status_code, reports=tuple(rows), data=result.data
    )


def delete_report(
    feedback_id: str,
    *,
    cp_host: str | None = None,
    home: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> FeedbackResult:
    """Delete exactly one of this account's own feedback reports.

    An id that belongs to someone else is answered ``NOT_FOUND``, exactly
    as an unknown id is: ownership failure and non-existence are
    indistinguishable by design (contract §2.1).
    """
    identifier = feedback_id.strip()
    if not identifier:
        return _failure(
            CODE_BAD_REQUEST,
            message="No feedback report id was given, so nothing was deleted.",
            remediation=(
                "Run `s0ma feedback list` to see your reports, then pass the id of the "
                "one to delete."
            ),
        )
    authorized = _authorize(cp_host, home)
    if isinstance(authorized, FeedbackResult):
        return authorized
    token, base = authorized

    quoted = urllib.parse.quote(identifier, safe="")
    result = request_json(
        "DELETE", f"{base}{FEEDBACK_PATH}/{quoted}", bearer=token.token, timeout=timeout
    )
    if not result.ok:
        return result
    return FeedbackResult(
        ok=True,
        status_code=result.status_code,
        feedback_id=str((result.data or {}).get("feedback_id", identifier)),
        data=result.data,
    )


#: The plan's name for :func:`delete_report`. The longer name is what the
#: package exports, because a bare ``delete`` in a shared namespace reads
#: as "delete what?".
delete = delete_report
