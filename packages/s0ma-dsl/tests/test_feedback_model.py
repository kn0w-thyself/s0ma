"""FB-M4: the ``s0ma-feedback@1`` envelope — caps, vocabulary, hashing.

The normative cross-language test vector from contract §3.3 is asserted
here **literally**: if this file's expected digest ever needs editing, the
wire format changed and the contract needs a §13 re-freeze, not a new
constant.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from s0ma_dsl.feedback.model import (
    ACTUAL_MAX_CHARS,
    BODY_MAX_BYTES,
    CATEGORIES,
    CHANNELS,
    CONTEXT_MAX_BYTES,
    DETAILS_MAX_CHARS,
    ENVELOPE_FIELDS,
    EXPECTED_MAX_CHARS,
    FEEDBACK_SCHEMA,
    IMPACTS,
    PRIVACY_PROFILE,
    RECEIPT_SCHEMA,
    REPRODUCTION_MAX_STEPS,
    REPRODUCTION_STEP_MAX_CHARS,
    STATUSES,
    SUMMARY_MAX_CHARS,
    FeedbackEnvelope,
    FeedbackPrivacy,
    build_envelope,
    canonical_bytes,
    payload_sha256,
    validate_envelope,
    validate_payload,
)

# ---------------------------------------------------------------------------
# Contract §3.3 — the normative vector, transcribed exactly
# ---------------------------------------------------------------------------

#: Authored key order is deliberately unsorted, as in the contract.
CONTRACT_VECTOR: dict[str, Any] = {
    "schema": "s0ma-feedback@1",
    "category": "friction",
    "impact": "minor",
    "summary": "check named the rule but not the declaration to edit.",
    "expected": "A declaration-level remediation — name the field to edit.",
    "context": {
        "s0ma_version": "0.19.0",
        "os": "macos",
        "python": "3.13",
        "cohort": "beta",
    },
    "privacy": {
        "profile": "metadata_only",
        "includes_source": False,
        "includes_transcript": False,
        "redacted": {"paths": 1},
    },
}

CONTRACT_CANONICAL = (
    '{"category":"friction","context":{"cohort":"beta","os":"macos","python":"3.13",'
    '"s0ma_version":"0.19.0"},"expected":"A declaration-level remediation — name the '
    'field to edit.","impact":"minor","privacy":{"includes_source":false,'
    '"includes_transcript":false,"profile":"metadata_only","redacted":{"paths":1}},'
    '"schema":"s0ma-feedback@1","summary":"check named the rule but not the '
    'declaration to edit."}'
)

CONTRACT_CANONICAL_LENGTH = 400

CONTRACT_SHA256 = "sha256:70265543186546875ad5b349b0ef581023add017b13c161fbac4d43597169d46"

#: The digest a wrong ``ensure_ascii`` produces. Seeing it means bug (3)
#: of contract §3.2, not a content difference.
NEGATIVE_CONTROL_SHA256 = (
    "sha256:72e528051e50ba44a03d3609982215b808ce4371688b0096c1611500dec4d287"
)


def test_contract_vector_canonical_serialization() -> None:
    assert canonical_bytes(CONTRACT_VECTOR).decode("utf-8") == CONTRACT_CANONICAL


def test_contract_vector_byte_length() -> None:
    assert len(canonical_bytes(CONTRACT_VECTOR)) == CONTRACT_CANONICAL_LENGTH


def test_contract_vector_payload_sha256() -> None:
    assert payload_sha256(CONTRACT_VECTOR) == CONTRACT_SHA256


def test_em_dash_is_literal_utf8_never_escaped() -> None:
    raw = canonical_bytes(CONTRACT_VECTOR)
    assert b"\xe2\x80\x94" in raw
    assert b"\\u2014" not in raw


def test_negative_control_ascii_escaping_diverges() -> None:
    """An ``ensure_ascii=True`` implementation must NOT match our digest."""
    import hashlib

    escaped = json.dumps(
        CONTRACT_VECTOR, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    escaped_digest = f"sha256:{hashlib.sha256(escaped).hexdigest()}"
    assert escaped_digest == NEGATIVE_CONTROL_SHA256
    assert escaped_digest != CONTRACT_SHA256
    assert payload_sha256(CONTRACT_VECTOR) != NEGATIVE_CONTROL_SHA256


def test_canonical_serialization_sorts_every_depth_and_omits_whitespace() -> None:
    raw = canonical_bytes(CONTRACT_VECTOR).decode("utf-8")
    assert ", " not in raw
    assert '": ' not in raw
    assert not raw.endswith("\n")
    nested = json.loads(raw)["privacy"]
    assert list(nested) == sorted(nested)


def test_canonical_serialization_preserves_array_order() -> None:
    steps = ["third", "first", "second"]
    raw = canonical_bytes({"schema": FEEDBACK_SCHEMA, "reproduction": steps})
    assert json.loads(raw)["reproduction"] == steps


def test_typed_envelope_reproduces_the_contract_vector() -> None:
    envelope = FeedbackEnvelope(
        category="friction",
        impact="minor",
        summary="check named the rule but not the declaration to edit.",
        expected="A declaration-level remediation — name the field to edit.",
        context={
            "s0ma_version": "0.19.0",
            "os": "macos",
            "python": "3.13",
            "cohort": "beta",
        },
        privacy=FeedbackPrivacy(redacted={"paths": 1}),
    )
    assert envelope.to_payload() == CONTRACT_VECTOR
    assert envelope.payload_sha256() == CONTRACT_SHA256
    assert envelope.canonical_bytes() == canonical_bytes(CONTRACT_VECTOR)
    assert validate_envelope(envelope) == ()


# ---------------------------------------------------------------------------
# Contract §4 — the closed vocabulary
# ---------------------------------------------------------------------------


def test_vocabulary_matches_the_contract_lists() -> None:
    assert CATEGORIES == (
        "bug",
        "friction",
        "idea",
        "documentation",
        "diagnostic_quality",
        "agent_behavior",
        "performance",
        "privacy_or_trust",
        "other",
    )
    assert IMPACTS == ("blocked", "degraded", "minor", "idea")
    assert STATUSES == (
        "received",
        "triaged",
        "needs_information",
        "planned",
        "resolved",
        "closed",
        "duplicate",
        "deleted",
    )
    assert CHANNELS == ("mcp", "cli", "web")


def test_schema_tags_match_the_contract() -> None:
    assert FEEDBACK_SCHEMA == "s0ma-feedback@1"
    assert RECEIPT_SCHEMA == "s0ma-feedback-receipt@1"
    assert PRIVACY_PROFILE == "metadata_only"


def test_envelope_fields_are_the_contract_field_list_in_order() -> None:
    assert ENVELOPE_FIELDS == (
        "schema",
        "category",
        "impact",
        "summary",
        "expected",
        "actual",
        "details",
        "reproduction",
        "context",
        "privacy",
    )


# ---------------------------------------------------------------------------
# Contract §3.1 — caps, table-driven
# ---------------------------------------------------------------------------


def valid_payload(**overrides: Any) -> dict[str, Any]:
    """A minimal report that passes every check, plus *overrides*."""
    payload: dict[str, Any] = {
        "schema": FEEDBACK_SCHEMA,
        "category": "bug",
        "impact": "degraded",
        "summary": "check reported the rule but not the declaration to edit.",
    }
    payload.update(overrides)
    return payload


def codes(payload: dict[str, Any]) -> list[str]:
    return [problem.code for problem in validate_payload(payload)]


def fields(payload: dict[str, Any]) -> list[str | None]:
    return [problem.field for problem in validate_payload(payload)]


#: (label, field, at-cap value, over-cap value)
CAP_CASES: tuple[tuple[str, str, Any, Any], ...] = (
    ("summary", "summary", "s" * SUMMARY_MAX_CHARS, "s" * (SUMMARY_MAX_CHARS + 1)),
    ("expected", "expected", "e" * EXPECTED_MAX_CHARS, "e" * (EXPECTED_MAX_CHARS + 1)),
    ("actual", "actual", "a" * ACTUAL_MAX_CHARS, "a" * (ACTUAL_MAX_CHARS + 1)),
    ("details", "details", "d" * DETAILS_MAX_CHARS, "d" * (DETAILS_MAX_CHARS + 1)),
    (
        "reproduction step count",
        "reproduction",
        ["step"] * REPRODUCTION_MAX_STEPS,
        ["step"] * (REPRODUCTION_MAX_STEPS + 1),
    ),
    (
        "reproduction step length",
        "reproduction",
        ["r" * REPRODUCTION_STEP_MAX_CHARS],
        ["r" * (REPRODUCTION_STEP_MAX_CHARS + 1)],
    ),
)


@pytest.mark.parametrize(("label", "name", "at_cap", "over_cap"), CAP_CASES)
def test_value_at_cap_is_accepted(
    label: str, name: str, at_cap: Any, over_cap: Any
) -> None:
    assert validate_payload(valid_payload(**{name: at_cap})) == (), label


@pytest.mark.parametrize(("label", "name", "at_cap", "over_cap"), CAP_CASES)
def test_value_over_cap_is_refused(
    label: str, name: str, at_cap: Any, over_cap: Any
) -> None:
    problems = validate_payload(valid_payload(**{name: over_cap}))
    assert len(problems) == 1, label
    assert problems[0].code == "SCHEMA_INVALID"
    assert problems[0].field is not None
    assert problems[0].field.startswith(name)


def test_caps_match_the_contract_numbers() -> None:
    assert SUMMARY_MAX_CHARS == 400
    assert EXPECTED_MAX_CHARS == 2000
    assert ACTUAL_MAX_CHARS == 2000
    assert DETAILS_MAX_CHARS == 8000
    assert REPRODUCTION_MAX_STEPS == 10
    assert REPRODUCTION_STEP_MAX_CHARS == 500
    assert CONTEXT_MAX_BYTES == 4096
    assert BODY_MAX_BYTES == 32768


def test_character_caps_count_code_points_not_bytes() -> None:
    """400 three-byte characters is 400 characters, not 1200."""
    assert validate_payload(valid_payload(summary="字" * SUMMARY_MAX_CHARS)) == ()
    problems = validate_payload(valid_payload(summary="字" * (SUMMARY_MAX_CHARS + 1)))
    assert [problem.code for problem in problems] == ["SCHEMA_INVALID"]


def test_body_cap_is_measured_in_utf8_bytes() -> None:
    """Every field within its character cap can still overrun 32 KB."""
    payload = valid_payload(
        details="字" * DETAILS_MAX_CHARS,
        expected="字" * EXPECTED_MAX_CHARS,
        actual="字" * ACTUAL_MAX_CHARS,
    )
    assert len(canonical_bytes(payload)) > BODY_MAX_BYTES
    problems = validate_payload(payload)
    assert [problem.code for problem in problems] == ["PAYLOAD_TOO_LARGE"]
    assert problems[0].field is None


def test_ascii_report_at_every_text_cap_stays_under_the_body_cap() -> None:
    payload = valid_payload(
        summary="s" * SUMMARY_MAX_CHARS,
        expected="e" * EXPECTED_MAX_CHARS,
        actual="a" * ACTUAL_MAX_CHARS,
        details="d" * DETAILS_MAX_CHARS,
        reproduction=["r" * REPRODUCTION_STEP_MAX_CHARS] * REPRODUCTION_MAX_STEPS,
    )
    assert len(canonical_bytes(payload)) <= BODY_MAX_BYTES
    assert validate_payload(payload) == ()


def test_context_over_four_kilobytes_is_refused() -> None:
    codes_list = [f"DIAGNOSTIC_CODE_NUMBER_{index:04d}" for index in range(200)]
    payload = valid_payload(context={"diagnostic_codes": codes_list})
    assert len(canonical_bytes(payload["context"])) > CONTEXT_MAX_BYTES
    problems = validate_payload(payload)
    assert [problem.code for problem in problems] == ["SCHEMA_INVALID"]
    assert problems[0].field == "context"


# ---------------------------------------------------------------------------
# Contract §3.1 — schema tag, vocabulary, unknown fields
# ---------------------------------------------------------------------------


def test_missing_summary_is_refused() -> None:
    payload = valid_payload()
    del payload["summary"]
    assert fields(payload) == ["summary"]


def test_blank_summary_is_refused() -> None:
    assert fields(valid_payload(summary="   ")) == ["summary"]


def test_wrong_schema_tag_is_refused() -> None:
    assert fields(valid_payload(schema="s0ma-feedback@2")) == ["schema"]


def test_unknown_top_level_key_is_refused_not_ignored() -> None:
    problems = validate_payload(valid_payload(transcript="everything the user said"))
    assert [problem.field for problem in problems] == ["transcript"]
    assert problems[0].code == "SCHEMA_INVALID"


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_contract_category_is_accepted(category: str) -> None:
    assert validate_payload(valid_payload(category=category)) == ()


@pytest.mark.parametrize("impact", IMPACTS)
def test_every_contract_impact_is_accepted(impact: str) -> None:
    assert validate_payload(valid_payload(impact=impact)) == ()


def test_unknown_category_and_impact_are_refused() -> None:
    assert fields(valid_payload(category="feature_request")) == ["category"]
    assert fields(valid_payload(impact="critical")) == ["impact"]


def test_non_text_fields_are_refused() -> None:
    assert fields(valid_payload(summary=42)) == ["summary"]
    assert fields(valid_payload(reproduction="one long string")) == ["reproduction"]
    assert fields(valid_payload(reproduction=[1])) == ["reproduction[0]"]


# ---------------------------------------------------------------------------
# Contract §5 — the context allow-list, schema half
# ---------------------------------------------------------------------------


def test_non_allow_listed_context_key_is_refused() -> None:
    payload = valid_payload(context={"os": "macos", "git_remote": "git@example:me/x"})
    problems = validate_payload(payload)
    assert [problem.field for problem in problems] == ["context.git_remote"]
    assert problems[0].code == "SCHEMA_INVALID"


def test_non_allow_listed_client_and_surface_keys_are_refused() -> None:
    payload = valid_payload(
        context={
            "client": {"name": "claude-code", "version": "1.0", "account": "me@x.com"},
            "surface": {"kind": "tool", "name": "check", "argv": "--secret"},
        }
    )
    assert fields(payload) == ["context.client.account", "context.surface.argv"]


def test_allow_listed_context_passes() -> None:
    payload = valid_payload(
        context={
            "s0ma_version": "0.19.0",
            "s0ma_core": "0.19.0",
            "s0ma_dsl": "0.19.0",
            "s0ma_mcp": None,
            "s0ma_studi0": None,
            "client": {"name": "claude-code", "version": "1.2.3"},
            "mcp_protocol_version": "2025-06-18",
            "python": "3.13",
            "os": "linux",
            "architecture": "x86_64",
            "surface": {"kind": "tool", "name": "check"},
            "diagnostic_codes": ["PROVIDES_KEY_MISMATCH"],
            "outcome": "failure",
            "duration_bucket": "1-5s",
            "cohort": "beta",
            "pseudonym": "0" * 32,
        }
    )
    assert validate_payload(payload) == ()


# ---------------------------------------------------------------------------
# Contract §3.1/§5 — the privacy block
# ---------------------------------------------------------------------------


def test_privacy_block_round_trips() -> None:
    privacy = FeedbackPrivacy(redacted={"paths": 2, "emails": 1})
    assert privacy.to_dict() == {
        "profile": "metadata_only",
        "includes_source": False,
        "includes_transcript": False,
        "redacted": {"emails": 1, "paths": 2},
    }


def test_source_or_transcript_inclusion_is_refused() -> None:
    payload = valid_payload(privacy={
        "profile": PRIVACY_PROFILE,
        "includes_source": True,
        "includes_transcript": True,
        "redacted": {},
    })
    assert fields(payload) == ["privacy.includes_source", "privacy.includes_transcript"]


def test_unknown_privacy_profile_and_field_are_refused() -> None:
    payload = valid_payload(privacy={
        "profile": "everything",
        "includes_source": False,
        "includes_transcript": False,
        "redacted": {},
        "attachments": ["trace.log"],
    })
    assert fields(payload) == ["privacy.attachments", "privacy.profile"]


def test_redaction_counts_must_be_counts() -> None:
    payload = valid_payload(privacy={
        "profile": PRIVACY_PROFILE,
        "includes_source": False,
        "includes_transcript": False,
        "redacted": {"paths": "two", "emails": -1},
    })
    assert fields(payload) == ["privacy.redacted.emails", "privacy.redacted.paths"]


# ---------------------------------------------------------------------------
# build_envelope — the CLI-facing boundary
# ---------------------------------------------------------------------------


def test_build_envelope_returns_a_structured_result_not_an_exception() -> None:
    result = build_envelope(category="nonsense", impact="minor", summary="hi")
    assert result.ok is False
    assert result.envelope is None
    assert [problem.field for problem in result.problems] == ["category"]
    assert result.to_dict()["ok"] is False
    assert result.to_dict()["problems"][0]["field"] == "category"
    assert result.problems[0].to_dict()["code"] == "SCHEMA_INVALID"


def test_build_envelope_trims_and_drops_blank_optional_fields() -> None:
    result = build_envelope(
        category="friction",
        impact="minor",
        summary="  the check was unclear  ",
        expected="   ",
        actual="",
        details=None,
        reproduction=["  run s0ma check  ", "   ", ""],
    )
    assert result.ok is True
    assert result.envelope is not None
    payload = result.envelope.to_payload()
    assert payload["summary"] == "the check was unclear"
    assert "expected" not in payload
    assert "actual" not in payload
    assert "details" not in payload
    assert payload["reproduction"] == ["run s0ma check"]


def test_build_envelope_reports_every_problem_at_once() -> None:
    result = build_envelope(
        category="nonsense",
        impact="critical",
        summary="s" * (SUMMARY_MAX_CHARS + 1),
    )
    assert [problem.field for problem in result.problems] == [
        "category",
        "impact",
        "summary",
    ]


def test_build_envelope_keeps_a_non_text_step_so_it_can_be_named() -> None:
    result = build_envelope(
        category="bug",
        impact="minor",
        summary="steps went wrong",
        reproduction=[1],  # type: ignore[list-item]
    )
    assert [problem.field for problem in result.problems] == ["reproduction[0]"]


def test_successful_build_carries_the_envelope_and_hashes_it() -> None:
    result = build_envelope(
        category="documentation",
        impact="minor",
        summary="the guide skipped a step",
        context={"os": "linux", "cohort": "beta"},
        privacy=FeedbackPrivacy(),
    )
    assert result.ok is True
    assert result.envelope is not None
    assert result.envelope.payload_sha256().startswith("sha256:")
    assert len(result.envelope.payload_sha256()) == len("sha256:") + 64
    assert result.to_dict() == {"ok": True, "problems": []}


# ---------------------------------------------------------------------------
# Contract §12 — voice
# ---------------------------------------------------------------------------

VOICE_CASES: tuple[dict[str, Any], ...] = (
    valid_payload(transcript="…"),
    valid_payload(schema="s0ma-feedback@2"),
    valid_payload(category="nope"),
    valid_payload(impact="nope"),
    valid_payload(summary="s" * (SUMMARY_MAX_CHARS + 1)),
    valid_payload(summary=""),
    valid_payload(details="d" * (DETAILS_MAX_CHARS + 1)),
    valid_payload(reproduction=["r" * (REPRODUCTION_STEP_MAX_CHARS + 1)]),
    valid_payload(reproduction=["s"] * (REPRODUCTION_MAX_STEPS + 1)),
    valid_payload(context={"git_remote": "x"}),
    valid_payload(context={"client": {"secret": "x"}}),
    valid_payload(privacy={"profile": "everything"}),
    valid_payload(
        details="字" * DETAILS_MAX_CHARS,
        expected="字" * EXPECTED_MAX_CHARS,
        actual="字" * ACTUAL_MAX_CHARS,
    ),
)


@pytest.mark.parametrize("payload", VOICE_CASES)
def test_user_facing_copy_never_says_payload(payload: dict[str, Any]) -> None:
    """§12/A-2: user-facing text says "feedback report"/"feedback data".

    Technical identifiers are exempt, so the ``PAYLOAD_TOO_LARGE`` *code*
    is not checked — only the copy a reader is shown.
    """
    problems = validate_payload(payload)
    assert problems
    for problem in problems:
        assert "payload" not in problem.message.lower()
        assert "payload" not in problem.remediation.lower()


@pytest.mark.parametrize("payload", VOICE_CASES)
def test_every_problem_carries_an_actionable_remediation(payload: dict[str, Any]) -> None:
    for problem in validate_payload(payload):
        assert problem.remediation.strip()
        assert problem.message.strip()
        assert problem.code in {"SCHEMA_INVALID", "PAYLOAD_TOO_LARGE"}


def test_refusal_message_never_echoes_a_long_value() -> None:
    """A refused value is described, not dumped back at the reader."""
    secret = "x" * 5000
    problems = validate_payload(valid_payload(summary=42, expected=secret))
    assert problems
    for problem in problems:
        assert secret not in problem.message
        assert len(problem.message) < 400
