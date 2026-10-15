"""FB-M5: redaction profile v1 — the ten rules, in the frozen order.

The adversarial corpus in ``fixtures/feedback_redaction_corpus.jsonl`` is the
executable definition of contract §7. Each record pins one input, its exact
redacted output, and exactly what was removed; the property tests then hold
the whole corpus to three rules that no record may break:

* every §7 pattern finds **zero** residue in the output (rule 3's kept name
  is the one contract-mandated exception, checked precisely rather than
  waived);
* redacting the output again is a fixed point that removes nothing;
* no placeholder is ever spelled differently from the frozen spellings the
  control plane neutralizes.

If a corpus expectation needs editing, the profile changed and the contract
needs a §13 re-freeze — not a new expected string.
"""

from __future__ import annotations

import importlib
import json
import re
import time
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.feedback.model import (
    DETAILS_MAX_CHARS,
    REPRODUCTION_MAX_STEPS,
    REPRODUCTION_STEP_MAX_CHARS,
    SUMMARY_MAX_CHARS,
    FeedbackEnvelope,
    FeedbackPrivacy,
    validate_payload,
)
from s0ma_dsl.feedback.redact import (
    COUNT_KEYS,
    ENTROPY_MIN_BITS,
    ENTROPY_MIN_CHARS,
    PLACEHOLDER_PATTERN,
    POSIX_PATH_ROOTS,
    REDACTED_TEXT_FIELDS,
    REDACTION_PROFILE,
    neutralize,
    redact,
    redact_envelope,
    shannon_entropy,
)

#: The module object. ``s0ma_dsl.feedback.redact`` resolves to the *function*
#: through the package's curated surface, so the module is fetched by name.
redact_module = importlib.import_module("s0ma_dsl.feedback.redact")

#: The identity every corpus record is redacted against, so the machine
#: running the suite cannot change an expectation.
USER = "alice"
HOST = "dev-box.local"

CORPUS_PATH = Path(__file__).parent / "fixtures" / "feedback_redaction_corpus.jsonl"


def _load_corpus() -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records, "the adversarial corpus is the executable definition of §7"
    return records


CORPUS = _load_corpus()
CORPUS_IDS = [str(record["name"]) for record in CORPUS]


def _redact_record(record: dict[str, Any]) -> tuple[str, dict[str, int]]:
    return redact(
        str(record["text"]),
        username=USER,
        hostname=HOST,
        keep_basename=bool(record["keep_basename"]),
    )


# ---------------------------------------------------------------------------
# Contract §7, transcribed — the independent detectors the property tests use
#
# These are the contract's own patterns, written here from the contract text
# rather than imported from the implementation, so a test failure means the
# profile drifted rather than that a constant was renamed. Rule 3's regex is
# the UNWRAPPED form given in §7.1.
# ---------------------------------------------------------------------------

RULE_1 = re.compile(r"s0ma_test_[A-Za-z0-9_-]+|s0ma_fb_[A-Za-z0-9_-]+")

RULE_2 = re.compile(
    r"AKIA[0-9A-Z]{16}"
    r"|ghp_[A-Za-z0-9]{36,}"
    r"|github_pat_\w+"
    r"|sk-[A-Za-z0-9_-]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]+"
    r"|Bearer\s+\S{16,}"
    r"|-----BEGIN [A-Z ]*KEY-----"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
)

#: Rule 3 as re-frozen in contract revision r5 — the prefix before the
#: keyword is optional. (r1's leading ``[A-Z]`` consumed the keyword's own
#: first letter, so ``PASSWORD=hunter2`` was never caught.)
RULE_3 = re.compile(
    r"\b(?:[A-Z][A-Z0-9_]*)?(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*\s*=\s*\S+"
)

RULE_4 = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")

RULE_5 = re.compile(r"(?:https?|ssh|ftp|file|git)://\S+|git@[\w.-]+:\S+")

RULE_6 = re.compile(
    r"/Users/\S+|/home/\S+|/private/\S+|[A-Za-z]:\\\S+|\\\\\S+"
)

RULE_8 = re.compile(
    r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
    r"|(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}"
)

RULE_9_CANDIDATE = re.compile(rf"[A-Za-z0-9+/=_-]{{{ENTROPY_MIN_CHARS},}}")

RULE_10 = re.compile(
    r"File \"[^\"\n]*\", line \d+|\bat +\S* *\([^)\n]*:\d+:\d+\)|\bat +\S+:\d+:\d+"
)

PLACEHOLDER_RE = re.compile(PLACEHOLDER_PATTERN)


def _rule_7_hits(text: str) -> list[str]:
    """The username as a standalone token, outside any placeholder."""
    pattern = re.compile(rf"(?<![\w.-]){re.escape(USER)}(?![\w-])")
    spans = [match.span() for match in PLACEHOLDER_RE.finditer(text)]
    return [
        match.group(0)
        for match in pattern.finditer(text)
        if not any(start <= match.start() and match.end() <= end for start, end in spans)
    ]


def _rule_9_hits(text: str) -> list[str]:
    """High-entropy runs that are not already a placeholder (§7 rule 9)."""
    spans = [match.span() for match in PLACEHOLDER_RE.finditer(text)]
    return [
        match.group(0)
        for match in RULE_9_CANDIDATE.finditer(text)
        if shannon_entropy(match.group(0)) >= ENTROPY_MIN_BITS
        and not any(start <= match.start() and match.end() <= end for start, end in spans)
    ]


def _rule_3_hits(text: str) -> list[str]:
    """Assignments whose value survived.

    §7 keeps the variable's name, so the pattern still matches its own
    output. What may never survive is a *value* other than the placeholder.
    """
    return [
        match.group(0)
        for match in RULE_3.finditer(text)
        if match.group(0).split("=")[-1].strip() != redact_module.SECRET_PLACEHOLDER
    ]


def residues(text: str) -> dict[int, list[str]]:
    """Every §7 rule that still finds something in *text*."""
    found: dict[int, list[str]] = {}
    for number, pattern in ((1, RULE_1), (2, RULE_2), (4, RULE_4), (5, RULE_5),
                            (6, RULE_6), (8, RULE_8), (10, RULE_10)):
        hits = pattern.findall(text)
        if hits:
            found[number] = [hit if isinstance(hit, str) else str(hit) for hit in hits]
    for number, hits in ((3, _rule_3_hits(text)), (7, _rule_7_hits(text)),
                         (9, _rule_9_hits(text))):
        if hits:
            found[number] = hits
    return found


# ---------------------------------------------------------------------------
# The corpus: exact outputs, exact counts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("record", CORPUS, ids=CORPUS_IDS)
def test_corpus_output_is_exact(record: dict[str, Any]) -> None:
    text, _ = _redact_record(record)
    assert text == record["redacted"], record["note"]


@pytest.mark.parametrize("record", CORPUS, ids=CORPUS_IDS)
def test_corpus_counts_are_exact(record: dict[str, Any]) -> None:
    _, counts = _redact_record(record)
    assert counts == record["counts"], record["note"]
    assert set(counts) <= set(COUNT_KEYS)
    assert all(count > 0 for count in counts.values()), "a type that removed nothing is absent"


@pytest.mark.parametrize("record", CORPUS, ids=CORPUS_IDS)
def test_corpus_leaves_no_rule_with_anything_to_find(record: dict[str, Any]) -> None:
    text, _ = _redact_record(record)
    assert residues(text) == {}


@pytest.mark.parametrize("record", CORPUS, ids=CORPUS_IDS)
def test_corpus_is_idempotent(record: dict[str, Any]) -> None:
    text, _ = _redact_record(record)
    again, counts = redact(
        text, username=USER, hostname=HOST, keep_basename=bool(record["keep_basename"])
    )
    assert again == text
    assert counts == {}


@pytest.mark.parametrize("record", CORPUS, ids=CORPUS_IDS)
def test_corpus_emits_only_frozen_placeholder_spellings(record: dict[str, Any]) -> None:
    text, _ = _redact_record(record)
    for angle in re.finditer(r"<[A-Z][A-Za-z0-9_.:+-]*>", text):
        assert PLACEHOLDER_RE.fullmatch(angle.group(0)), angle.group(0)


def test_the_corpus_covers_every_rule_and_both_s0ma_prefixes() -> None:
    """The corpus is the definition; a rule with no record is untested."""
    names = {str(record["name"]) for record in CORPUS}
    texts = " ".join(str(record["text"]) for record in CORPUS)
    outputs = " ".join(str(record["redacted"]) for record in CORPUS)
    assert len(names) == len(CORPUS), "corpus names are unique"
    for prefix in ("s0ma_test_", "s0ma_fb_"):
        assert prefix in texts
    for shape in ("AKIA", "ghp_", "github_pat_", "xox", "sk-", "eyJ", "Bearer ",
                  "-----BEGIN", "@", "https://", "git@", "/Users/", "/home/",
                  "/private/", "C:\\", "\\\\", ":\\", "\r\n"):
        assert shape in texts, shape
    for placeholder in ("<SECRET_REDACTED>", "<EMAIL_1>", "<URL_1>", "<PATH_1>",
                        "<PATH_1:main.s0ma>", "<USER>", "<HOST_ID_1>", "<TRACE_FRAME>"):
        assert placeholder in outputs, placeholder


# ---------------------------------------------------------------------------
# Rule 3 — the one place a §7 pattern still matches the output
# ---------------------------------------------------------------------------


def test_rule_three_keeps_the_name_which_keeps_the_pattern_alive() -> None:
    """§7 keeps the variable name, so §7's own regex matches the output.

    That is the contract's intent — the reader needs to know *which*
    setting was removed — and it is why the control plane's detection port
    neutralizes the placeholders before screening (contract r4 ruling 6).
    Only the value is guaranteed gone.
    """
    text, counts = redact("DB_PASSWORD=hunter2", username=USER, hostname=HOST)
    assert text == "DB_PASSWORD=<SECRET_REDACTED>"
    assert counts == {"secrets": 1}
    assert RULE_3.search(text) is not None
    assert _rule_3_hits(text) == []
    assert "hunter2" not in text


def test_rule_three_catches_a_name_that_is_itself_the_keyword() -> None:
    """Contract r5's re-freeze, asserted from both sides.

    r1's pattern opened with ``[A-Z]``, which consumed the keyword's own
    first letter, so a variable named exactly the keyword escaped rule 3 —
    and, at low entropy, rule 9 as well. r5 makes the prefix optional. The
    name is still kept: the reader needs to know *which* setting was
    removed.
    """
    for assignment, name in (
        ("PASSWORD=hunter2", "PASSWORD"),
        ("TOKEN=abc", "TOKEN"),
        ("KEY=abc", "KEY"),
        ("SECRET=abc", "SECRET"),
        ("CREDENTIAL=abc", "CREDENTIAL"),
        ("KEYS=abc", "KEYS"),
        ("TOKEN_VALUE=abc", "TOKEN_VALUE"),
        ("DB_PASSWORD=hunter2", "DB_PASSWORD"),
        ("API_KEY=abc", "API_KEY"),
        ("XTOKEN=abc", "XTOKEN"),
        ("S0MA_FEEDBACK_TOKEN=abc", "S0MA_FEEDBACK_TOKEN"),
    ):
        assert RULE_3.search(assignment) is not None, assignment
        text, counts = redact(assignment, username=USER, hostname=HOST)
        assert text == f"{name}=<SECRET_REDACTED>", assignment
        assert counts == {"secrets": 1}
        assert redact(text, username=USER, hostname=HOST) == (text, {}), "r5 stays idempotent"


def test_rule_three_still_needs_an_uppercase_name_and_a_secret_word() -> None:
    """r5 widened the name, it did not open it: the bounds still hold."""
    for untouched in ("api_key=hunter2", "MAX_RETRIES=5", "password=hunter2", "Key=abc"):
        assert redact(untouched, username=USER, hostname=HOST) == (untouched, {})


def test_rule_five_collapses_a_url_whose_host_rule_four_already_took() -> None:
    """A URL is one token, even when an earlier rule redacted part of it."""
    text, counts = redact("ssh://git@example.com/org/repo.git", username=USER, hostname=HOST)
    assert text == "<URL_1>", "no scheme and no repository path may be left behind"
    assert counts == {"emails": 1, "urls": 1}, "two removals, one placeholder"

    bracketed, _ = redact(
        "see <https://kn0wthyself.ai/docs> for more", username=USER, hostname=HOST
    )
    assert bracketed == "see <<URL_1>> for more", "brackets that are not a placeholder stay"


def test_neutralized_output_is_what_the_control_plane_screens() -> None:
    """:func:`neutralize` substitutes for exactly the frozen spellings.

    Contract r5 ruling 3 makes substitution binding: a *deleted* placeholder
    would leave ``NAME=`` and let rule 3's ``\\S+`` bind the following word,
    refusing correctly redacted text. The marker is non-space so nothing can
    reach across it, and the ``<PATH_n:basename>`` form is recognized too.
    """
    text, _ = redact(
        "mail rob@example.com from /Users/alice/a/x.py with AKIAIOSFODNN7EXAMPLE",
        username=USER,
        hostname=HOST,
        keep_basename=True,
    )
    assert text == "mail <EMAIL_1> from <PATH_1:x.py> with <SECRET_REDACTED>"
    assert neutralize(text) == "mail ~ from ~ with ~"
    assert neutralize(text, "·").count("·") == 3
    assert redact_module.NEUTRAL_MARKER.strip() == redact_module.NEUTRAL_MARKER != ""

    assignment, _ = redact("DB_PASSWORD=hunter2", username=USER, hostname=HOST)
    assert neutralize(assignment) == "DB_PASSWORD=~", "no gap for \\S+ to reach across"


# ---------------------------------------------------------------------------
# Numbering policy
# ---------------------------------------------------------------------------


def test_the_same_value_keeps_the_same_placeholder() -> None:
    text, counts = redact(
        "/Users/alice/a and /home/alice/b and /Users/alice/a",
        username=USER,
        hostname=HOST,
    )
    assert text == "<PATH_1> and <PATH_2> and <PATH_1>"
    assert counts == {"paths": 3}, "numbering counts distinct values, counts count removals"


def test_numbering_is_per_type() -> None:
    text, _ = redact(
        "rob@example.com https://a.dev/x /Users/alice/a bob@example.org "
        "https://b.dev/y /home/alice/b",
        username=USER,
        hostname=HOST,
    )
    assert text == "<EMAIL_1> <URL_1> <PATH_1> <EMAIL_2> <URL_2> <PATH_2>"


def test_numbering_continues_past_placeholders_already_in_the_text() -> None:
    text, counts = redact(
        "old <PATH_3> and new /Users/alice/a", username=USER, hostname=HOST
    )
    assert text == "old <PATH_3> and new <PATH_4>"
    assert counts == {"paths": 1}


def test_numbering_runs_across_the_whole_envelope_in_field_order() -> None:
    envelope = FeedbackEnvelope(
        category="bug",
        impact="degraded",
        summary="build failed for /Users/alice/p/a.s0ma",
        expected="it should compile /Users/alice/p/a.s0ma",
        actual="crashed instead; mail rob@example.com",
        details="second path /home/alice/q",
        reproduction=("run s0ma build /private/tmp/x", "open /Users/alice/p/a.s0ma"),
    )
    redacted, counts = redact_envelope(envelope, username=USER, hostname=HOST)
    assert redacted.summary == "build failed for <PATH_1>"
    assert redacted.expected == "it should compile <PATH_1>"
    assert redacted.actual == "crashed instead; mail <EMAIL_1>"
    assert redacted.details == "second path <PATH_2>"
    assert redacted.reproduction == ("run s0ma build <PATH_3>", "open <PATH_1>")
    assert counts == {"emails": 1, "paths": 5}


def test_reproduction_steps_are_walked_in_index_order() -> None:
    envelope = FeedbackEnvelope(
        category="bug",
        impact="minor",
        summary="steps leak paths",
        reproduction=("first /home/alice/one", "then /home/alice/two", "again /home/alice/one"),
    )
    redacted, counts = redact_envelope(envelope, username=USER, hostname=HOST)
    assert redacted.reproduction == ("first <PATH_1>", "then <PATH_2>", "again <PATH_1>")
    assert counts == {"paths": 3}


# ---------------------------------------------------------------------------
# The envelope: what is redacted, what is left alone, and the privacy block
# ---------------------------------------------------------------------------


def test_redact_envelope_leaves_everything_that_is_not_free_text_alone() -> None:
    envelope = FeedbackEnvelope(
        category="privacy_or_trust",
        impact="blocked",
        summary="secret s0ma_fb_abc123",
        context={"os": "macos", "pseudonym": "a" * 32, "cohort": "beta"},
    )
    redacted, _ = redact_envelope(envelope, username=USER, hostname=HOST)
    assert redacted.category == envelope.category
    assert redacted.impact == envelope.impact
    assert redacted.schema == envelope.schema
    assert redacted.context == envelope.context, "the context is built, not typed — §5 guards it"
    assert redacted.summary == "secret <SECRET_REDACTED>"


def test_redact_envelope_writes_the_counts_into_the_privacy_block() -> None:
    envelope = FeedbackEnvelope(
        category="bug",
        impact="minor",
        summary="mail rob@example.com about /Users/alice/a",
    )
    redacted, counts = redact_envelope(envelope, username=USER, hostname=HOST)
    assert redacted.privacy is not None
    assert redacted.privacy.redacted == counts == {"emails": 1, "paths": 1}
    assert redacted.privacy.profile == "metadata_only"
    assert redacted.privacy.includes_source is False
    assert redacted.privacy.includes_transcript is False


def test_redact_envelope_merges_over_counts_the_envelope_already_carried() -> None:
    envelope = FeedbackEnvelope(
        category="bug",
        impact="minor",
        summary="already <PATH_1>, now also rob@example.com",
        privacy=FeedbackPrivacy(redacted={"paths": 1}),
    )
    redacted, counts = redact_envelope(envelope, username=USER, hostname=HOST)
    assert counts == {"emails": 1, "paths": 1}
    assert redacted.privacy is not None
    assert redacted.privacy.redacted == {"emails": 1, "paths": 1}


def test_redact_envelope_is_exactly_idempotent() -> None:
    envelope = FeedbackEnvelope(
        category="bug",
        impact="degraded",
        summary="token s0ma_fb_abc123 for rob@example.com",
        expected="a clean build of /Users/alice/p/a.s0ma",
        actual='  File "/Users/alice/p/app.py", line 42, in <module>',
        details="host dev-box.local, id 3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        reproduction=("run s0ma build /home/alice/p",),
    )
    once, first = redact_envelope(envelope, username=USER, hostname=HOST)
    twice, second = redact_envelope(once, username=USER, hostname=HOST)
    assert twice == once
    assert second == first


def test_the_redaction_report_is_a_shape_the_envelope_validator_accepts() -> None:
    envelope = FeedbackEnvelope(
        category="bug",
        impact="minor",
        summary="mail rob@example.com from /Users/alice/a",
    )
    redacted, _ = redact_envelope(envelope, username=USER, hostname=HOST)
    assert validate_payload(redacted.to_payload()) == ()


def test_redacted_text_fields_are_the_contract_field_order() -> None:
    assert REDACTED_TEXT_FIELDS == (
        "summary",
        "expected",
        "actual",
        "details",
        "reproduction",
    )


# ---------------------------------------------------------------------------
# False-positive bounds
# ---------------------------------------------------------------------------

#: Ordinary writing a feedback report is made of. Redaction may not touch a
#: single character of it.
BENIGN = (
    "the word feedback",
    "s0ma check named the rule but not the declaration to edit",
    "validate_payload returned SCHEMA_INVALID",
    "test_redaction_of_absolute_paths",
    "version 0.19.0 and 1.2.3-rc.1",
    "MAX_RETRIES=5",
    "and/or, either/or",
    "POST /api/feedback returned 500",
    "run `s0ma build` in the project root",
    "a UUID-shaped word is not a UUID",
    "sha256:70265543186546875ad5b349b0ef581023add017b13c161fbac4d43597169d46",
    "abcdefghijklmnopqrs",
    "CamelCaseIdentifierName",
    "sk-short",
    "Bearer with a short one",
    "alicia, malice, and unalike",
    "https and ssh are schemes",
    "/usr/local/bin/s0ma",
    "an em dash — and a curly quote ’ survive",
    "日本語のテキストもそのまま",
)


@pytest.mark.parametrize("text", BENIGN)
def test_benign_text_passes_through_unchanged(text: str) -> None:
    assert redact(text, username=USER, hostname=HOST) == (text, {})


@pytest.mark.parametrize(
    "identifier",
    [
        "a" * length + "bcdefghijklmnopqrs"[: 19 - length]
        for length in (1, 5, 10)
    ]
    + ["x" * 19, "abcdefghijklmnopqrs", "s0ma_dsl_feedback_x"],
)
def test_identifiers_of_nineteen_characters_or_fewer_survive_the_entropy_rule(
    identifier: str,
) -> None:
    assert len(identifier) <= 19
    assert redact(identifier, username=USER, hostname=HOST) == (identifier, {})


def test_the_entropy_threshold_is_out_of_reach_below_twenty_three_characters() -> None:
    """log2(n) caps a length-n string's entropy, so the bound is structural."""
    assert ENTROPY_MIN_CHARS == 20
    assert ENTROPY_MIN_BITS == 4.5
    assert shannon_entropy("abcdefghijklmnopqrst") == pytest.approx(4.3219, abs=1e-4)
    assert shannon_entropy("abcdefghijklmnopqrst") < ENTROPY_MIN_BITS
    assert shannon_entropy("Xq7Vn2Lp9Ws4Zk1Rt6Yc3Bd8Fg5Hj0Mn") >= ENTROPY_MIN_BITS
    assert shannon_entropy("") == 0.0
    assert shannon_entropy("aaaaaaaaaaaaaaaaaaaaaaaaaaaa") == 0.0


def test_a_hex_digest_can_never_reach_the_entropy_threshold() -> None:
    digest = "70265543186546875ad5b349b0ef581023add017b13c161fbac4d43597169d46"
    assert shannon_entropy(digest) < 4.0, "16 symbols cap hex at 4 bits per character"
    assert redact(digest, username=USER, hostname=HOST) == (digest, {})


def test_a_username_shorter_than_three_characters_is_left_alone() -> None:
    """A two-letter login name would shred ordinary prose."""
    text = "we do not redact the word so in this sentence"
    assert redact(text, username="so", hostname="") == (text, {})
    assert redact("bob ran it", username="bob", hostname="") == ("<USER> ran it", {"usernames": 1})


def test_an_absent_username_or_hostname_disables_its_rule() -> None:
    text = "alice on dev-box.local"
    assert redact(text, username="", hostname="") == (text, {})


# ---------------------------------------------------------------------------
# Rule 6's enumerated POSIX roots (the §7 reading this implementation pins)
# ---------------------------------------------------------------------------


def test_posix_path_matching_is_the_enumeration_contract_seven_gives() -> None:
    assert POSIX_PATH_ROOTS == ("Users", "home", "private")
    for root in POSIX_PATH_ROOTS:
        text, counts = redact(f"/{root}/alice/project/file.txt", username=USER, hostname=HOST)
        assert text == "<PATH_1>"
        assert counts == {"paths": 1}
    for kept in ("/usr/local/bin/s0ma", "/etc/hosts", "/api/feedback", "/var/log/build.log"):
        assert redact(kept, username=USER, hostname=HOST) == (kept, {})


def test_a_basename_is_kept_only_when_asked_for_and_safe() -> None:
    path = "/Users/alice/Projects/s0ma/main.s0ma"
    assert redact(path, username=USER, hostname=HOST) == ("<PATH_1>", {"paths": 1})
    assert redact(path, username=USER, hostname=HOST, keep_basename=True) == (
        "<PATH_1:main.s0ma>",
        {"paths": 1},
    )
    for unsafe in (
        "/Users/alice/tmp/alice.log",
        "/Users/alice/tmp/3f2504e0-4f89-11d3-9a0c-0305e82c3301.json",
        "/Users/alice/tmp/Xq7Vn2Lp9Ws4Zk1Rt6Yc3Bd8Fg5Hj0Mn.bin",
        "/Users/alice/tmp/dev-box.local",
    ):
        text, _ = redact(unsafe, username=USER, hostname=HOST, keep_basename=True)
        assert text == "<PATH_1>", unsafe


# ---------------------------------------------------------------------------
# The frozen order, where it decides the outcome
# ---------------------------------------------------------------------------


def test_rule_four_reaches_a_git_remote_before_rule_five_does() -> None:
    """The frozen order, asserted rather than worked around.

    ``git@github.com`` is email-shaped, and rule 4 precedes rule 5, so the
    host half becomes ``<EMAIL_1>``. The repository path is the residue —
    a consequence of the frozen order, recorded here so a future re-freeze
    can decide it deliberately.
    """
    text, counts = redact("git@github.com:kn0wthyself/s0ma.git", username=USER, hostname=HOST)
    assert text == "<EMAIL_1>:kn0wthyself/s0ma.git"
    assert counts == {"emails": 1}

    dotless, dotless_counts = redact(
        "git@localhost:kn0wthyself/s0ma.git", username=USER, hostname=HOST
    )
    assert dotless == "<URL_1>", "no dot, no email — rule 5 takes the whole remote"
    assert dotless_counts == {"urls": 1}


def test_rule_ten_collapses_over_the_path_rule_six_already_removed() -> None:
    text, counts = redact(
        '  File "/Users/alice/p/app.py", line 42, in <module>', username=USER, hostname=HOST
    )
    assert text == "  <TRACE_FRAME>"
    assert counts == {"paths": 1, "trace_frames": 1}, "both were removed, so both are counted"


def test_a_secret_inside_a_path_is_a_secret_first() -> None:
    text, counts = redact(
        "/Users/alice/tmp/ghp_abcdefghijklmnopqrstuvwxyz0123456789AB",
        username=USER,
        hostname=HOST,
    )
    assert text == "<PATH_1><SECRET_REDACTED>"
    assert counts == {"paths": 1, "secrets": 1}


# ---------------------------------------------------------------------------
# Machine facts (rules 7 and 8) default to this machine
# ---------------------------------------------------------------------------


def test_the_username_and_hostname_default_to_this_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redact_module, "local_username", lambda: "zaphod")
    monkeypatch.setattr(redact_module, "local_hostname", lambda: "heart-of-gold.local")
    text, counts = redact("zaphod on heart-of-gold.local")
    assert text == "<USER> on <HOST_ID_1>"
    assert counts == {"host_ids": 1, "usernames": 1}


def test_the_machine_facts_are_readable_without_raising() -> None:
    assert isinstance(redact_module.local_username(), str)
    assert isinstance(redact_module.local_hostname(), str)


# ---------------------------------------------------------------------------
# The freeze
# ---------------------------------------------------------------------------


def test_the_profile_is_v1_and_says_what_changing_it_costs() -> None:
    assert REDACTION_PROFILE == "v1"
    doc = redact_module.__doc__ or ""
    assert "re-freeze" in doc
    assert "frozen" in doc


def test_the_placeholder_spellings_are_byte_exact() -> None:
    """The control plane neutralizes these exact strings (r4 ruling 6)."""
    for placeholder in (
        "<SECRET_REDACTED>",
        "<EMAIL_1>",
        "<URL_12>",
        "<PATH_3>",
        "<PATH_3:main.s0ma>",
        "<USER>",
        "<HOST_ID_2>",
        "<TRACE_FRAME>",
    ):
        assert PLACEHOLDER_RE.fullmatch(placeholder), placeholder
    for wrong in ("<SECRET>", "[PATH_1]", "<path_1>", "<EMAIL>", "<HOST_ID>", "<USER_1>"):
        assert not PLACEHOLDER_RE.fullmatch(wrong), wrong


def test_the_count_keys_are_the_seven_placeholder_types() -> None:
    assert COUNT_KEYS == (
        "secrets",
        "emails",
        "urls",
        "paths",
        "usernames",
        "host_ids",
        "trace_frames",
    )


def test_the_public_surface_is_exported_from_the_package() -> None:
    from s0ma_dsl import feedback

    assert feedback.REDACTION_PROFILE == "v1"
    assert feedback.redact is redact
    assert feedback.redact_envelope is redact_envelope
    for name in ("REDACTION_PROFILE", "redact", "redact_envelope"):
        assert name in feedback.__all__


# ---------------------------------------------------------------------------
# Performance — the acceptance budget is 50 ms; the assertion is ten times
# looser so a loaded CI machine cannot make it flake.
# ---------------------------------------------------------------------------

PERFORMANCE_BUDGET_MS = 50.0
PERFORMANCE_CEILING_MS = 500.0

_CHUNK = (
    "The build failed at /Users/alice/Projects/s0ma/packages/main.s0ma line 12 "
    "after AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEX was set; "
    "mail rob@example.com or see https://kn0wthyself.ai/docs/feedback. "
    '  File "/Users/alice/p/app.py", line 42, in <module>\n'
    "    at Object.run (/home/alice/p/app.js:10:5)\n"
    "id 3f2504e0-4f89-11d3-9a0c-0305e82c3301 on dev-box.local blob "
    "Xq7Vn2Lp9Ws4Zk1Rt6Yc3Bd8Fg5Hj0Mn\n"
)


def _filler(size: int) -> str:
    return (_CHUNK * (size // len(_CHUNK) + 1))[:size]


def test_a_thirty_two_kilobyte_report_redacts_well_inside_the_budget() -> None:
    text = _filler(32768)
    assert len(text.encode("utf-8")) == 32768

    start = time.perf_counter()
    redacted, counts = redact(text, username=USER, hostname=HOST)
    elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\n32 KB redaction: {elapsed_ms:.1f} ms (budget {PERFORMANCE_BUDGET_MS:.0f} ms)")
    assert counts, "the timing sample must actually be doing work"
    assert residues(redacted) == {}
    assert elapsed_ms < PERFORMANCE_CEILING_MS, f"{elapsed_ms:.1f} ms"


def test_a_full_size_envelope_redacts_well_inside_the_budget() -> None:
    envelope = FeedbackEnvelope(
        category="bug",
        impact="degraded",
        summary=_filler(SUMMARY_MAX_CHARS),
        expected=_filler(2000),
        actual=_filler(2000),
        details=_filler(DETAILS_MAX_CHARS),
        reproduction=tuple(
            _filler(REPRODUCTION_STEP_MAX_CHARS) for _ in range(REPRODUCTION_MAX_STEPS)
        ),
    )
    start = time.perf_counter()
    redacted, counts = redact_envelope(envelope, username=USER, hostname=HOST, keep_basename=True)
    elapsed_ms = (time.perf_counter() - start) * 1000

    print(f"\nfull envelope redaction: {elapsed_ms:.1f} ms")
    assert counts
    assert residues(redacted.summary) == {}
    assert elapsed_ms < PERFORMANCE_CEILING_MS, f"{elapsed_ms:.1f} ms"


@pytest.mark.parametrize(
    "text",
    [
        "a." * 4000 + "@b.com",
        "A" * 20000,
        "/Users/" + "a/" * 5000,
        "-----BEGIN RSA PRIVATE KEY-----\n" + "x" * 2000,
        "\\\\" * 5000,
        "Bearer " + "x" * 5000,
        "K=" * 5000,
    ],
)
def test_pathological_shapes_do_not_hang_the_redactor(text: str) -> None:
    """No pattern may backtrack catastrophically on hostile input."""
    start = time.perf_counter()
    redact(text, username=USER, hostname=HOST)
    assert (time.perf_counter() - start) * 1000 < PERFORMANCE_CEILING_MS
