"""FB-M7: the ``s0ma feedback`` command family (plan §5.9/§5.12, contract §12).

No test here touches a network. The three client calls — ``submit``,
``list_reports``, ``delete_report`` — and the token exchange are replaced on
the engine module itself, so what is exercised is the CLI's own behaviour:
what it asks, what it shows, what it writes to ``~/.s0ma``, and which exit
code it returns.

The rules held here as executable facts:

* nothing is sent without the verbatim ``Send exactly this feedback data?``
  answer, and no flag skips it — a non-TTY invocation is refused, never
  submitted silently;
* the reader reviews the whole report before that answer: the card renders
  every field the report carries — including one s0ma has never heard of —
  because what is hashed and what is read may never drift apart (F-1);
* the fast path costs two answers, both of them consequential: ``-m`` asks
  no field question at all, and the slim compose is one line, two menus that
  take a bare Enter, and one question offering the rest (F-1);
* a draft exists *before* the send is attempted, so a network failure leaves
  a resumable report, and the resume submits under the SAME idempotency key;
* the plan §5.9 exit codes: 0 sent · 2 declined · 3 failed · 4 auth · 5 the
  report or the invocation cannot be used;
* A-3 plurality: bare ``delete`` deletes nothing, ``delete --all`` asks first
  and stops gracefully when the service rate-limits it;
* contract §12/A-2 voice: the word "payload" appears in nothing a reader sees.

Every test runs against an isolated HOME (``isolated_home`` is autouse), so
no test can read or write the developer's real ``~/.s0ma``.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.cli import feedback_commands as fb
from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.feedback import client as feedback_client
from s0ma_dsl.feedback import tokens as feedback_tokens
from s0ma_dsl.feedback.client import (
    FeedbackReceipt,
    FeedbackReportRow,
    FeedbackResult,
)
from s0ma_dsl.feedback.drafts import list_drafts, load_draft, read_receipts
from s0ma_dsl.feedback.model import (
    CATEGORIES,
    ENVELOPE_FIELDS,
    IMPACTS,
    FeedbackEnvelope,
    FeedbackPrivacy,
    payload_sha256,
)
from s0ma_dsl.feedback.redact import COUNT_KEYS
from s0ma_dsl.feedback.tokens import StoredToken

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

NOW = 1_787_850_000_000

#: A summary that cannot collide with the redactor's machine-derived rules
#: (rule 7 removes the local user name, rule 8 the local host name).
SUMMARY = "The check step stops halfway through and says nothing about why"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME (and ``%USERPROFILE%``) at a throwaway directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("S0MA_LICENSE_KEY", raising=False)
    monkeypatch.delenv("S0MA_FEEDBACK_TOKEN", raising=False)
    return home


@pytest.fixture
def cli() -> S0maCLI:
    return S0maCLI()


# ---------------------------------------------------------------------------
# A terminal, scripted
# ---------------------------------------------------------------------------


class _FakeTTY:
    """Stands in for ``sys.stdin`` when a test needs to look interactive."""

    def isatty(self) -> bool:
        return True


def terminal(monkeypatch: pytest.MonkeyPatch, answers: Sequence[str]) -> list[str]:
    """Make the process look interactive and script every answer.

    Prompts are echoed to stdout exactly as :func:`input` echoes them, so a
    test can assert on the questions it was asked. The returned list records
    every prompt in order, so a test can also assert on the ones it was NOT
    asked — which is the whole of the F-1 fast path. Running out of answers
    raises ``EOFError``, which is what a closed terminal does.
    """
    pending = list(answers)
    asked: list[str] = []

    def fake_input(prompt: str = "") -> str:
        sys.stdout.write(prompt)
        asked.append(prompt)
        if not pending:
            raise EOFError
        return pending.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(sys, "stdin", _FakeTTY())
    return asked


#: The compose answers for one complete, minimal report: the one line a
#: report cannot do without, the two menus, and "no" to the question that
#: offers the longer half of the form.
COMPOSE_MINIMAL = (
    SUMMARY,  # summary
    "1",  # category: bug
    "2",  # impact: degraded
    "",  # no, do not add more detail
)


def run(cli: S0maCLI, argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """Run one command; return its exit code and everything it printed."""
    code = cli.run(argv)
    captured = capsys.readouterr()
    return code, captured.out + captured.err


# ---------------------------------------------------------------------------
# A fake service
# ---------------------------------------------------------------------------


class _Service:
    """Records what the CLI asked the engine to do, and answers as told."""

    def __init__(self) -> None:
        self.submits: list[dict[str, Any]] = []
        self.deletes: list[str] = []
        self.lists = 0
        self.submit_results: list[FeedbackResult] = []
        self.delete_results: list[FeedbackResult] = []
        self.list_result: FeedbackResult = FeedbackResult(ok=True, reports=())

    def submit(self, envelope: FeedbackEnvelope, **kwargs: Any) -> FeedbackResult:
        self.submits.append({"envelope": envelope, **kwargs})
        if self.submit_results:
            return self.submit_results.pop(0)
        return receipt_for(envelope)

    def list_reports(self, **kwargs: Any) -> FeedbackResult:
        del kwargs
        self.lists += 1
        return self.list_result

    def delete_report(self, feedback_id: str, **kwargs: Any) -> FeedbackResult:
        del kwargs
        self.deletes.append(feedback_id)
        if self.delete_results:
            return self.delete_results.pop(0)
        return FeedbackResult(ok=True, feedback_id=feedback_id)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> _Service:
    """Replace the three network calls on the engine module itself."""
    fake = _Service()
    monkeypatch.setattr(feedback_client, "submit", fake.submit)
    monkeypatch.setattr(feedback_client, "list_reports", fake.list_reports)
    monkeypatch.setattr(feedback_client, "delete_report", fake.delete_report)
    return fake


def receipt_for(envelope: FeedbackEnvelope, *, feedback_id: str = "fb_0001") -> FeedbackResult:
    """A success carrying the hash of exactly what was submitted."""
    receipt = FeedbackReceipt(
        feedback_id=feedback_id,
        received_ts=NOW,
        payload_sha256=envelope.payload_sha256(),
    )
    return FeedbackResult(ok=True, receipt=receipt, feedback_id=feedback_id)


def failure(code: str, **fields: Any) -> FeedbackResult:
    """A failure shaped like the engine's own, with its message + remediation."""
    return FeedbackResult(
        ok=False,
        code=code,
        message=f"The s0ma feedback service could not do this ({code}).",
        remediation=fields.pop("remediation", "Try again in a few minutes."),
        **fields,
    )


# ---------------------------------------------------------------------------
# A report with every field filled in
# ---------------------------------------------------------------------------

#: Every context key contract §5 allows, including the two sub-objects, the
#: list, and a distribution that is not installed. Hand-written rather than
#: collected, so the card is tested against the whole allow-list and not
#: against whatever this developer's machine happens to have.
FULL_CONTEXT: dict[str, Any] = {
    "s0ma_version": "0.18.0",
    "s0ma_core": "0.18.0",
    "s0ma_dsl": "0.18.0",
    "s0ma_mcp": None,
    "s0ma_studi0": "0.18.0",
    "client": {"name": "claude-code", "version": "9.9.9"},
    "surface": {"kind": "tool", "name": "check"},
    "mcp_protocol_version": "2026-03-26",
    "python": "3.13",
    "os": "macos",
    "architecture": "arm64",
    "diagnostic_codes": ["S0MA-E101", "S0MA-E207"],
    "outcome": "failure",
    "duration_bucket": "5-30s",
    "cohort": "beta",
    "pseudonym": "0123456789abcdef0123456789abcdef",
}


def full_envelope() -> FeedbackEnvelope:
    """One report with every envelope field populated."""
    return FeedbackEnvelope(
        category="bug",
        impact="blocked",
        summary=SUMMARY,
        expected="The check step finishes and tells me what it did",
        actual="The check step stops and says nothing",
        details="Only on a fresh copy of the project",
        reproduction=("Write a small project", "Run the check step"),
        context=dict(FULL_CONTEXT),
        privacy=FeedbackPrivacy(redacted={"paths": 2, "secrets": 1}),
    )


def text_leaves(value: Any) -> list[str]:
    """Every piece of text a report carries, at any depth."""
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in text_leaves(item)]
    if isinstance(value, (list, tuple)):
        return [leaf for item in value for leaf in text_leaves(item)]
    return [value] if isinstance(value, str) and value else []


def card_of(payload: dict[str, Any]) -> str:
    """The card for *payload*, as one block of text."""
    return "\n".join(fb.render_card(payload))


def rows(count: int) -> tuple[FeedbackReportRow, ...]:
    return tuple(
        FeedbackReportRow(
            feedback_id=f"fb_{index:04d}",
            received_ts=NOW,
            category="bug",
            impact="degraded",
            summary=f"Report number {index}",
            status="received",
        )
        for index in range(1, count + 1)
    )


# ---------------------------------------------------------------------------
# Help (T3)
# ---------------------------------------------------------------------------


def feedback_help(cli: S0maCLI, capsys: pytest.CaptureFixture[str]) -> str:
    """What ``s0ma feedback --help`` actually prints."""
    with pytest.raises(SystemExit):
        cli.run(["feedback", "--help"])
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_help_says_pseudonymous_not_anonymous(
    cli: S0maCLI, capsys: pytest.CaptureFixture[str]
) -> None:
    text = feedback_help(cli, capsys)
    assert "pseudonymous, not anonymous" in text
    assert "anonymous:" in text  # the claim is qualified, never made bare


def test_help_names_the_state_directory_and_the_contract(
    cli: S0maCLI, capsys: pytest.CaptureFixture[str]
) -> None:
    text = feedback_help(cli, capsys)
    assert "~/.s0ma" in text
    assert "%USERPROFILE%" in text
    assert "docs/contracts/feedback-v1.md" in text


def test_help_lists_every_subcommand(cli: S0maCLI, capsys: pytest.CaptureFixture[str]) -> None:
    text = feedback_help(cli, capsys)
    for name in ("drafts", "submit", "list", "delete", "enroll"):
        assert name in text


def test_no_yes_flag_exists(cli: S0maCLI, capsys: pytest.CaptureFixture[str]) -> None:
    """Plan §5.9: there is no way to skip the approval step."""
    assert "--yes" not in feedback_help(cli, capsys)


def test_help_offers_the_fast_path_and_names_both_defaults(
    cli: S0maCLI, capsys: pytest.CaptureFixture[str]
) -> None:
    """F-1: the one-line route is discoverable, and so is what it assumes."""
    text = feedback_help(cli, capsys)
    for usage in ("[-m MESSAGE]", "[-c CATEGORY]", "[-i IMPACT]"):
        assert usage in text
    assert f"default {fb.DEFAULT_CATEGORY}" in text
    assert f"default {fb.DEFAULT_IMPACT}" in text


def test_help_lists_the_whole_frozen_vocabulary(
    cli: S0maCLI, capsys: pytest.CaptureFixture[str]
) -> None:
    """A reader who skips the menus can still find every value there is."""
    text = feedback_help(cli, capsys)
    for value in (*CATEGORIES, *IMPACTS):
        assert value in text


# ---------------------------------------------------------------------------
# Compose — the happy path (T1)
# ---------------------------------------------------------------------------


def test_compose_sends_and_records_the_receipt(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "y"])  # contact: no, send: yes
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_SENT
    assert len(service.submits) == 1
    call = service.submits[0]
    assert call["channel"] == "cli"
    assert call["approval_method"] == "cli_tty"
    assert call["contact_ok"] is False

    envelope = call["envelope"]
    assert envelope.category == "bug"
    assert envelope.impact == "degraded"
    assert envelope.summary == SUMMARY

    # The questions were asked, verbatim, in that order.
    assert fb.CONTACT_QUESTION.strip() in output
    assert "Send exactly this feedback data? [y/N]" in output
    assert output.index("May kn0wthyself contact") < output.index("Send exactly this")

    # The card showed the exact report that was then sent, and showed it
    # before either question — approval follows the reading, not the other
    # way round.
    card = card_of(envelope.to_payload())
    assert card in output
    assert output.index(card) < output.index("May kn0wthyself contact")

    # The receipt was shown, and appended to this machine's record.
    assert "fb_0001" in output
    assert "matches the feedback data you approved" in output
    assert "s0ma feedback delete fb_0001" in output
    entries = read_receipts()
    assert len(entries) == 1
    assert entries[0].feedback_id == "fb_0001"
    assert entries[0].category == "bug"
    assert entries[0].payload_sha256 == envelope.payload_sha256()

    # The draft it was sent from is gone.
    assert list_drafts() == ()


def test_a_message_asks_only_the_two_questions_that_matter(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F-1: ``-m`` is the whole report; two answers, both consequential."""
    asked = terminal(monkeypatch, ["", "y"])  # contact: no, send: yes
    code, output = run(cli, ["feedback", "-m", SUMMARY], capsys)

    assert code == fb.EXIT_SENT
    assert asked == [fb.CONTACT_QUESTION, fb.SEND_QUESTION]

    envelope = service.submits[0]["envelope"]
    assert envelope.summary == SUMMARY
    assert envelope.category == fb.DEFAULT_CATEGORY
    assert envelope.impact == fb.DEFAULT_IMPACT

    # No field question was asked — not the summary, not the menus, not the
    # one that offers the rest.
    assert "In one line, what is your feedback?" not in output
    assert "Which of these is closest to your feedback?" not in output
    assert "How much is this affecting your work?" not in output
    assert fb.DETAIL_QUESTION not in output

    # …and the reader still read the whole report before approving it.
    assert card_of(envelope.to_payload()) in output


def test_the_long_message_flag_still_works(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, ["", "y"])
    code, _ = run(cli, ["feedback", "--message", SUMMARY], capsys)

    assert code == fb.EXIT_SENT
    assert service.submits[0]["envelope"].summary == SUMMARY


def test_the_kind_flags_override_the_defaults(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    asked = terminal(monkeypatch, ["", "y"])
    code, _ = run(
        cli, ["feedback", "-m", SUMMARY, "-c", "bug", "-i", "degraded"], capsys
    )

    assert code == fb.EXIT_SENT
    assert asked == [fb.CONTACT_QUESTION, fb.SEND_QUESTION]
    envelope = service.submits[0]["envelope"]
    assert envelope.category == "bug"
    assert envelope.impact == "degraded"


@pytest.mark.parametrize(
    ("flag", "value", "label", "vocabulary"),
    [
        ("-c", "banana", "a feedback category", CATEGORIES),
        ("-i", "sideways", "an impact level", IMPACTS),
    ],
)
def test_an_unknown_kind_is_refused_and_the_choices_are_listed(
    cli: S0maCLI,
    service: _Service,
    flag: str,
    value: str,
    label: str,
    vocabulary: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The vocabulary is frozen, so a near miss is refused — never guessed."""
    code, output = run(cli, ["feedback", "-m", SUMMARY, flag, value], capsys)

    assert code == fb.EXIT_VALIDATION
    assert service.submits == []
    assert list_drafts() == ()
    assert f"`{value}` is not {label} s0ma recognises." in output
    assert "Nothing was sent." in output
    for allowed in vocabulary:
        assert allowed in output


def test_contact_yes_travels_as_the_wrapper_fact(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "y", "y"])
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_SENT
    assert service.submits[0]["contact_ok"] is True
    assert "links this report to your account email" in output


def test_optional_fields_and_steps_reach_the_envelope(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(
        monkeypatch,
        [
            SUMMARY,
            "2",  # friction
            "3",  # minor
            "y",  # yes, add more detail
            "It finishes and tells me what it did",
            "It stops and says nothing",
            "Write a small project",
            "Run the check step",
            "",  # end of steps
            "It only happens on a fresh copy",
            "",  # contact: no
            "y",
        ],
    )
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_SENT
    envelope = service.submits[0]["envelope"]
    assert envelope.expected == "It finishes and tells me what it did"
    assert envelope.actual == "It stops and says nothing"
    assert envelope.reproduction == ("Write a small project", "Run the check step")
    assert envelope.details == "It only happens on a fresh copy"

    # Every one of them is on the card, under a label written for a reader.
    assert "What you expected" in output
    assert "What actually happened" in output
    assert "1. Write a small project" in output
    assert "2. Run the check step" in output
    assert "More detail" in output


def test_preview_reports_what_the_redactor_removed(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(
        monkeypatch,
        [
            "It failed and printed API_KEY=hunter2 into the log",
            "1",
            "1",
            "",  # no more detail
            "",  # contact: no
            "y",
        ],
    )
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_SENT
    assert "What was removed" in output
    assert "Removed before anything leaves this machine: 1 secret." in output
    assert "hunter2" not in output
    assert "hunter2" not in service.submits[0]["envelope"].summary


def test_a_report_with_nothing_to_redact_says_so(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "y"])
    _, output = run(cli, ["feedback"], capsys)
    assert "Nothing needed removing." in output


def test_the_counts_are_said_in_words_not_field_names() -> None:
    payload = full_envelope().to_payload()
    assert "Removed before anything leaves this machine: 2 file paths, 1 secret." in (
        card_of(payload)
    )


def test_a_redaction_counter_without_copy_is_still_said() -> None:
    """A new redactor rule cannot make a removal invisible while copy lags."""
    payload = full_envelope().to_payload()
    payload["privacy"]["redacted"] = {"gadgets": 3}
    assert "3 gadgets" in card_of(payload)


def test_every_redaction_type_has_plain_words() -> None:
    """A new redaction rule cannot ship without copy for its counter."""
    assert set(COUNT_KEYS) == set(fb.REDACTION_NOUNS)


def test_every_envelope_field_has_a_plain_label() -> None:
    """A new envelope field cannot ship without a label on the card.

    The card renders an unlabelled field anyway — completeness does not
    depend on this map — but it would say "s0ma did not expect this" about
    a field s0ma itself writes, which is a copy bug, caught here.
    """
    assert set(fb.FIELD_LABELS) == set(ENVELOPE_FIELDS)


def test_every_frozen_vocabulary_value_has_a_gloss_in_order() -> None:
    """Order too, not just membership: the help lists these keys verbatim."""
    assert tuple(fb.CATEGORY_HELP) == CATEGORIES
    assert tuple(fb.IMPACT_HELP) == IMPACTS
    assert fb.DEFAULT_CATEGORY in CATEGORIES
    assert fb.DEFAULT_IMPACT in IMPACTS


# ---------------------------------------------------------------------------
# The card (F-1) — completeness is the trust property
# ---------------------------------------------------------------------------


def test_the_card_shows_every_piece_of_text_the_report_carries() -> None:
    """Nothing the fingerprint covers may be invisible on the card."""
    payload = full_envelope().to_payload()
    card = card_of(payload)

    leaves = text_leaves(payload)
    assert len(leaves) > 20  # a sweep over nothing would pass
    for leaf in leaves:
        assert leaf in card, leaf

    # Every top-level field has its own labelled section.
    for key in payload:
        assert fb.FIELD_LABELS[key] in card or key == "privacy"
    assert "What was removed" in card

    # The values that are not text are said in words, never in Python's
    # spelling of them.
    assert "includes source: no" in card
    assert "includes transcript: no" in card
    assert "s0ma mcp: not recorded" in card
    assert "1. Write a small project" in card
    assert "2. Run the check step" in card
    for spelling in ("None", "True", "False"):
        assert spelling not in card


def test_the_card_shows_a_field_s0ma_did_not_expect() -> None:
    """A key from a newer s0ma renders too, rather than hiding in the hash."""
    payload = {**full_envelope().to_payload(), "extra_note": "smuggled in"}
    card = card_of(payload)

    assert "smuggled in" in card
    assert "Extra note (s0ma did not expect this)" in card


def test_the_card_ends_with_the_fingerprint_of_exactly_what_it_showed() -> None:
    payload = full_envelope().to_payload()
    fingerprint = payload_sha256(payload)

    assert fingerprint.startswith("sha256:")
    card = card_of(payload)
    assert f"fingerprint: {fingerprint[: len('sha256:') + 16]}…" in card
    assert "The whole fingerprint travels with this report" in card


def test_the_card_replaces_the_raw_report_data_in_the_preview(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F-1: a reader approves plain words, not a wall of JSON."""
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "y"])
    _, output = run(cli, ["feedback"], capsys)

    payload = service.submits[0]["envelope"].to_payload()
    assert json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) not in output
    assert '"schema"' not in output
    assert card_of(payload) in output


def test_the_card_fingerprint_is_the_hash_the_service_receipts(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The card's short form and the receipt's full form are one hash."""
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "y"])
    _, output = run(cli, ["feedback"], capsys)

    sent = service.submits[0]["envelope"].payload_sha256()
    assert f"fingerprint: {sent[: len('sha256:') + 16]}…" in output
    assert sent in output  # the receipt prints the whole of it back


def test_the_same_card_is_shown_again_when_a_draft_is_resumed(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "n"])
    _, composed = run(cli, ["feedback"], capsys)
    draft = list_drafts()[0]
    card = card_of(draft.envelope.to_payload())
    assert card in composed

    terminal(monkeypatch, ["n"])
    code, resumed = run(cli, ["feedback", "submit", draft.draft_id], capsys)

    assert code == fb.EXIT_DECLINED
    assert card in resumed
    assert '"schema"' not in resumed


# ---------------------------------------------------------------------------
# Compose — declining, aborting, and menus
# ---------------------------------------------------------------------------


def test_declining_keeps_the_draft_and_exits_two(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "n"])
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_DECLINED
    assert service.submits == []
    drafts = list_drafts()
    assert len(drafts) == 1
    assert drafts[0].envelope.summary == SUMMARY
    assert drafts[0].draft_id in output
    assert f"s0ma feedback submit {drafts[0].draft_id}" in output
    assert "Nothing was sent." in output


def test_silence_at_the_send_question_is_a_decline(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``[y/N]`` means no by default, and end-of-input is silence."""
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", ""])
    code, _ = run(cli, ["feedback"], capsys)
    assert code == fb.EXIT_DECLINED
    assert service.submits == []


def test_walking_away_mid_compose_sends_and_saves_nothing(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, [SUMMARY])  # input ends at the category menu
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_DECLINED
    assert service.submits == []
    assert list_drafts() == ()
    assert "Nothing was sent, and nothing was saved." in output


def test_walking_away_at_the_detail_question_saves_nothing_either(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Silence at a compose question is leaving, not an answer to it."""
    terminal(monkeypatch, [SUMMARY, "1", "2"])  # input ends at the gate
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_DECLINED
    assert service.submits == []
    assert list_drafts() == ()
    assert "Nothing was sent, and nothing was saved." in output


def test_menus_reject_out_of_range_and_ask_again(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(
        monkeypatch,
        [SUMMARY, "0", "99", "banana", "9", "0", "5", "4", "", "", "y"],
    )
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_SENT
    assert (
        f"Please enter a number from 1 to {len(CATEGORIES)}, "
        f"or press Enter for {fb.DEFAULT_CATEGORY}." in output
    )
    assert (
        f"Please enter a number from 1 to {len(IMPACTS)}, "
        f"or press Enter for {fb.DEFAULT_IMPACT}." in output
    )
    envelope = service.submits[0]["envelope"]
    assert envelope.category == CATEGORIES[8]
    assert envelope.impact == IMPACTS[3]


def test_enter_takes_the_default_on_both_menus(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F-1: one line, three Enters, and one yes is a whole report."""
    terminal(monkeypatch, [SUMMARY, "", "", "", "", "y"])
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_SENT
    envelope = service.submits[0]["envelope"]
    assert envelope.category == fb.DEFAULT_CATEGORY
    assert envelope.impact == fb.DEFAULT_IMPACT
    # The menus say so before they are answered, not afterwards.
    assert f"[Enter = {fb.DEFAULT_CATEGORY}]" in output
    assert f"[Enter = {fb.DEFAULT_IMPACT}]" in output


def test_a_kind_given_on_the_command_line_is_not_asked_for_again(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The flags fill the menus in either mode; they only skip the fast one."""
    terminal(monkeypatch, [SUMMARY, "", "", "y"])
    code, output = run(cli, ["feedback", "-c", "documentation", "-i", "blocked"], capsys)

    assert code == fb.EXIT_SENT
    assert "Which of these is closest to your feedback?" not in output
    assert "How much is this affecting your work?" not in output
    envelope = service.submits[0]["envelope"]
    assert envelope.category == "documentation"
    assert envelope.impact == "blocked"
    assert envelope.summary == SUMMARY


def test_the_detail_question_skips_all_four_of_them(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One "no" stands in for four skipped questions (F-1)."""
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "y"])
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_SENT
    assert fb.DETAIL_QUESTION.strip() in output
    for question in (
        "What did you expect to happen?",
        "What happened instead?",
        "Steps to see it happen",
        "Anything else the s0ma team should know?",
    ):
        assert question not in output

    envelope = service.submits[0]["envelope"]
    assert envelope.expected is None
    assert envelope.actual is None
    assert envelope.details is None
    assert envelope.reproduction == ()


def test_the_detail_question_walks_all_four_when_answered_yes(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, [SUMMARY, "1", "2", "y", "", "", "", "", "", "y"])
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_SENT
    for question in (
        "What did you expect to happen?",
        "What happened instead?",
        "Steps to see it happen",
        "Anything else the s0ma team should know?",
    ):
        assert question in output


def test_a_blank_summary_is_asked_for_again(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, ["", "   ", SUMMARY, "1", "1", "", "", "y"])
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_SENT
    assert "This one is needed" in output
    assert service.submits[0]["envelope"].summary == SUMMARY


# ---------------------------------------------------------------------------
# Compose — failure paths and the resume (T1/T2)
# ---------------------------------------------------------------------------


def test_a_network_failure_keeps_the_draft_and_prints_the_retry(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service.submit_results = [failure("NETWORK_UNREACHABLE")]
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "y"])
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_FAILED
    drafts = list_drafts()
    assert len(drafts) == 1
    assert "Code: NETWORK_UNREACHABLE" in output
    assert f"s0ma feedback submit {drafts[0].draft_id}" in output
    assert read_receipts() == ()


def test_resuming_a_draft_reuses_its_idempotency_key(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service.submit_results = [failure("TIMEOUT")]
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "y", "y"])
    assert run(cli, ["feedback"], capsys)[0] == fb.EXIT_FAILED

    draft = list_drafts()[0]
    first_key = service.submits[0]["idempotency_key"]
    assert first_key == draft.idempotency_key

    terminal(monkeypatch, ["y"])
    code, output = run(cli, ["feedback", "submit", draft.draft_id], capsys)

    assert code == fb.EXIT_SENT
    assert len(service.submits) == 2
    resend = service.submits[1]
    assert resend["idempotency_key"] == first_key
    # …and the wrapper facts the draft stored, not freshly asked ones.
    assert resend["contact_ok"] is True
    assert resend["channel"] == "cli"
    assert resend["approval_method"] == "cli_tty"
    assert fb.CONTACT_QUESTION.strip() not in output
    assert "Send exactly this feedback data? [y/N]" in output
    assert list_drafts() == ()


def test_a_replayed_receipt_is_not_announced_as_newly_filed(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service.submit_results = [
        FeedbackResult(
            ok=True,
            feedback_id="fb_0001",
            receipt=FeedbackReceipt(
                feedback_id="fb_0001",
                received_ts=NOW,
                payload_sha256="sha256:ignored",
                replayed=True,
            ),
        )
    ]
    # The engine checks the hash; a stand-in returns whatever it was told to.
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "y"])
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_SENT
    assert "was already on file" in output
    assert "not filed twice" in output


def test_a_replay_of_a_deleted_report_is_not_called_received(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Contract r4 item 4: a replay reports the row's CURRENT status."""
    service.submit_results = [
        FeedbackResult(
            ok=True,
            feedback_id="fb_0001",
            receipt=FeedbackReceipt(
                feedback_id="fb_0001",
                received_ts=NOW,
                payload_sha256="sha256:ignored",
                status="deleted",
                replayed=True,
            ),
        )
    ]
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "y"])
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_SENT
    assert "was received" not in output
    assert "status with the s0ma team is now: deleted" in output
    # A deleted report is not written into this machine's record of sends.
    assert read_receipts() == ()


def test_an_auth_failure_exits_four_and_names_enroll(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service.submit_results = [
        failure("INVALID_TOKEN", remediation="The service says: no."),
    ]
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "y"])
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_AUTH
    assert "The service says: no." in output  # the server's own words survive
    assert "s0ma feedback enroll" in output
    assert "Code: INVALID_TOKEN" in output


def test_a_refused_report_exits_five(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service.submit_results = [failure("SENSITIVE_CONTENT")]
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "y"])
    code, output = run(cli, ["feedback"], capsys)

    assert code == fb.EXIT_VALIDATION
    assert "Code: SENSITIVE_CONTENT" in output


def test_declining_a_resumed_draft_keeps_it(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "n"])
    assert run(cli, ["feedback"], capsys)[0] == fb.EXIT_DECLINED
    draft = list_drafts()[0]

    terminal(monkeypatch, ["n"])
    code, _ = run(cli, ["feedback", "submit", draft.draft_id], capsys)

    assert code == fb.EXIT_DECLINED
    assert service.submits == []
    assert load_draft(draft.draft_id) is not None


def test_an_unknown_draft_id_is_refused_not_crashed(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, ["y"])
    code, output = run(cli, ["feedback", "submit", "fbd_deadbeef"], capsys)

    assert code == fb.EXIT_VALIDATION
    assert service.submits == []
    assert "s0ma feedback drafts" in output


# ---------------------------------------------------------------------------
# drafts
# ---------------------------------------------------------------------------


def test_drafts_lists_what_is_waiting(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "n"])
    assert run(cli, ["feedback"], capsys)[0] == fb.EXIT_DECLINED
    draft = list_drafts()[0]

    code, output = run(cli, ["feedback", "drafts"], capsys)

    assert code == fb.EXIT_SENT
    assert draft.draft_id in output
    assert SUMMARY[:60] in output
    assert "s0ma feedback submit <draft-id>" in output


def test_drafts_on_a_clean_machine_says_so(
    cli: S0maCLI, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = run(cli, ["feedback", "drafts"], capsys)
    assert code == fb.EXIT_SENT
    assert "no unsent feedback reports" in output


def test_drafts_purges_expired_reports(
    cli: S0maCLI, capsys: pytest.CaptureFixture[str]
) -> None:
    from s0ma_dsl.feedback.drafts import DRAFT_TTL_DAYS, save_draft

    envelope = FeedbackEnvelope(category="bug", impact="minor", summary=SUMMARY)
    old = save_draft(envelope, created_ts=NOW - (DRAFT_TTL_DAYS + 1) * 86_400_000)

    code, output = run(cli, ["feedback", "drafts"], capsys)

    assert code == fb.EXIT_SENT
    assert old.draft_id not in output
    assert load_draft(old.draft_id) is None


# ---------------------------------------------------------------------------
# list (A-3, contract r4 item 3)
# ---------------------------------------------------------------------------


def test_list_shows_the_reports_the_service_returned(
    cli: S0maCLI, service: _Service, capsys: pytest.CaptureFixture[str]
) -> None:
    service.list_result = FeedbackResult(ok=True, reports=rows(3))
    code, output = run(cli, ["feedback", "list"], capsys)

    assert code == fb.EXIT_SENT
    assert "3 feedback reports" in output
    for row in rows(3):
        assert row.feedback_id in output
    assert "s0ma feedback delete <report-id>" in output


def test_list_with_nothing_on_file_says_so(
    cli: S0maCLI, service: _Service, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = run(cli, ["feedback", "list"], capsys)
    assert code == fb.EXIT_SENT
    assert "no feedback reports on file" in output


def test_list_falls_back_to_this_machines_record_when_offline(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "", "y"])
    assert run(cli, ["feedback"], capsys)[0] == fb.EXIT_SENT

    service.list_result = failure("NETWORK_UNREACHABLE")
    code, output = run(cli, ["feedback", "list"], capsys)

    assert code == fb.EXIT_SENT
    assert "recorded on this machine" in output
    assert "fb_0001" in output
    assert "Code: NETWORK_UNREACHABLE" in output


def test_list_does_not_pretend_an_auth_failure_is_offline(
    cli: S0maCLI, service: _Service, capsys: pytest.CaptureFixture[str]
) -> None:
    service.list_result = failure("INVALID_TOKEN")
    code, output = run(cli, ["feedback", "list"], capsys)

    assert code == fb.EXIT_AUTH
    assert "recorded on this machine" not in output
    assert "s0ma feedback enroll" in output


# ---------------------------------------------------------------------------
# delete (A-3)
# ---------------------------------------------------------------------------


def test_bare_delete_deletes_nothing(
    cli: S0maCLI, service: _Service, capsys: pytest.CaptureFixture[str]
) -> None:
    service.list_result = FeedbackResult(ok=True, reports=rows(2))
    code, output = run(cli, ["feedback", "delete"], capsys)

    assert code == fb.EXIT_VALIDATION
    assert service.deletes == []
    assert "does not delete anything" in output
    assert "fb_0001" in output  # the list is shown
    assert "s0ma feedback delete <report-id>" in output
    assert "s0ma feedback delete --all" in output


def test_deleting_one_report_needs_no_confirmation(
    cli: S0maCLI, service: _Service, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = run(cli, ["feedback", "delete", "fb_0007"], capsys)

    assert code == fb.EXIT_SENT
    assert service.deletes == ["fb_0007"]
    assert "fb_0007 was deleted" in output


def test_deleting_an_unknown_report_reports_the_service_answer(
    cli: S0maCLI, service: _Service, capsys: pytest.CaptureFixture[str]
) -> None:
    service.delete_results = [failure("NOT_FOUND")]
    code, output = run(cli, ["feedback", "delete", "fb_nope"], capsys)

    assert code == fb.EXIT_FAILED
    assert "Code: NOT_FOUND" in output


def test_an_id_and_all_together_is_refused(
    cli: S0maCLI, service: _Service, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = run(cli, ["feedback", "delete", "fb_0001", "--all"], capsys)

    assert code == fb.EXIT_VALIDATION
    assert service.deletes == []
    assert "not both" in output


def test_delete_all_asks_the_verbatim_question_then_deletes(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service.list_result = FeedbackResult(ok=True, reports=rows(3))
    terminal(monkeypatch, ["y"])
    code, output = run(cli, ["feedback", "delete", "--all"], capsys)

    assert code == fb.EXIT_SENT
    assert "Delete all 3 feedback reports? [y/N]" in output
    assert service.deletes == ["fb_0001", "fb_0002", "fb_0003"]
    assert "Deleted 3 feedback reports." in output


def test_delete_all_declined_deletes_nothing(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service.list_result = FeedbackResult(ok=True, reports=rows(2))
    terminal(monkeypatch, ["n"])
    code, output = run(cli, ["feedback", "delete", "--all"], capsys)

    assert code == fb.EXIT_DECLINED
    assert service.deletes == []
    assert "Nothing was deleted." in output


def test_delete_all_stops_gracefully_when_rate_limited(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Contract r4 item 7: report progress and when to retry — never loop."""
    service.list_result = FeedbackResult(ok=True, reports=rows(5))
    service.delete_results = [
        FeedbackResult(ok=True, feedback_id="fb_0001"),
        FeedbackResult(ok=True, feedback_id="fb_0002"),
        failure("RATE_LIMITED", status_code=429, retry_after=1800),
    ]
    terminal(monkeypatch, ["y"])
    code, output = run(cli, ["feedback", "delete", "--all"], capsys)

    assert code == fb.EXIT_FAILED
    # It stopped at the refusal: three attempts, not five.
    assert service.deletes == ["fb_0001", "fb_0002", "fb_0003"]
    assert "Deleted so far   2" in output
    assert "Still to delete  3" in output
    assert "in about 30 minutes" in output
    assert "Code: RATE_LIMITED" in output


def test_delete_all_without_a_retry_after_still_says_when(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service.list_result = FeedbackResult(ok=True, reports=rows(2))
    service.delete_results = [failure("RATE_LIMITED", status_code=429)]
    terminal(monkeypatch, ["y"])
    code, output = run(cli, ["feedback", "delete", "--all"], capsys)

    assert code == fb.EXIT_FAILED
    assert "in about an hour" in output


def test_delete_all_treats_an_already_deleted_report_as_gone(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service.list_result = FeedbackResult(ok=True, reports=rows(2))
    service.delete_results = [
        failure("NOT_FOUND"),
        FeedbackResult(ok=True, feedback_id="fb_0002"),
    ]
    terminal(monkeypatch, ["y"])
    code, output = run(cli, ["feedback", "delete", "--all"], capsys)

    assert code == fb.EXIT_SENT
    assert service.deletes == ["fb_0001", "fb_0002"]
    assert "already been deleted" in output


def test_delete_all_with_nothing_on_file_says_so(
    cli: S0maCLI,
    service: _Service,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal(monkeypatch, ["y"])
    code, output = run(cli, ["feedback", "delete", "--all"], capsys)

    assert code == fb.EXIT_SENT
    assert service.deletes == []
    assert "no feedback reports to delete" in output


# ---------------------------------------------------------------------------
# enroll (FD-4)
# ---------------------------------------------------------------------------


@pytest.fixture
def exchange(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the keys handed to the exchange; answer with a stored token."""
    keys: list[str] = []

    def fake_exchange(license_key: str, **kwargs: Any) -> FeedbackResult:
        del kwargs
        keys.append(license_key)
        if not license_key.strip():
            return FeedbackResult(
                ok=False,
                code="BAD_REQUEST",
                message="No license key was supplied, so there was nothing to enroll with.",
                remediation="Pass your s0ma license key with `--key`, or set S0MA_LICENSE_KEY.",
            )
        return FeedbackResult(
            ok=True,
            token=StoredToken(
                token="s0ma_fb_abcdefghijklmnop",
                token_prefix="s0ma_fb_abcd",
                expires_ts=NOW,
                cp_host="account.kn0wthyself.ai",
            ),
        )

    monkeypatch.setattr(feedback_tokens, "exchange", fake_exchange)
    return keys


def test_enroll_uses_the_key_flag_and_shows_the_token_once(
    cli: S0maCLI, exchange: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = run(cli, ["feedback", "enroll", "--key", "s0ma_lic_test"], capsys)

    assert code == fb.EXIT_SENT
    assert exchange == ["s0ma_lic_test"]
    assert "s0ma_fb_abcdefghijklmnop" in output  # the one-time echo
    assert "s0ma_fb_abcd" in output  # the short name it is known by afterwards
    assert "shown once" in output
    assert "~/.s0ma/feedback-token" in output
    assert "2026-08-27" in output  # the expiry, as a date
    assert "s0ma_lic_test" not in output  # the license key is never echoed


def test_enroll_falls_back_to_the_environment(
    cli: S0maCLI,
    exchange: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("S0MA_LICENSE_KEY", "s0ma_lic_env")
    code, _ = run(cli, ["feedback", "enroll"], capsys)

    assert code == fb.EXIT_SENT
    assert exchange == ["s0ma_lic_env"]


def test_enroll_without_a_key_refuses_and_says_how(
    cli: S0maCLI, exchange: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = run(cli, ["feedback", "enroll"], capsys)

    assert code == fb.EXIT_VALIDATION
    assert "S0MA_LICENSE_KEY" in output
    assert "Code: BAD_REQUEST" in output


def test_enroll_reports_a_refused_account(
    cli: S0maCLI, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        feedback_tokens,
        "exchange",
        lambda key, **kwargs: failure("NOT_ENTITLED"),  # noqa: ARG005 - signature match
    )
    code, output = run(cli, ["feedback", "enroll", "--key", "s0ma_lic_test"], capsys)

    assert code == fb.EXIT_AUTH
    assert "Code: NOT_ENTITLED" in output


def test_enroll_is_the_real_engine_call_by_default(
    cli: S0maCLI, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty key is answered locally: the engine never opens a socket."""
    code, output = run(cli, ["feedback", "enroll"], capsys)
    assert code == fb.EXIT_VALIDATION
    assert "license key" in output.lower()


# ---------------------------------------------------------------------------
# Non-TTY refusals (plan §5.9: no silent submission)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["feedback"],
        ["feedback", "--message", SUMMARY],
        ["feedback", "-m", SUMMARY],
        ["feedback", "-m", SUMMARY, "-c", "bug", "-i", "blocked"],
        ["feedback", "submit", "fbd_1a2b3c4d"],
        ["feedback", "delete", "--all"],
    ],
)
def test_the_approval_commands_refuse_without_a_terminal(
    cli: S0maCLI, service: _Service, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = run(cli, argv, capsys)

    assert code == fb.EXIT_VALIDATION
    assert service.submits == []
    assert service.deletes == []
    assert "needs a terminal" in output
    assert "No flag skips the approval step" in output


@pytest.mark.parametrize(
    "argv",
    [
        ["feedback", "drafts"],
        ["feedback", "list"],
        ["feedback", "delete", "fb_0001"],
        ["feedback", "enroll", "--key", "s0ma_lic_test"],
    ],
)
def test_the_reading_commands_work_without_a_terminal(
    cli: S0maCLI,
    service: _Service,
    exchange: list[str],
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output = run(cli, argv, capsys)

    assert code == fb.EXIT_SENT
    assert "needs a terminal" not in output


# ---------------------------------------------------------------------------
# Contract §12/A-2 — voice
# ---------------------------------------------------------------------------


def _voice_transcripts(
    cli: S0maCLI,
    service: _Service,
    exchange: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> list[str]:
    """Everything a reader can be shown, across every path this family has."""
    transcripts = [feedback_help(cli, capsys)]

    service.list_result = FeedbackResult(ok=True, reports=rows(2))
    for argv in (
        ["feedback", "drafts"],
        ["feedback", "list"],
        ["feedback", "delete"],
        ["feedback", "delete", "fb_0001"],
        ["feedback", "enroll", "--key", "s0ma_lic_test"],
        ["feedback"],  # refused: no terminal
        ["feedback", "-m", SUMMARY, "-c", "banana"],  # refused: unknown kind
    ):
        transcripts.append(run(cli, argv, capsys)[1])

    # Offline listing, and a listing that fails on auth.
    service.list_result = failure("NETWORK_UNREACHABLE")
    transcripts.append(run(cli, ["feedback", "list"], capsys)[1])
    service.list_result = failure("INVALID_TOKEN")
    transcripts.append(run(cli, ["feedback", "list"], capsys)[1])
    service.list_result = FeedbackResult(ok=True, reports=rows(2))

    # A full compose that is declined, then resumed, failed, and sent.
    terminal(monkeypatch, [*COMPOSE_MINIMAL, "y", "n"])
    transcripts.append(run(cli, ["feedback"], capsys)[1])
    draft = list_drafts()[0]

    service.submit_results = [failure("PAYLOAD_TOO_LARGE")]
    terminal(monkeypatch, ["y"])
    transcripts.append(run(cli, ["feedback", "submit", draft.draft_id], capsys)[1])

    service.submit_results = [failure("TIMEOUT")]
    terminal(monkeypatch, ["y"])
    transcripts.append(run(cli, ["feedback", "submit", draft.draft_id], capsys)[1])

    terminal(monkeypatch, ["y"])
    transcripts.append(run(cli, ["feedback", "submit", draft.draft_id], capsys)[1])

    # The bulk path, refused part way through.
    service.delete_results = [failure("RATE_LIMITED", retry_after=600)]
    terminal(monkeypatch, ["y"])
    transcripts.append(run(cli, ["feedback", "delete", "--all"], capsys)[1])

    # The F-1 fast path, sent: the shortest route to the most copy.
    terminal(monkeypatch, ["y", "y"])
    transcripts.append(run(cli, ["feedback", "-m", SUMMARY], capsys)[1])

    return transcripts


def test_no_user_facing_string_ever_says_payload(
    cli: S0maCLI,
    service: _Service,
    exchange: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§12/A-2: it is "feedback data" or "feedback report", never that word.

    Technical identifiers are exempt, so the ``PAYLOAD_TOO_LARGE`` *code* is
    allowed through — it is a code, printed as one, not prose.
    """
    transcripts = _voice_transcripts(cli, service, exchange, monkeypatch, capsys)
    assert len(transcripts) == 16
    for transcript in transcripts:
        # A sweep over nothing would pass; every path must have spoken.
        assert len(transcript) > 40, transcript
        cleaned = transcript.replace("PAYLOAD_TOO_LARGE", "")
        assert "payload" not in cleaned.lower(), transcript


def test_no_user_facing_string_ever_claims_anonymity(
    cli: S0maCLI,
    service: _Service,
    exchange: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-FB-11: pseudonymous is claimed; anonymous is never claimed."""
    for transcript in _voice_transcripts(cli, service, exchange, monkeypatch, capsys):
        lowered = transcript.lower()
        if "anonymous" in lowered:
            assert "pseudonymous, not anonymous" in lowered, transcript
