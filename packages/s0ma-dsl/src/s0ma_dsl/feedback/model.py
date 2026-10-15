"""The ``s0ma-feedback@1`` envelope: vocabulary, caps, hashing, validation.

This module is the client-side authority for the frozen feedback contract
(``docs/contracts/feedback-v1.md`` §3–§5). It holds four things:

* the closed §4 vocabulary and the §3.1 field caps;
* the §5 context allow-list (the schema half of its double enforcement —
  the collector half lives in :mod:`s0ma_dsl.feedback.context`);
* the §3.2 canonical serialization and :func:`payload_sha256`, which must
  stay byte-identical to the control-plane helper. The §3.3 vector is
  asserted literally in ``tests/test_feedback_model.py``;
* a pre-flight validator mirroring the server's checks, so a report is
  refused on this machine, with an actionable message, before anything is
  sent.

Everything here is pure: no clock, no filesystem, no network. Validation
returns structured results (:class:`FeedbackValidation`) rather than
raising, because its problems are user-facing copy at the CLI and MCP
boundaries, not transpiler bugs.

Voice (contract §12): every ``message``/``remediation`` string is written
for an intelligent non-programmer and says "feedback report" or "feedback
data" — never "payload". The identifier ``payload_sha256`` is a schema
field name and is explicitly exempt.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ACTUAL_MAX_CHARS",
    "BODY_MAX_BYTES",
    "CATEGORIES",
    "CHANNELS",
    "CLIENT_KEYS",
    "CONTEXT_ALLOWED_KEYS",
    "CONTEXT_MAX_BYTES",
    "DETAILS_MAX_CHARS",
    "ENVELOPE_FIELDS",
    "EXPECTED_MAX_CHARS",
    "FEEDBACK_SCHEMA",
    "IMPACTS",
    "PRIVACY_KEYS",
    "PRIVACY_PROFILE",
    "RECEIPT_SCHEMA",
    "REPRODUCTION_MAX_STEPS",
    "REPRODUCTION_STEP_MAX_CHARS",
    "STATUSES",
    "SUMMARY_MAX_CHARS",
    "SURFACE_KEYS",
    "FeedbackEnvelope",
    "FeedbackPrivacy",
    "FeedbackProblem",
    "FeedbackValidation",
    "build_envelope",
    "canonical_bytes",
    "payload_sha256",
    "validate_envelope",
    "validate_payload",
]

# ---------------------------------------------------------------------------
# Schema tags (contract §3.1, §3.4)
# ---------------------------------------------------------------------------

#: The one envelope schema this version writes and validates.
FEEDBACK_SCHEMA = "s0ma-feedback@1"

#: The receipt schema the control plane returns (consumed at FB-M6).
RECEIPT_SCHEMA = "s0ma-feedback-receipt@1"

#: The only privacy profile v1 defines (contract §3.1).
PRIVACY_PROFILE = "metadata_only"

# ---------------------------------------------------------------------------
# Vocabulary (contract §4 — closed lists; adding a member is a re-freeze)
# ---------------------------------------------------------------------------

CATEGORIES: tuple[str, ...] = (
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

IMPACTS: tuple[str, ...] = ("blocked", "degraded", "minor", "idea")

STATUSES: tuple[str, ...] = (
    "received",
    "triaged",
    "needs_information",
    "planned",
    "resolved",
    "closed",
    "duplicate",
    "deleted",
)

CHANNELS: tuple[str, ...] = ("mcp", "cli", "web")

# ---------------------------------------------------------------------------
# Field caps (contract §3.1). Character caps count Unicode code points,
# which is exactly what ``len()`` counts for a Python ``str``. Byte caps are
# measured on canonical UTF-8 bytes.
# ---------------------------------------------------------------------------

SUMMARY_MAX_CHARS = 400
EXPECTED_MAX_CHARS = 2000
ACTUAL_MAX_CHARS = 2000
DETAILS_MAX_CHARS = 8000
REPRODUCTION_MAX_STEPS = 10
REPRODUCTION_STEP_MAX_CHARS = 500
CONTEXT_MAX_BYTES = 4096
BODY_MAX_BYTES = 32768

#: Top-level envelope fields in contract §3.1 order. An unknown top-level
#: key is a validation failure, never an ignored field.
ENVELOPE_FIELDS: tuple[str, ...] = (
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

_ENVELOPE_FIELD_SET = frozenset(ENVELOPE_FIELDS)

# ---------------------------------------------------------------------------
# Context allow-list (contract §5) — nothing else may enter ``context``.
#
# Enforced twice on this side: the collector in ``context.py`` can only
# produce these keys, and :func:`validate_payload` refuses any other key
# with the same code the server returns. Excluded by construction and not
# addable without a PRD amendment: source, file contents, prompts,
# transcripts, raw output, stack traces, git remotes, repository or
# organization names, account email, license keys, hardware identifiers.
# ---------------------------------------------------------------------------

CONTEXT_ALLOWED_KEYS: frozenset[str] = frozenset({
    "s0ma_version",
    "s0ma_core",
    "s0ma_dsl",
    "s0ma_mcp",
    "s0ma_studi0",
    "client",
    "mcp_protocol_version",
    "python",
    "os",
    "architecture",
    "surface",
    "diagnostic_codes",
    "outcome",
    "duration_bucket",
    "cohort",
    "pseudonym",
})

#: Inner keys the two allow-listed sub-objects may carry (contract §5).
CLIENT_KEYS: frozenset[str] = frozenset({"name", "version"})
SURFACE_KEYS: frozenset[str] = frozenset({"kind", "name"})

#: Fields the ``privacy`` block carries (contract §3.1).
PRIVACY_KEYS: frozenset[str] = frozenset({
    "profile",
    "includes_source",
    "includes_transcript",
    "redacted",
})

# Problem codes mirror the server's D-5 matrix (contract §2.1), so a local
# pre-flight failure predicts the exact response the server would give.
_SCHEMA_INVALID = "SCHEMA_INVALID"
_TOO_LARGE = "PAYLOAD_TOO_LARGE"


# ---------------------------------------------------------------------------
# Canonical serialization and hashing (contract §3.2)
# ---------------------------------------------------------------------------


def canonical_bytes(envelope: Mapping[str, Any]) -> bytes:
    """Serialize *envelope* to its canonical UTF-8 bytes.

    Keys sorted at every depth, separators ``,`` and ``:`` with no
    whitespace, non-ASCII emitted literally (``ensure_ascii=False``), array
    order preserved, no trailing newline. Byte-identical to the
    control-plane TypeScript helper; the §3.3 vector proves it.
    """
    return json.dumps(
        dict(envelope), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def payload_sha256(envelope: Mapping[str, Any]) -> str:
    """Return ``"sha256:" + hex`` over :func:`canonical_bytes` of *envelope*.

    The hash covers the envelope alone: transport headers, the
    ``approval_method`` request field, and every server-derived fact sit
    outside it (contract §3.2 note 6).
    """
    return f"sha256:{hashlib.sha256(canonical_bytes(envelope)).hexdigest()}"


# ---------------------------------------------------------------------------
# Structured results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackProblem:
    """One reason a feedback report cannot be sent as written.

    Carries the server's own code, so a local pre-flight refusal and a
    server refusal read identically, plus copy the CLI or an agent can
    show verbatim.
    """

    code: str
    """``SCHEMA_INVALID`` or ``PAYLOAD_TOO_LARGE`` (contract §2.1)."""

    message: str
    """What is wrong, in the reader's language."""

    remediation: str
    """The specific edit that fixes it."""

    field: str | None = None
    """Envelope field at fault; ``None`` when the whole report is."""

    def to_dict(self) -> dict[str, str]:
        """Serialize to a JSON-compatible dictionary."""
        item: dict[str, str] = {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
        }
        if self.field is not None:
            item["field"] = self.field
        return item


@dataclass(frozen=True)
class FeedbackValidation:
    """The outcome of building or checking a feedback report.

    ``ok`` and ``envelope`` move together: a validation reporting no
    problems always carries the envelope, and one reporting problems never
    does.
    """

    problems: tuple[FeedbackProblem, ...] = ()
    envelope: FeedbackEnvelope | None = None

    @property
    def ok(self) -> bool:
        """Whether the report passed every client-side check."""
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "ok": self.ok,
            "problems": [problem.to_dict() for problem in self.problems],
        }


# ---------------------------------------------------------------------------
# Typed envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackPrivacy:
    """The ``privacy`` block: what this report does and does not carry.

    ``includes_source`` and ``includes_transcript`` are ``False`` in v1 and
    validation keeps them there — source and transcripts are excluded by
    construction (contract §5), not by a runtime choice.
    """

    profile: str = PRIVACY_PROFILE
    includes_source: bool = False
    includes_transcript: bool = False
    redacted: dict[str, int] = field(default_factory=dict)
    """Per-type counts from the FB-M5 redactor, e.g. ``{"paths": 2}``."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "profile": self.profile,
            "includes_source": self.includes_source,
            "includes_transcript": self.includes_transcript,
            "redacted": dict(sorted(self.redacted.items())),
        }


@dataclass(frozen=True)
class FeedbackEnvelope:
    """One ``s0ma-feedback@1`` report, ready to hash and send.

    Build it through :func:`build_envelope`, which validates every cap
    before handing one back. Constructing the dataclass directly is allowed
    (tests do) but skips validation.
    """

    category: str
    impact: str
    summary: str
    expected: str | None = None
    actual: str | None = None
    details: str | None = None
    reproduction: tuple[str, ...] = ()
    context: dict[str, Any] | None = None
    privacy: FeedbackPrivacy | None = None
    schema: str = FEEDBACK_SCHEMA

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON object form, omitting absent optional fields."""
        payload: dict[str, Any] = {
            "schema": self.schema,
            "category": self.category,
            "impact": self.impact,
            "summary": self.summary,
        }
        for name, value in (
            ("expected", self.expected),
            ("actual", self.actual),
            ("details", self.details),
        ):
            if value is not None:
                payload[name] = value
        if self.reproduction:
            payload["reproduction"] = list(self.reproduction)
        if self.context is not None:
            payload["context"] = dict(self.context)
        if self.privacy is not None:
            payload["privacy"] = self.privacy.to_dict()
        return payload

    def canonical_bytes(self) -> bytes:
        """Canonical UTF-8 bytes of this report (contract §3.2)."""
        return canonical_bytes(self.to_payload())

    def payload_sha256(self) -> str:
        """``"sha256:" + hex`` over this report's canonical bytes."""
        return payload_sha256(self.to_payload())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _problem(
    code: str,
    message: str,
    remediation: str,
    name: str | None = None,
) -> FeedbackProblem:
    return FeedbackProblem(code=code, message=message, remediation=remediation, field=name)


def _describe(value: Any) -> str:
    """Describe a refused value without quoting a wall of its content."""
    if isinstance(value, str):
        return f"`{value}`" if len(value) <= 40 else f"`{value[:40]}...`"
    if value is None:
        return "nothing"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, Mapping):
        return "a set of labelled values"
    if isinstance(value, Sequence):
        return "a list"
    return "an unsupported value"


def _check_unknown_fields(payload: Mapping[str, Any], problems: list[FeedbackProblem]) -> None:
    for name in sorted(set(payload) - _ENVELOPE_FIELD_SET):
        problems.append(_problem(
            _SCHEMA_INVALID,
            f"A feedback report has no `{name}` field, so this report cannot be sent.",
            f"Remove it. A feedback report carries only: {', '.join(ENVELOPE_FIELDS)}.",
            name,
        ))


def _check_schema_tag(payload: Mapping[str, Any], problems: list[FeedbackProblem]) -> None:
    tag = payload.get("schema")
    if tag == FEEDBACK_SCHEMA:
        return
    problems.append(_problem(
        _SCHEMA_INVALID,
        f"This feedback report is labelled {_describe(tag)}; this version of s0ma "
        f"writes `{FEEDBACK_SCHEMA}`.",
        f"Rebuild the report with this version of s0ma so it is labelled "
        f"`{FEEDBACK_SCHEMA}`.",
        "schema",
    ))


def _check_choice(
    payload: Mapping[str, Any],
    name: str,
    allowed: tuple[str, ...],
    label: str,
    problems: list[FeedbackProblem],
) -> None:
    value = payload.get(name)
    if value in allowed:
        return
    if name not in payload:
        problems.append(_problem(
            _SCHEMA_INVALID,
            f"Every feedback report needs {label}.",
            f"Set `{name}` to one of: {', '.join(allowed)}.",
            name,
        ))
        return
    problems.append(_problem(
        _SCHEMA_INVALID,
        f"{_describe(value)} is not {label} s0ma recognises.",
        f"Set `{name}` to one of: {', '.join(allowed)}.",
        name,
    ))


def _check_text(
    payload: Mapping[str, Any],
    name: str,
    cap: int,
    *,
    required: bool,
    problems: list[FeedbackProblem],
) -> None:
    if name not in payload:
        if required:
            problems.append(_problem(
                _SCHEMA_INVALID,
                "Every feedback report needs a one-line summary of what happened.",
                f"Add a `{name}` of 1 to {cap} characters.",
                name,
            ))
        return
    value = payload[name]
    if not isinstance(value, str):
        problems.append(_problem(
            _SCHEMA_INVALID,
            f"The `{name}` field must be text; this report has {_describe(value)}.",
            f"Write `{name}` as a single piece of text.",
            name,
        ))
        return
    if required and not value.strip():
        problems.append(_problem(
            _SCHEMA_INVALID,
            "The summary is empty, so nobody could tell what this report is about.",
            f"Write a `{name}` of 1 to {cap} characters.",
            name,
        ))
        return
    if len(value) > cap:
        problems.append(_problem(
            _SCHEMA_INVALID,
            f"The `{name}` field is {len(value)} characters; a feedback report "
            f"allows {cap}.",
            f"Shorten `{name}` to {cap} characters or fewer and send it again.",
            name,
        ))


def _check_reproduction(payload: Mapping[str, Any], problems: list[FeedbackProblem]) -> None:
    if "reproduction" not in payload:
        return
    steps = payload["reproduction"]
    if isinstance(steps, str) or not isinstance(steps, Sequence):
        problems.append(_problem(
            _SCHEMA_INVALID,
            "The reproduction steps must be a list of separate steps.",
            "Write each step as its own entry in a list.",
            "reproduction",
        ))
        return
    if len(steps) > REPRODUCTION_MAX_STEPS:
        problems.append(_problem(
            _SCHEMA_INVALID,
            f"This report has {len(steps)} reproduction steps; a feedback report "
            f"allows {REPRODUCTION_MAX_STEPS}.",
            f"Merge or drop steps until {REPRODUCTION_MAX_STEPS} remain.",
            "reproduction",
        ))
    for index, step in enumerate(steps):
        name = f"reproduction[{index}]"
        if not isinstance(step, str):
            problems.append(_problem(
                _SCHEMA_INVALID,
                f"Reproduction step {index + 1} must be text; it is {_describe(step)}.",
                "Write the step as a single piece of text.",
                name,
            ))
            continue
        if len(step) > REPRODUCTION_STEP_MAX_CHARS:
            problems.append(_problem(
                _SCHEMA_INVALID,
                f"Reproduction step {index + 1} is {len(step)} characters; a step "
                f"allows {REPRODUCTION_STEP_MAX_CHARS}.",
                f"Shorten step {index + 1} to {REPRODUCTION_STEP_MAX_CHARS} "
                "characters or fewer.",
                name,
            ))


def _check_sub_object(
    context: Mapping[str, Any],
    name: str,
    allowed: frozenset[str],
    problems: list[FeedbackProblem],
) -> None:
    if name not in context:
        return
    value = context[name]
    field_name = f"context.{name}"
    if not isinstance(value, Mapping):
        problems.append(_problem(
            _SCHEMA_INVALID,
            f"The `{name}` detail must be a small set of labelled values.",
            f"Let s0ma build the context — it fills `{name}` with only "
            f"{' and '.join(sorted(allowed))}.",
            field_name,
        ))
        return
    for key in sorted(set(value) - allowed):
        problems.append(_problem(
            _SCHEMA_INVALID,
            f"Feedback data may not carry `{name}.{key}`.",
            "Let s0ma build the context. It records only the details the "
            "privacy contract allows.",
            f"{field_name}.{key}",
        ))


def _check_context(payload: Mapping[str, Any], problems: list[FeedbackProblem]) -> None:
    if "context" not in payload:
        return
    context = payload["context"]
    if not isinstance(context, Mapping):
        problems.append(_problem(
            _SCHEMA_INVALID,
            "The context must be a set of labelled values.",
            "Let s0ma build the context rather than supplying one by hand.",
            "context",
        ))
        return
    for key in sorted(set(context) - CONTEXT_ALLOWED_KEYS):
        problems.append(_problem(
            _SCHEMA_INVALID,
            f"Feedback data may not carry `{key}`.",
            "Let s0ma build the context. It records only the details the privacy "
            f"contract allows: {', '.join(sorted(CONTEXT_ALLOWED_KEYS))}.",
            f"context.{key}",
        ))
    _check_sub_object(context, "client", CLIENT_KEYS, problems)
    _check_sub_object(context, "surface", SURFACE_KEYS, problems)
    size = _measure(context, problems, "context")
    if size is not None and size > CONTEXT_MAX_BYTES:
        problems.append(_problem(
            _SCHEMA_INVALID,
            f"The context is {size} bytes; a feedback report allows "
            f"{CONTEXT_MAX_BYTES} bytes.",
            "Drop some of the recorded details — the diagnostic codes are usually "
            "the longest part.",
            "context",
        ))


def _check_privacy(payload: Mapping[str, Any], problems: list[FeedbackProblem]) -> None:
    if "privacy" not in payload:
        return
    privacy = payload["privacy"]
    if not isinstance(privacy, Mapping):
        problems.append(_problem(
            _SCHEMA_INVALID,
            "The privacy block must be a set of labelled values.",
            "Let s0ma build the privacy block from the redaction it ran.",
            "privacy",
        ))
        return
    for key in sorted(set(privacy) - PRIVACY_KEYS):
        problems.append(_problem(
            _SCHEMA_INVALID,
            f"The privacy block has no `{key}` field.",
            f"The privacy block carries only: {', '.join(sorted(PRIVACY_KEYS))}.",
            f"privacy.{key}",
        ))
    profile = privacy.get("profile")
    if profile != PRIVACY_PROFILE:
        problems.append(_problem(
            _SCHEMA_INVALID,
            "This version of s0ma sends metadata only, so the privacy profile must "
            f"be `{PRIVACY_PROFILE}`; this report says {_describe(profile)}.",
            f"Set the privacy profile to `{PRIVACY_PROFILE}`.",
            "privacy.profile",
        ))
    for key, what in (
        ("includes_source", "your source code"),
        ("includes_transcript", "your conversation"),
    ):
        if privacy.get(key, False) is not False:
            problems.append(_problem(
                _SCHEMA_INVALID,
                f"A feedback report never carries {what}, so `{key}` must stay off.",
                f"Set `{key}` to false, or let s0ma build the privacy block.",
                f"privacy.{key}",
            ))
    _check_redacted(privacy, problems)


def _check_redacted(privacy: Mapping[str, Any], problems: list[FeedbackProblem]) -> None:
    redacted = privacy.get("redacted", {})
    if not isinstance(redacted, Mapping):
        problems.append(_problem(
            _SCHEMA_INVALID,
            "The redaction summary must be one count per kind of removed detail.",
            "Let s0ma build the privacy block from the redaction it ran.",
            "privacy.redacted",
        ))
        return
    for key in sorted(redacted):
        count = redacted[key]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            problems.append(_problem(
                _SCHEMA_INVALID,
                f"The redaction summary for `{key}` must be a count, not "
                f"{_describe(count)}.",
                "Let s0ma build the privacy block from the redaction it ran.",
                f"privacy.redacted.{key}",
            ))


def _measure(
    value: Mapping[str, Any], problems: list[FeedbackProblem], name: str
) -> int | None:
    """Canonical byte length of *value*, or ``None`` when it cannot serialize."""
    try:
        return len(canonical_bytes(value))
    except (TypeError, ValueError):
        problems.append(_problem(
            _SCHEMA_INVALID,
            f"Part of this feedback report ({name}) cannot be written as feedback data.",
            "Let s0ma build the report rather than assembling one by hand.",
            name,
        ))
        return None


def _check_total_size(payload: Mapping[str, Any], problems: list[FeedbackProblem]) -> None:
    size = _measure(payload, problems, "the report")
    if size is None or size <= BODY_MAX_BYTES:
        return
    problems.append(_problem(
        _TOO_LARGE,
        f"This feedback report is {size} bytes; the limit is {BODY_MAX_BYTES} bytes "
        "(32 KB).",
        "Shorten the details or the reproduction steps and send it again.",
    ))


def validate_payload(payload: Mapping[str, Any]) -> tuple[FeedbackProblem, ...]:
    """Check a raw feedback report against every contract §3.1 rule.

    Returns every problem found, in contract field order, so a caller can
    show one complete list instead of one problem per attempt. An empty
    tuple means this machine believes the server will accept the report.
    """
    problems: list[FeedbackProblem] = []
    _check_unknown_fields(payload, problems)
    _check_schema_tag(payload, problems)
    _check_choice(payload, "category", CATEGORIES, "a feedback category", problems)
    _check_choice(payload, "impact", IMPACTS, "an impact level", problems)
    _check_text(payload, "summary", SUMMARY_MAX_CHARS, required=True, problems=problems)
    _check_text(payload, "expected", EXPECTED_MAX_CHARS, required=False, problems=problems)
    _check_text(payload, "actual", ACTUAL_MAX_CHARS, required=False, problems=problems)
    _check_text(payload, "details", DETAILS_MAX_CHARS, required=False, problems=problems)
    _check_reproduction(payload, problems)
    _check_context(payload, problems)
    _check_privacy(payload, problems)
    _check_total_size(payload, problems)
    return tuple(problems)


def validate_envelope(envelope: FeedbackEnvelope) -> tuple[FeedbackProblem, ...]:
    """Check an already-typed envelope. Same rules as :func:`validate_payload`."""
    return validate_payload(envelope.to_payload())


def _clean(value: str | None) -> str | None:
    """Trim surrounding whitespace; blank text is an absent field."""
    if not isinstance(value, str):
        return value
    trimmed = value.strip()
    return trimmed or None


def build_envelope(
    *,
    category: str,
    impact: str,
    summary: str,
    expected: str | None = None,
    actual: str | None = None,
    details: str | None = None,
    reproduction: Sequence[str] | None = None,
    context: Mapping[str, Any] | None = None,
    privacy: FeedbackPrivacy | None = None,
) -> FeedbackValidation:
    """Build and validate one feedback report.

    Surrounding whitespace is trimmed and blank optional fields are dropped,
    so a half-filled interactive compose never ships empty strings. Every
    cap is then checked exactly as :func:`validate_payload` checks a report
    that arrives as a plain object.

    Returns a :class:`FeedbackValidation`: on success ``ok`` is true and
    ``envelope`` holds the report; on failure ``problems`` holds copy the
    caller can show as it stands.
    """
    steps: list[Any] = []
    for step in reproduction or ():
        if not isinstance(step, str):
            # Kept, not dropped, so validation names the offending step.
            steps.append(step)
        elif step.strip():
            steps.append(step.strip())
    envelope = FeedbackEnvelope(
        category=category,
        impact=impact,
        summary=summary.strip() if isinstance(summary, str) else summary,
        expected=_clean(expected),
        actual=_clean(actual),
        details=_clean(details),
        reproduction=tuple(steps),
        context=dict(context) if context is not None else None,
        privacy=privacy,
    )
    problems = validate_envelope(envelope)
    if problems:
        return FeedbackValidation(problems=problems)
    return FeedbackValidation(envelope=envelope)
