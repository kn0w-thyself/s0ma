"""Feedback drafts and the local receipts log (contract §8).

Two small stores, both under ``~/.s0ma/`` and both owner-only:

* ``feedback-drafts/fbd_<8-hex>.json`` — a report the user composed but has
  not (yet) sent. A draft carries the exact envelope, the idempotency key
  minted when the draft was created, and the wrapper facts a resubmit needs
  (channel, approval method, contact permission). Drafts expire after
  :data:`DRAFT_TTL_DAYS` days and are purged whenever they are listed.
* ``feedback-receipts.jsonl`` — one line per report this machine sent
  successfully, so ids stay findable after the conversation scrolls away
  (contract §12 A-3). It is the offline source for the CLI's report list.

Why the idempotency key lives with the draft: a submission that fails in
transport is not known to have failed on the server. Retrying with the
*same* key is therefore the only safe retry — the server replays the
original receipt instead of filing a second report (contract §2). Minting a
fresh key on retry would risk duplicates, so the key is created once, when
the draft is, and travels with it.

Nothing here touches the network, and nothing here validates the wrapper
vocabulary: a draft records what was composed, and the gate that decides
whether it may go on the wire lives where it goes on the wire
(:func:`s0ma_dsl.feedback.client.build_submission`).

Determinism note (contract §1.4): draft ids and idempotency keys are
deliberately random. INV-5 governs emitted artifacts, not runtime state.
"""

from __future__ import annotations

import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma_dsl.feedback.model import FeedbackEnvelope, FeedbackPrivacy
from s0ma_dsl.feedback.state import state_dir, write_private_text

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "DRAFTS_DIRNAME",
    "DRAFT_ID_BYTES",
    "DRAFT_ID_PREFIX",
    "DRAFT_SCHEMA",
    "DRAFT_TTL_DAYS",
    "RECEIPTS_FILENAME",
    "SUMMARY_LOG_CHARS",
    "FeedbackDraft",
    "ReceiptLogEntry",
    "append_receipt",
    "delete_draft",
    "drafts_dir",
    "list_drafts",
    "load_draft",
    "new_draft_id",
    "new_idempotency_key",
    "purge_expired_drafts",
    "read_receipts",
    "receipts_path",
    "save_draft",
]

#: Directory holding one JSON file per draft (contract §8).
DRAFTS_DIRNAME = "feedback-drafts"

#: Append-only log of successful submissions from this machine (§8, A-3).
RECEIPTS_FILENAME = "feedback-receipts.jsonl"

#: Draft id prefix — ``fbd_`` distinguishes a draft from a server-side
#: ``fb_`` feedback id at a glance, in copy and in support conversations.
DRAFT_ID_PREFIX = "fbd_"

#: Random bytes behind a draft id: 4 bytes rendered as 8 hex characters.
DRAFT_ID_BYTES = 4

#: Local file-format marker. Never transmitted: the wire schemas are
#: ``s0ma-feedback@1`` and ``s0ma-feedback-submission@1``.
DRAFT_SCHEMA = "s0ma-feedback-draft@1"

#: Drafts older than this are removed the next time drafts are listed.
DRAFT_TTL_DAYS = 30

#: Characters of the summary kept in the receipts log — enough to recognise
#: a report, not a second copy of it.
SUMMARY_LOG_CHARS = 60

_MS_PER_DAY = 86_400_000
_DRAFT_TTL_MS = DRAFT_TTL_DAYS * _MS_PER_DAY

# A draft id is also a filename, so it is validated before it reaches the
# filesystem: an id arriving from a command line can never resolve outside
# the drafts directory.
_DRAFT_ID_RE = re.compile(r"\Afbd_[0-9a-f]{8}\Z")

# Envelope fields this module knows how to restore. A stored draft carrying
# anything else is treated as corrupt rather than silently trimmed — a
# dropped field would change the hash the user approved.
_ENVELOPE_TEXT_FIELDS = ("summary", "expected", "actual", "details")


def _now_ms() -> int:
    """Epoch milliseconds from the client clock (the contract's ts unit)."""
    return int(time.time() * 1000)


def new_draft_id() -> str:
    """Return a fresh ``fbd_<8-hex>`` draft id."""
    return f"{DRAFT_ID_PREFIX}{secrets.token_hex(DRAFT_ID_BYTES)}"


def new_idempotency_key() -> str:
    """Return a fresh submission key (uuid4, the contract's client-uuid)."""
    return str(uuid.uuid4())


def drafts_dir(home: Path | None = None) -> Path:
    """Return ``~/.s0ma/feedback-drafts`` without creating anything."""
    return state_dir(home) / DRAFTS_DIRNAME


def receipts_path(home: Path | None = None) -> Path:
    """Return ``~/.s0ma/feedback-receipts.jsonl`` without creating it."""
    return state_dir(home) / RECEIPTS_FILENAME


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackDraft:
    """One composed-but-unsent feedback report, as stored on this machine.

    ``idempotency_key`` is minted once, with the draft, and reused by every
    retry: that is what makes a retry safe after an unclear failure.
    """

    draft_id: str
    envelope: FeedbackEnvelope
    idempotency_key: str
    created_ts: int
    channel: str = "cli"
    approval_method: str = "cli_tty"
    contact_ok: bool = False

    @property
    def expires_ts(self) -> int:
        """Epoch-ms after which listing drafts removes this one."""
        return self.created_ts + _DRAFT_TTL_MS

    def is_expired(self, now_ms: int | None = None) -> bool:
        """Whether this draft has passed its 30-day life."""
        return (now_ms if now_ms is not None else _now_ms()) >= self.expires_ts

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the stored file shape."""
        return {
            "schema": DRAFT_SCHEMA,
            "draft_id": self.draft_id,
            "created_ts": self.created_ts,
            "idempotency_key": self.idempotency_key,
            "channel": self.channel,
            "approval_method": self.approval_method,
            "contact_ok": self.contact_ok,
            "envelope": self.envelope.to_payload(),
        }


def _privacy_from_dict(value: Any) -> FeedbackPrivacy:
    """Rebuild a privacy block, refusing anything but its four keys."""
    if not isinstance(value, dict):
        raise ValueError("privacy must be an object")
    unknown = sorted(set(value) - {"profile", "includes_source", "includes_transcript", "redacted"})
    if unknown:
        raise ValueError(f"unknown privacy keys: {', '.join(unknown)}")
    redacted = value.get("redacted", {})
    if not isinstance(redacted, dict):
        raise ValueError("privacy.redacted must be an object")
    return FeedbackPrivacy(
        profile=str(value.get("profile", "")),
        includes_source=bool(value.get("includes_source", False)),
        includes_transcript=bool(value.get("includes_transcript", False)),
        redacted={str(key): int(count) for key, count in redacted.items()},
    )


def _envelope_from_payload(payload: Any) -> FeedbackEnvelope:
    """Rebuild a :class:`FeedbackEnvelope` from its stored JSON object.

    Raises :class:`ValueError` on anything this version cannot restore
    exactly — an unknown key, a wrong type. Callers treat that as a corrupt
    draft rather than guessing, because a guessed envelope would no longer
    hash to what the user approved.
    """
    if not isinstance(payload, dict):
        raise ValueError("envelope must be an object")
    known = {*_ENVELOPE_TEXT_FIELDS, "schema", "category", "impact", "reproduction",
             "context", "privacy"}
    unknown = sorted(set(payload) - known)
    if unknown:
        raise ValueError(f"unknown envelope keys: {', '.join(unknown)}")
    for name in ("schema", "category", "impact", *_ENVELOPE_TEXT_FIELDS):
        if name in payload and not isinstance(payload[name], str):
            raise ValueError(f"{name} must be a string")
    steps = payload.get("reproduction", [])
    if not isinstance(steps, list) or any(not isinstance(step, str) for step in steps):
        raise ValueError("reproduction must be a list of strings")
    context = payload.get("context")
    if context is not None and not isinstance(context, dict):
        raise ValueError("context must be an object")
    privacy = payload.get("privacy")
    return FeedbackEnvelope(
        category=str(payload.get("category", "")),
        impact=str(payload.get("impact", "")),
        summary=str(payload.get("summary", "")),
        expected=payload.get("expected"),
        actual=payload.get("actual"),
        details=payload.get("details"),
        reproduction=tuple(steps),
        context=dict(context) if context is not None else None,
        privacy=_privacy_from_dict(privacy) if privacy is not None else None,
        schema=str(payload.get("schema", "")),
    )


def _draft_from_dict(document: Any) -> FeedbackDraft:
    """Rebuild a draft from its file contents, or raise :class:`ValueError`."""
    if not isinstance(document, dict):
        raise ValueError("a draft file must hold an object")
    draft_id = document.get("draft_id")
    if not isinstance(draft_id, str) or not _DRAFT_ID_RE.match(draft_id):
        raise ValueError("missing or malformed draft id")
    key = document.get("idempotency_key")
    if not isinstance(key, str) or not key:
        raise ValueError("missing idempotency key")
    created_ts = document.get("created_ts")
    if not isinstance(created_ts, int) or isinstance(created_ts, bool):
        raise ValueError("missing created timestamp")
    return FeedbackDraft(
        draft_id=draft_id,
        envelope=_envelope_from_payload(document.get("envelope")),
        idempotency_key=key,
        created_ts=created_ts,
        channel=str(document.get("channel", "cli")),
        approval_method=str(document.get("approval_method", "cli_tty")),
        contact_ok=bool(document.get("contact_ok", False)),
    )


def _draft_path(draft_id: str, home: Path | None = None) -> Path | None:
    """Path for *draft_id*, or ``None`` when the id is not a draft id."""
    if not _DRAFT_ID_RE.match(draft_id):
        return None
    return drafts_dir(home) / f"{draft_id}.json"


def save_draft(
    envelope: FeedbackEnvelope,
    *,
    channel: str = "cli",
    approval_method: str = "cli_tty",
    contact_ok: bool = False,
    idempotency_key: str | None = None,
    draft_id: str | None = None,
    created_ts: int | None = None,
    home: Path | None = None,
) -> FeedbackDraft:
    """Write *envelope* to a draft file and return the stored draft.

    Called with no *draft_id* it mints one, along with the idempotency key
    that every later retry of this report will reuse. Called with an
    existing *draft_id* and its key it rewrites that draft in place — the
    path a decline-then-edit takes, which must not change the key.

    Raises :class:`ValueError` on a malformed *draft_id* and
    :class:`OSError` when the state directory cannot be written.
    """
    identifier = new_draft_id() if draft_id is None else draft_id
    if not _DRAFT_ID_RE.match(identifier):
        raise ValueError(f"not a draft id: {identifier!r}")
    draft = FeedbackDraft(
        draft_id=identifier,
        envelope=envelope,
        idempotency_key=(
            new_idempotency_key() if idempotency_key is None else idempotency_key
        ),
        created_ts=_now_ms() if created_ts is None else created_ts,
        channel=channel,
        approval_method=approval_method,
        contact_ok=contact_ok,
    )
    text = json.dumps(draft.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)
    write_private_text(drafts_dir(home) / f"{identifier}.json", f"{text}\n")
    return draft


def load_draft(draft_id: str, home: Path | None = None) -> FeedbackDraft | None:
    """Return the stored draft, or ``None`` when it is absent or corrupt.

    A malformed id reads as ``None`` rather than raising: draft ids arrive
    from command lines, and a typo is an ordinary user event, not a crash.
    """
    path = _draft_path(draft_id, home)
    if path is None:
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return _draft_from_dict(json.loads(raw))
    except (ValueError, TypeError):
        return None


def delete_draft(draft_id: str, home: Path | None = None) -> bool:
    """Delete one draft; return whether a file was actually removed."""
    path = _draft_path(draft_id, home)
    if path is None:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def purge_expired_drafts(
    home: Path | None = None, now_ms: int | None = None
) -> tuple[str, ...]:
    """Delete drafts older than :data:`DRAFT_TTL_DAYS`; return their ids.

    Unreadable or corrupt files are left alone: they are the user's data,
    and this function's job is expiry, not cleanup.
    """
    moment = _now_ms() if now_ms is None else now_ms
    removed: list[str] = []
    for draft in _stored_drafts(home):
        if draft.is_expired(moment):
            path = _draft_path(draft.draft_id, home)
            if path is not None:
                try:
                    path.unlink()
                except OSError:
                    continue
                removed.append(draft.draft_id)
    return tuple(sorted(removed))


def _stored_drafts(home: Path | None = None) -> tuple[FeedbackDraft, ...]:
    """Every readable draft on disk, in no particular order."""
    directory = drafts_dir(home)
    try:
        paths = sorted(directory.glob(f"{DRAFT_ID_PREFIX}*.json"))
    except OSError:
        return ()
    drafts: list[FeedbackDraft] = []
    for path in paths:
        draft = load_draft(path.stem, home)
        if draft is not None:
            drafts.append(draft)
    return tuple(drafts)


def list_drafts(
    home: Path | None = None, now_ms: int | None = None
) -> tuple[FeedbackDraft, ...]:
    """Return live drafts, newest first, purging expired ones first.

    Listing is the moment expiry happens (contract §8): there is no daemon,
    so the act of looking is what collects the garbage.
    """
    purge_expired_drafts(home, now_ms)
    return tuple(
        sorted(_stored_drafts(home), key=lambda draft: draft.created_ts, reverse=True)
    )


# ---------------------------------------------------------------------------
# Receipts log
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReceiptLogEntry:
    """One line of ``feedback-receipts.jsonl`` — a report sent from here."""

    feedback_id: str
    ts: int
    category: str
    summary60: str
    payload_sha256: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the stored line shape (contract §8)."""
        return {
            "feedback_id": self.feedback_id,
            "ts": self.ts,
            "category": self.category,
            "summary60": self.summary60,
            "payload_sha256": self.payload_sha256,
        }


def _entry_from_dict(document: Any) -> ReceiptLogEntry:
    """Rebuild one log entry, or raise :class:`ValueError`."""
    if not isinstance(document, dict):
        raise ValueError("a receipts line must hold an object")
    feedback_id = document.get("feedback_id")
    payload_hash = document.get("payload_sha256")
    ts = document.get("ts")
    if not isinstance(feedback_id, str) or not feedback_id:
        raise ValueError("missing feedback id")
    if not isinstance(payload_hash, str) or not payload_hash:
        raise ValueError("missing payload_sha256")
    if not isinstance(ts, int) or isinstance(ts, bool):
        raise ValueError("missing timestamp")
    return ReceiptLogEntry(
        feedback_id=feedback_id,
        ts=ts,
        category=str(document.get("category", "")),
        summary60=str(document.get("summary60", "")),
        payload_sha256=payload_hash,
    )


def read_receipts(home: Path | None = None) -> tuple[ReceiptLogEntry, ...]:
    """Return every readable receipts-log entry, oldest first.

    Unreadable lines are skipped rather than fatal: a log truncated by a
    crash must still answer "which reports did I send?".
    """
    try:
        raw = receipts_path(home).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    entries: list[ReceiptLogEntry] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            entries.append(_entry_from_dict(json.loads(line)))
        except (ValueError, TypeError):
            continue
    return tuple(entries)


def append_receipt(
    *,
    feedback_id: str,
    category: str,
    summary: str,
    payload_sha256: str,
    ts: int | None = None,
    home: Path | None = None,
) -> ReceiptLogEntry:
    """Append one sent report to the receipts log and return the entry.

    *summary* is truncated to :data:`SUMMARY_LOG_CHARS` characters — the log
    is an index, not a second copy of the report.

    The append is a whole-file rewrite through
    :func:`~s0ma_dsl.feedback.state.write_private_text`, which is what keeps
    every private write on one audited path (owner-only from creation, UTF-8,
    LF). The log is a few kilobytes at most, so the cost is nil; the
    trade-off is that two processes appending at the same instant could lose
    a line, which for a single-user CLI log is the right side to err on.
    """
    entry = ReceiptLogEntry(
        feedback_id=feedback_id,
        ts=_now_ms() if ts is None else ts,
        category=category,
        summary60=summary[:SUMMARY_LOG_CHARS],
        payload_sha256=payload_sha256,
    )
    path = receipts_path(home)
    try:
        existing = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        existing = ""
    if existing and not existing.endswith("\n"):
        existing = f"{existing}\n"
    line = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True)
    write_private_text(path, f"{existing}{line}\n")
    return entry
