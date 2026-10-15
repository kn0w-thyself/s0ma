"""``s0ma feedback`` — write, approve, send, and manage feedback reports (FB-M7).

The user-facing half of the feedback engine in :mod:`s0ma_dsl.feedback`. The
engine composes, redacts, hashes, drafts, and transports; this module is the
conversation that happens in a terminal around it:

``s0ma feedback -m "..."``
    The fast path (follow-up F-1). One line is a whole report: no field
    question is asked at all. The report is shown back as a card, the
    reader answers the contact question (FD-2) and then the one
    confirmation that matters — ``Send exactly this feedback data?
    [y/N]`` — and it is sent. Two answers, both of them consequential.
    ``-c``/``-i`` say which kind of feedback it is and how much it is
    affecting the reader; unsaid, a report is ``other`` and ``minor``.
``s0ma feedback``
    Interactive compose. One line, then two menus that take a bare Enter
    for their default, then one gate question that offers the longer half
    of the form rather than assuming it. Then the same card, the same two
    questions. Nothing leaves the machine before that answer is ``y``.

``s0ma feedback drafts`` / ``submit <draft-id>``
    Unsent reports, and the resume path. A draft is written **before** the
    submission is attempted, so a network failure always leaves something to
    retry — with the draft's original idempotency key, which is what makes
    the retry safe rather than a second report.
``s0ma feedback list`` / ``delete``
    The A-3 multi-report surface. Listing is server-backed and falls back to
    this machine's receipts log when the service cannot be reached. Bare
    ``delete`` deletes nothing on purpose; ``delete <id>`` deletes exactly
    one; ``delete --all`` is the only bulk path and asks first.
``s0ma feedback enroll``
    The one-time license-key → feedback-token exchange (FD-4).

The card (:func:`render_card`) is the trust surface. It renders the report
field by field, in plain words, walking the very object that is about to be
hashed and sent — so every field that travels is read first, and a field
this module has never heard of still appears rather than hiding inside a
shape it does not recognise. It ends with the fingerprint the receipt is
checked against. F-1 replaced a raw dump of the report data with it: the
same completeness, in a form a reader can actually check.

Two rules shape every string below. Contract §12/A-2: this is written for
intelligent non-programmers, and the word "payload" never appears in
anything a reader sees — it is "feedback data" or "feedback report" (the
schema field name ``payload_sha256`` is a technical identifier and is not
shown). FR-FB-11: reports are *pseudonymous*, never *anonymous*, and no
surface here claims otherwise.

Exit codes are the frozen plan §5.9 contract, not ``cli/main.py``'s general
codes — a feedback run reports what happened to the *report*:
``0`` sent · ``2`` declined · ``3`` the service could not be reached or
refused · ``4`` this machine is not enrolled · ``5`` the report or the
invocation cannot be used as written.

Every engine import is function-local. Building the argument parser reads
:data:`HELP_DESCRIPTION` and :data:`HELP_EPILOG` from this module on every
``s0ma`` invocation, and no other command should pay for the feedback
engine's import to get them.
"""

from __future__ import annotations

import math
import os
import sys
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import argparse
    from typing import TextIO

    from s0ma_dsl.feedback.client import FeedbackReportRow, FeedbackResult
    from s0ma_dsl.feedback.drafts import FeedbackDraft
    from s0ma_dsl.feedback.model import FeedbackEnvelope, FeedbackProblem

__all__ = [
    "CONTACT_QUESTION",
    "DEFAULT_CATEGORY",
    "DEFAULT_IMPACT",
    "DETAIL_QUESTION",
    "EXIT_AUTH",
    "EXIT_DECLINED",
    "EXIT_FAILED",
    "EXIT_SENT",
    "EXIT_VALIDATION",
    "FIELD_LABELS",
    "HELP_DESCRIPTION",
    "HELP_EPILOG",
    "SEND_QUESTION",
    "cmd_feedback_compose",
    "cmd_feedback_delete",
    "cmd_feedback_drafts",
    "cmd_feedback_enroll",
    "cmd_feedback_list",
    "cmd_feedback_submit",
    "render_card",
    "run_feedback",
]

# ---------------------------------------------------------------------------
# Exit codes (plan §5.9 — this family's own contract)
# ---------------------------------------------------------------------------

#: The report reached the service and a matching receipt came back.
EXIT_SENT = 0

#: The reader said no. Nothing was sent; the draft (if any) is kept.
EXIT_DECLINED = 2

#: The service could not be reached, or refused for a reason a retry may
#: fix. The draft is kept and the retry command is printed.
EXIT_FAILED = 3

#: This machine is not enrolled, or its access was refused.
EXIT_AUTH = 4

#: The report cannot be sent as written, or the command cannot be honoured
#: as invoked (a non-interactive approval, a missing id, an unknown draft).
EXIT_VALIDATION = 5

#: Server codes that mean "who are you?" rather than "try again".
AUTH_CODES = frozenset({"INVALID_TOKEN", "NOT_ENTITLED"})

#: Server codes that mean "this report, as written, cannot be accepted".
#: Retrying the same text cannot help, so they are not failures to retry.
VALIDATION_CODES = frozenset(
    {"SCHEMA_INVALID", "PAYLOAD_TOO_LARGE", "SENSITIVE_CONTENT", "BAD_REQUEST"}
)

#: Client-side transport codes. These are the only ones that make
#: ``s0ma feedback list`` fall back to the local receipts log: they mean the
#: service was not reached, not that it had an answer we did not like.
OFFLINE_CODES = frozenset(
    {"TIMEOUT", "NETWORK_UNREACHABLE", "INVALID_RESPONSE", "SERVER_ERROR"}
)

# ---------------------------------------------------------------------------
# Copy (contract §12)
# ---------------------------------------------------------------------------

#: What each category means, for a reader who has never seen the vocabulary.
#: Keys are the frozen contract §4 values **in contract order**; both the
#: key set and the order are held by this module's own tests, because the
#: help text below lists these keys as if they were the vocabulary itself.
CATEGORY_HELP: dict[str, str] = {
    "bug": "something is broken or gives the wrong answer",
    "friction": "it works, but it is harder than it should be",
    "idea": "a suggestion for something new",
    "documentation": "the writing or the examples were wrong, missing, or unclear",
    "diagnostic_quality": "a message, warning, or error that did not help you",
    "agent_behavior": "how an AI agent used s0ma",
    "performance": "something was too slow, or used too much of the machine",
    "privacy_or_trust": "a concern about what s0ma sends, stores, or shows",
    "other": "none of these fit",
}

IMPACT_HELP: dict[str, str] = {
    "blocked": "I cannot get my work done",
    "degraded": "I can work, but it is worse",
    "minor": "a small annoyance",
    "idea": "not a problem — this is a suggestion",
}

#: What a report is filed as when the reader does not say (follow-up F-1).
#: These two claim the least: they record that something happened without
#: putting words in the reader's mouth, which is exactly what a one-line
#: report knows. Both are members of the frozen §4 vocabulary.
DEFAULT_CATEGORY = "other"
DEFAULT_IMPACT = "minor"


def _listed(values: Mapping[str, str] | Sequence[str]) -> str:
    """A vocabulary as one indented, hand-width paragraph — help or refusal."""
    return textwrap.fill(
        ", ".join(values), width=78, initial_indent="  ", subsequent_indent="  "
    )

#: Pre-wrapped: the parser uses RawDescriptionHelpFormatter so that the
#: epilog's examples keep their shape, and that formatter leaves the
#: description exactly as written too.
HELP_DESCRIPTION = """\
Send feedback about s0ma to the s0ma team. You see the exact feedback data,
and approve it, before anything leaves this machine.

With -m "...", that is the whole command: s0ma shows you the report and asks
you two questions. Without it, you are asked for one line first, and the
longer questions are offered rather than assumed.\
"""

HELP_EPILOG = f"""\
Feedback reports are pseudonymous, not anonymous: each one carries a random id
for this installation of s0ma, and never your name, your source code, your
files, or your conversations. Nothing is ever sent without your approval.

Unsent drafts, the record of what you have sent, and this machine's feedback
access are stored in ~/.s0ma (%USERPROFILE%\\.s0ma on Windows) — outside every
project, and never in a repository.

What a feedback report may and may not carry is written down in
docs/contracts/feedback-v1.md.

Which kind of feedback (-c), default {DEFAULT_CATEGORY}:
{_listed(CATEGORY_HELP)}
How much it is affecting you (-i), default {DEFAULT_IMPACT}:
{_listed(IMPACT_HELP)}

Examples:
  s0ma feedback                        write and send one report
  s0ma feedback -m "the check stops"   one line, then the two questions
  s0ma feedback -m "..." -c bug -i degraded
                                       say which kind it is, and how much
  s0ma feedback drafts                 reports written here but not yet sent
  s0ma feedback submit fbd_1a2b3c4d    finish sending a saved draft
  s0ma feedback list                   the reports you have sent
  s0ma feedback delete fb_...          remove one report
  s0ma feedback enroll                 connect this machine to your account
"""

#: FD-2, verbatim. The wording is frozen; only the trailing space is ours.
CONTACT_QUESTION = "May kn0wthyself contact you about this report? [y/N] "

#: Hand-wrapped, like every paragraph this module prints: the width is a
#: deliberate reading choice, not whatever the terminal happens to be.
CONTACT_NOTE = """\
Answering yes links this report to your account email so the team can reply.
Answering no keeps the report pseudonymous.\
"""

#: Contract §12/A-2, verbatim. The one confirmation that sends anything.
SEND_QUESTION = "Send exactly this feedback data? [y/N] "

#: One question standing in for four (follow-up F-1). Enter and "n" both
#: skip the whole long half of the form; only "y" walks it.
DETAIL_QUESTION = "Add more detail — what you expected, what happened, the steps? [y/N] "

PREVIEW_HEADING = "This is the exact feedback data that would be sent — nothing else:"

NON_INTERACTIVE_REFUSAL = """\
This needs a terminal: you have to see the exact feedback data, and approve it,
before anything is sent — and there is no way to do that without one.
Nothing was sent.\
"""

NON_INTERACTIVE_REMEDIATION = """\
Run it again in a terminal. No flag skips the approval step — that is the point
of it.\
"""

#: The card's plain label for each envelope field, in the order the card
#: shows them — reading order, not contract order: what the reader wrote
#: first, then what s0ma added. The card walks the report itself, so a key
#: missing from this map still renders, under a label that says s0ma did
#: not expect it. Nothing the fingerprint covers may be invisible.
FIELD_LABELS: dict[str, str] = {
    "summary": "Summary",
    "category": "Category",
    "impact": "Impact",
    "expected": "What you expected",
    "actual": "What actually happened",
    "reproduction": "Steps",
    "details": "More detail",
    "context": "About this install",
    "privacy": "What this report carries",
    "schema": "Report format",
}

#: The privacy block's redaction counts get their own section, in words.
REMOVED_LABEL = "What was removed"

#: How much of the fingerprint the card shows. Enough to compare against a
#: receipt at a glance; the whole of it travels with the report.
FINGERPRINT_HEX_SHOWN = 16

FINGERPRINT_NOTE = """\
The whole fingerprint travels with this report, so the receipt that comes
back can be checked against exactly what you approved.\
"""

#: Where the card wraps its compact pairs. A deliberate reading width, not
#: whatever the terminal happens to be; whole pairs never split across it.
CARD_WIDTH = 74

#: Plain words for each redaction type (singular, plural). Keyed by the
#: redactor's own count keys so a new rule cannot ship without copy.
REDACTION_NOUNS: dict[str, tuple[str, str]] = {
    "secrets": ("secret", "secrets"),
    "emails": ("email address", "email addresses"),
    "urls": ("web address", "web addresses"),
    "paths": ("file path", "file paths"),
    "usernames": ("user name", "user names"),
    "host_ids": ("machine identifier", "machine identifiers"),
    "trace_frames": ("error trace line", "error trace lines"),
}


# ---------------------------------------------------------------------------
# Terminal conversation
# ---------------------------------------------------------------------------


class _AbortedError(Exception):
    """Input ended before the reader finished answering."""


def _interactive() -> bool:
    """Whether there is a person at a keyboard on the other end."""
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - closed stdin
        return False


def _ask(prompt: str) -> str:
    """Read one answer. End-of-input and Ctrl-C both end the conversation."""
    try:
        return input(prompt)
    except EOFError as error:
        raise _AbortedError from error
    except KeyboardInterrupt as error:
        print()
        raise _AbortedError from error


def _confirm(question: str) -> bool:
    """Ask a ``[y/N]`` question. Anything but yes — silence included — is no."""
    try:
        answer = _ask(question)
    except _AbortedError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _ask_yes(question: str) -> bool:
    """Ask a ``[y/N]`` question *during compose*, where silence is leaving.

    :func:`_confirm` reads end-of-input as "no", which is the right answer
    to a question about sending. Half way through writing a report it is
    not an answer at all — walking away there saves nothing and sends
    nothing — so this one lets :class:`_AbortedError` through.
    """
    return _ask(question).strip().lower() in {"y", "yes"}


def _choose(
    title: str, values: Sequence[str], glosses: Mapping[str, str], default: str
) -> str:
    """Show a numbered menu and return the chosen value.

    A bare Enter takes *default* — the menus are the two questions a reader
    is least able to answer for a report they have not written yet, and a
    frozen vocabulary member is a truthful answer to both. Out-of-range and
    non-numeric answers re-ask rather than guess: a wrong choice travels
    with the report.
    """
    print()
    print(title)
    print()
    width = max(len(value) for value in values)
    for number, value in enumerate(values, start=1):
        marker = f"   [Enter = {default}]" if value == default else ""
        print(f"  {number:>2}  {value.ljust(width)}   {glosses[value]}{marker}")
    print()
    limit = len(values)
    invitation = f"Enter a number from 1 to {limit}, or press Enter for {default}"
    while True:
        answer = _ask(f"{invitation}: ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= limit:
            return values[int(answer) - 1]
        print(f"Please enter a number from 1 to {limit}, or press Enter for {default}.")


def _ask_required(question: str, prompt: str) -> str:
    """Ask for something the report cannot do without."""
    print()
    print(question)
    while True:
        answer = _ask(prompt).strip()
        if answer:
            return answer
        print("This one is needed — a report without it cannot be read.")


def _ask_optional(question: str, prompt: str) -> str | None:
    """Ask for something the reader may skip with Enter."""
    print()
    print(f"{question} (press Enter to skip)")
    return _ask(prompt).strip() or None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _format_ts(epoch_ms: int) -> str:
    """Render an epoch-millisecond timestamp for a reader."""
    try:
        moment = datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)
    except (OSError, OverflowError, ValueError):  # pragma: no cover - absurd clock
        return str(epoch_ms)
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def _format_date(epoch_ms: int) -> str:
    """Render an epoch-millisecond timestamp as a date."""
    try:
        moment = datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)
    except (OSError, OverflowError, ValueError):  # pragma: no cover - absurd clock
        return str(epoch_ms)
    return moment.strftime("%Y-%m-%d")


def _words(key: str) -> str:
    """A field name as words: ``includes_source`` becomes ``includes source``."""
    return key.replace("_", " ")


def _scalar(value: Any) -> str:
    """Render one value in plain words, never in its Python spelling.

    Booleans are yes and no, an absent value is "not recorded", and a
    nested map or list is flattened rather than dropped — every piece of
    text a report carries has to survive to the card.
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "not recorded"
    if isinstance(value, str):
        return value or "(empty)"
    if isinstance(value, Mapping):
        joined = ", ".join(f"{_words(str(key))} {_scalar(value[key])}" for key in sorted(value))
        return joined or "(empty)"
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return ", ".join(_scalar(item) for item in value) or "(empty)"
    return str(value)


def _redaction_sentence(counts: Mapping[str, Any]) -> str:
    """Say what the redactor removed, in words rather than field names.

    A counter this module has no copy for is still said, under its own name
    in words: a removal nobody can read about is a removal nobody can
    check. A zero is not a removal, so zeros are answered by the one line
    that covers them all rather than listed one by one.
    """
    parts: list[str] = []
    for key, removed in sorted(counts.items()):
        nouns = REDACTION_NOUNS.get(key, (_words(key), _words(key)))
        if isinstance(removed, int) and not isinstance(removed, bool):
            if removed > 0:
                parts.append(_plural(removed, *nouns))
            continue
        parts.append(f"{nouns[1]}: {_scalar(removed)}")
    if not parts:
        return "Nothing needed removing."
    return f"Removed before anything leaves this machine: {', '.join(parts)}."


def _print_problems(problems: Sequence[FeedbackProblem]) -> None:
    """Show why a report cannot be sent, in the engine's own words."""
    print("This feedback report cannot be sent as written.", file=sys.stderr)
    for problem in problems:
        print(file=sys.stderr)
        print(f"  {problem.message}", file=sys.stderr)
        print(f"  {problem.remediation}", file=sys.stderr)
        print(f"  Code: {problem.code}", file=sys.stderr)


def _print_failure(result: FeedbackResult) -> None:
    """Show a service failure: its own words, then its own code.

    The server's ``message`` and ``remediation`` are printed as they arrived
    (contract §2.1). The one addition is the enrolment line, which plan §5.9
    requires on the auth path whatever the service happened to say.
    """
    fallback = "The s0ma feedback service could not complete this."
    print(result.message or fallback, file=sys.stderr)
    if result.remediation:
        print(result.remediation, file=sys.stderr)
    if result.code == "INVALID_TOKEN" and "s0ma feedback enroll" not in (
        result.remediation or ""
    ):
        print("Run `s0ma feedback enroll` to set this machine up again.", file=sys.stderr)
    if result.code:
        print(f"Code: {result.code}", file=sys.stderr)


def _exit_for(code: str | None) -> int:
    """Map a service or transport code onto the plan §5.9 exit contract."""
    if code in AUTH_CODES:
        return EXIT_AUTH
    if code in VALIDATION_CODES:
        return EXIT_VALIDATION
    return EXIT_FAILED


def _refuse_non_interactive(command: str) -> int:
    """Refuse, in words, rather than send anything nobody approved."""
    print(NON_INTERACTIVE_REFUSAL, file=sys.stderr)
    print(NON_INTERACTIVE_REMEDIATION, file=sys.stderr)
    print(f"Command: {command}", file=sys.stderr)
    return EXIT_VALIDATION


def _pairs(mapping: Mapping[str, Any]) -> list[str]:
    """``key: value`` for every key, in the order the fingerprint sees them."""
    return [f"{_words(str(key))}: {_scalar(mapping[key])}" for key in sorted(mapping)]


def _pack(pairs: Sequence[str], width: int = CARD_WIDTH) -> list[str]:
    """Lay short pairs out several to a line, never splitting one in half.

    Wrapping mid-value would make the reader guess where a version number
    or an identifier ends, so lines run over rather than break a pair.
    """
    lines: list[str] = []
    current = ""
    for pair in pairs:
        candidate = f"{current} · {pair}" if current else pair
        if current and len(candidate) > width:
            lines.append(current)
            current = pair
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _value_lines(key: str, value: Any) -> list[str]:
    """The card's body for one field, as lines — content kept verbatim.

    Text is printed as it stands, line for line: the reader is approving
    these characters, so this is the one place that must not paraphrase.
    """
    if key in {"category", "impact"}:
        glosses = CATEGORY_HELP if key == "category" else IMPACT_HELP
        gloss = glosses.get(value) if isinstance(value, str) else None
        return [f"{value} — {gloss}" if gloss else _scalar(value)]
    if isinstance(value, str):
        return value.split("\n")
    if key == "reproduction" and isinstance(value, Sequence):
        return [f"{number}. {_scalar(step)}" for number, step in enumerate(value, start=1)]
    if isinstance(value, Mapping):
        return _pack(_pairs(value))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_scalar(item) for item in value]
    return [_scalar(value)]


def _section(label: str, body: Sequence[str]) -> list[str]:
    """One labelled block of the card: a blank line, a label, its content."""
    return ["", f"  {label}", *(f"    {line}" for line in (body or ["(nothing)"]))]


def _privacy_sections(value: Any) -> list[str]:
    """The privacy block: what the report says of itself, then what was cut."""
    if not isinstance(value, Mapping):
        return _section(FIELD_LABELS["privacy"], _value_lines("privacy", value))
    carried = {key: item for key, item in value.items() if key != "redacted"}
    lines = _section(FIELD_LABELS["privacy"], _pack(_pairs(carried))) if carried else []
    if "redacted" not in value:
        return lines
    removed = value["redacted"]
    body = (
        [_redaction_sentence(removed)]
        if isinstance(removed, Mapping)
        else _value_lines("redacted", removed)
    )
    return [*lines, *_section(REMOVED_LABEL, body)]


def _short_fingerprint(fingerprint: str) -> str:
    """The head of the hash — enough to match a receipt against by eye."""
    algorithm, separator, digest = fingerprint.partition(":")
    if not separator:  # pragma: no cover - payload_sha256 always prefixes
        return fingerprint
    return f"{algorithm}:{digest[:FINGERPRINT_HEX_SHOWN]}…"


def render_card(payload: Mapping[str, Any]) -> list[str]:
    """Render one feedback report as the lines of its card.

    *payload* is the object that is about to be hashed and sent, and this
    is a rendering of it rather than a summary of it: every key present is
    shown, including one this module has never heard of, because a field
    the reader cannot see is a field the reader cannot approve. The
    fingerprint is :func:`~s0ma_dsl.feedback.model.payload_sha256` of this
    same object, computed here so the card and the hash cannot drift.
    """
    from s0ma_dsl.feedback.model import payload_sha256

    lines: list[str] = []
    unexpected = sorted(set(payload) - set(FIELD_LABELS))
    for key in (*FIELD_LABELS, *unexpected):
        if key not in payload:
            continue
        if key == "privacy":
            lines.extend(_privacy_sections(payload[key]))
            continue
        label = FIELD_LABELS.get(key) or f"{_words(key).capitalize()} (s0ma did not expect this)"
        lines.extend(_section(label, _value_lines(key, payload[key])))
    lines.append("")
    lines.append(f"  fingerprint: {_short_fingerprint(payload_sha256(payload))}")
    lines.extend(f"  {line}" for line in FINGERPRINT_NOTE.split("\n"))
    return lines


def _print_preview(envelope: FeedbackEnvelope) -> None:
    """Show the whole report, in plain words, exactly as it will be sent."""
    print()
    print(PREVIEW_HEADING)
    for line in render_card(envelope.to_payload()):
        print(line)


def _print_receipt(result: FeedbackResult) -> None:
    """Confirm a report the service acknowledged — never one it did not."""
    receipt = result.receipt
    if receipt is None:  # pragma: no cover - submit() guarantees one on ok
        return
    print()
    if result.replayed:
        print("This report was already on file, so it was not filed twice.")
    else:
        print("Your feedback report was received. Thank you.")
    print()
    print(f"  Report id    {receipt.feedback_id}")
    print(f"  Received     {_format_ts(receipt.received_ts)}")
    print(f"  Fingerprint  {receipt.payload_sha256}")
    print("               This matches the feedback data you approved.")
    print()
    if receipt.status == "received":
        print(f"To remove this report later, run: s0ma feedback delete {receipt.feedback_id}")
        return
    # Contract r4 item 4: a replay reports the row's CURRENT status, and a
    # report already deleted is never re-announced as newly received.
    print(f"Its status with the s0ma team is now: {receipt.status}.")


def _print_report_rows(rows: Sequence[FeedbackReportRow], *, stream: TextIO | None = None) -> None:
    """Render a listing. Refusals pass ``sys.stderr`` so one message stays whole."""
    where = stream if stream is not None else sys.stdout
    for row in rows:
        when = _format_ts(row.received_ts) if row.received_ts else "date unknown"
        status = row.status or "received"
        print(f"  {row.feedback_id}  {when}  {status}", file=where)
        print(f"      {row.category}/{row.impact}  {row.summary}", file=where)


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


def _save_draft(
    envelope: FeedbackEnvelope, *, contact_ok: bool
) -> FeedbackDraft | None:
    """Write the draft that a failed send will be resumed from.

    Returns ``None`` when the state directory cannot be written. An
    unwritable home is not a reason to refuse to send feedback — it only
    means there will be nothing to resume from, and the reader is told so.
    """
    from s0ma_dsl.feedback import drafts as feedback_drafts

    try:
        return feedback_drafts.save_draft(
            envelope,
            channel="cli",
            approval_method="cli_tty",
            contact_ok=contact_ok,
        )
    except OSError:
        print("This report could not be saved on this machine.", file=sys.stderr)
        print("If sending fails, there will be nothing to retry from.", file=sys.stderr)
        return None


def _declined(draft: FeedbackDraft | None) -> int:
    """The reader said no. Say what was kept, and how to come back to it."""
    print()
    print("Nothing was sent.")
    if draft is None:
        print("Nothing was saved either.")
        return EXIT_DECLINED
    print(f"Your report is saved here as draft {draft.draft_id}.")
    print(f"To pick it up again, run: s0ma feedback submit {draft.draft_id}")
    return EXIT_DECLINED


def _send(
    envelope: FeedbackEnvelope,
    *,
    idempotency_key: str,
    channel: str,
    approval_method: str,
    contact_ok: bool,
    draft_id: str | None,
) -> int:
    """Submit an approved report and report the outcome in plan §5.9 terms."""
    from s0ma_dsl.feedback import client as feedback_client
    from s0ma_dsl.feedback import drafts as feedback_drafts

    result = feedback_client.submit(
        envelope,
        idempotency_key=idempotency_key,
        channel=channel,
        approval_method=approval_method,
        contact_ok=contact_ok,
    )
    if not result.ok or result.receipt is None:
        print(file=sys.stderr)
        _print_failure(result)
        if draft_id is not None:
            print(f"Your report is kept here as draft {draft_id}.", file=sys.stderr)
            print(f"To try again, run: s0ma feedback submit {draft_id}", file=sys.stderr)
        return _exit_for(result.code)

    receipt = result.receipt
    if receipt.status == "received":
        try:
            feedback_drafts.append_receipt(
                feedback_id=receipt.feedback_id,
                category=envelope.category,
                summary=envelope.summary,
                payload_sha256=receipt.payload_sha256,
            )
        except OSError:  # pragma: no cover - unwritable home
            print("The report was received, but it could not be added to", file=sys.stderr)
            print("this machine's record of what you have sent.", file=sys.stderr)
    if draft_id is not None:
        feedback_drafts.delete_draft(draft_id)
    _print_receipt(result)
    return EXIT_SENT


# ---------------------------------------------------------------------------
# `s0ma feedback` — interactive compose
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Answers:
    """What the reader typed, before any of it has been checked or redacted."""

    category: str
    impact: str
    summary: str
    expected: str | None
    actual: str | None
    details: str | None
    reproduction: tuple[str, ...]


def _written(message: str, category: str | None, impact: str | None) -> _Answers:
    """The fast path (F-1): one line is the whole report, and nothing is asked.

    A reader who already knows what they want to say should not be walked
    through a form to say it. What the flags do not set falls to the
    defaults, which are shown on the card like every other field — so the
    fast path skips questions, never disclosure.
    """
    return _Answers(
        category=category or DEFAULT_CATEGORY,
        impact=impact or DEFAULT_IMPACT,
        summary=message,
        expected=None,
        actual=None,
        details=None,
        reproduction=(),
    )


def _detail_answers() -> tuple[str | None, str | None, str | None, tuple[str, ...]]:
    """The long half of the form, walked only when the reader asks for it."""
    from s0ma_dsl.feedback.model import REPRODUCTION_MAX_STEPS

    expected = _ask_optional("What did you expect to happen?", "Expected: ")
    actual = _ask_optional("What happened instead?", "Actual: ")

    print()
    print("Steps to see it happen, one per line (press Enter on an empty line to finish)")
    steps: list[str] = []
    while len(steps) < REPRODUCTION_MAX_STEPS:
        step = _ask(f"  Step {len(steps) + 1}: ").strip()
        if not step:
            break
        steps.append(step)
    if len(steps) == REPRODUCTION_MAX_STEPS:
        print(f"  That is as many steps as one report can carry ({REPRODUCTION_MAX_STEPS}).")

    details = _ask_optional("Anything else the s0ma team should know?", "Details: ")
    return expected, actual, details, tuple(steps)


def _compose(category: str | None, impact: str | None) -> _Answers:
    """Ask the questions that make one report. Raises :class:`_AbortedError`.

    The short form (F-1): the one line a report cannot do without, two
    menus that take a bare Enter, and one question offering the rest. A
    reader with nothing more to say answers three times and is at the card;
    a reader with more to say loses nothing by being asked first.
    """
    from s0ma_dsl.feedback.model import CATEGORIES, IMPACTS

    summary = _ask_required("In one line, what is your feedback?", "Summary: ")
    if category is None:
        category = _choose(
            "Which of these is closest to your feedback?",
            CATEGORIES,
            CATEGORY_HELP,
            DEFAULT_CATEGORY,
        )
    if impact is None:
        impact = _choose(
            "How much is this affecting your work?", IMPACTS, IMPACT_HELP, DEFAULT_IMPACT
        )

    print()
    if _ask_yes(DETAIL_QUESTION):
        expected, actual, details, steps = _detail_answers()
    else:
        expected, actual, details, steps = None, None, None, ()

    return _Answers(
        category=category,
        impact=impact,
        summary=summary,
        expected=expected,
        actual=actual,
        details=details,
        reproduction=steps,
    )


def _flag(args: argparse.Namespace, name: str) -> str | None:
    """One command-line value, trimmed; blank and absent are both nothing."""
    return str(getattr(args, name, None) or "").strip() or None


def _refuse_choice(flag: str, label: str, value: str, allowed: Sequence[str]) -> int:
    """Refuse an unknown ``-c``/``-i`` value by naming every value there is.

    The vocabulary is frozen and travels with the report, so a near miss is
    not guessed at — but a refusal that does not say what the choices are
    would leave the reader worse off than the menu they skipped.
    """
    print(f"`{value}` is not {label} s0ma recognises.", file=sys.stderr)
    print(f"Pass one of these with {flag}:", file=sys.stderr)
    print(_listed(allowed), file=sys.stderr)
    print("Nothing was sent.", file=sys.stderr)
    return EXIT_VALIDATION


def cmd_feedback_compose(args: argparse.Namespace) -> int:
    """Implement ``s0ma feedback [-m ...] [-c ...] [-i ...]`` (plan §5.9, T1)."""
    from s0ma_dsl.feedback.context import build_context
    from s0ma_dsl.feedback.model import (
        CATEGORIES,
        IMPACTS,
        build_envelope,
        validate_envelope,
    )
    from s0ma_dsl.feedback.redact import redact_envelope

    category = _flag(args, "category")
    impact = _flag(args, "impact")
    if category is not None and category not in CATEGORIES:
        return _refuse_choice("--category", "a feedback category", category, CATEGORIES)
    if impact is not None and impact not in IMPACTS:
        return _refuse_choice("--impact", "an impact level", impact, IMPACTS)

    if not _interactive():
        return _refuse_non_interactive("s0ma feedback")

    message = _flag(args, "message")
    print("Feedback about s0ma. Nothing is sent until you approve it.")
    try:
        fields = (
            _written(message, category, impact)
            if message is not None
            else _compose(category, impact)
        )
    except _AbortedError:
        print()
        print("Nothing was sent, and nothing was saved.")
        return EXIT_DECLINED

    validation = build_envelope(
        category=fields.category,
        impact=fields.impact,
        summary=fields.summary,
        expected=fields.expected,
        actual=fields.actual,
        details=fields.details,
        reproduction=fields.reproduction,
        context=build_context(channel="cli"),
    )
    if validation.envelope is None:
        _print_problems(validation.problems)
        return EXIT_VALIDATION

    # The counts the redactor returns are the ones it wrote into the
    # envelope's privacy block, and the card reads them from there — from
    # the object the fingerprint covers, never from a second copy.
    envelope, _ = redact_envelope(validation.envelope)
    problems = validate_envelope(envelope)
    if problems:
        _print_problems(problems)
        return EXIT_VALIDATION

    _print_preview(envelope)
    print()
    print(CONTACT_NOTE)
    contact_ok = _confirm(CONTACT_QUESTION)

    # The draft is written before the question that sends anything, so every
    # answer — yes, no, or a network failure after yes — leaves something to
    # come back to, under the one idempotency key this report will ever use.
    draft = _save_draft(envelope, contact_ok=contact_ok)
    print()
    if not _confirm(SEND_QUESTION):
        return _declined(draft)

    from s0ma_dsl.feedback.drafts import new_idempotency_key

    return _send(
        envelope,
        idempotency_key=(
            draft.idempotency_key if draft is not None else new_idempotency_key()
        ),
        channel="cli",
        approval_method="cli_tty",
        contact_ok=contact_ok,
        draft_id=draft.draft_id if draft is not None else None,
    )


# ---------------------------------------------------------------------------
# `s0ma feedback drafts` / `submit <draft-id>`
# ---------------------------------------------------------------------------


def cmd_feedback_drafts(args: argparse.Namespace) -> int:
    """Implement ``s0ma feedback drafts`` — unsent reports on this machine."""
    from s0ma_dsl.feedback.drafts import (
        DRAFT_TTL_DAYS,
        SUMMARY_LOG_CHARS,
        list_drafts,
        purge_expired_drafts,
    )

    del args  # the listing takes no options
    expired = purge_expired_drafts()
    if expired:
        removed = _plural(len(expired), "draft", "drafts")
        print(f"Removed {removed} older than {DRAFT_TTL_DAYS} days.")
        print()

    drafts = list_drafts()
    if not drafts:
        print("You have no unsent feedback reports on this machine.")
        print("To write one, run: s0ma feedback")
        return EXIT_SENT

    print(f"You have {_plural(len(drafts), 'unsent report', 'unsent reports')} here:")
    print()
    for draft in drafts:
        print(f"  {draft.draft_id}  {_format_ts(draft.created_ts)}")
        print(f"      {draft.envelope.summary[:SUMMARY_LOG_CHARS]}")
    print()
    print("To finish sending one, run: s0ma feedback submit <draft-id>")
    return EXIT_SENT


def cmd_feedback_submit(args: argparse.Namespace) -> int:
    """Implement ``s0ma feedback submit <draft-id>`` — re-approve, then send."""
    from s0ma_dsl.feedback.drafts import load_draft
    from s0ma_dsl.feedback.model import validate_envelope
    from s0ma_dsl.feedback.redact import redact_envelope

    if not _interactive():
        return _refuse_non_interactive("s0ma feedback submit")

    draft_id = str(getattr(args, "draft_id", "") or "").strip()
    draft = load_draft(draft_id)
    if draft is None:
        print(f"There is no saved draft called {draft_id!r} on this machine.", file=sys.stderr)
        print("Run `s0ma feedback drafts` to see the drafts you do have.", file=sys.stderr)
        return EXIT_VALIDATION

    # Redacting again is a fixed point for a report composed here, and the
    # only protection for one whose file was edited by hand since.
    envelope, _ = redact_envelope(draft.envelope)
    problems = validate_envelope(envelope)
    if problems:
        _print_problems(problems)
        return EXIT_VALIDATION

    print(f"Draft {draft.draft_id}, written {_format_ts(draft.created_ts)}.")
    _print_preview(envelope)
    print()
    answer = "yes" if draft.contact_ok else "no"
    print(f"You already answered the contact question for this report: {answer}.")
    print()
    if not _confirm(SEND_QUESTION):
        return _declined(draft)

    return _send(
        envelope,
        idempotency_key=draft.idempotency_key,
        channel=draft.channel,
        approval_method=draft.approval_method,
        contact_ok=draft.contact_ok,
        draft_id=draft.draft_id,
    )


# ---------------------------------------------------------------------------
# `s0ma feedback list`
# ---------------------------------------------------------------------------


def _print_local_receipts() -> None:
    """Show the receipts log — this machine's own record, labeled as such."""
    from s0ma_dsl.feedback.drafts import read_receipts

    entries = read_receipts()
    if not entries:
        print("Nothing is recorded on this machine either.")
        return
    print(f"{_plural(len(entries), 'report', 'reports')} recorded on this machine:")
    print()
    for entry in reversed(entries):
        print(f"  {entry.feedback_id}  {_format_ts(entry.ts)}  {entry.category}")
        print(f"      {entry.summary60}")


def cmd_feedback_list(args: argparse.Namespace) -> int:
    """Implement ``s0ma feedback list`` (A-3; contract r4 item 3)."""
    from s0ma_dsl.feedback import client as feedback_client

    del args  # the listing takes no options
    result = feedback_client.list_reports()
    if result.ok:
        rows = result.reports
        if not rows:
            print("You have no feedback reports on file with the s0ma team.")
            return EXIT_SENT
        print(f"You have {_plural(len(rows), 'feedback report', 'feedback reports')} on file:")
        print()
        _print_report_rows(rows)
        print()
        print("To remove one, run: s0ma feedback delete <report-id>")
        return EXIT_SENT

    _print_failure(result)
    if result.code not in OFFLINE_CODES:
        return _exit_for(result.code)
    print()
    _print_local_receipts()
    return EXIT_SENT


# ---------------------------------------------------------------------------
# `s0ma feedback delete`
# ---------------------------------------------------------------------------


def _retry_sentence(retry_after: int | None) -> str:
    """When to run the bulk delete again, from the service's own header."""
    if retry_after is None or retry_after <= 0:
        return "Run `s0ma feedback delete --all` again in about an hour to carry on."
    minutes = max(1, math.ceil(retry_after / 60))
    return (
        f"Run `s0ma feedback delete --all` again in about "
        f"{_plural(minutes, 'minute', 'minutes')} to carry on."
    )


def _delete_bare() -> int:
    """Bare ``delete`` deletes nothing — it shows what there is, and how (A-3).

    All of it goes to stderr, listing included: this is one refusal, and
    splitting it across two streams would tear the message in half.
    """
    from s0ma_dsl.feedback import client as feedback_client

    print("`s0ma feedback delete` on its own does not delete anything.", file=sys.stderr)
    print("Deleting needs you to say which report to delete.", file=sys.stderr)
    print(file=sys.stderr)
    result = feedback_client.list_reports()
    if result.ok and result.reports:
        listed = _plural(len(result.reports), "feedback report", "feedback reports")
        print(f"You have {listed} on file:", file=sys.stderr)
        print(file=sys.stderr)
        _print_report_rows(result.reports, stream=sys.stderr)
    elif result.ok:
        print("You have no feedback reports on file with the s0ma team.", file=sys.stderr)
    else:
        _print_failure(result)
    print(file=sys.stderr)
    print("To delete one report:    s0ma feedback delete <report-id>", file=sys.stderr)
    print("To delete every report:  s0ma feedback delete --all", file=sys.stderr)
    return EXIT_VALIDATION


def _delete_one(feedback_id: str) -> int:
    """Delete exactly one report. The id you typed is the confirmation."""
    from s0ma_dsl.feedback import client as feedback_client

    result = feedback_client.delete_report(feedback_id)
    if not result.ok:
        _print_failure(result)
        return _exit_for(result.code)
    print(f"Report {result.feedback_id or feedback_id} was deleted.")
    print("It is gone from your list; the s0ma team keeps only that it existed.")
    return EXIT_SENT


def _delete_all() -> int:
    """The only bulk path (A-3): preview, one explicit confirmation, then per id."""
    from s0ma_dsl.feedback import client as feedback_client

    if not _interactive():
        return _refuse_non_interactive("s0ma feedback delete --all")

    listing = feedback_client.list_reports()
    if not listing.ok:
        _print_failure(listing)
        print("Nothing was deleted.", file=sys.stderr)
        return _exit_for(listing.code)

    rows = listing.reports
    if not rows:
        print("You have no feedback reports to delete.")
        return EXIT_SENT

    total = len(rows)
    print(f"This will delete {_plural(total, 'feedback report', 'feedback reports')}:")
    print()
    _print_report_rows(rows)
    print()
    if not _confirm(f"Delete all {total} feedback reports? [y/N] "):
        print("Nothing was deleted.")
        return EXIT_DECLINED

    print()
    deleted = 0
    already_gone = 0
    for row in rows:
        outcome = feedback_client.delete_report(row.feedback_id)
        if outcome.ok:
            deleted += 1
            continue
        if outcome.code == "NOT_FOUND":
            # Already gone — deletion is visible as absence (contract r4).
            already_gone += 1
            continue
        # This one failed, so it is still there along with everything after it.
        remaining = total - deleted - already_gone
        if outcome.code == "RATE_LIMITED":
            print(
                "The s0ma feedback service limits how many reports can be deleted "
                "in an hour.",
                file=sys.stderr,
            )
            print("This stopped part way through; nothing else was touched.", file=sys.stderr)
            print(f"  Deleted so far   {deleted}", file=sys.stderr)
            print(f"  Still to delete  {remaining}", file=sys.stderr)
            print(_retry_sentence(outcome.retry_after), file=sys.stderr)
            print(f"Code: {outcome.code}", file=sys.stderr)
            return EXIT_FAILED
        _print_failure(outcome)
        print(f"  Deleted so far   {deleted}", file=sys.stderr)
        print(f"  Still to delete  {remaining}", file=sys.stderr)
        return _exit_for(outcome.code)

    print(f"Deleted {_plural(deleted, 'feedback report', 'feedback reports')}.")
    if already_gone:
        print(f"{_plural(already_gone, 'report', 'reports')} had already been deleted.")
    return EXIT_SENT


def cmd_feedback_delete(args: argparse.Namespace) -> int:
    """Implement ``s0ma feedback delete [<report-id>] [--all]`` (A-3)."""
    identifier = str(getattr(args, "report_id", "") or "").strip()
    delete_all = bool(getattr(args, "all", False))
    if delete_all and identifier:
        print("Pass a report id or --all, not both.", file=sys.stderr)
        print("One deletes exactly that report; the other deletes every one.", file=sys.stderr)
        return EXIT_VALIDATION
    if delete_all:
        return _delete_all()
    if not identifier:
        return _delete_bare()
    return _delete_one(identifier)


# ---------------------------------------------------------------------------
# `s0ma feedback enroll`
# ---------------------------------------------------------------------------


def cmd_feedback_enroll(args: argparse.Namespace) -> int:
    """Implement ``s0ma feedback enroll`` — the FD-4 key-for-token exchange."""
    from s0ma_dsl.feedback import tokens as feedback_tokens

    key = str(getattr(args, "key", "") or "").strip()
    if not key:
        key = os.environ.get("S0MA_LICENSE_KEY", "").strip()

    # A blank key never reaches the network: the engine answers it locally,
    # in the same voice a refusal from the service would use.
    result = feedback_tokens.exchange(key)
    if not result.ok or result.token is None:
        _print_failure(result)
        return _exit_for(result.code)

    stored = result.token
    print("This machine can now send feedback about s0ma.")
    print()
    print(f"  Access code   {stored.token}")
    print(f"  Short name    {stored.token_prefix}")
    if stored.expires_ts is None:
        print("  Valid until   no expiry was recorded")
    else:
        print(f"  Valid until   {_format_date(stored.expires_ts)}")
    print()
    print("The access code is shown once, and is stored at ~/.s0ma/feedback-token.")
    print("You do not need to write it down — s0ma reads it from there.")
    print("Your license key was not stored, and never travels with a feedback report.")
    return EXIT_SENT


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def run_feedback(args: argparse.Namespace) -> int:
    """Dispatch ``s0ma feedback [<subcommand>]``.

    No subcommand is the interactive compose — the command people actually
    run. The rest are the report-management surface around it.
    """
    sub = getattr(args, "feedback_command", None)
    handler = {
        None: cmd_feedback_compose,
        "drafts": cmd_feedback_drafts,
        "submit": cmd_feedback_submit,
        "list": cmd_feedback_list,
        "delete": cmd_feedback_delete,
        "enroll": cmd_feedback_enroll,
    }.get(sub)
    if handler is None:  # pragma: no cover - argparse rejects unknown names
        print(
            "Usage: s0ma feedback [-m TEXT] [-c CATEGORY] [-i IMPACT] | "
            "{drafts|submit <draft-id>|list|delete|enroll}",
            file=sys.stderr,
        )
        return EXIT_VALIDATION
    return handler(args)
