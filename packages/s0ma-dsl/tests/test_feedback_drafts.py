"""FB-M6: drafts and the receipts log (contract §8).

The rules held here as executable facts:

* a draft round-trips exactly — the envelope that comes back hashes to what
  went in, because the idempotency key stored beside it is only safe while
  the report it belongs to is unchanged;
* the idempotency key is minted once, with the draft, and survives a
  re-save (the decline-then-edit path must not mint a second key);
* drafts expire after 30 days and listing is what purges them;
* a draft id arriving from a command line can never resolve outside the
  drafts directory;
* the receipts log is append-only, survives a corrupt line, and keeps only
  60 characters of the summary.

Every test runs against an isolated HOME (``isolated_home`` is autouse), so
no test can read or write the developer's real ``~/.s0ma``.
"""

from __future__ import annotations

import json
import os
import re
import stat
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.feedback.drafts import (
    DRAFT_TTL_DAYS,
    SUMMARY_LOG_CHARS,
    FeedbackDraft,
    append_receipt,
    delete_draft,
    drafts_dir,
    list_drafts,
    load_draft,
    new_draft_id,
    new_idempotency_key,
    purge_expired_drafts,
    read_receipts,
    receipts_path,
    save_draft,
)
from s0ma_dsl.feedback.model import FeedbackEnvelope, FeedbackPrivacy, build_envelope
from s0ma_dsl.feedback.state import state_dir

if TYPE_CHECKING:
    from pathlib import Path

DRAFT_ID_RE = re.compile(r"\Afbd_[0-9a-f]{8}\Z")
UUID4_RE = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)

MS_PER_DAY = 86_400_000
NOW = 1_787_850_000_000


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME (and ``%USERPROFILE%``) at a throwaway directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def an_envelope(summary: str = "the check command explained nothing") -> FeedbackEnvelope:
    """One valid envelope, rich enough that a lossy round-trip would show."""
    result = build_envelope(
        category="friction",
        impact="degraded",
        summary=summary,
        expected="a reason for the refusal",
        actual="one line, no reason",
        details="Happens every time on a fresh project.",
        reproduction=["run s0ma new project", "run s0ma check"],
        context={"cohort": "beta", "os": "macos", "python": "3.11"},
        privacy=FeedbackPrivacy(redacted={"paths": 2}),
    )
    assert result.ok, result.problems
    assert result.envelope is not None
    return result.envelope


# ---------------------------------------------------------------------------
# Drafts round-trip
# ---------------------------------------------------------------------------


def test_a_saved_draft_round_trips_without_changing_the_report() -> None:
    envelope = an_envelope()
    saved = save_draft(envelope, channel="mcp", approval_method="mcp_elicitation")

    loaded = load_draft(saved.draft_id)

    assert loaded is not None
    assert loaded.envelope.to_payload() == envelope.to_payload()
    assert loaded.envelope.payload_sha256() == envelope.payload_sha256()
    assert loaded.idempotency_key == saved.idempotency_key
    assert loaded.created_ts == saved.created_ts
    assert loaded.channel == "mcp"
    assert loaded.approval_method == "mcp_elicitation"
    assert loaded.contact_ok is False


def test_the_wrapper_facts_a_resubmit_needs_are_stored() -> None:
    saved = save_draft(
        an_envelope(), channel="cli", approval_method="cli_tty", contact_ok=True
    )
    loaded = load_draft(saved.draft_id)
    assert loaded is not None
    assert (loaded.channel, loaded.approval_method, loaded.contact_ok) == (
        "cli",
        "cli_tty",
        True,
    )


def test_draft_ids_look_like_the_contract_says_and_do_not_repeat() -> None:
    ids = {new_draft_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(DRAFT_ID_RE.match(identifier) for identifier in ids)
    assert DRAFT_ID_RE.match(save_draft(an_envelope()).draft_id)


def test_the_idempotency_key_is_a_uuid4_and_differs_per_draft() -> None:
    first = save_draft(an_envelope())
    second = save_draft(an_envelope())
    assert UUID4_RE.match(first.idempotency_key)
    assert first.idempotency_key != second.idempotency_key


def test_re_saving_a_draft_keeps_its_key_so_a_retry_stays_safe() -> None:
    """The decline-then-edit path must not mint a second key."""
    first = save_draft(an_envelope())
    edited = save_draft(
        an_envelope("a clearer summary"),
        draft_id=first.draft_id,
        idempotency_key=first.idempotency_key,
        created_ts=first.created_ts,
    )
    reloaded = load_draft(first.draft_id)

    assert edited.idempotency_key == first.idempotency_key
    assert reloaded is not None
    assert reloaded.idempotency_key == first.idempotency_key
    assert reloaded.envelope.summary == "a clearer summary"
    assert len(list(drafts_dir().glob("fbd_*.json"))) == 1


def test_a_new_idempotency_key_is_a_uuid4() -> None:
    assert UUID4_RE.match(new_idempotency_key())


def test_the_stored_file_is_json_a_human_can_read() -> None:
    saved = save_draft(an_envelope())
    document = json.loads((drafts_dir() / f"{saved.draft_id}.json").read_text("utf-8"))
    assert document["schema"] == "s0ma-feedback-draft@1"
    assert document["draft_id"] == saved.draft_id
    assert document["envelope"]["schema"] == "s0ma-feedback@1"
    assert set(document) == {
        "schema",
        "draft_id",
        "created_ts",
        "idempotency_key",
        "channel",
        "approval_method",
        "contact_ok",
        "envelope",
    }


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def test_listing_purges_drafts_past_thirty_days_and_keeps_the_rest() -> None:
    old = save_draft(an_envelope("old"), created_ts=NOW - (DRAFT_TTL_DAYS + 1) * MS_PER_DAY)
    young = save_draft(an_envelope("young"), created_ts=NOW - MS_PER_DAY)

    live = list_drafts(now_ms=NOW)

    assert [draft.draft_id for draft in live] == [young.draft_id]
    assert not (drafts_dir() / f"{old.draft_id}.json").exists()
    assert (drafts_dir() / f"{young.draft_id}.json").exists()


def test_a_draft_exactly_thirty_days_old_has_expired() -> None:
    draft = FeedbackDraft(
        draft_id="fbd_00000000",
        envelope=an_envelope(),
        idempotency_key=new_idempotency_key(),
        created_ts=NOW - DRAFT_TTL_DAYS * MS_PER_DAY,
    )
    assert draft.is_expired(NOW) is True
    assert draft.is_expired(NOW - 1) is False
    assert draft.expires_ts == NOW


def test_purge_reports_which_drafts_it_removed() -> None:
    stale = save_draft(an_envelope(), created_ts=NOW - 60 * MS_PER_DAY)
    save_draft(an_envelope(), created_ts=NOW)

    assert purge_expired_drafts(now_ms=NOW) == (stale.draft_id,)
    assert purge_expired_drafts(now_ms=NOW) == ()


def test_listing_returns_newest_first() -> None:
    older = save_draft(an_envelope("older"), created_ts=NOW - 5_000)
    newer = save_draft(an_envelope("newer"), created_ts=NOW - 1_000)

    assert [draft.draft_id for draft in list_drafts(now_ms=NOW)] == [
        newer.draft_id,
        older.draft_id,
    ]


def test_listing_an_absent_drafts_directory_is_empty_not_an_error() -> None:
    assert list_drafts() == ()
    assert purge_expired_drafts() == ()


# ---------------------------------------------------------------------------
# Damaged and hostile input
# ---------------------------------------------------------------------------


def test_a_corrupt_draft_is_skipped_and_left_on_disk() -> None:
    good = save_draft(an_envelope())
    broken = drafts_dir() / "fbd_deadbeef.json"
    broken.write_text("{not json", encoding="utf-8")

    assert load_draft("fbd_deadbeef") is None
    assert [draft.draft_id for draft in list_drafts()] == [good.draft_id]
    assert broken.exists(), "a file we cannot read is still the user's data"


@pytest.mark.parametrize(
    "document",
    [
        {"draft_id": "fbd_deadbeef", "idempotency_key": "k", "created_ts": 1},
        {"draft_id": "nope", "idempotency_key": "k", "created_ts": 1, "envelope": {}},
        {"draft_id": "fbd_deadbeef", "created_ts": 1, "envelope": {}},
        {"draft_id": "fbd_deadbeef", "idempotency_key": "k", "envelope": {}},
        {
            "draft_id": "fbd_deadbeef",
            "idempotency_key": "k",
            "created_ts": 1,
            "envelope": {"schema": "s0ma-feedback@1", "license_key": "s0ma_live_x"},
        },
    ],
    ids=["no-envelope", "bad-id", "no-key", "no-ts", "foreign-envelope-key"],
)
def test_a_draft_this_version_cannot_restore_exactly_reads_as_absent(
    document: dict[str, object],
) -> None:
    path = drafts_dir() / "fbd_deadbeef.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    assert load_draft("fbd_deadbeef") is None


@pytest.mark.parametrize(
    "identifier",
    ["../../../etc/passwd", "fbd_deadbeef/../../secret", "", "fbd_DEADBEEF", "installation_id"],
)
def test_a_draft_id_can_never_escape_the_drafts_directory(identifier: str) -> None:
    assert load_draft(identifier) is None
    assert delete_draft(identifier) is False
    with pytest.raises(ValueError, match="not a draft id"):
        save_draft(an_envelope(), draft_id=identifier)


def test_deleting_reports_whether_anything_was_removed() -> None:
    saved = save_draft(an_envelope())
    assert delete_draft(saved.draft_id) is True
    assert delete_draft(saved.draft_id) is False
    assert load_draft(saved.draft_id) is None


# ---------------------------------------------------------------------------
# Receipts log
# ---------------------------------------------------------------------------


def test_receipts_append_and_read_back_oldest_first() -> None:
    first = append_receipt(
        feedback_id="fb_1",
        category="bug",
        summary="first report",
        payload_sha256="sha256:aa",
        ts=NOW,
    )
    second = append_receipt(
        feedback_id="fb_2",
        category="idea",
        summary="second report",
        payload_sha256="sha256:bb",
        ts=NOW + 1,
    )

    entries = read_receipts()

    assert [entry.feedback_id for entry in entries] == ["fb_1", "fb_2"]
    assert entries[0] == first
    assert entries[1] == second
    assert entries[1].category == "idea"


def test_a_receipt_line_keeps_only_sixty_characters_of_the_summary() -> None:
    entry = append_receipt(
        feedback_id="fb_long",
        category="bug",
        summary="s" * 400,
        payload_sha256="sha256:cc",
    )
    assert len(entry.summary60) == SUMMARY_LOG_CHARS
    assert read_receipts()[0].summary60 == "s" * SUMMARY_LOG_CHARS


def test_the_receipts_log_is_one_json_object_per_line() -> None:
    append_receipt(
        feedback_id="fb_1", category="bug", summary="one", payload_sha256="sha256:aa"
    )
    append_receipt(
        feedback_id="fb_2", category="bug", summary="two", payload_sha256="sha256:bb"
    )
    lines = receipts_path().read_text("utf-8").splitlines()
    assert len(lines) == 2
    assert set(json.loads(lines[0])) == {
        "feedback_id",
        "ts",
        "category",
        "summary60",
        "payload_sha256",
    }


def test_a_damaged_line_is_skipped_rather_than_fatal() -> None:
    append_receipt(
        feedback_id="fb_1", category="bug", summary="one", payload_sha256="sha256:aa"
    )
    with receipts_path().open("a", encoding="utf-8") as handle:
        handle.write("{truncated by a crash\n")
    append_receipt(
        feedback_id="fb_2", category="bug", summary="two", payload_sha256="sha256:bb"
    )

    assert [entry.feedback_id for entry in read_receipts()] == ["fb_1", "fb_2"]


def test_reading_an_absent_receipts_log_is_empty_not_an_error() -> None:
    assert read_receipts() == ()


def test_a_receipt_records_the_hash_that_was_confirmed() -> None:
    envelope = an_envelope()
    entry = append_receipt(
        feedback_id="fb_9",
        category=envelope.category,
        summary=envelope.summary,
        payload_sha256=envelope.payload_sha256(),
    )
    assert entry.payload_sha256 == envelope.payload_sha256()
    assert read_receipts()[0].payload_sha256 == envelope.payload_sha256()


# ---------------------------------------------------------------------------
# Where things live, and who may read them
# ---------------------------------------------------------------------------


def test_everything_lives_under_the_state_directory(isolated_home: Path) -> None:
    assert drafts_dir() == isolated_home / ".s0ma" / "feedback-drafts"
    assert receipts_path() == isolated_home / ".s0ma" / "feedback-receipts.jsonl"
    assert state_dir() == isolated_home / ".s0ma"


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes; Windows is best-effort")
def test_drafts_and_receipts_are_owner_only() -> None:
    saved = save_draft(an_envelope())
    append_receipt(
        feedback_id="fb_1", category="bug", summary="one", payload_sha256="sha256:aa"
    )

    draft_mode = stat.S_IMODE((drafts_dir() / f"{saved.draft_id}.json").stat().st_mode)
    directory_mode = stat.S_IMODE(drafts_dir().stat().st_mode)
    receipts_mode = stat.S_IMODE(receipts_path().stat().st_mode)

    assert draft_mode == 0o600
    assert receipts_mode == 0o600
    assert directory_mode == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes; Windows is best-effort")
def test_appending_repairs_the_mode_of_a_pre_existing_log() -> None:
    path = receipts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    os.chmod(path, 0o644)

    append_receipt(
        feedback_id="fb_1", category="bug", summary="one", payload_sha256="sha256:aa"
    )

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
