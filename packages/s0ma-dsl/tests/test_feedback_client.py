"""FB-M6: the token store and the HTTPS client (contract §2, §3, §8, r3/r4).

No test here touches a real network. A threaded ``http.server`` on
127.0.0.1 plays the control plane: it implements the contract's four
endpoints, the D-5 error shape, idempotent replay, and the r4 rulings
(a listing omits deleted reports; a replay reports the row's *current*
status). Tests that need a specific failure queue a canned response.

The rules held here as executable facts:

* the request body is the r3 submission wrapper, and nothing else;
* hash continuity — approved == transmitted == stored == receipt — and a
  receipt that confirms a different hash is a failure, never a success;
* a failure returns a structured result and the draft survives; retrying
  with the same key replays rather than files a second report;
* the server's ``code`` and ``remediation`` are surfaced verbatim, while
  transport failures speak in contract §12's voice;
* the license key is exchanged once, the token is stored owner-only, and
  the plaintext never appears in a result's ``repr`` or a stored log;
* importing the engine and working locally opens no socket at all — only
  an explicit client call does.

Every test runs against an isolated HOME (``isolated_home`` is autouse), so
no test can read or write the developer's real ``~/.s0ma``.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import socket
import stat
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.feedback import client as client_module
from s0ma_dsl.feedback.client import (
    CODE_HASH_MISMATCH,
    CODE_INVALID_RESPONSE,
    CODE_TIMEOUT,
    CODE_UNREACHABLE,
    DEFAULT_TIMEOUT_SECONDS,
    SUBMISSION_SCHEMA,
    WRAPPER_FIELDS,
    FeedbackResult,
    build_submission,
    delete_report,
    list_reports,
    submit,
    user_agent,
)
from s0ma_dsl.feedback.drafts import (
    load_draft,
    new_idempotency_key,
    save_draft,
)
from s0ma_dsl.feedback.model import (
    BODY_MAX_BYTES,
    RECEIPT_SCHEMA,
    FeedbackEnvelope,
    FeedbackPrivacy,
    build_envelope,
    canonical_bytes,
    payload_sha256,
)
from s0ma_dsl.feedback.tokens import (
    DEFAULT_CP_HOST,
    TOKEN_ABSENT,
    TOKEN_ENV_VAR,
    TOKEN_EXPIRED,
    TOKEN_UNREADABLE,
    base_url,
    clear_token,
    exchange,
    read_token,
    token_path,
    write_token,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: A fixed "now" so expiry assertions never depend on the wall clock.
NOW = 1_787_850_000_000

#: The feedback token the fake control plane issues and accepts. Its
#: ``s0ma_fb_`` prefix is the contract §2.2 format.
TEST_TOKEN = "s0ma_fb_Zm9ydGhlZmFrZWNvbnRyb2xwbGFuZW9ubHlfMDAx"

#: A license key, used only at enrollment — it must never reach a report.
TEST_LICENSE_KEY = "s0ma_live_fake_license_key_for_tests"

PROXY_VARS = (
    "http_proxy",
    "HTTP_PROXY",
    "https_proxy",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME (and ``%USERPROFILE%``) at a throwaway directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv("S0MA_CP_HOST", raising=False)
    return home


# ---------------------------------------------------------------------------
# The fake control plane
# ---------------------------------------------------------------------------


@dataclass
class Recorded:
    """One request the fake control plane received."""

    method: str
    path: str
    headers: dict[str, str]
    body: bytes

    def header(self, name: str) -> str:
        """Header value by case-insensitive name (HTTP headers are)."""
        return self.headers.get(name.lower(), "")

    def json(self) -> dict[str, Any]:
        """The request body, decoded."""
        document: dict[str, Any] = json.loads(self.body.decode("utf-8"))
        return document


@dataclass
class Canned:
    """A response forced onto the next request, whatever it asks for."""

    status: int
    body: object = None
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0


@dataclass
class Plane:
    """The fake control plane's state and the assertions' way into it."""

    base: str = ""
    requests: list[Recorded] = field(default_factory=list)
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    receipts: dict[str, dict[str, Any]] = field(default_factory=dict)
    queued: list[Canned] = field(default_factory=list)
    licenses: list[str] = field(default_factory=list)
    clock: int = NOW
    serial: int = 0

    def queue(
        self,
        status: int,
        body: object = None,
        headers: dict[str, str] | None = None,
        delay: float = 0.0,
    ) -> None:
        """Force the next request's response."""
        self.queued.append(Canned(status, body, dict(headers or {}), delay))

    def next_id(self) -> str:
        """A new server-side feedback id (contract §6: ``fb_`` + hex)."""
        self.serial += 1
        return f"fb_{self.serial:032x}"

    def live_rows(self) -> list[dict[str, Any]]:
        """Rows a listing may show — deleted reports are absent (r4 item 3)."""
        rows = [row for row in self.rows.values() if row["status"] != "deleted"]
        return sorted(rows, key=lambda row: row["received_ts"], reverse=True)


def _error(code: str, remediation: str) -> dict[str, Any]:
    """The D-5 structured-error body every refusal carries."""
    return {"ok": False, "code": code, "remediation": remediation}


class _Handler(BaseHTTPRequestHandler):
    """The contract's four endpoints, just real enough to hold a client."""

    protocol_version = "HTTP/1.1"

    # Silence the per-request stderr logging; pytest output stays readable.
    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A002
        return

    @property
    def _plane(self) -> Plane:
        return self.server.plane  # type: ignore[attr-defined]

    def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            # The client timed out and walked away. That is the scenario
            # under test, not a failure of the fake.
            return

    def _json(
        self, status: int, payload: object, headers: dict[str, str] | None = None
    ) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), headers or {})

    def _bearer(self) -> str:
        value = self.headers.get("Authorization", "")
        return value[len("Bearer ") :] if value.startswith("Bearer ") else ""

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
        self._dispatch("POST")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
        self._dispatch("GET")

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        plane = self._plane
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        path = self.path.split("?", 1)[0]
        plane.requests.append(
            Recorded(
                method=method,
                path=path,
                headers={key.lower(): value for key, value in self.headers.items()},
                body=raw,
            )
        )
        if plane.queued:
            canned = plane.queued.pop(0)
            if canned.delay:
                time.sleep(canned.delay)
            if isinstance(canned.body, bytes):
                self._send(canned.status, canned.body, canned.headers)
            else:
                self._json(canned.status, canned.body, canned.headers)
            return
        if method == "POST" and path == "/api/feedback/token":
            self._exchange()
        elif method == "POST" and path == "/api/feedback":
            self._submit(raw)
        elif method == "GET" and path == "/api/feedback":
            self._list()
        elif method == "DELETE" and path.startswith("/api/feedback/"):
            self._delete(path.rsplit("/", 1)[-1])
        else:
            self._json(404, _error("NOT_FOUND", "Check the address."))

    def _exchange(self) -> None:
        plane = self._plane
        key = self._bearer()
        if not key:
            self._json(401, _error("INVALID_TOKEN", "Pass your s0ma license key."))
            return
        plane.licenses.append(key)
        self._json(
            200,
            {
                "ok": True,
                "token": TEST_TOKEN,
                "token_prefix": TEST_TOKEN[:12],
                "expires_ts": plane.clock + 180 * 86_400_000,
                # r2 item 1: scopes are a JSON array on the wire.
                "scopes": ["feedback:write", "feedback:delete-own"],
            },
        )

    def _feedback_token_ok(self) -> bool:
        if self._bearer().startswith("s0ma_fb_"):
            return True
        self._json(
            401,
            _error("INVALID_TOKEN", "Run `s0ma feedback enroll` to set this machine up."),
        )
        return False

    def _submit(self, raw: bytes) -> None:
        plane = self._plane
        if not self._feedback_token_ok():
            return
        key = self.headers.get("Idempotency-Key")
        if not key:
            self._json(400, _error("BAD_REQUEST", "Send an Idempotency-Key header."))
            return
        if len(raw) > BODY_MAX_BYTES:
            self._json(413, _error("PAYLOAD_TOO_LARGE", "Shorten the report."))
            return
        try:
            wrapper = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, _error("BAD_REQUEST", "Send valid JSON."))
            return
        if not isinstance(wrapper, dict) or set(wrapper) - set(WRAPPER_FIELDS):
            self._json(400, _error("SCHEMA_INVALID", "Send the documented fields."))
            return
        if wrapper.get("schema") != SUBMISSION_SCHEMA:
            self._json(400, _error("SCHEMA_INVALID", "Send a supported schema."))
            return
        if key in plane.receipts:
            replay = dict(plane.receipts[key])
            # r4 item 4: a replay reports the row's CURRENT status.
            replay["status"] = plane.rows[replay["feedback_id"]]["status"]
            replay["replayed"] = True
            self._json(200, replay)
            return
        envelope = wrapper["envelope"]
        digest = payload_sha256(envelope)
        feedback_id = plane.next_id()
        plane.rows[feedback_id] = {
            "feedback_id": feedback_id,
            "received_ts": plane.clock,
            "category": envelope.get("category", ""),
            "impact": envelope.get("impact", ""),
            "summary": envelope.get("summary", ""),
            "status": "received",
            "payload_sha256": digest,
            "envelope": envelope,
            "channel": wrapper.get("channel"),
            "approval_method": wrapper.get("approval_method"),
            "contact_ok": wrapper.get("contact_ok", False),
        }
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "ok": True,
            "feedback_id": feedback_id,
            "received_ts": plane.clock,
            "payload_sha256": digest,
            "status": "received",
        }
        plane.receipts[key] = receipt
        self._json(200, receipt)

    def _list(self) -> None:
        if not self._feedback_token_ok():
            return
        rows = [
            {
                "feedback_id": row["feedback_id"],
                "received_ts": row["received_ts"],
                "category": row["category"],
                "impact": row["impact"],
                "summary": row["summary"],
                "status": row["status"],
            }
            for row in self._plane.live_rows()
        ]
        self._json(200, {"ok": True, "count": len(rows), "reports": rows})

    def _delete(self, feedback_id: str) -> None:
        if not self._feedback_token_ok():
            return
        row = self._plane.rows.get(feedback_id)
        if row is None or row["status"] == "deleted":
            # Ownership failure and non-existence are indistinguishable.
            self._json(404, _error("NOT_FOUND", "Check the id with `s0ma feedback list`."))
            return
        row["status"] = "deleted"
        # r5 item 2: deletion blanks the denormalized summary too.
        row["summary"] = ""
        row["envelope"] = None
        self._json(200, {"ok": True, "feedback_id": feedback_id, "status": "deleted"})


class _Server(ThreadingHTTPServer):
    """A control plane that shrugs at a client which walked away."""

    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        return


@pytest.fixture
def plane(monkeypatch: pytest.MonkeyPatch) -> Iterator[Plane]:
    """A running fake control plane on 127.0.0.1, torn down after the test."""
    for name in PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
    # Belt and braces: no proxy may intercept the loopback requests.
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")

    state = Plane()
    server = _Server(("127.0.0.1", 0), _Handler)
    server.plane = state  # type: ignore[attr-defined]
    # A short poll interval: the default makes every teardown wait half a
    # second, and this fixture runs dozens of times.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    state.base = f"http://{host}:{port}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def enrolled(plane: Plane) -> Plane:
    """A machine already holding a live feedback token for *plane*.

    The expiry is minted from the REAL clock, not the frozen ``NOW``
    constant: ``StoredToken.is_expired`` compares against wall time, so a
    fixture pinned to ``NOW`` becomes a time bomb the day the constant
    falls into the past (it did — 2026-08-28).
    """
    real_now_ms = int(time.time() * 1000)
    write_token(
        token=TEST_TOKEN, expires_ts=real_now_ms + 86_400_000, cp_host=plane.base
    )
    return plane


def an_envelope(summary: str = "the check command explained nothing") -> FeedbackEnvelope:
    """One valid envelope, rich enough that a lossy transport would show."""
    result = build_envelope(
        category="friction",
        impact="degraded",
        summary=summary,
        expected="a reason for the refusal",
        actual="one line, no reason — and a naïve ünicode summary ✓",
        reproduction=["run s0ma new project", "run s0ma check"],
        context={"cohort": "beta", "os": "macos", "python": "3.11"},
        privacy=FeedbackPrivacy(redacted={"paths": 2}),
    )
    assert result.ok, result.problems
    assert result.envelope is not None
    return result.envelope


def send(
    plane: Plane, envelope: FeedbackEnvelope | None = None, **overrides: Any
) -> FeedbackResult:
    """Submit one report to *plane* with the defaults these tests share."""
    arguments: dict[str, Any] = {
        "idempotency_key": new_idempotency_key(),
        "channel": "cli",
        "approval_method": "cli_tty",
        "contact_ok": False,
        "cp_host": plane.base,
    }
    arguments.update(overrides)
    return submit(envelope if envelope is not None else an_envelope(), **arguments)


# ---------------------------------------------------------------------------
# The submission wrapper (contract r3)
# ---------------------------------------------------------------------------


def test_the_wrapper_carries_the_envelope_and_the_five_request_facts() -> None:
    envelope = an_envelope()
    wrapper = build_submission(
        envelope,
        channel="mcp",
        approval_method="mcp_elicitation",
        contact_ok=True,
        created_ts=NOW,
    )
    assert set(wrapper) == set(WRAPPER_FIELDS)
    assert wrapper["schema"] == SUBMISSION_SCHEMA
    assert wrapper["envelope"] == envelope.to_payload()
    assert wrapper["channel"] == "mcp"
    assert wrapper["created_ts"] == NOW
    assert wrapper["approval_method"] == "mcp_elicitation"
    assert wrapper["contact_ok"] is True


def test_the_hash_covers_the_envelope_alone_not_the_wrapper() -> None:
    envelope = an_envelope()
    wrapper = build_submission(envelope, channel="cli", approval_method="cli_tty")
    assert payload_sha256(wrapper["envelope"]) == envelope.payload_sha256()
    assert payload_sha256(wrapper) != envelope.payload_sha256()


def test_a_created_ts_is_minted_when_the_caller_gives_none() -> None:
    before = int(time.time() * 1000)
    wrapper = build_submission(an_envelope(), channel="cli", approval_method="cli_tty")
    assert before <= wrapper["created_ts"] <= int(time.time() * 1000)


@pytest.mark.parametrize(
    ("channel", "approval_method"),
    [("web", "cli_tty"), ("email", "cli_tty"), ("cli", "trust_me"), ("cli", "")],
)
def test_a_wrapper_fact_outside_the_frozen_vocabulary_is_a_bug_not_a_request(
    channel: str, approval_method: str
) -> None:
    with pytest.raises(ValueError, match="must be one of"):
        build_submission(an_envelope(), channel=channel, approval_method=approval_method)


# ---------------------------------------------------------------------------
# Submitting
# ---------------------------------------------------------------------------


def test_a_submission_sends_the_wrapper_and_returns_a_matching_receipt(
    enrolled: Plane,
) -> None:
    envelope = an_envelope()
    key = new_idempotency_key()

    result = send(enrolled, envelope, idempotency_key=key)

    assert result.ok is True
    assert result.status_code == 200
    assert result.receipt is not None
    assert result.receipt.status == "received"
    assert result.receipt.replayed is False
    assert result.replayed is False
    assert result.feedback_id == result.receipt.feedback_id

    sent = enrolled.requests[-1]
    assert (sent.method, sent.path) == ("POST", "/api/feedback")
    assert sent.header("Idempotency-Key") == key
    assert sent.header("Content-Type") == "application/json"
    assert sent.header("Authorization") == f"Bearer {TEST_TOKEN}"
    assert sent.header("User-Agent") == user_agent()
    assert sent.header("User-Agent").startswith("s0ma-feedback/")

    body = sent.json()
    assert set(body) == set(WRAPPER_FIELDS)
    assert body["schema"] == SUBMISSION_SCHEMA
    assert body["envelope"] == envelope.to_payload()
    assert body["channel"] == "cli"
    assert body["approval_method"] == "cli_tty"
    assert body["contact_ok"] is False
    assert abs(body["created_ts"] - int(time.time() * 1000)) < 60_000


def test_hash_continuity_holds_from_approval_to_receipt(enrolled: Plane) -> None:
    """Approved == transmitted == stored == receipt (contract §3.4)."""
    envelope = an_envelope()
    approved = envelope.payload_sha256()

    result = send(enrolled, envelope)

    transmitted = payload_sha256(enrolled.requests[-1].json()["envelope"])
    assert result.receipt is not None
    stored = enrolled.rows[result.receipt.feedback_id]["payload_sha256"]
    assert approved == transmitted == stored == result.receipt.payload_sha256


def test_a_receipt_confirming_a_different_report_is_not_a_success(
    enrolled: Plane,
) -> None:
    enrolled.queue(
        200,
        {
            "schema": RECEIPT_SCHEMA,
            "ok": True,
            "feedback_id": "fb_somethingelse",
            "received_ts": NOW,
            "payload_sha256": "sha256:" + "0" * 64,
            "status": "received",
        },
    )

    result = send(enrolled)

    assert result.ok is False
    assert result.code == CODE_HASH_MISMATCH
    assert result.receipt is not None, "the mismatching receipt is kept for diagnosis"
    assert "approved" in result.message


def test_non_ascii_text_survives_the_round_trip_byte_for_byte(
    enrolled: Plane,
) -> None:
    envelope = an_envelope("a naïve summary with ✓ and 日本語")

    result = send(enrolled, envelope)

    assert result.ok is True
    received = enrolled.requests[-1].json()["envelope"]
    assert received["summary"] == envelope.summary
    assert payload_sha256(received) == envelope.payload_sha256()


def test_the_license_key_never_travels_with_a_report(enrolled: Plane) -> None:
    exchange(TEST_LICENSE_KEY, cp_host=enrolled.base)
    send(enrolled)

    submitted = enrolled.requests[-1]
    assert submitted.header("Authorization") == f"Bearer {TEST_TOKEN}"
    assert TEST_LICENSE_KEY not in submitted.body.decode("utf-8")
    assert TEST_LICENSE_KEY not in json.dumps(submitted.headers)


def test_the_same_key_replays_the_first_receipt_and_files_nothing_new(
    enrolled: Plane,
) -> None:
    key = new_idempotency_key()

    first = send(enrolled, idempotency_key=key)
    second = send(enrolled, idempotency_key=key)

    assert first.ok and second.ok
    assert first.receipt is not None and second.receipt is not None
    assert second.receipt.feedback_id == first.receipt.feedback_id
    assert second.receipt.payload_sha256 == first.receipt.payload_sha256
    assert first.replayed is False
    assert second.replayed is True
    assert len(enrolled.rows) == 1


def test_a_replay_reports_the_rows_current_status(enrolled: Plane) -> None:
    """r4 item 4: a deleted report is never re-announced as received."""
    key = new_idempotency_key()
    first = send(enrolled, idempotency_key=key)
    assert first.receipt is not None
    delete_report(first.receipt.feedback_id, cp_host=enrolled.base)

    replay = send(enrolled, idempotency_key=key)

    assert replay.ok is True
    assert replay.receipt is not None
    assert replay.receipt.replayed is True
    assert replay.receipt.status == "deleted"


def test_a_report_too_large_to_send_is_refused_before_anything_leaves(
    enrolled: Plane,
) -> None:
    # Built directly: the caps validator would refuse this at composition,
    # which is the point — the transport must refuse it too, on its own.
    oversized = FeedbackEnvelope(
        category="bug",
        impact="blocked",
        summary="too much",
        details="日" * 12_000,
        expected="本" * 4_000,
        actual="語" * 4_000,
    )

    result = send(enrolled, oversized)

    assert result.ok is False
    assert result.code == "PAYLOAD_TOO_LARGE"
    assert "too large" in result.message
    assert enrolled.requests == [], "nothing may be sent once it is known too large"


def test_the_cap_is_measured_on_the_whole_body_not_the_envelope_alone(
    enrolled: Plane,
) -> None:
    """r3: the 32 KB limit applies to the wrapper, envelope included."""
    empty = FeedbackEnvelope(
        category="bug", impact="blocked", summary="just under", details=""
    )
    room = BODY_MAX_BYTES - len(canonical_bytes(empty.to_payload()))
    envelope = FeedbackEnvelope(
        category="bug", impact="blocked", summary="just under", details="d" * room
    )
    assert len(canonical_bytes(envelope.to_payload())) == BODY_MAX_BYTES

    result = send(enrolled, envelope)

    assert result.ok is False
    assert result.code == "PAYLOAD_TOO_LARGE"
    assert enrolled.requests == []


def test_the_plans_name_for_deletion_is_the_same_function() -> None:
    assert client_module.delete is delete_report


def test_a_result_serializes_for_a_json_surface(enrolled: Plane) -> None:
    sent = send(enrolled).to_dict()
    assert sent["ok"] is True
    assert sent["receipt"]["schema"] == RECEIPT_SCHEMA
    assert sent["receipt"]["replayed"] is False
    assert sent["status_code"] == 200
    assert "data" not in sent and "token" not in sent

    enrolled.queue(429, _error("RATE_LIMITED", "Try later."), {"Retry-After": "60"})
    refused = send(enrolled).to_dict()
    assert refused == {
        "ok": False,
        "code": "RATE_LIMITED",
        "message": "This account has sent as much feedback as it can for now.",
        "remediation": "Try later.",
        "status_code": 429,
        "retry_after": 60,
    }


def test_the_default_timeout_is_the_contracted_ten_seconds() -> None:
    assert DEFAULT_TIMEOUT_SECONDS == 10.0
    for function in (submit, list_reports, delete_report):
        assert (
            inspect.signature(function).parameters["timeout"].default
            == DEFAULT_TIMEOUT_SECONDS
        )


# ---------------------------------------------------------------------------
# Refusals: the server's own words, surfaced verbatim
# ---------------------------------------------------------------------------


def test_a_token_the_service_rejects_reports_its_remediation(plane: Plane) -> None:
    write_token(token="not-a-feedback-token", cp_host=plane.base)

    result = send(plane)

    assert result.ok is False
    assert result.code == "INVALID_TOKEN"
    assert result.status_code == 401
    assert result.remediation == (
        "Run `s0ma feedback enroll` to set this machine up."
    )


@pytest.mark.parametrize(
    ("status", "code", "remediation"),
    [
        (403, "NOT_ENTITLED", "Ask the s0ma team to enable feedback for your account."),
        (413, "PAYLOAD_TOO_LARGE", "Shorten the description and try again."),
        (422, "SENSITIVE_CONTENT", "Remove the credential from the description."),
        (400, "SCHEMA_INVALID", "Choose one of the listed categories."),
        (500, "INTERNAL", "Try again in a few minutes."),
    ],
)
def test_every_refusal_surfaces_its_code_and_remediation_verbatim(
    enrolled: Plane, status: int, code: str, remediation: str
) -> None:
    enrolled.queue(status, _error(code, remediation))

    result = send(enrolled)

    assert result.ok is False
    assert result.code == code
    assert result.remediation == remediation
    assert result.status_code == status
    assert result.message, "a refusal always says something a person can read"
    assert "payload" not in result.message.lower()


def test_a_rate_limit_surfaces_the_retry_after_the_service_sent(
    enrolled: Plane,
) -> None:
    enrolled.queue(
        429,
        _error("RATE_LIMITED", "Wait for the limit to reset, then try again."),
        headers={"Retry-After": "300"},
    )

    result = send(enrolled)

    assert result.ok is False
    assert result.code == "RATE_LIMITED"
    assert result.retry_after == 300
    assert result.status_code == 429


def test_an_unparseable_retry_after_is_simply_absent(enrolled: Plane) -> None:
    enrolled.queue(
        429,
        _error("RATE_LIMITED", "Try later."),
        headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
    )
    assert send(enrolled).retry_after is None


def test_a_reply_that_is_not_json_is_reported_not_guessed_at(enrolled: Plane) -> None:
    enrolled.queue(200, b"<html>the wrong door</html>")

    result = send(enrolled)

    assert result.ok is False
    assert result.code == CODE_INVALID_RESPONSE
    assert result.receipt is None


def test_a_json_reply_that_is_not_a_receipt_is_reported(enrolled: Plane) -> None:
    enrolled.queue(200, {"ok": True, "nearly": "a receipt"})

    result = send(enrolled)

    assert result.ok is False
    assert result.code == CODE_INVALID_RESPONSE


def test_an_error_status_without_a_body_still_reads_as_its_code(
    enrolled: Plane,
) -> None:
    enrolled.queue(413, b"")

    result = send(enrolled)

    assert result.ok is False
    assert result.code == "PAYLOAD_TOO_LARGE"
    assert result.remediation is not None


def test_a_five_hundred_without_a_body_reads_as_a_service_problem(
    enrolled: Plane,
) -> None:
    enrolled.queue(500, b"upstream exploded")

    result = send(enrolled)

    assert result.ok is False
    assert result.code == "SERVER_ERROR"
    assert "at its end" in result.message


# ---------------------------------------------------------------------------
# Failures that never reached the service
# ---------------------------------------------------------------------------


def test_a_timeout_returns_a_structured_failure_and_keeps_the_draft(
    enrolled: Plane,
) -> None:
    envelope = an_envelope()
    draft = save_draft(envelope, channel="cli", approval_method="cli_tty")
    enrolled.queue(200, {"ok": True}, delay=0.6)

    result = send(
        enrolled, envelope, idempotency_key=draft.idempotency_key, timeout=0.05
    )

    assert result.ok is False
    assert result.code == CODE_TIMEOUT
    assert result.status_code is None
    assert result.receipt is None
    assert result.remediation is not None
    assert "safe" in result.remediation
    assert load_draft(draft.draft_id) is not None, "the draft is the user's safety net"


def test_the_explicit_retry_after_a_failure_replays_rather_than_duplicates(
    enrolled: Plane,
) -> None:
    """The whole point of storing the key with the draft."""
    envelope = an_envelope()
    draft = save_draft(envelope, channel="cli", approval_method="cli_tty")
    enrolled.queue(200, {"ok": True}, delay=0.6)

    failed = send(
        enrolled, envelope, idempotency_key=draft.idempotency_key, timeout=0.05
    )
    kept = load_draft(draft.draft_id)
    assert failed.ok is False
    assert kept is not None

    first = send(enrolled, kept.envelope, idempotency_key=kept.idempotency_key)
    again = send(enrolled, kept.envelope, idempotency_key=kept.idempotency_key)

    assert first.ok and again.ok
    assert again.replayed is True
    assert len(enrolled.rows) == 1


def test_an_unreachable_service_is_reported_in_plain_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    # Port 9 is discard; nothing answers on it, and nothing leaves the host.
    write_token(token=TEST_TOKEN, cp_host="http://127.0.0.1:9")

    result = submit(
        an_envelope(),
        idempotency_key=new_idempotency_key(),
        channel="cli",
        approval_method="cli_tty",
        timeout=1.0,
    )

    assert result.ok is False
    # Either refusal flavour is honest here: Windows commonly reports a
    # connection to a closed local port as a timeout rather than an
    # immediate refusal. What must hold is the plain-language reporting.
    assert result.code in {CODE_UNREACHABLE, CODE_TIMEOUT}
    assert result.status_code is None
    assert result.receipt is None
    assert result.message.startswith("The s0ma feedback service")
    assert result.message.endswith("so nothing was sent.")
    assert "payload" not in result.message.lower()
    assert result.remediation is not None
    assert "safe" in result.remediation
    assert "payload" not in result.remediation.lower()


def test_a_machine_with_no_token_is_told_how_to_set_one_up(plane: Plane) -> None:
    result = send(plane)

    assert result.ok is False
    assert result.code == "INVALID_TOKEN"
    assert result.remediation is not None
    assert "s0ma feedback enroll" in result.remediation
    assert plane.requests == [], "nothing is sent without a token"


# ---------------------------------------------------------------------------
# Listing and deleting (contract §2, r4 item 3)
# ---------------------------------------------------------------------------


def test_listing_nothing_is_an_empty_answer_not_a_failure(enrolled: Plane) -> None:
    result = list_reports(cp_host=enrolled.base)

    assert result.ok is True
    assert result.reports == ()
    assert (result.data or {})["count"] == 0
    assert enrolled.requests[-1].method == "GET"


def test_listing_returns_typed_rows_newest_first(enrolled: Plane) -> None:
    send(enrolled, an_envelope("first report"))
    enrolled.clock += 1_000
    send(enrolled, an_envelope("second report"))

    result = list_reports(cp_host=enrolled.base)

    assert result.ok is True
    assert [row.summary for row in result.reports] == ["second report", "first report"]
    assert result.reports[0].category == "friction"
    assert result.reports[0].impact == "degraded"
    assert result.reports[0].status == "received"
    assert result.reports[0].feedback_id.startswith("fb_")


def test_a_deleted_report_is_absent_from_the_listing(enrolled: Plane) -> None:
    kept = send(enrolled, an_envelope("kept"))
    gone = send(enrolled, an_envelope("removed"))
    assert gone.receipt is not None and kept.receipt is not None

    deletion = delete_report(gone.receipt.feedback_id, cp_host=enrolled.base)
    listed = list_reports(cp_host=enrolled.base)

    assert deletion.ok is True
    assert deletion.feedback_id == gone.receipt.feedback_id
    assert [row.feedback_id for row in listed.reports] == [kept.receipt.feedback_id]


def test_deleting_an_unknown_report_says_not_found(enrolled: Plane) -> None:
    result = delete_report("fb_0000000000000000", cp_host=enrolled.base)

    assert result.ok is False
    assert result.code == "NOT_FOUND"
    assert result.status_code == 404


def test_deleting_nothing_deletes_nothing(enrolled: Plane) -> None:
    result = delete_report("   ", cp_host=enrolled.base)

    assert result.ok is False
    assert result.code == "BAD_REQUEST"
    assert enrolled.requests == []


def test_a_report_id_is_escaped_into_the_url(enrolled: Plane) -> None:
    delete_report("fb_../../admin", cp_host=enrolled.base)

    assert enrolled.requests[-1].path == "/api/feedback/fb_..%2F..%2Fadmin"


def test_a_listing_that_is_not_a_listing_is_reported(enrolled: Plane) -> None:
    enrolled.queue(200, {"ok": True, "count": 1, "reports": "lots"})
    assert list_reports(cp_host=enrolled.base).code == CODE_INVALID_RESPONSE

    enrolled.queue(200, {"ok": True, "count": 1, "reports": [{"no": "id"}]})
    assert list_reports(cp_host=enrolled.base).code == CODE_INVALID_RESPONSE


# ---------------------------------------------------------------------------
# The token store (contract §2.2, §8)
# ---------------------------------------------------------------------------


def test_a_stored_token_round_trips_with_the_four_contract_keys(
    isolated_home: Path,
) -> None:
    write_token(token=TEST_TOKEN, expires_ts=NOW + 1_000, cp_host="account.example.test")

    document = json.loads(token_path().read_text("utf-8"))
    lookup = read_token(now_ms=NOW)

    assert set(document) == {"token", "token_prefix", "expires_ts", "cp_host"}
    assert document["token_prefix"] == TEST_TOKEN[:12]
    assert token_path() == isolated_home / ".s0ma" / "feedback-token"
    assert lookup.ok is True
    assert lookup.token is not None
    assert lookup.token.token == TEST_TOKEN
    assert lookup.token.cp_host == "account.example.test"
    assert lookup.token.source == "file"


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes; Windows is best-effort")
def test_the_token_file_is_owner_only() -> None:
    write_token(token=TEST_TOKEN)
    assert stat.S_IMODE(token_path().stat().st_mode) == 0o600


def test_the_plaintext_token_never_appears_in_a_repr() -> None:
    write_token(token=TEST_TOKEN, expires_ts=NOW + 1_000)
    lookup = read_token(now_ms=NOW)
    result = FeedbackResult(ok=True, token=lookup.token)

    assert TEST_TOKEN not in repr(lookup)
    assert TEST_TOKEN not in repr(result)
    assert TEST_TOKEN not in json.dumps(result.to_dict())
    assert TEST_TOKEN[:12] in repr(lookup), "the prefix is what people recognise"


def test_the_environment_overrides_the_stored_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_token(token="s0ma_fb_from_the_file", cp_host="stored.example.test")
    monkeypatch.setenv(TOKEN_ENV_VAR, "  s0ma_fb_from_the_environment  ")
    monkeypatch.setenv("S0MA_CP_HOST", "env.example.test")

    lookup = read_token()

    assert lookup.token is not None
    assert lookup.token.token == "s0ma_fb_from_the_environment"
    assert lookup.token.cp_host == "env.example.test"
    assert lookup.token.source == "environment"
    assert lookup.token.is_expired() is False, "an unknown expiry is not an expiry"


def test_an_expired_token_reads_as_absent_with_a_reason() -> None:
    write_token(token=TEST_TOKEN, expires_ts=NOW)

    lookup = read_token(now_ms=NOW)

    assert lookup.ok is False
    assert lookup.token is None
    assert lookup.reason == TOKEN_EXPIRED
    assert lookup.remediation is not None
    assert "s0ma feedback enroll" in lookup.remediation
    assert read_token(now_ms=NOW - 1).ok is True


def test_a_missing_token_reads_as_absent_with_a_reason() -> None:
    lookup = read_token()

    assert lookup.token is None
    assert lookup.reason == TOKEN_ABSENT
    assert lookup.remediation is not None
    assert "not set up" in lookup.remediation


@pytest.mark.parametrize(
    "content",
    ["{not json", "[]", '{"token": ""}', '{"token": "x", "expires_ts": "soon"}'],
)
def test_an_unreadable_token_file_reads_as_absent_with_a_reason(content: str) -> None:
    write_token(token=TEST_TOKEN)
    token_path().write_text(content, encoding="utf-8")

    lookup = read_token()

    assert lookup.token is None
    assert lookup.reason == TOKEN_UNREADABLE


def test_clearing_the_token_reports_whether_one_was_there() -> None:
    write_token(token=TEST_TOKEN)
    assert clear_token() is True
    assert clear_token() is False
    assert read_token().reason == TOKEN_ABSENT


def test_an_empty_token_is_never_stored() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        write_token(token="   ")


# ---------------------------------------------------------------------------
# Host resolution (the installer's rule)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("account.kn0wthyself.ai", "https://account.kn0wthyself.ai"),
        ("example.test", "https://example.test"),
        ("https://example.test", "https://example.test"),
        ("http://127.0.0.1:8788", "http://127.0.0.1:8788"),
        ("http://127.0.0.1:8788/", "http://127.0.0.1:8788"),
        ("  example.test  ", "https://example.test"),
    ],
)
def test_a_bare_host_gets_https_and_a_scheme_is_honoured(
    given: str, expected: str
) -> None:
    assert base_url(given) == expected


def test_the_default_host_is_the_production_control_plane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DEFAULT_CP_HOST == "account.kn0wthyself.ai"
    assert base_url() == "https://account.kn0wthyself.ai"
    monkeypatch.setenv("S0MA_CP_HOST", "http://127.0.0.1:8788")
    assert base_url() == "http://127.0.0.1:8788"


# ---------------------------------------------------------------------------
# Enrollment (the one time a license key is sent)
# ---------------------------------------------------------------------------


def test_enrolling_sends_the_license_key_and_stores_the_token(plane: Plane) -> None:
    result = exchange(TEST_LICENSE_KEY, cp_host=plane.base)

    sent = plane.requests[-1]
    assert (sent.method, sent.path) == ("POST", "/api/feedback/token")
    assert sent.header("Authorization") == f"Bearer {TEST_LICENSE_KEY}"
    assert plane.licenses == [TEST_LICENSE_KEY]
    assert result.ok is True
    assert result.token is not None
    assert result.token.token == TEST_TOKEN
    assert result.token.token_prefix == TEST_TOKEN[:12]
    assert result.token.cp_host == plane.base
    assert result.data is None, "the one body holding a token is not kept"

    stored = read_token(now_ms=NOW)
    assert stored.token is not None
    assert stored.token.token == TEST_TOKEN
    assert stored.token.cp_host == plane.base


def test_enrollment_sends_no_pseudonym_unless_it_is_asked_for(plane: Plane) -> None:
    exchange(TEST_LICENSE_KEY, cp_host=plane.base)
    assert plane.requests[-1].json() == {}

    exchange(TEST_LICENSE_KEY, cp_host=plane.base, pseudonym="abc123")
    assert plane.requests[-1].json() == {"pseudonym": "abc123"}


def test_a_token_from_enrollment_is_the_one_a_report_then_uses(plane: Plane) -> None:
    exchange(TEST_LICENSE_KEY, cp_host=plane.base)

    result = submit(
        an_envelope(),
        idempotency_key=new_idempotency_key(),
        channel="cli",
        approval_method="cli_tty",
    )

    assert result.ok is True, "the stored token remembers its own host"
    assert plane.requests[-1].header("Authorization") == f"Bearer {TEST_TOKEN}"


def test_a_refused_enrollment_stores_nothing(plane: Plane) -> None:
    plane.queue(403, _error("NOT_ENTITLED", "Ask the s0ma team for a tester key."))

    result = exchange(TEST_LICENSE_KEY, cp_host=plane.base)

    assert result.ok is False
    assert result.code == "NOT_ENTITLED"
    assert result.remediation == "Ask the s0ma team for a tester key."
    assert read_token().reason == TOKEN_ABSENT
    assert not token_path().exists()


def test_an_enrollment_reply_without_a_token_stores_nothing(plane: Plane) -> None:
    plane.queue(200, {"ok": True, "scopes": ["feedback:write"]})

    result = exchange(TEST_LICENSE_KEY, cp_host=plane.base)

    assert result.ok is False
    assert result.code == CODE_INVALID_RESPONSE
    assert not token_path().exists()


def test_enrolling_without_a_key_asks_for_one_and_sends_nothing(plane: Plane) -> None:
    result = exchange("   ", cp_host=plane.base)

    assert result.ok is False
    assert result.code == "BAD_REQUEST"
    assert result.remediation is not None
    assert "S0MA_LICENSE_KEY" in result.remediation
    assert plane.requests == []


def test_enrollment_records_the_scopes_as_the_wire_array(plane: Plane) -> None:
    """r2 item 1: scopes are a JSON array, not the D1 CSV encoding."""
    exchange(TEST_LICENSE_KEY, cp_host=plane.base)
    assert read_token(now_ms=NOW).ok is True


# ---------------------------------------------------------------------------
# The no-network boundary
# ---------------------------------------------------------------------------


class SocketCounter:
    """Counts every socket the process opens while it is installed."""

    def __init__(self) -> None:
        self.count = 0


def _count_sockets(monkeypatch: pytest.MonkeyPatch) -> SocketCounter:
    real = socket.socket
    counter = SocketCounter()

    def spy(*args: object, **kwargs: object) -> object:
        counter.count += 1
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "socket", spy)
    return counter


def test_importing_the_engine_and_working_locally_opens_no_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = _count_sockets(monkeypatch)
    saved = {
        name: module
        for name, module in sys.modules.items()
        if name == "s0ma_dsl.feedback" or name.startswith("s0ma_dsl.feedback.")
    }
    for name in saved:
        del sys.modules[name]
    try:
        feedback = importlib.import_module("s0ma_dsl.feedback")
        built = feedback.build_context(surface=feedback.SurfaceInfo("tool", "check"))
        composed = feedback.build_envelope(
            category="bug",
            impact="degraded",
            summary="composed, redacted, drafted and hashed with no network",
            context=built,
            privacy=feedback.FeedbackPrivacy(),
        )
        assert composed.ok is True
        assert composed.envelope is not None
        cleaned, counts = feedback.redact("mail me at someone@example.com")
        draft = feedback.save_draft(composed.envelope)
        assert counts
        assert "someone@example.com" not in cleaned
        assert feedback.load_draft(draft.draft_id) is not None
        assert feedback.read_token().ok is False
        assert feedback.payload_sha256(composed.envelope.to_payload()).startswith(
            "sha256:"
        )
        assert feedback.user_agent().startswith("s0ma-feedback/")
    finally:
        for name in [
            name
            for name in sys.modules
            if name == "s0ma_dsl.feedback" or name.startswith("s0ma_dsl.feedback.")
        ]:
            del sys.modules[name]
        sys.modules.update(saved)
        s0ma_dsl = importlib.import_module("s0ma_dsl")
        s0ma_dsl.feedback = saved["s0ma_dsl.feedback"]  # type: ignore[attr-defined]

    assert counter.count == 0, "the prepare path must never reach the network"


def test_only_an_explicit_client_call_opens_a_socket(
    enrolled: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    counter = _count_sockets(monkeypatch)

    read_token()
    save_draft(an_envelope())
    build_submission(an_envelope(), channel="cli", approval_method="cli_tty")
    assert counter.count == 0

    assert send(enrolled).ok is True
    assert counter.count >= 1
